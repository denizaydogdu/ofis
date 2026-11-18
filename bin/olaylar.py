"""The server's error and important-event record in the vault — deterministic, no model call.

    OFIS/Sunucu/Hatalar-YYYY-MM.md   one markdown table per month: İlk görülme | Son görülme | Sayı | Tür | İleti

Only errors and important events are kept, never the request lines or the routine post-office lines: the server
start (pid, port), the Obsidian access error, the errors the post office, dispatcher, Kontrol, workflow, scheduler,
karne and report loops already log (`Olaylar.stream` wraps their log stream and picks those lines), rejected inbox /
outbox files, failed or unconfirmed deliveries (the CEO's and the project channels' last_error, sampled on change),
page refresh failures and a crash of the server loop.
The same (Tür, normalised İleti — digits, hex ids and temp paths replaced) within a month updates Son görülme and Sayı
of its row in place. An İleti is plain text of our own code (an error class and message), at most 200 characters
(a delivery event `teslim` up to 520: it may carry the masked output tail of an unrecognised claude launch),
with `|` and newlines removed and credential-like values masked; never a project's quoted text.
Writes are atomic (jobs._write_atomic), only a plain file under OFIS/Sunucu/ (a symlinked folder or file is refused),
at most every FLUSH_SECONDS, or at once for a new row. An existing month file is read back at start, so counts go on
across restarts. When the vault cannot be written the server goes on; the reason is printed to the local log once.
Server-generated: the CEO reads it, nobody edits it.
"""
import os
import re
import sys
import threading
import time
from datetime import datetime

import jobs

FOLDER = "Sunucu"
MAX_TEXT = 200
# a delivery event may carry the masked output tail of an unrecognised claude launch (claude_cli.TAIL_LIMIT = 300)
# after its own sentence and the session name: that kind keeps a longer text, the others stay at MAX_TEXT
KIND_LIMITS = {"teslim": 520}
MAX_ROWS = 500  # new kinds beyond this in one month are not added (the counts of existing rows still go on)
FLUSH_SECONDS = 30.0
POLL_SECONDS = 5.0
COLUMNS = ("İlk görülme", "Son görülme", "Sayı", "Tür", "İleti")
INTRO = "Sunucunun hata ve önemli olay kaydı; sunucu yazar, elle düzenlenmez."
ROW = re.compile(r"^\| (\d{4}-\d\d-\d\d \d\d:\d\d) \| (\d{4}-\d\d-\d\d \d\d:\d\d) \| (\d+) \| ([^|]*?) \| ([^|]*?) \|$")

# a value after one of these words is replaced by *** (an error text must never carry a credential)
MASK_WORDS = ("token", "passwd", "parola", "şifre", "secret", "api_key", "apikey", "authorization", "pass" + "word")
# the key may be quoted (JSON / Python-dict style: "token": "abc", 'password': 'x'); a quoted value honours backslash
# escapes and an unterminated one is masked to the end; a bare value is masked up to the next whitespace (over-masking
# — e.g. "x&y=z" whole — is acceptable, a leak is not)
# a compound key counts too (access_token, client_secret, ANTHROPIC_API_KEY, x-api-key, Cookie, credentials, auth…):
# since 2026-11-13 untrusted claude output (an unrecognised launch's tail) passes through here
MASK_KEY = r"[\w-]*(?:" + "|".join(MASK_WORDS) + r"|api[_-]?key|cookie|credential|auth)[\w-]*"
MASK_AFTER = re.compile(r"""(?i)\b(""" + MASK_KEY + r""")(["']?)\s*[=:]\s*(?!["']?Bearer\b)"""
                        r"""(?:"(?:[^"\\]|\\.)*(?:"|$)|'(?:[^'\\]|\\.)*(?:'|$)|\S+)""")
