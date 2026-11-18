"""The Ar-Ge odası (plan "Sonraki iş (6)", owner decision 2026-11-12): the free daily check and the Ar-Ge report note.

Free daily check (server code, no model call): once a day — the first pass of each office day, so also once at a
server start when today's check is not done yet — `GunlukKontrol` runs, one after another and each with a timeout of
TIMEOUT_SN, `opencode models --standalone` (no background service), `claude --version`, `codex --version` and `opencode --version` (argument lists, no
shell, a process group killed on timeout; the binaries of ofis.json `codex_bin` / `opencode_bin`, else PATH). It
never runs while heavy work runs (a Kontrol or a review: `mesgul`) and contacts the network only through those CLIs'
own commands. A tool that is missing, fails or times out is "bilinmiyor". Results (free data, not a trusted record):
  durum/arge/gunler/YYYY-MM-DD.json  that day's lists: all models, the free ones, the versions, the day's diff (history,
                                     KEEP_DAYS days)
  durum/arge/son_fark.json           the last diff: new / removed / renamed free models against the last earlier day
                                     whose list was known, and the version changes
Free models: a name ending in "-free" or ":free", or one of opencode's own models without a version number (the
"big-pickle" style). A rename is one removed and one new model of the same provider whose names differ only in their
numbers ("glm-5.3-flash-free" → "glm-5.4-flash-free"). An unknown list is never read as "every model removed".

The Ar-Ge report: the post office only keeps a `bitti` of an `arge` job (its server record) as the job's pending
report (`bekleyen_kaydet`: durum/arge/raporlar/<iş>.json, id = job + a hash of the text; a newer report replaces it).
The background writer (`bekleyenleri_yaz`, the Ar-Ge thread) is the only caller of `yaz_ve_bildir`, the ONE place that
writes OFIS/ArGe/ArGe-YYYY-MM-DD.md, the reviewer cards and the one CEO notice, in that order, once the job is `bitti`
(no Kontrol, or its Kontrol passed). The done set durum/arge/yazilanlar.json makes it idempotent: never written twice,
never told twice (a failed queue or a restart between writing and telling only tells later). The "ArGe-" prefix keeps
the note apart from the morning summary's OFIS/Ozetler/YYYY-MM-DD.md, so the bare link [[ArGe-YYYY-MM-DD]] is unique.
The report is quoted as data (`> `, `kontrol.no_callout`), never as instructions. A line `ÖNERİ-DENETÇİ: <model> |
<lisans> | <neden>` (parsed tolerantly: case, Turkish letters, list / bold markup) becomes a pending decision card
`Kararlar/YYYY-MM-DD-arge-denetci-onerisi.md` (tur: denetci-onerisi, "Denetçi olarak denensin mi?") — only with a model
name and a license, at most MAX_KART per report, never a second card for a model whose card is still pending, and
nothing is ever invented: no line, no card.
"""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
from datetime import datetime

import jobs
import kontrol
import ozet
import records
import sahip
import sorumlu

PROJE = "arge"
FOLDER = "ArGe"
DURUM_DIR = "arge"
TIMEOUT_SN = 10
KEEP_DAYS = 90
BILINMIYOR = "bilinmiyor"
ARACLAR = ("claude", "codex", "opencode")
MAX_MODEL = 2000
MAX_CIKTI = 1_000_000
MAX_KART = 3
MAX_RAPOR = 20000
OZET_SATIR = 6
DENETCI_ONERISI = "denetci-onerisi"
SYSTEM_PREFIX = "[Ofis · sistem]\n"
YAZILANLAR = "yazilanlar.json"  # the done set of written / told reports
BILDIRIM_ONEK = "arge-"  # the notice key: arge-<rid>
MAX_BILDIRIM = 1500
# rapor_yaz runs from the post office and from the Ar-Ge thread (bekleyenleri_yaz): one writer at a time
_YAZ = threading.Lock()
_LOGGED = set()  # report ids whose write / notice failure was already logged
NOT_ONEK = "ArGe-"  # the note's name: ArGe-YYYY-MM-DD (never the morning summary's bare day name)
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,159}")
LISTED = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]*/[A-Za-z0-9._:/@+~-]+")
SAYI = re.compile(r"\d+(?:\.\d+)*")
# the suggestion line, matched on a copy whose Turkish letters are folded to ASCII (the same length as the line)
FOLD = str.maketrans("İıÖöÇçŞşÜüĞğ", "IiOoCcSsUuGg")
ONERI = re.compile(r"^\s*(?:[-*>•]\s*)*(?:\*\*|__)?\s*oneri[-\s_]*denetci\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.*)$",
                   re.I)


