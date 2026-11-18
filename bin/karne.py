"""The office scorecard (karne): one row per finished job, written by the server — deterministic, no model call.

    OFIS/Karne/Kayitlar-YYYY-MM.md   one markdown table per month (month of the job's bitis); a row per job
    OFIS/Karne/Ozet.md               GENERATED from every Kayitlar file after each new row; never edited by hand
    OFIS/Karne/Degisiklikler.md      tier-mapping changes; created with its header when missing; a row is appended by
                                     bin/model_secimi.py after the owner approved a pilot's mapping change (phase 8)

A job is due when its note has `karne: bekliyor` (jobs.update sets it in the same write that first gives the note a
final status, whoever wrote it: post office, kontrol worker, ofis.py bitir/iptal, a failed launch). process_pending()
first records the final harcanan_usd / cagri on the note (and, through on_final, on the server record), then writes
the row and then sets `karne: yazildi`. The key of a row is the job's file name: a job that already has a row in any
Kayitlar file gets that row REPLACED in place (`ofis.py devam` empties `karne`, so a job that went on after a stop
is written again at its next final status, with the number of devam rounds in the Devam column); a crash between
the steps therefore never writes a second row. Notes finished before the scorecard existed have no `karne` field and
are never counted. Costs are written with four decimals. A month file from before the Devam column gets the column
(0 for its rows) the next time it is written.
Phase 4: the last two columns name the workflow (`Akış`, the workflow id) and the step kind (`Adım`) of a workflow
step's job (empty for a plain job). A month file from before them gets the columns (empty for its rows) the next time
it is written; older rows are read with empty cells until then.
Only the server's post office thread writes here (under the job lock).
Self-test jobs (owner decision 2026-11-12, B3 audit): the last column `Deneme` is "evet" for a job the office ran to test itself
(the server record's `deneme`, never the note's). Such rows stay in the month files but counted() leaves them out of
quality(), Ozet.md (which lists them by name), the model selection (bin/model_secimi.py) and the group-report totals
(bin/rapor.py). A month file from before the column gets it (empty cells) the next time it is written; mark_trial()
sets the cell of one existing row (`ofis.py deneme-isaretle`, the one-time marking of the jobs before the flag).
Specialisation (plan "Sonraki iş (9)" step 2, bin/uzmanlik.py): the last column `Uzmanlık` is the job's
specialisation from the server record (never the note; "" for a job without one). A month file from before it gets the
column (empty cells) the next time it is written. quality() (`uzmanliklar`) and Ozet.md ("Uzmanlığa göre") also report
the numbers per specialisation; the project × tier × model tables and the model selection's key stay as they were.
Phase 7: quality() gives the Ozet numbers as data for the page's Kalite view (GET /api/kalite); it shares _measure()
with summary_text(), so the page and Ozet.md never disagree. Read-only.
"""
import os
import sys
import re
from datetime import datetime

import budget
import jobs
import sahip

FOLDER = "Karne"
SUMMARY = "Ozet.md"
CHANGES = "Degisiklikler.md"
RECORDS = re.compile(r"Kayitlar-(\d{4})-(\d{2})\.md")
COLUMNS = ("Tarih", "Proje", "İş", "Katman", "Model", "Effort", "Kontrol ilk turda", "Kontrol denemesi", "Yükseltme",
           "Çağrı", "Maliyet ($)", "Doğrulanmış maliyet ($)", "Süre (dk)", "Sonuç", "Devam", "Akış", "Adım", "Token",
           "Deneme", "Uzmanlık")
OLD_COLUMNS = COLUMNS[:-6]  # before the Devam column (phase 2 review)
# before Devam; before Akış/Adım (phase 4); before Token; before Deneme; before Uzmanlık
OLD_LAYOUTS = (OLD_COLUMNS, COLUMNS[:-5], COLUMNS[:-3], COLUMNS[:-2], COLUMNS[:-1])
# the values an older row gets for the columns it lacks (Devam, Akış, Adım, Token, Deneme, Uzmanlık: "" = not
# recorded, never 0)
DEFAULT_CELLS = ("0", "", "", "", "", "")
TRIAL_INDEX = COLUMNS.index("Deneme")
UZMANLIK_COLUMNS = ("Uzmanlık", "İş sayısı", "Bitti oranı", "Kontrol ilk turda geçme", "Toplam API karşılığı ($)",
                    "Yeniden iş oranı", "Doğrulanmış iş başına API karşılığı ($)", "Toplam token")
