"""Shared test helpers: a fake `claude` executable and transcript builders. The real claude is never called."""
import atexit
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone


def isolate_jobs_lock():
    """The job lock lives in the repo's durum/ (bin/jobs.py); tests must never touch the real durum/, so every test
    process points it at its own temp file (OFIS_JOBS_LOCK). Importing this module is enough."""
    if not os.environ.get("OFIS_JOBS_LOCK"):
        path = os.path.join(tempfile.gettempdir(), f"ofis-test-jobs-{os.getpid()}.lock")
        os.environ["OFIS_JOBS_LOCK"] = path
        atexit.register(lambda: os.path.exists(path) and os.remove(path))


isolate_jobs_lock()


def isolate_codex():
    """Codex is installed on the owner's machine and its quota is real: no test may ever run it. bin/akis.py takes
    $OFIS_CODEX_BIN before ofis.json and PATH, so every test process points it at a path that does not exist (a
    test that wants a codex passes FakeCodex's path in its config, which wins over this)."""
    os.environ["OFIS_CODEX_BIN"] = os.path.join(tempfile.gettempdir(), f"ofis-test-no-codex-{os.getpid()}")


isolate_codex()

# The tests' own neutral ofis.json (owner name, privacy rules) for every test process and its children, on any machine:
# the test-only override OFIS_TEST + OFIS_CONFIG (bin/yasaklar.py ofis_json). See test/sahip_yasaklari.py.
import sahip_yasaklari  # noqa: E402,F401


def isolate_claude_trust():
    """bin/launch.py reads folder trust from Claude's real ~/.claude.json; tests point $OFIS_CLAUDE_JSON at a path
    that does not exist (unknown trust: the start goes on). A trust test writes its own file and sets it."""
    os.environ["OFIS_CLAUDE_JSON"] = os.path.join(tempfile.gettempdir(), f"ofis-test-no-claude-json-{os.getpid()}")


isolate_claude_trust()

