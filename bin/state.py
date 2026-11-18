"""Office state for the page: office sessions, per-project status, today's tokens, decisions and tasks.

Only sessions whose name starts with "ofis-" and whose cwd is not a forbidden path (`guvenlik.yasak_yollar`) are ever
returned; every other session on the machine (a forbidden project's, the dev session, the owner's interactive sessions) is dropped before anything else.
Vault access is read-only and limited to OFIS/Kararlar and the job folders under OFIS/Isler. The schedules (phase 6)
come from the server's own definitions (durum/zamanlanmis, bin/zamanla.py), never from their display notes.
"""
import json
import os
import re
from datetime import date, datetime, timedelta

import adimlar
import akis
import alt_ajan
import ayarlar
import budget
import claude_cli
import denetci
import duyuru
import gunsonu
import hafiza
import dispatcher
import jobs
import launch
import limitler
import model_durum
import mudur
import pricing
import rapor
import records
import sahip
import sorumlu
import transcript
import yakala
import zamanla

MODEL_SCAN_AGE = timedelta(days=8)  # a known session's transcript older than this cannot hold a current quota

NOTE_NAME = re.compile(r"[^/\\\x00]{1,200}\.md")
MAX_QUESTION = 1500
MAX_TASKS = 10
BOARD_DONE = 20  # finished jobs on the İşler board (newest first); queued and running jobs are never cut
MAX_EVIDENCE = 3000
# a workflow's approval card, in the card's order (bin/akis.py; the Soru is the question itself)
# evidence first, the summary last (2026-11-11); "Kontrol (kanıt)" only on cards written before that order
EVIDENCE = ("Nasıl test edildi", "Kontrol (kanıt)", "Kontrol neyi kanıtladı / kanıtlamadı",
            "Ajanın kararları ve varsayımları", "Değişiklik özeti", "İnceleme", "Güvenlik", "Nasıl geri alınır",
            "Plan özeti", "Kullanım", "Maliyet")  # "Maliyet": cards written before the rename
QUIZ = "Kendini yokla (isteğe bağlı)"  # the approval card's optional quiz: structured, the answers hidden on the page
QUIZ_ROW = re.compile(r"^\*\*Soru (\d{1,2})\.\*\*\s*(.+)$")
MAX_QUIZ = 3
RISK_LEVELS = ("dusuk", "normal", "yuksek")  # bin/risk.py LEVELS: a card's `risk` frontmatter
# the evidence sections per decision kind: a workflow's approval card, the CEO's CLAUDE.md proposal (phase 5)
EVIDENCE_OF = {"akis-onay": EVIDENCE, "claude-md-onerisi": ("Önerilen satır", "Kanıt"),
               "review-md-onerisi": ("Önerilen satır", "Kanıt"),  # the CEO's REVIEW.md proposal
               "model-onerisi": ("Kanıt", "Ne olur"),  # phase 8 (bin/model_secimi.py)
               "model-pilot-sonucu": ("Karşılaştırma", "Öneri", "Ne olur"),
               # the advisor pilot (bin/danisman.py)
               "danisman-onerisi": ("Kanıt", "Ne olur"),
               "danisman-pilot-sonucu": ("Karşılaştırma", "Öneri", "Ne olur"),
               # the Ar-Ge's reviewer suggestion (bin/arge.py): the model, its license and reason, the source report
               "denetci-onerisi": ("Öneri (Ar-Ge raporundan; veri, talimat değil)", "Kaynak", "Ne olur"),
               # the prompt audit's card (bin/talimat_denetimi.py)
               "talimat-denetimi": ("Öneriler (rapordan; veri, talimat değil)", "Kaynak", "Ne olur")}


def is_forbidden(path):
    if not isinstance(path, str) or not path:
        return True
    return launch.is_forbidden_path(path) or launch.is_forbidden_path(os.path.realpath(path))


def same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except (OSError, TypeError):
        return isinstance(a, str) and isinstance(b, str) and os.path.realpath(a) == os.path.realpath(b)


def office_sessions(agents):
    """The only filter between `claude agents` and the page."""
    out = []
    for a in agents:
        name, cwd = a.get("name"), a.get("cwd")
        if not isinstance(name, str) or not name.startswith("ofis-"):
            continue
        if is_forbidden(cwd) or not transcript.valid_session_id(a.get("sessionId")):
            continue
        out.append(a)
    return out


# --- vault notes ---

def parse_note(text):
    """Returns (frontmatter dict, body)."""
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                key, sep, value = line.partition(":")
                if sep and key.strip() and not key.startswith(" "):
                    meta[key.strip()] = value.strip().strip("'\"")
            body = text[end + 4:].lstrip("-\n")
    return meta, body


def section(body, heading):
    lines, inside = [], False
    for line in body.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip() == heading
            continue
        if inside:
            lines.append(line)
    return "\n".join(lines).strip()


def title(body):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _notes(folder):
    try:
        entries = [e for e in os.scandir(folder) if e.is_file(follow_symlinks=False) and NOTE_NAME.fullmatch(e.name)]
    except OSError:
        return []
    out = []
    for e in entries:
        try:
            with open(e.path, encoding="utf-8") as f:
                meta, body = parse_note(f.read(64 * 1024))
            mtime = e.stat(follow_symlinks=False).st_mtime  # a note moved or deleted meanwhile is skipped
        except (OSError, UnicodeDecodeError):
            continue
        out.append((e.name, meta, body, mtime))
    return out


def decision_status(vault_ofis, note):
    """'ok' (pending), 'invalid' (bad name), 'missing' or 'not_pending' for a Kararlar note file name."""
    if not isinstance(note, str) or not NOTE_NAME.fullmatch(note) or note.startswith(".") or ".." in note:
        return "invalid"
    folder = os.path.join(vault_ofis, "Kararlar")
    path = os.path.join(folder, note)
    if os.path.islink(path) or not os.path.isfile(path) or os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        return "missing"
    try:
        with open(path, encoding="utf-8") as f:
            meta, _ = parse_note(f.read(64 * 1024))
    except (OSError, UnicodeDecodeError):
        return "missing"
    # a card a manager answered (bin/mudur.py) still takes the owner's answer: his answer replaces the manager's
    return "ok" if meta.get("durum") in ("bekliyor", mudur.DURUM) else "not_pending"


def _evidence(body, headings=EVIDENCE):
    """The evidence sections of a decision card (a workflow's approval card, bin/akis.py; a CLAUDE.md proposal) as
    plain text: the quote marks and the fences are only for the vault."""
    out = []
    for heading in headings:
        lines = []
        for line in section(body, heading).splitlines():
            bare = re.sub(r"^> ?", "", line) if line.startswith(">") else line
            bare = re.sub(r"^([\s>]*)\\\[!", r"\1[!", bare)  # the vault-only callout escape (kontrol.no_callout)
            if re.fullmatch(r"`{3,}", bare.strip()):
                continue
            lines.append(bare)
        text = "\n".join(lines).strip()
        if text:
            out.append({"title": heading, "text": text[:MAX_EVIDENCE]})
    return out


