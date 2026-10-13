"""Kiem tra lich day theo thu, tiet va tap tuan hoc.

Ham o day khong phu thuoc CSDL de co the dung chung cho sua tay, import va
kiem tra nghiem thuat toan. Cac thao tac ghi CSDL phai goi kiem tra trong
cung giao dich va khoa cac lich lien quan de tranh hai nguoi ghi dong thoi.
"""

from dataclasses import dataclass, field
from typing import Hashable, Iterable, Mapping


@dataclass(frozen=True)
class TeachingSession:
    session_id: Hashable
    semester_id: Hashable
    course_group_id: Hashable
    day: int
    start_period: int
    period_count: int
    weeks: frozenset[int]
    teacher_id: Hashable | None = None
    room_id: Hashable | None = None
    class_ids: frozenset[Hashable] = field(default_factory=frozenset)

    @property
    def end_period_exclusive(self) -> int:
        return self.start_period + self.period_count


@dataclass(frozen=True)
class ScheduleConflict:
    kind: str  # GIANG_VIEN, PHONG, LOP_HANH_CHINH, NHOM_HOC_PHAN
    first_session_id: Hashable
    second_session_id: Hashable
    weeks: frozenset[int]


def validate_session(session: TeachingSession, semester_weeks: int, *, max_period: int = 13) -> None:
    """Tu choi lich thieu tuan hoac vuot gioi han hoc ky/tiet hoc."""
    if not 1 <= semester_weeks <= 53:
        raise ValueError("Số tuần học kỳ phải từ 1 đến 53")
    if not 2 <= session.day <= 8:
        raise ValueError("Thứ phải từ 2 đến 8")
    if session.start_period < 1 or session.period_count < 1:
        raise ValueError("Tiết bắt đầu và số tiết phải dương")
    if session.end_period_exclusive > max_period + 1:
        raise ValueError("Buổi học vượt quá tiết cuối trong ngày")
    if not session.weeks:
        raise ValueError("Buổi học phải có ít nhất một tuần")
    if any(not isinstance(week, int) or isinstance(week, bool) or week < 1 or week > semester_weeks
           for week in session.weeks):
        raise ValueError("Tuần học nằm ngoài học kỳ")


def _shared_slot(first: TeachingSession, second: TeachingSession) -> frozenset[int]:
    if first.semester_id != second.semester_id or first.day != second.day:
        return frozenset()
    if first.start_period >= second.end_period_exclusive or second.start_period >= first.end_period_exclusive:
        return frozenset()
    return first.weeks & second.weeks


def conflicts_for_candidate(candidate: TeachingSession, existing: Iterable[TeachingSession],
                            semester_weeks: int, *, max_period: int = 13) -> list[ScheduleConflict]:
    """Tra tat ca xung dot; bo qua ban ghi cung ID de ho tro cap nhat."""
    validate_session(candidate, semester_weeks, max_period=max_period)
    result: list[ScheduleConflict] = []
    for other in existing:
        if other.session_id == candidate.session_id:
            continue
        shared_weeks = _shared_slot(candidate, other)
        if not shared_weeks:
            continue
        kinds: list[str] = []
        if candidate.teacher_id is not None and candidate.teacher_id == other.teacher_id:
            kinds.append("GIANG_VIEN")
        if candidate.room_id is not None and candidate.room_id == other.room_id:
            kinds.append("PHONG")
        if candidate.class_ids & other.class_ids:
            kinds.append("LOP_HANH_CHINH")
        if candidate.course_group_id == other.course_group_id:
            kinds.append("NHOM_HOC_PHAN")
        result.extend(ScheduleConflict(kind, candidate.session_id, other.session_id, shared_weeks)
                      for kind in kinds)
    return result


def detect_conflicts(sessions: Iterable[TeachingSession], semester_week_counts: Mapping[Hashable, int],
                     *, max_period: int = 13) -> list[ScheduleConflict]:
    """Kiem tra toan bo lich, moi cap buoi hoc chi xet mot lan."""
    seen: list[TeachingSession] = []
    seen_ids: set[Hashable] = set()
    result: list[ScheduleConflict] = []
    for session in sessions:
        if session.session_id in seen_ids:
            raise ValueError(f"Trùng mã buổi học {session.session_id}")
        if session.semester_id not in semester_week_counts:
            raise ValueError(f"Thiếu số tuần của học kỳ {session.semester_id}")
        result.extend(conflicts_for_candidate(session, seen, semester_week_counts[session.semester_id],
                                              max_period=max_period))
        seen.append(session)
        seen_ids.add(session.session_id)
    return result
