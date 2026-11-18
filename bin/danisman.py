"""The advisor pilot (danışman pilotu, Ar-Ge 2026-11-13 §3): does a Fable advisor (`claude --advisor fable`) make the
Kıdemli (Opus) `kod` jobs better enough to pay for itself?

Built OFF. Nothing changes while there is no running pilot: no arm, no flag, no record field.

1. The switch: ofis.json `danisman_pilotu: {"acik": false, "model": "fable", "is_sayisi": 10, "katman": "kod"}` (optional
   `arge_notu`: the Ar-Ge report the proposal card links, e.g. "ArGe-2026-11-13", when that note exists).
   `acik` is the pilot's kill switch; it is written true only by the owner's plain yes on the proposal card (and false again
   when the pilot's result card is answered). While it is false no job takes an arm and no job gets the flag from the
   pilot (also on a resume); the mapped advisor (point 5) does not depend on it.
2. The proposal card (tur: danisman-onerisi): `ofis.py danisman-pilotu oner`, run by the CEO only on the owner's word
   (CLAUDE.md); never created by the server on its own. One card while no cycle is open. The owner's answer goes through
   `ofis.py cevapla` (answer()): a plain yes starts the pilot (server state + `acik: true`); anything else closes it.
3. The pilot: launch.create_job(pilot=True) — `ekle`, workflow steps with a session, scheduled adds; never an escalation
   — for a job of the pilot's tier, with a Kontrol, not a self-test (deneme), without an explicit --model and not
   already a model-pilot job, takes one of `is_sayisi` slots (slot(), under the job lock). Arms alternate
   deterministically: A (no advisor) when A has no more jobs than B, else B (`--advisor <model>`), so the order is
   A, B, A, B … and a freed slot is refilled by the arm that lost it. The server record carries `danisman_pilotu`
   (the pilot id), `danisman_kolu` (A|B) and `danisman` (the advisor model for B, "" for A). A job leaves the pilot
   (its slot is freed) when it was cancelled before it started, when its launch failed (basarisiz), when it was started in a worktree (launch.start_job
   drops it before the launch: the flag is never added there), or when it ran on a quota backup model.
4. The flag: launch.session_flags(danisman=...) adds `--advisor <model>` on the start and on every resume; the value
   comes from advisor_for() — the record's `danisman` for a pilot job while the switch is on, else the mapped advisor.
5. The result card (tur: danisman-pilot-sonucu): when every pilot job is settled (model_secimi.settled) the server
   measures both arms from the Karne rows (karne._measure: Kontrol first-pass, rework, verified cost per job $ and
   tokens; rework rounds = karne._rework summed) plus the advisor calls the transcripts showed (records
   `danisman_cagri`, `danisman_hata`, `danisman_iterasyon`, written by the post office with the final spending; a job
   without them is "bilinmiyor"). Success (Ar-Ge's rule): B's first-pass rate at least 15 points above A's AND B's
   verified cost per job at most 25 % above A's; both arms need a measured Kontrol and a verified cost; and an arm B
   whose advisor was never called (every B job known, 0 calls) proves nothing (the advisor was not attached: Fable
   credit consent, issue 66784). One CEO notice.
6. The mapping change: only a plain yes on a SUCCESSFUL result card writes `tiers.<katman>.danisman = <model>` into
   ofis.json and one row into OFIS/Karne/Degisiklikler.md (model_secimi.changes_ready / record_change); from then on
   every job of that tier carries the flag (advisor_for). A failed pilot changes nothing.
7. The hard-job advisor (owner decision 2026-11-15; the pilot showed both arms passing 5/5 first time, with the advisor nearly
   doubling the verified usage per job): ofis.json `zor_is_danismani: {"acik", "model", "katman"}` (off when missing).
   A job outside the pilot, without a mapped advisor, of that tier gets `--advisor <model>` only when hard_reason()
   names a reason, computed at every start and resume from the server record and the workflow state only: the kod step
   of a workflow with a plan step (gelistir, never kucuk-is), an escalated job (yukseltme_kaynagi), a kod step whose
   code review rated the change yüksek risk, or rework (the review sent findings back: inceleme_turu; the Kontrol
   failed: kontrol_sonuc kaldi) — the advisor then joins on that resume. Precedence: the pilot, then the mapping, then
   this rule. advisor_for writes the outcome on the record (`danisman`, `danisman_nedeni`) when it changed; the page's
   job card shows "Danışman: Fable — zor iş: …".

State (server-owned; durum/model_secimi/danisman.json — no "__" in the name, so model_secimi.all_states never reads
it; the guard already protects the folder): durum bos|oneri|pilot|sonuc, kimlik, model, katman, is_sayisi, isler
[{is, kol}], the cards, sonuc, basari, bildirilen, gecmis.
"""
import json
import os
import re
from datetime import datetime

import ayarlar
import dil
import jobs
import karne
import launch
import model_secimi
import records
import sahip

