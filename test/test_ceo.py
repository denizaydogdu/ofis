"""Tests for bin/ceo.py (CEO delivery: start, stop+resume, queue, drain). Uses a fake claude only."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import ceo  # noqa: E402
import claude_cli  # noqa: E402
import fakes  # noqa: E402

R = ceo.with_reminder  # every CEO message ends with the Turkish reminder line

SID = "abcdef12-3456-7890-abcd-ef1234567890"
NEW_SID = "c0ffee00-1111-2222-3333-444455556666"


class CeoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "ajan-ofisi")
        self.durum = os.path.join(self.root, "durum")
        self.projects = os.path.join(base, "projects")
        os.makedirs(self.root)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.t = 1000.0
        self.ctl = self.make()

    def make(self):
        cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)
        return ceo.CeoController(cli, self.root, "ofis-ceo", self.durum, self.projects,
                                 clock=lambda: self.t, sleep=lambda s: None, grace=20, find_attempts=3)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, sid=SID):
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo.json"), "w") as f:
            json.dump({"session_id": sid}, f)

    def mutating_calls(self):
        return [c["args"] for c in self.fake.calls()]

    # --- start / resume ---

    def test_start_when_absent_records_full_id(self):
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nmerhaba"), "delivered")
        calls = self.fake.calls()
        self.assertEqual(calls[0]["args"], ["--bg", "--name", "ofis-ceo", "--append-system-prompt",
                                            ceo.ceo_system_prompt("Selin"), R("[Sahip · ofis sayfası]\nmerhaba")])
        self.assertIn("Türkçe", ceo.ceo_system_prompt("Selin"))
        self.assertIn("Sen Selin'in Ofis CEO'susun", ceo.ceo_system_prompt("Selin"))  # the owner's name (sahip_adi)
        self.assertEqual(os.path.realpath(calls[0]["cwd"]), self.root)
        self.assertEqual(self.ctl.session_id(), NEW_SID)

    def test_start_keeps_short_id_until_session_is_listed(self):
        self.fake.flag("no-agent-on-start")
        self.ctl.deliver("[Sahip · ofis sayfası]\nmerhaba")
        self.assertIsNone(self.ctl.session_id())
        with open(os.path.join(self.durum, "ceo.json")) as f:
            self.assertEqual(json.load(f)["short_id"], NEW_SID[:8])
        # The session appears later; status() upgrades the short id to the full id (name + cwd + prefix match).
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, NEW_SID, "idle")])
        self.t += 100
        self.assertEqual(self.ctl.status()["session_id"], NEW_SID)

    def test_idle_session_is_stopped_then_resumed(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nselam"), "delivered")
        self.assertEqual(self.mutating_calls(), [
            ["stop", SID[:8]],
            ["--bg", "--resume", SID, R("[Sahip · ofis sayfası]\nselam")],
        ])
        self.assertEqual(os.path.realpath(self.fake.calls()[-1]["cwd"]), self.root)

    def test_dormant_session_with_transcript_is_resumed_without_stop(self):
        self.record()
        fakes.write_transcript(self.projects, self.root, SID, [fakes.user(date.today(), "x")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nselam")
        self.assertEqual(self.mutating_calls(), [["--bg", "--resume", SID, R("[Sahip · ofis sayfası]\nselam")]])

    def test_a_finished_job_record_without_a_process_is_resumed(self):
        # Live 2026-11-11: after the CEO ended a turn with a question, `claude agents` kept a row without pid/status
        # ("state": "blocked"); the server read it as idle, refused to stop it as not idle and never delivered.
        self.record()
        fakes.write_transcript(self.projects, self.root, SID, [fakes.user(date.today(), "x")])
        self.fake.set_agents([{"id": SID[:8], "cwd": self.root, "kind": "background", "startedAt": 1,
                               "sessionId": SID, "name": "ofis-ceo", "state": "blocked"}])
        self.ctl.deliver("[Sahip · ofis sayfası]\nselam")
        self.assertEqual(self.mutating_calls(), [["--bg", "--resume", SID, R("[Sahip · ofis sayfası]\nselam")]])

    def test_recorded_session_without_transcript_starts_new(self):
        self.record()
        self.ctl.deliver("[Sahip · ofis sayfası]\nselam")
        self.assertEqual(self.mutating_calls()[0][:3], ["--bg", "--name", "ofis-ceo"])
        self.assertEqual(self.ctl.session_id(), NEW_SID)

    def test_other_sessions_with_same_name_elsewhere_are_not_adopted(self):
        other = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(other)
        self.fake.set_agents([fakes.agent("ofis-ceo", other, SID, "idle")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nselam")
        self.assertEqual(self.mutating_calls()[0][:3], ["--bg", "--name", "ofis-ceo"])
        self.assertNotIn(["stop", SID[:8]], self.mutating_calls())

    # --- busy / queue / drain ---

    def test_busy_session_is_never_resumed_message_is_queued(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nbir"), "queued")
        self.assertEqual(self.mutating_calls(), [])
        self.assertEqual([q["text"] for q in self.ctl.queue()], [R("[Sahip · ofis sayfası]\nbir")])
        self.assertEqual(self.ctl.status()["queue"], 1)

    def test_queue_drains_one_message_per_idle_transition(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.ctl.deliver("[Sahip · ofis sayfası]\niki")
        self.assertFalse(self.ctl.drain_once())  # still busy
        self.fake.set_status(SID, "idle")
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual(self.mutating_calls(), [["stop", SID[:8]], ["--bg", "--resume", SID,
                                                                     R("[Sahip · ofis sayfası]\nbir")]])
        self.assertEqual(len(self.ctl.queue()), 1)
        self.assertFalse(self.ctl.drain_once())  # resumed session is busy now
        self.fake.set_status(SID, "idle")
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual(self.mutating_calls()[-1], ["--bg", "--resume", SID, R("[Sahip · ofis sayfası]\niki")])
        self.assertEqual(self.ctl.queue(), [])

    def test_grace_period_prevents_interrupting_a_just_delivered_message(self):
        self.record()
        self.fake.flag("resume-idle")  # `claude agents` has not caught up: still reports idle
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nbir"), "delivered")
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\niki"), "queued")
        self.assertFalse(self.ctl.drain_once())
        self.t += 30  # grace over and the session is idle: it really finished
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual(self.mutating_calls()[-1], ["--bg", "--resume", SID, R("[Sahip · ofis sayfası]\niki")])

    def test_new_message_does_not_overtake_queued_ones(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.fake.set_status(SID, "idle")
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\niki"), "queued")
        self.assertEqual(self.mutating_calls(), [])
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual(self.mutating_calls()[-1][-1], R("[Sahip · ofis sayfası]\nbir"))

    def test_queue_survives_restart(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.assertEqual(len(self.make().queue()), 1)

    def test_failed_delivery_keeps_queued_message(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.fake.set_status(SID, "idle")
        self.fake.flag("fail")
        self.assertFalse(self.ctl.drain_once())
        self.assertEqual(len(self.ctl.queue()), 1)
        self.assertIsNotNone(self.ctl.last_error)
        self.fake.flag("fail", on=False)
        self.assertFalse(self.ctl.drain_once())  # backing off
        self.t += 60
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual(self.ctl.queue(), [])

    # --- races around stop + resume (finding 5) ---

    def ceo_transcript(self, records, age=0):
        path = fakes.write_transcript(self.projects, self.root, SID, records)
        if age:
            old = time.time() - age
            os.utime(path, (old, old))
        return path

    def turn_end(self):
        return {"type": "system", "subtype": "turn_duration", "timestamp": fakes.ts(date.today()), "durationMs": 1}

    def test_idle_session_with_an_open_turn_in_its_transcript_is_treated_as_busy(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        path = self.ceo_transcript([fakes.human(date.today(), "a"), self.turn_end(),
                                    fakes.peer(date.today(), "ofis-blog-1-ab", "[blog] DONE: x")])
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nbir"), "queued")
        self.assertEqual(self.mutating_calls(), [])
        self.assertFalse(self.ctl.drain_once())
        fakes.write_transcript(self.projects, self.root, SID, [self.turn_end()], mode="a")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(self.ctl.drain_once())
        self.assertEqual(self.mutating_calls()[-1], ["--bg", "--resume", SID, R("[Sahip · ofis sayfası]\nbir")])

    def test_open_turn_with_no_writes_for_a_while_is_not_waited_for_forever(self):
        # An interrupted turn writes no turn_duration; once the transcript is quiet the session is idle.
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        self.ceo_transcript([fakes.human(date.today(), "a"),
                             fakes.user(date.today(), [{"type": "text", "text": "[Request interrupted by user]"}])],
                            age=ceo.STALE_TURN_SECONDS + 5)
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nbir"), "delivered")

    def test_status_is_rechecked_right_before_stop(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        self.fake.set_next_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])  # a peer message woke it
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nbir"), "queued")
        self.assertEqual(self.mutating_calls(), [])
        self.assertEqual(len(self.ctl.queue()), 1)

    def test_session_still_listed_after_stop_is_not_resumed(self):
        self.record()
        self.fake.flag("stop-noop")
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        with self.assertRaises(ceo.CeoUnavailable):
            self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.assertEqual(self.mutating_calls(), [["stop", SID[:8]]])  # never a resume: that would be a copy

    def test_queued_message_is_kept_when_the_session_does_not_go_away(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.fake.set_status(SID, "idle")
        self.fake.flag("stop-noop")
        self.assertFalse(self.ctl.drain_once())
        self.assertEqual(len(self.ctl.queue()), 1)
        self.assertNotIn("--resume", [a for c in self.mutating_calls() for a in c])

    # --- delivery outcome (finding 6) ---

    def drained_once(self, text="[Sahip · ofis sayfası]\nbir"):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver(text)
        self.fake.set_status(SID, "idle")
        return self.ctl.drain_once()

    def resumes(self):
        return [c for c in self.mutating_calls() if c[:2] == ["--bg", "--resume"]]

    def test_resume_with_other_wording_counts_as_delivered(self):
        self.fake.flag("odd-output")
        self.assertTrue(self.drained_once())
        self.assertEqual(self.ctl.queue(), [])
        self.assertIn("launch line", self.ctl.last_error)
        self.t += 100
        self.fake.set_status(SID, "idle")
        self.assertFalse(self.ctl.drain_once())
        self.assertEqual(len(self.resumes()), 1)

    def test_direct_delivery_with_other_wording_is_delivered(self):
        self.record()
        self.fake.flag("odd-output")
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        self.assertEqual(self.ctl.deliver("[Sahip · ofis sayfası]\nbir"), "delivered")

    def test_resume_reporting_another_name_is_delivered_with_a_warning(self):
        self.fake.flag("other-name")
        self.assertTrue(self.drained_once())
        self.assertEqual(self.ctl.queue(), [])
        self.assertIn("ofis-other", self.ctl.last_error)
        self.assertEqual(len(self.resumes()), 1)

    def test_resume_timeout_is_unconfirmed_and_never_resent(self):
        self.fake.flag("slow")
        self.ctl.cli.timeout = 1
        self.assertFalse(self.drained_once())
        self.assertEqual(self.ctl.queue(), [])
        self.assertIn("unconfirmed", self.ctl.last_error)
        with open(os.path.join(self.durum, "ceo-unconfirmed.jsonl")) as f:
            self.assertEqual(json.loads(f.readline())["text"], R("[Sahip · ofis sayfası]\nbir"))
        self.t += 100
        self.fake.flag("slow", on=False)
        self.fake.set_status(SID, "idle")
        self.assertFalse(self.ctl.drain_once())
        self.assertEqual(len(self.resumes()), 1)

    def test_direct_delivery_timeout_is_reported_as_unconfirmed(self):
        self.record()
        self.fake.flag("slow")
        self.ctl.cli.timeout = 1
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        with self.assertRaises(ceo.CeoUnavailable) as ctx:
            self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.assertIn("unconfirmed", str(ctx.exception))
        self.assertEqual(self.ctl.queue(), [])

    def test_message_is_not_delivered_twice_when_dropping_it_fails(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "busy")])
        self.ctl.deliver("[Sahip · ofis sayfası]\nbir")
        self.fake.set_status(SID, "idle")
        real = self.ctl._rewrite_queue
        calls = []

        def failing():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk full")
            return real()
        self.ctl._rewrite_queue = failing
        with self.assertRaises(OSError):
            self.ctl.drain_once()
        self.t += 100
        self.fake.set_status(SID, "idle")
        self.ctl.drain_once()
        self.assertEqual(len(self.resumes()), 1)
        self.assertEqual(self.ctl.queue(), [])

    # --- queue file and status (findings 8, 9) ---

    def test_corrupt_queue_line_is_skipped_and_cleaned_up(self):
        self.record()
        os.makedirs(self.durum, exist_ok=True)
        with open(os.path.join(self.durum, "ceo-queue.jsonl"), "w") as f:
            f.write(json.dumps({"text": "[Sahip · ofis sayfası]\nbir"}) + "\n{bozuk\n[1, 2]\n"
                    + json.dumps({"text": "[Sahip · ofis sayfası]\niki"}) + "\n")
        self.assertEqual([q["text"] for q in self.ctl.queue()],
                         ["[Sahip · ofis sayfası]\nbir", "[Sahip · ofis sayfası]\niki"])
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        self.assertTrue(self.ctl.drain_once())
        with open(os.path.join(self.durum, "ceo-queue.jsonl")) as f:
            lines = f.read().splitlines()
        self.assertEqual([json.loads(line)["text"] for line in lines], ["[Sahip · ofis sayfası]\niki"])

    def test_status_does_not_wait_for_a_delivery_in_progress(self):
        self.record()
        self.fake.set_agents([fakes.agent("ofis-ceo", self.root, SID, "idle")])
        result = {}
        with self.ctl._lock:  # a delivery holds the lock
            self.ctl._delivering = True
            worker = threading.Thread(target=lambda: result.update(self.ctl.status()))
            worker.start()
            worker.join(10)
            self.ctl._delivering = False
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["state"], "busy")

    # --- refusals ---

    def test_unreachable_claude_raises(self):
        self.fake.flag("fail")
        with self.assertRaises(ceo.CeoUnavailable):
            self.ctl.deliver("[Sahip · ofis sayfası]\nmerhaba")

    def test_missing_claude_binary_raises(self):
        cli = claude_cli.ClaudeCLI(claude_bin=os.path.join(self.tmp.name, "yok"), cache_seconds=0)
        ctl = ceo.CeoController(cli, self.root, "ofis-ceo", self.durum, self.projects, sleep=lambda s: None)
        with self.assertRaises(ceo.CeoUnavailable):
            ctl.deliver("[Sahip · ofis sayfası]\nmerhaba")

    def test_text_starting_with_dash_is_refused_before_claude(self):
        for text in ("--dangerously-skip-permissions", "  -p x", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.ctl.deliver(text)
        self.assertEqual(self.mutating_calls(), [])

    def test_cli_refuses_dash_text_too(self):
        cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path)
        with self.assertRaises(claude_cli.ClaudeError):
            cli.resume_bg(SID, "--model x", self.root)
        self.assertEqual(self.mutating_calls(), [])


if __name__ == "__main__":
    unittest.main()
