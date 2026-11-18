"""Tests for bin/talimat_denetimi.py, the prompt audit when a model changes (owner decision 2026-11-14): the trigger on a
recorded mapping change, on the advisor made permanent and on a hand edit, never on a quota fallback or a running pilot;
idempotence and one open audit; the brief's paths (no forbidden project, no vault root, nothing outside the repo / projects); the
contract snapshots; the note, the card and the one notice; the CLI and its denial for project sessions; the switch.
Temp vault/durum only. Run: python3 -I test/test_talimat_denetimi.py"""
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401
import jobs  # noqa: E402
import kontrol  # noqa: E402
import launch  # noqa: E402
import ofis  # noqa: E402
import records  # noqa: E402
import talimat_denetimi as td  # noqa: E402

NOW = datetime(2026, 11, 14, 10, 0, 0)


class FakeCeo:
    def __init__(self):
        self.sent = []

    def enqueue(self, text, key):
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.vault_root = os.path.join(base, "vault")
        self.vault = os.path.join(self.vault_root, "OFIS")
        self.durum = os.path.join(base, "durum")
        dev = os.path.join(base, "Dev")
        for p in ("blog", "kasa", "ofis-arge", "zim-eski"):
            os.makedirs(os.path.join(dev, p))
        os.makedirs(self.vault)
        self.blog_md = os.path.join(dev, "blog", "CLAUDE.md")
        for path in (self.blog_md, os.path.join(dev, "blog", "REVIEW.md"),
                     os.path.join(dev, "zim-eski", "CLAUDE.md"), os.path.join(self.vault_root, "CLAUDE.md")):
            with open(path, "w", encoding="utf-8") as f:
                f.write("# kurallar\n")
        # kasa's CLAUDE.md is a link out of its folder (to the vault's root): never listed
        os.symlink(os.path.join(self.vault_root, "CLAUDE.md"), os.path.join(dev, "kasa", "CLAUDE.md"))
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault, "default_budget_usd": 3,
                    "ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"},
                    "projects": {"blog": {"path": os.path.join(dev, "blog")},
                                 "kasa": {"path": os.path.join(dev, "kasa")},
                                 "eski": {"path": os.path.join(dev, "zim-eski")},
                                 "arge": {"path": os.path.join(dev, "ofis-arge")}},
                    "tiers": {"genel": {"model": "sonnet", "effort": "medium", "butce_usd": 1.5},
                              "kod": {"model": "opus", "effort": "high"},
                              "planlama": {"model": "fable", "effort": "high"}},
                    "max_running": 3, "max_running_per_project": 1, "max_queued_per_project": 5,
                    "talimat_denetimi": {"acik": True, "katman": "genel", "butce_usd": 1.5}}
        self.ceo = FakeCeo()
        self.now = NOW
        self.added = []
        self.refuse = 0

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **kw):
        self.added.append(dict(kw))
        if self.refuse:
            self.refuse -= 1
            raise launch.Refused("Sıradakiler dolu: arge projesinde 5 iş sırada (sınır 5)")
        try:
            return ofis.add_job(self.cfg, self.durum, kw.pop("project"), kw.pop("title"), kw.pop("brief"),
                                kw.pop("now"), **kw)
        except ofis.Refused as e:
            raise launch.Refused(str(e)) from None

    def worker(self, bekle=0):
        return td.TalimatDenetimi(lambda: self.cfg, self.durum, self.ceo, add=self.add, now=lambda: self.now,
                                  bekle=bekle)

    def baseline(self, w):
        w.kontrol()  # the first pass: the baseline only
        self.assertEqual(self.added, [])
        self.assertIsNotNone(td.son(self.durum))

    def audits(self):
        return td.liste(self.durum)

    def finish(self, name, status="bitti", text="", proof="yok"):
        records.update(self.durum, name, {"kontrol_sonuc": proof})
        jobs.update(self.vault, name, status=status, fields={"bitis": "2026-11-14T11:00:00"})
        if text:
            kontrol.save_report(self.durum, name, text)


