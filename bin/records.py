"""The server-owned record of a job: durum/isler/<job>.json.

The job note lives in the vault, which a project session could edit (the deny rules cover its tools, not every shell
route). Everything the server enforces or acts on therefore comes from this record, never from the note: the limits
(butce_usd, max_cagri), the session (oturum, kisa_id), the working folder (calisma_dizini), the tier and the session
options (katman, model, effort, izin_modu, proje), the spending recorded so far (harcanan_usd, cagri) and the sha256 of
the trusted Kontrol command (kontrol_ozet). on_harcama_usd = spending outside the session's transcript (the review
panel's Claude calls — hakem, security reviewer — before its step fell back to a Claude review): budget.UsageMeter adds
it to the transcript's cost, so it is never overwritten. The note carries the same values for reading only.

Writers (all under the job lock, temp file + os.replace): `ofis.py ekle` / launch.create_job (created), launch.start_job
(session and folder), `ofis.py butce` (limits), the post office (short id, spending). trusted() overlays the record on a
loaded note; a running (or stopped) job from before the record existed gets one, created once from its note and
logged (migration). Project sessions are denied Edit/Write in this repository (and in the vault).
"""
import contextlib
import json
import os
import tempfile
from datetime import datetime

import jobs
import transcript

FOLDER = "isler"
TRUSTED = ("proje", "katman", "model", "effort", "izin_modu", "butce_usd", "max_cagri", "oturum", "kisa_id",
           "calisma_dizini", "harcanan_usd", "cagri", "oturum_kimlikleri", "harcanan_token", "on_harcama_usd",
           "mudur_usd", "mudur_token")