def quiz(body):
    """[{soru, cevap}] of an approval card's "Kendini yokla" section: `**Soru N.** <question>` lines, each followed by a
    collapsed callout (`> [!note]- Cevap` then `> <answer>` lines). Text only; at most MAX_QUIZ."""
    out, current = [], None
    for line in section(body, QUIZ).splitlines():
        m = QUIZ_ROW.match(line.strip())
        if m:
            current = {"soru": m.group(2).strip()[:300], "cevap": ""}
            out.append(current)
            continue
        if current is not None and line.startswith(">"):
            bare = re.sub(r"^> ?", "", line).strip()
            if re.match(r"^\[!note\]", bare, re.I):
                continue
            current["cevap"] = (current["cevap"] + " " + bare).strip()[:300]
    return [q for q in out if q["soru"] and q["cevap"]][:MAX_QUIZ]


def pending_decisions(vault_ofis):
    out = []
    for name, meta, body, mtime in _notes(os.path.join(vault_ofis, "Kararlar")):
        if meta.get("durum") != "bekliyor" or meta.get("mudur_bakiyor"):
            continue  # a question its manager is looking at is listed in mudur_kararlari (bin/mudur.py kararlar)
        # the post office quotes the project's words with "> " (so they cannot open sections); show them plainly
        soru = "\n".join(re.sub(r"^> ?", "", line) for line in section(body, "Soru").splitlines()).strip()
        question = soru or title(body)
        kind = meta.get("tur", "")
        out.append({"note": name, "project": meta.get("proje", ""), "title": title(body) or name[:-3],
                    "question": question[:MAX_QUESTION], "asked": meta.get("soruldu", ""),
                    "source": meta.get("kaynak_oturum", ""), "mtime": mtime, "kind": kind,
                    "evidence": _evidence(body, EVIDENCE_OF[kind]) if kind in EVIDENCE_OF else [],
                    "quiz": quiz(body) if kind == "akis-onay" else [],
                    # the CEO's own question (`ofis.py sor`): its options, shown as answer buttons
                    "options": jobs.question_options(body) if kind == "ceo-sorusu" else [],
                    # the approval card's risk level and an open security finding (bin/akis.py); "" / False else
                    "risk": meta.get("risk") if meta.get("risk") in RISK_LEVELS else "",
                    "guvenlik_acik": meta.get("guvenlik") == "acik-bulgu"})
    out.sort(key=lambda d: (d["asked"], d["mtime"]))
    for d in out:
        del d["mtime"]
    return out


def _last_quota_resume(rec):
    kd = (rec or {}).get("kota_devam")
    times = kd.get("zamanlar") if isinstance(kd, dict) else None
    return str(times[-1]) if isinstance(times, list) and times and isinstance(times[-1], str) else ""


def _count(value):
    """A small non-negative count from a note field; 0 when missing or unreadable."""
    text = str(value if value is not None else "").strip()
    # ASCII digits only: str.isdigit() also accepts "²" or "٣", which int() rejects (a session can edit its own note)
    return int(text) if text.isascii() and text.isdigit() and len(text) < 5 else 0


def task_title(meta, body):
    """baslik, else the first line of the Hedef (or of an older note's whole Görev), else the # title."""
    if meta.get("baslik"):
        return meta["baslik"][:140]
    hedef = jobs.read_brief(body)["hedef"].splitlines()
    return (hedef[0] if hedef else title(body))[:140]


def note_link(value):
    """A job note name usable as a link (plain file name), else ""."""
    if not isinstance(value, str) or not value:
        return ""
    name = value if value.endswith(".md") else value + ".md"
    return name if NOTE_NAME.fullmatch(name) and not name.startswith(".") and ".." not in name else ""


DEFAULT_MESAI = "08:30-18:30"
MESAI = re.compile(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)")


def mesai(cfg):
    """The living office's office hours "HH:MM-HH:MM" (ofis.json ofis_sahnesi.mesai; missing or invalid: the default;
    "", "yok", false or null: none, returned as "")."""
    raw = cfg.get("ofis_sahnesi") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    if "mesai" not in raw:
        return DEFAULT_MESAI
    value = raw.get("mesai")
    if value in (None, False, "", "yok"):
        return ""
    if isinstance(value, str) and MESAI.fullmatch(value) and value[:5] != value[6:]:
        return value
    return DEFAULT_MESAI


def katmanlar(cfg, durum_dir=None):
    """{genel: {tier: model}, projeler: {project: {tier: model}}}: the global tiers, and per project the tiers whose
    effective model differs from the global one — its override in ofis.json (launch.tier_entry) or a running pilot
    that still takes jobs (bin/model_secimi.py state). Display only."""
    tiers = cfg.get("tiers") if isinstance(cfg.get("tiers"), dict) else {}
    genel = {t: str(v.get("model") or "") for t, v in tiers.items() if isinstance(v, dict) and v.get("model")}
    projeler = {}
    for project in sorted(cfg.get("projects") or {}):
        for tier in tiers:
            model, _, source = launch.tier_entry(cfg, project, tier)
            if source == "proje" and model and model != genel.get(tier):
                projeler.setdefault(project, {})[tier] = str(model)
    if durum_dir:
        import model_secimi  # imports this module's neighbours only; kept local
        for st in model_secimi.all_states(durum_dir):
            if st.get("durum") != "pilot" or len(st.get("pilot_isler") or []) >= int(st.get("pilot_is") or 0):
                continue
            if st.get("proje") and st.get("katman") and st.get("onerilen_model"):
                projeler.setdefault(st["proje"], {})[st["katman"]] = str(st["onerilen_model"])
    return {"genel": genel, "projeler": projeler}


# Review 2026-11-12: the state is built every 1.5 s; job records and group reports are read again only when their file
# changed (stat: mtime_ns, size, inode). Display data only; a cache miss reads exactly as before.
_RECORD_CACHE = {}  # record path -> (stat key, record or None)
_REPORT_CACHE = {}  # report path -> (stat key, summary)


def _stat_key(path):
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino, st.st_mode)


def cached_record(durum_dir, job_name):
    """records.load(durum_dir, job_name), read again only when the record file changed."""
    try:
        path = records.path(durum_dir, job_name)
    except jobs.JobError:
        return None
    key = _stat_key(path)
    if key is None:
        _RECORD_CACHE.pop(path, None)
        return None
    hit = _RECORD_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    data = records.load(durum_dir, job_name)
    _RECORD_CACHE[path] = (key, data)
    return data


def son_rapor(vault_ofis):
    """{grup, baslik, yazildi} of the group report written last (OFIS/Raporlar), or None."""
    try:
        reports = rapor.list_reports(vault_ofis, limit=10000, cache=_REPORT_CACHE)
    except Exception:  # noqa: BLE001 — display only, never breaks the state
        return None
    reports = [r for r in reports if r.get("yazildi")]
    if not reports:
        return None
    r = max(reports, key=lambda x: (x["yazildi"], x["grup"]))
    return {"grup": r["grup"], "baslik": r.get("baslik", ""), "yazildi": r["yazildi"]}