# --- commands ---

def calistir(argv, timeout, cwd=None):
    """(returncode, stdout) of argv: no shell, no stdin, stderr dropped, its own process group (killed on timeout:
    raises subprocess.TimeoutExpired)."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, errors="replace", cwd=cwd, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        try:  # bounded: a detached grandchild may keep the pipe open
            proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            if proc.stdout:
                proc.stdout.close()
        raise
    return proc.returncode, (out or "")[:MAX_CIKTI]


def _temiz(text):
    return CONTROL.sub("", ANSI.sub("", str(text or "")))


def surum_satiri(text):
    """The first non-empty line of a `--version` output, cleaned and cut to 80 characters; "" when there is none."""
    for line in _temiz(text).splitlines():
        line = " ".join(line.split())
        if line:
            return line[:80]
    return ""


def modelleri_ayikla(text):
    """The sorted, distinct model names (provider/name) of an `opencode models` output; anything else is dropped."""
    out = set()
    for line in _temiz(text).splitlines():
        line = line.strip()
        if len(line) <= 160 and LISTED.fullmatch(line):
            out.add(line)
    return sorted(out)[:MAX_MODEL]


def ucretsiz_mi(name):
    provider, _, rest = str(name).partition("/")
    low = rest.lower()
    return low.endswith("-free") or low.endswith(":free") or (provider == "opencode" and bool(rest)
                                                               and not re.search(r"\d", rest))


def ucretsizler(models):
    return sorted(m for m in models or [] if ucretsiz_mi(m))


def _aile(name):
    provider, _, rest = name.partition("/")
    rest = re.sub(r"(?:-free|:free)$", "", rest, flags=re.I)
    return f"{provider}/{SAYI.sub('#', rest)}"


def model_farki(onceki, simdi):
    """{yeni, kalkan, ad_degisen: [[eski, yeni]]} of two free-model lists (see the module doc for a rename)."""
    old, new = set(onceki or []), set(simdi or [])
    kalkan, yeni = sorted(old - new), sorted(new - old)
    degisen = []
    for key in sorted({_aile(m) for m in kalkan} & {_aile(m) for m in yeni}):
        a = [m for m in kalkan if _aile(m) == key]
        b = [m for m in yeni if _aile(m) == key]
        if len(a) == 1 and len(b) == 1:
            degisen.append([a[0], b[0]])
    eski = {p[0] for p in degisen}
    taze = {p[1] for p in degisen}
    return {"yeni": [m for m in yeni if m not in taze], "kalkan": [m for m in kalkan if m not in eski],
            "ad_degisen": degisen}


# --- the stored days ---

def _dir(durum_dir, *parts):
    return os.path.join(durum_dir, DURUM_DIR, *parts)


def _read_json(path):
    try:
        if os.path.islink(path):
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    if os.path.islink(path):
        raise OSError(f"{path} is a link")
    jobs._write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def gunler(durum_dir):
    folder = _dir(durum_dir, "gunler")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n[:-5] for n in names if n.endswith(".json") and DAY.fullmatch(n[:-5]))


def gun_verisi(durum_dir, gun):
    return _read_json(_dir(durum_dir, "gunler", f"{gun}.json"))


def son_fark(durum_dir):
    return _read_json(_dir(durum_dir, "son_fark.json"))


def _office_now(cfg, now):
    tz = ozet._tz(cfg)
    now = now() if callable(now) else (now or datetime.now(tz))
    return now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)


class GunlukKontrol:
    """The server's thread: kontrol() runs the free daily check once per office day (see the module doc)."""

    def __init__(self, cfg, durum_dir, runner=None, now=None, mesgul=None, which=shutil.which, log=None, ceo=None):
        self.cfg = cfg  # a callable: ofis.json as it is now
        self.durum_dir = durum_dir
        self.runner = runner or (lambda argv, timeout: calistir(argv, timeout, cwd=self._cwd()))
        self.now = now
        self.mesgul = mesgul or (lambda: False)
        self.which = which
        self.log = log or (lambda line: None)
        self.ceo = ceo  # the deferred report's one notice
        self._lock = threading.Lock()

    def _cwd(self):
        folder = _dir(self.durum_dir)
        os.makedirs(folder, exist_ok=True)
        return folder

    def _bin(self, cfg, name):
        value = cfg.get(f"{name}_bin") if name != "claude" else None
        if isinstance(value, str) and value.strip():
            return os.path.expanduser(value.strip())
        return self.which(name)

    def _run(self, argv):
        try:
            code, out = self.runner(argv, TIMEOUT_SN)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return out if code == 0 else None

    def topla(self, cfg):
        """{modeller: [..] | None, ucretsiz: [..] | None, surumler: {arac: text | "bilinmiyor"}} — one call at a time."""
        oc = self._bin(cfg, "opencode")
        # --standalone: list without starting OpenCode's background service (`opencode serve --service`), which a plain
        # `opencode models` launches and leaves running for days (seen 2026-11-16).
        out = self._run([oc, "models", "--standalone"]) if oc else None
        models = modelleri_ayikla(out) if out is not None else None
        if models == []:  # an empty answer is no list
            models = None
        surumler = {}
        for name in ARACLAR:
            path = self._bin(cfg, name)
            text = self._run([path, "--version"]) if path else None
            surumler[name] = (surum_satiri(text) if text is not None else "") or BILINMIYOR
        return {"modeller": models, "ucretsiz": ucretsizler(models) if models is not None else None,
                "surumler": surumler}

    def fark(self, gun, veri):
        """The day's diff against the last earlier day whose model list (and each tool's version) was known."""
        days = [d for d in gunler(self.durum_dir) if d < gun]
        onceki = None
        for d in reversed(days):
            v = gun_verisi(self.durum_dir, d)
            if v and isinstance(v.get("ucretsiz"), list):
                onceki = (d, v)
                break
        if veri["ucretsiz"] is None:
            modeller = {"durum": BILINMIYOR, "yeni": [], "kalkan": [], "ad_degisen": []}
        elif onceki is None:
            modeller = {"durum": "ilk", "yeni": [], "kalkan": [], "ad_degisen": [], "sayi": len(veri["ucretsiz"])}
        else:
            modeller = {"durum": "tamam", **model_farki(onceki[1]["ucretsiz"], veri["ucretsiz"]),
                        "sayi": len(veri["ucretsiz"])}
        surumler = []
        for name in ARACLAR:
            now_v = veri["surumler"].get(name)
            if now_v == BILINMIYOR:
                continue
            for d in reversed(days):
                old = ((gun_verisi(self.durum_dir, d) or {}).get("surumler") or {}).get(name)
                if isinstance(old, str) and old != BILINMIYOR:
                    if old != now_v:
                        surumler.append({"arac": name, "onceki": old, "simdi": now_v})
                    break
        degisiklik = bool(surumler or modeller["yeni"] or modeller["kalkan"] or modeller["ad_degisen"])
        return {"gun": gun, "onceki_gun": onceki[0] if onceki else None, "modeller": modeller, "surumler": surumler,
                "araclar": dict(veri["surumler"]), "degisiklik": degisiklik}

    def _prune(self):
        days = gunler(self.durum_dir)
        for d in days[:-KEEP_DAYS] if len(days) > KEEP_DAYS else []:
            try:
                os.unlink(_dir(self.durum_dir, "gunler", f"{d}.json"))
            except OSError:
                pass

    def kontrol(self):
        """Runs today's check when it is not done yet and nothing heavy runs; returns the day, else None."""
        with self._lock:
            cfg = self.cfg()
            now = _office_now(cfg, self.now)
            gun = now.strftime("%Y-%m-%d")
            if os.path.lexists(_dir(self.durum_dir, "gunler", f"{gun}.json")):
                return None
            if self.mesgul():
                return None
            veri = self.topla(cfg)
            fark = self.fark(gun, veri)
            _write_json(_dir(self.durum_dir, "gunler", f"{gun}.json"),
                        {"gun": gun, "zaman": now.strftime("%Y-%m-%dT%H:%M:%S"), **veri, "fark": fark})
            _write_json(_dir(self.durum_dir, "son_fark.json"), fark)
            self._prune()
            return gun

    def run(self, stop_event, interval=15):
        while not stop_event.is_set():
            try:
                self.kontrol()
            except Exception as e:  # noqa: BLE001 — never stops the server
                self.log(f"ofis: Ar-Ge günlük kontrolü hatası: {type(e).__name__}: {e}")
            try:
                bekleyenleri_yaz(self.cfg(), self.durum_dir, self.now, ceo=self.ceo, log=self.log)
            except Exception as e:  # noqa: BLE001
                self.log(f"ofis: Ar-Ge raporu yazılamadı: {type(e).__name__}: {e}")
            stop_event.wait(interval)


