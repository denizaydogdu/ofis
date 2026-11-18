"""Tests for bin/channel.py: delivery to one named session (the CEO or a project session). Fake claude only."""
import json
import os
import re
import time
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import ceo  # noqa: E402
import sahip  # noqa: E402
import channel  # noqa: E402
import claude_cli  # noqa: E402
import fakes  # noqa: E402
import transcript  # noqa: E402

SID = "abcdef12-3456-7890-abcd-ef1234567890"
NAME = "ofis-blog-1110-183820-ab12"


class ProjectChannelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.cwd = os.path.join(base, "Dev", "blog")
        self.durum = os.path.join(base, "durum")
        self.projects = os.path.join(base, "projects")
        os.makedirs(self.cwd)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.fake.set_name(SID, NAME)
        self.t = 1000.0
        self.cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self):
        return channel.project_channel(self.cli, NAME, self.cwd, self.durum, self.projects,
                                       clock=lambda: self.t, sleep=lambda s: None, grace=20, find_attempts=3)

    def calls(self):
        return [c["args"] for c in self.fake.calls()]

    def test_files_live_under_kuyruk(self):
        ch = self.make()
        self.assertEqual(ch.queue_file, os.path.join(self.durum, "kuyruk", NAME + ".jsonl"))
        self.assertEqual(ch.id_file, os.path.join(self.durum, "kuyruk", NAME + ".json"))

    def test_absent_project_session_is_never_started(self):
        ch = self.make()
        self.assertEqual(ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1"), "queued")
        self.assertFalse(ch.drain_once())
        self.assertEqual(self.calls(), [], "a project session is never started by the channel")
        self.assertIn("not found", ch.last_error)

    def test_dormant_session_found_by_short_id_in_transcripts_is_resumed_in_its_cwd(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        ch = self.make()
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(self.calls(), [["--bg", "--resume", SID, "[Ofis · Sahibin cevabı]\nevet"]])
        self.assertEqual(os.path.realpath(self.fake.calls()[-1]["cwd"]), self.cwd)
        self.assertIsNone(ch.last_error)
        self.assertTrue(ch.was_sent("k1"))

    def test_project_resume_carries_the_sessions_own_flags(self):
        # Review finding 3: a resume without them falls back to the default model, effort and permission mode.
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        ch = self.make()
        ch.resume_args = ["--model", "haiku", "--effort", "low"]
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(self.calls(), [["--bg", "--resume", SID, "--model", "haiku", "--effort", "low",
                                         "[Ofis · Sahibin cevabı]\nevet"]])

    def test_worktree_session_transcript_is_found_under_its_own_project_folder(self):
        # Claude Code turns every non-alphanumeric character of the cwd (also the dot of .claude) into '-'.
        cwd = os.path.join(self.cwd, ".claude", "worktrees", NAME)
        os.makedirs(cwd)
        folder = os.path.join(self.projects, re.sub(r"[^A-Za-z0-9-]", "-", cwd))
        os.makedirs(folder)
        with open(os.path.join(folder, SID + ".jsonl"), "w") as f:
            f.write(json.dumps(fakes.user(date.today(), "x")) + "\n")
        ch = channel.project_channel(self.cli, NAME, cwd, self.durum, self.projects, sleep=lambda s: None,
                                     find_attempts=3)
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(self.calls()[-1][:3], ["--bg", "--resume", SID])
        self.assertEqual(os.path.realpath(self.fake.calls()[-1]["cwd"]), cwd)

    def test_running_idle_session_found_by_name_is_stopped_then_resumed(self):
        self.fake.set_agents([fakes.agent(NAME, self.cwd, SID, "idle")])
        ch = self.make()
        self.assertTrue(ch.adopt("-"))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(self.calls(), [["stop", SID[:8]], ["--bg", "--resume", SID, "[Ofis · Sahibin cevabı]\nevet"]])

    def test_busy_session_keeps_the_message_queued(self):
        self.fake.set_agents([fakes.agent(NAME, self.cwd, SID, "busy")])
        ch = self.make()
        ch.adopt("-")
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertFalse(ch.drain_once())
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(ch.queue()), 1)

    def test_a_session_at_a_permission_prompt_is_never_delivered_into(self):
        # review of phase 4: "waiting" was read as idle, the stop raised _Busy and the queue stalled silently
        self.fake.set_agents([fakes.agent(NAME, self.cwd, SID, "waiting")])
        ch = self.make()
        ch.adopt("-")
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertFalse(ch.drain_once())
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(ch.queue()), 1)
        self.assertEqual(ch.status()["state"], "waiting")
        self.assertIn("izin sorusunda bekliyor", ch.last_error)
        self.assertEqual(ch.deliver("bir mesaj daha"), "queued")
        self.assertEqual(self.calls(), [])
        self.fake.set_agents([fakes.agent(NAME, self.cwd, SID, "idle")])
        self.assertTrue(ch.drain_once())  # the prompt was answered: delivery goes on
        self.assertIsNone(ch.last_error)

    def test_same_name_in_another_folder_is_not_adopted(self):
        other = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(other)
        self.fake.set_agents([fakes.agent(NAME, other, SID, "idle")])
        self.assertFalse(self.make().adopt("-"))

    def test_ambiguous_short_id_is_not_adopted(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        fakes.write_transcript(self.projects, self.cwd, SID[:8] + "-ffff-0000-0000-000000000000",
                               [fakes.user(date.today(), "y")])
        self.assertFalse(self.make().adopt(SID[:8]))

    def test_keyed_enqueue_is_idempotent_before_and_after_delivery(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        ch = self.make()
        ch.adopt(SID[:8])
        self.assertEqual(ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1"), "queued")
        self.assertEqual(ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1"), "duplicate")
        self.assertTrue(ch.drain_once())
        # After a restart (new channel object) the delivered key is still remembered.
        again = self.make()
        self.assertTrue(again.was_sent("k1"))
        self.assertEqual(again.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1"), "duplicate")
        self.assertEqual(again.queue(), [])

    def test_the_sent_log_keeps_the_delivery_time_and_reads_old_lines(self):
        # the per-job progress line (bin/state.py) reads when a keyed notice was delivered
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        ch = self.make()
        ch.adopt(SID[:8])
        with open(ch.sent_file, "w", encoding="utf-8") as f:
            f.write("eski\n")  # a line written before times were kept
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        times = self.make().sent_times()
        self.assertEqual(times["eski"], "")
        self.assertRegex(times["k1"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.assertTrue(self.make().was_sent("k1") and self.make().was_sent("eski"))
        with self.assertRaises(ValueError):
            ch.enqueue("x", "a\tb")  # a tab would break the log's key/time split

    def test_enqueue_refuses_dash_text(self):
        with self.assertRaises(ValueError):
            self.make().enqueue("--model x", "k1")

    def test_channel_record_keeps_name_and_cwd_for_restart(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        ch = self.make()
        ch.adopt(SID[:8])
        with open(ch.id_file) as f:
            record = json.load(f)
        self.assertEqual((record["session_id"], record["name"], record["cwd"]), (SID, NAME, self.cwd))
        restored = channel.load_project_channels(self.cli, self.durum, self.projects, sleep=lambda s: None)
        self.assertEqual([c.name for c in restored], [NAME])
        self.assertEqual(restored[0].root, self.cwd)


NEW = "fedcba98-0000-4000-8000-000000000001"
NEWER = "fedcba98-0000-4000-8000-000000000002"


class ForkTest(unittest.TestCase):
    """Phase 3, item 0: Claude Code 2.1.322 continues a resumed PROJECT session in a NEW transcript (new id, same
    agent name, a copy of the earlier history first) while `claude agents` keeps the OLD id (status None)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.cwd = os.path.join(base, "Dev", "blog")
        self.durum = os.path.join(base, "durum")
        self.projects = os.path.join(base, "projects")
        os.makedirs(self.cwd)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.fake.set_name(SID, NAME)
        self.cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)
        fakes.write_transcript(self.projects, self.cwd, SID,
                               fakes.name_records(NAME, SID) + [fakes.user(date.today(), "x")])
        self.moved = []
        self.t = 1000.0
        self.closed = fakes.closed_turn(date.today(), "r-neu")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self):
        ch = channel.project_channel(self.cli, NAME, self.cwd, self.durum, self.projects, sleep=lambda s: None,
                                     find_attempts=3, clock=lambda: self.t, grace=20)
        ch.on_session = lambda sid, ids: self.moved.append((sid, list(ids)))
        return ch

    def calls(self):
        return [c["args"] for c in self.fake.calls()]

    def test_named_sessions_finds_the_transcripts_of_a_session_name(self):
        fakes.write_transcript(self.projects, self.cwd, NEW, fakes.name_records(NAME, NEW))
        fakes.write_transcript(self.projects, self.cwd, NEWER, fakes.name_records("ofis-baska-1", NEWER))
        fakes.write_transcript(self.projects, self.cwd, "abcdef00-0000-4000-8000-00000000000a",
                               [fakes.user(date.today(), "isimsiz")])
        found = transcript.named_sessions(self.projects, self.cwd, NAME)
        self.assertEqual(sorted(s for s, _ in found), sorted([SID, NEW]))
        self.assertEqual(transcript.named_sessions(self.projects, self.cwd, NAME, since=time.time() + 60), [],
                         "only files written since the given time")

    def test_a_resume_that_forks_is_followed_to_the_new_session_id(self):
        self.fake.fork_on_resume(self.projects, new_ids=[NEW, NEWER], records=self.closed)
        ch = self.make()
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(ch.session_id(), NEW)
        self.assertEqual(self.moved, [(NEW, [SID, NEW])])
        with open(ch.id_file) as f:
            self.assertEqual(json.load(f)["session_ids"], [SID, NEW])
        # the old id stays listed (status None); the next message goes to the NEW id, which forks again
        self.assertEqual([a["sessionId"] for a in self.fake.agents()], [SID])
        self.t += 30  # past the grace period
        ch.enqueue("[Ofis · Sahibin cevabı]\nikinci", "k2")
        self.assertTrue(ch.drain_once())
        self.assertEqual([c[:3] for c in self.calls() if c[:2] == ["--bg", "--resume"]],
                         [["--bg", "--resume", SID], ["--bg", "--resume", NEW]])
        self.assertEqual(ch.session_id(), NEWER)
        self.assertEqual(self.moved[-1], (NEWER, [SID, NEW, NEWER]))
        restored = channel.load_project_channels(self.cli, self.durum, self.projects)
        self.assertEqual(restored[0].session_id(), NEWER, "a restart keeps the newest id")

    def test_a_resume_without_a_fork_keeps_the_id(self):
        ch = self.make()
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(ch.session_id(), SID)
        self.assertEqual(self.moved, [])

    def test_the_stale_listing_of_the_old_id_does_not_block_the_next_delivery(self):
        self.fake.fork_on_resume(self.projects, new_ids=[NEW, NEWER], records=self.closed)
        ch = self.make()
        ch.adopt(SID[:8])
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        ch.drain_once()
        self.t += 30
        self.assertEqual(ch.status()["state"], "dormant")
        ch.enqueue("[Ofis · Sahibin cevabı]\nikinci", "k2")
        self.assertTrue(ch.drain_once())
        self.assertNotIn("stop", [c[0] for c in self.calls()], "a stale entry with status None is not stopped")

    def test_a_busy_stale_listing_keeps_the_message_queued(self):
        self.fake.fork_on_resume(self.projects, new_ids=[NEW], records=self.closed)
        ch = self.make()
        ch.adopt(SID[:8])
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        ch.drain_once()
        self.t += 30
        self.fake.set_status(SID, "busy")
        ch.enqueue("[Ofis · Sahibin cevabı]\nikinci", "k2")
        self.assertFalse(ch.drain_once())
        self.assertEqual(ch.status()["state"], "busy")

    def test_an_open_turn_in_the_new_transcript_counts_as_busy(self):
        self.fake.fork_on_resume(self.projects, new_ids=[NEW],
                                 records=self.closed + [fakes.human(date.today(), "çalışıyor")])
        ch = self.make()
        ch.adopt(SID[:8])
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        ch.drain_once()
        self.t += 30
        ch.enqueue("[Ofis · Sahibin cevabı]\nikinci", "k2")
        self.assertFalse(ch.drain_once(), "the forked session is still in its turn")

    def test_a_delivery_does_not_poll_for_a_late_fork(self):
        # phase 3 review, finding 11: the post office thread holds the channel lock; one immediate check only, a fork
        # that shows up later is found by the post office's _discover_sessions
        sleeps = []
        ch = channel.project_channel(self.cli, NAME, self.cwd, self.durum, self.projects, sleep=sleeps.append,
                                     find_attempts=3, clock=lambda: self.t, grace=20)
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertEqual(sleeps, [], "no polling while the lock is held")
        self.assertEqual(ch.session_id(), SID)

    # --- 2026-11-13: an unrecognised launch line (claude 2.1.323) ---

    def odd_channel(self):
        self.fake.flag("odd-output")
        ch = self.make()
        self.logged = []
        ch.log = self.logged.append
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once(), "exit 0 counts as delivered")
        return ch

    def test_an_unrecognised_launch_keeps_a_masked_tail_in_the_warning_and_the_log(self):
        ch = self.odd_channel()
        self.assertIn("without the expected launch line", ch.last_error)
        self.assertIn("output: stdout: Starting background service… ⏎ Session", ch.last_error)
        [line] = self.logged
        self.assertTrue(line.startswith(f"{NAME}: launch unconfirmed: "), line)
        self.assertIn("continues in the background", line)
        self.assertLessEqual(len(line), 500)

    # --- 2026-11-15: claude 2.1.325 starts a copy instead of resuming ---

    def test_a_copy_of_a_still_running_session_is_stopped_and_the_message_stays_queued(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        self.fake.flag("copy-running")
        ch = self.make()
        logged = []
        ch.log = logged.append
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertFalse(ch.drain_once())
        self.assertIn(["stop", "deadbeef"], self.calls())
        self.assertFalse(ch.was_sent("k1"))
        self.assertEqual(len(ch.queue()), 1)
        self.assertIn("copy deadbeef", logged[0])
        before = len(self.calls())
        self.t += 30  # past the grace period, inside the copy hold: no new copy every pass
        self.assertFalse(ch.drain_once())
        self.assertNotIn(["--bg", "--resume"], [c[:2] for c in self.calls()[before:]])
        self.assertEqual(ch.status()["state"], "busy")

    def test_a_copy_of_a_stopped_session_with_its_flags_counts_as_delivered(self):
        fakes.write_transcript(self.projects, self.cwd, SID, [fakes.user(date.today(), "x")])
        self.fake.flag("copy-options")
        ch = self.make()
        ch.resume_args = ["--model", "haiku"]
        self.assertTrue(ch.adopt(SID[:8]))
        ch.enqueue("[Ofis · Sahibin cevabı]\nevet", "k1")
        self.assertTrue(ch.drain_once())
        self.assertTrue(ch.was_sent("k1"))
        self.assertNotIn(["stop", "deadbeef"], self.calls())

    def test_a_confirmed_fork_clears_the_launch_warning(self):
        self.fake.fork_on_resume(self.projects, new_ids=[NEW], records=self.closed)
        ch = self.odd_channel()
        self.assertEqual(ch.session_id(), NEW)
        self.assertIsNone(ch.last_error, "the session went on under its new id: the message arrived")
        self.assertEqual(len(self.logged), 1, "the output is still logged once, so the new format can be seen")

    def test_a_fork_found_later_clears_the_launch_warning(self):
        ch = self.odd_channel()
        self.assertIn("launch line", ch.last_error)
        self.assertTrue(ch.follow(NEW))
        self.assertIsNone(ch.last_error)

    def test_following_does_not_clear_a_real_error(self):
        ch = self.make()
        ch.last_error = "session x not found"
        ch.adopt(SID[:8])
        ch.follow(NEW)
        self.assertEqual(ch.last_error, "session x not found")

    def test_a_later_confirmed_delivery_clears_the_launch_warning(self):
        ch = self.odd_channel()
        self.fake.flag("odd-output", on=False)
        self.fake.set_status(SID, "idle")
        fakes.write_transcript(self.projects, self.cwd, SID, fakes.name_records(NAME, SID)
                               + [fakes.user(date.today(), "x")] + self.closed)  # the turn ended
        self.t += 30
        ch.enqueue("[Ofis · Sahibin cevabı]\nikinci", "k2")
        self.assertTrue(ch.drain_once())
        self.assertIsNone(ch.last_error)

    def test_the_ceo_channel_never_follows_a_fork(self):
        self.assertFalse(ceo.CeoController(self.cli, self.cwd, "ofis-ceo", self.durum, self.projects).follow_forks)
        self.assertTrue(self.make().follow_forks)


class CeoKeyedEnqueueTest(unittest.TestCase):
    """The post office queues CEO notices with a key; CeoController keeps its file names."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "ajan-ofisi")
        self.durum = os.path.join(self.root, "durum")
        os.makedirs(self.root)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)
        self.ctl = ceo.CeoController(cli, self.root, "ofis-ceo", self.durum, os.path.join(base, "projects"),
                                     sleep=lambda s: None, find_attempts=3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ceo_files_are_unchanged(self):
        self.assertEqual(self.ctl.id_file, os.path.join(self.durum, "ceo.json"))
        self.assertEqual(self.ctl.queue_file, os.path.join(self.durum, "ceo-queue.jsonl"))
        self.assertEqual(self.ctl.unconfirmed_file, os.path.join(self.durum, "ceo-unconfirmed.jsonl"))
        self.assertIs(ceo.CeoUnavailable, channel.ChannelUnavailable)

    def test_keyed_notice_is_queued_once_and_started_when_absent(self):
        self.assertEqual(self.ctl.enqueue("[Ofis · sistem]\nblog işi bitti", "gelen-1"), "queued")
        self.assertEqual(self.ctl.enqueue("[Ofis · sistem]\nblog işi bitti", "gelen-1"), "duplicate")
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual([c["args"][:3] for c in self.fake.calls()], [["--bg", "--name", "ofis-ceo"]])
        self.assertTrue(self.ctl.was_sent("gelen-1"))

    def test_every_ceo_message_ends_with_the_turkish_reminder_once(self):
        # The owner's test: a resumed CEO does not re-read CLAUDE.md and answered a notice in English.
        self.ctl.enqueue("[Ofis · sistem]\nblog işi bitti", "gelen-1")
        self.ctl.drain_once()
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nselam\n" + sahip.hatirlatma("Selin")), "queued")
        self.assertEqual(self.fake.calls()[0]["args"][-1],
                         "[Ofis · sistem]\nblog işi bitti\n(Selin'e Türkçe ve sade yaz.)")
        [queued] = self.ctl.queue()
        self.assertEqual(queued["text"], "[Sahip · ofis sayfası]\nselam\n(Selin'e Türkçe ve sade yaz.)")


if __name__ == "__main__":
    unittest.main()