# --- the per-job progress line ("yol çizgisi", owner decision 2026-11-14): real stamps only, never an invented step ---

YOL_ADIMLARI = ("alindi", "verildi", "calisiyor", "kontrol", "rapor", "ceo", "iletildi")
WORKING = ("calisiyor", "karar-bekliyor", "incelemede")
# the CEO notices that tell a job's outcome, keyed by the job's stem (bin/kontrol.py, bin/postoffice.py,
# bin/dispatcher.py, bin/budget.py): the part after "<kind>-<stem>"
NOTICE_REST = {"kontrol": re.compile(r"-\d+(?:-i\d+)?(?:-red(?:-d\d+)?)?"), "yukseltme": re.compile(r"(?:-d\d+)?"),
               "butce": re.compile(r"-[0-9.e+-]+"), "cagri": re.compile(r"-\d+"),
               "baslatma": re.compile(r"(?:-[0-9a-f]{8})?")}
NOTICE_KEY = re.compile(r"(kontrol|yukseltme|butce|cagri|baslatma)-(.+)")
GROUP_KEY = re.compile(r"rapor-(.+)-v\d+")
STAMP = "%Y-%m-%dT%H:%M:%S"
RELAY_SLACK = timedelta(seconds=30)  # the delivered prompt's transcript record can precede the sent-log line a little


def bildirim_dizini(sent):
    """The CEO channel's sent log ({key: local time or ""}) indexed for is_yolu: {"is": {stem: [time]}, "gelen":
    {message id: time}, "grup": {group: [time]}}."""
    out = {"is": {}, "gelen": {}, "grup": {}}
    for key, when in (sent or {}).items():
        if key.startswith("gelen-"):
            out["gelen"][key[6:]] = when
            continue
        m = GROUP_KEY.fullmatch(key)
        if m:
            out["grup"].setdefault(m.group(1), []).append(when)
            continue
        m = NOTICE_KEY.fullmatch(key)
        if not m:
            continue
        kind, rest = m.groups()
        cuts = [len(rest)] + [i for i in range(len(rest) - 1, 0, -1) if rest[i] == "-"]
        for i in cuts:  # every split "<stem><rest>" whose rest has this kind's shape
            if NOTICE_REST[kind].fullmatch(rest[i:]):
                out["is"].setdefault(rest[:i], []).append(when)
    return out


def bildirim_zamani(dizin, note, son_mesaj, grup, bitis):
    """When the CEO got this job's outcome notice: the earliest delivery at or after `bitis` among its own notices,
    its last report message's notice and its group report; "" when delivered before times were kept; None when none
    was delivered."""
    stem = note[:-3] if note.endswith(".md") else note
    found = list(dizin["is"].get(stem, ()))
    if son_mesaj and son_mesaj in dizin["gelen"]:
        found.append(dizin["gelen"][son_mesaj])
    if grup:
        found.extend(dizin["grup"].get(grup, ()))
    if not found:
        return None
    timed = sorted(w for w in found if w and (not bitis or w >= bitis[:19]))
    if timed:
        return timed[0]
    return "" if any(not w for w in found) else None


def _dt(value):
    try:
        return datetime.strptime(str(value)[:19], STAMP)
    except ValueError:
        return None


def iletildi_zamani(bildirim, turlar):
    """(durum, zaman) of "sana iletildi": the CEO's reply in the first turn that began with (or right after) the
    delivery and did not end before it. turlar: [{basla, bitis, cevap_zaman}] in local "YYYY-MM-DDTHH:MM:SS",
    oldest first. Unknown when the delivery time is unknown or older than the turns read (the transcript's tail)."""
    t = _dt(bildirim)
    starts = [_dt(x.get("basla")) for x in turlar or ()]
    if t is None or not starts or not starts[0] or starts[0] > t + RELAY_SLACK:
        return "bilinmiyor", ""
    for tur, basla in zip(turlar, starts):
        bitis = _dt(tur.get("bitis"))
        if basla is None or basla < t - RELAY_SLACK or (bitis is not None and bitis < t):
            continue
        if tur.get("cevap_zaman"):
            return "tamam", tur["cevap_zaman"]
        return ("bilinmiyor", "") if bitis is not None else ("simdi", "")
    return "simdi", ""


def is_yolu(task, ek=None, bildirim=None, turlar=(), izin=False):
    """The job's progress line: [{adim, durum, zaman, not}] in YOL_ADIMLARI order. durum: tamam (with its stamp),
    simdi (the current step), bekliyor (still ahead), hata (stopped here; `not` = the reason word), atlandi (Kontrol
    yok), yok (will not happen), bilinmiyor (it happened or not, the records cannot tell). The current step's `not`
    says what it waits for: "cevap" (a question to the owner), "izin" (a permission prompt). ek: {mesaj_zamani (the last
    report's arrival), kontrol_var, durdurma (budget/call stop)}; bildirim: bildirim_zamani(); turlar: the CEO's turns."""
    ek = ek or {}
    s = task.get("status", "")
    steps = {a: {"adim": a, "durum": "bekliyor", "zaman": "", "not": ""} for a in YOL_ADIMLARI}

    def put(adim, durum, zaman="", note=""):
        steps[adim].update(durum=durum, zaman=zaman or "", **({"not": note} if note else {}))

    put("alindi", "tamam", task.get("created") or task.get("started"))
    started, finished = task.get("started") or "", task.get("finished") or ""
    final = s in jobs.FINAL_STATUSES
    kontrol_sonuc = task.get("kontrol_sonuc") or ""
    no_kontrol = kontrol_sonuc in ("yok", "kayit-yok", "calistirilmadi") or (
        not ek.get("kontrol_var") and (final or s in WORKING or s == "kontrolde"))
    if no_kontrol:
        put("kontrol", "atlandi")
    if s in ("sirada", "baslatiliyor"):
        put("verildi", "simdi")  # key kept for the API; it means "a worker takes the job" (the start), not a hand-over
        return [steps[a] for a in YOL_ADIMLARI]
    if s == "basarisiz" or (s == "iptal" and not started):
        put("verildi", "hata", note="başlatılamadı" if s == "basarisiz" else "iptal")
        for a in ("calisiyor", "kontrol", "rapor"):
            put(a, "yok")
    else:
        put("verildi", "tamam" if started else "bilinmiyor", started)
        report = ek.get("mesaj_zamani") or ""
        if s in WORKING:
            put("calisiyor", "simdi", note="cevap" if s == "karar-bekliyor" else "izin" if izin else "")
        elif s == "kontrolde":
            put("calisiyor", "tamam", report)
            put("kontrol", "simdi")
        elif s == "bitti":
            put("calisiyor", "tamam", report)
            if not no_kontrol:
                put("kontrol", "tamam", finished)
            put("rapor", "tamam", finished)
        elif s == "tikandi":
            why = ("üst katmana taşındı" if task.get("escalated_to") else
                   {"butce": "kullanım sınırı doldu", "cagri": "çağrı sınırı"}.get(ek.get("durdurma"), "takıldı"))
            if kontrol_sonuc == "kaldi":
                put("calisiyor", "tamam", report)
                put("kontrol", "hata", finished, why)
            else:
                put("calisiyor", "hata", finished, why)
                if not no_kontrol:
                    put("kontrol", "yok")
            put("rapor", "tamam" if finished else "bilinmiyor", finished)
        elif s == "iptal":
            put("calisiyor", "hata", finished, "iptal")
            for a in ("kontrol", "rapor"):
                if steps[a]["durum"] != "atlandi":
                    put(a, "yok")
    if not final:
        return [steps[a] for a in YOL_ADIMLARI]
    if bildirim is None:
        # no outcome notice delivered: it waits in the queue or for its group report; a cancelled job has none
        if s in ("iptal", "basarisiz"):
            put("ceo", "yok")
            put("iletildi", "yok")
        else:
            put("ceo", "simdi")
        return [steps[a] for a in YOL_ADIMLARI]
    put("ceo", "tamam", bildirim)
    durum, zaman = iletildi_zamani(bildirim, turlar)
    put("iletildi", durum, zaman)
    return [steps[a] for a in YOL_ADIMLARI]


