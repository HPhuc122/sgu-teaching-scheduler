"""Backstop for custom staff screens; API/admin enforce object scopes separately."""
from django.core.exceptions import PermissionDenied
from .access import global_action, require_global, require_object, roles, system_admin
from .models import AlgorithmRun, Course, Faculty, Lecturer, ScheduleEntry


class UnitAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return None
        name = request.resolver_match.url_name
        guarded = {"auto_schedule", "auto_template", "import_catalog", "import_catalog_template", "import_schedule",
                   "import_schedule_template", "review_schedules", "edit_schedule", "export_assignments", "faculty_timetable", "workload_report"}
        if name not in guarded:
            return None
        if not system_admin(request.user) and not roles(request.user).exists():
            raise PermissionDenied("Chưa được phân quyền nghiệp vụ/đơn vị.")
        if name in {"import_catalog", "import_catalog_template", "import_schedule", "import_schedule_template", "auto_template"}:
            require_global(request.user, "change")
        if name == "auto_schedule":
            require_global(request.user, "run" if request.method == "POST" else "view")
        for source in (request.GET, request.POST):
            for key, model in (("faculty", Faculty), ("lecturer", Lecturer), ("course", Course)):
                value = source.get(key, "")
                if value.isdigit():
                    obj = model.objects.filter(pk=value).first()
                    if obj:
                        require_object(request.user, obj)
            if source.get("run", "").isdigit() and not global_action(request.user):
                raise PermissionDenied("Nhật ký toàn lần chạy chỉ dành cho điều phối toàn hệ thống.")
        if name == "edit_schedule":
            obj = ScheduleEntry.objects.filter(pk=view_kwargs["entry_id"]).first()
            if obj:
                require_object(request.user, obj, "change")
