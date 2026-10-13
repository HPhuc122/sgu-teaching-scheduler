"""Build traceable demo Excel files from SGU's public 2026–2027 timetable PDFs.

The public timetable is a reference snapshot. Missing operational attributes
are explicitly marked as assumptions in the manifest; generated workbooks are
not official SGU input files or verified staffing/room inventories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pdfplumber
from openpyxl import Workbook


SOURCE_PAGE = "https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027"
FACULTY_PAGE = "https://www.sgu.edu.vn/danh-sach-cac-don-vi/"
SEMESTER = "Học kỳ 1 - Năm học 2026 - 2027"
DEMO_CYCLE = "DEMO-2026"
HEADERS = {
    "courses": {
        "Khoa": ("ma_khoa", "ten_khoa"),
        "BoMon": ("ma_bo_mon", "ten_bo_mon", "ma_khoa"),
        "ChuongTrinh": ("ma_nganh_ctdt", "ten_chuong_trinh", "ma_khoa", "chu_ky_ctdt"),
        "HocPhan": ("ma_mon_hoc", "ten_mon_hoc", "so_tin_chi", "ma_bo_mon_phu_trach", "loai_mon"),
        "HocPhanChuongTrinh": ("ma_mon_hoc", "ma_nganh_ctdt", "chu_ky_ctdt", "loai_trong_ctdt"),
        "NhomHocPhan": ("ma_mon_hoc", "hoc_ky", "nhom", "to_th", "si_so_du_kien", "ten_lop"),
        "BuoiHocYeuCau": ("ma_mon_hoc", "nhom", "to_th", "ma_buoi", "so_tiet", "tuan_hoc", "loai_phong", "thu_duoc_xep"),
    },
    "rooms": {
        "PhongHoc": ("ma_phong", "ma_toa_nha", "ten_toa_nha", "ten_phong", "suc_chua", "loai_phong", "trang_thai"),
        "PhongKhongKhaDung": ("ma_phong", "thu", "tiet_bat_dau", "so_tiet", "tuan_hoc"),
    },
    "lecturers": {
        "GiangVien": ("ma_vien_chuc", "ho_ten", "email", "ma_khoa", "ma_bo_mon", "trang_thai"),
        "GiangVienHocPhan": ("ma_vien_chuc", "ma_mon_hoc"),
        "GiangVienKhongKhaDung": ("ma_vien_chuc", "thu", "tiet_bat_dau", "so_tiet", "tuan_hoc"),
    },
}

# Association to a faculty is a demo mapping by major name, not an official SGU
# department/teaching responsibility mapping. Each value is an index into the
# official public faculty list below.
FACULTIES = (
    "Khoa Công nghệ Thông tin", "Khoa Giáo dục", "Khoa Giáo dục Chính trị",
    "Khoa Giáo dục Mầm non", "Khoa Giáo dục quốc phòng – An ninh – Giáo dục thể chất",
    "Khoa Giáo dục Tiểu học", "Khoa Khoa học Xã hội và Nghệ thuật",
    "Khoa Kỹ thuật và Công nghệ", "Khoa Luật", "Khoa Ngoại ngữ",
    "Khoa Quản trị Kinh doanh", "Khoa Sư phạm Khoa học Tự nhiên",
    "Khoa Tài chính – Kế toán", "Khoa Toán – Ứng dụng", "Khoa Văn hóa và Du lịch",
)
PROGRAM_FACULTY = {
    "DCT": 0, "DKP": 0, "DDU": 0, "DNT": 0,
    "DGD": 2, "DGM": 3, "DGT": 5,
    "DKD": 7, "DCM": 7, "DCV": 7, "DDE": 7, "DDV": 7, "DKM": 7,
    "DLU": 8, "DAN": 9, "DSA": 9,
    "DQK": 10, "DKQ": 10,
    "DHO": 11, "DKH": 11, "DSI": 11, "DLI": 11,
    "DKE": 12, "DKI": 12, "DTN": 12,
    "DTO": 13, "DTU": 13,
    "DDL": 14, "DHA": 14, "DVI": 14,
    # Demo-only inference by public program title, not an SGU staffing record.
    "DQG": 1, "DTL": 1,
    "DDH": 6, "DDI": 6, "DLD": 6, "DLS": 6, "DMI": 6,
    "DNH": 6, "DQT": 6, "DQV": 6, "DSU": 6, "DTT": 6, "DVA": 6,
}


def faculty_for_row(row):
    if row["program"] != "TKB_MONCHUNG":
        return PROGRAM_FACULTY.get(row["program"], -1)
    name = row["name"].lower()
    if "giáo dục thể chất" in name or "giáo dục quốc phòng" in name:
        return 4
    if "giáo dục học" in name or "tâm lý học" in name or "tâm lí học" in name:
        return 1
    return 6


class PdfLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = {}
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if "/sotaydkmh/261/" in href and href.lower().endswith(".pdf"):
                self.current = [href, ""]

    def handle_data(self, data):
        if self.current:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            href, title = self.current
            code = Path(href).stem.upper()
            self.links[code] = {"code": code, "name": title.strip(), "url": urljoin(SOURCE_PAGE, href)}
            self.current = None


def fetch_sources(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    html = urlopen(Request(SOURCE_PAGE, headers={"User-Agent": "SGU thesis research demo/1.0"}), timeout=30).read().decode("utf-8")
    parser = PdfLinks()
    parser.feed(html)
    if len(parser.links) < 40 or "DCT" not in parser.links or "TKB_MONCHUNG" not in parser.links:
        raise RuntimeError("Trang nguồn đã đổi cấu trúc; không suy đoán liên kết PDF")
    manifest = {"source_page": SOURCE_PAGE, "faculty_page": FACULTY_PAGE,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "files": {}}
    for code, item in sorted(parser.links.items()):
        path = output / f"{code}.pdf"
        if not path.exists():
            payload = urlopen(Request(item["url"], headers={"User-Agent": "SGU thesis research demo/1.0"}), timeout=40).read()
            if not payload.startswith(b"%PDF-"):
                raise RuntimeError(f"Nguồn {item['url']} không phải PDF")
            path.write_bytes(payload)
        else:
            payload = path.read_bytes()
        manifest["files"][code] = {**item, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    (output / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def cell(value):
    return " ".join(str(value or "").replace("\n", " ").split())


def weeks_from_public_pattern(raw):
    """PDF '*' output loses the original week position; use its count only."""
    raw = cell(raw)
    if not raw:
        return None
    if set(raw) == {"*"}:
        return f"1-{len(raw)}" if len(raw) > 1 else "1"
    pattern = raw.replace(" ", "")
    if pattern and set(pattern) <= set("1234567890-"):
        active = [index for index, char in enumerate(pattern, 1) if char != "-"]
        if active:
            return ",".join(map(str, active))
    return None


def parse_specialized_pdf(path: Path, program: str):
    rows = []
    carry = {"course": "", "name": "", "group": "", "lab": ""}
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                if not table or len(table[0]) != 15 or cell(table[0][1]) != "Mã MH":
                    continue
                for source_row in table[1:]:
                    if len(source_row) != 15 or not cell(source_row[0]).isdigit():
                        continue
                    number = int(cell(source_row[0]))
                    if cell(source_row[1]): carry["course"] = cell(source_row[1])
                    if cell(source_row[2]): carry["name"] = cell(source_row[2])
                    if cell(source_row[7]):
                        carry["group"] = cell(source_row[7])
                        carry["lab"] = cell(source_row[8])
                    elif cell(source_row[8]):
                        carry["lab"] = cell(source_row[8])
                    record = {
                        "program": program, "pdf": path.name, "page": page_number, "stt": number,
                        "course": carry["course"], "name": carry["name"], "credits": cell(source_row[3]),
                        "size": cell(source_row[4]), "lecturer": cell(source_row[5]),
                        "employee": cell(source_row[6]), "group": carry["group"], "lab": carry["lab"],
                        "day": cell(source_row[9]), "start": cell(source_row[10]),
                        "duration": cell(source_row[11]), "room": cell(source_row[12]),
                        "class": cell(source_row[13]), "weeks_raw": cell(source_row[14]),
                    }
                    record["weeks_demo"] = weeks_from_public_pattern(record["weeks_raw"])
                    rows.append(record)
    return rows


def parse_common_pdf(path: Path):
    rows = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                if not table or len(table[0]) != 12 or cell(table[0][2]) != "Mã MH":
                    continue
                for source_row in table[1:]:
                    if len(source_row) != 12 or not cell(source_row[2]).isdigit():
                        continue
                    record = {
                        "program": "TKB_MONCHUNG", "pdf": path.name, "page": page_number,
                        "stt": len(rows) + 1, "course": cell(source_row[2]),
                        "name": cell(source_row[5]), "credits": "3",  # No credits column in this PDF.
                        "size": cell(source_row[6]), "lecturer": cell(source_row[1]),
                        "employee": cell(source_row[0]), "group": cell(source_row[3]),
                        "lab": cell(source_row[4]), "day": cell(source_row[7]),
                        "start": cell(source_row[8]), "duration": cell(source_row[9]),
                        "room": cell(source_row[10]),
                        "class": f"SGU_DEMO_CHUNG_{cell(source_row[2])}_{cell(source_row[3])}",
                        "weeks_raw": cell(source_row[11]),
                    }
                    record["weeks_demo"] = weeks_from_public_pattern(record["weeks_raw"])
                    rows.append(record)
    return rows


def usable(row):
    return (row["course"].isdigit() and row["credits"].isdigit() and row["size"].isdigit()
            and 1 <= int(row["size"]) <= 1000
            and row["employee"].isdigit() and row["lecturer"] and row["group"]
            and row["day"].isdigit() and row["start"].isdigit()
            and row["duration"].isdigit() and 2 <= int(row["day"]) <= 7
            and 1 <= int(row["duration"]) <= 5 and row["room"]
            and row["weeks_demo"] is not None)


def demo_class_code(raw):
    """Keep public class codes that fit the system; preserve long text in provenance."""
    if len(raw) <= 30:
        return raw
    return "SGU_DEMO_LOP_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def write_book(path: Path, sheets: dict, rows: dict):
    book = Workbook()
    book.remove(book.active)
    for name, headers in sheets.items():
        sheet = book.create_sheet(name)
        sheet.append(headers)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{sheet.cell(1, len(headers)).coordinate}"
        for col, header in enumerate(headers, 1):
            sheet.column_dimensions[sheet.cell(1, col).column_letter].width = min(33, max(16, len(header) + 2))
        for row in rows[name]:
            sheet.append(row)
            for col, header in enumerate(headers, 1):
                if header.startswith("ma_") or header in ("nhom", "to_th", "ten_lop"):
                    sheet.cell(sheet.max_row, col).number_format = "@"
    book.save(path)


def build(output: Path, programs: list[str], source_dir: Path, *, semester=SEMESTER,
          max_sessions=None, seed=42, raw_rows=None):
    source_manifest = json.loads((source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    selected = [p for p in programs if p in source_manifest["files"]]
    if len(selected) != len(programs):
        raise ValueError("Mã ngành không có trong trang nguồn SGU")
    raw = raw_rows if raw_rows is not None else [row for code in selected for row in (
        parse_common_pdf(source_dir / f"{code}.pdf") if code == "TKB_MONCHUNG"
        else parse_specialized_pdf(source_dir / f"{code}.pdf", code))]
    # Cross-listed major PDFs may be byte-for-byte identical. A physical class
    # must appear only once in the solver's demand workbook.
    seen = set()
    eligible = []
    for row in raw:
        if not usable(row):
            continue
        key = tuple(row[field] for field in ("course", "group", "lab", "day", "start", "duration", "room", "class", "weeks_raw"))
        if key not in seen:
            seen.add(key)
            eligible.append(row)
    if not eligible:
        raise ValueError("Không tìm được buổi có đủ trường công khai để dựng ví dụ")
    if max_sessions is not None:
        # Select faculty coverage before random fill. Prefer distinct source
        # lecturers so that the timetable filter has data for all 15 faculties.
        if max_sessions < len(FACULTIES):
            raise ValueError("max_sessions phải >= số khoa")
        rng = random.Random(seed)
        by_faculty = defaultdict(list)
        for row in eligible:
            by_faculty[faculty_for_row(row)].append(row)
        missing = [FACULTIES[idx] for idx in range(len(FACULTIES)) if not by_faculty[idx]]
        if missing:
            raise ValueError(f"Không có buổi nguồn cho các khoa: {missing}")
        chosen = []
        used_teachers = set()
        for idx in range(len(FACULTIES)):
            choices = by_faculty[idx]
            rng.shuffle(choices)
            representative = next((row for row in choices if row["employee"] not in used_teachers), choices[0])
            chosen.append(representative)
            used_teachers.add(representative["employee"])
        chosen_ids = {id(row) for row in chosen}
        remaining = [row for row in eligible if id(row) not in chosen_ids]
        rng.shuffle(remaining)
        teacher_count = defaultdict(int)
        class_count = defaultdict(int)
        group_count = defaultdict(int)
        for row in chosen:
            teacher_count[row["employee"]] += 1
            class_count[row["class"]] += 1
            group_count[(row["course"], row["group"], row["lab"])] += 1
        teacher_cap = 2 if max_sessions <= 300 else 3 if max_sessions <= 500 else 5
        class_cap = 3 if max_sessions <= 500 else 5
        for row in remaining:
            if len(chosen) >= max_sessions:
                break
            group_key = row["course"], row["group"], row["lab"]
            if (teacher_count[row["employee"]] >= teacher_cap or
                    class_count[row["class"]] >= class_cap or
                    group_count[group_key] >= 2):
                continue
            chosen.append(row)
            teacher_count[row["employee"]] += 1
            class_count[row["class"]] += 1
            group_count[group_key] += 1
        if len(chosen) != max_sessions:
            raise ValueError(f"Chỉ chọn được {len(chosen)}/{max_sessions} buổi với giới hạn tải")
        eligible = chosen
    output.mkdir(parents=True, exist_ok=True)
    rows = {kind: {sheet: [] for sheet in sheets} for kind, sheets in HEADERS.items()}
    c, r, l = rows["courses"], rows["rooms"], rows["lecturers"]
    for index, name in enumerate(FACULTIES, 1):
        c["Khoa"].append((f"SGU_DEMO_K{index:02d}", name))
        c["BoMon"].append((f"SGU_DEMO_B{index:02d}", f"Đơn vị mô phỏng {name}", f"SGU_DEMO_K{index:02d}"))
    if any(code not in PROGRAM_FACULTY and code != "TKB_MONCHUNG" for code in selected):
        c["Khoa"].append(("SGU_DEMO_K00", "Chưa xác định từ nguồn công khai"))
        c["BoMon"].append(("SGU_DEMO_B00", "Bộ môn mô phỏng chưa xác định", "SGU_DEMO_K00"))
    for code in selected:
        if code == "TKB_MONCHUNG":
            continue  # Common subjects are not one degree program.
        faculty_index = PROGRAM_FACULTY.get(code, -1)
        faculty_code = f"SGU_DEMO_K{faculty_index + 1:02d}" if faculty_index >= 0 else "SGU_DEMO_K00"
        name = "Môn chung (chương trình sử dụng chưa xác định)" if code == "TKB_MONCHUNG" else source_manifest["files"][code]["name"]
        c["ChuongTrinh"].append((code, name, faculty_code, DEMO_CYCLE))
    courses = {}
    groups = {}
    teachers = {}
    qualifications = set()
    capacities = defaultdict(int)
    rooms = set()
    source_rows = []
    for row in eligible:
        code = row["course"]
        courses.setdefault(code, row)
        group_key = (code, row["group"], row["lab"])
        groups.setdefault(group_key, row)
        teachers.setdefault(row["employee"], row)
        qualifications.add((row["employee"], code))
        capacities[row["room"]] = max(capacities[row["room"]], int(row["size"]))
        rooms.add(row["room"])
        source_rows.append({"course": code, "group": row["group"], "source_pdf": row["pdf"],
                            "page": row["page"], "stt": row["stt"], "class_printed": row["class"],
                            "weeks_printed": row["weeks_raw"]})
    for code, row in sorted(courses.items()):
        idx = faculty_for_row(row)
        department = f"SGU_DEMO_B{idx + 1:02d}" if idx >= 0 else "SGU_DEMO_B00"
        kind = "CHUNG" if row["program"] == "TKB_MONCHUNG" else "CHUYEN_NGANH"
        c["HocPhan"].append((code, row["name"], int(row["credits"]), department, kind))
    linked = set()
    for row in raw:
        key = (row["course"], row["program"])
        if row["program"] != "TKB_MONCHUNG" and row["course"] in courses and key not in linked:
            linked.add(key)
            c["HocPhanChuongTrinh"].append((row["course"], row["program"], DEMO_CYCLE, "BAT_BUOC"))
    for key, row in sorted(groups.items()):
        c["NhomHocPhan"].append((row["course"], semester, row["group"], row["lab"], int(row["size"]), demo_class_code(row["class"])))
    counters = defaultdict(int)
    for row in eligible:
        key = (row["course"], row["group"], row["lab"])
        counters[key] += 1
        c["BuoiHocYeuCau"].append((row["course"], row["group"], row["lab"], f"SGU_DEMO_{counters[key]:03d}",
                                   int(row["duration"]), row["weeks_demo"], "LyThuyet", "2-7"))
    for room in sorted(rooms):
        building = room.split(".")[0] if "." in room else "SGU_DEMO"
        r["PhongHoc"].append((room, building, f"Cơ sở {building} (tên mô phỏng)", room,
                              capacities[room], "LyThuyet", "SanSang"))
    for employee, row in sorted(teachers.items()):
        idx = faculty_for_row(row)
        faculty = f"SGU_DEMO_K{idx + 1:02d}" if idx >= 0 else "SGU_DEMO_K00"
        department = f"SGU_DEMO_B{idx + 1:02d}" if idx >= 0 else "SGU_DEMO_B00"
        l["GiangVien"].append((employee, row["lecturer"], "", faculty, department, "DangCongTac"))
    l["GiangVienHocPhan"] = sorted(qualifications)
    for kind in HEADERS:
        write_book(output / f"{kind}.xlsx", HEADERS[kind], rows[kind])
    manifest = {
        "dataset": "SGU public timetable derived demo", "semester": semester,
        "public_source_page": SOURCE_PAGE, "faculty_source_page": FACULTY_PAGE,
        "selected_programs": selected, "raw_rows": len(raw), "usable_distinct_sessions": len(eligible),
        "sampling": {"max_sessions": max_sessions, "seed": seed},
        "excluded_or_duplicate_rows": len(raw) - len(eligible),
        "counts": {kind: {sheet: len(items) for sheet, items in book.items()} for kind, book in rows.items()},
        "source_files": {code: source_manifest["files"][code] for code in selected},
        "source_rows": source_rows,
        "assumptions": [
            "Mã khoa SGU_DEMO_* và bộ môn SGU_DEMO_* là mã hệ thống; tên khoa lấy từ danh sách công khai, quan hệ ngành–khoa là suy luận mô phỏng.",
            "Chu kỳ chương trình DEMO-2026, loại học phần CHUYEN_NGANH và loại CTĐT BAT_BUOC chưa được xác minh từ PDF lịch.",
            "PDF môn chung không ghi số tín chỉ hoặc lớp hành chính; bản demo dùng 3 tín chỉ và mã lớp SGU_DEMO_CHUNG_* để hoàn thành mẫu nhập.",
            "Tên lớp công khai dài quá giới hạn 30 ký tự của hệ thống được thay bằng mã SGU_DEMO_LOP_*; văn bản gốc giữ trong source_rows. Dòng có sĩ số trên 1000 bị loại khỏi workbook thử bộ giải.",
            "Sức chứa phòng đặt bằng sĩ số lớn nhất đã công bố tại phòng đó: chỉ là cận dưới suy ra từ lịch, không phải sức chứa được trường xác nhận.",
            "Loại phòng LyThuyet và trạng thái SanSang là giả định; PDF không cung cấp kiểm kê thiết bị/phòng.",
            "Giảng viên–học phần suy từ phân công đã công bố, không phải hồ sơ chuyên môn chính thức. Khoa giảng viên suy từ ngành nguồn.",
            "Một số quan hệ ngành–khoa và học phần chung–khoa là suy luận theo tên công khai nhằm phủ đủ 15 khoa; không phải xác nhận phân công của SGU.",
            "Ngày cho phép 2–7 và việc không có khoảng thời gian bận là giả định để thử bộ giải.",
            "Chuỗi dấu * của PDF chỉ cho biết số vị trí tuần đọc được; bộ nhập mô phỏng tuần 1–N, chưa xác nhận đúng vị trí tuần gốc.",
            "Đây là nhu cầu suy ngược từ lịch đã công bố; kết quả bộ giải là phương án mới, không phải lịch chính thức của SGU.",
        ],
    }
    (output / "provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path("outputs/sgu_public_sources"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/sgu_public_demo"))
    parser.add_argument("--fetch", action="store_true", help="Download official public PDFs from SGU")
    parser.add_argument("--programs", default="DCT", help="Comma-separated major codes; ALL for 43 majors, COMMON for the separate common-subject PDF")
    args = parser.parse_args()
    if args.fetch:
        source_manifest = fetch_sources(args.source_dir)
    else:
        source_manifest = json.loads((args.source_dir / "source_manifest.json").read_text(encoding="utf-8"))
    programs = ([code for code in source_manifest["files"] if code != "TKB_MONCHUNG"]
                if args.programs.upper() == "ALL" else ["TKB_MONCHUNG"] if args.programs.upper() == "COMMON"
                else [x.strip().upper() for x in args.programs.split(",") if x.strip()])
    result = build(args.output_dir, programs, args.source_dir)
    print(json.dumps({k: result[k] for k in ("selected_programs", "raw_rows", "usable_distinct_sessions", "excluded_or_duplicate_rows", "counts")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
