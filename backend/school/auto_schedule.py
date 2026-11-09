"""Import three proposed Excel workbooks and build a real-resource CP-SAT timetable."""

from collections import defaultdict
from contextlib import contextmanager
from io import BytesIO
from random import Random
from time import monotonic
from math import isfinite

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from ortools.sat.python import cp_model

from .catalog_import import SHEETS, commit_catalog, validate_catalog
from .auto_schedule_errors import InputIssues, issue
from .search_budget import (SearchBudgetExpired, check_deadline, cp_budget,
                            estimate_cp_build, load_cp_observations)
from .solution_audit import audit_solution
from .soft_score import SoftScorer, evening_penalty, preference_penalty
from .quality_search import search_quality
from .schedule_diagnostics import diagnose, forced_day_overloads
from .models import (AlgorithmRun, CourseGroup, Department, Faculty, Lecturer,
                     LecturerPreference, Period, Room, ScheduleEntry, ScheduleWeek, Semester, TeachingQualification)
from .preference_checks import day_off_error, day_off_violations
from .schedule_import import parse_weeks
from .planning import (PLAN_SHEETS, DUTY_SHEETS, LECTURER_FIELDS, validate_plan_inputs,
                       persist_plan, activity_blocks, update_selected_assignments)


AUTO_SHEETS = {
    "courses": {
        "Khoa": ("ma_khoa", "ten_khoa"),
        "BoMon": ("ma_bo_mon", "ten_bo_mon", "ma_khoa"),
        **SHEETS["courses"],
        "BuoiHocYeuCau": ("ma_mon_hoc", "nhom", "to_th", "ma_buoi", "so_tiet",
                           "tuan_hoc", "loai_phong", "thu_duoc_xep",
                           "ma_vien_chuc_phan_cong", "loai_buoi", "so_tiet_thuc_te"),
        **PLAN_SHEETS,
    },
    "rooms": {
        **SHEETS["rooms"],
        "PhongKhongKhaDung": ("ma_phong", "thu", "tiet_bat_dau", "so_tiet", "tuan_hoc"),
    },
    "lecturers": {
        **SHEETS["lecturers"],
        "GiangVien": (*SHEETS["lecturers"]["GiangVien"], *LECTURER_FIELDS),
        "GiangVienKhongKhaDung": ("ma_vien_chuc", "thu", "tiet_bat_dau", "so_tiet", "tuan_hoc"),
        **DUTY_SHEETS,
    },
}
MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 6000
LARGE_RUN_SESSIONS = 500
ROOM_TYPES = {"LyThuyet", "MayTinh", "ThiNghiem", "HoiTruong"}


