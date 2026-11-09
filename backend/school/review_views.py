"""Admin-only review screens for proposed teaching assignments."""

from urllib.parse import urlencode
import logging
import sqlite3

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db import connection, OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from .forms import ScheduleReviewForm
from .models import AlgorithmRun, Course, Faculty, Lecturer, Room, ScheduleEntry, Semester
from .preference_report import preference_report
from .services import ScheduleConflictError, approve_schedule_entries, save_schedule_entry
from .access import scoped, global_action


FILTER_KEYS = ("faculty", "course", "group", "lecturer", "room", "status", "run")
log = logging.getLogger(__name__)


def _sqlite_busy(exc):
    code = getattr(exc.__cause__, "sqlite_errorcode", None)
    return connection.vendor == "sqlite" and (
        (isinstance(code, int) and (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)) or
        str(exc).lower() == "database is locked" or
        str(exc).lower().startswith("database table is locked"))


def _review_filters(request):
    source = request.POST if request.method == "POST" else request.GET
    return {key: source.get(key, "").strip() for key in FILTER_KEYS}


def _review_entries(semester, filters):
    if semester is None:
        return ScheduleEntry.objects.none()
    qs = (ScheduleEntry.objects.filter(group__semester=semester)
          .select_related("group__course", "lecturer", "room", "approved_by")
          .prefetch_related("schedule_weeks").order_by("day", "start_period_id", "pk"))
    if filters["faculty"]:
        qs = qs.filter(lecturer__department__faculty_id=filters["faculty"])
    if filters["course"].isdigit():
        qs = qs.filter(group__course_id=filters["course"])
    if filters["group"]:
        qs = qs.filter(group__group=filters["group"])
    if filters["lecturer"].isdigit():
        qs = qs.filter(lecturer_id=filters["lecturer"])
    if filters["room"].isdigit():
        qs = qs.filter(room_id=filters["room"])
    if filters["status"] in ("ChoDuyet", "DaDuyet"):
        qs = qs.filter(status=filters["status"])
    if filters["run"].isdigit():
        qs = qs.filter(algorithm_run_id=filters["run"])
    return qs


def _review_context(request, semester, errors, filters, faculty):
    semesters = Semester.objects.all().order_by("-start_date")
    context = {"semesters": semesters, "selected_semester": semester,
               "errors": errors, "courses": scoped(Course.objects.all(), request.user).order_by("code"),
               "faculties": scoped(Faculty.objects.all(), request.user).order_by("name"),
               "selected_faculty": faculty,
               "lecturers": (Lecturer.objects.filter(department__faculty=faculty)
                             if faculty else Lecturer.objects.all()).order_by("name"),
               "rooms": Room.objects.all().order_by("code")}
    context["lecturers"] = scoped(context["lecturers"], request.user)
    context["lecturer_choices"] = scoped(
        Lecturer.objects.select_related("department").order_by("name", "pk"), request.user
    )
    context["filters"] = filters
    qs = scoped(_review_entries(semester, filters), request.user) if not errors else ScheduleEntry.objects.none()
    context["count"] = qs.count()
    context["page"] = Paginator(qs, 50).get_page(request.GET.get("page"))
    page_entries = list(context["page"].object_list)
    page_ids = [entry.pk for entry in page_entries]
    unlocked = semester is not None and semester.status != "DaKhoa"
    editable = set(scoped(ScheduleEntry.objects.filter(pk__in=page_ids), request.user, "change")
                   .values_list("pk", flat=True)) if unlocked else set()
    approvable = set(scoped(ScheduleEntry.objects.filter(pk__in=page_ids, status="ChoDuyet"),
                           request.user, "approve").values_list("pk", flat=True)) if unlocked else set()
    for entry in page_entries:
        entry.can_edit = entry.pk in editable
        entry.can_approve = entry.pk in approvable
    context["page"].object_list = page_entries
    context["can_approve_entries"] = bool(approvable)
    context["query_prefix"] = urlencode({"semester": semester.pk if semester else "",
                                          **{key: value for key, value in filters.items() if value}})
    selected_run = (AlgorithmRun.objects.filter(pk=filters["run"], semester=semester).first()
                    if semester and filters["run"].isdigit() else None)
    context["selected_run"] = selected_run
    context["preference_report"] = (preference_report(
        semester, run_id=int(filters["run"]) if filters["run"].isdigit() else None,
        snapshot=(selected_run.preferences_snapshot if selected_run.preferences_captured_at else None)
        if selected_run else None,
    ) if semester and global_action(request.user) else None)
    violation_ids = [entry.pk for entry in context["preference_report"]["violations"]] if context["preference_report"] else []
    context["editable_violation_ids"] = set(scoped(
        ScheduleEntry.objects.filter(pk__in=violation_ids), request.user, "change"
    ).values_list("pk", flat=True)) if unlocked and context["preference_report"] else set()
    return context


