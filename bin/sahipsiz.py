"""Orphan office sessions ("sahipsiz oturum", owner decision 2026-11-16).

A background session whose name starts with "ofis-" but that no job (any status, any folder) names as its session
falls through every other rule of the office: the post office stops sessions only on a budget / call-limit stop and
accidental resume copies. Found live on 2026-11-16 (an `ofis-<proje>-…` session alive for two days).

`Sahipsiz.check(agents)` runs on the post office's thread (bin/postoffice.py, every ORPHAN_CHECK_SECONDS, on the
cached `claude agents` list) and sends the CEO ONE notice per such session once it has existed longer than ofis.json
`sahipsiz_oturum_saat` hours (default 3). The office never stops, kills or deletes it: the CEO asks the owner and only on
his yes runs `claude stop <short id>`.

Never considered: the CEO session (cfg `ceo_session`, and "ofis-ceo"), a name not starting with "ofis-", a forbidden
(`guvenlik.yasak_yollar`) or missing working folder, a row without a valid session id or a start time. A session is "referenced" when a
job note (Siradakiler / Devam-Edenler / Bitenler / the legacy flat folder) or a server record (`durum/isler/`) has it
as `oturum`. When the vault's job folder cannot be read the check is skipped (it would flag every session).

Once-only across restarts: `durum/sahipsiz/bildirilen.json` = {"oturumlar": {<session id>: {"ad", "bildirildi"}}};
the CEO queue also dedups by the key `sahipsiz-<session id>`. Entries of sessions no longer listed are forgotten.
"""
import json
import os
import tempfile
from datetime import datetime

import jobs
import launch
import limitler
import records
import sahip
import transcript

CONFIG_KEY = "sahipsiz_oturum_saat"
DEFAULT_HOURS = 3
STATE_DIR = "sahipsiz"
STATE_FILE = "bildirilen.json"
SYSTEM_PREFIX = transcript.SYSTEM_PREFIX


def threshold_hours(cfg):
    """ofis.json `sahipsiz_oturum_saat` (a positive number of hours), else DEFAULT_HOURS."""
    value = (cfg or {}).get(CONFIG_KEY)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 24 * 365:
        return float(value)
    return float(DEFAULT_HOURS)


def _forbidden(cwd):
    if not isinstance(cwd, str) or not cwd:
        return True
    return launch.is_forbidden_path(cwd) or launch.is_forbidden_path(os.path.realpath(cwd))


def _same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except (OSError, TypeError):
        return isinstance(a, str) and isinstance(b, str) and os.path.realpath(a) == os.path.realpath(b)


def project_of(cfg, cwd):
    """The registry name of the project whose folder is cwd, else the folder's base name."""
    for name, entry in ((cfg or {}).get("projects") or {}).items():
        path = entry.get("path") if isinstance(entry, dict) else None
        if isinstance(path, str) and _same_dir(os.path.expanduser(path), cwd):
            return name
    return os.path.basename(os.path.normpath(cwd))


def referenced_sessions(vault_ofis, durum_dir):
    """Every session name a job note or a server record names as `oturum`; None when the job folder is unreadable."""
    if not os.path.isdir(jobs.folder_path(vault_ofis, "")):
        return None
    names = {j.meta.get("oturum") for j in jobs.list_jobs(vault_ofis, legacy=True)}
    folder = os.path.join(durum_dir, records.FOLDER)
    try:
        entries = list(os.scandir(folder))
    except OSError:
        entries = []
    for e in entries:
        if not e.name.endswith(".json") or not e.is_file(follow_symlinks=False):
            continue
        try:
            with open(e.path, encoding="utf-8") as f:
                data = json.loads(f.read(64 * 1024))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            names.add(data.get("oturum"))
    return {n for n in names if isinstance(n, str) and n}


def notice(name, project, short_id, started, hours, tz):
    t = started.astimezone(tz)
    since = f"{t.day} {limitler.AYLAR[t.month - 1]} {t:%H:%M}"
    return (f"{SYSTEM_PREFIX}Sahipsiz oturum: {name} ({project}) {int(hours)} saattir açık (başlangıç {since}) ve "
            f"hiçbir işe bağlı değil. Ofis onu durdurmaz: {sahip.e()} sor (sor kartı); yalnız onun onayıyla `claude stop "
            f"{short_id}` ile durdur, `claude rm` asla.")


class Sahipsiz:
    def __init__(self, cfg, durum_dir, ceo, now=None, log=None):
        self.cfg = cfg
        self.durum_dir = durum_dir
        self.ceo = ceo
        self.now = now or datetime.now  # a callable returning a datetime (naive = local time)
        self.log = log or (lambda line: None)

    def _path(self):
        return os.path.join(self.durum_dir, STATE_DIR, STATE_FILE)

    def _load(self):
        p = self._path()
        if os.path.islink(p) or not os.path.isfile(p):
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                data = json.loads(f.read(256 * 1024))
        except (OSError, ValueError, UnicodeDecodeError):
            return {}
        told = data.get("oturumlar") if isinstance(data, dict) else None
        return {k: v for k, v in told.items() if isinstance(v, dict)} if isinstance(told, dict) else {}

    def _save(self, told):
        folder = os.path.dirname(self._path())
        if os.path.islink(folder) or os.path.islink(self._path()):
            raise OSError("the sahipsiz state is a link")
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".bildirilen-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"oturumlar": told}, ensure_ascii=False, indent=1) + "\n")
            os.replace(tmp, self._path())
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def orphans(self, agents):
        """[(agent row, started datetime, age hours)] of the orphan sessions past the threshold; None = cannot tell."""
        cfg = self.cfg
        refs = referenced_sessions(os.path.expanduser(cfg["vault_ofis"]), self.durum_dir)
        if refs is None:
            return None
        ceo_names = {"ofis-ceo", cfg.get("ceo_session") or "ofis-ceo"}
        limit = threshold_hours(cfg)
        now = self.now()
        now_ts = now.timestamp()
        out, seen = [], set()
        for a in agents:
            name, sid, started_ms = a.get("name"), a.get("sessionId"), a.get("startedAt")
            if not isinstance(name, str) or not name.startswith("ofis-") or name in ceo_names or name in refs:
                continue
            if _forbidden(a.get("cwd")) or not transcript.valid_session_id(sid) or sid in seen:
                continue
            if not isinstance(started_ms, (int, float)) or isinstance(started_ms, bool) or started_ms <= 0:
                continue
            age = (now_ts - started_ms / 1000) / 3600
            if age < limit:
                continue
            seen.add(sid)
            out.append((a, datetime.fromtimestamp(started_ms / 1000).astimezone(), age))
        return out

    def check(self, agents):
        """Sends the due notices; returns the names told now. Never stops anything."""
        found = self.orphans(agents)
        if found is None:
            return []
        told = self._load()
        listed = {a.get("sessionId") for a in agents}
        changed = False
        for sid in [s for s in told if s not in listed]:
            del told[sid]  # the session is gone: forget it
            changed = True
        sent = []
        tz = limitler._tz(self.cfg)
        for a, started, age in found:
            sid, name = a["sessionId"], a["name"]
            if sid in told:
                continue
            text = notice(name, project_of(self.cfg, a["cwd"]), sid[:8], started, age, tz)
            self.ceo.enqueue(text, f"sahipsiz-{sid}")
            told[sid] = {"ad": name, "bildirildi": f"{self.now():%Y-%m-%dT%H:%M:%S}"}
            changed = True
            sent.append(name)
            self.log(f"orphan session {name} ({sid[:8]}): no job references it; the CEO is told (never stopped)")
        if changed:
            self._save(told)
        return sent