UZMANLIK_TITLES = {"backend": "Backend", "ui": "UI", "mobil": "Mobil", "test": "Tester", "analiz": "Analist",
                   "guvenlik": "Güvenlik", "genel": "Genel"}
UZMANLIK_SIRA = tuple(UZMANLIK_TITLES)
TRIAL = "evet"  # the Deneme cell of a self-test row
SUMMARY_COLUMNS = ("Proje", "Katman", "Model", "İş sayısı", "Bitti oranı", "Kontrol ilk turda geçme",
                   "Ort. API karşılığı ($)", "Ort. doğrulanmış API karşılığı ($)", "Toplam API karşılığı ($)",
                   "Yeniden iş oranı", "Doğrulanmış iş başına API karşılığı ($)", "Ort. süre (dk)", "Toplam token",
                   "Ort. token", "Doğrulanmış iş başına token")
# Phase 5: the correction log (ADR §7 "aynı düzeltme iki kez"), one file per project
CORRECTIONS = "Duzeltmeler-{}.md"
CORRECTION_KINDS = ("kontrol-basarisiz", "inceleme-duzelt", "yukseltme", "devam", "onay-degil")
REWORK_KINDS = CORRECTION_KINDS[:4]  # an approval answer that was not plain is a correction, not rework
CORRECTION_COLUMNS = ("Tarih", "İş", "Tür", "Alıntı", "Kimlik")
EXCERPT_MAX = 300
PROJECT = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
KEY = re.compile(r"[\w.-]{1,160}")


# Office vocabulary (the owner, 2026-11-11): the vault notes call a model by its office role. The column key stays "Model"
# (the code's name); the header shows "Çalışan" and the cell "Kıdemli (opus)". Files written before keep parsing: rows
# are read by their cell count, and a "Kıdemli (opus)" cell is read back as "opus" (model_of).
ROLES = {"haiku": "Stajyer", "sonnet": "Uzman", "opus": "Kıdemli", "fable": "Genel Müdür", "codex": "Dış denetçi"}
HEADER_SHOWN = {"Model": "Çalışan"}
WORKER_CELL = re.compile(r"^[^()|]+ \(([A-Za-z0-9][\w.:/-]{0,80})\)$")


def worker(model):
    """"opus" -> "Kıdemli (opus)" (a family contained in the id names the role); an unknown id stays as it is."""
    model = str(model or "")
    low = model.lower()
    fam = next((f for f in ROLES if f in low), "")
    return f"{ROLES[fam]} ({model})" if fam and not WORKER_CELL.match(model) else model


def model_of(cell):
    """The model id of a worker cell ("Kıdemli (opus)" -> "opus"; an older plain "opus" as it is)."""
    m = WORKER_CELL.match(str(cell or "").strip())
    return m.group(1) if m else str(cell or "").strip()


def _table_head(columns, shown=True):
    names = [HEADER_SHOWN.get(c, c) if shown else c for c in columns]
    return "| " + " | ".join(names) + " |\n|" + "---|" * len(names) + "\n"


def _cell(value):
    text = " ".join(str("" if value is None else value).split())
    return text.replace("|", "/")


def _int(value):
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _time(value):
    """A note time as a naive local datetime (an offset-bearing stamp is converted), or None."""
    try:
        t = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def first_round(meta):
    """evet / hayır / yok: did the server-run Kontrol pass on its first run?"""
    tries, outcome = _int(meta.get("kontrol_deneme")), meta.get("kontrol_sonuc")
    if tries == 0:
        return "yok"
    return "evet" if tries == 1 and outcome == "gecti" else "hayır"


