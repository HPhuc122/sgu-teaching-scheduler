"""Luu lich trong giao dich va kiem tra xung dot truoc khi ghi."""

from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from scheduling.validation import TeachingSession, conflicts_for_candidate

from .models import ScheduleEntry, ScheduleWeek, Semester, TeachingQualification
from .preference_checks import day_off_error, day_off_violations


class ScheduleConflictError(Exception):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__("Lịch học bị trùng")


def _to_session(entry, *, weeks=None, cohort_ids=None):
    if weeks is None:
        weeks = {item.week for item in entry.schedule_weeks.all()}
    if cohort_ids is None:
        cohort_ids = {link.cohort_id for link in entry.group.cohort_links.all()}
    return TeachingSession(
        session_id=entry.pk,
        semester_id=entry.group.semester_id,
        course_group_id=entry.group_id,
        day=entry.day,
        start_period=entry.start_period_id,
        period_count=entry.period_count,
        weeks=frozenset(weeks),
        teacher_id=entry.lecturer_id,
        room_id=entry.room_id,
        class_ids=frozenset(cohort_ids),
    )


@transaction.atomic
def save_schedule_entry(data, *, instance=None, actor=None):
    values = dict(data)
    if actor is not None:
        from .access import check_write, require_object
        check_write(actor, ScheduleEntry, values, instance, "change" if instance else "add")
        if values.get("status") == "DaDuyet" and (instance is None or instance.status != "DaDuyet"):
            group = values.get("group") or instance.group
            require_object(actor, group, "approve")
            teacher = values.get("lecturer") or (instance.lecturer if instance else None)
            if teacher:
                require_object(actor, teacher, "approve")
    weeks = values.pop("weeks", None)
    group = values.get("group") or instance.group
    # Moi thao tac cung hoc ky lay cung mot khoa; tranh doc lich cu dong thoi.
    semester = Semester.objects.select_for_update().get(pk=group.semester_id)
    if semester.status == "DaKhoa":
        raise ValidationError("Học kỳ đã khóa")
    if instance:
        instance = ScheduleEntry.objects.select_for_update().get(pk=instance.pk)
        previous_status = instance.status
        previous_values = (instance.group_id, instance.lecturer_id, instance.room_id,
                           instance.other_location, instance.day, instance.start_period_id,
                           instance.period_count)
        previous_weeks = set(ScheduleWeek.objects.filter(entry=instance).values_list("week", flat=True))
    else:
        previous_status = None
        previous_values = None
        previous_weeks = set()

    entry = instance if instance else ScheduleEntry()
    for field, value in values.items():
        setattr(entry, field, value)
    entry.group = group
    if weeks is None:
        weeks = list(ScheduleWeek.objects.filter(entry=instance).values_list("week", flat=True))
    from .planning import check_entry_plan
    try:
        check_entry_plan(entry, weeks)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    current_values = (entry.group_id, entry.lecturer_id, entry.room_id, entry.other_location,
                      entry.day, entry.start_period_id, entry.period_count)
    materially_changed = (previous_values is not None and
                          (previous_values != current_values or previous_weeks != set(weeks)))
    if previous_status == "DaDuyet" and materially_changed:
        entry.status = "ChoDuyet"
    if entry.status not in ("ChoDuyet", "DaDuyet"):
        raise ValidationError({"status": "Trạng thái lịch không hợp lệ"})
    if entry.status == "DaDuyet" and previous_status != "DaDuyet":
        if actor is None or not actor.is_authenticated or not actor.is_staff:
            raise ValidationError({"status": "Cần tài khoản quản trị để duyệt lịch"})
        entry.approved_by = actor
        entry.approved_at = timezone.now()
    elif entry.status != "DaDuyet":
        entry.approved_by = None
        entry.approved_at = None
    if entry.status == "DaDuyet" and entry.lecturer_id is None:
        raise ValidationError({"lecturer": "Lịch đã duyệt phải có giảng viên"})
    if entry.status == "DaDuyet" and previous_status != "DaDuyet":
        violations = day_off_violations(semester.pk, [entry])
        if violations:
            raise ValidationError(day_off_error(violations))
    if entry.lecturer_id is not None and entry.lecturer.status != "DangCongTac":
        raise ValidationError({"lecturer": "Giảng viên không ở trạng thái công tác"})
    if entry.lecturer_id is not None and not TeachingQualification.objects.filter(
        lecturer_id=entry.lecturer_id, course_id=group.course_id
    ).exists():
        raise ValidationError({"lecturer": "Giảng viên chưa được xác nhận chuyên môn cho học phần"})
    if entry.room_id is not None and entry.room.status != "SanSang":
        raise ValidationError({"room": "Phòng chưa sẵn sàng"})
    if group.needs_room and entry.room_id is None and not entry.other_location:
        raise ValidationError({"room": "Nhóm này cần phòng hoặc địa điểm học"})
    if entry.room_id is not None and entry.other_location:
        raise ValidationError({"other_location": "Chỉ chọn phòng hoặc địa điểm khác"})

    cohort_ids = set(group.cohort_links.values_list("cohort_id", flat=True))
    candidate = _to_session(entry, weeks=weeks, cohort_ids=cohort_ids)
    existing = (ScheduleEntry.objects.filter(group__semester=semester, day=entry.day)
                .exclude(pk=instance.pk if instance else None)
                .select_related("group")
                .prefetch_related("schedule_weeks", "group__cohort_links"))
    try:
        conflicts = conflicts_for_candidate(candidate, (_to_session(other) for other in existing),
                                            semester.week_count)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if conflicts:
        raise ScheduleConflictError([
            {"kind": conflict.kind, "entry_id": conflict.second_session_id,
             "weeks": sorted(conflict.weeks)} for conflict in conflicts
        ])

    try:
        entry.full_clean(exclude=["source"])
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict) from exc
    entry.save()
    if entry.request_code:
        from .models import TeachingAssignment
        TeachingAssignment.objects.filter(group=entry.group, request_code=entry.request_code).update(lecturer=entry.lecturer)
    ScheduleWeek.objects.filter(entry=entry).delete()
    ScheduleWeek.objects.bulk_create([ScheduleWeek(entry=entry, week=week) for week in weeks])
    return entry


@transaction.atomic
def approve_schedule_entries(semester_id, entry_ids, *, actor):
    if actor is None or not actor.is_authenticated or not actor.is_staff:
        raise ValidationError("Chỉ quản trị viên được duyệt lịch")
    ids = list(entry_ids)
    if not ids or len(ids) > 100 or len(ids) != len(set(ids)):
        raise ValidationError("Chọn từ 1 đến 100 buổi dạy, không lặp")
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    if semester.status == "DaKhoa":
        raise ValidationError("Học kỳ đã khóa")
    entries = list(ScheduleEntry.objects.select_for_update().filter(pk__in=ids)
                   .select_related("group").order_by("pk"))
    from .access import require_object
    for entry in entries:
        require_object(actor, entry, "approve")
    if len(entries) != len(ids) or any(entry.group.semester_id != semester_id for entry in entries):
        raise ValidationError("Danh sách duyệt có buổi không thuộc học kỳ đã chọn")
    if any(entry.status != "ChoDuyet" for entry in entries):
        raise ValidationError("Chỉ được duyệt lịch đang chờ duyệt")
    violations = day_off_violations(semester_id, entries)
    if violations:
        raise ValidationError(day_off_error(violations))
    for entry in entries:
        save_schedule_entry({"status": "DaDuyet"}, instance=entry, actor=actor)
    return len(entries)
