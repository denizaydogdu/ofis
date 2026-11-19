"""The dispatcher (phase 3): starts queued jobs by itself, deterministically — cheap file checks, never a model call.

A `sirada` job starts by itself (the path of `ofis.py baslat`, see ofis.start_job) when
- every job in its `bagimli` is `bitti`,
- it is not held (`beklet: evet`; `ofis.py ekle --beklet`, released with `ofis.py serbest <is>`),
- the global running limit allows it: fewer than `max_running` (ofis.json, default 3) jobs are baslatiliyor, calisiyor
  or kontrolde,
- the per-project limit allows it: fewer than `max_running_per_project` (default 1) unfinished jobs (the running
  statuses plus karar-bekliyor / incelemede: their session and changes are still in the folder) work in the project's
  own folder. A job in a worktree neither counts nor is held back by this limit.
Oldest `olusturuldu` first (then the file name); a job that cannot start yet does not hold back a later job that can.
At most one job starts per pass (a launch takes seconds and runs in the post office thread); the next pass starts the
next one. `ofis.py baslat` starts a job at once (dependencies and hold ignored: the CEO decided), but it respects the
limits too; the check runs under the job lock right before the job becomes `baslatiliyor` (start_gate), so two starters
can never pass the same free slot.
A dependency that ended `tikandi`, `iptal` or `basarisiz` (or whose note is missing) blocks the job: it stays `sirada`
with `engel: <dependency> <status>` (note and server record) and the CEO gets one keyed notice; `engel` is cleared
when no dependency blocks any more (e.g. after `ofis.py bagimli <is> --kaldir <dep>`, or a dependency that went on
with `devam`). A failed auto-start (the launch failed, or a `kod` job without its trusted Kontrol) gives one notice.
Phase 3 review: a dependency that is `tikandi` because it was escalated (`yukseltildi` on its server record — never a
note's) is followed to its replacement instead of blocking. A job that looks blocked (or has an engel to clear) is read
again with its dependencies under the job lock before engel is written or the CEO told. Before the start path the
cheap limit checks run (global and per project), so a job that cannot start never reaches `git rev-parse`. A start
refused for another reason (missing folder, a kod job without its Kontrol, …) while the job stays `sirada` is recorded
on the server record (`baslatma_hatasi`, `baslatma_izi` = a fingerprint of the note, the record, the Kontrol file and
the project folder) and not tried again until that fingerprint changes. Every dispatcher notice key is kept on the
job's record (`bildirilen`) and checked first, so a trimmed CEO sent log never repeats a notice; a start refusal's key
names the reason (a new reason is told again).
`bagimli` and `beklet` are read from the server record when it has them (written at `ekle`), else from the note: the
note is display only, and a record written before phase 3 lacks them.
Approval backlog (onay birikişi, 2026-11-11): while `max_bekleyen_onay` (ofis.json, default 2) workflow approval cards
(Kararlar notes `tur: akis-onay`, `durum: bekliyor` — a card whose answer the owner sent stays pending until the CEO runs
`cevapla`) wait for the owner, the dispatcher starts no new `kod` work: no queued job of tier `kod` (a workflow's kod step
included) and no workflow's first step. Reading / research jobs of other tiers still start; an escalated job (it
replaces running work) is exempt; Kontrol runs, reviews, answers and `ofis.py baslat` (the CEO's explicit start) are never
affected. The CEO gets one notice when the limit is hit (keyed by the pending cards; the last key is kept in
durum/onay-birikti.json, so a restart never repeats it).
`ekle` refuses a job for a project that already has `max_queued_per_project` (default 5) queued jobs ("Sıradakiler
dolu"); an escalated job (bin/kontrol.py) is exempt — it replaces a finished one. The queued steps of one workflow
(phase 4, bin/akis.py) count as one entry.
"""
import hashlib
import json
import os
import sys
from datetime import datetime

import jobs
import launch
import model_durum
import records
import sahip
import dil  # noqa: E402 — the CEO notices follow ofis.json `dil` (default Turkish)

