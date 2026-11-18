"""Tests for bin/danisman.py (the advisor pilot: Kıdemli kod jobs with / without `--advisor fable`) and its hooks in
launch.create_job / start_job / resume_flags, ofis.py (danisman-pilotu, cevapla, deneme-isaretle), the transcript's
advisor counting, the post office's record of it and the page helpers. Fakes only: a temp vault, temp durum, a temp
ofis.json and the fake claude (no real session, no model call)."""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402 (isolates the job lock)
import budget  # noqa: E402
import danisman  # noqa: E402
import jobs  # noqa: E402
import karne  # noqa: E402
import launch  # noqa: E402
import model_secimi  # noqa: E402
import ofis  # noqa: E402
import postoffice  # noqa: E402
import pricing  # noqa: E402
import records  # noqa: E402
import transcript  # noqa: E402

NOW = datetime(2026, 11, 14, 10, 0, 0)
TIERS = {"kod": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet", "effort": "medium"},
         "inceleme": {"model": "opus", "effort": "high"}}


def m(first, measured, cost, calls=None, known=0, unknown=0):
    return {"is_sayisi": measured, "ilk_tur_gecen": first, "ilk_tur_olculen": measured, "yeniden_is": 0,
            "yukseltme": 0, "dogrulanmis_is_basina_usd": cost,
            "danisman": {"cagri": calls or 0, "hata": {}, "bilinen": known, "bilinmeyen": unknown,
                         "hic_cagrilmayan": 0, "iterasyon": 0}}


def row(stem, first="evet", cost="2.0000", devam=0):
    values = ("2026-11-14", "blog", f"[[{stem}]]", "kod", "opus", "high", first, "1" if first == "evet" else "2",
              "hayır", "30", cost, cost if first == "evet" else "", "20", "bitti" if first == "evet" else "tikandi",
              str(devam), "", "", "100000", "", "backend")
    return "| " + " | ".join(values[:len(karne.COLUMNS)]) + " |"


class FakeCeo:
    def __init__(self):
        self.sent = []

    def enqueue(self, text, key):
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class RuleTest(unittest.TestCase):
    def test_settings_defaults_and_bad_values(self):
        s = danisman.settings({})
        self.assertEqual((s["acik"], s["model"], s["is_sayisi"], s["katman"], s["var"]), (False, "fable", 10, "kod", False))
        s = danisman.settings({"danisman_pilotu": {"acik": "true", "model": "--evil", "is_sayisi": 1, "katman": "K D"}})
        self.assertEqual((s["acik"], s["model"], s["is_sayisi"], s["katman"], s["var"]), (False, "fable", 10, "kod", True))
        s = danisman.settings({"danisman_pilotu": {"acik": True, "model": "claude-fable-5-2", "is_sayisi": 4}})
        self.assertEqual((s["acik"], s["model"], s["is_sayisi"]), (True, "claude-fable-5-2", 4))

    def test_the_ar_ge_note_link_comes_from_the_config(self):
        # plan "2. Aşama": the proposal links the Ar-Ge report named in danisman_pilotu.arge_notu, when that note exists
        state = {"katman": "kod", "is_sayisi": 4, "model": "fable", "kimlik": "p-1"}
        now = datetime(2026, 11, 14, 10, 0)
        with tempfile.TemporaryDirectory() as vault:
            os.makedirs(os.path.join(vault, "ArGe"))
            open(os.path.join(vault, "ArGe", "ArGe-2026-11-13.md"), "w").close()
            cfg = {"danisman_pilotu": {"arge_notu": "ArGe-2026-11-13"}}
            self.assertEqual(danisman.settings(cfg)["arge_notu"], "ArGe-2026-11-13")
            self.assertIn("Ar-Ge raporu [[ArGe-2026-11-13]]", danisman.proposal_card(cfg, vault, state, now))
            for cfg in ({}, {"danisman_pilotu": {"arge_notu": "ArGe-2026-11-12"}},  # the note does not exist
                        {"danisman_pilotu": {"arge_notu": "../../x"}}, {"danisman_pilotu": {"arge_notu": 3}}):
                with self.subTest(cfg=cfg):
                    self.assertNotIn("Ar-Ge raporu", danisman.proposal_card(cfg, vault, state, now))

    def test_success_needs_15_points_and_at_most_25_percent_more_cost(self):
        self.assertTrue(danisman.success(m(3, 5, 4.0), m(3.75, 5, 5.0))[0], "+15 points, +25 %: the edges pass")
        self.assertTrue(danisman.success(m(2, 5, 4.0), m(4, 5, 4.0))[0])
        ok, reason = danisman.success(m(3, 5, 4.0), m(3, 4, 4.0))
        self.assertTrue(ok, reason)  # 60 % → 75 %: +15
        ok, reason = danisman.success(m(3, 5, 4.0), m(37, 50, 4.0))
        self.assertFalse(ok)  # 60 % → 74 %: +14
        self.assertIn("+14 puan", reason)
        ok, reason = danisman.success(m(2, 5, 4.0), m(5, 5, 5.04))
        self.assertFalse(ok)
        self.assertIn("%26 arttı", reason)
        self.assertFalse(danisman.success(m(0, 0, 4.0), m(5, 5, 4.0))[0], "A without a measured Kontrol")
        self.assertFalse(danisman.success(m(2, 5, None), m(5, 5, 4.0))[0], "A without a verified job")
        ok, reason = danisman.success(m(2, 5, 4.0), m(5, 5, 4.0, calls=0, known=5))
        self.assertFalse(ok, "every B job known with 0 advisor calls: the advisor was not attached")
        self.assertIn("hiç çağrılmadı", reason)
        self.assertTrue(danisman.success(m(2, 5, 4.0), m(5, 5, 4.0, calls=0, known=0, unknown=5))[0],
                        "unknown counts never decide")

    def test_session_flags_add_only_a_valid_advisor(self):
        self.assertNotIn("--advisor", launch.session_flags("blog", "ofis-blog-x", "opus", "high"))
        flags = launch.session_flags("blog", "ofis-blog-x", "opus", "high", danisman="fable")
        self.assertEqual(flags[flags.index("--advisor") + 1], "fable")
        with self.assertRaises(launch.Refused):
            launch.session_flags("blog", "ofis-blog-x", danisman="--dangerously-skip-permissions")


