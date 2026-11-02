"""Explain local scheduling bottlenecks without claiming a minimal unsat core."""

from collections import defaultdict

from .models import LecturerPreference, Period, ScheduleEntry, TeachingQualification


def _overlap(a_start, a_count, b_start, b_count):
    return a_start < b_start + b_count and b_start < a_start + a_count


def forced_day_overloads(semester, demands):
    """Prove a clash when sessions forced onto one day exceed its period budget."""
    capacity = Period.objects.count()
    if not capacity:
        return {}
    loads = defaultdict(int)
    members = defaultdict(set)

    def add(resource, day, weeks, count, index=None):
        for week in weeks:
            key = (*resource, day, week)
            loads[key] += count
            if index is not None:
                members[key].add(index)

    fixed = (ScheduleEntry.objects.filter(group__semester=semester)
             .exclude(source="ThuatToan", status="ChoDuyet")
             .prefetch_related("schedule_weeks", "group__cohort_links"))
    for entry in fixed:
        weeks = [item.week for item in entry.schedule_weeks.all()]
        add(("nhóm", entry.group_id), entry.day, weeks, entry.period_count)
        for link in entry.group.cohort_links.all():
            add(("lớp", link.cohort_id), entry.day, weeks, entry.period_count)
    for index, demand in enumerate(demands):
        if len(demand["days"]) != 1:
            continue
        day = next(iter(demand["days"]))
        add(("nhóm", demand["group"].pk), day, demand["weeks"], demand["count"], index)
        for link in demand["group"].cohort_links.all():
            add(("lớp", link.cohort_id), day, demand["weeks"], demand["count"], index)

    conflicts = {}
    for (kind, resource_id, day, week), total in loads.items():
        if total > capacity:
            for index in members[(kind, resource_id, day, week)]:
                conflicts.setdefault(index, (kind, day, week, total, capacity))
    return conflicts


