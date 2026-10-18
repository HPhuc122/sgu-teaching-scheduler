"""Run the three-file workflow in an explicitly isolated SQLite database."""

import json
import os
import platform
from functools import partial
from hashlib import sha256
from math import isfinite
from collections import defaultdict
from datetime import date, time
from io import BytesIO
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import django
import ortools
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test.utils import override_settings
from openpyxl import load_workbook

from school.assignment_export import approved_assignments, assignment_workbook_bytes
from school.auto_schedule import (AUTO_SHEETS, _create_catalog, _prepare_inputs,
                                  approve_algorithm_run, read_auto_workbook, run_from_workbooks)
from school.models import AlgorithmRun, Faculty, Period, ScheduleEntry, Semester
from school.quality_experiment import apply_experiment, load_experiment
from school.quality_search import search_quality
from school.schedule_queue import enqueue_schedule, process_next_run
from school.search_budget import load_cp_observations


def assert_no_conflicts(entries):
    occupied = defaultdict(set)
    for entry in entries:
        cohorts = {link.cohort_id for link in entry.group.cohort_links.all()}
        resources = [("group", entry.group_id), ("room", entry.room_id),
                     ("lecturer", entry.lecturer_id)]
        resources += [("cohort", cohort_id) for cohort_id in cohorts]
        for week in (item.week for item in entry.schedule_weeks.all()):
            for period in range(entry.start_period_id, entry.start_period_id + entry.period_count):
                for kind, resource_id in resources:
                    if resource_id is None:
                        continue
                    key = kind, resource_id, week, entry.day, period
                    if key in occupied:
                        raise AssertionError(f"Trùng {kind}, tuần {week}, thứ {entry.day}, tiết {period}")
                    occupied[key].add(entry.pk)


