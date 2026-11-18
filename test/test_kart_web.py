"""Page tests for the approval card's new order and quiz, the approval backlog strip, the merged top-bar pill and the
top-bar date (web/ofis-text.js under node; app.js / index.html / style.css static checks). Skipped without node."""
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


def run_js(expr, tz=None):
    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "ofis-text.mjs"
        (Path(tmp) / "ofis-davranis.mjs").write_text(  # the owner's name helpers
            webkopya.mjs_yap((WEB / "ofis-davranis.js").read_text(encoding="utf-8")), encoding="utf-8")
        webkopya.i18n_ekle(tmp, mjs=True)
        module.write_text(webkopya.mjs_yap((WEB / "ofis-text.js").read_text(encoding="utf-8")), encoding="utf-8")
        code = (f"import * as t from {json.dumps(module.as_uri())};\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        env = dict(os.environ, TZ=tz) if tz else None
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              env=env)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def app():
    return (WEB / "app.js").read_text(encoding="utf-8")


@unittest.skipUnless(NODE, "node is not installed")
class CardOrderTest(unittest.TestCase):
    def test_evidence_first_and_the_summary_last_whatever_the_server_order(self):
        ev = [{"title": t, "text": "x"} for t in ("Plan özeti", "Kullanım", "İnceleme", "Nasıl test edildi",
                                                  "Ajanın kararları ve varsayımları", "Bilinmeyen",
                                                  "Kontrol neyi kanıtladı / kanıtlamadı")]
        out = run_js(f"t.kartBolumleri({json.dumps(ev)}).map((e) => e.title)")
        self.assertEqual(out, ["Nasıl test edildi", "Kontrol neyi kanıtladı / kanıtlamadı",
                               "Ajanın kararları ve varsayımları", "İnceleme", "Bilinmeyen", "Plan özeti", "Kullanım"])
        self.assertEqual(run_js("t.kartBolumleri(null)"), [])

    def test_the_quiz_items_are_plain_and_capped(self):
        q = [{"soru": "A?", "cevap": "a"}, {"soru": "B?", "cevap": ""}, {"soru": "<b>C</b>", "cevap": "c"},
             {"soru": "D?", "cevap": "d"}, {"soru": "E?", "cevap": "e"}, 5]
        self.assertEqual(run_js(f"t.sinavMaddeleri({json.dumps(q)})"),
                         [{"baslik": "Soru 1", "soru": "A?", "cevap": "a"},
                          {"baslik": "Soru 2", "soru": "<b>C</b>", "cevap": "c"},
                          {"baslik": "Soru 3", "soru": "D?", "cevap": "d"}])
        self.assertEqual(run_js("t.sinavMaddeleri(undefined)"), [])
        self.assertEqual(run_js("t.SINAV_BASLIGI"), "Kendini yokla (isteğe bağlı)")

    def test_the_page_renders_the_card_in_that_order_with_the_answers_behind_a_toggle(self):
        a = app()
        body = a[a.index("function syncAsks("):a.index("function renderAsks(")]
        self.assertIn("kartBolumleri(d.evidence)", body)
        self.assertIn("renderQuiz(card.parts.quiz, sinavMaddeleri(d.quiz))", body)
        quiz = a[a.index("function renderQuiz("):a.index("function syncAsks(")]
        self.assertIn("h('details', 'ask-quiz-answer')", quiz)
        self.assertIn("h('summary', null, T('Cevabı göster'))", quiz)
        self.assertNotIn("innerHTML", quiz)
        build = a[a.index("function buildAsk("):a.index("function renderQuiz(")]
        self.assertLess(build.index("evidence, quiz, secenekler, ta"), len(build), "the quiz comes after the evidence")
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".ask-quiz-answer summary", css)


