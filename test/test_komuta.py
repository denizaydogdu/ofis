"""Tests for the Komuta masası (the big CEO window): the pure helpers in web/komuta.js under node (skipped without
node) and static checks of its wiring in web/index.html, web/app.js, web/style.css, web/scene.js and web/demo.js."""
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


def run_k(expr):
    """Evaluates `expr` with web/komuta.js imported as `k` (its imports resolve in a temp folder with
    package.json type=module); returns the JSON-decoded result."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name in ("komuta.js", "ofis-sahne.js", "ofis-davranis.js", "ofis-text.js"):
            shutil.copyfile(WEB / name, Path(tmp) / name)
        webkopya.i18n_ekle(tmp)
        uri = json.dumps((Path(tmp) / "komuta.js").as_uri())
        code = (f"import * as k from {uri};\n{PRELUDE}\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp, env=dict(os.environ, TZ="UTC"))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


PRELUDE = r"""
const NOW = Date.parse('2026-11-12T10:00:00Z');
const iso = (min) => new Date(NOW - min * 60000).toISOString().slice(0, 19);
const task = (note, project, status, x = {}) => ({ note, project, status, title: 'İş ' + note, started: iso(30),
  created: iso(31), session: '', tier: 'kod', model: 'opus', spent: '0.41', tokens: 182000, budget: 3, calls: '4',
  max_calls: 120, workflow: '', step: '', step_kind: '', queue_position: null, held: false, depends: [], blocked: '', ...x });
const ses = (name, status, x = {}) => ({ name, project: 'vitrin', status, kind: 'background', started_at: NOW - 600000,
  model: 'opus', tier: 'kod', alt_ajanlar: [], ...x });
const st = (x = {}) => ({ projects: [{ name: 'vitrin', tasks: [] }, { name: 'kasa', tasks: [] }, { name: 'blog', tasks: [] }],
  sessions: [], ceo: { state: 'idle' }, decisions: [], tasks: [], board: [], workflows: [], modeller: [], denetim: null,
  sahne: { saat_dilimi: 'UTC', sunucu_utc_ofset_dk: 0 }, summary: {}, ...x });
