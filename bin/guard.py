#!/usr/bin/env python3
"""PreToolUse hook for the CEO session (registered in .claude/settings.json).

Deny rules in settings cannot see every Bash route (lower-case paths, ~, $HOME, cd, python -c, ...), so this hook
checks the paths and commands the CEO is about to use and blocks (exit 2) when they reach:
- The owner's privacy rules, ofis.json `guvenlik` (bin/yasaklar.py; plan "2. Aşama"): a forbidden project
  (`yasak_yollar`: the name as a word, in any case or script), a credential word in a file name (`yasak_kelimeler`)
  and the vault's private folders (`ozel_klasorler`). This process is new on every call: a missing ofis.json (a fresh
  clone) means yasaklar.VARSAYILAN (the generic credential words only); an ofis.json that is not valid JSON or whose
  `guvenlik` is malformed blocks every guarded call (exit 2) until it is fixed, and so does a bin/yasaklar.py that
  cannot be loaded,
- a hand-written `claude --bg` (project sessions are started only by bin/launch.py),
- writes to the server's trusted records durum/kontroller/, durum/isler/, durum/akislar/, durum/zamanlanmis/,
  durum/model_secimi/, durum/duyurular/, durum/sistem/ and durum/sunucu.json
  (the owner's decisions, 2026-11-11: they change only through bin/ofis.py and the server, never by hand; reading them
  with the Read tool stays allowed. durum/duyurular/ since 2026-11-12: an unexpired announcement goes into every
  project session's contract, so a forged record would speak as the owner. durum/sistem/ since 2026-11-12: the Sunucu
  odası's domain cache decides the CEO's domain notices; only the server's DomainKontrol writes it, from Python).
File contents being written are not inspected, only where they go.

How paths are read (Codex reviews 2026-11-12):
- a tool path is made absolute against the hook input's cwd and checked both normalised (the visible intent) and with
  its symbolic links resolved (realpath of the un-normalised path, so `link/..` goes up from the link's target; for a
  path that does not exist yet, its deepest existing parent);
- a Bash command is checked as written, with its quotes and backslash escapes removed, and word by word: every word
  (a bare name, redirect and tee targets included) is resolved against the working directory — the call's cwd, then
  every `cd` in the command — and checked like a tool path; the working directory itself must not be inside a
  trusted record folder or a private folder;
- deleting, moving, copying onto, linking or changing the mode/owner of a folder that holds the trusted records or
  the private vault folders (or one of its parents: durum/, the repository, the vault, the home folder) is blocked;
- a Grep / Glob search must not start at the vault or above it (its private folders would be searched), nor inside a
  private or forbidden folder; without a path the search starts at the cwd;
- bad or unexpectedly shaped input, and any internal error, fails closed.
Honest limit: a Bash command is checked as text. Not seen: a variable other than $HOME (`d=durum; touch $d/isler/x`),
eval of a variable, a script written to a file and run later, an interpreter given code (python3 -c, node -e, a heredoc
fed to python3 -), aliases and functions, paths fed on stdin (xargs) or produced by a program. The deny rules in
.claude/settings.json and .claude/settings.local.json and "a project session's text is data" are the second layer.
"""
import codecs
import glob
import json
import os
import re
import shlex
import sys

# The owner's privacy rules (the forbidden projects, the credential words, the vault's private folders) come from
# ofis.json `guvenlik` through bin/yasaklar.py (rules(), below). The module is loaded from its file next to this
# hook, never through sys.path: under `python3 -I` the system site-packages still come first, and a `yasaklar`
# installed there must not replace the rules. yasaklar imports only the standard library.
import importlib.util  # noqa: E402