class CharacterCardGroupTest(unittest.TestCase):
    """The guard's "Ofiste olanlar / Evde olanlar" rows are groups (owner decision 2026-11-12): a row with `uyeler` is a
    details/summary built with textContent only, and a group the viewer opened stays open when the card is rebuilt."""

    def test_a_group_row_is_a_details_element_built_with_text_only(self):
        a = app()
        body = a[a.index("function kartGoster("):a.index("// The data some staff cards read")]
        self.assertIn("h('details', 'karakter-kart-grup')", body)
        self.assertIn("h('summary', null, o.metin)", body)  # drawn by the one card component (kartIcerigi)
        self.assertIn("linkli('li', null, u)", body)  # text only; [[links]] open in Obsidian (2026-11-13)
        self.assertIn("acik.has(o.anahtar)", body)  # an open group stays open across the 1 s rebuild
        self.assertIn("details[data-anahtar][open]", body)
        self.assertNotIn("innerHTML", body)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".karakter-kart-grup > summary", css)


@unittest.skipUnless(NODE, "node is not installed")
class BacklogAndPillTest(unittest.TestCase):
    def test_the_backlog_strip_text(self):
        self.assertEqual(run_js("t.onayBiriktiMetni({onay_birikti: {bekleyen: 2, sinir: 2}})"),
                         "Onay bekleyen 2 kart var; yeni kod işleri bekliyor")
        self.assertEqual(run_js("t.onayBiriktiMetni({onay_birikti: {bekleyen: 1, sinir: 2}})"), "")
        self.assertEqual(run_js("t.onayBiriktiMetni({onay_birikti: {bekleyen: '2', sinir: 2}})"), "")
        self.assertEqual(run_js("t.onayBiriktiMetni(null)"), "")
        self.assertEqual(run_js("t.onayBekletmeMetni({onay_birikti: true})"), "onay birikişi nedeniyle bekliyor")
        self.assertEqual(run_js("t.onayBekletmeMetni({onay_birikti: 'evet'})"), "")
        # Step 4: the model and its quota backup both on quota
        self.assertEqual(run_js("t.onayBekletmeMetni({kota_bekliyor: 'Uzman ve yedeği Kıdemli kotada'})"),
                         "kota nedeniyle bekliyor: Uzman ve yedeği Kıdemli kotada")
        self.assertEqual(run_js("t.onayBekletmeMetni({kota_bekliyor: 3})"), "")
        # Step 5: a running job resumed after its quota came back
        self.assertEqual(run_js("t.kotaDevamMetni({kota_devam: '2026-11-13T16:42:10'})"),
                         "kota döndü, devam ettirildi (16:42)")
        self.assertEqual(run_js("t.kotaDevamMetni({kota_devam: ''})"), "")
        self.assertEqual(run_js("t.kotaDevamMetni({kota_devam: 'x'})"), "")

    def test_one_pill_says_who_works_and_the_limit_only_at_the_limit(self):
        idle = run_js("t.canliPill({running: 0, max_running: 3}, 0)")
        self.assertEqual((idle["metin"], idle["ton"]), ("Herkes dinleniyor", ""))
        self.assertIn("Aynı anda en çok 3 iş çalışır (ofis.json max_running)", idle["baslik"])
        self.assertEqual(run_js("t.canliPill({running: 2, max_running: 3}, 2).metin"), "2 ajan çalışıyor")
        full = run_js("t.canliPill({running: 3, max_running: 3}, 4)")
        self.assertEqual((full["metin"], full["ton"]), ("3/3 · sınırda, yeni işler sırada", "sinirda"))
        held = run_js("t.canliPill({running: 1, max_running: 3, onay_birikti: {bekleyen: 2, sinir: 2}}, 1).metin")
        self.assertEqual(held, "1 ajan çalışıyor · onay bekleniyor")
        self.assertEqual(run_js("t.canliPill(null, 0).metin"), "Herkes dinleniyor")
        over = run_js("t.canliPill({running: 5, max_running: 4}, 5)")
        self.assertEqual((over["metin"], over["ton"]), ("5 çalışıyor · sınır 4 aşıldı", "sinirda"))

    def test_the_page_wires_the_strip_the_pill_and_the_board_mark(self):
        a = app()
        for name in ("canliPill(state && state.summary, n)", "onayBiriktiMetni(state && state.summary)",
                     "$('onay-birikti-text').textContent", "onayBekletmeMetni(t)", "pill.title = live.baslik"):
            self.assertIn(name, a)
        self.assertNotIn("runningText(", a)
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'id="onay-birikti"[^>]*hidden')
        self.assertIn('id="onay-birikti-text"', html)
        self.assertLess(html.index('id="onay-birikti"'), html.index('id="po-warn"'))


