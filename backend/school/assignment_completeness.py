"""Compare persisted session requests with the current semester timetable."""

from collections import defaultdict
from django.db.models import Q

from .models import AlgorithmRun, CourseGroup, Department, ScheduleEntry
from .preference_checks import day_off_violations


def assignment_completeness(semester, departments=None, faculty=None):
    if faculty is not None:
        faculty_departments = Department.objects.filter(faculty=faculty)
        if departments is not None:
            faculty_departments = faculty_departments.filter(pk__in=departments)
        departments = faculty_departments
    group_query = CourseGroup.objects.filter(semester=semester)
    if departments is not None:
        group_query = group_query.filter(
            Q(course__department__in=departments) |
            Q(scheduleentry__lecturer__department__in=departments)
        ).distinct()
    groups = list(group_query
                  .select_related("course").order_by("course__code", "group", "lab_group"))
    group_ids = {group.pk for group in groups}
    latest = {}
    runs = AlgorithmRun.objects.filter(
        semester=semester, status__in=("FEASIBLE", "OPTIMAL", "HEURISTIC")
    ).order_by("-pk")
    for run in runs:
        for item in run.demand_snapshot:
            group_id = item["group_id"]
            if group_id not in group_ids:
                continue
            if group_id not in latest:
                latest[group_id] = (run.pk, [])
            if latest[group_id][0] == run.pk:
                latest[group_id][1].append(item)

    entries_by_key = defaultdict(list)
    pending_entries = []
    entries = (ScheduleEntry.objects.filter(group_id__in=group_ids)
               .select_related("group__course", "lecturer")
               .order_by("pk"))
    visible_ids = None
    if departments is not None:
        visible_ids = set(entries.filter(
            Q(lecturer__department__in=departments) |
            Q(lecturer__isnull=True, group__course__department__in=departments)
        ).values_list("pk", flat=True))
    for entry in entries:
        if entry.request_code:
            entries_by_key[(entry.group_id, entry.request_code)].append(entry)
        if entry.status == "ChoDuyet" and (visible_ids is None or entry.pk in visible_ids):
            pending_entries.append(entry)

    required = []
    counts = {"approved": 0, "pending": 0, "missing": 0, "duplicate": 0}
    for group_id, (run_id, items) in latest.items():
        for item in items:
            matches = entries_by_key[(group_id, item["code"])]
            # A session assigned wholly to another unit is outside this report.
            if matches and visible_ids is not None and not any(e.pk in visible_ids for e in matches):
                continue
            if not matches:
                status = "missing"
            elif len(matches) > 1:
                status = "duplicate"
            elif matches[0].status == "DaDuyet":
                status = "approved"
            else:
                status = "pending"
            counts[status] += 1
            required.append({"course_code": item["course_code"], "group": item["group"],
                             "lab_group": item["lab_group"], "code": item["code"],
                             "excel_row": item["excel_row"], "run_id": run_id,
                             "status": status, "entries": [e for e in matches
                             if visible_ids is None or e.pk in visible_ids]})
    unknown_groups = [group for group in groups if group.pk not in latest]
    issues = [item for item in required if item["status"] != "approved"]
    hard_conflicts = day_off_violations(semester.pk, [e for e in entries
                         if visible_ids is None or e.pk in visible_ids])
    return {
        "expected": len(required), "counts": counts, "issues": issues,
        "unknown_groups": unknown_groups, "pending_entries": pending_entries,
        "ready": bool(required and not issues and not unknown_groups and not pending_entries and not hard_conflicts),
        "hard_conflicts": hard_conflicts,
        "scope_label": (f"Phạm vi đơn vị được phân quyền · {faculty.name}" if faculty is not None
                        else "Toàn học kỳ" if departments is None else "Phạm vi đơn vị được phân quyền"),
    }
