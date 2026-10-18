"""Behavioral coverage for independent starts, audited selection and deadlines."""

from datetime import date, time
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from ortools.sat.python import cp_model

from .auto_schedule import (AUTO_SHEETS, _build_cp_model, _greedy_seed,
                            read_auto_files, run_from_workbooks, solve)
from .models import (Building, Course, CourseGroup, Department, Faculty, Lecturer,
                     LecturerPreference, Period, Room, ScheduleEntry, ScheduleWeek,
                     Semester, TeachingQualification)
from .quality_search import search_quality, solution_fingerprint
from .quality_experiment import apply_experiment, load_experiment
from .sample_data import synthetic_rows, workbook_bytes
from .search_budget import SearchBudgetExpired, cp_budget, estimate_cp_build, trial_budget
from .soft_score import SoftScorer
from .solution_audit import audit_solution


class QualityFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        faculty = Faculty.objects.create(code="Q", name="Mô phỏng")
        department = Department.objects.create(code="Q", name="Mô phỏng", faculty=faculty)
        cls.course = Course.objects.create(code="Q01", name="Mô phỏng", credits=3, department=department)
        cls.teacher = Lecturer.objects.create(employee_code="Q01", name="A", department=department)
        cls.other = Lecturer.objects.create(employee_code="Q02", name="B", department=department)
        TeachingQualification.objects.create(lecturer=cls.teacher, course=cls.course, priority=2)
        TeachingQualification.objects.create(lecturer=cls.other, course=cls.course, priority=3)
        cls.semester = Semester.objects.create(name="Q", academic_year="2026-2027",
                                               start_date=date(2026, 9, 1), end_date=date(2027, 1, 31),
                                               week_count=16)
        cls.group = CourseGroup.objects.create(code="Q01.01", group="01", course=cls.course,
                                                semester=cls.semester, capacity=20)
        building = Building.objects.create(code="Q", name="Q")
        cls.room = Room.objects.create(code="Q01", name="Q01", building=building, capacity=30)
        for number in range(1, 14):
            Period.objects.create(pk=number, block="Sang" if number <= 5 else "Chieu",
                                  start_time=time(7), end_time=time(7, 50))
        cls.pref = LecturerPreference.objects.create(semester=cls.semester, lecturer=cls.teacher,
                                                       kind="KhungGio", time_block="Sang", priority=1)

    def setUp(self):
        self.demand = {"group": self.group, "code": "LT1", "count": 2, "line": 2,
                       "weeks": frozenset({1, 2}), "days": frozenset({2, 3, 4}), "room_type": ""}
        self.room_map = {self.room.code: self.room}
        self.teacher_map = {t.employee_code: t for t in (self.teacher, self.other)}
        self.pairs = {(t.employee_code, self.course.code) for t in (self.teacher, self.other)}
        self.preferences = list(LecturerPreference.objects.filter(semester=self.semester))
        self.scoring = SoftScorer(self.semester, self.teacher_map, self.pairs, self.preferences)

    def solution(self, start=1, teacher=None, day=2):
        return [(self.demand, day, start, self.room, teacher or self.teacher)]

    def answer(self, solution, status="HEURISTIC"):
        return solution, status, self.scoring.score(solution)

    def search(self, **kwargs):
        kwargs.setdefault("deadline", monotonic() + 30)
        # Existing tests cover the original one-GD-turn contract; adaptive
        # scheduling and the production default are exercised explicitly below.
        kwargs.setdefault("gd_policy", "baseline")
        return search_quality(self.semester, [self.demand], self.room_map, self.teacher_map,
                              [], [], self.pairs, preferences=self.preferences, **kwargs)

    @staticmethod
    def unchanged(semester, initial, *args, scoring, **kwargs):
        score = scoring.score(initial)
        return initial, score, score

