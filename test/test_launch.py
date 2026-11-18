"""Tests for bin/launch.py. The real `claude` is never called; a fake script records its arguments."""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakes  # noqa: E402,F401 (isolates the job lock)
import launch  # noqa: E402

# Prints the line `claude --bg` prints; the name is the 3rd argument (--bg --name <name>).
FAKE_CLAUDE = """#!/bin/sh
printf '%s\\0' "$PWD" > "$FAKE_RECORD"
for a in "$@"; do printf '%s\\0' "$a" >> "$FAKE_RECORD"; done
echo "Starting background service…"
echo "backgrounded · abc12345 · $3"
"""


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dev = os.path.join(root, "Dev")
        self.project_dir = os.path.join(self.dev, "blog")
        self.zim = os.path.join(self.dev, "zim")
        self.vault_ofis = os.path.join(root, "vault", "OFIS")
        for d in (self.project_dir, self.zim, os.path.join(self.zim, "alt")):
            os.makedirs(d)
        self.record = os.path.join(root, "argv.txt")
        self.claude = os.path.join(root, "claude")
        self.write_fake(FAKE_CLAUDE)
        os.environ["FAKE_RECORD"] = self.record
        self.cfg = {
            "ceo_session": "ceo-test",
            "vault_ofis": self.vault_ofis,
            "projects": {
                "blog": {"path": self.project_dir, "description": "test"},
                "zim": {"path": self.zim},
                "zimalt": {"path": os.path.join(self.zim, "alt")},
                "yok": {"path": os.path.join(self.dev, "olmayan")},
            },
        }
        self.now = datetime(2026, 11, 10, 16, 30, 5)

    def tearDown(self):
        self.tmp.cleanup()

    def write_fake(self, script):
        with open(self.claude, "w") as f:
            f.write(script)
        os.chmod(self.claude, os.stat(self.claude).st_mode | stat.S_IEXEC)

    def launch(self, project, task="git durumunu özetle", suffix="ab12"):
        return launch.launch(self.cfg, project, task, claude_bin=self.claude, now=self.now, suffix=suffix)

    def argv(self):
        with open(self.record) as f:
            return f.read().split("\0")[:-1]

    def notes(self):
        """Paths of every job note in the three job folders (nothing is written into the flat Isler folder)."""
        out = []
        for folder in ("Siradakiler", "Devam-Edenler", "Bitenler", ""):
            path = os.path.join(self.vault_ofis, "Isler", folder)
            if os.path.isdir(path):
                out += [os.path.join(path, n) for n in os.listdir(path) if n.endswith(".md")]
        return sorted(out)

    def read_note(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    # --- folder trust (2026-11-15) ---

    def trust(self, projects):
        config = os.path.join(self.tmp.name, "claude.json")
        with open(config, "w") as f:
            json.dump({"projects": projects}, f)
        os.environ["OFIS_CLAUDE_JSON"] = config
        self.addCleanup(fakes.isolate_claude_trust)
        return config

    def test_folder_trust_reads_the_folders_own_entry(self):
        real = os.path.realpath(self.project_dir)
        self.trust({real: {"hasTrustDialogAccepted": False}})
        self.assertIs(launch.folder_trusted(self.project_dir), False)
        self.trust({os.path.dirname(real): {"hasTrustDialogAccepted": True}})
        self.assertIs(launch.folder_trusted(self.project_dir), False)  # a trusted parent is not enough
        self.trust({real: {"hasTrustDialogAccepted": True}})
        self.assertIs(launch.folder_trusted(self.project_dir), True)
        os.environ["OFIS_CLAUDE_JSON"] = os.path.join(self.tmp.name, "yok.json")
        self.assertIsNone(launch.folder_trusted(self.project_dir))  # unreadable: claude decides

    def test_an_untrusted_folder_is_refused_before_anything_is_recorded(self):
        self.trust({})
        job = launch.create_job(self.cfg, "blog", "Başlık", {"hedef": "Notun hedefi."}, now=self.now)
        with self.assertRaises(launch.Refused) as e:
            launch.start_job(self.cfg, job.name, claude_bin=self.claude, now=self.now, suffix="ab12")
        self.assertTrue(str(e.exception).startswith(launch.TRUST_REFUSAL))
        self.assertFalse(os.path.exists(self.record))
        self.assertIn("durum: sirada", self.read_note(self.notes()[0]))

    # --- refusals: claude must never be called ---

    def assert_refused_without_launch(self, project, task="git durumunu özetle"):
        with self.assertRaises(launch.Refused):
            self.launch(project, task)
        self.assertFalse(os.path.exists(self.record), "claude must not be called")

    def test_zim_is_refused(self):
        self.assert_refused_without_launch("zim")

    def test_zim_subfolder_is_refused(self):
        self.assert_refused_without_launch("zimalt")

    def test_zim_via_symlink_is_refused(self):
        link_path = os.path.join(self.dev, "innocent")
        os.symlink(self.zim, link_path)
        self.cfg["projects"]["innocent"] = {"path": link_path}
        self.assert_refused_without_launch("innocent")

    def test_zim_name_variants_are_refused(self):
        for i, folder in enumerate(("ZİM", "Zim", "zim-old", "ZIM.bak", "zim_worktree")):
            path = os.path.join(self.tmp.name, f"v{i}", folder)
            os.makedirs(path)
            self.cfg["projects"][f"v{i}"] = {"path": path}
            with self.subTest(folder=folder):
                self.assert_refused_without_launch(f"v{i}")

    def test_zim_lookalike_names_are_allowed(self):
        path = os.path.join(self.dev, "zimbo")
        os.makedirs(path)
        self.cfg["projects"]["zimbo"] = {"path": path}
        self.launch("zimbo")  # does not raise

    def test_unregistered_project_is_refused(self):
        self.assert_refused_without_launch("kayitsiz")

    def test_invalid_project_name_is_refused(self):
        self.assert_refused_without_launch("../zim")

    def test_missing_folder_is_refused(self):
        self.assert_refused_without_launch("yok")

    def test_empty_and_long_task_are_refused(self):
        self.assert_refused_without_launch("blog", "   ")
        self.assert_refused_without_launch("blog", "x" * 4001)

    def test_task_starting_with_dash_is_refused(self):
        for task in ("--add-dir=/Users/x/Dev/zim", "--dangerously-skip-permissions", "  -p hi", "\n--model opus"):
            with self.subTest(task=task):
                self.assert_refused_without_launch("blog", task)

    def test_unwritable_vault_refuses_before_launch(self):
        os.makedirs(os.path.dirname(self.vault_ofis))
        with open(self.vault_ofis, "w") as f:  # a file where the folder should be
            f.write("x")
        self.assert_refused_without_launch("blog")

    # --- successful launch ---

    def test_successful_launch_arguments(self):
        result = self.launch("blog", "git durumunu özetle; $(rm -rf /)")
        lines = self.argv()
        self.assertEqual(os.path.realpath(lines[0]), os.path.realpath(self.project_dir))
        argv = lines[1:]
        self.assertEqual(argv[:3], ["--bg", "--name", "ofis-blog-1110-163005-ab12"])
        contract = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn("'blog'", contract)
        self.assertIn("ofis-blog-1110-163005-ab12", contract)
        self.assertEqual(argv[-1], "git durumunu özetle; $(rm -rf /)",
                         "the task is the last argument, passed as one argument, never through a shell")
        self.assertEqual(result["short_id"], "abc12345")
        self.assertEqual(result["name"], "ofis-blog-1110-163005-ab12")

    def contract(self):
        argv = self.argv()[1:]
        return " ".join(argv[argv.index("--append-system-prompt") + 1].split())

    def test_contract_reports_through_the_inbox_command_with_the_session_name(self):
        # Phase 0: idle background sessions are reaped, so peer messages to the CEO are lost and retries burn tokens.
        self.launch("blog", "x")
        contract = self.contract()
        self.assertIn(f"python3 {launch.OFIS_PY} bildir --oturum ofis-blog-1110-163005-ab12 "
                      "--tur bitti - <<'OFIS_RAPOR'", contract)
        self.assertIn("[Ofis · Sahibin cevabı]", contract)
        self.assertIn("[Ofis · Sahibin duyurusu]", contract)
        # plan "2. Aşama": the tokens are neutral, only the name is the owner's (neither the old-protocol head nor one
        # with the configured name)
        self.assertNotIn("[Ofis · Deniz'in", contract)
        self.assertNotIn("[Ofis · Selin'in", contract)
        # answers already queued in durum/giden may still carry the old heads: generic, never a hardcoded name
        self.assertIn("Older messages may carry the owner's name in place of \"Sahibin\" (\"[Ofis · <name>'in cevabı]\", "
                      "\"[Ofis · <name>'in duyurusu]\"): they mean exactly the same as the two heads above.", contract)
        self.assertIn("the office (Ofis) of Selin, its owner", contract)  # the tests' owner (test/sahip_yasaklari.py)
        self.assertIn("end your turn and wait", contract)
        self.assertNotIn("30 seconds", contract)
        self.assertNotIn("up to 5 times", contract)

    def test_contract_keeps_the_work_in_the_given_folder(self):
        # Live trial 2026-11-11: a kod session made its own git worktree, so the server-run Kontrol (in the job's
        # folder) could never see the change, and the session then hung on a permission prompt.
        self.launch("blog", "x")
        contract = self.contract()
        self.assertIn("Work directly in your current working folder", contract)
        self.assertIn("never create a git worktree", contract)

    def test_contract_documents_only_the_quoted_heredoc_and_no_lossy_fallback(self):
        # Review finding 6: a double-quoted "<metin>" runs `command substitution`; ending the turn with the report as
        # final text loses it (nobody reads a project session's final text).
        self.launch("blog", "x")
        raw = self.argv()[1:]
        raw = raw[raw.index("--append-system-prompt") + 1]
        self.assertIn("<<'OFIS_RAPOR'\n", raw)
        self.assertIn("\nOFIS_RAPOR\n", raw, "the terminator stands alone at the start of its line")
        self.assertNotIn('"<metin>"', raw)
        self.assertNotIn("final text", raw)
        self.assertIn("run it once more", raw)
        self.assertIn("BİLDİRİM BAŞARISIZ", raw)

    def test_start_job_sends_a_given_task_instead_of_the_note(self):
        # phase 4: a workflow step's prompt is built by bin/akis.py from trusted data, not from the note
        job = launch.create_job(self.cfg, "blog", "Başlık", {"hedef": "Notun hedefi."}, now=self.now)
        launch.start_job(self.cfg, job.name, claude_bin=self.claude, suffix="ab12", now=self.now,
                         task="Akıştan gelen istem.")
        self.assertEqual(self.argv()[-1], "Akıştan gelen istem.")
        other = launch.create_job(self.cfg, "blog", "B", {"hedef": "x"}, now=self.now)
        with self.assertRaises(launch.Refused):
            launch.start_job(self.cfg, other.name, claude_bin=self.claude, task="-p evil")

    def test_a_job_starts_in_a_folder_that_is_not_a_git_repository(self):
        # the Ar-Ge workspace ~/Dev/ofis-arge is a plain folder (owner decision 2026-11-12): no base commit, no git state, and
        # the job still starts in that very folder with the usual contract
        import records
        arge = os.path.join(self.dev, "ofis-arge")
        os.makedirs(arge)
        with open(os.path.join(arge, "README.md"), "w") as f:
            f.write("# ofis-arge\n")
        self.cfg["projects"]["arge"] = {"path": arge, "description": "Ar-Ge", "notes": "Read-only research."}
        durum = os.path.join(self.tmp.name, "durum")
        self.assertEqual(launch.git_head(arge), "")
        job = launch.create_job(self.cfg, "arge", "Günlük Ar-Ge", {"hedef": "Araştır."}, tier="genel", now=self.now)
        out = launch.start_job(self.cfg, job.name, claude_bin=self.claude, suffix="ab12", now=self.now,
                               durum_dir=durum)
        self.assertEqual(out["name"], "ofis-arge-1110-163005-ab12")
        argv = self.argv()
        self.assertEqual(os.path.realpath(argv[0]), os.path.realpath(arge))  # claude ran in the folder itself
        rec = records.load(durum, job.name)
        self.assertEqual((rec["proje"], rec["taban_commit"]), ("arge", ""))
        self.assertEqual(os.path.realpath(rec["calisma_dizini"]), os.path.realpath(arge))
        for key in ("taban_kirli", "taban_kirli_durum", "taban_git_ozet"):
            self.assertNotIn(key, rec)
        note = self.read_note(self.notes()[0])
        self.assertIn("durum: calisiyor", note)  # the fake claude confirmed the start
        self.assertNotIn("taban_commit:", note)  # an empty value is not written

    def test_project_session_is_denied_the_ceo_commands_and_the_office_files(self):
        # Review finding 7: a project session must not answer, start, add, finish or cancel jobs, nor edit the office.
        self.launch("blog", "x")
        argv = self.argv()[1:]
        i = argv.index("--disallowedTools")
        rules = []
        for a in argv[i + 1:]:
            if a.startswith("--"):
                break
            rules.append(a)
        root = "//" + launch.ROOT.lstrip("/")
        vault = "//" + os.path.realpath(self.vault_ofis).lstrip("/")
        expected = [f"Edit({root}/**)", f"Write({root}/**)", f"Edit({vault}/**)", f"Write({vault}/**)"] + [
            f"Bash(python3 {launch.OFIS_PY} {cmd}:*)" for cmd in ("cevapla", "baslat", "ekle", "bitir", "iptal", "butce", "devam",
                                                                      "serbest", "bagimli", "akis",
                                                                      "akis-karar", "zamanla", "duyuru", "deneme-isaretle",
                                                                      "danisman-pilotu", "yakala", "hafiza-saglik",
                                                                      "talimat-denetimi", "sor", "ceo-yenile")] + ["EnterWorktree"]
        self.assertEqual(rules, expected)
        self.assertTrue(argv[i + 1 + len(rules)].startswith("--"), "the variadic list is closed by another option")
        self.assertEqual(argv[-1], "x")

    def test_the_vault_is_denied_by_its_real_path_too(self):
        # Phase 2 review finding 1a: limits, short id and folder are on the vault note; a session may not edit it.
        link = os.path.join(self.tmp.name, "kasa-link")
        os.makedirs(self.vault_ofis, exist_ok=True)
        os.symlink(self.vault_ofis, link)
        rules = launch.deny_rules(link)
        real = "//" + os.path.realpath(self.vault_ofis).lstrip("/")
        self.assertIn(f"Edit({real}/**)", rules)
        self.assertIn(f"Write({real}/**)", rules)

    def test_the_docstring_lists_every_denied_command(self):
        # Phase 2 review finding 11
        for cmd in launch.DENIED_COMMANDS:
            self.assertIn(cmd, launch.__doc__.split("--disallowedTools denies")[1].split("session_flags()")[0], cmd)

    def test_launch_timeout_keeps_the_job_starting_with_an_unconfirmed_note(self):
        # Review finding 12: the session may be running; a later report from it must still apply.
        self.write_fake("#!/bin/sh\nexec sleep 5\n")
        old, launch.LAUNCH_TIMEOUT = launch.LAUNCH_TIMEOUT, 0.5
        try:
            with self.assertRaises(launch.Refused) as ctx:
                self.launch("blog")
        finally:
            launch.LAUNCH_TIMEOUT = old
        self.assertIn("unconfirmed", str(ctx.exception))
        [path] = self.notes()
        self.assertEqual(os.path.basename(os.path.dirname(path)), "Devam-Edenler")
        text = self.read_note(path)
        self.assertIn("durum: baslatiliyor", text)
        self.assertIn("Başlatma doğrulanamadı", text)
        self.assertNotIn("bitis:", text)

    def test_contract_keeps_turkish_no_secrets_and_no_commit_rules(self):
        self.launch("blog", "x")
        contract = self.contract()
        self.assertIn("in Turkish", contract)
        self.assertIn("Never put secrets", contract)
        self.assertIn("Never commit or push", contract)

    def test_contract_explains_the_kontrol_failure_and_devam_messages(self):
        self.launch("blog", "x")
        contract = self.contract()
        self.assertIn("[Ofis · kontrol başarısız]", contract)
        self.assertIn("[Ofis · devam]", contract)

    def test_a_kod_jobs_contract_asks_for_its_decisions_and_assumptions(self):
        # "önce kanıt" (plan, 2026-11-11): the kod session lists the decisions it took on its own in its bitti report
        tiers = {"kod": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet"}}
        self.cfg.update(tiers=tiers, default_tier="genel")
        job = launch.create_job(self.cfg, "blog", "Giriş", {"hedef": "Düzelt.", "kontrol": "pytest -q"},
                                tier="kod", now=self.now)
        launch.start_job(self.cfg, job.name, claude_bin=self.claude, now=self.now, suffix="ab12")
        contract = self.contract()
        self.assertIn("Verdiğim kararlar ve varsayımlar", contract)
        for part in ("defaults you chose", "out of scope", "conflicted"):
            self.assertIn(part, contract)
        # Step 3 (owner decision 2026-11-13): parallel helpers inside a kod job — at most 3, separate files, the session merges
        # and tests, helpers never commit, push or delete
        for part in ("at most 3 helpers", "own separate files", "run the tests yourself", "never commit, push or delete"):
            self.assertIn(part, contract)
        for part in ("in every helper's prompt", "no worktree isolation", "stash, reset or checkout",
                     "run no ofis.py command"):
            self.assertIn(part, contract)
        for tier in ("genel", "inceleme", "planlama", "kolay", None):
            self.assertNotIn("at most 3 helpers", launch.contract("blog", "ofis-x", tier))
        self.assertNotIn("Verdiğim kararlar", launch.contract("blog", "ofis-x", "genel"))
        self.assertNotIn("Verdiğim kararlar", launch.contract("blog", "ofis-x"))
        # every resume carries the same contract (the tier comes from the job)
        resumed = launch.resume_flags(launch.jobs.load(self.vault_ofis, job.name), self.vault_ofis)
        self.assertIn("Verdiğim kararlar ve varsayımlar", resumed[resumed.index("--append-system-prompt") + 1])
        genel = launch.create_job(self.cfg, "blog", "Özet", {"hedef": "Özetle."}, now=self.now)
        self.launch("blog", "x")
        self.assertNotIn("Verdiğim kararlar", self.contract())
        self.assertEqual(genel.meta["katman"], "genel")

    def test_the_contract_carries_the_project_rules_at_start_and_resume(self):
        # plan "Sonraki iş (7)" (owner decision 2026-11-12): the project's rules and the sorumlu sections, planning a summary
        tiers = {"planlama": {"model": "fable", "effort": "high"}, "genel": {"model": "sonnet"}}
        self.cfg.update(tiers=tiers, default_tier="genel")
        self.cfg["projects"]["blog"]["notes"] = "Never ship ads."
        job = launch.create_job(self.cfg, "blog", "Plan", {"hedef": "Planla."}, tier="planlama", now=self.now)
        launch.start_job(self.cfg, job.name, claude_bin=self.claude, now=self.now, suffix="ab12")
        contract = self.contract()
        for need in ("Proje kuralları", "Never ship ads.", "Asla yapmaz", "Proje özeti"):
            self.assertIn(need, contract)
        resumed = launch.resume_flags(launch.jobs.load(self.vault_ofis, job.name), self.vault_ofis, cfg=self.cfg)
        text = resumed[resumed.index("--append-system-prompt") + 1]
        self.assertIn("Never ship ads.", text)
        self.assertIn("Proje özeti", text)
        genel = launch.create_job(self.cfg, "blog", "Özet", {"hedef": "Özetle."}, now=self.now)
        launch.start_job(self.cfg, genel.name, claude_bin=self.claude, now=self.now, suffix="cd34")
        self.assertIn("Never ship ads.", self.contract())
        self.assertNotIn("Proje özeti", self.contract())

    # --- specialisation (plan "Sonraki iş (9)", step 2) ---

    def test_create_job_routes_the_specialisation_onto_the_record_and_the_note(self):
        import records
        durum = os.path.join(self.tmp.name, "durum")
        self.cfg.update(tiers={"kod": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet"}},
                        default_tier="genel")
        open(os.path.join(self.project_dir, "pubspec.yaml"), "w").close()
        job = launch.create_job(self.cfg, "blog", "Giriş", {"hedef": "lib/login.dart hatasını düzelt",
                                                                "kontrol": "flutter test"},
                                tier="kod", now=self.now, durum_dir=durum)
        rec = records.load(durum, job.name)
        self.assertEqual((rec["uzmanlik"], rec["uzmanlik_kaynagi"]), ("mobil", "kural"))
        self.assertIn("lib/login.dart", rec["uzmanlik_nedeni"])
        self.assertEqual(job.meta["uzmanlik"], "mobil")
        # a plain job without signals: genel, "belirsiz"
        other = launch.create_job(self.cfg, "blog", "Özet", {"hedef": "Durumu özetle."}, now=self.now,
                                  durum_dir=durum)
        self.assertEqual(records.load(durum, other.name)["uzmanlik"], "genel")
        self.assertIn("belirsiz", records.load(durum, other.name)["uzmanlik_nedeni"])

    def test_an_explicit_specialisation_wins_and_an_unknown_one_is_refused(self):
        import records
        durum = os.path.join(self.tmp.name, "durum")
        job = launch.create_job(self.cfg, "blog", "Giriş", {"hedef": "lib/login.dart"}, now=self.now,
                                durum_dir=durum, uzmanlik="ui")
        rec = records.load(durum, job.name)
        self.assertEqual((rec["uzmanlik"], rec["uzmanlik_kaynagi"]), ("ui", "elle"))
        with self.assertRaises(launch.Refused) as cm:
            launch.create_job(self.cfg, "blog", "Giriş", {"hedef": "x"}, now=self.now, durum_dir=durum,
                              uzmanlik="devops")
        self.assertIn("bilinmeyen uzmanlık", str(cm.exception))
        self.assertEqual(len(self.notes()), 1)

    def test_the_role_section_is_in_the_contract_at_start_and_resume(self):
        durum = os.path.join(self.tmp.name, "durum")
        self.cfg.update(tiers={"kod": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet"}},
                        default_tier="genel")
        job = launch.create_job(self.cfg, "blog", "Uç", {"hedef": "backend/src/OrderController.java ekle",
                                                             "kontrol": "mvn -q test"},
                                tier="kod", now=self.now, durum_dir=durum)
        launch.start_job(self.cfg, job.name, claude_bin=self.claude, now=self.now, suffix="ab12", durum_dir=durum)
        contract = self.contract()
        self.assertIn("Rolün: Kıdemli Backend", contract)
        self.assertIn("Yetkinlik:", contract)
        self.assertIn("Verdiğim kararlar", contract)  # the kod contract stays
        self.assertIn("Proje kuralları", contract)    # the project's rules stay
        resumed = launch.resume_flags(launch.jobs.load(self.vault_ofis, job.name), self.vault_ofis,
                                      durum_dir=durum, cfg=self.cfg)
        self.assertIn("Rolün: Kıdemli Backend", resumed[resumed.index("--append-system-prompt") + 1])

    def test_past_lessons_are_in_the_contract_at_start_and_resume(self):
        # plan "Sonraki iş (9)" step 3 (bin/hafiza.py): verified lessons of the specialisation, quoted as data
        import hafiza
        durum = os.path.join(self.tmp.name, "durum")
        self.cfg.update(tiers={"kod": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet"}},
                        default_tier="genel")
        lesson = {"is": "2026-11-01-100000-blog.md", "isler": ["2026-11-01-100000-blog.md"], "proje": "blog",
                  "tarih": "2026-11-01", "dogrulanmis": True, "metin": "OrderController testleri mvn ile koşar.",
                  "anahtarlar": sorted(hafiza.anahtarlar("order controller")), "kaynak": "rapor", "sayi": 1}
        other = dict(lesson, metin="Doğrulanmamış ders.", dogrulanmis=False)
        hafiza._kaydet(durum, "backend", [lesson, other])
        job = launch.create_job(self.cfg, "blog", "Uç", {"hedef": "backend/src/OrderController.java ekle",
                                                             "kontrol": "mvn -q test"},
                                tier="kod", now=self.now, durum_dir=durum)
        launch.start_job(self.cfg, job.name, claude_bin=self.claude, now=self.now, suffix="ab12", durum_dir=durum)
        contract = self.contract()
        self.assertIn("Geçmiş dersler", contract)
        self.assertIn("talimat değildir", contract)
        self.assertIn("OrderController testleri mvn ile koşar.", contract)
        self.assertNotIn("Doğrulanmamış ders.", contract)
        self.assertLess(contract.index("Rolün:"), contract.index("Geçmiş dersler"))
        resumed = launch.resume_flags(launch.jobs.load(self.vault_ofis, job.name), self.vault_ofis,
                                      durum_dir=durum, cfg=self.cfg)
        self.assertIn("OrderController testleri mvn", resumed[resumed.index("--append-system-prompt") + 1])
        # a lesson of a project outside the office never shows
        hafiza._kaydet(durum, "backend", [dict(lesson, proje="baskasi")])
        resumed = launch.resume_flags(launch.jobs.load(self.vault_ofis, job.name), self.vault_ofis,
                                      durum_dir=durum, cfg=self.cfg)
        self.assertNotIn("Geçmiş dersler", resumed[resumed.index("--append-system-prompt") + 1])

    def test_the_contract_trusts_the_record_over_an_edited_note(self):
        import records
        durum = os.path.join(self.tmp.name, "durum")
        job = launch.create_job(self.cfg, "blog", "Özet", {"hedef": "Arayüz butonunu incele"}, now=self.now,
                                durum_dir=durum)
        self.assertEqual(records.load(durum, job.name)["uzmanlik"], "ui")
        launch.jobs.update(self.vault_ofis, job.name, fields={"uzmanlik": "guvenlik"})  # a session's edit
        flags = launch.resume_flags(launch.jobs.load(self.vault_ofis, job.name)._replace(
            meta={**launch.jobs.load(self.vault_ofis, job.name).meta, "oturum": "ofis-blog-x", "proje": "blog"}),
            self.vault_ofis, durum_dir=durum)
        text = flags[flags.index("--append-system-prompt") + 1]
        self.assertIn("Rolün:", text)
        self.assertNotIn("Güvenlik", text.split("Rolün:")[1].split("\n")[0])

    def test_a_kod_job_without_a_kontrol_is_refused(self):
        tiers = {"kod": {"model": "opus", "effort": "high"}, "genel": {"model": "sonnet"}}
        self.cfg.update(tiers=tiers, default_tier="genel")
        for brief in ({"hedef": "Düzelt."}, {"hedef": "Düzelt.", "kontrol": "  "}):
            with self.assertRaises(launch.Refused) as cm:
                launch.create_job(self.cfg, "blog", "Giriş", brief, tier="kod", now=self.now)
            self.assertIn("kod işi kontrolsüz başlatılamaz", str(cm.exception))
        self.assertEqual(self.notes(), [])
        job = launch.create_job(self.cfg, "blog", "Giriş", {"hedef": "Düzelt.", "kontrol": "pytest -q"},
                                tier="kod", now=self.now)
        self.assertEqual((job.meta["katman"], job.meta["effort"]), ("kod", "high"))

    def test_the_call_limit_comes_from_the_tier(self):
        self.cfg.update(tiers={"kolay": {"model": "haiku"}, "genel": {"model": "sonnet"}}, default_tier="genel",
                        default_max_calls={"kolay": 15, "genel": 40})
        kolay = launch.create_job(self.cfg, "blog", "a", {"hedef": "a"}, tier="kolay", now=self.now)
        genel = launch.create_job(self.cfg, "blog", "b", {"hedef": "b"}, now=self.now)
        self.assertEqual((kolay.meta["max_cagri"], genel.meta["max_cagri"]), ("15", "40"))
        del self.cfg["default_max_calls"]
        other = launch.create_job(self.cfg, "blog", "c", {"hedef": "c"}, now=self.now)
        self.assertNotIn("max_cagri", other.meta)

    def test_the_settings_template_has_tier_efforts_and_call_limits(self):
        cfg = launch.load(launch.EXAMPLE_CONFIG)
        self.assertEqual({t: (v.get("model"), v.get("effort")) for t, v in cfg["tiers"].items()},
                         {"kolay": ("haiku", "low"), "genel": ("sonnet", "medium"), "kod": ("opus", "high"),
                          "inceleme": ("opus", "high"), "planlama": ("fable", "high")})
        self.assertEqual(cfg["default_max_calls"],
                         {"kolay": 15, "genel": 40, "kod": 120, "inceleme": 60, "planlama": 60})

    def test_session_names_are_unique_within_a_second(self):
        first = launch.launch(self.cfg, "blog", "a", claude_bin=self.claude, now=self.now)["name"]
        second = launch.launch(self.cfg, "blog", "b", claude_bin=self.claude, now=self.now)["name"]
        self.assertNotEqual(first, second)
        for name in (first, second):
            self.assertRegex(name, r"^ofis-blog-1110-163005-[0-9a-f]{4}$")

    def test_task_note_is_written_to_vault(self):
        note_path = self.launch("blog")["note"]
        self.assertEqual(os.path.dirname(note_path), os.path.join(self.vault_ofis, "Isler", "Devam-Edenler"))
        content = self.read_note(note_path)
        for expected in ("proje: blog", "oturum: ofis-blog-1110-163005-ab12", "kisa_id: abc12345",
                         "durum: calisiyor", "git durumunu özetle"):
            self.assertIn(expected, content)
        self.assertNotIn("baslatiliyor", content)

    def test_second_note_in_same_second_does_not_overwrite(self):
        first = self.launch("blog", suffix="aaaa")["note"]
        second = self.launch("blog", suffix="bbbb")["note"]
        self.assertNotEqual(first, second)
        self.assertIn("ofis-blog-1110-163005-aaaa", self.read_note(first))
        self.assertIn("ofis-blog-1110-163005-bbbb", self.read_note(second))

    # --- failed or ambiguous launch is recorded, never silently lost ---

    def test_unexpected_claude_output_marks_note_failed(self):
        self.write_fake("#!/bin/sh\necho 'beklenmedik'\n")
        with self.assertRaises(launch.Refused):
            self.launch("blog")
        [note] = self.notes()
        self.assertIn(os.sep + "Bitenler" + os.sep, note)
        content = self.read_note(note)
        self.assertIn("durum: basarisiz", content)
        self.assertIn("beklenmedik", content)

    def test_claude_exit_code_marks_note_failed(self):
        self.write_fake("#!/bin/sh\necho 'boom' >&2\nexit 3\n")
        with self.assertRaises(launch.Refused):
            self.launch("blog")
        [note] = self.notes()
        self.assertIn("durum: basarisiz", self.read_note(note))

    def test_output_with_other_session_name_is_refused(self):
        self.write_fake("#!/bin/sh\necho 'backgrounded · abc12345 · someone-else'\n")
        with self.assertRaises(launch.Refused) as ctx:
            self.launch("blog")
        self.assertIn("someone-else", str(ctx.exception))

    def test_output_pattern_on_stderr_is_ignored(self):
        self.write_fake("#!/bin/sh\necho \"backgrounded · abc12345 · $3\" >&2\n")
        with self.assertRaises(launch.Refused):
            self.launch("blog")

    def test_malformed_short_id_is_refused(self):
        self.write_fake("#!/bin/sh\necho \"backgrounded · ab;c:\\ndurum · $3\"\n")
        with self.assertRaises(launch.Refused):
            self.launch("blog")

    # --- model, effort, worktree, permission mode (phase 0/1) ---

    def test_options_are_passed_before_the_task(self):
        result = launch.launch(self.cfg, "blog", "test yaz", claude_bin=self.claude, now=self.now, suffix="ab12",
                               model="sonnet", effort="low", worktree=True, permission_mode="acceptEdits")
        argv = self.argv()[1:]
        self.assertEqual(argv[-1], "test yaz")
        for flag, value in (("--model", "sonnet"), ("--effort", "low"), ("--permission-mode", "acceptEdits"),
                            ("--worktree", "ofis-blog-1110-163005-ab12")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        content = self.read_note(result["note"])
        for expected in ("model: sonnet", "effort: low", "worktree: ofis-blog-1110-163005-ab12",
                         "izin_modu: acceptEdits"):
            self.assertIn(expected, content)

    def test_defaults_add_no_flags(self):
        self.launch("blog")
        argv = self.argv()[1:]
        for flag in ("--model", "--effort", "--worktree", "--permission-mode"):
            self.assertNotIn(flag, argv)

    def test_sessions_edit_their_own_folder_without_a_worktree(self):
        # Live trial 2026-11-12: Claude Code's background isolation refused Edit/Write in the main checkout until the
        # session entered a worktree (which the contract forbids), so the kod session fell back to shell heredocs.
        # The owner approved (2026-11-12) turning that isolation off for office sessions only (worktree.bgIsolation none).
        import json as _json
        flags = launch.session_flags("blog", "ofis-blog-x")
        self.assertIn("--settings", flags)
        self.assertEqual(_json.loads(flags[flags.index("--settings") + 1]), {"worktree": {"bgIsolation": "none"}})
        # it comes before the variadic --disallowedTools list, so it is never read as a rule
        self.assertLess(flags.index("--settings"), flags.index("--disallowedTools"))

    def test_bad_options_are_refused_before_launch(self):
        for kwargs in ({"model": "--dangerously-skip-permissions"}, {"model": "opus; rm"}, {"model": ""},
                       {"effort": "ultra"}, {"permission_mode": "bypassPermissions"}, {"permission_mode": "yolo"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(launch.Refused):
                    launch.launch(self.cfg, "blog", "x", claude_bin=self.claude, now=self.now, **kwargs)
                self.assertFalse(os.path.exists(self.record))

    def test_cli_parses_options(self):
        args = launch.parse_args(["blog", "görev", "--model", "haiku", "--effort", "low", "--worktree",
                                  "--permission-mode", "auto"])
        self.assertEqual((args.project, args.task, args.model, args.effort, args.worktree, args.permission_mode),
                         ("blog", "görev", "haiku", "low", True, "auto"))

    def test_config_file_is_loaded(self):
        path = os.path.join(self.tmp.name, "ofis.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f)
        self.assertEqual(launch.load(path)["ceo_session"], "ceo-test")

    def test_a_config_that_is_not_an_object_is_a_clear_refusal(self):
        path = os.path.join(self.tmp.name, "ofis.json")
        for text in ("null", "[]", '"x"', "3"):
            with self.subTest(text=text):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                with self.assertRaises(launch.Refused):
                    launch.load(path)

    def test_invalid_json_is_a_clear_refusal_naming_the_line(self):
        path = os.path.join(self.tmp.name, "ofis.json")
        for text, line in (('{\n  "ceo_session": "x",\n  "projects": {,\n}', 3), ("", 1), ("{bozuk", 1)):
            with self.subTest(text=text):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                with self.assertRaises(launch.Refused) as ctx:
                    launch.load(path)
                msg = str(ctx.exception)
                self.assertTrue(msg.startswith(f"ofis.json okunamadı: geçerli JSON değil (satır {line},"), msg)
                self.assertIn("düzelt", msg)

    def test_a_file_that_is_not_utf8_is_a_clear_refusal(self):
        path = os.path.join(self.tmp.name, "ofis.json")
        with open(path, "wb") as f:
            f.write(b'{"ceo_session": "\xff"}')
        with self.assertRaises(launch.Refused) as ctx:
            launch.load(path)
        self.assertIn("ofis.json okunamadı", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
