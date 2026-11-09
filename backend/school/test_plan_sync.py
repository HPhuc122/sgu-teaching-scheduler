from copy import deepcopy
from datetime import date, time, timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook

from .auto_schedule import read_auto_files
from .models import (AlgorithmRun, Cohort, CourseGroup, Faculty, GroupCohort, GroupTeachingPlan, Lecturer, LecturerOtherDuty,
                     OffCampusActivity, PendingPlanImport, Period, PlanImportState, ScheduleEntry,
                     Semester, TeachingAssignment, TeachingQualification, UnitRoleAssignment)
from .plan_sync import confirm_import, preview_import
from .planning import save_plan_from_workbooks, workbooks_from_plan
from .sample_data import synthetic_rows, workbook_bytes
from .schedule_queue import enqueue_schedule, process_next_run


class PlanFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("sync_admin")
        cls.semester = Semester.objects.create(name="Đồng bộ", academic_year="2027-2028", number=1,
            start_date=date(2027, 1, 4), end_date=date(2027, 1, 17), week_count=2)
        Period.objects.bulk_create([Period(id=n, block="Sang" if n <= 5 else "Chieu",
            start_time=time(7), end_time=time(8)) for n in range(1, 14)])

    def rows(self, count=3, scenario="feasible"):
        rows = synthetic_rows(sessions=count, semester_name=self.semester.name, weeks=2, seed=7, scenario=scenario)
        courses, teachers = rows["courses"], rows["lecturers"]
        for index, demand in enumerate(courses["BuoiHocYeuCau"]):
            teacher = next(t for t, course in teachers["GiangVienHocPhan"] if course == demand[0]) if index == 0 else ""
            courses["BuoiHocYeuCau"][index] = (*demand, teacher, "TH" if demand[6] == "MayTinh" else "LT", 4)
        for group in courses["NhomHocPhan"]:
            courses["KeHoachMoNhom"].append((group[0], group[2], group[3], 1, "Khóa mô phỏng", 30, 0, 30, "0.8", ""))
        courses["HoatDongNgoaiTruong"].append(("HD1", courses["NhomHocPhan"][0][-1], "Khóa mô phỏng", "ĐH",
            "Thực tập mô phỏng", "Cơ sở", "2027-01-04", "2027-01-04", 35, 1))
        teachers["CongTacKhac"].append((courses["BuoiHocYeuCau"][0][8], "CT1", "Công tác mô phỏng", "KHAC", 10))
        return rows

    def files(self, rows):
        return {kind: SimpleUploadedFile(f"{kind}.xlsx", workbook_bytes(kind, data)) for kind, data in rows.items()}

    def preview(self, rows):
        return preview_import(self.semester.pk, self.files(rows), self.admin)

    def omit_last_group(self, rows):
        rows = deepcopy(rows)
        courses = rows["courses"]
        removed = courses["NhomHocPhan"].pop()
        key = removed[0], removed[2], removed[3]
        courses["BuoiHocYeuCau"] = [r for r in courses["BuoiHocYeuCau"] if r[:3] != key]
        courses["KeHoachMoNhom"] = [r for r in courses["KeHoachMoNhom"] if r[:3] != key]
        return rows