# Step 4 (bin/mudur.py): the managers' calls that answered (or tried to answer) this job's technical questions — their
# summed cost and tokens, added by the manager worker only; budget.UsageMeter counts them like on_harcama_usd. Never
# taken from a note (from_note leaves them out).
MUDUR = ("mudur_usd", "mudur_token")
# Phase 3 (dispatcher, escalation): read from the record when the record HAS the key, else from the note — a record
# written before phase 3 lacks them, and emptying a queued job's bagimli would start it too early.
DISPATCH = ("bagimli", "beklet", "engel", "yukseltme_kaynagi", "yukseltme_sayisi", "ilk_dakika", "grup")
# Phase 3 review: server-only fields, never read from a note. yukseltildi = the job opened one tier up for this one;
# baslatma_hatasi / baslatma_izi = the dispatcher's last refused start and the fingerprint of the job it was refused
# for (back-off until the job changes); bildirilen = the dispatcher notice keys already sent for this job.
SERVER_ONLY = ("yukseltildi", "baslatma_hatasi", "baslatma_izi", "bildirilen")
# Phase 4 (bin/akis.py): a workflow step's identity and review state, written only by the server, never read from a
# note. akis = the workflow id (its grup), adim = the step number in the template, adim_turu = the step kind;
# taban_commit = HEAD when the job's session started (the kod-inceleme reviews the diff since the kod step's);
# inceleme_yurutucu = codex, or "claude (codex yok: <reason>)" after the fallback; inceleme_turu = how many review
# rounds sent findings back to this kod job; akis_ilk = "evet" on the workflow's very first job (the approval backlog
# holds only that one; bin/dispatcher.py onay_bekletir).
WORKFLOW = ("akis", "adim", "adim_turu", "taban_commit", "inceleme_yurutucu", "inceleme_turu", "akis_ilk")
# Phase 8 (bin/model_secimi.py): where the job's model came from (model_kaynagi: elle | pilot | proje | katman) and the
# pilot it belongs to; written by launch.create_job only, never read from a note (a session could forge a pilot mark).
MODEL_CHOICE = ("model_kaynagi", "pilot")
# Step 4 (quota fallback, bin/dispatcher.py): kota_yedegi = {asil, yedek} when the dispatcher started the job with the
# backup model because its own was on a concrete quota (model_kaynagi then "kota"); kota_bekliyor = why a queued job
# waits (its model and the backup both on quota), "" otherwise.
QUOTA = ("kota_yedegi", "kota_bekliyor", "kota_devam")
QUOTA_PAIR = "kota_yedegi"
# Step 5 (bin/postoffice.py quota resume): kota_devam = {sayi: automatic resumes, zamanlar: their times, anahtarlar: the
# quota events already handled, soruldu: the event the CEO was asked about ("" when none), elle: devam rounds on
# the owner's word}
QUOTA_RESUME = "kota_devam"
# Phase 8 review: the Kontrol attempt and result as the server wrote them (kontrol.py, akis.py, the post office). A
# project session can edit its own note, so the attempt number and the Karne evidence come from here; a job from
# before this has no such key and falls back to its note (records.get).
KONTROL = ("kontrol_deneme", "kontrol_sonuc")
# Living office (bin/model_durum.py): when the codex process ran for this kod-inceleme job (its success or its
# fallback after a run, local time; never for a refusal before codex started), codex_kota = "evet" only on codex's own
# usage-limit error (non-zero exit and a limit line in its last output lines: model_durum.codex_limit), codex_donus =
# its parsed "try again at" time (ISO, office zone). The page's model status reads Codex's state only from these.
# codex_sonuc (review panel, bin/denetci.py) = "codex" when codex itself gave a verdict, else "codex yok: <reason>": the
# panel may approve a job whose Codex run failed, so the job's inceleme_yurutucu ("codex") no longer tells Codex's own
# outcome; model_durum reads codex_sonuc first.
CODEX = ("codex_zamani", "codex_kota", "codex_donus", "codex_sonuc")
# Risk-based review (bin/risk.py): the kod-inceleme job's risk level (dusuk | normal | yuksek) and its reasons ("; "
# joined), written by the review panel before it runs; server-only, never read from a note.
RISK = ("risk", "risk_nedenleri")
# The folder's state when the job's session started (launch.start_job, next to taban_commit): taban_kirli = the paths
# that were already modified or untracked (`git status --porcelain -z`), taban_kirli_durum = "tam" when the list is
# complete, else "eksik" (too many paths, or git failed). The approval card's "Nasıl geri alınır" leaves them out.
# taban_git_ozet = gitsafe.state_digest() then: the repository-local git state that can hide a change (filter / diff
# drivers, .git/info/attributes, .git/info/exclude); the review compares it (bin/gitsafe.py tricks()).
BASE_STATE = ("taban_kirli", "taban_kirli_durum", "taban_git_ozet")
DIRTY = "taban_kirli"  # a list of paths
# Self-test jobs (owner decision 2026-11-12, B3 audit): deneme = "evet" on a job the office ran to test itself (`ofis.py ekle
# --deneme`, `akis --deneme`, a schedule with deneme, or the one-time `ofis.py deneme-isaretle`); "" for a real job. The
# Karne row shows it and the quality numbers, model selection and group-report totals leave such rows out. Written by
# launch.create_job (always, so the key exists) and deneme-isaretle; never read from a note (a session could hide its
# own failure by marking itself).
TRIAL = ("deneme",)
# Specialisation (plan "Sonraki iş (9)" step 2, bin/uzmanlik.py): uzmanlik = the job's specialisation (backend, ui,
# mobil, test, analiz, guvenlik, genel), uzmanlik_nedeni = the routing's short Turkish reason, uzmanlik_kaynagi = kural
# (the routing), elle (--uzmanlik), adim (a workflow review step) or yukseltme (taken over from the escalated job).
# Written by launch.create_job (and, for a workflow's kod step at its start, bin/akis.py with the plan text); never
# read from a note: the contract's "Rolün" section and the Karne row take it from here.
ROLE = ("uzmanlik", "uzmanlik_nedeni", "uzmanlik_kaynagi")
# The end-of-day review (bin/gunsonu.py): gun_sonu = the day (YYYY-MM-DD) whose review this job is; written only by the
# server right after it added the job, never read from a note. The post office keeps such an arge job out of the Ar-Ge
# report path and leaves its done notice to bin/gunsonu.py.
GUN_SONU = ("gun_sonu",)
# The Yakala inbox (bin/yakala.py): yakala = the captured item's id whose research job this is; written only by the
# server right after it added the job, never read from a note. The post office keeps such an arge job out of the Ar-Ge
# report path and leaves its done notice to bin/yakala.py.
YAKALA = ("yakala",)
# The prompt audit (bin/talimat_denetimi.py): talimat_denetimi = the audit id whose job this is; written only by the
# server right after it added the job, never read from a note. The post office keeps such an arge job out of the Ar-Ge
# report path and leaves its done notice to bin/talimat_denetimi.py.
TALIMAT = ("talimat_denetimi",)
# The advisor pilot (bin/danisman.py): danisman = the advisor model this job's sessions get (`--advisor`; arm B), "" for
# none; danisman_pilotu = the pilot id, danisman_kolu = A | B (written by launch.create_job only, cleared when the job
# leaves the pilot); danisman_cagri / danisman_hata ("code:n,…") / danisman_iterasyon = the advisor calls, their error
# results and the priced advisor iterations its transcripts showed (the post office, with the final spending). Never
# read from a note. danisman_nedeni = why this job's sessions get the advisor (bin/danisman.py advisor_decision: the
# pilot's arm B, the permanent mapping, or the hard-job rule's "zor iş: …" reason; "" for none), written with danisman
# by danisman.advisor_for at each start and resume of a job outside the pilot; the page shows it.
DANISMAN = ("danisman", "danisman_pilotu", "danisman_kolu", "danisman_cagri", "danisman_hata", "danisman_iterasyon",
            "danisman_nedeni")
