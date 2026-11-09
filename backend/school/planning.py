"""Teaching plans, appointments and off-campus dates independent of timetables."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.db import transaction

from .auto_schedule_errors import InputIssues, issue
from .models import (Cohort, GroupTeachingPlan, Lecturer, LecturerOtherDuty,
                     OffCampusActivity, ScheduleEntry, TeachingAssignment, SemesterResourcePlan)

PLAN_SHEETS = {
    "LopHanhChinh": ("ten_lop", "ma_bo_mon_quan_ly"),
    "KeHoachMoNhom": ("ma_mon_hoc", "nhom", "to_th", "hoc_ky_so", "khoa",
                      "so_tiet_lt", "so_tiet_bt", "so_tiet_th", "he_so_hp", "ghi_chu"),
    "HoatDongNgoaiTruong": ("ma_hoat_dong", "ten_lop", "khoa", "trinh_do", "noi_dung",
                            "dia_diem", "tu_ngay", "den_ngay", "so_sinh_vien", "hoc_ky_so"),
}
DUTY_SHEETS = {"CongTacKhac": ("ma_vien_chuc", "ma_cong_tac", "noi_dung", "loai", "so_tiet")}
LECTURER_FIELDS = ("nguon_giang_vien", "chuyen_nganh", "hoc_vi_chuc_danh", "don_vi_cong_tac")


def _number(value, label, *, integer=False, optional=False, positive=False, places=2, maximum=100000):
    if not value and optional:
        return None
    try:
        result = Decimal(value)
        if (not result.is_finite() or result < 0 or result > maximum
                or (positive and result <= 0) or (integer and result != int(result))):
            raise ValueError
        if not integer and result.as_tuple().exponent < -places:
            raise ValueError
        return int(result) if integer else result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label}: giá trị số không hợp lệ")


def _semester_number(value):
    if not value:
        return None
    if value not in ("1", "2", "3"):
        raise ValueError("hoc_ky_so phải là 1, 2 hoặc 3")
    return int(value)


def validate_plan_inputs(semester, data):
    courses, teachers = data["courses"], data["lecturers"]
    groups = {(r["ma_mon_hoc"], r["nhom"], r["to_th"]) for r in courses["NhomHocPhan"]}
    classes = {c.strip() for r in courses["NhomHocPhan"] for c in r["ten_lop"].split(";") if c.strip()}
    teacher_codes = {r["ma_vien_chuc"] for r in teachers["GiangVien"]}
    errors, prepared = [], {"classes": [], "groups": [], "activities": [], "duties": []}
    from .models import Department
    department_codes = set(Department.objects.values_list("code", flat=True)) | {r["ma_bo_mon"] for r in courses["BoMon"]}
    seen_classes = set()
    for row in courses.get("LopHanhChinh", []):
        if row["ten_lop"] not in classes or row["ten_lop"] in seen_classes:
            errors.append(issue("courses", "LopHanhChinh", row["line"], "Lớp phải có trong NhomHocPhan và không được lặp"))
        elif row["ma_bo_mon_quan_ly"] not in department_codes:
            errors.append(issue("courses", "LopHanhChinh", row["line"], "Bộ môn quản lý lớp chưa có trong danh mục hoặc BoMon"))
        else:
            prepared["classes"].append((row["ten_lop"], row["ma_bo_mon_quan_ly"]))
        seen_classes.add(row["ten_lop"])
    semester_numbers = set()
    seen = set()
    for row in courses.get("KeHoachMoNhom", []):
        try:
            key = row["ma_mon_hoc"], row["nhom"], row["to_th"]
            if key not in groups or key in seen:
                raise ValueError("Nhóm kế hoạch không có trong NhomHocPhan hoặc bị lặp")
            seen.add(key)
            number = _semester_number(row["hoc_ky_so"])
            if number:
                semester_numbers.add(number)
            if len(row["khoa"]) > 150 or len(row["ghi_chu"]) > 500:
                raise ValueError("Khóa hoặc ghi chú quá dài")
            prepared["groups"].append((key, dict(
                semester_number=number, cohort_label=row["khoa"], note=row["ghi_chu"],
                lecture_periods=_number(row["so_tiet_lt"], "Số tiết LT", integer=True, optional=True),
                exercise_periods=_number(row["so_tiet_bt"], "Số tiết BT", integer=True, optional=True),
                practical_periods=_number(row["so_tiet_th"], "Số tiết TH", integer=True, optional=True),
                coefficient=_number(row["he_so_hp"], "Hệ số HP", optional=True, positive=True, places=3, maximum=Decimal("9999.999")))))
        except ValueError as exc:
            errors.append(issue("courses", "KeHoachMoNhom", row["line"], exc))
    seen = set()
    for row in courses.get("HoatDongNgoaiTruong", []):
        try:
            key = row["ma_hoat_dong"], row["ten_lop"]
            if not row["ma_hoat_dong"] or len(row["ma_hoat_dong"]) > 50 or key in seen:
                raise ValueError("Mã hoạt động thiếu, quá dài hoặc bị lặp cho cùng lớp")
            seen.add(key)
            if row["ten_lop"] not in classes:
                raise ValueError("Lớp hoạt động phải có trong NhomHocPhan của file")
            for field, maximum in (("khoa", 150), ("trinh_do", 50), ("noi_dung", 300), ("dia_diem", 200)):
                if len(row[field]) > maximum:
                    raise ValueError(f"{field} quá dài")
            if not row["noi_dung"]:
                raise ValueError("Thiếu nội dung hoạt động")
            start, end = date.fromisoformat(row["tu_ngay"]), date.fromisoformat(row["den_ngay"])
            if not semester.start_date <= start <= end <= semester.end_date:
                raise ValueError("Ngày hoạt động phải nằm trong học kỳ, từ ngày không lớn hơn đến ngày")
            number = _semester_number(row["hoc_ky_so"])
            if number:
                semester_numbers.add(number)
            prepared["activities"].append((row["ten_lop"], dict(
                code=row["ma_hoat_dong"], cohort_label=row["khoa"], training_level=row["trinh_do"] or "ĐH",
                description=row["noi_dung"], location=row["dia_diem"], start_date=start, end_date=end,
                student_count=_number(row["so_sinh_vien"], "Số sinh viên", integer=True, positive=True),
                semester_number=number)))
        except ValueError as exc:
            errors.append(issue("courses", "HoatDongNgoaiTruong", row["line"], exc))
    if len(semester_numbers) > 1:
        errors.append(issue("courses", "KeHoachMoNhom", None, "Một học kỳ chỉ được có một hoc_ky_so thống nhất"))
    if semester.number and semester_numbers and semester.number not in semester_numbers:
        errors.append(issue("courses", "KeHoachMoNhom", None, "hoc_ky_so không khớp học kỳ đã chọn"))
    for row in teachers["GiangVien"]:
        kind = row.get("nguon_giang_vien", "")
        if kind and kind not in ("CO_HUU", "THINH_GIANG"):
            errors.append(issue("lecturers", "GiangVien", row["line"], "nguon_giang_vien phải là CO_HUU hoặc THINH_GIANG"))
        for name, maximum in (("chuyen_nganh", 200), ("hoc_vi_chuc_danh", 100), ("don_vi_cong_tac", 200)):
            if len(row.get(name, "")) > maximum:
                errors.append(issue("lecturers", "GiangVien", row["line"], f"{name} quá dài"))
    for row in courses["BuoiHocYeuCau"]:
        try:
            _number(row.get("so_tiet_thuc_te", ""), "Số tiết thực tế", optional=True)
        except ValueError as exc:
            errors.append(issue("courses", "BuoiHocYeuCau", row["line"], exc))
    seen = set()
    for row in teachers.get("CongTacKhac", []):
        try:
            key = row["ma_vien_chuc"], row["ma_cong_tac"]
            if row["ma_vien_chuc"] not in teacher_codes:
                raise ValueError("Giảng viên công tác khác phải có trong GiangVien")
            if key in seen or not row["ma_cong_tac"] or len(row["ma_cong_tac"]) > 50:
                raise ValueError("Mã công tác thiếu, quá dài hoặc bị lặp")
            seen.add(key)
            if not row["noi_dung"] or len(row["noi_dung"]) > 300 or row["loai"] not in ("KHAC", "CLC"):
                raise ValueError("Nội dung hoặc loại công tác không hợp lệ (KHAC/CLC)")
            prepared["duties"].append((row["ma_vien_chuc"], row["ma_cong_tac"], dict(
                description=row["noi_dung"], kind=row["loai"], periods=_number(row["so_tiet"], "Số tiết công tác"))))
        except ValueError as exc:
            errors.append(issue("lecturers", "CongTacKhac", row["line"], exc))
    if errors:
        raise InputIssues(errors)
    return prepared


def persist_plan(semester, data, demands, prepared):
    from .auto_schedule import AUTO_SHEETS
    from .models import Department
    for class_name, department_code in prepared["classes"]:
        Cohort.objects.filter(semester=semester, name=class_name).update(department=Department.objects.get(code=department_code))
    SemesterResourcePlan.objects.update_or_create(semester=semester, defaults=dict(
        room_blocks=[[row[h] for h in AUTO_SHEETS["rooms"]["PhongKhongKhaDung"]] for row in data["rooms"]["PhongKhongKhaDung"]],
        teacher_blocks=[[row[h] for h in AUTO_SHEETS["lecturers"]["GiangVienKhongKhaDung"]] for row in data["lecturers"]["GiangVienKhongKhaDung"]]))
    groups = {d["key"]: d["group"] for d in demands}
    numbers = {v["semester_number"] for _, v in prepared["groups"] if v["semester_number"]}
    numbers.update(v["semester_number"] for _, v in prepared["activities"] if v["semester_number"])
    if numbers and not semester.number:
        semester.number = next(iter(numbers))
        semester.save(update_fields=["number"])
    for key, values in prepared["groups"]:
        GroupTeachingPlan.objects.update_or_create(group=groups[key], defaults=values)
    for group in groups.values():
        GroupTeachingPlan.objects.get_or_create(group=group)
    for row in data["lecturers"]["GiangVien"]:
        updates = {target: row[source] for source, target in zip(
            LECTURER_FIELDS, ("source_kind", "specialty", "academic_title", "workplace")) if row.get(source)}
        if updates:
            Lecturer.objects.filter(employee_code=row["ma_vien_chuc"]).update(**updates)
    for name, values in prepared["activities"]:
        cohort = Cohort.objects.get(semester=semester, name=name)
        values = values.copy()
        code = values.pop("code")
        OffCampusActivity.objects.update_or_create(semester=semester, cohort=cohort, code=code, defaults=values)
    for code, duty_code, values in prepared["duties"]:
        LecturerOtherDuty.objects.update_or_create(semester=semester, lecturer=Lecturer.objects.get(employee_code=code), code=duty_code, defaults=values)
    existing = {(a.group_id, a.request_code): a for a in TeachingAssignment.objects.filter(group__semester=semester)}
    reported = {(r["ma_mon_hoc"], r["nhom"], r["to_th"], r["ma_buoi"]): r.get("so_tiet_thuc_te", "")
                for r in data["courses"]["BuoiHocYeuCau"]}
    for d in demands:
        old = existing.get((d["group"].pk, d["code"]))
        teacher = d.get("assigned_teacher")
        # An unchanged, unfixed input must not erase the last selected lecturer.
        lecturer = teacher if teacher or not old or old.fixed_lecturer_id else old.lecturer_id
        obj, _ = TeachingAssignment.objects.update_or_create(group=d["group"], request_code=d["code"], defaults=dict(
            component=d.get("component", ""), period_count=d["count"], weeks=sorted(d["weeks"]),
            allowed_days=sorted(d["days"]), room_type=d["room_type"],
            fixed_lecturer=teacher, lecturer_id=getattr(lecturer, "pk", lecturer),
            reported_periods=_number(reported[(*d["key"], d["code"])],
                "Số tiết thực tế", optional=True)))
        d["planned_assignment_id"] = obj.pk
    # Missing rows are retained here. Only a confirmed synchronization may remove
    # unchanged, proven Excel records, including rows from entirely omitted groups.


def appointment_kind(assignment):
    teacher = assignment.lecturer
    if teacher is None:
        return "CHUA_PHAN_CONG"
    if teacher.source_kind == "THINH_GIANG":
        return "THINH_GIANG"
    if teacher.department.faculty_id != assignment.group.course.department.faculty_id:
        return "MOI_GIANG"
    return "CO_HUU"


def activity_blocks(semester):
    """Whole-day restrictions; week 1 starts on Monday containing start_date."""
    result = defaultdict(set)
    anchor = semester.start_date - timedelta(days=semester.start_date.weekday())
    for activity in OffCampusActivity.objects.filter(semester=semester).select_related("cohort"):
        dates = set()
        day = activity.start_date
        while day <= activity.end_date:
            week = (day - anchor).days // 7 + 1
            if 1 <= week <= semester.week_count:
                dates.add((day.isoweekday() + 1, week))
            day += timedelta(days=1)
        for group_id in activity.cohort.groupcohort_set.values_list("group_id", flat=True):
            result[group_id].update(dates)
    return result


def planned_periods(assignment):
    return assignment.period_count * len(assignment.weeks)


def update_selected_assignments(result):
    for demand, _day, _start, _room, teacher in result:
        if demand.get("planned_assignment_id"):
            TeachingAssignment.objects.filter(pk=demand["planned_assignment_id"]).update(lecturer=teacher)


def check_entry_plan(entry, weeks):
    blocked = activity_blocks(entry.group.semester).get(entry.group_id, set())
    if any((entry.day, week) in blocked for week in weeks):
        raise ValueError("Buổi dạy trùng thời gian hoạt động ngoài trường của lớp")
    if entry.request_code:
        assignment = TeachingAssignment.objects.filter(group=entry.group, request_code=entry.request_code).first()
        if assignment and assignment.fixed_lecturer_id and assignment.fixed_lecturer_id != entry.lecturer_id:
            raise ValueError("Giảng viên khác với phân công cố định trong kế hoạch")


@transaction.atomic
def save_plan_from_workbooks(semester_id, files):
    from .auto_schedule import read_auto_files, _prepare_inputs, _create_catalog
    from .models import Semester
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    if semester.status == "DaKhoa":
        raise ValueError("Học kỳ đã khóa")
    if hasattr(semester, "active_schedule_run"):
        raise ValueError("Học kỳ đang có phiên xếp lịch; hãy chờ hoàn tất")
    if ScheduleEntry.objects.filter(group__semester=semester).exists():
        raise ValueError("Học kỳ đã có lịch; cần xử lý lịch đang lưu trước khi thay kế hoạch đầu vào")
    data = read_auto_files(files)
    demands, rb, tb = _prepare_inputs(semester, data)
    prepared = validate_plan_inputs(semester, data)
    from .plan_sync import begin_import, finish_import
    context = begin_import(semester)
    demands, _, _ = _create_catalog(semester, data, demands, rb, tb)
    if ScheduleEntry.objects.filter(group_id__in={d["group"].pk for d in demands}).exists():
        raise ValueError("Nhóm đã có lịch; cần xử lý lịch đang lưu trước khi thay kế hoạch đầu vào")
    persist_plan(semester, data, demands, prepared)
    semester.import_result = finish_import(semester, context, demands, prepared, data)
    return semester


def workbooks_from_plan(semester):
    """Rebuild the same three-input contract for the saved pre-timetable plan."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from .auto_schedule import AUTO_SHEETS
    from .models import (Course, Department, Faculty, Room, TeachingQualification)
    from .sample_data import workbook_bytes
    rows = {kind: {sheet: [] for sheet in sheets} for kind, sheets in AUTO_SHEETS.items()}
    c, r, t = rows["courses"], rows["rooms"], rows["lecturers"]
    assignments = list(TeachingAssignment.objects.filter(group__semester=semester).select_related(
        "group__course", "group__teaching_plan", "fixed_lecturer").prefetch_related("group__cohort_links__cohort"))
    if not assignments:
        raise ValueError("Học kỳ chưa có kế hoạch buổi học")
    groups = {a.group_id: a.group for a in assignments}
    courses = Course.objects.filter(pk__in={g.course_id for g in groups.values()})
    department_ids = set(courses.values_list("department_id", flat=True))
    qualifications = list(TeachingQualification.objects.filter(course__in=courses, lecturer__status="DangCongTac").select_related("lecturer__department__faculty", "course"))
    teachers = {q.lecturer_id: q.lecturer for q in qualifications}
    duties = list(LecturerOtherDuty.objects.filter(semester=semester).select_related("lecturer__department__faculty"))
    teachers.update((d.lecturer_id, d.lecturer) for d in duties)
    department_ids.update(teacher.department_id for teacher in teachers.values())
    departments = Department.objects.filter(pk__in=department_ids)
    c["Khoa"] = [(f.code, f.name) for f in Faculty.objects.filter(pk__in=departments.values("faculty_id"))]
    c["BoMon"] = [(d.code, d.name, d.faculty.code) for d in departments.select_related("faculty")]
    c["HocPhan"] = [(course.code, course.name, course.credits, course.department.code, course.kind) for course in courses.select_related("department")]
    for group in groups.values():
        classes = ";".join(link.cohort.name for link in group.cohort_links.all())
        c["NhomHocPhan"].append((group.course.code, semester.name, group.group, group.lab_group or "", group.capacity, classes))
        p = getattr(group, "teaching_plan", None)
        if p:
            c["KeHoachMoNhom"].append((group.course.code, group.group, group.lab_group or "", p.semester_number or semester.number,
                p.cohort_label, p.lecture_periods, p.exercise_periods, p.practical_periods, p.coefficient, p.note))
    c["LopHanhChinh"] = [(cls.name, cls.department.code) for cls in Cohort.objects.filter(
        semester=semester, groupcohort__group_id__in=groups, department__isnull=False).select_related("department").distinct()]
    for a in assignments:
        c["BuoiHocYeuCau"].append((a.group.course.code, a.group.group, a.group.lab_group or "", a.request_code,
            a.period_count, ",".join(map(str, a.weeks)), a.room_type, ",".join(map(str, a.allowed_days)),
            a.fixed_lecturer.employee_code if a.fixed_lecturer_id else "", a.component, a.reported_periods))
    for room in Room.objects.select_related("building"):
        r["PhongHoc"].append((room.code, room.building.code, room.building.name, room.name, room.capacity, room.room_type, room.status))
    for teacher in teachers.values():
        t["GiangVien"].append((teacher.employee_code, teacher.name, teacher.email or "", teacher.department.faculty.code,
            teacher.department.code, teacher.status, teacher.source_kind, teacher.specialty, teacher.academic_title, teacher.workplace))
    t["GiangVienHocPhan"] = [(q.lecturer.employee_code, q.course.code) for q in qualifications]
    t["CongTacKhac"] = [(d.lecturer.employee_code, d.code, d.description, d.kind, d.periods) for d in duties]
    c["HoatDongNgoaiTruong"] = [(a.code, a.cohort.name, a.cohort_label, a.training_level,
        a.description, a.location, a.start_date.isoformat(), a.end_date.isoformat(), a.student_count,
        a.semester_number or semester.number) for a in OffCampusActivity.objects.filter(
            semester=semester, cohort__groupcohort__group_id__in=groups).select_related("cohort").distinct()]
    # Availability uploaded for a previous run is not reconstructed from catalogs.
    # Keep the last input resource blocks as part of the semester plan snapshot.
    snapshot = getattr(semester, "resource_plan", None)
    if snapshot:
        r["PhongKhongKhaDung"] = snapshot.room_blocks
        teacher_codes = {teacher.employee_code for teacher in teachers.values()}
        t["GiangVienKhongKhaDung"] = [row for row in snapshot.teacher_blocks if row[0] in teacher_codes]
    return {kind: SimpleUploadedFile(f"{kind}.xlsx", workbook_bytes(kind, sheets)) for kind, sheets in rows.items()}
