"""Import three proposed Excel workbooks and build a real-resource CP-SAT timetable."""

from collections import defaultdict
from io import BytesIO
from random import Random

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from ortools.sat.python import cp_model

from .catalog_import import SHEETS, commit_catalog, validate_catalog
from .auto_schedule_errors import InputIssues, issue
from .great_deluge import improve
from .schedule_diagnostics import diagnose, forced_day_overloads
from .solution_audit import audit_solution
from .models import (AlgorithmRun, CourseGroup, Department, Faculty, Lecturer,
                     LecturerPreference, Period, Room, ScheduleEntry, ScheduleWeek, Semester, TeachingQualification)
from .preference_checks import day_off_error, day_off_violations
from .schedule_import import parse_weeks


AUTO_SHEETS = {
    "courses": {
        "Khoa": ("ma_khoa", "ten_khoa"),
        "BoMon": ("ma_bo_mon", "ten_bo_mon", "ma_khoa"),
        **SHEETS["courses"],
        "BuoiHocYeuCau": ("ma_mon_hoc", "nhom", "to_th", "ma_buoi", "so_tiet",
                           "tuan_hoc", "loai_phong", "thu_duoc_xep"),
    },
    "rooms": {
        **SHEETS["rooms"],
        "PhongKhongKhaDung": ("ma_phong", "thu", "tiet_bat_dau", "so_tiet", "tuan_hoc"),
    },
    "lecturers": {
        **SHEETS["lecturers"],
        "GiangVienKhongKhaDung": ("ma_vien_chuc", "thu", "tiet_bat_dau", "so_tiet", "tuan_hoc"),
    },
}
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 6000
LARGE_RUN_SESSIONS = 500
ROOM_TYPES = {"LyThuyet", "MayTinh", "ThiNghiem", "HoiTruong"}


