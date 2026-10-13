"""
Pha B - Stage 2 mo rong: them Teacher Preference Penalty + toan tu Lecturer-Reassign.
Sol dict gio co them key 'gv': index vao class_candidates[c] (giao vien dang gan).
CAC TOAN TU CU (Time-Change, Time-Swap) duoc viet lai de kiem tra THEM giao vien co ranh khong.
"""
import random
from collections import defaultdict
from stage1_solver import days_to_set, weeks_to_set, times_overlap, week_position, compute_day_multiplier, parse_dist_type
from stage2_solver import (
    _violates_distribution, get_affected_soft_rows, sum_violation_penalty,
    build_class_to_hard_dist, build_class_to_soft_dist,
)


def generate_teacher_preferences(df_teachers, seed=42):
    """Sinh nguyen vong khung gio synthetic cho moi giao vien: 'morning'(<144)/'afternoon'(144-216)/'evening'(>216).
    Slot 0-287 (5 phut/slot, 288 slot/ngay) - 144 = 12h trua, 216 = 18h toi."""
    rng = random.Random(seed)
    prefs = {}
    for tid in df_teachers['teacher_id']:
        prefs[tid] = rng.choice(['morning', 'afternoon', 'evening'])
    return prefs


def _period_of(start_slot):
    if start_slot < 144:
        return 'morning'
    elif start_slot < 216:
        return 'afternoon'
    return 'evening'


def teacher_pref_penalty(teacher_id, start_slot, teacher_prefs, penalty_value=15):
    if teacher_prefs.get(teacher_id) == _period_of(start_slot):
        return 0
    return penalty_value


def build_teacher_occupancy(sol, class_times, class_candidates):
    """dict (teacher_id, day) -> list (class_id, start, end, weeks_set)."""
    occ = defaultdict(list)
    for c, s in sol.items():
        tid = class_candidates[c][s['gv']]
        t = class_times[c][s['t']]
        wset = weeks_to_set(t['weeks'])
        for d in days_to_set(t['days']):
            occ[(tid, d)].append((c, t['start'], t['start'] + t['length'], wset))
    return occ


def teacher_free(occ, teacher_id, topt, exclude_class):
    wset = weeks_to_set(topt['weeks'])
    for d in days_to_set(topt['days']):
        for (c2, s2, e2, w2) in occ.get((teacher_id, d), []):
            if c2 == exclude_class:
                continue
            if wset & w2 and topt['start'] < e2 and s2 < topt['start'] + topt['length']:
                return False
    return True


def occ_remove_class(occ, c, key, topt):
    for d in days_to_set(topt['days']):
        occ[(key, d)] = [e for e in occ[(key, d)] if e[0] != c]


def occ_add_class(occ, c, key, topt):
    wset = weeks_to_set(topt['weeks'])
    for d in days_to_set(topt['days']):
        occ[(key, d)].append((c, topt['start'], topt['start'] + topt['length'], wset))


def compute_objective_b(sol, class_times, class_rooms, class_candidates, df_dist, teacher_prefs,
                         weights=(1, 1, 10, 1)):
    """weights = (w_time, w_room, w_dist, w_teacher_pref)."""
    w_time, w_room, w_dist, w_pref = weights
    time_penalty = sum(class_times[c][s['t']]['penalty'] for c, s in sol.items())
    room_penalty = sum(class_rooms[c][s['r']]['penalty'] for c, s in sol.items() if s['r'] is not None)

    pref_penalty = 0
    for c, s in sol.items():
        tid = class_candidates[c][s['gv']]
        start = class_times[c][s['t']]['start']
        pref_penalty += teacher_pref_penalty(tid, start, teacher_prefs)

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

    total = w_time * time_penalty + w_room * room_penalty + w_dist * dist_penalty + w_pref * pref_penalty
    return {'total': total, 'time_penalty': time_penalty, 'room_penalty': room_penalty,
            'dist_penalty': dist_penalty, 'teacher_pref_penalty': pref_penalty}


# ---------- Toan tu (co kiem tra CA phong LAN giao vien khi doi gio) ----------
def op_time_change_b(sol, class_ids, class_times, class_rooms, class_candidates,
                      room_occ, teacher_occ, class_to_hard_dist, day_multiplier, rng):
    candidates = [c for c in class_ids if len(class_times[c]) > 1]
    if not candidates:
        return None
    c = rng.choice(candidates)
    old_t = sol[c]['t']
    choices = [i for i in range(len(class_times[c])) if i != old_t]
    rng.shuffle(choices)
    room_id = class_rooms[c][sol[c]['r']]['room_id'] if sol[c]['r'] is not None else None
    tid = class_candidates[c][sol[c]['gv']]
    for new_t in choices:
        new_topt = class_times[c][new_t]
        if room_id is not None and not room_free_check(room_occ, room_id, new_topt, c):
            continue
        if not teacher_free(teacher_occ, tid, new_topt, c):
            continue
        sol[c]['t'] = new_t
        if hard_dist_ok_b(class_to_hard_dist, c, sol, class_times, class_rooms, day_multiplier):
            return ('time_change', c, old_t, new_t)
        sol[c]['t'] = old_t
    return None


