"""Tests for bin/ofis.py (the job CLI of the CEO and the project sessions). Fake claude, temp vault/durum only."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402
import kontrol  # noqa: E402
import jobs  # noqa: E402
import karne  # noqa: E402
import ofis  # noqa: E402
import records  # noqa: E402

NOW = datetime(2026, 11, 10, 18, 38, 20)
SESSION = "ofis-blog-1110-183820-ab12"
TIERS = {"planlama": {"model": "fable", "effort": "high"}, "kod": {"model": "opus"}, "inceleme": {"model": "opus"},
         "genel": {"model": "sonnet"}, "kolay": {"model": "haiku", "effort": "low"}}


class OfisTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.project = os.path.join(base, "Dev", "blog")
        self.zim = os.path.join(base, "Dev", "zim")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.durum = os.path.join(base, "ajan-ofisi", "durum")
        for d in (self.project, self.zim, self.vault):
            os.makedirs(d)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
                    "projects": {"blog": {"path": self.project}, "zim": {"path": self.zim}},
                    "tiers": TIERS, "default_tier": "genel", "default_budget_usd": 3}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, stdin=None, now=NOW, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, claude_bin=self.fake.path,
                         now=lambda: now, suffix="ab12", stdin=io.StringIO(stdin or ""), out=out, err=err,
                         cwd=cwd or self.project)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv, **kw):
        code, out, err = self.run_cli(*argv, **kw)
        self.assertEqual(code, 0, err)
        return json.loads(out) if out.strip().startswith("{") else out

    def refused(self, *argv, **kw):
        code, out, err = self.run_cli(*argv, **kw)
        self.assertEqual(code, 1, out)
        self.assertTrue(err.startswith("REFUSED: "), err)
        return err

    def add(self, *extra, hedef="Durum özeti. Dal ve son commitler."):
        return self.ok("ekle", "--proje", "blog", "--baslik", "Durum özeti", "--hedef", hedef, *extra)["is"]

    def job(self, name):
        return jobs.load(self.vault, name)

    def claude_calls(self):
        return [c["args"] for c in self.fake.calls()]

    # --- ekle ---

    def test_ekle_creates_a_queued_job_with_the_default_tier(self):
        name = self.add()
        job = self.job(name)
        self.assertEqual(job.folder, jobs.QUEUED)
        meta = job.meta
        self.assertEqual((meta["durum"], meta["katman"], meta["model"], meta["yurutucu"], meta["butce_usd"]),
                         ("sirada", "genel", "sonnet", "claude", "3"))
        self.assertNotIn("effort", meta)
        self.assertEqual(jobs.section(job.body, "Görev"), "### Hedef\n\nDurum özeti. Dal ve son commitler.")
        self.assertEqual(self.claude_calls(), [], "ekle never starts a session")

    def test_tier_gives_model_and_effort_unless_set_explicitly(self):
        kolay = self.job(self.add("--katman", "kolay")).meta
        self.assertEqual((kolay["model"], kolay["effort"]), ("haiku", "low"))
        planlama = self.job(self.add("--katman", "planlama", "--effort", "max")).meta
        self.assertEqual((planlama["model"], planlama["effort"]), ("fable", "max"))
        kod = self.job(self.add("--katman", "kod", "--model", "sonnet", "--kontrol", "pytest -q")).meta
        self.assertEqual((kod["katman"], kod["model"]), ("kod", "sonnet"))

    def test_budget_dependencies_and_group_are_recorded(self):
        first = self.add()
        meta = self.job(self.add("--butce", "1.5", "--bagimli", first[:-3], "--grup", "w-145")).meta
        self.assertEqual((meta["butce_usd"], meta["bagimli"], meta["grup"]), ("1.5", first, "w-145"))

    def test_ekle_takes_the_brief_and_baslat_sends_it_in_order(self):
        name = self.ok("ekle", "--proje", "blog", "--baslik", "Giriş hatası", "--hedef", "Girişi düzelt.",
                       "--neden", "Kullanıcılar giremiyor.", "--kisitlar", "API değişmez.",
                       "--kapsam-disi", "Tasarım.", "--kontrol", "pytest -q tests/test_login.py")["is"]
        job = self.job(name)
        self.assertEqual(jobs.read_brief(job.body),
                         {"hedef": "Girişi düzelt.", "neden": "Kullanıcılar giremiyor.", "kisitlar": "API değişmez.",
                          "kapsam_disi": "Tasarım.", "kontrol": "pytest -q tests/test_login.py"})
        self.assertEqual(job.meta["kontrol"], "pytest -q tests/test_login.py")
        self.assertEqual(job.meta["baslik"], "Giriş hatası")
        self.ok("baslat", name)
        self.assertEqual(self.claude_calls()[0][-1],
                         "## Hedef\nGirişi düzelt.\n\n## Neden\nKullanıcılar giremiyor.\n\n## Kısıtlar\nAPI değişmez."
                         "\n\n## Kapsam dışı\nTasarım.\n\n## Kontrol\npytest -q tests/test_login.py")

    def test_gorev_is_an_alias_of_hedef(self):
        name = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--gorev", "Eski bayrak.")["is"]
        self.assertEqual(jobs.read_brief(self.job(name).body)["hedef"], "Eski bayrak.")

    def test_ekle_refuses_a_missing_or_empty_hedef_and_a_too_long_brief(self):
        self.refused("ekle", "--proje", "blog", "--baslik", "x", "--neden", "y")
        self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", " \n ", "--neden", "y")
        self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "a" * 3000, "--neden", "b" * 1000)
        self.assertEqual(jobs.list_jobs(self.vault), [])

    def test_ekle_refusals(self):
        cases = [
            ("--proje", "zim", "--baslik", "x", "--hedef", "y"),
            ("--proje", "kayitsiz", "--baslik", "x", "--hedef", "y"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "--dangerously-skip-permissions"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "   "),
            ("--proje", "blog", "--baslik", "  ", "--hedef", "y"),
            ("--proje", "blog", "--baslik", "x" * 200, "--hedef", "y"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--katman", "uzay"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--model", "opus; rm"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--butce", "-1"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--butce", "nan"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--bagimli", "yok-is"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--bagimli", "../Kararlar/a"),
            ("--proje", "blog", "--baslik", "x", "--hedef", "y", "--grup", "a/b"),
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.refused("ekle", *argv)
        self.assertEqual(jobs.list_jobs(self.vault), [])

    # --- baslat ---

    def test_baslat_starts_the_job_with_its_model_and_records_the_session(self):
        name = self.add("--katman", "kolay")
        result = self.ok("baslat", name)
        self.assertEqual(result["oturum"], SESSION)
        [call] = self.claude_calls()
        self.assertEqual(call[:3], ["--bg", "--name", SESSION])
        self.assertEqual(call[call.index("--model") + 1], "haiku")
        self.assertEqual(call[call.index("--effort") + 1], "low")
        self.assertEqual(call[-1], "Durum özeti. Dal ve son commitler.", "a Hedef alone is sent without a heading")
        contract = call[call.index("--append-system-prompt") + 1]
        self.assertIn(f"--oturum {SESSION}", contract)
        job = self.job(name)
        self.assertEqual(job.folder, jobs.ACTIVE)
        meta = job.meta
        self.assertEqual((meta["durum"], meta["oturum"], meta["kisa_id"], meta["calisma_dizini"]),
                         ("calisiyor", SESSION, "c0ffee00", self.project))
        self.assertEqual(meta.get("taban_commit", ""), "", "not a git repository")
        self.assertEqual(meta["baslangic"], "2026-11-10T18:38:20")

    def test_baslat_records_the_base_commit_of_a_git_project(self):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@e")
        subprocess.run(["git", "init", "-q", self.project], check=True, env=env)
        subprocess.run(["git", "-C", self.project, "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)
        head = subprocess.run(["git", "-C", self.project, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        name = self.add()
        self.ok("baslat", name)
        self.assertEqual(self.job(name).meta["taban_commit"], head)
        # phase 4: the server record keeps it too (a workflow's code review reads it from there, never the note)
        self.assertEqual(records.load(self.durum, name)["taban_commit"], head)
        self.assertEqual(records.from_note(self.job(name)).get("taban_commit"), None, "never taken from a note")

    def test_a_job_is_started_only_once(self):
        name = self.add()
        self.ok("baslat", name)
        self.refused("baslat", name)
        self.assertEqual(len(self.claude_calls()), 1)

    def test_failed_start_marks_the_job_failed_in_bitenler(self):
        self.fake.flag("fail")
        name = self.add()
        self.refused("baslat", name)
        job = self.job(name)
        self.assertEqual((job.folder, job.meta["durum"]), (jobs.DONE, "basarisiz"))
        self.assertIn("Başlatma başarısız", jobs.section(job.body, "Sonuç"))

    def test_baslat_unknown_or_unsafe_job_is_refused(self):
        for bad in ("yok", "../x", ".gizli"):
            with self.subTest(bad=bad):
                self.refused("baslat", bad)
        self.assertEqual(self.claude_calls(), [])

    # --- bildir ---

    def inbox(self):
        folder = os.path.join(self.durum, "gelen")
        return sorted(n for n in os.listdir(folder) if n.endswith(".json")) if os.path.isdir(folder) else []

    def test_bildir_only_writes_one_inbox_file(self):
        self.ok("bildir", "--oturum", SESSION, "--tur", "bitti", "İş bitti. Testler geçti.")
        [name] = self.inbox()
        with open(os.path.join(self.durum, "gelen", name), encoding="utf-8") as f:
            msg = json.load(f)
        self.assertEqual((msg["oturum"], msg["tur"], msg["metin"]), (SESSION, "bitti", "İş bitti. Testler geçti."))
        self.assertEqual(msg["id"], name[:-5])
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Isler")), "bildir never writes the vault")
        self.assertEqual(self.claude_calls(), [])
        self.assertEqual([n for n in os.listdir(os.path.join(self.durum, "gelen")) if n.startswith(".")], [])

    def test_bildir_names_are_unique_and_ordered(self):
        for i in range(3):
            self.ok("bildir", "--oturum", SESSION, "--tur", "soru", f"soru {i}")
        names = self.inbox()
        self.assertEqual(len(names), 3)
        texts = []
        for n in names:
            with open(os.path.join(self.durum, "gelen", n), encoding="utf-8") as f:
                texts.append(json.load(f)["metin"])
        self.assertEqual(texts, ["soru 0", "soru 1", "soru 2"])

    def test_bildir_reads_text_from_stdin(self):
        self.ok("bildir", "--oturum", SESSION, "--tur", "tikandi", "-", stdin="Satır 1\n`$HOME` \"tırnak\"\n")
        [name] = self.inbox()
        with open(os.path.join(self.durum, "gelen", name), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["metin"], "Satır 1\n`$HOME` \"tırnak\"")

    def test_bildir_validation(self):
        for argv in (("--oturum", "ofis-ceo/../x", "--tur", "bitti", "x"),
                     ("--oturum", "blog", "--tur", "bitti", "x"),
                     ("--oturum", "ofis-" + "a" * 81, "--tur", "bitti", "x"),
                     ("--oturum", SESSION, "--tur", "baska", "x"),
                     ("--oturum", SESSION, "--tur", "bitti", "   ")):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli("bildir", *argv)
                self.assertNotEqual(code, 0)
        self.assertEqual(self.inbox(), [])

    # --- cevapla ---

    def decision(self, name="2026-11-10-blog-soru-183900-ab12.md", job=None, status="bekliyor",
                 source=SESSION, soru="Devam edeyim mi?"):
        meta = {"tags": "[ofis, karar, blog]", "proje": "blog", "durum": status,
                "soruldu": "2026-11-10T18:39:00", "kaynak_oturum": source}
        if job:
            meta["is"] = job
        fakes.write_note(os.path.join(self.vault, "Kararlar"), name, meta,
                         f"# blog — Devam mı?\n\n## Soru\n{soru}\n\n## İlgili Sayfalar\n- [[OFIS/README]]\n")
        return name

    def running_job(self, status="karar-bekliyor"):
        name = self.add()
        self.ok("baslat", name)
        jobs.update(self.vault, name, status=status)
        return name

    def outbox(self):
        folder = os.path.join(self.durum, "giden")
        out = []
        for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if n.endswith(".json"):
                with open(os.path.join(folder, n), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out

    def test_cevapla_updates_the_decision_resumes_the_job_and_writes_one_outbox_file(self):
        job = self.running_job()
        note = self.decision(job=job)
        later = datetime(2026, 11, 10, 18, 45, 0)
        self.ok("cevapla", note, "Evet, devam et.\nAma testleri de yaz.", now=later)
        with open(os.path.join(self.vault, "Kararlar", note), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("durum: cevaplandi", text)
        self.assertIn("cevaplandi: 2026-11-10T18:45:00", text)
        self.assertIn("## Cevap (Selin)\n\nEvet, devam et.\nAma testleri de yaz.\n\n## İlgili Sayfalar", text)
        self.assertEqual(self.job(job).meta["durum"], "calisiyor")
        [msg] = self.outbox()
        self.assertEqual(msg["oturum"], SESSION)
        self.assertEqual(msg["metin"], f"[Ofis · Sahibin cevabı] {note[:-3]}\nSoru: Devam edeyim mi?\n"
                                       "Cevap: Evet, devam et.\nAma testleri de yaz.")
        self.assertEqual((msg["karar"], msg["is"]), (note, job))

    def test_cevapla_twice_is_refused_and_sends_nothing_more(self):
        job = self.running_job()
        note = self.decision(job=job)
        self.ok("cevapla", note, "Evet.")
        self.refused("cevapla", note, "Hayır.")
        self.assertEqual(len(self.outbox()), 1)

    def test_job_keeps_waiting_while_another_question_is_open(self):
        job = self.running_job()
        first = self.decision("2026-11-10-blog-soru-1.md", job=job)
        self.decision("2026-11-10-blog-soru-2.md", job=job)
        self.ok("cevapla", first, "Evet.")
        self.assertEqual(self.job(job).meta["durum"], "karar-bekliyor")

    def test_cevapla_closes_a_claude_md_proposal_without_any_session(self):
        # phase 5: the CEO's proposal has no project session; the answer is recorded and returned to the CEO
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-11-blog-claude-md-onerisi.md",
                         {"durum": "bekliyor", "proje": "blog", "tur": "claude-md-onerisi",
                          "soruldu": "2026-11-11T11:00:00"},
                         "# blog — CLAUDE.md önerisi\n\n## Soru\nEklensin mi?\n\n## İlgili Sayfalar\n- [[x]]\n")
        result = self.ok("cevapla", "2026-11-11-blog-claude-md-onerisi.md", "Evet")
        self.assertEqual((result["tur"], result["onay"]), ("claude-md-onerisi", True))
        self.assertEqual(self.outbox(), [])
        with open(os.path.join(self.vault, "Kararlar", "2026-11-11-blog-claude-md-onerisi.md"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertIn("durum: cevaplandi", text)
        self.assertIn("## Cevap (Selin)\n\nEvet\n", text)
        self.refused("cevapla", "2026-11-11-blog-claude-md-onerisi.md", "Hayır")

    def test_the_answer_heading_and_the_outbox_head_follow_the_configured_owner(self):
        # plan "2. Aşama": "## Cevap (<sahip_adi>)" in the note, the neutral "[Ofis · Sahibin cevabı]" to the session
        self.cfg["sahip_adi"] = "Ayşe"
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-11-blog-claude-md-onerisi.md",
                         {"durum": "bekliyor", "proje": "blog", "tur": "claude-md-onerisi",
                          "soruldu": "2026-11-11T11:00:00"},
                         "# blog — CLAUDE.md önerisi\n\n## Soru\nEklensin mi?\n\n## İlgili Sayfalar\n- [[x]]\n")
        self.ok("cevapla", "2026-11-11-blog-claude-md-onerisi.md", "Evet")
        with open(os.path.join(self.vault, "Kararlar", "2026-11-11-blog-claude-md-onerisi.md"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## Cevap (Ayşe)\n\nEvet\n", text)
        self.assertEqual(ofis.ANSWER_HEAD, "[Ofis · Sahibin cevabı]")

    def test_cevapla_closes_an_ArGe_reviewer_card_without_any_session(self):
        # plan "Sonraki iş (6)": the server writes the card from the Ar-Ge report; the answer goes back to the CEO only
        import arge
        os.makedirs(self.vault, exist_ok=True)
        card = arge.kart_metni({"model": "opencode/beam-free", "lisans": "MIT", "neden": "x"}, "2026-11-11",
                               "2026-11-11-090000-arge.md", datetime(2026, 11, 11, 9, 40))
        os.makedirs(os.path.join(self.vault, "Kararlar"), exist_ok=True)
        name = "2026-11-11-arge-denetci-onerisi.md"
        with open(os.path.join(self.vault, "Kararlar", name), "w", encoding="utf-8") as f:
            f.write(card)
        result = self.ok("cevapla", name, "Evet")
        self.assertEqual((result["tur"], result["onay"]), ("denetci-onerisi", True))
        self.assertEqual(self.outbox(), [])
        with open(os.path.join(self.vault, "Kararlar", name), encoding="utf-8") as f:
            self.assertIn("durum: cevaplandi", f.read())

    def test_cevapla_closes_a_review_md_proposal_like_a_claude_md_one(self):
        # a recurring reviewer finding class: the CEO proposes a REVIEW.md line; the answer goes back to the CEO only
        name = "2026-11-11-blog-review-md-onerisi.md"
        fakes.write_note(os.path.join(self.vault, "Kararlar"), name,
                         {"durum": "bekliyor", "proje": "blog", "tur": "review-md-onerisi",
                          "soruldu": "2026-11-11T11:00:00"},
                         "# blog — REVIEW.md önerisi\n\n## Soru\nEklensin mi?\n\n## İlgili Sayfalar\n- [[x]]\n")
        result = self.ok("cevapla", name, "Evet")
        self.assertEqual((result["tur"], result["onay"]), ("review-md-onerisi", True))
        self.assertEqual(self.outbox(), [])
        with open(os.path.join(self.vault, "Kararlar", name), encoding="utf-8") as f:
            self.assertIn("durum: cevaplandi", f.read())
        other = "2026-11-11-blog-review-md-onerisi-2.md"
        fakes.write_note(os.path.join(self.vault, "Kararlar"), other,
                         {"durum": "bekliyor", "proje": "blog", "tur": "review-md-onerisi"},
                         "# x\n\n## Soru\nEklensin mi?\n\n## İlgili Sayfalar\n- [[x]]\n")
        self.assertEqual(self.ok("cevapla", other, "Hayır, gerek yok")["onay"], False)

    def test_cevapla_refusals(self):
        self.decision("2026-11-10-eski.md", status="cevaplandi")
        self.decision("2026-11-10-kaynak-bozuk.md", source="ofis-ceo; rm")
        for argv in (("yok.md", "x"), ("../Isler/a.md", "x"), ("2026-11-10-eski.md", "x"),
                     ("2026-11-10-kaynak-bozuk.md", "x"), (self.decision(), "   ")):
            with self.subTest(argv=argv):
                self.refused("cevapla", *argv)
        self.assertEqual(self.outbox(), [])

    def outbox_names(self, sub=""):
        folder = os.path.join(self.durum, "giden", sub)
        return sorted(n for n in os.listdir(folder) if n.endswith(".json")) if os.path.isdir(folder) else []

    def test_answer_names_its_question_and_outbox_files_are_in_answer_order(self):
        # Review finding 4: the session must know which question an answer belongs to, and get them in order.
        job = self.running_job()
        a = self.decision("2026-11-10-blog-soru-a.md", job=job, soru="> API silinsin mi?\n> Ayrıntı: v1.")
        b = self.decision("2026-11-10-blog-soru-b.md", job=job, soru="Hangi dal?")
        self.ok("cevapla", b, "main.")
        self.ok("cevapla", a, "Hayır.")
        names = self.outbox_names()
        self.assertRegex(names[0], r"^[0-9]{19}-cevap-2026-11-10-blog-soru-b\.json$")
        self.assertRegex(names[1], r"^[0-9]{19}-cevap-2026-11-10-blog-soru-a\.json$")
        first, second = self.outbox()
        self.assertEqual((first["id"], second["id"]),
                         ("cevap-2026-11-10-blog-soru-b", "cevap-2026-11-10-blog-soru-a"))
        self.assertEqual(second["metin"], "[Ofis · Sahibin cevabı] 2026-11-10-blog-soru-a\n"
                                          "Soru: API silinsin mi?\nCevap: Hayır.")

    def test_cevapla_rerun_after_a_failed_note_write_queues_no_second_answer(self):
        job = self.running_job()
        note = self.decision(job=job)
        real = jobs._write_atomic

        def fail(path, text):
            raise OSError("disk full")
        jobs._write_atomic = fail
        try:
            self.refused("cevapla", note, "Evet.")
        finally:
            jobs._write_atomic = real
        self.assertEqual(len(self.outbox_names()), 1)
        self.ok("cevapla", note, "Evet.")
        self.assertEqual(len(self.outbox_names()), 1)

    def test_cevapla_scans_open_questions_and_updates_the_job_under_one_lock(self):
        # Review finding 11: a question written between the scan and the update must not be missed.
        job = self.running_job()
        note = self.decision(job=job)
        seen = []
        real_scan, real_update = ofis._pending_for_job, jobs.update

        def scan(*a, **k):
            seen.append(("scan", jobs.lock_held()))
            return real_scan(*a, **k)

        def update(*a, **k):
            seen.append(("update", jobs.lock_held()))
            return real_update(*a, **k)
        ofis._pending_for_job, jobs.update = scan, update
        try:
            self.ok("cevapla", note, "Evet.")
        finally:
            ofis._pending_for_job, jobs.update = real_scan, real_update
        self.assertEqual(seen, [("scan", True), ("update", True)])

    # --- file input (review finding 5: the guard blocks some words in argv, never in a written file) ---

    def taslak(self, name, content):
        folder = os.path.join(self.durum, "taslak")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
        return path

    def test_ekle_reads_the_brief_from_a_file_and_deletes_it(self):
        path = self.taslak("is.json", {"proje": "blog", "baslik": "W-116 şifre sıfırlama",
                                       "hedef": "Şifre sıfırlama e-postası gitsin.", "neden": "Kullanıcı giremiyor.",
                                       "kisitlar": "API değişmez.", "kapsam_disi": "Tasarım.",
                                       "kontrol": "pytest -q tests/test_reset.py", "katman": "kod", "butce": 2})
        name = self.ok("ekle", "--brief-dosya", path)["is"]
        job = self.job(name)
        self.assertEqual(jobs.read_brief(job.body),
                         {"hedef": "Şifre sıfırlama e-postası gitsin.", "neden": "Kullanıcı giremiyor.",
                          "kisitlar": "API değişmez.", "kapsam_disi": "Tasarım.",
                          "kontrol": "pytest -q tests/test_reset.py"})
        self.assertEqual((job.meta["baslik"], job.meta["katman"], job.meta["model"], job.meta["butce_usd"]),
                         ("W-116 şifre sıfırlama", "kod", "opus", "2"))
        self.assertFalse(os.path.exists(path), "the scratch file is deleted once the job is written")

    def test_command_line_values_win_over_the_brief_file(self):
        path = self.taslak("is.json", {"proje": "blog", "baslik": "Dosyadan", "hedef": "Dosyadan hedef."})
        name = self.ok("ekle", "--brief-dosya", path, "--baslik", "Komuttan")["is"]
        self.assertEqual(self.job(name).meta["baslik"], "Komuttan")

    def test_brief_file_refusals_keep_the_file_for_fixing(self):
        cases = {"eksik.json": {"proje": "blog", "baslik": "x"},
                 "bozuk.json": "{bozuk",
                 "liste.json": ["hedef"],
                 "bilinmeyen.json": {"proje": "blog", "baslik": "x", "hedef": "y", "komut": "rm"},
                 "tur.json": {"proje": "blog", "baslik": "x", "hedef": ["y"]}}
        for file_name, content in cases.items():
            with self.subTest(file=file_name):
                path = self.taslak(file_name, content)
                self.refused("ekle", "--brief-dosya", path)
                self.assertTrue(os.path.exists(path))
        self.assertEqual(jobs.list_jobs(self.vault), [])

    def test_input_files_must_be_plain_files_directly_in_durum_taslak(self):
        outside = os.path.join(self.durum, "is.json")
        self.taslak("x.json", "{}")
        with open(outside, "w", encoding="utf-8") as f:
            json.dump({"proje": "blog", "baslik": "x", "hedef": "y"}, f)
        link = os.path.join(self.durum, "taslak", "link.json")
        os.symlink(outside, link)
        os.makedirs(os.path.join(self.durum, "taslak", "alt"))
        nested = os.path.join(self.durum, "taslak", "alt", "is.json")
        with open(nested, "w", encoding="utf-8") as f:
            json.dump({"proje": "blog", "baslik": "x", "hedef": "y"}, f)
        for path in (outside, link, nested, os.path.join(self.durum, "taslak", "..", "is.json"),
                     os.path.join(self.durum, "taslak", "yok.json")):
            with self.subTest(path=path):
                self.refused("ekle", "--brief-dosya", path)
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(jobs.list_jobs(self.vault), [])

    def test_cevapla_reads_the_answer_from_a_file(self):
        job = self.running_job()
        note = self.decision(job=job)
        path = self.taslak("cevap.txt", "Yeni şifre kuralı: en az 12 karakter.\n")
        self.ok("cevapla", note, "--dosya", path)
        [msg] = self.outbox()
        self.assertTrue(msg["metin"].endswith("Cevap: Yeni şifre kuralı: en az 12 karakter."), msg["metin"])
        self.assertFalse(os.path.exists(path))
        second = self.decision("2026-11-10-blog-soru-2.md", job=job)
        path = self.taslak("cevap.txt", "x")
        self.refused("cevapla", second, "x", "--dosya", path)  # both forms at once
        self.refused("cevapla", second)  # neither
        self.assertTrue(os.path.exists(path))

    def test_bildir_reads_the_text_from_a_file(self):
        path = self.taslak("rapor.txt", "W-116 bitti: şifre sıfırlama çalışıyor.\n")
        self.ok("bildir", "--oturum", SESSION, "--tur", "bitti", "--dosya", path)
        [name] = self.inbox()
        with open(os.path.join(self.durum, "gelen", name), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["metin"], "W-116 bitti: şifre sıfırlama çalışıyor.")
        self.assertFalse(os.path.exists(path))

    # --- bildir: no lost reports (finding 6), the caller's folder (finding 7) ---

    def test_bildir_shortens_a_long_report_instead_of_refusing(self):
        self.ok("bildir", "--oturum", SESSION, "--tur", "bitti", "-", stdin="a" * 9000)
        [name] = self.inbox()
        with open(os.path.join(self.durum, "gelen", name), encoding="utf-8") as f:
            text = json.load(f)["metin"]
        self.assertEqual(text, "a" * 7500 + "\n(kısaltıldı)")

    def test_bildir_records_the_callers_working_directory(self):
        link = os.path.join(os.path.dirname(self.project), "kisayol")
        os.symlink(self.project, link)
        self.ok("bildir", "--oturum", SESSION, "--tur", "bitti", "Bitti.", cwd=link)
        [name] = self.inbox()
        with open(os.path.join(self.durum, "gelen", name), encoding="utf-8") as f:
            msg = json.load(f)
        self.assertEqual((msg["cwd"], msg["cwd_gercek"]), (link, self.project))

    # --- iptal / bitir drop what is still waiting (finding 2) ---

    def queue_file(self, session=SESSION):
        return os.path.join(self.durum, "kuyruk", session + ".jsonl")

    def write_queue(self, session, items):
        os.makedirs(os.path.dirname(self.queue_file(session)), exist_ok=True)
        with open(self.queue_file(session), "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def read_meta(self, note):
        with open(os.path.join(self.vault, "Kararlar", note), encoding="utf-8") as f:
            return jobs.parse(f.read())[1]

    def test_iptal_drops_pending_answers_and_queue_and_closes_open_questions(self):
        job = self.running_job()
        answered = self.decision("2026-11-10-blog-soru-1.md", job=job)
        still_open = self.decision("2026-11-10-blog-soru-2.md", job=job)
        other_job = self.decision("2026-11-10-blog-soru-3.md", job="baska-is.md", source="ofis-blog-baska")
        self.ok("cevapla", answered, "Evet.")
        self.write_queue(SESSION, [{"id": "giden-cevap-x", "text": "x", "keyed": True}])
        self.write_queue("ofis-blog-baska", [{"id": "giden-cevap-y", "text": "y", "keyed": True}])
        result = self.ok("iptal", job)
        self.assertEqual(self.outbox_names(), [])
        self.assertEqual(len(self.outbox_names("reddedilen")), 1)
        with open(self.queue_file(), encoding="utf-8") as f:
            self.assertEqual(f.read(), "")
        with open(self.queue_file("ofis-blog-baska"), encoding="utf-8") as f:
            self.assertIn("giden-cevap-y", f.read(), "another session's queue is untouched")
        self.assertEqual(self.read_meta(still_open)["durum"], "kapandi")
        self.assertEqual(self.read_meta(answered)["durum"], "cevaplandi")
        self.assertEqual(self.read_meta(other_job)["durum"], "bekliyor")
        self.assertEqual(result["kapanan_kararlar"], [still_open])

    def test_bitir_also_closes_open_questions_and_drops_answers(self):
        job = self.running_job()
        note = self.decision(job=job)
        self.ok("bitir", job)
        self.assertEqual(self.read_meta(note)["durum"], "kapandi")

    # --- bitir / iptal / durum ---

    def test_bitir_moves_a_running_job_to_bitenler_with_result(self):
        job = self.running_job("calisiyor")
        self.ok("bitir", job, "--sonuc", "CEO kapattı: oturum özetinden.", now=datetime(2026, 11, 10, 19, 0, 0))
        done = self.job(job)
        self.assertEqual((done.folder, done.meta["durum"], done.meta["bitis"]),
                         (jobs.DONE, "bitti", "2026-11-10T19:00:00"))
        self.assertIn("CEO kapattı", jobs.section(done.body, "Sonuç"))

    def test_bitir_only_for_started_jobs(self):
        self.refused("bitir", self.add())

    def test_iptal_cancels_a_queued_or_running_job_once(self):
        queued = self.add()
        self.ok("iptal", queued)
        self.assertEqual((self.job(queued).folder, self.job(queued).meta["durum"]), (jobs.DONE, "iptal"))
        self.refused("iptal", queued)
        running = self.running_job("calisiyor")
        result = self.ok("iptal", running)
        self.assertEqual(result["oturum"], SESSION, "the CEO learns which session to stop")

    # --- phase 2: trusted Kontrol, budget, devam ---

    def test_ekle_keeps_the_trusted_kontrol_copy_in_durum(self):
        with_kontrol = self.add("--kontrol", "pytest -q tests/test_login.py")
        without = self.add()
        self.assertEqual(kontrol.load(self.durum, with_kontrol), "pytest -q tests/test_login.py")
        self.assertIsNone(kontrol.load(self.durum, without))
        self.assertTrue(os.path.isfile(os.path.join(self.durum, "kontroller", with_kontrol[:-3] + ".json")))

    def test_a_kod_job_without_kontrol_is_refused(self):
        err = self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--katman", "kod")
        self.assertIn("kod işi kontrolsüz başlatılamaz", err)
        self.assertEqual(jobs.list_jobs(self.vault), [])

    def test_a_kontrol_naming_a_forbidden_path_is_refused(self):
        self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--kontrol",
                     "cd ~/Dev/zim && mvn test")
        self.assertEqual(jobs.list_jobs(self.vault), [])

    def test_baslat_refuses_a_kod_job_without_its_trusted_kontrol(self):
        name = self.add("--katman", "kod", "--kontrol", "pytest -q")
        os.remove(os.path.join(self.durum, "kontroller", name[:-3] + ".json"))
        err = self.refused("baslat", name)
        self.assertIn("kod işi kontrolsüz başlatılamaz", err)
        self.assertEqual(self.claude_calls(), [])
        self.assertEqual(self.job(name).meta["durum"], "sirada")

    def test_ekle_records_the_call_limit_of_the_tier(self):
        self.cfg["default_max_calls"] = {"genel": 40, "kolay": 15}
        self.assertEqual(self.job(self.add()).meta["max_cagri"], "40")
        self.assertEqual(self.job(self.add("--katman", "kolay")).meta["max_cagri"], "15")

    def test_butce_changes_the_budget_and_the_call_limit(self):
        name = self.running_job("calisiyor")
        self.assertEqual(self.ok("butce", name, "6"), {"is": name, "butce_usd": "6", "max_cagri": ""})
        self.ok("butce", name, "--cagri", "80")
        meta = self.job(name).meta
        self.assertEqual((meta["butce_usd"], meta["max_cagri"]), ("6", "80"))
        self.ok("butce", name, "7.5", "--cagri", "90")
        meta = self.job(name).meta
        self.assertEqual((meta["butce_usd"], meta["max_cagri"]), ("7.5", "90"))

    def test_butce_refusals(self):
        name = self.running_job("calisiyor")
        for argv in (("butce", name), ("butce", name, "0"), ("butce", name, "abc"), ("butce", name, "1001"),
                     ("butce", name, "--cagri", "0"), ("butce", name, "--cagri", "x"), ("butce", "yok.md", "5")):
            with self.subTest(argv=argv):
                self.refused(*argv)
        self.ok("bitir", name)
        self.refused("butce", name, "5")

    def stopped_job(self, **fields):
        name = self.running_job("calisiyor")
        jobs.update(self.vault, name, status="tikandi", fields=dict({"bitis": "2026-11-10T19:00:00"}, **fields))
        # the server keeps the spending on its own record too (the note is display only)
        records.update(self.durum, name, {k: v for k, v in fields.items() if k in records.TRUSTED})
        return name

    def test_devam_puts_a_stopped_job_back_to_work_and_queues_the_text(self):
        name = self.stopped_job(harcanan_usd="3.20", cagri="20")
        self.refused("devam", name)  # still over its $3 budget
        self.ok("butce", name, "5")
        result = self.ok("devam", name)
        self.assertEqual((result["is"], result["durum"]), (name, "calisiyor"))
        job = self.job(name)
        self.assertEqual((job.folder, job.meta["durum"], job.meta["bitis"]), (jobs.ACTIVE, "calisiyor", ""))
        [msg] = self.outbox()
        self.assertEqual((msg["oturum"], msg["is"]), (SESSION, name))
        self.assertTrue(msg["id"].startswith(f"devam-{name[:-3]}-"))
        self.assertTrue(msg["metin"].startswith("[Ofis · devam] "), msg["metin"])
        self.assertTrue(msg["metin"].endswith("\nDevam et."), msg["metin"])

    def test_devam_takes_the_text_from_an_argument_or_a_file(self):
        name = self.stopped_job()
        self.ok("devam", name, "Testleri bitir, sonra raporla.")
        self.assertTrue(self.outbox()[0]["metin"].endswith("\nTestleri bitir, sonra raporla."))
        # phase 5: every devam round is a correction event with its text
        [event] = karne.corrections(self.vault, "blog")
        self.assertEqual((event["is"], event["tur"]), (jobs.stem(name), "devam"))
        self.assertIn("Testleri bitir", event["alinti"])
        jobs.update(self.vault, name, status="tikandi")
        path = self.taslak("devam-1.txt", "Dosyadan devam.")
        self.ok("devam", name, "--dosya", path)
        self.assertTrue(any(m["metin"].endswith("\nDosyadan devam.") for m in self.outbox()))
        self.assertFalse(os.path.exists(path))

    def test_devam_only_for_a_stuck_job_with_a_session(self):
        self.cfg["max_running_per_project"] = 2  # phase 3: two jobs in one project folder need a higher limit
        self.refused("devam", self.running_job("calisiyor"))
        self.refused("devam", self.add())
        name = self.stopped_job()
        records.update(self.durum, name, {"oturum": ""})  # the server record decides, not the note
        self.refused("devam", name)
        self.assertEqual(self.outbox(), [])

    def test_durum_lists_queued_active_and_last_finished(self):
        queued = self.add()
        running = self.running_job("calisiyor")
        out = self.ok("durum")
        self.assertIn(queued[:-3], out)
        self.assertIn(running[:-3], out)
        self.assertIn("sirada", out)
        self.assertIn("calisiyor", out)

    # --- phase 2 review: the server-owned record (finding 1), devam and the karne row (finding 2), money (12) ---

    def record(self, name):
        return records.load(self.durum, name)

    def test_ekle_and_baslat_write_the_server_record(self):
        self.cfg["default_max_calls"] = {"kolay": 15}
        name = self.add("--katman", "kolay", "--butce", "0.5", "--kontrol", "pytest -q")
        rec = self.record(name)
        self.assertEqual((rec["is"], rec["proje"], rec["katman"], rec["model"], rec["effort"], rec["butce_usd"],
                          rec["max_cagri"]), (name, "blog", "kolay", "haiku", "low", "0.5", "15"))
        digest = records.digest("pytest -q")
        self.assertEqual(rec["kontrol_ozet"], digest)
        self.assertEqual(self.job(name).meta["kontrol_ozet"], digest, "the note shows the digest too")
        self.assertTrue(os.path.isfile(os.path.join(self.durum, "isler", name[:-3] + ".json")))
        self.ok("baslat", name)
        rec = self.record(name)
        self.assertEqual((rec["oturum"], rec["calisma_dizini"], rec["kisa_id"]), (SESSION, self.project, "c0ffee00"))

    def test_butce_updates_the_record_and_the_note(self):
        name = self.running_job("calisiyor")
        self.ok("butce", name, "0.002", "--cagri", "9")
        self.assertEqual((self.record(name)["butce_usd"], self.record(name)["max_cagri"]), ("0.002", "9"))
        self.assertEqual((self.job(name).meta["butce_usd"], self.job(name).meta["max_cagri"]), ("0.002", "9"))

    def test_devam_checks_the_limits_of_the_record_not_of_the_note(self):
        name = self.stopped_job()
        records.update(self.durum, name, {"harcanan_usd": "3.2", "cagri": "20"})
        jobs.update(self.vault, name, fields={"butce_usd": "1000", "harcanan_usd": "0"})  # an edited note
        err = self.refused("devam", name)
        self.assertIn("still over its budget ($3.20 / $3.00)", err)

    def test_devam_refusal_shows_small_amounts(self):
        name = self.stopped_job()
        self.ok("butce", name, "0.002")
        records.update(self.durum, name, {"harcanan_usd": "0.0061"})
        self.assertIn("($0.0061 / $0.002)", self.refused("devam", name))

    def test_a_running_job_without_a_record_gets_one_from_its_note_once(self):
        name = self.running_job("calisiyor")
        os.remove(records.path(self.durum, name))
        jobs.update(self.vault, name, status="tikandi", fields={"harcanan_usd": "1", "butce_usd": "2"})
        code, out, err = self.run_cli("devam", name)
        self.assertEqual(code, 0, err)
        self.assertIn("created the server record", err)
        rec = self.record(name)
        self.assertEqual((rec["oturum"], rec["butce_usd"], rec["harcanan_usd"]), (SESSION, "2", "1"))
        jobs.update(self.vault, name, status="tikandi", fields={"butce_usd": "0.5"})
        self.ok("devam", name)  # the note's later edit no longer counts
        self.assertEqual(self.record(name)["butce_usd"], "2")

    def test_devam_reopens_the_scorecard_row_and_counts_the_rounds(self):
        name = self.stopped_job(karne="yazildi")
        self.ok("devam", name)
        meta = self.job(name).meta
        self.assertEqual((meta["karne"], meta["devam_sayisi"]), ("", "1"))
        jobs.update(self.vault, name, status="tikandi")
        self.assertEqual(self.job(name).meta["karne"], "bekliyor", "the next final status writes the row again")
        self.ok("devam", name)
        self.assertEqual(self.job(name).meta["devam_sayisi"], "2")


    # --- B3 guard-rails, self-test jobs and per-tier budgets (owner decision 2026-11-12) ---

    def test_ekle_prints_warnings_and_still_adds_the_job(self):
        code, out, err = self.run_cli("ekle", "--proje", "blog", "--baslik", "Dal", "--katman", "kolay",
                                      "--hedef", "Dal adını bildir.", "--kontrol", "git rev-parse --abbrev-ref HEAD")
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(self.job(result["is"]).meta["durum"], "sirada", "a warning never blocks")
        self.assertEqual(len(result["uyarilar"]), 1)
        self.assertIn("her zaman geçer", result["uyarilar"][0])
        self.assertIn("UYARI: Kontrol (`git rev-parse --abbrev-ref HEAD`) her zaman geçer", err)
        clean = self.ok("ekle", "--proje", "blog", "--baslik", "Dal", "--katman", "kolay", "--hedef",
                        "Dal adını rapor.md dosyasına yaz.", "--kontrol", "test -s rapor.md && grep -q main rapor.md")
        self.assertNotIn("uyarilar", clean)

    def test_ekle_warns_when_a_change_brief_is_not_kod_and_on_an_explicit_model(self):
        result = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "lib/login.dart hatasını düzelt.",
                         "--model", "opus")
        self.assertEqual(len(result["uyarilar"]), 2, result)
        self.assertIn("kod katmanında olmalı", result["uyarilar"][0])
        self.assertIn("--model opus elle verildi", result["uyarilar"][1])

    def test_a_kod_job_whose_kontrol_cannot_fail_is_refused(self):
        for check in ("true", "git status", "pytest -q || true", "pytest -q; exit 0"):
            err = self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "lib/a.dart düzelt.",
                               "--katman", "kod", "--kontrol", check)
            self.assertIn("başarısız olamaz", err)
        self.assertEqual(jobs.list_jobs(self.vault), [])
        result = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "lib/a.dart düzelt.", "--katman",
                         "kod", "--kontrol", "cat lib/a.dart")
        self.assertIn("yalnız bir şeyin var olduğunu", result["uyarilar"][0], "a weak Kontrol is only a warning")
        for check in ("set -e; pytest -q; echo OK", "echo a#b && pytest -q"):  # review: real Kontrols are accepted
            self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "lib/a.dart düzelt.", "--katman", "kod",
                    "--kontrol", check)
        self.ok("zamanla", "ekle", "--ad", "gece", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--saat",
                "02:00", "--katman", "kod", "--kontrol", "set -e; pytest -q; echo OK")

    def test_ekle_takes_a_call_limit(self):
        self.cfg["default_max_calls"] = {"genel": 40, "kolay": 15}
        name = self.add("--cagri", "25")
        self.assertEqual((self.job(name).meta["max_cagri"], self.record(name)["max_cagri"]), ("25", "25"))
        result = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--katman", "kolay",
                         "--kontrol", "pytest -q", "--cagri", "40")
        self.assertIn("çağrı sınırı 40", result["uyarilar"][0])
        self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--cagri", "0")
        self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--cagri", "çok")
        brief = os.path.join(self.durum, "taslak", "is-1.json")
        os.makedirs(os.path.dirname(brief), exist_ok=True)
        with open(brief, "w", encoding="utf-8") as f:
            json.dump({"proje": "blog", "baslik": "x", "hedef": "y", "cagri": 12, "deneme": True}, f)
        name = self.ok("ekle", "--brief-dosya", brief)["is"]
        self.assertEqual((self.record(name)["max_cagri"], self.record(name)["deneme"]), ("12", "evet"))

    def test_ekle_marks_a_self_test_job_on_its_record(self):
        name = self.add("--deneme")
        self.assertEqual((self.record(name)["deneme"], self.job(name).meta["deneme"]), ("evet", "evet"))
        plain = self.add()
        self.assertEqual(self.record(plain)["deneme"], "", "the key exists: a note edit never stands in")
        jobs.update(self.vault, plain, fields={"deneme": "evet"})
        self.assertEqual(self.record(plain)["deneme"], "")

    def test_the_default_budget_comes_from_the_tier(self):
        self.cfg["tiers"] = {k: dict(v) for k, v in TIERS.items()}
        self.cfg["tiers"]["kolay"]["butce_usd"] = 0.3
        self.cfg["tiers"]["kod"]["butce_usd"] = 6
        kolay = self.add("--katman", "kolay", "--kontrol", "pytest -q")
        kod = self.add("--katman", "kod", "--kontrol", "pytest -q")
        genel = self.add()
        given = self.add("--katman", "kod", "--kontrol", "pytest -q", "--butce", "2")
        self.assertEqual([self.record(n)["butce_usd"] for n in (kolay, kod, genel, given)], ["0.3", "6", "3", "2"])

    def finished_job(self, karne_row=True, record=True):
        name = self.add("--katman", "kolay", "--kontrol", "pytest -q")
        jobs.update(self.vault, name, status="bitti", fields={"baslangic": "2026-11-10T18:40:00",
                                                             "bitis": "2026-11-10T18:41:00", "harcanan_usd": "0.01",
                                                             "kontrol_deneme": "1", "kontrol_sonuc": "gecti",
                                                             "karne": "yazildi"})
        if karne_row:
            karne.write_row(self.vault, self.job(name), None, NOW, record=self.record(name))
        if not record:
            os.remove(records.path(self.durum, name))
        return name

    def test_deneme_isaretle_marks_old_jobs_once(self):
        with_row = self.finished_job()
        without_record = self.finished_job(karne_row=False, record=False)
        result = self.ok("deneme-isaretle", with_row, without_record)
        self.assertEqual([(r["is"], r["kayit"], r["karne"]) for r in result["isaretlenen"]],
                         [(with_row, "vardi", "isaretlendi"), (without_record, "nottan", "satir-yok")])
        self.assertEqual(self.record(with_row)["deneme"], "evet")
        rec = self.record(without_record)
        self.assertEqual((rec["deneme"], rec["katman"], rec["butce_usd"]), ("evet", "kolay", "3"),
                         "a job without a record gets one from its note first")
        self.assertEqual(self.job(with_row).meta["deneme"], "evet")
        rows = karne._rows(self.vault)
        self.assertEqual([r["Deneme"] for r in rows], ["evet"])
        self.assertIn("deneme", karne.summary_text(self.vault).lower())
        again = self.ok("deneme-isaretle", with_row)
        self.assertEqual(again["isaretlenen"][0]["karne"], "zaten")
        self.assertEqual(again["isaretlenen"][0]["kayit"], "zaten")
        self.refused("deneme-isaretle", "2026-01-01-000000-yok.md")
        queued = self.add()
        self.refused("deneme-isaretle", queued)  # only finished jobs: a new one takes --deneme at ekle

    # --- specialisation (plan "Sonraki iş (9)" step 2) ---

    def test_ekle_prints_the_routed_specialisation_and_its_reason(self):
        out = self.ok("ekle", "--proje", "blog", "--baslik", "Giriş", "--hedef", "lib/login.dart düzelt",
                      "--katman", "kod", "--kontrol", "flutter test")
        self.assertEqual(out["uzmanlik"], "mobil")
        self.assertIn("lib/login.dart", out["uzmanlik_nedeni"])
        self.assertEqual(self.record(out["is"])["uzmanlik"], "mobil")
        self.assertEqual(self.job(out["is"]).meta["uzmanlik"], "mobil")
        plain = self.ok("ekle", "--proje", "blog", "--baslik", "Özet", "--hedef", "Durumu yaz.")
        self.assertEqual((plain["uzmanlik"], plain["uzmanlik_nedeni"]), ("genel", "belirsiz → genel"))

    def test_ekle_takes_an_explicit_specialisation_from_the_flag_or_the_brief_file(self):
        out = self.ok("ekle", "--proje", "blog", "--baslik", "Giriş", "--hedef", "lib/login.dart",
                      "--uzmanlik", "test")
        self.assertEqual((out["uzmanlik"], self.record(out["is"])["uzmanlik_kaynagi"]), ("test", "elle"))
        path = self.taslak("is.json", {"proje": "blog", "baslik": "x", "hedef": "y", "uzmanlik": "analiz"})
        self.assertEqual(self.ok("ekle", "--brief-dosya", path)["uzmanlik"], "analiz")
        before = len(jobs.list_jobs(self.vault))
        self.assertIn("bilinmeyen uzmanlık", self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef",
                                                          "y", "--uzmanlik", "devops"))
        self.assertEqual(len(jobs.list_jobs(self.vault)), before)

    def test_zamanla_ekle_keeps_an_explicit_specialisation(self):
        out = self.ok("zamanla", "ekle", "--ad", "sabah-ui", "--proje", "blog", "--baslik", "x", "--hedef",
                      "y", "--saat", "08:00", "--uzmanlik", "ui")
        self.assertEqual(out["uzmanlik"], "ui")
        import zamanla
        self.assertEqual(zamanla.load(self.durum, "sabah-ui")["uzmanlik"], "ui")
        routed = self.ok("zamanla", "ekle", "--ad", "sabah-api", "--proje", "blog", "--baslik", "API",
                         "--hedef", "Sunucu API uçlarını test et", "--saat", "08:00")
        self.assertEqual(routed["uzmanlik"], "backend")
        self.assertEqual(zamanla.load(self.durum, "sabah-api")["uzmanlik"], "")
        self.refused("zamanla", "ekle", "--ad", "aksam", "--proje", "blog", "--baslik", "x", "--hedef", "y",
                     "--saat", "18:00", "--uzmanlik", "devops")

    def test_zamanla_ekle_takes_deneme_warns_and_refuses_a_kod_kontrol_that_cannot_fail(self):
        result = self.ok("zamanla", "ekle", "--ad", "sabah", "--proje", "blog", "--baslik", "x", "--hedef", "y",
                         "--saat", "08:00", "--katman", "kolay", "--kontrol", "true", "--deneme")
        self.assertIn("her zaman geçer", result["uyarilar"][0])
        import zamanla
        self.assertTrue(zamanla.load(self.durum, "sabah")["deneme"])
        err = self.refused("zamanla", "ekle", "--ad", "aksam", "--proje", "blog", "--baslik", "x", "--hedef",
                           "y", "--saat", "18:00", "--katman", "kod", "--kontrol", "echo ok")
        self.assertIn("başarısız olamaz", err)


class ContractTest(unittest.TestCase):
    def test_ofis_py_path_in_contract_is_this_file(self):
        self.assertTrue(os.path.samefile(ofis.OFIS_PY, os.path.join(HERE, "..", "bin", "ofis.py")))


if __name__ == "__main__":
    unittest.main()
