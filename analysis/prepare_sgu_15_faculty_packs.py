"""Create three reproducible, independent SGU public-data demo Excel packs.

Requires PDFs and source_manifest.json fetched by sgu_public_demo.py --fetch.
The resulting teaching demands are sampled from public timetables. Every
operational attribute that the PDFs lack remains an explicit demo assumption.
"""

import argparse
import json
from pathlib import Path

from sgu_public_demo import build, parse_common_pdf, parse_specialized_pdf


PACKS = (("bo_01", 240, 41), ("bo_02", 480, 42), ("bo_03", 960, 43))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("outputs/sgu_public_sources"))
    parser.add_argument("--output-dir", type=Path, default=Path("samples/sgu_15_khoa"))
    args = parser.parse_args()
    source = json.loads((args.source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    programs = sorted(source["files"])
    raw = [row for code in programs for row in (
        parse_common_pdf(args.source_dir / f"{code}.pdf") if code == "TKB_MONCHUNG"
        else parse_specialized_pdf(args.source_dir / f"{code}.pdf", code)
    )]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, sessions, seed in PACKS:
        semester = f"SGU DEMO 15 khoa - {name.upper()}"
        destination = args.output_dir / name
        manifest = build(destination, programs, args.source_dir, semester=semester,
                         max_sessions=sessions, seed=seed, raw_rows=raw)
        (destination / "provenance.json").replace(args.output_dir / f"{name}_provenance.json")
        summary.append({"folder": name, "semester": semester, "sessions": sessions,
                        "faculties": manifest["counts"]["courses"]["Khoa"],
                        "lecturers": manifest["counts"]["lecturers"]["GiangVien"],
                        "rooms": manifest["counts"]["rooms"]["PhongHoc"]})
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
