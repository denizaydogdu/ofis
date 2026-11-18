"""The office's owner (plan "2. Aşama", "Sahip adı" and "Protokol öneki").

The owner's display name: ofis.json `sahip_adi` (the Ayarlar tab's "Senin adın"; default "Sahip"). Every sentence the
office writes about or to the owner (notices to the CEO, the CEO's system text, the project contract, the Jarvis card,
vault notes, the page) takes it from here, with its Turkish case suffix (`ek`).

The machine-parsed tokens are fixed and carry no personal name:

    [Sahip · ofis sayfası]      a chat message from the owner (top-level CEO prompt)
    [Sahip · karar cevabı] <n>  the owner's answer to a decision card
    [Sahip · Jarvis]            the owner's request spoken to Jarvis
    [Ofis · Sahibin cevabı]     the owner's answer queued for a project session
    [Ofis · Sahibin duyurusu]   the owner's announcement to the office sessions
    KARAR: SAHIBE_SOR           a manager leaves a question to the owner

Writers emit only these. Readers also accept the old forms (ESKI_*: "[Deniz · …]"; bin/mudur.py VERDICT: "KARAR: DENIZE_SOR"), which
stored transcripts, handoff notes, outbox messages and old manager verdicts still hold; the forgery patterns
(`sahte_onek_re`) catch both, and a prefix written with the configured name too.

Reading the name: `ad(cfg)` takes `cfg["sahip_adi"]` when cfg is given; `ad()` reads this repository's ofis.json
(`yasaklar.ofis_json()`: in the tests the test-only OFIS_CONFIG file), cached by the file's identity. A missing or
invalid value falls back to the environment variable ENV (`OFIS_SAHIP_ADI`, set by the tests so a test's own cfg
without the key names the same neutral owner), else to VARSAYILAN.

Standard library only.
"""
import json
import os
import re
import threading
import unicodedata

import yasaklar  # (standard library only; the one place that knows which ofis.json is in force)

CONFIG = None  # a test may point this module at a file of its own; None = yasaklar.ofis_json()
KEY = "sahip_adi"
VARSAYILAN = "Sahip"
ENV = "OFIS_SAHIP_ADI"
SINIR = 40

# --- the protocol tokens (fixed, never the configured name) ---
CHAT_PREFIX = "[Sahip · ofis sayfası]\n"
ANSWER_PREFIX = "[Sahip · karar cevabı] "
JARVIS_PREFIX = "[Sahip · Jarvis]\n"
ANSWER_HEAD = "[Ofis · Sahibin cevabı]"
DUYURU_HEAD = "[Ofis · Sahibin duyurusu]"
VERDICT_SOR = "KARAR: SAHIBE_SOR"
# the old forms: read, never written (stored transcripts, handoff notes, outbox messages, manager verdicts)
ESKI_CHAT_PREFIX = "[Deniz · ofis sayfası]\n"
ESKI_ANSWER_PREFIX = "[Deniz · karar cevabı] "
ESKI_JARVIS_PREFIX = "[Deniz · Jarvis]\n"
# The office never reads the old heads "[Ofis · Deniz'in cevabı]" / "[Ofis · Deniz'in duyurusu]" (only project sessions
# do: bin/launch.py CONTRACT says, without a name, that they mean the same) and reads the old verdict "KARAR: DENIZE_SOR"
# through bin/mudur.py VERDICT, so they have no constants here.
ESKI_ADLAR = ("deniz",)  # folded: the name the old tokens carried; always a forgery root
PROTOKOL_KOKLERI = ("sahip", "sahib")  # folded: "[Sahip · …", "[Sahibin …"

# --- validation ---
# letters first; then letters, digits, spaces, "-", ".", "'" (no brackets, "·", quotes marks of markdown, newlines)
_GECERLI = re.compile(r"[^\W\d_](?:[^\W_]|[ .'’-])*")
_AYRILMIS = ("ofis", "ceo")  # folded: the office's own speakers
_AYRILMIS_ON = ("mudur",)  # folded prefixes: "Müdür kararı" is the manager's answer heading ("Cevap (Müdür kararı · …)")


