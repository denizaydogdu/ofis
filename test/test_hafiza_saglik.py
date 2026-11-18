"""Tests for bin/hafiza_saglik.py: the memory health check of the OFIS notes (owner decision 2026-11-14). Temp vaults only."""
import builtins
import io
import json
import os
import sys
import tempfile
import unicodedata
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config, test/sahip_yasaklari.py)
import hafiza_saglik as hs  # noqa: E402
import ozet  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 11, 14, 7, 31)


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


def ders(gun, proje, job, text):
    return f"- {gun} · {proje} · [[{job}]] · raporundan\n  > {text}\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "vault")
        self.vault = os.path.join(self.root, "OFIS")
        self.durum = os.path.join(self.tmp.name, "durum")
        os.makedirs(self.vault)
        self.cfg = {"vault_ofis": self.vault, "ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"},
                    "hafiza_saglik": {"acik": True, "saat": "07:30", "eski_gun": 30}}
        self.clean()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text, mtime=None):
        path = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if mtime:
            ts = mtime.timestamp()
            os.utime(path, (ts, ts))
        return path

    def memory(self, key, verified="", unverified=""):
        self.write(f"Calisanlar/{key}-hafiza.md",
                   f"---\ntur: calisan-hafizasi\nuzmanlik: {key}\ndurum: aktif\n---\n\n# {key}\n\n## Şu an\n\nyok\n\n"
                   f"## Dersler (doğrulanmış)\n\nAçıklama.\n\n{verified or 'Henüz doğrulanmış ders yok.'}\n\n"
                   f"## Dersler (doğrulanmamış)\n\nAçıklama.\n\n{unverified or 'Doğrulanmamış ders yok.'}\n\n"
                   "## Sıradaki\n\nyok\n")

    def clean(self):
        """A healthy vault: links across folders, alias / heading forms, code spans, escaped links, root notes."""
        self.write("README.md", "# Ofis\n\n[[index]] · [[log]] · [[2026-11-13-090000-blog|iş]] · "
                   "[[blog#İşler]] · [[#Başlık]] · `[[kod-icinde]]` · \\[\\[kacisli]] · ![[resim.png]]\n"
                   "```\n[[blok-icinde]]\n```\n")
        self.write("resim.png", "x")
        self.write("Isler/Bitenler/2026-11-13-090000-blog.md",
                   "---\nproje: blog\ndurum: bitti\nolusturuldu: 2026-11-13T09:00:00\nbitis: 2026-11-13T10:00:00\n"
                   "---\n\n# İş\n\n[[2026-11-13-blog-soru]] [[Ozet]]\n")
        self.write("Isler/Devam-Edenler/2026-11-14-070000-blog.md",
                   "---\nproje: blog\ndurum: calisiyor\nolusturuldu: 2026-11-14T07:00:00\n---\n\n# İş\n")
        self.write("Isler/Siradakiler/2026-11-14-071000-kasa.md",
                   "---\nproje: kasa\ndurum: sirada\nolusturuldu: 2026-11-14T07:10:00\n---\n\n# İş\n")
        self.write("Kararlar/2026-11-13-blog-soru.md",
                   "---\nproje: blog\ndurum: bekliyor\nsoruldu: 2026-11-13T09:30:00\n---\n\n# Soru\n\n## Soru\n\n"
                   "> Devam mı?\n\n## İlgili Sayfalar\n- [[2026-11-13-090000-blog]]\n")
        # "## Cevap (Deniz)": the old answer heading (before the neutral protocol), still read as the owner's answer
        self.write("Kararlar/2026-11-12-blog-eski.md",
                   "---\nproje: blog\ndurum: cevaplandi\nsoruldu: 2026-11-12T09:30:00\ncevaplandi: 2026-11-12T10:00:00"
                   "\n---\n\n# Soru\n\n## Cevap (Deniz)\n\nDevam etsin.\n")
        self.write("Projeler/blog.md", "---\nproje: blog\ntur: proje-sorumlusu\ndurum: aktif\n---\n\n# blog\n\n"
                   "- [[2026-11-13-090000-blog]] — bitti\n- [[2026-11-14-070000-blog]]\n")
        self.write("Karne/Ozet.md", "---\ntags: [ofis, karne]\n---\n\n# Karne\n\nSatır.\n")
        self.write("Ozetler/2026-11-14.md", "---\ntur: sabah-ozeti\ntarih: 2026-11-14\ndurum: yazildi\n---\n\n# Özet\n")
        self.write("04-Aktif-Durum/Index.md", "---\ntags: [ofis]\n---\n\n# Aktif\n\n[[2026-11-13-blog-soru]]\n")
        self.memory("backend", verified=ders("2026-11-10", "blog", "2026-11-13-090000-blog",
                                             "Testleri nice ile çalıştır."))
        self.memory("ui", unverified=ders("2026-11-12", "blog", "2026-11-13-090000-blog",
                                          "Ekran görüntüsü alma."))
        # a file the vault root holds is never read; nothing about it shows up
        with open(os.path.join(self.root, "log.md"), "w", encoding="utf-8") as f:
            f.write("[[root-de-bozuk]]\n")

    def tara(self, now=NOW, eski=30):
        problems, _ = hs.tara(self.vault, now, eski)
        return problems

    def kinds(self, problems):
        return sorted({p["tur"] for p in problems})


