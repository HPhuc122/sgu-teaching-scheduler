"""Adaptive GD fairness, telemetry, audited fallback and frozen baseline checks."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from .great_deluge import improve
from .quality_search import solution_fingerprint
from .schedule_queue import enqueue_schedule, process_next_run
from .sample_data import synthetic_rows, workbook_bytes
from .search_budget import SearchBudgetExpired, extra_gd_budget
from .solution_audit import audit_solution
from .test_quality_search import QualityFixture


class GreatDelugeBudgetTests(QualityFixture):
    def run_gd(self, initial=None, **kwargs):
        return improve(self.semester, initial or self.solution(6), self.room_map, self.teacher_map,
                       [], [], self.pairs, scoring=self.scoring, preferences=self.preferences, **kwargs)

    def test_instrumented_baseline_matches_frozen_algorithm(self):
        snapshot = Path(settings.BASE_DIR).parent / "analysis/baselines/great_deluge_3_1_2.py"
        spec = importlib.util.spec_from_file_location("school._frozen_gd", snapshot)
        frozen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frozen)
        args = (self.semester, self.solution(6), self.room_map, self.teacher_map, [], [], self.pairs)
        before = frozen.improve(*args, scoring=self.scoring, seed=42, time_limit=5)
        stats = {}
        after = improve(*args, scoring=self.scoring, seed=42, time_limit=5, telemetry=stats)
        self.assertEqual(before[1:], after[1:])
        self.assertEqual(solution_fingerprint(before[0]), solution_fingerprint(after[0]))
        self.assertEqual(stats["iterations"], 3000)
        self.assertEqual(stats["stop_reason"], "ITERATION_LIMIT")

    def test_real_gd_counters_are_consistent_and_result_passes_audit(self):
        stats = {}
        result, before, after = self.run_gd(telemetry=stats, seed=42)
        self.assertLess(after, before)
        self.assertEqual(stats["score_before"], before)
        self.assertEqual(stats["score_after"], after)
        self.assertGreater(stats["score_improvements"], 0)
        self.assertLessEqual(stats["score_improvements"], stats["accepted_moves"])
        self.assertLessEqual(stats["accepted_moves"], stats["valid_moves"])
        self.assertLessEqual(stats["valid_moves"], stats["proposals"])
        self.assertLessEqual(stats["proposals"], stats["iterations"])
        audit_solution(self.semester, [self.demand], result, self.room_map,
                       self.teacher_map, [], [], self.pairs, preferences=self.preferences)

    def test_stagnation_stops_at_limit_without_discarding_best(self):
        stats = {}
        initial = self.solution()
        result = self.run_gd(initial, telemetry=stats, max_iterations=1000, stagnation_limit=20)
        self.assertEqual(result[1:], (1, 1))
        self.assertEqual(stats["iterations"], 20)
        self.assertEqual(stats["score_improvements"], 0)
        self.assertEqual(stats["stop_reason"], "STAGNATION")
        self.assertEqual(solution_fingerprint(result[0]), solution_fingerprint(initial))

    def test_expired_gd_time_returns_input_and_records_zero_iterations(self):
        stats = {}
        result = self.run_gd(telemetry=stats, time_limit=0)
        self.assertEqual(result[1:], (9, 9))
        self.assertEqual(stats["iterations"], 0)
        self.assertEqual(stats["stop_reason"], "TIME_LIMIT")

    def test_extra_budget_shares_time_and_protects_final_audit(self):
        self.assertEqual(extra_gd_budget(0, 3.5, eligible_starts=3, path_seconds=2,
                                         audit_reserve=0.5, min_seconds=0.1), 1)
        self.assertEqual(extra_gd_budget(3, 3.5, eligible_starts=1, path_seconds=2,
                                         audit_reserve=0.5, min_seconds=0.1), 0)

    @override_settings(QUALITY_GD_EXTRA_PATHS=9, QUALITY_GD_STALE_ROUNDS=2)
    def test_all_starts_get_first_gd_before_fair_extra_rounds_and_stagnation_stop(self):
        events = []

        def generate(*args, seed, **kwargs):
            events.append(("start", seed))
            return self.answer(self.solution(6, day=seed - 40))

        def gd(semester, initial, *args, max_iterations, seed, scoring, **kwargs):
            events.append(("initial" if max_iterations == 3000 else "extra", seed))
            score = scoring.score(initial)
            return initial, score, score

        with (patch("school.auto_schedule.solve", side_effect=generate) as generator,
              patch("school.quality_search.improve", side_effect=gd)):
            result = self.search(gd_policy="adaptive")
        generator.assert_called()
        self.assertEqual(generator.call_count, 3)
        self.assertEqual(events[:6], [("start", 42), ("initial", 42), ("start", 43),
                                      ("initial", 43), ("start", 44), ("initial", 44)])
        self.assertEqual(events[6:], [("extra", seed) for seed in range(45, 51)])
        for trial in result[4]:
            self.assertEqual(trial["extra_paths"], 2)
            self.assertEqual(trial["extra_search_stop_reason"], "NO_USEFUL_IMPROVEMENT")
            self.assertEqual([p["anchor"] for p in trial["paths"]], ["S0", "BEST", "S0"])

    @override_settings(QUALITY_GD_EXTRA_PATHS=3)
    def test_extra_improvement_wins_and_later_worse_paths_cannot_overwrite_it(self):
        low, high = self.solution(), self.solution(6)

        def gd(semester, initial, *args, seed, scoring, **kwargs):
            return (low, scoring.score(initial), 1) if seed == 43 else self.unchanged(
                semester, initial, *args, scoring=scoring, **kwargs)

        with (patch("school.auto_schedule.solve", return_value=self.answer(high)),
              patch("school.quality_search.improve", side_effect=gd)):
            result = self.search(gd_policy="adaptive", max_starts=1)
        self.assertEqual(result[3], 1)
        self.assertEqual(result[2], 9)
        self.assertEqual(solution_fingerprint(result[0]), solution_fingerprint(low))
        self.assertEqual(result[4][0]["score_after"], 1)
        paths = result[4][0]["paths"]
        self.assertEqual([p["anchor"] for p in paths], ["S0", "BEST", "S0", "BEST"])
        self.assertEqual([p["score_before"] for p in paths[1:]], [9, 9, 1])

    @override_settings(QUALITY_GD_EXTRA_PATHS=1)
    def test_hard_invalid_extra_cannot_displace_audited_initial(self):
        high = self.solution(6)
        with (patch("school.auto_schedule.solve", return_value=self.answer(high)),
              patch("school.quality_search.improve", side_effect=[(high, 9, 9),
                     (self.solution(day=8), 9, 1)])):
            result = self.search(gd_policy="adaptive", max_starts=1)
        self.assertEqual(result[3], 9)
        path = result[4][0]["paths"][-1]
        self.assertFalse(path["audit_passed"])
        self.assertEqual(path["stop_reason"], "REJECTED")

    @override_settings(QUALITY_GD_EXTRA_PATHS=1)
    def test_extra_runtime_error_or_timeout_keeps_feasible_best(self):
        high = self.solution(6)
        for error in (RuntimeError("GD failed"), SearchBudgetExpired()):
            with (patch("school.auto_schedule.solve", return_value=self.answer(high)),
                  patch("school.quality_search.improve", side_effect=[(high, 9, 9), error])):
                result = self.search(gd_policy="adaptive", max_starts=1)
            self.assertEqual(result[3], 9)
            self.assertEqual(result[4][0]["paths"][-1]["stop_reason"], "REJECTED")

    def test_no_extra_time_keeps_best_without_starting_additional_trajectory(self):
        high = self.solution(6)
        with (patch("school.auto_schedule.solve", return_value=self.answer(high)),
              patch("school.quality_search.improve", side_effect=self.unchanged) as gd,
              patch("school.quality_search.extra_gd_budget", return_value=0)):
            result = self.search(gd_policy="adaptive", max_starts=1)
        gd.assert_called_once()
        self.assertEqual(result[3], 9)
        self.assertEqual(result[4][0]["extra_search_stop_reason"], "BUDGET_EXHAUSTED")

    @override_settings(QUALITY_AUDIT_RESERVE_SECONDS=0.8, QUALITY_GD_EXTRA_PATHS=1)
    def test_completion_reserve_prevents_extra_path_and_retains_audited_best(self):
        high = self.solution(6)
        with (patch("school.auto_schedule.solve", return_value=self.answer(high)),
              patch("school.quality_search.improve", side_effect=self.unchanged) as gd,
              patch("school.quality_search.monotonic", return_value=100),
              patch("school.quality_search.extra_gd_budget", wraps=extra_gd_budget) as budget):
            result = self.search(gd_policy="adaptive", max_starts=1, deadline=100.7)
        gd.assert_called_once()
        self.assertEqual(budget.call_args.kwargs["audit_reserve"], 0.8)
        self.assertEqual(result[3], 9)
        self.assertTrue(result[4][0]["selected"])
        self.assertEqual(result[4][0]["extra_search_stop_reason"], "BUDGET_EXHAUSTED")

    @override_settings(QUALITY_GD_EXTRA_PATHS=1)
    def test_final_audit_rejection_of_extra_falls_back_to_valid_initial(self):
        low, high = self.solution(), self.solution(6)
        counts = 0

        def audit(*args, **kwargs):
            nonlocal counts
            if solution_fingerprint(args[2]) == solution_fingerprint(low):
                counts += 1
                if counts >= 2:
                    raise ValueError("Rejected at final selection")
            return audit_solution(*args, **kwargs)

        with (patch("school.auto_schedule.solve", return_value=self.answer(high)),
              patch("school.quality_search.improve", side_effect=[(high, 9, 9), (low, 9, 1)]),
              patch("school.quality_search.audit_solution", side_effect=audit)):
            result = self.search(gd_policy="adaptive", max_starts=1)
        self.assertEqual(result[3], 9)
        self.assertTrue(result[4][0]["selection_rejections"])

    @override_settings(QUALITY_SEARCH_BUDGET_SECONDS=5, QUALITY_GD_EXTRA_PATHS=1)
    def test_real_queue_defaults_to_greedy_first_budget_aware_and_adaptive_gd(self):
        actor = get_user_model().objects.create_superuser("gd_budget_admin")
        rows = synthetic_rows(sessions=3, semester_name=self.semester.name, seed=7)
        files = {kind: SimpleUploadedFile(f"{kind}.xlsx", workbook_bytes(kind, data))
                 for kind, data in rows.items()}
        queued = enqueue_schedule(self.semester.pk, files, actor)
        run = process_next_run()
        self.assertEqual(run.pk, queued.pk)
        self.assertIn(run.status, ("HEURISTIC", "FEASIBLE", "OPTIMAL"))
        starts = [t for t in run.optimization_trials if t["kind"] == "start"]
        self.assertLessEqual(len(starts), 3)
        self.assertTrue(starts)
        for trial in starts:
            self.assertEqual(trial["generation"]["policy"], "greedy_first")
            self.assertEqual(trial["generation"]["cp_policy"], "budget_aware")
            self.assertEqual(trial["gd_policy"], "adaptive")
        paths = [p for t in starts for p in t.get("paths", [])]
        self.assertTrue(paths)
        self.assertTrue(all("iterations" in p and p["stop_reason"] for p in paths))
