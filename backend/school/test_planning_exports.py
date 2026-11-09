from datetime import date
from decimal import Decimal
from io import BytesIO

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook

from .models import (Cohort, Course, CourseGroup, Department, Faculty, GroupTeachingPlan,
                     Lecturer, LecturerOtherDuty, OffCampusActivity, Semester, TeachingAssignment)
from .planning_exports import forms_workbook


class PlanningExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.faculty = Faculty.objects.create(code="EXPORT", name="Khoa xuất báo cáo")
        other = Faculty.objects.create(code="GUEST", name="Khoa khác")
        cls.department = Department.objects.create(faculty=cls.faculty, name="Bộ môn")
        guest_department = Department.objects.create(faculty=other, name="Bộ môn khác")
        cls.course = Course.objects.create(department=cls.department, code="HP1", name="Học phần 1", credits=3)
        cls.second_course = Course.objects.create(department=cls.department, code="HP2", name="Học phần 2", credits=3)
        cls.home = Lecturer.objects.create(department=cls.department, name="Cơ hữu A")
        cls.second_home = Lecturer.objects.create(department=cls.department, name="Cơ hữu B")
        cls.guest = Lecturer.objects.create(department=guest_department, name="Mời giảng", employee_code="GUEST")
        cls.external = Lecturer.objects.create(department=guest_department, name="Thỉnh giảng", employee_code="EXTERNAL", source_kind="THINH_GIANG")
        cls.semesters = [Semester.objects.create(name=f"HK{n}", academic_year="2027-2028", number=n,
            start_date=date(2027, n * 3, 1), end_date=date(2027, n * 3, 14), week_count=2) for n in (1, 2, 3)]
        for semester in cls.semesters:
            for index, teacher in enumerate((cls.home, cls.guest, cls.external, None), 1):
                group = CourseGroup.objects.create(course=cls.course, semester=semester, code=f"G{index}", group=str(index), capacity=35)
                GroupTeachingPlan.objects.create(group=group, lecture_periods=30, exercise_periods=0,
                    practical_periods=30, coefficient=Decimal("0.8"))
                TeachingAssignment.objects.create(group=group, request_code="B1", period_count=3, weeks=[1, 2],
                    lecturer=teacher, component="LT", reported_periods=Decimal("4.5"))

    def export(self):
        assignments = TeachingAssignment.objects.select_related("group__course__department__faculty",
            "group__semester", "group__teaching_plan", "lecturer__department__faculty").order_by("pk")
        activities = OffCampusActivity.objects.select_related("cohort", "semester")
        duties = LecturerOtherDuty.objects.select_related("lecturer__department__faculty")
        return load_workbook(BytesIO(forms_workbook(self.faculty, "2027-2028", assignments, activities, duties)))

    def test_all_three_semesters_keep_explicit_periods_and_unassigned_rows(self):
        book = self.export()
        self.assertEqual(set(book.sheetnames), {"Mau1_HK1", "Mau1_HK2", "Mau1_HK3", "Mau2", "Mau3", "Mau4", "Mau5"})
        for number in (1, 2, 3):
            rows = list(book[f"Mau1_HK{number}"].iter_rows(min_row=6, values_only=True))
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row[8] == 60 and row[9] == 0.8 and row[16] == 6 and row[17] == 4.5 for row in rows))
            self.assertEqual(sum(row[14] is None for row in rows), 2)  # Home teacher has no employee code; one session is unassigned.
        self.assertEqual(book["Mau3"].cell(6, 10).value, 13.5)
        self.assertEqual(book["Mau4"].cell(6, 15).value, 13.5)

    def test_missing_explicit_values_stay_blank_and_unknown_semester_is_not_guessed(self):
        TeachingAssignment.objects.filter(lecturer=self.guest).update(reported_periods=None)
        self.semesters[0].number = None
        self.semesters[0].save(update_fields=["number"])
        book = self.export()
        self.assertEqual(book["Mau1_HK1"].max_row, 5)
        self.assertEqual(book["Mau1_HKChuaGan"].max_row, 9)
        self.assertIsNone(book["Mau3"].cell(6, 10).value)
        self.assertIsNone(book["Mau1_HKChuaGan"].cell(7, 18).value)

    def test_home_totals_appear_once_per_teacher_even_without_employee_codes(self):
        semester = self.semesters[0]
        for index, teacher in enumerate((self.home, self.second_home), 1):
            group = CourseGroup.objects.create(course=self.second_course, semester=semester, code=f"EX{index}", group=str(index), capacity=35)
            GroupTeachingPlan.objects.create(group=group)
            TeachingAssignment.objects.create(group=group, request_code="B1", period_count=2,
                weeks=[1], lecturer=teacher, reported_periods=2)
        LecturerOtherDuty.objects.create(semester=semester, lecturer=self.home, code="D1", description="Khác", periods=10)
        LecturerOtherDuty.objects.create(semester=semester, lecturer=self.home, code="D2", description="CLC", periods=3, kind="CLC")
        book = self.export()
        rows = list(book["Mau2"].iter_rows(min_row=6, values_only=True))
        home_rows = [row for row in rows if row[2] == self.home.name]
        self.assertEqual(len(home_rows), 2)
        self.assertEqual([row[16] for row in home_rows], [28.5, None])
        second_row = next(row for row in rows if row[2] == self.second_home.name)
        self.assertEqual(second_row[16], 2)
        self.assertEqual(sum(row[15] for row in home_rows), 3)

    def test_duty_only_form_two_contains_only_home_permanent_staff(self):
        semester = self.semesters[0]
        for index, teacher in enumerate((self.second_home, self.external, self.guest)):
            LecturerOtherDuty.objects.create(semester=semester, lecturer=teacher, code=f"D{index}", description="Công tác", periods=10)
        rows = list(self.export()["Mau2"].iter_rows(min_row=6, values_only=True))
        self.assertEqual({row[2] for row in rows}, {self.home.name, self.second_home.name})

    def test_form_five_dates_and_formula_injection_protection(self):
        semester = self.semesters[0]
        cohort = Cohort.objects.create(semester=semester, department=self.department, name="Lớp")
        OffCampusActivity.objects.create(semester=semester, cohort=cohort, code="HD", description="=1+1",
            location="+Cơ sở", start_date=date(2027, 3, 1), end_date=date(2027, 3, 3), student_count=35)
        plan = GroupTeachingPlan.objects.first()
        plan.note = "@ghi chú"
        plan.save(update_fields=["note"])
        book = self.export()
        row = next(book["Mau5"].iter_rows(min_row=6, values_only=True))
        self.assertEqual(row[3], "'=1+1")
        self.assertEqual(row[4], "'+Cơ sở")
        self.assertEqual(row[6:9], (3, "2027-03-01", "2027-03-03"))
        self.assertEqual(book["Mau1_HK1"].cell(6, 19).value, "'@ghi chú")

    def test_export_uses_bounded_queries(self):
        with CaptureQueriesContext(connection) as queries:
            self.export()
        self.assertEqual(len(queries), 3)
