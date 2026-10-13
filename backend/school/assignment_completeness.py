"""Compare persisted session requests with the current semester timetable."""

from collections import defaultdict

from .models import AlgorithmRun, CourseGroup, ScheduleEntry


def assignment_completeness(semester):
    groups = list(CourseGroup.objects.filter(semester=semester)
                  .select_related("course").order_by("course__code", "group", "lab_group"))
    latest = {}
    runs = AlgorithmRun.objects.filter(
        semester=semester, status__in=("FEASIBLE", "OPTIMAL", "HEURISTIC")
    ).order_by("-pk")
    for run in runs:
        for item in run.demand_snapshot:
            group_id = item["group_id"]
            if group_id not in latest:
                latest[group_id] = (run.pk, [])
            if latest[group_id][0] == run.pk:
                latest[group_id][1].append(item)

    entries_by_key = defaultdict(list)
    pending_entries = []
    entries = (ScheduleEntry.objects.filter(group__semester=semester)
               .select_related("group__course", "lecturer")
               .order_by("pk"))
    for entry in entries:
        if entry.request_code:
            entries_by_key[(entry.group_id, entry.request_code)].append(entry)
        if entry.status == "ChoDuyet":
            pending_entries.append(entry)

    required = []
    counts = {"approved": 0, "pending": 0, "missing": 0, "duplicate": 0}
    for group_id, (run_id, items) in latest.items():
        for item in items:
            matches = entries_by_key[(group_id, item["code"])]
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
                             "status": status, "entries": matches})
    unknown_groups = [group for group in groups if group.pk not in latest]
    issues = [item for item in required if item["status"] != "approved"]
    return {
        "expected": len(required), "counts": counts, "issues": issues,
        "unknown_groups": unknown_groups, "pending_entries": pending_entries,
        "ready": bool(required and not issues and not unknown_groups and not pending_entries),
    }
