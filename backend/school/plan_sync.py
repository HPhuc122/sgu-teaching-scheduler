"""Conservative Excel reconciliation, provenance and expiring confirmation previews."""
from datetime import timedelta
from hashlib import sha256
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import models
from .access import require_global
from .ui import FIELD_LABELS, MODEL_LABELS


PLAN_MODELS = (models.GroupTeachingPlan, models.TeachingAssignment,
               models.OffCampusActivity, models.LecturerOtherDuty, models.SemesterResourcePlan)
CATALOG_MODELS = (models.Faculty, models.Department, models.Program, models.Course,
                  models.CourseProgram, models.Building, models.Room, models.Lecturer,
                  models.TeachingQualification, models.CourseGroup, models.Cohort, models.GroupCohort)
LABELS = {"groupteachingplan": "Kế hoạch nhóm", "teachingassignment": "Buổi yêu cầu",
          "offcampusactivity": "Hoạt động ngoài trường", "lecturerotherduty": "Công tác khác",
          "semesterresourceplan": "Thời gian không khả dụng"}
FIELD_NAMES = {**FIELD_LABELS, "groupcohort": "Lớp trong nhóm", "request_code": "Mã buổi",
    "component": "Loại buổi", "period_count": "Số tiết mỗi buổi", "reported_periods": "Số tiết thực tế",
    "weeks": "Tuần học", "allowed_days": "Thứ được xếp", "fixed_lecturer": "Giảng viên cố định",
    "semester_number": "Học kỳ số", "cohort_label": "Khóa", "lecture_periods": "Số tiết LT",
    "exercise_periods": "Số tiết BT", "practical_periods": "Số tiết TH", "coefficient": "Hệ số học phần",
    "note": "Ghi chú", "cohort": "Lớp hành chính", "description": "Nội dung", "location": "Địa điểm",
    "student_count": "Số sinh viên", "training_level": "Trình độ", "periods": "Số tiết công tác",
    "room_blocks": "Phòng không khả dụng", "teacher_blocks": "Giảng viên không khả dụng"}


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True))


def _key(model, pk):
    return f"{model._meta.model_name}:{pk}"


def _query(model, semester):
    if model in (models.GroupTeachingPlan, models.TeachingAssignment, models.GroupCohort):
        return model.objects.filter(group__semester=semester)
    if model in (models.CourseGroup, models.Cohort, models.OffCampusActivity,
                 models.LecturerOtherDuty, models.SemesterResourcePlan):
        return model.objects.filter(semester=semester)
    return model.objects.all()


def inventory(semester, *, lock=False):
    records = {}
    # Catalog rows are never deleted by synchronization. Include them in the
    # preview and stale-state fingerprint because the shared importer updates them.
    for model in (*CATALOG_MODELS, *PLAN_MODELS):
        qs = _query(model, semester).order_by("pk")
        if lock:
            qs = qs.select_for_update()
        for values in qs.values():
            records[_key(model, values[model._meta.pk.attname])] = _json(values)
    return records


def _comparable(key, values):
    values = values.copy()
    if key.startswith("teachingassignment:"):
        # The scheduler selects lecturer_id; the user's fixed_lecturer_id is
        # tracked independently and must never be silently overwritten.
        values.pop("lecturer_id", None)
    return values


