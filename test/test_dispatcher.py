"""Tests for the dispatcher (phase 3): auto-start of queued jobs, dependencies, holds, WIP limits, the first-minute
check and the ofis.py commands around them. Fake claude, temp vault/durum/transcripts only."""
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import ceo  # noqa: E402
import claude_cli  # noqa: E402
import dispatcher  # noqa: E402
import fakes  # noqa: E402
import jobs  # noqa: E402
import launch  # noqa: E402
import ofis  # noqa: E402
import postoffice  # noqa: E402
import records  # noqa: E402

NOW = datetime(2026, 11, 10, 18, 38, 20)


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "ajan-ofisi")
        self.durum = os.path.join(self.root, "durum")
        self.blog = os.path.join(base, "Dev", "blog")
        self.kasa = os.path.join(base, "Dev", "kasa")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.projects_dir = os.path.join(base, "projects")
        for d in (self.root, self.blog, self.kasa, self.vault):
            os.makedirs(d)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault, "default_budget_usd": 3,
                    "projects": {"blog": {"path": self.blog}, "kasa": {"path": self.kasa}}}
        self.cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)
        self.t = 1000.0
        self.now = NOW
        kw = {"clock": lambda: self.t, "sleep": lambda s: None, "find_attempts": 3}
        self.ceo = ceo.CeoController(self.cli, self.root, "ofis-ceo", self.durum, self.projects_dir, **kw)
        self.po = postoffice.PostOffice(self.cfg, self.cli, self.ceo, self.durum, self.projects_dir,
                                        now=lambda: self.now, channel_kwargs=kw, log=io.StringIO(),
                                        clock=lambda: self.t)

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def run_cli(self, *argv, now=None):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, claude_bin=self.fake.path,
                         now=lambda: now or self.now, out=out, err=err, cwd=self.blog)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv, **kw):
        code, out, err = self.run_cli(*argv, **kw)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def refused(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 1, out)
        self.assertTrue(err.startswith("REFUSED: "), err)
        return err

    def add(self, project="blog", *extra, minute=0):
        when = NOW + timedelta(minutes=minute)
        return self.ok("ekle", "--proje", project, "--baslik", f"İş {project} {minute}", "--hedef", "Yap.", *extra,
                       now=when)["is"]

    def job(self, name):
        return jobs.load(self.vault, name)

    def status(self, name):
        return self.job(name).meta["durum"]

    def starts(self):
        return [c for c in self.fake.calls() if c["args"][:2] == ["--bg", "--name"]
                and c["args"][2] != "ofis-ceo"]

    def ceo_queue(self):
        return [q["text"] for q in self.ceo.queue()]

    # --- auto-start ---

    def test_a_queued_job_starts_by_itself(self):
        name = self.add()
        self.assertEqual(self.po.dispatch(), [name])
        job = self.job(name)
        self.assertEqual((job.folder, job.meta["durum"]), (jobs.ACTIVE, "calisiyor"))
        [call] = self.starts()
        self.assertEqual(os.path.realpath(call["cwd"]), self.blog)
        self.assertEqual(records.load(self.durum, name)["oturum"], job.meta["oturum"])
        self.assertEqual(self.ceo_queue(), [], "a start wakes nobody")

    def test_oldest_first_and_one_start_per_pass(self):
        later = self.add("kasa", minute=5)
        older = self.add("blog", minute=1)
        self.assertEqual(self.po.dispatch(), [older])
        self.assertEqual(self.status(later), "sirada")
        self.assertEqual(self.po.dispatch(), [later])
        self.assertEqual(self.po.dispatch(), [])

    def test_the_tick_runs_the_dispatcher(self):
        name = self.add()
        self.po.tick()
        self.assertEqual(self.status(name), "calisiyor")

    def test_a_dependent_job_waits_until_its_dependency_is_bitti(self):
        first = self.add("blog")
        second = self.add("kasa", "--bagimli", first, minute=1)
        self.assertEqual(self.po.dispatch(), [first])
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.status(second), "sirada")
        jobs.update(self.vault, first, status="bitti")
        self.assertEqual(self.po.dispatch(), [second])

    def test_the_record_dependencies_win_over_the_note(self):
        first = self.add("blog", "--beklet")
        second = self.add("kasa", "--bagimli", first, minute=1)
        self.assertEqual(records.load(self.durum, second)["bagimli"], first)
        jobs.update(self.vault, second, fields={"bagimli": ""})  # a session cannot free a job by editing the note
        self.assertEqual(self.po.dispatch(), [])

    def test_a_held_job_waits_until_serbest(self):
        name = self.add("blog", "--beklet")
        self.assertEqual((self.job(name).meta["beklet"], records.load(self.durum, name)["beklet"]), ("evet", "evet"))
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.ok("serbest", name), {"is": name, "beklet": ""})
        self.assertEqual(self.job(name).meta.get("beklet", ""), "")
        self.assertEqual(self.po.dispatch(), [name])

    def test_serbest_needs_a_queued_held_job(self):
        name = self.add()
        self.assertIn("not held", self.refused("serbest", name))
        self.po.dispatch()
        self.assertIn("sirada", self.refused("serbest", name))

    def test_baslat_starts_a_held_job_at_once(self):
        name = self.add("blog", "--beklet")
        self.ok("baslat", name)
        self.assertEqual(self.status(name), "calisiyor")

    # --- the approval backlog (onay birikişi) ---

    def card(self, n, durum="bekliyor", tur="akis-onay"):
        folder = os.path.join(self.vault, "Kararlar")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"2026-11-10-akis-{n}-onay.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"---\nproje: blog\ndurum: {durum}\ntur: {tur}\n---\n# Onay {n}\n\n## Soru\nOnay?\n")
        return path

    def kod_job(self, project="blog", minute=0):
        return self.add(project, "--katman", "kod", "--kontrol", "test -d .", minute=minute)

    def test_approval_cards_piling_up_hold_new_kod_jobs_but_not_reading_jobs(self):
        self.card(1)
        self.card(2)
        self.card(3, tur="claude-md-onerisi")  # another kind of decision does not count
        self.card(4, durum="cevaplandi")
        kod = self.kod_job("blog")
        reading = self.add("kasa", minute=1)
        self.assertEqual(dispatcher.onay_birikti(self.cfg, self.vault)["bekleyen"], 2)
        self.assertEqual(self.po.dispatch(), [reading], "the reading job starts; the kod job waits")
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.status(kod), "sirada")
        info = dispatcher.queue_info(self.cfg, self.vault, self.durum)
        self.assertTrue(info[kod]["onay_birikti"])
        # The owner answers one card (cevapla closes it): the kod job starts by itself
        self.card(1, durum="cevaplandi")
        self.assertEqual(self.po.dispatch(), [kod])

    def test_the_limit_comes_from_ofis_json_and_the_ceo_is_told_once(self):
        self.cfg["max_bekleyen_onay"] = 1
        self.card(1)
        kod = self.kod_job()
        self.assertEqual(self.po.dispatch(), [])
        self.po.dispatch()
        told = [q for q in self.ceo_queue() if "Onay bekleyen 1 kart var" in q]
        self.assertEqual(len(told), 1)
        self.assertIn("yeni kod işlerini ve yeni akışları başlatmıyor", told[0])
        # a restart (a new dispatcher, the CEO queue drained) never repeats it for the same cards
        sent = []

        class Ceo:
            def enqueue(self, text, key):
                sent.append(key)
        again = dispatcher.Dispatcher(self.cfg, self.durum, Ceo(), start=lambda n: None, now=lambda: self.now,
                                      log=io.StringIO())
        again.run_once()
        self.assertEqual(sent, [], "the key kept in durum survives a restart")
        self.assertEqual(self.status(kod), "sirada")
        self.cfg["max_bekleyen_onay"] = 2
        self.assertEqual(self.po.dispatch(), [kod])

    def test_an_escalated_kod_job_is_not_held(self):
        self.card(1)
        self.card(2)
        kod = self.kod_job()
        records.update(self.durum, kod, {"yukseltme_kaynagi": "2026-11-10-000000-blog.md"})
        self.assertEqual(self.po.dispatch(), [kod])

    def test_a_workflow_first_step_is_held(self):
        self.card(1)
        self.card(2)
        name = self.add("kasa")
        records.update(self.durum, name, {"akis": "akis-1110-000000-kasa", "adim": 1, "akis_ilk": "evet"})
        self.assertTrue(dispatcher.onay_bekletir(self.durum, self.job(name)))
        self.assertEqual(self.po.dispatch(), [])
        records.update(self.durum, name, {"adim": 2, "akis_ilk": ""})
        self.assertFalse(dispatcher.onay_bekletir(self.durum, self.job(name)), "a later (review) step goes on")

    def test_a_plan_re_round_of_a_running_workflow_is_not_held(self):
        self.card(1)
        self.card(2)
        name = self.add("kasa")  # plan DÜZELT: a new plan job, step 1, round 2 (bin/akis.py _plan_round)
        records.update(self.durum, name, {"akis": "akis-1110-000000-kasa", "adim": 1, "adim_turu": "plan",
                                          "akis_ilk": ""})
        self.assertFalse(dispatcher.onay_bekletir(self.durum, self.job(name)))
        self.assertFalse(dispatcher.queue_info(self.cfg, self.vault, self.durum)[name]["onay_birikti"])

    # --- limits ---

    def test_the_global_running_limit(self):
        self.cfg["max_running"] = 1
        first = self.add("blog")
        second = self.add("kasa", minute=1)
        self.assertEqual(self.po.dispatch(), [first])
        self.assertEqual(self.po.dispatch(), [], "1/1 running")
        jobs.update(self.vault, first, status="kontrolde")
        self.assertEqual(self.po.dispatch(), [], "kontrolde counts")
        jobs.update(self.vault, first, status="bitti")
        self.assertEqual(self.po.dispatch(), [second])

    def test_one_job_per_project_folder_and_a_job_waiting_for_deniz_counts(self):
        first = self.add("blog")
        second = self.add("blog", minute=1)
        other = self.add("kasa", minute=2)
        self.assertEqual(self.po.dispatch(), [first])
        self.assertEqual(self.po.dispatch(), [other], "the per-project limit holds the second blog job only")
        jobs.update(self.vault, first, status="karar-bekliyor")
        self.assertEqual(self.po.dispatch(), [], "its working folder is still in use")
        jobs.update(self.vault, first, status="iptal")
        self.assertEqual(self.po.dispatch(), [second])

    def test_a_job_in_a_worktree_does_not_count_for_its_project(self):
        first = self.add("blog")
        second = self.add("blog", minute=1)
        self.ok("baslat", first, "--worktree")
        self.assertEqual(self.po.dispatch(), [second])

    def test_baslat_refuses_over_a_limit_with_a_clear_message(self):
        self.cfg["max_running"] = 1
        first = self.add("blog")
        second = self.add("kasa", minute=1)
        self.ok("baslat", first)
        err = self.refused("baslat", second)
        self.assertIn("1/1", err)
        self.assertIn("sınır", err)
        self.assertEqual(self.status(second), "sirada")
        self.assertIsNone(records.load(self.durum, second).get("oturum"), "nothing of a session was recorded")
        third = self.add("blog", minute=2)
        self.cfg["max_running"] = 3
        self.assertIn("blog", self.refused("baslat", third))

    def test_ekle_refuses_when_the_projects_queue_is_full(self):
        self.cfg["max_queued_per_project"] = 2
        self.add("blog", "--beklet")
        self.add("blog", "--beklet", minute=1)
        self.assertIn("Sıradakiler dolu", self.refused("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y"))
        self.add("kasa", minute=2)  # another project has its own queue

    def test_limits_default_to_three_one_and_five(self):
        self.assertEqual(dispatcher.limits({}), (3, 1, 5))
        self.assertEqual(dispatcher.limits({"max_running": 2, "max_running_per_project": 2,
                                            "max_queued_per_project": 9}), (2, 2, 9))
        self.assertEqual(dispatcher.limits({"max_running": 0, "max_running_per_project": "x"}), (3, 1, 5))

    # --- blocked dependencies ---

    def test_a_blocked_dependency_marks_engel_and_asks_the_ceo_once(self):
        first = self.add("blog")
        second = self.add("kasa", "--bagimli", first, minute=1)
        self.po.dispatch()
        jobs.update(self.vault, first, status="tikandi")
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.job(second).meta["engel"], f"{jobs.stem(first)} tikandi")
        self.assertEqual(records.load(self.durum, second)["engel"], f"{jobs.stem(first)} tikandi")
        [notice] = self.ceo_queue()
        self.assertTrue(notice.startswith("[Ofis · sistem]\nkasa işi bekliyor:"), notice)
        self.assertIn(f"ofis.py bagimli {jobs.stem(second)} --kaldir {jobs.stem(first)}", notice)
        self.po.dispatch()
        self.assertEqual(len(self.ceo_queue()), 1)
        self.assertEqual(self.ok("bagimli", second, "--kaldir", first), {"is": second, "bagimli": ""})
        self.assertEqual(self.po.dispatch(), [second])
        self.assertEqual(self.job(second).meta.get("engel", ""), "")

    def test_engel_clears_when_the_dependency_goes_on_and_finishes(self):
        first = self.add("blog")
        second = self.add("kasa", "--bagimli", first, minute=1)
        self.po.dispatch()
        jobs.update(self.vault, first, status="tikandi")
        self.po.dispatch()
        jobs.update(self.vault, first, status="calisiyor")
        self.po.dispatch()
        self.assertEqual(self.job(second).meta.get("engel", ""), "")
        jobs.update(self.vault, first, status="bitti")
        self.assertEqual(self.po.dispatch(), [second])

    def test_bagimli_kaldir_refuses_bad_input(self):
        first = self.add("blog")
        second = self.add("kasa", "--bagimli", first, minute=1)
        self.assertIn("not a dependency", self.refused("bagimli", second, "--kaldir", "2026-01-01-000000-yok"))
        self.ok("baslat", first)
        self.assertIn("sirada", self.refused("bagimli", first, "--kaldir", second))

    def test_a_failed_auto_start_tells_the_ceo_once(self):
        name = self.add()
        self.fake.flag("fail")
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.status(name), "basarisiz")
        [notice] = self.ceo_queue()
        self.assertTrue(notice.startswith("[Ofis · sistem]\nblog işi başlatılamadı:"), notice)
        self.po.dispatch()
        self.assertEqual(len(self.ceo_queue()), 1)

    def test_a_kod_job_without_a_trusted_kontrol_is_not_started(self):
        name = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--katman", "kod",
                       "--kontrol", "test -d .")["is"]
        os.remove(os.path.join(self.durum, "kontroller", jobs.stem(name) + ".json"))
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.status(name), "sirada")
        self.assertIn("kontrolsüz", self.ceo_queue()[0])

    def test_durum_shows_why_a_queued_job_waits(self):
        first = self.add("blog", "--beklet")
        second = self.add("kasa", "--bagimli", first, minute=1)
        code, out, err = self.run_cli("durum")
        self.assertEqual(code, 0, err)
        lines = {line.split()[1]: line for line in out.splitlines()[1:]}
        self.assertIn("beklet", lines[jobs.stem(first)])
        self.assertIn(f"bekliyor: {jobs.stem(first)}", lines[jobs.stem(second)])

    # --- the page ---

    def test_queue_info_for_the_page(self):
        first = self.add("blog", "--beklet")
        second = self.add("blog", "--bagimli", first, minute=1)
        info = dispatcher.queue_info(self.cfg, self.vault, self.durum)
        self.assertEqual(info[first], {"position": 1, "held": True, "depends": [], "blocked": "",
                                       "onay_birikti": False, "kota_bekliyor": ""})
        self.assertEqual(info[second], {"position": 2, "held": False, "depends": [first], "blocked": "",
                                        "onay_birikti": False, "kota_bekliyor": ""})
        self.assertEqual(dispatcher.running_count(self.vault), 0)

    # --- the first-minute check ---

    def started(self, project="blog", records_=None):
        name = self.add(project)
        self.po.dispatch()
        job = self.job(name)
        sid = "c0ffee00-1111-2222-3333-444455556666"
        self.fake.set_agents([])
        if records_ is not None:
            fakes.write_transcript(self.projects_dir, job.meta["calisma_dizini"], sid,
                                   fakes.name_records(job.meta["oturum"], sid) + records_)
        return name

    def test_a_job_with_no_progress_after_two_minutes_is_reported_once(self):
        name = self.started(records_=[fakes.human(NOW.date(), "Görev", hour=19)])
        self.now = NOW + timedelta(seconds=90)
        self.po.check_active()
        self.assertEqual(self.ceo_queue(), [], "not yet two minutes")
        self.now = NOW + timedelta(seconds=150)
        self.po.check_active()
        [notice] = self.ceo_queue()
        self.assertTrue(notice.startswith("[Ofis · sistem]\nblog işi ilerlemiyor:"), notice)
        self.assertIn("Selin'e sor", notice)
        self.assertEqual((self.job(name).meta["ilk_dakika"], records.load(self.durum, name)["ilk_dakika"]),
                         ("sessiz", "sessiz"))
        self.assertEqual(self.status(name), "calisiyor", "never stopped automatically")
        self.po.check_active()
        self.assertEqual(len(self.ceo_queue()), 1)

    def test_a_job_without_any_transcript_counts_as_no_progress(self):
        self.started()
        self.now = NOW + timedelta(seconds=150)
        self.po.check_active()
        self.assertEqual(len(self.ceo_queue()), 1)

    def test_a_job_that_used_a_tool_is_marked_fine(self):
        tool = fakes.assistant(NOW.date(), "a1", [{"type": "tool_use", "name": "Read", "input": {}}], hour=19,
                               stop_reason="tool_use")
        name = self.started(records_=[fakes.human(NOW.date(), "Görev", hour=19), tool])
        self.now = NOW + timedelta(seconds=150)
        self.po.check_active()
        self.assertEqual(self.ceo_queue(), [])
        self.assertEqual(self.job(name).meta["ilk_dakika"], "tamam")

    def test_progress_from_before_the_start_does_not_count(self):
        old = fakes.assistant(NOW.date(), "a0", [{"type": "text", "text": "eski"}], hour=17)
        self.started(records_=[old, fakes.human(NOW.date(), "Görev", hour=19)])
        self.now = NOW + timedelta(seconds=150)
        self.po.check_active()
        self.assertEqual(len(self.ceo_queue()), 1)


    # --- escalation end to end ---

    def test_an_escalated_job_is_started_by_the_dispatcher_in_a_fresh_session(self):
        self.cfg["tiers"] = {"genel": {"model": "sonnet", "effort": "medium"}, "kod": {"model": "opus"}}
        self.cfg["ladder"] = ["genel", "kod"]
        name = self.add("blog", "--katman", "genel", "--kontrol", "echo FAILED; exit 1")
        self.assertEqual(self.po.dispatch(), [name])
        session = self.job(name).meta["oturum"]
        for _ in range(2):
            self.ok("bildir", "--oturum", session, "--tur", "bitti", "Tamam.")
            self.po.process_inbox()
            self.po.kontrol.run_pending()
            if self.status(name) == "calisiyor":
                os.remove(os.path.join(self.durum, "giden", sorted(os.listdir(os.path.join(self.durum, "giden")))[0]))
        self.assertEqual(self.status(name), "tikandi")
        [new] = [j for j in jobs.list_jobs(self.vault) if j.meta.get("yukseltme_kaynagi") == name]
        self.assertEqual(self.po.dispatch(), [new.name])
        started = self.job(new.name)
        self.assertEqual((started.meta["durum"], started.meta["model"]), ("calisiyor", "opus"))
        self.assertNotEqual(started.meta["oturum"], session, "a new session, never the old one resumed")
        self.assertEqual([c["args"][:2] for c in self.fake.calls() if c["args"][:2] == ["--bg", "--resume"]], [])


    # --- phase 3 review ---

    def stuck_with_session(self, name, session, cwd=None, status="tikandi"):
        """A started job in the given status with its session and folder on the record and the note."""
        cwd = cwd or self.blog
        records.update(self.durum, name, {"oturum": session, "calisma_dizini": cwd, "kisa_id": "abcdef12"})
        jobs.update(self.vault, name, status=status, fields={"oturum": session, "calisma_dizini": cwd})

    def devam_messages(self):
        folder = os.path.join(self.durum, "giden")
        return [n for n in os.listdir(folder) if "-devam-" in n] if os.path.isdir(folder) else []

    def test_devam_respects_the_per_project_limit(self):
        # finding 1 (the reviewer's p3): A stopped, B started in the same folder, devam A must not run them both
        a = self.add("blog")
        b = self.add("blog", minute=1)
        self.stuck_with_session(a, "ofis-blog-1110-000000-aaaa")
        self.stuck_with_session(b, "ofis-blog-1110-000001-bbbb", status="calisiyor")
        err = self.refused("devam", a)
        self.assertIn("blog projesinin klasöründe zaten 1 iş var", err)
        self.assertIn("devam", err)
        self.assertEqual(self.status(a), "tikandi")
        self.assertEqual(self.devam_messages(), [], "nothing is queued for the stopped session")
        jobs.update(self.vault, b, status="bitti")
        self.ok("devam", a)
        self.assertEqual(self.status(a), "calisiyor")

    def test_devam_respects_the_global_limit_but_not_the_project_limit_in_a_worktree(self):
        self.cfg["max_running"] = 1
        a = self.add("blog")
        b = self.add("kasa", minute=1)
        worktree = os.path.join(self.blog, ".claude", "worktrees", "ofis-blog-1110-000000-aaaa")
        os.makedirs(worktree)
        self.stuck_with_session(a, "ofis-blog-1110-000000-aaaa", cwd=worktree)
        self.stuck_with_session(b, "ofis-kasa-1110-000001-bbbb", cwd=self.kasa, status="calisiyor")
        self.assertIn("1/1", self.refused("devam", a))
        self.cfg["max_running"] = 3
        c = self.add("blog", minute=2)
        self.stuck_with_session(c, "ofis-blog-1110-000002-cccc", status="calisiyor")
        self.ok("devam", a)  # a worktree job does not count against (nor is held by) the project folder
        self.assertEqual(self.status(a), "calisiyor")

    def test_an_escalated_dependency_is_followed_to_its_replacement(self):
        # finding 7: the old job is tikandi with yukseltildi on its record; the dependent waits for the new one
        first = self.add("blog", "--beklet")
        second = self.add("kasa", "--bagimli", first, minute=1)
        replacement = self.add("blog", "--beklet", minute=2)
        jobs.update(self.vault, first, status="tikandi", fields={"yukseltildi": replacement})
        records.update(self.durum, first, {"yukseltildi": replacement})
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.job(second).meta.get("engel", ""), "")
        self.assertEqual(self.ceo_queue(), [], "an escalated dependency is not a blocked one")
        jobs.update(self.vault, replacement, status="bitti")
        self.assertEqual(self.po.dispatch(), [second])

    def test_yukseltildi_on_the_note_alone_is_not_followed(self):
        first = self.add("blog", "--beklet")
        second = self.add("kasa", "--bagimli", first, minute=1)
        done = self.add("blog", "--beklet", minute=2)
        jobs.update(self.vault, done, status="bitti")
        jobs.update(self.vault, first, status="tikandi", fields={"yukseltildi": done})  # a forged note
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.job(second).meta["engel"], f"{jobs.stem(first)} tikandi")

    def test_dependencies_are_read_again_under_the_lock_before_engel(self):
        # finding 7: the dependency was dropped (ofis.py bagimli --kaldir) between the pass's read and the engel write
        first = self.add("blog", "--beklet")
        second = self.add("kasa", "--bagimli", first, minute=1)
        jobs.update(self.vault, first, status="tikandi")
        real, calls = dispatcher.dependencies, []

        def stale(durum_dir, job):
            calls.append(job.name)
            if job.name == second and len([c for c in calls if c == second]) == 1:
                deps = real(durum_dir, job)
                self.ok("bagimli", second, "--kaldir", first)  # The owner decided meanwhile
                return deps
            return real(durum_dir, job)
        dispatcher.dependencies = stale
        self.addCleanup(setattr, dispatcher, "dependencies", real)
        self.po.dispatch()
        self.assertEqual(self.job(second).meta.get("engel", ""), "")
        self.assertEqual(self.ceo_queue(), [])

    def test_a_job_that_cannot_start_for_its_project_limit_is_not_attempted(self):
        # finding 8: no start path (no git subprocess) for a job the project limit holds back
        first = self.add("blog")
        second = self.add("blog", minute=1)
        self.assertEqual(self.po.dispatch(), [first])
        tried = []
        real = self.po.dispatcher.start
        self.po.dispatcher.start = lambda name: (tried.append(name), real(name))[1]
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(tried, [])
        self.assertEqual(self.status(second), "sirada")

    def test_the_gate_runs_before_git_in_the_start_path(self):
        # finding 8, launch.py: a start refused by a limit never runs `git rev-parse`
        self.cfg["max_running"] = 1
        first = self.add("blog")
        second = self.add("kasa", minute=1)
        self.ok("baslat", first)
        real, runs = launch.git_head, []
        launch.git_head = lambda *a, **k: (runs.append(a), real(*a, **k))[1]
        self.addCleanup(setattr, launch, "git_head", real)
        self.refused("baslat", second)
        self.assertEqual(runs, [])

    def test_a_refused_start_is_backed_off_until_the_job_changes(self):
        # finding 8: a kod job without its trusted Kontrol is not retried (and logged) on every pass
        name = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--katman", "kod",
                       "--kontrol", "test -d .")["is"]
        os.remove(os.path.join(self.durum, "kontroller", jobs.stem(name) + ".json"))
        tried = []
        real = self.po.dispatcher.start
        self.po.dispatcher.start = lambda n: (tried.append(n), real(n))[1]
        for _ in range(3):
            self.po.dispatch()
        self.assertEqual(tried, [name])
        rec = records.load(self.durum, name)
        self.assertIn("kontrolsüz", rec["baslatma_hatasi"])
        self.assertTrue(rec["baslatma_izi"])
        self.assertEqual(self.po.dispatcher.log_file.getvalue().count(f"start of {name}"), 1)
        self.ok("butce", name, "4")  # the record and the note change: one more try
        self.po.dispatch()
        self.assertEqual(tried, [name, name])

    def test_an_untrusted_folder_keeps_the_job_queued_until_deniz_trusts_it(self):
        # 2026-11-15: Claude 2.1.325 refuses `--bg` in an untrusted folder; the gün sonu job failed outright
        config = os.path.join(self.root, "claude.json")
        with open(config, "w") as f:
            json.dump({"projects": {}}, f)
        os.environ["OFIS_CLAUDE_JSON"] = config
        self.addCleanup(fakes.isolate_claude_trust)
        name = self.add()
        tried = []
        real = self.po.dispatcher.start
        self.po.dispatcher.start = lambda n: (tried.append(n), real(n))[1]
        for _ in range(3):
            self.po.dispatch()
        self.assertEqual(tried, [name])
        self.assertEqual(self.status(name), "sirada")
        self.assertEqual(self.starts(), [])
        notices = [t for t in self.ceo_queue() if "güvenmiyor" in t]
        self.assertEqual(len(notices), 1, self.ceo_queue())
        self.assertIn("başarısız sayılmadı", notices[0])
        self.assertIn(os.path.realpath(self.blog), notices[0])
        with open(config, "w") as f:  # a trusted parent is not enough; then the owner accepts the folder's own prompt
            json.dump({"projects": {os.path.realpath(os.path.dirname(self.blog)): {"hasTrustDialogAccepted": True}}},
                      f)
        self.po.dispatch()
        self.assertEqual(tried, [name])
        with open(config, "w") as f:
            json.dump({"projects": {os.path.realpath(self.blog): {"hasTrustDialogAccepted": True}}}, f)
        self.po.dispatch()
        self.assertEqual(tried, [name, name])
        self.assertNotEqual(self.status(name), "sirada")

    def test_notices_are_not_repeated_when_the_ceo_sent_log_forgot_them(self):
        # finding 9: the dispatcher records the notice keys on the job record instead of relying on the sent log
        sent = []

        class Forgetful:
            def enqueue(self, text, key):
                sent.append(key)
                return "queued"
        self.po.dispatcher.ceo = Forgetful()
        first = self.add("blog", "--beklet")
        second = self.add("kasa", "--bagimli", first, minute=1)
        jobs.update(self.vault, first, status="tikandi")
        stuck = self.ok("ekle", "--proje", "blog", "--baslik", "x", "--hedef", "y", "--katman", "kod",
                        "--kontrol", "test -d .", now=NOW + timedelta(minutes=3))["is"]
        os.remove(os.path.join(self.durum, "kontroller", jobs.stem(stuck) + ".json"))
        for usd in ("4", "5", "6"):
            self.po.dispatch()
            self.ok("butce", stuck, usd)  # changes the job, so its start is tried again every pass
        self.assertEqual(len([k for k in sent if k.startswith("engel-")]), 1, sent)
        self.assertEqual(len([k for k in sent if k.startswith("baslatma-")]), 1, sent)
        self.assertIn(sent[0], records.load(self.durum, second)["bildirilen"])


