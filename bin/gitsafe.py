"""Git reads the server can trust while a kod session (same OS user) may have changed the repository's own git state.

A kod session can hide a change from `git diff` / `git ls-files`: `git update-index --assume-unchanged` or
`--skip-worktree` (flagged paths are never compared), a clean filter (filter.<x>.clean in .git/config +
.git/info/attributes or .gitattributes), an external diff, or an ignore rule (.git/info/exclude, core.excludesFile).
So every server git read
- runs with argv(): CONFIG plus filter_overrides() — every configured filter driver set to clean/smudge `cat`, an empty
  process and required=false, so the server never executes a session's filter command — (no global attributes/excludes
  file, no fsmonitor, no hooks, quoted paths; every diff also passes
  --no-ext-diff --no-textconv) and lists untracked files with UNTRACKED (only the repository's own .gitignore files,
  never .git/info/exclude or core.excludesFile);
- and the review panel checks the rest with tricks(): flagged paths (`git ls-files -v`: a lowercase tag =
  assume-unchanged, `S` = skip-worktree) and, when the local git state changed since the kod step started (state_digest
  recorded at its start as `taban_git_ozet`, or — no digest — when it holds any filter / diff driver / attributes /
  exclude rule), every tracked file with a filter attribute: their raw bytes (`hash-object --no-filters`) are compared
  with the base commit's blob. A differing file is a hidden change: it joins the changed paths and forces risk yüksek
  with the reason "git durumu değişikliği gizleyebilir: …".
Read-only: nothing here writes to the repository (hash-object without -w).
"""
import hashlib
import os
import re
import subprocess

CONFIG = ("-c", "core.attributesFile=/dev/null", "-c", "core.excludesFile=/dev/null", "-c", "core.quotePath=true",
          "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat")
# (an external diff and textconv are switched off per command: every server diff passes --no-ext-diff --no-textconv)
UNTRACKED = ("ls-files", "--others", "--exclude-per-directory=.gitignore")
# local config keys that can make a change invisible to git diff / ls-files
HIDING_CONFIG = re.compile(r"^(filter\.|diff\.[^.]+\.(command|textconv)|core\.(attributesfile|excludesfile|autocrlf"
                           r"|safecrlf|eol|ignorecase|fsmonitor|sparsecheckout)\b)", re.I)
MAX_FILES = 20000
FILTER_KEY = re.compile(r"^filter\.(.+)\.(clean|smudge|process|required)$", re.I)


def filter_overrides(folder, git_bin="git"):
    """-c settings that neutralise every configured filter driver (local, global, system, included config) for one
    server git call: clean/smudge = `cat` (content passes unchanged), process = "" (git 2.48: an empty value turns the
    long-running process off), required = false. Reading the config runs no filter. A session-controlled filter
    command is therefore never executed by the server (diff, status, add -A into a temporary index, worktree add,
    apply all check filters)."""
    try:
        proc = subprocess.run([git_bin, *CONFIG, "-C", folder, "config", "--get-regexp", r"^filter\."],
                              capture_output=True, timeout=TIMEOUT, env=_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return []
    names = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        m = FILTER_KEY.match(line.split(" ", 1)[0])
        if m and m.group(1) not in names and "\n" not in m.group(1):
            names.append(m.group(1))
    out = []
    for name in names:
        out += ["-c", f"filter.{name}.clean=cat", "-c", f"filter.{name}.smudge=cat", "-c", f"filter.{name}.process=",
                "-c", f"filter.{name}.required=false"]
    return out


def argv(git_bin, folder, *extra_config):
    """The start of every server git call in a project repository: CONFIG, the filter overrides, extra -c items."""
    out = [git_bin, *CONFIG, *filter_overrides(folder, git_bin)]
    for item in extra_config:
        out += ["-c", item]
    return out + ["-C", folder]
TIMEOUT = 60


def _env():
    return dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", LC_ALL="C",
                GIT_LFS_SKIP_SMUDGE="1")