class Clean(Base):
    def test_no_false_positives(self):
        problems, sayi = hs.tara(self.vault, NOW, 30)
        self.assertEqual(problems, [], [p["ayrinti"] for p in problems])
        self.assertGreaterEqual(sayi, 10)

    def test_nfd_and_case_insensitive_names_resolve(self):
        self.write(unicodedata.normalize("NFD", "Karne/Düzeltmeler-blog.md"), "---\nx: 1\n---\n\nmetin\n")
        self.write("Karne/Kayit.md", "---\nx: 1\n---\n\n[[düzeltmeler-BLOG]]\n")
        self.assertEqual(self.tara(), [])


class Links(Base):
    def test_broken_link_found_once_per_note(self):
        self.write("Raporlar/grup.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[Duzeltmeler-yok]] [[Duzeltmeler-yok|x]]\n"
                   "[[2026-11-13-090000-blog]]\n")
        problems = self.tara()
        self.assertEqual([(p["tur"], p["not"]) for p in problems], [("bozuk-baglanti", "grup")])
        self.assertIn("Duzeltmeler-yok", problems[0]["ayrinti"])

    def test_project_note_missing_job_is_stale_not_broken(self):
        self.write("Projeler/kasa.md", "---\nproje: kasa\ndurum: aktif\n---\n\n- [[2026-10-01-090000-kasa]]\n")
        self.assertEqual(self.kinds(self.tara()), ["eski-proje-isi"])

    def test_saglik_reports_are_not_scanned_for_links(self):
        self.write("Saglik/Saglik-2026-11-13.md", "---\ntarih: 2026-11-13\ndurum: yazildi\n---\n\n[[gitmis-not]]\n")
        self.assertEqual(self.tara(), [])


class Stale(Base):
    def test_old_lesson(self):
        self.memory("backend", verified=ders("2026-09-01", "blog", "2026-11-13-090000-blog", "Eski ders."))
        problems = self.tara()
        self.assertEqual(self.kinds(problems), ["eski-ders"])
        self.assertEqual(problems[0]["oneri"], "bu dersi yeniden doğrula")
        self.assertEqual(problems[0]["not"], "backend-hafiza")

    def test_old_pending_decision(self):
        self.write("Kararlar/2026-09-01-kasa-soru.md",
                   "---\nproje: kasa\ndurum: bekliyor\nsoruldu: 2026-09-01T09:00:00\n---\n\n# Soru\n")
        problems = self.tara()
        self.assertEqual(self.kinds(problems), ["eski-karar"])
        self.assertIn("bu kararı kapat", problems[0]["oneri"])

    def test_stuck_active_job(self):
        self.write("Isler/Devam-Edenler/2026-09-01-090000-kasa.md",
                   "---\nproje: kasa\ndurum: calisiyor\nolusturuldu: 2026-09-01T09:00:00\n"
                   "baslangic: 2026-09-01T09:01:00\n---\n\n# İş\n", mtime=datetime(2026, 9, 2))
        self.assertEqual(self.kinds(self.tara()), ["takili-is"])

    def test_threshold_from_config(self):
        self.memory("backend", verified=ders("2026-11-01", "blog", "2026-11-13-090000-blog", "Ders."))
        self.assertEqual(self.tara(eski=30), [])
        self.assertEqual(self.kinds(self.tara(eski=7)), ["eski-ders"])