@staff_member_required
def review_schedules(request):
    filters = _review_filters(request)
    semester_id = request.POST.get("semester") if request.method == "POST" else request.GET.get("semester")
    if semester_id and semester_id.isdigit():
        semester = Semester.objects.filter(pk=semester_id).first()
    elif semester_id:
        semester = None
    else:
        semester = Semester.objects.order_by("-start_date").first()
    errors = []
    error_status = 400
    if semester_id and semester is None:
        errors.append("Học kỳ không hợp lệ")
    faculty = (Faculty.objects.filter(pk=filters["faculty"]).first()
               if filters["faculty"].isdigit() else None)
    if filters["faculty"] and faculty is None:
        errors.append("Khoa không hợp lệ")
    if filters["lecturer"] and (not filters["lecturer"].isdigit() or
                                not Lecturer.objects.filter(pk=filters["lecturer"],
                                                            **({"department__faculty": faculty}
                                                               if faculty else {})).exists()):
        errors.append("Giảng viên không thuộc khoa đã chọn" if faculty else "Giảng viên không hợp lệ")
    if request.method == "POST":
        if semester is None:
            errors.append("Hãy chọn học kỳ")
        elif request.POST.get("action") != "approve":
            errors.append("Thao tác không hợp lệ")
        elif not errors:
            raw_ids = request.POST.getlist("entry_ids")
            if any(not raw.isdigit() for raw in raw_ids):
                errors.append("Mã buổi dạy không hợp lệ")
            else:
                try:
                    ids = [int(raw) for raw in raw_ids]
                    if _review_entries(semester, filters).filter(pk__in=ids).count() != len(set(ids)):
                        raise ValidationError("Có buổi dạy nằm ngoài bộ lọc đang chọn")
                    count = approve_schedule_entries(semester.pk, ids, actor=request.user)
                    messages.success(request, f"Đã duyệt {count} buổi dạy.")
                    query = urlencode({"semester": semester.pk,
                                       **{key: value for key, value in filters.items() if value}})
                    return redirect(f"{reverse('review_schedules')}?{query}")
                except (ValidationError, ScheduleConflictError) as exc:
                    errors.append(f"Không thể duyệt; dữ liệu chưa được thay đổi: {exc}")
                except OperationalError as exc:
                    if not _sqlite_busy(exc):
                        raise
                    # The service's atomic block (including commit) has exited
                    # and rolled back before we render or issue more queries.
                    log.warning("SQLite busy approving semester %s, %s entries", semester.pk, len(ids), exc_info=True)
                    errors.append("Cơ sở dữ liệu đang bận. Yêu cầu này chưa duyệt buổi nào. "
                                  "Hãy chờ thao tác đang chạy hoàn tất, tải lại trang rồi thử lại.")
                    error_status = 503
    response = render(request, "school/review_schedules.html", _review_context(request, semester, errors, filters, faculty),
                      status=error_status if errors else 200)
    if error_status == 503:
        response["Retry-After"] = "2"
    return response


@staff_member_required
def edit_schedule(request, entry_id):
    entry = get_object_or_404(ScheduleEntry.objects.select_related("group__course", "group__semester", "lecturer", "room")
                              .prefetch_related("schedule_weeks"), pk=entry_id)
    form = ScheduleReviewForm(request.POST if request.method == "POST" else None, entry=entry)
    for field in form.fields.values():
        if hasattr(field, "queryset"):
            field.queryset = scoped(field.queryset, request.user)
    if request.method == "POST":
        if form.is_valid():
            values = dict(form.cleaned_data)
            values["status"] = "ChoDuyet"
            try:
                save_schedule_entry(values, instance=entry, actor=request.user)
                messages.success(request, "Đã lưu lịch ở trạng thái chờ duyệt.")
                return redirect(f"{reverse('review_schedules')}?semester={entry.group.semester_id}")
            except ScheduleConflictError as exc:
                form.add_error(None, f"Trùng lịch: {exc.conflicts}")
            except ValidationError as exc:
                form.add_error(None, str(exc))
    return render(request, "school/edit_schedule.html", {"entry": entry, "form": form},
                  status=400 if form.errors else 200)