def _load_yasaklar():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yasaklar.py")
    loaded = sys.modules.get("yasaklar")
    # An in-process caller (the server, tests) that already imported bin/yasaklar.py shares its module and cache;
    # a module of that name from anywhere else is ignored.
    loaded_file = getattr(loaded, "__file__", None)
    if loaded_file and os.path.exists(loaded_file) and os.path.samefile(loaded_file, path):
        return loaded
    spec = importlib.util.spec_from_file_location("yasaklar", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if loaded is None:
        sys.modules["yasaklar"] = module
    return module


try:
    yasaklar = _load_yasaklar()
except BaseException:  # missing, renamed, a syntax error, even a SystemExit(0) inside it: never exit 1 (non-blocking)
    if __name__ != "__main__":
        raise  # an in-process importer (the server, tests) sees the real error
    print("guard: cannot load bin/yasaklar.py; blocking to be safe.", file=sys.stderr)
    sys.exit(2)
# Shell quoting and backslash escapes split words without changing the path (`dur"um"/isler`, `claude "--bg"`): a
# command is also checked with them removed.
SHELL_ESCAPE = re.compile(r"\\(.)", re.S)
SHELL_QUOTES = re.compile(r"[\"']")
MANUAL_BG = re.compile(r"(?<![\w-])claude\s+(?:[^|;&\n]*\s)?--(?:bg|background)(?![\w-])")
TRUSTED_DIRS = ("kontroller", "isler", "akislar", "zamanlanmis", "model_secimi", "duyurular", "sistem")
TRUSTED_FILES = ("sunucu.json",)
TRUSTED_PATH = re.compile(
    r"/durum/(?:(?:kontroller|isler|akislar|zamanlanmis|model_secimi|duyurular|sistem)(?:/|$)|sunucu\.json$)")
# In a shell command the path may be relative or split by `cd durum && ... isler/x`.
TRUSTED_IN_SHELL = re.compile(
    r"durum/(?:kontroller|isler|akislar|zamanlanmis|model_secimi|duyurular|sunucu\.json)\b|\bkontroller/"
    # sistem is also the name of bin/sistem.py and test/test_sistem.py: only the folder itself counts.
    r"|durum/sistem(?![\w.-])")
TRUSTED_SPLIT = re.compile(r"\b(?:isler|akislar|zamanlanmis|model_secimi|duyurular|sistem)/|\bsunucu\.json\b")
# The split form only counts after changing into a durum folder (`cd durum`, `cd .../durum`), so the vault's
# OFIS/Isler/ paths and its "durum:" frontmatter field never trigger it.
CD_DURUM = re.compile(r"\bcd\s+['\"]?[^\s;&|]*(?<![\w-])durum(?:/[^\s;&|'\"]*)?['\"]?(?:\s|;|&|\||$)")
REPEATED_SLASH = re.compile(r"/{2,}")
DOT_SEGMENT = re.compile(r"/\./")
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
TRUSTED_REASON = ("the server's trusted records (durum/kontroller, durum/isler, durum/akislar, durum/zamanlanmis, durum/model_secimi, "
                  "durum/duyurular, durum/sistem, durum/sunucu.json) "
                  "change only through bin/ofis.py and the server.")
PROTECTED_REASON = ("deleting, moving, copying onto or changing a folder that holds the trusted records or the private "
                    "vault folders (or one of its parents) is not allowed.")
SEARCH_REASON = ("a search from the vault or one of its parent folders reaches the private notes; search inside "
                 "OFIS/ (or another folder of the vault) instead.")

REPO = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_VAULT = "~/Documents/Obsidian Vault"
# Extra vault roots (os.pathsep-separated): they only add protection, never replace the configured vault.
EXTRA_VAULT_ENV = "OFIS_GUARD_EK_KASA"

# Commands that delete, move, overwrite, link or re-permission their arguments.
DESTRUCTIVE = {"rm", "rmdir", "unlink", "mv", "cp", "rsync", "tar", "ln", "chmod", "chown", "chgrp", "shred"}
# Words in front of the real program.
PREFIXES = {"sudo", "doas", "command", "builtin", "exec", "nohup", "time", "env", "nice", "xargs", "caffeinate", "arch",
            "stdbuf", "ionice", "watch", "unbuffer", "chronic", "nocache"}
# Wrappers whose first plain argument is theirs (a duration, a lock file, a typescript file), not the program.
PREFIXES_WITH_VALUE = {"timeout", "gtimeout", "flock", "script"}
# Shell reserved words in front of a command: `{ rm …; }`, `if …; then rm …; fi`, `! mv …`, `do rm …; done`.
KEYWORDS = {"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "case", "esac", "in",
            "select", "function", "coproc"}
SEPARATORS = re.compile(r"^[;&|()]+$")
REDIRECT = re.compile(r"^\d*[<>]+&?$")

# Which tool_input fields hold a path or command, per tool.
FIELDS = {
    "Bash": ("command",),
    "Read": ("file_path",),
    "Edit": ("file_path",),
    "Write": ("file_path",),
    "NotebookEdit": ("notebook_path",),
    "Glob": ("path", "pattern"),
    "Grep": ("path", "glob"),
}
# The field each guarded tool cannot do without; the other fields of FIELDS are optional (absent or null).
REQUIRED = {"Bash": "command", "Read": "file_path", "Edit": "file_path", "Write": "file_path",
            "NotebookEdit": "notebook_path", "Glob": "pattern"}
GLOB_CHARS = re.compile(r"[*?\[{]")


fold = yasaklar.fold


def rules():
    """The privacy rules in force: this repository's ofis.json `guvenlik` (bin/yasaklar.py). This process is new on every
    call: a missing file gives yasaklar.VARSAYILAN; a broken one raises yasaklar.Bozuk (no last good value to keep),
    which main() turns into a block."""
    return yasaklar.kurallar()


def tidy(text):
    """Collapses `//` and `/./` so `durum//isler` or `./durum/./sunucu.json` match like the plain spelling."""
    text = REPEATED_SLASH.sub("/", text)
    while DOT_SEGMENT.search(text):
        text = DOT_SEGMENT.sub("/", text)
    return text


def base_dir(event):
    """The folder a relative path is resolved against: the hook input's cwd, else the project, else our own cwd."""
    for cand in (event.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")):
        if isinstance(cand, str) and os.path.isabs(cand):
            return cand
    return os.getcwd()


def absolute(value, base):
    """A path as an absolute, normalised path (so `./durum/isler/x`, `bin/../durum/isler/x` and `<private folder>/x` are
    checked like their absolute spelling); `~` is the home folder."""
    path = os.path.expanduser(value)
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return os.path.normpath(tidy(path))  # also resolves `durum/taslak/../isler`


def joined(value, base):
    """A path made absolute but NOT normalised: `link/..` must be resolved by realpath after the link (the OS follows
    the link before the `..`)."""
    path = os.path.expanduser(value)
    return path if os.path.isabs(path) else os.path.join(base, path)


def spellings(path, raw=None):
    """The path as written (normalised: the visible intent) and with its symbolic links resolved — realpath of the
    un-normalised path (a `..` after a link goes up from the link's target), which also resolves the existing part of a
    path that does not exist yet."""
    out = [path]
    for cand in ((raw, path) if raw else (path,)):
        try:
            real = os.path.realpath(cand)
        except (OSError, ValueError):
            continue
        if real not in out:
            out.append(real)
    return out


def resolved(value, base):
    """Every spelling of a tool or command path to check."""
    return spellings(absolute(value, base), joined(value, base))


def key(path):
    """A comparison key for a path: normalised, folded (macOS paths are case-insensitive)."""
    return fold(os.path.normpath(path))


def inside(path_key, root_key):
    """Is path_key root_key itself or below it?"""
    root = root_key.rstrip("/")
    return path_key == root_key or path_key == root or path_key.startswith(root + "/")


def vault_roots():
    roots = [DEFAULT_VAULT]
    try:
        with open(yasaklar.ofis_json(), encoding="utf-8") as f:  # this repository's (or the test-only override)
            cfg = json.load(f)
        v = cfg.get("vault_ofis") if isinstance(cfg, dict) else None
        if isinstance(v, str) and v.strip():
            roots.append(os.path.dirname(os.path.expanduser(v.strip()).rstrip("/")))
    except (OSError, ValueError):
        pass
    roots += [p for p in os.environ.get(EXTRA_VAULT_ENV, "").split(os.pathsep) if p.strip()]
    out = []
    for r in roots:
        for s in spellings(os.path.normpath(os.path.expanduser(r))):
            if key(s) not in out:
                out.append(key(s))
    return out


def protected_keys():
    """The folders (and the record file) that no destructive command may reach, as keys."""
    paths = [os.path.join(REPO, "durum", d) for d in TRUSTED_DIRS + TRUSTED_FILES]
    paths += [os.path.join(v, p) for v in vault_roots() for p in rules().klasorler]
    out = []
    for p in paths:
        for s in spellings(p):
            out.append(key(s))
    return out


def unquote(command):
    """The command with backslash escapes resolved and every quote character removed (a check copy, never run)."""
    return SHELL_QUOTES.sub("", SHELL_ESCAPE.sub(r"\1", command))


def text_reason(tool, text):
    r = rules()
    if r.yol_kelimesi.search(text):
        return f"{r.yol_adi()} is outside the office; the CEO never touches {r.yol_adi()} paths."
    if r.kelime.search(text):
        return "the vault's credential notes are off-limits for the CEO."
    if r.klasor_yolu.search(text) or (tool == "Bash" and r.klasor_kabukta.search(text)):
        return f"{r.klasor_adi()} in the vault are off-limits for the CEO."
    if tool in WRITE_TOOLS and TRUSTED_PATH.search(text):
        return TRUSTED_REASON
    if tool == "Bash" and (TRUSTED_IN_SHELL.search(text) or (CD_DURUM.search(text) and TRUSTED_SPLIT.search(text))):
        return TRUSTED_REASON
    if tool == "Bash" and MANUAL_BG.search(text):
        return "start project sessions only with `python3 bin/launch.py <project> \"<task>\"`."
    return None


def path_reason(tool, paths):
    """A path's spellings (resolved()): blocked when any of them is."""
    for s in paths:
        why = text_reason(tool, fold(s))
        if why:
            return why
    return None


# --- Bash ---

def words_of(command):
    """The command's words (shlex with punctuation, no comments); on a quoting error, whitespace words."""
    text = command.replace("\n", " ; ")
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return re.findall(r"[;&|()<>]+|[^\s;&|()<>]+", text)


def segments(words):
    """Simple commands: [(args, redirect targets)]; `;`, `&&`, `||`, `|`, `(`, `)` separate them."""
    out, args, targets, redirect = [], [], [], False
    for w in words:
        if SEPARATORS.match(w):
            if args or targets:
                out.append((args, targets))
            args, targets, redirect = [], [], False
        elif REDIRECT.match(w):
            redirect = True
        elif redirect:
            targets.append(w)
            redirect = False
        else:
            args.append(w)
    if args or targets:
        out.append((args, targets))
    return out


# The options of a wrapper that take a value (`caffeinate -t 1`, `xargs -I {}`, `sudo -u root`, `exec -a x`).
WRAPPER_VALUE_OPTS = {
    "caffeinate": {"-t", "-w"}, "exec": {"-a"}, "arch": {"-arch"},
    "xargs": {"-I", "-L", "-P", "-s", "-E", "-d", "-n", "-J", "-R", "-S", "-a"},
    "env": {"-u", "-C", "-P", "-S", "--unset", "--chdir", "--split-string"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-U", "-r", "-t", "-D", "-T"}, "doas": {"-u", "-C"},
    "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "time": {"-o", "-f"}, "watch": {"-n", "-d"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"}, "gtimeout": {"-s", "-k", "--signal", "--kill-after"},
    "flock": {"-w", "-E", "-c", "--timeout", "--conflict-exit-code", "--command"}, "stdbuf": {"-i", "-o", "-e"},
    "script": {"-t", "-T"},
}


def program(args):
    """(program base name, its arguments) after assignments, shell keywords and wrapper words with their options
    (`sudo -u x`, `env X=1`, `nice -n 5`, `timeout 5`, `{`, `if`, `!`)."""
    i = 0
    while i < len(args):
        w = args[i]
        name = os.path.basename(w)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) or w in KEYWORDS:
            i += 1
            continue
        if name in PREFIXES or name in PREFIXES_WITH_VALUE:
            i += 1
            vals = WRAPPER_VALUE_OPTS.get(name, set())
            while i < len(args) and args[i].startswith("-") and args[i] != "-":
                opt = args[i]
                i += 1
                if opt == "--":
                    break
                if opt in vals and i < len(args):
                    i += 1
            if name in PREFIXES_WITH_VALUE:
                i += 1  # the duration / lock file / typescript file
            continue
        break
    if i >= len(args):
        return "", []
    return os.path.basename(args[i]), args[i + 1:]


def env_strings(args):
    """The command strings `env -S '…'` / `--split-string=…` splits and runs."""
    out = []
    for i, w in enumerate(args):
        if os.path.basename(w) != "env":
            continue
        j = i + 1
        while j < len(args):
            a = args[j]
            if a in ("-S", "--split-string") and j + 1 < len(args):
                out.append(args[j + 1])
                j += 2
                continue
            if a.startswith("--split-string="):
                out.append(a.split("=", 1)[1])
            elif a.startswith("-S") and len(a) > 2:
                out.append(a[2:])
            elif not a.startswith("-") and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a):
                break
            j += 1
    return out


