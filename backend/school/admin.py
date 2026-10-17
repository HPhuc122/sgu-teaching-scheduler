from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.utils.html import format_html

from .ui import CODE_OPTIONS, FIELD_LABELS, MODEL_LABELS, STATUS_LABELS

from .models import (Building, Cohort, Course, CourseGroup, CourseProgram, Department, Faculty,
                     Lecturer, Period, Room, Semester, TeachingQualification)
from .models import Program

admin.site.index_template = "school/admin_index.html"
admin.site.site_header = "SGU Teaching Scheduler"
admin.site.site_title = "SGU Teaching Scheduler"
admin.site.index_title = "Tổng quan"
admin.site.site_url = None
admin.site.enable_nav_sidebar = False


def related_label(obj):
    """Readable option labels without changing model __str__ or API output."""
    name = getattr(obj, "name", None)
    code = getattr(obj, "code", None) or getattr(obj, "employee_code", None)
    if name:
        return f"{code} · {name}" if code else name
    if isinstance(obj, CourseGroup):
        return f"{obj.course} · Nhóm {obj.group} · {obj.semester}"
    return str(obj)


class PreservingCodeSelect(forms.Select):
    """Show readable codes while retaining any legacy value on existing records."""

    def optgroups(self, name, value, attrs=None):
        options = list(self.choices)
        known = {str(code) for code, _ in options}
        for code in value:
            if code and str(code) not in known:
                options.append((code, code))
        self.choices = options
        return super().optgroups(name, value, attrs)


class SchoolModelAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = True
    save_on_top = False

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        kwargs.setdefault("label", FIELD_LABELS.get(db_field.name, db_field.verbose_name))
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        codes = CODE_OPTIONS.get((self.model._meta.model_name, db_field.name))
        if field is not None and codes:
            # Change only the widget. CharField validation and stored codes remain intact.
            field.widget = PreservingCodeSelect(choices=[(code, STATUS_LABELS[code]) for code in codes])
        if field is not None and hasattr(field, "label_from_instance"):
            field.label_from_instance = related_label
        return field

    def get_list_display(self, request):
        columns = []
        for name in super().get_list_display(request):
            if name not in FIELD_LABELS:
                columns.append(name)
                continue

            def display(obj, field=name):
                value = getattr(obj, field)
                if field == "status":
                    tone = "success" if value in ("DangCongTac", "SanSang", "DangMo") else "warning"
                    return format_html('<span class="badge {}">{}</span>', tone, STATUS_LABELS.get(value, value))
                if field in ("kind", "room_type", "requirement", "block"):
                    return STATUS_LABELS.get(value, value)
                if value is not None and hasattr(value, "_meta"):
                    return related_label(value)
                return value

            display.__name__ = f"ui_{name}"
            display.short_description = FIELD_LABELS[name]
            display.admin_order_field = name
            columns.append(display)
        return columns

    def _ui_context(self, extra_context, action=""):
        return {**(extra_context or {}), "title": f"{action}{MODEL_LABELS[self.model._meta.model_name]}"}

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, self._ui_context(extra_context))

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(request, form_url, self._ui_context(extra_context, "Thêm "))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(request, object_id, form_url, self._ui_context(extra_context, "Chi tiết: "))

    def delete_view(self, request, object_id, extra_context=None):
        return super().delete_view(request, object_id, self._ui_context(extra_context, "Xóa "))

    def history_view(self, request, object_id, extra_context=None):
        return super().history_view(request, object_id, self._ui_context(extra_context, "Lịch sử: "))


