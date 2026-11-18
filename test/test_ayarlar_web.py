"""Tests for the page's Ayarlar tab: the pure helpers in web/ayarlar.js under node (skipped without node) and static
checks of its wiring in web/index.html, web/app.js, web/style.css and web/demo.js (plan "Ayarlar sayfası" 1.5)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import webkopya  # noqa: E402  (web/i18n.js next to the copied modules)
import sahip_yasaklari  # noqa: E402,F401  (the owner's name as in his ofis.json; node reads it too)

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")


def run_a(expr):
    """Evaluates `expr` with web/ayarlar.js imported as `a`; returns the JSON-decoded result."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        shutil.copyfile(WEB / "ayarlar.js", Path(tmp) / "ayarlar.js")
        webkopya.i18n_ekle(tmp)
        uri = json.dumps((Path(tmp) / "ayarlar.js").as_uri())
        code = (f"import * as a from {uri};\n{PRELUDE}\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp, env=dict(os.environ, TZ="UTC"))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


# K = the rules of GET /api/ayarlar (bin/ayarlar.py ozet); P = one project row as the server sends it
PRELUDE = r"""
const K = { ad_regex: '[a-z0-9][a-z0-9-]{0,39}', ayrilmis: ['ofis'], yerlesik: ['arge'], aciklama_siniri: 300,
  notlar_siniri: 2000, ofis_adi_siniri: 40, hassas_sayisi: 20, sorumlu_alanlari: ['dur_sor', 'asla', 'teslim'],
  sistem_alanlari: ['domainler', 'eposta_domaini', 'cloudflare'] };
const P = { ad: 'ornek', path: '~/Dev/ornek', tam_yol: '/Users/x/Dev/ornek', description: 'Örnek uygulama',
  notes: 'Testleri çalıştır.', hassas_yollar: ['.env*'], sorumlu: { dur_sor: ['Ödeme'], teslim: 'Kısa özet' },
  sistem: { domainler: ['ornek.com'], eposta_domaini: 'ornek.com', cloudflare: true }, yerlesik: false,
  acik_is_sayisi: 0, guven: true, ipucu: '' };
"""


@unittest.skipUnless(NODE, "node is not installed")
class FormTest(unittest.TestCase):
    def test_lines_are_trimmed_and_empty_ones_dropped(self):
        self.assertEqual(run_a("a.satirlar(' a \\n\\n  b\\r\\n ')"), ["a", "b"])
        self.assertEqual(run_a("[a.satirlar(''), a.satirlar(null), a.satirlar(undefined)]"), [[], [], []])

    def test_a_project_row_becomes_form_values_and_back(self):
        out = run_a("a.formDegerleri(P)")
        self.assertEqual(out, {"ad": "ornek", "path": "~/Dev/ornek", "description": "Örnek uygulama",
                               "notes": "Testleri çalıştır.", "hassas_yollar": ".env*", "dur_sor": "Ödeme", "asla": "",
                               "teslim": "Kısa özet", "domainler": "ornek.com"})
        self.assertEqual(run_a("a.formDegerleri(null)"), run_a("a.bosForm()"))
        self.assertEqual(set(run_a("a.bosForm()")), set(out))

    def test_the_add_body_leaves_out_empty_optional_fields(self):
        out = run_a("""a.eklemeGovdesi({ ...a.bosForm(), ad: ' yeni ', path: ' ~/Dev/yeni ', description: ' Yeni iş ' })""")
        self.assertEqual(out, {"islem": "proje-ekle",
                               "proje": {"ad": "yeni", "path": "~/Dev/yeni", "description": "Yeni iş"}})

    def test_the_add_body_carries_the_advanced_fields_as_lists(self):
        out = run_a("""a.eklemeGovdesi({ ...a.bosForm(), ad: 'yeni', path: '/p', description: 'D', notes: ' Kural ',
          hassas_yollar: 'a/**\\n\\nb', dur_sor: 'x', asla: 'y\\nz', domainler: ' Ornek.COM \\nb.io' })""")
        self.assertEqual(out["proje"], {"ad": "yeni", "path": "/p", "description": "D", "notes": "Kural",
                                        "hassas_yollar": ["a/**", "b"],
                                        "sorumlu": {"dur_sor": ["x"], "asla": ["y", "z"]},
                                        "sistem": {"domainler": ["ornek.com", "b.io"]}})

    def test_an_unchanged_form_sends_nothing(self):
        self.assertIsNone(run_a("a.guncellemeGovdesi(P, a.formDegerleri(P))"))
        # whitespace alone is no change
        self.assertIsNone(run_a("a.guncellemeGovdesi(P, { ...a.formDegerleri(P), description: ' Örnek uygulama  ' })"))

    def test_the_update_body_holds_only_the_changed_fields(self):
        out = run_a("a.guncellemeGovdesi(P, { ...a.formDegerleri(P), path: '~/Dev/yeni', notes: '' })")
        self.assertEqual(out, {"islem": "proje-guncelle", "proje": {"ad": "ornek", "path": "~/Dev/yeni", "notes": ""}})
        out = run_a("a.guncellemeGovdesi(P, { ...a.formDegerleri(P), hassas_yollar: '' })")
        self.assertEqual(out["proje"], {"ad": "ornek", "hassas_yollar": []})

    def test_a_changed_sorumlu_line_keeps_the_untouched_sections_as_they_were(self):
        out = run_a("a.guncellemeGovdesi(P, { ...a.formDegerleri(P), asla: 'Push yapma' })")
        self.assertEqual(out["proje"], {"ad": "ornek", "sorumlu": {"dur_sor": ["Ödeme"], "asla": ["Push yapma"],
                                                                    "teslim": "Kısa özet"}})
        out = run_a("a.guncellemeGovdesi(P, { ...a.formDegerleri(P), dur_sor: '', teslim: '' })")
        self.assertEqual(out["proje"], {"ad": "ornek", "sorumlu": {}})

    def test_changed_domains_keep_the_mail_domain_and_cloudflare(self):
        out = run_a("a.guncellemeGovdesi(P, { ...a.formDegerleri(P), domainler: 'ornek.com\\nyeni.io' })")
        self.assertEqual(out["proje"], {"ad": "ornek", "sistem": {"domainler": ["ornek.com", "yeni.io"],
                                                                   "eposta_domaini": "ornek.com", "cloudflare": True}})
        out = run_a("a.guncellemeGovdesi({ ...P, sistem: {} }, { ...a.formDegerleri(P), domainler: '' })")
        self.assertIsNone(out)

    def test_the_office_name_is_dirty_only_against_a_baseline(self):
        self.assertEqual(run_a("""[a.ofisAdiKirli('Ofis', 'Ofis'), a.ofisAdiKirli('Ofis', ' Ofis  '),
          a.ofisAdiKirli('Ofis', 'Atölye'), a.ofisAdiKirli(null, 'Atölye'), a.ofisAdiKirli('Ofis', null)]"""),
                         [False, False, True, False, True])

    def test_dirty_compares_the_trimmed_values(self):
        self.assertEqual(run_a("""[a.kirli(a.formDegerleri(P), a.formDegerleri(P)),
          a.kirli(a.formDegerleri(P), { ...a.formDegerleri(P), notes: 'Testleri çalıştır. ' }),
          a.kirli(a.formDegerleri(P), { ...a.formDegerleri(P), asla: 'x' }),
          a.kirli(null, a.formDegerleri(P))]"""), [False, False, True, False])


@unittest.skipUnless(NODE, "node is not installed")
class ValidationTest(unittest.TestCase):
    def fields(self, expr):
        return [e["alan"] for e in run_a(expr)]

    def test_a_valid_new_project_has_no_errors(self):
        self.assertEqual(run_a("a.istemciHatalari({ ...a.bosForm(), ad: 'yeni-1', path: '~/Dev/x', description: 'D' }, K)"),
                         [])

    def test_the_name_follows_the_server_rule_and_the_reserved_names(self):
        for bad in ("''", "'Buyuk'", "'-x'", "'a_b'", "'x'.repeat(41)", "'ofis'"):
            self.assertIn("ad", self.fields(f"a.istemciHatalari({{ ...a.bosForm(), ad: {bad}, path: '/p', description: 'D' }}, K)"),
                          bad)

    def test_the_name_is_not_checked_while_editing(self):
        self.assertEqual(run_a("a.istemciHatalari({ ...a.formDegerleri(P), ad: '' }, K, { duzenleme: true })"), [])

    def test_folder_and_description_are_required_and_bounded(self):
        f = self.fields("a.istemciHatalari({ ...a.bosForm(), ad: 'x' }, K)")
        self.assertIn("path", f)
        self.assertIn("description", f)
        self.assertIn("path", self.fields("a.istemciHatalari({ ...a.bosForm(), ad: 'x', path: 'Dev/x', description: 'D' }, K)"))
        self.assertIn("description", self.fields(
            "a.istemciHatalari({ ...a.bosForm(), ad: 'x', path: '/p', description: 'd'.repeat(301) }, K)"))
        self.assertIn("notes", self.fields(
            "a.istemciHatalari({ ...a.bosForm(), ad: 'x', path: '/p', description: 'D', notes: 'n'.repeat(2001) }, K)"))
        self.assertIn("hassas_yollar", self.fields(
            "a.istemciHatalari({ ...a.bosForm(), ad: 'x', path: '/p', description: 'D', hassas_yollar: Array(21).fill('a').join('\\n') }, K)"))

    def test_domains_are_host_names_only(self):
        self.assertIn("domainler", self.fields(
            "a.istemciHatalari({ ...a.bosForm(), ad: 'x', path: '/p', description: 'D', domainler: 'https://ornek.com/x' }, K)"))
        self.assertEqual(run_a(
            "a.istemciHatalari({ ...a.bosForm(), ad: 'x', path: '/p', description: 'D', domainler: 'ornek.com\\nalt.ornek.com.tr' }, K)"), [])

    def test_the_office_name(self):
        self.assertEqual(run_a("a.ofisAdiGovdesi('  Atölye  ', K)"), {"govde": {"islem": "genel", "ofis_adi": "Atölye"}})
        self.assertIn("hata", run_a("a.ofisAdiGovdesi('   ', K)"))
        self.assertIn("hata", run_a("a.ofisAdiGovdesi('x'.repeat(41), K)"))

    def test_the_owners_name(self):
        # plan "2. Aşama": the Genel section saves both names; the owner's name is checked like bin/sahip.py dogrula
        self.assertEqual(run_a("a.genelGovdesi(' Atölye ', ' Ayşe Nur ', K)"),
                         {"govde": {"islem": "genel", "ofis_adi": "Atölye", "sahip_adi": "Ayşe Nur"}})
        for bad in ("''", "'[Sahip · x]'", "'Ali · Can'", "'Ali\\nCan'", "'Ofis'", "'ceo'", "'x'.repeat(41)", "'1Ali'"):
            with self.subTest(bad=bad):
                self.assertEqual(run_a(f"a.genelGovdesi('Ofis', {bad}, K).alan"), "sahip_adi")
        self.assertEqual(run_a("a.genelGovdesi('', 'Ali', K).alan"), "ofis_adi")
        self.assertEqual(run_a("a.sahipAdiHatasi(\"O'Neil\", K)"), "")
        self.assertEqual(run_a("a.hataAlani('Adın boş olamaz.')"), "sahip_adi")
        self.assertEqual(run_a("a.hataAlani('Bu ad ofisin kendi konuşmacılarına ayrılmış (Ofis, CEO); başka bir ad yaz.')"),
                         "sahip_adi")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ayar-sahip-adi"', html)
        self.assertIn("Senin adın", html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("genelGovdesi($('ayar-ofis-adi').value, $('ayar-sahip-adi').value", app)
        self.assertIn("ofisAdiKirli(ayarSahipBaslangic, $('ayar-sahip-adi').value)", app)

    def test_server_errors_are_placed_under_their_fields(self):
        out = run_a("""a.sunucuHatalari({ error: 'x', hatalar: ['Proje adı küçük harf…', "'x' adında bir proje zaten var.",
          'Klasör bulunamadı: /p', 'Bu klasör zaten \\'a\\' projesinin klasörü.', 'Proje klasörü Ofis\\'in kendi klasörü olamaz.',
          'Açıklama zorunlu.', 'Proje kuralları en çok 2000 karakterlik düz metin olabilir.', 'Hassas yollar en çok 20 satır olabilir.',
          'Sorumlu · asla: her satır…', 'Domainler yalnız host adı olmalı', 'Ofis adı boş olamaz.', 'Başka bir şey'] })""")
        self.assertEqual([e["alan"] for e in out], ["ad", "ad", "path", "path", "path", "description", "notes",
                                                    "hassas_yollar", "asla", "domainler", "ofis_adi", ""])
        self.assertEqual(run_a("a.sunucuHatalari({ error: 'tek' })"), [{"alan": "", "metin": "tek"}])
        self.assertEqual(run_a("a.sunucuHatalari(null)"), [])


@unittest.skipUnless(NODE, "node is not installed")
class TextTest(unittest.TestCase):
    def test_trust_badge(self):
        out = run_a("[a.guvenRozeti(true), a.guvenRozeti(false), a.guvenRozeti(null)]")
        self.assertEqual([o["ton"] for o in out], ["ok", "uyari", "bilinmiyor"])
        self.assertTrue(all(o["metin"] for o in out))

    def test_open_jobs(self):
        self.assertEqual(run_a("[a.acikIsMetni(0), a.acikIsMetni(1), a.acikIsMetni(3), a.acikIsMetni(undefined)]"),
                         ["Açık iş yok", "1 açık iş", "3 açık iş", "Açık iş yok"])

    def test_the_result_line_after_a_save(self):
        out = run_a("""[a.sonucMetni(200, { islem: 'proje-ekle', ad: 'x' }), a.sonucMetni(200, { islem: 'proje-guncelle', ad: 'x' }),
          a.sonucMetni(200, { islem: 'proje-sil', ad: 'x' }), a.sonucMetni(200, { islem: 'genel', ad: '' }),
          a.sonucMetni(0, {}), a.sonucMetni(403, {}), a.sonucMetni(409, { error: 'Açık işi var.' }),
          a.sonucMetni(500, {})]""")
        self.assertIn("eklendi", out[0])
        self.assertIn("güncellendi", out[1])
        self.assertIn("silindi", out[2])
        self.assertIn("Ofis adı", out[3])
        self.assertIn("Sunucuya ulaşılamadı", out[4])
        self.assertIn("yenile", out[5])
        self.assertEqual(out[6], "Açık işi var.")
        self.assertTrue(out[7])

    def test_delete_question_names_the_project_and_keeps_the_notes(self):
        text = run_a("a.silmeSorusu('ornek')")
        self.assertIn("ornek", text)
        self.assertIn("Obsidian", text)


@unittest.skipUnless(NODE, "node is not installed")
class NpcSohbetTest(unittest.TestCase):
    """The Genel section's NPC chat switch (bin/npc_sohbet.py dogrula, the same rule)."""

    def test_the_body_and_its_check(self):
        self.assertEqual(run_a("a.npcSohbetGovdesi(true, ' 7 ', K)"),
                         {"govde": {"islem": "genel", "npc_sohbet": {"acik": True, "saatlik_sinir": 7}}})
        self.assertEqual(run_a("a.npcSohbetGovdesi('x', 20, K)")["govde"]["npc_sohbet"]["acik"], False)
        for bad in ("0", "201", "2.5", "", "abc", "-3"):
            with self.subTest(bad=bad):
                self.assertIn("NPC sohbeti", run_a(f"a.npcSohbetGovdesi(true, {json.dumps(bad)}, K)")["hata"])

    def test_its_errors_and_result_line(self):
        self.assertEqual(run_a("a.hataAlani('NPC sohbeti · saatlik sınır 1 ile 200 arasında bir tam sayı olmalı.')"),
                         "npc_sohbet")
        self.assertEqual(run_a("a.sonucMetni(200, { islem: 'genel', alanlar: ['npc_sohbet'] })"),
                         "NPC sohbeti ayarı kaydedildi.")
        self.assertEqual(run_a("a.sonucMetni(200, { islem: 'genel', alanlar: ['ofis_adi', 'sahip_adi'] })"),
                         "Ofis adı kaydedildi.")


@unittest.skipUnless(NODE, "node is not installed")
class ProjeRengiTest(unittest.TestCase):
    """One colour per team in the scene and on the page (web/ofis-davranis.js projeRengi): indexed among the projects
    without the arge workspace, whatever form the list comes in."""

    def run_d(self, expr):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
            shutil.copyfile(WEB / "ofis-davranis.js", Path(tmp) / "ofis-davranis.js")
            webkopya.i18n_ekle(tmp)
            uri = json.dumps((Path(tmp) / "ofis-davranis.js").as_uri())
            proc = subprocess.run([NODE, "--input-type=module", "-e",
                                   f"import * as d from {uri};\nprocess.stdout.write(JSON.stringify({expr}));"],
                                  capture_output=True, text=True, timeout=30, cwd=tmp)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        return json.loads(proc.stdout)

    def test_the_page_rows_and_the_plan_names_give_the_same_colour(self):
        out = self.run_d("""(() => { const rows = [{ name: 'arge' }, { name: 'a' }, { name: 'b' }];
          const plan = d.ofisPlani(rows).projeler;
          return { satir: ['a', 'b'].map((p) => d.projeRengi(p, rows)), plan: ['a', 'b'].map((p) => d.projeRengi(p, plan)),
            ilk: d.ODA_RENKLERI.slice(0, 2), arge: d.projeRengi('arge', rows, 'x'), yok: d.projeRengi('c', rows, 'y'),
            bos: d.projeRengi('a', null, 'z') }; })()""")
        self.assertEqual(out["satir"], out["plan"])
        self.assertEqual(out["satir"], out["ilk"])
        self.assertEqual((out["arge"], out["yok"], out["bos"]), ("x", "y", "z"))

    def test_scene_and_page_use_the_helper(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertNotRegex(scene, r"ROOM_COLORS\[")
        self.assertIn("projeRengi(", scene)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("projeRengi(name, state ? state.projects : [], '#E5DCCF')", app)
        self.assertNotIn("ROOM_COLORS", app)


class WiringTest(unittest.TestCase):
    """The tab, its overlay and the form's wiring (static checks)."""

    def test_the_tab_and_the_overlay_exist(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-tab="ayarlar"', html)
        self.assertIn('id="overlay-ayarlar"', html)
        for need in ('id="ayar-genel-form"', 'id="ayar-ofis-adi"', 'id="ayar-projeler"', 'id="ayar-proje-ekle"',
                     'id="ayar-proje-form"', 'id="ayar-f-ad"', 'id="ayar-f-path"', 'id="ayar-f-description"',
                     'id="ayar-f-notes"', 'id="ayar-f-hassas_yollar"', 'id="ayar-f-dur_sor"', 'id="ayar-f-asla"',
                     'id="ayar-f-teslim"', 'id="ayar-f-domainler"', 'id="ayar-npc-form"', 'id="ayar-npc-acik"',
                     'id="ayar-npc-sinir"', 'for="ayar-npc-acik"', 'for="ayar-npc-sinir"'):
            self.assertIn(need, html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("npcSohbetGovdesi($('ayar-npc-acik').checked, $('ayar-npc-sinir').value", app)
        # every form field has a label
        for field in re.findall(r'id="(ayar-f-[a-z_]+)"', html):
            self.assertIn(f'for="{field}"', html, field)

    def test_app_wires_the_tab_without_redrawing_on_state_pushes(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("from './ayarlar.js'", app)
        self.assertRegex(app, r"const OVERLAYS = \[[^\]]*'ayarlar'")
        self.assertIn("if (tab === 'ayarlar' && !ayarlarAcikti) loadAyarlar()", app)
        self.assertIn("post('/api/ayarlar'", app)
        render_all = app[app.index("function renderAll()"):app.index("}", app.index("function renderAll()"))]
        self.assertNotIn("yar", render_all.replace("renderYakala", ""))
        self.assertIn("Demo modunda kaydedilmez", app)
        # leaving the tab with unsaved edits asks first
        set_tab = app[app.index("function setTab(tab) {"):app.index("\n}\n", app.index("function setTab(tab) {"))]
        self.assertIn("if (tab !== 'ayarlar' && !ayarlardanCikilsinMi()) return;", set_tab)
        self.assertNotIn("innerHTML", app[app.index("// --- Ayarlar"):app.index("// --- tabs ---")])

    def test_a_project_save_keeps_an_unsaved_office_name(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        start = app.index("function renderAyarlar(data) {")
        render = app[start:app.index("\n}\n", start)]
        guard = render.index("if (!ofisAdiKirli(ayarGenelBaslangic, $('ayar-ofis-adi').value))")
        # the field and its baseline are only rewritten inside the guard; the project list always
        self.assertGreater(render.index("$('ayar-ofis-adi').value = ad;"), guard)
        self.assertGreater(render.index("ayarGenelBaslangic = ad;"), guard)
        self.assertEqual(render.count("ayarGenelBaslangic = "), 1)
        self.assertIn("list.replaceChildren(...rows.map(ayarKarti));", render)
        kirli_fn = app[app.index("function ayarlarKirli() {"):app.index("\n}\n", app.index("function ayarlarKirli() {"))]
        self.assertIn("ofisAdiKirli(ayarGenelBaslangic, $('ayar-ofis-adi').value)", kirli_fn)

    def test_demo_answers_the_settings_read(self):
        demo = (WEB / "demo.js").read_text(encoding="utf-8")
        self.assertIn("if (path === '/api/ayarlar')", demo)


if __name__ == "__main__":
    unittest.main()
