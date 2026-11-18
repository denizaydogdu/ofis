"""Evidence-based model selection (phase 8, ADR-002 §8 "kanıta dayalı katmanlar"): Karne → pilot → mapping.

Deterministic server code finds the evidence and writes the proposal; the CEO only relays it; the owner decides; nothing
changes without his plain yes (akis.is_approval).

1. Finding a proposal (candidates(), pure over the Kayitlar rows): per project × tier, only the rows of the model the
   project's CURRENT mapping uses for that tier (project override > global tiers), without jobs whose model was given
   explicitly (`model_kaynagi: elle` on the server record), never a Codex review (model "codex") and never a
   self-test row (Karne column Deneme = evet, karne.counted; a self-test job takes no pilot slot either). With at least
   `min_is` rows whose Kontrol was measured:
   - aşağı: first-pass ≥ asagi_ilk_tur, rework ratio ≤ asagi_yeniden_is, no escalation, a cheaper model exists
   - yukarı: first-pass < yukari_ilk_tur or escalation ratio ≥ yukari_yukseltme, a stronger model exists
   The step is one model along MODEL_ORDER (haiku < sonnet < opus < fable); the effort is that model's usual one.
   Never while a proposal, a pilot or a result card of the same project × tier is open, nor until `yeniden_oneri_is`
   new rows of that project × tier were recorded after the last cycle ended.
2. The proposal card: a pending Kararlar note `YYYY-MM-DD-<proje>-<katman>-model-onerisi.md` (tur: model-onerisi) and
   one CEO notice (key model-onerisi-<kimlik>; the state remembers it was queued, so a restart never sends it twice).
3. The answer (`ofis.py cevapla`, answer()): a plain yes starts the pilot; anything else closes the proposal.
4. The pilot: launch.create_job(pilot=True) — `ekle`, workflow steps with a Claude session, scheduled adds; never an
   escalation — for that project × tier with a Kontrol and without an explicit --model takes the pilot model
   (pilot_slot), marks the note and the server record `pilot: <kimlik>`, until `pilot_is` jobs were added. A pilot job
   cancelled before it started gives its slot back. When all of them are final (a workflow step that ended bitti only
   once its workflow is closed: a review can reopen it) and their Karne rows are written, the
   server compares them with the proposal's evidence (like with like: first-pass over measured Kontrols on both sides)
   and writes a second pending card `…-model-pilot-sonucu.md` (tur: model-pilot-sonucu) + one notice. Success: aşağı =
   every measured pilot job passed its Kontrol on the first run and none was escalated; yukarı = pilot first-pass ≥
   yukari_ilk_tur; nothing measured proves nothing.
   Reminders: a card still pending 3 days after it was asked, and a pilot job still queued 3 days after it was added,
   get one CEO notice, then at most one per 7 days (kept in the state's `hatirlatma`). A card whose note is missing
   (its write failed) is written again from the state before any notice links it.
5. The mapping change: a plain yes on a SUCCESSFUL result card writes `projects.<P>.tiers.<T> = {model, effort}` into
   ofis.json (set_override: temp file + os.replace, the rest of the file and its key order kept) and appends one row to
   OFIS/Karne/Degisiklikler.md (checked writable before ofis.json changes; a row that still fails afterwards is a
   warning in the answer, not a refusal: the mapping did change). A yes on a failed pilot changes nothing; it just closes the card. No automatic revert:
   a revert is a later proposal like any other.

State (server-owned; written by the server and by `ofis.py cevapla`, under the job lock):
    durum/model_secimi/<proje>__<katman>.json   one file per project × tier: the open cycle (durum bos|oneri|pilot|
                                                sonuc, kimlik, yon, models, evidence, cards, pilot jobs, result),
                                                kapanis_satir (row count when the last cycle closed), bildirilen
                                                (notice keys queued), gecmis (closed cycles)
"""
import json
import os
import re
from datetime import datetime, timedelta

import ayarlar
import budget
import jobs
import karne
import launch
import rapor
import records
import sahip

STATE_DIR = "model_secimi"
DEFAULTS = {"min_is": 5, "asagi_ilk_tur": 0.9, "asagi_yeniden_is": 0.1, "yukari_ilk_tur": 0.6,
            "yukari_yukseltme": 0.3, "pilot_is": 3, "yeniden_oneri_is": 10}
INTEGER_SETTINGS = ("min_is", "pilot_is", "yeniden_oneri_is")
MODEL_ORDER = ("haiku", "sonnet", "opus", "fable")  # cheaper → stronger
MODEL_EFFORT = {"haiku": "low", "sonnet": "medium", "opus": "high", "fable": "high"}
OPEN = ("oneri", "pilot", "sonuc")
PROPOSAL, RESULT = "model-onerisi", "model-pilot-sonucu"
SYSTEM_PREFIX = "[Ofis · sistem]\n"
TIER_NAME = re.compile(r"[a-z0-9-]{1,40}")
DIRECTION_TR = {"asagi": "daha ucuz modele", "yukari": "daha güçlü modele"}
MAX_LINKS = 20
REMIND_AFTER = timedelta(days=3)  # a model card unanswered / a pilot job not started: the first reminder
REMIND_EVERY = timedelta(days=7)  # then at most one reminder per this while it stays so
HISTORY_KEEP = 50


class Refused(ValueError):
    """A card that does not match the server state, an invalid key, a missing registry entry."""


def _stamp(now):
    return f"{now:%Y-%m-%dT%H:%M:%S}"


