"""Populate the local SGU demo from published PDF timetable rows.

This is a research demonstration. Published week positions and operational
faculty ownership are not fully available; moved rows are explicitly counted.
Never use this command on a production database.
"""

import hashlib
import json
from collections import Counter, defaultdict, deque
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from analysis.sgu_public_demo import (DEMO_CYCLE, FACULTIES, PROGRAM_FACULTY,
                                      demo_class_code, faculty_for_row,
                                      parse_common_pdf, parse_specialized_pdf, usable)
from school.models import (Building, Cohort, Course, CourseGroup, CourseProgram,
                           Department, Faculty, GroupCohort, Lecturer, Period,
                           Program, Room, ScheduleEntry, ScheduleWeek, Semester,
                           TeachingQualification)


def _weeks(value):
    result = set()
    for part in value.split(","):
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            result.update(range(start, end + 1))
        else:
            result.add(int(part))
    return frozenset(result)


def _physical_key(row):
    return tuple(row[field] for field in (
        "course", "group", "lab", "employee", "day", "start", "duration", "room", "weeks_raw"))


def _occupied_keys(group_id, room_id, lecturer_id, cohort_ids, day, start, duration, weeks):
    resources = [("group", group_id), ("room", room_id), ("lecturer", lecturer_id)]
    resources.extend(("cohort", cohort_id) for cohort_id in cohort_ids)
    for kind, resource in resources:
        for week in weeks:
            for period in range(start, start + duration):
                yield kind, resource, week, day, period