def room_free_check(occ, room_id, topt, exclude_class):
    wset = weeks_to_set(topt['weeks'])
    for d in days_to_set(topt['days']):
        for (c2, s2, e2, w2) in occ.get((room_id, d), []):
            if c2 == exclude_class:
                continue
            if wset & w2 and topt['start'] < e2 and s2 < topt['start'] + topt['length']:
                return False
    return True


def hard_dist_ok_b(class_to_hard_dist, changed_class, sol, class_times, class_rooms, day_multiplier):
    for base_type, params, cls_group in class_to_hard_dist.get(changed_class, []):
        if _violates_distribution(base_type, params, cls_group, sol, class_times, class_rooms, day_multiplier):
            return False
    return True


def op_room_move_b(sol, class_ids, class_times, class_rooms, class_candidates,
                    room_occ, teacher_occ, class_to_hard_dist, day_multiplier, rng):
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
        if room_free_check(room_occ, room_id, topt, c):
            sol[c]['r'] = new_r
            return ('room_move', c, old_r, new_r)
    return None


def op_lecturer_reassign(sol, class_ids, class_times, class_rooms, class_candidates,
                          room_occ, teacher_occ, class_to_hard_dist, day_multiplier, rng):
    """Toan tu MOI: doi giao vien dang day 1 lop sang 1 giao vien khac cung kha di, khong doi gio/phong."""
    candidates = [c for c in class_ids if len(class_candidates[c]) > 1]
    if not candidates:
        return None
    c = rng.choice(candidates)
    old_gv = sol[c]['gv']
    choices = [i for i in range(len(class_candidates[c])) if i != old_gv]
    rng.shuffle(choices)
    topt = class_times[c][sol[c]['t']]
    for new_gv in choices:
        tid = class_candidates[c][new_gv]
        if teacher_free(teacher_occ, tid, topt, c):
            sol[c]['gv'] = new_gv
            return ('lecturer_reassign', c, old_gv, new_gv)
    return None


def _undo_move_b(sol, move):
    kind = move[0]
    if kind == 'time_change':
        _, c, old_t, _ = move
        sol[c]['t'] = old_t
    elif kind == 'room_move':
        _, c, old_r, _ = move
        sol[c]['r'] = old_r
    elif kind == 'lecturer_reassign':
        _, c, old_gv, _ = move
        sol[c]['gv'] = old_gv


