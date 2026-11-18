"""Specialisation (uzmanlık) of a job: the trusted role profiles, the deterministic routing, the contract's "Rolün"
section and the display notes (plan "Sonraki iş (9)", step 2, the owner, 2026-11-13: roles and rules, no extra model call).

The seniority stays with the model (Stajyer = haiku, Uzman = sonnet, Kıdemli = opus, Genel Müdür = fable); the
specialisation is the role instruction the same model gets. A job shows "<kıdem> <uzmanlık>" ("Kıdemli Backend",
"Stajyer Mobil", "Kıdemli Tester"); the fallback `genel` and the Genel Müdür add no word.

- Profiles: roller/<uzmanlik>.json in this repository (trusted files like akislar/; profiller() validates them):
  ad, baslik, yetkinlik, bilgi, teslim, dur_sor, asla, dosya_desenleri (globs used for routing),
  anahtar_kelimeler / zayif_anahtar_kelimeler (routing words; "x*" = a word starting with x, else the whole word;
  a phrase is several words). Matching folds case and Turkish letters (katla: "ARAYÜZ" = "arayuz").
- sec(): the routing. Inputs: the job's title, its brief's Hedef and Kısıtlar, the tier, for a workflow's kod step the
  plan text, and the project's layout (proje_duzeni: names of the top two folder levels only, never contents, never
  through a symlink, never a forbidden path). Scores, highest first: file paths mentioned in the text (PUAN_YOL each,
  the most specific glob of a path wins), keywords (PUAN_KELIME, weak ones PUAN_ZAYIF), the layout for kod work
  (PUAN_DUZEN), the tier (inceleme -> test, planlama -> analiz). A workflow's review steps follow their step
  (kod-inceleme -> test, plan-inceleme -> analiz); an explicit choice (--uzmanlik) wins over everything. A choice that
  is not clear (best < ESIK or not ahead by FARK) falls back to `genel` with the reason "belirsiz".
  Output: {uzmanlik, neden (short Turkish, built only from profile words and sanitised paths), kaynak (kural | elle |
  adim | yukseltme), puanlar}.
- sozlesme_bolumu(): the contract's "Rolün" section (yetkinlik, bilgi, teslim, dur_sor, asla; at most SOZLESME_SINIRI
  characters), on the session's start and every resume (bin/launch.py). It never replaces the project's rules.
- yaz_notlar(): the server mirrors each profile into OFIS/Calisanlar/<uzmanlik>.md (display only; written when its
  text changed; never through a link).
"""
import fnmatch
import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLLER = os.path.join(ROOT, "roller")
GENEL = "genel"
SIRA = ("backend", "ui", "mobil", "test", "analiz", "guvenlik", "genel")  # display order
ALANLAR = ("ad", "baslik", "yetkinlik", "bilgi", "teslim", "dur_sor", "asla", "dosya_desenleri", "anahtar_kelimeler",
           "zayif_anahtar_kelimeler")
LISTELER = ALANLAR[2:]
AD = re.compile(r"[a-z]{2,20}")
KIDEM = {"haiku": "Stajyer", "sonnet": "Uzman", "opus": "Kıdemli", "fable": "Genel Müdür"}
EKSIZ = ("fable",)  # the Genel Müdür is no specialist: its title stands alone
KAYNAKLAR = ("kural", "elle", "adim", "yukseltme")

PUAN_YOL = 6        # a file path in the brief / plan
YOL_EN_COK = 3      # paths counted per specialisation
PUAN_KELIME = 3     # a keyword
PUAN_ZAYIF = 1      # a weak keyword
KELIME_EN_COK = 3   # keywords counted per specialisation
PUAN_DUZEN = 2      # the project's layout (kod work only)
KATMAN = {"inceleme": ("test", 3), "planlama": ("analiz", 2)}
ADIM = {"kod-inceleme": "test", "plan-inceleme": "analiz"}
DUZEN_KATMANLARI = ("kod",)  # the layout leans only for code work: a summary in a Flutter project is no mobile job
ESIK = 2            # the least score of a choice
FARK = 1            # how far ahead of the next one
NEDEN_SINIRI = 160
SOZLESME_SINIRI = 1200
METIN_SINIRI = 20000  # characters of brief + plan text looked at

