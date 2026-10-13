"""Three proposed SGU catalog workbooks with preview and atomic upsert support.

These are system import formats, not official SGU Excel templates.
"""

from hashlib import sha1
from io import BytesIO

from openpyxl import Workbook, load_workbook
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db.models import Q

from .models import (Building, Cohort, Course, CourseGroup, CourseProgram, Department,
                     Faculty, GroupCohort, Lecturer, Program, Room, ScheduleEntry,
                     Semester, TeachingQualification)


SHEETS = {
    "courses": {
        "ChuongTrinh": ("ma_nganh_ctdt", "ten_chuong_trinh", "ma_khoa", "chu_ky_ctdt"),
        "HocPhan": ("ma_mon_hoc", "ten_mon_hoc", "so_tin_chi", "ma_bo_mon_phu_trach", "loai_mon"),
        "HocPhanChuongTrinh": ("ma_mon_hoc", "ma_nganh_ctdt", "chu_ky_ctdt", "loai_trong_ctdt"),
        "NhomHocPhan": ("ma_mon_hoc", "hoc_ky", "nhom", "to_th", "si_so_du_kien", "ten_lop"),
    },
    "rooms": {
        "PhongHoc": ("ma_phong", "ma_toa_nha", "ten_toa_nha", "ten_phong", "suc_chua",
                     "loai_phong", "trang_thai"),
    },
    "lecturers": {
        "GiangVien": ("ma_vien_chuc", "ho_ten", "email", "ma_khoa", "ma_bo_mon", "trang_thai"),
        "GiangVienHocPhan": ("ma_vien_chuc", "ma_mon_hoc"),
    },
}
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000


def template_bytes(kind):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, headers in SHEETS[kind].items():
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = max(18, len(column[0].value) + 2)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def read_workbook(upload, kind):
    if not upload.name.lower().endswith(".xlsx"):
        raise ValueError("Chỉ nhận file .xlsx")
    if upload.size > MAX_BYTES:
        raise ValueError("File vượt giới hạn 2 MB")
    try:
        workbook = load_workbook(upload, read_only=True, data_only=True)
        if set(workbook.sheetnames) != set(SHEETS[kind]):
            raise ValueError("Tên sheet không khớp mẫu Excel")
        result = {}
        total = 0
        for name, headers in SHEETS[kind].items():
            iterator = workbook[name].iter_rows(values_only=True)
            heading = next(iterator, None)
            if heading is None or tuple(str(cell or "").strip() for cell in heading) != headers:
                raise ValueError(f"Sheet {name}: tiêu đề cột không khớp mẫu")
            rows = []
            for line, cells in enumerate(iterator, start=2):
                if line > MAX_ROWS + 100:
                    raise ValueError(f"Sheet {name} có quá nhiều dòng")
                if all(cell is None or str(cell).strip() == "" for cell in cells):
                    continue
                total += 1
                if total > MAX_ROWS:
                    raise ValueError("Mỗi file chỉ được có tối đa 1000 dòng dữ liệu")
                if any(cell not in (None, "") for cell in cells[len(headers):]):
                    raise ValueError(f"Sheet {name}, dòng {line}: có dữ liệu ngoài các cột mẫu")
                values = list(cells[:len(headers)]) + [None] * max(0, len(headers) - len(cells))
                for key, value in zip(headers, values):
                    if (key.startswith("ma_") or key in ("nhom", "to_th", "ten_lop")) and isinstance(value, (int, float)):
                        raise ValueError(f"Sheet {name}, dòng {line}: cột {key} phải đặt định dạng văn bản để giữ số 0 đầu")
                rows.append({"line": line, **{key: "" if value is None else str(value).strip()
                                              for key, value in zip(headers, values)}})
            result[name] = rows
        if total == 0:
            raise ValueError("File không có dòng dữ liệu")
        return result
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Không đọc được file Excel hợp lệ") from exc
    finally:
        if "workbook" in locals():
            workbook.close()


def _required(row, field, *, max_length=None):
    value = row[field]
    if not value:
        raise ValueError(f"Thiếu {field}")
    if max_length and len(value) > max_length:
        raise ValueError(f"{field} dài quá {max_length} ký tự")
    return value


def _positive(row, field, *, maximum=None):
    value = _required(row, field)
    if not value.isdigit() or int(value) < 1 or (maximum and int(value) > maximum):
        raise ValueError(f"{field} phải là số nguyên dương" + (f" không quá {maximum}" if maximum else ""))
    return int(value)


def _record_error(errors, sheet, row, message):
    errors.append({"sheet": sheet, "line": row["line"], "message": message})


def _unique_rows(rows, fields, sheet, errors):
    keys = set()
    for row in rows:
        key = tuple(row[field] for field in fields)
        if key in keys:
            _record_error(errors, sheet, row, "Khóa dữ liệu bị lặp trong file")
        keys.add(key)


