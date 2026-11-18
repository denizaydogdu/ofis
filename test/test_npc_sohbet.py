"""Tests for bin/npc_sohbet.py (owner decision 2026-11-18, "gerçekten akıllı NPC'ler"): the switch and its validation
(also through bin/ayarlar.py, the one writer of ofis.json), the role keys, the summary builder (no forbidden project
leaks, bounded, role-scoped, usage wording), the one `claude -p` call with a fake claude binary (options, working
folder, environment, masking, failures), the hourly limit and one-at-a-time, and POST /api/npc-sohbet's security
matrix on a live test server. Temp folders and a fake claude only. Run: python3 -I test/test_npc_sohbet.py"""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config: forbidden project "zim")
import ayarlar  # noqa: E402
import claude_cli  # noqa: E402
import launch  # noqa: E402
import npc_sohbet  # noqa: E402

ROOT = os.path.realpath(os.path.join(HERE, ".."))
NOW = datetime(2026, 11, 18, 10, 0, 0)
ACIK = {"npc_sohbet": {"acik": True, "saatlik_sinir": 3}, "projects": {"blog": {"path": "/tmp/blog"}},
        "tiers": {"kolay": {"model": "haiku", "effort": "low"}}}


def task(project, title, status="calisiyor", **more):
    return {"note": f"2026-11-18-{project}-{title}.md", "project": project, "title": title, "status": status,
            "tier": "kod", "finished": "", "step_kind": "", **more}


def state(**more):
    s = {"today": "2026-11-18",
         "tasks": [task("blog", "giriş sayfası"), task("blog", "eski iş", "tikandi", finished="2026-11-18T09:00"),
                   task("zim", "gizli iş"), task("blog", "zim klasörünü oku"),
                   task("vitrin", "inceleme", "incelemede", tier="inceleme", step_kind="kod-inceleme")],
         "decisions": [{"project": "blog", "title": "Devam mı?", "question": "Sayfa böyle kalsın mı?"}],
         "projects": [{"name": "blog", "status": "calisiyor", "sessions": 1, "cost_today": 0.41,
                       "usage_today": 182000},
                      {"name": "vitrin", "status": "uyuyor", "sessions": 0, "cost_today": 0, "usage_today": 0}],
         "ceo": {"state": "busy", "cost_today": 0.2, "usage_today": 50000},
         "summary": {"usage_today": 232000, "running": 1, "max_running": 3}}
    s.update(more)
    return s


class SwitchTest(unittest.TestCase):
    def test_off_unless_acik_is_true_and_the_limit_defaults(self):
        for cfg in ({}, {"npc_sohbet": None}, {"npc_sohbet": {"acik": "true"}}, {"npc_sohbet": {"acik": 1}}):
            self.assertEqual(npc_sohbet.ayar(cfg), {"acik": False, "saatlik_sinir": 20})
        self.assertEqual(npc_sohbet.ayar({"npc_sohbet": {"acik": True, "saatlik_sinir": 5}}),
                         {"acik": True, "saatlik_sinir": 5})
        self.assertEqual(npc_sohbet.ayar({"npc_sohbet": {"acik": True, "saatlik_sinir": 10 ** 6}})["saatlik_sinir"],
                         npc_sohbet.EN_COK_SAATLIK)
        self.assertEqual(npc_sohbet.ayar({"npc_sohbet": {"acik": True, "saatlik_sinir": True}})["saatlik_sinir"], 20)

    def test_validation(self):
        self.assertEqual(npc_sohbet.dogrula({"acik": True, "saatlik_sinir": 20}), [])
        self.assertEqual(npc_sohbet.dogrula({"acik": False}), [])
        for bad in (None, [], "acik", {"acik": "evet"}, {"acik": True, "saatlik_sinir": 0},
                    {"acik": True, "saatlik_sinir": 201}, {"acik": True, "saatlik_sinir": 2.5},
                    {"acik": True, "saatlik_sinir": True}, {"acik": True, "x": 1}):
            with self.subTest(bad=bad):
                self.assertTrue(npc_sohbet.dogrula(bad))

    def test_the_example_config_ships_it_off(self):
        with open(os.path.join(ROOT, "ofis.example.json"), encoding="utf-8") as f:
            self.assertFalse(npc_sohbet.ayar(json.load(f))["acik"])


