"""Tests for bin/notyolu.py: a bare [[note]] name -> its path under OFIS/ for an obsidian:// link (GET
/api/not-yolu). Temp vault only."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config, test/sahip_yasaklari.py)
import notyolu  # noqa: E402


class NotYoluTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "Obsidian Kasası")
        self.vault = os.path.join(self.root, "OFIS")
        os.makedirs(self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def note(self, rel, age=0):
        path = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        if age:
            t = time.time() - age
            os.utime(path, (t, t))
        return path

    def test_a_unique_name_resolves_to_its_path_relative_to_the_vault(self):
        self.note("Raporlar/giris.md")
        self.assertEqual(notyolu.bul(self.vault, "giris"), {"yol": "OFIS/Raporlar/giris", "kasa": "Obsidian Kasası"})
        self.assertEqual(notyolu.bul(self.vault, "giris.md")["yol"], "OFIS/Raporlar/giris")

    def test_turkish_letters_and_spaces_are_kept(self):
        self.note("Kararlar/Ağaç ölçümü ş.md")
        self.assertEqual(notyolu.bul(self.vault, "Ağaç ölçümü ş")["yol"], "OFIS/Kararlar/Ağaç ölçümü ş")

    def test_an_ambiguous_name_prefers_the_hinted_folder_else_the_newest(self):
        self.note("Ozetler/2026-11-13.md", age=600)
        self.note("Isler/Bitenler/2026-11-13.md", age=60)
        self.assertEqual(notyolu.bul(self.vault, "2026-11-13", "Ozetler")["yol"], "OFIS/Ozetler/2026-11-13")
        self.assertEqual(notyolu.bul(self.vault, "2026-11-13", "Isler")["yol"], "OFIS/Isler/Bitenler/2026-11-13")
        self.assertEqual(notyolu.bul(self.vault, "2026-11-13")["yol"], "OFIS/Isler/Bitenler/2026-11-13", "newest")
        self.assertEqual(notyolu.bul(self.vault, "2026-11-13", "Raporlar")["yol"], "OFIS/Isler/Bitenler/2026-11-13",
                         "a hint that matches nothing falls back to the newest")

    def test_names_that_are_paths_or_odd_are_refused(self):
        self.note("Raporlar/giris.md")
        for bad in ("", "../giris", "Raporlar/giris", "a\\b", ".gizli", "a\x00b", "x" * 300, None, 5, "a\nb",
                    "a[b", "a|b", "a#b"):
            with self.subTest(bad=bad):
                self.assertIsNone(notyolu.bul(self.vault, bad))
        self.assertIsNone(notyolu.bul(self.vault, "giris", "../x"), "a bad hint is refused too")

    def test_nothing_outside_ofis_and_no_private_folder(self):
        with open(os.path.join(self.root, "disarida.md"), "w") as f:
            f.write("x")
        self.assertIsNone(notyolu.bul(self.vault, "disarida"))
        self.note("Mektuplar/posta.md")
        self.note("SİGORTA/sigorta-notu.md")
        self.note("Projeler/zim-notlari.md")
        self.note(".obsidian/gizli.md")
        for name in ("posta", "sigorta-notu", "zim-notlari", "gizli"):
            with self.subTest(name=name):
                self.assertIsNone(notyolu.bul(self.vault, name))

    def test_a_symlink_is_never_followed(self):
        outside = os.path.join(self.root, "dis")
        os.makedirs(outside)
        with open(os.path.join(outside, "kacak.md"), "w") as f:
            f.write("x")
        os.symlink(outside, os.path.join(self.vault, "Baglanti"))
        os.symlink(os.path.join(outside, "kacak.md"), os.path.join(self.vault, "kacak2.md"))
        self.assertIsNone(notyolu.bul(self.vault, "kacak"))
        self.assertIsNone(notyolu.bul(self.vault, "kacak2"))

    def test_a_missing_vault_is_none(self):
        self.assertIsNone(notyolu.bul(os.path.join(self.vault, "yok"), "x"))


if __name__ == "__main__":
    unittest.main()
