"""Generate reproducible fictional three-workbook scheduling fixtures."""

import json

from django.core.management.base import BaseCommand

from school.sample_data import write_workbooks


class Command(BaseCommand):
    help = "Generate synthetic courses, rooms and lecturers Excel files for load testing."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--sessions", type=int, default=80)
        parser.add_argument("--semester-name", default="HK giả lập 2026-2027")
        parser.add_argument("--weeks", type=int, default=16)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--scenario", choices=("feasible", "constrained", "infeasible",
                                                   "varied_weeks"),
                            default="feasible")

    def handle(self, *args, **options):
        manifest = write_workbooks(
            options["output_dir"], sessions=options["sessions"],
            semester_name=options["semester_name"], weeks=options["weeks"],
            seed=options["seed"], scenario=options["scenario"],
        )
        self.stdout.write(json.dumps(manifest, ensure_ascii=False, indent=2))
