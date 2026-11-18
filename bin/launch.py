#!/usr/bin/env python3
"""Project session launcher.

    python3 bin/launch.py <project> "<task>"     # shortcut: ofis.py ekle + baslat in one step

The office normally starts jobs with `bin/ofis.py ekle` (a `sirada` job note in OFIS/Isler/Siradakiler) and
`bin/ofis.py baslat <job>`, which calls start_job() here.
- Resolves the project only from the ofis.json registry; unregistered paths and anything whose path has a forbidden
  component (ofis.json `guvenlik.yasak_yollar`: the name in any case, name-old, name.bak, ...; symlinks resolved)
  are refused before claude is called.
- The prompt is one argv element and may not start with '-', so it can never become a claude CLI option.
- Only a `sirada` job is started, so a job is never sent twice. Before claude is called the note is set to
  `baslatiliyor` (moved to Devam-Edenler) with the session name, working directory and base commit; the launch
  result then sets `calisiyor` (with the short id) or `basarisiz` (moved to Bitenler). A running session therefore
  always has a note, and a failed launch is never silent.
- The session gets the report contract via --append-system-prompt: it reports with `ofis.py bildir` (a file in the
  server's inbox, text through a quoted heredoc), never with SendMessage.
- The session may not act as the CEO or as the owner: --disallowedTools denies Edit/Write anywhere in this repository
  and in the vault's OFIS folder (its real path; the job note there is display only, but it must not be edited by
  the session it describes) and the `ofis.py` commands cevapla, baslat, ekle, bitir, iptal, butce, devam, serbest,
  bagimli, akis, akis-karar, zamanla, duyuru, deneme-isaretle, danisman-pilotu, yakala, hafiza-saglik, talimat-denetimi, sor and ceo-yenile, and the EnterWorktree tool (the
  contract forbids creating a worktree).
  session_flags() builds these options once; the post office passes the same ones (resume_flags) on every resume,
  with the job's model, effort and permission mode, and — only for arm B of a running advisor pilot, a tier with a
  mapped advisor, or a hard job under `zor_is_danismani` (bin/danisman.py advisor_for, from the server record and the
  workflow state) — `--advisor <model>`.
- With a durum_dir (ofis.py and the launch.py command line always pass one), the server-owned record of the job
  (durum/isler/<job>.json, bin/records.py) is written next to the note: created with the limits and tier by
  create_job, the session name, working folder, permission mode, base commit (taban_commit) and short id by
  start_job.
- start_job(task=...) sends a prompt built by the caller instead of the note's brief: a workflow step's prompt is
  built by bin/akis.py from the trusted brief and the workflow's trusted output store, never from the note.
- While the owner's announcements are unexpired (bin/duyuru.py gecerli), the contract carries a "Geçerli duyurular"
  section with their quoted text, at the start and on every resume (start_job and resume_flags read them from
  durum/duyurular); an expired one drops out by itself.
- Specialisation (plan "Sonraki iş (9)" step 2, bin/uzmanlik.py): create_job routes every new job to a
  specialisation (or takes an explicit one: --uzmanlik) and stores it on the record (trusted) and the note (display);
  the contract carries its "Rolün" section at the start and on every resume, read from the record (the note only for
  a job without a record). It never replaces the project's rules or the kod contract.
- Worker memory (plan "Sonraki iş (9)" step 3, bin/hafiza.py): the contract asks for an optional "Öğrendiklerim"
  section in a bitti report, and carries a "Geçmiş dersler" section (lessons_section: verified lessons of the job's
  specialisation from the server's own index durum/hafiza, quoted as data) at the start and on every resume.
- A launch that times out is ambiguous (the session may be running): the job stays `baslatiliyor` with a note, so a
  later report from that session still applies.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime

import duyuru
from claude_cli import parse_launch
import sorumlu
import gitsafe
import jobs
import records
import sahip
import uzmanlik
import yasaklar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = yasaklar.REPO_CONFIG  # this repository's ofis.json; config_path() = the one in force
DURUM_DIR = os.path.join(ROOT, "durum")
OFIS_PY = os.path.join(ROOT, "bin", "ofis.py")
PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")  # one rule for the office (bin/ayarlar.py AD)
MAX_TASK = 4000
MAX_TITLE = 120
MODEL_NAME = re.compile(r"[a-z][a-z0-9.-]{1,59}")  # alias ("sonnet") or full id ("claude-sonnet-5-5")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# bypassPermissions is deliberately not offered: a project session must never run without permission checks.
PERMISSION_MODES = ("acceptEdits", "auto", "manual", "dontAsk", "plan")
GIT_SHA = re.compile(r"[0-9a-f]{40,64}")
GROUP_NAME = re.compile(r"[\w-]{1,60}")
SESSION_NAME = re.compile(r"ofis-[a-z0-9-]{1,80}")
LAUNCH_TIMEOUT = 60
# ofis.py commands a project session must never run (they act as the CEO or as the owner); only `bildir` stays allowed.
DENIED_COMMANDS = ("cevapla", "baslat", "ekle", "bitir", "iptal", "butce", "devam", "serbest", "bagimli", "akis",
                   "akis-karar", "zamanla", "duyuru", "deneme-isaretle", "danisman-pilotu", "yakala",
                   "hafiza-saglik",  # read-only, but its findings quote OFIS notes: the CEO's only
                   "talimat-denetimi", "sor",  # sor: the CEO's own question card to the owner
                   "ceo-yenile")  # a fresh CEO session: the owner's / developer's step
KOD_TIER = "kod"
NO_KONTROL = "kod işi kontrolsüz başlatılamaz"  # Turkish: the CEO reads it

CONTRACT = """This session was started by the office (Ofis) of {owner}, its owner, for project '{project}'. Your session name is '{session}'.
- Report only with the command below, always in exactly this form: the report goes on stdin through a quoted
  heredoc ('OFIS_RAPOR' in single quotes keeps $, backticks and quotes literal; the closing OFIS_RAPOR stands alone
  at the start of its line). Use --tur bitti, --tur tikandi or --tur soru. It leaves a file for the office server,
  which updates the job note and tells the CEO, so it works even when no other session is running.