# --- the report note and the reviewer cards ---

def oneriler(metin):
    """The `ÖNERİ-DENETÇİ: model | lisans | neden` lines of a report: [{model, lisans, neden}] (distinct models, in
    order); a line without a valid model name is dropped, a missing license stays "" (no card is opened for it)."""
    out, seen = [], set()
    for line in str(metin or "").splitlines():
        m = ONERI.match(line.translate(FOLD))
        if not m:
            continue
        parts = [p.strip() for p in line[m.start(1):].split("|")]
        model = parts[0].strip("`*_ ").strip()
        if not MODEL.fullmatch(model) or model in seen:
            continue
        seen.add(model)
        lisans = sorumlu.tek_satir(parts[1].strip("`*_ "), 80) if len(parts) > 1 else ""
        neden = sorumlu.tek_satir(" | ".join(parts[2:]), 300) if len(parts) > 2 else ""
        out.append({"model": model, "lisans": lisans, "neden": neden})
    return out


def _alinti(text):
    text = str(text or "").strip()
    if len(text) > MAX_RAPOR:
        text = text[:MAX_RAPOR].rstrip() + " …"
    return kontrol._quote(text)


def _record_path(durum_dir, job_name):
    return _dir(durum_dir, "raporlar", f"{jobs.stem(job_name)}.json")


