"""Tests for bin/model_secimi.py (phase 8: Karne → pilot → mapping) and its hooks in launch.create_job, ofis.py
(ekle, cevapla, modeller) and the post office. Temp vault, temp durum and a temp ofis.json only."""
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
import fakes  # noqa: E402,F401 (isolates the job lock)
import jobs  # noqa: E402
import karne  # noqa: E402
import launch  # noqa: E402
import model_secimi as ms  # noqa: E402
import ofis  # noqa: E402
import records  # noqa: E402

NOW = datetime(2026, 11, 11, 10, 0, 0)
S = dict(ms.DEFAULTS)
TIERS = {"planlama": {"model": "fable", "effort": "high"}, "kod": {"model": "opus", "effort": "high"},
         "inceleme": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet", "effort": "medium"},
         "kolay": {"model": "haiku", "effort": "low"}}


def m(n, first, measured=None, rework=0, esc=0, verified=None):
    return {"is_sayisi": n, "ilk_tur_gecen": first, "ilk_tur_olculen": n if measured is None else measured,
            "yeniden_is": rework, "yukseltme": esc, "dogrulanmis_is_basina_usd": verified, "bitti": n,
            "dogrulanan": first, "toplam_usd": 0.0, "ort_usd": None, "ort_dogrulanmis_usd": None, "ort_sure_dk": None}


def row(stem, proje="vitrin", katman="kolay", model="haiku", first="evet", yukseltme="hayır", devam=0,
        cost="0.0100", deneme=False):
    values = ("2026-11-10", proje, f"[[{stem}]]", katman, model, "low", first, "1" if first != "yok" else "0",
              yukseltme, "3", cost, cost if first == "evet" else "", "2", "bitti" if first == "evet" else "tikandi",
              str(devam), "", "") + (("", "evet") if deneme else ())
    return "| " + " | ".join(values) + " |"