# Phase 8 review: the fields a row takes from the server record when the record has them (the note only for a job
# from before); a project session can edit its own note, never the record.
TRUSTED_ROW_FIELDS = ("katman", "model", "effort", "kontrol_deneme", "kontrol_sonuc", "yukseltme_kaynagi")


def _uzmanlik(record):
    """The specialisation of a row: the server record's only (a session can edit its note)."""
    value = record.get("uzmanlik") if isinstance(record, dict) else ""
    return value if isinstance(value, str) and re.fullmatch(r"[a-z]{2,20}", value) else ""


def trusted_meta(meta, record):
    """The note's meta with the record's value for every TRUSTED_ROW_FIELDS key the record has."""
    if not isinstance(record, dict):
        return meta
    return {**meta, **{k: record[k] for k in TRUSTED_ROW_FIELDS if k in record}}


def row(job, usage, now, record=None):
    meta = trusted_meta(job.meta, record)
    finished, started = _time(meta.get("bitis")), _time(meta.get("baslangic"))
    day = (finished or now).strftime("%Y-%m-%d")
    if usage is not None:
        cost, calls = f"{usage.cost:.4f}", str(usage.calls)
        tokens = str(int(usage.tokens or 0))
    else:
        known = budget.token_count(meta.get("harcanan_token"))
        tokens = "" if known is None else str(known)
        cost = meta.get("harcanan_usd") or ""
        calls = meta.get("cagri") or ""
        try:
            cost = f"{float(cost):.4f}" if cost else ""
        except ValueError:
            cost = ""
    verified = cost if meta.get("durum") == "bitti" and meta.get("kontrol_sonuc") == "gecti" else ""
    minutes = ""
    if finished and started and finished >= started:
        minutes = str(round((finished - started).total_seconds() / 60))
    values = (day, meta.get("proje", ""), f"[[{jobs.stem(job.name)}]]", meta.get("katman", ""), worker(meta.get("model", "")),
              meta.get("effort", ""), first_round(meta), _int(meta.get("kontrol_deneme")),
              "evet" if meta.get("yukseltme_kaynagi") else "hayır", calls, cost,
              verified, minutes, meta.get("durum", ""), _int(meta.get("devam_sayisi")), meta.get("akis", ""),
              meta.get("adim_turu", ""), tokens, TRIAL if is_trial(record) else "", _uzmanlik(record))
    return "| " + " | ".join(_cell(v) for v in values) + " |"


def _folder(vault):
    return os.path.join(vault, FOLDER)


def _record_files(vault):
    try:
        names = sorted(n for n in os.listdir(_folder(vault)) if RECORDS.fullmatch(n))
    except OSError:
        return []
    return [os.path.join(_folder(vault), n) for n in names
            if os.path.isfile(os.path.join(_folder(vault), n)) and not os.path.islink(os.path.join(_folder(vault), n))]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def has_row(vault, job_name):
    link = f"| [[{jobs.stem(job_name)}]] |"
    return any(link in _read(path) for path in _record_files(vault))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    jobs._write_atomic(path, text)


def _pad(cells):
    """An older row's cells completed with the defaults of the columns it lacks."""
    missing = len(COLUMNS) - len(cells)
    return cells + list(DEFAULT_CELLS[len(DEFAULT_CELLS) - missing:]) if 0 < missing <= len(DEFAULT_CELLS) else cells


def _upgrade(text):
    """A month file from an older layout (before Devam, before Akış/Adım): its header gets the new columns and its
    rows the default cells."""
    # every older layout, with the old "Model" header or the new "Çalışan" one; the current columns under "Model"
    # only get the new header
    for old, shown in [(c, False) for c in (COLUMNS,) + OLD_LAYOUTS] + [(c, True) for c in OLD_LAYOUTS]:
        old_head = _table_head(old, shown)
        if old_head not in text:
            continue
        text = text.replace(old_head, _table_head(COLUMNS))
        lines = []
        for line in text.split("\n"):
            cells = line.strip().strip("|").split("|")
            if re.match(r"\| \d{4}-\d{2}-\d{2} \|", line) and len(cells) == len(old):
                line = "| " + " | ".join(c.strip() for c in _pad([c.strip() for c in cells])) + " |"
            lines.append(line)
        text = "\n".join(lines)
    return text