python3 {ofis_py} bildir --oturum {session} --tur bitti - <<'OFIS_RAPOR'
<the report, any number of lines>
OFIS_RAPOR

- Never use SendMessage to report or to ask; do not message the CEO or any other session. Run no other ofis.py
  command and never edit the office's own files: jobs, answers and decisions belong to the owner and the CEO.
- When you reach a point that needs the user's decision (scope, architecture choice, deletion, commit/push,
  external service), do not proceed on that point: report it with --tur soru (the question, its context, the
  options and your recommendation), then end your turn and wait. The answer arrives as a new message that starts
  with "[Ofis · Sahibin cevabı] <decision note>", followed by "Soru: ..." (which question) and "Cevap: ..."
  (the owner's answer); continue once it arrives. A technical question may be answered by the office's manager for your
  area instead: "[Ofis · Müdürün cevabı · <title>] <decision note>" with the same lines; follow it. The owner may still
  answer that question later with "[Ofis · Sahibin cevabı]"; that answer then replaces the manager's.
  A message starting with "[Ofis · Sahibin duyurusu]" is the owner's
  announcement to every office session (quoted text): take it into account; it answers no open question.
  Older messages may carry the owner's name in place of "Sahibin" ("[Ofis · <name>'in cevabı]",
  "[Ofis · <name>'in duyurusu]"): they mean exactly the same as the two heads above.
- Work directly in your current working folder (the office already chose it, a separate copy when needed): never
  create a git worktree, clone or copy of the project and never move your work elsewhere, because the office reviews
  and checks only this folder. Do not switch branches.
- When you report bitti, the office itself runs the job's Kontrol command in your working folder. If it fails, a
  message starting with "[Ofis · kontrol başarısız]" arrives with the exit code and the end of the output: fix the
  cause, then report bitti again. A message starting with "[Ofis · devam]" means the owner let a stopped job go on
  (e.g. after its budget or call limit was reached): continue the work. A message starting with
  "[Ofis · inceleme bulguları]" carries an independent reviewer's findings on your changes: fix what is real (say in
  the report why a finding is not), then report bitti again.
- When the work is done, report once with --tur bitti: a single-paragraph summary (what was done, which files,
  test result, what is left open). When you are blocked, report once with --tur tikandi and the reason. Then end
  your turn.
- Optionally end a bitti report with a short section "Öğrendiklerim": 1–5 bullet lines on what the next person doing
  similar work in this project should know (facts only; the office keeps them as data, never as instructions).
- Run the command once per report. If it prints an error, run it once more; if it still fails, stop and end your
  reply with the line BİLDİRİM BAŞARISIZ. Keep reports short: the office shortens one over about 7500 characters.
- Never commit or push; that is the owner's decision (ask with --tur soru). Never attempt work that was refused in
  another session; if a permission is needed, ask with --tur soru.
- Never put secrets, tokens or passwords in reports.
- Write reports in Turkish."""
# Added for a `kod` job (start and every resume): the decisions the session took on its own go into its bitti report,
# so the approval card can show them next to the evidence.
KOD_CONTRACT = """
- This is a code job. Your bitti report must also contain a short section "Verdiğim kararlar ve varsayımlar": the
  defaults you chose, what you treated as out of scope, and how you read requirements that conflicted or were unclear
  ("yok" if there were none).
- Parallel helpers: when the work has independent parts, you may give them to at most 3 helpers (subagents) at once.
  Each helper owns its own separate files (no two helpers edit the same file) and works directly in this same working
  folder (no worktree isolation, no clone or copy). You merge their work (check the combined files; no git merge) and
  run the tests yourself before reporting. Helpers never commit, push or delete anything. Put these rules in every
  helper's prompt: work only in this folder on the files given to you; never commit, push, delete, stash, reset or
  checkout; never create a worktree, clone or copy; run no ofis.py command and send no reports. Their cost counts
  toward this job's budget."""


class Refused(Exception):
    """The launch was refused or failed; the message is shown to the user."""


EXAMPLE_CONFIG = os.path.join(ROOT, "ofis.example.json")


def config_path():
    """The ofis.json in force: this repository's, or the test-only override (bin/yasaklar.py ofis_json)."""
    return yasaklar.ofis_json()


