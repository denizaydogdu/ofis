"""The owner's privacy rules (plan "2. Aşama"): ofis.json `guvenlik`, read by every check that used to hard-code them.

    "guvenlik": {"yasak_yollar": ["..."], "ozel_klasorler": ["..."], "yasak_kelimeler": ["..."]}

- yasak_yollar: plain names of folders outside the office. A path component that is the name, or the name followed by
  `-`, `.`, `_` or a space and anything (`name-old`, `name.bak`), is forbidden (launch.is_forbidden_path, which
  bin/ofis.py, the post office, the state, the transcripts, the Kontrol, the review panel, … go through); in free
  text (the guard's command check, the Komuta masası) the name as a whole word counts.
- ozel_klasorler: names of the vault's private folders (`/<name>/` in a path; a bare word in a shell command or a step
  name). The guard also protects `<vault>/<name>` against destructive commands.
- yasak_kelimeler: words a file or folder name must not contain (the guard and the Komuta masası: any path or command
  holding one is refused). bin/hafiza_saglik.py adds them to its own fixed list of password-store words.
Entries are plain words; matching folds case and script exactly as before (NFKC, casefold, Turkish dotted and dotless
i as plain i), so "GİZLİ", "gizli" and "Gizli" are one rule. An entry written as a path (`~/Dev/x`) counts by its last
component (a wider rule, never a narrower one). A missing field takes VARSAYILAN's value; a missing key takes all of
VARSAYILAN (a neutral install: only the generic credential words).

Reading: kurallar() reads ofis_json() (this repository's ofis.json, the file the server and bin/ofis.py use; CONFIG
when a test sets it) and caches the
compiled rules by the file's identity (inode, size, mtime). It fails closed:
- only a MISSING file (a fresh clone) means VARSAYILAN (a process that already read good rules keeps those);
- a file that is unreadable, not valid JSON, not an object, or whose `guvenlik` is malformed (a typo such as
  `yasak_yolar`, a string or null instead of a list, an unknown field) keeps the LAST GOOD rules of this process and
  logs the error to stderr once (until the file reads well again); with no last good rules it raises Bozuk. A
  long-running process got its first good rules through launch.load, which refuses such a file; the guard hook is a
  fresh process per call, so a broken file makes it block every guarded call (exit 2).

Test-only override: with OFIS_TEST=1 and OFIS_CONFIG naming a file inside the system temp directory, ofis_json() is
that file instead of this repository's ofis.json, for every reader of the configuration (these rules, bin/sahip.py's
name, bin/guard.py's vault roots, launch.load's default) and every child process (they inherit the environment). The
tests point it at a file with neutral values (test/sahip_yasaklari.py), so they never depend on the owner's own file.
Why it cannot weaken the live office: docs/gelistirici/guvenlik.md "The test-only config override".

EK_ENV (`OFIS_EK_YASAKLAR`, a JSON object with the same fields) only ADDS rules, never removes one, as bin/guard.py's
OFIS_GUARD_EK_KASA adds vault roots.

Standard library only: bin/guard.py imports this module in its hook process.
"""
import json
import os
import re
import sys
import tempfile
import threading
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_CONFIG = os.path.join(ROOT, "ofis.json")  # this repository's ofis.json: the office's one configuration
CONFIG = None  # a test may point this module (only) at a file of its own; None = ofis_json()
# The test-only override (see ofis_json): both must be set, and the file must lie in the system temp directory.
TEST_CONFIG_ENV = "OFIS_CONFIG"
TEST_ENV = "OFIS_TEST"
KEY = "guvenlik"
ALANLAR = ("yasak_yollar", "ozel_klasorler", "yasak_kelimeler")
VARSAYILAN = {"yasak_yollar": [], "ozel_klasorler": [],
              "yasak_kelimeler": ["sifre", "şifre", "parola", "password", "passwd", "keychain"]}
EK_ENV = "OFIS_EK_YASAKLAR"
MAX_GIRDI = 200  # entries per field
MAX_UZUNLUK = 200  # characters per entry
NEVER = re.compile(r"(?!)")


def _temp_kokleri():
    roots = []
    for d in (tempfile.gettempdir(), "/tmp"):
        real = os.path.realpath(d)
        if real not in roots and real != os.sep:
            roots.append(real)
    return roots


def test_config():
    """The test-only config file, or None: the real path of $OFIS_CONFIG when $OFIS_TEST is "1" and that file lies
    inside the system temp directory (tempfile.gettempdir() or /tmp); anything else is ignored, so the live office
    always reads this repository's ofis.json."""
    raw = os.environ.get(TEST_CONFIG_ENV)
    if not raw or os.environ.get(TEST_ENV) != "1":
        return None
    path = os.path.realpath(os.path.expanduser(raw))
    for root in _temp_kokleri():
        if path.startswith(root + os.sep):
            return path
    return None


