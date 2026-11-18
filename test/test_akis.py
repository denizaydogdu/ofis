"""Tests for bin/akis.py (phase 4: workflows and review): templates, verdicts, step prompts, the workflow engine, the
Codex reviewer with its Claude fallback, the approval card and probation. Fake claude, fake codex, temp
vault/durum/projects only; the real codex is never reachable (fakes.py points OFIS_CODEX_BIN away from it)."""
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
import akis  # noqa: E402
import ceo  # noqa: E402
import claude_cli  # noqa: E402
import jobs  # noqa: E402
import karne  # noqa: E402
import kontrol  # noqa: E402
import launch  # noqa: E402
import model_durum  # noqa: E402
import ofis  # noqa: E402
import postoffice  # noqa: E402
import records  # noqa: E402

NOW = datetime(2026, 11, 11, 10, 0, 0)
PASS = "test -d ."  # a Kontrol that passes in the test folder (a kod Kontrol that always passes is refused)
TIERS = {"planlama": {"model": "fable", "effort": "high"}, "kod": {"model": "opus", "effort": "high"},
         "inceleme": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet", "effort": "medium"},
         "kolay": {"model": "haiku", "effort": "low"}}


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@x"))


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.realpath(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        with open(os.path.join(self.folder, name + ".json"), "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_the_shipped_templates_are_valid(self):
        g = akis.load_template("gelistir", {"tiers": TIERS})
        self.assertEqual([s["tur"] for s in g["adimlar"]], ["plan", "plan-inceleme", "kod", "kod-inceleme", "onay"])
        self.assertEqual([s["katman"] for s in g["adimlar"]], ["planlama", "inceleme", "kod", "inceleme", ""])
        self.assertEqual(g["adimlar"][3]["yurutucu"], "codex")
        k = akis.load_template("kucuk-is", {"tiers": TIERS})
        self.assertEqual([s["tur"] for s in k["adimlar"]], ["kod", "kod-inceleme", "onay"])

    def test_a_bad_template_is_refused(self):
        good = [{"tur": "kod"}, {"tur": "kod-inceleme"}, {"tur": "onay"}]
        cases = {
            "bilinmeyen-tur": {"ad": "x", "adimlar": [{"tur": "deploy"}]},
            "bilinmeyen-katman": {"ad": "x", "adimlar": [{"tur": "kod", "katman": "dev"}]},
            "bilinmeyen-alan": {"ad": "x", "adimlar": good, "komut": "rm -rf /"},
            "adim-alani": {"ad": "x", "adimlar": [{"tur": "kod", "komut": "x"}]},
            "onay-sonda-degil": {"ad": "x", "adimlar": [{"tur": "onay"}, {"tur": "kod"}]},
            "inceleme-yalniz": {"ad": "x", "adimlar": [{"tur": "plan-inceleme"}]},
            "kod-inceleme-yalniz": {"ad": "x", "adimlar": [{"tur": "plan"}, {"tur": "kod-inceleme"}]},
            "iki-kod": {"ad": "x", "adimlar": [{"tur": "kod"}, {"tur": "kod"}]},
            "cok-adim": {"ad": "x", "adimlar": [{"tur": "plan"}, {"tur": "plan-inceleme"}] * 5},
            "bos": {"ad": "x", "adimlar": []},
            "yurutucu": {"ad": "x", "adimlar": [{"tur": "kod"}, {"tur": "kod-inceleme", "yurutucu": "gpt"}]},
            "yurutucu-kodda": {"ad": "x", "adimlar": [{"tur": "kod", "yurutucu": "codex"}]},
            "uzun-aciklama": {"ad": "x", "aciklama": "a" * 400, "adimlar": good},
            "ad-uyusmuyor": {"ad": "baska", "adimlar": good},
            "yalniz-onay": {"ad": "x", "adimlar": [{"tur": "onay"}]},
            "plan-kod-katmani": {"ad": "x", "adimlar": [{"tur": "plan", "katman": "kod"}]},
        }
        for name, data in cases.items():
            data = dict(data, ad=name if data["ad"] == "x" else data["ad"])
            self.write(name, data)
            with self.subTest(name=name):
                with self.assertRaises(akis.TemplateError):
                    akis.load_template(name, {"tiers": TIERS}, folder=self.folder)
        self.write("bozuk", "{not json")
        with self.assertRaises(akis.TemplateError):
            akis.load_template("bozuk", {"tiers": TIERS}, folder=self.folder)
        for bad in ("../gelistir", "Gelistir", "", "a/b"):
            with self.assertRaises(akis.TemplateError):
                akis.load_template(bad, {"tiers": TIERS}, folder=self.folder)
        target = os.path.join(self.folder, "real.json")
        self.write("real", {"ad": "link", "adimlar": good})
        os.symlink(target, os.path.join(self.folder, "link.json"))
        with self.assertRaises(akis.TemplateError):
            akis.load_template("link", {"tiers": TIERS}, folder=self.folder)


class VerdictTest(unittest.TestCase):
    def test_the_last_karar_line_decides(self):
        self.assertEqual(akis.parse_verdict("Bulgu yok.\nKARAR: ONAY"), "ONAY")
        self.assertEqual(akis.parse_verdict("KARAR: ONAY\n...\n**KARAR: DÜZELT**\n"), "DÜZELT")
        self.assertEqual(akis.parse_verdict("karar: duzelt"), "DÜZELT")
        self.assertEqual(akis.parse_verdict("- KARAR: Düzelt."), "DÜZELT")
        self.assertIsNone(akis.parse_verdict("Her şey iyi görünüyor."))
        self.assertIsNone(akis.parse_verdict("KARAR: belki"))
        self.assertIsNone(akis.parse_verdict("KARAR: ONAY\nKARAR: belki"), "a garbled last line is not skipped")

    def test_findings_and_outcome(self):
        text = "MAJOR: giriş boş parolayı kabul ediyor\n- MINOR: log satırı eksik\nKARAR: DÜZELT"
        outcome, found = akis.review_outcome(text)
        self.assertEqual(outcome, "duzelt")
        self.assertEqual([s for s, _ in found], ["MAJOR", "MINOR"])
        self.assertEqual(akis.review_outcome("1. MINOR: isim\n**MINOR** yorum\nKARAR: DÜZELT")[0], "onay",
                         "MINOR-only is an ONAY")
        self.assertEqual(akis.review_outcome("BLOCKER: veri kaybı\nKARAR: ONAY")[0], "duzelt",
                         "a BLOCKER is never approved")
        self.assertEqual(akis.review_outcome("KARAR: DÜZELT")[0], "duzelt")
        self.assertEqual(akis.review_outcome("bitti")[0], "eksik")

    def test_findings_wrapped_in_backticks(self):
        # live trial 2026-11-11: free reviewers (and Codex) wrap the whole finding, or the label, in backticks
        text = ("- `BLOCKER: stats.py:15 — last_n davranışı değişti.` `start = len(values) - n + 1` kayma.\n"
                "`MAJOR: a.py:3 boş liste`\n"
                "* **`MINOR:`** yorum eski\n"
                "1. `MAJOR`: b.py:9 hata\n"
                "- **MAJOR: c.py:4 bir eksik.** `start` örneği\n"
                "Kod içinde `MAJOR: değil` bir satır\n"
                "KARAR: DÜZELT")
        self.assertEqual(akis.findings(text), [
            ("BLOCKER", "BLOCKER: stats.py:15 — last_n davranışı değişti. `start = len(values) - n + 1` kayma."),
            ("MAJOR", "MAJOR: a.py:3 boş liste"),
            ("MINOR", "MINOR: yorum eski"),
            ("MAJOR", "MAJOR: b.py:9 hata"),
            ("MAJOR", "MAJOR: c.py:4 bir eksik. `start` örneği")])
        self.assertEqual(akis.review_outcome(text)[0], "duzelt")
        self.assertNotIn("`MAJOR", akis.REVIEW_RULES, "the example teaches no backticks")

    def test_none_statements_are_not_findings(self):
        # live trial 2026-11-12: GLM wrote "BLOCKER: ya da MAJOR bulunamadı." and the hakem was called for nothing
        for line in ("BLOCKER: ya da MAJOR bulunamadı.", "BLOCKER veya MAJOR bulgu yok.", "- MAJOR: yok",
                     "**BLOCKER:** Bulunmadı.", "MAJOR: bulgu yok", "BLOCKER: tespit edilmedi.", "MAJOR: None",
                     "BLOCKER: none found", "MAJOR: no blocker or major issues found", "BLOCKER: No major findings.",
                     "MAJOR: not found", "BLOCKER: N/A", "MAJOR: —", "BLOCKER: -", "BLOCKER/MAJOR: yok",
                     "`BLOCKER`: ya da `MAJOR` bulunamadı", "MINOR: yok.", "BLOCKER, MAJOR: hiç bulgu yok",
                     "BLOCKER ve MAJOR: ciddi bulgu yok", "MAJOR: herhangi bir sorun tespit edilmedi."):
            self.assertEqual(akis.findings(line), [], line)
            self.assertEqual(akis.review_outcome(line + "\nKARAR: ONAY")[0], "onay", line)
        real = ("MAJOR: a.py:3 null kontrolü yok\n"
                "BLOCKER: yetki kontrolü yok, herkes silebilir\n"
                "MAJOR: kontrol yok\n"
                "MINOR: test bulunamadı: login_test.py\n"
                "BLOCKER: none of the inputs are validated\n"
                "MAJOR: ya da b.py:9 boş liste çöküyor\n"
                "KARAR: DÜZELT")
        self.assertEqual([s for s, _ in akis.findings(real)], ["MAJOR", "BLOCKER", "MAJOR", "MINOR", "BLOCKER", "MAJOR"])
        self.assertEqual(akis.findings(real)[0], ("MAJOR", "MAJOR: a.py:3 null kontrolü yok"))
        self.assertEqual(akis.review_outcome(real)[0], "duzelt")

    def test_the_rules_say_how_to_write_no_finding(self):
        self.assertIn(akis.NO_FINDING_RULE, akis.REVIEW_RULES)
        self.assertIn("Ciddi bulgu yok.", akis.NO_FINDING_RULE)
        self.assertEqual(akis.findings(akis.NO_FINDING_LINE), [])
        prompt = akis.codex_prompt({"baslik": "t", "brief": {"hedef": "h"}}, "abc", "a.py | 1 +")
        self.assertIn(akis.NO_FINDING_RULE, prompt)
        self.assertIn(akis.NO_FINDING_RULE, akis.denetci.security_prompt({"baslik": "t", "brief": {"hedef": "h"}}, "+x"))

    def test_approval_phrases(self):
        for text in ("Onaylıyorum", "onaylıyorum.", "Evet, onaylıyorum!", "ONAY", "tamam"):
            self.assertTrue(akis.is_approval(text), text)
        for text in ("Onaylıyorum ama testleri de ekle", "hayır", "commit et", "evet ama bekle"):
            self.assertFalse(akis.is_approval(text), text)

    def test_budget_split(self):
        self.assertEqual(akis.split_budget(8, ["plan", "plan-inceleme", "kod", "kod-inceleme", "onay"]),
                         ["2", "1", "4", "1", ""])
        self.assertEqual(akis.split_budget(3, ["kod", "kod-inceleme", "onay"]), ["2.4", "0.6", ""])
        self.assertEqual(akis.split_budget(0.2, ["kod", "kod-inceleme", "onay"]), ["0.16", "0.5", ""],
                         "a share is never below the minimum; a review share covers one Claude review")
        self.assertEqual(akis.split_budget(0.2, ["plan", "plan-inceleme"]), ["0.13", "0.5"])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "ajan-ofisi")
        self.durum = os.path.join(self.root, "durum")
        self.project = os.path.join(base, "Dev", "blog")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.projects_dir = os.path.join(base, "projects")
        for d in (self.root, self.project, self.vault):
            os.makedirs(d)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.codex = fakes.FakeCodex(os.path.join(base, "fakecodex"))
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault, "default_budget_usd": 3,
                    "projects": {"blog": {"path": self.project}}, "tiers": TIERS, "default_tier": "genel",
                    "default_max_calls": {"kod": 120, "inceleme": 60, "planlama": 60, "genel": 40, "kolay": 15},
                    "akis_deneme_kosusu": 0, "codex_bin": self.codex.path, "codex_timeout_s": 30,
                    "kontrol_timeout_s": 30}
        self.cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)
        self.t = 1000.0
        kw = {"clock": lambda: self.t, "sleep": lambda s: None, "find_attempts": 3}
        self.ceo = ceo.CeoController(self.cli, self.root, "ofis-ceo", self.durum, self.projects_dir, **kw)
        self.po = postoffice.PostOffice(self.cfg, self.cli, self.ceo, self.durum, self.projects_dir,
                                        now=lambda: NOW, channel_kwargs=kw, log=io.StringIO(), clock=lambda: self.t)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, claude_bin=self.fake.path,
                         now=lambda: NOW, out=out, err=err, cwd=cwd or self.project)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv, **kw):
        code, out, err = self.run_cli(*argv, **kw)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def refused(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 1, out)
        self.assertTrue(err.startswith("REFUSED: "), err)
        return err

    def start(self, template="gelistir", *extra, kontrol=PASS):
        return self.ok("akis", template, "--proje", "blog", "--baslik", "Giriş hatası", "--hedef",
                       "Boş parola reddedilsin.", "--kontrol", kontrol, *extra)

    def job(self, name):
        return jobs.load(self.vault, name)

    def status(self, name):
        return self.job(name).meta["durum"]

    def state(self, grup):
        return akis.load_state(self.durum, grup)

    def latest(self, grup, kind):
        step = next(s for s in self.state(grup)["adimlar"] if s["tur"] == kind)
        return step["isler"][-1]

    def report(self, name, tur, text):
        session = records.load(self.durum, name)["oturum"]
        self.ok("bildir", "--oturum", session, "--tur", tur, text)
        self.po.process_inbox()

    def prompts(self):
        """{session name: prompt} of the claude starts so far."""
        out = {}
        for c in self.fake.calls():
            if c["args"][:2] == ["--bg", "--name"] and c["args"][2] != "ofis-ceo":
                out[c["args"][2]] = c["args"][-1]
        return out

    def prompt_of(self, name):
        return self.prompts()[records.load(self.durum, name)["oturum"]]

    def ceo_queue(self):
        return [q["text"] for q in self.ceo.queue()]

    def outbox(self):
        folder = os.path.join(self.durum, "giden")
        out = []
        for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if n.endswith(".json"):
                with open(os.path.join(folder, n), encoding="utf-8") as f:
                    out.append(json.load(f))
        return out

    def card(self, grup):
        name = self.state(grup)["onay_karti"]
        with open(os.path.join(self.vault, "Kararlar", name), encoding="utf-8") as f:
            return name, f.read()

    def run_kod(self, grup, text="Giriş düzeldi; 3 test geçti."):
        """Starts the kod step, reports bitti and runs its Kontrol (true)."""
        self.assertTrue(self.po.dispatch())
        kod = self.latest(grup, "kod")
        self.assertEqual(self.status(kod), "calisiyor")
        self.report(kod, "bitti", text)
        self.assertEqual(self.status(kod), "kontrolde")
        self.po.kontrol.run_pending()
        self.assertEqual(self.status(kod), "bitti")
        return kod

    def run_plan(self, grup, plan="1. login.py: boş parolayı reddet.\n2. test_login.py: test ekle.",
                 review="Bulgu yok.\nKARAR: ONAY"):
        self.assertTrue(self.po.dispatch())
        plan_job = self.latest(grup, "plan")
        self.report(plan_job, "bitti", plan)
        self.assertTrue(self.po.dispatch())
        review_job = self.latest(grup, "plan-inceleme")
        self.assertEqual(self.status(review_job), "calisiyor")
        self.report(review_job, "bitti", review)
        return plan_job, review_job

    def codex_review(self):
        self.po.check_active()
        self.po.codex.run_pending()


