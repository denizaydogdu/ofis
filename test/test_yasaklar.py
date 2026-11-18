"""Tests for bin/yasaklar.py: the privacy rules read from ofis.json `guvenlik` (plan "2. Aşama"), and the checks that
use them with a neutral (empty) and a custom configuration, and the test-only config override (OFIS_TEST +
OFIS_CONFIG). Rules of a real owner's shape are exercised by test_guard, test_launch, test_adimlar, test_hafiza_saglik,
… through test/sahip_yasaklari.py."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import sahip_yasaklari  # noqa: E402
import yasaklar  # noqa: E402
import launch  # noqa: E402
import adimlar  # noqa: E402
import transcript  # noqa: E402
import hafiza_saglik  # noqa: E402
import kontrol  # noqa: E402

GUARD = os.path.join(HERE, "..", "bin", "guard.py")
FORBIDDEN = sahip_yasaklari.YASAK_YOL
FOLDERS = sahip_yasaklari.KLASORLER
CRED = "ş" + "ifre"


class _Config(unittest.TestCase):
    """Each test writes its own ofis.json and points yasaklar.CONFIG at it; EK_ENV is removed for the test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "ofis.json")
        self._old = (yasaklar.CONFIG, os.environ.get(yasaklar.EK_ENV))
        os.environ.pop(yasaklar.EK_ENV, None)
        yasaklar.CONFIG = self.path
        yasaklar.sifirla()

    def tearDown(self):
        yasaklar.CONFIG = self._old[0]
        if self._old[1] is None:
            os.environ.pop(yasaklar.EK_ENV, None)
        else:
            os.environ[yasaklar.EK_ENV] = self._old[1]
        yasaklar.sifirla()

    def write(self, guvenlik=None, raw=None):
        cfg = {"ceo_session": "ofis-ceo", "vault_ofis": "/x/OFIS", "projects": {}}
        if guvenlik is not None:
            cfg["guvenlik"] = guvenlik
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(cfg, ensure_ascii=False))
        st = os.stat(self.path)  # a new mtime even within the same clock tick
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


