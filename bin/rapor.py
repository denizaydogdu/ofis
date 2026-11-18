"""Group reports (phase 5, ADR-002 "Birleşik rapor"): when every job of a group is final the server writes ONE report
and sends ONE CEO notice. Deterministic code, no model call; runs in the post office thread.

A group (`grup`) is the set of jobs whose server record (durum/isler/<job>.json, bin/records.py) names it: jobs added
with `ofis.py ekle --grup G`, the steps of a workflow (their grup is the workflow id) and jobs escalated from them
(same grup). The record is trusted; the vault note is not read for membership.
A group is complete when every member's note has a final status (bitti, tikandi, iptal, basarisiz), none still waits
for its scorecard row (`karne: bekliyor`: its final spending is not recorded yet) and, for a workflow, its state
(durum/akislar/<grup>/akis.json) is closed (bitti, iptal or ceo).
Then check() writes OFIS/Raporlar/<grup>.md (temp file + os.replace: a half-written report is never read) and queues
the notice "<proje> grubu bitti: … Rapor: [[<grup>]]" under the key rapor-<grup>-v<version>. The state of each group
is durum/raporlar/<grup>.json {grup, surum, iz, bildirilen}: `iz` is the fingerprint of the members' final states
(name, status, end time, devam rounds, and the workflow's state). Unchanged fingerprint → nothing happens; a member
that went on with `ofis.py devam` (or a new member) and finished again changes it → the report is rewritten in place
as the next version and one new notice is sent for it. Every step is idempotent: a crash after the report repeats the
same version, a notice key is queued at most once (the CEO channel's sent log).
A one-job group (no workflow) gets its report without a notice: its job's own done notice told the CEO.
Deployment: the first check creates durum/raporlar/.baslangic.json with the current time; a group whose last job
finished before that gets its report but no notice (no burst of old news).
To keep the group to one message the per-job "işi bitti" notices of a job whose group has more than one job, and every
"akış adımı bitti" notice of a workflow step, are not sent (quiet_done(); logged only) — except while another member
waits for the owner (held or blocked): then the done notice is the CEO's cue to ask him. Notices that need a decision
(soru, takıldı, durduruldu, yükseltme, engel, ilerlemiyor, izin, onay bekliyor, akış durdu) are unchanged.
Correction events (OFIS/Karne/Duzeltmeler-<proje>.md, bin/karne.py) of the group's jobs are listed in the report and
counted as rework.
Self-test jobs (server record `deneme: evet`, owner decision 2026-11-12) stay in the jobs table marked "(deneme)" but are left
out of every total (cost, tokens, verified cost, first pass, rework); the Toplamlar section and the notice say how many
were left out and what they cost (frontmatter `deneme_is`, `deneme_usd`).
"""
import hashlib
import json
import os
import re
from datetime import datetime

import budget
import jobs
import karne
import launch
import records
import sahip

FOLDER = "Raporlar"  # in the vault's OFIS folder
STATE_DIR = "raporlar"  # durum/raporlar/
BASELINE = ".baslangic.json"
SYSTEM_PREFIX = "[Ofis · sistem]\n"
WORKFLOW_CLOSED = ("bitti", "iptal", "ceo")
QUOTE_MAX = 1200
STATUS_TR = {"bitti": "bitti", "tikandi": "takıldı", "iptal": "iptal", "basarisiz": "başlatılamadı"}
KIND_TR = {"kontrol-basarisiz": "Kontrol geçmedi", "inceleme-duzelt": "inceleme düzeltme istedi",
           "yukseltme": "bir üst katmana taşındı", "devam": "devam ettirildi", "onay-degil": "onay dışı cevap"}
WORKFLOW_RESULT = {"bitti": "{sahip} onayladı", "ceo": "onay kartına düz onay dışında bir cevap verildi; CEO ele alıyor",
                   "iptal": "iptal edildi"}


