"""Reproducible descriptive analysis of the 30 ITC 2019 competition instances.

Run from the project root with: python analysis/itc2019_eda.py
This reads XML inputs and never modifies them.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from statistics import median
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "raw_itc2019"
OUTPUT = ROOT / "outputs" / "eda_itc2019"

GROUPS = {
    "Early": "agh-fis-spr17 agh-ggis-spr17 bet-fal17 iku-fal17 mary-spr17 muni-fi-spr16 muni-fsps-spr17 muni-pdf-spr16c pu-llr-spr17 tg-fal17".split(),
    "Middle": "agh-ggos-spr17 agh-h-spr17 lums-spr18 muni-fi-spr17 muni-fsps-spr17c muni-pdf-spr16 nbi-spr18 pu-d5-spr17 pu-proj-fal19 yach-fal17".split(),
    "Late": "agh-fal17 bet-spr18 iku-spr18 lums-fal17 mary-fal18 muni-fi-fal17 muni-fspsx-fal17 muni-pdfx-fal17 pu-d9-fal19 tg-spr18".split(),
}
COLORS = {"Early": "#3274a1", "Middle": "#e1812c", "Late": "#3a9d7d"}
GROUP_BY_NAME = {name: group for group, names in GROUPS.items() for name in names}


def read_instance(path: Path) -> tuple[dict, list[dict], Counter]:
    """Stream a large XML instance, recording counts without keeping the tree."""
    summary = {
        "instance": path.stem,
        "group": GROUP_BY_NAME[path.stem],
        "file_bytes": path.stat().st_size,
        "courses": 0,
        "classes": 0,
        "rooms": 0,
        "students": 0,
        "room_unavailable_blocks": 0,
        "hard_distributions": 0,
        "soft_distributions": 0,
        "classes_without_room": 0,
        "single_placement_classes": 0,
    }
    classes = []
    distribution_types = Counter()
    parents = []
    for event, element in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if element.tag == "problem":
                summary["xml_name"] = element.get("name")
                summary["days"] = int(element.get("nrDays"))
                summary["weeks"] = int(element.get("nrWeeks"))
                summary["slots_per_day"] = int(element.get("slotsPerDay"))
            parents.append(element.tag)
            continue
        parent = parents[-2] if len(parents) > 1 else None
        if element.tag == "room" and parent == "rooms":
            summary["rooms"] += 1
            summary["room_unavailable_blocks"] += len(element.findall("unavailable"))
            element.clear()
        elif element.tag == "class" and parent == "subpart":
            times = element.findall("time")
            rooms = element.findall("room")
            n_time, n_room = len(times), len(rooms)
            summary["classes"] += 1
            summary["classes_without_room"] += int(n_room == 0)
            summary["single_placement_classes"] += int(n_time == 1 and n_room <= 1)
            classes.append({
                "instance": path.stem,
                "class_id": element.get("id"),
                "student_limit": int(element.get("limit", "0")),
                "time_options": n_time,
                "room_options": n_room,
                "raw_placement_options": n_time * max(1, n_room),
            })
            element.clear()
        elif element.tag == "course" and parent == "courses":
            summary["courses"] += 1
            element.clear()
        elif element.tag == "distribution" and parent == "distributions":
            required = element.get("required", "false").lower() == "true"
            summary["hard_distributions" if required else "soft_distributions"] += 1
            distribution_types[(path.stem, element.get("type", "unknown"), "hard" if required else "soft")] += 1
            element.clear()
        elif element.tag == "student" and parent == "students":
            summary["students"] += 1
            element.clear()
        parents.pop()
    if summary["xml_name"] != path.stem:
        raise ValueError(f"Name mismatch in {path.name}: {summary['xml_name']}")
    if not classes or summary["courses"] == 0:
        raise ValueError(f"No courses/classes in {path.name}")
    summary["median_time_options"] = median(row["time_options"] for row in classes)
    room_choices = [row["room_options"] for row in classes if row["room_options"]]
    summary["median_room_options_with_room"] = median(room_choices) if room_choices else 0
    summary["median_raw_placement_options"] = median(row["raw_placement_options"] for row in classes)
    summary["classes_per_room"] = round(summary["classes"] / summary["rooms"], 2)
    summary["no_room_percent"] = round(100 * summary["classes_without_room"] / summary["classes"], 2)
    return summary, classes, distribution_types


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 14,
        "axes.labelsize": 11,
        "figure.facecolor": "white",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": 200,
    })


def save(name: str) -> None:
    plt.savefig(OUTPUT / name, bbox_inches="tight", facecolor="white")
    plt.close()


def draw_charts(rows: list[dict], classes: list[dict]) -> None:
    style()
    ordered = sorted(rows, key=lambda row: row["classes"])
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh([r["instance"] for r in ordered], [r["classes"] for r in ordered],
            color=[COLORS[r["group"]] for r in ordered])
    ax.set(xlabel="Số lớp", title="Quy mô lớp học của 30 instance ITC 2019")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.legend(handles=[Patch(facecolor=COLORS[group], label=group) for group in GROUPS],
              title="Đợt công bố", loc="lower right")
    fig.tight_layout()
    save("01_quy_mo_lop_30_instance.png")

    fig, ax = plt.subplots(figsize=(10, 6.5))
    for group in GROUPS:
        subset = [r for r in rows if r["group"] == group]
        ax.scatter([r["classes"] for r in subset], [r["rooms"] for r in subset],
                   s=70, alpha=0.85, label=group, color=COLORS[group])
    for name in ("muni-fi-fal17", "agh-fal17", "pu-proj-fal19"):
        row = next(r for r in rows if r["instance"] == name)
        ax.annotate(name, (row["classes"], row["rooms"]), xytext=(5, 5), textcoords="offset points", fontsize=9)
    ax.set(xlabel="Số lớp", ylabel="Số phòng", title="Số lớp và số phòng theo instance")
    ax.legend(title="Đợt công bố")
    fig.tight_layout()
    save("02_so_lop_va_so_phong.png")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for group in GROUPS:
        subset = [r for r in rows if r["group"] == group]
        axes[0].scatter([r["classes"] for r in subset], [r["median_time_options"] for r in subset],
                        s=65, alpha=0.85, label=group, color=COLORS[group])
        axes[1].scatter([r["classes"] for r in subset],
                        [r["median_room_options_with_room"] for r in subset],
                        s=65, alpha=0.85, label=group, color=COLORS[group])
    axes[0].set(xlabel="Số lớp", ylabel="Trung vị lựa chọn thời gian/lớp", title="Lựa chọn thời gian")
    axes[1].set(xlabel="Số lớp", ylabel="Trung vị lựa chọn phòng/lớp có phòng", title="Lựa chọn phòng")
    axes[1].legend(title="Đợt công bố")
    fig.suptitle("Độ rộng tập lựa chọn của 30 instance", fontsize=15)
    fig.tight_layout()
    save("03_lua_chon_thoi_gian_va_phong.png")

    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh([r["instance"] for r in ordered], [r["hard_distributions"] for r in ordered],
            color="#395f91", label="Bắt buộc")
    ax.barh([r["instance"] for r in ordered], [r["soft_distributions"] for r in ordered],
            left=[r["hard_distributions"] for r in ordered], color="#e6a450", label="Ưu tiên")
    ax.set(xlabel="Số ràng buộc distribution trong XML", title="Ràng buộc phân bố của 30 instance")
    ax.legend()
    fig.tight_layout()
    save("04_rang_buoc_distribution.png")

    fig, ax = plt.subplots(figsize=(12, 10))
    no_room = sorted(rows, key=lambda row: row["no_room_percent"])
    ax.barh([r["instance"] for r in no_room], [r["no_room_percent"] for r in no_room],
            color=[COLORS[r["group"]] for r in no_room])
    ax.set(xlabel="Tỷ lệ lớp không yêu cầu phòng (%)",
           title="Lớp không yêu cầu phòng trong 30 instance")
    fig.tight_layout()
    save("05_lop_khong_can_phong.png")

    selected = [c for c in classes if c["instance"] == "muni-fi-fal17"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax, key, title in (
        (axes[0], "time_options", "Số lựa chọn thời gian"),
        (axes[1], "room_options", "Số lựa chọn phòng (0 = không cần phòng)"),
    ):
        values = [c[key] for c in selected]
        ax.hist(values, bins=min(25, max(5, int(len(set(values)) ** 0.5 * 3))),
                color="#3274a1" if key == "time_options" else "#3a9d7d", edgecolor="white")
        ax.axvline(median(values), color="#b64242", linestyle="--", label=f"Trung vị = {median(values):g}")
        ax.set(xlabel=title, ylabel="Số lớp", title=title)
        ax.legend()
    fig.suptitle("Phân bố lựa chọn ở muni-fi-fal17", fontsize=15)
    fig.tight_layout()
    save("06_phan_bo_lua_chon_muni_fi_fal17.png")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    expected = set(GROUP_BY_NAME)
    files = {path.stem: path for path in INPUT.glob("*.xml") if path.stem in expected}
    if set(files) != expected:
        raise ValueError(f"Expected 30 named instances; missing={sorted(expected-set(files))}")
    duplicate = INPUT / "pu-proj-fal19 (1).xml"
    original = INPUT / "pu-proj-fal19.xml"
    if duplicate.exists() and hashlib.sha256(duplicate.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
        raise ValueError("The apparent duplicate pu-proj-fal19 (1).xml differs from the original")
    rows, all_classes, all_distributions = [], [], Counter()
    for name in sorted(expected):
        summary, classes, distributions = read_instance(files[name])
        rows.append(summary)
        all_classes.extend(classes)
        all_distributions.update(distributions)
        print(f"{name}: {summary['classes']} classes, {summary['rooms']} rooms")
    write_csv(OUTPUT / "instance_summary.csv", rows, list(rows[0]))
    write_csv(OUTPUT / "class_options.csv", all_classes, list(all_classes[0]))
    distribution_rows = [
        {"instance": name, "type": kind, "severity": severity, "count": count}
        for (name, kind, severity), count in sorted(all_distributions.items())
    ]
    write_csv(OUTPUT / "distribution_types.csv", distribution_rows,
              ["instance", "type", "severity", "count"])
    draw_charts(rows, all_classes)
    print(f"Wrote {len(rows)} instance summaries and {len(all_classes)} class rows to {OUTPUT}")


if __name__ == "__main__":
    main()
