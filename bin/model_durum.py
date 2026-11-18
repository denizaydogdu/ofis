"""The models' status for the living office page (/api/state.modeller) and the scene settings (/api/state.sahne).

Each model gets a title (Stajyer … Dış denetçi), how many office sessions run on it and one status:
- kota       only on a concrete matched message: for Claude, a usage-limit record in an office transcript (Claude
             Code writes an assistant record with isApiErrorMessage, error "rate_limit", apiError
             "usage_limit_reached" and quotaLimits {status: "rejected", resetsAt: <epoch s>, rateLimitType}; the
             text reads "You've hit your 5-hour limit · resets 4:30pm (Europe/Istanbul)"); for Codex, the strict flag
             codex_kota on the server record of its newest run — set by akis.py only when codex itself exited
             non-zero with a usage-limit line in its last output lines (codex_limit; never from review text), with
             its parsed "try again at …" time (codex_donus) when codex printed one.
             A rateLimitType that names a model (seven_day_opus) covers that model, any other the whole account.
             Every usage-limit record in the tail counts (an older weekly limit may outlive a newer 5-hour one);
             each ends at its reset time, at a later successful call of a covered model, or — with no reset time —
             QUOTA_WITHOUT_RESET after the message; donus = the latest reset time among the active ones. Codex's
             ends at codex_donus (else after QUOTA_WITHOUT_RESET) or at a later successful review.
- hata       another API error (Claude: isApiErrorMessage; Codex: another failure of a run) within ERROR_WINDOW
             (Codex: CODEX_ERROR_WINDOW) and no successful call of that model after it. A Claude error is the
             model's that ran just before it in the same file, else the model of the session's job; "computer went
             to sleep" is not a model error.
- calisiyor  at least one office session (Codex: a running Codex review, even while a quota flag is live) is on it.
- hazir      nothing of the above, and at least one office transcript could be read (Codex: its newest run worked).
- bilinmiyor nothing could be read (no transcript), or for Codex: it never ran, or its newest run failed and that is
             older than the window (an old failure or an expired quota proves nothing either way).

Only office transcripts are scanned (the caller passes the CEO's and the ofis-* sessions' files, and skips a
transcript folder whose "-" encoded name contains a forbidden component: transcript.forbidden_folder). Each
file's tail (TAIL_BYTES) is read again only when its size or mtime changed; the records under durum/isler likewise.

Scene: ofis.json "ofis_sahnesi": {"ogle": "HH:MM-HH:MM", "saat_dilimi": "<IANA zone>"} (defaults 12:00-13:00 and the
system's local zone, yerel_saat_dilimi). The page decides lunch in that zone; server-side times are shown in it (the
system's current fixed offset when the zone data is unavailable). Every module takes its office zone from here.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python without zoneinfo
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass

MODELS = ("haiku", "sonnet", "opus", "fable", "codex")
CLAUDE = MODELS[:4]
UNVAN = {"haiku": "Stajyer", "sonnet": "Uzman", "opus": "Kıdemli", "fable": "Genel Müdür", "codex": "Dış denetçi"}
DEFAULT_OGLE = "12:00-13:00"
FALLBACK_TZ = "UTC"  # when the system's local zone cannot be named
LOCALTIME = "/etc/localtime"  # a link into the zone database on macOS and most Linux systems
TIMEZONE_FILE = "/etc/timezone"  # Debian/Ubuntu: the zone's name on its first line (/etc/localtime may be a plain copy)
OGLE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)")
TAIL_BYTES = 128 * 1024
QUOTA_WITHOUT_RESET = timedelta(hours=5)
ERROR_WINDOW = timedelta(minutes=15)
CODEX_ERROR_WINDOW = timedelta(hours=1)
NOT_MODEL_ERRORS = {"computer_slept"}
QUOTA_TEXT = re.compile(r"hit your [\w -]*limit", re.I)
MAX_TEXT = 200


def family(model):
    """haiku | sonnet | opus | fable | codex for a model id or tier model, else ""."""
    if not isinstance(model, str):
        return ""
    low = model.lower()
    for name in MODELS:
        if name in low:
            return name
    return ""


def yerel_saat_dilimi():
    """The system's local IANA zone (plan "2. Aşama": the default office zone): $TZ when it names a known zone, else
    the zone /etc/localtime links to, else the first line of /etc/timezone (Linux, where /etc/localtime is often a
    plain file), else "UTC". Every name must be one zoneinfo can load (_valid_zone)."""
    names = [os.environ.get("TZ", "").lstrip(":")]
    try:
        link = os.path.realpath(LOCALTIME)
        names.append(link.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in link else "")
    except (OSError, ValueError):
        pass
    try:
        with open(TIMEZONE_FILE, encoding="utf-8") as f:
            names.append(f.readline(256).strip())
    except (OSError, ValueError):
        pass
    for name in names:
        if name and _valid_zone(name):
            return name
    return FALLBACK_TZ


def saat_dilimi(cfg):
    """The office zone's name: ofis.json ofis_sahnesi.saat_dilimi when valid, else the system's local zone."""
    return sahne(cfg)["saat_dilimi"]


def _fixed_local():
    """The system's current UTC offset as a fixed zone (when the zone data is unavailable)."""
    return datetime.now().astimezone().tzinfo