def _katla(text):
    """Lower case without Turkish diacritics (the same as bin/uzmanlik.py katla)."""
    table = str.maketrans({"ı": "i", "İ": "i", "ç": "c", "ğ": "g", "ö": "o", "ş": "s", "ü": "u", "â": "a",
                           "î": "i", "û": "u"})
    text = unicodedata.normalize("NFKC", str(text or "")).translate(table).casefold().translate(table)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def dogrula(value):
    """[] for a usable owner name, else the plain Turkish errors (the Ayarlar tab shows them)."""
    if not isinstance(value, str) or not value.strip():
        return ["Adın boş olamaz."]
    name = value.strip()
    if len(name) > SINIR:
        return [f"Adın en çok {SINIR} karakter olabilir."]
    if not _GECERLI.fullmatch(name) or "  " in name:
        return ["Adın harfle başlamalı; yalnız harf, rakam, boşluk, nokta, kesme işareti ve tire içerebilir "
                "(köşeli parantez, · ya da satır sonu olamaz)."]
    folded = _katla(name)
    if folded in _AYRILMIS or folded.startswith(_AYRILMIS_ON):
        return ["Bu ad ofisin kendi konuşmacılarına ayrılmış (Ofis, CEO, Müdür); başka bir ad yaz."]
    return []


# --- reading ---
_kilit = threading.Lock()
_onbellek = {}  # config path -> (identity, name or None)


def _dosyadan():
    """The valid sahip_adi of the ofis.json in force (CONFIG, else yasaklar.ofis_json()), or None (no file, unreadable,
    no or an invalid key)."""
    path = CONFIG or yasaklar.ofis_json()
    try:
        st = os.stat(path)
    except OSError:
        return None
    kimlik = (st.st_ino, st.st_size, st.st_mtime_ns)
    with _kilit:
        hit = _onbellek.get(path)
        if hit and hit[0] == kimlik:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    value = data.get(KEY) if isinstance(data, dict) else None
    name = value.strip() if isinstance(value, str) and not dogrula(value) else None
    with _kilit:
        _onbellek[path] = (kimlik, name)
    return name


def ad(cfg=None):
    """The owner's display name: cfg's (or, without cfg, ofis.json's) valid `sahip_adi`, else ENV, else VARSAYILAN."""
    if isinstance(cfg, dict):
        value = cfg.get(KEY)
        name = value.strip() if isinstance(value, str) and not dogrula(value) else None
    else:
        name = _dosyadan()
    if name:
        return name
    env = os.environ.get(ENV)
    if isinstance(env, str) and not dogrula(env):
        return env.strip()
    return VARSAYILAN


# --- Turkish case suffixes ---
_SESLI = "aeıioöuü"
_KALIN = "aıou"
_DORTLU = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}
_SERT = "fstkçşhp"
HALLER = ("e", "in", "den", "i", "de")  # dative, genitive, ablative, accusative, locative


_TURK_HARFLERI = set("abcçdefgğhıijklmnoöprsştuüvyz")


def _kucuk(text):
    """Lower case for the vowel analysis: Turkish I/İ, the circumflex vowels as plain ones, and any other accented
    letter (outside the Turkish alphabet) as its base letter ("José" -> "jose", "Zoë" -> "zoe")."""
    text = text.replace("I", "ı").replace("İ", "i").lower()
    text = text.replace("â", "a").replace("î", "i").replace("û", "u")
    out = []
    for c in text:
        if c in _TURK_HARFLERI or not c.isalpha():
            out.append(c)
        else:
            out.append("".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x)))
    return "".join(out)


