"""
Stage 2 - Adaptive Iterated Local Search voi Great Deluge (Pha A: khong Teacher, khong Student Sectioning)
Toi uu Soft Penalty = w_time*TimePenalty + w_room*RoomPenalty + w_dist*DistributionPenalty
Ban toi uu: dung DELTA (chi tinh phan thay doi) thay vi tinh lai tu dau moi vong lap.
"""
import random
from collections import defaultdict

from stage1_solver import (
    days_to_set, weeks_to_set, times_overlap, week_position,
    compute_day_multiplier, parse_dist_type,
)


# ---------- Trich xuat nghiem tu Stage 1 ----------
def extract_solution(solver, time_bool, room_bool, class_ids, class_times, class_rooms):
    sol = {}
    for c in class_ids:
        t_idx = next(i for i in range(len(class_times[c])) if solver.Value(time_bool[(c, i)]) == 1)
        if class_rooms[c]:
            r_idx = next(i for i in range(len(class_rooms[c])) if solver.Value(room_bool[(c, i)]) == 1)
        else:
            r_idx = None
        sol[c] = {'t': t_idx, 'r': r_idx}
    return sol


# ---------- Danh gia 1 dong distribution co bi vi pham khong (dung chung cho Stage 1 logic va o day) ----------
def _violates_distribution(base_type, params, cls_group, sol, class_times, class_rooms, day_multiplier):
    times = [class_times[c][sol[c]['t']] for c in cls_group]

    if base_type in ('NotOverlap', 'SameAttendees'):
        for i in range(len(times)):
            for j in range(i + 1, len(times)):
                if times_overlap(times[i], times[j]):
                    return True
        return False
    if base_type == 'SameTime':
        return len({(t['start'], t['length']) for t in times}) > 1
    if base_type == 'SameDays':
        return len({days_to_set(t['days']) for t in times}) > 1
    if base_type == 'SameWeeks':
        return len({weeks_to_set(t['weeks']) for t in times}) > 1
    if base_type == 'DifferentDays':
        for i in range(len(times)):
            for j in range(i + 1, len(times)):
                if days_to_set(times[i]['days']) & days_to_set(times[j]['days']):
                    return True
        return False
    if base_type == 'SameRoom':
        room_ids = {class_rooms[c][sol[c]['r']]['room_id'] for c in cls_group if sol[c]['r'] is not None}
        return len(room_ids) > 1
    if base_type == 'Precedence':
        for i in range(len(cls_group) - 1):
            end_i = week_position(times[i], day_multiplier) + times[i]['length']
            start_j = week_position(times[i + 1], day_multiplier)
            if end_i > start_j:
                return True
        return False
    if base_type == 'MinGap':
        g = params[0] if params else 0
        for i in range(len(times)):
            for j in range(i + 1, len(times)):
                if days_to_set(times[i]['days']) & days_to_set(times[j]['days']) and \
                   weeks_to_set(times[i]['weeks']) & weeks_to_set(times[j]['weeks']):
                    gap = max(times[j]['start'] - (times[i]['start'] + times[i]['length']),
                              times[i]['start'] - (times[j]['start'] + times[j]['length']))
                    if gap < g:
                        return True
        return False
    if base_type == 'WorkDay':
        s = params[0] if params else 10 ** 9
        for d in range(7):
            in_day = [t for t in times if d in days_to_set(t['days'])]
            if len(in_day) < 2:
                continue
            span = max(t['start'] + t['length'] for t in in_day) - min(t['start'] for t in in_day)
            if span > s:
                return True
        return False
    if base_type == 'MaxDays':
        D = params[0] if params else 7
        used_days = set()
        for t in times:
            used_days |= days_to_set(t['days'])
        return len(used_days) > D
    if base_type == 'MaxDayLoad':
        S = params[0] if params else 10 ** 9
        for d in range(7):
            load = sum(t['length'] for t in times if d in days_to_set(t['days']))
            if load > S:
                return True
        return False
    if base_type == 'MaxBlock':
        m, s = (params + (10 ** 9, 10 ** 9))[:2]
        for d in range(7):
            in_day = sorted((t for t in times if d in days_to_set(t['days'])), key=lambda t: t['start'])
            if not in_day:
                continue
            block_start = in_day[0]['start']
            block_end = in_day[0]['start'] + in_day[0]['length']
            for t in in_day[1:]:
                if t['start'] - block_end <= s:
                    block_end = max(block_end, t['start'] + t['length'])
                else:
                    if block_end - block_start > m:
                        return True
                    block_start, block_end = t['start'], t['start'] + t['length']
            if block_end - block_start > m:
                return True
        return False
    return False


