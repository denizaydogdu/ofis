"""Tests for bin/uzmanlik.py: the role profiles (roller/*.json), the deterministic routing of a job to a specialisation,
the contract's "Rolün" section and the display notes OFIS/Calisanlar/<uzmanlik>.md (plan "Sonraki iş (9)", step 2,
owner decision 2026-11-13)."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402,F401  (isolates the jobs lock)
import uzmanlik  # noqa: E402

ROLLER = os.path.join(HERE, "..", "roller")


def sec(baslik, hedef="", **kw):
    brief = {"hedef": hedef or baslik}
    for key in ("kisitlar",):
        if key in kw:
            brief[key] = kw.pop(key)
    return uzmanlik.sec(baslik, brief, **kw)


class ProfilesTest(unittest.TestCase):
    def test_every_profile_is_there_and_valid(self):
        p = uzmanlik.profiller()
        self.assertEqual(set(p), {"backend", "ui", "mobil", "test", "analiz", "genel", "guvenlik"})
        for key, prof in p.items():
            self.assertEqual(prof["ad"], key)
            for field in ("yetkinlik", "bilgi", "teslim", "dur_sor", "asla"):
                self.assertTrue(prof[field], (key, field))
        self.assertEqual(p["test"]["baslik"], "Tester")
        self.assertEqual(p["analiz"]["dosya_desenleri"], [])
        self.assertIn("*.dart", p["mobil"]["dosya_desenleri"])

    def test_a_bad_profile_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(ROLLER, "ui.json"), encoding="utf-8") as f:
                good = json.load(f)
            for broken in ({**good, "ad": "baska"}, {k: v for k, v in good.items() if k != "teslim"},
                           {**good, "fazla": 1}, {**good, "dosya_desenleri": "*.css"}, {**good, "asla": [3]}):
                with open(os.path.join(tmp, "ui.json"), "w", encoding="utf-8") as f:
                    json.dump(broken, f)
                with self.assertRaises(uzmanlik.ProfilHatasi):
                    uzmanlik.profiller(tmp, cache=False)

    def test_a_missing_folder_leaves_only_the_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(uzmanlik.ProfilHatasi):
                uzmanlik.profiller(os.path.join(tmp, "yok"), cache=False)

    def test_titles_and_role_text(self):
        self.assertEqual(uzmanlik.rol_metni("opus", "backend"), "Kıdemli Backend")
        self.assertEqual(uzmanlik.rol_metni("claude-haiku-4-5", "mobil"), "Stajyer Mobil")
        self.assertEqual(uzmanlik.rol_metni("sonnet", "ui"), "Uzman UI")
        self.assertEqual(uzmanlik.rol_metni("opus", "test"), "Kıdemli Tester")
        self.assertEqual(uzmanlik.rol_metni("sonnet", "genel"), "Uzman")  # the fallback adds nothing
        self.assertEqual(uzmanlik.rol_metni("fable", "analiz"), "Genel Müdür")  # the Genel Müdür has no specialty
        self.assertEqual(uzmanlik.rol_metni("opus", ""), "Kıdemli")
        self.assertEqual(uzmanlik.rol_metni("opus", "uydurma"), "Kıdemli")


class FoldTest(unittest.TestCase):
    def test_turkish_letters_fold_with_and_without_diacritics(self):
        self.assertEqual(uzmanlik.katla("ARAYÜZ İÇİN GÜVENLİK AÇIĞI"), uzmanlik.katla("arayuz icin guvenlik acigi"))
        self.assertEqual(uzmanlik.katla("Işık ŞÇĞ"), "isik scg")


class PathRoutingTest(unittest.TestCase):
    def test_a_dart_file_routes_to_mobil_with_the_path_in_the_reason(self):
        s = sec("Giriş hatası", "lib/login.dart içinde giriş hatasını düzelt", katman="kod")
        self.assertEqual(s["uzmanlik"], "mobil")
        self.assertEqual(s["kaynak"], "kural")
        self.assertIn("lib/login.dart", s["neden"])
        self.assertTrue(s["neden"].endswith("→ mobil"), s["neden"])

    def test_java_under_backend_is_backend(self):
        s = sec("Sipariş", "backend/src/main/java/com/x/OrderService.java dosyasında toplamı düzelt", katman="kod")
        self.assertEqual(s["uzmanlik"], "backend")

    def test_a_kotlin_file_under_android_is_mobil(self):
        s = sec("Bildirim", "android/app/src/main/kotlin/MainActivity.kt bildirimi açsın", katman="kod")
        self.assertEqual(s["uzmanlik"], "mobil")

    def test_test_files_are_test(self):
        self.assertEqual(sec("Test", "test/login_test.dart dosyasını tamamla", katman="kod")["uzmanlik"], "test")
        self.assertEqual(sec("Test", "tests/test_reset.py kırık, onar", katman="kod")["uzmanlik"], "test")
        self.assertEqual(sec("Test", "src/cart.spec.ts güncellensin", katman="kod")["uzmanlik"], "test")

    def test_web_files_are_ui(self):
        self.assertEqual(sec("Buton", "src/components/Button.tsx boyutu", katman="kod")["uzmanlik"], "ui")
        self.assertEqual(sec("Stil", "web/style.css içindeki rengi düzelt", katman="kod")["uzmanlik"], "ui")

    def test_the_kisitlar_count_too(self):
        s = sec("Hata", "Uygulamadaki hatayı düzelt", kisitlar="Yalnız lib/cart/cart_page.dart değişsin", katman="kod")
        self.assertEqual(s["uzmanlik"], "mobil")

    def test_paths_beat_a_weak_test_word(self):
        s = sec("Giriş", "lib/login.dart düzelt; testler geçsin", katman="kod")
        self.assertEqual(s["uzmanlik"], "mobil")

    def test_a_reason_never_carries_raw_brief_text(self):
        s = sec("x", "lib/a<b>`$(rm)`.dart ve [[not]] lib/ok.dart", katman="kod")
        self.assertNotIn("<", s["neden"])
        self.assertNotIn("[[", s["neden"])
        self.assertNotIn("$", s["neden"])
        self.assertLessEqual(len(s["neden"]), uzmanlik.NEDEN_SINIRI)


class KeywordRoutingTest(unittest.TestCase):
    def test_turkish_keywords_with_and_without_diacritics(self):
        for text in ("Arayüzde butonun rengini değiştir", "Arayuzde butonun rengini degistir",
                     "ARAYÜZDE BUTONUN RENGİNİ DEĞİŞTİR"):
            self.assertEqual(sec("Renk", text)["uzmanlik"], "ui", text)
        for text in ("Gereksinimleri ve kabul kriterlerini çıkar", "gereksinimleri ve kabul kriterlerini cikar"):
            s = sec("Analiz", text)
            self.assertEqual(s["uzmanlik"], "analiz", text)
            self.assertIn("gereksinim", uzmanlik.katla(s["neden"]))

    def test_english_keywords(self):
        self.assertEqual(sec("Endpoint", "Add a REST endpoint for orders")["uzmanlik"], "backend")
        self.assertEqual(sec("Story", "Write user stories and acceptance criteria")["uzmanlik"], "analiz")

    def test_api_with_a_turkish_suffix(self):
        self.assertEqual(sec("API", "API'ye yeni bir sipariş ucu ekle")["uzmanlik"], "backend")

    def test_security_words_route_to_guvenlik(self):
        self.assertEqual(sec("Açık", "GÜVENLİK AÇIĞINI kapat: XSS")["uzmanlik"], "guvenlik")

    def test_testflight_is_mobil_not_test(self):
        self.assertEqual(sec("Yayın", "TestFlight yüklemesi için sürüm numarasını artır")["uzmanlik"], "mobil")

    def test_a_short_keyword_never_matches_inside_a_longer_word(self):
        # "rest" must not match "restoran", "ui" not "uint"
        self.assertEqual(sec("Sıralama", "restoran listesini sırala")["uzmanlik"], "genel")


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def folder(self, *parts):
        p = os.path.join(self.root, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def touch(self, *parts):
        os.makedirs(os.path.join(self.root, *parts[:-1]), exist_ok=True)
        open(os.path.join(self.root, *parts), "w").close()

    def test_a_flutter_project_leans_to_mobil_for_kod_work(self):
        self.touch("kasa", "pubspec.yaml")
        self.folder("kasa", "lib")
        duzen = uzmanlik.proje_duzeni(os.path.join(self.root, "kasa"))
        self.assertEqual(duzen["egilim"], "mobil")
        s = sec("Çökme", "Bölüm 3'te oyun çöküyor, düzelt", katman="kod", duzen=duzen)
        self.assertEqual(s["uzmanlik"], "mobil")
        self.assertIn("pubspec.yaml", s["neden"])

    def test_the_layout_never_decides_a_reading_job(self):
        self.touch("kasa", "pubspec.yaml")
        duzen = uzmanlik.proje_duzeni(os.path.join(self.root, "kasa"))
        s = sec("Özet", "Yapılacaklar listesini özetle", katman="genel", duzen=duzen)
        self.assertEqual(s["uzmanlik"], "genel")
        self.assertIn("belirsiz", s["neden"])

    def test_a_nested_flutter_app_is_found_two_levels_down(self):
        self.touch("harita", "apps", "mobile", "pubspec.yaml")
        self.touch("harita", "apps", "server", "build.gradle.kts")
        duzen = uzmanlik.proje_duzeni(os.path.join(self.root, "harita"))
        self.assertEqual(duzen["egilim"], "mobil")
        self.assertIn("backend", duzen["turler"])

    def test_a_maven_project_leans_to_backend(self):
        self.touch("atolye", "atolyeApi", "pom.xml")
        self.touch("atolye", "atolyeUI", "pom.xml")
        self.assertEqual(uzmanlik.proje_duzeni(os.path.join(self.root, "atolye"))["egilim"], "backend")

    def test_keywords_beat_the_layout(self):
        self.touch("blog", "mobile", "pubspec.yaml")
        self.touch("blog", "backend", "pom.xml")
        duzen = uzmanlik.proje_duzeni(os.path.join(self.root, "blog"))
        s = sec("Uç", "Sunucuya yeni bir API endpoint'i ekle", katman="kod", duzen=duzen)
        self.assertEqual(s["uzmanlik"], "backend")

    def test_the_scan_never_follows_a_symlink(self):
        other = self.folder("baska")
        open(os.path.join(other, "pubspec.yaml"), "w").close()
        proj = self.folder("proje")
        os.symlink(other, os.path.join(proj, "mobile"))
        os.symlink(os.path.join(other, "pubspec.yaml"), os.path.join(proj, "pubspec.yaml"))
        self.assertEqual(uzmanlik.proje_duzeni(proj)["egilim"], "")
        self.assertEqual(uzmanlik.proje_duzeni(os.path.join(proj, "mobile"))["egilim"], "")  # the folder itself

    def test_a_zim_path_is_never_scanned(self):
        self.touch("zim", "pubspec.yaml")
        self.assertEqual(uzmanlik.proje_duzeni(os.path.join(self.root, "zim"))["egilim"], "")
        self.touch("proje2", "zim", "pubspec.yaml")
        self.assertEqual(uzmanlik.proje_duzeni(os.path.join(self.root, "proje2"))["egilim"], "")

    def test_a_missing_folder_has_no_layout(self):
        self.assertEqual(uzmanlik.proje_duzeni(os.path.join(self.root, "yok"))["egilim"], "")
        self.assertEqual(uzmanlik.proje_duzeni(None)["egilim"], "")

    def test_only_names_are_read(self):
        self.touch("p", "pubspec.yaml")
        with open(os.path.join(self.root, "p", "pubspec.yaml"), "w") as f:
            f.write("backend api server")
        self.assertEqual(uzmanlik.proje_duzeni(os.path.join(self.root, "p"))["egilim"], "mobil")


class TierAndStepTest(unittest.TestCase):
    def test_a_review_job_is_test(self):
        s = sec("İnceleme", "Son değişikliği incele", katman="inceleme")
        self.assertEqual(s["uzmanlik"], "test")
        self.assertIn("inceleme", s["neden"])

    def test_a_planning_job_without_signals_is_analiz(self):
        self.assertEqual(sec("Plan", "Bildirimler özelliğini işlere böl", katman="planlama")["uzmanlik"], "analiz")

    def test_workflow_review_steps_follow_the_step(self):
        s = sec("Kod incelemesi: x", "lib/a.dart", katman="inceleme", adim="kod-inceleme")
        self.assertEqual((s["uzmanlik"], s["kaynak"]), ("test", "adim"))
        s = sec("Plan incelemesi: x", "backend/x.java", katman="inceleme", adim="plan-inceleme")
        self.assertEqual((s["uzmanlik"], s["kaynak"]), ("analiz", "adim"))

    def test_the_plan_text_routes_a_kod_step(self):
        s = sec("Bildirim", "Bildirim ayarı eklensin", katman="kod",
                plan="1. backend/src/main/java/NotificationController.java ekle\n2. NotificationService.java")
        self.assertEqual(s["uzmanlik"], "backend")


class OverrideAndAmbiguityTest(unittest.TestCase):
    def test_an_explicit_choice_wins(self):
        s = sec("Giriş", "lib/login.dart düzelt", katman="kod", secilen="ui")
        self.assertEqual((s["uzmanlik"], s["kaynak"]), ("ui", "elle"))
        self.assertIn("elle", s["neden"])

    def test_an_unknown_choice_is_refused(self):
        with self.assertRaises(uzmanlik.Gecersiz):
            sec("Giriş", "lib/login.dart", secilen="devops")
        with self.assertRaises(uzmanlik.Gecersiz):
            uzmanlik.dogrula("Backend ")

    def test_a_tie_falls_back_to_genel(self):
        s = sec("Karışık", "lib/a.dart ve backend/src/B.java birlikte değişsin", katman="kod")
        self.assertEqual(s["uzmanlik"], "genel")
        self.assertIn("belirsiz", s["neden"])

    def test_nothing_at_all_is_genel(self):
        s = sec("Durum", "Projenin durumunu yaz", katman="kolay")
        self.assertEqual((s["uzmanlik"], s["kaynak"]), ("genel", "kural"))
        self.assertEqual(s["neden"], "belirsiz → genel")


class ContractTest(unittest.TestCase):
    def test_the_section_names_the_role_and_its_rules(self):
        text = uzmanlik.sozlesme_bolumu("backend", "opus")
        self.assertIn("Rolün: Kıdemli Backend", text)
        for word in ("Yetkinlik", "Önce oku", "Teslim", "Dur ve sor", "Asla"):
            self.assertIn(word, text)
        self.assertLessEqual(len(text), uzmanlik.SOZLESME_SINIRI)
        self.assertTrue(text.startswith("\n- "))

    def test_no_shipped_profile_is_cut_and_the_never_rules_come_first(self):
        for key in uzmanlik.profiller():
            for model in ("haiku", "sonnet", "opus", "fable"):
                text = uzmanlik.sozlesme_bolumu(key, model)
                self.assertFalse(text.endswith("…"), (key, model, len(text)))
        text = uzmanlik.sozlesme_bolumu("mobil", "opus")
        self.assertLess(text.index("Asla:"), text.index("Yetkinlik:"))
        self.assertIn("AndroidManifest.xml", text)

    def test_no_section_without_a_known_specialisation(self):
        self.assertEqual(uzmanlik.sozlesme_bolumu("", "opus"), "")
        self.assertEqual(uzmanlik.sozlesme_bolumu("uydurma", "opus"), "")

    def test_a_long_profile_is_cut(self):
        prof = dict(uzmanlik.profiller()["ui"])
        prof["yetkinlik"] = ["x" * 400] * 6
        text = uzmanlik.sozlesme_bolumu("ui", "sonnet", profiller={"ui": prof})
        self.assertLessEqual(len(text), uzmanlik.SOZLESME_SINIRI)
        self.assertIn("Rolün: Uzman UI", text)


class NotesTest(unittest.TestCase):
    def test_the_notes_are_written_once_and_only_when_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = os.path.join(tmp, "OFIS")
            os.makedirs(vault)
            written = uzmanlik.yaz_notlar(vault)
            self.assertEqual(sorted(written), sorted(uzmanlik.profiller()))
            with open(os.path.join(vault, "Calisanlar", "mobil.md"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("tur: rol-profili", text)
            self.assertIn("# Mobil", text)
            self.assertIn("*.dart", text)
            self.assertIn("roller/mobil.json", text)
            self.assertEqual(uzmanlik.yaz_notlar(vault), [])

    def test_never_through_a_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = os.path.join(tmp, "OFIS")
            os.makedirs(vault)
            other = os.path.join(tmp, "baska")
            os.makedirs(other)
            os.symlink(other, os.path.join(vault, "Calisanlar"))
            self.assertEqual(uzmanlik.yaz_notlar(vault), [])
            self.assertEqual(os.listdir(other), [])


if __name__ == "__main__":
    unittest.main()
