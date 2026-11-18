"""A bare Obsidian note name ([[2026-11-13]]) -> its path in the vault, for the page's obsidian:// links.

GET /api/not-yolu?ad=<name>[&tercih=<folder>] (bin/server.py) answers {yol, kasa}: yol is the note's path relative to
the vault root without ".md" (always "OFIS/…"), kasa the vault's name (the vault root's folder name) — the page builds
obsidian://open?vault=<kasa>&file=<yol> from them. Only plain files under OFIS/ count: no symlinked file or folder is
followed, no hidden folder (.obsidian, .trash), and nothing whose path reaches a forbidden project, the credential notes or the private
vault folders (adimlar.forbidden, the guard's patterns). A name that is a path, or carries a link's own syntax, is
refused. A bare name can exist in several folders: the one under the hinted OFIS sub-folder (`tercih`, from the
notice kind: Ozetler for the morning summary) wins, otherwise the newest file. Read-only; nothing else is returned.
"""
import os
import unicodedata

import adimlar

MAX_NAME = 200
MAX_FILES = 20000  # a walk that would look at more files than this stops (the vault's OFIS folder is far smaller)


def _valid_name(name):
    return (isinstance(name, str) and 0 < len(name) <= MAX_NAME and name.strip() == name and not name.startswith(".")
            and not any(c in name for c in "/\\[]|#^") and all(c >= " " and c != "\x7f" for c in name))


def bul(vault_ofis, ad, tercih=None):
    """{yol, kasa} of the note named `ad` under vault_ofis, or None."""
    if isinstance(ad, str) and ad.endswith(".md"):
        ad = ad[:-3]
    if not _valid_name(ad) or adimlar.forbidden(ad):
        return None
    if tercih is not None and tercih != "" and not _valid_name(tercih):
        return None
    try:
        top = os.path.realpath(vault_ofis)
        if not os.path.isdir(top) or os.path.islink(vault_ofis):
            return None
    except OSError:
        return None
    target = unicodedata.normalize("NFC", ad + ".md")  # macOS may keep a file name decomposed (NFD)
    found = []
    seen = 0
    for folder, dirs, files in os.walk(top, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(folder, d))
                         and not adimlar.forbidden(d))
        seen += len(files)
        if seen > MAX_FILES:
            break
        match = next((f for f in files if unicodedata.normalize("NFC", f) == target), None)
        if match is None:
            continue
        path = os.path.join(folder, match)
        rel = os.path.relpath(path, top)
        if os.path.islink(path) or not os.path.isfile(path) or adimlar.forbidden(rel) or rel.startswith(".."):
            continue
        try:
            found.append((os.stat(path).st_mtime, rel))
        except OSError:
            continue
    if not found:
        return None
    hinted = [f for f in found if tercih and f[1].split(os.sep)[0] == tercih]
    _, rel = max(hinted or found)
    yol = "/".join(["OFIS", *rel[:-3].split(os.sep)])
    return {"yol": yol, "kasa": os.path.basename(os.path.dirname(top))}