# the layout scan: names only, the top two folder levels, never through a link
DUZEN_DERINLIK = 2
DUZEN_GIRDI = 400     # entries read per folder
DUZEN_KLASOR = 60     # folders listed per scan
ATLA = {"node_modules", "build", "dist", "target", "vendor", "pods", "__pycache__", "venv", "android", "ios"}
# (android/ios are markers themselves; their own Gradle files are not a backend)
MOBIL_DOSYA = {"pubspec.yaml"}
BACKEND_DOSYA = {"pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "pyproject.toml", "requirements.txt",
                 "gemfile", "composer.json", "manage.py"}
UI_DOSYA = {"package.json"}
UI_KLASOR = {"web", "frontend", "site"}
EGILIM_SIRASI = ("mobil", "backend", "ui")

YOL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,200}")
GUVENLI_YOL = re.compile(r"[A-Za-z0-9_./-]{1,200}")
KELIME = re.compile(r"[a-z0-9]+")


class ProfilHatasi(Exception):
    """A role profile in roller/ is missing or malformed."""


class Gecersiz(ValueError):
    """An explicit specialisation that no profile has."""


# --- folding ---

_HARF = str.maketrans({"ı": "i", "İ": "i", "ç": "c", "ğ": "g", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i",
                       "û": "u"})


def katla(text):
    """Lower case without Turkish diacritics: "ARAYÜZ İÇİN" -> "arayuz icin" (also "I" -> "i")."""
    text = unicodedata.normalize("NFKC", str(text or "")).translate(_HARF).casefold().translate(_HARF)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


# --- profiles ---

_cache = {"key": None, "data": None}


def _dogrula(data, name):
    if not isinstance(data, dict):
        raise ProfilHatasi(f"{name}: not a JSON object")
    extra = sorted(set(data) - set(ALANLAR))
    missing = sorted(set(ALANLAR) - set(data))
    if extra or missing:
        raise ProfilHatasi(f"{name}: unknown fields {extra}, missing fields {missing}")
    if not isinstance(data["ad"], str) or not AD.fullmatch(data["ad"]) or data["ad"] != name:
        raise ProfilHatasi(f"{name}: 'ad' must be the file name")
    if not isinstance(data["baslik"], str) or not 1 <= len(data["baslik"]) <= 30 or "\n" in data["baslik"]:
        raise ProfilHatasi(f"{name}: 'baslik' must be a short line")
    for key in LISTELER:
        value = data[key]
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() and len(x) <= 400 and
                                                    "\n" not in x for x in value):
            raise ProfilHatasi(f"{name}: '{key}' must be a list of one-line texts")
    for key in ("yetkinlik", "bilgi", "teslim", "dur_sor", "asla"):
        if not data[key]:
            raise ProfilHatasi(f"{name}: '{key}' is empty")
    return data


def profiller(folder=ROLLER, cache=True):
    """{ad: profile} of every roller/*.json, validated (ProfilHatasi on any bad file; `genel` is required). Cached by
    the files' mtimes and sizes."""
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json") and not n.startswith("."))
    except OSError as e:
        raise ProfilHatasi(f"no role profiles in {folder} ({type(e).__name__})") from None
    key = []
    for n in names:
        p = os.path.join(folder, n)
        if os.path.islink(p) or not os.path.isfile(p):
            raise ProfilHatasi(f"{n}: not a plain file")
        st = os.stat(p)
        key.append((n, st.st_mtime_ns, st.st_size))
    key = (folder, tuple(key))
    if cache and _cache["key"] == key:
        return _cache["data"]
    out = {}
    for n in names:
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                data = json.loads(f.read(64 * 1024))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            raise ProfilHatasi(f"{n}: unreadable ({type(e).__name__})") from None
        out[n[:-5]] = _dogrula(data, n[:-5])
    if GENEL not in out:
        raise ProfilHatasi("the fallback profile genel.json is missing")
    if cache:
        _cache.update(key=key, data=out)
    return out


def _guvenli_profiller():
    try:
        return profiller()
    except ProfilHatasi:
        return {}


def dogrula(value, profs=None):
    """An explicit specialisation: returns the key, raises Gecersiz when no profile has it."""
    profs = profs if profs is not None else profiller()
    if not isinstance(value, str) or value not in profs:
        raise Gecersiz(f"bilinmeyen uzmanlık: {value!r} (geçerli: {', '.join(k for k in SIRA if k in profs)})")
    return value


def baslik(key, profs=None):
    profs = profs if profs is not None else _guvenli_profiller()
    prof = profs.get(key) if isinstance(key, str) else None
    return prof["baslik"] if prof else ""


def aile(model):
    low = str(model or "").lower()
    return next((f for f in KIDEM if f in low), "")