def _int(value):
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _float(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _time(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _quote(text, limit=QUOTE_MAX):
    text = str(text or "").strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return "\n".join("> " + line for line in text.splitlines()) if text else ""


def _cell(text):
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|")


# --- membership ---

def members(durum_dir):
    """{grup: [job names]} from the server records (sorted)."""
    folder = os.path.join(durum_dir, records.FOLDER)
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json") and not n.startswith("."))
    except OSError:
        return {}
    out = {}
    for n in names:
        try:
            name = jobs.check_name(n[:-5])
        except jobs.JobError:
            continue
        rec = records.load(durum_dir, name)
        group = (rec or {}).get("grup")
        if isinstance(group, str) and launch.GROUP_NAME.fullmatch(group):
            out.setdefault(group, []).append(name)
    return out


def _waits_for_deniz(durum_dir, vault, name):
    """A queued member that never starts by itself: held (`beklet`, e.g. a workflow on probation) or blocked
    (`engel`). Read like the dispatcher: the record when it has the key, else the note."""
    job = jobs.find(vault, name)
    if job is None or job.meta.get("durum") != "sirada":
        return False
    return records.get(durum_dir, job, "beklet") == "evet" or job.meta.get("beklet") == "evet" or \
        bool(records.get(durum_dir, job, "engel"))


def quiet_done(durum_dir, job_name, vault=None):
    """True when a job's own "işi bitti" notice is not sent because the group report will tell: a workflow step, or
    a job whose group has more than one job — unless another member waits for the owner (held or blocked): then the done
    notice is the CEO's cue to ask him, and it is sent."""
    rec = records.load(durum_dir, job_name) or {}
    group = rec.get("akis") or rec.get("grup")
    if not isinstance(group, str) or not group:
        return False
    others = [n for n in members(durum_dir).get(group, []) if n != jobs.check_name(job_name)]
    if not rec.get("akis") and not others:
        return False
    if vault and any(_waits_for_deniz(durum_dir, vault, n) for n in others):
        return False
    return True


# --- the report ---

def _workflow(durum_dir, group):
    import akis  # lazy: akis imports this module's neighbours (kontrol), never at import time
    return akis.load_state(durum_dir, group)


def _codex_review(durum_dir, job):
    """A kod-inceleme done by the review panel (bin/denetci.py): Codex's (and the free models') price is unknown."""
    rec = records.load(durum_dir, job.name) or {}
    return rec.get("adim_turu") == "kod-inceleme" and rec.get("inceleme_yurutucu") == "codex"


def _cost(durum_dir, job):
    rec = records.load(durum_dir, job.name) or {}
    if _codex_review(durum_dir, job):
        # only the hakem's recorded cost is known (None without a hakem call: the price is wholly unknown)
        spent = _float(rec.get("harcanan_usd"))
        return spent if spent else None
    return _float(rec.get("harcanan_usd") if rec.get("harcanan_usd") not in (None, "") else
                  job.meta.get("harcanan_usd"))


def _tokens(durum_dir, job):
    """The job's recorded tokens (harcanan_token: record first, else note), None when unknown (an older job, Codex)."""
    rec = records.load(durum_dir, job.name) or {}
    if rec.get("adim_turu") == "kod-inceleme" and rec.get("inceleme_yurutucu") == "codex":
        return None
    value = rec.get("harcanan_token")
    return budget.token_count(value if value not in (None, "") else job.meta.get("harcanan_token"))


def _minutes(start, end):
    if start and end and end >= start:
        return round((end - start).total_seconds() / 60)
    return None


def _duration_text(minutes):
    if minutes is None:
        return "—"
    if minutes < 120:
        return f"{minutes} dk"
    return f"{minutes // 60} sa {minutes % 60} dk"


def fingerprint(group_jobs, state):
    parts = [[j.name, j.meta.get("durum", ""), j.meta.get("bitis", ""), j.meta.get("devam_sayisi", "")]
             for j in group_jobs]
    if state is not None:
        parts.append(["akis", state.get("durum", ""), state.get("sonuc", "")])
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def summarise(durum_dir, vault, group, group_jobs, state):
    """Numbers and rows of a complete group (used by the report and the notice)."""
    stems = {jobs.stem(j.name) for j in group_jobs}
    projects = sorted({j.meta.get("proje", "") for j in group_jobs if j.meta.get("proje")})
    events = [e for p in projects for e in karne.corrections(vault, p) if e["is"] in stems]
    trial_stems = {jobs.stem(j.name) for j in group_jobs
                   if (records.load(durum_dir, j.name) or {}).get("deneme") == karne.TRIAL}
    rows, total, unknown = [], 0.0, False
    trial_total, trial_count = 0.0, 0
    tokens, tokens_known, tokens_missing = 0, 0, 0
    first = []
    starts, ends = [], []
    for job in group_jobs:
        meta = job.meta
        rec = records.load(durum_dir, job.name) or {}
        cost = _cost(durum_dir, job)
        codex = _codex_review(durum_dir, job)
        trial = jobs.stem(job.name) in trial_stems
        if trial:  # listed, never counted
            trial_count += 1
            trial_total += cost or 0.0
            start, end = _time(meta.get("baslangic")), _time(meta.get("bitis"))
            rows.append(_row(job, meta, rec, cost, codex, _tokens(durum_dir, job), karne.first_round(meta), start,
                             end, trial=True))
            continue
        if cost is None or codex:
            unknown = True
        if cost is not None:
            total += cost
        job_tokens = _tokens(durum_dir, job)
        if job_tokens is None:
            tokens_missing += 1
        else:
            tokens += job_tokens
            tokens_known += 1
        fr = karne.first_round(meta)
        if fr in ("evet", "hayır"):
            first.append(fr)
        start, end = _time(meta.get("baslangic")), _time(meta.get("bitis"))
        if start:
            starts.append(start)
        if end:
            ends.append(end)
        rows.append(_row(job, meta, rec, cost, codex, job_tokens, fr, start, end))
    verified = [r for r in rows if not r["trial"] and r["status"] == "bitti"
                and r["job"].meta.get("kontrol_sonuc") == "gecti"]
    rework = {k: sum(1 for e in events if e["tur"] == k and e["is"] not in trial_stems) for k in karne.REWORK_KINDS}
    statuses = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    # only a Duzeltmeler note that exists may be linked (a project with no correction yet has none)
    notes = [p for p in projects if os.path.isfile(os.path.join(vault, karne.FOLDER, karne.CORRECTIONS.format(p)))]
    return {"group": group, "projects": projects, "correction_notes": notes, "rows": rows, "events": events, "total": total,
            "unknown": unknown, "verified": len(verified),
            # tokens: the sum of the jobs whose tokens were recorded (None when none was); tokens_missing = the rest
            "tokens": tokens if tokens_known else None, "tokens_missing": tokens_missing,
            "per_verified": (total / len(verified)) if verified else None,
            # the token twin of per_verified: all known tokens / the same verified jobs (None when either is missing)
            "tokens_per_verified": round(tokens / len(verified)) if verified and tokens_known else None,
            "first": first, "rework": rework, "statuses": statuses,
            "trial_count": trial_count, "trial_total": trial_total,
            "start": min(starts) if starts else None, "end": max(ends) if ends else None,
            "state": state}


def _row(job, meta, rec, cost, codex, job_tokens, fr, start, end, trial=False):
    moved = rec.get("yukseltildi") or ""
    source = rec.get("yukseltme_kaynagi") or meta.get("yukseltme_kaynagi") or ""
    escalation = (f"↑ [[{jobs.stem(moved)}]]" if moved else f"← [[{jobs.stem(source)}]]" if source else "—")
    tier = " / ".join(x for x in (meta.get("katman", ""), karne.worker(meta.get("model", ""))) if x) or "—"
    return {"job": job, "tier": tier, "status": meta.get("durum", ""), "first": fr,
            "tries": _int(meta.get("kontrol_deneme")), "devam": _int(meta.get("devam_sayisi")),
            "escalation": escalation, "cost": cost, "codex": codex, "tokens": job_tokens,
            "minutes": _minutes(start, end), "moved": moved, "step": rec.get("adim_turu") or "", "trial": trial}


def _title(s):
    state = s["state"]
    if state is not None:
        return state.get("baslik") or s["group"]
    titles = [r["job"].meta.get("baslik") for r in s["rows"] if r["job"].meta.get("baslik")]
    return titles[0] if len(titles) == 1 else f"{s['group']} grubu"


def _money(value):
    return f"API karşılığı ~${budget.usd(value)}"


def _open_items(s):
    out = []
    for r in s["rows"]:
        if r["status"] in ("tikandi", "basarisiz") and not r["moved"] and r["step"] != "onay":
            tail = jobs.section(r["job"].body, "Sonuç").strip()
            tail = re.sub(r"^> ?", "", tail.splitlines()[-1]) if tail else ""
            reason = karne.excerpt(tail) if tail else "(sonuç yok)"
            out.append(f"- [[{jobs.stem(r['job'].name)}]] {STATUS_TR.get(r['status'], r['status'])}. Sonucun son "
                       f"satırı: {reason}")
    for e in s["events"]:
        if e["tur"] == "onay-degil":
            out.append(f"- Onay kartına düz bir onay dışında cevap verildi ([[{e['is']}]]): {e['alinti']} — CEO ele "
                       "alacak.")
    state = s["state"]
    if state is not None and state.get("durum") == "iptal":
        out.append("- Akış iptal edildi.")
    return out


def _workflow_lines(durum_dir, state):
    import akis
    lines = [f"- Şablon: {state.get('sablon', '')} · sonuç: {str(WORKFLOW_RESULT.get(state.get('durum'), state.get('durum'))).replace('{sahip}', sahip.ad())}",
             f"- Plan turu: {_int(state.get('plan_turu'))} · kod incelemesi turu: {_int(state.get('inceleme_turu'))}"]
    for step in state.get("adimlar") or []:
        if step.get("tur") not in akis.REVIEWS:
            continue
        for name in step.get("isler") or []:
            verdict = (state.get("kararlar") or {}).get(name)
            if not verdict:
                continue
            executor = records.server_value(durum_dir, name, "inceleme_yurutucu") or "claude"
            word = {"onay": "ONAY", "duzelt": "DÜZELT", "eksik": "karar satırı yok"}.get(verdict.get("karar"), "—")
            lines.append(f"- {akis.KIND_LABEL.get(step['tur'], step['tur'])} [[{jobs.stem(name)}]]: {word} "
                         f"(yürütücü: {_cell(executor)})")
            found = [f for f in verdict.get("bulgular") or [] if isinstance(f, str)]
            if found:
                lines.append(_quote("\n".join(found)))
    for d in state.get("deniz_kararlari") or []:
        if isinstance(d, dict):
            lines.append(f"- {sahip.in_()} kararı ({_cell(d.get('zaman'))}): {_cell(d.get('karar'))}")
    return lines


def report_text(durum_dir, s, version, now):
    rows = s["rows"]
    notes = s.get("correction_notes") or []
    project = ", ".join(s["projects"]) or "—"
    first = s["first"]
    rework_total = sum(s["rework"].values())
    cycle = _minutes(s["start"], s["end"])
    meta = [("tags", "[ofis, rapor]"), ("proje", project), ("grup", s["group"]), ("durum", "tamam"),
            ("tur", "akis" if s["state"] is not None else "grup"), ("surum", str(version)),
            ("baslangic", f"{s['start']:%Y-%m-%dT%H:%M:%S}" if s["start"] else ""),
            ("bitis", f"{s['end']:%Y-%m-%dT%H:%M:%S}" if s["end"] else ""),
            ("yazildi", f"{now:%Y-%m-%dT%H:%M:%S}"), ("toplam_usd", f"{s['total']:.4f}")]
    if s.get("tokens") is not None:
        meta.append(("toplam_token", str(s["tokens"])))
        if s.get("tokens_missing"):
            meta.append(("token_eksik", str(s["tokens_missing"])))
    if s.get("trial_count"):
        meta += [("deneme_is", str(s["trial_count"])), ("deneme_usd", f"{s['trial_total']:.4f}")]
    head = ["---"] + [f"{k}: {v}" if k == "tags" else f"{k}: {jobs.format_value(v)}" for k, v in meta] + ["---", ""]
    out = head + [f"# {project} — {_cell(_title(s))} ({s['group']})", "",
                  "> Bu raporu Ofis sunucusu grup bitince yazar (elle düzenleme). Bir iş devam ettirilip yeniden "
                  "biterse aynı dosya yeni sürümle baştan yazılır. Dolar tutarları API fiyatıyla karşılığıdır (abonelikte para ödenmez).", "",
                  "## İşler", "",
                  "| İş | Katman / çalışan | Sonuç | Kontrol ilk turda | Kontrol denemesi | Devam | Yükseltme | "
                  "API karşılığı ($) | Süre (dk) | Token |", "|" + "---|" * 10]
    for r in rows:
        cost = CODEX_COST if r["cost"] is None else f"{r['cost']:.4f}" + (" (Codex hariç)" if r.get("codex") else "")
        link = f"[[{jobs.stem(r['job'].name)}]]" + (" (deneme)" if r.get("trial") else "")
        values = (link, r["tier"], STATUS_TR.get(r["status"], r["status"]), r["first"],
                  r["tries"], r["devam"], r["escalation"], cost, "—" if r["minutes"] is None else r["minutes"],
                  budget.token_text(r.get("tokens")) or "—")
        out.append("| " + " | ".join(_cell(v) for v in values) + " |")
    per = (f"{_money(s['per_verified'])} ({s['verified']} iş kontrolü geçerek bitti)" if s["per_verified"] is not None
           else "— (kontrolü geçerek biten iş yok)")
    out += ["", "## Toplamlar", "",
            f"- Toplam kullanım: {_money(s['total'])}" + (f"; {CODEX_TOTAL} (toplam Codex hariç)"
                                                                 if s["unknown"] else ""),
            f"- Doğrulanmış iş başına kullanım: {per}",
            f"- Toplam token: {_tokens_line(s)}",
            f"- Doğrulanmış iş başına token: {_verified_tokens_line(s)}",
            "- Kontrol ilk turda geçme: " + (f"%{round(100 * first.count('evet') / len(first))} "
                                             f"({first.count('evet')}/{len(first)})" if first else "— (kontrol çalışmadı)"),
            f"- Yeniden iş: {rework_total} (Kontrol geçmedi: {s['rework']['kontrol-basarisiz']}, inceleme düzeltme "
            f"istedi: {s['rework']['inceleme-duzelt']}, bir üst katmana taşındı: {s['rework']['yukseltme']}, devam "
            f"ettirildi: {s['rework']['devam']})",
            f"- Döngü süresi (ilk başlangıç → son bitiş): {_duration_text(cycle)}"]
    if s.get("trial_count"):
        out.append(f"- Deneme işleri (toplamlara katılmadı): {s['trial_count']} iş, {_money(s['trial_total'])} — "
                   "ofisin kendini sınadığı işler; yukarıdaki sayılara girmez.")
    out += ["", "## Açık kalanlar", ""]
    out += _open_items(s) or ["- Açık kalan yok."]
    if s["state"] is not None:
        out += ["", "## Akış", ""] + _workflow_lines(durum_dir, s["state"])
    out += ["", "## Düzeltmeler", ""]
    if s["events"]:
        out += ["| Tarih | İş | Tür | Alıntı |", "|---|---|---|---|"]
        for e in s["events"]:
            out.append(f"| {_cell(e['tarih'])} | [[{e['is']}]] | {KIND_TR.get(e['tur'], e['tur'])} | "
                       f"{_cell(e['alinti'])} |")
        out.append("")
        if notes:
            out.append("Kaynak: " + " · ".join(f"[[Duzeltmeler-{p}]]" for p in notes))
    else:
        out.append("- Bu grupta düzeltme gerekmedi.")
    out += ["", "## İlgili Sayfalar", "", "- [[OFIS/README]]"] + \
        [f"- [[Duzeltmeler-{p}]]" for p in notes]
    if not notes:
        out.append("- Düzeltme kaydı yok (henüz Duzeltmeler notu açılmamış).")
    return "\n".join(out) + "\n"


def _tokens_line(s):
    """"182 bin token", with how many jobs have no recorded count; "—" when none has one (older jobs)."""
    if s.get("tokens") is None:
        return "— (token sayısı kaydedilmemiş)"
    missing = s.get("tokens_missing") or 0
    return budget.token_text(s["tokens"]) + (f" ({missing} işte kayıtlı değil)" if missing else "")


def _verified_tokens_line(s):
    """"182 bin token (1 iş kontrolü geçerek bitti; 1 işte token kayıtlı değil)"; "—" when unknown (never 0)."""
    value = s.get("tokens_per_verified")
    if value is None:
        return "—" + (" (kontrolü geçerek biten iş yok)" if not s.get("verified") else " (token sayısı kaydedilmemiş)")
    missing = s.get("tokens_missing") or 0
    return (f"{budget.token_text(value)} ({s['verified']} iş kontrolü geçerek bitti"
            + (f"; {missing} işte token kayıtlı değil)" if missing else ")"))


def notice_text(s, version):
    project = ", ".join(s["projects"]) or "—"
    counts = ", ".join(f"{n} {STATUS_TR.get(k, k)}" for k, n in sorted(s["statuses"].items()))
    per = (budget.spend_text(s["per_verified"], s.get("tokens_per_verified")) if s["per_verified"] is not None
           else "— (kontrolü geçerek biten iş yok)")
    opened = len(_open_items(s))
    again = f" Rapor yeniden yazıldı (sürüm {version}): gruptan bir iş yeniden bitti." if version > 1 else ""
    trial = (f" {s['trial_count']} deneme işi toplamlara katılmadı ({_money(s['trial_total'])})."
             if s.get("trial_count") else "")
    files = ", ".join(f"Karne/Duzeltmeler-{p}" for p in s["projects"])
    return (f"{SYSTEM_PREFIX}{project} grubu bitti: {_title(s)} ({s['group']}).{again} {len(s['rows'])} iş: {counts}. "
            f"Toplam kullanım {budget.token_text(s['tokens']) + ' · ' if s.get('tokens') else ''}{_money(s['total'])}"
            f"; doğrulanmış iş başına {per}; yeniden iş "
            f"{sum(s['rework'].values())}; açık kalan {opened}.{trial} Rapor: [[{s['group']}]] (Obsidian'da OFIS/Raporlar). "
            f"{sahip.e()} kısaca bildir; log.md'ye bu grup için tek kayıt yaz. Sonra {files} dosyasının son satırlarına "
            "bak: aynı türden düzeltme iki kez geçiyorsa projenin CLAUDE.md'si için bir satır öner (Kararlar notu, "
            "tur: claude-md-onerisi); aynı inceleme bulgusu sınıfı (inceleme-duzelt) iki kez geçiyorsa projenin "
            "REVIEW.md'si için bir satır öner (tur: review-md-onerisi).")


# --- reading reports back for the page (phase 7) ---
# The page lists the reports (GET /api/raporlar) and shows one (GET /api/rapor?grup=…). The parser lives next to
# report_text() on purpose: the report is the only place the group's numbers are kept, and a format change here must
# change both (test_postoffice.GroupReportTest reads a written report back).

MAX_REPORT_BYTES = 256 * 1024
MAX_LISTED = 100
STATUS_OF = {v: k for k, v in STATUS_TR.items()}  # "takıldı" -> "tikandi"
CODEX_COST = "Codex (fiyat bilinmiyor)"  # the jobs table cell and the Toplamlar remark written by report_text
CODEX_TOTAL = "Codex'in fiyatı bilinmiyor"


def valid_group(group):
    """A group id the page may ask for: the same rule as `--grup` (launch.GROUP_NAME), so it can only name a file
    directly in OFIS/Raporlar (no dot, slash or NUL)."""
    return isinstance(group, str) and bool(launch.GROUP_NAME.fullmatch(group))


def _report_text(folder, group):
    """The report file's text, or None: only a plain file (no symlink, no directory) directly in the folder, at most
    MAX_REPORT_BYTES."""
    path = os.path.join(folder, f"{group}.md")
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_REPORT_BYTES:
            return None
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read(MAX_REPORT_BYTES + 1)
    except (OSError, UnicodeDecodeError):
        return None


def _number(pattern, text, kind=float):
    m = re.search(pattern, text)
    try:
        return kind(m.group(1)) if m else None
    except ValueError:
        return None


def parse_report(group, text):
    """The summary of one report as data: what report_text() wrote in its frontmatter, its jobs table (outcomes) and
    its totals. A number the report does not give (no job verified, Kontrol never ran) is None or 0, never guessed."""
    _, meta, body = jobs.parse(text)
    project = meta.get("proje", "")
    heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), "")
    if project and heading.startswith(f"{project} — "):
        heading = heading[len(project) + 3:]
    if heading.endswith(f" ({group})"):
        heading = heading[:-len(group) - 3]
    outcomes = {}
    for line in jobs.section(body, "İşler").splitlines():
        if not line.startswith("| [["):
            continue
        cells = karne._split_row(line)
        if len(cells) >= 3:
            status = STATUS_OF.get(cells[2], cells[2])
            outcomes[status] = outcomes.get(status, 0) + 1
    totals = jobs.section(body, "Toplamlar")
    first = re.search(r"Kontrol ilk turda geçme: %\d+ \((\d+)/(\d+)\)", totals)
    per_verified = re.search(r"Doğrulanmış iş başına (?:kullanım|maliyet): (?:API karşılığı ~)?\$([0-9.]+) \((\d+) iş", totals)
    opened = [line for line in jobs.section(body, "Açık kalanlar").splitlines()
              if line.startswith("- ") and line.strip() != "- Açık kalan yok."]
    total = _number(r"^([0-9.]+)$", meta.get("toplam_usd", ""))
    verified = int(per_verified.group(2)) if per_verified else 0
    # the Toplamlar line is rounded for people ($0.89); the frontmatter total keeps four decimals, so the cost per
    # verified job is recomputed from it (report_text divides the same total by the same count)
    tokens = budget.token_count(meta.get("toplam_token"))
    per_job = (round(total / verified, 6) if total is not None else float(per_verified.group(1))) if verified else None
    return {"grup": group, "baslik": heading or group, "proje": project, "tur": meta.get("tur", ""),
            "surum": _int(meta.get("surum")), "baslangic": meta.get("baslangic", ""), "bitis": meta.get("bitis", ""),
            "yazildi": meta.get("yazildi", ""), "toplam_usd": total,
            "toplam_token": tokens,  # None for a report from before tokens
            # the token twin of dogrulanmis_is_basina_usd (all known tokens / verified jobs); token_eksik = the jobs
            # without a recorded count (the page says how many)
            "dogrulanmis_is_basina_token": round(tokens / verified) if tokens is not None and verified else None,
            "token_eksik": _int(meta.get("token_eksik")),
            "deneme_is": _int(meta.get("deneme_is")),  # self-test jobs left out of the totals
            "is_sayisi": sum(outcomes.values()), "sonuclar": outcomes,
            "dogrulanmis_is_basina_usd": per_job, "dogrulanan": verified,
            # a Codex review has no known price: the total leaves it out (report_text writes both markers)
            "fiyat_bilinmiyor": CODEX_COST in jobs.section(body, "İşler") or CODEX_TOTAL in totals,
            "ilk_tur_gecen": int(first.group(1)) if first else 0,
            "ilk_tur_olculen": int(first.group(2)) if first else 0,
            "yeniden_is": _number(r"Yeniden iş: (\d+)", totals, int) or 0, "acik": len(opened)}


