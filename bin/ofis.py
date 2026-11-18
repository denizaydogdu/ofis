#!/usr/bin/env python3
"""Job commands of the office, for the CEO and (only `bildir`) for project sessions.

    ofis.py ekle --brief-dosya durum/taslak/<f>.json      (or the flags below; flags win over the file)
    ofis.py ekle --proje P --baslik "…" --hedef "…" [--neden …] [--kisitlar …] [--kapsam-disi …] [--kontrol …]
                 [--katman T] [--model M] [--effort E] [--butce USD] [--cagri N] [--bagimli a,b] [--grup G] [--beklet]
                 [--deneme] [--uzmanlik U]
    ofis.py baslat <is> [--worktree] [--permission-mode M]
    ofis.py bildir --oturum <session name> --tur bitti|tikandi|soru - <<'OFIS_RAPOR' … OFIS_RAPOR   (stdin)
    ofis.py bildir --oturum <session name> --tur … "<metin>" | --dosya durum/taslak/<f>.txt
    ofis.py cevapla <karar notu> "<cevap>" | --dosya durum/taslak/<f>.txt
    ofis.py bitir <is> [--sonuc "…"]
    ofis.py iptal <is>
    ofis.py butce <is> [<usd>] [--cagri N]
    ofis.py devam <is> ["<metin>" | --dosya durum/taslak/<f>.txt]
    ofis.py serbest <is>                       (a held queued job may start)
    ofis.py bagimli <is> --kaldir <bagimlilik>   (drop a dependency of a queued job)
    ofis.py akis <sablon> --proje P --baslik "…" (--hedef "…" | --brief-dosya f) --kontrol "<cmd>" [--butce USD]
                 [--neden …] [--kisitlar …] [--kapsam-disi …] [--uzmanlik U]   (a workflow: one job per step)
    ofis.py akis-karar <grup> devam|iptal     (the owner's decision on a stopped workflow)
    ofis.py zamanla ekle --ad <ad> --proje P --baslik "…" --hedef "…" --saat HH:MM [--gunler pzt,sal,car,per,cum,cmt,paz]
                 [--neden …] [--kisitlar …] [--kapsam-disi …] [--kontrol …] [--katman T] [--model M] [--effort E]
                 [--butce USD] [--uzmanlik U]   (or --brief-dosya durum/taslak/<f>.json; a scheduled job, bin/zamanla.py)
    ofis.py zamanla listele | durdur <ad> | devam <ad> | sil <ad>
    ofis.py duyuru "<metin>" | --dosya durum/taslak/<f>.txt [--sure simdi|bugun|hafta|YYYY-AA-GG]
                                               (the owner's announcement to every office session; CEO only, on his word)
    ofis.py yakala --url <http(s) bağlantı> [--not "…" | --not-dosya durum/taslak/<f>.txt]
                                               (the owner's captured link -> one Ar-Ge research job; CEO only, bin/yakala.py)
    ofis.py modeller                           (read-only: effective model mapping, pilots, open model cards)
    ofis.py talimat-denetimi                   (the prompt audit of the instructions now -> one Ar-Ge job; CEO only, on
                                               the owner's word; bin/talimat_denetimi.py)
    ofis.py hafiza-saglik                      (read-only: the memory health check of OFIS/, printed; bin/hafiza_saglik.py)
    ofis.py deneme-isaretle <is>...          (one-time, idempotent: mark finished jobs as office self-tests)
    ofis.py danisman-pilotu oner | durum       (the advisor pilot's proposal card — CEO only, on the owner's word — or
                                               its read-only state; bin/danisman.py)
    ofis.py sor --dosya durum/taslak/<f>.json   (the CEO's own question to the owner -> one pending Kararlar card
                                               tur: ceo-sorusu; CEO only)
    ofis.py ceo-yenile                         (asks for one fresh CEO session at the next delivery, with the handoff
                                               note: after CLAUDE.md or the message protocol changed; bin/ceo.py)
    ofis.py durum

Results are one line of JSON (durum prints a table). A validation error prints "REFUSED: ..." and exits 1.
`bildir` only writes one JSON file into durum/gelen/ (temp file + os.replace): no network, no vault writes. It
records the caller's working folder; the office server's post office accepts a report only from the job's own
calisma_dizini, then updates the vault and tells the CEO. A report over MAX_REPORT characters is shortened.
Input files (--brief-dosya, --dosya) exist because the CEO's guard hook checks command lines but not the content of
files it writes: they must be plain files directly in durum/taslak/ and are deleted once the command succeeded (kept
when it refuses, so they can be fixed).
`cevapla` queues the answer as durum/giden/<time_ns>-cevap-<note>.json (name order = answer order).
`bitir` / `iptal` also drop the session's undelivered answers and close its open questions (durum: kapandi).
`ekle` also keeps the job's Kontrol in durum/kontroller/<job>.json: the copy the server trusts and runs (bin/kontrol.py);
a `kod` job without a Kontrol is refused. `ekle` / `baslat` also write the job's server record durum/isler/<job>.json
(bin/records.py), which the server enforces; the note shows the same values. `butce` changes a job's budget / call
limit on the record and the note; `devam` puts a `tikandi` job (e.g. stopped by the server for its budget or call
limit) back to `calisiyor` — checking the limits and spending of the record — and queues "[Ofis · devam]" + the text
(default "Devam et.") for its session in durum/giden/, the answers' path; it empties `karne` and counts the round
(`devam_sayisi`), so the job's scorecard row is replaced at its next final status.
Phase 3 (bin/dispatcher.py): a queued job starts by itself when its dependencies are bitti, it is not held
(`ekle --beklet`, released by `serbest`) and the WIP limits allow it; `baslat` starts at once but respects the limits
(start_job, shared with the dispatcher); `ekle` refuses beyond max_queued_per_project ("Sıradakiler dolu"); `bagimli
--kaldir` drops a dependency (e.g. one that got stuck, after the owner decided).
Phase 3 review: `ekle` also keeps the trusted brief (durum/kontroller/briefs/<job>.json, kontrol.save_brief); an
escalation is built only from it. `devam` refuses an escalated job (`yukseltildi`: it goes on as its replacement) and
checks the WIP limits like a start (dispatcher.start_gate with resume=True; a worktree job is not held by its project's
folder limit).
Phase 4 (bin/akis.py): `akis` starts a workflow from a trusted template (akislar/<name>.json): one `sirada` job per
step, chained with bagimli, one grup; start_job routes a workflow step to akis.start_step (the step gate, the prompt
from the trusted store, Codex or the approval card). `cevapla` on a workflow's approval card (tur: akis-onay) closes
the workflow on a plain approval and hands anything else to the CEO; it never writes an outbox message. `akis-karar`
lets a stopped workflow go on (the stopped step counts as passed) or cancels its open steps.
Phase 6 (bin/zamanla.py): `zamanla ekle` stores a trusted schedule definition (durum/zamanlanmis/<ad>.json, validated
like `ekle`); the server adds one normal `sirada` job per due slot (add_job, the path of `ekle`). `zamanla durdur` /
`devam` pause and resume it, `sil` marks it removed (its history stays), `listele` prints a table.
Phase 8 (bin/model_secimi.py): `ekle` (and scheduled adds) take a running pilot's model for its project × tier unless
--model is given; `cevapla` on a model card (tur: model-onerisi / model-pilot-sonucu) starts the pilot or closes the
proposal, and — only a plain yes on a successful pilot result — writes the project's tier override into ofis.json and a
row into OFIS/Karne/Degisiklikler.md; `modeller` prints the effective mapping, the pilots and the open model cards.
The advisor pilot (bin/danisman.py): `danisman-pilotu oner` writes its one proposal card (the CEO, only on the owner's
word); `cevapla` on its cards (tur: danisman-onerisi / danisman-pilot-sonucu) starts the pilot (and turns its ofis.json
switch on) or closes it, and — only a plain yes on a successful result — writes tiers.<T>.danisman into ofis.json and a
Degisiklikler row; `ekle` gives a kod job its arm (A without, B with `--advisor`) while the pilot runs.
`duyuru` (bin/duyuru.py): the owner's announcement — the trusted record durum/duyurular/<id>.json, one outbox message per
active session (delivered like an answer), the vault note OFIS/Duyurular/; the CEO runs it only on the owner's explicit word,
project sessions are denied it (launch.DENIED_COMMANDS). `bitir` / `iptal` mark the session's undelivered announcement
iletilemedi.
Guard-rails (B3 audit, owner decision 2026-11-12; bin/uyarilar.py): `ekle`, `akis` and `zamanla ekle` print `UYARI: …` lines
(stderr) and return them as `uyarilar` in their JSON — a change brief outside kod, an open-ended kolay Hedef or a kolay
job without Kontrol, an explicit --model, a budget far from the tier's observed spend, a Kontrol that cannot fail, a
--cagri far above the tier's or beyond what the budget pays, a workflow review share below one Claude review. They never
block, except a `kod` job (or a workflow's kod step, or a kod schedule) whose Kontrol always passes: REFUSED.
`--deneme` (brief field `deneme: true`) marks an office self-test: the record's `deneme`, the Karne row's Deneme
column; such rows stay out of the quality numbers, model selection and group-report totals. `deneme-isaretle` marks
jobs that finished before the flag existed (record from the note when missing, the note, the Karne row; idempotent).
Specialisation (plan "Sonraki iş (9)" step 2, bin/uzmanlik.py): every new job is routed to a specialisation (backend,
ui, mobil, test, analiz, guvenlik, genel) unless `--uzmanlik U` (brief field `uzmanlik`) names one; `ekle` / `akis` /
`zamanla ekle` print it with its short reason (`uzmanlik`, `uzmanlik_nedeni`). Advice for the session's role, never a
gate. `sor` (the owner, 2026-11-14: a question the CEO asked only in the chat was invisible): the CEO's own question becomes a
pending Kararlar card `YYYY-MM-DD-<proje|ofis>-ceo-sorusu[-n].md` (tur: ceo-sorusu; Soru quoted with "> ", Seçenekler
as "- A) …" lines, İlgili Sayfalar) that the page shows like any decision; `cevapla` closes it (CEO_DECISIONS) and
returns the answer (`cevap`, `onay`, and `secim` when it names one of the options). `ekle --cagri N` sets the job's call limit (else the tier's). The default budget is the tier's (`tiers.<T>.butce_usd`,
else default_budget_usd); --butce wins.
"""
import argparse
import json
import math
import os
import re
import secrets
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget  # noqa: E402
import dispatcher  # noqa: E402
import akis  # noqa: E402
import duyuru  # noqa: E402
import yakala  # noqa: E402
import talimat_denetimi  # noqa: E402
import jobs  # noqa: E402
import karne  # noqa: E402
import kontrol  # noqa: E402
import launch  # noqa: E402
import model_secimi  # noqa: E402
import danisman  # noqa: E402
import mudur  # noqa: E402
import records  # noqa: E402
import sahip  # noqa: E402
import uyarilar  # noqa: E402
import zamanla  # noqa: E402

