"""Tests for bin/uyarilar.py: the deterministic guard-rails of `ofis.py ekle` / `akis` / `zamanla ekle` (B3 audit,
owner decision 2026-11-12). Pure functions, no files."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
import uyarilar  # noqa: E402

TIERS = {"planlama": {"model": "fable", "effort": "high", "butce_usd": 3},
         "kod": {"model": "opus", "effort": "high", "butce_usd": 6},
         "inceleme": {"model": "opus", "effort": "high", "butce_usd": 1},
         "genel": {"model": "sonnet", "effort": "medium", "butce_usd": 1.5},
         "kolay": {"model": "haiku", "effort": "low", "butce_usd": 0.3}}
CFG = {"projects": {"blog": {"path": "/x"}}, "tiers": TIERS, "default_tier": "genel", "default_budget_usd": 3,
       "default_max_calls": {"kolay": 15, "genel": 40, "kod": 120, "inceleme": 60, "planlama": 60}}


def row(tier="kolay", model="haiku", cost="0.0100", calls="3", project="blog", deneme=""):
    return {"Proje": project, "Katman": tier, "Model": model, "Maliyet ($)": cost, "Çağrı": calls, "Deneme": deneme}


def warn(tier="kolay", hedef="Dal adını ve son üç commiti CEO'ya bildir.", kontrol="test -s rapor.md", model=None,
         explicit_model=False, budget="0.3", rows=(), calls=None):
    brief = {"hedef": hedef, "kontrol": kontrol}
    return uyarilar.ekle_uyarilari(CFG, "blog", tier, model or TIERS[tier]["model"], explicit_model, budget,
                                   brief, list(rows), call_limit=calls)


class KontrolStrengthTest(unittest.TestCase):
    def test_commands_that_always_pass_are_certain(self):
        for cmd in ("true", ":", "exit 0", "echo tamam", "printf ok", "pwd", "ls", "ls -la", "ls .", "git status",
                    "git status --short", "git rev-parse --is-inside-work-tree", "git rev-parse --abbrev-ref HEAD",
                    "git log --oneline -3", "pytest -q || true", "pytest -q ; true", "pytest -q; exit 0",
                    "make test || :", "echo a && echo b", "grep -c x f.txt | wc -l", "FOO=1 echo x",
                    "echo done > out.txt", "true && pwd", "pytest -q 2>&1 | tail -5", "ls 2>/dev/null",
                    "pytest -q | tee log.txt", "pytest -q 2>&1 | tee -a log.txt"):
            self.assertEqual(uyarilar.kontrol_gucu(cmd), "kesin", cmd)

    def test_existence_only_checks_are_weak(self):
        for cmd in ("cat rapor.md", "ls rapor.md", "git rev-parse --verify feature-x", "cat a.txt && echo ok"):
            self.assertEqual(uyarilar.kontrol_gucu(cmd), "zayif", cmd)

    def test_real_checks_are_not_flagged(self):
        for cmd in ("pytest -q tests/test_login.py", "test -s rapor.md && grep -q 'W-116' rapor.md",
                    "./gradlew test --tests 'Login*'", "flutter test test/login_test.dart", "[ -f x ]",
                    "git diff --exit-code", "git diff --quiet", "true && pytest -q", "echo x | grep -q x",
                    "bash -c 'true'", "if true; then echo; fi", "$(true)", "pytest -q || true && false",
                    "grep -q x f", "diff a b", "", "set -o pipefail; pytest -q | tail -5",
                    # review 2026-11-12: errexit / trap make an earlier command decide; `#` is no comment inside a word
                    "set -e; pytest -q; echo OK", "set -eu; pytest -q; true", "set -o errexit; pytest -q; echo OK",
                    "set -euo pipefail; pytest -q; echo OK", "trap 'exit 1' ERR; pytest -q; true",
                    'echo "== tests" # banner\npytest -q', "echo a#b && pytest -q",
                    "pytest -q | tee log.txt; echo ${PIPESTATUS[0]}"):
            self.assertEqual(uyarilar.kontrol_gucu(cmd), "", cmd)


class EkleWarningsTest(unittest.TestCase):
    def test_a_clean_kolay_job_has_no_warning(self):
        self.assertEqual(warn(), [])

    def test_kod_refusal_only_for_a_certain_kontrol(self):
        self.assertIn("başarısız olamaz", uyarilar.kontrol_reddi("kod", "git status"))
        self.assertIn("başarısız olamaz", uyarilar.kontrol_reddi("kod", "pytest -q || true"))
        self.assertIsNone(uyarilar.kontrol_reddi("kod", "cat rapor.md"), "weak: a warning, never a refusal")
        self.assertIsNone(uyarilar.kontrol_reddi("kod", "pytest -q"))
        self.assertIsNone(uyarilar.kontrol_reddi("kolay", "true"), "other tiers: a warning")
        self.assertIsNone(uyarilar.kontrol_reddi("kod", ""))

    def test_warns_on_a_kontrol_that_cannot_fail(self):
        out = warn(kontrol="git rev-parse --is-inside-work-tree")
        self.assertEqual(len(out), 1)
        self.assertIn("her zaman geçer", out[0])
        weak = warn(kontrol="cat rapor.md")
        self.assertEqual(len(weak), 1)
        self.assertIn("yalnız", weak[0])
        kod = warn("kod", kontrol="ls x.txt", hedef="lib/a.dart dosyasını düzelt.", budget="6")
        self.assertTrue(any("yalnız" in w for w in kod), kod)

    def test_warns_when_a_change_brief_is_not_kod(self):
        for hedef in ("lib/login.dart dosyasındaki hatayı düzelt.", "README'yi güncelle ve yeni bölüm ekle.",
                      "Giriş ekranını değiştir.", "Eski testleri sil.", "pubspec.yaml sürümünü 2.1 yap."):
            out = warn("genel", hedef=hedef, budget="1.5")
            self.assertTrue(any("kod katmanı" in w for w in out), (hedef, out))
        self.assertEqual(warn("kod", hedef="lib/login.dart dosyasını düzelt.", kontrol="pytest -q", budget="6"), [])

    def test_does_not_warn_on_a_read_only_kolay_brief(self):
        for hedef in ("Dal adını ve son üç commiti CEO'ya bildir.",
                      "Salt okuma: lib/login.dart dosyasını oku ve ne yaptığını özetle. Hiçbir dosyayı değiştirme.",
                      "git log --oneline -1 çalıştır ve sonucu tek cümleyle bildir.",
                      "Projenin durumunu özetle; dosya değiştirme, commit atma.",
                      "Testleri çalıştır ve sonucu rapor.md dosyasına yaz.",
                      "Son commit mesajını özetle (read-only, do not edit).",
                      "'python3 /x/bin/ofis.py iptal YOK.md' komutunu dene ve engellenip engellenmediğini bildir."):
            self.assertFalse(any("kod katmanı" in w for w in warn(hedef=hedef)), hedef)

    def test_warns_on_an_open_ended_kolay_hedef(self):
        for hedef in ("Giriş akışını araştır ve bir öneri yaz.", "Mimariyi analiz et.", "Ödeme akışını değerlendir.",
                      "Yeni bir ekran tasarla.", "Kod tabanını incele.", "x" * 500):
            out = warn(hedef=hedef)
            self.assertTrue(any("açık uçlu" in w for w in out), (hedef, out))
        out = warn(kontrol="")
        self.assertTrue(any("Kontrol yok" in w for w in out), out)
        self.assertFalse(any("açık uçlu" in w for w in warn("genel", hedef="Mimariyi analiz et.", budget="1.5")))

    def test_warns_on_an_explicit_model_override(self):
        out = warn(model="sonnet", explicit_model=True)
        self.assertEqual(len(out), 1)
        self.assertIn("--model sonnet", out[0])
        self.assertIn("kanıt sayılmaz", out[0])
        same = warn(model="haiku", explicit_model=True)
        self.assertIn("eşlemeyle aynı", same[0])

    def test_warns_when_the_budget_is_far_from_the_tiers_typical_spend(self):
        rows = [row(cost=c) for c in ("0.0100", "0.0120", "0.0800")]
        low = warn(budget="0.05", rows=rows)
        self.assertTrue(any("en pahalısının" in w for w in low), low)
        high = warn(budget="5", rows=rows)
        self.assertTrue(any("katı" in w for w in high), high)
        self.assertEqual(warn(budget="0.3", rows=rows), [])
        self.assertEqual(warn(budget="0.001", rows=rows[:2]), [], "fewer than three rows: no evidence")
        other = [row(model="sonnet", cost="0.0100")] * 3
        self.assertEqual(warn(budget="5", rows=other), [], "only the same model's rows count")

    def test_call_limit_misuse(self):
        self.assertEqual(warn(calls=15), [])
        out = warn(calls=40)
        self.assertTrue(any("çağrı sınırı 40" in w for w in out), out)
        rows = [row("kod", "opus", cost="0.5", calls="5")] * 3
        out = warn("kod", hedef="lib/a.dart dosyasını düzelt.", kontrol="pytest -q", budget="6", rows=rows,
                   calls=200)
        self.assertTrue(any("kullanım sınırı" in w and "çağrıda" in w for w in out), out)
        self.assertTrue(any("çağrı sınırı 200" in w for w in out), out)

    def test_review_share_warning(self):
        rows = [row("inceleme", "opus", cost="0.4215", calls="2")]
        self.assertTrue(uyarilar.akis_uyarilari("blog", {"kod-inceleme": "0.4"}, rows))
        self.assertEqual(uyarilar.akis_uyarilari("blog", {"kod-inceleme": "1.4"}, rows), [])
        self.assertEqual(uyarilar.akis_uyarilari("blog", {"kod-inceleme": "0.4"},
                                                 [row("inceleme", "heyet", cost="0.9")]), [],
                         "the review panel's rows are not a Claude review")


if __name__ == "__main__":
    unittest.main()
