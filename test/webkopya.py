"""Test support: the page's language module (web/i18n.js and its English map web/i18n-en.js, imported by the
translated web modules) copied next to a web module the node tests load from a temp folder.

- i18n_ekle(folder, mjs=False): copies both files into folder; mjs=True writes them as .mjs (for the helpers that load
  modules as .mjs copies without a package.json) with their own import rewritten.
- mjs_yap(text): a module's text with its imports of ./i18n.js, ./i18n-en.js and ./ofis-davranis.js pointed at the
  .mjs copies.
"""
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
I18N = ("i18n.js", "i18n-en.js")
MJS = ("i18n", "i18n-en", "ofis-davranis")


def mjs_yap(text):
    for stem in MJS:
        text = text.replace(f"'./{stem}.js'", f"'./{stem}.mjs'")
    return text


def i18n_ekle(folder, mjs=False):
    for name in I18N:
        text = (WEB / name).read_text(encoding="utf-8")
        target = Path(folder) / ((Path(name).stem + ".mjs") if mjs else name)
        target.write_text(mjs_yap(text) if mjs else text, encoding="utf-8")