def _coded_map(queryset):
    result = {}
    duplicates = set()
    for obj in queryset:
        if not obj.code:
            continue
        if obj.code in result:
            duplicates.add(obj.code)
        result[obj.code] = obj
    return result, duplicates


def validate_catalog(kind, data, semester=None, available_course_codes=None):
    if kind == "courses":
        return _validate_courses(data, semester)
    if kind == "rooms":
        return _validate_rooms(data)
    return _validate_lecturers(data, available_course_codes=available_course_codes)


def _validate_courses(data, semester):
    errors = []
    if semester is None:
        return [{"sheet": "NhomHocPhan", "line": None, "message": "Cần chọn học kỳ"}]
    if semester.status == "DaKhoa":
        return [{"sheet": "NhomHocPhan", "line": None, "message": "Học kỳ đã khóa"}]
    faculties = {item.code: item for item in Faculty.objects.all()}
    departments, duplicate_departments = _coded_map(Department.objects.select_related("faculty"))
    programs = {(item.code, item.cycle): item for item in Program.objects.all()}
    courses = {item.code: item for item in Course.objects.all()}
    groups = {}
    duplicate_groups = set()
    for item in CourseGroup.objects.filter(semester=semester).select_related("course"):
        key = (item.course.code, item.group, item.lab_group or "")
        if key in groups:
            duplicate_groups.add(key)
        groups[key] = item
    for sheet, fields in (("ChuongTrinh", ("ma_nganh_ctdt", "chu_ky_ctdt")),
                          ("HocPhan", ("ma_mon_hoc",)),
                          ("HocPhanChuongTrinh", ("ma_mon_hoc", "ma_nganh_ctdt", "chu_ky_ctdt")),
                          ("NhomHocPhan", ("ma_mon_hoc", "nhom", "to_th"))):
        _unique_rows(data[sheet], fields, sheet, errors)
    file_programs = {(r["ma_nganh_ctdt"], r["chu_ky_ctdt"]) for r in data["ChuongTrinh"]}
    file_courses = {r["ma_mon_hoc"] for r in data["HocPhan"]}
    for row in data["ChuongTrinh"]:
        try:
            _required(row, "ma_nganh_ctdt", max_length=20)
            _required(row, "ten_chuong_trinh", max_length=200)
            _required(row, "chu_ky_ctdt", max_length=30)
            if row["ma_khoa"] not in faculties:
                raise ValueError("Mã khoa chưa có trong danh mục")
        except ValueError as exc:
            _record_error(errors, "ChuongTrinh", row, str(exc))
    for row in data["HocPhan"]:
        try:
            code = _required(row, "ma_mon_hoc", max_length=30)
            _required(row, "ten_mon_hoc", max_length=200)
            _positive(row, "so_tin_chi", maximum=30)
            if row["ma_bo_mon_phu_trach"] in duplicate_departments:
                raise ValueError("Mã bộ môn bị lặp trong danh mục")
            if row["ma_bo_mon_phu_trach"] not in departments:
                raise ValueError("Mã bộ môn phụ trách chưa có trong danh mục")
            if row["loai_mon"] not in ("CHUNG", "CHUYEN_NGANH"):
                raise ValueError("loai_mon phải là CHUNG hoặc CHUYEN_NGANH")
            old = courses.get(code)
            if old and ScheduleEntry.objects.filter(group__course=old).exists():
                if (old.department_id != departments[row["ma_bo_mon_phu_trach"]].pk
                        or old.credits != int(row["so_tin_chi"]) or old.kind != row["loai_mon"]):
                    raise ValueError("Không thể đổi bộ môn, tín chỉ hoặc loại môn khi đã có lịch")
        except ValueError as exc:
            _record_error(errors, "HocPhan", row, str(exc))
    for row in data["HocPhanChuongTrinh"]:
        try:
            if row["ma_mon_hoc"] not in courses and row["ma_mon_hoc"] not in file_courses:
                raise ValueError("Mã môn học chưa có")
            key = row["ma_nganh_ctdt"], row["chu_ky_ctdt"]
            if key not in programs and key not in file_programs:
                raise ValueError("Mã ngành và chu kỳ CTĐT chưa có")
            if row["loai_trong_ctdt"] not in ("BAT_BUOC", "TU_CHON"):
                raise ValueError("loai_trong_ctdt phải là BAT_BUOC hoặc TU_CHON")
        except ValueError as exc:
            _record_error(errors, "HocPhanChuongTrinh", row, str(exc))
    for row in data["NhomHocPhan"]:
        try:
            code = _required(row, "ma_mon_hoc", max_length=30)
            if code not in courses and code not in file_courses:
                raise ValueError("Mã môn học chưa có")
            if row["hoc_ky"] != semester.name:
                raise ValueError("hoc_ky không khớp học kỳ đã chọn")
            _required(row, "nhom", max_length=10)
            if len(row["to_th"]) > 10:
                raise ValueError("to_th dài quá 10 ký tự")
            capacity = _positive(row, "si_so_du_kien", maximum=1000)
            classes = [part.strip() for part in row["ten_lop"].split(";") if part.strip()]
            if any(len(part) > 30 for part in classes):
                raise ValueError("Mã tên_lop dài quá 30 ký tự")
            key = code, row["nhom"], row["to_th"]
            if key in duplicate_groups:
                raise ValueError("Nhóm và tổ TH bị lặp trong học kỳ hiện có")
            old = groups.get(key)
            if old and ScheduleEntry.objects.filter(group=old).exists():
                old_classes = set(old.cohort_links.values_list("cohort__name", flat=True))
                if old.capacity != capacity or set(classes) - old_classes:
                    raise ValueError("Không thể đổi sĩ số hoặc thêm lớp khi nhóm đã có lịch")
        except ValueError as exc:
            _record_error(errors, "NhomHocPhan", row, str(exc))
    return errors


