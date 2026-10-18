"""Configurable simulated teaching units; no official SGU conversion assumed."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import ConversionRule, Lecturer, ScheduleEntry, Semester, TeachingQuota, WorkloadPolicy


def cent(value):
    return int((Decimal(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def configuration(semester):
    policy = WorkloadPolicy.objects.filter(semester=semester).first()
    return policy, {r.course_kind: r.factor for r in ConversionRule.objects.filter(semester=semester)}


@transaction.atomic
def save_configuration(obj, actor):
    from .access import check_write
    check_write(actor, type(obj), {f.name: getattr(obj, f.name) for f in obj._meta.fields
                                 if f.is_relation and f.name != "id"}, instance=obj if obj.pk else None,
                action="change" if obj.pk else "add")
    semester_ids = {obj.semester_id}
    if obj.pk:
        semester_ids.update(type(obj).objects.filter(pk=obj.pk).values_list("semester_id", flat=True))
    semesters = list(Semester.objects.select_for_update().filter(pk__in=semester_ids).order_by("pk"))
    if any(s.status == "DaKhoa" for s in semesters):
        from rest_framework.exceptions import ValidationError
        raise ValidationError("Học kỳ đã khóa; không thay cấu hình khối lượng.")
    from django.core.exceptions import ValidationError as ModelError
    from rest_framework.exceptions import ValidationError as ApiError
    try:
        obj.full_clean()
    except ModelError as exc:
        raise ApiError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
    obj.save()
    return obj


def workload_rows(semester, lecturers, status=None):
    policy, rules = configuration(semester)
    default = policy.default_factor if policy else None
    quotas = {q.lecturer_id: q for q in TeachingQuota.objects.filter(semester=semester)}
    lecturers = list(lecturers)
    totals = defaultdict(lambda: {"periods": 0, "units": Decimal(0), "missing": set(), "sessions": 0})
    entries = ScheduleEntry.objects.filter(group__semester=semester, lecturer_id__in=[t.pk for t in lecturers])
    entries = entries.filter(status=status) if status else entries.filter(status__in=("ChoDuyet", "DaDuyet"))
    for entry in entries.select_related("group__course").prefetch_related("schedule_weeks"):
        item = totals[entry.lecturer_id]
        periods = entry.period_count * len(list(entry.schedule_weeks.all()))
        item["periods"] += periods
        item["sessions"] += 1
        factor = rules.get(entry.group.course.kind, default)
        if factor is None:
            item["missing"].add(entry.group.course.kind)
        else:
            item["units"] += periods * factor
    result = []
    for teacher in lecturers:
        item, quota = totals[teacher.pk], quotas.get(teacher.pk)
        units = None if item["missing"] else item["units"].quantize(Decimal("0.01"))
        target = quota.target_units if quota else None
        effective = Decimal(cent(target * quota.allocation_fraction)) / 100 if quota else None
        result.append({"lecturer": teacher, "sessions": item["sessions"], "actual_periods": item["periods"],
                       "converted_units": units, "known_partial_units": item["units"], "quota": target,
                       "effective_quota": effective, "difference": units - effective if units is not None and effective is not None else None,
                       "missing_factors": sorted(item["missing"]), "missing_quota": quota is None})
    return result


class BalanceObjective:
    def __init__(self, semester, teacher_map, snapshot=None):
        if snapshot is not None:
            self.snapshot = snapshot
        else:
            policy, rules = configuration(semester)
            weight = policy.balance_weight if policy else 0
            self.snapshot = {"version": "soft_v2_workload" if weight else "soft_v1", "weight": weight}
            if weight:
                quotas = {q.lecturer_id: cent(q.target_units * q.allocation_fraction)
                          for q in TeachingQuota.objects.filter(semester=semester, lecturer_id__in=[t.pk for t in teacher_map.values()])}
                if any(t.pk not in quotas for t in teacher_map.values()):
                    raise ValueError("Cân bằng tải đã bật nhưng thiếu định mức giảng viên trong dữ liệu xếp lịch.")
                if any(v <= 0 for v in quotas.values()):
                    raise ValueError("Định mức phân bổ phải đạt ít nhất 0,01 giờ quy đổi.")
                self.snapshot.update(quotas={str(k): v for k, v in quotas.items()},
                                     factors={k: cent(v) for k, v in rules.items()},
                                     default_factor=cent(policy.default_factor) if policy.default_factor is not None else None)
        self.weight = self.snapshot.get("weight", 0)
        self.quotas = {int(k): v for k, v in self.snapshot.get("quotas", {}).items()}
        self.factors = self.snapshot.get("factors", {})
        self.default = self.snapshot.get("default_factor")
        self.volumes = self.snapshot.setdefault("volumes", {}) if self.weight else {}
        self.fixed = {int(k): v for k, v in self.snapshot.get("fixed_loads", {}).items()}
        if self.weight and snapshot is None:
            for entry in (ScheduleEntry.objects.filter(group__semester=semester, lecturer_id__in=self.quotas)
                          .exclude(source="ThuatToan", status="ChoDuyet")
                          .select_related("group__course").prefetch_related("schedule_weeks")):
                volume = entry.period_count * len(list(entry.schedule_weeks.all())) * self.factor(entry.group.course.kind)
                self.fixed[entry.lecturer_id] = self.fixed.get(entry.lecturer_id, 0) + volume
            self.snapshot["fixed_loads"] = {str(k): v for k, v in self.fixed.items()}

    def factor(self, kind):
        factor = self.factors.get(kind, self.default)
        if factor is None:
            raise ValueError(f"Thiếu hệ số quy đổi mô phỏng cho loại học phần {kind}.")
        return factor

    def volume(self, demand):
        import json
        group = demand["group"]
        key = json.dumps((group.course.code, group.group, group.lab_group or "", demand["code"]))
        if key not in self.volumes:
            self.volumes[key] = demand["count"] * len(demand["weeks"]) * self.factor(group.course.kind)
        return self.volumes[key]

    def loads(self, solution):
        loads = {t: self.fixed.get(t, 0) for t in self.quotas} if self.weight else {}
        if self.weight:
            for demand, _, _, _, teacher in solution:
                loads[teacher.pk] = loads.get(teacher.pk, 0) + self.volume(demand)
        return loads

    def cost(self, teacher_id, load):
        denominator = self.quotas[teacher_id] * 100
        return (load * load + denominator - 1) // denominator

    def score(self, loads):
        return self.weight * sum(self.cost(t, loads.get(t, 0)) for t in self.quotas) if self.weight else 0

    def add_cp_objective(self, model, choices, demands):
        if not self.weight:
            return []
        terms = []
        volumes = [self.volume(d) for d in demands]
        for teacher_id in self.quotas:
            maximum = self.fixed.get(teacher_id, 0) + sum(volumes)
            if maximum > 2_000_000_000:
                raise OverflowError("CP workload objective exceeds safe integer range")
            load = model.NewIntVar(0, maximum, f"load_{teacher_id}")
            model.Add(load == self.fixed.get(teacher_id, 0) + sum(
                volumes[i] * g[j] for i, (_, _, _, _, teachers, g) in enumerate(choices)
                for j, q in enumerate(teachers) if q.lecturer_id == teacher_id))
            square = model.NewIntVar(0, maximum * maximum, f"load_square_{teacher_id}")
            model.AddMultiplicationEquality(square, [load, load])
            denominator = self.quotas[teacher_id] * 100
            penalty = model.NewIntVar(0, (maximum * maximum + denominator - 1) // denominator, f"load_cost_{teacher_id}")
            model.AddDivisionEquality(penalty, square + denominator - 1, denominator)
            terms.append(self.weight * penalty)
        return terms