FIELDS = TRUSTED + ("kontrol_ozet",) + DISPATCH + SERVER_ONLY + WORKFLOW + MODEL_CHOICE + KONTROL + CODEX + RISK + \
    BASE_STATE + TRIAL + QUOTA + ROLE + GUN_SONU + DANISMAN + YAKALA + TALIMAT
# the note fields a server write mirrors into the record (mirror()); karne rows read them from the record first
MIRRORED = KONTROL + ("katman", "model", "effort")
SESSION_IDS = "oturum_kimlikleri"  # a list: every session id the job's session had (a resume may fork, see channel.py)
NOTICES = "bildirilen"  # a list of notice keys
MIGRATE_STATUSES = jobs.ACTIVE_STATUSES + ("tikandi",)  # jobs that may still run or go on (devam)


digest = jobs.kontrol_digest

def path(durum_dir, job_name):
    return os.path.join(durum_dir, FOLDER, f"{jobs.stem(jobs.check_name(job_name))}.json")


def load(durum_dir, job_name):
    """The record of a job, or None (missing, a link, unreadable, or written for another job)."""
    try:
        p = path(durum_dir, job_name)
    except jobs.JobError:
        return None
    if os.path.islink(p) or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.loads(f.read(64 * 1024))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("is") != jobs.check_name(job_name):
        return None
    return data


def _write(p, data):
    folder = os.path.dirname(p)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _clean(fields):
    out = {}
    for key, value in fields.items():
        if key not in FIELDS:
            raise ValueError(f"unknown record field: {key}")
        if key == SESSION_IDS:
            value = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
            out[key] = [v for v in (str(x).strip() for x in value) if transcript.valid_session_id(v)]
            continue
        if key == DIRTY:
            out[key] = [str(v) for v in value if isinstance(v, str) and v and "\0" not in v] \
                if isinstance(value, (list, tuple)) else []
            continue
        if key == QUOTA_RESUME:
            v = value if isinstance(value, dict) else {}

            def count(x):
                return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else 0
            out[key] = {"sayi": count(v.get("sayi")), "elle": count(v.get("elle")),
                        "zamanlar": [str(x)[:19] for x in v.get("zamanlar") or [] if isinstance(x, str)][-10:],
                        "anahtarlar": [str(x)[:80] for x in v.get("anahtarlar") or [] if isinstance(x, str)][-20:],
                        "soruldu": str(v.get("soruldu") or "")[:80]}
            continue
        if key == QUOTA_PAIR:  # {asil, yedek} model names, or nothing
            pair = value if isinstance(value, dict) else {}
            out[key] = {k: str(pair[k])[:40] for k in ("asil", "yedek") if isinstance(pair.get(k), str) and pair[k]} \
                if pair.get("asil") and pair.get("yedek") else ""
            continue
        if key == NOTICES:
            value = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
            out[key] = [v for v in (str(x).strip() for x in value) if v and "\n" not in v]
            continue
        out[key] = "" if value is None else str(value)
    return out


def session_ids(data):
    """The record's oturum_kimlikleri as a list (valid ids only)."""
    value = (data or {}).get(SESSION_IDS)
    return [v for v in value if transcript.valid_session_id(v)] if isinstance(value, list) else []


def add_session_ids(durum_dir, job_name, ids, current=None):
    """Appends ids to the record's oturum_kimlikleri (once each, in order) and, with current, sets kisa_id to its
    first 8 characters. Returns the record, or None when the job has no record."""
    with jobs.locked():
        data = load(durum_dir, job_name)
        if data is None:
            return None
        known = session_ids(data)
        for sid in list(ids) + ([current] if current else []):
            if transcript.valid_session_id(sid) and sid not in known:
                known.append(sid)
        fields = {SESSION_IDS: known}
        if current:
            fields["kisa_id"] = current[:8]
        return update(durum_dir, job_name, fields, create=False)


def get(durum_dir, job, key):
    """A phase-3 field (DISPATCH) of a job: the record's value when the record has the key, else the note's."""
    data = load(durum_dir, job.name) if durum_dir else None
    if data is not None and key in data:
        return data.get(key) or ""
    return job.meta.get(key) or ""