def rol_metni(model, key, profs=None):
    """"Kıdemli Backend": the seniority of the model and the specialisation's title (none for genel, an unknown key
    or the Genel Müdür)."""
    fam = aile(model)
    kidem = KIDEM.get(fam, "")
    ek = "" if key == GENEL or fam in EKSIZ else baslik(key, profs)
    return " ".join(x for x in (kidem, ek) if x)


# --- routing ---

def _yollar(text):
    out = []
    for m in YOL.finditer(text):
        parca = m.group(0).rstrip(".-/")
        if not parca or parca.startswith(("http", "www.")) or ("/" not in parca and "." not in parca):
            continue
        if parca not in out:
            out.append(parca)
    return out


def _glob_eslesir(pattern, path):
    """A glob without "/" matches the base name; with "/" the whole path, "**/" also at the start."""
    path, pattern = path.lower(), pattern.lower()
    if "/" not in pattern:
        return fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], pattern)
    rx = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(rx, path) is not None or re.fullmatch(rx, path + "/") is not None


def _ozgulluk(pattern):
    return len(pattern.replace("*", "").replace("/", "")) + (3 if "/" in pattern else 0)


def _yol_puanlari(paths, profs):
    """{uzmanlik: [paths]}: each path goes to the specialisation(s) whose most specific glob matches it best."""
    out = {}
    for path in paths:
        best, who = 0, []
        for key, prof in profs.items():
            score = max((_ozgulluk(g) for g in prof["dosya_desenleri"] if _glob_eslesir(g, path)), default=0)
            if score > best:
                best, who = score, [key]
            elif score and score == best:
                who.append(key)
        for key in who:
            out.setdefault(key, []).append(path)
    return out


def _kelime_parcalari(keyword):
    return [(w.rstrip("*"), w.endswith("*")) for w in katla(keyword).split()]


def _parca_eslesir(word, part):
    stem, prefix = part
    return word.startswith(stem) if prefix else word == stem


def _kelime_eslesmeleri(words, profs):
    """{uzmanlik: {"guclu": [keywords], "zayif": [keywords]}}. A single word matched by several one-word keywords
    counts only for the longest (TestFlight is mobil, not test)."""
    hits = []  # (start, single, stem length, key, kind, keyword)
    for key, prof in profs.items():
        for kind, field in (("guclu", "anahtar_kelimeler"), ("zayif", "zayif_anahtar_kelimeler")):
            for kw in prof[field]:
                parts = _kelime_parcalari(kw)
                if not parts:
                    continue
                for i in range(len(words) - len(parts) + 1):
                    if all(_parca_eslesir(words[i + j], parts[j]) for j in range(len(parts))):
                        hits.append((i, len(parts) == 1, len(parts[0][0]), key, kind, kw))
    longest = {}
    for i, single, size, *_ in hits:
        if single:
            longest[i] = max(longest.get(i, 0), size)
    out = {}
    for i, single, size, key, kind, kw in hits:
        if single and size < longest[i]:
            continue
        found = out.setdefault(key, {"guclu": [], "zayif": []})[kind]
        if kw not in found:
            found.append(kw)
    return out


def _temiz_yol(path):
    path = path if GUVENLI_YOL.fullmatch(path) else ""
    return path if len(path) <= 60 else "…" + path[-59:]


def _kelime_metni(kw):
    return "«" + kw.replace("*", "") + "»"