@unittest.skipUnless(NODE, "node is not installed")
class DateTest(unittest.TestCase):
    INSTANT = "Date.UTC(2026, 10, 11, 20, 4)"  # 23:04 in Istanbul

    def test_the_date_is_read_in_the_office_zone_whatever_the_process_zone(self):
        for tz in ("UTC", "America/New_York"):
            out = run_js(f"t.tarihMetni({self.INSTANT}, 'Europe/Istanbul')", tz=tz)
            self.assertEqual(out, {"saat": "23:04", "tarih": "Çarşamba, 11 Kasım 2026", "kisa": "Çar 11 Kas"}, tz)
        ny = run_js(f"t.tarihMetni({self.INSTANT}, 'America/New_York')", tz="UTC")
        self.assertEqual(ny["saat"], "15:04")
        self.assertEqual(run_js(f"t.tarihMetni({self.INSTANT}, 'Bad/Zone').saat", tz="UTC"), "23:04")
        late = run_js("t.tarihMetni(Date.UTC(2026, 10, 11, 22, 30), 'Europe/Istanbul').tarih", tz="America/New_York")
        self.assertEqual(late, "Perşembe, 12 Kasım 2026", "after midnight in the office it is the next day")

    def test_the_clock_uses_it(self):
        a = app()
        self.assertIn("tarihMetni(Date.now(), state && state.sahne && state.sahne.saat_dilimi)", a)
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for el in ("clock-time", "clock-date", "clock-date-short"):
            self.assertIn(f'id="{el}"', html)


