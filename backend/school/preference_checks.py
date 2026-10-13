"""Hard lecturer availability checks shared by every approval path."""

from .models import LecturerPreference


def day_off_violations(semester_id, entries):
    """Return scheduled entries that fall on a lecturer's unavailable day."""
    entries = list(entries)
    lecturer_ids = {entry.lecturer_id for entry in entries if entry.lecturer_id}
    if not lecturer_ids:
        return []
    unavailable = set(LecturerPreference.objects.filter(
        semester_id=semester_id, lecturer_id__in=lecturer_ids,
        kind="NgayNghi", day__isnull=False,
    ).values_list("lecturer_id", "day"))
    return [entry for entry in entries
            if (entry.lecturer_id, entry.day) in unavailable]


def day_off_error(violations):
    details = []
    for entry in violations[:20]:
        label = f"Buổi #{entry.pk}" if entry.pk else "Buổi mới"
        details.append(
            f"{label} ({entry.group.course.code}/{entry.group.group}, "
            f"{entry.lecturer.name}, thứ {entry.day})"
        )
    more = f"; và {len(violations) - 20} buổi khác" if len(violations) > 20 else ""
    return ("Trùng ngày giảng viên không thể dạy: " + "; ".join(details) + more
            + ". Hãy sửa lịch trước khi duyệt; trang rà soát liệt kê đầy đủ các buổi vi phạm.")