# ---------- Tinh Soft Penalty TOAN CUC (chi dung 1 lan luc khoi tao S0, khong dung trong vong lap) ----------
def compute_objective(sol, class_times, class_rooms, df_dist, weights=(1, 1, 10)):
    w_time, w_room, w_dist = weights
    time_penalty = sum(class_times[c][s['t']]['penalty'] for c, s in sol.items())
    room_penalty = sum(class_rooms[c][s['r']]['penalty'] for c, s in sol.items() if s['r'] is not None)

    day_multiplier = compute_day_multiplier(class_times)
    dist_penalty = 0
    for _, row in df_dist.iterrows():
        if row['required'] == 'true':
            continue
        pen = row['penalty'] or 0
        base_type, params = parse_dist_type(row['type'])
        cls_group = [cid for cid in row['class_ids'] if cid in sol]
        if len(cls_group) < 2:
            continue
        if _violates_distribution(base_type, params, cls_group, sol, class_times, class_rooms, day_multiplier):
            dist_penalty += pen

    total = w_time * time_penalty + w_room * room_penalty + w_dist * dist_penalty
    return {'total': total, 'time_penalty': time_penalty, 'room_penalty': room_penalty, 'dist_penalty': dist_penalty}


# ---------- Cau truc index phuc vu DELTA va kiem tra kha thi nhanh ----------
def build_occupancy(sol, class_times, class_rooms):
    occ = defaultdict(list)
    for c, s in sol.items():
        if s['r'] is None:
            continue
        t = class_times[c][s['t']]
        room_id = class_rooms[c][s['r']]['room_id']
        wset = weeks_to_set(t['weeks'])
        for d in days_to_set(t['days']):
            occ[(room_id, d)].append((c, t['start'], t['start'] + t['length'], wset))
    return occ


def occ_remove_class(occ, c, room_id, topt):
    wset = weeks_to_set(topt['weeks'])
    for d in days_to_set(topt['days']):
        occ[(room_id, d)] = [e for e in occ[(room_id, d)] if e[0] != c]


def occ_add_class(occ, c, room_id, topt):
    wset = weeks_to_set(topt['weeks'])
    for d in days_to_set(topt['days']):
        occ[(room_id, d)].append((c, topt['start'], topt['start'] + topt['length'], wset))


def room_free(occ, room_id, topt, exclude_class):
    wset = weeks_to_set(topt['weeks'])
    for d in days_to_set(topt['days']):
        for (c2, s2, e2, w2) in occ.get((room_id, d), []):
            if c2 == exclude_class:
                continue
            if wset & w2 and topt['start'] < e2 and s2 < topt['start'] + topt['length']:
                return False
    return True


def build_class_to_hard_dist(df_dist, class_ids_set):
    mapping = defaultdict(list)
    for _, row in df_dist.iterrows():
        if row['required'] != 'true':
            continue
        base_type, params = parse_dist_type(row['type'])
        cls_group = [cid for cid in row['class_ids'] if cid in class_ids_set]
        if len(cls_group) < 2:
            continue
        for c in cls_group:
            mapping[c].append((base_type, params, cls_group))
    return mapping


