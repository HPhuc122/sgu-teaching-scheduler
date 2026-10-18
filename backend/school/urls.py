from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("teaching-quotas", views.TeachingQuotaViewSet)
router.register("workload-policies", views.WorkloadPolicyViewSet)
router.register("conversion-rules", views.ConversionRuleViewSet)
router.register("faculties", views.FacultyViewSet)
router.register("departments", views.DepartmentViewSet)
router.register("lecturers", views.LecturerViewSet)
router.register("courses", views.CourseViewSet)
router.register("programs", views.ProgramViewSet)
router.register("course-programs", views.CourseProgramViewSet)
router.register("qualifications", views.TeachingQualificationViewSet)
router.register("semesters", views.SemesterViewSet)
router.register("buildings", views.BuildingViewSet)
router.register("rooms", views.RoomViewSet)
router.register("periods", views.PeriodViewSet)
router.register("course-groups", views.CourseGroupViewSet)
router.register("cohorts", views.CohortViewSet)
router.register("group-cohorts", views.GroupCohortViewSet)
router.register("schedules", views.ScheduleEntryViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("me/", views.my_profile),
    path("me/schedule/", views.my_schedule),
    path("me/preferences/", views.my_preferences),
]
