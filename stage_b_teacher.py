"""
Pha B - Bo sung bien Teacher vao nghiem Room+Time da co tu Pha A (best_sol).
Dung Cach Gop Chung (1 lan giai CP-SAT) - da kiem chung qua thuc nghiem la
vua nhanh hon/ngang bang, vua DUNG hon Sequential Fixing (Sequential that bai
o Nhom 2 tren ca 2 instance test do khoa cung lua chon Nhom 1 qua som).
"""
import time
from collections import defaultdict
import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
from stage1_solver import days_to_set, weeks_to_set


def generate_teachers(df_classes, teachers_per_subpart=1, pool_ratio=0.6, zipf_a=1.0, seed=42):
    """Sinh Teacher + TeacherCourseCompatibility (Course/Subpart Clustering + Zipf)."""
    rng = np.random.default_rng(seed)
    courses = (
        df_classes.groupby('course_id')['subpart_id']
        .nunique()
        .reset_index(name='n_subparts')
    )
    courses['n_teachers_needed'] = (courses['n_subparts'] * teachers_per_subpart).clip(lower=1)
    pool_size = max(1, int(courses['n_teachers_needed'].sum() * pool_ratio))
    teacher_ids = [f'GV_{i:04d}' for i in range(1, pool_size + 1)]
    weights = np.array([1.0 / (i ** zipf_a) for i in range(1, len(teacher_ids) + 1)])
    weights = weights / weights.sum()
    compat_rows = []
    for _, row in courses.iterrows():
        n_pick = min(int(row['n_teachers_needed']), len(teacher_ids))
        chosen = rng.choice(teacher_ids, size=n_pick, replace=False, p=weights)
        for t in chosen:
            compat_rows.append({'teacher_id': t, 'course_id': row['course_id']})
    df_compat = pd.DataFrame(compat_rows)
    df_teachers = pd.DataFrame({'teacher_id': teacher_ids, 'name': teacher_ids})
    return df_teachers, df_compat


def compute_stage0_metrics(df_compat, thresholds, epsilon=1e-6):
    """Tinh Deg(i), Bottleneck(c), phan loai 3 nhom giao vien."""
    deg = df_compat.groupby('teacher_id')['course_id'].nunique().rename('Deg').reset_index()

    def classify(d):
        if d <= thresholds['group1_max_deg']:
            return 1
        elif d <= thresholds['group2_max_deg']:
            return 2
        return 3

    deg['group'] = deg['Deg'].apply(classify)
    n_teachers_per_course = df_compat.groupby('course_id')['teacher_id'].nunique().rename('n_teachers').reset_index()
    n_teachers_per_course['Bottleneck'] = 1.0 / (n_teachers_per_course['n_teachers'] + epsilon)
    return deg, n_teachers_per_course


def get_class_candidates(class_ids, df_classes, df_compat):
    """class_id -> list teacher_id kha di (theo course_id cua lop)."""
    course_of = df_classes.set_index('class_id')['course_id'].to_dict()
    teachers_of_course = df_compat.groupby('course_id')['teacher_id'].apply(list).to_dict()
    return {c: teachers_of_course.get(course_of[c], []) for c in class_ids}


def _classes_conflict(c1, c2, best_sol, class_times):
    t1, t2 = class_times[c1][best_sol[c1]['t']], class_times[c2][best_sol[c2]['t']]
    if not (days_to_set(t1['days']) & days_to_set(t2['days'])):
        return False
    if not (weeks_to_set(t1['weeks']) & weeks_to_set(t2['weeks'])):
        return False
    s1, e1 = t1['start'], t1['start'] + t1['length']
    s2, e2 = t2['start'], t2['start'] + t2['length']
    return s1 < e2 and s2 < e1


def repair_teacher_feasibility(class_ids, best_sol, class_times, df_classes, df_teachers, df_compat, seed=42):
    """Vá lớp 1: thêm giáo viên dự phòng cho ĐÚNG course có lớp xung đột nội bộ vượt quá số giáo viên khả dĩ."""
    course_of = df_classes.set_index('class_id')['course_id'].to_dict()
    teachers_of_course = df_compat.groupby('course_id')['teacher_id'].apply(list).to_dict()
    classes_of_course = defaultdict(list)
    for c in class_ids:
        classes_of_course[course_of[c]].append(c)

    new_compat_rows, new_teacher_rows = [], []
    n_repaired = 0
    next_id = len(df_teachers) + 1

    for course_id, cls_list in classes_of_course.items():
        cands = teachers_of_course.get(course_id, [])
        max_overlap = 1
        for i in range(len(cls_list)):
            cnt = 1 + sum(1 for j in range(len(cls_list)) if j != i and _classes_conflict(cls_list[i], cls_list[j], best_sol, class_times))
            max_overlap = max(max_overlap, cnt)
        if max_overlap > len(cands):
            for _ in range(max_overlap - len(cands)):
                new_tid = f'GV_R{next_id:04d}'
                next_id += 1
                new_teacher_rows.append({'teacher_id': new_tid, 'name': new_tid})
                new_compat_rows.append({'teacher_id': new_tid, 'course_id': course_id})
            n_repaired += 1

    df_teachers2 = pd.concat([df_teachers, pd.DataFrame(new_teacher_rows)], ignore_index=True) if new_teacher_rows else df_teachers
    df_compat2 = pd.concat([df_compat, pd.DataFrame(new_compat_rows)], ignore_index=True) if new_compat_rows else df_compat
    return df_teachers2, df_compat2, n_repaired