ROOT = launch.ROOT
OFIS_PY = os.path.abspath(__file__)
DURUM_DIR = os.path.join(ROOT, "durum")
SESSION_NAME = re.compile(r"ofis-[a-z0-9-]{1,80}")
REPORT_TYPES = ("bitti", "tikandi", "soru")
MAX_REPORT = 8000
REPORT_KEEP = 7500  # a longer report keeps this much + SHORTENED (a refused report would be lost)
SHORTENED = "\n(kısaltıldı)"
MAX_ANSWER = 8000
CEO_YENILE = "ceo-yenile"  # bin/ceo.py YENILE_DOSYASI (not imported: ceo pulls the channel and the CLI wrapper)
ANSWER_HEAD = sahip.ANSWER_HEAD  # "[Ofis · Sahibin cevabı]" (the old "[Ofis · Deniz'in cevabı]" is never written)
MUDUR_HEAD = "[Ofis · Müdürün cevabı"  # + " · <Unvan>]" (bin/mudur.py: a manager answered a technical question)
MUDUR_DURUM = "mudur-cevapladi"  # a Kararlar note a manager answered; the owner may still answer it (bin/mudur.py DURUM)
DEVAM_HEAD = "[Ofis · devam]"
DEFAULT_DEVAM = "Devam et."
MAX_CALL_LIMIT = 100000
SCRATCH = "taslak"  # durum/taslak/: input files the CEO writes with the Write tool
MAX_INPUT_FILE = 64 * 1024
BRIEF_FILE_FIELDS = ("proje", "baslik", "hedef", "neden", "kisitlar", "kapsam_disi", "kontrol", "katman", "model",
                     "effort", "butce", "cagri", "bagimli", "grup", "beklet", "deneme", "uzmanlik")
AKIS_FILE_FIELDS = ("proje", "baslik", "hedef", "neden", "kisitlar", "kapsam_disi", "kontrol", "butce", "deneme",
                    "uzmanlik")
ZAMANLA_FILE_FIELDS = ("ad", "proje", "baslik", "hedef", "neden", "kisitlar", "kapsam_disi", "kontrol", "katman",
                       "model", "effort", "butce", "saat", "gunler", "deneme", "uzmanlik")
FLAGS = ("beklet", "deneme")  # brief file fields that are true / false
NOTE_NAME = re.compile(r"[^/\\\x00]{1,200}\.md")
MESSAGE_ID = re.compile(r"[0-9]{19}-[0-9a-f]{8}")