def _records(durum_dir):
    folder = _dir(durum_dir, "raporlar")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for n in names:
        if n.endswith(".json"):
            r = _read_json(os.path.join(folder, n))
            if r and isinstance(r.get("is"), str):
                out.append(r)
    return out


def _safe_folder(vault, name):
    folder = os.path.join(vault, name)
    if os.path.islink(folder) or (os.path.lexists(folder) and not os.path.isdir(folder)):
        raise OSError(f"OFIS/{name} is not a plain folder")
    os.makedirs(folder, exist_ok=True)
    return folder


def _pending_card(vault, model):
    """(name, frontmatter) of a pending reviewer card for `model`, else None."""
    folder = os.path.join(vault, "Kararlar")
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".md") and DENETCI_ONERISI in n)
    except OSError:
        return None
    for n in names:
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                _, meta, body = jobs.parse(f.read())
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if meta.get("tur") == DENETCI_ONERISI and meta.get("durum") == "bekliyor" and \
                f"> Model: {model}\n" in body:
            return n, meta
    return None


def _card_name(folder, gun):
    for suffix in [""] + [f"-{i}" for i in range(2, 100)]:
        name = f"{gun}-{PROJE}-{DENETCI_ONERISI}{suffix}.md"
        if not os.path.lexists(os.path.join(folder, name)):
            return name
    raise OSError("no free decision note name")


