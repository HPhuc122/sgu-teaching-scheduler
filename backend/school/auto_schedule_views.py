"""Single-screen three-workbook automatic scheduling workflow."""

from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from rest_framework.exceptions import ValidationError

from .auto_schedule import AUTO_SHEETS, approve_algorithm_run, template_bytes
from .auto_schedule_errors import InputIssues
from .models import AlgorithmRun, Semester, PendingPlanImport
from .preference_checks import day_off_violations
from .schedule_queue import enqueue_schedule
from .services import ScheduleConflictError
from .access import can_approve as user_can_approve


class NewSemesterForm(forms.ModelForm):
    class Meta:
        model = Semester
        fields = ("name", "academic_year", "number", "start_date", "end_date", "week_count")
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}),
                   "end_date": forms.DateInput(attrs={"type": "date"})}
        labels = {"name": "Tên học kỳ", "academic_year": "Năm học",
                  "start_date": "Ngày bắt đầu", "end_date": "Ngày kết thúc",
                  "week_count": "Số tuần học"}

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "Ngày kết thúc phải sau ngày bắt đầu")
        name = data.get("name", "").strip()
        year = data.get("academic_year", "").strip()
        if name and year and Semester.objects.filter(name__iexact=name, academic_year__iexact=year).exists():
            self.add_error("name", "Học kỳ này đã tồn tại")
        if year and data.get("number") and Semester.objects.filter(academic_year=year, number=data["number"]).exists():
            self.add_error("number", "Số học kỳ này đã tồn tại trong năm học")
        return data


@staff_member_required
def auto_schedule(request):
    semesters = Semester.objects.all().order_by("-start_date")
    errors = []
    input_issues = []
    input_issue_count = 0
    run = None
    plan_preview = None
    selected = request.POST.get("semester", "") if request.method == "POST" else request.GET.get("semester", "")
    semester_form = NewSemesterForm(request.POST if request.method == "POST" and
                                    request.POST.get("action") == "create_semester" else None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_semester":
            if semester_form.is_valid():
                created = semester_form.save()
                return redirect(f"/admin/auto-schedule/?semester={created.pk}")
        elif action == "approve":
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
        elif action in ("confirm_plan", "cancel_plan"):
            from .plan_sync import confirm_import
            from .access import require_global
            require_global(request.user, "run")
            try:
                pending = PendingPlanImport.objects.get(pk=request.POST.get("preview_id"), actor=request.user)
                if action == "cancel_plan":
                    pending.delete()
                    return redirect(f"/admin/auto-schedule/?semester={pending.semester_id}")
                saved = confirm_import(pending.pk, request.user, remove_missing=request.POST.get("remove_missing") == "yes")
                return redirect(f"/admin/teaching-plans/?semester={saved.pk}")
            except (PendingPlanImport.DoesNotExist, forms.ValidationError):
                errors.append("Bản xem trước không hợp lệ hoặc không thuộc tài khoản hiện tại")
            except (ValueError, InputIssues) as exc:
                errors.append(str(exc))
        elif action in ("run", "save_plan"):
            semester = Semester.objects.filter(pk=selected).first() if selected.isdigit() else None
            if semester is None:
                errors.append("Hãy chọn học kỳ hợp lệ")
            else:
                try:
                    if action == "save_plan":
                        from .plan_sync import preview_import
                        plan_preview = preview_import(semester.pk, request.FILES, request.user)
                    else:
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
                       and not hard_conflicts
                       and user_can_approve(request.user, run.entries.all()))
    approved_count = run.entries.filter(status="DaDuyet").count() if run else 0
    return render(request, "school/auto_schedule.html", {
        "semesters": semesters, "selected": selected, "errors": errors,
        "input_issues": input_issues,
        "input_issue_count": input_issue_count,
        "run": run, "recent": recent, "can_approve": can_approve,
        "approved_count": approved_count, "hard_conflicts": hard_conflicts,
        "semester_form": semester_form,
        "plan_preview": plan_preview,
    }, status=400 if errors or input_issues or semester_form.errors else 200)


@staff_member_required
def auto_template(request, kind):
    if kind not in AUTO_SHEETS:
        from django.http import Http404
        raise Http404
    response = HttpResponse(template_bytes(kind),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="mau_tu_dong_{kind}.xlsx"'
    return response
