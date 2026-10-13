"""Read and validate a small, explicit XLSX schedule import format."""

from io import BytesIO

from openpyxl import Workbook, load_workbook

from scheduling.validation import TeachingSession, conflicts_for_candidate

from .models import CourseGroup, Lecturer, Period, Room, ScheduleEntry, Semester, TeachingQualification
from .services import _to_session


HEADERS = ("ma_mon_hoc", "nhom", "to_th", "ma_vien_chuc", "ma_phong", "thu",
           "tiet_bat_dau", "so_tiet", "tuan_hoc", "dia_diem_khac")
MAX_ROWS = 500
MAX_BYTES = 2 * 1024 * 1024


def template_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Lich giang day"
    sheet.append(HEADERS)
    sheet.freeze_panes = "A2"
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = max(16, len(str(column[0].value)) + 2)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def parse_weeks(value):
    if value is None or str(value).strip() == "":
        raise ValueError("Thiếu tuần học")
    weeks = set()
    for part in str(value).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            raise ValueError("Định dạng tuần học không hợp lệ")
        pieces = part.split("-")
        if len(pieces) > 2 or any(not piece.strip().isdigit() for piece in pieces):
            raise ValueError("Tuần học phải có dạng 1-10,12,14-16")
        start = int(pieces[0])
        end = int(pieces[-1])
        if start < 1 or end < start or end > 53:
            raise ValueError("Khoảng tuần học không hợp lệ")
        weeks.update(range(start, end + 1))
    return sorted(weeks)


def _integer(value, label):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} phải là số nguyên")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} phải là số nguyên") from exc
    if str(value).strip() != str(number) and not (isinstance(value, float) and value.is_integer()):
        raise ValueError(f"{label} phải là số nguyên")
    return number


def read_excel(upload):
    if not upload.name.lower().endswith(".xlsx"):
        raise ValueError("Chỉ nhận file .xlsx")
    if upload.size > MAX_BYTES:
        raise ValueError("File vượt giới hạn 2 MB")
    try:
        workbook = load_workbook(upload, read_only=True, data_only=True)
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        header = next(iterator, None)
        if header is None or tuple(str(cell or "").strip() for cell in header[:len(HEADERS)]) != HEADERS:
            raise ValueError("Tiêu đề cột không khớp mẫu Excel")
        if any(cell not in (None, "") for cell in header[len(HEADERS):]):
            raise ValueError("File có cột ngoài mẫu Excel")
        rows = []
        for row_number, cells in enumerate(iterator, start=2):
            if row_number > MAX_ROWS + 100:
                raise ValueError("File có quá nhiều dòng; hãy xóa các dòng trống dư")
            if all(cell is None or str(cell).strip() == "" for cell in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise ValueError("Mỗi lần chỉ nhập tối đa 500 dòng")
            if any(cell not in (None, "") for cell in cells[len(HEADERS):]):
                raise ValueError(f"Dòng {row_number} có dữ liệu ngoài các cột mẫu")
            values = list(cells[:len(HEADERS)])
            values += [None] * (len(HEADERS) - len(values))
            for key, value in zip(HEADERS, values):
                if (key.startswith("ma_") or key in ("nhom", "to_th")) and isinstance(value, (int, float)):
                    raise ValueError(f"Dòng {row_number}: cột {key} phải đặt định dạng văn bản để giữ số 0 đầu")
            rows.append({"line": row_number, **{
                key: str(value).strip() if value is not None else ""
                for key, value in zip(HEADERS, values)
            }})
        if not rows:
            raise ValueError("File không có dòng dữ liệu")
        return rows
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Không đọc được file Excel hợp lệ") from exc
    finally:
        if "workbook" in locals():
            workbook.close()


def validate_rows(semester, rows):
    """Return resolved entries and row-specific errors; does not write to the database."""
    groups = {}
    duplicate_groups = set()
    for group in CourseGroup.objects.filter(semester=semester).select_related("course").prefetch_related("cohort_links"):
        key = (group.course.code, group.group, group.lab_group or "")
        if key in groups:
            duplicate_groups.add(key)
        groups[key] = group
    lecturers = {lecturer.employee_code: lecturer for lecturer in Lecturer.objects.all() if lecturer.employee_code}
    rooms = {room.code: room for room in Room.objects.all()}
    period_ids = set(Period.objects.values_list("id", flat=True))
    qualifications = set(TeachingQualification.objects.values_list("lecturer_id", "course_id"))
    existing = [_to_session(entry) for entry in ScheduleEntry.objects.filter(group__semester=semester)
                .select_related("group").prefetch_related("schedule_weeks", "group__cohort_links")]
    seen = list(existing)
    resolved = []
    errors = []
    if semester.status == "DaKhoa":
        return [], [{"line": None, "message": "Học kỳ đã khóa"}]
    for row in rows:
        line = row["line"]
        try:
            key = (row["ma_mon_hoc"], row["nhom"], row["to_th"])
            group = groups.get(key)
            if group is None:
                raise ValueError("Mã môn, nhóm và tổ TH không thuộc học kỳ đã chọn")
            if key in duplicate_groups:
                raise ValueError("Mã môn, nhóm và tổ TH bị lặp trong học kỳ")
            lecturer = lecturers.get(row["ma_vien_chuc"])
            if lecturer is None:
                raise ValueError("Không tìm thấy mã giảng viên")
            if lecturer.status != "DangCongTac":
                raise ValueError("Giảng viên không ở trạng thái công tác")
            if (lecturer.pk, group.course_id) not in qualifications:
                raise ValueError("Giảng viên chưa được xác nhận chuyên môn cho học phần")
            room_code = row["ma_phong"]
            room = rooms.get(room_code) if room_code else None
            other_location = row["dia_diem_khac"]
            if room_code and room is None:
                raise ValueError("Không tìm thấy mã phòng")
            if room is not None and room.status != "SanSang":
                raise ValueError("Phòng chưa sẵn sàng")
            if room is not None and other_location:
                raise ValueError("Chỉ chọn phòng hoặc địa điểm khác")
            if group.needs_room and room is None and not other_location:
                raise ValueError("Nhóm này cần phòng hoặc địa điểm học")
            day = _integer(row["thu"], "Thứ")
            start = _integer(row["tiet_bat_dau"], "Tiết bắt đầu")
            count = _integer(row["so_tiet"], "Số tiết")
            weeks = parse_weeks(row["tuan_hoc"])
            if start < 1 or count < 1 or start + count > 14:
                raise ValueError("Tiết học phải nằm trong khoảng 1-13")
            if any(period not in period_ids for period in range(start, start + count)):
                raise ValueError("Có tiết học chưa được cấu hình")
            candidate = TeachingSession(
                session_id=f"dòng {line}", semester_id=semester.pk, course_group_id=group.pk,
                day=day, start_period=start, period_count=count, weeks=frozenset(weeks),
                teacher_id=lecturer.pk, room_id=room.pk if room else None,
                class_ids=frozenset(link.cohort_id for link in group.cohort_links.all()),
            )
            conflicts = conflicts_for_candidate(candidate, seen, semester.week_count)
            if conflicts:
                first = conflicts[0]
                raise ValueError(f"Trùng {first.kind} với lịch {first.second_session_id}, tuần "
                                 f"{','.join(map(str, sorted(first.weeks)))}")
            resolved.append({"line": line, "group": group, "lecturer": lecturer, "room": room,
                             "other_location": other_location or None, "day": day,
                             "start_period_id": start, "period_count": count, "weeks": weeks})
            seen.append(candidate)
        except ValueError as exc:
            errors.append({"line": line, "message": str(exc)})
    return resolved, errors
