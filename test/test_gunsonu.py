"""Tests for bin/gunsonu.py: the end-of-day review team (owner decision 2026-11-13) — the evening window, the measurement, the
review job on a bad day only, the note OFIS/GunSonu/GunSonu-YYYY-MM-DD.md, its two CEO notices and the readers."""
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
import gunsonu  # noqa: E402
import jobs  # noqa: E402
import karne  # noqa: E402
import kontrol  # noqa: E402
import launch  # noqa: E402
import mudur  # noqa: E402
import ofis  # noqa: E402
import olaylar  # noqa: E402
import ozet  # noqa: E402
import records  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")


def at(day, hh, mm=0, ss=0):
    return datetime(2026, 11, day, hh, mm, ss, tzinfo=TZ)


class FakeCeo:
    def __init__(self):
        self.sent = []

    def enqueue(self, text, key):
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class FakeOlaylar:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def donem(self, bas, son):
        self.calls.append((bas, son))
        return [r for r in self.rows if bas <= r["son"] < son]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.vault = os.path.join(base, "vault", "OFIS")
        self.durum = os.path.join(base, "durum")
        dev = os.path.join(base, "Dev")
        for p in ("blog", "kasa", "ofis-arge"):
            os.makedirs(os.path.join(dev, p))
        os.makedirs(self.vault)
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault, "default_budget_usd": 3,
                    "ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"},
                    "projects": {"blog": {"path": os.path.join(dev, "blog")},
                                 "kasa": {"path": os.path.join(dev, "kasa")},
                                 "arge": {"path": os.path.join(dev, "ofis-arge"), "description": "Ar-Ge"}},
                    "tiers": {"genel": {"model": "sonnet", "effort": "medium", "butce_usd": 1.5},
                              "kod": {"model": "opus", "effort": "high"}},
                    "max_running": 3, "max_running_per_project": 1, "max_queued_per_project": 5,
                    "gun_sonu": {"acik": True, "baslangic": "20:00", "bitis": "24:00", "butce_usd": 0.5}}
        self.ceo = FakeCeo()
        self.now = at(13, 20, 5)
        self.olaylar = FakeOlaylar()
        self.added = []

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **kw):
        """The real path of `ekle` (ofis.add_job), recording the call."""
        self.added.append(kw)
        try:
            return ofis.add_job(self.cfg, self.durum, kw.pop("project"), kw.pop("title"), kw.pop("brief"),
                                kw.pop("now"), **kw)
        except ofis.Refused as e:
            raise launch.Refused(str(e)) from None

    def make(self, add=True):
        return gunsonu.GunSonu(lambda: self.cfg, self.durum, self.ceo, add=self.add if add else None,
                               now=lambda: self.now, olaylar=self.olaylar)

    def note(self, folder, name, rec=None, **meta):
        fakes.write_note(os.path.join(self.vault, "Isler", folder), name, meta, "## Görev\n\nx\n")
        if rec is not None:
            records.update(self.durum, name, rec)

    def good_day(self):
        self.note("Bitenler", "2026-11-13-090000-blog.md", proje="blog", durum="bitti", baslik="Giriş",
                  baslangic="2026-11-13T09:00:00", bitis="2026-11-13T10:00:00", harcanan_usd="0.40",
                  harcanan_token="150000",
                  rec={"proje": "blog", "katman": "kod", "model": "opus", "uzmanlik": "backend",
                       "kontrol_sonuc": "gecti", "kontrol_deneme": 1})
        self.note("Bitenler", "2026-11-12-090000-kasa.md", proje="kasa", durum="bitti", baslik="Eski",
                  baslangic="2026-11-12T09:00:00", bitis="2026-11-12T10:00:00", harcanan_usd="9")

    def bad_day(self):
        self.good_day()
        self.note("Bitenler", "2026-11-13-110000-kasa.md", proje="kasa", durum="tikandi", baslik="CSV [[sahte]] <img>",
                  baslangic="2026-11-13T11:00:00", bitis="2026-11-13T12:00:00", harcanan_usd="0.20",
                  rec={"proje": "kasa", "katman": "kod", "model": "opus", "kontrol_sonuc": "kaldi",
                       "kontrol_deneme": 2})
        for i, t in enumerate((at(13, 11, 30), at(13, 11, 50))):
            karne.record_correction(self.vault, "kasa", "2026-11-13-110000-kasa.md", "kontrol-basarisiz",
                                    "çıkış 1: hata", f"k-{i}", t.replace(tzinfo=None))
        self.note("Bitenler", "2026-11-13-130000-blog.md", proje="blog", durum="tikandi", baslik="Büyük iş",
                  baslangic="2026-11-13T13:00:00", bitis="2026-11-13T14:00:00", durdurma_nedeni="butce",
                  harcanan_usd="6.10", harcanan_token="900000",
                  rec={"proje": "blog", "katman": "kod", "model": "opus"})

    def note_path(self, gun="2026-11-13"):
        return os.path.join(self.vault, "GunSonu", f"GunSonu-{gun}.md")

    def read_note(self, gun="2026-11-13"):
        with open(self.note_path(gun), encoding="utf-8") as f:
            return f.read()

    def state(self, gun="2026-11-13"):
        return gunsonu.gun_durumu(self.durum, gun)


