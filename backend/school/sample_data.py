"""Reproducible synthetic inputs for the three-workbook scheduling flow.

All names and identifiers are fictional. These data are test fixtures, not
examples of an official SGU form or policy.
"""

from collections import defaultdict
from hashlib import sha256
from io import BytesIO
from math import ceil
from pathlib import Path
from random import Random

from openpyxl import Workbook

from .auto_schedule import AUTO_SHEETS, MAX_BYTES, MAX_ROWS


def synthetic_rows(*, sessions, semester_name, weeks=16, seed=42, scenario="feasible"):
    if not 3 <= sessions <= 2500:
        raise ValueError("Số buổi giả lập phải từ 3 đến 2500")
    if not 1 <= weeks <= 53:
        raise ValueError("Số tuần phải từ 1 đến 53")
    if scenario not in ("feasible", "constrained", "infeasible", "varied_weeks"):
        raise ValueError("Kịch bản phải là feasible, constrained, infeasible hoặc varied_weeks")
    rng = Random(seed)
    faculty_codes = ("TEST_CNTT", "TEST_KHTN", "TEST_NN")
    department_codes = ("TEST_CNPM", "TEST_TOAN", "TEST_NN")
    program_codes = ("TEST_CTR1", "TEST_CTR2", "TEST_CTR3")
    course_count = max(4, ceil(sessions / 12))
    constrained = scenario == "constrained"
    room_count = max(12, ceil(sessions / (19 if constrained else 11)))
    teacher_count = max(15, ceil(sessions / (8 if constrained else 7)))
    cohort_count = max(12, ceil(sessions / 10))
    cycle = "2026-2030"
    week_text = f"1-{weeks}" if weeks > 1 else "1"
    midpoint = (weeks + 1) // 2
    week_patterns = (
        week_text,
        f"1-{midpoint}" if midpoint > 1 else "1",
        f"{midpoint + 1}-{weeks}" if midpoint < weeks - 1 else str(weeks),
        ",".join(str(number) for number in range(1, weeks + 1, 2)),
        ",".join(str(number) for number in range(2, weeks + 1, 2)) or "1",
    )
    rows = {kind: {sheet: [] for sheet in sheets}
            for kind, sheets in AUTO_SHEETS.items()}
    courses, rooms, lecturers = rows["courses"], rows["rooms"], rows["lecturers"]

    for index, (faculty, department, program) in enumerate(
            zip(faculty_codes, department_codes, program_codes), 1):
        courses["Khoa"].append((faculty, f"Khoa giả lập {index}"))
        courses["BoMon"].append((department, f"Bộ môn giả lập {index}", faculty))
        courses["ChuongTrinh"].append((program, f"Chương trình giả lập {index}", faculty, cycle))

    course_codes = [f"TEST_HP_{index:03d}" for index in range(1, course_count + 1)]
    for index, code in enumerate(course_codes):
        department = department_codes[index % 3]
        common = index % 5 == 0
        courses["HocPhan"].append((code, f"Học phần giả lập {index + 1}", 3,
                                   department, "CHUNG" if common else "CHUYEN_NGANH"))
        target_programs = program_codes if common else (program_codes[index % 3],)
        for program in target_programs:
            courses["HocPhanChuongTrinh"].append((code, program, cycle, "BAT_BUOC"))

    group_numbers = defaultdict(int)
    shuffled_courses = list(range(course_count))
    rng.shuffle(shuffled_courses)
    generated_groups = {}
    for index in range(sessions):
        group_index = index // 2 if scenario == "varied_weeks" else index
        if group_index not in generated_groups:
            course_index = shuffled_courses[group_index % course_count]
            code = course_codes[course_index]
            group_numbers[code] += 1
            group = f"{group_numbers[code]:02d}"
            cohort = "TEST_BLOCKED" if scenario == "infeasible" and index < 3 else \
                f"TEST_LOP_{group_index % cohort_count:03d}"
            generated_groups[group_index] = (code, group)
            courses["NhomHocPhan"].append((code, semester_name, group, "", 35, cohort))
        code, group = generated_groups[group_index]
        lab = index % 4 == 0
        days = "2" if scenario == "infeasible" and index < 3 else "2-6"
        count = 5 if scenario == "infeasible" and index < 3 else 2
        demand_weeks = (week_patterns[(group_index + (index % 2 if group_index % 3 == 0 else 0))
                                      % len(week_patterns)] if scenario == "varied_weeks" else week_text)
        demand_code = f"BUOI_{index % 2 + 1}" if scenario == "varied_weeks" else "BUOI_1"
        courses["BuoiHocYeuCau"].append((code, group, "", demand_code, count, demand_weeks,
                                        "MayTinh" if lab else "LyThuyet", days))

    for index in range(room_count):
        room_type = "MayTinh" if index % 4 == 0 else "LyThuyet"
        code = f"TEST.P{index + 1:03d}"
        rooms["PhongHoc"].append((code, "TEST", "Tòa giả lập", f"Phòng {index + 1}",
                                  50, room_type, "SanSang"))
        if constrained and index % 4 == 0:
            rooms["PhongKhongKhaDung"].append((code, 2, 1, 5, week_text))
        elif index % 11 == 0:
            rooms["PhongKhongKhaDung"].append((code, 7, 1, 2, week_text))

    for index in range(teacher_count):
        code = f"TEST_GV_{index + 1:03d}"
        department_index = index % 3
        lecturers["GiangVien"].append((code, f"Giảng viên giả lập {index + 1}", "",
                                       faculty_codes[department_index],
                                       department_codes[department_index], "DangCongTac"))
        if constrained and index % 4 == 0:
            lecturers["GiangVienKhongKhaDung"].append((code, 2, 1, 5, week_text))
        elif index % 13 == 0:
            lecturers["GiangVienKhongKhaDung"].append((code, 7, 1, 2, week_text))
    for index, course_code in enumerate(course_codes):
        for offset in range(3):
            teacher_index = (index * 3 + offset) % teacher_count
            lecturers["GiangVienHocPhan"].append((f"TEST_GV_{teacher_index + 1:03d}",
                                                  course_code))

    for kind, sheets in rows.items():
        count = sum(len(items) for items in sheets.values())
        if count > MAX_ROWS:
            raise ValueError(f"File {kind} cần {count} dòng, vượt giới hạn {MAX_ROWS}")
    return rows