# The fake keeps the session list in $FAKE_DIR/agents.json and logs every call to $FAKE_DIR/calls.jsonl.
# Behaviour switches (files in $FAKE_DIR): fail (every --bg/stop fails), resume-idle (a resumed session stays idle),
# no-agent-on-start (a started session does not show up in `agents`), stop-noop (stop exits 0 but the session stays
# listed), odd-output (--bg exits 0 but prints another wording), other-name (--bg reports another session name),
# slow (--bg sleeps 3 s first), fork-on-resume (see FakeClaude.fork_on_resume). names.json maps a session id to the name a resumed session reports. agents-next.json, when present, replaces agents.json after the next `agents` call.
FAKE_CLAUDE = r'''#!{python} -I
import json, os, sys
d = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")
agents_path = os.path.join(d, "agents.json")
agents = json.load(open(agents_path)) if os.path.exists(agents_path) else []
def save():
    tmp = agents_path + ".%d.tmp" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(agents, f)
    os.replace(tmp, agents_path)
def on(flag):
    return os.path.exists(os.path.join(d, flag))
def launched(short, name):
    print("Starting background service…")
    if on("odd-output"):
        print("Session " + short + " continues in the background")
    else:
        print("backgrounded · " + short + " · " + ("ofis-other" if on("other-name") else name))
    sys.exit(0)
if args[:1] == ["-p"] and args[-1].startswith("Sen Ofis'in güvenlik denetçisisin"):
    # the security reviewer (FakeSecurity): the same claude -p call; switches guvenlik-fail / guvenlik-garbage,
    # guvenlik.txt = its report (default: no finding, KARAR: ONAY), cost $0.0731
    if on("guvenlik-garbage"):
        print("not json at all"); sys.exit(0)
    if on("guvenlik-fail"):
        print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                          "total_cost_usd": 0.2, "result": ""}))
        sys.exit(1)
    path = os.path.join(d, "guvenlik.txt")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else "Güvenlik bulgusu yok.\nKARAR: ONAY"
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0731,
                      "result": text}))
    sys.exit(0)
if args[:1] == ["-p"] and args[-1].startswith("Sen Ofis'in kanıt değerlendiricisisin"):
    # the kanıt pass (FakeKanit): switches kanit-fail; kanit.txt = its reply (default: two proof lines each, two
    # quiz questions), cost $0.0123
    if on("kanit-fail"):
        print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                          "total_cost_usd": 0.01, "result": ""}))
        sys.exit(1)
    path = os.path.join(d, "kanit.txt")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else "\n".join([
        "KANITLADI: testler geçiyor", "KANITLADI: a.py yükleniyor",
        "KANITLAMADI: hata yolu denenmedi", "KANITLAMADI: arayüz elle denenmedi",
        "SORU: Hangi dosyaya yeni değişken eklendi? | CEVAP: a.py (b = 2)",
        "SORU: new.py ne tanımlıyor? | CEVAP: z = 3", "KANIT: TAMAM"])
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0123,
                      "result": text}))
    sys.exit(0)
if args[:1] == ["-p"] and args[-1].startswith("Sen Ofis'te teknik soruları cevaplayan müdürsün"):
    # a manager's answer (FakeMudur, bin/mudur.py): switches mudur-fail / mudur-garbage / mudur-slow; mudur.txt = its
    # reply (default: one line of advice, KARAR: CEVAP), cost $0.0412, 2,4 bin token
    import time
    if on("mudur-slow"):
        time.sleep(30)
    if on("mudur-garbage"):
        print("not json at all"); sys.exit(0)
    if on("mudur-fail"):
        print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                          "total_cost_usd": 0.15, "result": ""}))
        sys.exit(1)
    path = os.path.join(d, "mudur.txt")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else \
        "Var olan tarih yardımcısını kullan; yeni sınıf açma.\nKARAR: CEVAP"
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0412,
                      "usage": {"input_tokens": 2000, "output_tokens": 400}, "result": text}))
    sys.exit(0)
if args[:1] == ["-p"]:  # the hakem (FakeHakem): claude -p … --output-format json "<prompt>"
    import re, time
    if on("hakem-slow"):
        time.sleep(30)
    if on("hakem-garbage"):
        print("not json at all"); sys.exit(0)
    if on("hakem-fail"):
        print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                          "total_cost_usd": 0.15, "result": ""}))
        sys.exit(1)
    path = os.path.join(d, "hakem.txt")
    if os.path.exists(path):
        text = open(path, encoding="utf-8").read()
    else:
        numbers = re.findall(r"^> \[(\d+)\]", args[-1], re.M)
        extra = ["KANITLADI: sahte kanıt", "KANITLAMADI: sahte eksik"] if "`KANITLADI: <kısa>`" in args[-1] else []
        extra += ["SORU: sahte soru? | CEVAP: sahte cevap"] if "`SORU: <soru>" in args[-1] else []
        text = "\n".join(["BULGU %s: GEÇERLİ | sahte hakem" % n for n in numbers] + extra + ["HAKEM: TAMAM"])
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0582,
                      "result": text}))
    sys.exit(0)
if args[:2] == ["agents", "--json"]:
    print(json.dumps(agents))
    if os.path.exists(os.path.join(d, "agents-next.json")):
        os.replace(os.path.join(d, "agents-next.json"), agents_path)
    sys.exit(0)
if on("fail"):
    print("boom", file=sys.stderr); sys.exit(1)
if args[:1] == ["--bg"] and on("slow"):
    import time; time.sleep(3)
if args[:1] == ["stop"]:
    if not on("stop-noop"):
        agents[:] = [a for a in agents if not a["sessionId"].startswith(args[1])]
        save()
    sys.exit(0)
if args[:2] == ["--bg", "--name"]:
    sid = "c0ffee00-1111-2222-3333-444455556666"
    if not os.path.exists(os.path.join(d, "no-agent-on-start")):
        agents.append({"pid": 1, "cwd": os.getcwd(), "kind": "background", "startedAt": 0, "sessionId": sid,
                       "name": args[2], "status": "busy"})
        save()
    launched(sid[:8], args[2])
if args[:2] == ["--bg", "--resume"] and (on("copy-running") or on("copy-options")):
    # Claude 2.1.325: a copy instead of a resume (2026-11-15), told on stderr
    agents.append({"pid": 3, "cwd": os.getcwd(), "kind": "background", "startedAt": 0,
                   "sessionId": "deadbeef-0000-4000-8000-000000000000", "name": "copy", "status": "busy"})
    save()
    print("  claude attach deadbeef    open in this terminal")
    if on("copy-running"):
        print(f"note: session {args[2][:8]} is already running in the background, so this started a copy as deadbeef. "
              f"`claude attach {args[2][:8]}` opens the original.", file=sys.stderr)
    else:
        print(f"note: background session {args[2][:8]} keeps its own saved options, so the flags you passed started a "
              f"copy as deadbeef. Without flags, the same command continues {args[2][:8]} itself.", file=sys.stderr)
    sys.exit(0)
if args[:2] == ["--bg", "--resume"]:
    sid = args[2]
    status = "idle" if os.path.exists(os.path.join(d, "resume-idle")) else "busy"
    names_path = os.path.join(d, "names.json")
    names = json.load(open(names_path)) if os.path.exists(names_path) else {}
    name = names.get(sid) or next((a["name"] for a in agents if a["sessionId"] == sid), "ofis-ceo")
    fork_path = os.path.join(d, "fork-on-resume")
    if os.path.exists(fork_path):
        # Claude Code 2.1.322 for a project session: the conversation goes on in a NEW transcript (new id) that starts
        # with the name records and a copy of the earlier history; `agents` keeps listing the OLD id (status None).
        cfg = json.load(open(fork_path))
        new_ids = cfg.get("new_ids") or []
        new = new_ids.pop(0) if new_ids else __import__("uuid").uuid4().hex[:8] + "-0000-4000-8000-" + "0" * 12
        cfg["new_ids"] = new_ids
        json.dump(cfg, open(fork_path, "w"))
        folder = os.path.join(cfg["projects_dir"], os.getcwd().replace("/", "-"))
        old_lines = open(os.path.join(folder, sid + ".jsonl")).read().splitlines()
        with open(os.path.join(folder, new + ".jsonl"), "w") as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": name, "sessionId": new}) + "\n")
            f.write(json.dumps({"type": "agent-name", "agentName": name, "sessionId": new}) + "\n")
            for line in old_lines:
                if line.strip():
                    r = json.loads(line)
                    if isinstance(r, dict) and "sessionId" in r:
                        r["sessionId"] = new
                    f.write(json.dumps(r) + "\n")
            for r in cfg.get("records") or []:
                f.write(json.dumps(dict(r, sessionId=new)) + "\n")
        if not any(a["sessionId"] == sid for a in agents):
            agents.append({"pid": 2, "cwd": os.getcwd(), "kind": "background", "startedAt": 0, "sessionId": sid,
                           "name": name, "status": None})
        else:
            agents[:] = [dict(a, status=None) if a["sessionId"] == sid else a for a in agents]
        save()
        launched(new[:8], name)
    agents[:] = [a for a in agents if a["sessionId"] != sid]
    agents.append({"pid": 2, "cwd": os.getcwd(), "kind": "background", "startedAt": 0, "sessionId": sid,
                   "name": name, "status": status})
    save()
    launched(sid[:8], name)
print("unexpected", args, file=sys.stderr); sys.exit(3)
'''


