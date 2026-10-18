"""One nonnegative soft objective shared by CP-SAT, search and verification."""

from collections import defaultdict

from .models import LecturerPreference, Period, TeachingQualification


def evening_penalty(block):
    return 5 if block.lower().startswith("toi") else 0


def preference_penalty(preferences, day, block):
    total = 0
    for pref in preferences:
        if not pref.time_block or (pref.day is not None and pref.day != day):
            continue
        if pref.priority <= 2 and pref.time_block != block:
            total += (3 - pref.priority) * 4
        elif pref.priority >= 3 and pref.time_block == block:
            total += (pref.priority - 2) * 4
    return total


class SoftScorer:
    """Capture periods, qualifications and preferences once per scheduling run.

    Model instances here are read-only snapshots: search never refreshes or
    updates them. The independent hard audit still checks current resources.
    """

    def __init__(self, semester, teacher_map, allowed_pairs, preferences=None, quality_snapshot=None):
        self.periods = {p.pk: p for p in Period.objects.order_by("pk")}
        teacher_ids = {teacher.pk for teacher in teacher_map.values()}
        self.qualifications = tuple(
            row for row in TeachingQualification.objects.filter(lecturer_id__in=teacher_ids)
            .select_related("lecturer", "course").order_by("course__code", "lecturer__employee_code")
            if row.lecturer.status == "DangCongTac"
            and (row.lecturer.employee_code, row.course.code) in allowed_pairs
        )
        self.priorities = {(row.lecturer_id, row.course_id): row.priority
                           for row in self.qualifications}
        self.preferences = tuple(preferences if preferences is not None else
                                 LecturerPreference.objects.filter(semester=semester).order_by("pk"))
        self.time_preferences = defaultdict(list)
        for pref in self.preferences:
            if pref.kind == "KhungGio":
                self.time_preferences[pref.lecturer_id].append(pref)
        from .workload import BalanceObjective
        eligible = {q.lecturer_id for q in self.qualifications}
        self.balance = BalanceObjective(semester, {k: t for k, t in teacher_map.items() if t.pk in eligible}, quality_snapshot)
        self.quality_snapshot = self.balance.snapshot
        self.objective_version = self.quality_snapshot["version"]

    def penalty(self, assignment):
        demand, day, start, _, teacher = assignment
        block = self.periods[start].block
        return (evening_penalty(block)
                + max(0, self.priorities[(teacher.pk, demand["group"].course_id)] - 1)
                + preference_penalty(self.time_preferences[teacher.pk], day, block))

    def score(self, solution):
        return sum(self.penalty(item) for item in solution) + self.balance.score(self.balance.loads(solution))

    def move_delta(self, old, new, loads):
        delta = self.penalty(new) - self.penalty(old)
        if self.balance.weight and old[4].pk != new[4].pk:
            volume = self.balance.volume(old[0])
            for teacher_id, change in ((old[4].pk, -volume), (new[4].pk, volume)):
                before = loads.get(teacher_id, 0)
                delta += self.balance.weight * (self.balance.cost(teacher_id, before + change)
                                               - self.balance.cost(teacher_id, before))
        return delta

    def accept_move(self, old, new, loads):
        if self.balance.weight and old[4].pk != new[4].pk:
            volume = self.balance.volume(old[0])
            loads[old[4].pk] = loads.get(old[4].pk, 0) - volume
            loads[new[4].pk] = loads.get(new[4].pk, 0) + volume