class PlanSynchronizationTests(PlanFixture):
    def test_preview_writes_only_pending_input_and_repeat_is_idempotent(self):
        rows = self.rows()
        pending = self.preview(rows)
        self.assertFalse(Faculty.objects.exists())
        self.assertFalse(TeachingAssignment.objects.exists())
        self.assertFalse(PlanImportState.objects.exists())
        self.assertTrue(pending.summary["added"])
        confirm_import(pending.pk, self.admin)
        self.assertFalse(PendingPlanImport.objects.exists())
        ids = list(TeachingAssignment.objects.order_by("pk").values_list("pk", flat=True))
        pending = self.preview(rows)
        self.assertEqual(pending.summary, dict(added=[], updated=[], missing=[], removable_count=0))
        confirm_import(pending.pk, self.admin)
        self.assertEqual(list(TeachingAssignment.objects.order_by("pk").values_list("pk", flat=True)), ids)
        self.assertEqual(OffCampusActivity.objects.count(), 1)
        self.assertEqual(LecturerOtherDuty.objects.count(), 1)

    def test_detect_updates_additions_and_missing_entire_groups_before_confirmation(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        changed = self.omit_last_group(rows)
        first = changed["courses"]["BuoiHocYeuCau"][0]
        changed["courses"]["BuoiHocYeuCau"][0] = (*first[:4], 3, *first[5:])
        changed["courses"]["BuoiHocYeuCau"].append((*first[:3], "EXTRA", *first[4:]))
        pending = self.preview(changed)
        self.assertTrue(pending.summary["added"])
        self.assertTrue(pending.summary["updated"])
        self.assertEqual(pending.summary["removable_count"], 3)
        self.assertEqual(TeachingAssignment.objects.count(), 3)
        confirm_import(pending.pk, self.admin, remove_missing=True)
        self.assertEqual(TeachingAssignment.objects.count(), 3)
        self.assertEqual(GroupTeachingPlan.objects.count(), 2)
        self.assertEqual(TeachingAssignment.objects.get(fixed_lecturer__isnull=False, request_code=first[3]).period_count, 3)

    def test_missing_is_retained_by_default_and_direct_import_never_deletes(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        changed = self.omit_last_group(rows)
        save_plan_from_workbooks(self.semester.pk, self.files(changed))
        self.assertEqual(TeachingAssignment.objects.count(), 3)
        confirm_import(self.preview(changed).pk, self.admin)
        self.assertEqual(TeachingAssignment.objects.count(), 3)

    def test_unknown_and_manually_modified_missing_rows_cannot_be_deleted(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        last = TeachingAssignment.objects.order_by("pk").last()
        last.component = "BT"
        last.save(update_fields=["component"])
        unknown = TeachingAssignment.objects.create(group=last.group, request_code="MANUAL", period_count=2, weeks=[1])
        pending = self.preview(self.omit_last_group(rows))
        protected = {item["key"] for item in pending.summary["missing"] if not item["removable"]}
        self.assertIn(f"teachingassignment:{last.pk}", protected)
        self.assertIn(f"teachingassignment:{unknown.pk}", protected)
        self.assertEqual(pending.summary["removable_count"], 0)
        confirm_import(pending.pk, self.admin, remove_missing=True)
        self.assertEqual(TeachingAssignment.objects.filter(pk__in=[last.pk, unknown.pk]).count(), 2)
        self.assertTrue(GroupTeachingPlan.objects.filter(group=last.group).exists())

    def test_legacy_rows_are_not_adopted_as_excel_owned(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        PlanImportState.objects.all().delete()  # Simulate a database predating provenance.
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        pending = self.preview(self.omit_last_group(rows))
        self.assertEqual(pending.summary["removable_count"], 0)
        confirm_import(pending.pk, self.admin, remove_missing=True)
        self.assertEqual(TeachingAssignment.objects.count(), 3)

    def test_manual_fixed_assignment_cannot_be_overwritten_and_transaction_rolls_back(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        assignment = TeachingAssignment.objects.filter(fixed_lecturer__isnull=False).get()
        other = Lecturer.objects.exclude(pk=assignment.lecturer_id).first()
        assignment.fixed_lecturer = other
        assignment.lecturer = other
        assignment.save(update_fields=["fixed_lecturer", "lecturer"])
        original_name = Faculty.objects.order_by("pk").first().name
        rows["courses"]["Khoa"][0] = (rows["courses"]["Khoa"][0][0], "Tên đổi trong Excel")
        with self.assertRaisesMessage(ValueError, "đã sửa thủ công"):
            self.preview(rows)
        assignment.refresh_from_db()
        self.assertEqual(assignment.fixed_lecturer, other)
        self.assertEqual(Faculty.objects.order_by("pk").first().name, original_name)
        self.assertFalse(PendingPlanImport.objects.exists())

    def test_manual_metadata_is_not_reclassified_when_metadata_sheet_is_absent(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        plan = GroupTeachingPlan.objects.order_by("pk").last()
        plan.note = "Sửa thủ công"
        plan.save(update_fields=["note"])
        rows["courses"]["KeHoachMoNhom"] = []
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        pending = self.preview(self.omit_last_group(rows))
        item = next(item for item in pending.summary["missing"] if item["key"] == f"groupteachingplan:{plan.pk}")
        self.assertFalse(item["removable"])

    def test_confirm_rechecks_stale_state_expiry_actor_and_replay(self):
        pending = self.preview(self.rows())
        self.semester.name = "Đã đổi"
        self.semester.save(update_fields=["name"])
        with self.assertRaisesMessage(ValueError, "Dữ liệu đã thay đổi"):
            confirm_import(pending.pk, self.admin)
        self.assertFalse(TeachingAssignment.objects.exists())
        self.semester.name = "Đồng bộ"
        self.semester.save(update_fields=["name"])
        PendingPlanImport.objects.filter(pk=pending.pk).update(created_at=timezone.now() - timedelta(minutes=31))
        with self.assertRaisesMessage(ValueError, "hết hạn"):
            confirm_import(pending.pk, self.admin)
        pending = self.preview(self.rows())
        self.assertEqual(PendingPlanImport.objects.count(), 1)
        other = get_user_model().objects.create_superuser("other_admin")
        with self.assertRaises(PendingPlanImport.DoesNotExist):
            confirm_import(pending.pk, other)
        confirm_import(pending.pk, self.admin)
        with self.assertRaises(PendingPlanImport.DoesNotExist):
            confirm_import(pending.pk, self.admin)

    def test_locked_scheduled_and_active_semesters_are_protected(self):
        pending = self.preview(self.rows())
        self.semester.status = "DaKhoa"
        self.semester.save(update_fields=["status"])
        with self.assertRaisesMessage(ValueError, "đã khóa"):
            self.preview(self.rows())
        with self.assertRaisesMessage(ValueError, "đã thay đổi"):
            confirm_import(pending.pk, self.admin, remove_missing=True)
        self.semester.status = "DangMo"
        self.semester.save(update_fields=["status"])
        run = enqueue_schedule(self.semester.pk, self.files(self.rows()), self.admin)
        with self.assertRaisesMessage(ValueError, "phiên xếp lịch"):
            self.preview(self.rows())
        run.queue_item.delete()
        save_plan_from_workbooks(self.semester.pk, self.files(self.rows()))
        assignment = TeachingAssignment.objects.first()
        entry = ScheduleEntry.objects.create(group=assignment.group, lecturer=assignment.lecturer,
            day=2, start_period_id=1, period_count=2, request_code=assignment.request_code, status="DaDuyet")
        with self.assertRaisesMessage(ValueError, "đã có lịch"):
            self.preview(self.omit_last_group(self.rows()))
        self.assertTrue(ScheduleEntry.objects.filter(pk=entry.pk, status="DaDuyet").exists())

    def test_missing_activities_and_duties_require_confirmation(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        rows["courses"]["HoatDongNgoaiTruong"] = []
        rows["lecturers"]["CongTacKhac"] = []
        pending = self.preview(rows)
        self.assertEqual(pending.summary["removable_count"], 2)
        confirm_import(pending.pk, self.admin, remove_missing=True)
        self.assertFalse(OffCampusActivity.objects.exists())
        self.assertFalse(LecturerOtherDuty.objects.exists())

    def test_removed_class_link_requires_confirmation_and_unknown_links_are_kept(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        group = TeachingAssignment.objects.get(fixed_lecturer__isnull=False).group
        manual_cohort = Cohort.objects.create(semester=self.semester, name="LỚP_THỦ_CÔNG")
        manual_link = GroupCohort.objects.create(group=group, cohort=manual_cohort)
        original = rows["courses"]["NhomHocPhan"][0]
        rows["courses"]["NhomHocPhan"][0] = (*original[:-1], "LỚP_MỚI")
        rows["courses"]["HoatDongNgoaiTruong"] = []
        pending = self.preview(rows)
        missing = [item for item in pending.summary["missing"] if item["key"].startswith("groupcohort:")]
        self.assertEqual(len(missing), 2)
        unknown = next(item for item in missing if item["key"] == f"groupcohort:{manual_link.pk}")
        self.assertFalse(unknown["removable"])
        self.assertTrue(any(item["removable"] for item in missing))
        confirm_import(pending.pk, self.admin, remove_missing=True)
        self.assertFalse(GroupCohort.objects.filter(cohort__name=original[-1]).exists())
        self.assertTrue(GroupCohort.objects.filter(cohort__name="LỚP_MỚI").exists())
        self.assertTrue(GroupCohort.objects.filter(pk=manual_link.pk).exists())

    def test_missing_session_in_a_retained_group_is_deleted_only_on_confirmation(self):
        rows = self.rows()
        extended = deepcopy(rows)
        first = extended["courses"]["BuoiHocYeuCau"][0]
        extended["courses"]["BuoiHocYeuCau"].append((*first[:3], "EXTRA", *first[4:]))
        save_plan_from_workbooks(self.semester.pk, self.files(extended))
        pending = self.preview(rows)
        self.assertEqual(pending.summary["removable_count"], 1)
        self.assertEqual(TeachingAssignment.objects.count(), 4)
        confirm_import(pending.pk, self.admin, remove_missing=True)
        self.assertEqual(TeachingAssignment.objects.count(), 3)
        self.assertFalse(TeachingAssignment.objects.filter(request_code="EXTRA").exists())

    def test_shared_catalog_change_cannot_modify_another_semesters_approved_report(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        assignment = TeachingAssignment.objects.get(fixed_lecturer__isnull=False)
        other_semester = Semester.objects.create(name="Đã duyệt", academic_year="2026-2027", number=1,
            start_date=date(2026, 1, 5), end_date=date(2026, 1, 18), week_count=2)
        group = CourseGroup.objects.create(course=assignment.group.course, semester=other_semester,
            code="APPROVED", group="01", capacity=35)
        ScheduleEntry.objects.create(group=group, lecturer=assignment.lecturer, day=2,
            start_period_id=1, period_count=2, status="DaDuyet")
        index = next(i for i, row in enumerate(rows["lecturers"]["GiangVien"]) if row[0] == assignment.lecturer.employee_code)
        row = rows["lecturers"]["GiangVien"][index]
        rows["lecturers"]["GiangVien"][index] = (*row, "THINH_GIANG", "", "", "")
        with self.assertRaisesMessage(ValueError, "danh mục đang được lịch đã duyệt"):
            self.preview(rows)
        assignment.lecturer.refresh_from_db()
        self.assertEqual(assignment.lecturer.source_kind, "CO_HUU")

    def test_confirm_failure_rolls_back_catalog_plan_and_keeps_preview(self):
        pending = self.preview(self.rows())
        with patch("school.plan_sync.finish_import", side_effect=ValueError("Lỗi giữa giao dịch")):
            with self.assertRaisesMessage(ValueError, "Lỗi giữa giao dịch"):
                confirm_import(pending.pk, self.admin)
        self.assertFalse(Faculty.objects.exists())
        self.assertFalse(TeachingAssignment.objects.exists())
        self.assertTrue(PendingPlanImport.objects.filter(pk=pending.pk).exists())

    def test_preview_confirm_cancel_and_invalid_ids_on_interface(self):
        self.client.force_login(self.admin)
        response = self.client.post("/admin/auto-schedule/", {"action": "save_plan", "semester": self.semester.pk, **self.files(self.rows())})
        self.assertContains(response, "Chưa áp dụng thay đổi")
        self.assertFalse(TeachingAssignment.objects.exists())
        pending = response.context["plan_preview"]
        response = self.client.post("/admin/auto-schedule/", {"action": "confirm_plan", "preview_id": pending.pk})
        self.assertRedirects(response, f"/admin/teaching-plans/?semester={self.semester.pk}")
        pending = self.preview(self.rows())
        response = self.client.post("/admin/auto-schedule/", {"action": "cancel_plan", "preview_id": pending.pk})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PendingPlanImport.objects.exists())
        for invalid in ("bad-id", "", "00000000-0000-0000-0000-000000000000"):
            response = self.client.post("/admin/auto-schedule/", {"action": "confirm_plan", "preview_id": invalid})
            self.assertEqual(response.status_code, 400)

    def test_faculty_cannot_import_or_confirm_global_workbooks(self):
        pending = self.preview(self.rows())
        user = get_user_model().objects.create_user("faculty_sync", is_staff=True)
        faculty = Faculty.objects.create(code="F", name="Khoa")
        UnitRoleAssignment.objects.create(user=user, role="FACULTY", faculty=faculty, can_manage=True)
        self.client.force_login(user)
        for action in ("save_plan", "confirm_plan", "cancel_plan"):
            response = self.client.post("/admin/auto-schedule/", {"action": action, "semester": self.semester.pk, "preview_id": pending.pk})
            self.assertEqual(response.status_code, 403)

    def test_roundtrip_includes_activities_duties_and_preserves_chosen_unfixed_teacher(self):
        rows = self.rows()
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        assignment = TeachingAssignment.objects.filter(fixed_lecturer__isnull=True).first()
        assignment.lecturer = Lecturer.objects.first()
        assignment.save(update_fields=["lecturer"])
        save_plan_from_workbooks(self.semester.pk, self.files(rows))
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.lecturer_id)
        parsed = read_auto_files(workbooks_from_plan(self.semester))
        self.assertEqual(len(parsed["courses"]["HoatDongNgoaiTruong"]), 1)
        self.assertEqual(len(parsed["lecturers"]["CongTacKhac"]), 1)


@override_settings(QUALITY_SEARCH_BUDGET_SECONDS=60, QUALITY_SEARCH_MAX_STARTS=1,
                   QUALITY_CP_MODEL_SECONDS_PER_SESSION=1000, QUALITY_GD_EXTRA_PATHS=0)
class PlanWorkflowScaleTests(PlanFixture):
    def _workflow(self, count):
        rows = self.rows(count)
        confirm_import(self.preview(rows).pk, self.admin)
        self.assertEqual(TeachingAssignment.objects.count(), count)
        self.assertEqual(TeachingAssignment.objects.filter(fixed_lecturer__isnull=False).count(), 1)
        self.assertEqual(TeachingAssignment.objects.filter(lecturer__isnull=True).count(), count - 1)
        self.client.force_login(self.admin)
        unassigned = TeachingAssignment.objects.filter(lecturer__isnull=True).select_related("group").first()
        qualified = TeachingQualification.objects.filter(course=unassigned.group.course).first()
        response = self.client.post(f"/admin/teaching-plans/assignment/{unassigned.pk}/", {
            "fixed_lecturer": qualified.lecturer_id, "component": unassigned.component, "reported_periods": 4})
        self.assertEqual(response.status_code, 302)
        fixed_assignments = list(TeachingAssignment.objects.filter(fixed_lecturer__isnull=False))
        self.assertEqual(len(fixed_assignments), 2)
        # Use the real queue, solvers, independent audit and approval services.
        queued = enqueue_schedule(self.semester.pk, workbooks_from_plan(self.semester), self.admin)
        run = process_next_run()
        self.assertEqual(run.pk, queued.pk)
        self.assertIn(run.status, ("HEURISTIC", "FEASIBLE", "OPTIMAL"), str(run.optimization_trials))
        self.assertEqual(run.entries.count(), count)
        for fixed in fixed_assignments:
            entry = run.entries.get(group=fixed.group, request_code=fixed.request_code)
            self.assertEqual(entry.lecturer_id, fixed.fixed_lecturer_id)
        self.assertFalse(TeachingAssignment.objects.filter(lecturer__isnull=True).exists())
        self.assertFalse(run.entries.filter(group__cohort_links__cohort__name=rows["courses"]["NhomHocPhan"][0][-1], day=2).exists())
        self.client.force_login(self.admin)
        review = self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}&run={run.pk}")
        self.assertEqual(review.status_code, 200)
        approved = self.client.post("/admin/auto-schedule/", {"action": "approve", "run_id": run.pk})
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(run.entries.filter(status="DaDuyet").count(), count)
        exported_periods = 0
        exported_reported = 0
        for faculty in Faculty.objects.all():
            response = self.client.get("/admin/teaching-plans/", {"year": self.semester.academic_year,
                "faculty": faculty.pk, "download": "xlsx", "page": 2})
            self.assertEqual(response.status_code, 200)
            book = load_workbook(BytesIO(response.content))
            self.assertEqual(set(book.sheetnames), {"Mau1_HK1", "Mau1_HK2", "Mau1_HK3", "Mau2", "Mau3", "Mau4", "Mau5"})
            for row in book["Mau1_HK1"].iter_rows(min_row=6, values_only=True):
                exported_periods += row[16]
                exported_reported += row[17]
        self.assertEqual(exported_periods, count * 4)
        self.assertEqual(exported_reported, count * 4)
        self.assertEqual(AlgorithmRun.objects.count(), 1)

    def test_240_session_workflow(self):
        self._workflow(240)

    def test_480_session_workflow(self):
        self._workflow(480)

    def test_960_session_workflow(self):
        self._workflow(960)

    def test_infeasible_inputs_never_replace_or_approve_an_existing_timetable(self):
        rows = self.rows(3, scenario="infeasible")
        rows["courses"]["HoatDongNgoaiTruong"] = []
        confirm_import(self.preview(rows).pk, self.admin)
        queued = enqueue_schedule(self.semester.pk, workbooks_from_plan(self.semester), self.admin)
        run = process_next_run()
        self.assertEqual(run.pk, queued.pk)
        self.assertEqual(run.status, "INFEASIBLE", run.message)
        self.assertEqual(TeachingAssignment.objects.count(), 3)
        self.assertFalse(ScheduleEntry.objects.exists())
        self.client.force_login(self.admin)
        response = self.client.post("/admin/auto-schedule/", {"action": "approve", "run_id": run.pk})
        self.assertEqual(response.status_code, 400)