def _validate_rooms(data):
    errors = []
    rooms = {item.code: item for item in Room.objects.all()}
    buildings, duplicate_buildings = _coded_map(Building.objects.all())
    _unique_rows(data["PhongHoc"], ("ma_phong",), "PhongHoc", errors)
    building_names = {}
    for row in data["PhongHoc"]:
        try:
            code = _required(row, "ma_phong", max_length=30)
            building_code = _required(row, "ma_toa_nha", max_length=30)
            building_name = _required(row, "ten_toa_nha", max_length=100)
            _required(row, "ten_phong", max_length=50)
            capacity = _positive(row, "suc_chua", maximum=10000)
            if building_code in duplicate_buildings:
                raise ValueError("Mã tòa nhà bị lặp trong danh mục")
            if building_code in building_names and building_names[building_code] != building_name:
                raise ValueError("Một mã tòa nhà có nhiều tên trong file")
            building_names[building_code] = building_name
            if row["loai_phong"] not in ("LyThuyet", "MayTinh", "ThiNghiem", "HoiTruong"):
                raise ValueError("loai_phong không thuộc danh sách hỗ trợ")
            if row["trang_thai"] not in ("SanSang", "BaoTri"):
                raise ValueError("trang_thai phải là SanSang hoặc BaoTri")
            old = rooms.get(code)
            if old and ScheduleEntry.objects.filter(room=old, status="DaDuyet").exists():
                if (row["trang_thai"] != "SanSang" or capacity < old.capacity
                        or old.building.code != building_code or old.room_type != row["loai_phong"]):
                    raise ValueError("Phòng đang có lịch đã duyệt; không thể đổi tòa, loại phòng, ngừng dùng hoặc giảm sức chứa")
        except ValueError as exc:
            _record_error(errors, "PhongHoc", row, str(exc))
    return errors


def _validate_lecturers(data, *, available_course_codes=None):
    errors = []
    lecturers = {item.employee_code: item for item in Lecturer.objects.all() if item.employee_code}
    departments, duplicate_departments = _coded_map(Department.objects.select_related("faculty"))
    courses = {item.code: item for item in Course.objects.all()}
    known_course_codes = set(courses) | set(available_course_codes or ())
    _unique_rows(data["GiangVien"], ("ma_vien_chuc",), "GiangVien", errors)
    _unique_rows(data["GiangVienHocPhan"], ("ma_vien_chuc", "ma_mon_hoc"), "GiangVienHocPhan", errors)
    file_codes = {row["ma_vien_chuc"] for row in data["GiangVien"]}
    emails = {}
    for row in data["GiangVien"]:
        try:
            code = _required(row, "ma_vien_chuc", max_length=30)
            _required(row, "ho_ten", max_length=200)
            if row["ma_bo_mon"] in duplicate_departments:
                raise ValueError("Mã bộ môn bị lặp trong danh mục")
            department = departments.get(row["ma_bo_mon"])
            if department is None:
                raise ValueError("Mã bộ môn chưa có trong danh mục")
            if department.faculty.code != row["ma_khoa"]:
                raise ValueError("Mã khoa không khớp bộ môn")
            if row["trang_thai"] not in ("DangCongTac", "NgungCongTac"):
                raise ValueError("trang_thai phải là DangCongTac hoặc NgungCongTac")
            old = lecturers.get(code)
            if old and ScheduleEntry.objects.filter(lecturer=old, status="DaDuyet").exists():
                if row["trang_thai"] != "DangCongTac" or old.department_id != department.pk:
                    raise ValueError("Giảng viên đang có lịch đã duyệt; không thể đổi bộ môn hoặc ngừng công tác")
            email = row["email"].lower()
            if email:
                try:
                    validate_email(email)
                except DjangoValidationError:
                    raise ValueError("Email không hợp lệ")
                if len(email) > 254:
                    raise ValueError("Email dài quá 254 ký tự")
                if email in emails and emails[email] != code:
                    raise ValueError("Email bị lặp trong file")
                emails[email] = code
                if Lecturer.objects.filter(email__iexact=email).exclude(employee_code=code).exists():
                    raise ValueError("Email đã thuộc giảng viên khác")
        except ValueError as exc:
            _record_error(errors, "GiangVien", row, str(exc))
    for row in data["GiangVienHocPhan"]:
        try:
            if row["ma_vien_chuc"] not in lecturers and row["ma_vien_chuc"] not in file_codes:
                raise ValueError("Mã viên chức chưa có")
            if row["ma_mon_hoc"] not in known_course_codes:
                raise ValueError("Mã môn học chưa có")
        except ValueError as exc:
            _record_error(errors, "GiangVienHocPhan", row, str(exc))
    return errors