def ofis_json():
    """The ofis.json every reader of the office's configuration uses (launch.load's default, bin/sahip.py, the guard's
    vault roots, these rules): this repository's file, or the test-only override (test_config)."""
    return test_config() or REPO_CONFIG


def temiz_ortam(env=None):
    """A copy of env (default os.environ) without the test-only override's variables: every session or reviewer the
    office starts (claude, codex, opencode, agy, a Kontrol command) gets this, so a test config can never reach one."""
    return {k: v for k, v in (os.environ if env is None else env).items() if k not in (TEST_CONFIG_ENV, TEST_ENV)}


def test_ortami_var():
    """True when either variable of the test-only override is set (server.main refuses to start then)."""
    return bool(os.environ.get(TEST_CONFIG_ENV) or os.environ.get(TEST_ENV))


def fold(text):
    """Case- and script-insensitive form: NFKC, casefold, Turkish dotted/dotless i mapped to plain i."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return folded.replace("i̇", "i").replace("ı", "i")


class Hatali(ValueError):
    """A `guvenlik` value of the wrong shape. `alan` names the bad field ("guvenlik" for the whole value), `tr` says
    what is wrong in plain Turkish (launch.load's refusal)."""

    def __init__(self, message, alan="guvenlik", tr=""):
        super().__init__(message)
        self.alan, self.tr = alan, tr or message


class Bozuk(Exception):
    """ofis.json exists but its rules cannot be read (bad JSON, not an object, a malformed `guvenlik`) and this process
    has no last good rules. Deliberately not a ValueError or OSError, so no `except ValueError` treats it as "allowed"."""


def _girdiler(value, alan):
    """The cleaned entries of one field: strings, stripped, an entry written as a path by its last component."""
    if not isinstance(value, list) or len(value) > MAX_GIRDI:
        raise Hatali(f"{alan} must be a list of at most {MAX_GIRDI} names", alan,
                     f"en fazla {MAX_GIRDI} addan oluşan bir liste olmalı (ör. [\"ad\"])")
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) > MAX_UZUNLUK:
            raise Hatali(f"{alan}: every entry must be text of at most {MAX_UZUNLUK} characters", alan,
                         f"her girdisi en fazla {MAX_UZUNLUK} karakterlik bir metin olmalı")
        item = item.strip()
        if alan != "yasak_kelimeler" and ("/" in item or os.sep in item):
            parts = [p for p in re.split(r"[/\\]", item) if p.strip() and p.strip() not in (".", "..", "~")]
            item = parts[-1].strip() if parts else ""
        if item and item not in out:
            out.append(item)
    return out


def dogrula(value):
    """The `guvenlik` value as {field: [entries]} (missing fields from VARSAYILAN); raises Hatali on a wrong shape."""
    if not isinstance(value, dict):
        raise Hatali("guvenlik must be an object", "guvenlik",
                     "bir nesne olmalı: {\"yasak_yollar\": [], \"ozel_klasorler\": [], \"yasak_kelimeler\": []}")
    unknown = sorted(set(value) - set(ALANLAR), key=str)
    if unknown:
        names = ", ".join(map(str, unknown))
        raise Hatali("guvenlik: unknown field(s) " + names, names,
                     "tanınmayan alan (geçerli alanlar: " + ", ".join(ALANLAR) + ")")
    return {alan: _girdiler(value[alan], alan) if alan in value else list(VARSAYILAN[alan]) for alan in ALANLAR}


def _alternatif(words):
    return "|".join(re.escape(w) for w in sorted(set(words), key=lambda w: (-len(w), w)))


def _derle(pattern, words):
    return re.compile(pattern.format(_alternatif(words))) if words else NEVER


