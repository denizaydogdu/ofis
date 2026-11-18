"""Tests for bin/karne.py: the scorecard rows (OFIS/Karne/Kayitlar-YYYY-MM.md) and the generated summary (Ozet.md).
Temp vault only."""
import os
import sys
import tempfile
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import budget  # noqa: E402
import fakes  # noqa: E402,F401 (isolates the job lock)
import jobs  # noqa: E402
import karne  # noqa: E402

NOW = datetime(2026, 11, 10, 18, 38, 20)


class WorkerVocabularyTest(unittest.TestCase):
    """The owner, 2026-11-11: the vault notes say "Kıdemli (opus)" under "Çalışan"; older notes still parse."""

    def test_worker_cells_round_trip_and_old_cells_read_as_they_are(self):
        self.assertEqual(karne.worker("opus"), "Kıdemli (opus)")
        self.assertEqual(karne.worker("claude-haiku-4-5"), "Stajyer (claude-haiku-4-5)")
        self.assertEqual(karne.worker("gpt-x"), "gpt-x")
        self.assertEqual(karne.worker(""), "")
        self.assertEqual(karne.worker("Kıdemli (opus)"), "Kıdemli (opus)", "never doubled")
        for model in ("opus", "sonnet", "fable", "claude-haiku-4-5"):
            self.assertEqual(karne.model_of(karne.worker(model)), model)
        self.assertEqual(karne.model_of("haiku"), "haiku", "an older plain cell")

    def test_a_month_file_with_the_old_model_header_is_upgraded_and_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as vault:
            folder = os.path.join(vault, "Karne")
            os.makedirs(folder)
            old_head = "| " + " | ".join(karne.COLUMNS) + " |\n|" + "---|" * len(karne.COLUMNS) + "\n"
            self.assertIn("| Model |", old_head)
            row = ("| 2026-11-09 | blog | [[eski]] | kod | opus | high | evet | 1 | hayır | 3 | 1.0000 | 1.0000 | "
                   "10 | bitti | 0 |  |  |  |\n")
            with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
                f.write("# Karne\n\n" + old_head + row)
            [r] = karne._rows(vault)
            self.assertEqual(r["Model"], "opus")
            upgraded = karne._upgrade(old_head + row)
            self.assertIn("| Çalışan |", upgraded)
            self.assertNotIn("| Model |", upgraded)
            self.assertIn("| blog | kod | Kıdemli (opus) |", karne.summary_text(vault))


class KarneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = os.path.join(os.path.realpath(self.tmp.name), "OFIS")
        os.makedirs(self.vault)
        self.usages = {}

    def tearDown(self):
        self.tmp.cleanup()

    def finished(self, status="bitti", katman="kod", model="opus", effort="high", bitis="2026-11-10T19:08:20",
                 project="blog", **fields):
        job = jobs.create(self.vault, project, "Giriş hatası", brief={"hedef": "Düzelt."}, now=NOW,
                          fields={"katman": katman, "model": model, "effort": effort})
        meta = {"baslangic": "2026-11-10T18:38:20", "bitis": bitis, "oturum": "ofis-x-1", "kisa_id": "abcdef12"}
        meta.update(fields)
        jobs.update(self.vault, job.name, status="calisiyor")
        return jobs.update(self.vault, job.name, status=status, fields=meta).name

    def usage_of(self, job):
        return self.usages.get(job.name)

    def process(self):
        return karne.process_pending(self.vault, self.usage_of, now=lambda: NOW)

    def read(self, name):
        with open(os.path.join(self.vault, "Karne", name), encoding="utf-8") as f:
            return f.read()

    def rows(self, name="Kayitlar-2026-11.md"):
        return [line for line in self.read(name).splitlines() if line.startswith("| 2026")]

    def test_an_offset_bearing_note_never_blocks_the_rows_after_it(self):
        # codex review: "+03:00" in baslangic and a naive bitis made `finished >= started` raise TypeError
        odd = self.finished(baslangic="2026-11-10T18:38:20+03:00", bitis="2026-11-10T19:08:20")
        normal = self.finished(project="kasa")
        written = self.process()
        self.assertEqual(sorted(written), sorted([odd, normal]))
        self.assertEqual(len(self.rows()), 2)

    def test_one_failing_row_is_skipped_and_the_others_are_written(self):
        bad = self.finished()
        good = self.finished(project="kasa")
        real = karne.write_row

        def flaky(vault, job, usage, now, record=None):
            if job.name == bad:
                raise RuntimeError("boom")
            return real(vault, job, usage, now, record=record)
        karne.write_row = flaky
        try:
            written = self.process()
        finally:
            karne.write_row = real
        self.assertEqual(written, [good])
        self.assertEqual(jobs.load(self.vault, bad).meta["karne"], "bekliyor")  # still due: tried again next pass

    def test_a_finished_job_gets_one_row_with_every_column(self):
        name = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        self.usages[name] = budget.Usage(cost=1.234, calls=17, unpriced=0, session_id="x")
        self.assertEqual(self.process(), [name])
        text = self.read("Kayitlar-2026-11.md")
        self.assertIn("| Tarih | Proje | İş | Katman | Çalışan | Effort | Kontrol ilk turda | Kontrol denemesi | "
                      "Yükseltme | Çağrı | Maliyet ($) | Doğrulanmış maliyet ($) | Süre (dk) | Sonuç | Devam | Akış | Adım | Token | "
                      "Deneme | Uzmanlık |",
                      text)
        self.assertEqual(self.rows(), [f"| 2026-11-10 | blog | [[{jobs.stem(name)}]] | kod | Kıdemli (opus) | high | evet | 1 "
                                       "| hayır | 17 | 1.2340 | 1.2340 | 30 | bitti | 0 |  |  | 0 |  |  |"])
        job = jobs.load(self.vault, name)
        self.assertEqual((job.meta["karne"], job.meta["harcanan_usd"], job.meta["cagri"]), ("yazildi", "1.234", "17"))

    def test_the_row_takes_tier_model_and_kontrol_from_the_server_record(self):
        # phase 8 review: a session can edit its own note (e.g. kontrol_deneme 2 → 1); the record the server wrote
        # wins where it has the field, the note fills the rest (a job from before the record kept it)
        name = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti", katman="kolay", model="haiku")
        record = {"kontrol_deneme": "2", "kontrol_sonuc": "gecti", "katman": "kod", "model": "opus"}
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, record_of=lambda job: record)
        [line] = self.rows()
        self.assertIn("| kod | Kıdemli (opus) | high | hayır | 2 |", line)
        other = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti", bitis="2026-11-10T19:09:00")
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, record_of=lambda job: None)
        self.assertIn(f"| [[{jobs.stem(other)}]] | kod | Kıdemli (opus) | high | evet | 1 |", self.rows()[1])

    def test_a_job_appears_once(self):
        name = self.finished()
        self.process()
        jobs.update(self.vault, name, fields={"karne": "bekliyor"})  # e.g. a crash before the note was updated
        self.process()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.process(), [])

    def test_kontrol_columns_and_verified_cost(self):
        first_fail = self.finished(kontrol_deneme="2", kontrol_sonuc="gecti")
        stuck = self.finished(status="tikandi", kontrol_deneme="2", kontrol_sonuc="kaldi")
        none = self.finished(katman="genel", model="sonnet", effort="medium")
        for n in (first_fail, stuck, none):
            self.usages[n] = budget.Usage(cost=0.5, calls=3, unpriced=0, session_id="x")
        self.process()
        rows = {r.split(" | ")[2]: r.split(" | ") for r in self.rows()}
        ff, st, no = (rows[f"[[{jobs.stem(n)}]]"] for n in (first_fail, stuck, none))
        self.assertEqual((ff[6], ff[7], ff[11]), ("hayır", "2", "0.5000"))
        self.assertEqual((st[6], st[7], st[11], st[13]), ("hayır", "2", "", "tikandi"))
        self.assertEqual((no[6], no[7], no[11]), ("yok", "0", ""))

    def test_an_escalated_job_row_says_yukseltme_evet_and_its_source_stays_tikandi(self):
        # phase 3, ADR §8: the new job (one tier up) is marked; the job it replaces keeps its tikandi row
        source = self.finished(status="tikandi", katman="genel", kontrol_deneme="2", kontrol_sonuc="kaldi")
        new = self.finished(katman="kod", yukseltme_kaynagi=source, yukseltme_sayisi="1")
        self.process()
        rows = {r.split(" | ")[2]: r.split(" | ") for r in self.rows()}
        self.assertEqual(rows[f"[[{jobs.stem(new)}]]"][8], "evet")
        self.assertEqual((rows[f"[[{jobs.stem(source)}]]"][8], rows[f"[[{jobs.stem(source)}]]"][13]),
                         ("hayır", "tikandi"))

    def test_without_a_transcript_the_recorded_values_are_used(self):
        name = self.finished(status="iptal", harcanan_usd="0.40", cagri="6", bitis="2026-12-01T09:00:00")
        self.process()
        [row] = self.rows("Kayitlar-2026-12.md")
        self.assertIn("| 6 | 0.4000 |  |", row)
        self.assertTrue(row.endswith("| iptal | 0 |  |  |  |  |  |"), row)  # tokens unknown: empty, never 0

    def test_the_summary_is_generated_from_all_rows(self):
        a = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        b = self.finished(status="tikandi", kontrol_deneme="2", kontrol_sonuc="kaldi")
        c = self.finished(katman="kolay", model="haiku", effort="low", bitis="2026-12-02T10:00:00")
        self.usages.update({a: budget.Usage(1.0, 5, 0, "x"), b: budget.Usage(3.0, 9, 0, "x"),
                            c: budget.Usage(0.02, 6, 0, "x")})
        self.process()
        summary = self.read("Ozet.md")
        self.assertIn("elle düzenlemeyin", summary)
        self.assertIn("[[Kayitlar-2026-11]]", summary)
        self.assertIn("[[Kayitlar-2026-12]]", summary)
        self.assertIn("| blog | kod | Kıdemli (opus) | 2 | %50 (1/2) | %50 (1/2) | 2.0000 | 1.0000 | 4.0000 |", summary)
        self.assertIn("| blog | kolay | Stajyer (haiku) | 1 | %100 (1/1) | — | 0.0200 | — | 0.0200 |", summary)
        self.assertTrue(os.path.isfile(os.path.join(self.vault, "Karne", "Degisiklikler.md")))

    def test_the_changes_file_is_created_once_and_never_overwritten(self):
        self.finished()
        self.process()
        path = os.path.join(self.vault, "Karne", "Degisiklikler.md")
        self.assertIn("| Tarih |", self.read("Degisiklikler.md"))
        with open(path, "a", encoding="utf-8") as f:
            f.write("| 2026-11-11 | kolay: haiku → sonnet | ... | [[x]] |\n")
        self.finished()
        self.process()
        self.assertIn("haiku → sonnet", self.read("Degisiklikler.md"))

    def test_cells_cannot_break_the_table(self):
        name = self.finished(model="a|b", effort="x\ny")
        self.process()
        [row] = self.rows()
        self.assertEqual(len(row.split(" | ")), len(karne.COLUMNS), row)
        self.assertIn(f"[[{jobs.stem(name)}]]", row)

    def test_jobs_not_marked_pending_are_ignored(self):
        old = jobs.create(self.vault, "blog", "Eski", brief={"hedef": "x"}, now=NOW)
        path = jobs.update(self.vault, old.name, status="bitti").path
        with open(path, encoding="utf-8") as f:
            text = f.read().replace("karne: bekliyor\n", "")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)  # a phase-1 note: finished before the scorecard existed
        self.assertEqual(self.process(), [])
        self.assertFalse(os.path.exists(os.path.join(self.vault, "Karne", "Kayitlar-2026-11.md")))

    # --- phase 2 review ---

    def test_after_devam_the_row_is_replaced_in_place_with_the_devam_count(self):
        # finding 2: the karne row was written at the first final status and never updated
        name = self.finished(status="tikandi", durdurma_nedeni="butce")
        self.usages[name] = budget.Usage(cost=3.2, calls=5, unpriced=0, session_id="x")
        self.process()
        other = self.finished()
        self.process()
        jobs.update(self.vault, name, status="calisiyor", fields={"karne": "", "devam_sayisi": "1", "bitis": ""})
        jobs.update(self.vault, name, status="bitti", fields={"kontrol_deneme": "1", "kontrol_sonuc": "gecti",
                                                              "bitis": "2026-11-10T20:00:00"})
        self.usages[name] = budget.Usage(cost=4.5, calls=8, unpriced=0, session_id="x")
        self.assertEqual(self.process(), [name])
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        mine = [r for r in rows if f"[[{jobs.stem(name)}]]" in r]
        self.assertEqual(len(mine), 1)
        self.assertEqual(rows.index(mine[0]), 0, "replaced where it was, not appended")
        self.assertTrue(mine[0].endswith("| 8 | 4.5000 | 4.5000 | 82 | bitti | 1 |  |  | 0 |  |  |"), mine[0])
        self.assertIn(f"[[{jobs.stem(other)}]]", rows[1])
        self.assertIn("toplam 2 iş", self.read("Ozet.md"))
        self.assertIn("| blog | kod | Kıdemli (opus) | 2 | %100 (2/2) |", self.read("Ozet.md"))

    def test_small_costs_keep_four_decimals(self):
        name = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        self.usages[name] = budget.Usage(cost=0.0061, calls=2, unpriced=0, session_id="x")
        self.process()
        self.assertIn("| 2 | 0.0061 | 0.0061 |", self.rows()[0])
        self.assertEqual(jobs.load(self.vault, name).meta["harcanan_usd"], "0.0061")
        self.assertIn("| 0.0061 | 0.0061 | 0.0061 |", self.read("Ozet.md"))

    def test_an_older_file_without_the_devam_column_is_upgraded(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        old_head = "| " + " | ".join(karne.COLUMNS[:14]) + " |\n|" + "---|" * 14 + "\n"
        old_row = "| 2026-11-09 | blog | [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.01 |  | 0 | tikandi |\n"
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# Karne kayıtları — 2026-11\n\n" + old_head + old_row)
        self.finished()
        self.process()
        text = self.read("Kayitlar-2026-11.md")
        self.assertIn(" | Sonuç | Devam | Akış | Adım | Token | Deneme | Uzmanlık |\n|" + "---|" * 20 + "\n", text)
        self.assertIn("| [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.01 |  | 0 | tikandi | 0 |  |  |  |",
                      text)
        self.assertIn("toplam 2 iş", self.read("Ozet.md"))

    def test_the_final_spending_reaches_the_note_and_the_record_before_the_row(self):
        # finding 13
        name = self.finished(cagri="1", harcanan_usd="0.01")
        self.usages[name] = budget.Usage(cost=0.0234, calls=3, unpriced=0, session_id="x")
        seen = []

        def on_final(job_name, fields):
            seen.append((job_name, dict(fields), os.path.exists(os.path.join(self.vault, "Karne",
                                                                               "Kayitlar-2026-11.md"))))
        real = karne.write_row

        def crash(*a, **k):
            raise OSError("disk dolu")
        karne.write_row = crash
        try:
            # a failing row is skipped (logged once) and stays due; it no longer aborts the pass
            self.assertEqual(karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, on_final=on_final), [])
        finally:
            karne.write_row = real
        job = jobs.load(self.vault, name)
        self.assertEqual((job.meta["cagri"], job.meta["harcanan_usd"], job.meta["karne"]), ("3", "0.0234", "bekliyor"))
        self.assertEqual(seen, [(name, {"harcanan_usd": "0.0234", "cagri": 3, "harcanan_token": 0}, False)])
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, on_final=on_final)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(jobs.load(self.vault, name).meta["karne"], "yazildi")


    # --- phase 4: workflow columns ---

    def test_a_workflow_step_row_names_its_workflow_and_step_kind(self):
        name = self.finished(akis="akis-1111-100000-blog", adim="2", adim_turu="plan-inceleme")
        self.process()
        [row] = self.rows()
        self.assertTrue(row.endswith("| bitti | 0 | akis-1111-100000-blog | plan-inceleme |  |  |  |"), row)
        self.assertIn(f"[[{jobs.stem(name)}]]", row)

    def test_a_file_from_before_the_workflow_columns_is_upgraded_and_stays_readable(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        head = "| " + " | ".join(karne.COLUMNS[:15]) + " |\n|" + "---|" * 15 + "\n"
        old_row = ("| 2026-11-09 | blog | [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.0100 |  | 0 "
                   "| tikandi | 1 |\n")
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# Karne kayıtları — 2026-11\n\n" + head + old_row)
        self.assertEqual(len(karne._rows(self.vault)), 1, "an old row is read before the upgrade")
        self.finished(akis="akis-x", adim="3", adim_turu="kod")
        self.process()
        text = self.read("Kayitlar-2026-11.md")
        self.assertIn(" | Devam | Akış | Adım | Token | Deneme | Uzmanlık |\n|" + "---|" * 20 + "\n", text)
        self.assertIn("| [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.0100 |  | 0 | tikandi | 1 |  |  |  |  |",
                      text)
        self.assertTrue(self.rows()[-1].endswith("| akis-x | kod |  |  |  |"), self.rows()[-1])
        self.assertIn("toplam 2 iş", self.read("Ozet.md"))

    def test_a_file_from_before_the_token_column_is_upgraded_and_old_rows_have_no_tokens(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        head = "| " + " | ".join(karne.COLUMNS[:17]) + " |\n|" + "---|" * 17 + "\n"
        old_row = ("| 2026-11-09 | blog | [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.0100 |  | 0 "
                   "| tikandi | 1 |  |  |\n")
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# Karne kayıtları — 2026-11\n\n" + head + old_row)
        [old] = karne._rows(self.vault)  # read before the upgrade
        self.assertEqual(old["Token"], "")
        self.assertIsNone(karne.quality(self.vault)["toplam"]["toplam_token"])  # unknown, never 0
        name = self.finished()
        self.usages[name] = budget.Usage(0.5, 4, 0, "x", tokens=182400)
        self.process()
        text = self.read("Kayitlar-2026-11.md")
        self.assertIn(" | Adım | Token | Deneme | Uzmanlık |\n|" + "---|" * 20 + "\n", text)
        self.assertIn("| tikandi | 1 |  |  |  |  |", text)
        self.assertTrue(self.rows()[-1].endswith("| 182400 |  |  |"), self.rows()[-1])
        total = karne.quality(self.vault)["toplam"]
        self.assertEqual((total["toplam_token"], total["token_bilinen"], total["is_sayisi"]), (182400, 1, 2))
        self.assertEqual(jobs.load(self.vault, name).meta["harcanan_token"], "182400")
        summary = self.read("Ozet.md")
        self.assertIn("| Toplam token | Ort. token | Doğrulanmış iş başına token |", summary)
        self.assertIn("| 182400 | 182400 | — |", summary)
        self.assertIn("| — | — | — |", summary)  # the old row's group: unknown, never "0"
        self.assertEqual(total["token_bilinmeyen"], 1)

    def test_token_counterparts_of_the_dollar_metrics(self):
        a = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        b = self.finished(status="tikandi", kontrol_deneme="2", kontrol_sonuc="kaldi", bitis="2026-11-10T19:38:20")
        c = self.finished(katman="kolay", model="haiku", effort="low")
        self.usages.update({a: budget.Usage(1.0, 5, 0, "x", tokens=100000), b: budget.Usage(3.0, 9, 0, "x", tokens=300001),
                            c: budget.Usage(0.01, 2, 0, "x", tokens=900)})
        self.process()
        q = karne.quality(self.vault)
        kod = next(r for r in q["satirlar"] if r["katman"] == "kod")
        # verified tokens per job: every token of the row's jobs / the jobs bitti with a passed Kontrol (same rule as $)
        self.assertEqual((kod["toplam_token"], kod["ort_token"], kod["dogrulanmis_is_basina_token"], kod["token_bilinmeyen"]),
                         (400001, 200000, 400001, 0))
        kolay = next(r for r in q["satirlar"] if r["katman"] == "kolay")
        self.assertEqual((kolay["ort_token"], kolay["dogrulanmis_is_basina_token"]), (900, None))  # nothing verified
        total = q["toplam"]
        self.assertEqual((total["toplam_token"], total["ort_token"], total["dogrulanmis_is_basina_token"]),
                         (400901, 133634, 400901))
        summary = self.read("Ozet.md")
        row = next(line for line in summary.splitlines() if line.startswith("| blog | kod |"))
        self.assertTrue(row.endswith("| 400001 | 200000 | 400001 |"), row)
        row = next(line for line in summary.splitlines() if line.startswith("| blog | kolay |"))
        self.assertTrue(row.endswith("| 900 | 900 | — |"), row)

    def test_unknown_tokens_are_never_zero_in_the_token_metrics(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        head = "| " + " | ".join(karne.COLUMNS[:17]) + " |\n|" + "---|" * 17 + "\n"
        old_row = ("| 2026-11-09 | blog | [[eski-is]] | kod | opus | high | evet | 1 | hayır | 2 | 0.5000 | 0.5000 | 3 "
                   "| bitti | 0 |  |  |\n")
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# Karne kayıtları — 2026-11\n\n" + head + old_row)
        total = karne.quality(self.vault)["toplam"]
        self.assertEqual((total["toplam_token"], total["ort_token"], total["dogrulanmis_is_basina_token"],
                          total["token_bilinen"], total["token_bilinmeyen"]), (None, None, None, 0, 1))
        name = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")  # same project × tier × worker as the old row
        self.usages[name] = budget.Usage(0.5, 4, 0, "x", tokens=182400)
        self.process()
        row = next(line for line in self.read("Ozet.md").splitlines() if line.startswith("| blog | kod |"))
        # one of the two jobs has no count: the known sum with how many are missing; verified tokens per job divide
        # only by the verified jobs that have a count, so the old row does not pull it down
        self.assertTrue(row.endswith("| 182400 (1 işte kayıtlı değil) | 182400 | 182400 |"), row)

    # --- phase 5: counter metrics and the correction log ---

    def test_the_summary_has_the_counter_metrics(self):
        a = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        b = self.finished(status="tikandi", kontrol_deneme="2", kontrol_sonuc="kaldi", bitis="2026-11-10T19:38:20")
        self.usages.update({a: budget.Usage(1.0, 5, 0, "x"), b: budget.Usage(3.0, 9, 0, "x")})
        self.process()
        summary = self.read("Ozet.md")
        for column in ("Yeniden iş oranı", "Doğrulanmış iş başına API karşılığı ($)", "Ort. süre (dk)"):
            self.assertIn(column, summary)
        # rework: b's Kontrol failed; verified cost per job = all spending (4.0) / jobs bitti with a passed Kontrol (1)
        self.assertIn("| blog | kod | Kıdemli (opus) | 2 | %50 (1/2) | %50 (1/2) | 2.0000 | 1.0000 | 4.0000 | %50 (1/2) | "
                      "4.0000 | 45 |", summary)

    def test_a_correction_counts_as_rework_and_no_verified_job_shows_a_dash(self):
        a = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        b = self.finished(status="tikandi", katman="genel", model="sonnet", effort="medium")
        karne.record_correction(self.vault, "blog", a, "inceleme-duzelt", "MAJOR: boş parola", "k-1", NOW)
        karne.record_correction(self.vault, "blog", b, "onay-degil", "Şunu da ekle", "k-2", NOW)
        self.usages.update({a: budget.Usage(1.0, 5, 0, "x"), b: budget.Usage(0.5, 2, 0, "x")})
        self.process()
        summary = self.read("Ozet.md")
        self.assertIn("| blog | kod | Kıdemli (opus) | 1 | %100 (1/1) | %100 (1/1) | 1.0000 | 1.0000 | 1.0000 | %100 (1/1) | "
                      "1.0000 | 30 |", summary)
        row = next(line for line in summary.splitlines() if line.startswith("| blog | genel |"))
        self.assertIn("| %0 (0/1) | — |", row)  # onay-degil is not rework; nothing verified

    def test_the_summary_never_writes_a_placeholder_inside_a_wikilink(self):
        self.finished()
        self.process()
        summary = self.read("Ozet.md")
        self.assertNotIn("…]]", summary)
        self.assertNotIn("[[Duzeltmeler-", summary)

    def test_the_correction_log_is_appended_once_per_key_and_cannot_break_the_table(self):
        name = self.finished()
        text = "satır 1 | pipe\nsatır 2 <b>x</b> [[link]] [[[Kararlar/x]]] " + "y" * 400
        self.assertTrue(karne.record_correction(self.vault, "blog", name, "kontrol-basarisiz", text, "k-1", NOW))
        self.assertFalse(karne.record_correction(self.vault, "blog", name, "kontrol-basarisiz", text, "k-1", NOW))
        body = self.read("Duzeltmeler-blog.md")
        rows = [line for line in body.splitlines() if line.startswith("| 2026")]
        self.assertEqual(len(rows), 1)
        self.assertIn("sunucu", body.lower())
        row = rows[0]
        self.assertEqual(row.count(" | "), 4, row)  # five cells: the excerpt's pipe is escaped
        self.assertIn("\\|", row)
        self.assertNotIn("<b>", row)
        self.assertNotIn("[[", row.split(" | ")[3])
        self.assertNotIn("]]", row.split(" | ")[3])
        cells = karne.corrections(self.vault, "blog")
        self.assertEqual(len(cells), 1)
        self.assertEqual((cells[0]["is"], cells[0]["tur"], cells[0]["kimlik"]), (jobs.stem(name), "kontrol-basarisiz", "k-1"))
        self.assertLessEqual(len(cells[0]["alinti"]), karne.EXCERPT_MAX + 10)  # quotes + escapes

    def test_unknown_kinds_and_bad_project_names_are_refused(self):
        name = self.finished()
        with self.assertRaises(ValueError):
            karne.record_correction(self.vault, "blog", name, "baska", "x", "k", NOW)
        with self.assertRaises(ValueError):
            karne.record_correction(self.vault, "../x", name, "devam", "x", "k", NOW)

    # --- phase 7: the page's Kalite panel reads the same numbers as Ozet.md, as data ---

    def test_the_quality_data_has_the_summary_numbers_per_row_per_model_and_in_total(self):
        a = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        b = self.finished(status="tikandi", kontrol_deneme="2", kontrol_sonuc="kaldi", bitis="2026-11-10T19:38:20")
        c = self.finished(katman="kolay", model="haiku", effort="low")
        self.usages.update({a: budget.Usage(1.0, 5, 0, "x"), b: budget.Usage(3.0, 9, 0, "x"),
                            c: budget.Usage(0.0111, 2, 0, "x")})
        self.process()
        q = karne.quality(self.vault)
        self.assertEqual(q["is_sayisi"], 3)
        rows = {(r["katman"], r["model"]): r for r in q["satirlar"]}
        self.assertEqual(rows[("kod", "opus")],
                         {"proje": "blog", "katman": "kod", "model": "opus", "is_sayisi": 2, "bitti": 1,
                          "ilk_tur_gecen": 1, "ilk_tur_olculen": 2, "yeniden_is": 1, "dogrulanan": 1,
                          "toplam_usd": 4.0, "ort_usd": 2.0, "ort_dogrulanmis_usd": 1.0,
                          "dogrulanmis_is_basina_usd": 4.0, "ort_sure_dk": 45, "toplam_token": 0, "token_bilinen": 2,
                          "token_bilinmeyen": 0, "ort_token": 0, "dogrulanmis_is_basina_token": 0})
        kolay = rows[("kolay", "haiku")]
        # a small amount keeps its digits; no passed Kontrol -> no verified cost per job (None, never 0)
        self.assertEqual((kolay["ort_usd"], kolay["dogrulanmis_is_basina_usd"], kolay["ilk_tur_olculen"]),
                         (0.0111, None, 0))
        self.assertEqual([m["model"] for m in q["modeller"]], ["haiku", "opus"])
        self.assertNotIn("proje", q["modeller"][0])
        total = q["toplam"]
        self.assertEqual((total["is_sayisi"], total["toplam_usd"], total["dogrulanan"]), (3, 4.0111, 1))
        self.assertEqual(total["dogrulanmis_is_basina_usd"], 4.0111)
        # the generated summary still shows the same row
        self.assertIn("| blog | kod | Kıdemli (opus) | 2 | %50 (1/2) | %50 (1/2) | 2.0000 | 1.0000 | 4.0000 | %50 (1/2) | "
                      "4.0000 | 45 |", self.read("Ozet.md"))

    def test_quality_of_an_empty_scorecard(self):
        self.assertEqual(karne.quality(self.vault), {"satirlar": [], "modeller": [], "uzmanliklar": [], "toplam": None,
                                                     "is_sayisi": 0, "deneme_sayisi": 0, "deneme_isler": []})

    # --- self-test jobs (deneme, owner decision 2026-11-12) ---

    def test_a_deneme_row_is_marked_and_left_out_of_the_numbers(self):
        trial = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti")
        real = self.finished(status="tikandi", kontrol_deneme="2", kontrol_sonuc="kaldi", bitis="2026-11-10T19:38:20")
        forged = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti", bitis="2026-11-10T19:40:00", deneme="evet")
        self.usages.update({trial: budget.Usage(1.0, 5, 0, "x"), real: budget.Usage(3.0, 9, 0, "x"),
                            forged: budget.Usage(2.0, 9, 0, "x")})
        recs = {trial: {"deneme": "evet"}, real: {"deneme": ""}, forged: {"deneme": ""}}
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, record_of=lambda job: recs[job.name])
        cells = {r["İş"]: r["Deneme"] for r in karne._rows(self.vault)}
        self.assertEqual(cells, {f"[[{jobs.stem(trial)}]]": "evet", f"[[{jobs.stem(real)}]]": "",
                                 f"[[{jobs.stem(forged)}]]": ""}, "the record decides, never the note")
        q = karne.quality(self.vault)
        self.assertEqual((q["is_sayisi"], q["deneme_sayisi"], q["deneme_isler"]), (2, 1, [jobs.stem(trial)]))
        self.assertEqual((q["toplam"]["toplam_usd"], q["toplam"]["dogrulanan"]), (5.0, 1))
        summary = self.read("Ozet.md")
        self.assertIn("toplam 2 iş", summary)
        self.assertIn(f"Deneme işleri (sayılmadı): 1 — [[{jobs.stem(trial)}]]", summary)
        self.assertIn("| blog | kod | Kıdemli (opus) | 2 |", summary)
        self.assertEqual(len(karne.counted(karne._rows(self.vault))), 2)

    def test_deneme_comes_only_from_the_record_never_from_the_note(self):
        # review 2026-11-12: an old record has no deneme key; a session writing `deneme: evet` into its own note must
        # not hide its failed job
        no_key = self.finished(status="tikandi", deneme="evet")
        no_record = self.finished(status="tikandi", deneme="evet", bitis="2026-11-10T19:40:00")
        recs = {no_key: {"katman": "kod"}, no_record: None}
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, record_of=lambda job: recs[job.name])
        self.assertEqual([r["Deneme"] for r in karne._rows(self.vault)], ["", ""])
        self.assertEqual(karne.quality(self.vault)["is_sayisi"], 2)

    def test_a_file_from_before_the_deneme_column_is_upgraded(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        head = "| " + " | ".join(karne.COLUMNS[:18]) + " |\n|" + "---|" * 18 + "\n"
        old_row = ("| 2026-11-09 | blog | [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.0100 |  | 0 "
                   "| tikandi | 1 |  |  | 120 |\n")
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# Karne kayıtları — 2026-11\n\n" + head + old_row)
        [old] = karne._rows(self.vault)
        self.assertEqual((old["Token"], old["Deneme"]), ("120", ""))
        self.assertEqual(karne.mark_trial(self.vault, "eski-is.md"), "isaretlendi")
        text = self.read("Kayitlar-2026-11.md")
        self.assertIn(" | Token | Deneme | Uzmanlık |\n|" + "---|" * 20 + "\n", text)
        self.assertIn("| tikandi | 1 |  |  | 120 | evet |  |", text)
        self.assertEqual(karne.mark_trial(self.vault, "eski-is.md"), "zaten")
        self.assertEqual(karne.mark_trial(self.vault, "yok.md"), "satir-yok")
        self.assertEqual(karne.quality(self.vault)["is_sayisi"], 0)

    # --- specialisation (plan "Sonraki iş (9)" step 2) ---

    def test_the_row_carries_the_specialisation_of_the_record(self):
        a = self.finished(kontrol_deneme="1", kontrol_sonuc="gecti", uzmanlik="guvenlik")  # a note's value: ignored
        b = self.finished(kontrol_deneme="2", kontrol_sonuc="kaldi", status="tikandi", bitis="2026-11-10T19:38:20")
        c = self.finished(katman="kolay", model="haiku", effort="low", bitis="2026-11-10T19:40:00")
        self.usages.update({a: budget.Usage(1.0, 5, 0, "x"), b: budget.Usage(3.0, 9, 0, "x"),
                            c: budget.Usage(0.5, 2, 0, "x")})
        recs = {a: {"uzmanlik": "mobil"}, b: {"uzmanlik": "mobil"}, c: None}
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW, record_of=lambda job: recs[job.name])
        cells = {r["İş"]: r["Uzmanlık"] for r in karne._rows(self.vault)}
        self.assertEqual(cells, {f"[[{jobs.stem(a)}]]": "mobil", f"[[{jobs.stem(b)}]]": "mobil",
                                 f"[[{jobs.stem(c)}]]": ""})
        q = karne.quality(self.vault)
        by = {u["uzmanlik"]: u for u in q["uzmanliklar"]}
        self.assertEqual(set(by), {"mobil", ""})
        self.assertEqual((by["mobil"]["is_sayisi"], by["mobil"]["bitti"], by["mobil"]["toplam_usd"]), (2, 1, 4.0))
        self.assertEqual(by["mobil"]["dogrulanmis_is_basina_usd"], 4.0)
        summary = self.read("Ozet.md")
        self.assertIn("## Uzmanlığa göre", summary)
        self.assertIn("| Mobil | 2 | %50 (1/2) |", summary)
        self.assertIn("| — (kayıtlı değil) | 1 |", summary)
        # the existing project × tier × model table stays
        self.assertIn("| blog | kod | Kıdemli (opus) | 2 |", summary)

    def test_a_file_from_before_the_uzmanlik_column_is_upgraded(self):
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        head = "| " + " | ".join(karne.COLUMNS[:19]) + " |\n|" + "---|" * 19 + "\n"
        old_row = ("| 2026-11-09 | blog | [[eski-is]] | kolay | haiku | low | yok | 0 | hayır | 2 | 0.0100 |  | 0 "
                   "| tikandi | 1 |  |  | 120 |  |\n")
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("# Karne kayıtları — 2026-11\n\n" + head + old_row)
        [old] = karne._rows(self.vault)
        self.assertEqual((old["Deneme"], old["Uzmanlık"]), ("", ""))
        self.assertEqual(karne.mark_trial(self.vault, "eski-is.md"), "isaretlendi")
        text = self.read("Kayitlar-2026-11.md")
        self.assertIn(" | Deneme | Uzmanlık |\n|" + "---|" * 20 + "\n", text)
        self.assertIn("| 120 | evet |  |", text)
        new = self.finished(bitis="2026-11-10T19:40:00")
        karne.process_pending(self.vault, self.usage_of, now=lambda: NOW,
                              record_of=lambda job: {"uzmanlik": "backend"})
        self.assertTrue(self.rows()[-1].endswith("|  | backend |"), self.rows()[-1])
        self.assertEqual(karne.mark_trial(self.vault, "eski-is.md"), "zaten")


if __name__ == "__main__":
    unittest.main()