def build_teacher_model(class_ids, best_sol, class_times, class_candidates):
    """Xay model CP-SAT gan giao vien (Cach Gop Chung) - tra ve model, teacher_bool de giai."""
    model = cp_model.CpModel()
    teacher_bool = {}
    for c in class_ids:
        cands = class_candidates[c]
        vt = [model.NewBoolVar(f'gv_{c}_{i}') for i in range(len(cands))]
        model.AddExactlyOne(vt)
        for i, v in enumerate(vt):
            teacher_bool[(c, i)] = v

    day_teacher_buckets = defaultdict(list)
    for c in class_ids:
        t = class_times[c][best_sol[c]['t']]
        wset = weeks_to_set(t['weeks'])
        for i, tid in enumerate(class_candidates[c]):
            for d in days_to_set(t['days']):
                day_teacher_buckets[(tid, d)].append((teacher_bool[(c, i)], t['start'], t['start'] + t['length'], wset, c))

    for key, items in day_teacher_buckets.items():
        for a in range(len(items)):
            p1, s1, e1, w1, c1 = items[a]
            for b in range(a + 1, len(items)):
                p2, s2, e2, w2, c2 = items[b]
                if c1 != c2 and (w1 & w2) and s1 < e2 and s2 < e1:
                    model.Add(p1 + p2 <= 1)

    return model, teacher_bool


def repair_global_iterative(class_ids, best_sol, class_times, class_candidates, df_teachers, df_compat,
                             course_of, max_rounds=10):
    """Vá lớp 2 (dự phòng cuối): dùng mô hình NỚI LỎNG (cho phép 1 lớp tạm "chưa có giáo viên"
    qua biến slack) để CP-SAT tự xác định CHÍNH XÁC toàn bộ các lớp đang gây xung đột thật sự
    trong 1 lần giải duy nhất, rồi vá HÀNG LOẠT cho tất cả các lớp đó cùng lúc - hội tụ nhanh
    hơn nhiều so với sửa dò từng lớp một (chỉ cần vài vòng thay vì hàng trăm lần)."""
    next_id = len(df_teachers) + 1000

    for rnd in range(max_rounds):
        model = cp_model.CpModel()
        teacher_bool = {}
        slack_bool = {}
        for c in class_ids:
            cands = class_candidates[c]
            vt = [model.NewBoolVar(f'gv_{c}_{i}') for i in range(len(cands))]
            sv = model.NewBoolVar(f'slack_{c}')  # "chua co giao vien" - CHI dung de do, khong phai nghiem that
            model.AddExactlyOne(vt + [sv])
            for i, v in enumerate(vt):
                teacher_bool[(c, i)] = v
            slack_bool[c] = sv

        day_teacher_buckets = defaultdict(list)
        for c in class_ids:
            t = class_times[c][best_sol[c]['t']]
            wset = weeks_to_set(t['weeks'])
            for i, tid in enumerate(class_candidates[c]):
                for d in days_to_set(t['days']):
                    day_teacher_buckets[(tid, d)].append((teacher_bool[(c, i)], t['start'], t['start'] + t['length'], wset, c))
        for key, items in day_teacher_buckets.items():
            for a in range(len(items)):
                p1, s1, e1, w1, c1 = items[a]
                for b in range(a + 1, len(items)):
                    p2, s2, e2, w2, c2 = items[b]
                    if c1 != c2 and (w1 & w2) and s1 < e2 and s2 < e1:
                        model.Add(p1 + p2 <= 1)

        model.Minimize(sum(slack_bool.values()))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 120
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f'Khong giai duoc ngay ca mo hinh noi long (vong {rnd}) - can kiem tra lai du lieu.')

        n_slack = sum(1 for c in class_ids if solver.Value(slack_bool[c]) == 1)
        print(f'  Vong va {rnd + 1}: so lop dang bi tac (dung slack) = {n_slack}')
        if n_slack == 0:
            return class_candidates, df_teachers, df_compat, solver, teacher_bool, rnd

        new_teacher_rows, new_compat_rows = [], []
        for c in class_ids:
            if solver.Value(slack_bool[c]) == 1:
                new_tid = f'GV_G{next_id:05d}'
                next_id += 1
                class_candidates[c] = class_candidates[c] + [new_tid]
                new_teacher_rows.append({'teacher_id': new_tid, 'name': new_tid})
                new_compat_rows.append({'teacher_id': new_tid, 'course_id': course_of[c]})
        df_teachers = pd.concat([df_teachers, pd.DataFrame(new_teacher_rows)], ignore_index=True)
        df_compat = pd.concat([df_compat, pd.DataFrame(new_compat_rows)], ignore_index=True)

    raise RuntimeError(f'Van con lop bi tac sau {max_rounds} vong va hang loat.')


def extract_teacher_assignment(solver, teacher_bool, class_ids, class_candidates):
    """Tra ve dict class_id -> teacher_id da gan."""
    assignment = {}
    for c in class_ids:
        for i, tid in enumerate(class_candidates[c]):
            if solver.Value(teacher_bool[(c, i)]):
                assignment[c] = tid
                break
    return assignment
