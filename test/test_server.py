"""Tests for bin/server.py: host/origin/token checks, static files, chat/answer endpoints, SSE. Fake claude only."""
import contextlib
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402
import ceo  # noqa: E402
import server  # noqa: E402

server.Handler.log_message = lambda self, *args: None  # keep test output readable

NONCE = "test-nonce-0123456789"
CEO_SID = "66666666-aaaa-bbbb-cccc-000000000006"
W1 = "11111111-aaaa-bbbb-cccc-000000000001"
ZIM_SID = "33333333-aaaa-bbbb-cccc-000000000003"
INDEX = """<!doctype html><html><head><meta name="ofis-token" content="%%OFIS_PAGE_NONCE%%">
<script type="importmap">{"imports":{"three":"./vendor/three.js"}}</script></head><body>ofis</body></html>"""


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "ajan-ofisi")
        self.web = os.path.join(self.root, "web")
        self.durum = os.path.join(self.root, "durum")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.blog = os.path.join(base, "Dev", "blog")
        self.zim = os.path.join(base, "Dev", "zim")
        for d in (os.path.join(self.web, "vendor"), os.path.join(self.web, ".git"), self.blog, self.zim,
                  os.path.join(self.vault, "Kararlar")):
            os.makedirs(d)
        with open(os.path.join(self.web, "index.html"), "w") as f:
            f.write(INDEX)
        with open(os.path.join(self.web, "vendor", "three.js"), "w") as f:
            f.write("export const x = 1;")
        with open(os.path.join(self.web, ".git", "config"), "w") as f:
            f.write("hidden")
        with open(os.path.join(self.web, "notes.md"), "w") as f:
            f.write("unknown type")
        with open(os.path.join(self.root, "secret.txt"), "w") as f:
            f.write("outside web")
        os.symlink(os.path.join(self.root, "secret.txt"), os.path.join(self.web, "leak.txt"))
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-10-blog-x.md",
                         {"proje": "blog", "durum": "bekliyor", "soruldu": "2026-11-10T16:30"},
                         "# blog — x\n\n## Soru\nDevam mı?\n")
        fakes.write_note(os.path.join(self.vault, "Kararlar"), "2026-11-09-blog-eski.md",
                         {"proje": "blog", "durum": "cevaplandi"}, "## Soru\nEski\n")
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
               "projects": {"blog": {"path": self.blog}}}
        self.app = server.App(cfg, root=self.root, web_dir=self.web, durum_dir=self.durum,
                              projects_dir=os.path.join(base, "projects"), claude_bin=self.fake.path,
                              page_nonce=NONCE, ceo_kwargs={"sleep": lambda s: None, "find_attempts": 3})
        self.app.cli.cache_seconds = 0
        self.httpd = server.make_server(self.app, ports=[0])
        self.port = self.app.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.stop_event.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.join_refreshes()  # a refresh after a delivery may still write under durum/ (flaky cleanup)
        self.tmp.cleanup()

    # --- helpers ---

    def raw(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        if body is not None:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        if body is not None:
            conn.send(body)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def get(self, path, host=None):
        return self.raw("GET", path, {"Host": host or f"127.0.0.1:{self.port}"})

    def post(self, path, payload, **over):
        headers = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}",
                   "Content-Type": "application/json", "X-Ofis-Token": NONCE}
        for k, v in over.items():
            key = k.replace("_", "-")
            if v is None:
                headers.pop(key, None)
            else:
                headers[key] = v
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.raw("POST", path, headers, body)

    def error(self, data):
        return json.loads(data)["error"]

    # --- host / origin / token ---

    def test_index_injects_nonce_and_sets_csp(self):
        resp, data = self.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn(NONCE.encode(), data)
        self.assertNotIn(b"%%OFIS_PAGE_NONCE%%", data)
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("'sha256-", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        resp, _ = self.get("/", host=f"localhost:{self.port}")
        self.assertEqual(resp.status, 200)

    def test_bad_host_is_rejected(self):
        for host in ("evil.example:%d" % self.port, f"127.0.0.1:{self.port + 1}", "127.0.0.1", f"0.0.0.0:{self.port}",
                     f"127.0.0.1:{self.port}.evil.example"):
            with self.subTest(host=host):
                resp, data = self.get("/api/state", host=host)
                self.assertEqual(resp.status, 403)
                self.assertNotIn(NONCE.encode(), data)
        resp, _ = self.raw("GET", "/", {})
        self.assertEqual(resp.status, 403)
        resp, _ = self.post("/api/chat", {"text": "x"}, Host="evil.example")
        self.assertEqual(resp.status, 403)
        self.assertEqual(self.fake.calls(), [])

    def test_kullanim_endpoint(self):
        """GET /api/kullanim (bin/kullanim.py): the limit pill's popup; the Host check like every GET; a ZIM-folder
        transcript contributes nothing; no session ids or paths."""
        zim_folder = os.path.join(self.app.office.projects_dir, self.zim.replace("/", "-"))
        os.makedirs(zim_folder)
        with open(os.path.join(zim_folder, f"{ZIM_SID}.jsonl"), "w") as f:
            f.write(json.dumps({"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "message": {"id": "b1", "model": "claude-opus-5-5",
                                            "usage": {"input_tokens": 5, "output_tokens": 5}}}) + "\n")
        resp, data = self.get("/api/kullanim")
        self.assertEqual(resp.status, 200)
        body = json.loads(data)
        self.assertEqual(set(body), {"limitler", "dagilim", "not", "hesaplandi"})
        self.assertEqual(set(body["dagilim"]), {"bes_saat", "haftalik"})
        self.assertEqual(body["dagilim"]["bes_saat"]["satirlar"], [])
        for bad in (ZIM_SID.encode(), b"zim", self.tmp.name.encode()):
            self.assertNotIn(bad, data)
        resp, _ = self.get("/api/kullanim", host="evil.example:%d" % self.port)
        self.assertEqual(resp.status, 403)

    def test_post_needs_exact_origin(self):
        for origin in (None, "null", "http://evil.example", f"https://127.0.0.1:{self.port}",
                       f"http://127.0.0.1:{self.port}/", f"http://127.0.0.1:{self.port + 1}"):
            with self.subTest(origin=origin):
                resp, data = self.post("/api/chat", {"text": "x"}, Origin=origin)
                self.assertEqual(resp.status, 403)
                self.assertEqual(self.error(data), "origin not allowed")
        self.assertEqual(self.fake.calls(), [])

    def test_token_never_in_state(self):
        resp, data = self.get("/api/state")
        self.assertEqual(resp.status, 200)
        self.assertNotIn(NONCE, str(data))

    def test_post_needs_token(self):
        for token in (None, "", "wrong", NONCE + "x"):
            with self.subTest(token=token):
                resp, data = self.post("/api/chat", {"text": "x"}, X_Ofis_Token=token)
                self.assertEqual(resp.status, 403)
                self.assertEqual(self.error(data), "invalid token")
        self.assertEqual(self.fake.calls(), [])

    def test_post_content_type_size_and_json(self):
        resp, _ = self.post("/api/chat", {"text": "x"}, Content_Type="text/plain")
        self.assertEqual(resp.status, 415)
        resp, _ = self.post("/api/chat", {"text": "x"}, Content_Type=None)
        self.assertEqual(resp.status, 415)
        resp, _ = self.post("/api/chat", b"x" * (16 * 1024 + 1))
        self.assertEqual(resp.status, 413)
        resp, _ = self.post("/api/chat", b"{not json")
        self.assertEqual(resp.status, 400)
        resp, _ = self.post("/api/chat", [1, 2])
        self.assertEqual(resp.status, 400)
        for text in ("", "   ", 5, None, "x" * 4001):
            with self.subTest(text=text):
                resp, _ = self.post("/api/chat", {"text": text})
                self.assertEqual(resp.status, 400)
        self.assertEqual(self.fake.calls(), [])

    # --- static files ---

    def test_static_files_and_traversal(self):
        resp, data = self.get("/vendor/three.js")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "text/javascript; charset=utf-8")
        for path in ("/../secret.txt", "/vendor/../../secret.txt", "/%2e%2e/secret.txt", "/vendor/%2e%2e/%2e%2e/secret.txt",
                     "/..%2fsecret.txt", "/vendor/..%5c..%5csecret.txt", "/leak.txt", "/.git/config", "/vendor/",
                     "/vendor", "/notes.md", "/missing.js", "//etc/passwd", "/%00index.html", "/api/nope"):
            with self.subTest(path=path):
                resp, data = self.get(path)
                self.assertEqual(resp.status, 404)
                self.assertNotIn(b"outside web", data)
                self.assertNotIn(b"hidden", data)

    def test_other_methods_are_refused(self):
        for method in ("PUT", "DELETE", "OPTIONS", "PATCH"):
            resp, _ = self.raw(method, "/api/chat", {"Host": f"127.0.0.1:{self.port}"})
            self.assertEqual(resp.status, 405)
            self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))

    # --- endpoints ---

    def test_chat_post_starts_ceo_with_prefixed_text(self):
        resp, data = self.post("/api/chat", {"text": "  merhaba  "})
        self.assertEqual(resp.status, 202)
        self.assertEqual(json.loads(data), {"status": "delivered"})
        call = self.fake.calls()[0]
        self.assertEqual(call["args"], ["--bg", "--name", "ofis-ceo", "--append-system-prompt",
                                        ceo.ceo_system_prompt("Selin"),
                                        "[Sahip · ofis sayfası]\nmerhaba\n(Selin'e Türkçe ve sade yaz.)"])
        self.assertEqual(os.path.realpath(call["cwd"]), self.root)

    def test_the_refresh_after_a_delivery_is_joined_before_cleanup(self):
        # review step 3, minor 7: deliver() starts a refresh thread; the test teardown waits for it
        started, release = threading.Event(), threading.Event()
        def slow():
            started.set()
            release.wait(5)
        self.app.hub.refresh = slow
        resp, _ = self.post("/api/chat", {"text": "merhaba"})
        self.assertEqual(resp.status, 202)
        self.assertTrue(started.wait(5))
        self.assertTrue(any(t.is_alive() for t in self.app._refreshers))
        release.set()
        self.app.join_refreshes()
        self.assertFalse(any(t.is_alive() for t in self.app._refreshers))

    def test_chat_text_starting_with_dash_is_still_safe(self):
        resp, _ = self.post("/api/chat", {"text": "--dangerously-skip-permissions"})
        self.assertEqual(resp.status, 202)
        self.assertEqual(self.fake.calls()[0]["args"][-1],
                         "[Sahip · ofis sayfası]\n--dangerously-skip-permissions\n(Selin'e Türkçe ve sade yaz.)")

    def test_chat_post_is_queued_when_ceo_busy(self):
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo.json"), "w") as f:
            json.dump({"session_id": CEO_SID}, f)
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, CEO_SID, "busy")])
        resp, data = self.post("/api/chat", {"text": "bir"})
        self.assertEqual((resp.status, json.loads(data)), (202, {"status": "queued"}))
        self.assertEqual(self.fake.calls(), [])

    def test_chat_post_409_when_claude_fails(self):
        self.fake.flag("fail")
        resp, data = self.post("/api/chat", {"text": "merhaba"})
        self.assertEqual(resp.status, 409)
        self.assertIn("CEO", self.error(data))

    def test_answer_validation(self):
        cases = [("../Kararlar/2026-11-10-blog-x.md", 400), ("Kararlar/2026-11-10-blog-x.md", 400),
                 ("a\\b.md", 400), ("x", 400), (5, 400), ("yok.md", 404), ("2026-11-09-blog-eski.md", 409)]
        for note, status in cases:
            with self.subTest(note=note):
                resp, _ = self.post("/api/answer", {"note": note, "answer": "Onaylıyorum"})
                self.assertEqual(resp.status, status)
        resp, _ = self.post("/api/answer", {"note": "2026-11-10-blog-x.md", "answer": " "})
        self.assertEqual(resp.status, 400)
        self.assertEqual(self.fake.calls(), [])

    def test_answer_is_delivered_with_note_prefix_and_vault_untouched(self):
        note_path = os.path.join(self.vault, "Kararlar", "2026-11-10-blog-x.md")
        before = open(note_path).read()
        resp, data = self.post("/api/answer", {"note": "2026-11-10-blog-x.md", "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 202)
        self.assertEqual(self.fake.calls()[0]["args"][-1],
                         "[Sahip · karar cevabı] 2026-11-10-blog-x.md\nOnaylıyorum\n(Selin'e Türkçe ve sade yaz.)")
        self.assertEqual(open(note_path).read(), before)
        _, data = self.get("/api/state")
        self.assertTrue(json.loads(data)["decisions"][0]["answer_sent"])

    def restarted(self):
        """A second App on the same durum folder (the server after a restart): nothing kept in memory."""
        app = server.App(self.app.cfg, root=self.root, web_dir=self.web, durum_dir=self.durum,
                         projects_dir=self.app.office.projects_dir, claude_bin=self.fake.path, page_nonce=NONCE,
                         ceo_kwargs={"sleep": lambda s: None, "find_attempts": 3})
        app.cli.cache_seconds = 0
        return app

    def ceo_busy(self):
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo.json"), "w") as f:
            json.dump({"session_id": CEO_SID}, f)
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, CEO_SID, "busy")])

    def test_a_second_answer_is_refused_while_the_first_is_queued(self):
        # seen live: after a restart the card offered the answer box again and the CEO got the same answer twice
        self.ceo_busy()
        note = "2026-11-10-blog-x.md"
        resp, data = self.post("/api/answer", {"note": note, "answer": "Onaylıyorum"})
        self.assertEqual((resp.status, json.loads(data)["status"]), (202, "queued"))
        resp, data = self.post("/api/answer", {"note": note, "answer": "Hayır"})
        self.assertEqual(resp.status, 409)
        self.assertEqual(json.loads(data)["kod"], "cevap-iletildi")
        self.assertIn("zaten iletildi", self.error(data))
        self.assertEqual(len(self.app.ceo.queue()), 1)
        app = self.restarted()  # the queue survives; the page still shows "cevap iletildi"
        app.hub.refresh()
        self.assertTrue(app.hub.state["decisions"][0]["answer_sent"])

    def test_a_delivered_answer_survives_a_restart(self):
        note = "2026-11-10-blog-x.md"
        resp, _ = self.post("/api/answer", {"note": note, "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 202)
        self.assertEqual(self.app.ceo.queue(), [])
        app = self.restarted()
        app.hub.refresh()
        self.assertTrue(app.hub.state["decisions"][0]["answer_sent"])
        # the restarted server refuses a second answer too
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app = app
        self.httpd = server.make_server(app, ports=[0])
        self.port = app.port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        calls = len(self.fake.calls())
        resp, data = self.post("/api/answer", {"note": note, "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 409)
        self.assertEqual(json.loads(data)["kod"], "cevap-iletildi")
        self.assertEqual(len(self.fake.calls()), calls)

    def test_a_delivered_answer_may_be_sent_again_when_the_ceo_never_recorded_it(self):
        # review of phase 5: the CEO's turn may die before `cevapla`; after a while the card takes an answer again
        note = "2026-11-10-blog-x.md"
        resp, _ = self.post("/api/answer", {"note": note, "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 202)
        self.assertIn(note, self.app.answers.notes())
        self.app.answers.clock = lambda: server.time.time() + server.AnswerLog.RESEND_AFTER + 1
        self.assertNotIn(note, self.app.answers.notes())
        resp, _ = self.post("/api/answer", {"note": note, "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 202)

    def test_an_answered_decision_is_refused_in_turkish(self):
        resp, data = self.post("/api/answer", {"note": "2026-11-09-blog-eski.md", "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 409)
        self.assertEqual(json.loads(data)["kod"], "cevap-iletildi")
        self.assertIn("zaten", self.error(data))

    def test_a_failed_answer_can_be_sent_again(self):
        self.fake.flag("fail")
        resp, _ = self.post("/api/answer", {"note": "2026-11-10-blog-x.md", "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 409)
        self.fake.flag("fail", False)
        resp, _ = self.post("/api/answer", {"note": "2026-11-10-blog-x.md", "answer": "Onaylıyorum"})
        self.assertEqual(resp.status, 202)

    def test_state_and_chat_endpoints(self):
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo.json"), "w") as f:
            json.dump({"session_id": CEO_SID}, f)
        fakes.write_transcript(self.app.office.projects_dir, self.root, CEO_SID, [
            fakes.human(date.today(), "[Deniz · ofis sayfası]\nselam"),  # old protocol: still parsed
        ])
        self.fake.set_agents([fakes.agent("ofis-blog-1-ab", self.blog, W1, "busy"),
                              fakes.agent("ofis-zim-1-ab", self.zim, ZIM_SID, "busy"),
                              fakes.agent("ofis-ceo", self.root, CEO_SID, "idle")])
        resp, data = self.get("/api/state")
        self.assertEqual(resp.status, 200)
        s = json.loads(data)
        self.assertEqual([x["name"] for x in s["sessions"]], ["ofis-blog-1-ab"])
        self.assertNotIn(ZIM_SID, data.decode())
        self.assertEqual(s["ceo"]["state"], "idle")
        self.assertEqual(s["decisions"][0]["note"], "2026-11-10-blog-x.md")
        resp, data = self.get("/api/chat")
        self.assertEqual([(m["role"], m["text"]) for m in json.loads(data)["messages"]], [("sahip", "selam")])

    def test_task_detail_endpoint(self):
        os.makedirs(os.path.join(self.vault, "Isler"))
        fakes.write_note(os.path.join(self.vault, "Isler"), "2026-11-10-1-blog.md",
                         {"proje": "blog", "durum": "bitti", "oturum": "ofis-blog-1-ab"},
                         "# x\n\n## Görev\n\nDurum özeti.\n\n## Sonuç\n\nHepsi temiz.\n")
        resp, data = self.get("/api/task?note=2026-11-10-1-blog.md")
        self.assertEqual(resp.status, 200)
        d = json.loads(data)
        self.assertEqual((d["project"], d["title"], d["result"]), ("blog", "Durum özeti.", "Hepsi temiz."))
        for bad in ("../Kararlar/2026-11-10-blog-x.md", "%2e%2e%2fKararlar%2f2026-11-10-blog-x.md", "yok.md", ""):
            with self.subTest(bad=bad):
                resp, _ = self.get(f"/api/task?note={bad}")
                self.assertEqual(resp.status, 404)
        resp, _ = self.get("/api/task?note=2026-11-10-1-blog.md", host="evil.example:80")
        self.assertEqual(resp.status, 403)

    def test_task_detail_endpoint_reads_the_job_folders(self):
        fakes.write_note(os.path.join(self.vault, "Isler", "Devam-Edenler"), "2026-11-10-2-blog.md",
                         {"proje": "blog", "durum": "karar-bekliyor", "baslik": "Giriş"},
                         "# x\n\n## Görev\n\n### Hedef\n\nDüzelt.\n")
        resp, data = self.get("/api/task?note=2026-11-10-2-blog.md")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data)["status"], "karar-bekliyor")

    # --- phase 7: İşler board, Raporlar, Kalite (GET only) ---

    def write_report(self, grup, body="# blog — Giriş (g)\n\n## İşler\n\n| İş | Katman / model | Sonuç |\n|---|---|---|\n"
                                      "| [[2026-11-10-1-blog]] | kod / opus | bitti |\n"):
        folder = os.path.join(self.vault, "Raporlar")
        os.makedirs(folder, exist_ok=True)
        fakes.write_note(folder, f"{grup}.md", {"proje": "blog", "grup": grup, "tur": "grup", "surum": "1",
                                                "bitis": "2026-11-10T19:00:00", "toplam_usd": "0.0111"}, body)

    def test_the_report_list_and_one_report(self):
        self.write_report("giris")
        resp, data = self.get("/api/raporlar")
        self.assertEqual(resp.status, 200)
        [r] = json.loads(data)["raporlar"]
        self.assertEqual((r["grup"], r["is_sayisi"], r["toplam_usd"]), ("giris", 1, 0.0111))
        resp, data = self.get("/api/rapor?grup=giris")
        self.assertEqual(resp.status, 200)
        d = json.loads(data)
        self.assertTrue(d["metin"].startswith("# blog — Giriş"))
        self.assertEqual(d["sonuclar"], {"bitti": 1})
        resp, _ = self.get("/api/rapor?grup=yok")
        self.assertEqual(resp.status, 404)
        resp, _ = self.get("/api/raporlar", host="evil.example:80")
        self.assertEqual(resp.status, 403)

    def test_a_report_outside_the_reports_folder_cannot_be_read(self):
        with open(os.path.join(self.vault, "gizli.md"), "w") as f:
            f.write("gizli")
        os.makedirs(os.path.join(self.vault, "Raporlar"))
        os.symlink(os.path.join(self.vault, "gizli.md"), os.path.join(self.vault, "Raporlar", "baglanti.md"))
        for bad in ("../gizli", "%2e%2e%2fgizli", "..%2fgizli", "Raporlar%2fx", "", "gizli.md", "a%00b"):
            with self.subTest(bad=bad):
                resp, data = self.get(f"/api/rapor?grup={bad}")
                self.assertEqual(resp.status, 400)
                self.assertNotIn(b"gizli\"", data)
        resp, data = self.get("/api/rapor?grup=baglanti")
        self.assertEqual(resp.status, 404)
        resp, data = self.get("/api/raporlar")
        self.assertEqual(json.loads(data)["raporlar"], [])

    def test_a_note_name_resolves_to_its_obsidian_path_under_ofis_only(self):
        os.makedirs(os.path.join(self.vault, "Ozetler"))
        with open(os.path.join(self.vault, "Ozetler", "2026-11-13.md"), "w") as f:
            f.write("özet")
        resp, data = self.get("/api/not-yolu?ad=2026-11-13&tercih=Ozetler")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data), {"yol": "OFIS/Ozetler/2026-11-13", "kasa": "vault"})
        resp, data = self.get("/api/not-yolu?ad=2026-11-10-blog-x")
        self.assertEqual(json.loads(data)["yol"], "OFIS/Kararlar/2026-11-10-blog-x")
        with open(os.path.join(os.path.dirname(self.vault), "disarida.md"), "w") as f:
            f.write("x")
        for bad in ("disarida", "..%2Fdisarida", "Kararlar%2F2026-11-10-blog-x", "", "yok"):
            with self.subTest(bad=bad):
                resp, data = self.get(f"/api/not-yolu?ad={bad}")
                self.assertEqual(resp.status, 404)
                self.assertNotIn(b"yol", data)
        resp, _ = self.get("/api/not-yolu?ad=2026-11-13", host="evil.example:80")
        self.assertEqual(resp.status, 403)
        resp, _ = self.post("/api/not-yolu?ad=2026-11-13", {})
        self.assertEqual(resp.status, 404)

    def test_the_quality_endpoint_reads_the_scorecard(self):
        resp, data = self.get("/api/kalite")
        self.assertEqual(resp.status, 200)
        body = json.loads(data)
        choice = body.pop("model_secimi")  # phase 8: the model selection rides along
        self.assertEqual(body.pop("denetciler"), [])  # the reviewer scorecard in short (İK card)
        self.assertEqual(body, {"satirlar": [], "modeller": [], "uzmanliklar": [], "toplam": None, "is_sayisi": 0,
                                "deneme_sayisi": 0, "deneme_isler": []})
        self.assertEqual((choice["pilotlar"], choice["oneriler"]), ([], []))
        self.assertIsInstance(choice["eslesme"], list)
        folder = os.path.join(self.vault, "Karne")
        os.makedirs(folder)
        with open(os.path.join(folder, "Kayitlar-2026-11.md"), "w", encoding="utf-8") as f:
            f.write("| Tarih | Proje | İş | Katman | Model | Effort | Kontrol ilk turda | Kontrol denemesi | Yükseltme | "
                    "Çağrı | Maliyet ($) | Doğrulanmış maliyet ($) | Süre (dk) | Sonuç | Devam | Akış | Adım |\n"
                    "| 2026-11-10 | blog | [[a]] | kolay | haiku | low | evet | 1 | hayır | 3 | 0.0111 | 0.0111 | "
                    "2 | bitti | 0 |  |  |\n")
        [row] = json.loads(self.get("/api/kalite")[1])["satirlar"]
        self.assertEqual((row["model"], row["dogrulanmis_is_basina_usd"], row["ilk_tur_gecen"]), ("haiku", 0.0111, 1))

    def test_the_accounting_and_office_endpoints_read_only_and_host_checked(self):
        resp, data = self.get("/api/muhasebe")
        self.assertEqual(resp.status, 200)
        body = json.loads(data)
        self.assertEqual(set(body), {"gun", "ay", "saat_dilimi", "bugun", "bu_ay", "kalite", "bu_ay_rol_kalite", "bu_ay_uzmanlik",
                                     "en_pahali", "butce"})
        self.assertIsNone(body["bugun"]["token"])
        resp, data = self.get("/api/idari")
        self.assertEqual(resp.status, 200)
        body = json.loads(data)
        self.assertEqual(body["sunucu"]["pid"], os.getpid())
        self.assertIn("max_running", body["limitler"])
        self.assertTrue(json.loads(self.get("/api/state")[1])["sunucu"]["baslangic"])
        for path in ("/api/muhasebe", "/api/idari"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, host="evil.example")[0].status, 403)
                self.assertEqual(self.post(path, {})[0].status, 404)

    def test_the_ArGe_endpoint_is_read_only_host_checked_and_shows_the_last_report(self):
        import arge
        from datetime import datetime
        resp, data = self.get("/api/arge")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data)["son_rapor"], None)
        job = "2026-11-12-090000-arge.md"
        rid = arge.bekleyen_kaydet(self.durum, job, "Günlük Ar-Ge", "Özet satırı.\nÖNERİ-DENETÇİ: opencode/x-free | MIT | y",
                                   datetime(2026, 11, 12, 9, 40))
        arge.yaz_ve_bildir(self.app.cfg, self.durum, rid, now=datetime(2026, 11, 12, 9, 40))
        body = json.loads(self.get("/api/arge")[1])
        self.assertEqual((body["son_rapor"]["is"], body["son_rapor"]["ozet"]), (job, ["Özet satırı."]))
        self.assertEqual(body["son_rapor"]["oneriler"][0]["model"], "opencode/x-free")
        self.assertNotIn("metin", body["son_rapor"])
        self.assertEqual(body["son_rapor"]["not"], "ArGe-2026-11-12")  # the card gets a summary, never the whole report
        self.assertEqual(self.get("/api/arge", host="evil.example")[0].status, 403)
        self.assertEqual(self.post("/api/arge", {})[0].status, 404)

    def test_the_server_room_endpoint_is_read_only_host_checked_and_shows_group_totals_only(self):
        import sistem
        import test_sistem
        run = test_sistem.FakeRun()
        self.app.sistem = sistem.Sistem(run=run, which=test_sistem.which_all, own_pid=test_sistem.OWN_PID,
                                        durum_dir=self.durum, cfg=self.app.current_config)
        self.app.office.sistem = self.app.sistem
        resp, data = self.get("/api/sistem")
        self.assertEqual(resp.status, 200)
        body = json.loads(data)
        self.assertEqual(body["cpu"]["cekirdek"], 10)
        self.assertTrue(set(g["ad"] for g in body["gruplar"]) <= set(sistem.GRUPLAR))
        text = data.decode("utf-8").casefold()
        for word in ("zim", "/users", "kullanici7", "musteri_db"):
            self.assertNotIn(word, text)
        # no project has a domain list yet: the card says so
        self.assertEqual(body["domainler"]["metin"], sistem.YOK_METNI)
        self.assertEqual(self.get("/api/sistem", host="evil.example")[0].status, 403)
        self.assertEqual(self.post("/api/sistem", {})[0].status, 404)
        # the scene's lights ride along in /api/state from the cache
        self.app.hub.refresh()
        state = json.loads(self.get("/api/state")[1])
        self.assertEqual(state["sistem"]["seviye"], "yesil")

    def test_a_broken_ofis_json_falls_back_to_the_start_config_and_a_get_never_drops_the_connection(self):
        path = os.path.join(self.root, "ofis.json")
        self.app.config_path = path
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for text in ("null", "[]", "{broken"):
                with self.subTest(text=text):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                    self.assertIs(self.app.current_config(), self.app.cfg)
        self.assertEqual(err.getvalue().count("ofis.json okunamadı"), 1)  # said once
        os.remove(path)
        self.assertIs(self.app.current_config(), self.app.cfg)

        class Broken:
            def durum(self, **kw):
                raise TypeError("boom")
        self.app.sistem = Broken()
        with contextlib.redirect_stderr(io.StringIO()):
            resp, data = self.get("/api/sistem")
        self.assertEqual(resp.status, 500)
        self.assertEqual(json.loads(data), {"error": "internal error"})

    def test_the_new_page_endpoints_take_no_post(self):
        for path in ("/api/raporlar", "/api/rapor", "/api/kalite"):
            with self.subTest(path=path):
                resp, _ = self.post(path, {})
                self.assertEqual(resp.status, 404)

    def test_the_state_carries_the_board(self):
        fakes.write_note(os.path.join(self.vault, "Isler", "Siradakiler"), "2026-11-10-3-blog.md",
                         {"proje": "blog", "durum": "sirada", "olusturuldu": "2026-11-10T10:00:00"},
                         "# x\n\n## Görev\n\nx\n")
        board = json.loads(self.get("/api/state")[1])["board"]
        self.assertEqual([t["note"] for t in board], ["2026-11-10-3-blog.md"])

    def test_state_shows_the_post_office(self):
        resp, data = self.get("/api/state")
        po = json.loads(data)["postoffice"]
        self.assertEqual((po["inbox"], po["rejected"], po["rejected_outbox"], po["silent"]), (0, 0, 0, []))
        self.assertIs(self.app.postoffice.ceo, self.app.ceo)
        self.assertTrue(os.path.isdir(os.path.join(self.durum, "taslak")), "the CEO's input files go there")

    def test_the_kontrol_worker_runs_in_its_own_thread(self):
        targets = []
        real = server.threading.Thread

        def record(*a, target=None, **k):
            targets.append(target)
            return real(*a, target=lambda stop: None, **k)
        server.threading.Thread = record
        try:
            self.app.start_threads()
        finally:
            server.threading.Thread = real
        self.assertIn(self.app.postoffice.kontrol.run, targets)
        self.assertIn(self.app.postoffice.run, targets)

    def test_usage_endpoint(self):
        fakes.write_transcript(self.app.office.projects_dir, self.blog, W1, [
            fakes.assistant(date.today(), "m1", [{"type": "tool_use", "name": "Read", "input": {"file_path": "/gizli/plan.md"}}],
                            fakes.usage(1, 2, 3, 4))])
        self.fake.set_agents([fakes.agent("ofis-blog-1-ab", self.blog, W1, "idle")])
        self.get("/api/state")  # registers the session
        resp, data = self.get("/api/usage?project=blog")
        self.assertEqual(resp.status, 200)
        d = json.loads(data)
        self.assertEqual(d["total"], 10)
        self.assertEqual(d["sessions"][0]["by_tool"], {"Read": 10})
        self.assertNotIn("plan.md", data.decode())
        resp, _ = self.get("/api/usage?project=ceo")
        self.assertEqual(resp.status, 200)
        for bad in ("yok", "", "../x"):
            with self.subTest(bad=bad):
                resp, _ = self.get(f"/api/usage?project={bad}")
                self.assertEqual(resp.status, 404)

    def test_the_ceo_steps_endpoint_lists_safe_tool_targets_only(self):
        # Komuta masası: GET /api/ceo/adimlar — tool names and short targets, never text, full paths or ZIM
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo.json"), "w") as f:
            json.dump({"session_id": CEO_SID}, f)
        day = date.today()
        tool = lambda i, name, inp: {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}  # noqa: E731
        fakes.write_transcript(self.app.office.projects_dir, self.root, CEO_SID, [
            fakes.human(day, "[Deniz · ofis sayfası]\ndurum?"),  # old protocol: still parsed
            fakes.assistant(day, "m1", [{"type": "thinking", "thinking": "GIZLI-DUSUNCE"},
                                        {"type": "text", "text": "GIZLI-METIN"},
                                        tool(1, "Read", {"file_path": "/Users/x/Documents/vault/OFIS/README.md"})],
                            stop_reason="tool_use"),
            fakes.assistant(day, "m2", [tool(2, "Bash", {"command": "cd /Users/x/Dev/ajan-ofisi && python3 bin/ofis.py durum --json"})],
                            stop_reason="tool_use"),
            fakes.assistant(day, "m3", [tool(3, "Read", {"file_path": "/Users/x/Dev/zim/notes.md"})], stop_reason="tool_use"),
            fakes.assistant(day, "m4", [tool(4, "Grep", {"pattern": "x", "path": "/Users/x/vault/Mektuplar"})],
                            stop_reason="tool_use"),
            fakes.assistant(day, "m5", [tool(5, "Write", {"file_path": "/tmp/durum/taslak/cevap-1.txt",
                                                          "content": "GIZLI-ICERIK"})], stop_reason="tool_use"),
        ])
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, CEO_SID, "idle")])
        resp, data = self.get("/api/ceo/adimlar")
        self.assertEqual(resp.status, 200)
        d = json.loads(data)
        self.assertEqual(set(d), {"adimlar", "durum", "arac_simdi", "sure_sn"})
        self.assertEqual([(a["arac"], a["hedef"], a["ozet"]) for a in d["adimlar"]],
                         [("Write", "cevap-1.txt", "yazdı"), ("Bash", "python3 ofis.py durum", "çalıştırdı"),
                          ("Read", "README.md", "okudu")])
        for secret in ("GIZLI", "zim", "Mektuplar", "/Users", "notes.md"):
            self.assertNotIn(secret, data.decode())
        self.assertIsNone(d["arac_simdi"])  # idle: nothing runs now
        resp, _ = self.get("/api/ceo/adimlar", host="evil.example:80")
        self.assertEqual(resp.status, 403)
        resp, _ = self.post("/api/ceo/adimlar", {})
        self.assertEqual(resp.status, 404)

    def test_the_ceo_turns_endpoint(self):
        # Step 1 (owner decision 2026-11-12): GET /api/ceo/turlar — the footer under each reply (no text, no forbidden place)
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo.json"), "w") as f:
            json.dump({"session_id": CEO_SID}, f)
        day = date.today()
        cmd = "python3 bin/ofis.py ekle --brief-dosya durum/taslak/is-1.json"
        fakes.write_transcript(self.app.office.projects_dir, self.root, CEO_SID, [
            fakes.human(day, "[Deniz · ofis sayfası]\nblog giriş hatası"),  # old protocol: still parsed
            fakes.assistant(day, "m1", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": cmd}}],
                            usage=fakes.usage(), model="claude-opus-5-5", stop_reason="tool_use"),
            fakes.user(day, [{"type": "tool_result", "tool_use_id": "t1",
                              "content": '{"is": "2026-11-12-101500-blog.md", "katman": "kod", "model": "opus"}'}]),
            fakes.assistant(day, "m2", [{"type": "text", "text": "GIZLI-CEVAP"}], usage=fakes.usage(),
                            model="claude-opus-5-5"),
        ])
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, CEO_SID, "busy")])
        resp, data = self.get("/api/ceo/turlar")
        self.assertEqual(resp.status, 200)
        d = json.loads(data)
        self.assertTrue(d["kapaniyor"])
        [t] = d["turlar"]
        self.assertEqual(t["adim"], 1)
        self.assertEqual([(j["note"], j["baslik"], j["unvan"]) for j in t["isler"]],
                         [("2026-11-12-101500-blog.md", "2026-11-12-101500-blog", "Kıdemli")])
        self.assertNotIn("GIZLI", data.decode())
        resp, _ = self.get("/api/ceo/turlar", host="evil.example:80")
        self.assertEqual(resp.status, 403)
        resp, _ = self.post("/api/ceo/turlar", {})
        self.assertEqual(resp.status, 404)
        _, state = self.get("/api/state")
        self.assertTrue(json.loads(state)["ceo"]["tur_kapaniyor"])

    def test_the_ceo_steps_endpoint_without_a_ceo_session(self):
        resp, data = self.get("/api/ceo/adimlar")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data)["adimlar"], [])

    def test_ceo_rotation_wiring_and_handoff(self):
        # bin/ceo.py rotation: the App gives the CEO its settings and the handoff builder; without ceo_yenileme it is off
        self.assertIsNone(self.app.ceo.rotation_reason(CEO_SID))
        text = self.app.devir_notu("baglam", 1, "0123456789abcdef")
        self.assertTrue(text.startswith("[Ofis · devir notu · 0123456789abcdef]\n"))
        self.assertTrue(text.endswith("[Ofis · devir notu sonu · 0123456789abcdef]\n"))
        self.assertIn("[[2026-11-10-blog-x]]", text)  # the pending decision
        self.assertIn("Açık işler (0)", text)
        self.assertIn("kuyrukta 1 mesaj", text)
        resp, data = self.get("/api/state")
        self.assertEqual(resp.status, 200)
        self.assertIn("baglam_token", json.loads(data)["ceo"])

    def test_events_stream_sends_state_and_chat(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.sendall(f"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
        buf = b""
        while b"event: chat" not in buf or b"event: state" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        sock.close()
        self.assertIn(b"text/event-stream", buf)
        self.assertIn(b"event: state", buf)
        self.assertIn(b"event: chat", buf)

    def test_events_rejects_bad_host(self):
        resp, _ = self.get("/api/events", host="evil.example")
        self.assertEqual(resp.status, 403)


class PageKeyTest(unittest.TestCase):
    """The page token survives a restart (durum/sayfa_anahtari, 0600), regenerates when missing or corrupt."""

    def test_file_created_private_and_reused(self):
        with tempfile.TemporaryDirectory() as d:
            first = server.sayfa_anahtari_yukle(d)
            path = os.path.join(d, "sayfa_anahtari")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(server.sayfa_anahtari_yukle(d), first)
            self.assertGreaterEqual(len(first), 32)

    def test_missing_or_corrupt_regenerates(self):
        with tempfile.TemporaryDirectory() as d:
            first = server.sayfa_anahtari_yukle(d)
            path = os.path.join(d, "sayfa_anahtari")
            for bad in ("", "kisa", "bad token with spaces " * 3):
                with open(path, "w") as f:
                    f.write(bad)
                new = server.sayfa_anahtari_yukle(d)
                self.assertNotEqual(new, bad.strip())
                self.assertEqual(server.sayfa_anahtari_yukle(d), new)
            os.remove(path)
            self.assertNotEqual(server.sayfa_anahtari_yukle(d), first)


class PortTest(unittest.TestCase):
    def test_next_free_port_is_used(self):
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        free_port = free.getsockname()[1]
        free.close()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"ceo_session": "ofis-ceo", "vault_ofis": tmp, "projects": {}}
            app = server.App(cfg, root=tmp, web_dir=tmp, durum_dir=tmp, projects_dir=tmp)
            httpd = server.make_server(app, ports=[taken, free_port])
            self.assertEqual(app.port, free_port)
            self.assertEqual(httpd.server_address[0], "127.0.0.1")
            httpd.server_close()
        busy.close()


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_second_server_cannot_take_the_lock(self):
        held = server.acquire_lock(self.tmp.name)
        try:
            with self.assertRaises(server.AlreadyRunning):
                server.acquire_lock(self.tmp.name)
        finally:
            held.close()
        server.acquire_lock(self.tmp.name).close()  # free again once the first one is gone

    def test_main_refuses_the_test_config_override(self):
        # the live office never runs on a test config: either variable alone stops it before the lock or the config
        real_lock = server.acquire_lock

        def never(*a, **k):
            raise AssertionError("the server must stop before taking the lock")
        server.acquire_lock = never
        saved = {k: os.environ.get(k) for k in ("OFIS_TEST", "OFIS_CONFIG")}
        try:
            for env in ({"OFIS_TEST": "1"}, {"OFIS_CONFIG": "/tmp/x.json"}, {"OFIS_TEST": "1", "OFIS_CONFIG": "/tmp/x"}):
                with self.subTest(env=env):
                    for k in saved:
                        os.environ.pop(k, None)
                    os.environ.update(env)
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        code = server.main(durum_dir=self.tmp.name)
                    self.assertEqual(code, 1)
                    self.assertIn("yalnız testler içindir", err.getvalue())
        finally:
            server.acquire_lock = real_lock
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_main_exits_when_another_server_runs(self):
        held = server.acquire_lock(self.tmp.name)
        real_load, real_make = server.launch.load, server.make_server

        def never(*a, **k):
            raise AssertionError("a second server must stop before loading config or binding a port")
        server.launch.load = server.make_server = never
        err = io.StringIO()
        saved = {k: os.environ.pop(k) for k in ("OFIS_TEST", "OFIS_CONFIG") if k in os.environ}
        try:
            with contextlib.redirect_stderr(err):
                code = server.main(durum_dir=self.tmp.name)
        finally:
            os.environ.update(saved)
            server.launch.load, server.make_server = real_load, real_make
            held.close()
        # exit 0: launchd (bin/autostart.py, KeepAlive SuccessfulExit=false) must not restart it in a loop
        self.assertEqual(code, 0)
        self.assertIn("Ofis server already running", err.getvalue())
        self.assertIn("ofis: başlatılıyor", err.getvalue())  # the start marker `autostart.py status` reads


class VaultCheckTest(unittest.TestCase):
    """A launchd-started python may be refused ~/Documents by macOS privacy (TCC): the server says so plainly."""

    def test_a_readable_vault_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(server.vault_problem({"vault_ofis": tmp}))

    def test_an_unreadable_vault_gives_a_turkish_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            locked = os.path.join(tmp, "OFIS")
            os.makedirs(locked)
            os.chmod(locked, 0)
            try:
                text = server.vault_problem({"vault_ofis": locked})
            finally:
                os.chmod(locked, 0o755)
        self.assertTrue(text.startswith("ofis: HATA Obsidian"), text)
        self.assertIn(locked, text)
        self.assertIn("Tam Disk Erişimi", text)
        self.assertIn(os.path.realpath(sys.executable), text)

    def test_a_missing_vault_is_reported_too(self):
        text = server.vault_problem({"vault_ofis": "/nonexistent/ofis-test-vault"})
        self.assertTrue(text.startswith("ofis: HATA Obsidian"), text)


class EventRecordWiringTest(unittest.TestCase):
    """The post office's log lines pass through the vault's error record (bin/olaylar.py); a refresh failure too."""

    def test_the_post_office_logs_through_the_given_stream(self):
        import olaylar
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"ceo_session": "ofis-ceo", "vault_ofis": tmp, "projects": {}}
            events = olaylar.Olaylar(tmp, local=io.StringIO())
            inner = io.StringIO()
            app = server.App(cfg, root=tmp, web_dir=tmp, durum_dir=tmp, projects_dir=tmp, log=events.stream(inner))
            app.postoffice.log("rejected 1.json: invalid type")
            app.postoffice.log("answer delivered to ofis-x")
            self.assertIn("answer delivered", inner.getvalue())
            self.assertEqual([r[3] for r in events.rows.values()], ["reddedildi"])
            self.assertIsNone(app.hub.events)

    def test_main_records_the_start_the_vault_error_and_a_crash(self):
        src = open(server.__file__, encoding="utf-8").read()
        for name in ('events.record("başlangıç"', 'events.record("obsidian", problem)', 'events.record("çöküş"',
                     "log=events.stream(sys.stderr)", "events.flush(force=True)", 'events.watch("ceo"'):
            self.assertIn(name, src)


