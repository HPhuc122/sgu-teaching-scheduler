"""Run the three-file workflow in an explicitly isolated SQLite database."""

import json
import os
from collections import defaultdict
from datetime import date, time
from io import BytesIO
from pathlib import Path
from time import perf_counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from openpyxl import load_workbook

from school.assignment_export import approved_assignments, assignment_workbook_bytes
from school.auto_schedule import AUTO_SHEETS, approve_algorithm_run, read_auto_workbook
from school.models import Faculty, Period, ScheduleEntry, Semester
from school.schedule_queue import enqueue_schedule, process_next_run


def assert_no_conflicts(entries):
    occupied = defaultdict(set)
    for entry in entries:
        cohorts = {link.cohort_id for link in entry.group.cohort_links.all()}
        resources = [("group", entry.group_id), ("room", entry.room_id),
                     ("lecturer", entry.lecturer_id)]
        resources += [("cohort", cohort_id) for cohort_id in cohorts]
        for week in (item.week for item in entry.schedule_weeks.all()):
            for period in range(entry.start_period_id, entry.start_period_id + entry.period_count):
                for kind, resource_id in resources:
                    if resource_id is None:
                        continue
                    key = kind, resource_id, week, entry.day, period
                    if key in occupied:
                        raise AssertionError(f"Trùng {kind}, tuần {week}, thứ {entry.day}, tiết {period}")
                    occupied[key].add(entry.pk)


class Command(BaseCommand):
    help = "Benchmark synthetic scheduling in a separate SQLite database only."

    def add_arguments(self, parser):
        parser.add_argument("--input-dir", required=True)
        parser.add_argument("--semester-name", required=True)
        parser.add_argument("--weeks", type=int, default=16)
        parser.add_argument("--approve", action="store_true")
        parser.add_argument("--expect-status", choices=("OPTIMAL", "FEASIBLE", "HEURISTIC",
                                                        "INFEASIBLE", "UNKNOWN", "ERROR"))
        parser.add_argument("--report", required=True)

    def handle(self, *args, **options):
        database = Path(settings.DATABASES["default"]["NAME"]).resolve()
        normal_database = (Path(settings.BASE_DIR) / "db.sqlite3").resolve()
        if (os.environ.get("UCTP_BENCHMARK") != "1" or
                settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3" or
                database == normal_database):
            raise CommandError("Benchmark chỉ chạy với UCTP_BENCHMARK=1 và UCTP_SQLITE_PATH riêng")
        input_dir = Path(options["input_dir"])
        file_data = {}
        parsed = {}
        for kind in AUTO_SHEETS:
            path = input_dir / f"{kind}.xlsx"
            file_data[kind] = path.read_bytes()
            parsed[kind] = read_auto_workbook(SimpleUploadedFile(path.name, file_data[kind]), kind)
        expected = len(parsed["courses"]["BuoiHocYeuCau"])

        semester, _ = Semester.objects.get_or_create(
            name=options["semester_name"], defaults={
                "academic_year": "2026-2027", "start_date": date(2026, 9, 1),
                "end_date": date(2027, 1, 31), "week_count": options["weeks"],
            },
        )
        if semester.week_count != options["weeks"]:
            raise CommandError("Số tuần trong dữ liệu và học kỳ không khớp")
        for number in range(1, 14):
            Period.objects.get_or_create(pk=number, defaults={
                "block": "Sang" if number <= 5 else "Chieu",
                "start_time": time(7, 0), "end_time": time(7, 50),
            })
        actor, _ = get_user_model().objects.get_or_create(
            username="synthetic_benchmark_admin", defaults={"is_staff": True},
        )
        files = {kind: SimpleUploadedFile(f"{kind}.xlsx", content)
                 for kind, content in file_data.items()}
        start = perf_counter()
        queued = enqueue_schedule(semester.pk, files, actor)
        enqueue_seconds = round(perf_counter() - start, 3)
        start = perf_counter()
        run = process_next_run()
        solve_seconds = round(perf_counter() - start, 3)
        if run is None or run.pk != queued.pk:
            raise CommandError("Worker không xử lý đúng lần chạy")
        entries = list(ScheduleEntry.objects.filter(algorithm_run=run)
                       .select_related("group", "lecturer", "room")
                       .prefetch_related("schedule_weeks", "group__cohort_links"))
        if run.status in ("FEASIBLE", "OPTIMAL", "HEURISTIC"):
            if len(entries) != expected or run.entry_count != expected:
                raise CommandError(f"Chỉ có {len(entries)}/{expected} buổi được xếp")
            assert_no_conflicts(entries)
        elif entries:
            raise CommandError("Lần chạy thất bại nhưng vẫn ghi lịch")

        approval_seconds = None
        export_rows = 0
        if options["approve"] and entries:
            start = perf_counter()
            approve_algorithm_run(run.pk, actor)
            approval_seconds = round(perf_counter() - start, 3)
            for faculty in Faculty.objects.filter(code__startswith="TEST_"):
                approved = approved_assignments(semester, faculty)
                content = assignment_workbook_bytes(semester, faculty, approved)
                book = load_workbook(BytesIO(content), read_only=True)
                export_rows += book["PhanCong"].max_row - 1
                book.close()
            if export_rows != expected:
                raise CommandError(f"Xuất Excel thiếu dòng: {export_rows}/{expected}")

        result = {
            "semester": semester.name, "expected_sessions": expected,
            "run_id": run.pk, "status": run.status, "scheduled_sessions": len(entries),
            "objective_before": run.objective_before, "objective_after": run.objective,
            "optimization_trials": run.optimization_trials,
            "diagnostic_rows": len(run.diagnostics), "enqueue_seconds": enqueue_seconds,
            "worker_seconds": solve_seconds, "approval_seconds": approval_seconds,
            "export_rows": export_rows, "message": run.message,
        }
        report_path = Path(options["report"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(result, ensure_ascii=True))
        if options["expect_status"] and run.status != options["expect_status"]:
            raise CommandError(
                f"Trạng thái {run.status} khác kỳ vọng {options['expect_status']}; "
                f"xem {report_path} và chẩn đoán lần chạy #{run.pk}"
            )
        if options["approve"] and not entries:
            raise CommandError(
                f"Không có lịch để duyệt/xuất (trạng thái {run.status}); "
                f"xem {report_path} và chẩn đoán lần chạy #{run.pk}"
            )
