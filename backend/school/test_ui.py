"""Regression checks for shared templates, navigation permissions and Admin writes."""

from datetime import date, time

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase
from django.urls import reverse

from .models import (Building, Cohort, Course, CourseGroup, CourseProgram, Department,
                     Faculty, Lecturer, Period, Program, Room, ScheduleEntry, Semester,
                     TeachingQualification)


class SharedInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin_user = users.objects.create_superuser("ui_admin", "", "test-password-only")
        cls.staff = users.objects.create_user("ui_viewer", is_staff=True)
        cls.staff.user_permissions.add(Permission.objects.get(codename="view_lecturer"))
        cls.teacher_user = users.objects.create_user("ui_teacher")
        cls.faculty = Faculty.objects.create(code="QA", name="Khoa kiểm thử giao diện")
        cls.department = Department.objects.create(code="QA_DM", name="Bộ môn kiểm thử", faculty=cls.faculty)
        cls.lecturer = Lecturer.objects.create(name="Giảng viên kiểm thử", department=cls.department,
                                               employee_code="QA_001", user=cls.teacher_user)
        cls.semester = Semester.objects.create(name="Học kỳ kiểm thử", academic_year="2026-2027",
                                               start_date=date(2026, 9, 1), end_date=date(2027, 1, 31), week_count=18)
        cls.building = Building.objects.create(code="QA_A", name="Tòa nhà kiểm thử")
        cls.room = Room.objects.create(code="QA_A101", name="Phòng kiểm thử", building=cls.building, capacity=50)
        cls.course = Course.objects.create(code="QA_HP", name="Học phần kiểm thử", department=cls.department, credits=3)
        cls.group = CourseGroup.objects.create(code="QA_01", group="01", course=cls.course,
                                               semester=cls.semester, capacity=40)
        cls.period = Period.objects.create(id=1, block="Sang", start_time=time(7), end_time=time(7, 50))
        cls.program = Program.objects.create(code="QA_CT", name="Chương trình kiểm thử", cycle="2026", faculty=cls.faculty)
        cls.course_program = CourseProgram.objects.create(course=cls.course, program=cls.program, requirement="BAT_BUOC")
        cls.qualification = TeachingQualification.objects.create(lecturer=cls.lecturer, course=cls.course)
        cls.cohort = Cohort.objects.create(name="QA_LOP", semester=cls.semester)
        cls.entry = ScheduleEntry.objects.create(group=cls.group, lecturer=cls.lecturer, room=cls.room,
                                                 day=2, start_period=cls.period, period_count=1)

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_every_registered_admin_list_add_change_history_delete_renders(self):
        records = [self.faculty, self.department, self.lecturer, self.course, self.group,
                   self.semester, self.building, self.room, self.period, self.program,
                   self.course_program, self.qualification, self.cohort, self.admin_user,
                   Group.objects.create(name="Nhóm kiểm thử")]
        for obj in records:
            name = f"admin:{obj._meta.app_label}_{obj._meta.model_name}"
            for view in ("changelist", "add", "change", "history", "delete"):
                with self.subTest(model=obj._meta.model_name, view=view):
                    url = reverse(f"{name}_{view}", args=[obj.pk] if view in ("change", "history", "delete") else [])
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'school/css/admin.css')
                    self.assertContains(response, 'id="uiSidebar"')

    def test_all_custom_screens_render_shared_shell(self):
        query = f"?semester={self.semester.pk}&faculty={self.faculty.pk}"
        urls = ["/admin/", "/admin/school/", "/admin/auth/", "/admin/password_change/",
                "/admin/password_change/done/", "/admin/auto-schedule/",
                "/admin/review-schedules/" + query, "/admin/faculty-timetable/" + query,
                "/admin/export-assignments/" + query, "/admin/import-schedule/",
                f"/admin/review-schedules/{self.entry.pk}/edit/",
                *[f"/admin/import-catalog/{kind}/" for kind in ("courses", "rooms", "lecturers")]]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="uiSidebar"')
                self.assertContains(response, 'school/css/ui.css')

    def test_model_navigation_obeys_view_permissions_and_dashboard_reads_real_counts(self):
        self.client.force_login(self.staff)
        response = self.client.get('/admin/')
        sidebar = response.content.decode().split('<aside', 1)[1].split('</aside>', 1)[0]
        self.assertIn(reverse('admin:school_lecturer_changelist'), sidebar)
        self.assertNotIn(reverse('admin:school_room_changelist'), sidebar)
        self.assertNotIn(reverse('admin:auth_user_changelist'), sidebar)
        self.assertContains(response, 'Giảng viên')
        self.assertNotContains(response, 'href="/admin/school/room/"')
        from .templatetags.school_ui import dashboard_data
        stats = dashboard_data({'request': response.wsgi_request})['stats']
        self.assertEqual([(item['label'], item['count']) for item in stats], [('Giảng viên', 1)])
        self.assertEqual(self.client.get('/admin/school/room/').status_code, 403)

    def test_staff_without_model_access_sees_no_model_links(self):
        user = get_user_model().objects.create_user('no_models', is_staff=True)
        self.client.force_login(user)
        response = self.client.get('/admin/')
        self.assertContains(response, 'Chưa có danh mục được cấp quyền')
        self.assertNotContains(response, 'href="/admin/auth/user/"')

    def test_add_only_navigation_links_to_the_allowed_form(self):
        user = get_user_model().objects.create_user('add_only', is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='add_building'))
        self.client.force_login(user)
        response = self.client.get('/admin/')
        sidebar = response.content.decode().split('<aside', 1)[1].split('</aside>', 1)[0]
        self.assertIn(reverse('admin:school_building_add'), sidebar)
        self.assertNotIn('href="' + reverse('admin:school_building_changelist') + '"', sidebar)
        self.assertEqual(self.client.get(reverse('admin:school_building_add')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:school_building_changelist')).status_code, 403)

    def test_admin_create_edit_and_delete_confirmation_remain_functional(self):
        url = reverse('admin:school_building_add')
        response = self.client.post(url, {'code': 'QA_B', 'name': 'Tòa mới', '_save': 'Lưu'})
        self.assertEqual(response.status_code, 302)
        building = Building.objects.get(code='QA_B')
        response = self.client.post(reverse('admin:school_building_change', args=[building.pk]),
                                    {'code': 'QA_B', 'name': 'Tòa đã sửa', '_save': 'Lưu'})
        self.assertEqual(response.status_code, 302)
        building.refresh_from_db()
        self.assertEqual(building.name, 'Tòa đã sửa')
        delete_url = reverse('admin:school_building_delete', args=[building.pk])
        self.assertContains(self.client.get(delete_url), 'name="post"')
        self.assertTrue(Building.objects.filter(pk=building.pk).exists())
        self.assertEqual(self.client.post(delete_url, {'post': 'yes'}).status_code, 302)
        self.assertFalse(Building.objects.filter(pk=building.pk).exists())

    def test_readable_code_widgets_preserve_legacy_values_and_readonly_fields(self):
        self.room.status = 'LegacyRoomStatus'
        self.room.save(update_fields=['status'])
        response = self.client.get(reverse('admin:school_room_change', args=[self.room.pk]))
        self.assertContains(response, '<option value="SanSang">Sẵn sàng</option>', html=True)
        self.assertContains(response, '<option value="LegacyRoomStatus" selected>LegacyRoomStatus</option>', html=True)
        self.assertEqual(response.context['adminform'].form.fields['status'].clean('LegacyRoomStatus'), 'LegacyRoomStatus')
        self.entry.status = 'DaDuyet'
        self.entry.save(update_fields=['status'])
        response = self.client.get(reverse('admin:school_lecturer_change', args=[self.lecturer.pk]))
        self.assertContains(response, '<label>Trạng thái:</label>', html=True)
        self.assertContains(response, '<div class="readonly">Đang công tác</div>', html=True)

    def test_permission_widget_preserves_explicit_selection_without_extra_grants(self):
        permission = Permission.objects.get(codename='view_lecturer')
        url = reverse('admin:auth_group_add')
        page = self.client.get(url)
        self.assertContains(page, 'class="selectfilter"')
        response = self.client.post(url, {'name': 'Chỉ xem giảng viên', 'permissions': [permission.pk], '_save': 'Lưu'})
        self.assertEqual(response.status_code, 302)
        group = Group.objects.get(name='Chỉ xem giảng viên')
        self.assertEqual(list(group.permissions.values_list('pk', flat=True)), [permission.pk])

    def test_authentication_csrf_and_teacher_scope(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin_user)
        self.assertEqual(csrf_client.post('/admin/school/building/add/', {'code': 'CSRF', 'name': 'No token'}).status_code, 403)
        self.assertEqual(csrf_client.get('/logout/').status_code, 405)
        self.client.logout()
        for url in ['/login/', '/admin/login/']:
            response = self.client.get(url)
            self.assertContains(response, 'Đăng nhập hệ thống')
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.client.force_login(self.teacher_user)
        response = self.client.get('/portal/')
        self.assertContains(response, 'Thời khóa biểu của tôi')
        self.assertNotContains(response, 'href="/admin/auto-schedule/"')
        self.assertEqual(self.client.get('/admin/auto-schedule/').status_code, 302)

    def test_popup_does_not_render_duplicate_shell(self):
        response = self.client.get('/admin/school/lecturer/add/?_popup=1')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="uiSidebar"')

    def test_portal_preselects_semester_and_uses_field_labels_in_errors(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(f'/portal/?semester={self.semester.pk}')
        self.assertEqual(response.context['form'].initial['semester'], str(self.semester.pk))
        response = self.client.post('/portal/preferences/', {
            'semester': self.semester.pk, 'kind': 'KhungGio', 'priority': 2,
        }, follow=True)
        self.assertContains(response, 'Buổi: Cần chọn buổi ưu tiên')

    def test_unlinked_profile_and_admin_logout_render_consistent_pages(self):
        user = get_user_model().objects.create_user('unlinked')
        self.client.force_login(user)
        response = self.client.get('/portal/')
        self.assertContains(response, 'Chưa liên kết hồ sơ giảng viên', status_code=403)
        self.assertContains(response, 'school/css/ui.css', status_code=403)
        self.client.force_login(self.admin_user)
        response = self.client.post('/admin/logout/')
        self.assertContains(response, 'Đã đăng xuất')
        self.assertContains(response, 'auth-page')
        self.assertNotContains(response, 'id="uiSidebar"')
