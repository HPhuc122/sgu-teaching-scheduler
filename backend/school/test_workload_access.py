"""Integration coverage for simulated workload and backend unit authorization."""
from decimal import Decimal
from io import BytesIO
from time import monotonic
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from openpyxl import load_workbook
from rest_framework.test import APIClient

from .auto_schedule import solve, run_from_workbooks, approve_algorithm_run
from .great_deluge import improve
from .models import (AlgorithmRun, Course, CourseGroup, Department, Faculty, Lecturer, ScheduleEntry,
                     ScheduleWeek, TeachingQualification, TeachingQuota, WorkloadPolicy, ConversionRule,
                     UnitRoleAssignment, Cohort, Program)
from .sample_data import synthetic_rows, workbook_bytes
from .schedule_queue import enqueue_schedule, process_next_run
from .services import approve_schedule_entries, save_schedule_entry
from .soft_score import SoftScorer
from .solution_audit import audit_solution
from .test_quality_search import QualityFixture
from .workload import workload_rows, save_configuration


class WorkloadTests(QualityFixture):
    def enable(self, weight=1):
        WorkloadPolicy.objects.create(semester=self.semester, default_factor=1, balance_weight=weight)
        TeachingQuota.objects.create(semester=self.semester, lecturer=self.teacher, target_units=2)
        TeachingQuota.objects.create(semester=self.semester, lecturer=self.other, target_units=8)
        return SoftScorer(self.semester, self.teacher_map, self.pairs, self.preferences)

    def entry(self, teacher=None):
        entry = ScheduleEntry.objects.create(group=self.group, lecturer=teacher or self.teacher, room=self.room,
                    day=6, start_period_id=1, period_count=2, status="DaDuyet")
        ScheduleWeek.objects.bulk_create([ScheduleWeek(entry=entry, week=w) for w in (1, 2)])
        return entry

    def test_actual_periods_conversion_fraction_and_difference(self):
        self.entry()
        WorkloadPolicy.objects.create(semester=self.semester, default_factor=Decimal("1.50"))
        TeachingQuota.objects.create(semester=self.semester, lecturer=self.teacher, target_units=10,
                                    allocation_fraction=Decimal("0.50"))
        row = workload_rows(self.semester, [self.teacher])[0]
        self.assertEqual((row["actual_periods"], row["converted_units"], row["effective_quota"], row["difference"]),
                         (4, Decimal(6), Decimal(5), Decimal(1)))

    def test_missing_configuration_is_explicit_and_rule_overrides_default(self):
        self.entry()
        row = workload_rows(self.semester, [self.teacher])[0]
        self.assertIsNone(row["converted_units"])
        self.assertTrue(row["missing_quota"])
        self.assertEqual(row["missing_factors"], [self.course.kind])
        WorkloadPolicy.objects.create(semester=self.semester, default_factor=1)
        ConversionRule.objects.create(semester=self.semester, course_kind=self.course.kind, factor=2)
        self.assertEqual(workload_rows(self.semester, [self.teacher])[0]["converted_units"], 8)

    def test_disabled_objective_preserves_legacy_score(self):
        scorer = self.enable(weight=0)
        self.assertEqual(scorer.objective_version, "soft_v1")
        self.assertEqual(scorer.score(self.solution()), self.scoring.score(self.solution()))

    def test_balance_uses_quota_not_equal_periods(self):
        scorer = self.enable()
        self.assertEqual(scorer.score(self.solution()), 9)  # base 1 + ceil(4²/2)
        self.assertEqual(scorer.score(self.solution(teacher=self.other)), 4)  # base 2 + ceil(4²/8)

    def test_move_delta_and_incremental_state_match_independent_full_score(self):
        scorer = self.enable(weight=3)
        initial = self.solution()
        loads = scorer.balance.loads(initial)
        for teacher in (self.other, self.teacher, self.other):
            candidate = self.solution(teacher=teacher)[0]
            score = scorer.score(initial) + scorer.move_delta(initial[0], candidate, loads)
            scorer.accept_move(initial[0], candidate, loads)
            initial = [candidate]
            self.assertEqual(score, scorer.score(initial))
            self.assertEqual(loads, scorer.balance.loads(initial))

    def test_real_cp_sat_matches_new_objective_and_audit(self):
        scorer = self.enable()
        metrics = {}
        result, status, score = solve(self.semester, [self.demand], self.room_map, self.teacher_map, [], [], self.pairs,
                    scoring=scorer, preferences=self.preferences, generation_policy="model_first", cp_policy="fixed_window",
                    deadline=monotonic()+8, num_search_workers=1, telemetry=metrics)
        self.assertTrue(metrics["cp_called"])
        self.assertIn(status, ("OPTIMAL", "FEASIBLE", "HEURISTIC"))
        self.assertEqual(score, scorer.score(result))
        self.assertEqual(score, 4)
        audit_solution(self.semester, [self.demand], result, self.room_map, self.teacher_map, [], [], self.pairs,
                       preferences=self.preferences)

    def test_real_gd_uses_global_workload_delta_and_keeps_hard_rules(self):
        scorer = self.enable()
        result, before, after = improve(self.semester, self.solution(), self.room_map, self.teacher_map, [], [], self.pairs,
                     scoring=scorer, preferences=self.preferences, seed=42, time_limit=2)
        self.assertEqual(before, 9)
        self.assertLess(after, before)
        self.assertEqual(after, scorer.score(result))
        audit_solution(self.semester, [self.demand], result, self.room_map, self.teacher_map, [], [], self.pairs,
                       preferences=self.preferences)

    def test_fixed_loads_and_snapshot_remain_stable_after_configuration_change(self):
        self.enable()
        self.entry()
        scorer = SoftScorer(self.semester, self.teacher_map, self.pairs, self.preferences)
        initial = self.solution(day=2)
        expected = scorer.score(initial)
        self.assertEqual(scorer.balance.fixed[self.teacher.pk], 400)
        WorkloadPolicy.objects.filter(semester=self.semester).update(balance_weight=0)
        restored = SoftScorer(self.semester, self.teacher_map, self.pairs, self.preferences,
                              quality_snapshot=scorer.quality_snapshot)
        self.assertEqual(restored.score(initial), expected)

    def test_enabled_objective_rejects_missing_quota_or_factor(self):
        policy = WorkloadPolicy.objects.create(semester=self.semester, balance_weight=1)
        with self.assertRaisesMessage(ValueError, "thiếu định mức"):
            SoftScorer(self.semester, self.teacher_map, self.pairs)
        for teacher in self.teacher_map.values():
            TeachingQuota.objects.create(semester=self.semester, lecturer=teacher, target_units=10)
        scorer = SoftScorer(self.semester, self.teacher_map, self.pairs)
        with self.assertRaisesMessage(ValueError, "Thiếu hệ số"):
            scorer.score(self.solution())

    def test_invalid_configuration_and_locked_semester_are_rejected(self):
        for value in (0, -1, 11):
            with self.assertRaises(ValidationError):
                ConversionRule(semester=self.semester, course_kind=self.course.kind, factor=value).full_clean()
        admin = get_user_model().objects.create_superuser("config_admin")
        self.semester.status = "DaKhoa"
        self.semester.save()
        from rest_framework.exceptions import ValidationError as ApiError
        with self.assertRaises(ApiError):
            save_configuration(WorkloadPolicy(semester=self.semester, default_factor=1), admin)

    def test_configuration_cannot_be_moved_out_of_locked_semester(self):
        from .models import Semester
        policy = WorkloadPolicy.objects.create(semester=self.semester, default_factor=1)
        self.semester.status = "DaKhoa"
        self.semester.save()
        other = Semester.objects.create(name="OPEN", start_date=self.semester.start_date,
                    end_date=self.semester.end_date, week_count=self.semester.week_count)
        admin = get_user_model().objects.create_superuser("locked_move")
        api = APIClient()
        api.force_authenticate(admin)
        self.assertEqual(api.patch(f"/api/workload-policies/{policy.pk}/", {"semester":other.pk}, format="json").status_code,400)
        policy.refresh_from_db()
        self.assertEqual(policy.semester_id,self.semester.pk)

    @override_settings(QUALITY_SEARCH_BUDGET_SECONDS=3, QUALITY_GD_EXTRA_PATHS=1)
    def test_queue_persists_new_snapshot_and_recomputed_score(self):
        admin = get_user_model().objects.create_superuser("queue_workload")
        data = synthetic_rows(sessions=3, semester_name=self.semester.name, seed=7)
        # A zero weight queue proves default compatibility; actual v2 persistence uses existing fixture uploads below.
        files = {k: SimpleUploadedFile(f"{k}.xlsx", workbook_bytes(k,v)) for k,v in data.items()}
        queued = enqueue_schedule(self.semester.pk, files, admin)
        run = process_next_run()
        self.assertEqual(run.pk, queued.pk)
        self.assertEqual(run.objective_version, "soft_v1")
        self.assertEqual(run.quality_snapshot["weight"], 0)

    def prepare_uploaded_catalog(self):
        from .auto_schedule import read_auto_files, _prepare_inputs, _create_catalog
        rows = synthetic_rows(sessions=3, semester_name=self.semester.name, seed=7)
        files = {k: SimpleUploadedFile(f"{k}.xlsx", workbook_bytes(k,v)) for k,v in rows.items()}
        parsed = read_auto_files(files)
        demands, rb, tb = _prepare_inputs(self.semester, parsed)
        demands, rooms, teachers = _create_catalog(self.semester, parsed, demands, rb, tb)
        pairs = {(r["ma_vien_chuc"],r["ma_mon_hoc"]) for r in parsed["lecturers"]["GiangVienHocPhan"]}
        return rows, demands, rooms, teachers, pairs, rb, tb

    def upload(self, rows):
        return {k: SimpleUploadedFile(f"{k}.xlsx", workbook_bytes(k,v)) for k,v in rows.items()}

    @override_settings(QUALITY_SEARCH_BUDGET_SECONDS=4, QUALITY_GD_EXTRA_PATHS=1)
    def test_v2_saved_solution_snapshot_recomputes_after_policy_change(self):
        rows, demands, rooms, teachers, pairs, rb, tb = self.prepare_uploaded_catalog()
        WorkloadPolicy.objects.create(semester=self.semester, default_factor="1.50", balance_weight=2)
        for teacher in teachers.values():
            TeachingQuota.objects.create(semester=self.semester, lecturer=teacher, target_units=120)
        admin = get_user_model().objects.create_superuser("v2_persistence")
        queued = enqueue_schedule(self.semester.pk, self.upload(rows), admin)
        run = process_next_run()
        self.assertEqual(run.pk, queued.pk)
        self.assertEqual(run.objective_version, "soft_v2_workload")
        self.assertEqual(run.quality_snapshot["weight"], 2)
        self.assertEqual(run.entry_count, 3)
        from .quality_search import pending_solution
        solution = pending_solution(self.semester, demands)
        audit_solution(self.semester, demands, solution, rooms, teachers, rb, tb, pairs, preferences=[])
        WorkloadPolicy.objects.filter(semester=self.semester).update(default_factor=2, balance_weight=0)
        TeachingQuota.objects.filter(semester=self.semester).update(target_units=1)
        scorer = SoftScorer(self.semester, teachers, pairs, preferences=[], quality_snapshot=run.quality_snapshot)
        self.assertEqual(scorer.score(solution), run.objective)
        self.assertEqual(approve_algorithm_run(run.pk, admin), 3)

    @override_settings(QUALITY_SEARCH_BUDGET_SECONDS=3, QUALITY_GD_EXTRA_PATHS=0)
    def test_real_partial_persistence_error_rolls_back_and_preserves_previous_schedule(self):
        rows, *_ = self.prepare_uploaded_catalog()
        admin = get_user_model().objects.create_superuser("rollback_workload")
        first = run_from_workbooks(self.semester.pk, self.upload(rows), admin)
        original = list(first.entries.order_by("pk").values_list("pk", "lecturer_id", "day", "start_period_id"))
        weeks = ScheduleWeek.objects.count()
        queued = enqueue_schedule(self.semester.pk, self.upload(rows), admin)
        with patch("school.models.ScheduleWeek.objects.bulk_create", side_effect=RuntimeError("disk/insert failure")), \
             patch("school.schedule_queue.log.exception"):
            failed = process_next_run()
        self.assertEqual(failed.status,"ERROR")
        self.assertEqual(list(first.entries.order_by("pk").values_list("pk", "lecturer_id", "day", "start_period_id")),original)
        self.assertEqual(ScheduleWeek.objects.count(),weeks)
        self.assertFalse(failed.entries.exists())

    @override_settings(QUALITY_SEARCH_BUDGET_SECONDS=3, QUALITY_GD_EXTRA_PATHS=0)
    def test_bulk_insert_without_returning_primary_keys_recovers_exact_week_mapping(self):
        rows, *_ = self.prepare_uploaded_catalog()
        admin = get_user_model().objects.create_superuser("pk_fallback")
        original = ScheduleEntry.objects.bulk_create
        def without_ids(entries, **kwargs):
            result = original(entries, **kwargs)
            for entry in entries:
                entry.pk = None
            return result
        with patch("school.models.ScheduleEntry.objects.bulk_create", side_effect=without_ids):
            run = run_from_workbooks(self.semester.pk, self.upload(rows), admin)
        self.assertEqual(run.entry_count,3)
        self.assertTrue(all(e.schedule_weeks.count()==16 for e in run.entries.all()))