STATE_FILE = "danisman.json"
KEY = "danisman_pilotu"
PROPOSAL, RESULT = "danisman-onerisi", "danisman-pilot-sonucu"
DECISIONS = (PROPOSAL, RESULT)
DEFAULTS = {"acik": False, "model": "fable", "is_sayisi": 10, "katman": "kod"}
OPEN = ("oneri", "pilot", "sonuc")
ADVISOR = re.compile(r"(?:opus|sonnet|fable|claude-[a-z0-9][a-z0-9.-]{1,60})")
MIN_JOBS, MAX_JOBS = 2, 40
ILK_TUR_ARTIS = 15  # points (Ar-Ge rule)
MALIYET_ARTIS = 0.25  # +25 % at most
# danisman_pilotu.arge_notu (optional): the Ar-Ge report the proposal card links (when that note exists in ArGe/)
ARGE_NOTU = re.compile(r"ArGe-\d{4}-\d{2}-\d{2}")
SYSTEM_PREFIX = model_secimi.SYSTEM_PREFIX
HISTORY_KEEP = 20
# the record fields of this pilot (bin/records.py DANISMAN)
FIELDS = ("danisman", "danisman_pilotu", "danisman_kolu", "danisman_cagri", "danisman_hata", "danisman_iterasyon")
# The hard-job advisor (owner decision 2026-11-15, after the pilot: on easy kod jobs the advisor nearly doubled the usage and added
# nothing): ofis.json `zor_is_danismani: {"acik": true, "model": "fable", "katman": "kod"}` — only a hard job of that
# tier gets `--advisor <model>` (hard_reason()); off when the key is missing.
HARD_KEY = "zor_is_danismani"
HARD_DEFAULTS = {"acik": False, "model": "fable", "katman": "kod"}
# the reasons stay Turkish on the record; bin/state.py translates them for the page (dil.N_ marks them, bin/dil.py EN)
HARD_REASONS = {"gelistir": dil.N_("zor iş: geliştirme akışının kod adımı"),
                "yukseltme": dil.N_("zor iş: bir üst katmana taşınan iş"),
                "risk": dil.N_("zor iş: kod incelemesi değişikliği yüksek riskli buldu"),
                "inceleme": dil.N_("zor iş: kod incelemesi düzeltme istedi"),
                "kontrol": dil.N_("zor iş: Kontrol geçmedi, yeniden çalışıyor")}


class Refused(ValueError):
    """A card that does not match the server state, a cycle already open, an invalid setting."""


def _stamp(now):
    return f"{now:%Y-%m-%dT%H:%M:%S}"


# --- settings and the effective advisor ---

def settings(cfg):
    """ofis.json `danisman_pilotu` over DEFAULTS; `var` = the key exists at all. A bad value keeps its default; `acik`
    is true only for the JSON value true."""
    given = (cfg or {}).get(KEY)
    out = dict(DEFAULTS, var=isinstance(given, dict), arge_notu=None)
    if not isinstance(given, dict):
        return out
    if isinstance(given.get("arge_notu"), str) and ARGE_NOTU.fullmatch(given["arge_notu"]):
        out["arge_notu"] = given["arge_notu"]
    out["acik"] = given.get("acik") is True
    if isinstance(given.get("model"), str) and ADVISOR.fullmatch(given["model"]):
        out["model"] = given["model"]
    n = given.get("is_sayisi")
    if isinstance(n, int) and not isinstance(n, bool) and MIN_JOBS <= n <= MAX_JOBS:
        out["is_sayisi"] = n
    if isinstance(given.get("katman"), str) and model_secimi.TIER_NAME.fullmatch(given["katman"]):
        out["katman"] = given["katman"]
    return out


def mapped(cfg, tier):
    """The advisor the mapping gives a tier (`tiers.<T>.danisman`, written only after the owner's yes on a successful
    result card), or ""."""
    entry = ((cfg or {}).get("tiers") or {}).get(tier or "")
    value = entry.get("danisman") if isinstance(entry, dict) else None
    return value if isinstance(value, str) and ADVISOR.fullmatch(value) else ""


def hard_settings(cfg):
    """ofis.json `zor_is_danismani` over HARD_DEFAULTS. Off unless the key exists with `acik` the JSON value true; a bad
    model or tier keeps its default."""
    given = (cfg or {}).get(HARD_KEY)
    out = dict(HARD_DEFAULTS)
    if not isinstance(given, dict):
        return out
    out["acik"] = given.get("acik") is True
    if isinstance(given.get("model"), str) and ADVISOR.fullmatch(given["model"]):
        out["model"] = given["model"]
    if isinstance(given.get("katman"), str) and model_secimi.TIER_NAME.fullmatch(given["katman"]):
        out["katman"] = given["katman"]
    return out


def _count(value):
    """A small non-negative count from a record value; anything unparseable or oversized counts as 0 (absent), so a
    malformed record never fails a start or a resume (int() refuses digit strings over Python's length limit)."""
    text = str(value or "").strip()
    if not text or len(text) > 6 or not text.isascii() or not text.isdigit():
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def hard_reason(durum_dir, job_name, rec=None):
    """Why a job counts as hard (zor iş) for the advisor, "" when it does not. Deterministic, from server-owned data
    only — the job's server record and its workflow's state, never the note or the project's text. In this order (the
    first match is the reason, so a job keeps one stable reason across its start and resumes):
    (a) the kod step of a workflow with a plan step (`gelistir`; never `kucuk-is`),
    (b) a job opened one tier up after a failure (escalation: the record's yukseltme_kaynagi),
    (d) a kod step whose workflow's code review rated the change yüksek risk (a kod-inceleme job's record `risk`),
    (c) rework: the code review sent findings back (the record's inceleme_turu ≥ 1), or the Kontrol failed
        (kontrol_sonuc "kaldi", or a pass only on a later attempt) — the advisor joins on that resume."""
    if rec is None:
        rec = (records.load(durum_dir, job_name) if durum_dir else None) or {}
    state = None
    if rec.get("akis") and durum_dir:
        import akis  # noqa: PLC0415 (bin/akis.py imports much; only a workflow step needs it)
        state = akis.load_state(durum_dir, str(rec["akis"]))
    steps = (state or {}).get("adimlar") or []
    kinds = {s.get("tur") for s in steps if isinstance(s, dict)}
    is_kod_step = rec.get("adim_turu") == "kod" and state is not None
    if is_kod_step and "plan" in kinds:
        return HARD_REASONS["gelistir"]
    if rec.get("yukseltme_kaynagi"):
        return HARD_REASONS["yukseltme"]
    if is_kod_step:
        for step in steps:
            if isinstance(step, dict) and step.get("tur") == "kod-inceleme":
                for name in step.get("isler") or []:
                    try:
                        if records.server_value(durum_dir, name, "risk") == "yuksek":
                            return HARD_REASONS["risk"]
                    except (jobs.JobError, ValueError):
                        continue
    if _count(rec.get("inceleme_turu")) >= 1:
        return HARD_REASONS["inceleme"]
    if rec.get("kontrol_sonuc") == "kaldi" or _count(rec.get("kontrol_deneme")) >= 2:
        return HARD_REASONS["kontrol"]
    return ""


