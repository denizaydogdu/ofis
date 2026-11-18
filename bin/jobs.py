"""Job notes of the office: OFIS/Isler/{Siradakiler,Devam-Edenler,Bitenler}/<name>.md.

The folder follows the status (durum): a status change rewrites the note in place (temp file + os.replace) and then
moves it to its status folder with os.replace, keeping the file name and never overwriting another file. A crash
between the two steps leaves a misplaced note that settle() (called by every update) moves to the right folder.
Notes link to each other by bare file name ([[2026-11-10-183820-ornek-uygulama]]), so moves never break links.

Writers (bin/ofis.py, the server's post office, bin/launch.py) serialise every read-modify-write with an flock on
durum/jobs.lock under the repo root: one fixed file for the server and the CEO, whose TMPDIR is sandboxed (nothing
extra is written into the vault). The lock is re-entrant within a thread, so a caller can hold it around a whole
scan + update. Readers take no lock.
Names are plain file names: no separators, no dotfiles, no symlinks out of the job folders.
"""
import contextlib
import fcntl
import hashlib
import os
import re
import tempfile
import threading
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_ENV = "OFIS_JOBS_LOCK"  # overrides the lock file (tests: never the real durum/)
ISLER = "Isler"
QUEUED, ACTIVE, DONE = "Siradakiler", "Devam-Edenler", "Bitenler"
FOLDERS = (QUEUED, ACTIVE, DONE)
LEGACY = ""  # the flat OFIS/Isler folder of phase 0; read only, until bin/migrate_v2.py has moved its notes
STATUS_FOLDER = {
    "sirada": QUEUED,
    "baslatiliyor": ACTIVE, "calisiyor": ACTIVE, "karar-bekliyor": ACTIVE, "incelemede": ACTIVE,
    "kontrolde": ACTIVE,  # the project reported bitti; the server is running the job's Kontrol (bin/kontrol.py)
    "bitti": DONE, "tikandi": DONE, "iptal": DONE, "basarisiz": DONE,
}
ACTIVE_STATUSES = tuple(s for s, f in STATUS_FOLDER.items() if f == ACTIVE)
FINAL_STATUSES = tuple(s for s, f in STATUS_FOLDER.items() if f == DONE)
NOTE_NAME = re.compile(r"[^/\\\x00]{1,200}\.md")
FIELD_NAME = re.compile(r"[a-z_]{1,40}")
FIELD_ORDER = ("tags", "proje", "baslik", "durum", "katman", "yurutucu", "model", "effort", "butce_usd", "max_cagri",
               "bagimli", "grup", "kontrol", "kontrol_ozet", "oturum", "kisa_id", "calisma_dizini", "taban_commit",
               "olusturuldu", "baslangic", "bitis")
PLACEHOLDER = "(henüz yok)"
OLD_PLACEHOLDERS = {PLACEHOLDER, "(bitince CEO yazar)", "(oturum başlatılıyor)"}
MAX_MESSAGES = 20  # processed inbox message ids kept in a note (idempotency of the post office)
NEEDS_QUOTES = re.compile(r"(?:^[\s\[\]{}&*#?|<>=!%@`'\",-])|(?::\s)|(?:\s#)|(?:\s$)|(?::$)")

# The job brief: ### subsections of ## Görev, in this order; only Hedef is required. Kontrol is also copied into the
# frontmatter (one line) for phase 2, where the server runs it.
BRIEF = (("hedef", "Hedef"), ("neden", "Neden"), ("kisitlar", "Kısıtlar"), ("kapsam_disi", "Kapsam dışı"),
         ("kontrol", "Kontrol"))
# Written only by the server (an escalated job, bin/kontrol.py): the earlier attempt, after the brief. read_brief()
# returns it only when the note has it.
EXTRA_BRIEF = (("onceki", "Önceki deneme"),)
ALL_BRIEF = BRIEF + EXTRA_BRIEF