def workbook_bytes(kind, sheets):
    book = Workbook()
    book.remove(book.active)
    for name, headers in AUTO_SHEETS[kind].items():
        sheet = book.create_sheet(name)
        sheet.append(headers)
        sheet.freeze_panes = "A2"
        for index, header in enumerate(headers, 1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = max(18, len(header) + 2)
        for values in sheets[name]:
            sheet.append(values)
            for column, header in enumerate(headers, 1):
                if header.startswith("ma_") or header in ("nhom", "to_th", "ten_lop"):
                    sheet.cell(sheet.max_row, column).number_format = "@"
    output = BytesIO()
    book.save(output)
    content = output.getvalue()
    if len(content) > MAX_BYTES:
        raise ValueError(f"File {kind} vượt giới hạn {MAX_BYTES // 1024 // 1024} MB")
    return content


def write_workbooks(output_dir, *, sessions, semester_name, weeks=16, seed=42,
                    scenario="feasible"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = synthetic_rows(sessions=sessions, semester_name=semester_name, weeks=weeks,
                          seed=seed, scenario=scenario)
    manifest = {"sessions": sessions, "semester_name": semester_name,
                "weeks": weeks, "seed": seed, "scenario": scenario, "files": {}}
    for kind, sheets in rows.items():
        content = workbook_bytes(kind, sheets)
        path = output_dir / f"{kind}.xlsx"
        path.write_bytes(content)
        manifest["files"][kind] = {"path": str(path), "bytes": len(content),
                                   "sha256": sha256(content).hexdigest(),
                                   "rows": {name: len(items) for name, items in sheets.items()}}
    return manifest