def office_tz(name=None):
    """The office's zone (default: the system's local zone); a fixed zone with the system's current offset when the
    zone data is unavailable."""
    try:
        return ZoneInfo(name or yerel_saat_dilimi()) if ZoneInfo is not None else _fixed_local()
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return _fixed_local()


def _valid_zone(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+){0,2}", name):
        return False
    try:
        ZoneInfo(name) if ZoneInfo is not None else None
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return ZoneInfo is not None


def sahne(cfg):
    """{ogle, saat_dilimi} for the page; invalid or missing values take the defaults."""
    raw = cfg.get("ofis_sahnesi") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    ogle = raw.get("ogle")
    m = OGLE.fullmatch(ogle) if isinstance(ogle, str) else None
    if not m or (m.group(1), m.group(2)) >= (m.group(3), m.group(4)):
        ogle = DEFAULT_OGLE
    zone = raw.get("saat_dilimi")
    return {"ogle": ogle, "saat_dilimi": zone if _valid_zone(zone) else yerel_saat_dilimi()}


def sunucu_ofset_dk(now=None):
    """The server's local UTC offset in minutes at `now` (default: this moment). Job notes carry naive stamps in the
    server's local time (bitis, baslangic); the page reads them with this offset (/api/state.sahne)."""
    now = now if now is not None else datetime.now()
    return int(_aware(now).astimezone().utcoffset().total_seconds() // 60)


def is_lunch(cfg, now):
    """Whether `now` (aware) falls in the lunch hour, in the office zone (start inclusive, end exclusive)."""
    s = sahne(cfg)
    local = now.astimezone(office_tz(s["saat_dilimi"]))
    start, end = s["ogle"].split("-")
    return start <= f"{local:%H:%M}" < end


def parse_time(value):
    """An aware datetime from a transcript timestamp (…Z) or a server stamp (local, naive), else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def _aware(now):
    return now if now.tzinfo else now.astimezone()


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def _short(text):
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def _quota(rec):
    """(resets_at or None, scope) when the record is a usage-limit message, else None."""
    limits = rec.get("quotaLimits")
    if not isinstance(limits, dict):
        params = rec.get("apiErrorParams")
        limits = params.get("rate_limit_info") if isinstance(params, dict) else None
    limits = limits if isinstance(limits, dict) else {}
    text = _text((rec.get("message") or {}).get("content"))
    matched = rec.get("apiError") == "usage_limit_reached" or limits.get("status") == "rejected" or \
        (rec.get("error") == "rate_limit" and QUOTA_TEXT.search(text))
    if not matched:
        return None
    resets = limits.get("resetsAt")
    resets_at = None
    if isinstance(resets, (int, float)) and not isinstance(resets, bool) and resets > 0:
        try:
            resets_at = datetime.fromtimestamp(resets, timezone.utc)
        except (OverflowError, OSError, ValueError):
            resets_at = None
    named = family(str(limits.get("rateLimitType") or ""))
    return resets_at, ((named,) if named in CLAUDE else CLAUDE)


CODEX_LIMIT = re.compile(r"usage[ _]limit|insufficient_quota|you[\u2019']ve hit your", re.I)
CODEX_TAIL_LINES = 20
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}
# codex 0.167 (strings of its binary): "… or try again at %b %-d<st|nd|rd|th>, %Y %-I:%M %p." in its local time
CODEX_AT_DATE = re.compile(r"try again at\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}),?\s+"
                           r"(\d{1,2}):(\d{2})\s*([AP]M)\b", re.I)
CODEX_AT_TIME = re.compile(r"try again at\s+(\d{1,2}):(\d{2})\s*([AP]M)\b", re.I)


def _clock(hour, minute, ampm):
    hour, minute = int(hour), int(minute)
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        raise ValueError("bad time")
    return (hour % 12) + (12 if ampm.upper() == "PM" else 0), minute


def codex_limit(output, exit_code, now, tz):
    """(quota, reset time in tz or None) from codex's own output (stdout + stderr). Strict: only a non-zero exit with
    a usage-limit line among the last CODEX_TAIL_LINES lines; a review text or a diff never counts. The reset time
    is codex's "try again at …" in its (this machine's) local time; a time alone means today, or tomorrow when it
    has passed."""
    if not exit_code or not isinstance(output, str):
        return False, None
    tail = "\n".join(output.strip().splitlines()[-CODEX_TAIL_LINES:])
    if not CODEX_LIMIT.search(tail):
        return False, None
    local_now = _aware(now).astimezone()
    back = None
    try:
        m = CODEX_AT_DATE.search(tail)
        if m:
            month = MONTHS.get(m.group(1).lower())
            if month is None:
                raise ValueError("bad month")
            hour, minute = _clock(m.group(4), m.group(5), m.group(6))
            back = datetime(int(m.group(3)), month, int(m.group(2)), hour, minute).astimezone()
        else:
            m = CODEX_AT_TIME.search(tail)
            if m:
                hour, minute = _clock(*m.groups())
                back = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if back <= local_now:
                    back += timedelta(days=1)
    except (ValueError, OverflowError):
        back = None
    return True, (back.astimezone(tz) if back is not None else None)


def scan_records(records):
    """{quotas: [every usage-limit record], error: the last other API error, ok: {family: last success time},
    model: last family} of a transcript's records in order. All quotas are kept: an older weekly limit may still be
    active while a newer 5-hour one has already reset."""
    out = {"quotas": [], "error": None, "ok": {}, "model": ""}
    for rec in records:
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        when = parse_time(rec.get("timestamp"))
        message = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        if when is None:
            continue
        if rec.get("isApiErrorMessage"):
            text = _short(_text(message.get("content")))
            q = _quota(rec)
            if q is not None:
                out["quotas"].append({"time": when, "resets_at": q[0], "scope": q[1], "text": text})
            elif rec.get("apiError") not in NOT_MODEL_ERRORS:
                out["error"] = {"time": when, "text": text, "model": out["model"]}
            continue
        fam = family(message.get("model"))
        if fam in CLAUDE:
            out["model"] = fam
            out["ok"][fam] = max(when, out["ok"].get(fam, when))
    return out


def tail_lines(path, nbytes=TAIL_BYTES):
    """The complete lines of the file's last nbytes (a line cut at the start is dropped)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - nbytes)
        f.seek(start)
        data = f.read(nbytes)
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]
    return [line.decode("utf-8", errors="replace") for line in lines if line.strip()]