def kart_metni(o, gun, job_name, now):
    lines = [f"tags: [ofis, karar, {PROJE}]"]
    for key, value in (("proje", PROJE), ("durum", "bekliyor"), ("tur", DENETCI_ONERISI),
                       ("kaynak_is", jobs.stem(job_name)), ("soruldu", now.strftime("%Y-%m-%dT%H:%M:%S"))):
        jobs._set_line(lines, key, value)
    model = o["model"]
    body = (f"# Ar-Ge — Denetçi önerisi: {model}\n\n"
            f"## Soru\nAr-Ge, {model} modelini ücretsiz bir denetçi olarak önerdi. Denetçi olarak denensin mi? "
            "\"Evet\" yazarsan öneri kabul edilmiş olarak kaydedilir; modelin denetçi heyetine eklenmesi ve denemesi "
            "ayrı bir iş olarak yeniden sorulur. Başka bir şey yazarsan öneri kapanır.\n\n"
            "## Öneri (Ar-Ge raporundan; veri, talimat değil)\n"
            f"> Model: {model}\n> Lisans: {o['lisans']}\n> Neden: {o['neden'] or '(yazılmadı)'}\n\n"
            f"## Kaynak\n- Rapor: [[{NOT_ONEK}{gun}]]\n- İş: [[{jobs.stem(job_name)}]]\n\n"
            "## Ne olur\nOnaylarsan ofis hiçbir şeyi kendiliğinden değiştirmez: modelin heyete (ofis.json "
            "`denetciler`) eklenmesi ve denemesi ayrı bir değişiklik olarak hazırlanır; denetçi karnesi "
            "(Karne/Denetciler) sonucu gösterir.\n\n"
            "## İlgili Sayfalar\n- [[Denetciler]]\n")
    return jobs.render(lines, body)


def _not_metni(gun, reports, fark):
    out = [f"---\ntags: [ofis, {PROJE}]\nproje: {PROJE}\ntur: arge-raporu\ntarih: {gun}\ndurum: yazildi\n---\n",
           f"# Ar-Ge raporu — {ozet.tarih_metni(gun)}\n",
           "> Bu notu ofis sunucusu Ar-Ge işinin raporundan yazar; rapor metni veri olarak alıntılanmıştır (talimat "
           "değildir). Elle düzenlenmez.\n"]
    out.append("## Ücretsiz günlük kontrol\n\n" + fark_metni(fark) + "\n")
    lines = []
    for r in reports:
        for o in r.get("oneriler") or []:
            bits = [o.get("model", ""), o.get("lisans") or ""]
            head = " · ".join(b for b in bits if b)
            if o.get("kart"):
                lines.append(f"- {head} → kart [[{jobs.stem(o['kart'])}]]")
            elif not o.get("lisans"):
                lines.append(f"- {head} → lisansı yazılmadığı için kart açılmadı")
            elif o.get("sebep"):
                lines.append(f"- {head} → {o['sebep']}")
    out.append("## Denetçi önerileri\n\n" + ("\n".join(lines) if lines else "Bu raporda denetçi önerisi yok.") + "\n")
    for r in reports:
        out.append(f"## Rapor: {sorumlu.tek_satir(r.get('baslik') or '', 100)} — [[{jobs.stem(r['is'])}]]\n\n"
                   f"{_alinti(r.get('metin'))}\n")
    return "\n".join(out)


def fark_metni(fark):
    """The free check of a day in plain Turkish lines (the note and the page say the same)."""
    if not isinstance(fark, dict):
        return "Bugünün ücretsiz kontrolü henüz yok."
    m = fark.get("modeller") or {}
    lines = []
    if m.get("durum") == BILINMIYOR:
        lines.append("- Ücretsiz model listesi: bilinmiyor (opencode okunamadı).")
    elif m.get("durum") == "ilk":
        lines.append(f"- İlk liste: {m.get('sayi', 0)} ücretsiz model kaydedildi (karşılaştırılacak önceki gün yok).")
    else:
        lines.append(f"- Karşılaştırılan gün: {fark.get('onceki_gun')} · bugün {m.get('sayi', 0)} ücretsiz model.")
        if m.get("yeni"):
            lines.append("- Yeni: " + ", ".join(m["yeni"]))
        if m.get("kalkan"):
            lines.append("- Kalkan: " + ", ".join(m["kalkan"]))
        if m.get("ad_degisen"):
            lines.append("- Adı değişen: " + ", ".join(f"{a} → {b}" for a, b in m["ad_degisen"]))
        if not (m.get("yeni") or m.get("kalkan") or m.get("ad_degisen")):
            lines.append("- Ücretsiz model listesinde değişiklik yok.")
    for s in fark.get("surumler") or []:
        lines.append(f"- Sürüm değişti: {s.get('arac')}: {s.get('onceki')} → {s.get('simdi')}")
    araclar = fark.get("araclar") if isinstance(fark.get("araclar"), dict) else {}
    simdi = " · ".join(f"{k} {araclar[k]}" for k in ARACLAR if araclar.get(k))
    if fark.get("surumler"):
        pass
    elif m.get("durum") == "ilk" or not fark.get("onceki_gun"):
        lines.append(f"- Sürümler kaydedildi: {simdi}." if simdi else "- Sürümler kaydedildi.")
    else:
        lines.append(f"- Sürümler değişmedi ({simdi})." if simdi else "- Sürümler değişmedi.")
    return "\n".join(lines)


