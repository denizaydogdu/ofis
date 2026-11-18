"""Full view of one job note for the page's task detail panel (read only).

The note name must be a plain file name inside one of the job folders OFIS/Isler/{Siradakiler,Devam-Edenler,
Bitenler} (or the flat legacy OFIS/Isler until it is migrated): no separators, no dotfiles, no symlinks out of the
folder. Linked decisions ([[name]] or [[OFIS/Kararlar/name]]) are read only from OFIS/Kararlar, by plain name.
Phase 4: with durum_dir, a workflow step also shows its workflow facts — verdict, findings, round, executor — from the
server's workflow state (bin/akis.py job_info), never from the note.
"""
import os
import re

import akis
import jobs
import sahip
from state import NOTE_NAME, note_link, parse_note, section, task_title, title

MAX_SECTION = 20000
PLACEHOLDERS = jobs.OLD_PLACEHOLDERS
DECISION_LINK = re.compile(r"\[\[(?:OFIS/Kararlar/)?([^\]|#/\\]{1,200}?)(?:\|[^\]]*)?\]\]")


def _safe_note(folder, name):
    """Absolute path of `name` inside `folder`, or None if the name is unsafe or the file is not a plain note there."""
    if not isinstance(name, str) or not NOTE_NAME.fullmatch(name) or name.startswith(".") or ".." in name:
        return None
    path = os.path.join(folder, name)
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        return None
    return path


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return parse_note(f.read(256 * 1024))
    except (OSError, UnicodeDecodeError):
        return None


def _clip(text):
    text = text.strip()
    return "" if text in PLACEHOLDERS else text[:MAX_SECTION]


def _unquote(text):
    """The project's words are stored quoted with "> " (so they cannot open sections); shown plainly."""
    return "\n".join(re.sub(r"^> ?", "", line) for line in text.splitlines())


KONTROL_HEAD = "### Kontrol (kanıt)"
QUOTE = re.compile(r"^> ?")


BLOCK_FENCES = 2  # an evidence block has two quoted fences: the command and the output (kontrol.evidence_block)


def _split_kontrol(text):
    """(Sonuç without the server's Kontrol blocks, [block lines]). Only an unquoted "### Kontrol (kanıt)" line opens a
    block (the server writes it; project text and command output are quoted). The block ends when its second quoted
    fence (the output) closes, so text appended after it (a later report, a budget stop) stays in the Sonuç; an
    unquoted ### line outside a fence, or the end, also closes it. Runs on the stored, still quoted text."""
    rest, blocks, current, fence, closed = [], [], None, None, 0
    for line in text.splitlines():
        if line.startswith(KONTROL_HEAD):
            current, fence, closed = [line], None, 0
            blocks.append(current)
            continue
        if current is not None and fence is None and line.startswith("### "):
            current = None
        if current is None:
            rest.append(line)
            continue
        current.append(line)
        bare = QUOTE.sub("", line) if line.startswith(">") else None
        if bare is not None and re.fullmatch(r"`{3,}", bare):
            if fence is None:
                fence = bare
            elif bare == fence:
                fence, closed = None, closed + 1
                if closed >= BLOCK_FENCES:
                    current = None
    return "\n".join(rest), blocks


def _kontrol_block(lines):
    fences, exit_code, duration, i = [], "", "", 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("- Çıkış kodu:"):
            exit_code = line.split(":", 1)[1].strip()
        elif line.startswith("- Süre:"):
            duration = line.split(":", 1)[1].strip()
        elif line.startswith(">") and re.fullmatch(r"`{3,}", QUOTE.sub("", line)):
            fence, body = QUOTE.sub("", line), []
            i += 1
            while i < len(lines) and lines[i].startswith(">") and QUOTE.sub("", lines[i]) != fence:
                body.append(QUOTE.sub("", lines[i]))
                i += 1
            fences.append("\n".join(body)[:MAX_SECTION])
        i += 1
    return {"title": lines[0][4:].strip(), "command": fences[0] if fences else "", "exit_code": exit_code,
            "duration": duration, "output": fences[1] if len(fences) > 1 else ""}


def _decision(vault_ofis, name):
    path = _safe_note(os.path.join(vault_ofis, "Kararlar"), name)
    note = path and _read(path)
    if not note:
        return None
    meta, body = note
    return {"note": name, "title": title(body) or name[:-3], "status": meta.get("durum", ""),
            "asked": meta.get("soruldu", ""), "answered": meta.get("cevaplandi", ""),
            "question": _clip(_unquote(section(body, "Soru"))), "answer": _clip(sahip.cevap_bolumu(body))}


def task_detail(vault_ofis, name, durum_dir=None):
    try:
        job = jobs.find(vault_ofis, name, legacy=True) if isinstance(name, str) and name.endswith(".md") else None
    except jobs.JobError:
        job = None
    path = job and _safe_note(os.path.dirname(job.path), name)
    note = path and _read(path)
    if not note:
        return None
    meta, body = note
    task = _clip(section(body, "Görev"))
    result, proofs = _split_kontrol(section(body, "Sonuç"))
    decisions = []
    for link in DECISION_LINK.findall(section(body, "İlgili Kararlar")):
        d = _decision(vault_ofis, link.strip() + ".md")
        if d:
            decisions.append(d)
    return {
        "note": name, "project": meta.get("proje", ""), "status": meta.get("durum", ""),
        "started": meta.get("baslangic", ""), "finished": meta.get("bitis", ""),
        "session": meta.get("oturum", ""), "short_id": meta.get("kisa_id", ""),
        "title": task_title(meta, body),
        "task": task, "result": _clip(_unquote(result)), "decisions": decisions,
        "kontrol": [_kontrol_block(b) for b in proofs][-10:],
        "spent": meta.get("harcanan_usd", ""), "budget": meta.get("butce_usd", ""), "calls": meta.get("cagri", ""),
        "tokens": meta.get("harcanan_token", ""),
        "max_calls": meta.get("max_cagri", ""),
        # phase 3: an escalated job (one tier up) and the job it replaced link each other
        "escalated_from": note_link(meta.get("yukseltme_kaynagi")), "escalated_to": note_link(meta.get("yukseltildi")),
        "escalations": meta.get("yukseltme_sayisi", ""),
        "workflow": akis.job_info(durum_dir, name) if durum_dir else None,
    }
