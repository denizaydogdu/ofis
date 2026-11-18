"""The CEO's recent tool steps for the page's Komuta masası (GET /api/ceo/adimlar).

Read from the tail of the CEO transcript (the last TAIL_WINDOW bytes), cached by the file's inode, size and mtime so
a poll that finds nothing new parses nothing. Only tool calls are read: the tool name and a short, safe target —
a file's base name, the head of a shell command (at most three words, paths as base names, never the heredoc or the
arguments after a flag), a peer session name, a skill name, a web host. Never the assistant's text or thinking, never
a file's content, never a full path. A step whose path, command or name reaches a forbidden project, a credential word
or a private vault folder (ofis.json `guvenlik`, bin/yasaklar.py: the guard's own rules; also as a bare word) is
dropped entirely.
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

import guard
import launch
import pricing
import yasaklar

TAIL_WINDOW = 512 * 1024
MAX_STEPS = 10
HEDEF_LEN = 48
ARAC_LEN = 40
TOOL_RECORD = re.compile(rb'"tool_use"|"tool_result"|"turn_duration"|"type":\s*"user"')
CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")
SAFE_NAME = re.compile(r"[\w:.-]{1,40}")
SHELL_SPLIT = re.compile(r"&&|\|\||[;|\n]")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# the fields that say where a tool went (checked against the forbidden patterns); content fields are never read
TARGET_FIELDS = ("file_path", "notebook_path", "path", "command", "pattern", "glob", "to", "url", "skill",
                 "subagent_type")

PAST = {"Read": "okudu", "Edit": "düzenledi", "MultiEdit": "düzenledi", "Write": "yazdı", "NotebookEdit": "düzenledi",
        "Bash": "çalıştırdı", "Grep": "aradı", "Glob": "aradı", "SendMessage": "mesaj gönderdi",
        "Agent": "yardımcı çalıştırdı", "Task": "yardımcı çalıştırdı", "Skill": "beceri kullandı",
        "WebFetch": "web sayfası okudu", "WebSearch": "web'de aradı", "ToolSearch": "araç aradı",
        "TodoWrite": "yapılacakları güncelledi"}
NOW = {"Read": "okuyor", "Edit": "düzenliyor", "MultiEdit": "düzenliyor", "Write": "yazıyor",
       "NotebookEdit": "düzenliyor", "Bash": "komut çalıştırıyor", "Grep": "arıyor", "Glob": "arıyor",
       "SendMessage": "mesaj gönderiyor", "Agent": "yardımcı çalıştırıyor", "Task": "yardımcı çalıştırıyor",
       "Skill": "beceri kullanıyor", "WebFetch": "web sayfası okuyor", "WebSearch": "web'de arıyor",
       "ToolSearch": "araç arıyor", "TodoWrite": "yapılacakları güncelliyor"}

_parse = json.loads  # indirection so tests can count parsed lines
_cache = {}  # path -> ((inode, size, mtime_ns), parsed)
_lock = threading.Lock()


def forbidden(text):
    """True when a path, command or name reaches a forbidden project, the credential notes or the private vault folders."""
    if not isinstance(text, str) or not text:
        return False
    folded = guard.tidy(guard.fold(text))
    r = yasaklar.kurallar()
    return bool(r.yol_kelimesi.search(folded) or r.kelime.search(folded)
                or r.klasor_yolu.search(folded) or r.klasor_kelimesi.search(folded)
                or launch.is_forbidden_path(text))


def _clip(text, n=HEDEF_LEN):
    text = CONTROL.sub(" ", str(text or "")).strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _base(value):
    return os.path.basename(str(value).rstrip("/")) or ""


SAFE_WORD = re.compile(r"[a-z][a-z0-9._-]{0,31}")
SAFE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
# a word that looks like a credential or an opaque id is never shown, whatever the program
OPAQUE_WORD = re.compile("(?i)" + "|".join(("sk-", "gh[pousr]_", "github_pat", "xox[a-z]?-", "akia",
                                             "[0-9a-f]{16,}", "[A-Za-z0-9+/_-]{24,}")))
UNSAFE_CHARS = (":", "@", "%", "=")
# programs whose next word is a subcommand (shown when it is a plain lower-case word)
SUBCOMMAND = {"git", "claude", "npm", "brew", "launchctl", "codex", "opencode", "pip", "pip3"}
PYTHONS = {"python", "python3"}
FILE_READERS = {"cat", "head", "tail", "wc", "less"}
SKIP_PROGRAMS = {"cd", "pushd", "popd", "set", "export", "unset", "source", "."}


def _plain(word, pattern):
    """`word` when it is safe to show under `pattern` (no ':', '@', '%', '=', nothing opaque), else None."""
    if not isinstance(word, str) or any(c in word for c in UNSAFE_CHARS) or OPAQUE_WORD.search(word):
        return None
    return word if pattern.fullmatch(word) else None


def command_head(command):
    """The program of a shell command (an allowlist, review of 2026-11-12): the first segment that is not a `cd` /
    `export`; the program's base name only — plus, for a known program, one subcommand word (`git status`, `claude
    agents`), for python the script's base name and one subcommand (`python3 ofis.py durum`), for a file reader the
    file's base name (`cat Index.md`). Arguments of every other program (echo, grep, curl, ssh, sed, env, openssl, …)
    are never shown; a word with ':', '@', '%', '=' or that looks opaque (a credential, a long hex or base64 run) is
    dropped, and so is everything after a flag. "" when nothing safe is left."""
    if not isinstance(command, str):
        return ""
    for seg in SHELL_SPLIT.split(command):
        words = seg.split()
        while words and ENV_ASSIGN.match(words[0]):
            words.pop(0)
        if not words or words[0] in SKIP_PROGRAMS:
            continue
        prog = _plain(_base(words[0]), SAFE_WORD)
        if not prog:
            return ""
        args = []
        for w in words[1:]:
            if w.startswith("-"):
                break
            args.append(w)
        out = [prog]
        first = args[0] if args else ""
        if prog in SUBCOMMAND and first:
            sub = _plain(first, SAFE_WORD)
            if sub:
                out.append(sub)
        elif prog in PYTHONS and first.endswith(".py") and not any(c in first for c in UNSAFE_CHARS):
            script = _plain(_base(first), SAFE_FILE)
            if script:
                out.append(script)
                sub = _plain(args[1], SAFE_WORD) if len(args) > 1 else None
                if sub:
                    out.append(sub)
        elif prog in FILE_READERS and first and not any(c in first for c in UNSAFE_CHARS):
            name = _plain(_base(first), SAFE_FILE)
            if name:
                out.append(name)
        return _clip(" ".join(out))
    return ""


def target(name, tool_input):
    """A short, safe label of what a tool touched, or None when the step must not be shown at all."""
    if not isinstance(tool_input, dict):
        return ""
    for key in TARGET_FIELDS:
        value = tool_input.get(key)
        if isinstance(value, str) and forbidden(value):
            return None
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return _clip(_base(value))
    if name == "Bash":
        return command_head(tool_input.get("command"))
    if name in ("Grep", "Glob"):
        value = tool_input.get("path")
        return _clip(_base(value)) if isinstance(value, str) and value.strip() else ""
    if name == "SendMessage":
        to = tool_input.get("to")
        if isinstance(to, str) and to.startswith("ofis-"):
            return _clip(to)
        return "başka bir oturum" if to else ""
    if name == "Skill":
        skill = tool_input.get("skill")
        return skill if isinstance(skill, str) and SAFE_NAME.fullmatch(skill) else ""
    if name in ("Agent", "Task"):
        kind = tool_input.get("subagent_type")
        return kind if isinstance(kind, str) and SAFE_NAME.fullmatch(kind) else ""
    if name == "WebFetch":
        try:
            host = urlsplit(str(tool_input.get("url") or "")).hostname or ""
        except ValueError:
            host = ""
        return _clip(host) if SAFE_NAME.fullmatch(host or "-") and host else ""
    value = tool_input.get("path")
    if isinstance(value, str) and value.strip():
        return _clip(_base(value))
    return ""


def _when(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_tail(data):
    """{steps: [{zaman, arac, hedef, ozet, id}] oldest first, open: {tool ids without a result}, turn_start,
    turn_end} from the transcript bytes (the first line may be cut)."""
    steps, seen, results = [], set(), set()
    turn_start = turn_end = None
    last_hidden = False
    for line in data.split(b"\n"):
        if not TOOL_RECORD.search(line):
            continue
        try:
            record = _parse(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("type")
        when = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        if kind == "system" and record.get("subtype") == "turn_duration":
            turn_end, turn_start = when, None
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        if kind == "user":
            parts = content if isinstance(content, list) else []
            tool_results = [p for p in parts if isinstance(p, dict) and p.get("type") == "tool_result"]
            for p in tool_results:
                if isinstance(p.get("tool_use_id"), str):
                    results.add(p["tool_use_id"])
            if not tool_results and turn_start is None:
                turn_start = when  # the prompt (or peer message) that opened the current turn
            continue
        if kind != "assistant" or not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool_use" or not isinstance(part.get("name"), str):
                continue
            pid = part.get("id") if isinstance(part.get("id"), str) else None
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            name = part["name"][:ARAC_LEN]
            hedef = target(name, part.get("input"))
            last_hidden = hedef is None
            if hedef is None:
                continue  # reaches a forbidden place: not shown at all
            steps.append({"zaman": when, "arac": name, "hedef": hedef, "ozet": PAST.get(name, f"{name} kullandı"),
                          "id": pid})
    open_ids = {s["id"] for s in steps if s["id"] and s["id"] not in results}
    return {"steps": steps[-MAX_STEPS * 3:], "open": open_ids, "turn_start": turn_start, "turn_end": turn_end,
            "last_hidden": last_hidden}


def read_tail(path, window=TAIL_WINDOW):
    """The parsed tail of a transcript, cached by (inode, size, mtime); None when it cannot be read."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    key = (st.st_ino, st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
    try:
        with open(path, "rb") as f:
            f.seek(max(0, st.st_size - window))
            data = f.read(window)
    except OSError:
        return None
    parsed = parse_tail(data)
    parsed["turns"] = parse_turns(data, cut=st.st_size > window)
    with _lock:
        _cache[path] = (key, parsed)
    return parsed


def ceo_adimlari(path, durum, now=None, onceki=()):
    """GET /api/ceo/adimlar: {adimlar: [{zaman, arac, hedef, ozet}] newest first (at most MAX_STEPS), durum (the CEO
    state code), arac_simdi ({arac, hedef, ozet} of a tool still running while the CEO works, else None), sure_sn
    (seconds since the current turn began while it works, else since the last turn ended; None when unknown)}.
    onceki: the transcripts of the sessions the CEO was rotated away from (bin/ceo.py), oldest first: their steps
    come before the current session's (the running tool and the times are the current session's only)."""
    now = time.time() if now is None else now
    durum = durum if isinstance(durum, str) else "unknown"
    parsed = read_tail(path) if path else None
    earlier = []
    for p in onceki or ():
        old = read_tail(p)
        if old:
            earlier.extend(old["steps"])
    if not parsed:
        adimlar = [{k: s[k] for k in ("zaman", "arac", "hedef", "ozet")} for s in reversed(earlier)][:MAX_STEPS]
        return {"adimlar": adimlar, "durum": durum, "arac_simdi": None, "sure_sn": None}
    steps = earlier + parsed["steps"]
    adimlar = [{k: s[k] for k in ("zaman", "arac", "hedef", "ozet")} for s in reversed(steps)][:MAX_STEPS]
    arac_simdi = None
    busy = durum in ("busy", "waiting")
    # the newest call is the one running; when it was hidden, nothing is named (never an older, visible one)
    if busy and steps and not parsed["last_hidden"] and steps[-1]["id"] in parsed["open"]:
        last = steps[-1]
        arac_simdi = {"arac": last["arac"], "hedef": last["hedef"],
                      "ozet": NOW.get(last["arac"], f"{last['arac']} kullanıyor")}
    since = _when(parsed["turn_start"]) if busy else _when(parsed["turn_end"])
    sure = int(max(0, now - since)) if since is not None else None
    return {"adimlar": adimlar, "durum": durum, "arac_simdi": arac_simdi, "sure_sn": sure}


# --- the CEO's turns (owner decision 2026-11-12): one footer per reply in the chat, "Cevap verdi · tur kapanıyor" ---
# A turn opens with a top-level prompt (or any user record that is not a tool result once the previous turn ended) and
# ends with Claude Code's `turn_duration` record (not `stop_hook_summary`: a blocking Stop hook continues the turn).
# Per turn: its visible steps (the same safe-target
# rules as above: a step reaching a forbidden project or a private folder is not counted and its result is never read), the jobs it
# opened (the JSON line `ofis.py ekle` / `akis` / `baslat` printed, only for such a command), the time of its last reply
# text (the page matches the chat line by it) and the list-price cost and tokens of its calls (bin/pricing.py).
MAX_TURNS = 30
MAX_TURN_JOBS = 5
TURN_RECORD = re.compile(rb'"type":\s*"(?:user|assistant)"|"subtype":\s*"turn_duration"')
JOB_NOTE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}-[a-z0-9][a-z0-9-]{0,60}\.md")
WORKFLOW_ID = re.compile(r"akis-\d{4}-\d{6}-[a-z0-9][a-z0-9-]{0,40}")
PLAIN_VALUE = re.compile(r"[a-z0-9][a-z0-9._-]{0,39}")
OPENING = ("ekle", "akis", "baslat")
TURN_END_KINDS = ("turn_duration",)  # a blocking Stop hook continues the turn after its stop_hook_summary
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def opening_command(command):
    """"ekle" / "akis" / "baslat" when a shell command runs bin/ofis.py with that subcommand, else None."""
    if not isinstance(command, str):
        return None
    for seg in SHELL_SPLIT.split(command):
        words = [w.strip("'\"") for w in seg.split()]
        for i, w in enumerate(words):
            if _base(w) == "ofis.py":
                if i + 1 < len(words) and words[i + 1] in OPENING:
                    return words[i + 1]
                break
    return None


def _result_text(part):
    content = part.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def _plain_value(value):
    return value if isinstance(value, str) and PLAIN_VALUE.fullmatch(value) else ""


def opened_jobs(kind, text):
    """The jobs a successful `ofis.py ekle` / `akis` / `baslat` printed: [{note, katman, model, akis, adim_sayisi}].
    Only the command's own JSON line counts; every value is checked against a strict pattern (nothing else is kept)."""
    out = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        if kind == "akis":
            names = [n for n in data.get("isler") or [] if isinstance(n, str) and JOB_NOTE.fullmatch(n)]
            grup = data.get("grup") if isinstance(data.get("grup"), str) and WORKFLOW_ID.fullmatch(data["grup"]) else ""
            if names and grup:
                out.append({"note": names[0], "katman": "", "model": "", "akis": grup, "adim_sayisi": len(names)})
        elif isinstance(data.get("is"), str) and JOB_NOTE.fullmatch(data["is"]):
            out.append({"note": data["is"], "katman": _plain_value(data.get("katman")),
                        "model": _plain_value(data.get("model")), "akis": "", "adim_sayisi": 0})
    return out


def _new_turn(when):
    return {"basla": when, "bitis": None, "cevap_zaman": None, "adim": 0, "isler": [], "usd": 0.0, "token": 0,
            "fiyat_eksik": False, "_ids": set(), "_seen": set(), "_open": set(), "_acan": {}, "_son": None}


def parse_turns(data, cut=False):
    """The turns in the transcript bytes, oldest first, each {basla, bitis, cevap_zaman, adim, isler, usd, token,
    fiyat_eksik, kapaniyor}. cut: the bytes start inside the file, so the turn before the first prompt seen is partial
    and left out."""
    turns, cur = [], None
    for line in data.split(b"\n"):
        if not TURN_RECORD.search(line):
            continue
        try:
            record = _parse(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        kind = record.get("type")
        when = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
        if kind == "system":
            if record.get("subtype") in TURN_END_KINDS and cur is not None and cur["bitis"] is None:
                cur["bitis"] = when or ""
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        if kind == "user":
            parts = content if isinstance(content, list) else []
            results = [p for p in parts if isinstance(p, dict) and p.get("type") == "tool_result"]
            if not results:
                origin = record.get("origin") if isinstance(record.get("origin"), dict) else {}
                prompt = origin.get("kind") == "human" and not record.get("isMeta")
                if cur is None or cur["bitis"] is not None or prompt:
                    cur = _new_turn(when)
                    turns.append(cur)
                else:
                    cur["_son"] = "kullanici"
                continue
            if cur is None:
                if cut:
                    continue
                cur = _new_turn(None)
                turns.append(cur)
            for p in results:
                pid = p.get("tool_use_id")
                if not isinstance(pid, str):
                    continue
                cur["_open"].discard(pid)
                opening = cur["_acan"].pop(pid, None)
                if opening and not p.get("is_error") and len(cur["isler"]) < MAX_TURN_JOBS:
                    known = {j["note"] for j in cur["isler"]}
                    for j in opened_jobs(opening, _result_text(p)):  # `ekle` then `baslat` of one job: listed once
                        if j["note"] not in known and len(cur["isler"]) < MAX_TURN_JOBS:
                            known.add(j["note"])
                            cur["isler"].append(j)
            continue
        if kind != "assistant":
            continue
        if cur is None:
            if cut:
                continue
            cur = _new_turn(None)
            turns.append(cur)
        synthetic = message.get("model") == "<synthetic>"
        msg_id = message.get("id")
        usage = message.get("usage")
        if isinstance(usage, dict) and not synthetic and (msg_id is None or msg_id not in cur["_ids"]):
            if msg_id is not None:
                cur["_ids"].add(msg_id)
            cur["token"] += sum(v for v in (usage.get(k) for k in USAGE_FIELDS) if isinstance(v, int) and v > 0)
            cost = pricing.call_cost(message.get("model"), usage)
            if cost is None:
                cur["fiyat_eksik"] = True
            else:
                cur["usd"] += cost["total"]
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use" and isinstance(part.get("name"), str):
                pid = part.get("id") if isinstance(part.get("id"), str) else None
                if pid and pid in cur["_seen"]:
                    continue  # a repeated chunk of the same call
                if pid:
                    cur["_seen"].add(pid)
                cur["_son"] = "arac"
                hedef = target(part["name"][:ARAC_LEN], part.get("input"))
                if hedef is None:
                    continue  # reaches a forbidden place: not counted, its result never read
                if pid:
                    cur["_open"].add(pid)
                cur["adim"] += 1
                if part["name"] == "Bash" and pid and isinstance(part.get("input"), dict):
                    opening = opening_command(part["input"].get("command"))
                    if opening:
                        cur["_acan"][pid] = opening
            elif part.get("type") == "text" and isinstance(part.get("text"), str) and part["text"].strip() \
                    and message.get("stop_reason") != "tool_use" and not synthetic:
                cur["cevap_zaman"] = when
                cur["_son"] = "metin"
    out = []
    for i, t in enumerate(turns):
        closing = i == len(turns) - 1 and t["bitis"] is None and t["_son"] == "metin" and not t["_open"]
        t["kapaniyor"] = closing  # only the newest turn can still be closing
        t["usd"] = round(t["usd"], 6)
        out.append({k: v for k, v in t.items() if not k.startswith("_")})
    return out


def ceo_turlari(path, onceki=()):
    """GET /api/ceo/turlar: {turlar: newest first (at most MAX_TURNS), kapaniyor: the newest turn's reply is written but
    the turn has not ended yet}. onceki: the transcripts of the sessions the CEO was rotated away from (oldest first);
    their turns come after the current session's (kapaniyor is the current session's only)."""
    parsed = read_tail(path) if path else None
    turns = (parsed or {}).get("turns") or []
    earlier = []
    for p in onceki or ():
        old = read_tail(p)
        earlier.extend((old or {}).get("turns") or [])
    every = earlier + turns
    return {"turlar": [dict(t, isler=[dict(j) for j in t["isler"]]) for t in reversed(every[-MAX_TURNS:])],
            "kapaniyor": bool(turns and turns[-1]["kapaniyor"])}


def tur_kapaniyor(path):
    """True while the CEO's last reply of the current turn is written but the turn has not ended (state.ceo)."""
    return ceo_turlari(path)["kapaniyor"] if path else False


ROLES = {"haiku": "Stajyer", "sonnet": "Uzman", "opus": "Kıdemli", "fable": "Genel Müdür"}


def _role(model):
    low = str(model or "").lower()
    return next((r for fam, r in ROLES.items() if fam in low), "")


def isleri_tamamla(turlar, tasks, cfg=None):
    """Gives each opened job its title (the office state's task, else the note's stem) and its role (the job's model:
    the server record's, else the one `ekle` printed, else its tier's mapping in ofis.json)."""
    by_note = {}
    for t in tasks or []:
        if isinstance(t, dict) and isinstance(t.get("note"), str):
            by_note.setdefault(t["note"], t)
    tiers = (cfg or {}).get("tiers") if isinstance((cfg or {}).get("tiers"), dict) else {}
    for tur in turlar:
        for j in tur.get("isler") or []:
            t = by_note.get(j["note"]) or {}
            j["baslik"] = _clip(t.get("title") or j["note"][:-3], 80)
            model = t.get("model") or j.get("model") or ""
            if not _role(model) and j.get("katman") and isinstance(tiers.get(j["katman"]), dict):
                model = tiers[j["katman"]].get("model") or ""
            j["unvan"] = _role(model)
            j["katman"] = j.get("katman") or str(t.get("tier") or "")
    return turlar
