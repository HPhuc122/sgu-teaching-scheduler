"""Independent hard-rule audit before any generated timetable is persisted."""

from .models import LecturerPreference, Period, ScheduleEntry, TeachingQualification


def _overlap(a_start, a_count, b_start, b_count):
    return a_start < b_start + b_count and b_start < a_start + a_count


def audit_solution(semester, demands, result, room_map, teacher_map, room_blocks,
                   teacher_blocks, allowed_pairs, *, preferences=None):
    from .planning import activity_blocks
    blocked_dates = activity_blocks(semester)
    if len(result) != len(demands) or any(item[0] is not demand
                                           for demand, item in zip(demands, result)):
        raise ValueError("Phương án không chứa đúng từng buổi yêu cầu")
    periods = {period.pk: period for period in Period.objects.all()}
    room_ids = {room.pk for room in room_map.values()}
    teacher_ids = {teacher.pk for teacher in teacher_map.values()}
    qualified = {(row.lecturer_id, row.course_id) for row in
                 TeachingQualification.objects.filter(lecturer_id__in=teacher_ids)
                 .select_related("lecturer", "course")
                 if (row.lecturer.employee_code, row.course.code) in allowed_pairs}
    room_busy = {}
    teacher_busy = {}
    for code, day, start, count, weeks in room_blocks:
        room = room_map[code]
        for week in weeks:
            room_busy.setdefault((room.pk, day, week), []).append((start, count))
    for code, day, start, count, weeks in teacher_blocks:
        teacher = teacher_map[code]
        for week in weeks:
            teacher_busy.setdefault((teacher.pk, day, week), []).append((start, count))
    if preferences is None:
        preferences = list(LecturerPreference.objects.filter(semester=semester))
    for pref in preferences:
        if pref.kind != "NgayNghi":
            continue
        if pref.day:
            for week in range(1, semester.week_count + 1):
                teacher_busy.setdefault((pref.lecturer_id, pref.day, week), []).append((1, 13))

    occupied = set()

    def reserve(kind, resource_id, day, start, count, weeks):
        if resource_id is None:
            return
        for week in weeks:
            for period in range(start, start + count):
                key = kind, resource_id, day, week, period
                if key in occupied:
                    raise ValueError(f"Phương án trùng {kind} ở thứ {day}, tiết {period}, tuần {week}")
                occupied.add(key)

    fixed = (ScheduleEntry.objects.filter(group__semester=semester)
             .exclude(source="ThuatToan", status="ChoDuyet")
             .prefetch_related("schedule_weeks", "group__cohort_links"))
    for entry in fixed:
        weeks = [item.week for item in entry.schedule_weeks.all()]
        reserve("nhóm", entry.group_id, entry.day, entry.start_period_id, entry.period_count, weeks)
        reserve("phòng", entry.room_id, entry.day, entry.start_period_id, entry.period_count, weeks)
        reserve("giảng viên", entry.lecturer_id, entry.day, entry.start_period_id, entry.period_count, weeks)
        for link in entry.group.cohort_links.all():
            reserve("lớp", link.cohort_id, entry.day, entry.start_period_id, entry.period_count, weeks)

    for demand, day, start, room, teacher in result:
        group = demand["group"]
        count, weeks = demand["count"], demand["weeks"]
        label = f"{group.course.code}/{group.group}/{demand['code']}"
        if demand.get("assigned_teacher") is not None and teacher.pk != demand["assigned_teacher"].pk:
            raise ValueError(f"Buổi {label}: giảng viên khác phân công cố định")
        if any((day, week) in blocked_dates.get(group.pk, set()) for week in weeks):
            raise ValueError(f"Buổi {label}: trùng hoạt động ngoài trường của lớp")
        if day not in demand["days"] or day not in range(2, 9):
            raise ValueError(f"Buổi {label}: thứ nằm ngoài phạm vi cho phép")
        if start not in periods or any(
                number not in periods or periods[number].block != periods[start].block
                for number in range(start, start + count)):
            raise ValueError(f"Buổi {label}: tiết không liên tiếp trong cùng ca")
        if not weeks or min(weeks) < 1 or max(weeks) > semester.week_count:
            raise ValueError(f"Buổi {label}: tuần nằm ngoài học kỳ")
        if (room.pk not in room_ids or room.status != "SanSang" or
                room.capacity < group.capacity or
                (demand["room_type"] and room.room_type != demand["room_type"])):
            raise ValueError(f"Buổi {label}: phòng không phù hợp")
        if (teacher.pk not in teacher_ids or teacher.status != "DangCongTac" or
                (teacher.pk, group.course_id) not in qualified):
            raise ValueError(f"Buổi {label}: giảng viên không đủ điều kiện")
        for week in weeks:
            if any(_overlap(start, count, busy_start, busy_count)
                   for busy_start, busy_count in room_busy.get((room.pk, day, week), ())):
                raise ValueError(f"Buổi {label}: phòng không khả dụng tuần {week}")
            if any(_overlap(start, count, busy_start, busy_count)
                   for busy_start, busy_count in teacher_busy.get((teacher.pk, day, week), ())):
                raise ValueError(f"Buổi {label}: giảng viên không khả dụng tuần {week}")
        reserve("nhóm", group.pk, day, start, count, weeks)
        reserve("phòng", room.pk, day, start, count, weeks)
        reserve("giảng viên", teacher.pk, day, start, count, weeks)
        for link in group.cohort_links.all():
            reserve("lớp", link.cohort_id, day, start, count, weeks)
