from datetime import date, time
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook

from .models import (
    Course, CourseGroup, Department, Faculty, GroupTeachingPlan, Lecturer,
    Period, ScheduleEntry, ScheduleWeek, Semester, TeachingAssignment, UnitRoleAssignment,
)


class PaginationLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "page-link" in attrs.get("class", "").split():
            self.links.append(attrs["href"])


class TeachingPlanPaginationTests(TestCase):
    url = "/admin/teaching-plans/"

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("pagination_admin")
        cls.faculty = Faculty.objects.create(code="PAGE", name="Khoa phân trang")
        cls.other_faculty = Faculty.objects.create(code="OTHER", name="Khoa khác")
        cls.department = Department.objects.create(faculty=cls.faculty, name="Bộ môn")
        other_department = Department.objects.create(faculty=cls.other_faculty, name="Bộ môn khác")
        cls.teacher = Lecturer.objects.create(department=cls.department, name="Giảng viên")
        cls.course = Course.objects.create(department=cls.department, code="PAGE", name="Học phần", credits=3)
        other_course = Course.objects.create(department=other_department, code="OTHER", name="Học phần khác", credits=3)
        cls.semester = Semester.objects.create(name="HK1", academic_year="2027-2028", number=1,
            start_date=date(2027, 1, 4), end_date=date(2027, 1, 17), week_count=2)
        cls.other_semester = Semester.objects.create(name="HK2", academic_year="2027-2028", number=2,
            start_date=date(2027, 6, 1), end_date=date(2027, 6, 14), week_count=2)
        cls.other_year = Semester.objects.create(name="Năm khác", academic_year="2028-2029", number=1,
            start_date=date(2028, 1, 3), end_date=date(2028, 1, 16), week_count=2)
        for semester, course, count in (
            (cls.semester, cls.course, 960), (cls.semester, other_course, 65),
            (cls.other_semester, cls.course, 70), (cls.other_year, cls.course, 55),
        ):
            groups = CourseGroup.objects.bulk_create([
                CourseGroup(semester=semester, course=course, code=f"G{i:04}", group=f"{i:04}", capacity=40)
                for i in range(count)
            ])
            GroupTeachingPlan.objects.bulk_create([GroupTeachingPlan(group=g) for g in groups])
            TeachingAssignment.objects.bulk_create([
                TeachingAssignment(group=g, request_code="B1", period_count=3, weeks=[1, 2],
                    lecturer=cls.teacher if course == cls.course and i % 2 == 0 else None)
                for i, g in enumerate(groups)
            ])
        cls.user = get_user_model().objects.create_user("pagination_faculty", is_staff=True)
        UnitRoleAssignment.objects.create(user=cls.user, role="FACULTY", faculty=cls.faculty, can_manage=True)

    def setUp(self):
        self.client.force_login(self.admin)
        self.filters = {"year": self.semester.academic_year, "semester": self.semester.pk, "faculty": self.faculty.pk}

    def test_all_960_sessions_are_reachable_once_and_links_keep_filters(self):
        expected = set(TeachingAssignment.objects.filter(group__semester=self.semester, group__course=self.course).values_list("pk", flat=True))
        seen = []
        for number in range(1, 21):
            response = self.client.get(self.url, {**self.filters, "page": number})
            self.assertEqual(response.status_code, 200)
            context = response.context
            self.assertEqual(context["total"], 960)
            self.assertEqual(context["unassigned"], 480)
            self.assertEqual(context["page_obj"].paginator.num_pages, 20)
            self.assertEqual(len(context["rows"]), 10 if number == 20 else 50)
            self.assertContains(response, f"Đang xem dòng {(number - 1) * 50 + 1}–{min(number * 50, 960)} trên tổng 960")
            seen.extend(row["assignment"].pk for row in context["rows"])
            for href in PaginationLinks(response.content.decode()).links:
                query = parse_qs(urlsplit(href).query)
                for key, value in self.filters.items():
                    self.assertEqual(query[key], [str(value)])
                self.assertEqual(len(query["page"]), 1)
                self.assertNotIn("download", query)
            if number == 10:
                self.assertContains(response, 'aria-label="Các trang khác">...</span>')
                self.assertContains(response, 'aria-current="page"')
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), expected)

    def test_filters_apply_before_pagination(self):
        for filters, expected in (
            ({"year": "2027-2028", "faculty": self.faculty.pk}, 1030),
            ({"year": "2028-2029", "faculty": self.faculty.pk}, 55),
            ({"semester": self.semester.pk, "faculty": self.other_faculty.pk}, 65),
            ({"semester": self.semester.pk}, 1025),
        ):
            with self.subTest(filters=filters):
                response = self.client.get(self.url, {**filters, "page": 2})
                self.assertEqual(response.context["total"], expected)
                self.assertEqual(response.context["page_obj"].number, 2)
                for row in response.context["rows"]:
                    assignment = row["assignment"]
                    if "faculty" in filters:
                        self.assertEqual(assignment.group.course.department.faculty_id, filters["faculty"])
                    if "year" in filters:
                        self.assertEqual(assignment.group.semester.academic_year, filters["year"])
                    if "semester" in filters:
                        self.assertEqual(assignment.group.semester_id, filters["semester"])

    def test_invalid_pages_and_empty_scope(self):
        for value, expected in (("abc", 1), ("1.5", 1), ("", 1), ("0", 20), ("-1", 20), ("999999999999999999999", 20)):
            with self.subTest(page=value):
                response = self.client.get(self.url, {**self.filters, "page": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, expected)
        response = self.client.get(self.url, {"year": "1900-1901", "page": 100})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["rows"], [])
        self.assertContains(response, "Đang xem dòng 0–0 trên tổng 0")

    def test_faculty_permissions_on_later_pages_and_export(self):
        self.client.force_login(self.user)
        for number in (1, 2, 20, 21):
            response = self.client.get(self.url, {"semester": self.semester.pk, "page": number})
            self.assertEqual(response.context["total"], 960)
            self.assertTrue(all(row["assignment"].group.course_id == self.course.pk for row in response.context["rows"]))
        for download in ("", "xlsx"):
            response = self.client.get(self.url, {**self.filters, "faculty": self.other_faculty.pk, "page": 2, "download": download})
            self.assertEqual(response.status_code, 404)
        response = self.client.get(self.url, {**self.filters, "download": "xlsx", "page": 2})
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book["Mau1_HK1"].max_row, 965)
        self.assertTrue(all(row[1] == self.course.code for row in book["Mau1_HK1"].iter_rows(min_row=6, values_only=True)))

    def test_excel_exports_entire_filtered_scope_regardless_of_page(self):
        for number in (1, 20):
            response = self.client.get(self.url, {**self.filters, "page": number, "download": "xlsx"})
            self.assertEqual(response.status_code, 200)
            book = load_workbook(BytesIO(response.content))
            sheet = book["Mau1_HK1"]
            self.assertEqual(sheet.max_row, 965)
            self.assertEqual(sum(row[16] for row in sheet.iter_rows(min_row=6, values_only=True)), 5760)
            self.assertEqual(book["Mau1_HK2"].max_row, 5)

    def test_cross_faculty_teaching_keeps_existing_read_and_edit_permissions(self):
        assignment = TeachingAssignment.objects.filter(
            group__semester=self.semester, group__course__department__faculty=self.other_faculty,
        ).first()
        assignment.lecturer = self.teacher
        assignment.save(update_fields=["lecturer"])
        self.client.force_login(self.user)
        # Existing scope also permits reading sessions taught by the faculty's staff.
        response = self.client.get(self.url, {"semester": self.semester.pk, "page": 20})
        self.assertEqual(response.context["total"], 961)
        response = self.client.get(self.url, {"semester": self.semester.pk, "page": 1})
        cross_row = next(row for row in response.context["rows"] if row["assignment"].pk == assignment.pk)
        self.assertFalse(cross_row["can_edit"])
        response = self.client.get(self.url, {**self.filters, "download": "xlsx", "page": 20})
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book["Mau1_HK1"].max_row, 965)
        self.assertEqual(book["Mau2"].max_row, 7)

    def test_tied_sort_keys_keep_a_stable_order_between_pages(self):
        CourseGroup.objects.filter(semester=self.semester, course=self.course).update(group="01")
        expected = list(TeachingAssignment.objects.filter(
            group__semester=self.semester, group__course=self.course,
        ).order_by("pk").values_list("pk", flat=True)[:100])
        seen = []
        for number in (1, 2):
            response = self.client.get(self.url, {**self.filters, "page": number})
            seen.extend(row["assignment"].pk for row in response.context["rows"])
        self.assertEqual(seen, expected)

    def test_reconciliation_editability_and_query_count(self):
        period = Period.objects.create(id=1, block="Sang", start_time=time(7), end_time=time(8))
        assignments = list(TeachingAssignment.objects.filter(group__semester=self.semester, group__course=self.course).order_by("group__group"))
        entries = ScheduleEntry.objects.bulk_create([
            ScheduleEntry(group=a.group, request_code=a.request_code, lecturer=a.lecturer,
                day=2, start_period=period, period_count=3, status="DaDuyet")
            for a in assignments
        ])
        ScheduleWeek.objects.bulk_create([ScheduleWeek(entry=e, week=w) for e in entries for w in (1, 2)])
        counts = []
        for number in (1, 20):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.url, {**self.filters, "page": number})
            counts.append(len(queries))
            page_query = response.context["page_obj"].object_list.query
            self.assertEqual(page_query.low_mark, (number - 1) * 50)
            self.assertEqual(page_query.high_mark, min(number * 50, 960))
            for row in response.context["rows"]:
                self.assertEqual(row["scheduled"], 6)
                self.assertEqual(row["state"], "Khớp kế hoạch")
                self.assertTrue(row["approved"])
                self.assertTrue(row["can_edit"])
        self.assertEqual(counts[0], counts[1])
        self.assertLess(counts[0], 25)
        self.semester.status = "DaKhoa"
        self.semester.save(update_fields=["status"])
        response = self.client.get(self.url, self.filters)
        self.assertTrue(all(not row["can_edit"] for row in response.context["rows"]))

    def test_unknown_semester_summary_covers_all_pages(self):
        self.semester.number = None
        self.semester.save(update_fields=["number"])
        plan = GroupTeachingPlan.objects.filter(group__semester=self.semester, group__course=self.course).first()
        plan.semester_number = 1
        plan.save(update_fields=["semester_number"])
        response = self.client.get(self.url, {**self.filters, "page": 20})
        self.assertEqual(response.context["unknown_semesters"], 959)
