"""Who used the most of the owner's Claude plan in the current 5-hour and weekly windows (owner decision 2026-11-16).

GET /api/kullanim (the popup under the top bar's usage pill): for each limit window its percentage, the reset time in
plain Turkish and when it was measured (bin/limitler.py), and "En çok kullananlar": the token usage of the window from
the Claude Code transcripts (~/.claude/projects/<encoded cwd>/<sessionId>.jsonl and their subagent transcripts
`<sessionId>/subagents/*.jsonl`, counted to their parent session), grouped by who used it.

Windows: 5 saatlik = five_hour.resets_at - 5 h .. now, haftalık = seven_day.resets_at - 7 days .. now; without a
usable reset time (no limit file, a reset already passed) the last 5 hours / 7 days (`tahmini`).

Grouping (the owner chose it):
- the CEO session (its name from ofis.json `ceo_session`, in this repository's transcript folder) -> "CEO";
- an office job session (a name starting with "ofis-") -> the job's title and project from the office's own job notes
  and records (by session name or recorded session id), else "<proje> işi" when the project is a registered one,
  else "Ofis işi" — never the raw name;
- the managers' and the review panel's `claude -p` calls (an unnamed `sdk-cli` session in a registered project's
  folder, or any session in the review panel's temporary `ofis-denetci-` copy) -> "Müdür ve hakem çağrıları";
- an interactive session in this repository's folder that is not the CEO -> "Geliştirici oturumu";
- a session in Jarvis's folder (ofis.json `jarvis.klasor`, optional: where the owner builds Jarvis; Jarvis itself runs no
  Claude session) -> "Jarvis"; without that key there is no Jarvis row;
- everything else -> ONE row "Ofis dışı diğer oturumlar" (no names, folders or paths).
Forbidden folders (transcript.forbidden_folder: the forbidden projects and lookalikes) are never listed, opened or counted.

Calls are de-duplicated by message.id across every file (a resumed session copies earlier records); synthetic
messages are not calls. Only records whose timestamp is inside a window count. The response carries display names
and numbers only: never message text, paths, folder names or session ids.

Cost: only transcript files written since the weekly start are opened; each file is read incrementally (byte offset,
cached by inode and size) and a large one is entered by bisecting its timestamps, so the old part of a long session is
skipped. The whole breakdown is cached for CACHE_S seconds and computed only when the popup asks for it.
"""
import json
import os
import re
import threading
import time

import budget
import jobs
import limitler
import pricing
import records
import transcript

CACHE_S = 60
BES_SAAT_S = 5 * 3600
HAFTA_S = 7 * 86400
PAYLASIM_S = 3600            # bisect this much before the weekly start (timestamps are only roughly ordered)
BOLUM = 8 * 1024 * 1024      # bytes per read
MAX_GECIS = 256 * 1024 * 1024  # bytes read from one file per request; the rest on the next request
BOLME_ESIGI = 4 * 1024 * 1024  # files above this are entered by bisecting their timestamps
MAX_DOSYA = 3000             # transcript files looked at per request
MAX_SATIR = 12               # rows shown; the smaller ones are merged into one row
DENETCI_PARCASI = "-ofis-denetci-"  # bin/denetci.py snapshot folders (tempfile prefix "ofis-denetci-")
ASSISTANT = re.compile(rb'"type":\s*"assistant"')
TIMESTAMP = re.compile(rb'"timestamp":\s*"([^"\\]{10,40})"')
ENTRYPOINT = re.compile(rb'"entrypoint":\s*"([a-z-]{1,20})"')
OFIS_ADI = re.compile(r"ofis-([a-z0-9-]{1,40}?)-\d{4}-\d{6}-[0-9a-f]{4}")

