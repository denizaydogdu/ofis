"""Tests for the CEO's own question to the owner (`ofis.py sor`, tur: ceo-sorusu; owner decision 2026-11-14): input validation, the
card's content, `cevapla` closing it, the denial for project sessions, the state listing, the page helpers (option
buttons, the chat badge, the bell tooltip, the header count) and the CEO's rule in CLAUDE.md. Temp vault/durum only."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import webkopya  # noqa: E402  (web/i18n.js next to the copied modules)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import sahip_yasaklari  # noqa: E402,F401  (the owner's name and rules, as in his ofis.json)
import jobs  # noqa: E402
import launch  # noqa: E402
import ofis  # noqa: E402
import state  # noqa: E402

ROOT = Path(HERE).parent
WEB = ROOT / "web"
NODE = shutil.which("node")
NOW = datetime(2026, 11, 14, 10, 0, 0)


class SorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.vault = os.path.join(base, "vault", "OFIS")
        self.durum = os.path.join(base, "durum")
        self.project = os.path.join(base, "Dev", "blog")
        os.makedirs(self.vault)
        os.makedirs(self.project)
        os.makedirs(os.path.join(self.durum, "taslak"))
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
                    "projects": {"blog": {"path": self.project}}, "tiers": {"genel": {"model": "sonnet"}},
                    "default_tier": "genel", "default_budget_usd": 1}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, now=lambda: NOW, out=out, err=err,
                         cwd=self.durum)
        return code, out.getvalue(), err.getvalue()

    def write_input(self, data, name="soru-1.json"):
        path = os.path.join(self.durum, "taslak", name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
        return path

    def sor(self, data):
        path = self.write_input(data)
        code, out, err = self.run_cli("sor", "--dosya", path)
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(path), "the input file is deleted on success")
        return json.loads(out)

    def refused(self, data):
        path = self.write_input(data)
        code, _, err = self.run_cli("sor", "--dosya", path)
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("REFUSED: "), err)
        self.assertTrue(os.path.exists(path), "kept on refusal so it can be fixed")
        return err

    def card(self, note):
        with open(os.path.join(self.vault, "Kararlar", note), encoding="utf-8") as f:
            return jobs.parse(f.read())

    QUESTION = {"baslik": "Kayıtlar nasıl gönderilsin?", "soru": "13 kayıt hazır.\n## Sahte bölüm\nNasıl ilerleyelim?",
                "secenekler": [{"kod": "A", "metin": "Hepsini şimdi gönder"}, {"kod": "b", "metin": "Önce 1 tane dene"},
                               {"kod": "C", "metin": "Bekle"}],
                "proje": "blog", "ilgili": ["2026-11-14-090000-blog", "2026-11-13-100000-blog.md"]}

    def test_sor_writes_a_pending_card_with_the_question_options_and_links(self):
        result = self.sor(self.QUESTION)
        self.assertEqual(result, {"karar": "2026-11-14-blog-ceo-sorusu.md", "tur": "ceo-sorusu",
                                  "proje": "blog", "secenekler": ["A", "B", "C"]})
        _, meta, body = self.card(result["karar"])
        self.assertEqual((meta["tur"], meta["durum"], meta["proje"], meta["soruldu"]),
                         ("ceo-sorusu", "bekliyor", "blog", "2026-11-14T10:00:00"))
        self.assertTrue(body.startswith("# Kayıtlar nasıl gönderilsin?\n"))
        # the CEO's text is quoted: its "## " line cannot open a section of the card
        self.assertIn("> ## Sahte bölüm", body)
        self.assertEqual(jobs.section(body, "Sahte bölüm"), "")
        self.assertEqual(jobs.question_options(body), [{"kod": "A", "metin": "Hepsini şimdi gönder"},
                                                       {"kod": "B", "metin": "Önce 1 tane dene"},
                                                       {"kod": "C", "metin": "Bekle"}])
        related = jobs.section(body, "İlgili Sayfalar")
        self.assertIn("[[2026-11-14-090000-blog]]", related)
        self.assertIn("[[2026-11-13-100000-blog]]", related)
        # a second question the same day gets its own note; no project = ofis, no options = a plain line
        second = self.sor({"baslik": "Commit atılsın mı?", "soru": "Değişiklikler hazır."})
        self.assertEqual(second["karar"], "2026-11-14-ofis-ceo-sorusu.md")
        self.assertEqual(self.sor({"baslik": "X", "soru": "Y", "proje": "ofis"})["karar"],
                         "2026-11-14-ofis-ceo-sorusu-2.md")
        _, _, body = self.card(second["karar"])
        self.assertEqual(jobs.question_options(body), [])
        self.assertIn(ofis.NO_OPTIONS, body)
        self.assertIn("[[OFIS/README]]", jobs.section(body, "İlgili Sayfalar"))

    def test_a_configured_project_key_with_a_path_is_refused(self):
        # Codex 2026-11-14: the key becomes part of the note's file name; ../ must never leave Kararlar/
        self.cfg["projects"]["../../x"] = {"path": self.project}
        self.assertIn("invalid project name", self.refused({"baslik": "B", "soru": "S", "proje": "../../x"}))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.vault), "x")))

    def test_sor_validates_its_input(self):
        ok = {"baslik": "B", "soru": "S"}
        for bad, words in (("{nope", "not valid JSON"), ([], "one JSON object"),
                           ({**ok, "fazla": 1}, "unknown question file fields"),
                           ({"soru": "S"}, "baslik is required"), ({"baslik": "B", "soru": "  "}, "soru is required"),
                           ({**ok, "baslik": "x" * 121}, "baslik is limited"),
                           ({**ok, "soru": "x" * 3001}, "soru is limited"),
                           ({**ok, "proje": "bilinmeyen"}, "unknown project"),
                           ({**ok, "proje": []}, "unknown project"), ({**ok, "proje": {}}, "unknown project"),
                           ({**ok, "proje": 5}, "unknown project"),
                           ({**ok, "secenekler": "A"}, "must be a list"),
                           ({**ok, "secenekler": [{"kod": k, "metin": "m"} for k in "ABCDE"] + [{"kod": "A", "metin": "x"}]},
                            "at most 5"),
                           ({**ok, "secenekler": [{"kod": "F", "metin": "m"}]}, "option kod"),
                           ({**ok, "secenekler": [{"kod": "A", "metin": "m"}, {"kod": "a", "metin": "n"}]}, "twice"),
                           ({**ok, "secenekler": [{"kod": "A", "metin": " "}]}, "has no metin"),
                           ({**ok, "secenekler": [{"kod": "A", "metin": "m" * 301}]}, "option text is limited"),
                           ({**ok, "secenekler": [{"kod": "A", "metin": "m", "x": 1}]}, "{kod, metin}"),
                           ({**ok, "ilgili": ["../x"]}, "invalid note name"),
                           ({**ok, "ilgili": ["a]]|b"]}, "invalid note name"),
                           ({**ok, "ilgili": [f"n{i}" for i in range(11)]}, "at most 10")):
            with self.subTest(bad=bad):
                self.assertIn(words, self.refused(bad))
        self.assertFalse(os.path.isdir(os.path.join(self.vault, "Kararlar")) and
                         os.listdir(os.path.join(self.vault, "Kararlar")))
        # the input must be a file directly in durum/taslak/
        outside = os.path.join(self.durum, "x.json")
        with open(outside, "w", encoding="utf-8") as f:
            json.dump(ok, f)
        code, _, err = self.run_cli("sor", "--dosya", outside)
        self.assertEqual(code, 1)
        self.assertIn("durum/taslak", err)

    def answer(self, note, text):
        code, out, err = self.run_cli("cevapla", note, text)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_cevapla_closes_the_card_and_returns_the_answer(self):
        note = self.sor(self.QUESTION)["karar"]
        result = self.answer(note, "B) Önce 1 tane dene")
        self.assertEqual((result["tur"], result["onay"], result["cevap"], result["secim"]),
                         ("ceo-sorusu", False, "B) Önce 1 tane dene", "B"))
        _, meta, body = self.card(note)
        self.assertEqual(meta["durum"], "cevaplandi")
        self.assertIn("B) Önce 1 tane dene", jobs.section(body, "Cevap (Selin)"))
        self.assertFalse(os.path.isdir(os.path.join(self.durum, "giden")), "no session waits: no outbox message")
        code, _, err = self.run_cli("cevapla", note, "A")
        self.assertEqual(code, 1)
        self.assertIn("not 'bekliyor'", err)
        # a plain yes: onay; free text: the text, no secim
        yes = self.answer(self.sor({"baslik": "Commit?", "soru": "Atılsın mı?"})["karar"], "Evet")
        self.assertEqual((yes["onay"], yes["cevap"]), (True, "Evet"))
        self.assertNotIn("secim", yes)
        free = self.answer(self.sor(self.QUESTION)["karar"], "Hiçbiri, yarın konuşalım")
        self.assertEqual((free["onay"], free["cevap"]), (False, "Hiçbiri, yarın konuşalım"))
        self.assertNotIn("secim", free)

    def test_answer_choice(self):
        codes = ["A", "B", "C"]
        for text, want in (("A", "A"), ("a", "A"), ("B)", "B"), ("C) Bekle", "C"), ("b — tamam", "B"),
                           ("A şıkkı", "A"), ("Evet", ""), ("Ama bekle", ""), ("D", ""), ("", "")):
            with self.subTest(text=text):
                self.assertEqual(ofis.answer_choice(text, codes), want)

    def test_project_sessions_may_not_run_it(self):
        self.assertIn("sor", launch.DENIED_COMMANDS)
        rules = launch.deny_rules(self.vault)
        self.assertIn(f"Bash(python3 {launch.OFIS_PY} sor:*)", rules)
        self.assertIn("ceo-sorusu", ofis.CEO_DECISIONS)

    def test_state_lists_it_among_pending_decisions_with_its_options(self):
        note = self.sor(self.QUESTION)["karar"]
        [d] = state.pending_decisions(self.vault)
        self.assertEqual((d["note"], d["kind"], d["project"], d["title"], d["asked"]),
                         (note, "ceo-sorusu", "blog", "Kayıtlar nasıl gönderilsin?", "2026-11-14T10:00:00"))
        self.assertIn("## Sahte bölüm", d["question"])  # the quote marks are removed for the page
        self.assertEqual([o["kod"] for o in d["options"]], ["A", "B", "C"])
        self.answer(note, "A")
        self.assertEqual(state.pending_decisions(self.vault), [])


class ClaudeMdTest(unittest.TestCase):
    def test_the_ceo_rule_is_in_claude_md(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("ofis.py sor --dosya durum/taslak/<ad>.json", text)
        self.assertIn("Kararını kartta bekliyorum", text)
        self.assertIn("`talimat-denetimi`, `sor`) and `EnterWorktree` denied", text)


def run_js(expr):
    with tempfile.TemporaryDirectory() as tmp:
        module = Path(tmp) / "ofis-text.mjs"
        (Path(tmp) / "ofis-davranis.mjs").write_text(  # the owner's name helpers
            webkopya.mjs_yap((WEB / "ofis-davranis.js").read_text(encoding="utf-8")), encoding="utf-8")
        webkopya.i18n_ekle(tmp, mjs=True)
        module.write_text(webkopya.mjs_yap((WEB / "ofis-text.js").read_text(encoding="utf-8")), encoding="utf-8")
        code = (f"import * as t from {json.dumps(module.as_uri())};\n"
                f"process.stdout.write(JSON.stringify({expr}));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class PageTest(unittest.TestCase):
    def test_option_buttons(self):
        d = {"kind": "ceo-sorusu", "options": [{"kod": "A", "metin": " Hepsini  gönder "}, {"kod": "A", "metin": "x"},
                                               {"kod": "F", "metin": "y"}, {"kod": "B", "metin": ""},
                                               {"kod": "C", "metin": "<b>Bekle</b>"}, 5]}
        self.assertEqual(run_js(f"t.secenekDugmeleri({json.dumps(d)})"),
                         [{"kod": "A", "metin": "Hepsini gönder", "cevap": "A) Hepsini gönder"},
                          {"kod": "C", "metin": "<b>Bekle</b>", "cevap": "C) <b>Bekle</b>"}])
        self.assertEqual(run_js("t.secenekDugmeleri({kind: 'akis-onay', options: [{kod: 'A', metin: 'x'}]})"), [])
        self.assertEqual(run_js("t.secenekDugmeleri(null)"), [])

    CHAT = [{"role": "deniz", "text": "Ne yapalım?", "time": "2026-11-14T09:59:00"},
            {"role": "ceo", "text": "Kararını kartta bekliyorum: gönderim", "time": "2026-11-14T10:00:40"},
            {"role": "ceo", "text": "Başka bir konu", "time": "2026-11-14T10:30:00"},
            {"role": "ceo", "text": "Kart: 2026-11-14-ofis-ceo-sorusu-2 açık", "time": "2026-11-14T12:00:00"}]

    def test_the_chat_badge_matches_by_time_or_by_note_name(self):
        decisions = [{"kind": "ceo-sorusu", "note": "2026-11-14-ofis-ceo-sorusu.md", "title": "Gönderim",
                      "asked": "2026-11-14T10:00:30"},
                     {"kind": "ceo-sorusu", "note": "2026-11-14-ofis-ceo-sorusu-2.md", "title": "İkinci",
                      "asked": "2026-11-14T10:29:50"},
                     {"kind": "claude-md-onerisi", "note": "x.md", "asked": "2026-11-14T10:30:00"},
                     {"kind": "ceo-sorusu", "note": "uzak.md", "asked": "2026-11-14T15:00:00"}]
        out = run_js(f"t.cevapBekleyenRozetleri({json.dumps(self.CHAT)}, {json.dumps(decisions)})")
        # the first by time; the second names its note in a later line, which wins over the line closest in time
        self.assertEqual(out, {"1": [{"note": "2026-11-14-ofis-ceo-sorusu.md", "baslik": "Gönderim"}],
                               "3": [{"note": "2026-11-14-ofis-ceo-sorusu-2.md", "baslik": "İkinci"}]})
        # answered (by the server or from this page): the badge goes
        answered = [dict(decisions[0], answer_sent=True), decisions[1]]
        self.assertEqual(list(run_js(f"t.cevapBekleyenRozetleri({json.dumps(self.CHAT)}, {json.dumps(answered)}, "
                                     "['2026-11-14-ofis-ceo-sorusu-2.md'])")), [])
        self.assertEqual(run_js("t.cevapBekleyenRozetleri(null, undefined)"), {})

    def test_the_bell_tooltip_and_the_header_count(self):
        out = run_js("t.kararBildirimi([{note: 'a.md', title: 'A', asked: ''}, {note: 'b.md', title: 'B', asked: ''}])")
        self.assertTrue(out["baslik"].startswith("2 karar seni bekliyor"), out["baslik"])
        self.assertEqual(run_js("[t.seniBekleyenMetni(3), t.seniBekleyenMetni(0)]"), ["Seni bekleyen: 3", ""])

    def test_the_page_wires_buttons_badges_and_the_header(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="side-bekleyen"', html)
        self.assertIn("seniBekleyenMetni(kararSayisi)", app)
        self.assertIn("renderSecenekler(card, secim)", app)
        self.assertIn("card.parts.submit(o.cevap)", app)
        self.assertIn("cevapBekleyenRozetleri(chat, rozetKararlari())", app)
        self.assertIn("'msg-bekliyor', T('cevap bekliyor')", app)
        badge = app[app.index("function renderChatBox("):app.index("function openDrawer(")]
        self.assertNotIn("innerHTML", badge)


if __name__ == "__main__":
    unittest.main()
