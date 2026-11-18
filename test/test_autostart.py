"""Tests for the login autostart (phase 6, bin/autostart.py): the LaunchAgent plist, install/uninstall/status with a
fake launchctl and temp folders. The real ~/Library/LaunchAgents and the real launchctl are never touched."""
import io
import json
import os
import plistlib
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401  (isolates the job lock)
import autostart  # noqa: E402

FAKE_LAUNCHCTL = r'''#!{python} -I
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
loaded = os.path.join(d, "loaded")
if args[0] == "print":
    if not os.path.exists(loaded):
        print("Bad request.\nCould not find service in domain for user gui: 501", file=sys.stderr)
        sys.exit(113)
    print(open(os.path.join(d, "print.txt")).read() if os.path.exists(os.path.join(d, "print.txt")) else "state = running")
    sys.exit(0)
if args[0] == "bootstrap":
    if os.path.exists(os.path.join(d, "fail-bootstrap")):
        print("Bootstrap failed: 5: Input/output error", file=sys.stderr)
        sys.exit(5)
    open(loaded, "w").close()
    sys.exit(0)
if args[0] == "bootout":
    if not os.path.exists(loaded):
        print("Boot-out failed: 3: No such process", file=sys.stderr)
        sys.exit(3)
    os.remove(loaded)
    sys.exit(0)
sys.exit(64)
'''


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.agents = os.path.join(base, "LaunchAgents")
        self.logs = os.path.join(base, "Logs", "ofis")
        self.fake_dir = os.path.join(base, "fake")
        os.makedirs(self.fake_dir)
        self.launchctl = os.path.join(self.fake_dir, "launchctl")
        with open(self.launchctl, "w") as f:
            f.write(FAKE_LAUNCHCTL.replace("{python}", sys.executable))
        os.chmod(self.launchctl, os.stat(self.launchctl).st_mode | stat.S_IEXEC)
        self.tools = {"claude": "/Users/x/.local/bin/claude", "codex": "/Users/x/.nvm/versions/node/v18/bin/codex"}
        self.plist = os.path.join(self.agents, f"{autostart.LABEL}.plist")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = autostart.main(["autostart.py", *argv], agents_dir=self.agents, log_dir=self.logs,
                              launchctl=self.launchctl, uid=501, which=self.tools.get, current_path="/usr/bin:/bin",
                              out=out, err=err, sleep=lambda s: None)
        return code, out.getvalue(), err.getvalue()

    def calls(self):
        path = os.path.join(self.fake_dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def read_plist(self):
        with open(self.plist, "rb") as f:
            return plistlib.load(f)

    def test_install_writes_the_plist_and_bootstraps_it(self):
        code, out, err = self.run_main("install")
        self.assertEqual(code, 0, err)
        p = self.read_plist()
        self.assertEqual(p["Label"], autostart.LABEL)
        self.assertEqual(p["ProgramArguments"], [sys.executable, os.path.join(autostart.ROOT, "bin", "server.py")])
        self.assertTrue(all(os.path.isabs(a) for a in p["ProgramArguments"]))
        self.assertEqual(p["WorkingDirectory"], autostart.ROOT)
        self.assertIs(p["RunAtLoad"], True)
        self.assertEqual(p["KeepAlive"], {"SuccessfulExit": False})
        self.assertGreaterEqual(p["ThrottleInterval"], 10)
        log = os.path.join(self.logs, "server.log")
        self.assertEqual((p["StandardOutPath"], p["StandardErrorPath"]), (log, log))
        self.assertTrue(os.path.isdir(self.logs))
        env = p["EnvironmentVariables"]
        path = env["PATH"].split(":")
        self.assertEqual(path[:2], ["/Users/x/.local/bin", "/Users/x/.nvm/versions/node/v18/bin"])
        self.assertIn(os.path.dirname(sys.executable), path)
        self.assertIn("/usr/bin", path)
        self.assertEqual(len(path), len(set(path)))
        self.assertEqual(env["HOME"], os.path.expanduser("~"))
        self.assertEqual(self.calls()[-1], ["bootstrap", "gui/501", self.plist])
        self.assertIn("kuruldu", out)

    def test_dry_run_writes_and_runs_nothing(self):
        code, out, err = self.run_main("install", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.plist))
        self.assertEqual(self.calls(), [])
        self.assertIn(autostart.LABEL, out)
        self.assertIn("bootstrap", out)

    def test_install_refuses_without_claude(self):
        del self.tools["claude"]
        code, out, err = self.run_main("install")
        self.assertEqual(code, 1)
        self.assertIn("claude bulunamadı", err)
        self.assertFalse(os.path.exists(self.plist))
        self.assertEqual(self.calls(), [])

    def test_codex_is_optional(self):
        del self.tools["codex"]
        code, out, err = self.run_main("install")
        self.assertEqual(code, 0, err)
        self.assertIn("codex", out)  # a warning line
        self.assertEqual(self.read_plist()["EnvironmentVariables"]["PATH"].split(":")[0], "/Users/x/.local/bin")

    def test_reinstall_replaces_its_own_plist(self):
        self.assertEqual(self.run_main("install")[0], 0)
        self.tools["claude"] = "/opt/new/claude"
        code, out, err = self.run_main("install")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_plist()["EnvironmentVariables"]["PATH"].split(":")[0], "/opt/new")
        verbs = [c[0] for c in self.calls() if c[0] != "print"]
        self.assertEqual(verbs, ["bootstrap", "bootout", "bootstrap"])

    def test_install_refuses_a_plist_it_did_not_write(self):
        os.makedirs(self.agents)
        with open(self.plist, "wb") as f:
            plistlib.dump({"Label": autostart.LABEL, "ProgramArguments": ["/bin/true"]}, f)
        code, out, err = self.run_main("install")
        self.assertEqual(code, 1)
        self.assertIn("başka", err)
        self.assertEqual(self.read_plist()["ProgramArguments"], ["/bin/true"])
        self.assertEqual(self.run_main("uninstall")[0], 1)
        self.assertTrue(os.path.exists(self.plist))

    def test_a_failed_bootstrap_is_reported(self):
        open(os.path.join(self.fake_dir, "fail-bootstrap"), "w").close()
        code, out, err = self.run_main("install")
        self.assertEqual(code, 1)
        self.assertIn("Input/output error", err)

    def test_uninstall_boots_out_and_removes_only_its_plist(self):
        self.run_main("install")
        other = os.path.join(self.agents, "com.example.other.plist")
        with open(other, "wb") as f:
            plistlib.dump({"Label": "com.example.other"}, f)
        code, out, err = self.run_main("uninstall")
        self.assertEqual(code, 0, err)
        self.assertIn(["bootout", f"gui/501/{autostart.LABEL}"], self.calls())
        self.assertFalse(os.path.exists(self.plist))
        self.assertTrue(os.path.exists(other))
        self.assertTrue(os.path.isdir(self.logs))  # the log stays
        code, out, err = self.run_main("uninstall")
        self.assertEqual(code, 0, err)
        self.assertIn("kurulu değil", out)

    def test_status(self):
        code, out, _ = self.run_main("status")
        self.assertEqual(code, 0)
        self.assertIn("kurulu değil", out)
        self.run_main("install")
        with open(os.path.join(self.fake_dir, "print.txt"), "w") as f:
            f.write("gui/501/local.ofis.server = {\n\tstate = running\n\tpid = 4242\n\tlast exit code = 0\n}\n")
        with open(os.path.join(self.logs, "server.log"), "w", encoding="utf-8") as f:
            f.write("ofis: başlatılıyor (pid 1)\nOfis: http://127.0.0.1:8801\n"
                    f"{autostart.VAULT_ERROR} (/x): Operation not permitted. eski\n"
                    "ofis: başlatılıyor (pid 4242)\nOfis: http://127.0.0.1:8800\n")
        code, out, _ = self.run_main("status")
        self.assertIn("4242", out)
        self.assertIn("8800", out)
        self.assertNotIn("8801", out)
        self.assertNotIn("Operation not permitted", out)  # an older start's error
        with open(os.path.join(self.logs, "server.log"), "a", encoding="utf-8") as f:
            f.write("ofis: başlatılıyor (pid 5000)\n"
                    f"{autostart.VAULT_ERROR} (/vault): Operation not permitted. Tam Disk Erişimi …\n")
        code, out, _ = self.run_main("status")
        self.assertIn("Operation not permitted", out)
        self.assertIn("Tam Disk Erişimi", out)


if __name__ == "__main__":
    unittest.main()