@admin.register(Faculty)
class FacultyAdmin(SchoolModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    fieldsets = (("Thông tin khoa", {"fields": ("code", "name")}),)


@admin.register(Department)
class DepartmentAdmin(SchoolModelAdmin):
    list_display = ("code", "name", "faculty")
    list_filter = ("faculty",)
    search_fields = ("code", "name", "faculty__name")
    fieldsets = (("Thông tin bộ môn", {"fields": ("code", "name", "faculty")}),)


@admin.register(Lecturer)
class LecturerAdmin(SchoolModelAdmin):
    list_display = ("employee_code", "name", "department", "status")
    search_fields = ("employee_code", "name", "email")
    list_filter = ("department", "status")
    fieldsets = (
        ("Hồ sơ giảng viên", {"fields": ("employee_code", "name", "email")}),
        ("Đơn vị & tài khoản", {"fields": ("department", "user", "status")}),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.scheduleentry_set.filter(status="DaDuyet").exists():
            return ("status",)
        return ()


@admin.register(Course)
class CourseAdmin(SchoolModelAdmin):
    list_display = ("code", "name", "credits", "kind", "department")
    search_fields = ("code", "name")
    list_filter = ("department", "kind")
    fieldsets = (
        ("Thông tin học phần", {"fields": ("code", "name", "credits")}),
        ("Phân loại & đơn vị phụ trách", {"fields": ("kind", "department")}),
    )


@admin.register(TeachingQualification)
class TeachingQualificationAdmin(SchoolModelAdmin):
    list_display = ("lecturer", "course", "priority")
    search_fields = ("lecturer__name", "lecturer__employee_code", "course__code", "course__name")
    list_filter = ("priority",)
    fieldsets = (("Chuyên môn giảng dạy", {"fields": ("lecturer", "course", "priority")}),)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.lecturer.scheduleentry_set.filter(group__course=obj.course,
                                                         status="DaDuyet").exists():
            return ("lecturer", "course")
        return ()

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def has_delete_permission(self, request, obj=None):
        if obj and obj.lecturer.scheduleentry_set.filter(group__course=obj.course,
                                                         status="DaDuyet").exists():
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Semester)
class SemesterAdmin(SchoolModelAdmin):
    list_display = ("name", "academic_year", "week_count", "status")
    search_fields = ("name", "academic_year")
    list_filter = ("status", "academic_year")
    fieldsets = (
        ("Thông tin học kỳ", {"fields": ("name", "academic_year", "status")}),
        ("Thời gian đào tạo", {"fields": ("start_date", "end_date", "week_count")}),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.coursegroup_set.filter(scheduleentry__isnull=False).exists():
            return ("week_count", "start_date", "end_date")
        return ()


@admin.register(Building)
class BuildingAdmin(SchoolModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    fieldsets = (("Thông tin tòa nhà", {"fields": ("code", "name")}),)


@admin.register(Program)
class ProgramAdmin(SchoolModelAdmin):
    list_display = ("code", "name", "cycle", "faculty")
    search_fields = ("code", "name")
    list_filter = ("faculty", "cycle")
    fieldsets = (("Chương trình đào tạo", {"fields": ("code", "name", "cycle", "faculty")}),)


@admin.register(CourseProgram)
class CourseProgramAdmin(SchoolModelAdmin):
    list_display = ("course", "program", "requirement")
    search_fields = ("course__code", "course__name", "program__code", "program__name")
    list_filter = ("requirement",)
    fieldsets = (("Liên kết học phần & chương trình", {"fields": ("course", "program", "requirement")}),)


@admin.register(Room)
class RoomAdmin(SchoolModelAdmin):
    list_display = ("code", "name", "capacity", "status")
    search_fields = ("code", "name")
    list_filter = ("building", "room_type", "status")
    fieldsets = (
        ("Thông tin phòng học", {"fields": ("code", "name", "building")}),
        ("Sức chứa & sử dụng", {"fields": ("capacity", "room_type", "status")}),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.scheduleentry_set.filter(status="DaDuyet").exists():
            return ("status",)
        return ()


@admin.register(Period)
class PeriodAdmin(SchoolModelAdmin):
    list_display = ("id", "block", "start_time", "end_time")
    search_fields = ("block",)
    list_filter = ("block",)
    fieldsets = (("Khung tiết học", {"fields": ("id", "block", "start_time", "end_time")}),)


@admin.register(CourseGroup)
class CourseGroupAdmin(SchoolModelAdmin):
    list_display = ("code", "course", "semester", "group", "lab_group", "capacity")
    list_filter = ("semester",)
    search_fields = ("code", "course__code", "course__name", "group")
    fieldsets = (
        ("Học phần & học kỳ", {"fields": ("course", "semester", "code")}),
        ("Tổ chức lớp học", {"fields": ("group", "lab_group", "capacity", "needs_room")}),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.scheduleentry_set.exists():
            return ("course", "semester", "code", "group", "lab_group", "needs_room")
        return ()


@admin.register(Cohort)
class CohortAdmin(SchoolModelAdmin):
    list_display = ("name", "semester")
    search_fields = ("name",)
    list_filter = ("semester",)
    fieldsets = (("Thông tin lớp hành chính", {"fields": ("name", "semester")}),)


def permission_label(permission):
    actions = {"add": "Thêm", "change": "Sửa", "delete": "Xóa", "view": "Xem"}
    model = permission.content_type.model
    label = MODEL_LABELS.get(model, {
        "algorithmrun": "Phiên xếp lịch", "schedulerunqueue": "Hàng đợi xếp lịch",
        "scheduleentry": "Buổi dạy", "scheduleweek": "Tuần học của buổi dạy",
        "lecturerpreference": "Nguyện vọng giảng viên", "groupcohort": "Liên kết lớp",
        "logentry": "Lịch sử quản trị", "session": "Phiên đăng nhập",
        "contenttype": "Loại nội dung", "permission": "Quyền truy cập",
    }.get(model, model))
    action = actions.get(permission.codename.split("_", 1)[0], permission.name)
    app = {"school": "Đào tạo", "auth": "Tài khoản"}.get(
        permission.content_type.app_label, permission.content_type.app_label)
    return f"{app} · {label} · {action}"


class PermissionPresentationMixin:
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        field = super().formfield_for_manytomany(db_field, request, **kwargs)
        if field is not None and db_field.name in ("permissions", "user_permissions"):
            field.queryset = field.queryset.select_related("content_type")
            field.label_from_instance = permission_label
        return field


# Preserve the built-in auth forms, fieldsets and permission checks.
admin.site.unregister(get_user_model())
admin.site.unregister(Group)


@admin.register(get_user_model())
class SchedulerUserAdmin(PermissionPresentationMixin, UserAdmin):
    list_per_page = 30


@admin.register(Group)
class SchedulerGroupAdmin(PermissionPresentationMixin, GroupAdmin):
    list_per_page = 30
