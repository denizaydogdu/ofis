"""The owner's Claude plan usage limits (owner decision 2026-11-14).

The owner's statusline script writes `~/.claude/ofis/limitler.json` (mode 0600) on every turn of an interactive Claude
Code session: {"five_hour": {"used_percentage", "resets_at"}, "seven_day": {...}, "saved_at"} (epoch seconds; either
window may be missing or null). The office only READS it: `oku` validates it and never fails on a missing or broken
file; `metin` / `kisa` turn it into plain Turkish; `sayfa` = `/api/state.limitler`; `LimitUyarisi` sends ONE CEO
notice the first time a window crosses each threshold of ofis.json `limitler.uyari` (default 80 and 95), idempotent
per window (its `resets_at`) through `durum/limitler/uyarilar.json` and the CEO queue's key.

ofis.json `limitler: {acik, uyari, dosya}`: missing or `acik` not true = off (no state field, no line, no notice);
`dosya` (optional) replaces the default path. The file is only refreshed while an interactive session runs, so a
reading older than `ESKI_DK` minutes is marked `eski` and its time is shown.
"""
import json
import os
import stat
import tempfile
import threading
import time
from datetime import datetime, timedelta

import dil
import model_durum
import sahip

VARSAYILAN_DOSYA = "~/.claude/ofis/limitler.json"
VARSAYILAN_UYARI = (80, 95)
ESKI_DK = 30
MAX_BOYUT = 64 * 1024
GELECEK_TOLERANS_S = 300  # a saved_at this far in the future is not trusted
MAX_ILERI_S = 8 * 24 * 3600  # a reset further ahead than a week (+1 day) is not trusted
AYNI_PENCERE_S = 30 * 60  # resets_at values this close belong to the same window (jitter between turns)
STATE_DIR = "limitler"
STATE_FILE = "uyarilar.json"
SYSTEM_PREFIX = "[Ofis · sistem]\n"
# (our name, the file's key, the label in a sentence, the short label of the pill)
PENCERELER = (("haftalik", "seven_day", dil.N_("Haftalık"), dil.N_("Haftalık")),
              ("bes_saat", "five_hour", dil.N_("5 saatlik"), dil.N_("5 saat")))  # labels: dil.t where drawn
GUNLER = ("pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar")
AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
         "Aralık")
# English (ofis.json dil "en"; bin/dil.py): the page path only (sayfa / metin / kisa with dil_kodu="en")
GUNLER_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
AYLAR_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
            "November", "December")


# --- config ---

def ayar(cfg):
    """{acik, uyari (sorted ints 1..100), dosya (expanded path)} from ofis.json `limitler`."""
    raw = (cfg or {}).get("limitler")
    raw = raw if isinstance(raw, dict) else {}
    uyari = raw.get("uyari", list(VARSAYILAN_UYARI))
    if not isinstance(uyari, list):
        uyari = list(VARSAYILAN_UYARI)
    esikler = sorted({int(u) for u in uyari if isinstance(u, (int, float)) and not isinstance(u, bool)
                      and 1 <= u <= 100})
    dosya = raw.get("dosya") if isinstance(raw.get("dosya"), str) and raw.get("dosya").strip() else VARSAYILAN_DOSYA
    return {"acik": raw.get("acik") is True, "uyari": esikler, "dosya": os.path.expanduser(dosya)}


def _tz(cfg):
    """The office time zone (ofis.json ofis_sahnesi.saat_dilimi, as bin/ozet.py)."""
    return model_durum.office_tz(model_durum.saat_dilimi(cfg))


# --- reading ---

