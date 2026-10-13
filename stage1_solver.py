"""
Stage 1 - CP-SAT Solver (Pha A: Time + Room + Distribution, khong Student Sectioning, khong Teacher)
Tu dong chon chien luoc theo quy mo instance:
  - Chien luoc A: nhanh hon, dung khi tong so to hop (gio x phong) con nho.
  - Chien luoc B: tiet kiem bo nho, dung khi tong so to hop qua lon (tranh MemoryError).
"""

from collections import defaultdict
from ortools.sat.python import cp_model


def days_to_set(days_str):
    return frozenset(i for i, ch in enumerate(days_str) if ch == '1')


def weeks_to_set(weeks_str):
    return frozenset(i for i, ch in enumerate(weeks_str) if ch == '1')


def compute_day_multiplier(class_times):
    """Tinh he so nhan ngay an toan tu chinh du lieu (khong can biet truoc slotsPerDay),
    dam bao du lon de moi ngay khong bao gio 'lan' sang vi tri cua ngay ke tiep khi quy doi
    (ngay, gio) thanh 1 gia tri thu tu duy nhat trong tuan, phuc vu so sanh Precedence dung dan."""
    max_end = 0
    for topts in class_times.values():
        for t in topts:
            max_end = max(max_end, t['start'] + t['length'])
    return max_end + 1


def week_position(topt, day_multiplier):
    """Vi tri thu tu (ngay, gio) trong tuan - dung ngay SOM NHAT trong days-bitmask lam moc,
    de so sanh Precedence dung ca ngay lan gio, khong chi rieng gio-trong-ngay."""
    d = min(days_to_set(topt['days']))
    return d * day_multiplier + topt['start']


def parse_dist_type(type_str):
    """Tach ten loai rang buoc goc va cac tham so so hoc di kem (neu co).
    Vi du: 'WorkDay(120)' -> ('WorkDay', (120,)); 'MaxBlock(48,10)' -> ('MaxBlock', (48, 10));
    'SameAttendees' -> ('SameAttendees', ())."""
    if '(' in type_str:
        base, rest = type_str.split('(', 1)
        params = tuple(int(x) for x in rest.rstrip(')').split(','))
        return base, params
    return type_str, ()


def times_overlap(t1, t2):
    if not (days_to_set(t1['days']) & days_to_set(t2['days'])):
        return False
    if not (weeks_to_set(t1['weeks']) & weeks_to_set(t2['weeks'])):
        return False
    s1, e1 = t1['start'], t1['start'] + t1['length']
    s2, e2 = t2['start'], t2['start'] + t2['length']
    return s1 < e2 and s2 < e1