class TriggerTest(Base):
    def test_a_recorded_mapping_change_triggers_one_audit(self):
        w = self.worker()
        self.baseline(w)
        # what model_secimi.answer writes on a plain yes to a successful pilot result
        self.cfg["projects"]["blog"]["tiers"] = {"genel": {"model": "haiku", "effort": "low"}}
        w.kontrol()
        w.kontrol()
        items = self.audits()
        self.assertEqual(len(items), 1)
        self.assertEqual(len(self.added), 1)
        self.assertEqual(items[0]["fark"], ["blog · genel: genel eşleme → haiku"])
        self.assertEqual(items[0]["neden"], "eslem")
        self.assertEqual(td.son(self.durum)["imza"], td.imza(td.eslem(self.cfg)))

    def test_the_advisor_made_permanent_triggers(self):
        w = self.worker()
        self.baseline(w)
        self.cfg["tiers"]["kod"]["danisman"] = "fable"  # danisman.answer on a successful result
        w.kontrol()
        self.assertEqual(self.audits()[0]["fark"], ["kod danışman: yok → fable"])

    def test_a_hand_edit_seen_at_startup_triggers(self):
        self.baseline(self.worker())
        self.cfg["tiers"]["genel"]["model"] = "opus"  # edited while the server was off
        self.worker().kontrol()  # a new server process
        self.assertEqual(self.audits()[0]["fark"], ["genel: sonnet → opus"])

    def test_temporary_changes_never_trigger(self):
        w = self.worker()
        self.baseline(w)
        # a running model pilot, the advisor pilot's switch and the quota fallback are server state / other keys
        self.cfg["danisman_pilotu"] = {"acik": True, "model": "fable", "is_sayisi": 10, "katman": "kod"}
        self.cfg["kota_yedegi"] = {"opus": "sonnet"}
        self.cfg["tiers"]["kod"]["effort"] = "max"
        self.cfg["tiers"]["kod"]["butce_usd"] = 9
        os.makedirs(os.path.join(self.durum, "model_secimi"))
        with open(os.path.join(self.durum, "model_secimi", "blog__genel.json"), "w") as f:
            json.dump({"durum": "pilot", "model": "haiku"}, f)
        w.kontrol()
        self.assertEqual((self.audits(), self.added), ([], []))

    def test_one_change_set_waits_until_it_is_stable(self):
        w = self.worker(bekle=60)
        self.baseline(w)
        self.cfg["tiers"]["kod"]["model"] = "fable"
        w.kontrol()
        self.cfg["tiers"]["genel"]["model"] = "opus"  # a second edit right after: the same change set
        self.now += timedelta(seconds=30)
        w.kontrol()
        self.now += timedelta(seconds=59)
        w.kontrol()
        self.assertEqual(self.audits(), [])
        self.now += timedelta(seconds=2)
        w.kontrol()
        self.assertEqual(len(self.audits()), 1)
        self.assertEqual(self.audits()[0]["fark"], ["genel: sonnet → opus", "kod: opus → fable"])

    def test_never_two_open_audits_then_the_next_change_after_it_closes(self):
        w = self.worker()
        self.baseline(w)
        self.cfg["tiers"]["kod"]["model"] = "fable"
        w.kontrol()
        first = self.audits()[0]
        self.cfg["tiers"]["genel"]["model"] = "opus"
        w.kontrol()
        w.kontrol()
        self.assertEqual(len(self.audits()), 1)
        self.finish(first["is"], text="## Bulgular\nyok\n## Özet\nTemiz.")
        self.now += timedelta(minutes=1)
        w.kontrol()  # the note; the next pass sees the newer change
        w.kontrol()
        self.assertEqual(len(self.audits()), 2)
        self.assertEqual(self.audits()[1]["fark"], ["genel: sonnet → opus"])

    def test_switched_off_nothing_happens(self):
        self.cfg["talimat_denetimi"]["acik"] = False
        w = self.worker()
        w.kontrol()
        self.cfg["tiers"]["kod"]["model"] = "fable"
        w.kontrol()
        self.assertEqual((self.audits(), self.added, td.son(self.durum)), ([], [], None))
        with self.assertRaises(td.Refused):
            td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        del self.cfg["talimat_denetimi"]
        self.assertIsNone(td.ayar(self.cfg))

    def test_a_full_queue_is_retried_and_never_added_twice(self):
        w = self.worker()
        self.baseline(w)
        self.refuse = 1
        self.cfg["tiers"]["kod"]["model"] = "fable"
        w.kontrol()
        it = self.audits()[0]
        self.assertFalse(it.get("is"))
        self.assertIn("dolu", it["is_hatasi"])
        w.kontrol()  # too early for a retry
        self.assertEqual(len(self.added), 1)
        self.now += timedelta(minutes=td.RETRY_DK)
        w.kontrol()
        w.kontrol()
        self.assertEqual(len(self.added), 2)
        self.assertTrue(self.audits()[0]["is"])
        self.assertEqual(len(self.audits()), 1)

    def test_a_crash_after_the_add_adopts_the_job(self):
        out = td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        it = td.yukle(self.durum, out["talimat_denetimi"])
        name = it.pop("is")
        it.update({"ekleniyor": True, "durum": "is-bekliyor"})
        td._kaydet(self.durum, it)
        self.worker().kontrol()
        self.assertEqual(len(self.added), 1)
        self.assertEqual(td.yukle(self.durum, it["id"])["is"], name)