def diagnose(semester, demands, room_map, teacher_map, room_blocks, teacher_blocks,
             allowed_pairs, *, preferences=None):
    """Return one factual, actionable row per requested session.

    Candidate counts consider one session in isolation against fixed schedules.
    They do not imply that all sessions can be scheduled together.
    """
    periods = {period.pk: period for period in Period.objects.all()}
    teacher_ids = {teacher.pk for teacher in teacher_map.values()}
    qualifications = defaultdict(list)
    for row in TeachingQualification.objects.filter(lecturer_id__in=teacher_ids).select_related("lecturer", "course"):
        if (row.lecturer.status == "DangCongTac" and
                (row.lecturer.employee_code, row.course.code) in allowed_pairs):
            qualifications[row.course_id].append(row.lecturer)

    room_busy, teacher_busy = defaultdict(list), defaultdict(list)
    for code, day, start, count, weeks in room_blocks:
        for week in weeks:
            room_busy[(room_map[code].pk, day, week)].append((start, count))
    for code, day, start, count, weeks in teacher_blocks:
        for week in weeks:
            teacher_busy[(teacher_map[code].pk, day, week)].append((start, count))
    if preferences is None:
        preferences = list(LecturerPreference.objects.filter(semester=semester))
    for pref in preferences:
        if pref.kind != "NgayNghi":
            continue
        if pref.day:
            for week in range(1, semester.week_count + 1):
                teacher_busy[(pref.lecturer_id, pref.day, week)].append((1, 13))

    fixed = []
    entries = (ScheduleEntry.objects.filter(group__semester=semester)
               .exclude(source="ThuatToan", status="ChoDuyet")
               .prefetch_related("schedule_weeks", "group__cohort_links"))
    for entry in entries:
        fixed.append((entry.day, entry.start_period_id, entry.period_count,
                      frozenset(item.week for item in entry.schedule_weeks.all()),
                      entry.group_id, frozenset(link.cohort_id for link in entry.group.cohort_links.all()),
                      entry.room_id, entry.lecturer_id))

    def is_busy(buckets, resource_id, day, start, count, weeks):
        return any(_overlap(start, count, busy_start, busy_count)
                   for week in weeks
                   for busy_start, busy_count in buckets[(resource_id, day, week)])

    overloads = forced_day_overloads(semester, demands)
    rows = []
    for index, demand in enumerate(demands):
        group = demand["group"]
        weeks, count = demand["weeks"], demand["count"]
        cohort_ids = frozenset(link.cohort_id for link in group.cohort_links.all())
        times = [(day, start) for day in demand["days"] for start in sorted(periods)
                 if all(number in periods and periods[number].block == periods[start].block
                        for number in range(start, start + count))]
        rooms = [room for room in room_map.values() if room.status == "SanSang"
                 and room.capacity >= group.capacity
                 and (not demand["room_type"] or room.room_type == demand["room_type"])]
        teachers = qualifications[group.course_id]
        if demand.get("assigned_teacher") is not None:
            teachers = [t for t in teachers if t.pk == demand["assigned_teacher"].pk]
        times = [(day, start) for day, start in times
                 if not any((day, week) in demand.get("activity_blocks", set()) for week in weeks)]
        free_group_times = 0
        times_with_room = times_with_teacher = combinations = 0
        for day, start in times:
            overlapping = [entry for entry in fixed if entry[0] == day
                           and weeks.intersection(entry[3])
                           and _overlap(start, count, entry[1], entry[2])]
            if any(entry[4] == group.pk or cohort_ids & entry[5] for entry in overlapping):
                continue
            free_group_times += 1
            available_rooms = sum(
                not is_busy(room_busy, room.pk, day, start, count, weeks)
                and all(entry[6] != room.pk for entry in overlapping)
                for room in rooms
            )
            available_teachers = sum(
                not is_busy(teacher_busy, teacher.pk, day, start, count, weeks)
                and all(entry[7] != teacher.pk for entry in overlapping)
                for teacher in teachers
            )
            times_with_room += bool(available_rooms)
            times_with_teacher += bool(available_teachers)
            combinations += available_rooms * available_teachers

        if index in overloads:
            kind, day, week, total, capacity = overloads[index]
            reason = (f"Các buổi bắt buộc của cùng {kind} vào thứ {day}, tuần {week} "
                      f"cần {total} tiết nhưng ngày chỉ có {capacity} tiết.")
            suggestion = "Nới thu_duoc_xep hoặc giảm số tiết bắt buộc trong ngày."
        elif not times:
            reason = "Không có dãy tiết liên tiếp cùng ca trong các thứ được phép."
            suggestion = "Kiểm tra so_tiet, thu_duoc_xep và cấu hình tiết học."
        elif not rooms:
            reason = "Không có phòng sẵn sàng đủ sức chứa và đúng loại."
            suggestion = "Kiểm tra PhongHoc, sức chứa và loai_phong."
        elif not teachers:
            reason = "Không có giảng viên đang công tác đủ chuyên môn trong file."
            suggestion = "Kiểm tra GiangVien và GiangVienHocPhan."
        elif not free_group_times:
            reason = "Mọi khung tiết đều trùng lịch cố định của nhóm hoặc lớp hành chính."
            suggestion = "Kiểm tra lịch đã duyệt và thu_duoc_xep."
        elif not times_with_room:
            reason = "Phòng phù hợp đều bận hoặc không khả dụng ở các khung tiết còn lại."
            suggestion = "Kiểm tra PhongKhongKhaDung, lịch phòng đã duyệt hoặc bổ sung phòng."
        elif not times_with_teacher:
            reason = "Giảng viên đủ chuyên môn đều bận hoặc không khả dụng ở các khung tiết còn lại."
            suggestion = "Kiểm tra GiangVienKhongKhaDung, NgayNghi và lịch giảng viên đã duyệt."
        elif not combinations:
            reason = "Không có cùng một khung tiết mà cả phòng và giảng viên đều trống."
            suggestion = "Nới thu_duoc_xep hoặc điều chỉnh thời gian không khả dụng."
        else:
            reason = (f"Có {combinations} cách xếp riêng lẻ; chưa xác định được buổi nào "
                      "gây xung đột khi xếp tất cả cùng lúc.")
            suggestion = "Kiểm tra các buổi dùng chung phòng, giảng viên hoặc lớp hành chính."
        rows.append({
            "excel_row": demand.get("line"),
            "course": group.course.code,
            "group": group.group,
            "lab_group": group.lab_group or "",
            "session": demand["code"],
            "candidate_count": combinations,
            "reason": reason,
            "suggestion": suggestion,
        })
    return rows