class FormatTest(_Config):
    def test_missing_key_is_the_neutral_default(self):
        self.write()
        r = yasaklar.kurallar()
        self.assertEqual(r.yollar, ())
        self.assertEqual(r.klasorler, ())
        self.assertIn("password", r.kelimeler)
        self.assertFalse(launch.is_forbidden_path(os.path.expanduser(f"~/Dev/{FORBIDDEN}")))

    def test_the_owner_rules_as_plain_words(self):
        self.write(sahip_yasaklari.SAHIP)
        r = yasaklar.kurallar()
        dotted = FORBIDDEN[0].upper() + "İ" + FORBIDDEN[2:]  # a dotted capital İ folds like the plain i
        for part in (FORBIDDEN, FORBIDDEN.upper(), dotted, f"{FORBIDDEN}-old", f"{FORBIDDEN}.bak", f"{FORBIDDEN}_x",
                     f"{FORBIDDEN} kopya"):
            with self.subTest(part=part):
                self.assertTrue(r.yasak_bilesen(part))
        for part in (f"{FORBIDDEN}x", f"a{FORBIDDEN}", "ajan-ofisi"):
            with self.subTest(part=part):
                self.assertFalse(r.yasak_bilesen(part))
        self.assertEqual(r.yol_adi(), FORBIDDEN.upper())
        self.assertEqual(r.klasor_adi(), f"{FOLDERS[0]}/, {FOLDERS[1]}/ and {FOLDERS[2]}/")
        self.assertIn("İ", FOLDERS[2])  # the dotted capital İ folds like the plain letter
        self.assertTrue(r.klasor_yolu.search(yasaklar.fold(f"/vault/{FOLDERS[2]}/x.md")))
        self.assertTrue(r.klasor_yolu.search(yasaklar.fold(f"/vault/{FOLDERS[2].replace('İ', 'I').lower()}/x.md")))
        self.assertTrue(r.kelime.search(yasaklar.fold("Email " + CRED.upper() + ".md")))
        self.assertFalse(r.kelime.search("password"))  # the owner's guard reads only the Turkish stem

    def test_a_path_entry_counts_by_its_last_component(self):
        self.write({"yasak_yollar": ["~/Dev/gizli-proje/"], "ozel_klasorler": ["Kasa/Ozel"], "yasak_kelimeler": []})
        r = yasaklar.kurallar()
        self.assertEqual(r.yollar, ("gizli-proje",))
        self.assertEqual(r.klasorler, ("Ozel",))

    def test_cache_follows_the_file(self):
        self.write({"yasak_yollar": ["eski"]})
        self.assertTrue(launch.is_forbidden_path("/x/eski/y"))
        self.write({"yasak_yollar": ["yeni"]})
        self.assertFalse(launch.is_forbidden_path("/x/eski/y"))
        self.assertTrue(launch.is_forbidden_path("/x/yeni/y"))

    def test_a_broken_file_keeps_the_last_good_rules(self):
        self.write({"yasak_yollar": [FORBIDDEN]})
        self.assertTrue(launch.is_forbidden_path(f"/x/{FORBIDDEN}"))
        for raw in ('{"guvenlik": {"yasak_yollar": [', "[]", '{"guvenlik": {"yasak_yollar": "x"}}',
                    '{"guvenlik": {"yasak_yolar": []}}', '{"guvenlik": []}'):
            with self.subTest(raw=raw):
                self.write(raw=raw)
                self.assertTrue(launch.is_forbidden_path(f"/x/{FORBIDDEN}"))
        os.remove(self.path)
        self.assertTrue(launch.is_forbidden_path(f"/x/{FORBIDDEN}"))

    def test_a_broken_file_without_a_last_good_value_fails_closed(self):
        # a typo, a string for a list, null, an unknown shape or bad JSON never silently becomes the neutral default
        for raw in ("{broken", "[]", '{"guvenlik": {"yasak_yolar": []}}', '{"guvenlik": {"yasak_yollar": "x"}}',
                    '{"guvenlik": null}', '{"guvenlik": {"ozel_klasorler": null}}', ""):
            with self.subTest(raw=raw):
                yasaklar.sifirla()
                self.write(raw=raw)
                with self.assertRaises(yasaklar.Bozuk) as ctx:
                    yasaklar.kurallar()
                self.assertNotIsInstance(ctx.exception, (ValueError, OSError))  # no `except ValueError` swallows it
                with self.assertRaises(yasaklar.Bozuk):
                    launch.is_forbidden_path(f"/x/{FORBIDDEN}")

    def test_the_bad_field_is_named(self):
        self.write(raw='{"guvenlik": {"yasak_yolar": []}}')
        with self.assertRaises(yasaklar.Bozuk) as ctx:
            yasaklar.kurallar()
        self.assertIn("yasak_yolar", str(ctx.exception))

    def test_a_missing_file_is_the_default(self):
        r = yasaklar.kurallar()  # setUp's path does not exist yet: a fresh clone
        self.assertEqual(r.yollar, ())
        self.assertIn("parola", r.kelimeler)

    def test_a_long_running_process_keeps_its_rules_and_logs_once(self):
        self.write({"yasak_yollar": [FORBIDDEN]})
        self.assertTrue(launch.is_forbidden_path(f"/x/{FORBIDDEN}"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(3):  # the same error, rewritten (a new identity each time): one line
                self.write(raw='{"guvenlik": {"yasak_yolar": []}}')
                self.assertTrue(launch.is_forbidden_path(f"/x/{FORBIDDEN}"))
        self.assertEqual(err.getvalue().count("ofis.json guvenlik is malformed"), 1, err.getvalue())
        self.assertIn("yasak_yolar", err.getvalue())
        self.write({"yasak_yollar": ["yeni"]})  # good again: the new rules, and a later break is told again
        self.assertTrue(launch.is_forbidden_path("/x/yeni"))
        with contextlib.redirect_stderr(err):
            self.write(raw="{broken")
            self.assertTrue(launch.is_forbidden_path("/x/yeni"))
        self.assertEqual(err.getvalue().count("ofis.json guvenlik is malformed"), 2, err.getvalue())

    def test_ek_env_only_adds(self):
        self.write({"yasak_yollar": ["a"], "ozel_klasorler": [], "yasak_kelimeler": []})
        os.environ[yasaklar.EK_ENV] = json.dumps({"yasak_yollar": ["b"]})
        r = yasaklar.kurallar()
        self.assertEqual(set(r.yollar), {"a", "b"})
        os.environ[yasaklar.EK_ENV] = "{not json"
        self.assertEqual(yasaklar.kurallar().yollar, ("a",))

    def test_dogrula_refuses_wrong_shapes(self):
        for bad in ([], {"yasak_yollar": "x"}, {"yasak_yollar": [1]}, {"baska": []}):
            with self.subTest(bad=bad), self.assertRaises(yasaklar.Hatali):
                yasaklar.dogrula(bad)


class EmptyRulesTest(_Config):
    """With an empty `guvenlik` nothing personal is refused; the generic rules stay."""

    def setUp(self):
        super().setUp()
        self.write({"yasak_yollar": [], "ozel_klasorler": [], "yasak_kelimeler": []})

    def test_the_forbidden_project_path_is_allowed(self):
        path = os.path.expanduser(f"~/Dev/{FORBIDDEN}")
        self.assertFalse(launch.is_forbidden_path(path))
        self.assertFalse(transcript.forbidden_folder(f"/x/projects/-Users-x-Dev-{FORBIDDEN}"))
        self.assertFalse(kontrol.forbidden_command(f"git -C {path} status"))
        self.assertFalse(adimlar.forbidden(f"cat {path}/README.md"))
        self.assertFalse(adimlar.forbidden(f"ls /vault/{FOLDERS[0]}/x"))
        self.assertFalse(adimlar.forbidden(f"cat /vault/{CRED}.md"))
        self.assertFalse(hafiza_saglik._yasak(FORBIDDEN, klasor=True))
        self.assertFalse(hafiza_saglik._yasak(FOLDERS[0], klasor=True))
        self.assertTrue(hafiza_saglik._yasak("password store.md"))  # its fixed password-store words stay

    def test_custom_words_work(self):
        self.write({"yasak_yollar": ["musteri"], "ozel_klasorler": ["Saglik"], "yasak_kelimeler": ["gizli"]})
        self.assertTrue(launch.is_forbidden_path("/Users/x/Dev/Musteri-eski/a"))
        self.assertFalse(launch.is_forbidden_path(os.path.expanduser(f"~/Dev/{FORBIDDEN}")))
        self.assertTrue(transcript.forbidden_folder("/x/projects/-Users-x-Dev-musteri"))
        self.assertTrue(kontrol.forbidden_command("ls /Users/x/musteri"))
        self.assertFalse(adimlar.forbidden("cat /vault/SAĞLIK/x.md"))  # ğ is a different letter: not this rule
        self.assertTrue(adimlar.forbidden("cat /vault/Saglik/x.md"))
        self.assertTrue(adimlar.forbidden("ls Saglik"))
        self.assertTrue(adimlar.forbidden("cat /vault/Gizli notlar.md"))
        self.assertTrue(hafiza_saglik._yasak("Saglik", klasor=True))
        self.assertTrue(hafiza_saglik._yasak("musteri", klasor=True))
        self.assertTrue(hafiza_saglik._yasak("gizli plan.md"))
        self.assertTrue(launch.is_forbidden_component("Musteri"))


class GuardHookTest(unittest.TestCase):
    """The hook process reads the tests' config (OFIS_CONFIG, inherited); EK_ENV adds a custom rule to it for this run."""

    def run_guard(self, tool, tool_input, ek):
        env = dict(os.environ)
        env[yasaklar.EK_ENV] = json.dumps(ek)
        proc = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps({"tool_name": tool,
                              "tool_input": tool_input}), capture_output=True, text=True, timeout=10, env=env)
        return proc.returncode, proc.stderr

    def test_a_custom_word_and_folder_block_in_the_hook(self):
        ek = {"yasak_yollar": ["musteri"], "ozel_klasorler": ["Saglik"], "yasak_kelimeler": ["gizlinot"]}
        for tool, ti in (("Bash", {"command": "ls ~/Dev/musteri"}),
                         ("Read", {"file_path": "/Users/x/Dev/MUSTERI-eski/a.py"}),
                         ("Bash", {"command": "cat Saglik/x.md"}),
                         ("Read", {"file_path": "/v/Saglik/x.md"}),
                         ("Read", {"file_path": "/v/a/GizliNot.md"})):
            with self.subTest(tool=tool, ti=ti):
                code, err = self.run_guard(tool, ti, ek)
                self.assertEqual(code, 2, err)
        code, err = self.run_guard("Read", {"file_path": "/Users/x/Dev/ajan-ofisi/README.md"}, ek)
        self.assertEqual(code, 0, err)

    def test_a_yasaklar_module_earlier_on_sys_path_never_replaces_the_rules(self):
        # site-packages come before bin/ even under -I: a module there named yasaklar must not be the one loaded
        with tempfile.TemporaryDirectory() as shadow:
            with open(os.path.join(shadow, "yasaklar.py"), "w", encoding="utf-8") as f:
                f.write("raise SystemExit(0)\n")
            env = dict(os.environ)
            env[yasaklar.EK_ENV] = json.dumps({"yasak_yollar": ["musteri"]})
            code = (f"import sys, runpy; sys.path.insert(0, {shadow!r}); "
                    f"runpy.run_path({GUARD!r}, run_name='__main__')")
            proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=10,
                                  env=env, input=json.dumps({"tool_name": "Bash",
                                                             "tool_input": {"command": "ls ~/Dev/musteri"}}))
        self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_the_hook_messages_name_the_configured_rules(self):
        code, err = self.run_guard("Bash", {"command": "ls ~/Dev/musteri"}, {"yasak_yollar": ["musteri"]})
        self.assertEqual(code, 2)
        self.assertIn("MUSTERI is outside the office", err)


