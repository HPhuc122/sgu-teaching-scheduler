"""Local visual QA with isolated synthetic data; never opens the project database.

Run with --phase before to render templates/Admin configuration from Git HEAD.
Both phases use the same isolated data so screenshots are directly comparable.
"""
import argparse
from datetime import date, time
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "ui-qa"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), default="after")
    parser.add_argument("--port", type=int, default=8027)
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Deliberately override any inherited DB setting. This harness is isolated.
    os.environ.pop("UCTP_DB_ENGINE", None)
    os.environ["UCTP_SQLITE_PATH"] = str(OUTPUT / "visual-test.sqlite3")
    os.environ["UCTP_DEBUG"] = "1"
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    django.setup()
    from django.conf import settings
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command, execute_from_command_line
    from django.test import Client
    from school.auto_schedule import approve_algorithm_run
    from school.models import AlgorithmRun, Lecturer, Period, Semester
    from school.sample_data import synthetic_rows, workbook_bytes
    from school.schedule_queue import enqueue_schedule, process_next_run

    call_command("migrate", interactive=False, verbosity=0)
    user, _ = get_user_model().objects.get_or_create(
        username="ui_qa_admin", defaults={"is_staff": True, "is_superuser": True,
                                         "first_name": "Quản trị", "last_name": "Kiểm thử"})
    semester, _ = Semester.objects.get_or_create(
        name="HK1 · Dữ liệu kiểm thử giao diện", defaults={"academic_year": "2026-2027",
        "start_date": date(2026, 9, 1), "end_date": date(2027, 1, 31), "week_count": 18})
    for number in range(1, 14):
        minute = 7 * 60 + (number - 1) * 55
        Period.objects.get_or_create(pk=number, defaults={"block": "Sang" if number <= 5 else "Chieu",
            "start_time": time(minute // 60, minute % 60),
            "end_time": time((minute + 50) // 60, (minute + 50) % 60)})
    rows = synthetic_rows(sessions=12, semester_name=semester.name, weeks=18, seed=42)
    files = {}
    for kind, sheets in rows.items():
        content = workbook_bytes(kind, sheets)
        (OUTPUT / f"{kind}.xlsx").write_bytes(content)
        files[kind] = SimpleUploadedFile(f"{kind}.xlsx", content)
    if not AlgorithmRun.objects.exists():
        enqueue_schedule(semester.pk, files, user)
        run = process_next_run()
        if not run.entry_count:
            raise RuntimeError(f"QA scheduling failed: {run.message}")
        approve_algorithm_run(run.pk, user)
    run = AlgorithmRun.objects.order_by("pk").first()
    lecturer = Lecturer.objects.filter(scheduleentry__status="DaDuyet").distinct().first()
    teacher, _ = get_user_model().objects.get_or_create(username="ui_qa_teacher")
    if lecturer.user_id != teacher.pk:
        lecturer.user = teacher
        lecturer.save(update_fields=["user"])
    pending = run.entries.filter(lecturer__department__faculty=lecturer.department.faculty).order_by("pk").last()
    if pending.status == "DaDuyet":
        pending.status = "ChoDuyet"
        pending.approved_at = None
        pending.approved_by = None
        pending.save(update_fields=["status", "approved_at", "approved_by"])

    if args.phase == "before":
        before = OUTPUT / "before-templates"
        names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD",
            "backend/school/templates"], cwd=ROOT, text=True).splitlines()
        for name in names:
            target = before / name.split("templates/", 1)[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=ROOT))
        settings.TEMPLATES[0]["DIRS"] = [before]
        for model in list(admin.site._registry):
            if model._meta.app_label == "school":
                admin.site.unregister(model)
        old_admin = subprocess.check_output(["git", "show", "HEAD:backend/school/admin.py"], cwd=ROOT)
        exec(compile(old_admin, "original-admin.py", "exec"), {"__name__": "school.qa_original_admin", "__package__": "school"})
        from django.contrib.auth.admin import GroupAdmin, UserAdmin
        from django.contrib.auth.models import Group
        admin.site.unregister(get_user_model())
        admin.site.unregister(Group)
        admin.site.register(get_user_model(), UserAdmin)
        admin.site.register(Group, GroupAdmin)
        admin.site.enable_nav_sidebar = True
        admin.site.site_header = "Django administration"
        admin.site.site_title = "Django site admin"
        admin.site.index_title = "Site administration"

    client = Client()
    client.force_login(user)
    admin_session = client.cookies[settings.SESSION_COOKIE_NAME].value
    client = Client()
    client.force_login(teacher)
    teacher_session = client.cookies[settings.SESSION_COOKIE_NAME].value
    info = {"base": f"http://127.0.0.1:{args.port}", "admin_session": admin_session,
            "teacher_session": teacher_session, "semester": semester.pk,
            "faculty": lecturer.department.faculty_id, "lecturer": lecturer.pk,
            "entry": pending.pk, "run": run.pk,
            "models": {model._meta.model_name: model.objects.order_by("pk").first().pk
                       for model in admin.site._registry
                       if model._meta.app_label == "school" and model.objects.exists()}}
    (OUTPUT / f"{args.phase}-session.json").write_text(json.dumps(info), encoding="utf-8")
    print(f"UI QA {args.phase}: {info['base']} (isolated synthetic database)", flush=True)
    execute_from_command_line(["manage.py", "runserver", f"127.0.0.1:{args.port}", "--noreload"])


if __name__ == "__main__":
    main()