def _sayi(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        and value not in (float("inf"), float("-inf"))


def _dosya_oku(yol):
    """The file's JSON object, or None (missing, not a regular file, too big, unreadable, not an object)."""
    try:
        fd = os.open(yol, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BOYUT:
            return None
        with os.fdopen(fd, "rb") as f:
            fd = None
            data = json.loads(f.read(MAX_BOYUT + 1).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    return data if isinstance(data, dict) else None


def _pencere(raw, now):
    """{yuzde, sifirlanma, gecti} of one window, or None when it is missing or unusable. A window whose reset time
    has passed is `gecti` with yuzde None: it was reset and nothing has been measured since."""
    if not isinstance(raw, dict):
        return None
    yuzde, reset = raw.get("used_percentage"), raw.get("resets_at")
    if not _sayi(yuzde) or not 0 <= yuzde <= 100:
        return None
    sifirlanma = int(reset) if _sayi(reset) and 0 < reset <= now + MAX_ILERI_S else None
    if sifirlanma is not None and sifirlanma <= now:
        return {"yuzde": None, "sifirlanma": sifirlanma, "gecti": True}
    return {"yuzde": int(round(yuzde)), "sifirlanma": sifirlanma, "gecti": False}


def oku(now=None, yol=None):
    """{bes_saat, haftalik, olculdu, eski} from the file, or None when there is no usable data. Read-only; never
    raises. `now` is epoch seconds (default: now)."""
    now = time.time() if now is None else float(now)
    data = _dosya_oku(os.path.expanduser(yol or VARSAYILAN_DOSYA))
    if data is None:
        return None
    out = {ad: _pencere(data.get(anahtar), now) for ad, anahtar, _, _ in PENCERELER}
    if out["bes_saat"] is None and out["haftalik"] is None:
        return None
    saved = data.get("saved_at")
    olculdu = int(saved) if _sayi(saved) and 0 < saved <= now + GELECEK_TOLERANS_S else None
    out["olculdu"] = olculdu
    out["eski"] = olculdu is None or now - olculdu > ESKI_DK * 60
    return out


# --- text ---

# the last spoken word of a number 0..100 -> (locative suffix, accusative suffix): "21:00'de", "19:30'da", "%80'i",
# "%90'ı"
_EK = {"sıfır": ("da", "ı"), "bir": ("de", "i"), "iki": ("de", "yi"), "üç": ("te", "ü"), "dört": ("te", "ü"),
       "beş": ("te", "i"), "altı": ("da", "yı"), "yedi": ("de", "yi"), "sekiz": ("de", "i"), "dokuz": ("da", "u"),
       "on": ("da", "u"), "yirmi": ("de", "yi"), "otuz": ("da", "u"), "kırk": ("ta", "ı"), "elli": ("de", "yi"),
       "altmış": ("ta", "ı"), "yetmiş": ("te", "i"), "seksen": ("de", "i"), "doksan": ("da", "ı"), "yüz": ("de", "ü")}
_BIRLER = ("sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_ONLAR = ("", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan")


def _son_kelime(n):
    n = int(n)
    if n == 100:
        return "yüz"
    if n == 0 or n % 10:
        return _BIRLER[n % 10]
    return _ONLAR[(n // 10) % 10]


def yuzde_i(n):
    """"%80'i", "%90'ı", "%95'i" (the accusative after a percentage)."""
    return f"%{int(n)}'{_EK[_son_kelime(n)][1]}"


def _yerel(ts, tz):
    return datetime.fromtimestamp(ts, tz)


def _saat_de(t):
    """The locative suffix of a clock time as it is read ("21:00'de", "19:30'da", "15:00'te")."""
    return _EK[_son_kelime(t.minute if t.minute else t.hour)][0]


def zaman_en(ts, now, tz, gun_adi=True, edat=True):
    """The English twin of _zaman: "at 21:00", "today at 21:00", "tomorrow at 21:00", "on Wednesday at 22:00",
    "on 20 November at 22:00"; without `edat` the bare forms ("21:00", "yesterday 21:30", "Wednesday 22:00")."""
    t, n = _yerel(ts, tz), _yerel(now, tz)
    saat = t.strftime("%H:%M")
    at = f"at {saat}" if edat else saat
    fark = (t.date() - n.date()).days
    if fark == 0:
        return f"today {at}" if gun_adi else at
    if fark == 1:
        return f"tomorrow {at}"
    if fark == -1:
        return f"yesterday {at}"
    gun = GUNLER_EN[t.weekday()] if 1 < fark < 7 else f"{t.day} {AYLAR_EN[t.month - 1]}"
    return f"on {gun} {at}" if edat else f"{gun} {saat}"


def _zaman(ts, now, tz, gun_adi=True, dil_kodu="tr"):
    """"21:00'de", "yarın 21:00'de", "çarşamba 22:00'de" (within a week) or "20 Kasım 22:00'de", in the office zone;
    today without a day name unless `gun_adi` ("bugün 21:00'de"). dil_kodu "en": zaman_en."""
    if dil_kodu == "en":
        return zaman_en(ts, now, tz, gun_adi)
    t, n = _yerel(ts, tz), _yerel(now, tz)
    saat = f"{t.strftime('%H:%M')}'{_saat_de(t)}"
    fark = (t.date() - n.date()).days
    if fark == 0:
        return saat if not gun_adi else f"bugün {saat}"
    if fark == 1:
        return f"yarın {saat}"
    if fark == -1:
        return f"dün {saat}"
    if 1 < fark < 7:
        return f"{GUNLER[t.weekday()]} {saat}"
    return f"{t.day} {AYLAR[t.month - 1]} {saat}"


def _parca(etiket, p, now, tz, ilk, dil_kodu="tr"):
    etiket = dil.t(etiket, dil_kodu)
    if p["gecti"]:
        return dil.t("{etiket} sınır sıfırlandı (yeni değer henüz ölçülmedi)", dil_kodu, etiket=etiket)
    head = dil.t("{etiket} sınır %{yuzde}" if ilk else "{etiket} %{yuzde}", dil_kodu, etiket=etiket,
                 yuzde=p["yuzde"])
    if p["sifirlanma"] is None:
        return head
    zaman = _zaman(p["sifirlanma"], now, tz, gun_adi=ilk, dil_kodu=dil_kodu)
    return dil.t("{head} · {zaman} sıfırlanır" if ilk else "{head} · {zaman}", dil_kodu, head=head, zaman=zaman)


def metin(veri, now=None, tz=None, dil_kodu="tr"):
    """"Haftalık sınır %54 · çarşamba 22:00'de sıfırlanır · 5 saatlik %62 · 21:00'de" (+ " · 19:41'de ölçüldü"
    when the reading is old); None without data. dil_kodu "en": the page's English (bin/dil.py)."""
    if not isinstance(veri, dict):
        return None
    now = time.time() if now is None else float(now)
    tz = tz or model_durum.office_tz()
    parts = []
    for ad, _, etiket, _ in PENCERELER:
        p = veri.get(ad)
        if isinstance(p, dict):
            parts.append(_parca(etiket, p, now, tz, ilk=not parts, dil_kodu=dil_kodu))
    if not parts:
        return None
    out = " · ".join(parts)
    if veri.get("eski"):
        olc = veri.get("olculdu")
        out += " · " + (dil.t("{zaman} ölçüldü", dil_kodu, zaman=_zaman(olc, now, tz, gun_adi=False,
                                                                         dil_kodu=dil_kodu))
                        if olc else dil.t("ölçüm zamanı bilinmiyor", dil_kodu))
    return out


def kisa(veri, dil_kodu="tr"):
    """The pill's text: "Haftalık %54 · 5 saat %62" (a reset window: "sıfırlandı"); None without data."""
    if not isinstance(veri, dict):
        return None
    parts = []
    for ad, _, _, etiket in PENCERELER:
        p = veri.get(ad)
        if isinstance(p, dict):
            parts.append(dil.t("{etiket} sıfırlandı" if p["gecti"] else "{etiket} %{yuzde}", dil_kodu,
                               etiket=dil.t(etiket, dil_kodu), yuzde=p["yuzde"]))
    return " · ".join(parts) or None


def sayfa(cfg, now=None, dil_kodu="tr"):
    """/api/state.limitler: the reading plus `metin` (the tooltip) and `kisa`; None when off or without data.
    dil_kodu: the texts' language (the page passes ofis.json dil; satir and the notices stay Turkish)."""
    a = ayar(cfg)
    if not a["acik"]:
        return None
    now = time.time() if now is None else float(now)
    veri = oku(now, a["dosya"])
    if veri is None:
        return None
    return {**veri, "metin": metin(veri, now, _tz(cfg), dil_kodu), "kisa": kisa(veri, dil_kodu)}


def satir(cfg, now=None):
    """The one line for the morning summary, the end-of-day note and Jarvis: "Claude kullanım sınırı: …"; None when
    off or without data."""
    s = sayfa(cfg, now)
    return f"Claude kullanım sınırı: {s['metin']}" if s and s.get("metin") else None


# --- the warning (one notice per window and threshold) ---

def bildirim(etiket, esik, p, now, tz):
    zaman = f"; {_zaman(p['sifirlanma'], now, tz)} sıfırlanır" if p.get("sifirlanma") else ""
    simdi = f" (şu an %{p['yuzde']})" if p["yuzde"] != esik else ""
    return (f"{SYSTEM_PREFIX}{etiket} kullanım sınırının {yuzde_i(esik)} doldu{simdi}{zaman}.\n"
            f"- {sahip.e()} tek satırla söyle. Ağır işleri (Kıdemli, Fable) sıfırlanmaya kadar bekletmeyi yalnızca öneri "
            "olarak söyleyebilirsin; hiçbir işi kendin durdurma ya da bekletme.")


class LimitUyarisi:
    """The server's pass: kontrol() sends the notices that are due (see the module doc)."""

    def __init__(self, cfg, durum_dir, ceo, now=None, log=None):
        self.cfg = cfg  # a callable: ofis.json as it is now
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.now = now  # a callable returning epoch seconds (tests)
        self.log = log or (lambda line: None)
        self._lock = threading.Lock()

    def _yol(self):
        return os.path.join(self.durum_dir, STATE_DIR, STATE_FILE)

    def _durum(self):
        data = _dosya_oku(self._yol())
        return data if isinstance(data, dict) else {}

    def _kaydet(self, data):
        folder = os.path.dirname(self._yol())
        if os.path.islink(folder) or os.path.islink(self._yol()):
            raise OSError("the limitler state is a link")
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".uyarilar-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
            os.replace(tmp, self._yol())
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def kontrol(self):
        """Sends the due notices; returns the list of (window, threshold) sent."""
        with self._lock:
            cfg = self.cfg()
            a = ayar(cfg)
            if not a["acik"] or not a["uyari"]:
                return []
            now = float(self.now()) if self.now else time.time()
            veri = oku(now, a["dosya"])
            if veri is None:
                return []
            tz = _tz(cfg)
            data = self._durum()
            sent, changed = [], False
            for ad, _, etiket, _ in PENCERELER:
                p = veri.get(ad)
                if not isinstance(p, dict) or p["gecti"] or p["yuzde"] is None or p["sifirlanma"] is None:
                    continue
                kayit = data.get(ad) if isinstance(data.get(ad), dict) else {}
                eski_reset = kayit.get("sifirlanma")
                if not _sayi(eski_reset) or abs(p["sifirlanma"] - eski_reset) > AYNI_PENCERE_S:
                    kayit = {"sifirlanma": p["sifirlanma"], "gonderilen": []}  # a new window
                    changed = True
                gonderilen = [g for g in kayit.get("gonderilen") or [] if isinstance(g, int)]
                yeni = [e for e in a["uyari"] if p["yuzde"] >= e and e not in gonderilen]
                if yeni:
                    esik = max(yeni)  # 70 → 96 at once: one notice for 95, 80 counts as told
                    key = f"limit-{ad}-{int(kayit['sifirlanma'])}-{esik}"  # the CEO queue dedups by key, too
                    self.ceo.enqueue(bildirim(etiket, esik, p, now, tz), key)
                    gonderilen = sorted(set(gonderilen) | set(yeni))
                    sent.append((ad, esik))
                    changed = True
                data[ad] = {"sifirlanma": int(kayit["sifirlanma"]), "gonderilen": gonderilen}
            if changed:
                self._kaydet(data)
            return sent

    def run(self, stop_event, interval=60):
        while not stop_event.is_set():
            try:
                self.kontrol()
            except Exception as e:  # noqa: BLE001 — never stops the server
                self.log(f"ofis: kullanım sınırı uyarısı hatası: {type(e).__name__}: {e}")
            stop_event.wait(interval)