def _parse(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def settings(cfg):
    """ofis.json `model_onerisi` over DEFAULTS (a missing or invalid value keeps its default)."""
    given = (cfg or {}).get("model_onerisi")
    out = dict(DEFAULTS)
    if isinstance(given, dict):
        for key, default in DEFAULTS.items():
            value = given.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if key in INTEGER_SETTINGS:
                if int(value) == value and value >= 1:
                    out[key] = int(value)
            elif 0 <= value <= 1:
                out[key] = float(value)
    return out


def neighbour(model, direction):
    """The next cheaper (asagi) or stronger (yukari) model along MODEL_ORDER, or None."""
    if model not in MODEL_ORDER:
        return None
    i = MODEL_ORDER.index(model) + (-1 if direction == "asagi" else 1)
    return MODEL_ORDER[i] if 0 <= i < len(MODEL_ORDER) else None


# --- the effective mapping ---

def mapping(cfg):
    """[{proje, katman, model, effort, kaynak}] for every registered project × tier: kaynak `proje` (a per-project
    override in ofis.json) or `katman` (the global tiers)."""
    out = []
    tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
    for project in sorted((cfg.get("projects") or {})):
        if not launch.PROJECT_NAME.fullmatch(project):
            continue
        for tier in tiers:
            model, effort, source = launch.tier_entry(cfg, project, tier)
            out.append({"proje": project, "katman": tier, "model": model or "", "effort": effort or "",
                        "kaynak": source})
    return out


# --- measuring (pure) ---

def stem_of(row):
    link = re.fullmatch(r"\[\[(.+)\]\]", row.get("İş", ""))
    return link.group(1) if link else ""


def measure(rows, events, escalated):
    """The Ozet numbers of a set of Karne rows (karne._measure) plus the escalations (jobs moved one tier up)."""
    m = karne._measure(rows, events)
    m["yukseltme"] = sum(1 for r in rows if stem_of(r) in escalated)
    return m


def _ratio(hits, total):
    return hits / total if total else None


def verdict(m, model, s):
    """(yon, target model, reason) or None, for the measured rows of one project × tier × model."""
    if m["ilk_tur_olculen"] < s["min_is"]:
        return None
    first = _ratio(m["ilk_tur_gecen"], m["ilk_tur_olculen"])
    rework = _ratio(m["yeniden_is"], m["is_sayisi"]) or 0.0
    escalation = _ratio(m["yukseltme"], m["is_sayisi"]) or 0.0
    down, up = neighbour(model, "asagi"), neighbour(model, "yukari")
    if first >= s["asagi_ilk_tur"] and rework <= s["asagi_yeniden_is"] and m["yukseltme"] == 0 and down:
        return "asagi", down, (f"ilk turda geçme %{round(100 * first)} (eşik %{round(100 * s['asagi_ilk_tur'])}), "
                               f"yeniden iş %{round(100 * rework)} (eşik %{round(100 * s['asagi_yeniden_is'])}), "
                               "yükseltme yok")
    if (first < s["yukari_ilk_tur"] or escalation >= s["yukari_yukseltme"]) and up:
        parts = []
        if first < s["yukari_ilk_tur"]:
            parts.append(f"ilk turda geçme %{round(100 * first)} (eşik %{round(100 * s['yukari_ilk_tur'])} altı)")
        if escalation >= s["yukari_yukseltme"]:
            parts.append(f"yükseltme oranı %{round(100 * escalation)} (eşik %{round(100 * s['yukari_yukseltme'])})")
        return "yukari", up, ", ".join(parts)
    return None


def baseline_rows(rows, project, tier, model, source_of):
    """The rows that count as evidence for a project × tier: the current mapping's model, no explicit --model job,
    never a Codex review."""
    return [r for r in rows if r["Proje"] == project and r["Katman"] == tier and r["Model"] == model
            and model != "codex" and source_of(stem_of(r)) not in ("elle", "kota")]  # kota: a quota backup (Step 4)


def candidates(rows, events, escalated, source_of, current, s, blocked):
    """The proposals the rows support. current(project, tier) -> (model, effort) of the mapping; blocked(project,
    tier) -> True while a cycle is open or too few new rows came after the last one. Pure: no file access except
    through the callables."""
    out = []
    keys = sorted({(r["Proje"], r["Katman"]) for r in rows})
    for project, tier in keys:
        if not launch.PROJECT_NAME.fullmatch(project) or not TIER_NAME.fullmatch(tier) or blocked(project, tier):
            continue
        model, effort = current(project, tier)
        if not model or model not in MODEL_ORDER:
            continue
        evidence = baseline_rows(rows, project, tier, model, source_of)
        if not evidence:
            continue
        m = measure(evidence, events, escalated)
        found = verdict(m, model, s)
        if not found:
            continue
        direction, target, reason = found
        out.append({"proje": project, "katman": tier, "yon": direction, "mevcut_model": model,
                    "mevcut_effort": effort or "", "onerilen_model": target, "onerilen_effort": MODEL_EFFORT[target],
                    "kanit": {**_rounded(m), "isler": [stem_of(r) for r in evidence]}, "neden": reason})
    return out


def _rounded(m):
    return {k: round(v, 6) if isinstance(v, float) else v for k, v in m.items()}


def pilot_success(direction, m, s):
    """Did the pilot prove the proposal? Measured like the evidence: first-pass over the pilot jobs whose Kontrol ran
    (only jobs with a Kontrol take a pilot slot). Nothing measured proves nothing."""
    measured = m["ilk_tur_olculen"]
    if not measured:
        return False
    if direction == "asagi":
        return m["ilk_tur_gecen"] == measured and m["yukseltme"] == 0
    return m["ilk_tur_gecen"] / measured >= s["yukari_ilk_tur"]


# --- the state files ---

def _dir(durum_dir):
    return os.path.join(durum_dir, STATE_DIR)


def state_path(durum_dir, project, tier):
    if not launch.PROJECT_NAME.fullmatch(project or "") or not TIER_NAME.fullmatch(tier or ""):
        raise Refused(f"invalid project/tier: {project!r}/{tier!r}")
    return os.path.join(_dir(durum_dir), f"{project}__{tier}.json")


def load(durum_dir, project, tier):
    """The state of a project × tier ({"durum": "bos"} when none)."""
    p = state_path(durum_dir, project, tier)
    empty = {"proje": project, "katman": tier, "durum": "bos", "gecmis": [], "bildirilen": []}
    if os.path.islink(p) or not os.path.isfile(p):
        return empty
    try:
        with open(p, encoding="utf-8") as f:
            data = json.loads(f.read(256 * 1024))
    except (OSError, ValueError, UnicodeDecodeError):
        return empty
    if not isinstance(data, dict) or data.get("proje") != project or data.get("katman") != tier:
        return empty
    data.setdefault("gecmis", [])
    data.setdefault("bildirilen", [])
    return data


def save(durum_dir, state):
    p = state_path(durum_dir, state["proje"], state["katman"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    jobs._write_atomic(p, json.dumps(state, ensure_ascii=False, indent=1) + "\n")


def all_states(durum_dir):
    try:
        names = sorted(n for n in os.listdir(_dir(durum_dir)) if n.endswith(".json") and "__" in n
                       and not n.startswith("."))
    except OSError:
        return []
    out = []
    for n in names:
        project, _, tier = n[:-5].partition("__")
        try:
            data = load(durum_dir, project, tier)
        except Refused:
            continue
        if data.get("durum") != "bos" or data.get("gecmis"):
            out.append(data)
    return out


def _close(state, outcome, now, rows_now):
    """Ends the open cycle: history entry, the row count from which a new proposal is counted."""
    entry = {k: state.get(k, "") for k in ("kimlik", "yon", "mevcut_model", "onerilen_model", "oneri_notu",
                                           "sonuc_notu")}
    entry.update(sonuc=outcome, kapandi=_stamp(now))
    history = (state.get("gecmis") or []) + [entry]
    return {"proje": state["proje"], "katman": state["katman"], "durum": "bos", "kapanis_satir": rows_now,
            "kapandi": _stamp(now), "bildirilen": (state.get("bildirilen") or [])[-20:],
            "gecmis": history[-HISTORY_KEEP:]}


def rows_of(rows, project, tier):
    return sum(1 for r in rows if r["Proje"] == project and r["Katman"] == tier)


# --- the pilot (launch.create_job) ---

def pilot_slot(durum_dir, project, tier):
    """(kimlik, model, effort) when a pilot of this project × tier is running and still takes jobs, else None.
    Call under the job lock, then add_pilot_job() with the new job."""
    try:
        state = load(durum_dir, project, tier)
    except Refused:
        return None
    if state.get("durum") != "pilot" or len(state.get("pilot_isler") or []) >= int(state.get("pilot_is") or 0):
        return None
    return state["kimlik"], state["onerilen_model"], state.get("onerilen_effort") or None


def add_pilot_job(durum_dir, project, tier, kimlik, job_name):
    state = load(durum_dir, project, tier)
    if state.get("durum") != "pilot" or state.get("kimlik") != kimlik:
        raise Refused(f"no running pilot {kimlik}")
    state["pilot_isler"] = (state.get("pilot_isler") or []) + [jobs.check_name(job_name)]
    save(durum_dir, state)


# --- ofis.json and Degisiklikler.md ---

def set_override(config_path, project, tier, model, effort):
    """Writes projects.<project>.tiers.<tier> = {model, effort} into ofis.json: only that entry changes (key order
    kept), through bin/ayarlar.py yaz (atomic replace under the job lock)."""
    def change(data):
        entry = (data.get("projects") or {}).get(project)
        if not isinstance(entry, dict):
            raise Refused(f"'{project}' is not in the ofis.json registry")
        tiers = entry.get("tiers")
        if not isinstance(tiers, dict):
            tiers = entry["tiers"] = {}
        tiers[tier] = {"model": model, "effort": effort}
    return ayarlar.yaz(config_path, change)


CHANGES_HEAD = ("Tarih", "Değişiklik (eski → yeni)", "Gerekçe", "Karar")


def changes_ready(vault):
    """Raises Refused/OSError unless OFIS/Karne/Degisiklikler.md exists (created when missing) as a plain, writable
    file: checked before ofis.json changes."""
    path = os.path.join(vault, karne.FOLDER, karne.CHANGES)
    karne.ensure_changes_file(vault)
    if os.path.islink(path) or not os.path.isfile(path):
        raise Refused("Karne/Degisiklikler.md is not a plain file; the mapping was not changed")
    if not os.access(path, os.W_OK):
        raise Refused("Karne/Degisiklikler.md is not writable; the mapping was not changed")


def record_change(vault, now, project, tier, old, new, reason, note):
    """Appends one row to OFIS/Karne/Degisiklikler.md (created with its header when missing; the header is appended
    when the file has none). Existing rows are never rewritten; a row for the same decision note is not added again."""
    path = os.path.join(vault, karne.FOLDER, karne.CHANGES)
    karne.ensure_changes_file(vault)
    if os.path.islink(path) or not os.path.isfile(path):
        raise Refused("Karne/Degisiklikler.md is not a plain file")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    link = f"[[{note[:-3] if note.endswith('.md') else note}]]"
    if link in text:
        return False
    head = karne._table_head(CHANGES_HEAD)
    if head.splitlines()[0] not in text:
        text = (text if text.endswith("\n") else text + "\n") + "\n" + head
    text = text if text.endswith("\n") else text + "\n"
    cells = (f"{now:%Y-%m-%d}", f"{project} · {tier}: {old} → {new}", reason, link)
    karne._write(path, text + "| " + " | ".join(karne._cell(c) for c in cells) + " |\n")
    return True


def refresh_overrides(cfg, config_path, seen=None):
    """Takes a changed ofis.json into the running server's cfg (ofis.py cevapla and the Ayarlar page change the file):
    the projects (new, changed, removed — bin/ayarlar.py tazele keeps a removed one with open work), the free
    reviewers' list, the office name and the advisor keys. Other keys stay as the server started. Returns the file's
    mtime (pass it back as seen: an unchanged file is not read again). The server itself uses ayarlar.Yenileyici."""
    try:
        mtime = os.stat(config_path).st_mtime_ns
    except OSError:
        return seen
    if mtime == seen:
        return seen
    try:
        with open(config_path, encoding="utf-8") as f:
            fresh = json.load(f)
    except (OSError, ValueError):
        return seen
    if isinstance(fresh, dict) and isinstance(fresh.get("projects"), dict):
        ayarlar.tazele(cfg, fresh)
    return mtime


# --- the cards ---

def _note_name(vault, now, project, tier, kind):
    folder = os.path.join(vault, "Kararlar")
    base = f"{now:%Y-%m-%d}-{project}-{tier}-{kind}"
    for suffix in [""] + [f"-{i}" for i in range(2, 100)]:
        name = f"{base}{suffix}.md"
        if not os.path.lexists(os.path.join(folder, name)):
            return name
    raise Refused("no free decision note name")


def _write_note(vault, name, text):
    folder = os.path.join(vault, "Kararlar")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if os.path.islink(path) or (os.path.lexists(path) and not os.path.isfile(path)):
        raise Refused(f"Kararlar/{name} is not a plain file")
    jobs._write_atomic(path, text)


def _pct(hits, total):
    return f"%{round(100 * hits / total)} ({hits}/{total})" if total else "—"


def _usd(value):
    return "—" if value is None else f"${value:.4f}"


def _spend(m):
    """The verified cost per job with its token twin ("$0.2700 · 182 bin token"); evidence stored before tokens, or
    with unknown tokens, shows the dollars alone (never "0 token")."""
    value = _usd(m.get("dogrulanmis_is_basina_usd"))
    tokens = budget.token_text(m.get("dogrulanmis_is_basina_token"))
    if value == "—":
        return value
    return f"{tokens} · API karşılığı ~{value}" if tokens else f"API karşılığı ~{value}"


def evidence_lines(m):
    return [f"- İş sayısı: {m['is_sayisi']} (kontrolü çalışan: {m['ilk_tur_olculen']})",
            f"- Kontrol ilk turda geçme: {_pct(m['ilk_tur_gecen'], m['ilk_tur_olculen'])}",
            f"- Yeniden iş oranı: {_pct(m['yeniden_is'], m['is_sayisi'])}",
            f"- Bir üst katmana taşınan: {m['yukseltme']}/{m['is_sayisi']}",
            f"- Doğrulanmış iş başına kullanım: {_spend(m)}"]


def _links(stems):
    shown = [f"[[{s}]]" for s in stems[:MAX_LINKS] if s]
    more = len(stems) - len(shown)
    return ", ".join(shown) + (f" ve {more} iş daha" if more > 0 else "") if shown else "(yok)"


def _frontmatter(project, kind, state, now, extra=()):
    lines = [f"tags: [ofis, karar, {project}]"]
    for key, value in (("proje", project), ("durum", "bekliyor"), ("tur", kind), ("katman", state["katman"]),
                       ("mevcut_model", state["mevcut_model"]), ("onerilen_model", state["onerilen_model"]),
                       ("yon", state["yon"]), ("pilot", state["kimlik"]), *extra, ("soruldu", _stamp(now))):
        jobs._set_line(lines, key, value)
    return lines


def who(model):
    """Office vocabulary for the owner (2026-11-11): "sonnet" -> "Uzman (Sonnet)"; an unknown id as it is."""
    model = str(model or "")
    fam = next((f for f in karne.ROLES if f in model.lower()), "")
    return f"{karne.ROLES[fam]} ({model[:1].upper()}{model[1:]})" if fam else model


def proposal_card(state, now, s):
    """The text of a proposal card (tur: model-onerisi). Display text names workers by role (who); the frontmatter
    keeps the model ids."""
    p, t, n = state["proje"], state["katman"], s["pilot_is"]
    cur, to = who(state["mevcut_model"]), who(state["onerilen_model"])
    m = state["kanit"]
    body = (f"# {p} — Kadro önerisi: {t} işler ({cur} → {to})\n\n"
            f"## Soru\n{p}'de {t} işler için sonraki {n} iş {cur} yerine {to} ile denensin mi? \"Evet\" yazarsan "
            "deneme (pilot) başlar; başka bir şey yazarsan öneri kapanır ve bir süre yeniden sorulmaz.\n\n"
            f"## Kanıt\nKarne satırları ({t} · {cur}; çalışanı elle seçilen işler sayılmadı). Öneri yönü: "
            f"{DIRECTION_TR[state['yon']]}. Neden: {state['neden']}.\n\n" + "\n".join(evidence_lines(m)) +
            f"\n- İşler: {_links(m.get('isler') or [])}\n\n"
            f"## Ne olur\nOnaylarsan {p}'de eklenen sonraki {n} {t} iş (çalışanı elle seçilmeyenler) {to} / "
            f"{state['onerilen_effort']} ile çalışır. Kontrol ve yükseltme kuralları aynen geçerli. Eşleme şimdilik "
            f"değişmez: {n} iş bitince sunucu sonuçları bu kanıtla karşılaştırır ve ayrı bir kartla sorar.\n\n"
            "## İlgili Sayfalar\n- [[Ozet]]\n- [[OFIS/README]]\n")
    return jobs.render(_frontmatter(p, PROPOSAL, state, now), body)


def result_card(state, now, s):
    """The text of a pilot result card (tur: model-pilot-sonucu); workers by role (who)."""
    p, t = state["proje"], state["katman"]
    cur, to = who(state["mevcut_model"]), who(state["onerilen_model"])
    base, pilot, ok = state["kanit"], state["sonuc"], state["basari"]
    rows = [("İş sayısı (kontrolü çalışan)", f"{base['is_sayisi']} ({base['ilk_tur_olculen']})",
             f"{pilot['is_sayisi']} ({pilot['ilk_tur_olculen']})"),
            ("Kontrol ilk turda geçme", _pct(base["ilk_tur_gecen"], base["ilk_tur_olculen"]),
             _pct(pilot["ilk_tur_gecen"], pilot["ilk_tur_olculen"])),
            ("Yeniden iş", _pct(base["yeniden_is"], base["is_sayisi"]), _pct(pilot["yeniden_is"], pilot["is_sayisi"])),
            ("Bir üst katmana taşınan", f"{base['yukseltme']}/{base['is_sayisi']}",
             f"{pilot['yukseltme']}/{pilot['is_sayisi']}"),
            ("Doğrulanmış iş başına kullanım", _spend(base), _spend(pilot))]
    table = karne._table_head(("Ölçüt", f"Önceki ({cur})", f"Pilot ({to})")) + \
        "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    rule = ("kontrolü çalışan her pilot işte kontrol ilk turda geçmeli ve hiçbir iş bir üst katmana taşınmamalı"
            if state["yon"] == "asagi" else
            f"kontrolü çalışan pilot işlerde ilk turda geçme oranı en az %{round(100 * s['yukari_ilk_tur'])} olmalı")
    if ok:
        question = (f"Eşleme değişsin mi: {p} {t} → {to}? \"Evet\" yazarsan {p}'de bundan sonraki {t} işler "
                    f"{to} / {state['onerilen_effort']} ile çalışır; başka bir şey yazarsan eşleme {cur} olarak kalır.")
        advice = f"Pilot başarılı ({rule}). Eşlemenin {cur} → {to} olarak değişmesini öneriyorum."
        then = (f"Onaylarsan sunucu `ofis.json`'da {p} için {t} katmanını {to} / {state['onerilen_effort']} yapar ve "
                "[[Degisiklikler]] notuna bir satır ekler. Çalışanı elle seçilen işler etkilenmez. Geri dönüş otomatik "
                "değildir: karne kötüleşirse yeni bir öneri gelir.")
    else:
        question = (f"Pilot öneriyi kanıtlamadı; eşleme değişmeyecek ({p} {t} → {cur} kalır). Bu kartı kapatmak "
                    "için \"tamam\" yazman yeterli; ne yazarsan yaz bir şey değişmez.")
        advice = f"Pilot kanıtlamadı ({rule}). Eşleme değişmesin."
        then = f"Hiçbir şey değişmez: {p}'de {t} işler {cur} ile çalışmaya devam eder."
    body = (f"# {p} — Kadro denemesi sonucu: {t} işler ({cur} → {to})\n\n"
            f"## Soru\n{question}\n\n"
            f"## Karşılaştırma\nÖnceki: önerinin kanıtı ([[{state['oneri_notu'][:-3]}]]). Pilot: "
            f"{_links([jobs.stem(n) for n in state.get('pilot_isler') or []])}.\n\n{table}\n\n"
            f"## Öneri\n{advice}\n\n"
            f"## Ne olur\n{then}\n\n"
            f"## İlgili Sayfalar\n- [[{state['oneri_notu'][:-3]}]]\n- [[Ozet]]\n- [[OFIS/README]]\n")
    return jobs.render(_frontmatter(p, RESULT, state, now, (("basari", "evet" if ok else "hayır"),)), body)


def proposal_notice(state, s):
    return (f"{SYSTEM_PREFIX}{state['proje']} kadro önerisi: {state['katman']} işler için sonraki {s['pilot_is']} iş "
            f"{who(state['mevcut_model'])} yerine {who(state['onerilen_model'])} ile denensin mi? Karar kartı: "
            f"[[{state['oneri_notu'][:-3]}]] (kanıt kartta). {sahip.e()} tek satırla sor; cevabını `ofis.py cevapla` ile "
            "ilet.")


def result_notice(state):
    outcome = ("Pilot başarılı; eşleme değişikliği soruluyor" if state["basari"] else
               "Pilot kanıtlamadı; eşleme değişmeyecek, kart yalnızca kapatılacak")
    return (f"{SYSTEM_PREFIX}{state['proje']} kadro denemesi bitti: {state['katman']} işler {who(state['onerilen_model'])} "
            f"ile ({len(state.get('pilot_isler') or [])} iş). {outcome}. Karar kartı: "
            f"[[{state['sonuc_notu'][:-3]}]]. {sahip.e()} tek satırla bildir; cevabını `ofis.py cevapla` ile ilet.")


# --- the server pass ---

def escalated_jobs(vault):
    """Job stems that were moved one tier up (the `yukseltme` correction events)."""
    return {e["is"] for e in karne.corrections(vault) if e["tur"] == "yukseltme"}


def settled(durum_dir, job):
    """A pilot job whose outcome can no longer change: final, its Karne row written, and — for a workflow step
    (server record `akis`) that ended `bitti` — its workflow closed (approved, cancelled or handed to the CEO),
    because a code review's DÜZELT reopens a `bitti` kod step (which may then fail or escalate). A step that
    ended tikandi / iptal / basarisiz is never reopened by its workflow. Shared with bin/danisman.py."""
    if job.meta.get("durum") not in jobs.FINAL_STATUSES or job.meta.get("karne") == "bekliyor":
        return False
    grup = records.server_value(durum_dir, job.name, "akis")
    if grup and job.meta.get("durum") == "bitti":
        flow = rapor._workflow(durum_dir, grup)
        return flow is None or flow.get("durum") in rapor.WORKFLOW_CLOSED  # no state: nothing can reopen it
    return True


class Advisor:
    """Runs in the post office thread after the Karne rows are written (process_karne): finished pilots get their
    result card, the rows' new proposals their card, every open card its one notice."""

    def __init__(self, cfg, durum_dir, ceo, now=datetime.now, log=None):
        self.cfg = cfg
        self.vault = os.path.expanduser(cfg["vault_ofis"])
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.now = now
        self.log = log or (lambda text: None)

    def _source(self, stem):
        try:
            return records.server_value(self.durum_dir, stem + ".md", "model_kaynagi")
        except jobs.JobError:
            return ""

    def check(self):
        """One pass. Returns {"oneriler": [notes written], "sonuclar": [notes written]}."""
        s = settings(self.cfg)
        written = {"oneriler": [], "sonuclar": []}
        with jobs.locked(self.vault):
            every = karne._rows(self.vault)
            rows = karne.counted(every)  # self-test rows (Deneme) are never evidence
            events = karne._rework_events(self.vault)
            escalated = escalated_jobs(self.vault)
            for state in all_states(self.durum_dir):
                if state.get("durum") == "pilot":
                    state = self._free_slots(state)
                    # a pilot is measured from all its own rows: a pilot job never leaves its measurement
                    note = self._finish_pilot(state, every, events, escalated, s)
                    if note:
                        written["sonuclar"].append(note)

            def blocked(project, tier):
                state = load(self.durum_dir, project, tier)
                if state.get("durum") in OPEN:
                    return True
                if "kapanis_satir" in state:
                    # kapanis_satir counts every row (self-tests too): the same basis here
                    return rows_of(every, project, tier) - int(state.get("kapanis_satir") or 0) < s["yeniden_oneri_is"]
                return False

            def current(project, tier):
                if project not in (self.cfg.get("projects") or {}):
                    return None, None
                model, effort, _ = launch.tier_entry(self.cfg, project, tier)
                return model, effort

            for c in candidates(rows, events, escalated, self._source, current, s, blocked):
                written["oneriler"].append(self._propose(c, s))
            self._repair_cards(s)
        self._notify(s)
        self._remind()
        return written

    def _free_slots(self, state):
        """A pilot job cancelled before it ever started (iptal without baslangic: ofis.py iptal, akis-karar iptal, a
        step cancelled right after it was written) gives its slot back."""
        names = state.get("pilot_isler") or []
        keep = []
        for name in names:
            job = jobs.find(self.vault, name)
            if job is not None and job.meta.get("durum") == "iptal" and not job.meta.get("baslangic"):
                self.log(f"model pilot {state['kimlik']}: {name} was cancelled before it started; slot freed")
                continue
            if records.server_value(self.durum_dir, name, "model_kaynagi") == "kota":
                # started with the quota backup (bin/dispatcher.py): it never measures the pilot model
                self.log(f"model pilot {state['kimlik']}: {name} ran with a quota backup; slot freed")
                continue
            keep.append(name)
        if keep != names:
            state["pilot_isler"] = keep
            save(self.durum_dir, state)
        return state

    def _card(self, state):
        """(note name, writer, asked time) of the state's open card, or None."""
        if state.get("durum") == "oneri":
            return state.get("oneri_notu"), proposal_card, state.get("oneri_tarihi")
        if state.get("durum") == "sonuc":
            return state.get("sonuc_notu"), result_card, state.get("sonuc_tarihi") or state.get("oneri_tarihi")
        return None

    def _card_path(self, note):
        return os.path.join(self.vault, "Kararlar", note) if note else ""

    def _repair_cards(self, s):
        """An open card whose note is missing (its write failed after the state was saved) is written again from the
        state; idempotent: an existing note is never touched."""
        for state in all_states(self.durum_dir):
            card = self._card(state)
            if not card or not card[0] or os.path.lexists(self._card_path(card[0])):
                continue
            note, writer, asked = card
            when = _parse(asked) or self.now()
            try:
                _write_note(self.vault, note, writer(state, when, s))
                self.log(f"model card {note} written again from the server state")
            except (OSError, Refused, KeyError) as e:
                self.log(f"model card {note} could not be written: {e}")

    def _propose(self, c, s):
        now = self.now()
        note = _note_name(self.vault, now, c["proje"], c["katman"], PROPOSAL)
        state = load(self.durum_dir, c["proje"], c["katman"])
        state.update(c, durum="oneri", kimlik=f"{c['proje']}-{c['katman']}-{now:%Y%m%d%H%M%S}-{len(state.get('gecmis') or []) + 1}", oneri_notu=note,
                     oneri_tarihi=_stamp(now), pilot_is=s["pilot_is"], pilot_isler=[], sonuc_notu="", sonuc={},
                     basari=False)
        save(self.durum_dir, state)  # the state first: a crash before the note never proposes twice
        _write_note(self.vault, note, proposal_card(state, now, s))
        self.log(f"model proposal {state['kimlik']}: {c['mevcut_model']} → {c['onerilen_model']} ({note})")
        return note

    def _settled(self, job):
        return settled(self.durum_dir, job)

    def _finish_pilot(self, state, rows, events, escalated, s):
        names = state.get("pilot_isler") or []
        if len(names) < int(state.get("pilot_is") or 0):
            return None
        for name in names:
            job = jobs.find(self.vault, name)
            if job is not None and not self._settled(job):
                return None
        stems = {jobs.stem(n) for n in names}
        pilot_rows = [r for r in rows if stem_of(r) in stems]
        m = measure(pilot_rows, events, escalated)
        now = self.now()
        state["sonuc"] = {**_rounded(m), "pilot_is": len(names)}
        state["basari"] = pilot_success(state["yon"], m, s)
        state["sonuc_notu"] = _note_name(self.vault, now, state["proje"], state["katman"], RESULT)
        state["sonuc_tarihi"] = _stamp(now)
        state["durum"] = "sonuc"
        save(self.durum_dir, state)
        _write_note(self.vault, state["sonuc_notu"], result_card(state, now, s))
        self.log(f"model pilot {state['kimlik']} finished ({'success' if state['basari'] else 'not proven'})")
        return state["sonuc_notu"]

    def _notify(self, s):
        for state in all_states(self.durum_dir):
            card = self._card(state)
            if card and not os.path.isfile(self._card_path(card[0])):
                continue  # never a notice that links a missing card; the next pass writes it again
            if state.get("durum") == "oneri":
                key, text = f"model-onerisi-{state['kimlik']}", proposal_notice(state, s)
            elif state.get("durum") == "sonuc":
                key, text = f"model-pilot-sonucu-{state['kimlik']}", result_notice(state)
            else:
                continue
            if key in (state.get("bildirilen") or []):
                continue
            self.ceo.enqueue(text, key)  # the channel never queues a key twice either
            with jobs.locked(self.vault):
                fresh = load(self.durum_dir, state["proje"], state["katman"])
                fresh["bildirilen"] = ((fresh.get("bildirilen") or []) + [key])[-20:]
                save(self.durum_dir, fresh)


    def _remind(self):
        """Reminders (the owner's request): a model card still `bekliyor` REMIND_AFTER after it was asked, and a pilot job
        still queued (never started: held or blocked) REMIND_AFTER after it was added, get one CEO notice, then at
        most one every REMIND_EVERY while it stays so. The sent reminders are kept in the state (hatirlatma), so a
        restart sends nothing twice; a card is never closed by this."""
        now = self.now()
        for state in all_states(self.durum_dir):
            due = []
            card = self._card(state)
            if card and os.path.isfile(self._card_path(card[0])):
                note, _, asked = card
                due.append((note, _parse(asked), lambda days, note=note: (
                    f"{SYSTEM_PREFIX}{state['proje']} kadro kararı {days} gündür cevap bekliyor: [[{note[:-3]}]] "
                    f"({state['katman']} · {who(state['mevcut_model'])} → {who(state['onerilen_model'])}). {sahip.e()} tek satırla "
                    "hatırlat; kart kendiliğinden kapanmaz.")))
            if state.get("durum") == "pilot":
                for name in state.get("pilot_isler") or []:
                    job = jobs.find(self.vault, name)
                    if job is None or job.meta.get("durum") != "sirada":
                        continue
                    due.append((name, _parse(job.meta.get("olusturuldu")), lambda days, name=name: (
                        f"{SYSTEM_PREFIX}{state['proje']} model denemesinin işi {days} gündür başlamadı: "
                        f"[[{jobs.stem(name)}]] (sırada; bekletiliyor ya da bir bağımlılığa takılı). Deneme "
                        f"({state['katman']} · {state['onerilen_model']}) bu iş bitmeden sonuçlanmaz; {sahip.e()} tek "
                        "satırla bildir.")))
            for ref, since, text in due:
                if since is None or now - since < REMIND_AFTER:
                    continue
                sent = (state.get("hatirlatma") or {}).get(ref) or {}
                last = _parse(sent.get("son"))
                if last is not None and now - last < REMIND_EVERY:
                    continue
                count = int(sent.get("sayi") or 0) + 1
                self.ceo.enqueue(text((now - since).days), f"model-hatirlatma-{state['kimlik']}-{jobs.stem(ref)}-{count}")
                with jobs.locked(self.vault):
                    fresh = load(self.durum_dir, state["proje"], state["katman"])
                    if fresh.get("kimlik") != state.get("kimlik"):
                        continue
                    reminders = fresh.get("hatirlatma") if isinstance(fresh.get("hatirlatma"), dict) else {}
                    reminders[ref] = {"son": _stamp(now), "sayi": count}
                    fresh["hatirlatma"] = reminders
                    save(self.durum_dir, fresh)
                    state = fresh


# --- the owner's answer (ofis.py cevapla, under the job lock) ---

def answer(cfg, durum_dir, note, meta, text, now, approved, config_path=None):
    """Applies the owner's answer to a model card. Checks the card against the server state first (Refused when they do
    not match). Returns a dict for the CEO."""
    vault = os.path.expanduser(cfg["vault_ofis"])
    kind = meta.get("tur")
    try:
        state = load(durum_dir, meta.get("proje") or "", meta.get("katman") or "")
    except Refused:
        raise Refused(f"{note}: bu model kartı sunucu kaydıyla uyuşmuyor; cevap işlenmedi") from None
    expected = ("oneri", "oneri_notu") if kind == PROPOSAL else ("sonuc", "sonuc_notu")
    if state.get("durum") != expected[0] or state.get(expected[1]) != note or meta.get("pilot") != state.get("kimlik"):
        raise Refused(f"{note}: bu model kartı sunucu kaydıyla uyuşmuyor; cevap işlenmedi")
    project, tier = state["proje"], state["katman"]
    rows_now = rows_of(karne._rows(vault), project, tier)
    out = {"tur": kind, "onay": approved, "proje": project, "katman": tier}
    if kind == PROPOSAL:
        if approved:
            state.update(durum="pilot", pilot_baslangic=_stamp(now), pilot_isler=[])
            save(durum_dir, state)
            out.update(pilot=state["kimlik"], model=state["onerilen_model"], pilot_is=state["pilot_is"])
        else:
            save(durum_dir, _close(state, "reddedildi", now, rows_now))
            out["pilot"] = ""
        return out
    changed = False
    if approved and state.get("basari"):
        if not config_path:
            raise Refused("the ofis.json path is unknown; the mapping was not changed")
        changes_ready(vault)  # before ofis.json: a Degisiklikler.md that cannot be written refuses the whole change
        set_override(config_path, project, tier, state["onerilen_model"], state["onerilen_effort"])
        entry = (cfg.get("projects") or {}).get(project)
        if isinstance(entry, dict):  # this process too
            entry.setdefault("tiers", {})[tier] = {"model": state["onerilen_model"],
                                                   "effort": state["onerilen_effort"]}
        base = state["kanit"]
        pilot = state["sonuc"]
        reason = (f"Pilot {pilot['pilot_is']} iş: ilk turda geçme "
                  f"{_pct(pilot['ilk_tur_gecen'], pilot['ilk_tur_olculen'])}, "
                  f"yükseltme {pilot['yukseltme']}; önceki {base['is_sayisi']} iş: ilk turda geçme "
                  f"{_pct(base['ilk_tur_gecen'], base['ilk_tur_olculen'])}, yükseltme {base['yukseltme']}")
        changed = True
        try:  # the mapping changed: from here on a failure is a warning, never REFUSED
            record_change(vault, now, project, tier, f"{state['mevcut_model']}/{state.get('mevcut_effort') or '-'}",
                          f"{state['onerilen_model']}/{state['onerilen_effort']}", reason, note)
        except (OSError, Refused) as e:
            out["uyari"] = (f"eşleme değişti ama Karne/Degisiklikler.md satırı yazılamadı ({type(e).__name__}: {e}); "
                            "satır eksik")
    save(durum_dir, _close(state, "eslesme-degisti" if changed else "degismedi", now, rows_now))
    out.update(eslesme_degisti=changed, model=state["onerilen_model"] if changed else state["mevcut_model"])
    return out


# --- read-only views (ofis.py modeller, GET /api/kalite) ---

def page(cfg, durum_dir):
    """{eslesme, pilotlar, oneriler, danisman} for the Kalite view and `ofis.py modeller`."""
    vault = os.path.expanduser(cfg["vault_ofis"])
    pilots, cards = [], []
    for state in all_states(durum_dir):
        if state.get("durum") == "pilot":
            names = state.get("pilot_isler") or []
            done = 0
            for name in names:
                job = jobs.find(vault, name)
                if job is None or job.meta.get("durum") in jobs.FINAL_STATUSES:
                    done += 1
            pilots.append({"proje": state["proje"], "katman": state["katman"], "kimlik": state["kimlik"],
                           "yon": state["yon"], "mevcut_model": state["mevcut_model"],
                           "model": state["onerilen_model"], "effort": state.get("onerilen_effort", ""),
                           "eklenen": len(names), "biten": done, "toplam": int(state.get("pilot_is") or 0)})
        elif state.get("durum") in ("oneri", "sonuc"):
            cards.append({"proje": state["proje"], "katman": state["katman"], "kimlik": state["kimlik"],
                          "tur": PROPOSAL if state["durum"] == "oneri" else RESULT, "yon": state["yon"],
                          "mevcut_model": state["mevcut_model"], "model": state["onerilen_model"],
                          "not": state["oneri_notu"] if state["durum"] == "oneri" else state["sonuc_notu"],
                          "basari": bool(state.get("basari")) if state["durum"] == "sonuc" else None,
                          "pilot_is": int(state.get("pilot_is") or 0)})
    import danisman  # imports this module
    return {"eslesme": mapping(cfg), "pilotlar": pilots, "oneriler": cards,
            "danisman": danisman.page(cfg, durum_dir)}  # the advisor pilot (None while nothing ever happened)


def table(cfg, durum_dir):
    """The text of `ofis.py modeller`."""
    data = page(cfg, durum_dir)
    lines = ["EŞLEME (proje · katman → model / effort; kaynak: proje = projeye özel, katman = genel tablo)"]
    for e in data["eslesme"]:
        lines.append(f"  {e['proje']} · {e['katman']} → {e['model'] or '-'} / {e['effort'] or '-'} ({e['kaynak']})")
    lines.append("PİLOTLAR")
    for p in data["pilotlar"]:
        lines.append(f"  {p['proje']} · {p['katman']}: {p['mevcut_model']} → {p['model']} ({p['yon']}), "
                     f"{p['eklenen']}/{p['toplam']} iş eklendi, {p['biten']} bitti [{p['kimlik']}]")
    if not data["pilotlar"]:
        lines.append("  (yok)")
    lines.append("AÇIK KARTLAR")
    for c in data["oneriler"]:
        what = "öneri" if c["tur"] == PROPOSAL else ("pilot sonucu: " + ("başarılı" if c["basari"] else "kanıtlamadı"))
        lines.append(f"  {c['proje']} · {c['katman']}: {c['mevcut_model']} → {c['model']} ({what}) "
                     f"[[{c['not'][:-3]}]]")
    if not data["oneriler"]:
        lines.append("  (yok)")
    import danisman  # imports this module
    return "\n".join(lines) + "\n" + danisman.table(cfg, durum_dir)