def mesaj_zamani(message_id):
    """The local arrival time of an inbox message id ("<ns>-…"), "" when it is not one."""
    head = str(message_id or "").split("-", 1)[0]
    if not head.isdigit() or len(head) < 18:
        return ""
    try:
        return datetime.fromtimestamp(int(head) / 1e9).strftime(STAMP)
    except (OverflowError, OSError, ValueError):
        return ""


def yerel_zaman(value):
    """A transcript's UTC stamp ("…Z") as local "YYYY-MM-DDTHH:MM:SS"; "" when unreadable."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return (d.astimezone() if d.tzinfo else d).replace(tzinfo=None).strftime(STAMP)


def yol_ekle(tasks, extras, sent=None, turlar=(), izinli=()):
    """Sets task["yol"] on each task (extras: {note: ek with son_mesaj, grup}); sent: the CEO's sent_times();
    turlar: the CEO's turns, local stamps, oldest first; izinli: session names at a permission prompt."""
    dizin = bildirim_dizini(sent)
    izinli = set(izinli or ())
    for t in tasks:
        ek = extras.get(t["note"], {})
        when = None
        if t["status"] in jobs.FINAL_STATUSES:
            when = bildirim_zamani(dizin, t["note"], ek.get("son_mesaj"), ek.get("grup"), t.get("finished"))
        t["yol"] = is_yolu(t, ek, when, turlar, izin=bool(t.get("session")) and t["session"] in izinli)


def recent_tasks(vault_ofis, limit=MAX_TASKS, cfg=None, durum_dir=None, extras=None):
    """Job notes of Siradakiler, Devam-Edenler, Bitenler (and the flat legacy Isler folder until it is migrated),
    newest first by start (or creation) time. A name is listed once (a job folder wins over the legacy folder).
    With cfg, each task also carries its limits (budget USD, max_calls; job field else the ofis.json default) next
    to the recorded spending (spent, calls: the server's throttled harcanan_usd / cagri, "" until known).
    Queued jobs carry their place in their project's queue, hold, dependencies and engel (bin/dispatcher.py; the
    server record's values when durum_dir is given); an escalated job its source (escalated_from), the source its
    replacement (escalated_to). extras: a dict filled with each job's facts for the progress line (yol_ekle)."""
    queue = dispatcher.queue_info(cfg or {"vault_ofis": vault_ofis}, vault_ofis, durum_dir)
    out, seen = [], set()
    for job in jobs.list_jobs(vault_ofis, legacy=True):
        if job.name in seen:
            continue
        seen.add(job.name)
        meta = job.meta
        # the living office draws a job by its tier, model and step kind: the server record's values (the note is for
        # reading only; a project session could edit it), the note's for a job without a record
        rec = (cached_record(durum_dir, job.name) or {}) if durum_dir else {}
        out.append({"note": job.name, "project": meta.get("proje", ""), "status": meta.get("durum", ""),
                    "started": meta.get("baslangic", ""), "finished": meta.get("bitis", ""),
                    "created": meta.get("olusturuldu", ""),
                    "session": meta.get("oturum", ""), "short_id": meta.get("kisa_id", ""),
                    "title": task_title(meta, job.body), "tier": str(rec.get("katman") or meta.get("katman", "")),
                    "model": str(rec.get("model") or meta.get("model", "")),
                    "spent": meta.get("harcanan_usd", ""), "calls": meta.get("cagri", ""),
                    "tokens": meta.get("harcanan_token", ""),
                    # the psychologist's card (display only): Kontrol attempts, devam rounds
                    "kontrol_deneme": _count(meta.get("kontrol_deneme")), "kontrol_sonuc": meta.get("kontrol_sonuc", ""),
                    "devam": _count(meta.get("devam_sayisi")),
                    "escalated_from": note_link(meta.get("yukseltme_kaynagi")),
                    # phase 4: a workflow step (display values; the page groups the steps under their workflow)
                    "workflow": meta.get("akis", ""), "step": meta.get("adim", ""),
                    "step_kind": str(rec.get("adim_turu") or meta.get("adim_turu", "")),
                    # living office: who reviews (codex / "claude (codex yok: …)"), from the server record only
                    "inceleme_yurutucu": str(rec.get("inceleme_yurutucu") or "") if meta.get("akis") or rec.get("akis") else "",
                    # plan "Sonraki iş (9)" step 2: the job's specialisation (server record only; "" before step 2)
                    "uzmanlik": str(rec.get("uzmanlik") or ""),
                    # the end-of-day review job (bin/gunsonu.py): its day, from the server record only — the page keeps
                    # it away from the Ar-Ge uzmanı's desk and seats the Değerlendirme ekibi for it
                    "gun_sonu": str(rec.get("gun_sonu") or ""),
                    # Step 5: the newest automatic resume after a quota (server record only)
                    "kota_devam": _last_quota_resume(rec),
                    # the advisor (bin/danisman.py): arm B of the advisor pilot or the mapped advisor's model, from the
                    # server record only; "" for none (the card shows "Danışman: Fable")
                    "danisman": str(rec.get("danisman") or ""),
                    # why it gets the advisor ("zor iş: …", bin/danisman.py advisor_decision), server record only
                    "danisman_nedeni": str(rec.get("danisman_nedeni") or "")})
        info = queue.get(job.name) if meta.get("durum") == "sirada" else None
        out[-1].update({"queue_position": info["position"] if info else None, "held": bool(info and info["held"]),
                        "depends": info["depends"] if info else [], "blocked": info["blocked"] if info else "",
                        # a kod job the dispatcher holds while approval cards pile up (bin/dispatcher.py)
                        "onay_birikti": bool(info and info.get("onay_birikti")),
                        # Step 4: its model and the backup are both on quota (bin/dispatcher.py)
                        "kota_bekliyor": str((info or {}).get("kota_bekliyor") or "")})
        if cfg is not None:
            out[-1]["budget"], out[-1]["max_calls"] = budget.limits(cfg, job)
        if extras is not None:
            messages = [m for m in str(meta.get("islenen_mesajlar") or "").split(",") if m]
            extras[job.name] = {"son_mesaj": messages[-1] if messages else "",
                                "mesaj_zamani": mesaj_zamani(messages[-1]) if messages else "",
                                "kontrol_var": bool(rec.get("kontrol_ozet")),
                                "durdurma": str(meta.get("durdurma_nedeni") or ""),
                                "grup": str(rec.get("akis") or rec.get("grup") or "")}
    replaced = {t["escalated_from"]: t["note"] for t in out if t["escalated_from"]}
    for t in out:
        t["escalated_to"] = replaced.get(t["note"], "")
    out.sort(key=lambda t: (t["started"] or t["created"], t["note"]), reverse=True)
    return out[:limit] if limit else out


