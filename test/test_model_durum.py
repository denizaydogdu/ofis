"""Tests for bin/model_durum.py (living office: model status, scene config) and bin/alt_ajan.py (open subagents).
Temp transcripts and records only. The quota records copy the real format Claude Code 2.1.322 writes (spike of
2026-11-11, office transcripts): an assistant record with isApiErrorMessage, error "rate_limit", apiError
"usage_limit_reached" and quotaLimits {status: rejected, resetsAt: <epoch s>, rateLimitType}."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config, test/sahip_yasaklari.py)
import alt_ajan  # noqa: E402
import model_durum as md  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 11, 11, 10, 0, 0, tzinfo=UTC)
TR = timezone(timedelta(hours=3))


def iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ok(dt, model="claude-opus-5-5", msg="m"):
    return {"type": "assistant", "timestamp": iso(dt),
            "message": {"id": msg, "model": model, "role": "assistant", "content": [{"type": "text", "text": "x"}]}}


def quota(dt, resets=None, kind="five_hour", text="You've hit your 5-hour limit · resets 4:30pm (Europe/Istanbul)"):
    limits = {"status": "rejected", "rateLimitType": kind}
    if resets is not None:
        limits["resetsAt"] = int(resets.timestamp())
    return {"type": "assistant", "timestamp": iso(dt), "isApiErrorMessage": True, "error": "rate_limit",
            "apiError": "usage_limit_reached", "apiErrorStatus": 429, "quotaLimits": limits,
            "apiErrorParams": {"rate_limit_info": dict(limits)},
            "message": {"model": "<synthetic>", "role": "assistant", "content": [{"type": "text", "text": text}]}}


def api_error(dt, text="API Error: Connection lost mid-response.", api="connection_failed", error="server_error"):
    return {"type": "assistant", "timestamp": iso(dt), "isApiErrorMessage": True, "error": error, "apiError": api,
            "message": {"model": "<synthetic>", "role": "assistant", "content": [{"type": "text", "text": text}]}}


def by_model(rows):
    return {r["model"]: r for r in rows}


class FamilyTest(unittest.TestCase):
    def test_families_and_titles(self):
        self.assertEqual(md.family("claude-opus-5-5"), "opus")
        self.assertEqual(md.family("claude-haiku-4-5-20251001"), "haiku")
        self.assertEqual(md.family("sonnet"), "sonnet")
        self.assertEqual(md.family("fable"), "fable")
        self.assertEqual(md.family("codex"), "codex")
        self.assertEqual(md.family("<synthetic>"), "")
        self.assertEqual(md.family(None), "")
        self.assertEqual([md.UNVAN[m] for m in md.MODELS], ["Stajyer", "Uzman", "Kıdemli", "Genel Müdür", "Dış denetçi"])


class SceneConfigTest(unittest.TestCase):
    def setUp(self):
        # plan "2. Aşama": without ofis_sahnesi.saat_dilimi the office zone is the system's local zone
        patcher = mock.patch.object(md, "yerel_saat_dilimi", return_value="Europe/Istanbul")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_when_absent(self):
        self.assertEqual(md.sahne({}), {"ogle": "12:00-13:00", "saat_dilimi": "Europe/Istanbul"})

    def test_configured_values_pass_and_bad_ones_fall_back(self):
        self.assertEqual(md.sahne({"ofis_sahnesi": {"ogle": "12:30-13:30", "saat_dilimi": "Europe/Berlin"}}),
                         {"ogle": "12:30-13:30", "saat_dilimi": "Europe/Berlin"})
        self.assertEqual(md.sahne({"ofis_sahnesi": {"ogle": "25:00-13:00", "saat_dilimi": "Mars/Base"}}),
                         {"ogle": "12:00-13:00", "saat_dilimi": "Europe/Istanbul"})

    def test_the_default_zone_is_the_system_local_zone(self):
        with mock.patch.object(md, "yerel_saat_dilimi", return_value="America/New_York"):
            self.assertEqual(md.sahne({})["saat_dilimi"], "America/New_York")
            self.assertEqual(md.saat_dilimi({}), "America/New_York")
            self.assertEqual(md.office_tz().key, "America/New_York")
            # the configured zone still wins
            self.assertEqual(md.saat_dilimi({"ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"}}), "Europe/Istanbul")
            # every module that used to fall back to a fixed zone takes this one
            import ceo
            import limitler
            import muhasebe
            import ozet
            for tz in (ceo._office_tz({}), limitler._tz({}), ozet._tz({}), limitler._tz({"ofis_sahnesi": "x"})):
                self.assertEqual(tz.key, "America/New_York")
            self.assertEqual(ozet._tz({"ofis_sahnesi": {"saat_dilimi": "Asia/Tokyo"}}).key, "Asia/Tokyo")
            with tempfile.TemporaryDirectory() as vault:
                self.assertEqual(muhasebe.ozet(vault, [])["saat_dilimi"], "America/New_York")


    def test_office_zone_and_its_fixed_fallback(self):
        tz = md.office_tz("Europe/Istanbul")
        self.assertEqual(datetime(2026, 11, 11, 9, 0, tzinfo=UTC).astimezone(tz).hour, 12)
        with mock.patch.object(md, "ZoneInfo", side_effect=md.ZoneInfoNotFoundError("no tzdata")):
            tz = md.office_tz("Europe/Istanbul")
            # the system's current offset (plan "2. Aşama"; UTC+3 on an Istanbul machine as before)
            self.assertEqual(tz.utcoffset(None), datetime.now().astimezone().utcoffset())
            # a configured zone that cannot be checked falls back to the default name, shown with the fixed offset
            self.assertEqual(md.sahne({"ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"}})["saat_dilimi"],
                             "Europe/Istanbul")

    def test_server_utc_offset_is_the_local_offset_of_the_server(self):
        # review step 2, finding 4: naive job stamps are the server's local time; the page needs its offset
        old = os.environ.get("TZ")
        try:
            for zone, minutes in (("America/New_York", -300), ("Asia/Kolkata", 330), ("UTC", 0)):
                os.environ["TZ"] = zone
                time.tzset()
                self.assertEqual(md.sunucu_ofset_dk(datetime(2026, 11, 11, 10, 0)), minutes, zone)
                self.assertEqual(md.sunucu_ofset_dk(NOW), minutes, zone)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_is_lunch_in_the_office_zone(self):
        cfg = {"ofis_sahnesi": {"ogle": "12:00-13:00", "saat_dilimi": "Europe/Istanbul"}}
        self.assertTrue(md.is_lunch(cfg, datetime(2026, 11, 11, 9, 30, tzinfo=UTC)))   # 12:30 in Istanbul
        self.assertFalse(md.is_lunch(cfg, datetime(2026, 11, 11, 12, 30, tzinfo=UTC)))  # 15:30 in Istanbul
        self.assertFalse(md.is_lunch(cfg, datetime(2026, 11, 11, 10, 0, tzinfo=UTC)))   # 13:00: the end is open


class LocalZoneTest(unittest.TestCase):
    def setUp(self):
        old = os.environ.get("TZ")
        self.addCleanup(lambda: os.environ.__setitem__("TZ", old) if old is not None else os.environ.pop("TZ", None))

    def test_tz_variable_wins(self):
        os.environ["TZ"] = "Asia/Tokyo"
        self.assertEqual(md.yerel_saat_dilimi(), "Asia/Tokyo")
        os.environ["TZ"] = ":Europe/Berlin"
        self.assertEqual(md.yerel_saat_dilimi(), "Europe/Berlin")

    def test_localtime_link_then_utc(self):
        os.environ.pop("TZ", None)
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "localtime")
            os.symlink("/var/db/timezone/zoneinfo/America/Sao_Paulo", link)
            with mock.patch.object(md, "LOCALTIME", link):
                self.assertEqual(md.yerel_saat_dilimi(), "America/Sao_Paulo")
            with mock.patch.object(md, "LOCALTIME", os.path.join(tmp, "yok")), \
                    mock.patch.object(md, "TIMEZONE_FILE", os.path.join(tmp, "yok")):
                self.assertEqual(md.yerel_saat_dilimi(), "UTC")
        os.environ["TZ"] = "Mars/Base"  # an unknown zone in TZ: the link, never the bad name
        with mock.patch.object(md, "LOCALTIME", "/nonexistent"), mock.patch.object(md, "TIMEZONE_FILE", "/nonexistent"):
            self.assertEqual(md.yerel_saat_dilimi(), "UTC")
        self.assertEqual(md.sahne({"ofis_sahnesi": {"ogle": "14:00-13:00"}})["ogle"], "12:00-13:00")  # end first
        self.assertEqual(md.sahne({"ofis_sahnesi": "x"})["ogle"], "12:00-13:00")

    def test_linux_plain_localtime_file_reads_etc_timezone(self):
        # Debian/Ubuntu: /etc/localtime is a plain copy of the zone file, the name is the first line of /etc/timezone
        os.environ.pop("TZ", None)
        with tempfile.TemporaryDirectory() as tmp:
            localtime = os.path.join(tmp, "localtime")
            with open(localtime, "wb") as f:
                f.write(b"TZif2 not a link")
            tzfile = os.path.join(tmp, "timezone")
            with mock.patch.object(md, "LOCALTIME", localtime), mock.patch.object(md, "TIMEZONE_FILE", tzfile):
                for text, want in (("Europe/Istanbul\n", "Europe/Istanbul"), ("  Asia/Tokyo  \nignored\n", "Asia/Tokyo"),
                                   ("Mars/Base\n", "UTC"), ("../../etc/passwd\n", "UTC"), ("", "UTC"),
                                   ("\nEurope/Berlin\n", "UTC")):
                    with self.subTest(text=text):
                        with open(tzfile, "w", encoding="utf-8") as f:
                            f.write(text)
                        self.assertEqual(md.yerel_saat_dilimi(), want)
                os.remove(tzfile)
                self.assertEqual(md.yerel_saat_dilimi(), "UTC")
            os.environ["TZ"] = "America/Sao_Paulo"  # $TZ still wins over the file
            with open(tzfile, "w", encoding="utf-8") as f:
                f.write("Europe/Istanbul\n")
            with mock.patch.object(md, "LOCALTIME", localtime), mock.patch.object(md, "TIMEZONE_FILE", tzfile):
                self.assertEqual(md.yerel_saat_dilimi(), "America/Sao_Paulo")

class ScanTest(unittest.TestCase):
    def test_quota_record_is_read_with_its_reset_time_and_the_model_before_it(self):
        resets = NOW + timedelta(hours=2)
        scan = md.scan_records([ok(NOW - timedelta(minutes=5)), quota(NOW - timedelta(minutes=1), resets)])
        self.assertEqual(scan["quotas"][-1]["resets_at"], resets.replace(microsecond=0))
        self.assertEqual(scan["quotas"][-1]["scope"], md.CLAUDE)  # five_hour: the whole account
        self.assertEqual(scan["model"], "opus")
        self.assertIn("5-hour limit", scan["quotas"][-1]["text"])

    def test_a_model_specific_weekly_limit_covers_only_that_model(self):
        scan = md.scan_records([quota(NOW, NOW + timedelta(days=1), kind="seven_day_opus")])
        self.assertEqual(scan["quotas"][-1]["scope"], ("opus",))

    def test_plain_rate_limit_or_server_error_is_not_quota(self):
        scan = md.scan_records([api_error(NOW, "API Error: 429 too many requests", api="rate_limited",
                                          error="rate_limit")])
        self.assertEqual(scan["quotas"], [])
        self.assertIsNotNone(scan["error"])

    def test_a_sleeping_computer_is_not_a_model_error(self):
        scan = md.scan_records([api_error(NOW, "API Error: Your computer went to sleep", api="computer_slept")])
        self.assertIsNone(scan["error"])


class ClaudeStatusTest(unittest.TestCase):
    def status(self, records, now=NOW, calisan=None, fallback=""):
        scans = [(md.scan_records(records), fallback)]
        return by_model(md.build(scans, [], calisan or {}, now, TR))

    def test_quota_with_a_reset_time_is_shown_for_every_claude_model(self):
        resets = NOW + timedelta(hours=2)
        rows = self.status([ok(NOW - timedelta(minutes=5)), quota(NOW - timedelta(minutes=1), resets)])
        for m in md.CLAUDE:
            self.assertEqual(rows[m]["durum"], "kota", m)
            self.assertEqual(rows[m]["donus"], resets.astimezone(TR).isoformat(timespec="minutes"))
            self.assertIn("5-hour limit", rows[m]["son_hata"])
        self.assertEqual(rows["codex"]["durum"], "bilinmiyor")
        self.assertEqual(rows["opus"]["unvan"], "Kıdemli")

    def test_an_older_still_active_limit_is_not_hidden_by_a_newer_expired_one(self):
        weekly_back = NOW + timedelta(days=2)
        rows = self.status([quota(NOW - timedelta(hours=10), weekly_back, kind="seven_day"),
                            quota(NOW - timedelta(hours=6), NOW - timedelta(hours=1))])
        self.assertEqual(rows["opus"]["durum"], "kota")
        self.assertEqual(rows["opus"]["donus"], weekly_back.astimezone(TR).isoformat(timespec="minutes"))
        # two active ones: the later return wins
        rows = self.status([quota(NOW - timedelta(hours=1), NOW + timedelta(hours=3)),
                            quota(NOW - timedelta(hours=10), weekly_back, kind="seven_day")])
        self.assertEqual(rows["opus"]["donus"], weekly_back.astimezone(TR).isoformat(timespec="minutes"))
        # across files too
        scans = [(md.scan_records([quota(NOW - timedelta(hours=10), weekly_back, kind="seven_day")]), ""),
                 (md.scan_records([quota(NOW - timedelta(hours=6), NOW - timedelta(hours=1))]), "")]
        self.assertEqual(by_model(md.build(scans, [], {}, NOW, TR))["opus"]["durum"], "kota")

    def test_quota_ends_when_the_reset_time_passes(self):
        rows = self.status([quota(NOW - timedelta(hours=3), NOW - timedelta(minutes=1))])
        self.assertEqual(rows["opus"]["durum"], "hazir")
        self.assertIsNone(rows["opus"]["donus"])

    def test_a_later_successful_call_clears_the_quota(self):
        rows = self.status([quota(NOW - timedelta(minutes=30), NOW + timedelta(hours=2)),
                            ok(NOW - timedelta(minutes=1), "claude-sonnet-4-6")])
        self.assertEqual(rows["opus"]["durum"], "hazir")

    def test_a_model_specific_quota_is_cleared_only_by_that_model(self):
        rows = self.status([quota(NOW - timedelta(minutes=30), NOW + timedelta(days=1), kind="seven_day_opus"),
                            ok(NOW - timedelta(minutes=1), "claude-sonnet-4-6")])
        self.assertEqual(rows["opus"]["durum"], "kota")
        self.assertEqual(rows["sonnet"]["durum"], "hazir")

    def test_quota_without_a_reset_time_lasts_at_most_the_window(self):
        rec = quota(NOW - timedelta(hours=1), None)
        self.assertEqual(self.status([rec])["opus"]["durum"], "kota")
        self.assertIsNone(self.status([rec])["opus"]["donus"])
        old = quota(NOW - md.QUOTA_WITHOUT_RESET - timedelta(minutes=1), None)
        self.assertEqual(self.status([old])["opus"]["durum"], "hazir")

    def test_never_quota_without_a_matched_message(self):
        rows = self.status([ok(NOW - timedelta(minutes=1))])
        self.assertNotIn("kota", {r["durum"] for r in rows.values()})
        # nothing could be read at all: unknown, not ready
        rows = by_model(md.build([], [], {}, NOW, TR))
        self.assertEqual({r["durum"] for r in rows.values()}, {"bilinmiyor"})

    def test_a_recent_api_error_is_an_error_of_the_model_that_ran_until_a_success(self):
        rows = self.status([ok(NOW - timedelta(minutes=6), "claude-haiku-4-5"),
                            api_error(NOW - timedelta(minutes=5))])
        self.assertEqual(rows["haiku"]["durum"], "hata")
        self.assertIn("Connection lost", rows["haiku"]["son_hata"])
        self.assertEqual(rows["opus"]["durum"], "hazir")
        rows = self.status([api_error(NOW - timedelta(minutes=5)), ok(NOW - timedelta(minutes=4), "claude-haiku-4-5")])
        self.assertEqual(rows["haiku"]["durum"], "hazir")
        rows = self.status([api_error(NOW - md.ERROR_WINDOW - timedelta(minutes=1))], fallback="haiku")
        self.assertEqual(rows["haiku"]["durum"], "hazir")
        # no model before the error: the session's job model
        rows = self.status([api_error(NOW - timedelta(minutes=2))], fallback="sonnet")
        self.assertEqual(rows["sonnet"]["durum"], "hata")

    def test_working_sessions_are_counted(self):
        rows = self.status([ok(NOW - timedelta(minutes=1))], calisan={"opus": 2, "codex": 1})
        self.assertEqual((rows["opus"]["durum"], rows["opus"]["calisan"]), ("calisiyor", 2))
        self.assertEqual((rows["haiku"]["durum"], rows["haiku"]["calisan"]), ("hazir", 0))
        self.assertEqual(rows["codex"]["durum"], "calisiyor")
        self.assertEqual([r["model"] for r in md.build([], [], {}, NOW, TR)], list(md.MODELS))


class TranscriptScannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "s.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, records, mode="w"):
        with open(self.path, mode, encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_the_tail_is_read_once_per_change(self):
        self.write([ok(NOW)])
        scanner = md.TranscriptScanner()
        self.assertEqual(scanner.scan(self.path)["model"], "opus")
        self.assertEqual(scanner.scan(self.path)["model"], "opus")
        self.assertEqual(scanner.reads, 1)
        self.write([quota(NOW, NOW + timedelta(hours=1))], mode="a")
        self.assertEqual(len(scanner.scan(self.path)["quotas"]), 1)
        self.assertEqual(scanner.reads, 2)
        self.assertIsNone(scanner.scan(os.path.join(self.tmp.name, "yok.jsonl")))

    def test_only_the_tail_is_read_and_a_cut_first_line_is_skipped(self):
        big = ok(NOW - timedelta(hours=1))
        big["message"]["content"][0]["text"] = "y" * 5000
        self.write([quota(NOW - timedelta(hours=2), NOW + timedelta(hours=1)), big, ok(NOW, "claude-haiku-4-5")])
        scan = md.TranscriptScanner(tail_bytes=3000).scan(self.path)
        self.assertEqual(scan["quotas"], [])  # outside the tail
        self.assertEqual(scan["model"], "haiku")


class CodexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.durum = self.tmp.name
        os.makedirs(os.path.join(self.durum, "isler"))

    def tearDown(self):
        self.tmp.cleanup()

    KOTA = "claude (codex yok: kota doldu)"

    def record(self, name, value, when, kota=False, donus=None):
        data = {"is": name + ".md", "adim_turu": "kod-inceleme", "inceleme_yurutucu": value}
        if when is not None:
            data["codex_zamani"] = f"{when.astimezone():%Y-%m-%dT%H:%M:%S}"
        if kota:
            data["codex_kota"] = "evet"
        if donus is not None:
            data["codex_donus"] = donus.astimezone(TR).isoformat(timespec="minutes")
        with open(os.path.join(self.durum, "isler", name + ".json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def codex(self, now=NOW, calisan=0):
        events = md.CodexScanner().events(self.durum)
        return by_model(md.build([], events, {"codex": calisan}, now, TR))["codex"]

    def test_quota_fallback_is_shown_then_cleared_by_a_later_success(self):
        self.record("2026-11-11-090000-blog", self.KOTA, NOW - timedelta(minutes=30), kota=True)
        row = self.codex()
        self.assertEqual((row["durum"], row["unvan"]), ("kota", "Dış denetçi"))
        self.assertIsNone(row["donus"])
        self.assertIn("kota doldu", row["son_hata"])
        self.record("2026-11-11-093000-blog", "codex", NOW - timedelta(minutes=5))
        self.assertEqual(self.codex()["durum"], "hazir")

    def test_only_the_strict_flag_is_a_quota(self):
        # the label alone (akis.QUOTA matched some text) is a failure, never a quota
        self.record("a-blog", self.KOTA, NOW - timedelta(minutes=30))
        self.assertEqual(self.codex()["durum"], "hata")

    def test_quota_with_a_reset_time_lasts_until_it_then_ready(self):
        # Codex named its own reset time: once it has passed, the quota is back (the owner, 2026-11-12: not "bilinmiyor")
        back = NOW + timedelta(hours=20)
        self.record("a-blog", self.KOTA, NOW - timedelta(hours=7), kota=True, donus=back)
        row = self.codex()
        self.assertEqual((row["durum"], row["donus"]), ("kota", back.astimezone(TR).isoformat(timespec="minutes")))
        self.assertEqual(self.codex(now=back + timedelta(minutes=1))["durum"], "hazir")

    def test_quota_without_a_reset_time_expires_into_unknown(self):
        self.record("a-blog", self.KOTA, NOW - md.QUOTA_WITHOUT_RESET - timedelta(minutes=1), kota=True)
        self.assertEqual(self.codex()["durum"], "bilinmiyor")

    def test_other_failures_are_errors_then_unknown_and_records_without_a_time_are_ignored(self):
        self.record("a-blog", "claude (codex yok: çıkış kodu 2)", NOW - timedelta(minutes=10))
        self.assertEqual(self.codex()["durum"], "hata")
        self.record("b-blog", self.KOTA, None, kota=True)  # inherited by a later round, no run
        self.assertEqual(self.codex()["durum"], "hata")
        self.assertEqual(self.codex(calisan=1)["durum"], "calisiyor")
        later = NOW + md.CODEX_ERROR_WINDOW
        self.assertEqual(self.codex(now=later)["durum"], "bilinmiyor")  # an old failure proves nothing either way
        self.assertEqual(self.codex(now=later, calisan=1)["durum"], "calisiyor")

    def test_a_running_review_is_calisiyor_even_while_a_quota_flag_is_live(self):
        # review step 2, finding 1: the board must not say "kota" while the scene shows Codex typing
        self.record("a-blog", self.KOTA, NOW - timedelta(minutes=30), kota=True,
                    donus=NOW + timedelta(hours=2))
        self.assertEqual(self.codex()["durum"], "kota")
        self.assertEqual(self.codex(calisan=1)["durum"], "calisiyor")

    def test_records_are_read_once_per_change(self):
        self.record("a-blog", "codex", NOW - timedelta(minutes=10))
        scanner = md.CodexScanner()
        scanner.events(self.durum)
        scanner.events(self.durum)
        self.assertEqual(scanner.reads, 1)


class CodexLimitTest(unittest.TestCase):
    """The strict quota match on codex's own output (non-zero exit, the last lines) and its reset time."""
    LOCAL = datetime(2026, 11, 11, 10, 0).astimezone()  # codex prints its local time

    def test_a_usage_limit_error_is_a_quota(self):
        out = "ERROR: You've hit your usage limit. Upgrade to Pro or try again later.\n"
        self.assertEqual(md.codex_limit(out, 1, self.LOCAL, TR), (True, None))
        self.assertEqual(md.codex_limit("Usage limit reached.", 1, self.LOCAL, TR)[0], True)
        self.assertEqual(md.codex_limit("error: usage_limit_reached", 1, self.LOCAL, TR)[0], True)
        self.assertEqual(md.codex_limit("insufficient_quota", 1, self.LOCAL, TR)[0], True)
        self.assertEqual(md.codex_limit("You’ve hit your usage limit.", 1, self.LOCAL, TR)[0], True)  # ’

    def test_never_on_success_review_text_or_old_lines(self):
        self.assertEqual(md.codex_limit("You've hit your usage limit.", 0, self.LOCAL, TR), (False, None))
        self.assertEqual(md.codex_limit("no rate limiting; return 429; quota", 1, self.LOCAL, TR), (False, None))
        old = "You've hit your usage limit.\n" + "\n".join(f"diff line {i}" for i in range(25))
        self.assertEqual(md.codex_limit(old, 1, self.LOCAL, TR), (False, None))
        self.assertEqual(md.codex_limit(None, None, self.LOCAL, TR), (False, None))

    def test_the_reset_time_is_parsed(self):
        out = ("ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
               "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Nov 12th, 2026 "
               "3:05 PM.")
        self.assertEqual(md.codex_limit(out, 1, self.LOCAL, TR),
                         (True, datetime(2026, 11, 12, 15, 5).astimezone().astimezone(TR)))
        # a time alone: today, or tomorrow when it has passed
        self.assertEqual(md.codex_limit("You've hit your usage limit. Try again at 3:05 PM.", 1, self.LOCAL, TR)[1],
                         datetime(2026, 11, 11, 15, 5).astimezone().astimezone(TR))
        self.assertEqual(md.codex_limit("You've hit your usage limit. Try again at 9:05 AM.", 1, self.LOCAL, TR)[1],
                         datetime(2026, 11, 12, 9, 5).astimezone().astimezone(TR))
        # nonsense dates are no reset time
        self.assertEqual(md.codex_limit("You've hit your usage limit. Try again at Foo 40th, 2026 13:99 PM.", 1,
                                        self.LOCAL, TR), (True, None))


