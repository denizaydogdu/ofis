"""Tests for bin/jobs.py: job notes in OFIS/Isler/{Siradakiler,Devam-Edenler,Bitenler}. Temp vault only."""
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakes  # noqa: E402,F401 (isolates the job lock)
import jobs  # noqa: E402

NOW = datetime(2026, 11, 10, 18, 38, 20)


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = os.path.join(os.path.realpath(self.tmp.name), "OFIS")
        os.makedirs(self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **kw):
        args = {"project": "blog", "title": "Durum özeti", "task": "Durum özeti.\nDal ve commitler.",
                "fields": {"katman": "genel", "model": "sonnet", "butce_usd": "3"}, "now": NOW}
        args.update(kw)
        return jobs.create(self.vault, **args)

    def folder(self, name):
        return os.path.join(self.vault, "Isler", name)

    def read(self, job):
        with open(job.path, encoding="utf-8") as f:
            return f.read()

    # --- create ---

    def test_create_writes_note_in_siradakiler_with_fields_and_sections(self):
        job = self.create()
        self.assertEqual(job.name, "2026-11-10-183820-blog.md")
        self.assertEqual(job.folder, jobs.QUEUED)
        self.assertEqual(os.path.dirname(job.path), self.folder("Siradakiler"))
        text = self.read(job)
        for expected in ("proje: blog", "baslik: Durum özeti", "durum: sirada", "katman: genel",
                         "yurutucu: claude", "model: sonnet", "butce_usd: 3", "olusturuldu: 2026-11-10T18:38:20",
                         "# blog — Durum özeti", "## Görev\n\nDurum özeti.\nDal ve commitler.",
                         "## Sonuç", "## İlgili Kararlar", "## İlgili Sayfalar\n- [[OFIS/README]]"):
            self.assertIn(expected, text)
        self.assertEqual(job.meta["durum"], "sirada")

    def test_create_never_overwrites_and_names_are_unique_across_folders(self):
        first = self.create()
        jobs.update(self.vault, first.name, status="calisiyor")  # now in Devam-Edenler
        second = self.create()
        third = self.create()
        self.assertEqual(len({first.name, second.name, third.name}), 3)
        self.assertEqual(second.name, "2026-11-10-183820-blog-2.md")

    def test_values_are_single_line_and_quoted_when_needed(self):
        job = self.create(title="Durum: özet\nikinci satır")
        text = self.read(job)
        self.assertIn('baslik: "Durum: özet ikinci satır"', text)
        self.assertEqual(jobs.load(self.vault, job.name).meta["baslik"], "Durum: özet ikinci satır")

    def test_a_kontrol_with_double_quotes_round_trips(self):
        # B3 audit: the note showed `test '$(git status …)' = 1` for a command written with double quotes
        for value in ('test "$(git status --porcelain | wc -l)" = 1', 'grep -q "a b" x && echo \'ok\'',
                      "it's: fine", '"quoted"', "plain"):
            job = self.create(fields={"kontrol": value})
            self.assertEqual(jobs.load(self.vault, job.name).meta["kontrol"], value)

    def test_invalid_field_names_are_refused(self):
        with self.assertRaises(jobs.JobError):
            self.create(fields={"durum\nx": "y"})

    # --- find / load ---

    def test_find_and_load_by_name_with_or_without_extension(self):
        job = self.create()
        self.assertEqual(jobs.load(self.vault, job.name).path, job.path)
        self.assertEqual(jobs.load(self.vault, job.name[:-3]).path, job.path)

    def test_unsafe_names_are_refused(self):
        self.create()
        for bad in ("../x.md", "a/b.md", "a\\b.md", ".gizli.md", "..md", "", None, "x" * 300, "a.md\x00"):
            with self.subTest(bad=bad):
                with self.assertRaises(jobs.JobError):
                    jobs.load(self.vault, bad)

    def test_symlink_out_of_folder_is_not_a_job(self):
        outside = os.path.join(self.tmp.name, "outside.md")
        with open(outside, "w") as f:
            f.write("---\ndurum: calisiyor\n---\n")
        os.makedirs(self.folder("Devam-Edenler"))
        os.symlink(outside, os.path.join(self.folder("Devam-Edenler"), "link.md"))
        with self.assertRaises(jobs.JobError):
            jobs.load(self.vault, "link.md")
        self.assertEqual(jobs.list_jobs(self.vault), [])

    def test_find_by_session(self):
        job = self.create()
        jobs.update(self.vault, job.name, status="calisiyor", fields={"oturum": "ofis-blog-1110-183820-ab12"})
        found = jobs.find_by_session(self.vault, "ofis-blog-1110-183820-ab12")
        self.assertEqual(found.name, job.name)
        self.assertIsNone(jobs.find_by_session(self.vault, "ofis-yok"))

    # --- status changes move the file ---

    def test_status_change_moves_the_file_and_keeps_its_name(self):
        job = self.create()
        moved = jobs.update(self.vault, job.name, status="calisiyor", fields={"kisa_id": "abc12345"})
        self.assertEqual(moved.path, os.path.join(self.folder("Devam-Edenler"), job.name))
        self.assertFalse(os.path.exists(job.path))
        self.assertIn("kisa_id: abc12345", self.read(moved))
        done = jobs.update(self.vault, job.name, status="bitti", fields={"bitis": "2026-11-10T19:00:00"})
        self.assertEqual(done.folder, jobs.DONE)
        self.assertEqual(os.listdir(self.folder("Devam-Edenler")), [])

    def test_every_status_has_a_folder(self):
        for status, folder in (("sirada", "Siradakiler"), ("baslatiliyor", "Devam-Edenler"),
                               ("calisiyor", "Devam-Edenler"), ("karar-bekliyor", "Devam-Edenler"),
                               ("incelemede", "Devam-Edenler"), ("bitti", "Bitenler"), ("tikandi", "Bitenler"),
                               ("iptal", "Bitenler"), ("basarisiz", "Bitenler")):
            self.assertEqual(jobs.folder_for(status), folder)
        with self.assertRaises(jobs.JobError):
            jobs.folder_for("uyuyor")

    def test_kontrolde_is_an_active_status(self):
        self.assertEqual(jobs.folder_for("kontrolde"), "Devam-Edenler")
        self.assertIn("kontrolde", jobs.ACTIVE_STATUSES)

    def test_reaching_a_final_status_marks_the_scorecard_row_pending_once(self):
        job = self.create()
        running = jobs.update(self.vault, job.name, status="calisiyor")
        self.assertNotIn("karne", running.meta)
        stuck = jobs.update(self.vault, job.name, status="tikandi")
        self.assertEqual(stuck.meta["karne"], "bekliyor")
        jobs.update(self.vault, job.name, fields={"karne": "yazildi"})
        jobs.update(self.vault, job.name, status="calisiyor")
        again = jobs.update(self.vault, job.name, status="bitti")
        self.assertEqual(again.meta["karne"], "yazildi", "a job gets one scorecard row")

    def test_move_never_overwrites_an_existing_file(self):
        job = self.create()
        os.makedirs(self.folder("Devam-Edenler"))
        squatter = os.path.join(self.folder("Devam-Edenler"), job.name)
        with open(squatter, "w") as f:
            f.write("başka not")
        with self.assertRaises(jobs.JobError):
            jobs.update(self.vault, job.name, status="calisiyor")
        with open(squatter) as f:
            self.assertEqual(f.read(), "başka not")

    def test_expected_status_guards_an_update(self):
        job = self.create()
        jobs.update(self.vault, job.name, status="baslatiliyor")
        jobs.update(self.vault, job.name, status="bitti")
        with self.assertRaises(jobs.StatusConflict):
            jobs.update(self.vault, job.name, status="calisiyor", expect=("baslatiliyor",))
        self.assertEqual(jobs.load(self.vault, job.name).meta["durum"], "bitti")

    def test_misplaced_note_is_settled(self):
        # A crash between the in-place write and the move leaves a done job in Devam-Edenler.
        job = self.create()
        jobs.update(self.vault, job.name, status="calisiyor")
        path = os.path.join(self.folder("Devam-Edenler"), job.name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("durum: calisiyor", "durum: bitti"))
        settled = jobs.settle(self.vault, job.name)
        self.assertEqual(settled.folder, jobs.DONE)

    # --- body sections ---

    def test_append_result_replaces_placeholder_then_appends(self):
        job = self.create()
        jobs.update(self.vault, job.name, append_result="İlk sonuç.")
        jobs.update(self.vault, job.name, append_result="İkinci sonuç.")
        text = self.read(jobs.load(self.vault, job.name))
        self.assertIn("## Sonuç\n\nİlk sonuç.\n\nİkinci sonuç.\n\n## İlgili Kararlar", text)
        self.assertNotIn(jobs.PLACEHOLDER, text)

    def test_decision_link_is_added_once_by_bare_name(self):
        job = self.create()
        jobs.update(self.vault, job.name, add_decision="2026-11-10-blog-soru-1.md")
        jobs.update(self.vault, job.name, add_decision="2026-11-10-blog-soru-1.md")
        text = self.read(jobs.load(self.vault, job.name))
        self.assertEqual(text.count("[[2026-11-10-blog-soru-1]]"), 1)
        self.assertIn("## İlgili Kararlar\n- [[2026-11-10-blog-soru-1]]", text)

    def test_processed_message_ids_are_recorded_with_the_change(self):
        job = self.create()
        jobs.update(self.vault, job.name, status="bitti", add_message="m1")
        job = jobs.load(self.vault, job.name)
        self.assertTrue(jobs.has_message(job, "m1"))
        self.assertFalse(jobs.has_message(job, "m2"))

    def test_unknown_frontmatter_lines_are_kept(self):
        os.makedirs(self.folder("Devam-Edenler"))
        path = os.path.join(self.folder("Devam-Edenler"), "eski.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\ntags: [ofis, is, blog]\nproje: blog\ndurum: calisiyor\nworktree: x\n---\n\n"
                    "# eski\n\n## Görev\n\nx\n\n## Sonuç\n\n(bitince CEO yazar)\n")
        jobs.update(self.vault, "eski.md", status="bitti", append_result="Tamam.")
        with open(os.path.join(self.folder("Bitenler"), "eski.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("tags: [ofis, is, blog]\n", text)
        self.assertIn("worktree: x\n", text)
        self.assertIn("## Sonuç\n\nTamam.\n", text)

    # --- brief (Hedef / Neden / Kısıtlar / Kapsam dışı / Kontrol) ---

    BRIEF = {"hedef": "Giriş ekranındaki hatayı düzelt.", "neden": "Kullanıcılar giriş yapamıyor.",
             "kisitlar": "API sözleşmesi değişmez.", "kapsam_disi": "", "kontrol": "./gradlew test --tests Login*"}

    def test_brief_sections_are_rendered_under_gorev_in_order_and_empty_ones_omitted(self):
        job = self.create(task=None, brief=self.BRIEF)
        gorev = jobs.section(job.body, "Görev")
        self.assertEqual(gorev, "### Hedef\n\nGiriş ekranındaki hatayı düzelt.\n\n### Neden\n\nKullanıcılar giriş "
                                "yapamıyor.\n\n### Kısıtlar\n\nAPI sözleşmesi değişmez.\n\n### Kontrol\n\n"
                                "./gradlew test --tests Login*")
        self.assertNotIn("Kapsam dışı", job.body)
        self.assertEqual(job.meta["kontrol"], "./gradlew test --tests Login*")

    def test_brief_round_trip(self):
        brief = dict(self.BRIEF, kapsam_disi="Tasarım değişikliği.\nİkinci satır.", kontrol="pytest -q\nve gözle bak")
        job = jobs.load(self.vault, self.create(task=None, brief=brief).name)
        self.assertEqual(jobs.read_brief(job.body), brief)
        self.assertEqual(job.meta["kontrol"], "pytest -q ve gözle bak", "frontmatter copy is one line")

    def test_prompt_is_assembled_in_order_with_turkish_headings(self):
        job = self.create(task=None, brief=dict(self.BRIEF, neden="", kapsam_disi="Tasarım."))
        self.assertEqual(jobs.prompt(job), "## Hedef\nGiriş ekranındaki hatayı düzelt.\n\n## Kısıtlar\nAPI "
                                           "sözleşmesi değişmez.\n\n## Kapsam dışı\nTasarım.\n\n## Kontrol\n"
                                           "./gradlew test --tests Login*")

    def test_prompt_of_a_note_without_brief_is_its_whole_task(self):
        job = self.create()
        self.assertEqual(jobs.prompt(job), "Durum özeti.\nDal ve commitler.")
        self.assertEqual(jobs.read_brief(job.body)["hedef"], "Durum özeti.\nDal ve commitler.")

    def test_prompt_of_a_hedef_only_brief_has_no_heading(self):
        job = self.create(task=None, brief={"hedef": "Yalnız hedef."})
        self.assertEqual(jobs.prompt(job), "Yalnız hedef.")

    def test_brief_needs_a_hedef(self):
        with self.assertRaises(jobs.JobError):
            self.create(task=None, brief=dict(self.BRIEF, hedef="  "))

    # --- listing ---

    def test_list_jobs_across_folders_and_legacy(self):
        a = self.create()
        b = self.create()
        jobs.update(self.vault, b.name, status="bitti")
        os.makedirs(self.folder(""), exist_ok=True)
        with open(os.path.join(self.folder(""), "2026-11-09-1-blog.md"), "w", encoding="utf-8") as f:
            f.write("---\nproje: blog\ndurum: bitti\n---\n")
        names = {j.name: j.folder for j in jobs.list_jobs(self.vault)}
        self.assertEqual(names, {a.name: jobs.QUEUED, b.name: jobs.DONE})
        legacy = {j.name: j.folder for j in jobs.list_jobs(self.vault, legacy=True)}
        self.assertEqual(legacy["2026-11-09-1-blog.md"], jobs.LEGACY)

    # --- lock (review findings 10 and 11) ---

    def test_lock_file_is_durum_jobs_lock_under_the_repo_root_not_in_tmpdir(self):
        # The CEO runs with a sandboxed TMPDIR; a lock there is not the server's lock.
        saved = os.environ.pop("OFIS_JOBS_LOCK")
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(jobs.__file__)))
            self.assertEqual(jobs.lock_path(), os.path.join(root, "durum", "jobs.lock"))
        finally:
            os.environ["OFIS_JOBS_LOCK"] = saved
        self.assertEqual(jobs.lock_path(), saved, "tests point the lock at a temp file, never the real durum/")

    def test_lock_is_reentrant_within_one_thread(self):
        done = threading.Event()
        held = []

        def work():
            with jobs.locked(self.vault):
                held.append(jobs.lock_held())
                with jobs.locked(self.vault):
                    job = self.create()
                    jobs.update(self.vault, job.name, status="calisiyor")
            held.append(jobs.lock_held())
            done.set()

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(10)
        self.assertTrue(done.is_set(), "a nested lock deadlocked")
        self.assertEqual(held, [True, False])

    def test_lock_still_excludes_another_thread(self):
        order = []
        inside = threading.Event()

        def other():
            inside.wait(5)
            with jobs.locked(self.vault):
                order.append("other")

        t = threading.Thread(target=other, daemon=True)
        t.start()
        with jobs.locked(self.vault):
            inside.set()
            t.join(0.3)
            order.append("first")
        t.join(5)
        self.assertEqual(order, ["first", "other"])


if __name__ == "__main__":
    unittest.main()
