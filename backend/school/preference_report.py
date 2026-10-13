"""Explain how the currently saved timetable relates to lecturer preferences."""

from collections import defaultdict

from .models import LecturerPreference, ScheduleEntry
from .preference_checks import day_off_violations


def preference_report(semester, *, run_id=None, snapshot=None):
    """Count recurring sessions once, within one run or the full semester."""
    assignments = ScheduleEntry.objects.filter(group__semester=semester, lecturer__isnull=False)
    if run_id is not None:
        assignments = assignments.filter(algorithm_run_id=run_id)
    assignments = list(assignments.select_related(
        "start_period", "group__course", "lecturer"))
    by_lecturer = defaultdict(list)
    for entry in assignments:
        by_lecturer[entry.lecturer_id].append((entry.day, entry.start_period.block))

    rows = []
    totals = {"met": 0, "partial": 0, "unmet": 0, "unassessed": 0, "hard_unmet": 0}
    captured = {item["id"]: item for item in snapshot} if snapshot is not None else None
    snapshot_totals = {"unchanged": 0, "added": 0, "changed": 0, "removed": 0}
    current_ids = set()
    preferences = (LecturerPreference.objects.filter(semester=semester)
                   .select_related("lecturer").order_by("lecturer__name", "pk"))
    for pref in preferences:
        current_ids.add(pref.pk)
        sessions = by_lecturer[pref.lecturer_id]
        block_label = {"Sang": "sáng", "Chieu": "chiều", "Toi": "tối"}.get(
            pref.time_block, pref.time_block or "khung giờ chưa chọn")
        if pref.kind == "NgayNghi":
            rule = f"Không thể dạy thứ {pref.day}" if pref.day else "Ngày không thể dạy chưa chọn thứ"
            priority_label = "Ràng buộc cứng"
        elif pref.kind == "KhungGio":
            action = "Ưu tiên" if pref.priority <= 2 else "Ít ưu tiên" if pref.priority == 3 else "Tránh"
            day_text = f" thứ {pref.day}" if pref.day else " mọi thứ"
            rule = f"{action} buổi {block_label}{day_text}"
            priority_label = {1: "Rất ưu tiên", 2: "Ưu tiên", 3: "Không ưu tiên",
                              4: "Tránh"}.get(pref.priority, str(pref.priority))
        else:
            rule = f"Loại nguyện vọng chưa hỗ trợ: {pref.kind}"
            priority_label = str(pref.priority)
        result = {"preference": pref, "status": "unassessed", "status_label": "Chưa đánh giá",
                  "detail": "Giảng viên chưa có buổi dạy trong phạm vi đang xem.",
                  "rule": rule, "priority_label": priority_label}
        if captured is not None:
            old = captured.get(pref.pk)
            if old is None:
                origin = "added"
            elif any(old.get(key) != value for key, value in {
                    "lecturer_id": pref.lecturer_id, "kind": pref.kind, "day": pref.day,
                    "time_block": pref.time_block, "priority": pref.priority,
                    "note": pref.note,
            }.items()):
                origin = "changed"
            else:
                origin = "unchanged"
            result["snapshot_status"] = origin
            result["snapshot_label"] = {
                "added": "Gửi sau lần chạy", "changed": "Đã sửa sau lần chạy",
                "unchanged": "Có khi chạy, chưa sửa",
            }[origin]
            snapshot_totals[origin] += 1
        if sessions and pref.kind == "NgayNghi" and pref.day:
            scheduled = sum(day == pref.day for day, _ in sessions)
            result["status"] = "met" if scheduled == 0 else "unmet"
            result["status_label"] = "Đáp ứng" if scheduled == 0 else "Chưa đáp ứng"
            result["detail"] = f"{scheduled} buổi được xếp vào thứ {pref.day}."
        elif sessions and pref.kind == "KhungGio" and pref.time_block:
            relevant = [(day, block) for day, block in sessions
                        if pref.day is None or day == pref.day]
            if relevant:
                prefers_block = pref.priority <= 2
                matching = sum((block == pref.time_block) == prefers_block
                               for _, block in relevant)
                if matching == len(relevant):
                    result["status"], result["status_label"] = "met", "Đáp ứng"
                elif matching:
                    result["status"], result["status_label"] = "partial", "Đáp ứng một phần"
                else:
                    result["status"], result["status_label"] = "unmet", "Chưa đáp ứng"
                action = "đúng khung giờ ưu tiên" if prefers_block else "tránh được khung giờ"
                result["detail"] = f"{matching}/{len(relevant)} buổi {action}."
            else:
                result["detail"] = "Không có buổi dạy vào thứ được chọn trong phạm vi đang xem."
        elif sessions:
            result["detail"] = "Nguyện vọng thiếu thông tin hoặc có loại chưa được hỗ trợ."
        totals[result["status"]] += 1
        if pref.kind == "NgayNghi" and result["status"] == "unmet":
            totals["hard_unmet"] += 1
        rows.append(result)
    removed = ([item for item in snapshot if item["id"] not in current_ids]
               if snapshot is not None else [])
    snapshot_totals["removed"] = len(removed)
    return {"rows": rows, "totals": totals, "count": len(rows),
            "violations": day_off_violations(semester.pk, assignments),
            "snapshot_totals": snapshot_totals if captured is not None else None,
            "removed_preferences": removed}