def run(folder, args, git_bin="git", data=None, timeout=TIMEOUT):
    """stdout bytes of a git read in folder with CONFIG, or None when git fails."""
    try:
        proc = subprocess.run([*argv(git_bin, folder), *args], input=data, capture_output=True,
                              timeout=timeout, env=_env(), stdin=None if data is not None else subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git_dir(top, git_bin="git"):
    out = run(top, ["rev-parse", "--absolute-git-dir"], git_bin)
    return out.decode("utf-8", "replace").strip() if out else ""


def _meaningful(path):
    """The non-comment, non-blank lines of a file (an absent file: "")."""
    try:
        with open(path, "rb") as f:
            raw = f.read(256 * 1024)
    except OSError:
        return ""
    lines = [line.strip() for line in raw.decode("utf-8", "replace").splitlines()]
    return "\n".join(line for line in lines if line and not line.startswith("#"))


def local_state(top, git_bin="git"):
    """The repository-local git state that can hide changes: (config lines, .git/info/attributes, .git/info/exclude)."""
    out = run(top, ["config", "--local", "--list"], git_bin)  # (the filter overrides are -c: not in --local)
    config = sorted(line for line in (out or b"").decode("utf-8", "replace").splitlines()
                    if HIDING_CONFIG.match(line.split("=", 1)[0]))
    git_dir = _git_dir(top, git_bin)
    attributes = _meaningful(os.path.join(git_dir, "info", "attributes")) if git_dir else ""
    exclude = _meaningful(os.path.join(git_dir, "info", "exclude")) if git_dir else ""
    return "\n".join(config), attributes, exclude


def state_digest(top, git_bin="git"):
    """sha256 of local_state() (recorded when the kod step starts: records.py taban_git_ozet)."""
    config, attributes, exclude = local_state(top, git_bin)
    return hashlib.sha256("\0".join((config, attributes, exclude)).encode("utf-8")).hexdigest()


def flagged(top, git_bin="git"):
    """The tracked paths flagged assume-unchanged (lowercase tag) or skip-worktree (`S`) in `git ls-files -v`."""
    out = run(top, ["ls-files", "-v", "-z"], git_bin)
    paths = []
    for entry in (out or b"").decode("utf-8", "replace").split("\0"):
        if len(entry) > 2 and (entry[0].islower() or entry[0] == "S"):
            paths.append(entry[2:])
    return paths


def filtered(top, git_bin="git"):
    """The tracked paths that have a filter attribute (check-attr, with the repository's own attributes)."""
    names = run(top, ["ls-files", "-z"], git_bin)
    if not names:
        return []
    out = run(top, ["check-attr", "-z", "--stdin", "filter"], git_bin, data=names)
    parts = (out or b"").decode("utf-8", "replace").split("\0")
    found = []
    for i in range(0, len(parts) - 2, 3):
        path, value = parts[i], parts[i + 2]
        if value not in ("unspecified", "unset", ""):
            found.append(path)
    return found


def differing(top, taban, paths, git_bin="git"):
    """The paths whose raw worktree bytes (no filters) differ from the base commit's blob (a missing file counts)."""
    paths = [p for p in dict.fromkeys(paths) if p][:MAX_FILES]
    if not paths:
        return []
    tree = run(top, ["ls-tree", "-r", "-z", taban], git_bin)
    blobs = {}
    for entry in (tree or b"").decode("utf-8", "replace").split("\0"):
        if "\t" in entry:
            meta, path = entry.split("\t", 1)
            blobs[path] = meta.split()[-1]
    present = [p for p in paths if "\n" not in p and os.path.isfile(os.path.join(top, p))
               and not os.path.islink(os.path.join(top, p))]
    hashes = run(top, ["hash-object", "--no-filters", "--stdin-paths"], git_bin,
                 data="\n".join(present).encode("utf-8") + b"\n") if present else b""
    now = dict(zip(present, (hashes or b"").decode().split()))
    return [p for p in paths if now.get(p) != blobs.get(p)]


def tricks(top, taban, start_digest="", git_bin="git"):
    """{"hidden": paths whose change git does not show, "reasons": Turkish lines} (see the module doc)."""
    reasons, candidates = [], []
    flags = flagged(top, git_bin)
    if flags:
        candidates += flags
    config, attributes, exclude = local_state(top, git_bin)
    digest = hashlib.sha256("\0".join((config, attributes, exclude)).encode("utf-8")).hexdigest()
    changed = digest != start_digest if start_digest else bool(config or attributes or exclude)
    if changed:
        what = [name for name, value in (("yerel git ayarı (filter/diff/core)", config),
                                         (".git/info/attributes", attributes), (".git/info/exclude", exclude))
                if value]
        reasons.append("yerel git durumu kod adımından bu yana değişti" if start_digest else
                       "yerel git durumu kayıtsız ve dolu" + (f" ({', '.join(what)})" if what else ""))
        candidates += filtered(top, git_bin)
    hidden = differing(top, taban, candidates, git_bin) if candidates else []
    if flags:
        reasons.append(f"assume-unchanged / skip-worktree işaretli {len(flags)} dosya")
    if hidden:
        reasons.append(f"git'in göstermediği {len(hidden)} değişen dosya")
    return {"hidden": hidden, "reasons": reasons if (hidden or changed) else []}
