"""Validate the 20-case collection, or test the reserved input in a copy."""
import argparse
import csv
import json
import os
import shutil
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile, ZIP_DEFLATED

from prepare_report_examples import ROOT, copy_database, audit_persisted, export_case, write_json


def publish_verified(output, stage):
    verified = json.loads((output / "final_verification.json").read_text(encoding="utf-8"))
    future = json.loads((output / "checks/future_input_verified.json").read_text(encoding="utf-8"))
    assert verified["scheduled_and_approved"] == 10800 and verified["output_workbooks"] == 600
    assert future["sessions"] == 480 and future["live_data_unchanged"]
    assert verified["stage_sha256"] == sha256(stage.read_bytes()).hexdigest(), "Staging changed since final verification"
    live = ROOT / "outputs/sgu_public_demo_DCT/demo.sqlite3"
    copy_database(stage, live)
    archive_root = output / "luu_tru_output_cu"
    archive_root.mkdir(exist_ok=True)
    for source in [ROOT / "outputs/planning_workflow_validation", *[
            live.parent / name for name in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "benchmark.json",
                "live_import_report.json", "multistart_report.json", "preview_import_report.json", "provenance.json")]]:
        target = archive_root / source.name
        assert source.resolve().is_relative_to((ROOT / "outputs").resolve())
        assert target.resolve().is_relative_to(output.resolve())
        if source.exists() and not target.exists():
            shutil.move(str(source), str(target))
    write_json(output / "published.json", dict(database=str(live), output_workbooks=600, semesters=21))
    print("Published verified 20 cases plus one empty presentation semester to local demo", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--future-check", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    args = parser.parse_args()
    assert not (args.future_check and args.publish)
    output = ROOT / "outputs/bao_cao_20_mau"
    stage = output / "staged_demo.sqlite3"
    if args.publish_only:
        assert not args.future_check
        publish_verified(output, stage)
        return
    database = output / "checks/future_check.sqlite3" if args.future_check else stage
    if args.future_check:
        if database.exists():
            raise RuntimeError("Future verification database already exists")
        copy_database(stage, database)
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", UCTP_SQLITE_PATH=str(database),
                      UCTP_QUALITY_BUDGET_SECONDS="60", UCTP_DEBUG="1")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import connection, transaction
    from django.db.models import Count
    from django.test import Client
    from django.test.utils import setup_test_environment
    from school.models import (Semester, ScheduleEntry, AlgorithmRun, CourseGroup, Lecturer,
                               TeachingAssignment, ScheduleRunQueue, TeachingQualification)
    from school.planning import save_plan_from_workbooks
    from school.schedule_queue import enqueue_schedule, process_next_run
    from school.auto_schedule import approve_algorithm_run
    from school.assignment_completeness import assignment_completeness

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 21 and len({r["name"] for r in manifest}) == 21
    future = manifest[-1]
    assert future["sessions"] == 480 and future["presentation"]
    actor = get_user_model().objects.get(username="sgu_admin_demo")
    if args.future_check:
        semester = Semester.objects.get(pk=future["semester_id"])
        assert not AlgorithmRun.objects.filter(semester=semester).exists()
        folder = ROOT / future["folder"]
        files = lambda: {k: SimpleUploadedFile(f"{k}.xlsx", (folder / f"{k}.xlsx").read_bytes())
                         for k in ("courses", "rooms", "lecturers")}
        started = perf_counter()
        save_plan_from_workbooks(semester.pk, files())
        enqueue_schedule(semester.pk, files(), actor)
        run = process_next_run()
        assert run.status in ("OPTIMAL", "FEASIBLE", "HEURISTIC"), (run.status, run.message)
        count = audit_persisted(semester, folder, run)
        assert approve_algorithm_run(run.pk, actor) == count == 480
        assert assignment_completeness(semester)["ready"]
        write_json(output / "checks/future_input_verified.json", dict(
            isolated_database=str(database), live_data_unchanged=True,
            search_seed=42, input_seed=future["seed"],
            sessions=count, status=run.status, objective_before=run.objective_before,
            objective=run.objective, seconds=round(perf_counter()-started, 3)))
        print("Future input: 480/480 scheduled, audited and approved in isolated copy", flush=True)
        return

    assert Semester.objects.count() == 21
    assert Semester.objects.filter(status="DaKhoa").count() == 20
    assert AlgorithmRun.objects.count() == 20
    assert not ScheduleRunQueue.objects.exists()
    assert ScheduleEntry.objects.count() == 10800
    assert ScheduleEntry.objects.exclude(status="DaDuyet").count() == 0
    assert TeachingAssignment.objects.count() == 10800
    next_semester = Semester.objects.get(pk=future["semester_id"])
    assert next_semester.status == "DangMo"
    assert not CourseGroup.objects.filter(semester=next_semester).exists()
    assert not AlgorithmRun.objects.filter(semester=next_semester).exists()

    # Retain existing passwords and role scopes; connect demo lecturer logins to
    # fictional lecturers from the same faculty who actually have new schedules.
    mapping_path = output / "demo_account_mapping.json"
    mappings = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else []
    with transaction.atomic():
        for old in Lecturer.objects.exclude(user=None).exclude(employee_code__startswith="MPGV"):
            new = Lecturer.objects.filter(employee_code__startswith="MPGV", department__faculty=old.department.faculty,
                user=None, scheduleentry__group__semester_id=manifest[-2]["semester_id"]).order_by("employee_code").first()
            if new is None:
                raise AssertionError(f"Cannot preserve lecturer demo access in faculty {old.department.faculty_id}")
            mappings.append(dict(username=old.user.username, lecturer_code=new.employee_code, lecturer_name=new.name))
            account = old.user
            old.user = None
            old.save(update_fields=["user"])
            new.user = account
            new.save(update_fields=["user"])
        legacy = Lecturer.objects.exclude(employee_code__startswith="MPGV")
        assert not TeachingAssignment.objects.filter(lecturer__in=legacy).exists()
        assert not ScheduleEntry.objects.filter(lecturer__in=legacy).exists()
        legacy.delete()
    write_json(output / "demo_account_mapping.json", mappings)

    # First pilot output predates the clarified timetable export description.
    export_case(Semester.objects.get(pk=manifest[0]["semester_id"]), output / Path(manifest[0]["folder"]).name)
    hashes, completed, endpoints = {}, [], []
    setup_test_environment()
    client = Client()
    client.force_login(actor)
    for info in manifest:
        folder = ROOT / info["folder"]
        for kind, digest in info["input_sha256"].items():
            assert sha256((folder / f"{kind}.xlsx").read_bytes()).hexdigest() == digest
        semester = Semester.objects.get(pk=info["semester_id"])
        if info["presentation"]:
            continue
        assert assignment_completeness(semester)["ready"]
        run = AlgorithmRun.objects.get(semester=semester)
        assert audit_persisted(semester, folder, run) == info["sessions"]
        files = sorted((output / folder.name).glob("*.xlsx"))
        assert len(files) == 30
        for path in files:
            hashes[str(path.relative_to(output))] = sha256(path.read_bytes()).hexdigest()
        for endpoint in (f"/admin/auto-schedule/?semester={semester.pk}",
                         f"/admin/teaching-plans/?semester={semester.pk}&faculty=1"):
            response = client.get(endpoint)
            assert response.status_code == 200, (endpoint, response.status_code)
            endpoints.append(endpoint)
        completed.append(dict(index=info["index"], sessions=run.entry_count, complete=True))
        print(f"VERIFIED {info['index']:02d}/20: {run.entry_count} sessions, 30 workbooks", flush=True)
    latest_id = manifest[-2]["semester_id"]
    for faculty in range(1, 16):
        for endpoint in (f"/admin/faculty-timetable/?semester={latest_id}&faculty={faculty}&week=1",
                         f"/admin/review-schedules/?semester={latest_id}&faculty={faculty}",
                         f"/admin/export-assignments/?semester={latest_id}&faculty={faculty}",
                         f"/admin/teaching-plans/?semester={latest_id}&faculty={faculty}&download=xlsx"):
            response = client.get(endpoint)
            assert response.status_code == 200, (endpoint, response.status_code)
            if "download=xlsx" in endpoint:
                assert response["Content-Type"].endswith("spreadsheetml.sheet")
            endpoints.append(endpoint)
    assert len(hashes) == 600 and len(completed) == 20
    write_json(output / "output_sha256.json", hashes)
    connection.close()
    write_json(output / "final_verification.json", dict(completed=completed, output_workbooks=600,
        scheduled_and_approved=10800, hard_violations=0, ui_requests=len(endpoints),
        future_semester=future["name"], future_untouched=True, accounts_preserved=True,
        stage_sha256=sha256(stage.read_bytes()).hexdigest()))
    with (output / "tong_hop.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("Mẫu", "Học kỳ", "Buổi yêu cầu", "Đã xếp/duyệt", "Khoa", "Điểm trước", "Điểm sau", "Giây xử lý worker", "Trạng thái"))
        for info in manifest:
            report = info.get("result", {})
            writer.writerow((info["index"], info["name"], info["sessions"], report.get("sessions", ""), 15,
                report.get("objective_before", ""), report.get("objective", ""), report.get("schedule_seconds", ""),
                "Đã kiểm chứng" if report else "Chưa chạy — dành cho báo cáo"))
    shutil.copyfile(ROOT / "docs/bo_mau_bao_cao_20_hoc_ky.md", output / "README.md")
    with ZipFile(output / "20_mau_output.zip", "w", ZIP_DEFLATED) as archive:
        for info in manifest[:-1]:
            for path in sorted((output / Path(info["folder"]).name).iterdir()):
                if path.is_file() and path.suffix in (".xlsx", ".json"):
                    archive.write(path, str(path.relative_to(output)))
        for name in ("README.md", "tong_hop.csv", "manifest.json", "final_verification.json", "output_sha256.json"):
            archive.write(output / name, name)
    with ZipFile(output / "Bo_21_chay_bao_cao.zip", "w", ZIP_DEFLATED) as archive:
        folder = ROOT / future["folder"]
        for name in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "thong_tin.json"):
            archive.write(folder / name, name)
        archive.write(ROOT / "samples/bao_cao_21_hoc_ky/README.md", "HUONG_DAN.md")
    if args.publish:
        publish_verified(output, stage)
    connection.close()


if __name__ == "__main__":
    main()