def list_reports(vault, limit=MAX_LISTED, cache=None):
    """Summaries of the reports in OFIS/Raporlar, newest first (by the group's end, else the time it was written).
    cache: a dict kept by the caller (bin/state.py builds every 1.5 s): a report whose file did not change (lstat:
    mtime, size, inode, mode) is not read and parsed again."""
    folder = os.path.join(vault, FOLDER)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for name in names:
        group = name[:-3] if name.endswith(".md") else ""
        if not valid_group(group):
            continue
        path = os.path.join(folder, name)
        key = None
        if cache is not None:
            try:
                st = os.lstat(path)
                key = (st.st_mtime_ns, st.st_size, st.st_ino, st.st_mode)
            except OSError:
                cache.pop(path, None)
                continue
            hit = cache.get(path)
            if hit is not None and hit[0] == key:
                if hit[1] is not None:
                    out.append(dict(hit[1]))
                continue
        text = _report_text(folder, group)
        summary = parse_report(group, text) if text is not None else None
        if cache is not None:
            cache[path] = (key, summary)
        if summary is not None:
            out.append(summary if cache is None else dict(summary))
    out.sort(key=lambda r: (r["bitis"] or r["yazildi"], r["grup"]), reverse=True)
    return out[:limit]


def read_report(vault, group):
    """One report for the page: its summary plus `metin`, the markdown body without the frontmatter (the page shows it
    as text, never as HTML). None for an invalid group id or a missing / unreadable report."""
    if not valid_group(group):
        return None
    text = _report_text(os.path.join(vault, FOLDER), group)
    if text is None:
        return None
    return {**parse_report(group, text), "metin": jobs.parse(text)[2]}