class AyarlarTest(unittest.TestCase):
    """The Genel section's POST body through bin/ayarlar.py islem (the one writer)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.tmp.name, "ofis.json")
        self.durum = os.path.join(self.tmp.name, "durum")
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump({"ceo_session": "ofis-ceo", "ofis_adi": "Atölye", "projects": {}}, f)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.config, encoding="utf-8") as f:
            return json.load(f)

    def test_the_switch_is_written_alone_and_keeps_the_rest(self):
        out = ayarlar.islem(self.config, self.durum, {"islem": "genel",
                                                      "npc_sohbet": {"acik": True, "saatlik_sinir": 7}})
        self.assertEqual(out["alanlar"], ["npc_sohbet"])
        data = self.read()
        self.assertEqual(data["npc_sohbet"], {"acik": True, "saatlik_sinir": 7})
        self.assertEqual(data["ofis_adi"], "Atölye")
        # a missing limit keeps the file's
        ayarlar.islem(self.config, self.durum, {"islem": "genel", "npc_sohbet": {"acik": False}})
        self.assertEqual(self.read()["npc_sohbet"], {"acik": False, "saatlik_sinir": 7})

    def test_a_bad_value_writes_nothing(self):
        with open(self.config, encoding="utf-8") as f:
            before = f.read()
        for body in ({"islem": "genel", "npc_sohbet": {"acik": True, "saatlik_sinir": 0}},
                     {"islem": "genel", "npc_sohbet": "acik"},
                     {"islem": "genel", "ofis_adi": "Yeni", "npc_sohbet": {"acik": "evet"}}):
            with self.subTest(body=body):
                with self.assertRaises(ayarlar.Hata) as ctx:
                    ayarlar.islem(self.config, self.durum, body)
                self.assertEqual(ctx.exception.durum, 400)
                self.assertTrue(all(e.startswith("NPC sohbeti") for e in ctx.exception.hatalar))
        with open(self.config, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_the_summary_and_the_live_refresh_carry_it(self):
        self.assertIn("npc_sohbet", ayarlar.CANLI_ANAHTARLAR)
        out = ayarlar.ozet({"npc_sohbet": {"acik": True}})
        self.assertEqual(out["npc_sohbet"], {"acik": True, "saatlik_sinir": 20})
        self.assertEqual(out["kurallar"]["npc_saatlik_en_cok"], 200)


class RoleTest(unittest.TestCase):
    def test_known_roles_managers_and_registered_projects_only(self):
        cfg = {"projects": {"blog": {"path": "/x/Dev/blog"}, "zim": {"path": "/x/Dev/zim"},
                            "eski": {"path": "/x/Dev/zim-old"}}}
        self.assertEqual(npc_sohbet.rol_coz("sekreter", cfg)[0], "Sekreter")
        self.assertEqual(npc_sohbet.rol_coz("mudur:qa", cfg)[0], "QA Müdürü")
        self.assertEqual(npc_sohbet.rol_coz("proje:blog", cfg)[2], ("proje", "blog"))
        for bad in ("", None, 5, "cayci", "mudur:yok", "proje:yok", "proje:zim", "proje:eski", "proje:../x",
                    "sekreter" * 10, "__class__"):
            with self.subTest(bad=bad):
                with self.assertRaises(npc_sohbet.Gecersiz):
                    npc_sohbet.rol_coz(bad, cfg)


class SummaryTest(unittest.TestCase):
    def test_no_forbidden_project_or_word_reaches_the_summary(self):
        for rol in ("sekreter", "muhasebe", "ik", "revir", "psikolog", "idari", "guvenlik", "sunucu", "arge",
                    "mudur:yazilim", "mudur:qa", "mudur:it", "proje:blog"):
            with self.subTest(rol=rol):
                text = npc_sohbet.ozet(state(), rol, ACIK, now=NOW)
                self.assertNotIn("zim", text.lower())
                self.assertNotIn("gizli iş", text)

    def test_the_secretary_sees_jobs_questions_and_usage_in_tokens_first(self):
        text = npc_sohbet.ozet(state(), "sekreter", ACIK, now=NOW)
        self.assertIn("Şu an: 2026-11-18 10:00", text)
        self.assertIn("blog · giriş sayfası · çalışıyor · Kıdemli", text)
        self.assertIn("Devam mı? · Sayfa böyle kalsın mı?", text)
        self.assertIn("blog · eski iş · takıldı", text)
        self.assertIn("232 bin token · API karşılığı ~$0.61", text)
        for word in ("harcama", "maliyet"):
            self.assertNotIn(word, text.lower())

    def test_the_accountant_lists_usage_per_project(self):
        text = npc_sohbet.ozet(state(), "muhasebe", ACIK, now=NOW)
        self.assertIn("- blog: 182 bin token · API karşılığı ~$0.41", text)
        self.assertIn("- CEO: 50 bin token · API karşılığı ~$0.20", text)
        self.assertNotIn("vitrin:", text, "a project without usage is left out, never '$0.00'")

    def test_scopes(self):
        proje = npc_sohbet.ozet(state(), "proje:blog", ACIK, now=NOW)
        self.assertIn("giriş sayfası", proje)
        self.assertNotIn("vitrin", proje)
        qa = npc_sohbet.ozet(state(), "mudur:qa", ACIK, now=NOW)
        self.assertIn("vitrin · inceleme", qa)
        self.assertNotIn("giriş sayfası", qa)

    def test_bounded(self):
        many = [task("blog", f"iş {i} " + "uzun başlık " * 40) for i in range(300)]
        decisions = [{"project": "blog", "title": "s" * 500, "question": "q" * 5000} for _ in range(100)]
        for rol in ("sekreter", "psikolog", "proje:blog"):
            text = npc_sohbet.ozet(state(tasks=many, decisions=decisions), rol, ACIK, now=NOW)
            self.assertLessEqual(len(text), npc_sohbet.OZET_SINIRI + 40)
            self.assertTrue(all(len(line) <= npc_sohbet.SATIR_SINIRI for line in text.splitlines()))

    def test_a_broken_state_gives_a_short_summary(self):
        for bad in (None, {}, {"tasks": "x", "decisions": [1, None], "projects": {"a": 1}, "summary": []}):
            self.assertIn("Açık iş: 0", npc_sohbet.ozet(bad, "sekreter", ACIK, now=NOW))


FAKE = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_OUT/args"
pwd > "$FAKE_OUT/cwd"
echo "oturum=[$OFIS_OTURUMU] test=[$OFIS_TEST]" > "$FAKE_OUT/env"
cat "$FAKE_OUT/reply"
exit "$(cat "$FAKE_OUT/code")"
"""