Job = namedtuple("Job", "name folder path meta body")


class JobError(Exception):
    """Invalid name, missing note, or a write that would overwrite another file."""


class StatusConflict(JobError):
    """The note's status is not one the caller expected (someone else changed it first)."""


# --- names and paths ---

def check_name(name):
    """The file name of a job note ('.md' added when missing). Raises JobError for unsafe names."""
    if not isinstance(name, str):
        raise JobError("job name must be a string")
    if not name.endswith(".md"):
        name += ".md"
    if not NOTE_NAME.fullmatch(name) or name.startswith(".") or ".." in name or len(name) > 200:
        raise JobError(f"invalid job name: {name!r}")
    return name


def kontrol_digest(command):
    """sha256 (hex) of a Kontrol command as the server stores it (stripped): `kontrol_ozet` on the note and on the
    server's record (bin/records.py); the Kontrol worker refuses a trusted command whose digest differs."""
    return hashlib.sha256(command.strip().encode("utf-8")).hexdigest()


def stem(name):
    return name[:-3] if name.endswith(".md") else name


def folder_for(status):
    try:
        return STATUS_FOLDER[status]
    except KeyError:
        raise JobError(f"unknown job status: {status!r}") from None


def folder_path(vault_ofis, folder):
    return os.path.join(vault_ofis, ISLER, folder) if folder else os.path.join(vault_ofis, ISLER)


def _safe_path(folder_dir, name):
    """Path of a plain note `name` directly inside folder_dir, or None (missing, symlink, not a file, escapes)."""
    path = os.path.join(folder_dir, name)
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder_dir):
        return None
    return path


# --- parsing and rendering ---

def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")  # YAML single quotes: '' is one '
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def parse(text):
    """(frontmatter lines, meta dict, body). Unknown frontmatter lines are kept verbatim."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            lines = text[4:end].splitlines()
            meta = {}
            for line in lines:
                key, sep, value = line.partition(":")
                if sep and key.strip() and not key.startswith(" "):
                    meta[key.strip()] = _unquote(value)
            rest = text[end + 4:]
            body = rest[1:] if rest.startswith("\n") else rest
            return lines, meta, body.lstrip("\n")
    return [], {}, text


def format_value(value):
    value = " ".join(str(value).split())  # always one line
    if value and (NEEDS_QUOTES.search(value) or (value[0] == value[-1] and value[0] in "\"'")):
        if '"' in value:  # YAML single quotes keep a double quote as it is (B3 audit: a Kontrol shown as it runs)
            return "'" + value.replace("'", "''") + "'"
        return '"' + value + '"'
    return value


def _set_line(lines, key, value):
    if not FIELD_NAME.fullmatch(key):
        raise JobError(f"invalid field name: {key!r}")
    new = f"{key}: {format_value(value)}"
    for i, line in enumerate(lines):
        if line.partition(":")[0].strip() == key and not line.startswith(" "):
            lines[i] = new
            return
    lines.append(new)


def render(lines, body):
    return "---\n" + "".join(line + "\n" for line in lines) + "---\n\n" + body.lstrip("\n")


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


def set_section(body, heading, content, before=None):
    """Replaces the content of `## heading` (adds the section, before `## before` when given, if missing)."""
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ") and line[3:].strip() == heading), None)
    block = [f"## {heading}", ""] + (content.strip("\n").splitlines() if content.strip() else []) + [""]
    if start is None:
        at = next((i for i, line in enumerate(lines) if before and line.startswith("## ")
                   and line[3:].strip() == before), len(lines))
        if at == len(lines) and lines and lines[-1].strip():
            lines.append("")
        lines[at:at] = block
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        lines[start:end] = block
    return "\n".join(lines).rstrip("\n") + "\n"


def _append_list_item(body, heading, item, before=None):
    current = section(body, heading)
    if item in current.splitlines():
        return body
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ") and line[3:].strip() == heading), None)
    if start is None:
        return set_section(body, heading, item, before=before)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = max((i for i in range(start + 1, end) if lines[i].strip()), default=start)
    lines.insert(last + 1, item)
    return "\n".join(lines).rstrip("\n") + "\n"



OPTION_LINE = re.compile(r"^- ([A-E])\) (.+)$")


def question_options(body):
    """[{kod, metin}] of a CEO question card's ## Seçenekler (`ofis.py sor`: "- A) …" lines; anything else is
    ignored)."""
    out = []
    for line in section(body, "Seçenekler").splitlines():
        m = OPTION_LINE.match(line.strip())
        if m and m.group(1) not in {o["kod"] for o in out}:
            out.append({"kod": m.group(1), "metin": m.group(2).strip()})
    return out

def render_brief(brief):
    """The ## Görev content for a brief: one ### section per non-empty field, in BRIEF order."""
    brief = brief or {}
    if not isinstance(brief.get("hedef"), str) or not brief["hedef"].strip():
        raise JobError("the brief needs a Hedef")
    unknown = set(brief) - {k for k, _ in ALL_BRIEF}
    if unknown:
        raise JobError(f"unknown brief fields: {', '.join(sorted(unknown))}")
    parts = []
    for key, heading in ALL_BRIEF:
        value = brief.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"### {heading}\n\n{value.strip()}")
    return "\n\n".join(parts)


