"""Tests for the office floor's project wing (proje kanadı), the Uzmanlar odası and the scene's zoom controls.

They run the page's ES modules (web/ofis-davranis.js, web/ofis-sahne.js, web/demo.js) under node when it is installed
and are skipped otherwise; the static checks read the page files. Run: python3 -I test/test_ofis_plani.py"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import webkopya  # noqa: E402  (web/i18n.js next to the copied modules)
import sahip_yasaklari  # noqa: E402,F401  (the owner's name as in his ofis.json; node reads it too)

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")

PRELUDE = r"""
const NOW = Date.parse('2026-11-11T07:00:00Z');   // 10:00 in Istanbul
const iso = (ms) => new Date(ms + 3 * 3600000).toISOString().slice(0, 19);
const st = (x = {}) => ({ projects: [{ name: 'vitrin' }], sahne: { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul' },
  sessions: [], tasks: [], board: [], ceo: { state: 'dormant' }, modeller: [], decisions: [], ...x });
const ses = (name, status, x = {}) => ({ name, project: 'vitrin', status, kind: 'bg', job_status: '', model: '',
  tier: '', note: '', step_kind: '', alt_ajanlar: [], ...x });
const task = (note, status, x = {}) => ({ note, project: 'vitrin', status, session: '', title: 'Giriş', model: 'opus',
  tier: 'kod', started: iso(NOW - 600000), created: iso(NOW - 700000), finished: '', step_kind: '',
  escalated_from: '', queue_position: null, held: false, blocked: '', inceleme_yurutucu: '', ...x });
const run = (s, now = NOW, prev = null, o = {}) => d.niyetler(s, now, prev, o);
const one = (list, id) => list.find((a) => a.id === id) || null;
const names = (n) => Array.from({ length: n }, (_, i) => 'p' + i);
const room = (p, id) => p.odalar.find((r) => r.id === id) || null;
// everyone at lunch at once (the demo's lunch scene): the canteen's worst case
const HEPSI = { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul', ogle_hepsi: true };
"""


def run_js(expr):
    """Evaluates `expr` with ofis-davranis.js as `d`, ofis-sahne.js as `h` and demo.js as `demo` (a temp folder with
    package.json type=module, so their relative imports resolve); returns the JSON-decoded result."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name in ("ofis-davranis.js", "ofis-sahne.js", "demo.js", "ofis-text.js"):
            shutil.copyfile(WEB / name, Path(tmp) / name)
        webkopya.i18n_ekle(tmp)
        uri = lambda n: json.dumps((Path(tmp) / n).as_uri())  # noqa: E731
        code = (f"import * as d from {uri('ofis-davranis.js')};\nimport * as h from {uri('ofis-sahne.js')};\n"
                f"import * as demo from {uri('demo.js')};\n{PRELUDE}\n"
                f"const out = await ({expr});\nprocess.stdout.write(JSON.stringify(out), () => process.exit(0));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                              cwd=tmp, env=dict(os.environ, TZ="UTC"))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


COUNTS = (0, 1, 4, 8, 12)
TESIS = 17  # len(KANAT_TESISLERI): Muhasebe, WC, İdari işler, İK, Sosyal medya ×2, Revir, Spor salonu, Duş, Psikolog, Masaj, Sunucu odası, Ar-Ge odası, the two manager cells, QA odası, Analist odası
COMMON = ["toplanti", "ceo", "denetci", "mudur", "uzmanlar", "oyun", "cay-ocagi", "ortak-alan", "yemekhane", "revir"]


@unittest.skipUnless(NODE, "node is not installed")
class ProjectWingPlanTest(unittest.TestCase):
    def test_the_wing_takes_as_many_rows_as_the_common_area_is_deep_and_every_cell_is_used(self):
        out = run_js("""[0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12].map((n) => { const p = d.ofisPlani(names(n));
          const yemek = room(p, 'yemekhane');
          const cells = p.odalar.filter((r) => r.x >= p.kanat.x - 1e-6).map((r) => [r.id, r.tur]);
          return [n, d.kanatIzgarasi(n), p.kanat, cells, p.odalar.filter((r) => r.tur === 'ekip').length,
            p.odalar.filter((r) => r.tur === 'bos-ekip').map((r) => r.id), p.derinlik, yemek.z + yemek.d]; })""")
        K = run_js("d.OLCU.K")
        P = run_js("(d.OLCU.TEAM_D + d.OLCU.SATIR_ARA) * d.OLCU.K")
        TD = run_js("d.OLCU.TEAM_D * d.OLCU.K")
        prev_rows = 0
        for n, grid, kanat, cells, ekip, bos, derinlik, yemek_alt in out:
            with self.subTest(projects=n):
                R, C = kanat["satir"], kanat["sutun"]
                self.assertEqual((grid["satir"], grid["sutun"], grid["yedek"]), (R, C, kanat["yedek"]))
                self.assertGreaterEqual(R, 5)  # never the old fixed three rows
                self.assertGreaterEqual(R, prev_rows)  # a deeper common area never loses a row
                prev_rows = R
                # the rows fill the floor's depth: the wing's bottom row ends within half a row of the floor's edge
                self.assertLess(derinlik - ((R - 1) * P + TD), P / 2)
                self.assertAlmostEqual(yemek_alt, derinlik, places=6)  # the canteen reaches the floor's edge
                self.assertEqual(ekip, n)
                self.assertGreaterEqual(len(bos), 1)  # always at least one reserved bay
                self.assertEqual(len(bos), kanat["yedek"])
                # no bare cell in the wing: every one of its C x R cells is a facility, a project or a reserved bay
                # the lobby takes two cells; each of the two manager cells holds two offices (plan "Sonraki iş (9)")
                self.assertEqual(len(cells), C * R - 1 + 2)
                self.assertIn(["lobi", "lobi"], cells)

    def test_bays_fill_the_cells_in_a_predictable_order(self):
        out = run_js("""[4, 8, 12].map((n) => { const p = d.ofisPlani(names(n));
          return { kanat: p.kanat, ortak: p.ortak, hucreler: d.kanatIzgarasi(n).hucreler,
            bays: p.odalar.filter((r) => r.tur === 'ekip' || r.tur === 'bos-ekip').map((r) => [r.id, r.x, r.z, r.w, r.d]) }; })""")
        K = run_js("d.OLCU.K")
        self.assertEqual(K, 1.5)
        for n, o in zip((4, 8, 12), out):
            with self.subTest(projects=n):
                k, bays, cells = o["kanat"], o["bays"], o["hucreler"]
                self.assertGreater(k["x"], o["ortak"]["w"] + 5.9)  # a 4-unit spine (x 1.5) between the common area and the wing
                # project i sits in cell i, the reserved bays in the cells after the projects
                self.assertEqual(len(bays), len(cells))
                for i, (b, c) in enumerate(zip(bays, cells)):
                    want = f"ekip-p{i}" if i < n else f"bos-ekip-{i - n + 1}"
                    self.assertEqual((b[0], b[1], b[2]), (want, round(c["x"] * K, 2), round(c["z"] * K, 2)))
                    self.assertGreaterEqual(b[3], 12 * K - 0.01)  # a project bay is always a full 12-unit bay
                    self.assertGreaterEqual(b[4], 9 * K)
                # wing cells first (column by column away from the spine), then the cells under the common area
                wing = [c for c in cells if c["bolge"] == "kanat"]
                self.assertEqual(cells[:len(wing)], wing)
                self.assertEqual(wing, sorted(wing, key=lambda c: (c["sutun"], c["satir"])))

    def test_the_lobby_is_the_floors_front_right_corner_two_cells_big(self):
        for n in (0, 1, 4, 8, 12):
            with self.subTest(projects=n):
                out = run_js(f"""(() => {{ const p = d.ofisPlani(names({n}), {{ max_running_per_project: 2 }}); const l = room(p, 'lobi');
                  const inRoom = (id) => {{ const q = p.dugumler[id]; return !!q && q.oda === 'lobi' && q.x > l.x && q.x < l.x + l.w && q.z > l.z && q.z < l.z + l.d; }};
                  const desks = Object.values(p.dugumler).filter((x) => x.tur === 'masa' || x.tur === 'mudur-masasi').map((x) => x.id);
                  const unreachable = desks.filter((id) => {{ const w = p.yol(id, 'asansor'); return !w.length || w[w.length - 1].id !== 'asansor'; }});
                  const seats = Object.values(p.dugumler).filter((x) => /^lobi-koltuk-\\d$/.test(x.id)).map((x) => x.x + ',' + x.z);
                  const tw = p.odalar.filter((r) => r.tur === 'ekip' || r.tur === 'bos-ekip').map((r) => r.w)[0] || 0;
                  return {{ l, W: p.genislik, D: p.derinlik, unreachable, seats, distinct: new Set(seats).size,
                    spots: ['asansor', 'lobi-nobet', 'lobi-karsilama', 'lobi-resepsiyon', 'lobi-ozet'].every(inRoom) && seats.length === 6,
                    decor: !!(l.lobi && l.lobi.sehpa && l.lobi.su && l.lobi.bitkiler.length >= 2),
                    sek: p.yol('lobi-resepsiyon', 'ceo-kapi').length > 0 && p.yol('lobi-nobet', 'lobi-karsilama').length > 0 }}; }})()""")
                l = out["l"]
                self.assertAlmostEqual(l["x"] + l["w"], out["W"], places=6)  # the right edge …
                self.assertAlmostEqual(l["z"] + l["d"], out["D"], places=6)  # … and the front edge of the floor
                self.assertGreater(l["x"], out["W"] / 2)  # the bottom-right quadrant
                self.assertGreater(l["z"], out["D"] / 2)
                self.assertGreaterEqual(l["w"], 2 * 12 * 1.5)  # two cells big
                self.assertGreaterEqual(l["d"], 9 * 1.5)
                self.assertEqual(out["unreachable"], [])
                self.assertEqual(out["distinct"], 6)
                self.assertTrue(out["spots"] and out["decor"] and out["sek"])

    def test_the_floor_is_balanced_for_any_number_of_projects(self):
        out = run_js("""[0, 1, 4, 8, 12].map((n) => [[], ['glm', 'deepseek']].map((den) => [1, 2].map((per) => {
          const p = d.ofisPlani(names(n), { denetciler: den, max_running_per_project: per });
          // the floor's area farther than a corridor's width from every room: the empty floor
          let empty = 0, all = 0;
          for (let x = 0.5; x < p.genislik; x += 1) for (let z = 0.5; z < p.derinlik; z += 1) { all++;
            if (!p.odalar.some((r) => x > r.x - 4.5 && x < r.x + r.w + 4.5 && z > r.z - 4.5 && z < r.z + r.d + 4.5)) empty++; }
          return [n, den.length, per, p.genislik, p.derinlik, +(empty / all).toFixed(4)]; })).flat())""")
        sizes = {}
        for row in out:
            for n, den, per, w, dd, empty in row:
                with self.subTest(projects=n, auditors=den, per=per):
                    self.assertGreaterEqual(w / dd, 1.3)
                    self.assertLessEqual(w / dd, 1.8)
                    self.assertLessEqual(empty, 0.03)  # no large empty strip
                    sizes.setdefault((den, per), []).append((w, dd))
        for key, s in sizes.items():
            with self.subTest(options=key):
                # adding projects grows the floor in both directions, never only one
                self.assertGreater(s[-1][0], s[0][0])
                self.assertGreater(s[-1][1], s[0][1])
                self.assertEqual([x[0] for x in s], sorted(x[0] for x in s))
                self.assertEqual([x[1] for x in s], sorted(x[1] for x in s))

    def test_some_facilities_sit_under_the_common_area_left_and_right_of_the_canteen(self):
        out = run_js("""(() => { const p = d.ofisPlani(names(1)); const r = (id) => room(p, id);
          return { ortak: p.ortak, yemek: r('yemekhane'), cay: r('cay-ocagi'), revir: r('revir'),
            alt: ['spor', 'dus', 'masaj', 'psikolog', 'sigara'].map((id) => [id, r(id).x, r(id).z, r(id).w, r(id).d]),
            kanat: ['muhasebe', 'wc', 'idari', 'ik', 'sosyal', 'sosyal-studyo'].map((id) => r(id).x >= p.kanat.x) }; })()""")
        o, y, cay = out["ortak"], out["yemek"], out["cay"]
        self.assertEqual(out["kanat"], [True] * 6)
        front = cay["z"] + cay["d"]
        rv = out["revir"]  # the Revir: where the lobby was, at the front row's right end
        self.assertEqual((rv["z"], rv["x"] + rv["w"]), (cay["z"], o["w"]))
        for id_, x, z, w, dd in out["alt"]:
            with self.subTest(room=id_):
                self.assertGreater(z, front)  # below the common area's front row
                self.assertLessEqual(x + w, o["w"] + 1e-6)  # inside the common area's width
                self.assertTrue(x + w <= y["x"] - 2.8 or x >= y["x"] + y["w"] + 2.8)  # beside the canteen
        self.assertEqual([a[0] for a in out["alt"] if a[1] >= y["x"]], ["psikolog"])  # under the Revir
        sig = [a for a in out["alt"] if a[0] == "sigara"][0]
        self.assertEqual(sig[1], out["cay"]["x"])  # the terrace stays in front of the tea corner

    def test_the_common_area_is_the_same_for_any_number_of_projects(self):
        out = run_js(f"""{list(COUNTS)}.map((n) => {{ const p = d.ofisPlani(names(n));
          const common = new Set({json.dumps(COMMON)});
          // the canteen only grows downwards with the number of projects (a chair for every possible luncher)
          const rooms = p.odalar.filter((r) => common.has(r.id)).map((r) => [r.id, r.x, r.z, r.w, r.id === 'yemekhane' ? 0 : r.d]);
          const nodes = Object.values(p.dugumler).filter((x) => common.has(x.oda) && x.oda !== 'yemekhane').map((x) => [x.id, x.x, x.z])
            .sort((a, b) => (a[0] < b[0] ? -1 : 1));
          return {{ rooms, nodes, w: p.genislik, d: p.derinlik, ortak: p.ortak, pano: p.dugumler.pano || null }}; }})""")
        first = out[0]
        self.assertEqual([r[0] for r in first["rooms"]], COMMON)
        for n, o in zip(COUNTS, out):
            with self.subTest(projects=n):
                self.assertEqual(o["rooms"], first["rooms"])
                self.assertEqual(o["nodes"], first["nodes"])
                self.assertEqual(o["ortak"], first["ortak"])
                self.assertIsNone(o["pano"])  # the 3D wall board is gone (owner decision 2026-11-12)
                self.assertGreaterEqual(o["d"], first["d"])  # the floor grows along the wing (x) and the canteen
        widths = [o["w"] for o in out]
        self.assertEqual(widths, sorted(widths))
        self.assertLess(widths[0], widths[-1])

    def test_no_room_touches_another_and_every_place_is_reachable_along_the_edges(self):
        for n in COUNTS:
            with self.subTest(projects=n):
                out = run_js(f"""(() => {{ const p = d.ofisPlani(names({n}), {{max_running_per_project: 4,
                    denetciler: ['glm', 'deepseek']}});
                  const r = p.odalar; const close = [];
                  for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {{
                    const a = r[i], b = r[j];
                    const gx = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w)), gz = Math.max(b.z - (a.z + a.d), a.z - (b.z + b.d));
                    if (Math.max(gx, gz) < 1.9) close.push(a.id + '|' + b.id);
                  }}
                  const out = r.filter((x) => x.x < 0 || x.z < 0 || x.x + x.w > p.genislik + 1e-6 || x.z + x.d > p.derinlik + 1e-6)
                    .map((x) => x.id);
                  const edges = new Set(p.kenarlar.flatMap(([a, b]) => [a + '|' + b, b + '|' + a]));
                  const bad = [];
                  for (const id of Object.keys(p.dugumler)) {{ const w = p.yol('asansor', id);
                    if (!w.length || w[w.length - 1].id !== id) bad.push(id);
                    for (let i = 1; i < w.length; i++) if (!edges.has(w[i - 1].id + '|' + w[i].id)) bad.push(id); }}
                  return {{ close, out, bad }}; }})()""")
                self.assertEqual(out, {"close": [], "out": [], "bad": []})

    def test_a_walk_from_the_lift_to_the_ceo_takes_the_spine_corridor(self):
        out = run_js("""(() => { const p = d.ofisPlani(names(4));
          const ids = p.yol('asansor', 'ceo-masa').map((x) => x.id);
          const spine = ids.filter((id) => /^koridor-[01]-sag$|^kanat-\\d-omurga$/.test(id));
          const sx = new Set(spine.map((id) => p.dugumler[id].x));
          // every straight edge between two corridor nodes runs along x or along z, never across a room
          const diag = p.kenarlar.filter(([a, b]) => p.dugumler[a].tur === 'koridor' && p.dugumler[b].tur === 'koridor' &&
            p.dugumler[a].x !== p.dugumler[b].x && p.dugumler[a].z !== p.dugumler[b].z);
          return { first: ids[0], last: ids.slice(-2), spine: spine.length, sx: sx.size,
            spineX: [...sx][0], ortak: p.ortak.w, kanat: p.kanat.x, diag }; })()""")
        self.assertEqual(out["first"], "asansor")
        self.assertEqual(out["last"][-1], "ceo-masa")
        self.assertTrue(out["last"][0] == "ceo-kapi" or out["last"][0].startswith("gecit:"), out["last"])  # around its desk
        self.assertGreaterEqual(out["spine"], 2)
        self.assertEqual(out["sx"], 1)  # one straight spine
        self.assertTrue(out["ortak"] < out["spineX"] < out["kanat"])
        self.assertEqual(out["diag"], [])

    def test_each_bay_has_its_desks_manager_desk_helper_spots_and_label_and_reserved_bays_none(self):
        out = run_js("""(() => { const p = d.ofisPlani(['vitrin', 'blog'], {max_running_per_project: 2});
          const inRoom = (id) => Object.values(p.dugumler).filter((x) => x.oda === id).map((x) => x.tur);
          const labels = h.odaEtiketleri(p).map((r) => [r.id, r.ad]);
          return { vitrin: inRoom('ekip-vitrin'), bos: inRoom('bos-ekip-1'), labels,
            desks: Object.keys(p.dugumler).filter((id) => /^ekip-blog-(mudur|masa-\\d)$/.test(id)).sort() }; })()""")
        self.assertEqual(out["vitrin"].count("masa"), 4)  # max_running_per_project + 2
        self.assertEqual(out["vitrin"].count("mudur-masasi"), 1)
        self.assertEqual(out["vitrin"].count("yardimci"), 5 * 5)
        self.assertEqual(out["bos"], ["kapi"])  # an empty reserved bay: no desks, no seats
        self.assertEqual(out["desks"], ["ekip-blog-masa-1", "ekip-blog-masa-2", "ekip-blog-masa-3", "ekip-blog-masa-4",
                                        "ekip-blog-mudur"])
        self.assertIn(["ekip-vitrin", "vitrin ekibi"], out["labels"])
        self.assertIn(["bos-ekip-1", "Boş ekip alanı · yeni proje"], out["labels"])
        self.assertIn(["uzmanlar", "Uzmanlar odası"], out["labels"])


@unittest.skipUnless(NODE, "node is not installed")
class UzmanlarRoomTest(unittest.TestCase):
    def test_the_room_has_six_desks_with_helper_spots_in_the_middle_row(self):
        out = run_js("""(() => { const p = d.ofisPlani(['vitrin']); const r = room(p, 'uzmanlar'), ceo = room(p, 'ceo');
          const desks = Object.values(p.dugumler).filter((x) => x.oda === 'uzmanlar' && x.tur === 'masa');
          const xs = [...new Set(desks.map((x) => x.x))].sort((a, b) => a - b);
          return { n: desks.length, ids: desks.map((x) => x.id), helpers: Object.keys(p.dugumler)
            .filter((id) => /^uzmanlar-masa-\\d-yardimci-\\d$/.test(id)).length, yan: !!p.dugumler['uzmanlar-masa-5-yan'],
            mid: +(r.x + r.w / 2 - (ceo.x + ceo.w / 2)).toFixed(6), below: r.z > ceo.z + ceo.d,
            gap: Math.min(...xs.slice(1).map((x, i) => x - xs[i])), front: r.z + r.d < room(p, 'lobi').z }; })()""")
        self.assertEqual(out["n"], 6)
        self.assertEqual(out["ids"], [f"uzmanlar-masa-{i}" for i in range(6)])
        self.assertEqual(out["helpers"], 6 * 5)
        self.assertTrue(out["yan"])
        self.assertEqual(out["mid"], 0)  # under the CEO's room
        self.assertTrue(out["below"] and out["front"])  # the middle row of the common area
        self.assertGreaterEqual(out["gap"], 6)

    def test_review_work_and_the_hakem_type_there_and_the_meeting_room_stays_empty(self):
        out = run_js("""(() => {
          const s = st({sessions: [ses('r1', 'busy', {note: 'a.md', tier: 'inceleme'}),
              ses('r2', 'busy', {note: 'b.md', step_kind: 'plan-inceleme'}), ses('r3', 'idle', {note: 'c.md'})],
            tasks: [task('a.md', 'calisiyor', {session: 'r1', tier: 'inceleme', model: 'opus'}),
              task('b.md', 'calisiyor', {session: 'r2', step_kind: 'plan-inceleme', tier: 'inceleme'}),
              task('c.md', 'calisiyor', {session: 'r3', step_kind: 'kod-inceleme', tier: 'inceleme'}),
              task('p.md', 'incelemede', {inceleme_yurutucu: 'codex', step_kind: 'kod-inceleme', tier: 'inceleme'})],
            modeller: [{model: 'guvenlik', unvan: 'Güvenlik denetçisi', ajan_modeli: 'sonnet', calisan: 1, durum: 'calisiyor'}],
            denetim: {is: 'p.md', denetciler: ['guvenlik'], hakem: 'sonnet'}});
          const r = run(s);
          const pick = (a) => [a.yer, a.masa, a.poz, a.durum_metni];
          return { hakem: pick(one(r, 'hakem')), a: pick(one(r, 'is:a')), b: pick(one(r, 'is:b')), c: pick(one(r, 'is:c')),
            sec: one(r, 'denetci:guvenlik').yer, sec_oda: d.ofisPlani(s.projects).dugumler[one(r, 'denetci:guvenlik').yer].oda,
            meeting: r.filter((x) => typeof x.yer === 'string' && x.yer.startsWith('toplanti-')).map((x) => x.id) }; })()""")
        # plan "Sonraki iş (9)": the hakem stays in the Uzmanlar odası; a Claude kod review (and an inceleme-tier job)
        # sits at a Kıdemli Tester desk of the QA odası, a plan review at an Analist odası desk
        self.assertEqual(out["hakem"], ["uzmanlar-masa-0", "uzmanlar-masa-0", "yaziyor", "bulguları tartıyor"])
        self.assertEqual(out["a"], ["qa-masa-0", "qa-masa-0", "yaziyor", "inceliyor · Giriş"])
        self.assertEqual(out["b"], ["analist-masa-0", "analist-masa-0", "yaziyor", "inceliyor · Giriş"])
        self.assertEqual(out["c"], ["qa-masa-1", "qa-masa-1", "bekliyor", "inceleme · sessiz"])
        self.assertEqual(out["sec"], "denetci-masa-guvenlik")  # the IT güvenlik desk …
        self.assertEqual(out["sec_oda"], "sunucu")  # … in the Sunucu odası
        self.assertEqual(out["meeting"], [])

    def test_the_sonnet_kadro_walks_to_an_uzmanlar_desk_as_the_hakem(self):
        out = run_js("""(() => { const m = [{model: 'sonnet', durum: 'hazir'}];
          const s = (denetim) => st({modeller: m, denetim,
            tasks: [task('p.md', 'incelemede', {inceleme_yurutucu: 'codex', tier: 'inceleme'})]});
          const idle = run(s(null), NOW, null, {hafif: true});
          const hk = run(s({is: 'p.md', denetciler: [], hakem: 'sonnet'}), NOW + 2000, idle, {hafif: true});
          return [one(idle, 'kadro:sonnet').yer, one(hk, 'hakem').devral, one(hk, 'hakem').yer, !!one(hk, 'kadro:sonnet')]; })()""")
        self.assertEqual(out, ["ortak-alan-sonnet", "kadro:sonnet", "uzmanlar-masa-0", False])

    def test_a_full_room_gets_one_summary(self):
        out = run_js("""(() => { const s = Array.from({length: 8}, (_, i) => ses('r' + i, 'busy', {note: 'r' + i + '.md'}));
          const t = s.map((x, i) => task('r' + i + '.md', 'calisiyor', {session: x.name, tier: 'inceleme'}));
          const r = run(st({sessions: s, tasks: t}));
          const seated = r.filter((a) => /^qa-masa-\\d$/.test(a.yer || '')).map((a) => a.yer);
          return { seated: seated.length, unique: new Set(seated).size, ozet: one(r, 'ozet:qa') }; })()""")
        self.assertEqual((out["seated"], out["unique"]), (4, 4))  # the QA odası's four desks
        self.assertEqual((out["ozet"]["etiket"], out["ozet"]["yer"], out["ozet"]["tiklama"]), ("+4", "qa-ozet", None))
        self.assertIn("QA odasında", out["ozet"]["durum_metni"])


@unittest.skipUnless(NODE, "node is not installed")
class WingFacilitiesTest(unittest.TestCase):
    def test_the_social_media_department_has_a_desk_per_member_in_pods(self):
        out = run_js("""(() => { const p = d.ofisPlani(['vitrin']); const room = (id) => p.odalar.find((r) => r.id === id);
          return d.SOSYAL_EKIBI.map((u) => { const n = p.dugumler[d.sosyalMasasi(u.id)]; const r = room(n.oda);
            return [u.id, u.grup, n.oda, n.tur, n.x > r.x && n.x < r.x + r.w && n.z > r.z && n.z < r.z + r.d]; }); })()""")
        self.assertEqual(len(out), 14)
        for uid, grup, oda, tur, inside in out:
            self.assertEqual((oda, tur, inside), ("sosyal" if grup == "platform" else "sosyal-studyo", "masa", True), uid)

    """Muhasebe and WC: the wing's first two slots, fixed for any number of projects (owner decision 2026-11-12)."""

    def test_facilities_never_move_and_keep_their_places(self):
        out = run_js(f"""{list(COUNTS)}.map((n) => {{ const p = d.ofisPlani(names(n));
          const ids = new Set([...d.KANAT_TESISLERI, 'sigara', 'dinlenme']);
          return {{ rooms: p.odalar.filter((r) => ids.has(r.id)).map((r) => [r.id, r.tur, r.ad, r.x, r.z, r.w, r.d, r.blok || null]),
            nodes: Object.values(p.dugumler).filter((x) => ids.has(x.oda)).map((x) => [x.id, x.x, x.z, x.tur])
              .sort((a, b) => (a[0] < b[0] ? -1 : 1)) }}; }})""")
        first = out[0]
        self.assertEqual(sorted(r[:3] for r in first["rooms"]), [["analist", "analist", "Analist odası"],
                         ["arge", "arge", "Ar-Ge odası"],
                         ["dinlenme", "dinlenme", "Dinlenme odası"],
                         ["dus", "dus", "Duş"], ["idari", "idari", "İdari işler"], ["ik", "ik", "İnsan kaynakları"],
                         ["masaj", "masaj", "Masaj odası"], ["muhasebe", "muhasebe", "Muhasebe"],
                         ["psikolog", "psikolog", "Psikolog"], ["qa", "qa", "QA odası"], ["revir", "revir", "Revir"],
                         ["sigara", "balkon", "Sigara odası"], ["sosyal", "sosyal", "Sosyal medya ve tasarım"],
                         ["sosyal-studyo", "sosyal", "Sosyal medya ve tasarım · stüdyo"], ["spor", "spor", "Spor salonu"],
                         ["sunucu", "sunucu", "Sunucu odası"], ["wc", "wc", "WC"]])
        for n, o in zip(COUNTS, out):
            with self.subTest(projects=n):
                self.assertEqual(o, first)
        ids = {x[0]: x for x in first["nodes"]}
        for need in ("muhasebe-masa", "idari-masa", "ik-masa", "sosyal-masa-instagram", "sosyal-masa-topluluk", "revir-masa",
                     "psikolog-masa", "masaj-yatak-1", "spor-kosu-0", "spor-mat-3", "dus-ici-1", "dus-kapi-0", "sigara-yer-3", "dinlenme-yatak-4", "dinlenme-yatak-19",
                     "dinlenme-yatak-19-ayak", "dinlenme-gang", "wc-kapi-0", "wc-kapi-1", "wc-ici-0", "wc-ici-1", "wc-lavabo-0", "wc-lavabo-1"):
            self.assertIn(need, ids)
        # the Dinlenme odası (owner decision 2026-11-13): exactly 20 beds, all inside the room, the same layout for any project count
        self.assertEqual(len([i for i in ids if re.match(r"^dinlenme-yatak-\d+$", i)]), 20)
        # the covered block sits inside the WC bay; the cubicle spots are inside the block, the doors and sinks outside
        wc = [r for r in first["rooms"] if r[0] == "wc"][0]
        b = wc[7]
        self.assertTrue(wc[3] < b["x"] and b["x"] + b["w"] < wc[3] + wc[5] and wc[4] < b["z"] and b["z"] + b["d"] < wc[4] + wc[6])
        inside = lambda x: b["x"] < x[1] < b["x"] + b["w"] and b["z"] < x[2] < b["z"] + b["d"]  # noqa: E731
        self.assertTrue(inside(ids["wc-ici-0"]) and inside(ids["wc-ici-1"]))
        for k in ("wc-kapi-0", "wc-kapi-1", "wc-lavabo-0", "wc-lavabo-1", "wc-gecit"):
            self.assertFalse(inside(ids[k]), k)

    def test_the_terrace_holds_about_eight_with_the_smoking_corner_at_one_end(self):
        out = run_js("""[0, 4, 12].map((n) => { const p = d.ofisPlani(names(n)); const r = room(p, 'sigara');
          const spots = Object.values(p.dugumler).filter((x) => x.oda === 'sigara' && /^sigara-yer-\\d+$/.test(x.id));
          const inside = spots.every((q) => q.x > r.x + 0.3 && q.x < r.x + r.w - 0.3 && q.z > r.z + 0.3 && q.z < r.z + r.d - 0.3);
          let near = 99;
          for (let i = 0; i < spots.length; i++) for (let j = i + 1; j < spots.length; j++)
            near = Math.min(near, Math.hypot(spots[i].x - spots[j].x, spots[i].z - spots[j].z));
          const reach = spots.every((q) => { const w = p.yol('asansor', q.id); return w.length && w[w.length - 1].id === q.id; });
          // whatever the molaPlani hands out to ten idle actors: distinct places on the terrace
          const m = d.molaPlani(Array.from({ length: 10 }, (_, i) => ({ id: 'x' + i, kadro: true })), NOW, p, 'sigara');
          const given = [...m.values()].map((x) => x.yer);
          const others = p.odalar.filter((o) => o.id !== 'sigara').filter((o) => Math.max(o.x - (r.x + r.w), r.x - (o.x + o.w)) < 1.9 &&
            Math.max(o.z - (r.z + r.d), r.z - (o.z + o.d)) < 1.9).map((o) => o.id);
          return { n: spots.length, agents: d.SIGARA_AJAN_YERLERI.length, inside, near, reach, given, others,
            benches: r.balkon.banklar.length, plants: r.balkon.bitkiler.length, kul: r.balkon.kul, w: r.w, x: r.x,
            smokers: spots.filter((q) => q.tur === 'sigara' && Math.hypot(q.x - r.balkon.kul[0], q.z - r.balkon.kul[1]) < 2.5).length }; })""")
        for o in out:
            self.assertGreaterEqual(o["n"], 10)  # eight for the agents and the two staff places
            self.assertGreaterEqual(o["agents"], 8)
            self.assertTrue(o["inside"] and o["reach"])
            self.assertGreaterEqual(o["near"], 1.2)  # distinct, a body apart
            self.assertEqual(len(o["given"]), len(set(o["given"])))
            self.assertEqual(len(o["given"]), o["agents"])  # ten want a break, eight places
            self.assertEqual(o["others"], [])  # it overlaps no room
            self.assertGreaterEqual(o["benches"], 2)
            self.assertGreaterEqual(o["plants"], 2)
            self.assertLess(o["kul"][0] - o["x"], o["w"] / 3)  # the ashtray at the left end
            self.assertGreaterEqual(o["smokers"], 4)
        self.assertEqual(out[0], out[-1])  # fixed for any number of projects

    def test_the_walk_to_a_cubicle_goes_through_its_door_and_never_crosses_the_block(self):
        out = run_js("""(() => { const p = d.ofisPlani(names(1)); const b = p.odalar.find((r) => r.id === 'wc').blok;
          const w = p.yol('asansor', 'wc-ici-0').map((x) => x.id);
          const pts = p.yol('asansor', 'wc-ici-0');
          const cross = [];
          for (let i = 1; i < pts.length - 1; i++) { const a = pts[i - 1], c = pts[i];
            for (let s = 0; s <= 20; s++) { const x = a.x + (c.x - a.x) * s / 20, z = a.z + (c.z - a.z) * s / 20;
              if (x > b.x && x < b.x + b.w && z > b.z && z < b.z + b.d) cross.push(a.id + '>' + c.id); } }
          return { w, cross: [...new Set(cross)] }; })()""")
        self.assertEqual(out["w"][-2:], ["wc-kapi-0", "wc-ici-0"])
        self.assertEqual(out["cross"], [])


@unittest.skipUnless(NODE, "node is not installed")
class CanteenTest(unittest.TestCase):
    """The owner, 2026-11-12: at lunch everyone who may eat gets a real canteen chair; nobody stands outside or in a "+N"."""

    LUNCH_OFFICE = r"""
      const at = (hhmm) => Date.parse(`2026-11-11T${String(Number(hhmm.slice(0, 2)) - 3).padStart(2, '0')}:${hhmm.slice(3)}:30Z`);
      const projs = names(4).map((name) => ({ name }));
      const P = d.ofisPlani(projs, { max_running_per_project: 1, denetciler: ['glm', 'deepseek'] });
      const sessions = projs.flatMap((p) => Array.from({ length: P.masa_sayisi }, (_, i) =>
        ses(`ofis-${p.name}-bos-${i}`, 'idle', { project: p.name, model: 'sonnet' })));
      const s = st({ projects: projs, sessions, ceo: { state: 'idle' },
        modeller: ['haiku', 'sonnet', 'opus', 'fable', 'codex'].map((model) => ({ model, durum: 'hazir' }))
          .concat(['glm', 'deepseek'].map((model) => ({ model, unvan: 'Dış denetçi', durum: 'hazir' }))) });
      // the lunch-goers: the idle agents, the kadro, the auditors, the CEO (the staff eat on their own chairs too)
      const goer = (a) => a.id === 'ceo' || /^(oturum:|kadro:|denetci:)/.test(a.id);
      const snap = (hhmm, o = {}) => { const l = run(s, at(hhmm), null, { plan: P, max_running_per_project: 1, ...o });
        const g = l.filter(goer);
        const spots = l.filter((a) => a.yer && !/^(koridor|kanat|alt-\d)/.test(a.yer)).map((a) => a.yer);
        return { n: g.length, eating: g.filter((a) => a.poz === 'yemek').map((a) => a.id).sort(),
          other: g.filter((a) => a.poz !== 'yemek').map((a) => [a.id, a.yer, a.poz, a.durum_metni]),
          shared: spots.length - new Set(spots).size, ids: l.length - new Set(l.map((a) => a.id)).size,
          seeded: g.filter((a) => a.poz === 'yemek').every((a) => d.ogleYemekte(a.id, at(hhmm), s.sahne)) }; };
    """

    def test_at_12_05_most_eat_and_at_12_50_a_seeded_subset_does_something_else(self):
        out = run_js(f"""(() => {{ {self.LUNCH_OFFICE}
          return {{ early: snap('12:05'), late: snap('12:50'), again: snap('12:50'), light: snap('12:50', {{ hafif: true }}),
            after: snap('13:05') }}; }})()""")
        e, l = out["early"], out["late"]
        self.assertGreater(len(e["eating"]), 0.6 * e["n"])  # most lunch-goers eat at 12:05
        self.assertTrue(l["other"], l)  # at 12:50 some do something else …
        self.assertTrue(l["eating"], l)  # … while a seeded few are still at the table
        self.assertLess(len(l["eating"]), len(e["eating"]))
        away = [o for o in l["other"] if o[1] and not o[1].startswith("yemekhane-")]
        self.assertTrue(any(o[2] in ("pingpong", "bilardo", "dart", "kosuyor", "bisiklet", "agirlik", "yoga", "yatiyor",
                                     "cay", "cay-al", "sigara", "yuruyor", "lavaboda", "dusta", "masajda") for o in away), away)
        for snap in (e, l, out["after"], out["light"]):
            self.assertEqual((snap["shared"], snap["ids"]), (0, 0))  # nobody on two spots, no two on one spot
        for snap in (e, l, out["after"]):
            self.assertTrue(snap["seeded"])  # every eater is one whose seeded lunch slot is now (hafif: all of them)
        self.assertEqual(out["again"], l)  # deterministic
        self.assertEqual(len(out["light"]["eating"]), out["light"]["n"])  # hafif: the whole hour at the table
        self.assertEqual(out["after"]["eating"], [])

    def test_each_one_eats_one_seeded_block_of_20_to_35_minutes(self):
        out = run_js("""(() => { const sahne = { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul' };
          const ids = Array.from({ length: 40 }, (_, i) => 'oturum:x' + i).concat(['ceo', 'kadro:opus', 'denetci:codex', 'sus:sekreter']);
          return ids.map((id) => { const m = Array.from({ length: 80 }, (_, k) =>
            d.ogleYemekte(id, Date.parse('2026-11-11T08:50:30Z') + k * 60000, sahne) ? 1 : 0);
            return [id, m.join('')]; }); })()""")
        starts = set()
        for id_, mins in out:
            with self.subTest(id=id_):
                self.assertEqual(mins[:10], "0" * 10)  # nothing before 12:00 …
                self.assertEqual(mins[70:], "0" * 10)  # … or after 13:00
                block = mins.strip("0")
                self.assertNotIn("0", block)  # one block
                self.assertTrue(20 <= len(block) <= 35, len(block))
                starts.add(mins.index("1") - 10)
        self.assertGreater(len(starts), 4)  # staggered starts

    def test_an_empty_window_means_no_lunch_and_an_overnight_window_keeps_one_plan(self):
        out = run_js("""(() => { const bos = { ogle: '12:00-12:00', saat_dilimi: 'Europe/Istanbul' };
          const gun = Array.from({ length: 48 }, (_, i) => Date.parse('2026-11-11T00:00:00Z') + i * 1800000);
          const gece = { ogle: '23:30-00:30', saat_dilimi: 'Europe/Istanbul' };
          // 23:30 Istanbul on 11 Nov = 20:30 UTC; one minute steps through the window
          const mins = Array.from({ length: 60 }, (_, k) => d.ogleYemekte('oturum:x0', Date.parse('2026-11-11T20:30:30Z') + k * 60000, gece) ? 1 : 0).join('');
          const at = (iso) => d.ogleYemekte('oturum:x0', Date.parse(iso), gece);
          const s = st({ sahne: bos, sessions: [ses('ofis-w-1', 'idle')], ceo: { state: 'idle' } });
          return { ogle: gun.some((m) => d.ogleMi(m, bos)), yemek: gun.some((m) => d.ogleYemekte('oturum:x0', m, bos)),
            // (breakfast and dinner still happen since 2026-11-14: only lunch is asked for here)
            eaters: gun.some((m) => run(s, m).some((a) => a.poz === 'yemek' && /öğle|yemek yiyor/.test(a.durum_metni || ''))), mins,
            a2345: at('2026-11-11T20:45:30Z'), a0010: at('2026-11-11T21:10:30Z') }; })()""")
        self.assertFalse(out["ogle"] or out["yemek"] or out["eaters"])  # 12:00-12:00: no lunch at all
        block = out["mins"].strip("0")
        self.assertTrue(block and "0" not in block, out["mins"])  # one continuous block across midnight
        self.assertTrue(20 <= len(block) <= 35)
        first = out["mins"].index("1")
        # 23:45 is minute 15, 00:10 minute 40 of the window: each eats exactly when the one plan says so
        self.assertEqual(out["a2345"], first <= 15 < first + len(block))
        self.assertEqual(out["a0010"], first <= 40 < first + len(block))

    def test_the_canteen_manager_serves_collects_washes_and_never_sits(self):
        out = run_js("""(() => { const P = d.ofisPlani(names(4), { max_running_per_project: 1 }); const r = room(P, 'yemekhane');
          const inside = (y) => { const q = P.dugumler[y]; return !!q && q.oda === 'yemekhane' && q.x > r.x && q.x < r.x + r.w && q.z > r.z && q.z < r.z + r.d; };
          const s = st({ projects: names(4).map((name) => ({ name })), ceo: { state: 'idle' },
            sessions: [ses('ofis-p0-bos', 'idle', { project: 'p0' }), ses('ofis-p1-bos', 'idle', { project: 'p1' })] });
          const day = Array.from({ length: 24 * 12 }, (_, i) => Date.parse('2026-11-10T21:00:20Z') + i * 300000)
            .concat(Array.from({ length: 180 }, (_, i) => Date.parse('2026-11-11T09:00:05Z') + i * 20000));
          const seen = day.map((m) => { const l = run(s, m, null, { plan: P, max_running_per_project: 1 });
            // the yemekhane görevlisi on duty (three on the 24/7 rotation since 2026-11-14; its own meal on a staff chair aside)
            const y = l.find((a) => a.gorevli === 'yemekhane' && a.nobetci && !a.otel && a.poz !== 'yemek'); if (!y) return null;
            const taken = l.filter((a) => a !== y && a.yer === y.yer).map((a) => a.id);
            return [m, y.yer, y.poz, y.durum_metni, taken, d.ogleMi(m, s.sahne)]; }).filter(Boolean);
          const lunch = seen.filter((x) => x[5]);
          const chairs = Object.keys(P.dugumler).filter((k) => /^yemekhane-(sandalye|personel)-/.test(k));
          const spots = [d.YEMEKHANE_SERVIS, d.YEMEKHANE_BULASIK, ...Object.keys(P.dugumler).filter((k) => /^yemekhane-masa-ucu-/.test(k))];
          const B = r.bulasik;
          const lowest = Math.max(...chairs.map((k) => P.dugumler[k].z));
          return { spotsInside: spots.every(inside), onChair: seen.filter((x) => chairs.includes(x[1])).length,
            shared: seen.filter((x) => x[4].length && !/^(koridor|kanat|alt-\\d)/.test(x[1])).map((x) => [x[1], x[4]]),
            phases: [...new Set(lunch.map((x) => x[3]))].sort(), early: lunch.filter((x) => x[0] < Date.parse('2026-11-11T09:15:00Z')).map((x) => x[3]),
            prep: seen.filter((x) => x[3] === 'öğle yemeğini hazırlıyor').map((x) => new Date(x[0]).toISOString().slice(11, 16)),
            wash: lunch.filter((x) => x[2] === 'yikiyor').map((x) => x[1]), tray: lunch.filter((x) => x[2] === 'tepsi').map((x) => x[1]),
            corner: !!B && B.z > lowest && B.z < r.z + r.d && [B.lavabo, B.raf, B.araba].every(([x, z]) => x > r.x && x < r.x + r.w && z > B.z && z < r.z + r.d),
            light: run(s, Date.parse('2026-11-11T09:30:00Z'), null, { hafif: true, plan: P }).some((a) => a.gorevli === 'yemekhane'),
            bilgi: d.BILGI_PERSONELI({ tur: 'sus', gorevli: 'yemekhane' }) }; })()""")
        self.assertTrue(out["spotsInside"] and out["corner"])
        self.assertEqual(out["onChair"], 0)  # never a luncher's (or the staff's) chair
        self.assertEqual(out["shared"], [])  # (a corridor walk may cross another)
        self.assertEqual(set(out["early"]), {"servis yapıyor"})  # before the first eaters finish it serves
        self.assertTrue({"tepsileri topluyor", "bulaşık yıkıyor"} <= set(out["phases"]), out["phases"])
        self.assertTrue(out["wash"] and set(out["wash"]) == {"yemekhane-bulasik"})
        self.assertTrue(out["tray"] and all(y.startswith("yemekhane-masa-ucu-") for y in out["tray"]))
        self.assertTrue(out["prep"] and all("08:45" <= x < "09:00" for x in out["prep"]), out["prep"])  # 11:45-12:00 local
        self.assertFalse(out["light"])  # hidden in hafif
        self.assertTrue(out["bilgi"])

    def test_the_canteen_managers_card_says_only_what_is_known(self):
        out = run_js("""(() => { const s = st({ sahne: { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul' } });
          const ak = [{ id: 'a', poz: 'yemek', yer: 'yemekhane-sandalye-0' }, { id: 'b', poz: 'yemek', yer: 'yemekhane-sandalye-1' },
            { id: 'c', poz: 'cay', yer: 'cay-ocagi-yer-0' }];
          const y = { id: 'sus:yemekhane', tur: 'sus', gorevli: 'yemekhane', etiket: 'Yemekhane görevlisi', durum_metni: 'tezgâhta' };
          return [h.karakterKarti(y, s, Date.parse('2026-11-11T09:30:00Z'), { aktorler: ak }),
            h.karakterKarti(y, s, Date.parse('2026-11-11T07:00:00Z'), { aktorler: [] })]; })()""")
        lines = [[(x["ad"], x["metin"]) for x in c["satirlar"]] for c in out]
        self.assertEqual(out[0]["baslik"], "Yemekhane görevlisi")
        self.assertIn(("Yemekhanede", "şu an 2 kişi yemekte"), lines[0])
        self.assertIn(("Öğle yemeği", "12:00–13:00"), lines[0])
        self.assertTrue(any(a == "Nöbette" for a, _ in lines[0]), lines[0])  # the team's shift rows (2026-11-14)
        self.assertIn(("Yemekhanede", "şu an kimse yemekte değil"), lines[1])
        self.assertFalse(any("bugün" in m and "yedi" in m for _, m in lines[0] + lines[1]))  # not derivable: no line

    def test_the_canteen_has_a_chair_for_everyone_and_reaches_the_floors_edge(self):
        out = run_js("""[0, 1, 4, 8, 12].flatMap((n) => [1, 2, 4].map((per) => { const den = ['glm', 'deepseek'];
          const p = d.ofisPlani(names(n), { max_running_per_project: per, denetciler: den });
          const r = room(p, 'yemekhane');
          const chairs = Object.values(p.dugumler).filter((x) => /^yemekhane-sandalye-\\d+$/.test(x.id));
          return [n, per, chairs.length, d.yemekKapasitesi(n, p.masa_sayisi, 3),
            chairs.every((q) => q.x > r.x && q.x < r.x + r.w && q.z > r.z && q.z < r.z + r.d), +(r.z + r.d - p.derinlik).toFixed(6),
            !!p.dugumler['yemekhane-sandalye-7']]; }))""")
        for n, per, chairs, cap, inside, edge, ceo in out:
            with self.subTest(projects=n, per=per):
                self.assertGreaterEqual(chairs, cap)
                self.assertTrue(inside and ceo)
                self.assertEqual(edge, 0)

    def test_a_full_office_at_12_30_seats_every_luncher_on_a_distinct_chair_inside_the_canteen(self):
        for n in COUNTS:
            with self.subTest(projects=n):
                out = run_js(f"""(() => {{ const LUNCH = Date.parse('2026-11-11T09:30:00Z');
                  const projs = names({n}).map((name) => ({{ name }}));
                  const P = d.ofisPlani(projs, {{ max_running_per_project: 1, denetciler: ['glm', 'deepseek'] }});
                  // the most lunch-goers the desks allow: an idle session for every desk of every project
                  const sessions = projs.flatMap((p) => Array.from({{ length: P.masa_sayisi }}, (_, i) =>
                    ses(`ofis-${{p.name}}-bos-${{i}}`, 'idle', {{ project: p.name, model: 'sonnet' }})));
                  const s = st({{ projects: projs, sessions, ceo: {{ state: 'idle' }}, sahne: HEPSI,
                    modeller: ['haiku', 'sonnet', 'opus', 'fable', 'codex'].map((model) => ({{ model, durum: 'hazir' }}))
                      .concat(['glm', 'deepseek'].map((model) => ({{ model, unvan: 'Dış denetçi', durum: 'hazir' }}))) }});
                  const l = run(s, LUNCH, null, {{ plan: P, max_running_per_project: 1 }});
                  const room = P.odalar.find((r) => r.id === 'yemekhane');
                  const inside = (y) => {{ const q = P.dugumler[y]; return !!q && q.oda === 'yemekhane' && q.x > room.x && q.x < room.x + room.w &&
                    q.z > room.z && q.z < room.z + room.d; }};
                  // the guard eats at his post (he never leaves the lobby: duty breaks stay close)
                  const lunch = l.filter((a) => a.poz === 'yemek' && a.id !== 'sus:guvenlik');
                  const notEating = l.filter((a) => a.poz !== 'yemek' && a.id !== 'sus:cayci' && a.id !== 'sus:yemekhane' && !a.nobetci && a.tur !== 'alt-ajan' && !a.otel).map((a) => a.id + '@' + a.yer);
                  return {{ n: lunch.length, distinct: new Set(lunch.map((a) => a.yer)).size, outside: lunch.filter((a) => !inside(a.yer)).map((a) => a.id),
                    ozet: l.filter((a) => a.tur === 'ozet').map((a) => a.id), notEating,
                    guard: (l.find((a) => a.id === 'sus:guvenlik') || {{}}).yer,
                    cap: d.yemekKapasitesi({n}, P.masa_sayisi, 3) }}; }})()""")
                self.assertEqual(out["ozet"], [])
                self.assertEqual(out["outside"], [])
                self.assertEqual(out["distinct"], out["n"])
                self.assertEqual(out["notEating"], [])  # everyone (but the tea server, the canteen manager and the IT person on shift) is at lunch
                self.assertGreaterEqual(out["n"], 20)
                self.assertEqual(out["guard"], "lobi-nobet")


@unittest.skipUnless(NODE, "node is not installed")
class CompanyRoomsTest(unittest.TestCase):
    """Plan "Sonraki iş (9)" step 1 (owner decision 2026-11-13): the four managers' offices, the QA odası, the Analist odası and the
    IT güvenlik desk are fixed cells; the reviews and the planning work sit there by role."""

    def test_the_offices_and_rooms_are_fixed_reachable_cells_with_their_desks(self):
        out = run_js(f"""{list(COUNTS)}.map((n) => {{ const p = d.ofisPlani(names(n), {{ denetciler: ['glm', 'guvenlik'] }});
          const ids = ['mudurluk-yazilim', 'mudurluk-it', 'mudurluk-qa', 'mudurluk-analist', 'qa', 'analist'];
          const inside = (id) => {{ const q = p.dugumler[id]; if (!q) return null; const r = room(p, q.oda);
            return r && q.x > r.x && q.x < r.x + r.w && q.z > r.z && q.z < r.z + r.d ? q.oda : 'disarida'; }};
          return {{ rooms: ids.map((id) => {{ const r = room(p, id); return r && [r.id, r.tur, r.ad, r.x, r.z, r.w, r.d]; }}),
            desks: d.MUDURLUKLER.map((m) => [m.key, p.dugumler[d.mudurMasasi(m.key)].tur, inside(d.mudurMasasi(m.key)),
              inside(d.mudurMasasi(m.key) + '-yan')]),
            plan: [inside(d.PLAN_MASASI), p.dugumler[d.PLAN_MASASI].tur, !!p.dugumler[d.PLAN_MASASI + '-yardimci-0']],
            ziyaret: ['it', 'qa', 'analist'].map((k) => inside('mudurluk-' + k + '-ziyaret')),
            qa: Object.values(p.dugumler).filter((x) => x.oda === 'qa' && x.tur === 'masa').map((x) => x.id),
            analist: Object.values(p.dugumler).filter((x) => x.oda === 'analist' && x.tur === 'masa').map((x) => x.id),
            qaYer: inside(d.QA_MUDUR_YERI), gm: p.dugumler[d.GM_KAPI_YERI] && p.dugumler[d.GM_KAPI_YERI].oda,
            guvenlik: inside(d.denetciMasasi('guvenlik')),
            denetciOdasi: Object.values(p.dugumler).filter((x) => x.oda === 'denetci' && x.tur === 'masa').map((x) => x.id),
            mudur: room(p, 'mudur').ad }}; }})""")
        first = out[0]
        self.assertEqual([r[:3] for r in first["rooms"]], [
            ["mudurluk-yazilim", "mudurluk", "Yazılım Müdürü odası"], ["mudurluk-it", "mudurluk", "IT Müdürü odası"],
            ["mudurluk-qa", "mudurluk", "QA Müdürü odası"], ["mudurluk-analist", "mudurluk", "Analist Müdürü odası"],
            ["qa", "qa", "QA odası"], ["analist", "analist", "Analist odası"]])
        for n, o in zip(COUNTS, out):
            with self.subTest(projects=n):
                self.assertEqual(o["rooms"], first["rooms"])  # fixed: never move when projects are added
        o = first
        self.assertEqual(o["desks"], [[k, "mudur-masasi", f"mudurluk-{k}", f"mudurluk-{k}"] for k in ("yazilim", "it", "qa", "analist")])
        self.assertEqual(o["plan"], ["mudurluk-yazilim", "masa", True])  # the planning desk with its helper spots
        self.assertEqual(o["ziyaret"], ["mudurluk-it", "mudurluk-qa", "mudurluk-analist"])
        self.assertEqual(o["qa"], [f"qa-masa-{i}" for i in range(4)])
        self.assertEqual(o["analist"], [f"analist-masa-{i}" for i in range(4)])
        self.assertEqual((o["qaYer"], o["gm"], o["guvenlik"]), ("qa", "ceo", "sunucu"))
        self.assertEqual(o["denetciOdasi"], ["denetci-masa", "denetci-masa-glm"])  # no security desk in the auditors' room
        self.assertEqual(o["mudur"], "Genel Müdür odası")

    def test_the_labels_name_the_new_rooms(self):
        out = run_js("h.odaEtiketleri(d.ofisPlani(['vitrin'])).map((r) => r.ad)")
        for ad in ("Yazılım Müdürü odası", "IT Müdürü odası", "QA Müdürü odası", "Analist Müdürü odası", "QA odası",
                   "Analist odası", "Genel Müdür odası"):
            self.assertIn(ad, out)

    def test_a_haiku_review_takes_a_stajyer_tester_desk_and_the_labels_say_the_role(self):
        out = run_js("""(() => { const s = st({ sessions: [ses('r1', 'busy', {note: 'a.md', step_kind: 'kod-inceleme', model: 'claude-haiku-4-5'}),
              ses('r2', 'busy', {note: 'b.md', step_kind: 'kod-inceleme'}), ses('r3', 'busy', {note: 'c.md', step_kind: 'plan-inceleme'})],
            tasks: [task('a.md', 'calisiyor', {session: 'r1', step_kind: 'kod-inceleme', tier: 'inceleme', model: 'haiku'}),
              task('b.md', 'calisiyor', {session: 'r2', step_kind: 'kod-inceleme', tier: 'inceleme', model: 'opus'}),
              task('c.md', 'calisiyor', {session: 'r3', step_kind: 'plan-inceleme', tier: 'inceleme', model: 'opus'})] });
          const r = run(s); const pick = (id) => { const a = one(r, id); return [a.yer, h.rolAdi(a.etiket)]; };
          return [pick('is:a'), pick('is:b'), pick('is:c')]; })()""")
        self.assertEqual(out, [["qa-masa-2", "vitrin · Stajyer Tester"], ["qa-masa-0", "vitrin · Kıdemli Tester"],
                               ["analist-masa-0", "vitrin · İş analisti · Kıdemli"]])

    def test_the_plan_is_written_in_the_yazilim_office_by_the_genel_mudur(self):
        out = run_js("""(() => { const s = (model) => st({ sessions: [ses('p1', 'busy', {note: 'p.md', tier: 'planlama', step_kind: 'plan'})],
            tasks: [task('p.md', 'calisiyor', {session: 'p1', tier: 'planlama', step_kind: 'plan', model})],
            modeller: [{model: 'fable', durum: 'calisiyor', calisan: 1}] });
          const f = run(s('fable')), o = run(s('opus'));
          const pick = (r) => { const a = one(r, 'is:p'); return [a.yer, a.masa, h.rolAdi(a.etiket), a.unvan]; };
          return { f: pick(f), o: pick(o), gm: d.UNVAN.fable.unvan }; })()""")
        self.assertEqual(out["gm"], "Genel Müdür")
        self.assertEqual(out["f"], ["yazilim-plan-masa", "yazilim-plan-masa", "vitrin · Genel Müdür (Yazılım Müdürü adına)", "Genel Müdür"])
        self.assertEqual(out["o"], ["yazilim-plan-masa", "yazilim-plan-masa", "vitrin · Kıdemli (Yazılım Müdürü adına)", "Kıdemli"])

    def test_other_fable_work_keeps_the_genel_mudur_office(self):
        out = run_js("""(() => { const r = run(st({ sessions: [ses('k1', 'busy', {note: 'k.md', tier: 'kod'})],
            tasks: [task('k.md', 'calisiyor', {session: 'k1', tier: 'kod', model: 'fable'})] }));
          return one(r, 'is:k').masa; })()""")
        self.assertEqual(out, "mudur-odasi-masa")


@unittest.skipUnless(NODE, "node is not installed")
class DemoWingTest(unittest.TestCase):
    def test_the_demo_shows_several_bays_reserved_bays_and_review_work_in_the_uzmanlar_room(self):
        out = run_js("""(() => { const x0 = demo.demoDurumu(0, NOW);
          const projs = ['vitrin', 'atolye', 'blog', 'kasa'].map((name) => ({ name }));
          const P = d.ofisPlani(projs, { max_running_per_project: 1, denetciler: d.denetciListesi(x0.modeller) });
          let prev = null; const seen = new Set(); const meeting = new Set();
          for (let t = 0; t < demo.DEMO_SURE; t++) { const now = NOW + t * 1000; const x = demo.demoDurumu(t, now);
            const s = { projects: projs, tasks: x.tasks, board: x.tasks, decisions: x.decisions, modeller: x.modeller,
              denetim: x.denetim, sahne: x.sahne, ceo: { state: 'idle' }, sessions: demo.demoOturumlari(x.live, x.tasks, now) };
            prev = d.niyetler(s, now, prev, { plan: P, max_running_per_project: 1 });
            for (const a of prev) { if (/^(uzmanlar|qa)-masa-/.test(a.yer || '')) seen.add(a.id);
              if (/^toplanti-/.test(a.yer || '')) meeting.add(a.id); } }
          const captions = demo.DEMO_SAHNELERI.filter((x) => x.id === 'inceleme' || x.id === 'hakem').map((x) => x.metin);
          const g = d.kanatIzgarasi(4, { max_running_per_project: 1, denetciler: d.denetciListesi(x0.modeller) });
          return { bays: P.odalar.filter((r) => r.tur === 'ekip').length, bos: P.kanat.yedek, sutun: P.kanat.sutun,
            grid: [g.yedek, g.sutun], seen: [...seen].sort(), meeting: [...meeting], captions }; })()""")
        self.assertEqual(out["bays"], 4)
        self.assertGreaterEqual(out["bos"], 1)  # several bays and reserved bays
        self.assertEqual([out["bos"], out["sutun"]], out["grid"])
        self.assertIn("hakem", out["seen"])
        self.assertIn("is:r", out["seen"])  # the Claude review of the demo
        self.assertEqual(out["meeting"], [])
        # plan "Sonraki iş (9)": the Claude review in the QA odası, the hakem in the Uzmanlar odası
        self.assertIn("QA odasında", out["captions"][0])
        self.assertIn("Uzmanlar odasında", out["captions"][1])


@unittest.skipUnless(NODE, "node is not installed")
class ZoomHelpersTest(unittest.TestCase):
    def test_a_step_in_or_out_is_clamped_to_the_cameras_limits(self):
        out = run_js("""[h.sonrakiZoom(1, 1, 0.6, 3.2), h.sonrakiZoom(1, -1, 0.6, 3.2), h.sonrakiZoom(3, 1, 0.6, 3.2),
          h.sonrakiZoom(0.65, -1, 0.6, 3.2), h.sonrakiZoom(2, 0, 0.6, 3.2), h.sonrakiZoom(NaN, 1, 0.6, 3.2), h.ZOOM_ADIMI]""")
        step = out[6]
        self.assertGreater(step, 1.1)
        self.assertAlmostEqual(out[0], step)
        self.assertAlmostEqual(out[1], 1 / step)
        self.assertEqual(out[2], 3.2)
        self.assertEqual(out[3], 0.6)
        self.assertEqual(out[4], 2)
        self.assertAlmostEqual(out[5], step)  # an unreadable zoom counts as 1

    def test_keys_plus_minus_zero_but_never_while_typing_or_with_modifiers(self):
        out = run_js("""[['+', {}], ['=', {}], ['-', {}], ['−', {}], ['0', {}], ['a', {}], ['+', {ctrlKey: true}],
          ['-', {metaKey: true}], ['0', {altKey: true}], ['+', {target: {tagName: 'input'}}],
          ['-', {target: {tagName: 'TEXTAREA'}}], ['0', {target: {tagName: 'SELECT'}}],
          ['+', {target: {tagName: 'DIV', isContentEditable: true}}], ['+', {target: {tagName: 'BUTTON'}}]]
          .map(([key, x]) => h.zoomTusu({key, ...x})).concat([h.zoomTusu(null)])""")
        self.assertEqual(out, ["yakin", "yakin", "uzak", "uzak", "tumu", None, None, None, None, None, None, None, None,
                               "yakin", None])


class ZoomWiringTest(unittest.TestCase):
    def test_the_buttons_are_labelled_focusable_and_in_the_hud_layer(self):
        page = (WEB / "index.html").read_text(encoding="utf-8")
        group = re.search(r'<div class="zoom-kontrol" id="zoom-kontrol"[^>]*>(.*?)</div>', page, re.S)
        self.assertIsNotNone(group)
        buttons = re.findall(r'<button class="zoom-btn" id="([a-z-]+)" type="button" aria-label="([^"]+)"[^>]*>([^<]+)</button>',
                             group.group(1))
        self.assertEqual(buttons, [("zoom-yakin", "Yakınlaştır", "+"), ("zoom-uzak", "Uzaklaştır", "−"),
                                   ("zoom-sola", "Sola döndür", "↺"), ("zoom-saga", "Sağa döndür", "↻"),
                                   ("zoom-tumu", "Tümünü göster", "⟲")])
        css = (WEB / "style.css").read_text(encoding="utf-8")
        block = css[css.index(".zoom-kontrol {"):css.index("}", css.index(".zoom-kontrol {"))]
        self.assertIn("z-index: var(--z-hud)", block)  # below the tab panels (--z-overlay) and popovers
        # The owner, 2026-11-13: the scene's bottom-LEFT corner with a 16px gutter (bottom-right felt too central)
        self.assertIn("left: var(--s2); bottom: var(--s2);", block)
        self.assertNotIn("right:", block)
        self.assertIn("--s2: 16px;", css)
        self.assertIn("body.panel-acik .zoom-kontrol { visibility: hidden; }", css)
        self.assertRegex(css, r"@media \(max-width: 820px\) \{[^}]*\.zoom-kontrol \{ left: var\(--s2\); bottom: auto;")
        self.assertRegex(css, r"@media \(max-width: 600px\) \{[^}]*\.zoom-kontrol \{ top: calc\(56px \+ min\(56vh, 100vw\)")

    def test_the_caption_the_hint_and_the_off_hours_line_never_sit_on_the_controls(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        def block(sel):
            i = css.index("\n" + sel + " {")
            return css[i:css.index("}", i)]
        # the demo caption and the hint start right of the 38px-wide group (+ a gap); the hint goes above the caption
        self.assertIn("left: calc(var(--s2) + 38px + var(--s2)); bottom: var(--s2);", block(".demo-caption"))
        self.assertIn("max-width: calc(50% - var(--side-w) / 2", block(".demo-caption"))  # the left half only
        self.assertIn("left: calc(var(--s2) + 38px + var(--s1)); bottom: var(--s2);", block(".kaydir-ipucu"))
        self.assertIn(".stage:has(.demo-caption:not([hidden])) .kaydir-ipucu { bottom: calc(var(--s2) + 40px + var(--s1)); }", css)
        # "Mesai dışı" takes the bottom-right corner, within the right half (never under the caption)
        m = block(".mesai-disi")
        self.assertIn("right: calc(var(--side-w) + var(--s3) + var(--s2)); bottom: var(--s2);", m)
        self.assertIn("max-width: calc(50% - var(--side-w) / 2 - 2 * var(--s3))", m)
        self.assertRegex(css, r"@media \(max-width: 820px\) \{[^}]*\.mesai-disi \{ right: var\(--s2\); bottom: auto; "
                              r"max-width: calc\(100% - 3 \* var\(--s2\) - 44px\)")

    def test_the_page_and_the_scene_wire_the_zoom(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for text in ("office.yakinlastir(1)", "office.yakinlastir(-1)", "office.tumunuGoster()",
                     "office.dondur(-1)", "office.dondur(1)", "$('zoom-sola').addEventListener('click'",
                     "$('zoom-saga').addEventListener('click'", "const don = donusTusu(e);",
                     "const ne = zoomTusu(e) || (don ? (don < 0 ? 'sola' : 'saga') : null);",
                     "document.body.classList.contains('panel-acik')",
                     "$('zoom-kontrol').hidden = true;"):
            self.assertIn(text, app)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        body = scene[scene.index("  yakinlastir(yon) {"):scene.index("  clampTarget() {")]
        for text in ("sonrakiZoom(", "this.controls.minZoom, this.controls.maxZoom", "this.userMoved = true;",
                     "this.focusAnim = { from: t, to: t.clone()", "this.userMoved = false;", "this.fit();"):
            self.assertIn(text, body)
        self.assertIn("if (r.tur === 'bos-ekip') { this.buildReservedBay(r, g); return; }", scene)
        self.assertIn("r.tur === 'uzmanlar'", scene)


# --- idle life: the Oyun odası, a bigger tea corner and lounge, idle routines (owner decision 2026-11-12) ---

IDLE = r"""
const KADRO = (durum = 'hazir') => ['haiku', 'sonnet', 'opus', 'fable'].map((m) => ({ model: m, durum }));
const idle = (x = {}) => st({ modeller: KADRO(), ...x });
const byId = (list) => Object.fromEntries(list.map((a) => [a.id, a]));
const SEG = d.MOLA_ADIM_MS;
"""


def run_idle(expr):
    return run_js(f"(() => {{ {IDLE}\n return ({expr}); }})()")


@unittest.skipUnless(NODE, "node is not installed")
class GameRoomPlanTest(unittest.TestCase):
    def test_the_game_room_is_in_the_middle_row_left_of_the_uzmanlar_room_for_any_number_of_projects(self):
        for n in range(0, 9):
            with self.subTest(projects=n):
                out = run_js(f"""(() => {{ const p = d.ofisPlani(names({n}), {{ max_running_per_project: 3 }});
                  const o = room(p, 'oyun'), u = room(p, 'uzmanlar'), c = room(p, 'cay-ocagi'), t = room(p, 'toplanti');
                  const spots = Object.values(p.dugumler).filter((x) => x.oda === 'oyun');
                  const inside = spots.filter((x) => x.tur !== 'kapi').every((x) => x.x > o.x && x.x < o.x + o.w && x.z > o.z && x.z < o.z + o.d);
                  const bad = spots.filter((x) => {{ const w = p.yol('asansor', x.id); return !w.length || w[w.length - 1].id !== x.id; }});
                  return {{ o: [o.tur, o.ad, o.x, o.z, o.w, o.d], left: o.x + o.w < u.x, gapU: +(u.x - o.x - o.w).toFixed(2),
                    sameRow: o.z === u.z, behindTea: o.z + o.d < c.z, belowMeeting: o.z > t.z + t.d, inside,
                    ids: spots.map((x) => x.id).sort(), bad: bad.map((x) => x.id), oyun: p.oyun }}; }})()""")
                self.assertEqual(out["o"][:2], ["oyun", "Oyun odası"])
                self.assertTrue(out["left"] and out["sameRow"] and out["behindTea"] and out["belowMeeting"], out)
                self.assertGreaterEqual(out["gapU"], 1.9)
                self.assertTrue(out["inside"])
                for spot in ("oyun-pingpong-0", "oyun-pingpong-1", "oyun-bilardo-0", "oyun-bilardo-1", "oyun-dart",
                             "oyun-puf", "oyun-ozet"):
                    self.assertIn(spot, out["ids"])
                self.assertEqual(out["bad"], [])
                self.assertEqual(sorted(out["oyun"]), ["bilardo", "dart", "pingpong"])

    def test_the_ping_pong_players_face_each_other_across_the_table(self):
        out = run_js("""(() => { const p = d.ofisPlani(['vitrin']); const n = p.dugumler;
          const a = n['oyun-pingpong-0'], b = n['oyun-pingpong-1'], [tx, tz] = p.oyun.pingpong;
          const fa = h.yuzAcisi(p, a.id), fb = h.yuzAcisi(p, b.id);
          return { across: Math.sign(a.x - tx) === -Math.sign(b.x - tx), dz: Math.abs(a.z - b.z),
            facing: +Math.abs(Math.abs(fa - fb) - Math.PI).toFixed(6), toTable: +Math.abs(Math.atan2(tx - a.x, tz - a.z) - fa).toFixed(6),
            bilardo: h.yuzAcisi(p, 'oyun-bilardo-0') !== null, puf: h.oturmaYeri(p, 'oyun-puf') }; })()""")
        self.assertEqual(out, {"across": True, "dz": 0, "facing": 0, "toTable": 0, "bilardo": True, "puf": True})

    def test_the_tea_corner_and_the_lounge_are_bigger(self):
        out = run_js("""(() => { const p = d.ofisPlani(['vitrin']); const n = p.dugumler;
          const ids = (re) => Object.keys(n).filter((id) => re.test(id)).sort();
          const tea = room(p, 'cay-ocagi'), lounge = room(p, 'ortak-alan');
          const inside = (x, r) => x.x > r.x && x.x < r.x + r.w && x.z > r.z && x.z < r.z + r.d;
          const seats = ids(/^ortak-alan-yer-\\d$/).map((id) => n[id]);
          return { stools: ids(/^cay-ocagi-yer-\\d$/).length, tables: p.cay_masalari.length,
            counter: ids(/^cay-ocagi-tezgah-yer-\\d$/).map((id) => [n[id].tur, inside(n[id], tea)]),
            lounge: seats.map((x) => [inside(x, lounge), h.oturmaYeri(p, x.id), h.yuzAcisi(p, x.id) !== null]),
            kafe: p.kafe_masalari.length, w: [tea.w, lounge.w],
            labels: h.odaEtiketleri(p).filter((r) => r.id === 'oyun').map((r) => r.ad) }; })()""")
        self.assertEqual(out["stools"], 9)
        self.assertEqual(out["tables"], 3)
        self.assertEqual(out["counter"], [["ayakta", True], ["ayakta", True]])
        self.assertEqual(len(out["lounge"]), 4)
        self.assertTrue(all(all(x) for x in out["lounge"]))
        self.assertEqual(out["kafe"], 2)
        self.assertGreater(out["w"][0], 9 * 1.3)
        self.assertGreater(out["w"][1], 10 * 1.3)
        self.assertEqual(out["labels"], ["Oyun odası"])


@unittest.skipUnless(NODE, "node is not installed")
class IdleLifeTest(unittest.TestCase):
    def test_the_schedule_is_deterministic_and_cycles_through_every_activity(self):
        out = run_idle("""(() => { const seen = {}; for (let i = 0; i < 400; i++) {
            const e = d.molaEtkinligi('kadro:opus', NOW + i * SEG); seen[e] = (seen[e] || 0) + 1; }
          return { seen: Object.keys(seen).sort(), same: d.molaEtkinligi('kadro:opus', NOW) === d.molaEtkinligi('kadro:opus', NOW + 1000),
            forced: d.molaEtkinligi('kadro:opus', NOW, 'oyun'), bogus: d.MOLA_ETKINLIKLERI.includes(d.molaEtkinligi('x', NOW, 'zzz')),
            rest: seen.dinlenme }; })()""")
        # by day in the office hours no nap (owner decision 2026-11-16); the lunch window keeps it (below)
        self.assertEqual(out["seen"], ["cay", "dinlenme", "masaj", "oyun", "sigara", "spor", "wc", "yuruyus"])
        self.assertTrue(out["same"])
        self.assertEqual(out["forced"], "oyun")
        self.assertTrue(out["bogus"])
        self.assertGreater(out["rest"], 100)  # resting at the seat stays the most common

    def test_no_nap_in_the_office_hours_except_the_lunch_window(self):
        out = run_idle("""(() => { const gun = {}, ogle = {}, ceo = {}, ceoOgle = {};
          for (let i = 0; i < 600; i++) {
            const t = NOW + i * SEG;
            for (const id of ['kadro:haiku', 'ceo', 'denetci:glm']) {
              const a = d.molaEtkinligi(id, t); gun[a] = (gun[a] || 0) + 1;
              const b = d.molaEtkinligi(id, t, '', { ogle: true }); ogle[b] = (ogle[b] || 0) + 1;
            }
            const c = d.ceoPlani(i * d.CEO_ADIM_MS, null, { uyuyabilir: true }).tur; ceo[c] = (ceo[c] || 0) + 1;
            const e = d.ceoPlani(i * d.CEO_ADIM_MS, null, { uyuyabilir: true, ogle: true }).tur; ceoOgle[e] = (ceoOgle[e] || 0) + 1;
          }
          return { gun, ogle, ceo, ceoOgle }; })()""")
        self.assertNotIn("uyku", out["gun"])
        self.assertIn("uyku", out["ogle"])
        self.assertNotIn("uyku", out["ceo"])  # a dormant CEO takes a break instead
        self.assertGreater(out["ceo"]["mola"], 0)
        self.assertIn("uyku", out["ceoOgle"])

    def test_tea_first_at_the_counter_then_with_the_cup_at_a_lounge_table(self):
        out = run_idle("""(() => { const s = idle({ sahne: { ...st().sahne, mola: 'cay' } });
          const pick = (a) => [a.yer, a.poz, a.durum_metni];
          const K4 = ['kadro:fable', 'kadro:haiku', 'kadro:sonnet', 'kadro:opus']; // the Müdür too (2026-11-12)
          // each actor's own slot (molaDilimi: its own seeded phase)
          const bas = (id) => NOW - d.molaDilimi(id, NOW).gecen + SEG;
          const at = (id, o) => byId(run(s, bas(id) + o));
          return { early: K4.map((id) => pick(at(id, 5000)[id])), late: K4.map((id) => pick(at(id, 40000)[id])),
            most: Math.max(...K4.map((id) => Object.values(at(id, 5000)).filter((a) => /^cay-ocagi-tezgah-yer-/.test(a.yer || '')).length)) }; })()""")
        counter = [a for a in out["early"] if a[0].startswith("cay-ocagi-tezgah-yer-")]
        self.assertGreaterEqual(len(counter), 2)  # at its own slot's start each one fetches its drink
        self.assertLessEqual(out["most"], 2)  # two places at the counter; the others wait at their seat
        for a in counter:
            self.assertEqual(a[1], "cay-al")
            self.assertRegex(a[2], r"^(çay|kahve) alıyor$")
        for a in out["late"]:
            self.assertTrue(a[0].startswith("ortak-alan-yer-"), a)
            self.assertEqual(a[1], "cay")  # carries / drinks from its cup
            self.assertRegex(a[2], r"^(çay|kahve) içiyor · ortak alan$")

    def test_two_idle_actors_play_ping_pong_the_next_two_billiards_and_one_alone_throws_darts(self):
        out = run_idle("""(() => { const s = idle({ sahne: { ...st().sahne, mola: 'oyun' },
            sessions: ['x', 'y', 'z'].map((n) => ses(`ofis-${n}-bos`, 'idle', { model: 'sonnet' })) });
          const r = run(s); return r.filter((a) => (a.yer || '').startsWith('oyun-') && !a.denetci && a.tur !== 'sus').map((a) => [a.id, a.yer, a.poz, a.durum_metni])
            .sort((a, b) => (a[1] < b[1] ? -1 : 1)); })()""")
        by = {a[1]: a for a in out}
        self.assertEqual({by["oyun-pingpong-0"][2], by["oyun-pingpong-1"][2]}, {"pingpong"})
        self.assertEqual(by["oyun-pingpong-0"][3], "masa tenisi oynuyor")
        self.assertEqual((by["oyun-bilardo-0"][2], by["oyun-bilardo-1"][2]), ("bilardo", "bekliyor"))
        self.assertEqual(by["oyun-bilardo-1"][3], "bilardo oynuyor")
        self.assertEqual((by["oyun-dart"][2], by["oyun-dart"][3]), ("dart", "dart atıyor"))
        self.assertEqual(len(out), 6)  # (an idle auditor comes after the office's own staff; the Müdür plays too)
        # (Codex at home: an idle auditor would be a partner)
        one_alone = run_idle("""(() => { const s = st({ modeller: [{ model: 'opus', durum: 'hazir' }, { model: 'codex', durum: 'kota' }],
            sahne: { ...st().sahne, mola: 'oyun' } }); const a = one(run(s), 'kadro:opus'); return [a.yer, a.poz]; })()""")
        self.assertEqual(one_alone, ["oyun-dart", "dart"])  # no ping-pong without a partner

    def test_real_state_first_busy_waiting_kontrol_quota_and_lunch_never_play(self):
        out = run_idle("""(() => { const LUNCH = Date.parse('2026-11-11T09:30:00Z');
          const m = { sahne: { ...st().sahne, mola: 'oyun' } };
          const busy = run(st({ ...m, modeller: [{ model: 'opus', durum: 'calisiyor' }],
            sessions: [ses('w', 'busy', { note: 'a.md', model: 'opus' }), ses('q', 'waiting', { note: 'b.md' })],
            tasks: [task('a.md', 'calisiyor', { session: 'w' }), task('b.md', 'calisiyor', { session: 'q' }),
              task('k.md', 'kontrolde', { session: '' })] }));
          const quota = one(run(st({ ...m, modeller: [{ model: 'opus', durum: 'kota' }, { model: 'haiku', durum: 'hazir' }] })), 'kadro:opus');
          const lunch = run(idle(m), LUNCH).filter((a) => a.kadro && a.model !== 'fable')
            .map((a) => [a.poz === 'yemek', d.ogleYemekte(a.id, LUNCH, st().sahne), (a.yer || '').startsWith('oyun-') && a.poz === 'yemek']);
          const light = run(idle(m), NOW, null, { hafif: true }).filter((a) => a.kadro).map((a) => a.yer);
          return { busy: busy.filter((a) => /^is:/.test(a.id)).map((a) => [a.id, (a.yer || '').startsWith('oyun-') || /cay-ocagi|ortak-alan-yer/.test(a.yer || '')]),
            quota: [quota.yer, quota.poz], lunch, light }; })()""")
        self.assertTrue(all(not x[1] for x in out["busy"]), out["busy"])
        self.assertEqual(out["quota"], ["ortak-alan-opus", "evde"])
        for eats, should, both in out["lunch"]:  # an eater eats (never plays at the same time); the others may play
            self.assertEqual(eats, should)
            self.assertFalse(both)
        self.assertEqual(out["light"], ["ortak-alan-haiku", "ortak-alan-sonnet", "ortak-alan-opus", "mudur-odasi-masa"])
        fable = run_idle("""one(run(idle({ sahne: { ...st().sahne, mola: 'oyun' } })), 'kadro:fable').yer""")
        self.assertTrue(fable.startswith("oyun-"), fable)  # the idle Müdür takes the breaks too (owner decision 2026-11-12)

    def test_over_a_day_idle_actors_spread_over_the_rooms_and_never_share_a_game_spot(self):
        out = run_idle("""(() => { const s = idle({ sessions: [ses('ofis-x-bos', 'idle', { model: 'sonnet' })] });
          const places = new Set(); let clash = 0;
          for (let i = 0; i < 300; i++) { const r = run(s, NOW + i * 20000);
            const spots = r.filter((a) => (a.yer || '').startsWith('oyun-') || (a.yer || '').startsWith('ortak-alan-yer-') ||
              (a.yer || '').startsWith('cay-ocagi-tezgah-yer-')).map((a) => a.yer);
            if (new Set(spots).size !== spots.length) clash++;
            for (const a of r) if (a.kadro || a.id === 'oturum:ofis-x-bos') places.add((a.yer || '').replace(/-\\d+$|-(haiku|sonnet|opus|fable)$/, ''));
          } return { places: [...places].sort(), clash }; })()""")
        self.assertEqual(out["clash"], 0)
        for p in ("cay-ocagi-tezgah-yer", "ortak-alan-yer", "ortak-alan", "oyun-pingpong", "cay-ocagi-yer"):
            self.assertIn(p, out["places"])

    def test_idle_labels_read_in_plain_turkish_on_hover(self):
        out = run_js("""['çay alıyor', 'kahve içiyor · ortak alan', 'masa tenisi oynuyor', 'bilardo oynuyor']
          .map((x, i) => h.etiketBilgisi({ id: 'k', tur: 'ajan', etiket: 'Kıdemli (Opus)', durum_metni: x,
            poz: ['cay-al', 'cay', 'pingpong', 'bilardo'][i] }, { yakin: false, uzerinde: true }).durum)""")
        self.assertEqual(out, ["çay alıyor", "kahve içiyor · ortak alan", "masa tenisi oynuyor", "bilardo oynuyor"])

    def test_the_demo_shows_idle_actors_playing_ping_pong(self):
        out = run_js("""(() => { const x0 = demo.demoDurumu(0, NOW);
          const projs = ['vitrin', 'atolye', 'blog', 'kasa'].map((name) => ({ name }));
          const P = d.ofisPlani(projs, { max_running_per_project: 1, denetciler: d.denetciListesi(x0.modeller) });
          const sc = demo.DEMO_SAHNELERI.find((x) => x.id === 'mola');
          const t = sc.bas + 3; const now = NOW + t * 1000; const x = demo.demoDurumu(t, now);
          const s = { projects: projs, tasks: x.tasks, board: x.tasks, decisions: x.decisions, modeller: x.modeller,
            denetim: x.denetim, sahne: x.sahne, ceo: { state: 'idle' }, sessions: demo.demoOturumlari(x.live, x.tasks, now) };
          const r = d.niyetler(s, now, null, { plan: P, max_running_per_project: 1 });
          return { caption: sc.metin, ping: r.filter((a) => a.poz === 'pingpong').length,
            working: r.filter((a) => a.poz === 'yaziyor').every((a) => !(a.yer || '').startsWith('oyun-')) }; })()""")
        self.assertIn("masa tenisi", out["caption"])
        self.assertEqual(out["ping"], 2)
        self.assertTrue(out["working"])

    def test_the_scene_draws_the_game_room_and_the_new_poses_cheaply(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        for text in ("r.tur === 'oyun'", "makePingPongTable(", "makeBilliardTable(", "makeDartBoard(", "makeBeanBag(",
                     "makeCoffeeMachine(", "poz === 'pingpong'", "poz === 'bilardo'", "poz === 'dart'",
                     "poz === 'cay-al'", "this.top"):
            self.assertIn(text, scene)
        # the ball and the swings never run in hafif
        self.assertRegex(scene, r"if \(this\.top && !this\.light\)")


# An announcement (state.duyuru, bin/duyuru.py son) delivered 10 s before NOW (10:00 Istanbul, not lunch).
HALL = r"""
const DUY = (x = {}) => ({ duyuru: { id: '20261111-095950-ab12', ilk_satir: 'Cuma günü deploy yok', zaman: iso(NOW - 10000),
  sayi: 1, hedef: 1, alanlar: ['ofis-vitrin-w'], ...x } });
const MODELS = [{ model: 'haiku', durum: 'hazir' }, { model: 'sonnet', durum: 'hazir' }, { model: 'opus', durum: 'hazir' },
  { model: 'fable', durum: 'hazir' }, { model: 'codex', durum: 'hazir' }];
const busyState = (x = {}) => st({ modeller: MODELS, ceo: { state: 'idle', queue: 0 },
  sessions: [ses('ofis-vitrin-w', 'busy', { note: 'a.md', model: 'opus', job_status: 'calisiyor' })],
  tasks: [task('a.md', 'calisiyor', { session: 'ofis-vitrin-w' })], ...x });
const inHall = (list) => list.filter((a) => /^konferans-/.test(a.yer || '')).map((a) => a.id).sort();
"""


@unittest.skipUnless(NODE, "node is not installed")
class ConferenceHallTest(unittest.TestCase):
    def js(self, expr):
        return run_js(f"(() => {{ {HALL}\n return {expr}; }})()")

    def test_the_hall_is_a_fixed_facility_with_a_lectern_chairs_and_a_screen_and_never_moves(self):
        out = run_js(f"""{list(COUNTS)}.map((n) => {{ const p = d.ofisPlani(names(n));
          const r = room(p, 'konferans'); const nodes = Object.values(p.dugumler).filter((x) => x.oda === 'konferans');
          const chairs = nodes.filter((x) => x.tur === 'sandalye');
          const inside = (x) => x.x > r.x && x.x < r.x + r.w && x.z > r.z && x.z < r.z + r.d;
          const reach = chairs.concat([p.dugumler[d.SALON_KURSU]]).every((x) => {{ const w = p.yol('asansor', x.id); return w.length && w[w.length - 1].id === x.id; }});
          return {{ r: [r.id, r.tur, r.ad, r.x, r.z, r.w, r.d], salon: r.salon, chairs: chairs.length, inside: nodes.filter((x) => x.tur !== 'kapi').every(inside),
            kursu: p.dugumler[d.SALON_KURSU].tur, reach, face: [h.yuzAcisi(p, chairs[0].id), h.yuzAcisi(p, d.SALON_KURSU)],
            sits: h.oturmaYeri(p, chairs[0].id), revir: room(p, 'revir'), lobi: room(p, 'lobi'), W: p.genislik, D: p.derinlik }}; }})""")
        first = out[0]
        for n, o in zip(COUNTS, out):
            with self.subTest(projects=n):
                self.assertEqual(o["r"], first["r"])  # fixed: never moves when projects are added
                self.assertEqual(o["r"][:3], ["konferans", "konferans", "Konferans salonu"])
                self.assertEqual(o["chairs"], 18)
                self.assertTrue(o["inside"] and o["reach"])
                self.assertEqual(o["kursu"], "kursu")
                self.assertAlmostEqual(o["face"][0], 3.141592653589793)  # the audience faces the screen
                self.assertEqual(o["face"][1], 0)  # the lectern faces the audience
                self.assertTrue(o["sits"])
                self.assertEqual(len(o["salon"]["ekran"]), 2)
                # under the Revir, inside the common area's width; the lobby stays in the floor's front-right corner
                self.assertGreater(o["r"][4], o["revir"]["z"] + o["revir"]["d"])
                self.assertAlmostEqual(o["lobi"]["x"] + o["lobi"]["w"], o["W"], places=6)
                self.assertAlmostEqual(o["lobi"]["z"] + o["lobi"]["d"], o["D"], places=6)

    def test_idle_staff_gather_the_ceo_takes_the_lectern_and_working_agents_stay(self):
        out = self.js("""(() => { const list = run({ ...busyState(), ...DUY() });
          const w = one(list, 'is:a');
          return { hall: inHall(list), ceo: [one(list, 'ceo').yer, one(list, 'ceo').durum_metni],
            w: [w.yer, w.durum_metni, !!w.duyuru_alindi], kadro: list.filter((a) => a.kadro).map((a) => a.yer.startsWith('konferans-sandalye-')),
            distinct: new Set(list.filter((a) => /^konferans-/.test(a.yer || '')).map((a) => a.yer)).size,
            screen: d.salonEkrani({ ...busyState(), ...DUY() }, NOW) }; })()""")
        self.assertEqual(out["ceo"], ["konferans-kursu", "duyuruyu okuyor"])
        self.assertEqual(out["w"][0], "ekip-vitrin-masa-1")  # the working agent never leaves its desk …
        self.assertTrue(out["w"][1].endswith("· duyuru alındı") and out["w"][2])  # … and shows the mark
        self.assertEqual(out["kadro"], [True, True, True])  # opus works: haiku, sonnet, fable listen
        self.assertIn("denetci:codex", out["hall"])
        self.assertTrue(any(i.startswith("sus:") for i in out["hall"]))
        self.assertNotIn("is:a", out["hall"])
        self.assertEqual(out["distinct"], len(out["hall"]))  # one actor per chair (the CEO on the lectern)
        self.assertEqual(out["screen"], "Cuma günü deploy yok")

    def test_a_busy_ceo_stays_and_the_gathering_ends_after_a_minute(self):
        out = self.js("""(() => {
          const busy = run({ ...busyState({ ceo: { state: 'busy', queue: 0 } }), ...DUY() });
          const later = run({ ...busyState(), ...DUY() }, NOW + d.DUYURU_MS + d.DUYURU_TOPLANMA_MS);
          const before = run({ ...busyState(), ...DUY({ zaman: iso(NOW + 60000) }) });
          return { ceo: one(busy, 'ceo').yer, later: inHall(later), before: inHall(before),
            mark: one(later, 'is:a').durum_metni.includes('duyuru alındı'),
            screen: d.salonEkrani({ ...busyState(), ...DUY() }, NOW + d.DUYURU_MS + d.DUYURU_TOPLANMA_MS), none: d.salonEkrani(st(), NOW) }; })()""")
        self.assertEqual(out["ceo"], "ceo-masa")
        self.assertEqual(out["later"], [])
        self.assertEqual(out["before"], [])
        self.assertFalse(out["mark"])
        self.assertEqual((out["screen"], out["none"]), ("", ""))

    def test_a_session_the_announcement_did_not_reach_gets_no_mark(self):
        out = self.js("""one(run({ ...busyState(), ...DUY({ alanlar: [] }) }), 'is:a').durum_metni""")
        self.assertNotIn("duyuru alındı", out)

    def test_hafif_shows_only_the_screen_text(self):
        out = self.js("""(() => { const s = { ...busyState(), ...DUY() };
          const list = run(s, NOW, null, { hafif: true });
          return { hall: inHall(list), ceo: one(list, 'ceo').yer, mark: one(list, 'is:a').durum_metni.includes('duyuru'),
            screen: d.salonEkrani(s, NOW) }; })()""")
        self.assertEqual(out["hall"], [])
        self.assertNotEqual(out["ceo"], "konferans-kursu")
        self.assertFalse(out["mark"])
        self.assertEqual(out["screen"], "Cuma günü deploy yok")

    def test_the_scene_draws_the_hall_screen_and_the_name_sign_with_canvas_text_only(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("r.tur === 'konferans'", scene)
        self.assertIn("setDuyuru(", scene)
        self.assertIn("setOfisAdi(", scene)
        self.assertNotIn("brand/", scene)  # no logo files: the office's name is drawn as text
        self.assertNotIn("new Image(", scene)
        body = scene.split("setDuyuru(", 1)[1]
        self.assertNotIn("innerHTML", scene)
        self.assertIn("fillText", scene.split("function ekranCiz", 1)[1].split("\n}\n", 1)[0])
        self.assertIn("fillText", scene.split("function adYaz", 1)[1].split("\n}\n", 1)[0])
        self.assertIn("adYaz(", scene.split("function levhaCiz", 1)[1].split("\n}\n", 1)[0])
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("office.setDuyuru(salonEkrani(state, Date.now()))", app)
        self.assertIn("office.setOfisAdi(ad)", app)
        self.assertTrue(body)


SUNUCU = r"""
const UYARI = { sistem: { seviye: 'sari', oneri: 1, domain_sorunu: 0 } };
const admin = (list) => list.find((a) => a.gorevli === 'sunucu' && a.nobetci) || null; // the IT team's person on shift
const itler = (list) => list.filter((a) => a.id.startsWith('sus:sunucu'));
"""


@unittest.skipUnless(NODE, "node is not installed")
class ServerRoomTest(unittest.TestCase):
    """The Sunucu odası (plan "Sonraki iş (5)", owner decision 2026-11-12): a fixed facility with cabinets; the IT team."""

    def js(self, expr):
        return run_js(f"(() => {{ {SUNUCU}\n return {expr}; }})()")

    def test_a_fixed_cell_under_idari_isler_with_two_cabinet_groups_and_a_reachable_spot(self):
        out = run_js(f"""{list(COUNTS)}.map((n) => {{ const p = d.ofisPlani(names(n), {{ max_running_per_project: 2 }});
          const r = room(p, 'sunucu'), idari = room(p, 'idari'); const k = p.dugumler[d.SUNUCU_KABIN_YERI];
          const inside = (x, z) => x > r.x && x < r.x + r.w && z > r.z && z < r.z + r.d;
          const boxes = d.mobilyaKutulari(p).filter((b) => b.id.startsWith('sunucu-kabin:'));
          const w = p.yol('asansor', d.SUNUCU_KABIN_YERI), m = p.yol('asansor', 'sunucu-masa');
          const k2 = p.dugumler[d.SUNUCU_KABIN_YERI_2], m2 = p.dugumler[d.IT_ARKADAS_MASASI];
          const desks = d.mobilyaKutulari(p).filter((b) => b.id.startsWith('masa:sunucu-'));
          return {{ r: [r.id, r.tur, r.ad, r.x, r.z, r.w, r.d], sunucu: r.sunucu, under: Math.abs(r.x - idari.x) < 1e-6 && r.z > idari.z,
            kabin: [k.oda, k.tur, inside(k.x, k.z)], groups: r.sunucu.gruplar.every(([x, z]) => inside(x, z)), boxes: boxes.length,
            spotFree: boxes.every((b) => !(k.x > b.x0 && k.x < b.x1 && k.z > b.z0 && k.z < b.z1)),
            reach: w.length > 0 && w[w.length - 1].id === d.SUNUCU_KABIN_YERI && m.length > 0,
            personel: d.TESIS_PERSONELI.sunucu, kanat: r.x >= p.kanat.x,
            team: [k2.oda, k2.tur, inside(k2.x, k2.z), m2.oda, m2.tur, inside(m2.x, m2.z), desks.length,
              p.yol('asansor', d.SUNUCU_KABIN_YERI_2).length > 0, p.yol('asansor', d.IT_ARKADAS_MASASI).length > 0,
              boxes.every((b) => !(k2.x > b.x0 && k2.x < b.x1 && k2.z > b.z0 && k2.z < b.z1))] }}; }})""")
        first = out[0]
        for n, o in zip(COUNTS, out):
            with self.subTest(projects=n):
                self.assertEqual(o["r"], first["r"])  # never moves when projects are added
                self.assertEqual(o["r"][:3], ["sunucu", "sunucu", "Sunucu odası"])
                self.assertTrue(o["under"] and o["kanat"])  # the wing's first column, under İdari işler
                self.assertEqual(len(o["sunucu"]["gruplar"]), 2)
                self.assertEqual(o["sunucu"]["kabin"], 3)
                self.assertTrue(o["groups"])
                self.assertEqual(o["boxes"], 2)  # walks go around the cabinets
                self.assertEqual(o["kabin"], ["sunucu", "kabin", True])
                self.assertTrue(o["spotFree"] and o["reach"])
                self.assertEqual(o["personel"], "IT sorumlusu")
                # the IT team: a second cabinet spot (the helper) and a second desk (the off-shift colleague)
                self.assertEqual(o["team"], ["sunucu", "kabin", True, "sunucu", "masa", True, 2, True, True, True])

    def test_on_duty_the_person_on_shift_stands_at_the_cabinets_also_at_night_and_in_hafif(self):
        out = self.js("""({
          calm: [admin(run(st())).yer, admin(run(st())).durum_metni],
          duty: [admin(run(st(UYARI))).yer, admin(run(st(UYARI))).durum_metni, !!admin(run(st(UYARI))).gorevde],
          pose: [admin(run(st(UYARI))).poz, h.yuzAcisi(d.ofisPlani(['vitrin']), d.SUNUCU_KABIN_YERI)],
          domain: admin(run(st({ sistem: { seviye: 'yesil', oneri: 0, domain_sorunu: 1 } }))).yer,
          night: admin(run(st(UYARI), NOW + 13 * 3600000)) && admin(run(st(UYARI), NOW + 13 * 3600000)).yer,
          nightCalm: admin(run(st(), NOW + 13 * 3600000)).yer,
          hafif: itler(run(st(UYARI), NOW, null, { hafif: true })).map((a) => [a.yer, a.poz, !!a.nobetci]),
          hafifCalm: itler(run(st(), NOW, null, { hafif: true })).map((a) => [a.yer, a.poz, !!a.nobetci]),
          none: admin(run(st({ sistem: null }))).durum_metni })""")
        self.assertNotEqual(out["calm"][0], "sunucu-kabin")
        self.assertNotEqual(out["calm"][1], "uyarı var")
        self.assertEqual(out["duty"], ["sunucu-kabin", "nöbette · uyarı var · kabinlerde", True])
        self.assertEqual(out["domain"], "sunucu-kabin")
        self.assertEqual(out["pose"], ["yaziyor", 3.141592653589793])  # typing at a cabinet, facing it
        self.assertEqual(out["night"], "sunucu-kabin")  # duty first: also outside the office hours
        self.assertIn(out["nightCalm"], ("sunucu-masa", "sunucu-kabin"))  # someone is always on shift
        self.assertEqual(out["hafif"], [["sunucu-kabin", "yaziyor", True]])  # hafif: the person on shift only, still
        self.assertEqual(out["hafifCalm"], [["sunucu-masa", "yaziyor", True]])
        self.assertNotEqual(out["none"], "uyarı var")

    def test_off_duty_the_person_on_shift_keeps_to_the_room_with_seeded_rounds(self):
        out = self.js("""(() => { const seen = {}; const texts = new Set();
          for (let m = 0; m < 240; m += 1) { const a = admin(run(st(), NOW + m * 60000)); if (!a) continue;
            seen[a.yer] = (seen[a.yer] || 0) + 1; texts.add(a.durum_metni); }
          const same = JSON.stringify(admin(run(st(), NOW + 7 * 60000))) === JSON.stringify(admin(run(st(), NOW + 7 * 60000)));
          const night = admin(run(st(), NOW + 13 * 3600000));
          return { seen, texts: [...texts], same, night }; })()""")
        seen = out["seen"]
        self.assertIn("sunucu-masa", seen)  # the room's desk …
        self.assertIn("sunucu-kabin", seen)  # … a seeded round to the cabinets now and then …
        self.assertLess(seen["sunucu-kabin"], 240 / 3)  # … not all the time
        self.assertEqual(set(seen), {"sunucu-masa", "sunucu-kabin"})  # it holds the room: no lunch, no breaks away
        self.assertIn("kabinleri kontrol ediyor", out["texts"])
        self.assertFalse(any("uyarı var" in t for t in out["texts"]))
        self.assertTrue(out["same"])  # deterministic
        self.assertIsNotNone(out["night"])  # the night shift is there

    def test_the_card_shows_status_groups_suggestions_and_domains_as_text(self):
        out = self.js("""(() => {
          const a = admin(run(st(UYARI)));
          const data = { cpu: { cekirdek: 10, yuk: [7.4, 6.8, 6.1], yuk_orani: 0.74 }, seviye: 'sari',
            bellek: { toplam_gb: 16, kullanilan_gb: 12.6, yuzde: 79, baski: 'normal', bos_yuzde: 31 },
            disk: { toplam_gb: 460, bos_gb: 66.6, dolu_yuzde: 86 }, pil: { yuzde: 94, durum: 'şarj oluyor' }, acik_kalma_sn: 788400,
            docker: { konteyner: 0, cpu: 0, bellek_mb: 0 },
            gruplar: [{ ad: 'Java', sayi: 2, cpu: 80.4, bellek_mb: 2048 }, { ad: 'Claude oturumları', sayi: 4, cpu: 7, bellek_mb: 1300, bosta: 3 }],
            oneriler: [{ tur: 'docker-bosta', metin: "Docker boşta (karar Selin'in)." }],
            domainler: { liste_var: false, metin: 'Domain listesi henüz yok — Ar-Ge ilk çalışmasında soracak' } };
          const k = h.karakterKarti(a, st(UYARI), NOW, { veri: { sistem: data } });
          const uzman = h.karakterKarti({ id: 'sus:sunucu:1', tur: 'sus', gorevli: 'sunucu', etiket: 'IT uzmanı' }, st(), NOW, {});
          const withList = h.sistemKarti(st(UYARI), NOW, { ...data, domainler: { liste_var: true, son_kontrol: iso(NOW - 3600000),
            domainler: [{ domain: 'site.example', https: { acildi: false, durum_kodu: null, gun: 9, hata: 'zaman aşımı' },
              dns: { ipler: ['104.16.1.1'], bulundu: true, cloudflare: true, cloudflare_bekleniyor: true, degisti: false },
              sorunlar: [{ tur: 'acilmiyor', metin: 'açılmıyor' }, { tur: 'sertifika', metin: 'sertifikası bitiyor' }] }],
            eposta: [{ domain: 'site.example', mx: 'bilinmiyor' }] } });
          const empty = h.sistemKarti(st(UYARI), NOW, null);
          return { k, withList, empty, uzman, v: d.itVardiyasi(NOW, st().sahne), ekip: d.IT_EKIBI }; })()""")
        k = out["k"]
        v, ekip = out["v"], out["ekip"]
        self.assertEqual((k["baslik"], k["alt"]), (ekip[v["nobetci"]]["etiket"], "IT ekibi"))
        self.assertEqual((out["uzman"]["baslik"], out["uzman"]["alt"]), ("IT uzmanı", "IT ekibi"))
        rows = {r["ad"]: r["metin"] for r in k["satirlar"] if r["ad"]}
        # the shift first: who is on shift now and until when, the next change, the team (from the clock, 10:00)
        self.assertEqual(rows["Nöbette"], f"{ekip[v['nobetci']]['ad']} · gündüz vardiyası (08:00–16:00)")
        self.assertEqual(rows["Nöbet bitişi"], "bugün 16:00")
        self.assertEqual(rows["Sonraki değişim"], f"bugün 16:00 · {ekip[v['sonraki']['kisi']]['ad']} gelir (akşam vardiyası)")
        names = [r["ad"] for r in k["satirlar"]]
        self.assertLess(names.index("Nöbette"), names.index("İşlemci"))
        ekip_rows = [r["metin"] for r in k["satirlar"][names.index("Ekip"):names.index("Ekip") + 3]]
        self.assertEqual(sorted(x.split(" · ")[1] for x in ekip_rows), ["nöbette", "otelde", "otelde"])  # off shift: at the Otel (owner decision 2026-11-14)
        text = " | ".join(f"{r['ad']}: {r['metin']}" for r in k["satirlar"])
        for need in ("10 çekirdek", "12,6 / 16,0 GB", "%86 dolu", "%94", "9 gün 3 saat", "Java: 2 süreç", "3 boşta",
                     "Docker boşta", "Domain listesi henüz yok — Ar-Ge ilk çalışmasında soracak", "karar Selin'in"):
            self.assertIn(need, text)
        w = " | ".join(r["metin"] for r in out["withList"]["satirlar"])
        for need in ("site.example · açılmıyor (zaman aşımı) · sertifika 9 gün · Cloudflare · sorun: açılmıyor, sertifikası bitiyor",
                     "site.example · MX bilinmiyor", "bugün"):
            self.assertIn(need, w)
        self.assertEqual([r["metin"] for r in out["empty"]["satirlar"] if r["ad"] == "Durum"], ["yük sarı (yoğun) · okunuyor…"])
        self.assertEqual(out["empty"]["satirlar"][0]["ad"], "Nöbette")  # the shift also before the data arrives

    def test_the_scene_draws_cabinets_with_two_light_materials_changed_in_place(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("r.tur === 'sunucu'", scene)
        body = scene.split("buildServerRoom(r, g) {", 1)[1].split("\n  // The hall screen", 1)[0]
        self.assertIn("birlestir(leds)", body)  # every status light in one merged mesh
        self.assertIn("beacon.visible = false", body)  # the warning light: no draw call while hidden
        self.assertIn("S.isik.color.set(c)", body)  # changed in place, never rebuilt
        frame = scene.split("  frame() {", 1)[1].split("\n  step(", 1)[0]
        self.assertNotIn("sunucu", frame)  # no per-frame cost
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("office.setSistem(state.sistem)", app)
        self.assertIn("sunucu: ['sistem']", app)


ARGE = r"""
const ARGE_IS = '2026-11-11-090000-arge.md';
const argeSt = (x = {}) => st({ projects: [{ name: 'vitrin' }, { name: 'arge' }], ...x });
const argeTask = (status = 'calisiyor') => task(ARGE_IS, status, { project: 'arge', tier: 'genel', model: 'sonnet',
  session: 'ofis-arge-1111-090000-ab12', title: 'Günlük Ar-Ge taraması' });
const argeSes = () => ses('ofis-arge-1111-090000-ab12', 'busy', { project: 'arge', note: ARGE_IS, model: 'sonnet', tier: 'genel' });
const uzman = (list) => list.find((a) => a.id === 'sus:arge') || null;
"""


@unittest.skipUnless(NODE, "node is not installed")
class ArGeRoomTest(unittest.TestCase):
    """The Ar-Ge odası (plan "Sonraki iş (6)", owner decision 2026-11-12): a fixed facility with a whiteboard, a bookshelf and two
    desks; the Ar-Ge uzmanı types there while an arge job runs; the arge workspace is no team bay."""

    def js(self, expr):
        return run_js(f"(() => {{ {ARGE}\n return {expr}; }})()")

    def test_a_fixed_cell_in_the_wing_with_a_whiteboard_a_bookshelf_and_two_reachable_desks(self):
        out = run_js(f"""{list(COUNTS)}.map((n) => {{ const p = d.ofisPlani(names(n), {{ max_running_per_project: 2 }});
          const r = room(p, 'arge'), studyo = room(p, 'sosyal-studyo');
          const inside = ([x, z]) => x > r.x && x < r.x + r.w && z > r.z && z < r.z + r.d;
          const desks = d.mobilyaKutulari(p).filter((b) => b.id.startsWith('masa:arge-'));
          const boxes = d.mobilyaKutulari(p).filter((b) => b.id.startsWith('arge-'));
          const m1 = p.dugumler['arge-masa'], m2 = p.dugumler[d.ARGE_MASA_2];
          return {{ r: [r.id, r.tur, r.ad, r.x, r.z, r.w, r.d], kanat: r.x >= p.kanat.x,
            under: Math.abs(r.x - studyo.x) < 1e-6 && r.z > studyo.z,
            tahta: inside(r.arge.tahta), kitaplik: inside(r.arge.kitaplik), desks: desks.length, boxes: boxes.length,
            nodes: [m1.oda, m1.tur, inside([m1.x, m1.z]), m2.oda, m2.tur, inside([m2.x, m2.z])],
            reach: p.yol('asansor', 'arge-masa').length > 0 && p.yol('asansor', d.ARGE_MASA_2).length > 0,
            free: boxes.every((b) => ![m1, m2].some((m) => m.x > b.x0 && m.x < b.x1 && m.z > b.z0 && m.z < b.z1)),
            personel: d.TESIS_PERSONELI.arge, listed: d.KANAT_TESISLERI.includes('arge') }}; }})""")
        first = out[0]
        for n, o in zip(COUNTS, out):
            with self.subTest(projects=n):
                self.assertEqual(o["r"], first["r"])  # never moves when projects are added
                self.assertEqual(o["r"][:3], ["arge", "arge", "Ar-Ge odası"])
                self.assertTrue(o["kanat"] and o["under"])  # the wing's second column, under the studio
                self.assertTrue(o["tahta"] and o["kitaplik"])
                self.assertEqual(o["desks"], 2)
                self.assertEqual(o["boxes"], 2)  # the whiteboard and the bookshelf: walks go around them
                self.assertEqual(o["nodes"], ["arge", "masa", True, "arge", "masa", True])
                self.assertTrue(o["reach"] and o["free"])
                self.assertEqual(o["personel"], "Ar-Ge uzmanı")
                self.assertTrue(o["listed"])

    def test_the_arge_workspace_is_no_team_bay(self):
        out = self.js("""(() => { const p = d.ofisPlani(['vitrin', 'arge']), q = d.ofisPlani(['vitrin']);
          return { projeler: p.projeler, bay: !!room(p, 'ekip-arge'), same: JSON.stringify(p.odalar) === JSON.stringify(q.odalar) }; })()""")
        self.assertEqual(out["projeler"], ["vitrin"])
        self.assertFalse(out["bay"])
        self.assertTrue(out["same"])

    def test_the_uzman_types_at_its_desk_while_an_arge_job_runs_and_no_robot_stands_for_the_job(self):
        out = self.js("""(() => {
          const busy = run(argeSt({ tasks: [argeTask()], sessions: [argeSes()] }));
          const idle = run(argeSt());
          const night = run(argeSt({ tasks: [argeTask()], sessions: [argeSes()] }), NOW + 13 * 3600000);
          const nightIdle = run(argeSt(), NOW + 13 * 3600000);
          const hafif = run(argeSt({ tasks: [argeTask()] }), NOW, null, { hafif: true });
          const hafifIdle = run(argeSt(), NOW, null, { hafif: true });
          const kontrolde = run(argeSt({ tasks: [argeTask('kontrolde')] }));
          const u = uzman(busy);
          return { busy: [u.yer, u.poz, u.durum_metni, !!u.gorevde, u.arge_is],
            robots: busy.filter((a) => a.proje === 'arge').map((a) => a.id),
            queued: run(argeSt({ tasks: [argeTask('sirada')] })).filter((a) => a.proje === 'arge').map((a) => a.id),
            idle: uzman(idle) && uzman(idle).durum_metni,
            night: uzman(night) && [uzman(night).yer, uzman(night).poz],
            nightIdle: uzman(nightIdle) && !uzman(nightIdle).cikis && !uzman(nightIdle).otel ? uzman(nightIdle).yer : null, // (at the Otel at night)
            hafif: uzman(hafif) && [uzman(hafif).yer, uzman(hafif).poz], hafifIdle: !!uzman(hafifIdle),
            kontrolde: uzman(kontrolde) && uzman(kontrolde).yer }; })()""")
        self.assertEqual(out["busy"][:2], ["arge-masa", "yaziyor"])
        self.assertIn("araştırıyor", out["busy"][2])
        self.assertTrue(out["busy"][3])
        self.assertEqual(out["busy"][4], "2026-11-11-090000-arge.md")
        self.assertEqual(out["robots"], [])  # the Ar-Ge uzmanı stands for the job: no second robot
        self.assertEqual(out["queued"], [])  # nor one in the lobby
        self.assertNotIn("araştırıyor", out["idle"] or "")
        self.assertEqual(out["night"], ["arge-masa", "yaziyor"])  # real work first: also outside its hours
        self.assertIsNone(out["nightIdle"])  # otherwise home at night
        self.assertEqual(out["hafif"], ["arge-masa", "yaziyor"])
        self.assertFalse(out["hafifIdle"])
        self.assertEqual(out["kontrolde"], "arge-masa")

    def test_the_card_shows_the_last_report_the_suggestions_the_diff_and_opens_the_report(self):
        out = self.js("""(() => {
          const veri = { arge: { son_rapor: { gun: '2026-11-11', is: '2026-11-11-090000-arge.md', baslik: 'Günlük Ar-Ge taraması',
              not: 'ArGe-2026-11-11', ozet: ['Yeni bir ücretsiz model çıktı.', 'Codex 0.168 yayımlandı.'],
              oneriler: [{ model: 'opencode/beam-free', lisans: 'MIT', neden: 'hızlı', kart: '2026-11-11-arge-denetci-onerisi.md' },
                { model: 'opencode/x-free', lisans: '', neden: '', kart: null }] },
            fark: { gun: '2026-11-11', onceki_gun: '2026-11-10', degisiklik: true,
              modeller: { durum: 'tamam', yeni: ['opencode/beam-free'], kalkan: ['opencode/iceman-free'],
                ad_degisen: [['opencode/glm-5.3-flash-free', 'opencode/glm-5.4-flash-free']], sayi: 12 },
              surumler: [{ arac: 'codex', onceki: 'codex-cli 0.167.0', simdi: 'codex-cli 0.168.0' }] },
            kontrol_gunu: '2026-11-11', surumler: { claude: '2.1.322 (Claude Code)', codex: 'codex-cli 0.168.0', opencode: 'bilinmiyor' } } };
          const a = { id: 'sus:arge', tur: 'sus', gorevli: 'arge', etiket: 'Ar-Ge uzmanı', arge_is: ARGE_IS };
          const k = h.karakterKarti(a, argeSt({ tasks: [argeTask()] }), NOW, { veri });
          const bos = h.karakterKarti({ ...a, arge_is: null }, argeSt(), NOW, { veri: { arge: { son_rapor: null, fark: null } } });
          const text = (c) => c.satirlar.map((s) => `${s.ad}: ${s.metin}`).join('\\n');
          return { baslik: k.baslik, alt: k.alt, text: text(k), eylemler: k.eylemler, bos: text(bos), bosE: bos.eylemler }; })()""")
        self.assertEqual(out["baslik"], "Ar-Ge uzmanı")
        self.assertEqual(out["alt"], "araştırma")
        for needle in ("Yeni bir ücretsiz model çıktı.", "opencode/beam-free · MIT", "lisansı yazılmadı",
                       "Yeni: opencode/beam-free", "Kalkan: opencode/iceman-free",
                       "opencode/glm-5.3-flash-free → opencode/glm-5.4-flash-free",
                       "codex: codex-cli 0.167.0 → codex-cli 0.168.0", "Günlük Ar-Ge taraması"):
            self.assertIn(needle, out["text"], needle)
        self.assertIn({"tur": "is", "note": "2026-11-11-090000-arge.md", "metin": "Raporu aç"}, out["eylemler"])
        self.assertIn({"tur": "karar", "note": "2026-11-11-arge-denetci-onerisi.md", "metin": "Kartı aç: opencode/beam-free"},
                      out["eylemler"])
        self.assertIn({"tur": "is", "note": "2026-11-11-090000-arge.md", "metin": "Çalışan işi aç"}, out["eylemler"])
        self.assertIn("Not: ArGe-2026-11-11 (Obsidian)", out["text"])
        self.assertIn("henüz rapor yok", out["bos"])
        self.assertEqual(out["bosE"], [])

    def test_the_page_fetches_the_card_data_and_the_scene_draws_the_room(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("arge: ['arge']", app)
        self.assertIn("r.tur === 'arge'", scene)


@unittest.skipUnless(NODE, "node is not installed")
class TurningTheViewTest(unittest.TestCase):
    """The owner, 2026-11-13: the office turns a full 360 degrees; ↺ / ↻ and Q / E turn it 45 degrees, ⟲ turns it back."""

    def test_one_step_is_45_degrees_either_way_and_never_wrapped_mid_animation(self):
        out = run_js("""[h.DONUS_ADIMI, h.donusAcisi(Math.PI / 4, 1), h.donusAcisi(Math.PI / 4, -1), h.donusAcisi(0, 0),
          h.donusAcisi(NaN, 1), h.donusAcisi(3, -1, 0.5), h.donusAcisi(3 * Math.PI / 4 + 0.1, -1)]""")
        q = 3.141592653589793 / 4
        self.assertAlmostEqual(out[0], q)
        self.assertAlmostEqual(out[1], 0)        # ↻ (yon 1): theta decreases
        self.assertAlmostEqual(out[2], 2 * q)    # ↺ (yon -1): theta increases
        self.assertEqual(out[3], 0)
        self.assertAlmostEqual(out[4], -q)       # an unreadable angle counts as 0
        self.assertAlmostEqual(out[5], 3.5)
        self.assertAlmostEqual(out[6], 4 * q + 0.1)  # past π: not wrapped, the animation turns one step only

    def test_eight_steps_make_a_full_turn_and_the_angle_wraps(self):
        out = run_js("""(() => { let a = Math.PI / 4; const seen = [];
          for (let i = 0; i < 8; i++) { a = h.donusAcisi(a, 1); seen.push(h.aciyiSar(a)); }
          return [h.aciyiSar(a), seen, h.aciyiSar(Math.PI), h.aciyiSar(-Math.PI), h.aciyiSar(7), h.aciyiSar('x'),
            h.aciyiSar(-10 * Math.PI + 0.25)]; })()""")
        pi = 3.141592653589793
        self.assertAlmostEqual(out[0], pi / 4)  # back where it started
        self.assertEqual(len({round(x, 6) for x in out[1]}), 8)  # eight different directions
        for x in out[1]:
            self.assertTrue(-pi < x <= pi + 1e-9, x)
        self.assertAlmostEqual(out[2], pi)
        self.assertAlmostEqual(out[3], pi)  # (-π, π]
        self.assertAlmostEqual(out[4], 7 - 2 * pi)
        self.assertEqual(out[5], 0)
        self.assertAlmostEqual(out[6], 0.25)

    def test_the_reset_turns_back_the_short_way(self):
        out = run_js("""[h.sifirlamaAcisi(Math.PI / 4, Math.PI / 4), h.sifirlamaAcisi(Math.PI / 4 + 4 * Math.PI, Math.PI / 4),
          h.sifirlamaAcisi(-3, Math.PI / 4), h.sifirlamaAcisi(3, Math.PI / 4), h.sifirlamaAcisi(-2.5, 2.5)]""")
        pi = 3.141592653589793
        self.assertAlmostEqual(out[0], pi / 4)
        self.assertAlmostEqual(out[1], pi / 4 + 4 * pi)  # whole turns kept: no spin back through them
        self.assertAlmostEqual(out[2], pi / 4 - 2 * pi)  # from -3 the short way is down to -5.50, not up 3.79
        self.assertAlmostEqual(out[3], pi / 4)
        self.assertAlmostEqual(out[4], 2.5 - 2 * pi)  # across ±π: 1.28 rad, not 5
        for o, a in ((out[2], -3), (out[3], 3), (out[4], -2.5)):
            self.assertLessEqual(abs(o - a), pi + 1e-9)

    def test_q_and_e_turn_with_the_zoom_keys_guard(self):
        out = run_js("""[['q', {}], ['Q', {}], ['e', {}], ['E', {}], ['x', {code: 'KeyQ'}], ['w', {}],
          ['q', {ctrlKey: true}], ['e', {metaKey: true}], ['q', {altKey: true}], ['q', {target: {tagName: 'input'}}],
          ['e', {target: {tagName: 'TEXTAREA'}}], ['e', {target: {tagName: 'DIV', isContentEditable: true}}]]
          .map(([key, x]) => h.donusTusu({key, ...x})).concat([h.donusTusu(null), h.zoomTusu({key: 'q'})])""")
        self.assertEqual(out, [-1, -1, 1, 1, -1, None, None, None, None, None, None, None, None, None])

    def test_the_scene_turns_around_the_view_centre_and_the_reset_turns_back(self):
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        self.assertIn("c.minAzimuthAngle = -Infinity;", scene)
        self.assertIn("c.maxAzimuthAngle = Infinity;", scene)
        self.assertIn("c.minPolarAngle = 0.55;", scene)  # the tilt limits stay: never under the floor
        self.assertIn("c.maxPolarAngle = 1.12;", scene)
        body = scene[scene.index("  dondur(yon) {"):]
        body = body[:body.index("\n  }\n")]
        for text in ("donusAcisi(f && Number.isFinite(f.aci1) ? f.aci1 : aci0, yon)", "this.userMoved = true;",
                     "from: t, to: t.clone()", "this.kirli = true;"):
            self.assertIn(text, body)
        reset = scene[scene.index("  tumunuGoster() {"):]
        reset = reset[:reset.index("\n  }\n")]
        self.assertIn("sifirlamaAcisi(aci, KAMERA_ACISI)", reset)
        self.assertIn("this.fit();", reset)


if __name__ == "__main__":
    unittest.main()
