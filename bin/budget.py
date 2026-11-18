"""A job's spending: list-price cost and model calls from its own session transcripts, and its limits.

Cost = pricing.call_cost summed over EVERY day of the session's transcript (a job may run past midnight), plus the
transcripts of that session's subagents (<sessionId>/subagents/*.jsonl, where Claude Code writes them; their calls
are not in the main file). Nothing else counts: other sessions in the same folder, the CEO, another job. The
session is the transcript whose name starts with the job's kisa_id in the transcript folder of its calisma_dizini
(a unique match only — an ambiguous short id is never guessed). A resumed project session may continue in a NEW
transcript that starts with a copy of the earlier history (Claude Code 2.1.322): every id of the job
(oturum_kimlikleri on its server record, plus the one of kisa_id) is read, and a model call is counted once by its
message id across all of these files. Readers are incremental (byte offsets), so a check
reads only what was appended since the last one. Models without a known price count as calls with cost 0
(`unpriced`). Not thread-safe: one meter per thread.

Limits: butce_usd / max_cagri of the job, else ofis.json default_budget_usd / default_max_calls[katman]. Callers pass
the job with its server record overlaid (records.trusted): limits, kisa_id and calisma_dizini come from
durum/isler/<job>.json, never from the vault note, which a project session could edit.

Money in text: usd() keeps small amounts readable ($0.002, $0.0123: three significant digits below $0.10, else two
decimals); recorded amounts (harcanan_usd) keep four decimals (field_usd()).
"""
import math
import os
from collections import namedtuple

import launch
import transcript

# tokens = input + output + cache read + cache creation of the same calls (each call once, like cost and calls)
# danisman_cagri / danisman_hata ({error_code: n}) / danisman_iterasyon: the advisor tool's calls, error results and
# priced sub-inferences across the job's files (bin/danisman.py; each counted once by its id / message id)
Usage = namedtuple("Usage", "cost calls unpriced session_id session_ids tokens danisman_cagri danisman_hata "
                   "danisman_iterasyon", defaults=((), 0, 0, None, 0))
MAX_POLLS = 64  # 4 MB each: a very large backlog is finished on the next check
RECORD_USD = 0.05
RECORD_CALLS = 10


def listed_ids(job):
    """The session ids recorded for a job (oturum_kimlikleri: comma-separated on the overlaid meta), valid ones only."""
    raw = job.meta.get("oturum_kimlikleri") or ""
    if isinstance(raw, (list, tuple)):
        raw = ",".join(str(x) for x in raw)
    return [s.strip() for s in raw.split(",") if transcript.valid_session_id(s.strip()) and len(s.strip()) >= 8]


def base_cost(job):
    """The job's spending outside its session's transcript (records.py on_harcama_usd: the review panel's Claude calls
    before its step fell back to a Claude review; mudur_usd: the managers' answers to its questions, bin/mudur.py);
    0 when missing or invalid."""
    total = 0.0
    for key in ("on_harcama_usd", "mudur_usd"):
        try:
            value = float(job.meta.get(key) or 0)
        except (TypeError, ValueError):
            continue
        total += value if 0 < value < 1000 else 0.0
    return total


def base_tokens(job):
    """The tokens of base_cost's manager calls (records.py mudur_token); 0 when missing or invalid."""
    value = token_count(job.meta.get("mudur_token"))
    return value if value and value < 10 ** 10 else 0