def run_demo(expr):
    """Evaluates `expr` with web/demo.js as `demo` and web/ofis-sahne.js as `h` (package.json type=module)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name in ("ofis-sahne.js", "ofis-davranis.js", "demo.js", "ofis-text.js"):
            shutil.copyfile(WEB / name, Path(tmp) / name)
        webkopya.i18n_ekle(tmp)
        uri = json.dumps((Path(tmp) / "demo.js").as_uri())
        sahne = json.dumps((Path(tmp) / "ofis-sahne.js").as_uri())
        code = (f"import * as demo from {uri};\nimport * as h from {sahne};\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class DemoCardTest(unittest.TestCase):
    NOW = 1794430800000  # 2026-11-11T12:00:00Z (fixed)

    def test_the_demo_card_shows_the_new_order_the_decisions_and_the_quiz(self):
        t = run_demo("demo.DEMO_SAHNELERI.find((x) => x.id === 'yukseltme').bas")
        self.assertEqual(run_demo(f"demo.demoDurumu(2, {self.NOW}).decisions.length"), 0, "not at the start")
        d = run_demo(f"demo.demoDurumu({t + 1}, {self.NOW}, {{today: '2026-11-11'}})")
        [card] = [x for x in d["decisions"] if x.get("kind") == "akis-onay"]
        titles = [e["title"] for e in card["evidence"]]
        self.assertEqual(titles[:3], ["Nasıl test edildi", "Kontrol neyi kanıtladı / kanıtlamadı",
                                      "Ajanın kararları ve varsayımları"])
        self.assertEqual(titles[-2:], ["Plan özeti", "Kullanım"])
        self.assertEqual(len(card["quiz"]), 2)
        self.assertEqual(d["onay_birikti"], {"bekleyen": 1, "sinir": 2})

    def test_the_demo_never_runs_more_jobs_than_its_limit(self):
        rows = run_demo("""Array.from({length: demo.DEMO_SURE * 2}, (_, i) => demo.demoDurumu(i / 2, 1794430800000).tasks
          .filter((t) => ['baslatiliyor', 'calisiyor', 'kontrolde'].includes(t.status)).length)""")
        limit = run_demo("demo.DEMO_MAX_RUNNING")
        self.assertLessEqual(max(rows), limit, rows)

    def test_the_lunch_scene_shows_the_approval_backlog(self):
        ogle = run_demo("demo.DEMO_SAHNELERI.find((x) => x.id === 'ogle').bas")
        d = run_demo(f"demo.demoDurumu({ogle + 1}, {self.NOW}, {{today: '2026-11-11'}})")
        self.assertEqual(d["onay_birikti"], {"bekleyen": 2, "sinir": 2})
        held = [t for t in d["tasks"] if t.get("onay_birikti")]
        self.assertEqual([(t["status"], t["tier"]) for t in held], [("sirada", "kod")])


@unittest.skipUnless(NODE, "node is not installed")
class OfficeVocabularyTest(unittest.TestCase):
    """The owner, 2026-11-11: an office has workers, not models — the role first, the model only in parentheses."""

    def test_the_workers_list_is_grouped_kadro_then_denetciler(self):
        rows = run_demo("""h.modelSatirlari([{model: 'haiku', durum: 'hazir'}, {model: 'opus', durum: 'kota'},
          {model: 'codex', durum: 'hazir'}, {model: 'glm', unvan: 'Dış denetçi', durum: 'hazir'},
          {model: 'guvenlik', unvan: 'Güvenlik denetçisi', ajan_modeli: 'sonnet', durum: 'hazir'}],
          Date.UTC(2026, 10, 11, 9)).map((r) => [r.grup, r.ad])""")
        self.assertEqual(rows, [["kadro", "Stajyer (Haiku)"], ["kadro", "Uzman (Sonnet)"], ["kadro", "Kıdemli (Opus)"],
                                ["kadro", "Genel Müdür (Fable)"], ["denetci", "Codex"], ["denetci", "GLM"],
                                ["denetci", "Güvenlik denetçisi (Sonnet)"]])
        groups = run_demo("""h.calisanGruplari(h.modelSatirlari([], Date.UTC(2026, 10, 11, 9)))
          .map((g) => [g.baslik, g.rows.length])""")
        self.assertEqual(groups, [["Kadro", 4], ["Denetçiler", 1]])

    def test_a_worker_name_and_the_table_column(self):
        self.assertEqual(run_demo("[h.calisanAdi('Kıdemli', 'opus'), h.calisanAdi('Dış denetçi', 'codex'), "
                                  "h.calisanAdi('Hakem', 'sonnet'), h.calisanAdi('Güvenlik denetçisi (Sonnet)', 'x'), "
                                  "h.calisanAdi('CEO', ''), h.CALISANLAR_BASLIK[2]]"),
                         ["Kıdemli (Opus)", "Dış denetçi (Codex)", "Hakem (Sonnet)", "Güvenlik denetçisi (Sonnet)",
                          "CEO", "Çalışan"])
        self.assertEqual(run_js("[t.calisanMetni('claude-opus-5-5'), t.calisanMetni('haiku'), t.calisanMetni(''), "
                                "t.calisanMetni('gpt-x'), t.QUALITY_HEAD[2], t.MAPPING_HEAD[2]]"),
                         ["Kıdemli (Opus)", "Stajyer (Haiku)", "", "gpt-x", "Çalışan", "Çalışan"])

    def test_the_camera_fit_keeps_a_clear_margin(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("export const FIT_MARGIN_PX = 28;", scene)
        fit = scene[scene.index("  fit() {"):scene.index("  yakinlastir(")]
        self.assertIn("this.visHalfW - mx", fit)
        self.assertIn("view / 2 - my", fit)

    def test_the_page_says_calisanlar_not_modeller(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for text in (">Çalışanlar</span> <", 'id="calisanlar-kadro-title" data-t="Çalışanlar">Çalışanlar</h3>', "Şu an iş başında", "Unvana göre",
                     "Kadro ve görev dağılımı"):
            self.assertIn(text, html)
        for old in ("Modeller", "Modele göre", "Model seçimi", "Şu an çalışanlar"):
            self.assertNotIn(old, html)
        self.assertIn("calisanGruplari(rows)", app())
        # (the 3D wall board that drew 'Çalışanlar' is gone: the live pill's popover lists them, owner decision 2026-11-12)
        self.assertNotIn("'Çalışanlar'", (WEB / "scene.js").read_text(encoding="utf-8"))


@unittest.skipUnless(NODE, "node is not installed")
class DecisionBellTest(unittest.TestCase):
    """Pending decisions as a notification in the top bar (the owner, 2026-11-12): a bell badge with the count next to the
    live pill, the tab title's "(N) " prefix, a gentle pulse when the count rises; answered cards do not count."""

    DECISIONS = [{"note": "b.md", "title": "İkinci", "asked": "2026-11-12T10:00:00"},
                 {"note": "a.md", "title": "En eski", "asked": "2026-11-12T08:00:00"},
                 {"note": "c.md", "title": "Cevaplandı", "asked": "2026-11-12T07:00:00", "answer_sent": True},
                 {"note": "d.md", "title": "Sayfadan gönderildi", "asked": "2026-11-12T06:00:00"}]

    def test_the_count_leaves_out_answered_cards_and_names_the_oldest(self):
        out = run_js(f"t.kararBildirimi({json.dumps(self.DECISIONS)}, ['d.md'])")
        self.assertEqual(out["sayi"], 2)
        self.assertEqual(out["metin"], "2 karar bekliyor")
        self.assertEqual(out["enEski"], "a.md")
        self.assertIn("En eski", out["baslik"])
        self.assertEqual(run_js("t.kararBildirimi([], [])"), {"sayi": 0, "metin": "", "baslik": "", "enEski": None})
        self.assertEqual(run_js("t.kararBildirimi(undefined)")["sayi"], 0)
        one = run_js("t.kararBildirimi([{note: 'x.md', title: 'X', asked: ''}])")
        self.assertEqual((one["metin"], one["enEski"]), ("1 karar bekliyor", "x.md"))

    def test_the_tab_title_prefix_and_the_pulse_rule(self):
        self.assertEqual(run_js("t.sekmeBasligi('Ofis', 2)"), "(2) Ofis")
        self.assertEqual(run_js("t.sekmeBasligi('(2) Ofis', 3)"), "(3) Ofis")
        self.assertEqual(run_js("t.sekmeBasligi('(3) Ofis', 0)"), "Ofis")
        # pulse only when the count rises, never on the first render
        self.assertEqual(run_js("[t.kararArtti(null, 2), t.kararArtti(1, 2), t.kararArtti(2, 2), t.kararArtti(3, 1)]"),
                         [False, True, False, False])

    def test_the_page_wires_the_bell_safely_and_without_motion_when_reduced(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        tag = re.search(r'<button[^>]*id="karar-bildirim"[^>]*>', html)
        self.assertTrue(tag and "hidden" in tag.group(0), "hidden until a decision waits")
        self.assertLess(html.index('id="live-pill"'), html.index('id="karar-bildirim"'))  # next to the live pill
        self.assertNotIn("Notification.requestPermission", app())  # never asks for permission by itself
        a = app()
        body = a[a.index("function renderKararBildirimi("):]
        body = body[:body.index("\n}\n") + 3]
        for needle in ("kararBildirimi(", "renderSekmeBasligi(", "kararArtti(", "textContent"):
            self.assertIn(needle, body)
        # the title itself is set in one place, shared with the unread CEO lines (2026-11-14)
        sekme = a[a.index("function renderSekmeBasligi("):]
        sekme = sekme[:sekme.index("\n}\n") + 3]
        for needle in ("sekmeBasligi(", "document.title"):
            self.assertIn(needle, sekme)
        self.assertNotRegex(a, r"\.innerHTML\s*=|insertAdjacentHTML\(")
        self.assertIn("focusDecision(", a[a.index("$('karar-bildirim').addEventListener('click'"):][:400])
        # ?sekme=<tab> opens a tab panel at load (screenshots), only one of the known panels
        self.assertIn("const sekmeParam = params.get('sekme');\nif (OVERLAYS.includes(sekmeParam))", a)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn("@keyframes karar-nabiz", css)
        reduced = css[css.index("@media (prefers-reduced-motion: reduce) { .karar-bildirim"):][:200]
        self.assertIn("animation: none", reduced)


if __name__ == "__main__":
    unittest.main()
