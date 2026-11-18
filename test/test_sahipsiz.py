"""Tests for bin/sahipsiz.py (orphan office sessions, owner decision 2026-11-16) and its hook in bin/postoffice.py: one CEO
notice per `ofis-` session no job references, past the threshold; never a stop. Temp vault/durum only."""
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config, test/sahip_yasaklari.py)
import jobs  # noqa: E402
import records  # noqa: E402
import sahipsiz  # noqa: E402

NOW = datetime(2026, 11, 16, 10, 0, 0)
ORPHAN = "ofis-atolye-1114-184955-399f"
ORPHAN_SID = "399f0000-1111-2222-3333-444455556666"


def ms(dt):
    return int(dt.timestamp() * 1000)


def row(name, cwd, sid, started, **extra):
    return dict({"cwd": cwd, "kind": "background", "startedAt": ms(started), "sessionId": sid, "name": name,
                 "state": "blocked"}, **extra)


class FakeCeo:
    def __init__(self):
        self.sent = []

    def enqueue(self, text, key):
        if any(k == key for _, k in self.sent):
            return "duplicate"
        self.sent.append((text, key))
        return "queued"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.vault = os.path.join(base, "vault", "OFIS")
        self.durum = os.path.join(base, "durum")
        self.project = os.path.join(base, "Dev", "atolye")
        self.zim = os.path.join(base, "Dev", "zim")
        for d in (self.project, self.zim, jobs.folder_path(self.vault, jobs.ACTIVE)):
            os.makedirs(d)
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
                    "projects": {"atolye": {"path": self.project}}}
        self.ceo = FakeCeo()
        self.check = sahipsiz.Sahipsiz(self.cfg, self.durum, self.ceo, now=lambda: NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def old(self):
        return datetime(2026, 11, 14, 18, 49, 55)


class DetectTest(Base):
    def test_orphan_past_threshold_gets_one_notice(self):
        sent = self.check.check([row(ORPHAN, self.project, ORPHAN_SID, self.old())])
        self.assertEqual(sent, [ORPHAN])
        self.assertEqual(len(self.ceo.sent), 1)
        text, key = self.ceo.sent[0]
        self.assertEqual(key, f"sahipsiz-{ORPHAN_SID}")
        self.assertTrue(text.startswith("[Ofis · sistem]\nSahipsiz oturum: " + ORPHAN + " (atolye) 39 saattir"))
        self.assertIn("başlangıç 14 Kasım 18:49", text)
        self.assertIn("`claude stop 399f0000`", text)
        self.assertIn("`claude rm` asla", text)

    def test_ignored_sessions(self):
        job = jobs.create(self.vault, "atolye", "İş", brief={"hedef": "Yap."}, now=NOW)
        jobs.update(self.vault, job.name, fields={"oturum": "ofis-atolye-1114-100000-aaaa"})
        records.update(self.durum, "2026-11-14-090000-atolye.md", {"oturum": "ofis-atolye-1114-090000-bbbb"})
        sid = "aaaa0000-1111-2222-3333-4444555566%02d"
        rows = [row("ofis-ceo", self.project, sid % 1, self.old()),
                row("ofis-atolye-1114-100000-aaaa", self.project, sid % 2, self.old()),  # a job's note names it
                row("ofis-atolye-1114-090000-bbbb", self.project, sid % 3, self.old()),  # a server record names it
                row("ofis-atolye-1116-083000-cccc", self.project, sid % 4, datetime(2026, 11, 16, 8, 30)),  # young
                row("review", self.project, sid % 5, self.old()),  # not an office session
                row("ofis-zim-1114-100000-dddd", self.zim, sid % 6, self.old()),  # ZIM: out of scope
                row("ofis-atolye-1114-100000-eeee", self.project, "../x", self.old()),
                row("ofis-atolye-1114-100000-ffff", self.project, sid % 8, self.old(), startedAt=None)]
        self.assertEqual(self.check.check(rows), [])
        self.assertEqual(self.ceo.sent, [])

    def test_threshold_from_config(self):
        young = row(ORPHAN, self.project, ORPHAN_SID, datetime(2026, 11, 16, 8, 30))
        self.assertEqual(self.check.check([young]), [])
        self.cfg["sahipsiz_oturum_saat"] = 1
        self.assertEqual(self.check.check([young]), [ORPHAN])
        for bad in ("3", 0, -1, True, None):
            self.assertEqual(sahipsiz.threshold_hours({"sahipsiz_oturum_saat": bad}), 3.0)
        self.assertEqual(sahipsiz.threshold_hours({}), 3.0)

    def test_unreadable_job_folder_skips_the_check(self):
        cfg = dict(self.cfg, vault_ofis=os.path.join(self.tmp.name, "missing"))
        check = sahipsiz.Sahipsiz(cfg, self.durum, self.ceo, now=lambda: NOW)
        self.assertEqual(check.check([row(ORPHAN, self.project, ORPHAN_SID, self.old())]), [])
        self.assertEqual(self.ceo.sent, [])


class OnceTest(Base):
    def test_notifies_once_across_a_restart_and_forgets_gone_sessions(self):
        rows = [row(ORPHAN, self.project, ORPHAN_SID, self.old())]
        self.assertEqual(self.check.check(rows), [ORPHAN])
        self.assertEqual(self.check.check(rows), [])
        restarted_ceo = FakeCeo()  # a fresh queue: only the state file prevents a repeat
        restarted = sahipsiz.Sahipsiz(self.cfg, self.durum, restarted_ceo, now=lambda: NOW)
        self.assertEqual(restarted.check(rows), [])
        self.assertEqual(restarted_ceo.sent, [])
        restarted.check([])  # the session is gone
        self.assertEqual(restarted._load(), {})


class NeverStopsTest(Base):
    def test_post_office_hook_only_lists_agents(self):
        import postoffice

        class RecordingCli:
            def __init__(self, agents):
                self.calls, self._agents = [], agents

            def agents(self, fresh=False):
                self.calls.append("agents")
                return self._agents

            def __getattr__(self, name):  # stop, rm, kill, send, …: recorded, never expected
                def call(*args, **kwargs):
                    self.calls.append(name)
                return call

        cli = RecordingCli([row(ORPHAN, self.project, ORPHAN_SID, self.old())])
        po = postoffice.PostOffice.__new__(postoffice.PostOffice)  # only the fields the hook uses
        po.cli, po.clock, po.log_file, po.last_error = cli, (lambda: 1000.0), io.StringIO(), None
        po.orphans, po._orphans_checked_at = self.check, None
        po._maybe_check_orphans()
        po._maybe_check_orphans()  # throttled: no second listing
        self.assertEqual(cli.calls, ["agents"])
        self.assertEqual([k for _, k in self.ceo.sent], [f"sahipsiz-{ORPHAN_SID}"])
        self.assertIsNone(po.last_error)


if __name__ == "__main__":
    unittest.main()
