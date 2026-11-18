"""Tests for the chat's notice cards and the Obsidian links (web/ofis-text.js: bildirimKarti, wikiParcalari,
obsidianUri, obsidianHref) under node; skipped without node. Every sample is the server's own wording (the emitters in
bin/ozet.py, bin/arge.py, bin/postoffice.py, bin/kontrol.py, bin/akis.py, bin/rapor.py, bin/model_secimi.py)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_web import NODE, WEB, run_js  # noqa: E402

STEM = "2026-11-13-091500-blog"

SAMPLES = {
    "sabah": ("Sabah özeti hazır: [[2026-11-13]] — 13 Kasım 2026 özeti Obsidian'da.\n"
              "- Dün biten: 4 iş (Kontrol geçen 3) · dünkü harcama $1.25 · 182 bin token\n"
              "- Bekleyen karar: 2\n- Takılan ya da durdurulan: 1\n- Bugün sırada: 3 iş, 1 zamanlanmış iş\n"
              "- Sunucu odası: 1 öneri, 0 domain sorunu"),
    "arge": (f"Ar-Ge raporu geldi: Yeni ücretsiz modeller ({STEM}). Obsidian notu: [[ArGe-2026-11-13]]. Kontrol geçti "
             f"(deneme 1; kanıt iş notunda). Selin'e tek satırla özetle. 2 denetçi önerisi kartı yazıldı "
             f"([[2026-11-13-arge-kart-1]], [[2026-11-13-arge-kart-2]]): Selin'e kartın beklediğini de söyle. Rapor:\n"
             "> GLM 5.3 yeni.\n> İki öneri var."),
    "soru": (f"blog soruyor (karar: 2026-11-13-blog-soru-1.md): Giriş hatası ({STEM}). Kararlar notu yazıldı; "
             "Selin'e sor, cevabı `ofis.py cevapla` ile ilet. Soru:\n> Hangi ekranda başlayayım?\n> İki seçenek var."),
    "bitti": (f"blog işi bitti: Giriş hatası (v2) ({STEM}). Kontrol geçti (deneme 2; kanıt iş notunda). Özet:\n"
              "> Giriş düzeldi.\n> 12 test geçti."),
    "bitti-kontrolsuz": f"blog işi bitti: Giriş hatası ({STEM}). Kontrol yok (yalnız projenin kendi raporu). Özet:\n> Tamam.",
    "takildi": (f"blog işi takıldı: Giriş hatası ({STEM}). Kontrol 2. denemede de geçmedi (çıkış kodu: 1); iş "
                "durduruldu. Selin'e sor: nasıl devam edilsin? Çıktının sonu:\n> FAILED test_login"),
    "takildi-rapor": f"blog işi takıldı: Giriş hatası ({STEM}). Neden:\n> Simülatör açılmıyor.",
    "durduruldu": (f"blog işi durduruldu: Giriş hatası ({STEM}). Kullanım sınırı aşıldı: API karşılığı ~$3.10 / ~$3.00; 182 bin token. "
                   "Oturum durduruldu. İş takıldı olarak işaretlendi. Selin'e sor: daha yüksek kullanım sınırıyla devam edilsin "
                   f"mi? Evet derse önce `ofis.py butce {STEM} <usd>`, sonra `ofis.py devam {STEM}`."),
    "yukseltme": (f"blog işi bir üst katmana taşındı: Giriş hatası ({STEM}). Kontrol 2. denemede de geçmedi (çıkış "
                  "kodu: 1); iş kolay yerine genel katmanında, temiz bir oturumda yeniden açıldı: "
                  "2026-11-13-101500-blog. Sırası gelince kendiliğinden başlar; Selin'e kısaca bildir. "
                  "Çıktının sonu:\n> FAILED"),
    "onay": ("blog akışı onay bekliyor: Profil sayfası (akis-1113-100000-blog). Kararlar notu yazıldı: "
             "2026-11-13-blog-akis-onay. Kartta kanıt var (plan özeti, Kontrol, değişiklik özeti, inceleme, "
             "maliyet). Hiçbir şey commit edilmedi. Selin'e sor; cevabını kelimesi kelimesine `ofis.py cevapla "
             "2026-11-13-blog-akis-onay` ile ilet (\"Onaylıyorum\" akışı kapatır; başka bir cevabı sen ele alırsın)."),
    "grup": ("blog grubu bitti: Giriş (giris). 2 iş: 2 bitti. Toplam kayıtlı harcama $1.20 · 90 bin token; "
             "doğrulanmış iş başına $0.60; yeniden iş 1; açık kalan 0. Rapor: [[giris]] (Obsidian'da OFIS/Raporlar). "
             "Selin'e kısaca bildir; log.md'ye bu grup için tek kayıt yaz. Sonra Karne/Duzeltmeler-blog dosyasının "
             "son satırlarına bak: aynı türden düzeltme iki kez geçiyorsa projenin CLAUDE.md'si için bir satır öner."),
    "kota": (f"blog işi: {STEM} kota döndüğü için kaldığı yerden devam ediyor (Giriş hatası ({STEM})). "
             "Selin'e tek satırla söyle."),
    "kota-ucuncu": (f"blog işi: {STEM} üçüncü kez kotaya takıldı; devam etsin mi? Giriş hatası ({STEM}): kota "
                    f"döndükten sonra iki kez kendiliğinden devam ettirildi, yine kotada durdu. Selin'e sor; yalnız "
                    f"onun sözüyle `ofis.py devam {STEM}`."),
    "izin": (f"blog işi izin onayı bekliyor: Giriş hatası ({STEM}). Oturum 7 dakikadır bir izin sorusunda duruyor; "
             "arka planda onu onaylayacak kimse yok, iş kendiliğinden ilerlemez. Ofis onu durdurmaz: Selin'e sade bir "
             "dille söyle ve ne yapılacağını sor; iptal ancak onun kararıyla."),
    "kadro": ("blog kadro önerisi: kod işler için sonraki 3 iş Kıdemli (Opus) yerine Uzman (Sonnet) ile denensin mi? "
              "Karar kartı: [[2026-11-13-blog-kod-model-onerisi]] (kanıt kartta). Selin'e tek satırla sor; cevabını "
              "`ofis.py cevapla` ile ilet."),
    "sunucu": "Sunucu odası (blog): blog.app açılmıyor (zaman aşımı). Selin'e tek satırla söyle; ofis hiçbir şeyi değiştirmez, karar Selin'in.",
    "akis-durdu": ("blog akışı durdu: Profil (akis-1113-100000-blog), adım 4 (kod-inceleme). İki inceleme turunda "
                   "da düzeltme istendi. Kalan adımlar kendiliğinden başlamaz. Selin'e sor: devam mı (`ofis.py "
                   "akis-karar akis-1113-100000-blog devam` — bu adım geçmiş sayılır), iptal mi? Son inceleme:\n"
                   "> KARAR: DÜZELT"),
}


def _gun_sonu_samples():
    """The end-of-day review's two notices in the server's own wording (bin/gunsonu.py bildirim / oneri_bildirimi)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
    import gunsonu
    st = {"gun": "2026-11-13", "is": "2026-11-13-201000-arge.md", "butce": 0.5, "atlananlar": ["2026-11-11"],
          "olcum": {"kotu": [{"tur": "tikandi"}, {"tur": "butce"}],
                    "sayilar": {"bitti": 5, "tikandi": 1, "basarisiz": 0, "kontrol": 4, "kontrol_ilk": 3, "usd": 1.23,
                                "token": 400000, "harcama_is": 6}},
          "rapor": {"durum": "bitti", "metin": "## Kök nedenler\n- Test komutu yanlış klasörde.",
                    "oneriler": [{"tur": "kod"}, {"tur": "kod"}, {"tur": "claude-md"}]}}
    cut = len(gunsonu.SYSTEM_PREFIX)
    return {"gunsonu": gunsonu.bildirim(st)[cut:], "gunsonu-oneri": gunsonu.oneri_bildirimi(st)[cut:]}