RUNNING = ("baslatiliyor", "calisiyor", "kontrolde")
OCCUPYING = RUNNING + ("karar-bekliyor", "incelemede")
BLOCKING = ("tikandi", "iptal", "basarisiz")
DEFAULTS = {"max_running": 3, "max_running_per_project": 1, "max_queued_per_project": 5}
DEFAULT_ONAY_SINIRI = 2  # ofis.json max_bekleyen_onay
ONAY_FILE = "onay-birikti.json"  # durum/: the key of the last approval-backlog notice
def durum_adi(status, cfg=None):
    """A dependency's status as a word, in the display language (the blocked-dependency notice)."""
    if status == "tikandi":
        return dil.t("takıldı", cfg)
    if status == "iptal":
        return dil.t("iptal edildi", cfg)
    if status == "basarisiz":
        return dil.t("başlatılamadı", cfg)
    if status == "yok":
        return dil.t("bulunamadı", cfg)
    return status
SYSTEM_PREFIX = "[Ofis · sistem]\n"
MAX_CHAIN = 10  # escalations followed for a dependency (the ladder is shorter; a loop is never followed)
BOOKKEEPING = ("baslatma_hatasi", "baslatma_izi", "bildirilen", "guncellendi")  # not part of a start's fingerprint


DEFAULT_KOTA_YEDEGI = {"haiku": "sonnet", "sonnet": "opus", "opus": "sonnet", "fable": "opus"}  # Owner decision 2026-11-13
KOTA_FILE = "kota-yedegi.json"  # durum/: the quota notices already sent (one per model and quota period)


def kota_yedegi(cfg):
    """{model family: its backup family} — ofis.json kota_yedegi over DEFAULT_KOTA_YEDEGI (only Claude families)."""
    out = dict(DEFAULT_KOTA_YEDEGI)
    raw = (cfg or {}).get("kota_yedegi")
    for fam, backup in (raw.items() if isinstance(raw, dict) else ()):
        if fam in out and backup in model_durum.CLAUDE and backup != fam:
            out[fam] = backup
    return out


_UNITS = {1: "de", 2: "de", 3: "te", 4: "te", 5: "te", 6: "da", 7: "de", 8: "de", 9: "da"}
_TENS = {0: "da", 1: "da", 2: "de", 3: "da", 4: "ta", 5: "de"}


def saat_eki(when):
    """"20:38'de", "15:00'te", "12:30'da": the clock time with its Turkish locative suffix (the minutes are read out,
    else the hour)."""
    n = when.minute or when.hour
    return f"{when:%H:%M}'{_UNITS[n % 10] if n % 10 else _TENS[n // 10 % 6] if n < 60 else 'da'}"


class LimitReached(launch.Refused):
    """A start was refused by a WIP limit; the job stays queued."""


def _limit(cfg, key):
    value = cfg.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DEFAULTS[key]


def limits(cfg):
    """(max_running, max_running_per_project, max_queued_per_project) from ofis.json, else the defaults."""
    return tuple(_limit(cfg, k) for k in ("max_running", "max_running_per_project", "max_queued_per_project"))


def _vault(cfg):
    return os.path.expanduser(cfg["vault_ofis"])


def dependencies(durum_dir, job):
    """The job names this job waits for (record, else note), '.md' added."""
    raw = records.get(durum_dir, job, "bagimli")
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                out.append(jobs.check_name(part))
            except jobs.JobError:
                out.append(part)  # an unusable name never resolves: the job is blocked, not started
    return out


def is_held(durum_dir, job):
    return records.get(durum_dir, job, "beklet") == "evet" or job.meta.get("beklet") == "evet"


def running_count(vault):
    return sum(1 for j in jobs.list_jobs(vault, (jobs.ACTIVE,)) if j.meta.get("durum") in RUNNING)


def in_project_folder(cfg, durum_dir, job):
    """True when the job works in its project's own folder (not in a worktree)."""
    rec = records.load(durum_dir, job.name) or {}
    cwd = rec.get("calisma_dizini") or job.meta.get("calisma_dizini") or ""
    try:
        root = launch.resolve_project(cfg, job.meta.get("proje"))
    except launch.Refused:
        return True
    return not cwd or os.path.realpath(cwd) == os.path.realpath(root)


