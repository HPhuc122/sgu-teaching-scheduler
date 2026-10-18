from rest_framework import permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import (Building, Cohort, Course, CourseGroup, CourseProgram, Department, Faculty,
                     GroupCohort, Lecturer, LecturerPreference, Period, Room,
                     Program, ScheduleEntry, Semester, TeachingQualification)
from .serializers import (BuildingSerializer, CohortSerializer, CourseGroupSerializer,
                          CourseProgramSerializer, CourseSerializer, DepartmentSerializer, FacultySerializer,
                          GroupCohortSerializer, LecturerPreferenceSerializer,
                          LecturerSerializer, PeriodSerializer, RoomSerializer,
                          ProgramSerializer, ScheduleEntrySerializer, SemesterSerializer,
                          TeachingQualificationSerializer)
from .services import ScheduleConflictError
from .forms import PreferenceForm
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import HttpResponse

from .schedule_import import read_excel, template_bytes, validate_rows
from .services import save_schedule_entry
from .catalog_import import SHEETS, commit_catalog, read_workbook, template_bytes as catalog_template_bytes, validate_catalog


@staff_member_required
def import_catalog(request, kind):
    if kind not in SHEETS:
        from django.http import Http404
        raise Http404
    semesters = Semester.objects.all().order_by("-start_date") if kind == "courses" else []
    context = {"kind": kind, "sheets": SHEETS[kind], "semesters": semesters,
               "selected_semester": "", "data": {}, "errors": []}
    if request.method == "GET":
        return render(request, "school/import_catalog.html", context)
    semester_id = request.POST.get("semester", "") if kind == "courses" else ""
    context["selected_semester"] = semester_id
    semester = Semester.objects.filter(pk=semester_id).first() if semester_id.isdigit() else None
    if kind == "courses" and semester is None:
        context["errors"] = [{"message": "Hãy chọn học kỳ hợp lệ"}]
        return render(request, "school/import_catalog.html", context, status=400)
    session_key = f"catalog_import_{kind}"
    action = request.POST.get("action")
    if action == "preview":
        request.session.pop(session_key, None)
        upload = request.FILES.get("file")
        if upload is None:
            context["errors"] = [{"message": "Hãy chọn file Excel"}]
            return render(request, "school/import_catalog.html", context, status=400)
        try:
            data = read_workbook(upload, kind)
        except ValueError as exc:
            context["errors"] = [{"message": str(exc)}]
            return render(request, "school/import_catalog.html", context, status=400)
        request.session[session_key] = {"semester": semester.pk if semester else None, "data": data}
    elif action == "confirm":
        draft = request.session.get(session_key)
        if not draft or draft["semester"] != (semester.pk if semester else None):
            context["errors"] = [{"message": "Bản xem trước đã hết hiệu lực; hãy tải lại file"}]
            return render(request, "school/import_catalog.html", context, status=400)
        data = draft["data"]
    else:
        context["errors"] = [{"message": "Thao tác không hợp lệ"}]
        return render(request, "school/import_catalog.html", context, status=400)
    context["data"] = data
    if action == "preview":
        context["errors"] = validate_catalog(kind, data, semester)
    else:
        with transaction.atomic():
            # Catalog changes and schedule creation share the semester row locks.
            list(Semester.objects.order_by("pk").select_for_update().values_list("pk", flat=True))
            if semester:
                semester.refresh_from_db()
            context["errors"] = validate_catalog(kind, data, semester)
            if not context["errors"]:
                commit_catalog(kind, data, semester)
        if not context["errors"]:
            del request.session[session_key]
            messages.success(request, "Đã nhập danh mục thành công.")
            return redirect("import_catalog", kind=kind)
    return render(request, "school/import_catalog.html", context,
                  status=400 if context["errors"] else 200)


