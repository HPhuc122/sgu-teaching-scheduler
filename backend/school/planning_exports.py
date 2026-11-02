"""Five form structures transcribed from supplied photographs; no source records."""
from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from .planning import appointment_kind, planned_periods


def semester_number(a):
    return a.group.semester.number or (getattr(a.group, "teaching_plan", None).semester_number
                                      if getattr(a.group, "teaching_plan", None) else None)


def _sum_explicit(values):
    values = list(values)
    return sum(values, Decimal(0)) if values and all(v is not None for v in values) else None


def _course_periods(plan):
    if plan is None:
        return None
    return _sum_explicit([plan.lecture_periods, plan.exercise_periods, plan.practical_periods])


def _safe(value):
    return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value


def _sheet(book, name, title, faculty, year, headers, rows, subtitle=""):
    sheet = book.create_sheet(name)
    last = len(headers)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last)
    sheet.cell(1, 1, "TRƯỜNG ĐẠI HỌC SÀI GÒN")
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last)
    sheet.cell(2, 1, _safe(f"Đơn vị: {faculty.name} · Năm học {year}"))
    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=last)
    sheet.cell(3, 1, title)
    sheet.merge_cells(start_row=4, start_column=1, end_row=4, end_column=last)
    sheet.cell(4, 1, _safe(subtitle or "Kế hoạch phân công giảng dạy"))
    sheet.append(headers)
    for row in rows:
        sheet.append([_safe(v) for v in row])
    thin = Side(style="thin", color="000000")
    for row in sheet:
        for cell in row:
            cell.font = Font(name="Times New Roman", size=12, color="000000", bold=cell.row in (1, 3, 5))
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center" if cell.row <= 5 else "left")
            if cell.row >= 5:
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for i, header in enumerate(headers, 1):
        sheet.column_dimensions[get_column_letter(i)].width = 30 if any(word in header for word in ("Tên", "Họ", "Nội dung", "Ghi chú", "Đơn vị", "Công tác")) else 15
    sheet.row_dimensions[3].height = 36
    sheet.row_dimensions[5].height = 75
    sheet.freeze_panes = "D6"
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = "1:5"
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
    sheet.print_area = f"A1:{get_column_letter(last)}{sheet.max_row}"
    return sheet