class TranscriptTest(unittest.TestCase):
    def test_advisor_calls_errors_and_iterations_are_counted_once(self):
        day = datetime(2026, 11, 14)
        usage = {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0,
                 "cache_read_input_tokens": 0,
                 "iterations": [{"type": "message", "input_tokens": 500, "output_tokens": 50},
                                {"type": "advisor_message", "model": "claude-opus-5-5", "input_tokens": 2000,
                                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 300},
                                {"type": "message", "input_tokens": 500, "output_tokens": 50}]}
        plain = dict(usage, iterations=[])
        records_ = [
            fakes.assistant(day, "m1", [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "advisor", "input": {}},
                                        {"type": "advisor_tool_result", "tool_use_id": "srvtoolu_1",
                                         "content": {"type": "advisor_redacted_result", "encrypted_content": "x"}}],
                            usage=usage, model="claude-opus-5-5"),
            fakes.assistant(day, "m1", [{"type": "text", "text": "same call, next chunk"}], usage=usage,
                            model="claude-opus-5-5"),
            fakes.assistant(day, "m2", [{"type": "server_tool_use", "id": "srvtoolu_2", "name": "advisor", "input": {}},
                                        {"type": "advisor_tool_result", "tool_use_id": "srvtoolu_2",
                                         "content": {"type": "advisor_tool_result_error", "error_code": "unavailable"}}],
                            usage=plain, model="claude-opus-5-5"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            projects = os.path.join(tmp, "projects")
            cwd = os.path.join(tmp, "Dev", "blog")
            sid = "aaaaaaaa-1111-2222-3333-444444444444"
            path = fakes.write_transcript(projects, cwd, sid, records_)
            reader = transcript.SessionTranscript(path)
            reader.poll()
            self.assertEqual(reader.advisor_calls, {"srvtoolu_1", "srvtoolu_2"})
            self.assertEqual(reader.advisor_errors, {"srvtoolu_2": "unavailable"})
            self.assertEqual(reader.advisor_iter_by_msg, {"m1": 1})
            # the advisor's tokens and its own price are in the call (top-level usage is the main model's only)
            self.assertEqual(reader.tokens_by_msg["m1"], 1100 + 2300)
            main = pricing.call_cost("claude-opus-5-5", usage)["total"]
            adv = pricing.call_cost("claude-opus-5-5", usage["iterations"][1])["total"]
            self.assertAlmostEqual(reader.calls_by_msg["m1"], main + adv)
            meter = budget.UsageMeter(projects)
            job = jobs.Job("x.md", jobs.DONE, "", {"kisa_id": sid[:8], "calisma_dizini": cwd}, "")
            u = meter.usage(job)
            self.assertEqual((u.danisman_cagri, u.danisman_hata, u.danisman_iterasyon), (2, {"unavailable": 1}, 1))
            self.assertEqual(budget.advisor_fields(u), {"danisman_cagri": "2", "danisman_hata": "unavailable:1",
                                                        "danisman_iterasyon": "1"})

    def test_a_transcript_without_advisor_is_unchanged(self):
        day = datetime(2026, 11, 14)
        with tempfile.TemporaryDirectory() as tmp:
            path = fakes.write_transcript(tmp, "/x", "bbbbbbbb-1111-2222-3333-444444444444",
                                          [fakes.assistant(day, "m1", [{"type": "text", "text": "hi"}],
                                                           usage=fakes.usage(), model="claude-opus-5-5")])
            reader = transcript.SessionTranscript(path)
            reader.poll()
            self.assertEqual((reader.advisor_calls, reader.advisor_errors, reader.advisor_iter_by_msg), (set(), {}, {}))
            self.assertEqual(reader.tokens_by_msg["m1"], 10)
            self.assertAlmostEqual(reader.calls_by_msg["m1"],
                                   pricing.call_cost("claude-opus-5-5", fakes.usage())["total"])


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.project = os.path.join(base, "Dev", "blog")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.durum = os.path.join(base, "ajan-ofisi", "durum")
        for d in (self.project, self.vault, self.durum):
            os.makedirs(d)
        self.config = os.path.join(base, "ajan-ofisi", "ofis.json")
        raw = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
               "projects": {"blog": {"path": self.project, "description": "W"}},
               "tiers": TIERS, "default_tier": "genel", "default_budget_usd": 3, "max_queued_per_project": 50,
               "danisman_pilotu": {"acik": False, "model": "fable", "is_sayisi": 4, "katman": "kod"}}
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
        self.cfg = launch.load(self.config)
        self.ceo = FakeCeo()
        self.pilot = danisman.Pilot(self.cfg, self.durum, self.ceo, now=lambda: NOW)
        self.claude = fakes.FakeClaude(os.path.join(base, "fake"))
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, now=lambda: NOW, out=out, err=err,
                         cwd=self.project, config_path=self.config)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        return json.loads(out) if out.strip().startswith("{") else out

    def refused(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 1, out)
        return err

    def add(self, *extra, katman="kod"):
        return self.ok("ekle", "--proje", "blog", "--baslik", "Giriş", "--hedef", "Düzelt.", "--katman", katman,
                       "--kontrol", "test -d .", *extra)["is"]

    def rec(self, name):
        return records.load(self.durum, name) or {}

    def file_cfg(self):
        with open(self.config, encoding="utf-8") as f:
            return json.load(f)

    def start(self, name, worktree=False):
        before = len(self.claude.calls())
        launch.start_job(self.cfg, name, claude_bin=self.claude.path, now=NOW, durum_dir=self.durum,
                         worktree=worktree)
        return [c for c in self.claude.calls()[before:] if "--bg" in c["args"]][-1]["args"]

    def resume(self, name):
        job = records.trusted(self.durum, jobs.load(self.vault, name))
        return launch.resume_flags(job, self.vault, durum_dir=self.durum, now=NOW, cfg=self.cfg)

    def note(self, name):
        with open(os.path.join(self.vault, "Kararlar", name), encoding="utf-8") as f:
            return f.read()

    def write_rows(self, *lines):
        self.lines += lines
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# x\n\n" + karne._table_head(karne.COLUMNS) + "\n".join(self.lines) + "\n")

    def finish(self, name, first=True, cost="2.0000"):
        jobs.update(self.vault, name, status="calisiyor", fields={"baslangic": "2026-11-14T10:00:00"})
        jobs.update(self.vault, name, status="bitti" if first else "tikandi",
                    fields={"bitis": "2026-11-14T10:20:00", "karne": "yazildi"})
        self.write_rows(row(jobs.stem(name), "evet" if first else "hayır", cost))

    # --- off ---

    def test_off_nothing_changes_at_all(self):
        self.assertEqual(self.cfg["danisman_pilotu"]["acik"], False)
        name = self.add()
        rec = self.rec(name)
        for key in danisman.FIELDS:
            self.assertNotIn(key, rec)
        self.assertNotIn("--advisor", self.start(name))
        self.assertNotIn("--advisor", self.resume(name))
        self.assertIsNone(self.pilot.check())
        self.assertEqual(self.ceo.sent, [])
        self.assertIsNone(model_secimi.page(self.cfg, self.durum)["danisman"])
        self.assertIn("DANIŞMAN PİLOTU: yok", self.ok("danisman-pilotu", "durum"))
        self.assertFalse(os.path.exists(danisman.state_path(self.durum)))
        # even a running pilot's state gives nothing while the switch is off (the kill switch)
        danisman.save(self.durum, {"durum": "pilot", "kimlik": "danisman-kod-x", "model": "fable", "katman": "kod",
                                   "is_sayisi": 4, "isler": [], "gecmis": [], "bildirilen": []})
        other = self.add()
        self.assertNotIn("danisman_pilotu", self.rec(other))
        self.assertEqual(danisman.load(self.durum)["isler"], [])

    def test_project_sessions_are_denied_the_command(self):
        self.assertIn("danisman-pilotu", launch.DENIED_COMMANDS)

    # --- proposal ---

    def propose(self):
        result = self.ok("danisman-pilotu", "oner")
        self.assertEqual((result["model"], result["katman"], result["is_sayisi"]), ("fable", "kod", 4))
        return result["karar"]

    def test_the_proposal_card_and_a_no(self):
        note = self.propose()
        self.assertEqual(note, "2026-11-14-ofis-danisman-onerisi.md")
        _, meta, body = jobs.parse(self.note(note))
        self.assertEqual((meta["tur"], meta["durum"], meta["katman"], meta["danisman"]),
                         ("danisman-onerisi", "bekliyor", "kod", "fable"))
        self.assertIn("Kıdemli (Opus) kod işlerinde Genel Müdür (Fable) danışman denensin mi?", jobs.section(body, "Soru"))
        self.assertIn("A, B, A, B", jobs.section(body, "Ne olur"))
        self.assertIn("REFUSED", self.refused("danisman-pilotu", "oner"), "one card at a time")
        self.assertEqual(self.ceo.sent, [], "the CEO relays the card itself: no server notice")
        result = self.ok("cevapla", note, "Hayır, şimdilik değil")
        self.assertEqual((result["tur"], result["onay"], result["pilot"]), ("danisman-onerisi", False, ""))
        self.assertEqual(danisman.load(self.durum)["durum"], "bos")
        self.assertFalse(self.file_cfg()["danisman_pilotu"]["acik"])
        self.assertNotIn("danisman_pilotu", self.rec(self.add()))

    def test_a_forged_card_is_refused(self):
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-14-ofis-danisman-onerisi.md",
                         {"durum": "bekliyor", "proje": "ofis", "tur": "danisman-onerisi", "pilot": "x"},
                         "# x\n\n## Soru\nx\n\n## İlgili Sayfalar\n- [[x]]\n")
        self.assertIn("uyuşmuyor", self.refused("cevapla", "2026-11-14-ofis-danisman-onerisi.md", "Evet"))
        self.assertFalse(self.file_cfg()["danisman_pilotu"]["acik"])

    # --- the pilot ---

    def start_pilot(self):
        note = self.propose()
        result = self.ok("cevapla", note, "Evet")
        kimlik = danisman.load(self.durum)["kimlik"]
        self.assertEqual((result["onay"], result["pilot"], result["is_sayisi"]), (True, kimlik, 4))
        self.assertTrue(self.file_cfg()["danisman_pilotu"]["acik"], "the yes turns the switch on in ofis.json")
        self.assertTrue(self.cfg["danisman_pilotu"]["acik"])
        return kimlik

    def test_arms_alternate_and_only_b_gets_the_flag_at_start_and_resume(self):
        kimlik = self.start_pilot()
        trial = self.add("--deneme")
        explicit = self.add("--model", "fable")
        genel = self.add(katman="genel")
        escalated = launch.create_job(self.cfg, "blog", "Yükseltme", {"hedef": "x", "kontrol": "true"},
                                      tier="kod", now=NOW, durum_dir=self.durum)
        arms = [self.add() for _ in range(4)]
        after = self.add()
        self.assertEqual([self.rec(n)["danisman_kolu"] for n in arms], ["A", "B", "A", "B"])
        self.assertEqual([self.rec(n)["danisman"] for n in arms], ["", "fable", "", "fable"])
        self.assertEqual({self.rec(n)["danisman_pilotu"] for n in arms}, {kimlik})
        for name in (trial, explicit, genel, escalated.name, after):
            self.assertNotIn("danisman_pilotu", self.rec(name), name)
        self.assertEqual([e["kol"] for e in danisman.load(self.durum)["isler"]], ["A", "B", "A", "B"])
        a, b = arms[0], arms[1]
        argv_b = self.start(b)
        self.assertEqual(argv_b[argv_b.index("--advisor") + 1], "fable")
        self.assertNotIn("--advisor", self.start(a))
        self.assertNotIn("--advisor", self.start(trial))
        resumed = self.resume(b)
        self.assertEqual(resumed[resumed.index("--advisor") + 1], "fable")
        self.assertNotIn("--advisor", self.resume(a))
        self.assertNotIn("--advisor", self.resume(trial))
        # the switch off (on the owner's word): no flag on the next resume either
        self.cfg["danisman_pilotu"]["acik"] = False
        self.assertNotIn("--advisor", self.resume(b))
        page = danisman.page(self.cfg, self.durum)
        self.assertEqual((page["durum"], page["eklenen"], page["A"]["eklenen"], page["B"]["eklenen"]), ("pilot", 4, 2, 2))

    def test_a_freed_slot_is_refilled_by_its_arm_and_a_worktree_job_leaves(self):
        self.start_pilot()
        a1, b1 = self.add(), self.add()
        self.ok("iptal", b1)  # cancelled before it started: its slot is freed
        self.pilot.check()
        self.assertEqual([e["is"] for e in danisman.load(self.durum)["isler"]], [a1])
        b2 = self.add()
        self.assertEqual(self.rec(b2)["danisman_kolu"], "B")
        argv = self.start(b2, worktree=True)
        self.assertNotIn("--advisor", argv, "a worktree job is never measured: no flag")
        self.assertEqual(self.rec(b2)["danisman_pilotu"], "")
        self.assertEqual([e["is"] for e in danisman.load(self.durum)["isler"]], [a1])

    def test_a_job_whose_launch_failed_frees_its_slot(self):
        # 2026-11-15: an untrusted folder failed five launches and they kept their slots; nothing was measured
        self.start_pilot()
        a1, b1 = self.add(), self.add()
        jobs.update(self.vault, b1, status="basarisiz", append_result="Başlatma başarısız: test")
        self.pilot.check()
        self.assertEqual([e["is"] for e in danisman.load(self.durum)["isler"]], [a1])
        self.assertEqual(self.rec(self.add())["danisman_kolu"], "B")

    def test_a_failed_pilot_write_does_not_strand_a_worktree_start(self):
        # Codex 2026-11-14: leave() failing after the note is baslatiliyor must not stop the launch
        self.start_pilot()
        self.add()
        b = self.add()
        real = danisman.leave
        def broken(*a, **k):
            raise OSError("disk full")
        danisman.leave = broken
        try:
            argv = self.start(b, worktree=True)
        finally:
            danisman.leave = real
        self.assertNotIn("--advisor", argv, "still no flag for a worktree job")
        self.assertEqual(jobs.load(self.vault, b).meta["durum"], "calisiyor")

    def test_deneme_isaretle_refuses_a_pilot_job(self):
        self.start_pilot()
        name = self.add()
        self.finish(name)
        self.assertIn("advisor pilot", self.refused("deneme-isaretle", name))

    def run_pilot(self, firsts_a, firsts_b, cost_a="2.0000", cost_b="2.2000", calls=3):
        self.start_pilot()
        names = [self.add() for _ in range(4)]
        self.assertIsNone(self.pilot.check(), "not settled yet")
        arms = {"A": iter(firsts_a), "B": iter(firsts_b)}
        for name in names:
            kol = self.rec(name)["danisman_kolu"]
            self.finish(name, next(arms[kol]), cost_a if kol == "A" else cost_b)
            if kol == "B":
                records.update(self.durum, name, {"danisman_cagri": str(calls), "danisman_hata": "unavailable:1",
                                                  "danisman_iterasyon": str(calls)})
        return self.pilot.check()

    def test_a_successful_pilot_asks_once_and_a_yes_maps_the_advisor(self):
        note = self.run_pilot([False, True], [True, True])  # A 50 %, B 100 %; cost +10 %
        self.assertEqual(note, "2026-11-14-ofis-danisman-pilot-sonucu.md")
        _, meta, body = jobs.parse(self.note(note))
        self.assertEqual((meta["tur"], meta["basari"], meta["danisman"]), ("danisman-pilot-sonucu", "evet", "fable"))
        table = jobs.section(body, "Karşılaştırma")
        self.assertIn("| Kontrol ilk turda geçme | %50 (1/2) | %100 (2/2) |", table)
        self.assertIn("| Danışman çağrısı | — | 6 |", table)
        self.assertIn("unavailable ×2", table)
        self.assertIn("\"unavailable\" döndü", table)
        self.assertIn("Danışman kalıcı olsun mu", jobs.section(body, "Soru"))
        [(notice, key)] = self.ceo.sent
        self.assertTrue(notice.startswith("[Ofis · sistem]\nDanışman denemesi bitti: kod işler"), notice)
        self.assertIn("Deneme başarılı", notice)
        self.assertIsNone(self.pilot.check())
        self.assertEqual(len(self.ceo.sent), 1, "one notice, also on the next pass")
        page = danisman.page(self.cfg, self.durum)
        self.assertEqual((page["sonuc"]["B"]["danisman_cagri"], page["sonuc"]["A"]["ilk_tur_gecen"]), (6, 1))
        with open(self.config, encoding="utf-8") as f:
            before = json.load(f)
        answer = self.ok("cevapla", note, "Onaylıyorum")
        self.assertTrue(answer["eslesme_degisti"])
        after = self.file_cfg()
        self.assertEqual(after["tiers"]["kod"], {"model": "opus", "effort": "high", "danisman": "fable"})
        self.assertFalse(after["danisman_pilotu"]["acik"], "the pilot is over: its switch goes back off")
        self.assertEqual(list(after), list(before), "key order kept")
        with open(os.path.join(self.vault, "Karne", "Degisiklikler.md"), encoding="utf-8") as f:
            self.assertIn("kod: danışman yok → danışman fable", f.read())
        self.assertEqual(danisman.load(self.durum)["durum"], "bos")
        # from now on every kod job carries the mapped advisor (start and resume), the other tiers none
        new = self.add()
        self.assertNotIn("danisman_pilotu", self.rec(new))
        argv = self.start(new)
        self.assertEqual(argv[argv.index("--advisor") + 1], "fable")
        self.assertIn("--advisor", self.resume(new))
        self.assertNotIn("--advisor", self.start(self.add(katman="genel")))

    def test_a_failed_pilot_recommends_dropping_it_and_a_yes_changes_nothing(self):
        note = self.run_pilot([True, True], [True, True], cost_b="4.0000")  # no gain, double cost
        _, meta, body = jobs.parse(self.note(note))
        self.assertEqual(meta["basari"], "hayır")
        self.assertIn("bırakmayı öneriyorum", jobs.section(body, "Öneri"))
        self.ok("cevapla", note, "Evet")
        self.assertNotIn("danisman", self.file_cfg()["tiers"]["kod"])
        self.assertNotIn("--advisor", self.start(self.add()))

    def test_an_advisor_never_called_proves_nothing(self):
        note = self.run_pilot([False, False], [True, True], calls=0)
        _, meta, body = jobs.parse(self.note(note))
        self.assertEqual(meta["basari"], "hayır")
        self.assertIn("hiç çağrılmadı", jobs.section(body, "Öneri"))

    def test_the_running_server_takes_the_switch_and_the_mapping_from_ofis_json(self):
        cfg = launch.load(self.config)
        raw = self.file_cfg()
        raw["danisman_pilotu"]["acik"] = True
        raw["tiers"]["kod"]["danisman"] = "fable"
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        model_secimi.refresh_overrides(cfg, self.config)
        self.assertTrue(cfg["danisman_pilotu"]["acik"])
        self.assertEqual(danisman.mapped(cfg, "kod"), "fable")
        del raw["tiers"]["kod"]["danisman"]
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.utime(self.config, ns=(1, 1))
        model_secimi.refresh_overrides(cfg, self.config)
        self.assertEqual(danisman.mapped(cfg, "kod"), "")

    def test_the_post_office_records_the_advisor_counts_with_the_final_spending(self):
        self.start_pilot()
        name = self.add()
        plain = self.add()

        class Meter:
            def usage(self, job):
                return budget.Usage(1.0, 3, 0, "s", ("s",), 10, 2, {"unavailable": 1}, 2)

        office = type("O", (), {"meter": Meter(), "durum_dir": self.durum, "_trusted": lambda self, job: job})()
        postoffice.PostOffice._final_usage(office, jobs.load(self.vault, name))
        self.assertEqual((self.rec(name)["danisman_cagri"], self.rec(name)["danisman_hata"]), ("2", "unavailable:1"))
        records.update(self.durum, plain, {"danisman_pilotu": "", "danisman": ""})

        class Quiet:
            def usage(self, job):
                return budget.Usage(1.0, 3, 0, "s", ("s",), 10)
        office.meter = Quiet()
        postoffice.PostOffice._final_usage(office, jobs.load(self.vault, plain))
        self.assertNotIn("danisman_cagri", self.rec(plain), "no pilot, no advisor calls: nothing written")


