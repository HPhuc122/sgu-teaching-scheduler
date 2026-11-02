"""Backend unit authorization for the explicitly simulated role model."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from rest_framework.permissions import BasePermission

from .models import Department, UnitRoleAssignment

SHARED = {"semester", "period", "room", "building", "workloadpolicy", "conversionrule"}
PATHS = {"faculty": ["department"], "department": ["pk"], "lecturer": ["department"],
         "course": ["department"], "program": ["faculty__department"],
         "courseprogram": ["course__department", "program__faculty__department"],
         "teachingqualification": ["lecturer__department", "course__department"],
         "coursegroup": ["course__department"], "cohort": ["department"],
         "groupcohort": ["group__course__department", "cohort__department"],
         "scheduleentry": ["group__course__department", "lecturer__department"],
         "scheduleweek": ["entry__group__course__department", "entry__lecturer__department"],
         "lecturerpreference": ["lecturer__department"], "teachingquota": ["lecturer__department"]}
PATHS.update({"groupteachingplan": ["group__course__department"],
              "teachingassignment": ["group__course__department"],
              "offcampusactivity": ["cohort__department"],
              "lecturerotherduty": ["lecturer__department"]})


def roles(user):
    if not user or not user.is_authenticated or not user.is_active or not user.is_staff:
        return UnitRoleAssignment.objects.none()
    return UnitRoleAssignment.objects.filter(user=user)


def system_admin(user):
    return bool(user and user.is_authenticated and user.is_active and
                (user.is_superuser or roles(user).filter(role="ADMIN", all_units=True).exists()))


def allowed_departments(user, action="view", model_name=None):
    """None means all units; empty queryset means deny."""
    if system_admin(user):
        return None
    grants = roles(user)
    if action == "approve":
        grants = grants.filter(role="TRAINING", can_manage=True)
    elif action in ("add", "change", "delete", "run"):
        grants = grants.filter(can_manage=True)
        if action in ("delete", "run") or model_name not in ("scheduleentry", "scheduleweek"):
            grants = grants.exclude(role="HEAD")
    if grants.filter(all_units=True).exists():
        return None
    return Department.objects.filter(Q(pk__in=grants.values("department_id"))
                                     | Q(faculty_id__in=grants.values("faculty_id")))


def global_action(user, action="view"):
    return allowed_departments(user, action) is None


def model_action(user, name, action):
    if action == "view" or system_admin(user):
        return True
    grants = roles(user).filter(can_manage=True)
    if name not in ("scheduleentry", "scheduleweek"):
        grants = grants.exclude(role="HEAD")
    if name in ("unitroleassignment", "user", "group", "permission"):
        return False
    return grants.exists()


def scoped(qs, user, action="view"):
    if system_admin(user):
        return qs
    name = qs.model._meta.model_name
    if not model_action(user, name, action):
        return qs.none()
    departments = allowed_departments(user, action, name)
    if name in ("unitroleassignment", "user", "group", "permission", "algorithmrun", "schedulerunqueue"):
        return qs.none()
    if name in SHARED:
        if action != "view":
            return qs if departments is None else qs.none()
        return qs if roles(user).exists() else qs.none()
    if departments is None:
        return qs
    if name not in PATHS:
        return qs.none()
    if action == "view" and name == "teachingassignment":
        return qs.filter(Q(group__course__department__in=departments) | Q(lecturer__department__in=departments)).distinct()
    if action == "view" and name == "offcampusactivity":
        return qs.filter(Q(cohort__department__in=departments) | Q(
            cohort__department__isnull=True, cohort__groupcohort__group__course__department__in=departments)).distinct()
    if action == "view" and name in ("scheduleentry", "scheduleweek"):
        prefix = "entry__" if name == "scheduleweek" else ""
        # Reading a teaching timetable follows the lecturer's unit. Unassigned
        # sessions remain visible to the course unit; write/approval scopes below
        # continue to require both units for cross-unit teaching.
        return qs.filter(
            Q(**{prefix + "lecturer__department__in": departments}) |
            Q(**{prefix + "lecturer__isnull": True,
                 prefix + "group__course__department__in": departments})
        ).distinct()
    for path in PATHS[name]:
        condition = Q(**{path + "__in": departments})
        # An unassigned session belongs to its course unit.
        if name in ("scheduleentry", "scheduleweek") and path.endswith("lecturer__department"):
            condition |= Q(**{path.removesuffix("department") + "isnull": True})
        qs = qs.filter(condition)
    return qs.distinct()


def require_object(user, obj, action="view"):
    if not scoped(type(obj).objects.filter(pk=obj.pk), user, action).exists():
        raise PermissionDenied("Không có quyền trong phạm vi đơn vị này.")


def require_global(user, action="change"):
    if not global_action(user, action):
        raise PermissionDenied("Thao tác toàn hệ thống cần quyền điều phối toàn phạm vi.")


def check_write(user, model, values, instance=None, action="change"):
    if instance is not None:
        require_object(user, instance, action)
    if system_admin(user):
        return
    if not model_action(user, model._meta.model_name, action):
        raise PermissionDenied("Vai trò không được thực hiện thao tác này.")
    if model._meta.model_name == "faculty" and action == "add":
        require_global(user, action)
    if model._meta.model_name == "department" and action == "add" and not global_action(user, action):
        if not roles(user).filter(can_manage=True, faculty=values.get("faculty"), role__in=("FACULTY", "TRAINING")).exists():
            raise PermissionDenied("Không được tạo đơn vị ngoài phạm vi quản lý khoa.")
    if model._meta.model_name in SHARED and not global_action(user, action):
        raise PermissionDenied("Danh mục dùng chung chỉ được cập nhật bởi quản trị/điều phối toàn hệ thống.")
    permitted = allowed_departments(user, action, model._meta.model_name)
    if permitted is not None and not permitted.exists():
        raise PermissionDenied("Không được cấp quyền thao tác.")
    for name, value in values.items():
        if model._meta.model_name == "lecturer" and name == "user":
            if (getattr(value, "pk", None) != (instance.user_id if instance else None)):
                raise PermissionDenied("Chỉ quản trị được thay liên kết tài khoản.")
        if hasattr(value, "_meta"):
            if value._meta.app_label == "auth":
                if instance is None or getattr(instance, name + "_id", None) != value.pk:
                    raise PermissionDenied("Chỉ quản trị được liên kết tài khoản.")
            else:
                require_object(user, value, "view")
    if model._meta.model_name in PATHS:
        # Creation must be rooted in an owned relation; orphan/global cohort denied.
        candidate = model()
        if instance:
            for field in model._meta.concrete_fields:
                setattr(candidate, field.attname, getattr(instance, field.attname))
        for key, value in values.items():
            if key in {f.name for f in model._meta.fields}:
                setattr(candidate, key, value)
        if model._meta.model_name == "cohort" and not candidate.department_id:
            raise PermissionDenied("Lớp hành chính cần đơn vị quản lý.")
        name = model._meta.model_name
        owner_ids = []
        if name in ("lecturer", "course", "cohort"):
            owner_ids = [candidate.department_id]
        elif name in ("teachingquota", "lecturerpreference", "lecturerotherduty"):
            owner_ids = [candidate.lecturer.department_id]
        elif name == "teachingqualification":
            owner_ids = [candidate.lecturer.department_id, candidate.course.department_id]
        elif name in ("groupteachingplan", "teachingassignment"):
            owner_ids = [candidate.group.course.department_id]
        elif name == "offcampusactivity":
            owner_ids = [candidate.cohort.department_id]
        elif name in ("coursegroup", "courseprogram"):
            owner_ids = [candidate.course.department_id]
            if name == "courseprogram":
                require_object(user, candidate.program, action)
        elif name == "scheduleweek":
            require_object(user, candidate.entry, action)
        elif name == "scheduleentry":
            owner_ids = [candidate.group.course.department_id]
            if candidate.lecturer_id:
                owner_ids.append(candidate.lecturer.department_id)
        elif name == "groupcohort":
            owner_ids = [candidate.group.course.department_id, candidate.cohort.department_id]
        if permitted is not None and any(not permitted.filter(pk=pk).exists() for pk in owner_ids):
            raise PermissionDenied("Không được chuyển bản ghi hoặc gán quan hệ sang phạm vi chỉ có quyền xem.")
        if name in ("faculty", "program", "department"):
            faculty_id = candidate.pk if name == "faculty" else candidate.faculty_id
            if not global_action(user, action) and not roles(user).filter(
                    role__in=("FACULTY", "TRAINING"), can_manage=True, faculty_id=faculty_id).exists():
                raise PermissionDenied("Thao tác cấp khoa cần quyền quản lý cấp khoa.")


class UnitPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_active
                    and (system_admin(request.user) or roles(request.user).exists()))


def can_approve(user, entries):
    return all(scoped(type(e).objects.filter(pk=e.pk), user, "approve").exists() for e in entries)


def check_delete(user, obj, visited=None):
    """Do not cascade into another unit or reveal its objects on confirmation."""
    require_object(user, obj, "delete")
    if system_admin(user):
        return
    visited = set() if visited is None else visited
    key = (obj._meta.label, obj.pk)
    if key in visited:
        return
    visited.add(key)
    for relation in obj._meta.related_objects:
        children = relation.related_model.objects.filter(**{relation.field.name: obj})
        for child in children:
            check_delete(user, child, visited)
