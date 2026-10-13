from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from school import views as school_views
from school import review_views
from school import export_views
from school import faculty_timetable
from school import auto_schedule_views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="school/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("portal/", school_views.portal, name="portal"),
    path("portal/preferences/", school_views.submit_preference, name="submit_preference"),
    path("admin/import-schedule/", school_views.import_schedule, name="import_schedule"),
    path("admin/import-schedule/template/", school_views.import_schedule_template, name="import_schedule_template"),
    path("admin/import-catalog/<str:kind>/", school_views.import_catalog, name="import_catalog"),
    path("admin/import-catalog/<str:kind>/template/", school_views.import_catalog_template, name="import_catalog_template"),
    path("admin/review-schedules/", review_views.review_schedules, name="review_schedules"),
    path("admin/review-schedules/<int:entry_id>/edit/", review_views.edit_schedule, name="edit_schedule"),
    path("admin/export-assignments/", export_views.export_assignments, name="export_assignments"),
    path("admin/faculty-timetable/", faculty_timetable.faculty_timetable, name="faculty_timetable"),
    path("admin/auto-schedule/", auto_schedule_views.auto_schedule, name="auto_schedule"),
    path("admin/auto-schedule/template/<str:kind>/", auto_schedule_views.auto_template, name="auto_template"),
    path("admin/", admin.site.urls),
    path("api/", include("school.urls")),
]