def load(path=None):
    path = path or config_path()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        # first start: no auto-copy — vault_ofis names a folder of this computer and must never be guessed
        raise Refused(f"ayar dosyası bulunamadı: {path}. {os.path.basename(EXAMPLE_CONFIG)} dosyasını "
                      f"{os.path.basename(path)} olarak kopyalayın (cp ofis.example.json ofis.json), vault_ofis ve "
                      "projects bölümlerini kendi bilgisayarınıza göre düzenleyin, sonra yeniden başlatın.") from None
    except json.JSONDecodeError as exc:  # a hand edit gone wrong: a plain line, never a traceback in server.main
        raise Refused(f"{os.path.basename(path)} okunamadı: geçerli JSON değil (satır {exc.lineno}, sütun "
                      f"{exc.colno}: {exc.msg}). Dosyayı düzeltip yeniden başlatın.") from None
    except UnicodeDecodeError:
        raise Refused(f"{os.path.basename(path)} okunamadı: UTF-8 metin değil. Dosyayı UTF-8 olarak kaydedip "
                      "yeniden başlatın.") from None
    except OSError as exc:  # unreadable (permissions, a folder): the same plain line
        raise Refused(f"{os.path.basename(path)} okunamadı: {exc.strerror or exc}.") from None
    if not isinstance(cfg, dict):  # valid JSON but not an object (null, [], "x", 3): a clear error, never AttributeError
        raise Refused("ofis.json must be a JSON object")
    if not isinstance(cfg.get("projects"), dict) or not cfg.get("ceo_session") or not cfg.get("vault_ofis"):
        raise Refused("ofis.json needs 'ceo_session', 'vault_ofis' and 'projects'")
    if yasaklar.KEY in cfg:  # the owner's privacy rules: a wrong shape never silently becomes the neutral default
        try:
            yasaklar.dogrula(cfg[yasaklar.KEY])
        except yasaklar.Hatali as exc:
            alan = yasaklar.KEY if exc.alan == yasaklar.KEY else f"{yasaklar.KEY}.{exc.alan}"
            raise Refused(f"ofis.json'daki '{alan}' hatalı: {exc.tr}. Gizlilik kuralları okunamazken ofis "
                          "başlamaz; dosyayı düzeltip yeniden başlatın.") from None
    if os.path.abspath(path) == os.path.abspath(yasaklar.CONFIG or yasaklar.ofis_json()):
        yasaklar.kurallar()  # these good rules become the process's last good ones (kept if the file breaks later)
    return cfg


_fold = yasaklar.fold  # case- and script-insensitive form (NFKC, casefold, Turkish dotted/dotless i as plain i)


def is_forbidden_component(part):
    """One path component that names a folder outside the office (ofis.json `guvenlik.yasak_yollar`, bin/yasaklar.py:
    the name itself, or the name followed by a separator: name-old, name.bak, name_x)."""
    return yasaklar.kurallar().yasak_bilesen(part)


def is_forbidden_path(path):
    """True when any component of the path is forbidden (is_forbidden_component)."""
    return yasaklar.kurallar().yasak_yol(path)


def resolve_project(cfg, project):
    if not isinstance(project, str) or not PROJECT_NAME.fullmatch(project):
        raise Refused(f"invalid project name: {project!r}")
    entry = cfg["projects"].get(project)
    if not isinstance(entry, dict) or not entry.get("path"):
        raise Refused(f"'{project}' is not in the ofis.json registry")
    path = os.path.realpath(os.path.expanduser(entry["path"]))
    if is_forbidden_path(path):
        raise Refused(f"'{project}' resolves to a forbidden path (a forbidden project is outside the office)")
    if not os.path.isdir(path):
        raise Refused(f"'{project}' folder does not exist: {path}")
    return path


TRUST_REFUSAL = "güven onayı yok"  # the start of the refusal text; bin/dispatcher.py tells it apart


def claude_config_path():
    """Claude Code's user config (~/.claude.json) where it keeps each folder's trust; $OFIS_CLAUDE_JSON overrides it
    (the tests point it at a path of their own)."""
    return os.path.expanduser(os.environ.get("OFIS_CLAUDE_JSON") or "~/.claude.json")


_trust_cache = {"key": None, "projects": None}


def folder_trusted(path, config=None):
    """True when Claude Code trusts the folder itself (its own entry has hasTrustDialogAccepted), False when it does
    not, None when the config cannot be read (the start goes on; claude decides). Claude 2.1.325 refuses a background
    session in an untrusted folder ("Workspace not trusted") even when a parent folder is trusted (seen 2026-11-15:
    ~/Dev trusted, ~/Dev/ofis-arge refused), so only the folder's own entry counts. Checking first keeps the job queued
    instead of failing it. Read only: the office never writes Claude's config — the owner accepts the prompt."""
    config = config or claude_config_path()
    try:
        st = os.stat(config)
        key = (config, st.st_mtime_ns, st.st_size)
        if _trust_cache["key"] != key:
            with open(config, encoding="utf-8") as f:
                projects = json.load(f).get("projects")
            _trust_cache.update(key=key, projects=projects if isinstance(projects, dict) else {})
        projects = _trust_cache["projects"]
    except (OSError, ValueError, AttributeError):
        return None
    entry = projects.get(os.path.realpath(os.path.expanduser(path)))
    return isinstance(entry, dict) and entry.get("hasTrustDialogAccepted") is True


def check_trusted(path):
    if folder_trusted(path) is False:
        raise Refused(f"{TRUST_REFUSAL}: Claude bu klasöre henüz güvenmiyor ({path}). {sahip.ad()} bir kez `cd {path} && "
                      "claude` çalıştırıp güven sorusuna evet demeli; iş sırada bekler, onaydan sonra kendiliğinden "
                      "başlar")


def check_task(task):
    if not isinstance(task, str) or not task.strip():
        raise Refused("task is empty")
    if len(task) > MAX_TASK:
        raise Refused(f"task is limited to {MAX_TASK} characters")
    if task.lstrip().startswith("-"):
        raise Refused("task may not start with '-' (it would be read as a claude option)")