SAMPLES.update(_gun_sonu_samples())

YAKALA_RAPOR = ("## Ne bu\nBir ajan aracı [[sahte]].\n\n## Riskler\n- Veri dışarı çıkar\n  - alt madde\n\n"
                "| Seçenek | Not |\n|---|:--:|\n| kullan | hızlı |\n| geç | yavaş |\n\nÖNERİ: fikir al")


def _yakala_sample():
    """A Yakala result notice in the server's own wording (bin/yakala.py bildirim)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
    import yakala
    item = {"id": "y1234abcd", "tur": "url", "host": "github.com", "not_adi": "Yakala-2026-11-15-github-com-abcd",
            "is": "2026-11-15-100000-arge.md", "rapor": {"durum": "bitti", "oneri": "fikir al", "metin": YAKALA_RAPOR}}
    return {"yakala": yakala.bildirim(item)[len(yakala.SYSTEM_PREFIX):]}


SAMPLES.update(_yakala_sample())


def card(kind):
    return run_js(f"t.bildirimKarti({json.dumps(SAMPLES[kind])})")


def rows(c):
    return {k: v for k, v in c["satirlar"]}


CEO_ONLY = ("Selin'e", "ofis.py", "`", "log.md", "Karne/Duzeltmeler", "CLAUDE.md'si", "Ofis onu durdurmaz",
            "iptal ancak onun kararıyla", "yalnız onun sözüyle", "cevabını")


@unittest.skipUnless(NODE, "node is not installed")
class NoticeCardKindsTest(unittest.TestCase):
    def test_morning_summary(self):
        c = card("sabah")
        self.assertEqual((c["tur"], c["etiket"], c["baslik"]), ("sabah", "Sabah özeti", "Sabah özeti · 13 Kasım 2026"))
        self.assertEqual(c["satirlar"], [["Dün biten", "4 iş"], ["Kontrol geçen", "3"],
                                         ["Kullanım", "$1.25 · 182 bin token"], ["Bekleyen karar", "2"],
                                         ["Takılan", "1"], ["Sırada", "3 iş, 1 zamanlanmış iş"],
                                         ["Sunucu odası", "1 öneri, 0 domain sorunu"]])
        self.assertEqual((c["not"], c["klasor"]), ("2026-11-13", "Ozetler"))

    def test_arge_report(self):
        c = card("arge")
        self.assertEqual((c["tur"], c["baslik"]), ("arge", "Ar-Ge raporu: Yeni ücretsiz modeller"))
        self.assertEqual(rows(c), {"Rapor notu": "ArGe-2026-11-13", "Kontrol": "geçti (1. deneme)", "Kart sayısı": "2"})
        self.assertEqual((c["not"], c["klasor"], c["is"]), ("ArGe-2026-11-13", "ArGe", STEM))

    def test_question(self):
        c = card("soru")
        self.assertEqual((c["tur"], c["tone"], c["baslik"]), ("soru", "ask", "blog bir şey soruyor"))
        self.assertEqual(c["satirlar"], [["Proje", "blog"], ["İş", "Giriş hatası"],
                                         ["Soru", "Hangi ekranda başlayayım?"]])
        self.assertEqual((c["karar"], c["is"]), ("2026-11-13-blog-soru-1", STEM))

    def test_job_done_with_and_without_proof(self):
        c = card("bitti")
        self.assertEqual((c["tur"], c["tone"], c["baslik"]), ("bitti", "done", "blog işi bitti"))
        self.assertEqual(c["satirlar"], [["Proje", "blog"], ["İş", "Giriş hatası (v2)"],
                                         ["Kontrol", "geçti (2. deneme)"], ["Özet", "Giriş düzeldi."]])
        self.assertEqual(c["is"], STEM)
        self.assertEqual(rows(card("bitti-kontrolsuz"))["Kontrol"], "yok (yalnız projenin raporu)")

    def test_stuck(self):
        c = card("takildi")
        self.assertEqual((c["tur"], c["tone"], c["baslik"]), ("takildi", "blocked", "blog işi takıldı"))
        self.assertEqual(rows(c)["Neden"], "Kontrol 2. denemede de geçmedi (çıkış kodu: 1)")
        self.assertEqual(rows(card("takildi-rapor"))["Neden"], "Simülatör açılmıyor.")

    def test_stopped_over_budget(self):
        c = card("durduruldu")
        self.assertEqual((c["tur"], c["baslik"]), ("durduruldu", "blog işi durduruldu"))
        self.assertEqual(rows(c)["Neden"], "Kullanım sınırı aşıldı: API karşılığı ~$3.10 / ~$3.00; 182 bin token")
        self.assertEqual(rows(c)["Oturum"], "Oturum durduruldu.")

    def test_escalation(self):
        c = card("yukseltme")
        self.assertEqual((c["tur"], c["baslik"]), ("yukseltme", "blog işi bir üst katmana taşındı"))
        self.assertEqual(rows(c)["Katman"], "kolay → genel")
        self.assertEqual(rows(c)["Yeni iş"], "2026-11-13-101500-blog")

    def test_approval_waiting(self):
        c = card("onay")
        self.assertEqual((c["tur"], c["tone"], c["baslik"]), ("onay", "ask", "blog akışı onayını bekliyor"))
        self.assertEqual(c["satirlar"], [["Proje", "blog"], ["Akış", "Profil sayfası"],
                                         ["Karar kartı", "2026-11-13-blog-akis-onay"]])
        self.assertEqual(c["karar"], "2026-11-13-blog-akis-onay")

    def test_group_report(self):
        c = card("grup")
        self.assertEqual((c["tur"], c["baslik"]), ("grup", "blog grubu bitti: Giriş"))
        self.assertEqual(rows(c), {"İşler": "2 iş: 2 bitti", "Kullanım": "$1.20 · 90 bin token", "Açık kalan": "0",
                                   "Rapor": "giris"})
        self.assertEqual((c["not"], c["klasor"]), ("giris", "Raporlar"))

    def test_quota(self):
        c = card("kota")
        self.assertEqual((c["tur"], c["baslik"]), ("kota", "blog işi kota döndü, devam ediyor"))
        self.assertEqual(c["is"], STEM)
        self.assertEqual(card("kota-ucuncu")["baslik"], "blog işi üçüncü kez kotaya takıldı")

    def test_permission_and_model_card_and_server_room_and_stopped_workflow(self):
        c = card("izin")
        self.assertEqual((c["tur"], c["baslik"], rows(c)["Bekleme"]),
                         ("izin", "blog işi izin onayı bekliyor", "7 dakika"))
        c = card("kadro")
        self.assertEqual((c["tur"], rows(c)["Öneri"], c["karar"]),
                         ("kadro", "Kıdemli (Opus) yerine Uzman (Sonnet), 3 iş", "2026-11-13-blog-kod-model-onerisi"))
        c = card("sunucu")
        self.assertEqual((c["tur"], c["baslik"], rows(c)["Durum"]),
                         ("sunucu", "Sunucu odası: blog", "blog.app açılmıyor (zaman aşımı)"))
        c = card("akis-durdu")
        self.assertEqual((c["tur"], rows(c)["Adım"], rows(c)["Neden"]),
                         ("akis-durdu", "4 · kod-inceleme", "İki inceleme turunda da düzeltme istendi"))

    def test_end_of_day_review_and_its_suggestions(self):
        c = card("gunsonu")
        self.assertEqual((c["tur"], c["etiket"], c["baslik"]), ("gunsonu", "Gün sonu", "Gün sonu değerlendirmesi · 13 Kasım 2026"))
        self.assertEqual((c["not"], c["klasor"]), ("GunSonu-2026-11-13", "GunSonu"))
        r = rows(c)
        self.assertEqual(r["İşler"], "5 bitti, 1 takıldı, 0 başlatılamadı · Kontrol ilk denemede 3/4 · kullanım 400 bin token · "
                                     "API karşılığı ~$1.23")
        self.assertTrue(r["Kötü giden"].startswith("2 → değerlendirme işi 2026-11-13-201000-arge eklendi"), r)
        self.assertEqual(r["Atlanan gün"], "11 Kasım 2026")
        c = card("gunsonu-oneri")
        self.assertEqual((c["tur"], c["baslik"], c["is"]), ("gunsonu-oneri", "Gün sonu önerileri eklendi",
                                                            "2026-11-13-201000-arge"))
        self.assertEqual(rows(c), {"Not": "GunSonu-2026-11-13", "Kod düzeltmesi": "2", "Kural önerisi": "1"})
        self.assertIn("Test komutu yanlış klasörde.", c["ham"])

    def test_every_kind_has_an_icon_a_badge_and_a_title(self):
        for kind in SAMPLES:
            with self.subTest(kind):
                c = card(kind)
                self.assertTrue(c["ikon"] and c["etiket"] and c["baslik"], c)
                self.assertNotEqual(c["tur"], "diger")


@unittest.skipUnless(NODE, "node is not installed")
class NoticeCardHidingTest(unittest.TestCase):
    def test_ceo_only_parts_never_reach_the_card(self):
        for kind in SAMPLES:
            with self.subTest(kind):
                c = card(kind)
                shown = "\n".join([c["baslik"], c["ham"], *[f"{k} {v}" for k, v in c["satirlar"]]])
                for word in CEO_ONLY:
                    self.assertNotIn(word, shown)

    def test_the_raw_text_keeps_the_rest_without_quote_marks(self):
        c = card("durduruldu")
        self.assertIn("Kullanım sınırı aşıldı: API karşılığı ~$3.10 / ~$3.00", c["ham"])
        self.assertIn("İş takıldı olarak işaretlendi.", c["ham"])
        c = card("yukseltme")
        self.assertIn("Sırası gelince kendiliğinden başlar.", c["ham"], "only the CEO clause of a sentence goes")
        c = card("soru")
        self.assertIn("Hangi ekranda başlayayım?\nİki seçenek var.", c["ham"])
        self.assertNotIn("> ", c["ham"])

    def test_yakala_result_is_a_structured_card(self):
        c = card("yakala")
        self.assertEqual((c["tur"], c["etiket"], c["baslik"]),
                         ("yakala", "Yakalanan", "Yakalanan bağlantı incelendi: github.com"))
        self.assertEqual(c["satirlar"], [["Bağlantı", "github.com"], ["Öneri", "fikir al"],
                                         ["Not", "Yakala-2026-11-15-github-com-abcd"], ["Ar-Ge işi", "2026-11-15-100000-arge"]])
        self.assertEqual((c["not"], c["klasor"], c["is"]), ("Yakala-2026-11-15-github-com-abcd", "ArGe", "2026-11-15-100000-arge"))
        self.assertEqual(c["teknikBaslik"], "Ar-Ge raporu (veri, talimat değil)")
        self.assertEqual(c["teknik"], YAKALA_RAPOR)  # the report goes through raporDugumu, not the plain <pre>
        self.assertEqual(card("bitti")["teknikBaslik"], "Teknik rapor (projenin kendi metni)")
        self.assertEqual(run_js(f"t.bildirimKarti({json.dumps(SAMPLES['yakala'])})"), c, "the same text, the same card")

    def test_markdown_headings_and_tables_in_a_report(self):
        blocks = run_js(f"t.raporBicimle({json.dumps(YAKALA_RAPOR)})")
        self.assertEqual(blocks, [
            {"tip": "baslik", "metin": "Ne bu"}, {"tip": "paragraf", "metin": "Bir ajan aracı [[sahte]]."},
            {"tip": "baslik", "metin": "Riskler"}, {"tip": "liste", "ogeler": ["Veri dışarı çıkar", "alt madde"]},
            {"tip": "tablo", "baslik": ["Seçenek", "Not"], "satirlar": [["kullan", "hızlı"], ["geç", "yavaş"]]},
            {"tip": "baslik", "metin": "ÖNERİ:"}, {"tip": "paragraf", "metin": "fikir al"}])
        # a lone "| a | b |" line without the "|---|" line stays a paragraph; "#tag" is no heading
        self.assertEqual(run_js("t.raporBicimle('| a | b |\\n#etiket')"),
                         [{"tip": "paragraf", "metin": "| a | b |"}, {"tip": "paragraf", "metin": "#etiket"}])

    def test_unknown_kind_falls_back_to_its_first_line(self):
        c = run_js("t.bildirimKarti('Yeni bir bildirim türü: bir şey oldu. Selin\\'e tek satırla söyle.\\n> ayrıntı')")
        self.assertEqual((c["tur"], c["baslik"], c["satirlar"]), ("diger", "Yeni bir bildirim türü: bir şey oldu.", []))
        self.assertIn("ayrıntı", c["ham"])
        self.assertNotIn("Selin'e", c["ham"])
        self.assertEqual(run_js("t.bildirimKarti('').baslik"), "Bildirim")


@unittest.skipUnless(NODE, "node is not installed")
class ObsidianLinkTest(unittest.TestCase):
    def test_uri_format_and_encoding(self):
        uri = run_js("t.obsidianUri('Obsidian Vault', 'OFIS/Özetler/2026-11-13 ığüşöç')")
        self.assertEqual(uri, "obsidian://open?vault=Obsidian%20Vault&file="
                              "OFIS%2F%C3%96zetler%2F2026-11-13%20%C4%B1%C4%9F%C3%BC%C5%9F%C3%B6%C3%A7")

    def test_only_paths_under_ofis(self):
        for path in ("Mektuplar/x", "../OFIS/x", "OFIS/../x", "/OFIS/x", "", "OFIS", "OFIS/a/./b", "OFISX/a"):
            with self.subTest(path):
                self.assertEqual(run_js(f"t.obsidianUri('Kasa', {json.dumps(path)})"), "")
        self.assertEqual(run_js("t.obsidianUri('', 'OFIS/a')"), "")

    def test_only_the_obsidian_scheme_is_ever_an_href(self):
        self.assertEqual(run_js("t.obsidianHref('obsidian://open?vault=K&file=OFIS%2Fa')"),
                         "obsidian://open?vault=K&file=OFIS%2Fa")
        for bad in ("javascript:alert(1)", "JAVASCRIPT:x", " obsidian://open?x", "obsidian://new?x",
                    "https://x", "data:text/html,x", "obsidian://open?vault=K&file=x\n"):
            with self.subTest(bad):
                self.assertEqual(run_js(f"t.obsidianHref({json.dumps(bad)})"), "")

    def test_wikilinks_are_split_out_of_text(self):
        parts = run_js("t.wikiParcalari('Özet: [[2026-11-13]] ve [[giris|Giriş raporu]], [[a#b]] [[]] [x]')")
        self.assertEqual(parts, [{"metin": "Özet: "}, {"not": "2026-11-13", "gorunen": "2026-11-13"},
                                 {"metin": " ve "}, {"not": "giris", "gorunen": "Giriş raporu"}, {"metin": ", "},
                                 {"not": "a", "gorunen": "a"}, {"metin": " [[]] [x]"}])
        self.assertEqual(run_js("t.wikiParcalari('düz metin')"), [{"metin": "düz metin"}])
        self.assertEqual(run_js("t.wikiParcalari('[[../x]] [[a/b]]')"), [{"metin": "[[../x]] [[a/b]]"}],
                         "a path is never a note name")

    def test_the_folder_hint_of_a_note_follows_the_notice_kind(self):
        self.assertEqual(run_js("t.notKlasoru('2026-11-13', 'sabah')"), "Ozetler")
        self.assertEqual(run_js("t.notKlasoru('ArGe-2026-11-13', '')"), "ArGe")
        self.assertEqual(run_js("t.notKlasoru('GunSonu-2026-11-13', '')"), "GunSonu")
        self.assertEqual(run_js("t.notKlasoru('2026-11-13-blog-soru-1', 'soru')"), "Kararlar")
        self.assertEqual(run_js("t.notKlasoru('giris', 'grup')"), "Raporlar")
        self.assertEqual(run_js("t.notKlasoru('x', '')"), "")


class PageWiringTest(unittest.TestCase):
    def test_the_page_uses_the_card_and_builds_links_safely(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("bildirimKarti(", app)
        self.assertIn("'Ayrıntı'", app)
        self.assertIn("/api/not-yolu?ad=", app)
        self.assertIn("obsidianHref(", app)
        self.assertIn("setAttribute('href'", app)
        self.assertNotRegex(app, r"\.href\s*=")


if __name__ == "__main__":
    unittest.main()
