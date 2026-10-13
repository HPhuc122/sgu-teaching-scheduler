from datetime import date, time
from io import BytesIO, StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook, load_workbook
from ortools.sat.python import cp_model
from rest_framework.test import APIClient

from .models import (AlgorithmRun, Building, Cohort, Course, CourseGroup, CourseProgram, Department, Faculty,
                     Lecturer, LecturerPreference, Period, Program, Room, ScheduleEntry, ScheduleRunQueue,
                     Semester, TeachingQualification)
from .schedule_import import HEADERS
from .catalog_import import SHEETS
from .auto_schedule import AUTO_SHEETS, read_auto_workbook
from .great_deluge import improve
from .schedule_queue import process_next_run
from .sample_data import synthetic_rows, workbook_bytes
from .schedule_diagnostics import forced_day_overloads
from .solution_audit import audit_solution
from .preference_report import preference_report


class ScheduleApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.admin = user_model.objects.create_user("admin", password="safe-test-password", is_staff=True)
        cls.teacher_user = user_model.objects.create_user("teacher", password="safe-test-password")
        faculty = Faculty.objects.create(code="CNTT", name="Công nghệ thông tin")
        department = Department.objects.create(faculty=faculty, code="KHMT", name="Khoa học máy tính")
        cls.teacher = Lecturer.objects.create(department=department, user=cls.teacher_user,
                                              employee_code="10001", name="Giảng viên A", email="a@example.edu")
        cls.other_teacher = Lecturer.objects.create(department=department, employee_code="10002",
                                                    name="Giảng viên B", email="b@example.edu")
        course = Course.objects.create(department=department, code="841021", name="Kiến trúc máy tính", credits=3)
        TeachingQualification.objects.create(lecturer=cls.teacher, course=course)
        TeachingQualification.objects.create(lecturer=cls.other_teacher, course=course)
        cls.semester = Semester.objects.create(name="HK1 2026-2027", academic_year="2026-2027",
                                               start_date=date(2026, 9, 1), end_date=date(2027, 1, 31),
                                               week_count=19)
        cls.group1 = CourseGroup.objects.create(course=course, semester=cls.semester, code="841021.01",
                                                group="01", capacity=50, needs_room=True)
        cls.group2 = CourseGroup.objects.create(course=course, semester=cls.semester, code="841021.02",
                                                group="02", capacity=50, needs_room=True)
        building = Building.objects.create(code="C", name="C")
        cls.room = Room.objects.create(building=building, code="C.A302", name="A302", capacity=60)
        for number in range(1, 14):
            Period.objects.create(id=number, block="Sang" if number <= 5 else "Chieu",
                                  start_time=time(7, 0), end_time=time(7, 50))

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def payload(self, group, teacher, weeks):
        return {"group": group.pk, "lecturer": teacher.pk, "room": self.room.pk,
                "day": 2, "start_period": 1, "period_count": 3,
                "status": "DaDuyet", "weeks": weeks}

    def test_forced_day_overload_is_proven_only_for_fixed_day(self):
        demands = [{"group": self.group1, "count": 5, "weeks": frozenset({1}),
                    "days": frozenset({2})} for _ in range(3)]
        overloads = forced_day_overloads(self.semester, demands)
        self.assertEqual(set(overloads), {0, 1, 2})
        self.assertEqual(overloads[0][3:], (15, 13))
        demands[2]["days"] = frozenset({2, 3})
        self.assertEqual(forced_day_overloads(self.semester, demands), {})

    def test_admin_creates_schedule_and_blocks_shared_room_week(self):
        first = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1, 2]), format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post("/api/schedules/", self.payload(self.group2, self.other_teacher, [2, 3]), format="json")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data["conflicts"][0]["kind"], "PHONG")
        self.assertEqual(second.data["conflicts"][0]["weeks"], [2])

    def test_disjoint_weeks_allowed_and_invalid_week_rejected(self):
        self.assertEqual(self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]),
                                          format="json").status_code, 201)
        second = self.client.post("/api/schedules/", self.payload(self.group2, self.other_teacher, [2]),
                                  format="json")
        self.assertEqual(second.status_code, 201, second.data)
        invalid = self.client.post("/api/schedules/", self.payload(self.group2, self.other_teacher, [20]),
                                   format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_teacher_sees_only_own_approved_schedule_and_can_submit_preference(self):
        self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        self.client.force_authenticate(user=self.teacher_user)
        self.assertEqual(self.client.get("/api/schedules/").status_code, 403)
        mine = self.client.get("/api/me/schedule/")
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(len(mine.data), 1)
        self.assertEqual(mine.data[0]["week_numbers"], [1])
        preference = self.client.post("/api/me/preferences/", {
            "semester": self.semester.pk, "kind": "KhungGio", "day": 3,
            "time_block": "Sang", "priority": 1, "note": "Ưu tiên buổi sáng"
        }, format="json")
        self.assertEqual(preference.status_code, 201, preference.data)
        self.assertEqual(len(self.client.get("/api/me/preferences/").data), 1)

    def test_anonymous_cannot_read_private_schedule(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get("/api/me/schedule/").status_code, (401, 403))

    def test_update_checks_conflict_and_keeps_existing_weeks(self):
        first = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        second = self.client.post("/api/schedules/", self.payload(self.group2, self.other_teacher, [2]), format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        conflict = self.client.patch(f"/api/schedules/{second.data['id']}/", {"weeks": [1]}, format="json")
        self.assertEqual(conflict.status_code, 409)
        saved = self.client.get(f"/api/schedules/{second.data['id']}/")
        self.assertEqual(saved.data["week_numbers"], [2])
        changed = self.client.patch(f"/api/schedules/{second.data['id']}/", {"period_count": 2}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["week_numbers"], [2])

    def test_locked_semester_rejects_new_schedule(self):
        self.semester.status = "DaKhoa"
        self.semester.save(update_fields=["status"])
        result = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        self.assertEqual(result.status_code, 400)

    def test_teacher_without_qualification_is_rejected(self):
        TeachingQualification.objects.filter(lecturer=self.teacher).delete()
        result = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        self.assertEqual(result.status_code, 400)
        self.assertIn("chuyên môn", str(result.data))

    def test_lecturer_portal_login_and_preference_form(self):
        self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/portal/").status_code, 302)
        self.client.force_login(self.teacher_user)
        page = self.client.get(f"/portal/?semester={self.semester.pk}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Kiến trúc máy tính")
        posted = self.client.post("/portal/preferences/", {
            "semester": self.semester.pk, "kind": "KhungGio", "day": "3",
            "time_block": "Sang", "priority": "1", "note": "Ưu tiên sáng"
        })
        self.assertEqual(posted.status_code, 302)
        self.assertContains(self.client.get(f"/portal/?semester={self.semester.pk}"), "Ưu tiên sáng")

    def test_review_explains_preference_outcomes_for_selected_run(self):
        run = AlgorithmRun.objects.create(semester=self.semester, created_by=self.admin,
                                          status="FEASIBLE")
        ScheduleEntry.objects.create(group=self.group1, lecturer=self.teacher, room=self.room,
                                     day=2, start_period_id=1, period_count=2,
                                     algorithm_run=run, status="ChoDuyet")
        ScheduleEntry.objects.create(group=self.group2, lecturer=self.teacher, room=self.room,
                                     day=3, start_period_id=6, period_count=2,
                                     status="ChoDuyet")
        preferred = LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="KhungGio",
            time_block="Sang", priority=1)
        LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="KhungGio",
            day=2, time_block="Sang", priority=4)
        LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="NgayNghi", day=2)
        LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="NgayNghi", day=4)
        LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="KhungGio",
            day=5, time_block="Sang", priority=1)
        LecturerPreference.objects.create(
            lecturer=self.other_teacher, semester=self.semester, kind="NgayNghi", day=2)
        whole = preference_report(self.semester)
        self.assertEqual(next(row for row in whole["rows"] if row["preference"].pk == preferred.pk)
                         ["status"], "partial")
        selected = preference_report(self.semester, run_id=run.pk)
        self.assertEqual(next(row for row in selected["rows"] if row["preference"].pk == preferred.pk)
                         ["status"], "met")
        self.assertEqual(selected["totals"], {"met": 2, "partial": 0, "unmet": 2,
                                               "unassessed": 2, "hard_unmet": 1})
        self.client.force_login(self.admin)
        response = self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}&run={run.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mức đáp ứng nguyện vọng giảng viên")
        self.assertContains(response, "trùng lịch trong phạm vi đang xem")
        self.assertContains(response, "Chưa đáp ứng")
        self.assertLess(response.content.index("Mức đáp ứng nguyện vọng".encode()),
                        response.content.index("Duyệt các buổi".encode()))

    def excel_file(self, *rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(HEADERS)
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return SimpleUploadedFile("lich.xlsx", output.getvalue(),
                                  content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_excel_preview_then_confirm(self):
        self.client.force_login(self.admin)
        row = ("841021", "01", "", self.teacher.employee_code, self.room.code, 2, 1, 3, "1-3,5", "")
        preview = self.client.post("/admin/import-schedule/", {
            "action": "preview", "semester": str(self.semester.pk), "file": self.excel_file(row)
        })
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Xác nhận nhập 1 dòng")
        self.assertEqual(ScheduleEntry.objects.count(), 0)
        saved = self.client.post("/admin/import-schedule/", {
            "action": "confirm", "semester": str(self.semester.pk)
        })
        self.assertEqual(saved.status_code, 302)
        entry = ScheduleEntry.objects.get()
        self.assertEqual(entry.status, "ChoDuyet")
        self.assertEqual(entry.source, "Excel")
        self.assertEqual(sorted(entry.schedule_weeks.values_list("week", flat=True)), [1, 2, 3, 5])
        self.assertEqual(self.client.post("/admin/import-schedule/", {
            "action": "confirm", "semester": str(self.semester.pk)
        }).status_code, 400)

    def test_excel_conflict_in_file_blocks_whole_batch(self):
        self.client.force_login(self.admin)
        row1 = ("841021", "01", "", self.teacher.employee_code, self.room.code, 2, 1, 3, "1-3", "")
        row2 = ("841021", "02", "", self.other_teacher.employee_code, self.room.code, 2, 1, 3, "2-4", "")
        preview = self.client.post("/admin/import-schedule/", {
            "action": "preview", "semester": str(self.semester.pk), "file": self.excel_file(row1, row2)
        })
        self.assertEqual(preview.status_code, 400)
        self.assertContains(preview, "Dòng 3: Trùng PHONG", status_code=400)
        self.assertEqual(ScheduleEntry.objects.count(), 0)
        confirm = self.client.post("/admin/import-schedule/", {
            "action": "confirm", "semester": str(self.semester.pk)
        })
        self.assertEqual(confirm.status_code, 400)
        self.assertEqual(ScheduleEntry.objects.count(), 0)

    def test_excel_rechecks_after_preview(self):
        self.client.force_login(self.admin)
        row = ("841021", "01", "", self.teacher.employee_code, self.room.code, 2, 1, 3, "1", "")
        preview = self.client.post("/admin/import-schedule/", {
            "action": "preview", "semester": str(self.semester.pk), "file": self.excel_file(row)
        })
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(self.client.post("/api/schedules/", self.payload(self.group2, self.other_teacher, [1]),
                                          format="json").status_code, 201)
        confirm = self.client.post("/admin/import-schedule/", {
            "action": "confirm", "semester": str(self.semester.pk)
        })
        self.assertContains(confirm, "Trùng PHONG", status_code=400)
        self.assertEqual(ScheduleEntry.objects.count(), 1)

    def test_excel_import_requires_admin(self):
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        self.assertNotEqual(self.client.get("/admin/import-schedule/").status_code, 200)
        self.assertNotEqual(self.client.get("/admin/import-schedule/template/").status_code, 200)

    def test_admin_has_import_link_and_template_download(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/admin/"), "Tải ba file Excel và tạo phương án")
        response = self.client.get("/admin/import-schedule/template/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:2], b"PK")

    def catalog_file(self, kind, rows_by_sheet):
        workbook = Workbook()
        workbook.remove(workbook.active)
        for name, headers in SHEETS[kind].items():
            sheet = workbook.create_sheet(name)
            sheet.append(headers)
            for row in rows_by_sheet.get(name, []):
                sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return SimpleUploadedFile(f"{kind}.xlsx", output.getvalue())

    def import_catalog(self, kind, rows_by_sheet, semester=None):
        self.client.force_login(self.admin)
        url = f"/admin/import-catalog/{kind}/"
        payload = {"action": "preview", "file": self.catalog_file(kind, rows_by_sheet)}
        if semester:
            payload["semester"] = str(semester.pk)
        preview = self.client.post(url, payload)
        if preview.status_code != 200:
            return preview, None
        confirm_payload = {"action": "confirm"}
        if semester:
            confirm_payload["semester"] = str(semester.pk)
        return preview, self.client.post(url, confirm_payload)

    def test_three_catalog_workbooks_import_and_repeat_safely(self):
        course_data = {
            "ChuongTrinh": [("DCT", "Công nghệ thông tin", "CNTT", "2024-2028")],
            "HocPhan": [("841099", "Dữ liệu lớn", 3, "KHMT", "CHUYEN_NGANH")],
            "HocPhanChuongTrinh": [("841099", "DCT", "2024-2028", "BAT_BUOC")],
            "NhomHocPhan": [("841099", self.semester.name, "01", "", 45, "DCT1261;DKP1261")],
        }
        preview, saved = self.import_catalog("courses", course_data, self.semester)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(saved.status_code, 302)
        course = Course.objects.get(code="841099")
        self.assertEqual(CourseProgram.objects.get(course=course).program.code, "DCT")
        group = CourseGroup.objects.get(course=course, semester=self.semester)
        self.assertEqual(group.cohort_links.count(), 2)
        self.assertEqual(Cohort.objects.filter(semester=self.semester).count(), 2)
        _, repeated = self.import_catalog("courses", course_data, self.semester)
        self.assertEqual(repeated.status_code, 302)
        self.assertEqual(CourseGroup.objects.filter(course=course, semester=self.semester).count(), 1)
        self.assertEqual(Program.objects.filter(code="DCT", cycle="2024-2028").count(), 1)

        room_data = {"PhongHoc": [("C.B201", "C", "C", "B201", 55, "LyThuyet", "SanSang")]}
        _, saved_room = self.import_catalog("rooms", room_data)
        self.assertEqual(saved_room.status_code, 302)
        self.assertEqual(Room.objects.get(code="C.B201").capacity, 55)
        _, repeated_room = self.import_catalog("rooms", room_data)
        self.assertEqual(repeated_room.status_code, 302)
        self.assertEqual(Room.objects.filter(code="C.B201").count(), 1)

        lecturer_data = {"GiangVien": [("54321", "Giảng viên C", "", "CNTT", "KHMT", "DangCongTac")],
                         "GiangVienHocPhan": [("54321", "841099")]}
        _, saved_lecturer = self.import_catalog("lecturers", lecturer_data)
        self.assertEqual(saved_lecturer.status_code, 302)
        teacher = Lecturer.objects.get(employee_code="54321")
        self.assertTrue(TeachingQualification.objects.filter(lecturer=teacher, course=course).exists())
        self.assertIsNone(teacher.email)
        _, repeated_lecturer = self.import_catalog("lecturers", lecturer_data)
        self.assertEqual(repeated_lecturer.status_code, 302)
        self.assertEqual(Lecturer.objects.filter(employee_code="54321").count(), 1)
        self.assertEqual(TeachingQualification.objects.filter(lecturer=teacher, course=course).count(), 1)

        row = ("841099", "01", "", "54321", "C.B201", 3, 1, 3, "1-2", "")
        schedule_preview = self.client.post("/admin/import-schedule/", {
            "action": "preview", "semester": str(self.semester.pk), "file": self.excel_file(row)
        })
        self.assertEqual(schedule_preview.status_code, 200)
        self.assertEqual(self.client.post("/admin/import-schedule/", {
            "action": "confirm", "semester": str(self.semester.pk)
        }).status_code, 302)

    def test_catalog_preview_blocks_invalid_relationship_without_writes(self):
        data = {"ChuongTrinh": [("DCT", "Công nghệ thông tin", "KHONG_CO", "2024-2028")],
                "HocPhan": [("841099", "Dữ liệu lớn", 3, "KHMT", "CHUYEN_NGANH")],
                "HocPhanChuongTrinh": [("841099", "DCT", "2024-2028", "BAT_BUOC")],
                "NhomHocPhan": [("841099", self.semester.name, "01", "", 45, "DCT1261")]}
        preview, saved = self.import_catalog("courses", data, self.semester)
        self.assertIsNone(saved)
        self.assertContains(preview, "Mã khoa chưa có", status_code=400)
        self.assertFalse(Course.objects.filter(code="841099").exists())
        confirm = self.client.post("/admin/import-catalog/courses/", {
            "action": "confirm", "semester": str(self.semester.pk)
        })
        self.assertEqual(confirm.status_code, 400)
        self.assertFalse(Program.objects.filter(code="DCT").exists())

    def test_catalog_import_and_templates_require_admin(self):
        self.client.force_login(self.teacher_user)
        for kind in SHEETS:
            self.assertNotEqual(self.client.get(f"/admin/import-catalog/{kind}/").status_code, 200)
            self.assertNotEqual(self.client.get(f"/admin/import-catalog/{kind}/template/").status_code, 200)

    def test_catalog_confirm_rechecks_locked_semester(self):
        data = {"HocPhan": [("841099", "Dữ liệu lớn", 3, "KHMT", "CHUYEN_NGANH")]}
        self.client.force_login(self.admin)
        preview = self.client.post("/admin/import-catalog/courses/", {
            "action": "preview", "semester": str(self.semester.pk),
            "file": self.catalog_file("courses", data),
        })
        self.assertEqual(preview.status_code, 200)
        self.semester.status = "DaKhoa"
        self.semester.save(update_fields=["status"])
        confirm = self.client.post("/admin/import-catalog/courses/", {
            "action": "confirm", "semester": str(self.semester.pk)
        })
        self.assertContains(confirm, "Học kỳ đã khóa", status_code=400)
        self.assertFalse(Course.objects.filter(code="841099").exists())

    def test_catalog_rejects_numeric_code_cells(self):
        self.client.force_login(self.admin)
        preview = self.client.post("/admin/import-catalog/rooms/", {
            "action": "preview", "file": self.catalog_file("rooms", {
                "PhongHoc": [(123, "C", "C", "B201", 55, "LyThuyet", "SanSang")],
            }),
        })
        self.assertContains(preview, "phải đặt định dạng văn bản", status_code=400)
        self.assertFalse(Room.objects.filter(code="123").exists())

    def test_review_screen_approves_pending_and_records_actor(self):
        payload = self.payload(self.group1, self.teacher, [1, 2])
        payload["status"] = "ChoDuyet"
        created = self.client.post("/api/schedules/", payload, format="json")
        self.assertEqual(created.status_code, 201)
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        self.assertEqual(len(self.client.get("/api/me/schedule/").data), 0)
        self.client.force_login(self.admin)
        page = self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}&status=ChoDuyet")
        self.assertContains(page, "Kiến trúc máy tính")
        approved = self.client.post("/admin/review-schedules/", {
            "action": "approve", "semester": str(self.semester.pk), "entry_ids": [str(created.data["id"])],
        })
        self.assertEqual(approved.status_code, 302)
        entry = ScheduleEntry.objects.get(pk=created.data["id"])
        self.assertEqual(entry.status, "DaDuyet")
        self.assertEqual(entry.approved_by, self.admin)
        self.assertIsNotNone(entry.approved_at)
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        self.assertEqual(len(self.client.get("/api/me/schedule/").data), 1)

    def test_bulk_approval_is_atomic_when_one_entry_becomes_invalid(self):
        first_payload = self.payload(self.group1, self.teacher, [1])
        first_payload["status"] = "ChoDuyet"
        second_payload = self.payload(self.group2, self.other_teacher, [2])
        second_payload["status"] = "ChoDuyet"
        first = self.client.post("/api/schedules/", first_payload, format="json")
        second = self.client.post("/api/schedules/", second_payload, format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.other_teacher.status = "NgungCongTac"
        self.other_teacher.save(update_fields=["status"])
        self.client.force_login(self.admin)
        response = self.client.post("/admin/review-schedules/", {
            "action": "approve", "semester": str(self.semester.pk),
            "entry_ids": [str(first.data["id"]), str(second.data["id"])],
        })
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "dữ liệu chưa được thay đổi", status_code=400)
        self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 0)
        self.assertEqual(ScheduleEntry.objects.filter(approved_at__isnull=False).count(), 0)

    def test_day_off_blocks_direct_and_selected_approval_until_schedule_is_fixed(self):
        LecturerPreference.objects.create(lecturer=self.teacher, semester=self.semester,
                                          kind="NgayNghi", day=2)
        direct = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]),
                                  format="json")
        self.assertEqual(direct.status_code, 400)
        self.assertIn("không thể dạy", str(direct.data))
        self.assertFalse(ScheduleEntry.objects.exists())

        first_payload = self.payload(self.group1, self.teacher, [1])
        first_payload["status"] = "ChoDuyet"
        first = self.client.post("/api/schedules/", first_payload, format="json")
        second_payload = self.payload(self.group2, self.other_teacher, [1])
        second_payload.update({"status": "ChoDuyet", "day": 3})
        second = self.client.post("/api/schedules/", second_payload, format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        direct_update = self.client.patch(f"/api/schedules/{first.data['id']}/",
                                          {"status": "DaDuyet"}, format="json")
        self.assertEqual(direct_update.status_code, 400)
        self.client.force_login(self.admin)
        blocked = self.client.post("/admin/review-schedules/", {
            "action": "approve", "semester": str(self.semester.pk),
            "entry_ids": [str(first.data["id"]), str(second.data["id"])],
        })
        self.assertContains(blocked, f"Buổi #{first.data['id']}", status_code=400)
        self.assertContains(blocked, "Các buổi cần sửa", status_code=400)
        self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 0)
        self.assertEqual(ScheduleEntry.objects.filter(approved_at__isnull=False).count(), 0)

        fixed = self.client.post(f"/admin/review-schedules/{first.data['id']}/edit/", {
            "lecturer": str(self.teacher.pk), "room": str(self.room.pk), "other_location": "",
            "day": "4", "start_period": "1", "period_count": "3", "weeks": "1",
        })
        self.assertEqual(fixed.status_code, 302)
        approved = self.client.post("/admin/review-schedules/", {
            "action": "approve", "semester": str(self.semester.pk),
            "entry_ids": [str(first.data["id"]), str(second.data["id"])],
        })
        self.assertEqual(approved.status_code, 302)
        self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 2)

    def test_day_off_blocks_whole_run_approval(self):
        payload = self.payload(self.group1, self.teacher, [1])
        payload["status"] = "ChoDuyet"
        created = self.client.post("/api/schedules/", payload, format="json")
        self.assertEqual(created.status_code, 201)
        run = AlgorithmRun.objects.create(semester=self.semester, created_by=self.admin,
                                          status="FEASIBLE", entry_count=1)
        entry = ScheduleEntry.objects.get(pk=created.data["id"])
        entry.algorithm_run = run
        entry.save(update_fields=["algorithm_run"])
        LecturerPreference.objects.create(lecturer=self.teacher, semester=self.semester,
                                          kind="NgayNghi", day=2)
        self.client.force_login(self.admin)
        page = self.client.get(f"/admin/auto-schedule/?run={run.pk}")
        self.assertFalse(page.context["can_approve"])
        self.assertContains(page, f"#{entry.pk}")
        blocked = self.client.post("/admin/auto-schedule/", {
            "action": "approve", "run_id": str(run.pk),
        })
        self.assertContains(blocked, f"Buổi #{entry.pk}", status_code=400)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "ChoDuyet")
        self.assertIsNone(entry.approved_at)

    def test_edit_approved_schedule_returns_to_pending(self):
        created = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        self.assertEqual(created.status_code, 201)
        entry = ScheduleEntry.objects.get(pk=created.data["id"])
        self.assertEqual(entry.approved_by, self.admin)
        self.client.force_login(self.admin)
        response = self.client.post(f"/admin/review-schedules/{entry.pk}/edit/", {
            "lecturer": str(self.teacher.pk), "room": str(self.room.pk), "other_location": "",
            "day": "2", "start_period": "1", "period_count": "3", "weeks": "3-4",
        })
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "ChoDuyet")
        self.assertIsNone(entry.approved_by)
        self.assertIsNone(entry.approved_at)
        self.assertEqual(sorted(entry.schedule_weeks.values_list("week", flat=True)), [3, 4])
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        self.assertEqual(len(self.client.get("/api/me/schedule/").data), 0)

    def test_teacher_cannot_access_review_or_edit(self):
        created = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1]), format="json")
        self.client.force_login(self.teacher_user)
        self.assertNotEqual(self.client.get("/admin/review-schedules/").status_code, 200)
        self.assertNotEqual(self.client.get(f"/admin/review-schedules/{created.data['id']}/edit/").status_code, 200)

    def test_assignment_export_scopes_faculty_and_approved_entries(self):
        approved = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1, 2, 4]),
                                    format="json")
        self.assertEqual(approved.status_code, 201, approved.data)
        pending_payload = self.payload(self.group2, self.other_teacher, [5])
        pending_payload.update({"status": "ChoDuyet", "day": 3})
        pending = self.client.post("/api/schedules/", pending_payload, format="json")
        self.assertEqual(pending.status_code, 201, pending.data)
        other_faculty = Faculty.objects.create(code="TOAN", name="Khoa Toán")
        other_department = Department.objects.create(faculty=other_faculty, code="TUD", name="Toán ứng dụng")
        outside_teacher = Lecturer.objects.create(department=other_department, employee_code="20001",
                                                   name="Giảng viên khoa khác")
        TeachingQualification.objects.create(lecturer=outside_teacher, course=self.group1.course)
        outside_payload = self.payload(self.group2, outside_teacher, [6])
        outside_payload["day"] = 4
        outside = self.client.post("/api/schedules/", outside_payload, format="json")
        self.assertEqual(outside.status_code, 201, outside.data)

        self.client.force_login(self.admin)
        url = f"/admin/export-assignments/?semester={self.semester.pk}&faculty={self.teacher.department.faculty_id}"
        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.context["completeness"]["ready"])
        self.assertEqual(len(preview.context["completeness"]["unknown_groups"]), 2)
        self.assertContains(preview, "Chưa xác nhận bảng phân công hoàn chỉnh")
        self.assertContains(preview, "9</strong> tiết theo lịch")
        self.assertNotContains(preview, "Giảng viên khoa khác")
        response = self.client.get(url + "&action=download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml.sheet", response["Content-Type"])
        workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
        self.assertEqual(workbook.sheetnames, ["PhanCong", "TongHopGV", "ThongTin"])
        detail = list(workbook["PhanCong"].values)
        self.assertEqual(len(detail), 2)
        self.assertEqual(detail[1][1], "841021")
        self.assertEqual(detail[1][6], "10001")
        self.assertEqual(detail[1][14], "1,2,4")
        self.assertEqual(detail[1][15], 9)
        summary = list(workbook["TongHopGV"].values)
        self.assertEqual(summary[1][3:], (1, 9))
        self.assertIn("MẪU XUẤT ĐỀ XUẤT", workbook["ThongTin"]["A1"].value)
        workbook.close()

    def test_assignment_export_rejects_invalid_selection_and_non_staff(self):
        self.client.force_login(self.admin)
        invalid = self.client.get("/admin/export-assignments/?semester=999&faculty=999&action=download")
        self.assertEqual(invalid.status_code, 400)
        self.assertNotIn("spreadsheetml.sheet", invalid["Content-Type"])
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        forbidden = self.client.get(
            f"/admin/export-assignments/?semester={self.semester.pk}"
            f"&faculty={self.teacher.department.faculty_id}&action=download"
        )
        self.assertNotEqual(forbidden.status_code, 200)

    def test_faculty_timetable_filters_approved_schedule_by_week_and_faculty(self):
        approved = self.client.post("/api/schedules/", self.payload(self.group1, self.teacher, [1, 3]),
                                    format="json")
        self.assertEqual(approved.status_code, 201, approved.data)
        pending_payload = self.payload(self.group2, self.other_teacher, [2])
        pending_payload.update({"status": "ChoDuyet", "day": 3})
        pending = self.client.post("/api/schedules/", pending_payload, format="json")
        self.assertEqual(pending.status_code, 201, pending.data)
        other_faculty = Faculty.objects.create(code="TOAN", name="Khoa Toán")
        other_department = Department.objects.create(faculty=other_faculty, code="TUD", name="Toán ứng dụng")
        Lecturer.objects.create(department=other_department, employee_code="20001", name="Giảng viên ngoài khoa")

        self.client.force_login(self.admin)
        base = (f"/admin/faculty-timetable/?semester={self.semester.pk}"
                f"&faculty={self.teacher.department.faculty_id}&lecturer={self.teacher.pk}")
        first_week = self.client.get(base + "&week=1")
        self.assertEqual(first_week.status_code, 200)
        self.assertContains(first_week, "Kiến trúc máy tính")
        self.assertNotContains(first_week, "Giảng viên ngoài khoa")
        slots = first_week.context["timetable"][0]["rows"][0]["cells"][0]
        self.assertEqual(slots[0]["entry"].pk, approved.data["id"])
        self.assertTrue(slots[0]["is_start"])
        second_week = self.client.get(base + "&week=2")
        self.assertEqual(second_week.status_code, 200)
        self.assertFalse(any(cell for row in second_week.context["timetable"][0]["rows"]
                             for cell in row["cells"]))
        third_week = self.client.get(base + "&week=3")
        self.assertEqual(third_week.status_code, 200)
        self.assertContains(third_week, "Kiến trúc máy tính")

    def test_faculty_timetable_rejects_bad_week_cross_faculty_and_non_staff(self):
        self.client.force_login(self.admin)
        base = f"/admin/faculty-timetable/?semester={self.semester.pk}&faculty={self.teacher.department.faculty_id}"
        self.assertEqual(self.client.get(base + "&week=20").status_code, 400)
        other_faculty = Faculty.objects.create(code="TOAN", name="Khoa Toán")
        self.assertEqual(self.client.get(
            base.replace(f"faculty={self.teacher.department.faculty_id}", f"faculty={other_faculty.pk}")
            + f"&week=1&lecturer={self.teacher.pk}"
        ).status_code, 400)
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        self.assertNotEqual(self.client.get(base + "&week=1").status_code, 200)

    def auto_file(self, kind, rows_by_sheet):
        workbook = Workbook()
        workbook.remove(workbook.active)
        for name, headers in AUTO_SHEETS[kind].items():
            sheet = workbook.create_sheet(name)
            sheet.append(headers)
            for row in rows_by_sheet.get(name, []):
                sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return SimpleUploadedFile(f"auto_{kind}.xlsx", output.getvalue())

    def auto_data(self):
        return {
            "courses": {
                "Khoa": [("CNTT", "Công nghệ thông tin")],
                "BoMon": [("KHMT", "Khoa học máy tính", "CNTT")],
                "HocPhan": [("841099", "Dữ liệu lớn", 3, "KHMT", "CHUYEN_NGANH")],
                "NhomHocPhan": [("841099", self.semester.name, "01", "", 40, "DCT1261")],
                "BuoiHocYeuCau": [("841099", "01", "", "LT1", 2, "1-2", "LyThuyet", "2-3")],
            },
            "rooms": {"PhongHoc": [("C.B201", "C", "C", "B201", 50, "LyThuyet", "SanSang")],
                      "PhongKhongKhaDung": [("C.B201", 2, 1, 13, "1-2")]},
            "lecturers": {"GiangVien": [("54321", "Giảng viên C", "", "CNTT", "KHMT", "DangCongTac")],
                          "GiangVienHocPhan": [("54321", "841099")]},
        }

    def queue_auto(self, data):
        response = self.client.post("/admin/auto-schedule/", {
            "action": "run", "semester": str(self.semester.pk),
            **{kind: self.auto_file(kind, rows) for kind, rows in data.items()},
        })
        self.assertEqual(response.status_code, 302, response.content[:500])
        run = AlgorithmRun.objects.latest("pk")
        self.assertEqual(run.status, "QUEUED")
        self.assertEqual(response["Location"], f"/admin/auto-schedule/?run={run.pk}")
        return run

    def test_upload_reports_multiple_files_sheets_and_rows_before_queueing(self):
        data = self.auto_data()
        data["courses"]["Khoa"].append((123, "Khoa thử"))
        data["courses"]["BoMon"].append((456, "Bộ môn thử", "CNTT"))
        data["rooms"]["PhongHoc"].append((789, "C", "C", "P789", 40,
                                              "LyThuyet", "SanSang"))
        data["lecturers"]["GiangVien"].append((987, "Người thử", "", "CNTT",
                                                  "KHMT", "DangCongTac"))
        self.client.force_login(self.admin)
        response = self.client.post("/admin/auto-schedule/", {
            "action": "run", "semester": str(self.semester.pk),
            **{kind: self.auto_file(kind, rows) for kind, rows in data.items()},
        })
        self.assertEqual(response.status_code, 400)
        issues = response.context["input_issues"]
        self.assertEqual(len(issues), 4)
        self.assertEqual({item["file"] for item in issues},
                         {"Học phần", "Phòng học", "Giảng viên"})
        self.assertTrue(all(item["sheet"] and item["line"] for item in issues))
        self.assertEqual(AlgorithmRun.objects.count(), 0)

    def test_worker_reports_semantic_errors_in_three_files_atomically(self):
        data = self.auto_data()
        data["courses"]["BuoiHocYeuCau"][0] = (
            "841099", "01", "", "LT1", 0, "1-2", "LyThuyet", "2-3")
        data["rooms"]["PhongKhongKhaDung"].append(("C.B201", 2, "bad", 2, "1-2"))
        data["lecturers"]["GiangVienKhongKhaDung"] = [("54321", 2, 1, 20, "1-2")]
        self.client.force_login(self.admin)
        run = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "ERROR")
        run.refresh_from_db()
        self.assertEqual({item["file"] for item in run.diagnostics},
                         {"Học phần", "Phòng học", "Giảng viên"})
        self.assertEqual({item["sheet"] for item in run.diagnostics},
                         {"BuoiHocYeuCau", "PhongKhongKhaDung", "GiangVienKhongKhaDung"})
        self.assertEqual(ScheduleEntry.objects.count(), 0)
        self.assertFalse(Course.objects.filter(code="841099").exists())
        self.assertContains(self.client.get(f"/admin/auto-schedule/?run={run.pk}"),
                            "GiangVienKhongKhaDung")

    def test_worker_reports_catalog_errors_in_three_files_atomically(self):
        data = self.auto_data()
        data["courses"]["HocPhan"][0] = (
            "841099", "Dữ liệu lớn", 0, "KHMT", "CHUYEN_NGANH")
        data["rooms"]["PhongHoc"][0] = (
            "C.B201", "C", "C", "B201", 0, "LyThuyet", "SanSang")
        data["lecturers"]["GiangVien"][0] = (
            "54321", "Giảng viên C", "", "CNTT", "KHMT", "KhongHopLe")
        self.client.force_login(self.admin)
        run = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "ERROR")
        run.refresh_from_db()
        self.assertEqual({item["file"] for item in run.diagnostics},
                         {"Học phần", "Phòng học", "Giảng viên"})
        self.assertEqual(ScheduleEntry.objects.count(), 0)
        self.assertFalse(Course.objects.filter(code="841099").exists())
        self.assertFalse(Room.objects.filter(code="C.B201").exists())
        self.assertFalse(Lecturer.objects.filter(employee_code="54321").exists())

    def test_three_files_run_solver_without_schedule_input(self):
        data = self.auto_data()
        self.client.force_login(self.admin)
        run = self.queue_auto(data)
        self.assertEqual(ScheduleEntry.objects.filter(group__course__code="841099").count(), 0)
        self.assertContains(self.client.get(f"/admin/auto-schedule/?run={run.pk}"), "Đang chờ")
        output = StringIO()
        call_command("process_auto_schedule", "--once", stdout=output)
        self.assertIn(f"Run #{run.pk}", output.getvalue())
        entry = ScheduleEntry.objects.get(group__course__code="841099")
        self.assertEqual(entry.status, "ChoDuyet")
        self.assertEqual(entry.source, "ThuatToan")
        self.assertEqual(entry.day, 3)
        self.assertEqual(entry.period_count, 2)
        self.assertEqual(entry.room.code, "C.B201")
        self.assertEqual(entry.lecturer.employee_code, "54321")
        self.assertEqual(sorted(entry.schedule_weeks.values_list("week", flat=True)), [1, 2])
        self.assertEqual(entry.algorithm_run.entry_count, 1)
        self.assertEqual(entry.algorithm_run.objective_before, entry.algorithm_run.objective)
        run.refresh_from_db()
        self.assertIsNotNone(run.started_at)
        self.assertIsNotNone(run.finished_at)
        self.assertFalse(ScheduleRunQueue.objects.filter(run=run).exists())

    def test_export_checks_required_sessions_before_calling_result_complete(self):
        CourseGroup.objects.filter(pk__in=[self.group1.pk, self.group2.pk]).delete()
        self.client.force_login(self.admin)
        run = self.queue_auto(self.auto_data())
        self.assertIn(process_next_run().status, ("OPTIMAL", "FEASIBLE"))
        entry = ScheduleEntry.objects.get(algorithm_run=run)
        self.assertEqual(entry.request_code, "LT1")
        run.refresh_from_db()
        self.assertEqual(run.demand_snapshot[0]["code"], "LT1")
        url = f"/admin/export-assignments/?semester={self.semester.pk}&faculty={self.teacher.department.faculty_id}"
        pending = self.client.get(url)
        self.assertEqual(pending.status_code, 200)
        self.assertFalse(pending.context["completeness"]["ready"])
        self.assertEqual(pending.context["completeness"]["counts"]["pending"], 1)
        self.assertContains(pending, "LT1")
        partial_file = self.client.get(url + "&action=download")
        workbook = load_workbook(BytesIO(partial_file.content), read_only=True)
        self.assertIn("CHƯA XÁC NHẬN ĐẦY ĐỦ",
                      str([row for row in workbook["ThongTin"].values]))
        workbook.close()

        approved = self.client.post("/admin/auto-schedule/", {
            "action": "approve", "run_id": str(run.pk),
        })
        self.assertEqual(approved.status_code, 200)
        complete = self.client.get(url)
        self.assertTrue(complete.context["completeness"]["ready"])
        self.assertEqual(complete.context["completeness"]["counts"]["approved"], 1)

        entry.delete()
        missing = self.client.get(url)
        self.assertFalse(missing.context["completeness"]["ready"])
        self.assertEqual(missing.context["completeness"]["counts"]["missing"], 1)
        self.assertContains(missing, "Thiếu lịch")

    def test_run_snapshot_distinguishes_later_preference_changes(self):
        unchanged = LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="KhungGio",
            day=3, time_block="Sang", priority=1)
        changed = LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="KhungGio",
            day=4, time_block="Chieu", priority=2)
        removed = LecturerPreference.objects.create(
            lecturer=self.other_teacher, semester=self.semester, kind="NgayNghi", day=5)
        self.client.force_login(self.admin)
        run = self.queue_auto(self.auto_data())
        self.assertIn(process_next_run().status, ("OPTIMAL", "FEASIBLE"))
        run.refresh_from_db()
        self.assertIsNotNone(run.preferences_captured_at)
        self.assertEqual({item["id"] for item in run.preferences_snapshot},
                         {unchanged.pk, changed.pk, removed.pk})
        changed.priority = 4
        changed.save(update_fields=["priority"])
        removed.delete()
        added = LecturerPreference.objects.create(
            lecturer=self.teacher, semester=self.semester, kind="KhungGio",
            day=6, time_block="Sang", priority=1)

        page = self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}&run={run.pk}")
        self.assertEqual(page.status_code, 200)
        report = page.context["preference_report"]
        self.assertEqual(report["snapshot_totals"], {
            "unchanged": 1, "added": 1, "changed": 1, "removed": 1,
        })
        labels = {row["preference"].pk: row["snapshot_label"] for row in report["rows"]}
        self.assertEqual(labels[unchanged.pk], "Có khi chạy, chưa sửa")
        self.assertEqual(labels[changed.pk], "Đã sửa sau lần chạy")
        self.assertEqual(labels[added.pk], "Gửi sau lần chạy")
        self.assertContains(page, "Nguyện vọng đã xóa sau lần chạy")
        self.assertEqual(run.preferences_snapshot[1]["priority"], 2)

    def test_auto_schedule_can_recover_stopped_worker_run(self):
        self.client.force_login(self.admin)
        run = self.queue_auto(self.auto_data())
        AlgorithmRun.objects.filter(pk=run.pk).update(status="RUNNING")
        output = StringIO()
        call_command("process_auto_schedule", "--recover-run", str(run.pk), stdout=output)
        run.refresh_from_db()
        self.assertEqual(run.status, "QUEUED")
        self.assertIn(f"Recovered run #{run.pk}", output.getvalue())
        self.assertEqual(process_next_run().pk, run.pk)

    def test_solver_timeout_uses_valid_seed_and_allows_approval(self):
        self.client.force_login(self.admin)
        queued = self.queue_auto(self.auto_data())
        with patch("school.auto_schedule.cp_model.CpSolver.Solve", return_value=cp_model.UNKNOWN):
            run = process_next_run()
        self.assertEqual(run.status, "HEURISTIC")
        self.assertEqual(run.entry_count, 1)
        entry = ScheduleEntry.objects.get(algorithm_run=run)
        self.assertEqual(entry.day, 3)
        response = self.client.get(f"/admin/auto-schedule/?run={run.pk}")
        self.assertContains(response, "Đã xếp lịch")
        self.assertNotContains(response, "HEURISTIC")
        self.assertEqual(self.client.post("/admin/auto-schedule/", {
            "action": "approve", "run_id": str(run.pk),
        }).status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "DaDuyet")

    def test_synthetic_workbooks_are_reproducible_and_fit_import_limits(self):
        first = synthetic_rows(sessions=449, semester_name=self.semester.name, seed=42)
        second = synthetic_rows(sessions=449, semester_name=self.semester.name, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(len(first["courses"]["BuoiHocYeuCau"]), 449)
        self.assertLessEqual(sum(map(len, first["courses"].values())), 1000)
        for kind, sheets in first.items():
            content = workbook_bytes(kind, sheets)
            self.assertLessEqual(len(content), 2 * 1024 * 1024)
            parsed = read_auto_workbook(SimpleUploadedFile(f"{kind}.xlsx", content), kind)
            self.assertEqual({name: len(rows) for name, rows in parsed.items()},
                             {name: len(rows) for name, rows in sheets.items()})
        impossible = synthetic_rows(sessions=80, semester_name=self.semester.name,
                                    seed=42, scenario="infeasible")
        self.assertEqual({row[-1] for row in impossible["courses"]["BuoiHocYeuCau"][:3]}, {"2"})
        self.assertEqual({row[-1] for row in impossible["courses"]["NhomHocPhan"][:3]},
                         {"TEST_BLOCKED"})
        varied = synthetic_rows(sessions=80, semester_name=self.semester.name,
                                seed=42, scenario="varied_weeks")
        self.assertEqual(len(varied["courses"]["NhomHocPhan"]), 40)
        self.assertEqual(len(varied["courses"]["BuoiHocYeuCau"]), 80)
        self.assertGreater(len({row[5] for row in varied["courses"]["BuoiHocYeuCau"]}), 1)
        self.assertEqual({row[3] for row in varied["courses"]["BuoiHocYeuCau"]},
                         {"BUOI_1", "BUOI_2"})

    def test_auto_schedule_rejects_second_active_run_and_worker_releases_slot(self):
        data = self.auto_data()
        self.client.force_login(self.admin)
        first = self.queue_auto(data)
        duplicate = self.client.post("/admin/auto-schedule/", {
            "action": "run", "semester": str(self.semester.pk),
            **{kind: self.auto_file(kind, rows) for kind, rows in data.items()},
        })
        self.assertContains(duplicate, f"lần chạy #{first.pk}", status_code=400)
        self.assertEqual(AlgorithmRun.objects.count(), 1)
        self.assertEqual(process_next_run().pk, first.pk)
        self.assertIsNone(process_next_run())
        self.queue_auto(data)

    def test_worker_error_releases_queue_without_partial_schedule(self):
        data = self.auto_data()
        self.client.force_login(self.admin)
        queued = self.queue_auto(data)
        with (patch("school.schedule_queue.log.exception"),
              patch("school.schedule_queue.run_from_workbooks", side_effect=RuntimeError("test failure"))):
            run = process_next_run()
        self.assertEqual(run.status, "ERROR")
        self.assertFalse(ScheduleRunQueue.objects.filter(run=queued).exists())
        self.assertFalse(ScheduleEntry.objects.filter(group__course__code="841099").exists())
        self.queue_auto(data)

    def test_great_deluge_improves_preference_without_breaking_blackout(self):
        LecturerPreference.objects.create(lecturer=self.teacher, semester=self.semester,
                                          kind="KhungGio", day=2, time_block="Sang", priority=1)
        demand = {"group": self.group1, "count": 2, "weeks": frozenset({1}),
                  "days": frozenset({2}), "room_type": ""}
        initial = [(demand, 2, 6, self.room, self.teacher)]
        args = (self.semester, initial, {self.room.code: self.room},
                {self.teacher.employee_code: self.teacher}, [], [],
                {(self.teacher.employee_code, self.group1.course.code)})
        result, before, after = improve(*args, max_iterations=300, seed=3)
        self.assertEqual((before, after), (9, 1))
        self.assertIn(result[0][2], range(1, 5))
        blocked = [(self.room.code, 2, 1, 5, frozenset({1}))]
        result, before, after = improve(*args[:4], blocked, *args[5:], max_iterations=300, seed=3)
        self.assertEqual((before, after), (9, 9))
        self.assertEqual(result[0][2], 6)

    def test_final_audit_rejects_blackout_and_resource_conflict(self):
        demand = {"group": self.group1, "code": "LT1", "count": 2,
                  "weeks": frozenset({1}), "days": frozenset({2}), "room_type": ""}
        args = (self.semester, [demand], [(demand, 2, 1, self.room, self.teacher)],
                {self.room.code: self.room}, {self.teacher.employee_code: self.teacher})
        allowed = {(self.teacher.employee_code, self.group1.course.code)}
        audit_solution(*args, [], [], allowed)
        with self.assertRaisesRegex(ValueError, "phòng không khả dụng"):
            audit_solution(*args, [(self.room.code, 2, 1, 2, frozenset({1}))], [], allowed)
        second = dict(demand, group=self.group2, code="LT2")
        with self.assertRaisesRegex(ValueError, "trùng phòng"):
            audit_solution(self.semester, [demand, second],
                           [args[2][0], (second, 2, 1, self.room, self.other_teacher)],
                           {self.room.code: self.room},
                           {self.teacher.employee_code: self.teacher,
                            self.other_teacher.employee_code: self.other_teacher},
                           [], [], allowed | {(self.other_teacher.employee_code, self.group2.course.code)})

    def test_auto_schedule_avoids_same_teacher_and_room_overlap(self):
        data = self.auto_data()
        data["courses"]["NhomHocPhan"].append(("841099", self.semester.name, "02", "", 40, "DKP1261"))
        data["courses"]["BuoiHocYeuCau"] = [
            ("841099", "01", "", "LT1", 2, "1-2", "LyThuyet", "2"),
            ("841099", "02", "", "LT1", 2, "1-2", "LyThuyet", "2"),
        ]
        data["rooms"]["PhongKhongKhaDung"] = []
        self.client.force_login(self.admin)
        self.queue_auto(data)
        self.assertEqual(process_next_run().status, "OPTIMAL")
        entries = list(ScheduleEntry.objects.filter(source="ThuatToan", group__semester=self.semester))
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry.day for entry in entries}, {2})
        self.assertTrue(entries[0].start_period_id + 2 <= entries[1].start_period_id or
                        entries[1].start_period_id + 2 <= entries[0].start_period_id)

    def test_auto_schedule_rerun_replaces_pending_result(self):
        data = self.auto_data()
        self.client.force_login(self.admin)
        for _ in range(2):
            self.queue_auto(data)
            self.assertIn(process_next_run().status, ("OPTIMAL", "FEASIBLE"))
        self.assertEqual(ScheduleEntry.objects.filter(source="ThuatToan", group__semester=self.semester).count(), 1)

    def test_auto_schedule_approves_whole_run_and_lecturer_sees_result(self):
        data = self.auto_data()
        self.client.force_login(self.admin)
        queued = self.queue_auto(data)
        self.assertIn(process_next_run().status, ("OPTIMAL", "FEASIBLE"))
        response = self.client.get(f"/admin/auto-schedule/?run={queued.pk}")
        run = response.context["run"]
        self.assertTrue(response.context["can_approve"])
        approved = self.client.post("/admin/auto-schedule/", {
            "action": "approve", "run_id": str(run.pk),
        })
        self.assertEqual(approved.status_code, 200, approved.content[:500])
        entry = ScheduleEntry.objects.get(algorithm_run=run)
        self.assertEqual(entry.status, "DaDuyet")
        self.assertEqual(entry.approved_by, self.admin)
        self.assertIsNotNone(entry.approved_at)
        self.assertFalse(approved.context["can_approve"])
        self.assertEqual(self.client.get(f"/admin/auto-schedule/?run={run.pk}").status_code, 200)
        rerun = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "ERROR")
        rerun.refresh_from_db()
        self.assertIn("đã có lịch được duyệt", rerun.diagnostics[0]["message"])
        self.assertEqual(ScheduleEntry.objects.filter(group__course__code="841099").count(), 1)
        self.client.force_authenticate(user=None)
        teacher_user = get_user_model().objects.create_user("auto_teacher", password="safe-test-password")
        entry.lecturer.user = teacher_user
        entry.lecturer.save(update_fields=["user"])
        self.client.force_login(teacher_user)
        self.assertEqual(len(self.client.get("/api/me/schedule/").data), 1)

    def test_auto_schedule_reports_infeasible_without_fake_teacher(self):
        data = self.auto_data()
        data["courses"]["NhomHocPhan"] = [
            ("841099", self.semester.name, group, "", 40, f"DCT{group}")
            for group in ("01", "02", "03")
        ]
        data["courses"]["BuoiHocYeuCau"] = [
            ("841099", group, "", "LT1", 5, "1-2", "LyThuyet", "2")
            for group in ("01", "02", "03")
        ]
        data["rooms"]["PhongKhongKhaDung"] = []
        self.client.force_login(self.admin)
        queued = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "INFEASIBLE")
        response = self.client.get(f"/admin/auto-schedule/?run={queued.pk}")
        self.assertEqual(response.context["run"].status, "INFEASIBLE")
        diagnostics = response.context["run"].diagnostics
        self.assertEqual(len(diagnostics), 3)
        self.assertEqual({row["excel_row"] for row in diagnostics}, {2, 3, 4})
        self.assertTrue(all(row["candidate_count"] > 0 for row in diagnostics))
        self.assertContains(response, "chưa xác định được buổi nào")
        self.assertContains(self.client.get(
            f"/admin/auto-schedule/?run={response.context['run'].pk}"), "Dòng Excel")
        self.assertEqual(ScheduleEntry.objects.filter(source="ThuatToan").count(), 0)
        self.assertFalse(Lecturer.objects.filter(employee_code__startswith="GV_").exists())

    def test_auto_schedule_diagnoses_room_blackout_for_single_session(self):
        data = self.auto_data()
        data["courses"]["BuoiHocYeuCau"] = [
            ("841099", "01", "", "LT1", 2, "1-2", "LyThuyet", "2"),
        ]
        data["rooms"]["PhongKhongKhaDung"] = [("C.B201", 2, 1, 13, "1-2")]
        self.client.force_login(self.admin)
        queued = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "INFEASIBLE")
        response = self.client.get(f"/admin/auto-schedule/?run={queued.pk}")
        run = response.context["run"]
        self.assertEqual(run.status, "INFEASIBLE")
        self.assertEqual(run.diagnostics[0]["candidate_count"], 0)
        self.assertIn("Phòng phù hợp đều bận", run.diagnostics[0]["reason"])
        self.assertContains(response, "PhongKhongKhaDung")

    def test_auto_schedule_rejects_missing_qualification_without_partial_catalog(self):
        data = self.auto_data()
        data["courses"]["NhomHocPhan"].append(("841099", self.semester.name, "02", "", 40, "DKP1261"))
        data["courses"]["BuoiHocYeuCau"].append(
            ("841099", "02", "", "LT1", 2, "1-2", "LyThuyet", "2-3"))
        data["lecturers"]["GiangVienHocPhan"] = []
        self.client.force_login(self.admin)
        queued = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "ERROR")
        response = self.client.get(f"/admin/auto-schedule/?run={queued.pk}")
        self.assertContains(response, "không có giảng viên đủ chuyên môn")
        self.assertEqual([(row["sheet"], row["line"]) for row in response.context["run"].diagnostics],
                         [("BuoiHocYeuCau", 2), ("BuoiHocYeuCau", 3)])
        self.assertFalse(Course.objects.filter(code="841099").exists())

    def test_auto_schedule_rejects_group_without_required_session(self):
        data = self.auto_data()
        data["courses"]["NhomHocPhan"].append(("841099", self.semester.name, "02", "", 40, "DKP1261"))
        self.client.force_login(self.admin)
        queued = self.queue_auto(data)
        self.assertEqual(process_next_run().status, "ERROR")
        response = self.client.get(f"/admin/auto-schedule/?run={queued.pk}")
        self.assertContains(response, "chưa có buổi học yêu cầu")
        self.assertFalse(Course.objects.filter(code="841099").exists())

    def test_auto_schedule_requires_staff_and_templates_have_three_files(self):
        self.client.force_authenticate(user=None)
        self.client.force_login(self.teacher_user)
        self.assertNotEqual(self.client.get("/admin/auto-schedule/").status_code, 200)
        self.client.force_login(self.admin)
        for kind in AUTO_SHEETS:
            response = self.client.get(f"/admin/auto-schedule/template/{kind}/")
            self.assertEqual(response.status_code, 200)
            book = load_workbook(BytesIO(response.content), read_only=True)
            self.assertEqual(set(book.sheetnames), set(AUTO_SHEETS[kind]))
            book.close()