def project_count(cfg, durum_dir, vault, project):
    return sum(1 for j in jobs.list_jobs(vault, (jobs.ACTIVE,))
               if j.meta.get("durum") in OCCUPYING and j.meta.get("proje") == project
               and in_project_folder(cfg, durum_dir, j))


def start_gate(cfg, durum_dir, worktree=False, resume=False):
    """A gate for launch.start_job: raises LimitReached (Turkish: the CEO reads it) when a WIP limit is full. Called
    under the job lock right before the job becomes `baslatiliyor`. resume=True: the same limits for `ofis.py devam`
    (a stopped job's session goes on in its folder); the job stays `tikandi` and the CEO tries again later."""
    def gate(job):
        vault = _vault(cfg)
        total, per_project, _ = limits(cfg)
        running = running_count(vault)
        if running >= total:
            if resume:
                raise LimitReached(f"eşzamanlı iş sınırı dolu ({running}/{total} çalışıyor); devam şimdi olmaz, iş "
                                   "takıldı olarak kalır; yer açılınca `ofis.py devam` yeniden dene")
            raise LimitReached(f"eşzamanlı iş sınırı dolu ({running}/{total} çalışıyor); iş sırada kalır, yer "
                               "açılınca dağıtıcı kendiliğinden başlatır")
        project = job.meta.get("proje")
        if not worktree:
            busy = project_count(cfg, durum_dir, vault, project)
            if busy >= per_project:
                if resume:
                    raise LimitReached(f"{project} projesinin klasöründe zaten {busy} iş var (proje başına sınır "
                                       f"{per_project}); devam şimdi olmaz, iş takıldı olarak kalır; o iş bitince "
                                       "`ofis.py devam` yeniden dene")
                raise LimitReached(f"{project} projesinin klasöründe zaten {busy} iş var (proje başına sınır "
                                   f"{per_project}); iş sırada kalır, o iş bitince dağıtıcı kendiliğinden başlatır "
                                   "(ya da --worktree ile ayrı çalışma kopyasında başlat)")
    return gate


def onay_siniri(cfg):
    value = (cfg or {}).get("max_bekleyen_onay")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else DEFAULT_ONAY_SINIRI