class WindowTest(Base):
    def test_the_switch_and_the_window_from_ofis_json(self):
        self.assertEqual(gunsonu.ayar(self.cfg), {"bas": 1200, "bit": 1440, "butce": 0.5})
        for off in ({}, {"gun_sonu": {"acik": False}}, {"gun_sonu": {"acik": "evet"}}, {"gun_sonu": True}):
            self.assertIsNone(gunsonu.ayar(off))
        self.assertEqual(gunsonu.ayar({"gun_sonu": {"acik": True}}), {"bas": 1200, "bit": 1440, "butce": 0.5})
        self.assertEqual(gunsonu.ayar({"gun_sonu": {"acik": True, "baslangic": "21:30", "bitis": "23:00",
                                                    "butce_usd": 0.8}}), {"bas": 1290, "bit": 1380, "butce": 0.8})
        for bad in ({"baslangic": "23:00", "bitis": "22:00"}, {"baslangic": "24:00"}, {"bitis": "25:00"},
                    {"butce_usd": -1}, {"butce_usd": 99}, {"butce_usd": "x"}):
            a = gunsonu.ayar({"gun_sonu": {"acik": True, **bad}})
            self.assertEqual((a["bas"], a["bit"]) if "butce_usd" not in bad else a["butce"],
                             (1200, 1440) if "butce_usd" not in bad else 0.5, bad)

    def test_before_the_window_nothing_happens(self):
        self.now = at(13, 19, 59, 59)
        self.assertIsNone(self.make().kontrol())
        self.assertIsNone(self.state())
        self.assertFalse(os.path.exists(self.note_path()))
        self.assertEqual(self.ceo.sent, [])

    def test_the_first_pass_inside_runs_once_and_a_restart_does_not_run_again(self):
        self.good_day()
        self.assertEqual(self.make().kontrol(), "2026-11-13")
        self.assertTrue(os.path.isfile(self.note_path()))
        self.assertEqual(len(self.ceo.sent), 1)
        self.now = at(13, 22, 0)
        self.assertIsNone(self.make().kontrol())  # a restart inside the window: a new object, the state decides
        self.assertIsNone(self.make().kontrol())
        self.assertEqual(len(self.ceo.sent), 1)
        self.assertEqual(self.state()["son"], "2026-11-13 20:05:00")

    def test_a_missed_window_is_recorded_as_skipped_and_shown_by_the_next_run(self):
        self.now = at(12, 10, 0)  # the feature's first day: the 12th
        self.make().kontrol()
        self.now = at(14, 8, 0)  # the server was off the whole evening of the 12th and of the 13th
        self.make().kontrol()
        self.assertEqual(self.state("2026-11-12")["durum"], "atlandi")
        self.assertEqual(self.state("2026-11-13")["durum"], "atlandi")
        self.assertIsNone(self.state("2026-11-11"))  # before the first day: never "skipped"
        self.assertEqual(gunsonu.dunku(self.durum, "2026-11-13"), {"atlandi": True})
        self.now = at(14, 21, 0)
        self.make().kontrol()
        st = self.state("2026-11-14")
        self.assertEqual(st["atlananlar"], ["2026-11-12", "2026-11-13"])
        self.assertIn("Atlanan günler: 12 Kasım 2026, 13 Kasım 2026", self.read_note("2026-11-14"))
        self.assertIn("Atlanan gün: 12 Kasım 2026, 13 Kasım 2026", self.ceo.sent[-1][0])
        self.assertEqual(st["bas"], "2026-11-12 00:00:00")  # no earlier run: from the first skipped day

    def test_the_midnight_boundary(self):
        self.now = at(13, 23, 59, 59)
        self.assertEqual(self.make().kontrol(), "2026-11-13")
        self.now = at(14, 0, 0, 1)
        self.assertIsNone(self.make().kontrol())  # the 14th's window has not opened; the 13th is done
        self.assertEqual(self.state("2026-11-13")["durum"], "olculdu")
        self.assertIsNone(self.state("2026-11-14"))
        self.now = at(14, 20, 0)
        self.make().kontrol()
        st = self.state("2026-11-14")
        self.assertEqual((st["bas"], st["atlananlar"]), ("2026-11-13 23:59:59", []))  # from the last run on

    def test_a_window_that_ends_before_midnight_skips_after_its_end(self):
        self.cfg["gun_sonu"]["bitis"] = "22:00"
        self.now = at(13, 9, 0)
        self.make().kontrol()
        self.now = at(13, 22, 0)
        self.assertIsNone(self.make().kontrol())
        self.assertEqual(self.state()["durum"], "atlandi")

    def test_a_half_measurement_after_a_crash_is_measured_again_inside_the_window(self):
        gunsonu._kaydet(self.durum, {"gun": "2026-11-13", "durum": "olculuyor"})
        self.assertEqual(self.make().kontrol(), "2026-11-13")
        self.assertEqual(self.state()["durum"], "olculdu")

    def test_switched_off_nothing_happens_at_all(self):
        self.cfg["gun_sonu"]["acik"] = False
        self.bad_day()
        self.assertIsNone(self.make().kontrol())
        self.assertFalse(os.path.exists(os.path.join(self.durum, "gunsonu")))
        self.assertFalse(os.path.exists(os.path.join(self.vault, "GunSonu")))
        self.assertEqual((self.ceo.sent, self.added), ([], []))
        del self.cfg["gun_sonu"]
        self.assertIsNone(self.make().kontrol())


