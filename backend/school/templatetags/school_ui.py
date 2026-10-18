from django import template
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from school.models import AlgorithmRun, Course, Lecturer, Room, Semester
from school.ui import FIELD_LABELS, MODEL_LABELS, STATUS_LABELS

register = template.Library()


@register.filter
def model_label(value):
    name = getattr(value, "model_name", str(value)).lower()
    return MODEL_LABELS.get(name, str(value))


@register.filter
def status_label(value):
    return STATUS_LABELS.get(value, value)


@register.filter
def filter_title(spec):
    return FIELD_LABELS.get(getattr(spec, "field_path", ""), spec.title)


@register.filter
def field_label(value):
    return FIELD_LABELS.get(str(value), str(value))


@register.simple_tag
def admin_field_label(field):
    if field.is_readonly and field.field.get("name") in FIELD_LABELS:
        return format_html("<label>{}:</label>", FIELD_LABELS[field.field["name"]])
    return field.label_tag()


@register.simple_tag(takes_context=True)
def ui_navigation(context):
    request = context["request"]
    if not request.user.is_active or not request.user.is_staff:
        return []
    sections = [
        ("Khối lượng & quyền đơn vị", ("teachingquota", "workloadpolicy", "conversionrule", "unitroleassignment")),
        ("Tổ chức & nhân sự", ("faculty", "department", "lecturer", "teachingqualification")),
        ("Đào tạo & cơ sở vật chất", ("course", "coursegroup", "program", "courseprogram",
                                     "cohort", "building", "room", "semester", "period")),
        ("Quản trị hệ thống", ("user", "group")),
    ]
    available = {}
    for model, model_admin in admin.site._registry.items():
        permissions = model_admin.get_model_perms(request)
        view = "changelist" if permissions.get("view") or permissions.get("change") else "add" if permissions.get("add") else None
        if model_admin.has_module_permission(request) and view:
            name = model._meta.model_name
            available[name] = {
                "label": ("Thêm " if view == "add" else "") + MODEL_LABELS.get(name, str(model._meta.verbose_name_plural)),
                "url": reverse(f"admin:{model._meta.app_label}_{name}_{view}"),
            }
    return [{"label": label, "links": [available[name] for name in names if name in available]}
            for label, names in sections if any(name in available for name in names)]


@register.simple_tag(takes_context=True)
def dashboard_data(context):
    request = context["request"]
    if not request.user.is_active or not request.user.is_staff:
        return {}
    stats = []
    for model, label in ((Lecturer, "Giảng viên"), (Course, "Học phần"),
                         (Room, "Phòng học"), (Semester, "Học kỳ")):
        model_admin = admin.site._registry[model]
        if model_admin.has_module_permission(request) and model_admin.has_view_or_change_permission(request):
            stats.append({"label": label, "count": model_admin.get_queryset(request).count(),
                          "url": reverse(f"admin:school_{model._meta.model_name}_changelist")})
    from school.access import global_action
    runs = AlgorithmRun.objects.all() if global_action(request.user) else AlgorithmRun.objects.none()
    return {"stats": stats, "run_count": runs.count(),
            "recent_runs": runs.select_related("semester").order_by("-created_at")[:5]}