class CreateTest(Base):
    def test_akis_creates_the_chained_step_jobs_with_trusted_fields(self):
        out = self.start("gelistir", "--butce", "8")
        grup, names = out["grup"], out["isler"]
        self.assertTrue(grup.startswith("akis-1111-100000-blog"), grup)
        self.assertEqual(len(names), 5)
        kinds = ["plan", "plan-inceleme", "kod", "kod-inceleme", "onay"]
        for i, (name, kind) in enumerate(zip(names, kinds), start=1):
            job, rec = self.job(name), records.load(self.durum, name)
            self.assertEqual(job.meta["durum"], "sirada")
            self.assertEqual((rec["akis"], rec["adim"], rec["adim_turu"]), (grup, str(i), kind))
            self.assertEqual((job.meta["akis"], job.meta["adim"], job.meta["adim_turu"]), (grup, str(i), kind))
            self.assertEqual((job.meta["grup"], rec["grup"]), (grup, grup))
            self.assertEqual(rec.get("bagimli", ""), names[i - 2] if i > 1 else "")
        self.assertEqual([records.load(self.durum, n)["katman"] for n in names[:4]],
                         ["planlama", "inceleme", "kod", "inceleme"])
        self.assertEqual([records.load(self.durum, n)["butce_usd"] for n in names[:4]], ["2", "1", "4", "1"])
        self.assertEqual(kontrol.load(self.durum, names[2]), PASS, "the kod step has the Kontrol")
        for n in (names[0], names[1], names[3], names[4]):
            self.assertIsNone(kontrol.load(self.durum, n), "only the kod step runs the Kontrol")
        self.assertEqual(records.load(self.durum, names[3])["inceleme_yurutucu"], "codex")
        self.assertEqual(self.job(names[3]).meta["yurutucu"], "codex")
        state = self.state(grup)
        self.assertEqual((state["sablon"], state["durum"], state["butce_usd"], state["deneme"]),
                         ("gelistir", "calisiyor", "8", False))
        self.assertEqual([s["isler"] for s in state["adimlar"]], [[n] for n in names])

    def test_default_budget_is_the_default_per_session_step(self):
        out = self.start("kucuk-is")
        self.assertEqual(self.state(out["grup"])["butce_usd"], "6")
        self.assertEqual([records.load(self.durum, n)["butce_usd"] for n in out["isler"][:2]], ["4.8", "1.2"])

    def test_the_default_budget_is_the_sum_of_the_step_tiers(self):
        self.cfg["tiers"] = {k: dict(v) for k, v in TIERS.items()}
        for tier, usd in (("planlama", 3), ("kod", 6), ("inceleme", 1), ("genel", 1.5), ("kolay", 0.3)):
            self.cfg["tiers"][tier]["butce_usd"] = usd
        out = self.start("gelistir")
        self.assertEqual(out["butce_usd"], "11")
        self.assertEqual([records.load(self.durum, n)["butce_usd"] for n in out["isler"][:4]],
                         ["2.75", "1.38", "5.5", "1.38"])
        small = self.start("kucuk-is", "--butce", "2")
        self.assertEqual([records.load(self.durum, n)["butce_usd"] for n in small["isler"][:2]], ["1.6", "0.5"],
                         "the review share covers one Claude review")

    def test_a_kod_kontrol_that_cannot_fail_is_refused(self):
        for check in ("true", "echo '3 passed'", "git status", "pytest -q || true"):
            err = self.refused("akis", "kucuk-is", "--proje", "blog", "--baslik", "x", "--hedef", "y",
                               "--kontrol", check)
            self.assertIn("başarısız olamaz", err)
        self.assertEqual(jobs.list_jobs(self.vault), [])
        weak = self.ok("akis", "kucuk-is", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--kontrol",
                       "cat login.py")
        self.assertIn("yalnız bir şeyin var olduğunu", " ".join(weak["uyarilar"]))

    def test_a_review_share_below_an_observed_claude_review_is_a_warning(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        row = ("| 2026-11-11 | blog | [[eski]] | inceleme | Kıdemli (opus) | high | yok | 0 | hayır | 2 | 0.9000 |  "
               "| 0 | bitti | 0 | akis-x | kod-inceleme |  | evet |\n")
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write(karne._table_head(karne.COLUMNS) + row)
        code, out, err = self.run_cli("akis", "kucuk-is", "--proje", "blog", "--baslik", "x", "--hedef", "y",
                                      "--kontrol", PASS, "--butce", "2")
        self.assertEqual(code, 0, err)
        self.assertIn("UYARI: kod-inceleme payı $0.5", err)
        self.assertIn("$0.9", json.loads(out)["uyarilar"][0])

    def test_a_self_test_workflow_marks_every_step_and_the_onay_step_is_denizs(self):
        out = self.start("kucuk-is", "--deneme")
        self.assertTrue(out["deneme_isi"])
        self.assertFalse(out["deneme"], "probation is another thing")
        self.assertEqual([records.load(self.durum, n)["deneme"] for n in out["isler"]], ["evet"] * 3)
        onay = out["isler"][2]
        rec, meta = records.load(self.durum, onay), self.job(onay).meta
        self.assertEqual((rec["katman"], rec["model"], rec["effort"], rec["max_cagri"]), ("onay", "deniz", "", ""))
        self.assertEqual((meta["katman"], meta["model"]), ("onay", "deniz"))
        plain = self.start("kucuk-is")
        self.assertEqual([records.load(self.durum, n)["deneme"] for n in plain["isler"]], [""] * 3)
        self.assertEqual(records.load(self.durum, plain["isler"][0])["katman"], "kod")

    def test_refusals_create_nothing(self):
        for argv in (("akis", "yok", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--kontrol", PASS),
                     ("akis", "gelistir", "--proje", "blog", "--baslik", "x", "--hedef", "y"),
                     ("akis", "gelistir", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--kontrol", PASS,
                      "--butce", "nan"),
                     ("akis", "gelistir", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--kontrol",
                      "cd ~/Dev/zim && make"),
                     ("akis", "gelistir", "--proje", "yok", "--baslik", "x", "--hedef", "y", "--kontrol", PASS),
                     ("akis", "gelistir", "--proje", "blog", "--baslik", "x", "--kontrol", PASS)):
            with self.subTest(argv=argv):
                self.refused(*argv)
        self.assertEqual(jobs.list_jobs(self.vault), [])
        self.assertFalse(os.path.isdir(os.path.join(self.durum, "akislar")) and
                         [n for n in os.listdir(os.path.join(self.durum, "akislar")) if n != "sayac.json"])

    def test_every_step_gets_its_specialisation(self):
        # plan "Sonraki iş (9)" step 2: the review steps follow their step, the kod step is routed
        out = self.ok("akis", "gelistir", "--proje", "blog", "--baslik", "Giriş ekranı", "--hedef",
                      "lib/login.dart boş parolayı reddetsin.", "--kontrol", PASS)
        names = out["isler"]
        recs = [records.load(self.durum, n) for n in names]
        self.assertEqual([r["uzmanlik"] for r in recs[:4]], ["mobil", "analiz", "mobil", "test"])
        self.assertEqual([r["uzmanlik_kaynagi"] for r in recs[:4]], ["kural", "adim", "kural", "adim"])
        self.assertEqual(recs[4]["uzmanlik"], "")  # the approval card is the owner's: no specialisation
        self.assertEqual(out["uzmanlik"], "mobil")

    def test_an_explicit_specialisation_names_the_kod_step_only(self):
        out = self.ok("akis", "kucuk-is", "--proje", "blog", "--baslik", "x", "--hedef", "lib/a.dart düzelt",
                      "--kontrol", PASS, "--uzmanlik", "ui")
        recs = [records.load(self.durum, n) for n in out["isler"]]
        self.assertEqual([(r["uzmanlik"], r["uzmanlik_kaynagi"]) for r in recs[:2]],
                         [("ui", "elle"), ("test", "adim")])
        self.assertIn("uzmanl", self.refused("akis", "kucuk-is", "--proje", "blog", "--baslik", "x", "--hedef",
                                             "y", "--kontrol", PASS, "--uzmanlik", "devops"))

    def test_the_kod_step_is_routed_again_with_the_plan_at_its_start(self):
        out = self.start("gelistir")
        grup, names = out["grup"], out["isler"]
        self.assertEqual(records.load(self.durum, names[2])["uzmanlik"], "genel")
        self.run_plan(grup, plan="1. backend/src/main/java/LoginController.java: boş parolayı reddet.\n"
                                 "2. LoginService.java: kontrol ekle.")
        self.assertEqual(self.po.dispatch(), [names[2]])
        rec = records.load(self.durum, names[2])
        self.assertEqual((rec["uzmanlik"], rec["uzmanlik_kaynagi"]), ("backend", "kural"))
        self.assertIn("LoginController.java", rec["uzmanlik_nedeni"])
        self.assertEqual(self.job(names[2]).meta["uzmanlik"], "backend")
        self.assertIn("Rolün: Kıdemli Backend", self.fake.calls()[-1]["args"][
            self.fake.calls()[-1]["args"].index("--append-system-prompt") + 1])

    def test_an_escalated_kod_step_keeps_its_specialisation_at_start(self):
        out = self.start("gelistir")
        grup, names = out["grup"], out["isler"]
        records.update(self.durum, names[2], {"uzmanlik": "mobil", "uzmanlik_kaynagi": "yukseltme"})
        self.run_plan(grup, plan="1. backend/src/main/java/LoginController.java")
        self.po.dispatch()
        rec = records.load(self.durum, names[2])
        self.assertEqual((rec["uzmanlik"], rec["uzmanlik_kaynagi"]), ("mobil", "yukseltme"))

    def test_an_explicit_kod_specialisation_survives_the_plan(self):
        out = self.start("gelistir", "--uzmanlik", "mobil")
        grup, names = out["grup"], out["isler"]
        self.run_plan(grup, plan="1. backend/src/main/java/LoginController.java")
        self.po.dispatch()
        self.assertEqual(records.load(self.durum, names[2])["uzmanlik"], "mobil")

    def test_the_brief_may_come_from_a_file(self):
        folder = os.path.join(self.durum, "taslak")
        os.makedirs(folder)
        path = os.path.join(folder, "akis-1.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"proje": "blog", "baslik": "Parola sıfırlama", "hedef": "Bağlantı çalışsın.",
                       "kontrol": PASS, "butce": 4}, f)
        out = self.ok("akis", "kucuk-is", "--brief-dosya", path)
        self.assertEqual(self.state(out["grup"])["baslik"], "Parola sıfırlama")
        self.assertFalse(os.path.exists(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"proje": "blog", "baslik": "x", "hedef": "y", "kontrol": PASS, "katman": "kod"}, f)
        self.assertIn("katman", self.refused("akis", "kucuk-is", "--brief-dosya", path))

    def test_probation_holds_every_step_of_the_first_runs(self):
        del self.cfg["akis_deneme_kosusu"]
        held, outs = [], []
        for _ in range(4):
            out = self.start("kucuk-is")
            outs.append(out)
            held.append([records.load(self.durum, n).get("beklet", "") for n in out["isler"]])
            self.assertEqual(out["deneme"], held[-1][0] == "evet")
        self.assertEqual(held, [["evet"] * 3] * 3 + [["", "", ""]])
        with open(os.path.join(self.durum, "akislar", "sayac.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"kucuk-is": 4})
        self.assertEqual(self.po.dispatch(), [outs[3]["isler"][0]], "held steps wait for serbest; the 4th run is free")
        first = self.state(self.ok("akis", "gelistir", "--proje", "blog", "--baslik", "x", "--hedef", "y",
                                   "--kontrol", PASS)["grup"])
        self.assertTrue(first["deneme"], "probation counts per template")

    def test_a_running_server_from_before_workflows_refuses_them(self):
        # deployment: an old server's dispatcher would start the steps as plain jobs (no gate, a session for onay)
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "server.lock"), "w") as f:
            f.write(f"{os.getpid()}\n")
        self.assertIn("yeniden başlat", self.refused("akis", "kucuk-is", "--proje", "blog", "--baslik", "x",
                                                    "--hedef", "y", "--kontrol", PASS))
        self.assertEqual(jobs.list_jobs(self.vault), [])
        with open(os.path.join(self.durum, "sunucu.json"), "w") as f:
            json.dump({"pid": os.getpid(), "akis": akis.SERVER_VERSION}, f)
        self.start("kucuk-is")
        with open(os.path.join(self.durum, "server.lock"), "w") as f:
            f.write("999999999\n")  # no such process: no server runs, the jobs simply wait for one
        os.remove(os.path.join(self.durum, "sunucu.json"))
        self.ok("akis", "kucuk-is", "--proje", "blog", "--baslik", "y", "--hedef", "y", "--kontrol", PASS)
        akis.announce(self.durum)
        with open(os.path.join(self.durum, "sunucu.json")) as f:
            self.assertEqual(json.load(f), {"pid": os.getpid(), "akis": akis.SERVER_VERSION})

    def test_a_workflow_counts_once_in_the_project_queue(self):
        self.cfg["max_queued_per_project"] = 2
        self.start("gelistir")
        self.ok("ekle", "--proje", "blog", "--baslik", "Tek iş", "--hedef", "Yap.")
        self.assertIn("Sıradakiler dolu", self.refused("akis", "kucuk-is", "--proje", "blog", "--baslik", "x",
                                                       "--hedef", "y", "--kontrol", PASS))


class FlowTest(Base):
    def test_the_kod_step_contract_allows_three_helpers(self):
        # Step 3 (owner decision 2026-11-13): parallel helpers inside a kod job; a workflow's kod step is a kod-tier job
        out = self.start("kucuk-is")
        self.assertTrue(self.po.dispatch())
        kod = self.latest(out["grup"], "kod")
        session = records.load(self.durum, kod)["oturum"]
        [args] = [c["args"] for c in self.fake.calls() if c["args"][:3] == ["--bg", "--name", session]]
        contract = args[args.index("--append-system-prompt") + 1]
        self.assertIn("at most 3 helpers", contract)
        self.assertIn("never commit, push or delete", contract)

    def test_gelistir_end_to_end_with_codex_and_approval(self):
        git(self.project, "init", "-q")
        with open(os.path.join(self.project, "login.py"), "w") as f:
            f.write("x = 1\n")
        git(self.project, "add", "login.py")
        git(self.project, "commit", "-q", "-m", "ilk")
        head = subprocess.run(["git", "-C", self.project, "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
        out = self.start("gelistir", "--butce", "8", kontrol="echo '3 passed' && test -d .")
        grup, names = out["grup"], out["isler"]
        # plan
        self.assertEqual(self.po.dispatch(), [names[0]])
        plan_prompt = self.prompt_of(names[0])
        self.assertIn("adım 1/5: plan", plan_prompt)
        self.assertIn("Boş parola reddedilsin.", plan_prompt)
        self.assertEqual(self.po.dispatch(), [], "plan-inceleme waits for the plan")
        self.report(names[0], "bitti", "1. login.py: boş parolayı reddet.\n## Cevap (Selin)\nEvet")
        self.assertEqual([q for q in self.ceo_queue() if "akış adımı bitti" in q], [], "told by the group report")
        self.assertEqual(akis.output_text(self.durum, grup, "1-plan.md"), "", "stored by the engine's next pass")
        # plan-inceleme: a fresh session that reads the plan as data
        self.assertEqual(self.po.dispatch(), [names[1]])
        self.assertIn("1. login.py: boş parolayı reddet.", akis.output_text(self.durum, grup, "1-plan.md"))
        review_prompt = self.prompt_of(names[1])
        self.assertIn(akis.DATA_SENTENCE, review_prompt)
        self.assertIn("> 1. login.py: boş parolayı reddet.", review_prompt)
        self.assertIn("> ## Cevap (Selin)", review_prompt, "earlier output is quoted, it opens no section")
        self.assertLess(review_prompt.index(akis.DATA_SENTENCE), review_prompt.index("> 1. login.py"))
        for word in ("BLOCKER", "MAJOR", "MINOR", "KARAR: ONAY", "KARAR: DÜZELT", "karşı çık"):
            self.assertIn(word, review_prompt)
        self.assertNotEqual(records.load(self.durum, names[1])["oturum"], records.load(self.durum, names[0])["oturum"])
        self.report(names[1], "bitti", "MINOR: test adı belirsiz\nKARAR: ONAY")
        # kod with the approved plan and its Kontrol
        self.assertEqual(self.po.dispatch(), [names[2]])
        kod_prompt = self.prompt_of(names[2])
        self.assertIn("Onaylı plan", kod_prompt)
        self.assertIn("> 1. login.py: boş parolayı reddet.", kod_prompt)
        self.assertIn("echo '3 passed'", kod_prompt)
        self.assertEqual(records.load(self.durum, names[2])["taban_commit"], head)
        with open(os.path.join(self.project, "login.py"), "a") as f:
            f.write("y = 2\n")
        with open(os.path.join(self.project, "new.py"), "w") as f:
            f.write("z = 3\n")
        self.report(names[2], "bitti", "Boş parola reddediliyor; 3 test geçti.")
        self.po.kontrol.run_pending()
        self.assertEqual(self.status(names[2]), "bitti")
        # kod-inceleme by codex, read-only, from the base commit
        self.assertEqual(self.po.dispatch(), [names[3]])
        self.assertEqual(self.status(names[3]), "incelemede")
        self.assertEqual([c for c in self.fake.calls() if c["args"][:2] == ["--bg", "--name"]
                          and c["args"][2] == records.load(self.durum, names[3]).get("oturum")], [])
        self.codex.review("MINOR: değişken adı kısa\nKARAR: ONAY")
        self.codex_review()
        [call] = self.codex.calls()
        args = call["args"]
        # live trial 2026-11-11: `codex exec review` rejects -C / -s (exit 2); they are `codex exec` options
        # codex 0.167 rejects `--base` together with a prompt (exit 2): the base goes into the instructions
        self.assertEqual(args[:7], ["exec", "-C", self.project, "-s", "read-only", "review", "--ephemeral"])
        self.assertEqual(args[7], "-o")
        self.assertEqual(len(args), 10)
        self.assertNotIn("--base", args)
        self.assertIn("KARAR:", args[-1])
        self.assertIn(f"git diff {head}", args[-1])
        self.assertIn("new.py", args[-1])  # an untracked new file is named in the instructions
        self.assertEqual(self.status(names[3]), "bitti")
        self.assertEqual(records.load(self.durum, names[3])["inceleme_yurutucu"], "codex")
        # onay: a decision card with evidence, nothing committed
        self.assertEqual(self.po.dispatch(), [names[4]])
        self.assertEqual(self.status(names[4]), "karar-bekliyor")
        note, card = self.card(grup)
        _, meta, body = jobs.parse(card)
        self.assertEqual((meta["durum"], meta["tur"], meta["akis"], meta["is"]),
                         ("bekliyor", "akis-onay", grup, names[4]))
        for heading in ("Soru", "Nasıl test edildi", "Kontrol neyi kanıtladı / kanıtlamadı",
                        "Ajanın kararları ve varsayımları", "Plan özeti", "Değişiklik özeti", "İnceleme", "Kullanım"):
            self.assertTrue(jobs.section(body, heading), heading)
        self.assertIn("login.py", jobs.section(body, "Değişiklik özeti"))
        self.assertIn("> 1. login.py", jobs.section(body, "Plan özeti"))
        self.assertIn("3 passed", jobs.section(body, "Nasıl test edildi"), "the Kontrol's output tail")
        self.assertIn("ONAY", jobs.section(body, "İnceleme"))
        self.assertIn("değişken adı kısa", jobs.section(body, "İnceleme"))
        self.assertIn("codex", jobs.section(body, "İnceleme"))
        self.assertIn("commit edilmedi", card)
        self.assertEqual(jobs.section(body, "Cevap (Selin)"), "")
        self.assertTrue(any("onay bekliyor" in n and note[:-3] in n for n in self.ceo_queue()))
        log = subprocess.run(["git", "-C", self.project, "log", "--oneline"], capture_output=True, text=True).stdout
        self.assertEqual(len(log.splitlines()), 1, "a workflow never commits")
        # The owner approves
        result = self.ok("cevapla", note, "Onaylıyorum")
        self.assertEqual((result["akis"], result["akis_sonuc"]), (grup, "onaylandi"))
        self.assertEqual([self.status(n) for n in names], ["bitti"] * 5)
        self.assertEqual(self.state(grup)["durum"], "bitti")
        self.assertEqual(self.outbox(), [], "an approval has no session to answer")
        _, meta, _ = jobs.parse(open(os.path.join(self.vault, "Kararlar", note), encoding="utf-8").read())
        self.assertEqual(meta["durum"], "cevaplandi")
        # phase 5: one group report and one notice for the whole workflow
        self.assertEqual([q for q in self.ceo_queue() if "akış adımı bitti" in q or "işi bitti" in q], [])
        self.po.process_karne()
        with open(os.path.join(self.vault, "Raporlar", f"{grup}.md"), encoding="utf-8") as f:
            report = f.read()
        _, meta, body = jobs.parse(report)
        self.assertEqual((meta["grup"], meta["tur"], meta["durum"]), (grup, "akis", "tamam"))
        flow = jobs.section(body, "Akış")
        self.assertIn("Selin onayladı", flow)
        self.assertIn("ONAY (yürütücü: codex)", flow)
        self.assertIn("> MINOR: değişken adı kısa", flow)
        for name in names:
            self.assertIn(f"[[{jobs.stem(name)}]]", jobs.section(body, "İşler"))
        # login.py is a sensitive path (risk yüksek): the security reviewer ran too, so the review job has a cost
        self.assertIn("(Codex hariç)", jobs.section(body, "İşler"))
        notices = [q for q in self.ceo_queue() if "grubu bitti" in q]
        self.assertEqual(len(notices), 1)
        self.assertIn(f"Rapor: [[{grup}]]", notices[0])

    def test_a_step_never_starts_before_its_predecessor_passed(self):
        out = self.start("gelistir")
        names = out["isler"]
        self.po.dispatch()
        err = self.refused("baslat", names[1])
        self.assertIn("akış", err)
        self.report(names[0], "bitti", "Plan.")
        self.po.dispatch()
        self.report(names[1], "bitti", "BLOCKER: plan yanlış dosyayı değiştiriyor\nKARAR: DÜZELT")
        self.assertEqual(self.status(names[1]), "bitti")
        started = self.po.dispatch()
        self.assertNotIn(names[2], started, "kod never starts after a DÜZELT")
        self.assertEqual(self.status(names[2]), "sirada")

    def test_plan_review_duzelt_opens_a_new_plan_round_then_asks_deniz(self):
        out = self.start("gelistir", "--butce", "20")
        grup, names = out["grup"], out["isler"]
        self.run_plan(grup, plan="Eski plan.", review="MAJOR: test planı yok\nKARAR: DÜZELT")
        started = self.po.dispatch()  # the engine opens the round, then the dispatcher starts the new plan
        state = self.state(grup)
        new_plan, new_review = state["adimlar"][0]["isler"][1], state["adimlar"][1]["isler"][1]
        self.assertEqual(started, [new_plan])
        self.assertEqual(state["plan_turu"], 2)
        # only the workflow's very first job counts as a new workflow for the approval backlog
        self.assertEqual(records.load(self.durum, names[0])["akis_ilk"], "evet")
        self.assertEqual(records.load(self.durum, new_plan)["akis_ilk"], "")
        self.assertEqual(records.load(self.durum, new_review)["bagimli"], new_plan)
        self.assertEqual(records.load(self.durum, names[2])["bagimli"], new_review, "kod waits for the new review")
        self.assertEqual(self.job(names[2]).meta["bagimli"], new_review)
        prompt = self.prompt_of(new_plan)
        self.assertIn("> Eski plan.", prompt)
        self.assertIn("> MAJOR: test planı yok", prompt)
        self.assertIn(akis.DATA_SENTENCE, prompt)
        self.assertNotEqual(records.load(self.durum, new_plan)["oturum"], records.load(self.durum, names[0])["oturum"])
        self.report(new_plan, "bitti", "Yeni plan.")
        self.assertEqual(self.po.dispatch(), [new_review])
        self.assertIn("> Yeni plan.", self.prompt_of(new_review))
        self.report(new_review, "bitti", "MAJOR: hâlâ test yok\nKARAR: DÜZELT")
        self.assertEqual(self.po.dispatch(), [])
        state = self.state(grup)
        self.assertEqual(state["durum"], "deniz")
        self.assertEqual(len(state["adimlar"][0]["isler"]), 2, "max 2 plan rounds")
        notice = self.ceo_queue()[-1]
        self.assertIn("akışı durdu", notice)
        self.assertIn("akis-karar", notice)
        self.assertIn("> MAJOR: hâlâ test yok", notice)
        self.assertEqual(self.status(names[2]), "sirada")
        # The owner lets it go on: the latest plan counts as approved
        self.ok("akis-karar", grup, "devam")
        self.assertEqual(self.po.dispatch(), [names[2]])
        self.assertIn("> Yeni plan.", self.prompt_of(names[2]))

    def test_a_missing_verdict_counts_as_duzelt_once_then_asks_deniz(self):
        out = self.start("gelistir", "--butce", "20")
        grup = out["grup"]
        self.run_plan(grup, review="Plan iyi görünüyor.")
        self.po.dispatch()
        state = self.state(grup)
        self.assertEqual((state["plan_turu"], state["durum"]), (2, "calisiyor"))
        self.assertEqual(state["adimlar"][1]["karar"], "eksik")
        new_plan = state["adimlar"][0]["isler"][1]
        self.assertEqual(self.status(new_plan), "calisiyor")
        self.report(new_plan, "bitti", "Plan 2.")
        self.po.dispatch()
        self.report(self.latest(grup, "plan-inceleme"), "bitti", "Yine karar yok.")
        self.po.dispatch()
        self.assertEqual(self.state(grup)["durum"], "deniz")
        self.assertIn("KARAR", self.ceo_queue()[-1])

    def test_kod_review_duzelt_sends_the_findings_to_the_kod_session_and_reviews_again(self):
        self.cfg["codex_bin"] = os.path.join(self.tmp.name, "yok", "codex")
        out = self.start("kucuk-is", "--butce", "10")
        grup, names = out["grup"], out["isler"]
        kod = self.run_kod(grup)
        self.assertEqual(self.po.dispatch(), [names[1]])  # codex is missing: falls back at once
        self.codex_review()
        self.assertEqual(self.status(names[1]), "sirada")
        self.assertEqual(self.po.dispatch(), [names[1]])
        self.assertEqual(self.status(names[1]), "calisiyor")
        self.report(names[1], "bitti", "MAJOR: boş parola hâlâ kabul ediliyor (login.py:12)\nMINOR: isim\n"
                                       "KARAR: DÜZELT")
        self.assertEqual(self.po.dispatch(), [])
        state = self.state(grup)
        self.assertEqual(state["inceleme_turu"], 2)
        self.assertEqual(self.status(kod), "calisiyor", "the kod job goes on in its own session")
        rec = records.load(self.durum, kod)
        self.assertEqual(rec["inceleme_turu"], "1")
        self.assertEqual(self.job(kod).meta["kontrol_deneme"], "0")
        [msg] = self.outbox()
        self.assertEqual((msg["oturum"], msg["is"]), (rec["oturum"], kod))
        self.assertTrue(msg["metin"].startswith(f"[Ofis · inceleme bulguları] {jobs.stem(kod)}"), msg["metin"])
        self.assertIn(akis.DATA_SENTENCE, msg["metin"])
        self.assertIn("> MAJOR: boş parola hâlâ kabul ediliyor (login.py:12)", msg["metin"])
        second = state["adimlar"][1]["isler"][1]
        self.assertEqual(records.load(self.durum, second)["bagimli"], kod)
        self.assertEqual(records.load(self.durum, names[2])["bagimli"], second, "onay waits for the new review")
        # the session fixes it; the Kontrol runs again under keys of its own
        self.report(kod, "bitti", "Düzeltildi.")
        self.po.kontrol.run_pending()
        self.assertEqual(self.status(kod), "bitti")
        self.assertEqual([q for q in self.ceo_queue() if "Kontrol geçti" in q], [],
                         "a workflow step's pass is told by the group report")
        [event] = karne.corrections(self.vault, "blog")
        # the rework belongs to the reviewed kod job (the review job is named in the key)
        self.assertEqual((event["is"], event["tur"], event["kimlik"]),
                         (jobs.stem(kod), "inceleme-duzelt", f"inceleme-{jobs.stem(names[1])}"))
        self.assertIn("MAJOR: boş parola hâlâ kabul ediliyor", event["alinti"])
        self.assertNotIn("MINOR", event["alinti"])
        self.assertEqual(self.po.dispatch(), [second])
        review_prompt = self.prompt_of(second)
        self.assertIn("> Düzeltildi.", review_prompt)
        self.assertIn("Önceki inceleme", review_prompt)
        self.report(second, "bitti", "KARAR: ONAY")
        self.assertEqual(self.po.dispatch(), [names[2]])
        _, card = self.card(grup)
        self.assertIn("2 tur", card)

    def test_minor_only_is_an_approval_with_the_minors_on_the_card(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is")
        grup, names = out["grup"], out["isler"]
        self.run_kod(grup)
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        self.report(names[1], "bitti", "MINOR: yorum satırı eski\nMINOR: log seviyesi\nKARAR: DÜZELT")
        self.assertEqual(self.po.dispatch(), [names[2]])
        _, card = self.card(grup)
        self.assertIn("yorum satırı eski", card)
        self.assertIn("log seviyesi", card)
        self.assertIn("claude (codex yok:", card)
        self.assertIn("Plan adımı yok", card)

    def test_two_failed_review_rounds_ask_deniz(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is", "--butce", "10")
        grup, names = out["grup"], out["isler"]
        kod = self.run_kod(grup)
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        self.report(names[1], "bitti", "MAJOR: hata\nKARAR: DÜZELT")
        self.po.dispatch()
        self.report(kod, "bitti", "Düzeltildi.")
        self.po.kontrol.run_pending()
        second = self.latest(grup, "kod-inceleme")
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        self.report(second, "bitti", "BLOCKER: yine hata\nKARAR: DÜZELT")
        self.po.dispatch()
        self.assertEqual(self.state(grup)["durum"], "deniz")
        self.assertEqual(self.status(kod), "bitti", "no third round")
        self.assertEqual(self.status(names[2]), "sirada")
        # The owner lets it go to the approval card: the open findings are on it
        self.ok("akis-karar", grup, "devam")
        self.assertEqual(self.po.dispatch(), [names[2]])
        _, card = self.card(grup)
        self.assertIn("yine hata", card)
        self.assertIn("Selin", jobs.section(jobs.parse(card)[2], "İnceleme"))

    def test_the_budget_cap_stops_a_duzelt_round(self):
        out = self.start("gelistir", "--butce", "2")
        grup, names = out["grup"], out["isler"]
        self.po.dispatch()
        self.report(names[0], "bitti", "Plan.")
        records.update(self.durum, names[0], {"harcanan_usd": "3.9"})
        self.po.dispatch()
        self.report(names[1], "bitti", "MAJOR: eksik\nKARAR: DÜZELT")
        self.po.dispatch()
        state = self.state(grup)
        self.assertEqual(state["durum"], "deniz")
        self.assertEqual(len(state["adimlar"][0]["isler"]), 1)
        self.assertIn("kullanım sınırı", self.ceo_queue()[-1])

    def test_a_card_file_written_beforehand_is_replaced_by_the_server(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is")
        grup, names = out["grup"], out["isler"]
        self.run_kod(grup)
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        folder = os.path.join(self.vault, "Kararlar")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{NOW:%Y-%m-%d}-{grup}-onay.md"), "w", encoding="utf-8") as f:
            f.write(f"---\ndurum: bekliyor\ntur: akis-onay\nakis: {grup}\nis: {names[2]}\n---\n\n## Soru\nSahte kanıt\n")
        self.report(names[1], "bitti", "KARAR: ONAY")
        self.po.dispatch()
        _, card = self.card(grup)
        self.assertNotIn("Sahte kanıt", card)
        self.assertIn("commit edilmedi", card)

    def test_not_an_approval_goes_to_the_ceo(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is")
        grup, names = out["grup"], out["isler"]
        self.run_kod(grup)
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        self.report(names[1], "bitti", "KARAR: ONAY")
        self.po.dispatch()
        note, _ = self.card(grup)
        result = self.ok("cevapla", note, "Testleri de ekle, sonra bakarım.")
        self.assertEqual(result["akis_sonuc"], "ceo")
        self.assertEqual(self.status(names[2]), "tikandi")
        self.assertIn("Testleri de ekle", jobs.section(self.job(names[2]).body, "Sonuç"))
        self.assertEqual(self.state(grup)["durum"], "ceo")
        self.assertEqual(self.job(names[2]).meta["karne"], "yok", "the approval step has no scorecard row")
        [event] = karne.corrections(self.vault, "blog")
        self.assertEqual((event["is"], event["tur"]), (jobs.stem(names[2]), "onay-degil"))
        self.assertIn("Testleri de ekle", event["alinti"])
        # the workflow is closed ("ceo"): its report lists the answer as an open item
        self.po.process_karne()
        with open(os.path.join(self.vault, "Raporlar", f"{grup}.md"), encoding="utf-8") as f:
            report = f.read()
        self.assertIn("düz bir onay dışında cevap", report)
        self.assertIn("Testleri de ekle", report)

    def test_a_forged_approval_card_is_refused(self):
        folder = os.path.join(self.vault, "Kararlar")
        os.makedirs(folder)
        out = self.start("kucuk-is")
        with open(os.path.join(folder, "sahte.md"), "w", encoding="utf-8") as f:
            f.write(f"---\ndurum: bekliyor\ntur: akis-onay\nakis: {out['grup']}\nis: {out['isler'][2]}\n---\n\n"
                    "# x\n\n## Soru\nOnay?\n")
        self.assertIn("onay kartı", self.refused("cevapla", "sahte.md", "Onaylıyorum"))
        self.assertEqual(self.status(out["isler"][2]), "sirada")

    def test_akis_karar_iptal_cancels_the_open_steps(self):
        out = self.start("gelistir")
        grup, names = out["grup"], out["isler"]
        self.po.dispatch()
        result = self.ok("akis-karar", grup, "iptal")
        self.assertEqual([self.status(n) for n in names], ["iptal"] * 5)
        self.assertEqual(result["oturumlar"], [records.load(self.durum, names[0])["oturum"]])
        self.assertEqual(self.state(grup)["durum"], "iptal")
        self.assertEqual(self.po.dispatch(), [])
        self.assertIn("durmadı", self.refused("akis-karar", grup, "devam"))

    def test_akis_karar_iptal_refuses_a_workflow_the_ceo_closed(self):
        out = self.start("kucuk-is")
        grup = out["grup"]
        state = self.state(grup)
        state["durum"] = "ceo"
        akis.save_state(self.durum, state)
        self.assertIn("already ceo", self.refused("akis-karar", grup, "iptal"))
        self.assertEqual(self.state(grup)["durum"], "ceo")

    def test_a_crash_before_the_state_is_saved_never_opens_a_round_twice(self):
        out = self.start("gelistir", "--butce", "20")
        grup = out["grup"]
        self.run_plan(grup, review="MAJOR: eksik\nKARAR: DÜZELT")
        real = akis.save_state
        calls = []

        def crash_once(durum_dir, state):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk dolu")
            return real(durum_dir, state)
        akis.save_state = crash_once
        try:
            self.po.akis.advance()
        finally:
            akis.save_state = real
        self.assertEqual(len(self.state(grup)["adimlar"][0]["isler"]), 1, "the crash lost the state change")
        self.po.dispatch()
        state = self.state(grup)
        self.assertEqual(len(state["adimlar"][0]["isler"]), 2)
        self.assertEqual(len(state["adimlar"][1]["isler"]), 2)
        mine = [n for n in os.listdir(os.path.join(self.durum, "isler"))
                if records.load(self.durum, n[:-5] + ".md").get("akis") == grup]
        self.assertEqual(len(mine), 7, "the round's jobs were adopted, not written again")

    def test_a_crash_during_the_kod_reopen_is_finished_not_stopped(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is", "--butce", "10")
        grup, names = out["grup"], out["isler"]
        kod = self.run_kod(grup)
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        self.report(names[1], "bitti", "MAJOR: hata\nKARAR: DÜZELT")
        real = akis.save_state

        def crash(durum_dir, state):
            raise OSError("disk dolu")
        akis.save_state = crash
        try:
            self.po.akis.advance()
        finally:
            akis.save_state = real
        self.assertEqual(self.status(kod), "calisiyor")
        self.po.dispatch()
        state = self.state(grup)
        self.assertEqual((state["durum"], state["inceleme_turu"], len(state["adimlar"][1]["isler"])),
                         ("calisiyor", 2, 2))
        self.assertEqual(len(self.outbox()), 1, "the findings went once")

    def test_an_approval_job_cancelled_by_hand_closes_the_workflow(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is")
        grup, names = out["grup"], out["isler"]
        self.run_kod(grup)
        self.po.dispatch()
        self.codex_review()
        self.po.dispatch()
        self.report(names[1], "bitti", "KARAR: ONAY")
        self.po.dispatch()
        self.assertEqual(self.state(grup)["durum"], "onay-bekliyor")
        self.ok("iptal", names[2])
        self.po.dispatch()
        self.assertEqual(self.state(grup)["durum"], "iptal")

    def test_a_step_report_is_not_told_one_by_one(self):
        # phase 5: the group report is the one message of a workflow; "akış adımı bitti" notices are dropped
        out = self.start("gelistir")
        self.po.dispatch()
        self.report(out["isler"][0], "bitti", "Plan.")
        self.assertEqual([q for q in self.ceo_queue() if "akış adımı bitti" in q or "işi bitti" in q], [])
        self.assertIn("withheld", self.po.log_file.getvalue())

    def test_an_escalated_kod_step_is_adopted_by_the_workflow(self):
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is", "--butce", "10", kontrol="exit 1")
        grup, names = out["grup"], out["isler"]
        self.po.dispatch()
        kod = names[0]
        for _ in range(2):
            self.report(kod, "bitti", "Bitti.")
            self.po.kontrol.run_pending()
        self.assertEqual(self.status(kod), "tikandi")
        new = records.load(self.durum, kod)["yukseltildi"]
        self.assertTrue(new)
        self.po.dispatch()
        state = self.state(grup)
        self.assertEqual(state["adimlar"][0]["isler"], [kod, new])
        rec = records.load(self.durum, new)
        self.assertEqual((rec["akis"], rec["adim_turu"]), (grup, "kod"))
        self.assertEqual(records.load(self.durum, names[1])["bagimli"], new)
        # the escalated job gets the workflow's prompt plus the trusted earlier attempts
        self.assertIn(new, self.po.dispatch() + [new])
        prompt = self.prompt_of(new)
        self.assertIn("adım 1/3: kod", prompt)
        self.assertIn("Önceki deneme", prompt)
        self.assertIn("commit ve push yapma", prompt)

    def test_an_escalated_step_is_held_during_probation(self):
        del self.cfg["akis_deneme_kosusu"]
        self.cfg["codex_bin"] = ""
        out = self.start("kucuk-is", "--butce", "10", kontrol="exit 1")
        kod = out["isler"][0]
        self.ok("serbest", kod)
        self.po.dispatch()
        for _ in range(2):
            self.report(kod, "bitti", "Bitti.")
            self.po.kontrol.run_pending()
        new = records.load(self.durum, kod)["yukseltildi"]
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(records.load(self.durum, new)["beklet"], "evet")


class CodexTest(Base):
    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q")
        with open(os.path.join(self.project, "a.py"), "w") as f:
            f.write("a = 1\n")
        git(self.project, "add", "a.py")
        git(self.project, "commit", "-q", "-m", "ilk")
        out = self.start("kucuk-is")
        self.grup, self.names = out["grup"], out["isler"]
        self.run_kod(self.grup)
        self.assertEqual(self.po.dispatch(), [self.names[1]])
        self.assertEqual(self.status(self.names[1]), "incelemede")

    def fell_back(self, reason, ran=True, kota=False):
        name = self.names[1]
        self.assertEqual(self.status(name), "sirada")
        rec = records.load(self.durum, name)
        value = rec["inceleme_yurutucu"]
        self.assertTrue(value.startswith("claude (codex yok: "), value)
        self.assertIn(reason, value)
        # the page's Codex status reads the run time (only when codex really ran) and the strict quota flag
        self.assertEqual(bool(rec.get("codex_zamani")), ran)
        self.assertEqual(rec.get("codex_kota", "") == "evet", kota)
        self.assertEqual(self.job(name).meta["inceleme_yurutucu"], value)
        self.assertEqual(self.po.dispatch(), [name])
        prompt = self.prompt_of(name)
        self.assertIn("kod incelemesi", prompt)
        self.assertIn(records.load(self.durum, self.names[0])["taban_commit"], prompt)
        self.assertEqual(records.load(self.durum, name)["model"], "opus")

    def test_a_quota_error_falls_back_to_claude(self):
        self.codex.flag("quota")
        self.codex_review()
        self.fell_back("kota", kota=True)
        self.assertEqual(records.load(self.durum, self.names[1]).get("codex_donus", ""), "")  # "try again later"

    def test_a_quota_error_with_a_reset_time_records_when_codex_comes_back(self):
        self.codex.flag("quota_at")
        self.codex_review()
        self.fell_back("kota", kota=True)
        donus = records.load(self.durum, self.names[1])["codex_donus"]
        # "Nov 12th, 2026 3:05 PM" is codex's local time; it is stored in the office zone
        expected = datetime(2026, 11, 12, 15, 5).astimezone().astimezone(model_durum.office_tz())
        self.assertEqual(donus, expected.isoformat(timespec="minutes"))

    def test_review_text_about_rate_limits_is_never_a_quota(self):
        # no KARAR line: the label may still say "kota doldu" (akis.QUOTA), but the strict flag stays off
        self.codex.review("No rate limiting on /login; it should return 429 after five tries.")
        self.codex_review()
        self.fell_back("codex yok", kota=False)

    def test_a_timeout_falls_back_to_claude(self):
        self.cfg["codex_timeout_s"] = 1
        self.po.codex.timeout = 1
        self.codex.flag("slow")
        self.codex_review()
        self.fell_back("zaman aşımı")

    def test_a_failing_codex_falls_back_to_claude(self):
        self.codex.flag("fail")
        self.codex_review()
        self.fell_back("çıkış kodu 2")

    def test_a_missing_codex_falls_back_to_claude(self):
        self.po.codex.cfg = dict(self.cfg, codex_bin=os.path.join(self.tmp.name, "yok"))
        self.codex_review()
        self.fell_back("bulunamadı", ran=False)  # codex never ran: no run time for the page

    def test_a_codex_review_without_a_verdict_falls_back_to_claude(self):
        # codex's built-in review mode may ignore the instructions: no KARAR line is a codex failure, not a DÜZELT
        self.codex.review("Looks fine overall.")
        self.codex_review()
        self.fell_back("karar satırı yok")

    def test_a_codex_verdict_is_parsed_from_its_output(self):
        self.codex.review("BLOCKER: a.py siliniyor\nKARAR: DÜZELT")
        self.codex_review()
        self.assertEqual(self.status(self.names[1]), "bitti")
        self.assertTrue(records.load(self.durum, self.names[1])["codex_zamani"])
        self.po.dispatch()
        state = self.state(self.grup)
        self.assertEqual(state["inceleme_turu"], 2)
        self.assertEqual(self.status(self.names[0]), "calisiyor")
        self.assertIn("> BLOCKER: a.py siliniyor", self.outbox()[0]["metin"])
        self.assertEqual(records.load(self.durum, state["adimlar"][1]["isler"][1])["inceleme_yurutucu"], "codex")


class DiffStatTest(unittest.TestCase):
    def test_diff_stat_and_untracked_files_since_the_base_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(os.path.realpath(tmp), "blog")
            os.makedirs(project)
            git(project, "init", "-q")
            with open(os.path.join(project, "a.py"), "w") as f:
                f.write("a = 1\n")
            git(project, "add", "a.py")
            git(project, "commit", "-q", "-m", "ilk")
            head = subprocess.run(["git", "-C", project, "rev-parse", "HEAD"], capture_output=True,
                                  text=True).stdout.strip()
            with open(os.path.join(project, "a.py"), "a") as f:
                f.write("b = 2\n")
            with open(os.path.join(project, "yeni.py"), "w") as f:
                f.write("c = 3\n")
            cfg = {"projects": {"blog": {"path": project}}}
            text = akis.diff_stat(cfg, "blog", head)
            self.assertIn("a.py", text)
            self.assertIn("1 file changed", text)
            self.assertIn("yeni.py", text)
            self.assertIn("taban commit yok", akis.diff_stat(cfg, "blog", ""))
            status = subprocess.run(["git", "-C", project, "status", "--porcelain"], capture_output=True,
                                    text=True).stdout
            self.assertIn("?? yeni.py", status, "nothing was staged or committed")


class PromptTest(Base):
    def test_a_long_earlier_output_is_trimmed_with_a_marker(self):
        out = self.start("gelistir")
        grup, names = out["grup"], out["isler"]
        self.po.dispatch()
        self.report(names[0], "bitti", "\n".join(f"Adım {i}: " + "x" * 60 for i in range(110)))
        self.po.dispatch()
        prompt = self.prompt_of(names[1])
        self.assertLessEqual(len(prompt), launch.MAX_TASK)
        self.assertIn(akis.TRIMMED, prompt)
        self.assertIn("KARAR: DÜZELT", prompt, "the fixed instructions are never trimmed")
        for line in prompt.split(akis.DATA_SENTENCE, 1)[1].splitlines()[1:]:
            if line.startswith("## "):
                break
            self.assertTrue(line.startswith(">") or not line.strip(), line)


class StateTest(Base):
    def test_summary_and_job_info_for_the_page(self):
        out = self.start("gelistir")
        grup, names = out["grup"], out["isler"]
        self.run_plan(grup, review="MINOR: x\nKARAR: ONAY")
        self.po.dispatch()
        [summary] = akis.summaries(self.durum)
        self.assertEqual((summary["grup"], summary["baslik"], summary["sablon"], summary["tamam"], summary["toplam"]),
                         (grup, "Giriş hatası", "gelistir", 2, 5))
        info = akis.job_info(self.durum, names[1])
        self.assertEqual((info["grup"], info["adim"], info["tur"], info["karar"], info["tur_no"]),
                         (grup, 2, "plan-inceleme", "onay", 1))
        self.assertEqual(info["bulgular"], ["MINOR: x"])
        self.assertIsNone(akis.job_info(self.durum, "yok.md"))


class CostLinesTest(unittest.TestCase):
    """The approval card's Kullanım section: tokens next to every dollar figure; unknown tokens are left out, never 0."""

    def test_each_step_and_the_total_carry_the_known_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            records.update(tmp, "2026-11-12-1-blog.md", {"harcanan_usd": "0.41", "harcanan_token": "182400"})
            records.update(tmp, "2026-11-12-2-blog.md", {"harcanan_usd": "0.5"})  # no token count
            state = {"butce_usd": 5, "adimlar": [{"tur": "plan", "isler": ["2026-11-12-1-blog.md"]},
                                                 {"tur": "kod", "isler": ["2026-11-12-2-blog.md"]},
                                                 {"tur": "onay", "isler": ["2026-11-12-3-blog.md"]}]}
            text, total = akis._cost_lines(tmp, state)
        self.assertAlmostEqual(total, 0.91)
        lines = text.splitlines()
        self.assertEqual(lines[0], "- Toplam kayıtlı kullanım: 182 bin token · API karşılığı ~$0.91 (akış kullanım sınırı "
                                   "~$5.00 API karşılığı; 1 adımda token kayıtlı değil)")
        self.assertEqual(lines[1:], ["- [[2026-11-12-1-blog]] plan: 182 bin token · API karşılığı ~$0.41",
                                     "- [[2026-11-12-2-blog]] kod: API karşılığı ~$0.50"])
        self.assertNotIn("0 token", text)


if __name__ == "__main__":
    unittest.main()