def build_class_to_soft_dist(df_dist, class_ids_set):
    """class_id -> list (row_id, base_type, params, cls_group, penalty) - CHI cac dong MEM (required != true).
    row_id dung de khu trung khi 1 dong lien quan toi ca 2 lop vua thay doi cung luc (vd time_swap)."""
    mapping = defaultdict(list)
    for row_id, row in df_dist.iterrows():
        if row['required'] == 'true':
            continue
        base_type, params = parse_dist_type(row['type'])
        cls_group = [cid for cid in row['class_ids'] if cid in class_ids_set]
        if len(cls_group) < 2:
            continue
        pen = row['penalty'] or 0
        for c in cls_group:
            mapping[c].append((row_id, base_type, params, cls_group, pen))
    return mapping


def hard_dist_ok(class_to_hard_dist, changed_class, sol, class_times, class_rooms, day_multiplier):
    for base_type, params, cls_group in class_to_hard_dist.get(changed_class, []):
        if _violates_distribution(base_type, params, cls_group, sol, class_times, class_rooms, day_multiplier):
            return False
    return True


def get_affected_soft_rows(changed_classes, class_to_soft_dist):
    seen = {}
    for c in changed_classes:
        for row_id, base_type, params, cls_group, pen in class_to_soft_dist.get(c, []):
            seen[row_id] = (base_type, params, cls_group, pen)
    return seen


def sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier):
    total = 0
    for row_id, (base_type, params, cls_group, pen) in affected_rows.items():
        if _violates_distribution(base_type, params, cls_group, sol, class_times, class_rooms, day_multiplier):
            total += pen
    return total


# ---------- Toan tu lang gieng (tra ve None neu khong tim duoc buoc di hop le) ----------
def op_time_change(sol, class_ids, class_times, class_rooms, occ, class_to_hard_dist, day_multiplier, rng):
    candidates = [c for c in class_ids if len(class_times[c]) > 1]
    if not candidates:
        return None
    c = rng.choice(candidates)
    old_t = sol[c]['t']
    choices = [i for i in range(len(class_times[c])) if i != old_t]
    rng.shuffle(choices)
    for new_t in choices:
        new_topt = class_times[c][new_t]
        if sol[c]['r'] is not None:
            room_id = class_rooms[c][sol[c]['r']]['room_id']
            if not room_free(occ, room_id, new_topt, exclude_class=c):
                continue
        sol[c]['t'] = new_t
        if hard_dist_ok(class_to_hard_dist, c, sol, class_times, class_rooms, day_multiplier):
            return ('time_change', c, old_t, new_t)
        sol[c]['t'] = old_t
    return None


def op_room_move(sol, class_ids, class_times, class_rooms, occ, class_to_hard_dist, day_multiplier, rng):
    candidates = [c for c in class_ids if len(class_rooms[c]) > 1]
    if not candidates:
        return None
    c = rng.choice(candidates)
    old_r = sol[c]['r']
    choices = [i for i in range(len(class_rooms[c])) if i != old_r]
    rng.shuffle(choices)
    topt = class_times[c][sol[c]['t']]
    for new_r in choices:
        room_id = class_rooms[c][new_r]['room_id']
        if not room_free(occ, room_id, topt, exclude_class=c):
            continue
        sol[c]['r'] = new_r
        return ('room_move', c, old_r, new_r)
    return None


