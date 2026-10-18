"""Independent read-only audit of persisted synthetic benchmark schedules.

Reconstructs demands from workbooks and checks the preference snapshot, hard
constraints, shared soft score and fingerprint. Never invokes a solver.
"""
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def audit_saved_report(path, report, pack, input_root=None):
    """Django must be initialized before calling; databases are opened read-only."""
    from django.db import connections
    from django.core.files.uploadedfile import SimpleUploadedFile
    from school.auto_schedule import _prepare_inputs, read_auto_workbook
    from school.models import (AlgorithmRun, CourseGroup, Lecturer, LecturerPreference,
                               Room, ScheduleEntry, TeachingQualification)
    from school.quality_search import pending_solution, solution_fingerprint
    from school.soft_score import SoftScorer
    from school.solution_audit import audit_solution

    path = Path(path).resolve()
    database = path.with_suffix(".sqlite3")
    require(database.is_file(), f"Missing database: {database}")
    before = digest(database)
    connections.close_all()
    connection = connections["default"]
    connection.settings_dict.update(NAME=database.as_uri() + "?mode=ro", OPTIONS={"uri": True})
    started = perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA query_only = ON")
        require(AlgorithmRun.objects.count() == 1, "Expected one run in an isolated database")
        run = AlgorithmRun.objects.select_related("semester").get(pk=report["run_id"])
        require(run.status == report["status"] and run.objective == report["objective_after"], "Run metadata differs")
        if "objective_version" in report:
            require(run.objective_version == report["objective_version"], "Objective version differs")
        if "quality_snapshot" in report:
            require(run.quality_snapshot == report["quality_snapshot"], "Quality snapshot differs")
        require(run.optimization_trials == report["optimization_trials"], "Trial log differs")
        semester = run.semester
        folder = Path(input_root or ROOT / "samples/sgu_15_khoa_soft") / pack
        parsed = {}
        for kind, expected in report["workbook_sha256"].items():
            workbook = folder / f"{kind}.xlsx"
            require(digest(workbook) == expected, f"Workbook hash differs: {workbook}")
            parsed[kind] = read_auto_workbook(SimpleUploadedFile(workbook.name, workbook.read_bytes()), kind)
        profile_path = folder / "experiment.json"
        require(digest(profile_path) == report["experiment_sha256"], "Profile hash differs")
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        demands, room_blocks, teacher_blocks = _prepare_inputs(semester, parsed)
        groups = {(g.course.code, g.group, g.lab_group or ""): g for g in
                  CourseGroup.objects.filter(semester=semester).select_related("course").prefetch_related("cohort_links")}
        for demand in demands:
            demand["group"] = groups[demand["key"]]
        room_codes = {r["ma_phong"] for r in parsed["rooms"]["PhongHoc"]}
        teacher_codes = {r["ma_vien_chuc"] for r in parsed["lecturers"]["GiangVien"]}
        rooms = {r.code: r for r in Room.objects.filter(code__in=room_codes)}
        teachers = {t.employee_code: t for t in Lecturer.objects.filter(employee_code__in=teacher_codes)}
        pairs = {(r["ma_vien_chuc"], r["ma_mon_hoc"]) for r in parsed["lecturers"]["GiangVienHocPhan"]}
        priorities = {(q.lecturer.employee_code, q.course.code): q.priority for q in
                      TeachingQualification.objects.select_related("lecturer", "course")
                      if (q.lecturer.employee_code, q.course.code) in pairs}
        require(priorities == {(r["employee_code"], r["course_code"]): r["priority"]
                               for r in profile["qualification_priorities"]}, "Qualification priorities differ")
        preferences = [LecturerPreference(semester=semester, lecturer_id=p["lecturer_id"],
                       kind=p["kind"], day=p["day"], time_block=p["time_block"], priority=p["priority"])
                       for p in run.preferences_snapshot]
        expected_prefs = {(r["employee_code"], r["kind"], r["day"], r["time_block"], r["priority"])
                          for r in profile["preferences"]}
        require(len(preferences) == len(expected_prefs) and
                {(p["employee_code"], p["kind"], p["day"], p["time_block"], p["priority"])
                 for p in run.preferences_snapshot} == expected_prefs, "Preference snapshot differs")
        entries = ScheduleEntry.objects.filter(algorithm_run=run)
        require(len(demands) == report["expected_sessions"], "Demand count differs")
        require(entries.count() == run.entry_count == report["scheduled_sessions"], "Entry count differs")
        if report["feasible"]:
            require(run.status in ("HEURISTIC", "FEASIBLE", "OPTIMAL"), "Invalid feasible status")
            result = pending_solution(semester, demands)
            require(result is not None and len(result) == entries.count(), "Saved schedule does not exactly cover demands")
            audit_solution(semester, demands, result, rooms, teachers, room_blocks,
                           teacher_blocks, pairs, preferences=preferences)
            score = SoftScorer(semester, teachers, pairs, preferences,
                               quality_snapshot=run.quality_snapshot or {"version": "soft_v1", "weight": 0}).score(result)
            fingerprint = solution_fingerprint(result)
            require(score == report["objective_after"], "Recomputed score differs")
            require(fingerprint == report["selected_fingerprint"], "Saved fingerprint differs")
            require(report["hard_penalty"] == 0, "Invalid hard penalty")
            outcome = {"audit": "PASS", "sessions": len(result), "hard_penalty": 0,
                       "recomputed_soft_penalty": score, "fingerprint": fingerprint}
        else:
            require(not entries.exists() and report["objective_after"] is None
                    and report["hard_penalty"] is None, "Failed run contains a schedule")
            outcome = {"audit": "NO_SOLUTION", "sessions": 0, "hard_penalty": None,
                       "recomputed_soft_penalty": None}
    finally:
        connections.close_all()
    require(digest(database) == before, "Audit changed database")
    outcome.update(database_unchanged=True, seconds=round(perf_counter() - started, 6), report=str(path))
    return outcome