def update(durum_dir, job_name, fields, create=True):
    """Sets fields on the job's record (created with them when missing and create is true). Returns the record."""
    name = jobs.check_name(job_name)
    p = path(durum_dir, name)
    with jobs.locked():
        data = load(durum_dir, name)
        if data is None:
            if not create:
                raise FileNotFoundError(p)
            data = {"is": name, "olusturuldu": f"{datetime.now():%Y-%m-%dT%H:%M:%S}"}
        data.update(_clean(fields))
        data["guncellendi"] = f"{datetime.now():%Y-%m-%dT%H:%M:%S}"
        _write(p, data)
        return data


def server_value(durum_dir, job_name, key):
    """A field of the record only ("" when the record or the key is missing): never the note's value."""
    return str((load(durum_dir, job_name) or {}).get(key) or "")


def notice_sent(durum_dir, job_name, key):
    """True when the record says the notice `key` was already sent for this job."""
    value = (load(durum_dir, job_name) or {}).get(NOTICES)
    return isinstance(value, list) and key in value


def add_notice(durum_dir, job_name, key):
    """Records that the notice `key` was sent for this job (kept at most 50 keys). False when it has no record."""
    with jobs.locked():
        data = load(durum_dir, job_name)
        if data is None:
            return False
        keys = [k for k in (data.get(NOTICES) or []) if isinstance(k, str)] if isinstance(data.get(NOTICES), list) \
            else []
        if key not in keys:
            keys = (keys + [key])[-50:]
            update(durum_dir, job_name, {NOTICES: keys}, create=False)
        return True


def from_note(job):
    """The record fields a note carries (the migration source). The session ids, the server-only fields and the
    workflow fields are never taken from a note."""
    return {k: job.meta.get(k, "") for k in FIELDS
            if k != SESSION_IDS and k not in SERVER_ONLY and k not in WORKFLOW and k not in MODEL_CHOICE
            and k not in KONTROL and k not in TRIAL and k not in ROLE and k not in MUDUR and k not in GUN_SONU
            and k not in DANISMAN and k not in YAKALA and job.meta.get(k, "") != ""}


@contextlib.contextmanager
def mirrored(durum_dir, job_name, fields):
    """mirror() around a note write: the record changes first; if the body (the note write) raises, the record's
    earlier values come back (a key it did not have is removed again), so the attempt count never runs ahead of a
    job whose note did not change. Use it under the job lock."""
    keys = [k for k in MIRRORED if k in (fields or {})]
    before = load(durum_dir, job_name) if keys and durum_dir else None
    mirror(durum_dir, job_name, fields or {})
    try:
        yield
    except BaseException:
        if before is not None:
            with jobs.locked():
                data = load(durum_dir, job_name)
                if data is not None:
                    for k in keys:
                        if k in before:
                            data[k] = before[k]
                        else:
                            data.pop(k, None)
                    _write(path(durum_dir, job_name), data)
        raise


def mirror(durum_dir, job_name, fields):
    """Copies the MIRRORED keys of a server write (kontrol_deneme, kontrol_sonuc, katman, model, effort) into the job's
    existing record; a job without a record is left alone. Call it under the job lock, before the note write."""
    values = {k: fields[k] for k in MIRRORED if k in fields}
    if not values or not durum_dir:
        return None
    try:
        return update(durum_dir, job_name, values, create=False)
    except FileNotFoundError:
        return None


def ensure(durum_dir, job, log=None):
    """The job's record; a job in MIGRATE_STATUSES without one gets it from its note, once (logged). None for other
    jobs without a record."""
    data = load(durum_dir, job.name)
    if data is not None or job.meta.get("durum") not in MIGRATE_STATUSES:
        return data
    with jobs.locked():
        data = load(durum_dir, job.name)
        if data is None:
            data = update(durum_dir, job.name, from_note(job))
            if log:
                log(f"created the server record of {job.name} from its note (migration)")
    return data


def trusted(durum_dir, job, log=None):
    """The job with the record's values in place of the note's for every TRUSTED field (a field the record lacks is
    empty, never taken from the note). A job without a record (and not migrated) is returned unchanged."""
    if job is None:
        return None
    data = ensure(durum_dir, job, log)
    if data is None:
        return job
    meta = dict(job.meta)
    for key in TRUSTED:
        meta[key] = data.get(key, "")
    meta[SESSION_IDS] = ",".join(session_ids(data))
    return job._replace(meta=meta)
