import unittest

from scheduling.validation import TeachingSession, conflicts_for_candidate, detect_conflicts


def session(session_id, *, weeks=frozenset({1}), day=2, start=1, periods=3,
            teacher=None, room=None, classes=frozenset(), group=None, semester=1):
    return TeachingSession(session_id, semester, group or session_id, day, start, periods,
                           frozenset(weeks), teacher, room, frozenset(classes))


class ScheduleValidationTests(unittest.TestCase):
    def test_overlapping_weeks_and_periods_report_all_shared_resources(self):
        first = session("a", weeks={2, 3}, teacher=10, room=20, classes={30}, group=40)
        second = session("b", weeks={3, 4}, teacher=10, room=20, classes={30}, group=40,
                         start=3)
        conflicts = conflicts_for_candidate(second, [first], 19)
        self.assertEqual({c.kind for c in conflicts},
                         {"GIANG_VIEN", "PHONG", "LOP_HANH_CHINH", "NHOM_HOC_PHAN"})
        self.assertTrue(all(c.weeks == frozenset({3}) for c in conflicts))

    def test_adjacent_periods_or_disjoint_weeks_are_allowed(self):
        first = session("a", weeks={1, 2}, teacher=10, room=20)
        adjacent = session("b", weeks={1}, teacher=10, room=20, start=4)
        other_week = session("c", weeks={3}, teacher=10, room=20)
        self.assertEqual(conflicts_for_candidate(adjacent, [first], 19), [])
        self.assertEqual(conflicts_for_candidate(other_week, [first], 19), [])

    def test_same_teacher_different_semester_is_allowed(self):
        self.assertEqual(detect_conflicts([
            session("a", teacher=10), session("b", teacher=10, semester=2)
        ], {1: 19, 2: 16}), [])

    def test_update_ignores_its_previous_record(self):
        old = session("a", teacher=10, room=20)
        new = session("a", teacher=10, room=20)
        self.assertEqual(conflicts_for_candidate(new, [old], 19), [])

    def test_rejects_week_outside_semester(self):
        with self.assertRaisesRegex(ValueError, "Tuần học"):
            conflicts_for_candidate(session("a", weeks={20}), [], 19)

    def test_rejects_period_overflow_and_empty_weeks(self):
        with self.assertRaisesRegex(ValueError, "vượt"):
            conflicts_for_candidate(session("a", start=12, periods=3), [], 19)
        with self.assertRaisesRegex(ValueError, "ít nhất"):
            conflicts_for_candidate(session("a", weeks=set()), [], 19)

    def test_duplicate_session_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Trùng mã"):
            detect_conflicts([session("a"), session("a")], {1: 19})


if __name__ == "__main__":
    unittest.main()
