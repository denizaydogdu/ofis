"""Tests for bin/budget.py: a job's list-price cost and model calls from its own transcript, and its limits.
Temp transcripts only."""
import os
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import budget  # noqa: E402
import fakes  # noqa: E402
import jobs  # noqa: E402

SID = "abcdef12-3456-7890-abcd-ef1234567890"
OTHER = "abcdef99-0000-0000-0000-000000000000"
DAY = date(2026, 11, 10)
OPUS = "claude-opus-5-5"


def call(day, msg_id, out_tokens=1_000_000, model=OPUS, hour=12):
    """One model call: 1M output tokens of Opus 5.5 = $20 at list price."""
    return fakes.assistant(day, msg_id, [{"type": "text", "text": "x"}], hour=hour, model=model,
                           usage={"input_tokens": 0, "output_tokens": out_tokens, "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 0})


class MeterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.projects = os.path.join(base, "projects")
        self.cwd = os.path.join(base, "Dev", "blog")
        os.makedirs(self.cwd)
        self.meter = budget.UsageMeter(self.projects)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, kisa_id=SID[:8], cwd=None, **meta):
        meta = {"proje": "blog", "durum": "calisiyor", "kisa_id": kisa_id, "calisma_dizini": cwd or self.cwd,
                **meta}
        return jobs.Job("2026-11-10-183820-blog.md", jobs.ACTIVE, "", meta, "")

    def test_cost_and_calls_count_every_day_of_the_session(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [
            call(fakes.yesterday(DAY), "m1", 100_000), call(DAY, "m2", 50_000), call(DAY, "m2", 50_000)])
        usage = self.meter.usage(self.job())
        self.assertAlmostEqual(usage.cost, 3.0)  # 150K output tokens of Opus 5.5 ($20 / M); m2 counted once
        self.assertEqual(usage.calls, 2)
        self.assertEqual(usage.session_id, SID)

    def test_only_the_jobs_own_session_counts_with_its_subagents(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1", 100_000)])
        fakes.write_transcript(self.projects, self.cwd, OTHER, [call(DAY, "o1", 900_000)])
        folder = os.path.join(self.projects, self.cwd.replace("/", "-"), SID, "subagents")
        os.makedirs(folder)
        with open(os.path.join(folder, "agent-a1.jsonl"), "w", encoding="utf-8") as f:
            import json
            f.write(json.dumps(call(DAY, "s1", 50_000)) + "\n")
        usage = self.meter.usage(self.job())
        self.assertAlmostEqual(usage.cost, 3.0)
        self.assertEqual(usage.calls, 2)
        self.assertEqual(usage.tokens, 150_000)  # the other session's 900K are not the job's

    def test_three_parallel_helpers_are_all_counted(self):
        # Step 3 (owner decision 2026-11-13): a kod session may give independent parts to at most 3 helpers at once; each
        # helper's transcript counts toward the job's budget and call limit
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1", 100_000)])
        folder = os.path.join(self.projects, self.cwd.replace("/", "-"), SID, "subagents")
        os.makedirs(folder)
        import json
        for i in range(3):
            with open(os.path.join(folder, f"agent-a{i}.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps(call(DAY, f"s{i}", 50_000)) + "\n")
        usage = self.meter.usage(self.job())
        self.assertEqual((usage.calls, usage.tokens), (4, 250_000))
        self.assertAlmostEqual(usage.cost, 5.0)

    def test_reading_is_incremental(self):
        path = fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1", 100_000)])
        self.assertEqual(self.meter.usage(self.job()).calls, 1)
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m2", 100_000)], mode="a")
        usage = self.meter.usage(self.job())
        self.assertEqual((usage.calls, round(usage.cost, 2)), (2, 4.0))
        self.assertTrue(os.path.isfile(path))

    def test_unknown_session_gives_none(self):
        self.assertIsNone(self.meter.usage(self.job(kisa_id="-")))
        self.assertIsNone(self.meter.usage(self.job()), "no transcript yet")
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1")])
        fakes.write_transcript(self.projects, self.cwd, SID[:8] + "-ffff-0000-0000-000000000000", [call(DAY, "m9")])
        self.assertIsNone(self.meter.usage(self.job()), "an ambiguous short id is not guessed")

    # --- phase 3, item 0: a resumed project session continues in a NEW transcript (fork) ---

    def test_usage_sums_every_transcript_of_the_job_with_one_message_id_dedup(self):
        new = "fedcba98-0000-4000-8000-000000000001"
        old = [call(DAY, "m1", 100_000), call(DAY, "m2", 50_000)]
        fakes.write_transcript(self.projects, self.cwd, SID, old)
        # the fork starts with a copy of the earlier history (same message ids), then goes on
        fakes.write_transcript(self.projects, self.cwd, new, old + [call(DAY, "m3", 50_000), call(DAY, "m4", 50_000)])
        folder = os.path.join(self.projects, self.cwd.replace("/", "-"), new, "subagents")
        os.makedirs(folder)
        with open(os.path.join(folder, "agent-a1.jsonl"), "w", encoding="utf-8") as f:
            import json
            f.write(json.dumps(call(DAY, "s1", 50_000)) + "\n")
        usage = self.meter.usage(self.job(kisa_id=new[:8], oturum_kimlikleri=f"{SID},{new}"))
        self.assertEqual(usage.calls, 5, "m1 and m2 are counted once although both files hold them")
        self.assertEqual(usage.tokens, 300_000, "tokens are counted once per call too, subagents included")
        self.assertAlmostEqual(usage.cost, 6.0)  # 300K output tokens of Opus 5.5
        self.assertEqual(usage.session_id, new, "the current session is the one of kisa_id")
        self.assertEqual(set(usage.session_ids), {SID, new})

    def test_the_old_transcript_still_counts_when_only_the_new_one_has_the_short_id(self):
        new = "fedcba98-0000-4000-8000-000000000002"
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1", 100_000)])
        fakes.write_transcript(self.projects, self.cwd, new, [call(DAY, "m1", 100_000), call(DAY, "m2", 100_000)])
        self.assertEqual(self.meter.usage(self.job(kisa_id=new[:8])).calls, 2, "the new file alone")
        meter = budget.UsageMeter(self.projects)
        self.assertEqual(meter.usage(self.job(kisa_id=new[:8], oturum_kimlikleri=SID)).calls, 2)
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m0", 100_000)], mode="a")
        self.assertEqual(meter.usage(self.job(kisa_id=new[:8], oturum_kimlikleri=SID)).calls, 3,
                         "a call written to the old file after the fork counts too (incremental)")

    def test_a_listed_session_id_without_a_transcript_is_ignored(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1", 100_000)])
        usage = self.meter.usage(self.job(oturum_kimlikleri="abcdef00-0000-4000-8000-000000000000,../x"))
        self.assertEqual((usage.calls, usage.session_ids), (1, (SID,)))

    def test_models_without_a_price_are_counted_as_calls(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [call(DAY, "m1", model="claude-x")])
        usage = self.meter.usage(self.job())
        self.assertEqual((usage.calls, usage.cost, usage.unpriced), (1, 0.0, 1))


class LimitsTest(unittest.TestCase):
    CFG = {"default_budget_usd": 3, "default_max_calls": {"kolay": 15, "genel": 40}}

    def job(self, **meta):
        return jobs.Job("a.md", jobs.ACTIVE, "", {"katman": "genel", **meta}, "")

    def test_limits_come_from_the_job_else_the_defaults(self):
        self.assertEqual(budget.limits(self.CFG, self.job()), (3.0, 40))
        self.assertEqual(budget.limits(self.CFG, self.job(butce_usd="1.5", max_cagri="7")), (1.5, 7))
        self.assertEqual(budget.limits({}, self.job(katman="kolay")), (None, None))
        self.assertEqual(budget.limits(self.CFG, self.job(butce_usd="bozuk", max_cagri="-1")), (3.0, 40))

    def test_exceeded_names_the_limit(self):
        u = budget.Usage(cost=3.2, calls=12, unpriced=0, session_id=SID)
        self.assertEqual(budget.exceeded(self.CFG, self.job(), u)[0], "butce")
        self.assertIsNone(budget.exceeded(self.CFG, self.job(butce_usd="5"), u))
        u = budget.Usage(cost=0.5, calls=41, unpriced=0, session_id=SID)
        kind, line, key = budget.exceeded(self.CFG, self.job(), u)
        self.assertEqual((kind, line), ("cagri", "> Çağrı sınırı aşıldı: 41 / 40"))
        self.assertEqual(key, "cagri-a-40")
        u = budget.Usage(cost=3.2, calls=1, unpriced=0, session_id=SID)
        self.assertEqual(budget.exceeded(self.CFG, self.job(), u)[1:], ("> Kullanım sınırı aşıldı: API karşılığı ~$3.20 / ~$3.00", "butce-a-3"))

    def test_usage_is_recorded_on_meaningful_change_only(self):
        u = budget.Usage(cost=0.03, calls=3, unpriced=0, session_id=SID)
        self.assertEqual(budget.record_fields({}, u), {"harcanan_usd": "0.03", "cagri": 3, "harcanan_token": 0})
        meta = {"harcanan_usd": "0.03", "cagri": "3"}
        self.assertIsNone(budget.record_fields(meta, budget.Usage(0.07, 9, 0, SID)))
        self.assertEqual(budget.record_fields(meta, budget.Usage(0.08, 9, 0, SID, tokens=5000)),
                         {"harcanan_usd": "0.08", "cagri": 9, "harcanan_token": 5000})
        self.assertEqual(budget.record_fields(meta, budget.Usage(0.04, 13, 0, SID))["cagri"], 13)
        self.assertEqual(budget.record_fields(meta, budget.Usage(0.04, 4, 0, SID), force=True),
                         {"harcanan_usd": "0.04", "cagri": 4, "harcanan_token": 0})
        self.assertIsNone(budget.record_fields(meta, budget.Usage(0.03, 3, 0, SID), force=True))
        # the final record also catches a token count that changed (or was never written) on its own
        self.assertEqual(budget.record_fields(meta, budget.Usage(0.03, 3, 0, SID, tokens=7), force=True)["harcanan_token"], 7)
        self.assertIsNone(budget.record_fields({**meta, "harcanan_token": "7"}, budget.Usage(0.03, 3, 0, SID, tokens=7),
                                               force=True))


class MoneyTest(unittest.TestCase):
    """Review finding 12: a $0.002 budget was printed "$0.00" and the CEO told the owner the budget was 0 dollars."""

    def test_small_amounts_keep_their_significant_digits(self):
        for value, text in ((0.002, "0.002"), (0.0123, "0.0123"), (0.00612, "0.00612"), (0.05, "0.05"),
                            (0.0567, "0.0567"), (0.1, "0.10"), (1.234, "1.23"), (3, "3.00"), (0, "0.00"),
                            (0.00004, "0.00004")):
            self.assertEqual(budget.usd(value), text, value)

    def test_the_budget_line_shows_a_small_budget(self):
        job = jobs.Job("a.md", jobs.ACTIVE, "", {"katman": "kolay", "butce_usd": "0.002"}, "")
        u = budget.Usage(cost=0.0061, calls=2, unpriced=0, session_id=SID)
        self.assertEqual(budget.exceeded({}, job, u)[1], "> Kullanım sınırı aşıldı: API karşılığı ~$0.0061 / ~$0.002")

    def test_recorded_cost_keeps_four_decimals(self):
        self.assertEqual(budget.record_fields({}, budget.Usage(0.0061, 2, 0, SID)),
                         {"harcanan_usd": "0.0061", "cagri": 2, "harcanan_token": 0})
        self.assertEqual(budget.record_fields({"harcanan_usd": "0.0061", "cagri": "2"},
                                              budget.Usage(0.0064, 2, 0, SID), force=True),
                         {"harcanan_usd": "0.0064", "cagri": 2, "harcanan_token": 0})


class TokenTextTest(unittest.TestCase):
    """Token counts next to the dollars (Turkish compact form; the page's twin is tokenMetni in web/ofis-text.js)."""

    CASES = ((0, "0 token"), (850, "850 token"), (999, "999 token"), (1000, "1 bin token"), (12_400, "12,4 bin token"),
             (99_949, "99,9 bin token"), (182_400, "182 bin token"), (999_499, "999 bin token"),
             (999_500, "1 mn token"), (1_200_000, "1,2 mn token"), (15_300_000, "15,3 mn token"),
             (250_000_000, "250 mn token"), (182_500, "183 bin token"), (1_250_000, "1,3 mn token"),
             (12_450, "12,5 bin token"), (99_950, "100 bin token"))  # half-up, like the page

    def test_compact_turkish_form(self):
        for value, text in self.CASES:
            self.assertEqual(budget.token_text(value), text, value)
            self.assertEqual(budget.token_text(str(value)), text, value)

    def test_unknown_is_empty_never_zero(self):
        for value in (None, "", "x", -5, float("nan"), True):
            self.assertEqual(budget.token_text(value), "", value)
            self.assertIsNone(budget.token_count(value), value)

    def test_dollars_with_tokens(self):
        self.assertEqual(budget.spend_text(0.41, 182_000), "182 bin token · API karşılığı ~$0.41")
        self.assertEqual(budget.spend_text(0.41, ""), "API karşılığı ~$0.41")


if __name__ == "__main__":
    unittest.main()