class MeasurementTest(Base):
    def measure(self, bas="2026-11-13 00:00:00", son="2026-11-13 20:05:00"):
        return gunsonu.olc(self.cfg, self.durum, self.vault, bas, son, olaylar=self.olaylar)

    def test_the_numbers_from_fixture_jobs(self):
        self.bad_day()
        self.note("Bitenler", "2026-11-13-150000-kasa.md", proje="kasa", durum="bitti", baslik="Deneme",
                  baslangic="2026-11-13T15:00:00", bitis="2026-11-13T15:10:00", harcanan_usd="1",
                  rec={"proje": "kasa", "deneme": "evet", "kontrol_sonuc": "kaldi", "kontrol_deneme": 3})
        self.note("Devam-Edenler", "2026-11-13-160000-blog.md", proje="blog", durum="calisiyor", baslik="Açık",
                  baslangic="2026-11-13T16:00:00",
                  rec={"proje": "blog", "katman": "genel", "model": "sonnet",
                       "kota_devam": {"sayi": 1, "zamanlar": ["2026-11-13T16:30:00", "2026-11-12T10:00:00"]},
                       "kota_yedegi": {"asil": "opus", "yedek": "sonnet"}})
        karne.record_correction(self.vault, "blog", "2026-11-13-160000-blog.md", "devam", "devam", "d-1",
                                datetime(2026, 11, 13, 17, 0))
        karne.record_correction(self.vault, "blog", "2026-11-13-160000-blog.md", "inceleme-duzelt", "x", "i-1",
                                datetime(2026, 11, 13, 17, 5))
        karne.record_correction(self.vault, "blog", "2026-11-13-160000-blog.md", "yukseltme", "x", "y-1",
                                datetime(2026, 11, 12, 17, 5))  # outside the period
        o = self.measure()
        s = o["sayilar"]
        self.assertEqual((s["bitti"], s["tikandi"], s["basarisiz"], s["acik"]), (1, 2, 0, 1))
        self.assertEqual((s["kontrol"], s["kontrol_ilk"], s["kontrol_iki_kez"]), (2, 1, 1))
        self.assertEqual((s["devam"], s["inceleme_duzelt"], s["yukseltme"]), (1, 1, 0))
        self.assertEqual((s["butce"], s["cagri"], s["kota_devam"], s["kota_yedek"]), (1, 0, 1, 1))
        self.assertEqual((round(s["usd"], 2), s["token"], s["harcama_is"]), (6.7, 1050000, 3))
        self.assertEqual(s["deneme"], 1)  # counted apart, never in the numbers
        self.assertNotIn("2026-11-12-090000-kasa.md", [r["is"] for r in o["isler"]])
        kinds = sorted((k["tur"], k.get("is")) for k in o["kotu"])
        self.assertEqual(kinds, [("butce", "2026-11-13-130000-blog.md"), ("kontrol-iki-kez", "2026-11-13-110000-kasa.md"),
                                 ("tikandi", "2026-11-13-110000-kasa.md")])
        row = next(r for r in o["isler"] if r["is"] == "2026-11-13-090000-blog.md")
        self.assertEqual((row["kim"], row["ilk_tur"]), ("Kıdemli Backend (opus)", "evet"))

    def test_reviewer_noise_manager_overrides_and_server_errors(self):
        import denetci
        denetci.save_round(self.durum, "2026-11-13-100000-kasa.md", {
            "is": "2026-11-13-100000-kasa.md", "bitis": "2026-11-13T10:30:00",
            "denetciler": [{"ad": "codex", "ciddi": 3, "gecerli": 2}, {"ad": "glm", "ciddi": 2, "gecerli": 0}],
            "hakem": {"durum": "tamam", "gecerli": 2, "gecersiz": 3},
            "reddedilen": [{"satir": "x", "denetci": "glm", "neden": "y"}]})
        denetci.save_round(self.durum, "2026-11-12-100000-kasa.md", {
            "is": "2026-11-12-100000-kasa.md", "bitis": "2026-11-12T10:30:00",
            "denetciler": [{"ad": "codex", "ciddi": 9, "gecerli": 9}]})
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-13-blog-soru.md",
                         {"proje": "blog", "durum": "cevaplandi", "karar_veren": "deniz"}, "# Soru\n")
        mudur.save(self.durum, {"mesaj": "1763035200000000001-ab12cd34", "durum": "cevapladi", "bitis": "2026-11-13T12:00:00",
                                "karar": "2026-11-13-blog-soru.md", "proje": "blog", "mudur": "yazilim"})
        mudur.save(self.durum, {"mesaj": "1763038800000000001-ab12cd35", "durum": "deniz", "bitis": "2026-11-13T13:00:00",
                                "karar": "2026-11-13-kasa-soru.md", "proje": "kasa", "mudur": "qa",
                                "neden_sonuc": "müdür Deniz'e bıraktı"})  # old protocol: a record written before the neutral wording
        self.olaylar.rows = [{"tur": "hata", "ileti": "kontrol failed: OSError", "sayi": 4, "son": "2026-11-13 19:40"},
                             {"tur": "teslim", "ileti": "unconfirmed", "sayi": 1, "son": "2026-11-13 09:00"},
                             {"tur": "hata", "ileti": "old", "sayi": 1, "son": "2026-11-12 09:00"}]
        o = self.measure()
        d = o["denetci"]
        self.assertEqual((d["tur"], d["ciddi"], d["gecerli"], d["reddedilen"], d["hakem_gecersiz"]), (1, 5, 2, 1, 3))
        self.assertEqual([x["ad"] for x in d["denetciler"]], ["codex", "glm"])
        m = o["mudur"]
        self.assertEqual((m["cevap"], m["degisti"], m["denize"]), (1, 1, 1))
        self.assertEqual([h["ileti"] for h in o["hatalar"]], ["kontrol failed: OSError", "unconfirmed"])
        self.assertEqual(self.olaylar.calls, [("2026-11-13 00:00", "2026-11-13 20:05")])
        kinds = sorted(k["tur"] for k in o["kotu"])
        self.assertEqual(kinds, ["mudur-degisti", "sunucu-hatasi"])  # the delivery warning alone is no bad case

    def test_a_failed_launch_shows_its_reason_and_is_not_counted_twice(self):
        # gün sonu 2026-11-15: "başlatılamadı" without a reason, and the same job again as a server error
        fakes.write_note(os.path.join(self.vault, "Isler", "Bitenler"), "2026-11-13-115457-kasa.md",
                         {"proje": "kasa", "durum": "basarisiz", "baslik": "Alıştırma", "bitis": "2026-11-13T11:57:00"},
                         "## Görev\n\nx\n\n## Sonuç\n\nBaşlatma başarısız: claude did not print the expected launch line "
                         "(exit 1)\n\n```\nWorkspace not trusted. Run `claude` once.\n\n```\n")
        self.olaylar.rows = [{"tur": "hata", "ileti": "advisor pilot p: 2026-11-13-115457-kasa.md failed to launch; "
                                                     "slot freed", "sayi": 1, "son": "2026-11-13 11:57"},
                             {"tur": "hata", "ileti": "kontrol failed: OSError", "sayi": 1, "son": "2026-11-13 12:00"}]
        o = self.measure()
        bad = [k for k in o["kotu"] if k["tur"] == "basarisiz"]
        self.assertEqual(bad[0]["neden"], "Workspace not trusted. Run claude once.")
        self.assertEqual([k["baslik"] for k in o["kotu"] if k["tur"] == "sunucu-hatasi"], ["kontrol failed: OSError"])
        self.assertIn("— neden: Workspace not trusted. Run claude once.", gunsonu._kotu_satiri(bad[0]))

    def test_background_lines_are_errors_only_when_they_say_so(self):
        self.assertEqual(olaylar.kind_of_background_line("ofis: gün sonu ölçümü 2026-11-15: 16 iş, 8 kötü durum"),
                         "bilgi")
        self.assertEqual(olaylar.kind_of_background_line("ofis: gün sonu notu yazılamadı (x): OSError"), "hata")
        self.assertEqual(olaylar.kind_of_background_line("ofis: sabah özeti hatası: X"), "hata")
        self.assertEqual(olaylar.kind_of_background_line("ofis: yakalanan a için iş eklenemedi: q"), "hata")

    def test_the_real_error_record_by_period(self):
        ev = olaylar.Olaylar(self.vault, now=lambda: datetime(2026, 11, 13, 19, 0))
        ev.record("başlangıç", "sunucu başladı")
        ev.record("hata", "dispatcher: OSError")
        os.makedirs(os.path.join(self.vault, "Sunucu"), exist_ok=True)
        with open(os.path.join(self.vault, "Sunucu", "Hatalar-2026-10.md"), "w", encoding="utf-8") as f:
            f.write("| 2026-10-31 23:50 | 2026-10-31 23:55 | 2 | hata | ekim hatası |\n")
        rows = ev.donem("2026-10-31 12:00", "2026-11-13 20:00")
        self.assertEqual([r["ileti"] for r in rows], ["dispatcher: OSError", "ekim hatası"])
        self.assertEqual(ev.donem("2026-11-13 19:01", "2026-11-13 20:00"), [])

    def test_error_rows_at_the_period_bounds_count_once_on_minutes(self):
        # the rows carry minutes only: a row counts when floor(bas) <= its minute < floor(son); consecutive periods
        # (one's son is the next one's bas) share no minute and leave none out
        os.makedirs(os.path.join(self.vault, "Sunucu"))
        rows = [("19:59", "before bas"), ("20:00", "at bas"), ("20:04", "just before son"), ("20:05", "at son")]
        with open(os.path.join(self.vault, "Sunucu", "Hatalar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("".join(f"| 2026-11-13 {m} | 2026-11-13 {m} | 1 | hata | {t} |\n" for m, t in rows))
        ev = olaylar.Olaylar(self.vault)
        bas, son = "2026-11-13 20:00:30", "2026-11-13 20:05:10"  # seconds inside the bound minutes
        got = [h["ileti"] for h in gunsonu._hatalar(ev, bas, son)]
        self.assertEqual(got, ["just before son", "at bas"])
        prev = [h["ileti"] for h in gunsonu._hatalar(ev, "2026-11-13 19:00:00", bas)]
        nxt = [h["ileti"] for h in gunsonu._hatalar(ev, son, "2026-11-13 21:00:00")]
        self.assertEqual((prev, nxt), (["before bas"], ["at son"]))
        self.assertEqual(sorted(prev + got + nxt), sorted(t for _, t in rows))  # each row in exactly one period


class ReviewJobTest(Base):
    def test_a_bad_day_adds_one_job_with_the_exact_brief_and_budget(self):
        self.bad_day()
        self.make().kontrol()
        [call] = self.added
        self.assertEqual((call["tier"], call["budget"], call["extra"], call["uzmanlik"]),
                         ("genel", 0.5, {"gun_sonu": "2026-11-13"}, "analiz"))
        st = self.state()
        name = st["is"]
        job = jobs.load(self.vault, name)
        rec = records.load(self.durum, name)
        self.assertEqual((job.meta["proje"], rec["proje"], rec["katman"], rec["model"], rec["gun_sonu"]),
                         ("arge", "arge", "genel", "sonnet", "2026-11-13"))
        self.assertEqual(float(rec["butce_usd"]), 0.5)
        self.assertEqual(rec["deneme"], "")  # real work, not a self-test
        self.assertEqual(job.meta["baslik"], "Gün sonu değerlendirmesi — 13 Kasım 2026")
        self.assertIsNone(kontrol.load(self.durum, name))  # a read-only report: no Kontrol
        text = job.body  # the brief as the session gets it (## Görev)
        for need in ("## Kök nedenler", "## Kod düzeltmeleri", "## Kural önerileri", "ÖNERİ-KOD:",
                     "ÖNERİ-CLAUDE-MD:", "ÖNERİ-REVIEW-MD:", "GunSonu/GunSonu-2026-11-13.md",
                     "Isler/Bitenler/2026-11-13-110000-kasa.md", "Isler/Bitenler/2026-11-13-130000-blog.md",
                     "Karne/Duzeltmeler-kasa.md", "Proje kod klasörleri ve kasanın kökü açılmaz"):
            self.assertIn(need, text)
        self.assertNotIn("2026-11-13-090000-blog.md", text)  # only the bad jobs' notes
        self.assertLess(len(jobs.section(job.body, "Görev")), launch.MAX_TASK)
        self.assertIsNotNone(kontrol.load_brief(self.durum, name))  # the trusted brief is stored like any ekle
        note = self.read_note()
        self.assertIn(f"[[{name[:-3]}]] (Uzman · kullanım sınırı API karşılığı ~$0.50)", note)
        [(notice, key)] = self.ceo.sent
        self.assertEqual(key, "gunsonu-2026-11-13")
        self.assertIn("Gün sonu değerlendirmesi hazır: [[GunSonu-2026-11-13]]", notice)
        self.assertIn(f"Kötü giden: 3 → değerlendirme işi [[{name[:-3]}]] eklendi (Uzman, kullanım sınırı API karşılığı ~$0.50)", notice)
        self.make().kontrol()
        self.assertEqual(len(self.added), 1)

    def test_a_good_day_adds_no_job_and_says_so(self):
        self.good_day()
        self.make().kontrol()
        self.assertEqual(self.added, [])
        note = self.read_note()
        self.assertIn("## Kötü gidenler\n\nBugün kötü giden bir şey yok.", note)
        self.assertIn("değerlendirme işi eklenmedi", note)
        self.assertIn("Bugün kötü giden bir şey yok; değerlendirme işi eklenmedi.", self.ceo.sent[0][0])

    def test_a_refused_add_is_written_and_retried_in_the_window(self):
        self.bad_day()
        for i in range(5):  # the arge queue is full
            jobs.create(self.vault, "arge", f"Sırada {i}", brief={"hedef": "x"}, now=datetime(2026, 11, 13, 8, i))
        self.make().kontrol()
        st = self.state()
        self.assertEqual(st["is"], "")
        self.assertIn("Sıradakiler dolu", st["is_hatasi"])
        self.assertIn("Değerlendirme işi eklenemedi", self.read_note())
        self.assertIn("eklenemedi", self.ceo.sent[0][0])
        self.now = at(13, 20, 10)
        self.make().kontrol()
        self.assertEqual(len(self.added), 1)  # not every pass: every RETRY_DK minutes
        for j in jobs.list_jobs(self.vault):
            if j.meta.get("proje") == "arge":
                jobs.update(self.vault, j.name, status="iptal")
        self.now = at(13, 20, 16)
        self.make().kontrol()
        self.assertTrue(self.state()["is"])
        self.assertEqual(len(self.ceo.sent), 1)  # the first notice is not repeated
        self.assertIn(f"[[{self.state()['is'][:-3]}]]", self.read_note())

    def test_a_crash_after_the_add_adopts_the_job_instead_of_adding_twice(self):
        self.bad_day()
        g = self.make()
        orig = gunsonu.GunSonu._is_ekle

        def crash(self_, cfg, vault, st, now):
            name, _ = self_.add(project="arge", title="x", brief={"hedef": "x"}, now=now.replace(tzinfo=None),
                                tier="genel", budget=0.5, extra={"gun_sonu": "2026-11-13"}, uzmanlik="analiz")
            st["ekleniyor"] = True
            gunsonu._kaydet(self_.durum_dir, st)
            raise KeyboardInterrupt
        gunsonu.GunSonu._is_ekle = crash
        try:
            with self.assertRaises(KeyboardInterrupt):
                g.kontrol()
        finally:
            gunsonu.GunSonu._is_ekle = orig
        self.make().kontrol()
        self.assertEqual(len(self.added), 1)
        name = self.state()["is"]
        self.assertTrue(name)
        self.assertEqual(records.load(self.durum, name)["gun_sonu"], "2026-11-13")


class ReportTest(Base):
    REPORT = ("## Kök nedenler\n- kasa CSV işinde test komutu yanlış klasörde [[sahte]] ![x](http://e/x.png)\n"
              "## Kod düzeltmeleri\nÖNERİ-KOD: kasa | test komutu `make test` olmalı\n"
              "- **Öneri-Kod:** bilinmez | x\n"
              "## Kural önerileri\nÖNERİ-CLAUDE-MD: kasa | Kontrol komutu kök klasörden çalışır.\n"
              "oneri-review-md: blog | Bütçe uyarısı incelensin.\n> [!warning] sahte\n")

    def finish(self, name, status="bitti", text=REPORT, proof="yok"):
        records.update(self.durum, name, {"kontrol_sonuc": proof})
        jobs.update(self.vault, name, status=status, fields={"bitis": "2026-11-13T21:00:00"})
        kontrol.save_report(self.durum, name, text)

    def test_the_suggestions_are_written_once_and_told_once(self):
        self.bad_day()
        self.make().kontrol()
        name = self.state()["is"]
        self.now = at(13, 20, 30)
        self.make().kontrol()  # still queued: nothing new
        self.assertEqual(len(self.ceo.sent), 1)
        self.finish(name)
        self.now = at(13, 21, 1)
        self.make().kontrol()
        self.make().kontrol()
        self.assertEqual([k for _, k in self.ceo.sent], ["gunsonu-2026-11-13", "gunsonu-oneri-2026-11-13"])
        notice = self.ceo.sent[1][0]
        self.assertIn("Gün sonu önerileri eklendi: [[GunSonu-2026-11-13]]", notice)
        self.assertIn("Kod düzeltmesi: 2 · CLAUDE.md satırı: 1 · REVIEW.md satırı: 1", notice)
        self.assertIn("iki kez", notice)
        note = self.read_note()
        self.assertIn("- Kod düzeltmesi · kasa: test komutu 'make test' olmalı", note)
        self.assertIn("- Kod düzeltmesi · bilinmez (bilinmeyen proje): x", note)
        self.assertIn("- CLAUDE.md satırı · kasa: Kontrol komutu kök klasörden çalışır.", note)
        self.assertIn("- REVIEW.md satırı · blog: Bütçe uyarısı incelensin.", note)
        self.assertNotIn("[[sahte]]", note)  # data never becomes a link, an embed, a tag or a callout
        self.assertNotIn("![x](", note)
        self.assertNotIn("> [!warning]", note)
        self.assertNotIn("<img>", note)
        self.assertIn("&lt;img&gt;", note)
        st = self.state()
        self.assertEqual(st["rapor"]["eksik_bolumler"], [])
        self.assertEqual(gunsonu.ozet_durumu(self.cfg, self.durum)["son"]["oneri"], 4)

    def test_office_suggestions_go_to_the_developer_inbox(self):
        # The owner, 2026-11-15: the office's own findings are written for the developer session, not turned into jobs
        self.bad_day()
        self.make().kontrol()
        inbox = os.path.join(self.vault, "Gelistirici", "Gelistirici-2026-11-13.md")
        with open(inbox, encoding="utf-8") as f:
            first = f.read()
        self.assertIn("[[GunSonu-2026-11-13]]", first)
        self.assertIn("## Kötü gidenler", first)
        self.assertIn("sırada ya da çalışıyor", first)
        self.assertIn("ofis", gunsonu.brief(self.cfg, "2026-11-13", [], 1)["hedef"])
        self.finish(self.state()["is"], text=self.REPORT + "\nÖNERİ-KOD: ofis | işi başlatmadan önce güven onayına bak\n"
                                                  "ÖNERİ-CLAUDE-MD: ajan-ofisi | <img> satırı\n")
        self.now = at(13, 21, 1)
        self.make().kontrol()
        with open(inbox, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("- Kod düzeltmesi: işi başlatmadan önce güven onayına bak", text)
        self.assertIn("&lt;img&gt;", text)
        self.assertIn("Projelerle ilgili 4 öneri CEO'ya gitti", text)
        notice = self.ceo.sent[-1][0]
        self.assertIn("Kod düzeltmesi: 2 · CLAUDE.md satırı: 1 · REVIEW.md satırı: 1", notice)  # ofis ones apart
        self.assertIn("Ofisin kendisiyle ilgili 2 öneri geliştiriciye gitti ([[Gelistirici-2026-11-13]])", notice)
        self.assertIn("ofis (geliştiriciye)", self.read_note())

    def test_a_job_that_ends_stuck_only_updates_the_note(self):
        self.bad_day()
        self.make().kontrol()
        self.finish(self.state()["is"], status="tikandi", text="takıldım")
        self.make().kontrol()
        self.assertEqual(len(self.ceo.sent), 1)
        self.assertIn("Değerlendirme işi tamamlanamadı (tikandi)", self.read_note())

    def test_a_report_without_the_sections_is_marked(self):
        self.bad_day()
        self.make().kontrol()
        self.finish(self.state()["is"], text="Kısa bir not.")
        self.make().kontrol()
        self.assertIn("Raporda eksik bölüm: Kök nedenler, Kod düzeltmeleri, Kural önerileri", self.read_note())
        self.assertIn("Raporda biçimli öneri satırı yok", self.read_note())

    def test_a_note_folder_that_is_a_link_is_never_written_through(self):
        self.good_day()
        other = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(other)
        os.symlink(other, os.path.join(self.vault, "GunSonu"))
        self.make().kontrol()
        self.assertEqual(os.listdir(other), [])
        self.assertEqual(self.ceo.sent, [])  # no notice for a note that is not there
        self.assertFalse(self.state()["yazildi"])


class ReadersTest(Base):
    def test_the_morning_summary_names_yesterdays_note(self):
        self.bad_day()
        self.make().kontrol()
        d = gunsonu.dunku(self.durum, "2026-11-13")
        self.assertEqual((d["not"], d["kotu"]), ("GunSonu-2026-11-13", 3))
        self.assertIsNone(gunsonu.dunku(self.durum, "2026-11-12"))
        line = ozet._gun_sonu_satiri(d)
        self.assertTrue(line.startswith("[[GunSonu-2026-11-13]] — kötü giden 3 durum · değerlendirme işi [["), line)
        self.assertIn("atlandı", ozet._gun_sonu_satiri({"atlandi": True}))
        s = ozet.SabahOzeti(lambda: self.cfg, self.durum, self.ceo, now=lambda: at(14, 8, 31))
        s.kontrol()
        with open(os.path.join(self.vault, "Ozetler", "2026-11-14.md"), encoding="utf-8") as f:
            self.assertIn("## Dünkü gün sonu değerlendirmesi\n\n[[GunSonu-2026-11-13]]", f.read())

    def test_the_state_summary_for_the_page(self):
        self.assertEqual(gunsonu.ozet_durumu(self.cfg, self.durum)["son"], None)
        self.now = at(12, 10)
        self.make().kontrol()
        self.now = at(14, 9)
        self.make().kontrol()
        self.bad_day()
        self.now = at(14, 20, 30)
        self.make().kontrol()
        o = gunsonu.ozet_durumu(self.cfg, self.durum)
        self.assertEqual((o["acik"], o["pencere"], o["aktif_dk"]), (True, "20:00–24:00", 10))
        self.assertEqual(o["atlananlar"], ["2026-11-12", "2026-11-13"])
        self.assertEqual((o["son"]["gun"], o["son"]["not"], o["son"]["kotu"]), ("2026-11-14", "GunSonu-2026-11-14", 3))
        self.assertEqual(o["son"]["olcum_zamani"], "2026-11-14 20:30:00")
        self.assertTrue(o["son"]["is"])
        self.assertTrue(gunsonu.is_mi(self.durum, o["son"]["is"]))
        self.assertFalse(gunsonu.is_mi(self.durum, "2026-11-13-090000-blog.md"))
        self.cfg["gun_sonu"]["acik"] = False
        self.assertFalse(gunsonu.ozet_durumu(self.cfg, self.durum)["acik"])

    def test_the_note_neutralises_titles_and_links_only_valid_names(self):
        self.bad_day()
        self.make().kontrol()
        note = self.read_note()
        self.assertIn("[[2026-11-13-110000-kasa]] CSV \\[\\[sahte\\]\\] &lt;img&gt;", note)
        self.assertIn("| Kontrol iki kez geçmeyen | 1 |", note)
        self.assertIn("| Kullanım sınırı / çağrı durdurma | 1 / 0 |", note)
        self.assertIn("## Kaynaklar", note)
        self.assertNotIn("[[sahte]]", note)


if __name__ == "__main__":
    unittest.main()