def board_tasks(tasks, done_limit=BOARD_DONE):
    """The jobs of the page's İşler board (phase 7): every job that is not final (queued, running, waiting for a
    decision, in Kontrol — a short list, bounded by the dispatcher's limits), the `done_limit` newest finished ones,
    and every other step of a workflow among them: the page draws a workflow as one card with all its steps."""
    final = set(jobs.FINAL_STATUSES)
    done = sorted((t for t in tasks if t["status"] in final),
                  key=lambda t: (t["finished"] or t["started"] or t["created"], t["note"]), reverse=True)
    picked = [t for t in tasks if t["status"] not in final] + done[:done_limit]
    flows = {t["workflow"] for t in picked if t["workflow"]}
    return picked + [t for t in done[done_limit:] if t["workflow"] in flows]


def _gun_sonu_ozeti(cfg, durum_dir):
    """/api/state.gun_sonu (bin/gunsonu.py ozet_durumu); None when it cannot be read — never fails the state build."""
    try:
        return gunsonu.ozet_durumu(cfg or {}, durum_dir) if durum_dir else None
    except Exception:  # noqa: BLE001 — display only
        return None


def _yakala_ozeti(cfg, durum_dir):
    """/api/state.yakala (bin/yakala.py sayfa); None when it cannot be read — never fails the state build."""
    try:
        return yakala.sayfa(cfg or {}, durum_dir) if durum_dir else None
    except Exception:  # noqa: BLE001 — display only
        return None


def _limitler_ozeti(cfg):
    """/api/state.limitler (bin/limitler.py sayfa): the owner's Claude plan usage limits; None when off, without data or
    unreadable — never fails the state build."""
    try:
        return limitler.sayfa(cfg or {})
    except Exception:  # noqa: BLE001 — display only
        return None


def _hafiza_ozeti(durum_dir):
    """/api/state.hafiza (bin/hafiza.py ozet); {} when its index cannot be read — never fails the state build."""
    try:
        return hafiza.ozet(durum_dir)
    except Exception:  # noqa: BLE001
        return {}


# --- builder ---