def check_options(model, effort, permission_mode):
    if model is not None and (not isinstance(model, str) or not MODEL_NAME.fullmatch(model)):
        raise Refused(f"invalid model name: {model!r}")
    if effort is not None and effort not in EFFORTS:
        raise Refused(f"effort must be one of {', '.join(EFFORTS)}")
    if permission_mode is not None and permission_mode not in PERMISSION_MODES:
        raise Refused(f"permission mode must be one of {', '.join(PERMISSION_MODES)}")


def tier_entry(cfg, project, tier):
    """(model, effort, source) a tier maps to for a project: the project's override in ofis.json
    (`projects.<P>.tiers.<T>`, phase 8: written only after the owner approved a successful pilot) when it names a model,
    else the global `tiers` entry. source: "proje" or "katman" ("" when neither names a model)."""
    projects = cfg.get("projects") if isinstance(cfg.get("projects"), dict) else {}
    entry = projects.get(project) if isinstance(project, str) else None
    overrides = entry.get("tiers") if isinstance(entry, dict) and isinstance(entry.get("tiers"), dict) else {}
    own = overrides.get(tier) if isinstance(overrides.get(tier), dict) else {}
    if own.get("model"):
        return own.get("model"), own.get("effort"), "proje"
    tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
    general = tiers.get(tier) if isinstance(tiers.get(tier), dict) else {}
    return general.get("model"), general.get("effort"), "katman" if general.get("model") else ""


def resolve_tier(cfg, tier=None, model=None, effort=None, project=None):
    """(tier, model, effort): model and effort come from the tier's mapping unless given explicitly — explicit >
    the project's override (ofis.json projects.<P>.tiers) > the global tiers."""
    tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
    tier = tier or cfg.get("default_tier") or "genel"
    if tiers and tier not in tiers:
        raise Refused(f"unknown tier {tier!r}; ofis.json has {', '.join(tiers)}")
    mapped_model, mapped_effort, _ = tier_entry(cfg, project, tier)
    model = model or mapped_model
    effort = effort or mapped_effort
    check_options(model, effort, None)
    return tier, model, effort


def default_budget(cfg, tier):
    """The default budget (USD, float) of a tier: ofis.json `tiers.<T>.butce_usd` (the owner, 2026-11-12: one figure per
    tier, the global table only — a project's tier override carries the model, not the money), else
    `default_budget_usd` (an unknown tier, or a tier without its own figure); None when neither is a positive number."""
    tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
    entry = tiers.get(tier) if isinstance(tiers.get(tier), dict) else {}
    for value in (entry.get("butce_usd"), cfg.get("default_budget_usd")):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 1000:
            return float(value)
    return None


def default_max_calls(cfg, tier):
    """The model-call limit of a tier (ofis.json default_max_calls), or None when none is configured."""
    limits = cfg.get("default_max_calls") if isinstance(cfg.get("default_max_calls"), dict) else {}
    value = limits.get(tier)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def contract(project, session, tier=None, duyurular=None, kurallar=None, rol=None, dersler=None):
    """The report contract of a project session; a `kod` job's also asks for its decisions and assumptions; the
    unexpired announcements (duyuru.gecerli) add the "Geçerli duyurular" section; kurallar = the project's "Proje
    kuralları" section (bin/sorumlu.py sozlesme_bolumu: the rules, the three sorumlu sections, for planning the project
    summary); rol = the job's "Rolün" section (bin/uzmanlik.py sozlesme_bolumu), after the project's rules; dersler =
    the job's "Geçmiş dersler" section (bin/hafiza.py sozlesme_bolumu: verified lessons quoted as data), after the role."""
    return CONTRACT.format(project=project, session=session, ofis_py=OFIS_PY, owner=sahip.ad()) + \
        (KOD_CONTRACT if tier == KOD_TIER else "") + \
        (kurallar or "") + (rol or "") + (dersler or "") + duyuru.sozlesme_bolumu(duyurular)


def role_section(job, durum_dir=None, model=None):
    """The "Rolün" section of a job: its specialisation from the server record (the note's only for a job without a
    record, e.g. from before records), its seniority from the model."""
    # with a durum_dir only the record counts (a missing key = no section): a session can edit its own note
    key = (records.load(durum_dir, job.name) or {}).get("uzmanlik", "") if durum_dir else job.meta.get("uzmanlik", "")
    return uzmanlik.sozlesme_bolumu(key, model if model is not None else job.meta.get("model"))


def lessons_section(job, durum_dir=None, cfg=None):
    """The "Geçmiş dersler" section of a job (bin/hafiza.py): verified lessons of its specialisation from the server's
    own index, chosen with its trusted brief; only lessons of the office's projects (cfg's registry; without cfg only
    the job's own project). "" without a durum_dir or when nothing fits; never fails a start or a resume."""
    if not durum_dir:
        return ""
    import hafiza  # lazy: hafiza imports kontrol, which imports this module
    project = (records.load(durum_dir, job.name) or {}).get("proje") or job.meta.get("proje") or ""
    office = set((cfg or {}).get("projects") or ()) if cfg else {project}
    try:
        return hafiza.sozlesme_bolumu(durum_dir, job.name, project, office)
    except Exception:  # noqa: BLE001 — the memory never fails a start or a resume
        return ""