def template_bytes(kind):
    book = Workbook()
    book.remove(book.active)
    for name, headers in AUTO_SHEETS[kind].items():
        sheet = book.create_sheet(name)
        sheet.append(headers)
        sheet.freeze_panes = "A2"
        for index, header in enumerate(headers, 1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = max(18, len(header) + 2)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def read_auto_workbook(upload, kind):
    if upload is None or not upload.name.lower().endswith(".xlsx") or upload.size > MAX_BYTES:
        raise InputIssues([issue(kind, "", None,
                                 f"Phải là .xlsx và không quá {MAX_BYTES // 1024 // 1024} MB")])
    try:
        book = load_workbook(upload, read_only=True, data_only=True)
        problems = []
        expected = set(AUTO_SHEETS[kind])
        for name in sorted(expected - set(book.sheetnames)):
            problems.append(issue(kind, name, None, "Thiếu sheet theo mẫu"))
        for name in sorted(set(book.sheetnames) - expected):
            problems.append(issue(kind, name, None, "Sheet không có trong mẫu"))
        result = {}
        count = 0
        limit_reported = False
        for name, headers in AUTO_SHEETS[kind].items():
            if name not in book.sheetnames:
                continue
            rows = book[name].iter_rows(values_only=True)
            heading = next(rows, None)
            if heading is None or tuple(str(value or "").strip() for value in heading) != headers:
                problems.append(issue(kind, name, 1, "Tiêu đề cột không khớp mẫu"))
                continue
            result[name] = []
            for line, values in enumerate(rows, 2):
                if line > MAX_ROWS + 100:
                    problems.append(issue(kind, name, line, "Sheet có quá nhiều dòng"))
                    break
                if all(value is None or str(value).strip() == "" for value in values):
                    continue
                count += 1
                if count > MAX_ROWS and not limit_reported:
                    problems.append(issue(kind, name, line,
                                          f"File vượt {MAX_ROWS} dòng dữ liệu"))
                    limit_reported = True
                if any(value not in (None, "") for value in values[len(headers):]):
                    problems.append(issue(kind, name, line, "Dữ liệu ngoài cột mẫu"))
                padded = list(values[:len(headers)]) + [None] * max(0, len(headers) - len(values))
                for key, value in zip(headers, padded):
                    if (key.startswith("ma_") or key in ("nhom", "to_th")) and isinstance(value, (int, float)):
                        problems.append(issue(kind, name, line, f"{key} phải là ô văn bản"))
                result[name].append({"line": line, **{
                    key: "" if value is None else str(value).strip()
                    for key, value in zip(headers, padded)
                }})
        if problems:
            raise InputIssues(problems)
        return result
    except InputIssues:
        raise
    except Exception as exc:
        raise InputIssues([issue(kind, "", None, "Không đọc được file Excel hợp lệ")]) from exc
    finally:
        if "book" in locals():
            book.close()


def read_auto_files(files):
    data = {}
    problems = []
    for kind in AUTO_SHEETS:
        try:
            data[kind] = read_auto_workbook(files.get(kind), kind)
        except InputIssues as exc:
            problems.extend(exc.issues)
    if problems:
        raise InputIssues(problems)
    return data


def _base(data, kind):
    return {name: data[name] for name in SHEETS[kind]}


def _int(value, label, minimum=1, maximum=53):
    if not value.isdigit() or not minimum <= int(value) <= maximum:
        raise ValueError(f"{label} phải từ {minimum} đến {maximum}")
    return int(value)


def _week_set(value, semester):
    weeks = parse_weeks(value)
    if weeks[-1] > semester.week_count:
        raise ValueError("Tuần học vượt giới hạn học kỳ")
    return frozenset(weeks)


def _days(value):
    if not value:
        return frozenset(range(2, 8))
    days = set()
    for part in value.replace(";", ",").split(","):
        pieces = part.strip().split("-")
        if len(pieces) > 2 or any(not p.isdigit() for p in pieces):
            raise ValueError("thu_duoc_xep phải có dạng 2-6,7")
        start, end = int(pieces[0]), int(pieces[-1])
        if start < 2 or end > 8 or end < start:
            raise ValueError("Thứ được xếp phải trong khoảng 2-8")
        days.update(range(start, end + 1))
    return frozenset(days)


def _blocks(data, sheet, key, semester, kind, problems):
    blocks = []
    for row in data[sheet]:
        try:
            code = row[key]
            if not code:
                raise ValueError(f"Thiếu {key}")
            day = _int(row["thu"], "Thứ", 2, 8)
            start = _int(row["tiet_bat_dau"], "Tiết bắt đầu", 1, 13)
            count = _int(row["so_tiet"], "Số tiết", 1, 13)
            if start + count > 14:
                raise ValueError("Buổi vượt tiết 13")
            blocks.append((code, day, start, count, _week_set(row["tuan_hoc"], semester)))
        except ValueError as exc:
            problems.append(issue(kind, sheet, row["line"], exc))
    return blocks


def _prepare_inputs(semester, data):
    courses, rooms, lecturers = data["courses"], data["rooms"], data["lecturers"]
    problems = []
    if not courses["BuoiHocYeuCau"]:
        problems.append(issue("courses", "BuoiHocYeuCau", None, "Cần ít nhất một buổi học yêu cầu"))
    faculties = {row["ma_khoa"]: row for row in courses["Khoa"]}
    seen_faculties = set()
    for row in courses["Khoa"]:
        if row["ma_khoa"] in seen_faculties:
            problems.append(issue("courses", "Khoa", row["line"], "Mã khoa bị lặp"))
        seen_faculties.add(row["ma_khoa"])
        if not row["ma_khoa"] or not row["ten_khoa"]:
            problems.append(issue("courses", "Khoa", row["line"], "Thiếu mã hoặc tên"))
        if len(row["ma_khoa"]) > 20 or len(row["ten_khoa"]) > 200:
            problems.append(issue("courses", "Khoa", row["line"], "Mã hoặc tên quá dài"))
    seen_departments = set()
    for row in courses["BoMon"]:
        if row["ma_bo_mon"] in seen_departments:
            problems.append(issue("courses", "BoMon", row["line"], "Mã bộ môn bị lặp"))
        seen_departments.add(row["ma_bo_mon"])
        if not row["ma_bo_mon"] or not row["ten_bo_mon"] or row["ma_khoa"] not in faculties:
            problems.append(issue("courses", "BoMon", row["line"], "Bộ môn hoặc khoa không hợp lệ"))
        if len(row["ma_bo_mon"]) > 30 or len(row["ten_bo_mon"]) > 200:
            problems.append(issue("courses", "BoMon", row["line"], "Mã hoặc tên quá dài"))
    demands = []
    keys = set()
    group_keys = {(row["ma_mon_hoc"], row["nhom"], row["to_th"]) for row in courses["NhomHocPhan"]}
    requested_keys = set()
    for row in courses["BuoiHocYeuCau"]:
        try:
            group_key = row["ma_mon_hoc"], row["nhom"], row["to_th"]
            requested_keys.add(group_key)
            if group_key not in group_keys:
                raise ValueError("Môn/nhóm/tổ TH không có trong NhomHocPhan")
            if not row["ma_buoi"]:
                raise ValueError("Thiếu ma_buoi")
            if len(row["ma_buoi"]) > 50:
                raise ValueError("ma_buoi dài quá 50 ký tự")
            key = (*group_key, row["ma_buoi"])
            if key in keys:
                raise ValueError("Mã buổi bị lặp trong nhóm")
            keys.add(key)
            count = _int(row["so_tiet"], "Số tiết", 1, 13)
            room_type = row["loai_phong"]
            if room_type and room_type not in ROOM_TYPES:
                raise ValueError("Loại phòng không hỗ trợ")
            demands.append({"key": group_key, "code": row["ma_buoi"], "line": row["line"], "count": count,
                            "weeks": _week_set(row["tuan_hoc"], semester),
                            "room_type": room_type, "days": _days(row["thu_duoc_xep"])})
        except ValueError as exc:
            problems.append(issue("courses", "BuoiHocYeuCau", row["line"], exc))
    for row in courses["NhomHocPhan"]:
        key = row["ma_mon_hoc"], row["nhom"], row["to_th"]
        if key not in requested_keys:
            problems.append(issue("courses", "NhomHocPhan", row["line"],
                                  "Nhóm chưa có buổi học yêu cầu"))
    room_blocks = _blocks(rooms, "PhongKhongKhaDung", "ma_phong", semester,
                          "rooms", problems)
    teacher_blocks = _blocks(lecturers, "GiangVienKhongKhaDung", "ma_vien_chuc",
                             semester, "lecturers", problems)
    room_codes = {row["ma_phong"] for row in rooms["PhongHoc"]}
    teacher_codes = {row["ma_vien_chuc"] for row in lecturers["GiangVien"]}
    for row in rooms["PhongKhongKhaDung"]:
        if row["ma_phong"] and row["ma_phong"] not in room_codes:
            problems.append(issue("rooms", "PhongKhongKhaDung", row["line"],
                                  "Mã phòng không có trong PhongHoc"))
    for row in lecturers["GiangVienKhongKhaDung"]:
        if row["ma_vien_chuc"] and row["ma_vien_chuc"] not in teacher_codes:
            problems.append(issue("lecturers", "GiangVienKhongKhaDung", row["line"],
                                  "Mã viên chức không có trong GiangVien"))
    if problems:
        raise InputIssues(problems)
    return demands, room_blocks, teacher_blocks


def _create_catalog(semester, data, demand_rows, room_blocks, teacher_blocks):
    courses, rooms, lecturers = data["courses"], data["rooms"], data["lecturers"]
    problems = []
    for row in courses["Khoa"]:
        Faculty.objects.update_or_create(code=row["ma_khoa"], defaults={"name": row["ten_khoa"]})
    for row in courses["BoMon"]:
        matches = list(Department.objects.filter(code=row["ma_bo_mon"])[:2])
        if len(matches) > 1:
            problems.append(issue("courses", "BoMon", row["line"], "Mã bộ môn bị lặp trong hệ thống"))
            continue
        old = matches[0] if matches else None
        faculty = Faculty.objects.get(code=row["ma_khoa"])
        if old and old.faculty_id != faculty.pk:
            problems.append(issue("courses", "BoMon", row["line"], "Bộ môn đã thuộc khoa khác"))
            continue
        Department.objects.update_or_create(code=row["ma_bo_mon"], defaults={
            "name": row["ten_bo_mon"], "faculty": faculty,
        })
    if problems:
        raise InputIssues(problems)
    course_errors = validate_catalog("courses", _base(courses, "courses"), semester)
    room_errors = validate_catalog("rooms", _base(rooms, "rooms"))
    lecturer_errors = validate_catalog(
        "lecturers", _base(lecturers, "lecturers"),
        available_course_codes={row["ma_mon_hoc"] for row in courses["HocPhan"]},
    )
    for kind, errors in (("courses", course_errors), ("rooms", room_errors),
                         ("lecturers", lecturer_errors)):
        problems.extend(issue(kind, item.get("sheet"), item.get("line"), item["message"])
                        for item in errors)
    if problems:
        raise InputIssues(problems)
    commit_catalog("courses", _base(courses, "courses"), semester)
    commit_catalog("rooms", _base(rooms, "rooms"))
    commit_catalog("lecturers", _base(lecturers, "lecturers"))

    group_map = {(g.course.code, g.group, g.lab_group or ""): g for g in
                 CourseGroup.objects.filter(semester=semester).select_related("course")}
    room_codes = {row["ma_phong"] for row in rooms["PhongHoc"]}
    teacher_codes = {row["ma_vien_chuc"] for row in lecturers["GiangVien"]}
    room_map = {r.code: r for r in Room.objects.filter(code__in=room_codes)}
    teacher_map = {t.employee_code: t for t in Lecturer.objects.filter(employee_code__in=teacher_codes)}
    for code, *_ in room_blocks:
        if code not in room_map:
            raise ValueError(f"Phòng không khả dụng {code} chưa có trong file")
    for code, *_ in teacher_blocks:
        if code not in teacher_map:
            raise ValueError(f"Giảng viên không khả dụng {code} chưa có trong file")
    return [dict(row, group=group_map[row["key"]]) for row in demand_rows], room_map, teacher_map


def _add_fixed(buckets, key, day, start, count, weeks, model, label):
    interval = model.NewIntervalVar(start, count, start + count, label)
    for week in weeks:
        buckets[(key, day, week)].append(interval)


def _overlap(a_start, a_count, b_start, b_count):
    return a_start < b_start + b_count and b_start < a_start + a_count


def _greedy_seed(demands, choices, previous, room_unavailable, teacher_unavailable,
                 *, attempts=8, seed=42):
    """Find a valid complete assignment to hint CP-SAT and cover timeouts."""
    fixed = set()

    def keys(kind, resource_id, day, start, count, weeks):
        return ((kind, resource_id, day, week, period)
                for week in weeks for period in range(start, start + count))

    for entry in previous:
        weeks = [item.week for item in entry.schedule_weeks.all()]
        resources = [("group", entry.group_id), ("room", entry.room_id),
                     ("teacher", entry.lecturer_id)]
        resources += [("cohort", link.cohort_id) for link in entry.group.cohort_links.all()]
        for kind, resource_id in resources:
            if resource_id is not None:
                fixed.update(keys(kind, resource_id, entry.day, entry.start_period_id,
                                  entry.period_count, weeks))

    rng = Random(seed)
    order = list(range(len(demands)))
    order.sort(key=lambda index: (len(choices[index][0]) * len(choices[index][2]) * len(choices[index][4]),
                                  -demands[index]["count"], rng.random()))
    cohorts = [{link.cohort_id for link in demand["group"].cohort_links.all()}
               for demand in demands]
    for _ in range(attempts):
        occupied = set(fixed)
        selected = {}
        for index in order:
            demand = demands[index]
            group = demand["group"]
            count, weeks = demand["count"], demand["weeks"]
            time_options, _, rooms, _, teachers, _ = choices[index]
            time_indices = list(range(len(time_options)))
            rng.shuffle(time_indices)
            found = False
            for time_index in time_indices:
                day, start, _ = time_options[time_index]
                group_keys = list(keys("group", group.pk, day, start, count, weeks))
                for cohort_id in cohorts[index]:
                    group_keys.extend(keys("cohort", cohort_id, day, start, count, weeks))
                if any(key in occupied for key in group_keys):
                    continue
                room_indices = list(range(len(rooms)))
                teacher_indices = list(range(len(teachers)))
                rng.shuffle(room_indices)
                rng.shuffle(teacher_indices)
                for room_index in room_indices:
                    room = rooms[room_index]
                    if (any(_overlap(start, count, busy_start, busy_count)
                            for week in weeks for busy_start, busy_count
                            in room_unavailable[(room.pk, day, week)]) or
                            any(key in occupied for key in keys("room", room.pk, day, start, count, weeks))):
                        continue
                    for teacher_index in teacher_indices:
                        teacher = teachers[teacher_index].lecturer
                        if (any(_overlap(start, count, busy_start, busy_count)
                                for week in weeks for busy_start, busy_count
                                in teacher_unavailable[(teacher.pk, day, week)]) or
                                any(key in occupied for key in keys("teacher", teacher.pk, day, start, count, weeks))):
                            continue
                        occupied.update(group_keys)
                        occupied.update(keys("room", room.pk, day, start, count, weeks))
                        occupied.update(keys("teacher", teacher.pk, day, start, count, weeks))
                        selected[index] = (time_index, room_index, teacher_index)
                        found = True
                        break
                    if found:
                        break
                if found:
                    break
            if not found:
                break
        if len(selected) == len(demands):
            return selected
        rng.shuffle(order)
    return None


def _solve_large(semester, demands, room_map, qualification, periods,
                 room_unavailable, teacher_unavailable, room_blocks, teacher_blocks,
                 teacher_map, allowed_pairs):
    """Use the audited constructive path without allocating a huge CP-SAT model."""
    if forced_day_overloads(semester, demands):
        return None, "INFEASIBLE", None
    choices = []
    problems = []
    available_rooms = [room for room in room_map.values() if room.status == "SanSang"]
    for demand in demands:
        group = demand["group"]
        count = demand["count"]
        times = [(day, start, periods[start].block) for day in demand["days"]
                 for start in sorted(periods)
                 if all(number in periods and periods[number].block == periods[start].block
                        for number in range(start, start + count))]
        rooms = [room for room in available_rooms if room.capacity >= group.capacity
                 and (not demand["room_type"] or room.room_type == demand["room_type"])]
        teachers = qualification[group.course_id]
        if not times or not rooms or not teachers:
            reasons = []
            if not times:
                reasons.append("không có khung tiết phù hợp")
            if not rooms:
                reasons.append("không có phòng phù hợp")
            if not teachers:
                reasons.append("không có giảng viên đủ chuyên môn")
            problems.append(issue("courses", "BuoiHocYeuCau", demand["line"],
                                  "; ".join(reasons)))
        choices.append((times, None, rooms, None, teachers, None))
    if problems:
        raise InputIssues(problems)
    previous = list(ScheduleEntry.objects.filter(group__semester=semester)
                    .exclude(source="ThuatToan", status="ChoDuyet")
                    .select_related("group").prefetch_related("schedule_weeks", "group__cohort_links"))
    selected = _greedy_seed(demands, choices, previous, room_unavailable,
                            teacher_unavailable, attempts=12)
    if selected is None:
        return None, "UNKNOWN", None
    result = []
    for index, demand in enumerate(demands):
        time_index, room_index, teacher_index = selected[index]
        times, _, rooms, _, teachers, _ = choices[index]
        day, start, _ = times[time_index]
        result.append((demand, day, start, rooms[room_index], teachers[teacher_index].lecturer))
    _, score, _ = improve(semester, result, room_map, teacher_map, room_blocks,
                          teacher_blocks, allowed_pairs, max_iterations=0)
    return result, "HEURISTIC", score


def solve(semester, demands, room_map, teacher_map, room_blocks, teacher_blocks,
          allowed_pairs, *, preferences=None):
    periods = {p.pk: p for p in Period.objects.all()}
    if not periods:
        raise ValueError("Chưa cấu hình tiết học cho hệ thống")
    qualification = defaultdict(list)
    teacher_ids = {teacher.pk for teacher in teacher_map.values()}
    for q in TeachingQualification.objects.filter(lecturer_id__in=teacher_ids).select_related("lecturer", "course"):
        if q.lecturer.status == "DangCongTac" and (q.lecturer.employee_code, q.course.code) in allowed_pairs:
            qualification[q.course_id].append(q)
    room_unavailable = defaultdict(list)
    for code, day, start, count, weeks in room_blocks:
        for week in weeks:
            room_unavailable[(room_map[code].pk, day, week)].append((start, count))
    teacher_unavailable = defaultdict(list)
    for code, day, start, count, weeks in teacher_blocks:
        for week in weeks:
            teacher_unavailable[(teacher_map[code].pk, day, week)].append((start, count))
    if preferences is None:
        preferences = list(LecturerPreference.objects.filter(semester=semester))
    for pref in preferences:
        if pref.kind != "NgayNghi":
            continue
        if pref.day:
            for week in range(1, semester.week_count + 1):
                teacher_unavailable[(pref.lecturer_id, pref.day, week)].append((1, 13))
    prefs = defaultdict(list)
    for pref in preferences:
        if pref.kind == "KhungGio":
            prefs[pref.lecturer_id].append(pref)

    if len(demands) >= LARGE_RUN_SESSIONS:
        return _solve_large(semester, demands, room_map, qualification, periods,
                            room_unavailable, teacher_unavailable, room_blocks,
                            teacher_blocks, teacher_map, allowed_pairs)

    model = cp_model.CpModel()
    room_buckets, teacher_buckets, cohort_buckets, group_buckets = (defaultdict(list) for _ in range(4))
    choices = []
    objective = []
    preflight_errors = []
    for index, demand in enumerate(demands):
        group = demand["group"]
        count = demand["count"]
        time_options = [(day, start, periods[start].block) for day in demand["days"]
                        for start in sorted(periods)
                        if all(number in periods and periods[number].block == periods[start].block
                               for number in range(start, start + count))]
        rooms = [room for room in room_map.values() if room.status == "SanSang"
                 and room.capacity >= group.capacity
                 and (not demand["room_type"] or room.room_type == demand["room_type"])]
        teachers = qualification[group.course_id]
        issues = []
        if not time_options:
            issues.append("không có khung tiết hợp lệ; kiểm tra so_tiet, thu_duoc_xep và cấu hình tiết học")
        if not rooms:
            issues.append("không có phòng đủ sức chứa/đúng loại; kiểm tra file Phòng học")
        if not teachers:
            issues.append("không có giảng viên đủ chuyên môn; kiểm tra GiangVienHocPhan")
        if issues:
            preflight_errors.append(issue("courses", "BuoiHocYeuCau", demand["line"],
                                          f"Môn {group.course.code}, nhóm {group.group}, "
                                          f"buổi {demand['code']}: " + "; ".join(issues)))
            continue
        x = [model.NewBoolVar(f"t_{index}_{j}") for j in range(len(time_options))]
        r = [model.NewBoolVar(f"r_{index}_{j}") for j in range(len(rooms))]
        g = [model.NewBoolVar(f"g_{index}_{j}") for j in range(len(teachers))]
        model.AddExactlyOne(x)
        model.AddExactlyOne(r)
        model.AddExactlyOne(g)
        start_var = model.NewIntVar(1, 13, f"start_{index}")
        end_var = model.NewIntVar(2, 14, f"end_{index}")
        model.Add(end_var == start_var + count)
        for j, (_, start, block) in enumerate(time_options):
            model.Add(start_var == start).OnlyEnforceIf(x[j])
            if block.lower().startswith("toi"):
                objective.append(5 * x[j])
        day_flags = {}
        for day in demand["days"]:
            flag = model.NewBoolVar(f"day_{index}_{day}")
            model.Add(flag == sum(x[j] for j, option in enumerate(time_options) if option[0] == day))
            day_flags[day] = flag
            interval = model.NewOptionalIntervalVar(start_var, count, end_var, flag,
                                                     f"group_{index}_{day}")
            for week in demand["weeks"]:
                group_buckets[(group.pk, day, week)].append(interval)
                for link in group.cohort_links.all():
                    cohort_buckets[(link.cohort_id, day, week)].append(interval)
        for j, room in enumerate(rooms):
            for day, day_flag in day_flags.items():
                present = model.NewBoolVar(f"room_{index}_{j}_{day}")
                model.AddMultiplicationEquality(present, [r[j], day_flag])
                interval = model.NewOptionalIntervalVar(start_var, count, end_var, present,
                                                         f"ri_{index}_{j}_{day}")
                for week in demand["weeks"]:
                    room_buckets[(room.pk, day, week)].append(interval)
        for j, qualification_row in enumerate(teachers):
            teacher = qualification_row.lecturer
            objective.append(max(0, qualification_row.priority - 1) * g[j])
            for k, (day, start, block) in enumerate(time_options):
                if any(_overlap(start, count, busy_start, busy_count)
                       for week in demand["weeks"]
                       for busy_start, busy_count in teacher_unavailable[(teacher.pk, day, week)]):
                    model.Add(g[j] + x[k] <= 1)
                penalty = 0
                for pref in prefs[teacher.pk]:
                    if not pref.time_block or (pref.day is not None and pref.day != day):
                        continue
                    if pref.priority <= 2 and pref.time_block != block:
                        penalty += (3 - pref.priority) * 4
                    elif pref.priority >= 3 and pref.time_block == block:
                        penalty += (pref.priority - 2) * 4
                if penalty:
                    both = model.NewBoolVar(f"pref_{index}_{j}_{k}")
                    model.AddMultiplicationEquality(both, [g[j], x[k]])
                    objective.append(penalty * both)
            for day, day_flag in day_flags.items():
                present = model.NewBoolVar(f"teacher_{index}_{j}_{day}")
                model.AddMultiplicationEquality(present, [g[j], day_flag])
                interval = model.NewOptionalIntervalVar(start_var, count, end_var, present,
                                                         f"ti_{index}_{j}_{day}")
                for week in demand["weeks"]:
                    teacher_buckets[(teacher.pk, day, week)].append(interval)
        choices.append((time_options, x, rooms, r, teachers, g))

    if preflight_errors:
        raise InputIssues(preflight_errors)

    previous = list(ScheduleEntry.objects.filter(group__semester=semester)
                    .exclude(source="ThuatToan", status="ChoDuyet")
                    .select_related("group").prefetch_related("schedule_weeks", "group__cohort_links"))
    for entry in previous:
        weeks = [item.week for item in entry.schedule_weeks.all()]
        if entry.room_id:
            _add_fixed(room_buckets, entry.room_id, entry.day, entry.start_period_id,
                       entry.period_count, weeks, model, f"fixed_room_{entry.pk}")
        if entry.lecturer_id:
            _add_fixed(teacher_buckets, entry.lecturer_id, entry.day, entry.start_period_id,
                       entry.period_count, weeks, model, f"fixed_teacher_{entry.pk}")
        _add_fixed(group_buckets, entry.group_id, entry.day, entry.start_period_id,
                   entry.period_count, weeks, model, f"fixed_group_{entry.pk}")
        for link in entry.group.cohort_links.all():
            _add_fixed(cohort_buckets, link.cohort_id, entry.day, entry.start_period_id,
                       entry.period_count, weeks, model, f"fixed_cohort_{entry.pk}_{link.cohort_id}")
    for buckets in (room_buckets, teacher_buckets, cohort_buckets, group_buckets):
        seen_overlaps = set()
        for intervals in buckets.values():
            if len(intervals) > 1:
                signature = tuple(interval.Index() for interval in intervals)
                if signature not in seen_overlaps:
                    model.AddNoOverlap(intervals)
                    seen_overlaps.add(signature)
    # Resource unavailability is checked against every candidate time option.
    for index, demand in enumerate(demands):
        time_options, x, rooms, r, _, _ = choices[index]
        for j, room in enumerate(rooms):
            for k, (day, start, _) in enumerate(time_options):
                if any(_overlap(start, demand["count"], busy_start, busy_count)
                       for week in demand["weeks"]
                       for busy_start, busy_count in room_unavailable[(room.pk, day, week)]):
                    model.Add(r[j] + x[k] <= 1)
    seed_solution = _greedy_seed(demands, choices, previous, room_unavailable, teacher_unavailable)
    if seed_solution is not None:
        for index, (time_options, x, rooms, r, teachers, g) in enumerate(choices):
            selected_time, selected_room, selected_teacher = seed_solution[index]
            for flags, chosen in ((x, selected_time), (r, selected_room), (g, selected_teacher)):
                for flag_index, flag in enumerate(flags):
                    model.AddHint(flag, int(flag_index == chosen))
    model.Minimize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE and seed_solution is not None:
            raise ValueError("Lịch khởi tạo mâu thuẫn với kết luận CP-SAT; cần kiểm tra mô hình ràng buộc")
        if status == cp_model.UNKNOWN and seed_solution is not None:
            result = []
            for index, demand in enumerate(demands):
                time_options, _, rooms, _, teachers, _ = choices[index]
                time_index, room_index, teacher_index = seed_solution[index]
                day, start, _ = time_options[time_index]
                result.append((demand, day, start, rooms[room_index], teachers[teacher_index].lecturer))
            _, objective_value, _ = improve(
                semester, result, room_map, teacher_map, room_blocks, teacher_blocks,
                allowed_pairs, max_iterations=0,
            )
            return result, "HEURISTIC", objective_value
        return None, solver.StatusName(status), None
    result = []
    for demand, (time_options, x, rooms, r, teachers, g) in zip(demands, choices):
        day, start, _ = time_options[next(j for j, flag in enumerate(x) if solver.Value(flag))]
        room = rooms[next(j for j, flag in enumerate(r) if solver.Value(flag))]
        teacher = teachers[next(j for j, flag in enumerate(g) if solver.Value(flag))].lecturer
        result.append((demand, day, start, room, teacher))
    return result, solver.StatusName(status), round(solver.ObjectiveValue())


def _demand_snapshot(demands):
    return [{
        "group_id": demand["group"].pk,
        "course_code": demand["group"].course.code,
        "group": demand["group"].group,
        "lab_group": demand["group"].lab_group or "",
        "code": demand["code"], "excel_row": demand["line"],
    } for demand in demands]


@transaction.atomic
def run_from_workbooks(semester_id, files, actor, existing_run_id=None):
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    if semester.status == "DaKhoa":
        raise ValueError("Học kỳ đã khóa")
    data = read_auto_files(files)
    demands, room_blocks, teacher_blocks = _prepare_inputs(semester, data)
    demands, room_map, teacher_map = _create_catalog(semester, data, demands, room_blocks, teacher_blocks)
    demand_group_ids = {demand["group"].pk for demand in demands}
    existing_in_group = (ScheduleEntry.objects.filter(group_id__in=demand_group_ids)
                         .exclude(source="ThuatToan", status="ChoDuyet")
                         .select_related("group__course").first())
    if existing_in_group:
        demand = next(item for item in demands if item["group"].pk == existing_in_group.group_id)
        raise InputIssues([issue("courses", "BuoiHocYeuCau", demand["line"],
                                 f"Nhóm {existing_in_group.group.course.code}/{existing_in_group.group.group} "
                                 "đã có lịch được duyệt hoặc nhập riêng; không thể tự xếp thêm "
                                 "khi chưa có mã buổi yêu cầu để đối chiếu")])
    allowed_pairs = {(row["ma_vien_chuc"], row["ma_mon_hoc"])
                     for row in data["lecturers"]["GiangVienHocPhan"]}
    preferences = list(LecturerPreference.objects.filter(semester=semester)
                       .select_related("lecturer").order_by("pk"))
    preferences_captured_at = timezone.now()
    preferences_snapshot = [{
        "id": pref.pk, "lecturer_id": pref.lecturer_id,
        "employee_code": pref.lecturer.employee_code, "lecturer_name": pref.lecturer.name,
        "kind": pref.kind, "day": pref.day, "time_block": pref.time_block,
        "priority": pref.priority, "note": pref.note,
    } for pref in preferences]
    result, status, objective = solve(semester, demands, room_map, teacher_map,
                                      room_blocks, teacher_blocks, allowed_pairs,
                                      preferences=preferences)
    if result is None:
        if status == "INFEASIBLE":
            message = "Không có phương án thỏa đồng thời các ràng buộc với nguồn lực hiện có"
        elif status == "UNKNOWN":
            message = ("Chưa tìm được phương án khởi tạo hợp lệ; chưa thể kết luận vô nghiệm"
                       if len(demands) >= LARGE_RUN_SESSIONS else
                       "Hết 30 giây nhưng chưa tìm được phương án; chưa thể kết luận vô nghiệm")
        else:
            message = f"Bộ giải trả trạng thái {status}; cần kiểm tra dữ liệu và mô hình"
        diagnostics = diagnose(semester, demands, room_map, teacher_map,
                               room_blocks, teacher_blocks, allowed_pairs,
                               preferences=preferences)
        if existing_run_id is None:
            run = AlgorithmRun.objects.create(semester=semester, created_by=actor, status=status,
                                              message=message, diagnostics=diagnostics,
                                              preferences_snapshot=preferences_snapshot,
                                              preferences_captured_at=preferences_captured_at)
        else:
            run = AlgorithmRun.objects.select_for_update().get(pk=existing_run_id)
            run.status, run.message, run.diagnostics = status, message, diagnostics
            run.preferences_snapshot = preferences_snapshot
            run.preferences_captured_at = preferences_captured_at
            run.save(update_fields=["status", "message", "diagnostics",
                                    "preferences_snapshot", "preferences_captured_at"])
        return run
    objective_before = objective
    if status != "OPTIMAL" and objective > 0:
        improved, verified_before, verified_after = improve(
            semester, result, room_map, teacher_map, room_blocks, teacher_blocks, allowed_pairs,
            preferences=preferences,
        )
        if verified_before != objective:
            raise ValueError("Điểm CP-SAT và pha cải thiện không khớp; đã hủy lần chạy")
        if verified_after < objective:
            result, objective = improved, verified_after
    audit_solution(semester, demands, result, room_map, teacher_map,
                   room_blocks, teacher_blocks, allowed_pairs, preferences=preferences)
    replaced = ScheduleEntry.objects.filter(group__semester=semester, source="ThuatToan", status="ChoDuyet")
    replaced_run_ids = set(replaced.exclude(algorithm_run_id__isnull=True)
                           .values_list("algorithm_run_id", flat=True))
    replaced.delete()
    AlgorithmRun.objects.filter(pk__in=replaced_run_ids).update(message="Phương án đã được thay thế bởi lần chạy mới")
    if existing_run_id is None:
        run = AlgorithmRun.objects.create(semester=semester, created_by=actor, status=status,
                                          objective=objective, objective_before=objective_before,
                                          entry_count=len(result),
                                          preferences_snapshot=preferences_snapshot,
                                          preferences_captured_at=preferences_captured_at,
                                          demand_snapshot=_demand_snapshot(demands))
    else:
        run = AlgorithmRun.objects.select_for_update().get(pk=existing_run_id)
        run.status, run.objective, run.objective_before = status, objective, objective_before
        run.entry_count = len(result)
        run.message, run.diagnostics = "", []
        run.preferences_snapshot = preferences_snapshot
        run.preferences_captured_at = preferences_captured_at
        run.demand_snapshot = _demand_snapshot(demands)
        run.save(update_fields=["status", "objective", "objective_before", "entry_count",
                                "message", "diagnostics", "preferences_snapshot",
                                "preferences_captured_at", "demand_snapshot"])
    entries = [ScheduleEntry(
        group=demand["group"], lecturer=teacher, room=room, day=day,
        start_period_id=start, period_count=demand["count"],
        status="ChoDuyet", source="ThuatToan", algorithm_run=run,
        request_code=demand["code"],
    ) for demand, day, start, room, teacher in result]
    # audit_solution checks every hard rule against fixed and generated sessions
    # before this transaction writes any of the generated entries.
    ScheduleEntry.objects.bulk_create(entries, batch_size=250)
    ScheduleWeek.objects.bulk_create((
        ScheduleWeek(entry=entry, week=week)
        for entry, (demand, *_rest) in zip(entries, result)
        for week in demand["weeks"]
    ), batch_size=1000)
    return run


@transaction.atomic
def approve_algorithm_run(run_id, actor):
    from rest_framework.exceptions import ValidationError

    if actor is None or not actor.is_authenticated or not actor.is_staff:
        raise ValidationError("Chỉ quản trị viên được duyệt lịch")

    run = AlgorithmRun.objects.select_for_update().get(pk=run_id)
    if run.status not in ("FEASIBLE", "OPTIMAL", "HEURISTIC") or run.entry_count == 0:
        raise ValidationError("Lần chạy không có phương án để duyệt")
    semester = Semester.objects.select_for_update().get(pk=run.semester_id)
    if semester.status == "DaKhoa":
        raise ValidationError("Học kỳ đã khóa")
    ids = list(run.entries.order_by("pk").values_list("pk", flat=True))
    if len(ids) != run.entry_count or run.entries.exclude(status="ChoDuyet").exists():
        raise ValidationError("Phương án đã thay đổi hoặc đã được duyệt; hãy chạy lại nếu cần")
    violations = day_off_violations(semester.pk, run.entries.select_related(
        "group__course", "lecturer"))
    if violations:
        raise ValidationError(day_off_error(violations))
    occupied = set()
    entries = (ScheduleEntry.objects.filter(group__semester=semester)
               .select_related("group", "lecturer", "room")
               .prefetch_related("schedule_weeks", "group__cohort_links"))
    qualified = set(TeachingQualification.objects.values_list("lecturer_id", "course_id"))
    for entry in entries:
        if (entry.lecturer_id and
                (entry.lecturer.status != "DangCongTac" or
                 (entry.lecturer_id, entry.group.course_id) not in qualified)):
            raise ValidationError("Lịch có giảng viên không còn đủ điều kiện; cần xếp lại")
        if (entry.room_id and entry.room.status != "SanSang") or (
                entry.group.needs_room and not entry.room_id and not entry.other_location):
            raise ValidationError("Lịch có phòng hoặc địa điểm không còn hợp lệ; cần xếp lại")
        resources = [("group", entry.group_id), ("room", entry.room_id),
                     ("lecturer", entry.lecturer_id)]
        resources.extend(("cohort", link.cohort_id) for link in entry.group.cohort_links.all())
        weeks = [item.week for item in entry.schedule_weeks.all()]
        if not weeks or min(weeks) < 1 or max(weeks) > semester.week_count:
            raise ValidationError("Lịch có tuần ngoài học kỳ; cần xếp lại")
        for week in weeks:
            for period in range(entry.start_period_id, entry.start_period_id + entry.period_count):
                for kind, resource_id in resources:
                    if resource_id is None:
                        continue
                    key = kind, resource_id, entry.day, week, period
                    if key in occupied:
                        raise ValidationError("Lịch phát sinh xung đột trước khi duyệt; cần xếp lại")
                    occupied.add(key)
    changed = ScheduleEntry.objects.filter(pk__in=ids, status="ChoDuyet").update(
        status="DaDuyet", approved_by=actor, approved_at=timezone.now(),
    )
    if changed != len(ids):
        raise ValidationError("Phương án đã thay đổi trong khi duyệt; hãy thử lại")
    return len(ids)
