from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase

from .realistic_planning_data import build_realistic_packs, fictional_names, read_pack


class RealisticPlanningDataTests(SimpleTestCase):
    def test_names_are_reproducible_unique_and_avoid_source_names(self):
        excluded = {"Trần Minh Khôi", "Nguyễn Văn A"}
        first = fictional_names(1000, excluded)
        self.assertEqual(first, fictional_names(1000, excluded))
        self.assertEqual(len(set(first)), 1000)
        self.assertFalse(set(first) & excluded)
        self.assertTrue(all(len(name.split()) >= 3 and not any(c.isdigit() for c in name) for name in first))

    def test_realistic_packs_keep_public_subjects_and_replace_all_personal_identities(self):
        source = Path(settings.BASE_DIR).parent / "samples" / "sgu_15_khoa"
        original = [read_pack(source / f"bo_{i:02d}") for i in (1, 2, 3)]
        real_names = {r["ho_ten"] for pack in original for r in pack["lecturers"]["GiangVien"]}
        profiles = {}
        for pack, expected, old in zip(build_realistic_packs(source), (240, 480, 960), original):
            _, _, _, _, rows, provenance = pack
            self.assertEqual(len(rows["courses"]["Khoa"]), 15)
            self.assertEqual(len(rows["courses"]["BuoiHocYeuCau"]), expected)
            self.assertEqual({r[0] for r in rows["courses"]["HocPhan"]}, {r["ma_mon_hoc"] for r in old["courses"]["HocPhan"]})
            for teacher in rows["lecturers"]["GiangVien"]:
                self.assertTrue(teacher[0].startswith("MPGV"))
                self.assertNotIn(teacher[1], real_names)
                self.assertNotIn("giả lập", teacher[1].lower())
                self.assertNotIn("test", teacher[1].lower())
                if teacher[0] in profiles:
                    self.assertEqual(profiles[teacher[0]], teacher)
                profiles[teacher[0]] = teacher
            self.assertEqual(len(provenance["source_files"]), 3)