def fingerprint(semester, records=None):
    state = models.PlanImportState.objects.filter(semester=semester).values_list("records", flat=True).first() or {}
    payload = dict(records=records if records is not None else inventory(semester), source=state,
                   semester=_json(models.Semester.objects.values().get(pk=semester.pk)),
                   entries=list(models.ScheduleEntry.objects.filter(group__semester=semester).order_by("pk").values()),
                   weeks=list(models.ScheduleWeek.objects.filter(entry__group__semester=semester).order_by("pk").values()),
                   active=list(models.ScheduleRunQueue.objects.filter(semester=semester).values_list("run_id", flat=True)))
    return sha256(json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def begin_import(semester):
    state = models.PlanImportState.objects.filter(semester=semester).first()
    return inventory(semester), state.records.copy() if state else {}


def _description(key, values, records=None):
    name = key.split(":")[0]
    identity = values.get("request_code") or values.get("code") or values.get("name") or values.get("group_id") or values["id"]
    if records is not None and values.get("group_id"):
        group = records.get(f"coursegroup:{values['group_id']}", {})
        course = records.get(f"course:{group.get('course_id')}", {})
        identity = f"{course.get('code', '')}/{group.get('group', '')} · {values.get('request_code', '')}"
    return f"{LABELS.get(name, MODEL_LABELS.get(name, 'Liên kết danh mục'))} · {identity} (#{values['id']})"


def _incoming_catalog_keys(data, records, demands):
    c, r, t = data["courses"], data["rooms"], data["lecturers"]
    codes = {
        "faculty": ("code", {x["ma_khoa"] for x in c["Khoa"]}),
        "department": ("code", {x["ma_bo_mon"] for x in c["BoMon"]}),
        "course": ("code", {x["ma_mon_hoc"] for x in c["HocPhan"]}),
        "building": ("code", {x["ma_toa_nha"] for x in r["PhongHoc"]}),
        "room": ("code", {x["ma_phong"] for x in r["PhongHoc"]}),
        "lecturer": ("employee_code", {x["ma_vien_chuc"] for x in t["GiangVien"]}),
        "cohort": ("name", {name.strip() for x in c["NhomHocPhan"] for name in x["ten_lop"].split(";") if name.strip()}),
    }
    seen = {key for key, value in records.items() if key.split(":")[0] in codes
            and value[codes[key.split(":")[0]][0]] in codes[key.split(":")[0]][1]}
    programs = {(x["ma_nganh_ctdt"], x["chu_ky_ctdt"]) for x in c["ChuongTrinh"]}
    course_programs = {(x["ma_mon_hoc"], x["ma_nganh_ctdt"], x["chu_ky_ctdt"]) for x in c["HocPhanChuongTrinh"]}
    pairs = {(x["ma_vien_chuc"], x["ma_mon_hoc"]) for x in t["GiangVienHocPhan"]}
    groups = {d["key"]: d["group"].pk for d in demands}
    links = {(groups[(x["ma_mon_hoc"], x["nhom"], x["to_th"])], name.strip())
             for x in c["NhomHocPhan"] for name in x["ten_lop"].split(";") if name.strip()}
    for key, value in records.items():
        name = key.split(":")[0]
        present = False
        if name == "program":
            present = (value["code"], value["cycle"]) in programs
        elif name == "coursegroup":
            present = value["id"] in groups.values()
        elif name == "groupcohort":
            cohort = records[f"cohort:{value['cohort_id']}"]
            present = (value["group_id"], cohort["name"]) in links
        elif name == "courseprogram":
            course, program = (records[f"{model}:{value[model + '_id']}"] for model in ("course", "program"))
            present = (course["code"], program["code"], program["cycle"]) in course_programs
        elif name == "teachingqualification":
            teacher, course = (records[f"{model}:{value[model + '_id']}"] for model in ("lecturer", "course"))
            present = (teacher["employee_code"], course["code"]) in pairs
        if present:
            seen.add(key)
    return seen


def _field_change(key, field, before, after, records_before, records_after):
    name = field.removesuffix("_id")
    model = next(model for model in (*CATALOG_MODELS, *PLAN_MODELS) if model._meta.model_name == key.split(":")[0])
    model_field = next(f for f in model._meta.concrete_fields if f.attname == field)
    if model_field.is_relation:
        related = model_field.related_model._meta.model_name
        def label(value, records):
            values = records.get(f"{related}:{value}")
            return _description(f"{related}:{value}", values, records) if values else value
        before, after = label(before, records_before), label(after, records_after)
    return dict(name=FIELD_NAMES.get(name, str(model_field.verbose_name)), before=before, after=after)


def _protect_shared_update(key):
    name, pk = key.split(":")
    paths = {
        "faculty": ("group__course__department__faculty_id", "lecturer__department__faculty_id"),
        "department": ("group__course__department_id", "lecturer__department_id"),
        "course": ("group__course_id",), "coursegroup": ("group_id",),
        "building": ("room__building_id",), "room": ("room_id",), "lecturer": ("lecturer_id",),
        "cohort": ("group__cohort_links__cohort_id",),
    }
    if name not in paths:
        return
    relation = Q()
    for path in paths[name]:
        relation |= Q(**{path: pk})
    protected = models.ScheduleEntry.objects.filter(
        Q(status="DaDuyet") | Q(group__semester__status="DaKhoa") |
        Q(group__semester__active_schedule_run__isnull=False), relation)
    if protected.exists():
        raise ValueError("Không thể đổi danh mục đang được lịch đã duyệt, học kỳ đã khóa "
                         "hoặc phiên xếp lịch đang chạy sử dụng.")


def finish_import(semester, context, demands, prepared, data):
    before, previous_tracked = context
    tracked = previous_tracked.copy()
    after = inventory(semester)
    added, updated = [], []
    explicit_keys = {key for key, _ in prepared["groups"]}
    explicit_group_ids = {d["group"].pk for d in demands if d["key"] in explicit_keys}
    explicit_plans = {_key(models.GroupTeachingPlan, pk) for pk in
                      models.GroupTeachingPlan.objects.filter(group_id__in=explicit_group_ids).values_list("pk", flat=True)}
    for key, values in after.items():
        old = before.get(key)
        if old is not None and old != values:
            _protect_shared_update(key)
            baseline = tracked.get(key)
            if baseline:
                current, imported, previous = (_comparable(key, v) for v in (old, values, baseline))
                conflicts = [field for field in current
                             if current[field] != previous.get(field) and imported[field] != current[field]]
                if conflicts:
                    raise ValueError(f"{_description(key, old, before)} đã sửa thủ công ({', '.join(FIELD_NAMES.get(f.removesuffix('_id'), f) for f in conflicts)}). "
                                     "Giữ dữ liệu hiện tại hoặc sửa Excel cho khớp trước khi nhập lại.")
            updated.append(dict(key=key, label=_description(key, values, after), source="Excel" if baseline else "Chưa rõ nguồn",
                                fields=[_field_change(key, field, old.get(field), value, before, after)
                                        for field, value in values.items() if old.get(field) != value]))
        elif old is None:
            added.append(dict(key=key, label=_description(key, values, after), source="Excel"))
        # Only creation proves origin. Legacy records are not retroactively owned.
        if old is None or (key in tracked and (not key.startswith("groupteachingplan:") or key in explicit_plans)):
            tracked[key] = values

    seen = {_key(models.TeachingAssignment, d["planned_assignment_id"]) for d in demands}
    group_ids = {d["group"].pk for d in demands}
    seen.update(_key(models.GroupTeachingPlan, pk) for pk in models.GroupTeachingPlan.objects.filter(group_id__in=group_ids).values_list("pk", flat=True))
    for name, values in prepared["activities"]:
        pk = models.OffCampusActivity.objects.get(semester=semester, cohort__name=name, code=values["code"]).pk
        seen.add(_key(models.OffCampusActivity, pk))
    for teacher, code, _ in prepared["duties"]:
        pk = models.LecturerOtherDuty.objects.get(semester=semester, lecturer__employee_code=teacher, code=code).pk
        seen.add(_key(models.LecturerOtherDuty, pk))
    seen.update(_key(models.SemesterResourcePlan, pk) for pk in models.SemesterResourcePlan.objects.filter(semester=semester).values_list("pk", flat=True))
    seen.update(_incoming_catalog_keys(data, after, demands))

    missing = []
    removable_names = {model._meta.model_name for model in PLAN_MODELS} - {"semesterresourceplan"}
    removable_names.add("groupcohort")
    for key, values in before.items():
        name = key.split(":")[0]
        if key in seen or (name not in removable_names and key not in previous_tracked):
            continue
        baseline = context[1].get(key)
        removable = name in removable_names and baseline is not None and _comparable(key, baseline) == _comparable(key, values)
        missing.append(dict(key=key, label=_description(key, values, before), removable=removable,
                            source="Excel" if baseline else "Chưa rõ nguồn",
                            reason=("Có thể xóa sau xác nhận" if removable else "Giữ lại: đã sửa thủ công hoặc chưa rõ nguồn")
                            if name in removable_names else "Giữ lại danh mục dùng chung"))
    removable_keys = {item["key"] for item in missing if item["removable"]}
    for item in missing:
        if item["key"].split(":")[0] in ("groupteachingplan", "groupcohort") and item["removable"]:
            group_id = before[item["key"]]["group_id"]
            if any(values["group_id"] == group_id and key not in removable_keys and key not in seen
                   for key, values in before.items() if key.startswith("teachingassignment:")):
                item.update(removable=False, reason="Giữ kế hoạch nhóm vì còn buổi yêu cầu được bảo vệ")
    # Retained missing records keep their OLD baseline, so a later import cannot
    # accidentally relabel a manual edit as the last imported value.
    for item in missing:
        if item["key"] in context[1]:
            tracked[item["key"]] = context[1][item["key"]]
    tracked = {key: value for key, value in tracked.items() if key in after}
    models.PlanImportState.objects.update_or_create(semester=semester, defaults={"records": tracked})
    return dict(added=added, updated=updated, missing=missing,
                removable_count=sum(item["removable"] for item in missing))


def preview_import(semester_id, files, actor):
    require_global(actor, "run")
    from .auto_schedule import AUTO_SHEETS, read_auto_files
    from .planning import save_plan_from_workbooks
    read_auto_files(files)
    content = {}
    for kind in AUTO_SHEETS:
        files[kind].seek(0)
        content[kind] = files[kind].read()
    with transaction.atomic():
        models.PendingPlanImport.objects.filter(created_at__lt=timezone.now() - timedelta(minutes=30)).delete()
        semester = models.Semester.objects.select_for_update().get(pk=semester_id)
        baseline = fingerprint(semester, inventory(semester, lock=True))
        # Execute the real validated importer in a savepoint and roll it back.
        # No catalog or plan changes are persisted during preview.
        with transaction.atomic():
            result = save_plan_from_workbooks(semester_id, _uploads(content)).import_result
            transaction.set_rollback(True)
        return models.PendingPlanImport.objects.create(semester=semester, actor=actor,
            baseline_digest=baseline, summary=result, **{f"{kind}_file": value for kind, value in content.items()})


def _uploads(content):
    return {kind: SimpleUploadedFile(f"{kind}.xlsx", bytes(value)) for kind, value in content.items()}


@transaction.atomic
def confirm_import(preview_id, actor, *, remove_missing=False):
    require_global(actor, "run")
    from .planning import save_plan_from_workbooks
    pending = models.PendingPlanImport.objects.select_for_update().get(pk=preview_id, actor=actor)
    if timezone.now() - pending.created_at > timedelta(minutes=30):
        raise ValueError("Bản xem trước đã hết hạn. Hãy tải lại ba file để xem trước.")
    semester = models.Semester.objects.select_for_update().get(pk=pending.semester_id)
    if fingerprint(semester, inventory(semester, lock=True)) != pending.baseline_digest:
        raise ValueError("Dữ liệu đã thay đổi sau khi xem trước. Hãy tạo bản xem trước mới.")
    semester = save_plan_from_workbooks(semester.pk, _uploads({
        kind: getattr(pending, f"{kind}_file") for kind in ("courses", "rooms", "lecturers")}))
    if remove_missing:
        # Recomputed from current state under the same transaction; never trust
        # client-supplied IDs or a client-supplied deletion list.
        missing = semester.import_result["missing"]
        registry = {model._meta.model_name: model for model in (*PLAN_MODELS, models.GroupCohort)}
        for item in missing:
            if item["removable"]:
                name, pk = item["key"].split(":")
                _query(registry[name], semester).filter(pk=pk).delete()
        state = models.PlanImportState.objects.get(semester=semester)
        current = inventory(semester)
        state.records = {key: value for key, value in state.records.items() if key in current}
        state.save(update_fields=["records"])
    pending.delete()
    return semester
