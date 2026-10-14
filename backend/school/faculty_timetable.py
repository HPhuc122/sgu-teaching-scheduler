"""Weekly approved teaching timetable for administrators."""

from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Faculty, Lecturer, Period, ScheduleEntry, Semester


DAYS = ((2, "Thứ 2"), (3, "Thứ 3"), (4, "Thứ 4"), (5, "Thứ 5"),
        (6, "Thứ 6"), (7, "Thứ 7"), (8, "Chủ nhật"))


@staff_member_required
def faculty_timetable(request):
    semesters = Semester.objects.all().order_by("-start_date")
    faculties = Faculty.objects.all().order_by("name")
    semester_id = request.GET.get("semester", "")
    faculty_id = request.GET.get("faculty", "")
    lecturer_id = request.GET.get("lecturer", "")
    week_text = request.GET.get("week", "1")
    semester = Semester.objects.filter(pk=semester_id).first() if semester_id.isdigit() else None
    faculty = Faculty.objects.filter(pk=faculty_id).first() if faculty_id.isdigit() else None
    errors = []
    if semester_id and semester is None:
        errors.append("Học kỳ không hợp lệ")
    if faculty_id and faculty is None:
        errors.append("Khoa không hợp lệ")
    try:
        week = int(week_text)
    except ValueError:
        week = 0
    if week < 1 or (semester and week > semester.week_count):
        errors.append("Tuần học không hợp lệ")
    lecturers = Lecturer.objects.filter(department__faculty=faculty).order_by("name", "pk") if faculty else Lecturer.objects.none()
    if lecturer_id:
        if not lecturer_id.isdigit() or not lecturers.filter(pk=lecturer_id).exists():
            errors.append("Giảng viên không thuộc khoa đã chọn")
        else:
            lecturers = lecturers.filter(pk=lecturer_id)

    page = None
    timetable = []
    public_demo_count = 0
    if semester and faculty and not errors:
        public_demo_count = ScheduleEntry.objects.filter(
            group__semester=semester, lecturer__department__faculty=faculty,
            source="SGUMoPhong", status="DaDuyet").count()
        if not lecturer_id:
            # The faculty may have many catalog-only lecturers. Show those who
            # actually teach in the selected week before paginating.
            lecturers = lecturers.filter(scheduleentry__group__semester=semester,
                                         scheduleentry__schedule_weeks__week=week,
                                         scheduleentry__status="DaDuyet").distinct()
        page = Paginator(lecturers, 10).get_page(request.GET.get("page"))
        periods = list(Period.objects.order_by("pk"))
        entries = (ScheduleEntry.objects.filter(
            group__semester=semester, lecturer_id__in=[item.pk for item in page.object_list],
            schedule_weeks__week=week, status="DaDuyet",
        ).select_related("group__course", "room").order_by("day", "start_period_id", "pk"))
        grid = {}
        for entry in entries:
            for number in range(entry.start_period_id, entry.start_period_id + entry.period_count):
                grid.setdefault((entry.lecturer_id, number, entry.day), []).append(
                    {"entry": entry, "is_start": number == entry.start_period_id}
                )
        for lecturer in page.object_list:
            rows = [{"period": period,
                     "cells": [{"slots": grid.get((lecturer.pk, period.pk, day), []),
                                "rowspan": 1} for day, _ in DAYS]}
                    for period in periods]
            for day_index, _ in enumerate(DAYS):
                index = 0
                while index < len(periods):
                    cell = rows[index]["cells"][day_index]
                    slots = cell["slots"]
                    if len(slots) == 1 and slots[0]["is_start"]:
                        entry = slots[0]["entry"]
                        span = entry.period_count
                        if (span > 1 and index + span <= len(periods)
                                and all(periods[index + offset].pk == entry.start_period_id + offset
                                        and len(grid.get((lecturer.pk, entry.start_period_id + offset,
                                                          DAYS[day_index][0]), [])) == 1
                                        and grid[(lecturer.pk, entry.start_period_id + offset,
                                                  DAYS[day_index][0])][0]["entry"].pk == entry.pk
                                        for offset in range(span))):
                            cell["rowspan"] = span
                            cell["end_period"] = entry.start_period_id + span - 1
                            for offset in range(1, span):
                                rows[index + offset]["cells"][day_index] = None
                            index += span
                            continue
                    index += 1
            timetable.append({"lecturer": lecturer, "rows": rows})
    context = {
        "semesters": semesters, "faculties": faculties, "selected_semester": semester,
        "selected_faculty": faculty, "semester_id": semester_id, "faculty_id": faculty_id,
        "lecturer_id": lecturer_id, "lecturers": Lecturer.objects.filter(department__faculty=faculty).order_by("name")
        if faculty else Lecturer.objects.none(),
        "week": week, "weeks": range(1, semester.week_count + 1) if semester else [],
        "public_demo_count": public_demo_count,
        "days": DAYS, "page": page, "timetable": timetable, "errors": errors,
        "query_prefix": urlencode({"semester": semester_id, "faculty": faculty_id,
                                   "lecturer": lecturer_id, "week": week}),
    }
    return render(request, "school/faculty_timetable.html", context, status=400 if errors else 200)