class FakeClaude:
    def __init__(self, folder):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "claude")
        with open(self.path, "w") as f:
            f.write(FAKE_CLAUDE.replace("{python}", sys.executable))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)
        os.environ["FAKE_DIR"] = folder
        self.set_agents([])

    def set_agents(self, agents):
        # Atomic: a fake `claude agents` run by a server thread must never read a half-written file.
        path = os.path.join(self.dir, "agents.json")
        with open(path + ".tmp", "w") as f:
            json.dump(agents, f)
        os.replace(path + ".tmp", path)

    def set_next_agents(self, agents):
        """The list `claude agents` reports from its second call on (the first still reports the current one)."""
        path = os.path.join(self.dir, "agents-next.json")
        with open(path + ".tmp", "w") as f:
            json.dump(agents, f)
        os.replace(path + ".tmp", path)

    def set_name(self, session_id, name):
        """The name a resumed session reports (default: its listed name, else ofis-ceo)."""
        path = os.path.join(self.dir, "names.json")
        names = json.load(open(path)) if os.path.exists(path) else {}
        names[session_id] = name
        with open(path, "w") as f:
            json.dump(names, f)

    def fork_on_resume(self, projects_dir, new_ids=(), records=()):
        """Every `--bg --resume` continues in a NEW transcript (the next id of new_ids, else a random one): the name
        records, a copy of the old transcript (sessionId rewritten, message ids kept) and `records`; `agents` keeps
        the OLD id with status None (what Claude Code 2.1.322 does for a resumed project session)."""
        with open(os.path.join(self.dir, "fork-on-resume"), "w") as f:
            json.dump({"projects_dir": projects_dir, "new_ids": list(new_ids), "records": list(records)}, f)

    def agents(self):
        with open(os.path.join(self.dir, "agents.json")) as f:
            return json.load(f)

    def set_status(self, session_id, status):
        self.set_agents([dict(a, status=status) if a["sessionId"] == session_id else a for a in self.agents()])

    def flag(self, name, on=True):
        path = os.path.join(self.dir, name)
        if on:
            open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)

    def calls(self, skip_agents=True):
        path = os.path.join(self.dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            calls = [json.loads(line) for line in f]
        return [c for c in calls if not (skip_agents and c["args"][:1] == ["agents"])]


def agent(name, cwd, sid, status="idle", kind="background"):
    return {"pid": 1, "cwd": cwd, "kind": kind, "startedAt": 1794316175301, "sessionId": sid, "name": name,
            "status": status}


def ts(day, hour=12, minute=0):
    """ISO UTC timestamp (Claude Code format) of a local time on `day`."""
    local = datetime.combine(day, time(hour, minute)).astimezone()
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def yesterday(day):
    return day - timedelta(days=1)


def assistant(day, msg_id, parts, usage=None, hour=12, model="claude-x", stop_reason="end_turn"):
    return {"type": "assistant", "timestamp": ts(day, hour),
            "message": {"id": msg_id, "model": model, "role": "assistant", "content": parts,
                        "stop_reason": stop_reason,
                        "usage": usage or {"input_tokens": 0, "output_tokens": 0,
                                           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}


def usage(i=1, o=2, cc=3, cr=4):
    return {"input_tokens": i, "output_tokens": o, "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr,
            "server_tool_use": {"web_search_requests": 7}}


def user(day, content, hour=12, meta=False, origin=None):
    record = {"type": "user", "timestamp": ts(day, hour), "message": {"role": "user", "content": content}}
    if meta:
        record["isMeta"] = True
    if origin is not None:
        record["origin"] = origin
    return record


def human(day, content, hour=12):
    """A prompt delivered as a top-level user turn (start or resume with a prompt): origin.kind human."""
    return user(day, content, hour, origin={"kind": "human"})


def peer(day, from_name, body, hour=12, structured=True, content_body=None):
    """A cross-session message as Claude Code records it: isMeta, the tagged text, and origin.kind peer with the
    sender name and body (structured=False drops the origin, as older records have none)."""
    record = user(day, cross(from_name, body if content_body is None else content_body), hour, meta=True)
    if structured:
        record["origin"] = {"kind": "peer", "from": "uds:/tmp/x.sock", "verifiedPeerPid": 1, "msg_id": "m",
                            "name": from_name, "fromMode": "prompting", "body": body}
    return record


def cross(from_name, body):
    return ("Another Claude session sent a message:\n"
            f'<cross-session-message from="uds:/tmp/x.sock" from-name="{from_name}" from-mode="prompting">\n'
            f"{body}\n</cross-session-message>\n\nThis came from another Claude session — not typed by your user.")


def write_transcript(projects_dir, cwd, session_id, records, mode="w"):
    folder = os.path.join(projects_dir, cwd.replace("/", "-"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{session_id}.jsonl")
    with open(path, mode, encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def write_note(folder, name, meta, body):
    os.makedirs(folder, exist_ok=True)
    head = "".join(f"{k}: {v}\n" for k, v in meta.items())
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(f"---\n{head}---\n\n{body}")
    return os.path.join(folder, name)


def name_records(name, session_id):
    """The records Claude Code writes at the top of a named session's transcript."""
    return [{"type": "custom-title", "customTitle": name, "sessionId": session_id},
            {"type": "agent-name", "agentName": name, "sessionId": session_id}]


def closed_turn(day, msg_id="r1", text="Tamam.", hour=12):
    """An assistant reply and the turn-end record Claude Code writes after it (the turn is closed)."""
    return [assistant(day, msg_id, [{"type": "text", "text": text}], hour=hour),
            {"type": "system", "subtype": "turn_duration", "timestamp": ts(day, hour)}]


# A fake `codex`: logs every call (args + cwd) to $FAKE_CODEX_DIR/calls.jsonl. Switches (files in that folder):
# quota (prints a usage-limit error, exit 1), quota_at (the same with codex's "try again at <time>"), fail (exit 2), slow (sleeps 30 s), review.txt (the review it writes
# to the -o file; default "Bulgu yok." + "KARAR: ONAY").
FAKE_CODEX = r"""#!{python} -I
import json, os, sys, time
d = os.environ["FAKE_CODEX_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "pid": os.getpid()}) + "\n")
def on(flag):
    return os.path.exists(os.path.join(d, flag))
# Like the real parser: -C/--cd and -s/--sandbox belong to `codex exec`, `codex exec review` rejects them.
if "review" in args and any(a in ("-C", "--cd", "-s", "--sandbox") for a in args[args.index("review") + 1:]):
    print("error: unexpected argument '-C' found", file=sys.stderr)
    sys.exit(2)
# Like the real parser (codex 0.167): `review --base <BRANCH>` cannot be used together with a [PROMPT].
if "review" in args and "--base" in args:
    rest = args[args.index("review") + 1:]
    skip = {"--base", "-o", "--output-last-message", "-c", "--commit", "--title"}
    positional = [a for i, a in enumerate(rest) if not a.startswith("-") and (i == 0 or rest[i - 1] not in skip)]
    if positional:
        print("error: the argument '--base <BRANCH>' cannot be used with '[PROMPT]'", file=sys.stderr)
        sys.exit(2)
if on("slow"):
    time.sleep(30)
if on("quota"):
    print("ERROR: You've hit your usage limit. Upgrade to Pro or try again later.", file=sys.stderr)
    sys.exit(1)
if on("quota_at"):  # the wording of codex 0.167 (its binary: "… or try again at %b %-d<th>, %Y %-I:%M %p.")
    print("ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
          "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Nov 12th, 2026 3:05 PM.",
          file=sys.stderr)
    sys.exit(1)
if on("fail"):
    print("codex: something broke", file=sys.stderr)
    sys.exit(2)
review = os.path.join(d, "review.txt")
text = open(review, encoding="utf-8").read() if os.path.exists(review) else "Bulgu yok.\nKARAR: ONAY\n"
if "-o" in args:
    with open(args[args.index("-o") + 1], "w", encoding="utf-8") as f:
        f.write(text)
print("codex review done")
"""


class FakeCodex:
    def __init__(self, folder):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "codex")
        with open(self.path, "w") as f:
            f.write(FAKE_CODEX.replace("{python}", sys.executable))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)
        os.environ["FAKE_CODEX_DIR"] = folder

    def flag(self, name, on=True):
        path = os.path.join(self.dir, name)
        if on:
            open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)

    def review(self, text):
        with open(os.path.join(self.dir, "review.txt"), "w", encoding="utf-8") as f:
            f.write(text)

    def calls(self):
        path = os.path.join(self.dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]


def isolate_opencode():
    """OpenCode is installed on the owner's machine and its free models send the diff to an outside service: no test may
    ever run it. bin/denetci.py takes ofis.json opencode_bin, then $OFIS_OPENCODE_BIN, then PATH; every test process
    points the variable at a path that does not exist (a test that wants one passes FakeOpenCode's path in its
    config)."""
    os.environ["OFIS_OPENCODE_BIN"] = os.path.join(tempfile.gettempdir(), f"ofis-test-no-opencode-{os.getpid()}")


isolate_opencode()

# A fake `opencode run … --format json`: logs every call (args, cwd, the OPENCODE_* and PWD environment, whether stdin
# was empty, the files it saw in its folder) to $FAKE_OPENCODE_DIR/calls.jsonl and prints JSON events like OpenCode
# 2.0.32. Switches per model (files named <model short name>.<switch> in that folder, the short name is the part after
# "opencode/"): .review (the final text; default "Bulgu yok." + "KARAR: ONAY"), .quota / .ratelimit / .noroute (an
# error event of that provider type, exit 1), .fail (exit 1, no JSON), .slow (sleeps 30 s), .empty (no text event),
# .write (writes into its folder: changes the first file and adds kotu.txt — the snapshot must take it, never the
# real project).
FAKE_OPENCODE = r"""#!{python} -I
import json, os, sys, time
d = os.environ["FAKE_OPENCODE_DIR"]
args = sys.argv[1:]
model = args[args.index("-m") + 1] if "-m" in args else ""
key = model.split("/")[-1]
def on(flag):
    return os.path.exists(os.path.join(d, key + "." + flag))
files = {}
for root, dirs, names in os.walk(os.getcwd()):
    dirs[:] = [x for x in dirs if x != ".git"]
    for n in names:
        p = os.path.join(root, n)
        try:
            files[os.path.relpath(p, os.getcwd())] = open(p, encoding="utf-8", errors="replace").read(2000)
        except OSError:
            pass
stdin_empty = sys.stdin.read() == ""
env = {k: v for k, v in os.environ.items() if k.startswith("OPENCODE_") or k == "PWD"}
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "env": env, "stdin_empty": stdin_empty,
                        "files": files}) + "\n")
def event(kind, **kw):
    print(json.dumps(dict({"type": kind, "timestamp": 1, "sessionID": "ses_x"}, **kw)))
if on("slow"):
    time.sleep(30)
if on("fail"):
    print("opencode: crashed", file=sys.stderr)
    sys.exit(1)
for flag, kind, msg in (("quota", "provider.quota", "Free usage quota exceeded"),
                        ("ratelimit", "provider.rate-limit", "Rate limited, retry later"),
                        ("noroute", "provider.no-route", "Model unavailable: " + model)):
    if on(flag):
        event("error", error={"type": kind, "message": msg})
        sys.exit(1)
if on("write"):
    first = next(iter(sorted(k for k in files if k != ".git")), None)
    if first:
        with open(os.path.join(os.getcwd(), first), "a") as f:
            f.write("# denetçi yazdı\n")
    with open(os.path.join(os.getcwd(), "kotu.txt"), "w") as f:
        f.write("x")
event("step_start", part={"type": "step-start"})
event("tool_use", part={"type": "tool", "tool": "read", "state": {"status": "completed", "output": "KARAR: ONAY"}})
if not on("empty"):
    event("text", part={"type": "text", "text": "Önce bakıyorum.\nKARAR: DÜZELT"})
    review = os.path.join(d, key + ".review")
    text = open(review, encoding="utf-8").read() if os.path.exists(review) else "Bulgu yok.\nKARAR: ONAY\n"
    event("text", part={"type": "text", "text": text})
event("step_finish", part={"type": "step-finish"})
"""


class FakeOpenCode:
    def __init__(self, folder):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "opencode")
        with open(self.path, "w") as f:
            f.write(FAKE_OPENCODE.replace("{python}", sys.executable))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)
        os.environ["FAKE_OPENCODE_DIR"] = folder

    def flag(self, model, name, on=True):
        path = os.path.join(self.dir, model.split("/")[-1] + "." + name)
        if on:
            open(path, "w").close()
        elif os.path.exists(path):
            os.remove(path)

    def review(self, model, text):
        with open(os.path.join(self.dir, model.split("/")[-1] + ".review"), "w", encoding="utf-8") as f:
            f.write(text)

    def calls(self):
        path = os.path.join(self.dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]


def isolate_agy():
    """Antigravity (agy) is installed on the owner's machine and its free plan sends the diff to an outside service: no test
    may ever run it. bin/denetci.py takes ofis.json agy_bin, then $OFIS_AGY_BIN, then PATH; every test process points
    the variable at a path that does not exist (a test that wants one passes FakeAgy's path in its config)."""
    os.environ["OFIS_AGY_BIN"] = os.path.join(tempfile.gettempdir(), f"ofis-test-no-agy-{os.getpid()}")
    # agy's config folders (bin/denetci.py agy_config_mtime): never the owner's real ~/.gemini
    os.environ["OFIS_AGY_CONFIG_PATHS"] = os.path.join(tempfile.gettempdir(), f"ofis-test-no-gemini-{os.getpid()}")


isolate_agy()

# A fake `agy -p <prompt> --mode plan --sandbox --model <m> --output-format json --print-timeout <s>s`: logs every call
# (args, cwd, PWD, whether stdin was empty, the files it saw in its folder, its pid) to $FAKE_AGY_DIR/calls.jsonl and
# prints one JSON object {status, response, denied_actions, usage, duration_seconds} like agy 1.5.7. Switches (files
# named <model>.<switch> in that folder): .review (the response; default "Bulgu yok." + "KARAR: ONAY"), .quota (exit 1,
# status ERROR, error "RESOURCE_EXHAUSTED … 429"), .errstatus (exit 0, status ERROR, error "internal"), .fail (exit 1,
# no JSON), .slow (sleeps 30 s), .sleep (sleeps the seconds written in it, then answers), .empty (empty response),
# .nokarar (a response without a KARAR line), .denied (two denied actions), .write (writes kotu.txt into its folder).
FAKE_AGY = r"""#!{python} -I
import json, os, sys, time
d = os.environ["FAKE_AGY_DIR"]
args = sys.argv[1:]
model = args[args.index("--model") + 1] if "--model" in args else ""
def on(flag):
    return os.path.exists(os.path.join(d, model + "." + flag))
if args[:2] in (["mcp", "list"], ["plugin", "list"]):  # the user-config guard (setup.jsonl, never calls.jsonl)
    with open(os.path.join(d, "setup.jsonl"), "a") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")
    if os.path.exists(os.path.join(d, "list.fail")):
        print("agy: cannot read config", file=sys.stderr)
        sys.exit(1)
    if os.path.exists(os.path.join(d, args[0] + ".has")):
        print("github  npx -y @modelcontextprotocol/server-github" if args[0] == "mcp" else "swarm 1.0.0  enabled")
    else:
        print("No MCP servers configured" if args[0] == "mcp" else "No plugins installed")
    sys.exit(0)
files = {}
for root, dirs, names in os.walk(os.getcwd()):
    dirs[:] = [x for x in dirs if x != ".git"]
    for n in names:
        p = os.path.join(root, n)
        try:
            files[os.path.relpath(p, os.getcwd())] = open(p, encoding="utf-8", errors="replace").read(2000)
        except OSError:
            pass
stdin_empty = sys.stdin.read() == ""
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "pwd": os.environ.get("PWD", ""), "stdin_empty": stdin_empty,
                        "files": files, "pid": os.getpid()}) + "\n")
if on("slow"):
    time.sleep(30)
if on("sleep"):
    time.sleep(float(open(os.path.join(d, model + ".sleep")).read().strip() or "1"))
if on("fail"):
    print("agy: crashed", file=sys.stderr)
    sys.exit(1)
out = {"status": "SUCCESS", "response": "", "denied_actions": [], "usage": {"input_tokens": 10, "output_tokens": 5},
       "duration_seconds": 1.0}
if on("quota"):
    out.update(status="ERROR", error="RESOURCE_EXHAUSTED: You have exhausted your quota (429)")
    print(json.dumps(out))
    sys.exit(1)
if on("errstatus"):
    out.update(status="ERROR", error="internal error")
    print(json.dumps(out))
    sys.exit(0)
if on("write"):
    with open(os.path.join(os.getcwd(), "kotu.txt"), "w") as f:
        f.write("x")
if on("denied"):
    out["denied_actions"] = [{"tool": "write_file", "path": "a.py"}, "run_command: ls"]
review = os.path.join(d, model + ".review")
text = open(review, encoding="utf-8").read() if os.path.exists(review) else "Bulgu yok.\nKARAR: ONAY\n"
if on("nokarar"):
    text = "Her şey iyi görünüyor."
if not on("empty"):
    out["response"] = text
print(json.dumps(out))
"""


class FakeAgy:
    def __init__(self, folder):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "agy")
        with open(self.path, "w") as f:
            f.write(FAKE_AGY.replace("{python}", sys.executable))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)
        os.environ["FAKE_AGY_DIR"] = folder

    def flag(self, model, name, on=True, text=""):
        path = os.path.join(self.dir, model + "." + name)
        if on:
            with open(path, "w") as f:
                f.write(text)
        elif os.path.exists(path):
            os.remove(path)

    def review(self, model, text):
        with open(os.path.join(self.dir, model + ".review"), "w", encoding="utf-8") as f:
            f.write(text)

    def user_config(self, mcp=False, plugin=False, fail=False):
        """agy's user config as `agy mcp list` / `agy plugin list` show it (default: nothing configured)."""
        for name, on in (("mcp.has", mcp), ("plugin.has", plugin), ("list.fail", fail)):
            path = os.path.join(self.dir, name)
            if on:
                open(path, "w").close()
            elif os.path.exists(path):
                os.remove(path)

    def setup_calls(self):
        path = os.path.join(self.dir, "setup.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def calls(self):
        path = os.path.join(self.dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]


class FakeHakem:
    """The hakem's `claude -p … --output-format json` on FakeClaude (same executable, same calls.jsonl). Default: every
    finding of the prompt (lines "> [n] …") is GEÇERLİ, cost $0.0582. verdicts({n: (True|False, reason)},
    same={n: m}) writes a reply; text(raw) any reply; fail() exits 1 with an error result; garbage() prints no JSON;
    slow() sleeps 30 s."""

    def __init__(self, fake_claude):
        self.fake = fake_claude

    def _write(self, name, text):
        with open(os.path.join(self.fake.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def verdicts(self, judged, same=None):
        lines = [f"BULGU {n}: {'GEÇERLİ' if ok else 'GEÇERSİZ'} | {why}" for n, (ok, why) in sorted(judged.items())]
        lines += [f"AYNI {a}: {b}" for a, b in sorted((same or {}).items())]
        self.text("\n".join(lines + ["HAKEM: TAMAM"]))

    def text(self, raw):
        self._write("hakem.txt", raw)

    def fail(self):
        self.fake.flag("hakem-fail")

    def garbage(self):
        self.fake.flag("hakem-garbage")

    def slow(self):
        self.fake.flag("hakem-slow")

    def calls(self):
        return [c for c in self.fake.calls() if c["args"][:1] == ["-p"] and not is_security(c) and not is_kanit(c)
                and not is_mudur(c)]


MUDUR_HEAD = "Sen Ofis'te teknik soruları cevaplayan müdürsün"  # bin/mudur.py PROMPT_HEAD


def is_mudur(call):
    return call["args"][:1] == ["-p"] and call["args"][-1].startswith(MUDUR_HEAD)


class FakeMudur:
    """A manager's `claude -p` on FakeClaude (bin/mudur.py). Default reply: one line of advice and `KARAR: CEVAP`,
    $0.0412, 2400 tokens. text(raw) sets the reply; fail() exits 1 with an error result; garbage() prints no JSON;
    slow() sleeps 30 s."""

    def __init__(self, fake_claude):
        self.fake = fake_claude

    def text(self, raw):
        with open(os.path.join(self.fake.dir, "mudur.txt"), "w", encoding="utf-8") as f:
            f.write(raw)

    def fail(self):
        self.fake.flag("mudur-fail")

    def garbage(self):
        self.fake.flag("mudur-garbage")

    def slow(self):
        self.fake.flag("mudur-slow")

    def calls(self):
        return [c for c in self.fake.calls() if is_mudur(c)]


SECURITY_HEAD = "Sen Ofis'in güvenlik denetçisisin"  # bin/denetci.py SECURITY_HEAD
KANIT_HEAD = "Sen Ofis'in kanıt değerlendiricisisin"  # bin/denetci.py KANIT_HEAD


def is_kanit(call):
    return call["args"][:1] == ["-p"] and call["args"][-1].startswith(KANIT_HEAD)


class FakeKanit:
    """The kanıt pass's `claude -p` on FakeClaude (a round without a hakem): text(raw) sets its reply (default: two
    KANITLADI, two KANITLAMADI, two SORU lines; $0.0123); fail() exits 1 with an error result."""

    def __init__(self, fake_claude):
        self.fake = fake_claude

    def text(self, raw):
        with open(os.path.join(self.fake.dir, "kanit.txt"), "w", encoding="utf-8") as f:
            f.write(raw)

    def fail(self):
        self.fake.flag("kanit-fail")

    def calls(self):
        return [c for c in self.fake.calls() if is_kanit(c)]


def is_security(call):
    return call["args"][:1] == ["-p"] and call["args"][-1].startswith(SECURITY_HEAD)


class FakeSecurity:
    """The security reviewer's `claude -p` on FakeClaude: report(text) sets its report (default: no finding, KARAR:
    ONAY, $0.0731); fail() exits 1 with an error result ($0.20); garbage() prints no JSON."""

    def __init__(self, fake_claude):
        self.fake = fake_claude

    def report(self, text):
        with open(os.path.join(self.fake.dir, "guvenlik.txt"), "w", encoding="utf-8") as f:
            f.write(text)

    def fail(self):
        self.fake.flag("guvenlik-fail")

    def garbage(self):
        self.fake.flag("guvenlik-garbage")

    def calls(self):
        return [c for c in self.fake.calls() if is_security(c)]