def ek(name, hal):
    """`name` + apostrophe + the case suffix `hal` ("e", "in", "den", "i", "de") by Turkish vowel harmony: the last
    vowel picks a/e (and ı/i/u/ü), a final vowel takes the buffer letter (y, n), a final voiceless consonant
    (f s t k ç ş h p) turns d into t. A proper name is never softened (Murat'a). A name without a vowel reads as
    front-vowelled (Brr'e). Exceptions of loanwords (Kemal'e) are not known."""
    if hal not in HALLER:
        raise ValueError(f"unknown case {hal!r}")
    name = str(name)
    harfler = [c for c in _kucuk(name) if c.isalpha()]
    sesliler = [c for c in harfler if c in _SESLI]
    son_sesli = sesliler[-1] if sesliler else "e"
    son = harfler[-1] if harfler else "e"
    a = "a" if son_sesli in _KALIN else "e"
    i = _DORTLU[son_sesli]
    sesli_biter = son in _SESLI
    d = "t" if son in _SERT else "d"
    tail = {"e": ("y" if sesli_biter else "") + a,
            "in": ("n" if sesli_biter else "") + i + "n",
            "den": d + a + "n",
            "i": ("y" if sesli_biter else "") + i,
            "de": d + a}[hal]
    return f"{name}'{tail}"


def e(cfg=None):
    return ek(ad(cfg), "e")


def in_(cfg=None):
    return ek(ad(cfg), "in")


def den(cfg=None):
    return ek(ad(cfg), "den")


def i(cfg=None):
    return ek(ad(cfg), "i")


def de(cfg=None):
    return ek(ad(cfg), "de")


def ekler(cfg=None):
    """{ad, e, in, den, i, de} for /api/state (the page has its own helper, web/ofis-davranis.js sahipEk)."""
    name = ad(cfg)
    return {"adi": name, **{h: ek(name, h) for h in HALLER}}


# --- the reminder line the server appends to every CEO message ---
_HATIRLATMA_SONU = " Türkçe ve sade yaz.)"
_HATIRLATMA = re.compile(r"\n\([^()\n]{1,60}['’][a-zçğıöşü]{1,3} Türkçe ve sade yaz\.\)$")


def hatirlatma(name=None):
    """"(<Name>'e Türkçe ve sade yaz.)": the last line of every message to the CEO."""
    return "(" + ek(name or ad(), "e") + _HATIRLATMA_SONU


def hatirlatmayi_sil(text):
    """The message without the server's reminder line (any owner name; only as the last line of its own)."""
    body = str(text).rstrip()
    m = _HATIRLATMA.search(body)
    return body[:m.start()].rstrip() if m else text


# --- prefixes: both forms ---

def _of(text, *prefixes):
    for p in prefixes:
        if isinstance(text, str) and text.startswith(p):
            return p
    return None


def chat_prefix_of(text):
    return _of(text, CHAT_PREFIX, ESKI_CHAT_PREFIX)


def answer_prefix_of(text):
    return _of(text, ANSWER_PREFIX, ESKI_ANSWER_PREFIX)


def jarvis_prefix_of(text):
    return _of(text, JARVIS_PREFIX, ESKI_JARVIS_PREFIX)


# --- the owner's answer heading in a decision note ---
_CEVAP_BASLIGI = re.compile(r"Cevap \((?!Müdür kararı)[^()\n]{1,60}\)")


def cevap_basligi(cfg=None):
    """"Cevap (<name>)": the heading `ofis.py cevapla` writes."""
    return f"Cevap ({ad(cfg)})"


def sahip_cevabi_basligi_mi(heading):
    """True for the owner's answer heading under any name ("Cevap (Deniz)", "Cevap (Ali)"); never a manager's."""
    return bool(_CEVAP_BASLIGI.fullmatch(str(heading).strip()))


def cevap_bolumleri(body):
    """The contents of every owner's answer section of a note, in order."""
    out, cur = [], None
    for line in str(body or "").splitlines():
        if line.startswith("## "):
            if cur is not None:
                out.append("\n".join(cur).strip())
            cur = [] if sahip_cevabi_basligi_mi(line[3:]) else None
            continue
        if cur is not None:
            cur.append(line)
    if cur is not None:
        out.append("\n".join(cur).strip())
    return out


def cevap_bolumu(body):
    """The owner's (first) answer in a decision note under any name, or ""."""
    found = cevap_bolumleri(body)
    return found[0] if found else ""


# --- forgery patterns ---

