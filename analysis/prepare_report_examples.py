"""Build and audit 20 historical simulations plus one presentation input pack.

Runs the application's real import/queue/approval/export pipeline in a staged
copy of the local demo database. Never mutates the live database.
"""
import argparse
import copy
import csv
import json
import os
import random
import re
import sqlite3
import sys
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def copy_database(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def period_info(index):
    # Twenty consecutive simulated terms ending at HK1 2026-2027.
    absolute = 2019 * 3 + 2 + index
    year, n = absolute // 3, absolute % 3 + 1
    calendar_year, month = (year, 9) if n == 1 else (year + 1, 1 if n == 2 else 5)
    first = date(calendar_year, month, 1)
    start = first + timedelta(days=(-first.weekday()) % 7)
    return dict(index=index + 1, number=n, academic_year=f"{year}-{year+1}",
                name=f"Học kỳ {n} - Năm học {year} - {year+1}",
                start_date=start, end_date=start + timedelta(days=111), weeks=16,
                seed=20261106 + index * 97, presentation=index == 20)


def adapt_pack(base, info):
    from school.auto_schedule import AUTO_SHEETS
    from school.schedule_import import parse_weeks

    _, old_start, _, _, packed, provenance = base
    rows = {kind: {sheet: [dict(zip(AUTO_SHEETS[kind][sheet], row)) for row in values]
                   for sheet, values in sheets.items()} for kind, sheets in packed.items()}
    c, t, r = rows["courses"], rows["lecturers"], rows["rooms"]
    rng = random.Random(info["seed"])
    year_delta = int(info["academic_year"][:4]) - 2026

    def class_name(value):
        # Public SGU labels such as DCT1231 -> cohort 2023. Preserve program prefix.
        return re.sub(r"^(D[A-Z]{2,3}1)(\d{2})(.*)$",
                      lambda m: f"{m[1]}{int(m[2]) + year_delta:02d}{m[3]}", value)

    hours = {}
    for group in c["NhomHocPhan"]:
        group["hoc_ky"] = info["name"]
        group["ten_lop"] = ";".join(class_name(x) for x in str(group["ten_lop"]).split(";"))
    for cohort in c["LopHanhChinh"]:
        cohort["ten_lop"] = class_name(cohort["ten_lop"])
    for demand in c["BuoiHocYeuCau"]:
        # Different genuine scheduling instances, not just 20 renamed copies.
        # Keep at least four permitted weekdays and >=12 teaching weeks.
        days = list(range(2, 7))
        if rng.random() < .25:
            days.remove(rng.choice(days))
        demand["thu_duoc_xep"] = ",".join(map(str, days))
        weeks = sorted(parse_weeks(str(demand["tuan_hoc"])))
        if len(weeks) > 12 and rng.random() < .3:
            weeks.remove(rng.choice(weeks))
        demand["tuan_hoc"] = ",".join(map(str, weeks))
        volume = int(demand["so_tiet"]) * len(weeks)
        demand["so_tiet_thuc_te"] = volume
        key = (demand["ma_mon_hoc"], demand["nhom"], demand["to_th"])
        hours.setdefault(key, {"LT": 0, "BT": 0, "TH": 0})[demand["loai_buoi"]] += volume
    for plan in c["KeHoachMoNhom"]:
        plan["hoc_ky_so"] = info["number"]
        plan["khoa"] = re.sub(r"20\d{2}", lambda m: str(int(m[0]) + year_delta), plan["khoa"])
        key = (plan["ma_mon_hoc"], plan["nhom"], plan["to_th"])
        for component, field in (("LT", "so_tiet_lt"), ("BT", "so_tiet_bt"), ("TH", "so_tiet_th")):
            plan[field] = hours[key][component]
    # Give off-campus events different weeks/days, overlapping real teaching days.
    for i, activity in enumerate(c["HoatDongNgoaiTruong"]):
        activity["ten_lop"] = class_name(activity["ten_lop"])
        activity["khoa"] = f"Khóa {2026 + year_delta}"
        when = info["start_date"] + timedelta(weeks=(info["index"] + i) % 8, days=i % 5)
        activity.update(tu_ngay=when.isoformat(), den_ngay=when.isoformat(), hoc_ky_so=info["number"])
    for duty in t["CongTacKhac"]:
        duty["noi_dung"] = re.sub(r"D[A-Z]{2,3}1\d{2}\w*", lambda m: class_name(m[0]), duty["noi_dung"])
        duty["so_tiet"] += info["index"] % 3
    # Explicit unavailability survives save-plan -> schedule round trips.
    for room in r["PhongHoc"][:5]:
        r["PhongKhongKhaDung"].append(dict(ma_phong=room["ma_phong"], thu=6,
            tiet_bat_dau=1, so_tiet=2, tuan_hoc="1,2,3,4"))
    for person in t["GiangVien"][:5]:
        t["GiangVienKhongKhaDung"].append(dict(ma_vien_chuc=person["ma_vien_chuc"], thu=5,
            tiet_bat_dau=1, so_tiet=2, tuan_hoc="5,6,7,8"))
    packed = {kind: {sheet: [tuple(row.get(h, "") for h in AUTO_SHEETS[kind][sheet]) for row in values]
                     for sheet, values in sheets.items()} for kind, sheets in rows.items()}
    return rows, packed, dict(provenance, simulation=info,
        note="Historical dates and appointments are simulations, not historical SGU records.",
        reference_year="2026-2027", source_start_date=old_start)


def clear_staged_history():
    from django.db import transaction
    from school import models as m
    with transaction.atomic():
        for model in (m.ScheduleRunQueue, m.ScheduleEntry, m.AlgorithmRun, m.OffCampusActivity,
                      m.LecturerOtherDuty, m.LecturerPreference, m.TeachingQuota, m.ConversionRule,
                      m.WorkloadPolicy, m.CourseGroup, m.Cohort, m.SemesterResourcePlan, m.Semester):
            model.objects.all().delete()


def add_preferences(semester, rows, seed):
    from school.models import Lecturer, LecturerPreference
    from school.preference_validation import preference_errors
    teachers = {t.employee_code: t for t in Lecturer.objects.filter(employee_code__in=[
        r["ma_vien_chuc"] for r in rows["lecturers"]["GiangVien"]])}
    # One hard day off and one soft morning/afternoon preference per faculty.
    records = []
    for i, faculty in enumerate(rows["courses"]["Khoa"]):
        person = next(r for r in rows["lecturers"]["GiangVien"] if r["ma_khoa"] == faculty["ma_khoa"])
        for kind, day, block, priority in (("NgayNghi", 2 + (seed+i) % 5, "", 2),
                                          ("KhungGio", None, "Sang" if i % 2 else "Chieu", 1)):
            values = dict(kind=kind, day=day, time_block=block, priority=priority)
            assert not preference_errors(values)
            pref, _ = LecturerPreference.objects.update_or_create(semester=semester,
                lecturer=teachers[person["ma_vien_chuc"]], kind=kind,
                defaults={**values, "note": "Nguyện vọng mô phỏng phục vụ bộ báo cáo"})
            records.append(dict(employee_code=person["ma_vien_chuc"], **values))
    return records


def audit_persisted(semester, folder, run):
    from school.auto_schedule import read_auto_files, _prepare_inputs
    from school.models import Lecturer, Room, ScheduleEntry, TeachingAssignment
    from school.planning import activity_blocks
    from school.solution_audit import audit_solution
    from school.soft_score import SoftScorer
    from school.assignment_completeness import assignment_completeness
    from django.core.files.uploadedfile import SimpleUploadedFile

    files = {k: SimpleUploadedFile(f"{k}.xlsx", (folder / f"{k}.xlsx").read_bytes())
             for k in ("courses", "rooms", "lecturers")}
    data = read_auto_files(files)
    demands, rb, tb = _prepare_inputs(semester, data)
    assignments = {(a.group.course.code, a.group.group, a.group.lab_group or "", a.request_code): a
                   for a in TeachingAssignment.objects.filter(group__semester=semester)
                   .select_related("group__course", "fixed_lecturer")}
    teacher_map = {t.employee_code: t for t in Lecturer.objects.filter(employee_code__in=[
        r["ma_vien_chuc"] for r in data["lecturers"]["GiangVien"]])}
    room_map = {r.code: r for r in Room.objects.filter(code__in=[r["ma_phong"] for r in data["rooms"]["PhongHoc"]])}
    blocks = activity_blocks(semester)
    entries = {(e.group_id, e.request_code): e for e in ScheduleEntry.objects.filter(group__semester=semester)
               .select_related("lecturer", "room").prefetch_related("schedule_weeks")}
    result = []
    for d in demands:
        a = assignments[(*d["key"], d["code"])]
        d["group"], d["assigned_teacher"] = a.group, a.fixed_lecturer
        d["activity_blocks"] = blocks.get(a.group_id, set())
        e = entries[(a.group_id, a.request_code)]
        assert set(a.weeks) == {w.week for w in e.schedule_weeks.all()}
        assert a.period_count == e.period_count and a.lecturer_id == e.lecturer_id
        result.append((d, e.day, e.start_period_id, e.room, e.lecturer))
    assert len(result) == len(entries) == len(assignments) == run.entry_count
    pairs = {(r["ma_vien_chuc"], r["ma_mon_hoc"]) for r in data["lecturers"]["GiangVienHocPhan"]}
    # Re-audit a resumed approved case without counting its own entries twice.
    # Status changes stay inside a transaction that is always rolled back.
    from django.db import transaction
    with transaction.atomic():
        ScheduleEntry.objects.filter(group__semester=semester).update(status="ChoDuyet")
        audit_solution(semester, demands, result, room_map, teacher_map, rb, tb, pairs)
        transaction.set_rollback(True)
    score = SoftScorer(semester, teacher_map, pairs).score(result)
    assert score == run.objective, (score, run.objective)
    return len(entries)


def export_case(semester, folder):
    from django.db.models import Q
    from openpyxl import load_workbook
    from school.models import Faculty, TeachingAssignment, OffCampusActivity, LecturerOtherDuty
    from school.planning_exports import forms_workbook
    from school.assignment_export import approved_assignments, assignment_workbook_bytes
    from school.assignment_completeness import assignment_completeness

    folder.mkdir(parents=True, exist_ok=True)
    completeness = assignment_completeness(semester)
    assert completeness["ready"], str(completeness["counts"])
    checks, timetable_total = [], 0
    for faculty in Faculty.objects.filter(code__startswith="SGU_DEMO_K").order_by("code"):
        assignments = TeachingAssignment.objects.filter(group__semester=semester).filter(
            Q(group__course__department__faculty=faculty) | Q(lecturer__department__faculty=faculty)
        ).select_related("group__course__department__faculty", "group__semester", "group__teaching_plan", "lecturer__department__faculty")
        activities = OffCampusActivity.objects.filter(semester=semester, cohort__department__faculty=faculty).select_related("semester", "cohort")
        duties = LecturerOtherDuty.objects.filter(semester=semester, lecturer__department__faculty=faculty).select_related("lecturer")
        content = forms_workbook(faculty, semester.academic_year, assignments, activities, duties)
        filename = f"{faculty.code.rsplit('_', 1)[-1]}_bieu_mau_1_5.xlsx"
        (folder / filename).write_bytes(content)
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
        counts = {s.title: max(0, s.max_row - 5) for s in book}
        assert counts[f"Mau1_HK{semester.number}"] > 0, counts
        assert not any(str(cell.value).startswith(("#REF!", "#VALUE!", "#DIV/0!")) for s in book for row in s for cell in row)
        book.close()
        entries = approved_assignments(semester, faculty)
        timetable_total += len(entries)
        scoped_check = assignment_completeness(semester, faculty=faculty)
        assert scoped_check["ready"]
        (folder / f"{faculty.code.rsplit('_', 1)[-1]}_thoi_khoa_bieu.xlsx").write_bytes(
            assignment_workbook_bytes(semester, faculty, entries, scoped_check))
        checks.append(dict(faculty=faculty.name, file=filename, form_rows=counts, timetable_sessions=len(entries)))
    assert len(checks) == 15 and timetable_total == completeness["expected"]
    assert all(sum(c["form_rows"][sheet] for c in checks) > 0 for sheet in ("Mau2", "Mau3", "Mau4", "Mau5"))
    return dict(expected=completeness["expected"], counts=completeness["counts"],
                complete=True, hard_conflicts=0, faculties=checks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--budget", type=float, default=60)
    parser.add_argument("--retry-index", type=int)
    args = parser.parse_args()
    stage = ROOT / "outputs/bao_cao_20_mau/staged_demo.sqlite3"
    live = ROOT / "outputs/sgu_public_demo_DCT/demo.sqlite3"
    output = stage.parent
    inputs = ROOT / "samples/bao_cao_21_hoc_ky"
    output.mkdir(parents=True, exist_ok=True)
    if args.initialize:
        if stage.exists():
            raise RuntimeError("Staged database already exists; cannot overwrite an experiment")
        backup = output / "backup_truoc_thay_output.sqlite3"
        copy_database(live, backup)
        copy_database(backup, stage)
    if not stage.exists():
        raise RuntimeError("Use --initialize once")
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", UCTP_SQLITE_PATH=str(stage),
                      UCTP_QUALITY_BUDGET_SECONDS=str(args.budget), UCTP_DEBUG="1")
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import connection
    from django.utils import timezone
    from school.models import Semester, AlgorithmRun, ScheduleEntry, Lecturer
    from school.realistic_planning_data import build_realistic_packs
    from school.sample_data import workbook_bytes
    from school.planning import save_plan_from_workbooks, workbooks_from_plan
    from school.schedule_queue import enqueue_schedule, process_next_run
    from school.auto_schedule import approve_algorithm_run

    assert Path(settings.DATABASES["default"]["NAME"]).resolve() == stage.resolve() != live.resolve()
    if args.initialize:
        clear_staged_history()
    if args.retry_index:
        failed_info = period_info(args.retry_index - 1)
        failed = Semester.objects.get(name=failed_info["name"])
        assert failed.status != "DaKhoa"
        assert not ScheduleEntry.objects.filter(group__semester=failed, status="DaDuyet").exists()
        write_json(output / f"pilot_replaced_{args.retry_index}.json", list(AlgorithmRun.objects.filter(
            semester=failed).values("id", "status", "optimization_trials")))
        ScheduleEntry.objects.filter(group__semester=failed).delete()
        AlgorithmRun.objects.filter(semester=failed).delete()
    bases = build_realistic_packs(ROOT / "samples/sgu_15_khoa", preserve_catalog=True)
    actor = get_user_model().objects.get(username="sgu_admin_demo")
    assert actor.is_superuser
    manifest = []
    for index in range(21):
        info = period_info(index)
        # Rotate sizes independently of semester number: 7 small, 7 medium, 6 large.
        base = bases[1 if index == 20 else index % 3]
        rows, packed, provenance = adapt_pack(base, info)
        folder = inputs / f"{index+1:02d}_{info['academic_year']}_HK{info['number']}"
        folder.mkdir(parents=True, exist_ok=True)
        for kind, sheets in packed.items():
            path = folder / f"{kind}.xlsx"
            if not path.exists():
                path.write_bytes(workbook_bytes(kind, sheets))
        info.update(folder=str(folder.relative_to(ROOT)), sessions=len(rows["courses"]["BuoiHocYeuCau"]),
                    groups=len(rows["courses"]["NhomHocPhan"]), faculties=15,
                    courses=len(rows["courses"]["HocPhan"]), lecturers=len(rows["lecturers"]["GiangVien"]),
                    rooms=len(rows["rooms"]["PhongHoc"]),
                    input_sha256={k: sha256((folder / f"{k}.xlsx").read_bytes()).hexdigest() for k in packed})
        write_json(folder / "thong_tin.json", dict(info, provenance=provenance))
        manifest.append(info)
        if index >= args.limit and index < 20:
            continue
        semester, _ = Semester.objects.get_or_create(name=info["name"], defaults=dict(
            number=info["number"], academic_year=info["academic_year"], start_date=info["start_date"],
            end_date=info["end_date"], week_count=16))
        info["semester_id"] = semester.pk
        if index == 20:
            assert not ScheduleEntry.objects.filter(group__semester=semester).exists()
            assert not AlgorithmRun.objects.filter(semester=semester).exists()
            info["state"] = "CHUA_CHAY_DANH_CHO_BAO_CAO"
            if args.limit == 20:
                info["preferences"] = add_preferences(semester, rows, info["seed"])
            continue
        result_folder = output / folder.name
        summary_path = result_folder / "kiem_chung.json"
        if summary_path.exists():
            info["result"] = json.loads(summary_path.read_text(encoding="utf-8"))
            print(f"SKIP {folder.name}: already verified", flush=True)
            continue
        started = perf_counter()
        run = AlgorithmRun.objects.filter(semester=semester).first()
        if run is None:
            uploaded = {k: SimpleUploadedFile(f"{k}.xlsx", (folder / f"{k}.xlsx").read_bytes()) for k in packed}
            save_plan_from_workbooks(semester.pk, uploaded)
            preferences = add_preferences(semester, rows, info["seed"])
            settings.QUALITY_SEARCH_SEED = info["seed"]
            # Use precisely these three files, as in the upload-and-run UI.
            # Rebuilding from a saved plan includes the site's wider catalog.
            uploaded = {k: SimpleUploadedFile(f"{k}.xlsx", (folder / f"{k}.xlsx").read_bytes()) for k in packed}
            queued = enqueue_schedule(semester.pk, uploaded, actor)
            run = process_next_run()
            assert run.pk == queued.pk
        else:
            preferences = list(semester.lecturerpreference_set.values("lecturer__employee_code", "kind", "day", "time_block", "priority"))
        if run.status not in ("OPTIMAL", "FEASIBLE", "HEURISTIC") or run.entry_count != info["sessions"]:
            write_json(output / f"FAILED_{folder.name}.json", dict(status=run.status, message=run.message, diagnostics=run.diagnostics))
            raise RuntimeError(f"{folder.name}: {run.status}: {run.message}; see failure JSON")
        audit_persisted(semester, folder, run)
        approved = ScheduleEntry.objects.filter(algorithm_run=run, status="DaDuyet").count()
        if not approved:
            approved = approve_algorithm_run(run.pk, actor)
        assert approved == info["sessions"]
        exported = export_case(semester, result_folder)
        # Freeze historical examples only after auditing and exporting them.
        semester.status = "DaKhoa"
        semester.save(update_fields=["status"])
        report = dict(index=index+1, semester_id=semester.pk, semester=info["name"], run_id=run.pk,
            status=run.status, sessions=approved, objective_before=run.objective_before, objective=run.objective,
            elapsed_seconds=round(perf_counter()-started, 3), budget_seconds=args.budget,
            schedule_seconds=round((run.finished_at - run.started_at).total_seconds(), 3),
            seed=info["seed"], simulated=True, preferences=preferences, **exported)
        write_json(summary_path, report)
        write_json(result_folder / "nhat_ky_thuat_toan.json", run.optimization_trials)
        info["result"] = report
        write_json(output / "tien_do.json", manifest)
        print(f"DONE {index+1:02d}/20 {info['name']} sessions={approved} score={run.objective_before}->{run.objective} time={report['elapsed_seconds']}s", flush=True)
    write_json(inputs / "manifest.json", manifest)
    write_json(output / "manifest.json", manifest)
    with (output / "tong_hop.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("Mẫu", "Học kỳ", "Buổi yêu cầu", "Đã xếp/duyệt", "Khoa", "Điểm trước", "Điểm sau", "Giây xử lý worker", "Trạng thái"))
        for info in manifest:
            r = info.get("result", {})
            writer.writerow((info["index"], info["name"], info["sessions"], r.get("sessions", ""), 15,
                r.get("objective_before", ""), r.get("objective", ""), r.get("schedule_seconds", ""),
                "Đã kiểm chứng" if r else info.get("state", "Chưa chạy")))
    write_json(output / "environment.json", dict(django=django.get_version(), python=sys.version,
        generated_at=timezone.now().isoformat(), database=str(stage), budget_seconds=args.budget))
    connection.close()


if __name__ == "__main__":
    main()