class Command(BaseCommand):
    help = "Import traceable SGU public timetable demo rows into one existing semester."

    def add_arguments(self, parser):
        parser.add_argument("--semester-id", type=int, required=True)
        parser.add_argument("--source-dir", type=Path, default=Path("outputs/sgu_public_sources"))
        parser.add_argument("--report", type=Path, required=True)
        parser.add_argument("--apply", action="store_true", help="Commit changes; otherwise roll back")

    def handle(self, *args, **options):
        source_dir = options["source_dir"]
        manifest_path = source_dir / "source_manifest.json"
        if not manifest_path.exists():
            raise CommandError("Không có source_manifest.json")
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cache_path = source_dir / "parsed_rows_cache.json"
        source_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        if cache.get("source_manifest_sha256") == source_hash:
            raw = cache["rows"]
        else:
            raw = []
            for code in sorted(source_manifest["files"]):
                path = source_dir / f"{code}.pdf"
                raw.extend(parse_common_pdf(path) if code == "TKB_MONCHUNG"
                           else parse_specialized_pdf(path, code))
            cache_path.write_text(json.dumps({"source_manifest_sha256": source_hash, "rows": raw},
                                             ensure_ascii=False), encoding="utf-8")

        semester = Semester.objects.filter(pk=options["semester_id"]).first()
        if semester is None or semester.status == "DaKhoa":
            raise CommandError("Học kỳ không tồn tại hoặc đã khóa")
        if not semester.name.startswith("Học kỳ 1 - Năm học 2026 - 2027"):
            raise CommandError("Chỉ nhập vào học kỳ trình diễn HK1 2026–2027")
        if ScheduleEntry.objects.filter(group__semester=semester, source="SGUMoPhong").exists():
            raise CommandError("Đã có lịch SGUMoPhong; không nhập trùng")

        seen = set()
        candidates = []
        filtered = Counter()
        for row in raw:
            if not usable(row):
                filtered["thieu_truong_nguon"] += 1
                continue
            idx = faculty_for_row(row)
            if idx < 0:
                filtered["chua_anh_xa_khoa"] += 1
                continue
            if idx == 0:
                filtered["giu_nguyen_cntt"] += 1
                continue
            key = _physical_key(row)
            if key in seen:
                filtered["trung_dong_cong_khai"] += 1
                continue
            seen.add(key)
            candidates.append(row)

        try:
            with transaction.atomic():
                result = self._import(semester, candidates, source_manifest, filtered)
                if not options["apply"]:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f"Nhập lịch thất bại và đã hủy giao dịch: {exc}") from exc
        result.update({"mode": "apply" if options["apply"] else "dry_run",
                       "semester_id": semester.pk, "semester": semester.name,
                       "source_page": source_manifest["source_page"],
                       "source_manifest_sha256": source_hash,
                       "public_rows_read": len(raw), "candidate_rows": len(candidates)})
        options["report"].parent.mkdir(parents=True, exist_ok=True)
        options["report"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps({k: result[k] for k in (
            "mode", "candidate_rows", "imported", "moved", "skipped", "faculty_counts")}, ensure_ascii=False))

    def _import(self, semester, candidates, manifest, filtered):
        actor = get_user_model().objects.filter(is_staff=True, is_superuser=True).order_by("pk").first()
        if actor is None:
            actor = get_user_model().objects.filter(is_staff=True).order_by("pk").first()
        if actor is None:
            raise ValueError("Cần có tài khoản quản trị để ghi người phê duyệt bản mô phỏng")
        periods = {item.pk: item.block for item in Period.objects.all()}
        if not periods:
            raise ValueError("Chưa cấu hình tiết học")
        faculty_map = {}
        department_map = {}
        for index, name in enumerate(FACULTIES, 1):
            code = f"SGU_DEMO_K{index:02d}"
            faculty, _ = Faculty.objects.get_or_create(code=code, defaults={"name": name})
            department, _ = Department.objects.get_or_create(
                code=f"SGU_DEMO_B{index:02d}",
                defaults={"faculty": faculty, "name": f"Đơn vị mô phỏng {name}"})
            faculty_map[index - 1], department_map[index - 1] = faculty, department

        existing_courses = {item.code: item for item in Course.objects.all()}
        existing_lecturers = {item.employee_code: item for item in Lecturer.objects.all() if item.employee_code}
        existing_rooms = {item.code: item for item in Room.objects.select_related("building")}
        existing_groups = {(item.course.code, item.group, item.lab_group or ""): item for item in
                           CourseGroup.objects.filter(semester=semester).select_related("course")}
        protected_groups = set(ScheduleEntry.objects.filter(group__semester=semester)
                               .values_list("group_id", flat=True))
        existing_cohorts = {item.name: item for item in Cohort.objects.filter(semester=semester)}
        published_room_capacity = defaultdict(int)
        for row in candidates:
            published_room_capacity[row["room"]] = max(published_room_capacity[row["room"]], int(row["size"]))

        # Add source catalogs without changing the already approved CNTT records.
        for row in candidates:
            index, code = faculty_for_row(row), row["course"]
            if code not in existing_courses:
                existing_courses[code] = Course.objects.create(
                    code=code, name=row["name"], credits=int(row["credits"]),
                    department=department_map[index],
                    kind="CHUNG" if row["program"] == "TKB_MONCHUNG" else "CHUYEN_NGANH")
            employee = row["employee"]
            if employee not in existing_lecturers:
                existing_lecturers[employee] = Lecturer.objects.create(
                    employee_code=employee, name=row["lecturer"],
                    department=department_map[index], status="DangCongTac")
            TeachingQualification.objects.get_or_create(
                lecturer=existing_lecturers[employee], course=existing_courses[code],
                defaults={"priority": 2})
            room_code = row["room"]
            if room_code not in existing_rooms:
                building_code = room_code.split(".")[0] if "." in room_code else "SGU_DEMO"
                building, _ = Building.objects.get_or_create(
                    code=building_code, defaults={"name": f"Cơ sở {building_code} (mô phỏng)"})
                existing_rooms[room_code] = Room.objects.create(
                    code=room_code, name=room_code, building=building,
                    capacity=published_room_capacity[room_code], room_type="LyThuyet", status="SanSang")
            elif existing_rooms[room_code].capacity < published_room_capacity[room_code]:
                room = existing_rooms[room_code]
                room.capacity = published_room_capacity[room_code]
                room.save(update_fields=["capacity"])
            group_key = code, row["group"], row["lab"]
            if group_key not in existing_groups:
                digest = hashlib.sha1("|".join(group_key).encode()).hexdigest()[:20]
                existing_groups[group_key] = CourseGroup.objects.create(
                    course=existing_courses[code], semester=semester, code=f"I{digest}",
                    group=row["group"], lab_group=row["lab"] or None,
                    capacity=int(row["size"]), needs_room=True)
            if row["class"] and existing_groups[group_key].pk not in protected_groups:
                class_name = demo_class_code(row["class"])
                if class_name not in existing_cohorts:
                    existing_cohorts[class_name] = Cohort.objects.create(semester=semester, name=class_name)
                GroupCohort.objects.get_or_create(group=existing_groups[group_key],
                                                  cohort=existing_cohorts[class_name])

        # The same common subjects appear in many major PDFs. Their first PDF
        # must not decide the owning faculty or the lecturers' demo faculty.
        physical_courses = {
            row["course"] for row in candidates
            if "giáo dục thể chất" in row["name"].lower()
            or "giáo dục quốc phòng" in row["name"].lower()
        }
        for code in physical_courses:
            course = existing_courses[code]
            if course.department_id != department_map[4].pk:
                course.department = department_map[4]
                course.save(update_fields=["department"])
        lecturer_courses = defaultdict(set)
        for row in candidates:
            lecturer_courses[row["employee"]].add(row["course"])
        for employee, codes in lecturer_courses.items():
            if codes <= physical_courses:
                lecturer = existing_lecturers[employee]
                if lecturer.department_id != department_map[4].pk:
                    lecturer.department = department_map[4]
                    lecturer.save(update_fields=["department"])

        # Program links reflect the public major PDF, with a clearly demo cycle.
        program_map = {}
        for row in candidates:
            program_code = row["program"]
            if program_code == "TKB_MONCHUNG" or program_code in program_map:
                continue
            index = PROGRAM_FACULTY[program_code]
            program_map[program_code], _ = Program.objects.get_or_create(
                code=program_code, cycle=DEMO_CYCLE,
                defaults={"name": manifest["files"][program_code]["name"],
                          "faculty": faculty_map[index]})
        links = {(row["program"], row["course"]) for row in candidates
                 if row["program"] != "TKB_MONCHUNG"}
        for program_code, course_code in links:
            CourseProgram.objects.get_or_create(course=existing_courses[course_code],
                                                program=program_map[program_code],
                                                defaults={"requirement": "BAT_BUOC"})

        # The original PDF slot wins when free. Changed slots remain demo data.
        occupied = set()
        for entry in (ScheduleEntry.objects.filter(group__semester=semester)
                      .select_related("group").prefetch_related("schedule_weeks", "group__cohort_links")):
            occupied.update(_occupied_keys(
                entry.group_id, entry.room_id, entry.lecturer_id,
                [link.cohort_id for link in entry.group.cohort_links.all()],
                entry.day, entry.start_period_id, entry.period_count,
                [week.week for week in entry.schedule_weeks.all()]))
        cohort_ids = {group.pk: tuple(group.cohort_links.values_list("cohort_id", flat=True))
                      for group in existing_groups.values()}
        pools = defaultdict(deque)
        for row in candidates:
            pools[faculty_for_row(row)].append(row)
        ordered = []
        while any(pools.values()):
            for index in range(1, len(FACULTIES)):
                if pools[index]:
                    ordered.append(pools[index].popleft())

        accepted = []
        skipped = Counter(filtered)
        moved = 0
        counts = Counter()
        ready_rooms = [room for room in existing_rooms.values() if room.status == "SanSang"]
        for row in ordered:
            group = existing_groups[row["course"], row["group"], row["lab"]]
            if group.pk in protected_groups:
                skipped["nhom_da_co_lich_cntt"] += 1
                continue
            lecturer = existing_lecturers[row["employee"]]
            source_room = existing_rooms[row["room"]]
            weeks = _weeks(row["weeks_demo"])
            duration = int(row["duration"])
            original_day, original_start = int(row["day"]), int(row["start"])
            if not weeks or max(weeks) > semester.week_count:
                skipped["tuan_ngoai_hoc_ky"] += 1
                continue
            times = [(day, start) for day in range(2, 8) for start in sorted(periods)
                     if all(periods.get(number) == periods[start]
                            for number in range(start, start + duration))]
            times.sort(key=lambda item: (item != (original_day, original_start),
                                         item[0] != original_day, abs(item[1] - original_start), item))
            rooms = [source_room] + [room for room in ready_rooms if room.pk != source_room.pk
                                     and room.capacity >= group.capacity]
            placement = None
            for day, start in times:
                base_keys = list(_occupied_keys(group.pk, None, lecturer.pk,
                                                cohort_ids[group.pk], day, start, duration, weeks))
                base_keys = [key for key in base_keys if key[1] is not None]
                if any(key in occupied for key in base_keys):
                    continue
                for room in rooms:
                    if room.status != "SanSang" or room.capacity < group.capacity:
                        continue
                    room_keys = [("room", room.pk, week, day, period)
                                 for week in weeks for period in range(start, start + duration)]
                    if not any(key in occupied for key in room_keys):
                        placement = (day, start, room, base_keys + room_keys)
                        break
                if placement:
                    break
            if not placement:
                skipped["khong_con_khung_hop_le"] += 1
                continue
            day, start, room, keys = placement
            occupied.update(keys)
            if (day, start, room.code) != (original_day, original_start, row["room"]):
                moved += 1
            accepted.append((row, group, lecturer, room, day, start, weeks))
            counts[lecturer.department.faculty.code] += 1

        now = timezone.now()
        entries = [ScheduleEntry(
            group=group, lecturer=lecturer, room=room, day=day,
            start_period_id=start, period_count=int(row["duration"]),
            source="SGUMoPhong", status="DaDuyet", approved_by=actor,
            approved_at=now,
            request_code=f"SGU_{row['program']}_{row['page']}_{row['stt']}"[:50],
        ) for row, group, lecturer, room, day, start, weeks in accepted]
        ScheduleEntry.objects.bulk_create(entries, batch_size=250)
        ScheduleWeek.objects.bulk_create([
            ScheduleWeek(entry=entry, week=week)
            for entry, item in zip(entries, accepted)
            for week in item[-1]
        ], batch_size=1000)
        if len(counts) < 14:
            raise ValueError(f"Chỉ có {len(counts)}/14 khoa còn lại có lịch")
        return {"imported": len(entries), "moved": moved, "skipped": dict(skipped),
                "faculty_counts": dict(sorted(counts.items())),
                "assumptions": [
                    "Ánh xạ ngành/học phần chung–khoa suy luận từ tên công khai, chưa được trường xác nhận.",
                    "Tuần dấu * trong PDF được mô phỏng từ tuần 1 theo số dấu đọc được.",
                    "Các buổi đổi thời gian hoặc phòng để tránh xung đột được đếm ở moved; không phải lịch công bố.",
                    "Phòng và chuyên môn giảng viên suy từ lịch công khai; không phải hồ sơ vận hành chính thức.",
                    "Trạng thái DaDuyet chỉ dành cho bản trình diễn nghiên cứu trên cơ sở dữ liệu địa phương.",
                ]}
