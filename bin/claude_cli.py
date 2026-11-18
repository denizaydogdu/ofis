"""Thin wrapper around the `claude` CLI used by the office server.

Every call uses an argument list (no shell), a timeout and the binary found by shutil.which (or an explicit path in
tests). Message text is always a single argv element; callers guarantee it does not start with '-'.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import olaylar
import yasaklar

# The launch line of `claude --bg` (2.1.322: "backgrounded · <short id> · <name>"). 2.1.323 printed something else for
# a resume (2026-11-13; its output was not kept), so a slightly wider form is accepted: ANSI codes anywhere (removed
# first), an optional check mark, "backgrounded" / "resumed" / "started" (any case, optionally "session"), the
# separators · | - : and a hex short id (a session id prefix). The whole line must be exactly that: a random line
# never matches.
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_SEP = r"[ \t]*[·|:\-][ \t]*"
LAUNCH_LINE = re.compile(r"^[ \t]*(?:[✓✔•*>][ \t]*)?(?i:backgrounded|resumed|started)(?:[ \t]+(?i:session))?"
                         + _SEP + r"([0-9a-fA-F]{4,64})" + _SEP + r"([A-Za-z0-9][A-Za-z0-9._-]{0,99})[ \t]*$", re.M)
# Claude 2.1.325 starts a COPY instead of resuming (seen 2026-11-14/15), saying so on stderr:
# - "session <id> is already running in the background, so this started a copy as <id>" — the original still runs;
# - "background session <id> keeps its own saved options, so the flags you passed started a copy as <id>" — the
#   original is stopped and the copy goes on with the message (like the 2.1.322 fork).
COPY_RUNNING = re.compile(r"already running in the background, so this started a copy as ([0-9a-fA-F]{6,64})")
COPY_OPTIONS = re.compile(r"keeps its own saved options, so the flags you passed started a copy as ([0-9a-fA-F]{6,64})")
TAIL_LIMIT = 300  # characters of claude's output kept when the launch line was not recognised


def parse_launch(stdout):
    """(short_id, printed_name) of the launch line in claude's stdout, or (None, None)."""
    match = LAUNCH_LINE.search(ANSI.sub("", stdout or ""))
    return (match.group(1), match.group(2)) if match else (None, None)


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _plain(text):
    """Escape codes and other control characters REMOVED (never rendered: an escape inside a key word such as
    "to<ESC>[0mken=x" must not defeat the mask); line breaks shown as " ⏎ ". Returns (text, had_ansi)."""
    raw = str(text)
    stripped = ANSI.sub("", raw)
    had = stripped != raw or "\x1b" in stripped
    lines = [CONTROL.sub("", line.replace("\t", " ")).rstrip() for line in stripped.strip().splitlines()]
    return " ⏎ ".join(line for line in lines if line), had


def launch_tail(stdout, stderr, limit=TAIL_LIMIT):
    """A short, masked tail of claude's output, at most `limit` characters; "(no output)". Order: strip escape and
    control characters, then mask (olaylar.maskele), then cut — a cut never exposes what the mask would hide."""
    parts, coloured = [], False
    for label, text in (("stdout", stdout), ("stderr", stderr)):
        if text and text.strip():
            plain, had = _plain(text)
            coloured = coloured or had
            if plain:
                parts.append(f"{label}: {plain}")
    text = olaylar.maskele(" · ".join(parts))
    if not text:
        return "(no output)"
    prefix = "(ANSI codes removed) " if coloured else ""
    room = limit - len(prefix)
    return prefix + (text if len(text) <= room else "…" + text[-(room - 1):])


class Launch(tuple):
    """(short_id, printed_name) of a launch; both None when the launch line was not recognised. `tail` is then the
    masked end of claude's output (launch_tail), else "". Compares like a plain tuple."""

    def __new__(cls, short_id, printed_name, tail="", kopya=None, kopya_nedeni=None):
        obj = super().__new__(cls, (short_id, printed_name))
        obj.tail = tail
        obj.kopya = kopya  # the short id of a copy claude started instead of resuming (see COPY_RUNNING)
        obj.kopya_nedeni = kopya_nedeni  # "calisiyor" (the original still runs) or "secenek" (it was stopped)
        return obj


class ClaudeError(Exception):
    """The claude CLI could not be run or returned something unexpected."""


class ClaudeTimeout(ClaudeError):
    """claude did not finish in time. For a launch this is ambiguous: the message may have been delivered."""