def advisor_decision(cfg, durum_dir, job_name, tier):
    """(advisor model or "", reason or "") for a job's start or resume. Precedence: a job of the advisor pilot gets its
    record's `danisman` (B: the model, A: "") while the pilot's switch is on, nothing while it is off — the hard-job
    rule never touches it; else the permanent mapping (`tiers.<T>.danisman`); else the hard-job rule
    (`zor_is_danismani`): a job of its tier gets its model only when hard_reason() names a reason."""
    rec = records.load(durum_dir, job_name) if durum_dir else None
    rec = rec or {}
    if rec.get("danisman_pilotu"):
        if not settings(cfg)["acik"]:
            return "", ""
        value = str(rec.get("danisman") or "")
        return (value, dil.N_("danışman denemesi (B kolu)")) if ADVISOR.fullmatch(value) else ("", "")
    job_tier = rec.get("katman") or tier
    value = mapped(cfg, job_tier)
    if value:
        return value, dil.N_("kalıcı eşleme")
    hard = hard_settings(cfg)
    if not hard["acik"] or not durum_dir or job_tier != hard["katman"]:
        return "", ""
    reason = hard_reason(durum_dir, job_name, rec)
    return (hard["model"], reason) if reason else ("", "")


def advisor_for(cfg, durum_dir, job_name, tier):
    """The `--advisor` value for a job's start or resume, "" for none (advisor_decision). A job outside the advisor
    pilot also gets the decision on its server record — `danisman` (the model, "" for none) and `danisman_nedeni` (the
    plain Turkish reason the page shows) — written only when they changed (idempotent); a failed write never changes
    the flag."""
    value, reason = advisor_decision(cfg, durum_dir, job_name, tier)
    if durum_dir:
        try:
            rec = records.load(durum_dir, job_name)
            if rec is not None and not rec.get("danisman_pilotu") and \
                    (str(rec.get("danisman") or ""), str(rec.get("danisman_nedeni") or "")) != (value, reason):
                records.update(durum_dir, job_name, {"danisman": value, "danisman_nedeni": reason}, create=False)
        except (OSError, ValueError, jobs.JobError):
            pass
    return value


# --- the state ---

def state_path(durum_dir):
    return os.path.join(durum_dir, model_secimi.STATE_DIR, STATE_FILE)