def rapor_kimligi(job_name, metin):
    """A report's identity: its job and a hash of its text (the same report is written and told once)."""
    return f"{jobs.stem(jobs.check_name(job_name))}-{hashlib.sha256(str(metin or '').encode('utf-8')).hexdigest()[:16]}"


def bekleyen_kaydet(durum_dir, job_name, baslik, metin, now):
    """The inbox path's only Ar-Ge step: keeps the report as the job's pending record (replacing an older report of
    the same job; the same report again changes nothing). Raises OSError when it cannot be saved: the post office then
    keeps the inbox file and retries. Returns the report id."""
    rid = rapor_kimligi(job_name, metin)
    path = _record_path(durum_dir, job_name)
    with _YAZ:
        old = _read_json(path) or {}
        if old.get("rid") == rid:
            return rid
        at = now() if callable(now) else (now or datetime.now())
        _write_json(path, {"is": jobs.check_name(job_name), "baslik": str(baslik or "")[:200], "rid": rid,
                           "metin": str(metin or "")[:MAX_RAPOR], "zaman": at.strftime("%Y-%m-%dT%H:%M:%S")})
    return rid


def _done_path(durum_dir):
    return _dir(durum_dir, YAZILANLAR)


def kaydi_var(durum_dir, job_name):
    """True when the job has a pending or a written Ar-Ge report (then the Ar-Ge writer tells the CEO about it)."""
    stem = jobs.stem(job_name)
    if os.path.isfile(_record_path(durum_dir, job_name)):
        return True
    return any(jobs.stem(str(e.get("is") or "")) == stem for e in yazilanlar(durum_dir).values())


