"""Delivery of messages to one named background session: the CEO or a project session.

A Channel delivers to the session `name` whose cwd is `root`. Its full sessionId is kept in a small record file
(explicit identity — never "the latest session"). deliver(text) / drain_once():
- no session yet              -> start a background session named <name> with the text (only when allow_start;
                                 a project session is never started here: that would be a session without a task),
- recorded but not running    -> resume it in the background with the text when its transcript exists, else as above,
- running and idle            -> `claude stop <short id>`, wait until it is gone, then resume with the text,
- running and busy            -> append to the queue file; drain_once() delivers one queued message per idle
                                 transition, removing it once claude accepted it,
- running and waiting         -> (a permission prompt) like busy: queued, never stopped or resumed; last_error says
                                 so ("<label> bir izin sorusunda bekliyor; mesajlar kuyrukta") until it moves on.
"Idle" needs both `claude agents` (re-checked right before `stop`) and a closed turn in the transcript tail. A busy
session, or one still listed after `stop`, is never resumed (that would start a copy). Right after a delivery the
session is treated as busy for a grace period until `claude agents` reports it busy.
Forks (project sessions only, follow_forks): Claude Code 2.1.322 continues a resumed project session in a NEW
transcript (new session id, same agent name, starting with a copy of the earlier history) while `claude agents` keeps
listing the OLD id (status None). After every resume the channel finds the new id (_follow_fork), records it with all
earlier ids (`session_ids` in its record) and tells the post office (on_session), so the next resume, the dormant
check and the job's metering use the newest id. The check right after the resume is a single look (no polling under
the lock); a fork that shows up later is found by the post office's active check (_discover_sessions). A listed entry of an earlier id counts only when it says busy or
idle; while a forked session is not listed, an open turn in its newest transcript means busy. The CEO session does
not fork (it is resumed without extra options) and keeps the old behaviour.
Copies (claude 2.1.325, 2026-11-15): when claude says it "started a copy" instead of resuming, a copy of a session
that was still running (e.g. a fresh session `claude agents` did not yet list as live) is stopped at once — only that
copy, which the office itself just made — and the message stays queued; the channel then counts the session busy for
COPY_HOLD_SECONDS. A copy of a stopped session made because resume flags were passed is the session going on (a fork).
A launch that exits 0 counts as delivered even when its output is not the expected launch line (warning in
last_error, with a short masked tail of claude's output — claude_cli.launch_tail — also written once to `log`, so a new
CLI format can be seen later). That warning is cleared by the next confirmed delivery and by a confirmed fork (the
session went on under a new id: the message arrived), here in follow(); the post office also clears it once the job
is final. A launch that times out is ambiguous: it is never re-sent; it is logged in the unconfirmed file and
reported in last_error.
enqueue(text, key) queues a message under an explicit key at most once: a key that is queued, or that was delivered
(the sent log survives restarts), is not queued again. The post office relies on this for idempotency.
Each sent-log line is `<key>\t<local time of the delivery>` (older lines: the key only); sent_times() reads them back
for the page's per-job progress line (bin/state.py is_yolu).
"""
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime

import claude_cli
import transcript

GRACE_SECONDS = 25.0
COPY_HOLD_SECONDS = 120.0  # after claude made a copy of a still-running session: counted busy this long
RETRY_SECONDS = 10.0
STALE_TURN_SECONDS = 60.0  # an open turn with no transcript writes for this long was interrupted, not running
SESSION_NAME = re.compile(r"ofis-[a-z0-9-]{1,80}")
MAX_SENT_LOG = 1000
HOLD_STATES = ("busy", "waiting")  # a message is queued, never delivered, while the session is in one of these
WAITING_TEXT = "{label} bir izin sorusunda bekliyor; mesajlar kuyrukta"
UNCONFIRMED_LAUNCH = "without the expected launch line"
FORK_SLACK = 1.0  # seconds: a transcript written this long before the resume still counts as written after it


def is_launch_warning(text):
    """True for the last_error of a delivery whose launch line was not recognised (delivered, not confirmed)."""
    return isinstance(text, str) and text.startswith("warning: ") and UNCONFIRMED_LAUNCH in text


class ChannelUnavailable(Exception):
    """The session could not be started or reached."""