class UsageMeter:
    def __init__(self, projects_dir):
        self.projects_dir = projects_dir
        self._readers = {}  # path -> SessionTranscript

    def session_id(self, job):
        """(current session id, transcript folder): the unique transcript whose name starts with the job's kisa_id."""
        short = job.meta.get("kisa_id") or ""
        cwd = job.meta.get("calisma_dizini") or ""
        if not transcript.valid_session_id(short) or len(short) < 8 or not os.path.isabs(cwd):
            return None, None
        folder = transcript.project_folder(self.projects_dir, cwd)
        try:
            found = [n[:-6] for n in os.listdir(folder)
                     if n.startswith(short) and n.endswith(".jsonl") and transcript.valid_session_id(n[:-6])]
        except OSError:
            return None, None
        return (found[0], folder) if len(found) == 1 else (None, None)

    def session_ids(self, job):
        """(current id or None, every id of the job that has a transcript, folder). A resumed project session may
        continue in a new transcript (a fork that starts with a copy of the old history); all of them belong to the
        job: those recorded in oturum_kimlikleri and the one of kisa_id."""
        current, folder = self.session_id(job)
        cwd = job.meta.get("calisma_dizini") or ""
        if folder is None:
            if not os.path.isabs(cwd):
                return None, [], None
            folder = transcript.project_folder(self.projects_dir, cwd)
        ids = [s for s in listed_ids(job) if os.path.isfile(os.path.join(folder, f"{s}.jsonl"))]
        if current and current not in ids:
            ids.append(current)
        return current, ids, folder

    def _read(self, path):
        reader = self._readers.get(path)
        if reader is None:
            reader = self._readers[path] = transcript.SessionTranscript(path)
        for _ in range(MAX_POLLS):
            if not reader.poll():
                break
        return reader

    def files(self, job):
        """Every transcript file of the job (main files of all its sessions, then their subagents)."""
        _, ids, folder = self.session_ids(job)
        paths = []
        for sid in ids:
            paths.append(os.path.join(folder, f"{sid}.jsonl"))
            sub = os.path.join(folder, sid, "subagents")
            try:
                paths += sorted(os.path.join(sub, n) for n in os.listdir(sub) if n.endswith(".jsonl"))
            except OSError:
                pass
        return paths

    def usage(self, job):
        """Usage of the job's sessions so far, or None when no session/transcript is known yet. A model call is
        counted once by its message id across all files (the fork's copied history is not counted twice)."""
        current, ids, _ = self.session_ids(job)
        if not ids:
            return None
        cost, calls, unpriced, tokens, seen = 0.0, 0, 0, 0, set()
        advisor_calls, advisor_errors, advisor_iter, anon_iter = set(), {}, {}, 0
        for path in self.files(job):
            reader = self._read(path)
            advisor_calls |= reader.advisor_calls
            advisor_errors.update(reader.advisor_errors)
            advisor_iter.update(reader.advisor_iter_by_msg)
            anon_iter += reader.anon_advisor_iter
            for msg_id, call_cost in reader.calls_by_msg.items():
                if msg_id in seen:
                    continue
                seen.add(msg_id)
                calls += 1
                tokens += reader.tokens_by_msg.get(msg_id, 0)
                if call_cost is None:
                    unpriced += 1
                else:
                    cost += call_cost
            cost += reader.anon_cost
            calls += reader.anon_calls
            unpriced += reader.anon_unpriced
            tokens += reader.anon_tokens
        errors = {}
        for code in advisor_errors.values():
            errors[code] = errors.get(code, 0) + 1
        return Usage(cost + base_cost(job), calls, unpriced, current or ids[-1], tuple(ids), tokens + base_tokens(job),
                     len(advisor_calls), errors, sum(advisor_iter.values()) + anon_iter)


def advisor_fields(usage):
    """The advisor counts of a Usage as server-record fields (records.py DANISMAN)."""
    errors = usage.danisman_hata or {}
    return {"danisman_cagri": str(int(usage.danisman_cagri or 0)),
            "danisman_hata": ",".join(f"{k}:{v}" for k, v in sorted(errors.items())),
            "danisman_iterasyon": str(int(usage.danisman_iterasyon or 0))}


