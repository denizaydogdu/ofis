"""Tests for the page's text helpers in web/ofis-text.js (system-notice cards, post office warnings).

They run the ES module under node when it is installed and are skipped otherwise; the page itself has no build step
and no dependencies."""
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
import webkopya  # noqa: E402  (web/i18n.js next to the copied modules)
import sahip_yasaklari  # noqa: E402,F401  (the owner's name as in his ofis.json; node reads it too)

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")


def as_module(name, folder):
    """Copies web/<name> to folder/<name>.mjs: node reads a bare .js without package.json as CommonJS, the browser
    loads it as a module (type="module"). An import of ./ofis-davranis.js (the owner's name helpers, also imported by
    ofis-text.js) is copied along as .mjs and the import rewritten."""
    target = Path(folder) / (Path(name).stem + ".mjs")
    text = (WEB / name).read_text(encoding="utf-8")
    if "'./ofis-davranis.js'" in text:
        (Path(folder) / "ofis-davranis.mjs").write_text(
            webkopya.mjs_yap((WEB / "ofis-davranis.js").read_text(encoding="utf-8")), encoding="utf-8")
    webkopya.i18n_ekle(folder, mjs=True)
    target.write_text(webkopya.mjs_yap(text), encoding="utf-8")
    return target


def run_js(expr):
    """Evaluates `expr` with web/ofis-text.js imported as `t`; returns the JSON-decoded result."""
    with tempfile.TemporaryDirectory() as tmp:
        module = as_module("ofis-text.js", tmp)
        code = (f"import * as t from {json.dumps(module.as_uri())};\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class NoticeCardTest(unittest.TestCase):
    def test_first_line_is_the_title_and_quoted_lines_the_body(self):
        text = "yayin işi bitti: Giriş hatası (2026-11-10-1-yayin). Özet:\n> Düzeldi.\n> \n> 12 test geçti."
        self.assertEqual(run_js(f"t.noticeParts({json.dumps(text)})"),
                         {"title": "yayin işi bitti: Giriş hatası (2026-11-10-1-yayin). Özet:",
                          "body": "Düzeldi.\n\n12 test geçti.", "tone": "done"})

    def test_tone_follows_the_kind_of_notice(self):
        for first, tone in (("yayin işi takıldı: x. Neden:", "blocked"),
                            ("yayin soruyor (karar: a.md): x. Soru:", "ask"),
                            ("başka bir bildirim", "info")):
            with self.subTest(first=first):
                self.assertEqual(run_js(f"t.noticeParts({json.dumps(first + chr(10) + '> x')}).tone"), tone)

    def test_a_group_report_notice_is_a_done_card(self):
        text = "yayin grubu bitti: Giriş (giris). 2 iş: 2 bitti. Rapor: [[giris]] (Obsidian'da OFIS/Raporlar)."
        self.assertEqual(run_js(f"t.noticeParts({json.dumps(text)}).tone"), "done")

    def test_a_notice_without_quoted_lines_keeps_its_text(self):
        self.assertEqual(run_js("t.noticeParts('tek satır')"), {"title": "tek satır", "body": "", "tone": "info"})


@unittest.skipUnless(NODE, "node is not installed")
class SahipAdiTest(unittest.TestCase):
    """The owner's name on the page (plan "2. Aşama"): web/ofis-davranis.js sahipEk / sahipAyarla, re-exported by
    ofis-text.js; the same suffix rule as bin/sahip.py ek."""

    def test_the_suffixes_match_the_server_helper(self):
        sys.path.insert(0, str(WEB.parent / "bin"))
        import sahip
        names = ["Ali", "Ayşe", "Selin", "Murat", "Sahip", "Duru", "Övgü", "Gönül", "Yıldız", "Barış", "Tarık",
                 "Yusuf", "Gökçe", "İLKER", "IŞIK", "Hâle", "Ümit", "Oğuz Bora", "Brr"]
        got = run_js(f"{json.dumps(names)}.map((n) => ['e', 'in', 'den', 'i', 'de'].map((h) => t.sahipEk(n, h)))")
        self.assertEqual(got, [[sahip.ek(n, h) for h in sahip.HALLER] for n in names])
        self.assertEqual(got[2], ["Selin'e", "Selin'in", "Selin'den", "Selin'i", "Selin'de"])
        self.assertEqual(got[3][2], "Murat'tan")

    def test_the_default_name_and_the_state_name(self):
        env = {k: v for k, v in os.environ.items() if k != "OFIS_SAHIP_ADI"}
        with tempfile.TemporaryDirectory() as tmp:
            module = as_module("ofis-text.js", tmp)
            code = (f"import * as t from {json.dumps(module.as_uri())};\n"
                    "const a = t.queueText({status: 'sirada', queue_position: 1, held: true});\n"
                    "t.sahipAyarla({adi: 'Murat'});\n"
                    "const b = t.queueText({status: 'sirada', queue_position: 1, held: true});\n"
                    "t.sahipAyarla('[Sahip · x]');\n"  # never a prefix-like name: the name stays
                    "const c = t.workflowProgressText({tamam: 1, toplam: 3, durum: 'deniz'});\n"
                    "process.stdout.write(JSON.stringify([a, b, c]));")
            proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True,
                                  timeout=30, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), ["sırada 1. · bekletiliyor (Sahip bırakınca başlar)",
                                                   "sırada 1. · bekletiliyor (Murat bırakınca başlar)",
                                                   "1/3 adım · durdu, Murat'ın kararı bekleniyor"])

    def test_the_card_hides_the_ceo_part_under_any_owner_name(self):
        text = ("Sunucu odası (yayin): yayin.app açılmıyor. Murat'a tek satırla söyle; ofis hiçbir şeyi "
                "değiştirmez.")
        got = run_js(f"(t.sahipAyarla('Murat'), t.bildirimKarti({json.dumps(text)}).ham)")
        self.assertNotIn("Murat'a", got)
        duyuru = "Murat'ın duyurusu 2 oturuma iletildi. Not: [[Duyuru-x]]. Murat'a tek satırla söyle."
        card = run_js(f"(t.sahipAyarla('Murat'), t.bildirimKarti({json.dumps(duyuru)}))")
        self.assertEqual((card["tur"], card["baslik"]), ("duyuru", "Murat'ın duyurusu iletildi"))
        self.assertIn(["İletilen", "2 oturum"], card["satirlar"])
        # the old notice of the same office still reads (old protocol: written under the earlier owner name)
        card = run_js(f"t.bildirimKarti({json.dumps(duyuru.replace('Murat', 'Deniz').replace('ın', 'in', 1))})")
        self.assertEqual(card["tur"], "duyuru")


@unittest.skipUnless(NODE, "node is not installed")
class BudgetTextTest(unittest.TestCase):
    def test_an_active_job_shows_spending_against_its_limits(self):
        t = {"status": "calisiyor", "spent": "1.25", "budget": 5, "calls": "12", "max_calls": 40}
        self.assertEqual(run_js(f"t.budgetText({json.dumps(t)})"), "≈$1,25 / ≈$5,00 · 12 / 40 çağrı")

    def test_small_amounts_are_not_shown_as_zero(self):
        # phase 2 review finding 12: a $0.002 budget was shown as $0.00
        t = {"status": "calisiyor", "spent": "0.0061", "budget": "0.002", "calls": "2", "max_calls": 15}
        self.assertEqual(run_js(f"t.budgetText({json.dumps(t)})"), "≈$0,0061 / ≈$0,002 · 2 / 15 çağrı")
        t = {"status": "calisiyor", "spent": "0.0123", "budget": "0.05", "calls": "2", "max_calls": 15}
        self.assertEqual(run_js(f"t.budgetText({json.dumps(t)})"), "≈$0,0123 / ≈$0,05 · 2 / 15 çağrı")

    def test_unknown_values_and_finished_jobs(self):
        t = {"status": "kontrolde", "spent": "", "budget": 3, "calls": "", "max_calls": None}
        self.assertEqual(run_js(f"t.budgetText({json.dumps(t)})"), "≈$0,00 / ≈$3,00 · 0 / ? çağrı")
        self.assertEqual(run_js("t.budgetText({status: 'bitti', spent: '1', budget: 3})"), "")
        self.assertEqual(run_js("t.budgetText({status: 'calisiyor'})"), "")

    def test_a_stopped_job_notice_is_a_blocked_card(self):
        text = "yayin işi durduruldu: Giriş (x). Bütçe aşıldı: $4,00 / $3,00."
        self.assertEqual(run_js(f"t.noticeParts({json.dumps(text)}).tone"), "blocked")


@unittest.skipUnless(NODE, "node is not installed")
class ScheduleTextTest(unittest.TestCase):
    """The Zamanlanmış tab's rows (the owner, 2026-11-13: moved out of the side panel); the scheduler's notices are blocked
    cards."""

    def test_an_active_schedule_shows_its_next_run_and_its_last_runs_as_note_names(self):
        s = {"ad": "gunluk", "proje": "yayin", "baslik": "Günlük test", "zaman": "her gün 09:00",
             "sonraki": "2026-11-12T09:00", "duraklatildi": False, "neden": "", "son_is": "2026-11-11-090000-yayin.md",
             "son_sonuc": "bitti",
             "kosular": [{"slot": "2026-11-11T09:00", "is": "2026-11-11-090000-yayin.md", "sonuc": "tikandi",
                          "son_is": "2026-11-11-101500-yayin.md"},
                         {"slot": "2026-11-10T09:00", "is": "2026-11-10-090000-yayin.md", "sonuc": ""}]}
        [r] = run_js(f"t.zamanlanmisSatirlari([{json.dumps(s)}, null, {{}}])")
        self.assertEqual({k: r[k] for k in ("ad", "proje", "baslik", "zaman", "sonraki", "durum", "neden", "sonKosu")},
                         {"ad": "gunluk", "proje": "yayin", "baslik": "Günlük test", "zaman": "her gün 09:00",
                          "sonraki": "12.11 09:00", "durum": "etkin", "neden": "", "sonKosu": "takıldı · 11.11 09:00"})
        self.assertEqual(r["kosular"], [
            {"zaman": "11.11 09:00", "is": "2026-11-11-090000-yayin", "sonuc": "takıldı",
             "son_is": "2026-11-11-101500-yayin"},
            {"zaman": "10.11 09:00", "is": "2026-11-10-090000-yayin", "sonuc": "sürüyor", "son_is": ""}])

    def test_a_paused_schedule_says_so_and_an_older_server_still_links_its_last_run(self):
        s = {"ad": "aksam", "proje": "yayin", "baslik": "", "zaman": "her gün 18:30", "sonraki": "",
             "duraklatildi": True, "neden": "art arda 2 koşu başarısız oldu", "son_is": "2026-11-10-183000-yayin.md",
             "son_sonuc": "basarisiz"}
        [r] = run_js(f"t.zamanlanmisSatirlari([{json.dumps(s)}])")
        self.assertEqual((r["baslik"], r["sonraki"], r["durum"], r["neden"], r["sonKosu"]),
                         ("aksam", "—", "duraklatıldı", "art arda 2 koşu başarısız oldu", "başlatılamadı"))
        self.assertEqual(r["kosular"], [{"zaman": "", "is": "2026-11-10-183000-yayin", "sonuc": "başlatılamadı",
                                         "son_is": ""}])
        fresh = run_js("t.zamanlanmisSatirlari([{ ad: 'yeni', proje: 'kasa', sonraki: '2026-11-12T07:00' }])")[0]
        self.assertEqual((fresh["sonKosu"], fresh["kosular"]), ("henüz koşmadı", []))
        self.assertEqual(run_js("t.zamanlanmisSatirlari(undefined)"), [])

    def test_scheduler_notices_are_blocked_cards(self):
        for text in ("yayin zamanlanmış işi duraklatıldı: Günlük (gunluk). Art arda 2 koşu başarısız oldu.",
                     "yayin zamanlanmış işi eklenemedi: Günlük (gunluk), 11 Kasım koşusu. Neden: x."):
            with self.subTest(text=text):
                self.assertEqual(run_js(f"t.noticeParts({json.dumps(text)}).tone"), "blocked")


@unittest.skipUnless(NODE, "node is not installed")
class DispatcherTextTest(unittest.TestCase):
    """Phase 3: queue state of a waiting job, the running limit, the escalation mark."""

    def test_a_queued_job_shows_its_position_dependencies_engel_and_hold(self):
        t = {"status": "sirada", "queue_position": 2, "held": True, "blocked": "2026-11-10-1-yayin tikandi",
             "depends": ["2026-11-10-1-yayin.md", "2026-11-10-2-pazar.md"]}
        self.assertEqual(run_js(f"t.queueText({json.dumps(t)})"),
                         "sırada 2. · bekletiliyor (Selin bırakınca başlar) · engel: 2026-11-10-1-yayin tikandi")
        t = {"status": "sirada", "queue_position": 1, "held": False, "blocked": "",
             "depends": ["2026-11-10-1-yayin.md"]}
        self.assertEqual(run_js(f"t.queueText({json.dumps(t)})"), "sırada 1. · bekliyor: 2026-11-10-1-yayin")
        self.assertEqual(run_js("t.queueText({status: 'calisiyor', queue_position: null})"), "")

    def test_running_against_the_limit(self):
        self.assertEqual(run_js("t.runningText({running: 2, max_running: 3})"), "2/3 çalışıyor")
        self.assertEqual(run_js("t.runningText({})"), "")

    def test_an_escalated_job_is_marked(self):
        self.assertEqual(run_js("t.escalationText({escalated_from: 'a.md'})"), "↑ yükseltme")
        self.assertEqual(run_js("t.escalationText({escalated_from: ''})"), "")

    def test_an_escalation_notice_is_its_own_card(self):
        text = "yayin işi bir üst katmana taşındı: Giriş (x). Kontrol 2. denemede de geçmedi."
        self.assertEqual(run_js(f"t.noticeParts({json.dumps(text)}).tone"), "info")


@unittest.skipUnless(NODE, "node is not installed")
class WorkflowTextTest(unittest.TestCase):
    """Phase 4: workflow steps grouped under their workflow title, step labels, progress and verdicts."""

    def test_steps_are_grouped_under_their_workflow_in_step_order(self):
        tasks = [{"note": "r.md", "workflow": "akis-1", "step": "2", "step_kind": "plan-inceleme", "created": "b"},
                 {"note": "x.md", "workflow": "", "step": "", "step_kind": ""},
                 {"note": "p2.md", "workflow": "akis-1", "step": "1", "step_kind": "plan", "created": "c"},
                 {"note": "p.md", "workflow": "akis-1", "step": "1", "step_kind": "plan", "created": "a"}]
        workflows = [{"grup": "akis-1", "baslik": "Giriş", "tamam": 1, "toplam": 5, "durum": "calisiyor",
                      "sablon": "gelistir"}]
        groups = run_js(f"t.groupTasks({json.dumps(tasks)}, {json.dumps(workflows)})")
        self.assertEqual([g["kind"] for g in groups], ["workflow", "task"])
        self.assertEqual(groups[0]["title"], "Giriş")
        self.assertEqual(groups[0]["progress"], "1/5 adım")
        self.assertEqual([t["note"] for t in groups[0]["tasks"]], ["p.md", "p2.md", "r.md"])
        self.assertEqual(groups[1]["task"]["note"], "x.md")
        unknown = run_js(f"t.groupTasks({json.dumps(tasks[:1])}, [])")
        self.assertEqual((unknown[0]["title"], unknown[0]["progress"]), ("akis-1", ""))

    def test_progress_step_and_verdict_texts(self):
        self.assertEqual(run_js("t.workflowProgressText({tamam: 2, toplam: 5, durum: 'deniz'})"),
                         "2/5 adım · durdu, Selin'in kararı bekleniyor")
        self.assertEqual(run_js("t.workflowProgressText({tamam: 4, toplam: 5, durum: 'onay-bekliyor'})"),
                         "4/5 adım · onay bekliyor")
        self.assertEqual(run_js("t.workflowProgressText({tamam: 5, toplam: 5, durum: 'bitti'})"), "5/5 adım · bitti")
        self.assertEqual(run_js("t.stepText({step: '2', step_kind: 'plan-inceleme'})"), "adım 2 · plan incelemesi")
        self.assertEqual(run_js("t.stepText({step: '', step_kind: ''})"), "")
        w = {"karar": "duzelt", "tur_no": 2, "yurutucu": "claude (codex yok: kota doldu)", "tur": "kod-inceleme"}
        self.assertEqual(run_js(f"t.verdictText({json.dumps(w)})"),
                         "Karar: DÜZELT · tur 2 · yürütücü: claude (codex yok: kota doldu)")
        self.assertEqual(run_js("t.verdictText({karar: '', tur_no: 1, tur: 'kod'})"), "tur 1")
        self.assertEqual(run_js("t.budgetText({status: 'karar-bekliyor', step_kind: 'onay', budget: 0.01})"), "")

    def test_a_workflow_notice_gets_a_tone(self):
        self.assertEqual(run_js("t.noticeParts('yayin akış adımı bitti (1/5 · plan): x. Rapor:').tone"), "done")
        self.assertEqual(run_js("t.noticeParts('yayin akışı onay bekliyor: x').tone"), "ask")
        self.assertEqual(run_js("t.noticeParts('yayin akışı durdu: x').tone"), "blocked")


@unittest.skipUnless(NODE, "node is not installed")
class PostofficeWarningsTest(unittest.TestCase):
    def test_nothing_to_show_for_a_healthy_post_office(self):
        healthy = {"inbox": 0, "outbox": 0, "rejected": 0, "rejected_outbox": 0, "sessions": {}, "last_error": None,
                   "silent": []}
        self.assertEqual(run_js(f"t.postofficeWarnings({json.dumps(healthy)})"), [])
        self.assertEqual(run_js("t.postofficeWarnings(null)"), [])

    def test_every_problem_gets_one_turkish_line(self):
        po = {"inbox": 0, "outbox": 1, "rejected": 2, "rejected_outbox": 1, "last_error": "inbox x: OSError",
              "sessions": {"ofis-yayin-1110-1-ab": {"queue": 0, "error": "session not found"},
                           "ofis-yayin-1110-2-ab": {"queue": 0, "error": None}},
              "silent": [{"is": "2026-11-10-1-yayin.md", "oturum": "ofis-yayin-1110-1-ab", "proje": "yayin",
                          "seconds": 185}]}
        lines = run_js(f"t.postofficeWarnings({json.dumps(po)})")
        self.assertEqual(len(lines), 5, lines)
        joined = "\n".join(lines)
        for expected in ("Mesaj iletilemedi: inbox x: OSError", "yayin oturumuna cevap iletilemiyor: session not found",
                         "2 proje raporu kabul edilmedi",
                         "1 cevap projeye ulaştırılamadı", "yayin işi 3 dakikadır sessiz"):
            self.assertIn(expected, joined)
        # The owner does not know the word "postane" nor the folder paths (2026-11-12)
        self.assertNotIn("ostane", joined)
        self.assertNotIn("durum/", joined)
        self.assertNotIn("beklenmeyen", joined)

    def test_the_page_never_says_postane(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
        for name in sorted(os.listdir(root)):
            if name.endswith((".js", ".html", ".css")):
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    self.assertNotIn("ostane", f.read(), name)

    def test_a_session_waiting_for_permission_is_named_so(self):
        po = {"rejected": 0, "rejected_outbox": 0, "sessions": {}, "last_error": None,
              "silent": [{"is": "a.md", "oturum": "ofis-yayin-1", "proje": "yayin", "seconds": 300, "izin": True}]}
        [line] = run_js(f"t.postofficeWarnings({json.dumps(po)})")
        self.assertIn("yayin işi 5 dakikadır izin bekliyor", line)

    def test_an_unconfirmed_launch_is_said_as_delivered_but_unconfirmed(self):
        # 2026-11-13: "cevap iletilemiyor" was false; the answer was delivered, only claude's output was not recognised
        error = ("warning: claude resumed the ofis-arge-1113-095913-67e7 session without the expected launch line; "
                 "output: stdout: Resumed abcdef12 ofis-arge")
        po = {"last_error": None, "rejected": 0, "rejected_outbox": 0, "silent": [],
              "sessions": {"ofis-arge-1113-095913-67e7": {"queue": 0, "error": error}}}
        [line] = run_js(f"t.postofficeWarnings({json.dumps(po)})")
        self.assertTrue(line.startswith("arge oturumuna cevap iletildi, ama claude'un çıktısı tanınmadı"), line)
        self.assertIn("Resumed abcdef12 ofis-arge", line)
        self.assertNotIn("iletilemiyor", line)

    def test_a_cleared_session_error_leaves_no_line(self):
        po = {"last_error": None, "rejected": 0, "rejected_outbox": 0, "silent": [],
              "sessions": {"ofis-arge-1113-095913-67e7": {"queue": 0, "error": None}}}
        self.assertEqual(run_js(f"t.postofficeWarnings({json.dumps(po)})"), [])

    def test_the_session_error_repeating_the_last_error_is_shown_once(self):
        po = {"last_error": "session not found", "rejected": 0, "rejected_outbox": 0, "silent": [],
              "sessions": {"ofis-yayin-1": {"queue": 0, "error": "session not found"}}}
        self.assertEqual(len(run_js(f"t.postofficeWarnings({json.dumps(po)})")), 1)


class PageWiringTest(unittest.TestCase):
    """Static checks that need no node: the page uses the helpers and never parses data as HTML."""

    def test_app_uses_the_helpers_and_the_page_has_the_warning_strip(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("from './ofis-text.js'", app)
        self.assertIn("bildirimKarti(", app)  # the notice card (2026-11-13; noticeParts stays for other callers)
        self.assertIn("postofficeWarnings(", app)
        self.assertNotRegex(app, r"\.innerHTML\s*=|insertAdjacentHTML\(|\.outerHTML\s*=")
        self.assertNotRegex((WEB / "ofis-text.js").read_text(encoding="utf-8"), r"innerHTML|document\.")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertTrue(re.search(r'id="po-warn"[^>]*hidden', html))

    def test_the_page_shows_the_queue_the_running_limit_and_escalations(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("queueText(", "canliPill(", "escalationText(", "t.escalated_from"):
            self.assertIn(name, app)
        # one pill (the owner, 2026-11-11): the separate N/M pill is gone; the limit shows in the live pill at the limit
        self.assertNotIn('id="run-text"', (WEB / "index.html").read_text(encoding="utf-8"))

    def test_the_page_knows_kontrolde_budget_and_the_kontrol_evidence(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("kontrolde: N_('kontrolde')", app)
        self.assertIn("budgetText(", app)
        self.assertIn("t.kontrol", app)
        self.assertRegex((WEB / "style.css").read_text(encoding="utf-8"), r"\.badge\.kontrolde")

    def test_the_page_groups_workflows_and_shows_the_approval_evidence(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("boardColumns(", "stepText(", "verdictText(", "d.evidence", "t.workflow"):
            self.assertIn(name, app)

    def test_the_page_lists_the_schedules_in_their_own_tab(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("zamanlanmisSatirlari(state && state.schedules)", app)
        self.assertIn('id="sched-body"', (WEB / "index.html").read_text(encoding="utf-8"))

    def test_the_page_has_the_board_reports_and_quality_views(self):
        # phase 7: three tabs with their own panels; data only through GET endpoints; the demo fakes them
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for tab in ("isler", "raporlar", "kalite"):
            self.assertIn(f'data-tab="{tab}"', html)
            self.assertTrue(re.search(rf'id="overlay-{tab}"[^>]*hidden', html), tab)
        for el in ("board-sirada", "board-devam", "board-biten", "report-list", "quality-body", "model-cards",
                   "mapping-body"):
            self.assertIn(f'id="{el}"', html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("boardColumns(", "budgetBar(", "reportBlocks(", "reportSummaryText(", "qualityCells(",
                     "state.board", "'/api/raporlar'", "'/api/kalite'", "/api/rapor?grup=", "map(modelCardText)",
                     "map(pilotText)", "map(mappingCells)", "renderModelChoice("):
            self.assertIn(name, app)
        demo = (WEB / "demo.js").read_text(encoding="utf-8")
        for path in ("/api/raporlar", "/api/rapor", "/api/kalite", "board", "model_secimi"):
            self.assertIn(path, demo)
        self.assertNotRegex(demo, r"\.innerHTML\s*=|insertAdjacentHTML\(")
        self.assertNotRegex(app, r"method:\s*'(PUT|DELETE)'")

    @unittest.skipUnless(NODE, "node is not installed")
    def test_app_js_parses(self):
        for name in ("app.js", "demo.js", "ofis-text.js"):
            with tempfile.TemporaryDirectory() as tmp:
                proc = subprocess.run([NODE, "--check", str(as_module(name, tmp))], capture_output=True, text=True,
                                      timeout=30)
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")



def board_task(note, status, **extra):
    t = {"note": note, "status": status, "workflow": "", "step": "", "step_kind": "", "created": "", "started": "",
         "finished": ""}
    t.update(extra)
    return t


class PageKeyRetryTest(unittest.TestCase):
    def test_app_posts_through_the_retry_helper(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("from './sayfa-anahtari.js'", app)
        self.assertIn("tekrarla(send, pageNonce", app)
        self.assertIn("let pageNonce", app)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_retries_once_on_invalid_token_and_keeps_the_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = as_module("sayfa-anahtari.js", tmp)
            code = f"""import * as k from {json.dumps(mod.as_uri())};
const mem = {{}}; const storage = {{ setItem: (a, b) => {{ mem[a] = b; }}, removeItem: (a) => {{ delete mem[a]; }} }};
const html = '<meta name="ofis-token" content="NEW">';
async function run(first, second) {{
  const sent = []; const st = [first, second];
  const send = async (t) => {{ sent.push(t); return st.shift(); }};
  const out = await k.tekrarla(send, 'OLD', '/api/chat', {{ text: 'uzun mesaj' }}, {{ fetchHtml: async () => html, storage }});
  return {{ sent, status: out.res.status, token: out.token, draft: mem[k.TASLAK_ANAHTARI] || null }};
}}
const bad = {{ status: 403, data: {{ error: 'invalid token' }} }};
const r = {{
  ok: await run(bad, {{ status: 202, data: {{}} }}),
  still: await run(bad, bad),
  origin: await run({{ status: 403, data: {{ error: 'origin not allowed' }} }}, null),
  other: await run({{ status: 422, data: {{}} }}, null),
}};
process.stdout.write(JSON.stringify(r));"""
            proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        r = json.loads(proc.stdout)
        self.assertEqual(r["ok"]["sent"], ["OLD", "NEW"])
        self.assertEqual(r["ok"]["status"], 202)
        self.assertIsNone(r["ok"]["draft"])
        self.assertEqual(r["still"]["sent"], ["OLD", "NEW"])  # exactly one retry
        self.assertEqual(r["still"]["status"], 403)
        self.assertIn("uzun mesaj", r["still"]["draft"])
        self.assertEqual(r["origin"]["sent"], ["OLD"])
        self.assertEqual(r["other"]["sent"], ["OLD"])


@unittest.skipUnless(NODE, "node is not installed")
class BoardTest(unittest.TestCase):
    """Phase 7: the İşler board — three columns, workflows as one card, budget bars."""

    def columns(self, tasks, workflows=(), limit=20):
        return run_js(f"t.boardColumns({json.dumps(tasks)}, {json.dumps(list(workflows))}, {limit})")

    @staticmethod
    def notes(items):
        return [i["task"]["note"] if i["kind"] == "task" else i["id"] for i in items]

    def test_jobs_go_to_the_column_of_their_status(self):
        tasks = [board_task("q2", "sirada", created="2026-11-10T12:00"), board_task("q1", "sirada", created="2026-11-10T11:00"),
                 board_task("r1", "calisiyor", started="2026-11-10T10:00"), board_task("r2", "kontrolde", started="2026-11-10T13:00"),
                 board_task("k", "karar-bekliyor", started="2026-11-10T09:00"),
                 board_task("d1", "bitti", finished="2026-11-10T08:00"), board_task("d2", "tikandi", finished="2026-11-10T09:30"),
                 board_task("d3", "iptal", finished=""), board_task("d4", "basarisiz", started="2026-11-10T07:00")]
        cols = self.columns(tasks)
        self.assertEqual(self.notes(cols["sirada"]), ["q1", "q2"])  # oldest first: the dispatcher's order
        self.assertEqual(self.notes(cols["devam"]), ["r2", "r1", "k"])  # newest start first
        self.assertEqual(self.notes(cols["biten"]), ["d2", "d1", "d4", "d3"])  # newest end first
        self.assertEqual(cols["bitenGizli"], 0)

    def test_only_the_newest_finished_items_are_shown(self):
        tasks = [board_task(f"d{i}", "bitti", finished=f"2026-11-10T1{i}:00") for i in range(5)]
        cols = self.columns(tasks, limit=2)
        self.assertEqual(self.notes(cols["biten"]), ["d4", "d3"])
        self.assertEqual(cols["bitenGizli"], 3)

    def test_the_jobs_the_server_did_not_send_count_as_hidden(self):
        # state.board_hidden: finished jobs the server already cut (bin/state.py board_tasks)
        tasks = [board_task("d1", "bitti", finished="2026-11-10T10:00")]
        cols = run_js(f"t.boardColumns({json.dumps(tasks)}, [], 20, 7)")
        self.assertEqual((self.notes(cols["biten"]), cols["bitenGizli"]), (["d1"], 7))
        self.assertEqual(run_js(f"t.boardColumns({json.dumps(tasks)}, [], 20, undefined).bitenGizli"), 0)

    def test_a_workflow_is_one_card_in_the_column_of_its_state(self):
        def flow(grup, *statuses):
            return [board_task(f"{grup}-{i}", st, workflow=grup, step=str(i), step_kind="kod",
                               started=f"2026-11-10T1{i}:00", finished=f"2026-11-10T1{i}:30" if st == "bitti" else "")
                    for i, st in enumerate(statuses, 1)]
        tasks = (flow("a", "bitti", "calisiyor", "sirada") + flow("b", "bitti", "sirada") + flow("c", "bitti", "bitti")
                 + flow("d", "bitti", "tikandi", "sirada") + flow("e", "bitti", "sirada"))
        workflows = [{"grup": "a", "baslik": "A", "tamam": 1, "toplam": 3, "durum": "calisiyor"},
                     {"grup": "b", "baslik": "B", "tamam": 1, "toplam": 2, "durum": "calisiyor"},
                     {"grup": "c", "baslik": "C", "tamam": 2, "toplam": 2, "durum": "bitti"},
                     {"grup": "d", "baslik": "D", "tamam": 1, "toplam": 3, "durum": "deniz"},
                     {"grup": "e", "baslik": "E", "tamam": 1, "toplam": 2, "durum": "iptal"}]
        cols = self.columns(tasks, workflows)
        self.assertEqual(sorted(self.notes(cols["devam"])), ["a", "d"])  # running, or stopped for the owner
        self.assertEqual(self.notes(cols["sirada"]), ["b"])
        self.assertEqual(sorted(self.notes(cols["biten"])), ["c", "e"])
        a = next(i for i in cols["devam"] if i["id"] == "a")
        self.assertEqual([t["note"] for t in a["tasks"]], ["a-1", "a-2", "a-3"])
        self.assertEqual(a["progress"], "1/3 adım")

    def test_the_budget_bar_shows_spending_and_calls_against_the_limits(self):
        t = {"status": "calisiyor", "spent": "1.25", "budget": 5, "calls": "50", "max_calls": 40}
        self.assertEqual(run_js(f"t.budgetBar({json.dumps(t)})"),
                         {"money": {"pct": 25, "over": False, "text": "≈$1,25 / ≈$5,00"},
                          "calls": {"pct": 100, "over": True, "text": "50 / 40 çağrı"}})
        small = {"status": "bitti", "spent": "0.0111", "budget": "0.05", "calls": "", "max_calls": None}
        self.assertEqual(run_js(f"t.budgetBar({json.dumps(small)})"),
                         {"money": {"pct": 22, "over": False, "text": "≈$0,0111 / ≈$0,05"}, "calls": None})
        self.assertIsNone(run_js("t.budgetBar({status: 'calisiyor'})"))
        self.assertIsNone(run_js("t.budgetBar({status: 'karar-bekliyor', step_kind: 'onay', budget: 0.01})"))
        self.assertIsNone(run_js("t.budgetBar(null)"))


@unittest.skipUnless(NODE, "node is not installed")
class ReportAndQualityTextTest(unittest.TestCase):
    """Phase 7: the Raporlar list and report text, the Kalite panel's cells."""

    def test_amounts_ratios_and_durations(self):
        self.assertEqual(run_js("[t.usdText(0.0111), t.usdText(4), t.usdText(null), t.usdText('')]"),
                         ["≈$0,0111", "≈$4,00", "—", "—"])
        self.assertEqual(run_js("[t.ratioText(1, 2), t.ratioText(0, 0), t.ratioText(2, 3)]"),
                         ["%50 (1/2)", "—", "%67 (2/3)"])
        self.assertEqual(run_js("[t.minutesText(45), t.minutesText(130), t.minutesText(null)]"),
                         ["45 dk", "2 sa 10 dk", "—"])

    def test_a_report_total_without_codex_says_so(self):
        self.assertEqual(run_js("t.reportCostText({toplam_usd: 0.5523, fiyat_bilinmiyor: true})"),
                         "≈$0,55 (Codex hariç; fiyatı bilinmiyor)")
        self.assertEqual(run_js("t.reportCostText({toplam_usd: 0.0111, fiyat_bilinmiyor: false})"), "≈$0,0111")
        self.assertEqual(run_js("t.reportCostText({toplam_usd: null})"), "—")

    def test_a_report_summary_line(self):
        r = {"is_sayisi": 3, "sonuclar": {"iptal": 1, "bitti": 1, "tikandi": 1}}
        self.assertEqual(run_js(f"t.reportSummaryText({json.dumps(r)})"), "3 iş: 1 bitti, 1 takıldı, 1 iptal")
        self.assertEqual(run_js("t.reportSummaryText({is_sayisi: 0, sonuclar: {}})"), "iş yok")

    def test_quality_cells_keep_small_amounts_and_unknowns(self):
        row = {"proje": "yayin", "katman": "kolay", "model": "haiku", "is_sayisi": 7, "bitti": 6, "ilk_tur_gecen": 6,
               "ilk_tur_olculen": 6, "yeniden_is": 2, "dogrulanmis_is_basina_usd": 0.0126, "ort_usd": 0.0108,
               "ort_sure_dk": None}
        self.assertEqual(run_js(f"t.qualityCells({json.dumps(row)})"),
                         ["yayin", "kolay", "Stajyer (Haiku)", "7", "%86 (6/7)", "%100 (6/6)", "%29 (2/7)", "≈$0,0126",
                          "≈$0,0108", "—", "—"])  # no token count in the row: "—", never "0 token"
        self.assertEqual(len(run_js("t.QUALITY_HEAD")), 11)

    def test_model_selection_lines(self):
        # phase 8: the Kalite view's open model cards, running pilots and effective mapping
        card = {"proje": "yayin", "katman": "kolay", "tur": "model-onerisi", "yon": "yukari", "mevcut_model": "haiku",
                "model": "sonnet", "pilot_is": 3, "basari": None}
        self.assertEqual(run_js(f"t.modelCardText({json.dumps(card)})"),
                         "yayin · kolay: Stajyer (Haiku) → Uzman (Sonnet) — daha deneyimli çalışan için 3 işlik deneme öneriliyor "
                         "(karar bekliyor)")
        ok = {**card, "tur": "model-pilot-sonucu", "basari": True}
        self.assertIn("deneme başarılı; eşleme değişikliği soruluyor", run_js(f"t.modelCardText({json.dumps(ok)})"))
        failed = {**ok, "basari": False}
        self.assertIn("deneme kanıtlamadı; eşleme değişmeyecek", run_js(f"t.modelCardText({json.dumps(failed)})"))
        pilot = {"proje": "yayin", "katman": "kolay", "mevcut_model": "haiku", "model": "sonnet", "eklenen": 2,
                 "biten": 1, "toplam": 3}
        self.assertEqual(run_js(f"t.pilotText({json.dumps(pilot)})"),
                         "yayin · kolay: Stajyer (Haiku) → Uzman (Sonnet) denemesi — 2/3 iş eklendi, 1 bitti")
        self.assertEqual(run_js("t.mappingCells({proje: 'yayin', katman: 'kolay', model: 'sonnet', effort: '', "
                                "kaynak: 'proje'})"),
                         ["yayin", "kolay", "Uzman (Sonnet)", "—", "projeye özel (onaylı pilot)"])
        self.assertEqual(run_js("t.MAPPING_HEAD.length"), 5)
        self.assertEqual(run_js("[t.pilotText(null), t.modelCardText(null)]"), ["", ""])

    def test_model_notices_ask_for_a_decision(self):
        for first in ("yayin model önerisi: kolay işler için sonraki 3 iş haiku yerine sonnet ile denensin mi?",
                      "yayin model pilotu bitti: kolay işler sonnet ile (3 iş). Pilot başarılı.",
                      # the office vocabulary since 2026-11-11; the older wording above still reads the same
                      "yayin kadro önerisi: kolay işler için sonraki 3 iş Stajyer (Haiku) yerine Uzman (Sonnet) "
                      "ile denensin mi?",
                      "yayin kadro denemesi bitti: kolay işler Uzman (Sonnet) ile (3 iş). Pilot başarılı."):
            with self.subTest(first=first):
                self.assertEqual(run_js(f"t.noticeParts({json.dumps(first)}).tone"), "ask")

    def test_report_text_becomes_safe_blocks(self):
        text = ("---\ngrup: x\n---\n\n# yayin — Giriş (x)\n\n> Sunucu yazar.\n> İkinci satır.\n\n## İşler\n\n"
                "| İş | Sonuç | Not |\n|---|---|---|\n| [[2026-11-10-1-yayin]] | bitti | a \\| b |\n"
                "| <b>x</b> | [[Kararlar/k\\|karar]] | **kalın** |\n\n## Açık kalanlar\n\n- [[2026-11-10-2-yayin]] takıldı\n"
                "- ikinci\n\nDüz paragraf\nsürüyor.\n")
        blocks = run_js(f"t.reportBlocks({json.dumps(text)})")
        self.assertEqual([b["type"] for b in blocks], ["h", "quote", "h", "table", "h", "list", "p"])
        self.assertEqual((blocks[0]["level"], blocks[0]["text"]), (1, "yayin — Giriş (x)"))
        self.assertEqual(blocks[1]["text"], "Sunucu yazar.\nİkinci satır.")
        table = blocks[3]
        self.assertEqual(table["head"], ["İş", "Sonuç", "Not"])
        plain = [[{k: c[k] for k in ("text", "note")} for c in row] for row in table["rows"]]
        self.assertEqual(plain[0], [{"text": "2026-11-10-1-yayin", "note": "2026-11-10-1-yayin.md"},
                                    {"text": "bitti", "note": ""}, {"text": "a | b", "note": ""}])
        # markup stays literal text; a link with an alias shows the alias; only a job note link is clickable
        self.assertEqual(plain[1], [{"text": "<b>x</b>", "note": ""}, {"text": "karar", "note": ""},
                                    {"text": "kalın", "note": ""}])
        self.assertEqual(blocks[5]["items"], ["2026-11-10-2-yayin takıldı", "ikinci"])
        self.assertEqual(blocks[6]["text"], "Düz paragraf\nsürüyor.")
        # 2026-11-13: the same text with its [[links]] kept, for the page's Obsidian links (bold still dropped)
        self.assertEqual(table["rows"][0][0]["linkli"], "[[2026-11-10-1-yayin]]")
        self.assertEqual(table["rows"][1][2]["linkli"], "kalın")
        self.assertEqual(blocks[5]["linkli"], ["[[2026-11-10-2-yayin]] takıldı", "ikinci"])
        self.assertEqual(blocks[1]["linkli"], "Sunucu yazar.\nİkinci satır.")


@unittest.skipUnless(NODE, "node is not installed")
class AnswerResultTest(unittest.TestCase):
    def test_a_refused_second_answer_marks_the_card_answered(self):
        data = {"error": "Bu karara cevabın zaten iletildi; CEO notu güncelleyecek.", "kod": "cevap-iletildi"}
        self.assertEqual(run_js(f"t.answerResult(409, {json.dumps(data)})"),
                         {"ok": False, "sent": True, "text": data["error"]})

    def test_delivered_queued_and_unreachable(self):
        self.assertEqual(run_js("t.answerResult(202, {status: 'delivered'})"),
                         {"ok": True, "sent": True, "text": "Cevap CEO'ya iletildi."})
        self.assertEqual(run_js("t.answerResult(202, {status: 'queued'})"),
                         {"ok": True, "sent": True, "text": "Cevap sıraya alındı; CEO boşalınca iletilecek."})
        out = run_js("t.answerResult(409, {error: 'CEO session unreachable: x'})")
        self.assertEqual((out["ok"], out["sent"]), (False, False))
        self.assertTrue(out["text"].startswith("CEO'ya ulaşılamadı."))
        self.assertEqual(run_js("t.answerResult(0, {})"), {"ok": False, "sent": False, "text": "Sunucu kapalı."})



# --- living office, step 2: the behaviour engine (web/ofis-davranis.js) ---

DAV_PRELUDE = r"""
const NOW = Date.parse('2026-11-11T07:00:00Z');   // 10:00 in Istanbul
const LUNCH = Date.parse('2026-11-11T09:30:00Z'); // 12:30 in Istanbul (04:30 in New York, 09:30 UTC)
// lunch is a seeded part of the hour per actor (ogleYemekte): the first minute of 12:00-13:00 at which `id` eats
const yemekAni = (id, sahne = { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul' }) => {
  for (let m = 0; m < 60; m++) { const t = Date.parse('2026-11-11T09:00:30Z') + m * 60000; if (d.ogleYemekte(id, t, sahne)) return t; }
  return null; };
// everyone at lunch at once (the demo's lunch scene): the canteen's worst case
const HEPSI = { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul', ogle_hepsi: true };
const iso = (ms) => new Date(ms + 3 * 3600000).toISOString().slice(0, 19); // naive Istanbul wall clock
const st = (x = {}) => ({ projects: [{ name: 'yayin' }], sahne: { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul' },
  sessions: [], tasks: [], board: [], ceo: { state: 'dormant' }, modeller: [], decisions: [], ...x });
const ses = (name, status, x = {}) => ({ name, project: 'yayin', status, kind: 'bg', job_status: '', model: '',
  tier: '', note: '', step_kind: '', alt_ajanlar: [], ...x });
const task = (note, status, x = {}) => ({ note, project: 'yayin', status, session: '', title: 'Giriş', model: 'opus',
  tier: 'kod', started: iso(NOW - 600000), created: iso(NOW - 700000), finished: '', step_kind: '',
  escalated_from: '', queue_position: null, held: false, blocked: '', inceleme_yurutucu: '', ...x });
const run = (s, now = NOW, prev = null, o = {}) => d.niyetler(s, now, prev, o);
const one = (list, id) => list.find((a) => a.id === id) || null;
const working = (x = {}, sx = {}) => st({ sessions: [ses('ofis-w-1', 'busy', { job_status: 'calisiyor', model: 'opus',
  note: 'a.md', ...sx })], tasks: [task('a.md', 'calisiyor', { session: 'ofis-w-1', ...x })] });
"""


def run_dav(expr, tz="UTC"):
    """Evaluates `expr` with web/ofis-davranis.js imported as `d` (and the DAV_PRELUDE fixtures), in process zone tz."""
    with tempfile.TemporaryDirectory() as tmp:
        module = as_module("ofis-davranis.js", tmp)
        code = (f"import * as d from {json.dumps(module.as_uri())};\n{DAV_PRELUDE}\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, TZ=tz))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class BehaviourRulesTest(unittest.TestCase):
    """One test per row of the plan's rule table ("gerçek durum önce gelir")."""

    def actor(self, state_js, actor_id="is:a", now="NOW"):
        return run_dav(f"one(run({state_js}, {now}), {json.dumps(actor_id)})")

    def test_a_working_agent_types_at_its_desk(self):
        a = self.actor("working()")
        self.assertEqual((a["yer"], a["poz"], a["simge"]), ("ekip-yayin-masa-1", "yaziyor", None))
        self.assertEqual(a["etiket"], "yayin · Kıdemli (Opus)")
        self.assertEqual(a["durum_metni"], "çalışıyor · Giriş")
        self.assertEqual(a["tiklama"], {"note": "a.md"})

    def test_a_busy_agent_never_goes_to_lunch_or_home(self):
        kota = "[{model: 'opus', durum: 'kota', donus: '2026-11-11T16:30+03:00'}]"
        for now in ("NOW", "LUNCH"):
            for state in ("working()", f"{{...working(), modeller: {kota}}}",
                          f"{{...st({{sessions: [ses('ofis-w-1', 'busy', {{model: 'opus'}})]}}), modeller: {kota}}}"):
                with self.subTest(now=now, state=state):
                    out = run_dav(f"run({state}, {now}).filter((a) => a.tur === 'ajan' && !a.denetci && !a.kadro)")
                    self.assertEqual(len(out), 1)
                    self.assertTrue(out[0]["yer"].startswith("ekip-yayin-"), out[0])
                    self.assertEqual(out[0]["poz"], "yaziyor")

    def test_kontrolde_sits_at_the_desk_with_the_test_lamp(self):
        a = self.actor("st({sessions: [ses('ofis-w-1', 'idle', {note: 'a.md'})], "
                       "tasks: [task('a.md', 'kontrolde', {session: 'ofis-w-1'})]})")
        self.assertEqual((a["yer"], a["simge"]), ("ekip-yayin-masa-1", "test"))

    def test_a_decision_waits_at_the_ceo_door(self):
        a = self.actor("st({sessions: [ses('ofis-w-1', 'idle', {note: 'a.md'})], "
                       "tasks: [task('a.md', 'karar-bekliyor', {session: 'ofis-w-1'})]})", now="LUNCH")
        self.assertEqual((a["yer"], a["poz"], a["simge"]), ("ceo-kuyruk-0", "bekliyor", "?"))
        self.assertEqual(a["masa"], "ekip-yayin-masa-1")  # it keeps its desk

    def test_a_permission_prompt_raises_a_hand_at_the_desk(self):
        a = self.actor("working({}, {status: 'waiting'})", now="LUNCH")
        self.assertEqual((a["yer"], a["poz"], a["simge"]), ("ekip-yayin-masa-1", "el-kaldirmis", "!"))

    def test_a_running_review_step_types_at_a_desk_of_the_qa_or_analist_room(self):
        # plan "Sonraki iş (9)": a kod review / an inceleme job at a Kıdemli Tester desk, a plan review at an analyst's
        for x, desk in (("{step_kind: 'kod-inceleme'}", "qa-masa-0"), ("{tier: 'inceleme'}", "qa-masa-0"),
                        ("{step_kind: 'plan-inceleme'}", "analist-masa-0")):
            with self.subTest(x=x):
                a = self.actor(f"working({x}, {x})")
                self.assertEqual((a["yer"], a["masa"], a["poz"], a["durum_metni"]), (desk, desk, "yaziyor", "inceliyor · Giriş"))

    def test_queued_jobs_wait_in_the_lobby_and_held_ones_say_so(self):
        out = run_dav("run(st({tasks: [task('q1.md', 'sirada', {queue_position: 1}), "
                      "task('q2.md', 'sirada', {queue_position: 2, held: true})]}))")
        self.assertRegex(one_of(out, "is:q1")["yer"], r"^lobi-koltuk-[0-5]$")  # a seat from its own seed
        self.assertNotEqual(one_of(out, "is:q1")["yer"], one_of(out, "is:q2")["yer"])
        self.assertEqual(one_of(out, "is:q1")["poz"], "lobide")
        self.assertEqual(one_of(out, "is:q2")["durum_metni"], "sırada 2. · bekletiliyor")

    def test_more_queued_jobs_than_seats_are_summarised(self):
        out = run_dav("run(st({tasks: Array.from({length: 8}, (_, i) => "
                      "task(`q${i}.md`, 'sirada', {queue_position: i + 1}))}))")
        self.assertEqual(sum(1 for a in out if a["poz"] == "lobide"), 6)
        self.assertEqual(one_of(out, "ozet:lobi")["etiket"], "+2")
        self.assertIsNone(one_of(out, "ozet:lobi")["tiklama"])

    def test_a_finished_job_celebrates_then_walks_to_the_lift(self):
        base = "st({tasks: [task('a.md', 'bitti', {session: 'ofis-w-1', finished: iso(NOW - %d)})]})"
        a = self.actor(base % 10000)
        self.assertEqual((a["yer"], a["poz"], a["simge"]), ("ekip-yayin-masa-1", "kutluyor", "✓"))
        # the last opus worker walks back to the lounge as the resident Kıdemli (kadro) instead of the lift
        self.assertIsNone(self.actor(base % 45000))
        self.assertEqual(self.actor(base % 45000, actor_id="kadro:opus")["yer"], "ortak-alan-opus")
        self.assertIsNone(self.actor(base % 90000))
        # another opus job still runs: the leaver takes the lift
        other = ("st({sessions: [ses('ofis-w-2', 'busy', {note: 'b.md'})], tasks: [task('a.md', 'bitti', "
                 "{session: 'ofis-w-1', finished: iso(NOW - 45000)}), task('b.md', 'calisiyor', {session: 'ofis-w-2'})]})")
        a = self.actor(other)
        self.assertEqual((a["yer"], a.get("cikis")), ("asansor", True))
        self.assertIsNone(self.actor(other, actor_id="kadro:opus"))

    def test_a_finished_job_whose_session_stays_goes_idle_after_the_celebration(self):
        a = self.actor("st({sessions: [ses('ofis-w-1', 'idle')], "
                       "tasks: [task('a.md', 'bitti', {session: 'ofis-w-1', finished: iso(NOW - 45000)})]})")
        self.assertNotIn("cikis", a)
        self.assertNotEqual(a["yer"], "ekip-yayin-masa-1")

    def test_a_stuck_job_hangs_its_head_at_the_desk(self):
        a = self.actor("st({sessions: [ses('ofis-w-1', 'idle')], "
                       "tasks: [task('a.md', 'tikandi', {session: 'ofis-w-1', finished: iso(NOW - 3600000)})]})",
                       now="LUNCH")
        self.assertEqual((a["yer"], a["poz"], a["simge"]), ("ekip-yayin-masa-1", "basi-onde", "kirmizi"))

    def test_an_escalated_job_carries_the_file_to_the_new_actor_then_leaves(self):
        state = ("st({tasks: [task('b.md', 'sirada', {escalated_from: 'a.md', model: 'fable', queue_position: 1}), "
                 "task('a.md', 'tikandi', {session: 'ofis-w-1', finished: iso(NOW - %d)})]})")
        out = run_dav(f"run({state % 10000})")
        old, new = one_of(out, "is:a"), one_of(out, "is:b")
        self.assertEqual((old["hedef_id"], old["dosya"], old["yer"]), ("is:b", True, new["yer"]))
        self.assertEqual(new["unvan"], "Genel Müdür")
        # its job is over and no other opus works: it goes back to the lounge as the kadro (not through the lift)
        self.assertIsNone(one_of(run_dav(f"run({state % 50000})"), "is:a"))
        self.assertEqual(one_of(run_dav(f"run({state % 50000})"), "kadro:opus")["yer"], "ortak-alan-opus")
        self.assertIsNone(one_of(run_dav(f"run({state % 90000})"), "is:a"))

    def test_an_idle_agent_without_a_job_takes_a_break_and_eats_at_lunch(self):
        state = "st({sessions: [ses('ofis-w-1', 'idle', {model: 'sonnet'})]})"
        a = self.actor(state, actor_id="oturum:ofis-w-1")
        self.assertIn(a["poz"], ("cay", "cay-al", "yuruyor", "pingpong", "bilardo", "bekliyor", "dart"))  # idle life
        self.assertFalse(a["yer"].startswith("ekip-"))
        self.assertIsNone(a["masa"])  # an idle agent takes no free desk (review of steps 2+3, minor 2)
        a = self.actor(state, actor_id="oturum:ofis-w-1", now="LUNCH")
        self.assertEqual(a["poz"], "yemek")
        self.assertRegex(a["yer"], r"^yemekhane-sandalye-\d+$")  # a stable chair from its own seed (not the CEO's 7)
        self.assertNotEqual(a["yer"], "yemekhane-sandalye-7")

    def test_lunch_is_read_in_the_office_zone_whatever_the_process_zone(self):
        for tz in ("UTC", "America/New_York", "Asia/Tokyo"):
            with self.subTest(tz=tz):
                self.assertEqual(run_dav("[d.ogleMi(LUNCH, st().sahne), d.ogleMi(NOW, st().sahne), "
                                         "d.ogleMi(Date.parse('2026-11-11T10:00:00Z'), st().sahne)]", tz=tz),
                                 [True, False, False])
                a = run_dav("one(run(st({sessions: [ses('ofis-w-1', 'idle')]}), LUNCH), 'oturum:ofis-w-1').poz", tz=tz)
                self.assertEqual(a, "yemek")
                self.assertEqual(run_dav("d.zamanMs('2026-11-11T12:30:00', 'Europe/Istanbul') === LUNCH", tz=tz), True)

    def test_a_model_out_of_quota_sends_its_idle_agent_home(self):
        a = self.actor("{...working({}, {status: 'idle'}), modeller: [{model: 'opus', durum: 'kota', "
                       "donus: '2026-11-11T16:30+03:00'}]}", now="LUNCH")
        self.assertEqual((a["yer"], a["poz"], a["durum_metni"]),
                         ("ekip-yayin-masa-1", "evde", "Evde · 16:30'da döner"))
        # only a concrete kota: another status keeps it at the desk
        a = self.actor("{...working({}, {status: 'idle'}), modeller: [{model: 'opus', durum: 'hata'}]}")
        self.assertEqual(a["poz"], "bekliyor")

    def test_the_ceo_types_drinks_tea_or_sleeps(self):
        for state, yer, poz in (("busy", "ceo-masa", "yaziyor"), ("absent", "ceo-masa", "uyuyor")):
            with self.subTest(state=state):
                c = run_dav(f"one(run(st({{ceo: {{state: '{state}'}}}})), 'ceo')")
                self.assertEqual((c["yer"], c["poz"]), (yer, poz))
        # idle / dormant with nothing open: its seeded free time (ceoPlani); in hafif its desk — by day in the office
        # hours no bed outside the lunch window (owner decision 2026-11-16)
        for state, yer, poz in (("idle", "ceo-masa", "bekliyor"), ("dormant", "ceo-masa", "bekliyor")):
            with self.subTest(state=state, hafif=True):
                c = run_dav(f"one(run(st({{ceo: {{state: '{state}'}}}}), NOW, null, {{hafif: true}}), 'ceo')")
                self.assertEqual((c["yer"], c["poz"]), (yer, poz))
        c = run_dav("one(run(st({ceo: {state: 'busy'}}), LUNCH), 'ceo')")
        self.assertEqual((c["yer"], c["poz"]), ("ceo-masa", "yaziyor"))
        # Step 1 (owner decision 2026-11-12): the reply is written, the turn has not ended yet
        c = run_dav("one(run(st({ceo: {state: 'busy', tur_kapaniyor: true}})), 'ceo')")
        self.assertEqual((c["yer"], c["poz"], c["durum_metni"]), ("ceo-masa", "bekliyor", "Cevap verdi · tur kapanıyor"))

    def test_codex_works_at_the_auditor_desk_or_is_home_on_quota(self):
        c = run_dav("one(run(st({tasks: [task('r.md', 'incelemede', {inceleme_yurutucu: 'codex', "
                    "step_kind: 'kod-inceleme'})], modeller: [{model: 'codex', durum: 'calisiyor'}]})), 'denetci:codex')")
        self.assertEqual((c["yer"], c["poz"], c["tiklama"]), ("denetci-masa", "yaziyor", {"note": "r.md"}))
        c = run_dav("one(run(st({modeller: [{model: 'codex', durum: 'kota', donus: '2026-11-12T09:00+03:00'}]})), "
                    "'denetci:codex')")
        self.assertEqual((c["poz"], c["durum_metni"]), ("evde", "Evde · 12 Kas 09:00'da döner"))
        self.assertEqual(c["unvan"], "Dış denetçi")


def one_of(actors, actor_id):
    return next((a for a in actors if a["id"] == actor_id), None)


@unittest.skipUnless(NODE, "node is not installed")
class BehaviourHelpersTest(unittest.TestCase):
    def test_subagents_stand_next_to_the_parent_capped_at_four(self):
        out = run_dav("run(working({}, {alt_ajanlar: Array.from({length: 6}, (_, i) => ({id: 'h' + i, "
                      "model: i === 0 ? 'sonnet' : '', gorev: 'ara', son_yazma: '2026-11-11T09:59:00+03:00', "
                      "bitti: false}))}))")
        helpers = [a for a in out if a["tur"] == "alt-ajan"]
        self.assertEqual([a["yer"] for a in helpers], [f"ekip-yayin-masa-1-yardimci-{i}" for i in range(4)])
        self.assertEqual([a["unvan"] for a in helpers], ["Uzman", "Stajyer", "Stajyer", "Stajyer"])
        self.assertEqual(helpers[1]["etiket"], "Yardımcı · Stajyer")
        self.assertEqual(one_of(out, "is:a/alt:+")["etiket"], "+2")
        self.assertTrue(all(a["ebeveyn"] == "is:a" for a in helpers))

    def test_a_finished_subagent_gets_a_check_then_leaves(self):
        expr = ("one(run(working({}, {alt_ajanlar: [{id: 'h', model: 'haiku', gorev: 'x', son_yazma: '%s', "
                "bitti: true}]})), 'is:a/alt:h')")
        a = run_dav(expr % "2026-11-11T09:59:55+03:00")
        self.assertEqual((a["poz"], a["simge"]), ("kutluyor", "✓"))
        # then it is gone beside its parent: helpers never walk out by the lift
        self.assertIsNone(run_dav(expr % "2026-11-11T09:59:20+03:00"))
        self.assertIsNone(run_dav(expr % "2026-11-11T09:50:00+03:00"))

    def test_the_ceo_subagents_stand_in_the_ceo_room(self):
        out = run_dav("run(st({ceo: {state: 'busy', alt_ajanlar: [{id: 'c1', model: 'opus', gorev: 'oku', "
                      "son_yazma: '2026-11-11T09:59:00+03:00', bitti: false}]}}))")
        a = one_of(out, "ceo/alt:c1")
        self.assertEqual((a["yer"], a["unvan"]), ("ceo-yardimci-0", "Kıdemli"))

    def test_the_tea_server_is_decorative_absent_in_hafif_and_goes_to_a_fresh_finish(self):
        out = run_dav("run(st())")
        c = one_of(out, "sus:cayci")
        self.assertEqual((c["tur"], c["etiket"], c["tiklama"]), ("sus", "Çaycı", None))
        self.assertIsNone(one_of(run_dav("run(st(), NOW, null, {hafif: true})"), "sus:cayci"))
        out = run_dav("run(st({tasks: [task('a.md', 'bitti', {session: 'x', finished: iso(NOW - 5000)})]}))")
        self.assertEqual(one_of(out, "sus:cayci")["yer"], "ekip-yayin-masa-1-yan")

    def test_the_result_is_deterministic(self):
        self.assertEqual(run_dav("JSON.stringify(run(working())) === JSON.stringify(run(working()))"), True)
        self.assertNotIn("Math.random(", (WEB / "ofis-davranis.js").read_text(encoding="utf-8"))

    def test_desks_and_ids_are_stable_across_ticks(self):
        expr = """(() => {
          const a = ses('ofis-w-b', 'busy', {note: 'b.md', job_status: 'calisiyor'});
          const t1 = st({sessions: [a], tasks: [task('b.md', 'calisiyor', {session: 'ofis-w-b'})]});
          const first = run(t1);
          const t2 = st({sessions: [ses('ofis-w-a', 'busy', {note: 'a.md', job_status: 'calisiyor'}), a],
            tasks: [task('a.md', 'calisiyor', {session: 'ofis-w-a'}), task('b.md', 'calisiyor', {session: 'ofis-w-b'})]});
          const kept = run(t2, NOW + 1000, first);
          const fresh = run(t2, NOW + 1000);
          return [one(first, 'is:b').masa, one(kept, 'is:b').masa, one(kept, 'is:a').masa, one(fresh, 'is:b').masa];
        })()"""
        self.assertEqual(run_dav(expr), ["ekip-yayin-masa-1", "ekip-yayin-masa-1", "ekip-yayin-masa-2",
                                         "ekip-yayin-masa-2"])

    def test_desk_count_follows_the_running_limit_and_the_rest_is_summarised(self):
        expr = ("run(st({sessions: Array.from({length: %d}, (_, i) => ses('ofis-w-' + i, 'busy', {model: 'sonnet'}))}), "
                "NOW, null, {max_running_per_project: %d})")
        out = run_dav(expr % (5, 1))
        at_desk = [a for a in out if a["tur"] == "ajan" and not a.get("denetci") and not a.get("kadro")]
        # 1 + 2 desks, then (review of steps 2+3, minor 1) a working Uzman falls back to the free manager's desk
        self.assertEqual(len(at_desk), 4)
        self.assertEqual(one_of(out, "ozet:ekip-yayin")["etiket"], "+1")
        self.assertEqual(run_dav(f"d.ofisPlani(['yayin'], {{max_running_per_project: 2}}).masa_sayisi"), 4)

    def test_a_manager_or_planning_job_takes_the_managers_desk(self):
        a = run_dav("one(run(working({model: 'fable', tier: 'planlama'}, {model: 'fable', tier: 'planlama'})), 'is:a')")
        # plan "Sonraki iş (9)": planning work is written at the planning desk of the Yazılım Müdürü's office
        self.assertEqual((a["masa"], a["unvan"]), ("yazilim-plan-masa", "Genel Müdür"))
        # two planning jobs at once: the second takes its team's manager's desk; none of them leaves the kadro behind
        out = run_dav("""(() => { const s = st({sessions: [ses('s1', 'busy', {note: 'a.md'}), ses('s2', 'busy', {note: 'b.md'})],
          tasks: [task('a.md', 'calisiyor', {session: 's1', model: 'fable', tier: 'planlama'}),
                  task('b.md', 'calisiyor', {session: 's2', model: 'opus', tier: 'planlama'})]});
          const r = run(s); return [one(r, 'is:a').masa, one(r, 'is:b').masa, !!one(r, 'kadro:fable')]; })()""")
        self.assertEqual(out, ["yazilim-plan-masa", "ekip-yayin-mudur", False])
        # an idle Müdür (no fable work) sits at its office desk; on quota its "Evde" sign is there
        out = run_dav("""[one(run(st({modeller: [{model: 'fable', durum: 'hazir'}], sahne: { ...st().sahne, mola: 'dinlenme' }}), NOW), 'kadro:fable'),
          one(run(st({modeller: [{model: 'fable', durum: 'kota'}]}), NOW), 'kadro:fable')].map((a) => [a.yer, a.poz])""")
        self.assertEqual(out, [["mudur-odasi-masa", "bekliyor"], ["mudur-odasi-masa", "evde"]])

    def test_unvan_map_and_texts_are_plain(self):
        self.assertEqual(run_dav("[d.UNVAN.haiku.unvan, d.UNVAN.sonnet.unvan, d.UNVAN.opus.unvan, d.UNVAN.fable.unvan, "
                                 "d.UNVAN.codex.unvan, d.UNVAN.ceo.unvan]"),
                         ["Stajyer", "Uzman", "Kıdemli", "Genel Müdür", "Dış denetçi", "CEO"])
        self.assertEqual(run_dav("d.modelAilesi('claude-opus-4-1')"), "opus")
        a = run_dav("one(run({...working({title: '<b>x</b>'}), projects: [{name: '<i>p</i>'}], "
                    "sessions: [ses('ofis-w-1', 'busy', {project: '<i>p</i>', note: 'a.md'})], "
                    "tasks: [task('a.md', 'calisiyor', {project: '<i>p</i>', session: 'ofis-w-1', title: '<b>x</b>'})]}), 'is:a')")
        self.assertEqual((a["etiket"], a["durum_metni"]), ("<i>p</i> · Kıdemli (Opus)", "çalışıyor · <b>x</b>"))
        self.assertEqual(run_dav("['2026-11-11T12:00+03:00', '2026-11-11T13:00+03:00', '2026-11-11T16:40+03:00']"
                                 ".map((x) => d.donusMetni(x, NOW, 'Europe/Istanbul'))"),
                         ["12:00'de döner", "13:00'te döner", "16:40'ta döner"])


@unittest.skipUnless(NODE, "node is not installed")
class FloorPlanTest(unittest.TestCase):
    def test_every_room_and_place_exists(self):
        plan = run_dav("d.ofisPlani(['yayin', 'blog'])")
        self.assertEqual([r["id"] for r in plan["odalar"]],
                         ["toplanti", "ceo", "denetci", "mudur", "uzmanlar", "oyun", "dinlenme", "cay-ocagi", "ortak-alan",
                          "yemekhane", "muhasebe", "idari", "ik", "revir", "psikolog", "masaj", "sunucu", "arge", "sosyal",
                          "sosyal-studyo", "spor", "dus", "wc", "konferans", "mudurluk-yazilim", "mudurluk-it",
                          "mudurluk-qa", "mudurluk-analist", "qa", "analist", "ekip-yayin", "ekip-blog", "bos-ekip-1",
                          "bos-ekip-2", "bos-ekip-3", "bos-ekip-4", "bos-ekip-5", "lobi", "sigara"])
        self.assertNotIn("pano", plan["dugumler"])  # the 3D wall board is gone (owner decision 2026-11-12)
        for place in ("ceo-masa", "ceo-kuyruk-0", "denetci-masa", "ekip-blog-mudur", "ekip-blog-masa-3",
                      "cay-ocagi-tezgah", "yemekhane-sandalye-0", "lobi-koltuk-5", "asansor"):
            self.assertIn(place, plan["dugumler"])
        self.assertNotIn("ekip-blog-masa-4", plan["dugumler"])

    def test_paths_follow_the_edges_and_reach_every_place(self):
        for n in (0, 1, 4, 7):
            with self.subTest(projects=n):
                out = run_dav(f"""(() => {{
                  const plan = d.ofisPlani(Array.from({{length: {n}}}, (_, i) => 'p' + i));
                  const edges = new Set(plan.kenarlar.flatMap(([a, b]) => [a + '|' + b, b + '|' + a]));
                  const bad = [];
                  for (const id of Object.keys(plan.dugumler)) {{
                    const p = plan.yol('asansor', id);
                    if (!p.length || p[0].id !== 'asansor' || p[p.length - 1].id !== id) bad.push(id);
                    for (let i = 1; i < p.length; i++) if (!edges.has(p[i - 1].id + '|' + p[i].id)) bad.push(id);
                  }}
                  return bad;
                }})()""")
                self.assertEqual(out, [])

    def test_shortest_path_and_unknown_nodes(self):
        path = run_dav("d.yol(d.ofisPlani(['yayin']), 'ekip-yayin-masa-1', 'ceo-masa').map((n) => n.id)")
        self.assertEqual(path[0], "ekip-yayin-masa-1")
        self.assertEqual(path[-1], "ceo-masa")
        self.assertIn("ceo-kapi", path)  # through the CEO's door (then around its desk, not through it)
        self.assertNotIn("koridor-0-sol", path)
        self.assertEqual(run_dav("d.yol(d.ofisPlani(['yayin']), 'asansor', 'yok')"), [])
        self.assertEqual(run_dav("d.yol(d.ofisPlani(['yayin']), 'asansor', 'asansor').length"), 1)

    def test_the_module_parses_and_never_touches_the_dom(self):
        text = (WEB / "ofis-davranis.js").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\bdocument\.|\bwindow\.|innerHTML|from 'three'")
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([NODE, "--check", str(as_module("ofis-davranis.js", tmp))], capture_output=True,
                                  text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)



@unittest.skipUnless(NODE, "node is not installed")
class BehaviourReviewFixesTest(unittest.TestCase):
    """Independent review of step 2 (KARAR DÜZELT): one test per finding."""

    def test_1_a_running_codex_review_types_even_while_a_quota_flag_is_live(self):
        c = run_dav("one(run(st({tasks: [task('r.md', 'incelemede', {inceleme_yurutucu: 'codex', "
                    "step_kind: 'kod-inceleme'})], modeller: [{model: 'codex', durum: 'kota', donus: null}]})), 'denetci:codex')")
        self.assertEqual((c["yer"], c["poz"]), ("denetci-masa", "yaziyor"))

    STUCK = """const stuck = ['2026-11-11-080000-yayin', '2026-11-11-083000-yayin', '2026-11-11-090000-yayin']
      .map((n, i) => task(n, 'tikandi', {session: 'ofis-old-' + i, started: iso(NOW - 7000000 + i),
        finished: iso(NOW - 1800000)}));
    const olds = stuck.map((t) => ses(t.session, 'idle', {model: 'opus'}));
    const busy = ses('ofis-new', 'busy', {note: '2026-11-11-095500-yayin', job_status: 'calisiyor', model: 'opus'});
    const busyTask = task('2026-11-11-095500-yayin', 'calisiyor', {session: 'ofis-new'});
    const O = {max_running_per_project: 1};"""

    def test_2_a_working_agent_gets_a_desk_before_stuck_ones(self):
        out = run_dav(f"""(() => {{ {self.STUCK}
          const fresh = run(st({{sessions: [...olds, busy], tasks: [busyTask, ...stuck]}}), NOW, null, O);
          const before = run(st({{sessions: olds, tasks: stuck}}), NOW - 5000, null, O);
          const kept = run(st({{sessions: [...olds, busy], tasks: [busyTask, ...stuck]}}), NOW, before, O);
          return [fresh, before, kept].map((r) => [one(r, 'is:2026-11-11-095500-yayin'), one(r, 'ozet:ekip-yayin')]);
        }})()""")
        (fresh_busy, fresh_ozet), (_, before_ozet), (kept_busy, kept_ozet) = out
        self.assertIsNone(before_ozet)  # the three stuck ones held all three desks
        for busy, ozet in ((fresh_busy, fresh_ozet), (kept_busy, kept_ozet)):
            self.assertIsNotNone(busy)
            self.assertEqual(busy["poz"], "yaziyor")
            self.assertTrue(busy["yer"].startswith("ekip-yayin-masa-"), busy)
            self.assertEqual(ozet["etiket"], "+1")
            self.assertIn("takıldı", ozet["durum_metni"])

    def test_3_a_busy_session_with_a_decision_stays_at_its_desk(self):
        a = run_dav("one(run(st({sessions: [ses('s', 'busy', {note: 'a.md'})], "
                    "tasks: [task('a.md', 'karar-bekliyor', {session: 's'})]})), 'is:a')")
        self.assertEqual((a["yer"], a["poz"], a["simge"]), ("ekip-yayin-masa-1", "yaziyor", "?"))

    def test_4_now_is_required(self):
        for arg in ("", ", undefined", ", 'abc'", ", NaN"):
            with self.subTest(arg=arg):
                self.assertEqual(run_dav(f"(() => {{ try {{ d.niyetler(st(){arg}); return 'ok'; }} "
                                         f"catch (e) {{ return e instanceof TypeError; }} }})()"), True)
        self.assertEqual(run_dav("d.nowMs(new Date(NOW)) === NOW && d.nowMs('2026-11-11T07:00:00Z') === NOW"), True)

    def test_4_offsets_and_fractions_are_read(self):
        t = 1794403800000  # 2026-11-11T13:30:00Z
        self.assertEqual(run_dav("[Date.parse('2026-11-11T13:30:00Z'), d.zamanMs('2026-11-11T16:30+0300'), "
                                 "d.zamanMs('2026-11-11T16:30:00.123456+03:00'), d.zamanMs('2026-11-11T10:30-03:00')]"),
                         [t, t, t + 123, t])

    def test_4_naive_stamps_are_read_with_the_servers_offset(self):
        # the server runs in New York (UTC-5); its naive stamp of 10 s ago must not be read as Istanbul time
        ny = "new Date(NOW - 10000 - 5 * 3600000).toISOString().slice(0, 19)"
        state = (f"st({{sahne: {{ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul', sunucu_utc_ofset_dk: -300}}, "
                 f"tasks: [task('a.md', 'bitti', {{session: 'x', finished: {ny}}})]}})")
        a = run_dav(f"one(run({state}), 'is:a')", tz="Asia/Tokyo")
        self.assertEqual((a["poz"], a["simge"]), ("kutluyor", "✓"))
        self.assertEqual(run_dav("d.zamanMs('2026-11-11T02:00:00', 'Europe/Istanbul', -300) === NOW"), True)

    def test_4_a_finish_in_the_future_counts_as_just_now(self):
        a = run_dav("one(run(st({tasks: [task('a.md', 'bitti', {session: 'x', finished: iso(NOW + 3600000)})]})), 'is:a')")
        self.assertEqual(a["poz"], "kutluyor")

    @staticmethod
    def shared_spots(actors):
        spots = {}
        for a in actors:
            if a["yer"] and not a.get("cikis"):
                spots.setdefault(a["yer"], []).append(a["id"])
        return {k: v for k, v in spots.items() if len(v) > 1}

    def test_5_nobody_shares_a_spot_and_full_rooms_get_a_summary(self):
        three = "projects: [{name: 'yayin'}, {name: 'b'}, {name: 'c'}]"
        lunch = run_dav(f"run(st({{{three}, sahne: HEPSI, ceo: {{state: 'idle'}}, sessions: Array.from({{length: 8}}, (_, i) => "
                        "ses('s' + i, 'idle', {project: ['yayin', 'b', 'c'][i % 3]}))}), LUNCH)")
        # the same office at a real lunch: everyone eats in a seeded part of the hour, still never two on one spot
        for m in range(0, 60, 5):
            real = run_dav(f"run(st({{{three}, ceo: {{state: 'idle'}}, sessions: Array.from({{length: 8}}, (_, i) => "
                           f"ses('s' + i, 'idle', {{project: ['yayin', 'b', 'c'][i % 3]}}))}}), "
                           f"Date.parse('2026-11-11T09:00:30Z') + {m} * 60000)")
            # (a corridor walk may cross another; a place is never shared)
            self.assertEqual({k: v for k, v in self.shared_spots(real).items()
                              if not re.match(r"^(koridor|kanat|alt)-", k)}, {}, m)
        self.assertEqual(self.shared_spots(lunch), {})
        self.assertEqual(one_of(lunch, "ceo")["yer"], "yemekhane-sandalye-7")
        # the canteen has a chair for everyone (owner decision 2026-11-12): no "+N" at lunch
        self.assertIsNone(one_of(lunch, "ozet:yemek"))
        self.assertEqual(sum(1 for a in lunch if a["poz"] == "yemek" and a["id"].startswith("oturum:")), 8)
        # (plan "Sonraki iş (9)": seven Claude kod reviews fill the QA odası's four desks: "+3")
        for status, extra, key, n in (("calisiyor", "{step_kind: 'kod-inceleme'}", "ozet:qa", "+3"),
                                      ("karar-bekliyor", "{}", "ozet:kuyruk", "+1")):
            with self.subTest(status=status):
                out = run_dav(f"run(st({{{three}, sessions: Array.from({{length: 7}}, (_, i) => ses('s' + i, "
                              f"'{'busy' if status == 'calisiyor' else 'idle'}', {{project: ['yayin', 'b', 'c'][i % 3], "
                              f"note: 'r' + i + '.md'}})), tasks: Array.from({{length: 7}}, (_, i) => task('r' + i + '.md', "
                              f"'{status}', {{project: ['yayin', 'b', 'c'][i % 3], session: 's' + i, ...{extra}}}))}}))")
                self.assertEqual(self.shared_spots(out), {})
                self.assertEqual(one_of(out, key)["etiket"], n)
        tea = run_dav(f"run(st({{{three}, sessions: Array.from({{length: 10}}, (_, i) => "
                      "ses('s' + i, 'idle', {project: ['yayin', 'b', 'c'][i % 3]}))}), NOW, null, {hafif: true})")
        self.assertEqual(self.shared_spots(tea), {})
        self.assertEqual(one_of(tea, "ozet:cay")["etiket"], "+1")

    HELPER = "{id: 'h', model: 'haiku', gorev: 'ara', son_yazma: '2026-11-11T12:29:00+03:00', bitti: false}"

    def test_6_an_idle_parent_with_an_open_helper_keeps_working(self):
        for sess in (f"ses('s', 'idle', {{note: 'a.md', alt_ajanlar: [{self.HELPER}]}})",):
            out = run_dav(f"run(st({{sessions: [{sess}], tasks: [task('a.md', 'calisiyor', {{session: 's'}})]}}), LUNCH)")
            self.assertEqual((one_of(out, "is:a")["yer"], one_of(out, "is:a")["poz"]),
                             ("ekip-yayin-masa-1", "yaziyor"))
            self.assertEqual(one_of(out, "is:a/alt:h")["yer"], "ekip-yayin-masa-1-yardimci-0")
        out = run_dav(f"run(st({{sessions: [ses('s', 'idle', {{alt_ajanlar: [{self.HELPER}]}})]}}), LUNCH)")
        self.assertEqual((one_of(out, "oturum:s")["yer"], one_of(out, "oturum:s")["poz"]),
                         ("ekip-yayin-masa-1", "yaziyor"))
        # an open helper also outweighs a quota on the parent's model
        out = run_dav(f"run({{...st({{sessions: [ses('s', 'idle', {{model: 'opus', alt_ajanlar: [{self.HELPER}]}})]}}), "
                      "modeller: [{model: 'opus', durum: 'kota'}]}, LUNCH)")
        self.assertEqual(one_of(out, "oturum:s")["poz"], "yaziyor")
        c = run_dav(f"one(run(st({{ceo: {{state: 'idle', alt_ajanlar: [{self.HELPER}]}}}}), LUNCH), 'ceo')")
        self.assertEqual((c["yer"], c["poz"]), ("ceo-masa", "yaziyor"))

    def test_6_helpers_of_hidden_or_deskless_parents_are_counted(self):
        two = f"[{self.HELPER}, {{...{self.HELPER}, id: 'h2'}}]"
        out = run_dav(f"run(st({{sessions: Array.from({{length: 5}}, (_, i) => ses('s' + i, 'busy', "
                      f"{{model: 'opus', alt_ajanlar: {two}}}))}}), NOW, null, {{max_running_per_project: 1}})")
        self.assertEqual(one_of(out, "ozet:ekip-yayin")["etiket"], "+1")
        self.assertIn("2 yardımcı", one_of(out, "ozet:ekip-yayin")["durum_metni"])
        out = run_dav(f"run(st({{sessions: [ses('s', 'busy', {{note: 'a.md', alt_ajanlar: {two}}})], "
                      "tasks: [task('a.md', 'calisiyor', {session: 's', step_kind: 'kod-inceleme'})]}))")
        # a reviewer has a desk in the QA odası: its helpers stand beside it
        self.assertEqual([one_of(out, f"is:a/alt:{x}")["yer"] for x in ("h", "h2")],
                         ["qa-masa-0-yardimci-0", "qa-masa-0-yardimci-1"])
        self.assertIsNone(one_of(out, "is:a/alt:+"))



# --- living office, step 3: the scene's pure helpers (web/ofis-sahne.js) and the page wiring ---

def run_scene(expr, prelude="", tz=None):
    """Evaluates `expr` with web/ofis-sahne.js as `h`, web/ofis-davranis.js as `d` and web/demo.js as `demo` imported
    under their own names (a temp folder with package.json type=module, so their relative imports resolve)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name in ("ofis-sahne.js", "ofis-davranis.js", "demo.js", "ofis-text.js"):
            shutil.copyfile(WEB / name, Path(tmp) / name)
        webkopya.i18n_ekle(tmp)
        uri = lambda n: json.dumps((Path(tmp) / n).as_uri())  # noqa: E731
        code = (f"import * as h from {uri('ofis-sahne.js')};\nimport * as d from {uri('ofis-davranis.js')};\n"
                f"import * as demo from {uri('demo.js')};\n{DAV_PRELUDE}\n{prelude}\n"
                f"const out = await ({expr});\nprocess.stdout.write(JSON.stringify(out), () => process.exit(0));")
        env = dict(os.environ, TZ=tz) if tz else None
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp, env=env)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


# The scripted demo (web/demo.js) through the engine: P = its plan, stateAt(t) = the state at loop second t (NOW + t s),
# sahne(t, prev, opts, niyetOpts) = the actors.
DEMO_JS = r"""
const PROJ = ['ornek-uygulama', 'atolye', 'blog', 'kasa'].map((name) => ({ name }));
const P = d.ofisPlani(PROJ, { max_running_per_project: 1,
  denetciler: d.denetciListesi(demo.demoDurumu(0, NOW).modeller) });
const stateAt = (t, o = {}) => { const now = NOW + t * 1000; const x = demo.demoDurumu(t, now, o);
  return { now, x, st: { projects: PROJ, tasks: x.tasks, board: x.tasks, decisions: x.decisions, modeller: x.modeller,
    denetim: x.denetim, sahne: x.sahne, ceo: { state: 'idle' }, sessions: demo.demoOturumlari(x.live, x.tasks, now) } }; };
const sahne = (t, prev = null, o = {}, opt = {}) => { const s = stateAt(t, o);
  return d.niyetler(s.st, s.now, prev, { plan: P, max_running_per_project: 1, ...opt }); };
const bas = (id) => demo.DEMO_SAHNELERI.find((x) => x.id === id).bas;
"""


@unittest.skipUnless(NODE, "node is not installed")
class SceneHelpersTest(unittest.TestCase):
    def test_facing_at_each_kind_of_place(self):
        out = run_scene("""(() => { const p = d.ofisPlani(['yayin']); const f = (id) => h.yuzAcisi(p, id);
          return { masa: f('ekip-yayin-masa-1'), mudur: f('ekip-yayin-mudur'), ust: f('toplanti-sandalye-0'),
            alt: f('toplanti-sandalye-4'), yemek: f('yemekhane-sandalye-5'), asansor: f('asansor'),
            koridor: f('koridor-0-sol'), yok: f('yok'), yan: f('ekip-yayin-masa-1-yan'),
            kuyruk: f('ceo-kuyruk-0'), oturur: [h.oturmaYeri(p, 'ekip-yayin-masa-1'), h.oturmaYeri(p, 'lobi-koltuk-0'),
              h.oturmaYeri(p, 'ceo-kuyruk-0'), h.oturmaYeri(p, 'asansor')] }; })()""")
        self.assertEqual((out["masa"], out["mudur"], out["ust"]), (0, 0, 0))
        self.assertAlmostEqual(out["alt"], 3.14159, places=4)  # the far row of the meeting table faces back
        self.assertAlmostEqual(out["yemek"], 3.14159, places=4)
        self.assertAlmostEqual(out["asansor"], 3.14159, places=4)  # into the lift in the lobby's back wall
        self.assertIsNone(out["koridor"])
        self.assertIsNone(out["yok"])
        self.assertAlmostEqual(out["yan"], -1.5708, places=3)  # beside a desk, facing it (-x)
        self.assertLess(out["kuyruk"], 0)  # the CEO door queue looks left, towards the door
        self.assertEqual(out["oturur"], [True, True, False, False])

    def test_shared_spots_get_a_small_deterministic_ring(self):
        out = run_scene("""(() => { const a = [{id: 'b', yer: 'x'}, {id: 'a', yer: 'x'}, {id: 'c', yer: 'x'},
          {id: 'z', yer: 'y'}, {id: 'n', yer: null}];
          const one = [...h.ortakOfsetler(a)]; const two = [...h.ortakOfsetler([...a].reverse())];
          return { one, two }; })()""")
        one = dict(out["one"])
        self.assertEqual(one["z"], [0, 0])  # alone: on the node
        self.assertNotIn("n", one)
        self.assertEqual(dict(out["two"]), one)  # order of the list does not matter
        ring = [tuple(one[k]) for k in "abc"]
        self.assertEqual(len(set(ring)), 3)
        for dx, dz in ring:
            self.assertAlmostEqual((dx * dx + dz * dz) ** 0.5, 0.75, places=2)  # step 5: a little more room

    def test_label_text_and_classes(self):
        out = run_scene("""(() => { const p = d.ofisPlani(['yayin']);
          const acts = run(working(), NOW, null, {plan: p});
          const me = one(acts, 'is:a');
          return {
            desk: h.etiketBilgisi(me), walk: h.etiketBilgisi(me, {yuruyor: true}),
            away: h.etiketBilgisi({...me, yer: 'ceo-kuyruk-0', poz: 'bekliyor', simge: '?'}),
            helper: h.etiketBilgisi({id: 'x/alt:1', tur: 'alt-ajan', etiket: 'Yardımcı · Stajyer (Haiku)',
              durum_metni: 'Dosyaları tarıyor', poz: 'yaziyor', simge: null}),
            sus: h.etiketBilgisi(one(acts, 'sus:cayci')),
            ozet: h.etiketBilgisi({id: 'ozet:lobi', tur: 'ozet', etiket: '+3', durum_metni: '3 iş daha sırada'}),
            classes: ['yaziyor', 'el-kaldirmis', 'basi-onde', 'kutluyor', 'evde', 'lobide', 'cay']
              .map((poz) => h.durumSinifi({tur: 'ajan', poz, simge: null})),
            long: h.etiketBilgisi({...me, durum_metni: 'x'.repeat(200)}).durum.length,
          }; })()""")
        self.assertEqual(out["desk"]["ad"], "Kıdemli")  # role only (the model is in the card)  # its own team area shows the project on the floor
        self.assertEqual(out["desk"]["sinif"], "is-working is-gorevde")  # working: the green pill
        self.assertTrue(out["desk"]["durum"].startswith("çalışıyor"))
        self.assertEqual(out["walk"]["durum"], "")
        self.assertEqual((out["away"]["ad"], out["away"]["sinif"]), ("yayin · Kıdemli", "is-waiting"))
        self.assertEqual((out["helper"]["ad"], out["helper"]["durum"], out["helper"]["kucuk"]),
                         ("Yardımcı Stajyer", "", True))
        self.assertEqual((out["sus"]["sinif"], out["sus"]["kucuk"]), ("is-sus", True))
        self.assertEqual((out["ozet"]["ad"], out["ozet"]["sinif"]), ("+3", "is-ozet"))
        self.assertEqual(out["classes"], ["is-working is-gorevde", "is-waiting", "is-stuck", "is-done", "is-sleeping",
                                          "is-queued", "is-idle"])
        self.assertLessEqual(out["long"], 32)

    def test_labels_go_to_the_most_important_actors_first(self):
        out = run_scene("""[...h.etiketSecimi([
          {id: 's', tur: 'sus'}, {id: 'h', tur: 'alt-ajan'}, {id: 'o', tur: 'ozet'}, {id: 'i', tur: 'ajan', poz: 'cay'},
          {id: 'w', tur: 'ajan', poz: 'yaziyor'}, {id: 'q', tur: 'ajan', poz: 'bekliyor', simge: '?'}, {id: 'c', tur: 'ceo'},
        ], 4)]""")
        self.assertEqual(out, ["c", "q", "w", "i"])

    def test_a_walk_follows_the_graph_from_the_current_spot_to_the_offset_spot(self):
        out = run_scene("""(() => { const p = d.ofisPlani(['yayin']); const n = p.dugumler;
          const to = {x: n['ekip-yayin-masa-1'].x + 0.3, z: n['ekip-yayin-masa-1'].z};
          const w = h.yolHazirla(h.yuruyusYolu(p, {x: n.asansor.x, z: n.asansor.z}, 'asansor', 'ekip-yayin-masa-1', to));
          const o = {}; const at = (s) => { const r = h.yolKonumu(w, s, o); return [r.x, r.z, r.bitti, r.sonraki]; };
          const graph = d.yol(p, 'asansor', 'ekip-yayin-masa-1').map((x) => x.id);
          const lost = h.yolHazirla(h.yuruyusYolu(p, {x: 1, z: 1}, 'yok', 'asansor', {x: 2, z: 2}));
          return { pts: w.pts, ids: w.ids, toplam: w.toplam, graph, start: at(0), mid: at(w.toplam / 2),
            end: at(w.toplam + 5), lost: lost.pts, turn: h.aciFarki(3, -3) }; })()""")
        self.assertEqual(out["pts"][0], [out["start"][0], out["start"][1]])
        self.assertEqual(out["end"][:3], [out["pts"][-1][0], out["pts"][-1][1], True])
        self.assertEqual(out["ids"][1:], out["graph"][1:])  # every corner is a node of the shortest path
        self.assertEqual(out["end"][3], "ekip-yayin-masa-1")
        self.assertFalse(out["mid"][2])
        self.assertIn(out["mid"][3], out["graph"])
        self.assertGreater(out["toplam"], 5)
        self.assertEqual(out["lost"], [[1, 1], [2, 2]])  # an unknown start node: a straight line
        self.assertAlmostEqual(out["turn"], 0.2832, places=3)  # the short way round

    def test_overlapping_labels_move_up_and_free_ones_stay(self):
        out = run_scene("""(() => { const it = [
            {x: 100, y: 200, w: 120, h: 20}, {x: 130, y: 198, w: 120, h: 20}, {x: 400, y: 199, w: 80, h: 20},
            {x: 110, y: 190, w: 100, h: 20, gizli: true}, {x: 120, y: 205, w: 120, h: 20}];
          const nc = h.etiketleriYerlestir(it, it.length, [], []); return {dy: it.map((x) => x.dy), nc}; })()""")
        dy = out["dy"]
        self.assertEqual(out["nc"], 0)
        self.assertEqual(dy[4], 0)  # same priority: the lowest one stays
        self.assertEqual(dy[2], 0)  # far away: stays
        self.assertEqual(dy[3], 0)  # hidden: ignored
        tops = sorted([(200 + dy[0]), (198 + dy[1]), (205 + dy[4])])
        self.assertTrue(all(b - a >= 20 for a, b in zip(tops, tops[1:])), tops)
        self.assertTrue(all(x >= -48 for x in dy))

    def test_a_crowd_of_labels_stacks_by_priority_and_folds_the_rest_into_a_plus_n(self):
        # Owner decision 2026-11-14 (screenshot 19:03): "Genel Müdür", "sozluk · Uzman Güvenlik", "Antigravity", "GLM",
        # "DeepSeek" piled up in the meeting room. Six labels on one spot: green / amber first, idle last; two stack,
        # the idle rest folds into one "+N" on the first label; a working or waiting one is never folded.
        out = run_scene("""(() => {
          const A = [{tur: 'kadro', gorevde: true, etiket: 'Genel Müdür'},
            {tur: 'ajan', poz: 'bekliyor', etiket: 'idle agent'}, {tur: 'denetci', denetci: true, etiket: 'GLM'},
            {tur: 'ajan', simge: '?', etiket: 'question'}, {tur: 'denetci', denetci: true, etiket: 'DeepSeek'},
            {tur: 'sus', etiket: 'Çaycı'}];
          const it = A.map((a, i) => ({x: 300 + i, y: 400, w: 110, h: 18, ...h.etiketOnceligi(a)}));
          const cips = [];
          const nc = h.etiketleriYerlestir(it, it.length, [], cips);
          const shown = it.map((x, i) => i).filter((i) => it[i].toplu < 0);
          const boxes = shown.map((i) => [it[i].x, it[i].y + it[i].dy, it[i].w, it[i].h]);
          let overlap = false;
          for (let i = 0; i < boxes.length; i++) for (let j = 0; j < i; j++) {
            const [ax, ay, aw, ah] = boxes[i], [bx, by, bw, bh] = boxes[j];
            if (Math.abs(ax - bx) * 2 < aw + bw && ay - ah < by && ay > by - bh) overlap = true; }
          // a crowd of working labels: all kept (stacked), none folded
          const W = [0, 1, 2, 3, 4].map((i) => ({x: 300, y: 400, w: 110, h: 18, ...h.etiketOnceligi({tur: 'ajan', poz: 'yaziyor'})}));
          const ncW = h.etiketleriYerlestir(W, W.length, [], []);
          // the reused chip array is reset on the next frame
          const again = h.etiketleriYerlestir([{...it[0]}], 1, [], cips);
          return {nc, cips: cips.slice(0, nc).map((c) => ({sahip: c.sahip, uyeler: c.uyeler.slice()})),
            toplu: it.map((x) => x.toplu), dy: it.map((x) => x.dy), overlap, shown,
            ncW, wFolded: W.filter((x) => x.toplu >= 0).length, wDy: W.map((x) => x.dy), again,
            pr: [h.etiketOnceligi(A[3]), h.etiketOnceligi(A[0]), h.etiketOnceligi({tur: 'ceo'}), h.etiketOnceligi(A[5]),
              h.etiketOnceligi(A[5], {uzerinde: true})]}; })()""")
        self.assertFalse(out["overlap"], out)
        # the question (amber) stays at its robot, the working Genel Müdür stacks just above it
        self.assertEqual(out["dy"][3], 0)
        self.assertEqual(out["dy"][0], -20)
        self.assertEqual(out["toplu"][3], -1)
        self.assertEqual(out["toplu"][0], -1)
        # one more fits within the limit (the idle agent, next in priority); the rest fold into one chip on the first
        self.assertEqual(out["toplu"][1], -1)
        self.assertEqual(out["dy"][1], -40)
        self.assertEqual(out["nc"], 1)
        self.assertEqual(out["cips"][0]["sahip"], 3)
        self.assertEqual(sorted(out["cips"][0]["uyeler"]), [2, 4, 5])
        self.assertEqual(out["cips"][0]["uyeler"][-1], 5)  # decoration last: placing order is priority order
        # never fold a working / waiting label, however many
        self.assertEqual(out["ncW"], 0)
        self.assertEqual(out["wFolded"], 0)
        self.assertEqual(sorted(out["wDy"]), [-80, -60, -40, -20, 0])
        self.assertEqual(out["again"], 0)
        q, g, ceo, cay, hover = out["pr"]
        self.assertTrue(q["kalici"] and g["kalici"] and ceo["kalici"] and hover["kalici"])
        self.assertFalse(cay["kalici"])
        self.assertTrue(q["on"] < g["on"] < ceo["on"] < cay["on"])
        self.assertLess(hover["on"], q["on"])

    def test_smoke_every_demo_scene_gives_a_scene_worth_looking_at(self):
        # demo.js demoDurumu -> niyetler at every second of the loop: every actor stands on a known place reachable from
        # the lift; over the loop the demo shows every pose, symbol, kind of actor and room
        out = run_scene(f"""(() => {{ {DEMO_JS} const seen = {{poz: new Set(), simge: new Set(), tur: new Set(), rooms: new Set()}};
          const bad = []; let n = 0, plain = true, prev = null;
          for (let t = 0; t < demo.DEMO_SURE; t++) {{
            const acts = sahne(t, prev); prev = acts; n = Math.max(n, acts.length);
            for (const a of acts) {{
              if (!P.dugumler[a.yer] || !d.yol(P, 'asansor', a.yer).length) bad.push(t + ':' + a.id);
              seen.poz.add(a.poz); if (a.simge) seen.simge.add(a.simge); seen.tur.add(a.tur);
              if (P.dugumler[a.yer]) seen.rooms.add(P.dugumler[a.yer].oda);
              const l = h.etiketBilgisi(a); plain = plain && typeof l.ad === 'string' && typeof l.durum === 'string';
            }}
          }}
          return {{ bad, plain, n, poz: [...seen.poz].sort(), simge: [...seen.simge].sort(), tur: [...seen.tur].sort(),
            rooms: [...seen.rooms].filter(Boolean).sort() }}; }})()""")
        self.assertEqual(out["bad"], [])
        self.assertTrue(out["plain"])
        for poz in ("yaziyor", "lobide", "el-kaldirmis", "bekliyor", "kutluyor", "yemek", "evde", "cay", "yuruyor"):
            self.assertIn(poz, out["poz"])
        self.assertTrue({"ajan", "alt-ajan", "ceo", "sus"} <= set(out["tur"]), out["tur"])
        self.assertTrue({"?", "!", "test", "✓"} <= set(out["simge"]), out["simge"])
        self.assertTrue({"lobi", "ceo", "uzmanlar", "denetci", "cay-ocagi", "yemekhane"} <= set(out["rooms"]), out["rooms"])
        self.assertNotIn("toplanti", out["rooms"])  # the meeting room stays empty (no fake meetings)
        # (+ the wing's office staff, the 13 of Sosyal medya, one resident per project; + the six people of the three
        # shift teams off shift, hidden at the Otel — 2026-11-14; + the kitchen's two shift teams of three, which replaced
        # the one Yemekhane sorumlusu: five more — 2026-11-14)
        self.assertLessEqual(out["n"], 59)

    def test_the_helpers_never_touch_the_dom_and_parse(self):
        text = (WEB / "ofis-sahne.js").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\bdocument\.|\bwindow\.|innerHTML|from 'three'|Math\.random\(")
        for name in ("ofis-sahne.js", "scene.js"):
            with tempfile.TemporaryDirectory() as tmp:
                proc = subprocess.run([NODE, "--check", str(as_module(name, tmp))], capture_output=True, text=True,
                                      timeout=30)
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr}")

    def test_queued_jobs_show_their_title_from_the_model_or_the_tier(self):
        out = run_scene("""(() => { const r = run(st({tasks: [
            task('q1.md', 'sirada', {model: 'haiku', tier: 'kolay'}), task('q2.md', 'sirada', {model: '', tier: 'genel'}),
            task('q3.md', 'sirada', {model: '', tier: 'planlama'}), task('q4.md', 'sirada', {model: '', tier: ''})]}));
          return ['q1', 'q2', 'q3', 'q4'].map((n) => { const a = one(r, 'is:' + n); return [a.etiket, a.unvan, a.model]; }); })()""")
        self.assertEqual(out, [["yayin · Stajyer (Haiku)", "Stajyer", "haiku"],
                               ["yayin · Uzman (Sonnet)", "Uzman", "sonnet"],
                               ["yayin · Genel Müdür (Fable)", "Genel Müdür", "fable"],
                               ["yayin · Ajan", "Ajan", ""]])  # neither known: the honest fallback
        self.assertEqual(run_scene("[d.isModeli({tier: 'inceleme'}), d.isModeli({model: 'claude-opus-5', tier: 'kolay'}), "
                                   "d.isModeli({tier: 'kod'}, {model: 'claude-haiku-4-5'}), d.isModeli({})]"),
                         ["opus", "claude-opus-5", "claude-haiku-4-5", ""])

    def test_at_the_default_zoom_only_important_labels_show_their_state(self):
        out = run_scene("""(() => { const b = (a, o) => h.etiketBilgisi({id: 'x', etiket: 'p · Uzman (Sonnet)',
            durum_metni: 'boşta · çay molası', tur: 'ajan', ...a}, {yakin: false, ...o}).durum;
          return { idle: b({poz: 'cay'}), hovered: b({poz: 'cay'}, {uzerinde: true}), near: b({poz: 'cay'}, {yakin: true}),
            working: b({poz: 'yaziyor'}), ask: b({poz: 'bekliyor', simge: '?'}), perm: b({poz: 'el-kaldirmis', simge: '!'}),
            stuck: b({poz: 'basi-onde', simge: 'kirmizi'}), ceo: b({tur: 'ceo', poz: 'cay'}), queued: b({poz: 'lobide'}),
            ozet: b({tur: 'ozet', etiket: '+2'}),
            full: ['ceo', 'ajan'].map((tur) => h.tamEtiket({tur, poz: 'lobide'})) }; })()""")
        self.assertEqual((out["idle"], out["queued"]), ("", ""))
        self.assertEqual(out["hovered"], "boşta · çay molası")
        self.assertEqual(out["near"], "boşta · çay molası")
        for key in ("working", "ask", "perm", "stuck", "ceo", "ozet"):
            self.assertNotEqual(out[key], "", key)
        self.assertEqual(out["full"], [True, False])

    # --- independent review of steps 2+3 (minors) ---

    def test_r1_a_working_agent_takes_the_free_managers_desk_before_becoming_plus_n(self):
        out = run_scene("""(() => { const ses4 = Array.from({length: 4}, (_, i) => ses('w' + i, 'busy', {note: 'w' + i + '.md'}));
          const t4 = Array.from({length: 4}, (_, i) => task('w' + i + '.md', 'calisiyor', {session: 'w' + i, model: 'opus'}));
          const r = run(st({sessions: ses4, tasks: t4}), NOW, null, {max_running_per_project: 1});
          return { yer: r.filter((a) => a.id.startsWith('is:w')).map((a) => a.yer).sort(),
            ozet: one(r, 'ozet:ekip-yayin') }; })()""")
        self.assertEqual(out["yer"], ["ekip-yayin-masa-1", "ekip-yayin-masa-2", "ekip-yayin-masa-3",
                                      "ekip-yayin-mudur"])
        self.assertIsNone(out["ozet"])

    def test_r2_an_agent_at_home_keeps_a_desk_for_its_sign_before_tea_breakers(self):
        out = run_scene("""(() => { const s = [0, 1, 2].map((i) => ses('i' + i, 'idle', {model: 'claude-sonnet'}));
          s.push(ses('k', 'idle', {model: 'claude-opus'}));
          const r = run(st({sessions: s, modeller: [{model: 'opus', durum: 'kota', donus: '2026-11-11T16:30+03:00'}]}),
            NOW, null, {max_running_per_project: 1, hafif: true});
          const k = one(r, 'oturum:k');
          return { k: k && [k.poz, k.yer], ozet: one(r, 'ozet:ekip-yayin'),
            tea: ['i0', 'i1', 'i2'].map((n) => one(r, 'oturum:' + n).masa) }; })()""")
        self.assertEqual(out["k"][0], "evde")
        self.assertTrue(out["k"][1].startswith("ekip-yayin-masa-"), out)
        self.assertIsNone(out["ozet"])
        self.assertEqual(out["tea"], [None, None, None])  # idle ones need no desk

    def test_r3_a_summary_never_pushes_a_body_off_its_spot(self):
        out = run_scene("""(() => { const hh = (id) => ({id, model: 'haiku', gorev: 'x', bitti: false,
            son_yazma: '2026-11-11T09:59:00+03:00'});
          const r = run(st({sessions: [ses('r', 'idle', {note: 'r.md', tier: 'inceleme', step_kind: 'kod-inceleme',
            alt_ajanlar: [hh('a'), hh('b')]})], tasks: [task('r.md', 'calisiyor', {session: 'r', tier: 'inceleme',
            step_kind: 'kod-inceleme'})]}));
          const off = h.ortakOfsetler(r);
          return { parent: off.get('is:r') || null, desk: one(r, 'is:r').yer,
            helpers: ['a', 'b'].map((x) => [one(r, 'is:r/alt:' + x).yer, off.get('is:r/alt:' + x) || null]) }; })()""")
        # (the reviewer now works at a QA odası desk: its helpers stand on their own spots beside it)
        self.assertEqual(out["desk"], "qa-masa-0")
        self.assertIn(out["parent"], (None, [0, 0]))
        self.assertEqual(out["helpers"], [["qa-masa-0-yardimci-0", [0, 0]], ["qa-masa-0-yardimci-1", [0, 0]]])


class SceneWiringTest(unittest.TestCase):
    """Static checks of the living office wiring (no node, no browser)."""

    def test_the_page_draws_the_engine_actors_and_never_parses_data_as_html(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("from './ofis-davranis.js'", "niyetler(state, Date.now(), prevActors", "ofisPlani(",
                     "office.setActors(actors, plan)", "max_running_per_project", "hafif: LIGHT", "onActor:",
                     "kind: 'task', note: x.note", "selectRoom(CEO)"):
            self.assertIn(name, app)
        self.assertNotIn("labelFor(", app)
        self.assertNotIn("office.update(", app)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertNotRegex(scene, r"innerHTML|insertAdjacentHTML|outerHTML")
        for name in ("from './ofis-sahne.js'", "setActors(actors, plan)", "textContent", "document.hidden",
                     "etiketleriYerlestir(", "etiketOnceligi(v.a", "placeChips(", "this.light", "uzerinde: this.hoverId === v.id", "yakin: this.yakin"):
            self.assertIn(name, scene)
        self.assertNotIn("Math.random(", scene)  # deterministic phases: the same state looks the same

    def test_only_a_real_drag_or_zoom_stops_the_resize_refit(self):
        # Review 2026-11-11: OrbitControls fires 'start' on every press, so a click or tap used to stop the re-fit.
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertNotRegex(scene, r"addEventListener\('start',[^\n]*userMoved")
        self.assertRegex(scene, r">= 5\) this\.userMoved = true")
        # the wheel / pinch / two-finger scroll is the scene's own (tekerlek) and counts as moving the camera
        for fn in ("imleceZoom(z1, cx, cy) {", "tekerlek(e) {"):
            body = scene[scene.index(fn):]
            body = body[:body.index("\n  }\n")]
            self.assertIn("this.userMoved = true;", body)

    def test_the_server_sends_the_desks_per_team_and_the_demo_feeds_the_scene(self):
        self.assertIn('"max_running_per_project"', (WEB.parent / "bin" / "state.py").read_text(encoding="utf-8"))
        demo = (WEB / "demo.js").read_text(encoding="utf-8")
        for name in ("sahne:", "modeller:", "alt_ajanlar", "job_status", "step_kind: 'kod-inceleme'", "'waiting'",
                     "export function demoDurumu(", "export const DEMO_SAHNELERI"):
            self.assertIn(name, demo)


# --- living office, step 4: the model board (ofis-sahne.js modelSatirlari, the wall board and the side panel) ---

MODEL_PRELUDE = r"""
const IST = { saat_dilimi: 'Europe/Istanbul' };
const rows = (list, now = NOW, sahne = IST) => h.modelSatirlari(list, now, sahne);
const by = (list, now, sahne) => Object.fromEntries(rows(list, now, sahne).map((r) => [r.model, r]));
"""


@unittest.skipUnless(NODE, "node is not installed")
class ModelBoardTest(unittest.TestCase):
    def board(self, expr, tz=None):
        return run_scene(expr, MODEL_PRELUDE, tz=tz)

    def test_each_status_gets_its_plain_turkish_line_and_tone(self):
        out = self.board("""by([
          {model: 'haiku', unvan: 'Stajyer', calisan: 1, durum: 'calisiyor', donus: null, son_hata: null},
          {model: 'sonnet', calisan: 0, durum: 'hata', son_hata: 'API Error: 529 Overloaded'},
          {model: 'opus', calisan: 0, durum: 'kota', donus: '2026-11-11T16:30+03:00', son_hata: 'limit'},
          {model: 'fable', calisan: 0, durum: 'hazir'},
          {model: 'codex', calisan: 0, durum: 'bilinmiyor'}])""")
        self.assertEqual({k: (v["metin"], v["ton"], v["durum"], v["unvan"]) for k, v in out.items()}, {
            "haiku": ("Stajyer (Haiku) · 1 çalışıyor · hazır", "busy", "calisiyor", "Stajyer"),
            "sonnet": ("Uzman (Sonnet) · hata: API Error: 529 Overloaded", "error", "hata", "Uzman"),
            "opus": ("Kıdemli (Opus) · kota doldu · 16:30'da döner", "warn", "kota", "Kıdemli"),
            "fable": ("Genel Müdür (Fable) · hazır", "ok", "hazir", "Genel Müdür"),
            "codex": ("Codex · durumu bilinmiyor", "muted", "bilinmiyor", "Dış denetçi")})

    def test_rows_are_always_the_five_models_in_order(self):
        out = self.board("rows([{model: 'codex', durum: 'hazir'}, {model: 'haiku', durum: 'hazir'}]).map((r) => r.model)")
        self.assertEqual(out, ["haiku", "sonnet", "opus", "fable", "codex"])

    def test_return_time_today_tomorrow_passed_and_unknown(self):
        out = self.board("""[
          rows([{model: 'codex', durum: 'kota', donus: '2026-11-12T15:05:00+03:00'}])[4].metin,
          rows([{model: 'opus', durum: 'kota', donus: '2026-11-11T13:00:00Z'}])[2].metin,
          rows([{model: 'opus', durum: 'kota', donus: '2026-11-11T09:00+03:00'}])[2].metin,
          rows([{model: 'opus', durum: 'kota', donus: null}])[2].metin,
          rows([{model: 'opus', durum: 'kota', donus: 'yarın'}])[2].metin,
          rows([{model: 'opus', durum: 'kota', calisan: 2, donus: '2026-11-11T12:00+03:00'}])[2].metin]""")
        self.assertEqual(out, ["Codex · kota doldu · 12 Kas 15:05'te döner",
                               "Kıdemli (Opus) · kota doldu · 16:00'da döner",
                               "Kıdemli (Opus) · kota doldu · dönüş saati geçti",
                               "Kıdemli (Opus) · kota doldu",
                               "Kıdemli (Opus) · kota doldu",
                               "Kıdemli (Opus) · 2 çalışıyor · kota doldu · 12:00'de döner"])

    def test_times_are_read_in_the_office_zone_whatever_the_browser_zone(self):
        expr = "rows([{model: 'opus', durum: 'kota', donus: '2026-11-11T13:30:00Z'}])[2].metin"
        for tz in ("UTC", "America/New_York", "Asia/Tokyo"):
            with self.subTest(tz=tz):
                self.assertEqual(self.board(expr, tz=tz), "Kıdemli (Opus) · kota doldu · 16:30'da döner")
        # no scene settings: the office default zone; an unknown zone: fixed UTC+3 like the server
        self.assertEqual(self.board("[rows([{model: 'opus', durum: 'kota', donus: '2026-11-11T13:30:00Z'}], NOW, null)[2].metin,"
                                    " rows([{model: 'opus', durum: 'kota', donus: '2026-11-11T13:30:00Z'}], NOW,"
                                    " {saat_dilimi: 'Yok/Boyle'})[2].metin]"),
                         ["Kıdemli (Opus) · kota doldu · 16:30'da döner"] * 2)

    def test_missing_unknown_and_garbled_models_are_honestly_unknown(self):
        out = self.board("""[rows(null).map((r) => r.metin), rows([{model: 'opus', durum: 'kotaa'}, {model: 'gpt-5', durum: 'kota'},
          null, 'x', {durum: 'kota'}, {model: 'claude-sonnet-4-5', durum: 'hazir'},
          {model: 'sonnet', durum: 'kota'}]).map((r) => [r.model, r.durum, r.ton]),
          rows([{model: 'fable', durum: 'kota'}], 'not a time')[3].metin]""")
        self.assertEqual(out[0], ["Stajyer (Haiku) · durumu bilinmiyor", "Uzman (Sonnet) · durumu bilinmiyor",
                                  "Kıdemli (Opus) · durumu bilinmiyor", "Genel Müdür (Fable) · durumu bilinmiyor",
                                  "Codex · durumu bilinmiyor"])
        # an unknown durum is never shown as kota; the first entry of a family counts; a bad now drops only the time
        self.assertEqual(out[1], [["haiku", "bilinmiyor", "muted"], ["sonnet", "hazir", "ok"],
                                  ["opus", "bilinmiyor", "muted"], ["fable", "bilinmiyor", "muted"],
                                  ["codex", "bilinmiyor", "muted"]])
        self.assertEqual(out[2], "Genel Müdür (Fable) · kota doldu")

    def test_kota_is_said_only_for_kota(self):
        out = self.board("""['hazir', 'calisiyor', 'hata', 'bilinmiyor', 'x'].map((d) =>
          rows([{model: 'opus', durum: d, donus: '2026-11-11T16:30+03:00', son_hata: 'error'}])[2].metin)""")
        for line in out:
            self.assertNotIn("kota", line)
            self.assertNotIn("döner", line)

    def test_errors_are_short_plain_text(self):
        out = self.board("""[rows([{model: 'sonnet', durum: 'hata', son_hata: '<b>API</b>\\n  Error ' + 'x'.repeat(200)}])[1],
          rows([{model: 'sonnet', durum: 'hata', son_hata: ''}])[1].metin]""")
        detail = out[0]["metin"].split("hata: ", 1)[1]
        self.assertLessEqual(len(detail), 60)
        self.assertTrue(detail.startswith("<b>API</b> Error x") and detail.endswith("…"), detail)
        self.assertEqual(out[1], "Uzman (Sonnet) · son çağrı hata verdi")

    def test_the_folded_summary_line(self):
        out = self.board("""[h.modelOzeti([]), h.modelOzeti(rows([{model: 'haiku', durum: 'hazir'}, {model: 'sonnet', durum: 'calisiyor', calisan: 1},
          {model: 'opus', durum: 'hazir'}, {model: 'fable', durum: 'hazir'}, {model: 'codex', durum: 'hazir'}])),
          h.modelOzeti(rows([{model: 'haiku', durum: 'hazir'}, {model: 'sonnet', durum: 'hata'}, {model: 'opus', durum: 'kota'},
          {model: 'fable', durum: 'hazir'}]))]""")
        self.assertEqual(out, ["durum yükleniyor", "hepsi hazır",
                               "Kıdemli (Opus): kota doldu · Uzman (Sonnet): hata · Codex: bilinmiyor"])

    def test_the_demo_board_shows_the_quota_and_its_return(self):
        out = run_scene(f"""(() => {{ {DEMO_JS} const at = (id) => {{ const t = demo.DEMO_SAHNELERI.find((x) => x.id === id).bas + 2;
            const x = demo.demoDurumu(t, NOW + t * 1000); return h.modelSatirlari(x.modeller, NOW + t * 1000, x.sahne)
              .map((r) => [r.model, r.durum, r.metin, r.kisa]); }};
          return {{ start: at('acilis'), kota: at('kota'), donus: at('donus') }}; }})()""")
        self.assertEqual([r[1] for r in out["start"]], ["calisiyor", "calisiyor", "calisiyor", "hazir", "hazir",
                                                        "hazir", "hazir", "hazir"])  # Fable idle; the security row too
        self.assertEqual([r[0] for r in out["start"]], ["haiku", "sonnet", "opus", "fable", "codex", "glm", "deepseek",
                                                        "guvenlik"])
        sonnet = out["kota"][1]
        self.assertEqual(sonnet[1], "kota")
        self.assertRegex(sonnet[2], r"^Uzman \(Sonnet\) · 1 çalışıyor · kota doldu · \d\d:\d\d'(da|de|te|ta) döner$")
        self.assertTrue(sonnet[3].startswith("1 çalışıyor · kota doldu · "), sonnet[3])  # the board's short text
        self.assertEqual(out["donus"][1][1], "calisiyor")
        self.assertTrue(all(r[1] != "kota" for r in out["start"] + out["donus"]))
        self.assertEqual(out["kota"][6][:3], ["deepseek", "kota", "DeepSeek · ücretsiz · kota doldu"])

    def test_the_page_wires_the_panel_and_the_popover_with_text_only(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("from './ofis-sahne.js'", "modelSatirlari(state.modeller, Date.now(), state.sahne)",
                     "modelOzeti(rows)", "renderModels();", "if (sahneGorunur()) renderScene();", "renderModels(); renderCalisanlar();", "renderCalisanlarKadro(rows);"):
            self.assertIn(name, app)
        self.assertNotIn("setModelPanosu", app)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        for gone in ("setModelPanosu", "panoKey", "panoTexture", "drawModelBoard", "buildPano", "fitExtra", "PANO_"):
            self.assertNotIn(gone, scene)  # the 3D wall board is gone (owner decision 2026-11-12)
        page = (WEB / "index.html").read_text(encoding="utf-8")
        # the side panel's own Çalışanlar list is gone (the owner, 2026-11-13: the live pill's popover has the same list)
        for name in ('id="models"', 'id="models-list"', 'id="models-sum"'):
            self.assertNotIn(name, page)
        self.assertIn('id="calisanlar-kadro"', page)
        self.assertIn(".models-list .ton-warn .dot", (WEB / "style.css").read_text(encoding="utf-8"))



# --- living office, step 5: the scripted demo, the roomier floor and the board's place ---

@unittest.skipUnless(NODE, "node is not installed")
class DemoScriptTest(unittest.TestCase):
    def test_the_scenes_come_in_order_and_last_about_three_minutes(self):
        out = run_scene("""(() => ({ ids: demo.DEMO_SAHNELERI.map((x) => x.id), bas: demo.DEMO_SAHNELERI.map((x) => x.bas),
          sure: demo.DEMO_SURE, metin: demo.DEMO_SAHNELERI.map((x) => x.metin),
          wrap: [demo.demoSahnesi(demo.DEMO_SURE + 1).id, demo.demoSahnesi(-1).id, demo.demoSahnesi(0).kalan] }))()""")
        self.assertEqual(out["ids"], ["acilis", "gelis", "calisma", "yardimci", "yardimci-bitti", "izin", "kontrol",
                                      "bitti", "mola", "cikis", "karar", "inceleme", "hakem", "yukseltme", "ogle", "kota",
                                      "donus"])
        lengths = [b - a for a, b in zip(out["bas"], out["bas"][1:] + [out["sure"]])]
        self.assertTrue(all(n >= 5 for n in lengths), lengths)  # each long enough to see
        self.assertTrue(150 <= out["sure"] <= 240, out["sure"])
        self.assertTrue(all(isinstance(m, str) and m and "<" not in m for m in out["metin"]))
        self.assertEqual(out["wrap"], ["acilis", "donus", 5])

    def test_each_scene_shows_its_event(self):
        out = run_scene(f"""(() => {{ {DEMO_JS}
          let prev = null; const at = {{}};
          for (let t = 0; t < demo.DEMO_SURE; t++) {{
            prev = sahne(t, prev);
            for (const x of demo.DEMO_SAHNELERI) if (t === x.bas + 3) at[x.id] = prev;
          }}
          const a = (id, aid) => at[id].find((x) => x.id === aid) || null;
          const pick = (x) => x && {{ yer: x.yer, poz: x.poz, simge: x.simge, masa: x.masa, cikis: !!x.cikis,
            dosya: !!x.dosya, unvan: x.unvan, metin: x.durum_metni }};
          const ids = ['gelis', 'calisma', 'yardimci', 'yardimci-bitti', 'izin', 'kontrol', 'bitti', 'cikis'];
          const out = {{}};
          for (const id of ids) out[id] = {{ n1: pick(a(id, 'is:n1')), alt: pick(a(id, 'is:n1/alt:yardimci-1')),
            cay: pick(a(id, 'sus:cayci')) }};
          out.karar = {{ c: pick(a('karar', 'is:c')), dec: stateAt(bas('karar') + 3).x.decisions.length }};
          out.inceleme = pick(a('inceleme', 'is:r'));
          out.yukseltme = {{ g: pick(a('yukseltme', 'is:g')), h: pick(a('yukseltme', 'is:h')) }};
          out.ogle = {{ bos: pick(a('ogle', 'oturum:ofis-blog-bos')), ceo: pick(a('ogle', 'ceo')), w: pick(a('ogle', 'is:a')) }};
          out.kota = {{ bos: pick(a('kota', 'oturum:ofis-blog-bos')), b: pick(a('kota', 'is:b')) }};
          out.donus = pick(a('donus', 'oturum:ofis-blog-bos'));
          out.lunch = demo.DEMO_SAHNELERI.filter((x) => {{ const s = stateAt(x.bas + 3); return d.ogleMi(s.now, s.x.sahne); }})
            .map((x) => x.id);
          return out; }})()""")
        self.assertEqual((out["gelis"]["n1"]["poz"], out["gelis"]["n1"]["yer"][:11]), ("lobide", "lobi-koltuk"))
        desk = out["calisma"]["n1"]["yer"]
        self.assertTrue(desk.startswith("ekip-blog-masa-"), desk)
        self.assertEqual(out["calisma"]["n1"]["poz"], "yaziyor")
        self.assertEqual((out["yardimci"]["alt"]["yer"], out["yardimci"]["alt"]["poz"]), (f"{desk}-yardimci-0", "yaziyor"))
        self.assertEqual(out["yardimci-bitti"]["alt"]["simge"], "✓")
        self.assertEqual((out["izin"]["n1"]["yer"], out["izin"]["n1"]["simge"]), (desk, "!"))
        self.assertEqual((out["kontrol"]["n1"]["yer"], out["kontrol"]["n1"]["simge"]), (desk, "test"))
        self.assertEqual((out["bitti"]["n1"]["poz"], out["bitti"]["n1"]["simge"]), ("kutluyor", "✓"))
        self.assertEqual(out["bitti"]["cay"]["yer"], f"{desk}-yan")  # the tea server brings tea
        self.assertEqual((out["cikis"]["n1"]["yer"], out["cikis"]["n1"]["cikis"]), ("asansor", True))
        self.assertTrue(out["karar"]["c"]["yer"].startswith("ceo-kuyruk-"))
        self.assertEqual((out["karar"]["c"]["simge"], out["karar"]["dec"]), ("?", 1))
        self.assertEqual(out["inceleme"]["poz"], "yaziyor")  # a Claude review types in the QA odası
        self.assertTrue(out["inceleme"]["yer"].startswith("qa-masa-"))
        g, hh = out["yukseltme"]["g"], out["yukseltme"]["h"]
        self.assertEqual((g["unvan"], hh["unvan"], g["dosya"], g["yer"]), ("Stajyer", "Kıdemli", True, f"{hh['masa']}-yan"))
        self.assertEqual(out["ogle"]["bos"]["poz"], "yemek")
        # a decision waits for the owner in that scene (the approval cards): the CEO stays at its desk, never at lunch
        self.assertEqual(out["ogle"]["ceo"]["yer"], "ceo-masa")
        self.assertEqual(out["ogle"]["w"]["poz"], "yaziyor")  # a working agent never goes to lunch
        self.assertEqual(out["kota"]["bos"]["poz"], "evde")
        self.assertRegex(out["kota"]["bos"]["metin"], r"^Evde · \d\d:\d\d'(da|de|te|ta) döner$")
        self.assertEqual(out["kota"]["b"]["poz"], "yaziyor")  # busy on the same model: stays at its desk
        self.assertNotEqual(out["donus"]["poz"], "evde")
        self.assertEqual(out["lunch"], ["ogle"])  # the demo's lunch window covers only its lunch scene

    def test_answering_the_card_sends_the_job_back_to_its_desk(self):
        out = run_scene(f"""(() => {{ {DEMO_JS} const k = bas('karar');
          const c = (t, o) => {{ const r = sahne(t, null, o).find((x) => x.id === 'is:c'); return [r.yer, r.poz, r.simge,
            stateAt(t, o).x.decisions.length, stateAt(t, o).x.sahne_metni]; }};
          return {{ before: c(k + 4, {{cevap: {{t: k + 3}}}}), after: c(k + 6, {{cevap: {{t: k + 3}}}}),
            stale: c(k + 6, {{cevap: {{t: 10}}}}), none: c(k + 6, {{}}) }}; }})()""")
        self.assertTrue(out["before"][0].startswith("ceo-kuyruk-"))  # the answer is delivered 2.5 s later
        self.assertEqual(out["after"][:4], ["yazilim-plan-masa", "yaziyor", None, 0])  # the planning desk (Yazılım Müdürü)
        self.assertIn("masasına", out["after"][4])
        self.assertTrue(out["stale"][0].startswith("ceo-kuyruk-"))  # an answer from before this decision is ignored
        self.assertEqual(out["none"][2:4], ["?", 1])

    def test_hafif_has_no_tea_server_and_the_script_is_deterministic(self):
        out = run_scene(f"""(() => {{ {DEMO_JS} let sus = 0, it = 0; for (let t = 0; t < demo.DEMO_SURE; t += 3)
            {{ const l = sahne(t, null, {{}}, {{hafif: true}});
              sus += l.filter((x) => x.tur === 'sus' && !['sekreter', 'guvenlik', 'revir'].includes(x.gorevli) && !x.nobetci).length;
              it = Math.max(it, l.filter((x) => x.gorevli === 'sunucu').length); }}
          return {{ sus, it, same: JSON.stringify(demo.demoDurumu(77, NOW)) === JSON.stringify(demo.demoDurumu(77, NOW)) }}; }})()""")
        # hafif: no tea server and no informational staff; of the IT team only the person on shift (owner decision 2026-11-12)
        self.assertEqual(out, {"sus": 0, "it": 1, "same": True})
        self.assertTrue(run_scene("h.tamEtiket({tur: 'ajan', poz: 'evde'})"))  # the "Evde · …" text shows by default
        text = (WEB / "demo.js").read_text(encoding="utf-8")
        self.assertNotIn("Math.random(", text)


@unittest.skipUnless(NODE, "node is not installed")
class RoomyFloorTest(unittest.TestCase):
    def test_rooms_and_team_areas_never_touch_and_corridors_are_wide(self):
        for n in (1, 2, 3, 4, 7):
            with self.subTest(projects=n):
                out = run_dav(f"""(() => {{ const p = d.ofisPlani(Array.from({{length: {n}}}, (_, i) => 'p' + i));
                  const r = p.odalar; const close = [];
                  for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {{
                    const a = r[i], b = r[j];
                    const gx = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w)), gz = Math.max(b.z - (a.z + a.d), a.z - (b.z + b.d));
                    if (Math.max(gx, gz) < 1.9) close.push(a.id + '|' + b.id + ':' + Math.max(gx, gz));
                  }}
                  const team = r.filter((x) => x.tur === 'ekip');
                  return {{ close, teamW: Math.min(...team.map((x) => x.w)), teamD: Math.min(...team.map((x) => x.d)) }}; }})()""")
                self.assertEqual(out["close"], [])
                self.assertGreaterEqual(out["teamW"], 12)
                self.assertGreaterEqual(out["teamD"], 9)

    def test_neighbours_keep_their_distance_and_helpers_stand_beside_the_desk(self):
        out = run_dav("""(() => { const p = d.ofisPlani(['a', 'b'], {max_running_per_project: 4}); const n = p.dugumler;
          const gap = (prefix, k) => Math.min(...Array.from({length: k - 1}, (_, i) => Math.hypot(n[prefix + i].x - n[prefix + (i + 1)].x,
            n[prefix + i].z - n[prefix + (i + 1)].z)));
          const desks = Object.values(n).filter((x) => x.tur === 'masa' && x.oda === 'ekip-a');
          let deskGap = 99; for (const x of desks) for (const y of desks) if (x !== y) deskGap = Math.min(deskGap, Math.hypot(x.x - y.x, x.z - y.z));
          const rel = []; for (const did of ['ekip-a-masa-1', 'ekip-a-mudur', 'ceo-masa']) for (let h = 0; h < 4; h++) {
            const s = n[(did === 'ceo-masa' ? 'ceo' : did) + '-yardimci-' + h]; rel.push([+(s.x - n[did].x).toFixed(2), +(s.z - n[did].z).toFixed(2)]); }
          // the nearest other body spot to any helper spot of a team desk
          const spots = Object.values(n).filter((x) => ['masa', 'mudur-masasi', 'yan', 'yardimci'].includes(x.tur) && x.oda === 'ekip-a');
          let helperGap = 99; for (const x of spots) if (x.tur === 'yardimci' && !x.id.endsWith('-4'))
            for (const y of spots) if (y !== x) helperGap = Math.min(helperGap, Math.hypot(x.x - y.x, x.z - y.z));
          return { kuyruk: gap('ceo-kuyruk-', 6), lobi: gap('lobi-koltuk-', 3), toplanti: gap('toplanti-sandalye-', 3),
            cay: gap('cay-ocagi-yer-', 3), deskGap, rel, helperGap }; })()""")
        self.assertGreaterEqual(out["kuyruk"], 1.5)
        self.assertGreaterEqual(out["lobi"], 1.9)
        self.assertGreaterEqual(out["toplanti"], 2.3)
        self.assertGreaterEqual(out["cay"], 2.0)
        self.assertGreaterEqual(out["deskGap"], 2.39)
        for dx, dz in out["rel"]:  # beside the chair (left of it), not hidden behind it
            self.assertLessEqual(dx, -1.1)
            self.assertGreaterEqual(dz, -0.4)
        self.assertGreaterEqual(out["helperGap"], 0.55)


class DemoAndBoardWiringTest(unittest.TestCase):
    def test_the_caption_and_the_start_offset(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("onSahne: showDemoCaption", "params.get('demo_t')", "el.textContent = text"):
            self.assertIn(name, app)
        page = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="demo-caption"', page)
        self.assertIn(".demo-caption", (WEB / "style.css").read_text(encoding="utf-8"))




# --- phone model board and the "Şu an çalışanlar" popover ---

class PillEmployeeListTest(unittest.TestCase):
    """The owner, 2026-11-12: the 3D wall board and the phone's floating board are gone; the live pill's popover ("Şu an iş
    başında") shows the grouped employee list below the active agents, also when nobody works."""

    def test_the_popover_has_the_employee_list_text_only_and_the_phone_board_is_gone(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        pop = html[html.index('id="calisanlar"'):html.index("</section>", html.index('id="calisanlar"'))]
        self.assertLess(pop.index('id="calisanlar-body"'), pop.index('id="calisanlar-kadro"'))  # below the agents
        self.assertIn('id="calisanlar-kadro-title" data-t="Çalışanlar">Çalışanlar<', pop)
        self.assertNotIn("model-mini", html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        fn = app[app.index("function renderCalisanlarKadro("):app.index("function renderCalisanlar() {")]
        for name in ("calisanGruplari(rows)", "h('span', 'dot')", "h('b', null, r.pano_ad || r.rol)", "h('span', 'kisa', r.kisa)",
                     "li.title = r.ipucu", "h('li', 'models-group', g.baslik)"):
            self.assertIn(name, fn)
        self.assertNotIn("innerHTML", fn)
        # rendered when the popover opens, whatever the active rows (the empty text "kimse yok" stays above it)
        open_fn = app[app.index("function renderCalisanlar() {"):app.index("function openCalisanlar(")]
        self.assertLess(open_fn.index("renderCalisanlarKadro("), open_fn.index("calisanlarTablosu(state"))
        self.assertNotIn("MINI_KEY", app)
        self.assertNotIn("model-mini", app)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertNotIn("model-mini", css)
        self.assertIn(".calisanlar-kadro {", css)
        self.assertEqual(run_scene("h.CALISANLAR_BOS"), "Şu an iş başında kimse yok.")


CAL_PRELUDE = r"""
const cal = (s) => h.calisanlarTablosu(s, NOW);
"""


@unittest.skipUnless(NODE, "node is not installed")
class CalisanlarTest(unittest.TestCase):
    def rows(self, state_expr):
        return run_scene(f"cal({state_expr})", prelude=CAL_PRELUDE)

    def test_nobody_working_is_an_empty_table(self):
        self.assertEqual(self.rows("st()"), [])
        self.assertEqual(run_scene("h.CALISANLAR_BOS"), "Şu an iş başında kimse yok.")

    def test_a_working_job_row_has_every_column(self):
        out = self.rows("""st({ sessions: [ses('ofis-w-1', 'busy', { note: 'a.md', model: 'opus', tier: 'kod',
            alt_ajanlar: [{ id: 'x', model: 'claude-haiku-4-5', bitti: false }, { id: 'y', model: 'haiku', bitti: false },
                          { id: 'z', model: 'sonnet', bitti: true }] })],
          tasks: [task('a.md', 'calisiyor', { session: 'ofis-w-1', spent: 0.0123, budget: 3, title: 'Giriş ekranı' })] })""")
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual([r["proje"], r["is"], r["unvan"], r["model"], r["katman"], r["durum"], r["sure"]],
                         ["yayin", "Giriş ekranı", "Kıdemli", "opus", "kod", "çalışıyor", "10 dk"])
        self.assertEqual(r["harcama"], "≈$0,0123 / ≈$3,00")
        self.assertEqual(r["yardimci"], "2 yardımcı (Haiku)")
        self.assertEqual(r["ac"], {"note": "a.md"})
        cells = run_scene("h.calisanHucreleri(cal(st({ tasks: [task('a.md', 'kontrolde')] }))[0])", prelude=CAL_PRELUDE)
        self.assertEqual(len(cells), 8)
        self.assertEqual(cells[2], "Kıdemli", "the worker: role only, the model in the cell's tooltip")

    def test_states_in_plain_turkish(self):
        out = self.rows("""st({ sessions: [ses('s-1', 'waiting', { note: 'a.md' }), ses('s-2', 'idle', { note: 'b.md' })],
          tasks: [task('a.md', 'calisiyor', { session: 's-1' }), task('b.md', 'calisiyor', { session: 's-2' }),
                  task('c.md', 'kontrolde'), task('d.md', 'karar-bekliyor'), task('e.md', 'baslatiliyor'),
                  task('f.md', 'bitti'), task('g.md', 'sirada'), task('h.md', 'tikandi')] })""")
        by = {r["ac"]["note"]: r["durum"] for r in out}
        self.assertEqual(by, {"a.md": "izin bekliyor", "b.md": "sessiz", "c.md": "Kontrol",
                              "d.md": "Selin'in cevabını bekliyor", "e.md": "başlıyor"})

    def test_the_ceo_first_and_codex_while_it_reviews(self):
        out = self.rows("""st({ ceo: { state: 'busy', cost_today: 0.5, usage_today: 250000, alt_ajanlar: [] },
          tasks: [task('r.md', 'incelemede', { inceleme_yurutucu: 'codex', tier: 'inceleme', title: 'Kod incelemesi' })] })""")
        self.assertEqual([r["id"] for r in out], ["ceo", "denetci:codex"])
        self.assertEqual(out[0]["unvan"], "CEO")
        self.assertEqual(out[0]["ac"], {"ceo": True})
        self.assertEqual(out[0]["harcama"], "bugün 250 bin token · ≈$0,50")
        self.assertEqual([out[1]["unvan"], out[1]["model"], out[1]["durum"], out[1]["harcama"]],
                         ["Dış denetçi", "codex", "inceliyor", "fiyat bilinmiyor"])
        self.assertEqual(out[1]["ac"], {"note": "r.md"})
        closing = self.rows("st({ ceo: { state: 'busy', tur_kapaniyor: true, alt_ajanlar: [] } })")
        self.assertEqual(closing[0]["durum"], "Cevap verdi · tur kapanıyor")
        idle = self.rows("st({ ceo: { state: 'idle', alt_ajanlar: [{ id: 'q', model: 'haiku', bitti: false }] } })")
        self.assertEqual(idle[0]["yardimci"], "1 yardımcı (Haiku)")  # an open helper keeps the CEO in the table

    def test_a_busy_session_without_an_open_job_is_listed_once(self):
        out = self.rows("""st({ sessions: [ses('ofis-x', 'busy', { model: 'sonnet' }), ses('ofis-y', 'idle')] })""")
        self.assertEqual([(r["id"], r["unvan"], r["is"]) for r in out], [("oturum:ofis-x", "Uzman", "—")])

    def test_unknown_values_are_dashes_and_a_long_title_is_cut(self):
        out = self.rows("st({ tasks: [task('a.md', 'calisiyor', { title: 'x'.repeat(200), started: '', created: '', "
                        "model: '', tier: '' })] })")
        r = out[0]
        self.assertLessEqual(len(r["is"]), 48)
        self.assertEqual([r["sure"], r["harcama"], r["yardimci"], r["model"], r["katman"]], ["—", "—", "—", "—", "—"])

    def test_only_a_job_row_names_the_job_for_its_progress_line(self):
        # the popover draws the job's compact progress line (web/is-akisi.js) only on a row of an open job
        out = self.rows("""st({ ceo: { state: 'busy', alt_ajanlar: [] },
          sessions: [ses('ofis-w-1', 'busy', { note: 'a.md' }), ses('ofis-x', 'busy', { note: 'old.md' })],
          tasks: [task('a.md', 'calisiyor', { session: 'ofis-w-1' }), task('old.md', 'bitti'),
                  task('r.md', 'incelemede', { inceleme_yurutucu: 'codex', tier: 'inceleme' })] })""")
        by = {r["id"]: r.get("yolNot", "") for r in out}
        self.assertEqual(by, {"ceo": "", "is:a": "a.md", "oturum:ofis-x": "", "denetci:codex": ""})

    def test_durations(self):
        out = run_scene("[h.sureMetni(NOW - 30000, NOW), h.sureMetni(NOW - 3900000, NOW), h.sureMetni(null, NOW)]")
        self.assertEqual(out, ["<1 dk", "1 sa 5 dk", "—"])


class CalisanlarWiringTest(unittest.TestCase):
    def test_the_pills_are_buttons_that_open_the_popover(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for pill in ("live-pill",):
            self.assertRegex(html, rf'<button[^>]*id="{pill}"[^>]*type="button"[^>]*aria-controls="calisanlar"')
        self.assertNotIn('id="run-text"', html)
        self.assertRegex(html, r'id="calisanlar" role="dialog"[^>]*hidden')
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("calisanlarTablosu(state, Date.now())", "CALISANLAR_BOS", "openDetail({ kind: 'task', note: now.ac.note })",
                     "selectRoom(CEO)", "e.key !== 'Escape' || !calisanlarOpen()", "closeCalisanlar(false)",
                     "makeClickable(tr,"):
            self.assertIn(name, app)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".pill-btn {", css)
        self.assertIn("cursor: pointer", css[css.index(".pill-btn {"):css.index(".pill-btn {") + 200])
        self.assertIn("td::before { content: attr(data-k)", css)  # the phone sheet labels each cell

    def test_rows_are_kept_and_updated_in_place(self):
        # a row keeps its element (focus, a click mid-press) when only its text changes, e.g. Süre every minute
        app = (WEB / "app.js").read_text(encoding="utf-8")
        body = app[app.index("function renderCalisanlar()"):app.index("function openCalisanlar(")]
        self.assertIn("calisanlarIds", body)
        self.assertIn("span.textContent !== text", body)
        self.assertIn("calisanlarRows.get(", body)

    def test_a_job_row_shows_its_compact_progress_line_under_the_title(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        body = app[app.index("function renderCalisanlar()"):app.index("function openCalisanlar(")]
        helper = app[app.index("function calisanYolu("):app.index("function renderCalisanlar()")]
        self.assertIn("yolCizgisi(t, { kompakt: true })", helper)  # the same line as the job cards, not a new one
        self.assertIn("setAttribute('data-yol-not', note)", helper)  # kept fresh like the chat's (yollariYenile)
        self.assertNotIn("innerHTML", helper)
        # drawn on a rebuild and refreshed on the in-place path (the row element stays: no flicker, focus kept)
        self.assertEqual(body.count("calisanYolu("), 2)
        self.assertLess(body.index("calisanYolu("), body.index("calisanlarIds = ids"))
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".calisanlar-table .yol-ozet { font-size: 12px;", css)
        self.assertIn(".calisanlar-table .yol-kompakt { margin: var(--s1) 0 0;", css)
        self.assertIn(".calisanlar-table td.c-is .yol-kompakt { grid-column: 2; }", css)  # the phone card layout



@unittest.skipUnless(NODE, "node is not installed")
class TokenTextTest(unittest.TestCase):
    """Tokens next to the dollars; tokenMetni is the twin of bin/budget.py token_text (same cases)."""

    def test_the_page_and_the_server_format_the_same(self):
        import sys
        sys.path.insert(0, str(WEB.parent / "bin"))
        import budget
        values = [0, 850, 999, 1000, 12_400, 99_949, 99_950, 182_400, 999_499, 999_500, 1_200_000, 15_300_000,
                  250_000_000, 182_500, 1_250_000, 12_450, 1_050_000, 99_999_999, "182400", None, "", "x", -5, True]
        page = run_js(f"{json.dumps(values)}.map((v) => t.tokenMetni(v))")
        self.assertEqual(page, [budget.token_text(v) for v in values])
        self.assertEqual(page[:4], ["0 token", "850 token", "999 token", "1 bin token"])
        self.assertEqual(page[4], "12,4 bin token")
        self.assertEqual(page[10], "1,2 mn token")
        self.assertEqual(page[-5:], ["", "", "", "", ""])
        self.assertEqual(page[13:15], ["183 bin token", "1,3 mn token"])  # half-up on both sides

    def test_spending_texts_carry_the_tokens_when_known(self):
        t = {"status": "calisiyor", "spent": "0.41", "budget": 3, "calls": "12", "max_calls": 40, "tokens": "182400"}
        self.assertEqual(run_js(f"t.budgetText({json.dumps(t)})"), "182 bin token · ≈$0,41 / ≈$3,00 · 12 / 40 çağrı")
        self.assertEqual(run_js(f"t.budgetBar({json.dumps(t)}).money.text"), "182 bin token · ≈$0,41 / ≈$3,00")
        old = {**t, "tokens": ""}
        self.assertEqual(run_js(f"t.budgetBar({json.dumps(old)}).money.text"), "≈$0,41 / ≈$3,00")
        self.assertEqual(run_js("[t.harcamaText('0.41', 182400), t.harcamaText('0.41', ''), t.harcamaText('', '')]"),
                         ["182 bin token · ≈$0,41", "≈$0,41", "—"])
        self.assertEqual(run_js("t.reportCostText({toplam_usd: 1.8423, toplam_token: 642000})"),
                         "642 bin token · ≈$1,84")
        self.assertEqual(run_js("t.reportCostText({toplam_usd: 1.8423})"), "≈$1,84")
        cells = run_js("[t.qualityCells({toplam_token: 1830000}).at(-1), t.qualityCells({}).at(-1), t.QUALITY_HEAD.at(-1)]")
        self.assertEqual(cells, ["1,8 mn token", "—", "Token"])

    def test_the_quality_view_shows_the_token_twin_of_every_dollar_metric(self):
        row = {"proje": "yayin", "katman": "kod", "model": "opus", "is_sayisi": 9, "bitti": 8, "ilk_tur_gecen": 7,
               "ilk_tur_olculen": 8, "yeniden_is": 2, "dogrulanmis_is_basina_usd": 0.27, "dogrulanmis_is_basina_token": 182400,
               "ort_usd": 0.24, "ort_token": 161000, "ort_sure_dk": 30, "toplam_token": 1450000, "token_bilinmeyen": 1}
        cells = run_js(f"t.qualityCells({json.dumps(row)})")
        self.assertEqual(cells[7:], ["182 bin token · ≈$0,27", "161 bin token · ≈$0,24", "30 dk",
                                     "1,5 mn token (1 işte kayıtlı değil)"])
        # unknown tokens: the dollars alone, "—" for the total, never "0 token"
        old = {k: v for k, v in row.items() if "token" not in k}
        self.assertEqual(run_js(f"t.qualityCells({json.dumps(old)})")[7:], ["≈$0,27", "≈$0,24", "30 dk", "—"])
        self.assertEqual(run_js("t.tokenToplamMetni({toplam_token: 0, token_bilinmeyen: 0})"), "0 token")
        self.assertEqual(run_js("t.paraTokenMetni(null, 5)"), "—")  # no verified job: nothing, not the tokens alone

    def test_the_quality_tiles_carry_tokens_and_say_how_many_jobs_have_no_count(self):
        t = {"is_sayisi": 10, "bitti": 8, "ilk_tur_gecen": 7, "ilk_tur_olculen": 8, "yeniden_is": 2, "dogrulanan": 8,
             "toplam_usd": 2.16, "ort_usd": 0.216, "dogrulanmis_is_basina_usd": 0.27, "ort_sure_dk": 30,
             "toplam_token": 1460000, "ort_token": 182500, "dogrulanmis_is_basina_token": 182500, "token_bilinen": 8,
             "token_bilinmeyen": 2}
        tiles = run_js(f"t.kaliteKutulari({json.dumps(t)})")
        self.assertEqual(tiles[0], {"etiket": "Doğrulanmış iş başına kullanım", "deger": "183 bin token · ≈$0,27",
                                    "ipucu": "8 iş kontrolü geçerek bitti · 2 işin token sayısı kayıtlı değil", "ana": True})
        self.assertEqual(tiles[-1], {"etiket": "Toplam kullanım", "deger": "1,5 mn token · ≈$2,16",
                                     "ipucu": "iş başına ortalama 183 bin token · ≈$0,22", "ana": False})
        old = {k: v for k, v in t.items() if "token" not in k}
        tiles = run_js(f"t.kaliteKutulari({json.dumps(old)})")
        self.assertEqual((tiles[0]["deger"], tiles[0]["ipucu"], tiles[-1]["deger"], tiles[-1]["ipucu"]),
                         ("≈$0,27", "8 iş kontrolü geçerek bitti", "≈$2,16", "iş başına ortalama ≈$0,22"))
        self.assertEqual(run_js("t.kaliteKutulari(null)"), [])

    def test_a_report_card_shows_the_verified_tokens_and_the_missing_counts(self):
        r = {"toplam_usd": 1.8423, "toplam_token": 642000, "token_eksik": 1, "dogrulanmis_is_basina_usd": 0.9212,
             "dogrulanmis_is_basina_token": 321000, "dogrulanan": 2}
        self.assertEqual(run_js(f"t.reportCostText({json.dumps(r)})"), "642 bin token (1 işte kayıtlı değil) · ≈$1,84")
        self.assertEqual(run_js(f"t.reportVerifiedText({json.dumps(r)})"), "321 bin token · ≈$0,92")
        self.assertEqual(run_js("t.reportVerifiedText({dogrulanmis_is_basina_usd: null})"),
                         "yok (kontrolü geçerek biten iş yok)")
        self.assertEqual(run_js("t.reportVerifiedText({dogrulanmis_is_basina_usd: 0.5})"), "≈$0,50")

    def test_the_running_table_shows_tokens_in_harcama(self):
        out = run_scene("""h.calisanlarTablosu(st({ tasks: [task('a.md', 'calisiyor', { spent: '0.41', budget: 3,
            tokens: 182400 }), task('b.md', 'calisiyor', { spent: '0.2', budget: 3, tokens: '' })] }), NOW)
            .map((r) => r.harcama)""")
        self.assertEqual(sorted(out), ["182 bin token · ≈$0,41 / ≈$3,00", "≈$0,20 / ≈$3,00"])


# --- the review panel in the office (dış denetçi heyeti, plan step 4): auditor desks, the hakem, rows ---

PANEL_PRELUDE = r"""
const FREE = [{model: 'glm', unvan: 'Dış denetçi', calisan: 0, durum: 'hazir', donus: null, son_hata: null},
  {model: 'deepseek', unvan: 'Dış denetçi', calisan: 0, durum: 'hazir', donus: null, son_hata: null}];
const CODEX = {model: 'codex', unvan: 'Dış denetçi', calisan: 0, durum: 'hazir', donus: null, son_hata: null};
const rev = (x = {}) => task('p.md', 'incelemede', {inceleme_yurutucu: 'codex', step_kind: 'kod-inceleme', tier: 'inceleme',
  title: 'Kod incelemesi', ...x});
const panel = (x = {}) => st({modeller: [CODEX, ...FREE], tasks: [rev()], ...x});
const pick = (a) => a && {yer: a.yer, poz: a.poz, simge: a.simge, metin: a.durum_metni, etiket: a.etiket,
  tiklama: a.tiklama, ucretsiz: a.ucretsiz};
const aud = (list) => Object.fromEntries(list.filter((a) => a.denetci).map((a) => [a.id, pick(a)]));
"""


def run_panel(expr, tz=None, extra=""):
    return run_scene(expr, PANEL_PRELUDE + extra, tz=tz)


@unittest.skipUnless(NODE, "node is not installed")
class AuditorRoomTest(unittest.TestCase):
    def test_the_auditor_list_is_codex_first_then_the_valid_free_reviewers_once(self):
        out = run_panel("""[d.denetciListesi(null), d.denetciListesi([CODEX, ...FREE, FREE[0], {model: 'opus', unvan: 'Kıdemli'},
          {model: 'sonnet', unvan: 'Dış denetçi'}, {model: 'Bad!', unvan: 'Dış denetçi'}, {model: 'kimi'}, null]),
          d.denetciListesi(['glm', 'codex', 'x', 'deepseek']), d.denetciAdi('glm'), d.denetciAdi('deepseek'),
          d.denetciAdi('codex'), d.denetciAdi('kimi'), d.denetciMasasi('codex'), d.denetciMasasi('glm'),
          d.denetciAdi('antigravity'), d.denetciListesi(['glm', 'deepseek', 'antigravity'])]""")
        self.assertEqual(out, [["codex"], ["codex", "glm", "deepseek"], ["codex", "glm", "deepseek"], "GLM", "DeepSeek",
                               "Codex", "Kimi", "denetci-masa", "denetci-masa-glm", "Antigravity",
                               ["codex", "glm", "deepseek", "antigravity"]])

    def test_one_desk_per_auditor_side_by_side_with_room_to_breathe(self):
        for n_proj in (0, 1, 2, 3, 7):
            for free in ([], ["glm"], ["glm", "deepseek"], ["glm", "deepseek", "kimi"]):
                with self.subTest(projects=n_proj, free=free):
                    out = run_panel(f"""(() => {{ const p = d.ofisPlani(Array.from({{length: {n_proj}}}, (_, i) => 'p' + i),
                        {{denetciler: {json.dumps(free)}}});
                      const room = p.odalar.find((r) => r.id === 'denetci'), ceo = p.odalar.find((r) => r.id === 'ceo');
                      const desks = Object.values(p.dugumler).filter((x) => x.oda === 'denetci' && x.tur === 'masa');
                      const xs = desks.map((x) => x.x).sort((a, b) => a - b);
                      const edges = new Set(p.kenarlar.flatMap(([a, b]) => [a + '|' + b, b + '|' + a]));
                      const bad = [];
                      for (const id of Object.keys(p.dugumler)) {{ const w = p.yol('asansor', id);
                        if (!w.length || w[w.length - 1].id !== id) bad.push(id);
                        for (let i = 1; i < w.length; i++) if (!edges.has(w[i - 1].id + '|' + w[i].id)) bad.push(id); }}
                      return {{ ids: desks.map((x) => x.id), zs: [...new Set(desks.map((x) => x.z))], xs,
                        gap: Math.min(99, ...xs.slice(1).map((x, i) => x - xs[i])), left: xs[0] - room.x,
                        right: room.x + room.w - xs[xs.length - 1], ceoGap: room.x - (ceo.x + ceo.w),
                        ceoMid: ceo.x + ceo.w / 2 - p.ortak.w / 2, edge: room.x + room.w - p.ortak.w, bad,
                        denetciler: p.denetciler, key: h.planAnahtari(p) }}; }})()""")
                    self.assertEqual(out["ids"], ["denetci-masa"] + [f"denetci-masa-{x}" for x in free])
                    self.assertEqual(out["denetciler"], ["codex"] + free)
                    self.assertEqual(len(out["zs"]), 1)  # one row, side by side
                    if free:
                        self.assertGreaterEqual(out["gap"], 3.5)  # a desk is about 2.3 wide: over a unit between
                    self.assertGreaterEqual(out["left"], 2.4)
                    self.assertGreaterEqual(out["right"], 2.4)
                    self.assertGreaterEqual(out["ceoGap"], 1.9)
                    self.assertAlmostEqual(out["ceoMid"], 0, places=6)  # the CEO's room stays in the common area's middle
                    self.assertAlmostEqual(out["edge"], 0, places=6)
                    self.assertEqual(out["bad"], [])
                    self.assertTrue(out["key"].endswith("#" + ",".join(["codex"] + free)), out["key"])

    def test_the_floor_stays_as_it_was_with_codex_alone(self):
        out = run_panel("""[d.ofisPlani(['yayin']).ortak.w, d.ofisPlani(['yayin'], {denetciler: ['glm', 'deepseek']}).ortak.w,
          d.ofisPlani(['yayin']).odalar.find((r) => r.id === 'denetci').w,
          d.ofisPlani(['yayin'], {denetciler: ['glm', 'deepseek']}).odalar.find((r) => r.id === 'denetci').w]""")
        # the common area: 56 base units x 1.5 (52 until 2026-11-13: the Dinlenme odası widened for its 20 beds)
        self.assertEqual(out[0], 84)
        self.assertEqual(out[1], 84)  # the wider auditor room still fits the common area
        self.assertGreater(out[3], out[2])

    def test_reviewers_at_work_type_at_their_desks_and_open_the_reviewed_job(self):
        out = run_panel("""aud(run(panel({denetim: {is: 'p.md', denetciler: ['codex', 'glm', 'deepseek'], hakem: ''}})))""")
        click = {"note": "p.md"}
        self.assertEqual(out["denetci:codex"], {"yer": "denetci-masa", "poz": "yaziyor", "simge": None,
                                                "metin": "inceliyor · yayin", "etiket": "Codex",
                                                "tiklama": click, "ucretsiz": False})
        self.assertEqual(out["denetci:glm"], {"yer": "denetci-masa-glm", "poz": "yaziyor", "simge": None,
                                              "metin": "inceliyor · yayin", "etiket": "GLM",
                                              "tiklama": click, "ucretsiz": True})
        self.assertEqual(out["denetci:deepseek"]["etiket"], "DeepSeek")
        self.assertEqual(out["denetci:deepseek"]["poz"], "yaziyor")
        # only those the marker names are at work; the rest sit idle at their desks
        out = run_panel("aud(run(panel({denetim: {is: 'p.md', denetciler: ['codex'], hakem: ''}})))")
        self.assertEqual((out["denetci:glm"]["poz"], out["denetci:glm"]["metin"], out["denetci:glm"]["tiklama"]),
                         ("bekliyor", "hazır", None))

    def test_the_hakem_weighs_the_findings_in_the_uzmanlar_room(self):
        out = run_panel("""(() => { const acts = run(panel({denetim: {is: 'p.md', denetciler: [], hakem: 'sonnet'}}));
          const hk = one(acts, 'hakem');
          return { hk: {...pick(hk), unvan: hk.unvan, model: hk.model, tur: hk.tur}, aud: aud(acts),
            label: h.etiketBilgisi(hk, {yakin: false}), cls: h.durumSinifi(hk) }; })()""")
        self.assertEqual(out["hk"], {"yer": "uzmanlar-masa-0", "poz": "yaziyor", "simge": None,
                                     "metin": "bulguları tartıyor", "etiket": "Hakem (Sonnet)", "tiklama": {"note": "p.md"},
                                     "unvan": "Uzman", "model": "sonnet", "tur": "ajan"})
        self.assertEqual((out["label"]["ad"], out["label"]["durum"], out["cls"]),
                         ("Hakem", "bulguları tartıyor", "is-working is-gorevde"))  # role only on the floor; shown at the default zoom
        self.assertTrue(all(a["poz"] != "yaziyor" for a in out["aud"].values()), out["aud"])  # the panel is done
        # the hakem keeps its chair when the meeting room is full; no marker, no hakem
        out = run_panel("""(() => { const s = Array.from({length: 7}, (_, i) => ses('r' + i, 'busy', {note: 'r' + i + '.md'}));
          const t = s.map((x, i) => task('r' + i + '.md', 'calisiyor', {session: x.name, tier: 'inceleme'}));
          const acts = run({...panel({denetim: {is: 'p.md', denetciler: [], hakem: 'sonnet'}}), sessions: s,
            tasks: [rev(), ...t]});
          return [one(acts, 'hakem').yer, one(acts, 'ozet:qa').etiket, !!one(acts, 'ozet:uzmanlar'), !!one(run(panel()), 'hakem')]; })()""")
        # plan "Sonraki iş (9)": the reviews fill the QA odası ("+3"), the hakem keeps its Uzmanlar odası desk
        self.assertEqual(out, ["uzmanlar-masa-0", "+3", False, False])

    def test_quota_error_and_unknown_only_when_the_server_says_so(self):
        out = run_panel("""[['kota', null], ['kota', '2026-11-11T16:30+03:00'], ['hata', null], ['bilinmiyor', null],
          ['kotaa', null], [undefined, null], ['hazir', null]].map(([durum, donus]) => {
            const m = [{...CODEX, durum: 'hazir'}, {...FREE[0], durum, donus}];
            return pick(one(run(st({modeller: m})), 'denetci:glm')); })""")
        self.assertEqual([(a["poz"], a["simge"], a["metin"], a["yer"]) for a in out], [
            ("evde", None, "Evde · kota doldu", "denetci-masa-glm"),
            ("evde", None, "Evde · 16:30'da döner", "denetci-masa-glm"),
            ("bekliyor", "kirmizi", "son çalışma hata verdi", "denetci-masa-glm"),
            ("bekliyor", None, "durumu bilinmiyor", "denetci-masa-glm"),
            ("bekliyor", None, "durumu bilinmiyor", "denetci-masa-glm"),
            ("bekliyor", None, "durumu bilinmiyor", "denetci-masa-glm"),
            ("bekliyor", None, "hazır", "denetci-masa-glm")])

    def test_work_beats_a_quota_flag(self):
        out = run_panel("""pick(one(run(st({modeller: [CODEX, {...FREE[0], durum: 'kota'}], denetim: {is: 'p.md', denetciler: ['glm'],
            hakem: ''}, tasks: [rev()]})), 'denetci:glm'))""")
        self.assertEqual(out["poz"], "yaziyor")

    # The owner, 2026-11-12: idle auditors join office life (breaks like the kadro); at work they type at their desk
    IDLE_LIFE = r"""
const minutes = Array.from({length: 90}, (_, i) => NOW + i * 60000);
const yerler = (s, opts = {}) => minutes.map((t) => Object.fromEntries(run(s, t, null, opts).filter((a) => a.denetci)
  .map((a) => [a.id, {yer: a.yer, poz: a.poz, metin: a.durum_metni, simge: a.simge}])));
"""

    def test_an_auditor_at_work_never_takes_a_break(self):
        out = run_panel("""yerler(panel({denetim: {is: 'p.md', denetciler: ['codex', 'glm', 'deepseek'],
          hakem: ''}})).flatMap((g) => Object.entries(g).map(([id, a]) => [id, a.yer, a.poz]))""", extra=self.IDLE_LIFE)
        self.assertTrue(out)
        for aid, yer, poz in out:
            self.assertEqual((yer, poz), (d_masa(aid), "yaziyor"))
        # even with a forced break (the demo's sahne.mola) and at lunch
        out = run_panel("""[aud(run(panel({denetim: {is: 'p.md', denetciler: ['codex'], hakem: ''}, sahne: {mola: 'oyun'}}))),
          aud(run(panel({denetim: {is: 'p.md', denetciler: ['codex'], hakem: ''}}), LUNCH))]""")
        for group in out:
            self.assertEqual((group["denetci:codex"]["yer"], group["denetci:codex"]["poz"]), ("denetci-masa", "yaziyor"))

    def test_an_idle_auditor_takes_breaks_and_lunch_but_not_in_hafif(self):
        out = run_panel("""({ free: yerler(st({modeller: [CODEX, ...FREE]})),
          unknown: yerler(st({modeller: [{...CODEX, durum: 'x'}]})),
          hafif: yerler(st({modeller: [CODEX, ...FREE]}), {hafif: true}),
          lunch: Object.fromEntries(['denetci:codex', 'denetci:glm', 'denetci:deepseek']
            .map((id) => [id, aud(run(st({modeller: [CODEX, ...FREE]}), yemekAni(id)))[id]])),
          forced: aud(run(st({modeller: [CODEX, ...FREE], sahne: {mola: 'cay'}}), NOW + 30000)) })""", extra=self.IDLE_LIFE)
        away = {aid for g in out["free"] for aid, a in g.items() if a["yer"] != d_masa(aid)}
        self.assertEqual(away, {"denetci:codex", "denetci:glm", "denetci:deepseek"})  # each one leaves its desk sometime
        self.assertTrue(any(a["yer"] != d_masa(aid) for g in out["unknown"] for aid, a in g.items()))  # bilinmiyor too
        for g in out["hafif"]:
            for aid, a in g.items():
                self.assertEqual((a["yer"], a["poz"]), (d_masa(aid), "bekliyor"))
        for aid, a in out["lunch"].items():
            self.assertTrue(a["yer"].startswith("yemekhane-sandalye-"), (aid, a))
            self.assertEqual(a["poz"], "yemek")
        drinks = [a for a in out["forced"].values()]
        self.assertTrue(all(a["poz"] in ("cay", "bekliyor") for a in drinks), drinks)
        self.assertTrue(any(a["yer"].startswith("ortak-alan-yer-") and a["metin"].endswith("içiyor · ortak alan")
                            for a in drinks), drinks)

    def test_kota_and_hata_auditors_stay_at_their_desks(self):
        out = run_panel("""[yerler(st({modeller: [CODEX, {...FREE[0], durum: 'kota', donus: null},
          {...FREE[1], durum: 'hata'}]})), aud(run(st({modeller: [CODEX, {...FREE[0], durum: 'kota', donus: null},
          {...FREE[1], durum: 'hata'}]}), LUNCH))]""", extra=self.IDLE_LIFE)
        for g in out[0] + [out[1]]:
            self.assertEqual((g["denetci:glm"]["yer"], g["denetci:glm"]["poz"], g["denetci:glm"]["metin"]),
                             ("denetci-masa-glm", "evde", "Evde · kota doldu"))  # the "Evde" sign at its desk
            self.assertEqual((g["denetci:deepseek"]["yer"], g["denetci:deepseek"]["simge"]),
                             ("denetci-masa-deepseek", "kirmizi"))

    def test_auditor_floor_labels_are_short_and_the_role_is_in_the_tooltip(self):
        out = run_panel("""(() => { const acts = run(panel({denetim: {is: 'p.md', denetciler: ['codex', 'glm', 'guvenlik'],
            hakem: 'sonnet'}, modeller: [CODEX, ...FREE, {model: 'guvenlik', unvan: 'Güvenlik denetçisi', durum: 'hazir',
            calisan: 1, ajan_modeli: 'sonnet'}]}));
          return ['denetci:codex', 'denetci:glm', 'denetci:deepseek', 'denetci:guvenlik', 'hakem'].map((id) => {
            const a = one(acts, id); return [h.etiketBilgisi(a, {yakin: true}).ad, h.etiketBilgisi(a, {yakin: false}).ad, a.ipucu]; }); })()""")
        self.assertEqual(out, [["Codex", "Codex", "Codex · Dış denetçi"], ["GLM", "GLM", "GLM · Dış denetçi · ücretsiz"],
                               ["DeepSeek", "DeepSeek", "DeepSeek · Dış denetçi · ücretsiz"],
                               ["IT güvenlik uzmanı", "IT güvenlik uzmanı", "IT güvenlik uzmanı · Güvenlik denetçisi (Sonnet)"], ["Hakem", "Hakem", "Hakem (Sonnet)"]])
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("const tip = typeof v.a.ipucu === 'string' ? v.a.ipucu : '';", scene)
        self.assertIn("if (L.el.title !== tip) L.el.title = tip;", scene)

    def test_without_the_marker_an_older_server_still_shows_codex_and_the_rows(self):
        out = run_panel("""[aud(run(panel())), aud(run(st({modeller: [CODEX, {...FREE[0], durum: 'calisiyor', calisan: 1}]})))]""")
        self.assertEqual((out[0]["denetci:codex"]["poz"], out[0]["denetci:codex"]["tiklama"]), ("yaziyor", {"note": "p.md"}))
        self.assertEqual(out[0]["denetci:glm"]["poz"], "bekliyor")
        self.assertEqual(out[1]["denetci:glm"]["poz"], "yaziyor")
        self.assertNotEqual(out[1]["denetci:codex"]["poz"], "yaziyor")  # idle: at its desk or on a break
        # a free reviewer the server no longer lists (no project uses it) has no actor, even with a stale plan
        out = run_panel("""Object.keys(aud(run(st({modeller: [CODEX]}), NOW, null,
          {plan: d.ofisPlani(['yayin'], {denetciler: ['glm']})})))""")
        self.assertEqual(out, ["denetci:codex"])

    def test_each_reviewer_has_its_own_shell_colour(self):
        out = run_panel("""[['codex', 'glm', 'deepseek', 'antigravity', 'kimi'].map((x) => h.denetciRenk(x)),
          h.denetciRenk('kimi'), h.denetciRenk('kimi')]""")
        shells = [c["shell"] for c in out[0]]
        trims = [c["trim"] for c in out[0]]
        self.assertEqual(len(set(shells)), 5)
        self.assertEqual(len(set(trims)), 5)
        claude = {"#E4F4E7", "#DEEBFA", "#ECE2FA", "#FBE9C6"}  # scene.js SHELL of the Claude families
        self.assertFalse(claude & set(shells))
        self.assertEqual(out[0][0]["shell"], "#C9E4DE")  # Codex stays teal
        self.assertEqual(out[1], out[2])

    def test_antigravity_is_a_free_reviewer_with_its_own_label_desk_and_quota_sign(self):
        # plan "Sonraki iş (10)": the model row "Antigravity · ücretsiz", unvan "Dış denetçi"; quota → "Evde" at its desk
        out = run_scene("""h.modelSatirlari([{model: 'antigravity', unvan: 'Dış denetçi', durum: 'kota', donus: null},
          {model: 'antigravity', unvan: 'Dış denetçi', durum: 'hazir'}],
          NOW, {saat_dilimi: 'Europe/Istanbul'}).filter((r) => r.model === 'antigravity').map((r) => [r.ad, r.metin, r.ucretsiz, r.grup])""")
        self.assertEqual(out[0][:3], ["Antigravity", "Antigravity · ücretsiz · kota doldu", True])
        out = run_panel("""(() => { const plan = d.ofisPlani(['yayin'], {denetciler: ['glm', 'deepseek', 'antigravity']});
          const a = run(st({modeller: [CODEX, ...FREE, {model: 'antigravity', unvan: 'Dış denetçi', durum: 'kota', donus: null}]}),
            NOW, null, {plan}).find((x) => x.id === 'denetci:antigravity');
          return [a.yer, a.poz, a.etiket, a.ipucu, !!plan.dugumler['denetci-masa-antigravity']]; })()""")
        self.assertEqual(out[0], "denetci-masa-antigravity")
        self.assertEqual(out[1], "evde")
        self.assertEqual(out[3], "Antigravity · Dış denetçi · ücretsiz")
        self.assertTrue(out[4])

    def test_model_rows_list_claude_then_codex_then_the_free_reviewers(self):
        out = run_scene("""h.modelSatirlari([{model: 'deepseek', unvan: 'Dış denetçi', durum: 'kota', donus: null},
          {model: 'glm', unvan: 'Dış denetçi', durum: 'calisiyor', calisan: 1}, {model: 'glm', unvan: 'Dış denetçi', durum: 'hata'},
          {model: 'opus', unvan: 'Dış denetçi', durum: 'kota'}, {model: 'codex', unvan: 'Dış denetçi', durum: 'hazir'}],
          NOW, {saat_dilimi: 'Europe/Istanbul'}).map((r) => [r.model, r.ad, r.metin, r.kisa, r.ton, r.ucretsiz])""")
        self.assertEqual([r[0] for r in out], ["haiku", "sonnet", "opus", "fable", "codex", "deepseek", "glm"])
        self.assertEqual(out[2][2], "Kıdemli (Opus) · kota doldu")  # a Claude family never becomes a free reviewer
        self.assertEqual(out[4][2:], ["Codex · hazır", "hazır", "ok", False])
        self.assertEqual(out[5][1:], ["DeepSeek", "DeepSeek · ücretsiz · kota doldu", "kota doldu", "warn",
                                      True])
        self.assertEqual(out[6][1:], ["GLM", "GLM · ücretsiz · 1 çalışıyor · hazır", "1 çalışıyor · hazır",
                                      "busy", True])
        self.assertEqual(run_scene("""h.modelOzeti(h.modelSatirlari([{model: 'glm', unvan: 'Dış denetçi', durum: 'kota'},
          ...['haiku', 'sonnet', 'opus', 'fable', 'codex'].map((m) => ({model: m, durum: 'hazir'}))], NOW))"""),
                         "GLM: kota doldu")


def d_masa(actor_id):
    ad = actor_id.split(":", 1)[1]
    return "denetci-masa" if ad == "codex" else f"denetci-masa-{ad}"


@unittest.skipUnless(NODE, "node is not installed")
class PanelTableAndDemoTest(unittest.TestCase):
    def test_the_table_lists_the_reviewers_at_work_and_the_hakem(self):
        out = run_scene("""(() => { const s = (denetim) => st({ceo: {state: 'dormant'}, denetim,
            modeller: [{model: 'glm', unvan: 'Dış denetçi', durum: 'calisiyor'}],
            tasks: [task('p.md', 'incelemede', {inceleme_yurutucu: 'codex', tier: 'inceleme', title: 'Kod incelemesi'})]});
          const f = (r) => [r.id, r.is, r.unvan, r.model, r.katman, r.durum, r.harcama, r.ac];
          return [h.calisanlarTablosu(s({is: 'p.md', denetciler: ['codex', 'glm'], hakem: ''}), NOW).map(f),
            h.calisanlarTablosu(s({is: 'p.md', denetciler: [], hakem: 'sonnet'}), NOW).map(f),
            h.calisanlarTablosu(s(null), NOW).map(f),
            h.calisanlarTablosu(st({denetim: {is: 'q.md', denetciler: ['glm', 'guvenlik'], hakem: ''},
              modeller: [{model: 'glm', unvan: 'Dış denetçi'}]}), NOW).map(f)]; })()""")
        note = {"note": "p.md"}
        self.assertEqual(out[0], [
            ["denetci:codex", "Kod incelemesi", "Dış denetçi", "codex", "inceleme", "inceliyor", "fiyat bilinmiyor", note],
            ["denetci:glm", "Kod incelemesi", "Dış denetçi", "glm", "inceleme", "inceliyor", "ücretsiz", note]])
        self.assertEqual(out[1], [["hakem", "Kod incelemesi", "Hakem", "sonnet", "inceleme", "bulguları tartıyor", "—", note]])
        self.assertEqual([r[0] for r in out[2]], ["denetci:codex"])  # an older server: Codex alone, as before
        self.assertEqual(out[3], [["denetci:glm", "q", "Dış denetçi", "glm", "inceleme", "inceliyor", "ücretsiz",
                                   {"note": "q.md"}],
                                  ["denetci:guvenlik", "q", "Güvenlik denetçisi", "guvenlik", "inceleme", "inceliyor",
                                   "—", {"note": "q.md"}]])

    def test_the_demo_review_shows_the_panel_then_the_hakem_and_a_free_quota(self):
        out = run_panel(f"""(() => {{ {DEMO_JS}
          const at = (id) => sahne(bas(id) + 3);
          const hk = (acts) => one(acts, 'hakem');
          return {{ inc: aud(at('inceleme')), incHakem: !!hk(at('inceleme')), hakem: pick(hk(at('hakem'))),
            hakemAud: aud(at('hakem')), kota: aud(at('kota')), yuk: aud(at('yukseltme')), yukHakem: !!hk(at('yukseltme')),
            rows: h.modelSatirlari(stateAt(bas('inceleme') + 3).x.modeller, NOW).map((r) => [r.model, r.durum]),
            table: h.calisanlarTablosu(stateAt(bas('hakem') + 3).st, NOW).map((r) => r.id) }}; }})()""")
        self.assertEqual({k: (v["poz"], v["tiklama"]) for k, v in out["inc"].items()},
                         {f"denetci:{x}": ("yaziyor", {"note": "p.md"}) for x in ("codex", "glm", "deepseek", "guvenlik")})
        self.assertFalse(out["incHakem"])
        self.assertEqual((out["hakem"]["poz"], out["hakem"]["etiket"], out["hakem"]["metin"]),
                         ("yaziyor", "Hakem (Sonnet)", "bulguları tartıyor"))
        self.assertTrue(out["hakem"]["yer"].startswith("uzmanlar-masa-"))
        self.assertTrue(all(v["poz"] not in ("yaziyor", "evde") for v in out["hakemAud"].values()))  # idle: any break
        self.assertEqual((out["kota"]["denetci:deepseek"]["poz"], out["kota"]["denetci:deepseek"]["metin"]),
                         ("evde", "Evde · kota doldu"))
        self.assertNotIn(out["kota"]["denetci:glm"]["poz"], ("yaziyor", "evde"))
        self.assertTrue(all(v["poz"] not in ("yaziyor", "evde") for v in out["yuk"].values()))
        self.assertFalse(out["yukHakem"])
        self.assertEqual(out["rows"][4:], [["codex", "calisiyor"], ["glm", "calisiyor"], ["deepseek", "calisiyor"],
                                           ["guvenlik", "calisiyor"]])
        self.assertIn("hakem", out["table"])

    def test_the_page_builds_one_desk_per_auditor_and_colours_them(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("denetciListesi(state.modeller)", "{ max_running_per_project: per, denetciler }",
                     "#${denetciler.join(',')}"):
            self.assertIn(name, app)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("denetciRenk(fam)", scene)
        self.assertIn("s.denetim = d.denetim", (WEB / "demo.js").read_text(encoding="utf-8"))


# --- the approval card's risk and open security finding; the security reviewer; the auditors' labels ---

@unittest.skipUnless(NODE, "node is not installed")
class CardRiskAndSecurityTest(unittest.TestCase):
    def test_the_risk_badge_and_the_security_warning_are_plain_text(self):
        out = run_js("""[t.kararIsaretleri({risk: 'yuksek', guvenlik_acik: true}), t.kararIsaretleri({risk: 'dusuk'}),
          t.kararIsaretleri({risk: 'normal'}), t.kararIsaretleri({risk: '<b>x</b>', guvenlik_acik: 'evet'}),
          t.kararIsaretleri(null)]""")
        self.assertEqual(out[0], {"risk": {"metin": "Risk: yüksek", "sinif": "risk-yuksek"},
                                  "uyari": "Açık güvenlik bulgusu var — bu haliyle onaylanmamalı"})
        self.assertEqual(out[1], {"risk": {"metin": "Risk: düşük", "sinif": "risk-dusuk"}, "uyari": ""})
        self.assertEqual(out[2], {"risk": {"metin": "Risk: normal", "sinif": "risk-normal"}, "uyari": ""})
        self.assertEqual(out[3], {"risk": None, "uyari": ""})  # only the server's exact values
        self.assertEqual(out[4], {"risk": None, "uyari": ""})

    def test_the_card_shows_them_and_keeps_approve_clickable_but_secondary(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        body = app[app.index("function syncAsks("):app.index("function renderAsks(")]
        for name in ("kararIsaretleri(d)", "card.parts.risk.textContent", "card.parts.warn.textContent",
                     "card.parts.yes.classList.toggle('is-secondary', !!isaret.uyari)"):
            self.assertIn(name, body)
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("yes.disabled = !!", body)  # The owner decides: never disabled for it
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for name in (".ask-risk.risk-yuksek", ".ask-risk.risk-dusuk", ".ask-warn", ".btn.is-secondary"):
            self.assertIn(name, css)

    def test_a_review_md_proposal_is_a_card_like_a_claude_md_one(self):
        # both are pending Kararlar notes with evidence; the page draws every pending decision the same way
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("'claude-md-onerisi'", app)  # no kind-specific branch that would leave the new kind out


@unittest.skipUnless(NODE, "node is not installed")
class SecurityReviewerTest(unittest.TestCase):
    ROW = "{model: 'guvenlik', unvan: 'Güvenlik denetçisi', ajan_modeli: 'sonnet', calisan: 0, durum: 'hazir'}"

    def test_its_desk_comes_last_and_it_is_never_free(self):
        out = run_panel(f"""[d.denetciListesi([{self.ROW}, CODEX, ...FREE]), d.ucretsizDenetciMi({self.ROW}),
          d.ucretsizDenetciMi({{model: 'guvenlik', unvan: 'Dış denetçi'}}), d.denetciListesi(['guvenlik', 'glm'])]""")
        self.assertEqual(out, [["codex", "glm", "deepseek", "guvenlik"], False, False, ["codex", "glm", "guvenlik"]])

    def test_it_types_at_its_desk_only_while_it_runs(self):
        out = run_panel(f"""(() => {{ const m = [CODEX, ...FREE, {self.ROW}];
          const at = (x) => one(run(st({{modeller: m, tasks: [rev()], ...x}})), 'denetci:guvenlik');
          const busy = at({{denetim: {{is: 'p.md', denetciler: ['codex', 'guvenlik'], hakem: ''}}}});
          return [{{...pick(busy), unvan: busy.unvan, ucretsiz: busy.ucretsiz}}, at({{}}),
            at({{denetim: {{is: 'p.md', denetciler: ['codex'], hakem: ''}}}}),
            pick(one(run(st({{modeller: [CODEX, {{...{self.ROW}, durum: 'calisiyor', calisan: 1}}]}})), 'denetci:guvenlik')),
            one(run(st({{modeller: [CODEX, {{...{self.ROW}, durum: 'calisiyor', calisan: 0}}]}})), 'denetci:guvenlik')]; }})()""")
        self.assertEqual(out[0], {"yer": "denetci-masa-guvenlik", "poz": "yaziyor", "simge": None,
                                  "metin": "inceliyor · yayin", "etiket": "IT güvenlik uzmanı",
                                  "tiklama": {"note": "p.md"}, "ucretsiz": False, "unvan": "Güvenlik denetçisi"})
        self.assertIsNone(out[1])
        self.assertIsNone(out[2])
        self.assertEqual(out[3]["poz"], "yaziyor")  # an older server: its own row says so
        self.assertIsNone(out[4])  # its row mirrors Sonnet's "calisiyor": that alone never means it runs

    def test_its_model_row_and_table_row(self):
        out = run_scene(f"""[h.modelSatirlari([{self.ROW}, {{model: 'glm', unvan: 'Dış denetçi', durum: 'hazir'}}], NOW)
            .slice(5).map((r) => [r.model, r.ad, r.metin, r.ucretsiz]),
          h.calisanlarTablosu(st({{denetim: {{is: 'q.md', denetciler: ['guvenlik'], hakem: ''}}, modeller: [{self.ROW}]}}), NOW)
            .map((r) => [r.id, r.unvan, r.harcama]), h.denetciRenk('guvenlik')]""")
        self.assertEqual(out[0], [["glm", "GLM", "GLM · ücretsiz · hazır", True],
                                  ["guvenlik", "Güvenlik denetçisi (Sonnet)", "Güvenlik denetçisi (Sonnet) · hazır",
                                   False]])
        self.assertEqual(out[1], [["denetci:guvenlik", "Güvenlik denetçisi", "—"]])
        self.assertNotIn(out[2]["shell"], {"#C9E4DE", "#F6DCCB", "#D6DCF5", "#DEEBFA"})

    def test_quiet_actors_get_a_small_name_only_label_until_hovered_or_zoomed(self):
        out = run_panel("""(() => { const idle = run(panel({tasks: []}), NOW, null, {hafif: true});
          const busy = run(panel({denetim: {is: 'p.md', denetciler: ['glm'], hakem: ''}}), NOW, null, {hafif: true});
          const l = (a, o = {}) => { const x = h.etiketBilgisi(a, {yakin: false, ...o}); return [x.ad, x.durum, x.kompakt]; };
          return { kadro: l(one(idle, 'kadro:opus')), kadroHover: l(one(idle, 'kadro:opus'), {uzerinde: true}),
            kadroNear: l(one(idle, 'kadro:opus'), {yakin: true}), codex: l(one(idle, 'denetci:codex')),
            glmBusy: l(one(busy, 'denetci:glm')), ceo: l(one(idle, 'ceo'))[2] }; })()""")
        self.assertEqual(out["kadro"], ["Kıdemli", "", True])  # role only on the floor
        # (no opus row in this state: honestly "durumu bilinmiyor")
        self.assertEqual(out["kadroHover"], ["Kıdemli", "durumu bilinmiyor", False])
        self.assertEqual(out["kadroNear"], ["Kıdemli", "durumu bilinmiyor", False])
        self.assertEqual(out["codex"], ["Codex", "", True])
        self.assertEqual(out["glmBusy"], ["GLM", "inceliyor · yayin", False])  # at work: full
        self.assertFalse(out["ceo"])
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertNotIn("etiket_yukseklik", scene)  # labels sit right above their robot
        self.assertIn("{ max: 48 }", scene)  # a label stays next to its robot; a crowd folds into "+N"
        self.assertIn(".desk-label.is-compact", (WEB / "style.css").read_text(encoding="utf-8"))
        self.assertIn("if (first || still || a.denetci ||", scene)  # an auditor appears at its desk, not via the lift


# --- the resident staff (kadro), the CEO's round, the guard and the secretary, the tea corner, room names ---

@unittest.skipUnless(NODE, "node is not installed")
class KadroTest(unittest.TestCase):
    def kadro(self, expr):
        return run_dav(f"run({expr}).filter((a) => a.kadro).map((a) => [a.id, a.yer, a.poz, a.simge, a.etiket, "
                       "a.durum_metni, a.tiklama, a.devral || null])")

    def test_idle_staff_wait_in_the_lounge_one_per_claude_model(self):
        out = run_dav("""run(st({modeller: ['haiku', 'sonnet', 'opus', 'fable', 'codex'].map((m) => ({model: m,
          durum: 'hazir'}))}), NOW, null, {hafif: true}).filter((a) => a.kadro).map((a) => [a.id, a.yer, a.poz,
          a.etiket, a.durum_metni, a.tiklama, a.tur])""")
        self.assertEqual(out, [
            ["kadro:haiku", "ortak-alan-haiku", "bekliyor", "Stajyer (Haiku)", "hazır · iş bekliyor", None, "ajan"],
            ["kadro:sonnet", "ortak-alan-sonnet", "bekliyor", "Uzman (Sonnet)", "hazır · iş bekliyor", None, "ajan"],
            ["kadro:opus", "ortak-alan-opus", "bekliyor", "Kıdemli (Opus)", "hazır · iş bekliyor", None, "ajan"],
            ["kadro:fable", "mudur-odasi-masa", "bekliyor", "Genel Müdür (Fable)", "hazır · iş bekliyor", None, "ajan"]])

    def test_quota_error_and_unknown_follow_the_model_row_only(self):
        out = run_dav("""(() => { const k = (m) => one(run(st({modeller: [m]}), NOW, null, {hafif: true}), 'kadro:opus');
          return [k({model: 'opus', durum: 'kota', donus: '2026-11-11T16:30+03:00'}), k({model: 'opus', durum: 'kota'}),
            k({model: 'opus', durum: 'hata'}), k({model: 'opus', durum: 'bilinmiyor'}), k({model: 'opus', durum: 'kotaa'}),
            k(null)].map((a) => [a.yer, a.poz, a.simge, a.durum_metni]); })()""")
        self.assertEqual(out, [["ortak-alan-opus", "evde", None, "Evde · 16:30'da döner"],
                               ["ortak-alan-opus", "evde", None, "Evde · kota doldu"],
                               ["ortak-alan-opus", "bekliyor", "kirmizi", "son çağrı hata verdi"],
                               ["ortak-alan-opus", "bekliyor", None, "durumu bilinmiyor"],
                               ["ortak-alan-opus", "bekliyor", None, "durumu bilinmiyor"],
                               ["ortak-alan-opus", "bekliyor", None, "durumu bilinmiyor"]])

    def test_lunch_in_the_canteen_and_idle_life_never_in_hafif(self):
        out = run_dav("""(() => { const s = st({modeller: [{model: 'opus', durum: 'hazir'}]});
          const lunch = one(run(s, yemekAni('kadro:opus')), 'kadro:opus');
          const ticks = Array.from({length: 40}, (_, i) => one(run(s, NOW + i * 45000), 'kadro:opus'));
          const light = Array.from({length: 40}, (_, i) => one(run(s, NOW + i * 45000, null, {hafif: true}), 'kadro:opus'));
          return { lunch: [lunch.yer.slice(0, 18), lunch.poz], away: ticks.filter((a) => a.yer !== 'ortak-alan-opus').length,
            seated: ticks.filter((a) => a.yer === 'ortak-alan-opus').length, light: light.every((a) => a.yer === 'ortak-alan-opus') }; })()""")
        self.assertEqual(out["lunch"], ["yemekhane-sandalye", "yemek"])
        self.assertTrue(0 < out["away"] < 30, out)  # breaks (tea, games, a walk), resting at its seat stays common
        self.assertGreater(out["seated"], 10)
        self.assertTrue(out["light"])

    def test_the_kadro_walks_to_the_new_job_and_back_to_the_lounge(self):
        out = run_dav("""(() => { const idle = run(st({modeller: [{model: 'opus', durum: 'hazir'}]}), NOW, null, {hafif: true});
          const start = run(working(), NOW + 2000, idle, {hafif: true});
          const next = run(working(), NOW + 4000, start, {hafif: true});
          const done = (age, prev) => run(st({tasks: [task('a.md', 'bitti', {session: 'ofis-w-1', finished: iso(NOW + 6000 - age)})]}),
            NOW + 6000, prev, {hafif: true});
          const party = done(10000, next), back = done(45000, party);
          return { start: [one(start, 'kadro:opus'), one(start, 'is:a').devral, one(start, 'is:a').yer],
            next: one(next, 'is:a').devral || null, party: [one(party, 'is:a').poz, !!one(party, 'kadro:opus')],
            back: [one(back, 'is:a'), one(back, 'kadro:opus').yer, one(back, 'kadro:opus').devral] }; })()""")
        self.assertEqual(out["start"], [None, "kadro:opus", "ekip-yayin-masa-1"])  # its body walks from the lounge
        self.assertIsNone(out["next"])
        self.assertEqual(out["party"], ["kutluyor", False])  # still at the desk: no kadro yet
        self.assertEqual(out["back"], [None, "ortak-alan-opus", "is:a"])  # walks back from the desk as the kadro

    def test_two_concurrent_jobs_of_one_model_one_takes_the_kadro_the_other_comes_by_lift(self):
        out = run_dav("""(() => { const idle = run(st(), NOW, null, {hafif: true});
          const two = st({sessions: [ses('s1', 'busy', {note: 'a.md'}), ses('s2', 'busy', {note: 'b.md'})],
            tasks: [task('a.md', 'calisiyor', {session: 's1'}), task('b.md', 'calisiyor', {session: 's2'})]});
          const r = run(two, NOW + 2000, idle, {hafif: true});
          return [one(r, 'is:a').devral || null, one(r, 'is:b').devral || null, one(r, 'kadro:opus')]; })()""")
        self.assertEqual(out, ["kadro:opus", None, None])

    def test_an_idle_session_of_the_model_is_its_presence_and_auditors_and_the_ceo_are_no_kadro(self):
        out = run_dav("""(() => { const r = run(st({sessions: [ses('x', 'idle', {model: 'opus'})], modeller: [
          {model: 'codex', unvan: 'Dış denetçi', durum: 'hazir'}]}), NOW, null, {hafif: true});
          return r.filter((a) => a.kadro).map((a) => a.id); })()""")
        self.assertEqual(out, ["kadro:haiku", "kadro:sonnet", "kadro:fable"])

    def test_a_queued_job_does_not_take_the_kadro_away(self):
        out = run_dav("""one(run(st({tasks: [task('q.md', 'sirada', {queue_position: 1})]}), NOW, null, {hafif: true}),
          'kadro:opus').yer""")
        self.assertEqual(out, "ortak-alan-opus")


@unittest.skipUnless(NODE, "node is not installed")
class CeoRoundAndStaffTest(unittest.TestCase):
    def test_the_free_ceo_splits_its_time_between_desk_rounds_breaks_and_sleep(self):
        # The owner, 2026-11-12: not asleep all the time; a seeded split of about 30 / 25 / 25 / 20 percent
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin', 'blog']);
          const ticks = Array.from({length: 480}, (_, i) => NOW + i * 15000);  // 2 hours, every 15 s
          const kind = (a) => a.yer === 'ceo-masa' ? 'masa' : a.poz === 'yatiyor' ? 'uyku' : a.poz === 'yuruyor' &&
            a.durum_metni === 'ofisi dolaşıyor' ? 'tur' : 'mola';
          const day = (ceo, o = {}) => ticks.map((t) => one(run(st({projects: [{name: 'yayin'}, {name: 'blog'}], ceo}), t, null, o), 'ceo'));
          const count = (l) => l.map(kind).reduce((m, k) => ({ ...m, [k]: (m[k] || 0) + 1 }), {});
          const dormant = day({state: 'dormant'}), idle = day({state: 'idle'});
          const stops = [...new Set(dormant.filter((a) => kind(a) === 'tur').map((a) => a.yer))].sort();
          const breaks = [...new Set(dormant.filter((a) => kind(a) === 'mola').map((a) => a.durum_metni))].sort();
          const at = (ceo, x = {}, o = {}) => ticks.map((t) => one(run(st({ceo, ...x}), t, null, o), 'ceo'));
          return { dormant: count(dormant), idle: count(idle), stops, breaks,
            busy: [...new Set(at({state: 'busy'}).map((a) => a.yer + '|' + a.poz))],
            waiting: [...new Set(at({state: 'waiting'}).map((a) => a.yer))],
            dec: [...new Set(at({state: 'dormant'}, {decisions: [{note: 'k.md'}]}).map((a) => a.yer))],
            queue: [...new Set(at({state: 'idle', queue: 1}).map((a) => a.yer))],
            helper: [...new Set(at({state: 'idle', alt_ajanlar: [{id: 'h', model: 'haiku', bitti: false}]}).map((a) => a.yer))],
            hafifIdle: [...new Set(at({state: 'idle'}, {}, {hafif: true}).map((a) => a.yer))],
            hafifDormant: [...new Set(at({state: 'dormant'}, {}, {hafif: true}).map((a) => a.yer))],
            same: d.ceoPlani(NOW, P).tur === d.ceoPlani(NOW, P).tur, turu: d.ceoTuru(NOW, P) === (d.ceoPlani(NOW, P).durak || null) }; })()""")
        n = 480
        for k in ("masa", "tur", "mola"):
            self.assertGreater(out["dormant"].get(k, 0), 0, (k, out["dormant"]))
        # The owner, 2026-11-16: by day in the office hours (10:00-12:00 here, no lunch) it never sleeps: its sleep share is
        # a break
        self.assertNotIn("uyku", out["dormant"])
        self.assertGreaterEqual(out["dormant"]["mola"], 0.25 * n)
        self.assertGreaterEqual(out["dormant"]["tur"], 0.1 * n)  # rounds are frequent now
        self.assertNotIn("uyku", out["idle"])  # sleep only when dormant
        self.assertIn("ceo-kapi", out["stops"])
        self.assertTrue({"denetci-kapi", "uzmanlar-kapi"} & set(out["stops"]), out["stops"])
        self.assertTrue(any(s.startswith("ekip-") for s in out["stops"]))
        self.assertTrue(out["breaks"], out["breaks"])
        self.assertEqual(out["busy"], ["ceo-masa|yaziyor"])  # real state first: never leaves its desk
        self.assertEqual(out["waiting"], ["ceo-masa"])
        self.assertEqual(out["dec"], ["ceo-masa"])  # a decision for the owner: at its desk
        self.assertEqual(out["queue"], ["ceo-masa"])
        self.assertEqual(out["helper"], ["ceo-masa"])
        self.assertEqual(out["hafifIdle"], ["ceo-masa"])  # hafif: simple
        # hafif keeps the same plan without the walking breaks and rounds: the desk (no bed by day)
        self.assertEqual(sorted(out["hafifDormant"]), ["ceo-masa"])
        self.assertTrue(out["same"] and out["turu"])

    def test_the_guard_and_the_secretary_are_decoration_tied_to_real_state(self):
        out = run_dav("""(() => { const pick = (a) => a && [a.tur, a.yer, a.poz, a.simge, a.etiket, a.durum_metni, a.tiklama];
          const quiet = run(st());
          const dec = Array.from({length: 30}, (_, i) => one(run(st({decisions: [{note: 'x.md'}, {note: 'y.md'}]}),
            NOW + i * 20000), 'sus:sekreter')); // no previous tick: nothing new, so no trip
          return { guard: pick(one(quiet, 'sus:guvenlik')), sek: pick(one(quiet, 'sus:sekreter')),
            busy: pick(dec.find((a) => a.yer === 'lobi-resepsiyon')), trips: dec.filter((a) => a.yer === 'ceo-kapi').length,
            paper: dec.every((a) => a.dosya && a.simge === '?' && a.durum_metni === "Selin'e 2 soru bekliyor"),
            hafif: run(st({decisions: [{note: 'x.md'}]}), NOW, null, {hafif: true}).filter((a) => a.tur === 'sus' && !d.BILGI_PERSONELI(a))
              .map((a) => [a.id, a.yer]).sort() };
          })()""")
        self.assertEqual(out["guard"], ["sus", "lobi-nobet", "bekliyor", None, "Güvenlik görevlisi", "girişte", None])
        self.assertEqual(out["sek"], ["sus", "lobi-resepsiyon", "bekliyor", None, "Sekreter", "resepsiyonda", None])
        self.assertEqual(out["busy"], ["sus", "lobi-resepsiyon", "bekliyor", "?", "Sekreter", "Selin'e 2 soru bekliyor", None])
        self.assertEqual(out["trips"], 0)
        self.assertTrue(out["paper"])
        # hafif (owner decision 2026-11-12): the duty staff stand still at their posts; no tea server
        self.assertEqual(out["hafif"], [["sus:guvenlik", "lobi-nobet"], ["sus:sekreter", "lobi-resepsiyon"]])
        # decoration never takes a label from an agent
        self.assertEqual(run_scene("""[...h.etiketSecimi([{id: 'sus:sekreter', tur: 'sus', simge: '?'},
          {id: 'is:a', tur: 'ajan', poz: 'bekliyor'}], 1)]"""), ["is:a"])


@unittest.skipUnless(NODE, "node is not installed")
class TeaCornerAndRoomNamesTest(unittest.TestCase):
    def test_idle_agents_sit_around_two_round_tables_and_the_lounge_has_a_seat_per_model(self):
        out = run_scene("""(() => { const p = d.ofisPlani(['yayin']); const n = p.dugumler;
          const seats = Array.from({length: 6}, (_, i) => n['cay-ocagi-yer-' + i]);
          const faces = seats.map((x) => { const a = h.yuzAcisi(p, x.id); const t = Math.atan2(x.hedef[0] - x.x, x.hedef[1] - x.z);
            return Math.abs(a - t) < 1e-9; });
          const dist = seats.map((x) => +Math.hypot(x.x - x.hedef[0], x.z - x.hedef[1]).toFixed(2));
          const lounge = ['haiku', 'sonnet', 'opus'].map((f) => n['ortak-alan-' + f]);
          const tea = p.odalar.find((r) => r.id === 'ortak-alan'); const lobby = p.odalar.find((r) => r.id === 'lobi');
          let gap = 99; for (const a of lounge) for (const b of lounge) if (a !== b) gap = Math.min(gap, Math.hypot(a.x - b.x, a.z - b.z));
          const inside = (x, r) => x.x > r.x + 0.4 && x.x < r.x + r.w - 0.4 && x.z > r.z + 0.4 && x.z < r.z + r.d - 0.4;
          return { tur: [...new Set(seats.map((x) => x.tur))], faces, dist, tables: p.cay_masalari.length,
            sit: [h.oturmaYeri(p, 'cay-ocagi-yer-0'), h.oturmaYeri(p, 'ortak-alan-opus'), h.oturmaYeri(p, 'lobi-resepsiyon'),
              h.oturmaYeri(p, 'lobi-nobet')],
            lounge: lounge.map((x) => [x.tur, x.oda, inside(x, tea)]),
            lobby: ['lobi-nobet', 'lobi-resepsiyon'].map((id) => inside(n[id], lobby)), gap }; })()""")
        self.assertEqual(out["tur"], ["tabure"])
        self.assertTrue(all(out["faces"]))
        self.assertEqual(out["dist"], [1.2] * 6)
        self.assertEqual(out["tables"], 3)
        self.assertEqual(out["sit"], [True, True, True, False])
        self.assertEqual(out["lounge"], [["bekleme", "ortak-alan", True]] * 3)  # a lounge room of its own
        self.assertGreaterEqual(out["gap"], 4.5)  # each kadro at its own seat with real spacing
        self.assertEqual(out["lobby"], [True, True])

    def test_room_names_are_plain_text_at_each_rooms_front_corner(self):
        out = run_scene("""(() => { const p = d.ofisPlani(['yayin', '<b>x</b>']); return h.odaEtiketleri(p); })()""")
        names = [r["ad"] for r in out]
        self.assertEqual(names, ["Toplantı odası", "CEO odası", "Dış denetçiler", "Genel Müdür odası", "Uzmanlar odası", "Oyun odası",
                                 "Dinlenme odası", "Çay ocağı", "Ortak alan", "Yemekhane", "Muhasebe", "İdari işler",
                                 "İnsan kaynakları", "Revir", "Psikolog", "Masaj odası", "Sunucu odası", "Ar-Ge odası", "Sosyal medya ve tasarım",
                                 "Sosyal medya ve tasarım · stüdyo", "Spor salonu", "Duş", "WC", "Konferans salonu",
                                 "Yazılım Müdürü odası", "IT Müdürü odası", "QA Müdürü odası", "Analist Müdürü odası",
                                 "QA odası", "Analist odası",
                                 "yayin ekibi", "<b>x</b> ekibi"] + ["Boş ekip alanı · yeni proje"] * 5 +
                         ["Giriş", "Sigara odası", "Otel"])  # the Otel outside the floor (owner decision 2026-11-14)
        for r in out:
            self.assertEqual(set(r), {"id", "ad", "x", "z"})

    def test_a_room_name_hides_under_an_actor_label_never_the_other_way(self):
        out = run_scene("""[h.odaEtiketiGorunur({x: 100, y: 100, w: 80, h: 16}, [{x: 110, y: 104, w: 90, h: 20}]),
          h.odaEtiketiGorunur({x: 100, y: 100, w: 80, h: 16}, [{x: 400, y: 100, w: 90, h: 20}]),
          h.odaEtiketiGorunur({x: 100, y: 100, w: 80, h: 16}, [{x: 110, y: 104, w: 90, h: 20, gizli: true}])]""")
        self.assertEqual(out, [False, True, True])



@unittest.skipUnless(NODE, "node is not installed")
class DemoKadroTest(unittest.TestCase):
    def test_the_demo_starts_with_the_mudur_in_the_lounge_who_walks_to_its_desk(self):
        out = run_scene(f"""(() => {{ {DEMO_JS} let prev = null; const at = {{}};
          for (let t = 0; t <= bas('calisma') + 1; t++) {{ prev = sahne(t, prev); at[t] = prev; }}
          const k = one(at[2], 'kadro:fable'), c = one(at[bas('calisma')], 'is:c');
          return [k.yer, k.etiket, !!one(at[bas('calisma')], 'kadro:fable'), c.devral, c.masa]; }})()""")
        self.assertEqual(out[1:4], ["Genel Müdür (Fable)", False, "kadro:fable"])  # (idle: wherever its break took it)
        # the same body walks to the planning desk of the Yazılım Müdürü's office (plan "Sonraki iş (9)": atolye's plan)
        self.assertEqual(out[4], "yazilim-plan-masa")



class GreetingAndFloorWiringTest(unittest.TestCase):
    def test_the_greeting_folds_into_a_pill_and_remembers_the_choice(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for name in ("SELAM_KEY", "setTimeout(() => fold(true), 6000)", "classList.toggle('is-compact', compact)",
                     "try { window.localStorage.setItem(SELAM_KEY"):
            self.assertIn(name, app)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".greeting.is-compact p { display: none; }", css)

    def test_the_floor_has_a_perimeter_wall_room_names_and_a_steeper_camera(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        for name in ("buildPerimeter(plan)", "const KAMERA = [40, 46, 40]", "odaEtiketleri(plan)", "odaEtiketiGorunur(rect, items)",
                     "el.textContent = r.ad", "a.devral", "gozetle(v)", "makeStool()", "makeRoundTable()", "makeReception()"):
            self.assertIn(name, scene)
        self.assertNotIn("this.textPlate(team ? r.proje : r.ad", scene)  # no tiny floor text any more
        tints = re.search(r"const ROOM_TINT = \{(.*?)\};", scene, re.S).group(1)
        colours = re.findall(r"'(#[0-9A-F]{6})'", tints)
        # + the wing's facilities, the terrace, the Dinlenme odası, the Konferans salonu, the Sunucu odası, the Ar-Ge odası,
        # the managers' offices, the QA odası, the Analist odası
        self.assertEqual(len(colours), 28)
        self.assertEqual(len(set(colours)), 28)  # every area its own floor colour (the Uzmanlar odası too)
        base = re.search(r"const BASE_FLOOR = '(#[0-9A-F]{6})'", scene).group(1)
        lum = lambda c: sum(int(c[i:i + 2], 16) for i in (1, 3, 5))  # noqa: E731
        self.assertTrue(all(lum(base) < lum(c) for c in colours), "the corridors are darker than every room")
        self.assertIn("r.tur === 'mudur'", scene)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn("pointer-events: none", css[css.index(".room-label {"):css.index(".room-label {") + 200])



@unittest.skipUnless(NODE, "node is not installed")
class LabelGroupTest(unittest.TestCase):
    def test_each_group_has_its_own_label_class(self):
        out = run_panel("""(() => { const acts = run(panel({denetim: {is: 'p.md', denetciler: [], hakem: 'sonnet'}}), NOW);
          const g = (id) => h.etiketBilgisi(one(acts, id)).grup;
          return [g('ceo'), g('kadro:opus'), g('denetci:codex'), g('denetci:glm'), g('hakem'), g('sus:cayci'), g('sus:sekreter'),
            g('sus:guvenlik'), h.etiketGrubu({tur: 'ozet'}), h.etiketGrubu({tur: 'alt-ajan'}),
            h.etiketGrubu(one(run(working()), 'is:a'))]; })()""")
        self.assertEqual(out, ["grup-ajan", "grup-ajan", "grup-denetci", "grup-denetci", "grup-denetci", "grup-personel",
                               "grup-personel", "grup-personel", "", "grup-ajan", "grup-ajan"])

    def test_the_classes_the_room_style_and_the_legend(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("info.grup ? ` ${info.grup}`", scene)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for name in (".desk-label.grup-ajan", ".desk-label.grup-denetci", ".desk-label.grup-personel", ".etiket-lejant",
                     "@media (max-width: 600px) { .etiket-lejant { display: none; } }"):
            self.assertIn(name, css)
        page = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertRegex(page, r'<details class="etiket-lejant" id="etiket-lejant">\s*<summary data-t="Etiket renkleri">Etiket renkleri</summary>')
        for text in ("Yapay zekâ çalışanları", "Denetçiler", "Ofis personeli", "Oda adları"):
            self.assertIn(text, page)



class StackingTest(unittest.TestCase):
    """The scene's labels never paint over a panel: a z-index scale in CSS tokens, the labels layer is its own
    stacking context below the tab panels, and an open tab panel hides the labels and the legend (no placement)."""

    def test_a_z_index_scale_and_no_bare_numbers(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        scale = dict(re.findall(r"--z-([a-z]+): (\d+);", css))
        self.assertEqual({k: int(v) for k, v in scale.items()},
                         {"scene": 0, "labels": 1, "hud": 5, "overlay": 15, "header": 20, "scrim": 30, "modal": 40, "toast": 50})
        # every positioned layer uses the scale (label children inside the labels' own stacking context excepted)
        bare = [m for m in re.findall(r"z-index: (\d+)", css)]
        self.assertTrue(set(bare) <= {"0", "1"}, bare)
        self.assertRegex(css, r"\.labels \{[^}]*z-index: var\(--z-labels\)")
        self.assertRegex(css, r"\.overlay \{[^}]*z-index: var\(--z-overlay\)")
        self.assertIn("body.panel-acik .labels, body.panel-acik .etiket-lejant { visibility: hidden; }", css)

    def test_an_open_panel_hides_the_labels_and_skips_their_placement(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        body = app[app.index("function setTab(tab)"):app.index("if (tab === 'raporlar') loadReports();")]
        self.assertIn("document.body.classList.toggle('panel-acik', tab !== 'ofis')", body)
        self.assertIn("office.setLabelsHidden(tab !== 'ofis')", body)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("if (!this.labelsHidden) this.placeLabels();", scene)



@unittest.skipUnless(NODE, "node is not installed")
class ReviewFixesPageRoundTest(unittest.TestCase):
    """Independent review of the page round (minors): one test per finding."""

    def test_1_answered_decisions_do_not_send_the_secretary_or_the_tea_server(self):
        out = run_dav("""(() => { const at = (dec) => Array.from({length: 30}, (_, i) => run(st({decisions: dec}), NOW + i * 20000));
          const sent = at([{note: 'x.md', answer_sent: true}]), open = at([{note: 'x.md', answer_sent: true}, {note: 'y.md'}]);
          const sek = (r) => one(r, 'sus:sekreter'), cay = (r) => one(r, 'sus:cayci');
          return { sentSek: sent.map(sek).filter((a) => a.simge || a.yer === 'ceo-kapi').length,
            sentCay: sent.map(cay).filter((a) => a.yer === 'ceo-kapi').length,
            openText: [...new Set(open.map(sek).map((a) => a.durum_metni))] }; })()""")
        self.assertEqual((out["sentSek"], out["sentCay"]), (0, 0))
        self.assertEqual(out["openText"], ["Selin'e 1 soru bekliyor"])

    def test_2_the_demo_security_row_is_never_working_while_idle(self):
        out = run_scene("""(() => { const bad = []; for (let t = 0; t < demo.DEMO_SURE; t++) {
            const x = demo.demoDurumu(t, NOW + t * 1000); const g = x.modeller.find((m) => m.model === 'guvenlik');
            if (g.calisan === 0 && g.durum === 'calisiyor') bad.push(t); } return bad; })()""")
        self.assertEqual(out, [])

    def test_3_only_the_fable_family_works_in_the_mudur_office(self):
        out = run_dav("""(() => { const r = run(st({sessions: [ses('s1', 'busy', {note: 'a.md'})], tasks: [task('a.md', 'calisiyor',
            {session: 's1', model: 'opus', tier: 'planlama'})], modeller: [{model: 'fable', durum: 'hazir'}],
            sahne: { ...st().sahne, mola: 'dinlenme' }}));
          return [one(r, 'is:a').masa, one(r, 'kadro:fable').yer]; })()""")
        # planning work (any model) at the Yazılım Müdürü's planning desk; no two robots on the Genel Müdür's desk
        self.assertEqual(out, ["yazilim-plan-masa", "mudur-odasi-masa"])
        # defensive: whoever sits at the Müdür desk, the idle fable kadro never shares it
        out = run_dav("""d.ofisPlani(['yayin']).dugumler['ortak-alan-fable'].oda""")
        self.assertEqual(out, "ortak-alan")

    def test_4_a_hakem_or_security_call_is_its_model_family_at_work(self):
        out = run_panel("""(() => { const m = [CODEX, ...FREE, {model: 'sonnet', durum: 'hazir'},
            {model: 'guvenlik', unvan: 'Güvenlik denetçisi', ajan_modeli: 'sonnet', calisan: 0, durum: 'hazir'}];
          const s = (denetim) => st({modeller: m, tasks: [rev()], denetim});
          const idle = run(s(null), NOW, null, {hafif: true});
          const hk = run(s({is: 'p.md', denetciler: [], hakem: 'sonnet'}), NOW + 2000, idle, {hafif: true});
          const back = run(s(null), NOW + 4000, hk, {hafif: true});
          const sec = run(s({is: 'p.md', denetciler: ['codex', 'guvenlik'], hakem: ''}), NOW + 6000, back, {hafif: true});
          const both = run(s({is: 'p.md', denetciler: ['guvenlik'], hakem: 'sonnet'}), NOW + 8000, back, {hafif: true});
          return { idle: !!one(idle, 'kadro:sonnet'), hk: [!!one(hk, 'kadro:sonnet'), one(hk, 'hakem').devral || null],
            back: [one(back, 'kadro:sonnet').yer, one(back, 'kadro:sonnet').devral || null, one(back, 'hakem')],
            sec: [!!one(sec, 'kadro:sonnet'), one(sec, 'denetci:guvenlik').devral || null],
            both: [one(both, 'denetci:guvenlik').devral || null, one(both, 'hakem').devral || null] }; })()""")
        self.assertTrue(out["idle"])
        self.assertEqual(out["hk"], [False, "kadro:sonnet"])  # the lounge's Uzman walks in as the hakem
        self.assertEqual(out["back"], ["ortak-alan-sonnet", "hakem", None])  # and walks back to the lounge after
        self.assertEqual(out["sec"], [False, "kadro:sonnet"])
        self.assertEqual(sorted(x or "" for x in out["both"]), ["", "kadro:sonnet"])  # one takes the kadro, one by lift

    def test_5_the_greeting_and_the_legend_share_one_column(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertRegex(page, r'<div class="hud-sol">\s*<section class="card greeting"[\s\S]*?</section>\s*'
                               r'<details class="etiket-lejant" id="etiket-lejant">')
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.hud-sol \{[^}]*display: flex; flex-direction: column;")
        self.assertRegex(css, r"\.hud-sol \.greeting, \.hud-sol \.etiket-lejant \{[^}]*position: static;")


# --- moving around the floor like a map (the owner, 2026-11-12: zoomed in, the rest of the office was out of reach) ---

@unittest.skipUnless(NODE, "node is not installed")
class MapPanTest(unittest.TestCase):
    def test_left_drag_and_one_finger_pan_right_drag_rotates(self):
        self.assertEqual(run_scene("[h.FARE_DUGMELERI, h.DOKUNMA]"),
                         [{"LEFT": "PAN", "MIDDLE": "DOLLY", "RIGHT": "ROTATE"}, {"ONE": "PAN", "TWO": "DOLLY_ROTATE"}])
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        for text in ("c.mouseButtons = { LEFT: THREE.MOUSE[FARE_DUGMELERI.LEFT]", "RIGHT: THREE.MOUSE[FARE_DUGMELERI.RIGHT]",
                     "c.touches = { ONE: THREE.TOUCH[DOKUNMA.ONE], TWO: THREE.TOUCH[DOKUNMA.TWO] }",
                     "c.screenSpacePanning = false;", "e.altKey && e.button === 0 ? 'ROTATE'", "{ capture: true }",
                     "style.cursor = 'grabbing'"):
            self.assertIn(text, scene)
        # the click, the re-fit stop and the label forwarding stay
        self.assertRegex(scene, r">= 5\) this\.userMoved = true")
        self.assertRegex(scene, r"< 5\) \{")
        self.assertIn("canvas.dispatchEvent(new PointerEvent('pointerdown', e))", scene)

    def test_the_target_is_clamped_to_the_real_floor_bounds_not_around_the_origin(self):
        # a floor whose wing reaches far right of the origin: its far corner must be reachable
        out = run_scene("""(() => { const b = { minX: -10, maxX: 60, minZ: -5, maxZ: 25 };
          return [h.hedefiSinirla(58, 24, b), h.hedefiSinirla(100, -40, b), h.hedefiSinirla(-30, 30, b, 0),
                  h.hedefiSinirla(3, 4, null), h.hedefiSinirla(3, 4, { minX: NaN }), h.hedefSiniri(b, 2)]; })()""")
        self.assertEqual(out, [{"x": 58, "z": 24}, {"x": 61.5, "z": -6.5}, {"x": -10, "z": 25}, {"x": 3, "z": 4},
                               {"x": 3, "z": 4}, {"minX": -12, "maxX": 62, "minZ": -7, "maxZ": 27}])
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        clamp = scene[scene.index("  clampTarget() {"):]
        clamp = clamp[:clamp.index("\n  }\n")]
        self.assertIn("hedefiSinirla(t.x, t.z, this.bounds)", clamp)
        self.assertNotIn("extent", clamp)
        self.assertIn("this.camera.position.x += dx", clamp)  # the camera moves with the target: no tilt at the edge

    def test_arrow_keys_and_wasd_pan_with_the_zoom_keys_guard(self):
        out = run_scene("""[['ArrowLeft'], ['ArrowRight'], ['ArrowUp'], ['ArrowDown'], ['w'], ['A'], ['s'], ['d'],
          ['x'], ['ArrowLeft', {ctrlKey: true}], ['ArrowLeft', {altKey: true}], ['ArrowLeft', {metaKey: true}],
          ['w', {target: {tagName: 'input'}}], ['w', {target: {tagName: 'TEXTAREA'}}],
          ['w', {target: {tagName: 'DIV', isContentEditable: true}}],
          ['ArrowRight', {target: {tagName: 'BUTTON', getAttribute: () => 'tab'}}],
          ['ArrowRight', {target: {tagName: 'BUTTON', getAttribute: () => null}}],
          ['ö', {code: 'KeyW'}]].map(([key, o]) => h.kaydirmaTusu({ key, ...(o || {}) }))""")
        self.assertEqual(out, [[-1, 0], [1, 0], [0, 1], [0, -1], [0, 1], [-1, 0], [0, -1], [1, 0],
                               None, None, None, None, None, None, None, None, [1, 0], [0, 1]])
        self.assertEqual(run_scene("[h.kaydirmaAdimi(20, 1), h.kaydirmaAdimi(20, 4), h.kaydirmaAdimi(0, 0)]"),
                         [10, 2.5, 5])
        app = (WEB / "app.js").read_text(encoding="utf-8")
        # review 2026-11-12: the pan keys only on the page itself or the scene, never in the side panel's scroll area
        self.assertIn("const yon = ne || !sahneHedefi(e.target) ? null : kaydirmaTusu(e);", app)
        guard = app[app.index("function sahneHedefi("):]
        guard = guard[:guard.index("\n}\n")]
        for text in ("t === document.body", "t === document.documentElement", "$('scene').contains(t)"):
            self.assertIn(text, guard)
        for text in ( "if ((!ne && !yon) || document.body.classList.contains('panel-acik')",
                     "!$('calisanlar').hidden || komutaOpen()) return;", "else office.kaydir(yon[0], yon[1]);"):
            self.assertIn(text, app)
        self.assertIn("kaydir(sag, ileri) {", (WEB / "scene.js").read_text(encoding="utf-8"))

    def test_a_one_time_hint_is_dismissable_remembered_and_hidden_on_phones(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        hint = app[app.index("function kaydirIpucu() {"):]
        hint = hint[:hint.index("\n}\n")]
        for text in ("Sürükle ya da iki parmakla kaydır · Sıkıştırarak yakınlaştır · Sağ tık ya da ↺ ↻: döndür",
                     "localStorage.getItem(KEY) === '1'",
                     "localStorage.setItem(KEY, '1')", "try {", "box.remove()"):
            self.assertIn(text, hint)
        self.assertNotRegex(hint, r"innerHTML")
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"@media \(max-width: 820px\), \(hover: none\) \{ \.kaydir-ipucu \{ display: none; \} \}")
        self.assertIn("body.panel-acik .kaydir-ipucu { visibility: hidden; }", css)


# --- the trackpad: pinch zooms the scene (never the page), two fingers pan, a mouse wheel steps (owner decision 2026-11-12) ---

@unittest.skipUnless(NODE, "node is not installed")
class WheelTest(unittest.TestCase):
    def test_wheel_kind_tells_a_pinch_a_two_finger_scroll_and_a_mouse_wheel_apart(self):
        out = run_scene("""[
          {ctrlKey: true, deltaY: 2.5, deltaMode: 0}, {ctrlKey: true, deltaY: -7, deltaMode: 0},
          {ctrlKey: true, deltaY: 100, deltaMode: 0}, {ctrlKey: true, deltaY: 3, deltaMode: 1},
          {deltaY: 4.5, deltaMode: 0}, {deltaX: 12, deltaY: 0, deltaMode: 0}, {deltaX: 3, deltaY: 100, deltaMode: 0},
          {deltaY: 7, deltaMode: 0}, {deltaY: 100, deltaMode: 0}, {deltaY: -120, deltaMode: 0},
          {deltaY: 3, deltaMode: 1}, {deltaY: -1, deltaMode: 2}, {deltaY: 0, deltaX: 0}, null,
        ].map((e) => h.tekerlekTuru(e))""")
        self.assertEqual(out, ["pinch", "pinch", "yakinlastir", "yakinlastir", "kaydir", "kaydir", "kaydir",
                               "kaydir", "yakinlastir", "yakinlastir", "yakinlastir", "yakinlastir", None, None])

    def test_pinch_zoom_is_exponential_clamped_and_takes_the_fit_to_about_twice_in_one_pinch(self):
        out = run_scene("""({
          one: h.pinchZoom(1, -10, 0.5, 4), out: h.pinchZoom(1, 10, 0.5, 4),
          sym: h.pinchZoom(h.pinchZoom(1, -6, 0.1, 10), 6, 0.1, 10),
          max: h.pinchZoom(3.9, -50, 0.5, 4), min: h.pinchZoom(0.55, 50, 0.5, 4), jump: h.pinchZoom(1, -1000, 0.01, 1e9),
          // a comfortable macOS Chromium pinch: ~25 events of deltaY -2 (60 Hz, under half a second)
          gesture: Array.from({length: 25}).reduce((z) => h.pinchZoom(z, -2, 0.1, 10), 1),
          wheelIn: h.tekerZoom(1, -100, 0.5, 4), wheelOut: h.tekerZoom(1, 3, 0.5, 4), wheelMax: h.tekerZoom(3.9, -100, 0.5, 4),
        })""")
        self.assertAlmostEqual(out["one"], 2.718281828 ** 0.15, places=6)
        self.assertAlmostEqual(out["out"], 2.718281828 ** -0.15, places=6)
        self.assertAlmostEqual(out["sym"], 1, places=9)
        self.assertEqual((out["max"], out["min"]), (4, 0.5))
        self.assertAlmostEqual(out["jump"], 2.718281828 ** 0.9, places=5)  # one event moves at most 60 units
        self.assertGreater(out["gesture"], 1.8)
        self.assertLess(out["gesture"], 2.6)
        self.assertAlmostEqual(out["wheelIn"], 1.2)
        self.assertAlmostEqual(out["wheelOut"], 1 / 1.2)
        self.assertEqual(out["wheelMax"], 4)

    def test_zoom_to_cursor_keeps_the_floor_point_under_the_pointer(self):
        # an orthographic camera: the floor point under a fixed pixel is target + A / zoom
        out = run_scene("""(() => {
          const A = [6, -4], T = [2, 3], z0 = 1.3, z1 = 2.9;
          const P = [T[0] + A[0] / z0, T[1] + A[1] / z0];
          const k = h.imlecZoomHedefi(T[0], T[1], P[0], P[1], z0, z1);
          return { after: [k.x + A[0] / z1, k.z + A[1] / z1], P, same: h.imlecZoomHedefi(2, 3, 9, 9, 1.5, 1.5),
                   bad: h.imlecZoomHedefi(2, 3, 9, 9, 0, 2), pan: h.tekerKaydirma(10, 20, 0.05), none: h.tekerKaydirma(5, 5, 0) };
        })()""")
        self.assertAlmostEqual(out["after"][0], out["P"][0])
        self.assertAlmostEqual(out["after"][1], out["P"][1])
        self.assertEqual(out["same"], {"x": 2, "z": 3})
        self.assertEqual(out["bad"], {"x": 2, "z": 3})
        self.assertEqual(out["pan"], [0.5, -1])
        self.assertEqual(out["none"], [0, 0])

    def test_the_scene_owns_the_wheel_and_pinch_over_the_scene_only(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("c.enableZoom = false;", scene)
        self.assertNotIn("zoomSpeed", scene)
        wheel = scene[scene.index("this.olayAlani.addEventListener('wheel'"):]
        wheel = wheel[:wheel.index("}, { passive: false, capture: true });")]
        for text in ("if (!this.sahneOlayi(e)) return;", "e.preventDefault();", "this.tekerlek(e);"):
            self.assertIn(text, wheel)
        for text in ("['gesturestart', 'gesturechange', 'gestureend']", "jestOlayi(tur, e) {",
                     "if (this.jest) return;", "this.olayAlani = host.parentElement || host;",
                     "const SAHNE_USTU = '.zoom-kontrol, .kaydir-ipucu, .demo-caption, .hud-sol';",
                     "imlecZoomHedefi(t.x, t.z, p.x, p.z, cam.zoom, z)", "tekerlekTuru(e)"):
            self.assertIn(text, scene)
        # the gesture listeners are non-passive too and prevent the page zoom
        gest = scene[scene.index("for (const tur of ['gesturestart'"):]
        gest = gest[:gest.index("}, { passive: false, capture: true });")]
        self.assertIn("e.preventDefault();", gest)
        # labels no longer forward the wheel (the stage's capture listener sees it once); touch pinch keeps OrbitControls
        self.assertNotIn("new WheelEvent('wheel', e)", scene)
        self.assertIn("if (e.pointerType === 'touch' || e.button === 1) { dokunmalar.add(e.pointerId); c.enableZoom = true; }",
                      scene)
        self.assertIn("if (!dokunmalar.size) c.enableZoom = false;", scene)
        # the side panel, overlays and dialogs are outside the scene: sahneOlayi only takes the scene, labels and HUD
        own = scene[scene.index("  sahneOlayi(e) {"):]
        own = own[:own.index("\n  }\n")]
        for text in ("this.host.contains(t) || this.labelHost.contains(t)", "t.closest(SAHNE_USTU)",
                     "!this.olayAlani.contains(t)"):
            self.assertIn(text, own)


# --- clicking any character opens a small info card (ofis-sahne.js karakterKarti; owner decision 2026-11-12) ---

KART_PRELUDE = r"""
const kart = (a, s) => h.karakterKarti(a, s, NOW);
const by = (k) => Object.fromEntries((k.satirlar || []).map((r) => [r.ad, r.metin]));
const actorOf = (s, id) => one(run(s), id);
"""


@unittest.skipUnless(NODE, "node is not installed")
class CharacterCardTest(unittest.TestCase):
    def card(self, expr):
        return run_scene(expr, KART_PRELUDE)

    def test_a_working_job_shows_its_job_spending_and_an_open_job_action(self):
        out = self.card("""(() => { const s = working({ title: 'Giriş hatası', spent: '0.41', tokens: '182000', budget: 3,
            step: '3', step_kind: 'kod', workflow: 'akis-1' },
          { alt_ajanlar: [{ id: 'x1', model: 'haiku', gorev: 'testleri çalıştır', bitti: false }] });
          const k = kart(actorOf(s, 'is:a'), s); return { k, r: by(k) }; })()""")
        k, r = out["k"], out["r"]
        self.assertEqual(k["baslik"], "Kıdemli")
        self.assertEqual(r["Model"], "Opus")
        self.assertIn("yayin", k["alt"])
        self.assertEqual(r["İş"], "Giriş hatası")
        self.assertEqual(r["Adım"], "adım 3 · kod")
        self.assertEqual(r["Süre"], "10 dk")
        self.assertEqual(r["Kullanım"], "182 bin token · ≈$0,41 / ≈$3,00")
        # review 2026-11-12: /api/state cannot tell whether a running job has a Kontrol or already failed one
        self.assertNotIn("Kontrol", r)
        self.assertEqual(r["Yardımcılar"], "1 yardımcı (Haiku)")
        self.assertEqual(k["eylemler"], [{"tur": "is", "metin": "İşi aç", "note": "a.md"}])

    def test_a_job_in_kontrol_says_so(self):
        r = self.card("""(() => { const s = st({ tasks: [task('k.md', 'kontrolde')] });
          return by(kart({ id: 'is:k', tur: 'ajan', unvan: 'Kıdemli', model: 'opus', proje: 'yayin',
            durum_metni: 'Kontrol çalışıyor', tiklama: { note: 'k.md' } }, s)); })()""")
        self.assertEqual(r["Kontrol"], "sunucu şu an çalıştırıyor")

    def test_an_idle_kadro_shows_its_role_last_job_and_today(self):
        out = self.card("""(() => { const s = st({ today: '2026-11-11',
            modeller: [{ model: 'opus', durum: 'hazir' }],
            tasks: [task('b.md', 'bitti', { title: 'Eski iş', finished: iso(NOW - 3600000), started: iso(NOW - 7200000),
                       spent: '0.80', tokens: '182400' }),
                    task('c.md', 'tikandi', { title: 'Dünkü iş', started: '2026-11-10T09:00:00',
                       finished: '2026-11-10T10:00:00', spent: '1' }),
                    task('d.md', 'bitti', { title: 'Haiku işi', model: 'haiku', finished: iso(NOW - 60000) })] });
          const k = kart(actorOf(s, 'kadro:opus'), s); return { k, r: by(k) }; })()""")
        k, r = out["k"], out["r"]
        self.assertEqual(k["baslik"], "Kıdemli")
        self.assertEqual(r["Model"], "Opus")
        self.assertEqual(r["Görevi"], "kod yazma ve hata düzeltme, inceleme")
        self.assertEqual(r["Model durumu"], "hazır")  # the model's row, not this character's own state
        self.assertNotIn("Durum", r)
        self.assertEqual(r["Son işi"], "Eski iş · bitti · bugün 09:00 · 182 bin token · ≈$0,80")
        self.assertEqual(r["Bugün"], "1 iş · 182 bin token · ≈$0,80")
        self.assertEqual(k["eylemler"], [{"tur": "is", "metin": "İşi aç", "note": "b.md"}])

    def test_each_kadro_role_has_its_line_and_quota_says_when_it_returns(self):
        out = self.card("""(() => { const s = st({ modeller: [{ model: 'haiku', durum: 'kota',
            donus: '2026-11-11T16:30:00+03:00' }, { model: 'sonnet', durum: 'hazir' }, { model: 'fable', durum: 'hata',
            son_hata: 'x' }] });
          return ['haiku', 'sonnet', 'fable'].map((f) => by(kart({ id: `kadro:${f}`, tur: 'ajan', kadro: true,
            unvan: d.UNVAN[f].unvan, model: f, etiket: 'x', durum_metni: '' }, s))); })()""")
        self.assertEqual(out[0]["Görevi"], "kolay işler: test çalıştırma, durum kontrolü, biçimlendirme")
        self.assertEqual(out[0]["Model durumu"], "kota doldu · 16:30'da döner")
        self.assertNotIn("Son işi", out[0])  # nothing claimed without a finished job
        self.assertEqual(out[1]["Görevi"], "okuma, özetleme, araştırma")
        self.assertEqual(out[2]["Görevi"], "büyük işleri planlama, mimari")
        self.assertEqual(out[2]["Model durumu"], "hata: x")

    def test_a_helper_shows_its_task_and_its_parent_job(self):
        out = self.card("""(() => { const s = working({ title: 'Giriş hatası' },
            { alt_ajanlar: [{ id: 'x1', model: 'haiku', gorev: 'Tüm birim testlerini çalıştır ve sonucu yaz', bitti: false }] });
          const a = run(s).find((x) => x.tur === 'alt-ajan'); const k = kart(a, s); return { k, r: by(k) }; })()""")
        k, r = out["k"], out["r"]
        self.assertEqual(k["baslik"], "Yardımcı · Stajyer")
        self.assertEqual(r["Model"], "Haiku")
        self.assertEqual(r["Görevi"], "Tüm birim testlerini çalıştır ve sonucu yaz")
        self.assertEqual(r["Ana iş"], "Giriş hatası")
        self.assertEqual(k["eylemler"], [{"tur": "is", "metin": "Ana işi aç", "note": "a.md"}])

    def test_auditors_and_the_hakem_describe_their_role(self):
        out = self.card("""(() => { const s = st({ modeller: [{ model: 'codex', durum: 'hazir' },
            { model: 'glm', durum: 'hazir', ucretsiz: true, tur: 'opencode' }],
            tasks: [task('r.md', 'bitti', { title: 'Kod incelemesi: giriş', inceleme_yurutucu: 'codex',
              finished: iso(NOW - 600000), step_kind: 'kod-inceleme' })] });
          const codex = kart({ id: 'denetci:codex', tur: 'ajan', denetci: true, model: 'codex', unvan: 'Dış denetçi',
            etiket: 'Codex · Dış denetçi', durum_metni: 'hazır' }, s);
          const glm = kart({ id: 'denetci:glm', tur: 'ajan', denetci: true, ucretsiz: true, model: 'glm',
            unvan: 'Dış denetçi', etiket: 'GLM', durum_metni: 'inceliyor · yayin', tiklama: { note: 'r.md' } }, s);
          const hakem = kart({ id: 'hakem', tur: 'ajan', hakem: true, model: 'sonnet', unvan: 'Uzman',
            etiket: 'Hakem (Sonnet)', durum_metni: 'bulguları tartıyor', tiklama: { note: 'r.md' } }, s);
          return [codex, by(codex), glm, by(glm), hakem, by(hakem)]; })()""")
        codex, rc, glm, rg, hakem, rh = out
        self.assertEqual(codex["baslik"], "Codex")
        self.assertIn("kod incelemesi", rc["Görevi"])
        self.assertEqual(rc["Durum"], "hazır")
        self.assertEqual(rc["Son incelemesi"], "Kod incelemesi: giriş · bitti · bugün 09:50")
        self.assertEqual(rc["Karnesi"], "Obsidian'da Karne/Denetciler")
        self.assertEqual(codex["eylemler"], [])
        self.assertIn("ücretsiz", rg["Görevi"])
        self.assertEqual(rg["İncelediği iş"], "Kod incelemesi: giriş")
        self.assertEqual(glm["eylemler"], [{"tur": "is", "metin": "İşi aç", "note": "r.md"}])
        self.assertEqual(hakem["baslik"], "Hakem")
        self.assertEqual(rh["Model"], "Sonnet")
        self.assertIn("bulgu", rh["Görevi"])

    def test_the_ceo_card_shows_its_tool_queue_and_opens_the_command_desk(self):
        out = self.card("""(() => { const s = st({ ceo: { state: 'busy', current_tool: 'Bash', queue: 2,
            cost_today: 1.5, usage_today: 250000 } });
          const k = kart(actorOf(s, 'ceo'), s); return { k, r: by(k) }; })()""")
        k, r = out["k"], out["r"]
        self.assertEqual(k["baslik"], "CEO")
        self.assertEqual(r["Şu an"], "Bash")
        self.assertEqual(r["Sırada"], "2 mesaj")
        self.assertEqual(r["Bugün"], "250 bin token · ≈$1,50")
        self.assertEqual(k["eylemler"], [{"tur": "komuta", "metin": "Komuta masasını aç"}])

    def test_decoration_staff_get_a_friendly_line_and_the_secretary_counts_decisions(self):
        out = self.card("""(() => { const s = st({ decisions: [{ note: 'k1.md' }, { note: 'k2.md', answer_sent: true },
            { note: 'k3.md' }] });
          const list = run(s);
          return ['sus:cayci', 'sus:guvenlik', 'sus:sekreter'].map((id) => kart(one(list, id), s))
            .concat([kart(one(run(st()), 'sus:sekreter'), st())]); })()""")
        cay, guv, sek, sek0 = out
        self.assertEqual(cay["baslik"], "Çaycı")
        self.assertTrue(cay["satirlar"] and cay["eylemler"] == [])
        self.assertEqual(guv["baslik"], "Güvenlik görevlisi")
        self.assertIn({"ad": "Bekleyen", "metin": "Selin'e 2 soru bekliyor"}, sek["satirlar"])
        self.assertEqual(sek["eylemler"], [{"tur": "karar", "metin": "k1", "note": "k1.md"},
                                           {"tur": "karar", "metin": "k3", "note": "k3.md"}])
        self.assertEqual(sek0["eylemler"], [])
        self.assertIn({"ad": "Bekleyen", "metin": "Selin'i bekleyen soru yok"}, sek0["satirlar"])

    def test_a_summary_actor_lists_the_hidden_ones(self):
        out = self.card("""(() => { const s = st({ projects: [{ name: 'yayin' }],
            tasks: Array.from({ length: 6 }, (_, i) => task(`t${i}.md`, 'calisiyor', { title: `İş ${i}` })) });
          const list = run(s, NOW, null, { max_running_per_project: 1 });
          const o = list.find((a) => a.tur === 'ozet');
          return o ? h.karakterKarti(o, s, NOW, { aktorler: list }) : null; })()""")
        self.assertIsNotNone(out)
        self.assertTrue(out["baslik"].startswith("+"))
        n = int(out["baslik"][1:])
        self.assertEqual(len(out["satirlar"]), n)  # one line per hidden job, none of the drawn ones
        for r in out["satirlar"]:
            self.assertTrue(r["ad"] and r["metin"].startswith("İş "))

    def test_the_team_summary_card_lists_exactly_the_engines_hidden_jobs(self):
        # review 2026-11-12: the card used to recompute the team's hidden jobs from the state and could list jobs drawn
        # elsewhere (a Codex review, the CEO-door queue); the engine's own `left` list is passed as gizliler
        out = self.card("""(() => { const s = st({ projects: [{ name: 'yayin' }],
            tasks: Array.from({ length: 6 }, (_, i) => task(`t${i}.md`, 'calisiyor', { title: `İş ${i}` })) });
          const list = run(s, NOW, null, { max_running_per_project: 1 });
          const o = list.find((a) => a.id === 'ozet:ekip-yayin');
          const only = { ...o, gizliler: o.gizliler.slice(0, 1) };
          return { n: Number(o.etiket.slice(1)), g: o.gizliler, k: h.karakterKarti(only, s, NOW, { aktorler: [] }) }; })()""")
        self.assertEqual(len(out["g"]), out["n"])
        self.assertTrue(all(g["note"].startswith("t") for g in out["g"]))
        # only the engine's list counts, even when the card is given no drawn actors
        self.assertEqual(len(out["k"]["satirlar"]), 1)
        self.assertTrue(out["k"]["satirlar"][0]["metin"].startswith("İş "))

    def test_the_open_card_is_rebuilt_only_when_it_changes(self):
        # review 2026-11-12: rebuilding every second lost button clicks and reset the focus
        app = (WEB / "app.js").read_text(encoding="utf-8")
        kart = app[app.index("function kartGoster("):]
        kart = kart[:kart.index("\n}\n")]
        # the card's content and (NPC chat, 2026-11-18) whether its question box shows
        self.assertIn("const anahtar = JSON.stringify([k, npcSohbetRolu(a) && npcSohbetKutusu(state, DEMO)]);", kart)
        self.assertIn("if (el && !place && kart.anahtar === anahtar && !el.hidden) return;", kart)
        self.assertIn("kart.anahtar = anahtar;", kart)

    def test_every_text_is_a_plain_string_and_a_missing_actor_is_safe(self):
        out = self.card("[h.karakterKarti(null, null, NOW), h.karakterKarti({ id: 'x', tur: 'ajan' }, {}, NOW)]")
        for k in out:
            self.assertIsInstance(k["baslik"], str)
            self.assertIsInstance(k["satirlar"], list)
            self.assertIsInstance(k["eylemler"], list)

    def test_the_page_opens_the_card_for_every_character(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertNotIn("v.a.tur !== 'sus' && v.a.tur !== 'ozet') this.onActor", scene)
        self.assertIn("this.onActor(v.a, { x: e.clientX, y: e.clientY })", scene)
        self.assertIn("onActor: (a, at) => openActor(a, at)", (WEB / "app.js").read_text(encoding="utf-8"))
        app = (WEB / "app.js").read_text(encoding="utf-8")
        kart = app[app.index("function kartGoster("):]
        kart = kart[:kart.index("\n}\n")]
        self.assertIn("karakterKarti(a, state, Date.now(), { aktorler: prevActors, veri: kartVeri })", kart)
        self.assertNotIn("openDetail(", app[app.index("function openActor("):app.index("function kartKapat(")])
        self.assertNotRegex(app[app.index("function kartGoster("):], r"innerHTML")
        for text in ("e.key === 'Escape' && kart", "kartKapat()", "openDetail({ kind: 'task', note: x.note })",
                     "openKomuta(", "setTab('kararlar')"):
            self.assertIn(text, app)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.karakter-kart \{[^}]*z-index: var\(--z-overlay\)")
        # the decoration (Çaycı, Sekreter, Güvenlik görevlisi): body and label open their card (owner decision 2026-11-12)
        self.assertNotRegex(css, r"\.desk-label\.is-sus[^{]*\{[^}]*pointer-events: none")
        self.assertIn(".desk-label { pointer-events: auto; cursor: pointer;", css)
        for fn in ("actorAt(e) {", "pick(e) {"):
            body = scene[scene.index(fn):]
            body = body[:body.index("\n  }\n")]
            self.assertNotIn("'sus'", body)  # picking never skips a decoration actor
            self.assertIn("o.userData.aktor", body)
        spawn = scene[scene.index("  spawn(a) {"):]
        self.assertIn("root.userData.aktor = a.id;", spawn[:200])
        label = scene[scene.index("    if (hasLabel && !v.label) {"):]
        label = label[:label.index("    } else if (!hasLabel && v.label) {")]
        self.assertNotIn("sus", label)
        self.assertIn("this.labelDown = id;", label)
        cards = self.card("""['sus:cayci', 'sus:sekreter', 'sus:guvenlik'].map((id) => one(run(st({})), id))
          .map((a) => h.karakterKarti(a, st({}), NOW).baslik)""")
        self.assertEqual(cards, ["Çaycı", "Sekreter", "Güvenlik görevlisi"])
        self.assertIn("body.panel-acik .karakter-kart { display: none; }", css)


# --- role first; the model only in the character card / tooltip (owner decision 2026-11-12) ---

@unittest.skipUnless(NODE, "node is not installed")
class RoleOnlyWordingTest(unittest.TestCase):
    def test_floor_labels_show_the_role_without_the_model(self):
        out = run_scene("""[['yayin · Kıdemli (Opus)', 'ajan'], ['Müdür (Fable)', 'ajan'], ['Hakem (Sonnet)', 'ajan'],
          ['Güvenlik denetçisi (Sonnet)', 'ajan'], ['Yardımcı · Stajyer (Haiku)', 'alt-ajan'], ['2 yardımcı (Haiku)', 'ozet'],
          ['GLM · Dış denetçi (ücretsiz)', 'ajan'], ['Codex · Dış denetçi', 'ajan'], ['CEO', 'ceo']]
          .map(([etiket, tur]) => h.etiketBilgisi({ id: 'x', tur, etiket, durum_metni: '', poz: 'yaziyor' }).ad)""")
        self.assertEqual(out, ["yayin · Kıdemli", "Müdür", "Hakem", "Güvenlik denetçisi", "Yardımcı Stajyer",
                               "2 yardımcı", "GLM · Dış denetçi (ücretsiz)", "Codex · Dış denetçi", "CEO"])
        self.assertEqual(run_scene("[h.rolAdi('Uzman (sonnet)'), h.rolAdi('x (ücretsiz)'), h.rolAdi(null)]"),
                         ["Uzman", "x (ücretsiz)", ""])
        # the compact label too
        self.assertEqual(run_scene("""h.etiketBilgisi({ id: 'k', tur: 'ajan', etiket: 'Kıdemli (Opus)',
          kisa_etiket: 'Kıdemli (Opus)', durum_metni: 'hazır', poz: 'bekliyor' }, { yakin: false }).ad"""), "Kıdemli")

    def test_the_side_panel_and_board_show_the_role_and_the_model_as_a_tooltip(self):
        out = run_scene("""h.modelSatirlari([{ model: 'opus', durum: 'hazir' }, { model: 'codex', durum: 'hazir' },
          { model: 'glm', durum: 'hazir', unvan: 'Dış denetçi' },
          { model: 'guvenlik', durum: 'hazir', ajan_modeli: 'sonnet', unvan: 'Güvenlik denetçisi' }], NOW,
          { saat_dilimi: 'Europe/Istanbul' }).filter((r) => ['opus', 'codex', 'glm', 'guvenlik'].includes(r.model))
          .map((r) => [r.model, r.rol, r.rol_metin, r.ipucu])""")
        self.assertEqual(out[0], ["opus", "Kıdemli", "Kıdemli · hazır", "Kıdemli · model: Opus"])
        self.assertEqual(out[1], ["codex", "Codex", "Codex · hazır", "Codex · Dış denetçi"])  # the role in the tooltip
        self.assertEqual(out[2][1:3], ["GLM", "GLM · ücretsiz · hazır"])
        self.assertEqual(out[3][1:], ["Güvenlik denetçisi", "Güvenlik denetçisi · hazır",
                                      "Güvenlik denetçisi · model: Sonnet"])
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("h('span', null, r.rol_metin)", app)
        self.assertIn("li.title = r.ipucu", app)

    def test_the_popover_list_shows_the_role_and_the_model_for_claude_workers(self):
        # The owner, 2026-11-12: "Uzman · Sonnet" in the popover's list; the reviewers by their name; floor labels stay role-only
        out = run_scene("""h.modelSatirlari([{ model: 'haiku', durum: 'hazir' }, { model: 'sonnet', durum: 'hazir' },
          { model: 'opus', durum: 'hazir' }, { model: 'fable', durum: 'hazir' }, { model: 'codex', durum: 'hazir' },
          { model: 'glm', durum: 'hazir', unvan: 'Dış denetçi' }, { model: 'deepseek', durum: 'hazir', unvan: 'Dış denetçi' },
          { model: 'guvenlik', durum: 'hazir', ajan_modeli: 'sonnet', unvan: 'Güvenlik denetçisi' }], NOW,
          { saat_dilimi: 'Europe/Istanbul' }).map((r) => r.pano_ad)""")
        self.assertEqual(out, ["Stajyer · Haiku", "Uzman · Sonnet", "Kıdemli · Opus", "Genel Müdür · Fable", "Codex", "GLM",
                               "DeepSeek", "Güvenlik denetçisi · Sonnet"])

    def test_the_card_names_the_model(self):
        out = run_scene("""(() => { const s = st({ modeller: [{ model: 'opus', durum: 'hazir' }] });
          const k = h.karakterKarti(one(run(s), 'kadro:opus'), s, NOW);
          const w = working(); const kw = h.karakterKarti(one(run(w), 'is:a'), w, NOW);
          return [k.baslik, k.satirlar[0], kw.baslik, kw.satirlar[0]]; })()""")
        self.assertEqual(out[0], "Kıdemli")
        self.assertEqual(out[1], {"ad": "Model", "metin": "Opus"})
        self.assertEqual(out[2], "Kıdemli")
        self.assertEqual(out[3], {"ad": "Model", "metin": "Opus"})


@unittest.skipUnless(NODE, "node is not installed")
class RoleOnlyNowViewsTest(unittest.TestCase):
    def test_the_now_table_shows_the_role_and_the_model_as_a_tooltip(self):
        out = run_scene("""[h.calisanRolu('Kıdemli', 'opus'), h.calisanRolu('Dış denetçi', 'codex'), h.calisanRolu('Dış denetçi', 'glm'),
          h.calisanRolu('Hakem', 'sonnet'), h.calisanRolu('Güvenlik denetçisi', 'guvenlik'), h.calisanRolu('', ''),
          h.calisanIpucu('Kıdemli', 'opus'), h.calisanIpucu('Dış denetçi', 'codex'), h.calisanIpucu('Hakem', 'sonnet'),
          h.calisanHucreleri({ proje: 'p', is: 'i', unvan: 'Uzman', model: 'sonnet', katman: 'genel', durum: 'çalışıyor',
            sure: '1 dk', harcama: '—', yardimci: '2 yardımcı (Haiku)' })]""")
        self.assertEqual(out[:6], ["Kıdemli", "Codex", "GLM", "Hakem", "Güvenlik denetçisi", "—"])
        self.assertEqual(out[6:9], ["Kıdemli · model: Opus", "Codex", "Hakem · model: Sonnet"])
        self.assertEqual(out[9], ["p", "i", "Uzman", "genel", "çalışıyor", "1 dk", "—", "2 yardımcı"])
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("td.title = calisanIpucu(r.unvan, r.model)", app)
        self.assertIn("row.title = [it.calisan_ipucu", app)


@unittest.skipUnless(NODE, "node is not installed")
class FullRoomCardTest(unittest.TestCase):
    def test_a_full_common_room_card_lists_the_hidden_actors(self):
        out = run_scene("""(() => { const s = st({ projects: [{ name: 'yayin' }],
            sessions: Array.from({ length: 8 }, (_, i) => ses('r' + i, 'busy', { note: 'r' + i + '.md' })),
            tasks: Array.from({ length: 8 }, (_, i) => task('r' + i + '.md', 'calisiyor', { session: 'r' + i, tier: 'inceleme',
              title: 'İnceleme ' + i })) });
          const list = run(s); const o = list.find((a) => a.id === 'ozet:qa');
          return [o.gizliler.length, h.karakterKarti(o, s, NOW, { aktorler: list })]; })()""")
        n, k = out
        self.assertEqual(n, 4)  # eight reviews, the QA odası's four desks (plan "Sonraki iş (9)")
        self.assertEqual(k["baslik"], "+4")
        self.assertEqual(len(k["satirlar"]), 4)
        for r in k["satirlar"]:
            self.assertNotIn("(", r["ad"])  # role only
            self.assertTrue(r["metin"].startswith("inceliyor"))


class ZoomKeepsTheViewCentreTest(unittest.TestCase):
    def test_the_side_panel_offset_is_in_pixels_so_zooming_never_drifts_the_view_centre(self):
        # 2026-11-12: the asymmetric frustum (left/right in world units) moved the view centre left as the zoom grew,
        # so a zoomed-in view slid out of the visible area; a pixel view offset stays put at any zoom
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("this.camera.setViewOffset(w, h, this.inset / 2, 0, w, h)", scene)
        self.assertNotIn("right: (w - visible / 2) / ppu", scene)




# --- the three staff NPCs are useful (owner decision 2026-11-12): Sekreter, Güvenlik görevlisi, Çaycı ---

NPC_PRELUDE = KART_PRELUDE + r"""
const H = 3600000;
const card = (id, s, list) => { const l = list || run(s); return h.karakterKarti(one(l, id), s, NOW, { aktorler: l }); };
const rows = (k) => k.satirlar.map((r) => [r.ad, r.metin]);
"""


SAAT_SATIRLARI = ("Nöbette", "Nöbet bitişi", "Sonraki değişim", "Ekip", "Ofiste olanlar", "Otelde olanlar", "")


@unittest.skipUnless(NODE, "node is not installed")
class StaffCardsTest(unittest.TestCase):
    def card(self, expr):
        return run_scene(expr, NPC_PRELUDE)

    def test_the_secretary_lists_decisions_oldest_first_with_wait_and_risk_and_opens_each(self):
        k = self.card("""card('sus:sekreter', st({
            decisions: [{ note: 'b.md', title: 'Onay: CSV', asked: iso(NOW - 2 * H), risk: 'yuksek', kind: 'akis-onay' },
              { note: 'a.md', title: 'Renk paleti', asked: iso(NOW - 15 * 60000) },
              { note: 'c.md', title: 'Eski', asked: iso(NOW - 5 * H), answer_sent: true },
              { note: 'm.md', title: 'Kadro önerisi', asked: iso(NOW - 4 * 24 * H), kind: 'model-onerisi' }],
            summary: { tasks_today: 4, finished_today: 2 },
            schedules: [{ ad: 'sabah', proje: 'yayin', baslik: 'Sabah testleri', sonraki: iso(NOW + 26 * H) },
              { ad: 'oglen', proje: 'kasa', baslik: 'Öğlen', sonraki: iso(NOW + 3 * H) },
              { ad: 'dur', proje: 'kasa', baslik: 'Durdu', sonraki: '', duraklatildi: true }] }))""")
        self.assertEqual(k["alt"], "kararlar ve takvim")
        self.assertEqual(k["eylemler"], [
            {"tur": "karar", "metin": "Kadro önerisi · 4 gün", "note": "m.md"},
            {"tur": "karar", "metin": "Onay: CSV · 2 sa · yüksek risk", "note": "b.md"},
            {"tur": "karar", "metin": "Renk paleti · 15 dk", "note": "a.md"}])
        r = dict((a, m) for a, m in [(x["ad"], x["metin"]) for x in k["satirlar"]])
        self.assertEqual(r["Bekleyen"], "Selin'e 3 soru bekliyor")
        self.assertEqual(r["Bugün"], "4 iş başladı · 2 iş bitti")
        self.assertEqual(r["Sıradaki zamanlanmış iş"], "Öğlen · kasa · bugün 13:00")
        self.assertEqual(r["Duraklatılmış"], "1 zamanlanmış iş")
        self.assertEqual(r["Hatırlatma"], "Kadro önerisi · 4 gündür cevap bekliyor")

    def test_the_secretary_leaves_out_what_the_state_does_not_say(self):
        k = self.card("""card('sus:sekreter', st({ decisions: undefined }))""")
        ads = [r["ad"] for r in k["satirlar"]]
        # only Görevi and the shift rows (from the clock, always known; plan "Sonraki iş (8)")
        self.assertEqual([a for a in ads if a not in SAAT_SATIRLARI], ["Görevi"])
        self.assertEqual(k["eylemler"], [])
        # a decision without a readable time: no wait text, never "NaN"
        k = self.card("""card('sus:sekreter', st({ decisions: [{ note: 'x.md', title: 'X', asked: 'dün' }] }))""")
        self.assertEqual(k["eylemler"], [{"tur": "karar", "metin": "X", "note": "x.md"}])

    def test_the_guard_shows_arrivals_departures_headcount_security_and_delivery_warnings(self):
        k = self.card("""(() => { const s = st({
            sessions: [ses('ofis-w-1', 'busy', { job_status: 'calisiyor', model: 'opus', note: 'a.md' })],
            tasks: [task('a.md', 'calisiyor', { session: 'ofis-w-1', title: 'Giriş', started: iso(NOW - H) }),
              task('b.md', 'bitti', { title: 'Rapor', started: iso(NOW - 3 * H), finished: iso(NOW - 2 * H) }),
              task('c.md', 'bitti', { title: 'Dün', started: iso(NOW - 30 * H), finished: iso(NOW - 26 * H) })],
            modeller: [{ model: 'codex', unvan: 'Dış denetçi', durum: 'hazir' }],
            decisions: [{ note: 'k.md', title: 'Onay: giriş', asked: iso(NOW - H), risk: 'yuksek', guvenlik_acik: true },
              { note: 'n.md', title: 'Normal', risk: 'normal' }],
            postoffice: { rejected: 1, rejected_outbox: 0, sessions: {}, silent: [], last_error: null } });
          return card('sus:guvenlik', s); })()""")
        self.assertEqual(k["alt"], "giriş-çıkış ve güvenlik")
        got = [[r["ad"], r["metin"]] for r in k["satirlar"]]
        self.assertEqual(got[1:4], [["Giriş 09:00", "yayin · Giriş"], ["Çıkış 08:00", "yayin · Rapor"],
                                    ["Giriş 07:00", "yayin · Rapor"]])
        r = dict((a, m) for a, m in got)
        # everyone in the office (owner decision 2026-11-16), the same number as "Ofiste olanlar"
        m = re.match(r"^(\d+) kişi: 1 çalışıyor, (\d+) nöbette, (\d+) diğer$", r["Ofiste şimdi"])
        self.assertIsNotNone(m, r["Ofiste şimdi"])
        self.assertEqual(r["Ofiste olanlar"], f"{m.group(1)} kişi")
        self.assertEqual(int(m.group(1)), 1 + int(m.group(2)) + int(m.group(3)))
        self.assertEqual(r["Güvenlik"], "1 açık güvenlik bulgusu")
        self.assertEqual(r["İletişim uyarıları"], "1 proje raporu kabul edilmedi")  # the reason is not known
        self.assertEqual(k["eylemler"], [{"tur": "karar", "metin": "Onay: giriş · 1 sa · açık güvenlik bulgusu · yüksek risk",
                                          "note": "k.md"}])

    def test_the_guard_omits_lines_without_data(self):
        out = self.card("""(() => { const s = st({ decisions: undefined });
          return [h.karakterKarti(one(run(s), 'sus:guvenlik'), s, NOW), card('sus:guvenlik', st())]; })()""")
        # no actors, decisions, postoffice: only Görevi and what the clock says (the shift, who is in / at home)
        self.assertEqual([r["ad"] for r in out[0]["satirlar"] if r["ad"] not in SAAT_SATIRLARI], ["Görevi"])
        r = {x["ad"]: x["metin"] for x in out[1]["satirlar"]}
        self.assertEqual(r["Güvenlik"], "açık güvenlik bulgusu yok, yüksek riskli kart yok")
        self.assertNotIn("İletişim uyarıları", r)
        self.assertFalse(any(a.startswith(("Giriş ", "Çıkış ")) for a in r))

    def test_the_tea_server_shows_breaks_the_longest_worker_lunch_and_top_spenders(self):
        k = self.card("""(() => { const s = st({
            sessions: [ses('ofis-w-1', 'busy', { job_status: 'calisiyor', model: 'opus', note: 'a.md' }),
              ses('ofis-w-2', 'busy', { job_status: 'calisiyor', model: 'sonnet', note: 'b.md', project: 'yayin' })],
            tasks: [task('a.md', 'calisiyor', { session: 'ofis-w-1', title: 'Giriş', started: iso(NOW - 130 * 60000), spent: '1.2', tokens: '400000' }),
              task('b.md', 'calisiyor', { session: 'ofis-w-2', model: 'sonnet', tier: 'genel', title: 'Özet', started: iso(NOW - 20 * 60000), spent: '0.05' }),
              task('c.md', 'bitti', { title: 'Rapor', started: iso(NOW - 3 * H), finished: iso(NOW - 2 * H), spent: '2.5', tokens: '' }),
              task('d.md', 'bitti', { title: 'Dün', started: iso(NOW - 30 * H), finished: iso(NOW - 26 * H), spent: '9' })],
            ceo: { state: 'idle' } });
          return card('sus:cayci', s); })()""")
        self.assertEqual(k["alt"], "molalar")
        got = [[r["ad"], r["metin"]] for r in k["satirlar"]]
        r = dict(got)
        self.assertIn("Molada", [a for a, _ in got])
        self.assertEqual(r["En uzun çalışan"], "Kıdemli (Opus) · 2 sa 10 dk masasında · yayin · Giriş")
        self.assertEqual(r["Öğle arası"], "öğle arası 2 sa sonra")
        i = [a for a, _ in got].index("Bugün en çok kullanan")
        self.assertEqual([m for _, m in got[i:i + 3]], ["Rapor · ≈$2,50", "Giriş · 400 bin token · ≈$1,20", "Özet · ≈$0,05"])
        self.assertEqual(k["eylemler"], [])

    def test_the_tea_server_card_without_data_and_the_lunch_text(self):
        out = self.card("""[h.karakterKarti(one(run(st()), 'sus:cayci'), st(), NOW).satirlar.map((r) => r.ad),
          h.ogleMetni(LUNCH, {}), h.ogleMetni(NOW + 105 * 60000, {}), h.ogleMetni(NOW + 4 * H, {}), h.ogleMetni(NaN, {}),
          h.bekleyisMetni(NOW - 3 * 24 * H, NOW), h.bekleyisMetni(NOW + 2 * H, NOW)]""")
        self.assertEqual(out[0], ["Görevi", "Öğle arası"])
        self.assertEqual(out[1:], ["şu an öğle arası", "öğle arası 15 dk sonra", "bugünkü öğle arası bitti", "", "3 gün", ""])


@unittest.skipUnless(NODE, "node is not installed")
class StaffBehaviourTest(unittest.TestCase):
    def test_the_secretary_walks_once_per_new_decision(self):
        out = run_dav("""(() => { const dec = (n) => Array.from({length: n}, (_, i) => ({ note: `k${i}.md` }));
          let prev = run(st({ decisions: dec(1) }), NOW);
          const seq = [];
          const counts = [1, 1, ...Array(6).fill(2), ...Array(400).fill(4), 0];
          counts.forEach((n, i) => { prev = run(st({ decisions: dec(n) }), NOW + (i + 1) * 1000, prev);
            const s = one(prev, 'sus:sekreter'); seq.push(s.yer === 'ceo-kapi' ? 'K' : 'R'); });
          return seq.join(''); })()""")
        # one trip (the walk there and a moment at the door) for the 2nd decision, then two queued trips for the 3rd
        # and 4th (a note not seen before), each after the walk back
        self.assertEqual(out[:2], "RR")
        trips = [t for t in out.split("R") if t]
        self.assertEqual(len(trips), 3, out)
        self.assertEqual(out[-1], "R")  # nothing waits: back at reception

    def test_the_secretary_trip_helper_is_deterministic(self):
        out = run_dav("""(() => { const S = { ilk: 30000, gidis: 20000, donus: 20000 };
          const T = (bas, adet) => ({ bas, adet, ilk: 36000, gidis: 26000, donus: 20000 });
          return [d.sekreterTasimasi(null, ['a', 'b', 'c'], NOW, S), d.sekreterTasimasi({ karar_notlari: ['a'] }, ['a', 'b', 'c'], NOW, S),
          d.sekreterTasimasi({ karar_notlari: ['a', 'b', 'c'], tasima: T(NOW - 40000, 2) }, ['a', 'b', 'c'], NOW, S),
          d.sekreterTasimasi({ karar_notlari: ['a', 'b', 'c'], tasima: T(NOW - 200000, 2) }, ['a', 'b', 'c'], NOW, S),
          d.sekreterTasimasi({ karar_notlari: ['a'], tasima: T(NOW, 1) }, [], NOW, S),
          // one card answered and another asked in the same tick: the count stays, the new note still gets a trip
          d.sekreterTasimasi({ karar_notlari: ['a', 'b'] }, ['a', 'c'], NOW, S)]; })()""")
        self.assertEqual(out[0], {"tasima": None, "kapida": False})
        self.assertEqual(out[1], {"tasima": {"bas": out[1]["tasima"]["bas"], "adet": 2, "ilk": 36000, "gidis": 26000,
                                             "donus": 20000}, "kapida": True})
        self.assertEqual(out[2]["kapida"], False)  # between two trips: walking back to reception
        self.assertEqual(out[3], {"tasima": None, "kapida": False})
        self.assertEqual(out[4], {"tasima": None, "kapida": False})
        self.assertEqual((out[5]["tasima"]["adet"], out[5]["kapida"]), (1, True))

    def test_the_guard_steps_out_to_greet_an_arrival_and_goes_back(self):
        out = run_dav("""(() => {
          // the first opus job takes over the lounge's Kıdemli (a hand-over, not an arrival); the second comes by lift
          const two = () => { const s = working(); s.projects.push({ name: 'kasa' });
            s.sessions.push(ses('ofis-k-1', 'busy', { job_status: 'calisiyor', model: 'opus', note: 'b.md', project: 'kasa' }));
            s.tasks.push(task('b.md', 'calisiyor', { session: 'ofis-k-1', project: 'kasa' })); return s; };
          const one1 = () => { const s = working(); s.projects.push({ name: 'kasa' }); return s; };
          const quiet = run(one1(), NOW);
          const g = (r) => [one(r, 'sus:guvenlik').yer, one(r, 'sus:guvenlik').durum_metni];
          const came = run(two(), NOW + 1000, quiet);
          const still = run(two(), NOW + 5000, came);
          const later = run(two(), NOW + 40000, still);
          const first = run(two(), NOW, null);
          const hafif = run(two(), NOW + 1000, run(one1(), NOW, null, {hafif: true}), {hafif: true});
          return { came: g(came), still: g(still), later: g(later), first: g(first),
            hafif: one(hafif, 'sus:guvenlik'), node: !!d.ofisPlani(['yayin']).dugumler['lobi-karsilama'],
            arrivals: d.asansordenGelenler(came, quiet).map((a) => a.id) }; })()""")
        self.assertEqual(out["came"], ["lobi-karsilama", "karşılıyor"])
        self.assertEqual(out["still"], ["lobi-karsilama", "karşılıyor"])
        self.assertEqual(out["later"], ["lobi-nobet", "girişte"])
        self.assertEqual(out["first"], ["lobi-nobet", "girişte"])  # the first render places everyone
        self.assertEqual((out["hafif"]["yer"], out["hafif"]["durum_metni"]), ("lobi-nobet", "girişte"))  # hafif: at the post
        self.assertTrue(out["node"])
        self.assertEqual(out["arrivals"], ["is:b"])

    def test_auditors_and_hand_overs_are_not_lift_arrivals(self):
        out = run_dav("""d.asansordenGelenler([{ id: 'denetci:glm', denetci: true }, { id: 'is:x', devral: 'kadro:opus' },
          { id: 'sus:cayci', tur: 'sus' }, { id: 'is:y', tur: 'ajan', yer: 'ekip-yayin-masa-1' },
          { id: 'is:y/alt:h', tur: 'alt-ajan', yer: 'ekip-yayin-masa-1-yardimci-0' },
          { id: 'is:z', tur: 'ajan', poz: 'evde' }], [{ id: 'ceo' }]).map((a) => a.id)""")
        # staff coming in for their office hours are arrivals; a helper appears beside its parent
        self.assertEqual(out, ["sus:cayci", "is:y"])

    def test_the_tea_server_takes_tea_to_the_longest_worker_after_a_celebration(self):
        out = run_dav("""(() => { const two = (x = []) => st({
            sessions: [ses('s1', 'busy', { job_status: 'calisiyor', model: 'opus', note: 'a.md' }),
              ses('s2', 'busy', { job_status: 'calisiyor', model: 'opus', note: 'b.md', project: 'yayin' })],
            tasks: [task('a.md', 'calisiyor', { session: 's1', started: iso(NOW - 600000) }),
              task('b.md', 'calisiyor', { session: 's2', started: iso(NOW - 3 * 3600000) }), ...x] });
          const at = (s) => { let p = null; return Array.from({length: 3600}, (_, i) => (p = run(s, NOW + i * 1000, p), one(p, 'sus:cayci'))); };
          const r = at(two()); const b = one(run(two()), 'is:b');
          const fresh = at(two([task('c.md', 'bitti', { started: iso(NOW - 900000), finished: iso(NOW - 5000) })]));
          return { b: b.masa, tea: [...new Set(r.filter((a) => a.durum_metni === 'en uzun çalışana çay götürüyor').map((a) => a.yer))],
            n: r.filter((a) => a.durum_metni === 'en uzun çalışana çay götürüyor').length,
            trips: r.reduce((n, a, i) => n + (a.durum_metni === 'en uzun çalışana çay götürüyor' &&
              (i === 0 || r[i - 1].durum_metni !== a.durum_metni) ? 1 : 0), 0),
            fresh: fresh.slice(0, 2).filter((a) => a.durum_metni === 'en uzun çalışana çay götürüyor').length,
            freshTea: fresh.slice(0, 2).map((a) => a.durum_metni),
            longest: d.enUzunCalisan([task('x.md', 'calisiyor', { started: iso(NOW - 10) }), task('y.md', 'kontrolde', { started: iso(NOW - 9e6) }),
              task('w.md', 'calisiyor', { started: 'bilinmiyor' })], 'Europe/Istanbul').note,
            enAz: (d.enUzunCalisan([task('x.md', 'calisiyor', { started: iso(NOW - 60000) })], 'Europe/Istanbul', null, NOW,
              d.EN_UZUN_MIN_MS) || {}).note || null }; })()""")
        self.assertEqual(out["tea"], [out["b"] + "-yan"])
        # at most one such round every EN_UZUN_ARA_MS (20 min): within an hour two or three
        self.assertGreaterEqual(out["trips"], 1)
        self.assertLessEqual(out["trips"], 3)
        self.assertEqual(out["fresh"], 0)  # a fresh ✓ comes first while it lasts
        self.assertEqual(out["freshTea"], ["çay getiriyor", "çay getiriyor"])
        self.assertEqual(out["longest"], "x.md")
        self.assertIsNone(out["enAz"])  # a job working only a minute is never "the longest worker"



@unittest.skipUnless(NODE, "node is not installed")
class IdleLifePrioritiesTest(unittest.TestCase):
    """The owner, 2026-11-12: duty > break, work > break, decisions for the owner keep the CEO and the Sekreter on duty."""

    def test_the_ceo_sleeps_in_a_bed_only_in_its_sleep_slots_and_never_with_something_open(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']);
          // a slot whose seeded share is sleep (it sleeps there only in the lunch window or at night)
          const t = Array.from({ length: 60 }, (_, i) => NOW + i * 90000).find((m) => d.ceoPlani(m, P, { uyuyabilir: true, ogle: true }).tur === 'uyku');
          const c = (x, o = {}) => { const a = one(run(st({ ceo: x.ceo, decisions: x.dec || [] }), t, null, o), 'ceo');
            return [a.yer, a.poz, a.durum_metni]; };
          return { dormant: c({ ceo: { state: 'dormant' } }), idle: c({ ceo: { state: 'idle' } }),
            dec: c({ ceo: { state: 'dormant' }, dec: [{ note: 'k.md' }] }), queue: c({ ceo: { state: 'dormant', queue: 1 } }),
            busy: c({ ceo: { state: 'busy' } }) }; })()""")
        # by day in the office hours (owner decision 2026-11-16) a dormant CEO's sleep slot is a break, never the bed
        self.assertNotEqual(out["dormant"][0], "dinlenme-yatak-0")
        self.assertNotIn("uyuyor", out["dormant"][2])
        self.assertNotEqual(out["idle"][0], "dinlenme-yatak-0")  # an idle CEO's sleep slot: a break, never the bed
        self.assertEqual(out["dec"][0], "ceo-masa")  # a decision waits: it stays at its desk
        self.assertEqual(out["queue"][0], "ceo-masa")
        self.assertEqual(out["busy"], ["ceo-masa", "yaziyor", "çalışıyor"])

    def test_the_secretary_and_the_guard_take_breaks_only_off_duty(self):
        out = run_dav("""(() => { const at = (s, id) => Array.from({ length: 120 }, (_, i) => one(run(s, NOW + i * 60000), id));
          const sekFree = at(st(), 'sus:sekreter'), sekDuty = at(st({ decisions: [{ note: 'k.md' }] }), 'sus:sekreter');
          const guard = at(st(), 'sus:guvenlik');
          return { sekFree: [...new Set(sekFree.map((a) => a.durum_metni))].sort(),
            sekDuty: [...new Set(sekDuty.map((a) => a.yer))],
            guard: [...new Set(guard.map((a) => a.durum_metni))].sort(),
            spots: [...new Set([...sekFree, ...guard].map((a) => a.yer))].filter((y) => !/^(lobi-|koridor|kanat|alt-|balkon)/.test(y)).sort() }; })()""")
        self.assertIn("resepsiyonda", out["sekFree"])
        self.assertTrue(set(out["sekFree"]) - {"resepsiyonda"}, out["sekFree"])  # some breaks
        self.assertEqual(out["sekDuty"], ["lobi-resepsiyon"])  # a decision waits: at reception
        self.assertIn("girişte", out["guard"])
        # their own spots only, never an agent's seat
        for y in out["spots"]:
            self.assertRegex(y, r"^(cay-ocagi-personel-[01]|yemekhane-personel-[01]|sigara-yer-3|spor-mat-[23]|.*-kapi)$")

    def test_a_greeting_beats_the_guards_break(self):
        out = run_dav("""(() => { const one1 = () => { const s = working(); s.projects.push({ name: 'kasa' }); return s; };
          const two = () => { const s = one1(); s.sessions.push(ses('k', 'busy', { model: 'opus', note: 'b.md', project: 'kasa' }));
            s.tasks.push(task('b.md', 'calisiyor', { session: 'k', project: 'kasa' })); return s; };
          const res = [];
          for (let i = 0; i < 60; i++) { const t = NOW + i * 60000; const q = run(one1(), t);
            res.push(one(run(two(), t + 1000, q), 'sus:guvenlik').yer); }
          return [...new Set(res)]; })()""")
        self.assertEqual(out, ["lobi-karsilama"])

    def test_the_mudur_takes_breaks_when_idle_and_goes_back_to_its_office_for_work_or_quota(self):
        out = run_dav("""(() => { const m = (x) => st({ modeller: [{ model: 'fable', durum: x }] });
          const day = Array.from({ length: 120 }, (_, i) => one(run(m('hazir'), NOW + i * 60000), 'kadro:fable').yer);
          const kota = one(run(m('kota')), 'kadro:fable');
          const work = one(run(working({ model: 'fable', tier: 'kod' }, { model: 'fable' })), 'is:a');
          return { away: day.filter((y) => y !== 'mudur-odasi-masa').length, home: day.filter((y) => y === 'mudur-odasi-masa').length,
            kota: [kota.yer, kota.poz], work: work.masa }; })()""")
        self.assertGreater(out["away"], 0)
        self.assertGreater(out["home"], out["away"] / 3)  # resting at its office desk stays common
        self.assertEqual(out["kota"], ["mudur-odasi-masa", "evde"])
        self.assertEqual(out["work"], "mudur-odasi-masa")

    def test_naps_need_a_long_idle_and_at_most_twenty_beds(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']);
          const list = (uzun, n) => Array.from({ length: n }, (_, i) => ({ id: 'kadro:x' + String(i).padStart(2, '0'), kadro: true, uzun }));
          const naps = (l, o) => [...d.molaPlani(l, NOW, P, 'uyku', o).values()].filter((x) => x.poz === 'yatiyor');
          return { short: naps(list(false, 3)).length, long: naps(list(true, 25)).map((x) => x.yer),
            ceoBed: naps(list(true, 25), { doluYataklar: ['dinlenme-yatak-0'] }).map((x) => x.yer),
            text: naps(list(true, 1))[0].metin, gece: naps(list(true, 1), { gece: true })[0].metin }; })()""")
        self.assertEqual(out["short"], 0)  # not idle long enough: rests at its seat
        self.assertEqual(out["long"], [f"dinlenme-yatak-{i}" for i in range(20)])  # one bed each, 20 at most
        self.assertEqual(out["ceoBed"], [f"dinlenme-yatak-{i}" for i in range(1, 20)])
        self.assertEqual(out["text"], "dinleniyor · uyuyor")
        self.assertEqual(out["gece"], "uyuyor")

    def test_a_restroom_visit_hides_inside_then_the_sink_and_the_door_is_a_stable_seed(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']);
          // the actor's own slot start (molaDilimi: every actor has its own seeded phase)
          const bas = (id) => { const x = d.molaDilimi(id, NOW); return NOW - x.gecen + d.MOLA_ADIM_MS; };
          const seg = bas('kadro:opus');
          const v = (t) => d.molaPlani([{ id: 'kadro:opus', kadro: true }], t, P, 'wc').get('kadro:opus');
          const two = d.molaPlani([{ id: 'a', kadro: true }, { id: 'b', kadro: true }, { id: 'c', kadro: true }], NOW, P, 'wc');
          return { inside: v(seg + 5000), sink: v(seg + d.WC_ICERDE_MS + 5000), after: v(seg + d.WC_LAVABO_MS + 5000) || null,
            door: d.wcKapisi('kadro:opus') === d.wcKapisi('kadro:opus'),
            occupied: [...two.values()].filter((x) => x.poz === 'lavaboda').map((x) => x.yer).sort() }; })()""")
        k = out["inside"]["yer"][-1]
        self.assertEqual(out["inside"], {"yer": f"wc-ici-{k}", "poz": "lavaboda", "metin": "lavaboda", "mola": True})
        self.assertEqual(out["sink"], {"yer": f"wc-lavabo-{k}", "poz": "bekliyor", "metin": "ellerini yıkıyor", "mola": True})
        self.assertIsNone(out["after"])  # then back at its seat for the rest of the slot
        self.assertTrue(out["door"])
        self.assertEqual(len(out["occupied"]), len(set(out["occupied"])))  # one per cubicle

    def test_a_cigarette_break_is_on_the_terrace_and_working_actors_never_take_one(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']);
          const m = d.molaPlani([1, 2, 3, 4].map((i) => ({ id: 'x' + i, kadro: true })), NOW, P, 'sigara');
          const busy = run(st({ ...working(), sahne: { ...st().sahne, mola: 'sigara' } }));
          return { places: [...m.values()].map((x) => [x.yer, x.poz, x.metin]),
            busy: one(busy, 'is:a').yer, light: run(st({ sahne: { ...st().sahne, mola: 'sigara' } }), NOW, null, { hafif: true })
              .filter((a) => a.poz === 'sigara').length }; })()""")
        # the smoking corner first (sigara-yer-3 is the guard's, 4 the roaming staff's), then a bench seat
        self.assertEqual(out["places"], [[f"sigara-yer-{i}", "sigara", "sigara molası"] for i in range(3)]
                         + [["sigara-yer-5", "bekliyor", "terasta oturuyor"]])
        self.assertEqual(out["busy"], "ekip-yayin-masa-1")
        self.assertEqual(out["light"], 0)

    def test_the_project_resident_sits_at_the_managers_desk_only_when_free_and_staff_show_in_hafif(self):
        out = run_dav("""(() => { const free = run(st()), boss = run(working({ model: 'fable', tier: 'planlama' }, { model: 'opus' }));
          const two = st({ sessions: [ses('s1', 'busy', { note: 'a.md' }), ses('s2', 'busy', { note: 'b.md' })],
            tasks: [task('a.md', 'calisiyor', { session: 's1', model: 'fable', tier: 'planlama' }),
              task('b.md', 'calisiyor', { session: 's2', model: 'opus', tier: 'planlama' })] });
          const taken = run(two); const r = (l) => { const a = one(l, 'sus:proje:yayin'); return [a.yer, a.etiket, a.tur]; };
          return { free: r(free), taken: r(taken), light: run(st(), NOW, null, { hafif: true }).filter((a) => a.tur === 'sus').map((a) => a.id).sort() }; })()""")
        self.assertEqual(out["free"], ["ekip-yayin-mudur", "Yayin sorumlusu", "sus"])
        self.assertEqual(out["taken"][0], "ekip-yayin-mudur-yan")
        # hafif (performance): only the duty staff — the guard, the Sekreter, the doctor; the rooms stay
        # … and of the IT team only the person on shift (owner decision 2026-11-12)
        it = [x for x in out["light"] if x.startswith("sus:sunucu")]
        self.assertEqual(len(it), 1, out["light"])
        self.assertEqual([x for x in out["light"] if x not in it], ["sus:guvenlik", "sus:revir", "sus:sekreter"])



@unittest.skipUnless(NODE, "node is not installed")
class OfficeStaffCardsTest(unittest.TestCase):
    """Muhasebeci, İdari işler, İK and the project residents: only what /api/state and the fetched data say."""

    def card(self, expr):
        return run_scene(expr, NPC_PRELUDE)

    def test_the_accountant_shows_day_month_quality_costliest_and_budget(self):
        k = self.card("""(() => { const s = st(); const m = { bugun: { usd: 1.21, token: null, is_sayisi: 2, codex_fiyatsiz: 1,
            proje: [{ proje: 'yayin', usd: 1.2, token: 400000, is_sayisi: 1 }, { proje: 'kasa', usd: 0.01, is_sayisi: 1 }],
            rol: [{ rol: 'Kıdemli', usd: 1.2, is_sayisi: 1 }] },
          bu_ay: { usd: 3, token: 900000, is_sayisi: 4, proje: [], rol: [] },
          kalite: { dogrulanmis_is_basina_usd: 1.5, dogrulanmis_is_basina_token: 450000, ilk_tur_gecen: 3, ilk_tur_olculen: 4 },
          en_pahali: [{ not: 'a.md', baslik: 'Giriş', usd: 1.2, token: 400000 }],
          butce: { calisan: 1, harcanan_usd: 2.9, harcanan_token: 800000, butce_usd: 3,
            dikkat: [{ not: 'a.md', baslik: 'Giriş', usd: 2.9, token: 800000, butce: 3, durum: 'yakin' }] } };
          return h.karakterKarti(one(run(s), 'sus:muhasebe'), s, NOW, { veri: { muhasebe: m } }); })()""")
        self.assertEqual((k["baslik"], k["alt"]), ("Muhasebeci", "kullanım"))
        got = [[r["ad"], r["metin"]] for r in k["satirlar"]]
        self.assertIn(["Bugün", "≈$1,21 · 2 iş"], got)  # unknown tokens: the dollars only, never 0 (CLAUDE.md)
        self.assertIn(["", "projeye göre: yayin (400 bin token · ≈$1,20) · kasa ≈$0,01"], got)  # no count: dollars alone
        self.assertIn(["", "Codex incelemeleri (1) fiyatsız: toplamda yok"], got)
        self.assertIn(["Bu ay", "900 bin token · ≈$3,00 · 4 iş"], got)
        self.assertIn(["Doğrulanmış iş başına", "450 bin token · ≈$1,50 (bu ay)"], got)
        self.assertIn(["Kullanım sınırı", "1 açık iş: 800 bin token · ≈$2,90 / ≈$3,00"], got)  # the cap stays dollars only
        self.assertIn(["İlk turda geçen", "%75 (3/4) (bu ay)"], got)
        self.assertIn(["Kullanım sınırı uyarısı", "Giriş · 800 bin token · ≈$2,90 / ≈$3,00 · sınıra yakın"], got)
        self.assertEqual(k["eylemler"], [{"tur": "is", "note": "a.md", "metin": "Giriş · 400 bin token · ≈$1,20"},
                                         {"tur": "kalite", "metin": "Kalite sekmesini aç"}])
        empty = self.card("""(() => { const s = st(); return h.karakterKarti(one(run(s), 'sus:muhasebe'), s, NOW); })()""")
        self.assertEqual([r["ad"] for r in empty["satirlar"]], ["Görevi", "Kullanım"])

    def test_the_office_manager_shows_server_autostart_access_log_limits_and_schedules(self):
        k = self.card("""(() => { const s = st({ sunucu: { baslangic: iso(NOW - 2 * H - 5 * 60000), pid: 1 },
            schedules: [{ ad: 'sabah', proje: 'yayin', baslik: 'Sabah', sonraki: iso(NOW + 2 * H) },
              { ad: 'dur', proje: 'kasa', baslik: 'Durdu', sonraki: '', duraklatildi: true }] });
          const d = { limitler: { max_running: 3, max_running_per_project: 1, max_queued_per_project: 5, max_bekleyen_onay: 2 },
            otomatik_baslatma: { kurulu: true }, obsidian: { sorun: false, python: null }, gunluk: { dosya: 'server.log', boyut: 1258291, yedek_boyut: null } };
          return h.karakterKarti(one(run(s), 'sus:idari'), s, NOW, { veri: { idari: d } }); })()""")
        r = {x["ad"]: x["metin"] for x in k["satirlar"] if x["ad"]}
        self.assertEqual(r["Sunucu"], "bugün 07:55 başladı · 2 sa 5 dk çalışıyor")
        self.assertEqual(r["Otomatik başlatma"], "kurulu: oturum açılınca kendiliğinden başlar")
        self.assertEqual(r["Obsidian erişimi"], "sorun yok")
        self.assertEqual(r["Günlük"], "server.log 1,2 MB · 5 MB'ı geçince kısalır")
        self.assertIn("aynı anda 3 iş", r["Sınırlar"])
        self.assertEqual(r["Zamanlanmış işler"], "Sabah · yayin · sonraki bugün 12:00")
        self.assertIn("Durdu · kasa · duraklatıldı", [x["metin"] for x in k["satirlar"]])
        bad = self.card("""(() => { const s = st(); return h.karakterKarti(one(run(s), 'sus:idari'), s, NOW,
          { veri: { idari: { obsidian: { sorun: true, python: '/opt/homebrew/bin/python3.12' } } } }); })()""")
        self.assertEqual({x["ad"]: x["metin"] for x in bad["satirlar"]}["Obsidian erişimi"],
                         "notlar okunamıyor — Sistem Ayarları > Gizlilik ve Güvenlik > Tam Disk Erişimi'ne şunu ekle: "
                         "/opt/homebrew/bin/python3.12, sonra sunucuyu yeniden başlat")
        bare = self.card("""(() => { const s = st(); return h.karakterKarti(one(run(s), 'sus:idari'), s, NOW); })()""")
        self.assertEqual([x["ad"] for x in bare["satirlar"]], ["Görevi"])  # nothing known: nothing shown

    def test_hr_shows_the_roster_monthly_role_numbers_pilots_proposals_and_reviewers(self):
        k = self.card("""(() => { const s = st({ modeller: [{ model: 'opus', durum: 'calisiyor', calisan: 1 }, { model: 'haiku', durum: 'hazir' }],
            decisions: [{ note: 'm.md', title: 'Kadro önerisi', kind: 'model-onerisi', asked: iso(NOW - H) }] });
          const veri = { muhasebe: { bu_ay_rol_kalite: [{ rol: 'Kıdemli', is_sayisi: 4, ilk_tur_gecen: 3, ilk_tur_olculen: 4, dogrulanmis_is_basina_usd: 2, dogrulanmis_is_basina_token: 1200000 }] },
            kalite: { model_secimi: { pilotlar: [{ proje: 'yayin', katman: 'genel', model: 'opus', biten: 1, toplam: 3 }] },
              denetciler: [{ ad: 'codex', tur: 5, ciddi: 4, gecerli: 3 }] } };
          return h.karakterKarti(one(run(s), 'sus:ik'), s, NOW, { veri }); })()""")
        got = [[r["ad"], r["metin"]] for r in k["satirlar"]]
        self.assertEqual(got[1][0], "Kadro")
        self.assertTrue(any(m.startswith("Kıdemli (Opus) · 1 çalışıyor") for _, m in got), got)
        self.assertIn(["Bu ay · Kıdemli", "4 iş · ilk turda %75 (3/4) · doğrulanmış iş başına 1,2 mn token · ≈$2,00"], got)
        self.assertIn(["Kadro denemesi", "yayin · genel: Opus deneniyor (1/3)"], got)
        self.assertIn(["Denetçi karnesi", "Codex · 5 tur · ciddi bulguların %75 (3/4) geçerli"], got)
        self.assertEqual(k["eylemler"], [{"tur": "karar", "metin": "Kadro önerisi · 1 sa", "note": "m.md"},
                                         {"tur": "kalite", "metin": "Kalite sekmesini aç"}])

    def test_hr_shows_who_is_in_on_shift_and_at_the_otel(self):
        # owner decision 2026-11-18: the same people the guard's card counts (kimNerede)
        out = self.card("""(() => { const s = st(); const l = run(s); const k = d.kimNerede(s, NOW, l);
          return { rows: h.karakterKarti(one(l, 'sus:ik'), s, NOW, { aktorler: l }).satirlar.filter((r) => r.bolum === 'Şu an').map((r) => [r.ad, r.metin]),
            ofiste: k.ofiste.filter((e) => e.durum !== 'cikiyor').length, evde: k.evde.length,
            nobet: k.ofiste.filter((e) => e.durum === 'nobette').length, v: h.ikVarligi(s, NOW, l) }; })()""")
        rows = dict(out["rows"])
        self.assertEqual(list(rows), ["Ofiste", "Nöbette", "Otelde"])
        self.assertTrue(rows["Ofiste"].startswith(f"{out['ofiste']} kişi ("), rows)
        self.assertEqual(len(out["v"]["nobette"]), out["nobet"])
        self.assertIn("Güvenlik · ", rows["Nöbette"])
        self.assertEqual(rows["Otelde"], f"{out['evde']} kişi" if out["evde"] else "kimse yok")

    def test_a_manager_card_lists_its_departments_silent_and_stuck_jobs(self):
        out = run_scene("""(() => { const s = st({ tasks: [task('a.md', 'calisiyor', { title: 'Sepet' }),
            task('b.md', 'tikandi', { title: 'Ödeme', finished: iso(NOW - 3600000) }),
            task('c.md', 'tikandi', { title: 'Dün', finished: iso(NOW - 30 * 3600000) }),
            task('r.md', 'calisiyor', { title: 'İnceleme', tier: 'inceleme', step_kind: 'kod-inceleme' })],
            postoffice: { silent: [{ is: 'a', seconds: 300 }, { is: 'r', seconds: 300 }] } });
          const rows = (k) => k.satirlar.map((r) => [r.ad, r.metin]);
          return { yaz: rows(h.mudurKarti(s, NOW, 'yazilim')), qa: rows(h.mudurKarti(s, NOW, 'qa')), it: h.sorunluIsler(s, NOW, 'it') }; })()""")
        i = out["yaz"].index(["Bakılması gereken", "yayin · Sepet · sessiz"])
        self.assertEqual(out["yaz"][i + 1], ["", "yayin · Ödeme · takıldı"])
        self.assertNotIn("Dün", str(out["yaz"]))  # stuck today only
        self.assertIn(["Bakılması gereken", "yayin · İnceleme · sessiz"], out["qa"])
        self.assertEqual(out["it"], [])

    def test_the_project_resident_shows_its_project_without_pretending_to_work(self):
        k = self.card("""(() => { const s = st({ projects: [{ name: 'yayin', description: 'Dilek uygulaması', klasor: 'yayin' }],
            sessions: [ses('w', 'busy', { note: 'a.md', model: 'opus' })],
            tasks: [task('a.md', 'calisiyor', { session: 'w', title: 'Giriş', started: iso(NOW - 20 * 60000) }),
              task('q.md', 'sirada', { title: 'Sıradaki', held: true }),
              task('b.md', 'bitti', { title: 'Rapor', finished: iso(NOW - H), spent: '0.5', tokens: '' })],
            workflows: [{ grup: 'akis-1', proje: 'yayin', baslik: 'Profil', durum: 'calisiyor', tamam: 2, toplam: 5 }] });
          const m = { bu_ay: { proje: [{ proje: 'yayin', usd: 4.5, token: 1200000, is_sayisi: 6 }] } };
          const l = run(s); const a = one(l, 'sus:proje:yayin');
          return [a.tur, a.etiket, a.tiklama, h.karakterKarti(a, s, NOW, { veri: { muhasebe: m } })]; })()""")
        tur, etiket, tiklama, kk = k
        self.assertEqual((tur, etiket, tiklama), ("sus", "Yayin sorumlusu", None))  # staff, never a worker
        self.assertEqual(kk["alt"], "proje bilgisi")
        r = {x["ad"]: x["metin"] for x in kk["satirlar"] if x["ad"]}
        self.assertEqual((r["Proje"], r["Klasör"]), ("Dilek uygulaması", "yayin"))
        self.assertEqual(r["Şimdi"], "Giriş · Kıdemli (Opus) · çalışıyor · 20 dk")
        self.assertEqual(r["Sırada"], "1 iş · 1 bekletiliyor")
        self.assertEqual(r["Akış"], "Profil · 2/5 adım")
        self.assertEqual(r["Son işler"], "Rapor · bitti · bugün 09:00 · ≈$0,50")
        self.assertEqual(r["Bu ay kullanım"], "1,2 mn token · ≈$4,50 · 6 iş")
        self.assertEqual([e["tur"] for e in kk["eylemler"]], ["is", "is", "raporlar"])

    def test_the_project_resident_card_shows_the_sorumlu_note_summary(self):
        # plan "Sonraki iş (7)": the rules and the three sections of OFIS/Projeler/<proje>.md (state.projects[].sorumlu)
        k = self.card("""(() => { const s = st({ projects: [{ name: 'yayin', description: 'D', klasor: 'yayin',
            sorumlu: { kurallar: 'Never ship ads.', hassas_yollar: ['ios/**'], dur_sor: ['a', 'b', 'c'], asla: ['Reklam eklemez.'],
              teslim: ['bildir ile rapor'], varsayilan: { dur_sor: true, asla: false, teslim: true } } }] });
          const a = one(run(s), 'sus:proje:yayin'); return h.karakterKarti(a, s, NOW).satirlar; })()""")
        r = [(x["ad"], x["metin"]) for x in k]
        for row in (("Kurallar", "Never ship ads."), ("Hassas yollar", "ios/**"), ("Durup sorar", "a"), ("", "b"),
                    ("", "+1 madde (notta)"), ("Asla yapmaz", "Reklam eklemez."), ("Teslim", "bildir ile rapor")):
            self.assertIn(row, r)



@unittest.skipUnless(NODE, "node is not installed")
class SocialMediaTeamTest(unittest.TestCase):
    def test_the_department_is_data_driven_and_its_cards_say_there_is_no_work_yet(self):
        out = run_scene("""(() => { const s = st({ projects: [{ name: 'yayin' }, { name: 'kasa' }] }); const l = run(s);
          const team = l.filter((a) => a.gorevli === 'sosyal');
          return { ids: team.map((a) => [a.id, a.etiket, a.tur, a.tiklama]), n: d.SOSYAL_EKIBI.length,
            card: h.karakterKarti(one(l, 'sus:sosyal:grafik'), s, NOW),
            light: run(s, NOW, null, { hafif: true }).filter((a) => a.gorevli === 'sosyal').map((a) => [a.yer === a.masa, a.poz]) }; })()""")
        self.assertEqual(out["n"], 14)
        self.assertEqual(len(out["ids"]), 14)
        self.assertEqual(out["ids"][0], ["sus:sosyal:instagram", "Instagram uzmanı", "sus", None])
        self.assertIn(["sus:sosyal:topluluk", "Topluluk yöneticisi", "sus", None], out["ids"])
        k = out["card"]
        self.assertEqual((k["baslik"], k["alt"], k["eylemler"]), ("Grafik tasarımcı", "sosyal medya ve tasarım", []))
        self.assertEqual(k["satirlar"], [{"ad": "Görevi", "metin": "Paylaşımlar için görselleri hazırlayacak."},
                                         {"ad": "Alan", "metin": "görsel"},
                                         {"ad": "Şu an", "metin": "Şu an atanmış iş yok"},
                                         {"ad": "Hizmet edeceği projeler", "metin": "yayin, kasa"}])
        self.assertEqual(out["light"], [])  # hafif: the room only (performance)



@unittest.skipUnless(NODE, "node is not installed")
class CareStaffTest(unittest.TestCase):
    """Ofis doktoru, Ofis psikoloğu, Masajcı and the gym: real data only, one visit per event, nobody is moved."""

    def card(self, expr):
        return run_scene(expr, NPC_PRELUDE)

    def test_the_doctor_lists_stuck_jobs_silent_sessions_red_workers_and_the_error_record(self):
        k = self.card("""(() => { const s = st({ tasks: [task('t.md', 'tikandi', { title: 'Giriş', finished: iso(NOW - H) }),
              task('y.md', 'tikandi', { title: 'Dün', finished: iso(NOW - 30 * H) })],
            postoffice: { silent: [{ proje: 'kasa', seconds: 300 }, { proje: 'blog', seconds: 130, izin: true }] },
            modeller: [{ model: 'opus', durum: 'hata', son_hata: 'API 500' }],
            olaylar: [{ tur: 'hata', ileti: 'inbox x: OSError', sayi: 3, son: '2026-11-11 09:50' }] });
          return h.karakterKarti(one(run(s), 'sus:revir'), s, NOW); })()""")
        self.assertEqual((k["baslik"], k["alt"]), ("Ofis doktoru", "ofis sağlığı"))
        got = [[r["ad"], r["metin"]] for r in k["satirlar"]]
        self.assertIn(["Takılan işler", "yayin · Giriş · bugün 09:00"], got)
        self.assertNotIn("Dün", str(got))  # today only
        self.assertIn(["Oturumlar", "kasa · 5 dakikadır sessiz"], got)
        self.assertIn(["", "blog · 2 dakikadır izin bekliyor"], got)
        self.assertTrue(any(a == "Hata veren" and m.startswith("Kıdemli (Opus)") for a, m in got), got)
        self.assertIn(["Sunucu kaydı", "2026-11-11 09:50 · hata · inbox x: OSError (3 kez)"], got)
        self.assertEqual(k["eylemler"], [{"tur": "is", "note": "t.md", "metin": "İşi aç: Giriş"}])
        ok = self.card("""(() => { const s = st({ postoffice: { silent: [] } }); return h.karakterKarti(one(run(s), 'sus:revir'), s, NOW); })()""")
        r = {x["ad"]: x["metin"] for x in ok["satirlar"]}
        self.assertEqual(r["Durum"], "Ofis sağlıklı")
        self.assertEqual(r["Bakılanlar"], "takılan iş yok · Kontrol'ü geçmeyen iş yok · sessiz oturum yok · hata veren çalışan yok")

    def test_the_doctor_lists_the_open_jobs_whose_kontrol_failed(self):
        # owner decision 2026-11-18: failing jobs too (a Kontrol that did not pass; the job is fixing it now)
        k = self.card("""(() => { const s = st({ tasks: [task('k.md', 'calisiyor', { title: 'Sepet', kontrol_sonuc: 'kaldi', kontrol_deneme: 1 }),
              task('m.md', 'calisiyor', { title: 'Ödeme', kontrol_sonuc: 'kaldi', kontrol_deneme: 2 }),
              task('b.md', 'bitti', { title: 'Eski', kontrol_sonuc: 'kaldi', finished: iso(NOW - H) })], postoffice: { silent: [] } });
          return h.karakterKarti(one(run(s), 'sus:revir'), s, NOW); })()""")
        got = [[r["ad"], r["metin"]] for r in k["satirlar"]]
        self.assertIn(["Kontrol'ü geçmeyen", "yayin · Sepet · düzeltiyor"], got)
        self.assertIn(["", "yayin · Ödeme · 2. deneme"], got)
        self.assertNotIn("Eski", str(got))  # a finished job is no case
        self.assertNotIn("Ofis sağlıklı", str(got))
        self.assertEqual([e["note"] for e in k["eylemler"]], ["k.md", "m.md"])

    def test_the_doctor_visits_each_new_case_once_and_never_moves_the_patient(self):
        out = run_dav("""(() => { const stuck = () => st({ sessions: [ses('s', 'idle', { note: 'a.md', model: 'opus' })],
            tasks: [task('a.md', 'tikandi', { session: 's', finished: iso(NOW - 60000) })] });
          let prev = run(st(), NOW);
          const seq = [], pat = [];
          for (let i = 1; i <= 240; i++) { prev = run(stuck(), NOW + i * 1000, prev); const dr = one(prev, 'sus:revir');
            seq.push(dr.yer.startsWith('ekip-') && dr.yer.endsWith('-yan') ? 'V' : 'M'); pat.push(one(prev, 'is:a').yer); }
          const first = one(run(stuck(), NOW), 'sus:revir').durum_metni;
          const P = d.ofisPlani(['yayin']);
          return { seq: seq.join(''), pat: [...new Set(pat)], first,
            sure: d.yurumeSuresi(P, 'revir-masa', 'ekip-yayin-masa-1-yan') + d.DOKTOR_KALIS_MS }; })()""")
        visit = out["seq"].split("M")[0]
        # one visit right after the job got stuck, as long as the walk there plus a moment beside the desk
        self.assertGreaterEqual(len(visit), 8)  # at least the stay beside the desk (the walk comes on top)
        self.assertNotIn("V", out["seq"][len(visit):])  # and only one
        self.assertEqual(len(out["pat"]), 1)  # the patient stays where it is
        self.assertNotEqual(out["first"], "hastaya bakıyor")  # nothing to compare on the first render

    def test_the_psychologist_reads_pressure_from_real_numbers_with_advice(self):
        k = self.card("""(() => { const s = st({ tasks: [
              task('a.md', 'calisiyor', { title: 'Uzun', started: iso(NOW - 2 * H) }),
              task('b.md', 'calisiyor', { title: 'Kalan', kontrol_deneme: 2, kontrol_sonuc: 'kaldi' }),
              task('f.md', 'kontrolde', { title: 'İkinci', kontrol_deneme: 2 }),
              task('g.md', 'calisiyor', { title: 'Bir', kontrol_deneme: 1, kontrol_sonuc: 'kaldi' }),
              task('h.md', 'kontrolde', { title: 'İlk', kontrol_deneme: 1 }),
              task('c.md', 'calisiyor', { title: 'Pahalı', spent: '2.55', budget: 3 }),
              task('d.md', 'calisiyor', { title: 'Çağrı', calls: '35', max_calls: 40, devam: 2 }),
              task('e.md', 'bitti', { title: 'Bitmiş', kontrol_deneme: 3 })],
            workflows: [{ grup: 'akis-1', baslik: 'Profil', durum: 'calisiyor', inceleme_turu: 2, plan_turu: 1 }] });
          return [h.karakterKarti(one(run(s), 'sus:psikolog'), s, NOW),
            h.karakterKarti(one(run(st()), 'sus:psikolog'), st(), NOW)]; })()""")
        busy, calm = k
        got = {r["ad"]: r["metin"] for r in busy["satirlar"]}
        self.assertEqual(got["Uzun"], "2 sa 0 dk çalışıyor — ilerlemiyorsa CEO oturumun son mesajlarına bakar")
        # only what really happened: a failure only after kontrol_sonuc says so, no escalation claimed without one
        self.assertEqual(got["Kalan"], "Kontrol 2 kez kaldı — brif yeniden yazılsın")
        self.assertEqual(got["İkinci"], "Kontrol 2. kez çalışıyor — geçmezse iş bir üst katmana taşınır ya da Selin'e sorulur")
        self.assertEqual(got["Bir"], "Kontrol bir kez kaldı — ajan düzeltiyor; ikinci kez kalırsa iş bir üst katmana taşınır")
        self.assertNotIn("İlk", got)
        self.assertEqual(got["Pahalı"], "kullanım sınırının %85'i kullanıldı — devam için Selin'in onayı gerekir")
        self.assertIn("Profil", got)
        self.assertNotIn("Bitmiş", got)  # finished jobs are no pressure
        self.assertEqual(calm["satirlar"][-1], {"ad": "Durum", "metin": "Ekip rahat"})

    def test_the_psychologist_visits_on_a_second_failure_once(self):
        out = run_dav("""(() => { const s = (n) => working({ kontrol_deneme: n });
          let prev = run(s(1), NOW); const seq = [];
          for (let i = 1; i <= 24; i++) { prev = run(s(2), NOW + i * 5000, prev); seq.push(one(prev, 'sus:psikolog').yer); }
          return { seq, desk: one(prev, 'is:a').yer }; })()""")
        self.assertTrue(out["seq"][0].endswith("-yan"), out["seq"])
        self.assertFalse(out["seq"][-1].startswith("ekip-"))  # back off duty (its own desk or a break)
        self.assertEqual(out["desk"], "ekip-yayin-masa-1")

    def test_a_massage_only_after_a_long_working_day_and_the_masseur_stands_beside(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']);
          const tired = d.molaPlani([{ id: 'kadro:opus', kadro: true, yorgun: true }], NOW, P, 'masaj');
          const fresh = d.molaPlani([{ id: 'kadro:opus', kadro: true }], NOW, P, 'masaj');
          const day = [task('a.md', 'bitti', { started: iso(NOW - 3 * 3600000), finished: iso(NOW - 30 * 60000) })];
          const s = st({ tasks: day, modeller: [{ model: 'opus', durum: 'hazir' }], sahne: { ...st().sahne, mola: 'masaj' } });
          const l = run(s);
          return { tired: tired.get('kadro:opus'), fresh: fresh.size, sure: d.calismaSuresi(day, 'opus', NOW, 'Europe/Istanbul'),
            kadro: [one(l, 'kadro:opus').yer, one(l, 'kadro:opus').poz], masor: one(l, 'sus:masaj').yer }; })()""")
        self.assertEqual(out["tired"], {"yer": "masaj-yatak-0", "poz": "masajda", "metin": "masajda", "mola": True})
        self.assertEqual(out["fresh"], 0)
        self.assertEqual(out["sure"], 150 * 60000)
        self.assertRegex(out["kadro"][0], r"^masaj-yatak-[01]$")  # the table nearest its seat
        self.assertEqual(out["kadro"][1], "masajda")
        self.assertEqual(out["masor"], out["kadro"][0] + "-yan")  # the masseur beside that table

    def test_the_masseur_card_shows_the_longest_day_and_who_is_on_the_table(self):
        k = self.card("""(() => { const day = [task('a.md', 'bitti', { started: iso(NOW - 3 * H), finished: iso(NOW - 30 * 60000) })];
          const s = st({ tasks: day, modeller: [{ model: 'opus', durum: 'hazir' }], sahne: { ...st().sahne, mola: 'masaj' } });
          const l = run(s); return h.karakterKarti(one(l, 'sus:masaj'), s, NOW, { aktorler: l }); })()""")
        got = {r["ad"]: r["metin"] for r in k["satirlar"]}
        self.assertEqual(got["Bugün en çok çalışan"], "Kıdemli (Opus) · 2 sa 30 dk")
        self.assertEqual(got["Şu an masajda"], "Kıdemli")

    def test_the_gym_then_sometimes_the_shower_hidden_and_never_in_hafif(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']); const seg = Math.ceil(NOW / d.MOLA_ADIM_MS) * d.MOLA_ADIM_MS;
          const ids = Array.from({ length: 8 }, (_, i) => ({ id: 'x' + i, kadro: true }));
          const early = [...d.molaPlani(ids, seg + 5000, P, 'spor').values()];
          const late = [...d.molaPlani(ids, seg + 50000, P, 'spor').values()];
          const light = run(st({ sahne: { ...st().sahne, mola: 'spor' } }), NOW, null, { hafif: true }).filter((a) => /^spor-|^dus-/.test(a.yer || ''));
          return { early: early.map((x) => [x.yer, x.poz, x.metin]), late: late.map((x) => x.poz), light: light.length }; })()""")
        self.assertEqual(len(out["early"]), 6)  # six machines and mats for the agents (the other two are the staff's)
        self.assertEqual({x[2] for x in out["early"]}, {"spor yapıyor"})
        self.assertEqual({x[1] for x in out["early"]}, {"kosuyor", "bisiklet", "agirlik", "yoga"})
        self.assertIn("dusta", out["late"])
        self.assertLessEqual(out["late"].count("dusta"), 2)  # one per cubicle
        self.assertEqual(out["light"], 0)



@unittest.skipUnless(NODE, "node is not installed")
class StaffLabelPriorityTest(unittest.TestCase):
    def test_staff_on_duty_keep_their_label_and_informational_staff_go_last(self):
        out = run_scene("""(() => { const many = Array.from({ length: 20 }, (_, i) => ({ id: 'is:' + String(i).padStart(2, '0'), tur: 'ajan', poz: 'bekliyor' }));
          const staff = [{ id: 'sus:sekreter', tur: 'sus', gorevli: 'sekreter', simge: '?' },
            { id: 'sus:revir', tur: 'sus', gorevli: 'revir', gorevde: true },
            { id: 'sus:cayci', tur: 'sus', gorevli: 'cayci' },
            { id: 'sus:muhasebe', tur: 'sus', gorevli: 'muhasebe' },
            { id: 'sus:sosyal:x', tur: 'sus', gorevli: 'sosyal' }];
          const pick = [...h.etiketSecimi([...staff, ...many], 23)];
          return { duty: ['sus:sekreter', 'sus:revir'].every((id) => pick.includes(id)),
            info: pick.includes('sus:muhasebe') || pick.includes('sus:sosyal:x'),
            order: [...h.etiketSecimi(staff, 3)].sort() }; })()""")
        self.assertTrue(out["duty"])
        self.assertFalse(out["info"])
        self.assertEqual(out["order"], ["sus:cayci", "sus:revir", "sus:sekreter"])  # informational staff last

    def test_duty_actors_carry_the_flag(self):
        out = run_dav("""(() => { const dec = (n) => Array.from({ length: n }, (_, i) => ({ note: `k${i}.md` }));
          const a = run(st({ decisions: dec(1) }), NOW); const b = run(st({ decisions: dec(2) }), NOW + 1000, a);
          return [one(a, 'sus:sekreter').gorevde || false, one(b, 'sus:sekreter').gorevde]; })()""")
        self.assertEqual(out, [False, True])



@unittest.skipUnless(NODE, "node is not installed")
class StaffPersonalityTest(unittest.TestCase):
    """Staff without real work roam by a seeded personality; duty always wins (owner decision 2026-11-12)."""

    def test_weights_are_seeded_and_shape_where_each_one_goes(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']);
          const ids = d.SOSYAL_EKIBI.map((u) => 'sus:sosyal:' + u.id);
          const day = (id) => Array.from({ length: 300 }, (_, i) => d.personelRotasi(id, NOW + i * 60000, P, new Set()));
          const share = Object.fromEntries(ids.map((id) => [id, day(id).filter((x) => x === null).length / 300]));
          const w = d.personelKisiligi(ids[0]);
          const sameW = JSON.stringify(w) === JSON.stringify(d.personelKisiligi(ids[0]));
          const seen = new Set(ids.flatMap((id) => day(id).filter(Boolean).map((x) => x.secim)));
          const deskW = Object.fromEntries(ids.map((id) => [id, d.personelKisiligi(id).masa]));
          return { share, sameW, seen: [...seen].sort(), deskW, keys: Object.keys(w) }; })()""")
        self.assertTrue(out["sameW"])
        self.assertEqual(out["keys"], ["masa", "cay", "oyun", "spor", "sigara", "salon", "yuruyus"])
        self.assertEqual(out["seen"], ["cay", "oyun", "salon", "sigara", "spor", "yuruyus"])
        shares = list(out["share"].values())
        self.assertGreater(max(shares) - min(shares), 0.2, out["share"])  # some stay put, others roam
        # a higher desk weight means more time at the desk (rank correlation, roughly)
        by_w = sorted(out["deskW"], key=lambda k: out["deskW"][k])
        self.assertLess(out["share"][by_w[0]], out["share"][by_w[-1]])

    def test_spots_are_never_shared_and_a_taken_option_means_the_desk(self):
        out = run_dav("""(() => { const P = d.ofisPlani(['yayin']); const bad = [];
          for (let i = 0; i < 120; i++) { const l = run(st(), NOW + i * 60000);
            const spots = l.filter((a) => a.tur === 'sus' && !/^(koridor|kanat|alt-\\d)/.test(a.yer || '')).map((a) => a.yer);
            if (new Set(spots).size !== spots.length) bad.push(i); }
          return bad; })()""")
        self.assertEqual(out, [])

    def test_duty_wins_the_resident_stays_while_its_project_works_and_hafif_hides_them(self):
        out = run_dav("""(() => { const at = (s) => Array.from({ length: 120 }, (_, i) => one(run(s, NOW + i * 60000), 'sus:proje:yayin').yer);
          const busy = at(working()), idle = at(st());
          const light = run(st(), NOW, null, { hafif: true }).filter((a) => a.gorevli === 'sosyal' || a.gorevli === 'proje').length;
          return { busy: [...new Set(busy)], idleAway: idle.filter((y) => !y.startsWith('ekip-yayin-mudur')).length, light }; })()""")
        self.assertTrue(all(y.startswith("ekip-yayin-mudur") for y in out["busy"]), out["busy"])
        self.assertGreater(out["idleAway"], 0)
        self.assertEqual(out["light"], 0)



@unittest.skipUnless(NODE, "node is not installed")
class StaffFloorLabelTest(unittest.TestCase):
    """The owner, 2026-11-12: a staff label without real work shows the name only; one with a real duty is a green pill."""

    def test_no_work_label_has_no_state_text_and_a_working_one_is_green(self):
        out = run_scene("""(() => { const b = (a, o) => h.etiketBilgisi(a, o);
          const idle = { id: 'sus:sosyal:instagram', tur: 'sus', gorevli: 'sosyal', etiket: 'Instagram uzmanı', durum_metni: 'atanmış iş yok' };
          const duty = { id: 'sus:revir', tur: 'sus', gorevli: 'revir', etiket: 'Ofis doktoru', durum_metni: 'hastaya bakıyor', gorevde: true };
          const ask = { id: 'sus:sekreter', tur: 'sus', gorevli: 'sekreter', etiket: 'Sekreter', durum_metni: "Selin'e 2 soru bekliyor", simge: '?' };
          return { idle: [b(idle), b(idle, { yakin: true, uzerinde: true })], duty: b(duty, { yakin: true }), ask: b(ask, { yakin: true }) }; })()""")
        for i in out["idle"]:
            self.assertEqual((i["ad"], i["durum"]), ("Instagram uzmanı", ""))  # never "atanmış iş yok", not even on hover
            self.assertNotIn("is-gorevde", i["sinif"])
        self.assertEqual(out["duty"]["durum"], "hastaya bakıyor")
        self.assertIn("is-gorevde", out["duty"]["sinif"])
        self.assertIn("is-gorevde", out["ask"]["sinif"])
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".desk-label.is-sus.is-gorevde, .desk-label.is-gorevde, .desk-label.is-compact.is-gorevde { background: #2E7D4F;", css)

    def test_every_character_really_at_work_gets_the_same_green_pill(self):
        # The owner, 2026-11-14: "aynı durum olmalı çalışanlar için o anda" — agents, the CEO, the kadro and reviewers too
        out = run_scene("""(() => { const c = (a) => h.etiketBilgisi({ id: 'x', etiket: 'x', durum_metni: '', ...a }, { yakin: false }).sinif;
          return {
            working: [
              c({ tur: 'ajan', proje: 'sozluk', poz: 'yaziyor' }),                 // a job agent on its running job
              c({ tur: 'ceo', poz: 'yaziyor' }),                                     // the CEO busy
              c({ tur: 'ceo', poz: 'yuruyor', dosya: true }),                        // the CEO handing a job over
              c({ tur: 'ajan', kadro: true, poz: 'yuruyor', dosya: true, gorevde: true }), // a kadro hand-over leg
              c({ tur: 'ajan', kadro: true, poz: 'bekliyor', gorevde: true }),       // taking the file over
              c({ tur: 'ajan', denetci: true, poz: 'yaziyor' }),                     // a reviewer reviewing
              c({ tur: 'ajan', hakem: true, poz: 'toplanti' }),
              c({ tur: 'ajan', poz: 'bekliyor', simge: 'test' }),
              c({ tur: 'sus', gorevde: true }),                                      // staff on duty (unchanged)
            ],
            idle: [
              c({ tur: 'ajan', poz: 'cay' }), c({ tur: 'ajan', kadro: true, poz: 'bekliyor' }),
              c({ tur: 'ceo', poz: 'bekliyor' }), c({ tur: 'ceo', poz: 'uyuyor' }),
              c({ tur: 'ajan', poz: 'yemek', mola: true }), c({ tur: 'ajan', denetci: true, poz: 'bekliyor' }),
              c({ tur: 'ajan', poz: 'evde' }), c({ tur: 'ajan', poz: 'lobide' }), c({ tur: 'sus' }),
              c({ tur: 'ajan', poz: 'yaziyor', simge: '?' }), c({ tur: 'ajan', poz: 'yaziyor', simge: 'kirmizi' }),
              c({ tur: 'ajan', poz: 'kutluyor', simge: '✓' }), c({ tur: 'ozet' }),
            ] }; })()""")
        for s in out["working"]:
            self.assertIn("is-gorevde", s.split(), out["working"])
        for s in out["idle"]:
            self.assertNotIn("is-gorevde", s.split(), out["idle"])
        page = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('<span class="lj lj-calisiyor"></span><span data-t="Yeşil etiket', page)  # the legend names it
        self.assertIn(".etiket-lejant .lj-calisiyor { background: #2E7D4F; }", (WEB / "style.css").read_text(encoding="utf-8"))

    def test_the_tea_server_is_on_duty_only_when_it_carries_tea_to_a_fresh_finish(self):
        out = run_dav("""(() => { const fresh = st({ sessions: [ses('s', 'idle', { note: 'a.md', model: 'opus' })],
            tasks: [task('a.md', 'bitti', { session: 's', finished: iso(NOW - 5000) })] });
          return [one(run(fresh), 'sus:cayci').gorevde || false, one(run(st()), 'sus:cayci').gorevde || false]; })()""")
        self.assertEqual(out, [True, False])


# --- plan "Sonraki iş (9)" step 2: the role "<kıdem> <uzmanlık>" everywhere a role is shown ---

class UzmanlikMapsTest(unittest.TestCase):
    def test_the_page_maps_equal_the_role_profiles(self):
        roller = Path(__file__).resolve().parent.parent / "roller"
        titles = {p.stem: json.loads(p.read_text(encoding="utf-8"))["baslik"] for p in roller.glob("*.json")}
        for name, const in (("ofis-davranis.js", "UZMANLIK_BASLIK"), ("ofis-text.js", "UZMANLIK_ADI")):
            text = (WEB / name).read_text(encoding="utf-8")
            body = re.search(const + r" = \{(.*?)\};", text, re.S).group(1)
            found = dict(re.findall(r"(\w+): (?:N_\()?'([^']*)'", body))  # N_('…'): translated where drawn
            self.assertEqual(found, titles, name)
        # the scorecard's titles too
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
        import karne
        self.assertEqual(karne.UZMANLIK_TITLES, titles)


@unittest.skipUnless(NODE, "node is not installed")
class UzmanlikWebTest(unittest.TestCase):
    def test_role_text(self):
        out = run_dav("[d.rolMetni('opus', 'backend'), d.rolMetni('claude-haiku-4-5', 'mobil'), d.rolMetni('sonnet', 'ui'), "
                      "d.rolMetni('opus', 'test'), d.rolMetni('sonnet', 'genel'), d.rolMetni('fable', 'analiz'), "
                      "d.rolMetni('opus', ''), d.rolMetni('opus', 'uydurma'), d.rolMetni('opus', 'toString'), "
                      "d.testerUnvani('opus'), d.testerUnvani('haiku')]")
        self.assertEqual(out, ["Kıdemli Backend", "Stajyer Mobil", "Uzman UI", "Kıdemli Tester", "Uzman", "Genel Müdür",
                               "Kıdemli", "Kıdemli", "Kıdemli", "Kıdemli Tester", "Stajyer Tester"])

    def test_floor_labels_and_the_card_title_carry_the_specialisation(self):
        out = run_scene("""(() => { const w = working({ uzmanlik: 'backend' }); const a = one(run(w), 'is:a');
          const q = st({ tasks: [task('q.md', 'sirada', { queue_position: 1, uzmanlik: 'mobil', model: 'haiku' })] });
          const l = one(run(q), 'is:q');
          return [a.etiket, a.unvan, a.rol_metni, h.karakterKarti(a, w, NOW).baslik, h.rolAdi(a.etiket), l.etiket,
            one(run(working()), 'is:a').etiket]; })()""")
        self.assertEqual(out, ["yayin · Kıdemli Backend (Opus)", "Kıdemli", "Kıdemli Backend", "Kıdemli Backend",
                               "yayin · Kıdemli Backend", "yayin · Stajyer Mobil (Haiku)",
                               "yayin · Kıdemli (Opus)"])

    def test_the_qa_room_label_uses_the_test_specialisation(self):
        out = run_dav("[one(run(working({step_kind: 'kod-inceleme', tier: 'inceleme', uzmanlik: 'test'}, "
                      "{step_kind: 'kod-inceleme', tier: 'inceleme'})), 'is:a').etiket, "
                      "one(run(working({tier: 'inceleme'}, {tier: 'inceleme'})), 'is:a').etiket]")
        self.assertEqual(out, ["yayin · Kıdemli Tester (Opus)", "yayin · Kıdemli Tester (Opus)"])

    def test_the_running_table_and_the_board_show_the_role(self):
        out = run_scene("""(() => { const r = h.calisanlarTablosu(working({ uzmanlik: 'ui' }), NOW)[0];
          return [h.calisanRolu(r.unvan, r.model), h.calisanIpucu(r.unvan, r.model)]; })()""")
        self.assertEqual(out, ["Kıdemli UI", "Kıdemli UI · model: Opus"])
        self.assertEqual(run_js("[t.calisanMetni('opus', 'backend'), t.calisanMetni('fable', 'analiz'), "
                                "t.calisanMetni('sonnet'), t.calisanMetni('sonnet', 'genel'), t.calisanMetni('codex', 'test')]"),
                         ["Kıdemli Backend (Opus)", "Genel Müdür (Fable)", "Uzman (Sonnet)", "Uzman (Sonnet)",
                          "Dış denetçi (Codex)"])
        self.assertIn("calisanMetni(t.model, t.uzmanlik)", (WEB / "app.js").read_text(encoding="utf-8"))

    def test_the_software_managers_card_lists_its_people_by_specialisation(self):
        out = run_scene("""(() => { const s = st({ projects: [{ name: 'yayin' }, { name: 'pazar' }], tasks: [
            task('a.md', 'calisiyor', { uzmanlik: 'mobil' }),
            task('b.md', 'calisiyor', { project: 'pazar', model: 'haiku', tier: 'kolay', uzmanlik: 'mobil' }),
            task('c.md', 'calisiyor', { uzmanlik: 'backend' }), task('e.md', 'calisiyor', { model: 'sonnet', tier: 'genel' })] });
          return h.mudurKarti(s, NOW, 'yazilim').satirlar.filter((r) => r.ad === 'Uzmanlığa göre' || (r.ad === '' && /: /.test(r.metin) && !/^Uzmanlıklar/.test(r.metin)))
            .map((r) => r.metin); })()""")
        self.assertEqual(out, ["Backend: yayin Kıdemli", "Mobil: yayin Kıdemli, pazar Stajyer", "Genel: yayin Uzman"])

    def test_the_hr_card_lists_every_specialisation_with_this_months_jobs(self):
        out = run_scene("""(() => { const s = st(); const veri = { muhasebe: { bu_ay_uzmanlik: [
            { uzmanlik: 'mobil', is_sayisi: 3, usd: 1 }, { uzmanlik: '', is_sayisi: 2, usd: 0 }] } };
          return h.karakterKarti(one(run(s), 'sus:ik'), s, NOW, { veri }).satirlar.map((r) => [r.ad, r.metin]); })()""")
        start = [i for i, (k, _) in enumerate(out) if k == "Uzmanlıklar · bu ay"][0]
        self.assertEqual([v for _, v in out[start:start + 8]],
                         ["Backend · 0 iş", "UI · 0 iş", "Mobil · 3 iş", "Tester · 0 iş", "Analist · 0 iş",
                          "Güvenlik · 0 iş", "Genel · 0 iş", "uzmanlığı kayıtlı değil · 2 iş"])



SISTEM_VERISI = """{ cpu: { cekirdek: 10, yuk: [7.4, 6.8, 6.1], yuk_orani: 0.94 }, seviye: 'sari',
  bellek: { toplam_gb: 16, kullanilan_gb: 12, baski: 'normal', bos_yuzde: 25 }, disk: { toplam_gb: 460, bos_gb: 66.6, dolu_yuzde: 72 },
  pil: { yuzde: 94, durum: 'şarj oluyor' }, acik_kalma_sn: 788400, docker: { konteyner: 0, cpu: 0, bellek_mb: 0 },
  gruplar: [{ ad: 'Java', sayi: 2, cpu: 80.4, bellek_mb: 2048 }, { ad: 'Claude oturumları', sayi: 4, cpu: 7, bellek_mb: 1300, bosta: 3 }],
  oneriler: [{ metin: 'a' }, { metin: 'b' }], domainler: { liste_var: false, metin: 'Domain listesi henüz yok' } }"""


@unittest.skipUnless(NODE, "node is not installed")
class SharedCardTest(unittest.TestCase):
    """Owner decision 2026-11-13 ("kartlar okunaklı olsun"): one card component for every character — kartDuzeni groups the
    rows into titled sections with label / value rows, status bars, real tables and long lists folded; app.js draws
    it with createElement / textContent only. Only the presentation changes: every row's data is kept."""

    def test_the_rules_group_rows_into_titled_sections_and_keep_every_text(self):
        rows = [{"ad": "Görevi", "metin": "g"}, {"ad": "Durum", "metin": "d"},
                {"ad": "Takılan işler", "metin": "t1"}, {"ad": "", "metin": "t2"},
                {"ad": "Not", "metin": "n"},
                {"ad": "", "metin": "Kadro: 2 kişi", "uyeler": ["a", "b"], "anahtar": "k"},
                {"ad": "Bütçe", "metin": "b", "bolum": "Bütçe", "cubuk": {"yuzde": 140, "ton": "x"}},
                {"ad": "Bütçe uyarısı", "metin": "u1", "bolum": "Bütçe",
                 "tablo": {"anahtar": "u", "basliklar": ["İş", "Durum"], "satirlar": [["A", "aştı"]]}},
                {"ad": "Bütçe uyarısı", "metin": "u2", "bolum": "Bütçe",
                 "tablo": {"anahtar": "u", "basliklar": ["İş", "Durum"], "satirlar": [["B", None]]}}]
        out = run_scene(f"h.kartDuzeni({{ satirlar: {json.dumps(rows)} }})")
        self.assertEqual([b["baslik"] for b in out], ["Özet", "Takılan işler", "Not", "Bütçe"])
        self.assertEqual(out[0]["ogeler"], [{"tur": "satir", "ad": "Görevi", "metin": "g"},
                                            {"tur": "satir", "ad": "Durum", "metin": "d"}])
        self.assertEqual(out[1]["ogeler"], [{"tur": "madde", "metin": "t1"}, {"tur": "madde", "metin": "t2"}])
        self.assertEqual(out[2]["ogeler"][1], {"tur": "grup", "metin": "Kadro: 2 kişi", "uyeler": ["a", "b"],
                                               "anahtar": "k"})
        butce = out[3]["ogeler"]
        self.assertEqual(butce[0]["cubuk"], {"yuzde": 100, "ton": "iyi"})  # clamped, an unknown tone is plain
        self.assertEqual(butce[1], {"tur": "tablo", "anahtar": "u", "baslik": "", "basliklar": ["İş", "Durum"],
                                    "satirlar": [["A", "aştı"], ["B", ""]]})  # one table for the rows in a row
        self.assertEqual(run_scene("h.kartDuzeni(null)"), [])

    def test_the_it_card_has_the_shift_table_status_bars_and_the_process_group_table(self):
        out = run_scene(f"""(() => {{ const s = st(); const a = {{ id: 'sus:sunucu:1', tur: 'sus', gorevli: 'sunucu', etiket: 'IT uzmanı' }};
          const k = h.karakterKarti(a, s, NOW, {{ veri: {{ sistem: {SISTEM_VERISI} }} }});
          return {{ k, b: h.kartDuzeni(k) }}; }})()""", NPC_PRELUDE)
        b = {x["baslik"]: x for x in out["b"]}
        names = [x["baslik"] for x in out["b"]]
        self.assertEqual(names[names.index("Nöbet"):names.index("Nöbet") + 3], ["Nöbet", "Bilgisayar", "Süreç grupları"])
        [ekip] = [o for o in b["Nöbet"]["ogeler"] if o["tur"] == "tablo"]
        self.assertEqual((ekip["baslik"], ekip["basliklar"]), ("Ekip", ["Kişi", "Durum", "Vardiya"]))
        self.assertEqual(len(ekip["satirlar"]), 3)
        self.assertEqual([r[1] for r in ekip["satirlar"]].count("nöbette"), 1)
        nobette = [r for r in ekip["satirlar"] if r[1] == "nöbette"][0]
        self.assertRegex(nobette[2], r"^\d\d:\d\d–\d\d:\d\d$")  # the current shift's hours
        self.assertTrue(all(r[2].startswith("sıradaki ") for r in ekip["satirlar"] if r[1] != "nöbette"))
        bars = {o["ad"]: o.get("cubuk") for o in b["Bilgisayar"]["ogeler"] if o["tur"] == "satir"}
        self.assertEqual(bars["İşlemci"], {"yuzde": 94, "ton": "kotu"})
        self.assertEqual(bars["Bellek"], {"yuzde": 75, "ton": "uyari"})
        self.assertEqual(bars["Disk"], {"yuzde": 72, "ton": "uyari"})
        self.assertIsNone(bars["Pil"])
        [surec] = b["Süreç grupları"]["ogeler"]
        self.assertEqual(surec["basliklar"], ["Grup", "Adet", "CPU %", "Bellek", "Boşta"])
        self.assertEqual(surec["satirlar"], [["Java", "2", "%80", "2,0 GB", ""], ["Claude oturumları", "4", "%7", "1,3 GB", "3"]])
        # every row that is not a table row keeps its text somewhere in the layout
        shown = [o.get("metin") for x in out["b"] for o in x["ogeler"]]
        for r in out["k"]["satirlar"]:
            if "tablo" not in r:
                self.assertIn(r["metin"], shown)

    def test_the_accountant_shows_the_spending_and_the_budget_as_tables(self):
        out = run_scene("""(() => { const s = st(); const m = { bugun: { usd: 1.21, is_sayisi: 2,
            proje: [{ proje: 'yayin', usd: 1.2, token: 400000, is_sayisi: 1 }, { proje: 'kasa', usd: 0.01, is_sayisi: 1 }], rol: [] },
          butce: { calisan: 1, harcanan_usd: 2.9, butce_usd: 3,
            dikkat: [{ not: 'a.md', baslik: 'Giriş', usd: 2.9, token: 800000, butce: 3, durum: 'yakin' }] } };
          return h.kartDuzeni(h.karakterKarti(one(run(s), 'sus:muhasebe'), s, NOW, { veri: { muhasebe: m } })); })()""",
                        NPC_PRELUDE)
        b = {x["baslik"]: x["ogeler"] for x in out}
        [pr] = [o for o in b["Kullanım"] if o["tur"] == "tablo"]
        self.assertEqual((pr["baslik"], pr["basliklar"]), ("Bugün · projeye göre", ["Proje", "Kullanım", "İş"]))
        self.assertEqual(pr["satirlar"], [["yayin", "400 bin token · ≈$1,20", "1"], ["kasa", "≈$0,01", "1"]])
        butce = b["Kullanım sınırı"]
        self.assertEqual(butce[0]["cubuk"], {"yuzde": 97, "ton": "kotu"})
        self.assertEqual(butce[1]["satirlar"], [["Giriş", "800 bin token · ≈$2,90", "≈$3,00", "sınıra yakın"]])

    def test_the_page_draws_every_character_card_with_the_one_component_and_text_only(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        show = app[app.index("function kartGoster("):app.index("function kartIcerigi(")]
        self.assertIn("kartIcerigi(k, acik)", show)
        self.assertIn("karakterKarti(a, state, Date.now()", show)
        self.assertNotIn("karakter-kart-satirlar", app)  # the old cramped dl is gone
        body = app[app.index("function kartIcerigi("):app.index("// The data some staff cards read")]
        for need in ("kartDuzeni(k)", "'kart-bolum-baslik'", "'kart-fazla'", "KART_LISTE_SINIRI", "h('caption'",
                     "h('th'", "`kart-cubuk ton-", "dolu.style.width", "'karakter-kart-grup'"):
            self.assertIn(need, body)
        self.assertNotIn("innerHTML", body)
        self.assertIn("const KART_KENAR = 16;", app)
        self.assertEqual(app.count("karakterKarti("), 1)  # one place builds a character card
        css = (WEB / "style.css").read_text(encoding="utf-8")
        rule = re.search(r"\.karakter-kart \{([^}]*)\}", css).group(1)
        for need in ("min(560px, 92vw, calc(100vw - 32px))", "80vh", "overflow: auto", "font-size: 14px"):
            self.assertIn(need, rule)
        self.assertIn(".kart-tablo-wrap { max-width: 100%; overflow-x: auto;", css)


@unittest.skipUnless(NODE, "node is not installed")
class SidePanelAndTabsTest(unittest.TestCase):
    """The owner, 2026-11-13: the right panel keeps only "CEO soruyor" and collapses when it is empty; Zamanlanmış and Son
    olanlar are top-bar tabs next to Kalite (full-panel views, also on a phone)."""

    def setUp(self):
        self.html = (WEB / "index.html").read_text(encoding="utf-8")
        self.app = (WEB / "app.js").read_text(encoding="utf-8")
        self.css = (WEB / "style.css").read_text(encoding="utf-8")

    def test_the_side_panel_keeps_only_the_questions(self):
        side = self.html[self.html.index('<aside class="side"'):self.html.index("</aside>")]
        self.assertIn('id="ask-list"', side)
        for gone in ('id="sched"', 'id="models"', 'id="feed"', "feed-katla", "Çalışanlar", "Zamanlanmış", "Son olanlar"):
            self.assertNotIn(gone, side)
        for gone in ("ofis.sonOlanlarKapali", "modelsDetails", "$('models-list')", "$('sched-list')", "fillFeed($('feed')"):
            self.assertNotIn(gone, self.app)
        self.assertIn("modelSatirlari(state.modeller", self.app)  # the helper stays (the popover, the Komuta masası)

    def test_an_empty_panel_collapses_and_the_scene_takes_the_width(self):
        body = self.app[self.app.index("function yanPanel("):]
        body = body[:body.index("\n}\n")]
        self.assertIn("const bos = !askItems().length;", body)  # questions only: the warnings are top-bar chips
        self.assertIn("classList.toggle('yan-bos', bos)", body)
        self.assertIn("office.resize()", body)
        self.assertIn("html.yan-bos { --side-w: 0px; }", self.css)
        self.assertIn("html.yan-bos .side { display: none; }", self.css)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        inset = scene[scene.index("rightInset(w) {"):scene.index("resize() {")]
        self.assertIn("side > 0 ?", inset)  # 0px is not read as "unset" (parseFloat('0px') || 360 was 360)

    def test_the_warnings_are_top_bar_chips(self):
        # The owner, 2026-11-13: the approval-backlog and "İletişim uyarısı" strips left the right panel; each is a chip in
        # the top bar, hidden while there is nothing to say, whose click opens the same detail text
        side = self.html[self.html.index('<aside class="side"'):self.html.index("</aside>")]
        for gone in ('id="onay-birikti"', 'id="po-warn"', "İletişim uyarısı"):
            self.assertNotIn(gone, side)
        top = self.html[self.html.index('<div class="topbar-right">'):self.html.index("</header>")]
        for chip in ("onay-birikti", "po-warn"):
            self.assertRegex(top, rf'<button class="pill pill-btn uyari-cip" id="{chip}" type="button" hidden[^>]*'
                                  rf'aria-controls="{chip}-detay"')
            self.assertRegex(top, rf'id="{chip}-detay" role="dialog"[^>]*hidden')
        self.assertIn('id="onay-birikti-text"', top)
        self.assertIn('id="po-warn-list"', top)
        self.assertIn("const UYARI_CIPLERI = ['onay-birikti', 'po-warn', 'limit-pill'];", self.app)
        po = self.app[self.app.index("function renderPostoffice("):]
        po = po[:po.index("\n}\n")]
        self.assertIn("box.hidden = lines.length === 0;", po)
        self.assertNotIn("yanPanel()", po)
        self.assertIn(".uyari-detay[hidden] { display: none; }", self.css)

    def test_two_new_tabs_after_kalite_open_full_panel_views(self):
        tabs = re.findall(r'data-tab="([a-z]+)"', self.html)
        self.assertEqual(tabs, ["ofis", "kararlar", "isler", "raporlar", "kalite", "zamanlanmis", "olaylar", "ayarlar"])
        self.assertIn(">Zamanlanmış</span> <span", self.html)
        self.assertIn('data-tab="olaylar" aria-selected="false" data-t="Son olanlar">Son olanlar</button>', self.html)
        for name in ("zamanlanmis", "olaylar"):
            self.assertIn(f'<section class="overlay overlay-wide" id="overlay-{name}" hidden>', self.html)
        self.assertIn("const OVERLAYS = ['kararlar', 'isler', 'raporlar', 'kalite', 'zamanlanmis', 'olaylar', 'ayarlar'];", self.app)
        heads = re.findall(r"<th scope=\"col\"(?: data-t=\"[^\"]*\")?>([^<]+)</th>", self.html[self.html.index('id="overlay-zamanlanmis"'):])[:6]
        self.assertEqual(heads, ["Ad", "Proje", "Ne zaman", "Sonraki", "Durum", "Son koşu"])
        # on a phone the tab bar scrolls sideways (the same tabs); nothing hides these two
        self.assertNotRegex(self.css, r'data-tab="(zamanlanmis|olaylar)"[^{]*\{[^}]*display: none')

    def test_the_schedule_tab_links_the_runs_and_the_timeline_reuses_the_notice_card(self):
        sched = self.app[self.app.index("function renderSchedules("):self.app.index("// The workers' status")]
        self.assertIn("notLinki(x.is, x.is, 'Isler')", sched)
        self.assertIn("notLinki(x.son_is, x.son_is, 'Isler')", sched)
        self.assertIn("notLinki(r.ad, r.ad, 'Zamanlanmis')", sched)
        olay = self.app[self.app.index("function renderOlaylar("):]
        olay = olay[:olay.index("\n}\n")]
        self.assertIn("noticeCard(item.m)", olay)  # a notice is the chat's own card
        self.assertIn("olayRozeti(item.tur)", olay)
        self.assertIn("`msg relay notice ${r.tone}`", olay)
        self.assertNotIn("innerHTML", olay + sched)
        self.assertIn("'bildirim', m);", self.app)  # notices keep their message for the timeline
        self.assertEqual(run_js("['is-bitti', 'takildi', 'soru', 'yok'].map((x) => t.olayRozeti(x).tone)"),
                         ["done", "blocked", "ask", "info"])


@unittest.skipUnless(NODE, "node is not installed")
class JobToastTest(unittest.TestCase):
    """The owner, 2026-11-14: a finished job, a stuck one, a decision waiting and a manager decision pop up as a small toast
    (top-right, ~6 s, at most 3); only events that are new since the page loaded."""

    PREV = """{ tasks: [{ note: 'a.md', project: 'sozluk', title: 'Okuma işi', status: 'calisiyor' },
        { note: 'b.md', project: 'yayin', title: 'Giriş hatası', status: 'calisiyor' },
        { note: 'c.md', project: 'blog', title: 'Eski iş', status: 'bitti' }],
      decisions: [{ note: 'k0.md', project: 'blog', title: 'Eski soru' }],
      mudur_kararlari: [{ note: 'm1.md', project: 'yayin', title: 'Hangi kütüphane?', durum: 'bakiyor', unvan: 'Yazılım Müdürü' }] }"""
    CUR = """{ tasks: [{ note: 'a.md', project: 'sozluk', title: 'Okuma işi', status: 'bitti' },
        { note: 'b.md', project: 'yayin', title: 'Giriş hatası', status: 'tikandi' },
        { note: 'c.md', project: 'blog', title: 'Eski iş', status: 'bitti' },
        { note: 'd.md', project: 'atolye', title: 'Yeni iş', status: 'calisiyor' }],
      decisions: [{ note: 'k0.md', project: 'blog', title: 'Eski soru' }, { note: 'k1.md', project: 'yayin', title: 'Hangi renk?' }],
      mudur_kararlari: [{ note: 'm1.md', project: 'yayin', title: 'Hangi kütüphane?', durum: 'cevapladi', unvan: 'Yazılım Müdürü', is: 'b.md' }] }"""

    def test_the_toast_text_for_each_new_event(self):
        out = run_js(f"t.toastOlaylari({self.PREV}, {self.CUR})")
        self.assertEqual([(x["tur"], x["ikon"], x["metin"]) for x in out], [
            ("bitti", "✓", "sozluk işi bitti · Okuma işi"),
            ("takildi", "!", "yayin işi takıldı · Giriş hatası"),
            ("soru", "?", "CEO soruyor · yayin: Hangi renk?"),
            ("mudur", "✓", "Müdür kararı · Yazılım Müdürü · yayin: Hangi kütüphane?"),
        ])
        self.assertEqual((out[0]["is"], out[2]["karar"], out[3]["karar"]), ("a.md", "k1.md", "m1.md"))
        self.assertEqual(run_js("""t.toastOlaylari({ tasks: [{ note: 'x.md', status: 'baslatiliyor', project: 'p', title: 'T' }] },
          { tasks: [{ note: 'x.md', status: 'basarisiz', project: 'p', title: 'T' }] })[0].metin"""), "p işi başlatılamadı · T")

    def test_only_new_events_never_those_from_before_the_page_loaded(self):
        self.assertEqual(run_js(f"t.toastOlaylari(null, {self.CUR})"), [])  # first snapshot: nothing pops up
        self.assertEqual(run_js(f"t.toastOlaylari({self.CUR}, {self.CUR})"), [])  # no change: nothing
        self.assertEqual(run_js("t.toastOlaylari({}, { tasks: 'x', decisions: [null, 1] })"), [])  # bad input

    def test_the_stack_keeps_at_most_three_newest_first_one_per_event(self):
        out = run_js("""(() => { const it = (k) => ({ anahtar: k, metin: k });
          const a = t.toastYigini([], [it('1'), it('2')]);
          const b = t.toastYigini(a, [it('3'), it('4')]);
          const c = t.toastYigini(b, [it('4')]);
          return { a: a.map((x) => x.anahtar), b: b.map((x) => x.anahtar), c: c.map((x) => x.anahtar),
            max: t.TOAST_EN_COK, sure: t.TOAST_SURE_MS }; })()""")
        self.assertEqual(out["a"], ["2", "1"])
        self.assertEqual(out["b"], ["4", "3", "2"])  # the oldest drops off
        self.assertEqual(out["c"], ["4", "3", "2"])  # the same event twice: one toast
        self.assertEqual((out["max"], out["sure"]), (3, 6000))

    def test_the_page_wiring(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("isToastlari(toastOlaylari(prev, s));", app)
        body = app[app.index("function isToastlari"):app.index("function isToastlari") + 1400]
        self.assertNotIn("innerHTML", body)
        self.assertNotRegex(app, r"Notification\.requestPermission|new Audio\(")
        self.assertIn('<div class="is-toastlar" id="is-toastlar" role="status" aria-live="polite"></div>',
                      (WEB / "index.html").read_text(encoding="utf-8"))
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".is-toastlar { position: fixed; top: 64px; right: var(--s2);", css)
        self.assertIn("@media (max-width: 600px) { .is-toastlar { left: var(--s2); right: var(--s2); width: auto; } }", css)


@unittest.skipUnless(NODE, "node is not installed")
class CeoUnreadTest(unittest.TestCase):
    """The owner, 2026-11-14: a CEO reply written while the chat is closed pops up as "CEO yazdı: ..." and counts on the
    "CEO ile sohbet" button; the tab title gets the count while the tab is hidden."""

    def test_toasts_only_for_new_ceo_lines_with_the_first_80_chars(self):
        out = run_js("""t.ceoToastlari([
          { role: 'ceo', time: 't1', text: 'Merhaba Selin, iş bitti.' },
          { role: 'deniz', time: 't2', text: 'selam' },
          { role: 'system', kind: 'notice', time: 't3', text: 'x' },
          { role: 'ceo', time: 't4', text: '   ' },
          { role: 'ceo', time: 't5', text: 'a'.repeat(200) }], (m) => m.time)""")
        self.assertEqual([x["metin"] for x in out][0], "CEO yazdı: Merhaba Selin, iş bitti.")
        self.assertEqual(len(out), 2)  # The owner's line, notices and empty lines never toast
        self.assertEqual((out[0]["tur"], out[0]["mesaj"], out[0]["anahtar"]), ("ceo", "t1", "ceo:t1"))
        self.assertEqual(len(out[1]["metin"]) - len("CEO yazdı: "), 80)
        self.assertTrue(out[1]["metin"].endswith("…"))
        self.assertEqual(run_js("t.ceoToastlari([], null)"), [])  # nothing new (e.g. the lines that existed at load)
        self.assertEqual(run_js("t.ceoToastlari(null)"), [])

    def test_the_chat_counts_as_unseen_when_closed_or_the_tab_is_hidden(self):
        self.assertEqual(run_js("[t.sohbetGorulmedi(false, false, false), t.sohbetGorulmedi(true, false, false),"
                                " t.sohbetGorulmedi(false, true, false), t.sohbetGorulmedi(true, false, true)]"),
                         [True, False, False, True])

    def test_badge_count_grows_while_unseen_and_resets_when_the_chat_is_seen(self):
        self.assertEqual(run_js("[t.okunmamisSayi(0, 1, true), t.okunmamisSayi(2, 3, true), t.okunmamisSayi(5, 1, false),"
                                " t.okunmamisSayi(undefined, NaN, true)]"), [1, 5, 0, 0])
        self.assertEqual(run_js("[t.okunmamisMetni(0), t.okunmamisMetni(3), t.okunmamisMetni(10), t.okunmamisMetni(NaN)]"),
                         ["", "3", "9+", ""])

    def test_tab_title_prefix_counts_unread_only_while_hidden_and_restores(self):
        self.assertEqual(run_js("""[t.sekmeBasligi('Atölye', t.sekmeSayisi(0, 2, true)),
          t.sekmeBasligi('Atölye', t.sekmeSayisi(0, 2, false)),
          t.sekmeBasligi('Atölye', t.sekmeSayisi(1, 2, true)),
          t.sekmeBasligi('(3) Atölye', t.sekmeSayisi(0, 0, true))]"""),
                         ["(2) Atölye", "Atölye", "(3) Atölye", "Atölye"])

    def test_the_page_wiring(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("if (chatSeeded) ceoYazdi(fresh);", app)  # never for the lines that existed at load
        body = app[app.index("function ceoYazdi"):app.index("function ceoYazdi") + 1800]
        self.assertIn("sohbetGorulmedi(", body)
        self.assertIn("isToastlari(toasts)", body)
        self.assertNotIn("innerHTML", body)
        self.assertNotRegex(app, r"Notification\.requestPermission|new Audio\(")
        self.assertIn("function ceoOkundu() { ceoOkunmamis = 0;", app)
        self.assertRegex(app, r"function openDrawer\(\) \{\n  ceoOkundu\(\);")
        self.assertIn("  ceoOkundu();\n", app[app.index("function openKomuta"):app.index("function closeKomuta")])
        self.assertIn("if (item.tur === 'ceo') ceoMesajinaGit(item.mesaj);", app)
        self.assertIn("b.dataset.anahtar = chatKey(m);", app)
        self.assertIn("document.title = sekmeBasligi(baseTitle, sekmeSayisi(kararSayisi, ceoOkunmamis, document.hidden));", app)
        self.assertIn('id="open-chat-top-sayi" hidden></span></button>', (WEB / "index.html").read_text(encoding="utf-8"))
        self.assertIn(".rozet-sayi[hidden] { display: none; }", (WEB / "style.css").read_text(encoding="utf-8"))


class TopBarOneLineTest(unittest.TestCase):
    """The owner, 2026-11-14: the top bar wrapped onto two lines on a ~2000px screen; every item stays on one line."""

    def test_header_items_never_wrap_and_the_tab_row_shrinks(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn(".topbar .tab, .topbar .pill, .topbar .btn, .topbar .clock, .topbar-right > *, .brand { white-space: nowrap; }", css)
        self.assertIn(".topbar .tabs { min-width: 0; flex: 0 1 auto; overflow-x: auto;", css)  # scrolls in its own row
        self.assertIn("@media (max-width: 1700px) { .clock-date { display: none; }", css)  # the clock shortens first
        self.assertRegex(css, r"@media \(min-width: 821px\) \{\n  \.topbar \{ gap: var\(--s2\); \}\n  \.topbar \.tab \{ padding: 3px 12px; font-size: 13px; \}")


# A minimal DOM for node: enough of createElement / createTextNode / append / textContent to run raporDugumu.
FAKE_DOC_JS = """
class Node_ { constructor(tag) { this.tag = tag; this.kids = []; this.className = ''; this._t = null; this.ev = {}; }
  append(...xs) { for (const x of xs) this.kids.push(x); }
  addEventListener(n, f) { this.ev[n] = f; }
  set textContent(v) { this._t = String(v); this.kids = []; } get textContent() { return this._t; } }
const doc = { createElement: (t) => new Node_(t), createTextNode: (s) => ({ text: String(s) }) };
const dump = (n) => n.text !== undefined ? n.text : { tag: n.tag, cls: n.className, text: n._t, kids: n.kids.map(dump) };
"""


@unittest.skipUnless(NODE, "node is not installed")
class ProjectReportFormatterTest(unittest.TestCase):
    """The owner, 2026-11-14: the "iş bitti" card showed the project's report as one plain blob; now a short summary on top
    and the report structured (headings, lists, tables) under a collapsed "Teknik rapor" toggle."""

    REPORT = ("TD-415 SIR ENVANTERİ VE TEMİZLİK PLANI (kök repo)\n"
              "ÖZET: Sırlar envanterlendi. İkinci cümle burada.\n"
              "1) ENVANTER (tür | yer | commit | servis | canlı mı | kim değiştirir)\n"
              "- DB parolası | a.md | abc123 | api | evet | ben\n"
              "- API anahtarı | b.md | def456 | web | hayır | sen\n"
              "KÖK REPO (üç dosya):\n"
              "- ilk madde\n• ikinci madde\n* üçüncü madde\n"
              "Düz bir açıklama satırı.")

    def blocks(self, text):
        return run_js(f"t.raporBicimle({json.dumps(text)})")

    def test_headings_lists_and_a_table_from_the_paren_header(self):
        b = self.blocks(self.REPORT)
        self.assertEqual([x["tip"] for x in b],
                         ["baslik", "baslik", "paragraf", "baslik", "tablo", "baslik", "liste", "paragraf"])
        self.assertEqual(b[0]["metin"], "TD-415 SIR ENVANTERİ VE TEMİZLİK PLANI (kök repo)")
        self.assertEqual((b[1]["metin"], b[2]["metin"]), ("ÖZET:", "Sırlar envanterlendi. İkinci cümle burada."))
        self.assertEqual(b[3]["metin"].startswith("1) ENVANTER"), True)
        self.assertEqual(b[4]["baslik"], ["tür", "yer", "commit", "servis", "canlı mı", "kim değiştirir"])
        self.assertEqual(b[4]["satirlar"][1], ["API anahtarı", "b.md", "def456", "web", "hayır", "sen"])
        self.assertEqual(b[5]["metin"], "KÖK REPO (üç dosya):")  # a line ending with ":" is a heading
        self.assertEqual(b[6]["ogeler"], ["ilk madde", "ikinci madde", "üçüncü madde"])

    def test_numbered_caps_heading_but_not_a_numbered_sentence(self):
        b = self.blocks("2) SONUÇ\n3) bu bir cümle gibi devam eder")
        self.assertEqual([x["tip"] for x in b], ["baslik", "paragraf"])

    def test_table_without_a_paren_header_uses_its_first_line(self):
        b = self.blocks("a | b | c\n1 | 2 | 3\n4 | 5 | 6")
        self.assertEqual(b, [{"tip": "tablo", "baslik": ["a", "b", "c"], "satirlar": [["1", "2", "3"], ["4", "5", "6"]]}])

    def test_a_single_pipe_or_uneven_rows_are_not_a_table(self):
        self.assertEqual([x["tip"] for x in self.blocks("- DB parolası | PGPASSWORD='x' literal: a.md")], ["liste"])
        self.assertEqual([x["tip"] for x in self.blocks("a | b | c\n1 | 2")], ["paragraf", "paragraf"])

    def test_a_long_paragraph_is_split_at_sentence_ends_but_not_after_a_digit(self):
        sentence = "Bu bir uzun cümledir ve epey yer kaplar, çünkü ayrıntıyı anlatır"
        text = ". ".join([sentence] * 8) + ". Kontrol 2. denemede geçti."
        b = self.blocks(text)
        self.assertGreater(len(b), 1)
        self.assertTrue(all(x["tip"] == "paragraf" and len(x["metin"]) <= 300 for x in b))
        self.assertEqual(" ".join(x["metin"] for x in b), text)  # text stays exact
        self.assertIn("Kontrol 2. denemede geçti.", b[-1]["metin"])

    def test_a_long_file_list_is_shortened_to_five_items(self):
        files = [f"dosya{i}.md" for i in range(12)]
        line = "Dokunulan dosyalar: " + ", ".join(files) + "."
        u = run_js(f"t.uzunListe({json.dumps(line)})")
        self.assertEqual(u["kisa"], "Dokunulan dosyalar: " + ", ".join(files[:5]) + "… ve 7 dosya daha")
        self.assertEqual(u["tam"], line)
        self.assertIsNone(run_js("t.uzunListe('a.md, b.md, c.md')"))
        self.assertIsNone(run_js("t.uzunListe('bir iki, üç dört, beş, altı, yedi, sekiz, dokuz, on')"))

    def test_html_is_never_interpreted(self):
        payload = "<img src=x onerror=alert(1)>\n- <b>kalın</b> [bağlantı](javascript:alert(1))"
        out = run_js(f"(() => {{ {FAKE_DOC_JS} return dump(t.raporDugumu({json.dumps(payload)}, doc)); }})()")
        dumped = json.dumps(out, ensure_ascii=False)
        self.assertIn("<img src=x onerror=alert(1)>", dumped)  # kept as text
        self.assertNotIn('"tag": "img"', dumped)
        self.assertNotIn('"tag": "a"', dumped)
        src = (WEB / "ofis-text.js").read_text(encoding="utf-8")
        body = src[src.index("export function raporDugumu"):src.index("export function raporOzeti")]
        self.assertNotIn("innerHTML", body)
        self.assertNotRegex(body, r"insertAdjacentHTML|outerHTML")

    def test_the_toggle_expands_and_collapses_a_long_list(self):
        line = "Dosyalar: " + ", ".join(f"d{i}.py" for i in range(10))
        out = run_js(f"""(() => {{ {FAKE_DOC_JS}
          const root = t.raporDugumu({json.dumps(line)}, doc);
          const p = root.kids[0]; const span = p.kids[0]; const btn = p.kids[2];
          const before = [span.textContent, btn.textContent]; btn.ev.click();
          const after = [span.textContent, btn.textContent]; return {{ before, after }}; }})()""")
        self.assertTrue(out["before"][0].endswith("… ve 5 dosya daha"))
        self.assertEqual(out["before"][1], "tümünü göster")
        self.assertEqual(out["after"], [line, "daha az göster"])

    def test_the_card_summary_is_one_short_sentence_and_the_report_is_kept_whole(self):
        long_first = "Çok uzun bir özet cümlesi " + "uzayıp gider " * 30 + "sonunda biter. İkinci."
        text = ("yayin işi bitti: Sır temizliği (2026-11-14-100000-yayin). Kontrol geçti (deneme 1; kanıt iş notunda). Özet:\n"
                + "\n".join("> " + x for x in ["TD-415 SIR ENVANTERİ", "ÖZET: " + long_first, "- madde"]))
        c = run_js(f"t.bildirimKarti({json.dumps(text)})")
        ozet = dict((k, v) for k, v in c["satirlar"])["Özet"]
        self.assertLessEqual(len(ozet), 160)
        self.assertTrue(ozet.startswith("Çok uzun bir özet"))
        self.assertEqual(c["teknik"], "TD-415 SIR ENVANTERİ\nÖZET: " + long_first + "\n- madde")
        self.assertEqual(c["teknikBaslik"], "Teknik rapor (projenin kendi metni)")
        short = run_js("t.bildirimKarti('yayin işi bitti: X (2026-11-14-100000-yayin). Kontrol yok. Özet:\\n> Tamam. İkinci cümle.')")
        self.assertEqual(dict((k, v) for k, v in short["satirlar"])["Özet"], "Tamam.")
        self.assertEqual(run_js("t.bildirimKarti('tek satır').teknik"), "")

    def test_summary_helper_picks_the_paragraph_after_ozet(self):
        self.assertEqual(run_js(f"t.raporOzeti({json.dumps(self.REPORT)})"), "Sırlar envanterlendi.")

    def test_collapsed_by_default_and_wired(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for sel in (".rapor-baslik", ".rapor-liste", ".rapor-tablo", ".rapor-toggle"):
            self.assertIn(sel, css)
        text_js = (WEB / "ofis-text.js").read_text(encoding="utf-8")
        self.assertIn("teknik: ctx.rapor", text_js)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        if "raporDugumu" in app:  # wired by app.js: a closed <details> (open only when the user opened it)
            body = app[app.index("function noticeCard"):app.index("function noticeActions")]
            self.assertIn("raporDugumu(", body)
            self.assertIn("c.teknikBaslik", body)
            self.assertNotIn("innerHTML", body)



def run_yol(expr):
    """Evaluates `expr` with web/is-akisi.js imported as `y` (the per-job progress line)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "ofis-davranis.mjs").write_text(
            webkopya.mjs_yap((WEB / "ofis-davranis.js").read_text(encoding="utf-8")), encoding="utf-8")
        module = as_module("is-akisi.js", tmp)
        module.write_text(webkopya.mjs_yap(module.read_text(encoding="utf-8")), encoding="utf-8")
        code = (f"import * as y from {json.dumps(module.as_uri())};\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def yol_of(**steps):
    """A task's server-side yol: every step bekliyor unless given as adim=(durum, zaman, not)."""
    out = []
    for adim in ("alindi", "verildi", "calisiyor", "kontrol", "rapor", "ceo", "iletildi"):
        durum, zaman, note = (tuple(steps.get(adim) or ("bekliyor",)) + ("", ""))[:3]
        out.append({"adim": adim, "durum": durum, "zaman": zaman, "not": note})
    return out


@unittest.skipUnless(NODE, "node is not installed")
class JobPathTest(unittest.TestCase):
    """The per-job progress line (web/is-akisi.js; owner decision 2026-11-14)."""

    def steps(self, task):
        return run_yol(f"y.yolAdimlari({json.dumps(task)})")

    def test_labels_times_and_the_current_step(self):
        task = {"project": "yayin", "status": "calisiyor", "tier": "kod", "uzmanlik": "backend",
                "yol": yol_of(alindi=("tamam", "2026-11-14T09:58:00"), verildi=("tamam", "2026-11-14T10:00:00"),
                              calisiyor=("simdi",))}
        s = self.steps(task)
        self.assertEqual([x["etiket"] for x in s],
                         ["CEO aldı", "Kıdemli Backend aldı", "yayin masasında çalışıyor", "Kontrol", "rapor geldi",
                          "CEO'ya ulaştı", "sana iletildi"])
        self.assertEqual([(x["sinif"], x["ek"]) for x in s[:4]],
                         [("tamam", "09:58"), ("tamam", "10:00"), ("simdi", "şimdi"), ("bekliyor", "")])
        self.assertEqual(run_yol(f"y.yolOzeti({json.dumps(task)})"), "yayin masasında çalışıyor")

    def test_an_arge_job_names_the_arge_uzmani_and_the_arge_room(self):
        task = {"project": "arge", "status": "calisiyor", "tier": "genel", "yol": yol_of(
            alindi=("tamam", "2026-11-14T20:29:00"), verildi=("tamam", "2026-11-14T20:29:00"), calisiyor=("simdi",))}
        s = self.steps(task)
        self.assertEqual([x["etiket"] for x in s[:3]], ["CEO aldı", "Ar-Ge uzmanı aldı", "Ar-Ge odasında çalışıyor"])
        self.assertFalse(any("Genel Müdür" in x["etiket"] for x in s))

    def test_the_worker_title_follows_tier_and_specialisation_and_a_queued_job_is_not_taken_yet(self):
        task = {"project": "yayin", "tier": "genel", "uzmanlik": "guvenlik", "yol": yol_of(verildi=("simdi",))}
        self.assertEqual(self.steps(task)[1]["etiket"], "Uzman Güvenlik alacak")
        task["yol"] = yol_of(verildi=("tamam", "2026-11-14T10:00:00"))
        self.assertEqual(self.steps(task)[1]["etiket"], "Uzman Güvenlik aldı")
        self.assertEqual(self.steps({"project": "x", "yol": yol_of()})[1]["etiket"], "Çalışan aldı")

    def test_waiting_for_an_answer_or_a_permission_is_amber(self):
        for note, text in (("cevap", "senin cevabını bekliyor"), ("izin", "izin bekliyor")):
            task = {"project": "yayin", "yol": yol_of(calisiyor=("simdi", "", note))}
            s = self.steps(task)[2]
            self.assertEqual((s["sinif"], s["ek"]), ("bekleme", text))
            self.assertEqual(run_yol(f"y.yolOzeti({json.dumps(task)})"), f"yayin masasında çalışıyor · {text}")

    def test_stuck_cancelled_failed_are_red_with_the_reason(self):
        for durum_not, adim in ((("hata", "", "takıldı"), "calisiyor"), (("hata", "", "iptal"), "verildi"),
                                (("hata", "", "başlatılamadı"), "verildi"), (("hata", "", "üst katmana taşındı"), "kontrol")):
            s = {x["adim"]: x for x in self.steps({"yol": yol_of(**{adim: durum_not})})}
            self.assertEqual((s[adim]["sinif"], s[adim]["ek"]), ("hata", durum_not[2]))

    def test_no_kontrol_and_unknown_and_done_to_deniz(self):
        task = {"project": "kitap", "status": "bitti",
                "yol": yol_of(alindi=("tamam", "2026-11-14T09:00:00"), verildi=("tamam", "2026-11-14T09:01:00"),
                              calisiyor=("tamam", "2026-11-14T09:20:00"), kontrol=("atlandi",),
                              rapor=("tamam", "2026-11-14T09:20:00"), ceo=("tamam", "2026-11-14T09:21:00"),
                              iletildi=("tamam", "2026-11-14T09:22:00"))}
        s = self.steps(task)
        self.assertEqual((s[3]["etiket"], s[3]["sinif"]), ("Kontrol yok", "atlandi"))
        self.assertEqual(s[-1]["ek"], "09:22")
        self.assertEqual(run_yol(f"y.yolOzeti({json.dumps(task)})"), "sana iletildi")
        task["yol"][-1] = {"adim": "iletildi", "durum": "bilinmiyor", "zaman": "", "not": ""}
        self.assertEqual(self.steps(task)[-1]["ek"], "bilinmiyor")
        self.assertEqual(run_yol(f"y.yolOzeti({json.dumps(task)})"), "CEO'ya ulaştı")  # never claims the last step

    def test_a_task_without_a_line_and_bad_values(self):
        self.assertEqual(self.steps({"status": "bitti"}), [])
        self.assertEqual(run_yol("y.yolOzeti(null)"), "")
        s = self.steps({"yol": [{"adim": "alindi", "durum": "<b>", "zaman": "x"}]})
        self.assertEqual((s[0]["durum"], s[0]["ek"]), ("bekliyor", ""))
        self.assertEqual(run_yol("y.saatDakika('2026-11-14T07:05:09')"), "07:05")


class JobPathWiringTest(unittest.TestCase):
    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_compact_line_names_its_step_for_screen_readers(self):
        task = {"project": "yayin", "yol": yol_of(alindi=("tamam", "2026-11-14T09:58:00"), calisiyor=("simdi",))}
        self.assertEqual(run_yol(f"y.yolEtiketi({json.dumps(task)}, true)"), "İşin yolu: yayin masasında çalışıyor")
        self.assertEqual(run_yol(f"y.yolEtiketi({json.dumps(task)}, false)"), "İşin yolu")
        self.assertEqual(run_yol("y.yolEtiketi({ yol: [] }, true)"), "İşin yolu")
        js = (WEB / "is-akisi.js").read_text(encoding="utf-8")
        self.assertIn("box.setAttribute('aria-label', yolEtiketi(task, kompakt))", js)

    def test_the_page_draws_the_line_in_the_card_the_chat_and_the_board(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("from './is-akisi.js'", app)
        board = app[app.index("function boardCard("):app.index("function workflowCard(")]
        self.assertIn("yolCizgisi(t, { kompakt: true })", board)
        footer = app[app.index("function turAlti("):app.index("// --- rendering ---")]
        self.assertIn("yolCizgisi(stateTask(j.note), { kompakt: true })", footer)
        detail = app[app.index("async function renderDetail("):]
        self.assertIn("yolCizgisi(stateTask(t.note)", detail[:detail.index("t.kontrol ||")])
        self.assertIn("yollariYenile(document, stateTask)", app)
        js = (WEB / "is-akisi.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", js)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for cls in (".yol-tamam", ".yol-simdi", ".yol-bekleme", ".yol-hata", ".yol-atlandi", ".yol-kompakt"):
            self.assertIn(cls, css)



# --- NPC chat (owner decision 2026-11-18; bin/npc_sohbet.py): the card's question box ---

@unittest.skipUnless(NODE, "node is not installed")
class NpcSohbetTest(unittest.TestCase):
    def test_role_keys_for_staff_only(self):
        out = run_scene("""[
          h.npcSohbetRolu({ tur: 'sus', gorevli: 'sekreter' }), h.npcSohbetRolu({ tur: 'sus', id: 'sus:muhasebe' }),
          h.npcSohbetRolu({ tur: 'sus', gorevli: 'mudur', alan: 'qa' }), h.npcSohbetRolu({ tur: 'sus', gorevli: 'mudur', alan: 'x' }),
          h.npcSohbetRolu({ tur: 'sus', gorevli: 'proje', proje: 'blog' }), h.npcSohbetRolu({ tur: 'sus', gorevli: 'proje', proje: '../x' }),
          h.npcSohbetRolu({ tur: 'sus', gorevli: 'cayci' }), h.npcSohbetRolu({ tur: 'dekor', gorevli: 'sekreter' }),
          h.npcSohbetRolu({ tur: 'ceo' }), h.npcSohbetRolu(null)]""")
        self.assertEqual(out, ["sekreter", "muhasebe", "mudur:qa", None, "proje:blog", None, None, None, None, None])

    def test_the_box_only_when_on_and_never_in_the_demo(self):
        out = run_scene("""[h.npcSohbetKutusu({ npc_sohbet: { acik: true } }), h.npcSohbetKutusu({ npc_sohbet: { acik: false } }),
          h.npcSohbetKutusu({}), h.npcSohbetKutusu({ npc_sohbet: { acik: true } }, true)]""")
        self.assertEqual(out[0], {"kutu": True, "ipucu": ""})
        self.assertFalse(out[1]["kutu"])
        self.assertIn("Ayarlar", out[1]["ipucu"])
        self.assertEqual(out[1], out[2])
        self.assertEqual(out[3], {"kutu": False, "ipucu": "Soru sormak demo modunda çalışmaz."})

    def test_the_answer_or_a_plain_error(self):
        out = run_scene("""[h.npcSohbetSonucu(200, { cevap: ' Bugün sakin. ', kullanim: '1,2 bin token · API karşılığı ~$0.002' }),
          h.npcSohbetSonucu(200, { cevap: '' }), h.npcSohbetSonucu(429, { error: 'Saatte en çok 20 soru sorulabilir.' }),
          h.npcSohbetSonucu(0, null), h.npcSohbetSonucu(403, {}), h.npcSohbetSonucu(500, {})]""")
        self.assertEqual(out[0], {"cevap": "Bugün sakin.", "alt": "Kullanım: 1,2 bin token · API karşılığı ~$0.002"})
        self.assertIn("hata", out[1])
        self.assertEqual(out[2], {"hata": "Saatte en çok 20 soru sorulabilir."})
        self.assertIn("Sunucuya ulaşılamadı", out[3]["hata"])
        self.assertIn("reddedildi", out[4]["hata"])
        self.assertEqual(out[5], {"hata": "Cevap alınamadı (hata 500)."})

    def test_the_page_draws_the_answer_as_text_and_keeps_the_box_across_rebuilds(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        part = app[app.index("function sohbetYap("):app.index("// The one character card component")]
        self.assertIn("post('/api/npc-sohbet', { npc: rol, soru })", part)
        self.assertIn("cevap.textContent = out.cevap || out.hata;", part)
        self.assertIn("'Düşünüyor…'", part)
        self.assertNotIn("innerHTML", part)
        self.assertIn("for (const c of [...el.children]) if (c !== soru) c.remove();", app)
        self.assertIn("npcSohbetKutusu(state, DEMO)", app)
        css = (WEB / "style.css").read_text(encoding="utf-8")
        for cls in (".npc-sohbet-form", ".npc-sohbet-cevap", ".npc-sohbet-alt"):
            self.assertIn(cls, css)


if __name__ == "__main__":
    unittest.main()
