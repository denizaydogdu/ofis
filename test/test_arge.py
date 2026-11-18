"""Tests for bin/arge.py: the Ar-Ge odası's free daily check (the `opencode models` diff and the CLI versions, no model
call) and the Ar-Ge report note OFIS/ArGe/ArGe-YYYY-MM-DD.md with its reviewer-suggestion cards (plan "Sonraki iş (6)",
owner decision 2026-11-12)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401 (isolates the job lock)
import arge  # noqa: E402
import jobs  # noqa: E402
import records  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
ROOT = os.path.join(HERE, "..")


def at(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ)


MODELS_1 = """opencode/big-pickle
opencode/glm-5.3-flash-free
opencode/iceman-free
opencode/deepseek-v4.1-flash-free
openai/gpt-6-sol
openrouter/cohere/north-mini-code:free
"""
MODELS_2 = """opencode/big-pickle
opencode/glm-5.4-flash-free
opencode/deepseek-v4.1-flash-free
opencode/beam-free
openai/gpt-6-sol
openai/gpt-6.1-sol
openrouter/cohere/north-mini-code:free
"""


class FakeRunner:
    """Records every call; answers from a table {program base name + args: (code, stdout) | exception}."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        key = " ".join([os.path.basename(argv[0])] + list(argv[1:]))
        value = self.answers.get(key)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise FileNotFoundError(argv[0])
        return value


def which_all(name):
    return f"/fake/bin/{name}"


class FakeCeo:
    """Dedupes by key like the real queue; `fail` = how many enqueue calls raise first."""

    def __init__(self, fail=0):
        self.sent = []
        self.fail = fail

    def enqueue(self, text, key):
        if self.fail:
            self.fail -= 1
            raise OSError("queue not writable")
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.durum = os.path.join(self.tmp.name, "durum")
        self.vault = os.path.join(self.tmp.name, "vault", "OFIS")
        os.makedirs(self.vault)
        self.cfg = {"vault_ofis": self.vault, "ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"}, "projects": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def answers(self, models=MODELS_1, claude="2.1.322 (Claude Code)", codex="codex-cli 0.167.0",
                opencode="opencode v2.0.32"):
        return {"opencode models --standalone": (0, models), "claude --version": (0, claude + "\n"),
                "codex --version": (0, codex + "\n"), "opencode --version": (0, opencode + "\n")}

    def checker(self, runner, now, mesgul=None, which=which_all):
        return arge.GunlukKontrol(lambda: self.cfg, self.durum, runner=runner, now=lambda: now, mesgul=mesgul,
                                  which=which)

    def read(self, *parts):
        with open(os.path.join(self.durum, "arge", *parts), encoding="utf-8") as f:
            return json.load(f)


class FreeModelsTest(Base):
    def test_free_models_are_the_free_suffixes_and_the_stealth_names(self):
        self.assertTrue(arge.ucretsiz_mi("opencode/glm-5.3-flash-free"))
        self.assertTrue(arge.ucretsiz_mi("openrouter/cohere/north-mini-code:free"))
        self.assertTrue(arge.ucretsiz_mi("opencode/big-pickle"))  # "big-pickle style": opencode's own, no version
        self.assertFalse(arge.ucretsiz_mi("openai/gpt-6-sol"))
        self.assertFalse(arge.ucretsiz_mi("openrouter/~anthropic/claude-sonnet-latest"))
        self.assertFalse(arge.ucretsiz_mi("opencode/gpt-6-sol"))  # opencode's paid ones carry a version

    def test_the_model_list_keeps_only_model_names(self):
        text = "opencode/a-free\n\n  openai/b \nnot a model name with spaces\n\x1b[31mopencode/c-free\x1b[0m\n" + \
            "x" * 300 + "\nopencode/a-free\n"
        self.assertEqual(arge.modelleri_ayikla(text), ["openai/b", "opencode/a-free", "opencode/c-free"])

    def test_the_diff_finds_new_removed_and_renamed_free_models(self):
        old = arge.ucretsizler(arge.modelleri_ayikla(MODELS_1))
        new = arge.ucretsizler(arge.modelleri_ayikla(MODELS_2))
        f = arge.model_farki(old, new)
        self.assertEqual(f["yeni"], ["opencode/beam-free"])
        self.assertEqual(f["kalkan"], ["opencode/iceman-free"])
        self.assertEqual(f["ad_degisen"], [["opencode/glm-5.3-flash-free", "opencode/glm-5.4-flash-free"]])

    def test_a_rename_needs_one_to_one_pairs(self):
        f = arge.model_farki(["opencode/x-1-free"], ["opencode/x-2-free", "opencode/x-3-free"])
        self.assertEqual(f["ad_degisen"], [])
        self.assertEqual(f["yeni"], ["opencode/x-2-free", "opencode/x-3-free"])
        self.assertEqual(f["kalkan"], ["opencode/x-1-free"])