def deny_rules(vault_ofis=None):
    """--disallowedTools rules for a project session. '//' marks an absolute path in Claude Code permission rules.
    The vault's OFIS folder is denied by its real path (symlinks resolved)."""
    folders = [ROOT]
    if vault_ofis:
        folders.append(os.path.realpath(os.path.expanduser(vault_ofis)))
    rules = []
    for folder in folders:
        root = "//" + folder.lstrip("/")
        rules += [f"Edit({root}/**)", f"Write({root}/**)"]
    # the contract says never create a worktree (the office decides where a job works): enforce it
    return rules + [f"Bash(python3 {OFIS_PY} {c}:*)" for c in DENIED_COMMANDS] + ["EnterWorktree"]


BG_SETTINGS = '{"worktree": {"bgIsolation": "none"}}'


ADVISOR_VALUE = re.compile(r"(?:opus|sonnet|fable|claude-[a-z0-9][a-z0-9.-]{1,60})")


def session_flags(project, session, model=None, effort=None, permission_mode=None, vault_ofis=None, tier=None,
                  duyurular=None, kurallar=None, rol=None, dersler=None, danisman=None):
    """The options every start and every resume of a project session carries. The variadic --disallowedTools list is
    closed by --append-system-prompt, so the prompt after these options is never read as a rule. tier: the job's
    tier (a `kod` job's contract asks for its decisions and assumptions); duyurular: the unexpired announcements;
    danisman: the advisor model (`--advisor`, bin/danisman.py: arm B of the advisor pilot, the mapped advisor or the
    hard-job advisor)."""
    flags = []
    if model:
        flags += ["--model", model]
    if effort:
        flags += ["--effort", effort]
    if danisman:
        if not ADVISOR_VALUE.fullmatch(danisman):
            raise Refused(f"invalid advisor model: {danisman!r}")
        flags += ["--advisor", danisman]
    if permission_mode:
        flags += ["--permission-mode", permission_mode]
    # The owner's decision (2026-11-12): Claude Code isolates a background session's edits in a worktree it must enter
    # first (EnterWorktree, which the contract denies), so Edit/Write were refused in the job's folder. The office
    # already chose that folder and reviews only it: the isolation is off for office sessions only.
    flags += ["--settings", BG_SETTINGS]
    flags += ["--disallowedTools", *deny_rules(vault_ofis)]
    flags += ["--append-system-prompt", contract(project, session, tier, duyurular, kurallar, rol, dersler)]
    return flags


def resume_flags(job, vault_ofis, durum_dir=None, now=None, cfg=None):
    """session_flags() rebuilt from a job (model, effort, izin_modu, proje, oturum: pass it with its server record
    overlaid, records.trusted), with the announcements unexpired at `now` (durum_dir given) and, with cfg, the
    project's "Proje kuralları" section (bin/sorumlu.py). Raises Refused."""
    meta = job.meta
    project, session = meta.get("proje") or "", meta.get("oturum") or ""
    if not PROJECT_NAME.fullmatch(project) or not SESSION_NAME.fullmatch(session):
        raise Refused(f"{job.name} has no valid proje/oturum")
    model, effort, mode = meta.get("model") or None, meta.get("effort") or None, meta.get("izin_modu") or None
    check_options(model, effort, mode)
    advisor = None
    if cfg is not None and durum_dir:
        import danisman  # imports this module
        advisor = danisman.advisor_for(cfg, durum_dir, job.name, meta.get("katman") or None) or None
    return session_flags(project, session, model, effort, mode, vault_ofis=vault_ofis,
                         tier=meta.get("katman") or None, duyurular=duyuru.gecerli(durum_dir, now),
                         kurallar=sorumlu.sozlesme_bolumu(cfg, project, meta.get("katman") or None) if cfg else None,
                         rol=role_section(job, durum_dir, model), dersler=lessons_section(job, durum_dir, cfg),
                         danisman=advisor)


