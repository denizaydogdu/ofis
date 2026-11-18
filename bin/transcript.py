"""Incremental reading of Claude Code session transcripts (~/.claude/projects/<cwd>/<sessionId>.jsonl).

A transcript is read by byte offset: each poll reads only what was appended since the last poll, and only complete
lines are parsed. From the records it keeps today's token usage (de-duplicated by message.id), the last tool call
(name + a short target, never message text) and, when asked, the chat lines shown on the office page.
"""
import json
import os
import re
from datetime import datetime

import sahip

# The owner's top-level prompts (bin/sahip.py): the server writes only the neutral "[Sahip · …]" forms; the parser
# below also reads the old "[Deniz · …]" ones that stored transcripts hold.
CHAT_PREFIX = sahip.CHAT_PREFIX
ANSWER_PREFIX = sahip.ANSWER_PREFIX
# The owner's spoken request through Jarvis (bin/jarvis.py is-ekle): only the server writes this first line, and only
# for a request with the Jarvis key; an optional "Proje: <ad>" line follows, then the text.
JARVIS_PREFIX = sahip.JARVIS_PREFIX
ROLE = "sahip"  # the owner's chat lines (the old role "deniz" is still accepted by the readers: ROLES)
ROLES = (ROLE, "deniz")
JARVIS_PROJE = re.compile(r"Proje: ([a-z0-9-]{1,40})\n")
JARVIS_KANAL = "Jarvis üzerinden"
SYSTEM_PREFIX = "[Ofis · sistem]\n"  # notices from the office server (post office), not the owner
# The handoff block a rotated CEO session gets before the first message (bin/devir.py, bin/ceo.py): the server's data.
# Both marker lines carry a per-rotation id (16 hex) that the server records in durum/ceo.json (`devir_kimlikleri`)
# before the start; only a block with the exact start line at the very beginning AND the end line with the same id is
# taken apart, and only one whose id is recorded is hidden (verify_handoffs) — text the owner types can never be hidden by
# copying the markers.
HANDOFF_START = re.compile(r"\[Ofis · devir notu · ([0-9a-f]{16})\]\n")
HANDOFF_LINE = "CEO yeni oturumla devam ediyor · devir notu verildi"


def handoff_markers(kimlik):
    """(start line, end line) of the handoff block with id `kimlik` (16 hex)."""
    return f"[Ofis · devir notu · {kimlik}]\n", f"\n[Ofis · devir notu sonu · {kimlik}]\n"


def verify_handoffs(lines, kimlikler):
    """Chat lines with every handoff checked against the ids the server recorded: a recorded one keeps its small system
    line and the message after it; an unknown one is shown as the raw prompt it was (the owner's line), nothing hidden.
    Returns new dicts (the cached lines are not changed); the internal keys are dropped."""
    known = set(kimlikler or ())
    out, bad = [], set()
    for m in lines:
        k = m.get("devir")
        if m.get("kind") == "devir" and k is not None:
            if k in known:
                out.append({x: v for x, v in m.items() if x not in ("_ham", "devir")})
            else:
                bad.add(k)
                out.append({"role": ROLE, "text": m.get("_ham", ""), "time": m.get("time")})
            continue
        if "_devir" in m:
            if m["_devir"] in bad:
                continue
            m = {x: v for x, v in m.items() if x != "_devir"}
        out.append(m)
    return out
# The last line of every message the server delivers to the CEO ("(<Owner>'e Türkçe ve sade yaz.)", sahip.hatirlatma):
# a resumed session does not re-read CLAUDE.md. strip_reminder removes it under any owner name.
import pricing  # noqa: E402

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
CROSS_SESSION = re.compile(
    r"<cross-session-message\b([^>]*)>(.*?)</cross-session-message>", re.S)
FROM_NAME = re.compile(r'\bfrom-name="([^"]*)"')
RECORD_KIND = re.compile(rb'"type":\s*"(?:user|assistant)"')  # cheap prefilter before json.loads
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{3,63}")
MAX_READ = 4 * 1024 * 1024  # bytes per poll; a large backlog is consumed over several polls
MAX_CHAT = 500
TARGET_LEN = 40