def template_bytes(kind):
    book = Workbook()
    book.remove(book.active)
    for name, headers in AUTO_SHEETS[kind].items():
        sheet = book.create_sheet(name)
        sheet.append(headers)
        sheet.freeze_panes = "A2"
        for index, header in enumerate(headers, 1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = max(18, len(header) + 2)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def read_auto_workbook(upload, kind):
    if upload is None or not upload.name.lower().endswith(".xlsx") or upload.size > MAX_BYTES:
        raise InputIssues([issue(kind, "", None,
                                 f"Phải là .xlsx và không quá {MAX_BYTES // 1024 // 1024} MB")])
    try:
        book = load_workbook(upload, read_only=True, data_only=True)
        problems = []
        expected = set(AUTO_SHEETS[kind])
        optional_sheets = set(PLAN_SHEETS) | set(DUTY_SHEETS)
        for name in sorted(expected - set(book.sheetnames) - optional_sheets):
            problems.append(issue(kind, name, None, "Thiếu sheet theo mẫu"))
        for name in sorted(set(book.sheetnames) - expected):
            problems.append(issue(kind, name, None, "Sheet không có trong mẫu"))
        result = {}
        count = 0
        limit_reported = False
        for name, headers in AUTO_SHEETS[kind].items():
            if name not in book.sheetnames:
                result[name] = []
                continue
            rows = book[name].iter_rows(values_only=True)
            heading = next(rows, None)
            actual_headers = tuple(str(value or "").strip() for value in heading or ())
            row_headers = headers
            # Accept existing workbooks created before the optional assigned-teacher
            # column was introduced. Newly downloaded templates include the column.
            minimum = 8 if name == "BuoiHocYeuCau" else 6 if name == "GiangVien" else len(headers)
            if minimum <= len(actual_headers) <= len(headers) and actual_headers == headers[:len(actual_headers)]:
                row_headers = actual_headers
            if heading is None or actual_headers != row_headers:
                problems.append(issue(kind, name, 1, "Tiêu đề cột không khớp mẫu"))
                continue
            result[name] = []
            for line, values in enumerate(rows, 2):
                if line > MAX_ROWS + 100:
                    problems.append(issue(kind, name, line, "Sheet có quá nhiều dòng"))
                    break
                if all(value is None or str(value).strip() == "" for value in values):
                    continue
                count += 1
                if count > MAX_ROWS and not limit_reported:
                    problems.append(issue(kind, name, line,
                                          f"File vượt {MAX_ROWS} dòng dữ liệu"))
                    limit_reported = True
                if any(value not in (None, "") for value in values[len(row_headers):]):
                    problems.append(issue(kind, name, line, "Dữ liệu ngoài cột mẫu"))
                padded = list(values[:len(row_headers)]) + [None] * max(0, len(row_headers) - len(values))
                normalized = {key: "" if value is None else str(value).strip()
                              for key, value in zip(row_headers, padded)}
                for header in headers:
                    normalized.setdefault(header, "")
                for key, value in zip(row_headers, padded):
                    if (key.startswith("ma_") or key in ("nhom", "to_th")) and isinstance(value, (int, float)):
                        problems.append(issue(kind, name, line, f"{key} phải là ô văn bản"))
                result[name].append({"line": line, **normalized})
        if problems:
            raise InputIssues(problems)
        return result
    except InputIssues:
        raise
    except Exception as exc:
        raise InputIssues([issue(kind, "", None, "Không đọc được file Excel hợp lệ")]) from exc
    finally:
        if "book" in locals():
            book.close()


def read_auto_files(files):
    data = {}
    problems = []
    for kind in AUTO_SHEETS:
        try:
            data[kind] = read_auto_workbook(files.get(kind), kind)
        except InputIssues as exc:
            problems.extend(exc.issues)
    if problems:
        raise InputIssues(problems)
    return data


def _base(data, kind):
    return {name: data[name] for name in SHEETS[kind]}


def _int(value, label, minimum=1, maximum=53):
    if not value.isdigit() or not minimum <= int(value) <= maximum:
        raise ValueError(f"{label} phải từ {minimum} đến {maximum}")
    return int(value)


def _week_set(value, semester):
    weeks = parse_weeks(value)
    if weeks[-1] > semester.week_count:
        raise ValueError("Tuần học vượt giới hạn học kỳ")
    return frozenset(weeks)


def _days(value):
    if not value:
        return frozenset(range(2, 8))
    days = set()
    for part in value.replace(";", ",").split(","):
        pieces = part.strip().split("-")
        if len(pieces) > 2 or any(not p.isdigit() for p in pieces):
            raise ValueError("thu_duoc_xep phải có dạng 2-6,7")
        start, end = int(pieces[0]), int(pieces[-1])
        if start < 2 or end > 8 or end < start:
            raise ValueError("Thứ được xếp phải trong khoảng 2-8")
        days.update(range(start, end + 1))
    return frozenset(days)


def _blocks(data, sheet, key, semester, kind, problems):
    blocks = []
    for row in data[sheet]:
        try:
            code = row[key]
            if not code:
                raise ValueError(f"Thiếu {key}")
            day = _int(row["thu"], "Thứ", 2, 8)
            start = _int(row["tiet_bat_dau"], "Tiết bắt đầu", 1, 13)
            count = _int(row["so_tiet"], "Số tiết", 1, 13)
            if start + count > 14:
                raise ValueError("Buổi vượt tiết 13")
            blocks.append((code, day, start, count, _week_set(row["tuan_hoc"], semester)))
        except ValueError as exc:
            problems.append(issue(kind, sheet, row["line"], exc))
    return blocks


def _prepare_inputs(semester, data):
    courses, rooms, lecturers = data["courses"], data["rooms"], data["lecturers"]
    problems = []
    if not courses["BuoiHocYeuCau"]:
        problems.append(issue("courses", "BuoiHocYeuCau", None, "Cần ít nhất một buổi học yêu cầu"))
    faculties = {row["ma_khoa"]: row for row in courses["Khoa"]}
    seen_faculties = set()
    for row in courses["Khoa"]:
        if row["ma_khoa"] in seen_faculties:
            problems.append(issue("courses", "Khoa", row["line"], "Mã khoa bị lặp"))
        seen_faculties.add(row["ma_khoa"])
        if not row["ma_khoa"] or not row["ten_khoa"]:
            problems.append(issue("courses", "Khoa", row["line"], "Thiếu mã hoặc tên"))
        if len(row["ma_khoa"]) > 20 or len(row["ten_khoa"]) > 200:
            problems.append(issue("courses", "Khoa", row["line"], "Mã hoặc tên quá dài"))
    seen_departments = set()
    for row in courses["BoMon"]:
        if row["ma_bo_mon"] in seen_departments:
            problems.append(issue("courses", "BoMon", row["line"], "Mã bộ môn bị lặp"))
        seen_departments.add(row["ma_bo_mon"])
        if not row["ma_bo_mon"] or not row["ten_bo_mon"] or row["ma_khoa"] not in faculties:
            problems.append(issue("courses", "BoMon", row["line"], "Bộ môn hoặc khoa không hợp lệ"))
        if len(row["ma_bo_mon"]) > 30 or len(row["ten_bo_mon"]) > 200:
            problems.append(issue("courses", "BoMon", row["line"], "Mã hoặc tên quá dài"))
    demands = []
    keys = set()
    lecturer_rows = {row["ma_vien_chuc"]: row for row in lecturers["GiangVien"]}
    qualified_pairs = {(row["ma_vien_chuc"], row["ma_mon_hoc"])
                       for row in lecturers["GiangVienHocPhan"]}
    group_keys = {(row["ma_mon_hoc"], row["nhom"], row["to_th"]) for row in courses["NhomHocPhan"]}
    requested_keys = set()
    for row in courses["BuoiHocYeuCau"]:
        try:
            group_key = row["ma_mon_hoc"], row["nhom"], row["to_th"]
            requested_keys.add(group_key)
            if group_key not in group_keys:
                raise ValueError("Môn/nhóm/tổ TH không có trong NhomHocPhan")
            if not row["ma_buoi"]:
                raise ValueError("Thiếu ma_buoi")
            if len(row["ma_buoi"]) > 50:
                raise ValueError("ma_buoi dài quá 50 ký tự")
            key = (*group_key, row["ma_buoi"])
            if key in keys:
                raise ValueError("Mã buổi bị lặp trong nhóm")
            keys.add(key)
            count = _int(row["so_tiet"], "Số tiết", 1, 13)
            room_type = row["loai_phong"]
            if room_type and room_type not in ROOM_TYPES:
                raise ValueError("Loại phòng không hỗ trợ")
            assigned_code = row.get("ma_vien_chuc_phan_cong", "")
            component = row.get("loai_buoi", "")
            if component and component not in ("LT", "BT", "TH"):
                raise ValueError("loai_buoi phải là LT, BT hoặc TH")
            if assigned_code:
                teacher_row = lecturer_rows.get(assigned_code)
                if teacher_row is None:
                    raise ValueError("Mã giảng viên phân công chưa có trong file Giảng viên")
                if teacher_row["trang_thai"] != "DangCongTac":
                    raise ValueError("Giảng viên phân công không ở trạng thái đang công tác")
                if (assigned_code, row["ma_mon_hoc"]) not in qualified_pairs:
                    raise ValueError("Giảng viên phân công chưa được khai báo chuyên môn cho học phần")
            demands.append({"key": group_key, "code": row["ma_buoi"], "line": row["line"], "count": count,
                            "weeks": _week_set(row["tuan_hoc"], semester),
                            "room_type": room_type, "days": _days(row["thu_duoc_xep"]),
                            "assigned_teacher_code": assigned_code, "component": component})
        except ValueError as exc:
            problems.append(issue("courses", "BuoiHocYeuCau", row["line"], exc))
    for row in courses["NhomHocPhan"]:
        key = row["ma_mon_hoc"], row["nhom"], row["to_th"]
        if key not in requested_keys:
            problems.append(issue("courses", "NhomHocPhan", row["line"],
                                  "Nhóm chưa có buổi học yêu cầu"))
    room_blocks = _blocks(rooms, "PhongKhongKhaDung", "ma_phong", semester,
                          "rooms", problems)
    teacher_blocks = _blocks(lecturers, "GiangVienKhongKhaDung", "ma_vien_chuc",
                             semester, "lecturers", problems)
    room_codes = {row["ma_phong"] for row in rooms["PhongHoc"]}
    teacher_codes = {row["ma_vien_chuc"] for row in lecturers["GiangVien"]}
    for row in rooms["PhongKhongKhaDung"]:
        if row["ma_phong"] and row["ma_phong"] not in room_codes:
            problems.append(issue("rooms", "PhongKhongKhaDung", row["line"],
                                  "Mã phòng không có trong PhongHoc"))
    for row in lecturers["GiangVienKhongKhaDung"]:
        if row["ma_vien_chuc"] and row["ma_vien_chuc"] not in teacher_codes:
            problems.append(issue("lecturers", "GiangVienKhongKhaDung", row["line"],
                                  "Mã viên chức không có trong GiangVien"))
    if problems:
        raise InputIssues(problems)
    return demands, room_blocks, teacher_blocks


def _create_catalog(semester, data, demand_rows, room_blocks, teacher_blocks):
    courses, rooms, lecturers = data["courses"], data["rooms"], data["lecturers"]
    problems = []
    for row in courses["Khoa"]:
        Faculty.objects.update_or_create(code=row["ma_khoa"], defaults={"name": row["ten_khoa"]})
    for row in courses["BoMon"]:
        matches = list(Department.objects.filter(code=row["ma_bo_mon"])[:2])
        if len(matches) > 1:
            problems.append(issue("courses", "BoMon", row["line"], "Mã bộ môn bị lặp trong hệ thống"))
            continue
        old = matches[0] if matches else None
        faculty = Faculty.objects.get(code=row["ma_khoa"])
        if old and old.faculty_id != faculty.pk:
            problems.append(issue("courses", "BoMon", row["line"], "Bộ môn đã thuộc khoa khác"))
            continue
        Department.objects.update_or_create(code=row["ma_bo_mon"], defaults={
            "name": row["ten_bo_mon"], "faculty": faculty,
        })
    if problems:
        raise InputIssues(problems)
    course_errors = validate_catalog("courses", _base(courses, "courses"), semester)
    room_errors = validate_catalog("rooms", _base(rooms, "rooms"))
    lecturer_errors = validate_catalog(
        "lecturers", _base(lecturers, "lecturers"),
        available_course_codes={row["ma_mon_hoc"] for row in courses["HocPhan"]},
    )
    for kind, errors in (("courses", course_errors), ("rooms", room_errors),
                         ("lecturers", lecturer_errors)):
        problems.extend(issue(kind, item.get("sheet"), item.get("line"), item["message"])
                        for item in errors)
    if problems:
        raise InputIssues(problems)
    commit_catalog("courses", _base(courses, "courses"), semester)
    commit_catalog("rooms", _base(rooms, "rooms"))
    commit_catalog("lecturers", _base(lecturers, "lecturers"))

    group_map = {(g.course.code, g.group, g.lab_group or ""): g for g in
                 CourseGroup.objects.filter(semester=semester).select_related("course")
                 .prefetch_related("cohort_links")}
    room_codes = {row["ma_phong"] for row in rooms["PhongHoc"]}
    teacher_codes = {row["ma_vien_chuc"] for row in lecturers["GiangVien"]}
    room_map = {r.code: r for r in Room.objects.filter(code__in=room_codes).order_by("code")}
    teacher_map = {t.employee_code: t for t in Lecturer.objects.filter(
        employee_code__in=teacher_codes).order_by("employee_code")}
    for code, *_ in room_blocks:
        if code not in room_map:
            raise ValueError(f"Phòng không khả dụng {code} chưa có trong file")
    for code, *_ in teacher_blocks:
        if code not in teacher_map:
            raise ValueError(f"Giảng viên không khả dụng {code} chưa có trong file")
    prepared_demands = []
    for row in demand_rows:
        teacher = teacher_map.get(row["assigned_teacher_code"]) if row["assigned_teacher_code"] else None
        if row["assigned_teacher_code"] and teacher is None:
            raise InputIssues([issue("courses", "BuoiHocYeuCau", row["line"],
                                      "Giảng viên phân công chưa có trong danh mục đã nhập")])
        prepared_demands.append(dict(row, group=group_map[row["key"]], assigned_teacher=teacher))
    return prepared_demands, room_map, teacher_map


def _add_fixed(buckets, key, day, start, count, weeks, model, label):
    interval = model.NewIntervalVar(start, count, start + count, label)
    for week in weeks:
        buckets[(key, day, week)].append(interval)


def _overlap(a_start, a_count, b_start, b_count):
    return a_start < b_start + b_count and b_start < a_start + a_count


def _greedy_seed(demands, choices, previous, room_unavailable, teacher_unavailable,
                 *, attempts=8, seed=42, deadline=None):
    """Find a valid complete assignment to hint CP-SAT and cover timeouts."""
    check_deadline(deadline)
    fixed = set()

    def keys(kind, resource_id, day, start, count, weeks):
        return ((kind, resource_id, day, week, period)
                for week in weeks for period in range(start, start + count))

    for entry in previous:
        check_deadline(deadline)
        weeks = [item.week for item in entry.schedule_weeks.all()]
        resources = [("group", entry.group_id), ("room", entry.room_id),
                     ("teacher", entry.lecturer_id)]
        resources += [("cohort", link.cohort_id) for link in entry.group.cohort_links.all()]
        for kind, resource_id in resources:
            if resource_id is not None:
                fixed.update(keys(kind, resource_id, entry.day, entry.start_period_id,
                                  entry.period_count, weeks))

    rng = Random(seed)
    order = list(range(len(demands)))
    order.sort(key=lambda index: (len(choices[index][0]) * len(choices[index][2]) * len(choices[index][4]),
                                  -demands[index]["count"], rng.random()))
    cohorts = [{link.cohort_id for link in demand["group"].cohort_links.all()}
               for demand in demands]
    for _ in range(attempts):
        check_deadline(deadline)
        occupied = set(fixed)
        selected = {}
        for index in order:
            check_deadline(deadline)
            demand = demands[index]
            group = demand["group"]
            count, weeks = demand["count"], demand["weeks"]
            time_options, _, rooms, _, teachers, _ = choices[index]
            time_indices = list(range(len(time_options)))
            rng.shuffle(time_indices)
            found = False
            for time_index in time_indices:
                check_deadline(deadline)
                day, start, _ = time_options[time_index]
                group_keys = list(keys("group", group.pk, day, start, count, weeks))
                for cohort_id in cohorts[index]:
                    group_keys.extend(keys("cohort", cohort_id, day, start, count, weeks))
                if any(key in occupied for key in group_keys):
                    continue
                room_indices = list(range(len(rooms)))
                teacher_indices = list(range(len(teachers)))
                rng.shuffle(room_indices)
                rng.shuffle(teacher_indices)
                for room_index in room_indices:
                    check_deadline(deadline)
                    room = rooms[room_index]
                    if (any(_overlap(start, count, busy_start, busy_count)
                            for week in weeks for busy_start, busy_count
                            in room_unavailable[(room.pk, day, week)]) or
                            any(key in occupied for key in keys("room", room.pk, day, start, count, weeks))):
                        continue
                    for teacher_index in teacher_indices:
                        check_deadline(deadline)
                        teacher = teachers[teacher_index].lecturer
                        if (any(_overlap(start, count, busy_start, busy_count)
                                for week in weeks for busy_start, busy_count
                                in teacher_unavailable[(teacher.pk, day, week)]) or
                                any(key in occupied for key in keys("teacher", teacher.pk, day, start, count, weeks))):
                            continue
                        occupied.update(group_keys)
                        occupied.update(keys("room", room.pk, day, start, count, weeks))
                        occupied.update(keys("teacher", teacher.pk, day, start, count, weeks))
                        selected[index] = (time_index, room_index, teacher_index)
                        found = True
                        break
                    if found:
                        break
                if found:
                    break
            if not found:
                break
        if len(selected) == len(demands):
            return selected
        rng.shuffle(order)
    return None


def _prepare_choices(demands, room_map, qualification, periods, deadline):
    """Prepare identical domains for both Greedy and CP-SAT before building variables."""
    choices = []
    problems = []
    available_rooms = [room for room in room_map.values() if room.status == "SanSang"]
    for demand in demands:
        check_deadline(deadline)
        group = demand["group"]
        count = demand["count"]
        times = [(day, start, periods[start].block) for day in demand["days"]
                 for start in sorted(periods)
                 if not any((day, week) in demand.get("activity_blocks", set()) for week in demand["weeks"])
                 and all(number in periods and periods[number].block == periods[start].block
                        for number in range(start, start + count))]
        rooms = [room for room in available_rooms if room.capacity >= group.capacity
                 and (not demand["room_type"] or room.room_type == demand["room_type"])]
        teachers = qualification[group.course_id]
        if demand.get("assigned_teacher") is not None:
            teachers = [item for item in teachers
                        if item.lecturer_id == demand["assigned_teacher"].pk]
        if not times or not rooms or not teachers:
            reasons = []
            if not times:
                reasons.append("không có khung tiết phù hợp")
            if not rooms:
                reasons.append("không có phòng phù hợp")
            if not teachers:
                reasons.append("giảng viên được chỉ định không có trong danh sách đủ chuyên môn"
                               if demand.get("assigned_teacher") is not None
                               else "không có giảng viên đủ chuyên môn")
            problems.append(issue("courses", "BuoiHocYeuCau", demand["line"],
                                  "; ".join(reasons)))
        choices.append((times, None, rooms, None, teachers, None))
    if problems:
        raise InputIssues(problems)
    return choices


def _selected_result(demands, choices, selected):
    result = []
    for index, demand in enumerate(demands):
        time_index, room_index, teacher_index = selected[index]
        times, _, rooms, _, teachers, _ = choices[index]
        day, start, _ = times[time_index]
        result.append((demand, day, start, rooms[room_index], teachers[teacher_index].lecturer))
    return result


def solve(semester, demands, room_map, teacher_map, room_blocks, teacher_blocks,
          allowed_pairs, *, preferences=None, seed=42, deadline=None,
          cp_time_limit=30, use_cp_sat=True, scoring=None, num_search_workers=4,
          generation_policy="greedy_first", telemetry=None,
          cp_policy="budget_aware", cp_observations=None):
    """Keep an audited seed before optional, bounded CP-SAT refinement/rescue.

    ``model_first`` controls the previous ordering and time allocation, using
    the same new validation/selection safeguards. Domains/scoring are shared.
    Stage timers are wall time, exclusive of one another; validation includes
    independent audits and scoring. The return tuple remains backwards compatible.
    """
    if generation_policy not in ("greedy_first", "model_first"):
        raise ValueError("Unknown generation policy")
    if cp_policy not in ("budget_aware", "fixed_window"):
        raise ValueError("Unknown CP admission policy")
    active_cp_policy = "fixed_window" if generation_policy == "model_first" else cp_policy
    refinement_seconds = settings.QUALITY_CP_REFINEMENT_SECONDS
    min_solve_seconds = settings.QUALITY_CP_MIN_SOLVE_SECONDS
    if (not isfinite(refinement_seconds) or not isfinite(min_solve_seconds)
            or min_solve_seconds <= 0 or refinement_seconds < min_solve_seconds
            or not isfinite(cp_time_limit) or cp_time_limit <= 0):
        raise ValueError("Invalid CP-SAT time allocation")
    metrics = telemetry if telemetry is not None else {}
    metrics.update(policy=generation_policy, source="NONE", cp_called=False,
                   cp_status="NOT_CALLED", cp_skip_reason=None, greedy_status="NOT_CALLED",
                   cp_policy=active_cp_policy, cp_decision="NOT_CONSIDERED",
                   sessions=len(demands), cp_model_complete=False,
                   preparation_seconds=0, greedy_seconds=0, cp_model_seconds=0,
                   cp_solve_seconds=0, validation_seconds=0,
                   greedy_score=None, cp_score=None)

    @contextmanager
    def timed(stage):
        started = monotonic()
        try:
            yield
        finally:
            metrics[stage] = round(metrics[stage] + monotonic() - started, 6)

    def validate(result):
        with timed("validation_seconds"):
            audit_solution(semester, demands, result, room_map, teacher_map,
                           room_blocks, teacher_blocks, allowed_pairs, preferences=scoring.preferences)
            return scoring.score(result)

    # Preparation is timed even if validation of the input/domain fails.
    with timed("preparation_seconds"):
        prepared = _prepare_generation(semester, demands, room_map, teacher_map,
                                       room_blocks, teacher_blocks, allowed_pairs,
                                       preferences, scoring, deadline)
    scoring, choices, previous, room_unavailable, teacher_unavailable = prepared
    constructive_only = len(demands) >= LARGE_RUN_SESSIONS or not use_cp_sat
    if constructive_only and forced_day_overloads(semester, demands):
        metrics.update(cp_skip_reason="CONSTRUCTIVE_ONLY", cp_decision="SKIPPED_POLICY")
        return None, "INFEASIBLE", None
    seed_solution, greedy, greedy_score = None, None, None

    def generate_greedy(greedy_deadline):
        nonlocal seed_solution, greedy, greedy_score
        try:
            with timed("greedy_seconds"):
                seed_solution = _greedy_seed(
                    demands, choices, previous, room_unavailable, teacher_unavailable,
                    attempts=12 if constructive_only else 8, seed=seed, deadline=greedy_deadline)
            if seed_solution is None:
                metrics["greedy_status"] = "NO_SOLUTION"
                return
            result = _selected_result(demands, choices, seed_solution)
            greedy_score = validate(result)
            greedy = result
            metrics.update(greedy_status="VALID", greedy_score=greedy_score)
        except SearchBudgetExpired:
            metrics["greedy_status"] = "TIMEOUT"
        except (ValueError, KeyError) as exc:
            seed_solution = None
            metrics.update(greedy_status="AUDIT_REJECTED", greedy_error=str(exc))

    def fallback(reason):
        metrics["cp_skip_reason"] = reason
        metrics["source"] = "GREEDY" if greedy is not None else "NONE"
        return greedy, "HEURISTIC" if greedy is not None else "UNKNOWN", greedy_score

    if generation_policy == "greedy_first" or constructive_only:
        greedy_deadline = deadline
        if not constructive_only and deadline is not None:
            # A failed constructive search must leave time for CP-SAT rescue.
            now = monotonic()
            greedy_deadline = min(deadline, now + max(0, deadline - now) * 0.25)
        metrics["greedy_budget_seconds"] = max(0, greedy_deadline - monotonic()) if greedy_deadline is not None else None
        generate_greedy(greedy_deadline)
    if constructive_only:
        metrics["cp_decision"] = "SKIPPED_POLICY"
        return fallback("LARGE_INSTANCE" if len(demands) >= LARGE_RUN_SESSIONS else "LATER_START")
    if generation_policy == "greedy_first" and greedy_score == 0:
        metrics["cp_decision"] = "SKIPPED_ZERO_PENALTY"
        return fallback("ZERO_SOFT_PENALTY")

    cp_deadline = deadline
    build_deadline = deadline
    if active_cp_policy == "budget_aware":
        observations = (load_cp_observations(settings.QUALITY_CP_BUILD_PROFILE)
                        if cp_observations is None else cp_observations)
        estimate = estimate_cp_build(
            len(demands), observations,
            seconds_per_session=settings.QUALITY_CP_MODEL_SECONDS_PER_SESSION,
            safety_factor=settings.QUALITY_CP_ESTIMATE_SAFETY_FACTOR)
        decision = cp_budget(
            monotonic(), deadline, has_seed=greedy is not None, estimate=estimate,
            refinement_seconds=refinement_seconds, min_solve_seconds=min_solve_seconds,
            audit_reserve=settings.QUALITY_AUDIT_RESERVE_SECONDS, cp_time_limit=cp_time_limit)
        metrics.update(decision)
        if decision["cp_decision"] == "SKIPPED_BUDGET":
            return fallback("SKIPPED_BUDGET")
        cp_deadline = decision["cp_deadline"]
        build_deadline = decision["cp_build_deadline"]
    elif generation_policy == "greedy_first":
        now = monotonic()
        # With a valid fallback CP-SAT is a bounded improvement, otherwise it
        # may use the remaining generation allocation to recover feasibility.
        if greedy is not None:
            cp_deadline = now + refinement_seconds
            if deadline is not None:
                cp_deadline = min(deadline, cp_deadline)
        if cp_deadline is not None and cp_deadline - now < min_solve_seconds:
            metrics["cp_decision"] = "SKIPPED_BUDGET"
            return fallback("INSUFFICIENT_CP_BUDGET")
        build_deadline = cp_deadline - min_solve_seconds if cp_deadline is not None else None
    if active_cp_policy == "fixed_window":
        metrics.update(cp_decision="RUN_FIXED_WINDOW",
                       cp_remaining_seconds=max(0, deadline - monotonic()) if deadline is not None else None,
                       cp_allocated_seconds=max(0, cp_deadline - monotonic()) if cp_deadline is not None else cp_time_limit)
    try:
        with timed("cp_model_seconds"):
            model, cp_choices = _build_cp_model(
                demands, choices, previous, room_unavailable, teacher_unavailable,
                scoring.time_preferences, build_deadline, scoring=scoring)
    except SearchBudgetExpired:
        return fallback("MODEL_BUILD_TIMEOUT")
    except OverflowError:
        return fallback("MODEL_OBJECTIVE_LIMIT")
    metrics["cp_model_complete"] = True

    if generation_policy == "model_first":
        generate_greedy(deadline)
    try:
        with timed("cp_model_seconds"):
            if seed_solution is not None:
                for index, (_, x, _, r, _, g) in enumerate(cp_choices):
                    check_deadline(build_deadline)
                    for flags, chosen in zip((x, r, g), seed_solution[index]):
                        for flag_index, flag in enumerate(flags):
                            model.AddHint(flag, int(flag_index == chosen))
    except SearchBudgetExpired:
        return fallback("HINT_BUILD_TIMEOUT")
    remaining = cp_time_limit if cp_deadline is None else min(cp_time_limit, cp_deadline - monotonic())
    if remaining <= 0 or (active_cp_policy == "budget_aware" and remaining < min_solve_seconds):
        return fallback("NO_SOLVE_TIME")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = num_search_workers
    solver.parameters.random_seed = seed
    metrics.update(cp_called=True, cp_time_limit_seconds=round(remaining, 6))
    try:
        with timed("cp_solve_seconds"):
            status = solver.Solve(model)
    except SearchBudgetExpired:
        metrics["cp_status"] = "INTERRUPTED"
        return fallback("SOLVER_INTERRUPTED")
    except RuntimeError as exc:
        metrics.update(cp_status="ERROR", cp_error=str(exc))
        if greedy is not None:
            return fallback("SOLVER_ERROR")
        raise
    metrics["cp_status"] = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if greedy is not None:
            if status != cp_model.UNKNOWN:
                metrics["cp_warning"] = "Solver rejected a model with an independently valid seed"
            return fallback(None)
        return None, solver.StatusName(status), None
    result = []
    for demand, (times, x, rooms, r, teachers, g) in zip(demands, cp_choices):
        day, start, _ = times[next(j for j, flag in enumerate(x) if solver.Value(flag))]
        room = rooms[next(j for j, flag in enumerate(r) if solver.Value(flag))]
        teacher = teachers[next(j for j, flag in enumerate(g) if solver.Value(flag))].lecturer
        result.append((demand, day, start, room, teacher))
    try:
        score = validate(result)
        metrics["cp_score"] = score
        if score != round(solver.ObjectiveValue()):
            raise ValueError("CP-SAT objective differs from shared score")
    except (ValueError, KeyError) as exc:
        metrics["cp_candidate_error"] = str(exc)
        return fallback("CP_CANDIDATE_REJECTED")
    if greedy is not None and greedy_score <= score:
        return fallback("CP_NOT_BETTER_THAN_GREEDY")
    metrics["source"] = "CP_SAT"
    return result, solver.StatusName(status), score


def _prepare_generation(semester, demands, room_map, teacher_map, room_blocks,
                        teacher_blocks, allowed_pairs, preferences, scoring, deadline):
    check_deadline(deadline)
    scoring = scoring or SoftScorer(semester, teacher_map, allowed_pairs, preferences)
    periods = scoring.periods
    if not periods:
        raise ValueError("Chưa cấu hình tiết học cho hệ thống")
    qualification = defaultdict(list)
    for q in scoring.qualifications:
        qualification[q.course_id].append(q)
    room_unavailable = defaultdict(list)
    for code, day, start, count, weeks in room_blocks:
        for week in weeks:
            room_unavailable[(room_map[code].pk, day, week)].append((start, count))
    teacher_unavailable = defaultdict(list)
    for code, day, start, count, weeks in teacher_blocks:
        for week in weeks:
            teacher_unavailable[(teacher_map[code].pk, day, week)].append((start, count))
    preferences = scoring.preferences
    for pref in preferences:
        if pref.kind != "NgayNghi":
            continue
        if pref.day:
            for week in range(1, semester.week_count + 1):
                teacher_unavailable[(pref.lecturer_id, pref.day, week)].append((1, 13))
    choices = _prepare_choices(demands, room_map, qualification, periods, deadline)
    previous = list(ScheduleEntry.objects.filter(group__semester=semester)
                    .exclude(source="ThuatToan", status="ChoDuyet")
                    .select_related("group").prefetch_related("schedule_weeks", "group__cohort_links"))
    return scoring, choices, previous, room_unavailable, teacher_unavailable


def _build_cp_model(demands, domains, previous, room_unavailable, teacher_unavailable,
                    prefs, deadline, scoring=None):
    """Existing CP-SAT formulation, sharing the exact domains used by Greedy."""

    model = cp_model.CpModel()
    room_buckets, teacher_buckets, cohort_buckets, group_buckets = (defaultdict(list) for _ in range(4))
    choices = []
    objective = []
    for index, demand in enumerate(demands):
        check_deadline(deadline)
        group = demand["group"]
        count = demand["count"]
        time_options, _, rooms, _, teachers, _ = domains[index]
        x = [model.NewBoolVar(f"t_{index}_{j}") for j in range(len(time_options))]
        r = [model.NewBoolVar(f"r_{index}_{j}") for j in range(len(rooms))]
        g = [model.NewBoolVar(f"g_{index}_{j}") for j in range(len(teachers))]
        model.AddExactlyOne(x)
        model.AddExactlyOne(r)
        model.AddExactlyOne(g)
        start_var = model.NewIntVar(1, 13, f"start_{index}")
        end_var = model.NewIntVar(2, 14, f"end_{index}")
        model.Add(end_var == start_var + count)
        for j, (_, start, block) in enumerate(time_options):
            model.Add(start_var == start).OnlyEnforceIf(x[j])
            objective.append(evening_penalty(block) * x[j])
        day_flags = {}
        for day in demand["days"]:
            flag = model.NewBoolVar(f"day_{index}_{day}")
            model.Add(flag == sum(x[j] for j, option in enumerate(time_options) if option[0] == day))
            day_flags[day] = flag
            interval = model.NewOptionalIntervalVar(start_var, count, end_var, flag,
                                                     f"group_{index}_{day}")
            for week in demand["weeks"]:
                group_buckets[(group.pk, day, week)].append(interval)
                for link in group.cohort_links.all():
                    cohort_buckets[(link.cohort_id, day, week)].append(interval)
        for j, room in enumerate(rooms):
            check_deadline(deadline)
            for day, day_flag in day_flags.items():
                present = model.NewBoolVar(f"room_{index}_{j}_{day}")
                model.AddMultiplicationEquality(present, [r[j], day_flag])
                interval = model.NewOptionalIntervalVar(start_var, count, end_var, present,
                                                         f"ri_{index}_{j}_{day}")
                for week in demand["weeks"]:
                    room_buckets[(room.pk, day, week)].append(interval)
        for j, qualification_row in enumerate(teachers):
            check_deadline(deadline)
            teacher = qualification_row.lecturer
            objective.append(max(0, qualification_row.priority - 1) * g[j])
            for k, (day, start, block) in enumerate(time_options):
                if any(_overlap(start, count, busy_start, busy_count)
                       for week in demand["weeks"]
                       for busy_start, busy_count in teacher_unavailable[(teacher.pk, day, week)]):
                    model.Add(g[j] + x[k] <= 1)
                penalty = preference_penalty(prefs[teacher.pk], day, block)
                if penalty:
                    both = model.NewBoolVar(f"pref_{index}_{j}_{k}")
                    model.AddMultiplicationEquality(both, [g[j], x[k]])
                    objective.append(penalty * both)
            for day, day_flag in day_flags.items():
                present = model.NewBoolVar(f"teacher_{index}_{j}_{day}")
                model.AddMultiplicationEquality(present, [g[j], day_flag])
                interval = model.NewOptionalIntervalVar(start_var, count, end_var, present,
                                                         f"ti_{index}_{j}_{day}")
                for week in demand["weeks"]:
                    teacher_buckets[(teacher.pk, day, week)].append(interval)
        choices.append((time_options, x, rooms, r, teachers, g))

    for entry in previous:
        check_deadline(deadline)
        weeks = [item.week for item in entry.schedule_weeks.all()]
        if entry.room_id:
            _add_fixed(room_buckets, entry.room_id, entry.day, entry.start_period_id,
                       entry.period_count, weeks, model, f"fixed_room_{entry.pk}")
        if entry.lecturer_id:
            _add_fixed(teacher_buckets, entry.lecturer_id, entry.day, entry.start_period_id,
                       entry.period_count, weeks, model, f"fixed_teacher_{entry.pk}")
        _add_fixed(group_buckets, entry.group_id, entry.day, entry.start_period_id,
                   entry.period_count, weeks, model, f"fixed_group_{entry.pk}")
        for link in entry.group.cohort_links.all():
            _add_fixed(cohort_buckets, link.cohort_id, entry.day, entry.start_period_id,
                       entry.period_count, weeks, model, f"fixed_cohort_{entry.pk}_{link.cohort_id}")
    for buckets in (room_buckets, teacher_buckets, cohort_buckets, group_buckets):
        seen_overlaps = set()
        for intervals in buckets.values():
            check_deadline(deadline)
            if len(intervals) > 1:
                signature = tuple(interval.Index() for interval in intervals)
                if signature not in seen_overlaps:
                    model.AddNoOverlap(intervals)
                    seen_overlaps.add(signature)
    # Resource unavailability is checked against every candidate time option.
    for index, demand in enumerate(demands):
        check_deadline(deadline)
        time_options, x, rooms, r, _, _ = choices[index]
        for j, room in enumerate(rooms):
            for k, (day, start, _) in enumerate(time_options):
                if any(_overlap(start, demand["count"], busy_start, busy_count)
                       for week in demand["weeks"]
                       for busy_start, busy_count in room_unavailable[(room.pk, day, week)]):
                    model.Add(r[j] + x[k] <= 1)
    if scoring is not None:
        objective.extend(scoring.balance.add_cp_objective(model, choices, demands))
    model.Minimize(sum(objective))
    check_deadline(deadline)
    return model, choices


def _demand_snapshot(demands):
    return [{
        "group_id": demand["group"].pk,
        "course_code": demand["group"].course.code,
        "group": demand["group"].group,
        "lab_group": demand["group"].lab_group or "",
        "code": demand["code"], "excel_row": demand["line"],
    } for demand in demands]


@transaction.atomic
def run_from_workbooks(semester_id, files, actor, existing_run_id=None):
    budget = settings.QUALITY_SEARCH_BUDGET_SECONDS
    if not isfinite(budget) or budget <= 0:
        raise ValueError("Ngân sách xếp lịch phải là số giây dương hữu hạn")
    if not 0 <= settings.QUALITY_SEARCH_SEED <= 2147483645:
        raise ValueError("Seed xếp lịch phải từ 0 đến 2147483645")
    preparation_started = monotonic()
    deadline = preparation_started + budget
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    if semester.status == "DaKhoa":
        raise ValueError("Học kỳ đã khóa")
    data = read_auto_files(files)
    demands, room_blocks, teacher_blocks = _prepare_inputs(semester, data)
    plan_input = validate_plan_inputs(semester, data)
    from .plan_sync import begin_import, finish_import
    import_context = begin_import(semester)
    demands, room_map, teacher_map = _create_catalog(semester, data, demands, room_blocks, teacher_blocks)
    demand_group_ids = {demand["group"].pk for demand in demands}
    existing_in_group = (ScheduleEntry.objects.filter(group_id__in=demand_group_ids)
                         .exclude(source="ThuatToan", status="ChoDuyet")
                         .select_related("group__course").first())
    if existing_in_group:
        demand = next(item for item in demands if item["group"].pk == existing_in_group.group_id)
        raise InputIssues([issue("courses", "BuoiHocYeuCau", demand["line"],
                                 f"Nhóm {existing_in_group.group.course.code}/{existing_in_group.group.group} "
                                 "đã có lịch được duyệt hoặc nhập riêng. Hãy vào Rà soát và duyệt, "
                                 "chọn Sửa ở từng buổi cần thay đổi, lưu về chờ duyệt rồi duyệt lại; "
                                 "không chạy lại ba tệp Excel cho nhóm này.")])
    persist_plan(semester, data, demands, plan_input)
    finish_import(semester, import_context, demands, plan_input, data)
    blocked_dates = activity_blocks(semester)
    for demand in demands:
        demand["activity_blocks"] = blocked_dates.get(demand["group"].pk, set())
    allowed_pairs = {(row["ma_vien_chuc"], row["ma_mon_hoc"])
                     for row in data["lecturers"]["GiangVienHocPhan"]}
    preferences = list(LecturerPreference.objects.filter(semester=semester)
                       .select_related("lecturer").order_by("pk"))
    preferences_captured_at = timezone.now()
    preferences_snapshot = [{
        "id": pref.pk, "lecturer_id": pref.lecturer_id,
        "employee_code": pref.lecturer.employee_code, "lecturer_name": pref.lecturer.name,
        "kind": pref.kind, "day": pref.day, "time_block": pref.time_block,
        "priority": pref.priority, "note": pref.note,
    } for pref in preferences]
    input_preparation_seconds = round(monotonic() - preparation_started, 6)
    result, status, objective_before, objective, optimization_trials = search_quality(
        semester, demands, room_map, teacher_map, room_blocks, teacher_blocks, allowed_pairs,
        preferences=preferences, deadline=deadline, max_starts=settings.QUALITY_SEARCH_MAX_STARTS,
        seed=settings.QUALITY_SEARCH_SEED,
    )
    if optimization_trials:
        # Charged once per request, not once for each independent start.
        optimization_trials[0]["input_preparation_seconds"] = input_preparation_seconds
    quality_snapshot = next((t["quality_snapshot"] for t in optimization_trials if "quality_snapshot" in t),
                            {"version": "soft_v1", "weight": 0})
    if result is None:
        if status == "INFEASIBLE":
            message = "Không có phương án thỏa đồng thời các ràng buộc với nguồn lực hiện có"
        elif status == "UNKNOWN":
            message = "Chưa tìm được phương án hợp lệ trong ngân sách tìm kiếm; chưa thể kết luận vô nghiệm"
        else:
            message = f"Bộ giải trả trạng thái {status}; cần kiểm tra dữ liệu và mô hình"
        diagnostics = diagnose(semester, demands, room_map, teacher_map,
                               room_blocks, teacher_blocks, allowed_pairs,
                               preferences=preferences)
        if existing_run_id is None:
            run = AlgorithmRun.objects.create(semester=semester, created_by=actor, status=status,
                                              message=message, diagnostics=diagnostics,
                                              optimization_trials=optimization_trials,
                                              preferences_snapshot=preferences_snapshot,
                                              preferences_captured_at=preferences_captured_at)
        else:
            run = AlgorithmRun.objects.select_for_update().get(pk=existing_run_id)
            run.status, run.message, run.diagnostics = status, message, diagnostics
            run.optimization_trials = optimization_trials
            run.preferences_snapshot = preferences_snapshot
            run.preferences_captured_at = preferences_captured_at
            run.save(update_fields=["status", "message", "diagnostics",
                                    "preferences_snapshot", "preferences_captured_at", "optimization_trials"])
        run.objective_version = quality_snapshot["version"]
        run.quality_snapshot = quality_snapshot
        run.save(update_fields=["objective_version", "quality_snapshot"])
        return run
    update_selected_assignments(result)
    replaced = ScheduleEntry.objects.filter(group__semester=semester, source="ThuatToan", status="ChoDuyet")
    replaced_run_ids = set(replaced.exclude(algorithm_run_id__isnull=True)
                           .values_list("algorithm_run_id", flat=True))
    replaced.delete()
    AlgorithmRun.objects.filter(pk__in=replaced_run_ids).update(message="Phương án đã được thay thế bởi lần chạy mới")
    if existing_run_id is None:
        run = AlgorithmRun.objects.create(semester=semester, created_by=actor, status=status,
                                          objective=objective, objective_before=objective_before,
                                          entry_count=len(result),
                                          optimization_trials=optimization_trials,
                                          preferences_snapshot=preferences_snapshot,
                                          preferences_captured_at=preferences_captured_at,
                                          demand_snapshot=_demand_snapshot(demands))
    else:
        run = AlgorithmRun.objects.select_for_update().get(pk=existing_run_id)
        run.status, run.objective, run.objective_before = status, objective, objective_before
        run.entry_count = len(result)
        run.message, run.diagnostics = "", []
        run.optimization_trials = optimization_trials
        run.preferences_snapshot = preferences_snapshot
        run.preferences_captured_at = preferences_captured_at
        run.demand_snapshot = _demand_snapshot(demands)
        run.save(update_fields=["status", "objective", "objective_before", "entry_count",
                                "message", "diagnostics", "optimization_trials", "preferences_snapshot",
                                "preferences_captured_at", "demand_snapshot"])
    entries = [ScheduleEntry(
        group=demand["group"], lecturer=teacher, room=room, day=day,
        start_period_id=start, period_count=demand["count"],
        status="ChoDuyet", source="ThuatToan", algorithm_run=run,
        request_code=demand["code"],
    ) for demand, day, start, room, teacher in result]
    run.objective_version = quality_snapshot["version"]
    run.quality_snapshot = quality_snapshot
    run.save(update_fields=["objective_version", "quality_snapshot"])
    # audit_solution checks every hard rule against fixed and generated sessions
    # before this transaction writes any of the generated entries.
    ScheduleEntry.objects.bulk_create(entries, batch_size=250)
    if any(entry.pk is None for entry in entries):
        saved = {(e.group_id, e.request_code): e for e in run.entries.all()}
        if len(saved) != len(entries):
            raise ValueError("Không ánh xạ được đầy đủ ID buổi dạy sau khi lưu.")
        entries = [saved[(e.group_id, e.request_code)] for e in entries]
    ScheduleWeek.objects.bulk_create((
        ScheduleWeek(entry=entry, week=week)
        for entry, (demand, *_rest) in zip(entries, result)
        for week in demand["weeks"]
    ), batch_size=1000)
    return run


@transaction.atomic
def approve_algorithm_run(run_id, actor):
    from rest_framework.exceptions import ValidationError

    if actor is None or not actor.is_authenticated or not actor.is_staff:
        raise ValidationError("Chỉ quản trị viên được duyệt lịch")

    semester_id = AlgorithmRun.objects.only("semester_id").get(pk=run_id).semester_id
    semester = Semester.objects.select_for_update().get(pk=semester_id)
    run = AlgorithmRun.objects.select_for_update().get(pk=run_id)
    if run.status not in ("FEASIBLE", "OPTIMAL", "HEURISTIC") or run.entry_count == 0:
        raise ValidationError("Lần chạy không có phương án để duyệt")
    if semester.status == "DaKhoa":
        raise ValidationError("Học kỳ đã khóa")
    ids = list(run.entries.order_by("pk").values_list("pk", flat=True))
    from .access import require_object
    for entry in run.entries.select_related("group", "lecturer"):
        require_object(actor, entry, "approve")
    if len(ids) != run.entry_count or run.entries.exclude(status="ChoDuyet").exists():
        raise ValidationError("Phương án đã thay đổi hoặc đã được duyệt; hãy chạy lại nếu cần")
    violations = day_off_violations(semester.pk, run.entries.select_related(
        "group__course", "lecturer"))
    if violations:
        raise ValidationError(day_off_error(violations))
    occupied = set()
    entries = (ScheduleEntry.objects.filter(group__semester=semester)
               .select_related("group", "lecturer", "room")
               .prefetch_related("schedule_weeks", "group__cohort_links"))
    qualified = set(TeachingQualification.objects.values_list("lecturer_id", "course_id"))
    for entry in entries:
        if (entry.lecturer_id and
                (entry.lecturer.status != "DangCongTac" or
                 (entry.lecturer_id, entry.group.course_id) not in qualified)):
            raise ValidationError("Lịch có giảng viên không còn đủ điều kiện; cần xếp lại")
        if (entry.room_id and entry.room.status != "SanSang") or (
                entry.group.needs_room and not entry.room_id and not entry.other_location):
            raise ValidationError("Lịch có phòng hoặc địa điểm không còn hợp lệ; cần xếp lại")
        resources = [("group", entry.group_id), ("room", entry.room_id),
                     ("lecturer", entry.lecturer_id)]
        resources.extend(("cohort", link.cohort_id) for link in entry.group.cohort_links.all())
        weeks = [item.week for item in entry.schedule_weeks.all()]
        from .planning import check_entry_plan
        try:
            check_entry_plan(entry, weeks)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if not weeks or min(weeks) < 1 or max(weeks) > semester.week_count:
            raise ValidationError("Lịch có tuần ngoài học kỳ; cần xếp lại")
        for week in weeks:
            for period in range(entry.start_period_id, entry.start_period_id + entry.period_count):
                for kind, resource_id in resources:
                    if resource_id is None:
                        continue
                    key = kind, resource_id, entry.day, week, period
                    if key in occupied:
                        raise ValidationError("Lịch phát sinh xung đột trước khi duyệt; cần xếp lại")
                    occupied.add(key)
    changed = ScheduleEntry.objects.filter(pk__in=ids, status="ChoDuyet").update(
        status="DaDuyet", approved_by=actor, approved_at=timezone.now(),
    )
    if changed != len(ids):
        raise ValidationError("Phương án đã thay đổi trong khi duyệt; hãy thử lại")
    return len(ids)
