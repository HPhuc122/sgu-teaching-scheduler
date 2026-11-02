"""Public SGU course snapshots with entirely fictional lecturer identities."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from random import Random

from openpyxl import load_workbook

from .auto_schedule import AUTO_SHEETS
from .models import Course, Room
from .schedule_import import parse_weeks

SEMESTERS = ((1, "2027-09-06", "2027-12-26"), (2, "2028-01-03", "2028-04-23"), (3, "2028-05-01", "2028-08-20"))
SPECIALTIES = ("Công nghệ phần mềm", "Khoa học giáo dục", "Giáo dục chính trị", "Giáo dục mầm non",
    "Giáo dục thể chất và quốc phòng", "Giáo dục tiểu học", "Khoa học xã hội và nghệ thuật",
    "Kỹ thuật điện và công nghệ", "Luật học", "Ngôn ngữ và giảng dạy ngoại ngữ", "Quản trị kinh doanh",
    "Khoa học tự nhiên", "Tài chính và kế toán", "Toán ứng dụng", "Văn hóa và du lịch")


def read_pack(folder):
    result = {}
    for kind in ("courses", "rooms", "lecturers"):
        book = load_workbook(Path(folder) / f"{kind}.xlsx", read_only=True, data_only=True)
        result[kind] = {}
        for sheet in book:
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows)
            result[kind][sheet.title] = [{h: "" if v is None else v for h, v in zip(headers, values)} for values in rows]
        book.close()
    return result


def fictional_names(count, excluded=()):
    rng, names, used = Random(20261102), [], set(excluded)
    starters = ("Trần Minh Khôi", "Lê Hoàng Phương Thảo", "Phạm Ngọc Quỳnh Anh", "Đặng Quốc Huy", "Võ Thùy Dương")
    families = ("Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Đinh", "Trương", "Lâm", "Đoàn", "Tạ")
    middles = (("Minh", "Quốc", "Hoàng", "Đức", "Gia", "Nhật", "Thanh", "Tuấn", "Trọng", "Hữu", "Đình", "Anh"),
               ("Ngọc", "Thùy", "Thanh", "Phương", "Khánh", "Bảo", "Hoàng", "Quỳnh", "Diệu", "Hồng", "Thu", "Minh"))
    endings = (("Khôi", "Huy", "Khang", "Duy", "Lâm", "Phong", "Phúc", "Quân", "Kiên", "Thiện", "Tùng", "Đạt", "Sơn", "Bách", "Vinh", "Trí", "Khải", "Hưng", "Long", "Nam", "Bình", "Dũng", "Thuận", "Tuấn", "Tín"),
               ("Anh", "Linh", "Thảo", "Trâm", "Hương", "Dung", "Ngân", "Châu", "Hà", "Trang", "Mai", "Yến", "Uyên", "Nhi", "Tiên", "Dương", "Tâm", "Hạnh", "Thư", "Nhung", "Quyên", "Chi", "Huyền", "Nga", "Vân"))
    while len(names) < count:
        gender = len(names) % 2
        candidate = starters[len(names)] if len(names) < len(starters) else " ".join((rng.choice(families), rng.choice(middles[gender]), rng.choice(endings[gender])))
        if candidate not in used:
            names.append(candidate)
            used.add(candidate)
        elif len(names) < len(starters):
            # Avoid a coincidental match with a real name in the source snapshot.
            starters = (*starters[:len(names)], " ".join((rng.choice(families), rng.choice(middles[gender]), rng.choice(endings[gender]))), *starters[len(names)+1:])
    return names


def build_realistic_packs(source_root, *, preserve_catalog=False):
    sources = [read_pack(Path(source_root) / f"bo_{i:02d}") for i in (1, 2, 3)]
    teachers, canonical_courses, canonical_rooms = {}, {}, {}
    real_names = set()
    for source in sources:
        for r in source["lecturers"]["GiangVien"]:
            teachers.setdefault(r["ma_vien_chuc"], r)
            real_names.add(r["ho_ten"])
        for r in source["courses"]["HocPhan"]:
            canonical_courses.setdefault(r["ma_mon_hoc"], dict(r))
        for r in source["rooms"]["PhongHoc"]:
            old = canonical_rooms.setdefault(r["ma_phong"], dict(r))
            old["suc_chua"] = max(int(old["suc_chua"]), int(r["suc_chua"]))
    if preserve_catalog:
        for c in Course.objects.select_related("department").filter(code__in=canonical_courses):
            canonical_courses[c.code].update(ten_mon_hoc=c.name, so_tin_chi=c.credits,
                ma_bo_mon_phu_trach=c.department.code, loai_mon=c.kind)
        for r in Room.objects.select_related("building").filter(code__in=canonical_rooms):
            canonical_rooms[r.code].update(ma_toa_nha=r.building.code, ten_toa_nha=r.building.name,
                ten_phong=r.name, suc_chua=r.capacity, loai_phong=r.room_type, trang_thai=r.status)
    codes = sorted(teachers)
    names = fictional_names(len(codes) + 30, real_names)
    profiles = {}
    for index, old_code in enumerate(codes):
        r = teachers[old_code]
        faculty = int(r["ma_khoa"].rsplit("K", 1)[1])
        external = index % 13 == 7
        profiles[old_code] = dict(ma_vien_chuc=f"MPGV{index+1:04d}", ho_ten=names[index], email="",
            ma_khoa=r["ma_khoa"], ma_bo_mon=r["ma_bo_mon"], trang_thai="DangCongTac",
            nguon_giang_vien="THINH_GIANG" if external else "CO_HUU", chuyen_nganh=SPECIALTIES[faculty-1],
            hoc_vi_chuc_danh="TS" if index % 4 == 0 else "ThS", don_vi_cong_tac="Trung tâm Nghiên cứu và Đào tạo Ứng dụng" if external else "Trường Đại học Sài Gòn")
    # One fictional full-time coordinator and one external lecturer per faculty
    # guarantee enough examples for each of the five forms in every semester.
    extras = {}
    for faculty in range(1, 16):
        for kind in (0, 1):
            index = len(codes) + (faculty-1)*2 + kind
            extras[(faculty, kind)] = dict(ma_vien_chuc=f"MPGV{index+1:04d}", ho_ten=names[index], email="",
                ma_khoa=f"SGU_DEMO_K{faculty:02d}", ma_bo_mon=f"SGU_DEMO_B{faculty:02d}", trang_thai="DangCongTac",
                nguon_giang_vien="CO_HUU" if kind == 0 else "THINH_GIANG", chuyen_nganh=SPECIALTIES[faculty-1],
                hoc_vi_chuc_danh="TS" if faculty % 3 == 0 else "ThS",
                don_vi_cong_tac="Trường Đại học Sài Gòn" if kind == 0 else "Viện Nghiên cứu và Phát triển Giáo dục Ứng dụng")
    packs = []
    for source, (number, start, end) in zip(sources, SEMESTERS):
        semester_name = f"Học kỳ {number} - Năm học 2027 - 2028"
        rows = {kind: {s: [] for s in sheets} for kind, sheets in AUTO_SHEETS.items()}
        c, t, rooms = rows["courses"], rows["lecturers"], rows["rooms"]
        for sheet in ("Khoa", "BoMon", "ChuongTrinh", "HocPhanChuongTrinh"):
            c[sheet] = [dict(r) for r in source["courses"][sheet]]
        faculty_names = {r["ma_khoa"]: r["ten_khoa"] for r in c["Khoa"]}
        for r in c["BoMon"]:
            r["ten_bo_mon"] = "Đơn vị phụ trách " + faculty_names[r["ma_khoa"]]
        c["HocPhan"] = [dict(canonical_courses[r["ma_mon_hoc"]]) for r in source["courses"]["HocPhan"]]
        course_map = {r["ma_mon_hoc"]: r for r in c["HocPhan"]}
        c["NhomHocPhan"] = [dict(r, hoc_ky=semester_name) for r in source["courses"]["NhomHocPhan"]]
        present = {r["ma_vien_chuc"] for r in source["lecturers"]["GiangVien"]}
        t["GiangVien"] = [dict(profiles[code]) for code in sorted(present)] + [dict(r) for r in extras.values()]
        t["GiangVienHocPhan"] = [dict(ma_vien_chuc=profiles[r["ma_vien_chuc"]]["ma_vien_chuc"], ma_mon_hoc=r["ma_mon_hoc"]) for r in source["lecturers"]["GiangVienHocPhan"]]
        candidates = defaultdict(list)
        for r in t["GiangVienHocPhan"]:
            candidates[r["ma_mon_hoc"]].append(r["ma_vien_chuc"])
        for course in c["HocPhan"]:
            faculty = int(course["ma_bo_mon_phu_trach"].rsplit("B", 1)[1])
            for person in (extras[(faculty, 0)], extras[(faculty, 1)], extras[(faculty % 15 + 1, 0)]):
                t["GiangVienHocPhan"].append(dict(ma_vien_chuc=person["ma_vien_chuc"], ma_mon_hoc=course["ma_mon_hoc"]))
        hours, class_owners, seen_faculties = defaultdict(Counter), defaultdict(Counter), Counter()
        for i, old in enumerate(source["courses"]["BuoiHocYeuCau"]):
            r = dict(old)
            faculty = int(course_map[r["ma_mon_hoc"]]["ma_bo_mon_phu_trach"].rsplit("B", 1)[1])
            component = "TH" if r["to_th"] else "LT"
            r["ma_buoi"] = "BUOI_" + str(old["ma_buoi"].rsplit("_", 1)[-1])
            r["loai_buoi"] = component
            duration = int(r["so_tiet"]) * len(parse_weeks(str(r["tuan_hoc"])))
            hours[(r["ma_mon_hoc"], r["nhom"], r["to_th"])][component] += duration
            assigned = candidates[r["ma_mon_hoc"]][i % len(candidates[r["ma_mon_hoc"]])]
            occurrence = seen_faculties[faculty]
            if occurrence < 3:
                # Cơ hữu, internal invitation, external appointment per faculty.
                person = extras[(faculty, 0)] if occurrence == 0 else extras[(faculty % 15 + 1, 0)] if occurrence == 1 else extras[(faculty, 1)]
                assigned = person["ma_vien_chuc"]
            r["ma_vien_chuc_phan_cong"] = assigned if occurrence < 3 or i % 10 else ""
            r["so_tiet_thuc_te"] = duration
            seen_faculties[faculty] += 1
            c["BuoiHocYeuCau"].append(r)
        group_rows = {(r["ma_mon_hoc"], r["nhom"], r["to_th"]): r for r in c["NhomHocPhan"]}
        program_faculties = {r["ma_nganh_ctdt"]: r["ma_khoa"].replace("_K", "_B") for r in c["ChuongTrinh"]}
        for key, group in group_rows.items():
            department = course_map[key[0]]["ma_bo_mon_phu_trach"]
            for class_name in str(group["ten_lop"]).split(";"):
                if class_name:
                    class_owners[class_name][department] += 1
            c["KeHoachMoNhom"].append(dict(ma_mon_hoc=key[0], nhom=key[1], to_th=key[2], hoc_ky_so=number,
                khoa="Khóa " + ("20" + str(group["ten_lop"])[4:6] if str(group["ten_lop"]).startswith("D") and str(group["ten_lop"])[4:6].isdigit() else "2026"),
                so_tiet_lt=hours[key]["LT"], so_tiet_bt=0, so_tiet_th=hours[key]["TH"], he_so_hp=1, ghi_chu=""))
        for class_name, department_counts in sorted(class_owners.items()):
            department = program_faculties.get(class_name[:3], department_counts.most_common(1)[0][0])
            c["LopHanhChinh"].append(dict(ten_lop=class_name, ma_bo_mon_quan_ly=department))
        for old in source["rooms"]["PhongHoc"]:
            r = dict(canonical_rooms[old["ma_phong"]])
            r["ten_phong"] = "Phòng " + r["ma_phong"]
            r["ten_toa_nha"] = str(r["ten_toa_nha"]).replace(" (tên mô phỏng)", "")
            rooms["PhongHoc"].append(r)
        by_faculty = defaultdict(list)
        for cls in c["LopHanhChinh"]:
            by_faculty[int(cls["ma_bo_mon_quan_ly"].rsplit("B", 1)[1])].append(cls["ten_lop"])
        for faculty in range(1, 16):
            core = extras[(faculty, 0)]
            classes = by_faculty[faculty]
            label = classes[0] if classes else "sinh viên năm thứ nhất"
            t["CongTacKhac"].extend((dict(ma_vien_chuc=core["ma_vien_chuc"], ma_cong_tac="CVHT", noi_dung=f"Cố vấn học tập {label}", loai="KHAC", so_tiet=20),
                dict(ma_vien_chuc=core["ma_vien_chuc"], ma_cong_tac="HDCLB", noi_dung="Hướng dẫn câu lạc bộ học thuật của khoa", loai="KHAC", so_tiet=10)))
            if classes:
                activity_date = date.fromisoformat(start) + timedelta(days=5)
                c["HoatDongNgoaiTruong"].append(dict(ma_hoat_dong=f"HD{number}{faculty:02d}", ten_lop=classes[0], khoa="Khóa 2026",
                    trinh_do="ĐH", noi_dung="Tham quan, khảo sát thực tế chuyên ngành", dia_diem="Cơ sở thực hành và đơn vị liên kết đào tạo",
                    tu_ngay=activity_date.isoformat(), den_ngay=activity_date.isoformat(), so_sinh_vien=35, hoc_ky_so=number))
        serializable = {kind: {sheet: [tuple(row.get(h, "") for h in headers) for row in rows[kind][sheet]] for sheet, headers in sheets.items()} for kind, sheets in AUTO_SHEETS.items()}
        source_files = {kind: str(Path(source_root) / f"bo_{number:02d}" / f"{kind}.xlsx") for kind in rows}
        provenance = dict(source_files={k: {"path": path, "sha256": sha256(Path(path).read_bytes()).hexdigest()} for k, path in source_files.items()},
            lecturer_identity="All lecturer names, identifiers, titles, employment categories and appointments are fictional. No personal data copied from internal photographs.",
            academic_period="HK1 public 2026-2027 snapshot adapted as three simulated semesters of 2027-2028; not official HK2/HK3 data.",
            simulated_attributes=["lecture/practical classification from group structure", "class ownership mapping", "planned hours and coefficient 1", "reported hours", "other duties", "off-campus activities", "lecturer qualifications and availability"],
            preserve_existing_catalog=preserve_catalog)
        packs.append((number, start, end, semester_name, serializable, provenance))
    return packs
