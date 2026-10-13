"""Database-backed automatic scheduling queue and one-shot worker operation."""

import logging

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from .auto_schedule import AUTO_SHEETS, read_auto_files, run_from_workbooks
from .auto_schedule_errors import InputIssues
from .models import AlgorithmRun, ScheduleRunQueue, Semester


log = logging.getLogger(__name__)


def enqueue_schedule(semester_id, files, actor):
    """Check workbook shape and atomically reserve this semester's active slot."""
    content = {}
    read_auto_files(files)
    for kind in AUTO_SHEETS:
        upload = files.get(kind)
        upload.seek(0)
        content[kind] = upload.read()
    try:
        with transaction.atomic():
            semester = Semester.objects.select_for_update().get(pk=semester_id)
            if semester.status == "DaKhoa":
                raise ValueError("Học kỳ đã khóa")
            active = ScheduleRunQueue.objects.filter(semester=semester).select_related("run").first()
            if active:
                raise ValueError(f"Học kỳ đang có lần chạy #{active.run_id}; hãy chờ kết quả trước khi chạy lại")
            run = AlgorithmRun.objects.create(semester=semester, created_by=actor,
                                              status="QUEUED", message="Đang chờ tiến trình xếp lịch")
            ScheduleRunQueue.objects.create(
                semester=semester, run=run,
                courses_file=content["courses"], rooms_file=content["rooms"],
                lecturers_file=content["lecturers"],
            )
            return run
    except IntegrityError as exc:
        raise ValueError("Học kỳ đang có lần chạy khác; hãy chờ kết quả trước khi chạy lại") from exc


def process_next_run():
    """Claim and execute one queued run; return its final AlgorithmRun or None."""
    # A crash after committing results can leave only the small queue record.
    ScheduleRunQueue.objects.exclude(run__status__in=("QUEUED", "RUNNING")).delete()
    run_id = None
    for queued_id in ScheduleRunQueue.objects.filter(run__status="QUEUED").order_by("pk").values_list("run_id", flat=True):
        with transaction.atomic():
            changed = AlgorithmRun.objects.filter(pk=queued_id, status="QUEUED").update(
                status="RUNNING", started_at=timezone.now(), message="Đang xếp lịch",
            )
            if changed:
                run_id = queued_id
                break
    if run_id is None:
        return None

    try:
        queued = ScheduleRunQueue.objects.select_related("run").get(run_id=run_id)
        files = {
            "courses": SimpleUploadedFile("courses.xlsx", bytes(queued.courses_file)),
            "rooms": SimpleUploadedFile("rooms.xlsx", bytes(queued.rooms_file)),
            "lecturers": SimpleUploadedFile("lecturers.xlsx", bytes(queued.lecturers_file)),
        }
        run_from_workbooks(queued.semester_id, files, queued.run.created_by, existing_run_id=run_id)
    except InputIssues as exc:
        AlgorithmRun.objects.filter(pk=run_id).update(
            status="ERROR", message=f"Phát hiện {len(exc.issues)} lỗi dữ liệu đầu vào",
            diagnostics=exc.issues,
        )
    except ValueError as exc:
        message = str(exc)
        AlgorithmRun.objects.filter(pk=run_id).update(status="ERROR", message=message)
    except Exception:
        log.exception("Automatic scheduling run %s failed", run_id)
        AlgorithmRun.objects.filter(pk=run_id).update(
            status="ERROR", message="Lỗi xử lý ngoài dự kiến; xem nhật ký tiến trình xếp lịch",
        )
    finally:
        with transaction.atomic():
            AlgorithmRun.objects.filter(pk=run_id).update(finished_at=timezone.now())
            ScheduleRunQueue.objects.filter(run_id=run_id).delete()
    return AlgorithmRun.objects.get(pk=run_id)
