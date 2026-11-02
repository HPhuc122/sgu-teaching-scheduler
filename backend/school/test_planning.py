from datetime import date, time
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from openpyxl import load_workbook

from .auto_schedule import read_auto_files, _prepare_inputs, _create_catalog, run_from_workbooks
from .auto_schedule_errors import InputIssues
from .models import (Faculty, Lecturer, Semester, Period, GroupTeachingPlan, TeachingAssignment,
                     OffCampusActivity, LecturerOtherDuty, ScheduleEntry, UnitRoleAssignment)
from .planning import save_plan_from_workbooks, workbooks_from_plan, appointment_kind, activity_blocks
from .sample_data import synthetic_rows, workbook_bytes
from django.core.files.uploadedfile import SimpleUploadedFile


class TeachingPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("planning_admin")
        cls.semester = Semester.objects.create(name="HK1 kế hoạch", academic_year="2027-2028", number=1,
            start_date=date(2027, 1, 4), end_date=date(2027, 1, 17), week_count=2)
        for n in range(1, 14):
            Period.objects.create(id=n, block="Sang" if n <= 5 else "Chieu", start_time=time(7), end_time=time(8))

    def rows(self):
        rows = synthetic_rows(sessions=3, semester_name=self.semester.name, weeks=2, seed=7)
        c, t = rows["courses"], rows["lecturers"]
        c["HocPhan"] = [(*r[:3], "TEST_CNPM", r[4]) for r in c["HocPhan"]]
        chosen = []
        for i, r in enumerate(c["BuoiHocYeuCau"]):
            teacher = next(x[0] for x in t["GiangVienHocPhan"] if x[1] == r[0] and x[0] not in chosen)
            chosen.append(teacher)
            c["BuoiHocYeuCau"][i] = (*r, teacher, "TH" if r[6] == "MayTinh" else "LT", 4)
            c["KeHoachMoNhom"].append((r[0], r[1], r[2], 1, "Khóa mô phỏng", 30, 0, 30, "0.8", ""))
        for i, teacher_code in enumerate(chosen):
            j = next(j for j, r in enumerate(t["GiangVien"]) if r[0] == teacher_code)
            r = t["GiangVien"][j]
            t["GiangVien"][j] = (*r[:3], "TEST_KHTN" if i == 1 else "TEST_CNTT",
                "TEST_TOAN" if i == 1 else "TEST_CNPM", "DangCongTac",
                "THINH_GIANG" if i == 2 else "CO_HUU", "Chuyên ngành mô phỏng", "ThS", "Đơn vị mô phỏng")
        t["CongTacKhac"].append((chosen[0], "CT1", "Công tác mô phỏng", "KHAC", 10))
        return rows

    def files(self, rows):
        return {kind: SimpleUploadedFile(f"{kind}.xlsx", workbook_bytes(kind, data)) for kind, data in rows.items()}

    def test_plan_persists_before_timetable_and_roundtrips_all_sources(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        self.assertEqual(TeachingAssignment.objects.count(), 3)
        self.assertEqual(GroupTeachingPlan.objects.count(), 3)
        self.assertEqual(ScheduleEntry.objects.count(), 0)
        self.assertEqual({appointment_kind(a) for a in TeachingAssignment.objects.select_related("group__course__department", "lecturer__department")}, {"CO_HUU", "MOI_GIANG", "THINH_GIANG"})
        parsed = read_auto_files(workbooks_from_plan(self.semester))
        self.assertEqual(len(parsed["courses"]["BuoiHocYeuCau"]), 3)
        self.assertTrue(all(r["ma_vien_chuc_phan_cong"] for r in parsed["courses"]["BuoiHocYeuCau"]))
        self.assertEqual(LecturerOtherDuty.objects.count(), 1)

    def test_activity_blocks_are_used_in_scheduling_and_independent_audit(self):
        from .solution_audit import audit_solution
        rows = self.rows()
        cls_name = rows["courses"]["NhomHocPhan"][0][-1]
        rows["courses"]["HoatDongNgoaiTruong"].append(("HD1", cls_name, "Khóa mô phỏng", "ĐH", "Thực tập", "Cơ sở mô phỏng", "2027-01-04", "2027-01-04", 35, 1))
        with override_settings(QUALITY_SEARCH_BUDGET_SECONDS=4, QUALITY_GD_EXTRA_PATHS=0):
            run = run_from_workbooks(self.semester.pk, self.files(rows), self.admin)
        self.assertEqual(run.entry_count, 3)
        a = TeachingAssignment.objects.first()
        entries = list(run.entries.order_by("pk").select_related("lecturer", "room", "group"))
        for e in entries:
            planned = TeachingAssignment.objects.get(group=e.group, request_code=e.request_code)
            self.assertEqual(e.lecturer_id, planned.fixed_lecturer_id)
        self.assertIn((2, 1), activity_blocks(self.semester)[a.group_id])
        for e in entries:
            if e.group_id == a.group_id:
                self.assertNotEqual(e.day, 2)
        parsed = read_auto_files(self.files(rows))
        demands, rb, tb = _prepare_inputs(self.semester, parsed)
        demands, rooms, teachers = _create_catalog(self.semester, parsed, demands, rb, tb)
        result = [(d, e.day, e.start_period_id, e.room, e.lecturer) for d, e in zip(demands, entries)]
        wrong = next(t for t in teachers.values() if t.pk != result[0][4].pk)
        result[0] = (*result[0][:4], wrong)
        pairs = {(r["ma_vien_chuc"], r["ma_mon_hoc"]) for r in parsed["lecturers"]["GiangVienHocPhan"]}
        with self.assertRaisesMessage(ValueError, "phân công cố định"):
            audit_solution(self.semester, demands, result, rooms, teachers, rb, tb, pairs, preferences=[])

    def test_invalid_activity_and_teacher_roll_back_catalogs(self):
        rows = self.rows()
        r = rows["courses"]["BuoiHocYeuCau"][0]
        rows["courses"]["BuoiHocYeuCau"][0] = (*r[:8], "UNKNOWN", *r[9:])
        with self.assertRaises(InputIssues):
            save_plan_from_workbooks(self.semester.pk, self.files(rows))
        self.assertFalse(Faculty.objects.exists())
        rows = self.rows()
        rows["courses"]["HoatDongNgoaiTruong"].append(("HD1", rows["courses"]["NhomHocPhan"][0][-1], "", "ĐH", "Thực tập", "", "2027-01-18", "2027-01-17", 35, 1))
        with self.assertRaises(InputIssues):
            save_plan_from_workbooks(self.semester.pk, self.files(rows))
        self.assertFalse(TeachingAssignment.objects.exists())

    def test_all_five_forms_and_three_semesters_export_from_plan_without_schedule(self):
        save_plan_from_workbooks(self.semester.pk, self.files(self.rows()))
        self.client.force_login(self.admin)
        faculty = Faculty.objects.get(code="TEST_CNTT")
        response = self.client.get(f"/admin/teaching-plans/?year=2027-2028&faculty={faculty.pk}&download=xlsx")
        self.assertEqual(response.status_code, 200)
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(set(book.sheetnames), {"Mau1_HK1", "Mau1_HK2", "Mau1_HK3", "Mau2", "Mau3", "Mau4", "Mau5"})
        for name in ("Mau1_HK1", "Mau2", "Mau3", "Mau4"):
            self.assertGreater(book[name].max_row, 5)
        self.assertEqual(ScheduleEntry.objects.count(), 0)
        self.assertEqual(self.client.get("/admin/teaching-plans/").status_code, 200)

    def test_role_scope_and_locked_semester(self):
        save_plan_from_workbooks(self.semester.pk, self.files(self.rows()))
        user = get_user_model().objects.create_user("faculty_plan", is_staff=True)
        faculty = Faculty.objects.get(code="TEST_KHTN")
        UnitRoleAssignment.objects.create(user=user, role="FACULTY", faculty=faculty, can_manage=True)
        self.client.force_login(user)
        assignment = TeachingAssignment.objects.first()
        self.assertEqual(self.client.get(f"/admin/teaching-plans/assignment/{assignment.pk}/").status_code, 404)
        self.client.force_login(self.admin)
        self.semester.status = "DaKhoa"
        self.semester.save()
        response = self.client.post(f"/admin/teaching-plans/assignment/{assignment.pk}/", {"fixed_lecturer": assignment.fixed_lecturer_id, "component": "LT"})
        self.assertEqual(response.status_code, 400)

    def test_activity_form_uses_named_cohorts_and_iso_dates_for_edit(self):
        from .planning_views import ActivityForm
        from .models import Cohort
        save_plan_from_workbooks(self.semester.pk, self.files(self.rows()))
        cohort = Cohort.objects.filter(semester=self.semester).first()
        activity = OffCampusActivity.objects.create(semester=self.semester, cohort=cohort,
            code="DATE_TEST", description="Hoạt động mô phỏng", start_date=date(2027, 1, 10),
            end_date=date(2027, 1, 10), student_count=35, semester_number=1)
        form = ActivityForm(instance=activity)
        self.assertIn(cohort.name, form.fields["cohort"].label_from_instance(cohort))
        self.assertIn(self.semester.name, form.fields["cohort"].label_from_instance(cohort))
        self.assertIn('value="2027-01-10"', str(form["start_date"]))
        self.client.force_login(self.admin)
        response = self.client.get(f"/admin/teaching-plans/activity/{activity.pk}/")
        self.assertContains(response, 'plan-cohort-options')
        self.assertContains(response, cohort.name)

    def test_faculty_export_keeps_legacy_activity_with_unowned_cohort(self):
        rows = self.rows()
        rows["courses"]["HoatDongNgoaiTruong"].append(("LEGACY_HD", rows["courses"]["NhomHocPhan"][0][-1], "", "ĐH", "Hoạt động cũ", "", "2027-01-10", "2027-01-10", 35, 1))
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        faculty = Faculty.objects.get(code="TEST_CNTT")
        self.client.force_login(self.admin)
        response = self.client.get(f"/admin/teaching-plans/?year=2027-2028&faculty={faculty.pk}&download=xlsx")
        self.assertEqual(response.status_code, 200)
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book["Mau5"].max_row, 6)
        self.assertEqual(book["Mau5"].cell(6, 4).value, "Hoạt động cũ")

    def test_explicit_class_owner_controls_activity_scope_and_export(self):
        from .access import scoped
        rows = self.rows()
        class_name = rows["courses"]["NhomHocPhan"][0][-1]
        rows["courses"]["LopHanhChinh"].append((class_name, "TEST_TOAN"))
        rows["courses"]["HoatDongNgoaiTruong"].append(("OWNED_HD", class_name, "", "ĐH", "Hoạt động theo khoa", "", "2027-01-10", "2027-01-10", 35, 1))
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        owner = Faculty.objects.get(code="TEST_KHTN")
        other = Faculty.objects.get(code="TEST_CNTT")
        user = get_user_model().objects.create_user("activity_owner", is_staff=True)
        UnitRoleAssignment.objects.create(user=user, role="FACULTY", faculty=owner, can_manage=True)
        self.assertEqual(scoped(OffCampusActivity.objects.all(), user).count(), 1)
        self.client.force_login(self.admin)
        for faculty, count in ((owner, 6), (other, 5)):
            response = self.client.get(f"/admin/teaching-plans/?year=2027-2028&faculty={faculty.pk}&download=xlsx")
            book = load_workbook(BytesIO(response.content))
            self.assertEqual(book["Mau5"].max_row, count)