class QualitySearchTests(QualityFixture):
    def test_three_real_seeded_constructions_are_distinct_and_reproducible(self):
        with (patch("school.auto_schedule.LARGE_RUN_SESSIONS", 0),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            first = self.search()
            second = self.search()
        for result in (first, second):
            self.assertEqual(len(result[4]), 3)
            self.assertEqual([t["seed"] for t in result[4]], [42, 43, 44])
            self.assertEqual(len({t["initial_fingerprint"] for t in result[4]}), 3)
            audit_solution(self.semester, [self.demand], result[0], self.room_map,
                           self.teacher_map, [], [], self.pairs, preferences=self.preferences)
        self.assertEqual([t["initial_fingerprint"] for t in first[4]],
                         [t["initial_fingerprint"] for t in second[4]])

    def test_duplicate_starts_are_logged_without_repeating_gd(self):
        initial = self.solution()
        with (patch("school.auto_schedule.solve", return_value=self.answer(initial)) as generator,
              patch("school.quality_search.improve", side_effect=self.unchanged) as gd):
            result = self.search()
        self.assertEqual(generator.call_count, 3)
        self.assertEqual(gd.call_count, 1)
        self.assertEqual([t["outcome"] for t in result[4]], ["VALID", "DUPLICATE", "DUPLICATE"])
        self.assertIs(result[0], initial)

    def test_one_failed_search_does_not_discard_other_valid_candidates(self):
        high, low = self.solution(6), self.solution()
        with (patch("school.auto_schedule.solve", side_effect=[self.answer(high),
                    (None, "UNKNOWN", None), self.answer(low)]) as generator,
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertIs(result[0], low)
        self.assertEqual(result[3], 1)
        self.assertEqual(result[4][1]["outcome"], "NO_SOLUTION")
        self.assertTrue(result[4][2]["selected"])
        self.assertEqual([c.kwargs["seed"] for c in generator.call_args_list], [42, 43, 44])
        self.assertEqual([c.kwargs["use_cp_sat"] for c in generator.call_args_list], [True, False, False])
        self.assertEqual(len({id(c.kwargs["scoring"]) for c in generator.call_args_list}), 1)

    def test_all_searches_fail_without_claiming_infeasible(self):
        with patch("school.auto_schedule.solve", return_value=(None, "UNKNOWN", None)) as generator:
            result = self.search()
        self.assertEqual(result[:4], (None, "UNKNOWN", None, None))
        self.assertEqual(generator.call_count, 3)
        self.assertFalse(any(t["selected"] for t in result[4]))
        self.assertFalse(ScheduleEntry.objects.exists())

    def test_solver_runtime_error_does_not_discard_other_starts(self):
        initial = self.solution()
        with (patch("school.auto_schedule.solve", side_effect=[RuntimeError("Lỗi lượt đầu"),
                    self.answer(initial), (None, "UNKNOWN", None)]),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertIs(result[0], initial)
        self.assertEqual(result[4][0]["outcome"], "SEARCH_ERROR")
        self.assertEqual(result[4][0]["status"], "ERROR")

    def test_all_solver_runtime_errors_are_reported_as_error(self):
        with patch("school.auto_schedule.solve", side_effect=RuntimeError("Bộ giải lỗi")):
            result = self.search()
        self.assertIsNone(result[0])
        self.assertEqual(result[1], "ERROR")
        self.assertEqual(len(result[4]), 3)

    def test_infeasibility_proof_stops_repeated_search(self):
        with patch("school.auto_schedule.solve", return_value=(None, "INFEASIBLE", None)) as generator:
            result = self.search()
        self.assertEqual(result[1], "INFEASIBLE")
        self.assertEqual(generator.call_count, 1)

    def test_low_scoring_hard_invalid_start_cannot_win(self):
        invalid, valid = self.solution(day=8), self.solution(6)
        with (patch("school.auto_schedule.solve", side_effect=[self.answer(invalid),
                    self.answer(valid), (None, "UNKNOWN", None)]),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertIs(result[0], valid)
        self.assertEqual(result[3], 9)
        self.assertEqual(result[4][0]["outcome"], "AUDIT_REJECTED")

    def test_invalid_improvement_retains_audited_start_then_selects_next_best(self):
        high, middle, invalid = self.solution(6), self.solution(1, self.other), self.solution(day=8)
        with (patch("school.auto_schedule.solve", side_effect=[self.answer(high),
                    self.answer(middle), (None, "UNKNOWN", None)]),
              patch("school.quality_search.improve", side_effect=[
                  (invalid, 9, 1), (middle, 2, 2)])):
            result = self.search()
        self.assertIs(result[0], middle)
        self.assertEqual(result[3], 2)
        self.assertEqual(result[4][0]["outcome"], "IMPROVEMENT_REJECTED")

    def test_later_worse_candidate_does_not_overwrite_best(self):
        best, worse = self.solution(), self.solution(6)
        with (patch("school.auto_schedule.solve", side_effect=[self.answer(best),
                    self.answer(worse), self.answer(self.solution(1, self.other))]),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertIs(result[0], best)
        self.assertEqual(result[3], 1)
        self.assertTrue(result[4][0]["selected"])

    def test_expired_budget_starts_no_solver(self):
        with patch("school.auto_schedule.solve") as generator:
            result = self.search(deadline=monotonic() - 1)
        generator.assert_not_called()
        self.assertIsNone(result[0])
        self.assertEqual(result[4][-1]["outcome"], "BUDGET_EXHAUSTED")

    def test_budget_exhausted_after_solution_keeps_it_without_more_search(self):
        clock = [0.0]
        initial = self.solution()

        def generate(*args, **kwargs):
            clock[0] = 11.0
            return self.answer(initial)

        with (patch("school.quality_search.monotonic", side_effect=lambda: clock[0]),
              patch("school.auto_schedule.solve", side_effect=generate) as generator,
              patch("school.quality_search.improve") as gd):
            result = self.search(deadline=10)
        generator.assert_called_once()
        gd.assert_not_called()
        self.assertIs(result[0], initial)
        self.assertEqual(result[4][-1]["outcome"], "BUDGET_EXHAUSTED")

    def test_generation_timeout_is_local_to_one_start(self):
        initial = self.solution()
        with (patch("school.auto_schedule.solve", side_effect=[SearchBudgetExpired,
                    self.answer(initial), (None, "UNKNOWN", None)]),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertIs(result[0], initial)
        self.assertEqual(result[4][0]["outcome"], "BUDGET_EXHAUSTED")

    def test_snapshot_is_shared_despite_database_preference_and_priority_changes(self):
        initial = self.solution(6)

        def generate(*args, scoring, preferences, **kwargs):
            LecturerPreference.objects.filter(pk=self.pref.pk).update(priority=4)
            TeachingQualification.objects.filter(lecturer=self.teacher).update(priority=5)
            self.assertEqual(scoring.score(initial), 9)
            self.assertEqual(preferences[0].priority, 1)
            return initial, "HEURISTIC", 9

        with (patch("school.auto_schedule.solve", side_effect=generate),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertEqual(result[3], 9)
        self.assertEqual(len(result[4]), 3)

    def test_heuristic_and_cp_timeout_score_same_snapshot(self):
        LecturerPreference.objects.filter(pk=self.pref.pk).update(priority=4)
        with patch("school.auto_schedule.cp_model.CpSolver.Solve", autospec=True,
                   return_value=cp_model.UNKNOWN) as cp:
            cp_result = solve(self.semester, [self.demand], self.room_map, self.teacher_map,
                              [], [], self.pairs, scoring=self.scoring, seed=73,
                              deadline=monotonic() + 5, cp_time_limit=2)
        solver = cp.call_args.args[0]
        self.assertEqual(solver.parameters.random_seed, 73)
        self.assertLessEqual(solver.parameters.max_time_in_seconds, 2)
        greedy_result = solve(self.semester, [self.demand], self.room_map, self.teacher_map,
                              [], [], self.pairs, scoring=self.scoring, use_cp_sat=False, seed=74)
        for solution, status, score in (cp_result, greedy_result):
            self.assertEqual(status, "HEURISTIC")
            self.assertEqual(score, self.scoring.score(solution))

    def test_greedy_enforces_deadline_inside_generation(self):
        with self.assertRaises(SearchBudgetExpired):
            _greedy_seed([self.demand], [], [], {}, {}, deadline=monotonic() - 1)

    def generate(self, **kwargs):
        kwargs.setdefault("deadline", monotonic() + 10)
        kwargs.setdefault("scoring", self.scoring)
        kwargs.setdefault("num_search_workers", 1)
        return solve(self.semester, [self.demand], self.room_map, self.teacher_map,
                     [], [], self.pairs, **kwargs)

    def test_greedy_is_audited_before_model_build_and_survives_build_timeout(self):
        events, metrics = [], {}

        def audit(*args, **kwargs):
            events.append("audit")
            return audit_solution(*args, **kwargs)

        def build(*args, **kwargs):
            events.append("model")
            raise SearchBudgetExpired

        with (patch("school.auto_schedule.audit_solution", side_effect=audit),
              patch("school.auto_schedule._build_cp_model", side_effect=build),
              patch("school.auto_schedule.cp_model.CpSolver.Solve") as cp):
            result = self.generate(telemetry=metrics)
        self.assertEqual(events, ["audit", "model"])
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["source"], "GREEDY")
        self.assertEqual(metrics["cp_status"], "NOT_CALLED")
        self.assertEqual(metrics["cp_skip_reason"], "MODEL_BUILD_TIMEOUT")
        self.assertFalse(metrics["cp_called"])
        cp.assert_not_called()
        audit_solution(self.semester, [self.demand], result[0], self.room_map,
                       self.teacher_map, [], [], self.pairs, preferences=self.preferences)

    def test_cp_unknown_keeps_valid_greedy_and_records_actual_stages(self):
        metrics = {}
        with patch("school.auto_schedule.cp_model.CpSolver.Solve", autospec=True,
                   return_value=cp_model.UNKNOWN) as cp:
            result = self.generate(telemetry=metrics, seed=73)
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(result[2], self.scoring.score(result[0]))
        self.assertEqual(metrics["cp_status"], "UNKNOWN")
        self.assertTrue(metrics["cp_called"])
        self.assertEqual(metrics["source"], "GREEDY")
        solver = cp.call_args.args[0]
        self.assertEqual(solver.parameters.random_seed, 73)
        self.assertLessEqual(solver.parameters.max_time_in_seconds, 5)
        for stage in ("preparation_seconds", "greedy_seconds", "cp_model_seconds",
                      "cp_solve_seconds", "validation_seconds"):
            self.assertGreaterEqual(metrics[stage], 0)
        self.assertGreater(metrics["greedy_seconds"], 0)
        self.assertGreater(metrics["cp_model_seconds"], 0)
        self.assertGreater(metrics["validation_seconds"], 0)

    def test_hint_build_timeout_keeps_already_audited_greedy(self):
        metrics = {}
        with (patch("school.auto_schedule.cp_model.CpModel.add_hint", side_effect=SearchBudgetExpired),
              patch("school.auto_schedule.cp_model.CpSolver.Solve") as cp):
            result = self.generate(telemetry=metrics)
        cp.assert_not_called()
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["source"], "GREEDY")
        self.assertEqual(metrics["cp_skip_reason"], "HINT_BUILD_TIMEOUT")
        self.assertEqual(metrics["cp_status"], "NOT_CALLED")

    def test_zero_penalty_greedy_skips_cp_sat_without_claiming_optimal(self):
        TeachingQualification.objects.filter(course=self.course).update(priority=1)
        LecturerPreference.objects.filter(semester=self.semester).delete()
        metrics = {}
        with patch("school.auto_schedule._build_cp_model") as build:
            result = self.generate(scoring=None, telemetry=metrics)
        build.assert_not_called()
        self.assertEqual(result[1:], ("HEURISTIC", 0))
        self.assertEqual(metrics["cp_skip_reason"], "ZERO_SOFT_PENALTY")

    def test_cp_infeasible_contradiction_does_not_discard_valid_greedy(self):
        metrics = {}
        with patch("school.auto_schedule.cp_model.CpSolver.Solve", return_value=cp_model.INFEASIBLE):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["cp_status"], "INFEASIBLE")
        self.assertEqual(metrics["source"], "GREEDY")
        self.assertIn("cp_warning", metrics)

    def test_real_cp_sat_rescues_failed_greedy(self):
        metrics = {}
        with patch("school.auto_schedule._greedy_seed", return_value=None):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1], "OPTIMAL")
        self.assertEqual(result[2], 1)
        self.assertEqual(metrics["greedy_status"], "NO_SOLUTION")
        self.assertEqual(metrics["source"], "CP_SAT")
        self.assertEqual(metrics["cp_status"], "OPTIMAL")
        audit_solution(self.semester, [self.demand], result[0], self.room_map,
                       self.teacher_map, [], [], self.pairs, preferences=self.preferences)

    def test_greedy_timeout_leaves_cp_rescue_available(self):
        metrics = {}
        with patch("school.auto_schedule._greedy_seed", side_effect=SearchBudgetExpired):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1], "OPTIMAL")
        self.assertEqual(metrics["greedy_status"], "TIMEOUT")
        self.assertEqual(metrics["source"], "CP_SAT")

    def test_no_seed_and_cp_unknown_does_not_claim_infeasibility(self):
        metrics = {}
        with (patch("school.auto_schedule._greedy_seed", return_value=None),
              patch("school.auto_schedule.cp_model.CpSolver.Solve", return_value=cp_model.UNKNOWN)):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result, (None, "UNKNOWN", None))
        self.assertEqual(metrics["source"], "NONE")
        self.assertEqual(metrics["cp_status"], "UNKNOWN")

    def test_no_seed_and_no_model_budget_is_unknown(self):
        metrics = {}
        with (patch("school.auto_schedule._greedy_seed", return_value=None),
              patch("school.auto_schedule._build_cp_model", side_effect=SearchBudgetExpired)):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result, (None, "UNKNOWN", None))
        self.assertEqual(metrics["cp_status"], "NOT_CALLED")

    def test_real_infeasible_model_has_no_valid_fallback(self):
        LecturerPreference.objects.filter(semester=self.semester).delete()
        for teacher in (self.teacher, self.other):
            for day in self.demand["days"]:
                LecturerPreference.objects.create(semester=self.semester, lecturer=teacher,
                                                   kind="NgayNghi", day=day)
        metrics = {}
        result = self.generate(scoring=None, telemetry=metrics)
        self.assertEqual(result, (None, "INFEASIBLE", None))
        self.assertEqual(metrics["greedy_status"], "NO_SOLUTION")
        self.assertEqual(metrics["cp_status"], "INFEASIBLE")

    def test_insufficient_cp_budget_keeps_greedy_without_building_model(self):
        metrics = {}
        with patch("school.auto_schedule._build_cp_model") as build:
            result = self.generate(deadline=monotonic() + 0.5, telemetry=metrics)
        build.assert_not_called()
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["cp_skip_reason"], "SKIPPED_BUDGET")
        self.assertEqual(metrics["cp_status"], "NOT_CALLED")

    def test_later_start_uses_greedy_without_building_model(self):
        metrics = {}
        with patch("school.auto_schedule._build_cp_model") as build:
            result = self.generate(use_cp_sat=False, telemetry=metrics)
        build.assert_not_called()
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["cp_skip_reason"], "LATER_START")

    def test_cp_worse_solution_cannot_replace_greedy(self):
        metrics = {}

        def worse_model(*args, **kwargs):
            model, choices = _build_cp_model(*args, **kwargs)
            teachers, flags = choices[0][4:]
            model.Add(flags[next(i for i, q in enumerate(teachers)
                                 if q.lecturer_id == self.other.pk)] == 1)
            return model, choices

        with (patch("school.auto_schedule._greedy_seed", return_value={0: (0, 0, 0)}),
              patch("school.auto_schedule._build_cp_model", side_effect=worse_model)):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[2], 1)
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["cp_score"], 2)
        self.assertEqual(metrics["source"], "GREEDY")

    def test_invalid_greedy_is_discarded_before_cp_rescue(self):
        metrics = {}
        invalid = [(self.demand, 8, 1, self.room, self.teacher)]
        with patch("school.auto_schedule._selected_result", return_value=invalid):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1], "OPTIMAL")
        self.assertEqual(metrics["greedy_status"], "AUDIT_REJECTED")
        self.assertEqual(metrics["source"], "CP_SAT")

    def test_rejected_cp_candidate_keeps_audited_greedy(self):
        metrics, calls = {}, []

        def audit(*args, **kwargs):
            calls.append(args[2])
            if len(calls) == 2:
                raise ValueError("CP candidate rejected")
            return audit_solution(*args, **kwargs)

        with patch("school.auto_schedule.audit_solution", side_effect=audit):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["source"], "GREEDY")
        self.assertEqual(metrics["cp_skip_reason"], "CP_CANDIDATE_REJECTED")

    def test_model_first_control_uses_same_seed_domains_and_shared_score(self):
        fingerprints = []
        for policy in ("model_first", "greedy_first"):
            metrics = {}
            with patch("school.auto_schedule.cp_model.CpSolver.Solve", return_value=cp_model.UNKNOWN):
                result = self.generate(generation_policy=policy, seed=73, telemetry=metrics)
            fingerprints.append(solution_fingerprint(result[0]))
            self.assertEqual(result[2], self.scoring.score(result[0]))
            self.assertEqual(metrics["policy"], policy)
        self.assertEqual(fingerprints[0], fingerprints[1])

    def test_generation_details_are_retained_in_quality_trial_log(self):
        with patch("school.quality_search.improve", side_effect=self.unchanged):
            result = self.search(max_starts=1)
        metrics = result[4][0]["generation"]
        self.assertEqual(metrics["policy"], "greedy_first")
        self.assertEqual(metrics["source"], "CP_SAT")
        self.assertEqual(metrics["cp_status"], "OPTIMAL")
        self.assertEqual(metrics["cp_score"], result[3])

    def test_observed_cost_skips_model_before_build_when_valid_greedy_exists(self):
        metrics = {}
        observation = {"sessions": 1, "seconds": 20, "model_complete": False}
        with patch("school.auto_schedule._build_cp_model") as build:
            result = self.generate(telemetry=metrics, cp_observations=[observation])
        build.assert_not_called()
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["cp_decision"], "SKIPPED_BUDGET")
        self.assertEqual(metrics["cp_status"], "NOT_CALLED")
        self.assertEqual(metrics["cp_model_seconds"], 0)
        self.assertEqual(metrics["cp_estimate"]["censored_observations"], 1)

    def test_sufficient_budget_admits_real_cp_and_accepts_strict_improvement(self):
        metrics = {}
        observation = {"sessions": 1, "seconds": 6, "model_complete": True}
        with patch("school.auto_schedule._greedy_seed", return_value={0: (4, 0, 0)}):
            result = self.generate(deadline=monotonic() + 20, telemetry=metrics,
                                   cp_observations=[observation])
        self.assertEqual(result[1:], ("OPTIMAL", 1))
        self.assertEqual(metrics["greedy_score"], 9)
        self.assertTrue(metrics["cp_called"])
        self.assertEqual(metrics["cp_decision"], "RUN_IMPROVEMENT")
        self.assertEqual(metrics["source"], "CP_SAT")
        self.assertGreater(metrics["cp_allocated_seconds"], 5)

    def test_equal_cp_score_keeps_the_audited_greedy_assignment(self):
        metrics = {}
        with patch("school.auto_schedule._greedy_seed", return_value={0: (0, 0, 0)}):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1:], ("HEURISTIC", 1))
        self.assertEqual(metrics["cp_status"], "OPTIMAL")
        self.assertEqual(metrics["source"], "GREEDY")
        self.assertEqual(metrics["cp_skip_reason"], "CP_NOT_BETTER_THAN_GREEDY")

    def test_no_greedy_allows_best_effort_cp_rescue_despite_cost_estimate(self):
        metrics = {}
        with patch("school.auto_schedule._greedy_seed", return_value=None):
            result = self.generate(telemetry=metrics,
                                   cp_observations=[{"sessions": 1, "seconds": 20, "model_complete": False}])
        self.assertEqual(result[1:], ("OPTIMAL", 1))
        self.assertEqual(metrics["cp_decision"], "RUN_RESCUE")
        self.assertTrue(metrics["cp_estimate_exceeds_budget"])
        self.assertEqual(metrics["source"], "CP_SAT")

    def test_no_greedy_and_no_minimum_solve_time_returns_unknown_without_building(self):
        metrics = {}
        with (patch("school.auto_schedule._greedy_seed", return_value=None),
              patch("school.auto_schedule._build_cp_model") as build):
            result = self.generate(telemetry=metrics, deadline=monotonic() + 0.5)
        build.assert_not_called()
        self.assertEqual(result, (None, "UNKNOWN", None))
        self.assertEqual(metrics["cp_decision"], "SKIPPED_BUDGET")

    def test_fixed_window_control_still_attempts_build_with_same_observations(self):
        metrics = {}
        with patch("school.auto_schedule._build_cp_model", side_effect=SearchBudgetExpired) as build:
            result = self.generate(telemetry=metrics, cp_policy="fixed_window",
                                   cp_observations=[{"sessions": 1, "seconds": 20, "model_complete": False}])
        build.assert_called_once()
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["cp_decision"], "RUN_FIXED_WINDOW")
        self.assertEqual(metrics["cp_skip_reason"], "MODEL_BUILD_TIMEOUT")

    def test_cost_estimate_preserves_censored_lower_bounds_and_matches_size(self):
        observations = [{"sessions": 240, "seconds": 12, "model_complete": False},
                        {"sessions": 480, "seconds": 1, "model_complete": True}]
        estimate = estimate_cp_build(240, observations)
        self.assertEqual(estimate["seconds"], 15)
        self.assertEqual(estimate["observations"], 1)
        self.assertEqual(estimate["censored_observations"], 1)
        self.assertEqual(estimate_cp_build(1, observations)["source"], "CONFIGURED_PRIOR")

    def test_solver_interruption_keeps_valid_greedy_without_fabricating_unknown(self):
        metrics = {}
        with patch("school.auto_schedule.cp_model.CpSolver.Solve", side_effect=SearchBudgetExpired):
            result = self.generate(telemetry=metrics)
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(metrics["source"], "GREEDY")
        self.assertTrue(metrics["cp_called"])
        self.assertEqual(metrics["cp_status"], "INTERRUPTED")

    def test_trial_and_cp_reserves_are_separate_and_stay_within_start(self):
        stages = trial_budget(0, 15, gd_reserve=1, audit_reserve=0.5)
        self.assertLessEqual(stages["generation_deadline"], 15 - 1 - 0.5)
        plan = cp_budget(1, stages["generation_deadline"], has_seed=True,
                         estimate={"seconds": 1}, refinement_seconds=5,
                         min_solve_seconds=1, audit_reserve=0.5, cp_time_limit=30)
        self.assertLessEqual(plan["cp_deadline"], stages["generation_deadline"] - 0.5)
        self.assertEqual(plan["cp_deadline"] - plan["cp_build_deadline"], 1)
        self.assertLessEqual(stages["improvement_deadline"], 15 - 0.5)

    def test_released_generation_time_is_available_to_unchanged_gd_and_measured(self):
        with (patch("school.auto_schedule.solve", return_value=self.answer(self.solution(6))),
              patch("school.quality_search.improve", side_effect=self.unchanged) as gd):
            result = self.search(max_starts=1)
        gd.assert_called_once()
        self.assertEqual(gd.call_args.kwargs["max_iterations"], 3000)
        self.assertEqual(gd.call_args.kwargs["time_limit"], 5)
        record = result[4][0]
        self.assertEqual(record["gd_allocated_seconds"], 5)
        self.assertGreater(record["generation_unused_seconds"], 0)
        self.assertGreater(record["gd_available_after_generation_seconds"], 5)
        self.assertGreater(record["gd_unused_seconds"], 0)
        self.assertEqual(record["gd_calls"], 1)

    def test_existing_better_pending_schedule_is_preserved(self):
        initial = self.solution()
        entry = ScheduleEntry.objects.create(group=self.group, lecturer=self.teacher, room=self.room,
                                               day=2, start_period_id=1, period_count=2,
                                               source="ThuatToan", status="ChoDuyet", request_code="LT1")
        ScheduleWeek.objects.bulk_create([ScheduleWeek(entry=entry, week=w) for w in (1, 2)])
        with (patch("school.auto_schedule.solve", return_value=self.answer(self.solution(6))),
              patch("school.quality_search.improve", side_effect=self.unchanged)):
            result = self.search()
        self.assertEqual(solution_fingerprint(result[0]), solution_fingerprint(initial))
        self.assertEqual(result[3], 1)
        self.assertEqual(result[4][0]["kind"], "incumbent")
        self.assertTrue(result[4][0]["selected"])

    def test_one_optimal_audited_start_stops_early(self):
        initial = self.solution()
        with (patch("school.auto_schedule.solve", return_value=self.answer(initial, "OPTIMAL")) as generator,
              patch("school.quality_search.improve") as gd):
            result = self.search()
        generator.assert_called_once()
        gd.assert_not_called()
        self.assertEqual(result[1], "OPTIMAL")

    def test_legacy_control_has_one_construction_and_three_paths(self):
        with (patch("school.auto_schedule.solve", return_value=self.answer(self.solution(6))) as generator,
              patch("school.quality_search.improve", side_effect=self.unchanged) as gd):
            result = self.search(strategy="legacy")
        generator.assert_called_once()
        self.assertEqual(gd.call_count, 3)
        self.assertEqual(len(result[4][0]["paths"]), 3)

    def test_selection_audit_rejection_falls_back_to_next_ranked_candidate(self):
        low, middle, high = self.solution(), self.solution(1, self.other), self.solution(6)
        counts = {}

        def audit(*args, **kwargs):
            solution = args[2]
            fingerprint = solution_fingerprint(solution)
            counts[fingerprint] = counts.get(fingerprint, 0) + 1
            # Initial and post-GD audit pass; reject the best at final selection.
            if fingerprint == solution_fingerprint(low) and counts[fingerprint] >= 3:
                raise ValueError("Ứng viên bị loại khi chọn cuối")
            return audit_solution(*args, **kwargs)

        with (patch("school.auto_schedule.solve", side_effect=[self.answer(low), self.answer(middle),
                                                              self.answer(high)]),
              patch("school.quality_search.improve", side_effect=self.unchanged),
              patch("school.quality_search.audit_solution", side_effect=audit)):
            result = self.search()
        self.assertIs(result[0], middle)
        self.assertEqual(result[3], 2)
        self.assertTrue(result[4][0]["selection_rejections"])
        self.assertTrue(result[4][1]["selected"])

    def test_false_improvement_score_is_rejected(self):
        initial = self.solution(6)
        with (patch("school.auto_schedule.solve", return_value=self.answer(initial)),
              patch("school.quality_search.improve", return_value=(self.solution(), 9, 0))):
            result = self.search()
        self.assertEqual(result[3], 9)
        self.assertEqual(result[4][0]["outcome"], "IMPROVEMENT_REJECTED")

    def test_more_than_three_starts_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "1 đến 3"):
            self.search(max_starts=4)

    def test_missing_period_configuration_remains_an_input_error(self):
        Period.objects.all().delete()
        with self.assertRaisesRegex(ValueError, "cấu hình tiết"):
            self.search()

    def test_zero_score_stops_early_without_claiming_optimal(self):
        TeachingQualification.objects.filter(lecturer=self.teacher).update(priority=1)
        initial = self.solution()
        with (patch("school.auto_schedule.solve", return_value=(initial, "HEURISTIC", 0)) as generator,
              patch("school.quality_search.improve") as gd):
            result = self.search()
        generator.assert_called_once()
        gd.assert_not_called()
        self.assertEqual(result[1], "HEURISTIC")
        self.assertEqual(result[3], 0)

    def uploaded_files(self):
        rows = synthetic_rows(sessions=3, semester_name=self.semester.name, seed=7)
        return {kind: SimpleUploadedFile(f"{kind}.xlsx", workbook_bytes(kind, data))
                for kind, data in rows.items()}

    def test_all_failed_starts_persist_diagnostics_without_any_schedule(self):
        actor = get_user_model().objects.create_superuser("quality_admin")
        with patch("school.auto_schedule.solve", return_value=(None, "UNKNOWN", None)):
            run = run_from_workbooks(self.semester.pk, self.uploaded_files(), actor)
        run.refresh_from_db()
        self.assertEqual(run.status, "UNKNOWN")
        self.assertEqual(len(run.optimization_trials), 3)
        self.assertTrue(run.diagnostics)
        self.assertEqual(run.entry_count, 0)
        self.assertFalse(ScheduleEntry.objects.exists())

    def test_rerun_retains_schedule_if_all_new_starts_fail(self):
        actor = get_user_model().objects.create_superuser("quality_admin")
        first = run_from_workbooks(self.semester.pk, self.uploaded_files(), actor)

        def rows(run):
            return list(run.entries.order_by("group_id", "request_code").values_list(
                "group_id", "request_code", "day", "start_period_id", "room_id", "lecturer_id"))

        original = rows(first)
        with patch("school.auto_schedule.solve", return_value=(None, "UNKNOWN", None)):
            second = run_from_workbooks(self.semester.pk, self.uploaded_files(), actor)
        self.assertEqual(rows(second), original)
        self.assertEqual(second.objective, first.objective)
        self.assertEqual(ScheduleEntry.objects.count(), 3)
        self.assertTrue(second.optimization_trials[0]["selected"])

    def test_experiment_profile_has_exact_coverage_and_rejects_changed_workbooks(self):
        files = self.uploaded_files()
        file_data = {k: f.read() for k, f in files.items()}
        for f in files.values():
            f.seek(0)
        parsed = read_auto_files(files)
        profile = {"format_version": 1, "simulated": True,
                   "workbook_sha256": {k: sha256(v).hexdigest() for k, v in file_data.items()},
                   "qualification_priorities": [
                       {"employee_code": r["ma_vien_chuc"], "course_code": r["ma_mon_hoc"], "priority": 3}
                       for r in parsed["lecturers"]["GiangVienHocPhan"]],
                   "preferences": [
                       {"employee_code": r["ma_vien_chuc"], "kind": "KhungGio", "day": None,
                        "time_block": "Chieu", "priority": 1}
                       for r in parsed["lecturers"]["GiangVien"]]}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            self.assertEqual(load_experiment(path, file_data, parsed), profile)
            with self.assertRaisesRegex(ValueError, "workbook"):
                load_experiment(path, dict(file_data, courses=b"changed"), parsed)
            profile["qualification_priorities"].append(profile["qualification_priorities"][0])
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "từng cặp"):
                load_experiment(path, file_data, parsed)

    def test_experiment_priorities_affect_score_without_changing_formula(self):
        LecturerPreference.objects.filter(semester=self.semester).delete()
        profile = {"qualification_priorities": [
            {"employee_code": self.teacher.employee_code, "course_code": self.course.code, "priority": 4}],
            "preferences": [{"employee_code": self.teacher.employee_code, "kind": "KhungGio",
                             "day": None, "time_block": "Chieu", "priority": 1}]}
        apply_experiment(self.semester, profile)
        scoring = SoftScorer(self.semester, self.teacher_map, self.pairs)
        self.assertEqual(scoring.score(self.solution()), 11)
        self.assertEqual(scoring.score(self.solution(6)), 3)

    def test_benchmark_reports_actual_quality_metrics_and_allows_sgu_faculty_export(self):
        data = synthetic_rows(sessions=3, semester_name="QUALITY BENCH", seed=8)
        # Use a non-TEST_ faculty code, as the SGU demonstration packs do.
        for kind, sheets in data.items():
            for name, rows in sheets.items():
                headers = AUTO_SHEETS[kind][name]
                if "ma_khoa" in headers:
                    column = headers.index("ma_khoa")
                    sheets[name] = [tuple(str(v).replace("TEST_", "DEMO_", 1) if i == column else v
                                          for i, v in enumerate(row)) for row in rows]
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            for kind, sheets in data.items():
                (folder / f"{kind}.xlsx").write_bytes(workbook_bytes(kind, sheets))
            from analysis.prepare_quality_experiments import build_profile
            profile = build_profile(folder, seed=20261018)
            profile_path = folder / "experiment.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with patch.dict(os.environ, {"UCTP_BENCHMARK": "1"}):
                call_command("benchmark_auto_schedule", input_dir=str(folder), semester_name="QUALITY BENCH",
                             weeks=16, report=str(folder / "report.json"), budget_seconds=5,
                             strategy="single", search_seed=42, cp_workers=1, approve=True,
                             experiment_file=str(profile_path),
                             stdout=StringIO())
            report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["feasible"])
            self.assertEqual(report["hard_penalty"], 0)
            self.assertEqual(report["scheduled_sessions"], 3)
            self.assertEqual(report["export_rows"], 3)
            self.assertEqual(report["distinct_initial_solutions"], 1)
            self.assertTrue(report["algorithm_sha256"])
            self.assertTrue(report["experiment_sha256"])
            timing = report["phase_seconds"]
            self.assertTrue(timing)
            self.assertTrue(all(v >= 0 for v in timing.values()))
            self.assertLessEqual(timing["finalization_sql_execute_seconds"],
                                 timing["finalization_after_search_seconds"] + 0.000002)
            worker_phases = sum(timing[k] for k in ("before_search_seconds", "search_including_audits_seconds",
                                                    "finalization_after_search_seconds", "queue_and_worker_other_seconds"))
            self.assertAlmostEqual(worker_phases, report["worker_seconds"], delta=0.001)
            run = self.semester.__class__.objects.get(name="QUALITY BENCH").algorithm_runs.get()
            self.assertEqual(len(run.preferences_snapshot), len(profile["preferences"]))
            for row in profile["qualification_priorities"]:
                self.assertEqual(TeachingQualification.objects.get(
                    lecturer__employee_code=row["employee_code"], course__code=row["course_code"]).priority,
                    row["priority"])