CEO, IS, YAN, GELISTIRICI, JARVIS, DIGER, KUCUK = "ceo", "is", "yan", "gelistirici", "jarvis", "diger", "kucuk"
ADLAR = {CEO: "CEO", YAN: "Müdür ve hakem çağrıları", GELISTIRICI: "Geliştirici oturumu", JARVIS: "Jarvis",
         DIGER: "Ofis dışı diğer oturumlar"}
NOT_METNI = ("Plan yüzdesi tokenlarla birebir orantılı değildir (önbellekten okunan tokenlar daha hafif sayılır); "
             "bu liste kimin en çok kullandığını gösterir, kesin payını değil.")
ESKI_ACIKLAMA = "Son ölçüm eski: değerler bir Claude oturumu açılınca yenilenir."


# --- reading one transcript file ---

class _Dosya:
    """The calls of one transcript file read so far: [(epoch, message id or None, tokens, output tokens, usd or
    None)], plus its entrypoint ("cli", "sdk-cli", …)."""
    __slots__ = ("ino", "offset", "partial", "calls", "entry")

    def __init__(self, ino, offset):
        self.ino, self.offset, self.partial, self.calls, self.entry = ino, offset, b"", [], None


def _zaman_at(f, offset):
    """Epoch seconds of the first complete record's timestamp after `offset`, or None."""
    window = 256 * 1024
    f.seek(offset)
    data = f.read(window)
    start = data.find(b"\n") + 1 if offset else 0
    lines = data[start:].split(b"\n")
    if len(data) == window:
        lines.pop()  # cut by the window
    for line in lines:
        m = TIMESTAMP.search(line)
        if m:
            when = transcript.parse_time(m.group(1).decode("ascii", "replace"))
            if when:
                return when.timestamp()
    return None


def _ilk_ofset(path, size, since):
    """A byte offset at or before the first record written at `since` (bisecting the timestamps); 0 when unsure."""
    lo, hi = 0, size
    try:
        with open(path, "rb") as f:
            for _ in range(40):
                if hi - lo < 1024 * 1024:
                    break
                mid = (lo + hi) // 2
                t = _zaman_at(f, mid)
                if t is None:
                    break
                if t < since:
                    lo = mid
                else:
                    hi = mid
    except OSError:
        return 0
    return lo


def _cagri(line, keep_since):
    """(epoch, message id, tokens, output tokens, usd or None, entrypoint) of an assistant record with usage, else
    None. Broken lines are skipped."""
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("model") == "<synthetic>":
        return None
    usage = message.get("usage")
    when = transcript.parse_time(record.get("timestamp"))
    if not isinstance(usage, dict) or when is None or when.timestamp() < keep_since:
        return None
    tokens = sum(v for v in (usage.get(k) for k in transcript.USAGE_FIELDS) if isinstance(v, int) and v > 0)
    _, adv_tokens, adv_cost = transcript._advisor_iterations(usage)
    out = usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else 0
    cost = pricing.call_cost(message.get("model"), usage)
    msg_id = message.get("id") if isinstance(message.get("id"), str) and message.get("id") else None
    return (when.timestamp(), msg_id, tokens + adv_tokens, max(0, out),
            None if cost is None else cost["total"] + adv_cost)


def _oku(c, path, st, keep_since):
    """Reads what was appended to the file since the last pass (at most MAX_GECIS bytes)."""
    try:
        f = open(path, "rb")
    except OSError:
        return
    with f:
        read = 0
        while c.offset < st.st_size and read < MAX_GECIS:
            f.seek(c.offset)
            data = f.read(min(BOLUM, st.st_size - c.offset))
            if not data:
                break
            c.offset += len(data)
            read += len(data)
            lines = (c.partial + data).split(b"\n")
            c.partial = lines.pop()
            if len(c.partial) > MAX_GECIS:
                c.partial = b""  # a giant line (an attachment): never an assistant record worth keeping
            for line in lines:
                if c.entry is None:
                    m = ENTRYPOINT.search(line[:4096])
                    if m:
                        c.entry = m.group(1).decode("ascii")
                if b'"usage"' not in line or not ASSISTANT.search(line):
                    continue
                call = _cagri(line, keep_since)
                if call:
                    c.calls.append(call)