class Contradictions(Base):
    def test_same_lesson_verified_and_unverified_across_roles(self):
        self.memory("backend", verified=ders("2026-11-10", "blog", "2026-11-13-090000-blog", "Önbelleği temizle!"))
        self.memory("ui", unverified=ders("2026-11-12", "blog", "2026-11-13-090000-blog", "önbelleği TEMİZLE"))
        problems = self.tara()
        self.assertEqual(self.kinds(problems), ["celiski-ders"])
        self.assertIn("[[ui-hafiza]]", problems[0]["ayrinti"])

    def test_duplicate_lesson_in_one_memory(self):
        line = ders("2026-11-10", "blog", "2026-11-13-090000-blog", "Aynı ders.")
        self.memory("backend", verified=line + line)
        self.assertEqual(self.kinds(self.tara()), ["tekrar-ders"])

    def test_decision_answered_twice_differently(self):
        # old answer heading (before the neutral protocol): still read as the owner's answer
        self.write("Kararlar/2026-11-13-kasa-iki.md",
                   "---\nproje: kasa\ndurum: cevaplandi\nsoruldu: 2026-11-13T09:00:00\n---\n\n# S\n\n"
                   "## Cevap (Deniz)\n\nEvet.\n\n## Cevap (Deniz)\n\nHayır, dur.\n")
        self.assertEqual(self.kinds(self.tara()), ["celiski-karar"])

    def test_same_answer_twice_is_no_contradiction(self):
        self.write("Kararlar/2026-11-13-kasa-iki.md",
                   "---\nproje: kasa\ndurum: cevaplandi\nsoruldu: 2026-11-13T09:00:00\n---\n\n# S\n\n"
                   "## Cevap (Deniz)\n\nEvet.\n\n## Cevap (Deniz)\n\nevet\n")
        self.assertEqual(self.tara(), [])


class Format(Base):
    def test_missing_and_invalid_fields(self):
        self.write("Isler/Bitenler/2026-11-13-100000-kasa.md", "---\ndurum: bitti\nolusturuldu: dun\n---\n\n# İş\n")
        self.write("Isler/Siradakiler/2026-11-13-110000-kasa.md",
                   "---\nproje: kasa\ndurum: bitti\nolusturuldu: 2026-11-13T11:00:00\n---\n\n# İş\n")
        problems = self.tara()
        texts = " / ".join(p["ayrinti"] for p in problems)
        self.assertEqual(self.kinds(problems), ["bicim"])
        self.assertIn("eksik alan: proje, bitis /", texts)
        self.assertIn("geçersiz tarih: olusturuldu", texts)
        self.assertIn("bu klasöre uymuyor", texts)

    def test_unclosed_frontmatter_and_empty_notes(self):
        self.write("Kararlar/2026-11-13-bozuk.md", "---\nproje: kasa\ndurum: bekliyor\n\n# Soru\n")
        self.write("Raporlar/bos.md", "---\ngrup: g\ndurum: tamam\n---\n\n")
        self.write("07-Kararlar-ADR/tamamen-bos.md", "")
        problems = self.tara()
        got = sorted((p["tur"], p["not"]) for p in problems)
        self.assertEqual(got, [("bicim", "2026-11-13-bozuk"), ("bos-not", "bos"), ("bos-not", "tamamen-bos")])