@staff_member_required
def import_catalog_template(request, kind):
    if kind not in SHEETS:
        from django.http import Http404
        raise Http404
    response = HttpResponse(catalog_template_bytes(kind),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="mau_{kind}_sgu.xlsx"'
    return response


@staff_member_required
def import_schedule(request):
    semesters = Semester.objects.all().order_by("-start_date")
    context = {"semesters": semesters, "selected_semester": "", "rows": [], "errors": []}
    if request.method == "GET":
        return render(request, "school/import_schedule.html", context)
    semester_id = request.POST.get("semester", "")
    context["selected_semester"] = semester_id
    semester = Semester.objects.filter(pk=semester_id).first() if semester_id.isdigit() else None
    if semester is None:
        context["errors"] = [{"line": None, "message": "Hãy chọn học kỳ hợp lệ"}]
        return render(request, "school/import_schedule.html", context, status=400)
    if request.POST.get("action") == "preview":
        request.session.pop("schedule_import", None)
        upload = request.FILES.get("file")
        if upload is None:
            context["errors"] = [{"line": None, "message": "Hãy chọn file Excel"}]
            return render(request, "school/import_schedule.html", context, status=400)
        try:
            rows = read_excel(upload)
        except ValueError as exc:
            context["errors"] = [{"line": None, "message": str(exc)}]
            return render(request, "school/import_schedule.html", context, status=400)
        request.session["schedule_import"] = {"semester": semester.pk, "rows": rows}
    elif request.POST.get("action") == "confirm":
        draft = request.session.get("schedule_import")
        if not draft or draft["semester"] != semester.pk:
            context["errors"] = [{"line": None, "message": "Bản xem trước không còn phù hợp; hãy tải lại file"}]
            return render(request, "school/import_schedule.html", context, status=400)
        rows = draft["rows"]
    else:
        context["errors"] = [{"line": None, "message": "Thao tác không hợp lệ"}]
        return render(request, "school/import_schedule.html", context, status=400)
    context["rows"] = rows
    try:
        if request.POST.get("action") == "confirm":
            with transaction.atomic():
                semester = Semester.objects.select_for_update().get(pk=semester.pk)
                resolved, errors = validate_rows(semester, rows)
                if errors:
                    context["errors"] = errors
                    return render(request, "school/import_schedule.html", context, status=400)
                for item in resolved:
                    save_schedule_entry({
                        "group": item["group"], "lecturer": item["lecturer"],
                        "room": item["room"], "other_location": item["other_location"],
                        "day": item["day"], "start_period": Period.objects.get(pk=item["start_period_id"]),
                        "period_count": item["period_count"], "weeks": item["weeks"],
                        "source": "Excel", "status": "ChoDuyet",
                    })
            del request.session["schedule_import"]
            messages.success(request, f"Đã nhập {len(resolved)} buổi dạy vào học kỳ {semester.name}.")
            return redirect("import_schedule")
        _, context["errors"] = validate_rows(semester, rows)
    except Exception as exc:
        # Any failed save rolls back the whole batch; the staged preview is retained.
        from .services import ScheduleConflictError
        from rest_framework.exceptions import ValidationError as ApiValidationError
        if not isinstance(exc, (ScheduleConflictError, ApiValidationError)):
            raise
        context["errors"] = [{"line": None, "message": f"Dữ liệu đã thay đổi; nhập lại sau khi kiểm tra: {exc}"}]
    return render(request, "school/import_schedule.html", context,
                  status=400 if context["errors"] else 200)


@staff_member_required
def import_schedule_template(request):
    response = HttpResponse(template_bytes(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="mau_nhap_lich_sgu.xlsx"'
    return response


class AdminViewSet(viewsets.ModelViewSet):
    from .access import UnitPermission
    permission_classes = [UnitPermission]

    def get_queryset(self):
        from .access import scoped
        action = {"create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}.get(self.action, "view")
        return scoped(super().get_queryset(), self.request.user, action)

    def perform_create(self, serializer):
        from .access import check_write
        check_write(self.request.user, serializer.Meta.model, serializer.validated_data, action="add")
        if serializer.Meta.model._meta.model_name in ("teachingquota", "workloadpolicy", "conversionrule"):
            from .workload import save_configuration
            obj = serializer.Meta.model(**serializer.validated_data)
            save_configuration(obj, self.request.user)
            serializer.instance = obj
        else:
            serializer.save()

    def perform_update(self, serializer):
        from .access import check_write
        check_write(self.request.user, serializer.Meta.model, serializer.validated_data, serializer.instance)
        if serializer.Meta.model._meta.model_name in ("teachingquota", "workloadpolicy", "conversionrule"):
            from .workload import save_configuration
            for key, value in serializer.validated_data.items():
                setattr(serializer.instance, key, value)
            save_configuration(serializer.instance, self.request.user)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        from .access import check_delete
        from django.db.models.deletion import ProtectedError
        check_delete(self.request.user, instance)
        with transaction.atomic():
            if instance._meta.model_name in ("teachingquota", "workloadpolicy", "conversionrule"):
                semester = Semester.objects.select_for_update().get(pk=instance.semester_id)
                if semester.status == "DaKhoa":
                    raise PermissionDenied("Học kỳ đã khóa.")
            try:
                instance.delete()
            except ProtectedError as exc:
                raise ValidationError("Đối tượng còn được sử dụng; không thể xóa.") from exc


from .models import TeachingQuota, WorkloadPolicy, ConversionRule
from .serializers import TeachingQuotaSerializer, WorkloadPolicySerializer, ConversionRuleSerializer

class TeachingQuotaViewSet(AdminViewSet):
    queryset = TeachingQuota.objects.all()
    serializer_class = TeachingQuotaSerializer

class WorkloadPolicyViewSet(AdminViewSet):
    queryset = WorkloadPolicy.objects.all()
    serializer_class = WorkloadPolicySerializer

class ConversionRuleViewSet(AdminViewSet):
    queryset = ConversionRule.objects.all()
    serializer_class = ConversionRuleSerializer


class FacultyViewSet(AdminViewSet):
    queryset = Faculty.objects.all()
    serializer_class = FacultySerializer


class DepartmentViewSet(AdminViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer


class LecturerViewSet(AdminViewSet):
    queryset = Lecturer.objects.all()
    serializer_class = LecturerSerializer


class CourseViewSet(AdminViewSet):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer


class ProgramViewSet(AdminViewSet):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer


class CourseProgramViewSet(AdminViewSet):
    queryset = CourseProgram.objects.all()
    serializer_class = CourseProgramSerializer


class TeachingQualificationViewSet(AdminViewSet):
    queryset = TeachingQualification.objects.all()
    serializer_class = TeachingQualificationSerializer

    def perform_destroy(self, instance):
        if ScheduleEntry.objects.filter(lecturer=instance.lecturer, group__course=instance.course,
                                        status="DaDuyet").exists():
            raise ValidationError("Chuyên môn này đang được dùng trong lịch đã duyệt")
        instance.delete()


class SemesterViewSet(AdminViewSet):
    queryset = Semester.objects.all()
    serializer_class = SemesterSerializer


class BuildingViewSet(AdminViewSet):
    queryset = Building.objects.all()
    serializer_class = BuildingSerializer


class RoomViewSet(AdminViewSet):
    queryset = Room.objects.all()
    serializer_class = RoomSerializer


class PeriodViewSet(AdminViewSet):
    queryset = Period.objects.all()
    serializer_class = PeriodSerializer


class CourseGroupViewSet(AdminViewSet):
    queryset = CourseGroup.objects.all()
    serializer_class = CourseGroupSerializer


class CohortViewSet(AdminViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer


class GroupCohortViewSet(AdminViewSet):
    queryset = GroupCohort.objects.all()
    serializer_class = GroupCohortSerializer


class ScheduleEntryViewSet(AdminViewSet):
    serializer_class = ScheduleEntrySerializer
    queryset = (ScheduleEntry.objects.select_related("group", "lecturer", "room")
                .prefetch_related("schedule_weeks").all())

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except ScheduleConflictError as exc:
            return Response({"conflicts": exc.conflicts}, status=409)

    def update(self, request, *args, **kwargs):
        try:
            return super().update(request, *args, **kwargs)
        except ScheduleConflictError as exc:
            return Response({"conflicts": exc.conflicts}, status=409)

    def get_queryset(self):
        qs = super().get_queryset()
        semester = self.request.query_params.get("semester")
        lecturer = self.request.query_params.get("lecturer")
        if semester:
            qs = qs.filter(group__semester_id=semester)
        if lecturer:
            qs = qs.filter(lecturer_id=lecturer)
        return qs


def _my_lecturer(request):
    lecturer = Lecturer.objects.filter(user=request.user).first()
    if not lecturer:
        raise PermissionDenied("Tài khoản chưa liên kết với hồ sơ giảng viên")
    return lecturer


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def my_profile(request):
    return Response(LecturerSerializer(_my_lecturer(request)).data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def my_schedule(request):
    lecturer = _my_lecturer(request)
    qs = ScheduleEntry.objects.filter(lecturer=lecturer, status="DaDuyet").prefetch_related("schedule_weeks")
    semester = request.query_params.get("semester")
    if semester:
        qs = qs.filter(group__semester_id=semester)
    return Response(ScheduleEntrySerializer(qs, many=True).data)


@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def my_preferences(request):
    lecturer = _my_lecturer(request)
    if request.method == "GET":
        qs = LecturerPreference.objects.filter(lecturer=lecturer)
        semester = request.query_params.get("semester")
        if semester:
            qs = qs.filter(semester_id=semester)
        return Response(LecturerPreferenceSerializer(qs, many=True).data)
    serializer = LecturerPreferenceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data["semester"].status == "DaKhoa":
        raise PermissionDenied("Học kỳ đã khóa")
    serializer.save(lecturer=lecturer)
    return Response(serializer.data, status=201)
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse


@login_required
def portal(request):
    if request.user.is_staff and not Lecturer.objects.filter(user=request.user).exists():
        from .access import global_action
        return redirect("auto_schedule" if global_action(request.user) else "admin:index")
    lecturer = Lecturer.objects.filter(user=request.user).select_related("department").first()
    if not lecturer:
        return render(request, "school/no_profile.html", status=403)
    semester_id = request.GET.get("semester")
    semesters = Semester.objects.all().order_by("-start_date")
    if not semester_id:
        first = semesters.first()
        semester_id = str(first.pk) if first else None
    entries = (ScheduleEntry.objects.filter(lecturer=lecturer, status="DaDuyet")
               .select_related("group__course", "room", "start_period")
               .prefetch_related("schedule_weeks")
               .order_by("day", "start_period_id"))
    if semester_id:
        entries = entries.filter(group__semester_id=semester_id)
    preferences = LecturerPreference.objects.filter(lecturer=lecturer)
    if semester_id:
        preferences = preferences.filter(semester_id=semester_id)
    return render(request, "school/portal.html", {
        "lecturer": lecturer, "semesters": semesters, "selected_semester": str(semester_id or ""),
        "entries": entries, "preferences": preferences, "form": PreferenceForm(initial={"semester": semester_id}),
    })


@login_required
def submit_preference(request):
    if request.method != "POST":
        return redirect("portal")
    lecturer = Lecturer.objects.filter(user=request.user).first()
    if not lecturer:
        return render(request, "school/no_profile.html", status=403)
    form = PreferenceForm(request.POST)
    if form.is_valid():
        preference = form.save(commit=False)
        preference.lecturer = lecturer
        preference.save()
        messages.success(request, "Đã ghi nhận nguyện vọng.")
        return redirect(f"{reverse('portal')}?semester={preference.semester_id}")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                label = form.fields[field].label if field in form.fields else "Biểu mẫu"
                messages.error(request, f"{label}: {error}")
    return redirect("portal")