def read_brief(body):
    """{field: text} of the ### sections under ## Görev (missing ones are ""). A Görev without ### Hedef (older
    notes) is read as one Hedef."""
    gorev = section(body, "Görev")
    found, current = {}, None
    for line in gorev.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            found.setdefault(current, [])
            continue
        if current is not None:
            found[current].append(line)
    if "Hedef" not in found:
        return dict({k: "" for k, _ in BRIEF}, hedef=gorev)
    out = {key: "\n".join(found.get(heading, [])).strip() for key, heading in BRIEF}
    for key, heading in EXTRA_BRIEF:
        if heading in found:
            out[key] = "\n".join(found[heading]).strip()
    return out


def prompt(job):
    """The prompt for the project session: the brief with Turkish ## headings, empty sections omitted; just the
    Hedef text when it is the only section; the whole Görev text for a note without a brief."""
    brief = read_brief(job.body)
    if "### Hedef" not in section(job.body, "Görev").splitlines() or not any(
            value for key, value in brief.items() if key != "hedef"):
        return brief["hedef"].strip()  # a Hedef alone needs no heading
    return "\n\n".join(f"## {heading}\n{brief[key]}" for key, heading in ALL_BRIEF if brief.get(key))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read(512 * 1024)


def _write_atomic(path, text):
    folder, base = os.path.split(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{base}.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# --- lock ---

_held = threading.local()


def lock_path():
    """durum/jobs.lock under the repo root ($OFIS_JOBS_LOCK when set)."""
    return os.environ.get(LOCK_ENV) or os.path.join(ROOT, "durum", "jobs.lock")


def lock_held():
    """True while this thread holds the job lock."""
    return getattr(_held, "depth", 0) > 0


@contextlib.contextmanager
def locked(vault_ofis=None):
    """Serialises job-note writers (flock on lock_path()). Re-entrant within one thread; other threads and
    processes wait. vault_ofis is accepted for the callers' readability; there is one lock per office."""
    if lock_held():
        _held.depth += 1
        try:
            yield
        finally:
            _held.depth -= 1
        return
    path = lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        _held.depth = 1
        try:
            yield
        finally:
            _held.depth = 0
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


# --- lookup ---

def _load_at(folder, path, name):
    lines, meta, body = parse(_read(path))
    return Job(name, folder, path, meta, body)


def find(vault_ofis, name, legacy=False):
    """The Job called `name` in the job folders (Devam-Edenler first), or None. Raises JobError for bad names."""
    name = check_name(name)
    if sum(os.path.lexists(os.path.join(folder_path(vault_ofis, f), name)) for f in FOLDERS) > 1:
        raise JobError(f"{name} exists in more than one job folder; fix it by hand")
    folders = (ACTIVE, QUEUED, DONE) + ((LEGACY,) if legacy else ())
    for folder in folders:
        path = _safe_path(folder_path(vault_ofis, folder), name)
        if path:
            try:
                return _load_at(folder, path, name)
            except (OSError, UnicodeDecodeError):
                continue
    return None


def load(vault_ofis, name, legacy=False):
    job = find(vault_ofis, name, legacy=legacy)
    if job is None:
        raise JobError(f"no such job: {check_name(name)}")
    return job


def list_jobs(vault_ofis, folders=FOLDERS, legacy=False):
    """Every readable job note in `folders` (plus the flat legacy folder when asked), with no order."""
    out = []
    for folder in tuple(folders) + ((LEGACY,) if legacy else ()):
        folder_dir = folder_path(vault_ofis, folder)
        try:
            entries = list(os.scandir(folder_dir))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith(".") or not NOTE_NAME.fullmatch(e.name) or not e.is_file(follow_symlinks=False):
                continue
            try:
                out.append(_load_at(folder, e.path, e.name))
            except (OSError, UnicodeDecodeError):
                continue
    return out


def find_by_session(vault_ofis, session):
    """The job whose `oturum` is `session` (Devam-Edenler first), or None."""
    if not isinstance(session, str) or not session:
        return None
    order = {ACTIVE: 0, QUEUED: 1, DONE: 2}
    matches = [j for j in list_jobs(vault_ofis) if j.meta.get("oturum") == session]
    matches.sort(key=lambda j: order[j.folder])
    return matches[0] if matches else None


def has_message(job, message_id):
    return message_id in (job.meta.get("islenen_mesajlar") or "").split(",")


# --- writes ---

def _exists_anywhere(vault_ofis, name):
    return any(os.path.lexists(os.path.join(folder_path(vault_ofis, f), name)) for f in FOLDERS + (LEGACY,))


def create(vault_ofis, project, title, task=None, fields=None, now=None, brief=None):
    """Writes a new `sirada` job in Siradakiler; never overwrites. Returns the Job.

    The ## Görev content is the brief (render_brief) when given, else the plain task text."""
    if brief is not None:
        task = render_brief(brief)
        fields = dict(fields or {})
        if isinstance(brief.get("kontrol"), str) and brief["kontrol"].strip():
            fields["kontrol"] = brief["kontrol"]
            fields["kontrol_ozet"] = kontrol_digest(brief["kontrol"])
    if not isinstance(task, str) or not task.strip():
        raise JobError("the job has no task")
    lines = ["tags: [ofis, is, " + project + "]"]
    _set_line(lines, "proje", project)
    _set_line(lines, "baslik", title)
    _set_line(lines, "durum", "sirada")
    _set_line(lines, "yurutucu", "claude")
    for key in FIELD_ORDER:
        if key in (fields or {}) and fields[key] not in (None, ""):
            _set_line(lines, key, fields[key])
    for key, value in (fields or {}).items():
        if key not in FIELD_ORDER and value not in (None, ""):
            _set_line(lines, key, value)
    _set_line(lines, "olusturuldu", f"{now:%Y-%m-%dT%H:%M:%S}")
    body = (f"# {project} — {' '.join(title.split())}\n\n"
            f"## Görev\n\n{task.strip()}\n\n"
            f"## Sonuç\n\n{PLACEHOLDER}\n\n"
            "## İlgili Kararlar\n\n"
            "## İlgili Sayfalar\n- [[OFIS/README]]\n")
    text = render(lines, body)
    folder_dir = folder_path(vault_ofis, QUEUED)
    with locked(vault_ofis):
        try:
            os.makedirs(folder_dir, exist_ok=True)
        except OSError as e:
            raise JobError(f"cannot create the job folder ({type(e).__name__})") from e
        base = f"{now:%Y-%m-%d-%H%M%S}-{project}"
        for suffix in [""] + [f"-{i}" for i in range(2, 100)]:
            name = f"{base}{suffix}.md"
            if _exists_anywhere(vault_ofis, name):
                continue
            path = os.path.join(folder_dir, name)
            try:
                with open(path, "x", encoding="utf-8") as f:
                    f.write(text)
            except FileExistsError:
                continue
            except OSError as e:
                raise JobError(f"cannot write the job note ({type(e).__name__})") from e
            return _load_at(QUEUED, path, name)
    raise JobError("no free file name for the job note")


def _move(vault_ofis, job):
    """Moves the note to the folder of its status; never overwrites. Returns the Job at its new place."""
    target = folder_for(job.meta.get("durum"))
    if target == job.folder:
        return job
    target_dir = folder_path(vault_ofis, target)
    os.makedirs(target_dir, exist_ok=True)
    dst = os.path.join(target_dir, job.name)
    if os.path.lexists(dst):
        raise JobError(f"refusing to overwrite {target}/{job.name}")
    os.replace(job.path, dst)
    return job._replace(folder=target, path=dst)


def settle(vault_ofis, name):
    """Moves a note whose status does not match its folder (e.g. after a crash mid-update)."""
    with locked(vault_ofis):
        job = load(vault_ofis, name)
        if job.meta.get("durum") in STATUS_FOLDER:
            job = _move(vault_ofis, job)
        return job


def update(vault_ofis, name, status=None, fields=None, append_result=None, add_decision=None, add_message=None,
           expect=None):
    """Changes one note atomically and moves it when its status changes. Returns the updated Job.

    expect: statuses the note must have now, else StatusConflict (nothing is written).
    add_message: an inbox message id recorded in `islenen_mesajlar` in the same write as the change.
    A note that reaches a final status (Bitenler) for the first time gets `karne: bekliyor` in the same write: the
    server's scorecard (bin/karne.py) writes one row per job and then sets `karne: yazildi`, so every writer of a
    final status (post office, ofis.py bitir/iptal, a failed launch) is covered and a job is counted once."""
    if status is not None:
        folder_for(status)
    with locked(vault_ofis):
        job = load(vault_ofis, name)
        if job.meta.get("durum") in STATUS_FOLDER:
            job = _move(vault_ofis, job)  # finish an earlier interrupted move first
        if expect is not None and job.meta.get("durum") not in expect:
            raise StatusConflict(f"{job.name} is '{job.meta.get('durum')}', expected one of {', '.join(expect)}")
        lines, _, body = parse(_read(job.path))
        if status is not None:
            _set_line(lines, "durum", status)
            if status in FINAL_STATUSES and not job.meta.get("karne") and "karne" not in (fields or {}):
                _set_line(lines, "karne", "bekliyor")
        for key, value in (fields or {}).items():
            _set_line(lines, key, "" if value is None else value)
        if add_message:
            done = [m for m in (job.meta.get("islenen_mesajlar") or "").split(",") if m]
            if add_message not in done:
                done.append(add_message)
            _set_line(lines, "islenen_mesajlar", ",".join(done[-MAX_MESSAGES:]))
        if append_result:
            current = section(body, "Sonuç")
            text = append_result.strip()
            new = text if not current or current in OLD_PLACEHOLDERS else f"{current}\n\n{text}"
            body = set_section(body, "Sonuç", new, before="İlgili Kararlar")
        if add_decision:
            body = _append_list_item(body, "İlgili Kararlar", f"- [[{stem(check_name(add_decision))}]]",
                                     before="İlgili Sayfalar")
        _write_atomic(job.path, render(lines, body))
        _, meta, body = parse(_read(job.path))
        job = job._replace(meta=meta, body=body)
        return _move(vault_ofis, job)
