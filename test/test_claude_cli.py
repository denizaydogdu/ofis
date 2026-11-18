"""Tests for bin/claude_cli.py error reporting. A fake claude script stands in for the real CLI."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config: sets OFIS_TEST / OFIS_CONFIG)
import claude_cli  # noqa: E402


class ClaudeCliErrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = os.path.join(self.tmp.name, "claude")

    def tearDown(self):
        self.tmp.cleanup()

    def fake_script(self, body):
        with open(self.fake, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        return claude_cli.ClaudeCLI(claude_bin=self.fake)

    def test_every_office_session_is_marked_for_the_global_hooks(self):
        # The owner's global end-of-turn Codex hook skips sessions that carry OFIS_OTURUMU=1 (2026-11-12)
        cli = self.fake_script('echo "flag=$OFIS_OTURUMU" >&2\nexit 1\n')
        with self.assertRaises(claude_cli.ClaudeError) as ctx:
            cli.start_bg("ofis-ceo", "merhaba", self.tmp.name)
        self.assertIn("flag=1", str(ctx.exception))

    def test_the_test_config_override_never_reaches_a_session(self):
        # OFIS_TEST / OFIS_CONFIG (bin/yasaklar.py) stay in the test process: a started claude never inherits them
        self.assertEqual(os.environ.get("OFIS_TEST"), "1")  # set by the tests' fixture
        cli = self.fake_script('echo "test=[$OFIS_TEST] config=[$OFIS_CONFIG]" >&2\nexit 1\n')
        with self.assertRaises(claude_cli.ClaudeError) as ctx:
            cli.start_bg("ofis-ceo", "merhaba", self.tmp.name)
        self.assertIn("test=[] config=[]", str(ctx.exception))

    def test_reviewers_and_kontrol_commands_never_inherit_it(self):
        import denetci
        import kontrol
        script = 'echo "test=[$OFIS_TEST] config=[$OFIS_CONFIG]"'
        for env in (None, dict(os.environ, X="1")):
            with self.subTest(env=env is not None):
                result = denetci.run_capture(["/bin/sh", "-c", script], self.tmp.name, 10, env=env)
                self.assertIn("test=[] config=[]", str(result))
                out = kontrol.run_argv(["/bin/sh", "-c", script], self.tmp.name, 10, env=env)
                self.assertIn("test=[] config=[]", str(out))

    def test_failed_start_reports_stderr_and_stdout_tail(self):
        cli = self.fake_script("echo 'Starting background service…'\necho 'Error: login required' >&2\nexit 1\n")
        with self.assertRaises(claude_cli.ClaudeError) as ctx:
            cli.start_bg("ofis-ceo", "[Sahip · ofis sayfası]\nmerhaba", self.tmp.name)
        message = str(ctx.exception)
        self.assertIn("exit 1", message)
        self.assertIn("Error: login required", message)
        self.assertIn("Starting background service", message)

    def test_a_credential_in_the_failure_output_is_masked(self):
        cli = self.fake_script("echo 'Error: bad key sk-ant-0123456789abcdefXYZ' >&2\nexit 1\n")
        with self.assertRaises(claude_cli.ClaudeError) as ctx:
            cli.start_bg("ofis-ceo", "merhaba", self.tmp.name)
        self.assertIn("exit 1", str(ctx.exception))
        self.assertNotIn("0123456789abcdefXYZ", str(ctx.exception))

    def test_reported_output_is_bounded(self):
        cli = self.fake_script("i=0; while [ $i -lt 400 ]; do echo 'xxxxxxxxxxxxxxxxxxxx' >&2; i=$((i+1)); done; exit 1\n")
        with self.assertRaises(claude_cli.ClaudeError) as ctx:
            cli.start_bg("ofis-ceo", "merhaba", self.tmp.name)
        self.assertLess(len(str(ctx.exception)), 700)

    def test_failed_stop_reports_output(self):
        cli = self.fake_script("echo 'no such session' >&2\nexit 2\n")
        with self.assertRaises(claude_cli.ClaudeError) as ctx:
            cli.stop("abc12345")
        self.assertIn("no such session", str(ctx.exception))

    def test_exit_zero_with_other_wording_is_a_launch_without_details(self):
        # A CLI wording change must not turn a delivered message into a failure (it would be sent again).
        cli = self.fake_script("echo 'Session abc12345 continues in the background'\nexit 0\n")
        self.assertEqual(cli.resume_bg("abcdef12-3456", "merhaba", self.tmp.name), (None, None))
        self.assertEqual(cli.start_bg("ofis-ceo", "merhaba", self.tmp.name), (None, None))

    def test_resume_passes_extra_flags_between_the_session_id_and_the_text(self):
        record = os.path.join(self.tmp.name, "argv")
        cli = self.fake_script(f"for a in \"$@\"; do printf '%s\\0' \"$a\" >> '{record}'; done\n"
                               "echo 'backgrounded · abcdef12 · ofis-x'\n")
        cli.resume_bg("abcdef12-3456", "[Ofis]\nmetin", self.tmp.name,
                      extra=["--model", "haiku", "--append-system-prompt", "kurallar"])
        with open(record) as f:
            argv = f.read().split("\0")[:-1]
        self.assertEqual(argv, ["--bg", "--resume", "abcdef12-3456", "--model", "haiku", "--append-system-prompt",
                                "kurallar", "[Ofis]\nmetin"])

    def test_extra_flags_must_be_options_with_values(self):
        cli = self.fake_script("exit 0\n")
        for extra in (["haiku"], ["--model"], "--model haiku", [5]):
            with self.subTest(extra=extra):
                with self.assertRaises(claude_cli.ClaudeError):
                    cli.resume_bg("abcdef12-3456", "metin", self.tmp.name, extra=extra)

    def test_launch_timeout_is_reported_as_ambiguous(self):
        cli = self.fake_script("exec sleep 5\n")
        cli.timeout = 1
        with self.assertRaises(claude_cli.ClaudeTimeout):
            cli.resume_bg("abcdef12-3456", "merhaba", self.tmp.name)
        self.assertTrue(issubclass(claude_cli.ClaudeTimeout, claude_cli.ClaudeError))


class LaunchLineTest(unittest.TestCase):
    """The launch line of `claude --bg` (2.1.322: "backgrounded · <short id> · <name>") in the slightly wider forms a
    newer CLI may print; a random line never counts as one."""

    def test_accepted_forms(self):
        cases = {
            "the 2.1.322 form": "backgrounded · abcdef12 · ofis-x",
            "ansi colours": "\x1b[32mbackgrounded\x1b[0m · \x1b[1mabcdef12\x1b[0m · \x1b[2mofis-x\x1b[0m",
            "resumed": "resumed · abcdef12 · ofis-x",
            "started": "started · abcdef12 · ofis-x",
            "capitalised with 'session'": "Resumed session · abcdef12 · ofis-x",
            "pipe": "backgrounded | abcdef12 | ofis-x",
            "dash": "resumed - abcdef12 - ofis-x",
            "colon": "started: abcdef12 : ofis-x",
            "mixed separators and a check mark": "✓ resumed: abcdef12 · ofis-x",
            "surrounding spaces": "   backgrounded  ·  abcdef12  ·  ofis-x   ",
        }
        for label, line in cases.items():
            with self.subTest(label):
                out = "Starting background service…\n" + line + "\nsee `claude agents`\n"
                self.assertEqual(claude_cli.parse_launch(out), ("abcdef12", "ofis-x"))

    def test_lines_that_are_not_a_launch_line(self):
        cases = {
            "other wording": "Session abcdef12 continues in the background",
            "no separator": "backgrounded abcdef12 ofis-x",
            "unknown verb": "stopped · abcdef12 · ofis-x",
            "verb not first": "the job resumed · abcdef12 · ofis-x",
            "id too short": "resumed · ab1 · ofis-x",
            "id not hex": "resumed · zzzzzzzz · ofis-x",
            "id with punctuation": "backgrounded · ab;c:12 · ofis-x",
            "trailing words": "resumed · abcdef12 · ofis-x and more",
            "missing name": "resumed · abcdef12 ·",
            "name with odd characters": "resumed · abcdef12 · ofis/x",
            "prose with a colon": "started: please wait - loading",
            "empty": "",
        }
        for label, line in cases.items():
            with self.subTest(label):
                self.assertEqual(claude_cli.parse_launch(line + "\n"), (None, None))

    def test_launch_py_uses_the_same_parser(self):
        import launch
        self.assertIs(launch.parse_launch, claude_cli.parse_launch)


class LaunchTailTest(unittest.TestCase):
    """A launch whose line is not recognised still counts as delivered; its output is kept, short and masked, so the
    new format can be seen next time (2.1.323, 2026-11-13: the output was lost)."""

    setUp = ClaudeCliErrorTest.setUp
    tearDown = ClaudeCliErrorTest.tearDown
    fake_script = ClaudeCliErrorTest.fake_script

    def test_unrecognised_output_comes_back_as_a_masked_tail(self):
        cli = self.fake_script("printf '\\033[1mResumed\\033[0m in the background (id 1234)\\n'\n"
                               "echo 'auth token=abc123secret Bearer xyz.789 sk-ant-0123456789abcdef' >&2\n"
                               "echo 'log in /Users/deniz/.claude/x' >&2\nexit 0\n")
        result = cli.resume_bg("abcdef12-3456", "merhaba", self.tmp.name)
        self.assertEqual(result, (None, None))
        tail = result.tail
        self.assertIn("Resumed in the background (id 1234)", tail)
        self.assertNotIn("\x1b", tail)
        self.assertTrue(tail.startswith("(ANSI codes removed) "), "says that the output was coloured")
        for secret in ("abc123secret", "xyz.789", "0123456789abcdef", "deniz"):
            self.assertNotIn(secret, tail)
        self.assertIn("stderr:", tail)

    def test_escape_codes_are_stripped_before_masking(self):
        # an escape code inside a key word must not defeat the mask (Codex, 2026-11-13): strip, then mask, then cut
        cli = self.fake_script("printf 'to\\033[0mken=secret1 pass\\033[1mword: hunter2 \\001x\\n'\nexit 0\n")
        tail = cli.resume_bg("abcdef12-3456", "merhaba", self.tmp.name).tail
        for leak in ("secret1", "hunter2", "\x1b", "\x01"):
            self.assertNotIn(leak, tail)
        self.assertIn("token=***", tail)

    def test_the_tail_is_short(self):
        cli = self.fake_script("i=0; while [ $i -lt 100 ]; do echo 'line of claude output' ; i=$((i+1)); done\n"
                               "echo 'the very end'\nexit 0\n")
        tail = cli.start_bg("ofis-ceo", "merhaba", self.tmp.name).tail
        self.assertLessEqual(len(tail), claude_cli.TAIL_LIMIT)
        self.assertLessEqual(claude_cli.TAIL_LIMIT, 320)
        self.assertTrue(tail.endswith("the very end"), tail)

    def test_no_output_says_so(self):
        cli = self.fake_script("exit 0\n")
        self.assertEqual(cli.resume_bg("abcdef12-3456", "merhaba", self.tmp.name).tail, "(no output)")

    def test_a_recognised_launch_has_no_tail(self):
        cli = self.fake_script("echo 'resumed · abcdef12 · ofis-x'\n")
        result = cli.resume_bg("abcdef12-3456", "merhaba", self.tmp.name)
        self.assertEqual((result, result.tail), (("abcdef12", "ofis-x"), ""))


if __name__ == "__main__":
    unittest.main()