def add_distribution_constraints(model, df_dist, class_ids_set, class_times, class_rooms,
                                  time_bool, room_bool, day_multiplier=None):
    if day_multiplier is None:
        day_multiplier = compute_day_multiplier(class_times)

    # Loai phan ra duoc theo tung cap lop (pairwise)
    pairwise_types = {'SameTime', 'SameDays', 'SameRoom', 'SameWeeks',
                       'NotOverlap', 'SameAttendees', 'DifferentDays', 'Precedence',
                       'MinGap', 'WorkDay'}
    # Loai bat buoc phai xet CA NHOM cung luc, khong the phan ra theo cap
    group_types = {'MaxDays', 'MaxDayLoad'}
    # Loai xap xi bang pairwise (dieu kien CAN nhung chua chac DU - xem ghi chu trong code)
    approx_types = {'MaxBlock'}

    n_dist_constraints = 0
    skipped_types = set()

    for _, row in df_dist.iterrows():
        if row['required'] != 'true':
            continue
        dtype_raw = row['type']
        base_type, params = parse_dist_type(dtype_raw)
        cls_group = [cid for cid in row['class_ids'] if cid in class_ids_set]
        if len(cls_group) < 2:
            continue

        if base_type in pairwise_types or base_type in approx_types:
            for a in range(len(cls_group)):
                for b in range(a + 1, len(cls_group)):
                    c1, c2 = cls_group[a], cls_group[b]
                    for i1, t1 in enumerate(class_times[c1]):
                        for i2, t2 in enumerate(class_times[c2]):
                            forbid = False
                            if base_type in ('NotOverlap', 'SameAttendees'):
                                forbid = times_overlap(t1, t2)
                            elif base_type == 'SameTime':
                                forbid = not (t1['start'] == t2['start'] and t1['length'] == t2['length'])
                            elif base_type == 'SameDays':
                                forbid = days_to_set(t1['days']) != days_to_set(t2['days'])
                            elif base_type == 'SameWeeks':
                                forbid = weeks_to_set(t1['weeks']) != weeks_to_set(t2['weeks'])
                            elif base_type == 'DifferentDays':
                                forbid = bool(days_to_set(t1['days']) & days_to_set(t2['days']))
                            elif base_type == 'Precedence':
                                pos1_end = week_position(t1, day_multiplier) + t1['length']
                                pos2_start = week_position(t2, day_multiplier)
                                forbid = not (pos1_end <= pos2_start)
                            elif base_type == 'MinGap':
                                g = params[0] if params else 0
                                if days_to_set(t1['days']) & days_to_set(t2['days']) and \
                                   weeks_to_set(t1['weeks']) & weeks_to_set(t2['weeks']):
                                    gap = max(t2['start'] - (t1['start'] + t1['length']),
                                              t1['start'] - (t2['start'] + t2['length']))
                                    forbid = gap < g
                            elif base_type == 'WorkDay':
                                s = params[0] if params else 10 ** 9
                                if days_to_set(t1['days']) & days_to_set(t2['days']) and \
                                   weeks_to_set(t1['weeks']) & weeks_to_set(t2['weeks']):
                                    span = max(t1['start'] + t1['length'], t2['start'] + t2['length']) - \
                                           min(t1['start'], t2['start'])
                                    forbid = span > s
                            elif base_type == 'MaxBlock':
                                # XAP XI: day la dieu kien CAN (khong DU) cho toan nhom, vi ban than
                                # loai nay theo tai lieu chinh thuc "khong the bieu dien day du chi
                                # bang rang buoc theo cap" (Muller et al.) - chi bat duoc vi pham
                                # giua TUNG CAP lop lien ke, chua bat het truong hop chuoi 3+ lop noi tiep.
                                m, s = (params + (10 ** 9, 10 ** 9))[:2]
                                if days_to_set(t1['days']) & days_to_set(t2['days']) and \
                                   weeks_to_set(t1['weeks']) & weeks_to_set(t2['weeks']):
                                    gap = max(t2['start'] - (t1['start'] + t1['length']),
                                              t1['start'] - (t2['start'] + t2['length']))
                                    if gap <= s:  # cung 1 "khoi" (block)
                                        span = max(t1['start'] + t1['length'], t2['start'] + t2['length']) - \
                                               min(t1['start'], t2['start'])
                                        forbid = span > m

                            if forbid:
                                model.Add(time_bool[(c1, i1)] + time_bool[(c2, i2)] <= 1)
                                n_dist_constraints += 1

                    if base_type == 'SameRoom':
                        for i1, ro1 in enumerate(class_rooms[c1]):
                            for i2, ro2 in enumerate(class_rooms[c2]):
                                if ro1['room_id'] != ro2['room_id']:
                                    model.Add(room_bool[(c1, i1)] + room_bool[(c2, i2)] <= 1)
                                    n_dist_constraints += 1

        elif base_type in group_types:
            # meets_on_day[c,d]: co lop c nao trong nhom hoc vao ngay d hay khong (theo lua chon dang xet)
            meets_group = {}
            for c in cls_group:
                for d in range(7):
                    relevant = [time_bool[(c, ti)] for ti, topt in enumerate(class_times[c])
                                if d in days_to_set(topt['days'])]
                    if relevant:
                        meets_group[(c, d)] = relevant

            if base_type == 'MaxDays':
                D = params[0] if params else 7
                uses_day = []
                for d in range(7):
                    relevant_all = [v for c in cls_group for v in meets_group.get((c, d), [])]
                    if not relevant_all:
                        continue
                    ud = model.NewBoolVar(f'usesday_{id(row)}_{d}')
                    for v in relevant_all:
                        model.Add(ud >= v)
                    uses_day.append(ud)
                if uses_day:
                    model.Add(sum(uses_day) <= D)
                    n_dist_constraints += 1

            elif base_type == 'MaxDayLoad':
                S = params[0] if params else 10 ** 9
                for d in range(7):
                    terms = []
                    for c in cls_group:
                        for ti, topt in enumerate(class_times[c]):
                            if d in days_to_set(topt['days']):
                                terms.append((time_bool[(c, ti)], topt['length']))
                    if terms:
                        model.Add(sum(v * w for v, w in terms) <= S)
                        n_dist_constraints += 1

        else:
            skipped_types.add(dtype_raw)

    return n_dist_constraints, skipped_types