def session_quota_end(path):
    """{anahtar, time, resets_at, scope} when the session's transcript (its tail) ends with a usage-limit record — the
    last assistant record is that error, read the strict way of _quota — else None (no file, another last record, or a
    later answer). anahtar = the record's uuid, else its timestamp (the quota event's key)."""
    try:
        lines = tail_lines(path)
    except OSError:
        return None
    last = None
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("type") == "assistant":
            last = rec
    if last is None or not last.get("isApiErrorMessage"):
        return None
    q = _quota(last)
    when = parse_time(last.get("timestamp"))
    if q is None or when is None:
        return None
    key = last.get("uuid") if isinstance(last.get("uuid"), str) and last["uuid"] else str(last.get("timestamp"))
    return {"anahtar": key[:80], "time": when, "resets_at": q[0], "scope": q[1]}


class TranscriptScanner:
    """scan(path) → scan_records of the file's tail, cached by (mtime, size); None when the file is missing."""

    def __init__(self, tail_bytes=TAIL_BYTES):
        self.tail_bytes = tail_bytes
        self.reads = 0
        self._cache = {}

    def scan(self, path):
        try:
            st = os.stat(path)
        except OSError:
            self._cache.pop(path, None)
            return None
        key = (st.st_mtime_ns, st.st_size)
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        try:
            lines = tail_lines(path, self.tail_bytes)
        except OSError:
            return None
        self.reads += 1
        records = []
        for line in lines:
            if '"assistant"' not in line:
                continue  # only assistant records matter: skip parsing tool results and the rest
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        result = scan_records(records)
        self._cache[path] = (key, result)
        return result


