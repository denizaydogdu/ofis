"""Scheduled jobs (phase 6, ADR-002 "Zamanlanmış işler"): a job the server adds by itself at a local time of day.

Definitions are trusted server files, durum/zamanlanmis/<ad>.json, changed only through `ofis.py zamanla …`
(ekle, listele, durdur, devam, sil; project sessions are denied the command, see launch.DENIED_COMMANDS). A definition
holds the brief, the Kontrol with its sha256 (kontrol_ozet, checked before every run), the tier (model/effort only
when given explicitly, else the tier's current mapping), the approved budget (the default is fixed at `zamanla ekle`),
the time (saat, HH:MM local) and the weekdays (gunler: pzt sal car per cum cmt paz), the status (etkin, durduruldu,
kaldirildi — `sil` never deletes: the file and its history stay, the name is never reused) and the run state the
server keeps: son_slot (the last slot handled), acik_slot (a slot whose job is being added: crash recovery), kosular
(runs: slot, job, outcome), atlananlar (skipped slots and why), sayim_baslangic (failures before it do not count;
set by `devam`), son_hata (the last refused add), bildirilen (CEO notice keys sent). Every write is a temp file +
os.replace under the job lock (jobs.locked), so the CLI and the server never interleave.

The server's pass (Scheduler.run_once, called by the post office right before each dispatcher pass; deterministic, no
model call, local time):
- the latest slot at or before now (on an allowed weekday, not before the schedule was added or resumed) is due when
  it is after son_slot. Only that latest slot is ever looked at, so a computer that was off for days catches up at
  most once; a due slot more than 24 hours old is recorded as missed (kaçırıldı) and not run.
- never two open runs: when an earlier run's job (followed through an escalation, records `yukseltildi`) is not final,
  the slot is recorded as skipped (atlandı) and logged.
- the run is a normal `sirada` job added through ofis.add_job (Sıradakiler limit, server record, trusted Kontrol and
  brief) with grup = "<ad>-<YYYYMMDD-HHMM>" (so each run is reportable, bin/rapor.py) and `zamanlama: <ad>` on the
  note; the dispatcher starts it like any job. A refused add (e.g. "Sıradakiler dolu") leaves the slot due: it is
  retried every pass, logged and told to the CEO once per slot and reason.
- idempotent: the grup is a deterministic key per schedule and slot. acik_slot is written before the add; a slot
  whose key already names a job (a server record, or — after a crash between the note and its record — a note) is
  adopted instead of adding a second job, and its missing record / trusted Kontrol / trusted brief are written from
  the definition (never from the note).
- after MAX_FAILURES consecutive finished runs that ended tikandi or basarisiz (iptal and open runs neither count nor
  reset; bitti resets) the schedule pauses itself and the CEO gets one notice to ask the owner.
- a Kontrol whose digest no longer matches pauses the schedule (nothing runs) with one notice.
The server also writes the display note OFIS/Zamanlanmis/<ad>.md (what, when, next run, last runs with links, paused
or not); it is display only and never read back. summaries() feeds the page.
"""
import hashlib
import json
import os
import re
from datetime import datetime, time, timedelta

import jobs
import kontrol
import launch
import records
import sahip
import uyarilar

FOLDER = "zamanlanmis"  # durum/zamanlanmis/<ad>.json
NOTES = "Zamanlanmis"  # OFIS/Zamanlanmis/<ad>.md
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
TIME = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
DAYS = ("pzt", "sal", "car", "per", "cum", "cmt", "paz")
DAY_TR = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
MONTH_TR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
            "Aralık")
ACTIVE, PAUSED, REMOVED = "etkin", "durduruldu", "kaldirildi"
STATUS_TR = {ACTIVE: "etkin", PAUSED: "duraklatıldı", REMOVED: "kaldırıldı"}
RESULT_TR = {"bitti": "bitti", "tikandi": "takıldı", "basarisiz": "başlatılamadı", "iptal": "iptal edildi",
             "yok": "not bulunamadı", "": "sürüyor"}
