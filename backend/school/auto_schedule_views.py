"""Single-screen three-workbook automatic scheduling workflow."""

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from rest_framework.exceptions import ValidationError

from .auto_schedule import AUTO_SHEETS, approve_algorithm_run, template_bytes
from .auto_schedule_errors import InputIssues
from .models import AlgorithmRun, Semester
from .preference_checks import day_off_violations
from .schedule_queue import enqueue_schedule
from .services import ScheduleConflictError


@staff_member_required
def auto_schedule(request):
    semesters = Semester.objects.all().order_by("-start_date")
    errors = []
    input_issues = []
    input_issue_count = 0
    run = None
    selected = request.POST.get("semester", "") if request.method == "POST" else ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            run_id = request.POST.get("run_id", "")
            if not run_id.isdigit():
                errors.append("Mã lần chạy không hợp lệ")
            else:
                try:
                    count = approve_algorithm_run(int(run_id), request.user)
                    run = AlgorithmRun.objects.get(pk=run_id)
                    run.message = f"Đã duyệt {count} buổi dạy."
                except (ValidationError, ScheduleConflictError, AlgorithmRun.DoesNotExist) as exc:
                    errors.append(f"Không thể duyệt phương án: {exc}")
        elif action == "run":
            semester = Semester.objects.filter(pk=selected).first() if selected.isdigit() else None
            if semester is None:
                errors.append("Hãy chọn học kỳ hợp lệ")
            else:
                try:
                    run = enqueue_schedule(semester.pk, request.FILES, request.user)
                    return redirect(f"/admin/auto-schedule/?run={run.pk}")
                except InputIssues as exc:
                    input_issues = exc.issues
                    input_issue_count = len(exc.issues)
                except ValueError as exc:
                    errors.extend(str(exc).splitlines())
        else:
            errors.append("Thao tác không hợp lệ")
    elif request.GET.get("run", "").isdigit():
        run = AlgorithmRun.objects.filter(pk=request.GET["run"]).first()
    recent = AlgorithmRun.objects.select_related("semester", "created_by").order_by("-created_at")[:10]
    hard_conflicts = (day_off_violations(run.semester_id, run.entries.select_related(
        "group__course", "lecturer")) if run and run.entry_count else [])
    can_approve = bool(run and run.status in ("FEASIBLE", "OPTIMAL", "HEURISTIC") and run.entry_count
                       and run.entries.count() == run.entry_count
                       and not run.entries.exclude(status="ChoDuyet").exists()
                       and not hard_conflicts)
    approved_count = run.entries.filter(status="DaDuyet").count() if run else 0
    return render(request, "school/auto_schedule.html", {
        "semesters": semesters, "selected": selected, "errors": errors,
        "input_issues": input_issues,
        "input_issue_count": input_issue_count,
        "run": run, "recent": recent, "can_approve": can_approve,
        "approved_count": approved_count, "hard_conflicts": hard_conflicts,
    }, status=400 if errors or input_issues else 200)


@staff_member_required
def auto_template(request, kind):
    if kind not in AUTO_SHEETS:
        from django.http import Http404
        raise Http404
    response = HttpResponse(template_bytes(kind),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="mau_tu_dong_{kind}.xlsx"'
    return response