class Refused(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def _stamp(now):
    return f"{now:%Y-%m-%dT%H:%M:%S}"


def write_json_atomic(folder, name, data):
    """Writes data as folder/name via a temp file + os.replace; refuses to overwrite an existing file."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    if os.path.lexists(path):
        raise FileExistsError(path)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


# --- commands ---

def apply_brief_file(args, durum_dir, cwd, allowed=BRIEF_FILE_FIELDS):
    """Fills the ekle (or akis) arguments that were not given on the command line from a JSON brief file. Returns
    its path."""
    text, path = read_input_file(durum_dir, args.brief_dosya, cwd)
    try:
        data = json.loads(text)
    except ValueError:
        raise Refused("the brief file is not valid JSON") from None
    if not isinstance(data, dict):
        raise Refused("the brief file must hold one JSON object")
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise Refused(f"unknown brief file fields: {', '.join(unknown)} (allowed: {', '.join(allowed)})")
    for key, value in data.items():
        if value is None:
            continue
        if key in ("butce", "cagri") and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if key in ("bagimli", "gunler") and isinstance(value, list) and all(isinstance(v, str) for v in value):
            value = ",".join(value)
        if key in FLAGS:
            if not isinstance(value, bool):
                raise Refused(f"brief file field '{key}' must be true or false")
            setattr(args, key, getattr(args, key, False) or value)
            continue
        if not isinstance(value, str):
            raise Refused(f"brief file field '{key}' must be text")
        if getattr(args, key) is None:
            setattr(args, key, value)
    return path


def add_job(cfg, durum_dir, project, title, brief, now, tier=None, model=None, effort=None, budget=None,
            depends=None, group=None, beklet=False, extra=None, deneme=False, call_limit=None, uyari=None,
            uzmanlik=None):
    """The path of `ekle`, shared with the scheduler (bin/zamanla.py): the queue limit and the new note under one lock,
    the server record, the trusted Kontrol (a `kod` job without one is refused, and one whose Kontrol always passes) and
    the trusted brief. Returns (job, warning or None). Raises Refused / launch.Refused.
    deneme: an office self-test (record `deneme: evet`). call_limit: the job's max_cagri instead of the tier's.
    uyari: a list that gets the guard-rail warnings (bin/uyarilar.py; plain Turkish, no prefix).
    uzmanlik: an explicit specialisation (--uzmanlik; Refused when unknown), else the routing decides
    (bin/uzmanlik.py, launch.create_job)."""
    check = (brief.get("kontrol") or "").strip()
    if check and kontrol.forbidden_command(check):
        raise Refused("the Kontrol names a forbidden path (a forbidden project is outside the office)")
    vault = os.path.expanduser(cfg["vault_ofis"])
    refusal = uyarilar.kontrol_reddi(launch.resolve_tier(cfg, tier, model, effort, project=project)[0], check)
    if refusal:
        raise Refused(refusal)
    fields = dict(extra or {})
    if beklet:
        fields["beklet"] = "evet"
    if deneme:
        fields["deneme"] = "evet"
    if call_limit is not None:
        fields["max_cagri"] = call_limit
    with jobs.locked(vault):  # the queue count and the new note together: two `ekle` cannot both take the last slot
        full = dispatcher.queue_full(cfg, vault, project)
        if full:
            raise Refused(f"Sıradakiler dolu: {project} projesinde {full[0]} iş sırada (sınır {full[1]}); yenisini "
                          "eklemeden önce biri başlasın ya da iptal edilsin")
        job = launch.create_job(cfg, project, title, brief, tier=tier, model=model, effort=effort, budget=budget,
                                depends=depends, group=group, now=now, durum_dir=durum_dir, extra=fields or None,
                                pilot=True, uzmanlik=uzmanlik)
    if uyari is not None:
        uyari.extend(guard_warnings(cfg, durum_dir, job, brief, explicit_model=bool(model), call_limit=call_limit))
    if check:
        try:
            kontrol.save(durum_dir, job.name, check, now)
        except OSError as e:  # never leave a job whose Kontrol the server cannot find
            jobs.update(vault, job.name, status="iptal",
                        append_result="Kontrol sunucuya kaydedilemedi; iş iptal edildi, yeniden ekleyin.",
                        fields={"bitis": _stamp(now), "karne": "yok"})
            raise Refused(f"cannot store the Kontrol in durum/kontroller ({type(e).__name__}); the job was cancelled")
    warning = None
    try:  # the trusted brief: an escalation is built only from it (never from the vault note)
        kontrol.save_brief(durum_dir, job.name, title, brief, group, now)
    except OSError as e:
        warning = f"the trusted brief was not stored ({type(e).__name__}); the job cannot be escalated"
    return job, warning


def _karne_rows(cfg):
    """The Karne rows for the guard-rails (an unreadable scorecard gives no evidence, never an error)."""
    try:
        return karne._rows(os.path.expanduser(cfg["vault_ofis"]))
    except (OSError, UnicodeDecodeError):
        return []


def guard_warnings(cfg, durum_dir, job, brief, explicit_model=False, call_limit=None):
    """The guard-rail warnings of a job just added, from its server record (the tier, model and budget it really
    got)."""
    rec = records.load(durum_dir, job.name) or {}
    return uyarilar.ekle_uyarilari(cfg, job.meta.get("proje", ""), rec.get("katman") or job.meta.get("katman", ""),
                                   rec.get("model") or job.meta.get("model", ""), explicit_model,
                                   rec.get("butce_usd") or job.meta.get("butce_usd"), brief, _karne_rows(cfg),
                                   call_limit=call_limit)


def cmd_ekle(cfg, args, now, durum_dir):
    if not args.proje or not args.baslik:
        raise Refused("--proje and --baslik are required (on the command line or in the brief file)")
    brief = {"hedef": args.hedef if args.hedef is not None else args.gorev, "neden": args.neden,
             "kisitlar": args.kisitlar, "kapsam_disi": args.kapsam_disi, "kontrol": args.kontrol}
    depends = [d for d in (args.bagimli or "").split(",") if d.strip()]
    calls = _call_limit(args.cagri) if args.cagri is not None else None
    warnings = []
    job, warning = add_job(cfg, durum_dir, args.proje, args.baslik, brief, now, tier=args.katman, model=args.model,
                           effort=args.effort, budget=args.butce, depends=depends, group=args.grup,
                           beklet=args.beklet, deneme=args.deneme, call_limit=calls, uyari=warnings,
                           uzmanlik=args.uzmanlik)
    rec = records.load(durum_dir, job.name) or {}
    out = {"is": job.name, "durum": job.meta.get("durum"), "katman": job.meta.get("katman"),
           "model": job.meta.get("model", ""), "effort": job.meta.get("effort", ""),
           "uzmanlik": rec.get("uzmanlik", ""), "uzmanlik_nedeni": rec.get("uzmanlik_nedeni", "")}
    if warning:
        out["uyari"] = warning
    if args.beklet:
        out["beklet"] = "evet"
    if args.deneme:
        out["deneme"] = "evet"
    if warnings:
        out["uyarilar"] = warnings
    return out


def start_job(cfg, name, durum_dir, claude_bin=None, now=None, suffix=None, worktree=False, permission_mode=None):
    """Starts a queued job: `ofis.py baslat` and the dispatcher take this one path. A `kod` job needs its trusted
    Kontrol; the WIP limits are checked under the job lock right before the start (dispatcher.start_gate). Raises
    launch.Refused (dispatcher.LimitReached for a limit)."""
    try:
        job = jobs.load(os.path.expanduser(cfg["vault_ofis"]), name)
    except jobs.JobError as e:
        raise launch.Refused(str(e)) from e
    tier = (records.load(durum_dir, job.name) or {}).get("katman") or job.meta.get("katman")
    if tier == launch.KOD_TIER and kontrol.load(durum_dir, job.name) is None:
        raise launch.Refused(launch.NO_KONTROL)
    if records.server_value(durum_dir, job.name, "akis"):  # a workflow step (phase 4): its gate, prompt, executor
        return akis.start_step(cfg, durum_dir, job.name, claude_bin=claude_bin, now=now, suffix=suffix,
                               worktree=worktree, permission_mode=permission_mode)
    return launch.start_job(cfg, job.name, claude_bin=claude_bin, now=now, suffix=suffix, worktree=worktree,
                            permission_mode=permission_mode, durum_dir=durum_dir,
                            gate=dispatcher.start_gate(cfg, durum_dir, worktree=worktree))


def cmd_baslat(cfg, args, now, claude_bin, suffix, durum_dir):
    _job(cfg, args.is_)
    result = start_job(cfg, args.is_, durum_dir, claude_bin=claude_bin, now=now, suffix=suffix,
                       worktree=args.worktree, permission_mode=args.permission_mode)
    return {"is": result["is"], "oturum": result.get("name", ""), "kisa_id": result.get("short_id", ""),
            "durum": result.get("durum", "calisiyor")}


def cmd_akis(cfg, args, now, durum_dir):
    """A workflow from a trusted template (bin/akis.py)."""
    if not args.proje or not args.baslik:
        raise Refused("--proje and --baslik are required (on the command line or in the brief file)")
    total = None
    if args.butce is not None:
        try:
            total = float(args.butce)
        except ValueError:
            raise Refused(f"invalid budget: {args.butce!r}") from None
        if not math.isfinite(total):
            raise Refused(f"invalid budget: {args.butce!r}")
    brief = {"hedef": args.hedef, "neden": args.neden, "kisitlar": args.kisitlar, "kapsam_disi": args.kapsam_disi,
             "kontrol": args.kontrol}
    check = (args.kontrol or "").strip()
    result = akis.create(cfg, durum_dir, args.sablon, args.proje, args.baslik, brief, total=total, now=now,
                         deneme=args.deneme, uzmanlik_=args.uzmanlik)
    warnings = uyarilar.akis_uyarilari(args.proje, result.get("paylar"), _karne_rows(cfg))
    weak = uyarilar.kontrol_uyarisi(check) if check else None
    if weak:
        warnings.append(weak)
    if warnings:
        result["uyarilar"] = warnings
    return result



def cmd_zamanla(cfg, args, now, durum_dir):
    """Scheduled jobs (bin/zamanla.py). Returns a dict (one JSON line) or, for listele, the table text."""
    vault = os.path.expanduser(cfg["vault_ofis"])
    if args.zamanla_komut == "listele":
        return zamanla.table(durum_dir, now)
    if args.zamanla_komut == "ekle":
        if not args.ad or not args.proje or not args.baslik or not args.saat:
            raise Refused("--ad, --proje, --baslik and --saat are required (on the command line or in the brief file)")
        brief = {"hedef": args.hedef, "neden": args.neden, "kisitlar": args.kisitlar,
                 "kapsam_disi": args.kapsam_disi, "kontrol": args.kontrol}
        if args.butce is not None:
            try:
                if not math.isfinite(float(args.butce)):
                    raise ValueError
            except ValueError:
                raise Refused(f"invalid budget: {args.butce!r}") from None
        data = zamanla.create(cfg, durum_dir, now, args.ad, args.proje, args.baslik, brief, katman=args.katman,
                              model=args.model, effort=args.effort, butce=args.butce, saat=args.saat,
                              gunler=args.gunler, deneme=args.deneme, uzmanlik=args.uzmanlik)
        model = data["model"] or launch.tier_entry(cfg, data["proje"], data["katman"])[0]
        warnings = uyarilar.ekle_uyarilari(cfg, data["proje"], data["katman"], model, bool(args.model),
                                           data["butce_usd"], dict(data["brief"], kontrol=data["kontrol"]),
                                           _karne_rows(cfg))
    elif args.zamanla_komut == "durdur":
        data = zamanla.pause(durum_dir, args.ad, now)
    elif args.zamanla_komut == "devam":
        data = zamanla.resume(durum_dir, args.ad, now)
    else:
        data = zamanla.remove(durum_dir, args.ad, now)
    nxt = zamanla.upcoming(data, now)
    out = {"ad": data["ad"], "proje": data["proje"], "durum": data["durum"], "zaman": zamanla.when_text(data),
           "sonraki": f"{nxt:%Y-%m-%d %H:%M}" if nxt else ""}
    if args.zamanla_komut == "ekle":
        if data.get("deneme"):
            out["deneme"] = "evet"
        # each run is routed when it is added (the same inputs give the same choice); this is that choice now
        choice = launch.route(cfg, data["proje"], data["baslik"], data["brief"], data["katman"],
                              data.get("uzmanlik") or None)
        out["uzmanlik"], out["uzmanlik_nedeni"] = choice["uzmanlik"], choice["neden"]
        if warnings:
            out["uyarilar"] = warnings
    try:
        zamanla.write_note(vault, data, now)
    except OSError as e:
        out["uyari"] = f"the display note was not written ({type(e).__name__}); the server writes it on its next pass"
    return out


def cmd_akis_karar(cfg, args, now, durum_dir):
    """The owner's decision on a stopped workflow: devam (the stopped step counts as passed) or iptal (open steps
    cancelled; their undelivered answers dropped and open questions closed — stop running sessions separately)."""
    result = akis.decide(cfg, durum_dir, args.grup, args.karar, now)
    if args.karar == "iptal":
        vault = os.path.expanduser(cfg["vault_ofis"])
        for name in result.get("iptal_edilen", []):
            drop_session_mail(durum_dir, records.server_value(durum_dir, name, "oturum"))
            close_open_questions(vault, name, now, "akış iptal edildi")
    return result


def _set_queued(cfg, durum_dir, name, fields, log=None):
    """Sets fields on a `sirada` job's record (created from the note for a job from before records) and note."""
    vault = os.path.expanduser(cfg["vault_ofis"])
    with jobs.locked(vault):
        job = _job(cfg, name)
        if job.meta.get("durum") != "sirada":
            raise Refused(f"{job.name} is '{job.meta.get('durum')}'; only a 'sirada' job can be changed")
        if records.load(durum_dir, job.name) is None:
            records.update(durum_dir, job.name, records.from_note(job))
        records.update(durum_dir, job.name, fields)
        try:
            return jobs.update(vault, job.name, fields=fields, expect=("sirada",))
        except jobs.JobError as e:
            raise Refused(str(e)) from e


def cmd_serbest(cfg, args, durum_dir):
    """Releases a held job (beklet); the dispatcher starts it when its turn comes."""
    job = _job(cfg, args.is_)
    if job.meta.get("durum") == "sirada" and not dispatcher.is_held(durum_dir, job):
        raise Refused(f"{job.name} is not held (no beklet)")
    job = _set_queued(cfg, durum_dir, job.name, {"beklet": ""})
    return {"is": job.name, "beklet": ""}


def cmd_bagimli(cfg, args, durum_dir):
    """Drops a dependency of a queued job (after the owner decided); engel is recomputed by the dispatcher."""
    job = _job(cfg, args.is_)
    deps = dispatcher.dependencies(durum_dir, job)
    try:
        drop = jobs.check_name(args.kaldir.strip())
    except jobs.JobError as e:
        raise Refused(str(e)) from e
    if job.meta.get("durum") == "sirada" and drop not in deps:
        raise Refused(f"{jobs.stem(drop)} is not a dependency of {job.name}")
    rest = ",".join(d for d in deps if d != drop)
    job = _set_queued(cfg, durum_dir, job.name, {"bagimli": rest, "engel": ""})
    return {"is": job.name, "bagimli": rest}