def load(durum_dir):
    p = state_path(durum_dir)
    empty = {"durum": "bos", "gecmis": [], "bildirilen": []}
    if os.path.islink(p) or not os.path.isfile(p):
        return empty
    try:
        with open(p, encoding="utf-8") as f:
            data = json.loads(f.read(256 * 1024))
    except (OSError, ValueError, UnicodeDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("durum") not in ("bos",) + OPEN:
        return empty
    data.setdefault("gecmis", [])
    data.setdefault("bildirilen", [])
    data.setdefault("isler", [])
    return data


def save(durum_dir, state):
    p = state_path(durum_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    jobs._write_atomic(p, json.dumps(state, ensure_ascii=False, indent=1) + "\n")


def _arms(state):
    a = sum(1 for e in state.get("isler") or [] if e.get("kol") == "A")
    return a, len(state.get("isler") or []) - a


def _close(state, outcome, now):
    entry = {k: state.get(k, "") for k in ("kimlik", "model", "katman", "oneri_notu", "sonuc_notu")}
    entry.update(sonuc=outcome, kapandi=_stamp(now), basari=bool(state.get("basari")))
    return {"durum": "bos", "kapandi": _stamp(now), "bildirilen": (state.get("bildirilen") or [])[-20:],
            "gecmis": ((state.get("gecmis") or []) + [entry])[-HISTORY_KEEP:]}


# --- the pilot's slots (launch.create_job / start_job, under the job lock) ---

def slot(cfg, durum_dir, tier, trial=False, explicit_model=False, model_pilot=False, kontrol=""):
    """(kimlik, kol, advisor) when the new job takes a slot of the running advisor pilot, else None. Nothing while the
    switch is off."""
    s = settings(cfg)
    if not durum_dir or not s["acik"] or trial or explicit_model or model_pilot or not (kontrol or "").strip():
        return None
    state = load(durum_dir)
    if state.get("durum") != "pilot" or tier != state.get("katman"):
        return None
    if len(state.get("isler") or []) >= int(state.get("is_sayisi") or 0):
        return None
    a, b = _arms(state)
    kol = "A" if a <= b else "B"
    return state["kimlik"], kol, (state["model"] if kol == "B" else "")


def add_job(durum_dir, kimlik, job_name, kol):
    state = load(durum_dir)
    if state.get("durum") != "pilot" or state.get("kimlik") != kimlik:
        raise Refused(f"no running advisor pilot {kimlik}")
    state["isler"] = (state.get("isler") or []) + [{"is": jobs.check_name(job_name), "kol": kol}]
    save(durum_dir, state)


def leave(durum_dir, job_name, reason, log=None):
    """Takes a job out of the pilot (its slot is freed; its record keeps no arm, so it never gets the pilot's flag).
    False when it was not in a running pilot."""
    name = jobs.check_name(job_name)
    with jobs.locked():
        state = load(durum_dir)
        names = [e.get("is") for e in state.get("isler") or []]
        if state.get("durum") != "pilot" or name not in names:
            return False
        state["isler"] = [e for e in state["isler"] if e.get("is") != name]
        save(durum_dir, state)
        if records.load(durum_dir, name) is not None:
            records.update(durum_dir, name, {"danisman_pilotu": "", "danisman_kolu": "", "danisman": ""},
                           create=False)
    if log:
        log(f"advisor pilot {state.get('kimlik')}: {name} left the pilot ({reason}); slot freed")
    return True


# --- ofis.json ---

def _write_config(config_path, change):
    """Reads ofis.json, applies change(data) and replaces the file atomically (key order kept): bin/ayarlar.py yaz,
    the office's one config writer (under the job lock)."""
    return ayarlar.yaz(config_path, change)


def set_switch(config_path, cfg, on):
    """danisman_pilotu.acik = on in ofis.json (the key is created with DEFAULTS when missing) and in this cfg."""
    def change(data):
        entry = data.get(KEY) if isinstance(data.get(KEY), dict) else \
            {k: v for k, v in DEFAULTS.items()}
        entry["acik"] = bool(on)
        data[KEY] = entry
    data = _write_config(config_path, change)
    cfg[KEY] = dict(data[KEY])


def set_mapping(config_path, cfg, tier, model):
    """tiers.<tier>.danisman = model in ofis.json and in this cfg."""
    def change(data):
        entry = (data.get("tiers") or {}).get(tier)
        if not isinstance(entry, dict):
            raise Refused(f"tier '{tier}' is not in ofis.json")
        entry["danisman"] = model
    _write_config(config_path, change)
    (cfg.get("tiers") or {}).setdefault(tier, {})["danisman"] = model


def refresh(cfg, fresh):
    """Takes `danisman_pilotu`, `zor_is_danismani` and every tier's `danisman` of a freshly read ofis.json into the
    running cfg (bin/ayarlar.py tazele calls it: `ofis.py cevapla` writes them in another process; the
    hard-job switch is taken along so turning it off needs no restart)."""
    for key in (KEY, HARD_KEY):
        if isinstance(fresh.get(key), dict):
            cfg[key] = dict(fresh[key])
        else:
            cfg.pop(key, None)
    tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
    new = fresh.get("tiers") if isinstance(fresh.get("tiers"), dict) else {}
    for tier, entry in tiers.items():
        if not isinstance(entry, dict):
            continue
        value = (new.get(tier) or {}).get("danisman") if isinstance(new.get(tier), dict) else None
        if isinstance(value, str) and value:
            entry["danisman"] = value
        else:
            entry.pop("danisman", None)


# --- measuring (pure over the rows and the records) ---

def _advisor_stats(durum_dir, names):
    """{cagri, hata: {code: n}, bilinen, bilinmeyen, hic_cagrilmayan, iterasyon} over the jobs' records."""
    out = {"cagri": 0, "hata": {}, "bilinen": 0, "bilinmeyen": 0, "hic_cagrilmayan": 0, "iterasyon": 0}
    for name in names:
        rec = records.load(durum_dir, name) or {}
        raw = str(rec.get("danisman_cagri") or "")
        if not raw.isdigit():
            out["bilinmeyen"] += 1
            continue
        out["bilinen"] += 1
        out["cagri"] += int(raw)
        out["hic_cagrilmayan"] += 1 if int(raw) == 0 else 0
        it = str(rec.get("danisman_iterasyon") or "")
        out["iterasyon"] += int(it) if it.isdigit() else 0
        for part in str(rec.get("danisman_hata") or "").split(","):
            code, _, n = part.partition(":")
            if code and n.isdigit():
                out["hata"][code] = out["hata"].get(code, 0) + int(n)
    return out


def measure_arm(rows, events, escalated, names, durum_dir):
    stems = {jobs.stem(n) for n in names}
    arm_rows = [r for r in rows if model_secimi.stem_of(r) in stems]
    m = model_secimi._rounded(model_secimi.measure(arm_rows, events, escalated))
    m["yeniden_is_turu"] = sum(karne._rework(r, events) for r in arm_rows)
    m["isler"] = sorted(stems)
    m["danisman"] = _advisor_stats(durum_dir, names)
    return m


def _first(m):
    return m["ilk_tur_gecen"] / m["ilk_tur_olculen"] if m.get("ilk_tur_olculen") else None


def success(a, b):
    """(basari, reason) — Ar-Ge's rule over the two arms' measurements."""
    adv = b.get("danisman") or {}
    if adv.get("bilinen") and not adv.get("bilinmeyen") and adv.get("cagri") == 0:
        return False, "B kolunda danışman hiç çağrılmadı (bağlanmamış olabilir); deneme danışmanı ölçmedi"
    fa, fb = _first(a), _first(b)
    if fa is None or fb is None:
        return False, "iki kolda da kontrolü çalışan iş olmalı"
    ca, cb = a.get("dogrulanmis_is_basina_usd"), b.get("dogrulanmis_is_basina_usd")
    if ca is None or cb is None:
        return False, "iki kolda da Kontrolü geçen (doğrulanmış) iş olmalı"
    points = 100 * (fb - fa)
    if points < ILK_TUR_ARTIS - 1e-9:
        return False, f"ilk turda geçme {round(points):+d} puan değişti (en az +{ILK_TUR_ARTIS} gerekiyordu)"
    if cb > ca * (1 + MALIYET_ARTIS) + 1e-9:
        rise = round(100 * (cb / ca - 1)) if ca else None
        return False, (f"doğrulanmış iş başına kullanım %{rise} arttı (en çok %{round(100 * MALIYET_ARTIS)})"
                       if rise is not None else "doğrulanmış iş başına kullanım karşılaştırılamadı")
    return True, (f"ilk turda geçme {round(points):+d} puan, doğrulanmış iş başına kullanım "
                  f"{'%' + format(round(100 * (cb / ca - 1)), '+d') if ca else '—'}")


# --- the cards ---

def _note_name(vault, now, kind):
    folder = os.path.join(vault, "Kararlar")
    base = f"{now:%Y-%m-%d}-ofis-{kind}"
    for suffix in [""] + [f"-{i}" for i in range(2, 100)]:
        name = f"{base}{suffix}.md"
        if not os.path.lexists(os.path.join(folder, name)):
            return name
    raise Refused("no free decision note name")


def _frontmatter(kind, state, now, extra=()):
    lines = ["tags: [ofis, karar, danisman]"]
    for key, value in (("proje", "ofis"), ("durum", "bekliyor"), ("tur", kind), ("katman", state["katman"]),
                       ("danisman", state["model"]), ("pilot", state["kimlik"]), *extra, ("soruldu", _stamp(now))):
        jobs._set_line(lines, key, value)
    return lines


def _main_who(cfg, tier):
    model = ((cfg.get("tiers") or {}).get(tier) or {}).get("model") or ""
    return model_secimi.who(model) or tier


def proposal_card(cfg, vault, state, now):
    t, n, adv = state["katman"], state["is_sayisi"], model_secimi.who(state["model"])
    main = _main_who(cfg, t)
    arge = settings(cfg)["arge_notu"]
    source = (f"Ar-Ge raporu [[{arge}]] (danışman bölümü). " if
              arge and os.path.isfile(os.path.join(vault, "ArGe", arge + ".md")) else "")
    body = (f"# Danışman denemesi: {t} işlerde {adv} danışman\n\n"
            f"## Soru\n{main} {t} işlerinde {adv} danışman denensin mi? \"Evet\" yazarsan sonraki {n} gerçek {t} işi "
            f"sırayla iki kola ayrılır: A (danışmansız) ve B ({adv} danışmanlı). Başka bir şey yazarsan öneri kapanır.\n\n"
            f"## Kanıt\n{source}Danışman, ana çalışanın karar anlarında (yaklaşım seçerken, tekrar eden hatada, işi "
            "bitirmeden önce) tüm konuşmayı okuyup tavsiye veren daha güçlü bir çalışandır. Her danışman çağrısı tüm "
            f"konuşmayı {adv} fiyatından, önbelleksiz okur; bu ana çalışanın kullanımına eklenir.\n\n"
            f"## Ne olur\nOnaylarsan sonraki {n} {t} işi (deneme işleri, çalışanı elle seçilenler, kadro denemesindeki "
            "işler ve bir üst katmana taşınan işler hariç) sırayla A, B, A, B … olarak çalışır; B işleri "
            f"`--advisor {state['model']}` ile başlar ve her devamda da öyle sürer. Kullanım sınırı ve Kontrol kuralları aynen geçerli "
            "(B işlerinin kullanımına danışman da girer). Hepsi bitince sunucu iki kolu karşılaştırır: B'nin Kontrol'ü "
            f"ilk turda geçme oranı en az {ILK_TUR_ARTIS} puan yüksekse ve doğrulanmış iş başına kullanımı en çok "
            f"%{round(100 * MALIYET_ARTIS)} fazlaysa ayrı bir kartla \"danışman kalıcı olsun mu?\" diye sorar; değilse "
            "bırakılmasını önerir. Eşleme şimdilik değişmez. Fable için kullanım kredisi onayı yoksa oturum "
            "danışmansız başlar; sonuç kartı bunu danışman çağrı sayısıyla gösterir.\n\n"
            "## İlgili Sayfalar\n- [[Ozet]]\n- [[OFIS/README]]\n")
    return jobs.render(_frontmatter(PROPOSAL, state, now), body)


def _pct(m):
    return model_secimi._pct(m["ilk_tur_gecen"], m["ilk_tur_olculen"])


def _advisor_text(d):
    if not d or not d.get("bilinen"):
        return "bilinmiyor"
    text = f"{d['cagri']}"
    if d.get("bilinmeyen"):
        text += f" ({d['bilinmeyen']} işte bilinmiyor)"
    return text


def _errors_text(d):
    codes = (d or {}).get("hata") or {}
    return ", ".join(f"{k} ×{v}" for k, v in sorted(codes.items())) or "yok"


def result_card(state, now):
    t, adv = state["katman"], model_secimi.who(state["model"])
    a, b, ok = state["sonuc"]["A"], state["sonuc"]["B"], state["basari"]
    rows = [("İş sayısı (kontrolü çalışan)", f"{a['is_sayisi']} ({a['ilk_tur_olculen']})",
             f"{b['is_sayisi']} ({b['ilk_tur_olculen']})"),
            ("Kontrol ilk turda geçme", _pct(a), _pct(b)),
            ("Yeniden iş (iş / tur)", f"{a['yeniden_is']} / {a['yeniden_is_turu']}",
             f"{b['yeniden_is']} / {b['yeniden_is_turu']}"),
            ("Bir üst katmana taşınan", f"{a['yukseltme']}/{a['is_sayisi']}", f"{b['yukseltme']}/{b['is_sayisi']}"),
            ("Doğrulanmış iş başına kullanım", model_secimi._spend(a), model_secimi._spend(b)),
            ("Danışman çağrısı", "—", _advisor_text(b.get("danisman"))),
            ("Danışman hatası (unavailable vb.)", "—", _errors_text(b.get("danisman")))]
    table = karne._table_head(("Ölçüt", "A (danışmansız)", f"B ({adv} danışman)")) + \
        "\n".join(f"| {x} | {y} | {z} |" for x, y, z in rows)
    rule = (f"B'nin ilk turda geçme oranı en az {ILK_TUR_ARTIS} puan yüksek ve doğrulanmış iş başına kullanımı en çok "
            f"%{round(100 * MALIYET_ARTIS)} fazla olmalı")
    notes = []
    d = b.get("danisman") or {}
    if d.get("bilinen") and d.get("hic_cagrilmayan"):
        notes.append(f"B kolunda {d['hic_cagrilmayan']} işte danışman hiç çağrılmadı (bağlanmamış olabilir).")
    if (d.get("hata") or {}).get("unavailable"):
        notes.append("Danışman bazı çağrılarda \"unavailable\" döndü.")
    if d.get("cagri") and not d.get("iterasyon"):
        notes.append("Danışman çağrılarının kullanımı oturum kaydında görünmedi; B'nin kullanımı eksik olabilir.")
    if ok:
        question = (f"Danışman kalıcı olsun mu: {t} işler → {adv} danışman? \"Evet\" yazarsan bundan sonraki bütün {t} "
                    "işleri danışmanla başlar; başka bir şey yazarsan danışman kullanılmaz.")
        advice = f"Deneme başarılı ({state['neden']}; kural: {rule}). Danışmanın kalıcı olmasını öneriyorum."
        then = (f"Onaylarsan sunucu `ofis.json`'da {t} katmanına `danisman: {state['model']}` yazar ve [[Degisiklikler]] "
                "notuna bir satır ekler. Geri dönüş otomatik değildir.")
    else:
        question = ("Deneme danışmanın değerini kanıtlamadı; danışman kullanılmayacak. Bu kartı kapatmak için \"tamam\" "
                    "yazman yeterli; ne yazarsan yaz bir şey değişmez.")
        advice = f"Deneme kanıtlamadı ({state['neden']}; kural: {rule}). Danışmanı bırakmayı öneriyorum."
        then = f"Hiçbir şey değişmez: {t} işler danışmansız çalışmaya devam eder."
    body = (f"# Danışman denemesi sonucu: {t} işlerde {adv} danışman\n\n"
            f"## Soru\n{question}\n\n"
            f"## Karşılaştırma\nA: {model_secimi._links(a['isler'])}. B: {model_secimi._links(b['isler'])}.\n\n"
            f"{table}\n" + ("\n" + "\n".join(f"- {x}" for x in notes) + "\n" if notes else "") + "\n"
            f"## Öneri\n{advice}\n\n"
            f"## Ne olur\n{then}\n\n"
            f"## İlgili Sayfalar\n- [[{state['oneri_notu'][:-3]}]]\n- [[Ozet]]\n- [[OFIS/README]]\n")
    return jobs.render(_frontmatter(RESULT, state, now, (("basari", "evet" if ok else "hayır"),)), body)


def result_notice(state):
    outcome = ("Deneme başarılı; danışmanın kalıcı olması soruluyor" if state["basari"] else
               "Deneme kanıtlamadı; danışman kullanılmayacak, kart yalnızca kapatılacak")
    return (f"{SYSTEM_PREFIX}Danışman denemesi bitti: {state['katman']} işler, {model_secimi.who(state['model'])} "
            f"danışman ({len(state.get('isler') or [])} iş). {outcome}. Karar kartı: [[{state['sonuc_notu'][:-3]}]]. "
            f"{sahip.e()} tek satırla bildir; cevabını `ofis.py cevapla` ile ilet.")


# --- the CEO's command: ofis.py danisman-pilotu oner (only on the owner's word) ---

def propose(cfg, durum_dir, now):
    """Writes the one proposal card. Refused while a cycle is open or without the ofis.json key."""
    s = settings(cfg)
    if not s["var"]:
        raise Refused("ofis.json has no danisman_pilotu key")
    if s["katman"] not in (cfg.get("tiers") or {}):
        raise Refused(f"tier '{s['katman']}' is not in ofis.json")
    vault = os.path.expanduser(cfg["vault_ofis"])
    with jobs.locked(vault):
        state = load(durum_dir)
        if state.get("durum") in OPEN:
            raise Refused(f"the advisor pilot is already '{state['durum']}' ({state.get('kimlik')}); one at a time")
        note = _note_name(vault, now, PROPOSAL)
        state.update(durum="oneri", kimlik=f"danisman-{s['katman']}-{now:%Y%m%d%H%M%S}", model=s["model"],
                     katman=s["katman"], is_sayisi=s["is_sayisi"], oneri_notu=note, oneri_tarihi=_stamp(now),
                     isler=[], sonuc={}, basari=False, neden="", sonuc_notu="")
        save(durum_dir, state)  # the state first: a crash before the note never proposes twice
        model_secimi._write_note(vault, note, proposal_card(cfg, vault, state, now))
    return {"karar": note, "kimlik": state["kimlik"], "model": state["model"], "katman": state["katman"],
            "is_sayisi": state["is_sayisi"]}


# --- the server pass (post office, after the Karne rows) ---

class Pilot:
    def __init__(self, cfg, durum_dir, ceo, now=datetime.now, log=None):
        self.cfg = cfg
        self.vault = os.path.expanduser(cfg["vault_ofis"])
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.now = now
        self.log = log or (lambda text: None)

    def check(self):
        """One pass: frees slots, writes the result card when every pilot job is settled, sends its one notice.
        Returns the note written or None."""
        written = None
        with jobs.locked(self.vault):
            state = load(self.durum_dir)
            if state.get("durum") == "pilot":
                state = self._free_slots(state)
                written = self._finish(state)
            state = load(self.durum_dir)
            note = state.get("sonuc_notu") if state.get("durum") == "sonuc" else ""
            path = os.path.join(self.vault, "Kararlar", note) if note else ""
            if note and not os.path.lexists(path):
                try:  # its write failed after the state was saved: written again from the state
                    model_secimi._write_note(self.vault, note, result_card(state, _parse(state.get("sonuc_tarihi"))
                                                                           or self.now()))
                except (OSError, Refused, model_secimi.Refused, KeyError) as e:
                    self.log(f"advisor result card {note} could not be written: {e}")
        if note and os.path.isfile(path):
            key = f"danisman-pilot-sonucu-{state['kimlik']}"
            if key not in (state.get("bildirilen") or []):
                self.ceo.enqueue(result_notice(state), key)
                with jobs.locked(self.vault):
                    fresh = load(self.durum_dir)
                    fresh["bildirilen"] = ((fresh.get("bildirilen") or []) + [key])[-20:]
                    save(self.durum_dir, fresh)
        return written

    def _free_slots(self, state):
        keep = []
        for entry in state.get("isler") or []:
            name = entry.get("is") or ""
            job = jobs.find(self.vault, name)
            if job is not None and job.meta.get("durum") == "iptal" and not job.meta.get("baslangic"):
                self.log(f"advisor pilot {state['kimlik']}: {name} was cancelled before it started; slot freed")
                continue
            if job is not None and job.meta.get("durum") == "basarisiz":
                import gunsonu  # lazy: a large module
                why = gunsonu._baslatma_nedeni(job.body) or "reason unknown"
                # not worded as an error: the job itself is the bad case (gün sonu), this line only says why
                self.log(f"advisor pilot {state['kimlik']}: {name} did not start ({why}); slot freed")
                continue
            if records.server_value(self.durum_dir, name, "model_kaynagi") == "kota":
                self.log(f"advisor pilot {state['kimlik']}: {name} ran with a quota backup; slot freed")
                continue
            keep.append(entry)
        if keep != state.get("isler"):
            state["isler"] = keep
            save(self.durum_dir, state)
        return state

    def _finish(self, state):
        entries = state.get("isler") or []
        if len(entries) < int(state.get("is_sayisi") or 0):
            return None
        for entry in entries:
            job = jobs.find(self.vault, entry["is"])
            if job is not None and not model_secimi.settled(self.durum_dir, job):
                return None
        rows = karne._rows(self.vault)  # every row: a pilot job is never a self-test (slot() refuses them)
        events = karne._rework_events(self.vault)
        escalated = model_secimi.escalated_jobs(self.vault)
        arms = {k: [e["is"] for e in entries if e.get("kol") == k] for k in ("A", "B")}
        result = {k: measure_arm(rows, events, escalated, names, self.durum_dir) for k, names in arms.items()}
        ok, reason = success(result["A"], result["B"])
        now = self.now()
        state.update(sonuc=result, basari=ok, neden=reason, durum="sonuc",
                     sonuc_notu=_note_name(self.vault, now, RESULT), sonuc_tarihi=_stamp(now))
        save(self.durum_dir, state)
        model_secimi._write_note(self.vault, state["sonuc_notu"], result_card(state, now))
        self.log(f"advisor pilot {state['kimlik']} finished ({'success' if ok else 'not proven'}: {reason})")
        return state["sonuc_notu"]


def _parse(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# --- the owner's answer (ofis.py cevapla, under the job lock) ---

def answer(cfg, durum_dir, note, meta, text, now, approved, config_path=None):
    vault = os.path.expanduser(cfg["vault_ofis"])
    kind = meta.get("tur")
    state = load(durum_dir)
    expected = ("oneri", "oneri_notu") if kind == PROPOSAL else ("sonuc", "sonuc_notu")
    if state.get("durum") != expected[0] or state.get(expected[1]) != note or meta.get("pilot") != state.get("kimlik"):
        raise Refused(f"{note}: bu danışman kartı sunucu kaydıyla uyuşmuyor; cevap işlenmedi")
    out = {"tur": kind, "onay": approved, "katman": state["katman"], "danisman": state["model"]}
    if kind == PROPOSAL:
        if approved:
            if not config_path:
                raise Refused("the ofis.json path is unknown; the pilot was not started")
            set_switch(config_path, cfg, True)  # the switch first: without the pilot state it gives no job an arm,
            state.update(durum="pilot", pilot_baslangic=_stamp(now), isler=[])  # and a failed write here can be
            save(durum_dir, state)  # answered again (the card stays bekliyor, the state oneri)
            out.update(pilot=state["kimlik"], is_sayisi=state["is_sayisi"])
        else:
            save(durum_dir, _close(state, "reddedildi", now))
            out["pilot"] = ""
        return out
    changed = False
    if approved and state.get("basari"):
        if not config_path:
            raise Refused("the ofis.json path is unknown; the mapping was not changed")
        model_secimi.changes_ready(vault)  # before ofis.json: a Degisiklikler.md that cannot be written refuses
        old = mapped(cfg, state["katman"]) or "yok"
        set_mapping(config_path, cfg, state["katman"], state["model"])
        changed = True
        a, b = state["sonuc"]["A"], state["sonuc"]["B"]
        reason = (f"Danışman denemesi: ilk turda geçme A {_pct(a)}, B {_pct(b)}; doğrulanmış iş başına kullanım "
                  f"A {model_secimi._usd(a.get('dogrulanmis_is_basina_usd'))}, "
                  f"B {model_secimi._usd(b.get('dogrulanmis_is_basina_usd'))}")
        try:
            model_secimi.record_change(vault, now, "tüm projeler", state["katman"], f"danışman {old}",
                                       f"danışman {state['model']}", reason, note)
        except (OSError, model_secimi.Refused) as e:
            out["uyari"] = (f"eşleme değişti ama Karne/Degisiklikler.md satırı yazılamadı ({type(e).__name__}: {e}); "
                            "satır eksik")
    save(durum_dir, _close(state, "eslesme-degisti" if changed else "degismedi", now))
    if config_path and settings(cfg)["acik"]:
        set_switch(config_path, cfg, False)  # the pilot is over: its switch goes back off
    out.update(eslesme_degisti=changed)
    return out


# --- read-only views (ofis.py danisman-pilotu durum, GET /api/kalite) ---

def page(cfg, durum_dir):
    """The pilot for the page and `ofis.py modeller`: None while nothing ever happened; else {durum, acik, model,
    katman, is_sayisi, eklenen, A, B (eklenen/biten), sonuc (per-arm numbers once measured), basari, not, eslesme}."""
    s = settings(cfg)
    state = load(durum_dir)
    tier_map = mapped(cfg, s["katman"])
    if state.get("durum") == "bos" and not state.get("gecmis") and not tier_map:
        return None
    vault = os.path.expanduser(cfg["vault_ofis"])
    out = {"durum": state.get("durum"), "acik": s["acik"], "model": state.get("model") or s["model"],
           "katman": state.get("katman") or s["katman"], "is_sayisi": int(state.get("is_sayisi") or s["is_sayisi"]),
           "eslesme": tier_map, "kimlik": state.get("kimlik", ""), "not": "", "basari": None, "sonuc": None}
    if state.get("durum") == "oneri":
        out["not"] = state.get("oneri_notu", "")
    elif state.get("durum") == "sonuc":
        out.update(**{"not": state.get("sonuc_notu", "")}, basari=bool(state.get("basari")),
                   neden=state.get("neden", ""))
    if state.get("sonuc"):
        out["sonuc"] = {k: {x: v.get(x) for x in ("is_sayisi", "ilk_tur_gecen", "ilk_tur_olculen", "yeniden_is",
                                                    "yeniden_is_turu", "dogrulanmis_is_basina_usd",
                                                    "dogrulanmis_is_basina_token")}
                        | {"danisman_cagri": (v.get("danisman") or {}).get("cagri")
                           if (v.get("danisman") or {}).get("bilinen") else None}
                        for k, v in state["sonuc"].items()}
    arms = {"A": {"eklenen": 0, "biten": 0}, "B": {"eklenen": 0, "biten": 0}}
    for entry in state.get("isler") or []:
        arm = arms.get(entry.get("kol"))
        if arm is None:
            continue
        arm["eklenen"] += 1
        job = jobs.find(vault, entry.get("is") or "")
        if job is None or job.meta.get("durum") in jobs.FINAL_STATUSES:
            arm["biten"] += 1
    out.update(A=arms["A"], B=arms["B"], eklenen=arms["A"]["eklenen"] + arms["B"]["eklenen"])
    return out


def table(cfg, durum_dir):
    p = page(cfg, durum_dir)
    if p is None:
        s = settings(cfg)
        return (f"DANIŞMAN PİLOTU: yok (anahtar {'var' if s['var'] else 'yok'}, acik={'true' if s['acik'] else 'false'}, "
                f"{s['katman']} → {s['model']}, {s['is_sayisi']} iş)\n")
    lines = [f"DANIŞMAN PİLOTU: {p['durum']} (acik={'true' if p['acik'] else 'false'}) {p['katman']} → {p['model']} "
             f"danışman, {p['eklenen']}/{p['is_sayisi']} iş (A {p['A']['eklenen']}, B {p['B']['eklenen']}) "
             f"[{p['kimlik']}]"]
    if p["not"]:
        lines.append(f"  kart: [[{p['not'][:-3]}]]")
    if p["eslesme"]:
        lines.append(f"  eşleme: {p['katman']} işler danışman {p['eslesme']} ile başlar")
    for arm, m in (p.get("sonuc") or {}).items():
        lines.append(f"  {arm}: ilk tur {model_secimi._pct(m['ilk_tur_gecen'], m['ilk_tur_olculen'])}, yeniden iş "
                     f"{m['yeniden_is']} iş / {m['yeniden_is_turu']} tur, doğrulanmış iş başına "
                     f"{model_secimi._usd(m['dogrulanmis_is_basina_usd'])}, danışman çağrısı "
                     f"{'bilinmiyor' if m['danisman_cagri'] is None else m['danisman_cagri']}")
    return "\n".join(lines) + "\n"
