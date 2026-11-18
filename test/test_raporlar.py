"""Tests for the page's report reading in bin/rapor.py (phase 7): the list of group reports (OFIS/Raporlar/*.md, written
by the server) with their summary numbers, and one report's text. Temp vault only; the report text follows the
format bin/rapor.py writes (a round trip through report_text is in test_postoffice.GroupReportTest)."""
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
import rapor  # noqa: E402

REPORT = """---
tags: [ofis, rapor]
proje: blog
grup: {grup}
durum: tamam
tur: akis
surum: 2
baslangic: 2026-11-11T08:06:12
bitis: {bitis}
yazildi: 2026-11-11T10:07:04
toplam_usd: 0.5523
---

# blog — Faz 4 deneme: README'ye tek satır (x) ({grup})

> Bu raporu Ofis sunucusu grup bitince yazar (elle düzenleme).

## İşler

| İş | Katman / model | Sonuç | Kontrol ilk turda | Kontrol denemesi | Devam | Yükseltme | Maliyet ($) | Süre (dk) |
|---|---|---|---|---|---|---|---|---|
| [[2026-11-11-075319-blog]] | kod / opus | bitti | evet | 1 | 0 | — | 0.5400 | 52 |
| [[2026-11-11-075319-blog-2]] | inceleme / opus | takıldı | yok | 0 | 0 | — | Codex (fiyat bilinmiyor) | — |
| [[2026-11-11-075319-blog-3]] | genel / sonnet | iptal | yok | 0 | 0 | — | 0.0123 | — |

## Toplamlar

- Toplam kayıtlı harcama: $0.55; Codex'in fiyatı bilinmiyor
- Doğrulanmış iş başına maliyet: $0.0111 (1 iş kontrolü geçerek bitti)
- Kontrol ilk turda geçme: %100 (1/1)
- Yeniden iş: 2 (Kontrol geçmedi: 1, inceleme düzeltme istedi: 1, bir üst katmana taşındı: 0, devam ettirildi: 0)
- Döngü süresi (ilk başlangıç → son bitiş): 52 dk

## Açık kalanlar

- [[2026-11-11-075319-blog-2]] takıldı. Sonucun son satırı: “x”
- Akış iptal edildi.

## Düzeltmeler

- Bu grupta düzeltme gerekmedi.
"""


class ReportReadingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = os.path.join(os.path.realpath(self.tmp.name), "OFIS")
        self.folder = os.path.join(self.vault, "Raporlar")
        os.makedirs(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, grup, bitis="2026-11-11T08:58:34", text=None):
        with open(os.path.join(self.folder, f"{grup}.md"), "w", encoding="utf-8") as f:
            f.write(text if text is not None else REPORT.format(grup=grup, bitis=bitis))

    def test_a_report_summary_has_its_counts_costs_and_open_items(self):
        self.write("akis-1111-075319-blog")
        [r] = rapor.list_reports(self.vault)
        self.assertEqual(r, {"grup": "akis-1111-075319-blog", "baslik": "Faz 4 deneme: README'ye tek satır (x)",
                             "proje": "blog", "tur": "akis", "surum": 2, "baslangic": "2026-11-11T08:06:12",
                             "bitis": "2026-11-11T08:58:34", "yazildi": "2026-11-11T10:07:04", "toplam_usd": 0.5523,
                             "is_sayisi": 3, "sonuclar": {"bitti": 1, "tikandi": 1, "iptal": 1},
                             "dogrulanmis_is_basina_usd": 0.5523, "dogrulanan": 1, "ilk_tur_gecen": 1,
                             "ilk_tur_olculen": 1, "yeniden_is": 2, "acik": 2, "fiyat_bilinmiyor": True,
                         "toplam_token": None, "dogrulanmis_is_basina_token": None,
                         "token_eksik": 0,  # a report from before tokens: unknown, never 0
                     "deneme_is": 0})  # and from before self-test jobs: none left out

    def test_the_cost_per_verified_job_comes_from_the_total_not_the_rounded_text(self):
        # review finding: the Toplamlar line is rounded ($0.89); the frontmatter total keeps four decimals
        text = REPORT.format(grup="g", bitis="").replace("toplam_usd: 0.5523", "toplam_usd: 1.7718").replace(
            "$0.0111 (1 iş", "$0.89 (2 iş")
        self.write("g", text=text)
        [r] = rapor.list_reports(self.vault)
        self.assertEqual((r["dogrulanmis_is_basina_usd"], r["dogrulanan"]), (0.8859, 2))
        # without the frontmatter total the text value is the fallback
        self.write("g", text=text.replace("toplam_usd: 1.7718\n", ""))
        [r] = rapor.list_reports(self.vault)
        self.assertEqual((r["toplam_usd"], r["dogrulanmis_is_basina_usd"]), (None, 0.89))

    def test_a_report_written_with_a_codex_review_says_its_cost_is_incomplete(self):
        def job(name, katman, status, **meta):
            return jobs.Job(name, jobs.DONE, "", {"proje": "blog", "katman": katman, "model": "opus",
                                                  "durum": status, "baslik": "Giriş", **meta}, "")
        rows = [{"job": job("2026-11-11-1-blog.md", "kod", "bitti", kontrol_sonuc="gecti"), "tier": "kod / opus",
                 "status": "bitti", "first": "evet", "tries": 1, "devam": 0, "escalation": "—", "cost": 1.7718,
                 "minutes": 30, "moved": "", "step": "kod"},
                {"job": job("2026-11-11-2-blog.md", "inceleme", "bitti"), "tier": "inceleme / opus",
                 "status": "bitti", "first": "yok", "tries": 0, "devam": 0, "escalation": "—", "cost": None,
                 "minutes": None, "moved": "", "step": "kod-inceleme"}]
        s = {"group": "g", "projects": ["blog"], "rows": rows, "events": [], "total": 1.7718, "unknown": True,
             "verified": 1, "per_verified": 1.7718, "first": ["evet"],
             "rework": dict.fromkeys(karne.REWORK_KINDS, 0), "statuses": {"bitti": 2},
             "start": datetime(2026, 11, 11, 8), "end": datetime(2026, 11, 11, 9), "state": None}
        self.write("g", text=rapor.report_text("", s, 1, datetime(2026, 11, 11, 10)))
        [r] = rapor.list_reports(self.vault)
        self.assertEqual((r["toplam_usd"], r["dogrulanmis_is_basina_usd"], r["fiyat_bilinmiyor"]),
                         (1.7718, 1.7718, True))
        s.update(unknown=False, rows=rows[:1], statuses={"bitti": 1})
        self.write("g", text=rapor.report_text("", s, 1, datetime(2026, 11, 11, 10)))
        self.assertFalse(rapor.list_reports(self.vault)[0]["fiyat_bilinmiyor"])

    def _links_summary(self, events, notes):
        job = jobs.Job("2026-11-11-1-blog.md", jobs.DONE, "", {"proje": "blog", "katman": "kod", "model": "opus",
                                                                 "durum": "bitti", "baslik": "Giriş"}, "")
        row = {"job": job, "tier": "kod / opus", "status": "bitti", "first": "evet", "tries": 1, "devam": 0,
               "escalation": "—", "cost": 1.0, "minutes": 30, "moved": "", "step": "kod"}
        return {"group": "g", "projects": ["blog"], "correction_notes": notes, "rows": [row], "events": events,
                "total": 1.0, "unknown": False, "verified": 0, "per_verified": None, "first": ["evet"],
                "rework": dict.fromkeys(karne.REWORK_KINDS, 0), "statuses": {"bitti": 1},
                "start": datetime(2026, 11, 11, 8), "end": datetime(2026, 11, 11, 9), "state": None}

    def test_a_report_links_a_duzeltmeler_note_only_when_it_exists(self):
        text = rapor.report_text("", self._links_summary([], []), 1, datetime(2026, 11, 11, 10))
        self.assertNotIn("[[Duzeltmeler-", text)
        self.assertIn("Düzeltme kaydı yok", text)
        text = rapor.report_text("", self._links_summary([], ["blog"]), 1, datetime(2026, 11, 11, 10))
        self.assertIn("- [[Duzeltmeler-blog]]", text)
        self.assertNotIn("Düzeltme kaydı yok", text)

    def test_summarise_lists_only_the_duzeltmeler_notes_on_disk(self):
        durum = os.path.join(self.tmp.name, "durum")
        job = jobs.Job("2026-11-11-1-blog.md", jobs.DONE, "", {"proje": "blog", "durum": "bitti"}, "")
        self.assertEqual(rapor.summarise(durum, self.vault, "g", [job], None)["correction_notes"], [])
        os.makedirs(os.path.join(self.vault, "Karne"))
        with open(os.path.join(self.vault, "Karne", "Duzeltmeler-blog.md"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertEqual(rapor.summarise(durum, self.vault, "g", [job], None)["correction_notes"], ["blog"])

    def test_a_panel_review_counts_the_hakem_cost_and_leaves_out_only_codex(self):
        import records
        durum = os.path.join(self.tmp.name, "durum")
        name = "2026-11-11-2-blog.md"
        job = jobs.Job(name, jobs.DONE, "", {"proje": "blog", "durum": "bitti", "harcanan_usd": "9"}, "")
        records.update(durum, name, {"adim_turu": "kod-inceleme", "inceleme_yurutucu": "codex",
                                     "harcanan_usd": "0.0582"})
        self.assertEqual((rapor._cost(durum, job), rapor._codex_review(durum, job)), (0.0582, True))
        records.update(durum, name, {"harcanan_usd": ""})
        self.assertEqual(rapor._cost(durum, job), None, "no hakem: the price is wholly unknown, as before")
        row = {"job": job, "tier": "inceleme / heyet", "status": "bitti", "first": "yok", "tries": 0, "devam": 0,
               "escalation": "—", "cost": 0.0582, "codex": True, "minutes": None, "moved": "", "step": "kod-inceleme"}
        s = {"group": "g", "projects": ["blog"], "rows": [row], "events": [], "total": 0.0582, "unknown": True,
             "verified": 0, "per_verified": None, "first": [], "rework": dict.fromkeys(karne.REWORK_KINDS, 0),
             "statuses": {"bitti": 1}, "start": datetime(2026, 11, 11, 8), "end": datetime(2026, 11, 11, 9),
             "state": None}
        text = rapor.report_text("", s, 1, datetime(2026, 11, 11, 10))
        self.assertIn("0.0582 (Codex hariç)", text)
        self.assertIn("Codex hariç", jobs.section(jobs.parse(text)[2], "Toplamlar"))
        self.write("g", text=text)
        [r] = rapor.list_reports(self.vault)
        self.assertEqual((r["toplam_usd"], r["fiyat_bilinmiyor"]), (0.0582, True))

    def test_unknown_numbers_stay_unknown(self):
        text = REPORT.format(grup="g", bitis="").replace(
            "- Doğrulanmış iş başına maliyet: $0.0111 (1 iş kontrolü geçerek bitti)",
            "- Doğrulanmış iş başına maliyet: — (kontrolü geçerek biten iş yok)").replace(
            "- Kontrol ilk turda geçme: %100 (1/1)", "- Kontrol ilk turda geçme: — (kontrol çalışmadı)").replace(
            "toplam_usd: 0.5523\n", "").replace("- Akış iptal edildi.\n", "- Açık kalan yok.\n").replace(
            "- [[2026-11-11-075319-blog-2]] takıldı. Sonucun son satırı: “x”\n", "")
        self.write("g", text=text)
        [r] = rapor.list_reports(self.vault)
        self.assertEqual((r["dogrulanmis_is_basina_usd"], r["dogrulanan"], r["ilk_tur_olculen"], r["toplam_usd"],
                          r["acik"]), (None, 0, 0, None, 0))

    def test_newest_first_and_only_plain_report_files(self):
        self.write("eski", bitis="2026-11-10T10:00:00")
        self.write("yeni", bitis="2026-11-11T10:00:00")
        self.write("bos-bitis", bitis="")  # falls back to yazildi (2026-11-11T10:07:04)
        os.symlink(os.path.join(self.folder, "eski.md"), os.path.join(self.folder, "baglanti.md"))
        os.makedirs(os.path.join(self.folder, "klasor.md"))
        for name in (".gizli.md", "bosluklu ad.md", "notu.txt"):
            with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
                f.write(REPORT.format(grup="x", bitis=""))
        self.assertEqual([r["grup"] for r in rapor.list_reports(self.vault)], ["bos-bitis", "yeni", "eski"])

    def test_a_missing_folder_is_an_empty_list(self):
        self.assertEqual(rapor.list_reports(os.path.join(self.vault, "yok")), [])

    def test_reading_one_report_gives_its_body_without_the_frontmatter(self):
        self.write("giris")
        r = rapor.read_report(self.vault, "giris")
        self.assertEqual(r["grup"], "giris")
        self.assertTrue(r["metin"].startswith("# blog — Faz 4 deneme"), r["metin"][:40])
        self.assertNotIn("toplam_usd:", r["metin"])
        self.assertEqual(r["is_sayisi"], 3)

    def test_the_group_name_is_strict(self):
        self.write("giris")
        outside = os.path.join(self.vault, "gizli.md")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("gizli")
        for bad in ("", "../gizli", "Raporlar/giris", "giris.md", ".giris", "a b", "x" * 61, None, 5, "giris\x00"):
            with self.subTest(bad=bad):
                self.assertFalse(rapor.valid_group(bad))
                self.assertIsNone(rapor.read_report(self.vault, bad))
        self.assertTrue(rapor.valid_group("akis-1111-075319-blog"))
        self.assertIsNone(rapor.read_report(self.vault, "yok"))
        os.symlink(outside, os.path.join(self.folder, "baglanti.md"))
        self.assertIsNone(rapor.read_report(self.vault, "baglanti"))

    def test_a_huge_report_is_not_read(self):
        self.write("buyuk", text=REPORT.format(grup="buyuk", bitis="") + "x" * (rapor.MAX_REPORT_BYTES + 1))
        self.assertIsNone(rapor.read_report(self.vault, "buyuk"))
        self.assertEqual(rapor.list_reports(self.vault), [])


if __name__ == "__main__":
    unittest.main()
