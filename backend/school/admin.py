from django.contrib import admin

from .models import (Building, Cohort, Course, CourseGroup, CourseProgram, Department, Faculty,
                     Lecturer, Period, Room, Semester, TeachingQualification)
from .models import Program

admin.site.index_template = "school/admin_index.html"


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "faculty")
    list_filter = ("faculty",)


@admin.register(Lecturer)
class LecturerAdmin(admin.ModelAdmin):
    list_display = ("employee_code", "name", "department", "status")
    search_fields = ("employee_code", "name", "email")
    list_filter = ("department", "status")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.scheduleentry_set.filter(status="DaDuyet").exists():
            return ("status",)
        return ()


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "credits", "kind", "department")
    search_fields = ("code", "name")


@admin.register(TeachingQualification)
class TeachingQualificationAdmin(admin.ModelAdmin):
    list_display = ("lecturer", "course", "priority")

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
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_year", "week_count", "status")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.coursegroup_set.filter(scheduleentry__isnull=False).exists():
            return ("week_count", "start_date", "end_date")
        return ()


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "cycle", "faculty")
    search_fields = ("code", "name")


@admin.register(CourseProgram)
class CourseProgramAdmin(admin.ModelAdmin):
    list_display = ("course", "program", "requirement")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "capacity", "status")
    search_fields = ("code", "name")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.scheduleentry_set.filter(status="DaDuyet").exists():
            return ("status",)
        return ()


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ("id", "block", "start_time", "end_time")


@admin.register(CourseGroup)
class CourseGroupAdmin(admin.ModelAdmin):
    list_display = ("code", "course", "semester", "group", "lab_group", "capacity")
    list_filter = ("semester",)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.scheduleentry_set.exists():
            return ("course", "semester", "code", "group", "lab_group", "needs_room")
        return ()


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ("name", "semester")