class JobTest(Base):
    def test_the_job_brief_record_and_snapshots(self):
        out = td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        call = self.added[0]
        self.assertEqual((call["project"], call["tier"], call["budget"], call["uzmanlik"]),
                         ("arge", "genel", 1.5, "analiz"))
        name = out["is"]
        self.assertEqual(records.server_value(self.durum, name, "talimat_denetimi"), out["talimat_denetimi"])
        self.assertFalse(kontrol.load(self.durum, name))  # a read-only report: no Kontrol
        folder = os.path.join(self.durum, "talimat_denetimi", out["talimat_denetimi"])
        for t in ("genel", "kod", "planlama"):
            with open(os.path.join(folder, f"sozlesme-{t}.txt"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("bildir --oturum ofis-ornek-" + t, text)
        with open(os.path.join(folder, "sozlesme-kod.txt"), encoding="utf-8") as f:
            self.assertIn(launch.KOD_CONTRACT.strip()[:40], f.read())
        hedef = call["brief"]["hedef"]
        self.assertIn('Skill("claude-api", "prompt-audit")', hedef)
        self.assertIn("ÖNERİ-DOSYA:", hedef)
        self.assertIn("- kod: opus", hedef)

    def test_the_brief_lists_only_allowed_paths(self):
        td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        hedef = self.added[0]["brief"]["hedef"]
        paths = [line[2:].split(" (")[0] for line in hedef.splitlines() if line.startswith("- /")]
        self.assertIn(self.blog_md, paths)
        self.assertIn(os.path.join(td.ROOT, "CLAUDE.md"), paths)
        self.assertNotIn("zim", hedef.lower())
        self.assertNotIn(os.path.join(self.vault_root, "CLAUDE.md"), hedef)
        self.assertNotIn(os.path.join(os.path.dirname(self.blog_md).replace("blog", "kasa"), "CLAUDE.md"), hedef)
        snaps = os.path.join(self.durum, "talimat_denetimi")
        for p in paths:
            self.assertTrue(p.startswith(td.ROOT + os.sep) or p.startswith(os.path.dirname(os.path.dirname(
                self.blog_md)) + os.sep) or p.startswith(snaps + os.sep), p)
        self.assertLess(len(jobs.render_brief(self.added[0]["brief"])), launch.MAX_TASK)

    def test_the_tier_and_budget_from_config(self):
        self.cfg["talimat_denetimi"] = {"acik": True, "katman": "planlama", "butce_usd": 2}
        td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        self.assertEqual((self.added[0]["tier"], self.added[0]["budget"]), ("planlama", 2.0))
        self.assertEqual(td.ayar({"talimat_denetimi": {"acik": True, "katman": "kod", "butce_usd": 99}}),
                         {"katman": "genel", "butce": td.DEFAULT_BUTCE})

    def test_an_open_audit_refuses_a_second(self):
        td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        with self.assertRaises(td.Refused):
            td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        self.assertEqual(len(self.added), 1)


REPORT = """## Bulgular
BULGU: {md}:3 | BÜYÜK HARF vurgu | yeni modelde gereksiz | yüksek
## Önerilen değişiklikler
ÖNERİ-DOSYA: {md} | vurguyu yumuşat [[Token]] <img src=x>
```diff
-ASLA
+Yapma
```
ÖNERİ-DOSYA: {root}/CLAUDE.md | tekrar eden kuralı sil
ÖNERİ-DOSYA: /etc/passwd | bir şey
## Özet
İki öneri var.
"""


class ResultTest(Base):
    def start(self):
        out = td.olustur(self.cfg, self.durum, "elle", NOW, self.add)
        return out["talimat_denetimi"], out["is"]

    def test_the_note_card_and_one_notice(self):
        aid, name = self.start()
        self.finish(name, text=REPORT.format(md=self.blog_md, root=td.ROOT))
        w = self.worker()
        w.kontrol()
        w.kontrol()
        it = td.yukle(self.durum, aid)
        self.assertEqual(it["not_adi"], "TalimatDenetimi-2026-11-14")
        with open(os.path.join(self.vault, "ArGe", it["not_adi"] + ".md"), encoding="utf-8") as f:
            note = f.read()
        self.assertIn("blog · CLAUDE.md", note)
        self.assertIn("Ofis · CLAUDE.md (geliştirici değişikliği)", note)
        self.assertIn("Tanınmayan yol", note)
        self.assertNotIn("\n[[Token]]", note)
        self.assertNotIn("<img", note.split("## Rapor")[0])
        self.assertIn("> ```", note)  # the report in a quoted fence
        kart = os.path.join(self.vault, "Kararlar", it["kart"])
        with open(kart, encoding="utf-8") as f:
            _, meta, body = jobs.parse(f.read())
        self.assertEqual((meta["tur"], meta["durum"], meta["proje"]), ("talimat-denetimi", "bekliyor", "ofis"))
        self.assertIn("1 proje dosyası", body)
        self.assertNotIn("<img", body)
        self.assertEqual(len(self.ceo.sent), 1)
        text, key = self.ceo.sent[0]
        self.assertTrue(text.startswith("[Ofis · sistem]\nTalimat denetimi bitti: 3 öneri · [[TalimatDenetimi-2026-11-14]]"))
        self.assertIn(jobs.stem(it["kart"]), text)
        self.assertEqual(key, f"talimat-{aid}")
        # idempotent: nothing again, no second card
        w.kontrol()
        self.assertEqual(len(self.ceo.sent), 1)
        self.assertEqual(len([n for n in os.listdir(os.path.join(self.vault, "Kararlar"))]), 1)

    def test_a_crash_after_the_card_write_reuses_the_card(self):
        # Codex 2026-11-14: the card was written but item["kart"] was not saved -> the retry must not open a second one
        aid, name = self.start()
        self.finish(name, text=REPORT.format(md=self.blog_md, root=td.ROOT))
        real = td._kaydet
        calls = {"n": 0}
        def crash_after_card(durum_dir, item):
            if item.get("kart") and not calls["n"]:
                calls["n"] += 1
                raise OSError("power cut")
            return real(durum_dir, item)
        td._kaydet = crash_after_card
        try:
            try:
                self.worker().kontrol()
            except OSError:
                pass
        finally:
            td._kaydet = real
        self.worker().kontrol()
        cards = os.listdir(os.path.join(self.vault, "Kararlar"))
        self.assertEqual(len(cards), 1, cards)
        self.assertEqual(td.yukle(self.durum, aid)["kart"], cards[0])

    def test_no_proposal_no_card(self):
        aid, name = self.start()
        self.finish(name, text="## Bulgular\nyok\n## Önerilen değişiklikler\nyok\n## Özet\nTemiz.")
        self.worker().kontrol()
        self.assertFalse(td.yukle(self.durum, aid).get("kart"))
        self.assertIn("0 öneri", self.ceo.sent[0][0])
        self.assertIn("Temiz.", self.ceo.sent[0][0])

    def test_a_stuck_job_only_gets_its_note(self):
        aid, name = self.start()
        self.finish(name, status="tikandi")
        self.worker().kontrol()
        it = td.yukle(self.durum, aid)
        self.assertEqual((it["durum"], it["bildirildi"]), ("kapandi", True))
        self.assertEqual(self.ceo.sent, [])

    def test_the_card_is_answered_through_cevapla_as_a_ceo_decision(self):
        aid, name = self.start()
        self.finish(name, text=REPORT.format(md=self.blog_md, root=td.ROOT))
        self.worker().kontrol()
        kart = td.yukle(self.durum, aid)["kart"]
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", "cevapla", kart, "evet"], cfg=self.cfg, durum_dir=self.durum, now=lambda: NOW,
                         out=out, err=err, cwd=os.path.dirname(self.durum))
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["onay"], True)