class GuardRulesTest(_Config):
    """The guard's checks in-process with an empty configuration: nothing personal is refused."""

    def test_empty_rules_allow_personal_paths(self):
        import guard
        for tool, ti in (("Bash", {"command": f"ls ~/Dev/{FORBIDDEN}"}),
                         ("Read", {"file_path": os.path.expanduser(f"~/Dev/{FORBIDDEN}/pom.xml")}),
                         ("Bash", {"command": f"ls {FOLDERS[0]}"})):
            with self.subTest(tool=tool, ti=ti):
                self.write({"yasak_yollar": [], "ozel_klasorler": [], "yasak_kelimeler": []})
                self.assertIsNone(guard.check({"tool_name": tool, "tool_input": ti, "cwd": "/tmp"}))
        # the generic rules are app logic and stay
        self.assertIsNotNone(guard.check({"tool_name": "Bash", "tool_input": {"command": "claude --bg x"},
                                          "cwd": "/tmp"}))


class LaunchLoadTest(_Config):
    """launch.load refuses an ofis.json whose `guvenlik` has the wrong shape: ofis.py and the server do not start."""

    def test_a_malformed_guvenlik_is_refused_naming_the_field(self):
        for guvenlik, field in (({"yasak_yolar": []}, "yasak_yolar"), ({"yasak_yollar": "x"}, "yasak_yollar"),
                                (None, "guvenlik"), ({"ozel_klasorler": [3]}, "ozel_klasorler"), ([], "guvenlik")):
            with self.subTest(guvenlik=guvenlik):
                cfg = {"ceo_session": "ofis-ceo", "vault_ofis": "/x/OFIS", "projects": {}, "guvenlik": guvenlik}
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f)
                with self.assertRaises(launch.Refused) as ctx:
                    launch.load(self.path)
                self.assertIn(field, str(ctx.exception))
                self.assertIn("hatalı", str(ctx.exception))

    def test_a_good_or_missing_guvenlik_loads(self):
        self.write({"yasak_yollar": ["a"]})
        self.assertEqual(launch.load(self.path)["guvenlik"], {"yasak_yollar": ["a"]})
        self.write()
        self.assertNotIn("guvenlik", launch.load(self.path))


