"""Admin preview and Excel download of approved faculty teaching assignments."""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import render

from .assignment_export import approved_assignments, assignment_rows, assignment_workbook_bytes
from .assignment_completeness import assignment_completeness
from .models import Faculty, Semester
from .access import scoped, global_action


@staff_member_required
def export_assignments(request):
    semesters = Semester.objects.all().order_by("-start_date")
    faculties = scoped(Faculty.objects.all(), request.user).order_by("name")
    semester_id = request.GET.get("semester", "")
    faculty_id = request.GET.get("faculty", "")
    semester = Semester.objects.filter(pk=semester_id).first() if semester_id.isdigit() else None
    faculty = Faculty.objects.filter(pk=faculty_id).first() if faculty_id.isdigit() else None
    errors = []
    if semester_id and semester is None:
        errors.append("Học kỳ không hợp lệ")
    if faculty_id and faculty is None:
        errors.append("Khoa không hợp lệ")
    if request.GET.get("action") == "download" and (semester is None or faculty is None):
        errors.append("Hãy chọn học kỳ và khoa trước khi tải file")

    detail_rows, summary_rows = [], []
    entries = []
    completeness = None
    if semester is not None and faculty is not None and not errors:
        completeness = assignment_completeness(semester) if global_action(request.user) else None
        from .models import ScheduleEntry
        visible = set(scoped(ScheduleEntry.objects.all(), request.user).values_list("pk", flat=True))
        entries = [e for e in approved_assignments(semester, faculty) if e.pk in visible]
        detail_rows, summary_rows = assignment_rows(entries)
        if request.GET.get("action") == "download":
            response = HttpResponse(
                assignment_workbook_bytes(semester, faculty, entries, completeness),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                f'attachment; filename="phan_cong_hk{semester.pk}_khoa{faculty.pk}.xlsx"'
            )
            return response
    context = {
        "semesters": semesters, "faculties": faculties, "selected_semester": semester,
        "selected_faculty": faculty, "semester_id": semester_id, "faculty_id": faculty_id,
        "errors": errors, "detail_rows": detail_rows[:50], "summary_rows": summary_rows,
        "total_entries": len(detail_rows), "total_periods": sum(row[-1] for row in detail_rows),
        "completeness": completeness,
    }
    return render(request, "school/export_assignments.html", context, status=400 if errors else 200)
