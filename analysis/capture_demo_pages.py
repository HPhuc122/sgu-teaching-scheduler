"""Save rendered demo pages from an isolated benchmark SQLite database."""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from school.models import AlgorithmRun, ScheduleEntry  # noqa: E402


def save(client, url, path):
    response = client.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"{url}: HTTP {response.status_code}")
    path.write_bytes(response.content)


def main():
    if not os.environ.get("UCTP_SQLITE_PATH"):
        raise RuntimeError("Chỉ chạy với UCTP_SQLITE_PATH trỏ tới SQLite benchmark riêng")
    output = ROOT / "outputs" / "screenshots" / "html"
    output.mkdir(parents=True, exist_ok=True)
    run = AlgorithmRun.objects.order_by("pk").first()
    entry = ScheduleEntry.objects.filter(algorithm_run=run, status="DaDuyet").select_related(
        "lecturer"
    ).first()
    if run is None or entry is None:
        raise RuntimeError("Cần một benchmark đã duyệt trước khi chụp giao diện")

    admin = get_user_model().objects.get(username="synthetic_benchmark_admin")
    client = Client()
    client.force_login(admin)
    save(client, f"/admin/auto-schedule/?run={run.pk}", output / "admin_run.html")
    save(client, f"/admin/review-schedules/?semester={run.semester_id}&run={run.pk}",
         output / "admin_review.html")

    teacher, _ = get_user_model().objects.get_or_create(
        username="synthetic_demo_lecturer", defaults={"is_active": True}
    )
    teacher.set_unusable_password()
    teacher.save(update_fields=["password"])
    entry.lecturer.user = teacher
    entry.lecturer.save(update_fields=["user"])
    client.force_login(teacher)
    save(client, "/portal/", output / "lecturer_portal.html")
    print(output)


if __name__ == "__main__":
    main()