def commit_catalog(kind, data, semester=None):
    """Call inside a transaction, after validate_catalog returned no errors."""
    if kind == "courses":
        _commit_courses(data, semester)
    elif kind == "rooms":
        _commit_rooms(data)
    else:
        _commit_lecturers(data)


def _commit_courses(data, semester):
    for row in data["ChuongTrinh"]:
        Program.objects.update_or_create(code=row["ma_nganh_ctdt"], cycle=row["chu_ky_ctdt"], defaults={
            "name": row["ten_chuong_trinh"], "faculty": Faculty.objects.get(code=row["ma_khoa"]),
        })
    for row in data["HocPhan"]:
        Course.objects.update_or_create(code=row["ma_mon_hoc"], defaults={
            "name": row["ten_mon_hoc"], "credits": int(row["so_tin_chi"]),
            "department": Department.objects.get(code=row["ma_bo_mon_phu_trach"]),
            "kind": row["loai_mon"],
        })
    for row in data["HocPhanChuongTrinh"]:
        CourseProgram.objects.update_or_create(
            course=Course.objects.get(code=row["ma_mon_hoc"]),
            program=Program.objects.get(code=row["ma_nganh_ctdt"], cycle=row["chu_ky_ctdt"]),
            defaults={"requirement": row["loai_trong_ctdt"]},
        )
    for row in data["NhomHocPhan"]:
        course = Course.objects.get(code=row["ma_mon_hoc"])
        group_query = CourseGroup.objects.filter(course=course, semester=semester, group=row["nhom"])
        group = (group_query.filter(lab_group=row["to_th"]).first() if row["to_th"] else
                 group_query.filter(Q(lab_group__isnull=True) | Q(lab_group="")).first())
        if group is None:
            digest = sha1(f"{course.code}|{row['nhom']}|{row['to_th']}".encode()).hexdigest()[:20]
            group = CourseGroup.objects.create(course=course, semester=semester, code=f"I{digest}",
                                               group=row["nhom"], lab_group=row["to_th"] or None,
                                               capacity=int(row["si_so_du_kien"]))
        else:
            group.capacity = int(row["si_so_du_kien"])
            group.save(update_fields=["capacity"])
        for class_name in {part.strip() for part in row["ten_lop"].split(";") if part.strip()}:
            cohort, _ = Cohort.objects.get_or_create(semester=semester, name=class_name)
            GroupCohort.objects.get_or_create(group=group, cohort=cohort)


def _commit_rooms(data):
    for row in data["PhongHoc"]:
        building, _ = Building.objects.update_or_create(code=row["ma_toa_nha"],
                                                        defaults={"name": row["ten_toa_nha"]})
        Room.objects.update_or_create(code=row["ma_phong"], defaults={
            "building": building, "name": row["ten_phong"], "capacity": int(row["suc_chua"]),
            "room_type": row["loai_phong"], "status": row["trang_thai"],
        })


def _commit_lecturers(data):
    for row in data["GiangVien"]:
        defaults = {"name": row["ho_ten"], "department": Department.objects.get(code=row["ma_bo_mon"]),
                    "status": row["trang_thai"]}
        if row["email"]:
            defaults["email"] = row["email"]
        Lecturer.objects.update_or_create(employee_code=row["ma_vien_chuc"], defaults=defaults)
    for row in data["GiangVienHocPhan"]:
        TeachingQualification.objects.get_or_create(
            lecturer=Lecturer.objects.get(employee_code=row["ma_vien_chuc"]),
            course=Course.objects.get(code=row["ma_mon_hoc"]), defaults={"priority": 2},
        )
