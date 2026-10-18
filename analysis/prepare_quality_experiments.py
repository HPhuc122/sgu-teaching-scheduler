"""Copy original workbooks byte-for-byte and add reproducible soft-criteria sidecars.

No workbook is authored or changed. The sidecar is consumed only by the isolated
benchmark command; production workbook schemas and the original data stay intact.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import shutil

from openpyxl import load_workbook


def build_profile(folder, seed):
    book = load_workbook(folder / "lecturers.xlsx", read_only=True, data_only=True)
    try:
        teachers = sorted(str(row[0]) for row in book["GiangVien"].iter_rows(min_row=2, values_only=True)
                          if row[0] is not None)
        pairs = sorted((str(row[0]), str(row[1])) for row in
                       book["GiangVienHocPhan"].iter_rows(min_row=2, values_only=True)
                       if row[0] is not None)
    finally:
        book.close()
    rng = Random(seed)
    return {
        "format_version": 1, "simulated": True, "seed": seed,
        "note": "Dữ liệu thực nghiệm mô phỏng; không phải nguyện vọng/phân công chính thức của SGU.",
        "workbook_sha256": {kind: sha256((folder / f"{kind}.xlsx").read_bytes()).hexdigest()
                            for kind in ("courses", "rooms", "lecturers")},
        "qualification_priorities": [{"employee_code": teacher, "course_code": course,
                                      "priority": rng.randint(1, 4)} for teacher, course in pairs],
        "preferences": [{"employee_code": teacher, "kind": "KhungGio", "day": None,
                         "time_block": rng.choice(("Sang", "Chieu")), "priority": rng.randint(1, 4)}
                        for teacher in teachers],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("samples/sgu_15_khoa"))
    parser.add_argument("--output-dir", type=Path, default=Path("samples/sgu_15_khoa_soft"))
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--verify", action="store_true", help="Verify hashes and reproducibility without writing")
    args = parser.parse_args()
    source, target = args.source_dir.resolve(), args.output_dir.resolve()
    if target == source or source in target.parents or target in source.parents:
        parser.error("Thư mục thực nghiệm phải tách biệt thư mục gốc")
    if args.verify:
        for index, pack in enumerate(("bo_01", "bo_02", "bo_03")):
            destination = target / pack
            for kind in ("courses", "rooms", "lecturers"):
                if (source / pack / f"{kind}.xlsx").read_bytes() != (destination / f"{kind}.xlsx").read_bytes():
                    raise ValueError(f"Workbook gốc và bản sao khác nhau: {pack}/{kind}")
            expected = build_profile(destination, args.seed + index)
            actual = json.loads((destination / "experiment.json").read_text(encoding="utf-8"))
            if expected != actual:
                raise ValueError(f"Cấu hình không tái lập được bằng seed đã cho: {pack}")
            print(f"{pack}: OK")
        return
    if target.exists():
        parser.error("Thư mục đích đã tồn tại; không ghi đè dữ liệu")
    for pack in ("bo_01", "bo_02", "bo_03"):
        for kind in ("courses", "rooms", "lecturers"):
            if not (source / pack / f"{kind}.xlsx").is_file():
                parser.error(f"Thiếu workbook nguồn: {pack}/{kind}")
    for index, pack in enumerate(("bo_01", "bo_02", "bo_03")):
        destination = target / pack
        destination.mkdir(parents=True)
        for kind in ("courses", "rooms", "lecturers"):
            shutil.copyfile(source / pack / f"{kind}.xlsx", destination / f"{kind}.xlsx")
        profile = build_profile(destination, args.seed + index)
        (destination / "experiment.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"pack": pack, "preferences": len(profile["preferences"]),
                          "qualifications": len(profile["qualification_priorities"])}))


if __name__ == "__main__":
    main()