def write_row(vault, job, usage, now, record=None):
    """Writes the job's row: replaces its existing row in place (any month file), else appends it to its month's
    file (created with its header). Returns "replaced" or "added"."""
    line = row(job, usage, now, record)
    link = f"| [[{jobs.stem(job.name)}]] |"
    for path in _record_files(vault):
        text = _read(path)
        if link not in text:
            continue
        lines = _upgrade(text).split("\n")
        lines = [line if link in old and re.match(r"\| \d{4}-\d{2}-\d{2} \|", old) else old for old in lines]
        _write(path, "\n".join(lines))
        return "replaced"
    month = line[2:9]
    path = os.path.join(_folder(vault), f"Kayitlar-{month}.md")
    if os.path.isfile(path):
        text = _upgrade(_read(path))
        text = text if text.endswith("\n") else text + "\n"
    else:
        text = (f"---\ntags: [ofis, karne]\nay: {month}\n---\n\n# Karne kayıtları — {month}\n\n"
                "Bu dosyayı Ofis sunucusu yazar: her biten iş bir satır. Elle düzenleme; özet için "
                "[[Ozet]] notuna bak.\n\n" + _table_head(COLUMNS))
    _write(path, text + line + "\n")
    return "added"


def is_trial(record):
    """A self-test job: only the server record says so (`deneme: evet`), never the note — a record without the key (or
    no record) is a real job, so a session cannot hide its own failure by writing `deneme: evet` into its note."""
    return isinstance(record, dict) and record.get("deneme") == TRIAL


