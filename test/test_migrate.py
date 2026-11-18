"""Tests for bin/migrate_v2.py on a temp copy shaped like the real vault (flat OFIS/Isler → three job folders)."""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakes  # noqa: E402,F401 (isolates the job lock)
import migrate_v2  # noqa: E402


def note(status, extra=""):
    return (f"---\ntags: [ofis, is, blog]\nproje: blog\noturum: ofis-x\nkisa_id: a39b8aa2\ndurum: {status}\n"
            f"baslangic: 2026-11-10T16:22:00\n{extra}---\n\n# blog — x\n\n## Görev\nx\n\n## Sonuç\ny\n\n"
            "## İlgili Kararlar\n- [[OFIS/Kararlar/2026-11-10-blog-spike-devam]]\n\n"
            "## İlgili Sayfalar\n- [[OFIS/README]]\n")


NOTES = {
    "2026-11-10-162200-blog-spike.md": note("bitti"),
    "2026-11-10-183820-blog.md": note("bitti", "bitis: 2026-11-10\n"),
    "2026-11-10-201533-blog.md": note("calisiyor", "model: haiku\n"),
    "2026-11-10-201534-blog.md": note("baslatiliyor"),
    "2026-11-10-201535-blog-2.md": note("basarisiz"),
    "2026-11-10-201536-blog.md": note("tikandi"),
}
KARAR = ("---\nproje: blog\ndurum: cevaplandi\n---\n\n# x\n\n## İlgili Sayfalar\n"
         "- [[OFIS/Isler/2026-11-10-162200-blog-spike]]\n")
AKTIF = ("# Ofis — Aktif Durum\n\n## Son bitenler\n"
         "- 2026-11-10 · blog · Durum — [[OFIS/Isler/2026-11-10-183820-blog|iş notu]]\n"
         "- 2026-11-10 · blog · Spike — [[OFIS/Isler/2026-11-10-162200-blog-spike#Sonuç|iş notu]]\n"
         "- [[OFIS/README]] · [[OFIS/Kararlar/2026-11-10-blog-spike-devam]]\n")
LOG = ("# Log\n\n## [2026-11-10] ofis | blog — Durum\n- Detay: [[OFIS/Isler/2026-11-10-183820-blog]].\n\n"
       "## [2026-11-10] work | Başka — iş\n- Not: [[Baska/isler/X-1]] ve [[OFIS/README]].\n")
INDEX = "| [[OFIS/README]] | MOC |\n| `OFIS/Kararlar/`, `OFIS/Isler/` | Her iş ayrı not |\n"
OTHER = "Bu not ofisin dışında: [[OFIS/Isler/2026-11-10-183820-blog]]\n"


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = os.path.realpath(self.tmp.name)
        self.ofis = os.path.join(self.vault, "OFIS")
        files = {f"OFIS/Isler/{n}": t for n, t in NOTES.items()}
        files.update({"OFIS/Kararlar/2026-11-10-blog-spike-devam.md": KARAR,
                      "OFIS/04-Aktif-Durum/Index.md": AKTIF, "log.md": LOG, "index.md": INDEX,
                      "Diger/not.md": OTHER})
        for rel, text in files.items():
            self.write(rel, text)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.vault, rel), encoding="utf-8") as f:
            return f.read()

    def snapshot(self):
        out = {}
        for folder, _, names in os.walk(self.vault):
            for n in names:
                p = os.path.join(folder, n)
                with open(p, encoding="utf-8") as f:
                    out[os.path.relpath(p, self.vault)] = f.read()
        return out

    def run_migration(self, *extra):
        out = io.StringIO()
        code = migrate_v2.main(["migrate_v2.py", "--vault", self.ofis, *extra], out=out)
        return code, out.getvalue()

    def test_dry_run_changes_nothing_and_prints_the_plan(self):
        before = self.snapshot()
        code, out = self.run_migration("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Isler/2026-11-10-201533-blog.md -> Isler/Devam-Edenler/", out)
        self.assertIn("Isler/2026-11-10-183820-blog.md -> Isler/Bitenler/", out)
        self.assertIn("log.md", out)

    def test_notes_move_by_status_and_links_lose_the_folder_path(self):
        code, _ = self.run_migration()
        self.assertEqual(code, 0)
        isler = os.path.join(self.ofis, "Isler")
        self.assertEqual(sorted(os.listdir(os.path.join(isler, "Devam-Edenler"))),
                         ["2026-11-10-201533-blog.md", "2026-11-10-201534-blog.md"])
        self.assertEqual(sorted(os.listdir(os.path.join(isler, "Bitenler"))),
                         ["2026-11-10-162200-blog-spike.md", "2026-11-10-183820-blog.md",
                          "2026-11-10-201535-blog-2.md", "2026-11-10-201536-blog.md"])
        self.assertEqual(os.listdir(os.path.join(isler, "Siradakiler")), [])
        self.assertEqual(sorted(n for n in os.listdir(isler) if n.endswith(".md")), [])
        self.assertEqual(self.read("OFIS/Isler/Bitenler/2026-11-10-183820-blog.md"),
                         NOTES["2026-11-10-183820-blog.md"], "note content is unchanged")
        aktif = self.read("OFIS/04-Aktif-Durum/Index.md")
        self.assertIn("[[2026-11-10-183820-blog|iş notu]]", aktif)
        self.assertIn("[[2026-11-10-162200-blog-spike#Sonuç|iş notu]]", aktif)
        self.assertIn("[[OFIS/README]] · [[OFIS/Kararlar/2026-11-10-blog-spike-devam]]", aktif)
        self.assertIn("[[2026-11-10-162200-blog-spike]]",
                      self.read("OFIS/Kararlar/2026-11-10-blog-spike-devam.md"))
        self.assertEqual(self.read("log.md"), LOG.replace("[[OFIS/Isler/2026-11-10-183820-blog]]",
                                                          "[[2026-11-10-183820-blog]]"))
        self.assertEqual(self.read("index.md"), INDEX, "plain text mentions are not links")
        self.assertEqual(self.read("Diger/not.md"), OTHER, "only OFIS notes, log.md and index.md are rewritten")

    def test_second_run_is_a_no_op(self):
        self.run_migration()
        after = self.snapshot()
        code, out = self.run_migration()
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot(), after)
        self.assertIn("nothing to do", out)

    def test_existing_target_is_never_overwritten(self):
        self.write("OFIS/Isler/Bitenler/2026-11-10-183820-blog.md", "başka içerik")
        code, out = self.run_migration()
        self.assertEqual(code, 1)
        self.assertIn("exists", out)
        self.assertEqual(self.read("OFIS/Isler/Bitenler/2026-11-10-183820-blog.md"), "başka içerik")
        self.assertEqual(self.read("OFIS/Isler/2026-11-10-183820-blog.md"), NOTES["2026-11-10-183820-blog.md"])

    def test_symlinks_are_not_moved_or_rewritten(self):
        outside = os.path.join(self.vault, "Diger", "hedef.md")
        self.write("Diger/hedef.md", note("bitti"))
        os.symlink(outside, os.path.join(self.ofis, "Isler", "link.md"))
        self.run_migration()
        self.assertTrue(os.path.islink(os.path.join(self.ofis, "Isler", "link.md")))
        self.assertFalse(os.path.exists(os.path.join(self.ofis, "Isler", "Bitenler", "link.md")))

    def test_vault_must_be_an_ofis_folder(self):
        out = io.StringIO()
        self.assertEqual(migrate_v2.main(["migrate_v2.py", "--vault", os.path.join(self.vault, "yok")], out=out), 2)


if __name__ == "__main__":
    unittest.main()