def read_input_file(durum_dir, path, cwd):
    """(text, path) of an input file: a plain file (no symlink) directly in durum/taslak/, UTF-8, at most 64 KB.
    A relative path is taken from the caller's working folder."""
    if not isinstance(path, str) or not path.strip():
        raise Refused("input file path is empty")
    full = os.path.abspath(os.path.join(cwd, path))
    folder = os.path.realpath(os.path.join(durum_dir, SCRATCH))
    if os.path.islink(full) or not os.path.isfile(full):
        raise Refused(f"no such input file (a plain file, not a link): {path}")
    if os.path.dirname(os.path.realpath(full)) != folder:
        raise Refused(f"input files must be directly in durum/{SCRATCH}/: {path}")
    with open(full, "rb") as f:
        raw = f.read(MAX_INPUT_FILE + 1)
    if len(raw) > MAX_INPUT_FILE:
        raise Refused(f"input file is larger than {MAX_INPUT_FILE // 1024} KB")
    try:
        return raw.decode("utf-8"), full
    except UnicodeDecodeError:
        raise Refused("input file is not UTF-8") from None


def _remove_input(path):
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _text_arg(value, file_path, durum_dir, cwd, stdin=None, what="text"):
    """The text of a command: the argument ("-" = stdin when stdin is given) or the --dosya file, exactly one."""
    if (value is None) == (file_path is None):
        raise Refused(f"give the {what} either as an argument or with --dosya (exactly one)")
    if file_path is not None:
        return read_input_file(durum_dir, file_path, cwd)
    return (stdin.read() if stdin is not None and value == "-" else value), None


def cmd_yakala(cfg, url, note, durum_dir, now, log):
    """`ofis.py yakala`: the CEO's path of the Yakala box (bin/yakala.py) — the same checks, limits and job as the page."""
    def add(project, title, brief, now, **kw):
        return add_job(cfg, durum_dir, project, title, brief, now, **kw)
    try:
        return yakala.olustur(cfg, durum_dir, url=url, not_=note, kaynak="ceo", now=now, add=add, log=log)
    except yakala.Refused as e:
        raise Refused(str(e)) from None


def cmd_talimat_denetimi(cfg, durum_dir, now, log):
    """`ofis.py talimat-denetimi`: one prompt audit of the current mapping now (bin/talimat_denetimi.py)."""
    def add(project, title, brief, now, **kw):
        return add_job(cfg, durum_dir, project, title, brief, now, **kw)
    try:
        return talimat_denetimi.olustur(cfg, durum_dir, "elle", now, add, log=log)
    except talimat_denetimi.Refused as e:
        raise Refused(str(e)) from None


def cmd_ceo_yenile(durum_dir, now):
    """Writes the flag durum/ceo-yenile (bin/ceo.py YENILE_DOSYASI): the server's next delivery to an idle or dormant CEO
    starts a fresh CEO session with the handoff note (reason "elle"), which reads the current CLAUDE.md and system text.
    Idempotent; the server removes the flag once a CEO session was started. Nothing else changes."""
    zaten = os.path.lexists(os.path.join(durum_dir, CEO_YENILE))
    if not zaten:
        write_json_atomic(durum_dir, CEO_YENILE, {"istendi": _stamp(now)})
    return {"ceo_yenile": True, "zaten_istenmis": zaten,
            "dosya": os.path.join(os.path.basename(durum_dir), CEO_YENILE)}


def cmd_bildir(args, durum_dir, now, stdin, cwd):
    if not SESSION_NAME.fullmatch(args.oturum or ""):
        raise Refused("invalid session name (expected ofis-<lowercase letters, digits, dashes>)")
    if args.tur not in REPORT_TYPES:
        raise Refused(f"type must be one of {', '.join(REPORT_TYPES)}")
    text, source = _text_arg(args.metin, args.dosya, durum_dir, cwd, stdin)
    text = (text or "").strip()
    if not text:
        raise Refused("text is empty")
    if len(text) > MAX_REPORT:
        text = text[:REPORT_KEEP].rstrip() + SHORTENED
    folder = os.path.join(durum_dir, "gelen")
    for _ in range(5):
        message_id = f"{time.time_ns():019d}-{secrets.token_hex(4)}"  # name order = arrival order
        try:
            write_json_atomic(folder, message_id + ".json",
                              {"id": message_id, "oturum": args.oturum, "tur": args.tur, "metin": text,
                               "zaman": _stamp(now), "cwd": cwd, "cwd_gercek": os.path.realpath(cwd)})
            _remove_input(source)
            return {"bildirildi": message_id}
        except FileExistsError:
            continue
    raise Refused("no free inbox file name")


def _decision_path(vault, note):
    if not isinstance(note, str) or not note.endswith(".md"):
        note = f"{note}.md" if isinstance(note, str) else note
    if not isinstance(note, str) or not NOTE_NAME.fullmatch(note) or note.startswith(".") or ".." in note:
        raise Refused(f"invalid decision note name: {note!r}")
    folder = os.path.join(vault, "Kararlar")
    path = os.path.join(folder, note)
    if os.path.islink(path) or not os.path.isfile(path) or \
            os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        raise Refused(f"no such decision note: {note}")
    return note, path


def _pending_for_job(vault, job_name, except_note):
    folder = os.path.join(vault, "Kararlar")
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for n in names:
        if n == except_note or not n.endswith(".md") or n.startswith("."):
            continue
        p = os.path.join(folder, n)
        if os.path.islink(p) or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                _, meta, _ = jobs.parse(f.read(64 * 1024))
        except (OSError, UnicodeDecodeError):
            continue
        if meta.get("durum") == "bekliyor" and meta.get("is") == job_name:
            out.append(n)
    return out


def question_line(body):
    """The first line of a decision's ## Soru (without the "> " quote), for the answer's "Soru:" line."""
    for line in jobs.section(body, "Soru").splitlines():
        line = line.strip()
        if line.startswith(">"):
            line = line[1:].strip()
        if line:
            line = " ".join(line.split())
            return line if len(line) <= 300 else line[:300].rstrip() + " …"
    return "(soru metni yok)"


def _outbox_exists(folder, msg_id):
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    return any(n == f"{msg_id}.json" or n.endswith(f"-{msg_id}.json") for n in names)


# Kararlar notes no project session waits for: a line for the project's CLAUDE.md or REVIEW.md (the CEO writes them),
# the Ar-Ge's reviewer suggestion (bin/arge.py DENETCI_ONERISI, written by the server) and the CEO's own question
# (`ofis.py sor`); the answer goes to the CEO only
CEO_QUESTION = "ceo-sorusu"
CEO_DECISIONS = ("claude-md-onerisi", "review-md-onerisi", "denetci-onerisi",
                 talimat_denetimi.TUR,  # the prompt audit's card (bin/talimat_denetimi.py)
                 CEO_QUESTION)
MODEL_DECISIONS = (model_secimi.PROPOSAL, model_secimi.RESULT)  # phase 8: written by the server, no session either
ADVISOR_DECISIONS = danisman.DECISIONS  # the advisor pilot's cards (bin/danisman.py): no session either


def cmd_cevapla(cfg, args, durum_dir, now, cwd, config_path=None):
    vault = os.path.expanduser(cfg["vault_ofis"])
    note, path = _decision_path(vault, args.karar)
    answer, source_file = _text_arg(args.cevap, args.dosya, durum_dir, cwd, what="answer")
    answer = (answer or "").strip()
    if not answer:
        raise Refused("answer is empty")
    if len(answer) > MAX_ANSWER:
        raise Refused(f"answer is limited to {MAX_ANSWER} characters")
    # One lock for the whole answer: a question the post office writes meanwhile is either seen by the scan below
    # or written after the job is back to calisiyor (and then sets it to karar-bekliyor again).
    with jobs.locked(vault):
        with open(path, encoding="utf-8") as f:
            lines, meta, body = jobs.parse(f.read())
        if meta.get("durum") != "bekliyor" and not (meta.get("durum") == MUDUR_DURUM and not meta.get("tur")):
            raise Refused(f"{note} is '{meta.get('durum')}', not 'bekliyor' (already answered?)")
        if meta.get("tur") == "akis-onay":  # a workflow's approval card: no session to answer
            result = akis.answer_approval(cfg, durum_dir, note, meta, answer, now)  # checks the card first
            jobs._set_line(lines, "durum", "cevaplandi")
            jobs._set_line(lines, "cevaplandi", _stamp(now))
            body = jobs.set_section(body, sahip.cevap_basligi(cfg), answer, before="İlgili Sayfalar")
            jobs._write_atomic(path, jobs.render(lines, body))
            _remove_input(source_file)
            return {"karar": note, **result}
        if meta.get("tur") in MODEL_DECISIONS:
            # phase 8: the server's model card; the server state decides (it checks the card first, then the pilot
            # starts, the proposal closes, or — a plain yes on a successful pilot — the mapping changes)
            try:
                result = model_secimi.answer(cfg, durum_dir, note, meta, answer, now, akis.is_approval(answer),
                                             config_path=config_path)
            except model_secimi.Refused as e:
                raise Refused(str(e)) from None
            jobs._set_line(lines, "durum", "cevaplandi")
            jobs._set_line(lines, "cevaplandi", _stamp(now))
            body = jobs.set_section(body, sahip.cevap_basligi(cfg), answer, before="İlgili Sayfalar")
            jobs._write_atomic(path, jobs.render(lines, body))
            _remove_input(source_file)
            return {"karar": note, **result}
        if meta.get("tur") in ADVISOR_DECISIONS:
            # the advisor pilot's card: a plain yes on the proposal starts the pilot (state + the switch), on a
            # successful result it writes the tier's advisor; anything else closes the card
            try:
                result = danisman.answer(cfg, durum_dir, note, meta, answer, now, akis.is_approval(answer),
                                         config_path=config_path)
            except (danisman.Refused, model_secimi.Refused) as e:
                raise Refused(str(e)) from None
            jobs._set_line(lines, "durum", "cevaplandi")
            jobs._set_line(lines, "cevaplandi", _stamp(now))
            body = jobs.set_section(body, sahip.cevap_basligi(cfg), answer, before="İlgili Sayfalar")
            jobs._write_atomic(path, jobs.render(lines, body))
            _remove_input(source_file)
            return {"karar": note, **result}
        if meta.get("tur") in CEO_DECISIONS:
            # a decision the CEO itself asked (phase 5: a CLAUDE.md proposal): no session waits for it; the answer is
            # recorded and handed back to the CEO (onay: a plain approval), which acts on it with normal jobs
            jobs._set_line(lines, "durum", "cevaplandi")
            jobs._set_line(lines, "cevaplandi", _stamp(now))
            body = jobs.set_section(body, sahip.cevap_basligi(cfg), answer, before="İlgili Sayfalar")
            jobs._write_atomic(path, jobs.render(lines, body))
            _remove_input(source_file)
            result = {"karar": note, "tur": meta["tur"], "onay": akis.is_approval(answer), "cevap": answer}
            if meta["tur"] == CEO_QUESTION:
                choice = answer_choice(answer, [o["kod"] for o in jobs.question_options(body)])
                if choice:
                    result["secim"] = choice
            return result
        override = meta.get("durum") == MUDUR_DURUM
        unvan = mudur.ID_UNVAN.get(meta.get("karar_veren") or "", "") if override else ""
        line = (f"Not: Bu cevap {sahip.in_(cfg)}; {unvan + chr(39) + 'nün' if unvan else 'müdürün'} önceki cevabının yerine "
                "geçer, bunu uygula." if override else None)
        if override:
            jobs._set_line(lines, "karar_veren", "deniz")
            jobs._set_line(lines, "deniz_degistirdi", _stamp(now))
        result = answer_session(vault, durum_dir, note, path, lines, body, answer, now, note_line=line, meta=meta)
        if override:
            result["mudur_cevabi_degisti"] = True
    _remove_input(source_file)
    return {"karar": note, **result}