def run_stage2_b(sol0, class_ids, class_times, class_rooms, class_candidates, df_dist, teacher_prefs,
                  weights=(1, 1, 10, 1), max_iterations=20000,
                  initial_level_factor=1.2, decay_rate=0.9998, seed=42,
                  verbose_every=2000, stagnation_limit=3000, kick_size=15):
    rng = random.Random(seed)
    day_multiplier = compute_day_multiplier(class_times)
    class_ids_set = set(class_ids)
    class_to_hard_dist = build_class_to_hard_dist(df_dist, class_ids_set)
    class_to_soft_dist = build_class_to_soft_dist(df_dist, class_ids_set)  # xay 1 LAN duy nhat, khong lap lai moi vong

    sol = {c: dict(v) for c, v in sol0.items()}
    room_occ = defaultdict(list)
    for c, s in sol.items():
        if s['r'] is not None:
            t = class_times[c][s['t']]
            occ_add_class(room_occ, c, class_rooms[c][s['r']]['room_id'], t)
    teacher_occ = build_teacher_occupancy(sol, class_times, class_candidates)

    obj0 = compute_objective_b(sol, class_times, class_rooms, class_candidates, df_dist, teacher_prefs, weights)
    best_sol = {c: dict(v) for c, v in sol.items()}
    best_obj = obj0['total']
    cur_obj = obj0['total']
    level = cur_obj * initial_level_factor
    w_time, w_room, w_dist, w_pref = weights

    operators = [op_time_change_b, op_room_move_b, op_lecturer_reassign]
    op_names = ['time_change', 'room_move', 'lecturer_reassign']
    op_weights = [1.0, 1.0, 1.0]
    op_attempts = [0, 0, 0]  # so lan GOI toan tu
    op_found = [0, 0, 0]     # so lan toan tu TIM DUOC 1 buoc di hop le (khong tinh accept/reject)
    op_accepted = [0, 0, 0]  # so lan buoc di duoc CHAP NHAN (duoi muc nuoc)
    history = []
    no_improve = 0

    for it in range(max_iterations):
        if no_improve >= stagnation_limit:
            targets = rng.sample(class_ids, min(kick_size, len(class_ids)))
            for c in targets:
                if len(class_candidates[c]) > 1 and rng.random() < 0.5:
                    old_gv = sol[c]['gv']
                    for new_gv in rng.sample(range(len(class_candidates[c])), len(class_candidates[c])):
                        if new_gv == old_gv:
                            continue
                        tid = class_candidates[c][new_gv]
                        topt = class_times[c][sol[c]['t']]
                        if teacher_free(teacher_occ, tid, topt, c):
                            occ_remove_class(teacher_occ, c, class_candidates[c][old_gv], topt)
                            sol[c]['gv'] = new_gv
                            occ_add_class(teacher_occ, c, tid, topt)
                            break
            cur_obj = compute_objective_b(sol, class_times, class_rooms, class_candidates, df_dist, teacher_prefs, weights)['total']
            level = max(level, cur_obj * 1.05)
            no_improve = 0
            continue

        idx = rng.choices(range(len(operators)), weights=op_weights, k=1)[0]
        op_attempts[idx] += 1
        move = operators[idx](sol, class_ids, class_times, class_rooms, class_candidates,
                               room_occ, teacher_occ, class_to_hard_dist, day_multiplier, rng)
        if move is None:
            no_improve += 1
            continue
        op_found[idx] += 1

        kind, c = move[0], move[1]
        old_val = move[2]
        new_val = move[3]

        old_state = dict(sol[c])
        if kind == 'time_change':
            old_state['t'] = old_val
        elif kind == 'room_move':
            old_state['r'] = old_val
        elif kind == 'lecturer_reassign':
            old_state['gv'] = old_val

        cur_val_state = dict(sol[c])
        sol[c] = dict(old_state)
        time_penalty_before = class_times[c][sol[c]['t']]['penalty']
        room_penalty_before = class_rooms[c][sol[c]['r']]['penalty'] if sol[c]['r'] is not None else 0
        tid_before = class_candidates[c][sol[c]['gv']]
        start_before = class_times[c][sol[c]['t']]['start']
        pref_before = teacher_pref_penalty(tid_before, start_before, teacher_prefs)
        affected_rows = get_affected_soft_rows([c], class_to_soft_dist) if w_dist else {}
        before_dist = sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier) if affected_rows else 0

        sol[c] = dict(cur_val_state)
        time_penalty_after = class_times[c][sol[c]['t']]['penalty']
        room_penalty_after = class_rooms[c][sol[c]['r']]['penalty'] if sol[c]['r'] is not None else 0
        tid_after = class_candidates[c][sol[c]['gv']]
        start_after = class_times[c][sol[c]['t']]['start']
        pref_after = teacher_pref_penalty(tid_after, start_after, teacher_prefs)
        after_dist = sum_violation_penalty(affected_rows, sol, class_times, class_rooms, day_multiplier) if affected_rows else 0

        delta = (w_time * (time_penalty_after - time_penalty_before) +
                 w_room * (room_penalty_after - room_penalty_before) +
                 w_dist * (after_dist - before_dist) +
                 w_pref * (pref_after - pref_before))
        new_obj = cur_obj + delta

        if new_obj <= level:
            op_accepted[idx] += 1
            if kind == 'time_change':
                room_id = class_rooms[c][sol[c]['r']]['room_id'] if sol[c]['r'] is not None else None
                if room_id is not None:
                    occ_remove_class(room_occ, c, room_id, class_times[c][old_val])
                    occ_add_class(room_occ, c, room_id, class_times[c][new_val])
                occ_remove_class(teacher_occ, c, tid_before, class_times[c][old_val])
                occ_add_class(teacher_occ, c, tid_before, class_times[c][new_val])
            elif kind == 'room_move':
                topt = class_times[c][sol[c]['t']]
                occ_remove_class(room_occ, c, class_rooms[c][old_val]['room_id'], topt)
                occ_add_class(room_occ, c, class_rooms[c][new_val]['room_id'], topt)
            elif kind == 'lecturer_reassign':
                topt = class_times[c][sol[c]['t']]
                occ_remove_class(teacher_occ, c, class_candidates[c][old_val], topt)
                occ_add_class(teacher_occ, c, class_candidates[c][new_val], topt)

            cur_obj = new_obj
            if new_obj < best_obj - 1e-9:
                best_obj = new_obj
                best_sol = {cc: dict(v) for cc, v in sol.items()}
                op_weights[idx] = min(op_weights[idx] * 1.05, 10.0)
                no_improve = 0
            else:
                no_improve += 1
        else:
            _undo_move_b(sol, move)
            op_weights[idx] = max(op_weights[idx] * 0.98, 0.1)
            no_improve += 1

        level *= decay_rate
        if verbose_every and (it + 1) % verbose_every == 0:
            history.append((it + 1, cur_obj, best_obj, level))
            print(f'  Vong lap {it+1:6d} | cur={cur_obj:10.1f} | best={best_obj:10.1f} | level={level:10.1f}')
            for name, att, fnd, acc in zip(op_names, op_attempts, op_found, op_accepted):
                print(f'      {name:18s}: goi={att:6d} | tim_duoc={fnd:6d} | chap_nhan={acc:6d}')

    return best_sol, best_obj, history