def bekleyen_onaylar(vault):
    """The names of the workflow approval cards waiting for the owner (Kararlar, `tur: akis-onay`, `durum: bekliyor`)."""
    folder = os.path.join(vault, "Kararlar")
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".md") and not n.startswith("."))
    except OSError:
        return []
    out = []
    for name in names:
        path = os.path.join(folder, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                _, meta, _ = jobs.parse(f.read(8 * 1024))
        except (OSError, UnicodeDecodeError):
            continue
        if meta.get("tur") == "akis-onay" and meta.get("durum") == "bekliyor":
            out.append(name)
    return out


def onay_birikti(cfg, vault):
    """{bekleyen, sinir, dolu, kartlar} of the approval backlog."""
    cards = bekleyen_onaylar(vault)
    limit = onay_siniri(cfg)
    return {"bekleyen": len(cards), "sinir": limit, "dolu": len(cards) >= limit, "kartlar": cards}


def onay_bekletir(durum_dir, job):
    """True when starting this queued job would start new kod work the approval backlog holds: a `kod` tier job (a
    workflow's kod step too) or a workflow's very first job (`akis_ilk` on its server record, bin/akis.py); never a plan
    re-round of a running workflow, never an escalated job (both replace running work)."""
    if records.get(durum_dir, job, "yukseltme_kaynagi"):
        return False
    rec = (records.load(durum_dir, job.name) or {}) if durum_dir else {}
    tier = rec.get("katman") or job.meta.get("katman") or ""
    if tier == launch.KOD_TIER:
        return True
    return bool(rec.get("akis")) and rec.get("akis_ilk") == "evet"


def queued(vault):
    """The `sirada` jobs, oldest olusturuldu first."""
    out = [j for j in jobs.list_jobs(vault, (jobs.QUEUED,)) if j.meta.get("durum") == "sirada"]
    out.sort(key=lambda j: (j.meta.get("olusturuldu") or "", j.name))
    return out


def queue_full(cfg, vault, project):
    """(count, limit) when the project's queue is full, else None. The queued steps of one workflow (bin/akis.py,
    `akis` on their notes) count as one entry: a workflow is one piece of work."""
    cap = limits(cfg)[2]
    entries = {j.meta.get("akis") or j.name for j in queued(vault) if j.meta.get("proje") == project}
    count = len(entries)
    return (count, cap) if count >= cap else None


def waiting_text(durum_dir, job):
    """Why a queued job waits, in a few words (for `ofis.py durum`), or ""."""
    parts = []
    if is_held(durum_dir, job):
        parts.append("beklet")
    engel = records.get(durum_dir, job, "engel")
    if engel:
        parts.append(f"engel: {engel}")
    elif dependencies(durum_dir, job):
        parts.append("bekliyor: " + ",".join(jobs.stem(d) for d in dependencies(durum_dir, job)))
    return "; ".join(parts)


def queue_info(cfg, vault, durum_dir):
    """{job name: {position (in its project's queue, 1-based), held, depends, blocked, onay_birikti (held by the
    approval backlog)}} for the page."""
    out, positions = {}, {}
    waiting = queued(vault)
    full = bool(waiting) and onay_birikti(cfg, vault)["dolu"]
    for job in waiting:
        project = job.meta.get("proje", "")
        positions[project] = positions.get(project, 0) + 1
        out[job.name] = {"position": positions[project], "held": is_held(durum_dir, job),
                         "depends": dependencies(durum_dir, job), "blocked": records.get(durum_dir, job, "engel"),
                         "onay_birikti": full and onay_bekletir(durum_dir, job),
                         "kota_bekliyor": records.server_value(durum_dir, job.name, "kota_bekliyor")}
    return out


class Dispatcher:
    def __init__(self, cfg, durum_dir, ceo, start, now=datetime.now, log=None, kota=None):
        """start(job name) starts a job (ofis.start_job); it raises launch.Refused (LimitReached for a limit).
        kota() -> {Claude family: its return time (aware datetime) or None} of the families on a concrete quota now
        (the server wires bin/state.py OfficeState.claude_kotalari; None: no quota is known)."""
        self.cfg = cfg
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.start = start
        self.now = now
        self.log_file = log or sys.stderr
        self.last_error = None
        self.kota = kota

    def log(self, text):
        try:
            self.log_file.write(f"ofis dispatcher: {text}\n")
            self.log_file.flush()
        except (OSError, ValueError):
            pass

    def _notify(self, text, key):
        self.ceo.enqueue(SYSTEM_PREFIX + text, key)

    @staticmethod
    def _what(job):
        return f"{job.meta.get('baslik') or jobs.stem(job.name)} ({jobs.stem(job.name)})"

    def _set_engel(self, job, text):
        """Writes engel on the record and the note when it changed. Returns True when it changed."""
        if records.get(self.durum_dir, job, "engel") == text and (job.meta.get("engel") or "") == text:
            return False
        vault = _vault(self.cfg)
        with jobs.locked(vault):
            try:
                records.update(self.durum_dir, job.name, {"engel": text}, create=False)
            except FileNotFoundError:
                pass
            try:
                jobs.update(vault, job.name, fields={"engel": text}, expect=("sirada",))
            except jobs.JobError:
                return False
        return True

    def _final(self, dep, by_name):
        """(name, status, Job) of a dependency, following an escalation: a `tikandi` job whose server record names the
        job opened one tier up for it (yukseltildi; never read from a note) stands for that job, and so on."""
        name, seen = dep, []
        while True:
            if name not in by_name:
                try:
                    by_name[name] = jobs.find(_vault(self.cfg), name)
                except jobs.JobError:
                    by_name[name] = None
            other = by_name[name]
            status = other.meta.get("durum") if other is not None else "yok"
            if status == "tikandi" and len(seen) < MAX_CHAIN:
                replacement = records.server_value(self.durum_dir, name, "yukseltildi")
                if replacement and replacement not in seen and replacement != name:
                    seen.append(name)
                    name = replacement
                    continue
            return name, status, other

    def _blocked(self, deps, by_name):
        """[(dependency, status, its Job)] of the dependencies that block the job (an escalated one is followed to
        its replacement), and whether all are bitti. Only the dependencies are read (cached in by_name), never every
        finished note."""
        blocked, done = [], True
        for dep in deps:
            name, status, other = self._final(dep, by_name)
            if status != "bitti":
                done = False
            if status in BLOCKING or status == "yok":
                blocked.append((name, status, other))
        return blocked, done

    def _notify_once(self, job, text, key):
        """One CEO notice per job and key: the job's server record keeps the keys sent (bildirilen), so a trimmed
        sent log of the CEO channel never repeats it. A job without a record relies on the channel alone."""
        if records.notice_sent(self.durum_dir, job.name, key):
            return
        self._notify(text, key)
        records.add_notice(self.durum_dir, job.name, key)

    def _tell_blocked(self, job, blocked):
        stem = jobs.stem(job.name)
        for dep, status, other in blocked:
            rounds = (other.meta.get("devam_sayisi") or "0") if other is not None else "0"
            key = f"engel-{stem}-{jobs.stem(dep)}-{status}-{rounds}"
            self._notify_once(job, dil.t(
                "{proje} işi bekliyor: {what}. Bağımlı olduğu {dep} işi {durum}; bu iş kendiliğinden başlamaz. "
                "{sahip_e} sor: bağımlılık kaldırılsın mı (`ofis.py bagimli {stem} --kaldir {dep}`), yoksa iş "
                "iptal mi edilsin (`ofis.py iptal {stem}`)?",
                self.cfg, proje=job.meta.get("proje", ""), what=self._what(job), dep=jobs.stem(dep),
                durum=durum_adi(status, self.cfg), sahip_e=sahip.e(), stem=stem), key)

    def _settle_engel(self, job):
        """Under the job lock: reads the job and its dependencies again (a dependency dropped or escalated since the
        pass read them counts), writes engel when it changed. Returns (blocked, done, job) or None when the job is no
        longer queued."""
        vault = _vault(self.cfg)
        with jobs.locked(vault):
            try:
                current = jobs.find(vault, job.name)
            except jobs.JobError:
                return None
            if current is None or current.meta.get("durum") != "sirada":
                return None
            blocked, done = self._blocked(dependencies(self.durum_dir, current), {})
            engel = "; ".join(f"{jobs.stem(d)} {s}" for d, s, _ in blocked)
            if self._set_engel(current, engel) and blocked:
                self.log(f"{job.name} is blocked: {engel}")
        return blocked, done, current

    def fingerprint(self, job):
        """A digest of what a start depends on: the note, the server record (without the dispatcher's own
        bookkeeping), whether the trusted Kontrol exists and whether the project folder resolves. A start refused for
        a reason other than a limit is not tried again until it changes."""
        h = hashlib.sha256()
        try:
            with open(job.path, "rb") as f:
                h.update(f.read(256 * 1024))
        except OSError:
            h.update(b"-")
        rec = {k: v for k, v in (records.load(self.durum_dir, job.name) or {}).items() if k not in BOOKKEEPING}
        h.update(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode())
        kontrol_file = os.path.join(self.durum_dir, "kontroller", f"{jobs.stem(job.name)}.json")
        h.update(b"k1" if os.path.isfile(kontrol_file) else b"k0")
        try:
            launch.resolve_project(self.cfg, job.meta.get("proje"))
            h.update(b"p1")
        except launch.Refused:
            h.update(b"p0")
        else:  # a folder the owner trusted since the refusal is tried again
            h.update({True: b"t1", False: b"t0", None: b"t?"}[launch.folder_trusted(
                launch.resolve_project(self.cfg, job.meta.get("proje")))])
        return h.hexdigest()

    def _back_off(self, job, error):
        """Records a refused start on the job's server record (created from the note for a job from before records)
        with the fingerprint the next passes compare against."""
        vault = _vault(self.cfg)
        with jobs.locked(vault):
            fields = {"baslatma_hatasi": error[:500]}
            if records.load(self.durum_dir, job.name) is None:
                fields = dict(records.from_note(job), **fields)
            records.update(self.durum_dir, job.name, fields)
            records.update(self.durum_dir, job.name, {"baslatma_izi": self.fingerprint(job)})

    def _start_refused(self, job, error):
        self.last_error = f"start of {job.name}: {error}"
        self.log(self.last_error)
        stem = jobs.stem(job.name)
        try:
            current = jobs.find(_vault(self.cfg), job.name)
        except jobs.JobError:
            current = None
        if str(error).startswith("launch unconfirmed"):
            text = dil.t("{proje} işinin başlatılması doğrulanamadı: {what}. claude zamanında yanıt vermedi; oturum "
                         "çalışıyor olabilir (`claude agents`). İşi yeniden başlatma; {sahip_e} bildir.",
                         self.cfg, proje=job.meta.get("proje", ""), what=self._what(job), sahip_e=sahip.e(self.cfg))
        elif str(error).startswith(launch.TRUST_REFUSAL):
            text = dil.t("{proje} işi sırada bekliyor: {what}. Claude bu projenin klasörüne henüz güvenmiyor "
                         "({neden}); iş başarısız sayılmadı. {sahip_e} bir `sor` kartıyla söyle: o klasörde bir kez "
                         "`claude` çalıştırıp güven sorusuna evet desin; iş ondan sonra kendiliğinden başlar.",
                         self.cfg, proje=job.meta.get("proje", ""), what=self._what(job),
                         neden=error.split("(", 1)[-1].split(")", 1)[0], sahip_e=sahip.e(self.cfg))
        else:
            text = dil.t("{proje} işi başlatılamadı: {what}. Dağıtıcı işi kendiliğinden başlatmayı denedi; neden: "
                         "{neden}. {sahip_e} bildir.",
                         self.cfg, proje=job.meta.get("proje", ""), what=self._what(job), neden=error,
                         sahip_e=sahip.e(self.cfg))
        key = f"baslatma-{stem}"
        if current is not None and current.meta.get("durum") == "sirada":
            # still queued (missing folder, kod without its Kontrol, …): back off until the job changes; the same
            # reason is told once, a new reason again
            self._back_off(current, str(error))
            key += "-" + hashlib.sha256(str(error).encode()).hexdigest()[:8]
        self._notify_once(job, text, key)

    def _tell_backlog(self, backlog):
        """One CEO notice when the approval backlog reaches its limit, keyed by the pending cards; the last key is kept
        in durum/onay-birikti.json (a restart or a trimmed sent log never repeats it)."""
        key = "onay-birikti-" + hashlib.sha256("|".join(backlog["kartlar"]).encode()).hexdigest()[:12]
        path = os.path.join(self.durum_dir, ONAY_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                if json.load(f).get("anahtar") == key:
                    return
        except (OSError, ValueError, AttributeError):
            pass
        self._notify(dil.t(
            "Onay bekleyen {n} kart var (sınır {sinir}, ofis.json max_bekleyen_onay): dağıtıcı yeni kod işlerini "
            "ve yeni akışları başlatmıyor; okuma ve araştırma işleri sürüyor. {sahip_e} tek satırla söyle: kartlara "
            "cevap verince kod işleri kendiliğinden başlar.",
            self.cfg, n=backlog["bekleyen"], sinir=backlog["sinir"], sahip_e=sahip.e(self.cfg)), key)
        try:
            os.makedirs(self.durum_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"anahtar": key, "kartlar": backlog["kartlar"]}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            self.log(f"approval backlog key not written: {e}")

    # --- quota fallback (Step 4, the owner's delegated decision 2026-11-13) ---

    def _quotas(self):
        """{family: return time} of the Claude families on a concrete quota: a known return time still ahead."""
        if self.kota is None:
            return {}
        try:
            raw = self.kota() or {}
        except Exception as e:  # the page's reader failing never stops a start
            self.log(f"quota status unreadable: {type(e).__name__}: {e}")
            return {}
        now = model_durum._aware(self.now())
        out = {}
        for fam, back in raw.items():
            if fam in model_durum.CLAUDE and isinstance(back, datetime):
                back = model_durum._aware(back)
                if back > now:
                    out[fam] = back
        return out

    def _set_quota_wait(self, job, text):
        if records.server_value(self.durum_dir, job.name, "kota_bekliyor") == text:
            return
        try:
            records.update(self.durum_dir, job.name, {"kota_bekliyor": text}, create=False)
        except (OSError, ValueError, FileNotFoundError, jobs.JobError) as e:
            self.log(f"quota wait of {job.name} not recorded: {e}")

    def _swap(self, job, fields, note):
        """Writes the model change only while the job is still queued: the note first (its expect check), then the
        record. Raises jobs.JobError when the job left the queue (nothing is written then)."""
        vault = _vault(self.cfg)
        with jobs.locked(vault):
            current = jobs.find(vault, job.name)
            if current is None or current.meta.get("durum") != "sirada":
                raise jobs.JobError(f"{job.name} is no longer queued")
            jobs.update(vault, job.name, fields=note, expect=("sirada",))
            records.update(self.durum_dir, job.name, fields, create=False)

    def _tell_quota(self, fam, backup, back):
        """One CEO notice per model and quota period (keyed by its return time; kept in durum/kota-yedegi.json)."""
        key = f"kota-yedegi-{fam}-{back.isoformat(timespec='minutes')}"
        path = os.path.join(self.durum_dir, KOTA_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                sent = json.load(f).get("anahtarlar") or []
        except (OSError, ValueError, AttributeError):
            sent = []
        if key in sent:
            return
        tz = model_durum.office_tz(model_durum.sahne(self.cfg)["saat_dilimi"])
        self._notify(dil.t(
            "{unvan} kotada; yeni işler {yedek} ile başlıyor, {saat} dönüyor. {sahip_e} tek satırla söyle. Çalışan "
            "işler başka modele geçmez; kotaya takılan bir iş kota bitince kendiliğinden sürmez (sayfada sessiz "
            "görünür).",
            self.cfg, unvan=model_durum.UNVAN[fam], yedek=model_durum.UNVAN[backup],
            saat=saat_eki(back.astimezone(tz)), sahip_e=sahip.e(self.cfg)), key)
        try:
            os.makedirs(self.durum_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"anahtarlar": (sent + [key])[-50:]}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            self.log(f"quota notice key not written: {e}")

    def _quota_choice(self, job, quotas):
        """(start?, revert fields or None): a job whose effective model is on quota gets its backup (record and note,
        model_kaynagi "kota"); both on quota → it waits with kota_bekliyor. revert puts the job back if the start is
        refused (it stays queued)."""
        rec = records.load(self.durum_dir, job.name) or {}
        if rec.get("adim_turu") == "onay" or (rec.get("adim_turu") == "kod-inceleme" and
                                              rec.get("inceleme_yurutucu") == "codex"):
            return True, None  # no Claude session starts (an approval card, the review panel)
        if rec.get("akis"):
            import akis  # imports this module
            try:
                state, index = akis._state_for(self.durum_dir, job.name)
                closed = akis.gate_reason(state, index, job.name)
            except Exception:  # the start path refuses it with its own reason
                closed = ""
            if closed:
                return True, None  # the workflow's gate is closed: the start raises Waiting, nothing to swap
        model = str(rec.get("model") or job.meta.get("model") or "")
        fam = model_durum.family(model)
        if fam not in quotas:
            if rec.get("kota_bekliyor"):
                self._set_quota_wait(job, "")
            return True, None
        backup = kota_yedegi(self.cfg).get(fam)
        if not backup or backup in quotas:
            tz = model_durum.office_tz(model_durum.sahne(self.cfg)["saat_dilimi"])
            back = min(quotas[fam], quotas[backup]) if backup in quotas else quotas[fam]
            self._set_quota_wait(job, f"{model_durum.UNVAN[fam]}" + (f" ve yedeği {model_durum.UNVAN[backup]}"
                                                                    if backup else "") +
                                 f" kotada; ilk dönüş {saat_eki(back.astimezone(tz))}")
            return False, None
        old_source = str(rec.get("model_kaynagi") or "")
        try:
            self._swap(job, {"model": backup, "kota_yedegi": {"asil": model, "yedek": backup},
                             "model_kaynagi": "kota", "kota_bekliyor": ""},
                       {"model": backup, "kota_yedegi": f"{model} → {backup}"})
        except (OSError, ValueError, FileNotFoundError, jobs.JobError) as e:
            self.log(f"quota backup of {job.name} not written: {e}")
            return False, None
        self.log(f"{job.name}: {model} is on quota; starting with {backup}")
        return True, ({"model": model, "kota_yedegi": None, "model_kaynagi": old_source}, {"model": model,
                                                                                           "kota_yedegi": None},
                      (fam, backup, quotas[fam]))

    def _still_queued(self, job):
        try:
            current = jobs.find(_vault(self.cfg), job.name)
        except jobs.JobError:
            return False
        return current is not None and current.meta.get("durum") == "sirada"

    def _revert(self, job, revert):
        try:
            self._swap(job, *revert[:2])
        except (OSError, ValueError, FileNotFoundError, jobs.JobError) as e:
            self.log(f"quota backup of {job.name} not reverted: {e}")

    def run_once(self):
        """One pass: engel bookkeeping for every queued job, then at most one start. Returns the started names."""
        self.last_error = None
        vault = _vault(self.cfg)
        backlog = onay_birikti(self.cfg, vault)
        if backlog["dolu"]:
            self._tell_backlog(backlog)
        waiting = queued(vault)
        if not waiting:
            return []
        quotas = None  # read once per pass, only when needed
        if any(records.server_value(self.durum_dir, j.name, "kota_bekliyor") for j in waiting):
            quotas = self._quotas()  # a stale "kota nedeniyle bekliyor" goes as soon as the quota no longer holds it
            for j in waiting:
                if records.server_value(self.durum_dir, j.name, "kota_bekliyor"):
                    fam = model_durum.family(records.server_value(self.durum_dir, j.name, "model") or
                                             j.meta.get("model") or "")
                    backup = kota_yedegi(self.cfg).get(fam)
                    if fam not in quotas or (backup and backup not in quotas):
                        self._set_quota_wait(j, "")
        by_name = {}
        total, per_project, _ = limits(self.cfg)
        busy = {}  # project -> unfinished jobs in its folder (this pass)
        started = []
        for job in waiting:
            blocked, done = self._blocked(dependencies(self.durum_dir, job), by_name)
            if blocked or records.get(self.durum_dir, job, "engel") or job.meta.get("engel"):
                settled = self._settle_engel(job)  # read again under the lock before engel or a notice
                if settled is None:
                    continue
                blocked, done, job = settled
                if blocked:
                    self._tell_blocked(job, blocked)
                    continue
            if started or not done or is_held(self.durum_dir, job):
                continue
            if backlog["dolu"] and onay_bekletir(self.durum_dir, job):
                continue  # approval cards pile up: no new kod work (reading / research jobs still start)
            if running_count(vault) >= total:
                continue  # cheap pre-checks; the gate in start() is the authoritative one
            project = job.meta.get("proje")
            if project not in busy:
                busy[project] = project_count(self.cfg, self.durum_dir, vault, project)
            if busy[project] >= per_project:
                continue
            if records.server_value(self.durum_dir, job.name, "baslatma_izi") == self.fingerprint(job):
                continue  # refused before and nothing changed since
            if quotas is None:
                quotas = self._quotas()
            go, revert = self._quota_choice(job, quotas)
            if not go:
                continue  # its model and the backup are both on quota: it waits (kota_bekliyor on the page)
            try:
                self.start(job.name)
            except LimitReached:
                if revert:
                    self._revert(job, revert)
                continue
            except launch.Refused as e:
                if revert and self._still_queued(job):
                    self._revert(job, revert)
                self._start_refused(job, str(e))
                continue
            if revert:  # the notice only once a job really started on the backup
                self._tell_quota(*revert[2])
            self.log(f"started {job.name}")
            started.append(job.name)
        return started