class Command(BaseCommand):
    help = "Benchmark synthetic scheduling in a separate SQLite database only."

    def add_arguments(self, parser):
        parser.add_argument("--input-dir", required=True)
        parser.add_argument("--semester-name", required=True)
        parser.add_argument("--weeks", type=int, default=16)
        parser.add_argument("--approve", action="store_true")
        parser.add_argument("--expect-status", choices=("OPTIMAL", "FEASIBLE", "HEURISTIC",
                                                        "INFEASIBLE", "UNKNOWN", "ERROR"))
        parser.add_argument("--report", required=True)
        parser.add_argument("--strategy", choices=("legacy", "single", "multi-start"), default="multi-start")
        parser.add_argument("--budget-seconds", type=float, default=settings.QUALITY_SEARCH_BUDGET_SECONDS)
        parser.add_argument("--search-seed", type=int, default=42)
        parser.add_argument("--cp-workers", type=int, default=4)
        parser.add_argument("--generation-policy", choices=("greedy-first", "model-first"),
                            default="greedy-first", help="Initial generation only; independent of strategy")
        parser.add_argument("--cp-policy", choices=("fixed-window", "budget-aware"), default="budget-aware")
        parser.add_argument("--cp-build-profile", default=settings.QUALITY_CP_BUILD_PROFILE)
        parser.add_argument("--gd-policy", choices=("baseline", "adaptive"), default="adaptive")
        parser.add_argument("--experiment-file", help="Opt-in JSON soft criteria for an isolated experiment")
        parser.add_argument("--workload-profile", help="Opt-in simulated quotas/factors; objective baseline must be kept separate")

    def handle(self, *args, **options):
        database = Path(settings.DATABASES["default"]["NAME"]).resolve()
        normal_database = (Path(settings.BASE_DIR) / "db.sqlite3").resolve()
        if (os.environ.get("UCTP_BENCHMARK") != "1" or
                settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3" or
                database == normal_database):
            raise CommandError("Benchmark chỉ chạy với UCTP_BENCHMARK=1 và UCTP_SQLITE_PATH riêng")
        if (not isfinite(options["budget_seconds"]) or options["budget_seconds"] <= 0
                or not 0 <= options["search_seed"] <= 2147483645 or options["cp_workers"] < 1):
            raise CommandError("Ngân sách, seed hoặc số worker không hợp lệ")
        if AlgorithmRun.objects.exists() or ScheduleEntry.objects.exists():
            raise CommandError("Cần database benchmark mới, chưa có lần chạy hoặc lịch")
        if Path(options["report"]).exists():
            raise CommandError("File báo cáo đã tồn tại; không ghi đè kết quả thực nghiệm")
        if options["cp_build_profile"]:
            try:
                load_cp_observations(options["cp_build_profile"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise CommandError(f"Invalid CP build profile: {exc}") from exc
        input_dir = Path(options["input_dir"])
        file_data = {}
        parsed = {}
        for kind in AUTO_SHEETS:
            path = input_dir / f"{kind}.xlsx"
            file_data[kind] = path.read_bytes()
            parsed[kind] = read_auto_workbook(SimpleUploadedFile(path.name, file_data[kind]), kind)
        expected = len(parsed["courses"]["BuoiHocYeuCau"])
        profile = None
        if options["experiment_file"]:
            try:
                profile = load_experiment(options["experiment_file"], file_data, parsed)
            except (ValueError, KeyError, TypeError) as exc:
                raise CommandError(str(exc)) from exc

        semester, _ = Semester.objects.get_or_create(
            name=options["semester_name"], defaults={
                "academic_year": "2026-2027", "start_date": date(2026, 9, 1),
                "end_date": date(2027, 1, 31), "week_count": options["weeks"],
            },
        )
        if semester.week_count != options["weeks"]:
            raise CommandError("Số tuần trong dữ liệu và học kỳ không khớp")
        for number in range(1, 14):
            Period.objects.get_or_create(pk=number, defaults={
                "block": "Sang" if number <= 5 else "Chieu",
                "start_time": time(7, 0), "end_time": time(7, 50),
            })
        setup_started = perf_counter()
        if profile is not None or options["workload_profile"]:
            with transaction.atomic():
                demands, room_blocks, teacher_blocks = _prepare_inputs(semester, parsed)
                _create_catalog(semester, parsed, demands, room_blocks, teacher_blocks)
                if profile is not None:
                    apply_experiment(semester, profile)
        setup_seconds = perf_counter() - setup_started
        actor, _ = get_user_model().objects.get_or_create(
            username="synthetic_benchmark_admin", defaults={"is_staff": True, "is_superuser": True},
        )
        if options["workload_profile"]:
            from school.models import Lecturer, TeachingQuota, WorkloadPolicy
            from decimal import Decimal
            workload_profile = json.loads(Path(options["workload_profile"]).read_text(encoding="utf-8"))
            if workload_profile.get("simulated") is not True or workload_profile.get("format_version") != 1:
                raise CommandError("Workload profile must explicitly describe simulated data, version 1")
            with transaction.atomic():
                policy = WorkloadPolicy(semester=semester, default_factor=Decimal(str(workload_profile["factor"])),
                                        balance_weight=workload_profile["weight"], note="Simulated workload experiment")
                policy.full_clean()
                policy.save()
                for teacher in Lecturer.objects.filter(employee_code__in=[r["ma_vien_chuc"] for r in parsed["lecturers"]["GiangVien"]]):
                    quota = TeachingQuota(semester=semester, lecturer=teacher,
                        target_units=Decimal(str(workload_profile.get("quotas", {}).get(teacher.employee_code, workload_profile["quota"]))))
                    quota.full_clean()
                    quota.save()
        files = {kind: SimpleUploadedFile(f"{kind}.xlsx", content)
                 for kind, content in file_data.items()}
        start = perf_counter()
        queued = enqueue_schedule(semester.pk, files, actor)
        enqueue_seconds = round(perf_counter() - start, 3)
        phase = {}

        def measured_search(*args, **kwargs):
            phase["search_started"] = perf_counter()
            try:
                return search_quality(*args, **kwargs)
            finally:
                phase["search_finished"] = perf_counter()

        def measured_run(*args, **kwargs):
            phase["run_started"] = perf_counter()
            try:
                return run_from_workbooks(*args, **kwargs)
            finally:
                # Includes the original atomic wrapper's commit/rollback.
                phase["run_finished"] = perf_counter()

        def measure_finalization_sql(execute, sql, params, many, context):
            in_tail = "search_finished" in phase and "run_finished" not in phase
            began = perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                if in_tail:
                    phase["tail_sql_seconds"] = phase.get("tail_sql_seconds", 0) + perf_counter() - began

        start = perf_counter()
        with (override_settings(QUALITY_SEARCH_BUDGET_SECONDS=options["budget_seconds"],
                                QUALITY_SEARCH_SEED=options["search_seed"],
                                QUALITY_CP_BUILD_PROFILE=options["cp_build_profile"],
                                QUALITY_SEARCH_MAX_STARTS=1 if options["strategy"] == "single" else 3),
              patch("school.auto_schedule.search_quality", partial(
                  measured_search, strategy="legacy" if options["strategy"] == "legacy" else "multi_start",
                  num_search_workers=options["cp_workers"],
                  generation_policy=options["generation_policy"].replace("-", "_"),
                  cp_policy=options["cp_policy"].replace("-", "_"),
                  gd_policy=options["gd_policy"],
              )),
              patch("school.schedule_queue.run_from_workbooks", measured_run),
              connection.execute_wrapper(measure_finalization_sql)):
            run = process_next_run()
        worker_elapsed = perf_counter() - start
        solve_seconds = round(worker_elapsed, 3)
        phase_seconds = {}
        if all(k in phase for k in ("run_started", "search_started", "search_finished", "run_finished")):
            phase_seconds = {
                "before_search_seconds": phase["search_started"] - phase["run_started"],
                "search_including_audits_seconds": phase["search_finished"] - phase["search_started"],
                "finalization_after_search_seconds": phase["run_finished"] - phase["search_finished"],
                # SQL execute only; transaction commit and Python work remain in the tail total.
                "finalization_sql_execute_seconds": phase.get("tail_sql_seconds", 0),
                "queue_and_worker_other_seconds": worker_elapsed - (phase["run_finished"] - phase["run_started"]),
            }
            phase_seconds = {k: round(v, 6) for k, v in phase_seconds.items()}
        if run is None or run.pk != queued.pk:
            raise CommandError("Worker không xử lý đúng lần chạy")
        entries = list(ScheduleEntry.objects.filter(algorithm_run=run)
                       .select_related("group", "lecturer__department", "room")
                       .prefetch_related("schedule_weeks", "group__cohort_links"))
        if run.status in ("FEASIBLE", "OPTIMAL", "HEURISTIC"):
            if len(entries) != expected or run.entry_count != expected:
                raise CommandError(f"Chỉ có {len(entries)}/{expected} buổi được xếp")
            assert_no_conflicts(entries)
        elif entries:
            raise CommandError("Lần chạy thất bại nhưng vẫn ghi lịch")

        approval_seconds = None
        export_rows = 0
        if options["approve"] and entries:
            start = perf_counter()
            approve_algorithm_run(run.pk, actor)
            approval_seconds = round(perf_counter() - start, 3)
            faculty_ids = {e.lecturer.department.faculty_id for e in entries}
            for faculty in Faculty.objects.filter(pk__in=faculty_ids):
                approved = approved_assignments(semester, faculty)
                content = assignment_workbook_bytes(semester, faculty, approved)
                book = load_workbook(BytesIO(content), read_only=True)
                export_rows += book["PhanCong"].max_row - 1
                book.close()
            if export_rows != expected:
                raise CommandError(f"Xuất Excel thiếu dòng: {export_rows}/{expected}")

        starts = [t for t in run.optimization_trials if t.get("kind") == "start"]
        initial_hashes = {t["initial_fingerprint"] for t in starts if "initial_fingerprint" in t}
        final_hashes = {t["fingerprint"] for t in starts if "fingerprint" in t}
        path_hashes = {p["fingerprint"] for t in starts for p in t.get("paths", []) if p.get("audit_passed")}
        feasible = bool(entries) and run.status in ("OPTIMAL", "FEASIBLE", "HEURISTIC")
        school_dir = Path(__file__).resolve().parents[2]
        result = {
            "semester": semester.name, "expected_sessions": expected,
            "run_id": run.pk, "status": run.status, "scheduled_sessions": len(entries),
            "objective_before": run.objective_before, "objective_after": run.objective,
            "objective_version": run.objective_version, "quality_snapshot": run.quality_snapshot,
            "workload_profile_sha256": sha256(Path(options["workload_profile"]).read_bytes()).hexdigest() if options["workload_profile"] else None,
            "optimization_trials": run.optimization_trials,
            "diagnostic_rows": len(run.diagnostics), "enqueue_seconds": enqueue_seconds,
            "worker_seconds": solve_seconds, "approval_seconds": approval_seconds,
            "export_rows": export_rows, "message": run.message,
            "strategy": options["strategy"], "budget_seconds": options["budget_seconds"],
            "search_seed": options["search_seed"], "cp_workers": options["cp_workers"],
            "generation_policy": options["generation_policy"],
            "cp_policy": options["cp_policy"],
            "gd_policy": options["gd_policy"],
            "gd_configuration": {
                "extra_paths": settings.QUALITY_GD_EXTRA_PATHS,
                "extra_path_seconds": settings.QUALITY_GD_EXTRA_PATH_SECONDS,
                "extra_iterations": settings.QUALITY_GD_EXTRA_ITERATIONS,
                "stagnation_iterations": settings.QUALITY_GD_STAGNATION_ITERATIONS,
                "stale_rounds": settings.QUALITY_GD_STALE_ROUNDS,
                "min_path_seconds": settings.QUALITY_GD_MIN_PATH_SECONDS,
            },
            "cp_build_profile_sha256": sha256(Path(options["cp_build_profile"]).read_bytes()).hexdigest()
                                       if options["cp_build_profile"] else None,
            "cp_budget_configuration": {
                "seconds_per_session": settings.QUALITY_CP_MODEL_SECONDS_PER_SESSION,
                "estimate_safety_factor": settings.QUALITY_CP_ESTIMATE_SAFETY_FACTOR,
                "gd_reserve_seconds": settings.QUALITY_GD_RESERVE_SECONDS,
                "audit_reserve_seconds": settings.QUALITY_AUDIT_RESERVE_SECONDS,
            },
            "cp_refinement_seconds": settings.QUALITY_CP_REFINEMENT_SECONDS,
            "cp_min_solve_seconds": settings.QUALITY_CP_MIN_SOLVE_SECONDS,
            "feasible": feasible, "hard_penalty": 0 if feasible else None,
            "distinct_initial_solutions": len(initial_hashes),
            "distinct_final_solutions": len(final_hashes), "distinct_gd_solutions": len(path_hashes),
            "selected_fingerprint": next((t.get("selected_fingerprint") for t in run.optimization_trials
                                          if t.get("selected")), None),
            "experiment_setup_seconds": round(setup_seconds, 6),
            "processing_seconds": round(enqueue_seconds + solve_seconds, 3),
            "phase_seconds": phase_seconds,
            "workbook_sha256": {k: sha256(v).hexdigest() for k, v in file_data.items()},
            "experiment_sha256": sha256(Path(options["experiment_file"]).read_bytes()).hexdigest()
                                  if profile is not None else None,
            "environment": {"python": platform.python_version(), "django": django.get_version(),
                            "ortools": ortools.__version__, "platform": platform.platform()},
            "algorithm_sha256": {name: sha256((school_dir / name).read_bytes()).hexdigest()
                                 for name in ("auto_schedule.py", "great_deluge.py", "quality_search.py",
                                              "soft_score.py", "workload.py", "search_budget.py", "solution_audit.py")},
        }
        report_path = Path(options["report"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(result, ensure_ascii=True))
        if options["expect_status"] and run.status != options["expect_status"]:
            raise CommandError(
                f"Trạng thái {run.status} khác kỳ vọng {options['expect_status']}; "
                f"xem {report_path} và chẩn đoán lần chạy #{run.pk}"
            )
        if options["approve"] and not entries:
            raise CommandError(
                f"Không có lịch để duyệt/xuất (trạng thái {run.status}); "
                f"xem {report_path} và chẩn đoán lần chạy #{run.pk}"
            )
