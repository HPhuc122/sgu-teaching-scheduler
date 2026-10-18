"""Audited multi-start search. No persistence or approval policy lives here."""

from hashlib import sha256
import json
from math import isfinite
from time import monotonic

from django.conf import settings

from .auto_schedule_errors import InputIssues
from .great_deluge import improve
from .search_budget import (SearchBudgetExpired, extra_gd_budget,
                            load_cp_observations, trial_budget)
from .soft_score import SoftScorer
from .solution_audit import audit_solution


def solution_fingerprint(solution):
    rows = sorted((d["group"].course.code, d["group"].group,
                   d["group"].lab_group or "", d["code"], day, start,
                   room.code, teacher.employee_code, d["count"], sorted(d["weeks"]))
                  for d, day, start, room, teacher in solution)
    return sha256(json.dumps(rows, ensure_ascii=True).encode()).hexdigest()


def pending_solution(semester, demands):
    """Only compare an incumbent covering exactly the current demands/weeks."""
    from .models import ScheduleEntry

    entries = list(ScheduleEntry.objects.filter(
        group__semester=semester, source="ThuatToan", status="ChoDuyet",
    ).select_related("room", "lecturer").prefetch_related("schedule_weeks"))
    mapping = {(entry.group_id, entry.request_code): entry for entry in entries}
    if len(entries) != len(demands) or len(mapping) != len(entries):
        return None
    result = []
    for demand in demands:
        entry = mapping.get((demand["group"].pk, demand["code"]))
        if (entry is None or entry.room is None or entry.lecturer is None
                or entry.period_count != demand["count"]
                or {row.week for row in entry.schedule_weeks.all()} != demand["weeks"]):
            return None
        result.append((demand, entry.day, entry.start_period_id, entry.room, entry.lecturer))
    return result