def build_stage1_model(df_classes, df_rooms, df_dist, class_times, class_rooms,
                        min_gap_default=0, combo_threshold=300_000):
    model = cp_model.CpModel()
    class_ids = df_classes['class_id'].tolist()
    class_ids_set = set(class_ids)
    class_limit = df_classes.set_index('class_id')['limit'].to_dict()
    room_capacity = df_rooms.set_index('room_id')['capacity'].to_dict()

    total_combo = sum(len(class_times[c]) * len(class_rooms[c]) for c in class_ids)
    strategy = 'A' if total_combo <= combo_threshold else 'B'

    time_bool, room_bool = {}, {}
    for c in class_ids:
        vt = [model.NewBoolVar(f't_{c}_{i}') for i in range(len(class_times[c]))]
        model.AddExactlyOne(vt)
        for i, v in enumerate(vt):
            time_bool[(c, i)] = v

        # LUU Y: mot so lop KHONG CAN gan phong (n_possible_rooms == 0) - day la truong hop
        # hop le theo dung luat ITC 2019 (vd lop online/tu hoc), khong phai loi du lieu.
        # Chi tao rang buoc "chon dung 1 phong" khi lop THUC SU co it nhat 1 lua chon phong.
        vr = [model.NewBoolVar(f'r_{c}_{i}') for i in range(len(class_rooms[c]))]
        if vr:
            model.AddExactlyOne(vr)
        for i, v in enumerate(vr):
            room_bool[(c, i)] = v

    # LUU Y: KHONG ep sac chua phong >= si so lam rang buoc CUNG.
    # Theo dung luat ITC 2019 (itc2019.org/format), cuoc thi dam bao luon ton tai nghiem
    # kha thi tu chinh danh sach phong/gio kha di cua moi lop - "phong qua nho" la mot dang
    # RANG BUOC MEM, da duoc phan anh san qua gia tri 'penalty' cua tung lua chon phong
    # trong du lieu goc. Stage 2 se toi uu phan penalty nay, Stage 1 chi can dam bao kha thi.

    day_room_buckets = defaultdict(list)

    if strategy == 'A':
        # day_room_buckets[(room_id, d)] chua danh sach (presence, start, end, weeks_set, class_id)
        for c in class_ids:
            n_t, n_r = len(class_times[c]), len(class_rooms[c])
            for ti, topt in enumerate(class_times[c]):
                for ri, ropt in enumerate(class_rooms[c]):
                    if n_t == 1 and n_r == 1:
                        presence = None
                    elif n_t == 1:
                        presence = room_bool[(c, ri)]
                    elif n_r == 1:
                        presence = time_bool[(c, ti)]
                    else:
                        presence = model.NewBoolVar(f'p_{c}_{ti}_{ri}')
                        model.AddBoolAnd([time_bool[(c, ti)], room_bool[(c, ri)]]).OnlyEnforceIf(presence)
                        model.AddBoolOr(
                            [time_bool[(c, ti)].Not(), room_bool[(c, ri)].Not()]
                        ).OnlyEnforceIf(presence.Not())

                    start, length = topt['start'], topt['length']
                    wset = weeks_to_set(topt['weeks'])
                    for d in days_to_set(topt['days']):
                        day_room_buckets[(ropt['room_id'], d)].append(
                            (presence, start, start + length, wset, c)
                        )

        # Trong tung bucket (phong, ngay): CHI cam 2 muc chiem dung cua 2 LOP KHAC NHAU
        # neu chung giao nhau ca ve tuan (weeks) LAN ve khung gio - dung AddNoOverlap toan bucket
        # se sai neu co cap lop khac tuan (vd xen ke tuan chan/le) dung chung phong/gio.
        for (room_id, d), items in day_room_buckets.items():
            n = len(items)
            for a in range(n):
                p1, s1, e1, w1, c1 = items[a]
                for b in range(a + 1, n):
                    p2, s2, e2, w2, c2 = items[b]
                    if c1 == c2:
                        continue
                    if not (w1 & w2):
                        continue  # khac tuan hoan toan -> khong xung dot, cho phep dung chung
                    if s1 < e2 and s2 < e1:  # trung khung gio
                        if p1 is None and p2 is None:
                            # ca 2 la lua chon duy nhat cua ca 2 lop -> mau thuan that su
                            model.AddBoolOr([])  # ep INFEASIBLE co chu dich, se duoc bao ro
                        elif p1 is None:
                            model.Add(p2 == 0)
                        elif p2 is None:
                            model.Add(p1 == 0)
                        else:
                            model.Add(p1 + p2 <= 1)

    else:  # strategy == 'B'
        start_var, size_var, end_var_map, meets_on_day = {}, {}, {}, {}
        for c in class_ids:
            starts = [t['start'] for t in class_times[c]]
            lengths = [t['length'] for t in class_times[c]]
            sv = model.NewIntVar(min(starts), max(starts), f'start_{c}')
            zv = model.NewIntVar(min(lengths), max(lengths), f'size_{c}')
            ev = model.NewIntVar(
                min(s + l for s, l in zip(starts, lengths)),
                max(s + l for s, l in zip(starts, lengths)),
                f'end_{c}'
            )
            for ti, topt in enumerate(class_times[c]):
                model.Add(sv == topt['start']).OnlyEnforceIf(time_bool[(c, ti)])
                model.Add(zv == topt['length']).OnlyEnforceIf(time_bool[(c, ti)])
            model.Add(ev == sv + zv)
            start_var[c], size_var[c], end_var_map[c] = sv, zv, ev

            for d in range(7):
                relevant = [
                    time_bool[(c, ti)] for ti, topt in enumerate(class_times[c])
                    if d in days_to_set(topt['days'])
                ]
                if not relevant:
                    continue
                mv = model.NewBoolVar(f'meets_{c}_{d}')
                model.Add(mv == sum(relevant))
                meets_on_day[(c, d)] = mv

        for c in class_ids:
            for ri, ropt in enumerate(class_rooms[c]):
                for d in range(7):
                    if (c, d) not in meets_on_day:
                        continue
                    presence = model.NewBoolVar(f'p_{c}_{ri}_{d}')
                    model.AddBoolAnd(
                        [room_bool[(c, ri)], meets_on_day[(c, d)]]
                    ).OnlyEnforceIf(presence)
                    model.AddBoolOr(
                        [room_bool[(c, ri)].Not(), meets_on_day[(c, d)].Not()]
                    ).OnlyEnforceIf(presence.Not())
                    interval = model.NewOptionalIntervalVar(
                        start=start_var[c], size=size_var[c], end=end_var_map[c],
                        is_present=presence, name=f'iv_{c}_{ri}_{d}'
                    )
                    day_room_buckets[(ropt['room_id'], d)].append(interval)

    if strategy == 'B':
        for (room_id, d), intervals in day_room_buckets.items():
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)

    n_dist_constraints, skipped_types = add_distribution_constraints(
        model, df_dist, class_ids_set, class_times, class_rooms, time_bool, room_bool
    )

    stats = {
        'strategy': strategy,
        'total_combo': total_combo,
        'n_day_room_buckets': len(day_room_buckets),
        'n_dist_constraints': n_dist_constraints,
        'skipped_types': skipped_types,
    }
    return model, time_bool, room_bool, stats