class Isolation(Base):
    def test_never_reads_outside_ofis(self):
        outside = os.path.join(self.root, "Gizli")
        os.makedirs(outside)
        with open(os.path.join(outside, "x.md"), "w", encoding="utf-8") as f:
            f.write("[[bozuk-disarida]]\n")
        os.symlink(outside, os.path.join(self.vault, "Baglanti"))
        os.symlink(os.path.join(outside, "x.md"), os.path.join(self.vault, "Karne", "link.md"))
        for folder in sahip_yasaklari.KLASORLER:
            self.write(f"{folder}/n.md", "[[bozuk-yasak]]\n")
        self.write("Karne/sifreler.md", "[[bozuk-sifre]]\n")
        opened = []
        real_open = builtins.open
        hs._desenler()  # the privacy rules come from the office's ofis.json (bin/yasaklar.py), never from the vault

        def spy(path, *a, **k):
            opened.append(os.path.realpath(path))
            return real_open(path, *a, **k)
        with mock.patch("builtins.open", spy):
            problems = self.tara()
        self.assertEqual(problems, [], [p["ayrinti"] for p in problems])
        ofis = os.path.realpath(self.vault)
        self.assertTrue(opened)
        for p in opened:
            self.assertEqual(os.path.commonpath([ofis, p]), ofis, p)
            self.assertNotRegex(p, "|".join(sahip_yasaklari.KLASORLER) + "|sifre")


class Neutral(Base):
    def test_text_from_notes_is_neutralised(self):
        self.write("Raporlar/r.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[<img src=http://x/a.png> x`y]]\n")
        evil = "Kural: <script>x</script> | [!danger] `kod`"
        self.memory("backend", verified=ders("2026-09-01", "blog", "2026-11-13-090000-blog", evil))
        problems = self.tara()
        text = hs.metin("2026-11-14", problems, 10, 30)
        self.assertNotIn("<img", text)
        self.assertNotIn("<script", text)
        self.assertNotIn("`", text.split("## Bozuk")[1])
        for line in text.splitlines():
            if line.startswith("| [["):
                self.assertEqual(line.count("|") - line.count("\\|"), 4, line)