class HardJobTest(unittest.TestCase):
    """The hard-job advisor (ofis.json `zor_is_danismani`, owner decision 2026-11-15): only hard kod jobs get `--advisor`."""
    setUp, tearDown = FlowTest.setUp, FlowTest.tearDown
    run_cli, ok, refused, add, rec, file_cfg, start, resume, propose, start_pilot = (
        FlowTest.run_cli, FlowTest.ok, FlowTest.refused, FlowTest.add, FlowTest.rec, FlowTest.file_cfg, FlowTest.start,
        FlowTest.resume, FlowTest.propose, FlowTest.start_pilot)
    R = danisman.HARD_REASONS

    def on(self, acik=True):
        self.cfg["zor_is_danismani"] = {"acik": acik, "model": "fable", "katman": "kod"}

    def advisor(self, argv):
        return argv[argv.index("--advisor") + 1] if "--advisor" in argv else ""

    def workflow(self, kinds, grup="blog-akis-1"):
        """A workflow state with one job per step (kod-inceleme jobs as genel jobs; their tier does not matter here)."""
        steps = []
        for i, kind in enumerate(kinds, start=1):
            name = self.add(katman="kod" if kind == "kod" else "genel")
            records.update(self.durum, name, {"akis": grup, "adim": i, "adim_turu": kind}, create=False)
            steps.append({"adim": i, "tur": kind, "isler": [name]})
        import akis
        akis.save_state(self.durum, {"grup": grup, "sablon": "x", "adimlar": steps})
        return {s["tur"]: s["isler"][0] for s in steps}

    def test_settings_default_off_and_bad_values(self):
        self.assertEqual(danisman.hard_settings({}), {"acik": False, "model": "fable", "katman": "kod"})
        self.assertEqual(danisman.hard_settings({"zor_is_danismani": {"acik": "true", "model": "--x", "katman": "K D"}}),
                         {"acik": False, "model": "fable", "katman": "kod"})

    def test_an_easy_kod_job_gets_no_flag(self):
        self.on()
        plain = self.add()
        self.assertEqual(self.advisor(self.start(plain)), "")
        self.assertEqual(self.advisor(self.resume(plain)), "")
        self.assertNotIn("danisman_nedeni", self.rec(plain), "nothing to record: no write")
        steps = self.workflow(("kod", "kod-inceleme", "onay"))  # kucuk-is
        self.assertEqual(self.advisor(self.start(steps["kod"])), "")
        self.assertEqual(danisman.hard_reason(self.durum, steps["kod"]), "")

    def test_the_kod_step_of_a_gelistir_workflow(self):
        self.on()
        steps = self.workflow(("plan", "plan-inceleme", "kod", "kod-inceleme", "onay"))
        self.assertEqual(self.advisor(self.start(steps["kod"])), "fable")
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "fable")
        rec = self.rec(steps["kod"])
        self.assertEqual((rec["danisman"], rec["danisman_nedeni"]),
                         ("fable", "zor iş: geliştirme akışının kod adımı"))
        self.assertEqual(self.advisor(self.start(steps["plan"])), "", "another tier: never")

    def test_an_escalated_job(self):
        self.on()
        source, name = self.add(katman="genel"), self.add()
        records.update(self.durum, name, {"yukseltme_kaynagi": source}, create=False)
        self.assertEqual(self.advisor(self.start(name)), "fable")
        self.assertEqual(self.rec(name)["danisman_nedeni"], self.R["yukseltme"])
        # the same signal on a job of another tier (kod → planlama) gives nothing
        up = self.add(katman="genel")
        records.update(self.durum, up, {"yukseltme_kaynagi": source}, create=False)
        self.assertEqual(self.advisor(self.start(up)), "")

    def test_a_kod_step_whose_review_rated_it_high_risk(self):
        self.on()
        steps = self.workflow(("kod", "kod-inceleme", "onay"))
        self.assertEqual(self.advisor(self.start(steps["kod"])), "")
        records.update(self.durum, steps["kod-inceleme"], {"risk": "normal"}, create=False)
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "")
        records.update(self.durum, steps["kod-inceleme"], {"risk": "yuksek"}, create=False)
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "fable")
        self.assertEqual(self.rec(steps["kod"])["danisman_nedeni"], self.R["risk"])

    def test_a_resume_after_a_review_duzelt_round(self):
        self.on()
        steps = self.workflow(("kod", "kod-inceleme", "onay"))
        self.assertEqual(self.advisor(self.start(steps["kod"])), "")
        records.update(self.durum, steps["kod"], {"inceleme_turu": 1, "kontrol_deneme": 0, "kontrol_sonuc": ""},
                       create=False)
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "fable")
        self.assertEqual(self.rec(steps["kod"])["danisman_nedeni"], self.R["inceleme"])

    def test_a_resume_after_a_kontrol_failure(self):
        self.on()
        name = self.add()
        self.assertEqual(self.advisor(self.start(name)), "")
        # what kontrol.KontrolWorker._send_back writes on the first failure
        records.update(self.durum, name, {"kontrol_deneme": 1, "kontrol_sonuc": "kaldi"}, create=False)
        self.assertEqual(self.advisor(self.resume(name)), "fable")
        self.assertEqual((self.rec(name)["danisman"], self.rec(name)["danisman_nedeni"]), ("fable", self.R["kontrol"]))
        # it passed on the second attempt: still the job that needed rework
        records.update(self.durum, name, {"kontrol_deneme": 2, "kontrol_sonuc": "gecti"}, create=False)
        self.assertEqual(self.advisor(self.resume(name)), "fable")
        other = self.add()
        self.start(other)
        records.update(self.durum, other, {"kontrol_deneme": 1, "kontrol_sonuc": "gecti"}, create=False)
        self.assertEqual(self.advisor(self.resume(other)), "", "passed first time: easy")

    def test_a_malformed_or_oversized_count_counts_as_absent(self):
        self.on()
        self.assertEqual([danisman._count(v) for v in ("9" * 4301, "١٢", "-1", "x", "", None, "3", 2)],
                         [0, 0, 0, 0, 0, 0, 3, 2])
        name = self.add()
        self.start(name)
        records.update(self.durum, name, {"inceleme_turu": "9" * 4301, "kontrol_deneme": "²"}, create=False)
        self.assertEqual(self.advisor(self.resume(name)), "", "no crash, and no signal")

    def test_the_switch_off_means_no_flag(self):
        steps = self.workflow(("plan", "plan-inceleme", "kod", "kod-inceleme", "onay"))
        self.assertEqual(self.advisor(self.start(steps["kod"])), "", "no key: off")
        self.on(acik=False)
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "")
        self.on()
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "fable")
        self.on(acik=False)  # turned off again: the next resume has no flag and the record says so
        self.assertEqual(self.advisor(self.resume(steps["kod"])), "")
        self.assertEqual((self.rec(steps["kod"])["danisman"], self.rec(steps["kod"])["danisman_nedeni"]), ("", ""))

    def test_the_running_server_takes_the_switch_from_ofis_json(self):
        danisman.refresh(self.cfg, {"zor_is_danismani": {"acik": True, "model": "fable", "katman": "kod"}})
        self.assertTrue(danisman.hard_settings(self.cfg)["acik"])
        danisman.refresh(self.cfg, {})
        self.assertFalse(danisman.hard_settings(self.cfg)["acik"])

    def test_pilot_jobs_and_the_mapping_keep_their_own_behaviour(self):
        self.on()
        self.start_pilot()
        a, b = self.add(), self.add()
        self.assertEqual((self.rec(a)["danisman_kolu"], self.rec(b)["danisman_kolu"]), ("A", "B"))
        self.assertEqual((self.advisor(self.start(a)), self.advisor(self.start(b))), ("", "fable"))
        for name in (a, b):
            records.update(self.durum, name, {"kontrol_deneme": 1, "kontrol_sonuc": "kaldi",
                                              "yukseltme_kaynagi": a}, create=False)
        self.assertEqual(self.advisor(self.resume(a)), "", "arm A stays without the advisor, hard or not")
        self.assertEqual(self.advisor(self.resume(b)), "fable")
        self.assertNotIn("danisman_nedeni", self.rec(a), "a pilot job's record is the pilot's")
        self.cfg["danisman_pilotu"]["acik"] = False  # the pilot's kill switch still wins
        self.assertEqual(self.advisor(self.resume(b)), "")
        # the permanent mapping: every job of the tier, easy or not
        self.cfg["tiers"]["kod"]["danisman"] = "opus"
        try:
            easy = self.add()
            self.assertEqual(self.advisor(self.start(easy)), "opus")
            self.assertEqual(self.rec(easy)["danisman_nedeni"], "kalıcı eşleme")
        finally:
            self.cfg["tiers"]["kod"].pop("danisman", None)