class UnitAuthorizationTests(QualityFixture):
    def setUp(self):
        super().setUp()
        users = get_user_model()
        self.admin = users.objects.create_superuser("unit_admin")
        self.faculty_user = users.objects.create_user("faculty_a", is_staff=True)
        self.head = users.objects.create_user("head_a", is_staff=True)
        self.training = users.objects.create_user("training_a", is_staff=True)
        self.viewer = users.objects.create_user("view_a", is_staff=True)
        self.no_scope = users.objects.create_user("no_scope", is_staff=True)
        faculty = self.teacher.department.faculty
        UnitRoleAssignment.objects.create(user=self.faculty_user, role="FACULTY", faculty=faculty, can_manage=True)
        UnitRoleAssignment.objects.create(user=self.head, role="HEAD", department=self.teacher.department, can_manage=True)
        UnitRoleAssignment.objects.create(user=self.training, role="TRAINING", faculty=faculty, can_manage=True)
        UnitRoleAssignment.objects.create(user=self.viewer, role="FACULTY", faculty=faculty)
        self.foreign_faculty = Faculty.objects.create(code="F", name="Foreign Faculty")
        d = Department.objects.create(code="F", name="Foreign Department", faculty=self.foreign_faculty)
        self.foreign_teacher = Lecturer.objects.create(employee_code="FOREIGN", name="Foreign teacher", department=d)
        c = Course.objects.create(code="FOREIGN", name="Foreign course", department=d, credits=2)
        TeachingQualification.objects.create(lecturer=self.foreign_teacher, course=c)
        self.foreign_group = CourseGroup.objects.create(course=c, semester=self.semester, code="FOREIGN", group="1", capacity=20)
        self.own_entry = ScheduleEntry.objects.create(group=self.group, lecturer=self.teacher, room=self.room,
                         day=2, start_period_id=1, period_count=2, status="ChoDuyet")
        self.foreign_entry = ScheduleEntry.objects.create(group=self.foreign_group, lecturer=self.foreign_teacher,
                         room=self.room, day=3, start_period_id=1, period_count=2, status="ChoDuyet")
        for entry in (self.own_entry, self.foreign_entry):
            ScheduleWeek.objects.create(entry=entry, week=1)
        self.api = APIClient()
        self.api.force_authenticate(self.faculty_user)

    def test_scoped_lists_and_direct_foreign_id_read_update_delete(self):
        response = self.api.get("/api/lecturers/")
        self.assertEqual({r["id"] for r in response.data}, {self.teacher.pk, self.other.pk})
        url = f"/api/lecturers/{self.foreign_teacher.pk}/"
        for method, data in (("get", None), ("patch", {"name":"stolen"}), ("delete", None)):
            self.assertEqual(getattr(self.api, method)(url, data, format="json").status_code, 404)

    def test_foreign_relations_and_scope_relocation_are_denied(self):
        response = self.api.post("/api/teaching-quotas/", {"lecturer":self.foreign_teacher.pk,
                    "semester":self.semester.pk,"target_units":"20"}, format="json")
        self.assertEqual(response.status_code, 403)
        response = self.api.patch(f"/api/lecturers/{self.teacher.pk}/",
                                 {"department":self.foreign_teacher.department_id}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_faculty_manage_own_quota_and_readonly_role_cannot_write(self):
        payload = {"lecturer":self.teacher.pk,"semester":self.semester.pk,"target_units":"20"}
        self.assertEqual(self.api.post("/api/teaching-quotas/", payload, format="json").status_code, 201)
        self.api.force_authenticate(self.viewer)
        self.assertEqual(self.api.get("/api/teaching-quotas/").status_code, 200)
        self.assertEqual(self.api.post("/api/teaching-quotas/", {**payload,"lecturer":self.other.pk}, format="json").status_code, 403)

    def test_unassigned_staff_has_no_implicit_global_rights(self):
        self.api.force_authenticate(self.no_scope)
        self.assertEqual(self.api.get("/api/lecturers/").status_code, 403)
        self.client.force_login(self.no_scope)
        for url in ("/admin/auto-schedule/", "/admin/review-schedules/", "/admin/export-assignments/", "/workload/"):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_head_can_propose_but_cannot_approve_or_change_catalog(self):
        self.client.force_login(self.head)
        self.assertRedirects(self.client.get("/portal/"), "/admin/", fetch_redirect_response=False)
        self.api.force_authenticate(self.head)
        self.assertEqual(self.api.patch(f"/api/schedules/{self.own_entry.pk}/", {"day":4}, format="json").status_code, 200)
        self.assertEqual(self.api.patch(f"/api/lecturers/{self.teacher.pk}/", {"name":"x"}, format="json").status_code, 404)
        self.assertEqual(self.api.patch(f"/api/schedules/{self.own_entry.pk}/", {"status":"DaDuyet"}, format="json").status_code, 403)

    def test_training_approves_only_own_unit_and_batch_rolls_back(self):
        with self.assertRaises(PermissionDenied):
            approve_schedule_entries(self.semester.pk, [self.own_entry.pk,self.foreign_entry.pk], actor=self.training)
        self.own_entry.refresh_from_db()
        self.assertEqual(self.own_entry.status, "ChoDuyet")
        self.assertEqual(approve_schedule_entries(self.semester.pk,[self.own_entry.pk],actor=self.training), 1)

    def test_custom_url_filters_exports_and_edit_are_guarded(self):
        self.client.force_login(self.faculty_user)
        for url in (f"/admin/review-schedules/{self.foreign_entry.pk}/edit/",
                    f"/admin/review-schedules/?faculty={self.foreign_faculty.pk}",
                    f"/admin/export-assignments/?faculty={self.foreign_faculty.pk}&semester={self.semester.pk}&action=download",
                    f"/admin/faculty-timetable/?faculty={self.foreign_faculty.pk}&semester={self.semester.pk}",
                    f"/workload/?semester={self.semester.pk}&lecturer={self.foreign_teacher.pk}",
                    "/admin/auth/user/", "/admin/school/unitroleassignment/", "/admin/import-schedule/", "/admin/auto-schedule/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_admin_foreign_object_ids_and_post_foreign_fk_are_denied(self):
        self.client.force_login(self.faculty_user)
        response = self.client.get(f"/admin/school/lecturer/{self.foreign_teacher.pk}/change/")
        self.assertIn(response.status_code, (302,403,404))
        self.assertNotContains(response, "Foreign teacher", status_code=response.status_code)
        response = self.client.post("/admin/school/teachingquota/add/", {"lecturer":self.foreign_teacher.pk,
                    "semester":self.semester.pk,"target_units":"20","allocation_fraction":"1","_save":"save"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TeachingQuota.objects.filter(lecturer=self.foreign_teacher).exists())

    def test_teacher_workload_and_excel_are_self_only(self):
        user = get_user_model().objects.create_user("self_only")
        self.teacher.user = user
        self.teacher.save()
        self.client.force_login(user)
        url = f"/workload/?semester={self.semester.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response,"Foreign teacher")
        book = load_workbook(BytesIO(self.client.get(url+"&action=download").content))
        self.assertEqual(book.active.max_row, 2)
        self.assertEqual(self.client.get(url+f"&lecturer={self.foreign_teacher.pk}").status_code, 403)

    def test_role_scope_constraint_rejects_ambiguous_or_empty_scope(self):
        with self.assertRaises(ValidationError):
            UnitRoleAssignment(user=self.no_scope, role="FACULTY", all_units=True).full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            UnitRoleAssignment.objects.create(user=self.no_scope, role="HEAD")

    def test_account_link_cannot_be_hijacked(self):
        response = self.api.patch(f"/api/lecturers/{self.teacher.pk}/", {"user":self.admin.pk},format="json")
        self.assertEqual(response.status_code,403)

    def test_shared_conversion_policy_write_requires_global_coordinator(self):
        payload={"semester":self.semester.pk,"default_factor":"1.50","balance_weight":1}
        self.assertEqual(self.api.post("/api/workload-policies/",payload,format="json").status_code,403)
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.post("/api/workload-policies/",payload,format="json").status_code,201)

    def test_mixed_roles_do_not_expand_catalog_write_scope(self):
        UnitRoleAssignment.objects.create(user=self.faculty_user, role="HEAD",
                                         department=self.foreign_teacher.department, can_manage=True)
        self.assertEqual(self.api.get(f"/api/lecturers/{self.foreign_teacher.pk}/").status_code,200)
        self.assertEqual(self.api.patch(f"/api/lecturers/{self.foreign_teacher.pk}/",{"name":"x"},format="json").status_code,404)
        self.assertEqual(self.api.patch(f"/api/lecturers/{self.teacher.pk}/",
                         {"department":self.foreign_teacher.department_id},format="json").status_code,403)

    def test_other_catalog_foreign_ids_and_root_creation_are_denied(self):
        for resource, obj in (("departments",self.foreign_teacher.department), ("faculties",self.foreign_faculty),
                              ("courses",self.foreign_group.course),("course-groups",self.foreign_group)):
            for method in ("get","patch","delete"):
                self.assertEqual(getattr(self.api,method)(f"/api/{resource}/{obj.pk}/",{},format="json").status_code,404)
        self.assertEqual(self.api.post("/api/faculties/",{"code":"NEW","name":"new"},format="json").status_code,403)
        self.assertEqual(self.api.post("/api/lecturers/",{"employee_code":"X","name":"x","department":self.foreign_teacher.department_id},format="json").status_code,403)

    def test_unit_exports_and_lists_hide_other_faculties(self):
        self.client.force_login(self.faculty_user)
        url=f"/workload/?semester={self.semester.pk}"
        self.assertNotContains(self.client.get(url),"Foreign teacher")
        book=load_workbook(BytesIO(self.client.get(url+"&action=download").content))
        self.assertNotIn("FOREIGN",[row[0] for row in book.active.iter_rows(values_only=True)])
        response=self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}")
        self.assertNotContains(response,"Foreign teacher")
        self.own_entry.status=self.foreign_entry.status="DaDuyet"
        self.own_entry.save(); self.foreign_entry.save()
        faculty_id=self.teacher.department.faculty_id
        response=self.client.get(f"/admin/export-assignments/?semester={self.semester.pk}&faculty={faculty_id}&action=download")
        self.assertEqual(response.status_code,200)
        book=load_workbook(BytesIO(response.content))
        self.assertEqual(book["PhanCong"].max_row,2)

    def test_cross_unit_teaching_is_visible_consistently_without_granting_write(self):
        self.foreign_entry.lecturer = self.teacher
        self.foreign_entry.status = "DaDuyet"
        self.foreign_entry.save()
        self.own_entry.status = "DaDuyet"
        self.own_entry.save()
        self.client.force_login(self.viewer)
        faculty_id = self.teacher.department.faculty_id
        timetable = self.client.get(f"/admin/faculty-timetable/?semester={self.semester.pk}&faculty={faculty_id}&week=1")
        self.assertContains(timetable, "Foreign course")
        self.assertNotContains(timetable, f'href="/admin/review-schedules/{self.foreign_entry.pk}/edit/"')
        review = self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}&faculty={faculty_id}")
        self.assertEqual(review.context["count"], 2)
        self.assertContains(review, "Foreign course")
        self.assertNotContains(review, 'name="entry_ids"')
        exported = self.client.get(f"/admin/export-assignments/?semester={self.semester.pk}&faculty={faculty_id}")
        self.assertEqual(exported.context["total_entries"], 2)
        self.api.force_authenticate(self.training)
        url = f"/api/schedules/{self.foreign_entry.pk}/"
        self.assertEqual(self.api.get(url).status_code, 200)
        self.assertEqual(self.api.patch(url, {"day": 4}, format="json").status_code, 404)
        self.client.force_login(self.training)
        self.assertEqual(self.client.get(f"/admin/review-schedules/{self.foreign_entry.pk}/edit/").status_code, 403)
        self.foreign_entry.status = "ChoDuyet"
        self.foreign_entry.save()
        with self.assertRaises(PermissionDenied):
            approve_schedule_entries(self.semester.pk, [self.foreign_entry.pk], actor=self.training)
        response = self.client.get(f"/admin/review-schedules/?semester={self.semester.pk}")
        cross = next(e for e in response.context["page"] if e.pk == self.foreign_entry.pk)
        self.assertFalse(cross.can_edit)
        self.assertFalse(cross.can_approve)

    def test_unassigned_sessions_are_visible_only_to_the_course_unit(self):
        from .access import scoped
        self.own_entry.lecturer = None
        self.own_entry.save()
        self.foreign_entry.lecturer = None
        self.foreign_entry.save()
        entries = scoped(ScheduleEntry.objects.all(), self.viewer)
        self.assertEqual(list(entries.values_list("pk", flat=True)), [self.own_entry.pk])
        weeks = scoped(ScheduleWeek.objects.all(), self.viewer)
        self.assertEqual(list(weeks.values_list("entry_id", flat=True)), [self.own_entry.pk])

    def test_export_completeness_is_limited_to_selected_faculty_for_multi_unit_users(self):
        UnitRoleAssignment.objects.create(user=self.viewer, role="FACULTY", faculty=self.foreign_faculty)
        self.own_entry.status = "DaDuyet"
        self.own_entry.request_code = "LT1"
        self.own_entry.save()
        AlgorithmRun.objects.create(semester=self.semester, status="OPTIMAL", created_by=self.admin,
            demand_snapshot=[{"group_id": group.pk, "code": "LT1", "course_code": group.course.code,
                              "group": group.group, "lab_group": "", "excel_row": 2}
                             for group in (self.group, self.foreign_group)])
        for user in (self.viewer, self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                url = f"/admin/export-assignments/?semester={self.semester.pk}&faculty="
                own = self.client.get(url + str(self.teacher.department.faculty_id))
                check = own.context["completeness"]
                self.assertTrue(check["ready"])
                self.assertEqual(check["expected"], 1)
                self.assertEqual(check["counts"]["missing"], 0)
                self.assertEqual(check["pending_entries"], [])
                self.assertNotContains(own, "Foreign course")
                foreign = self.client.get(url + str(self.foreign_faculty.pk))
                check = foreign.context["completeness"]
                self.assertFalse(check["ready"])
                self.assertEqual(check["expected"], 1)
                self.assertEqual(check["counts"]["missing"], 1)
                self.assertEqual(len(check["pending_entries"]), 1)
                book = load_workbook(BytesIO(self.client.get(
                    url + str(self.teacher.department.faculty_id) + "&action=download").content))
                info = dict(row for row in book["ThongTin"].values if len(row) == 2)
                self.assertEqual(info["Kiểm tra phạm vi đơn vị"], "Đủ theo buổi yêu cầu đã lưu")
                self.assertIn(self.teacher.department.faculty.name, info["Phạm vi kiểm tra"])
                book.close()

    def test_role_screens_hide_actions_the_user_cannot_perform(self):
        review_url = f"/admin/review-schedules/?semester={self.semester.pk}"
        for user, can_edit, can_approve in ((self.viewer, False, False),
                                           (self.head, True, False),
                                           (self.faculty_user, True, False),
                                           (self.training, True, True)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                for url in ("/admin/", review_url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    for href in ('href="/admin/auto-schedule/', 'href="/admin/import-catalog/',
                                 'href="/admin/import-schedule/'):
                        self.assertNotContains(response, href)
                response = self.client.get(review_url)
                self.assertEqual(response.context["can_approve_entries"], can_approve)
                edit_link = f'href="/admin/review-schedules/{self.own_entry.pk}/edit/"'
                if can_edit:
                    self.assertContains(response, edit_link)
                else:
                    self.assertNotContains(response, edit_link)
                self.assertEqual('name="entry_ids"' in response.content.decode(), can_approve)
                self.assertEqual('class="approve"' in response.content.decode(), can_approve)
        self.semester.status = "DaKhoa"
        self.semester.save()
        response = self.client.get(review_url)
        self.assertNotContains(response, 'name="entry_ids"')
        self.assertNotContains(response, f'href="/admin/review-schedules/{self.own_entry.pk}/edit/"')

    def test_global_readonly_role_can_view_runs_without_mutation_controls(self):
        UnitRoleAssignment.objects.create(user=self.viewer, role="TRAINING", all_units=True)
        run = AlgorithmRun.objects.create(semester=self.semester, status="OPTIMAL",
            created_by=self.admin, entry_count=1)
        self.own_entry.algorithm_run = run
        self.own_entry.save()
        self.client.force_login(self.viewer)
        response = self.client.get(f"/admin/auto-schedule/?run={run.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_approve"])
        self.assertNotContains(response, 'id="scheduleUploadForm"')
        self.assertNotContains(response, 'value="create_semester"')
        self.assertNotContains(response, "Duyệt toàn bộ phương án")
        self.assertEqual(self.client.post("/admin/auto-schedule/", {
            "action": "create_semester", "name": "forbidden",
        }).status_code, 403)

    def test_scoped_export_warns_and_includes_own_lecturers_cross_unit_teaching(self):
        self.own_entry.status = "DaDuyet"
        self.own_entry.save()
        self.foreign_entry.lecturer = self.teacher
        self.foreign_entry.status = "DaDuyet"
        self.foreign_entry.save()
        self.client.force_login(self.viewer)
        faculty_id = self.teacher.department.faculty_id
        url = f"/admin/export-assignments/?semester={self.semester.pk}&faculty={faculty_id}"
        response = self.client.get(url)
        self.assertEqual(response.context["total_entries"], 2)
        self.assertFalse(response.context["completeness"]["ready"])
        self.assertContains(response, "Phạm vi đơn vị được phân quyền")
        self.assertContains(response, "Chưa xác nhận bảng phân công hoàn chỉnh")
        self.assertNotContains(response, "Foreign teacher")
        book = load_workbook(BytesIO(self.client.get(url + "&action=download").content))
        self.assertEqual(book["PhanCong"].max_row, 3)
        self.assertIn("CHƯA XÁC NHẬN ĐẦY ĐỦ", str(list(book["ThongTin"].values)))
        self.assertIn("Kiểm tra phạm vi đơn vị", str(list(book["ThongTin"].values)))
        book.close()

    def test_scoped_completeness_does_not_leak_unrelated_demand_or_teachers(self):
        AlgorithmRun.objects.create(semester=self.semester, status="OPTIMAL", created_by=self.admin,
            demand_snapshot=[{"group_id": self.foreign_group.pk, "code": "SECRET_SESSION"}])
        self.client.force_login(self.faculty_user)
        url = f"/admin/export-assignments/?semester={self.semester.pk}&faculty={self.teacher.department.faculty_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "SECRET_SESSION")
        self.assertNotContains(response, "Foreign course")

    def test_scoped_completeness_tracks_missing_pending_approved_and_duplicate(self):
        from .assignment_completeness import assignment_completeness
        from .access import allowed_departments
        AlgorithmRun.objects.create(semester=self.semester, status="OPTIMAL", created_by=self.admin,
            demand_snapshot=[{"group_id": self.group.pk, "code": "LT1",
                              "course_code": self.group.course.code, "group": self.group.group,
                              "lab_group": "", "excel_row": 2}])
        departments = allowed_departments(self.faculty_user)
        check = lambda: assignment_completeness(self.semester, departments)
        self.assertEqual(check()["counts"]["missing"], 1)
        self.own_entry.request_code = "LT1"
        self.own_entry.save()
        self.assertEqual(check()["counts"]["pending"], 1)
        self.assertFalse(check()["ready"])
        self.own_entry.status = "DaDuyet"
        self.own_entry.save()
        self.assertTrue(check()["ready"])
        ScheduleEntry.objects.create(group=self.group, lecturer=self.teacher, room=self.room,
            day=4, start_period_id=1, period_count=2, status="DaDuyet", request_code="LT1")
        self.assertEqual(check()["counts"]["duplicate"], 1)
        self.assertFalse(check()["ready"])

    def test_locked_configuration_and_invalid_effective_quota_return_validation_error(self):
        self.api.force_authenticate(self.admin)
        payload={"lecturer":self.teacher.pk,"semester":self.semester.pk,"target_units":"0.01","allocation_fraction":"0.01"}
        self.assertEqual(self.api.post("/api/teaching-quotas/",payload,format="json").status_code,400)
        self.semester.status="DaKhoa"; self.semester.save()
        self.assertEqual(self.api.post("/api/workload-policies/",{"semester":self.semester.pk,"balance_weight":0},format="json").status_code,400)

    def test_faculty_cannot_approve_and_head_cannot_delete(self):
        self.assertEqual(self.api.patch(f"/api/schedules/{self.own_entry.pk}/",{"status":"DaDuyet"},format="json").status_code,403)
        self.api.force_authenticate(self.head)
        self.assertEqual(self.api.delete(f"/api/schedules/{self.own_entry.pk}/").status_code,404)

    def test_global_training_can_run_and_scoped_training_cannot(self):
        rows=synthetic_rows(sessions=3,semester_name=self.semester.name,seed=7)
        def files():
            return {k:SimpleUploadedFile(f"{k}.xlsx",workbook_bytes(k,v)) for k,v in rows.items()}
        with self.assertRaises(PermissionDenied):
            enqueue_schedule(self.semester.pk,files(),self.training)
        self.training.unitroleassignment_set.all().delete()
        UnitRoleAssignment.objects.create(user=self.training,role="TRAINING",all_units=True,can_manage=True)
        queued=enqueue_schedule(self.semester.pk,files(),self.training)
        self.assertEqual(queued.status,"QUEUED")

    def test_cross_unit_cascade_delete_is_denied_without_revealing_children(self):
        leaf = Lecturer.objects.create(employee_code="LEAF", name="Own leaf", department=self.teacher.department)
        foreign_link = TeachingQualification.objects.create(lecturer=leaf, course=self.foreign_group.course)
        self.assertEqual(self.api.delete(f"/api/lecturers/{leaf.pk}/").status_code, 403)
        self.assertTrue(TeachingQualification.objects.filter(pk=foreign_link.pk).exists())
        self.client.force_login(self.faculty_user)
        response = self.client.get(f"/admin/school/lecturer/{leaf.pk}/delete/")
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "Foreign course", status_code=403)

    def test_own_leaf_and_unassigned_schedule_can_be_deleted(self):
        leaf = Lecturer.objects.create(employee_code="LEAF", name="Own leaf", department=self.teacher.department)
        self.assertEqual(self.api.delete(f"/api/lecturers/{leaf.pk}/").status_code, 204)
        self.own_entry.lecturer = None
        self.own_entry.save()
        self.assertEqual(self.api.delete(f"/api/schedules/{self.own_entry.pk}/").status_code, 204)
        self.assertFalse(ScheduleWeek.objects.filter(entry_id=self.own_entry.pk).exists())

    def test_mixed_roles_cannot_link_program_from_readonly_scope(self):
        UnitRoleAssignment.objects.create(user=self.faculty_user, role="HEAD",
                                         department=self.foreign_teacher.department, can_manage=True)
        program = Program.objects.create(code="FOREIGN", name="Foreign program", cycle="2026", faculty=self.foreign_faculty)
        response = self.api.post("/api/course-programs/", {"course":self.course.pk,
                    "program":program.pk,"requirement":"BAT_BUOC"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_department_scope_cannot_be_moved_through_admin_mutated_instance(self):
        from .access import check_write
        department = self.teacher.department
        department.faculty = self.foreign_faculty
        with self.assertRaises(PermissionDenied):
            check_write(self.faculty_user, Department, {"faculty":self.foreign_faculty}, department)

    def test_review_form_rejects_foreign_teacher_before_saving(self):
        self.client.force_login(self.faculty_user)
        response = self.client.post(f"/admin/review-schedules/{self.own_entry.pk}/edit/", {
            "lecturer":self.foreign_teacher.pk,"room":self.room.pk,"other_location":"", "day":2,
            "start_period":1,"period_count":2,"weeks":"1"})
        self.assertEqual(response.status_code,403)
        self.own_entry.refresh_from_db()
        self.assertEqual(self.own_entry.lecturer_id,self.teacher.pk)