class Kurallar:
    """The compiled rules. Every pattern is meant for text already folded with fold()."""

    def __init__(self, ayar):
        self.ayar = {alan: tuple(ayar.get(alan) or ()) for alan in ALANLAR}
        self.yollar = tuple(dict.fromkeys(fold(w) for w in self.ayar["yasak_yollar"]))
        self.klasorler = self.ayar["ozel_klasorler"]  # as written: the guard joins them to the vault root
        self.klasor_katlari = tuple(dict.fromkeys(fold(w) for w in self.klasorler))
        self.kelimeler = tuple(dict.fromkeys(fold(w) for w in self.ayar["yasak_kelimeler"]))
        # a path component that is a forbidden name, or the name followed by a separator (name-old, name.bak, name_x)
        self.bilesen = _derle(r"(?:{})(?:[-._ ].*)?", self.yollar)
        # the name as a word in free text (a command, a step's target)
        self.yol_kelimesi = _derle(r"(?<![a-z0-9])(?:{})(?![a-z0-9])", self.yollar)
        # a private folder as a path segment: `/mektuplar/`, `/tapu` at the end, `/sigorta'`
        self.klasor_yolu = _derle(r"/(?:{})(?:/|$|['\"\s])", self.klasor_katlari)
        # in a shell command the folder may be a relative path segment: `cat <name>/x`, `ls <name>`, `cd <name> && ls`
        self.klasor_kabukta = _derle(r"(?:^|[\s'\"=:(<>|;&/])(?:{})(?=$|[/\s'\";&|)<>])", self.klasor_katlari)
        # a private folder as a bare word (a base name or a command word has no leading "/")
        self.klasor_kelimesi = _derle(r"(?<![a-z0-9])(?:{})(?![a-z0-9])", self.klasor_katlari)
        # a credential word anywhere in a name or command
        self.kelime = _derle(r"(?:{})", self.kelimeler)

    def yasak_bilesen(self, part):
        return bool(part) and bool(self.bilesen.fullmatch(fold(part)))

    def yasak_yol(self, path):
        """True when any component of the path is a forbidden name (yasak_yollar)."""
        return isinstance(path, str) and any(self.yasak_bilesen(p) for p in path.split(os.sep) if p)

    def yol_adi(self):
        """The forbidden names for a message ("ZIM"), or "" without any."""
        return "/".join(w.upper() for w in self.yollar)

    def klasor_adi(self):
        """The private folders for a message ("Mektuplar/, TAPU/ and SİGORTA/"), or "" without any."""
        parts = [f"{k}/" for k in self.klasorler]
        return parts[0] if len(parts) == 1 else (", ".join(parts[:-1]) + " and " + parts[-1] if parts else "")


def _ek():
    """The rules EK_ENV adds ({field: [entries]}), {} without a usable value."""
    raw = os.environ.get(EK_ENV)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return {alan: _girdiler(value[alan], alan) for alan in ALANLAR if isinstance(value, dict) and alan in value}
    except (ValueError, Hatali):
        return {}


def _birlestir(ayar, ek):
    return {alan: list(dict.fromkeys(list(ayar.get(alan) or []) + list(ek.get(alan) or []))) for alan in ALANLAR}


def oku(path):
    """The file's `guvenlik` as {field: [entries]}; VARSAYILAN when the file has no such key. Raises
    FileNotFoundError for a missing file, OSError for an unreadable one, ValueError (Hatali for a wrong shape) for bad
    JSON or a malformed `guvenlik`."""
    with open(path, encoding="utf-8") as f:
        try:
            cfg = json.load(f)
        except ValueError as exc:  # also UnicodeDecodeError
            raise Hatali(f"ofis.json is not valid JSON ({exc})", "ofis.json", "geçerli bir JSON değil") from None
    if not isinstance(cfg, dict):
        raise Hatali("ofis.json is not an object", "ofis.json", "bir JSON nesnesi değil")
    return dogrula(cfg[KEY]) if KEY in cfg else {alan: list(v) for alan, v in VARSAYILAN.items()}


_lock = threading.Lock()
# son_iyi: path -> the last good {field: [entries]}; bildirilen: path -> the error last logged for it
_cache = {"anahtar": None, "kurallar": None, "son_iyi": {}, "bildirilen": {}}


def _kimlik(path):
    try:
        st = os.stat(path)
        return (st.st_ino, st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def kurallar(path=None):
    """The rules in force (see the module doc): CONFIG's `guvenlik` (or the last good one), plus EK_ENV."""
    path = path or CONFIG or ofis_json()
    anahtar = (path, _kimlik(path), os.environ.get(EK_ENV, ""))
    with _lock:
        if _cache["anahtar"] == anahtar:  # also a missing file: it is read again once it appears (a new identity)
            return _cache["kurallar"]
        try:
            ayar = oku(path)
            _cache["son_iyi"][path] = ayar
            _cache["bildirilen"].pop(path, None)
        except FileNotFoundError:  # a fresh clone; a process that read good rules keeps them
            ayar = _cache["son_iyi"].get(path) or {alan: list(v) for alan, v in VARSAYILAN.items()}
        except (OSError, ValueError) as exc:
            neden = f"{path}: {exc}"
            ayar = _cache["son_iyi"].get(path)
            if ayar is None:
                raise Bozuk(neden) from None
            if _cache["bildirilen"].get(path) != neden:  # once per error, until the file reads well again
                _cache["bildirilen"][path] = neden
                print(f"ofis.json guvenlik is malformed: {neden}; keeping the last good rules.", file=sys.stderr,
                      flush=True)
        out = Kurallar(_birlestir(ayar, _ek()))
        _cache["anahtar"], _cache["kurallar"] = anahtar, out
        return out


def sifirla():
    """Forgets the cache and the last good values (tests)."""
    with _lock:
        _cache.update(anahtar=None, kurallar=None, son_iyi={}, bildirilen={})