"""


@unittest.skipUnless(NODE, "node is not installed")
class SuAnTest(unittest.TestCase):
    def test_jobs_are_grouped_per_project_with_role_state_time_and_spending(self):
        out = run_k("""k.suAnGruplari(st({
          sessions: [ses('ofis-vitrin-1', 'busy', { note: 'a.md', alt_ajanlar: [{ id: 'x', model: 'haiku' }] })],
          tasks: [task('2026-11-12-1-vitrin.md', 'vitrin', 'calisiyor', { session: 'ofis-vitrin-1', title: 'Giriş hatası' }),
            task('2026-11-12-2-kasa.md', 'kasa', 'kontrolde', { model: 'sonnet', tier: 'genel' }),
            task('q1.md', 'kasa', 'sirada', { held: true }), task('q2.md', 'kasa', 'sirada', { onay_birikti: true }),
            task('q3.md', 'blog', 'sirada'), task('old.md', 'blog', 'bitti')],
          workflows: [{ grup: 'akis-1', baslik: 'Profil', proje: 'vitrin', durum: 'calisiyor', tamam: 2, toplam: 3 },
            { grup: 'akis-0', baslik: 'Eski', proje: 'vitrin', durum: 'bitti', tamam: 5, toplam: 5 }],
          ceo: { state: 'busy' } }), NOW)""")
        self.assertEqual([p["proje"] for p in out["projeler"]], ["vitrin", "kasa", "blog"])
        w, kasa, blog = out["projeler"]
        self.assertEqual(len(w["isler"]), 1)
        job = w["isler"][0]
        self.assertEqual(job["baslik"], "Giriş hatası")
        self.assertEqual(job["calisan"], "Kıdemli")  # role only; the model in the tooltip
        self.assertEqual(job["calisan_ipucu"], "Kıdemli · model: Opus")
        self.assertEqual(job["durum"], "çalışıyor")
        self.assertEqual(job["sure"], "30 dk")
        self.assertEqual(job["harcama"], "182 bin token · ≈$0,41 / ≈$3,00")
        self.assertEqual(job["yardimci"], "1 yardımcı")
        self.assertEqual(job["note"], "2026-11-12-1-vitrin.md")
        self.assertEqual(w["akislar"], [{"grup": "akis-1", "baslik": "Profil", "ilerleme": "2/3 adım"}])
        self.assertEqual((kasa["sirada"], kasa["bekletilen"], kasa["birikis"]), (2, 1, 1))
        self.assertEqual(kasa["isler"][0]["calisan"], "Uzman")
        self.assertEqual(kasa["isler"][0]["durum"], "Kontrol")
        self.assertEqual((blog["sirada"], blog["isler"]), (1, []))
        self.assertFalse(out["bos"])
        # the CEO has its own header in the chat column: never a row here
        self.assertNotIn("ceo", json.dumps([j["id"] for p in out["projeler"] for j in p["isler"]]))

    def test_reviewers_and_the_hakem_stand_apart_and_empty_is_empty(self):
        out = run_k("""k.suAnGruplari(st({ tasks: [task('2026-11-12-3-kasa.md', 'kasa', 'incelemede',
            { inceleme_yurutucu: 'codex', title: 'Kod incelemesi' })],
          denetim: { is: '2026-11-12-3-kasa.md', denetciler: ['codex', 'glm'], hakem: 'sonnet' },
          modeller: [{ model: 'glm', unvan: 'Dış denetçi', ucretsiz: true }] }), NOW)""")
        self.assertEqual(out["projeler"], [])
        self.assertEqual([d["id"] for d in out["denetim"]], ["denetci:codex", "denetci:glm", "hakem"])
        self.assertEqual(out["denetim"][0]["calisan"], "Codex")  # a name, not a role
        self.assertEqual(out["denetim"][1]["calisan"], "GLM")
        self.assertEqual(out["denetim"][2]["calisan"], "Hakem")
        self.assertEqual(out["denetim"][2]["calisan_ipucu"], "Hakem · model: Sonnet")
        self.assertEqual(out["denetim"][0]["note"], "2026-11-12-3-kasa.md")
        self.assertTrue(run_k("k.suAnGruplari(st(), NOW).bos"))
        self.assertTrue(run_k("k.suAnGruplari(null, NOW).bos"))

    def test_the_queue_line(self):
        self.assertEqual(run_k("k.siraMetni({sirada: 3, bekletilen: 1, birikis: 2})"),
                         "3 iş sırada · 1 bekletiliyor (Selin bırakınca başlar) · 2 onay birikişi nedeniyle bekliyor")
        self.assertEqual(run_k("k.siraMetni({sirada: 0})"), "")


@unittest.skipUnless(NODE, "node is not installed")
class ContextChipTest(unittest.TestCase):
    def test_chips_end_the_message_with_one_related_line(self):
        out = run_k("""(() => { let c = [];
          c = k.baglamEkle(c, {note: '2026-11-12-1-vitrin.md', baslik: 'Giriş hatası'});
          c = k.baglamEkle(c, {note: '2026-11-12-1-vitrin', baslik: 'aynı iş'});
          c = k.baglamEkle(c, {note: '2026-11-12-2-kasa.md', baslik: 'CSV'});
          c = k.baglamEkle(c, {note: 'kötü]] [[x', baslik: 'kötü'});
          return { c, msg: k.mesajMetni('  Bu ikisi ne durumda?  ', c), label: k.baglamEtiketi(c[0]),
            removed: k.mesajMetni('x', k.baglamCikar(c, '2026-11-12-1-vitrin.md')), none: k.mesajMetni('Selam', []),
            empty: k.mesajMetni('   ', c) }; })()""")
        self.assertEqual(out["c"], [{"note": "2026-11-12-1-vitrin", "baslik": "Giriş hatası"},
                                    {"note": "2026-11-12-2-kasa", "baslik": "CSV"}])
        self.assertEqual(out["msg"], "Bu ikisi ne durumda?\n\nİlgili: [[2026-11-12-1-vitrin]], [[2026-11-12-2-kasa]]")
        self.assertEqual(out["label"], "İlgili: Giriş hatası")
        self.assertEqual(out["removed"], "x\n\nİlgili: [[2026-11-12-2-kasa]]")
        self.assertEqual(out["none"], "Selam")
        self.assertEqual(out["empty"], "")

    def test_the_chip_line_length_lowers_the_room_for_the_text(self):
        # review MINOR 4: the 4000-character limit counts the "İlgili:" line too
        out = run_k("""(() => { const c = k.baglamEkle([], {note: '2026-11-12-1-vitrin', baslik: 'x'});
          return [k.baglamSatiriUzunlugu([]), k.baglamSatiriUzunlugu(c), k.mesajMetni('a', c).length - 1,
            k.metinSiniri(c), k.metinSiniri([]), k.mesajMetni('a'.repeat(k.metinSiniri(c)), c).length]; })()""")
        self.assertEqual(out[0], 0)
        self.assertEqual(out[1], out[2])
        self.assertEqual(out[3], 4000 - out[1])
        self.assertEqual(out[4], 4000)
        self.assertEqual(out[5], 4000)

    def test_at_most_five_chips_and_long_titles_are_cut(self):
        out = run_k("""(() => { let c = [];
          for (let i = 0; i < 7; i++) c = k.baglamEkle(c, {note: 'is-' + i, baslik: 'x'.repeat(60)});
          return [c.map((x) => x.note), k.baglamEtiketi(c[0]).length]; })()""")
        self.assertEqual(out[0], ["is-2", "is-3", "is-4", "is-5", "is-6"])
        self.assertLessEqual(out[1], len("İlgili: ") + 40)


@unittest.skipUnless(NODE, "node is not installed")
class StepTextTest(unittest.TestCase):
    def test_steps_read_as_plain_turkish(self):
        out = run_k("""[k.adimMetni({arac: 'Read', hedef: 'Index.md', ozet: 'okudu'}),
          k.adimMetni({arac: 'Bash', hedef: 'python3 ofis.py durum'}), k.adimMetni({arac: 'Grep', hedef: ''}),
          k.adimMetni({arac: 'Yeni', hedef: ''}), k.adimMetni(null),
          k.adimMetni({arac: 'Read', hedef: 'a\\u2028b\\nc' + 'x'.repeat(80), ozet: 'okudu'}).length <= 'okudu: '.length + 48]""")
        self.assertEqual(out, ["okudu: Index.md", "çalıştırdı: python3 ofis.py durum", "aradı", "Yeni kullandı", "", True])

    def test_the_ceo_header_line(self):
        out = run_k("""[
          k.ceoSimdiMetni({state: 'busy'}, {arac_simdi: {arac: 'Bash', hedef: 'python3 ofis.py durum', ozet: 'komut çalıştırıyor'}, sure_sn: 190}),
          k.ceoSimdiMetni({state: 'busy', current_tool: {name: 'Read', target: 'Index.md'}}, null),
          k.ceoSimdiMetni({state: 'busy'}, {arac_simdi: null, sure_sn: 20}),
          k.ceoSimdiMetni({state: 'idle'}, {sure_sn: 3700}),
          k.ceoSimdiMetni({state: 'dormant'}, null), k.ceoSimdiMetni(null, null),
          k.sureYazisi(null), k.sureYazisi(59), k.sureYazisi(7260)]""")
        self.assertEqual(out, ["CEO şu an: çalışıyor · komut çalıştırıyor: python3 ofis.py durum · 3 dk",
                               "CEO şu an: çalışıyor · okuyor: Index.md",
                               "CEO şu an: çalışıyor · düşünüyor ya da cevap yazıyor · <1 dk",
                               "CEO şu an: hazır · son işi 1 sa 1 dk önce bitti", "CEO şu an: uyuyor",
                               "CEO şu an: bilinmiyor", "", "<1 dk", "2 sa 1 dk"])

    def test_the_closing_turn_replaces_working(self):
        # Step 1 (owner decision 2026-11-12): the reply is written, the turn not ended yet
        out = run_k("""[k.ceoSimdiMetni({state: 'busy', tur_kapaniyor: true}, {arac_simdi: null, sure_sn: 20}),
          k.ceoSimdiMetni({state: 'busy', tur_kapaniyor: false}, {arac_simdi: null, sure_sn: 20}),
          k.CEO_KAPANIYOR]""")
        self.assertEqual(out, ["CEO şu an: Cevap verdi · tur kapanıyor",
                               "CEO şu an: çalışıyor · düşünüyor ya da cevap yazıyor · <1 dk",
                               "Cevap verdi · tur kapanıyor"])

    def test_the_footer_under_each_reply(self):
        out = run_k("""[k.turAltMetni({adim: 3, isler: [], usd: 0.031, token: 12400}),
          k.turAltMetni({adim: 0, isler: [], usd: 0.002, token: 900}),
          k.turAltMetni({adim: 4, usd: 0.12, token: 182000, isler: [
            {note: 'a.md', baslik: 'Giriş hatası', unvan: 'Kıdemli', akis: '', adim_sayisi: 0},
            {note: 'b.md', baslik: 'Profil', unvan: '', katman: 'planlama', akis: 'akis-1', adim_sayisi: 5}]}),
          k.turAltMetni({adim: 1, isler: [], usd: 0, token: 500, fiyat_eksik: true}),
          k.turAltMetni(null)]""")
        self.assertEqual(out[0], {"metin": "CEO kendisi baktı · 3 adım · iş açılmadı · 12,4 bin token · ≈$0,031", "isler": []})
        self.assertEqual(out[1]["metin"], "CEO kendisi cevapladı · iş açılmadı · 900 token · ≈$0,002")
        self.assertEqual(out[2], {"metin": "4 adım · 182 bin token · ≈$0,12", "isler": [
            {"note": "a.md", "metin": "İş açıldı: Giriş hatası → Kıdemli"},
            {"note": "b.md", "metin": "İş açıldı: Profil → planlama · akış, 5 adım"}]})
        self.assertEqual(out[3]["metin"], "CEO kendisi baktı · 1 adım · iş açılmadı · 500 token")
        self.assertIsNone(out[4])

    def test_each_turn_goes_under_its_last_reply(self):
        out = run_k("""k.turAltlari([{role: 'deniz', time: 't0'}, {role: 'ceo', time: 't1'}, {role: 'ceo', time: 't1'},
            {role: 'system', time: 't1', kind: 'notice'}, {role: 'ceo', time: 't2'}, {role: 'ceo', time: 't3'}],
          [{cevap_zaman: 't3', adim: 1}, {cevap_zaman: 't1', adim: 2}, {cevap_zaman: null, adim: 9}, {cevap_zaman: 'tX'}])""")
        self.assertEqual(sorted(out), ["2", "5"])
        self.assertEqual(out["2"]["adim"], 2)
        self.assertEqual(out["5"]["adim"], 1)

    def test_the_queued_indicator(self):
        out = run_k("""[k.siradaGostergesi({state: 'busy', queue: 2}), k.siradaGostergesi({state: 'busy', queue: 0}),
          k.siradaGostergesi({state: 'waiting'}), k.siradaGostergesi({state: 'idle', queue: 0}), k.siradaGostergesi(null)]""")
        self.assertEqual(out, ["Mesajın sırada: CEO şu anki işini bitirince okuyacak (2 mesaj bekliyor).",
                               "CEO çalışıyor; şimdi yazarsan mesajın sıraya girer.",
                               "CEO bir izin sorusunda bekliyor; mesajlar kuyrukta.", "", ""])

    def test_notice_actions_and_todays_spending(self):
        out = run_k("""[
          k.bildirimEylemleri('kasa akışı onay bekliyor: CSV (akis-1). Kararlar notu yazıldı: 2026-11-12-akis-kasa-onay.',
            [{note: '2026-11-12-akis-kasa-onay.md'}, {note: '2026-11-12-baska.md'}], [{note: 'a.md'}]),
          k.bildirimEylemleri('vitrin işi bitti: Giriş (2026-11-12-1-vitrin). Kontrol geçti.', [],
            [{note: '2026-11-12-1-vitrin.md'}, {note: 'a.md'}]),
          k.bildirimEylemleri('başka bir bildirim', [{note: '2026-11-12-x.md'}], []),
          k.bugunkuHarcama({ceo: {cost_today: 0.4}, projects: [{cost_today: 1.2}, {}], summary: {usage_today: 182000}}),
          k.bugunkuHarcama({}), k.HAZIR_SORULAR]""")
        self.assertEqual(out[0], {"karar": "2026-11-12-akis-kasa-onay.md", "is": ""})
        self.assertEqual(out[1], {"karar": "", "is": "2026-11-12-1-vitrin.md"})
        self.assertEqual(out[2], {"karar": "", "is": ""})
        self.assertEqual(out[3], "182 bin token · ≈$1,60")
        self.assertEqual(out[4], "≈$0,00")
        self.assertEqual(out[5], ["Durum nedir?", "Bugün ne bitti?", "Bekleyen kararlar neler?"])


class WiringTest(unittest.TestCase):
    """Static checks: the window, its three columns and tabs, the shared conversation, text only, the z-index scale."""

    def setUp(self):
        self.html = (WEB / "index.html").read_text(encoding="utf-8")
        self.app = (WEB / "app.js").read_text(encoding="utf-8")
        self.css = (WEB / "style.css").read_text(encoding="utf-8")

    def test_the_window_is_a_hidden_modal_dialog_with_three_columns_and_tabs(self):
        self.assertRegex(self.html, r'<div class="komuta" id="komuta" role="dialog" aria-modal="true" '
                                    r'aria-labelledby="komuta-title" hidden>')
        for el in ("komuta-suan", "komuta-sohbet", "komuta-kararlar", "suan-list", "ceo-simdi", "ceo-adim-list",
                   "komuta-messages", "komuta-input", "hazir-sorular", "baglam-list", "ask-list-komuta",
                   "komuta-models-list", "komuta-harcama", "komuta-feed", "komuta-sirada", "komuta-close",
                   "drawer-expand"):
            self.assertIn(f'id="{el}"', self.html)
        for sekme in ("sohbet", "suan", "kararlar"):
            self.assertIn(f'data-sekme="{sekme}"', self.html)
        self.assertIn(">Genişlet</button>", self.html)
        # the window comes before the task detail: the same modal layer, the detail paints over it
        self.assertLess(self.html.index('id="komuta"'), self.html.index('id="detail"'))

    def test_the_top_button_opens_it_and_the_drawer_stays(self):
        self.assertIn("$('open-chat-top').addEventListener('click', () => openKomuta());", self.app)
        self.assertIn("$('drawer-expand').addEventListener('click'", self.app)
        self.assertIn("$('komuta-kucult').addEventListener('click'", self.app)
        self.assertIn('id="drawer"', self.html)
        # one conversation: both boxes render the same `chat` array; the window polls only the CEO's steps
        body = self.app[self.app.index("function renderChat(grew)"):self.app.index("function renderChatBox(")]
        self.assertIn("renderChatBox($('messages'), grew, false)", body)
        self.assertIn("renderChatBox($('komuta-messages'), grew, true)", body)
        self.assertEqual(self.app.count("new EventSource("), 1)
        self.assertIn("getJson('/api/ceo/adimlar')", self.app)
        self.assertIn("setInterval(loadAdimlar, ADIM_ARALIGI)", self.app)
        self.assertIn("clearInterval(adimTimer)", self.app[self.app.index("function closeKomuta()"):])

    def test_open_pauses_the_scene_and_close_resumes_it(self):
        opener = self.app[self.app.index("function openKomuta("):self.app.index("function closeKomuta()")]
        closer = self.app[self.app.index("function closeKomuta()"):self.app.index("async function loadAdimlar()")]
        self.assertIn("office.setPaused(true); office.setLabelsHidden(true);", opener)
        self.assertIn("document.body.classList.add('komuta-acik')", opener)
        self.assertIn("office.setPaused(false); office.setLabelsHidden(document.body.classList.contains('panel-acik'))",
                      closer)
        self.assertIn("komutaFrom.focus()", closer)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("if (document.hidden || this.paused || this.labelsHidden) return;", scene)  # also under a tab panel
        self.assertIn("setPaused(paused) {", scene)
        self.assertIn("body.komuta-acik .labels, body.komuta-acik .etiket-lejant { visibility: hidden; }", self.css)

    def test_esc_closes_it_after_the_detail_and_focus_is_trapped(self):
        esc = self.app[self.app.rindex("if (e.key !== 'Escape') return;"):]
        self.assertIn("if (!$('detail').hidden) detailBack();\n  else if (komutaOpen()) closeKomuta();", esc)
        self.assertIn("if (e.key !== 'Tab' || !komutaOpen()) return;", self.app)
        self.assertIn("if (!$('detail').hidden) roots.push($('detail'));", self.app)
        # the zoom keys and the click-outside handlers leave the window alone
        self.assertIn("!$('calisanlar').hidden || komutaOpen()) return;", self.app)
        self.assertEqual(self.app.count("#scrim, #komuta')"), 1)
        self.assertIn(".overlay, #komuta')", self.app)

    def test_a_job_click_opens_its_detail_and_adds_a_chip_and_send_appends_the_line(self):
        row = self.app[self.app.index("function suAnRow(it)"):self.app.index("function renderBaglam()")]
        self.assertIn("baglam = baglamEkle(baglam, { note: it.note, baslik: it.baslik });", row)
        self.assertIn("openDetail({ kind: 'task', note: it.note });", row)
        self.assertIn("const text = mesajMetni(ta.value, baglam);", self.app)
        self.assertIn("if (await sendChat(text)) { ta.value = ''; baglam = []; renderBaglam(); }", self.app)
        # Enter sends, Shift+Enter is a new line
        self.assertIn("$('komuta-input').addEventListener('keydown', (e) => {\n  if (e.key === 'Enter' && !e.shiftKey", self.app)
        # the detail opened over the window is a right-hand sheet
        self.assertIn("$('detail').classList.toggle('in-komuta', komutaOpen());", self.app)
        self.assertIn(".modal.in-komuta {", self.css)

    def test_switching_windows_moves_the_draft_and_drops_the_chips(self):
        # review MINORs 2 and 3: the draft moves (the source is cleared) both ways; Küçült drops the chips
        small = self.app[self.app.index("$('komuta-kucult').addEventListener('click'"):
                         self.app.index("$('drawer-expand').addEventListener('click'")]
        big = self.app[self.app.index("$('drawer-expand').addEventListener('click'"):
                       self.app.index("// a click on the backdrop (outside the card) closes it")]
        self.assertIn("moveDraft($('komuta-input'), $('drawer-input'));", small)
        self.assertIn("baglam = [];", small)
        self.assertIn("renderBaglam();", small)
        self.assertIn("moveDraft($('drawer-input'), $('komuta-input'));", big)
        helper = self.app[self.app.index("function moveDraft(from, to)"):]
        self.assertIn("from.value = '';", helper[:400])
        # the composer's maxlength leaves room for the chip line; the error names it
        self.assertIn("$('komuta-input').maxLength = metinSiniri(baglam);", self.app)
        self.assertIn("bağlam satırıyla birlikte", self.app)

    def test_text_only_and_the_z_index_scale(self):
        komuta = (WEB / "komuta.js").read_text(encoding="utf-8")
        for src in (self.app, komuta):
            self.assertNotRegex(src, r"\.innerHTML\s*=|insertAdjacentHTML\(|\.outerHTML\s*=")
        self.assertNotRegex(komuta, r"document\.|window\.")
        block = self.css[self.css.index(".komuta {"):]
        self.assertIn("z-index: var(--z-modal)", block[:400])
        self.assertNotRegex(block, r"z-index: \d")
        # narrow: tabs; phone: full screen
        self.assertIn("@media (max-width: 1099px) { /* narrow: three tabs", self.css)
        self.assertRegex(self.css, r"@media \(max-width: 600px\) \{ /\* phone: a full-screen sheet \*/\s*\.komuta \{ padding: 0; \}")

    def test_the_demo_fakes_the_steps_without_a_backend(self):
        demo = (WEB / "demo.js").read_text(encoding="utf-8")
        self.assertIn("if (path === '/api/ceo/adimlar')", demo)
        self.assertIn("if (path === '/api/ceo/turlar')", demo)
        self.assertIn("kind: 'notice'", demo)
        self.assertIn("cost_today", demo)
        self.assertNotRegex(demo, r"\bfetch\(")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_modules_parse(self):
        for name in ("komuta.js", "app.js", "scene.js"):
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / (Path(name).stem + ".mjs")
                shutil.copyfile(WEB / name, target)
                proc = subprocess.run([NODE, "--check", str(target)], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")



class AnnouncementFormTest(unittest.TestCase):
    """"Duyuru yap" in the Komuta masası (POST /api/duyuru, bin/duyuru.py)."""

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_body_and_the_result_line(self):
        out = run_k("""[k.duyuruGovdesi('  Cuma deploy yok. ', 'bugun'), k.duyuruGovdesi('x', 'tarih', '2026-11-20'),
          k.duyuruGovdesi('', 'simdi'), k.duyuruGovdesi('x', 'tarih', ''), k.duyuruGovdesi('x', 'yarin'),
          k.duyuruGovdesi('x'.repeat(2001), 'simdi'), k.duyuruSonucu({ hedef: 2, bitis: '2026-11-12T23:59:59' }),
          k.duyuruSonucu({ hedef: 0, bitis: '' })]""")
        self.assertEqual(out[0], {"govde": {"metin": "Cuma deploy yok.", "sure": "bugun"}})
        self.assertEqual(out[1], {"govde": {"metin": "x", "sure": "2026-11-20"}})
        for bad in out[2:6]:
            self.assertIn("hata", bad)
        self.assertEqual(out[6], "Duyuru kaydedildi: 2 çalışan oturuma iletilecek; 2026-11-12 23:59 saatine kadar yeni "
                                 "işlere de eklenir.")
        self.assertEqual(out[7], "Duyuru kaydedildi: şu an çalışan oturum yok.")

    def test_the_form_is_wired_to_the_endpoint_with_the_token(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for need in ('id="duyuru-form"', 'id="duyuru-metin"', 'maxlength="2000"', 'id="duyuru-sure-sec"',
                     '<option value="simdi" data-t="Yalnız şimdi">Yalnız şimdi</option>',
                     '<option value="hafta" data-t="Bu hafta">Bu hafta</option>',
                     'id="duyuru-tarih" type="date"'):
            self.assertIn(need, html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("post('/api/duyuru', g.govde)", app)
        self.assertIn("$('duyuru-durum').textContent = duyuruSonucu(r.data)", app)
        demo = (WEB / "demo.js").read_text(encoding="utf-8")
        self.assertIn("if (path === '/api/duyuru')", demo)


class BrandTest(unittest.TestCase):
    """The office's name (ofis.json ofis_adi, the Ayarlar tab; /api/state.ofis.adi): the top bar's text, the tab
    title and the scene's sign; no company logo files (plan "Ayarlar sayfası" 1.6)."""

    def test_the_top_bar_shows_the_name_as_text_and_the_title_defaults_to_ofis(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>Ofis</title>", html)
        self.assertIn('<span class="brand-ad" id="brand-ad">Ofis</span>', html)
        self.assertIn('<link rel="icon" href="favicon.svg" type="image/svg+xml">', html)
        self.assertNotIn("brand/", html)
        self.assertNotIn("<img", html)
        self.assertIn("İyi günler.", html)  # the greeting stays as it is
        self.assertFalse((WEB / "brand").exists())

    def test_the_page_takes_the_name_from_the_state(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        body = app[app.index("function renderOfisAdi()"):app.index("\n}\n", app.index("function renderOfisAdi()"))]
        self.assertIn("state.ofis", body)
        self.assertIn("$('brand-ad').textContent = ad", body)
        self.assertIn("baseTitle = ad", body)
        self.assertIn("office.setOfisAdi(ad)", body)
        self.assertIn("renderOfisAdi();", app[app.index("function renderAll()"):])


if __name__ == "__main__":
    unittest.main()