_parse = json.loads  # indirection so tests can count parsed lines


def encode_cwd(cwd):
    return cwd.replace("/", "-")


def valid_session_id(value):
    return isinstance(value, str) and SESSION_ID.fullmatch(value) is not None


def _folder_names(cwd):
    return list(dict.fromkeys([encode_cwd(cwd), re.sub(r"[^A-Za-z0-9-]", "-", cwd)]))


def transcript_path(projects_dir, cwd, session_id):
    """Path of a session transcript. Claude Code replaces '/' (and other non-alphanumerics) in the cwd with '-'."""
    paths = [os.path.join(projects_dir, c, f"{session_id}.jsonl") for c in _folder_names(cwd)]
    for p in paths:
        if os.path.isfile(p):
            return p
    return paths[0]


def project_folder(projects_dir, cwd):
    """The transcript folder of a cwd: the existing one of the two encodings, else Claude Code's own (every
    non-alphanumeric, also the dot of a worktree's .claude, becomes '-')."""
    names = _folder_names(cwd)
    for name in names:
        if os.path.isdir(os.path.join(projects_dir, name)):
            return os.path.join(projects_dir, name)
    return os.path.join(projects_dir, names[-1])


def forbidden_folder(folder):
    """True for a transcript folder that may belong to a forbidden project (launch.is_forbidden_component: ofis.json
    `guvenlik.yasak_yollar`). Claude Code
    encodes a cwd by turning every non-alphanumeric into "-", so a cwd that passes the path check (~/Dev_<name>) can
    still land in a forbidden project's folder: any "-" part of the folder name that is a forbidden component refuses
    it. Nothing in such a folder is read (tokens, chat, subagents, model status)."""
    import launch  # lazy: launch imports records, which imports this module
    if not isinstance(folder, str) or not folder:
        return True
    if launch.is_forbidden_path(folder) or launch.is_forbidden_path(os.path.realpath(folder)):
        return True
    names = {os.path.basename(folder.rstrip(os.sep)), os.path.basename(os.path.realpath(folder))}
    return any(launch.is_forbidden_component(part) for name in names for part in name.split("-") if part)


NAME_RECORD = re.compile(rb'"type":\s*"(?:agent-name|custom-title)"')
HEAD_BYTES = 64 * 1024
HEAD_LINES = 16
_names_cache = {}  # path -> (inode, frozenset of names): the head of a transcript never changes once written


