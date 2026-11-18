"""Regression test for bin/guard.py: the everyday commands of the CEO session and of the agents working on this repo
must pass (the owner, 2026-11-12: over-blocking a destructive or protected-path command is fine; blocking an everyday
read-only or normal command is a bug). Shapes taken from this repository's sessions and from CLAUDE.md's
`claude agents` / `ofis.py` usage. Run: python3 -I test/test_guard_ceo.py"""
import json
import os
import subprocess
import sys
import unittest

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "guard.py")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahip_yasaklari  # noqa: E402,F401 (the tests' neutral config, test/sahip_yasaklari.py)
ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # this checkout
VAULT_OFIS = os.path.join(os.path.expanduser("~"), "Documents", "Obsidian Vault", "OFIS")  # bin/guard.py DEFAULT_VAULT
SCRATCH = "/private/tmp/claude-501/-Users-ornek-Dev-ajan-ofisi/scratch"

CEO_TRANSCRIPT_PROBE = (
    f"cd {ROOT} && sid="
    "$(curl -s http://127.0.0.1:8800/api/state | python3 -c "
    "\"import json,sys; print(json.load(sys.stdin)['ceo'].get('session_id',''))\") ; "
    "f=$(ls ~/.claude/projects/-Users-ornek-Dev-ajan-ofisi/$sid.jsonl 2>/dev/null); echo \"sid=$sid file=${f:+ok}\"; "
    "[ -n \"$f\" ] && { grep -c '\"type\":\"assistant\"' \"$f\"; python3 - \"$f\" <<'EOF'\n"
    "import json, sys\n"
    "n = sum(1 for _ in open(sys.argv[1]))\n"
    "print(n, 'satır / kayıt')\n"
    "print(\"toplam satır\", n)\n"
    "d = {\"a b\": [x for x in range(3)]}; print(d)\n"
    "EOF\n"
    "}")

EVERYDAY = [
    CEO_TRANSCRIPT_PROBE,
    "p=$(python3 -c \"import json,os;d=json.load(open('ofis.json'));print(d['ceo_session'], os.getcwd())\"); echo \"$p\"",
    "for f in W-*; do echo \"$f\"; done",
    "python3 bin/ofis.py durum",
    "git status --short | awk '{print $2}'",
    "git status --short | awk '{print $2}' | xargs -I{} echo {}",
    f"cat > {SCRATCH}/a.py <<'EOF'\nprint(\"merhaba / dünya\")\nx = 1 / 2\nEOF",
    f"cat >> {SCRATCH}/notlar.md <<EOF\n- satır / ayraç ~ ev . nokta\nEOF",
    "for f in test/test_*.py; do r=$(nice -n 10 python3 -I \"$f\" 2>&1 | grep -E \"^(Ran|OK|FAILED)\" | tr '\\n' ' '); "
    "echo \"$f: $r\"; done",
    "claude agents --json",
    "claude agents --json | python3 -c \"import json,sys; [print(a['name']) for a in json.load(sys.stdin) "
    "if a['name'].startswith('ofis-')]\"",
    "python3 bin/ofis.py ekle --brief-dosya durum/taslak/is-1.json",
    "python3 bin/ofis.py cevapla 2026-11-12-blog-soru.md --dosya durum/taslak/cevap-1.txt",
    "python3 bin/ofis.py zamanla listele",
    "python3 bin/ofis.py modeller",
    "python3 bin/autostart.py status",
    "ls -la durum/taslak/",
    "cat \"$HOME/Documents/Obsidian Vault/OFIS/04-Aktif-Durum/Index.md\"",
    f"grep -rn \"durum: bekliyor\" \"{VAULT_OFIS}/Kararlar\" | head -20",
    "tail -n 50 ~/Library/Logs/ofis/server.log",
    "git log --oneline -5 && git diff --stat",
    "curl -s http://127.0.0.1:8800/api/state | python3 -m json.tool | head -40",
    f"V=\"{VAULT_OFIS}\"; ls \"$V/Isler/Devam-Edenler\"",
    "if [ -f durum/ceo.json ]; then python3 -c \"import json;print(json.load(open('durum/ceo.json')))\"; fi",
    "[[ -d durum/taslak ]] && ls durum/taslak | wc -l",
    "case \"$x\" in a) echo a;; *) echo b;; esac",
    "find bin -name '*.py' -newer CLAUDE.md | sort",
    "ps aux | grep -c \"[c]laude\"",
    "wc -l bin/*.py | tail -1",
    "date +%F; uptime",
    "python3 - <<'EOF'\nimport json\nprint(json.dumps({'a': 1, 'yol': 'a/b'}))\nEOF",
    "while read -r l; do echo \"$l\"; done < /tmp/x.txt",
    "echo \"sid=${sid:-yok} n=${#arr[@]}\"",
    "x=`date +%s`; echo $((x / 60))",
    "{ git status --short; git stash list; } | head",
    "until [ -f /tmp/ready ]; do sleep 1; done",
    "cmd=ls; $cmd -la bin",
    f"cd {VAULT_OFIS} && ls Kararlar | tail -5",
    "nice -n 10 python3 -I test/test_guard.py 2>&1 | tail -3",
    "git diff -- bin/guard.py | head -100",
    "python3 bin/ofis.py bildir --is 2026-11-12-blog.md --durum bitti <<'EOF'\nTamam / bitti.\nEOF",
    # the standard commit form, with an apostrophe in the message
    "git commit -m \"$(cat <<'EOF'\nFix the guard's heredoc scan\n\nCo-Authored-By: x <x@example.com>\nEOF\n)\"",
    "msg=$(cat <<'EOF'\nThe owner's answer / today\nEOF\n); echo \"$msg\"",
    "[[ $x =~ ^[0-9]+$ ]] && echo num",
    "[[ \"$x\" =~ ok ]]",
    "[[ -n $x && $x =~ ok ]] || echo no",
    f"V=\"{VAULT_OFIS}\"; cd \"$V/04-Aktif-Durum\" && cat Index.md ../Isler/Devam-Edenler/a.md",
]


def run(cmd, cwd=ROOT):
    proc = subprocess.run([sys.executable, "-I", GUARD], capture_output=True, text=True, timeout=20,
                          input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}))
    return proc.returncode, proc.stderr


class EverydayCommandsPass(unittest.TestCase):
    def test_everyday_commands_are_never_blocked(self):
        self.assertGreaterEqual(len(EVERYDAY), 20)
        for cmd in EVERYDAY:
            with self.subTest(cmd=cmd[:80]):
                code, err = run(cmd)
                self.assertEqual(code, 0, err)

    def test_an_opaque_program_word_only_has_its_arguments_checked(self):
        # `$cmd args`: the program comes from a variable; its arguments still go through the path rule
        self.assertEqual(run("cmd=ls; $cmd -la bin")[0], 0)
        self.assertEqual(run("cmd=cat; $cmd durum/isler/x.json")[0], 2)
        self.assertEqual(run("$X ~/Documents/Obsidian\\ Vault/Mektuplar/a.md")[0], 2)


if __name__ == "__main__":
    unittest.main()