def op_time_swap(sol, class_ids, class_times, class_rooms, occ, class_to_hard_dist, day_multiplier, rng):
    c1 = rng.choice(class_ids)
    t1 = class_times[c1][sol[c1]['t']]
    key1 = (t1['days'], t1['start'], t1['length'], t1['weeks'])
    for c2 in rng.sample(class_ids, min(20, len(class_ids))):
        if c2 == c1:
            continue
        t2 = class_times[c2][sol[c2]['t']]
        key2 = (t2['days'], t2['start'], t2['length'], t2['weeks'])
        idx1_in_c2 = next((i for i, t in enumerate(class_times[c2])
                            if (t['days'], t['start'], t['length'], t['weeks']) == key1), None)
        idx2_in_c1 = next((i for i, t in enumerate(class_times[c1])
                            if (t['days'], t['start'], t['length'], t['weeks']) == key2), None)
        if idx1_in_c2 is None or idx2_in_c1 is None:
            continue
        old_t1, old_t2 = sol[c1]['t'], sol[c2]['t']
        sol[c1]['t'], sol[c2]['t'] = idx2_in_c1, idx1_in_c2

        ok = True
        if sol[c1]['r'] is not None and not room_free(
                occ, class_rooms[c1][sol[c1]['r']]['room_id'], class_times[c1][sol[c1]['t']], exclude_class=c1):
            ok = False
        if ok and sol[c2]['r'] is not None and not room_free(
                occ, class_rooms[c2][sol[c2]['r']]['room_id'], class_times[c2][sol[c2]['t']], exclude_class=c2):
            ok = False
        if ok and not (hard_dist_ok(class_to_hard_dist, c1, sol, class_times, class_rooms, day_multiplier) and
                        hard_dist_ok(class_to_hard_dist, c2, sol, class_times, class_rooms, day_multiplier)):
            ok = False

        if ok:
            return ('time_swap', c1, c2, old_t1, old_t2)
        sol[c1]['t'], sol[c2]['t'] = old_t1, old_t2
    return None


def _undo_move(sol, move):
    kind = move[0]
    if kind == 'time_change':
        _, c, old_t, _ = move
        sol[c]['t'] = old_t
    elif kind == 'room_move':
        _, c, old_r, _ = move
        sol[c]['r'] = old_r
    elif kind == 'time_swap':
        _, c1, c2, old_t1, old_t2 = move
        sol[c1]['t'], sol[c2]['t'] = old_t1, old_t2


def _move_changed_classes(move):
    kind = move[0]
    if kind in ('time_change', 'room_move'):
        return [move[1]]
    if kind == 'time_swap':
        return [move[1], move[2]]
    return []


def _apply_occ_for_accepted_move(occ, move, sol, class_times, class_rooms, old_state):
    """Cap nhat occ CO DINH HUONG (chi 1-2 lop lien quan), khong xay lai toan bo."""
    for c in _move_changed_classes(move):
        old_t, old_r = old_state[c]
        if old_r is not None:
            occ_remove_class(occ, c, class_rooms[c][old_r]['room_id'], class_times[c][old_t])
        new_r = sol[c]['r']
        if new_r is not None:
            occ_add_class(occ, c, class_rooms[c][new_r]['room_id'], class_times[c][sol[c]['t']])