class SubagentTest(unittest.TestCase):
    SID = "11111111-aaaa-bbbb-cccc-000000000001"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.sub = os.path.join(self.folder, self.SID, "subagents")
        os.makedirs(self.sub)
        self.now = datetime.now(UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, aid, records, meta=None, age=0):
        path = os.path.join(self.sub, f"agent-{aid}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        if meta is not None:
            with open(os.path.join(self.sub, f"agent-{aid}.meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f)
        t = self.now.timestamp() - age
        os.utime(path, (t, t))
        return path

    def first(self, text):
        return {"type": "user", "isSidechain": True, "agentId": "x", "message": {"role": "user", "content": text}}

    def stop(self):
        return {"type": "attachment", "attachment": {"type": "hook_success", "hookEvent": "SubagentStop"}}

    def tool_use(self, model="claude-haiku-4-5"):
        rec = ok(self.now, model)
        rec["message"]["content"] = [{"type": "tool_use", "name": "Bash", "input": {"command": "x"}}]
        return rec

    def test_open_finished_and_stale_subagents(self):
        self.agent("a1", [self.first("Find every\n\tcaller of foo()  in bin/ and report the lines " + "z" * 200),
                          ok(self.now, "claude-haiku-4-5")])
        self.agent("a2", [self.first("x"), ok(self.now), self.stop()], meta={"description": "Review the diff"},
                   age=10)
        self.agent("a3", [self.first("old"), ok(self.now)], age=alt_ajan.OPEN_WINDOW + 60)
        self.agent("a4", [self.first("done long ago"), ok(self.now), self.stop()], age=alt_ajan.DONE_SHOWN + 30)
        rows = alt_ajan.SubagentScanner().list(self.folder, self.SID, self.now)
        self.assertEqual([r["id"] for r in rows], ["a1", "a2"])
        a1, a2 = rows
        self.assertEqual((a1["model"], a1["bitti"]), ("haiku", False))
        self.assertLessEqual(len(a1["gorev"]), 80)
        self.assertTrue(a1["gorev"].startswith("Find every caller of foo() in bin/"))
        self.assertTrue(a1["gorev"].endswith("…"))
        self.assertEqual((a2["model"], a2["bitti"], a2["gorev"]), ("opus", True, "Review the diff"))
        self.assertRegex(a1["son_yazma"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")

    def test_a_subagent_waiting_on_a_long_tool_stays_open(self):
        self.agent("a1", [self.first("x"), self.tool_use()], age=alt_ajan.OPEN_WINDOW + 60)
        [row] = alt_ajan.SubagentScanner().list(self.folder, self.SID, self.now)
        self.assertFalse(row["bitti"])

    def test_meta_finished_and_model_fallback(self):
        self.agent("a1", [self.first("x")], meta={"pickedEffortModel": "claude-sonnet-4-6", "finished": True})
        [row] = alt_ajan.SubagentScanner().list(self.folder, self.SID, self.now)
        self.assertEqual((row["model"], row["bitti"]), ("sonnet", True))

    def test_at_most_eight_open_first(self):
        for i in range(10):
            self.agent(f"b{i}", [self.first("x"), ok(self.now)], age=i)
        self.agent("done", [self.first("x"), ok(self.now), self.stop()])
        rows = alt_ajan.SubagentScanner().list(self.folder, self.SID, self.now)
        self.assertEqual(len(rows), alt_ajan.MAX_SHOWN)
        self.assertFalse(any(r["bitti"] for r in rows))
        self.assertEqual(rows[0]["id"], "b0")

    def test_cached_by_mtime_and_bad_input_is_harmless(self):
        self.agent("a1", [self.first("x"), ok(self.now)])
        with open(os.path.join(self.sub, "agent-bad.jsonl"), "w") as f:
            f.write("{nope\n")
        scanner = alt_ajan.SubagentScanner()
        scanner.list(self.folder, self.SID, self.now)
        scanner.list(self.folder, self.SID, self.now)
        self.assertEqual(scanner.reads, 2)  # two files, each read once
        self.assertEqual(scanner.list(self.folder, "../x", self.now), [])
        self.assertEqual(scanner.list(self.folder, "22222222-aaaa-bbbb-cccc-000000000002", self.now), [])

    def test_a_subagent_stopped_by_an_api_error_is_not_open(self):
        self.agent("a1", [self.first("x"), ok(self.now), api_error(self.now)])
        self.assertEqual(alt_ajan.SubagentScanner().list(self.folder, self.SID, self.now), [])

    def test_only_finished_rows_when_the_parent_job_is_final(self):
        self.agent("a1", [self.first("x"), ok(self.now)])
        self.agent("a2", [self.first("x"), ok(self.now), self.stop()])
        rows = alt_ajan.SubagentScanner().list(self.folder, self.SID, self.now, only_finished=True)
        self.assertEqual([r["id"] for r in rows], ["a2"])

    def test_a_forbidden_transcript_folder_is_never_read(self):
        # a cwd like ~/Dev_<forbidden> encodes to a folder whose "-" parts include the forbidden name
        for name in ("-Users-x-Dev-zim", "-Users-x-Dev-ZIM-api", "-Users-x-Dev-zim-x"):
            self.assertTrue(alt_ajan.forbidden_folder(os.path.join(self.folder, name)), name)
        for name in ("-Users-x-Dev-blog", "-Users-x-Dev-zimbo", "-Users-x-Dev-ajan-ofisi"):
            self.assertFalse(alt_ajan.forbidden_folder(os.path.join(self.folder, name)), name)
        fake = os.path.join(self.folder, "-Users-x-Dev-zim")
        os.makedirs(os.path.join(fake, self.SID, "subagents"))
        with open(os.path.join(fake, self.SID, "subagents", "agent-z1.jsonl"), "w") as f:
            f.write(json.dumps(self.first("gizli")) + "\n")
        scanner = alt_ajan.SubagentScanner()
        self.assertEqual(scanner.list(fake, self.SID, self.now), [])
        self.assertEqual(scanner.reads, 0)

    def test_task_text_is_plain_and_short(self):
        self.assertEqual(alt_ajan.plain("  a\x00b\n\n c  "), "ab c")
        self.assertEqual(alt_ajan.plain([{"type": "text", "text": "merhaba"}, {"type": "image"}]), "merhaba")


if __name__ == "__main__":
    unittest.main()