class FakeCeo:
    def __init__(self):
        self.sent = []

    def enqueue(self, text, key):
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class PureTest(unittest.TestCase):
    def test_the_evidence_shows_tokens_next_to_the_verified_cost(self):
        m = {"is_sayisi": 6, "ilk_tur_olculen": 5, "ilk_tur_gecen": 5, "yeniden_is": 0, "yukseltme": 0,
             "dogrulanmis_is_basina_usd": 0.27, "dogrulanmis_is_basina_token": 182400}
        self.assertEqual(ms.evidence_lines(m)[-1], "- Doğrulanmış iş başına kullanım: 182 bin token · API karşılığı ~$0.2700")
        # evidence stored before tokens (no key) or unknown tokens: the dollars alone, never "0 token"
        old = {k: v for k, v in m.items() if k != "dogrulanmis_is_basina_token"}
        self.assertEqual(ms.evidence_lines(old)[-1], "- Doğrulanmış iş başına kullanım: API karşılığı ~$0.2700")
        self.assertEqual(ms._spend({"dogrulanmis_is_basina_usd": None}), "—")

    def test_model_order_and_effort(self):
        self.assertEqual([ms.neighbour(x, "asagi") for x in ms.MODEL_ORDER], [None, "haiku", "sonnet", "opus"])
        self.assertEqual([ms.neighbour(x, "yukari") for x in ms.MODEL_ORDER], ["sonnet", "opus", "fable", None])
        self.assertIsNone(ms.neighbour("claude-sonnet-5-5", "asagi"))
        self.assertEqual(ms.MODEL_EFFORT, {"haiku": "low", "sonnet": "medium", "opus": "high", "fable": "high"})

    def test_settings_default_and_override(self):
        self.assertEqual(ms.settings({}), ms.DEFAULTS)
        s = ms.settings({"model_onerisi": {"min_is": 8, "asagi_ilk_tur": 0.95, "pilot_is": 0, "yukari_ilk_tur": 7,
                                           "yeniden_oneri_is": True}})
        self.assertEqual((s["min_is"], s["asagi_ilk_tur"], s["pilot_is"], s["yukari_ilk_tur"], s["yeniden_oneri_is"]),
                         (8, 0.95, 3, 0.6, 10))

    def test_cheaper_needs_high_first_pass_low_rework_and_no_escalation(self):
        self.assertEqual(ms.verdict(m(5, 5), "sonnet", S)[:2], ("asagi", "haiku"))
        self.assertEqual(ms.verdict(m(10, 9), "opus", S)[:2], ("asagi", "sonnet"))
        self.assertIsNone(ms.verdict(m(10, 8), "opus", S), "first-pass 0.8 < 0.9 and ≥ 0.6: nothing")
        self.assertIsNone(ms.verdict(m(5, 5, rework=1), "sonnet", S), "rework 0.2 > 0.1")
        self.assertIsNone(ms.verdict(m(10, 10, esc=1), "sonnet", S), "an escalation blocks a cheaper pilot")
        self.assertIsNone(ms.verdict(m(5, 5), "haiku", S), "no cheaper model than haiku")

    def test_stronger_on_low_first_pass_or_many_escalations(self):
        self.assertEqual(ms.verdict(m(5, 2), "haiku", S)[:2], ("yukari", "sonnet"))
        self.assertEqual(ms.verdict(m(10, 7, esc=3), "opus", S)[:2], ("yukari", "fable"))
        self.assertIsNone(ms.verdict(m(5, 1), "fable", S), "no stronger model than fable")
        self.assertIn("ilk turda geçme %40", ms.verdict(m(5, 2), "haiku", S)[2])

    def test_too_few_measured_jobs_propose_nothing(self):
        self.assertIsNone(ms.verdict(m(9, 1, measured=4), "haiku", S))
        self.assertIsNone(ms.verdict(m(4, 4), "sonnet", S))

    def test_pilot_success_rules_measure_like_the_evidence(self):
        self.assertTrue(ms.pilot_success("asagi", m(3, 3), S))
        self.assertFalse(ms.pilot_success("asagi", m(3, 2), S))
        self.assertTrue(ms.pilot_success("asagi", m(3, 2, measured=2), S), "x/measured, like the evidence")
        self.assertFalse(ms.pilot_success("asagi", m(3, 3, esc=1), S))
        self.assertTrue(ms.pilot_success("yukari", m(3, 2), S))
        self.assertFalse(ms.pilot_success("yukari", m(3, 1), S))
        self.assertTrue(ms.pilot_success("yukari", m(3, 2, measured=2), S))
        self.assertFalse(ms.pilot_success("yukari", m(3, 0, measured=0), S), "nothing measured proves nothing")

    def parse(self, lines):
        return [dict(zip(karne.COLUMNS, [c.strip() for c in line.strip().strip("|").split("|")])) for line in lines]

    def test_candidates_count_only_the_mapping_model_and_never_explicit_or_codex(self):
        rows = self.parse([row(f"k{i}", first="hayır" if i < 3 else "evet") for i in range(5)] +
                          [row(f"s{i}", model="sonnet") for i in range(5)] +  # another model: not this mapping
                          [row(f"e{i}", first="hayır") for i in range(3)] +  # explicit --model haiku
                          [row(f"c{i}", katman="inceleme", model="codex", first="yok") for i in range(6)])
        # an explicit --model (elle) and a quota backup (kota, Step 4) never count as evidence
        source = {**{f"e{i}": "elle" for i in range(2)}, "e2": "kota"}.get
        current = {("vitrin", "kolay"): ("haiku", "low"), ("vitrin", "inceleme"): ("opus", "high")}.get

        def cur(p, t):
            return current((p, t)) or (None, None)
        found = ms.candidates(rows, {}, set(), lambda s: source(s, ""), cur, S, lambda p, t: False)
        [c] = found
        self.assertEqual((c["katman"], c["yon"], c["mevcut_model"], c["onerilen_model"], c["onerilen_effort"]),
                         ("kolay", "yukari", "haiku", "sonnet", "medium"))
        self.assertEqual(c["kanit"]["is_sayisi"], 5)
        self.assertEqual(c["kanit"]["isler"], [f"k{i}" for i in range(5)])
        self.assertEqual(ms.candidates(rows, {}, set(), lambda s: "", cur, S, lambda p, t: True), [])


