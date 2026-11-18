"""Tests for bin/adimlar.py: the CEO's recent tool steps for the Komuta masası (GET /api/ceo/adimlar)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import adimlar  # noqa: E402
import fakes  # noqa: E402

CREDENTIAL = "ş" + "ifre"  # the Turkish credential-note stem, spelled apart like bin/guard.py does


def tool(i, name, inp):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}


def result(day, i, hour=12):
    return fakes.user(day, [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "GIZLI-SONUC"}], hour)


class TargetTest(unittest.TestCase):
    def test_command_heads(self):
        cases = {
            "python3 bin/ofis.py durum": "python3 ofis.py durum",
            "cd /Users/x/Dev/ajan-ofisi && python3 bin/ofis.py ekle --brief-dosya durum/taslak/is-1.json":
                "python3 ofis.py ekle",
            "claude agents --json": "claude agents",
            "cat <<'EOF' > durum/taslak/x.json\n{\"a\": 1}\nEOF": "cat",
            "FOO=1 BAR=2 ls -la /Users/x/Documents/vault/OFIS": "ls",
            "grep -rn 'GIZLI' /Users/x": "grep",
            "  ": "",
            "cd /tmp": "",
            "git status | head -5": "git status",
            "cat /Users/x/Documents/vault/OFIS/04-Aktif-Durum/Index.md": "cat Index.md",
            "ls": "ls",
            "python3 -I test/test_adimlar.py": "python3",
        }
        for cmd, head in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(adimlar.command_head(cmd), head)
        self.assertLessEqual(len(adimlar.command_head("a" * 300)), adimlar.HEDEF_LEN)

    def test_command_arguments_never_leak(self):
        # review MAJOR: the head showed argument words (credentials, tokens, patterns, user@host)
        cases = {
            "curl https://selin:ghp_SECRET123@api.github.com": "curl",
            "curl https://api.example.com/v1/reset/tok3n": "curl",
            "echo sk-live-ABCDEF | pbcopy": "echo",
            "grep TODO bin/x.py": "grep",
            "ssh selin@10.0.0.5 uptime": "ssh",
            "printf 'x' > a": "printf",
            "sed -n 1,5p a.txt": "sed",
            "awk '{print $1}' a": "awk",
            "wget http://x/y": "wget",
            "scp a selin@h:/tmp": "scp",
            "env TOKEN=abc python3 x.py": "env",
            "export KEY=abc": "",
            "security find-generic-password -s x": "security",
            "openssl rand -hex 32": "openssl",
            "base64 -d secret.txt": "base64",
            "git push https://u:p@github.com/x": "git push",
            "git checkout ghp_abcdefABCDEF1234567890": "git checkout",
            "claude 0123456789abcdef0123456789abcdef": "claude",
            "python3 bin/ofis.py sk-live-ABCDEF": "python3 ofis.py",
            "python3 bin/ofis.py AKIAIOSFODNN7EXAMPLE": "python3 ofis.py",
            "cat selin@host.txt": "cat",
            "cat https://x/y.md": "cat",
            "cat a=b.md": "cat",
            "cat %41.md": "cat",
            "cat 0123456789abcdef0123.md": "cat",
            "cat xoxb-123.md": "cat",
            "/usr/bin/curl https://x": "curl",
            "./Gizli_Program x": "",
            "npm run build": "npm run",
        }
        for cmd, head in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(adimlar.command_head(cmd), head)
        for secret in ("SECRET", "tok3n", "ABCDEF", "TODO", "10.0.0.5", "selin", "AKIA", "abc"):
            for cmd in cases:
                self.assertNotIn(secret, adimlar.command_head(cmd))

    def test_targets_are_short_and_never_full_paths(self):
        self.assertEqual(adimlar.target("Read", {"file_path": "/Users/x/Documents/vault/OFIS/04-Aktif-Durum/Index.md"}),
                         "Index.md")
        self.assertEqual(adimlar.target("Edit", {"file_path": "/a/b/c.py", "old_string": "GIZLI", "new_string": "X"}),
                         "c.py")
        self.assertEqual(adimlar.target("Grep", {"pattern": "GIZLI", "path": "/Users/x/vault/OFIS/Kararlar"}),
                         "Kararlar")
        self.assertEqual(adimlar.target("Grep", {"pattern": "GIZLI"}), "")
        self.assertEqual(adimlar.target("Glob", {"pattern": "**/*.md"}), "")
        self.assertEqual(adimlar.target("SendMessage", {"to": "ofis-blog-1110-1-ab", "message": "GIZLI"}),
                         "ofis-blog-1110-1-ab")
        self.assertEqual(adimlar.target("SendMessage", {"to": "review", "message": "GIZLI"}), "başka bir oturum")
        self.assertEqual(adimlar.target("Skill", {"skill": "commit"}), "commit")
        self.assertEqual(adimlar.target("Skill", {"skill": "x y <b>"}), "")
        self.assertEqual(adimlar.target("WebFetch", {"url": "https://docs.example.com/a?token=GIZLI"}),
                         "docs.example.com")
        self.assertEqual(adimlar.target("Agent", {"description": "GIZLI", "prompt": "GIZLI",
                                                  "subagent_type": "general-purpose"}), "general-purpose")
        self.assertEqual(adimlar.target("WebSearch", {"query": "GIZLI"}), "")
        self.assertEqual(adimlar.target("Read", "bozuk"), "")
        self.assertEqual(adimlar.target("Read", {"file_path": "/a/\u2028x\nY.md"}), "x Y.md")

    def test_forbidden_places_drop_the_whole_step(self):
        for name, inp in (
                ("Read", {"file_path": "/Users/x/Dev/zim/a.md"}),
                ("Read", {"file_path": "/Users/x/Dev/ZİM-api/a.md"}),
                ("Bash", {"command": "ls ~/Dev/zim-web"}),
                ("Read", {"file_path": f"/Users/x/vault/Kişisel/{CREDENTIAL}ler.md"}),
                ("Read", {"file_path": f"/Users/x/vault/{CREDENTIAL.upper()}.md"}),
                ("Glob", {"pattern": "*", "path": "/Users/x/vault/Mektuplar"}),
                ("Grep", {"pattern": "x", "path": "/Users/x/vault/TAPU/"}),
                ("Read", {"file_path": "/Users/x/vault/SİGORTA/not.md"}),
                ("Bash", {"command": "cat vault/sigorta/x.md"}),
                ("SendMessage", {"to": "ofis-zim-1"}),
                ("Skill", {"skill": "zim"}),
        ):
            with self.subTest(name=name, inp=inp):
                self.assertIsNone(adimlar.target(name, inp))
        # an ordinary word that only contains the letters is fine
        self.assertEqual(adimlar.target("Read", {"file_path": "/a/zimodal-sigortaron.md"}), "zimodal-sigortaron.md")


class StepsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ceo.jsonl")
        adimlar._cache.clear()
        self.day = date.today()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, records, mode="w"):
        with open(self.path, mode, encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_newest_first_capped_deduplicated_and_without_text(self):
        d = self.day
        # "[Deniz · …]" here and below: the old protocol (before the neutral prefixes), still parsed as the owner's turn
        records = [fakes.human(d, "[Deniz · ofis sayfası]\nselam", hour=9)]
        for i in range(14):
            records.append(fakes.assistant(d, f"m{i}", [{"type": "text", "text": "GIZLI-ANLATIM"},
                                                        tool(i, "Read", {"file_path": f"/x/n{i}.md"})],
                                           hour=10, stop_reason="tool_use"))
            records.append(result(d, i, hour=10))
        records.append(fakes.assistant(d, "m13", [tool(13, "Read", {"file_path": "/x/n13.md"})], hour=10))  # a repeat
        records += fakes.closed_turn(d, text="GIZLI-CEVAP", hour=11)
        self.write(records)
        out = adimlar.ceo_adimlari(self.path, "idle", now=datetime.combine(d, datetime.min.time()).timestamp() + 11 * 3600 + 120)
        self.assertEqual([a["hedef"] for a in out["adimlar"]], [f"n{i}.md" for i in range(13, 3, -1)])
        self.assertEqual(set(out["adimlar"][0]), {"zaman", "arac", "hedef", "ozet"})
        self.assertNotIn("GIZLI", json.dumps(out))
        self.assertIsNone(out["arac_simdi"])
        self.assertEqual(out["durum"], "idle")
        self.assertEqual(out["sure_sn"], 120)  # idle for two minutes since the turn ended

    def test_a_running_tool_while_the_ceo_works(self):
        d = self.day
        start = datetime.combine(d, datetime.min.time()).timestamp() + 12 * 3600
        self.write([fakes.human(d, "[Deniz · ofis sayfası]\ndurum?"),
                    fakes.assistant(d, "m1", [tool(1, "Read", {"file_path": "/x/Index.md"})], stop_reason="tool_use"),
                    result(d, 1),
                    fakes.assistant(d, "m2", [tool(2, "Bash", {"command": "python3 bin/ofis.py durum"})],
                                    stop_reason="tool_use")])
        out = adimlar.ceo_adimlari(self.path, "busy", now=start + 95)
        self.assertEqual(out["arac_simdi"], {"arac": "Bash", "hedef": "python3 ofis.py durum",
                                             "ozet": "komut çalıştırıyor"})
        self.assertEqual(out["sure_sn"], 95)  # since the owner's message opened the turn
        self.write([result(d, 2)], mode="a")
        self.assertIsNone(adimlar.ceo_adimlari(self.path, "busy", now=start + 96)["arac_simdi"])  # the tool returned

    def test_unchanged_file_is_not_parsed_again(self):
        self.write([fakes.assistant(self.day, "m1", [tool(1, "Read", {"file_path": "/x/a.md"})])])
        calls = []
        real = adimlar._parse
        adimlar._parse = lambda line: calls.append(1) or real(line)
        try:
            first = adimlar.ceo_adimlari(self.path, "idle")
            n = len(calls)
            self.assertGreater(n, 0)
            again = adimlar.ceo_adimlari(self.path, "idle")
            self.assertEqual(len(calls), n)  # cached by inode, size and mtime
            self.assertEqual(first["adimlar"], again["adimlar"])
            self.write([fakes.assistant(self.day, "m2", [tool(2, "Write", {"file_path": "/x/b.md"})])], mode="a")
            third = adimlar.ceo_adimlari(self.path, "idle")
            self.assertGreater(len(calls), n)
            self.assertEqual([a["hedef"] for a in third["adimlar"]], ["b.md", "a.md"])
        finally:
            adimlar._parse = real

    def test_only_the_tail_is_read_and_missing_files_are_empty(self):
        filler = fakes.assistant(self.day, "f", [{"type": "text", "text": "x" * 2000}])
        self.write([fakes.assistant(self.day, "m0", [tool(0, "Read", {"file_path": "/x/eski.md"})])] + [filler] * 400 +
                   [fakes.assistant(self.day, "m1", [tool(1, "Read", {"file_path": "/x/yeni.md"})])])
        out = adimlar.ceo_adimlari(self.path, "idle")
        self.assertEqual([a["hedef"] for a in out["adimlar"]], ["yeni.md"])
        empty = {"adimlar": [], "durum": "idle", "arac_simdi": None, "sure_sn": None}
        self.assertEqual(adimlar.ceo_adimlari(os.path.join(self.tmp.name, "yok.jsonl"), "idle"), empty)
        self.assertEqual(adimlar.ceo_adimlari(None, "idle"), empty)
        self.assertEqual(adimlar.ceo_adimlari(None, None)["durum"], "unknown")

    def test_a_forbidden_step_is_left_out_of_the_list(self):
        self.write([fakes.assistant(self.day, "m1", [tool(1, "Read", {"file_path": "/x/a.md"}),
                                                     tool(2, "Read", {"file_path": "/Users/x/Dev/zim/b.md"}),
                                                     tool(3, "Bash", {"command": "ls /v/Mektuplar"})])])
        out = adimlar.ceo_adimlari(self.path, "busy")
        self.assertEqual([a["hedef"] for a in out["adimlar"]], ["a.md"])
        self.assertNotIn("zim", json.dumps(out))
        self.assertIsNone(out["arac_simdi"])  # the running call is the hidden one: no older step is named instead


OPUS = "claude-opus-5-5"


def u(i=100, o=50, cc=0, cr=1000):
    return {"input_tokens": i, "output_tokens": o, "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}


def bash_result(day, i, text, hour=12, error=False):
    part = {"type": "tool_result", "tool_use_id": f"t{i}", "content": text}
    if error:
        part["is_error"] = True
    return fakes.user(day, [part], hour)


class TurnsTest(unittest.TestCase):
    """Step 1 (owner decision 2026-11-12): one footer per CEO reply — the turn's steps, the jobs it opened, its cost."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ceo.jsonl")
        adimlar._cache.clear()
        self.day = date.today()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, records, mode="w"):
        with open(self.path, mode, encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def self_answered(self, d, hour=9, msg="a"):
        return [fakes.human(d, "[Deniz · ofis sayfası]\ndurum?", hour=hour),
                fakes.assistant(d, f"{msg}1", [{"type": "thinking", "thinking": "GIZLI"},
                                               tool(f"{msg}1", "Bash", {"command": "python3 bin/ofis.py durum"})],
                                usage=u(), hour=hour, model=OPUS, stop_reason="tool_use"),
                fakes.user(d, [{"type": "tool_result", "tool_use_id": f"t{msg}1", "content": "GIZLI-SONUC"}], hour),
                fakes.assistant(d, f"{msg}1", [tool(f"{msg}1", "Bash", {"command": "python3 bin/ofis.py durum"})],
                                usage=u(), hour=hour, model=OPUS, stop_reason="tool_use"),  # a repeated chunk
                fakes.assistant(d, f"{msg}2", [tool(f"{msg}2", "Read", {"file_path": "/v/OFIS/Index.md"})],
                                usage=u(), hour=hour, model=OPUS, stop_reason="tool_use"),
                fakes.user(d, [{"type": "tool_result", "tool_use_id": f"t{msg}2", "content": "GIZLI"}], hour),
                fakes.assistant(d, f"{msg}3", [{"type": "text", "text": "GIZLI-CEVAP"}], usage=u(o=200), hour=hour,
                                model=OPUS),
                {"type": "system", "subtype": "stop_hook_summary", "timestamp": fakes.ts(d, hour)},
                {"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(d, hour)}]

    def test_a_self_answered_turn(self):
        d = self.day
        self.write(self.self_answered(d))
        out = adimlar.ceo_turlari(self.path)
        self.assertEqual(len(out["turlar"]), 1)
        t = out["turlar"][0]
        self.assertEqual(t["adim"], 2)
        self.assertEqual(t["isler"], [])
        self.assertEqual(t["cevap_zaman"], fakes.ts(d, 9))
        self.assertEqual(t["token"], 2 * 1150 + 1300)  # three calls, the repeated chunk counted once
        per = lambda i, o, cr: (i * 4 + o * 20 + cr * 0.2) / 1e6  # noqa: E731  opus 5.5 list prices
        self.assertAlmostEqual(t["usd"], 2 * per(100, 50, 1000) + per(100, 200, 1000), places=9)
        self.assertFalse(t["fiyat_eksik"])
        self.assertFalse(out["kapaniyor"])
        self.assertNotIn("GIZLI", json.dumps(out))

    def test_a_turn_that_opened_jobs(self):
        d = self.day
        ekle = {"command": "cd /Users/x/Dev/ajan-ofisi && python3 bin/ofis.py ekle --brief-dosya durum/taslak/is-1.json"}
        akis = {"command": "python3 bin/ofis.py akis gelistir --brief-dosya durum/taslak/is-2.json"}
        cevapla = {"command": "python3 bin/ofis.py cevapla x.md --dosya durum/taslak/c.txt"}
        self.write(self.self_answered(d, hour=8, msg="o") + [
            fakes.human(d, "[Deniz · ofis sayfası]\nblog'de giriş hatasını düzelt", hour=10),
            fakes.assistant(d, "m1", [tool(1, "Bash", ekle)], usage=u(), hour=10, model=OPUS, stop_reason="tool_use"),
            bash_result(d, 1, 'UYARI: kolay işin Kontrol yok\n{"is": "2026-11-12-101500-blog.md", "durum": "sirada", '
                              '"katman": "kod", "model": "opus", "effort": "high"}', hour=10),
            fakes.assistant(d, "m2", [tool(2, "Bash", akis)], usage=u(), hour=10, model=OPUS, stop_reason="tool_use"),
            bash_result(d, 2, json.dumps({"grup": "akis-1112-101600-kasa", "isler": [
                "2026-11-12-101600-kasa.md", "2026-11-12-101600-kasa-2.md", "2026-11-12-101600-kasa-3.md"]}), hour=10),
            fakes.assistant(d, "m3", [tool(3, "Bash", cevapla)], usage=u(), hour=10, model=OPUS, stop_reason="tool_use"),
            bash_result(d, 3, json.dumps({"karar": "k.md", "is": "2026-11-11-090356-blog-3.md"}), hour=10),
            fakes.assistant(d, "m4", [tool(4, "Bash", dict(ekle))], usage=u(), hour=10, model=OPUS, stop_reason="tool_use"),
            bash_result(d, 4, "REFUSED: Sıradakiler dolu", hour=10, error=True),
            fakes.assistant(d, "m5", [{"type": "text", "text": "Stajyere verdim."}], usage=u(), hour=10, model=OPUS),
            {"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(d, 10)},
        ])
        out = adimlar.ceo_turlari(self.path)
        self.assertEqual(len(out["turlar"]), 2)
        newest = out["turlar"][0]
        self.assertEqual(newest["adim"], 4)
        self.assertEqual(newest["isler"], [
            {"note": "2026-11-12-101500-blog.md", "katman": "kod", "model": "opus", "akis": "", "adim_sayisi": 0},
            {"note": "2026-11-12-101600-kasa.md", "katman": "", "model": "", "akis": "akis-1112-101600-kasa",
             "adim_sayisi": 3}])
        self.assertEqual(out["turlar"][1]["isler"], [])

    def test_a_job_added_and_started_in_one_turn_is_listed_once(self):
        d = self.day
        line = '{"is": "2026-11-12-101500-blog.md", "katman": "kod", "model": "opus"}'
        self.write([fakes.human(d, "x"),
                    fakes.assistant(d, "m1", [tool(1, "Bash", {"command": "python3 bin/ofis.py ekle --brief-dosya a.json"})],
                                    usage=u(), model=OPUS, stop_reason="tool_use"),
                    bash_result(d, 1, line),
                    fakes.assistant(d, "m2", [tool(2, "Bash", {"command": "python3 bin/ofis.py baslat 2026-11-12-101500-blog.md"})],
                                    usage=u(), model=OPUS, stop_reason="tool_use"),
                    bash_result(d, 2, '{"is": "2026-11-12-101500-blog.md", "oturum": "ofis-blog-1"}'),
                    fakes.assistant(d, "m3", [{"type": "text", "text": "ok"}], usage=u(), model=OPUS)])
        [t] = adimlar.ceo_turlari(self.path)["turlar"]
        self.assertEqual([j["note"] for j in t["isler"]], ["2026-11-12-101500-blog.md"])

    def test_a_turn_still_closing(self):
        d = self.day
        head = [fakes.human(d, "[Deniz · ofis sayfası]\nselam", hour=11),
                fakes.assistant(d, "m1", [tool(1, "Read", {"file_path": "/v/OFIS/Index.md"})], usage=u(), hour=11,
                                model=OPUS, stop_reason="tool_use")]
        self.write(head)
        self.assertFalse(adimlar.ceo_turlari(self.path)["kapaniyor"])  # a tool call is pending
        self.write([fakes.user(d, [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}], 11),
                    fakes.assistant(d, "m2", [{"type": "thinking", "thinking": "x"}], usage=u(), hour=11, model=OPUS),
                    fakes.assistant(d, "m2", [{"type": "text", "text": "Merhaba."}], usage=u(), hour=11, model=OPUS)],
                   mode="a")
        out = adimlar.ceo_turlari(self.path)
        self.assertTrue(out["kapaniyor"])
        self.assertTrue(adimlar.tur_kapaniyor(self.path))
        self.assertIsNone(out["turlar"][0]["bitis"])
        self.write([{"type": "system", "subtype": "stop_hook_summary", "timestamp": fakes.ts(d, 11)}], mode="a")
        self.assertTrue(adimlar.ceo_turlari(self.path)["kapaniyor"])  # a blocking Stop hook may still continue it
        self.write([{"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(d, 11)}], mode="a")
        self.assertFalse(adimlar.ceo_turlari(self.path)["kapaniyor"])  # the turn-end record: the turn is over
        self.assertFalse(adimlar.tur_kapaniyor(os.path.join(self.tmp.name, "yok.jsonl")))
        self.assertEqual(adimlar.ceo_turlari(None), {"turlar": [], "kapaniyor": False})

    def test_zim_steps_are_dropped_from_the_turn(self):
        d = self.day
        self.write([fakes.human(d, "[Deniz · ofis sayfası]\nbak", hour=12),
                    fakes.assistant(d, "m1", [tool(1, "Read", {"file_path": "/Users/x/Dev/zim/notes.md"}),
                                              tool(2, "Bash", {"command": "python3 bin/ofis.py ekle --proje x --baslik "
                                                                          "'/Users/x/Dev/zim/a'"}),
                                              tool(3, "Grep", {"pattern": "x", "path": "/v/Mektuplar"}),
                                              tool(4, "Read", {"file_path": "/v/OFIS/README.md"})],
                                    usage=u(), hour=12, model=OPUS, stop_reason="tool_use"),
                    bash_result(d, 2, '{"is": "2026-11-12-120000-x.md", "katman": "kod", "model": "opus"}', hour=12),
                    fakes.assistant(d, "m2", [{"type": "text", "text": "Tamam."}], usage=u(), hour=12, model=OPUS),
                    {"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(d, 12)}])
        out = adimlar.ceo_turlari(self.path)
        t = out["turlar"][0]
        self.assertEqual(t["adim"], 1)  # README.md only
        self.assertEqual(t["isler"], [])  # the job command reached ZIM: dropped with its result
        for secret in ("zim", "Mektuplar", "notes.md", "2026-11-12-120000-x"):
            self.assertNotIn(secret, json.dumps(out))

    def test_a_cut_window_drops_the_partial_first_turn_and_caps_the_list(self):
        d = self.day
        records = []
        for i in range(adimlar.MAX_TURNS + 5):
            records += [fakes.human(d, "x", hour=9), fakes.assistant(d, f"r{i}", [{"type": "text", "text": "ok"}],
                                                                       usage=u(), hour=9, model=OPUS),
                        {"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(d, 9)}]
        self.write(records)
        self.assertEqual(len(adimlar.ceo_turlari(self.path)["turlar"]), adimlar.MAX_TURNS)
        turns = adimlar.parse_turns(b"\n".join(json.dumps(r).encode() for r in records[1:6]), cut=True)
        self.assertEqual(len(turns), 1)  # the first record (its prompt) is outside the window: that turn is dropped

    def test_unknown_model_marks_the_price_missing(self):
        d = self.day
        self.write([fakes.human(d, "x"), fakes.assistant(d, "m1", [{"type": "text", "text": "ok"}], usage=u()),
                    {"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(d, 12)}])
        t = adimlar.ceo_turlari(self.path)["turlar"][0]
        self.assertTrue(t["fiyat_eksik"])
        self.assertEqual(t["token"], 1150)

    def test_jobs_get_their_title_and_role(self):
        turlar = [{"isler": [{"note": "a.md", "katman": "kod", "model": "", "akis": "", "adim_sayisi": 0},
                             {"note": "b.md", "katman": "genel", "model": "", "akis": "", "adim_sayisi": 0},
                             {"note": "c.md", "katman": "", "model": "haiku", "akis": "", "adim_sayisi": 0}]}]
        tasks = [{"note": "a.md", "title": "Giriş hatası", "model": "opus"}]
        cfg = {"tiers": {"genel": {"model": "sonnet"}}}
        adimlar.isleri_tamamla(turlar, tasks, cfg)
        self.assertEqual([(j["baslik"], j["unvan"]) for j in turlar[0]["isler"]],
                         [("Giriş hatası", "Kıdemli"), ("b", "Uzman"), ("c", "Stajyer")])


if __name__ == "__main__":
    unittest.main()