# ---------- Vong lap chinh ----------
def run_stage2(sol0, class_ids, class_times, class_rooms, df_dist,
               weights=(1, 1, 10), max_iterations=5000,
               initial_level_factor=1.2, decay_rate=0.999, seed=42, verbose_every=500):
    rng = random.Random(seed)
    day_multiplier = compute_day_multiplier(class_times)
    class_ids_set = set(class_ids)
    class_to_hard_dist = build_class_to_hard_dist(df_dist, class_ids_set)
    class_to_soft_dist = build_class_to_soft_dist(df_dist, class_ids_set)

    sol = {c: dict(v) for c, v in sol0.items()}
    occ = build_occupancy(sol, class_times, class_rooms)

    obj0 = compute_objective(sol, class_times, class_rooms, df_dist, weights)
    best_sol = {c: dict(v) for c, v in sol.items()}
    best_obj = obj0['total']
    cur_obj = obj0['total']

    level = cur_obj * initial_level_factor
    w_time, w_room, w_dist = weights

    operators = [op_time_change, op_room_move, op_time_swap]
    op_weights = [1.0, 1.0, 1.0]

    history = []

    for it in range(max_iterations):
        idx = rng.choices(range(len(operators)), weights=op_weights, k=1)[0]
        op = operators[idx]

        move = op(sol, class_ids, class_times, class_rooms, occ, class_to_hard_dist, day_multiplier, rng)
        if move is None:
            continue

        kind = move[0]
        if kind == 'time_change':
            _, c, old_t, _ = move
            snapshot_before = {c: (old_t, sol[c]['r'])}
        elif kind == 'room_move':
            _, c, old_r, _ = move
            snapshot_before = {c: (sol[c]['t'], old_r)}
        else:  # time_swap
            _, c1, c2, old_t1, old_t2 = move
            snapshot_before = {c1: (old_t1, sol[c1]['r']), c2: (old_t2, sol[c2]['r'])}

        changed = list(snapshot_before.keys())
        affected_rows = get_affected_soft_rows(changed, class_to_soft_dist)

        # "Truoc": khoi phuc tam gia tri cu de tinh vi pham truoc do
        cur_vals = {c: (sol[c]['t'], sol[c]['r']) for c in changed}
        for c in changed:
            sol[c]['t'], sol[c]['r'] = snapshot_before[c]
        before_pen = sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier)
        for c in changed:
            sol[c]['t'], sol[c]['r'] = cur_vals[c]
        after_pen = sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier)

        time_delta = sum(
            class_times[c][sol[c]['t']]['penalty'] - class_times[c][snapshot_before[c][0]]['penalty']
            for c in changed
        )
        room_delta = sum(
            (class_rooms[c][sol[c]['r']]['penalty'] if sol[c]['r'] is not None else 0) -
            (class_rooms[c][snapshot_before[c][1]]['penalty'] if snapshot_before[c][1] is not None else 0)
            for c in changed
        )
        dist_delta = after_pen - before_pen

        delta = w_time * time_delta + w_room * room_delta + w_dist * dist_delta
        new_obj = cur_obj + delta

        if new_obj <= level:
            _apply_occ_for_accepted_move(occ, move, sol, class_times, class_rooms, snapshot_before)
            cur_obj = new_obj
            if new_obj < best_obj:
                best_obj = new_obj
                best_sol = {c: dict(v) for c, v in sol.items()}
                op_weights[idx] = min(op_weights[idx] * 1.05, 10.0)
        else:
            _undo_move(sol, move)
            op_weights[idx] = max(op_weights[idx] * 0.98, 0.1)

        level *= decay_rate

        if verbose_every and (it + 1) % verbose_every == 0:
            history.append((it + 1, cur_obj, best_obj, level))
            print(f'  Vong lap {it+1:5d} | cur={cur_obj:10.1f} | best={best_obj:10.1f} | level={level:10.1f}')

    return best_sol, best_obj, history


def op_perturbation(sol, class_ids, class_times, class_rooms, occ, class_to_hard_dist, day_multiplier, rng, kick_size=15):
    """Xao tron (kick) mot so lop CUNG LUC de thoat cuc tri dia phuong - dung khi thuat toan bi 'ket'.
    Khac voi 3 toan tu con lai (chi doi 1 buoc nho), ham nay co the doi NHIEU lop cung luc,
    khong hoan tac tung buoc rieng le neu that bai ma bo qua hoan toan lop do (giu nguyen)."""
    changed = []
    old_vals = {}
    targets = rng.sample(class_ids, min(kick_size, len(class_ids)))
    for c in targets:
        did_change = False
        if len(class_times[c]) > 1 and rng.random() < 0.6:
            old_t = sol[c]['t']
            choices = [i for i in range(len(class_times[c])) if i != old_t]
            rng.shuffle(choices)
            for new_t in choices:
                new_topt = class_times[c][new_t]
                if sol[c]['r'] is not None:
                    room_id = class_rooms[c][sol[c]['r']]['room_id']
                    if not room_free(occ, room_id, new_topt, exclude_class=c):
                        continue
                old_vals.setdefault(c, (old_t, sol[c]['r']))
                sol[c]['t'] = new_t
                if hard_dist_ok(class_to_hard_dist, c, sol, class_times, class_rooms, day_multiplier):
                    did_change = True
                    break
                sol[c]['t'] = old_t
        if not did_change and len(class_rooms[c]) > 1 and rng.random() < 0.6:
            old_r = sol[c]['r']
            choices = [i for i in range(len(class_rooms[c])) if i != old_r]
            rng.shuffle(choices)
            topt = class_times[c][sol[c]['t']]
            for new_r in choices:
                room_id = class_rooms[c][new_r]['room_id']
                if room_free(occ, room_id, topt, exclude_class=c):
                    old_vals.setdefault(c, (sol[c]['t'], old_r))
                    sol[c]['r'] = new_r
                    did_change = True
                    break
        if did_change:
            changed.append(c)
    return changed, old_vals