# --- grouping ---

def jarvis_klasoru(cfg):
    """ofis.json `jarvis.klasor` (the folder Jarvis is built in), or None when it is not set."""
    raw = (cfg or {}).get("jarvis") if isinstance(cfg, dict) else None
    value = raw.get("klasor") if isinstance(raw, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _klasor_adlari(cwd):
    return set(transcript._folder_names(os.path.expanduser(cwd))) if isinstance(cwd, str) and cwd else set()


def is_haritasi(vault_ofis, durum_dir):
    """({session name: (title, project)}, {session id: (title, project)}) from the office's job notes and their
    server records (the record's session first; the note's for reading only). Display data only."""
    import state  # lazy: state is heavy and only the title helper is needed
    by_name, by_id = {}, {}
    for job in jobs.list_jobs(vault_ofis, legacy=True):
        meta = job.meta or {}
        rec = (records.load(durum_dir, job.name) or {}) if durum_dir else {}
        try:
            title = state.task_title(meta, job.body)
        except Exception:  # noqa: BLE001 — a broken note: its name
            title = job.name[:-3]
        proje = str(rec.get("proje") or meta.get("proje") or "")[:40]
        value = (str(title or job.name[:-3])[:140], proje)
        for name in {str(rec.get("oturum") or ""), str(meta.get("oturum") or "")} - {""}:
            by_name.setdefault(name, value)
        for sid in records.session_ids(rec):
            by_id.setdefault(sid, value)
    return by_name, by_id


def _sinif(kind, proje, names, entry, sid, ceo_name, isler, projeler):
    """(group key, display name, kind) of one session."""
    by_name, by_id = isler
    if kind == "ofis" and ceo_name in names:
        return CEO, ADLAR[CEO], CEO
    ofis_names = sorted(n for n in names if n.startswith("ofis-") and n != ceo_name)
    if kind == "denetci":
        return YAN, ADLAR[YAN], YAN
    job = next((by_name[n] for n in ofis_names if n in by_name), None) or by_id.get(sid)
    if job:
        title, p = job
        return f"is:{title}|{p}", (f"{title} ({p})" if p else title), IS
    if ofis_names:
        m = OFIS_ADI.fullmatch(ofis_names[0])
        p = m.group(1) if m and m.group(1) in projeler else proje
        ad = f"{p} işi" if p else "Ofis işi"
        return f"is:{ad}", ad, IS
    if kind == "proje" and not names and entry == "sdk-cli":
        return YAN, ADLAR[YAN], YAN
    if kind == "ofis" and entry != "sdk-cli":
        return GELISTIRICI, ADLAR[GELISTIRICI], GELISTIRICI
    if kind == "jarvis":
        return JARVIS, ADLAR[JARVIS], JARVIS
    return DIGER, ADLAR[DIGER], DIGER


# --- windows ---

def pencereler(veri, now):
    """{bes_saat: (start, tahmini), haftalik: (start, tahmini)} from the limit reading (bin/limitler.py oku)."""
    out = {}
    for ad, uzunluk in (("bes_saat", BES_SAAT_S), ("haftalik", HAFTA_S)):
        p = (veri or {}).get(ad) if isinstance(veri, dict) else None
        reset = p.get("sifirlanma") if isinstance(p, dict) and not p.get("gecti") else None
        start = reset - uzunluk if isinstance(reset, (int, float)) else None
        if start is None or start > now or start < now - uzunluk:
            out[ad] = (now - uzunluk, True)
        else:
            out[ad] = (float(start), False)
    return out


def _kalan(saniye):
    """"2 sa 14 dk sonra", "45 dk sonra", "3 gün 4 sa sonra", "1 dakikadan az kaldı"."""
    dk = int(saniye // 60)
    if dk < 1:
        return "1 dakikadan az kaldı"
    gun, sa, dk = dk // 1440, (dk % 1440) // 60, dk % 60
    if gun:
        return f"{gun} gün {sa} sa sonra" if sa else f"{gun} gün sonra"
    if sa:
        return f"{sa} sa {dk} dk sonra" if dk else f"{sa} sa sonra"
    return f"{dk} dk sonra"


def _beri(ts, now, tz):
    """"16:00'dan beri", "dün 21:30'dan beri", "çarşamba 22:00'den beri" (the ablative of limitler's clock text)."""
    zaman = limitler._zaman(ts, now, tz, gun_adi=False)
    return f"{zaman}n beri"  # 'de -> 'den, 'da -> 'dan, 'te -> 'ten, 'ta -> 'tan


def limit_bolumu(veri, now, tz):
    """The popup's limit part: per window its percentage, reset text and remaining time; when it was measured."""
    if not isinstance(veri, dict):
        return None
    out = []
    for ad, _, etiket, _ in limitler.PENCERELER:
        p = veri.get(ad)
        if not isinstance(p, dict):
            continue
        item = {"ad": ad, "etiket": etiket, "yuzde": p.get("yuzde"), "gecti": bool(p.get("gecti")),
                "yenilenir": "", "kalan": ""}
        if p.get("gecti"):
            item["yenilenir"] = "sıfırlandı (yeni değer henüz ölçülmedi)"
        elif p.get("sifirlanma"):
            item["yenilenir"] = f"{limitler._zaman(p['sifirlanma'], now, tz)} yenilenir"
            item["kalan"] = _kalan(p["sifirlanma"] - now)
        out.append(item)
    olc = veri.get("olculdu")
    return {"pencereler": out, "eski": bool(veri.get("eski")),
            "olculdu": f"{limitler._zaman(olc, now, tz)} ölçüldü" if olc else "ölçüm zamanı bilinmiyor",
            "eski_aciklama": ESKI_ACIKLAMA if veri.get("eski") else ""}


# --- the scan ---

def _satir(ad, tur, b):
    tok = b["token"]
    return {"ad": ad, "tur": tur, "token": tok, "cikti_token": b["cikti"], "usd": round(b["usd"], 6),
            "fiyat_eksik": b["fiyatsiz"] > 0, "oturum_sayisi": len(b["oturumlar"]),
            "metin": (f"{budget.token_text(tok)} · API karşılığı bilinmiyor" if b["fiyatsiz"] and not b["usd"]
                      and tok > 0 else budget.spend_text(b["usd"], tok if tok > 0 else None)),
            "cikti_metni": f"çıktı {budget.token_text(b['cikti'])}" if tok > 0 else ""}


def _bos():
    return {"token": 0, "cikti": 0, "usd": 0.0, "fiyatsiz": 0, "oturumlar": set()}


def _ekle(b, call, oturum):
    b["token"] += call[2]
    b["cikti"] += call[3]
    if call[4] is None:
        b["fiyatsiz"] += 1
    else:
        b["usd"] += call[4]
    b["oturumlar"].add(oturum)


def _liste(gruplar):
    rows = sorted(gruplar.items(), key=lambda kv: (-kv[1][2]["token"], kv[1][0]))
    out = [_satir(ad, tur, b) for _, (ad, tur, b) in rows[:MAX_SATIR]]
    rest = rows[MAX_SATIR:]
    if rest:
        merged = _bos()
        for _, (_, _, b) in rest:
            for k in ("token", "cikti", "usd", "fiyatsiz"):
                merged[k] += b[k]
            merged["oturumlar"] |= b["oturumlar"]
        out.append(_satir(f"Daha küçük {len(rest)} kullanım", KUCUK, merged))
    toplam = _bos()
    for _, (_, _, b) in rows:
        for k in ("token", "cikti", "usd", "fiyatsiz"):
            toplam[k] += b[k]
        toplam["oturumlar"] |= b["oturumlar"]
    return out, _satir("Toplam", "toplam", toplam)


class Kullanim:
    """The server's one instance: per-file read state kept between requests, the result cached CACHE_S seconds."""

    def __init__(self, projects_dir, root, durum_dir=None, vault_ofis=None, jarvis_klasoru=None,
                 clock=None, is_haritasi_fn=None):
        self.projects_dir = projects_dir
        self.root = root
        self.durum_dir = durum_dir
        self.vault_ofis = vault_ofis
        self.jarvis_klasoru = jarvis_klasoru
        self.clock = clock or time.time
        self.is_haritasi_fn = is_haritasi_fn
        self._files = {}
        self._cache = None  # (computed at, key, breakdown)
        self._lock = threading.Lock()

    def _isler(self):
        if self.is_haritasi_fn:
            return self.is_haritasi_fn()
        if not self.vault_ofis:
            return {}, {}
        try:
            return is_haritasi(self.vault_ofis, self.durum_dir)
        except Exception:  # noqa: BLE001 — display only: no titles, the "<proje> işi" rows
            return {}, {}

    def _klasorler(self, cfg):
        """[(folder path, kind, project)] of the transcript folders that are not forbidden."""
        ofis = _klasor_adlari(self.root)
        jarvis = _klasor_adlari(self.jarvis_klasoru or jarvis_klasoru(cfg))
        projeler = {}
        for name, p in ((cfg or {}).get("projects") or {}).items():
            if isinstance(p, dict):
                for folder in _klasor_adlari(p.get("path")):
                    projeler[folder] = name
        try:
            entries = list(os.scandir(self.projects_dir))
        except (OSError, TypeError):
            return []
        out = []
        for e in entries:
            if not e.is_dir(follow_symlinks=False) or transcript.forbidden_folder(e.path):
                continue  # forbidden projects and lookalikes: never listed, opened or counted
            if e.name in ofis:
                kind, proje = "ofis", ""
            elif e.name in jarvis:
                kind, proje = "jarvis", ""
            elif e.name in projeler:
                kind, proje = "proje", projeler[e.name]
            elif DENETCI_PARCASI in e.name:
                kind, proje = "denetci", ""
            else:
                kind, proje = "diger", ""
            out.append((e.path, kind, proje))
        return out

    def _dosyalar(self, folder, since):
        """[(path, parent session id, st)] of the transcripts (and subagent transcripts) written since `since`."""
        out = []
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return out
        for e in entries:
            try:
                if e.name.endswith(".jsonl") and transcript.valid_session_id(e.name[:-6]) \
                        and e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    if st.st_mtime >= since:
                        out.append((e.path, e.name[:-6], st))
                elif transcript.valid_session_id(e.name) and e.is_dir(follow_symlinks=False):
                    sub = os.path.join(e.path, "subagents")
                    if os.path.islink(sub) or not os.path.isdir(sub):
                        continue
                    for s in os.scandir(sub):
                        if s.name.endswith(".jsonl") and s.is_file(follow_symlinks=False):
                            st = s.stat(follow_symlinks=False)
                            if st.st_mtime >= since:
                                out.append((s.path, e.name, st))
            except OSError:
                continue
        return out

    def _dosya(self, path, st, keep_since):
        c = self._files.get(path)
        if c is None or c.ino != st.st_ino or st.st_size < c.offset:
            start = _ilk_ofset(path, st.st_size, keep_since - PAYLASIM_S) if st.st_size > BOLME_ESIGI else 0
            c = _Dosya(st.st_ino, start)
            if start:
                c.partial = b"\x00"  # the first line is cut: never parsed (a NUL makes it invalid JSON)
            self._files[path] = c
        _oku(c, path, st, keep_since - PAYLASIM_S)
        c.calls = [x for x in c.calls if x[0] >= keep_since - PAYLASIM_S]
        return c

    def dagilim(self, cfg, windows, now):
        """{bes_saat: {...}, haftalik: {...}}: the rows of each window (see the module doc)."""
        keep_since = min(w[0] for w in windows.values())
        # the read state of a file is kept for the longest window any request can ask for (a later request without
        # the limit file falls back to the last 7 days): bisect and prune by that, filter by the windows below
        scan_since = min(keep_since, now - HAFTA_S)
        ceo_name = str((cfg or {}).get("ceo_session") or "ofis-ceo")
        projeler = set(((cfg or {}).get("projects") or {}).keys())
        isler = self._isler()
        files, seen_paths = [], set()
        for folder, kind, proje in self._klasorler(cfg):
            for path, sid, st in self._dosyalar(folder, keep_since):
                files.append((getattr(st, "st_birthtime", None) or st.st_mtime, path, folder, kind, proje, sid, st))
        files.sort(key=lambda x: (x[0], x[1]))
        files = files[-MAX_DOSYA:]
        gruplar = {ad: {} for ad in windows}
        seen = set()
        siniflar = {}
        for _, path, folder, kind, proje, sid, st in files:
            seen_paths.add(path)
            c = self._dosya(path, st, scan_since)
            if not c.calls:
                continue
            key = (folder, sid)
            if key not in siniflar:
                parent = os.path.join(folder, f"{sid}.jsonl")
                names = transcript._head_names(parent) \
                    if os.path.isfile(parent) and not os.path.islink(parent) else frozenset()
                parent_c = self._files.get(parent)
                entry = (parent_c.entry if parent_c else None) or c.entry
                siniflar[key] = _sinif(kind, proje, names, entry, sid, ceo_name, isler, projeler)
            gkey, ad, tur = siniflar[key]
            for call in c.calls:
                if call[1] is not None:
                    if call[1] in seen:
                        continue
                    seen.add(call[1])
                for w, (start, _) in windows.items():
                    if start <= call[0] <= now + 300:
                        bucket = gruplar[w].setdefault(gkey, (ad, tur, _bos()))
                        _ekle(bucket[2], call, key)
        for path in [p for p in self._files if p not in seen_paths]:
            del self._files[path]  # a file that left the window (or was removed): forget it
        out = {}
        for w, (start, tahmini) in windows.items():
            satirlar, toplam = _liste(gruplar[w])
            out[w] = {"baslangic": int(start), "tahmini": tahmini, "satirlar": satirlar, "toplam": toplam}
        return out

    def sayfa(self, cfg, now=None):
        """GET /api/kullanim (see the module doc). Never raises for a missing or broken limit file."""
        now = float(self.clock() if now is None else now)
        tz = limitler._tz(cfg)
        a = limitler.ayar(cfg)
        try:
            veri = limitler.oku(now, a["dosya"])
        except Exception:  # noqa: BLE001 — display only
            veri = None
        windows = pencereler(veri, now)
        # a window from a reset time is the same window while its start stays; a fallback window ("the last 5 h")
        # moves with the clock, so it is cached by its kind only (at most CACHE_S seconds behind)
        key = tuple((w, None if windows[w][1] else int(windows[w][0] // 60)) for w in sorted(windows))
        with self._lock:
            hit = self._cache
            if hit and hit[1] == key and 0 <= now - hit[0] < CACHE_S:
                breakdown = hit[2]
            else:
                breakdown = self.dagilim(cfg, windows, now)
                self._cache = (now, key, breakdown)
        dagilim = {}
        for w, d in breakdown.items():
            uzun = "5 saat" if w == "bes_saat" else "7 gün"
            beri = f"Son {uzun}" if d["tahmini"] else f"Bu pencere: {_beri(d['baslangic'], now, tz)}"
            dagilim[w] = {**d, "aralik": beri}
        return {"limitler": limit_bolumu(veri, now, tz), "dagilim": dagilim, "not": NOT_METNI,
                "hesaplandi": int(self._cache[0])}