def _kes(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def sec(title, brief, proje=None, katman=None, plan=None, duzen=None, adim=None, secilen=None, profiller_=None):
    """The specialisation of a job (see the module doc). brief: {hedef, kisitlar, …}; duzen: proje_duzeni()'s result;
    adim: a workflow step kind; secilen: an explicit choice (Gecersiz when unknown). Never raises otherwise: without
    profiles every job is `genel`."""
    profs = profiller_ if profiller_ is not None else _guvenli_profiller()
    if secilen not in (None, ""):
        return {"uzmanlik": dogrula(secilen, profs), "neden": "elle seçildi", "kaynak": "elle", "puanlar": {}}
    if adim in ADIM and ADIM[adim] in profs:
        return {"uzmanlik": ADIM[adim], "neden": f"akış adımı {adim} → {ADIM[adim]}", "kaynak": "adim",
                "puanlar": {}}
    brief = brief if isinstance(brief, dict) else {}
    text = "\n".join(str(x) for x in (title, brief.get("hedef"), brief.get("kisitlar"), plan) if x)[:METIN_SINIRI]
    scores, evidence = {}, {}

    def add(key, points, why):
        if key not in profs or not points:
            return
        scores[key] = scores.get(key, 0) + points
        evidence.setdefault(key, []).append((points, why))
    for key, paths in _yol_puanlari(_yollar(text), profs).items():
        shown = [p for p in (_temiz_yol(x) for x in paths[:2]) if p]
        add(key, PUAN_YOL * min(len(paths), YOL_EN_COK),
            f"brief'te {', '.join(shown)} geçiyor" if shown else "brief'te bu alanın dosyaları geçiyor")
    for key, found in _kelime_eslesmeleri(KELIME.findall(katla(text)), profs).items():
        strong, weak = found["guclu"][:KELIME_EN_COK], found["zayif"][:KELIME_EN_COK]
        words = [_kelime_metni(k) for k in (strong + weak)[:3]]
        add(key, PUAN_KELIME * len(strong) + PUAN_ZAYIF * len(weak), f"brief'te {', '.join(words)} geçiyor")
    lean = duzen.get("egilim") if isinstance(duzen, dict) else ""
    if lean and katman in DUZEN_KATMANLARI:
        marker = (duzen.get("isaretler") or {}).get(lean) or lean
        add(lean, PUAN_DUZEN, f"proje düzeni: {_temiz_yol(marker) or lean}")
    if katman in KATMAN:
        key, points = KATMAN[katman]
        add(key, points, f"katman {katman}")
    ranked = sorted(((v, k) for k, v in scores.items()),
                    key=lambda x: (-x[0], SIRA.index(x[1]) if x[1] in SIRA else 99))
    if not ranked or ranked[0][0] < ESIK or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < FARK):
        close = [f"{k} {v}" for v, k in ranked[:2] if v]
        why = f"belirsiz ({' · '.join(close)})" if len(close) > 1 and ranked[0][0] >= ESIK else "belirsiz"
        return {"uzmanlik": GENEL, "neden": _kes(f"{why} → {GENEL}", NEDEN_SINIRI), "kaynak": "kural",
                "puanlar": scores}
    winner = ranked[0][1]
    items = [why for _, why in sorted(evidence[winner], key=lambda x: -x[0])[:2]]
    tail = f" → {winner}"
    return {"uzmanlik": winner, "neden": _kes("; ".join(items), NEDEN_SINIRI - len(tail)) + tail, "kaynak": "kural",
            "puanlar": scores}


# --- the project's layout ---

def _girdiler(folder):
    """(dirs, files) base names of one folder; links and hidden entries are skipped, never followed."""
    dirs, files = [], []
    try:
        with os.scandir(folder) as it:
            for n, entry in enumerate(it):
                if n >= DUZEN_GIRDI:
                    break
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(entry.name)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry.name)
    except OSError:
        pass
    return sorted(dirs), sorted(files)


def proje_duzeni(path):
    """{egilim: "mobil" | "backend" | "ui" | "", turler: [...], isaretler: {tur: "relative/marker"}} from the names of
    the project folder's top two levels (pubspec.yaml or android/ + ios/ -> mobil; pom.xml, build.gradle, go.mod,
    pyproject.toml … -> backend; package.json, web/, frontend/, site/ -> ui). Never reads a file, never follows a link,
    never scans a forbidden path."""
    empty = {"egilim": "", "turler": [], "isaretler": {}}
    if not isinstance(path, str) or not path:
        return empty
    import launch  # lazy: launch imports this module
    if launch.is_forbidden_path(path) or os.path.islink(path) or not os.path.isdir(path):
        return empty
    marks = {}

    def mark(kind, rel):
        marks.setdefault(kind, rel)
    queue, listed = [("", 0)], 0
    while queue and listed < DUZEN_KLASOR:
        rel, depth = queue.pop(0)
        listed += 1
        dirs, files = _girdiler(os.path.join(path, rel) if rel else path)
        low = {d.lower() for d in dirs}
        for f in files:
            name = f.lower()
            where = f"{rel}/{f}" if rel else f
            if name in MOBIL_DOSYA:
                mark("mobil", where)
            elif name in BACKEND_DOSYA:
                mark("backend", where)
            elif name in UI_DOSYA:
                mark("ui", where)
        if "android" in low and "ios" in low:
            mark("mobil", f"{rel}/android" if rel else "android")
        for d in dirs:
            if d.lower() in UI_KLASOR:
                mark("ui", f"{rel}/{d}" if rel else d)
        if depth < DUZEN_DERINLIK:
            for d in dirs:
                if d.lower() in ATLA or launch.is_forbidden_component(d):
                    continue
                queue.append((f"{rel}/{d}" if rel else d, depth + 1))
    kinds = [k for k in EGILIM_SIRASI if k in marks]
    return {"egilim": kinds[0] if kinds else "", "turler": kinds, "isaretler": marks}