class GuardFailClosedTest(unittest.TestCase):
    """The hook in a copy of bin/ next to an ofis.json of the test's own: a broken file or module blocks (exit 2)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.mkdir(os.path.join(self.tmp, "bin"))
        self.guard = os.path.join(self.tmp, "bin", "guard.py")
        shutil.copy(GUARD, self.guard)
        self.module = os.path.join(self.tmp, "bin", "yasaklar.py")
        shutil.copy(os.path.join(HERE, "..", "bin", "yasaklar.py"), self.module)
        self.config = os.path.join(self.tmp, "ofis.json")

    def write(self, raw):
        with open(self.config, "w", encoding="utf-8") as f:
            f.write(raw)

    def run_guard(self, tool="Read", tool_input=None):
        # no override: the copied hook reads the ofis.json next to its bin/
        drop = (yasaklar.EK_ENV, yasaklar.TEST_CONFIG_ENV, yasaklar.TEST_ENV)
        env = {k: v for k, v in os.environ.items() if k not in drop}
        tool_input = tool_input or {"file_path": "/Users/x/Dev/proje/README.md"}
        proc = subprocess.run([sys.executable, "-I", self.guard], input=json.dumps({"tool_name": tool,
                              "tool_input": tool_input, "cwd": self.tmp}), capture_output=True, text=True,
                              timeout=10, env=env)
        return proc.returncode, proc.stderr

    def test_a_good_file_lets_a_harmless_read_through(self):
        self.write(json.dumps({"guvenlik": {"yasak_yollar": ["musteri"]}}))
        self.assertEqual(self.run_guard()[0], 0)
        self.assertEqual(self.run_guard(tool_input={"file_path": "/Users/x/Dev/musteri/a"})[0], 2)

    def test_a_malformed_guvenlik_blocks(self):
        for raw in ('{"guvenlik": {"yasak_yolar": []}}', '{"guvenlik": {"yasak_yollar": "x"}}', '{"guvenlik": null}'):
            with self.subTest(raw=raw):
                self.write(raw)
                code, err = self.run_guard()
                self.assertEqual(code, 2, err)
                self.assertIn("ofis.json guvenlik is malformed", err)
        code, err = self.run_guard("Bash", {"command": "ls"})
        self.assertEqual(code, 2, err)

    def test_invalid_json_blocks(self):
        for raw in ('{"guvenlik": {"yasak_yollar": [', "", "[]"):
            with self.subTest(raw=raw):
                self.write(raw)
                code, err = self.run_guard()
                self.assertEqual(code, 2, err)
                self.assertIn("ofis.json guvenlik is malformed", err)

    def test_a_missing_file_gives_the_defaults(self):
        self.assertEqual(self.run_guard()[0], 0)
        code, err = self.run_guard(tool_input={"file_path": "/Users/x/notes/" + CRED + ".md"})
        self.assertEqual(code, 2, err)

    def test_a_missing_module_blocks(self):
        os.remove(self.module)
        code, err = self.run_guard()
        self.assertEqual(code, 2, err)
        self.assertIn("guard: cannot load bin/yasaklar.py; blocking to be safe.", err)

    def test_a_module_with_a_syntax_error_blocks(self):
        with open(self.module, "w", encoding="utf-8") as f:
            f.write("def broken(:\n")
        code, err = self.run_guard()
        self.assertEqual(code, 2, err)
        self.assertIn("guard: cannot load bin/yasaklar.py; blocking to be safe.", err)

    def test_a_module_that_exits_zero_blocks(self):
        with open(self.module, "w", encoding="utf-8") as f:
            f.write("raise SystemExit(0)\n")
        code, err = self.run_guard()
        self.assertEqual(code, 2, err)


class TestOverrideTest(unittest.TestCase):
    """The test-only config override: OFIS_TEST=1 and OFIS_CONFIG naming a file inside the system temp directory.
    Anything less leaves every reader on this repository's ofis.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=tempfile.gettempdir())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = {k: os.environ.get(k) for k in (yasaklar.TEST_CONFIG_ENV, yasaklar.TEST_ENV)}

        def restore():
            for k, v in self.saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            yasaklar.sifirla()
        self.addCleanup(restore)
        self.path = self.config(os.path.join(self.tmp, "ofis.json"), {"yasak_yollar": ["musteri"]}, "Ayşe")

    def config(self, path, guvenlik, name):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ceo_session": "ofis-ceo", "vault_ofis": "/x/Kasa/OFIS", "projects": {}, "sahip_adi": name,
                       "guvenlik": guvenlik}, f, ensure_ascii=False)
        return os.path.realpath(path)

    def use(self, path, test="1"):
        os.environ[yasaklar.TEST_CONFIG_ENV] = path
        if test is None:
            os.environ.pop(yasaklar.TEST_ENV, None)
        else:
            os.environ[yasaklar.TEST_ENV] = test
        yasaklar.sifirla()

    def test_the_fixture_runs_every_test_on_its_neutral_file(self):
        self.assertEqual(os.environ.get(yasaklar.TEST_ENV), "1")
        self.assertNotEqual(yasaklar.ofis_json(), yasaklar.REPO_CONFIG)
        self.assertEqual(yasaklar.kurallar().ayar["yasak_yollar"], (FORBIDDEN,))
        self.assertEqual(launch.config_path(), yasaklar.ofis_json())

    def test_a_file_in_the_temp_directory_is_used_by_every_reader(self):
        import sahip
        self.use(self.path)
        self.assertEqual(yasaklar.ofis_json(), self.path)
        self.assertTrue(launch.is_forbidden_path("/Users/x/Dev/musteri/a"))
        self.assertFalse(launch.is_forbidden_path(f"/Users/x/Dev/{FORBIDDEN}/a"))
        self.assertEqual(sahip.ad(), "Ayşe")
        self.assertEqual(launch.load()["sahip_adi"], "Ayşe")

    def test_it_needs_ofis_test(self):
        for value in (None, "", "0", "true", "yes"):
            with self.subTest(value=value):
                self.use(self.path, test=value)
                self.assertEqual(yasaklar.ofis_json(), yasaklar.REPO_CONFIG)

    def test_a_file_outside_the_temp_directory_is_ignored(self):
        outside = os.path.join(HERE, "..", "ofis.example.json")
        for path in (outside, os.path.join(self.tmp, "..", "..", "..", "..", "..", "..", "etc", "hosts"),
                     "relative.json"):
            with self.subTest(path=path):
                self.use(path)
                self.assertEqual(yasaklar.ofis_json(), yasaklar.REPO_CONFIG)

    def test_a_link_in_the_temp_directory_to_a_file_outside_is_ignored(self):
        link = os.path.join(self.tmp, "link.json")
        os.symlink(os.path.abspath(os.path.join(HERE, "..", "ofis.example.json")), link)
        self.use(link)
        self.assertEqual(yasaklar.ofis_json(), yasaklar.REPO_CONFIG)

    def test_the_hook_inherits_it_and_a_command_cannot_switch_it(self):
        # the hook is a child process: it reads the override of the environment it was started with. Variables
        # written into a Bash command (`OFIS_TEST=1 OFIS_CONFIG=… cmd`) are text of that command, never the hook's.
        self.use(self.path)
        empty = self.config(os.path.join(self.tmp, "bos.json"), {"yasak_yollar": []}, "Ali")
        for command in ("ls ~/Dev/musteri",
                        f"OFIS_TEST=1 OFIS_CONFIG={empty} ls ~/Dev/musteri",
                        f"env OFIS_TEST=1 OFIS_CONFIG={empty} ls ~/Dev/musteri"):
            with self.subTest(command=command):
                proc = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(
                    {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.tmp}),
                    capture_output=True, text=True, timeout=10, env=dict(os.environ))
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn("MUSTERI is outside the office", proc.stderr)

    def test_the_hook_reads_the_vault_root_from_it(self):
        import guard
        self.use(self.config(os.path.join(self.tmp, "kasa.json"), {"ozel_klasorler": ["Ozel"]}, "Ali"))
        self.assertIn(guard.key("/x/Kasa"), guard.vault_roots())
        self.assertIn(guard.key("/x/Kasa/Ozel"), guard.protected_keys())


