"""Tests for bin/kullanim.py (the usage popup under the limit pill, owner decision 2026-11-16): the windows from the limit file
(and the fallback without it), de-duplication by message id, the grouping (CEO, job title, Geliştirici, Jarvis, the
managers' calls, the one lump), ZIM exclusion, no paths / text / session ids in the output, the pricing labels, the
cache and the incremental read; the popup helper (web/limitler.js kullanimGorunumu) under node, skipped without it;
the page wiring (text only). Temp folders only: the real ~/.claude is never read."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, HERE)
import fakes  # noqa: E402
import jobs  # noqa: E402
import kullanim  # noqa: E402
import records  # noqa: E402
import transcript  # noqa: E402

WEB = Path(HERE).parent / "web"
NODE = shutil.which("node")
TZ = ZoneInfo("Europe/Istanbul")
NOW = float(int(time.time()))
SECRET = "GIZLI-METIN-asla-gorunmemeli"

CEO_SID = "c0000000-0000-0000-0000-000000000001"
DEV_SID = "d0000000-0000-0000-0000-000000000002"
JOB_SID = "a0000000-0000-0000-0000-000000000003"
JOB2_SID = "a0000000-0000-0000-0000-000000000004"
MUDUR_SID = "e0000000-0000-0000-0000-000000000005"
JARVIS_SID = "f0000000-0000-0000-0000-000000000006"
OTHER_SID = "b0000000-0000-0000-0000-000000000007"
ZIM_SID = "99999999-0000-0000-0000-000000000008"
HAKEM_SID = "e0000000-0000-0000-0000-000000000009"


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def call(ts, msg_id, inp=100, out=50, read=0, model="claude-opus-5-5", entry="cli", synthetic=False):
    return {"type": "assistant", "timestamp": iso(ts), "entrypoint": entry,
            "message": {"id": msg_id, "model": "<synthetic>" if synthetic else model, "role": "assistant",
                        "content": [{"type": "text", "text": SECRET}],
                        "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
                                  "cache_creation_input_tokens": 0}}}


def user(ts):
    return {"type": "user", "timestamp": iso(ts), "message": {"role": "user", "content": SECRET}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.tmp.name)
        self.projects = os.path.join(base, "projects")
        self.root = os.path.join(base, "Dev", "ajan-ofisi")
        self.blog = os.path.join(base, "Dev", "blog")
        self.jarvis = os.path.join(base, "Dev", "jarvis")
        self.zim = os.path.join(base, "Dev", "zim")
        self.durum = os.path.join(self.root, "durum")
        self.vault = os.path.join(base, "vault", "OFIS")
        self.limit = os.path.join(base, "limitler.json")
        os.makedirs(self.projects)
        self.cfg = {"ceo_session": "ofis-ceo", "vault_ofis": self.vault,
                    "projects": {"blog": {"path": self.blog}},
                    "ofis_sahnesi": {"saat_dilimi": "Europe/Istanbul"},
                    "limitler": {"acik": True, "dosya": self.limit}}
        self.k = self.make()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, **kw):
        return kullanim.Kullanim(self.projects, self.root, self.durum, self.vault, jarvis_klasoru=self.jarvis, **kw)

    def folder(self, cwd_or_name, raw=False):
        name = cwd_or_name if raw else transcript.encode_cwd(cwd_or_name)
        path = os.path.join(self.projects, name)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, folder, sid, records_, name=None, sub=None, mtime=None):
        lines = list(fakes.name_records(name, sid)) if name else []
        lines += records_
        if sub:
            path = os.path.join(folder, sid, "subagents", f"{sub}.jsonl")
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            path = os.path.join(folder, f"{sid}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for r in lines:
                f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def limits(self, five_reset=None, week_reset=None, saved=None, five=17, week=74):
        data = {"saved_at": NOW - 60 if saved is None else saved}
        if five_reset is not None:
            data["five_hour"] = {"used_percentage": five, "resets_at": five_reset}
        if week_reset is not None:
            data["seven_day"] = {"used_percentage": week, "resets_at": week_reset}
        with open(self.limit, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def page(self, now=NOW):
        return self.k.sayfa(self.cfg, now=now)

    def rows(self, out, w="bes_saat"):
        return {r["ad"]: r for r in out["dagilim"][w]["satirlar"]}


class WindowTest(Base):
    def test_window_starts_at_reset_minus_length(self):
        self.limits(five_reset=NOW + 2 * 3600, week_reset=NOW + 3 * 86400)
        f = self.folder(self.root)
        start5, start7 = NOW - 3 * 3600, NOW - 4 * 86400
        self.write(f, DEV_SID, [call(start5 - 5, "m-before5", inp=1000), call(start5 + 5, "m-in5", inp=2000),
                                call(start7 - 5, "m-before7", inp=40000), call(start7 + 5, "m-in7", inp=80000)])
        out = self.page()
        d5, d7 = out["dagilim"]["bes_saat"], out["dagilim"]["haftalik"]
        self.assertEqual((d5["baslangic"], d5["tahmini"]), (int(start5), False))
        self.assertEqual((d7["baslangic"], d7["tahmini"]), (int(start7), False))
        self.assertEqual(d5["toplam"]["token"], 2050)
        self.assertEqual(d7["toplam"]["token"], 2050 + 1050 + 80050)
        self.assertIn("Bu pencere:", d5["aralik"])
        self.assertTrue(d5["aralik"].endswith("'den beri") or d5["aralik"].endswith("'dan beri")
                        or d5["aralik"].endswith("'ten beri") or d5["aralik"].endswith("'tan beri"))

    def test_missing_limit_file_falls_back_to_last_5h_and_7d(self):
        f = self.folder(self.root)
        self.write(f, DEV_SID, [call(NOW - 5 * 3600 - 30, "old5"), call(NOW - 5 * 3600 + 30, "in5"),
                                call(NOW - 7 * 86400 + 30, "in7")])
        out = self.page()
        self.assertIsNone(out["limitler"])
        d5, d7 = out["dagilim"]["bes_saat"], out["dagilim"]["haftalik"]
        self.assertEqual((d5["baslangic"], d5["tahmini"], d5["aralik"]), (int(NOW - 5 * 3600), True, "Son 5 saat"))
        self.assertEqual((d7["baslangic"], d7["tahmini"], d7["aralik"]), (int(NOW - 7 * 86400), True, "Son 7 gün"))
        self.assertEqual(d5["toplam"]["token"], 150)
        self.assertEqual(d7["toplam"]["token"], 450)

    def test_a_passed_reset_falls_back_too(self):
        self.limits(five_reset=NOW - 60, week_reset=NOW + 86400)
        out = self.page()
        self.assertTrue(out["dagilim"]["bes_saat"]["tahmini"])
        self.assertFalse(out["dagilim"]["haftalik"]["tahmini"])
        five = next(p for p in out["limitler"]["pencereler"] if p["ad"] == "bes_saat")
        self.assertTrue(five["gecti"])
        self.assertIn("sıfırlandı", five["yenilenir"])

    def test_limit_texts(self):
        self.limits(five_reset=NOW + 2 * 3600 + 14 * 60 + 30, week_reset=NOW + 3 * 86400, saved=NOW - 3600)
        lim = self.page()["limitler"]
        five = next(p for p in lim["pencereler"] if p["ad"] == "bes_saat")
        week = next(p for p in lim["pencereler"] if p["ad"] == "haftalik")
        self.assertEqual((five["yuzde"], five["etiket"], five["kalan"]), (17, "5 saatlik", "2 sa 14 dk sonra"))
        self.assertTrue(five["yenilenir"].endswith(" yenilenir"))
        self.assertEqual(week["kalan"], "3 gün sonra")
        self.assertEqual([p["ad"] for p in lim["pencereler"]], ["haftalik", "bes_saat"])
        self.assertTrue(lim["eski"])
        self.assertIn("ölçüldü", lim["olculdu"])
        self.assertIn("eski", lim["eski_aciklama"])

    def test_remaining_time_text(self):
        self.assertEqual(kullanim._kalan(30), "1 dakikadan az kaldı")
        self.assertEqual(kullanim._kalan(45 * 60), "45 dk sonra")
        self.assertEqual(kullanim._kalan(2 * 3600), "2 sa sonra")
        self.assertEqual(kullanim._kalan(86400 + 4 * 3600 + 60), "1 gün 4 sa sonra")


class CountTest(Base):
    def test_dedup_by_message_id_within_and_across_files(self):
        f = self.folder(self.root)
        self.write(f, CEO_SID, [call(NOW - 60, "m1", inp=1000), call(NOW - 60, "m1", inp=1000),  # streamed chunks
                                call(NOW - 50, "m2", inp=10)], name="ofis-ceo")
        # a resumed session copies earlier records into its new transcript: m1 again
        self.write(f, DEV_SID[:-1] + "9", [call(NOW - 60, "m1", inp=1000), call(NOW - 40, "m3", inp=20)],
                   name="ofis-ceo")
        out = self.page()
        self.assertEqual(out["dagilim"]["bes_saat"]["toplam"]["token"], 1050 + 60 + 70)
        self.assertEqual(self.rows(out)["CEO"]["oturum_sayisi"], 2)

    def test_synthetic_and_broken_lines_do_not_count_or_fail(self):
        f = self.folder(self.root)
        self.write(f, DEV_SID, ['{"type": "assistant", "message": {broken', "not json at all", user(NOW - 10),
                                call(NOW - 9, "syn", synthetic=True), call(NOW - 8, "ok", inp=7, out=3),
                                '{"type":"assistant","timestamp":"x","message":{"usage":{"input_tokens":5}}}'])
        out = self.page()
        self.assertEqual(out["dagilim"]["bes_saat"]["toplam"]["token"], 10)
        self.assertEqual(out["dagilim"]["bes_saat"]["toplam"]["cikti_token"], 3)

    def test_subagents_count_to_their_parent(self):
        f = self.folder(self.root)
        self.write(f, CEO_SID, [call(NOW - 60, "p1")], name="ofis-ceo")
        self.write(f, CEO_SID, [call(NOW - 30, "s1", inp=500)], sub="agent-abc")
        out = self.page()
        self.assertEqual(list(self.rows(out)), ["CEO"])
        self.assertEqual(self.rows(out)["CEO"]["token"], 150 + 550)

    def test_old_files_are_not_opened(self):
        f = self.folder(self.root)
        p = self.write(f, DEV_SID, [call(NOW - 60, "x")], mtime=NOW - 8 * 86400)
        out = self.page()
        self.assertEqual(out["dagilim"]["haftalik"]["satirlar"], [])
        self.assertNotIn(p, self.k._files)

    def test_large_file_is_entered_by_bisecting(self):
        f = self.folder(self.root)
        old = [call(NOW - 6 * 86400 - 3600 * 30 + i, f"old{i}", inp=1) for i in range(4000)]
        new = [call(NOW - 100 + i, f"new{i}", inp=10, out=0) for i in range(10)]
        self.write(f, DEV_SID, old + new)
        orig = kullanim.BOLME_ESIGI
        kullanim.BOLME_ESIGI = 64 * 1024
        try:
            k = self.make()
            out = k.sayfa(self.cfg, now=NOW)
        finally:
            kullanim.BOLME_ESIGI = orig
        c = next(iter(k._files.values()))
        self.assertEqual(out["dagilim"]["bes_saat"]["toplam"]["token"], 100)
        self.assertEqual(out["dagilim"]["haftalik"]["toplam"]["token"], 100)  # the old part is before the week
        self.assertEqual(len(c.calls), 10)

    def test_cache_and_incremental_read(self):
        f = self.folder(self.root)
        self.write(f, DEV_SID, [call(NOW - 60, "a", inp=100, out=0)])
        self.assertEqual(self.page()["dagilim"]["bes_saat"]["toplam"]["token"], 100)
        self.write(f, DEV_SID, [call(NOW - 10, "b", inp=5, out=0)])
        self.assertEqual(self.page(NOW + 30)["dagilim"]["bes_saat"]["toplam"]["token"], 100)  # cached
        out = self.page(NOW + 61)
        self.assertEqual(out["dagilim"]["bes_saat"]["toplam"]["token"], 105)
        c = next(iter(self.k._files.values()))
        self.assertEqual(c.offset, os.path.getsize(os.path.join(f, f"{DEV_SID}.jsonl")))

    def test_pricing_labels(self):
        f = self.folder(self.root)
        self.write(f, DEV_SID, [call(NOW - 60, "a", inp=1_000_000, out=100_000)])
        self.write(f, DEV_SID[:-1] + "8", [call(NOW - 60, "u", inp=10, out=0, model="claude-unknown-9")],
                   name="ofis-ceo")
        out = self.page()
        rows = self.rows(out)
        dev = rows["Geliştirici oturumu"]
        # opus 5.5: $4 / M input, $20 / M output -> 4 + 2 = $6
        self.assertAlmostEqual(dev["usd"], 6.0)
        self.assertEqual(dev["metin"], "1,1 mn token · API karşılığı ~$6.00")
        self.assertEqual(dev["cikti_metni"], "çıktı 100 bin token")
        self.assertTrue(rows["CEO"]["fiyat_eksik"])
        self.assertEqual(rows["CEO"]["metin"], "10 token · API karşılığı bilinmiyor")
        text = json.dumps(out, ensure_ascii=False)
        for word in ("harcama", "maliyet", "0 token ·"):
            self.assertNotIn(word, text.replace("10 token ·", ""))
        self.assertIn("birebir orantılı değildir", out["not"])


class GroupTest(Base):
    def setUp(self):
        super().setUp()
        done = jobs.folder_path(self.vault, jobs.DONE)
        fakes.write_note(done, "2026-11-16-101010-blog.md",
                         {"proje": "blog", "baslik": "Onboarding metinleri", "durum": "bitti",
                          "oturum": "ofis-blog-1116-101010-abcd"}, "## Hedef\nx\n")
        fakes.write_note(done, "2026-11-16-111111-blog.md",
                         {"proje": "blog", "baslik": "Kayıtla bulunan iş", "durum": "bitti"}, "## Hedef\ny\n")
        records.update(self.durum, "2026-11-16-111111-blog.md",
                       {"proje": "blog", "oturum_kimlikleri": [JOB2_SID]})
        root, ws = self.folder(self.root), self.folder(self.blog)
        t = NOW - 600
        self.write(root, CEO_SID, [call(t, "ceo1", inp=9000)], name="ofis-ceo")
        self.write(root, DEV_SID, [call(t, "dev1", inp=8000)])
        self.write(ws, JOB_SID, [call(t, "job1", inp=7000)], name="ofis-blog-1116-101010-abcd")
        self.write(ws, JOB2_SID, [call(t, "job2", inp=6500)])
        self.write(ws, OTHER_SID[:-1] + "1", [call(t, "job3", inp=6000)], name="ofis-blog-1116-121212-ffff")
        self.write(ws, MUDUR_SID, [call(t, "mud1", inp=5000, entry="sdk-cli")])
        self.write(ws, OTHER_SID[:-1] + "2", [call(t, "sahip-ws", inp=4000)])  # The owner in a project folder
        self.write(self.folder(self.jarvis), JARVIS_SID, [call(t, "jar1", inp=3000)])
        self.write(self.folder("-private-var-folders-x-T-ofis-denetci-abc123-kopya", raw=True), HAKEM_SID,
                   [call(t, "hak1", inp=2000, entry="sdk-cli")])
        self.write(self.folder(os.path.join(os.path.dirname(self.root), "baska-proje")), OTHER_SID,
                   [call(t, "oth1", inp=1000)], name="kendi-adim")
        # ZIM: a huge session that must not appear anywhere (also under an office-like name)
        self.zim_path = self.write(self.folder(self.zim), ZIM_SID, [call(t, "zim1", inp=10_000_000)],
                                   name="ofis-blog-1116-131313-0000")
        self.write(self.folder(self.zim + "-api"), ZIM_SID[:-1] + "1", [call(t, "zim2", inp=10_000_000)])

    def test_groups(self):
        out = self.page()
        rows = self.rows(out)
        self.assertEqual(rows["CEO"]["token"], 9050)
        self.assertEqual(rows["Geliştirici oturumu"]["token"], 8050)
        self.assertEqual(rows["Onboarding metinleri (blog)"]["token"], 7050)
        self.assertEqual(rows["Kayıtla bulunan iş (blog)"]["token"], 6550)
        self.assertEqual(rows["blog işi"]["token"], 6050)
        self.assertEqual(rows["Müdür ve hakem çağrıları"]["token"], 5050 + 2050)
        self.assertEqual(rows["Jarvis"]["token"], 3050)
        self.assertEqual(rows["Ofis dışı diğer oturumlar"]["token"], 4050 + 1050)
        self.assertEqual(rows["Ofis dışı diğer oturumlar"]["oturum_sayisi"], 2)
        self.assertEqual(len(rows), 8)
        tokens = [r["token"] for r in out["dagilim"]["bes_saat"]["satirlar"]]
        self.assertEqual(tokens, sorted(tokens, reverse=True))
        self.assertEqual(out["dagilim"]["bes_saat"]["toplam"]["token"], sum(tokens))

    def test_zim_contributes_nothing_anywhere(self):
        out = self.page()
        for w in ("bes_saat", "haftalik"):
            self.assertLess(out["dagilim"][w]["toplam"]["token"], 1_000_000)
        text = json.dumps(out, ensure_ascii=False).lower()
        self.assertNotIn("zim", text)
        self.assertNotIn("131313", text)
        self.assertFalse(any("zim" in p.lower() for p in self.k._files))

    def test_no_paths_text_or_session_ids_leak(self):
        text = json.dumps(self.page(), ensure_ascii=False)
        for bad in (SECRET, self.projects, self.root, self.blog, "ajan-ofisi", "denetci", "kendi-adim",
                    "baska-proje", "ofis-blog", "ofis-ceo", "jsonl", CEO_SID, DEV_SID, JOB_SID, OTHER_SID[:8],
                    "/Users", self.tmp.name):
            self.assertNotIn(bad, text, bad)

    def test_unregistered_project_in_an_office_name_is_not_shown(self):
        self.write(self.folder(os.path.join(os.path.dirname(self.root), "x")), OTHER_SID[:-1] + "5",
                   [call(NOW - 60, "z", inp=1)], name="ofis-gizliproje-1116-101010-abcd")
        rows = self.rows(self.page())
        self.assertIn("Ofis işi", rows)
        self.assertNotIn("gizliproje", json.dumps(rows, ensure_ascii=False))

    def test_jarvis_folder_comes_from_the_config(self):
        # plan "2. Aşama": ofis.json `jarvis.klasor` names the folder; the server builds Kullanim without one
        self.k = kullanim.Kullanim(self.projects, self.root, self.durum, self.vault)
        self.cfg["jarvis"] = {"acik": False, "klasor": self.jarvis}
        self.assertEqual(self.rows(self.page())["Jarvis"]["token"], 3050)

    def test_without_a_jarvis_folder_there_is_no_jarvis_row(self):
        self.k = kullanim.Kullanim(self.projects, self.root, self.durum, self.vault)
        for jarvis in (None, {"acik": True}, {"klasor": ""}, {"klasor": 3}, "x"):
            with self.subTest(jarvis=jarvis):
                if jarvis is None:
                    self.cfg.pop("jarvis", None)
                else:
                    self.cfg["jarvis"] = jarvis
                self.k._cache = None
                rows = self.rows(self.page())
                self.assertNotIn("Jarvis", rows)
                self.assertEqual(rows["Ofis dışı diğer oturumlar"]["token"], 4050 + 1050 + 3050)

    def test_small_rows_are_merged(self):
        orig = kullanim.MAX_SATIR
        kullanim.MAX_SATIR = 3
        try:
            out = self.page()
        finally:
            kullanim.MAX_SATIR = orig
        rows = out["dagilim"]["bes_saat"]["satirlar"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["ad"], "Daha küçük 5 kullanım")
        self.assertEqual(sum(r["token"] for r in rows), out["dagilim"]["bes_saat"]["toplam"]["token"])


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
class PopupTest(Base):
    def test_view_from_the_endpoint(self):
        self.limits(five_reset=NOW + 3600, week_reset=NOW + 86400, five=96, week=81)
        f = self.folder(self.root)
        self.write(f, CEO_SID, [call(NOW - 60, "a", inp=2000)], name="ofis-ceo")
        self.write(f, DEV_SID, [call(NOW - 60, "b", inp=1000)])
        data = self.page()
        g = run_js(f"l.kullanimGorunumu({json.dumps(data)}, 'bes_saat')")
        self.assertEqual([p["etiket"] for p in g["pencereler"]], ["Haftalık", "5 saatlik"])
        self.assertEqual([p["yuzdeMetni"] for p in g["pencereler"]], ["%81", "%96"])
        self.assertEqual([p["ton"] for p in g["pencereler"]], ["uyari", "kritik"])
        self.assertEqual(g["pencereler"][1]["genislik"], 96)
        self.assertTrue(g["pencereler"][1]["yenilenir"].endswith("yenilenir"))
        self.assertEqual(g["pencereler"][1]["kalan"], "1 sa sonra")
        self.assertIn("ölçüldü", g["olcum"])
        self.assertEqual([r["ad"] for r in g["satirlar"]], ["CEO", "Geliştirici oturumu"])
        self.assertEqual(g["satirlar"][0]["metin"], data["dagilim"]["bes_saat"]["satirlar"][0]["metin"])
        self.assertTrue(g["satirlar"][0]["metin"].startswith("2,1 bin token · API karşılığı ~$"))
        self.assertEqual(g["toplam"]["ad"], "Toplam")
        self.assertEqual(g["bos"], "")
        self.assertIn("birebir orantılı değildir", g["not"])
        w = run_js(f"l.kullanimGorunumu({json.dumps(data)}, 'haftalik')")
        self.assertEqual(w["sekme"], "haftalik")
        self.assertTrue(w["aralik"].startswith("Bu pencere:"))

    def test_empty_loading_error_and_bad_shapes(self):
        g = run_js("l.kullanimGorunumu(null, 'bes_saat', 'yukleniyor')")
        self.assertEqual((g["bos"], g["sinirYok"], g["satirlar"], g["toplam"]), ("Yükleniyor…", "", [], None))
        self.assertEqual(run_js("l.kullanimGorunumu(null, 'x', 'hata')")["bos"], "Kullanım dökümü alınamadı.")
        g = run_js("l.kullanimGorunumu({dagilim: {bes_saat: {satirlar: [], toplam: null}}}, 'zzz')")
        self.assertEqual((g["sekme"], g["bos"]), ("bes_saat", "Bu aralıkta kayıtlı kullanım yok."))
        self.assertTrue(g["sinirYok"].startswith("Sınır bilgisi yok"))
        g = run_js('l.kullanimGorunumu({limitler: {pencereler: [{etiket: "5 saatlik", yuzde: 250}, '
                   '{etiket: "Haftalık", gecti: true, yuzde: null}, 7]}, dagilim: {bes_saat: {satirlar: '
                   '[{ad: 5}, {ad: "A", metin: 3, fiyat_eksik: true}], toplam: {ad: "Toplam"}}}}, "bes_saat")')
        self.assertEqual([p["yuzdeMetni"] for p in g["pencereler"]], ["%100", "sıfırlandı"])
        self.assertEqual(g["pencereler"][1]["genislik"], 0)
        self.assertEqual(g["satirlar"], [{"ad": "A", "metin": "", "cikti": "", "fiyatEksik": True, "tur": ""}])
        self.assertIn("fiyatı bilinmiyor", g["fiyatNotu"])


class WiringTest(unittest.TestCase):
    def test_the_page_uses_text_only(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        demo = (WEB / "demo.js").read_text(encoding="utf-8")
        self.assertIn("import { kullanimGorunumu, limitPill } from './limitler.js';", app)
        for el in ('id="limit-pill-detay"', 'id="limit-liste"', 'id="limit-pencereler"', 'data-sekme="haftalik"'):
            self.assertIn(el, html)
        start = app.index("function renderKullanim()")
        body = app[start:app.index("\nfunction ", start + 10)]
        self.assertNotIn("innerHTML", body)
        self.assertIn("getJson('/api/kullanim')", app)
        self.assertIn("'limit-pill'", app[app.index("const UYARI_CIPLERI"):][:120])
        self.assertIn("'/api/kullanim'", demo)
        server = (Path(HERE).parent / "bin" / "server.py").read_text(encoding="utf-8")
        self.assertIn('if path == "/api/kullanim":', server)


if __name__ == "__main__":
    unittest.main()