class MappingTest(unittest.TestCase):
    def test_project_override_beats_the_global_tiers_and_explicit_beats_both(self):
        cfg = {"tiers": TIERS, "projects": {"vitrin": {"path": "/x", "tiers": {"kolay": {"model": "sonnet",
                                                                                         "effort": "medium"}}},
                                            "blog": {"path": "/y"}}}
        self.assertEqual(launch.resolve_tier(cfg, "kolay", project="vitrin"), ("kolay", "sonnet", "medium"))
        self.assertEqual(launch.resolve_tier(cfg, "kolay", project="blog"), ("kolay", "haiku", "low"))
        self.assertEqual(launch.resolve_tier(cfg, "kolay"), ("kolay", "haiku", "low"))
        self.assertEqual(launch.resolve_tier(cfg, "kolay", model="opus", project="vitrin"),
                         ("kolay", "opus", "medium"))
        self.assertEqual(launch.tier_entry(cfg, "vitrin", "kolay"), ("sonnet", "medium", "proje"))
        self.assertEqual(launch.tier_entry(cfg, "vitrin", "kod"), ("opus", "high", "katman"))
        self.assertEqual([(e["proje"], e["katman"], e["model"], e["kaynak"]) for e in ms.mapping(cfg)
                          if e["katman"] == "kolay"], [("blog", "kolay", "haiku", "katman"),
                                                       ("vitrin", "kolay", "sonnet", "proje")])

    def test_refresh_takes_the_projects_but_not_the_other_keys_into_a_running_cfg(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ofis.json")
            cfg = {"tiers": TIERS, "default_budget_usd": 3, "projects": {"vitrin": {"path": "/x"}}}
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"tiers": {}, "default_budget_usd": 99, "projects": {
                    "vitrin": {"path": "/elsewhere", "tiers": {"kolay": {"model": "sonnet", "effort": "medium"}}},
                    "new": {"path": "/n"}}}, f)
            seen = ms.refresh_overrides(cfg, path)
            # the Ayarlar page (bin/ayarlar.py tazele): a new project and a changed folder apply without a restart
            self.assertEqual(cfg["projects"], {"vitrin": {"path": "/elsewhere", "tiers": {
                "kolay": {"model": "sonnet", "effort": "medium"}}}, "new": {"path": "/n"}})
            self.assertEqual((cfg["default_budget_usd"], cfg["tiers"]), (3, TIERS))
            self.assertEqual(ms.refresh_overrides(cfg, path, seen), seen)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.project = os.path.join(base, "Dev", "vitrin")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.durum = os.path.join(base, "ajan-ofisi", "durum")
        for d in (self.project, self.vault, self.durum):
            os.makedirs(d)
        self.config = os.path.join(base, "ajan-ofisi", "ofis.json")
        raw = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
               "projects": {"vitrin": {"path": self.project, "description": "W"}, "blog": {"path": self.project}},
               "tiers": TIERS, "default_tier": "genel", "default_budget_usd": 3, "max_queued_per_project": 50}
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
        self.cfg = launch.load(self.config)
        self.ceo = FakeCeo()
        self.advisor = ms.Advisor(self.cfg, self.durum, self.ceo, now=lambda: NOW)
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

    def add(self, *extra, katman="kolay", proje="vitrin", kontrol="true"):
        check = ("--kontrol", kontrol) if kontrol else ()
        return self.ok("ekle", "--proje", proje, "--baslik", "Durum", "--hedef", "Durum özeti.", "--katman", katman,
                       *check, *extra)["is"]

    def write_rows(self, *lines):
        self.lines += lines
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# x\n\n" + karne._table_head(karne.COLUMNS) + "\n".join(self.lines) + "\n")

    def weak_haiku(self, n=5, start=0):
        self.write_rows(*[row(f"2026-11-10-{i:06d}-vitrin", first="hayır" if i % 5 < 3 else "evet")
                          for i in range(start, start + n)])

    def note(self, name):
        with open(os.path.join(self.vault, "Kararlar", name), encoding="utf-8") as f:
            return f.read()

    def state(self, tier="kolay"):
        return ms.load(self.durum, "vitrin", tier)

    def finish(self, name, first=True, escalated=False):
        jobs.update(self.vault, name, status="calisiyor", fields={"baslangic": "2026-11-11T10:00:00"})
        fields = {"bitis": "2026-11-11T10:10:00", "kontrol_deneme": 1 if first else 2,
                  "kontrol_sonuc": "gecti" if first else "gecmedi"}
        jobs.update(self.vault, name, status="bitti" if first else "tikandi", fields=fields)
        if escalated:
            karne.record_correction(self.vault, "vitrin", name, "yukseltme", "taşındı", f"y-{jobs.stem(name)}", NOW)
        karne.process_pending(self.vault, lambda job: None, now=lambda: NOW)

    # --- proposal ---

    def test_a_weak_tier_gets_one_proposal_card_and_one_notice(self):
        self.weak_haiku()
        written = self.advisor.check()
        [note] = written["oneriler"]
        self.assertEqual(note, "2026-11-11-vitrin-kolay-model-onerisi.md")
        text = self.note(note)
        _, meta, body = jobs.parse(text)
        self.assertEqual({k: meta[k] for k in ("proje", "durum", "tur", "katman", "mevcut_model", "onerilen_model",
                                               "yon", "soruldu")},
                         {"proje": "vitrin", "durum": "bekliyor", "tur": "model-onerisi", "katman": "kolay",
                          "mevcut_model": "haiku", "onerilen_model": "sonnet", "yon": "yukari",
                          "soruldu": "2026-11-11T10:00:00"})
        self.assertIn("vitrin'de kolay işler için sonraki 3 iş Stajyer (Haiku) yerine Uzman (Sonnet) ile denensin mi?",
                      jobs.section(body, "Soru"))
        evidence = jobs.section(body, "Kanıt")
        self.assertIn("Kontrol ilk turda geçme: %40 (2/5)", evidence)
        self.assertIn("[[2026-11-10-000000-vitrin]]", evidence)
        self.assertIn("Eşleme şimdilik değişmez", jobs.section(body, "Ne olur"))
        self.assertIn("[[Ozet]]", jobs.section(body, "İlgili Sayfalar"))
        [(notice, key)] = self.ceo.sent
        self.assertTrue(notice.startswith("[Ofis · sistem]\nvitrin kadro önerisi: kolay işler için"), notice)
        self.assertIn("[[2026-11-11-vitrin-kolay-model-onerisi]]", notice)
        self.assertEqual(key, f"model-onerisi-{self.state()['kimlik']}")
        # pending: no second card, no second notice — also after a restart (a new Advisor)
        self.assertEqual(self.advisor.check(), {"oneriler": [], "sonuclar": []})
        ms.Advisor(self.cfg, self.durum, FakeCeo(), now=lambda: NOW).check()
        self.assertEqual(len(os.listdir(os.path.join(self.vault, "Kararlar"))), 1)
        self.assertEqual(self.state()["bildirilen"], [key])

    def test_a_card_that_does_not_match_the_server_state_is_refused(self):
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-11-vitrin-kolay-model-onerisi.md",
                         {"durum": "bekliyor", "proje": "vitrin", "tur": "model-onerisi", "katman": "kolay",
                          "pilot": "x"}, "# x\n\n## Soru\nx\n\n## İlgili Sayfalar\n- [[x]]\n")
        self.assertIn("uyuşmuyor", self.refused("cevapla", "2026-11-11-vitrin-kolay-model-onerisi.md", "Evet"))
        self.assertIn("durum: bekliyor", self.note("2026-11-11-vitrin-kolay-model-onerisi.md"))
        self.assertEqual(self.state()["durum"], "bos")

    def test_a_declined_proposal_waits_for_new_jobs(self):
        self.weak_haiku()
        [note] = self.advisor.check()["oneriler"]
        result = self.ok("cevapla", note, "Hayır, şimdilik kalsın")
        self.assertEqual((result["tur"], result["onay"], result["pilot"]), ("model-onerisi", False, ""))
        self.assertIn("durum: cevaplandi", self.note(note))
        state = self.state()
        self.assertEqual((state["durum"], state["kapanis_satir"], state["gecmis"][-1]["sonuc"]),
                         ("bos", 5, "reddedildi"))
        self.weak_haiku(9, start=5)
        self.assertEqual(self.advisor.check()["oneriler"], [], "9 new rows < yeniden_oneri_is")
        self.weak_haiku(1, start=14)
        self.assertEqual(len(self.advisor.check()["oneriler"]), 1)
        self.assertEqual(len(self.ceo.sent), 2)

    # --- pilot ---

    def start_pilot(self):
        self.weak_haiku()
        [note] = self.advisor.check()["oneriler"]
        result = self.ok("cevapla", note, "Evet")
        self.assertEqual((result["onay"], result["pilot"], result["model"], result["pilot_is"]),
                         (True, self.state()["kimlik"], "sonnet", 3))
        self.assertEqual(self.state()["durum"], "pilot")
        return note

    def test_a_yes_starts_a_pilot_that_takes_the_next_jobs_of_that_tier(self):
        self.start_pilot()
        kimlik = self.state()["kimlik"]
        explicit = self.add("--model", "haiku")
        no_kontrol = self.add(kontrol=None)  # never measured: takes no pilot slot
        other_tier = self.add(katman="genel")
        other_project = self.add(proje="blog")
        escalated = launch.create_job(self.cfg, "vitrin", "Yükseltme", {"hedef": "x", "kontrol": "true"},
                                      tier="kolay", now=NOW, durum_dir=self.durum)
        pilots = [self.add() for _ in range(3)]
        after = self.add()
        for name in pilots:
            meta, rec = jobs.load(self.vault, name).meta, records.load(self.durum, name)
            self.assertEqual((meta["model"], meta["effort"], meta["pilot"], meta["model_kaynagi"]),
                             ("sonnet", "medium", kimlik, "pilot"))
            self.assertEqual((rec["model"], rec["pilot"], rec["model_kaynagi"]), ("sonnet", kimlik, "pilot"))
        for name, source in ((explicit, "elle"), (no_kontrol, "katman"), (other_tier, "katman"), (other_project, "katman"),
                             (escalated.name, "katman"), (after, "katman")):
            meta = jobs.load(self.vault, name).meta
            self.assertNotIn("pilot", meta)
            self.assertEqual(meta["model_kaynagi"], source, name)
            self.assertEqual(records.load(self.durum, name)["model_kaynagi"], source)
        self.assertEqual(jobs.load(self.vault, after).meta["model"], "haiku")
        self.assertEqual(self.state()["pilot_isler"], pilots)
        out = self.ok("modeller")
        self.assertIn("vitrin · kolay: haiku → sonnet (yukari), 3/3 iş eklendi, 0 bitti", out)

    def test_a_workflow_step_with_a_session_can_be_a_pilot_job(self):
        self.write_rows(*[row(f"2026-11-10-{i:06d}-vitrin", katman="kod", model="opus", first="hayır")
                          for i in range(5)])
        [note] = self.advisor.check()["oneriler"]
        self.ok("cevapla", note, "evet")
        out = self.ok("akis", "kucuk-is", "--proje", "vitrin", "--baslik", "Giriş", "--hedef", "Düzelt.",
                      "--kontrol", "test -d .")
        kinds = {}
        for name in out["isler"]:
            rec = records.load(self.durum, name)
            kinds[rec["adim_turu"]] = jobs.load(self.vault, name).meta
        self.assertEqual((kinds["kod"]["model"], kinds["kod"].get("model_kaynagi")), ("fable", "pilot"))
        self.assertNotIn("pilot", kinds["onay"])

    def test_self_test_rows_are_never_evidence_and_a_self_test_job_takes_no_pilot_slot(self):
        self.write_rows(*[row(f"2026-11-10-{i:06d}-vitrin", first="hayır", deneme=True) for i in range(5)])
        self.assertEqual(self.advisor.check()["oneriler"], [], "five self-test rows are no evidence")
        self.write_rows(*[row(f"2026-11-10-{i:06d}-vitrin", first="hayır" if i % 5 < 3 else "evet")
                          for i in range(10, 15)])
        [note] = self.advisor.check()["oneriler"]
        self.assertIn("(2/5)", jobs.section(jobs.parse(self.note(note))[2], "Kanıt"), "only the real rows count")
        self.ok("cevapla", note, "evet")
        trial = self.add("--deneme")
        self.assertNotIn("pilot", jobs.load(self.vault, trial).meta)
        self.assertEqual(self.state()["pilot_isler"], [])

    def test_deneme_isaretle_refuses_a_pilot_job(self):
        # review 2026-11-12: a marked pilot job would vanish from the pilot's measurement
        self.start_pilot()
        pilot = self.add()
        self.finish(pilot, first=False)
        err = self.refused("deneme-isaretle", pilot)
        self.assertIn("REFUSED:", err)
        self.assertIn("pilot", err)
        self.assertEqual(records.load(self.durum, pilot).get("deneme", ""), "")

    def test_the_pilot_is_measured_from_all_its_rows_even_a_self_test_one(self):
        self.start_pilot()
        pilots = [self.add() for _ in range(3)]
        for name, first in zip(pilots, (True, False, True)):
            self.finish(name, first=first)
        karne.mark_trial(self.vault, pilots[1])  # a failed pilot row marked by any route still counts for the pilot
        self.advisor.check()
        self.assertEqual((self.state()["sonuc"]["ilk_tur_olculen"], self.state()["sonuc"]["ilk_tur_gecen"]), (3, 2))

    def test_new_rows_after_a_closed_cycle_are_counted_on_the_same_basis(self):
        # review 2026-11-12: kapanis_satir counts every row (self-tests too); the comparison must too
        self.write_rows(*[row(f"2026-11-09-{i:06d}-vitrin", deneme=True) for i in range(10)])
        ms.save(self.durum, {"proje": "vitrin", "katman": "kolay", "durum": "bos", "kapanis_satir": 10,
                             "gecmis": [], "bildirilen": []})
        self.weak_haiku(n=10)
        self.assertEqual(len(self.advisor.check()["oneriler"]), 1, "ten new rows since the cycle closed")

    def finish_pilot(self, firsts):
        self.start_pilot()
        pilots = [self.add() for _ in firsts]
        self.assertEqual(self.advisor.check()["sonuclar"], [], "the pilot is not done yet")
        for name, first in zip(pilots, firsts):
            self.finish(name, first=first)
        [result] = self.advisor.check()["sonuclar"]
        return result

    def test_a_successful_pilot_asks_and_a_yes_changes_the_mapping(self):
        with open(self.config, encoding="utf-8") as f:
            before = json.load(f)
        result = self.finish_pilot([True, True, False])  # 2/3 ≥ 0.6: a stronger model proved itself
        self.assertEqual(result, "2026-11-11-vitrin-kolay-model-pilot-sonucu.md")
        _, meta, body = jobs.parse(self.note(result))
        self.assertEqual((meta["tur"], meta["durum"], meta["basari"], meta["onerilen_model"]),
                         ("model-pilot-sonucu", "bekliyor", "evet", "sonnet"))
        self.assertIn("Eşleme değişsin mi: vitrin kolay → Uzman (Sonnet)?", jobs.section(body, "Soru"))
        table = jobs.section(body, "Karşılaştırma")
        self.assertIn("| Kontrol ilk turda geçme | %40 (2/5) | %67 (2/3) |", table)
        self.assertIn("| İş sayısı (kontrolü çalışan) | 5 (5) | 3 (3) |", table)
        notice = self.ceo.sent[-1][0]
        self.assertIn("vitrin kadro denemesi bitti: kolay işler Uzman (Sonnet) ile (3 iş). Pilot başarılı", notice)
        self.assertEqual(self.advisor.check(), {"oneriler": [], "sonuclar": []})
        self.assertEqual(len(self.ceo.sent), 2)

        answer = self.ok("cevapla", result, "Onaylıyorum")
        self.assertEqual((answer["eslesme_degisti"], answer["model"]), (True, "sonnet"))
        with open(self.config, encoding="utf-8") as f:
            raw = f.read()
        after = json.loads(raw)
        self.assertEqual(list(after), list(before), "key order kept")
        self.assertEqual(list(after["projects"]["vitrin"]), ["path", "description", "tiers"])
        self.assertEqual(after["projects"]["vitrin"]["tiers"], {"kolay": {"model": "sonnet", "effort": "medium"}})
        self.assertEqual({k: v for k, v in after.items() if k != "projects"},
                         {k: v for k, v in before.items() if k != "projects"})
        self.assertTrue(raw.endswith("}\n"))
        with open(os.path.join(self.vault, "Karne", "Degisiklikler.md"), encoding="utf-8") as f:
            changes = f.read()
        self.assertIn("| 2026-11-11 | vitrin · kolay: haiku/low → sonnet/medium | Pilot 3 iş: ilk turda geçme %67 "
                      "(2/3), yükseltme 0; önceki 5 iş: ilk turda geçme %40 (2/5), yükseltme 0 | "
                      "[[2026-11-11-vitrin-kolay-model-pilot-sonucu]] |", changes)
        state = self.state()
        self.assertEqual((state["durum"], state["gecmis"][-1]["sonuc"]), ("bos", "eslesme-degisti"))
        # the override now drives ekle (this process; the server reads the file again)
        name = self.add()
        meta = jobs.load(self.vault, name).meta
        self.assertEqual((meta["model"], meta["effort"], meta["model_kaynagi"]), ("sonnet", "medium", "proje"))
        self.assertIn("vitrin · kolay → sonnet / medium (proje)", self.ok("modeller"))
        self.refused("cevapla", result, "Evet")

    def test_a_failed_pilot_changes_nothing_even_on_yes(self):
        with open(self.config, encoding="utf-8") as f:
            before = f.read()
        result = self.finish_pilot([True, False, False])  # 1/3 < 0.6
        _, meta, body = jobs.parse(self.note(result))
        self.assertEqual(meta["basari"], "hayır")
        self.assertIn("Pilot öneriyi kanıtlamadı; eşleme değişmeyecek", jobs.section(body, "Soru"))
        self.assertIn("kanıtlamadı", self.ceo.sent[-1][0])
        answer = self.ok("cevapla", result, "evet")
        self.assertEqual((answer["eslesme_degisti"], answer["model"]), (False, "haiku"))
        with open(self.config, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        changes = os.path.join(self.vault, "Karne", "Degisiklikler.md")
        if os.path.exists(changes):
            with open(changes, encoding="utf-8") as f:
                self.assertNotIn("model-pilot-sonucu", f.read())
        self.assertEqual(self.state()["gecmis"][-1]["sonuc"], "degismedi")

    def test_a_cheaper_pilot_needs_every_job_first_time_and_no_escalation(self):
        self.write_rows(*[row(f"2026-11-10-{i:06d}-vitrin", katman="genel", model="sonnet") for i in range(5)])
        [note] = self.advisor.check()["oneriler"]
        self.assertEqual((self.state("genel")["yon"], self.state("genel")["onerilen_model"]), ("asagi", "haiku"))
        self.ok("cevapla", note, "tamam")
        pilots = [self.add(katman="genel") for _ in range(3)]
        self.assertEqual({jobs.load(self.vault, n).meta["model"] for n in pilots}, {"haiku"})
        for i, name in enumerate(pilots):
            self.finish(name, first=True, escalated=(i == 2))
        [result] = self.advisor.check()["sonuclar"]
        self.assertFalse(self.state("genel")["basari"], "an escalated pilot job proves nothing")
        self.assertIn("| Bir üst katmana taşınan | 0/5 | 1/3 |", self.note(result))

    # --- phase 8 review ---

    def test_a_card_whose_write_failed_is_written_again_before_any_notice(self):
        self.weak_haiku()
        real = ms._write_note
        ms._write_note = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        try:
            with self.assertRaises(OSError):
                self.advisor.check()
        finally:
            ms._write_note = real
        self.assertEqual(self.state()["durum"], "oneri")
        self.assertEqual(self.ceo.sent, [], "no notice links a missing card")
        self.advisor.check()
        note = self.state()["oneri_notu"]
        _, meta, body = jobs.parse(self.note(note))
        self.assertEqual((meta["tur"], meta["durum"], meta["soruldu"]), ("model-onerisi", "bekliyor",
                                                                         "2026-11-11T10:00:00"))
        [(notice, _)] = self.ceo.sent
        self.assertIn(note[:-3], notice)
        before = self.note(note)
        self.advisor.check()
        self.assertEqual(self.note(note), before, "an existing card is never rewritten")

    def test_a_pilot_job_started_with_a_quota_backup_frees_its_slot(self):
        # Step 4: a job that ran with the quota backup never measures the pilot model
        self.start_pilot()
        first = self.add()
        records.update(self.durum, first, {"kota_yedegi": {"asil": "sonnet", "yedek": "opus"}, "model_kaynagi": "kota"})
        self.advisor.check()
        self.assertEqual(self.state()["pilot_isler"], [])
        second = self.add()
        self.assertEqual(jobs.load(self.vault, second).meta.get("pilot"), self.state()["kimlik"])

    def test_a_pilot_job_cancelled_before_it_started_frees_its_slot(self):
        self.start_pilot()
        first, second = self.add(), self.add()
        self.ok("iptal", first)  # never started
        jobs.update(self.vault, second, status="calisiyor", fields={"baslangic": "2026-11-11T10:05:00"})
        self.ok("iptal", second)  # started, then cancelled: keeps its slot (it ran with the pilot model)
        self.advisor.check()
        self.assertEqual(self.state()["pilot_isler"], [second])
        third = self.add()
        self.assertEqual(jobs.load(self.vault, third).meta.get("pilot"), self.state()["kimlik"])

    def clock_advisor(self, clock):
        return ms.Advisor(self.cfg, self.durum, self.ceo, now=lambda: clock[0])

    def reminders(self):
        return [(t, k) for t, k in self.ceo.sent if k.startswith("model-hatirlatma-")]

    def test_an_unanswered_card_is_remembered_after_3_days_then_weekly(self):
        from datetime import timedelta
        self.weak_haiku()
        clock = [NOW]
        advisor = self.clock_advisor(clock)
        [note] = advisor.check()["oneriler"]
        for days, expected in ((2, 0), (3, 1), (5, 1), (9, 1), (10, 2), (12, 2), (17, 3)):
            clock[0] = NOW + timedelta(days=days)
            self.clock_advisor(clock).check()  # a new Advisor each time: what was sent survives a restart
            self.assertEqual(len(self.reminders()), expected, days)
        text, key = self.reminders()[0]
        self.assertTrue(text.startswith("[Ofis · sistem]\nvitrin kadro kararı 3 gündür cevap bekliyor: "
                                        f"[[{note[:-3]}]]"), text)
        self.assertTrue(key.endswith("-1"))
        self.assertIn("durum: bekliyor", self.note(note), "a reminder never closes the card")
        self.ok("cevapla", note, "Hayır")
        clock[0] = NOW + timedelta(days=40)
        self.clock_advisor(clock).check()
        self.assertEqual(len(self.reminders()), 3, "an answered card is not remembered")

    def test_a_pilot_job_that_never_starts_is_remembered(self):
        from datetime import timedelta
        self.start_pilot()
        held = self.add("--beklet")
        clock = [NOW + timedelta(days=3, minutes=1)]
        self.clock_advisor(clock).check()
        self.clock_advisor(clock).check()
        [(text, _)] = self.reminders()
        self.assertIn(f"model denemesinin işi 3 gündür başlamadı: [[{jobs.stem(held)}]]", text)
        jobs.update(self.vault, held, status="calisiyor", fields={"baslangic": "2026-11-14T11:00:00"})
        clock[0] = NOW + timedelta(days=20)
        self.clock_advisor(clock).check()
        self.assertEqual(len(self.reminders()), 1, "a started pilot job is not remembered")

    def test_a_degisiklikler_file_that_cannot_be_written_refuses_before_ofis_json_changes(self):
        with open(self.config, encoding="utf-8") as f:
            before = f.read()
        result = self.finish_pilot([True, True, True])
        path = os.path.join(self.vault, "Karne", "Degisiklikler.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)
        os.makedirs(path)  # not a plain file
        self.refused("cevapla", result, "Evet")
        with open(self.config, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.state()["durum"], "sonuc")
        os.rmdir(path)
        real = ms.record_change
        ms.record_change = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            answer = self.ok("cevapla", result, "Evet")
        finally:
            ms.record_change = real
        self.assertTrue(answer["eslesme_degisti"])
        self.assertIn("satır eksik", answer["uyari"])
        self.assertEqual(self.state()["gecmis"][-1]["sonuc"], "eslesme-degisti")
        with open(self.config, encoding="utf-8") as f:
            self.assertIn('"sonnet"', f.read())

    def test_a_workflow_kod_step_counts_only_once_its_workflow_is_closed(self):
        # phase 8 re-review: a code review's DÜZELT can reopen a bitti kod step; the pilot waits for the workflow
        import akis
        self.cfg["model_onerisi"] = {"pilot_is": 1}
        self.write_rows(*[row(f"2026-11-10-{i:06d}-vitrin", katman="kod", model="opus", first="hayır")
                          for i in range(5)])
        [note] = self.advisor.check()["oneriler"]
        self.ok("cevapla", note, "evet")
        out = self.ok("akis", "kucuk-is", "--proje", "vitrin", "--baslik", "Giriş", "--hedef", "Düzelt.",
                      "--kontrol", "test -d .")
        [kod] = [n for n in out["isler"] if records.load(self.durum, n)["adim_turu"] == "kod"]
        self.assertEqual(self.state("kod")["pilot_isler"], [kod])
        records.update(self.durum, kod, {"kontrol_deneme": 1, "kontrol_sonuc": "gecti"})
        self.finish(kod, first=True)
        self.assertEqual(self.advisor.check()["sonuclar"], [], "the review may still reopen the kod step")
        self.assertEqual(self.state("kod")["durum"], "pilot")
        flow = akis.load_state(self.durum, out["grup"])
        flow["durum"] = "bitti"
        akis.save_state(self.durum, flow)
        [result] = self.advisor.check()["sonuclar"]
        self.assertTrue(self.state("kod")["basari"])
        self.assertIn("| Kontrol ilk turda geçme | %0 (0/5) | %100 (1/1) |", self.note(result))

    def test_the_page_lists_mapping_pilots_and_cards(self):
        self.start_pilot()
        self.add()
        page = ms.page(self.cfg, self.durum)
        [pilot] = page["pilotlar"]
        self.assertEqual({k: pilot[k] for k in ("proje", "katman", "model", "eklenen", "biten", "toplam", "yon")},
                         {"proje": "vitrin", "katman": "kolay", "model": "sonnet", "eklenen": 1, "biten": 0,
                          "toplam": 3, "yon": "yukari"})
        self.assertEqual(page["oneriler"], [])
        self.assertIn({"proje": "vitrin", "katman": "kolay", "model": "haiku", "effort": "low", "kaynak": "katman"},
                      page["eslesme"])


if __name__ == "__main__":
    unittest.main()
