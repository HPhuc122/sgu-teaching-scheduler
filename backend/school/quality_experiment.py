"""Opt-in soft criteria for isolated experiments, never the upload/API format."""

from hashlib import sha256
import json
from pathlib import Path

from django.db import transaction

from .models import Lecturer, LecturerPreference, TeachingQualification


def load_experiment(path, file_data, parsed):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if profile.get("format_version") != 1 or profile.get("simulated") is not True:
        raise ValueError("Cấu hình thực nghiệm phải ghi rõ phiên bản 1 và dữ liệu mô phỏng")
    expected_hashes = {kind: sha256(content).hexdigest() for kind, content in file_data.items()}
    if profile.get("workbook_sha256") != expected_hashes:
        raise ValueError("Cấu hình thực nghiệm không khớp nội dung ba workbook")
    allowed = {(r["ma_vien_chuc"], r["ma_mon_hoc"])
               for r in parsed["lecturers"]["GiangVienHocPhan"]}
    priorities = profile.get("qualification_priorities", [])
    keys = [(r["employee_code"], r["course_code"]) for r in priorities]
    if len(keys) != len(set(keys)) or set(keys) != allowed:
        raise ValueError("Mức ưu tiên phải phủ đúng từng cặp giảng viên/học phần trong đầu vào")
    if any(type(r["priority"]) is not int or not 1 <= r["priority"] <= 5 for r in priorities):
        raise ValueError("Mức ưu tiên chuyên môn phải từ 1 đến 5")
    teacher_codes = {r["ma_vien_chuc"] for r in parsed["lecturers"]["GiangVien"]}
    preferences = profile.get("preferences", [])
    pref_codes = [r["employee_code"] for r in preferences]
    if len(pref_codes) != len(set(pref_codes)) or set(pref_codes) != teacher_codes:
        raise ValueError("Thực nghiệm cần đúng một nguyện vọng khung giờ cho mỗi giảng viên")
    for row in preferences:
        if (row.get("kind") != "KhungGio" or row.get("day") is not None
                or row.get("time_block") not in ("Sang", "Chieu", "Toi")
                or type(row.get("priority")) is not int or not 1 <= row["priority"] <= 4):
            raise ValueError("Nguyện vọng mô phỏng không hợp lệ")
    return profile


@transaction.atomic
def apply_experiment(semester, profile):
    """Call only after catalog import in a fresh, explicitly isolated benchmark DB."""
    if LecturerPreference.objects.filter(semester=semester).exists():
        raise ValueError("Học kỳ thực nghiệm đã có nguyện vọng; cần database mới")
    for row in profile["qualification_priorities"]:
        updated = TeachingQualification.objects.filter(
            lecturer__employee_code=row["employee_code"], course__code=row["course_code"],
        ).update(priority=row["priority"])
        if updated != 1:
            raise ValueError("Không tìm thấy duy nhất chuyên môn cần áp dụng")
    teachers = {t.employee_code: t for t in Lecturer.objects.filter(
        employee_code__in=[r["employee_code"] for r in profile["preferences"]])}
    LecturerPreference.objects.bulk_create([
        LecturerPreference(semester=semester, lecturer=teachers[r["employee_code"]],
                           kind=r["kind"], day=r["day"], time_block=r["time_block"],
                           priority=r["priority"], note="Nguyện vọng mô phỏng cho thực nghiệm")
        for r in profile["preferences"]
    ])
