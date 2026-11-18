"""Tests for bin/ozet.py: the morning summary OFIS/Ozetler/YYYY-MM-DD.md and its single CEO notice (plan "Sonraki iş
(7)" Ekler, owner decision 2026-11-12)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402
import ozet  # noqa: E402
import records  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")


def at(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ)


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
        self.vault = os.path.join(self.tmp.name, "vault", "OFIS")
        self.durum = os.path.join(self.tmp.name, "durum")
        dev = os.path.join(self.tmp.name, "Dev")
        for p in ("blog", "kasa"):
            os.makedirs(os.path.join(dev, p))
        self.cfg = {"vault_ofis": self.vault, "ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"},
                    "projects": {"blog": {"path": os.path.join(dev, "blog")},
                                 "kasa": {"path": os.path.join(dev, "kasa")}}}
        self.ceo = FakeCeo()
        self.now = at(12, 8, 31)
        self.oneriler = ["Disk %93 dolu (karar Selin'in)."]

    def tearDown(self):
        self.tmp.cleanup()

    def note(self, folder, name, **meta):
        fakes.write_note(os.path.join(self.vault, "Isler", folder), name, meta, "## Hedef\n\nx\n")

    def jobs_of_yesterday(self):
        self.note("Bitenler", "2026-11-11-090000-blog.md", proje="blog", durum="bitti", baslik="Giriş hatası",
                  bitis="2026-11-11T10:00:00", kontrol_sonuc="gecti", kontrol_deneme="1", harcanan_usd="0.41",
                  harcanan_token="182000", katman="kod")
        records.update(self.durum, "2026-11-11-090000-blog.md", {"kontrol_sonuc": "gecti", "kontrol_deneme": 1})
        self.note("Bitenler", "2026-11-11-110000-kasa.md", proje="kasa", durum="tikandi", baslik="CSV [[sahte]]",
                  bitis="2026-11-11T12:00:00", kontrol_sonuc="kaldi", harcanan_usd="0.20")
        self.note("Bitenler", "2026-11-10-090000-kasa.md", proje="kasa", durum="bitti", baslik="Eski",
                  bitis="2026-11-10T10:00:00")
        self.note("Siradakiler", "2026-11-12-070000-blog.md", proje="blog", durum="sirada", baslik="Profil")
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-11-blog-soru.md",
                         {"proje": "blog", "durum": "bekliyor", "soruldu": "2026-11-11T15:00"}, "# Renk?\n\n## Soru\n\nRenk?\n")

    def make(self, now=None, cfg=None):
        return ozet.SabahOzeti(lambda: cfg or self.cfg, self.durum, self.ceo, now=lambda: now or self.now,
                               oneriler=lambda: list(self.oneriler))


class ScheduleTest(Base):
    def test_the_time_comes_from_ofis_json_with_a_default(self):
        self.assertEqual(ozet.saat(self.cfg), (8, 30))
        self.assertEqual(ozet.saat({"sabah_ozeti": "07:15"}), (7, 15))
        for bad in ("25:00", "8.30", 830, None, ""):
            self.assertEqual(ozet.saat({"sabah_ozeti": bad}), (8, 30))

    def test_the_latest_slot(self):
        self.assertEqual(ozet.son_slot((8, 30), at(12, 8, 31)), at(12, 8, 30))
        self.assertEqual(ozet.son_slot((8, 30), at(12, 8, 29)), at(11, 8, 30))

    def test_written_once_at_its_time_and_never_twice_for_a_day(self):
        self.jobs_of_yesterday()
        gun = self.make().kontrol()
        self.assertEqual(gun, "2026-11-12")
        path = os.path.join(self.vault, "Ozetler", "2026-11-12.md")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(len(self.ceo.sent), 1)
        self.assertIsNone(self.make(now=at(12, 9)).kontrol())
        self.assertIsNone(self.make(now=at(12, 23, 59)).kontrol())
        self.assertEqual(len(self.ceo.sent), 1)
        with open(os.path.join(self.durum, "ozet", "son.json")) as f:
            self.assertIn("2026-11-12", json.load(f)["gunler"])
        os.remove(os.path.join(self.durum, "ozet", "son.json"))  # the state lost: the note itself still says done
        self.assertIsNone(self.make(now=at(12, 10)).kontrol())

    def test_a_missed_summary_is_caught_up_once_within_24_hours(self):
        # the server was off at 08:30 yesterday and starts today at 08:00: yesterday's summary, once
        self.assertEqual(self.make(now=at(12, 8, 0)).kontrol(), "2026-11-11")
        self.assertIsNone(self.make(now=at(12, 8, 10)).kontrol())
        self.assertEqual(self.make(now=at(12, 8, 31)).kontrol(), "2026-11-12")  # today's at its own time
        self.assertEqual([k for _, k in self.ceo.sent], ["sabah-ozeti-2026-11-11", "sabah-ozeti-2026-11-12"])
        # off for more than a day: the day before yesterday's slot is never caught up
        self.assertEqual(ozet.son_slot((8, 30), at(14, 8, 0)), at(13, 8, 30))


class TextTest(Base):
    def test_the_note_and_the_notice(self):
        self.jobs_of_yesterday()
        self.make().kontrol()
        with open(os.path.join(self.vault, "Ozetler", "2026-11-12.md"), encoding="utf-8") as f:
            text = f.read()
        for need in ("tur: sabah-ozeti", "# Sabah özeti — 12 Kasım 2026", "## Dün biten işler",
                     "[[2026-11-11-090000-blog]]", "Giriş hatası", "Kontrol geçti", "182 bin token · API karşılığı ~$0.41",
                     "## Bekleyen kararlar", "[[2026-11-11-blog-soru]]", "## Takılan ya da durdurulan işler",
                     "[[2026-11-11-110000-kasa]]", "## Bugün sırada", "[[2026-11-12-070000-blog]]",
                     "## Projeler", "- blog:", "- kasa:", "## Dünkü toplam kullanım", "## Sunucu odası",
                     "Disk %93 dolu"):
            self.assertIn(need, text)
        self.assertNotIn("Eski", text)  # finished the day before yesterday
        self.assertNotIn("[[sahte]]", text)
        [(notice, key)] = self.ceo.sent
        self.assertEqual(key, "sabah-ozeti-2026-11-12")
        self.assertTrue(notice.startswith("[Ofis · sistem]\nSabah özeti hazır: [[2026-11-12]]"))
        lines = [ln for ln in notice.splitlines()[2:] if ln.startswith("- ")]
        self.assertTrue(3 <= len(lines) <= 5, notice)
        self.assertIn("Dün biten: 2 iş", notice)
        self.assertIn("Bekleyen karar: 1", notice)

    def test_the_note_starts_with_a_short_summary_table(self):
        # The owner, 2026-11-13: easier to read — the numbers first, then the sections
        self.jobs_of_yesterday()
        self.make().kontrol()
        with open(os.path.join(self.vault, "Ozetler", "2026-11-12.md"), encoding="utf-8") as f:
            text = f.read()
        head = text.split("## Dün biten işler")[0]
        self.assertIn("## Kısaca\n\n| Konu | Durum |\n|---|---|\n", head)
        rows = [ln for ln in head.splitlines() if ln.startswith("| ") and not ln.startswith("| Konu")]
        labels = [ln.split(" | ")[0][2:] for ln in rows]
        self.assertEqual(labels, ["Dün biten", "Kontrol geçen", "Dünkü kullanım", "Bekleyen karar", "Takılan",
                                  "Bugün sırada", "Sunucu odası"])
        self.assertIn("| Dün biten | 2 iş |", head)
        self.assertIn("| Bekleyen karar | 1 |", head)
        self.assertRegex(head, r"\| Dünkü kullanım \| .*API karşılığı ~\$[\d.]+.* · \d+ iş \|")
        for ln in rows:
            self.assertEqual(ln.count("|"), 3, ln)  # a value never breaks the table
        self.assertLess(text.index("## Kısaca"), text.index("## Dün biten işler"))

    def test_the_summary_table_escapes_a_pipe(self):
        v = {"biten": [], "kararlar": [], "takilan": [], "sirada": [], "zamanlanmis": [], "projeler": [],
             "harcama": None, "oneriler": ["a | b"], "domain": []}
        text = ozet.metin("2026-11-12", v)
        self.assertIn("| Dünkü kullanım | kayıt yok |", text)
        self.assertIn("| Sunucu odası | 1 öneri, 0 domain sorunu |", text)

    def test_the_proof_comes_from_the_server_record_and_a_failed_launch_is_listed_once(self):
        # review MAJOR: a session can edit its note; the record decides. review MINOR: basarisiz counted twice
        self.note("Bitenler", "2026-11-11-100000-kasa.md", proje="kasa", durum="bitti", baslik="Sahte kanıt",
                  bitis="2026-11-11T11:00:00", kontrol_sonuc="gecti", kontrol_deneme="1")
        records.update(self.durum, "2026-11-11-100000-kasa.md", {"kontrol_sonuc": "yok"})
        self.note("Bitenler", "2026-11-11-120000-kasa.md", proje="kasa", durum="bitti", baslik="Kayıtsız",
                  bitis="2026-11-11T12:00:00", kontrol_sonuc="gecti")
        self.note("Bitenler", "2026-11-11-130000-kasa.md", proje="kasa", durum="basarisiz", baslik="Başlamadı",
                  bitis="2026-11-11T13:00:00")
        v = self.make().veri(self.cfg, "2026-11-12")
        text = ozet.metin("2026-11-12", v)
        line = lambda n: next(ln for ln in text.splitlines() if n in ln and "Dün" not in ln)  # noqa: E731
        self.assertIn("kontrol yok", line("Sahte kanıt"))
        self.assertIn("kontrol bilinmiyor", line("Kayıtsız"))
        self.assertEqual([t["note"] for t in v["biten"]].count("2026-11-11-130000-kasa.md"), 1)
        self.assertIn("Kontrol geçen 0", ozet.bildirim("2026-11-12", v))
        # a job that never started is named in the notice, not hidden in one count (owner decision 2026-11-15)
        self.assertIn("(başlatılamayan 1: Başlamadı)", ozet.bildirim("2026-11-12", v))

    def test_a_note_written_without_its_notice_is_told_on_the_next_pass(self):
        # review MINOR: the process died between the note and the notice
        self.make().kontrol()
        os.remove(os.path.join(self.durum, "ozet", "son.json"))
        self.ceo.sent.clear()
        self.assertIsNone(self.make(now=at(12, 9)).kontrol())
        self.assertEqual([k for _, k in self.ceo.sent], ["sabah-ozeti-2026-11-12"])
        self.assertIsNone(self.make(now=at(12, 9, 1)).kontrol())
        self.assertEqual(len(self.ceo.sent), 1)

    def test_questions_handed_back_to_deniz_are_listed_separately(self):
        v = self.make().veri(self.cfg, "2026-11-12")
        self.assertEqual(v["mudur_deniz"], [])
        text = ozet.metin("2026-11-12", v)
        self.assertIn("## Dün müdürlerin Selin'e bıraktığı sorular\n\nDün müdürün Selin'e bıraktığı soru yok.", text)
        self.assertNotIn("Selin'e bıraktığı:", ozet.bildirim("2026-11-12", v))
        v["mudur_deniz"] = [{"note": "2026-11-11-kasa-soru-1a2b3c4d.md", "proje": "kasa", "unvan": "QA Müdürü",
                             "neden": "QA Müdürü cevap veremedi (zaman aşımı, 180 sn)", "acik": False}]
        text = ozet.metin("2026-11-12", v)
        self.assertIn("- [[2026-11-11-kasa-soru-1a2b3c4d]] — QA Müdürü cevap veremedi (zaman aşımı, 180 sn) · kasa\n",
                      text)
        self.assertIn("- Bekleyen karar: 0 · müdürün Selin'e bıraktığı: 1", ozet.bildirim("2026-11-12", v))

    def test_model_and_project_text_is_inert(self):
        # review finding: the manager's reason, titles and other model / project text never render as HTML, a link or
        # an embed in Obsidian
        bad = "<img src=http://x> ![](http://x) [[x]] [a](http://x) `kod`\nikinci satır"
        v = self.make().veri(self.cfg, "2026-11-12")
        v["mudur_deniz"] = [{"note": "2026-11-11-kasa-soru-1a2b3c4d.md", "proje": "kasa", "unvan": "QA Müdürü",
                             "neden": "QA Müdürü Selin'e bıraktı: " + bad, "acik": True}]
        v["mudur"] = [{"note": "2026-11-11-kasa-soru-1a2b3c4e.md", "proje": bad, "unvan": bad, "degisti": False}]
        v["kararlar"] = [{"note": bad, "title": bad, "project": "kasa"}]
        v["oneriler"] = [bad]
        text = ozet.metin("2026-11-12", v)
        for payload in ("<img", "](http", "[[x]]", "[a]", "`", "\nikinci"):
            self.assertNotIn(payload, text, payload)
        self.assertIn("&lt;img src=http://x&gt;", text)
        self.assertIn("'kod' ikinci satır", text)  # newlines collapsed into one line
        self.assertIn("[[2026-11-11-kasa-soru-1a2b3c4d]]", text)  # the office's own links stay links

    def test_deterministic_text(self):
        self.jobs_of_yesterday()
        s = self.make()
        cfg = self.cfg
        a = ozet.metin("2026-11-12", s.veri(cfg, "2026-11-12"))
        b = ozet.metin("2026-11-12", s.veri(cfg, "2026-11-12"))
        self.assertEqual(a, b)

    def test_a_vault_write_failure_sends_no_notice(self):
        os.makedirs(os.path.dirname(self.vault), exist_ok=True)
        with open(self.vault, "w") as f:
            f.write("x")  # a file where the OFIS folder should be
        self.assertIsNone(self.make().kontrol())
        self.assertEqual(self.ceo.sent, [])


if __name__ == "__main__":
    unittest.main()