class CodexScanner:
    """events(durum_dir) → [{time, value, kota, donus}] of every server record with a Codex run time (codex_zamani):
    kota = the strict flag (codex_kota, set only on codex's own usage-limit error), donus = its parsed reset time."""

    def __init__(self):
        self.reads = 0
        self._cache = {}

    def events(self, durum_dir):
        folder = os.path.join(durum_dir, "isler")
        out, seen = [], set()
        try:
            entries = [e for e in os.scandir(folder) if e.name.endswith(".json") and e.is_file(follow_symlinks=False)]
        except OSError:
            return []
        for e in entries:
            seen.add(e.path)
            try:
                key = e.stat(follow_symlinks=False).st_mtime_ns
            except OSError:
                continue
            hit = self._cache.get(e.path)
            if hit is None or hit[0] != key:
                event = None
                try:
                    with open(e.path, encoding="utf-8") as f:
                        data = json.loads(f.read(64 * 1024))
                    self.reads += 1
                    when = parse_time(data.get("codex_zamani")) if isinstance(data, dict) else None
                    # the review panel: codex_sonuc is Codex's own outcome (the job may pass without Codex)
                    value = (data.get("codex_sonuc") or data.get("inceleme_yurutucu")) if isinstance(data, dict) \
                        else None
                    if when is not None and isinstance(value, str) and value:
                        event = {"time": when, "value": value, "kota": data.get("codex_kota") == "evet",
                                 "donus": parse_time(data.get("codex_donus"))}
                except (OSError, ValueError, UnicodeDecodeError):
                    event = None
                hit = self._cache[e.path] = (key, event)
            if hit[1] is not None:
                out.append(hit[1])
        for path in set(self._cache) - seen:
            del self._cache[path]
        return out


class DenetciScanner:
    """events(durum_dir) → {reviewer: [{time, durum, hata}]} of the review panel's round files
    (durum/denetciler/turlar/*.json, written by bin/akis.py): one event per reviewer and round, at the round's end."""

    def __init__(self):
        self.reads = 0
        self._cache = {}

    def events(self, durum_dir):
        folder = os.path.join(durum_dir, "denetciler", "turlar")
        out, seen = {}, set()
        try:
            entries = [e for e in os.scandir(folder) if e.name.endswith(".json") and e.is_file(follow_symlinks=False)]
        except OSError:
            return {}
        for e in entries:
            seen.add(e.path)
            try:
                key = e.stat(follow_symlinks=False).st_mtime_ns
            except OSError:
                continue
            hit = self._cache.get(e.path)
            if hit is None or hit[0] != key:
                found = []
                try:
                    with open(e.path, encoding="utf-8") as f:
                        data = json.loads(f.read(256 * 1024))
                    self.reads += 1
                    when = parse_time(data.get("bitis")) if isinstance(data, dict) else None
                    rows = data.get("denetciler") if isinstance(data, dict) else None
                    if when is not None and isinstance(rows, list):
                        found = [(r["ad"], {"time": when, "durum": r.get("durum") or "",
                                            "hata": str(r.get("hata") or "")})
                                 for r in rows if isinstance(r, dict) and isinstance(r.get("ad"), str)]
                except (OSError, ValueError, UnicodeDecodeError):
                    found = []
                hit = self._cache[e.path] = (key, found)
            for name, event in hit[1]:
                out.setdefault(name, []).append(event)
        for path in set(self._cache) - seen:
            del self._cache[path]
        return out


def _denetci(events, calisan, now):
    """A free reviewer of the review panel, from its newest round: a verdict is hazir; a quota (only the strict
    provider.quota / provider.rate-limit error event, bin/denetci.py) is kota for QUOTA_WITHOUT_RESET (OpenCode names
    no reset time); another failure is hata for CODEX_ERROR_WINDOW; then nothing proves either way: bilinmiyor. A
    running review is calisiyor."""
    if calisan:
        return "calisiyor", None, None
    # a reviewer stopped because its hedge partner answered first (bin/denetci.py STOPPED) proves nothing either way
    latest = max((e for e in events if e["durum"] != "durduruldu"), key=lambda e: e["time"], default=None)
    if latest is None:
        return "bilinmiyor", None, None
    if latest["durum"] == "karar":
        return "hazir", None, None
    age = now - latest["time"]
    if latest["durum"] == "kota":
        return ("kota", None, _short(latest["hata"])) if age < QUOTA_WITHOUT_RESET else ("bilinmiyor", None, None)
    if age < CODEX_ERROR_WINDOW:
        return "hata", None, _short(latest["hata"] or latest["durum"])
    return "bilinmiyor", None, None


