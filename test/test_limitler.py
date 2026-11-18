"""Tests for bin/limitler.py (the owner's Claude plan usage limits, owner decision 2026-11-14): the reader, the Turkish text, the
/api/state field, the top bar's pill (web/limitler.js under node, skipped without it), the one notice per window and
threshold, and the lines in the morning summary, the end-of-day note and Jarvis `durum`. Temp files only: the real
~/.claude/ofis/limitler.json is never read."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import jarvis  # noqa: E402
import limitler  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
WEB = Path(HERE).parent / "web"
NODE = shutil.which("node")


def ts(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=TZ).timestamp()


NOW = ts(14, 19, 41)  # a Saturday


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
        self.path = os.path.join(self.tmp.name, "limitler.json")
        self.durum = os.path.join(self.tmp.name, "durum")
        self.cfg = {"ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"},
                    "limitler": {"acik": True, "uyari": [80, 95], "dosya": self.path}}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data, raw=None):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(data))

    def sample(self, hafta=54, bes=62, saved=NOW - 60, bes_reset=None, hafta_reset=None):
        return {"five_hour": {"used_percentage": bes, "resets_at": bes_reset or ts(14, 21)},
                "seven_day": {"used_percentage": hafta, "resets_at": hafta_reset or ts(18, 22)},
                "saved_at": saved}


class ReadTest(Base):
    def test_a_good_file(self):
        self.write(self.sample())
        v = limitler.oku(NOW, self.path)
        self.assertEqual(v["haftalik"], {"yuzde": 54, "sifirlanma": int(ts(18, 22)), "gecti": False})
        self.assertEqual(v["bes_saat"], {"yuzde": 62, "sifirlanma": int(ts(14, 21)), "gecti": False})
        self.assertEqual(v["olculdu"], int(NOW - 60))
        self.assertFalse(v["eski"])

    def test_missing_corrupt_or_wrong_shape_gives_none(self):
        self.assertIsNone(limitler.oku(NOW, self.path))
        for raw in ("", "{", "[1, 2]", "null", '"x"', '{"five_hour": null, "seven_day": null}',
                    '{"five_hour": {"used_percentage": "62"}}', '{"seven_day": {"used_percentage": 140}}',
                    '{"seven_day": {"used_percentage": -1}}', '{"seven_day": {"used_percentage": true}}'):
            self.write(None, raw)
            self.assertIsNone(limitler.oku(NOW, self.path), raw)
        os.remove(self.path)
        os.mkdir(self.path)  # a folder, not a file
        self.assertIsNone(limitler.oku(NOW, self.path))

    def test_a_big_file_or_a_link_is_not_read(self):
        self.write(None, json.dumps(self.sample()) + " " * (limitler.MAX_BOYUT + 10))
        self.assertIsNone(limitler.oku(NOW, self.path))
        real = os.path.join(self.tmp.name, "real.json")
        with open(real, "w", encoding="utf-8") as f:
            json.dump(self.sample(), f)
        os.remove(self.path)
        os.symlink(real, self.path)
        self.assertIsNone(limitler.oku(NOW, self.path))

    def test_a_partial_file_keeps_the_good_window(self):
        self.write({"seven_day": {"used_percentage": 54.4, "resets_at": ts(18, 22)}, "five_hour": None,
                    "saved_at": NOW})
        v = limitler.oku(NOW, self.path)
        self.assertIsNone(v["bes_saat"])
        self.assertEqual(v["haftalik"]["yuzde"], 54)
        self.write({"five_hour": {"used_percentage": 10}})  # no reset time, no saved_at
        v = limitler.oku(NOW, self.path)
        self.assertEqual(v["bes_saat"], {"yuzde": 10, "sifirlanma": None, "gecti": False})
        self.assertIsNone(v["olculdu"])
        self.assertTrue(v["eski"])

    def test_a_passed_reset_means_reset_and_unknown_since(self):
        self.write(self.sample(bes_reset=NOW - 5))
        v = limitler.oku(NOW, self.path)
        self.assertEqual(v["bes_saat"], {"yuzde": None, "sifirlanma": int(NOW - 5), "gecti": True})
        self.assertFalse(v["haftalik"]["gecti"])

    def test_old_and_future_readings(self):
        self.write(self.sample(saved=NOW - 31 * 60))
        self.assertTrue(limitler.oku(NOW, self.path)["eski"])
        self.write(self.sample(saved=NOW - 29 * 60))
        self.assertFalse(limitler.oku(NOW, self.path)["eski"])
        self.write(self.sample(saved=NOW + 3600))  # a clock from the future is not trusted
        v = limitler.oku(NOW, self.path)
        self.assertIsNone(v["olculdu"])
        self.assertTrue(v["eski"])

    def test_an_absurd_reset_time_is_dropped(self):
        self.write(self.sample(hafta_reset=1e20))
        v = limitler.oku(NOW, self.path)
        self.assertIsNone(v["haftalik"]["sifirlanma"])
        self.assertTrue(limitler.metin(v, NOW, TZ).startswith("Haftalık sınır %54 · 5 saatlik"))

    def test_the_switch_and_the_thresholds(self):
        self.write(self.sample())
        self.assertIsNone(limitler.sayfa({}, NOW))
        self.assertIsNone(limitler.sayfa({"limitler": {"acik": False, "dosya": self.path}}, NOW))
        a = limitler.ayar({"limitler": {"acik": True, "uyari": [95, 80, 0, 101, "x", True, 80]}})
        self.assertEqual(a["uyari"], [80, 95])
        self.assertEqual(limitler.ayar({"limitler": {"acik": True}})["dosya"],
                         os.path.expanduser("~/.claude/ofis/limitler.json"))


class TextTest(Base):
    def test_the_line(self):
        self.write(self.sample())
        v = limitler.oku(NOW, self.path)
        self.assertEqual(limitler.metin(v, NOW, TZ),
                         "Haftalık sınır %54 · çarşamba 22:00'de sıfırlanır · 5 saatlik %62 · 21:00'de")
        self.assertEqual(limitler.kisa(v), "Haftalık %54 · 5 saat %62")

    def test_an_old_reading_shows_when_it_was_measured(self):
        self.write(self.sample(saved=ts(14, 18, 30)))
        v = limitler.oku(NOW, self.path)
        self.assertTrue(limitler.metin(v, NOW, TZ).endswith(" · 18:30'da ölçüldü"))

    def test_tomorrow_today_far_away_and_a_reset_window(self):
        self.write(self.sample(bes_reset=ts(15, 0, 30), hafta_reset=ts(14, 23)))
        v = limitler.oku(NOW, self.path)
        self.assertEqual(limitler.metin(v, NOW, TZ),
                         "Haftalık sınır %54 · bugün 23:00'te sıfırlanır · 5 saatlik %62 · yarın 00:30'da")
        self.write(self.sample(bes_reset=NOW - 1, hafta_reset=ts(21, 15)))
        v = limitler.oku(NOW, self.path)
        self.assertEqual(limitler.metin(v, NOW, TZ),
                         "Haftalık sınır %54 · 21 Kasım 15:00'te sıfırlanır · 5 saatlik sınır sıfırlandı "
                         "(yeni değer henüz ölçülmedi)")
        self.assertEqual(limitler.kisa(v), "Haftalık %54 · 5 saat sıfırlandı")

    def test_suffixes(self):
        self.assertEqual([limitler.yuzde_i(n) for n in (80, 90, 95, 100, 60)],
                         ["%80'i", "%90'ı", "%95'i", "%100'ü", "%60'ı"])
        self.assertIsNone(limitler.metin(None))
        self.assertIsNone(limitler.kisa({}))

    def test_satir_and_sayfa(self):
        self.write(self.sample(saved=time.time()))
        self.assertIsNone(limitler.satir({}))
        self.assertTrue(limitler.satir(self.cfg).startswith("Claude kullanım sınırı: Haftalık sınır %54"))
        s = limitler.sayfa(self.cfg, NOW)
        self.assertEqual(s["kisa"], "Haftalık %54 · 5 saat %62")
        self.assertIn("çarşamba 22:00'de sıfırlanır", s["metin"])
        self.assertNotIn(self.path, json.dumps(s))  # no path on the page


class WarningTest(Base):
    def make(self, now=NOW, cfg=None):
        self.ceo = getattr(self, "ceo", None) or FakeCeo()
        return limitler.LimitUyarisi(lambda: cfg or self.cfg, self.durum, self.ceo, now=lambda: now)

    def test_below_the_threshold_nothing(self):
        self.write(self.sample(hafta=79, bes=10))
        self.assertEqual(self.make().kontrol(), [])
        self.assertEqual(self.ceo.sent, [])

    def test_once_per_window_and_threshold(self):
        self.write(self.sample(hafta=81, bes=10))
        self.assertEqual(self.make().kontrol(), [("haftalik", 80)])
        [(text, key)] = self.ceo.sent
        self.assertEqual(text.splitlines()[1],
                         "Haftalık kullanım sınırının %80'i doldu (şu an %81); çarşamba 22:00'de sıfırlanır.")
        self.assertTrue(text.startswith("[Ofis · sistem]\n"))
        self.assertIn("hiçbir işi kendin durdurma", text)
        self.assertEqual(key, f"limit-haftalik-{int(ts(18, 22))}-80")
        # the next passes, a restart (a new object), a few seconds of jitter in resets_at: nothing again
        self.make().kontrol()
        self.write(self.sample(hafta=88, bes=10, hafta_reset=ts(18, 22) + 2))
        self.assertEqual(self.make().kontrol(), [])
        self.assertEqual(len(self.ceo.sent), 1)
        # 95 % in the same window: one more
        self.write(self.sample(hafta=95, bes=10))
        self.assertEqual(self.make().kontrol(), [("haftalik", 95)])
        self.assertIn("Haftalık kullanım sınırının %95'i doldu; ", self.ceo.sent[1][0])
        self.assertEqual(self.make().kontrol(), [])
        # a new window (after the reset) starts again
        self.write(self.sample(hafta=82, bes=10, hafta_reset=ts(21, 22)))
        self.assertEqual(self.make().kontrol(), [("haftalik", 80)])
        self.assertEqual(len(self.ceo.sent), 3)

    def test_a_jump_past_both_sends_one_notice_and_windows_are_separate(self):
        self.write(self.sample(hafta=50, bes=97))
        self.assertEqual(self.make().kontrol(), [("bes_saat", 95)])
        self.assertIn("5 saatlik kullanım sınırının %95'i doldu (şu an %97); bugün 21:00'de sıfırlanır.",
                      self.ceo.sent[0][0])
        with open(os.path.join(self.durum, "limitler", "uyarilar.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["bes_saat"]["gonderilen"], [80, 95])
        self.write(self.sample(hafta=80, bes=97))
        self.assertEqual(self.make().kontrol(), [("haftalik", 80)])

    def test_lost_state_is_still_deduplicated_by_the_queue_key(self):
        self.write(self.sample(hafta=85))
        self.make().kontrol()
        shutil.rmtree(os.path.join(self.durum, "limitler"))
        self.make().kontrol()
        self.assertEqual(len(self.ceo.sent), 1)

    def test_off_reset_or_unknown_reset_sends_nothing(self):
        self.write(self.sample(hafta=99, bes=99))
        self.assertEqual(self.make(cfg={"limitler": {"acik": False, "dosya": self.path}}).kontrol(), [])
        self.write(self.sample(hafta=50, bes=99, bes_reset=NOW - 1))
        self.assertEqual(self.make().kontrol(), [])
        self.write({"seven_day": {"used_percentage": 99}})
        self.assertEqual(self.make().kontrol(), [])
        os.remove(self.path)
        self.assertEqual(self.make().kontrol(), [])
        self.assertEqual(self.ceo.sent, [])


class StateFieldTest(Base):
    def test_api_state_carries_the_limits(self):
        import test_state
        case = test_state.Base("setUp")
        case.setUp()
        try:
            self.write(self.sample(saved=time.time(), bes_reset=time.time() + 3600,
                                   hafta_reset=time.time() + 3 * 86400))
            case.cfg["limitler"] = {"acik": True, "dosya": self.path}
            s = case.office().build()
            self.assertEqual(s["limitler"]["kisa"], "Haftalık %54 · 5 saat %62")
            del case.cfg["limitler"]
            self.assertIsNone(case.office().build()["limitler"])
        finally:
            case.tearDown()


class LinesTest(Base):
    def setUp(self):
        super().setUp()
        self.write(self.sample(saved=time.time(), bes_reset=time.time() + 3600, hafta_reset=time.time() + 3 * 86400))

    def test_morning_summary(self):
        import test_ozet
        case = test_ozet.Base("setUp")
        case.setUp()
        try:
            case.cfg["limitler"] = {"acik": True, "dosya": self.path}
            case.make().kontrol()
            with open(os.path.join(case.vault, "Ozetler", "2026-11-12.md"), encoding="utf-8") as f:
                note = f.read()
            self.assertIn("\nClaude kullanım sınırı: Haftalık sınır %54 · ", note)
            self.assertIn("\n- Claude kullanım sınırı: Haftalık sınır %54 · ", case.ceo.sent[0][0])
        finally:
            case.tearDown()

    def test_morning_summary_without_data_has_no_line(self):
        import test_ozet
        case = test_ozet.Base("setUp")
        case.setUp()
        try:
            case.make().kontrol()
            self.assertNotIn("Claude kullanım sınırı", case.ceo.sent[0][0])
        finally:
            case.tearDown()

    def test_end_of_day_note(self):
        import test_gunsonu
        case = test_gunsonu.Base("setUp")
        case.setUp()
        try:
            case.cfg["limitler"] = {"acik": True, "dosya": self.path}
            case.good_day()
            case.make().kontrol()
            note = case.read_note()
            self.assertIn("\nClaude kullanım sınırı: Haftalık sınır %54 · ", note)
            self.assertIn("\n- Claude kullanım sınırı: Haftalık sınır %54 · ", case.ceo.sent[0][0])
            # kept in the day's state: a rewrite of the note gives the same line even when the file changes
            os.remove(self.path)
            import gunsonu
            self.assertEqual(gunsonu.metin(case.state()), note)
        finally:
            case.tearDown()

    def test_jarvis_durum(self):
        s = limitler.sayfa(self.cfg)
        data = jarvis.durum_verisi({"tasks": [], "ceo": {}, "limitler": s}, {}, [])
        self.assertEqual(data["limitler"]["haftalik"]["yuzde"], 54)
        self.assertEqual(data["limitler"]["bes_saat"]["yuzde"], 62)
        self.assertEqual(data["limitler"]["metin"], s["metin"])
        self.assertIn(f"Claude kullanım sınırı: {s['metin']}.", jarvis.durum_metni(data))
        none = jarvis.durum_verisi({"tasks": [], "ceo": {}}, {}, [])
        self.assertIsNone(none["limitler"])
        self.assertNotIn("Claude kullanım sınırı", jarvis.durum_metni(none))


def run_js(expr):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        shutil.copyfile(WEB / "limitler.js", Path(tmp) / "limitler.js")
        uri = json.dumps((Path(tmp) / "limitler.js").as_uri())
        code = f"import * as l from {uri};\nprocess.stdout.write(JSON.stringify({expr}));"
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class PillTest(unittest.TestCase):
    def pill(self, hafta, bes, **x):
        lim = {"haftalik": {"yuzde": hafta, "gecti": False}, "bes_saat": {"yuzde": bes, "gecti": False},
               "metin": "Haftalık sınır …", **x}
        return run_js(f"l.limitPill({json.dumps(lim)})")

    def test_thresholds(self):
        self.assertEqual(self.pill(54, 62)["ton"], "")
        self.assertEqual(self.pill(54, 62)["metin"], "Haftalık %54 · 5 saat %62")
        self.assertEqual(self.pill(79, 10)["ton"], "")
        self.assertEqual(self.pill(80, 10)["ton"], "uyari")
        self.assertEqual(self.pill(10, 94)["ton"], "uyari")
        self.assertEqual(self.pill(10, 95)["ton"], "kritik")
        self.assertEqual(self.pill(100, 50)["ton"], "kritik")

    def test_hidden_without_data_and_tooltip(self):
        for v in ("null", "{}", '{"haftalik": null, "bes_saat": null}', '"x"'):
            self.assertTrue(run_js(f"l.limitPill({v})")["gizli"], v)
        p = self.pill(54, 62, eski=True)
        self.assertFalse(p["gizli"])
        self.assertTrue(p["ipucu"].startswith("Claude kullanım sınırı: Haftalık sınır …"))
        self.assertIn("son ölçüm eski", p["ipucu"])
        r = run_js('l.limitPill({"bes_saat": {"yuzde": null, "gecti": true}, "haftalik": {"yuzde": 97}})')
        self.assertEqual((r["metin"], r["ton"]), ("Haftalık %97 · 5 saat sıfırlandı", "kritik"))


class WiringTest(unittest.TestCase):
    def test_the_page_uses_text_only(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (WEB / "style.css").read_text(encoding="utf-8")
        self.assertIn("import { kullanimGorunumu, limitPill } from './limitler.js';", app)
        self.assertIn('id="limit-pill"', html)
        start = app.index("function renderLimit()")
        body = app[start:app.index("\n}\n", start)]
        self.assertIn("el.textContent = lp.metin;", body)
        self.assertNotIn("innerHTML", body)
        for cls in (".limit-pill.is-uyari", ".limit-pill.is-kritik", ".limit-pill[hidden]"):
            self.assertIn(cls, css)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_module_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "limitler.mjs"
            shutil.copyfile(WEB / "limitler.js", target)
            proc = subprocess.run([NODE, "--check", str(target)], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