def yazilanlar(durum_dir):
    """The done set: {rid: {is, baslik, metin, gun, zaman, kartlar, oneriler, yazildi, bildirildi}}."""
    data = _read_json(_done_path(durum_dir)) or {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _save_done(durum_dir, done):
    _write_json(_done_path(durum_dir), done)


def bildirim(entry, durum_dir=None):
    """The one CEO notice of a written report (the job's own done notice is withheld for arge jobs); it says when the
    report's Kontrol passed (the server record)."""
    stem = jobs.stem(entry["is"])
    head = (f"Ar-Ge raporu geldi: {sorumlu.tek_satir(entry.get('baslik') or stem, 100)} ({stem}). Obsidian notu: "
            f"[[{NOT_ONEK}{entry['gun']}]].")
    if durum_dir and records.server_value(durum_dir, entry["is"], "kontrol_sonuc") == "gecti":
        n = records.server_value(durum_dir, entry["is"], "kontrol_deneme")
        head += f" Kontrol geçti (deneme {n or '?'}; kanıt iş notunda)."
    head += f" {sahip.e()} tek satırla özetle."
    cards = [k["kart"] for k in entry.get("kartlar") or [] if isinstance(k, dict) and k.get("kart")]
    if cards:
        links = ", ".join(f"[[{jobs.stem(c)}]]" for c in cards)
        head += f" {len(cards)} denetçi önerisi kartı yazıldı ({links}): {sahip.e()} kartın beklediğini de söyle."
    return f"{SYSTEM_PREFIX}{head} Rapor:\n{kontrol._quote(entry.get('metin') or '', MAX_BILDIRIM)}"


def _sonuc(entry):
    return {"not": f"{NOT_ONEK}{entry['gun']}", "gun": entry["gun"], "oneriler": entry.get("oneriler") or [],
            "kartlar": [k["kart"] for k in entry.get("kartlar") or [] if isinstance(k, dict) and k.get("kart")],
            "rid": entry.get("rid")}


def yaz_ve_bildir(cfg, durum_dir, rid, now=None, ceo=None):
    """The ONLY writer of an Ar-Ge note, its cards and its notice, in that order, for the pending report `rid`.
    Idempotent through the done set durum/arge/yazilanlar.json: a report is written once (cards are recorded one by one,
    so a crash never opens a card twice) and told once (key arge-<rid>); a report written but not told yet (the queue
    failed, a restart) is only told on the next call. Returns {not, gun, oneriler, kartlar, rid}, or None when `rid` is
    neither pending nor written. Raises OSError when the note or a card cannot be written (retried later)."""
    with _YAZ:
        done = yazilanlar(durum_dir)
        entry = done.get(rid)
        if entry is None or not entry.get("yazildi"):
            rec = next((r for r in _records(durum_dir) if r.get("rid") == rid), None)
            if rec is None and entry is None:
                return None
            entry = _write_report(cfg, durum_dir, rid, rec or entry, entry or {}, now, done)
        if ceo is not None and not entry.get("bildirildi"):
            result = ceo.enqueue(bildirim(entry, durum_dir), f"{BILDIRIM_ONEK}{rid}")  # raises when it cannot queue
            if result in ("queued", "duplicate"):
                done = yazilanlar(durum_dir)
                done[rid] = {**done.get(rid, entry), "bildirildi": True}
                _save_done(durum_dir, done)
                entry = done[rid]
        return _sonuc(entry)


def _write_report(cfg, durum_dir, rid, src, entry, now, done):
    now = _office_now(cfg, now)
    vault = os.path.expanduser(str(cfg.get("vault_ofis") or ""))
    folder = _safe_folder(vault, FOLDER)
    gun = entry.get("gun") if isinstance(entry.get("gun"), str) and DAY.fullmatch(entry.get("gun")) else \
        now.strftime("%Y-%m-%d")
    job_name = jobs.check_name(src["is"])
    metin = str(src.get("metin") or "")
    entry = {**entry, "rid": rid, "is": job_name, "baslik": str(src.get("baslik") or "")[:200], "metin": metin,
             "gun": gun, "zaman": entry.get("zaman") or now.strftime("%Y-%m-%dT%H:%M:%S"), "yazildi": False,
             "bildirildi": False}
    kartlar = {k["model"]: k["kart"] for k in entry.get("kartlar") or [] if isinstance(k, dict) and k.get("model")}
    done[rid] = entry
    _save_done(durum_dir, done)  # the day is fixed before anything is written: a retry after midnight keeps it
    found = oneriler(metin)
    cards_dir = None
    for o in found:
        if not o["lisans"]:
            continue
        if o["model"] in kartlar:
            o["kart"] = kartlar[o["model"]]
            continue
        if len(kartlar) >= MAX_KART:
            o["sebep"] = f"bir raporda en çok {MAX_KART} kart açılır"
            continue
        pending = _pending_card(vault, o["model"])
        if pending and pending[1].get("kaynak_is") == jobs.stem(job_name):
            # this job's own card, written before a crash recorded it: adopt it (never a second one)
            kartlar[o["model"]] = pending[0]
            o["kart"] = pending[0]
            continue
        if pending:
            o["sebep"] = f"bekleyen kartı var: [[{jobs.stem(pending[0])}]]"
            continue
        cards_dir = cards_dir or _safe_folder(vault, "Kararlar")
        name = _card_name(cards_dir, gun)
        jobs._write_atomic(os.path.join(cards_dir, name), kart_metni(o, gun, job_name, now))
        kartlar[o["model"]] = name
        o["kart"] = name
        entry["kartlar"] = [{"model": m, "kart": k} for m, k in kartlar.items()]
        done[rid] = entry
        _save_done(durum_dir, done)  # recorded card by card: a re-run never opens it again
    entry["kartlar"] = [{"model": m, "kart": k} for m, k in kartlar.items()]
    entry["oneriler"] = found
    reports = sorted([e for k, e in done.items() if k != rid and e.get("yazildi") and e.get("gun") == gun] + [entry],
                     key=lambda e: (str(e.get("zaman")), e["is"]))
    day = gun_verisi(durum_dir, gun)
    jobs._write_atomic(os.path.join(folder, f"{NOT_ONEK}{gun}.md"), _not_metni(gun, reports, (day or {}).get("fark")))
    entry["yazildi"] = True
    done[rid] = entry
    _prune_done(done, durum_dir)
    _save_done(durum_dir, done)
    # written: the pending record goes (the done entry is the report from now on), so pruning the done set later can
    # never turn it back into a pending report
    rpath = _record_path(durum_dir, job_name)
    if (_read_json(rpath) or {}).get("rid") == rid:
        try:
            os.unlink(rpath)
        except OSError:
            pass
    return entry


def _prune_done(done, durum_dir):
    """Drops told entries older than KEEP_DAYS report days — never one whose pending record still exists."""
    days = sorted({e.get("gun") for e in done.values() if isinstance(e.get("gun"), str)})
    keep = set(days[-KEEP_DAYS:])
    pending = {r.get("rid") for r in _records(durum_dir)}
    for k in [k for k, e in done.items() if e.get("bildirildi") and e.get("gun") not in keep and k not in pending]:
        del done[k]


def bekleyenleri_yaz(cfg, durum_dir, now=None, ceo=None, log=None):
    """The background writer's pass (the only caller of yaz_ve_bildir): every pending report whose job is `bitti` (no
    Kontrol, or its Kontrol passed) is written and told; a report written but not told yet is told. A report whose job
    is still at work (its Kontrol failed and the job goes on) stays pending until a newer report replaces it."""
    vault = os.path.expanduser(str(cfg.get("vault_ofis") or ""))
    done = yazilanlar(durum_dir)
    rids = [rid for rid, e in done.items() if e.get("yazildi") and not e.get("bildirildi")]
    for r in _records(durum_dir):
        rid = r.get("rid")
        if not rid or (done.get(rid) or {}).get("bildirildi") or rid in rids:
            continue
        try:
            job = jobs.find(vault, r["is"])
        except jobs.JobError:
            job = None
        # bitti on the note AND, on the server record, no Kontrol or a passed one (`bitir` by hand is neither)
        if job is not None and job.meta.get("durum") == "bitti" and \
                records.server_value(durum_dir, job.name, "kontrol_sonuc") in ("yok", "gecti"):
            rids.append(rid)
    for rid in rids:
        try:
            yaz_ve_bildir(cfg, durum_dir, rid, now=now, ceo=ceo)
        except Exception as e:  # noqa: BLE001 — retried on the next pass; said once per report
            if log and rid not in _LOGGED:
                _LOGGED.add(rid)
                log(f"ofis: Ar-Ge raporu yazılamadı ya da bildirilemedi ({rid}): {type(e).__name__}: {e}")


# --- the page (GET /api/arge: the Ar-Ge uzmanı's card) ---

def _ozet(metin):
    out = []
    for line in str(metin or "").splitlines():
        line = " ".join(_temiz(line).split()).lstrip("#> ").strip()
        if not line or ONERI.match(line.translate(FOLD)):
            continue
        out.append(line[:160])
        if len(out) >= OZET_SATIR:
            break
    return out


def sayfa(cfg, durum_dir):
    """{son_rapor: {gun, is, baslik, not, ozet, oneriler} | None, fark: the last diff | None, kontrol_gunu, surumler}."""
    reports = [e for e in yazilanlar(durum_dir).values() if e.get("yazildi") and isinstance(e.get("is"), str)]
    son = max(reports, key=lambda r: (str(r.get("zaman")), r["is"])) if reports else None
    days = gunler(durum_dir)
    last = gun_verisi(durum_dir, days[-1]) if days else None
    return {
        "son_rapor": {"gun": son["gun"], "is": son["is"], "baslik": str(son.get("baslik") or ""),
                      "not": f"{NOT_ONEK}{son['gun']}", "ozet": _ozet(son.get("metin")),
                      "oneriler": [{"model": o.get("model"), "lisans": o.get("lisans"), "neden": o.get("neden"),
                                    "kart": o.get("kart")} for o in son.get("oneriler") or [] if isinstance(o, dict)]}
        if son else None,
        "fark": son_fark(durum_dir),
        "kontrol_gunu": days[-1] if days else None,
        "surumler": (last or {}).get("surumler"),
    }