def substitutions(text, quotes=True):
    """The code of every `$(…)` and `` `…` `` the shell runs in text — single quotes hide them only outside double
    quotes (and not at all in a heredoc body: quotes=False); None when one is unbalanced (fail closed)."""
    out, i, n, dq = [], 0, len(text), False
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if quotes and c == "'" and not dq:
            j = text.find("'", i + 1)
            if j < 0:
                return None
            i = j + 1
            continue
        if quotes and c == '"':
            dq = not dq
            i += 1
            continue
        if text.startswith("$(", i):
            depth, j, q = 1, i + 2, None
            while j < n and depth:
                d = text[j]
                if d == "\\":
                    j += 2
                    continue
                if q:
                    if d == q:
                        q = None
                elif d in ("'", '"'):
                    q = d
                elif d == "(":
                    depth += 1
                elif d == ")":
                    depth -= 1
                j += 1
            if depth or q:
                return None
            out.append(text[i + 2:j - 1])
            i = j
            continue
        if c == "`":
            j = i + 1
            while j < n and text[j] != "`":
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                return None
            out.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return out


def expand_home(word):
    return word.replace("${HOME}", "~").replace("$HOME", "~")


GIT_VALUE_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env")
GIT_DIR_OPTS = ("-C", "--git-dir", "--work-tree")
GLOB_LIMIT = 2000  # more matches than this: treated as reaching a protected path (fail closed)
# Commands that write their arguments besides DESTRUCTIVE (sed / perl only with -i).
WRITING = DESTRUCTIVE | {"tee", "touch", "truncate", "dd", "install", "mkdir", "patch"}
IN_PLACE = {"sed", "perl"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
SUBSTITUTION = re.compile(r"`([^`]*)`|\$\(([^()]*)\)")
# Where a word stops being literal: a glob, a brace, a variable or a command substitution.
NOT_LITERAL = re.compile(r"[*?\[{$`]")
MAX_DEPTH = 3
READ_REASON = ("durum/ holds the server's trusted records: read a file inside it (e.g. durum/taslak/<file>), not the "
               "folder itself.")
PRIVATE_PARENT_REASON = ("a folder that contains the vault's private folders (the vault itself or one of its parents) "
                         "is off-limits; work inside OFIS/ instead.")


def dry_run(rest):
    return any(w in ("-n", "--dry-run") or (re.match(r"^-[a-zA-Z]+$", w) and "n" in w) for w in rest)


def git_parts(rest):
    """git's global options -> ([(option, directory value)], subcommand, its arguments)."""
    dirs, i = [], 0
    while i < len(rest):
        w = rest[i]
        if w in GIT_VALUE_OPTS:
            if w in GIT_DIR_OPTS:
                dirs.append((w, rest[i + 1] if i + 1 < len(rest) else ""))
            i += 2
            continue
        m = re.match(r"^(--[a-z-]+)=(.*)$", w)
        if m and m.group(1) in GIT_VALUE_OPTS:
            if m.group(1) in GIT_DIR_OPTS:
                dirs.append((m.group(1), m.group(2)))
            i += 1
            continue
        if w.startswith("-"):
            i += 1
            continue
        break
    return dirs, (rest[i] if i < len(rest) else ""), rest[i + 1:]


def git_targets(sub, args):
    """What a destructive git subcommand acts on: pathspecs, None for the whole work tree; [] when it writes nothing."""
    plain = [w for w in args if not w.startswith("-")]
    if sub == "clean":
        return [] if dry_run(args) else (plain or None)
    if sub == "rm":
        return plain
    if sub == "checkout":
        if "--" in args:
            return [w for w in args[args.index("--") + 1:] if not w.startswith("-")] or None
        return ["."] if "." in plain else []
    if sub == "restore":
        return plain or None
    if sub == "reset":
        return None if any(w in ("--hard", "--merge", "--keep") for w in args) else []
    if sub == "stash":
        if any(w in ("--include-untracked", "--all") or re.match(r"^-[a-zA-Z]*[ua][a-zA-Z]*$", w) for w in args):
            return None
        return []
    return []


def find_writes(rest):
    return "-delete" in rest or any(w in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(rest)
                                    and os.path.basename(rest[i + 1]) in WRITING for i, w in enumerate(rest))


RECURSIVE_READERS = {"rg", "ag", "ack", "fd", "fdfind", "tree", "du", "find"}


def option_value(rest, shorts, longs):
    """The value of `-C dir`, `-Cdir`, `--directory=dir`, `--directory dir`; None when absent."""
    for i, w in enumerate(rest):
        if w in shorts or w in longs:
            return rest[i + 1] if i + 1 < len(rest) else ""
        for o in longs:
            if w.startswith(o + "="):
                return w[len(o) + 1:]
        for o in shorts:
            if len(o) == 2 and w.startswith(o) and len(w) > 2:
                return w[2:]
    return None


def extraction_target(prog, rest):
    """Where an archive or a patch is unpacked (its members are unknown): the -C / -d value or the cwd; None when the
    command extracts nothing."""
    if prog in ("tar", "bsdtar", "gtar"):
        first = rest[0] if rest else ""
        mode = any(w in ("-x", "--extract", "--get") or re.match(r"^-[A-Za-z]*x", w) for w in rest) or \
            bool(re.match(r"^[A-Za-z]*x[A-Za-z]*$", first))
        return (option_value(rest, ("-C",), ("--directory",)) or ".") if mode else None
    if prog == "unzip":
        if any(w in ("-l", "-v", "-t", "-Z", "-z") for w in rest):
            return None
        return option_value(rest, ("-d",), ()) or "."
    if prog == "cpio":
        mode = any(w in ("--extract",) or re.match(r"^-[A-Za-z]*i", w) for w in rest)
        return (option_value(rest, ("-D",), ("--directory",)) or ".") if mode else None
    if prog in ("7z", "7za", "7zr"):
        if rest and rest[0] in ("x", "e"):
            out = next((w[2:] for w in rest if w.startswith("-o") and len(w) > 2), None)
            return out or "."
        return None
    if prog == "pax":
        return "." if any(re.match(r"^-[A-Za-z]*r", w) for w in rest) else None
    if prog == "patch":
        if any(w in ("--dry-run", "-C", "--check") for w in rest):
            return None
        return option_value(rest, ("-d",), ("--directory",)) or "."
    return None


def recursive_read(prog, rest):
    """A recursive search or listing: its root is (also) the cwd."""
    if prog in RECURSIVE_READERS:
        return True
    if prog in ("grep", "egrep", "fgrep"):
        return any(w in ("--recursive", "--dereference-recursive") or re.match(r"^-[A-Za-z]*[rR]", w) for w in rest)
    if prog == "ls":
        return any(re.match(r"^-[A-Za-z]*R", w) or w == "--recursive" for w in rest)
    return False


def writes(prog, rest):
    if prog in IN_PLACE:
        return any(w.startswith("-i") or w.startswith("--in-place") for w in rest)
    if prog == "find":
        return find_writes(rest)
    return prog in WRITING


# Options of a program that run it (or what follows) in another directory.
CHDIR_OPTS = {"env": ("-C", "--chdir"), "make": ("-C", "--directory"), "gmake": ("-C", "--directory"),
              "npm": ("--prefix",), "pnpm": ("--prefix", "-C", "--dir"), "yarn": ("--cwd",), "sudo": ("-D", "--chdir"),
              "git": ("-C", "--work-tree")}


def chdir_values(args):
    """The directories `env -C d`, `make -C d`, `npm --prefix d`, `sudo -D d`, `git -C d` (and `=` / attached forms)
    move to."""
    out, prog = [], None
    for i, w in enumerate(args):
        name = os.path.basename(w)
        if name in CHDIR_OPTS:
            prog = name
            continue
        if not prog:
            continue
        for o in CHDIR_OPTS[prog]:
            if w == o and i + 1 < len(args):
                out.append(args[i + 1])
            elif w.startswith(o + "="):
                out.append(w[len(o) + 1:])
            elif len(o) == 2 and w.startswith(o) and len(w) > 2:
                out.append(w[2:])
    return out


def command_dirs(segs, cwd):
    """The starting cwd and every directory a `cd` / `pushd` in the command names (each resolved against the cwd and
    against the directory reached so far): a subshell `(cd x)` or `cd -` must never hide where a later word runs."""
    dirs, cur = [os.path.normpath(cwd)], cwd
    for args, _ in segs:
        for val in chdir_values(args):  # env -C, make -C, npm --prefix, sudo -D, git -C: a cd for what follows
            if "$" in val or "`" in val:
                continue
            for b in (cwd, cur):
                for d in resolved(expand_home(val), b):
                    if d not in dirs:
                        dirs.append(d)
        prog, rest = program(args)
        if prog not in ("cd", "pushd"):
            continue
        dest = next((w for w in rest if not w.startswith("-")), "~")
        if dest == "-":
            continue
        cands = candidates(dest)
        if cands is None:
            return None
        for c in cands:
            if "$" in c or "`" in c:
                continue
            for b in (cwd, cur):
                if NOT_LITERAL.search(c):
                    hits = glob.glob(joined(c, b))
                    if len(hits) > GLOB_LIMIT:
                        return None
                    new = [os.path.normpath(h) for h in hits]
                else:
                    new = list(resolved(c, b))  # logical (`cd`) and physical (`cd -P`, links followed first)
                for d in new:
                    if d not in dirs:
                        dirs.append(d)
            if not NOT_LITERAL.search(c):
                cur = absolute(c, cur)
    return dirs


LINE_CONTINUATION = re.compile(r"\\\r?\n")
ANSI_C = re.compile(r"\$'((?:[^'\\]|\\.)*)'", re.S)
BRACE_LIMIT = 256


def decode_ansi_c(command):
    """`$'dur\\x75m'` -> `'durum'` (bash's ANSI-C quoting); None when it cannot be decoded safely (fail closed)."""
    def one(m):
        try:
            text = codecs.decode(m.group(1).encode("latin-1", "backslashreplace"), "unicode_escape")
        except (UnicodeError, ValueError):
            raise ValueError("ansi-c")
        if "'" in text or "\\" in text or "\x00" in text:
            raise ValueError("ansi-c")
        return "'" + text + "'"
    try:
        return ANSI_C.sub(one, command)
    except ValueError:
        return None


def expand_braces(word, limit=BRACE_LIMIT):
    """bash brace expansion (`a{b,c}d`, `{1..3}`, nested); None when it would give more than `limit` words."""
    out, todo = [], [word]
    while todo:
        w = todo.pop()
        start = None
        depth = 0
        found = None
        for i, ch in enumerate(w):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth:
                depth -= 1
                if depth == 0:
                    inner = w[start + 1:i]
                    parts, d, last = [], 0, 0
                    for j, c in enumerate(inner):
                        if c == "{":
                            d += 1
                        elif c == "}":
                            d -= 1
                        elif c == "," and d == 0:
                            parts.append(inner[last:j])
                            last = j + 1
                    parts.append(inner[last:])
                    rng = re.match(r"^(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])$", inner)
                    if len(parts) > 1:
                        found = (start, i, parts)
                        break
                    if rng:
                        a, b = rng.group(1), rng.group(2)
                        if a.lstrip("-").isdigit() and b.lstrip("-").isdigit():
                            lo, hi = int(a), int(b)
                            step = 1 if hi >= lo else -1
                            if abs(hi - lo) + 1 > limit:
                                return None
                            vals = [str(x) for x in range(lo, hi + step, step)]
                        elif a.isalpha() and b.isalpha():
                            step = 1 if ord(b) >= ord(a) else -1
                            vals = [chr(x) for x in range(ord(a), ord(b) + step, step)]
                        else:
                            vals = None
                        if vals:
                            found = (start, i, vals)
                            break
        if not found:
            out.append(w)
        else:
            a, b, parts = found
            todo += [w[:a] + part + w[b + 1:] for part in parts]
        if len(out) + len(todo) > limit:
            return None
    return out


def candidates(word):
    """A word's path candidates: the word, an option's value (`--opt=value`, `-oVALUE`), an assignment's value; `~`
    expanded. Options themselves are not paths."""
    words = expand_braces(word)
    if words is None:
        return None
    if len(words) > 1 or words[0] != word:
        out = []
        for w in words:
            c = candidates(w)
            if c is None:
                return None
            out += c
        return out
    word = expand_home(word)
    out = [] if word.startswith("-") else [word]
    m = re.match(r"^--[^=]+=(.*)$", word)
    if m:
        out.append(m.group(1))
    elif re.match(r"^-[A-Za-z]", word) and len(word) > 2:
        out.append(word[2:])
    elif "=" in word and not word.startswith("-") and not word.startswith("="):
        out.append(word.split("=", 1)[1])
    return [c for c in out if c]


def reached(cand, base):
    """Every path a candidate may reach from base, links resolved: itself, or for a word that is not literal its literal
    prefix and the glob matches of it and of its parent patterns; None = too many matches (fail closed)."""
    m = NOT_LITERAL.search(cand)
    if not m:
        return list(resolved(cand, base))
    out = []
    prefix = cand[:m.start()]
    if prefix:
        out += resolved(prefix, base)
    if "$" in cand or "`" in cand:
        return out
    pattern, n = joined(cand, base), 0
    while GLOB_CHARS.search(pattern):
        for hit in glob.iglob(pattern):
            n += 1
            if n > GLOB_LIMIT:
                return None
            out += spellings(os.path.normpath(hit), hit)
        parent = os.path.dirname(pattern)
        if parent == pattern:
            break
        pattern = parent
    return out


HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SHELL_OPENER = re.compile(r"(?:^|[;&|(\s])(?:bash|sh|zsh|dash|ksh|fish|eval|source)(?:\s|$|<)")
# Programs whose arguments are text to print, never paths (their redirect targets still are).
TEXT_PROGRAMS = {"echo", "printf"}
MESSAGE_OPTS = ("-m", "--message")


def fed_to_shell(opener):
    """Is a heredoc's opener line a shell command (`bash <<EOF`, `/bin/zsh <<EOF`, `/usr/bin/env sh <<EOF`,
    `exec ksh <<EOF`, `x | bash <<EOF`)? Its body is then code. A heredoc for any other program is data (an
    interpreter's code is a documented limit)."""
    if SHELL_OPENER.search(opener):
        return True
    for args, _targets in segments(words_of(opener)):
        prog, _rest = program(args)
        if prog in SHELLS or prog in ("eval", "source", "."):
            return True
    return False


def heredoc_openers(line):
    """The real heredoc openers of one line: [(dash, delimiter, quoted)] for each `<<` (not `<<<`) at the top level of
    the line — not inside quotes, `$(…)`, `${…}`, backticks or `((…))` arithmetic, not after a `#` comment — and only
    in the exact simple forms `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`, `<<\\EOF` followed by a blank, a
    redirection, a pipe or the line end. A top-level `<<` in any other form makes the whole command have no heredoc
    (its lines stay commands: fail closed)."""
    out, i, n, stack = [], 0, len(line), []
    while i < n:
        c = line[i]
        top = stack[-1] if stack else None
        if top == "'":
            if c == "'":
                stack.pop()
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if top == '"':
            if c == '"':
                stack.pop()
            elif line.startswith("$(", i):
                stack.append("$(")
                i += 2
                continue
            elif line.startswith("${", i):
                stack.append("${")
                i += 2
                continue
            elif c == "`":
                stack.append("`")
            i += 1
            continue
        if top == "`" and c == "`":
            stack.pop()
            i += 1
            continue
        if top == "${" and c == "}":
            stack.pop()
            i += 1
            continue
        if c in ("'", '"'):
            stack.append(c)
        elif line.startswith("$((", i) or (line.startswith("((", i) and top in (None, "$(", "(")):
            stack.append("((")
            i += 3 if c == "$" else 2
            continue
        elif top == "((" and line.startswith("))", i):
            stack.pop()
            i += 2
            continue
        elif line.startswith("$(", i):
            stack.append("$(")
            i += 2
            continue
        elif line.startswith("${", i):
            stack.append("${")
            i += 2
            continue
        elif c == "`":
            stack.append("`")
        elif stack and top in ("$(", "(") and re.match(r"case(?![A-Za-z0-9_])", line[i:]) and \
                (i == 0 or line[i - 1] in " \t;&|("):
            return None  # a case pattern's `)` would close the frame too early: fail closed
        elif c == "(" and top in ("$(", "("):
            stack.append("(")
        elif c == ")" and top in ("$(", "("):
            stack.pop()
        elif c == "#" and not stack and (i == 0 or line[i - 1] in " \t;&|("):
            break
        elif (not stack or top in ("$(", "(")) and line.startswith("<<", i) and not line.startswith("<<<", i):
            m = re.match(r"<<(-?)[ \t]*(\\?)(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\3(?=$|[ \t;&|<>)])", line[i:])
            if not m or (m.group(2) and m.group(3)):
                return None
            out.append((m.group(1) == "-", m.group(4), bool(m.group(2) or m.group(3))))
            i += m.end()
            continue
        i += 1
    return out


def without_single_quotes(text):
    """The text with its single-quoted spans removed (the shell expands nothing inside them)."""
    return re.sub(r"'[^']*'", "''", text)


def strip_heredocs(command):
    """(the command without its heredoc bodies, [(the line that opened it, the body)]). A body is data — unless it is
    fed to a shell, which the caller checks as a command."""
    lines, out, bodies, pending = command.split("\n"), [], [], []
    body, current = [], None
    for line in lines:
        if current:
            dash, delim, quoted, opener = current
            if (line.lstrip("\t") if dash else line) == delim:
                bodies.append((opener, "\n".join(body), quoted))
                body, current = [], (pending.pop(0) if pending else None)
            else:
                body.append(line)
            continue
        out.append(line)
        openers = heredoc_openers(line)
        if openers is None:  # an opener the scan cannot read exactly: no line of the command is a body
            return command, []
        found = [(dash, delim, quoted, line) for dash, delim, quoted in openers]
        if found:
            current, pending = found[0], found[1:]
    if current:  # an unterminated heredoc runs to the end of the command
        bodies.append((current[3], "\n".join(body), current[2]))
    return "\n".join(out), bodies


def message_values(args):
    """Indices of the words that are a `git commit -m` / `--message` text."""
    skip = set()
    for i, w in enumerate(args):
        if w in MESSAGE_OPTS and i + 1 < len(args):
            skip.add(i + 1)
        elif w.startswith("--message=") or (w.startswith("-m") and len(w) > 2 and not w.startswith("--")):
            skip.add(i)
    return skip


def bash_reason(command, cwd, depth=0):
    if depth > MAX_DEPTH:
        return "the command nests shells too deeply to check; blocking to be safe."
    command = LINE_CONTINUATION.sub("", command)  # `dur\\<newline>um` is one word to the shell
    decoded = decode_ansi_c(command)
    if decoded is None:
        return "an ANSI-C quoted word ($'...') that cannot be checked; blocking to be safe."
    command = decoded
    # the command as written and its quote-normalised copy
    for text in (tidy(fold(command)), tidy(fold(unquote(command)))):
        why = text_reason("Bash", text)
        if why:
            return why
    # heredoc bodies are data for the path layer (the text rule above has read them); a body fed to a shell is a command
    command, bodies = strip_heredocs(command)
    for opener, body, _quoted in bodies:
        if fed_to_shell(opener):
            why = bash_reason(body, cwd, depth + 1)
            if why:
                return why
    # command substitutions run too: `...` and $(...) — outside single quotes and in unquoted heredoc bodies only
    for text, quotes in [(command, True)] + [(b, False) for _o, b, q in bodies if not q]:
        codes = substitutions(text, quotes)
        if codes is None:
            return "an unbalanced quote, $( or backtick that cannot be checked; blocking to be safe."
        for code in codes:
            why = bash_reason(code, cwd, depth + 1)
            if why:
                return why
    why = path_reason("Write", spellings(os.path.normpath(cwd)))
    if why:
        return f"the working directory is off-limits: {why}"
    segs = segments(words_of(command))
    dirs = command_dirs(segs, cwd)
    if dirs is None:
        return "a cd target with too many matches to check; blocking to be safe."
    for d in dirs[1:]:
        why = path_reason("Write", spellings(d))
        if why:
            return f"the working directory is off-limits: {why}"
    records = [key(s) for d in TRUSTED_DIRS + TRUSTED_FILES for s in spellings(os.path.join(REPO, "durum", d))]
    private = [key(s) for v in vault_roots() for p in rules().klasorler for s in spellings(os.path.join(v, p))]
    durum_keys = [key(s) for s in spellings(os.path.join(REPO, "durum"))]

    def verdict(paths, writing, bare, ancestors):
        """The one rule for every candidate path. `ancestors`: the command writes, extracts or searches recursively, so a
        parent folder of a protected one counts too; a plain read only must not be inside one."""
        if paths is None:
            return PROTECTED_REASON
        why = path_reason("Write", paths)  # inside a record, a private folder, a credential note, the excluded project
        if why:
            return why
        if not ancestors:
            return None
        for s in paths:
            k = key(s)
            if any(inside(p, k) for p in private):
                return PRIVATE_PARENT_REASON
            if any(inside(p, k) for p in records):
                if writing:
                    return PROTECTED_REASON
                # reading: only durum/ itself is refused (the repository, its parents and a bare word such as the
                # `durum` subcommand of `ofis.py` stay readable)
                if not bare and any(inside(k, dk) for dk in durum_keys):
                    return READ_REASON
        return None

    for args, targets in segs:
        prog, rest = program(args)
        # a program word that is not a plain name (`$cmd`, a quoted string): opaque — its arguments still get the path
        # rule (with the parent-folder rule), never a refusal of its own
        opaque = bool(re.search(r"[\s$`{}]", prog))
        for code in env_strings(args):
            why = bash_reason(code, cwd, depth + 1)
            if why:
                return why
        if prog in SHELLS:
            for i, w in enumerate(rest):
                if w == "--command" or re.match(r"^-[A-Za-z]*c[A-Za-z]*$", w):
                    if i + 1 < len(rest):
                        why = bash_reason(rest[i + 1], cwd, depth + 1)
                        if why:
                            return why
                    break
                if w.startswith("--command="):
                    why = bash_reason(w.split("=", 1)[1], cwd, depth + 1)
                    if why:
                        return why
                    break
        if prog == "eval":
            why = bash_reason(" ".join(rest), cwd, depth + 1)
            if why:
                return why
        writing = writes(prog, rest)
        bases = list(dirs)
        implicit = []
        if prog == "find" and find_writes(rest) and (not rest or rest[0].startswith("-")):
            implicit = ["."]
        # the cwd as an implicit target: an extraction (written) and a recursive search (read)
        target = extraction_target(prog, rest)
        if target is not None:
            implicit = implicit + [target]
            writing = True
        recursive = recursive_read(prog, rest)
        reads = ["."] if recursive else []
        if prog == "git":
            gdirs, sub, gargs = git_parts(rest)
            gt = git_targets(sub, gargs)
            writing = gt is None or bool(gt)
            for opt, val in gdirs:
                if opt in ("-C", "--work-tree") and not NOT_LITERAL.search(val):
                    bases = [absolute(expand_home(val), b) for b in bases]
            for b in bases:  # git's -C / --work-tree directory is a working directory too
                why = path_reason("Write", spellings(b))
                if why:
                    return f"the working directory is off-limits: {why}"
            if gt is None:
                implicit = ["."]
            if sub == "apply" and not any(w in ("--check", "--stat", "--numstat", "--summary") for w in gargs):
                implicit = implicit + ["."]
                writing = True
        # text arguments are data: echo / printf words, a git commit / tag message
        data = set(range(len(args))) if prog in TEXT_PROGRAMS else set()
        if prog == "git":
            data |= message_values(args)
        plain = [w for i, w in enumerate(args) if i not in data]
        words = [(w, False, dirs) for w in plain] + [(w, True, dirs) for w in targets] + [(w, True, bases) for w in implicit]
        words += [(w, False, dirs) for w in reads]
        if prog == "git":  # pathspecs are relative to git's own directory
            words += [(w, False, bases) for w in plain]
        for w, is_target, where in words:
            cands = candidates(w)
            if cands is None:
                return "a brace expansion too large to check; blocking to be safe."
            for cand in cands:
                bare = "/" not in cand and cand not in (".", "..") and not cand.startswith("~") and w not in reads
                for b in where:
                    why = verdict(reached(cand, b), writing or is_target, bare,
                                  writing or is_target or recursive or bool(implicit) or opaque)
                    if why:
                        return why
    return None


# --- Grep / Glob ---

def glob_prefix(pattern):
    """The leading components of a glob pattern that hold no wildcard (`../**/*.md` -> `..`)."""
    parts = pattern.split("/")
    keep = []
    for p in parts[:-1]:
        if GLOB_CHARS.search(p):
            break
        keep.append(p)
    if pattern.startswith("/") and not keep:
        return "/"
    return "/".join(keep) if keep != [""] else "/"


def search_reason(tool, tool_input, base):
    path = tool_input.get("path")
    path = path if isinstance(path, str) and path else "."
    roots = [resolved(path, base)]
    pattern = tool_input.get("pattern")
    if tool == "Glob" and isinstance(pattern, str):
        prefix = glob_prefix(os.path.expanduser(pattern))
        if prefix:
            roots.append(resolved(os.path.join(joined(path, base), prefix), base))
    vaults = vault_roots()
    for spell in roots:
        why = path_reason(tool, spell)
        if why:
            return why
        if any(inside(v, key(s)) for s in spell for v in vaults):
            return SEARCH_REASON
    return None


def check(event):
    """None when the call may go on, else the reason it is blocked. Every unexpected shape of a guarded call blocks."""
    if not isinstance(event, dict):
        return "unreadable hook input (not an object); blocking to be safe."
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        return "unreadable hook input (no tool name); blocking to be safe."
    if tool not in FIELDS:
        return None
    rules()  # read the rules up front: a broken ofis.json blocks every guarded call (yasaklar.Bozuk), not only some
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return f"unreadable {tool} input (not an object); blocking to be safe."
    base = base_dir(event)
    for field in FIELDS[tool]:
        value = tool_input.get(field)
        if value is None and field != REQUIRED.get(tool):
            continue
        if not isinstance(value, str):
            return f"unreadable {tool} input ({field} is missing or not text); blocking to be safe."
        if tool == "Bash":
            why = bash_reason(value, base)
        else:
            why = path_reason(tool, resolved(value, base))
        if why:
            return why
    if tool in ("Grep", "Glob"):
        return search_reason(tool, tool_input, base)
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        print("guard: unreadable hook input; blocking to be safe.", file=sys.stderr)
        return 2
    try:
        why = check(event)
    except yasaklar.Bozuk as exc:
        print(f"guard: ofis.json guvenlik is malformed: {exc}; blocking to be safe.", file=sys.stderr)
        return 2
    if why:
        print(f"Blocked by the office guard: {why}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:  # fail closed: a crash must never let a call through
        print(f"guard: internal error ({type(exc).__name__}); blocking to be safe.", file=sys.stderr)
        code = 2
    sys.exit(code)