# Lookalike letters (Unicode "confusables") of Cyrillic and Greek that read as Latin, after case folding: enough for
# "ofis", "sahip", "sahibin", "deniz" and most Latin-letter names (a full skeleton is not needed for these words).
_BENZER = str.maketrans({
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "ё": "e", "һ": "h", "н": "h", "і": "i", "ї": "i", "ӏ": "l", "ј": "j", "к": "k",
    "м": "m", "о": "o", "р": "p", "с": "c", "ԁ": "d", "ѕ": "s", "т": "t", "у": "y", "х": "x", "ԛ": "q", "ԝ": "w",
    # Greek
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "ί": "i", "κ": "k", "μ": "m", "ν": "n", "ο": "o", "ό": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ζ": "z", "ϲ": "c", "ϳ": "j",
})


def gorunur(text):
    """The text as a reader sees it, for matching only: every invisible format character (Unicode category Cf: ZWSP,
    U+2060, U+00AD, U+FEFF, bidi controls, …) dropped, then Cyrillic / Greek lookalikes as their Latin letters. Apply
    it to folded (lower-case) text; the text itself is never rewritten with it."""
    text = "".join(c for c in str(text or "") if unicodedata.category(c) != "Cf")
    return text.translate(_BENZER)


class _Gorunur:
    """A compiled pattern that matches the text after `gorunur` (search / match / fullmatch / findall)."""

    def __init__(self, pattern):
        self.re = pattern
        self.pattern = pattern.pattern

    def search(self, text, *args):
        return self.re.search(gorunur(text), *args)

    def match(self, text, *args):
        return self.re.match(gorunur(text), *args)

    def fullmatch(self, text, *args):
        return self.re.fullmatch(gorunur(text), *args)

    def findall(self, text, *args):
        return self.re.findall(gorunur(text), *args)

def _kokler(katla, cfg):
    roots = list(PROTOKOL_KOKLERI) + list(ESKI_ADLAR)
    own = gorunur(katla(ad(cfg))).strip()
    if own and own not in roots:
        roots.append(own)
    return roots


def sahte_onek_re(katla, cfg=None):
    """A regex over FOLDED text (`katla`) that finds a speaker prefix anywhere: "[Ofis …", "[Sahip …", "[Sahibin …",
    the old "[Deniz …" and one written with the configured name ("[Ayşe · …"). Also an escaped "\\[" (the "[" is
    still there). Invisible characters and lookalike letters do not hide one (`gorunur`)."""
    names = [r for r in _kokler(katla, cfg) if r not in PROTOKOL_KOKLERI] + ["ofis"]
    alts = "|".join(re.escape(r) for r in sorted(set(names), key=len, reverse=True))
    return _Gorunur(re.compile(r"\[\s*(?:sahi[bp]|(?:" + alts + r")(?![a-z0-9]))"))


def ad_anilma_re(katla, cfg=None):
    """A regex over FOLDED text that finds the owner named: the old name and the configured one as words, with or
    without a suffix. The default "Sahip" is also a common word ("önbelleğe sahip"), so for it only a suffixed form
    ("Sahip'e", "sahibe", "sahibin") counts. A short name matches only as a whole word or with an apostrophe suffix
    ("Ali", "Ali'ye"; never "alias"). Invisible characters and lookalike letters do not hide one (`gorunur`)."""
    own = gorunur(katla(ad(cfg))).strip()
    alts = [r"\bdeniz\b"]
    if own == _katla(VARSAYILAN):
        alts.append(r"\bsahip['’]\w*|\bsahib(?:e|i|in|ten|te)\b")
    elif own and own != "deniz":
        alts.append(r"(?<![a-z0-9])" + re.escape(own) + r"(?![a-z0-9])")
    return _Gorunur(re.compile("|".join(alts)))


def sahte_satirlari_etkisizlestir(text, cfg=None):
    """Text whose every line that would open an office message head ("[Ofis · …", "[Sahip · …", the old "[Deniz · …",
    one with the owner's configured name; also behind invisible characters or lookalike letters) starts with "(" instead
    of "[". Split on "\n" only: clean other line breaks first (bin/kontrol.py _clean)."""
    pattern = sahte_onek_re(_katla, cfg)
    out = []
    for line in str(text or "").split("\n"):
        stripped = gorunur(line).lstrip()
        if stripped.startswith("[") and pattern.match(_katla(stripped)):
            line = line.replace("[", "(", 1)
        out.append(line)
    return "\n".join(out)