class CallTest(unittest.TestCase):
    """The one `claude -p` call against a fake claude binary."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.realpath(self.tmp.name)
        os.environ["FAKE_OUT"] = self.out
        self.bin = os.path.join(self.out, "claude")
        with open(self.bin, "w") as f:
            f.write(FAKE)
        os.chmod(self.bin, os.stat(self.bin).st_mode | stat.S_IEXEC)
        self.durum = os.path.join(self.out, "durum")
        self.reply({"type": "result", "subtype": "success", "is_error": False,
                    "result": "Bugün blog'da bir iş takıldı. Anahtar sk-ant-0123456789abcdefXYZ\x1b[31m",
                    "total_cost_usd": 0.002, "usage": {"input_tokens": 1200, "output_tokens": 80}})
        self.cfg = dict(ACIK, npc_sohbet={"acik": True, "saatlik_sinir": 50})
        self.sohbet = npc_sohbet.Sohbet(self.durum, claude_cli.ClaudeCLI(claude_bin=self.bin), lambda: self.cfg,
                                        lambda: state())

    def tearDown(self):
        self.tmp.cleanup()

    def reply(self, data, code=0):
        with open(os.path.join(self.out, "reply"), "w") as f:
            f.write(json.dumps(data) if isinstance(data, dict) else data)
        with open(os.path.join(self.out, "code"), "w") as f:
            f.write(str(code))

    def args(self):
        with open(os.path.join(self.out, "args"), encoding="utf-8") as f:
            return f.read().split("\n")

    def test_options_folder_environment_and_masking(self):
        out = self.sohbet.sor("sekreter", "--help bugün ne oldu?")
        self.assertTrue(out["cevap"].startswith("Bugün blog'da bir iş takıldı."))
        self.assertNotIn("0123456789abcdefXYZ", out["cevap"])
        self.assertNotIn("\x1b", out["cevap"])
        self.assertEqual(out["kullanim"], "1,3 bin token · API karşılığı ~$0.002")
        args = self.args()
        self.assertEqual(args[0], "-p")
        self.assertEqual(args[args.index("--tools") + 1], "", "no tools at all")
        self.assertEqual(args[args.index("--model") + 1], "haiku")
        self.assertEqual(args[args.index("--effort") + 1], "low")
        for flag in ("--no-session-persistence", "--strict-mcp-config", "--safe-mode", "--disable-slash-commands"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--output-format") + 1], "json")
        prompt = "\n".join(args[args.index("--output-format") + 2:])
        self.assertFalse(prompt.startswith("-"))
        self.assertIn("~~~\n--help bugün ne oldu?\n~~~", prompt, "the question is fenced data inside the prompt")
        self.assertIn("blog · giriş sayfası", prompt)
        self.assertNotIn("zim", prompt.lower())
        with open(os.path.join(self.out, "cwd")) as f:
            self.assertEqual(os.path.realpath(f.read().strip()),
                             os.path.realpath(os.path.join(self.durum, "npc_sohbet", "bos")))
        self.assertEqual(os.listdir(os.path.join(self.durum, "npc_sohbet", "bos")), [])
        with open(os.path.join(self.out, "env")) as f:
            self.assertEqual(f.read().strip(), "oturum=[1] test=[]")

    def test_the_model_follows_the_kolay_tier(self):
        self.cfg = dict(self.cfg, tiers={"kolay": {"model": "sonnet", "effort": "low"}})
        self.sohbet.sor("muhasebe", "Bugün ne kadar kullandık?")
        args = self.args()
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        self.assertEqual(npc_sohbet.Sohbet.model({}), "haiku")
        self.assertEqual(npc_sohbet.Sohbet.model({"tiers": {"kolay": {"model": "-x; rm"}}}), "haiku")

    def test_failures_become_one_turkish_error(self):
        cases = [({"result": "x", "is_error": True}, 0), ({"result": "ok"}, 1), ("not json", 0),
                 ({"result": "   "}, 0)]
        for data, code in cases:
            with self.subTest(data=data, code=code):
                self.reply(data, code)
                with self.assertRaises(npc_sohbet.CagriHatasi):
                    self.sohbet.sor("sekreter", "ne oldu?")
        self.sohbet.cli.claude_bin = os.path.join(self.out, "yok")
        with self.assertRaises(npc_sohbet.CagriHatasi):
            self.sohbet.sor("sekreter", "ne oldu?")

    def test_input_checks(self):
        with self.assertRaises(npc_sohbet.Gecersiz):
            self.sohbet.sor("sekreter", "x" * 501)
        with self.assertRaises(npc_sohbet.Gecersiz):
            self.sohbet.sor("sekreter", "   ")
        with self.assertRaises(npc_sohbet.Gecersiz):
            self.sohbet.sor("cayci", "ne oldu?")
        self.cfg = {}
        with self.assertRaises(npc_sohbet.Kapali):
            self.sohbet.sor("sekreter", "ne oldu?")
        self.assertFalse(os.path.exists(os.path.join(self.out, "args")), "no call for a refused question")


class LimitTest(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.calls = []
        self.sohbet = npc_sohbet.Sohbet("/nonexistent", None, lambda: ACIK, lambda: state(),
                                        clock=lambda: self.now[0])
        self.sohbet.cagir = lambda model, sistem, prompt: (self.calls.append(prompt), ("Tamam.", 0.001, 100))[1]

    def test_hourly_limit_with_the_minutes_until_it_frees(self):
        for _ in range(3):
            self.sohbet.sor("sekreter", "ne oldu?")
        self.now[0] += 600
        with self.assertRaises(npc_sohbet.Sinir) as ctx:
            self.sohbet.sor("sekreter", "ne oldu?")
        self.assertEqual(ctx.exception.dakika, 50)
        self.assertIn("50 dakika", str(ctx.exception))
        code, body, extra = npc_sohbet.hata_json(ctx.exception)
        self.assertEqual((code, extra), (429, {"Retry-After": "3000"}))
        self.assertEqual(len(self.calls), 3)
        self.now[0] += 3000
        self.sohbet.sor("sekreter", "ne oldu?")
        self.assertEqual(len(self.calls), 4)

    def test_one_question_at_a_time(self):
        started, release = threading.Event(), threading.Event()

        def slow(model, sistem, prompt):
            started.set()
            release.wait(5)
            return "Tamam.", 0.0, 0
        self.sohbet.cagir = slow
        t = threading.Thread(target=self.sohbet.sor, args=("sekreter", "ne oldu?"))
        t.start()
        self.assertTrue(started.wait(5))
        with self.assertRaises(npc_sohbet.Mesgul) as ctx:
            self.sohbet.sor("muhasebe", "ne kadar?")
        self.assertIn("Biraz bekle", str(ctx.exception))
        release.set()
        t.join(5)
        self.assertEqual(self.sohbet.sor("muhasebe", "ne kadar?")["kullanim"], "kayıt yok")


class PostTest(unittest.TestCase):
    """POST /api/npc-sohbet on a live test server (test_server.ServerTest's harness, without its tests)."""

    def setUp(self):
        import test_server
        self.ts = test_server
        test_server.ServerTest.setUp(self)
        self.app.cfg["npc_sohbet"] = {"acik": True, "saatlik_sinir": 2}
        self.calls = []
        self.app.npc_sohbet.cagir = lambda model, sistem, prompt: (
            self.calls.append((model, prompt)), ("Bugün sakin bir gün <b>x</b>.", 0.002, 1200))[1]

    def tearDown(self):
        self.ts.ServerTest.tearDown(self)

    def post(self, path, payload, **over):
        return self.ts.ServerTest.post(self, path, payload, **over)

    def raw(self, *a, **kw):
        return self.ts.ServerTest.raw(self, *a, **kw)

    def test_security_like_every_post(self):
        payload = {"npc": "sekreter", "soru": "ne oldu?"}
        for over, status in (({"Origin": "http://evil.example"}, 403), ({"Origin": None}, 403),
                             ({"X_Ofis_Token": None}, 403), ({"X_Ofis_Token": "wrong"}, 403),
                             ({"Content_Type": "text/plain"}, 415), ({"Host": "evil.example:80"}, 403),
                             ({"Authorization": "Bearer x"}, 403)):
            with self.subTest(over=over):
                resp, _ = self.post("/api/npc-sohbet", payload, **over)
                self.assertEqual(resp.status, status)
        resp, _ = self.post("/api/npc-sohbet", b"{not json")
        self.assertEqual(resp.status, 400)
        resp, _ = self.post("/api/npc-sohbet", ["sekreter"])
        self.assertEqual(resp.status, 400)
        resp, _ = self.post("/api/npc-sohbet", json.dumps({"npc": "sekreter", "soru": "x" * (17 * 1024)}).encode())
        self.assertEqual(resp.status, 413)
        resp, _ = self.raw("GET", "/api/npc-sohbet", {"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(resp.status, 404)
        self.assertEqual(self.calls, [], "no model call for a refused request")

    def test_bad_input_is_400_and_off_is_409(self):
        for payload in ({"npc": "yok", "soru": "x"}, {"npc": "sekreter", "soru": ""}, {"npc": "sekreter", "soru": 5},
                        {"npc": "sekreter", "soru": "x" * 501}, {"npc": ["sekreter"], "soru": "x"},
                        {"npc": "proje:zim", "soru": "x"}):
            with self.subTest(payload=str(payload)[:60]):
                resp, data = self.post("/api/npc-sohbet", payload)
                self.assertEqual(resp.status, 400, data)
        self.app.cfg["npc_sohbet"]["acik"] = False
        resp, data = self.post("/api/npc-sohbet", {"npc": "sekreter", "soru": "ne oldu?"})
        self.assertEqual(resp.status, 409)
        self.assertIn("Ayarlar", json.loads(data)["error"])
        self.assertEqual(self.calls, [])

    def test_an_answer_then_the_limit(self):
        resp, data = self.post("/api/npc-sohbet", {"npc": "proje:blog", "soru": "blog'da ne takıldı?"})
        self.assertEqual(resp.status, 200, data)
        out = json.loads(data)
        self.assertEqual(out["cevap"], "Bugün sakin bir gün <b>x</b>.")  # plain text: the page uses textContent
        self.assertEqual(out["kullanim"], "1,2 bin token · API karşılığı ~$0.002")
        self.assertEqual(out["unvan"], "blog proje sorumlusu")
        self.assertIn("blog'da ne takıldı?", self.calls[0][1])
        resp, _ = self.post("/api/npc-sohbet", {"npc": "sekreter", "soru": "ne oldu?"})
        self.assertEqual(resp.status, 200)
        resp, data = self.post("/api/npc-sohbet", {"npc": "sekreter", "soru": "ne oldu?"})
        self.assertEqual(resp.status, 429)
        self.assertIn("Saatte en çok 2", json.loads(data)["error"])
        self.assertEqual(resp.getheader("Retry-After"), "3600")
        self.assertEqual(len(self.calls), 2)

    def test_the_state_tells_the_page_whether_it_is_on(self):
        _, body = self.raw("GET", "/api/state", {"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(json.loads(body)["npc_sohbet"], {"acik": True, "saatlik_sinir": 2})

if __name__ == "__main__":
    unittest.main()