class _Busy(Exception):
    """The session turned out to be busy right before `stop`; the message must be queued."""


def _live(agents):
    """The rows of `claude agents --json` that describe a running process. A finished background job keeps a row
    with neither pid nor status (e.g. "state": "blocked" after a turn that ended with a question to the user); that
    session is not running and is resumed like a dormant one (seen live 2026-11-11)."""
    return [a for a in agents if a.get("status") is not None or a.get("pid") is not None]


def _same_dir(a, b):
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


class Channel:
    def __init__(self, cli, root, name, durum_dir, projects_dir, clock=time.monotonic, sleep=time.sleep,
                 grace=GRACE_SECONDS, find_attempts=20, wallclock=time.time, id_file=None, queue_file=None,
                 unconfirmed_file=None, sent_file=None, allow_start=True, label=None):
        self.cli = cli
        self.root = root
        self.name = name
        self.durum_dir = durum_dir
        self.projects_dir = projects_dir
        self.clock = clock
        self.sleep = sleep
        self.grace = grace
        self.find_attempts = find_attempts
        self.wallclock = wallclock
        self.id_file = id_file or os.path.join(durum_dir, f"{name}.json")
        self.queue_file = queue_file or os.path.join(durum_dir, f"{name}.jsonl")
        self.unconfirmed_file = unconfirmed_file or os.path.join(durum_dir, f"{name}-unconfirmed.jsonl")
        self.sent_file = sent_file or os.path.join(durum_dir, f"{name}-sent.txt")
        self.allow_start = allow_start
        self.label = label or name
        self.resume_args = None  # project sessions: options every resume carries (see launch.resume_flags)
        self.follow_forks = False  # project sessions: a resume may continue under a new session id (see _follow_fork)
        self.on_session = None  # called (session id, every id seen) when a resume moved the session to a new id
        self.start_args = None   # options used when this channel starts its session (the CEO's system prompt)
        self._lock = threading.RLock()  # serialises deliveries; status() never takes it
        self._delivering = False
        self._handled = set()  # keys of queued items claude accepted (or that timed out): never sent again
        self._delivered_at = None
        self._seen_busy = False
        self._copy_hold_until = None
        self._retry_after = 0.0
        self.last_error = None
        self.log = None  # optional callable(text): the post office's log (an unrecognised launch's output)

    # --- persistence ---

    def _read_record(self):
        try:
            with open(self.id_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_record(self, record):
        """Writes the record; a new session_id is appended to `session_ids` (every id the session ever had)."""
        sid = record.get("session_id")
        if transcript.valid_session_id(sid):
            ids = self.known_ids()
            record = dict(record, session_ids=ids + ([sid] if sid not in ids else []))
        os.makedirs(os.path.dirname(self.id_file), exist_ok=True)
        tmp = f"{self.id_file}.{threading.get_ident()}.tmp"  # status() may write it while a delivery runs
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.id_file)

    def session_id(self):
        sid = self._read_record().get("session_id")
        return sid if transcript.valid_session_id(sid) else None

    def known_ids(self):
        """Every session id recorded for this session, oldest first (the current one last)."""
        record = self._read_record()
        ids = [i for i in record.get("session_ids") or [] if transcript.valid_session_id(i)]
        sid = record.get("session_id")
        if transcript.valid_session_id(sid) and sid not in ids:
            ids.append(sid)
        return ids

    def follow(self, sid):
        """Records `sid` as the session's current id (a newer transcript of the same session). Returns True when
        it changed."""
        if not transcript.valid_session_id(sid) or sid == self.session_id():
            return False
        self._write_record({"session_id": sid, "name": self.name, "cwd": self.root,
                            "recorded_at": datetime.now().isoformat(timespec="seconds")})
        self.clear_launch_warning()  # the session went on under a new id: the unconfirmed message arrived
        return True

    def clear_launch_warning(self):
        """Drops a warning about an unrecognised launch line (never a real error)."""
        if is_launch_warning(self.last_error):
            self.last_error = None

    def queue(self):
        """Queued items, oldest first. Unreadable lines are skipped (and dropped on the next rewrite)."""
        try:
            with open(self.queue_file, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        items = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                items.append(item)
        return items

    @staticmethod
    def _key(item):
        return item.get("id") or json.dumps(item, sort_keys=True, ensure_ascii=False)

    def _pending(self):
        return [i for i in self.queue() if self._key(i) not in self._handled]

    def pending(self):
        return len(self._pending())

    def _append_queue(self, text, key=None):
        os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
        item = {"id": key or secrets.token_hex(8), "text": text,
                "queued_at": datetime.now().isoformat(timespec="seconds")}
        if key:
            item["keyed"] = True
        with open(self.queue_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _drop_delivered(self, item):
        self._handled.add(self._key(item))
        if item.get("keyed"):
            self._log_sent(self._key(item))
        self._rewrite_queue()

    def _rewrite_queue(self):
        """Rewrites the queue file with the pending items only (no handled items, no unreadable lines)."""
        items = self._pending()
        tmp = self.queue_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for i in items:
                f.write(json.dumps(i, ensure_ascii=False) + "\n")
        os.replace(tmp, self.queue_file)

    def _sent_lines(self):
        try:
            with open(self.sent_file, encoding="utf-8") as f:
                return f.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return []

    def _sent_keys(self):
        return [line.split("\t", 1)[0] for line in self._sent_lines()]

    def sent_times(self):
        """{key: local delivery time "YYYY-MM-DDTHH:MM:SS"} of the sent log; "" for a line written before times were
        kept. A key delivered twice (never by design) keeps its first time."""
        out = {}
        for line in self._sent_lines():
            key, _, when = line.partition("\t")
            out.setdefault(key, when)
        return out

    def _log_sent(self, key):
        os.makedirs(os.path.dirname(self.sent_file), exist_ok=True)
        lines = self._sent_lines()
        if len(lines) >= MAX_SENT_LOG:
            tmp = self.sent_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("".join(k + "\n" for k in lines[-MAX_SENT_LOG // 2:]))
            os.replace(tmp, self.sent_file)
        with open(self.sent_file, "a", encoding="utf-8") as f:
            f.write(f"{key}\t{datetime.now():%Y-%m-%dT%H:%M:%S}\n")

    def was_sent(self, key):
        """True once a message queued under `key` was delivered (or its delivery timed out: never re-sent)."""
        return key in self._sent_keys()

    def _log_unconfirmed(self, text, reason):
        try:
            os.makedirs(os.path.dirname(self.unconfirmed_file), exist_ok=True)
            with open(self.unconfirmed_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"text": text, "reason": reason,
                                    "at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
        except OSError:
            pass  # last_error still reports it

    # --- identity ---

    def _matches(self, agent):
        return agent.get("name") == self.name and _same_dir(agent.get("cwd"), self.root)

    def adopt(self, short_id):
        """Records the full session id of an existing session: by name + cwd in `claude agents` (prefix-checked
        against short_id when it looks like one), else by a unique transcript file starting with short_id in the
        session's project folder. Returns True when an id is recorded (already or now)."""
        if self.session_id():
            return True
        short = short_id if transcript.valid_session_id(short_id) and len(short_id) >= 8 else None
        try:
            agents = self.cli.agents(fresh=True)
        except claude_cli.ClaudeError:
            agents = []
        found = [a["sessionId"] for a in agents if self._matches(a) and transcript.valid_session_id(a.get("sessionId"))
                 and (short is None or a["sessionId"].startswith(short))]
        if len(found) != 1 and short:
            folder = transcript.project_folder(self.projects_dir, self.root)
            try:
                found = [n[:-6] for n in os.listdir(folder) if n.startswith(short) and n.endswith(".jsonl")
                         and transcript.valid_session_id(n[:-6])]
            except OSError:
                found = []
        if len(found) != 1:
            return False
        self._write_record({"session_id": found[0], "name": self.name, "cwd": self.root,
                            "recorded_at": datetime.now().isoformat(timespec="seconds")})
        return True

    # --- status ---

    def _resolve(self, agents):
        """Returns (session_id, agent or None). Upgrades a pending short id or adopts a unique running session."""
        record = self._read_record()
        sid = record.get("session_id") if transcript.valid_session_id(record.get("session_id")) else None
        if sid:
            agent = next((a for a in agents if a.get("sessionId") == sid), None)
            return sid, agent if agent is not None else self._stale_agent(agents, sid)
        short = record.get("short_id")
        candidates = [a for a in agents if self._matches(a) and transcript.valid_session_id(a.get("sessionId"))]
        if transcript.valid_session_id(short):
            candidates = [a for a in candidates if a["sessionId"].startswith(short)]
        if len(candidates) == 1:
            agent = candidates[0]
            self._write_record({"session_id": agent["sessionId"], "name": self.name, "cwd": self.root,
                                "recorded_at": datetime.now().isoformat(timespec="seconds")})
            return agent["sessionId"], agent
        return None, None

    def _stale_agent(self, agents, sid):
        """After a fork `claude agents` keeps listing the session under an OLD id (status None). Such an entry of an
        earlier id of this session counts only when it says busy or idle."""
        if not self.follow_forks:
            return None
        old = set(self.known_ids()) - {sid}
        listed = [a for a in agents if a.get("sessionId") in old and self._matches(a)
                  and a.get("status") in ("busy", "idle")]
        listed.sort(key=lambda a: a.get("status") != "busy")
        return listed[0] if listed else None

    def _status(self, fresh=False):
        try:
            agents = _live(self.cli.agents(fresh=fresh))
        except claude_cli.ClaudeError as e:
            raise ChannelUnavailable(str(e)) from e
        sid, agent = self._resolve(agents)
        in_grace = (self._delivered_at is not None and not self._seen_busy
                    and self.clock() - self._delivered_at < self.grace)
        if agent is not None and agent.get("status") == "busy":
            self._seen_busy = True
            state = "busy"
        elif agent is not None and agent.get("status") == "waiting":
            state = "waiting"  # at a permission prompt: never stopped, never delivered into (it is not idle)
        elif in_grace or (self._copy_hold_until is not None and self.clock() < self._copy_hold_until):
            state = "busy"  # just delivered (or claude just showed it still runs); `claude agents` has not caught up
        elif agent is not None:
            state = "idle"
        elif sid and os.path.isfile(transcript.transcript_path(self.projects_dir, self.root, sid)):
            state = "dormant"
        else:
            state = "absent"
        return {"state": state, "session_id": sid, "agent": agent}

    def _turn_open(self, sid):
        """True when the transcript shows a turn that is still running (and was written to recently)."""
        path = transcript.transcript_path(self.projects_dir, self.root, sid)
        if not transcript.turn_open(path):
            return False
        try:
            quiet = self.wallclock() - os.stat(path).st_mtime
        except OSError:
            return False
        return quiet < STALE_TURN_SECONDS

    def _ready_status(self):
        """Fresh status for a delivery: an idle session whose transcript shows an open turn counts as busy."""
        st = self._status(fresh=True)
        if st["state"] == "idle" and self._turn_open(st["session_id"]):
            st["state"] = "busy"
        elif st["state"] == "dormant" and self._forked() and self._turn_open(st["session_id"]):
            st["state"] = "busy"  # a forked session is not listed under its new id: its transcript is the signal
        return st

    def _forked(self):
        return self.follow_forks and len(self.known_ids()) > 1

    def status(self):
        """Public status: state is busy, waiting (a permission prompt), idle, dormant (stopped, resumable) or absent.

        Never takes the delivery lock (a delivery can take a minute); during a delivery the state is busy."""
        try:
            st = self._status()
        except ChannelUnavailable as e:
            st = {"state": "unknown", "session_id": self.session_id(), "error": str(e)}
        if self._delivering:
            st["state"] = "busy"
        st.pop("agent", None)
        st["queue"] = len(self._pending())
        return st

    # --- delivery ---

    def _start(self, text):
        """Starts the session. Returns a warning (str) when claude accepted the message but did not confirm it."""
        try:
            before = {a.get("sessionId") for a in self.cli.agents(fresh=True)}
        except claude_cli.ClaudeError:
            before = set()
        if self.start_args:
            result = self.cli.start_bg(self.name, text, self.root, extra=self.start_args)
        else:
            result = self.cli.start_bg(self.name, text, self.root)
        short, printed = result
        if short is None:
            return self._launch_warning(f"claude started the {self.label} session {UNCONFIRMED_LAUNCH}; its id is "
                                        "resolved from `claude agents`", result)
        if printed != self.name:
            return f"claude reported session '{printed}' instead of '{self.name}'; check `claude agents`"
        self._write_record({"short_id": short, "name": self.name, "cwd": self.root})
        for _ in range(self.find_attempts):
            try:
                agents = self.cli.agents(fresh=True)
            except claude_cli.ClaudeError:
                agents = []
            found = [a for a in agents if self._matches(a) and a.get("sessionId") not in before
                     and transcript.valid_session_id(a.get("sessionId")) and a["sessionId"].startswith(short)]
            if len(found) == 1:
                self._write_record({"session_id": found[0]["sessionId"], "name": self.name, "cwd": self.root,
                                    "recorded_at": datetime.now().isoformat(timespec="seconds")})
                return None
            self.sleep(0.5)
        return None  # delivered; the full id is resolved later from the recorded short id

    def _resume(self, sid, text):
        started = self.wallclock()
        warning = self._resume_bg(sid, text)
        if self.follow_forks:
            before = self.session_id()
            fork_warning = self._follow_fork(sid, started)
            if self.session_id() != before and warning and UNCONFIRMED_LAUNCH in warning:
                warning = None  # a confirmed fork: the session went on with the message
            warning = fork_warning or warning
        return warning

    def _follow_fork(self, previous, started):
        """Claude Code 2.1.322 continues a resumed project session in a NEW transcript in the same folder (same
        agent name, a copy of the earlier history first) while `claude agents` keeps listing the old id. Finds the
        session's current id: a transcript named like the session, written since the resume and not one of its known
        ids (one immediate check, no polling: this runs under the channel lock on the post office thread), else
        `claude agents` by name + cwd. A fork whose transcript appears later is found by the post office
        (PostOffice._discover_sessions, every active check) and followed with follow(). Records it (and calls
        on_session). Returns a warning or None."""
        known = set(self.known_ids()) | {previous}
        found = None
        new = [(sid, born) for sid, born in transcript.named_sessions(self.projects_dir, self.root, self.name,
                                                                      since=started - FORK_SLACK)
               if sid not in known]
        if new:
            found = max(new, key=lambda x: (x[1], x[0]))[0]
        if found is None:
            try:
                agents = self.cli.agents(fresh=True)
            except claude_cli.ClaudeError:
                agents = []
            listed = {a["sessionId"] for a in agents if self._matches(a)
                      and transcript.valid_session_id(a.get("sessionId"))}
            if len(listed) == 1 and not listed & known:
                found = next(iter(listed))
        if found is None or not self.follow(found):
            return None
        if self.on_session:
            try:
                self.on_session(found, self.known_ids())
            except Exception as e:  # the delivery itself succeeded; the record is fixed by the next active check
                return f"session moved to {found[:8]} but the job record was not updated ({type(e).__name__}: {e})"
        return None

    def _resume_bg(self, sid, text):
        if self.resume_args:
            result = self.cli.resume_bg(sid, text, self.root, extra=self.resume_args)
        else:
            result = self.cli.resume_bg(sid, text, self.root)
        short, printed = result
        kopya = getattr(result, "kopya", None)
        if kopya and getattr(result, "kopya_nedeni", None) == "calisiyor":
            # the session was still running (e.g. a fresh session `claude agents` did not list as live yet): two
            # sessions would now answer the same message. The office stops only the copy it just made and keeps the
            # message queued for the original (2026-11-15).
            try:
                self.cli.stop(kopya[:8])
                stopped = "stopped"
            except claude_cli.ClaudeError as e:
                stopped = f"NOT stopped ({e}); stop it by hand"
            if self.log:
                try:
                    self.log(f"{self.name}: claude started a copy {kopya[:8]} of a session that was still running; "
                             f"copy {stopped}, message kept queued")
                except Exception:  # noqa: BLE001
                    pass
            self._copy_hold_until = self.clock() + COPY_HOLD_SECONDS  # never a copy every pass
            raise _Busy()
        if kopya:
            # the original was stopped; the copy goes on with the message (a fork: follow_forks finds its id)
            return None if self.follow_forks else (f"claude continued the {self.label} session as a copy "
                                                   f"{kopya[:8]}; check `claude agents`")
        if short is None:
            return self._launch_warning(f"claude resumed the {self.label} session {UNCONFIRMED_LAUNCH}", result)
        if printed != self.name:
            return f"claude resumed session '{printed}' instead of '{self.name}'; check `claude agents`"
        return None

    def _launch_warning(self, sentence, result):
        """The warning of an unrecognised launch with claude's masked output tail; logged once."""
        tail = getattr(result, "tail", "")
        warning = f"{sentence}; output: {tail}" if tail else sentence
        if self.log:
            try:
                self.log(f"{self.name}: launch unconfirmed: {warning}")
            except Exception:  # the delivery itself succeeded
                pass
        return warning

    def _stop_idle(self, sid):
        """Stops the idle session so it can be resumed. Raises _Busy if it became busy, ChannelUnavailable if it
        stays listed."""
        agents = _live(self.cli.agents(fresh=True))
        agent = next((a for a in agents if a.get("sessionId") == sid), None)
        if agent is None:
            agent = self._stale_agent(agents, sid)
        if agent is not None and agent.get("status") != "idle":
            raise _Busy()
        target = agent.get("sessionId") if agent is not None else sid
        if agent is not None:
            self.cli.stop(target[:8])
        for _ in range(self.find_attempts):
            if not any(a.get("sessionId") == target and (target == sid or a.get("status") is not None)
                       for a in self.cli.agents(fresh=True)):
                return
            self.sleep(0.25)
        raise ChannelUnavailable(f"the {self.label} session is still running after `claude stop`; not resuming "
                                 "(it would be a copy)")

    def _send(self, text, st):
        """Delivers text. Returns None or a warning; raises _Busy, ChannelUnavailable or claude_cli.ClaudeTimeout."""
        launched = False
        try:
            if st["state"] == "absent":
                if not self.allow_start:
                    raise ChannelUnavailable(f"session {self.name} not found (no running session and no transcript); "
                                             "a project session is never started by the office server")
                launched = True
                warning = self._start(text)
            elif st["state"] == "dormant":
                launched = True
                warning = self._resume(st["session_id"], text)
            elif st["state"] == "idle":
                self._stop_idle(st["session_id"])
                launched = True
                warning = self._resume(st["session_id"], text)
            else:
                raise ChannelUnavailable(f"cannot deliver while the {self.label} session is {st['state']}")
        except claude_cli.ClaudeTimeout:
            if launched:
                self._delivered_at, self._seen_busy = self.clock(), False  # it may be running now
                raise
            self.last_error = "claude timed out before the message was sent"
            raise ChannelUnavailable(self.last_error)
        except claude_cli.ClaudeError as e:
            self.last_error = str(e)
            raise ChannelUnavailable(str(e)) from e
        except ChannelUnavailable as e:
            self.last_error = str(e)
            raise
        self._delivered_at = self.clock()
        self._seen_busy = False
        self.last_error = f"warning: {warning}" if warning else None
        return warning

    def _note_waiting(self, st):
        """A session at a permission prompt keeps its messages queued; say so (shown on the page), and clear that
        line again once it moved on."""
        if st["state"] == "waiting":
            self.last_error = WAITING_TEXT.format(label=self.label)
        elif self.last_error == WAITING_TEXT.format(label=self.label):
            self.last_error = None

    def _unconfirmed(self, text, error):
        self._log_unconfirmed(text, str(error))
        where = os.path.relpath(self.unconfirmed_file, os.path.dirname(self.durum_dir))
        self.last_error = (f"delivery unconfirmed ({error}); not re-sent — check the {self.label} chat and resend if "
                           f"it did not arrive (logged in {where})")
        return self.last_error

    @staticmethod
    def _check_text(text):
        if not isinstance(text, str) or not text.strip() or text.lstrip().startswith("-"):
            raise ValueError("text must be non-empty and must not start with '-'")

    def deliver(self, text):
        """Delivers now or queues. Returns "delivered" or "queued"; raises ChannelUnavailable."""
        self._check_text(text)
        with self._lock:
            self._delivering = True
            try:
                st = self._ready_status()
                self._note_waiting(st)
                if st["state"] not in HOLD_STATES and not self._pending():
                    try:
                        self._send(text, st)
                        return "delivered"
                    except _Busy:
                        pass
                    except claude_cli.ClaudeTimeout as e:
                        raise ChannelUnavailable(self._unconfirmed(text, e)) from e
                self._append_queue(text)  # busy, or keep order: never overtake queued messages
                return "queued"
            finally:
                self._delivering = False

    def enqueue(self, text, key):
        """Queues text under `key` unless that key is queued or was delivered. Returns "queued" or "duplicate".
        Delivery happens in drain_once()."""
        self._check_text(text)
        if not isinstance(key, str) or not key or "\n" in key or "\t" in key:
            raise ValueError("key must be a single-line string without tabs")
        with self._lock:
            if key in self._handled or any(self._key(i) == key for i in self.queue()) or self.was_sent(key):
                return "duplicate"
            self._append_queue(text, key)
            return "queued"

    def drop_pending(self, keys=None):
        """Removes queued messages without delivering them (all, or only `keys`); they are never sent later.
        Returns how many were dropped. Used when the job of a project session is no longer running."""
        with self._lock:
            items = [i for i in self._pending() if keys is None or self._key(i) in keys]
            if not items:
                return 0
            self._handled.update(self._key(i) for i in items)
            self._rewrite_queue()
            return len(items)

    def drain_once(self):
        """Delivers the oldest queued message if the session is not busy. Returns True when one was delivered.

        A message is sent at most once: once claude accepted it (or timed out) its key is remembered in memory
        before the queue file is rewritten, so a failed rewrite cannot cause a second delivery."""
        with self._lock:
            queued = self.queue()
            items = [i for i in queued if self._key(i) not in self._handled]
            if len(items) != len(queued):
                self._rewrite_queue()  # finish an earlier failed rewrite
            if not items or self.clock() < self._retry_after:
                return False
            item = items[0]
            self._delivering = True
            try:
                st = self._ready_status()
                self._note_waiting(st)
                if st["state"] in HOLD_STATES:
                    return False
                delivered = True
                try:
                    self._send(item["text"], st)
                except _Busy:
                    return False
                except claude_cli.ClaudeTimeout as e:
                    self._unconfirmed(item["text"], e)
                    delivered = False
            except ChannelUnavailable as e:
                self.last_error = str(e)
                self._retry_after = self.clock() + RETRY_SECONDS
                return False
            finally:
                self._delivering = False
            self._drop_delivered(item)
            return delivered

    def run_drainer(self, stop_event, interval=1.5):
        while not stop_event.wait(interval):
            try:
                self.drain_once()
            except Exception as e:  # keep the thread alive; the error is visible in state
                self.last_error = f"drainer: {type(e).__name__}"


# --- project sessions ---

def project_channel(cli, name, cwd, durum_dir, projects_dir, **kwargs):
    """Channel to project session `name` (cwd = the job's calisma_dizini); files under durum/kuyruk/."""
    if not isinstance(name, str) or not SESSION_NAME.fullmatch(name):
        raise ValueError(f"invalid session name: {name!r}")
    folder = os.path.join(durum_dir, "kuyruk")
    ch = Channel(cli, cwd, name, durum_dir, projects_dir, id_file=os.path.join(folder, f"{name}.json"),
                 queue_file=os.path.join(folder, f"{name}.jsonl"),
                 unconfirmed_file=os.path.join(folder, f"{name}-unconfirmed.jsonl"),
                 sent_file=os.path.join(folder, f"{name}-sent.txt"), allow_start=False, label=name, **kwargs)
    ch.follow_forks = True
    return ch


def load_project_channels(cli, durum_dir, projects_dir, **kwargs):
    """Channels recorded under durum/kuyruk/ (after a restart, so leftover queues keep draining)."""
    folder = os.path.join(durum_dir, "kuyruk")
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for file_name in names:
        if not file_name.endswith(".json") or not SESSION_NAME.fullmatch(file_name[:-5]):
            continue
        try:
            with open(os.path.join(folder, file_name), encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            continue
        cwd = record.get("cwd") if isinstance(record, dict) else None
        if record.get("name") != file_name[:-5] or not isinstance(cwd, str) or not os.path.isdir(cwd):
            continue
        out.append(project_channel(cli, file_name[:-5], cwd, durum_dir, projects_dir, **kwargs))
    return out
