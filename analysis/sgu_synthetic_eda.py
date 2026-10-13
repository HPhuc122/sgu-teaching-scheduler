"""Descriptive charts for the system's synthetic three-workbook test data."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
OUTPUT = ROOT / "outputs" / "eda_sgu_synthetic"
SIZES = (80, 160, 320, 449, 1000, 2000)


def sheet_rows(path: Path, sheet: str) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    values = workbook[sheet].values
    headers = next(values)
    rows = [dict(zip(headers, row)) for row in values if any(value is not None for value in row)]
    workbook.close()
    return rows


def save(name: str) -> None:
    plt.savefig(OUTPUT / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 14,
        "axes.spines.top": False, "axes.spines.right": False,
    })
    summary = []
    for size in SIZES:
        base = SAMPLES / f"synthetic_{size}_seed42"
        courses = sheet_rows(base / "courses.xlsx", "HocPhan")
        groups = sheet_rows(base / "courses.xlsx", "NhomHocPhan")
        sessions = sheet_rows(base / "courses.xlsx", "BuoiHocYeuCau")
        rooms = sheet_rows(base / "rooms.xlsx", "PhongHoc")
        lecturers = sheet_rows(base / "lecturers.xlsx", "GiangVien")
        summary.append({"bo_du_lieu": base.name, "hoc_phan": len(courses),
                        "nhom": len(groups), "buoi": len(sessions),
                        "phong": len(rooms), "giang_vien": len(lecturers)})
    with (OUTPUT / "synthetic_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    sizes = [row["buoi"] for row in summary]
    ax.plot(sizes, [row["giang_vien"] for row in summary], "o-", label="Giảng viên", color="#3274a1")
    ax.plot(sizes, [row["phong"] for row in summary], "s-", label="Phòng", color="#e1812c")
    ax.set(xlabel="Số buổi yêu cầu", ylabel="Số nguồn lực",
           title="Quy mô nguồn lực trong sáu bộ dữ liệu giả lập")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    save("01_quy_mo_nguon_luc_gia_lap.png")

    base = SAMPLES / "synthetic_1000_seed42"
    sessions = sheet_rows(base / "courses.xlsx", "BuoiHocYeuCau")
    rooms = sheet_rows(base / "rooms.xlsx", "PhongHoc")
    labels = {"LyThuyet": "Lý thuyết", "MayTinh": "Máy tính"}
    demands = Counter(labels.get(row["loai_phong"], row["loai_phong"] or "Không giới hạn") for row in sessions)
    room_types = Counter(labels.get(row["loai_phong"], row["loai_phong"] or "Không ghi") for row in rooms)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].bar(demands.keys(), demands.values(), color="#3274a1")
    axes[0].set(ylabel="Số buổi", title="Nhu cầu theo loại phòng")
    axes[1].bar(room_types.keys(), room_types.values(), color="#3a9d7d")
    axes[1].set(ylabel="Số phòng", title="Nguồn phòng theo loại")
    fig.suptitle("Bộ dữ liệu giả lập 1.000 buổi, seed 42", fontsize=15)
    fig.tight_layout()
    save("02_nhu_cau_va_nguon_phong_gia_lap.png")
    print(f"Wrote {len(summary)} synthetic summaries and two charts to {OUTPUT}")


if __name__ == "__main__":
    main()