def mark_trial(vault, job_name):
    """Sets the Deneme cell of the job's existing row to evet (its file upgraded to the current layout first).
    Returns "isaretlendi", "zaten" (already evet) or "satir-yok" (the job has no row). Call it under the job lock."""
    link = f"| [[{jobs.stem(job_name)}]] |"
    for path in _record_files(vault):
        text = _read(path)
        if link not in text:
            continue
        lines = _upgrade(text).split("\n")
        for i, line in enumerate(lines):
            if link not in line or not re.match(r"\| \d{4}-\d{2}-\d{2} \|", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != len(COLUMNS):
                continue
            if cells[TRIAL_INDEX] == TRIAL:
                return "zaten"
            cells[TRIAL_INDEX] = TRIAL
            lines[i] = "| " + " | ".join(cells) + " |"
            _write(path, "\n".join(lines))
            return "isaretlendi"
    return "satir-yok"


def counted(rows):
    """The rows that count in the numbers: every row but the self-test ones (Deneme = evet)."""
    return [r for r in rows if r.get("Deneme") != TRIAL]


def trials(rows):
    """The job stems of the self-test rows, in row order."""
    out = []
    for r in rows:
        link = re.fullmatch(r"\[\[(.+)\]\]", r.get("İş", ""))
        if r.get("Deneme") == TRIAL and link:
            out.append(link.group(1))
    return out


def _rows(vault):
    out = []
    for path in _record_files(vault):
        for line in _read(path).splitlines():
            if not line.startswith("| ") or not re.match(r"\| \d{4}-\d{2}-\d{2} \|", line):
                continue
            cells = _pad([c.strip() for c in line.strip().strip("|").split("|")])
            if len(cells) == len(COLUMNS):
                row = dict(zip(COLUMNS, cells))
                row["Model"] = model_of(row["Model"])  # "Kıdemli (opus)" or an older "opus"
                out.append(row)
    return out


def _money(values):
    numbers = []
    for v in values:
        try:
            numbers.append(float(v))
        except ValueError:
            continue
    return numbers


def _rate(hits, total):
    return f"%{round(100 * hits / total)} ({hits}/{total})" if total else "—"


def _four(value):
    return "—" if value is None else f"{value:.4f}"


def excerpt(text, limit=EXCERPT_MAX):
    """Project / review / owner text as one safe table cell: whitespace (newlines too) collapsed, cut to `limit`
    characters, `|` escaped, no HTML and no wikilinks; quoted with “ ” (it is data)."""
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    text = text.replace("\\", "/").replace("|", "\\|").replace("<", "‹").replace(">", "›")
    text = text.replace("[", "［").replace("]", "］").replace("`", "'")  # never a wikilink, however nested
    return f"“{text}”" if text else ""


def _corrections_path(vault, project):
    if not isinstance(project, str) or not PROJECT.fullmatch(project):
        raise ValueError(f"invalid project name: {project!r}")
    return os.path.join(_folder(vault), CORRECTIONS.format(project))


def record_correction(vault, project, job_name, kind, text, key, now):
    """Appends one correction event to OFIS/Karne/Duzeltmeler-<project>.md (created with its header): date, job
    link, kind, a short quoted excerpt and the event key. A key already in the file is not written again (a retry
    after a crash). Returns True when a row was added. Under the job lock (writers: the server's threads and
    `ofis.py devam` / `cevapla`)."""
    if kind not in CORRECTION_KINDS:
        raise ValueError(f"unknown correction kind: {kind!r}")
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError(f"invalid correction key: {key!r}")
    path = _corrections_path(vault, project)
    stem = jobs.stem(jobs.check_name(job_name))
    with jobs.locked(vault):
        if os.path.islink(path) or (os.path.lexists(path) and not os.path.isfile(path)):
            raise ValueError(f"{path} is not a plain file")
        if os.path.isfile(path):
            current = _read(path)
            if f"| {key} |" in current:
                return False
            current = current if current.endswith("\n") else current + "\n"
        else:
            current = (f"---\ntags: [ofis, karne]\nproje: {project}\n---\n\n# Düzeltmeler — {project}\n\n"
                       "Bu dosyayı Ofis sunucusu yazar: bir işte gereken her düzeltme bir satır (kontrol geçmedi, "
                       "inceleme düzeltme istedi, iş bir üst katmana taşındı, iş devam ettirildi, onay kartına düz "
                       "onay dışında bir cevap verildi). Alıntılar veri olarak okunur. Elle düzenleme; aynı düzeltme "
                       f"iki kez geçiyorsa CEO projenin CLAUDE.md'si için bir satır önerir, onay {sahip.de()}.\n\n"
                       + _table_head(CORRECTION_COLUMNS))
        values = (f"{now:%Y-%m-%d %H:%M}", f"[[{stem}]]", kind, excerpt(text), key)
        _write(path, current + "| " + " | ".join(values) + " |\n")
    return True


def _split_row(line):
    """The cells of a table row; an escaped pipe (\\|) stays inside its cell."""
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def corrections(vault, project=None):
    """The correction events, oldest first: [{tarih, is (stem), tur, alinti, kimlik, proje}] of one project (or of
    every project)."""
    if project is None:
        try:
            names = sorted(n for n in os.listdir(_folder(vault))
                           if n.startswith("Duzeltmeler-") and n.endswith(".md"))
        except OSError:
            return []
        projects = [n[len("Duzeltmeler-"):-3] for n in names if PROJECT.fullmatch(n[len("Duzeltmeler-"):-3])]
    else:
        projects = [project]
    out = []
    for name in projects:
        path = _corrections_path(vault, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        for line in _read(path).splitlines():
            if not re.match(r"\| \d{4}-\d{2}-\d{2}", line):
                continue
            cells = _split_row(line)
            if len(cells) != len(CORRECTION_COLUMNS):
                continue
            link = re.fullmatch(r"\[\[(.+)\]\]", cells[1])
            if not link or cells[2] not in CORRECTION_KINDS:
                continue
            out.append({"tarih": cells[0], "is": link.group(1), "tur": cells[2], "alinti": cells[3],
                        "kimlik": cells[4], "proje": name})
    return out


def _rework(row, events):
    """Rework of one scorecard row: the job's correction events (kontrol failures, review DÜZELT rounds,
    escalations, devam rounds), or — for a job from before the log — what its row shows."""
    link = re.fullmatch(r"\[\[(.+)\]\]", row["İş"])
    logged = events.get(link.group(1), 0) if link else 0
    shown = (1 if row["Kontrol ilk turda"] == "hayır" else 0) + (1 if row["Yükseltme"] == "evet" else 0) + \
        _int(row["Devam"])
    return max(logged, shown)


def _rework_events(vault):
    """{job stem: number of rework corrections} from every project's correction log."""
    events = {}
    for e in corrections(vault):
        if e["tur"] in REWORK_KINDS:
            events[e["is"]] = events.get(e["is"], 0) + 1
    return events


def _measure(items, events):
    """The numbers of a set of scorecard rows as data: Ozet.md (summary_text) and the page's Kalite panel (quality)
    share them. Averages are None when nothing is known — a missing value is never 0."""
    first = [r["Kontrol ilk turda"] for r in items if r["Kontrol ilk turda"] in ("evet", "hayır")]
    costs = _money(r["Maliyet ($)"] for r in items)
    verified = _money(r["Doğrulanmış maliyet ($)"] for r in items)
    minutes = [_int(r["Süre (dk)"]) for r in items if r["Süre (dk)"].strip().isascii() and r["Süre (dk)"].strip().isdigit()]
    counted = [r for r in items if r.get("Token", "").strip().isascii() and r.get("Token", "").strip().isdigit()]
    tokens = [int(r["Token"]) for r in counted]
    verified_counted = len(_money(r["Doğrulanmış maliyet ($)"] for r in counted))
    return {"is_sayisi": len(items), "bitti": sum(1 for r in items if r["Sonuç"] == "bitti"),
            "ilk_tur_gecen": first.count("evet"), "ilk_tur_olculen": len(first),
            "yeniden_is": sum(1 for r in items if _rework(r, events) > 0), "dogrulanan": len(verified),
            "toplam_usd": sum(costs), "ort_usd": sum(costs) / len(costs) if costs else None,
            "ort_dogrulanmis_usd": sum(verified) / len(verified) if verified else None,
            "dogrulanmis_is_basina_usd": sum(costs) / len(verified) if verified else None,
            "ort_sure_dk": round(sum(minutes) / len(minutes)) if minutes else None,
            # rows from before the Token column have none: the sum of the known ones, None when none is known (never
            # 0); token_bilinmeyen = the rows without a count. The token twins of the dollar metrics: the average over
            # the known counts, and verified tokens per job = all known tokens / the jobs bitti with a passed Kontrol
            # among the rows that have a count (the owner, 2026-11-12: a row without a count must not pull it down)
            "toplam_token": sum(tokens) if tokens else None, "token_bilinen": len(tokens),
            "token_bilinmeyen": len(items) - len(tokens),
            "ort_token": round(sum(tokens) / len(tokens)) if tokens else None,
            "dogrulanmis_is_basina_token": round(sum(tokens) / verified_counted) if tokens and verified_counted else None}


def _rounded(measure):
    """Amounts for the page rounded to 6 places (the rows carry 4 decimals: this only drops float noise, a small
    amount such as 0.0111 keeps its digits)."""
    return {k: round(v, 6) if isinstance(v, float) else v for k, v in measure.items()}


def _grouped(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    return sorted(groups.items())


def _by_uzmanlik(rows):
    """[(uzmanlik, rows)] in the display order (known ones first, then others, rows without one — "" — last)."""
    groups = {}
    for r in rows:
        groups.setdefault(r.get("Uzmanlık", ""), []).append(r)
    order = {u: i for i, u in enumerate(UZMANLIK_SIRA)}
    return sorted(groups.items(), key=lambda x: (x[0] == "", order.get(x[0], 99), x[0]))


def quality(vault):
    """The page's Kalite panel (GET /api/kalite): the Ozet numbers per project × tier × model (`satirlar`), per model
    (`modeller`) and over every row (`toplam`, None without rows), computed from the Kayitlar rows and the correction
    logs — the same source and code as Ozet.md, never parsed back from it. Self-test rows (Deneme = evet) are left
    out; deneme_sayisi / deneme_isler name them."""
    every, events = _rows(vault), _rework_events(vault)
    rows = counted(every)
    lines = [{"proje": p, "katman": t, "model": m, **_rounded(_measure(items, events))}
             for (p, t, m), items in _grouped(rows, lambda r: (r["Proje"], r["Katman"], r["Model"]))]
    models = [{"model": m, **_rounded(_measure(items, events))} for m, items in _grouped(rows, lambda r: r["Model"])]
    roles = [{"uzmanlik": u, **_rounded(_measure(items, events))} for u, items in _by_uzmanlik(rows)]
    return {"satirlar": lines, "modeller": models, "uzmanliklar": roles,
            "toplam": _rounded(_measure(rows, events)) if rows else None,
            "is_sayisi": len(rows), "deneme_sayisi": len(every) - len(rows), "deneme_isler": trials(every)}


def summary_text(vault):
    every = _rows(vault)
    rows = counted(every)
    events = _rework_events(vault)
    left_out = trials(every)
    groups = {}
    for r in rows:
        groups.setdefault((r["Proje"], r["Katman"], r["Model"]), []).append(r)
    sources = " · ".join(f"[[{os.path.basename(p)[:-3]}]]" for p in _record_files(vault)) or "(henüz kayıt yok)"
    lines = ["---", "tags: [ofis, karne]", "---", "", "# Karne — özet", "",
             "> Bu dosya Ofis sunucusu tarafından `Kayitlar-*.md` dosyalarından üretilir; elle düzenlemeyin "
             "(her yeni kayıtta baştan yazılır).", "",
             f"Kaynak: {sources} · toplam {len(rows)} iş.", ""]
    if left_out:
        lines += [f"Deneme işleri (sayılmadı): {len(left_out)} — " + ", ".join(f"[[{s}]]" for s in left_out) +
                  ". Ofisin kendini sınadığı işler; kayıtlarda Deneme sütununda «evet» yazar, buradaki sayılara "
                  "katılmaz.", ""]
    lines += [
             "Kontrol ilk turda geçme: sunucunun çalıştırdığı kontrolün ilk denemede geçtiği işlerin, kontrolü "
             "çalışan işlere oranı. Doğrulanmış maliyet: kontrolü geçerek biten işlerin kullanımı (API fiyatıyla "
             "karşılığı, USD; abonelikte para ödenmez). Yeniden iş oranı: en az bir düzeltme gereken işlerin oranı (kontrol geçmedi, inceleme "
             "düzeltme istedi, bir üst katmana taşındı ya da devam ettirildi; Duzeltmeler-<proje> notlarından). "
             "**Doğrulanmış iş başına kullanım** (ana ölçüt; dolar sütunları API karşılığıdır): o satırdaki işlerin bütün kullanımı / kontrolü geçerek "
             "biten iş sayısı. Token sütunları aynı ölçütlerin token karşılığıdır (yalnız token sayısı kayıtlı "
             "işler; kayıtsız iş sayısı Toplam token hücresinde yazar, bilinmeyen değer — olarak gösterilir).", "",
             _table_head(SUMMARY_COLUMNS).rstrip("\n")]
    for (project, tier, model), items in sorted(groups.items()):
        m = _measure(items, events)
        values = (project, tier, worker(model), m["is_sayisi"], _rate(m["bitti"], m["is_sayisi"]),
                  _rate(m["ilk_tur_gecen"], m["ilk_tur_olculen"]), _four(m["ort_usd"]), _four(m["ort_dogrulanmis_usd"]),
                  f"{m['toplam_usd']:.4f}", _rate(m["yeniden_is"], m["is_sayisi"]),
                  _four(m["dogrulanmis_is_basina_usd"]), "—" if m["ort_sure_dk"] is None else str(m["ort_sure_dk"]),
                  _token_total(m), "—" if m["ort_token"] is None else str(m["ort_token"]),
                  "—" if m["dogrulanmis_is_basina_token"] is None else str(m["dogrulanmis_is_basina_token"]))
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    lines += ["", "## Uzmanlığa göre", "",
              "Aynı ölçütler işin uzmanlığına göre (iş eklenirken yönlendirmenin seçtiği uzmanlık; kayıtlı değil = "
              "uzmanlıktan önceki işler).", "", _table_head(UZMANLIK_COLUMNS).rstrip("\n")]
    for key, items in _by_uzmanlik(rows):
        m = _measure(items, events)
        values = (UZMANLIK_TITLES.get(key, key) if key else "— (kayıtlı değil)", m["is_sayisi"],
                  _rate(m["bitti"], m["is_sayisi"]), _rate(m["ilk_tur_gecen"], m["ilk_tur_olculen"]),
                  f"{m['toplam_usd']:.4f}", _rate(m["yeniden_is"], m["is_sayisi"]),
                  _four(m["dogrulanmis_is_basina_usd"]), _token_total(m))
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    return "\n".join(lines) + "\n"


def _token_total(m):
    """Ozet's Toplam token cell: the known sum, with how many rows have no count; "—" when none is known (never 0)."""
    if m["toplam_token"] is None:
        return "—"
    missing = m.get("token_bilinmeyen") or 0
    return str(m["toplam_token"]) + (f" ({missing} işte kayıtlı değil)" if missing else "")


def regenerate_summary(vault):
    _write(os.path.join(_folder(vault), SUMMARY), summary_text(vault))


def ensure_changes_file(vault):
    path = os.path.join(_folder(vault), CHANGES)
    if os.path.lexists(path):
        return
    _write(path, "---\ntags: [ofis, karne]\n---\n\n# Karne — katman değişiklikleri\n\n"
                 "Katman eşlemesindeki (`ofis.json` → `tiers`, projeye özel `projects.<proje>.tiers`) her değişiklik "
                 "buraya bir satır olarak eklenir: tarih, eski → yeni, gerekçe (pilotun ve karnenin kanıtı) ve karar "
                 f"notunun linki. Değişikliği {sahip.ad()} onaylar; onayından sonra satırı Ofis sunucusu ekler (eski satırlar "
                 "hiç değiştirilmez).\n\n" + _table_head(("Tarih", "Değişiklik (eski → yeni)", "Gerekçe",
                                                                  "Karar")))


_FAILED = set()  # job names whose row failed (logged once)


def process_pending(vault, usage_of, now=datetime.now, on_final=None, record_of=None):
    """Writes the row of every finished job marked `karne: bekliyor`. usage_of(job) -> budget.Usage or None;
    on_final(job name, {harcanan_usd, cagri}) records the final spending elsewhere too (the server record);
    record_of(job) -> the server record (or None): its tier, model and Kontrol fields win over the note's.
    Returns the names written (or completed after an interrupted run)."""
    done = []
    with jobs.locked(vault):
        for job in sorted(jobs.list_jobs(vault, (jobs.DONE,)), key=lambda j: j.name):
            if job.meta.get("karne") != "bekliyor" or job.meta.get("durum") not in jobs.FINAL_STATUSES:
                continue
            try:
                usage = usage_of(job)
                final = budget.record_fields(job.meta, usage, force=True) if usage is not None else None
                if final:
                    # the final spending first (note, then the record): the row below and the note always agree
                    job = jobs.update(vault, job.name, fields=final)
                    if on_final:
                        on_final(job.name, final)
                write_row(vault, job, usage, now(), record=record_of(job) if record_of else None)
                jobs.update(vault, job.name, fields={"karne": "yazildi"})  # a crash before this leaves the job due
            except Exception as e:  # one bad note never blocks the others; it stays due and is logged once
                if job.name not in _FAILED:
                    _FAILED.add(job.name)
                    print(f"ofis: karne satırı yazılamadı ({job.name}): {type(e).__name__}: {e}", file=sys.stderr)
                continue
            done.append(job.name)
        if done:
            ensure_changes_file(vault)
            regenerate_summary(vault)
    return done
