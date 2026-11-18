"""List-price estimate of a model call, in USD, from its transcript usage record.

This is an *estimate at Anthropic API list prices*: on a Claude subscription nothing is billed per token (usage counts
against the plan's limits instead). Prices are USD per million tokens, from the Claude API skill's model table
(cached 2026-11-03); update PRICES_AS_OF and the table when prices change.

- cache writes: 1.25x the input price for the 5-minute TTL, 2x for the 1-hour TTL (Claude Code writes 1-hour);
  the TTL split comes from usage.cache_creation; without it the 5-minute price is assumed;
- cache reads: the model's listed cache-read price where the table names one, else 0.1x input;
- fast mode (usage.speed == "fast"): 2x the standard prices;
- Claude Haiku 5.5: prompts over 100K tokens use the higher tier ($0.50 / $2.50).
"""

PRICES_AS_OF = "2026-11-03"

# model id prefix -> (input, output, cache read or None for 0.1x input)
PRICES = {
    "claude-fable-5-2": (8.00, 40.00, 0.20),
    "claude-mythos-5-2": (8.00, 40.00, 0.20),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-mythos-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, None),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, None),
    "claude-opus-4-8": (5.00, 25.00, None),
    "claude-opus-4-7": (5.00, 25.00, None),
    "claude-opus-4-6": (5.00, 25.00, None),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-sonnet-5": (2.00, 10.00, None),
    "claude-sonnet-4-6": (3.00, 15.00, None),
    "claude-haiku-5-5": (0.10, 0.50, None),
    "claude-haiku-4-5": (1.00, 5.00, None),
}
HAIKU_5_5_LONG = (0.50, 2.50)
HAIKU_LONG_PROMPT = 100_000
FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _int(value):
    return value if isinstance(value, int) and value > 0 else 0


def _rates(model):
    """Longest matching id prefix, so "claude-opus-5-5" never falls back to "claude-opus-5"."""
    if not isinstance(model, str):
        return None, None
    best = None
    for key in PRICES:
        if (model == key or model.startswith(key + "-")) and (best is None or len(key) > len(best)):
            best = key
    return best, PRICES.get(best)


def call_cost(model, usage):
    """{field: usd, ..., "total": usd} for one call, or None when the model has no known price."""
    key, rates = _rates(model)
    if rates is None:
        return None
    usage = usage if isinstance(usage, dict) else {}
    tokens = {f: _int(usage.get(f)) for f in FIELDS}
    inp, out, read = rates
    prompt = tokens["input_tokens"] + tokens["cache_read_input_tokens"] + tokens["cache_creation_input_tokens"]
    if key == "claude-haiku-5-5" and prompt > HAIKU_LONG_PROMPT:
        inp, out = HAIKU_5_5_LONG
        read = None
    read = read if read is not None else inp * 0.1
    factor = 2.0 if usage.get("speed") == "fast" else 1.0

    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    w1 = _int(split.get("ephemeral_1h_input_tokens"))
    w5 = _int(split.get("ephemeral_5m_input_tokens"))
    if w1 + w5 == 0:
        w5 = tokens["cache_creation_input_tokens"]  # no TTL split recorded: assume the 5-minute price

    per_m = 1_000_000
    cost = {
        "input_tokens": tokens["input_tokens"] * inp * factor / per_m,
        "output_tokens": tokens["output_tokens"] * out * factor / per_m,
        "cache_creation_input_tokens": (w5 * inp * 1.25 + w1 * inp * 2.0) * factor / per_m,
        "cache_read_input_tokens": tokens["cache_read_input_tokens"] * read * factor / per_m,
    }
    cost["total"] = sum(cost.values())
    return cost