def git_head(path, git_bin="git", timeout=10):
    """HEAD commit of the project, or "" when it is not a git repository (or git fails)."""
    try:
        proc = subprocess.run([git_bin, "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and GIT_SHA.fullmatch(sha) else ""


DIRTY_MAX = 200  # paths kept of a folder's state at the start (records.py taban_kirli; a record is read up to 64 KB)
DIRTY_BYTES = 16 * 1024


def git_dirty(path, git_bin="git", timeout=10):
    """(paths, durum) of the folder's state now: the paths already modified, staged or untracked (`git status
    --porcelain=v1 -z --untracked-files=all --no-renames`, read-only), durum "tam"; ([], "eksik") when git fails or
    there are more than DIRTY_MAX paths / DIRTY_BYTES bytes."""
    try:
        proc = subprocess.run([*gitsafe.argv(git_bin, path), "status", "--porcelain=v1", "-z",
                               "--untracked-files=all", "--no-renames"], capture_output=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C"))
    except (OSError, subprocess.TimeoutExpired):
        return [], "eksik"
    if proc.returncode != 0:
        return [], "eksik"
    paths = [entry[3:] for entry in proc.stdout.decode("utf-8", "replace").split("\0") if len(entry) > 3]
    if len(paths) > DIRTY_MAX or sum(len(p) + 4 for p in paths) > DIRTY_BYTES:
        return [], "eksik"
    return paths, "tam"


def _vault(cfg):
    return os.path.expanduser(cfg["vault_ofis"])


def validate_job(cfg, project, title, brief, tier=None, model=None, effort=None, budget=None):
    """Checks a job before anything is written (the checks of `ofis.py ekle`, shared with `ofis.py zamanla ekle`).
    Returns (title, brief, tier, model, effort, budget) normalised; raises Refused."""
    resolve_project(cfg, project)
    if not isinstance(title, str) or not title.strip():
        raise Refused("title (baslik) is empty")
    title = " ".join(title.split())
    if len(title) > MAX_TITLE:
        raise Refused(f"title is limited to {MAX_TITLE} characters")
    brief = {k: v for k, v in (brief or {}).items() if v is not None}
    if not isinstance(brief.get("hedef"), str) or not brief["hedef"].strip():
        raise Refused("the brief needs a non-empty Hedef")
    try:
        body = jobs.render_brief(brief)
    except jobs.JobError as e:
        raise Refused(str(e)) from e
    check_task(_prompt_of(body))
    tier, model, effort = resolve_tier(cfg, tier, model, effort, project=project)
    if tier == KOD_TIER and not (isinstance(brief.get("kontrol"), str) and brief["kontrol"].strip()):
        raise Refused(NO_KONTROL)
    if budget is None:
        budget = default_budget(cfg, tier)
    if budget is not None:
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            raise Refused(f"invalid budget: {budget!r}") from None
        if not 0 < budget <= 1000:  # also refuses nan
            raise Refused("budget must be between 0 and 1000 USD")
        budget = f"{budget:g}"
    return title, brief, tier, model, effort, budget


def route(cfg, project, title, brief, tier, choice=None, plan=None, adim=None):
    """The specialisation of a job (bin/uzmanlik.py sec): the explicit choice, else the routing over the brief, the tier,
    the plan text and the project's layout (names of its top folders only; never a forbidden path). Raises Refused for
    an unknown explicit choice."""
    try:
        if choice not in (None, ""):
            return uzmanlik.sec(title, brief, secilen=choice)
        entry = cfg.get("projects", {}).get(project) if isinstance(cfg.get("projects"), dict) else None
        path = os.path.realpath(os.path.expanduser(entry["path"])) if isinstance(entry, dict) and \
            isinstance(entry.get("path"), str) and entry["path"] else None
        duzen = uzmanlik.proje_duzeni(path) if path and not is_forbidden_path(path) else None
        return uzmanlik.sec(title, brief, proje=project, katman=tier, plan=plan, duzen=duzen, adim=adim)
    except uzmanlik.Gecersiz as e:
        raise Refused(str(e)) from None


def create_job(cfg, project, title, brief, tier=None, model=None, effort=None, budget=None, depends=None,
               group=None, now=None, durum_dir=None, extra=None, pilot=False, uzmanlik=None, uzmanlik_secimi=None,
               adim=None):
    """Validates and writes a `sirada` job in Siradakiler (and, with durum_dir, its server record).
    brief: {hedef, neden, kisitlar, kapsam_disi, kontrol, onceki}. extra: more fields for the note and the record
    (beklet, yukseltme_kaynagi, yukseltme_sayisi).
    Phase 8: `model_kaynagi` on the note and the record says where the model came from — elle (an explicit model),
    pilot, proje (the project's override) or katman (the global tiers). With pilot=True (ekle, workflow steps with a
    session, scheduled adds — never an escalation) and no explicit model, a running pilot of this project × tier
    (bin/model_secimi.py) gives the model and effort and the job is marked `pilot: <kimlik>` — only for a job whose brief
has a Kontrol (a job without one would never be measured).
    Specialisation (bin/uzmanlik.py): uzmanlik = an explicit choice (Refused when unknown); uzmanlik_secimi = a choice
    made by the caller ({uzmanlik, neden, kaynak}: an escalation keeps its job's); adim = a workflow step kind (its
    review steps follow the step); otherwise the routing decides. Stored on the record and the note."""
    explicit_model = bool(model)
    explicit_effort = effort or None
    trial = "evet" if (extra or {}).get("deneme") == "evet" else ""
    title, brief, tier, model, effort, budget = validate_job(cfg, project, title, brief, tier, model, effort, budget)
    source = "elle" if explicit_model else (tier_entry(cfg, project, tier)[2] or "katman")
    if adim == "onay":  # The owner's approval card: no session, no specialisation (never counted per specialisation)
        role = {"uzmanlik": "", "neden": "", "kaynak": ""}
    elif isinstance(uzmanlik_secimi, dict) and uzmanlik_secimi.get("uzmanlik"):
        role = uzmanlik_secimi
    else:
        role = route(cfg, project, title, brief, tier, uzmanlik, adim=adim)
    role = {"uzmanlik": role["uzmanlik"], "uzmanlik_nedeni": role.get("neden") or "",
            "uzmanlik_kaynagi": role.get("kaynak") or ("kural" if role["uzmanlik"] else "")}
    vault = _vault(cfg)
    names = []
    for dep in depends or []:
        try:
            name = jobs.check_name(dep.strip())
            found = jobs.find(vault, name)
        except jobs.JobError as e:
            raise Refused(str(e)) from e
        if found is None:
            raise Refused(f"no such job to depend on: {name}")
        names.append(name)
    if group is not None and not GROUP_NAME.fullmatch(group):
        raise Refused(f"invalid group name: {group!r}")
    now = now or datetime.now()
    with jobs.locked(vault):  # the pilot's free slot and the new note together: two adds never take the last slot
        pilot_id = ""
        # only a job with a Kontrol takes a pilot slot: the pilot is measured like the evidence (phase 8 review)
        # a self-test job (deneme) never takes a slot either: its row is left out of the measurement
        if pilot and not explicit_model and not trial and durum_dir and (brief.get("kontrol") or "").strip():
            import model_secimi  # imports this module
            slot = model_secimi.pilot_slot(durum_dir, project, tier)
            if slot:
                pilot_id, model, pilot_effort = slot
                effort = explicit_effort or pilot_effort
                check_options(model, effort, None)
                source = "pilot"
        choice = {"model_kaynagi": source, "pilot": pilot_id or None}
        # the advisor pilot (bin/danisman.py): the same callers, never a self-test, an explicit model or a model-pilot
        # job; nothing at all while its switch is off
        advisor = {}
        if pilot and durum_dir:
            import danisman  # imports this module
            arm = danisman.slot(cfg, durum_dir, tier, trial=bool(trial), explicit_model=explicit_model,
                                model_pilot=bool(pilot_id), kontrol=brief.get("kontrol") or "")
            if arm:
                advisor = {"danisman_pilotu": arm[0], "danisman_kolu": arm[1], "danisman": arm[2]}
        fields = {"katman": tier, "model": model, "effort": effort, "butce_usd": budget,
                  "max_cagri": default_max_calls(cfg, tier),
                  "bagimli": ",".join(names) or None, "grup": group, **(extra or {}), **choice,
                  "uzmanlik": role["uzmanlik"], "uzmanlik_nedeni": role["uzmanlik_nedeni"]}
        try:
            job = jobs.create(vault, project, title, fields=fields, now=now, brief=brief)
        except jobs.JobError as e:
            raise Refused(f"cannot write the job note in the vault ({e}); nothing was started") from e
        if durum_dir:
            try:
                # the Kontrol count starts on the record (phase 8 review): a session-edited note never stands in
                records.update(durum_dir, job.name, {**records.from_note(job),
                                                     **{k: v for k, v in choice.items() if v},
                                                     "kontrol_deneme": 0, "kontrol_sonuc": "", "deneme": trial,
                                                     **role, **advisor})
                if pilot_id:
                    model_secimi.add_pilot_job(durum_dir, project, tier, pilot_id, job.name)
                if advisor:
                    danisman.add_job(durum_dir, advisor["danisman_pilotu"], job.name, advisor["danisman_kolu"])
            except (OSError, ValueError) as e:  # model_secimi.Refused / danisman.Refused are ValueErrors
                # never leave a job whose limits (or pilot) the server cannot find
                jobs.update(vault, job.name, status="iptal",
                            fields={"bitis": f"{now:%Y-%m-%dT%H:%M:%S}", "karne": "yok"},
                            append_result="Sunucu kaydı yazılamadı; iş iptal edildi, yeniden ekleyin.")
                raise Refused(f"cannot write the job's server record ({type(e).__name__}); the job was "
                              "cancelled") from e
    return job


def _prompt_of(goerev_body):
    return jobs.prompt(jobs.Job("x.md", jobs.QUEUED, "", {}, f"## Görev\n\n{goerev_body}\n"))


def start_job(cfg, job_name, claude_bin=None, now=None, suffix=None, worktree=False, permission_mode=None,
              git_bin="git", durum_dir=None, gate=None, task=None):
    """Starts a `sirada` job; returns {project, name, short_id, path, note, is}. Raises Refused. With durum_dir the
    server record gets the session name, working folder, permission mode, base commit and short id. gate(job), when
    given, runs under the job lock right before the job becomes `baslatiliyor` and may raise Refused (the WIP limits of
    bin/dispatcher.py): nothing is recorded then. task: the prompt to send (a workflow step's, bin/akis.py) instead of
    the note's brief."""
    vault = _vault(cfg)
    try:
        job = jobs.load(vault, job_name)
    except jobs.JobError as e:
        raise Refused(str(e)) from e
    if job.meta.get("durum") != "sirada":
        raise Refused(f"{job.name} is '{job.meta.get('durum')}'; only a 'sirada' job is started (a job is started "
                      "once — add a new job instead)")
    project = job.meta.get("proje")
    path = resolve_project(cfg, project)
    check_trusted(path)  # before anything is recorded: an untrusted folder leaves the job queued
    task = jobs.prompt(job) if task is None else task
    check_task(task)
    model, effort = job.meta.get("model") or None, job.meta.get("effort") or None
    check_options(model, effort, permission_mode)
    now = now or datetime.now()
    name = f"ofis-{project}-{now:%m%d-%H%M%S}-{suffix or secrets.token_hex(2)}"
    cwd = os.path.join(path, ".claude", "worktrees", name) if worktree else path
    if gate is not None:
        gate(job)  # a cheap pre-check first: a job a limit holds back never runs git (checked again under the lock)
    base = git_head(path, git_bin)
    dirty, dirty_state = git_dirty(path, git_bin) if base else ([], "")
    git_state = gitsafe.state_digest(path, git_bin) if base else ""
    fields = {"oturum": name, "kisa_id": "-", "calisma_dizini": cwd, "taban_commit": base,
              "baslangic": f"{now:%Y-%m-%dT%H:%M:%S}", "worktree": name if worktree else None,
              "izin_modu": permission_mode}

    def record(values):
        if durum_dir:
            base = {} if records.load(durum_dir, job.name) else records.from_note(job)  # a job from before records
            records.update(durum_dir, job.name, {**base, **values})

    with jobs.locked(vault):
        if gate is not None:
            try:
                current = jobs.load(vault, job.name)
            except jobs.JobError as e:
                raise Refused(str(e)) from e
            if current.meta.get("durum") != "sirada":
                raise Refused(f"{job.name} is '{current.meta.get('durum')}'; only a 'sirada' job is started")
            gate(current)
        try:
            record({"oturum": name, "kisa_id": "-", "calisma_dizini": cwd, "izin_modu": permission_mode or "",
                    "proje": project, "model": model or "", "effort": effort or "", "taban_commit": base,
                    **({"taban_kirli": dirty, "taban_kirli_durum": dirty_state, "taban_git_ozet": git_state}
                       if base else {})})
        except OSError as e:
            raise Refused(f"cannot write the job's server record ({type(e).__name__}); nothing was started") from e
        try:
            job = jobs.update(vault, job.name, status="baslatiliyor", fields={k: v for k, v in fields.items() if v},
                              expect=("sirada",))
        except jobs.JobError as e:
            raise Refused(f"cannot update the job note ({e}); nothing was started") from e

    def fail(reason, output=""):
        detail = f"{reason}\n\n```\n{output[-500:]}\n```" if output else reason
        try:
            failed = jobs.update(vault, job.name, status="basarisiz", append_result=f"Başlatma başarısız: {detail}",
                                 fields={"bitis": f"{datetime.now():%Y-%m-%dT%H:%M:%S}"}, expect=("baslatiliyor",))
            where = failed.path
        except jobs.JobError:
            where = job.name
        raise Refused(f"{reason} (note: {where})")

    advisor = None
    if durum_dir:
        import danisman  # imports this module
        if worktree:  # the advisor pilot never measures a worktree job: it leaves, and never gets the flag
            try:
                danisman.leave(durum_dir, job.name, "started in a worktree")
            except OSError:
                pass  # the note is already baslatiliyor: a failed state write must not strand it (Codex, 2026-11-14)
        else:
            try:
                advisor = danisman.advisor_for(cfg, durum_dir, job.name, job.meta.get("katman") or None) or None
            except OSError:
                advisor = None
    claude = claude_bin or shutil.which("claude") or "claude"
    flags = ["--worktree", name] if worktree else []
    flags += session_flags(project, name, model, effort, permission_mode, vault_ofis=vault,
                           tier=job.meta.get("katman") or None, duyurular=duyuru.gecerli(durum_dir, now),
                           kurallar=sorumlu.sozlesme_bolumu(cfg, project, job.meta.get("katman") or None),
                           rol=role_section(job, durum_dir, model), dersler=lessons_section(job, durum_dir, cfg),
                           danisman=advisor)
    command = [claude, "--bg", "--name", name, *flags, task]
    try:
        proc = subprocess.run(command, cwd=path, capture_output=True, text=True, timeout=LAUNCH_TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        # Ambiguous: claude may have started the session. Keep the job open so its report still applies.
        try:
            jobs.update(vault, job.name, expect=("baslatiliyor",),
                        append_result=f"Başlatma doğrulanamadı: claude {LAUNCH_TIMEOUT:g} sn içinde yanıt vermedi; "
                                      "oturum çalışıyor olabilir. Oturumdan gelen rapor yine işlenir.")
        except jobs.JobError:
            pass
        raise Refused(f"launch unconfirmed: claude timed out after {LAUNCH_TIMEOUT:g} s; {job.name} stays "
                      "'baslatiliyor' (the session may be running — check `claude agents`; do not start it again)")
    except OSError as e:
        fail(f"could not start claude: {type(e).__name__}")
    short_id, printed_name = parse_launch(proc.stdout)
    if proc.returncode != 0 or short_id is None:
        fail(f"claude did not print the expected launch line (exit {proc.returncode})", proc.stdout + proc.stderr)
    if printed_name != name:
        fail(f"claude reported session '{printed_name}' instead of '{name}'; check `claude agents`", proc.stdout)
    record({"kisa_id": short_id})
    try:
        job = jobs.update(vault, job.name, status="calisiyor", fields={"kisa_id": short_id}, expect=("baslatiliyor",))
    except jobs.StatusConflict:
        # The session reported (bitti/soru) before this update: keep its status, record the short id only.
        job = jobs.update(vault, job.name, fields={"kisa_id": short_id})
    return {"project": project, "name": name, "short_id": short_id, "path": path, "note": job.path, "is": job.name}


def launch(cfg, project, task, claude_bin=None, now=None, suffix=None,
           model=None, effort=None, worktree=False, permission_mode=None, durum_dir=None):
    """ekle + baslat in one step: the task is the job's Hedef, its first line the title."""
    resolve_project(cfg, project)
    check_task(task)
    check_options(model, effort, permission_mode)
    now = now or datetime.now()
    title = task.strip().splitlines()[0][:80]
    job = create_job(cfg, project, title, {"hedef": task}, model=model, effort=effort, now=now, durum_dir=durum_dir)
    return start_job(cfg, job.name, claude_bin=claude_bin, now=now, suffix=suffix, worktree=worktree,
                     permission_mode=permission_mode, durum_dir=durum_dir)


def parse_args(args):
    import argparse
    p = argparse.ArgumentParser(prog="launch.py", description="Add a job and start its project session.")
    p.add_argument("project")
    p.add_argument("task")
    p.add_argument("--model", help="model alias or id, e.g. sonnet, haiku, opus, fable")
    p.add_argument("--effort", choices=EFFORTS)
    p.add_argument("--worktree", action="store_true", help="run in a separate git worktree")
    p.add_argument("--permission-mode", choices=PERMISSION_MODES)
    return p.parse_args(args)


def main(argv):
    args = parse_args(argv[1:])
    try:
        result = launch(load(), args.project, args.task, model=args.model, effort=args.effort,
                        worktree=args.worktree, permission_mode=args.permission_mode, durum_dir=DURUM_DIR)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
