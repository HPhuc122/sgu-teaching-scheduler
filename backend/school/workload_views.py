from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from openpyxl import Workbook
from io import BytesIO

from .access import scoped, roles, system_admin
from .assignment_export import _safe_cell
from .models import Faculty, Lecturer, Semester
from .workload import workload_rows


@login_required
def workload_report(request):
    teachers = Lecturer.objects.select_related("department__faculty").order_by("employee_code", "pk")
    if system_admin(request.user) or roles(request.user).exists():
        teachers = scoped(teachers, request.user)
        faculties = scoped(Faculty.objects.all(), request.user)
    else:
        teachers = teachers.filter(user=request.user)
        faculties = Faculty.objects.filter(pk__in=teachers.values("department__faculty_id"))
        if not teachers.exists():
            raise PermissionDenied("Chưa có quyền hoặc hồ sơ giảng viên.")
    for key, qs in (("faculty", faculties), ("lecturer", teachers)):
        value = request.GET.get(key, "")
        if value:
            if not value.isdigit() or not qs.filter(pk=value).exists():
                raise PermissionDenied("Đối tượng ngoài phạm vi được cấp.")
    selected = request.GET.get("semester", "")
    semester = Semester.objects.filter(pk=selected).first() if selected.isdigit() else None
    choices = teachers
    if request.GET.get("faculty"):
        teachers = teachers.filter(department__faculty_id=request.GET["faculty"])
    if request.GET.get("lecturer"):
        teachers = teachers.filter(pk=request.GET["lecturer"])
    status = request.GET.get("status", "")
    if status not in ("", "ChoDuyet", "DaDuyet"):
        raise PermissionDenied("Bộ lọc không hợp lệ.")
    rows = workload_rows(semester, teachers, status or None) if semester else []
    if semester and request.GET.get("action") == "download":
        book = Workbook()
        sheet = book.active
        sheet.title = "KhoiLuongMoPhong"
        sheet.append(["Mã GV", "Giảng viên", "Khoa", "Số tiết", "Giờ quy đổi mô phỏng", "Định mức", "Định mức phân bổ", "Chênh lệch", "Thiếu hệ số", "Thiếu định mức"])
        for row in rows:
            t = row["lecturer"]
            sheet.append([_safe_cell(v) for v in (t.employee_code, t.name, t.department.faculty.name,
                         row["actual_periods"], row["converted_units"], row["quota"], row["effective_quota"],
                         row["difference"], ", ".join(row["missing_factors"]), "Có" if row["missing_quota"] else "Không")])
        stream = BytesIO()
        book.save(stream)
        response = HttpResponse(stream.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="khoi_luong_mo_phong.xlsx"'
        return response
    return render(request, "school/workload_report.html", {"rows": rows, "faculties": faculties,
                  "lecturers": choices, "semesters": Semester.objects.order_by("-start_date"),
                  "semester": semester, "selected": request.GET, "query": request.GET.urlencode()})
