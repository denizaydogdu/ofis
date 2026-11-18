"""Tests for the English option (ofis.json `dil`): the page's dictionary (web/i18n.js, web/i18n-en.js) and the server's
(bin/dil.py) against the strings the code marks for translation, the language setting on the Ayarlar path, the CEO's
reminder line and system text, and a few renderers under English. node runs the JavaScript (no browser); the node
parts are skipped without it."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahip_yasaklari  # noqa: E402,F401  (the owner's name as in his ofis.json; node reads it too)
import webkopya  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
BIN = ROOT / "bin"
sys.path.insert(0, str(BIN))
import ayarlar  # noqa: E402
import ceo  # noqa: E402
import dil  # noqa: E402
import npc_sohbet  # noqa: E402
import sahip  # noqa: E402

NODE = shutil.which("node")

# Phase 1 (the page) and phase 2 (the scene, its cards, the demo): the page's files translated in full.
JS_DOSYALARI = ("app.js", "ofis-text.js", "komuta.js", "ayarlar.js", "is-akisi.js", "limitler.js", "ofis-sahne.js",
                "ofis-davranis.js", "scene.js", "demo.js")
HTML = "index.html"
# The server's display texts: bin/dil.py t("…") / Metin("…") / N_("…") (and ayarlar.py's M = dil.Metin).
PY_DOSYALARI = ("dil.py", "ayarlar.py", "sahip.py", "npc_sohbet.py", "server.py", "state.py", "kullanim.py", "danisman.py",
                "limitler.py", "sistem.py")

_JS_LIT = r"""('(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\$]|\\.|\$(?!\{))*`)"""
JS_CAGRI = re.compile(r"(?<![\w.$])(?:T|N_)\(\s*" + _JS_LIT)
JS_SABLON = re.compile(r"(?<![\w.$])(?:T|N_)\(\s*`(?:[^`\\]|\\.)*?\$\{")
JS_BIRLESIK = re.compile(r"(?<![\w.$])(?:T|N_)\(\s*" + _JS_LIT + r"\s*\+")
HTML_ATTR = re.compile(r"""\bdata-t(?:-title|-placeholder|-aria-label)?="([^"]*)\"""")
YER = re.compile(r"\{(\w+)\}")


def js_coz(lit):
    """A JS string literal's value (the escapes these files use)."""
    body = lit[1:-1]
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n == "u" and body[i + 2:i + 3] == "{":
                j = body.index("}", i)
                out.append(chr(int(body[i + 3:j], 16)))
                i = j + 1
                continue
            if n == "u":
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append({"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"', "`": "`", "$": "$"}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def html_coz(v):
    return v.replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def js_anahtarlari():
    """{key: [file, …]} of every T('…') / N_('…') literal and data-t value; plus the problems found on the way."""
    keys, sorunlar = {}, []
    for name in JS_DOSYALARI:
        text = (WEB / name).read_text(encoding="utf-8")
        for m in JS_SABLON.finditer(text):
            sorunlar.append(f"{name}: a template literal with ${{…}} in T(): use {{placeholders}} ({text[m.start():m.start() + 60]!r})")
        for m in JS_BIRLESIK.finditer(text):
            sorunlar.append(f"{name}: a concatenated literal in T(): one literal per key ({text[m.start():m.start() + 60]!r})")
        for m in JS_CAGRI.finditer(text):
            keys.setdefault(js_coz(m.group(1)), []).append(name)
    for m in HTML_ATTR.finditer((WEB / HTML).read_text(encoding="utf-8")):
        keys.setdefault(html_coz(m.group(1)), []).append(HTML)
    return keys, sorunlar


def py_anahtarlari():
    """{key: [file, …]} of every literal first argument of dil.t / dil.Metin / dil.N_ (and M / Metin / t imported
    from dil), plus the problems (an f-string or a non-literal template where a literal is expected)."""
    keys, sorunlar = {}, []
    for name in PY_DOSYALARI:
        tree = ast.parse((BIN / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            hit = (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "dil"
                   and f.attr in ("t", "Metin", "N_")) or \
                  (isinstance(f, ast.Name) and f.id in ("M", "Metin", "N_") and name != "dil.py") or \
                  (name == "dil.py" and isinstance(f, ast.Name) and f.id in ("Metin",))
            if not hit:
                continue
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                keys.setdefault(a.value, []).append(name)
            elif isinstance(a, ast.IfExp) and all(isinstance(x, ast.Constant) for x in (a.body, a.orelse)):
                for x in (a.body, a.orelse):
                    keys.setdefault(x.value, []).append(name)
            elif isinstance(a, ast.JoinedStr):
                sorunlar.append(f"{name}:{node.lineno}: an f-string as a translation key: use {{placeholders}}")
    return keys, sorunlar


def en_sozluk():
    """web/i18n-en.js EN as a dict (node)."""
    with tempfile.TemporaryDirectory() as tmp:
        webkopya.i18n_ekle(tmp, mjs=True)
        code = (f"import {{ EN }} from {json.dumps((Path(tmp) / 'i18n-en.mjs').as_uri())};\n"
                "process.stdout.write(JSON.stringify(EN));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def formlar(value):
    """The English forms of an entry: a string, {one, other} (JS) or a (one, other) tuple (Python)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [value.get("one"), value.get("other")]
    if isinstance(value, tuple):
        return list(value)
    return [None]


def yer_sorunlari(sozluk):
    out = []
    for key, value in sozluk.items():
        want = set(YER.findall(key))
        for form in formlar(value):
            if not isinstance(form, str) or not form.strip():
                out.append(f"{key!r}: an empty or malformed English entry")
            elif set(YER.findall(form)) != want:
                out.append(f"{key!r}: placeholders {sorted(want)} != {sorted(set(YER.findall(form)))} in {form!r}")
    return out


def run_js(expr, dil_kodu="en", files=("ayarlar.js",)):
    """Evaluates `expr` with the given web modules imported by their stem (dashes as underscores) under OFIS_DIL."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name in set(files) | {"ofis-davranis.js", "ofis-text.js", "ofis-sahne.js"}:
            shutil.copyfile(WEB / name, Path(tmp) / name)
        webkopya.i18n_ekle(tmp)
        imports = "".join(f"import * as {Path(n).stem.replace('-', '_')} from {json.dumps((Path(tmp) / n).as_uri())};\n"
                          for n in files)
        code = imports + f"process.stdout.write(JSON.stringify({expr}));"
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp, env=dict(os.environ, TZ="UTC", OFIS_DIL=dil_kodu))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class SayfaSozluguTest(unittest.TestCase):
    """web/i18n-en.js against the marked strings of the phase-1 files."""

    @classmethod
    def setUpClass(cls):
        cls.keys, cls.sorunlar = js_anahtarlari()
        cls.en = en_sozluk()

    def test_no_template_or_concatenated_keys(self):
        self.assertEqual(self.sorunlar, [])

    def test_every_marked_string_has_an_english_entry(self):
        eksik = sorted(f"{k!r} ({', '.join(sorted(set(v)))})" for k, v in self.keys.items() if k not in self.en)
        self.assertEqual(eksik, [], f"{len(eksik)} missing")

    def test_no_unused_entries(self):
        self.assertEqual(sorted(k for k in self.en if k not in self.keys), [])

    def test_placeholders_match(self):
        self.assertEqual(yer_sorunlari(self.en), [])

    def test_the_static_page_marks_its_texts(self):
        html = (WEB / HTML).read_text(encoding="utf-8")
        self.assertIn('data-t="', html)
        self.assertIn('id="ayar-dil"', html)


class SunucuSozluguTest(unittest.TestCase):
    """bin/dil.py EN against the server's marked display texts."""

    @classmethod
    def setUpClass(cls):
        cls.keys, cls.sorunlar = py_anahtarlari()

    def test_no_fstring_keys(self):
        self.assertEqual(self.sorunlar, [])

    def test_every_marked_string_has_an_english_entry(self):
        eksik = sorted(f"{k!r} ({', '.join(sorted(set(v)))})" for k, v in self.keys.items() if k not in dil.EN)
        self.assertEqual(eksik, [], f"{len(eksik)} missing")

    def test_no_unused_entries(self):
        self.assertEqual(sorted(k for k in dil.EN if k not in self.keys), [])

    def test_placeholders_match(self):
        self.assertEqual(yer_sorunlari(dil.EN), [])


class DilTest(unittest.TestCase):
    def test_the_code_and_its_default(self):
        self.assertEqual(dil.kod({}), "tr")
        self.assertEqual(dil.kod({"dil": "en"}), "en")
        self.assertEqual(dil.kod({"dil": "de"}), "tr")
        self.assertEqual(dil.kod("en"), "en")

    def test_turkish_is_the_source_and_placeholders_fill_in_both(self):
        self.assertEqual(dil.t("Dil şunlardan biri olmalı: {diller}.", "tr", diller="tr, en"),
                         "Dil şunlardan biri olmalı: tr, en.")
        self.assertEqual(dil.t("Dil şunlardan biri olmalı: {diller}.", "en", diller="tr, en"),
                         "Language must be one of: tr, en.")
        self.assertEqual(dil.t("bilinmeyen bir metin", "en"), "bilinmeyen bir metin")

    def test_an_error_keeps_its_field_and_translates_later(self):
        e = ayarlar.proje_dogrula({}, "Kötü Ad", {"description": ""})
        self.assertIn("Açıklama zorunlu.", e)  # still the Turkish string itself
        self.assertEqual([x.alan for x in e], ["ad", "description", "path"])
        self.assertNotIn("Açıklama zorunlu.", [dil.cevir(x, {"dil": "en"}) for x in e])
        self.assertEqual(sahip.dogrula("")[0].alan, "sahip_adi")
        self.assertEqual(npc_sohbet.dogrula({"acik": 1})[0].alan, "npc_sohbet")
        self.assertEqual(dil.dogrula("de")[0].alan, "dil")


class AyarTest(unittest.TestCase):
    """The language on the Ayarlar path (bin/ayarlar.py islem genel)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "ofis.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"ofis_adi": "Ofis", "projects": {}}, f)

    def oku(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_saving_english_writes_it_and_says_it_changed(self):
        out = ayarlar.islem(self.path, self.tmp.name, {"islem": "genel", "dil": "en"})
        self.assertEqual(self.oku()["dil"], "en")
        self.assertTrue(out["dil_degisti"])
        self.assertEqual(out["alanlar"], ["dil"])
        again = ayarlar.islem(self.path, self.tmp.name, {"islem": "genel", "dil": "en"})
        self.assertFalse(again["dil_degisti"])

    def test_an_unknown_language_is_refused_under_its_field(self):
        with self.assertRaises(ayarlar.Hata) as c:
            ayarlar.islem(self.path, self.tmp.name, {"islem": "genel", "dil": "de"})
        self.assertEqual(c.exception.durum, 400)
        self.assertEqual([x.alan for x in c.exception.hatalar], ["dil"])
        self.assertNotIn("dil", self.oku())
        for bad in (None, 1, "EN", ["en"]):
            with self.assertRaises(ayarlar.Hata):
                ayarlar.islem(self.path, self.tmp.name, {"islem": "genel", "dil": bad})

    def test_the_settings_answer_and_the_live_keys_carry_it(self):
        self.assertIn("dil", ayarlar.CANLI_ANAHTARLAR)
        o = ayarlar.ozet({"dil": "en", "projects": {}})
        self.assertEqual(o["dil"], "en")
        self.assertEqual(o["kurallar"]["diller"], ["tr", "en"])
        self.assertEqual(ayarlar.ozet({"projects": {}})["dil"], "tr")

    def test_the_flag_for_a_fresh_ceo_session(self):
        self.assertTrue(ceo.yenile_iste(self.tmp.name, "2026-11-18T10:00:00"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, ceo.YENILE_DOSYASI)))
        self.assertFalse(ceo.yenile_iste(self.tmp.name, "2026-11-18T10:01:00"))


class CeoTest(unittest.TestCase):
    def test_the_reminder_line_in_both_languages_is_added_and_stripped(self):
        tr = sahip.hatirlatma("Ayşe")
        en = sahip.hatirlatma("Ayşe", "en")
        self.assertEqual(tr, "(Ayşe'ye Türkçe ve sade yaz.)")
        self.assertEqual(en, "(Reply to Ayşe in plain English.)")
        for line in (tr, en):
            self.assertEqual(sahip.hatirlatmayi_sil("Merhaba\n" + line), "Merhaba")
        self.assertEqual(ceo.with_reminder("Merhaba", "Ayşe", "en"), "Merhaba\n" + en)
        self.assertEqual(ceo.with_reminder("Merhaba\n" + tr, "Ayşe", "en"), "Merhaba\n" + tr)  # once
        # only as its own last line
        self.assertEqual(sahip.hatirlatmayi_sil("x (Reply to Ayşe in plain English.)"),
                         "x (Reply to Ayşe in plain English.)")

    def test_the_system_text_follows_the_language(self):
        self.assertIn("Türkçe", ceo.ceo_system_prompt("Ayşe"))
        en = ceo.ceo_system_prompt("Ayşe", "en")
        self.assertIn("in English", en)
        self.assertIn("Ayşe", en)

    def test_the_owner_suffixes_in_english(self):
        self.assertEqual(sahip.ek_dilde("Ayşe", "in", "en"), "Ayşe's")
        self.assertEqual(sahip.ek_dilde("Ayşe", "e", "en"), "Ayşe")
        self.assertEqual(sahip.ek_dilde("Ayşe", "e"), "Ayşe'ye")
        self.assertEqual(sahip.ekler({"sahip_adi": "Ayşe", "dil": "en"})["in"], "Ayşe's")
        self.assertEqual(sahip.ekler({"sahip_adi": "Ayşe"})["in"], "Ayşe'nin")


@unittest.skipUnless(NODE, "node is not installed")
class SayfaTest(unittest.TestCase):
    """A few page helpers under English (OFIS_DIL=en) and unchanged under Turkish."""

    def test_the_server_sends_the_field_with_each_error(self):
        body = {"hatalar": ["Description is required.", "Folder not found: /x"], "alanlar": ["description", "path"]}
        self.assertEqual(run_js(f"ayarlar.sunucuHatalari({json.dumps(body)})"),
                         [{"alan": "description", "metin": "Description is required."},
                          {"alan": "path", "metin": "Folder not found: /x"}])
        # an older answer without alanlar: the Turkish text still finds its field
        self.assertEqual(run_js("ayarlar.sunucuHatalari({hatalar: ['Açıklama zorunlu.']})", "tr"),
                         [{"alan": "description", "metin": "Açıklama zorunlu."}])

    def test_the_language_body(self):
        self.assertEqual(run_js("ayarlar.dilGovdesi('en', {diller: ['tr', 'en']})"),
                         {"govde": {"islem": "genel", "dil": "en"}})
        self.assertIn("hata", run_js("ayarlar.dilGovdesi('de', {diller: ['tr', 'en']})"))

    def test_t_and_the_locale(self):
        files = ("i18n.js",)
        self.assertEqual(run_js("[i18n.t('Dil kaydedildi.'), i18n.yerel()]", "en", files), ["Language saved.", "en-GB"])
        self.assertEqual(run_js("[i18n.t('Dil kaydedildi.'), i18n.yerel()]", "tr", files), ["Dil kaydedildi.", "tr-TR"])
        self.assertEqual(run_js("i18n.t('yok {x}', {x: 3})", "en", files), "yok 3")

    def test_a_few_renderers_in_both_languages(self):
        files = ("ayarlar.js", "limitler.js", "ofis-text.js")
        expr = ("[ayarlar.acikIsMetni(1), ayarlar.acikIsMetni(3), "
                "limitler.limitPill({haftalik: {yuzde: 54}, bes_saat: {yuzde: 12}}).metin, ofis_text.tokenMetni(182000)]")
        self.assertEqual(run_js(expr, "en", files), ["1 open job", "3 open jobs", "Weekly 54% · 5 hours 12%", "182K tokens"])
        self.assertEqual(run_js(expr, "tr", files), ["1 açık iş", "3 açık iş", "Haftalık %54 · 5 saat %12", "182 bin token"])

    def test_the_owner_suffix_in_english(self):
        files = ("ofis-davranis.js",)
        self.assertEqual(run_js("[ofis_davranis.sahipEk('Ayşe', 'in'), ofis_davranis.sahipEk('Ayşe', 'e')]", "en", files),
                         ["Ayşe's", "Ayşe"])
        self.assertEqual(run_js("ofis_davranis.sahipEk('Ayşe', 'in')", "tr", files), "Ayşe'nin")

    def test_the_scene_in_english_and_unchanged_in_turkish(self):
        # phase 2: the org chart's root, a staff card, an NPC's desk line and an actor's label
        files = ("ofis-sahne.js", "ofis-davranis.js")
        expr = ("(() => { const g = ofis_sahne.orgSemasi({tasks: [], sessions: []}, '2026-11-18T10:30:00'); "
                "const kart = ofis_sahne.doktorKarti({tasks: []}, Date.parse('2026-11-18T10:00:00Z')); "
                "return [g.alt, kart.satirlar[0].ad, kart.satirlar[0].metin, ofis_davranis.masaSozu('ik', {tasks: []}, 0), "
                "ofis_davranis.etiketCevir('blog · Kıdemli Backend', 'blog'), ofis_davranis.etiketCevir('Yazılım Müdürü')]; })()")
        self.assertEqual(run_js(expr, "en", files),
                         ["founder", "Status", "The office is healthy", "at the desk · no jobs at work right now",
                          "blog · Senior Backend", "Software Manager"])
        self.assertEqual(run_js(expr, "tr", files),
                         ["kurucu", "Durum", "Ofis sağlıklı", "masasında · şu an çalışan iş yok",
                          "blog · Kıdemli Backend", "Yazılım Müdürü"])

    def test_the_approval_buttons_send_what_the_parser_accepts(self):
        import akis  # noqa: E402
        sent = run_js("[i18n.t('Onaylıyorum'), i18n.t('Hayır')]", "en", ("i18n.js",))
        self.assertEqual(sent, ["I approve", "No"])
        self.assertTrue(akis.is_approval(sent[0]))
        self.assertFalse(akis.is_approval(sent[1]))
        self.assertIn("submit(T('Onaylıyorum'))", (WEB / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
