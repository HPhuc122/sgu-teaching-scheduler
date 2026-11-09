from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, OperationalError, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError

from .models import (Course, CourseGroup, Department, Faculty, Lecturer, Period, ScheduleEntry,
                     ScheduleWeek, Semester, TeachingAssignment, TeachingQualification)
from .services import approve_schedule_entries


def approval_fixture(count=3):
    admin = get_user_model().objects.create_superuser("approval_admin")
    semester = Semester.objects.create(name="HK1", academic_year="2027-2028", number=1,
        start_date=date(2027, 1, 4), end_date=date(2027, 1, 17), week_count=2)
    faculty = Faculty.objects.create(code="APP", name="Khoa")
    department = Department.objects.create(faculty=faculty, name="Bộ môn")
    course = Course.objects.create(department=department, code="APP", name="Học phần", credits=3)
    periods = Period.objects.bulk_create([Period(id=n, block="Sang" if n <= 5 else "Chieu",
        start_time=time(7), end_time=time(8)) for n in range(1, 14)])
    period = periods[0]
    teachers = Lecturer.objects.bulk_create([Lecturer(department=department, name=f"GV {i}") for i in range(count)])
    groups = CourseGroup.objects.bulk_create([CourseGroup(course=course, semester=semester, code=f"APP{i}",
        group=str(i), capacity=35, needs_room=False) for i in range(count)])
    TeachingQualification.objects.bulk_create([TeachingQualification(course=course, lecturer=t) for t in teachers])
    entries = ScheduleEntry.objects.bulk_create([ScheduleEntry(group=g, lecturer=t, day=2,
        start_period=period, period_count=1, other_location="Cơ sở", request_code="B1") for g, t in zip(groups, teachers)])
    ScheduleWeek.objects.bulk_create([ScheduleWeek(entry=e, week=w) for e in entries for w in (1, 2)])
    TeachingAssignment.objects.bulk_create([TeachingAssignment(group=g, request_code="B1", period_count=1,
        weeks=[1, 2]) for g in groups])
    return admin, semester, [e.pk for e in entries]