def forms_workbook(faculty, year, assignments, activities, duties):
    assignments, activities, duties = list(assignments), list(activities), list(duties)
    book = Workbook()
    book.remove(book.active)
    own = [a for a in assignments if a.group.course.department.faculty_id == faculty.pk]
    # Every semester remains separate even when exporting one academic year.
    for number in (1, 2, 3, None):
        selected = [a for a in own if semester_number(a) == number]
        if number is None and not selected:
            continue
        buckets = defaultdict(list)
        for a in selected:
            buckets[(a.group_id, a.lecturer_id, a.component)].append(a)
        rows = []
        for index, items in enumerate(buckets.values(), 1):
            a, group = items[0], items[0].group
            plan = getattr(group, "teaching_plan", None)
            teacher = a.lecturer
            group_count = len({x.group_id for x in selected if x.group.course_id == group.course_id})
            rows.append((index, group.course.code, group.course.name, group.course.credits,
                plan.cohort_label if plan else "", plan.lecture_periods if plan else None,
                plan.exercise_periods if plan else None, plan.practical_periods if plan else None,
                _course_periods(plan), plan.coefficient if plan else None, group_count, group.capacity,
                group.group + (f"/{group.lab_group}" if group.lab_group else ""), a.component,
                teacher.employee_code if teacher else "", teacher.name if teacher else "",
                sum(planned_periods(x) for x in items), _sum_explicit(x.reported_periods for x in items), plan.note if plan else ""))
        _sheet(book, f"Mau1_HK{number or 'ChuaGan'}", "KẾ HOẠCH MỞ NHÓM MÔN CHUYÊN NGÀNH", faculty, year,
            ("STT", "Mã HP", "Tên học phần", "Số TC", "Khóa", "Số tiết LT", "Số tiết BT", "Số tiết TH", "Tổng tiết HP",
             "Hệ số HP", "Tổng số nhóm", "SLSV/Nhóm", "Nhóm/Tổ TH", "Loại buổi", "Mã CBGD", "Họ và tên CBGD",
             "Số tiết thực hiện", "Số tiết thực tế", "Ghi chú"), rows, f"Học kỳ {number or 'chưa gán số'}")
    buckets = defaultdict(list)
    for a in assignments:
        if not a.lecturer_id:
            continue
        if a.lecturer.source_kind == "CO_HUU" and a.lecturer.department.faculty_id == faculty.pk:
            buckets[("CO_HUU", a.lecturer_id, a.group.course_id)].append(a)
        elif a in own:
            buckets[(appointment_kind(a), a.lecturer_id, a.group.course_id)].append(a)
    duty_map = defaultdict(list)
    for duty in duties:
        duty_map[duty.lecturer_id].append(duty)
    rows2, rows3, rows4 = [], [], []
    displayed_duties = set()
    for (kind, _teacher_id, _course_id), items in buckets.items():
        a, teacher = items[0], items[0].lecturer
        plan = getattr(a.group, "teaching_plan", None)
        counts = [len({x.group_id for x in items if semester_number(x) == n}) for n in (1, 2, 3)]
        total = sum(planned_periods(x) for x in items)
        explicit = _sum_explicit(x.reported_periods for x in items)
        if kind == "CO_HUU":
            duties_here = duty_map[teacher.pk] if teacher.pk not in displayed_duties else []
            displayed_duties.add(teacher.pk)
            other = "; ".join(f"{d.description} ({d.periods})" for d in duties_here if d.kind == "KHAC")
            clc = sum((d.periods for d in duties_here if d.kind == "CLC"), Decimal(0))
            teacher_items = [x for x in assignments if x.lecturer_id == teacher.pk]
            teaching_total = _sum_explicit(x.reported_periods for x in teacher_items)
            total_work = teaching_total + sum((d.periods for d in duty_map[teacher.pk]), Decimal(0)) if teaching_total is not None else None
            rows2.append((len(rows2) + 1, teacher.employee_code, teacher.name, "", teacher.academic_title,
                a.group.course.name, a.group.course.code, a.group.course.credits, _course_periods(plan),
                len({x.group_id for x in items}), *counts, total, other, clc, total_work if duties_here or not any(r[1] == teacher.employee_code for r in rows2) else None))
        elif kind == "MOI_GIANG":
            rows3.append((len(rows3) + 1, a.group.course.name, a.group.course.code, a.group.course.credits,
                _course_periods(plan), len({x.group_id for x in items}), *counts, explicit,
                teacher.employee_code, teacher.name, teacher.academic_title, teacher.department.faculty.name))
        else:
            rows4.append((len(rows4) + 1, teacher.name, "", teacher.specialty, teacher.academic_title,
                teacher.workplace, a.group.course.name, a.group.course.code, a.group.course.credits,
                _course_periods(plan), len({x.group_id for x in items}), *counts, explicit,
                _sum_explicit(x.reported_periods for x in own if x.lecturer_id == teacher.pk)))
    # Include staff whose current plan only contains non-teaching duties.
    for teacher_id, items in duty_map.items():
        if teacher_id not in displayed_duties:
            t = items[0].lecturer
            rows2.append((len(rows2) + 1, t.employee_code, t.name, "", t.academic_title, "", "", None, None, 0, 0, 0, 0, 0,
                          "; ".join(f"{d.description} ({d.periods})" for d in items if d.kind == "KHAC"),
                          sum((d.periods for d in items if d.kind == "CLC"), Decimal(0)),
                          sum((d.periods for d in items), Decimal(0))))
    _sheet(book, "Mau2", "BẢNG PHÂN CÔNG CÔNG TÁC CỦA CÁN BỘ, GIẢNG VIÊN CƠ HỮU", faculty, year,
        ("STT", "Mã CB", "Họ và tên GV", "Năm sinh", "Chức danh, học vị", "Tên học phần", "Mã học phần", "Số TC", "Số tiết HP",
         "Số lượng lớp, nhóm", "HK1", "HK2", "HK3", "Tổng tiết giảng dạy theo kế hoạch", "Công tác khác", "Tổng CLC", "Tổng số tiết công tác của GV"), rows2)
    _sheet(book, "Mau3", "KẾ HOẠCH MỜI GIẢNG", faculty, year,
        ("STT", "Tên học phần", "Mã HP", "Số TC", "Số tiết HP", "Số nhóm, lớp", "HK1", "HK2", "HK3", "Số tiết thực tế mời giảng",
         "Mã CB", "Họ tên", "Học vị, chức danh", "Đơn vị công tác"), rows3, "Mời cán bộ, giảng viên trong trường không thuộc đơn vị mình")
    _sheet(book, "Mau4", "KẾ HOẠCH THỈNH GIẢNG", faculty, year,
        ("STT", "Họ và tên", "Năm sinh", "Chuyên ngành đào tạo", "Chức danh, học vị", "Đơn vị công tác", "Tên học phần", "Mã HP", "Số TC",
         "Số tiết HP", "Số lớp, nhóm", "HK1", "HK2", "HK3", "Số tiết thực tế thỉnh giảng", "Tổng"), rows4)
    _sheet(book, "Mau5", "ĐĂNG KÍ THỜI GIAN CÁC HOẠT ĐỘNG TẬP TRUNG NGOÀI TRƯỜNG CỦA SINH VIÊN HỆ CHÍNH QUY", faculty, year,
        ("Trình độ đào tạo", "Khóa", "Lớp", "Nội dung hoạt động tập trung ngoài trường", "Địa điểm", "Học kỳ", "Số ngày", "Từ ngày", "Đến ngày", "Số lượng SV"),
        [(a.training_level, a.cohort_label, a.cohort.name, a.description, a.location, a.semester_number or a.semester.number,
          (a.end_date - a.start_date).days + 1, a.start_date.isoformat(), a.end_date.isoformat(), a.student_count) for a in activities])
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