BEARER = re.compile(r"(?i)\bBearer\s+\S+")
SK_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
# well-known key shapes without a key word in front (GitHub, Slack, AWS access key id, a JWT)
BILINEN_BICIM = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[abprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{16}|eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*)")
TEMP_PATH = re.compile(r"(/private)?/(tmp|var/folders)/\S+")
HOME_PATH = re.compile(r"/(?:Users|home)/[^/\s]+/")
# Text a project controls never reaches the note: the name of a rejected inbox file and the folder a report claims
# to come from are replaced by a word; only our own reason stays.
REJECTED_FILE = re.compile(r"(rejected) \S+?: ")
SENT_FROM = re.compile(r"sent from .*?, outside the job's working folder.*$")
HEX_ID = re.compile(r"\b[0-9a-f]{8,}(-[0-9a-f]{4,})*\b", re.I)
DIGITS = re.compile(r"\d+")

# Which logged lines are kept (the rest are routine): (pattern, Tür). The first match wins.
LINE_KINDS = (
    (re.compile(r"^ofis post office: rejected "), "reddedildi"),
    (re.compile(r"reddedilen|^ofis post office: outbox "), "giden"),
    (re.compile(r"unconfirmed|doğrulanamadı"), "teslim"),
    (re.compile(r"\b[A-Z]\w*(Error|Exception)\b|\bcannot\b|\bnot written\b|\brefused\b|\bfailed\b(?! \(attempt)|"
                r"\bHATA\b"), "hata"),
)


def maskele(text):
    """Credential-like values, home folders and temp paths masked; nothing else changed (no cap, no escaping). Also
    used by claude_cli for the output tail of an unrecognised launch."""
    t = BEARER.sub("Bearer ***", str(text if text is not None else ""))
    t = SK_KEY.sub("sk-***", t)
    t = BILINEN_BICIM.sub("***", t)
    t = MASK_AFTER.sub(lambda m: f"{m.group(1)}{m.group(2)}=***", t)  # "token=abc", "token: abc", '"token": "abc"'
    t = TEMP_PATH.sub("‹geçici›", t)
    return HOME_PATH.sub("~/", t)  # a home folder names the user: "/Users/<name>/x" -> "~/x"


def clean(text, limit=MAX_TEXT):
    """One line of plain text, masked and capped."""
    t = re.sub(r"\s+", " ", str(text if text is not None else "")).strip().replace("|", "/")
    t = REJECTED_FILE.sub(r"\1 (dosya): ", t)
    t = SENT_FROM.sub("sent from (klasör), outside the job's working folder", t)
    t = maskele(t)
    # never a wikilink, a tag or HTML in the note (like karne.excerpt)
    t = t.replace("[", "［").replace("]", "］").replace("<", "‹").replace(">", "›").replace("`", "'")
    return t if len(t) <= limit else t[:limit - 1] + "…"


def limit_of(kind):
    return KIND_LIMITS.get(kind, MAX_TEXT)


def key(kind, text):
    norm = HEX_ID.sub("<id>", clean(text, limit_of(kind)))
    return kind, DIGITS.sub("#", norm).lower()


# Turkish failure words of the server's background passes (bin/gunsonu.py, ozet.py, sistem.py, …): their log lines
# are errors only with one of these (or an English error word, LINE_KINDS); the rest — a measurement made, a day
# skipped, an ekle warning — is "bilgi", never a bad case of the end-of-day review (2026-11-15: the measurement line
# itself was counted as a server error the next day).
TR_HATA = re.compile(r"hatası|hatasi|\w+(?:ılamadı|ilemedi|ulamadı|ülemedi|alınamadı|enemedi|anamadı|amadı|emedi)\b|"
                     r"başlatılmadı|başarısız", re.I)


def kind_of_background_line(line):
    """The kind of a background pass's log line: "hata" for a failure, else the LINE_KINDS kind, else "bilgi"."""
    if TR_HATA.search(str(line or "")):
        return "hata"
    return kind_of_line(line) or "bilgi"


def kind_of_line(line):
    for pattern, kind in LINE_KINDS:
        if pattern.search(line):
            return kind
    return None