# --- the checker ---

class Reporter:
    def __init__(self, cfg, durum_dir, ceo, now=datetime.now, log=None):
        self.cfg = cfg
        self.vault = os.path.expanduser(cfg["vault_ofis"])
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.now = now
        self.log = log or (lambda text: None)
        self.state_dir = os.path.join(durum_dir, STATE_DIR)

    def _state_path(self, group):
        return os.path.join(self.state_dir, f"{group}.json")

    def _load(self, path):
        if os.path.islink(path) or not os.path.isfile(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        jobs._write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")

    def baseline(self):
        """The time from which finished groups are told (created at the first check)."""
        path = os.path.join(self.state_dir, BASELINE)
        data = self._load(path)
        start = _time(data.get("baslangic"))
        if start is None:
            start = self.now().replace(microsecond=0)
            self._save(path, {"baslangic": f"{start:%Y-%m-%dT%H:%M:%S}"})
        return start

    def _complete(self, names):
        """(the members' notes, the workflow state) when the group is complete, else None."""
        found = []
        for name in names:
            job = jobs.find(self.vault, name)
            if job is None:
                return None
            if job.meta.get("durum") not in jobs.FINAL_STATUSES or job.meta.get("karne") == "bekliyor":
                return None
            found.append(job)
        return sorted(found, key=lambda j: (j.meta.get("olusturuldu") or "", jobs.stem(j.name)))

    def check(self):
        """One pass over the groups. Returns the groups whose report was written in this pass."""
        start = self.baseline()
        written = []
        for group, names in sorted(members(self.durum_dir).items()):
            try:
                if self._check_one(group, names, start):
                    written.append(group)
            except (OSError, jobs.JobError, ValueError) as e:
                self.log(f"report of {group}: {type(e).__name__}: {e}")
        return written

    def _check_one(self, group, names, start):
        group_jobs = self._complete(names)
        if group_jobs is None:
            return False
        state = _workflow(self.durum_dir, group)
        if state is not None and state.get("durum") not in WORKFLOW_CLOSED:
            return False
        iz = fingerprint(group_jobs, state)
        path = self._state_path(group)
        saved = self._load(path)
        version, told = _int(saved.get("surum")), _int(saved.get("bildirilen"))
        if saved.get("iz") == iz and told == version and version:
            return False
        s = summarise(self.durum_dir, self.vault, group, group_jobs, state)
        wrote = False
        if saved.get("iz") != iz or not version:
            version += 1
            folder = os.path.join(self.vault, FOLDER)
            os.makedirs(folder, exist_ok=True)
            target = os.path.join(folder, f"{group}.md")
            if os.path.islink(target) or (os.path.lexists(target) and not os.path.isfile(target)):
                raise ValueError(f"Raporlar/{group}.md is not a plain file")
            jobs._write_atomic(target, report_text(self.durum_dir, s, version, self.now()))
            old = s["end"] is not None and s["end"] < start
            single = state is None and len(group_jobs) < 2  # its job's own done notice already told the CEO
            if old or single:
                told = version  # the report only, no notice
            self._save(path, {"grup": group, "surum": version, "iz": iz, "bildirilen": told,
                              "yazildi": f"{self.now():%Y-%m-%dT%H:%M:%S}"})
            self.log(f"report of {group} written (version {version})" + (" without a notice (old)" if old else ""))
            wrote = True
        if told != version:
            self.ceo.enqueue(notice_text(s, version), f"rapor-{group}-v{version}")
            self._save(path, {"grup": group, "surum": version, "iz": iz, "bildirilen": version,
                              "yazildi": saved.get("yazildi") if not wrote else f"{self.now():%Y-%m-%dT%H:%M:%S}"})
        return wrote