class CommandTest(Base):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, now=lambda: NOW, out=out, err=err,
                         cwd=os.path.dirname(self.durum))
        return code, out.getvalue(), err.getvalue()

    def test_ofis_py_talimat_denetimi_adds_the_job(self):
        code, out, err = self.run_cli("talimat-denetimi")
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        it = td.yukle(self.durum, result["talimat_denetimi"])
        self.assertEqual((it["neden"], it["is"]), ("elle", result["is"]))
        self.assertEqual(records.server_value(self.durum, result["is"], "talimat_denetimi"), it["id"])
        self.assertEqual(td.son(self.durum)["imza"], td.imza(td.eslem(self.cfg)))  # the trigger never repeats it
        code, _, err = self.run_cli("talimat-denetimi")
        self.assertEqual(code, 1)
        self.assertIn("açık bir talimat denetimi var", err)

    def test_switched_off_the_command_refuses(self):
        self.cfg["talimat_denetimi"]["acik"] = False
        code, _, err = self.run_cli("talimat-denetimi")
        self.assertEqual(code, 1)
        self.assertIn("kapalı", err)

    def test_project_sessions_are_denied_the_command(self):
        self.assertIn("talimat-denetimi", launch.DENIED_COMMANDS)
        flags = launch.session_flags("blog", "ofis-blog-x")
        rules = flags[flags.index("--disallowedTools") + 1:flags.index("--append-system-prompt")]
        self.assertIn(f"Bash(python3 {launch.OFIS_PY} talimat-denetimi:*)", rules)