# --- `sor`: the CEO's own question to the owner (owner decision 2026-11-14) ---
SOR_FIELDS = ("baslik", "soru", "secenekler", "proje", "ilgili")
MAX_SOR_TITLE = 120
MAX_SOR_QUESTION = 3000
MAX_OPTIONS = 5
MAX_OPTION_TEXT = 300
MAX_RELATED = 10
OPTION_CODES = "ABCDE"
RELATED_NAME = re.compile(r"[\w.-]{1,150}")  # a job note's file name: no brackets, pipes, hashes or slashes
NO_OPTIONS = "Seçenek yok; cevabını serbestçe yaz."


def _one_line(value):
    return " ".join(str(value).split())


def answer_choice(answer, codes):
    """The option an answer names ("A", "A)", "A) …", "a — …", "B şıkkı"), else ""."""
    m = re.match(r"\s*([A-Ea-e])(?:\s*$|\s*[).:\-—–]|\s+şıkkı)", answer or "")
    code = m.group(1).upper() if m else ""
    return code if code in codes else ""


def _sor_input(cfg, data):
    if not isinstance(data, dict):
        raise Refused("the question file must hold one JSON object")
    unknown = sorted(set(data) - set(SOR_FIELDS))
    if unknown:
        raise Refused(f"unknown question file fields: {', '.join(unknown)} (allowed: {', '.join(SOR_FIELDS)})")
    title, question = data.get("baslik"), data.get("soru")
    if not isinstance(title, str) or not _one_line(title):
        raise Refused("baslik is required (one line)")
    title = _one_line(title)
    if len(title) > MAX_SOR_TITLE:
        raise Refused(f"baslik is limited to {MAX_SOR_TITLE} characters")
    if not isinstance(question, str) or not question.strip():
        raise Refused("soru is required")
    question = question.strip()
    if len(question) > MAX_SOR_QUESTION:
        raise Refused(f"soru is limited to {MAX_SOR_QUESTION} characters")
    project = data.get("proje")
    if project in (None, ""):
        project = "ofis"
    if not isinstance(project, str) or (project != "ofis" and project not in (cfg.get("projects") or {})):
        raise Refused(f"unknown project: {project!r} (a project of ofis.json, or ofis)")
    if not launch.PROJECT_NAME.fullmatch(project):  # it becomes part of the note's file name (Codex, 2026-11-14)
        raise Refused(f"invalid project name: {project!r}")
    options = data.get("secenekler")
    options = [] if options is None else options
    if not isinstance(options, list):
        raise Refused("secenekler must be a list of {kod, metin}")
    if len(options) > MAX_OPTIONS:
        raise Refused(f"at most {MAX_OPTIONS} options")
    clean = []
    for o in options:
        if not isinstance(o, dict) or set(o) - {"kod", "metin"}:
            raise Refused("each option is {kod, metin}")
        code, text = o.get("kod"), o.get("metin")
        if not isinstance(code, str) or code.strip().upper() not in OPTION_CODES or len(code.strip()) != 1:
            raise Refused(f"option kod must be one of {', '.join(OPTION_CODES)}: {code!r}")
        code = code.strip().upper()
        if code in {c["kod"] for c in clean}:
            raise Refused(f"option {code} appears twice")
        if not isinstance(text, str) or not _one_line(text):
            raise Refused(f"option {code} has no metin")
        text = _one_line(text)
        if len(text) > MAX_OPTION_TEXT:
            raise Refused(f"option text is limited to {MAX_OPTION_TEXT} characters")
        clean.append({"kod": code, "metin": text})
    related = data.get("ilgili")
    related = [] if related is None else related
    if not isinstance(related, list) or len(related) > MAX_RELATED:
        raise Refused(f"ilgili must be a list of at most {MAX_RELATED} note names")
    links = []
    for r in related:
        name = r[:-3] if isinstance(r, str) and r.endswith(".md") else r
        if not isinstance(name, str) or not RELATED_NAME.fullmatch(name) or name.startswith(".") or ".." in name:
            raise Refused(f"invalid note name in ilgili: {r!r}")
        if name not in links:
            links.append(name)
    return title, question, project, clean, links


def question_card(title, question, project, options, links, now):
    """The text of a ceo-sorusu card. The CEO's words are kept as data: the question quoted with "> " (it cannot open
    a section), the title and each option one line."""
    lines = ["tags: [ofis, karar, ceo-sorusu]"]
    for key, value in (("proje", project), ("durum", "bekliyor"), ("tur", CEO_QUESTION), ("soruldu", _stamp(now)),
                       ("secenekler", ",".join(o["kod"] for o in options))):
        jobs._set_line(lines, key, value)
    quoted = "\n".join("> " + line if line.strip() else ">" for line in question.splitlines())
    choices = "\n".join(f"- {o['kod']}) {o['metin']}" for o in options) or NO_OPTIONS
    related = "\n".join(f"- [[{n}]]" for n in links) or "- [[OFIS/README]]"
    body = (f"# {title.lstrip('#').strip() or 'CEO sorusu'}\n\n## Soru\n{quoted}\n\n## Seçenekler\n{choices}\n\n"
            f"## İlgili Sayfalar\n{related}\n")
    return jobs.render(lines, body)


def cmd_sor(cfg, args, durum_dir, now, cwd):
    """`ofis.py sor --dosya durum/taslak/<f>.json`: the CEO's question to the owner as a pending Kararlar card."""
    text, source_file = read_input_file(durum_dir, args.dosya, cwd)
    try:
        data = json.loads(text)
    except ValueError:
        raise Refused("the question file is not valid JSON") from None
    title, question, project, options, links = _sor_input(cfg, data)
    vault = os.path.expanduser(cfg["vault_ofis"])
    folder = os.path.join(vault, "Kararlar")
    with jobs.locked(vault):
        base = f"{now:%Y-%m-%d}-{project}-{CEO_QUESTION}"
        note = next((f"{base}{s}.md" for s in [""] + [f"-{i}" for i in range(2, 100)]
                     if not os.path.lexists(os.path.join(folder, f"{base}{s}.md"))), None)
        if note is None:
            raise Refused("no free decision note name")
        try:
            model_secimi._write_note(vault, note, question_card(title, question, project, options, links, now))
        except model_secimi.Refused as e:
            raise Refused(str(e)) from None
    _remove_input(source_file)
    return {"karar": note, "tur": CEO_QUESTION, "proje": project, "secenekler": [o["kod"] for o in options]}


def answer_session(vault, durum_dir, note, path, lines, body, answer, now, head=ANSWER_HEAD, msg_prefix="cevap",
                   section=None, section_text=None, status="cevaplandi", stamp_key="cevaplandi",
                   note_line=None, tail=None, meta=None):
    """The answer path of `cevapla` for a question a session waits for, shared with the managers' answers
    (bin/mudur.py). The caller holds the job lock and has read the note (lines, meta, body). 1. the outbox message
    (id <msg_prefix>-<note>, so a re-run never sends twice): "<head> <note>", an optional note line, "Soru: …",
    "Cevap: …", an optional tail; 2. the note: durum, the time under stamp_key, `## <section>` before İlgili Sayfalar;
    3. the job back to calisiyor when it waits for this answer and no other question of it is open. Returns {oturum,
    is, is_durumu, giden, iletilmeyecek}; iletilmeyecek = the job is no longer running (the server never delivers to
    it; the answer is only recorded)."""
    meta = meta if meta is not None else jobs.parse(jobs.render(lines, body))[1]
    source = meta.get("kaynak_oturum", "")
    if not SESSION_NAME.fullmatch(source):
        raise Refused(f"{note} has no valid kaynak_oturum; relay the answer by hand")
    job_name = meta.get("is") or None
    # 1. outbox first, under an id derived from the note: a re-run after a failure below never sends twice.
    msg_id = f"{msg_prefix}-{note[:-3]}"
    text = f"{head} {note[:-3]}\n" + (f"{note_line}\n" if note_line else "") + \
        f"Soru: {question_line(body)}\nCevap: {answer}" + (f"\n{tail}" if tail else "")
    outbox_dir = os.path.join(durum_dir, "giden")
    if not _outbox_exists(outbox_dir, msg_id):
        write_json_atomic(outbox_dir, f"{time.time_ns():019d}-{msg_id}.json",
                          {"id": msg_id, "oturum": source, "metin": text, "karar": note, "is": job_name,
                           "zaman": _stamp(now)})
    # 2. the decision note
    jobs._set_line(lines, "durum", status)
    jobs._set_line(lines, stamp_key, _stamp(now))
    body = jobs.set_section(body, section or sahip.cevap_basligi(), section_text if section_text is not None else answer,
                            before="İlgili Sayfalar")
    jobs._write_atomic(path, jobs.render(lines, body))
    # 3. the job goes back to work unless another question of it is still open
    job_status = None
    if job_name:
        try:
            job = jobs.find(vault, job_name)
            if job and job.meta.get("durum") == "karar-bekliyor" and not _pending_for_job(vault, job.name, note):
                job = jobs.update(vault, job.name, status="calisiyor", expect=("karar-bekliyor",))
            job_status = job.meta.get("durum") if job else None
        except jobs.JobError:
            job_status = None
    return {"oturum": source, "is": job_name, "is_durumu": job_status, "giden": msg_id,
            "iletilmeyecek": job_status not in jobs.ACTIVE_STATUSES}