class OfficeState:
    def __init__(self, cfg, cli, ceo, root, projects_dir, durum_dir, today=date.today, now=datetime.now):
        self.postoffice = None  # set by the server; its status is part of the state
        self.sunucu = None  # set by the server: {baslangic, pid} of this start (the İdari işler card)
        self.olaylar = None  # set by the server: its error record (bin/olaylar.py) — the newest rows for the doctor
        self.sistem = None  # set by the server: bin/sistem.py Sistem — the Sunucu odası's lights (cached summary only)
        self.cfg = cfg
        self.cli = cli
        self.ceo = ceo
        self.root = root
        self.vault_ofis = os.path.expanduser(cfg["vault_ofis"])
        self.durum_dir = durum_dir
        self.today = today
        self.now = now
        self.transcripts = transcript.TranscriptCache(projects_dir)
        self.projects_dir = projects_dir
        self.sessions_file = os.path.join(durum_dir, "sessions.json")
        self._known = self._load_known()
        # living office: cached readers (stat every build, read only what changed)
        self.subagents = alt_ajan.SubagentScanner()
        self.model_scans = model_durum.TranscriptScanner()
        self.codex_scans = model_durum.CodexScanner()
        self.denetci_scans = model_durum.DenetciScanner()

    def claude_kotalari(self):
        """{Claude family: return time (aware) or None} of the families on quota now, for the dispatcher's quota
        fallback (bin/dispatcher.py, Step 4): the same usage-limit records as the page's model rows, from the office
        transcripts this server has seen (the CEO's and every known ofis-* session; no `claude agents` call). Runs in the
        post office thread with its own cached scanner."""
        scanner = self.__dict__.setdefault("_kota_scans", model_durum.TranscriptScanner())
        now = self.now()
        files = {sid: k["cwd"] for sid, k in dict(self._known).items() if isinstance(k.get("cwd"), str)
                 and not is_forbidden(k["cwd"])}
        try:
            ceo_sid = self.ceo.session_id()  # the session record only (never a `claude agents` call)
        except Exception:  # unreadable: the CEO's transcript is left out this pass
            ceo_sid = None
        if transcript.valid_session_id(ceo_sid):
            files.setdefault(ceo_sid, self.root)
        oldest = now.timestamp() - MODEL_SCAN_AGE.total_seconds()
        scans = []
        for sid, cwd in files.items():
            path = transcript.transcript_path(self.projects_dir, cwd, sid)
            if transcript.forbidden_folder(os.path.dirname(path)):
                continue
            try:
                if os.stat(path).st_mtime < oldest:
                    continue
            except OSError:
                continue
            scan = scanner.scan(path)
            if scan is not None:
                scans.append((scan, ""))
        tz = model_durum.office_tz(model_durum.sahne(self.cfg)["saat_dilimi"])
        out = {}
        for row in model_durum.build(scans, [], {}, now, tz):
            if row["model"] in model_durum.CLAUDE and row["durum"] == "kota":
                try:
                    out[row["model"]] = datetime.fromisoformat(row["donus"]) if row["donus"] else None
                except ValueError:
                    out[row["model"]] = None
        return out

    def _load_known(self):
        try:
            with open(self.sessions_file, encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if transcript.valid_session_id(k) and isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}

    def _remember(self, sid, project, cwd, name):
        entry = {"project": project, "cwd": cwd, "name": name}
        if self._known.get(sid) == entry:
            return
        self._known[sid] = entry
        os.makedirs(self.durum_dir, exist_ok=True)
        tmp = self.sessions_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._known, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.sessions_file)

    def projects(self):
        out = {}
        for name, entry in self.cfg["projects"].items():
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                continue
            path = os.path.realpath(os.path.expanduser(entry["path"]))
            if not is_forbidden(path):
                out[name] = {"path": path, "description": entry.get("description", "")}
        return out

    def _project_of(self, agent, projects):
        for name, p in projects.items():
            if same_dir(agent.get("cwd"), p["path"]):
                return name
        for name in projects:
            if agent.get("name", "").startswith(f"ofis-{name}-"):
                return name
        return None

    def _task_sessions(self, tasks, projects):
        """Resolves the short ids written in task notes to transcript files of that project."""
        for t in tasks:
            p = projects.get(t["project"])
            short = t["short_id"]
            if not p or not transcript.valid_session_id(short) or len(short) < 8:
                continue
            if any(sid.startswith(short) for sid in self._known):
                continue
            folder = transcript.project_folder(self.projects_dir, p["path"])
            if transcript.forbidden_folder(folder):
                continue
            try:
                names = [n for n in os.listdir(folder) if n.startswith(short) and n.endswith(".jsonl")]
            except OSError:
                continue
            if len(names) == 1:
                self._remember(names[0][:-6], t["project"], p["path"], t["session"])

    def _tokens_cost_tool(self, sids, today):
        tokens, cost, tool = 0, 0.0, None
        for sid, cwd in sids:
            path = transcript.transcript_path(self.projects_dir, cwd, sid)
            if transcript.forbidden_folder(os.path.dirname(path)):
                continue  # the "-" encoding of an allowed cwd may still name a forbidden project's folder
            try:
                if date.fromtimestamp(os.stat(path).st_mtime) < today:
                    continue  # nothing written today: skip without reading
            except OSError:
                continue
            st = self.transcripts.get(cwd, sid)
            if st is None:
                continue
            tokens += st.tokens_on(today.isoformat())
            cost += st.cost_on(today.isoformat())
            if st.last_tool and (tool is None or (st.last_tool["time"] or "") > (tool["time"] or "")):
                tool = st.last_tool
        return tokens, cost, tool

    def _session_breakdown(self, sid, cwd, day):
        path = transcript.transcript_path(self.projects_dir, cwd, sid)
        if transcript.forbidden_folder(os.path.dirname(path)):
            return None
        try:
            if date.fromtimestamp(os.stat(path).st_mtime) < self.today():
                return None  # nothing written today
        except OSError:
            return None
        st = self.transcripts.get(cwd, sid)
        if st is None:
            return None
        b = st.breakdown_on(day)
        return b if b["total"] else None

    def usage_detail(self, project):
        """Today's tokens of one project (or "ceo"), per session, by usage field and by tool. None if unknown."""
        day = self.today().isoformat()
        if project == "ceo":
            sid = self.ceo.status().get("session_id")
            entries = [(i, {"cwd": self.root, "name": self.cfg["ceo_session"]})
                       for i in (self._ceo_earlier(sid) + [sid] if sid else [])]
        else:
            if project not in self.projects():
                return None
            entries = [(sid, k) for sid, k in self._known.items() if k.get("project") == project]
        tasks = recent_tasks(self.vault_ofis, limit=0) if project != "ceo" else []
        sessions = []
        for sid, k in entries:
            b = self._session_breakdown(sid, k["cwd"], day)
            if not b:
                continue
            task = next((t for t in tasks if t["session"] == k.get("name")
                         or (len(t["short_id"]) >= 8 and sid.startswith(t["short_id"]))), None)
            sessions.append({"name": k.get("name") or sid[:8], "task": task["title"] if task else "",
                             "note": task["note"] if task else "", **b})
        sessions.sort(key=lambda x: x["total"], reverse=True)
        fields = dict.fromkeys(transcript.USAGE_FIELDS, 0)
        for x in sessions:
            for f in fields:
                fields[f] += x["fields"].get(f, 0)
        by_model = {}
        for x in sessions:
            for model, v in x.get("by_model", {}).items():
                m = by_model.setdefault(model, {"total": 0, "calls": 0, "cost": 0.0})
                m["total"] += v["total"]
                m["calls"] += v["calls"]
                m["cost"] = None if m["cost"] is None or v.get("cost") is None else m["cost"] + v["cost"]
        cost = dict.fromkeys((*transcript.USAGE_FIELDS, "total"), 0.0)
        for x in sessions:
            for k in cost:
                cost[k] += x.get("cost", {}).get(k, 0.0)
        return {"project": project, "day": day, "total": sum(x["total"] for x in sessions),
                "fields": fields, "by_model": by_model, "cost": cost,
                "unpriced_calls": sum(x.get("unpriced_calls", 0) for x in sessions),
                "prices_as_of": pricing.PRICES_AS_OF, "sessions": sessions}

    def build(self):
        today = self.today()
        projects = self.projects()
        error = None
        try:
            agents = office_sessions(self.cli.agents())
        except claude_cli.ClaudeError as e:
            agents, error = [], str(e)
        ceo_name = self.cfg["ceo_session"]
        sessions, by_project = [], {name: [] for name in projects}
        for a in agents:
            if a.get("name") == ceo_name and same_dir(a.get("cwd"), self.root):
                continue
            project = self._project_of(a, projects)
            if project is None:
                continue  # an ofis-* session outside the registry is not shown
            self._remember(a["sessionId"], project, a["cwd"], a["name"])
            by_project[project].append(a)
            sessions.append({"name": a["name"], "project": project, "status": a.get("status"),
                             "kind": a.get("kind"), "started_at": a.get("startedAt"),
                             "_sid": a["sessionId"], "_cwd": a["cwd"]})
        decisions = pending_decisions(self.vault_ofis)
        extras = {}
        all_tasks = recent_tasks(self.vault_ofis, limit=0, cfg=self.cfg, durum_dir=self.durum_dir, extras=extras)
        self._task_sessions(all_tasks[:50], projects)
        sahne = model_durum.sahne(self.cfg)
        # the office hours of the living office (web/ofis-davranis.js mesaiMi): ofis_sahnesi.mesai, default 08:30-18:30
        sahne["mesai"] = mesai(self.cfg)
        tz = model_durum.office_tz(sahne["saat_dilimi"])
        now = self.now()
        # the job notes' naive stamps are the server's local time: the page reads them with this offset
        sahne["sunucu_utc_ofset_dk"] = model_durum.sunucu_ofset_dk(now)
        now = (now if now.tzinfo else now.astimezone()).astimezone(tz)
        self._join_sessions(sessions, all_tasks, now)
        today_iso = today.isoformat()
        out_projects = []
        for name, p in projects.items():
            busy = any(a.get("status") == "busy" for a in by_project[name])
            waiting = any(d["project"] == name for d in decisions)
            sids = [(sid, k["cwd"]) for sid, k in self._known.items() if k.get("project") == name]
            tokens, cost, tool = self._tokens_cost_tool(sids, today)
            out_projects.append({
                "name": name, "description": p["description"],
                "klasor": os.path.basename(os.path.normpath(p["path"])) if p.get("path") else "",  # the name only
                "status": "calisiyor" if busy else ("bekliyor" if waiting else "uyuyor"),
                "sessions": len(by_project[name]), "usage_today": tokens, "cost_today": round(cost, 4), "last_tool": tool,
                "tasks": [t for t in all_tasks if t["project"] == name][:5],
                # the project sorumlusu's card: the rules and the three sections of OFIS/Projeler/<proje>.md
                "sorumlu": sorumlu.sayfa_ozeti(self.cfg, name),
            })
        board = board_tasks(all_tasks)  # board_hidden: the finished jobs it leaves out ("N daha eski" on the page)
        ceo = self.ceo.status()
        ceo_tokens, ceo_cost, ceo_tool = 0, 0.0, None
        if ceo.get("session_id"):
            # today's CEO spending also counts the sessions it was rotated away from today (bin/ceo.py rotation)
            ceo_tokens, ceo_cost, ceo_tool = self._tokens_cost_tool(
                [(i, self.root) for i in self._ceo_earlier(ceo["session_id"])] + [(ceo["session_id"], self.root)],
                today)
        ceo.update({"name": ceo_name, "usage_today": ceo_tokens, "cost_today": round(ceo_cost, 4),
                    "current_tool": ceo_tool if ceo.get("state") == "busy" else None,
                    "last_error": self.ceo.last_error,
                    "alt_ajanlar": self.subagents.list(transcript.project_folder(self.projects_dir, self.root),
                                                       ceo.get("session_id"), now)})
        # "Cevap verdi · tur kapanıyor": the reply is written, no tool call pends, the turn-end record is not there yet
        # the context size of the CEO's newest model call (the rotation's measure; None when unknown)
        ceo["baglam_token"] = self._ceo_context(ceo.get("session_id"))
        ceo["tur_kapaniyor"] = bool(ceo.get("state") == "busy" and self._ceo_closing(ceo.get("session_id")))
        # the per-job progress line: the CEO channel's delivery times and the CEO's turns (display only)
        yol_ekle(all_tasks, extras, self._ceo_sent(), self._ceo_turlar(ceo.get("session_id")),
                 {s["name"] for s in sessions if s.get("status") == "waiting"})
        denetim = self._denetim()
        modeller = self._models(sessions, all_tasks, ceo, now, tz, denetim)
        for s in sessions:
            del s["_sid"], s["_cwd"]
        return {
            "today": today_iso,
            "projects": out_projects,
            "sessions": sessions,
            "ceo": ceo,
            "decisions": decisions,
            # step 4: the questions a manager is looking at or has answered (bin/mudur.py); the owner can still answer
            "mudur_kararlari": mudur.kararlar(self.vault_ofis),
            "tasks": all_tasks[:MAX_TASKS],
            "board": board,
            "board_hidden": sum(1 for t in all_tasks if t["status"] in jobs.FINAL_STATUSES) - \
            sum(1 for t in board if t["status"] in jobs.FINAL_STATUSES),
            "workflows": akis.summaries(self.durum_dir),
            "schedules": zamanla.summaries(self.durum_dir, self.now()),
            "summary": {
                "tasks_today": sum(1 for t in all_tasks if t["started"].startswith(today_iso)),
                "finished_today": sum(1 for t in all_tasks if t["status"] in jobs.FINAL_STATUSES
                                      and t["finished"].startswith(today_iso)),
                "working": sum(1 for p in out_projects if p["status"] == "calisiyor"),
                "waiting": sum(1 for p in out_projects if p["status"] == "bekliyor"),
                "sleeping": sum(1 for p in out_projects if p["status"] == "uyuyor"),
                "usage_today": ceo_tokens + sum(p["usage_today"] for p in out_projects),
                "pending_decisions": len(decisions),
                "running": sum(1 for t in all_tasks if t["status"] in dispatcher.RUNNING),
                "max_running": dispatcher.limits(self.cfg)[0],
                # the living office's desk count per team (web/ofis-davranis.js masaSayisi)
                "max_running_per_project": dispatcher.limits(self.cfg)[1],
                # the approval backlog: {bekleyen, sinir}; the page shows its strip when bekleyen >= sinir
                "onay_birikti": {k: v for k, v in dispatcher.onay_birikti(self.cfg, self.vault_ofis).items()
                                 if k in ("bekleyen", "sinir")},
            },
            "agents_error": error,
            "postoffice": self.postoffice.status() if self.postoffice else None,
            "modeller": modeller,
            # the review panel's phase now (bin/denetci.py running_info): who reviews which job, or the hakem; None
            "denetim": denetim,
            "sahne": sahne,
            # the office's own name (ofis.json ofis_adi, the Ayarlar tab; default "Ofis"): the page title and the sign
            "ofis": {"adi": ayarlar.ofis_adi(self.cfg)},
            # the owner's display name (ofis.json sahip_adi, the Ayarlar tab; default "Sahip") with its case forms
            # {adi, e, in, den, i, de}: every page text that names the owner (web/ofis-davranis.js sahipAyarla)
            "sahip": sahip.ekler(self.cfg),
            "sunucu": self.sunucu,
            "olaylar": self.olaylar.son(5) if self.olaylar else None,
            # the Sunucu odası (bin/sistem.py ozet, from the cache, never a command): {seviye, oneri, domain_sorunu}
            "sistem": self.sistem.ozet() if self.sistem else None,
            # the latest announcement (bin/duyuru.py son): the conference hall's screen and gathering; display only
            "duyuru": duyuru.son(self.durum_dir),
            # plan "Sonraki iş (9)" step 3: the worker memory per specialisation (bin/hafiza.py ozet: lesson counts, the
            # newest lesson's date, the note's name) for the İK card and a job's card; display only
            "hafiza": _hafiza_ozeti(self.durum_dir),
            # the end-of-day review (bin/gunsonu.py ozet_durumu): the last run, its numbers, the note, skipped days;
            # the Değerlendirme ekibi's desks and card; display only
            "gun_sonu": _gun_sonu_ozeti(self.cfg, self.durum_dir),
            # the Yakala box (bin/yakala.py sayfa): on / off, the file limit, the last few captures; display only
            "yakala": _yakala_ozeti(self.cfg, self.durum_dir),
            # The owner's Claude plan usage limits (bin/limitler.py sayfa; ofis.json limitler): the top bar's pill
            "limitler": _limitler_ozeti(self.cfg),
            # the effective tier -> model mapping (global, project overrides, running pilots): the living office's
            # fallback for a job without a known model and the kadro card's "Görevi"
            "katmanlar": katmanlar(self.cfg, self.durum_dir),
            # the newest group report (bin/rapor.py): the living office's Sekreter files it (a cue, display only)
            "son_rapor": son_rapor(self.vault_ofis),
        }

    def _ceo_earlier(self, sid):
        getter = getattr(self.ceo, "earlier_ids", None)
        try:
            # every recorded rotation (bounded in durum/ceo.json): the totals skip files not written today unread
            return [i for i in getter(limit=None) if i != sid] if getter else []
        except Exception:  # noqa: BLE001 — an unreadable record: the current session only
            return []

    def _ceo_sent(self):
        getter = getattr(self.ceo, "sent_times", None)
        try:
            return getter() if getter else {}
        except Exception:  # noqa: BLE001 — display only
            return {}

    def _ceo_turlar(self, sid):
        """The CEO's turns (current session and the last rotated ones; transcript tails only), oldest first, with
        local stamps: [{basla, bitis, cevap_zaman}]."""
        turns = []
        for i in self._ceo_earlier_few(sid) + [sid]:
            if not transcript.valid_session_id(i):
                continue
            path = transcript.transcript_path(self.projects_dir, self.root, i)
            if transcript.forbidden_folder(os.path.dirname(path)):
                continue
            for t in (adimlar.read_tail(path) or {}).get("turns") or []:
                turns.append({k: yerel_zaman(t.get(k)) for k in ("basla", "bitis", "cevap_zaman")})
        turns.sort(key=lambda t: t["basla"])
        return turns

    def _ceo_earlier_few(self, sid):
        getter = getattr(self.ceo, "earlier_ids", None)
        try:
            return [i for i in getter() if i != sid] if getter else []
        except Exception:  # noqa: BLE001
            return []

    def _ceo_context(self, sid):
        if not transcript.valid_session_id(sid):
            return None
        path = transcript.transcript_path(self.projects_dir, self.root, sid)
        if transcript.forbidden_folder(os.path.dirname(path)):
            return None
        found = transcript.last_context(path)
        return found["token"] if found else None

    def _ceo_closing(self, sid):
        if not transcript.valid_session_id(sid):
            return False
        path = transcript.transcript_path(self.projects_dir, self.root, sid)
        if transcript.forbidden_folder(os.path.dirname(path)):
            return False
        return adimlar.tur_kapaniyor(path)

    def _denetim(self):
        """{is, denetciler, hakem, baslangic} of the review panel this server runs now (the reviewers at work, or the
        hakem's model while it weighs their findings), else None."""
        info = denetci.running_info(self.durum_dir)
        if info is None:
            return None
        return {"is": note_link(info["is"]), "denetciler": info["denetciler"], "hakem": info["hakem"],
                "baslangic": info["zaman"]}

    # --- living office (step 1: data) ---

    def _join_sessions(self, sessions, tasks, now):
        """Each session gets its unfinished job (task.session == session name; tasks are newest first, so the latest
        wins) — model, tier, note, job_status (the raw session status stays under status), step_kind — and its open
        subagents (alt_ajan.py)."""
        final = set(jobs.FINAL_STATUSES)
        open_jobs, latest = {}, {}
        for t in tasks:
            if t["session"]:
                latest.setdefault(t["session"], t)
                if t["status"] not in final:
                    open_jobs.setdefault(t["session"], t)
        for s in sessions:
            t = open_jobs.get(s["name"]) or {}
            # the session's newest job is over (bitti, tikandi, iptal…): none of its subagents is open any more
            over = s["name"] in latest and not t
            s.update({"job_status": t.get("status", ""), "model": t.get("model", ""), "tier": t.get("tier", ""),
                      "uzmanlik": t.get("uzmanlik", ""),
                      "note": t.get("note", ""), "step_kind": t.get("step_kind", ""),
                      "alt_ajanlar": self.subagents.list(transcript.project_folder(self.projects_dir, s["_cwd"]),
                                                         s["_sid"], now, only_finished=over)})

    def _models(self, sessions, tasks, ceo, now, tz, denetim=None):
        """/api/state.modeller (model_durum.py): the tails of office transcripts only — the listed office sessions,
        the CEO, and the known office sessions (durum/sessions.json) written in the last MODEL_SCAN_AGE. denetim
        (_denetim): while the hakem runs, its model counts as working and that review's Codex no longer does."""
        job_model = {}
        for t in tasks:
            if t["session"]:
                job_model.setdefault(t["session"], t["model"])
        files = {}
        for s in sessions:
            files[s["_sid"]] = (s["_cwd"], s["model"] or job_model.get(s["name"], ""))
        ceo_sid = ceo.get("session_id")
        if transcript.valid_session_id(ceo_sid):
            files.setdefault(ceo_sid, (self.root, ""))
        oldest = now.timestamp() - MODEL_SCAN_AGE.total_seconds()
        for sid, k in self._known.items():
            if sid in files or not isinstance(k.get("cwd"), str) or is_forbidden(k["cwd"]):
                continue
            files[sid] = (k["cwd"], job_model.get(k.get("name"), ""))
        scans, ceo_model = [], ""
        for sid, (cwd, fallback) in files.items():
            path = transcript.transcript_path(self.projects_dir, cwd, sid)
            if transcript.forbidden_folder(os.path.dirname(path)):
                continue  # the "-" encoding of an allowed cwd may still name a forbidden project's folder
            try:
                if os.stat(path).st_mtime < oldest:
                    continue
            except OSError:
                continue
            scan = self.model_scans.scan(path)
            if scan is not None:
                scans.append((scan, fallback))
                if sid == ceo_sid:
                    ceo_model = scan["model"]
        calisan = {}
        for s in sessions:
            fam = model_durum.family(s["model"])
            if fam and s["job_status"]:
                calisan[fam] = calisan.get(fam, 0) + 1
        if ceo.get("state") == "busy" and ceo_model:
            calisan[ceo_model] = calisan.get(ceo_model, 0) + 1
        # a review whose panel is done (the hakem weighs the findings) no longer keeps Codex at work
        done = denetim["is"] if denetim and denetim["is"] and "codex" not in denetim["denetciler"] else ""
        codex_running = sum(1 for t in tasks if t["status"] == "incelemede" and t["inceleme_yurutucu"] == "codex"
                            and t["note"] != done)
        if codex_running:
            calisan["codex"] = calisan.get("codex", 0) + codex_running
        hakem = model_durum.family(denetim["hakem"]) if denetim else ""
        if hakem in model_durum.CLAUDE:
            calisan[hakem] = calisan.get(hakem, 0) + 1
        sec_running = denetci.SECURITY in (denetim or {}).get("denetciler", [])
        sec_model = denetci.security_settings(self.cfg)["model"]
        if sec_running and model_durum.family(sec_model) in model_durum.CLAUDE:  # the security call is a Claude call
            calisan[model_durum.family(sec_model)] = calisan.get(model_durum.family(sec_model), 0) + 1
        # the review panel's free reviewers (bin/denetci.py): a row each while some project may use them
        names = denetci.free_names(self.cfg)
        free = []
        if names:
            events, busy = self.denetci_scans.events(self.durum_dir), (denetim or {}).get("denetciler", [])
            free = [(n, events.get(n, []), 1 if n in busy else 0) for n in names]
        rows = model_durum.build(scans, self.codex_scans.events(self.durum_dir), calisan, now, tz, denetciler=free)
        # the security reviewer (bin/denetci.py SECURITY, a `claude -p` call): a row while ofis.json configures it or it
        # runs; working while the panel marker names it, else its Claude model's own state (never a guess)
        running, model = sec_running, sec_model
        if running or isinstance(self.cfg.get("guvenlik_denetcisi"), dict):
            own = next((r for r in rows if r["model"] == model_durum.family(model)), None) or {}
            rows.append({"model": denetci.SECURITY, "unvan": "Güvenlik denetçisi", "ajan_modeli": model,
                         "calisan": 1 if running else 0,
                         # idle: its model's state, but another Sonnet session at work never makes it "calisiyor"
                         "durum": "calisiyor" if running else
                         ("hazir" if own.get("durum") == "calisiyor" else own.get("durum", "bilinmiyor")),
                         "donus": None if running else own.get("donus"),
                         "son_hata": None if running else own.get("son_hata")})
        return rows