SLOT = "%Y-%m-%dT%H:%M"
CATCH_UP = timedelta(hours=24)
MAX_FAILURES = 2
FAILED = ("tikandi", "basarisiz")
KEEP = 30  # runs and skipped slots kept in a definition
PAGE_RUNS = 5  # runs per schedule sent to the page (summaries)
RETRY = timedelta(seconds=60)  # a refused add is tried again at most this often
MAX_CHAIN = 10  # escalations followed
BRIEF_KEYS = ("hedef", "neden", "kisitlar", "kapsam_disi")
SYSTEM_PREFIX = "[Ofis · sistem]\n"


class Refused(launch.Refused):
    """A `zamanla` command was refused; the message is shown to the CEO."""


def _stamp(now):
    return f"{now:%Y-%m-%dT%H:%M:%S}"


def _parse(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def check_name(ad):
    if not isinstance(ad, str) or not NAME.fullmatch(ad):
        raise Refused(f"invalid schedule name {ad!r}: lowercase letters, digits and dashes, at most 40 characters")
    return ad


def parse_time(value):
    value = (value or "").strip()
    if not TIME.fullmatch(value):
        raise Refused(f"invalid time {value!r}: expected HH:MM (00:00-23:59)")
    return value


def parse_days(value):
    """['pzt', …] in week order from "pzt,car" (or a list); empty = every day."""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = (value or "").split(",")
    parts = [p.strip().lower().replace("ç", "c") for p in parts if p.strip()]
    if not parts:
        return list(DAYS)
    unknown = [p for p in parts if p not in DAYS]
    if unknown:
        raise Refused(f"unknown days: {', '.join(unknown)} (use {','.join(DAYS)})")
    return [d for d in DAYS if d in parts]


# --- storage ---

def folder(durum_dir):
    return os.path.join(durum_dir, FOLDER)


def path(durum_dir, ad):
    return os.path.join(folder(durum_dir), f"{check_name(ad)}.json")


def _valid(data, ad):
    if not isinstance(data, dict) or data.get("ad") != ad:
        return False
    if not isinstance(data.get("saat"), str) or not TIME.fullmatch(data["saat"]):
        return False
    if not isinstance(data.get("gunler"), list) or not data["gunler"] or \
            any(d not in DAYS for d in data["gunler"]):
        return False
    if data.get("durum") not in STATUS_TR or not isinstance(data.get("proje"), str):
        return False
    brief = data.get("brief")
    return isinstance(brief, dict) and isinstance(brief.get("hedef"), str) and bool(brief["hedef"].strip())


def load(durum_dir, ad):
    """The definition of a schedule, or None (missing, a link, unreadable, invalid, or written for another name)."""
    try:
        p = path(durum_dir, ad)
    except Refused:
        return None
    if os.path.islink(p) or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.loads(f.read(512 * 1024))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not _valid(data, ad):
        return None
    for key in ("kosular", "atlananlar", "bildirilen"):
        if not isinstance(data.get(key), list):
            data[key] = []
    data["kosular"] = [r for r in data["kosular"] if isinstance(r, dict) and isinstance(r.get("is"), str)
                       and isinstance(r.get("slot"), str)]
    return data


def _save(durum_dir, data):
    """Atomic write of a definition (temp file + os.replace)."""
    data["guncellendi"] = _stamp(datetime.now())
    kontrol._write_json(path(durum_dir, data["ad"]), data, overwrite=True)


def names(durum_dir):
    try:
        entries = sorted(os.listdir(folder(durum_dir)))
    except OSError:
        return []
    return [n[:-5] for n in entries if n.endswith(".json") and not n.startswith(".") and NAME.fullmatch(n[:-5])]


# --- time ---

def _at(day, defn):
    h, m = (int(x) for x in defn["saat"].split(":"))
    return datetime.combine(day, time(h, m))


def latest_slot(defn, now):
    """The latest slot at or before now on an allowed weekday, or None when it is before baslangic (the schedule was
    added or resumed after it)."""
    start = _parse(defn.get("baslangic"))
    for back in range(8):
        day = now.date() - timedelta(days=back)
        if DAYS[day.weekday()] not in defn["gunler"]:
            continue
        slot = _at(day, defn)
        if slot > now:
            continue
        return None if start and slot < start else slot
    return None


def next_slot(defn, after):
    """The first slot strictly after `after` (and not before baslangic)."""
    start = _parse(defn.get("baslangic"))
    for fwd in range(9):
        day = after.date() + timedelta(days=fwd)
        if DAYS[day.weekday()] not in defn["gunler"]:
            continue
        slot = _at(day, defn)
        if slot > after and (not start or slot >= start):
            return slot
    return None


def when_text(defn):
    """"her gün 09:00", "hafta içi her gün 09:00", "hafta sonu 09:00", "Pazartesi, Cuma 09:00"."""
    days = list(defn["gunler"])
    if days == list(DAYS):
        head = "her gün"
    elif days == list(DAYS[:5]):
        head = "hafta içi her gün"
    elif days == list(DAYS[5:]):
        head = "hafta sonu"
    else:
        head = ", ".join(DAY_TR[DAYS.index(d)] for d in days)
    return f"{head} {defn['saat']}"


def date_text(when):
    return f"{when.day} {MONTH_TR[when.month - 1]} {when.year} {DAY_TR[when.weekday()]} {when:%H:%M}"


def slot_text(slot):
    when = _parse(slot)
    return date_text(when) if when else str(slot)


def group_key(ad, slot):
    return f"{ad}-{slot:%Y%m%d-%H%M}"


def upcoming(defn, now):
    """The next run (datetime) of an active schedule, else None."""
    return next_slot(defn, now) if defn.get("durum") == ACTIVE else None


# --- commands (ofis.py zamanla …) ---

def create(cfg, durum_dir, now, ad, proje, baslik, brief, katman=None, model=None, effort=None, butce=None,
           saat=None, gunler=None, deneme=False, uzmanlik=None):
    """Validates like `ofis.py ekle` and writes a new definition (never overwrites; a name is never reused).
    The budget is fixed here (the tier's default when none is given). deneme: every run is an office self-test (the
    job's record `deneme: evet`). A kod schedule whose Kontrol always passes is refused (bin/uyarilar.py).
    uzmanlik: every run's explicit specialisation (Refused when unknown); without it each run is routed when it is
    added (bin/uzmanlik.py). Returns the definition."""
    check_name(ad)
    saat = parse_time(saat)
    days = parse_days(gunler)
    brief = {k: v for k, v in (brief or {}).items() if isinstance(v, str) and v.strip()}
    check = (brief.get("kontrol") or "").strip()
    if check and kontrol.forbidden_command(check):
        raise Refused("the Kontrol names a forbidden path (a forbidden project is outside the office)")
    title, brief, tier, _, _, budget = launch.validate_job(cfg, proje, baslik, brief, katman, model, effort, butce)
    refusal = uyarilar.kontrol_reddi(tier, check)
    if refusal:
        raise Refused(refusal)
    launch.check_options(model, effort, None)
    if uzmanlik not in (None, ""):
        launch.route(cfg, proje, title, brief, tier, uzmanlik)  # Refused for an unknown one
    data = {"ad": ad, "proje": proje, "baslik": title,
            "brief": {k: brief[k].strip() for k in BRIEF_KEYS if k in brief},
            "kontrol": check, "kontrol_ozet": jobs.kontrol_digest(check) if check else "",
            "katman": tier, "model": model or "", "effort": effort or "", "butce_usd": budget or "",
            "saat": saat, "gunler": days, "deneme": bool(deneme), "uzmanlik": uzmanlik or "", "durum": ACTIVE,
            "durdurma_nedeni": "",
            "olusturuldu": _stamp(now), "baslangic": _stamp(now), "sayim_baslangic": "",
            "son_slot": "", "acik_slot": "", "son_hata": "", "kosular": [], "atlananlar": [], "bildirilen": []}
    with jobs.locked():
        p = path(durum_dir, ad)
        if os.path.lexists(p):
            raise Refused(f"a schedule named {ad} exists (or existed: names are never reused); choose another name")
        kontrol._write_json(p, data, overwrite=False)
    return data


def _change(durum_dir, ad, allowed, fields_of):
    with jobs.locked():
        data = load(durum_dir, check_name(ad))
        if data is None:
            raise Refused(f"no such schedule: {ad}")
        if data["durum"] not in allowed:
            raise Refused(f"{ad} is '{data['durum']}', expected {' or '.join(allowed)}")
        data.update(fields_of(data))
        _save(durum_dir, data)
        return data


def pause(durum_dir, ad, now, reason=None):
    reason = reason if reason is not None else f"{sahip.in_()} isteğiyle duraklatıldı"
    return _change(durum_dir, ad, (ACTIVE,), lambda d: {"durum": PAUSED, "durdurma_nedeni": reason,
                                                         "durduruldu": _stamp(now)})


def resume(durum_dir, ad, now):
    """Active again: slots before now are not run, failures before now no longer count."""
    return _change(durum_dir, ad, (PAUSED,), lambda d: {"durum": ACTIVE, "durdurma_nedeni": "",
                                                        "baslangic": _stamp(now), "sayim_baslangic": f"{now:{SLOT}}",
                                                        "son_hata": ""})


def remove(durum_dir, ad, now):
    """Marks a schedule removed; the file and its history stay (nothing is deleted)."""
    return _change(durum_dir, ad, (ACTIVE, PAUSED), lambda d: {"durum": REMOVED, "kaldirildi": _stamp(now)})


def table(durum_dir, now):
    rows = []
    for ad in names(durum_dir):
        d = load(durum_dir, ad)
        if d is None:
            rows.append((ad, "", "", "", "okunamadı", ""))
            continue
        nxt = upcoming(d, now)
        last = d["kosular"][-1] if d["kosular"] else None
        rows.append((ad, d["proje"], when_text(d), f"{nxt:%Y-%m-%d %H:%M}" if nxt else "—",
                     STATUS_TR[d["durum"]], f"{jobs.stem(last['is'])} {RESULT_TR.get(last.get('sonuc'), '')}"
                     if last else ""))
    header = ("AD", "PROJE", "ZAMAN", "SONRAKİ", "DURUM", "SON KOŞU")
    widths = [max(len(r[i]) for r in rows + [header]) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in [header] + rows]
    if not rows:
        lines.append("(zamanlanmış iş yok)")
    return "\n".join(lines) + "\n"


def summaries(durum_dir, now):
    """For the page: the schedules that are not removed."""
    out = []
    for ad in names(durum_dir):
        d = load(durum_dir, ad)
        if d is None or d["durum"] == REMOVED:
            continue
        nxt = upcoming(d, now)
        last = d["kosular"][-1] if d["kosular"] else None
        out.append({"ad": ad, "proje": d["proje"], "baslik": d.get("baslik", ""), "zaman": when_text(d),
                    "sonraki": f"{nxt:{SLOT}}" if nxt else "", "duraklatildi": d["durum"] == PAUSED,
                    "neden": d.get("durdurma_nedeni", "") if d["durum"] == PAUSED else "",
                    "son_is": last["is"] if last else "", "son_sonuc": (last.get("sonuc") or "") if last else "",
                    # the newest runs first (at most PAGE_RUNS): the page's Zamanlanmış tab links each run's job note
                    "kosular": [{"slot": r["slot"], "is": r["is"], "sonuc": r.get("sonuc") or "",
                                 "son_is": r.get("son_is") or ""}
                                for r in sorted(d["kosular"], key=lambda r: r["slot"], reverse=True)[:PAGE_RUNS]]})
    return out


# --- the display note ---

def _cell(text):
    return " ".join(str(text or "").split()).replace("|", "/")


def note_text(defn, now):
    nxt = upcoming(defn, now)
    status = STATUS_TR[defn["durum"]]
    if defn["durum"] == PAUSED and defn.get("durdurma_nedeni"):
        status += f" ({defn['durdurma_nedeni']})"
    lines = ["---", f"tags: [ofis, zamanlanmis, {defn['proje']}]", f"proje: {defn['proje']}",
             f"zamanlama: {defn['ad']}", f"durum: {defn['durum']}", f"saat: \"{defn['saat']}\"",
             f"gunler: {','.join(defn['gunler'])}", f"olusturuldu: {defn.get('olusturuldu', '')}", "---", ""]
    body = [f"# Zamanlanmış iş — {defn.get('baslik') or defn['ad']}", "",
            "> Bu notu ofis sunucusu yazar; burada yapılan değişiklikler dikkate alınmaz. Değişiklik için CEO'ya "
            "söyle.", "",
            f"- **Proje:** {defn['proje']}",
            f"- **Ne zaman:** {when_text(defn)}",
            f"- **Durum:** {status}",
            f"- **Sonraki koşu:** {date_text(nxt) if nxt else '—'}",
            f"- **Katman:** {defn.get('katman', '')}" + (f" · kullanım sınırı ~${defn['butce_usd']} (API karşılığı)" if defn.get('butce_usd')
                                                          else ""),
            f"- **Kontrol:** `{defn['kontrol']}`" if defn.get("kontrol") else "- **Kontrol:** yok", ""]
    for key, heading in jobs.BRIEF:
        text = (defn["brief"].get(key) or "").strip()
        if text:
            body += [f"## {heading}", "", text, ""]
    body += ["## Son koşular", ""]
    rows = [(r["slot"], f"[[{jobs.stem(r['is'])}]]", RESULT_TR.get(r.get("sonuc") or "", r.get("sonuc", ""))
             + (f" → [[{jobs.stem(r['son_is'])}]]" if r.get("son_is") else "")) for r in defn["kosular"]]
    rows += [(s.get("slot", ""), "—", f"atlandı: {s.get('neden', '')}") for s in defn["atlananlar"]
             if isinstance(s, dict)]
    rows.sort(key=lambda r: r[0], reverse=True)
    if rows:
        body += ["| Zaman | İş | Sonuç |", "|---|---|---|"]
        body += [f"| {_cell(slot_text(s))} | {j} | {_cell(r)} |" for s, j, r in rows[:KEEP]]
    else:
        body.append("Henüz koşu yok.")
    body += ["", "## İlgili Sayfalar", "- [[OFIS/README]]", ""]
    return "\n".join(lines + body)


def write_note(vault, defn, now, cache=None):
    """Writes OFIS/Zamanlanmis/<ad>.md when its text changed. Returns True when written."""
    text = note_text(defn, now)
    target = os.path.join(vault, NOTES, f"{defn['ad']}.md")
    if cache is not None and cache.get(defn["ad"]) == text:
        return False
    try:
        with open(target, encoding="utf-8") as f:
            same = f.read(256 * 1024) == text
    except (OSError, UnicodeDecodeError):
        same = False
    if not same:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.islink(target):
            raise OSError(f"refusing to write through a link: {target}")
        jobs._write_atomic(target, text)
    if cache is not None:
        cache[defn["ad"]] = text
    return not same


# --- the server's pass ---

class Scheduler:
    def __init__(self, cfg, durum_dir, ceo, add, now=datetime.now, log=None):
        """add(project=, title=, brief=, now=, tier=, model=, effort=, budget=, group=, extra=[, uzmanlik=]) adds a
        queued job (ofis.add_job) and returns (job, warning); it raises launch.Refused."""
        self.cfg = cfg
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.add = add
        self.now = now
        self.log_file = log
        self.last_error = None
        self._notes = {}  # ad -> the display note text last written
        self._tried = {}  # ad -> (slot, time) of the last refused add (retries are throttled; memory only)

    @property
    def vault(self):
        return os.path.expanduser(self.cfg["vault_ofis"])

    def log(self, text):
        if self.log_file is None:
            return
        try:
            self.log_file.write(f"ofis scheduler: {text}\n")
            self.log_file.flush()
        except (OSError, ValueError):
            pass

    def run_once(self):
        """One pass over every schedule. Returns the names of the jobs added."""
        self.last_error = None
        added = []
        schedules = names(self.durum_dir)
        if schedules:
            try:
                self._check_vault()
            except OSError as e:  # e.g. macOS privacy refuses ~/Documents: never read a run as gone
                self.last_error = f"scheduler: the job folders cannot be read ({type(e).__name__}: {e}); pass skipped"
                self.log(self.last_error)
                return []
        for ad in schedules:
            try:
                job = self._one(ad)
            except (OSError, ValueError, jobs.JobError, launch.Refused) as e:
                self.last_error = f"schedule {ad}: {type(e).__name__}: {e}"
                self.log(self.last_error)
                continue
            if job:
                added.append(job)
        return added

    def _check_vault(self):
        """Raises OSError unless the vault and its job folders can be listed (a missing job folder is fine)."""
        os.listdir(self.vault)
        for f in jobs.FOLDERS:
            try:
                os.listdir(jobs.folder_path(self.vault, f))
            except FileNotFoundError:
                continue

    def _notify_once(self, defn, text, key):
        if key in defn["bildirilen"]:
            return False
        self.ceo.enqueue(SYSTEM_PREFIX + text, key)
        defn["bildirilen"] = (defn["bildirilen"] + [key])[-50:]
        return True

    def _one(self, ad):
        now = self.now()
        added = None
        with jobs.locked():
            defn = load(self.durum_dir, ad)
            if defn is None:
                return None
            if defn["durum"] != REMOVED:
                changed, open_runs = self._settle(defn, now)
                if defn["durum"] == ACTIVE:
                    ran, added = self._maybe_run(defn, now, open_runs)
                    changed = changed or ran
                if changed:
                    _save(self.durum_dir, defn)
        write_note(self.vault, defn, now, self._notes)
        return added

    # outcomes and the auto-pause

    def _follow(self, name):
        """(status, final job name) of a run's job, followed through escalations (records `yukseltildi`)."""
        seen = []
        while True:
            try:
                job = jobs.find(self.vault, name)
            except jobs.JobError:
                return "?", name  # e.g. a note in two folders: unknown, counted as open
            status = job.meta.get("durum", "") if job is not None else "yok"
            if status == "tikandi" and len(seen) < MAX_CHAIN:
                nxt = records.server_value(self.durum_dir, name, "yukseltildi")
                if nxt and nxt != name and nxt not in seen:
                    seen.append(name)
                    name = nxt
                    continue
            return status, name

    def _settle(self, defn, now):
        """Records the outcome of finished runs and pauses after MAX_FAILURES failures in a row. Returns (changed,
        open runs). A run that ended tikandi is checked again (it may go on with `devam` or be escalated)."""
        changed, open_runs = False, []
        for run in defn["kosular"]:
            if run.get("sonuc") not in ("", None, "tikandi", "yok"):  # yok: re-checked (a misread corrects itself)
                continue
            status, final = self._follow(run["is"])
            result = status if status in jobs.FINAL_STATUSES or status == "yok" else ""
            last = final if final != run["is"] else ""
            if result != (run.get("sonuc") or "") or last != (run.get("son_is") or ""):
                run["sonuc"], run["son_is"] = result, last
                changed = True
            if not result:
                open_runs.append(run)
        count, latest = self.failures(defn)
        if defn.get("ardisik_basarisiz") != count:
            defn["ardisik_basarisiz"] = count
            changed = True
        if count >= MAX_FAILURES and defn["durum"] == ACTIVE:
            defn.update({"durum": PAUSED, "durduruldu": _stamp(now),
                         "durdurma_nedeni": f"art arda {count} koşu başarısız oldu"})
            final = latest.get("son_is") or latest["is"]
            self.log(f"schedule {defn['ad']} paused after {count} failed runs")
            self._notify_once(defn, f"{defn['proje']} zamanlanmış işi duraklatıldı: {defn.get('baslik')} "
                                    f"({defn['ad']}). Art arda {count} koşu başarısız oldu (son koşu: "
                                    f"[[{jobs.stem(final)}]] {RESULT_TR.get(latest['sonuc'], latest['sonuc'])}). Sunucu "
                                    f"yeni koşu eklemeyecek. {sahip.e()} sor: sorun giderilip yeniden başlasın mı "
                                    f"(`ofis.py zamanla devam {defn['ad']}`), yoksa kaldırılsın mı (`ofis.py zamanla "
                                    f"sil {defn['ad']}`)?", f"zamanla-durdu-{defn['ad']}-{latest['slot']}")
            changed = True
        return changed, open_runs

    @staticmethod
    def failures(defn):
        """(number of the latest finished runs in a row that failed, the latest failed run). Open, iptal and missing
        runs neither count nor reset; bitti resets; runs before sayim_baslangic are not counted."""
        since = defn.get("sayim_baslangic") or ""
        count, latest = 0, None
        for run in sorted(defn["kosular"], key=lambda r: r["slot"], reverse=True):
            if run["slot"] < since:
                break
            result = run.get("sonuc") or ""
            if result in FAILED:
                count += 1
                latest = latest or run
            elif result == "bitti":
                break
        return count, latest

    # a due slot

    def _skip(self, defn, key, reason, log):
        defn["atlananlar"] = (defn["atlananlar"] + [{"slot": key, "neden": reason}])[-KEEP:]
        defn["son_slot"] = key
        defn["acik_slot"] = ""
        self.log(f"schedule {defn['ad']}: slot {key} skipped: {log}")

    def _maybe_run(self, defn, now, open_runs):
        """Returns (changed, added job name or None)."""
        stale = defn.get("acik_slot") or ""
        if stale:  # a crash during an add of an earlier slot: adopt its job before anything else
            when = _parse(stale)
            due = latest_slot(defn, now)
            if when is not None and (due is None or f"{due:{SLOT}}" != stale):
                group = group_key(defn["ad"], when)
                found = self._existing(group, deep=True)
                if found:
                    self._adopt(defn, found, group, now)
                    keep = defn.get("son_slot") or ""
                    self._record(defn, stale, found)
                    defn["son_slot"] = max(keep, stale)
                    self.log(f"schedule {defn['ad']}: slot {stale} already had {found} (adopted after a crash)")
                    return True, None  # the next pass sees it as a run (open or finished)
                defn["acik_slot"] = ""
                return True, None
        due = latest_slot(defn, now)
        if due is None:
            return False, None
        key = f"{due:{SLOT}}"
        if defn.get("son_slot") and key <= defn["son_slot"]:
            return False, None
        if now - due > CATCH_UP:
            self._skip(defn, key, "kaçırıldı (bilgisayar ya da sunucu kapalıydı; 24 saatten eski koşu yapılmaz)",
                       "missed more than 24 hours ago")
            return True, None
        group = group_key(defn["ad"], due)
        retrying = defn.get("son_hata_slot") == key and defn.get("acik_slot") != key  # a refused add made no job
        tried = self._tried.get(defn["ad"])
        if retrying and tried and tried[0] == key and now - tried[1] < RETRY:
            return False, None
        existing = None if retrying else self._existing(group, deep=defn.get("acik_slot") == key)
        if existing:
            self._adopt(defn, existing, group, now)
            self._record(defn, key, existing)
            self.log(f"schedule {defn['ad']}: slot {key} already had {existing} (adopted)")
            return True, None
        if open_runs:
            other = open_runs[-1]["is"]
            self._skip(defn, key, f"önceki koşu sürüyor ([[{jobs.stem(other)}]])",
                       f"the previous run {other} is still open")
            return True, None
        check = defn.get("kontrol") or ""
        if (jobs.kontrol_digest(check) if check else "") != (defn.get("kontrol_ozet") or ""):
            defn.update({"durum": PAUSED, "durduruldu": _stamp(now), "durdurma_nedeni": "Kontrol kaydı değişmiş"})
            self.log(f"schedule {defn['ad']}: the Kontrol does not match its digest; paused, nothing added")
            self._notify_once(defn, f"{defn['proje']} zamanlanmış işi duraklatıldı: {defn.get('baslik')} "
                                    f"({defn['ad']}). Kontrol kaydı onaylanan hâlinden farklı; iş çalıştırılmadı. "
                                    f"{sahip.e()} bildir; zamanlanmış iş yeniden eklenmeli.",
                              f"zamanla-kontrol-{defn['ad']}-{key}")
            return True, None
        defn["acik_slot"] = key
        _save(self.durum_dir, defn)  # the intent first: a crash after the add is adopted, never added twice
        brief = dict(defn["brief"])
        if check:
            brief["kontrol"] = check
        try:
            job, warning = self.add(project=defn["proje"], title=defn["baslik"], brief=brief, now=now,
                                    tier=defn.get("katman") or None, model=defn.get("model") or None,
                                    effort=defn.get("effort") or None, budget=defn.get("butce_usd") or None,
                                    group=group, extra={"zamanlama": defn["ad"],
                                                        **({"deneme": "evet"} if defn.get("deneme") else {})},
                                    **({"uzmanlik": defn["uzmanlik"]} if defn.get("uzmanlik") else {}))
        except launch.Refused as e:
            defn["acik_slot"] = ""
            error = str(e)
            defn["son_hata_slot"] = key
            self._tried[defn["ad"]] = (key, now)
            if defn.get("son_hata") != error:
                defn["son_hata"] = error
                self.log(f"schedule {defn['ad']}: slot {key} not added ({error}); retried every pass")
            digest = hashlib.sha256(error.encode()).hexdigest()[:8]
            self._notify_once(defn, f"{defn['proje']} zamanlanmış işi eklenemedi: {defn.get('baslik')} "
                                    f"({defn['ad']}), {slot_text(key)} koşusu. Neden: {error}. Sunucu yeniden "
                                    f"deneyecek; 24 saat içinde eklenemezse bu koşu atlanır. {sahip.e()} bildir.",
                              f"zamanla-hata-{defn['ad']}-{key}-{digest}")
            return True, None
        if warning:
            self.log(f"schedule {defn['ad']}: {job.name}: {warning}")
        self._record(defn, key, job.name)
        self.log(f"schedule {defn['ad']}: slot {key} added {job.name}")
        return True, job.name

    def _record(self, defn, key, name):
        defn["kosular"] = (defn["kosular"] + [{"slot": key, "is": name, "sonuc": "", "son_is": ""}])[-KEEP:]
        defn["son_slot"] = key
        defn["acik_slot"] = ""
        defn["son_hata"] = ""
        defn["son_hata_slot"] = ""

    def _existing(self, group, deep):
        """A job already added for this slot (its grup is the slot's key): a server record names it, or — deep, after a
        crash between the note and its record — a note does. A cancelled job (e.g. its Kontrol could not be stored)
        does not count."""
        candidates = []
        rec_dir = os.path.join(self.durum_dir, records.FOLDER)
        try:
            entries = sorted(os.listdir(rec_dir))
        except OSError:
            entries = []
        for n in entries:
            if not n.endswith(".json") or n.startswith("."):
                continue
            try:
                name = jobs.check_name(n[:-5])
            except jobs.JobError:
                continue
            if (records.load(self.durum_dir, name) or {}).get("grup") == group:
                candidates.append(name)
        if deep:
            candidates += [j.name for j in jobs.list_jobs(self.vault) if j.meta.get("grup") == group]
        for name in candidates:
            try:
                job = jobs.find(self.vault, name)
            except jobs.JobError:
                continue
            if job is not None and job.meta.get("durum") != "iptal":
                return job.name
        return None

    def _adopt(self, defn, name, group, now):
        """Completes a job added before a crash: its server record, trusted Kontrol and trusted brief, from the
        definition (never from the note)."""
        job = jobs.find(self.vault, name)
        if job is None:
            return
        if records.load(self.durum_dir, name) is None:
            tier, model, effort = launch.resolve_tier(self.cfg, defn.get("katman") or None,
                                                      defn.get("model") or None, defn.get("effort") or None)
            role = launch.route(self.cfg, defn["proje"], defn["baslik"], defn["brief"], tier,
                                defn.get("uzmanlik") or None)
            trusted = {"proje": defn["proje"], "katman": tier, "model": model or "", "effort": effort or "",
                       "butce_usd": defn.get("butce_usd") or "", "max_cagri": launch.default_max_calls(self.cfg, tier)
                       or "", "grup": group, "kontrol_ozet": defn.get("kontrol_ozet") or "",
                       "deneme": "evet" if defn.get("deneme") else "", "uzmanlik": role["uzmanlik"],
                       "uzmanlik_nedeni": role["neden"], "uzmanlik_kaynagi": role["kaynak"]}
            records.update(self.durum_dir, name, {**records.from_note(job), **trusted})
        if job.meta.get("durum") != "sirada":
            return
        if defn.get("kontrol") and kontrol.load(self.durum_dir, name) is None:
            kontrol.save(self.durum_dir, name, defn["kontrol"], now)
        if kontrol.load_brief(self.durum_dir, name) is None:
            brief = dict(defn["brief"], kontrol=defn.get("kontrol") or None)
            kontrol.save_brief(self.durum_dir, name, defn["baslik"], brief, group, now)