class _Tee:
    """A log stream: forwards everything to `inner` and records the error lines."""

    def __init__(self, events, inner):
        self.events = events
        self.inner = inner
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, text):
        n = self.inner.write(text)
        lines = []
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                lines.append(line)
        for line in lines:
            kind = kind_of_line(line)
            if kind:
                try:
                    self.events.record(kind, line)
                except Exception:  # the vault record never breaks the log stream
                    pass
        return n

    def flush(self):
        self.inner.flush()

    def fileno(self):
        return self.inner.fileno()


class Olaylar:
    def __init__(self, vault, now=datetime.now, clock=time.monotonic, local=None, flush_seconds=FLUSH_SECONDS):
        self.vault = vault
        self.now = now
        self.clock = clock
        self.local = local  # the local log (stderr when None)
        self.flush_seconds = flush_seconds
        self.lock = threading.Lock()
        self.month = None
        self.rows = {}  # key -> [ilk, son, sayi, tur, ileti]
        self.loaded = False  # the month file was read (or is absent); an existing file is never written unread
        self.dirty = False
        self.flushed_at = None
        self.write_error = None
        self.sources = {}  # name -> (Tür, getter)
        self._seen = {}  # source name -> its last values

    def _say(self, text):
        out = self.local if self.local is not None else sys.stderr
        try:
            out.write(f"ofis: {text}\n")
            out.flush()
        except (OSError, ValueError):
            pass

    def path(self, month):
        return os.path.join(self.vault, FOLDER, f"Hatalar-{month}.md")

    def _read_rows(self, month):
        """The rows of the month file: {} when it does not exist; None when it exists but cannot be read now (e.g.
        macOS refused the vault at start) or is not a plain file."""
        p = self.path(month)
        try:
            if not os.path.lexists(p):
                return {}
            if os.path.islink(p) or not os.path.isfile(p):
                return None
            with open(p, encoding="utf-8") as f:
                text = f.read(1024 * 1024)
        except (OSError, UnicodeDecodeError):  # undecodable: unreadable, so never overwritten
            return None
        rows = {}
        for line in text.splitlines():
            m = ROW.match(line.strip())
            if m:
                first, last, count, kind, msg = m.groups()
                rows.setdefault(key(kind, msg), [first, last, int(count), kind, msg])
        return rows

    def _load(self, month):
        """The rows of an existing month file (counts go on across restarts)."""
        self.month = month
        found = self._read_rows(month)
        self.rows, self.loaded = (found, True) if found is not None else ({}, False)

    def _merge_unread(self):
        """Before the first write of a month whose file could not be read: read it now and add the rows counted
        meanwhile to its rows (each once). False while it still cannot be read."""
        found = self._read_rows(self.month)
        if found is None:
            return False
        for k, row in self.rows.items():
            old = found.get(k)
            if old is None:
                found[k] = row
            else:
                old[0], old[1], old[2], old[4] = min(old[0], row[0]), max(old[1], row[1]), old[2] + row[2], row[4]
        self.rows, self.loaded = found, True
        return True

    def record(self, kind, text):
        """Counts one event; a new row is written at once, a repeat at the next flush."""
        msg = clean(text, limit_of(kind))
        if not msg:
            return
        now = self.now()
        stamp = f"{now:%Y-%m-%d %H:%M}"
        with self.lock:
            month = f"{now:%Y-%m}"
            if month != self.month:
                if self.month is not None and self.dirty:
                    self._flush_locked()
                self._load(month)
            k = key(kind, msg)
            row = self.rows.get(k)
            if row:
                row[1], row[2], row[4] = stamp, row[2] + 1, msg
                self.dirty = True
                return
            if len(self.rows) >= MAX_ROWS:
                return
            self.rows[k] = [stamp, stamp, 1, kind, msg]
            self.dirty = True
            self._flush_locked()

    def son(self, n=5, kinds=None):
        """The newest n rows of this month (by last seen) for the page (the Ofis doktoru's card): [{tur, ileti, sayi,
        son}], plain text, the start event left out (it is not a problem); [] before anything was counted."""
        with self.lock:
            rows = [r for r in self.rows.values() if r[3] != "başlangıç" and (kinds is None or r[3] in kinds)]
        rows.sort(key=lambda r: r[1], reverse=True)
        return [{"tur": r[3], "ileti": r[4][:160], "sayi": r[2], "son": r[1]} for r in rows[:n]]

    def donem(self, bas, son):
        """The rows last seen in the period, newest first, the start event left out: [{tur, ileti, sayi, son}]
        (bin/gunsonu.py, the end-of-day review). The rows carry minutes only, so the rule is on minutes: bas and son
        are "YYYY-MM-DD HH:MM" (the period's ends cut to their minute) and a row counts when bas <= its minute < son —
        half-open, so two periods that meet (one's son is the next one's bas) share no minute and leave none out. This month's rows are the live
        ones; an earlier month the period reaches is read from its file (a file that cannot be read gives nothing).
        sayi is the row's count over its whole month (the record keeps no per-day counts)."""
        months = sorted({bas[:7], son[:7]})
        with self.lock:
            live_month = self.month
            rows = list(self.rows.values()) if live_month in months else []
        for month in months:
            if month != live_month:
                rows += list((self._read_rows(month) or {}).values())
        found = [r for r in rows if r[3] != "başlangıç" and bas <= r[1] < son]
        found.sort(key=lambda r: r[1], reverse=True)
        return [{"tur": r[3], "ileti": r[4], "sayi": r[2], "son": r[1]} for r in found]

    def text(self):
        rows = sorted(self.rows.values(), key=lambda r: r[1], reverse=True)
        lines = ["---", "tags: [ofis, sunucu]", f"ay: {self.month}", "---", "", f"# Sunucu hataları — {self.month}",
                 "", INTRO, "", "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
        lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in rows]
        return "\n".join(lines) + "\n"

    def _flush_locked(self):
        if self.month is None:
            return False
        try:
            if not os.path.isdir(self.vault):
                raise OSError(f"Obsidian klasörü yok: {self.vault}")
            if not self.loaded and not self._merge_unread():
                raise OSError(f"{os.path.basename(self.path(self.month))} okunamadı; üzerine yazılmadı")
            folder = os.path.join(self.vault, FOLDER)
            if os.path.islink(folder):
                raise OSError(f"{FOLDER} bir bağlantı (symlink); yazılmadı")
            os.makedirs(folder, exist_ok=True)
            target = self.path(self.month)
            if os.path.islink(target) or (os.path.lexists(target) and not os.path.isfile(target)):
                raise OSError(f"{os.path.basename(target)} düz bir dosya değil; yazılmadı")
            jobs._write_atomic(target, self.text())
        except OSError as e:
            reason = f"{type(e).__name__}: {e}"
            if reason != self.write_error:
                self._say(f"olay kaydı Obsidian'a yazılamadı: {reason}")
            self.write_error = reason
            self.flushed_at = self.clock()
            return False
        self.write_error = None
        self.dirty = False
        self.flushed_at = self.clock()
        return True

    def flush(self, force=False):
        with self.lock:
            if not self.dirty:
                return False
            if not force and self.flushed_at is not None and self.clock() - self.flushed_at < self.flush_seconds:
                return False
            return self._flush_locked()

    def stream(self, inner):
        return _Tee(self, inner)

    def watch(self, name, kind, getter):
        """Samples getter() (a text, a list or dict of texts, or None) every poll; each new value is one event."""
        self.sources[name] = (kind, getter)

    def poll(self):
        for name, (kind, getter) in list(self.sources.items()):
            try:
                value = getter()
            except Exception:  # a source must never stop the record
                continue
            if isinstance(value, dict):
                value = [f"{k}: {v}" for k, v in sorted(value.items()) if v]
            values = [v for v in (value if isinstance(value, (list, tuple)) else [value]) if v]
            before = self._seen.get(name, [])
            for v in values:
                if v not in before:
                    self.record(kind, v)
            self._seen[name] = values

    def run(self, stop_event, interval=POLL_SECONDS):
        while not stop_event.wait(interval):
            self.poll()
            self.flush()
        self.flush(force=True)
