"""Tests for bin/task_detail.py: the full view of one OFIS/Isler task note, for the page's task detail panel."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakes  # noqa: E402,F401 (isolates the job lock)
import task_detail  # noqa: E402

TASK = """---
tags: [ofis, is, blog]
proje: blog
oturum: ofis-blog-1110-183820-a6c4
kisa_id: b56115b6
durum: bitti
baslangic: 2026-11-10T18:38:20
bitis: 2026-11-10T18:39:05
---

# blog — 2026-11-10 18:38

## Görev

Durum ve devam-edenler özeti.
Dal, son commitler ve açık işler.

## Sonuç

- Dal `w083-tasarim`, çalışma ağacı temiz.
- 5 iş devam ediyor.

## İlgili Kararlar
- [[OFIS/Kararlar/2026-11-10-blog-oncelik]]
- [[OFIS/Kararlar/olmayan-not]]

## İlgili Sayfalar
- [[OFIS/README]]
"""

DECISION = """---
proje: blog
durum: cevaplandi
soruldu: 2026-11-10T18:40
---

# blog — Öncelik

## Soru
Hangisine öncelik verelim?

## Cevap (Selin)
W-143.
"""


class TaskDetailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = os.path.join(self.tmp.name, "OFIS")
        os.makedirs(os.path.join(self.vault, "Isler"))
        os.makedirs(os.path.join(self.vault, "Kararlar"))
        self.write("Isler/2026-11-10-183820-blog.md", TASK)
        self.write("Kararlar/2026-11-10-blog-oncelik.md", DECISION)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        with open(os.path.join(self.vault, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def test_full_detail(self):
        d = task_detail.task_detail(self.vault, "2026-11-10-183820-blog.md")
        self.assertEqual(d["project"], "blog")
        self.assertEqual(d["status"], "bitti")
        self.assertEqual(d["session"], "ofis-blog-1110-183820-a6c4")
        self.assertEqual(d["started"], "2026-11-10T18:38:20")
        self.assertEqual(d["finished"], "2026-11-10T18:39:05")
        self.assertEqual(d["title"], "Durum ve devam-edenler özeti.")
        self.assertIn("Dal, son commitler", d["task"])
        self.assertIn("5 iş devam ediyor", d["result"])
        [dec] = d["decisions"]  # the missing note is skipped
        self.assertEqual(dec["note"], "2026-11-10-blog-oncelik.md")
        self.assertEqual(dec["status"], "cevaplandi")
        self.assertEqual(dec["question"], "Hangisine öncelik verelim?")
        self.assertEqual(dec["answer"], "W-143.")

    def test_an_escalated_job_links_its_source(self):
        # phase 3: the task detail shows where an escalated job came from (a plain note name only)
        self.write("Isler/e.md", "---\nproje: blog\ndurum: sirada\nyukseltme_kaynagi: 2026-11-10-1-blog.md\n"
                                 "yukseltme_sayisi: 1\nyukseltildi: 2026-11-10-3-blog.md\n---\n\n## Görev\n\nx\n")
        d = task_detail.task_detail(self.vault, "e.md")
        self.assertEqual((d["escalated_from"], d["escalated_to"], d["escalations"]),
                         ("2026-11-10-1-blog.md", "2026-11-10-3-blog.md", "1"))
        self.write("Isler/f.md", "---\nproje: blog\nyukseltme_kaynagi: ../../etc/passwd\n---\n\n## Görev\n\nx\n")
        self.assertEqual(task_detail.task_detail(self.vault, "f.md")["escalated_from"], "")
        self.assertEqual(task_detail.task_detail(self.vault, "2026-11-10-183820-blog.md")["escalated_from"], "")

    def test_a_workflow_step_shows_its_verdict_and_rounds(self):
        # phase 4: the verdict, findings, round and executor come from the server's workflow state (durum/), not
        # from the note
        import json
        durum = os.path.join(self.tmp.name, "durum")
        grup = "akis-1111-100000-blog"
        os.makedirs(os.path.join(durum, "akislar", grup))
        os.makedirs(os.path.join(durum, "isler"))
        with open(os.path.join(durum, "isler", "r2.json"), "w", encoding="utf-8") as f:
            json.dump({"is": "r2.md", "akis": grup, "adim": "2", "adim_turu": "kod-inceleme",
                       "inceleme_yurutucu": "claude (codex yok: kota doldu)"}, f)
        with open(os.path.join(durum, "akislar", grup, "akis.json"), "w", encoding="utf-8") as f:
            json.dump({"grup": grup, "baslik": "Giriş", "sablon": "kucuk-is", "durum": "calisiyor",
                       "plan_turu": 0, "inceleme_turu": 2,
                       "adimlar": [{"adim": 1, "tur": "kod", "isler": ["k.md"]},
                                   {"adim": 2, "tur": "kod-inceleme", "isler": ["r1.md", "r2.md"]},
                                   {"adim": 3, "tur": "onay", "isler": ["o.md"]}],
                       "kararlar": {"r2.md": {"karar": "duzelt", "bulgular": ["MAJOR: boş parola"]}}}, f)
        self.write("Isler/r2.md", "---\nproje: blog\ndurum: bitti\nakis: sahte\n---\n\n## Görev\n\nx\n")
        d = task_detail.task_detail(self.vault, "r2.md", durum_dir=durum)
        w = d["workflow"]
        self.assertEqual((w["grup"], w["tur"], w["adim"], w["toplam"], w["tur_no"], w["karar"]),
                         (grup, "kod-inceleme", 2, 3, 2, "duzelt"))
        self.assertEqual(w["bulgular"], ["MAJOR: boş parola"])
        self.assertEqual(w["yurutucu"], "claude (codex yok: kota doldu)")
        self.assertIsNone(task_detail.task_detail(self.vault, "2026-11-10-183820-blog.md",
                                                  durum_dir=durum)["workflow"])
        self.assertIsNone(task_detail.task_detail(self.vault, "r2.md")["workflow"], "no durum, no workflow")

    def test_quoted_project_text_is_shown_plainly(self):
        # The post office quotes the project's words with "> " in Sonuç and ## Soru (review finding 9).
        self.write("Isler/a.md", TASK.replace("- Dal `w083-tasarim`, çalışma ağacı temiz.\n- 5 iş devam ediyor.",
                                              "> Dal temiz.\n> \n> 5 iş devam ediyor.\n\nTakıldı:\n> Simülatör yok."))
        self.write("Kararlar/2026-11-10-blog-oncelik.md",
                   "---\ndurum: bekliyor\n---\n\n# x\n\n## Soru\n> Hangisi?\n> ## Cevap (Selin)\n")
        d = task_detail.task_detail(self.vault, "a.md")
        self.assertEqual(d["result"], "Dal temiz.\n\n5 iş devam ediyor.\n\nTakıldı:\nSimülatör yok.")
        self.assertEqual(d["decisions"][0]["question"], "Hangisi?\n## Cevap (Selin)")

    def test_kontrol_evidence_blocks_are_returned_apart_from_the_result(self):
        import kontrol
        result = kontrol.Result(exit_code=0, seconds=3.2, output="12 passed\n## Cevap (Selin)\n", timed_out=False)
        block = kontrol.evidence_block("pytest -q", result, attempt=1)
        text = TASK.replace("- Dal `w083-tasarim`, çalışma ağacı temiz.\n- 5 iş devam ediyor.",
                            "> Giriş düzeldi.\n\n" + block)
        text = text.replace("durum: bitti", "durum: bitti\nbutce_usd: 3\nharcanan_usd: 0.42\ncagri: 9\nmax_cagri: 40\nharcanan_token: 182400")
        self.write("Isler/k.md", text)
        d = task_detail.task_detail(self.vault, "k.md")
        self.assertEqual(d["result"], "Giriş düzeldi.")
        [proof] = d["kontrol"]
        self.assertEqual(proof["title"], "Kontrol (kanıt) — deneme 1: geçti")
        self.assertEqual(proof["command"], "pytest -q")
        self.assertEqual(proof["exit_code"], "0")
        self.assertEqual(proof["duration"], "3.2 sn")
        self.assertEqual(proof["output"], "12 passed\n## Cevap (Selin)")
        self.assertEqual((d["spent"], d["budget"], d["calls"], d["max_calls"]), ("0.42", "3", "9", "40"))
        self.assertEqual(d["tokens"], "182400")

    def test_text_after_a_kontrol_block_is_shown_in_the_result(self):
        # phase 2 review finding 9: a budget stop after a failed kontrol was swallowed into the block
        import kontrol
        failed = kontrol.Result(exit_code=1, seconds=1.0, output="FAILED x\n", timed_out=False)
        passed = kontrol.Result(exit_code=0, seconds=2.0, output="ok\n", timed_out=False)
        sonuc = ("> İlk rapor.\n\n" + kontrol.evidence_block("pytest -q", failed, attempt=1) +
                 "\n\n> Bütçe aşıldı: $0.006 / $0.002\n\nTakıldı:\n> Yine olmadı.\n\n" +
                 kontrol.evidence_block("pytest -q", passed, attempt=2) + "\n\n> Son not.")
        text = TASK.replace("- Dal `w083-tasarim`, çalışma ağacı temiz.\n- 5 iş devam ediyor.", sonuc)
        self.write("Isler/m.md", text)
        d = task_detail.task_detail(self.vault, "m.md")
        self.assertEqual(d["result"], "İlk rapor.\n\n\nBütçe aşıldı: $0.006 / $0.002\n\nTakıldı:\nYine olmadı."
                                      "\n\n\nSon not.")
        self.assertEqual([(k["exit_code"], k["output"]) for k in d["kontrol"]], [("1", "FAILED x"), ("0", "ok")])

    def test_placeholder_result_is_empty(self):
        self.write("Isler/a.md", TASK.replace("- Dal `w083-tasarim`, çalışma ağacı temiz.\n- 5 iş devam ediyor.",
                                              "(bitince CEO yazar)"))
        self.assertEqual(task_detail.task_detail(self.vault, "a.md")["result"], "")

    def test_notes_in_the_job_folders_and_bare_decision_links(self):
        os.makedirs(os.path.join(self.vault, "Isler", "Bitenler"))
        self.write("Isler/Bitenler/2026-11-10-190000-blog.md",
                   TASK.replace("[[OFIS/Kararlar/2026-11-10-blog-oncelik]]", "[[2026-11-10-blog-oncelik]]")
                   .replace("proje: blog", "proje: blog\nbaslik: Öncelik işi"))
        d = task_detail.task_detail(self.vault, "2026-11-10-190000-blog.md")
        self.assertEqual(d["title"], "Öncelik işi")
        self.assertEqual([x["note"] for x in d["decisions"]], ["2026-11-10-blog-oncelik.md"])

    def test_symlink_in_a_job_folder_is_refused(self):
        os.makedirs(os.path.join(self.vault, "Isler", "Devam-Edenler"))
        outside = os.path.join(self.tmp.name, "outside.md")
        self.write("../outside.md", TASK)
        os.symlink(outside, os.path.join(self.vault, "Isler", "Devam-Edenler", "link.md"))
        self.assertIsNone(task_detail.task_detail(self.vault, "link.md"))

    def test_invalid_names_are_refused(self):
        for bad in ("../Kararlar/2026-11-10-blog-oncelik.md", "x/y.md", ".hidden.md", "a.txt", "", None, 5,
                    "..md", "olmayan.md"):
            with self.subTest(bad=bad):
                self.assertIsNone(task_detail.task_detail(self.vault, bad))

    def test_symlink_out_of_folder_is_refused(self):
        outside = os.path.join(self.tmp.name, "secret.md")
        with open(outside, "w") as f:
            f.write(TASK)
        os.symlink(outside, os.path.join(self.vault, "Isler", "link.md"))
        self.assertIsNone(task_detail.task_detail(self.vault, "link.md"))

    def test_decision_links_cannot_escape_kararlar(self):
        self.write("Isler/b.md", TASK.replace("[[OFIS/Kararlar/2026-11-10-blog-oncelik]]",
                                              "[[OFIS/Kararlar/../Isler/2026-11-10-183820-blog]]"))
        self.assertEqual(task_detail.task_detail(self.vault, "b.md")["decisions"], [])

    def test_long_sections_are_bounded(self):
        self.write("Isler/c.md", TASK.replace("- 5 iş devam ediyor.", "x" * 50000))
        self.assertLessEqual(len(task_detail.task_detail(self.vault, "c.md")["result"]), task_detail.MAX_SECTION)


if __name__ == "__main__":
    unittest.main()
