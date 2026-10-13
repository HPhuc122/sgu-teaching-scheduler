"""Run the automatic scheduling worker as a separate Django process."""

from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction

from school.models import AlgorithmRun, ScheduleRunQueue
from school.schedule_queue import process_next_run


class Command(BaseCommand):
    help = "Process queued automatic schedules. Use --once for one job, otherwise poll continuously."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-seconds", type=float, default=2.0)
        parser.add_argument("--recover-run", type=int)

    def handle(self, *args, **options):
        if options["recover_run"] is not None:
            with transaction.atomic():
                queued = ScheduleRunQueue.objects.filter(run_id=options["recover_run"]).first()
                if queued is None or queued.run.status != "RUNNING":
                    raise ValueError("Chỉ khôi phục được lần chạy RUNNING còn trong hàng đợi")
                AlgorithmRun.objects.filter(pk=queued.run_id, status="RUNNING").update(
                    status="QUEUED", started_at=None, message="Đã đưa lại vào hàng đợi sau khi worker dừng",
                )
            self.stdout.write(f"Recovered run #{queued.run_id}")
            return
        if options["poll_seconds"] <= 0:
            raise ValueError("--poll-seconds must be positive")
        while True:
            run = process_next_run()
            if run:
                self.stdout.write(f"Run #{run.pk}: {run.status}")
            if options["once"]:
                return
            if run is None:
                sleep(options["poll_seconds"])