def run_stage2_ils(sol0, class_ids, class_times, class_rooms, df_dist,
                    weights=(1, 1, 10), max_iterations=100000,
                    initial_level_factor=1.2, decay_rate=0.99995, seed=42,
                    verbose_every=10000, stagnation_limit=3000, kick_size=15):
    """Ban day du: Great Deluge + co che Perturbation/Kick khi bi ket (dung khi 'best' khong doi
    qua stagnation_limit vong lap lien tiep)."""
    rng = random.Random(seed)
    day_multiplier = compute_day_multiplier(class_times)
    class_ids_set = set(class_ids)
    class_to_hard_dist = build_class_to_hard_dist(df_dist, class_ids_set)
    class_to_soft_dist = build_class_to_soft_dist(df_dist, class_ids_set)

    sol = {c: dict(v) for c, v in sol0.items()}
    occ = build_occupancy(sol, class_times, class_rooms)

    obj0 = compute_objective(sol, class_times, class_rooms, df_dist, weights)
    best_sol = {c: dict(v) for c, v in sol.items()}
    best_obj = obj0['total']
    cur_obj = obj0['total']

    level = cur_obj * initial_level_factor
    w_time, w_room, w_dist = weights

    operators = [op_time_change, op_room_move, op_time_swap]
    op_weights = [1.0, 1.0, 1.0]

    history = []
    no_improve_count = 0
    n_kicks = 0

    for it in range(max_iterations):
        if no_improve_count >= stagnation_limit:
            # KICK: xao tron kick_size lop, LUON chap nhan (khong xet muc nuoc), coi nhu diem xuat phat moi
            changed, old_vals = op_perturbation(sol, class_ids, class_times, class_rooms, occ,
                                                 class_to_hard_dist, day_multiplier, rng, kick_size)
            if changed:
                for c in changed:
                    old_t, old_r = old_vals[c]
                    if old_r is not None:
                        occ_remove_class(occ, c, class_rooms[c][old_r]['room_id'], class_times[c][old_t])
                    if sol[c]['r'] is not None:
                        occ_add_class(occ, c, class_rooms[c][sol[c]['r']]['room_id'], class_times[c][sol[c]['t']])
                cur_obj = compute_objective(sol, class_times, class_rooms, df_dist, weights)['total']
                level = max(level, cur_obj * 1.05)  # nang muc nuoc len de co khong gian kham pha lai
                n_kicks += 1
            no_improve_count = 0
            continue

        idx = rng.choices(range(len(operators)), weights=op_weights, k=1)[0]
        op = operators[idx]

        move = op(sol, class_ids, class_times, class_rooms, occ, class_to_hard_dist, day_multiplier, rng)
        if move is None:
            no_improve_count += 1
            continue

        kind = move[0]
        if kind == 'time_change':
            _, c, old_t, _ = move
            snapshot_before = {c: (old_t, sol[c]['r'])}
        elif kind == 'room_move':
            _, c, old_r, _ = move
            snapshot_before = {c: (sol[c]['t'], old_r)}
        else:
            _, c1, c2, old_t1, old_t2 = move
            snapshot_before = {c1: (old_t1, sol[c1]['r']), c2: (old_t2, sol[c2]['r'])}

        changed = list(snapshot_before.keys())
        affected_rows = get_affected_soft_rows(changed, class_to_soft_dist)

        cur_vals = {c: (sol[c]['t'], sol[c]['r']) for c in changed}
        for c in changed:
            sol[c]['t'], sol[c]['r'] = snapshot_before[c]
        before_pen = sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier)
        for c in changed:
            sol[c]['t'], sol[c]['r'] = cur_vals[c]
        after_pen = sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier)

        time_delta = sum(
            class_times[c][sol[c]['t']]['penalty'] - class_times[c][snapshot_before[c][0]]['penalty']
            for c in changed
        )
        room_delta = sum(
            (class_rooms[c][sol[c]['r']]['penalty'] if sol[c]['r'] is not None else 0) -
            (class_rooms[c][snapshot_before[c][1]]['penalty'] if snapshot_before[c][1] is not None else 0)
            for c in changed
        )
        dist_delta = after_pen - before_pen
        delta = w_time * time_delta + w_room * room_delta + w_dist * dist_delta
        new_obj = cur_obj + delta

        if new_obj <= level:
            _apply_occ_for_accepted_move(occ, move, sol, class_times, class_rooms, snapshot_before)
            cur_obj = new_obj
            if new_obj < best_obj - 1e-9:
                best_obj = new_obj
                best_sol = {c: dict(v) for c, v in sol.items()}
                op_weights[idx] = min(op_weights[idx] * 1.05, 10.0)
                no_improve_count = 0
            else:
                no_improve_count += 1
        else:
            _undo_move(sol, move)
            op_weights[idx] = max(op_weights[idx] * 0.98, 0.1)
            no_improve_count += 1

        level *= decay_rate

        if verbose_every and (it + 1) % verbose_every == 0:
            history.append((it + 1, cur_obj, best_obj, level, n_kicks))
            print(f'  Vong lap {it+1:6d} | cur={cur_obj:10.1f} | best={best_obj:10.1f} | '
                  f'level={level:10.1f} | so lan kick={n_kicks}')

    return best_sol, best_obj, history