class ClaudeCLI:
    def __init__(self, claude_bin=None, cache_seconds=2.0, timeout=60):
        self.claude_bin = claude_bin
        self.cache_seconds = cache_seconds
        self.timeout = timeout
        self._lock = threading.Lock()
        self._cache = None
        self._cache_at = 0.0

    def _bin(self):
        path = self.claude_bin or shutil.which("claude")
        if not path:
            raise ClaudeError("claude executable not found on PATH")
        return path

    def _run(self, args, cwd=None, timeout=None):
        try:
            # OFIS_OTURUMU=1 marks every office session (CEO and projects): the owner's global end-of-turn Codex hook
            # skips them (2026-11-12), the office has its own review panel
            return subprocess.run([self._bin()] + args, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout or self.timeout, stdin=subprocess.DEVNULL,
                                  env=dict(yasaklar.temiz_ortam(), OFIS_OTURUMU="1"))
        except subprocess.TimeoutExpired as e:
            raise ClaudeTimeout(f"claude {args[0]} timed out after {e.timeout} s") from e
        except OSError as e:
            raise ClaudeError(f"could not run claude {args[0]}: {type(e).__name__}") from e

    def agents(self, fresh=False):
        """`claude agents --json`, cached for cache_seconds. Returns a list of dicts."""
        with self._lock:
            now = time.monotonic()
            if not fresh and self._cache is not None and now - self._cache_at < self.cache_seconds:
                return self._cache
            proc = self._run(["agents", "--json"], timeout=20)
            if proc.returncode != 0:
                raise ClaudeError(f"claude agents exited with {proc.returncode}")
            try:
                data = json.loads(proc.stdout)
            except ValueError as e:
                raise ClaudeError("claude agents returned invalid JSON") from e
            if not isinstance(data, list):
                raise ClaudeError("claude agents returned a non-list")
            self._cache = [a for a in data if isinstance(a, dict)]
            self._cache_at = now
            return self._cache

    def invalidate(self):
        with self._lock:
            self._cache = None

    def _check_text(self, text):
        if not isinstance(text, str) or not text.strip() or text.lstrip().startswith("-"):
            raise ClaudeError("message text must be non-empty and must not start with '-'")

    @staticmethod
    def _tail(proc, limit=400):
        """Last part of stdout+stderr, so a failure shows claude's own reason (bounded, single line). Masked before
        it is cut (olaylar.maskele), like launch_tail: a credential claude prints never reaches an error message."""
        output = " | ".join(s.strip() for s in (proc.stdout or "", proc.stderr or "") if s and s.strip())
        output = olaylar.maskele(" ".join(output.split()))
        return output[-limit:] if output else "(no output)"

    def _launched(self, proc):
        """Launch (short_id, printed_name) from the launch line. Exit 0 without that line returns (None, None) with
        the masked output tail: claude accepted the message (only the wording changed), so the caller must count it
        as delivered and should show the tail."""
        if proc.returncode != 0:
            raise ClaudeError(f"claude launch failed (exit {proc.returncode}): {self._tail(proc)}")
        output = ANSI.sub("", f"{proc.stdout or ''}\n{proc.stderr or ''}")
        for pattern, why in ((COPY_RUNNING, "calisiyor"), (COPY_OPTIONS, "secenek")):
            m = pattern.search(output)
            if m:
                return Launch(None, None, launch_tail(proc.stdout, proc.stderr), kopya=m.group(1), kopya_nedeni=why)
        short_id, printed = parse_launch(proc.stdout)
        if short_id is None:
            return Launch(None, None, launch_tail(proc.stdout, proc.stderr))
        return Launch(short_id, printed)

    def start_bg(self, name, text, cwd, extra=None):
        """Starts a new background session; returns (short_id, printed_name) or (None, None), see _launched.
        extra: options placed between the name and the text (e.g. the CEO's --append-system-prompt)."""
        self._check_text(text)
        extra = self._check_extra(extra)
        proc = self._run(["--bg", "--name", name, *extra, text], cwd=cwd)
        self.invalidate()
        return self._launched(proc)

    @staticmethod
    def _check_extra(extra):
        """Extra launch options: a list of strings that starts with an option and ends with a value, so the message
        text after them is never read as an option or as an option's value. A variadic option (--disallowedTools)
        must be followed by another option; the caller builds the list that way."""
        if extra is None:
            return []
        if not isinstance(extra, (list, tuple)) or not extra or \
                not all(isinstance(a, str) and a for a in extra) or \
                not extra[0].startswith("--") or extra[-1].startswith("-"):
            raise ClaudeError("extra options must be a list that starts with an option and ends with a value")
        return list(extra)

    def resume_bg(self, session_id, text, cwd, extra=None):
        """Continues an existing conversation in the background; returns (short_id, printed_name) or (None, None).
        extra: options placed between the session id and the text (a project session's model, effort, permission
        mode, deny rules and contract)."""
        self._check_text(text)
        extra = self._check_extra(extra)
        proc = self._run(["--bg", "--resume", session_id, *extra, text], cwd=cwd)
        self.invalidate()
        return self._launched(proc)

    def stop(self, short_id):
        proc = self._run(["stop", short_id], timeout=30)
        self.invalidate()
        if proc.returncode != 0:
            raise ClaudeError(f"claude stop exited with {proc.returncode}: {self._tail(proc)}")
