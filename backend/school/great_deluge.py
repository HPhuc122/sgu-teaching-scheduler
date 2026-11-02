"""Bounded Great Deluge improvement for a CP-SAT timetable.

Only one assignment is changed at a time. Every proposed move is checked
against the same resource, availability and eligibility rules as the solver.
"""

from collections import defaultdict
from random import Random
from time import monotonic

from .models import ScheduleEntry
from .soft_score import SoftScorer


def _overlap(start_a, count_a, start_b, count_b):
    return start_a < start_b + count_b and start_b < start_a + count_a


def improve(semester, initial, room_map, teacher_map, room_blocks, teacher_blocks,
            allowed_pairs, *, max_iterations=3000, time_limit=5, seed=42,
            preferences=None, deadline=None, scoring=None, telemetry=None,
            stagnation_limit=None):
    """Return (best solution, initial score, best score).

    The score exactly matches the CP-SAT objective in auto_schedule.solve.
    The starting solution is assumed to have passed the CP-SAT hard rules.
    """
    started = monotonic()
    deadline = min(deadline if deadline is not None else float("inf"), started + time_limit)
    stats = telemetry if telemetry is not None else {}
    stats.update(seed=seed, iterations=0, proposals=0, valid_moves=0, accepted_moves=0,
                 score_improvements=0, max_iterations=max_iterations,
                 time_limit_seconds=time_limit, stagnation_limit=stagnation_limit,
                 stop_reason=None)
    if stagnation_limit is not None and (type(stagnation_limit) is not int or stagnation_limit < 1):
        raise ValueError("GD stagnation limit must be a positive integer")
    scoring = scoring or SoftScorer(semester, teacher_map, allowed_pairs, preferences)
    periods = scoring.periods
    first_score = scoring.score(initial)
    stats["score_before"] = first_score

    def finish(solution, score, reason):
        stats.update(score_after=score, stop_reason=reason, seconds=round(monotonic() - started, 6))
        return solution, first_score, score

    if not initial:
        return finish([], first_score, "EMPTY_SOLUTION")
    if first_score == 0:
        return finish(list(initial), first_score, "ZERO_SCORE")
    if max_iterations <= 0:
        return finish(list(initial), first_score, "ITERATION_LIMIT")
    if monotonic() >= deadline:
        return finish(list(initial), first_score, "TIME_LIMIT")
    qualifications = defaultdict(list)
    for row in scoring.qualifications:
        qualifications[row.course_id].append(row)
    teacher_unavailable = defaultdict(list)
    preferences = scoring.preferences
    for item in preferences:
        if item.kind == "NgayNghi" and item.day:
            for week in range(1, semester.week_count + 1):
                teacher_unavailable[(item.lecturer_id, item.day, week)].append((1, 13))
    room_unavailable = defaultdict(list)
    for code, day, start, count, weeks in room_blocks:
        for week in weeks:
            room_unavailable[(room_map[code].pk, day, week)].append((start, count))
    for code, day, start, count, weeks in teacher_blocks:
        for week in weeks:
            teacher_unavailable[(teacher_map[code].pk, day, week)].append((start, count))

    options = []
    for demand, _, _, _, _ in initial:
        if monotonic() >= deadline:
            return finish(list(initial), first_score, "SETUP_TIME_LIMIT")
        group = demand["group"]
        times = [(day, start) for day in demand["days"] for start in sorted(periods)
                 if not any((day, week) in demand.get("activity_blocks", set()) for week in demand["weeks"])
                 and all(number in periods and periods[number].block == periods[start].block
                        for number in range(start, start + demand["count"]))]
        rooms = [room for room in room_map.values() if room.status == "SanSang"
                 and room.capacity >= group.capacity
                 and (not demand["room_type"] or room.room_type == demand["room_type"])]
        teachers = [row.lecturer for row in qualifications[group.course_id]]
        if demand.get("assigned_teacher") is not None:
            teachers = [t for t in teachers if t.pk == demand["assigned_teacher"].pk]
        options.append((times, rooms, teachers, {row.lecturer_id: row.priority
                                                 for row in qualifications[group.course_id]}))

    fixed = []
    previous = (ScheduleEntry.objects.filter(group__semester=semester)
                .exclude(source="ThuatToan", status="ChoDuyet")
                .select_related("group").prefetch_related("schedule_weeks", "group__cohort_links"))
    for entry in previous:
        if monotonic() >= deadline:
            return finish(list(initial), first_score, "SETUP_TIME_LIMIT")
        fixed.append((entry.group_id, frozenset(link.cohort_id for link in entry.group.cohort_links.all()),
                      frozenset(item.week for item in entry.schedule_weeks.all()),
                      entry.day, entry.start_period_id, entry.period_count, entry.room_id, entry.lecturer_id))
    cohorts = [frozenset(link.cohort_id for link in item[0]["group"].cohort_links.all())
               for item in initial]

    def penalty(index, assignment):
        return scoring.penalty(assignment)

    def valid(index, candidate, solution):
        demand, day, start, room, teacher = candidate
        group = demand["group"]
        count, weeks = demand["count"], demand["weeks"]
        times, rooms, teachers, _ = options[index]
        if ((day, start) not in times or room not in rooms or teacher not in teachers):
            return False
        for week in weeks:
            for resource_id, blocked in ((room.pk, room_unavailable),
                                         (teacher.pk, teacher_unavailable)):
                if any(_overlap(start, count, busy_start, busy_count)
                       for busy_start, busy_count in blocked[(resource_id, day, week)]):
                    return False
        for other_index, (other_demand, other_day, other_start, other_room, other_teacher) in enumerate(solution):
            if other_index == index or day != other_day or not weeks.intersection(other_demand["weeks"]):
                continue
            if not _overlap(start, count, other_start, other_demand["count"]):
                continue
            if (room.pk == other_room.pk or teacher.pk == other_teacher.pk or
                    group.pk == other_demand["group"].pk or cohorts[index] & cohorts[other_index]):
                return False
        for fixed_group, fixed_cohorts, fixed_weeks, fixed_day, fixed_start, fixed_count, fixed_room, fixed_teacher in fixed:
            if day != fixed_day or not weeks.intersection(fixed_weeks):
                continue
            if not _overlap(start, count, fixed_start, fixed_count):
                continue
            if (room.pk == fixed_room or teacher.pk == fixed_teacher or group.pk == fixed_group
                    or cohorts[index] & fixed_cohorts):
                return False
        return True

    current = list(initial)
    current_score = scoring.score(current)
    workload_loads = scoring.balance.loads(current)
    first_score = current_score
    best = list(current)
    best_score = current_score
    if not current or current_score == 0 or max_iterations <= 0:
        return finish(best, best_score, "ZERO_SCORE" if current_score == 0 else "ITERATION_LIMIT")
    rng = Random(seed)
    level = current_score + max(1, current_score // 5)
    last_improvement = 0
    stop_reason = "ITERATION_LIMIT"
    for iteration in range(max_iterations):
        if monotonic() >= deadline:
            stop_reason = "TIME_LIMIT"
            break
        if stagnation_limit is not None and iteration - last_improvement >= stagnation_limit:
            stop_reason = "STAGNATION"
            break
        stats["iterations"] += 1
        index = rng.randrange(len(current))
        demand, day, start, room, teacher = current[index]
        times, rooms, teachers, _ = options[index]
        operator = rng.randrange(3)
        if operator == 0 and len(times) > 1:
            new_day, new_start = rng.choice(times)
            candidate = (demand, new_day, new_start, room, teacher)
        elif operator == 1 and len(rooms) > 1:
            candidate = (demand, day, start, rng.choice(rooms), teacher)
        elif operator == 2 and len(teachers) > 1:
            candidate = (demand, day, start, room, rng.choice(teachers))
        else:
            continue
        stats["proposals"] += 1
        if candidate == current[index] or not valid(index, candidate, current):
            continue
        stats["valid_moves"] += 1
        proposed_score = current_score + scoring.move_delta(current[index], candidate, workload_loads)
        # Water level decreases toward the original score. Keep the best seen
        # even when an accepted intermediate move is worse than the current one.
        water_level = first_score + (level - first_score) * (1 - iteration / max_iterations)
        if proposed_score <= water_level:
            stats["accepted_moves"] += 1
            scoring.accept_move(current[index], candidate, workload_loads)
            current[index] = candidate
            current_score = proposed_score
            if current_score < best_score:
                stats["score_improvements"] += 1
                last_improvement = iteration + 1
                best, best_score = list(current), current_score
                if best_score == 0:
                    stop_reason = "ZERO_SCORE"
                    break
    return finish(best, best_score, stop_reason)
