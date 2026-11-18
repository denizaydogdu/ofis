"""Open subagents of an office session, for the living office page (/api/state sessions[].alt_ajanlar, ceo.alt_ajanlar).

Claude Code writes a subagent's transcript to <transcript folder>/<sessionId>/subagents/agent-<id>.jsonl, next to
agent-<id>.meta.json ({agentType, description, pickedEffortModel, …, finished: true once it handed back}). Seen in
this office's own transcripts (Claude Code 2.1.322, spike 2026-11-11):
- the first line is the task: {"type": "user", "isSidechain": true, "message": {"content": "<prompt>"}};
- assistant records carry message.model (e.g. "claude-opus-5-5");
- every end of a subagent's turn appends {"type": "attachment", "attachment": {"hookEvent": "SubagentStop", …}}; a
  subagent resumed later (a message or a notification) writes after it again.
A subagent is finished (bitti) when its last record is that SubagentStop, or when its meta says finished and is not
older than the transcript. It is listed while open and written in the last OPEN_WINDOW (LONG_TOOL_WINDOW while its
last record is a tool call still waiting for its result), and for DONE_SHOWN after it finished, at most MAX_SHOWN
(open ones first, newest first). gorev = the meta description, else the start of the first prompt: plain text, at
most 80 characters. Only the folder of a valid session id is read (the caller passes office sessions only); a file is
parsed again only when its mtime or size changed (head 16 KB, tail 64 KB); the rest is one listdir and a stat each.
"""
import json
import os
import re
from datetime import datetime, timezone

import model_durum
import transcript

OPEN_WINDOW = 5 * 60
LONG_TOOL_WINDOW = 30 * 60
DONE_SHOWN = 60
MAX_SHOWN = 8
MAX_GOREV = 80
HEAD_BYTES = 16 * 1024
TAIL_BYTES = 64 * 1024
AGENT_FILE = re.compile(r"agent-([A-Za-z0-9_-]{1,64})\.jsonl")


forbidden_folder = transcript.forbidden_folder  # one check for every transcript read (see transcript.py)


def plain(content, limit=MAX_GOREV):
    """Plain one-line text of a prompt (str or content blocks), at most `limit` characters."""
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content
                           if isinstance(p, dict) and isinstance(p.get("text"), str))
    if not isinstance(content, str):
        return ""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", content)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _head(path):
    with open(path, "rb") as f:
        line = f.read(HEAD_BYTES).split(b"\n", 1)[0]
    try:
        rec = json.loads(line.decode("utf-8", errors="replace"))
    except ValueError:
        return ""
    if not isinstance(rec, dict) or rec.get("type") != "user":
        return ""
    return plain((rec.get("message") or {}).get("content"))


def _tail(path):
    """(model family or "", finished, waiting on a tool, stopped by an API error)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read(TAIL_BYTES)
    lines = data.split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]
    model, last = "", None
    for raw in lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") not in ("user", "assistant", "attachment"):
            continue  # api-request, queue operations and other bookkeeping
        last = rec
        if rec.get("type") == "assistant" and not rec.get("isApiErrorMessage"):
            fam = model_durum.family((rec.get("message") or {}).get("model"))
            model = fam or model
    finished, waiting, error = False, False, False
    if last is not None:
        error = bool(last.get("isApiErrorMessage"))
        att = last.get("attachment") if isinstance(last.get("attachment"), dict) else {}
        finished = last.get("type") == "attachment" and att.get("hookEvent") == "SubagentStop"
        content = (last.get("message") or {}).get("content") if last.get("type") == "assistant" else None
        waiting = isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "tool_use"
                                                    for p in content)
    return model, finished, waiting, error


def _meta(path):
    try:
        st = os.stat(path)
        with open(path, encoding="utf-8") as f:
            data = json.loads(f.read(16 * 1024))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}, None
    return (data if isinstance(data, dict) else {}), st.st_mtime


class SubagentScanner:
    def __init__(self):
        self.reads = 0
        self._cache = {}  # jsonl path -> ((mtime_ns, size, meta mtime), info)

    def _info(self, path, st):
        meta_path = path[:-len(".jsonl")] + ".meta.json"
        try:
            meta_mtime = os.stat(meta_path).st_mtime_ns
        except OSError:
            meta_mtime = None
        key = (st.st_mtime_ns, st.st_size, meta_mtime)
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        try:
            gorev_head = _head(path)
            model, stopped, waiting, error = _tail(path)
        except OSError:
            return None
        self.reads += 1
        meta, meta_mt = _meta(meta_path) if meta_mtime is not None else ({}, None)
        gorev = plain(meta.get("description")) or gorev_head
        model = model or model_durum.family(meta.get("pickedEffortModel"))
        meta_done = meta.get("finished") is True and meta_mt is not None and meta_mt >= st.st_mtime - 1
        info = {"model": model, "gorev": gorev, "bitti": bool(stopped or meta_done), "waiting": waiting,
                "error": error}
        self._cache[path] = (key, info)
        return info

    def list(self, folder, session_id, now, only_finished=False):
        """[{id, model, gorev, son_yazma, bitti}] of a session's subagents to show. now: aware datetime.
        only_finished: the parent's job is final, so nothing of it is open any more (only the finished rows stay)."""
        if not transcript.valid_session_id(session_id) or forbidden_folder(folder):
            return []
        sub = os.path.join(folder, session_id, "subagents")
        try:
            entries = list(os.scandir(sub))
        except OSError:
            return []
        now_ts = now.timestamp()
        rows = []
        for e in entries:
            m = AGENT_FILE.fullmatch(e.name)
            if not m or not e.is_file(follow_symlinks=False):
                continue
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            age = now_ts - st.st_mtime
            if age > LONG_TOOL_WINDOW:
                continue  # nothing to read: never open, never just finished
            info = self._info(e.path, st)
            if info is None:
                continue
            if info["bitti"]:
                if age > DONE_SHOWN:
                    continue
            elif info["error"] or only_finished:
                continue  # stopped by an API error (it did not hand back), or its parent's job is over
            elif age > (LONG_TOOL_WINDOW if info["waiting"] else OPEN_WINDOW):
                continue
            rows.append({"id": m.group(1), "model": info["model"], "gorev": info["gorev"],
                         "son_yazma": datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone(now.tzinfo)
                         .isoformat(timespec="seconds"), "bitti": info["bitti"], "_t": st.st_mtime})
        rows.sort(key=lambda r: (r["bitti"], -r["_t"]))
        for r in rows:
            del r["_t"]
        return rows[:MAX_SHOWN]
