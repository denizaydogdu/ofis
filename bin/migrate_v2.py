#!/usr/bin/env python3
"""One-time migration of the vault to the phase 1 job layout (ADR-002).

    python3 bin/migrate_v2.py --vault "~/Documents/Obsidian Vault/OFIS" --dry-run    # print the plan only
    python3 bin/migrate_v2.py --vault "~/Documents/Obsidian Vault/OFIS"

1. Moves every flat OFIS/Isler/*.md note into its status folder: calisiyor / baslatiliyor (and the other active
   statuses) -> Devam-Edenler, sirada -> Siradakiler, anything else -> Bitenler. Contents are not changed.
2. Rewrites wikilinks [[OFIS/Isler/<name>...]] to [[<name>...]] (keeping #heading and |alias) in the notes under
   OFIS and in the vault's log.md and index.md (one level above OFIS). Nothing else in the vault is read or written.
Idempotent (a second run finds nothing to do); never overwrites a file (a conflict is reported, the source stays,
exit code 1); symlinks are neither moved nor rewritten; rewritten files are replaced atomically.
"""
import argparse
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs  # noqa: E402

LINK = re.compile(r"\[\[OFIS/Isler/([^\]/\\|#]+(?:#[^\]|]*)?(?:\|[^\]]*)?)\]\]")


def target_folder(status):
    return jobs.STATUS_FOLDER.get(status, jobs.DONE)


def plan_moves(ofis):
    isler = os.path.join(ofis, jobs.ISLER)
    moves = []
    try:
        entries = sorted(os.scandir(isler), key=lambda e: e.name)
    except OSError:
        return moves
    for e in entries:
        if e.name.startswith(".") or not e.name.endswith(".md") or not e.is_file(follow_symlinks=False):
            continue
        try:
            with open(e.path, encoding="utf-8") as f:
                _, meta, _ = jobs.parse(f.read(64 * 1024))
        except (OSError, UnicodeDecodeError):
            meta = {}
        moves.append((e.path, os.path.join(isler, target_folder(meta.get("durum")), e.name)))
    return moves


def link_files(ofis):
    out = []
    for folder, dirs, names in os.walk(ofis):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(folder, d)))
        out += [os.path.join(folder, n) for n in sorted(names) if n.endswith(".md") and not n.startswith(".")]
    parent = os.path.dirname(ofis)
    out += [os.path.join(parent, n) for n in ("log.md", "index.md")]
    return [p for p in out if os.path.isfile(p) and not os.path.islink(p)]


def _write_atomic(path, text):
    mode = os.stat(path).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=".migrate.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv, out=None):
    out = out or sys.stdout
    p = argparse.ArgumentParser(prog="migrate_v2.py", description="Move OFIS/Isler notes into the job folders.")
    p.add_argument("--vault", required=True, help="the OFIS folder of the vault")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv[1:])
    ofis = os.path.realpath(os.path.expanduser(args.vault))
    if not os.path.isdir(os.path.join(ofis, jobs.ISLER)):
        out.write(f"error: {ofis} has no {jobs.ISLER}/ folder; pass the vault's OFIS folder\n")
        return 2
    rel = lambda path: os.path.relpath(path, ofis)  # noqa: E731
    conflicts, changes = 0, 0
    for src, dst in plan_moves(ofis):
        if os.path.lexists(dst):
            out.write(f"skip {rel(src)}: {rel(dst)} exists (not overwritten)\n")
            conflicts += 1
            continue
        out.write(f"{'would move' if args.dry_run else 'move'} {rel(src)} -> {rel(dst)}\n")
        changes += 1
        if not args.dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(src, dst)
    if not args.dry_run:
        for folder in jobs.FOLDERS:
            os.makedirs(os.path.join(ofis, jobs.ISLER, folder), exist_ok=True)
    for path in link_files(ofis):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        new, count = LINK.subn(lambda m: f"[[{m.group(1)}]]", text)
        if not count:
            continue
        out.write(f"{'would rewrite' if args.dry_run else 'rewrite'} {count} link(s) in {rel(path)}\n")
        changes += 1
        if not args.dry_run:
            _write_atomic(path, new)
    if not changes and not conflicts:
        out.write("nothing to do\n")
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