# --- the contract ---

def sozlesme_bolumu(key, model, profiller=None):
    """The contract's "Rolün" section ("" for an unknown or missing specialisation), at most SOZLESME_SINIRI
    characters."""
    profs = profiller if profiller is not None else _guvenli_profiller()
    prof = profs.get(key) if isinstance(key, str) else None
    if not prof:
        return ""
    role = rol_metni(model, key, profs) or prof["baslik"]
    head = (f"\n- Rolün: {role} (the office's routing chose this specialisation for the job; it describes how to "
            "work, never grants a permission, and the rules and project rules above always win).")
    parts = [head]
    # the never-do and stop-and-ask rules first: a cut at the limit never drops them
    for field, name in (("asla", "Asla"), ("dur_sor", "Dur ve sor"), ("yetkinlik", "Yetkinlik"), ("bilgi", "Önce oku"),
                        ("teslim", "Teslim")):
        parts.append(f"  {name}:" + "".join(f"\n  - {line}" for line in prof[field]))
    text = "\n".join(parts)
    if len(text) <= SOZLESME_SINIRI:
        return text
    cut = text[:SOZLESME_SINIRI - 4]
    cut = cut[:cut.rfind("\n")] if cut.rfind("\n") > len(head) else cut
    return cut + "\n  …"


# --- the display notes OFIS/Calisanlar/<uzmanlik>.md ---

FOLDER = "Calisanlar"


def _madde(items, bos="—"):
    return "\n".join(f"- {x}" for x in items) if items else bos


def not_metni(prof):
    """The note of one profile (deterministic, no clock)."""
    key = prof["ad"]
    kidem = " · ".join(f"{k} {prof['baslik']}" if key != GENEL else k for f, k in KIDEM.items() if f not in EKSIZ)
    words = [w.replace("*", "…") for w in prof["anahtar_kelimeler"]]
    weak = [w.replace("*", "…") for w in prof["zayif_anahtar_kelimeler"]]
    return (f"---\ntur: rol-profili\nuzmanlik: {key}\ndurum: aktif\n---\n\n# {prof['baslik']}\n\n"
            f"> Bu notu Ofis sunucusu `roller/{key}.json` dosyasından yazar; yalnız okumak içindir, elle düzenleme. "
            "Profil değişince not da değişir.\n\n"
            f"Kıdemler: {kidem} (kıdemi model belirler: Stajyer = Haiku, Uzman = Sonnet, Kıdemli = Opus).\n\n"
            f"## Yetkinlik\n\n{_madde(prof['yetkinlik'])}\n\n"
            f"## Önce okuduğu\n\n{_madde(prof['bilgi'])}\n\n"
            f"## Teslim biçimi\n\n{_madde(prof['teslim'])}\n\n"
            f"## Nerede durup sorar\n\n{_madde(prof['dur_sor'])}\n\n"
            f"## Asla yapmaz\n\n{_madde(prof['asla'])}\n\n"
            "## Yönlendirme\n\n"
            f"- Dosya desenleri: {', '.join(f'`{g}`' for g in prof['dosya_desenleri']) or '—'}\n"
            f"- Anahtar kelimeler: {', '.join(words) or '—'}\n"
            + (f"- Zayıf anahtar kelimeler: {', '.join(weak)}\n" if weak else ""))


def yaz_notlar(vault, profs=None):
    """Writes OFIS/Calisanlar/<uzmanlik>.md for every profile whose text changed. Returns the keys written. Never
    through a link (the folder or a note); unreadable profiles write nothing."""
    import jobs  # lazy: keeps this module light for the routing tests
    profs = profs if profs is not None else _guvenli_profiller()
    if not vault or not profs:
        return []
    folder = os.path.join(vault, FOLDER)
    if os.path.islink(folder) or (os.path.lexists(folder) and not os.path.isdir(folder)):
        return []
    written = []
    for key in sorted(profs):
        target = os.path.join(folder, f"{key}.md")
        text = not_metni(profs[key])
        if os.path.islink(target):
            continue
        try:
            with open(target, encoding="utf-8") as f:
                if f.read(256 * 1024) == text:
                    continue
        except (OSError, UnicodeDecodeError):
            pass
        os.makedirs(folder, exist_ok=True)
        jobs._write_atomic(target, text)
        written.append(key)
    return written
