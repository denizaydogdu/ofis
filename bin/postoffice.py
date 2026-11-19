"""The office server's post office: projects and the CEO never message each other directly.

Inbox (durum/gelen/*.json, written by `ofis.py bildir`), oldest first:
- a report is applied only when its id is one `bildir` writes, its sender (`oturum`) is the session of a job in
  Devam-Edenler and it was sent from that job's working folder (calisma_dizini, or a folder inside it). Anything
  else (unknown sender, finished job, foreign folder, malformed file, a job note found in two folders, a Kararlar
  name taken by another message) is moved to durum/gelen/reddedilen/ and logged — nothing else happens,
- bitti / tikandi: the text is appended to the job's Sonuç and the job gets that status (moves to Bitenler),
- soru: a pending Kararlar note is written (durum: bekliyor, kaynak_oturum, is) and the job becomes karar-bekliyor;
  with ofis.json mudur_karari on, a technical question goes to its manager first (bin/mudur.py yonlendir + the
  MudurWorker thread): its notice is then the worker's (the manager's answer, or "soruyor" when it falls back),
- then ONE notice ("[Ofis · sistem]" + a Turkish line + the project's text quoted with "> ") is queued for the CEO
  under the key gelen-<message id>, and only then the inbox file is deleted.
Project text written into the vault (Sonuç, ## Soru) is quoted with "> " on every line, so it can never open a
section of its own (e.g. a fake "## Cevap (Deniz)").
A transient error (anything that is not a rejection) keeps the file and holds back only the later files of the same
sender in that tick (their order matters); other senders go on. After MAX_ATTEMPTS failed ticks the file is
rejected, so one bad file can never block the inbox for good.
Idempotency: the message id is recorded in the job note (islenen_mesajlar) in the same atomic write as the change,
the Kararlar note name is derived from the message id, and the CEO channel queues a key at most once (also after
delivery, via its sent log). A crash at any step therefore never applies or notifies twice; the retry finishes it.

Outbox (durum/giden/*.json, written by `ofis.py cevapla`, name order = answer order): an answer is delivered only
while its job is running (ACTIVE_STATUSES); an answer for a finished or cancelled job goes to giden/reddedilen and
the session's queued answers are dropped, so a stopped job is never restarted. Each text goes to its session through
a project channel (stop+resume / queue, never a new session; cwd = the job's calisma_dizini) and every resume carries
the job's model, effort, permission mode, deny rules and report contract (launch.resume_flags). The session is found
by name + cwd in `claude agents --json` or by the job's kisa_id among the transcripts of that folder. The outbox file
is kept until the channel reports the message delivered; after MAX_ATTEMPTS failed attempts it goes to
giden/reddedilen. Errors are shown in status() and on the page.
Silent jobs: a `calisiyor` job whose session has been idle (or gone) for SILENT_SECONDS without a report is listed
in status()["silent"] (shown on the page as "sessiz"); checked at most every SILENT_CHECK_SECONDS, and only while
such a job exists.
Server record (phase 2 review): the session name, working folder, short id, tier, session options, limits and
recorded spending of a job are read from its server record durum/isler/<job>.json (bin/records.py), never from the
vault note, which is display only: inbox origin checks, outbox resumes, metering and limits all use
records.trusted(job). An active job from before the records gets one from its note, once (logged).
Kontrol (phase 2): a `bitti` report for a job whose trusted Kontrol exists (durum/kontroller, see bin/kontrol.py)
sets the job `kontrolde` instead of `bitti` and sends no notice yet; the KontrolWorker (its own thread) runs the
command and finishes the job. check_active() hands every `kontrolde` job to the worker, so a restart re-runs it.
A `kod` job whose trusted Kontrol is missing is never closed on the project's word: it becomes `tikandi`
("Güvenilir kontrol kaydı bulunamadı; iş kanıtsız kapatılmadı.") and the CEO is told.
Budget and call limit (phase 2): check_active() (every ACTIVE_CHECK_SECONDS) reads each active job's own session
transcript incrementally (bin/budget.py), records harcanan_usd / cagri on the note and the record when they changed
meaningfully, and stops a `calisiyor` / `baslatiliyor` / `kontrolde` job whose list-price cost is over butce_usd or
whose model calls are over max_cagri: under the job lock the job and its record are read again and the limit is
checked again (a budget raised meanwhile wins), then `claude stop` (only the job's own session id), the job becomes
`tikandi` with a Sonuç line, and the CEO gets one notice keyed by the job and the limit (a raised limit that is
exceeded again asks again). A failed stop of a busy/idle entry, or a session of the job's name listed under another
session id, leaves the job running with last_error set; it is retried on the next check. When the stop failed (a
leftover entry) or matched no listed session, the job's newest transcript decides (a fork runs under an id `claude
agents` does not list): written in the last WRITING_SECONDS, or an open turn written within channel.STALE_TURN_SECONDS,
means still running — the job stays as it is and is checked again. Only a stopped or clearly idle session is marked
`tikandi`; the Sonuç and the notice say what happened ("Oturum durduruldu." only after a successful stop; "Oturum
durdurulamadı, tekrar denenecek" — and the stop is retried at every check while the job stays that tikandi —, or
"Oturum çalışmıyordu"). A kontrol running meanwhile is discarded by
its attempt gate. A job whose launch was unconfirmed (kisa_id "-") gets its short id from `claude agents` (name +
working folder) on the record and the note, so it is metered too.
Scorecard (phase 2): process_karne() writes the karne row of every job marked `karne: bekliyor` (bin/karne.py), right
after a job finished in this process and otherwise every KARNE_CHECK_SECONDS (jobs finished by ofis.py bitir/iptal).
The final harcanan_usd / cagri go to the note and the record before the row. After `ofis.py devam` the job's row is
replaced in place at its next final status. Only cheap file checks run when there is nothing to do; no model is
ever called.
Workflows (phase 4, bin/akis.py): every `bitti` report of a workflow step is also kept in durum/kontroller/raporlar
(the trusted text the workflow engine stores as the step's output and reads the verdict from); the CEO notice of a
finished step says the workflow goes on by itself. dispatch() runs the workflow engine (akis.Engine.advance) before
and after the dispatcher pass; check_active() hands every `incelemede` Codex review to the CodexWorker (its own thread,
like the Kontrol worker), so a restart re-runs it.
Announcements (bin/duyuru.py): an outbox file with a `duyuru` id is one of the owner's announcements for one session; it is
delivered like an answer, and its outcome (iletildi, or iletilemedi when the job is no longer running or the file is
given up) is recorded per session on the trusted record durum/duyurular/<id>.json and in its vault note. Once no
session waits, process_duyurular() sends the CEO one notice ("N oturuma iletildi"). Every resume carries the
unexpired announcements in the contract (launch.resume_flags with durum_dir).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

import akis
import ayarlar
import arge
import budget
import channel
import claude_cli
import danisman
import duyuru
import dispatcher
import jobs
import karne
import kontrol
import launch
import model_secimi
import model_durum
import mudur
import ofis
import rapor
import records
import sahip
import sahipsiz
import dil  # noqa: E402 — the CEO notices follow ofis.json `dil` (default Turkish)
import transcript
import zamanla

MESSAGE_FILE_MAX = 64 * 1024
MAX_PER_TICK = 20
MAX_NOTICE_TEXT = 1500
MAX_ATTEMPTS = 20  # failed ticks before an inbox or outbox file is given up (moved to reddedilen)
SILENT_SECONDS = 120
SILENT_CHECK_SECONDS = 15
ACTIVE_CHECK_SECONDS = 10
ORPHAN_CHECK_SECONDS = 300  # orphan office sessions (bin/sahipsiz.py): notice only, never a stop
KARNE_CHECK_SECONDS = 30
DISPATCH_SECONDS = 5
FIRST_MINUTE_SECONDS = 120  # a started job with no tool use and no text after this long gets one CEO notice
WRITING_SECONDS = 30  # a transcript written this recently belongs to a session that may still run (limit stop)
# a session that may be spending (kontrolde: it may still run after its bitti; the kontrol result is then discarded);
# karar-bekliyor / incelemede wait for the owner
LIMITED_STATUSES = ("calisiyor", "baslatiliyor", "kontrolde")
NO_TRUSTED_KONTROL = "Güvenilir kontrol kaydı bulunamadı; iş kanıtsız kapatılmadı."
REPORT_TYPES = ("bitti", "tikandi", "soru")
SYSTEM_PREFIX = transcript.SYSTEM_PREFIX
QUOTA_RESUME_MARGIN = timedelta(minutes=2)  # after the usage limit's reset time
QUOTA_RESUME_MAX = 2  # automatic resumes per job; then the CEO asks the owner
QUOTA_RESUME_TEXT = "Kota döndü, kaldığın yerden devam et."


STOP_DONE, STOP_FAILED, STOP_NOT_RUNNING = "durduruldu", "durdurulamadi", "calismiyordu"
STOP_TEXT = {STOP_DONE: "Oturum durduruldu.",
             STOP_FAILED: "Oturum durdurulamadı, tekrar denenecek (claude stop hata verdi; oturum boşta görünüyor).",
             STOP_NOT_RUNNING: "Oturum çalışmıyordu (claude agents listesinde yok); durdurulacak bir şey yoktu."}


def _stop_notice_text(outcome, cfg=None):
    """STOP_TEXT in the display language (the CEO notice; the job note keeps the Turkish constant above)."""
    if outcome == STOP_DONE:
        return dil.t("Oturum durduruldu.", cfg)
    if outcome == STOP_FAILED:
        return dil.t("Oturum durdurulamadı, tekrar denenecek (claude stop hata verdi; oturum boşta görünüyor).", cfg)
    return dil.t("Oturum çalışmıyordu (claude agents listesinde yok); durdurulacak bir şey yoktu.", cfg)


class _Reject(Exception):
    pass


def _quote(text, limit=None):
    """Every line prefixed with "> " (optionally cut to `limit` characters first)."""
    text = text.strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return "\n".join("> " + line for line in text.splitlines())


def _message_files(folder):
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name)
    except OSError:
        return []
    return [e.path for e in entries
            if e.name.endswith(".json") and not e.name.startswith(".") and e.is_file(follow_symlinks=False)]


def _read_message(path):
    with open(path, "rb") as f:
        raw = f.read(MESSAGE_FILE_MAX + 1)
    if len(raw) > MESSAGE_FILE_MAX:
        raise _Reject("file too large")
    try:
        msg = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _Reject("not valid JSON") from None
    if not isinstance(msg, dict):
        raise _Reject("not a JSON object")
    return msg


def _sender(path):
    """The `oturum` of an inbox file, or None when it cannot be read (then nothing after it may overtake it)."""
    try:
        msg = _read_message(path)
    except _Reject:
        return ""  # malformed: it is rejected, nobody waits for it
    except Exception:
        return None
    session = msg.get("oturum")
    return session if isinstance(session, str) else ""


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _move_unique(path, folder):
    os.makedirs(folder, exist_ok=True)
    base = os.path.basename(path)
    target, n = os.path.join(folder, base), 2
    while os.path.lexists(target):
        target = os.path.join(folder, f"{base[:-5]}-{n}.json")
        n += 1
    os.replace(path, target)
    return target


class PostOffice:
    def __init__(self, cfg, cli, ceo, durum_dir, projects_dir, now=datetime.now, channel_kwargs=None, log=None,
                 clock=time.monotonic, wallclock=time.time, config_path=None):
        self.cfg = cfg
        self.cli = cli
        self.ceo = ceo
        self.vault = os.path.expanduser(cfg["vault_ofis"])
        self.durum_dir = durum_dir
        self.projects_dir = projects_dir
        self.now = now
        self.clock = clock
        self.wallclock = wallclock  # compared with transcript mtimes (the limit stop)
        self._pending_stops = {}  # job name -> (session ids, devam_sayisi): a stop that failed for an idle session
        self.channel_kwargs = channel_kwargs or {}
        self.log_file = log or sys.stderr
        self.inbox_dir = os.path.join(durum_dir, "gelen")
        self.rejected_dir = os.path.join(self.inbox_dir, "reddedilen")
        self.outbox_dir = os.path.join(durum_dir, "giden")
        self.outbox_rejected_dir = os.path.join(self.outbox_dir, "reddedilen")
        self.channels = {c.name: c for c in channel.load_project_channels(cli, durum_dir, projects_dir,
                                                                           **self.channel_kwargs)}
        for ch in self.channels.values():
            ch.log = self.log  # an unrecognised launch's output reaches the log (and the server's error record)
        if getattr(ceo, "log", None) is None:
            ceo.log = self.log
        self.errors = {}  # session name -> outbox error
        self.last_error = None  # an error of the latest tick (reset at the start of each tick)
        self.attempts = {}  # inbox file name -> failed ticks
        self.out_attempts = {}  # outbox file name -> failed attempts
        self.silent = {}  # job name -> {is, oturum, proje, seconds}
        self._idle_since = {}  # job name -> clock() when its session was first seen idle/gone
        self._waiting_since = {}  # job name -> (clock(), wall stamp) when its session was first seen "waiting"
        self._silent_checked_at = None
        self.orphans = sahipsiz.Sahipsiz(cfg, durum_dir, ceo, now=now, log=self.log)
        self._orphans_checked_at = None
        self.meter = budget.UsageMeter(projects_dir)  # used by this thread only
        self.kontrol = kontrol.KontrolWorker(cfg, ceo, durum_dir, now=now, log=self.log_file,
                                             on_finish=self._karne_soon)
        self._active_checked_at = None
        self._karne_checked_at = None
        self._karne_due = True
        self.dispatcher = dispatcher.Dispatcher(cfg, durum_dir, ceo, start=self._start_job, now=now, log=self.log_file)
        self.schedules = zamanla.Scheduler(cfg, durum_dir, ceo, add=self._add_job, now=now, log=self.log_file)
        self._dispatched_at = None
        self.akis = akis.Engine(cfg, durum_dir, ceo, now=now, log=self.log_file)
        # the review panel (bin/denetci.py); its hakem runs `claude -p` with the office's claude binary
        self.codex = akis.DenetciHeyeti(cfg, durum_dir, now=now, log=self.log_file, on_finish=self._karne_soon,
                                        claude_bin=getattr(cli, "claude_bin", None))
        # step 4 (bin/mudur.py): a technical question goes to its manager first; one `claude -p` call in its own thread
        self.mudur = mudur.MudurWorker(cfg, durum_dir, ceo, now=now, log=self.log_file,
                                       claude_bin=getattr(cli, "claude_bin", None))
        self.reports = rapor.Reporter(cfg, durum_dir, ceo, now=now, log=self.log)
        # phase 8: model proposals and pilot results after the Karne rows; the per-project tier overrides that
        # `ofis.py cevapla` writes into ofis.json are taken into this cfg (config_path: the file the server loaded)
        self.models = model_secimi.Advisor(cfg, durum_dir, ceo, now=now, log=self.log)
        # the advisor pilot (bin/danisman.py): its result card once every pilot job is settled
        self.danisman = danisman.Pilot(cfg, durum_dir, ceo, now=now, log=self.log)
        self.config_path = config_path
        self._duyuru_done = set()  # announcement ids whose CEO notice went out (not read again)
        # the live settings (bin/ayarlar.py): projects added, changed or removed in ofis.json (the Ayarlar page, a
        # hand edit, `ofis.py cevapla`'s tier overrides) reach this shared cfg without a restart
        self.ayarlar = ayarlar.Yenileyici(cfg, config_path, durum_dir, log=self.log)
        self.ayarlar.yenile()

    def log(self, text):
        try:
            self.log_file.write(f"ofis post office: {text}\n")
            self.log_file.flush()
        except (OSError, ValueError):
            pass

    def _trusted(self, job):
        """The job with its server record's session, folder, limits and spending (records.trusted)."""
        return records.trusted(self.durum_dir, job, self.log)

    def _record(self, job_name, fields):
        """Sets fields on an existing server record (a job without one is left alone)."""
        try:
            records.update(self.durum_dir, job_name, fields, create=False)
        except FileNotFoundError:
            pass

    # --- inbox ---

    def _reject(self, path, reason):
        _move_unique(path, self.rejected_dir)
        self.log(f"rejected {os.path.basename(path)}: {reason}")

    @staticmethod
    def _validate(msg, path):
        msg_id = msg.get("id")
        if not isinstance(msg_id, str) or not ofis.MESSAGE_ID.fullmatch(msg_id) or \
                os.path.basename(path) != f"{msg_id}.json":
            raise _Reject("invalid id (or it does not match the file name)")
        if not isinstance(msg.get("oturum"), str) or not channel.SESSION_NAME.fullmatch(msg["oturum"]):
            raise _Reject("invalid session name")
        if msg.get("tur") not in REPORT_TYPES:
            raise _Reject("invalid type")
        text = msg.get("metin")
        if not isinstance(text, str) or not text.strip() or len(text) > ofis.MAX_REPORT:
            raise _Reject("invalid text")
        where = msg.get("cwd_gercek")
        if not isinstance(where, str) or not os.path.isabs(where):
            raise _Reject("no working folder recorded (not sent with `ofis.py bildir`)")

    @staticmethod
    def _check_origin(job, msg):
        """The report must come from the job's own working folder (or a folder inside it)."""
        root = job.meta.get("calisma_dizini") or ""
        if not os.path.isabs(root):
            raise _Reject(f"job {job.name} has no calisma_dizini")
        if not _inside(msg["cwd_gercek"], root):
            raise _Reject(f"sent from {msg['cwd_gercek']}, outside the job's working folder {root}")

    def _asked_at(self, msg_id):
        try:
            return datetime.fromtimestamp(int(msg_id.split("-")[0]) / 1e9)
        except (ValueError, OverflowError, OSError):
            return self.now()

    def _write_question(self, job, msg):
        """The pending Kararlar note for a `soru`; its name comes from the message id (idempotent)."""
        project = job.meta.get("proje", "")
        asked = self._asked_at(msg["id"])
        name = f"{asked:%Y-%m-%d}-{project}-soru-{msg['id'][-8:]}.md"
        folder = os.path.join(self.vault, "Kararlar")
        path = os.path.join(folder, name)
        if os.path.lexists(path):
            with open(path, encoding="utf-8") as f:
                _, meta, _ = jobs.parse(f.read(64 * 1024))
            if meta.get("mesaj") != msg["id"]:
                raise _Reject(f"Kararlar/{name} exists for another message")
            return name
        text = msg["metin"].strip()
        title = " ".join(text.splitlines()[0].split())[:80]
        lines = [f"tags: [ofis, karar, {project}]"]
        for key, value in (("proje", project), ("durum", "bekliyor"), ("soruldu", f"{asked:%Y-%m-%dT%H:%M:%S}"),
                           ("kaynak_oturum", msg["oturum"]), ("is", job.name), ("mesaj", msg["id"])):
            jobs._set_line(lines, key, value)
        body = (f"# {project} — {title}\n\n## Soru\n{_quote(text)}\n\n"
                f"## İlgili Sayfalar\n- [[{jobs.stem(job.name)}]]\n- [[OFIS/README]]\n")
        os.makedirs(folder, exist_ok=True)
        with open(path, "x", encoding="utf-8") as f:
            f.write(jobs.render(lines, body))
        return name

    def _step_head(self, job):
        """"<project> akış adımı bitti (2/5 · plan-inceleme)" for a workflow step (server record), else None."""
        grup = records.server_value(self.durum_dir, job.name, "akis")
        state = akis.load_state(self.durum_dir, grup) if grup else None
        if state is None:
            return None
        kind = records.server_value(self.durum_dir, job.name, "adim_turu")
        step = records.server_value(self.durum_dir, job.name, "adim")
        return dil.t("{proje} akış adımı bitti ({adim}/{toplam} · {turu})", self.cfg,
                     proje=job.meta.get("proje", ""), adim=step, toplam=len(state["adimlar"]), turu=kind)

    def _notice(self, job, msg, decision):
        project = job.meta.get("proje", "")
        title = job.meta.get("baslik") or jobs.stem(job.name)
        what = f"{title} ({jobs.stem(job.name)})"
        v = dict(proje=project, what=what, sahip=sahip.ad(), sahip_e=sahip.e(), sahip_in=sahip.in_(),
                 nok=dil.t("Güvenilir kontrol kaydı bulunamadı; iş kanıtsız kapatılmadı.", self.cfg))
        step_head = self._step_head(job) if msg["tur"] == "bitti" and job.meta.get("durum") == "bitti" else None
        if step_head:
            head = dil.t("{step_head}: {what}. Akış kendiliğinden ilerler (sonraki adım, inceleme kararı ya da en "
                         "sonda {sahip_in} onay kartı); {sahip_e} ayrıca bildirmen gerekmez. Rapor:",
                         None, step_head=step_head, **v)
        elif msg["tur"] == "bitti" and job.meta.get("durum") == "tikandi":
            head = dil.t("{proje} işi takıldı: {what}. {nok} {sahip_e} bildir. Projenin raporu:", self.cfg, **v)
        elif msg["tur"] == "bitti":
            head = dil.t("{proje} işi bitti: {what}. Kontrol yok (yalnız projenin kendi raporu). Özet:", self.cfg, **v)
        elif msg["tur"] == "tikandi":
            head = dil.t("{proje} işi takıldı: {what}. Neden:", self.cfg, **v)
        else:
            return mudur.soru_bildirimi(project, decision, what, msg["metin"])
        return f"{SYSTEM_PREFIX}{head}\n{_quote(msg['metin'], MAX_NOTICE_TEXT)}"

    def _has_kontrol(self, job):
        return kontrol.load(self.durum_dir, job.name) is not None

    def _apply(self, job, msg):
        """Applies a report to its job once. Returns (job, decision note name or None).
        Holds the job lock throughout, so `ofis.py cevapla` sees a question and its status change together."""
        with jobs.locked(self.vault):
            # re-read the job under the lock: a Kontrol may have finished it since the caller loaded it
            job = self._trusted(jobs.settle(self.vault, job.name))  # the server record's fields, never the note's
            decision = None
            if msg["tur"] == "soru":
                decision = self._write_question(job, msg)
            if jobs.has_message(job, msg["id"]):
                # a retry of an already applied report: its Ar-Ge record (kept on the first pass) still owns the notice
                if self._arge_job(job, msg) and arge.kaydi_var(self.durum_dir, job.name):
                    self._arge_rid = arge.rapor_kimligi(job.name, msg["metin"])
                return job, decision
            if job.meta.get("durum") not in jobs.ACTIVE_STATUSES:
                raise _Reject(f"job {job.name} is '{job.meta.get('durum')}', not running")
            # The Ar-Ge report is kept here, under the job lock and only after the status check (2026-11-13): it is on
            # record before the new status is visible, and a report the job no longer accepts (a Kontrol finished
            # meanwhile) never replaces the pending one. Raises when it cannot be kept: the inbox file stays.
            self._arge_rid = self._arge(job, msg)
            stamp = f"{self.now():%Y-%m-%dT%H:%M:%S}"
            if msg["tur"] == "soru":
                job = jobs.update(self.vault, job.name, status="karar-bekliyor", add_decision=decision,
                                  add_message=msg["id"], expect=jobs.ACTIVE_STATUSES)
            elif msg["tur"] == "bitti" and self._has_kontrol(job):
                kontrol.save_report(self.durum_dir, job.name, msg["metin"])
                job = jobs.update(self.vault, job.name, status="kontrolde", append_result=_quote(msg["metin"]),
                                  add_message=msg["id"], expect=jobs.ACTIVE_STATUSES)
            elif msg["tur"] == "bitti" and records.server_value(self.durum_dir, job.name, "akis") and \
                    job.meta.get("katman") != launch.KOD_TIER:
                # a workflow step without a Kontrol: its report is its output (the engine reads it from here)
                kontrol.save_report(self.durum_dir, job.name, msg["metin"])
                with records.mirrored(self.durum_dir, job.name, {"kontrol_sonuc": "yok"}):
                    job = jobs.update(self.vault, job.name, status="bitti", append_result=_quote(msg["metin"]),
                                      fields={"bitis": stamp, "kontrol_sonuc": "yok"}, add_message=msg["id"],
                                      expect=jobs.ACTIVE_STATUSES)
            elif msg["tur"] == "bitti" and job.meta.get("katman") == launch.KOD_TIER:
                # a kod job is never closed without its proof: the trusted Kontrol is missing
                with records.mirrored(self.durum_dir, job.name, {"kontrol_sonuc": "kayit-yok"}):
                    job = jobs.update(self.vault, job.name, status="tikandi", add_message=msg["id"],
                                      fields={"bitis": stamp, "kontrol_sonuc": "kayit-yok"},
                                      append_result=f"{_quote(msg['metin'])}\n\n> {NO_TRUSTED_KONTROL}",
                                      expect=jobs.ACTIVE_STATUSES)
                self.log(f"{job.name}: bitti without a trusted kontrol record; marked tikandi")
            else:
                quoted = _quote(msg["metin"])
                result = quoted if msg["tur"] == "bitti" else f"Takıldı:\n{quoted}"
                fields = {"bitis": stamp}
                if msg["tur"] == "bitti":
                    fields["kontrol_sonuc"] = "yok"  # no trusted Kontrol: the project's word only
                    # kept server-side for the worker memory (bin/hafiza.py: its "Öğrendiklerim" lines stay unverified)
                    kontrol.save_report(self.durum_dir, job.name, msg["metin"])
                with records.mirrored(self.durum_dir, job.name, fields):
                    job = jobs.update(self.vault, job.name, status=msg["tur"], fields=fields,
                                      append_result=result, add_message=msg["id"], expect=jobs.ACTIVE_STATUSES)
            return job, decision

    def _handle_inbox(self, path):
        try:
            msg = _read_message(path)
            self._validate(msg, path)
            job = jobs.find_by_session(self.vault, msg["oturum"])
            if job is None:
                raise _Reject(f"no job has session {msg['oturum']}")
            job = self._trusted(job)
            if job.meta.get("oturum") != msg["oturum"]:
                raise _Reject(f"job {job.name} has session {job.meta.get('oturum')!r} on its server record")
            self._check_origin(job, msg)
            if not jobs.has_message(job, msg["id"]) and job.folder != jobs.ACTIVE:
                raise _Reject(f"job {job.name} is '{job.meta.get('durum')}', not running")
            self._arge_rid = None  # set by _apply (the Ar-Ge report is kept there, under the job lock)
            job, decision = self._apply(job, msg)
            arge_rid = self._arge_rid
        except (_Reject, jobs.JobError) as e:  # JobError: a note in two folders, a bad name, a status conflict
            self._reject(path, str(e))
            return
        if msg["tur"] == "bitti" and self._has_kontrol(job):
            if job.meta.get("durum") == "kontrolde":
                self.kontrol.submit(job.name)  # the worker tells the CEO once the Kontrol has run
        else:
            if msg["tur"] == "bitti" and job.meta.get("durum") == "bitti" and rapor.quiet_done(self.durum_dir,
                                                                                           job.name, self.vault):
                self.log(f"notice withheld for {job.name}: its group report will tell the CEO")
            elif arge_rid and job.meta.get("durum") == "bitti":
                # the Ar-Ge writer sends this report's one notice with the note's link (bin/arge.py yaz_ve_bildir)
                self.log(f"notice left to the Ar-Ge writer for {job.name}")
            elif msg["tur"] == "bitti" and job.meta.get("durum") == "bitti" and \
                    records.server_value(self.durum_dir, job.name, "gun_sonu"):
                # the end-of-day review job: bin/gunsonu.py writes its suggestions into the day's note and sends the
                # one notice ("Gün sonu önerileri eklendi …"); its report is kept by the branch above (save_report)
                self.log(f"notice left to the end-of-day writer for {job.name}")
            elif msg["tur"] == "bitti" and job.meta.get("durum") == "bitti" and \
                    records.server_value(self.durum_dir, job.name, "yakala"):
                # a Yakala research job: bin/yakala.py writes the OFIS/ArGe/Yakala-… note and sends the one notice
                # ("Yakalanan bağlantı incelendi …"); its report is kept by the branch above (save_report)
                self.log(f"notice left to the Yakala writer for {job.name}")
            elif msg["tur"] == "bitti" and job.meta.get("durum") == "bitti" and \
                    records.server_value(self.durum_dir, job.name, "talimat_denetimi"):
                # a prompt-audit job: bin/talimat_denetimi.py writes the OFIS/ArGe/TalimatDenetimi-… note, the card and
                # the one notice ("Talimat denetimi bitti …"); its report is kept by the branch above (save_report)
                self.log(f"notice left to the prompt-audit writer for {job.name}")
            elif msg["tur"] == "soru" and decision and \
                    mudur.yonlendir(self.cfg, self.durum_dir, job, msg, decision, self.now()):
                # a technical question: its manager answers first (the worker sends the one notice: the answer, or
                # the usual "soruyor" when the manager leaves it to the owner)
                self.mudur.submit(msg["id"])
                self.log(f"question {msg['id']} of {job.name} went to its manager")
            else:
                self.ceo.enqueue(self._notice(job, msg, decision), f"gelen-{msg['id']}")
            if job.meta.get("durum") in jobs.FINAL_STATUSES:
                self._karne_soon()
        os.unlink(path)
        self.log(f"{msg['tur']} from {msg['oturum']} applied to {job.name}")

    def _arge_job(self, job, msg):
        """A `bitti` from a job of the arge project (by its server record) — never the end-of-day review job, which
        also works in the arge workspace (bin/gunsonu.py writes its report into the day's GunSonu note), and never a
        Yakala research job (bin/yakala.py writes its own OFIS/ArGe/Yakala-… note), and never a prompt-audit job
        (bin/talimat_denetimi.py writes its own OFIS/ArGe/TalimatDenetimi-… note)."""
        return msg["tur"] == "bitti" and records.server_value(self.durum_dir, job.name, "proje") == arge.PROJE and \
            not records.server_value(self.durum_dir, job.name, "gun_sonu") and \
            not records.server_value(self.durum_dir, job.name, "yakala") and \
            not records.server_value(self.durum_dir, job.name, "talimat_denetimi")

    def _arge(self, job, msg):
        """The inbox path's only Ar-Ge step (bin/arge.py): a `bitti` from a job of the arge project (its server record)
        is kept as the job's pending report; the Ar-Ge thread's writer alone writes the note, the cards and the one
        notice once the job is bitti. Returns the report id, else None. When the report cannot be kept the error is
        logged once and raised: the inbox file stays for the post office's retry (never lost)."""
        if not self._arge_job(job, msg):
            return None
        try:
            return arge.bekleyen_kaydet(self.durum_dir, job.name, job.meta.get("baslik") or jobs.stem(job.name),
                                        msg["metin"], self.now)
        except Exception as e:
            self._arge_log(job, "kaydet", f"{job.name}: Ar-Ge raporu kaydedilemedi: {type(e).__name__}: {e}")
            raise

    def _arge_log(self, job, kind, line):
        """One line per job and kind in the server's error record (the inbox retries may repeat the failure)."""
        seen = self.__dict__.setdefault("_arge_logged", set())
        if (job.name, kind) not in seen:
            seen.add((job.name, kind))
            self.log(line)

    def process_inbox(self):
        held = set()  # senders with a transient error in this tick: their later files wait (order matters)
        hold_all = False  # a file whose sender is unknown failed: nothing may overtake it in this tick
        for path in _message_files(self.inbox_dir)[:MAX_PER_TICK]:
            sender = _sender(path)
            if hold_all or (sender and sender in held):
                continue
            base = os.path.basename(path)
            try:
                self._handle_inbox(path)
                self.attempts.pop(base, None)
            except Exception as e:  # keep the file; retried next tick, in order
                self.last_error = f"inbox {base}: {type(e).__name__}: {e}"
                self.log(self.last_error)
                n = self.attempts.get(base, 0) + 1
                if n >= MAX_ATTEMPTS:
                    self.attempts.pop(base, None)
                    try:
                        self._reject(path, f"gave up after {n} attempts ({type(e).__name__}: {e})")
                    except OSError as move_error:
                        self.log(f"cannot move {base} to reddedilen: {move_error}")
                    continue
                self.attempts[base] = n
                if sender is None:
                    hold_all = True
                else:
                    held.add(sender)

    # --- outbox ---

    def _job_of(self, session, job_name=None):
        """The job an answer belongs to: by its `is` field when that job has this session, else by session."""
        if isinstance(job_name, str) and job_name:
            try:
                job = jobs.find(self.vault, job_name)
            except jobs.JobError:
                job = None
            job = self._trusted(job)
            if job is not None and job.meta.get("oturum") == session:
                return job
        job = self._trusted(jobs.find_by_session(self.vault, session))
        return job if job is None or job.meta.get("oturum") == session else None

    def _session_moved(self, job_name, sid, ids):
        """A resume continued the job's session under a new id (a fork, see channel.py): the record gets every id and
        the new short id, the note the short id (display)."""
        with jobs.locked(self.vault):
            if records.add_session_ids(self.durum_dir, job_name, ids, current=sid) is None:
                return
            try:
                jobs.update(self.vault, job_name, fields={"kisa_id": sid[:8]})
            except jobs.JobError:
                pass
        self.log(f"session of {job_name} continues as {sid[:8]} (ids: {', '.join(i[:8] for i in ids)})")

    def _prepare(self, ch, job):
        """The job's options and fork hook on its channel; the channel follows the job's current session id."""
        ch.resume_args = launch.resume_flags(job, self.vault, durum_dir=self.durum_dir, now=self.now(), cfg=self.cfg)
        ch.log = self.log
        ch.on_session = lambda sid, ids, name=job.name: self._session_moved(name, sid, ids)
        known = ch.known_ids()
        current = self._current_id(job, known)
        # only an id the channel has not seen (found by _discover_sessions): never back to an older one
        if current and ch.session_id() and current not in known and ch.follow(current):
            self.log(f"channel {ch.name} follows {current[:8]}")
        return ch

    def _current_id(self, job, extra=()):
        """The full id of the job's current session (kisa_id among its recorded ids), or None."""
        short = job.meta.get("kisa_id") or ""
        if not transcript.valid_session_id(short) or len(short) < 8:
            return None
        ids = list(budget.listed_ids(job)) + list(extra)
        cwd = job.meta.get("calisma_dizini") or ""
        found = {i for i in ids if i.startswith(short)
                 and os.path.isfile(transcript.transcript_path(self.projects_dir, cwd, i))}
        return next(iter(found)) if len(found) == 1 else None

    def _channel(self, session, job):
        ch = self.channels.get(session)
        if job is None:
            raise LookupError(f"no job has session {session}")
        launch.resume_flags(job, self.vault, durum_dir=self.durum_dir)  # refuses a job without valid options before anything else
        if ch is not None and ch.session_id():
            return self._prepare(ch, job)
        cwd = job.meta.get("calisma_dizini") or ""
        if not cwd or not os.path.isabs(cwd) or not os.path.isdir(cwd) or state_forbidden(cwd):
            raise LookupError(f"job {job.name} has no usable calisma_dizini")
        if ch is None or not os.path.samefile(ch.root, cwd):
            ch = channel.project_channel(self.cli, session, cwd, self.durum_dir, self.projects_dir,
                                         **self.channel_kwargs)
        if not ch.adopt(job.meta.get("kisa_id", "")):
            raise LookupError(f"session {session} not found (not running, no transcript for its short id)")
        self.channels[session] = ch
        return self._prepare(ch, job)

    def _handle_outbox(self, path):
        """Returns True when delivered, False when still waiting without error, None when the attempt failed."""
        msg = _read_message(path)
        session, text, msg_id = msg.get("oturum"), msg.get("metin"), msg.get("id")
        if not isinstance(session, str) or not channel.SESSION_NAME.fullmatch(session) or \
                not isinstance(msg_id, str) or not msg_id or "\n" in msg_id or \
                not isinstance(text, str) or not text.strip() or text.lstrip().startswith("-"):
            raise _Reject("invalid outbox message")
        key = f"giden-{msg_id}"
        job = self._job_of(session, msg.get("is"))
        if msg.get("duyuru") and job is not None and job.meta.get("durum") in jobs.ACTIVE_STATUSES and \
                job.meta.get("durum") not in duyuru.DELIVER_STATUSES:
            # an announcement only for a session at work (never during a Kontrol, a question or a review: it would run
            # outside the limits); an unexpired one still reaches it through the contract at its next resume
            ch = self.channels.get(session)
            if ch is not None:
                ch.drop_pending({key})
            raise _Reject(f"{duyuru.NOT_WORKING} (iş '{job.meta.get('durum')}')")
        if job is not None and job.meta.get("durum") not in jobs.ACTIVE_STATUSES:
            ch = self.channels.get(session)
            if ch is not None:
                ch.drop_pending()
            self.errors.pop(session, None)
            raise _Reject(f"job {job.name} is '{job.meta.get('durum')}'; an answer never restarts a stopped job")
        try:
            ch = self._channel(session, job)
        except (LookupError, launch.Refused) as e:
            self.errors[session] = str(e)
            raise
        if not ch.was_sent(key):
            ch.enqueue(text, key)
            ch.drain_once()
        if ch.was_sent(key):
            os.unlink(path)
            self.errors.pop(session, None)
            self.log(f"answer delivered to {session}")
            self._duyuru_sonuc(msg, duyuru.ILETILDI)
            return True
        if ch.last_error:
            self.errors[session] = ch.last_error
            return None
        return False

    def _reject_outbox(self, path, reason):
        _move_unique(path, self.outbox_rejected_dir)
        self.last_error = f"outbox {os.path.basename(path)}: {reason}"
        self.log(self.last_error)

    def process_outbox(self):
        for path in _message_files(self.outbox_dir)[:MAX_PER_TICK]:
            base = os.path.basename(path)
            try:
                result = self._handle_outbox(path)
            except _Reject as e:
                self.out_attempts.pop(base, None)
                self._duyuru_sonuc(path, duyuru.ILETILEMEDI, str(e))
                self._reject_outbox(path, str(e))
                continue
            except Exception as e:  # keep the file, try again next tick
                self.last_error = f"outbox {base}: {e}"
                self.log(self.last_error)
                result = None
            if result is not None:
                self.out_attempts.pop(base, None)
                continue
            n = self.out_attempts.get(base, 0) + 1
            if n < MAX_ATTEMPTS:
                self.out_attempts[base] = n
                continue
            self.out_attempts.pop(base, None)
            session = None
            try:
                session = _read_message(path).get("oturum")
                ch = self.channels.get(session) if isinstance(session, str) else None
                msg_id = _read_message(path).get("id")
                if ch is not None and isinstance(msg_id, str):
                    ch.drop_pending({f"giden-{msg_id}"})
            except Exception:
                pass
            self._duyuru_sonuc(path, duyuru.ILETILEMEDI, f"{n} denemede iletilemedi")
            try:
                self._reject_outbox(path, f"not delivered after {n} attempts ({self.errors.get(session) or 'error'})")
            except OSError as e:
                self.log(f"cannot move {base} to giden/reddedilen: {e}")

    def _duyuru_sonuc(self, msg_or_path, state, reason=""):
        """Records an announcement's outcome for one session (msg: the outbox message or its file); never raises."""
        try:
            msg = msg_or_path if isinstance(msg_or_path, dict) else _read_message(msg_or_path)
            duyuru_id, session = msg.get("duyuru"), msg.get("oturum")
            if not isinstance(duyuru_id, str) or not duyuru.ID.fullmatch(duyuru_id) or not isinstance(session, str):
                return
            rec = duyuru.mark(self.durum_dir, duyuru_id, session, state, self.now(), reason)
            if rec is not None:
                duyuru.write_note(self.vault, rec, self.log)
        except Exception as e:  # the delivery itself already happened (or was refused); only the record failed
            self.log(f"announcement state not recorded: {type(e).__name__}: {e}")

    def process_duyurular(self):
        """One CEO notice per announcement once no session waits for it (bin/duyuru.py)."""
        try:
            for duyuru_id in duyuru.process(self.durum_dir, self.vault, self.ceo, self.now(), self._duyuru_done,
                                            self.log):
                self.log(f"announcement {duyuru_id}: CEO notified")
        except (OSError, ValueError, jobs.JobError) as e:
            self.last_error = f"duyuru: {type(e).__name__}: {e}"
            self.log(self.last_error)

    def clear_final_errors(self):
        """A delivery error or warning of a session whose job is final is dropped: an answer never reaches a
        finished job anyway, and a stale warning must not stay on the page forever (2026-11-13). Only the sessions
        that show one are looked up; an unknown job (vault unreadable) keeps its line."""
        names = set(self.errors) | {n for n, ch in self.channels.items() if ch.last_error}
        for name in sorted(names):
            job = self._trusted(jobs.find_by_session(self.vault, name))
            if job is None or job.meta.get("durum") not in jobs.FINAL_STATUSES:
                continue
            self.errors.pop(name, None)
            ch = self.channels.get(name)
            if ch is not None:
                ch.last_error = None

    def delivery_errors(self):
        """{session name: its current delivery error or warning} — what the page shows per session; sampled by the
        server's error record (bin/olaylar.py)."""
        errors = dict(self.errors)
        out = {name: errors.get(name) or ch.last_error for name, ch in list(self.channels.items())}
        out.update({name: e for name, e in errors.items() if name not in out})
        return {name: e for name, e in out.items() if e}

    def drain_channels(self):
        for name, ch in list(self.channels.items()):
            if not ch.pending():
                continue
            job = self._trusted(jobs.find_by_session(self.vault, name))
            if job is None:
                continue  # cannot tell (vault unreadable?): neither deliver nor drop
            if job.meta.get("durum") not in jobs.ACTIVE_STATUSES:
                dropped = ch.drop_pending()
                self.log(f"dropped {dropped} queued answer(s) for {name}: job {job.name} is '{job.meta.get('durum')}'")
                continue
            try:
                self._prepare(ch, job)
            except launch.Refused as e:
                self.errors[name] = str(e)
                continue
            ch.drain_once()

    # --- silent jobs ---

    def check_silent(self):
        """Lists the `calisiyor` jobs whose session has been idle (or gone) for SILENT_SECONDS: such a session ended
        its turn without a report (e.g. `bildir` failed)."""
        now = self.clock()
        running = [j for j in jobs.list_jobs(self.vault, (jobs.ACTIVE,))
                   if j.meta.get("durum") == "calisiyor" and channel.SESSION_NAME.fullmatch(j.meta.get("oturum") or "")]
        if not running:
            self._idle_since.clear()
            self._waiting_since.clear()
            self.silent = {}
            return
        try:
            agents = self.cli.agents()
        except claude_cli.ClaudeError:
            return  # unknown: keep the last result
        silent, seen = {}, set()
        for job in running:
            session = job.meta["oturum"]
            seen.add(job.name)
            rows = [a for a in channel._live(agents) if a.get("name") == session]
            rows.sort(key=lambda a: a.get("status") is None)  # a row with a status says more than a bare pid
            agent = rows[0] if rows else None
            status = agent.get("status") if agent is not None else None
            if status == "busy":
                self._idle_since.pop(job.name, None)
                self._waiting_since.pop(job.name, None)
                continue
            if status == "waiting":
                # A permission prompt nobody can answer in a background session: tell the CEO once per episode.
                self._waiting_since.setdefault(job.name, (now, self._episode(job, agent, now)))
            else:
                self._waiting_since.pop(job.name, None)
            since = self._idle_since.setdefault(job.name, now)
            if now - since >= SILENT_SECONDS and status == "idle" and job.name not in self._waiting_since:
                try:
                    self._quota_resume(job, agent)
                except (OSError, ValueError, jobs.JobError) as e:
                    self.log(f"quota resume of {job.name}: {type(e).__name__}: {e}")
            if now - since >= SILENT_SECONDS:
                waiting = job.name in self._waiting_since
                silent[job.name] = {"is": job.name, "oturum": session, "proje": job.meta.get("proje", ""),
                                    "seconds": int(now - since), "izin": waiting}
                if waiting and now - self._waiting_since[job.name][0] >= SILENT_SECONDS:
                    self._tell_waiting(job, int((now - self._waiting_since[job.name][0]) // 60))
        for name in [n for n in self._idle_since if n not in seen]:
            del self._idle_since[name]
        for name in [n for n in self._waiting_since if n not in seen]:
            del self._waiting_since[name]
        self.silent = silent

    # --- Step 5: a running job that stopped on a usage limit goes on once the limit has reset ---

    def _quota_resume(self, job, agent):
        """Only on concrete evidence: the idle session's own transcript ends with a usage-limit record (model_durum
        .session_quota_end) whose reset time passed QUOTA_RESUME_MARGIN ago, while the job's model is not on quota now.
        Once per quota event (its key on the record's kota_devam), at most QUOTA_RESUME_MAX times per job; then the CEO
        is asked once ("… üçüncü kez kotaya takıldı; devam etsin mi?") and `ofis.py devam` takes it on the owner's word. The
        message goes through the answer path (durum/giden: delivered only to an idle session, stop + resume with the
        job's options). A job over its budget or call limit is never resumed (the meter stops it)."""
        sid = agent.get("sessionId") if isinstance(agent.get("sessionId"), str) else ""
        trusted = self._trusted(job)
        cwd = trusted.meta.get("calisma_dizini") or ""
        if not transcript.valid_session_id(sid) or not os.path.isabs(cwd):
            return
        end = model_durum.session_quota_end(transcript.transcript_path(self.projects_dir, cwd, sid))
        kd_now = (records.load(self.durum_dir, job.name) or {}).get(records.QUOTA_RESUME) or {}
        if kd_now.get("soruldu") and (end is None or end["anahtar"] != kd_now["soruldu"]):
            # the session went on (or stopped otherwise) since the CEO was asked: the ask no longer opens `devam`
            records.update(self.durum_dir, job.name, {records.QUOTA_RESUME: dict(kd_now, soruldu="")}, create=False)
        if end is None or end["resets_at"] is None:
            return  # no usage-limit record (or no reset time): never on a guess
        now = model_durum._aware(self.now())
        if now < end["resets_at"] + QUOTA_RESUME_MARGIN:
            return
        fam = model_durum.family(trusted.meta.get("model") or "")
        live = self.dispatcher._quotas()
        if (fam and fam in live) or (not fam and live):
            return  # the model is still (or again) on quota
        rec = records.load(self.durum_dir, job.name) or {}
        kd = dict(rec.get(records.QUOTA_RESUME) or {})
        handled = list(kd.get("anahtarlar") or [])
        key = end["anahtar"]
        if key in handled:
            return
        spend, calls = budget.limits(self.cfg, trusted)
        try:
            spent, used = float(trusted.meta.get("harcanan_usd") or 0), int(trusted.meta.get("cagri") or 0)
        except ValueError:
            spent, used = 0.0, 0
        if (spend is not None and spent > spend) or (calls is not None and used > calls):
            return
        stem = jobs.stem(job.name)
        what = f"{job.meta.get('baslik') or stem} ({stem})"
        kd["anahtarlar"] = handled + [key]
        if int(kd.get("sayi") or 0) >= QUOTA_RESUME_MAX:
            kd["soruldu"] = key
            records.update(self.durum_dir, job.name, {records.QUOTA_RESUME: kd}, create=False)
            self.ceo.enqueue(SYSTEM_PREFIX + dil.t(
                "{proje} işi: {stem} üçüncü kez kotaya takıldı; devam etsin mi? {what}: kota döndükten sonra iki kez "
                "kendiliğinden devam ettirildi, yine kotada durdu. {sahip_e} sor; yalnız onun sözüyle "
                "`ofis.py devam {stem}`.",
                self.cfg, proje=job.meta.get("proje", ""), stem=stem, what=what, sahip_e=sahip.e(self.cfg)),
                f"kota-devam-sor-{stem}-{key[:40]}")
            self.log(f"{job.name} stopped on a quota again; the CEO asks the owner")
            return
        stamp = f"{self.now():%Y-%m-%dT%H:%M:%S}"
        msg_id = f"devam-{stem}-{time.time_ns():019d}"
        ofis.write_json_atomic(self.outbox_dir, f"{time.time_ns():019d}-{msg_id}.json",
                               {"id": msg_id, "oturum": trusted.meta.get("oturum") or job.meta.get("oturum"),
                                "metin": f"{ofis.DEVAM_HEAD} {stem}\n{QUOTA_RESUME_TEXT}", "is": job.name,
                                "zaman": stamp})
        kd["sayi"] = int(kd.get("sayi") or 0) + 1
        kd["zamanlar"] = list(kd.get("zamanlar") or []) + [stamp]
        records.update(self.durum_dir, job.name, {records.QUOTA_RESUME: kd}, create=False)
        self.ceo.enqueue(SYSTEM_PREFIX + dil.t(
            "{proje} işi: {stem} kota döndüğü için kaldığı yerden devam ediyor ({what}). {sahip_e} tek satırla söyle.",
            self.cfg, proje=job.meta.get("proje", ""), stem=stem, what=what, sahip_e=sahip.e(self.cfg)),
            f"kota-devam-{stem}-{key[:40]}")
        self.log(f"{job.name}: the quota is back; resume queued ({kd['sayi']}/{QUOTA_RESUME_MAX})")

    def _episode(self, job, agent, now):
        """The key part of one permission-prompt episode, stable across a server restart: the session id and the size
        of its transcript (a session waiting at a prompt writes nothing; it grows again once the prompt is answered).
        Without a readable transcript: the first-seen time (one repeat per restart then)."""
        sid = agent.get("sessionId") if isinstance(agent.get("sessionId"), str) else ""
        cwd = self._trusted(job).meta.get("calisma_dizini") or ""
        if transcript.valid_session_id(sid) and cwd:
            try:
                size = os.stat(transcript.transcript_path(self.projects_dir, cwd, sid)).st_size
                return f"{sid[:8]}-{size}"
            except OSError:
                pass
        return f"{self.now():%Y%m%d%H%M%S}-{int(now)}"

    def _tell_waiting(self, job, minutes):
        stem = jobs.stem(job.name)
        key = f"izin-{stem}-{self._waiting_since[job.name][1]}"
        self.ceo.enqueue(SYSTEM_PREFIX + dil.t(
            "{proje} işi izin onayı bekliyor: {baslik} ({stem}). Oturum {dk} dakikadır bir izin sorusunda duruyor; "
            "arka planda onu onaylayacak kimse yok, iş kendiliğinden ilerlemez. Ofis onu durdurmaz: {sahip_e} sade "
            "bir dille söyle ve ne yapılacağını sor (oturuma kendisi bakabilir ya da iş iptal edilip yeniden "
            "açılabilir); iptal ancak onun kararıyla.",
            self.cfg, proje=job.meta.get("proje", ""), baslik=job.meta.get("baslik") or stem, stem=stem,
            dk=max(2, minutes), sahip_e=sahip.e(self.cfg)), key)

    def _maybe_check_silent(self):
        now = self.clock()
        if self._silent_checked_at is not None and now - self._silent_checked_at < SILENT_CHECK_SECONDS:
            return
        self._silent_checked_at = now
        self.check_silent()

    def _maybe_check_orphans(self):
        """Every ORPHAN_CHECK_SECONDS: one CEO notice per `ofis-` session no job references (bin/sahipsiz.py), on the
        cached `claude agents` list. Never stops, kills or deletes a session."""
        now = self.clock()
        if self._orphans_checked_at is not None and now - self._orphans_checked_at < ORPHAN_CHECK_SECONDS:
            return
        self._orphans_checked_at = now
        try:
            self.orphans.check(self.cli.agents())
        except claude_cli.ClaudeError:
            return  # unknown: tried again on the next check
        except (OSError, ValueError, KeyError) as e:
            self.last_error = f"sahipsiz: {type(e).__name__}: {e}"
            self.log(self.last_error)

    # --- active jobs: Kontrol hand-off, spending, limits ---

    def check_active(self):
        self._retry_stops()
        for note in jobs.list_jobs(self.vault, (jobs.ACTIVE,)):
            status = note.meta.get("durum")
            if status not in jobs.ACTIVE_STATUSES:
                continue
            if status == "kontrolde":
                self.kontrol.submit(note.name)
            if status == "incelemede" and \
                    records.server_value(self.durum_dir, note.name, "inceleme_yurutucu") == "codex":
                self.codex.submit(note.name)  # a workflow's Codex review (bin/akis.py)
            try:
                job = self._discover_sessions(self._resolve_short_id(self._trusted(note)))
                if status in ("calisiyor", "baslatiliyor"):
                    self._check_first_minute(job)
                usage = self.meter.usage(job)
            except OSError as e:
                self.last_error = f"usage of {note.name}: {type(e).__name__}: {e}"
                continue
            if usage is None:
                continue
            if status in LIMITED_STATUSES and budget.exceeded(self.cfg, job, usage):
                self._stop_for_limit(job, usage)
                continue
            fields = budget.record_fields(job.meta, usage)
            if fields:
                try:
                    with jobs.locked(self.vault):
                        jobs.update(self.vault, job.name, fields=fields, expect=(status,))
                        self._record(job.name, fields)
                except jobs.JobError:
                    pass  # changed meanwhile: recorded on the next check

    def _resolve_short_id(self, job):
        """A job whose launch was unconfirmed has kisa_id "-": its session is found in `claude agents` by name and
        working folder (a unique match only) and its short id written to the record and the note."""
        short = job.meta.get("kisa_id") or ""
        session, cwd = job.meta.get("oturum") or "", job.meta.get("calisma_dizini") or ""
        if (transcript.valid_session_id(short) and len(short) >= 8) or not channel.SESSION_NAME.fullmatch(session) \
                or not os.path.isabs(cwd):
            return job
        try:
            agents = self.cli.agents()
        except claude_cli.ClaudeError:
            return job
        found = {a["sessionId"] for a in agents if a.get("name") == session and channel._same_dir(a.get("cwd"), cwd)
                 and transcript.valid_session_id(a.get("sessionId"))}
        if len(found) != 1:
            return job
        short = next(iter(found))[:8]
        with jobs.locked(self.vault):
            self._record(job.name, {"kisa_id": short})
            try:
                jobs.update(self.vault, job.name, fields={"kisa_id": short})
            except jobs.JobError:
                pass
        self.log(f"short id of {job.name} resolved from claude agents: {short}")
        return job._replace(meta=dict(job.meta, kisa_id=short))

    def _check_first_minute(self, job):
        """Once per job, FIRST_MINUTE_SECONDS after its start: no tool use and no text in any of its transcripts since
        the start -> one keyed CEO notice and `ilk_dakika: sessiz`; otherwise `ilk_dakika: tamam`. Never stops it."""
        if records.get(self.durum_dir, job, "ilk_dakika"):
            return
        try:
            started = datetime.fromisoformat(job.meta.get("baslangic") or "")
        except ValueError:
            return
        if (self.now() - started).total_seconds() < FIRST_MINUTE_SECONDS:
            return
        since = started.astimezone()
        moving = any(transcript.progress_since(path, since) for path in self.meter.files(job))
        mark = "tamam" if moving else "sessiz"
        with jobs.locked(self.vault):
            self._record(job.name, {"ilk_dakika": mark})
            try:
                jobs.update(self.vault, job.name, fields={"ilk_dakika": mark})
            except jobs.JobError:
                pass
        if moving:
            return
        stem = jobs.stem(job.name)
        minutes = int((self.now() - started).total_seconds() // 60)
        self.log(f"{job.name}: no progress {minutes} min after its start")
        self.ceo.enqueue(SYSTEM_PREFIX + dil.t(
            "{proje} işi ilerlemiyor: {baslik} ({stem}). Oturum {dk} dakika önce başladı ama henüz hiçbir araç "
            "kullanmadı ve bir şey yazmadı. Ofis onu durdurmaz: oturuma bak (`claude agents`), {sahip_e} sor; iptal "
            "ancak onun kararıyla.",
            self.cfg, proje=job.meta.get("proje", ""), baslik=job.meta.get("baslik") or stem, stem=stem,
            dk=minutes, sahip_e=sahip.e(self.cfg)), f"ilk-dakika-{stem}")

    def _discover_sessions(self, job):
        """Every transcript in the job's folder whose head names the job's session (written since the job started)
        belongs to the job: a resume may have continued it under a new id while the server did not follow (a restart,
        a resume outside the post office). New ids go to the record (oturum_kimlikleri); the newest one becomes the
        current short id (record and note). Returns the job with the updated values."""
        session, cwd = job.meta.get("oturum") or "", job.meta.get("calisma_dizini") or ""
        if not channel.SESSION_NAME.fullmatch(session) or not os.path.isabs(cwd):
            return job
        since = _epoch(job.meta.get("baslangic"))
        found = transcript.named_sessions(self.projects_dir, cwd, session,
                                          since=None if since is None else since - 60)
        if not found:
            return job
        known = budget.listed_ids(job)
        current = self._current_id(job, [sid for sid, _ in found])
        ids = known + [i for i in [current] + [sid for sid, _ in found] if i and i not in known]
        ids = list(dict.fromkeys(ids))
        newest = found[-1][0]  # the newest transcript of the session is where it goes on
        if ids == known and current == newest:
            return job
        new_ids = [i for i in ids if i not in known]
        with jobs.locked(self.vault):
            rec = records.add_session_ids(self.durum_dir, job.name, ids, current=newest)
            if rec is None:
                return job
            if newest[:8] != (job.meta.get("kisa_id") or ""):
                try:
                    jobs.update(self.vault, job.name, fields={"kisa_id": newest[:8]})
                except jobs.JobError:
                    pass
        if new_ids:
            self.log(f"sessions of {job.name}: {', '.join(i[:8] for i in records.session_ids(rec))} "
                     f"(current {newest[:8]})")
        ch = self.channels.get(session)
        if ch is not None and ch.session_id():
            ch.follow(newest)
        return job._replace(meta=dict(job.meta, kisa_id=newest[:8],
                                      oturum_kimlikleri=",".join(records.session_ids(rec))))

    def _limit_notice(self, job, kind, usage, outcome=STOP_DONE):
        spend, calls = budget.limits(self.cfg, job)
        stem = jobs.stem(job.name)
        what = f"{job.meta.get('baslik') or stem} ({stem})"
        dil_kodu = dil.kod()
        if kind == "butce":
            tok = (budget.token_text_en(usage.tokens) if dil_kodu == "en" else budget.token_text(usage.tokens)) \
                if budget.token_text(usage.tokens) and usage.tokens else ""
            reason = dil.t("Kullanım sınırı aşıldı: API karşılığı ~${harcanan} / ~${sinir}; {token}" if tok
                           else "Kullanım sınırı aşıldı: API karşılığı ~${harcanan} / ~${sinir}",
                           self.cfg, harcanan=budget.usd(usage.cost), sinir=budget.usd(spend), token=tok)
            raise_it = f"`ofis.py butce {stem} <usd>`"
        else:
            reason = dil.t("Çağrı sınırı aşıldı: {kullanilan} / {sinir} model çağrısı ({harcama})" if usage.tokens
                           else "Çağrı sınırı aşıldı: {kullanilan} / {sinir} model çağrısı",
                           None, kullanilan=usage.calls, sinir=calls,
                           harcama=budget.spend_text(usage.cost, usage.tokens, dil_kodu))
            raise_it = f"`ofis.py butce {stem} --cagri <N>`"
        return (SYSTEM_PREFIX + dil.t("{proje} işi durduruldu: {what}. {reason}. {stop} İş takıldı olarak işaretlendi. "
                                      "{sahip_e} sor: daha yüksek kullanım sınırıyla devam edilsin mi? Evet derse önce "
                                      "{raise_it}, sonra `ofis.py devam {stem}`.",
                                      self.cfg, proje=job.meta.get("proje", ""), what=what, reason=reason,
                                      stop=_stop_notice_text(outcome, self.cfg), sahip_e=sahip.e(), raise_it=raise_it,
                                      stem=stem))

    def _stop_for_limit(self, job, usage):
        """Under the job lock: reads the job and its record again and re-checks the limit (a budget raised meanwhile
        wins), stops the job's own session (when listed), marks the job tikandi; then asks the CEO once (keyed)."""
        with jobs.locked(self.vault):
            try:
                note = jobs.find(self.vault, job.name)
            except jobs.JobError as e:
                self.last_error = f"limit of {job.name}: {e}"
                return
            current = self._trusted(note)
            status = current.meta.get("durum") if current else None
            over = budget.exceeded(self.cfg, current, usage) if status in LIMITED_STATUSES else None
            if not over:
                return
            kind, line, key = over
            session = current.meta.get("oturum")
            try:
                agents = self.cli.agents(fresh=True)
            except claude_cli.ClaudeError as e:
                self.last_error = f"limit of {job.name}: {e}"
                return
            listed = [a for a in agents if a.get("name") == session]
            own = set(usage.session_ids) | {usage.session_id}  # a forked session stays listed under an older id
            stop_error, stopped_ids, failed_ids = None, [], []
            for agent in listed:
                if agent.get("sessionId") in own:
                    try:
                        self.cli.stop(agent["sessionId"][:8])
                        stopped_ids.append(agent["sessionId"])
                    except claude_cli.ClaudeError as e:
                        self.last_error = f"limit of {job.name}: {e}"
                        self.log(self.last_error)
                        if agent.get("status") in ("busy", "idle", "waiting"):
                            return  # still running (also at a permission prompt): retried on the next check
                        stop_error = self.last_error  # a leftover entry (status None) of a forked session
                        failed_ids.append(agent["sessionId"])
            foreign = sorted(str(a.get("sessionId"))[:8] for a in listed if a.get("sessionId") not in own)
            if foreign:
                self.last_error = (f"limit of {job.name}: a session named {session} is listed under another session id "
                                   f"({', '.join(foreign)}); the job is not marked stopped, checked again next time")
                self.log(self.last_error)
                return
            if stop_error or not stopped_ids:
                # the stop failed or matched nothing: a fork goes on under a new id that `claude agents` does not list,
                # so the job's newest transcript decides; a session still writing is never marked stopped
                quiet = self._writing(current)
                if quiet is not None:
                    self.last_error = (f"limit of {job.name}: the session is still running (its transcript was written "
                                       f"{quiet:.0f} s ago) and `claude stop` "
                                       f"{'failed' if stop_error else 'matched no listed session'}; the job is not "
                                       "marked stopped, checked again next time")
                    self.log(self.last_error)
                    return
            outcome = STOP_FAILED if stop_error else STOP_DONE if stopped_ids else STOP_NOT_RUNNING
            fields = budget.record_fields(current.meta, usage, force=True) or {}
            try:
                stopped = jobs.update(self.vault, job.name, status="tikandi", append_result=f"{line}\n> {STOP_TEXT[outcome]}",
                                      expect=(status,),
                                      fields={"bitis": f"{self.now():%Y-%m-%dT%H:%M:%S}", "durdurma_nedeni": kind,
                                              **fields})
            except jobs.JobError as e:
                self.log(f"limit of {job.name}: {e}")
                return
            if fields:
                self._record(job.name, fields)
        ch = self.channels.get(session)
        if ch is not None:
            ch.drop_pending()
        if stop_error:
            self.last_error = stop_error
            self._pending_stops[stopped.name] = (failed_ids, stopped.meta.get("devam_sayisi") or "")
        self.log(f"{stopped.name} is tikandi: {line[2:]}")
        self.ceo.enqueue(self._limit_notice(current, kind, usage, outcome), key)
        self._karne_soon()
        self.log(f"stopped {session}" if outcome == STOP_DONE else f"{session}: {STOP_TEXT[outcome]}")

    def _writing(self, job):
        """Seconds since the job's newest transcript was written when its session may still be running (written in
        the last WRITING_SECONDS, or an open turn written within channel.STALE_TURN_SECONDS), else None."""
        newest, newest_main = None, None
        mains = {os.path.join(self.meter.session_ids(job)[2] or "", f"{sid}.jsonl")
                 for sid in self.meter.session_ids(job)[1]}
        for path in self.meter.files(job):
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
            if path in mains and (newest_main is None or mtime > newest_main[0]):
                newest_main = (mtime, path)
        if newest is None:
            return None
        quiet = max(0.0, self.wallclock() - newest)
        if quiet < WRITING_SECONDS:
            return quiet
        if newest_main is not None and transcript.turn_open(newest_main[1]):
            quiet_main = max(0.0, self.wallclock() - newest_main[0])
            if quiet_main < channel.STALE_TURN_SECONDS:
                return quiet_main
        return None

    def _retry_stops(self):
        """Tries again the `claude stop` that failed for an idle session of a job stopped over its limit, while the
        job is still that `tikandi` (not gone on with `devam`) and the session is still listed. Kept in memory: after
        a restart an idle leftover entry is not stopped again (it does not run)."""
        if not self._pending_stops:
            return
        try:
            agents = self.cli.agents(fresh=True)
        except claude_cli.ClaudeError:
            return
        for name, (ids, rounds) in list(self._pending_stops.items()):
            try:
                job = jobs.find(self.vault, name)
            except jobs.JobError:
                job = None
            if job is None or job.meta.get("durum") != "tikandi" or (job.meta.get("devam_sayisi") or "") != rounds:
                del self._pending_stops[name]
                continue
            left = [a["sessionId"] for a in agents if a.get("sessionId") in ids]
            if not left:
                del self._pending_stops[name]
                continue
            for sid in left:
                try:
                    self.cli.stop(sid[:8])
                    self.log(f"stopped the session {sid[:8]} of {name} (retry)")
                except claude_cli.ClaudeError as e:
                    self.last_error = f"stop of {name} (retry): {e}"

    def check_mudur(self):
        """Hands queued manager questions to the worker; an earlier process's unfinished call falls back to the owner."""
        self.mudur.scan()

    def _maybe_check_active(self):
        now = self.clock()
        if self._active_checked_at is not None and now - self._active_checked_at < ACTIVE_CHECK_SECONDS:
            return
        self._active_checked_at = now
        try:
            self.check_mudur()
        except Exception as e:  # noqa: BLE001 — the records stay; tried again on the next check
            self.last_error = f"mudur: {type(e).__name__}: {e}"
            self.log(self.last_error)
        self.check_active()

    # --- dispatcher ---

    def _start_job(self, name):
        return ofis.start_job(self.cfg, name, self.durum_dir, claude_bin=self.cli.claude_bin, now=self.now())

    def _add_job(self, project, title, brief, now, tier=None, model=None, effort=None, budget=None, group=None,
                 extra=None, uzmanlik=None):
        try:
            return ofis.add_job(self.cfg, self.durum_dir, project, title, brief, now, tier=tier, model=model,
                                effort=effort, budget=budget, group=group, extra=extra, uzmanlik=uzmanlik)
        except ofis.Refused as e:  # e.g. "Sıradakiler dolu": the scheduler handles launch.Refused
            raise launch.Refused(str(e)) from None

    def dispatch(self):
        """One dispatcher pass now (see bin/dispatcher.py), with the workflow engine before it (finished steps,
        verdicts, new rounds) and after it (an approval card just written), and the scheduler (phase 6,
        bin/zamanla.py) right before it, so a job added for a due slot can start in the same pass. Returns the
        started job names."""
        self._dispatched_at = self.clock()
        self.akis.advance()
        try:
            self.schedules.run_once()  # catches its own errors per schedule (last_error)
        except Exception as e:  # never skip the dispatcher pass because of a schedule
            self.schedules.last_error = f"scheduler: {type(e).__name__}: {e}"
            self.log(self.schedules.last_error)
        try:
            started = self.dispatcher.run_once()
        except (OSError, jobs.JobError) as e:
            self.last_error = f"dispatcher: {type(e).__name__}: {e}"
            self.log(self.last_error)
            started = []
        self.akis.advance()
        return started

    def _maybe_dispatch(self):
        now = self.clock()
        if self._dispatched_at is not None and now - self._dispatched_at < DISPATCH_SECONDS:
            return
        self.dispatch()

    # --- scorecard ---

    def _karne_soon(self):
        self._karne_due = True

    def process_karne(self):
        """The scorecard rows of finished jobs, then the group reports (bin/rapor.py: a group is reported only once
        every job's row — its final spending — is written)."""
        self._karne_due = False
        try:
            done = karne.process_pending(self.vault, self._final_usage, now=self.now,
                                         on_final=self._record,
                                         record_of=lambda job: records.load(self.durum_dir, job.name))
        except (OSError, jobs.JobError) as e:
            self._karne_due = True
            self.last_error = f"karne: {type(e).__name__}: {e}"
            self.log(self.last_error)
            return []
        try:
            self.reports.check()
        except (OSError, jobs.JobError, ValueError) as e:
            self.last_error = f"rapor: {type(e).__name__}: {e}"
            self.log(self.last_error)
        try:
            self.models.check()
        except (OSError, jobs.JobError, ValueError) as e:
            self.last_error = f"model seçimi: {type(e).__name__}: {e}"
            self.log(self.last_error)
        try:
            self.danisman.check()
        except (OSError, jobs.JobError, ValueError) as e:
            self.last_error = f"danışman pilotu: {type(e).__name__}: {e}"
            self.log(self.last_error)
        return done

    def _final_usage(self, job):
        """A finished job's usage for its Karne row; a job of the advisor pilot, or one whose transcript shows advisor
        calls, also gets the advisor counts on its server record (bin/danisman.py measures arm B from them)."""
        usage = self.meter.usage(self._trusted(job))
        if usage is None:
            return None
        rec = records.load(self.durum_dir, job.name)
        if rec is not None and (rec.get("danisman_pilotu") or rec.get("danisman") or usage.danisman_cagri):
            records.update(self.durum_dir, job.name, budget.advisor_fields(usage), create=False)
        return usage

    def _maybe_process_karne(self):
        now = self.clock()
        if not self._karne_due and self._karne_checked_at is not None and \
                now - self._karne_checked_at < KARNE_CHECK_SECONDS:
            return
        self._karne_checked_at = now
        self.process_karne()

    # --- loop ---

    def tick(self):
        self.last_error = None
        self.ayarlar.yenile()
        self.process_inbox()
        self.process_outbox()
        self.drain_channels()
        self.clear_final_errors()
        self.process_duyurular()
        self._maybe_check_silent()
        self._maybe_check_orphans()
        self._maybe_check_active()
        self._maybe_process_karne()
        self._maybe_dispatch()
        if self.ceo.pending():
            self.ceo.drain_once()

    def run(self, stop_event, interval=3.0):
        while not stop_event.wait(interval):
            try:
                self.tick()
            except Exception as e:  # keep the thread alive; the error is visible in state
                self.last_error = f"post office: {type(e).__name__}: {e}"

    def status(self):
        """A snapshot for the page. Runs on the HTTP threads while the post office thread changes its tables, so it
        works on copies only."""
        def count(folder):
            return len(_message_files(folder))
        channels = list(self.channels.items())
        errors = dict(self.errors)
        silent = list(dict(self.silent).values())
        last_error = self.last_error
        sessions = {name: {"queue": ch.pending(), "error": errors.get(name) or ch.last_error} for name, ch in channels}
        for name, error in errors.items():
            sessions.setdefault(name, {"queue": 0, "error": error})
        current = [e for e in (self.kontrol.last_error, self.codex.last_error, self.akis.last_error,
                               self.schedules.last_error, self.dispatcher.last_error, last_error, *errors.values())
                   if e]
        return {"inbox": count(self.inbox_dir), "outbox": count(self.outbox_dir), "rejected": count(self.rejected_dir),
                "rejected_outbox": count(self.outbox_rejected_dir), "sessions": sessions,
                "last_error": current[-1] if current else None,
                "silent": sorted(silent, key=lambda s: s["is"]), "kontrol": self.kontrol.status(),
                "codex": self.codex.status()}


def _epoch(value):
    """A note time (local, ISO without zone) as epoch seconds, or None."""
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def state_forbidden(path):
    return launch.is_forbidden_path(path) or launch.is_forbidden_path(os.path.realpath(path))