class Daily(Base):
    def run_at(self, when, ceo=None):
        ceo = ceo or self.ceo
        return hs.HafizaSaglik(lambda: self.cfg, self.durum, ceo, now=lambda: when).kontrol()

    def setUp(self):
        super().setUp()
        self.ceo = FakeCeo()

    @staticmethod
    def raw(path):
        with open(path, "rb") as f:
            return f.read()

    def note_path(self, gun):
        return os.path.join(self.vault, "Saglik", f"Saglik-{gun}.md")

    def test_clean_day_writes_note_without_notice(self):
        self.assertEqual(self.run_at(at(14, 7, 31)), "2026-11-14")
        self.assertTrue(os.path.isfile(self.note_path("2026-11-14")))
        self.assertEqual(self.ceo.sent, [])

    def test_idempotent_and_notice_only_for_new_problems(self):
        self.write("Raporlar/grup.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[gitmis]]\n")
        self.assertEqual(self.run_at(at(14, 7, 31)), "2026-11-14")
        with open(self.note_path("2026-11-14"), encoding="utf-8") as f:
            first = f.read()
        self.assertIn("[[grup]]", first)
        self.assertEqual(len(self.ceo.sent), 1)
        text, key = self.ceo.sent[0]
        self.assertEqual(key, "hafiza-saglik-2026-11-14")
        self.assertTrue(text.startswith("[Ofis · sistem]\n"))
        self.assertIn("[[Saglik-2026-11-14]]", text)
        # same day again: nothing new, nothing rewritten
        self.assertIsNone(self.run_at(at(14, 12, 0)))
        with open(self.note_path("2026-11-14"), encoding="utf-8") as f:
            self.assertEqual(f.read(), first)
        self.assertEqual(len(self.ceo.sent), 1)
        # next day, same problem: a note, no notice
        self.assertEqual(self.run_at(at(15, 7, 40)), "2026-11-15")
        self.assertEqual(len(self.ceo.sent), 1)
        # the day after, one more problem: a notice naming 1 new
        self.write("Raporlar/iki.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[baska-gitmis]]\n")
        self.assertEqual(self.run_at(at(16, 7, 40)), "2026-11-16")
        self.assertEqual(len(self.ceo.sent), 2)
        self.assertIn("2 sorun (1 yeni)", self.ceo.sent[1][0])

    def test_before_the_hour_catches_up_yesterday_once_only(self):
        self.assertEqual(self.run_at(at(14, 6, 0)), "2026-11-13")
        self.assertIsNone(self.run_at(at(14, 7, 0)))
        self.assertEqual(self.run_at(at(14, 7, 30)), "2026-11-14")

    def test_existing_note_is_not_overwritten(self):
        self.write("Saglik/Saglik-2026-11-14.md", "---\ntarih: 2026-11-14\ndurum: yazildi\n---\n\nelle\n")
        self.assertEqual(self.run_at(at(14, 7, 31)), "2026-11-14")
        with open(self.note_path("2026-11-14"), encoding="utf-8") as f:
            self.assertIn("elle", f.read())

    def test_off_or_missing_key_does_nothing(self):
        self.cfg["hafiza_saglik"]["acik"] = False
        self.assertIsNone(self.run_at(at(14, 7, 31)))
        del self.cfg["hafiza_saglik"]
        self.assertIsNone(self.run_at(at(14, 7, 31)))
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Saglik")))

    def test_never_edits_other_notes(self):
        self.write("Raporlar/grup.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[gitmis]]\n")
        before = {}
        for here, _, files in os.walk(self.vault):
            for f in files:
                p = os.path.join(here, f)
                before[p] = (os.stat(p).st_mtime_ns, self.raw(p))
        self.run_at(at(14, 7, 31))
        for p, v in before.items():
            self.assertEqual((os.stat(p).st_mtime_ns, self.raw(p)), v, p)

    def test_morning_summary_line(self):
        self.write("Raporlar/grup.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[gitmis]]\n")
        self.run_at(at(14, 7, 31))
        self.assertEqual(hs.ozet_icin(self.durum, "2026-11-14"), {"sorun": 1, "not": "Saglik-2026-11-14"})
        self.assertEqual(hs.ozet_icin(self.durum, "2026-11-15"), {"sorun": 1, "not": "Saglik-2026-11-14"})
        self.assertIsNone(hs.ozet_icin(self.durum, "2026-11-16"))
        v = {"biten": [], "kararlar": [], "takilan": [], "sirada": [], "zamanlanmis": [], "projeler": [],
             "harcama": {}, "oneriler": [], "domain": [], "saglik": hs.ozet_icin(self.durum, "2026-11-14")}
        self.assertIn("Hafıza sağlığı: 1 sorun · [[Saglik-2026-11-14]]", ozet.metin("2026-11-14", v))
        v["saglik"] = {"sorun": 0, "not": "Saglik-2026-11-14"}
        self.assertNotIn("Hafıza sağlığı", ozet.metin("2026-11-14", v))


class Command(Base):
    def test_ofis_command_is_read_only(self):
        import ofis
        self.write("Raporlar/grup.md", "---\ngrup: g\ndurum: tamam\n---\n\n[[gitmis]]\n")
        out, err = io.StringIO(), io.StringIO()
        rc = ofis.main(["ofis.py", "hafiza-saglik"], cfg=self.cfg, durum_dir=self.durum, out=out, err=err)
        self.assertEqual(rc, 0, err.getvalue())
        self.assertIn("bozuk bağlantı: gitmis", out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Saglik")))
        self.assertFalse(os.path.exists(self.durum))


class Config(unittest.TestCase):
    def test_ayar(self):
        self.assertEqual(hs.ayar({}), {"acik": False, "saat": (7, 30), "eski_gun": 30})
        self.assertEqual(hs.ayar({"hafiza_saglik": {"acik": True, "saat": "06:05", "eski_gun": 7}}),
                         {"acik": True, "saat": (6, 5), "eski_gun": 7})
        self.assertEqual(hs.ayar({"hafiza_saglik": {"acik": "evet", "saat": "25:00", "eski_gun": True}}),
                         {"acik": False, "saat": (7, 30), "eski_gun": 30})

    def test_real_config_has_only_the_key(self):
        with open(os.path.join(HERE, "..", "ofis.example.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["hafiza_saglik"], {"acik": True, "saat": "07:30", "eski_gun": 30})


if __name__ == "__main__":
    unittest.main()
