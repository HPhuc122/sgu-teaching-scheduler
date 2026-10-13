"""Create a checksum-verifiable thesis demo snapshot without local databases."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "outputs" / "release"
SOURCE_SUFFIXES = {".py", ".html", ".txt", ".md", ".sql", ".json"}
SAMPLE_SUFFIXES = {".xlsx", ".json", ".md"}
OUTPUT_SUFFIXES = {".xlsx", ".json", ".csv", ".png", ".svg", ".md", ".html"}
FIXED_ZIP_TIME = (2026, 10, 13, 0, 0, 0)
EXPECTED_REPORTS = {
    "freeze_smoke_80.json": ("OPTIMAL", 80, 80),
    "freeze_smoke_1000_correct.json": ("HEURISTIC", 1000, 1000),
    "freeze_varied_80_report.json": ("OPTIMAL", 80, 80),
    "freeze_varied_1000_report.json": ("HEURISTIC", 1000, 1000),
    "freeze_infeasible_1000_report.json": ("INFEASIBLE", 0, 0),
    "freeze_smoke_1000_bad_name.json": ("ERROR", 0, 0),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def files_to_include():
    selected = set()
    for dirname in ("backend", "scheduling", "validator", "tests", "docs", "analysis"):
        for path in (ROOT / dirname).rglob("*"):
            if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
                selected.add(path)
    for path in (ROOT / "samples").rglob("*"):
        if path.is_file() and path.suffix.lower() in SAMPLE_SUFFIXES:
            selected.add(path)
    for dirname in ("diagrams", "eda_itc2019", "eda_sgu_synthetic",
                    "freeze_varied_80", "freeze_varied_1000", "screenshots"):
        for path in (ROOT / "outputs" / dirname).rglob("*"):
            if path.is_file() and path.suffix.lower() in OUTPUT_SUFFIXES:
                selected.add(path)
    for name in EXPECTED_REPORTS:
        selected.add(ROOT / "outputs" / name)
    for name in ("stage1_solver.py", "stage2_solver.py", "stage_b_teacher.py",
                 "stage_b_stage2.py", "uctp_master_pipeline.ipynb", ".gitignore"):
        selected.add(ROOT / name)
    selected.add(ROOT / "database" / "schema.sql")
    return sorted(selected, key=lambda path: path.relative_to(ROOT).as_posix())


def add_bytes(archive, name, content):
    info = ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=9)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="uctp_thesis_freeze_2026-10-13")
    args = parser.parse_args()
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    package = RELEASE_DIR / f"{args.label}.zip"
    if package.exists():
        raise FileExistsError(f"Bản đóng băng đã tồn tại: {package}")

    for name, expected in EXPECTED_REPORTS.items():
        report = json.loads((ROOT / "outputs" / name).read_text(encoding="utf-8"))
        actual = (report["status"], report["scheduled_sessions"], report["export_rows"])
        if actual != expected:
            raise ValueError(f"Báo cáo {name} không đạt cổng kiểm tra: {actual} != {expected}")

    paths = files_to_include()
    records = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        content = path.read_bytes()
        records.append({"path": path.relative_to(ROOT).as_posix(),
                        "bytes": len(content), "sha256": sha256(content)})
    manifest = {
        "label": args.label,
        "file_count": len(records),
        "scope": "Mã nguồn, tài liệu, dữ liệu mẫu hư cấu và bằng chứng kiểm thử; không có SQLite, môi trường Python hay dữ liệu ITC gốc",
        "files": records,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    with ZipFile(package, "w") as archive:
        for path in paths:
            add_bytes(archive, path.relative_to(ROOT).as_posix(), path.read_bytes())
        add_bytes(archive, "manifest.json", manifest_bytes)

    digest = sha256(package.read_bytes())
    (RELEASE_DIR / f"{args.label}.manifest.json").write_bytes(manifest_bytes)
    (RELEASE_DIR / f"{args.label}.sha256").write_text(
        f"{digest}  {package.name}\n", encoding="ascii"
    )
    print(json.dumps({"package": str(package), "files": len(records),
                      "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
