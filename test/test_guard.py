"""Tests for bin/guard.py, the CEO's PreToolUse hook. Exit 2 = blocked, exit 0 = allowed."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "guard.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config, test/sahip_yasaklari.py)

# This checkout and the vault the guard protects by default (bin/guard.py DEFAULT_VAULT): derived, never one machine's.
ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HOME = os.path.expanduser("~")
VAULT = os.path.join(HOME, "Documents", "Obsidian Vault")


def run(tool_name, tool_input):
    proc = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps({"tool_name": tool_name,
                          "tool_input": tool_input}), capture_output=True, text=True, timeout=10)
    return proc.returncode, proc.stderr


class GuardTest(unittest.TestCase):
    def assert_blocked(self, tool, tool_input):
        code, err = run(tool, tool_input)
        self.assertEqual(code, 2, f"expected block for {tool} {tool_input}")
        self.assertTrue(err.strip(), "a block must explain itself on stderr")

    def assert_allowed(self, tool, tool_input):
        code, err = run(tool, tool_input)
        self.assertEqual(code, 0, f"expected allow for {tool} {tool_input}: {err}")

    def test_bash_routes_to_zim_are_blocked(self):
        for cmd in ("git -C /Users/ornek/dev/zim log", "git -C ~/Dev/zim show", "cd ~/Dev/zim && git show",
                    "cd $HOME/Dev/ZIM; ls", "python3 -c \"open('/Users/ornek/Dev/zim/x')\"",
                    "ls ~/Dev/ZİM", "cat ~/Dev/zim-old/README.md", "ls '/Users/ornek/Documents/Obsidian Vault/ZIM'"):
            with self.subTest(cmd=cmd):
                self.assert_blocked("Bash", {"command": cmd})

    def test_password_files_are_blocked(self):
        self.assert_blocked("Bash", {"command": "cat '/Users/ornek/Documents/Obsidian Vault/E commint/Email Şifre.md'"})
        self.assert_blocked("Read", {"file_path": VAULT + "/Marbaş/Şifre ve kullanıcı.md"})
        self.assert_blocked("Read", {"file_path": "/x/SC/ŞİFRELER VE KULLANICILAR/a.md"})
        self.assert_blocked("Grep", {"pattern": "token", "path": "/x/ORNEK/Şifreler"})

    def test_private_vault_folders_are_blocked(self):
        for folder in ("Mektuplar", "TAPU", "SİGORTA"):
            with self.subTest(folder=folder):
                self.assert_blocked("Write", {"file_path": f"{VAULT}/{folder}/yeni.md",
                                              "content": "x"})

    def test_zim_file_paths_are_blocked(self):
        self.assert_blocked("Read", {"file_path": "/Users/ornek/Dev/zim/pom.xml"})
        self.assert_blocked("Glob", {"pattern": "**/*.md", "path": VAULT + "/ZIM"})
        self.assert_blocked("Edit", {"file_path": "/Users/ornek/dev/ZIM/x", "old_string": "a", "new_string": "b"})

    def test_manual_background_launch_is_blocked(self):
        for cmd in ("claude --bg --name x 'do it'", "cd ~/Dev/blog && claude --background hi",
                    "/Users/ornek/.local/bin/claude --bg x"):
            with self.subTest(cmd=cmd):
                self.assert_blocked("Bash", {"command": cmd})

    def test_server_trusted_records_are_blocked(self):
        root = ROOT
        for tool, ti in (("Write", {"file_path": f"{root}/durum/kontroller/x.md.json", "content": "{}"}),
                         ("Edit", {"file_path": f"{root}/durum/isler/x.md.json", "old_string": "a", "new_string": "b"}),
                         ("Bash", {"command": f"echo '{{}}' > {root}/durum/kontroller/x.md.json"}),
                         ("Bash", {"command": "cd durum && sed -i '' s/a/b/ isler/x.md.json"}),
                         ("Bash", {"command": "rm durum/kontroller/x.md.pid"}),
                         ("NotebookEdit", {"notebook_path": f"{root}/durum/kontroller/n.ipynb"})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)

    def test_workflow_records_are_blocked(self):
        # The owner's decision (2026-11-11): workflow state/outputs and the server info file are trusted records too.
        root = ROOT
        for tool, ti in (("Write", {"file_path": f"{root}/durum/akislar/akis-1/01-kod.md", "content": "x"}),
                         ("Edit", {"file_path": f"{root}/durum/akislar/sayac.json", "old_string": "1", "new_string": "9"}),
                         ("Write", {"file_path": f"{root}/durum/sunucu.json", "content": "{}"}),
                         ("Bash", {"command": "echo '{}' > durum/akislar/sayac.json"}),
                         ("Bash", {"command": "rm durum/sunucu.json"}),
                         ("Bash", {"command": "cd durum && rm -r akislar/akis-1"}),
                         ("Bash", {"command": "cd durum; echo x > sunucu.json"})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)

    def test_schedule_records_are_blocked(self):
        # The owner's decision (2026-11-11): schedule definitions change only through `ofis.py zamanla`.
        root = ROOT
        for tool, ti in (("Write", {"file_path": f"{root}/durum/zamanlanmis/sabah.json", "content": "{}"}),
                         ("Edit", {"file_path": f"{root}/durum/zamanlanmis/sabah.json", "old_string": "a", "new_string": "b"}),
                         ("Write", {"file_path": f"{root}/durum/taslak/../zamanlanmis/x.json", "content": "{}"}),
                         ("Bash", {"command": "echo '{}' > durum/zamanlanmis/sabah.json"}),
                         ("Bash", {"command": "cd durum && rm zamanlanmis/sabah.json"})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)

    def test_model_selection_records_are_blocked(self):
        # Decision 2026-11-11: proposal/pilot state changes only through the server and `ofis.py cevapla`.
        root = ROOT
        for tool, ti in (("Write", {"file_path": f"{root}/durum/model_secimi/blog__kolay.json", "content": "{}"}),
                         ("Edit", {"file_path": f"{root}/durum/model_secimi/blog__kolay.json", "old_string": "a", "new_string": "b"}),
                         ("Write", {"file_path": f"{root}/durum/taslak/../model_secimi/x.json", "content": "{}"}),
                         ("Bash", {"command": "echo '{}' > durum/model_secimi/blog__kolay.json"}),
                         ("Bash", {"command": "cd durum && rm model_secimi/blog__kolay.json"})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py modeller"})
        self.assert_allowed("Read", {"file_path": f"{root}/durum/model_secimi/blog__kolay.json"})

    def test_announcement_records_are_blocked(self):
        # Owner decision 2026-11-12 (plan "Sonraki iş (4)"): an unexpired announcement goes into every project session's
        # contract, so its trusted record changes only through `ofis.py duyuru` and the page's POST /api/duyuru.
        root = ROOT
        rec = f"{root}/durum/duyurular/20261112-100000-ab12.json"
        for tool, ti in (("Write", {"file_path": rec, "content": "{}"}),
                         ("Edit", {"file_path": rec, "old_string": "a", "new_string": "b"}),
                         ("Write", {"file_path": f"{root}/durum/taslak/../duyurular/x.json", "content": "{}"}),
                         ("Write", {"file_path": f"{root}/durum//duyurular/x.json", "content": "{}"}),
                         ("Bash", {"command": "echo '{}' > durum/duyurular/20261112-100000-ab12.json"}),
                         ("Bash", {"command": "sed -i '' s/a/b/ durum/duyurular/x.json"}),
                         ("Bash", {"command": "cd durum && rm duyurular/20261112-100000-ab12.json"}),
                         ("Bash", {"command": "python3 -c \"open('durum/duyurular/x.json','w')\""})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py duyuru --dosya durum/taslak/duyuru-1.txt --sure bugun"})
        self.assert_allowed("Read", {"file_path": rec})
        self.assert_allowed("Write", {"file_path": f"{root}/durum/taslak/duyuru-1.txt", "content": "Merhaba"})

    def test_domain_cache_is_blocked(self):
        # The owner, 2026-11-12: the Sunucu odası's domain cache drives the CEO notices ("<domain> açılmıyor", "DNS
        # değişti"), so only the server's DomainKontrol writes it (from Python, which the guard never sees).
        root = ROOT
        rec = f"{root}/durum/sistem/domainler.json"
        for tool, ti in (("Write", {"file_path": rec, "content": "{}"}),
                         ("Edit", {"file_path": rec, "old_string": "a", "new_string": "b"}),
                         ("Write", {"file_path": f"{root}/durum/taslak/../sistem/domainler.json", "content": "{}"}),
                         ("Write", {"file_path": f"{root}/durum//sistem/domainler.json", "content": "{}"}),
                         ("Write", {"file_path": f"{root}/durum/sistem", "content": "{}"}),
                         ("Bash", {"command": "echo '{}' > durum/sistem/domainler.json"}),
                         ("Bash", {"command": "rm -rf durum/sistem"}),
                         ("Bash", {"command": "sed -i '' s/a/b/ durum//sistem/domainler.json"}),
                         ("Bash", {"command": "cd durum && rm sistem/domainler.json"}),
                         ("Bash", {"command": "python3 -c \"open('durum/sistem/domainler.json','w')\""})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)
        self.assert_allowed("Read", {"file_path": rec})
        # The module and its tests share the word but are not the cache.
        for tool, ti in (("Edit", {"file_path": f"{root}/bin/sistem.py", "old_string": "a", "new_string": "b"}),
                         ("Write", {"file_path": f"{root}/test/test_sistem.py", "content": "x"}),
                         ("Write", {"file_path": f"{root}/durum/sistemler.json", "content": "{}"}),
                         ("Write", {"file_path": f"{root}/durum/taslak/sistem.txt", "content": "x"}),
                         ("Bash", {"command": "nice -n 10 python3 -I test/test_sistem.py"}),
                         ("Bash", {"command": "python3 -I bin/sistem.py ozet"}),
                         ("Bash", {"command": "cd durum && cat taslak/a.txt; python3 ../bin/sistem.py"}),
                         ("Bash", {"command": "git diff -- bin/sistem.py test/test_sistem.py"})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_allowed(tool, ti)

    def test_schedule_commands_and_notes_allowed(self):
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py zamanla listele"})
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py zamanla ekle --brief-dosya durum/taslak/z.json"})
        self.assert_allowed("Read", {"file_path": ROOT + "/durum/zamanlanmis/sabah.json"})
        self.assert_allowed("Bash", {"command": "cat \"$V\"/OFIS/Zamanlanmis/sabah.md"})

    def test_odd_path_spellings_are_blocked(self):
        # Review 2026-11-11: doubled slashes, ./ and ../ segments and `cd durum/<sub>` slipped past the rules.
        root = ROOT
        for tool, ti in (("Write", {"file_path": f"{root}/durum/taslak/../akislar/g/x.json", "content": "x"}),
                         ("Write", {"file_path": f"{root}/durum//isler/x.md.json", "content": "x"}),
                         ("Edit", {"file_path": f"{root}/durum/./sunucu.json", "old_string": "a", "new_string": "b"}),
                         ("Bash", {"command": "cd durum/taslak && echo x > ../akislar/g/x.json"}),
                         ("Bash", {"command": "echo x > durum//akislar/g/x.json"}),
                         ("Bash", {"command": "echo x > ./durum/./sunucu.json"}),
                         ("Bash", {"command": f"cd {ROOT}/durum/taslak; rm ../isler/x.md.json"})):
            with self.subTest(tool=tool, ti=ti):
                self.assert_blocked(tool, ti)

    def test_workflow_templates_and_commands_allowed(self):
        self.assert_allowed("Read", {"file_path": ROOT + "/durum/akislar/sayac.json"})
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py akis kucuk-is --brief-dosya durum/taslak/a.json"})
        self.assert_allowed("Bash", {"command": "cat akislar/kucuk-is.json"})

    def test_office_commands_still_allowed(self):
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py ekle --proje blog --brief-dosya durum/taslak/b.json"})
        self.assert_allowed("Bash", {"command": "python3 bin/ofis.py butce 2026-11-11-1-blog.md 5"})
        self.assert_allowed("Write", {"file_path": ROOT + "/durum/taslak/b.json", "content": "{}"})
        # Reading vault job notes: their frontmatter has a "durum:" field and the vault folder is OFIS/Isler/.
        self.assert_allowed("Bash", {"command": "grep -E '^durum: bitti' \"$V\"/Isler/*/x.md"})
        self.assert_allowed("Bash", {"command": "V=/x/OFIS; grep '^durum' $V/Isler/Bitenler/a.md"})

    def test_normal_work_is_allowed(self):
        self.assert_allowed("Bash", {"command": "claude agents --json"})
        self.assert_allowed("Bash", {"command": "python3 bin/launch.py blog \"testleri çalıştır\""})
        self.assert_allowed("Bash", {"command": "git -C ~/Dev/blog log --oneline -3"})
        self.assert_allowed("Bash", {"command": "ls ~/Dev/zimbo"})
        self.assert_allowed("Read", {"file_path": VAULT + "/OFIS/README.md"})
        self.assert_allowed("Write", {"file_path": VAULT + "/OFIS/Kararlar/a.md",
                                      "content": "ZIM bu notta geçebilir; içerik kontrol edilmez"})
        self.assert_allowed("SendMessage", {"to": "ofis-blog-1", "message": "zim"})

    def test_bad_input_fails_closed(self):
        proc = subprocess.run([sys.executable, "-I", GUARD], input="not json", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)

    def raw(self, payload):
        proc = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload), capture_output=True, text=True,
                              timeout=10)
        return proc.returncode, proc.stderr

    def test_malformed_hook_input_fails_closed(self):
        # Codex review 2026-11-12: a null / non-string command passed, a non-object tool_input or an odd tool_name crashed.
        for payload in ([], 7, None, "Bash", {}, {"tool_input": {"command": "ls"}},
                        {"tool_name": None, "tool_input": {"command": "ls"}},
                        {"tool_name": ["Bash"], "tool_input": {"command": "ls"}},
                        {"tool_name": {"x": 1}, "tool_input": {}},
                        {"tool_name": 3, "tool_input": {}},
                        {"tool_name": "Bash", "tool_input": None},
                        {"tool_name": "Bash", "tool_input": []},
                        {"tool_name": "Bash", "tool_input": ["ls", {"command": "ls"}]},
                        {"tool_name": "Write", "tool_input": [{"file_path": "/tmp/x"}]},
                        {"tool_name": "Read", "tool_input": {}},
                        {"tool_name": "Glob", "tool_input": {"path": "/tmp"}},
                        {"tool_name": "Bash", "tool_input": "rm -rf durum"},
                        {"tool_name": "Bash", "tool_input": 5},
                        {"tool_name": "Bash"},
                        {"tool_name": "Bash", "tool_input": {}},
                        {"tool_name": "Bash", "tool_input": {"command": None}},
                        {"tool_name": "Bash", "tool_input": {"command": ["echo", "x"]}},
                        {"tool_name": "Bash", "tool_input": {"command": 42}},
                        {"tool_name": "Write", "tool_input": {"content": "x"}},
                        {"tool_name": "Write", "tool_input": {"file_path": None, "content": "x"}},
                        {"tool_name": "Edit", "tool_input": {"file_path": ["/tmp/a"]}},
                        {"tool_name": "Read", "tool_input": {"file_path": 1}},
                        {"tool_name": "NotebookEdit", "tool_input": {}},
                        {"tool_name": "Glob", "tool_input": {"pattern": None}},
                        {"tool_name": "Glob", "tool_input": {"pattern": "*.md", "path": 3}},
                        {"tool_name": "Grep", "tool_input": {"pattern": "x", "glob": ["*.py"]}}):
            with self.subTest(payload=payload):
                code, err = self.raw(payload)
                self.assertEqual(code, 2, payload)
                self.assertTrue(err.strip())
                self.assertNotIn("Traceback", err)

    def test_well_formed_optional_fields_still_pass(self):
        for payload in ({"tool_name": "Glob", "tool_input": {"pattern": "**/*.py"}},
                        {"tool_name": "Glob", "tool_input": {"pattern": "*.md", "path": None}},
                        {"tool_name": "Grep", "tool_input": {"pattern": "x"}},
                        {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "bin", "glob": "*.py"}},
                        {"tool_name": "SendMessage", "tool_input": {"to": "x", "message": "y"}},
                        {"tool_name": "SendMessage", "tool_input": None},
                        {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": ROOT}):
            with self.subTest(payload=payload):
                code, err = self.raw(payload)
                self.assertEqual(code, 0, f"{payload}: {err}")

    def test_relative_write_paths_reach_the_trusted_records(self):
        # Codex review 2026-11-12: normpath dropped the leading ./ and TRUSTED_PATH needs /durum/.
        root = ROOT
        for cwd in (root, None):
            for path in ("./durum/isler/x.json", "durum/isler/x.json", "bin/../durum/isler/x.json",
                         "durum/sistem/domainler.json", "./durum/sunucu.json", "durum/taslak/../akislar/g/x.json"):
                for tool in ("Write", "Edit"):
                    with self.subTest(cwd=cwd, path=path, tool=tool):
                        payload = {"tool_name": tool, "tool_input": {"file_path": path, "content": "x"}}
                        if cwd:
                            payload["cwd"] = cwd
                        self.assertEqual(self.raw(payload)[0], 2, payload)
        # relative paths elsewhere stay allowed
        for path in ("durum/taslak/is-1.json", "./bin/sistem.py", "test/test_sistem.py"):
            with self.subTest(path=path):
                code, err = self.raw({"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}, "cwd": root})
                self.assertEqual(code, 0, err)

    def raw_env(self, payload, **env):
        proc = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(payload), capture_output=True, text=True,
                              timeout=10, env=dict(os.environ, **env))
        return proc.returncode

    def test_symlinks_to_trusted_or_private_folders_are_resolved(self):
        # Codex review 2026-11-12 (third pass): a harmless-looking link to a protected folder.
        with tempfile.TemporaryDirectory() as tmp:
            t = os.path.realpath(tmp)
            os.makedirs(f"{t}/durum/isler")
            os.makedirs(f"{t}/kasa/Mektuplar")
            os.symlink(f"{t}/durum/isler", f"{t}/kayitlar")
            os.symlink(f"{t}/kasa/Mektuplar", f"{t}/posta")
            os.symlink(f"{t}/durum", f"{t}/d")
            for tool, ti in (("Write", {"file_path": f"{t}/kayitlar/forged.json", "content": "{}"}),
                             ("Edit", {"file_path": f"{t}/kayitlar/x.json", "old_string": "a", "new_string": "b"}),
                             ("Write", {"file_path": f"{t}/d/isler/yeni/klasor/x.json", "content": "{}"}),
                             ("Write", {"file_path": "kayitlar/forged.json", "content": "{}"}),
                             ("Read", {"file_path": f"{t}/posta/inbox.md"}),
                             ("Read", {"file_path": "posta/inbox.md"}),
                             ("Grep", {"pattern": "x", "path": f"{t}/posta"})):
                with self.subTest(tool=tool, ti=ti):
                    self.assertEqual(self.raw({"tool_name": tool, "tool_input": ti, "cwd": t})[0], 2)
            self.assertEqual(self.raw({"tool_name": "Read", "tool_input": {"file_path": f"{t}/kayitlar/x.json"}, "cwd": t})[0], 0)
            self.assertEqual(self.raw({"tool_name": "Write", "tool_input": {"file_path": f"{t}/notlar.md", "content": "x"},
                                       "cwd": t})[0], 0)

    def test_dot_dot_after_a_symlink_follows_the_link_first(self):
        # Codex review 2026-11-12 (sixth pass): public/link/../secret.txt with link -> vault/Mektuplar/subdir reads
        # vault/Mektuplar/secret.txt (the OS resolves the link before the `..`).
        with tempfile.TemporaryDirectory() as tmp:
            t = os.path.realpath(tmp)
            os.makedirs(f"{t}/kasa/Mektuplar/subdir")
            os.makedirs(f"{t}/durum/isler/alt")
            os.makedirs(f"{t}/public")
            os.symlink(f"{t}/kasa/Mektuplar/subdir", f"{t}/public/link")
            os.symlink(f"{t}/durum/isler/alt", f"{t}/public/kayit")
            for tool, ti in (("Read", {"file_path": f"{t}/public/link/../secret.txt"}),
                             ("Read", {"file_path": "public/link/../secret.txt"}),
                             ("Write", {"file_path": f"{t}/public/kayit/../forged.json", "content": "x"}),
                             ("Grep", {"pattern": "x", "path": "public/link/.."})):
                with self.subTest(tool=tool, ti=ti):
                    self.assertEqual(self.raw({"tool_name": tool, "tool_input": ti, "cwd": t})[0], 2)
            for cmd in ("cat public/link/../secret.txt", "echo x > public/kayit/../forged.json"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": t})[0], 2)
            self.assertEqual(self.raw({"tool_name": "Read", "tool_input": {"file_path": "public/a.md"}, "cwd": t})[0], 0)

    def test_bare_name_targets_of_writing_commands_are_resolved(self):
        # Codex review 2026-11-12 (sixth pass): `printf forged > alias` with alias -> a trusted record.
        with tempfile.TemporaryDirectory() as tmp:
            t = os.path.realpath(tmp)
            os.makedirs(f"{t}/durum/isler")
            os.makedirs(f"{t}/kasa/TAPU")
            with open(f"{t}/durum/isler/kayit.json", "w") as f:
                f.write("{}")
            os.symlink(f"{t}/durum/isler/kayit.json", f"{t}/alias")
            os.symlink(f"{t}/durum/isler", f"{t}/klasor")
            os.symlink(f"{t}/kasa/TAPU", f"{t}/ag")
            for cmd in ("printf forged > alias", "printf forged >alias", "echo x >> alias", "echo x | tee alias",
                        "echo x | tee -a alias >/dev/null", "touch alias", "rm alias", "rm -f klasor", "mv yeni alias",
                        "cp yeni alias", "chmod 600 alias", "ln -sf yeni alias", "truncate -s 0 alias",
                        "dd if=/dev/zero of=alias count=1", "sed -i '' s/a/b/ alias", "cat ag", "cp ag/x yeni"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": t})[0], 2)
            for cmd in ("printf x > notlar.txt", "touch yeni", "echo x | tee kopya.txt", "sed -n 1p notlar.txt",
                        "cp notlar.txt yedek.txt", "rm yeni"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": t})[0], 0)

    def test_a_bash_cwd_inside_a_trusted_or_private_folder_blocks(self):
        # Codex review 2026-11-12 (third pass): the call's working directory and a leading `cd` count as a path.
        with tempfile.TemporaryDirectory() as tmp:
            t = os.path.realpath(tmp)
            os.makedirs(f"{t}/durum/isler")
            os.makedirs(f"{t}/durum/taslak")
            os.makedirs(f"{t}/kasa/Mektuplar")
            os.makedirs(f"{t}/kasa/OFIS")
            os.symlink(f"{t}/durum/isler", f"{t}/kayitlar")
            os.symlink(f"{t}/kasa/Mektuplar", f"{t}/posta")
            for cwd, cmd in ((f"{t}/durum/isler", "touch record.json"), (f"{t}/kayitlar", "touch record.json"),
                             (f"{t}/kasa/Mektuplar", "cat account.txt"), (f"{t}/posta", "cat account.txt"),
                             (t, "cd kayitlar && touch record.json"), (t, "cd posta; cat account.txt"),
                             (f"{t}/durum/taslak", "cd ../isler && touch r.json"), (t, "cd \"kayitlar\" && ls"),
                             (t, "ls && cd posta && cat a.txt")):
                with self.subTest(cwd=cwd, cmd=cmd):
                    self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
            for cwd, cmd in ((f"{t}/durum/taslak", "ls"), (t, "cd kasa/OFIS && ls"), (f"{t}/kasa", "cd OFIS; cat a.md"),
                             (ROOT, "git status"),
                             (ROOT, "python3 bin/ofis.py durum")):
                with self.subTest(cwd=cwd, cmd=cmd):
                    self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 0)

    def test_searches_rooted_at_the_vault_or_above_are_blocked(self):
        # Codex review 2026-11-12 (third pass): a Grep/Glob from the vault root (or a parent) reaches the private notes.
        vault = VAULT
        for tool, ti, cwd in (("Grep", {"pattern": "token", "path": vault}, None),
                              ("Grep", {"pattern": "token", "path": vault + "/"}, None),
                              ("Grep", {"pattern": "token", "path": HOME + "/Documents"}, None),
                              ("Grep", {"pattern": "token", "path": HOME}, None),
                              ("Grep", {"pattern": "token", "path": "/"}, None),
                              ("Grep", {"pattern": "token"}, vault),
                              ("Grep", {"pattern": "token", "path": "."}, vault),
                              ("Grep", {"pattern": "token", "path": ".."}, vault + "/OFIS"),
                              ("Glob", {"pattern": "**/*.md", "path": vault}, None),
                              ("Glob", {"pattern": "**/*.md"}, HOME + "/Documents"),
                              ("Glob", {"pattern": vault + "/**/*.md"}, ROOT),
                              ("Glob", {"pattern": HOME + "/**/hesap*"}, ROOT),
                              ("Grep", {"pattern": "x", "path": vault + "/TAPU"}, None)):
            with self.subTest(tool=tool, ti=ti, cwd=cwd):
                payload = {"tool_name": tool, "tool_input": ti}
                if cwd:
                    payload["cwd"] = cwd
                self.assertEqual(self.raw(payload)[0], 2)
        for tool, ti, cwd in (("Grep", {"pattern": "blog", "path": vault + "/OFIS/Kararlar"}, None),
                              ("Grep", {"pattern": "blog", "path": "OFIS/Kararlar"}, vault),
                              ("Grep", {"pattern": "durum: bekliyor"}, vault + "/OFIS"),
                              ("Glob", {"pattern": "**/*.md", "path": vault + "/OFIS"}, None),
                              ("Glob", {"pattern": vault + "/OFIS/Kararlar/*.md"}, ROOT),
                              ("Grep", {"pattern": "def ", "path": "bin"}, ROOT),
                              ("Grep", {"pattern": "def "}, ROOT),
                              ("Glob", {"pattern": "test/*.py"}, ROOT)):
            with self.subTest(tool=tool, ti=ti, cwd=cwd):
                payload = {"tool_name": tool, "tool_input": ti}
                if cwd:
                    payload["cwd"] = cwd
                self.assertEqual(self.raw(payload)[0], 0, self.raw(payload)[1])
        # an extra vault root (tests, a second vault) only adds protection
        with tempfile.TemporaryDirectory() as tmp:
            v = os.path.realpath(tmp) + "/Kasa"
            os.makedirs(v + "/OFIS")
            self.assertEqual(self.raw_env({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": v}},
                                          OFIS_GUARD_EK_KASA=v), 2)
            self.assertEqual(self.raw_env({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": v + "/OFIS"}},
                                          OFIS_GUARD_EK_KASA=v), 0)
            self.assertEqual(self.raw_env({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": vault}},
                                          OFIS_GUARD_EK_KASA=v), 2)

    def test_dot_dot_segments_and_cwd_relative_words_in_shell_commands(self):
        # Codex review 2026-11-12 (fourth pass): path words are normalised and resolved against the cwd.
        root = ROOT
        for cwd, cmd in ((root, "touch durum/other/../isler/x.json"), (root + "/durum", "touch isler/x.json"),
                         (root + "/durum", "echo x > ./sistem/domainler.json"), (root + "/bin", "cp a ../durum/akislar/g/x"),
                         (root, "touch ./bin/../durum/./kontroller/x.json")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
        for cwd, cmd in ((root + "/durum", "ls taslak/"), (root, "cat bin/../CLAUDE.md"), (root, "ls web/vendor/three/")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 0)

    def test_redirect_and_tee_targets_count_as_paths(self):
        # Codex review 2026-11-12 (fifth pass).
        root = ROOT
        for cwd, cmd in ((root, "echo '{}' > durum/taslak/../sistem/domainler.json"),
                         (root + "/durum", "echo '{}' > sistem/domainler.json"),
                         (root + "/durum", "echo '{}' >> sistem/domainler.json"),
                         (root + "/durum", "echo '{}' >sistem/domainler.json"),
                         (root + "/durum", "echo '{}'>>./isler/x.json"),
                         (root + "/durum", "echo '{}' | tee sistem/domainler.json"),
                         (root + "/durum/taslak", "echo x | tee -a ../isler/x.json >/dev/null")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
        for cwd, cmd in ((root, "echo x > durum/taslak/is-1.json"), (root + "/durum", "echo x | tee taslak/a.txt >/dev/null"),
                         (root, "python3 -I test/test_guard.py 2>&1 | tail -3")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 0)

    def test_a_search_without_a_path_is_rooted_at_the_cwd(self):
        # Codex review 2026-11-12 (fifth pass): fake folders only; the real ZIM folder is never touched.
        with tempfile.TemporaryDirectory() as tmp:
            t = os.path.realpath(tmp)
            for sub in ("kasa/Mektuplar/a", "Dev/zim/src", "Dev/ZIM-eski", "Dev/blog"):
                os.makedirs(f"{t}/{sub}")
            for tool, ti, cwd in (("Grep", {"pattern": "x"}, f"{t}/kasa/Mektuplar"), ("Grep", {"pattern": "x"}, f"{t}/kasa/Mektuplar/a"),
                                  ("Glob", {"pattern": "**/*"}, f"{t}/kasa/Mektuplar"), ("Grep", {"pattern": "x"}, f"{t}/Dev/zim"),
                                  ("Grep", {"pattern": "x"}, f"{t}/Dev/zim/src"), ("Glob", {"pattern": "*.py"}, f"{t}/Dev/ZIM-eski"),
                                  ("Grep", {"pattern": "x", "path": "."}, f"{t}/Dev/zim")):
                with self.subTest(tool=tool, cwd=cwd):
                    self.assertEqual(self.raw({"tool_name": tool, "tool_input": ti, "cwd": cwd})[0], 2)
            # above a private folder: the fake vault is given as an extra vault root
            self.assertEqual(self.raw_env({"tool_name": "Grep", "tool_input": {"pattern": "x"}, "cwd": f"{t}/kasa"},
                                          OFIS_GUARD_EK_KASA=f"{t}/kasa"), 2)
            self.assertEqual(self.raw_env({"tool_name": "Grep", "tool_input": {"pattern": "x"}, "cwd": t},
                                          OFIS_GUARD_EK_KASA=f"{t}/kasa"), 2)
            for tool, ti, cwd in (("Grep", {"pattern": "x"}, f"{t}/Dev/blog"), ("Glob", {"pattern": "*.md"}, f"{t}/Dev/blog")):
                with self.subTest(tool=tool, cwd=cwd):
                    self.assertEqual(self.raw({"tool_name": tool, "tool_input": ti, "cwd": cwd})[0], 0)

    def test_one_rule_for_every_word(self):
        # Codex review 2026-11-12 (eighth pass): every word, option value and redirect target is a path candidate
        # (`~` expanded, globs expanded against every directory the command may run in, links resolved).
        root = ROOT
        vault = VAULT
        for cwd, cmd in ((root, "printf x > durum/i?ler/x.json"), (root, "rm -f durum/i?ler/*.json"),
                         (root, "cp -r --target-directory=. /tmp/durum"), (root, "cp -t. /tmp/durum"),
                         (root, "rm -rf durum/{isler,kontroller}"), (root, "rm -rf durum/$X"), (root, "ls -R durum/"),
                         (root, "grep -r x ./durum/"), (root, "ls -R ~/Documents"), (root, "grep -r token ~/Documents/Obsidian\\ Vault"),
                         (root, "bash -c 'rm -rf durum'"), (root, "sh -c \"echo x > durum/isler/a\""), (root, "eval rm -rf durum"),
                         (root, "echo `rm -rf durum`"), (root, "echo $(rm -rf durum)"), (root, "pushd durum/isler && ls"),
                         (root, "pushd /tmp; rm -rf durum"),
                         # recursive reads of a parent (the vault root, durum/) and globs into the records
                         (vault + "/OFIS", "ls -R .."), (root, "ls durum/*"),
                         # final review: a glob cd target, brace expansion, a line continuation, ANSI-C quoting
                         (root, "cd dur* && touch isler/x.json"), (root, "cd d?rum; touch sunucu.json"),
                         (root, "rm -rf dur{um,}"),
                         (root, "touch durum/i{s,}ler/x.json"), (root, "cat ~/Documents/Obsidian\\ Vault/Mek{tuplar,}/x.md"),
                         (root, "touch dur\\\num/isler/x.json"), (root, "rm -rf dur\\\num"),
                         (root, "touch $'dur\\x75m/isler/x.json'"), (root, "rm -rf $'\\x64urum'")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
        # globs into the private folders, expanded against a fake vault (an extra vault root), never a real one
        with tempfile.TemporaryDirectory() as tmp:
            kasa = os.path.join(os.path.realpath(tmp), "Obsidian Vault")
            for folder in ("Mektuplar", "TAPU"):
                os.makedirs(os.path.join(kasa, folder))
            t = os.path.dirname(kasa)
            for cmd in (f"cat {t}/Obsidian*/Mek*/*", f"ls {t}/Obsidian*/TA*", f"cd {t}/Obs*/Mek* && cat x.md",
                        f"echo '<<EOF'\ncat {t}/Obsidian\\ Vault/M*/x"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.raw_env({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root},
                                                  OFIS_GUARD_EK_KASA=kasa), 2)
        vault = VAULT
        for cwd, cmd in ((root, "git status"), (root, "ls"), (root, "ls ."), (root, "grep -rn def bin/"),
                         (root, "python3 bin/ofis.py durum"), (root, "cat durum/taslak/is-1.json"), (root, "ls durum/taslak/"),
                         (root, f"cat '{vault}/OFIS/README.md'"), (root, f"ls '{vault}/OFIS/Kararlar/'"),
                         (root, f"grep -rl blog '{vault}/OFIS/Isler'"), (root, "ls ~/Dev"),
                         (root, "git -C ~/Dev/blog log --oneline -3"), (root, "for f in test/test_*.py; do echo $f; done"),
                         (root, "bash -c 'git status'"), (root, "echo $(date +%F)"),
                         (root, "printf $'a\\tb\\n'"), (root, "ls durum/taslak/{a,b}.json"), (root, "cd te* && ls"),
                         (root, "echo {1..3}"), (root, "git log \\\n  --oneline -3")):
            with self.subTest(cwd=cwd, cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
                self.assertEqual(code, 0, err)

    def test_data_text_is_not_a_path(self):
        # False positive 2026-11-12: a lone "/" in a heredoc resolved to the file-system root (a parent of the vault).
        # Heredoc bodies and the text arguments of echo / printf / git commit -m are data; the old text rule
        # (TRUSTED_IN_SHELL, ZIM, private folder names) still reads the whole command.
        root = ROOT
        plan = ("cd /Users/ornek/.claude/plans && cat >> plan.md <<'EOF'\n## Durum Raporu / Paydaş Raporu\n"
                "- satır / ayraç . nokta ~ ev\nEOF")
        for cmd in (plan, "echo \"a / b\"", "git commit -m \"x / y\"", "git commit -m 'x / .' -m \"/ ~\"",
                    "printf '%s\\n' \"a / b\" > /tmp/out.txt", "cat <<-EOF\n\t/ . ~\n\tEOF", "cat <<EOF | wc -l\n/\nEOF",
                    "ls /", "ls ~", "ls .", "cat /etc/hosts"):
            with self.subTest(cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})
                self.assertEqual(code, 0, err)
        for cmd in ("rm -rf /", "rm -rf /Users", "rm -rf ~", "chmod -R 777 /", "mv ~ /tmp/x",
                    "bash <<'EOF'\nrm -rf durum\nEOF", "sh <<EOF\ntouch durum/isler/x.json\nEOF",
                    "cat > durum/isler/x.json <<'EOF'\n{}\nEOF",
                    # the old text rule is unchanged: a trusted path named as plain text still blocks
                    "git commit -m \"fix durum/isler handling\"", "echo durum/sistem/x"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})[0], 2)

    def test_fake_heredoc_openers_keywords_and_wrappers(self):
        # Closing review 2026-11-12: a `<<WORD` in quotes, a comment or arithmetic is no heredoc; shell keywords and
        # wrapper programs never hide the real command; code spans in a quoted heredoc are prose.
        root = ROOT
        vault = VAULT
        for cmd in ("echo '<<EOF'\nrm -rf durum", "echo $((1<<X))\nrm -rf durum", "true # <<EOF\nrm -rf .",
                    "echo \"<<EOF\"\nrm -rf ~/Documents/Obsidian\\ Vault",
                    # (a fake opener followed by a glob into a private folder: test_one_rule_for_every_word's fake vault)
                    "(( x = 1<<EOF ))\nrm -rf durum",
                    "{ rm -rf durum; }", "if true; then rm -rf durum; fi", "! mv durum /tmp/x", "for i in 1; do rm -rf .; done",
                    "while false; do :; done; until true; do rm -rf durum; done", "caffeinate -i rm -rf durum",
                    "arch -arm64 rm -rf durum", "timeout 5 rm -rf durum", "gtimeout -s KILL 5 rm -rf durum",
                    "stdbuf -oL rm -rf durum", "flock /tmp/l rm -rf durum", "if true; then tar xf /tmp/a.tar; fi",
                    "{ grep -r token ~/Documents/Obsidian\\ Vault; }", "time -p rm -rf durum",
                    "cat <<EOF\n$(rm -rf durum)\nEOF"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})[0], 2)
        prose = ("cat >> notes.md <<'EOF'\nUse `patch` here, then `git apply` ran; the `unzip` step failed.\n"
                 "cost $(tar xf a) note / ~ .\nEOF")
        for cmd in (prose, "cat >> notes.md <<\"EOF\"\n`rm -rf .` is what we never run\nEOF",
                    "echo 'see `rm -rf durum` in the docs'", "git log --format='%h $(x)' -1",
                    "if git diff --quiet; then echo clean; fi", "{ git status; git diff --stat; }", "timeout 30 git status",
                    f"cd '{vault}/OFIS' && grep -rn blog Kararlar"):
            with self.subTest(cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})
                self.assertEqual(code, 0, err)

    def test_shell_flag_clusters_and_absolute_shells_run_their_code(self):
        # Codex review 2026-11-12 (tenth pass).
        root = ROOT
        for cmd in ("bash -lc 'rm -rf .'", "sh -ec 'rm -rf durum'", "zsh -ic \"mv durum /tmp/x\"", "bash --command 'rm -rf .'",
                    "/bin/bash -c 'rm -rf .'", "/bin/bash <<EOF\nrm -rf .\nEOF", "/usr/bin/env bash <<'EOF'\nrm -rf durum\nEOF",
                    "env -i sh <<EOF\nrm -rf .\nEOF", "/bin/zsh <<EOF\nrm -rf .\nEOF", "dash <<EOF\nrm -rf .\nEOF",
                    "exec ksh <<EOF\nrm -rf .\nEOF", "nohup fish <<EOF\nrm -rf .\nEOF", "time bash <<EOF\nrm -rf .\nEOF",
                    "cat x | bash <<EOF\nrm -rf .\nEOF"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})[0], 2)
        for cmd in ("cat >> notes.md <<'EOF'\n## Rapor / Not\nrm -rf . is never run here\nEOF",
                    "tee notes.md <<EOF >/dev/null\nmv a / b\nEOF", "git commit -F - <<'EOF'\nMove / rename . ~\nEOF",
                    "bash -lc 'git status'", "/bin/bash -c 'ls durum/taslak'"):
            with self.subTest(cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})
                self.assertEqual(code, 0, err)

    def test_unusual_heredoc_delimiters_substitutions_and_wrapper_options_fail_closed(self):
        # Last review 2026-11-12: anything the scanner cannot read exactly is treated as commands, never as data.
        root = ROOT
        for cmd in ("cat <<\"E\"OF\nx\nEOF\nrm -rf durum", "cat <<E\"OF\"\nx\nEOF\nrm -rf durum", "cat <<EOF.x\nx\nEOF.x\nrm -rf durum",
                    "cat <<E\\OF\nx\nEOF\nrm -rf .", "echo \"$(echo \"<<EOF\")\"\nrm -rf durum", "echo ${x:-<<EOF}\nrm -rf durum",
                    "echo \"'$(rm -rf durum)'\"", "echo \"'`rm -rf durum`'\"", "echo \"$(rm -rf durum; (true))\"",
                    "echo \"$(rm -rf durum\"", "echo `rm -rf durum",
                    "caffeinate -t 1 rm -rf durum", "exec -a x rm -rf durum", "true | xargs -I {} rm -rf durum",
                    "true | xargs -L 1 rm -rf .", "arch -arch arm64 rm -rf durum", "env -S 'rm -rf durum'",
                    "env --split-string='rm -rf .'", "sudo -u root rm -rf durum", "nice -n 5 rm -rf durum",
                    "xargs -0 -n 1 -P 4 rm -rf durum"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})[0], 2)
        for cmd in ("cat >> notes.md <<'EOF'\nUse `patch` and $(date) / ~ .\nEOF", "cat <<EOF >> notes.md\nline / x\nEOF",
                    "cat <<-'EOF' > /tmp/x.txt\n\tok / .\n\tEOF", "echo \"it's $(date +%F)\"", "echo \"$(git rev-parse --short HEAD)\"",
                    "caffeinate -t 1 git status", "true | xargs -I {} echo {}", "env -i PATH=/usr/bin git status",
                    "git commit -m \"$(printf 'Add / fix')\""):
            with self.subTest(cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})
                self.assertEqual(code, 0, err)

    def test_physical_cd_targets_and_directory_changing_wrappers(self):
        # Codex review 2026-11-12 (eleventh pass, the last guard addition of the round).
        root = ROOT
        with tempfile.TemporaryDirectory() as tmp:
            t = os.path.realpath(tmp)
            os.makedirs(f"{t}/durum/taslak")
            os.makedirs(f"{t}/durum/isler")
            os.symlink(f"{t}/durum/taslak", f"{t}/link")
            for cmd in ("cd -P link/.. && rm -rf isler", "cd link/.. && touch isler/x.json"):
                with self.subTest(cmd=cmd):
                    self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": t})[0], 2)
        for cmd in (f"env -C {root}/durum/taslak rm -rf ../isler", f"env --chdir={root}/durum/taslak rm -rf ..",
                    "env -C durum/taslak touch ../sistem/x.json", "make -C durum/taslak clean && rm -rf ../isler",
                    "npm --prefix durum/taslak exec -- rm -rf ../isler", "sudo -D durum/taslak rm -rf ..",
                    "pushd durum/taslak && rm -rf ../isler"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})[0], 2)
        for cmd in ("env -C bin ls", "make -C web test", "npm --prefix web run lint"):
            with self.subTest(cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})
                self.assertEqual(code, 0, err)

    def test_a_case_pattern_inside_a_substitution_hides_no_heredoc(self):
        # Frozen-guard review 2026-11-12: a case pattern's `)` closed the `$(` too early in the opener scan.
        root = ROOT
        for cmd in ("echo \"$(case a in a) echo \" <<EOF \";; esac)\"\nrm -rf durum",
                    f"echo \"$(case a in a) echo \" <<EOF \";; esac)\"\nrm -rf {root}",
                    "x=$(case a in a) cat <<EOF ;; esac)\nrm -rf ."):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": root})[0], 2)

    def test_commands_whose_target_is_the_cwd(self):
        # Codex review 2026-11-12 (ninth pass): an extraction or a recursive search without a path acts on the cwd.
        root = ROOT
        vault = VAULT
        for cwd, cmd in ((root, "tar -xf /tmp/payload.tar"), (root, "tar xzf /tmp/p.tgz"), (root, "tar -x -f /tmp/p.tar"),
                         (root, "bsdtar -xf /tmp/p.tar"), (root, "tar -xf /tmp/p.tar -C durum"), (root, "tar -xf /tmp/p.tar --directory=."),
                         (root, "unzip /tmp/p.zip"), (root, "unzip -o /tmp/p.zip -d durum"), (root, "cpio -id < /tmp/p.cpio"),
                         (root, "7z x /tmp/p.7z"), (root, "pax -r -f /tmp/p.pax"), (root, "git apply /tmp/p.diff"),
                         (root, "patch -p1 < /tmp/p.diff"), (root + "/durum", "tar -xf /tmp/p.tar"),
                         (vault, "rg --hidden needle"), (vault, "grep -r needle"), (vault, "grep -Rn needle ."), (vault, "ag needle"),
                         (vault, "ack needle"), (vault, "find -name '*.md'"), (vault, "ls -R"), (vault, "ls -laR"), (vault, "tree"),
                         (vault, "du -sh"), (vault, "fd md"), (HOME + "/Documents", "rg needle"), (HOME, "grep -rl x")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
        for cwd, cmd in ((vault + "/OFIS", "rg needle"), (vault + "/OFIS", "grep -rn blog ."), (vault + "/OFIS", "ls -R Kararlar"),
                         (root, "rg -n def bin"), (root, "grep -rn guard test/"), (root, "ls -la"), (root, "du -sh bin"),
                         (root, "tar -tf /tmp/p.tar"), (root, "tar -czf /tmp/out.tgz bin"), (root, "unzip -l /tmp/p.zip"),
                         (root, "tar -xf /tmp/p.tar -C /tmp/x"), (root, "unzip /tmp/p.zip -d durum/taslak/acik"),
                         (root, "git apply --check /tmp/p.diff"), (root, "find bin -name '*.py'")):
            with self.subTest(cwd=cwd, cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
                self.assertEqual(code, 0, err)

    def test_destructive_globs_subshell_cds_and_git_options(self):
        # Codex review 2026-11-12 (seventh pass): fail closed instead of following shell semantics.
        root = ROOT
        for cwd, cmd in ((root, "rm -rf durum/*"), (root, "rm -rf dur*"), (root, "rm -rf ./durum/is*"), (root, "mv durum/* /tmp/x"),
                         (root, "rm -rf ?urum"), (root, "chmod 000 durum/[a-z]*"),
                         (root, "(cd /tmp); rm -rf durum"), (root, "(cd /tmp && true); rm -rf durum/"),
                         (root, "cd /tmp; cd -; rm -rf durum"), ("/tmp", f"(cd {root}); rm -rf durum"),
                         (root, "git -C durum clean -fdx"), (root, "git -C . clean -fdx"), (root, "git --work-tree=durum clean -f"),
                         (root, "git --git-dir=.git --work-tree . clean -fdX"), (root, "git -c core.x=1 clean -fd"),
                         ("/tmp", f"git -C {root} clean -fdx"), (root, "git rm -r --cached durum"), (root, "git rm -rf ."),
                         (root, "git checkout -- ."), (root, "git checkout ."), (root, "git restore ."),
                         (root, "git restore --source=HEAD durum"), (root, "git reset --hard"), (root, "git reset --hard HEAD~1"),
                         (root, "git stash -u"), (root, "git stash push --include-untracked"), (root, "git stash --all"),
                         (root, "git -C durum/isler status"), (root, "git --work-tree=durum/sistem status")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
        for cwd, cmd in ((root, "git clean -n"), (root, "git -C . clean -n -dx"), (root, "git clean --dry-run -fdx"),
                         (root, "git status"), (root, "git -C . status --short"), (root, "git diff -- bin/guard.py"),
                         (root, "git -c color.ui=never log --oneline -3"), (root, "git checkout -- bin/guard.py"),
                         (root, "git restore bin/guard.py"), (root, "git stash list"), (root, "rm -f durum/taslak/*.json"),
                         (root, "rm durum/taslak/is-?.json"), (root, "ls durum/taslak/*"), (root, "(cd /tmp && ls); git status"),
                         (root, "git -C /Users/ornek/Dev/blog log -1")):
            with self.subTest(cwd=cwd, cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
                self.assertEqual(code, 0, err)

    def test_destructive_commands_on_a_protected_folder_or_its_parents(self):
        # Codex review 2026-11-12 (fourth pass): `rm -rf durum` deleted every trusted record.
        root = ROOT
        vault = VAULT
        for cwd, cmd in ((root, "rm -rf durum"), (root, "rm -r ./durum/"), (root, "rmdir durum"), (root, "mv durum /tmp/x"),
                         (root, "rm -rf ."), (root + "/bin", "rm -rf .."), (root, "rm -rf ~/Documents"),
                         (root, f"rm -rf '{vault}'"), (vault, "rm -rf ."), (vault + "/OFIS", "mv .. /tmp/k"),
                         (root, "find durum -delete"), (root, "find . -name x -exec rm {} +"), (root, "git clean -fdx"),
                         (root, "git clean -fd durum"), (root, "chmod -R 777 durum"), (root, "chown -R x durum"),
                         (root, "cp -r /tmp/e durum"), (root, "rsync -a --delete /tmp/e/ durum/"), (root, "tar czf a.tgz durum"),
                         (root, "ln -sfn /tmp/e durum"), (root, "ls && /bin/rm -rf durum"), (root, "sudo rm -rf durum"),
                         (root, f"rm -rf \"$HOME\"/../{os.path.basename(HOME)}"), (root, "rm -rf /")):
            with self.subTest(cwd=cwd, cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})[0], 2)
        for cwd, cmd in ((root, "rm durum/taslak/is-1.json"), (root, "rm -f durum/taslak/cevap-1.txt"),
                         (root, "git status"), (root, "git diff -- bin/guard.py"), (root, "ls durum/taslak"),
                         (root, "find . -name '*.py' -newer CLAUDE.md"), (root, "mv durum/taslak/a.json durum/taslak/b.json"),
                         (root, "rm -rf /tmp/ofis-deneme"), (root, "cp bin/guard.py /tmp/guard.py"), (root, "git clean -n"),
                         (root, "chmod +x bin/guard.py"), (vault + "/OFIS", "ls Kararlar")):
            with self.subTest(cwd=cwd, cmd=cmd):
                code, err = self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
                self.assertEqual(code, 0, err)

    def test_private_folders_in_shell_commands_are_blocked(self):
        # Codex review 2026-11-12 (second pass): relative folder words in a command, with or without a trailing slash.
        for cmd in ("cat Mektuplar/inbox.md", "ls TAPU", "ls tapu", "ls SİGORTA", "ls 'SİGORTA'", "cat SİGORTA/notlar.md",
                    "cd Mektuplar && ls", "find . -path ./TAPU/x", "cat 'E commint/Email Şifre.md'", "cat ŞİFRELER/a.md",
                    "ls ./Mektuplar"):
            with self.subTest(cmd=cmd):
                self.assert_blocked("Bash", {"command": cmd})
        for cmd in ("ls OFIS/Mektuplarler", "cat tapuler.md", "python3 bin/ofis.py durum", "grep -rn sigortavi notlar.md"):
            with self.subTest(cmd=cmd):
                self.assert_allowed("Bash", {"command": cmd})

    def test_shell_quoting_does_not_hide_a_guarded_path(self):
        # Codex review 2026-11-12 (second pass): quotes and backslashes split the words the text match looks for.
        for cmd in ("echo '{}' > durum/sis\"\"tem/x.json", "echo x > durum/is''ler/x.json", "echo x > dur\\um/isler/x",
                    "claude \"--bg\" task", "claude '--background' x", "claude --b\\g x", "ls ~/Dev/z\"i\"m",
                    "cat \"Mek\"tuplar/inbox.md", "rm durum/\"duyurular\"/x.json"):
            with self.subTest(cmd=cmd):
                self.assert_blocked("Bash", {"command": cmd})
        for cmd in ("git commit -m \"Add the IT team's rotating shifts\"",
                    "git commit -m 'Guard: block quoted paths' -- bin/guard.py test/test_guard.py",
                    "python3 bin/ofis.py ekle --brief-dosya durum/taslak/is-1.json",
                    "python3 bin/ofis.py cevapla 2026-11-12-blog-soru.md \"Evet, devam et.\"",
                    "grep -E '^durum: bitti' \"$V\"/Isler/*/x.md",
                    "python3 bin/launch.py blog \"testleri çalıştır\"",
                    "echo \"it's fine\" | wc -c"):
            with self.subTest(cmd=cmd):
                self.assert_allowed("Bash", {"command": cmd})

    def test_relative_private_paths_are_blocked(self):
        # Codex review 2026-11-12: the private-folder check needed a leading slash.
        vault = VAULT
        for tool, field in (("Read", "file_path"), ("Write", "file_path"), ("Edit", "file_path"), ("Grep", "path"),
                            ("Glob", "path")):
            for path in ("Mektuplar/private.md", "./TAPU/a.md", "SİGORTA/x.md", "sigorta", "OFIS/../Mektuplar/a.md"):
                with self.subTest(tool=tool, path=path):
                    ti = {field: path, "content": "x"} if tool in ("Write", "Edit") else {field: path, "pattern": "x"}
                    self.assertEqual(self.raw({"tool_name": tool, "tool_input": ti, "cwd": vault})[0], 2)
        for cmd in ("cat Mektuplar/private.md", "ls TAPU/", "cat 'SİGORTA/x.md'", "cp a.md Mektuplar/b.md", "head \"tapu/x\""):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": vault})[0], 2)
        # a relative credential note name is blocked as before
        self.assertEqual(self.raw({"tool_name": "Read", "tool_input": {"file_path": "Marbaş/Şifre.md"}, "cwd": vault})[0], 2)
        # look-alike names stay allowed
        for path in ("OFIS/Mektuplarler.md", "OFIS/README.md", "test/test_tapux.py"):
            with self.subTest(path=path):
                self.assertEqual(self.raw({"tool_name": "Read", "tool_input": {"file_path": path}, "cwd": vault})[0], 0)
        self.assertEqual(self.raw({"tool_name": "Bash", "tool_input": {"command": "ls OFIS/Isler"}, "cwd": vault})[0], 0)


if __name__ == "__main__":
    unittest.main()
