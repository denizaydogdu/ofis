"""Tests for bin/muhasebe.py: the Muhasebeci's numbers (GET /api/muhasebe) and the İdari işler data (GET /api/idari).
Run: python3 -I test/test_muhasebe.py"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401 (isolates the job lock)
import karne  # noqa: E402
import muhasebe  # noqa: E402

HEAD = "| " + " | ".join(karne.COLUMNS) + " |\n|" + "---|" * len(karne.COLUMNS) + "\n"


def row(day, project, stem, model, cost, tokens="", verified="", first="evet", result="bitti", tier="kod",
        uzmanlik=""):
    cells = [day, project, f"[[{stem}]]", tier, karne.worker(model), "high", first, "1", "hayır", "3", cost,
             verified, "5", result, "0", "", "", tokens, "", uzmanlik]
    return "| " + " | ".join(cells) + " |\n"


class MuhasebeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = self.tmp.name
        os.makedirs(os.path.join(self.vault, "Karne"))
        muhasebe._cache.update(key=None, rows=[], events={})

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, month, *rows):
        with open(os.path.join(self.vault, "Karne", f"Kayitlar-{month}.md"), "w", encoding="utf-8") as f:
            f.write(HEAD + "".join(rows))

    def test_day_and_month_totals_split_by_project_and_role_with_unknown_tokens_as_none(self):
        self.write("2026-11",
                   row("2026-11-12", "blog", "a", "opus", "1.2000", "400000", "1.2000"),
                   row("2026-11-12", "kasa", "b", "haiku", "0.0100", ""),
                   row("2026-11-03", "blog", "c", "sonnet", "0.5000", "1000", "0.5000", first="hayır"),
                   row("2026-11-12", "kasa", "r", "codex", "", "", tier="inceleme"))
        now = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
        out = muhasebe.ozet(self.vault, [], now=now)
        day, month = out["bugun"], out["bu_ay"]
        self.assertEqual((out["gun"], out["ay"]), ("2026-11-12", "2026-11"))
        self.assertEqual((day["usd"], day["is_sayisi"], day["token"], day["token_bilinen"]), (1.21, 3, 400000, 1))
        self.assertEqual(day["codex_fiyatsiz"], 1)
        self.assertEqual([(p["proje"], p["usd"]) for p in day["proje"]], [("blog", 1.2), ("kasa", 0.01)])
        self.assertEqual([(r["rol"], r["is_sayisi"]) for r in day["rol"]], [("Stajyer", 1), ("Kıdemli", 1),
                                                                          ("Dış denetçi", 1)])
        kasa = [p for p in day["proje"] if p["proje"] == "kasa"][0]
        self.assertIsNone(kasa["token"])  # unknown tokens are not 0
        self.assertEqual((month["usd"], month["is_sayisi"]), (1.71, 4))
        self.assertEqual(out["kalite"]["ilk_tur_gecen"], 3)
        self.assertEqual(out["kalite"]["dogrulanan"], 2)
        self.assertAlmostEqual(out["kalite"]["dogrulanmis_is_basina_usd"], 1.71 / 2, places=4)
        # the token twins: all known tokens / the verified jobs; how many rows have no count (never counted as 0)
        k = out["kalite"]
        self.assertEqual((k["dogrulanmis_is_basina_token"], k["toplam_token"], k["token_bilinmeyen"]), (200500, 401000, 2))
        self.assertEqual([x["not"] for x in out["en_pahali"]], ["a.md", "c.md", "b.md"])
        roles = {r["rol"]: r for r in out["bu_ay_rol_kalite"]}
        self.assertEqual(list(roles), ["Stajyer", "Uzman", "Kıdemli", "Dış denetçi"])
        self.assertEqual((roles["Uzman"]["ilk_tur_gecen"], roles["Uzman"]["ilk_tur_olculen"]), (0, 1))
        self.assertEqual(roles["Kıdemli"]["dogrulanmis_is_basina_usd"], 1.2)
        self.assertEqual(roles["Kıdemli"]["dogrulanmis_is_basina_token"], 400000)
        self.assertIsNone(roles["Stajyer"]["dogrulanmis_is_basina_token"])  # nothing verified, no count: unknown

    def test_this_months_jobs_per_specialisation(self):
        # plan "Sonraki iş (9)" step 2 (the İK card): every specialisation with this month's jobs, open ones included
        self.write("2026-11",
                   row("2026-11-12", "blog", "a", "opus", "1.0000", uzmanlik="mobil"),
                   row("2026-11-03", "blog", "b", "sonnet", "0.5000", uzmanlik="backend"),
                   row("2026-11-04", "blog", "c", "sonnet", "0.5000", uzmanlik="mobil"),
                   row("2026-11-05", "blog", "d", "haiku", "0.1000"))
        self.write("2026-10", row("2026-10-30", "blog", "e", "opus", "1.0000", uzmanlik="ui"))
        board = [{"note": "f.md", "status": "calisiyor", "project": "pazar", "model": "opus", "uzmanlik": "test",
                  "started": "2026-11-12T08:00:00", "spent": "0.2"}]
        out = muhasebe.ozet(self.vault, board, now=datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc))
        self.assertEqual([(u["uzmanlik"], u["is_sayisi"]) for u in out["bu_ay_uzmanlik"]],
                         [("backend", 1), ("mobil", 2), ("test", 1), ("", 1)])
        mobil = [u for u in out["bu_ay_uzmanlik"] if u["uzmanlik"] == "mobil"][0]
        self.assertEqual(mobil["usd"], 1.5)

    def test_the_month_and_the_day_are_read_in_the_office_zone(self):
        self.write("2026-11", row("2026-11-30", "blog", "a", "opus", "1.0000"))
        self.write("2026-12", row("2026-12-01", "blog", "b", "opus", "2.0000"))
        late = datetime(2026, 11, 30, 22, 30, tzinfo=timezone.utc)  # 01:30 on 1 December in Istanbul
        out = muhasebe.ozet(self.vault, [], now=late, tz="Europe/Istanbul")
        self.assertEqual((out["gun"], out["ay"]), ("2026-12-01", "2026-12"))
        self.assertEqual((out["bugun"]["usd"], out["bu_ay"]["usd"]), (2.0, 2.0))
        out = muhasebe.ozet(self.vault, [], now=late, tz="UTC")
        self.assertEqual((out["gun"], out["bu_ay"]["usd"]), ("2026-11-30", 1.0))

    def test_an_open_job_is_counted_once_and_budgets_are_flagged(self):
        self.write("2026-11", row("2026-11-12", "blog", "d", "opus", "0.3000"))
        board = [
            {"note": "a.md", "status": "calisiyor", "project": "blog", "title": "Giriş", "spent": "2.9",
             "tokens": "", "model": "opus", "budget": 3},
            {"note": "b.md", "status": "kontrolde", "project": "kasa", "title": "CSV", "spent": "0.5", "tokens": "900",
             "model": "sonnet", "budget": 3},
            {"note": "d.md", "status": "calisiyor", "project": "blog", "title": "Devam", "spent": "0.9",
             "model": "opus", "budget": 1},  # went on with devam: its Karne row counts, not the board value
            {"note": "e.md", "status": "bitti", "project": "blog", "spent": "9"},  # final: only through Karne
            {"note": "s.md", "status": "sirada", "project": "blog", "spent": ""},
        ]
        out = muhasebe.ozet(self.vault, board, now=datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc))
        # d.md runs again after devam: counted once, with the live (higher) board spending, and in the budget view
        self.assertEqual((out["bugun"]["usd"], out["bugun"]["is_sayisi"]), (4.3, 3))
        b = out["butce"]
        self.assertEqual((b["calisan"], b["harcanan_usd"], b["butce_usd"]), (3, 4.3, 7.0))
        self.assertEqual([(x["not"], x["durum"]) for x in b["dikkat"]], [("a.md", "yakin"), ("d.md", "yakin")])
        # the running jobs' tokens: only the known ones (b.md's 900), with how many are known
        self.assertEqual((b["harcanan_token"], b["token_bilinen"]), (900, 1))
        self.assertEqual([x["token"] for x in b["dikkat"]], [None, None])
        self.assertEqual(out["en_pahali"][0], {"not": "a.md", "baslik": "Giriş", "proje": "blog", "usd": 2.9,
                                               "token": None, "acik": True})

    def test_an_open_job_is_dated_by_its_start_not_today(self):
        board = [{"note": "o.md", "status": "karar-bekliyor", "project": "blog", "spent": "4", "started": "2026-10-20T10:00:00"},
                 {"note": "n.md", "status": "calisiyor", "project": "blog", "spent": "1", "started": "2026-11-12T08:00:00"}]
        out = muhasebe.ozet(self.vault, board, now=datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc))
        self.assertEqual((out["bugun"]["usd"], out["bu_ay"]["usd"]), (1.0, 1.0))
        self.assertEqual(out["butce"]["harcanan_usd"], 5.0)  # the budget view still sees every open job

    def test_nothing_known_gives_empty_totals_never_invented_numbers(self):
        out = muhasebe.ozet(self.vault, None, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        self.assertEqual((out["bugun"]["usd"], out["bugun"]["token"], out["bugun"]["is_sayisi"]), (0.0, None, 0))
        self.assertIsNone(out["kalite"]["dogrulanmis_is_basina_usd"])
        self.assertIsNone(out["kalite"]["dogrulanmis_is_basina_token"])
        self.assertIsNone(out["butce"]["harcanan_token"])
        self.assertEqual((out["en_pahali"], out["butce"]["butce_usd"]), ([], None))

    def test_npc_chat_usage_joins_the_totals_but_never_counts_as_a_job(self):
        # the owner, 2026-11-19: the questions' usage is part of the office's day/month totals; a question is not a
        # job — is_sayisi, the breakdowns and the quality numbers stay job-only
        self.write("2026-11", row("2026-11-12", "blog", "a", "opus", "1.0000", "1000", "1.0000"))
        durum = os.path.join(self.tmp.name, "durum")
        folder = os.path.join(durum, "npc_sohbet")
        os.makedirs(folder)
        tz = timezone.utc
        with open(os.path.join(folder, "kullanim.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"zaman": datetime(2026, 11, 12, 9, 30, tzinfo=tz).timestamp(), "usd": 0.02,
                                "token": 800}) + "\n")
            f.write(json.dumps({"zaman": datetime(2026, 10, 30, 9, 30, tzinfo=tz).timestamp(), "usd": 0.03,
                                "token": 900}) + "\n")
        now = datetime(2026, 11, 12, 10, 0, tzinfo=tz)
        out = muhasebe.ozet(self.vault, [], now=now, tz="UTC", durum_dir=durum)
        day = out["bugun"]
        self.assertEqual((day["usd"], day["is_sayisi"], day["token"], day["token_bilinen"]), (1.02, 1, 1800, 2))
        self.assertEqual(day["npc_sohbet"], {"usd": 0.02, "token": 800, "soru": 1})
        self.assertEqual([(p["proje"], p["usd"], p["is_sayisi"]) for p in day["proje"]], [("blog", 1.0, 1)])
        self.assertEqual(day["rol"][0]["is_sayisi"], 1)
        # the October record is another month: only today's question counts in the day, both months stay apart
        self.assertEqual(out["bu_ay"]["npc_sohbet"], {"usd": 0.02, "token": 800, "soru": 1})
        self.assertEqual((out["bu_ay"]["usd"], out["bu_ay"]["is_sayisi"]), (1.02, 1))
        self.assertEqual(out["kalite"]["dogrulanan"], 1)  # the quality numbers are job-only
        # without the records (no durum_dir) nothing changes and the period still carries the empty NPC total
        out = muhasebe.ozet(self.vault, [], now=now, tz="UTC")
        self.assertEqual((out["bugun"]["usd"], out["bugun"]["token"], out["bugun"]["is_sayisi"]), (1.0, 1000, 1))
        self.assertEqual(out["bugun"]["npc_sohbet"], {"usd": 0.0, "token": None, "soru": 0})
        # a record with no known tokens keeps the period's tokens as they were
        with open(os.path.join(folder, "kullanim.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"zaman": datetime(2026, 11, 12, 9, 40, tzinfo=tz).timestamp(), "usd": 0.04,
                                "token": 0}) + "\n")
        day = muhasebe.ozet(self.vault, [], now=now, tz="UTC", durum_dir=durum)["bugun"]
        self.assertEqual((day["usd"], day["token"], day["npc_sohbet"]), (1.06, 1800,
                                                                        {"usd": 0.06, "token": 800, "soru": 2}))

    def test_rows_are_parsed_again_only_when_a_file_changes(self):
        self.write("2026-11", row("2026-11-12", "blog", "a", "opus", "1.0000"))
        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        calls = []
        real = karne._rows
        karne._rows = lambda v: calls.append(v) or real(v)
        try:
            muhasebe.ozet(self.vault, [], now=now)
            muhasebe.ozet(self.vault, [], now=now)
            self.write("2026-11", row("2026-11-12", "blog", "a", "opus", "1.0000"),
                       row("2026-11-12", "blog", "b", "opus", "2.0000"))
            out = muhasebe.ozet(self.vault, [], now=now)
        finally:
            karne._rows = real
        self.assertEqual(len(calls), 2)
        self.assertEqual(out["bugun"]["usd"], 3.0)


class IdariTest(unittest.TestCase):
    def test_limits_autostart_log_size_and_base_names_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents, logs = os.path.join(tmp, "agents"), os.path.join(tmp, "logs")
            os.makedirs(logs)
            with open(os.path.join(logs, "server.log"), "w") as f:
                f.write("x" * 1234)
            muhasebe._idari.update(at=0.0, data=None)
            t = [100.0]
            out = muhasebe.idari({"max_running": 4, "max_bekleyen_onay": 3}, {"baslangic": "2026-11-12T09:00:00",
                                 "pid": 1}, None, agents_dir=agents, log_dir=logs, clock=lambda: t[0])
            self.assertEqual(out["limitler"], {"max_running": 4, "max_running_per_project": 1,
                                               "max_queued_per_project": 5, "max_bekleyen_onay": 3})
            self.assertEqual(out["otomatik_baslatma"], {"kurulu": False, "dosya": "local.ofis.server.plist"})
            self.assertEqual(out["gunluk"], {"dosya": "server.log", "boyut": 1234, "yedek_boyut": None})
            self.assertEqual(out["obsidian"], {"sorun": False, "python": None})
            self.assertNotIn(tmp, repr(out))
            with open(os.path.join(logs, "server.log"), "a") as f:
                f.write("y")
            t[0] = 110.0  # cached for 30 s
            problem = {"sorun": True, "python": "/opt/homebrew/Cellar/python@3.12/bin/python3.12"}
            self.assertEqual(muhasebe.idari({}, None, problem, agents_dir=agents, log_dir=logs,
                                            clock=lambda: t[0])["gunluk"]["boyut"], 1234)
            t[0] = 140.0
            again = muhasebe.idari({}, None, problem, agents_dir=agents, log_dir=logs, clock=lambda: t[0])
            self.assertEqual((again["gunluk"]["boyut"], again["obsidian"]), (1235, problem))
            # never the problem's free text (it names the vault's home path)
            self.assertEqual(muhasebe.idari({}, None, "HATA ~/Documents/x", agents_dir=agents, log_dir=logs,
                                            clock=lambda: t[0])["obsidian"], {"sorun": True, "python": None})


if __name__ == "__main__":
    unittest.main()