def _head_names(path):
    """The session names (agent-name / custom-title records) at the top of a transcript, or None when the head is
    not complete yet (then nothing is cached)."""
    try:
        st = os.stat(path)
    except OSError:
        return frozenset()
    cached = _names_cache.get(path)
    if cached and cached[0] == st.st_ino:
        return cached[1]
    try:
        with open(path, "rb") as f:
            data = f.read(HEAD_BYTES)
    except OSError:
        return frozenset()
    lines = data.split(b"\n")
    complete = lines[:-1] if len(data) < HEAD_BYTES or not data.endswith(b"\n") else lines
    names = set()
    for line in complete[:HEAD_LINES]:
        if not NAME_RECORD.search(line):
            continue
        try:
            record = _parse(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            value = record.get("agentName") if record.get("type") == "agent-name" else record.get("customTitle")
            if isinstance(value, str) and value:
                names.add(value)
    result = frozenset(names)
    if names or len(complete) >= HEAD_LINES:
        _names_cache[path] = (st.st_ino, result)
    return result


def _born(st):
    return getattr(st, "st_birthtime", None) or st.st_mtime


def named_sessions(projects_dir, cwd, name, since=None):
    """[(session id, creation time)] of the transcripts in cwd's project folder whose head names the session `name`
    (agent-name or custom-title record), oldest first; with `since` (epoch seconds) only files written since then.
    A resumed project session continues in a new transcript with the same name (Claude Code 2.1.322), so a session
    name can have several ids; the newest one is where it goes on."""
    folder = project_folder(projects_dir, cwd)
    if forbidden_folder(folder):
        return []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    out = []
    for e in entries:
        sid = e.name[:-6]
        if not e.name.endswith(".jsonl") or not valid_session_id(sid):
            continue
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if not e.is_file(follow_symlinks=False) or (since is not None and st.st_mtime < since):
            continue
        if name in _head_names(e.path):
            out.append((sid, _born(st)))
    out.sort(key=lambda x: (x[1], x[0]))
    return out


def progress_since(path, since):
    """True when the transcript has a model reply after `since` (aware datetime) that used a tool or wrote text:
    the session is making progress. Synthetic replies (written by Claude Code itself) do not count."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    for line in data.split(b"\n"):
        if b'"assistant"' not in line or not RECORD_KIND.search(line):
            continue
        try:
            record = _parse(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        when = parse_time(record.get("timestamp"))
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        if when is None or when < since or message.get("model") == "<synthetic>":
            continue
        for part in message.get("content") or []:
            if isinstance(part, dict) and (part.get("type") == "tool_use" or
                                           (part.get("type") == "text" and str(part.get("text", "")).strip())):
                return True
    return False


def strip_reminder(text):
    """The owner's own message without the reminder line the server appended for the CEO."""
    return sahip.hatirlatmayi_sil(text)


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def tool_target(name, tool_input):
    """A short, non-sensitive label for what a tool touched: a file base name or a peer session name."""
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return os.path.basename(value.rstrip("/"))[:TARGET_LEN]
    if name == "SendMessage" and isinstance(tool_input.get("to"), str):
        return tool_input["to"][:TARGET_LEN]
    if name == "Skill" and isinstance(tool_input.get("skill"), str):
        return tool_input["skill"][:TARGET_LEN]
    return ""


def _user_text(content):
    """Text of a user record, or None when it is a tool result (or has no text)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
        return None
    texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
    return "\n".join(t for t in texts if t) or None


OUTSIDE_PEER = "Ofis dışından bir oturum mesajı gizlendi."
INTERRUPTED = "[Request interrupted by user"


def _peer_line(sender, body, time):
    """One system line for a peer message; senders outside the office never show their text."""
    if not isinstance(sender, str) or not sender.startswith("ofis-"):
        return {"role": "system", "text": OUTSIDE_PEER, "time": time}
    return {"role": "system", "from": sender, "text": f"{sender}: {body}", "time": time}


def _peer_lines(record, text, time):
    """Peer messages: the structured origin (sender name, body) is trusted; the <cross-session-message> tag text
    is only a fallback for records without it, because a body can contain a closing and a new opening tag."""
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind") == "peer":
        if origin.get("handback"):
            return []  # a subagent's hand-back report: internal work, not office chat
        sender, body = origin.get("name"), origin.get("body")
        if isinstance(sender, str) and isinstance(body, str):
            return [_peer_line(sender, body.strip(), time)] if body.strip() else []
    out = []
    for match in CROSS_SESSION.finditer(text or ""):
        sender = FROM_NAME.search(match.group(1))
        body = match.group(2).strip()
        if body:
            out.append(_peer_line(sender.group(1) if sender else None, body, time))
    return out


def _user_lines(record, message, time):
    origin = record.get("origin") if isinstance(record.get("origin"), dict) else {}
    kind = origin.get("kind")
    text = _user_text(message.get("content"))
    if kind == "peer" or (record.get("isMeta") and not kind):
        return _peer_lines(record, text, time)
    if not text or record.get("isMeta") or record.get("isCompactSummary"):
        return []  # harness notices (idle notice, images, continuations) and compaction summaries
    if kind == "human":
        # Only a top-level prompt (what the server delivers) is the owner; the prefix only splits text and note.
        # A post-office notice is also a top-level prompt, but it is the server speaking, not the owner.
        text = strip_reminder(text)
        start = HANDOFF_START.match(text)
        if start:
            # a rotated CEO session's first prompt: the server's handoff block (one small system line, never its
            # text), then the message it carried. Without the matching end line the prompt is shown unchanged.
            end_marker = handoff_markers(start.group(1))[1]
            end = text.find(end_marker, start.end())
            if end >= 0:
                kimlik = start.group(1)
                line = {"role": "system", "kind": "devir", "text": HANDOFF_LINE, "time": time, "devir": kimlik,
                        "_ham": text}
                rest = text[end + len(end_marker):].lstrip("\n")
                if not rest.strip() or HANDOFF_START.match(rest):
                    return [line]
                inner = dict(record, message=dict(message, content=rest))
                return [line] + [dict(x, _devir=kimlik) for x in _user_lines(inner, inner["message"], time)]
        if text.startswith(SYSTEM_PREFIX):
            return [{"role": "system", "kind": "notice", "text": text[len(SYSTEM_PREFIX):], "time": time}]
        prefix = sahip.chat_prefix_of(text)
        if prefix:
            return [{"role": ROLE, "text": text[len(prefix):], "time": time}]
        prefix = sahip.jarvis_prefix_of(text)
        if prefix:
            rest = text[len(prefix):]
            line = {"role": ROLE, "kanal": JARVIS_KANAL, "time": time}
            proje = JARVIS_PROJE.match(rest)
            if proje:
                line["proje"], rest = proje.group(1), rest[proje.end():]
            return [dict(line, text=rest)]
        prefix = sahip.answer_prefix_of(text)
        if prefix:
            first, _, answer = text[len(prefix):].partition("\n")
            return [{"role": ROLE, "text": answer, "note": first.strip(), "time": time}]
        if text.lstrip().startswith("<"):
            return []  # local command output and other harness markup
        return [{"role": ROLE, "text": text, "time": time}]  # typed outside the page
    if text.lstrip().startswith("<") or text.startswith(INTERRUPTED):
        return []  # task notifications, harness markup, interruption markers: noise
    return [{"role": "system", "text": text, "time": time}]


def chat_lines(record):
    """Chat lines for one transcript record: [{role, text, time, ...}]. Tool calls and results are not chat.

    Roles: "sahip" (ROLE) only for top-level prompts (origin.kind == "human"); "ceo" for the CEO's replies; "system" for
    office peer messages, synthetic assistant messages and any other user record that is not noise."""
    kind = record.get("type")
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    time = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
    if kind == "user":
        content = message.get("content")
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
            return []
        return _user_lines(record, message, time)
    out = []
    if kind == "assistant":
        if message.get("stop_reason") == "tool_use":
            return out  # narration written right before a tool call ("Now SendMessage..."), not a reply to the owner
        role = "system" if message.get("model") == "<synthetic>" else "ceo"
        for part in message.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text", "").strip():
                out.append({"role": role, "text": part["text"], "time": time})
    return out


USER_RECORD = re.compile(rb'"type":\s*"user"')
TURN_END = re.compile(rb'"subtype":\s*"turn_duration"')
TAIL_WINDOW = 512 * 1024


def turn_open(path, window=TAIL_WINDOW):
    """True when the transcript's last user record has no turn end after it, i.e. a turn is still running.

    Claude Code closes every completed turn with a `system` record of subtype `turn_duration` (written after the
    final assistant message and the stop-hook summary). Any user record (prompt, peer message, notice, tool result)
    after the last such record means a turn started and has not finished. Returns None when the tail shows neither
    (missing file, or an unknown layout): the caller then relies on `claude agents` alone."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - window))
            data = f.read()
    except OSError:
        return None
    last_user = last_end = -1
    for i, line in enumerate(data.split(b"\n")):
        if TURN_END.search(line):
            last_end = i
        elif USER_RECORD.search(line):
            try:
                record = _parse(line)
            except ValueError:
                continue  # the first line of the window may be cut
            if isinstance(record, dict) and record.get("type") == "user":
                last_user = i
    if last_user < 0 and last_end < 0:
        return None
    return last_user > last_end


_context_cache = {}


def last_context(path, window=TAIL_WINDOW):
    """{"token": context size of the newest model call (input + cache read + cache creation tokens), "zaman": its
    time (epoch seconds) or None} from the transcript's tail; None when no call is found. Cached by (inode, size,
    mtime). Synthetic messages (written by Claude Code itself) are not calls."""
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    key = (st.st_ino, st.st_size, st.st_mtime_ns)
    hit = _context_cache.get(path)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(path, "rb") as f:
            f.seek(max(0, st.st_size - window))
            data = f.read(window)
    except OSError:
        return None
    found = None
    for line in reversed(data.split(b"\n")):
        if b'"assistant"' not in line or b'"usage"' not in line:
            continue
        try:
            record = _parse(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message")
        if record.get("type") != "assistant" or not isinstance(message, dict) or \
                message.get("model") == "<synthetic>" or not isinstance(message.get("usage"), dict):
            continue
        usage = message["usage"]
        tokens = sum(v for v in (usage.get(k) for k in ("input_tokens", "cache_read_input_tokens",
                                                         "cache_creation_input_tokens")) if isinstance(v, int))
        when = parse_time(record.get("timestamp"))
        found = {"token": tokens, "zaman": when.timestamp() if when else None}
        break
    if len(_context_cache) > 64:
        _context_cache.clear()
    _context_cache[path] = (key, found)
    return found


def first_time(path, head=HEAD_BYTES):
    """Epoch seconds of the first timestamped record in the transcript's head (when the session began), else None."""
    try:
        with open(path, "rb") as f:
            data = f.read(head)
    except (OSError, TypeError, ValueError):
        return None
    for line in data.split(b"\n"):
        if b'"timestamp"' not in line:
            continue
        try:
            record = _parse(line)
        except ValueError:
            continue
        when = parse_time(record.get("timestamp")) if isinstance(record, dict) else None
        if when:
            return when.timestamp()
    return None


def _advisor_iterations(usage):
    """(count, tokens, list-price usd) of the advisor sub-inferences in a call's usage.iterations (type
    advisor_message, priced at its own model); (0, 0, 0.0) when there are none."""
    n, tokens, cost = 0, 0, 0.0
    items = usage.get("iterations") if isinstance(usage, dict) else None
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or it.get("type") != "advisor_message":
            continue
        n += 1
        tokens += sum(v for v in (it.get(k) for k in USAGE_FIELDS) if isinstance(v, int) and v >= 0)
        priced = pricing.call_cost(it.get("model"), it)
        cost += priced["total"] if priced else 0.0
    return n, tokens, cost


class SessionTranscript:
    """Incremental view of one transcript file."""

    def __init__(self, path, with_chat=False):
        self.path = path
        self.with_chat = with_chat
        self._reset()

    def _reset(self):
        self.offset = 0
        self._partial = b""
        self._inode = None
        self.usage_by_date = {}
        self.fields_by_date = {}      # day -> {usage field -> tokens}
        self.calls_by_date = {}       # day -> number of model calls (distinct message ids)
        self.tool_tokens_by_date = {} # day -> {tool name -> tokens of the calls that used it}
        self.model_by_date = {}       # day -> {model -> {"total", "calls", "cost"}}
        self.cost_by_date = {}        # day -> {usage field -> usd, "total": usd} (list-price estimate)
        self.tool_cost_by_date = {}   # day -> {tool name -> usd}
        self.unpriced_by_date = {}    # day -> calls of models without a known price
        self._msg_cost = {}           # message id -> usd, for attributing a call's cost to its tool
        self.calls_by_msg = {}        # message id -> usd of the call, None when unpriced (cross-file de-dup)
        self.anon_calls = self.anon_unpriced = 0  # calls without a message id (never de-duplicated)
        self.anon_cost = 0.0
        self.tokens_by_msg = {}       # message id -> tokens of the call (input + output + cache read + cache creation)
        self.anon_tokens = 0          # tokens of the calls without a message id
        self._msg_usage = {}          # message id -> (day, total), for attributing a call to its tool
        # the advisor tool (bin/danisman.py): its calls (server_tool_use "advisor", by block id), its error results
        # (advisor_tool_result_error: tool_use_id -> error_code) and the priced advisor sub-inferences per call
        # (usage.iterations entries of type advisor_message; their tokens and cost are added to the call's, since the
        # top-level usage holds the main model's tokens only)
        self.advisor_calls = set()
        self.advisor_errors = {}
        self.advisor_iter_by_msg = {}
        self.anon_advisor_iter = 0
        self._attributed = set()
        self._seen_ids = set()
        self.last_tool = None
        self.last_time = None
        self.chat = []
        self.chat_total = 0  # grows monotonically (also counts lines trimmed from self.chat)

    def poll(self):
        """Reads appended bytes. Returns True when anything new was parsed."""
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        if self._inode is not None and (st.st_ino != self._inode or st.st_size < self.offset):
            self._reset()  # replaced or truncated: start over
        self._inode = st.st_ino
        if st.st_size == self.offset:
            return False
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read(MAX_READ)
        except OSError:
            return False
        self.offset += len(data)
        data = self._partial + data
        lines = data.split(b"\n")
        self._partial = lines.pop()
        changed = False
        for line in lines:
            if not line.strip() or not RECORD_KIND.search(line):
                continue  # most bytes are attachment / api-request records; skip them unparsed
            try:
                record = _parse(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                self._consume(record)
                changed = True
        return changed

    def _consume(self, record):
        kind = record.get("type")
        if kind not in ("user", "assistant"):
            return
        when = parse_time(record.get("timestamp"))
        if when:
            self.last_time = when
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        if kind == "assistant":
            msg_id = message.get("id")
            usage = message.get("usage")
            synthetic = message.get("model") == "<synthetic>"  # written by Claude Code itself, not a model call
            if isinstance(usage, dict) and when and not synthetic and (msg_id is None or msg_id not in self._seen_ids):
                if msg_id is not None:
                    self._seen_ids.add(msg_id)
                total = sum(v for v in (usage.get(k) for k in USAGE_FIELDS) if isinstance(v, int))
                adv_n, adv_tokens, adv_cost = _advisor_iterations(usage)
                total += adv_tokens
                day = when.date().isoformat()
                self.usage_by_date[day] = self.usage_by_date.get(day, 0) + total
                fields = self.fields_by_date.setdefault(day, dict.fromkeys(USAGE_FIELDS, 0))
                for k in USAGE_FIELDS:
                    if isinstance(usage.get(k), int):
                        fields[k] += usage[k]
                self.calls_by_date[day] = self.calls_by_date.get(day, 0) + 1
                model = str(message.get("model") or "bilinmiyor")[:60]
                per_model = self.model_by_date.setdefault(day, {}).setdefault(model, {"total": 0, "calls": 0, "cost": 0.0})
                per_model["total"] += total
                per_model["calls"] += 1
                cost = pricing.call_cost(message.get("model"), usage)
                if cost is not None and adv_cost:
                    cost = {**cost, "total": cost["total"] + adv_cost}  # the advisor's share: in the total only
                if adv_n:
                    if msg_id is not None:
                        self.advisor_iter_by_msg[msg_id] = adv_n
                    else:
                        self.anon_advisor_iter += adv_n
                if msg_id is not None:
                    self.calls_by_msg[msg_id] = None if cost is None else cost["total"]
                    self.tokens_by_msg[msg_id] = total
                else:
                    self.anon_tokens += total
                    self.anon_calls += 1
                    if cost is None:
                        self.anon_unpriced += 1
                    else:
                        self.anon_cost += cost["total"]
                if cost is None:
                    per_model["cost"] = None
                    self.unpriced_by_date[day] = self.unpriced_by_date.get(day, 0) + 1
                else:
                    if per_model["cost"] is not None:
                        per_model["cost"] += cost["total"]
                    day_cost = self.cost_by_date.setdefault(day, dict.fromkeys((*USAGE_FIELDS, "total"), 0.0))
                    for k in day_cost:
                        day_cost[k] += cost[k]
                    if msg_id is not None:
                        self._msg_cost[msg_id] = cost["total"]
                if msg_id is not None:
                    self._msg_usage[msg_id] = (day, total)
            for part in message.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "server_tool_use" and part.get("name") == "advisor":
                    self.advisor_calls.add(str(part.get("id") or f"{msg_id}:{len(self.advisor_calls)}")[:100])
                elif isinstance(part, dict) and part.get("type") == "advisor_tool_result":
                    body = part.get("content") if isinstance(part.get("content"), dict) else {}
                    if body.get("type") == "advisor_tool_result_error":
                        code = str(body.get("error_code") or "bilinmiyor")
                        code = code if re.fullmatch(r"[a-z_]{1,40}", code) else "bilinmiyor"
                        self.advisor_errors[str(part.get("tool_use_id") or len(self.advisor_errors))[:100]] = code
                if isinstance(part, dict) and part.get("type") == "tool_use" and isinstance(part.get("name"), str):
                    # a call's tokens go to the first tool it used (streamed chunks share the message id)
                    if msg_id in self._msg_usage and msg_id not in self._attributed:
                        self._attributed.add(msg_id)
                        day, total = self._msg_usage[msg_id]
                        tools = self.tool_tokens_by_date.setdefault(day, {})
                        name = part["name"][:TARGET_LEN]
                        tools[name] = tools.get(name, 0) + total
                        if msg_id in self._msg_cost:
                            tool_cost = self.tool_cost_by_date.setdefault(day, {})
                            tool_cost[name] = tool_cost.get(name, 0.0) + self._msg_cost[msg_id]
                    self.last_tool = {"name": part["name"][:TARGET_LEN],
                                      "target": tool_target(part["name"], part.get("input")),
                                      "time": record.get("timestamp")}
        if self.with_chat:
            lines = chat_lines(record)
            self.chat.extend(lines)
            self.chat_total += len(lines)
            if len(self.chat) > MAX_CHAT:
                del self.chat[:len(self.chat) - MAX_CHAT]

    def tokens_on(self, day):
        return self.usage_by_date.get(day, 0)

    def cost_on(self, day):
        """List-price estimate (USD) of `day`'s calls whose model has a known price."""
        return self.cost_by_date.get(day, {}).get("total", 0.0)

    def breakdown_on(self, day):
        """Tokens of `day` by usage field and by tool; `other` = calls that used no tool (replies, thinking)."""
        total = self.usage_by_date.get(day, 0)
        by_tool = dict(self.tool_tokens_by_date.get(day, {}))
        return {"total": total, "fields": dict(self.fields_by_date.get(day, dict.fromkeys(USAGE_FIELDS, 0))),
                "calls": self.calls_by_date.get(day, 0), "by_tool": by_tool,
                "by_model": {m: dict(v) for m, v in self.model_by_date.get(day, {}).items()},
                "cost": dict(self.cost_by_date.get(day, dict.fromkeys((*USAGE_FIELDS, "total"), 0.0))),
                "cost_by_tool": dict(self.tool_cost_by_date.get(day, {})),
                "cost_other": self.cost_by_date.get(day, {}).get("total", 0.0)
                - sum(self.tool_cost_by_date.get(day, {}).values()),
                "unpriced_calls": self.unpriced_by_date.get(day, 0),
                "other": total - sum(by_tool.values())}


class TranscriptCache:
    """Keeps one SessionTranscript per path so every poll is incremental."""

    def __init__(self, projects_dir):
        self.projects_dir = projects_dir
        self._files = {}

    def get(self, cwd, session_id, with_chat=False):
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id) or not isinstance(cwd, str):
            return None
        path = transcript_path(self.projects_dir, cwd, session_id)
        if forbidden_folder(os.path.dirname(path)):
            return None
        st = self._files.get(path)
        if st is None or (with_chat and not st.with_chat):
            st = SessionTranscript(path, with_chat=with_chat)
            self._files[path] = st
        st.poll()
        return st