class LogRotationTest(unittest.TestCase):
    """The launchd log (stdout/stderr redirected to one O_APPEND file) is rotated in place: copy the tail, truncate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "server.log")
        self.other = os.path.join(self.tmp.name, "keep.txt")
        with open(self.other, "w") as f:
            f.write("untouched\n")

    def stream(self, mode="a"):
        s = open(self.path, mode, encoding="utf-8")
        self.addCleanup(s.close)
        return s

    def fill(self, stream, n=40):
        for i in range(n):
            stream.write(f"satir {i:03d} " + "x" * 20 + "\n")
        stream.flush()

    def test_the_path_is_the_autostart_log(self):
        import autostart
        self.assertEqual(server.LOG_FILE, os.path.join(autostart.LOG_DIR, autostart.LOG_NAME))
        self.assertEqual((server.LOG_LIMIT, server.LOG_KEEP), (5 * 1024 * 1024, 1024 * 1024))

    def test_over_the_limit_the_tail_is_kept_and_the_file_truncated_in_place(self):
        out = self.stream()
        self.fill(out)  # 40 lines of 31 bytes
        inode = os.stat(self.path).st_ino
        r = server.LogRotator(self.path, limit=500, keep=100, stream=out)
        r.remember("ofis: başlatılıyor (pid 1)")
        r.remember("Ofis: http://127.0.0.1:8801")
        self.assertTrue(r.check())
        with open(self.path + ".1", encoding="utf-8") as f:
            kept = f.read()
        self.assertTrue(kept.startswith("satir "), kept)  # starts at a line boundary
        self.assertTrue(kept.endswith("satir 039 " + "x" * 20 + "\n"))
        self.assertLessEqual(len(kept.encode()), 100)
        self.assertEqual(os.stat(self.path).st_ino, inode)  # same file: launchd's handle keeps working
        out.write("sonraki satir\n")
        out.flush()
        with open(self.path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[:2], ["ofis: başlatılıyor (pid 1)", "Ofis: http://127.0.0.1:8801"])
        self.assertTrue(lines[2].startswith("ofis: günlük "), lines)
        self.assertEqual(lines[-1], "sonraki satir")  # appended at the new end, no hole
        self.assertLess(os.path.getsize(self.path), 200)
        import autostart  # `status` still finds the port of the latest start
        self.assertIn("Ofis: http://127.0.0.1:8801", autostart.latest_start(self.path))
        with open(self.other, encoding="utf-8") as f:
            self.assertEqual(f.read(), "untouched\n")

    def test_under_the_limit_nothing_happens(self):
        out = self.stream()
        self.fill(out, 3)
        self.assertFalse(server.LogRotator(self.path, limit=500, keep=100, stream=out).check())
        self.assertFalse(os.path.exists(self.path + ".1"))

    def test_only_when_stdout_is_that_file(self):
        out = self.stream()
        self.fill(out)
        with open(self.other, "a", encoding="utf-8") as elsewhere:
            self.assertFalse(server.LogRotator(self.path, limit=500, keep=100, stream=elsewhere).check())
        self.assertFalse(server.LogRotator(self.path, limit=500, keep=100, stream=io.StringIO()).check())
        self.assertFalse(os.path.exists(self.path + ".1"))
        self.assertGreater(os.path.getsize(self.path), 500)

    def test_a_handle_without_o_append_is_left_alone(self):
        self.fill(self.stream())
        plain = self.stream("r+")  # truncating under it would leave a hole up to its offset
        self.assertFalse(server.LogRotator(self.path, limit=500, keep=100, stream=plain).check())
        self.assertGreater(os.path.getsize(self.path), 500)

    def test_a_missing_log_is_no_error(self):
        r = server.LogRotator(os.path.join(self.tmp.name, "yok.log"), limit=1, keep=1, stream=io.StringIO())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertFalse(r.check())
        self.assertEqual(err.getvalue(), "")  # a server started by hand has no log: quiet

    def test_the_loop_stops_with_the_server(self):
        stop = threading.Event()
        calls = []
        r = server.LogRotator(self.path, stream=io.StringIO())
        r.check = lambda: calls.append(1)
        t = threading.Thread(target=r.run, args=(stop, 0.01), daemon=True)
        t.start()
        while not calls:
            stop.wait(0.01)
        stop.set()
        t.join(2)
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