def usd(amount):
    """Amount as text for people: below 0.10 three significant digits (0.002, 0.0123, 0.05), else two decimals."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    if value != value or math.isinf(value):
        return str(value)
    if value == 0:
        return "0.00"
    if abs(value) >= 0.1:
        return f"{value:.2f}"
    decimals = min(10, -math.floor(math.log10(abs(value))) + 2)
    whole, _, frac = f"{value:.{decimals}f}".rstrip("0").partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def field_usd(amount):
    """Amount as a recorded field: four decimals, trailing zeros dropped down to two (0.0061, 0.03, 1.234)."""
    whole, _, frac = f"{float(amount):.4f}".partition(".")
    return f"{whole}.{frac.rstrip('0').ljust(2, '0')}"


def _positive(value, kind):
    try:
        number = kind(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 and number == number else None  # also drops nan


def limits(cfg, job):
    """(budget USD or None, call limit or None) of a job."""
    spend = _positive(job.meta.get("butce_usd"), float)
    if spend is None:
        spend = _positive(cfg.get("default_budget_usd"), float)
    calls = _positive(job.meta.get("max_cagri"), int)
    if calls is None:
        calls = launch.default_max_calls(cfg, job.meta.get("katman") or cfg.get("default_tier") or "genel")
    return spend, calls


def exceeded(cfg, job, usage):
    """(kind, Sonuç line, CEO notice key) when the job is over its budget or call limit, else None. The key names the
    limit, so a raised limit that is exceeded again gives a new notice."""
    spend, calls = limits(cfg, job)
    stem = job.name[:-3] if job.name.endswith(".md") else job.name
    if spend is not None and usage.cost > spend:
        return "butce", f"> Kullanım sınırı aşıldı: API karşılığı ~${usd(usage.cost)} / ~${usd(spend)}", f"butce-{stem}-{spend:g}"
    if calls is not None and usage.calls > calls:
        return "cagri", f"> Çağrı sınırı aşıldı: {usage.calls} / {calls}", f"cagri-{stem}-{calls}"
    return None


def record_fields(meta, usage, force=False):
    """{harcanan_usd, cagri, harcanan_token} to write when they changed meaningfully (>= RECORD_USD or >= RECORD_CALLS
    since the recorded values; any change when force, also a missing or different harcanan_token), else None."""
    try:
        spent = float(meta.get("harcanan_usd"))
    except (TypeError, ValueError):
        spent = None
    try:
        calls = int(meta.get("cagri"))
    except (TypeError, ValueError):
        calls = None
    cost = field_usd(usage.cost)
    if spent is None or calls is None:
        changed = usage.calls > 0 or usage.cost > 0 or force
    elif force:
        recorded = token_count(meta.get("harcanan_token"))
        changed = cost != field_usd(spent) or usage.calls != calls or \
            (recorded or 0) != int(usage.tokens or 0)
    else:
        changed = abs(usage.cost - spent) >= RECORD_USD - 1e-9 or abs(usage.calls - calls) >= RECORD_CALLS
    return {"harcanan_usd": cost, "cagri": usage.calls, "harcanan_token": int(usage.tokens or 0)} if changed else None


def token_count(value):
    """A recorded token count (harcanan_token) as int, or None when unknown (a job from before tokens were recorded)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return int(n) if math.isfinite(n) and n >= 0 else None


def _tenths(t):
    """A count of tenths as "12,4" / "1" (no ",0")."""
    return f"{t // 10},{t % 10}" if t % 10 else str(t // 10)


def token_text(value):
    """Turkish compact token count: "850 token", "12,4 bin token", "182 bin token", "1,2 mn token"; "" when unknown
    (never "0 token" for a job whose tokens were not recorded). Rounded half-up in integers, exactly like the page's
    twin tokenMetni in web/ofis-text.js (test_web checks both on the same cases)."""
    n = token_count(value)
    if n is None:
        return ""
    if n < 1000:
        return f"{n} token"
    if n < 999_500:
        tenths = (n + 50) // 100
        return f"{_tenths(tenths) if tenths < 1000 else (n + 500) // 1000} bin token"
    tenths = (n + 50_000) // 100_000
    return f"{_tenths(tenths) if tenths < 1000 else (n + 500_000) // 1_000_000} mn token"


def token_text_en(value):
    """The English twin of token_text (ofis.json dil "en", the page's texts only): "850 tokens", "12.4k tokens",
    "182k tokens", "1.2M tokens"; "" when unknown. The same rounding."""
    n = token_count(value)
    if n is None:
        return ""
    if n < 1000:
        return "1 token" if n == 1 else f"{n} tokens"
    if n < 999_500:
        tenths = (n + 50) // 100
        return f"{_tenths(tenths).replace(',', '.') if tenths < 1000 else (n + 500) // 1000}k tokens"
    tenths = (n + 50_000) // 100_000
    return f"{_tenths(tenths).replace(',', '.') if tenths < 1000 else (n + 500_000) // 1_000_000}M tokens"


def spend_text(usd_value, tokens, dil_kodu="tr"):
    """"182 bin token · API karşılığı ~$0.41" (tokens first; the owner is on a subscription, the dollars are only the
    API-price equivalent), or the dollars alone when the tokens are unknown. dil_kodu "en" (the page's texts):
    "182k tokens · API equivalent ~$0.41"."""
    if dil_kodu == "en":
        t = token_text_en(tokens)
        return f"{t} · API equivalent ~${usd(usd_value)}" if t else f"API equivalent ~${usd(usd_value)}"
    t = token_text(tokens)
    return f"{t} · API karşılığı ~${usd(usd_value)}" if t else f"API karşılığı ~${usd(usd_value)}"