class ReviewApprovalTests(TestCase):
    def setUp(self):
        self.admin, self.semester, self.ids = approval_fixture()

    def assert_pending(self):
        self.assertEqual(ScheduleEntry.objects.filter(pk__in=self.ids, status="ChoDuyet",
            approved_by__isnull=True, approved_at__isnull=True).count(), len(self.ids))

    def test_batch_changes_only_approval_fields_and_syncs_plan_lecturers(self):
        before = list(ScheduleEntry.objects.order_by("pk").values())
        weeks = list(ScheduleWeek.objects.order_by("pk").values())
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin), 3)
        changed_fields = {"status", "approved_by_id", "approved_at"}
        after = list(ScheduleEntry.objects.order_by("pk").values())
        for old, new in zip(before, after):
            self.assertEqual({k: v for k, v in old.items() if k not in changed_fields},
                             {k: v for k, v in new.items() if k not in changed_fields})
            self.assertEqual(new["status"], "DaDuyet")
            self.assertEqual(new["approved_by_id"], self.admin.pk)
        self.assertEqual(len({row["approved_at"] for row in after}), 1)
        self.assertEqual(list(ScheduleWeek.objects.order_by("pk").values()), weeks)
        self.assertFalse(TeachingAssignment.objects.filter(lecturer__isnull=True).exists())
        entry_table = connection.ops.quote_name(ScheduleEntry._meta.db_table)
        updates = [q["sql"] for q in queries if q["sql"].startswith(f"UPDATE {entry_table}")]
        self.assertEqual(len(updates), 1)

    def test_invalid_last_entry_rolls_back_entire_batch(self):
        last = ScheduleEntry.objects.get(pk=self.ids[-1])
        last.lecturer.status = "NgungCongTac"
        last.lecturer.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin)
        self.assert_pending()
        self.assertFalse(TeachingAssignment.objects.filter(lecturer__isnull=False).exists())

    def test_failure_after_status_update_rolls_back_status_and_plan(self):
        weeks = list(ScheduleWeek.objects.values_list("pk", "entry_id", "week"))
        with patch("school.services.TeachingAssignment.objects.bulk_update", side_effect=RuntimeError("write failed")):
            with self.assertRaisesMessage(RuntimeError, "write failed"):
                approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin)
        self.assert_pending()
        self.assertFalse(TeachingAssignment.objects.filter(lecturer__isnull=False).exists())
        self.assertEqual(list(ScheduleWeek.objects.values_list("pk", "entry_id", "week")), weeks)

    def test_already_approved_batch_cannot_be_approved_again(self):
        approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin)
        before = list(ScheduleEntry.objects.values_list("pk", "approved_by_id", "approved_at"))
        with self.assertRaisesMessage(ValidationError, "đang chờ duyệt"):
            approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin)
        self.assertEqual(list(ScheduleEntry.objects.values_list("pk", "approved_by_id", "approved_at")), before)

    def test_duplicate_empty_and_oversized_batches_are_rejected(self):
        for ids in ([], [self.ids[0], self.ids[0]], list(range(101))):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                approve_schedule_entries(self.semester.pk, ids, actor=self.admin)
        self.assert_pending()

    def test_mixed_status_cannot_partially_approve_pending_entries(self):
        approve_schedule_entries(self.semester.pk, [self.ids[0]], actor=self.admin)
        with self.assertRaises(ValidationError):
            approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin)
        self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 1)

    def test_http_post_does_not_hide_unrelated_operational_errors(self):
        self.client.force_login(self.admin)
        with patch("school.review_views.approve_schedule_entries", side_effect=OperationalError("no such table")):
            with self.assertRaisesMessage(OperationalError, "no such table"):
                self.client.post("/admin/review-schedules/", {"action": "approve", "semester": self.semester.pk,
                    "entry_ids": self.ids})
        self.assert_pending()

    def test_busy_after_status_write_is_rolled_back_before_rendering(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-specific busy handling")
        self.client.force_login(self.admin)
        with patch("school.services.TeachingAssignment.objects.bulk_update", side_effect=OperationalError("database is locked")):
            with self.assertLogs("school.review_views", level="WARNING"):
                response = self.client.post("/admin/review-schedules/", {"action": "approve",
                    "semester": self.semester.pk, "entry_ids": self.ids})
        self.assertEqual(response.status_code, 503)
        self.assert_pending()
        self.assertFalse(TeachingAssignment.objects.filter(lecturer__isnull=False).exists())

    def test_full_hundred_entry_batch_is_approved_once(self):
        # Build a separate 100-entry fixture in this transaction.
        ScheduleEntry.objects.all().delete()
        TeachingAssignment.objects.all().delete()
        ScheduleWeek.objects.all().delete()
        # Reuse the first fixture's catalogs and add nonconflicting weeks/days.
        entries = []
        for index in range(100):
            group = CourseGroup.objects.create(course=Course.objects.first(), semester=self.semester,
                code=f"BATCH{index}", group=str(index), capacity=35, needs_room=False)
            entry = ScheduleEntry.objects.create(group=group, lecturer=Lecturer.objects.first(),
                day=2 + index // 26, start_period_id=1 + index % 13, period_count=1, other_location="Cơ sở")
            ScheduleWeek.objects.create(entry=entry, week=1 + index // 13 % 2)
            entries.append(entry.pk)
        self.assertEqual(approve_schedule_entries(self.semester.pk, entries, actor=self.admin), 100)
        self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 100)


class SQLiteApprovalContentionTests(TransactionTestCase):
    """Independent connections to a disposable FILE, not shared-cache :memory:."""
    def setUp(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-specific contention regression")
        self.admin, self.semester, self.ids = approval_fixture()

    @contextmanager
    def file_database(self, timeout=2):
        original = connections["default"]
        with TemporaryDirectory(prefix="sgu_approval_") as directory:
            isolated = original.copy(alias="default")
            isolated.settings_dict["NAME"] = str(Path(directory) / "test.sqlite3")
            isolated.settings_dict["OPTIONS"] = {"timeout": timeout, "transaction_mode": "DEFERRED"}
            original.ensure_connection()
            isolated.ensure_connection()
            original.connection.backup(isolated.connection)
            connections["default"] = isolated
            try:
                yield isolated
            finally:
                isolated.close()
                connections["default"] = original

    def hold_writer(self, db):
        writer = sqlite3.connect(db.settings_dict["NAME"], isolation_level=None, timeout=2)
        writer.execute("BEGIN IMMEDIATE")
        table = db.ops.quote_name(Semester._meta.db_table)
        status = db.ops.quote_name(Semester._meta.get_field("status").column)
        writer.execute(f"UPDATE {table} SET {status} = {status} WHERE id = ?", (self.semester.pk,))
        return writer

    def approve_on_connection(self, db, wrapper):
        # Django wrappers are thread-bound; construct the live wrapper here.
        db = db.copy(alias="default")
        connections["default"] = db
        try:
            with db.execute_wrapper(wrapper):
                return approve_schedule_entries(self.semester.pk, self.ids, actor=self.admin)
        finally:
            db.close()

    def test_real_sqlite_busy_post_returns_503_without_partial_approval(self):
        with self.file_database(timeout=0.05) as db:
            self.client.force_login(self.admin)
            writer = self.hold_writer(db)
            try:
                with self.assertLogs("school.review_views", level="WARNING"):
                    response = self.client.post("/admin/review-schedules/", {"action": "approve",
                        "semester": self.semester.pk, "entry_ids": self.ids})
                self.assertContains(response, "Yêu cầu này chưa duyệt buổi nào", status_code=503)
                self.assertEqual(response["Retry-After"], "2")
            finally:
                writer.rollback()
                writer.close()
            self.assertFalse(ScheduleEntry.objects.filter(status="DaDuyet").exists())
            self.assertFalse(ScheduleEntry.objects.filter(approved_at__isnull=False).exists())
            response = self.client.post("/admin/review-schedules/", {"action": "approve",
                "semester": self.semester.pk, "entry_ids": self.ids})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 3)

    def test_deferred_read_to_write_upgrade_reproduces_database_locked(self):
        with self.file_database(timeout=0.05) as db:
            writer = None
            try:
                with self.assertRaisesMessage(OperationalError, "database is locked"):
                    with transaction.atomic():
                        # Same ordering as the original approval transaction:
                        # read snapshot, another writer reserves, then write.
                        Semester.objects.get(pk=self.semester.pk)
                        writer = self.hold_writer(db)
                        Semester.objects.filter(pk=self.semester.pk).update(name="Not committed")
            finally:
                if writer is not None:
                    writer.rollback()
                    writer.close()
            self.assertEqual(Semester.objects.get(pk=self.semester.pk).name, "HK1")

    def test_approval_waits_for_writer_before_reading_its_snapshot(self):
        attempted = Event()
        first_statements = []
        def observe(execute, sql, params, many, context):
            if not first_statements and sql.startswith(("SELECT", "UPDATE")):
                first_statements.append(sql)
                attempted.set()
            return execute(sql, params, many, context)
        with self.file_database() as db:
            writer = self.hold_writer(db)
            other = db.copy(alias="default")
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.approve_on_connection, other, observe)
                try:
                    self.assertTrue(attempted.wait(5))
                    self.assertTrue(first_statements[0].startswith('UPDATE "HocKy"'))
                finally:
                    writer.commit()
                    writer.close()
                self.assertEqual(future.result(timeout=10), 3)
            self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 3)

    def test_two_concurrent_approvers_have_exactly_one_success(self):
        first_reserved, release_first, second_attempted = Event(), Event(), Event()
        def first(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.startswith('UPDATE "HocKy"'):
                first_reserved.set()
                if not release_first.wait(5):
                    raise RuntimeError("test synchronization timed out")
            return result
        def second(execute, sql, params, many, context):
            if sql.startswith('UPDATE "HocKy"'):
                second_attempted.set()
            return execute(sql, params, many, context)
        with self.file_database() as db, ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self.approve_on_connection, db.copy(alias="default"), first)
            try:
                self.assertTrue(first_reserved.wait(5))
                two = pool.submit(self.approve_on_connection, db.copy(alias="default"), second)
                self.assertTrue(second_attempted.wait(5))
            finally:
                release_first.set()
            self.assertEqual(one.result(timeout=10), 3)
            with self.assertRaises(ValidationError):
                two.result(timeout=10)
            self.assertEqual(ScheduleEntry.objects.filter(status="DaDuyet").count(), 3)
