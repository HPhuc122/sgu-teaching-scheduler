"""Provisional faculty assignment report based on approved schedule entries."""

from collections import defaultdict
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


DETAIL_HEADERS = (
    "STT", "Mã MH", "Tên môn học", "Số TC", "Sĩ số dự kiến", "Họ và tên GV",
    "Mã viên chức", "Nhóm", "Tổ TH", "Thứ", "Tiết BĐ", "Số tiết/buổi",
    "Mã phòng / địa điểm", "Tên lớp", "Tuần học", "Tổng tiết theo lịch",
)
SUMMARY_HEADERS = ("STT", "Mã viên chức", "Họ và tên GV", "Số dòng phân công", "Tổng tiết theo lịch")


def approved_assignments(semester, faculty):
    from .models import ScheduleEntry

    return list(
        ScheduleEntry.objects.filter(
            status="DaDuyet", group__semester=semester,
            lecturer__department__faculty=faculty,
        ).select_related("group__course", "lecturer", "room")
        .prefetch_related("schedule_weeks", "group__cohort_links__cohort")
        .order_by("lecturer__employee_code", "lecturer__name", "group__course__code",
                  "group__group", "group__lab_group", "day", "start_period_id", "pk")
    )


def assignment_rows(entries):
    rows = []
    totals = defaultdict(lambda: {"code": "", "name": "", "sessions": 0, "periods": 0})
    for index, entry in enumerate(entries, 1):
        weeks = sorted(week.week for week in entry.schedule_weeks.all())
        periods = entry.period_count * len(weeks)
        cohorts = sorted({link.cohort.name for link in entry.group.cohort_links.all()})
        lecturer = entry.lecturer
        rows.append((
            index, entry.group.course.code, entry.group.course.name, entry.group.course.credits,
            entry.group.capacity, lecturer.name, lecturer.employee_code or "", entry.group.group,
            entry.group.lab_group or "", entry.day, entry.start_period_id, entry.period_count,
            entry.room.code if entry.room_id else (entry.other_location or ""),
            "; ".join(cohorts), ",".join(map(str, weeks)), periods,
        ))
        item = totals[lecturer.pk]
        item["code"] = lecturer.employee_code or ""
        item["name"] = lecturer.name
        item["sessions"] += 1
        item["periods"] += periods
    summary = [
        (index, item["code"], item["name"], item["sessions"], item["periods"])
        for index, item in enumerate(totals.values(), 1)
    ]
    return rows, summary


def _safe_cell(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _style_table(sheet, headers, rows, widths):
    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="164B6B")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 32
    for row in rows:
        sheet.append([_safe_cell(value) for value in row])
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "D2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(sheet.max_row, 1)}"
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = "1:1"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_setup.orientation = "landscape"


def assignment_workbook_bytes(semester, faculty, entries, completeness=None):
    detail_rows, summary_rows = assignment_rows(entries)
    workbook = Workbook()
    detail = workbook.active
    detail.title = "PhanCong"
    _style_table(detail, DETAIL_HEADERS, detail_rows,
                 (6, 14, 36, 9, 16, 26, 16, 9, 9, 8, 10, 14, 22, 25, 24, 19))
    summary = workbook.create_sheet("TongHopGV")
    _style_table(summary, SUMMARY_HEADERS, summary_rows, (6, 16, 30, 17, 21))
    note = workbook.create_sheet("ThongTin")
    info = (
        ("BẢNG PHÂN CÔNG GIẢNG DẠY – MẪU XUẤT ĐỀ XUẤT",),
        ("Học kỳ", semester.name),
        ("Năm học", semester.academic_year),
        ("Khoa quản lý giảng viên", faculty.name),
        ("Phạm vi", "Chỉ các buổi đã duyệt của giảng viên thuộc khoa"),
        ("Tổng tiết theo lịch", "Số tiết/buổi × số tuần đã xếp; chưa quy đổi giờ giảng"),
        ("Nguồn cột", "Các trường thời khóa biểu công khai SGU X5110AB.006 và X5010B.001"),
        ("Lưu ý", "Chưa xác minh biểu mẫu phân công giảng dạy nội bộ chính thức của SGU"),
    )
    for row in info:
        note.append([_safe_cell(value) for value in row])
    if completeness is not None:
        note.append(("Kiểm tra toàn học kỳ",
                     "Đủ theo buổi yêu cầu đã lưu" if completeness["ready"] else
                     "CHƯA XÁC NHẬN ĐẦY ĐỦ – xem các dòng kiểm tra bên dưới"))
        note.append(("Buổi yêu cầu", completeness["expected"]))
        note.append(("Đã duyệt đúng yêu cầu", completeness["counts"]["approved"]))
        note.append(("Thiếu lịch", completeness["counts"]["missing"]))
        note.append(("Chờ duyệt theo yêu cầu", completeness["counts"]["pending"]))
        note.append(("Mã buổi trùng lịch", completeness["counts"]["duplicate"]))
        note.append(("Nhóm chưa có yêu cầu lưu", len(completeness["unknown_groups"])))
        note.append(("Tổng buổi chờ duyệt", len(completeness["pending_entries"])))
        note.append(("Phạm vi kiểm tra", "Toàn học kỳ; buổi chưa có giảng viên chưa thể gắn cho một khoa"))
    note.column_dimensions["A"].width = 28
    note.column_dimensions["B"].width = 75
    note["A1"].font = Font(bold=True, size=14, color="164B6B")
    note.sheet_view.showGridLines = False
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
