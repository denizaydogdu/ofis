"""Tests for bin/pricing.py: list-price estimate of one model call from its usage record."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import pricing  # noqa: E402


def usage(i=0, o=0, read=0, w5=0, w1=0, speed="standard"):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": w5 + w1,
            "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}, "speed": speed}


class PricingTest(unittest.TestCase):
    def test_opus_5_5_real_call(self):
        # first call of the real blog session: 1h cache writes
        c = pricing.call_cost("claude-opus-5-5", usage(i=2, o=215, read=28388, w1=38452))
        self.assertAlmostEqual(c["input_tokens"], 2 * 4 / 1e6)
        self.assertAlmostEqual(c["output_tokens"], 215 * 20 / 1e6)
        self.assertAlmostEqual(c["cache_read_input_tokens"], 28388 * 0.20 / 1e6)
        self.assertAlmostEqual(c["cache_creation_input_tokens"], 38452 * 8 / 1e6)  # 1h write = 2x input
        self.assertAlmostEqual(c["total"], sum(v for k, v in c.items() if k != "total"))

    def test_five_minute_writes_cost_1_25x(self):
        c = pricing.call_cost("claude-opus-5-5", usage(w5=1_000_000))
        self.assertAlmostEqual(c["cache_creation_input_tokens"], 5.0)

    def test_missing_ttl_breakdown_assumes_5_minutes(self):
        c = pricing.call_cost("claude-opus-5-5", {"cache_creation_input_tokens": 1_000_000})
        self.assertAlmostEqual(c["cache_creation_input_tokens"], 5.0)

    def test_fast_mode_doubles_opus_5_5(self):
        c = pricing.call_cost("claude-opus-5-5", usage(i=1_000_000, o=1_000_000, speed="fast"))
        self.assertAlmostEqual(c["total"], 8 + 40)

    def test_explicit_cache_read_prices(self):
        self.assertAlmostEqual(pricing.call_cost("claude-sonnet-5-5", usage(read=1_000_000))["total"], 0.10)
        self.assertAlmostEqual(pricing.call_cost("claude-fable-5-1", usage(read=1_000_000))["total"], 0.25)
        self.assertAlmostEqual(pricing.call_cost("claude-sonnet-5", usage(read=1_000_000))["total"], 0.20)  # 0.1x

    def test_haiku_5_5_long_prompt_tier(self):
        short = pricing.call_cost("claude-haiku-5-5", usage(i=50_000, o=1_000_000))
        self.assertAlmostEqual(short["output_tokens"], 0.50)
        long = pricing.call_cost("claude-haiku-5-5", usage(i=150_000, o=1_000_000))
        self.assertAlmostEqual(long["output_tokens"], 2.50)
        self.assertAlmostEqual(long["input_tokens"], 150_000 * 0.50 / 1e6)

    def test_unknown_model_has_no_price(self):
        self.assertIsNone(pricing.call_cost("gpt-x", usage(i=10)))
        self.assertIsNone(pricing.call_cost("<synthetic>", usage(i=10)))
        self.assertIsNone(pricing.call_cost(None, usage(i=10)))

    def test_bad_usage_values_are_ignored(self):
        c = pricing.call_cost("claude-opus-5-5", {"input_tokens": "x", "output_tokens": None, "cache_creation": "?"})
        self.assertEqual(c["total"], 0)


if __name__ == "__main__":
    unittest.main()