class PostOfficeTest(unittest.TestCase):
    """A prompt-audit job's bitti never takes the Ar-Ge report path; its done notice is left to the writer."""

    def setUp(self):
        import test_postoffice
        self.tp = test_postoffice
        test_postoffice.PostOfficeTest.setUp(self)
        self.arge = os.path.join(os.path.dirname(self.project), "ofis-arge")
        os.makedirs(self.arge)
        self.cfg["projects"]["arge"] = {"path": self.arge, "description": "Ar-Ge"}
        self.cfg["talimat_denetimi"] = {"acik": True}
        self.fake.set_name(test_postoffice.PROJECT_SID, test_postoffice.ARGE_SESSION)

    def tearDown(self):
        self.tp.PostOfficeTest.tearDown(self)

    def cli_run(self, *argv, cwd=None):
        return self.tp.PostOfficeTest.cli_run(self, *argv, cwd=cwd)

    def test_the_report_goes_to_the_audit_note_with_one_notice(self):
        import arge
        tp = self.tp

        def add(project, title, brief, now, **kw):
            return ofis.add_job(self.cfg, self.durum, project, title, brief, now, **kw)
        out = td.olustur(self.cfg, self.durum, "elle", tp.NOW, add)
        name = out["is"]
        self.cli_run("baslat", name)
        jobs.update(self.vault, name, fields={"kisa_id": tp.PROJECT_SID[:8]})
        records.update(self.durum, name, {"kisa_id": tp.PROJECT_SID[:8]})
        self.fake.set_agents([])
        self.cli_run("bildir", "--oturum", tp.ARGE_SESSION, "--tur", "bitti",
                     "## Bulgular\nyok\n## Özet\nTemiz.", cwd=self.arge)
        self.po.process_inbox()
        self.assertEqual(jobs.load(self.vault, name).meta["durum"], "bitti")
        self.assertFalse(arge.kaydi_var(self.durum, name))
        self.assertEqual([q["text"] for q in self.ceo.queue() if "işi bitti" in q["text"]], [])
        w = td.TalimatDenetimi(lambda: copy.deepcopy(self.cfg), self.durum, self.ceo, add=add, now=lambda: tp.NOW,
                               bekle=0)
        w.kontrol()
        w.kontrol()
        notices = [q["text"] for q in self.ceo.queue() if "Talimat denetimi bitti" in q["text"]]
        self.assertEqual(len(notices), 1)


if __name__ == "__main__":
    unittest.main()