if __name__ == '__main__':
    import sys, time
    sys.path.insert(0, '.')
    from parser_v2 import parse_itc_instance
    from stage1_solver import build_stage1_model
    from ortools.sat.python import cp_model

    df_rooms, df_classes, df_dist, class_times, class_rooms = parse_itc_instance(
        '/home/claude/itc2019/repo3/data/raw_data/wbg-fal10.xml'
    )
    class_ids = df_classes['class_id'].tolist()

    model, time_bool, room_bool, stats = build_stage1_model(df_classes, df_rooms, df_dist, class_times, class_rooms)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)
    print('Stage 1 status:', solver.StatusName(status))

    sol = extract_solution(solver, time_bool, room_bool, class_ids, class_times, class_rooms)
    obj = compute_objective(sol, class_times, class_rooms, df_dist)
    print('Soft Penalty ban dau (S0):', obj)

    t0 = time.time()
    best_sol, best_obj, history = run_stage2(
        sol, class_ids, class_times, class_rooms, df_dist,
        max_iterations=5000, verbose_every=1000, seed=0
    )
    dt = time.time() - t0
    print('Soft Penalty sau Stage 2:', best_obj, '(giam', round(obj['total'] - best_obj, 1), ')')
    print('Thoi gian chay 5000 vong lap:', round(dt, 2), 's ->', round(dt / 5000 * 1000, 3), 'ms/vong lap')

    # Kiem tra doi chieu: tinh lai objective TU DAU tren nghiem cuoi, phai KHOP voi best_obj (sai so lam tron)
    check = compute_objective(best_sol, class_times, class_rooms, df_dist)
    print('Doi chieu (tinh lai tu dau):', check['total'], '| Khop:', abs(check['total'] - best_obj) < 1e-6)