def _job(cfg, name):
    try:
        return jobs.load(os.path.expanduser(cfg["vault_ofis"]), name)
    except jobs.JobError as e:
        raise Refused(str(e)) from e


def _move_unique(path, folder):
    os.makedirs(folder, exist_ok=True)
    base = os.path.basename(path)
    target, n = os.path.join(folder, base), 2
    while os.path.lexists(target):
        target = os.path.join(folder, f"{base[:-5]}-{n}.json")
        n += 1
    os.replace(path, target)


def drop_session_mail(durum_dir, session):
    """Moves the session's undelivered answers to giden/reddedilen and empties its delivery queue (durum/kuyruk).
    The server also refuses to deliver to a job that is not running; this keeps nothing waiting. Returns the count
    of answers moved."""
    if not SESSION_NAME.fullmatch(session or ""):
        return 0
    outbox = os.path.join(durum_dir, "giden")
    moved = 0
    try:
        entries = sorted(os.scandir(outbox), key=lambda e: e.name)
    except OSError:
        entries = []
    for e in entries:
        if not e.name.endswith(".json") or e.name.startswith(".") or not e.is_file(follow_symlinks=False):
            continue
        try:
            with open(e.path, encoding="utf-8") as f:
                msg = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(msg, dict) and msg.get("oturum") == session:
            _move_unique(e.path, os.path.join(outbox, "reddedilen"))
            moved += 1
            if isinstance(msg.get("duyuru"), str) and duyuru.ID.fullmatch(msg["duyuru"]):
                try:  # an announcement for this session is not delivered any more: its record says so
                    duyuru.mark(durum_dir, msg["duyuru"], session, duyuru.ILETILEMEDI, neden="iş kapandı")
                except (OSError, ValueError):
                    pass
    queue = os.path.join(durum_dir, "kuyruk", f"{session}.jsonl")
    if os.path.isfile(queue) and not os.path.islink(queue):
        tmp = f"{queue}.{os.getpid()}.tmp"
        open(tmp, "w").close()
        os.replace(tmp, queue)
    return moved


def close_open_questions(vault, job_name, now, reason):
    """Sets every `bekliyor` Kararlar note of the job to `kapandi` (the page card disappears). Returns their names."""
    closed = []
    with jobs.locked(vault):
        for note in sorted(_pending_for_job(vault, job_name, None)):
            path = os.path.join(vault, "Kararlar", note)
            with open(path, encoding="utf-8") as f:
                lines, meta, body = jobs.parse(f.read())
            if meta.get("durum") != "bekliyor":
                continue
            jobs._set_line(lines, "durum", "kapandi")
            jobs._set_line(lines, "kapandi", _stamp(now))
            jobs._set_line(lines, "kapanis_nedeni", reason)
            jobs._write_atomic(path, jobs.render(lines, body))
            closed.append(note)
    return closed


def _wind_down(cfg, job, durum_dir, now, reason):
    vault = os.path.expanduser(cfg["vault_ofis"])
    dropped = drop_session_mail(durum_dir, job.meta.get("oturum", ""))
    closed = close_open_questions(vault, job.name, now, reason)
    return {"dusen_cevaplar": dropped, "kapanan_kararlar": closed}


def cmd_bitir(cfg, args, now, durum_dir):
    job = _job(cfg, args.is_)
    if job.meta.get("durum") not in jobs.ACTIVE_STATUSES:
        raise Refused(f"{job.name} is '{job.meta.get('durum')}'; only a started job can be finished")
    try:
        job = jobs.update(os.path.expanduser(cfg["vault_ofis"]), job.name, status="bitti",
                          fields={"bitis": _stamp(now)}, append_result=args.sonuc, expect=jobs.ACTIVE_STATUSES)
    except jobs.JobError as e:
        raise Refused(str(e)) from e
    return {"is": job.name, "durum": "bitti", "oturum": job.meta.get("oturum", ""),
            **_wind_down(cfg, job, durum_dir, now, "iş bitirildi")}


def cmd_iptal(cfg, args, now, durum_dir):
    job = _job(cfg, args.is_)
    allowed = ("sirada",) + jobs.ACTIVE_STATUSES
    if job.meta.get("durum") not in allowed:
        raise Refused(f"{job.name} is '{job.meta.get('durum')}'; it cannot be cancelled")
    try:
        job = jobs.update(os.path.expanduser(cfg["vault_ofis"]), job.name, status="iptal",
                          fields={"bitis": _stamp(now)}, expect=allowed)
    except jobs.JobError as e:
        raise Refused(str(e)) from e
    return {"is": job.name, "durum": "iptal", "oturum": job.meta.get("oturum", ""),
            **_wind_down(cfg, job, durum_dir, now, "iş iptal edildi")}