class CommandsTest(unittest.TestCase):
    def test_project_sessions_are_denied_the_new_commands(self):
        self.assertIn("serbest", launch.DENIED_COMMANDS)
        self.assertIn("bagimli", launch.DENIED_COMMANDS)



class QuotaFallbackTest(unittest.TestCase):
    """Step 4 (the owner's delegated decision, 2026-11-13): a new job whose model is on a concrete quota starts with its
    backup model (haiku→sonnet, sonnet→opus, opus→sonnet, fable→opus); a running job is never moved."""

    tearDown, run_cli, ok, add, job, status, starts, ceo_queue = (
        DispatcherTest.tearDown, DispatcherTest.run_cli, DispatcherTest.ok, DispatcherTest.add, DispatcherTest.job,
        DispatcherTest.status, DispatcherTest.starts, DispatcherTest.ceo_queue)

    def setUp(self):
        DispatcherTest.setUp(self)
        self.cfg.update({"tiers": {"genel": {"model": "sonnet", "effort": "medium"},
                                   "kolay": {"model": "haiku", "effort": "low"}}, "default_tier": "genel"})
        self.quotas = {}
        self.po.dispatcher.kota = lambda: dict(self.quotas)

    def back(self, hours=2):
        import model_durum
        return (NOW + timedelta(hours=hours)).replace(tzinfo=model_durum.office_tz())

    def model_of(self, call):
        return call["args"][call["args"].index("--model") + 1]

    def test_the_backup_table_has_defaults_and_reads_ofis_json(self):
        self.assertEqual(dispatcher.kota_yedegi({}), {"haiku": "sonnet", "sonnet": "opus", "opus": "sonnet",
                                                      "fable": "opus"})
        self.assertEqual(dispatcher.kota_yedegi({"kota_yedegi": {"opus": "fable", "haiku": "bad name!", "x": "y"}}),
                         {"haiku": "sonnet", "sonnet": "opus", "opus": "fable", "fable": "opus"})

    def test_a_job_whose_model_is_on_quota_starts_with_the_backup_and_says_so(self):
        self.quotas = {"sonnet": self.back()}
        name = self.add()
        self.assertEqual(self.po.dispatch(), [name])
        [call] = self.starts()
        self.assertEqual(self.model_of(call), "opus")
        rec = records.load(self.durum, name)
        self.assertEqual((rec["model"], rec["kota_yedegi"], rec["model_kaynagi"]),
                         ("opus", {"asil": "sonnet", "yedek": "opus"}, "kota"))
        self.assertEqual(self.job(name).meta["kota_yedegi"], "sonnet → opus")
        [notice] = [q for q in self.ceo_queue() if "kotada" in q]
        self.assertIn("Uzman kotada; yeni işler Kıdemli ile başlıyor, 20:38'de dönüyor", notice)
        # a second job in the same quota period: no second notice
        other = self.add("kasa", minute=1)
        self.assertEqual(self.po.dispatch(), [other])
        self.assertEqual(len([q for q in self.ceo_queue() if "kotada" in q]), 1)
        self.assertEqual(self.model_of(self.starts()[1]), "opus")

    def test_a_past_or_unknown_return_time_is_no_concrete_quota(self):
        self.quotas = {"sonnet": self.back(-1)}
        name = self.add()
        self.assertEqual(self.po.dispatch(), [name])
        self.assertEqual(self.model_of(self.starts()[0]), "sonnet")
        self.assertNotIn("kota_yedegi", records.load(self.durum, name))

    def test_both_models_on_quota_keep_the_job_queued_with_a_page_hint(self):
        self.quotas = {"sonnet": self.back(), "opus": self.back(3)}
        name = self.add()
        self.assertEqual(self.po.dispatch(), [])
        self.assertEqual(self.status(name), "sirada")
        self.assertEqual(self.starts(), [])
        info = dispatcher.queue_info(self.cfg, self.vault, self.durum)[name]
        self.assertIn("kotada", info["kota_bekliyor"])
        self.assertEqual(records.load(self.durum, name)["model"], "sonnet", "nothing was swapped")
        self.quotas = {}
        self.assertEqual(self.po.dispatch(), [name])
        self.assertEqual(self.model_of(self.starts()[0]), "sonnet", "the quota is over: its own model")
        self.assertFalse(records.load(self.durum, name).get("kota_bekliyor"))

    def test_a_refused_start_puts_the_model_back(self):
        self.quotas = {"haiku": self.back()}
        name = self.add("kasa", "--katman", "kolay")
        os.rmdir(self.kasa)  # the start is refused: the folder is gone
        self.assertEqual(self.po.dispatch(), [])
        rec = records.load(self.durum, name)
        self.assertEqual(rec["model"], "haiku")
        self.assertFalse(rec.get("kota_yedegi"))
        self.assertNotEqual(rec.get("model_kaynagi"), "kota")
        self.assertFalse(self.job(name).meta.get("kota_yedegi"))
        self.assertEqual(self.job(name).meta["model"], "haiku")

    def test_a_limit_after_the_swap_puts_the_model_back_and_tells_nobody(self):
        self.quotas = {"sonnet": self.back()}
        name = self.add()

        def full(job_name):
            raise dispatcher.LimitReached("dolu")
        self.po.dispatcher.start = full
        self.assertEqual(self.po.dispatch(), [])
        rec = records.load(self.durum, name)
        self.assertEqual((rec["model"], rec.get("kota_yedegi")), ("sonnet", ""))
        self.assertEqual(self.job(name).meta["model"], "sonnet")
        self.assertEqual([q for q in self.ceo_queue() if "kotada" in q], [], "nothing started: no notice")

    def test_steps_without_a_claude_session_are_never_swapped(self):
        self.quotas = {"opus": self.back(), "sonnet": self.back()}
        name = self.add()
        for fields in ({"adim_turu": "kod-inceleme", "inceleme_yurutucu": "codex", "model": "opus"},
                       {"adim_turu": "onay", "model": "opus"}):
            records.update(self.durum, name, fields)
            self.assertEqual(self.po.dispatcher._quota_choice(self.job(name), self.quotas), (True, None))
        self.assertFalse(records.load(self.durum, name).get("kota_bekliyor"))

    def test_a_stale_wait_hint_goes_when_the_quota_is_over_even_if_a_limit_holds_the_job(self):
        self.quotas = {"sonnet": self.back(), "opus": self.back()}
        name = self.add()
        self.po.dispatch()
        self.assertTrue(records.load(self.durum, name)["kota_bekliyor"])
        self.cfg["max_running"] = 1
        busy = self.add("kasa", "--katman", "kolay", minute=1)
        jobs.update(self.vault, busy, status="calisiyor")  # the running limit is full now
        self.quotas = {}
        self.assertEqual(self.po.dispatch(), [])
        self.assertFalse(records.load(self.durum, name).get("kota_bekliyor"))

    def test_a_running_job_is_never_moved_to_another_model(self):
        name = self.add()
        self.assertEqual(self.po.dispatch(), [name])
        self.quotas = {"sonnet": self.back()}
        self.po.dispatch()
        self.assertEqual(records.load(self.durum, name)["model"], "sonnet")
        self.assertEqual(len(self.starts()), 1)


if __name__ == "__main__":
    unittest.main()