class PageTest(unittest.TestCase):
    def setUp(self):
        import test_web
        if not test_web.NODE:
            self.skipTest("node is not installed")
        self.run_js = test_web.run_js

    def test_job_card_line_and_quality_lines(self):
        self.assertEqual(self.run_js("[t.danismanMetni({danisman: 'fable'}), t.danismanMetni({danisman: ''}), "
                                     "t.danismanMetni({})]"), ["Danışman: Fable", "", ""])
        self.assertEqual(self.run_js("t.danismanMetni({danisman: 'fable', "
                                     "danisman_nedeni: 'zor iş: geliştirme akışının kod adımı'})"),
                         "Danışman: Fable — zor iş: geliştirme akışının kod adımı")
        running = {"durum": "pilot", "acik": True, "model": "fable", "katman": "kod", "is_sayisi": 10, "eklenen": 3,
                   "A": {"eklenen": 2, "biten": 1}, "B": {"eklenen": 1, "biten": 0}}
        self.assertEqual(self.run_js(f"t.danismanPilotuSatirlari({json.dumps(running)})"),
                         ["Danışman denemesi · kod işler, Fable danışman — deneme sürüyor (3/10 iş · A 2 iş, 1 bitti · "
                          "B 1 iş, 0 bitti)"])
        done = {"durum": "sonuc", "basari": False, "model": "fable", "katman": "kod",
                "sonuc": {"A": {"ilk_tur_gecen": 3, "ilk_tur_olculen": 5, "yeniden_is": 2, "yeniden_is_turu": 3,
                                "dogrulanmis_is_basina_usd": 2.5, "dogrulanmis_is_basina_token": None,
                                "danisman_cagri": None},
                          "B": {"ilk_tur_gecen": 4, "ilk_tur_olculen": 5, "yeniden_is": 1, "yeniden_is_turu": 1,
                                "dogrulanmis_is_basina_usd": 3.5, "dogrulanmis_is_basina_token": None,
                                "danisman_cagri": None}}}
        lines = self.run_js(f"t.danismanPilotuSatirlari({json.dumps(done)})")
        self.assertIn("kanıtlamadı", lines[0])
        self.assertTrue(lines[1].startswith("A (danışmansız): ilk denemede geçti"), lines[1])
        self.assertIn("danışman çağrısı bilinmiyor", lines[2])
        self.assertEqual(self.run_js("t.danismanPilotuSatirlari(null)"), [])


if __name__ == "__main__":
    unittest.main()