def _budget_value(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise Refused(f"invalid budget: {value!r}") from None
    if not 0 < number <= 1000:  # also refuses nan
        raise Refused("budget must be between 0 and 1000 USD")
    return f"{number:g}"


def _call_limit(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise Refused(f"invalid call limit: {value!r}") from None
    if not 0 < number <= MAX_CALL_LIMIT:
        raise Refused(f"call limit must be between 1 and {MAX_CALL_LIMIT}")
    return number


def cmd_butce(cfg, args, durum_dir, log):
    """Changes the limits on the server record (what the server enforces) and on the note (display)."""
    if args.usd is None and args.cagri is None:
        raise Refused("give a budget in USD and/or --cagri N")
    fields = {}
    if args.usd is not None:
        fields["butce_usd"] = _budget_value(args.usd)
    if args.cagri is not None:
        fields["max_cagri"] = _call_limit(args.cagri)
    vault = os.path.expanduser(cfg["vault_ofis"])
    allowed = ("sirada", "tikandi") + jobs.ACTIVE_STATUSES
    with jobs.locked(vault):
        job = _job(cfg, args.is_)
        if job.meta.get("durum") not in allowed:
            raise Refused(f"{job.name} is '{job.meta.get('durum')}', expected one of {', '.join(allowed)}")
        if records.load(durum_dir, job.name) is None:
            records.ensure(durum_dir, job, log)
            if records.load(durum_dir, job.name) is None:  # a queued job from before records
                records.update(durum_dir, job.name, records.from_note(job))
        rec = records.update(durum_dir, job.name, fields)
        try:
            job = jobs.update(vault, job.name, fields=fields, expect=allowed)
        except jobs.JobError as e:
            raise Refused(str(e)) from e
    return {"is": job.name, "butce_usd": rec.get("butce_usd", ""), "max_cagri": rec.get("max_cagri", "")}


class _NoCorrection(Exception):
    """A quota devam (Step 5) records no correction event."""


def cmd_devam(cfg, args, durum_dir, now, cwd, log=None):
    vault = os.path.expanduser(cfg["vault_ofis"])
    if args.metin is None and args.dosya is None:
        text, source_file = DEFAULT_DEVAM, None
    else:
        text, source_file = _text_arg(args.metin, args.dosya, durum_dir, cwd, what="text")
    text = (text or "").strip()
    if not text:
        raise Refused("text is empty")
    if len(text) > MAX_ANSWER:
        raise Refused(f"text is limited to {MAX_ANSWER} characters")
    with jobs.locked(vault):
        note = _job(cfg, args.is_)
        # Step 5: a `calisiyor` job idle on a quota goes on too, but only after the server asked the CEO about it (it
        # stopped on a quota again after its automatic resumes: kota_devam.soruldu on the server record)
        asked = str(((records.load(durum_dir, note.name) or {}).get(records.QUOTA_RESUME) or {}).get("soruldu") or "")
        on_quota = note.meta.get("durum") == "calisiyor" and bool(asked)
        if note.meta.get("durum") != "tikandi" and not on_quota:
            raise Refused(f"{note.name} is '{note.meta.get('durum')}'; only a 'tikandi' job can go on")
        job = records.trusted(durum_dir, note, log)  # limits, spending, session and folder of the server record
        # an escalated job goes on as its replacement (record, or the note: refusing more is always safe)
        moved = records.server_value(durum_dir, job.name, "yukseltildi") or note.meta.get("yukseltildi") or ""
        if moved:
            raise Refused(f"iş bir üst katmana taşındı: [[{jobs.stem(moved)}]]; devam {jobs.stem(moved)} üzerinden")
        session = job.meta.get("oturum") or ""
        if not SESSION_NAME.fullmatch(session) or not os.path.isabs(job.meta.get("calisma_dizini") or ""):
            raise Refused(f"{job.name} has no session to continue; add a new job instead")
        spend, calls = budget.limits(cfg, job)
        try:
            spent = float(job.meta.get("harcanan_usd") or 0)
            used = int(job.meta.get("cagri") or 0)
        except ValueError:
            spent, used = 0.0, 0
        if spend is not None and spent > spend:
            raise Refused(f"the job is still over its budget (${budget.usd(spent)} / ${budget.usd(spend)}); raise it "
                          f"first with "
                          f"`ofis.py butce {jobs.stem(job.name)} <usd>`")
        if calls is not None and used > calls:
            raise Refused(f"the job is still over its call limit ({used} / {calls}); raise it first with "
                          f"`ofis.py butce {jobs.stem(job.name)} --cagri N`")
        # the WIP limits, like a start: a resumed session works in its folder again (a running job already holds its
        # place)
        if not on_quota:
            try:
                dispatcher.start_gate(cfg, durum_dir, worktree=not dispatcher.in_project_folder(cfg, durum_dir, job),
                                      resume=True)(job)
            except dispatcher.LimitReached as e:
                raise Refused(str(e)) from None
        # outbox first (like cevapla): a failure after it leaves a message for a stuck job, which is never delivered
        msg_id = f"devam-{jobs.stem(job.name)}-{time.time_ns():019d}"
        write_json_atomic(os.path.join(durum_dir, "giden"), f"{time.time_ns():019d}-{msg_id}.json",
                          {"id": msg_id, "oturum": session, "metin": f"{DEVAM_HEAD} {jobs.stem(job.name)}\n{text}",
                           "is": job.name, "zaman": _stamp(now)})
        # the job's scorecard row is written again (replaced in place) at its next final status
        try:
            rounds = int(note.meta.get("devam_sayisi") or 0) + 1
        except ValueError:
            rounds = 1
        try:
            if on_quota:
                # a usage limit says nothing about the work: no devam round, no correction (kota_devam.elle counts it)
                job = jobs.update(vault, job.name, expect=("calisiyor",), fields={})
                rec = (records.load(durum_dir, job.name) or {}).get(records.QUOTA_RESUME) or {}
                records.update(durum_dir, job.name, {records.QUOTA_RESUME: dict(rec, soruldu="",
                                                                                 elle=int(rec.get("elle") or 0) + 1)},
                               create=False)
            else:
                job = jobs.update(vault, job.name, status="calisiyor", expect=("tikandi",),
                                  fields={"bitis": "", "karne": "", "devam_sayisi": rounds})
                if asked:  # an open quota ask never outlives a devam of another kind
                    rec = (records.load(durum_dir, job.name) or {}).get(records.QUOTA_RESUME) or {}
                    records.update(durum_dir, job.name, {records.QUOTA_RESUME: dict(rec, soruldu="")}, create=False)
        except jobs.JobError as e:
            raise Refused(str(e)) from e
        # phase 5: a devam round is a correction event (OFIS/Karne/Duzeltmeler-<proje>.md); never blocks the devam
        try:
            if on_quota:
                raise _NoCorrection
            karne.record_correction(vault, job.meta.get("proje", ""), job.name, "devam", text, msg_id, now)
        except _NoCorrection:
            pass
        except (OSError, ValueError, jobs.JobError) as e:
            if log:
                log(f"correction event of {job.name} not written: {e}")
    _remove_input(source_file)
    return {"is": job.name, "durum": "calisiyor", "oturum": session, "giden": msg_id}


def cmd_deneme_isaretle(cfg, args, durum_dir):
    """One-time, idempotent: marks finished jobs as office self-tests (owner decision 2026-11-12, B3 audit: every job so far
    was a probe of the office itself). Per job: the server record gets `deneme: evet` (a job without a record gets one
    from its note first, so the trusted overlay never empties its values), the note shows it, its Karne row's Deneme
    cell becomes evet (karne.mark_trial); then Ozet.md is written again. Only jobs in Bitenler: a new job takes
    --deneme at ekle. Everything is checked before anything is written."""
    vault = os.path.expanduser(cfg["vault_ofis"])
    done = []
    with jobs.locked(vault):
        found = []
        for name in args.isler:
            job = _job(cfg, name)
            if job.meta.get("durum") not in jobs.FINAL_STATUSES:
                raise Refused(f"{job.name} is '{job.meta.get('durum')}'; only a finished job can be marked (a new job "
                              "takes --deneme at ekle)")
            pilot = records.server_value(durum_dir, job.name, "pilot")
            if pilot:  # its pilot would be measured without it (review 2026-11-12)
                raise Refused(f"{job.name} is a job of the model pilot {pilot}; a pilot job is never marked as a "
                              "self-test (its pilot is measured from it)")
            pilot = records.server_value(durum_dir, job.name, "danisman_pilotu")
            if pilot:
                raise Refused(f"{job.name} is a job of the advisor pilot {pilot}; a pilot job is never marked as a "
                              "self-test (its pilot is measured from it)")
            found.append(job)
        for job in found:
            rec = records.load(durum_dir, job.name)
            if rec is None:
                records.update(durum_dir, job.name, {**records.from_note(job), "deneme": "evet"})
                kayit = "nottan"
            elif rec.get("deneme") == "evet":
                kayit = "zaten"
            else:
                records.update(durum_dir, job.name, {"deneme": "evet"})
                kayit = "vardi"
            if job.meta.get("deneme") != "evet":
                jobs.update(vault, job.name, fields={"deneme": "evet"})
            done.append({"is": job.name, "kayit": kayit, "karne": karne.mark_trial(vault, job.name)})
        if any(d["karne"] == "isaretlendi" for d in done):
            karne.regenerate_summary(vault)
    return {"isaretlenen": done}


def cmd_durum(cfg, durum_dir=None):
    vault = os.path.expanduser(cfg["vault_ofis"])
    rows = []
    order = {jobs.QUEUED: 0, jobs.ACTIVE: 1}
    open_jobs = [j for j in jobs.list_jobs(vault, (jobs.QUEUED, jobs.ACTIVE))]
    open_jobs.sort(key=lambda j: (order[j.folder], j.meta.get("olusturuldu") or j.meta.get("baslangic") or "", j.name))
    done = sorted(jobs.list_jobs(vault, (jobs.DONE,)), key=lambda j: (j.meta.get("bitis") or "", j.name),
                  reverse=True)[:5]
    for j in open_jobs + done:
        m = j.meta
        waiting = dispatcher.waiting_text(durum_dir, j) if m.get("durum") == "sirada" else ""
        rows.append((m.get("durum", ""), jobs.stem(j.name), m.get("proje", ""),
                     "/".join(x for x in (m.get("katman", ""), m.get("model", "")) if x),
                     (m.get("baslik") or "")[:60], waiting))
    header = ("DURUM", "İŞ", "PROJE", "KATMAN/MODEL", "BAŞLIK", "BEKLEME")
    widths = [max(len(r[i]) for r in rows + [header]) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in [header] + rows]
    if not rows:
        lines.append("(iş yok)")
    return "\n".join(lines) + "\n"


def build_parser():
    p = _Parser(prog="ofis.py", description="Job commands of the office.")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)
    e = sub.add_parser("ekle", help="add a queued job")
    e.add_argument("--brief-dosya", dest="brief_dosya", help="JSON brief in durum/taslak/ (deleted on success)")
    e.add_argument("--proje")
    e.add_argument("--baslik")
    e.add_argument("--hedef")
    e.add_argument("--gorev", help="alias of --hedef")
    e.add_argument("--neden")
    e.add_argument("--kisitlar")
    e.add_argument("--kapsam-disi", dest="kapsam_disi")
    e.add_argument("--kontrol")
    e.add_argument("--katman")
    e.add_argument("--model")
    e.add_argument("--effort")
    e.add_argument("--butce")
    e.add_argument("--cagri", help="the job's model-call limit (default: the tier's)")
    e.add_argument("--bagimli")
    e.add_argument("--grup")
    e.add_argument("--beklet", action="store_true", help="queued but held until `ofis.py serbest`")
    e.add_argument("--deneme", action="store_true", help="an office self-test: left out of the quality numbers")
    e.add_argument("--uzmanlik", help="the job's specialisation (roller/*.json); default: the routing decides")
    b = sub.add_parser("baslat", help="start a queued job")
    b.add_argument("is_", metavar="is")
    b.add_argument("--worktree", action="store_true")
    b.add_argument("--permission-mode", choices=launch.PERMISSION_MODES)
    r = sub.add_parser("bildir", help="report to the office (project sessions)")
    r.add_argument("--oturum", required=True)
    r.add_argument("--tur", required=True)
    r.add_argument("metin", nargs="?", help='the text, or "-" to read it from stdin')
    r.add_argument("--dosya", help="text file in durum/taslak/ (deleted on success)")
    c = sub.add_parser("cevapla", help="record the owner's answer and send it to the asking session")
    c.add_argument("karar")
    c.add_argument("cevap", nargs="?")
    c.add_argument("--dosya", help="answer file in durum/taslak/ (deleted on success)")
    f = sub.add_parser("bitir", help="finish a started job")
    f.add_argument("is_", metavar="is")
    f.add_argument("--sonuc")
    i = sub.add_parser("iptal", help="cancel a queued or started job")
    i.add_argument("is_", metavar="is")
    u = sub.add_parser("butce", help="change a job's budget (USD) and/or call limit")
    u.add_argument("is_", metavar="is")
    u.add_argument("usd", nargs="?")
    u.add_argument("--cagri")
    d = sub.add_parser("devam", help="let a stuck (tikandi) job go on in its session")
    d.add_argument("is_", metavar="is")
    d.add_argument("metin", nargs="?")
    d.add_argument("--dosya", help="text file in durum/taslak/ (deleted on success)")
    sv = sub.add_parser("serbest", help="release a held queued job (beklet)")
    sv.add_argument("is_", metavar="is")
    bg = sub.add_parser("bagimli", help="drop a dependency of a queued job")
    bg.add_argument("is_", metavar="is")
    bg.add_argument("--kaldir", required=True, help="the dependency to drop")
    a = sub.add_parser("akis", help="start a workflow from a template (akislar/<sablon>.json)")
    a.add_argument("sablon")
    a.add_argument("--brief-dosya", dest="brief_dosya", help="JSON brief in durum/taslak/ (deleted on success)")
    a.add_argument("--proje")
    a.add_argument("--baslik")
    a.add_argument("--hedef")
    a.add_argument("--neden")
    a.add_argument("--kisitlar")
    a.add_argument("--kapsam-disi", dest="kapsam_disi")
    a.add_argument("--kontrol")
    a.add_argument("--butce", help="the whole workflow's budget in USD (split over its steps)")
    a.add_argument("--deneme", action="store_true", help="an office self-test: left out of the quality numbers")
    a.add_argument("--uzmanlik", help="the kod step's specialisation (roller/*.json); default: the routing decides")
    ak = sub.add_parser("akis-karar", help="the owner's decision on a stopped workflow")
    ak.add_argument("grup")
    ak.add_argument("karar", choices=("devam", "iptal"))
    z = sub.add_parser("zamanla", help="scheduled jobs (bin/zamanla.py)")
    zs = z.add_subparsers(dest="zamanla_komut", required=True, parser_class=_Parser)
    ze = zs.add_parser("ekle", help="add a schedule (the server adds a job at each due time)")
    ze.add_argument("--brief-dosya", dest="brief_dosya", help="JSON brief in durum/taslak/ (deleted on success)")
    for flag in ("--ad", "--proje", "--baslik", "--hedef", "--neden", "--kisitlar", "--kontrol", "--katman", "--model",
                 "--effort", "--butce", "--saat", "--gunler"):
        ze.add_argument(flag)
    ze.add_argument("--kapsam-disi", dest="kapsam_disi")
    ze.add_argument("--deneme", action="store_true", help="every run is an office self-test")
    ze.add_argument("--uzmanlik", help="every run's specialisation (roller/*.json); default: routed at each add")
    zs.add_parser("listele", help="table of the schedules")
    for name, text in (("durdur", "pause a schedule"), ("devam", "resume a paused schedule"),
                       ("sil", "mark a schedule removed (its history stays)")):
        zs.add_parser(name, help=text).add_argument("ad")
    du = sub.add_parser("duyuru", help="the owner's announcement to every office session (CEO, on the owner's explicit word)")
    du.add_argument("metin", nargs="?")
    du.add_argument("--dosya", help="text file in durum/taslak/ (deleted on success)")
    du.add_argument("--sure", default="simdi", help="simdi (default), bugun, hafta or a date YYYY-MM-DD")
    ya = sub.add_parser("yakala", help="the owner's captured link -> one Ar-Ge research job (CEO, when the owner writes "
                        "'yakala: <url>')")
    ya.add_argument("--url", required=True)
    ya.add_argument("--not", dest="not_", help="the owner's one-line note (data)")
    ya.add_argument("--not-dosya", dest="not_dosya", help="the note as a text file in durum/taslak/ (deleted on success)")
    sub.add_parser("modeller", help="effective model mapping per project, running pilots, open model cards")
    sub.add_parser("talimat-denetimi", help="the prompt audit of the office's and projects' instructions now -> one "
                   "Ar-Ge job (CEO, on the owner's word)")
    sub.add_parser("hafiza-saglik", help="read-only: the memory health check of the OFIS notes, printed now")
    dn =sub.add_parser("deneme-isaretle", help="one-time: mark finished jobs as office self-tests (idempotent)")
    dn.add_argument("isler", nargs="+", metavar="is")
    so = sub.add_parser("sor", help="the CEO's own question to the owner -> one pending Kararlar card (tur: ceo-sorusu)")
    so.add_argument("--dosya", required=True, help="JSON {baslik, soru, secenekler, proje, ilgili} in durum/taslak/ "
                    "(deleted on success)")
    sub.add_parser("durum", help="table of queued, active and the last 5 finished jobs")
    sub.add_parser("ceo-yenile", help="the next delivery to the CEO starts a fresh CEO session with the handoff note "
                   "(after CLAUDE.md or the message protocol changed); writes only the flag durum/ceo-yenile")
    dp = sub.add_parser("danisman-pilotu", help="the advisor pilot: oner = its one proposal card (on the owner's word); "
                        "durum = read-only state")
    dp.add_argument("eylem", choices=("oner", "durum"))
    return p


def main(argv, cfg=None, durum_dir=DURUM_DIR, claude_bin=None, now=None, suffix=None, stdin=None, out=None,
         err=None, cwd=None, config_path=None):
    """config_path: the ofis.json that `cevapla` may change (phase 8 mapping change); launch.config_path() when the
    config is loaded here, else only what the caller passes (a test's cfg never writes the real file)."""
    out, err, stdin = out or sys.stdout, err or sys.stderr, stdin or sys.stdin
    clock = now or datetime.now
    cwd = cwd or os.getcwd()

    def log(text):
        err.write(f"ofis: {text}\n")
    try:
        args = build_parser().parse_args(argv[1:])
        if args.command == "bildir":  # no config, no vault: only the inbox file
            result = cmd_bildir(args, durum_dir, clock(), stdin, cwd)
        elif args.command == "ceo-yenile":  # no config, no vault: only the flag file the server's CEO channel reads
            result = cmd_ceo_yenile(durum_dir, clock())
        else:
            if cfg is None:
                cfg = launch.load()
                config_path = config_path or launch.config_path()
            if args.command == "ekle":
                brief_file = apply_brief_file(args, durum_dir, cwd) if args.brief_dosya else None
                if args.butce is not None:
                    try:
                        if not math.isfinite(float(args.butce)):
                            raise ValueError
                    except ValueError:
                        raise Refused(f"invalid budget: {args.butce!r}") from None
                result = cmd_ekle(cfg, args, clock(), durum_dir)
                _remove_input(brief_file)
            elif args.command == "baslat":
                result = cmd_baslat(cfg, args, clock(), claude_bin, suffix, durum_dir)
            elif args.command == "cevapla":
                result = cmd_cevapla(cfg, args, durum_dir, clock(), cwd, config_path)
            elif args.command == "bitir":
                result = cmd_bitir(cfg, args, clock(), durum_dir)
            elif args.command == "iptal":
                result = cmd_iptal(cfg, args, clock(), durum_dir)
            elif args.command == "butce":
                result = cmd_butce(cfg, args, durum_dir, log)
            elif args.command == "devam":
                result = cmd_devam(cfg, args, durum_dir, clock(), cwd, log)
            elif args.command == "serbest":
                result = cmd_serbest(cfg, args, durum_dir)
            elif args.command == "bagimli":
                result = cmd_bagimli(cfg, args, durum_dir)
            elif args.command == "akis":
                brief_file = apply_brief_file(args, durum_dir, cwd, AKIS_FILE_FIELDS) if args.brief_dosya else None
                result = cmd_akis(cfg, args, clock(), durum_dir)
                _remove_input(brief_file)
            elif args.command == "akis-karar":
                result = cmd_akis_karar(cfg, args, clock(), durum_dir)
            elif args.command == "zamanla":
                brief_file = None
                if args.zamanla_komut == "ekle" and args.brief_dosya:
                    brief_file = apply_brief_file(args, durum_dir, cwd, ZAMANLA_FILE_FIELDS)
                result = cmd_zamanla(cfg, args, clock(), durum_dir)
                _remove_input(brief_file)
                if isinstance(result, str):
                    out.write(result)
                    return 0
            elif args.command == "duyuru":
                text, source_file = _text_arg(args.metin, args.dosya, durum_dir, cwd, what="text")
                try:
                    result = duyuru.create(cfg, durum_dir, text, args.sure, clock(), kaynak="ceo", log=log)
                except duyuru.Refused as e:
                    raise Refused(str(e)) from None
                _remove_input(source_file)
            elif args.command == "yakala":
                note, source_file = (None, None) if args.not_ is None and args.not_dosya is None else \
                    _text_arg(args.not_, args.not_dosya, durum_dir, cwd, what="note")
                result = cmd_yakala(cfg, args.url, note, durum_dir, clock(), log)
                _remove_input(source_file)
            elif args.command == "talimat-denetimi":
                result = cmd_talimat_denetimi(cfg, durum_dir, clock(), log)
            elif args.command == "modeller":
                out.write(model_secimi.table(cfg, durum_dir))
                return 0
            elif args.command == "hafiza-saglik":  # read-only: prints the report, writes nothing
                import hafiza_saglik
                out.write(hafiza_saglik.rapor_metni(cfg))
                return 0
            elif args.command == "sor":
                result = cmd_sor(cfg, args, durum_dir, clock(), cwd)
            elif args.command == "deneme-isaretle":
                result = cmd_deneme_isaretle(cfg, args, durum_dir)
            elif args.command == "danisman-pilotu":
                if args.eylem == "durum":
                    out.write(danisman.table(cfg, durum_dir))
                    return 0
                try:
                    result = danisman.propose(cfg, durum_dir, clock())
                except danisman.Refused as e:
                    raise Refused(str(e)) from None
            else:
                out.write(cmd_durum(cfg, durum_dir))
                return 0
    except (Refused, launch.Refused) as e:
        err.write(f"REFUSED: {e}\n")
        return 1
    except (jobs.JobError, OSError) as e:
        err.write(f"REFUSED: {type(e).__name__}: {e}\n")
        return 1
    if isinstance(result, dict):
        for text in result.get("uyarilar") or []:
            err.write(f"UYARI: {text}\n")
    out.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
