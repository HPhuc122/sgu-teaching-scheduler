from django import forms
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .access import scoped, require_object, require_global, roles, system_admin
from .models import (Faculty, Semester, Lecturer, GroupTeachingPlan, TeachingAssignment,
                     LecturerOtherDuty, OffCampusActivity, ScheduleEntry)
from .planning import appointment_kind, planned_periods, check_entry_plan, workbooks_from_plan
from .planning_exports import forms_workbook

LABELS = {"CO_HUU": "Cơ hữu", "MOI_GIANG": "Mời giảng", "THINH_GIANG": "Thỉnh giảng", "CHUA_PHAN_CONG": "Chưa phân công"}


def _staff(user):
    if not system_admin(user) and not roles(user).exists():
        raise PermissionDenied("Chưa được phân quyền nghiệp vụ")


@staff_member_required
def teaching_plans(request):
    _staff(request.user)
    semester_id = request.GET.get("semester", "")
    year = request.GET.get("year", "")
    faculty_id = request.GET.get("faculty", "")
    semester = get_object_or_404(Semester, pk=semester_id) if semester_id.isdigit() else None
    if semester:
        year = semester.academic_year
    if not year:
        year = Semester.objects.order_by("-start_date").values_list("academic_year", flat=True).first() or ""
    faculty = None
    if faculty_id.isdigit():
        faculty = get_object_or_404(scoped(Faculty.objects.all(), request.user), pk=faculty_id)
    assignments = scoped(TeachingAssignment.objects.all(), request.user).filter(group__semester__academic_year=year)
    activities = scoped(OffCampusActivity.objects.all(), request.user).filter(semester__academic_year=year)
    duties = scoped(LecturerOtherDuty.objects.all(), request.user).filter(semester__academic_year=year)
    if semester:
        assignments = assignments.filter(group__semester=semester)
        activities = activities.filter(semester=semester)
        duties = duties.filter(semester=semester)
    if faculty:
        assignments = assignments.filter(group__course__department__faculty=faculty)
        activities = activities.filter(Q(cohort__department__faculty=faculty) | Q(
            cohort__department__isnull=True, cohort__groupcohort__group__course__department__faculty=faculty)).distinct()
        duties = duties.filter(lecturer__department__faculty=faculty)
    assignments = assignments.select_related("group__course__department__faculty", "group__semester", "group__teaching_plan", "lecturer__department__faculty", "fixed_lecturer").order_by("group__semester__start_date", "group__course__code", "group__group", "request_code", "pk")
    if request.method == "POST":
        require_global(request.user, "run")
        try:
            selected_id = request.POST.get("semester", "")
            if not selected_id.isdigit():
                raise ValueError("Chọn học kỳ để xếp lịch")
            selected = get_object_or_404(Semester, pk=selected_id)
            from .schedule_queue import enqueue_schedule
            run = enqueue_schedule(selected.pk, workbooks_from_plan(selected), request.user)
            return redirect(f"/admin/auto-schedule/?run={run.pk}")
        except ValueError as exc:
            messages.error(request, str(exc))
    if request.GET.get("download") == "xlsx":
        if faculty is None:
            messages.error(request, "Chọn khoa để xuất bộ biểu mẫu")
        else:
            # Mẫu 2 includes the home faculty's staff teaching for other units.
            extra = scoped(TeachingAssignment.objects.all(), request.user).filter(
                group__semester__academic_year=year, lecturer__department__faculty=faculty)
            if semester:
                extra = extra.filter(group__semester=semester)
            combined = TeachingAssignment.objects.filter(pk__in=set(assignments.values_list("pk", flat=True)) | set(extra.values_list("pk", flat=True))).select_related(
                "group__course__department__faculty", "group__semester", "group__teaching_plan", "lecturer__department__faculty")
            response = HttpResponse(forms_workbook(faculty, year, combined, activities.select_related("semester", "cohort"), duties.select_related("lecturer__department__faculty")),
                                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = 'attachment; filename="ke_hoach_phan_cong.xlsx"'
            return response
    # Summary counts cover the full filtered scope; only page items need reconciliation.
    summary = assignments.aggregate(
        unassigned=Count("pk", filter=Q(lecturer__isnull=True)),
        unknown_semesters=Count("pk", filter=(
            (Q(group__semester__number__isnull=True) | Q(group__semester__number=0)) &
            (Q(group__teaching_plan__semester_number__isnull=True) | Q(group__teaching_plan__semester_number=0)))),
    )
    paginator = Paginator(assignments, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_assignments = list(page_obj.object_list)
    page_ids = [a.pk for a in page_assignments]
    editable = set(scoped(TeachingAssignment.objects.filter(pk__in=page_ids), request.user, "change").values_list("pk", flat=True))
    entries = ScheduleEntry.objects.filter(group_id__in={a.group_id for a in page_assignments}).prefetch_related("schedule_weeks")
    rows = []
    entry_map = {}
    for entry in entries:
        entry_map.setdefault((entry.group_id, entry.request_code), []).append(entry)
    for a in page_assignments:
        scheduled = entry_map.get((a.group_id, a.request_code), [])
        actual = sum(e.period_count * len(e.schedule_weeks.all()) for e in scheduled)
        matched = (len(scheduled) == 1 and scheduled[0].lecturer_id == a.lecturer_id
                   and scheduled[0].period_count == a.period_count
                   and {w.week for w in scheduled[0].schedule_weeks.all()} == set(a.weeks))
        rows.append(dict(assignment=a, kind=LABELS[appointment_kind(a)], planned=planned_periods(a), scheduled=actual,
                         can_edit=a.pk in editable and a.group.semester.status != "DaKhoa",
                         state="Chưa xếp lịch" if not scheduled else "Khớp kế hoạch" if matched else "Cần đối chiếu",
                         approved=matched and scheduled[0].status == "DaDuyet"))
    pagination_filters = request.GET.copy()
    for key in list(pagination_filters):
        if key not in ("year", "semester", "faculty"):
            del pagination_filters[key]
    pagination_filters["year"] = year
    return render(request, "school/teaching_plans.html", dict(
        rows=rows, total=paginator.count, page_obj=page_obj,
        page_range=paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1),
        page_ellipsis=paginator.ELLIPSIS, pagination_query=pagination_filters.urlencode(),
        semesters=Semester.objects.order_by("-start_date"), semester=semester,
        years=Semester.objects.values_list("academic_year", flat=True).distinct(), year=year,
        faculties=scoped(Faculty.objects.all(), request.user).order_by("name"), faculty=faculty,
        activities=activities.select_related("cohort", "semester"), duties=duties.select_related("lecturer", "semester"),
        unassigned=summary["unassigned"],
        manage=system_admin(request.user) or roles(request.user).filter(can_manage=True).exclude(role="HEAD").exists(),
        unknown_semesters=summary["unknown_semesters"]))


class PlanForm(forms.ModelForm):
    class Meta:
        model = GroupTeachingPlan
        exclude = ("group",)
        labels = {"semester_number": "Học kỳ số", "cohort_label": "Khóa", "lecture_periods": "Số tiết LT của học phần",
                  "exercise_periods": "Số tiết BT của học phần", "practical_periods": "Số tiết TH của học phần", "coefficient": "Hệ số học phần", "note": "Ghi chú"}


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = TeachingAssignment
        fields = ("fixed_lecturer", "component", "reported_periods")
        labels = {"fixed_lecturer": "Giảng viên phân công cố định (để trống để tự chọn)", "component": "Loại buổi", "reported_periods": "Số tiết thực tế theo kế hoạch"}


class ActivityForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cohort"].label_from_instance = lambda c: f"{c.name} · {c.semester.name}"
        self.fields["cohort"].queryset = self.fields["cohort"].queryset.select_related("semester")

    class Meta:
        model = OffCampusActivity
        fields = ("semester", "cohort", "code", "cohort_label", "training_level", "description", "location", "start_date", "end_date", "student_count", "semester_number")
        widgets = {"start_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                   "end_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}
        help_texts = {"start_date": "Tuần 1 bắt đầu vào thứ Hai của tuần chứa ngày bắt đầu học kỳ. Hoạt động chặn cả ngày của lớp liên quan."}
        labels = {"semester": "Học kỳ", "cohort": "Lớp", "code": "Mã hoạt động", "cohort_label": "Khóa", "training_level": "Trình độ đào tạo",
                  "description": "Nội dung hoạt động", "location": "Địa điểm", "start_date": "Từ ngày", "end_date": "Đến ngày", "student_count": "Số sinh viên", "semester_number": "Học kỳ số"}

    def clean(self):
        data = super().clean()
        semester, cohort, start, end = (data.get(k) for k in ("semester", "cohort", "start_date", "end_date"))
        if semester and cohort and cohort.semester_id != semester.pk:
            self.add_error("cohort", "Lớp không thuộc học kỳ đã chọn")
        if semester and start and end and not semester.start_date <= start <= end <= semester.end_date:
            self.add_error("end_date", "Khoảng ngày phải nằm trong học kỳ và kết thúc sau khi bắt đầu")
        if semester and semester.number and data.get("semester_number") and semester.number != data["semester_number"]:
            self.add_error("semester_number", "Số học kỳ không khớp")
        if data.get("student_count") == 0:
            self.add_error("student_count", "Số sinh viên phải lớn hơn 0")
        return data


class DutyForm(forms.ModelForm):
    class Meta:
        model = LecturerOtherDuty
        fields = ("semester", "lecturer", "code", "description", "kind", "periods")
        labels = {"semester": "Học kỳ", "lecturer": "Giảng viên", "code": "Mã công tác", "description": "Nội dung", "kind": "Loại công tác", "periods": "Số tiết công tác"}


@staff_member_required
def edit_plan_item(request, kind, pk=None):
    _staff(request.user)
    models = {"group": (GroupTeachingPlan, PlanForm), "assignment": (TeachingAssignment, AssignmentForm),
              "activity": (OffCampusActivity, ActivityForm), "duty": (LecturerOtherDuty, DutyForm)}
    if kind not in models or (pk is None and kind in ("group", "assignment")):
        from django.http import Http404
        raise Http404
    model, form_class = models[kind]
    obj = get_object_or_404(scoped(model.objects.all(), request.user, "change"), pk=pk) if pk else None
    form = form_class(request.POST if request.method == "POST" else None, instance=obj)
    for name in ("lecturer", "cohort"):
        if name in form.fields:
            form.fields[name].queryset = scoped(form.fields[name].queryset, request.user, "change")
    if "semester" in form.fields:
        form.fields["semester"].queryset = Semester.objects.exclude(status="DaKhoa")
    if obj and kind in ("activity", "duty"):
        for name in ("semester", "cohort" if kind == "activity" else "lecturer"):
            form.fields[name].disabled = True
    if kind == "assignment":
        form.fields["fixed_lecturer"].queryset = Lecturer.objects.filter(status="DangCongTac", teachingqualification__course=obj.group.course).distinct()
    if request.method == "POST" and request.POST.get("action") == "delete" and obj and kind in ("activity", "duty"):
        require_object(request.user, obj, "delete")
        with transaction.atomic():
            semester = Semester.objects.select_for_update().get(pk=obj.semester_id)
            if semester.status == "DaKhoa" or hasattr(semester, "active_schedule_run"):
                form.add_error(None, "Học kỳ đã khóa hoặc đang xếp lịch")
            else:
                obj.delete()
                messages.success(request, "Đã xóa mục kế hoạch")
                return redirect(f"/admin/teaching-plans/?semester={semester.pk}")
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                candidate = form.save(commit=False)
                semester = candidate.group.semester if kind in ("group", "assignment") else candidate.semester
                semester = Semester.objects.select_for_update().get(pk=semester.pk)
                if semester.status == "DaKhoa":
                    raise ValueError("Học kỳ đã khóa")
                if hasattr(semester, "active_schedule_run"):
                    raise ValueError("Học kỳ đang có phiên xếp lịch; hãy chờ hoàn tất")
                if kind in ("assignment", "group"):
                    require_object(request.user, candidate.group, "change")
                    if ScheduleEntry.objects.filter(group=candidate.group, status="DaDuyet").exists():
                        raise ValueError("Nhóm đã có lịch được duyệt; cần đưa lịch về chờ duyệt trước khi sửa kế hoạch")
                else:
                    require_object(request.user, candidate.cohort if kind == "activity" else candidate.lecturer, "change")
                if kind == "assignment":
                    candidate.lecturer = candidate.fixed_lecturer
                if kind == "group" and semester.number and candidate.semester_number and semester.number != candidate.semester_number:
                    raise ValueError("Số học kỳ không khớp học kỳ đã chọn")
                candidate.save()
                if kind == "activity":
                    for entry in ScheduleEntry.objects.filter(group__cohort_links__cohort=candidate.cohort).select_related("group__semester").prefetch_related("schedule_weeks"):
                        check_entry_plan(entry, [w.week for w in entry.schedule_weeks.all()])
                messages.success(request, "Đã lưu kế hoạch. Nếu đã có lịch chờ duyệt, hãy xếp lịch lại để áp dụng thay đổi.")
                return redirect(f"/admin/teaching-plans/?semester={semester.pk}")
        except ValueError as exc:
            form.add_error(None, str(exc))
    cohort_options = []
    if kind == "activity":
        cohort_options = [{"id": c.pk, "semester": c.semester_id, "label": form.fields["cohort"].label_from_instance(c)}
                          for c in form.fields["cohort"].queryset]
    return render(request, "school/edit_plan_item.html", {
        "form": form, "kind": kind, "obj": obj, "cohort_options": cohort_options,
    }, status=400 if form.errors else 200)