def search_quality(semester, demands, room_map, teacher_map, room_blocks, teacher_blocks,
                   allowed_pairs, *, preferences, deadline, max_starts=3, seed=42,
                   num_search_workers=4, strategy="multi_start", generation_policy="greedy_first",
                   cp_policy="budget_aware", cp_observations=None, gd_policy="adaptive"):
    """Return solution, status, winning start score, final score and trial log.

    The first start can use bounded CP-SAT below 500 sessions; later starts
    construct fresh greedy schedules. ``legacy`` is a benchmark control:
    one construction followed by up to three GD paths from that same start.
    Deadlines include preparation; mandatory audits/persistence may finish
    after them. Never accept an unaudited solution to meet a time limit.
    """
    from .auto_schedule import solve

    if not 1 <= max_starts <= 3:
        raise ValueError("Số lần khởi tạo phải từ 1 đến 3")
    if strategy not in ("multi_start", "legacy"):
        raise ValueError("Chiến lược thực nghiệm không hợp lệ")
    if generation_policy not in ("greedy_first", "model_first"):
        raise ValueError("Unknown generation policy")
    if cp_policy not in ("budget_aware", "fixed_window"):
        raise ValueError("Unknown CP admission policy")
    if gd_policy not in ("baseline", "adaptive"):
        raise ValueError("Unknown GD policy")
    adaptive = gd_policy == "adaptive" and strategy != "legacy"
    if adaptive:
        for value, maximum in ((settings.QUALITY_GD_EXTRA_PATHS, 30),
                               (settings.QUALITY_GD_EXTRA_ITERATIONS, 1000000),
                               (settings.QUALITY_GD_STAGNATION_ITERATIONS, 1000000),
                               (settings.QUALITY_GD_STALE_ROUNDS, 10)):
            if type(value) is not int or not (0 if maximum == 30 else 1) <= value <= maximum:
                raise ValueError("Invalid bounded GD configuration")
        if (not isfinite(settings.QUALITY_GD_EXTRA_PATH_SECONDS)
                or not 0 < settings.QUALITY_GD_EXTRA_PATH_SECONDS <= 5
                or not isfinite(settings.QUALITY_GD_MIN_PATH_SECONDS)
                or not 0 < settings.QUALITY_GD_MIN_PATH_SECONDS <= settings.QUALITY_GD_EXTRA_PATH_SECONDS):
            raise ValueError("Invalid GD trajectory time limit")
    observations = (load_cp_observations(settings.QUALITY_CP_BUILD_PROFILE)
                    if cp_observations is None else cp_observations)
    budget_aware = cp_policy == "budget_aware" and generation_policy == "greedy_first"
    snapshot_started = monotonic()
    scoring = SoftScorer(semester, teacher_map, allowed_pairs, preferences)
    if scoring.balance.weight:
        for demand in demands:
            scoring.balance.volume(demand)
    snapshot_seconds = round(monotonic() - snapshot_started, 6)
    if not scoring.periods:
        raise ValueError("Chưa cấu hình tiết học cho hệ thống")
    preferences = scoring.preferences
    args = (semester, demands, room_map, teacher_map, room_blocks, teacher_blocks, allowed_pairs)
    best, best_score, best_before, best_status, best_trial = None, None, None, "UNKNOWN", None
    trials, seen, candidates, contexts = [], {}, [], []

    def audit(solution):
        audit_solution(semester, demands, solution, room_map, teacher_map,
                       room_blocks, teacher_blocks, allowed_pairs, preferences=preferences)

    def consider(solution, score, before, status, trial):
        nonlocal best, best_score, best_before, best_status, best_trial
        candidates.append((solution, score, before, status, trial))
        if (best is None or score < best_score
                or (score == best_score and status == "OPTIMAL" and best_status != "OPTIMAL")):
            best, best_score, best_before, best_status, best_trial = solution, score, before, status, trial

    incumbent = pending_solution(semester, demands)
    if incumbent is not None:
        started = monotonic()
        record = {"kind": "incumbent", "seed": None, "status": "HEURISTIC"}
        try:
            audit(incumbent)
            score = scoring.score(incumbent)
            record.update(outcome="VALID", score_before=score, score_after=score,
                          score=score, fingerprint=solution_fingerprint(incumbent))
            consider(incumbent, score, score, "HEURISTIC", record)
        except (ValueError, KeyError) as exc:
            record.update(outcome="AUDIT_REJECTED", error=str(exc))
        record["seconds"] = round(monotonic() - started, 6)
        trials.append(record)

    starts = 1 if strategy == "legacy" else max_starts
    for index in range(starts):
        if best_score == 0:
            break
        now = monotonic()
        if now >= deadline:
            trials.append({"kind": "stop", "seed": seed + index,
                           "outcome": "BUDGET_EXHAUSTED", "status": "UNKNOWN", "seconds": 0})
            break
        trial_deadline = now + (deadline - now) / (starts - index)
        # Leave part of this start's allocation for GD; also charge building
        # the model and greedy seed to the generation deadline.
        generation_deadline = now + (trial_deadline - now) * 0.8
        downstream = (trial_budget(now, trial_deadline,
                                   gd_reserve=settings.QUALITY_GD_RESERVE_SECONDS,
                                   audit_reserve=settings.QUALITY_AUDIT_RESERVE_SECONDS)
                      if budget_aware else {"generation_deadline": generation_deadline,
                                            "improvement_deadline": trial_deadline,
                                            "gd_reserved_seconds": (trial_deadline - now) * 0.2,
                                            "audit_reserved_seconds": 0})
        generation_deadline = downstream["generation_deadline"]
        record = {"kind": "start", "seed": seed + index, "status": "UNKNOWN",
                  "outcome": "NO_SOLUTION", "score_before": None, "score_after": None,
                  "score": None, "generation_seconds": 0, "improvement_seconds": 0,
                  "audit_seconds": 0, "allocated_seconds": round(trial_deadline - now, 6),
                  "generation": {}, "snapshot_seconds": snapshot_seconds if index == 0 else 0,
                  "budget": {**downstream,
                             "generation_allocated_seconds": round(generation_deadline - now, 6)},
                  "gd_allocated_seconds": 0, "gd_calls": 0,
                  "gd_policy": "adaptive" if adaptive else "baseline", "extra_gd_seconds": 0}
        trials.append(record)
        try:
            initial, status, solver_score = solve(
                *args, preferences=preferences, scoring=scoring, seed=seed + index,
                deadline=generation_deadline, use_cp_sat=index == 0,
                num_search_workers=num_search_workers,
                generation_policy=generation_policy, telemetry=record["generation"],
                cp_policy=cp_policy, cp_observations=observations,
            )
            record.update(status=status, generation_seconds=round(monotonic() - now, 6))
            record["generation_unused_seconds"] = round(max(0, generation_deadline - monotonic()), 6)
            if initial is None:
                if status == "INFEASIBLE":
                    # A solver proof applies to the same model in all starts.
                    if best is None:
                        best_status = "INFEASIBLE"
                    break
                continue
            audit_started = monotonic()
            try:
                audit(initial)
            finally:
                record["audit_seconds"] += monotonic() - audit_started
            before = scoring.score(initial)
            if before != solver_score:
                raise ValueError("Điểm bộ giải không khớp hàm điểm chung")
            fingerprint = solution_fingerprint(initial)
            record.update(score_before=before, score_after=before, score=before,
                          initial_fingerprint=fingerprint, fingerprint=fingerprint, outcome="VALID")
            consider(initial, before, before, status, record)
            duplicate = fingerprint in seen
            if duplicate:
                record.update(outcome="DUPLICATE", duplicate_initial_of=seen[fingerprint])
            else:
                seen[fingerprint] = seed + index
            if status == "OPTIMAL" or before == 0:
                break
            if duplicate:
                continue
            context = {"initial": tuple(initial), "best": tuple(initial), "best_score": before,
                       "before": before, "record": record, "status": status,
                       "stale": 0, "extra_count": 0}
            contexts.append(context)
            paths = 3 if strategy == "legacy" else 1
            # Legacy retains the old nine-second GD cap and its common S0.
            improvement_deadline = downstream["improvement_deadline"]
            gd_deadline = min(improvement_deadline, monotonic() + 9) if strategy == "legacy" else improvement_deadline
            record["gd_available_after_generation_seconds"] = round(max(0, gd_deadline - monotonic()), 6)
            record["paths"] = []
            for path in range(paths):
                remaining = gd_deadline - monotonic()
                if remaining <= 0 or best_score == 0:
                    break
                improvement_started = monotonic()
                time_limit = min(5, remaining / (paths - path))
                record["gd_allocated_seconds"] += time_limit
                record["gd_calls"] += 1
                path_stats = {}
                try:
                    try:
                        candidate, verified_before, reported_after = improve(
                            semester, initial, room_map, teacher_map, room_blocks, teacher_blocks,
                            allowed_pairs, preferences=preferences, scoring=scoring,
                            seed=seed + index + path, max_iterations=3000,
                            time_limit=time_limit, deadline=gd_deadline,
                            telemetry=path_stats,
                        )
                    finally:
                        record["improvement_seconds"] += monotonic() - improvement_started
                    audit_started = monotonic()
                    try:
                        audit(candidate)
                    finally:
                        elapsed_audit = monotonic() - audit_started
                        record["audit_seconds"] += elapsed_audit
                        path_stats["audit_seconds"] = round(elapsed_audit, 6)
                    after = scoring.score(candidate)
                    if verified_before != before or reported_after != after:
                        raise ValueError("Điểm Great Deluge không khớp hàm điểm chung")
                    record["paths"].append({**path_stats, "phase": "initial", "anchor": "S0",
                                            "seed": seed + index + path, "score": after,
                                            "audit_passed": True,
                                            "fingerprint": solution_fingerprint(candidate)})
                    # A rejected or worse improvement cannot displace S0.
                    if after < record["score_after"]:
                        record.update(score_after=after, score=after,
                                      fingerprint=solution_fingerprint(candidate))
                    consider(candidate, after, before, status, record)
                    if after < context["best_score"]:
                        context.update(best=tuple(candidate), best_score=after)
                except (ValueError, KeyError, RuntimeError, SearchBudgetExpired) as exc:
                    record.update(outcome="IMPROVEMENT_REJECTED", error=str(exc))
                    record["paths"].append({**path_stats, "phase": "initial", "anchor": "S0",
                                            "seed": seed + index + path, "audit_passed": False,
                                            "stop_reason": "REJECTED", "error": str(exc)})
        except InputIssues:
            raise
        except SearchBudgetExpired:
            record.update(outcome="BUDGET_EXHAUSTED")
        except RuntimeError as exc:
            record.update(status="ERROR", outcome="SEARCH_ERROR", error=str(exc))
        except (ValueError, KeyError) as exc:
            record.update(outcome="AUDIT_REJECTED", error=str(exc))
        finally:
            if not record["generation_seconds"]:
                record["generation_seconds"] = round(monotonic() - now, 6)
            record["seconds"] = round(monotonic() - now, 6)
            record["initial_round_seconds"] = record["seconds"]
            for key in ("audit_seconds", "improvement_seconds"):
                record[key] = round(record[key], 6)
            record["gd_allocated_seconds"] = round(record["gd_allocated_seconds"], 6)
            record["gd_unused_seconds"] = round(max(0, record["gd_allocated_seconds"]
                                                       - record["improvement_seconds"]), 6)

    # Every constructive start and its first GD turn are attempted before any
    # extra work. Round-robin slices cannot consume another start's first turn.
    extra_count, extra_stop = 0, "BASELINE"
    if adaptive and contexts:
        extra_stop = "PATH_LIMIT"
        while extra_count < settings.QUALITY_GD_EXTRA_PATHS:
            if best_score == 0:
                extra_stop = "ZERO_SCORE"
                break
            eligible = [c for c in contexts if c["stale"] < settings.QUALITY_GD_STALE_ROUNDS]
            if not eligible:
                extra_stop = "NO_USEFUL_IMPROVEMENT"
                break
            for position, context in enumerate(eligible):
                if extra_count >= settings.QUALITY_GD_EXTRA_PATHS or best_score == 0:
                    break
                now = monotonic()
                time_limit = extra_gd_budget(
                    now, deadline, eligible_starts=len(eligible) - position,
                    path_seconds=settings.QUALITY_GD_EXTRA_PATH_SECONDS,
                    audit_reserve=settings.QUALITY_AUDIT_RESERVE_SECONDS,
                    min_seconds=settings.QUALITY_GD_MIN_PATH_SECONDS)
                if not time_limit:
                    extra_stop = "BUDGET_EXHAUSTED"
                    break
                record = context["record"]
                from_best = context["extra_count"] % 2 == 0
                anchor = context["best"] if from_best else context["initial"]
                anchor_score = scoring.score(anchor)
                path_seed = seed + starts + extra_count
                extra_count += 1
                context["extra_count"] += 1
                path_stats = {}
                path = {"phase": "extra", "anchor": "BEST" if from_best else "S0",
                        "seed": path_seed, "extra_sequence": extra_count,
                        "score_before": anchor_score, "start_best_before": context["best_score"],
                        "audit_passed": False}
                record["paths"].append(path)
                record["gd_calls"] += 1
                record["gd_allocated_seconds"] += time_limit
                started = monotonic()
                improved = False
                try:
                    try:
                        candidate, verified_before, reported_after = improve(
                            semester, anchor, room_map, teacher_map, room_blocks, teacher_blocks,
                            allowed_pairs, preferences=preferences, scoring=scoring,
                            seed=path_seed, max_iterations=settings.QUALITY_GD_EXTRA_ITERATIONS,
                            time_limit=time_limit, deadline=deadline - settings.QUALITY_AUDIT_RESERVE_SECONDS,
                            telemetry=path_stats, stagnation_limit=settings.QUALITY_GD_STAGNATION_ITERATIONS)
                    finally:
                        elapsed = monotonic() - started
                        record["improvement_seconds"] += elapsed
                        record["extra_gd_seconds"] += elapsed
                    audit_started = monotonic()
                    try:
                        audit(candidate)
                    finally:
                        elapsed_audit = monotonic() - audit_started
                        record["audit_seconds"] += elapsed_audit
                        path["audit_seconds"] = round(elapsed_audit, 6)
                    after = scoring.score(candidate)
                    if verified_before != anchor_score or reported_after != after:
                        raise ValueError("Extra GD score differs from shared objective")
                    path.update(audit_passed=True, score=after, fingerprint=solution_fingerprint(candidate))
                    consider(candidate, after, context["before"], context["status"], record)
                    if after < context["best_score"]:
                        context.update(best=tuple(candidate), best_score=after)
                        record.update(score_after=after, score=after, fingerprint=path["fingerprint"])
                        improved = True
                except (ValueError, KeyError, RuntimeError, SearchBudgetExpired) as exc:
                    path.update(error=str(exc), stop_reason="REJECTED")
                finally:
                    # Telemetry cannot turn a failed/audit-rejected candidate into
                    # a valid one. Previously audited candidates remain available.
                    path.update({k: v for k, v in path_stats.items() if k not in ("seed", "audit_seconds")})
                    if not path["audit_passed"]:
                        path["stop_reason"] = "REJECTED"
                    path.update(improves_start_best=improved, start_best_after=context["best_score"])
                    path["wall_seconds"] = round(monotonic() - started, 6)
                    record["seconds"] += path["wall_seconds"]
                context["stale"] = 0 if improved else context["stale"] + 1
            if extra_stop == "BUDGET_EXHAUSTED":
                break
        for context in contexts:
            record = context["record"]
            record.update(extra_search_stop_reason="ZERO_SCORE" if best_score == 0 else extra_stop,
                          extra_paths=context["extra_count"], stale_extra_paths=context["stale"])
            for key in ("seconds", "audit_seconds", "improvement_seconds", "extra_gd_seconds", "gd_allocated_seconds"):
                record[key] = round(record[key], 6)
            record["gd_unused_seconds"] = round(max(0, record["gd_allocated_seconds"] - record["improvement_seconds"]), 6)

    # Recheck ranked candidates at selection time. If the lowest-scoring one
    # is rejected, try the next, including its previously audited initial S0.
    if candidates:
        best, best_score, best_before, best_status, best_trial = None, None, None, "UNKNOWN", None
        for solution, score, before, status, record in sorted(
                candidates, key=lambda item: (item[1], item[3] != "OPTIMAL")):
            started = monotonic()
            try:
                audit(solution)
            except (ValueError, KeyError) as exc:
                record.setdefault("selection_rejections", []).append(str(exc))
                continue
            finally:
                record["selection_audit_seconds"] = round(
                    record.get("selection_audit_seconds", 0) + monotonic() - started, 6)
            best, best_score, best_before, best_status, best_trial = solution, score, before, status, record
            record.update(selected_score=score, selected_fingerprint=solution_fingerprint(solution))
            break
    for record in trials:
        record["selected"] = record is best_trial
    starts_log = [record for record in trials if record["kind"] == "start"]
    if best is None and starts_log and all(record["outcome"] == "SEARCH_ERROR" for record in starts_log):
        best_status = "ERROR"
    if trials:
        trials[0].update(objective_version=scoring.objective_version, quality_snapshot=scoring.quality_snapshot)
    return best, best_status, best_before, best_score, trials