class SettingsSplitTest(unittest.TestCase):
    """The tracked .claude/settings.json keeps every generic deny (the MCP tools the guard hook never sees) and no
    personal absolute path; the git-ignored local file holds only the owner's absolute paths."""
    ROOT = os.path.join(HERE, "..")
    MCP = ("mcp__serena", "mcp__plugin_serena_serena", "mcp__filesystem__write_file", "mcp__filesystem__edit_file",
           "mcp__filesystem__move_file", "mcp__filesystem__create_directory", "mcp__github__push_files",
           "mcp__github__create_or_update_file", "mcp__github__merge_pull_request", "mcp__postgres")

    def deny(self, name):
        with open(os.path.join(self.ROOT, ".claude", name), encoding="utf-8") as f:
            return json.load(f).get("permissions", {}).get("deny", [])

    def test_generic_mcp_denies_are_tracked(self):
        tracked = self.deny("settings.json")
        for rule in self.MCP:
            with self.subTest(rule=rule):
                self.assertIn(rule, tracked)
        self.assertFalse([r for r in tracked if "/Users/" in r])

    def test_the_local_file_holds_no_mcp_rule(self):
        if not os.path.exists(os.path.join(self.ROOT, ".claude", "settings.local.json")):
            self.skipTest("no local settings on this machine")
        self.assertFalse([r for r in self.deny("settings.local.json") if r.startswith("mcp__")])


if __name__ == "__main__":
    unittest.main()