def _iso(dt, tz):
    return dt.astimezone(tz).isoformat(timespec="minutes") if dt else None


def _claude(fam, scans, calisan, now, tz):
    active = []
    for scan, _ in scans:
        for q in scan.get("quotas", ()):
            if fam not in q["scope"]:
                continue
            live = now < q["resets_at"] if q["resets_at"] is not None else now - q["time"] < QUOTA_WITHOUT_RESET
            cleared = any(t > q["time"] for other, _ in scans for f, t in other.get("ok", {}).items()
                          if f in q["scope"])
            if live and not cleared:
                active.append(q)
    if active:
        newest = max(active, key=lambda q: q["time"])
        back = max((q["resets_at"] for q in active if q["resets_at"] is not None), default=None)
        return "kota", _iso(back, tz), newest["text"]
    error = None
    for scan, fallback in scans:
        e = scan.get("error")
        if e and (e["model"] or family(fallback)) == fam and (error is None or e["time"] > error["time"]):
            error = e
    if error is not None and now - error["time"] < ERROR_WINDOW and \
            not any(scan.get("ok", {}).get(fam) and scan["ok"][fam] > error["time"] for scan, _ in scans):
        return "hata", None, error["text"]
    if calisan:
        return "calisiyor", None, None
    return ("hazir" if scans else "bilinmiyor"), None, None


def _codex(events, calisan, now, tz):
    """From the newest Codex run: a success is hazir; a run with the strict quota flag is kota until its reset time
    (or QUOTA_WITHOUT_RESET without one), then hazir once a named reset time has passed; another failure is hata for CODEX_ERROR_WINDOW. After that nothing proves
    either way: bilinmiyor. A running Codex review is always calisiyor (also while a quota flag is still live: the
    run itself is the newer fact, and the office page shows Codex at work)."""
    if calisan:
        return "calisiyor", None, None
    latest = max(events, key=lambda e: e["time"], default=None)
    if latest is not None and latest["value"] != "codex":
        if latest.get("kota"):
            back = latest.get("donus")
            live = now < back if back is not None else now - latest["time"] < QUOTA_WITHOUT_RESET
            if live:
                return "kota", _iso(back, tz), _short(latest["value"])
            if back is not None:
                # Codex named its own reset time and it has passed: the quota is back (owner decision 2026-11-12)
                return "hazir", None, None
        elif now - latest["time"] < CODEX_ERROR_WINDOW and not calisan:
            return "hata", None, _short(latest["value"])
        return ("calisiyor" if calisan else "bilinmiyor"), None, None
    if calisan:
        return "calisiyor", None, None
    return ("bilinmiyor" if latest is None else "hazir"), None, None


def build(scans, codex_events, calisan, now, tz, denetciler=()):
    """The /api/state.modeller list. scans: [(scan_records result, fallback model of that session)];
    codex_events: CodexScanner.events; calisan: {family: running office sessions}; now: aware (naive = local);
    denetciler: [(free reviewer name, its DenetciScanner events, running now)] — one more row each, after Codex, with
    the same keys (model = the reviewer's name, unvan "Dış denetçi")."""
    now = _aware(now)
    scans = [(s, f) for s, f in scans if s is not None]
    out = []
    for fam in MODELS:
        n = int(calisan.get(fam, 0) or 0)
        if fam == "codex":
            durum, donus, son = _codex(codex_events, n, now, tz)
        else:
            durum, donus, son = _claude(fam, scans, n, now, tz)
        out.append({"model": fam, "unvan": UNVAN[fam], "calisan": n, "durum": durum, "donus": donus,
                    "son_hata": son})
    for name, events, n in denetciler:
        n = int(n or 0)
        durum, donus, son = _denetci(events or [], n, now)
        out.append({"model": name, "unvan": UNVAN["codex"], "calisan": n, "durum": durum, "donus": donus,
                    "son_hata": son})
    return out