class DailyCheckTest(Base):
    def test_the_first_day_is_the_baseline_and_runs_every_call_with_a_short_timeout(self):
        runner = FakeRunner(self.answers())
        self.assertEqual(self.checker(runner, at(12, 0, 5)).kontrol(), "2026-11-12")
        self.assertEqual(sorted(" ".join([os.path.basename(c[0][0])] + c[0][1:]) for c in runner.calls),
                         ["claude --version", "codex --version", "opencode --version", "opencode models --standalone"])
        self.assertTrue(all(0 < c[1] <= 10 for c in runner.calls))
        day = self.read("gunler", "2026-11-12.json")
        self.assertEqual(day["surumler"], {"claude": "2.1.322 (Claude Code)", "codex": "codex-cli 0.167.0",
                                           "opencode": "opencode v2.0.32"})
        self.assertIn("opencode/big-pickle", day["ucretsiz"])
        self.assertNotIn("openai/gpt-6-sol", day["ucretsiz"])
        self.assertIn("openai/gpt-6-sol", day["modeller"])
        fark = self.read("son_fark.json")
        self.assertEqual(fark["gun"], "2026-11-12")
        self.assertEqual(fark["modeller"]["durum"], "ilk")
        self.assertEqual(fark["surumler"], [])

    def test_it_runs_once_a_day_and_diffs_against_the_previous_day(self):
        self.checker(FakeRunner(self.answers()), at(11, 9)).kontrol()
        again = FakeRunner(self.answers())
        self.assertIsNone(self.checker(again, at(11, 23)).kontrol())
        self.assertEqual(again.calls, [])
        runner = FakeRunner(self.answers(models=MODELS_2, codex="codex-cli 0.168.0"))
        self.assertEqual(self.checker(runner, at(12, 0, 1)).kontrol(), "2026-11-12")
        fark = self.read("son_fark.json")
        self.assertEqual((fark["onceki_gun"], fark["modeller"]["durum"]), ("2026-11-11", "tamam"))
        self.assertEqual(fark["modeller"]["yeni"], ["opencode/beam-free"])
        self.assertEqual(fark["modeller"]["kalkan"], ["opencode/iceman-free"])
        self.assertEqual(fark["modeller"]["ad_degisen"], [["opencode/glm-5.3-flash-free", "opencode/glm-5.4-flash-free"]])
        self.assertEqual(fark["surumler"], [{"arac": "codex", "onceki": "codex-cli 0.167.0", "simdi": "codex-cli 0.168.0"}])
        self.assertTrue(fark["degisiklik"])
        # the day file keeps the day's diff too (the Ar-Ge note reads it)
        self.assertEqual(self.read("gunler", "2026-11-12.json")["fark"]["modeller"]["yeni"], ["opencode/beam-free"])

    def test_a_missing_tool_is_bilinmiyor_and_never_counts_as_all_models_removed(self):
        self.checker(FakeRunner(self.answers()), at(11, 9)).kontrol()
        answers = self.answers()
        del answers["opencode models --standalone"], answers["opencode --version"]
        self.checker(FakeRunner(answers), at(12, 9), which=lambda n: None if n == "opencode" else which_all(n)).kontrol()
        day = self.read("gunler", "2026-11-12.json")
        self.assertIsNone(day["modeller"])
        self.assertEqual(day["surumler"]["opencode"], "bilinmiyor")
        fark = self.read("son_fark.json")
        self.assertEqual(fark["modeller"]["durum"], "bilinmiyor")
        self.assertEqual(fark["modeller"]["kalkan"], [])
        self.assertEqual(fark["surumler"], [])  # an unknown version is no change
        # the next day compares with the last day whose list was known
        self.checker(FakeRunner(self.answers(models=MODELS_2)), at(13, 9)).kontrol()
        fark = self.read("son_fark.json")
        self.assertEqual((fark["onceki_gun"], fark["modeller"]["durum"]), ("2026-11-11", "tamam"))

    def test_a_timeout_or_a_failure_is_bilinmiyor(self):
        answers = self.answers()
        answers["codex --version"] = subprocess.TimeoutExpired("codex", 10)
        answers["claude --version"] = (1, "")
        self.checker(FakeRunner(answers), at(12, 9)).kontrol()
        day = self.read("gunler", "2026-11-12.json")
        self.assertEqual((day["surumler"]["codex"], day["surumler"]["claude"]), ("bilinmiyor", "bilinmiyor"))

    def test_it_waits_while_heavy_work_runs(self):
        runner = FakeRunner(self.answers())
        busy = [True]
        c = self.checker(runner, at(12, 9), mesgul=lambda: busy[0])
        self.assertIsNone(c.kontrol())
        self.assertEqual(runner.calls, [])
        busy[0] = False
        self.assertEqual(c.kontrol(), "2026-11-12")

    def test_the_configured_binaries_are_used(self):
        self.cfg["codex_bin"] = "/opt/codex/bin/codex"
        self.cfg["opencode_bin"] = "/opt/oc/opencode"
        runner = FakeRunner(self.answers())
        self.checker(runner, at(12, 9)).kontrol()
        progs = {c[0][0] for c in runner.calls}
        self.assertIn("/opt/codex/bin/codex", progs)
        self.assertIn("/opt/oc/opencode", progs)

    def test_a_version_line_is_one_short_clean_line(self):
        answers = self.answers(claude="2.1.322 (Claude Code)\x1b[0m\nsecond line" + "y" * 200)
        self.checker(FakeRunner(answers), at(12, 9)).kontrol()
        self.assertEqual(self.read("gunler", "2026-11-12.json")["surumler"]["claude"], "2.1.322 (Claude Code)")

    def test_old_days_are_pruned(self):
        for d in range(1, 13):
            self.checker(FakeRunner(self.answers()), at(d, 9)).kontrol()
        folder = os.path.join(self.durum, "arge", "gunler")
        self.assertEqual(len(os.listdir(folder)), 12)
        old = arge.KEEP_DAYS
        try:
            arge.KEEP_DAYS = 5
            self.checker(FakeRunner(self.answers()), at(13, 9)).kontrol()
        finally:
            arge.KEEP_DAYS = old
        self.assertEqual(sorted(os.listdir(folder))[0], "2026-11-09.json")
        self.assertEqual(len(os.listdir(folder)), 5)

    def test_the_real_runner_kills_a_slow_command(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            arge.calistir([sys.executable, "-c", "import time; time.sleep(5)"], 0.3)
        self.assertEqual(arge.calistir([sys.executable, "-c", "print('ok')"], 5), (0, "ok\n"))


REPORT = """Bugünün Ar-Ge raporu.
> [!success] yeni bir model
Kaynak: https://example.org/haber

ÖNERİ-DENETÇİ: opencode/beam-free | MIT | ücretsiz ve kod incelemesinde iyi (kaynak: https://example.org/b)
- **Öneri-Denetçi:** openrouter/cohere/north-mini-code:free | CC-BY-NC 4.0 | Türkçe destekli
ONERI-DENETCI: opencode/lisanssiz-free |  | lisansı yok
ÖNERİ-DENETÇİ: bu bir model adı değil | MIT | x
"""


class ReportTest(Base):
    def setUp(self):
        super().setUp()
        self.job = "2026-11-12-090000-arge.md"
        fakes.write_note(os.path.join(self.vault, "Isler", "Bitenler"), self.job,
                         {"proje": "arge", "durum": "bitti", "baslik": "Günlük Ar-Ge"}, "## Hedef\n\nx\n")

    def write(self, text=REPORT, job=None, now=None, ceo=None):
        """The two steps: the inbox keeps the report, the background writer writes (and tells) it."""
        now = now or at(12, 9, 40)
        rid = arge.bekleyen_kaydet(self.durum, job or self.job, "Günlük Ar-Ge", text, now)
        return arge.yaz_ve_bildir(self.cfg, self.durum, rid, now=now, ceo=ceo)

    def note_text(self, gun="2026-11-12"):
        with open(os.path.join(self.vault, "ArGe", f"ArGe-{gun}.md"), encoding="utf-8") as f:
            return f.read()

    def cards(self):
        folder = os.path.join(self.vault, "Kararlar")
        out = []
        for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                out.append((n, f.read()))
        return out

    def test_the_note_quotes_the_report_as_data_without_callouts(self):
        r = self.write()
        self.assertEqual(r["not"], "ArGe-2026-11-12")
        text = self.note_text()
        self.assertIn("tur: arge-raporu", text)
        self.assertIn("> Bugünün Ar-Ge raporu.", text)
        self.assertIn("> \\[!success] yeni bir model", text)
        self.assertNotIn("> [!success]", text)
        self.assertIn("[[2026-11-12-090000-arge]]", text)
        # never the morning summary's name (OFIS/Ozetler/YYYY-MM-DD.md): a bare link must find this note only
        self.assertEqual(os.listdir(os.path.join(self.vault, "ArGe")), ["ArGe-2026-11-12.md"])

    def test_the_note_carries_the_days_free_check(self):
        self.checker(FakeRunner(self.answers()), at(11, 9)).kontrol()
        self.checker(FakeRunner(self.answers(models=MODELS_2)), at(12, 0, 5)).kontrol()
        self.write()
        text = self.note_text()
        self.assertIn("## Ücretsiz günlük kontrol", text)
        self.assertIn("opencode/beam-free", text)
        self.assertIn("opencode/glm-5.3-flash-free → opencode/glm-5.4-flash-free", text)

    def test_the_first_day_records_the_versions_instead_of_claiming_no_change(self):
        self.checker(FakeRunner(self.answers()), at(12, 0, 5)).kontrol()
        text = arge.fark_metni(arge.son_fark(self.durum))
        self.assertIn("Sürümler kaydedildi: claude 2.1.322 (Claude Code) · codex codex-cli 0.167.0", text)
        self.assertNotIn("değişmedi", text)
        self.checker(FakeRunner(self.answers()), at(13, 0, 5)).kontrol()
        self.assertIn("Sürümler değişmedi (claude", arge.fark_metni(arge.son_fark(self.durum)))

    def test_without_a_free_check_the_note_says_so(self):
        self.write()
        self.assertIn("Bugünün ücretsiz kontrolü henüz yok", self.note_text())

    def test_reviewer_suggestions_become_cards_only_with_a_model_and_a_license(self):
        r = self.write()
        self.assertEqual([o["model"] for o in r["oneriler"]],
                         ["opencode/beam-free", "openrouter/cohere/north-mini-code:free", "opencode/lisanssiz-free"])
        self.assertEqual(len(r["kartlar"]), 2)
        cards = self.cards()
        self.assertEqual(len(cards), 2)
        name, text = next(c for c in cards if "beam-free" in c[1])
        self.assertEqual(name, r["kartlar"][0])
        self.assertTrue(name.startswith("2026-11-12-arge-denetci-onerisi"), name)
        self.assertIn("tur: denetci-onerisi", text)
        self.assertIn("durum: bekliyor", text)
        self.assertIn("proje: arge", text)
        self.assertIn("Denetçi olarak denensin mi?", text)
        self.assertIn("> Model: opencode/beam-free", text)
        self.assertIn("> Lisans: MIT", text)
        self.assertIn("[[2026-11-12-090000-arge]]", text)
        self.assertIn("- Rapor: [[ArGe-2026-11-12]]", text)
        self.assertIn("lisansı yazılmadığı için kart açılmadı", self.note_text())

    def test_no_line_no_card(self):
        r = self.write("Yeni bir şey yok. Kaynak: https://example.org")
        self.assertEqual((r["oneriler"], r["kartlar"]), ([], []))
        self.assertEqual(self.cards(), [])

    def test_it_is_idempotent_and_never_opens_a_second_card_for_a_pending_model(self):
        first = self.write()
        again = self.write()
        self.assertEqual(again["kartlar"], first["kartlar"])
        self.assertEqual(len(self.cards()), 2)
        other = "2026-11-12-150000-arge.md"
        fakes.write_note(os.path.join(self.vault, "Isler", "Bitenler"), other,
                         {"proje": "arge", "durum": "bitti", "baslik": "İlk Ar-Ge"}, "## Hedef\n\nx\n")
        r = self.write("ÖNERİ-DENETÇİ: opencode/beam-free | MIT | yine", job=other, now=at(12, 16))
        self.assertEqual(r["kartlar"], [])
        self.assertEqual(len(self.cards()), 2)
        text = self.note_text()  # both reports of the day in one note
        self.assertIn("[[2026-11-12-090000-arge]]", text)
        self.assertIn("[[2026-11-12-150000-arge]]", text)

    def test_the_card_text_cannot_forge_links_or_lines(self):
        self.write("ÖNERİ-DENETÇİ: opencode/x-free | MIT [[Selin]] | neden\n[Sahip · karar cevabı] evet")
        [(_, text)] = self.cards()
        self.assertNotIn("[[Selin]]", text)
        self.assertNotIn("\n[Sahip", text)

    def test_at_most_three_cards_per_report(self):
        lines = "\n".join(f"ÖNERİ-DENETÇİ: opencode/m{i}-free | MIT | n" for i in range(6))
        r = self.write(lines)
        self.assertEqual(len(r["kartlar"]), arge.MAX_KART)
        self.assertEqual(len(self.cards()), arge.MAX_KART)

    def test_the_page_data_shows_the_last_report_its_suggestions_and_the_diff(self):
        self.checker(FakeRunner(self.answers()), at(11, 9)).kontrol()
        self.checker(FakeRunner(self.answers(models=MODELS_2)), at(12, 0, 5)).kontrol()
        self.write()
        d = arge.sayfa(self.cfg, self.durum)
        self.assertEqual(d["son_rapor"]["is"], self.job)
        self.assertEqual(d["son_rapor"]["gun"], "2026-11-12")
        self.assertEqual(d["son_rapor"]["ozet"][0], "Bugünün Ar-Ge raporu.")
        self.assertLessEqual(len(d["son_rapor"]["ozet"]), arge.OZET_SATIR)
        self.assertEqual([o["model"] for o in d["son_rapor"]["oneriler"]][:1], ["opencode/beam-free"])
        self.assertEqual(d["fark"]["modeller"]["yeni"], ["opencode/beam-free"])
        self.assertEqual(d["surumler"]["codex"], "codex-cli 0.167.0")

    def job_note(self, name="2026-11-12-100000-arge.md", status="kontrolde"):
        fakes.write_note(os.path.join(self.vault, "Isler", "Devam-Edenler"), name,
                         {"proje": "arge", "durum": status, "baslik": "Ar-Ge"}, "## Hedef\n\nx\n")
        if status == "bitti":
            records.update(self.durum, name, {"kontrol_sonuc": "yok"})  # done without a Kontrol
        return name

    def bitti(self, job, sonuc="gecti"):
        """The job is done: the note's status and the server record's Kontrol result (as kontrol.py mirrors it)."""
        records.update(self.durum, job, {"kontrol_sonuc": sonuc})
        jobs.update(self.vault, job, status="bitti")

    def pas(self, ceo, now=None, n=2):
        """The background writer's pass, run n times (it must be idempotent)."""
        for _ in range(n):
            arge.bekleyenleri_yaz(self.cfg, self.durum, now=lambda: now or at(12, 13), ceo=ceo)

    def assert_once(self, ceo, text, model="opencode/b-free"):
        """Exactly one note quoting `text`, one card for `model`, one notice."""
        self.assertEqual(self.note_text().count(f"> {text}"), 1)
        cards = [c for c in self.cards() if f"> Model: {model}" in c[1]]
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(self.cards()), 1)
        self.assertEqual(len(ceo.sent), 1, ceo.sent)
        notice, key = ceo.sent[0]
        self.assertTrue(key.startswith("arge-"))
        self.assertIn("[[ArGe-2026-11-12]]", notice)
        self.assertIn(f"[[{cards[0][0][:-3]}]]", notice)

    SECOND = "İkinci metin.\nÖNERİ-DENETÇİ: opencode/b-free | MIT | y"

    def test_no_kontrol_one_note_one_card_one_notice(self):
        ceo = FakeCeo()
        job = self.job_note(status="bitti")
        arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 10))
        self.pas(ceo, n=3)
        self.assert_once(ceo, "İkinci metin.")

    def test_kontrol_passes_one_note_one_card_one_notice(self):
        ceo = FakeCeo()
        job = self.job_note()
        arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 10))
        self.pas(ceo)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "ArGe")))  # nothing while the Kontrol runs
        self.assertEqual(ceo.sent, [])
        self.bitti(job)
        self.pas(ceo)
        self.assert_once(ceo, "İkinci metin.")

    def test_kontrol_fails_then_resume_then_pass_writes_only_the_second_report(self):
        ceo = FakeCeo()
        job = self.job_note()
        arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", "İlk metin.\nÖNERİ-DENETÇİ: opencode/a-free | MIT | x", at(12, 10))
        jobs.update(self.vault, job, status="calisiyor")  # the Kontrol failed: the job goes on
        self.pas(ceo)
        jobs.update(self.vault, job, status="tikandi")  # failed twice; later the owner says devam
        self.pas(ceo)
        jobs.update(self.vault, job, status="calisiyor")
        self.assertFalse(os.path.exists(os.path.join(self.vault, "ArGe")))
        arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 12))  # the newer report replaces it
        jobs.update(self.vault, job, status="kontrolde")
        self.pas(ceo)
        self.bitti(job)  # the Kontrol passed
        self.pas(ceo)
        self.assert_once(ceo, "İkinci metin.")
        self.assertNotIn("İlk metin.", self.note_text())

    def test_a_notice_queue_failure_is_retried_without_writing_again(self):
        ceo = FakeCeo(fail=1)
        job = self.job_note(status="bitti")
        arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 10))
        self.pas(ceo, n=1)
        self.assertEqual(ceo.sent, [])  # written, not told yet
        note = os.path.join(self.vault, "ArGe", "ArGe-2026-11-12.md")
        with open(note, encoding="utf-8") as f:
            first = f.read()
        os.remove(note)  # if the retry wrote again, the note would come back
        self.pas(ceo)
        self.assertFalse(os.path.exists(note))
        with open(note, "w", encoding="utf-8") as f:
            f.write(first)
        self.assert_once(ceo, "İkinci metin.")

    def test_a_restart_between_writing_and_notifying_tells_once(self):
        job = self.job_note(status="bitti")
        rid = arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 10))
        arge.yaz_ve_bildir(self.cfg, self.durum, rid, now=at(12, 11), ceo=None)  # the server stopped right here
        ceo = FakeCeo()  # a new server
        self.pas(ceo, n=3)
        self.assert_once(ceo, "İkinci metin.")

    def test_bitir_by_hand_never_publishes_an_unproven_report(self):
        ceo = FakeCeo()
        job = self.job_note()
        arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 10))
        records.update(self.durum, job, {"kontrol_sonuc": "kaldi"})  # the Kontrol failed …
        jobs.update(self.vault, job, status="bitti")  # … and the CEO ran `bitir`
        self.pas(ceo)
        self.assertFalse(os.path.exists(os.path.join(self.vault, "ArGe")))
        self.assertEqual(ceo.sent, [])

    def test_pruning_the_done_set_never_brings_an_old_report_back(self):
        old = arge.KEEP_DAYS
        arge.KEEP_DAYS = 3
        self.addCleanup(setattr, arge, "KEEP_DAYS", old)
        ceo = FakeCeo()
        for d in range(1, 6):
            job = self.job_note(f"2026-11-0{d}-090000-arge.md", status="bitti")
            arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", f"Gün {d}.\nÖNERİ-DENETÇİ: opencode/m{d}-free | MIT | x",
                                 at(d, 9))
            self.pas(ceo, now=at(d, 10), n=3)
        self.assertEqual(len(ceo.sent), 5)  # one notice per report, none again after pruning
        self.assertEqual(len(self.cards()), 5)
        self.assertEqual(os.listdir(os.path.join(self.durum, "arge", "raporlar")), [])  # written: no pending record
        self.assertEqual(len(arge.yazilanlar(self.durum)), 3)

    def test_a_card_written_before_a_crash_is_adopted_not_doubled(self):
        ceo = FakeCeo()
        job = self.job_note(status="bitti")
        rid = arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", self.SECOND, at(12, 10))
        os.makedirs(os.path.join(self.vault, "Kararlar"))
        name = "2026-11-12-arge-denetci-onerisi.md"
        with open(os.path.join(self.vault, "Kararlar", name), "w", encoding="utf-8") as f:  # the card got out, then a crash
            f.write(arge.kart_metni({"model": "opencode/b-free", "lisans": "MIT", "neden": "y"}, "2026-11-12", job,
                                    at(12, 11)))
        self.pas(ceo)
        self.assert_once(ceo, "İkinci metin.")
        self.assertIsNotNone(rid)

    def test_the_same_report_again_changes_nothing_and_a_new_one_replaces_the_pending_one(self):
        job = self.job_note()
        r1 = arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", "Bir.", at(12, 10))
        self.assertEqual(arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", "Bir.", at(12, 11)), r1)
        r2 = arge.bekleyen_kaydet(self.durum, job, "Ar-Ge", "İki.", at(12, 12))
        self.assertNotEqual(r1, r2)
        self.assertTrue(r2.startswith("2026-11-12-100000-arge-"))  # job + text hash
        self.assertIsNone(arge.yaz_ve_bildir(self.cfg, self.durum, r1, now=at(12, 13)))  # replaced: nothing to write

    def test_the_page_data_is_empty_before_anything_ran(self):
        d = arge.sayfa(self.cfg, self.durum)
        self.assertEqual((d["son_rapor"], d["fark"]), (None, None))

    def test_a_link_in_the_ArGe_folder_is_never_written_through(self):
        target = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(target)
        os.symlink(target, os.path.join(self.vault, "ArGe"))
        with self.assertRaises(OSError):
            self.write()
        self.assertEqual(os.listdir(target), [])


class ConfigTest(unittest.TestCase):
    """The versioned settings template ofis.example.json: the arge workspace (owner decision 2026-11-12; ofis.json itself is
    personal and not versioned since the Ayarlar page)."""

    def setUp(self):
        with open(os.path.join(ROOT, "ofis.example.json"), encoding="utf-8") as f:
            self.cfg = json.load(f)

    def test_the_arge_project_is_registered_with_its_rules(self):
        p = self.cfg["projects"]["arge"]
        self.assertEqual(p["path"], "~/ofis-arge")
        self.assertTrue(p["description"])
        notes = p["notes"]
        for needle in ("read-only", "never code", "source link", "invent", "license"):
            self.assertIn(needle, notes.lower(), needle)

    def test_the_free_reviewers_never_see_arge(self):
        self.assertNotIn("arge", self.cfg.get("ucretsiz_denetci_projeler") or [])

    def test_the_arge_project_name_is_the_one_the_code_uses(self):
        self.assertIn(arge.PROJE, self.cfg["projects"])

    def test_the_kontrol_worker_knows_the_arge_project(self):
        import kontrol
        self.assertEqual(kontrol.ARGE_PROJE, arge.PROJE)

    def test_the_reviewer_card_is_answered_like_a_ceo_decision(self):
        import ofis
        self.assertIn(arge.DENETCI_ONERISI, ofis.CEO_DECISIONS)


if __name__ == "__main__":
    unittest.main()
