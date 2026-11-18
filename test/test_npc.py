"""The living office's NPCs over whole simulated days (web/ofis-davranis.js with the scene's walking emulated).

The fixtures (test/npc/fixtures.mjs) are /api/state in bin/state.py's shapes; test/npc/yurume.mjs emulates
web/scene.js setActors and its walking at YURUME_HIZI, so "did the Sekreter reach the CEO's door" is measured, not
assumed. Skipped without node. Run: python3 -I test/test_npc.py"""
import json
import re
import os
import shutil
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # (-I leaves the script's folder out)
from yavas import yavas  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sahip_yasaklari  # noqa: E402,F401  (the owner's name as in his ofis.json; node reads it too)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NPC = Path(__file__).resolve().parent / "npc"
NODE = shutil.which("node")

PRELUDE = r"""
const at = F.at, M = F.M, H = F.H;
// the duty roles of the shift teams: 'sus:guvenlik' / 'sus:sekreter' stand for whoever of the team is on shift now
const ROL = { 'sus:guvenlik': 'guvenlik', 'sus:sekreter': 'sekreter' };
const bul = (a, id) => (ROL[id] ? a.find((x) => x.tur === 'sus' && x.gorevli === ROL[id] && x.nobetci)
  : a.find((x) => x.id === id)) || null;
// runs scenario `ad` from ms a to b every `step` seconds (prev passed on, the scene's walking emulated); cb(ms, actors,
// emu, state) per tick; returns the emulator
function gun(ad, a, b, step, cb, o = {}) {
  const spec = typeof ad === 'string' ? F.SENARYOLAR[ad] : ad;
  const per = spec.per ?? 1;
  let plan = null, key = '', prev = null, emu = null;
  for (let ms = a; ms < b; ms += step * 1000) {
    const st = F.durumOlustur(spec, ms);
    const den = d.denetciListesi(st.modeller);
    const k = `${st.projects.map((p) => p.name).join('|')}#${per}#${den.join(',')}`;
    if (k !== key) { plan = d.ofisPlani(st.projects, { max_running_per_project: per, denetciler: den }); key = k; prev = null; emu = new Y.SahneEmu(plan); }
    const actors = d.niyetler(st, ms, prev, { hafif: !!(o.hafif ?? spec.hafif), max_running_per_project: per, plan });
    const ev = emu.setActors(actors, ms);
    emu.advance(step);
    if (cb) cb(ms, actors, emu, st, ev, plan);
    prev = actors;
  }
  return emu;
}
// duty stints of one actor: [{bas, son, ulasti}] while pred(actor) holds (contiguous ticks)
function stintler(ad, a, b, id, pred) {
  const out = []; let cur = null;
  gun(ad, a, b, 1, (ms, actors, emu) => {
    const x = bul(actors, id);
    if (x && pred(x)) { if (!cur) out.push(cur = { bas: ms, son: ms, ulasti: false, yer: x.yer }); cur.son = ms; if (emu.arrived(x.id)) cur.ulasti = true; }
    else cur = null;
  });
  return out;
}
"""


def run_js(expr, timeout=600):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (Path(tmp) / "web").mkdir()
        (Path(tmp) / "npc").mkdir()
        for name in ("ofis-davranis.js", "ofis-sahne.js", "ofis-text.js"):
            shutil.copyfile(WEB / name, Path(tmp) / "web" / name)
        for name in ("fixtures.mjs", "yurume.mjs"):
            shutil.copyfile(NPC / name, Path(tmp) / "npc" / name)
        uri = lambda n: json.dumps((Path(tmp) / n).as_uri())  # noqa: E731
        code = (f"import * as d from {uri('web/ofis-davranis.js')};\nimport * as h from {uri('web/ofis-sahne.js')};\n"
                f"import * as F from {uri('npc/fixtures.mjs')};\nimport * as Y from {uri('npc/yurume.mjs')};\n{PRELUDE}\n"
                f"const out = await ({expr});\nprocess.stdout.write(JSON.stringify(out), () => process.exit(0));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=timeout,
                              cwd=tmp, env=dict(os.environ, TZ="UTC"))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-3000:])
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class NoPhantomRobotTest(unittest.TestCase):
    """Only real Claude work becomes a robot: the approval step and the review panel's work never do."""

    def test_the_approval_step_is_no_robot_and_hides_no_kadro(self):
        out = run_js("""(() => { const s = (status, x = {}) => ({ projects: [{ name: 'kasa' }], sessions: [], ceo: { state: 'idle' },
            sahne: { saat_dilimi: 'Europe/Istanbul', sunucu_utc_ofset_dk: 180 },
            modeller: ['haiku', 'sonnet', 'opus', 'fable'].map((m) => ({ model: m, durum: 'hazir', calisan: 0 })),
            decisions: [{ note: 'k.md', project: 'kasa', kind: 'akis-onay', asked: '2026-11-12T10:00', answer_sent: false }],
            tasks: [{ note: 'k-3.md', project: 'kasa', status, tier: 'genel', model: 'sonnet', step_kind: 'onay', workflow: 'w',
              started: '2026-11-12T10:00:00', created: '2026-11-12T09:59:00', finished: '', session: '', ...x }] });
          const ms = at(10, 5);
          return ['sirada', 'karar-bekliyor', 'bitti'].map((st) => { const a = d.niyetler(s(st, st === 'bitti' ? { finished: '2026-11-12T10:04:50' } : {}), ms);
            return { robot: a.some((x) => x.id === 'is:k-3'), uzman: a.some((x) => x.id === 'kadro:sonnet'),
              sek: (bul(a, 'sus:sekreter') || {}).simge }; }); })()""")
        for o in out:
            self.assertEqual(o, {"robot": False, "uzman": True, "sek": "?"})

    def test_a_panel_review_never_becomes_a_claude_robot_nor_gets_tea(self):
        out = run_js("""(() => { const base = (t) => ({ projects: [{ name: 'kasa' }], sessions: [], ceo: { state: 'idle' },
            sahne: { saat_dilimi: 'Europe/Istanbul', sunucu_utc_ofset_dk: 180 }, decisions: [],
            modeller: ['haiku', 'sonnet', 'opus', 'fable', 'codex'].map((m) => ({ model: m, durum: 'hazir', calisan: 0 })),
            tasks: [{ note: 'r.md', project: 'kasa', tier: 'inceleme', step_kind: 'kod-inceleme', workflow: 'w', session: '',
              started: '2026-11-12T10:00:00', created: '2026-11-12T09:59:00', finished: '', ...t }] });
          const ms = at(10, 5), done = { status: 'bitti', finished: '2026-11-12T10:04:55' };
          const cases = [{ status: 'sirada', inceleme_yurutucu: 'codex', model: 'opus' }, { ...done, model: 'heyet', inceleme_yurutucu: 'codex' },
            { ...done, model: 'codex', inceleme_yurutucu: 'codex' }, { ...done, model: 'heyet' }];
          return cases.map((t) => { const a = d.niyetler(base(t), ms);
            return { robot: a.some((x) => x.id === 'is:r'), codex: a.filter((x) => x.model === 'codex').length,
              cay: (a.find((x) => x.id === 'sus:cayci') || {}).durum_metni, kidemli: a.some((x) => x.id === 'kadro:opus') }; }); })()""")
        for o in out:
            self.assertFalse(o["robot"], o)
            self.assertEqual(o["codex"], 1)  # the auditor at its desk only
            self.assertNotEqual(o["cay"], "çay getiriyor")
            self.assertTrue(o["kidemli"])

    def test_the_approval_step_labelled_onay_deniz_is_nobodys_work(self):
        # bin/akis.py writes katman `onay`, model `deniz` for the approval step (no step kind needed to know it)
        out = run_js("""(() => { const t = { note: 'k-3.md', project: 'kasa', status: 'karar-bekliyor', tier: 'onay', model: 'deniz',
            started: '2026-11-12T10:00:00', created: '2026-11-12T09:59:00', finished: '', session: '' };
          const st = { projects: [{ name: 'kasa' }], sessions: [], ceo: { state: 'idle' }, tasks: [t], decisions: [],
            sahne: { saat_dilimi: 'Europe/Istanbul', sunucu_utc_ofset_dk: 180 },
            modeller: ['haiku', 'sonnet', 'opus', 'fable'].map((m) => ({ model: m, durum: 'hazir', calisan: 0 })) };
          const a = d.niyetler(st, at(10, 5));
          return { robot: a.some((x) => x.id === 'is:k-3'), kadro: a.filter((x) => x.kadro).length,
            fam: d.modelAilesi(d.isModeli(t)), tier: d.katmanModeli(null, 'kasa', 'onay'), unvan: d.unvanOf(d.isModeli(t)).unvan,
            row: h.calisanlarTablosu(st, at(10, 5)).some((r) => r.id === 'is:k-3'),
            proje: h.karakterKarti({ id: 'sus:proje:kasa', tur: 'sus', gorevli: 'proje', proje: 'kasa', etiket: 'Kasa sorumlusu' }, st, at(10, 5))
              .satirlar.filter((r) => r.ad === 'Şimdi').map((r) => r.metin) }; })()""")
        self.assertEqual((out["robot"], out["kadro"], out["fam"], out["tier"], out["row"]), (False, 4, "", "", False))
        self.assertEqual(out["unvan"], "Ajan")  # never a kadro title
        self.assertEqual(len(out["proje"]), 1)
        self.assertIn("Selin'in onayını bekliyor", out["proje"][0])
        self.assertNotIn("Ajan", out["proje"][0])

    def test_a_claude_reviews_done_or_stuck_stays_in_the_qa_room(self):
        out = run_js("""(() => { const s = (status) => ({ projects: [{ name: 'kasa' }], ceo: { state: 'idle' }, decisions: [],
            sahne: { saat_dilimi: 'Europe/Istanbul', sunucu_utc_ofset_dk: 180 }, modeller: [],
            sessions: [{ name: 'ofis-kasa-r', project: 'kasa', status: 'idle', model: 'opus', tier: 'inceleme', note: 'r.md',
              step_kind: 'kod-inceleme', alt_ajanlar: [] }],
            tasks: [{ note: 'r.md', project: 'kasa', status, tier: 'inceleme', model: 'opus', step_kind: 'kod-inceleme',
              session: 'ofis-kasa-r', started: '2026-11-12T10:00:00', finished: '2026-11-12T10:04:50', inceleme_yurutucu: 'claude (codex yok: kota)' }] });
          return ['bitti', 'tikandi'].map((x) => d.niyetler(s(x), at(10, 5)).find((a) => a.id === 'is:r').yer); })()""")
        for y in out:  # plan "Sonraki iş (9)": where the review was done — the QA odası
            self.assertRegex(y, r"^qa-masa-\d$")

    def test_the_mapping_drives_the_fallback_model_and_the_role_text(self):
        out = run_js("""(() => { const k = { genel: { kod: 'opus', genel: 'sonnet', kolay: 'haiku' }, projeler: { kasa: { kod: 'sonnet' } } };
          return { fallback: [d.isModeli({ tier: 'kod', project: 'kasa' }, null, k), d.isModeli({ tier: 'kod', project: 'blog' }, null, k),
            d.isModeli({ tier: 'kod', project: 'kasa', model: 'claude-opus-5' }, null, k), d.isModeli({ tier: 'kod' })],
            uzman: h.kadroGorevi('sonnet', k), kidemli: h.kadroGorevi('opus', k), bos: h.kadroGorevi('fable', {}) }; })()""")
        self.assertEqual(out["fallback"], ["sonnet", "opus", "claude-opus-5", "opus"])  # the job's own model always wins
        self.assertEqual(out["uzman"], "okuma, özetleme, araştırma, ayrıca kasa: kod")
        self.assertEqual(out["kidemli"], "kod yazma ve hata düzeltme, inceleme")  # inceleme: the default mapping
        self.assertEqual(out["bos"], "büyük işleri planlama, mimari")  # no state: the defaults


@unittest.skipUnless(NODE, "node is not installed")
class DutyTripTest(unittest.TestCase):
    """Every duty trip lasts its walk plus a stay: it reaches its spot (measured with the scene's walking)."""

    def test_the_secretary_reaches_the_ceo_door_on_every_trip(self):
        out = run_js("stintler('kararlar', at(8, 58), at(10, 8), 'sus:sekreter', (x) => x.yer === 'ceo-kapi')")
        self.assertEqual(len(out), 3)  # one trip per new decision note (the 3rd card came with the 2nd at once)
        for s in out:
            self.assertTrue(s["ulasti"], s)

    def test_the_doctor_and_the_psychologist_reach_the_desk_they_visit(self):
        dr = run_js("stintler('takildi-kirmizi', at(9, 59), at(10, 4), 'sus:revir', (x) => x.durum_metni === 'hastaya bakıyor')")
        ps = run_js("stintler('kontrol', at(10, 29), at(10, 33), 'sus:psikolog', (x) => x.durum_metni === 'moral veriyor')")
        for out in (dr, ps):
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0]["ulasti"], out)

    def test_the_guard_reaches_the_greeting_spot_and_stays_in_the_lobby(self):
        out = run_js("""(() => { const st = stintler('dort-mesgul', at(9, 0), at(11, 0), 'sus:guvenlik', (x) => x.durum_metni === 'karşılıyor');
          const yerler = new Set(); gun('dort-mesgul', at(9, 0), at(11, 0), 5, (ms, a) => yerler.add(bul(a, 'sus:guvenlik').yer));
          return { st, yerler: [...yerler] }; })()""")
        self.assertTrue(out["st"])
        self.assertTrue(all(s["ulasti"] for s in out["st"]), out["st"])
        for y in out["yerler"]:  # duty breaks stay close: his post, the greeting spot, the dispenser, the lobby door
            self.assertIn(y, ("lobi-nobet", "lobi-karsilama", "lobi-su", "lobi-kapi"))

    def test_the_ceo_reaches_its_round_stops(self):
        out = run_js("stintler('bos-ofis', at(9, 0), at(12, 0), 'ceo', (x) => x.durum_metni === 'ofisi dolaşıyor')")
        self.assertTrue(out)
        self.assertGreaterEqual(sum(s["ulasti"] for s in out) / len(out), 0.9, out)


@unittest.skipUnless(NODE, "node is not installed")
class HandOverTest(unittest.TestCase):
    def test_a_queued_job_starting_from_the_lobby_lets_nobody_vanish(self):
        out = run_js("""(() => { const lost = [], kadro = [];
          gun('yukseltme', at(9, 59), at(10, 3), 1, (ms, a, emu, st, ev) => {
            for (const e of ev) if (e.t === 'kayboldu' && e.yer !== 'asansor' && !/alt:|^ozet/.test(e.id)) lost.push(e);
            const k = a.find((x) => x.id === 'kadro:opus'); if (k) kadro.push([k.yer, !!k.cikis]); });
          return { lost, cikis: kadro.some(([y, c]) => y === 'asansor' && c) }; })()""")
        self.assertEqual(out["lost"], [])
        self.assertTrue(out["cikis"])  # the Kıdemli walks out by the lift (the lobby robot takes the desk)

    def test_the_hakem_takes_over_the_security_reviewers_body(self):
        out = run_js("""(() => { let h = null; gun('codex-kota', at(11, 9), at(11, 11), 1, (ms, a) => { const x = a.find((y) => y.id === 'hakem'); if (x && !h) h = x; });
          return h && h.devral; })()""")
        self.assertEqual(out, "denetci:guvenlik")

    def test_helpers_appear_beside_their_parent_and_never_use_the_lift(self):
        out = run_js("""(() => { const seen = [];
          gun('yukseltme', at(10, 4, 50), at(10, 9, 30), 1, (ms, a, emu, st, ev) => {
            for (const x of a) if (x.tur === 'alt-ajan') seen.push(x.yer);
            for (const e of ev) if (e.t === 'asansorden' && /alt:/.test(e.id)) seen.push('LIFT'); });
          return [...new Set(seen)]; })()""")
        self.assertTrue(out)
        self.assertNotIn("LIFT", out)
        self.assertNotIn("asansor", out)


@unittest.skipUnless(NODE, "node is not installed")
class CalmMovementTest(unittest.TestCase):
    def test_walking_by_day_stays_low_and_nobody_switches_in_step(self):
        out = run_js("""(() => { const sw = new Map(); let prevYer = new Map();
          const emu = gun('bos-ofis', at(9, 0), at(12, 0), 1, (ms, a) => {
            let n = 0; for (const x of a) { if (prevYer.has(x.id) && prevYer.get(x.id) !== x.yer) n++; }
            sw.set(ms, n); prevYer = new Map(a.map((x) => [x.id, x.yer])); });
          const st = new Map();
          for (const [id, s] of [...emu.bitmis, ...[...emu.v].map(([id, v]) => [id, v.stats])]) {
            const t = st.get(id) || { w: 0, t: 0 }; t.w += s.walkMs / 1000; t.t += s.ticks; st.set(id, t); }
          const oran = [...st].map(([id, t]) => [id, t.w / Math.max(1, t.t)]);
          return { staff: Math.max(...oran.filter(([id]) => id.startsWith('sus:')).map(([, r]) => r)),
            kadro: Math.max(...oran.filter(([id]) => id.startsWith('kadro:')).map(([, r]) => r)),
            maxSwitch: Math.max(...sw.values()) }; })()""")
        self.assertLessEqual(out["staff"], 0.25, out)
        self.assertLessEqual(out["kadro"], 0.15, out)
        self.assertLessEqual(out["maxSwitch"], 6, out)  # no minute mark where the whole office stands up

    def test_a_nap_lasts_at_least_ten_minutes(self):
        out = run_js("""(() => { const P = d.ofisPlani(['vitrin']); const naps = [];
          for (const id of ['kadro:opus', 'kadro:haiku', 'kadro:sonnet', 'denetci:codex', 'denetci:glm']) {
            let run = 0;
            for (let ms = at(9); ms < at(18); ms += 60000) {
              const e = d.molaEtkinligi(id, ms, '', { ogle: true });  // a day nap: only in the lunch window (2026-11-16)
              if (e === 'uyku') run++; else { if (run) naps.push(run); run = 0; } } }
          return naps; })()""")
        self.assertTrue(out)
        self.assertGreaterEqual(min(out), 10, out)


@unittest.skipUnless(NODE, "node is not installed")
class StableSeatTest(unittest.TestCase):
    def test_nobody_changes_chair_during_a_meal(self):
        out = run_js("""(() => { const chair = new Map(), changes = []; let eaters = 0;
          gun('ogle', at(11, 58), at(13, 2), 1, (ms, a) => {
            for (const x of a) {
              if (x.poz !== 'yemek') { chair.delete(x.id); continue; }
              eaters = Math.max(eaters, a.filter((y) => y.poz === 'yemek').length);
              if (chair.has(x.id) && chair.get(x.id) !== x.yer) changes.push([x.id, chair.get(x.id), x.yer]);
              chair.set(x.id, x.yer); } });
          return { changes, eaters }; })()""")
        self.assertGreaterEqual(out["eaters"], 15)
        self.assertEqual(out["changes"], [])

    def test_a_queued_job_keeps_its_lobby_seat(self):
        out = run_js("""(() => { const seat = new Map(), changes = [];
          gun('dort-mesgul', at(9, 0), at(10, 30), 5, (ms, a) => {
            for (const x of a) { if (x.poz !== 'lobide') { seat.delete(x.id); continue; }
              if (seat.has(x.id) && seat.get(x.id) !== x.yer) changes.push(x.id); seat.set(x.id, x.yer); } });
          return changes; })()""")
        self.assertEqual(out, [])


@unittest.skipUnless(NODE, "node is not installed")
class FurnitureWalkTest(unittest.TestCase):
    def test_no_edge_crosses_furniture_a_wall_or_a_third_room(self):
        out = run_js("""[0, 1, 4, 10].flatMap((n) => [1, 4].map((per) => {
          const p = d.ofisPlani(Array.from({ length: n }, (_, i) => 'p' + i), { max_running_per_project: per, denetciler: ['codex', 'glm', 'deepseek', 'guvenlik'] });
          const boxes = d.mobilyaKutulari(p);
          const rooms = new Map(p.odalar.map((r) => [r.id, r]));
          const inRoom = (q, r, m) => q.x > r.x + m && q.x < r.x + r.w - m && q.z > r.z + m && q.z < r.z + r.d - m;
          const cross = p.kenarlar.filter(([a, b]) => d.kenarMobilyadan(p, a, b, boxes)).map((e) => e.join('>'));
          const third = p.kenarlar.filter(([a, b]) => { const A = p.dugumler[a], B = p.dugumler[b];
            for (let i = 1; i < 20; i++) { const q = { x: A.x + (B.x - A.x) * i / 20, z: A.z + (B.z - A.z) * i / 20 };
              for (const r of p.odalar) if (r.id !== A.oda && r.id !== B.oda && inRoom(q, r, 0.25)) return true; }
            return false; }).map((e) => e.join('>'));
          const outside = Object.values(p.dugumler).filter((q) => q.tur === 'gecit' && q.oda && !inRoom(q, rooms.get(q.oda), 0.3)).map((q) => q.id);
          const adj = new Map(); for (const [a, b] of p.kenarlar) { (adj.get(a) || adj.set(a, []).get(a)).push(b); (adj.get(b) || adj.set(b, []).get(b)).push(a); }
          const seen = new Set(['asansor']); const q = ['asansor'];
          while (q.length) { const c = q.shift(); for (const x of adj.get(c) || []) if (!seen.has(x)) { seen.add(x); q.push(x); } }
          return { n, per, cross, third, outside, unreachable: Object.keys(p.dugumler).filter((k) => !seen.has(k)) }; }))""")
        for o in out:
            with self.subTest(projects=o["n"], per=o["per"]):
                self.assertEqual(o["cross"], [])
                self.assertEqual(o["third"], [])
                self.assertEqual(o["outside"], [])
                self.assertEqual(o["unreachable"], [])


@unittest.skipUnless(NODE, "node is not installed")
class TextTest(unittest.TestCase):
    def test_possessive_suffix_after_numbers(self):
        out = run_js("[85, 90, 100, 50, 60, 96, 83, 20, 2, 7, 9, 10, 40, 70, 80, 150, 200, 1000, 0].map((n) => d.yuzdeMetni(n))")
        self.assertEqual(out, ["%85'i", "%90'ı", "%100'ü", "%50'si", "%60'ı", "%96'sı", "%83'ü", "%20'si", "%2'si", "%7'si",
                               "%9'u", "%10'u", "%40'ı", "%70'i", "%80'i", "%150'si", "%200'ü", "%1000'i", "%0'ı"])

    def test_the_tea_servers_card_lists_every_break_and_not_the_ceos_round(self):
        out = run_js("""(() => { const ak = [
            { id: 'a', tur: 'ajan', etiket: 'Kıdemli', poz: 'sigara', durum_metni: 'sigara molası', mola: true },
            { id: 'b', tur: 'ajan', etiket: 'Uzman', poz: 'kosuyor', durum_metni: 'spor yapıyor', mola: true },
            { id: 'c', tur: 'ajan', etiket: 'Stajyer', poz: 'dusta', durum_metni: 'duşta', mola: true },
            { id: 'ceo', tur: 'ceo', etiket: 'CEO', poz: 'yuruyor', durum_metni: 'ofisi dolaşıyor' },
            { id: 'd', tur: 'ajan', etiket: 'Müdür', poz: 'yatiyor', durum_metni: 'dinleniyor · uyuyor', mola: true }];
          const st = { tasks: [], sahne: { saat_dilimi: 'Europe/Istanbul' } };
          return h.karakterKarti({ id: 'sus:cayci', tur: 'sus', gorevli: 'cayci', etiket: 'Çaycı' }, st, at(10), { aktorler: ak })
            .satirlar.filter((r) => r.ad === 'Molada' || (r.ad === '' && / · /.test(r.metin))).map((r) => r.metin); })()""")
        self.assertEqual(out, ["Kıdemli · sigara molası", "Uzman · spor yapıyor", "Stajyer · duşta", "Müdür · dinleniyor · uyuyor"])

    def test_staff_on_duty_show_their_duty_at_the_default_zoom(self):
        out = run_js("""[h.etiketBilgisi({ id: 'sus:sekreter', tur: 'sus', etiket: 'Sekreter', durum_metni: 'karar götürüyor', gorevde: true }, { yakin: false }),
          h.etiketBilgisi({ id: 'sus:ik', tur: 'sus', etiket: 'İK sorumlusu', durum_metni: 'masasında' }, { yakin: false })]""")
        self.assertEqual((out[0]["ad"], out[0]["durum"]), ("Sekreter", "karar götürüyor"))
        self.assertEqual(out[1]["durum"], "")

    def test_the_announcement_gathering_stays_seated_most_of_its_minute(self):
        out = run_js("""(() => { const s = new Map(); gun('duyuru', at(14, 59), at(15, 3), 1, (ms, a, emu) => {
            for (const x of a) if (x.salonda) { const t = s.get(x.id) || 0; s.set(x.id, t + (emu.arrived(x.id) ? 1 : 0)); } });
          return [...s.values()]; })()""")
        self.assertTrue(out)
        self.assertGreaterEqual(sum(1 for v in out if v >= 45) / len(out), 0.8, out)


@unittest.skipUnless(NODE, "node is not installed")
class OfficeHoursTest(unittest.TestCase):
    def test_at_night_the_office_staff_are_home_and_nobody_plays(self):
        out = run_js("""(() => { const ids = new Set(), poz = new Set(); let guard = new Set(), ceo = new Set();
          gun('bos-ofis', at(2, 0), at(4, 0), 10, (ms, a) => { for (const x of a) if (!x.otel) { ids.add(x.id); poz.add(x.poz); }
            guard.add(bul(a, 'sus:guvenlik').yer); });
          gun('ceo-uyuyor', at(2, 0), at(3, 0), 10, (ms, a) => { const c = a.find((x) => x.id === 'ceo'); ceo.add(c.yer + '|' + c.durum_metni); });
          return { staff: [...ids].filter((i) => i.startsWith('sus:')), poz: [...poz], guard: [...guard], ceo: [...ceo] }; })()""")
        # the night shift of the shift teams only (IT, guard, Sekreter, and since 2026-11-14 the kitchen's server and cook:
        # one person each, 00–08); the doctor is home
        for team in ("sus:sunucu", "sus:guvenlik", "sus:sekreter", "sus:yemekhane", "sus:asci"):
            self.assertEqual(len([s for s in out["staff"] if s == team or s.startswith(team + ":")]), 1, out["staff"])
        self.assertEqual(len(out["staff"]), 5, out["staff"])
        for p in ("pingpong", "bilardo", "dart", "sigara", "kosuyor", "bisiklet", "agirlik", "yoga"):
            self.assertNotIn(p, out["poz"])
        self.assertTrue(set(out["guard"]) <= {"lobi-nobet", "lobi-su", "lobi-kapi"})
        self.assertEqual(out["ceo"], ["dinlenme-yatak-0|uyuyor"])  # a dormant CEO sleeps at night

    def test_the_doctor_goes_home_and_has_no_night_call_even_with_a_stuck_job(self):
        out = run_js("""(() => { const spec = { ...F.SENARYOLAR['takildi-kirmizi'], jobs: [{ note: '2026-11-12-190000-vitrin.md',
            project: 'vitrin', title: 'Akşam', tier: 'kod', model: 'opus', start: at(19), end: at(19, 30), outcome: 'tikandi', sessionIdleFor: 3 * H },
            { note: '2026-11-12-020000-vitrin.md', project: 'vitrin', title: 'Gece', tier: 'kod', model: 'opus', start: at(2), end: at(3),
              outcome: 'tikandi', sessionIdleFor: 3 * H }] };
          const gece = [], kirmizi = [];
          gun(spec, at(19, 0), at(21, 0), 5, (ms, a) => { if (a.some((x) => x.id === 'sus:revir' && !x.otel)) gece.push(ms);
            if (a.some((x) => x.poz === 'basi-onde' || x.simge === 'kirmizi')) kirmizi.push(ms); });
          gun(spec, at(2, 50), at(3, 10), 5, (ms, a) => { if (a.some((x) => x.id === 'sus:revir' && !x.otel)) gece.push(ms); });
          return { gece, stuck: kirmizi.length }; })()""")
        self.assertGreater(out["stuck"], 0)  # the stuck job is on the floor …
        self.assertEqual(out["gece"], [])  # … and the doctor is home all the same (no night call)

    def test_staff_walk_in_from_the_hotel_in_the_morning_and_are_greeted(self):
        # the Otel (owner decision 2026-11-14): the day staff spent the night at the hotel and walk back in (no lift)
        out = run_js("""(() => { const came = new Set(); let greet = 0;
          gun('bos-ofis', at(8, 0), at(9, 0), 1, (ms, a, emu, st, ev) => {
            for (const e of ev) if (e.t === 'otelden' && e.id.startsWith('sus:')) came.add(e.id);
            if (bul(a, 'sus:guvenlik').durum_metni === 'karşılıyor') greet++; });
          return { came: came.size, greet }; })()""")
        self.assertGreaterEqual(out["came"], 15)
        self.assertGreater(out["greet"], 0)

    def test_office_hours_can_be_switched_off_and_moved(self):
        out = run_js("""(() => { const s = (m) => ({ saat_dilimi: 'Europe/Istanbul', ...(m === undefined ? {} : { mesai: m }) });
          return [d.mesaiMi(at(3), s()), d.mesaiMi(at(10), s()), d.mesaiMi(at(3), s('')), d.mesaiMi(at(3), s('yok')),
            d.mesaiMi(at(7), s('06:00-14:00')), d.mesaiMi(at(15), s('06:00-14:00')), d.personelSaati('sus:ik', at(3), s())]; })()""")
        self.assertEqual(out, [False, True, True, True, True, False, "evde"])

    def test_a_ceo_with_something_open_never_lunches_rounds_or_breaks(self):
        out = run_js("""(() => { const yer = new Set();
          gun('kararlar', at(9, 0), at(16, 0), 10, (ms, a, emu, st) => {
            if (st.decisions.some((x) => !x.answer_sent)) { const c = a.find((x) => x.id === 'ceo'); yer.add(c.yer); } });
          return [...yer]; })()""")
        self.assertEqual(out, ["ceo-masa"])

    def test_hafif_follows_the_same_ceo_plan_without_walking(self):
        out = run_js("""(() => { const full = new Map(), light = new Map();
          gun('ceo-uyuyor', at(10), at(12), 10, (ms, a) => full.set(ms, a.find((x) => x.id === 'ceo').yer));
          gun('ceo-uyuyor', at(10), at(12), 10, (ms, a) => light.set(ms, a.find((x) => x.id === 'ceo').yer), { hafif: true });
          let ok = true; for (const [ms, y] of light) { const f = full.get(ms);
            if (y === 'dinlenme-yatak-0' && f !== y) ok = false;
            if (y !== 'dinlenme-yatak-0' && y !== 'ceo-masa' && y !== 'yemekhane-sandalye-7') ok = false; }
          return { ok, yerler: [...new Set(light.values())].sort() }; })()""")
        self.assertTrue(out["ok"], out)
        self.assertIn("ceo-masa", out["yerler"])


@unittest.skipUnless(NODE, "node is not installed")
class EventCueTest(unittest.TestCase):
    """Step 4 (B4, owner decision 2026-11-12): a short cue for a real event, only from /api/state, carried by a tiny prop."""

    def test_the_ceo_hands_a_new_job_over_to_the_project_sorumlusu(self):
        # plan 7 (owner decision 2026-11-12): CEO -> the project's sorumlu -> the worker; the sorumlu carries the last leg
        out = run_js("""({ ceo: stintler('ipuclari', at(8, 59), at(9, 4), 'ceo', (x) => x.durum_metni === 'işi teslim ediyor'),
          alir: stintler('ipuclari', at(8, 59), at(9, 4), 'sus:proje:vitrin', (x) => x.durum_metni === 'yeni işi teslim alıyor'),
          gotur: stintler('ipuclari', at(8, 59), at(9, 6), 'sus:proje:vitrin', (x) => x.durum_metni === 'işi masaya götürüyor') })""")
        self.assertEqual(len(out["ceo"]), 1, out)
        self.assertTrue(out["ceo"][0]["ulasti"], out)
        # plan "Sonraki iş (9)": the CEO hands it to the Genel Müdür (the spot beside its desk); the sorumlu is the last link
        self.assertEqual(out["ceo"][0]["yer"], "mudur-odasi-masa-yan")
        self.assertEqual(len(out["alir"]), 1, out)
        self.assertEqual(len(out["gotur"]), 1, out)
        self.assertTrue(out["gotur"][0]["ulasti"], out)
        # to the queued job's robot — in the lobby, or beside its desk once it started (it follows the robot; since the
        # meals, 2026-11-14, the CEO may first walk over from its breakfast, so the chain can end after the 09:02 start)
        self.assertRegex(out["gotur"][0]["yer"], r"^(lobi-koltuk-\d|ekip-vitrin-masa-\d-yan)$")
        self.assertGreaterEqual(out["gotur"][0]["bas"], out["ceo"][0]["son"])  # the hand-over first, then the leg
        self.assertGreaterEqual(out["gotur"][0]["son"] - out["gotur"][0]["bas"], 5000)

    def test_the_hand_over_shares_no_spot_and_never_moves_in_hafif(self):
        out = run_js("""(() => { const ortak = new Set(); gun('ipuclari', at(8, 59), at(9, 6), 1, (ms, a) => {
            for (const id of ['ceo', 'sus:proje:vitrin']) { const x = a.find((y) => y.id === id); if (!x || !/teslim|götürüyor/.test(x.durum_metni || '')) continue;
              const y = a.find((z) => z !== x && z.yer === x.yer && !z.cikis && z.tur !== 'ozet' && z.id !== 'is:2026-11-12-090000-vitrin');
              if (y) ortak.add(`${x.id}|${y.id}|${x.yer}`); } });
          const hafif = new Set(); gun('ipuclari', at(8, 59), at(9, 6), 2, (ms, a) => { for (const x of a) if (/teslim|götürüyor/.test(x.durum_metni || '')) hafif.add(x.id); }, { hafif: true });
          return { ortak: [...ortak], hafif: [...hafif] }; })()""")
        self.maxDiff = None
        self.assertEqual(out, {"ortak": [], "hafif": []})

    def test_the_sorumlu_meets_the_mudur_when_planning_starts(self):
        out = run_js("""({ toplanti: stintler('kararlar', at(9, 29), at(9, 36), 'sus:proje:atolye', (x) => x.durum_metni === 'Genel Müdürle planı görüşüyor'),
          baska: stintler('kararlar', at(9, 36), at(12), 'sus:proje:atolye', (x) => /görüşüyor/.test(x.durum_metni || '')) })""")
        self.assertEqual(len(out["toplanti"]), 1, out)
        self.assertTrue(out["toplanti"][0]["ulasti"], out)
        self.assertEqual(out["toplanti"][0]["yer"], "yazilim-plan-masa-yan")  # the planning desk in the Yazılım Müdürü's office
        self.assertGreaterEqual(out["toplanti"][0]["son"] - out["toplanti"][0]["bas"], 20000)
        self.assertEqual(out["baska"], [])  # once per planning job: never again while it waits or works on

    def test_the_first_kontrol_failure_shows_a_short_mark(self):
        out = run_js("""(() => { const seq = []; gun('ipuclari', at(9, 24, 50), at(9, 26), 1, (ms, a) => {
            const x = a.find((y) => y.id === 'is:2026-11-12-090000-vitrin'); seq.push(x.simge || '-'); });
          const docs = []; gun('ipuclari', at(9, 24, 50), at(9, 26), 1, (ms, a) => {
            const dr = a.find((y) => y.id === 'sus:revir'); if (dr) docs.push(dr.durum_metni); });
          return { kaldi: seq.filter((x) => x === 'kaldi').length, docs: docs.includes('hastaya bakıyor') }; })()""")
        self.assertTrue(18 <= out["kaldi"] <= 21, out)  # KONTROL_ISARET_MS (20 s)
        self.assertFalse(out["docs"])  # not a red mark: nobody is stuck, no doctor

    def test_review_findings_go_back_to_the_kod_desk(self):
        out = run_js("stintler('ipuclari', at(10, 39), at(10, 43), 'denetci:codex', (x) => x.durum_metni === 'bulguları götürüyor')")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["ulasti"], out)
        self.assertEqual(out[0]["yer"], "ekip-kasa-masa-1-yan")

    def test_the_sekreter_takes_an_answer_to_the_desk_and_files_a_report(self):
        cevap = run_js("stintler('kararlar', at(10, 59), at(11, 4), 'sus:sekreter', (x) => x.durum_metni === 'cevabı götürüyor')")
        rapor = run_js("stintler('ipuclari', at(11, 29), at(11, 33), 'sus:sekreter', (x) => x.durum_metni === 'raporu dosyalıyor')")
        self.assertEqual(len(cevap), 1)
        self.assertTrue(cevap[0]["ulasti"], cevap)
        self.assertRegex(cevap[0]["yer"], r"^(ceo-kapi|.*-yan)$")
        self.assertEqual(len(rapor), 1)
        self.assertTrue(rapor[0]["ulasti"], rapor)

    def test_no_cue_without_its_event(self):
        out = run_js("""(() => { const seen = new Set(); gun('bos-ofis', at(9), at(12), 5, (ms, a) => {
            for (const x of a) if (/teslim|götürüyor|dosyalıyor|görüşüyor|Kontrol geçmedi/.test(x.durum_metni || '')) seen.add(x.id + ':' + x.durum_metni); });
          return [...seen]; })()""")
        self.assertEqual(out, [])


SIRKET = r"""
const ISLER = { plan: 'is:2026-11-12-090000-vitrin-plan', pinc: 'is:2026-11-12-093100-vitrin-pinc',
  kod: 'is:2026-11-12-094600-vitrin-kod', kinc: 'is:2026-11-12-103100-vitrin-kinc' };
const YAZ = 'sus:mudur:yazilim', QA = 'sus:mudur:qa', AN = 'sus:mudur:analist', IT = 'sus:mudur:it';
"""


@unittest.skipUnless(NODE, "node is not installed")
class CompanyStructureTest(unittest.TestCase):
    """Plan "Sonraki iş (9)" step 1 (owner decision 2026-11-13): the four managers are staff NPCs with office hours; communication
    on screen comes only from real events (a new job, a review starting, a plan review, an approval card)."""

    def js(self, expr, timeout=400):
        return run_js(f"(() => {{ {SIRKET}\n return {expr}; }})()", timeout=timeout)

    def test_the_managers_keep_office_hours_and_hafif_hides_them(self):
        out = self.js("""[at(3), at(10), at(10, 0, 0)].map((t, i) => { let a = null;
          gun('bos-ofis', t - 3 * M, t + 1000, 5, (ms, x) => { a = x; }, { hafif: i === 2 });
          return a.filter((x) => x.gorevli === 'mudur' && !x.cikis && !x.otel).map((x) => [x.id, x.etiket]).sort(); })""")
        self.assertEqual(out[0], [])  # at night they are at the Otel
        self.assertEqual(out[1], [["sus:mudur:analist", "Analist Müdürü"], ["sus:mudur:it", "IT Müdürü"],
                                  ["sus:mudur:qa", "QA Müdürü"], ["sus:mudur:yazilim", "Yazılım Müdürü"]])
        self.assertEqual(out[2], [])  # hafif: informational staff are hidden

    def test_a_new_kod_job_goes_ceo_genel_mudur_yazilim_mudur_sorumlu_worker(self):
        out = self.js("""({
          ceo: stintler('ipuclari', at(8, 59), at(9, 8), 'ceo', (x) => x.durum_metni === 'işi teslim ediyor'),
          gm: stintler('ipuclari', at(8, 59), at(9, 8), 'kadro:fable', (x) => x.durum_metni === 'işi teslim ediyor'),
          yaz: stintler('ipuclari', at(8, 59), at(9, 8), YAZ, (x) => x.durum_metni === 'işi teslim ediyor'),
          sor: stintler('ipuclari', at(8, 59), at(9, 8), 'sus:proje:vitrin', (x) => x.durum_metni === 'işi masaya götürüyor') })""")
        for k, yer in (("ceo", "mudur-odasi-masa-yan"), ("gm", "mudurluk-yazilim-masa-yan"), ("yaz", "ekip-vitrin-mudur-ziyaret")):
            with self.subTest(leg=k):
                self.assertEqual(len(out[k]), 1, out)
                self.assertEqual(out[k][0]["yer"], yer)
                self.assertTrue(out[k][0]["ulasti"], out)
        self.assertEqual(len(out["sor"]), 1, out)
        self.assertTrue(out["sor"][0]["ulasti"], out)
        # one leg after the other: nobody hands the file over before it reached them
        self.assertLessEqual(out["ceo"][0]["son"], out["gm"][0]["bas"])
        self.assertLessEqual(out["gm"][0]["son"], out["yaz"][0]["bas"])
        self.assertLessEqual(out["yaz"][0]["son"], out["sor"][0]["bas"])

    def test_a_review_job_goes_to_the_qa_mudur_and_a_plan_review_to_the_analist_mudur(self):
        out = self.js("""({
          qa: stintler('sirket', at(10, 28), at(10, 36), QA, (x) => x.durum_metni === 'işi masaya götürüyor'),
          an: stintler('sirket', at(9, 28), at(9, 36), AN, (x) => x.durum_metni === 'işi masaya götürüyor'),
          sor: stintler('sirket', at(10, 28), at(10, 36), 'sus:proje:vitrin', (x) => /götürüyor|teslim/.test(x.durum_metni || '')) })""")
        for k in ("qa", "an"):
            with self.subTest(dept=k):
                self.assertEqual(len(out[k]), 1, out)
                self.assertTrue(out[k][0]["ulasti"], out)
        self.assertEqual(out["sor"], [])  # a review is not the project team's work: no sorumlu in that chain

    def test_the_qa_mudur_walks_to_the_qa_room_when_a_review_starts(self):
        out = self.js("""({ ip: stintler('ipuclari', at(10, 30), at(10, 45), QA, (x) => x.durum_metni === 'incelemeyi başlatıyor'),
          sk: stintler('sirket', at(10, 30), at(10, 45), QA, (x) => x.durum_metni === 'incelemeyi başlatıyor'),
          bos: stintler('bos-ofis', at(9), at(11), QA, (x) => x.durum_metni === 'incelemeyi başlatıyor') })""")
        for k in ("ip", "sk"):  # a panel review (Codex) and a Claude review
            with self.subTest(senaryo=k):
                self.assertEqual(len(out[k]), 1, out)
                self.assertEqual(out[k][0]["yer"], "qa-mudur-yer")
                self.assertTrue(out[k][0]["ulasti"], out)
                self.assertGreaterEqual(out[k][0]["son"] - out[k][0]["bas"], 20000)
        self.assertEqual(out["bos"], [])

    def test_the_yazilim_mudur_meets_the_analist_mudur_when_the_plan_review_starts(self):
        out = self.js("""({ yaz: stintler('sirket', at(9, 28), at(9, 40), YAZ, (x) => x.durum_metni === 'planı Analist Müdürüyle görüşüyor'),
          an: stintler('sirket', at(9, 28), at(9, 40), AN, (x) => x.durum_metni === 'plan incelemesini görüşüyor'),
          sonra: stintler('sirket', at(9, 40), at(12), YAZ, (x) => /görüşüyor/.test(x.durum_metni || '')) })""")
        self.assertEqual(len(out["yaz"]), 1, out)
        self.assertEqual(out["yaz"][0]["yer"], "mudurluk-analist-ziyaret")
        self.assertTrue(out["yaz"][0]["ulasti"], out)
        self.assertGreaterEqual(out["yaz"][0]["son"] - out["yaz"][0]["bas"], 20000)
        self.assertEqual(len(out["an"]), 1, out)
        self.assertEqual(out["sonra"], [])  # once per plan review

    def test_the_genel_mudur_carries_the_approval_summary_and_the_sekreter_still_brings_the_decision(self):
        out = self.js("""({ gm: stintler('sirket', at(10, 40), at(10, 50), 'kadro:fable', (x) => x.yer === 'ceo-kapi-gm'),
          sek: stintler('sirket', at(10, 40), at(10, 50), 'sus:sekreter', (x) => x.yer === 'ceo-kapi') })""")
        self.assertEqual(len(out["gm"]), 1, out)
        self.assertTrue(out["gm"][0]["ulasti"], out)
        self.assertEqual(len(out["sek"]), 1, out)
        self.assertTrue(out["sek"][0]["ulasti"], out)

    def test_the_planner_writes_in_the_yazilim_office_and_reviews_sit_by_role(self):
        out = self.js("""[[at(9, 10), ISLER.plan], [at(9, 38), ISLER.pinc], [at(10, 35), ISLER.kinc]].map(([t, id]) => { let a = null;
          gun('sirket', t - 2 * M, t + 1000, 2, (ms, x) => { a = x; });
          const x = a.find((y) => y.id === id); return [x.yer, h.rolAdi(x.etiket)]; })""")
        self.assertEqual(out, [["yazilim-plan-masa", "vitrin · Genel Müdür (Yazılım Müdürü adına)"],
                               ["analist-masa-0", "vitrin · İş analisti · Kıdemli"],
                               ["qa-masa-2", "vitrin · Stajyer Tester"]])

    def test_no_cue_shares_a_spot_and_hafif_has_none(self):
        out = self.js("""(() => { const ortak = new Set(), hafif = new Set();
          const cue = /teslim|götürüyor|görüşüyor|başlatıyor/;
          gun('sirket', at(8, 55), at(11, 0), 2, (ms, a) => { for (const x of a) { if (x.cikis || !cue.test(x.durum_metni || '')) continue;
            // (the last carrier hands the file to the job's own robot on its lobby seat, as before)
            const y = a.find((z) => z !== x && z.yer === x.yer && !z.cikis && z.tur !== 'ozet' &&
              !(/götürüyor/.test(x.durum_metni) && z.id.startsWith('is:')));
            if (y) ortak.add(`${x.id}|${y.id}|${x.yer}`); } });
          gun('sirket', at(8, 55), at(11, 0), 5, (ms, a) => { for (const x of a) if (cue.test(x.durum_metni || '') || x.gorevli === 'mudur') hafif.add(x.id); }, { hafif: true });
          return { ortak: [...ortak].slice(0, 5), hafif: [...hafif] }; })()""")
        self.maxDiff = None
        self.assertEqual(out, {"ortak": [], "hafif": []})

    def test_no_company_cue_without_its_event(self):
        out = self.js("""(() => { const seen = new Set(); gun('bos-ofis', at(8), at(19), 10, (ms, a) => {
            for (const x of a) if (/teslim|götürüyor|görüşüyor|başlatıyor|özeti/.test(x.durum_metni || '')) seen.add(x.id + ':' + x.durum_metni); });
          return [...seen]; })()""")
        self.assertEqual(out, [])

    def kart(self, ad, t, id_, veri="{}"):
        return self.js(f"""(() => {{ let a = null, st = null; const t = {t};
          gun('{ad}', t - 3 * M, t + 1000, 2, (ms, x, e, s) => {{ a = x; st = s; }});
          const x = a.find((y) => y.id === '{id_}') || {{ id: '{id_}', tur: 'sus', gorevli: 'mudur', alan: '{id_}'.split(':')[2] }};
          return h.karakterKarti(x, st, t, {{ aktorler: a, veri: {veri} }}); }})()""")

    def test_each_manager_card_shows_its_department_people_and_real_work(self):
        yaz = self.kart("sirket", "at(10)", "sus:mudur:yazilim")
        qa = self.kart("sirket", "at(10, 35)", "sus:mudur:qa")
        an = self.kart("sirket", "at(9, 38)", "sus:mudur:analist")
        it = self.kart("it-uyari", "at(14, 30)", "sus:mudur:it",
                       "{ sistem: { oneriler: [{ metin: 'Docker 2 GB tutuyor' }] } }")
        rows = lambda k: {r["ad"]: r["metin"] for r in k["satirlar"] if r["ad"]}  # noqa: E731
        self.assertEqual((yaz["baslik"], rows(yaz)["Departman"], rows(yaz)["Bağlı olduğu"]), ("Yazılım Müdürü", "Yazılım", "Genel Müdür"))
        self.assertIn("Bildirimler", rows(yaz)["Kod işleri"])
        self.assertIn("Kıdemli (Opus)", rows(yaz)["Kod işleri"])
        self.assertIn("Kod incelemesi", rows(qa)["İncelemeler"])
        self.assertIn("Stajyer Tester", rows(qa)["İncelemeler"])
        self.assertEqual(rows(qa)["Kontrol"], "şu an çalışan Kontrol yok")
        self.assertIn("Plan incelemesi", rows(an)["Plan incelemeleri"])
        self.assertIn("İş analisti", rows(an)["Plan incelemeleri"])
        self.assertIn("1 öneri", rows(it)["Sunucu odası"])
        self.assertEqual(rows(it)["Öneriler"], "Docker 2 GB tutuyor")
        self.assertEqual(rows(it)["Güvenlik bulguları"], "açık güvenlik bulgusu yok")
        self.assertIn("Nöbette", rows(it))
        for k in (yaz, qa, an):
            self.assertTrue(any(e["tur"] == "is" for e in k["eylemler"]), k)

    def test_the_genel_mudur_card_shows_the_org_summary(self):
        out = self.kart("sirket", "at(10, 45)", "kadro:fable")
        rows = {r["ad"]: r["metin"] for r in out["satirlar"] if r["ad"]}
        self.assertEqual(out["baslik"], "Genel Müdür")
        self.assertIn("Yazılım Müdürü (ofiste)", rows["Bağlı müdürler"])
        self.assertIn("Yazılım:", rows["Şirket şu an"])
        self.assertIn("1 akış onay kartı", rows["Onay bekleyen"])

    def test_the_org_chart_is_the_tree_with_real_presence_and_state(self):
        out = self.js("""[at(3), at(9, 38)].map((t) => { let a = null, st = null;
          gun('sirket', t - 3 * M, t + 1000, 2, (ms, x, e, s) => { a = x; st = s; });
          const g = h.orgSemasi(st, t, a);
          const flat = []; const walk = (n, d) => { flat.push([d, n.id, n.ad, n.yer, n.durum, !!(n.aktor || n.kart)]); n.cocuklar.forEach((c) => walk(c, d + 1)); };
          walk(g, 0); return flat; })""")
        gece, gunduz = out
        by = {r[1]: r for r in gunduz}
        self.assertEqual([r[2] for r in gunduz[:3]], ["Selin", "CEO", "Genel Müdür"])
        mudurler = [r for r in gunduz if r[0] == 3]
        self.assertEqual([r[2] for r in mudurler], ["Yazılım Müdürü", "QA Müdürü", "Analist Müdürü", "IT Müdürü",
                                                  "İK ve İdari İşler Müdürü", "Ar-Ge uzmanı"])
        self.assertTrue(all(r[5] for r in mudurler))  # every manager opens its card (also when home)
        self.assertEqual(by["sus:mudur:analist"][3], "ofiste")
        # the Analist odası holds the plan review now (a real actor), the IT team has exactly one on shift
        self.assertIn("is:2026-11-12-093100-vitrin-pinc", by)
        it = [r for r in gunduz if r[1].startswith("sus:sunucu")]
        self.assertEqual([r[3] for r in it].count("nobette"), 1)
        gby = {r[1]: r for r in gece}
        self.assertEqual([gby[f"sus:mudur:{k}"][3] for k in ("yazilim", "qa", "analist", "it")], ["evde"] * 4)
        self.assertIn("IT güvenlik uzmanı", [r[2] for r in gunduz])

    def test_the_org_chart_holds_every_character_of_the_office(self):
        # The owner, 2026-11-13: every staff kind the scene draws and every person kimNerede knows has a node; reviewers by
        # their real state; the İK staff NPC is the İK ve İdari İşler Müdürü
        out = self.js("""[at(3), at(9, 38), at(12, 10), at(20)].map((t) => { let a = null, st = null; const sus = new Set();
          gun('sirket', t - 3 * M, t + 1000, 2, (ms, x, e, s) => { a = x; st = s; x.forEach((y) => { if (y.tur === 'sus') sus.add(y.id); }); });
          const g = h.orgSemasi(st, t, a);
          const ids = []; const walk = (n) => { ids.push(n.id); n.cocuklar.forEach(walk); }; walk(g);
          const k = d.kimNerede(st, t, a);
          return { ids, sus: [...sus], kim: [...k.ofiste, ...k.evde].map((e) => e.id) }; })""")
        for o in out:
            ids = set(o["ids"])
            self.assertEqual(len(o["ids"]), len(ids), "a person appears twice")
            self.assertEqual(sorted(set(o["sus"]) - ids), [])
            self.assertEqual(sorted(set(o["kim"]) - ids), [])

    def test_the_org_chart_reporting_lines(self):
        out = self.js("""[at(3), at(10, 35)].map((t) => { let a = null, st = null;
          gun('sirket', t - 3 * M, t + 1000, 2, (ms, x, e, s) => { a = x; st = s; });
          const g = h.orgSemasi(st, t, a);
          const ust = {}, by = {}; const walk = (n, p) => { ust[n.id] = p; by[n.id] = { ad: n.ad, yer: n.yer, durum: n.durum, alt: n.alt,
            kart: !!(n.aktor || n.kart), cocuklar: n.cocuklar.map((c) => c.id) }; n.cocuklar.forEach((c) => walk(c, n.id)); };
          walk(g, null);
          return { ust, by }; })""")
        gece, gunduz = out
        for o in out:
            ust, by = o["ust"], o["by"]
            self.assertEqual(by["kadro:fable"]["cocuklar"], ["sus:mudur:yazilim", "sus:mudur:qa", "sus:mudur:analist",
                                                             "sus:mudur:it", "sus:ik", "sus:arge"])
            self.assertEqual(by["sus:ik"]["ad"], "İK ve İdari İşler Müdürü")
            self.assertEqual(by["sus:arge"]["ad"], "Ar-Ge uzmanı")
            self.assertTrue(by["sus:ik"]["kart"] and by["sus:arge"]["kart"])
            self.assertEqual(by["sus:ik"]["cocuklar"], ["sekreterler", "guvenlik-ekibi", "sus:muhasebe", "sus:idari",
                                                        "ofis-hizmetleri", "sosyal-ekip"])
            self.assertEqual(by["ofis-hizmetleri"]["cocuklar"], ["sus:cayci", "ascilar", "yemekhane-ekibi", "sus:revir", "sus:psikolog", "sus:masaj"])
            self.assertEqual(len(by["sosyal-ekip"]["cocuklar"]), 14)
            # each shift team: three people, exactly one on shift with its shift, named on the team's line
            for ekip, pre in (("sekreterler", "sus:sekreter"), ("guvenlik-ekibi", "sus:guvenlik"), ("it-ekibi", "sus:sunucu"),
                              ("ascilar", "sus:asci"), ("yemekhane-ekibi", "sus:yemekhane")):
                uyeler = by[ekip]["cocuklar"]
                self.assertEqual([u.startswith(pre) for u in uyeler], [True] * 3)
                nb = [u for u in uyeler if by[u]["yer"] == "nobette"]
                self.assertEqual(len(nb), 1, (ekip, [by[u] for u in uyeler]))
                self.assertRegex(by[nb[0]]["durum"], r"vardiyası · \d\d:\d\d–\d\d:\d\d")
                self.assertEqual(by[ekip]["durum"], f"nöbette: {by[nb[0]]['ad']}")
                self.assertTrue(all(by[u]["kart"] for u in uyeler))
            # the outside reviewers and the hakem under the QA Müdürü
            self.assertEqual(ust["dis-denetciler"], "sus:mudur:qa")
            self.assertEqual(ust["hakem"], "sus:mudur:qa")
            self.assertEqual(by["dis-denetciler"]["cocuklar"], ["denetci:codex", "denetci:glm", "denetci:deepseek", "denetci:antigravity"])
            self.assertEqual(ust["denetci:guvenlik"], "sus:mudur:it")
        # at night the office staff are home, the agents never go home
        self.assertEqual(gece["by"]["sus:ik"]["yer"], "evde")
        self.assertEqual(gece["by"]["denetci:codex"]["yer"], "ofiste")
        self.assertTrue(all(gunduz["by"][f"denetci:{r}"]["durum"] for r in ("codex", "glm", "deepseek", "antigravity")))

    def test_a_reviewer_on_quota_is_home_in_the_chart_and_a_working_one_counts(self):
        out = self.js("""(() => { const t = at(10);
          const st = F.durumOlustur({ ...F.SENARYOLAR.sirket, over: { glm: { durum: 'kota', donus: '2026-11-12T15:00:00' },
            deepseek: { durum: 'calisiyor', calisan: 1 } } }, t);
          const g = h.orgSemasi(st, t, null);
          const by = {}; const walk = (n) => { by[n.id] = [n.yer, n.durum]; n.cocuklar.forEach(walk); }; walk(g);
          return by; })()""")
        # a quota stop is not a hotel stay (review 2026-11-14): its own place 'kota' ("kota doldu"), never 'evde' ("otelde")
        self.assertEqual(out["denetci:glm"][0], "kota")
        self.assertIn("kota doldu", out["denetci:glm"][1])
        self.assertNotIn("otelde", out["denetci:glm"][1])
        self.assertEqual(out["denetci:deepseek"][0], "ofiste")
        self.assertIn("çalışıyor", out["denetci:deepseek"][1])
        self.assertEqual(out["dis-denetciler"][1], "1 inceliyor")
        self.assertEqual(out["hakem"], ["", "incelemede çağrılır"])

    def test_the_genel_mudur_card_names_the_ik_mudur_and_the_arge_uzmani(self):
        out = self.kart("sirket", "at(10, 45)", "kadro:fable")
        rows = {r["ad"]: r["metin"] for r in out["satirlar"] if r["ad"]}
        self.assertIn("İK ve İdari İşler Müdürü (", rows["Bağlı müdürler"])
        self.assertIn("Ar-Ge uzmanı (", rows["Bağlı müdürler"])

    def test_the_page_draws_the_org_chart_with_text_only(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="sema-btn"', html)
        self.assertIn('id="sema"', html)
        block = app[app.index("function semaDugumu"):app.index("function openSema")]
        self.assertIn("orgSemasi(state, Date.now(), prevActors)", block)
        self.assertNotIn("innerHTML", block)
        self.assertIn("openActor(a,", block)
        # the badge words: only the Otel's guests read "otelde"; a quota-stopped reviewer reads "kota doldu"
        self.assertIn("evde: 'otelde'", app)
        self.assertIn("kota: 'kota doldu'", app)
        self.assertIn(".yer-kota", (WEB / "style.css").read_text(encoding="utf-8"))


IT = r"""
// (the IT people staying at the Otel are not on the floor: x.otel)
const itler = (a) => a.filter((x) => x.id.startsWith('sus:sunucu') && !x.otel);
const nobetciler = (a) => itler(a).filter((x) => x.nobetci);
"""


@unittest.skipUnless(NODE, "node is not installed")
class ItTeamTest(unittest.TestCase):
    """The Sunucu odası's IT team (owner decision 2026-11-12): three people on a rotating shift, exactly one on shift."""

    def js(self, expr):
        return run_js(f"(() => {{ {IT}\n return {expr}; }})()")

    def test_exactly_one_on_shift_at_every_minute_of_a_day(self):
        out = self.js("""['bos-ofis', 'it-uyari'].map((ad) => { const bad = []; let n = 0;
          gun(ad, at(0), at(24), 60, (ms, a, emu, st) => { n++;
            const nb = nobetciler(a), v = d.itVardiyasi(ms, st.sahne);
            // (its breakfast / dinner turn on the staff chair, NOBET_SOFRA_SIRASI, 2026-11-14)
            if (nb.length !== 1 || nb[0].id !== d.IT_EKIBI[v.nobetci].id || !['sunucu-masa', 'sunucu-kabin', 'yemekhane-personel-1'].includes(nb[0].yer))
              bad.push([ms, nb.map((x) => x.id + '@' + x.yer)]);
            if (itler(a).length > 3 || new Set(itler(a).map((x) => x.id)).size !== itler(a).length) bad.push([ms, 'dup']); });
          return { ad, n, bad: bad.slice(0, 5) }; })""")
        for o in out:
            self.assertEqual(o["n"], 1440)
            self.assertEqual(o["bad"], [], o["ad"])

    def test_the_night_moves_to_another_person_every_day_and_no_one_works_two_shifts_in_a_row(self):
        out = self.js("""(() => { const s = { saat_dilimi: 'Europe/Istanbul' };
          const geceler = [0, 1, 2].map((k) => d.itVardiyasi(at(3) + k * 24 * H, s).nobetci);
          const sira = []; for (let h = 0; h < 9 * 24; h += 8) sira.push(d.itVardiyasi(at(1) + h * H, s).nobetci);
          const v = d.itVardiyasi(at(9), s);
          return { geceler, sira, v: [v.ad, v.bas === at(8), v.son === at(16), v.sonraki.ad, v.sonraki.bas === at(16)] }; })()""")
        self.assertEqual(sorted(out["geceler"]), [0, 1, 2])  # each takes the night once in three days
        self.assertTrue(all(a != b for a, b in zip(out["sira"], out["sira"][1:])), out["sira"])
        self.assertEqual({out["sira"].count(i) for i in range(3)}, {9})  # an even share of the shifts
        self.assertEqual(out["v"], ["gündüz", True, True, "akşam", True])

    def test_shift_changes_go_through_the_lift(self):
        out = self.js("""[[at(7, 58), at(8, 8)], [at(15, 58), at(16, 8)], [at(23, 58), at(24, 8)]].map(([a, b]) => {
          const gelen = [], giden = [], kaybolan = [];
          let son = null, varan = null;
          gun('bos-ofis', a, b, 1, (ms, ak, emu, st, ev) => {
            for (const e of ev) if (e.id && e.id.startsWith('sus:sunucu')) {
              if (e.t === 'otelden') gelen.push(e.id);
              if (e.t === 'kayboldu') kaybolan.push([e.id, e.yer, e.walking]); }
            for (const x of itler(ak)) if (x.cikis && !giden.includes(x.id)) giden.push(x.id);
            son = ak; varan = emu; });
          const v = d.itVardiyasi(b, { saat_dilimi: 'Europe/Istanbul' });
          const eski = d.IT_EKIBI[v.onceki.kisi].id, e = son.find((x) => x.id === eski);
          return { gelen, giden, kaybolan, yeni: d.IT_EKIBI[v.nobetci].id, eski,
            eskiOtelde: !!e && e.otel && /^otel-oda-\\d+$/.test(e.yer) && varan.arrived(eski) }; })""")
        sabah, ogle, gece = out
        for o in (sabah, ogle, gece):
            self.assertEqual(o["gelen"], [o["yeni"]], o)  # the incoming person walks in from the Otel
            self.assertEqual(o["kaybolan"], [], o)  # nobody vanishes any more
        for o in (sabah, gece):  # the outgoing person walks to its own Otel room and stays there
            self.assertEqual(o["giden"], [o["eski"]], o)
            self.assertTrue(o["eskiOtelde"], o)
        self.assertEqual(ogle["giden"], [])  # 16:00: the day-shift person stays in the office as a colleague

    def test_the_colleague_walks_to_the_hotel_at_its_own_staggered_time(self):
        out = self.js("""(() => { const otele = []; let kim = null;
          gun('bos-ofis', at(16, 0), at(19, 0), 2, (ms, a, emu, st, ev) => {
            const r = itler(a).find((x) => !x.nobetci && !x.cikis); if (r) kim = r.id;
            for (const e of ev) if (e.t === 'otele' && e.id.startsWith('sus:sunucu')) otele.push([e.id, ms]); });
          return { kim, otele, bas: at(18, 10), son: at(18, 55) }; })()""")
        self.assertEqual(len(out["otele"]), 1, out)
        kid, ms = out["otele"][0]
        self.assertEqual(kid, out["kim"])
        self.assertTrue(out["bas"] <= ms <= out["son"], out)

    def test_duty_only_the_on_shift_person_at_the_cabinets_and_one_colleague_helps_in_office_hours(self):
        out = self.js("""(() => { const at_ = (ms) => { let last = null; gun('it-uyari', ms - 300000, ms + 1000, 5, (t, a) => { last = a; }); return last; };
          const ozet = (a) => itler(a).map((x) => [x.nobetci ? 'N' : 'R', x.yer, x.durum_metni, !!x.gorevde]).sort();
          return { gece: ozet(at_(at(2, 30))), geceSakin: ozet(at_(at(3, 30))), gunduz: ozet(at_(at(14, 30))),
            aksam: ozet(at_(at(16, 30))), sonra: ozet(at_(at(17, 30))),
            stint: stintler('it-uyari', at(15, 59), at(17, 1), d.IT_EKIBI[d.itVardiyasi(at(15), {}).nobetci].id, (x) => x.yer === d.SUNUCU_KABIN_YERI_2) }; })()""")
        self.assertEqual(out["gece"], [["N", "sunucu-kabin", "nöbette · uyarı var · kabinlerde", True]])
        self.assertEqual(out["geceSakin"][0][0], "N")
        self.assertEqual(len(out["geceSakin"]), 1)
        self.assertIn(out["geceSakin"][0][2], ("nöbette", "nöbette · kabinleri kontrol ediyor"))
        self.assertEqual(out["gunduz"], [["N", "sunucu-kabin", "nöbette · uyarı var · kabinlerde", True]])
        self.assertEqual(out["aksam"], [["N", "sunucu-kabin", "nöbette · uyarı var · kabinlerde", True],
                                        ["R", "sunucu-kabin-2", "uyarı var · kabinlerde yardım ediyor", True]])
        self.assertFalse(any(r[1].startswith("sunucu-kabin") for r in out["sonra"] if r[0] == "R"))
        self.assertEqual(len(out["stint"]), 1)  # the helper joins once for the warning's length …
        self.assertTrue(out["stint"][0]["ulasti"])  # … and reaches the cabinets

    def test_hafif_shows_only_the_on_shift_person_standing_still(self):
        out = self.js("""(() => { const bad = []; const yer = new Set();
          gun('it-uyari', at(0), at(24), 60, (ms, a, emu, st) => { const i = itler(a);
            const uyari = d.sistemUyarisi(st);
            if (i.length !== 1 || !i[0].nobetci || i[0].yer !== (uyari ? 'sunucu-kabin' : 'sunucu-masa') || i[0].poz !== 'yaziyor') bad.push([ms, i.map((x) => x.id + '@' + x.yer)]);
            yer.add(i[0] && i[0].yer); }, { hafif: true });
          return { bad: bad.slice(0, 5), yer: [...yer].sort() }; })()""")
        self.assertEqual(out["bad"], [])
        self.assertEqual(out["yer"], ["sunucu-kabin", "sunucu-masa"])


NB = r"""
const ekip = (a, g) => a.filter((x) => x.tur === 'sus' && x.gorevli === g && !x.otel); // the floor only (not the Otel)
const nobette = (a, g) => ekip(a, g).filter((x) => x.nobetci);
const TEAMS = { guvenlik: d.GUVENLIK_EKIBI, sekreter: d.SEKRETER_EKIBI };
const S = { saat_dilimi: 'Europe/Istanbul' };
// a decision asked at 03:00 (the night shift's Sekreter takes it to the CEO's door)
F.SENARYOLAR['gece-karar'] = { projects: ['vitrin'], jobs: [], ceo: { state: 'idle' },
  decisions: [{ note: '2026-11-12-vitrin-gece.md', project: 'vitrin', title: 'vitrin — Gece sorusu', asked: at(3), gone: at(5) }] };
"""


@unittest.skipUnless(NODE, "node is not installed")
class ShiftTeamTest(unittest.TestCase):
    """Plan "Sonraki iş (8)" (owner decision 2026-11-12): the guard and the Sekreter are three people each on the IT team's
    rotating 8-hour shifts (one shared helper), the doctor goes home, and the guard's card says who is where."""

    def js(self, expr, timeout=400):
        return run_js(f"(() => {{ {NB}\n return {expr}; }})()", timeout=timeout)

    def test_one_helper_serves_all_three_teams(self):
        out = self.js("""(() => { const ms = at(10, 30);
          return { same: JSON.stringify(d.itVardiyasi(ms, S)) === JSON.stringify(d.vardiya(ms, S)),
            ekipler: Object.keys(d.NOBET_EKIPLERI).sort(),
            it: d.itEkibi(ms, S).map((u) => u.durum), g: d.nobetEkibi('guvenlik', ms, S).map((u) => u.durum),
            s: d.nobetEkibi('sekreter', ms, S).map((u) => u.durum), ids: [...d.GUVENLIK_EKIBI, ...d.SEKRETER_EKIBI].map((u) => u.id) }; })()""")
        self.assertTrue(out["same"])
        self.assertEqual(out["ekipler"], ["asci", "guvenlik", "sekreter", "sunucu", "yemekhane"])  # the kitchen teams since 2026-11-14
        for team in ("g", "s"):
            self.assertEqual(out[team].count("nobette"), 1)
            self.assertNotIn("iceride", out[team])  # no colleague staying on: off shift means home
        self.assertEqual(out["ids"][:3], ["sus:guvenlik", "sus:guvenlik:1", "sus:guvenlik:2"])
        self.assertEqual(out["ids"][3:], ["sus:sekreter", "sus:sekreter:1", "sus:sekreter:2"])

    def test_exactly_one_on_shift_guard_and_secretary_at_every_minute_of_two_days(self):
        out = self.js("""['bos-ofis', 'gece-karar'].map((ad) => { const bad = []; let n = 0; const fazla = [];
          gun(ad, at(0), at(48), 60, (ms, a) => { n++;
            const v = d.vardiya(ms, S);
            for (const g of ['guvenlik', 'sekreter']) {
              const nb = nobette(a, g), e = ekip(a, g);
              if (nb.length !== 1 || nb[0].id !== TEAMS[g][v.nobetci].id) bad.push([ms, g, nb.map((x) => x.id)]);
              if (e.length > 2 || new Set(e.map((x) => x.id)).size !== e.length) bad.push([ms, g, 'dup', e.map((x) => x.id)]);
              if (e.length > 1) fazla.push((ms - v.bas) / 60000); } });
          return { ad, n, bad: bad.slice(0, 5), fazla: Math.max(0, ...fazla) }; })""")
        for o in out:
            self.assertEqual(o["n"], 2880)
            self.assertEqual(o["bad"], [], o["ad"])
            self.assertLess(o["fazla"], 5, o)  # a second person only in the minutes right after a change

    def test_the_rotation_moves_the_night_every_day_across_three_days(self):
        out = self.js("""(() => { const r = {};
          for (const g of ['guvenlik', 'sekreter']) {
            // the Sekreters work on work days only (the work calendar): their three days are Monday to Wednesday
            const o = g === 'sekreter' ? 4 * 24 * H : 0;
            const geceler = [0, 1, 2].map((k) => d.nobetEkibi(g, o + at(3) + k * 24 * H, S).findIndex((u) => u.durum === 'nobette'));
            const sira = []; for (let h = 1; h < 72; h += 8) sira.push(d.nobetEkibi(g, o + at(h), S).findIndex((u) => u.durum === 'nobette'));
            r[g] = { geceler, sira }; }
          return r; })()""")
        for g in ("guvenlik", "sekreter"):
            self.assertEqual(sorted(out[g]["geceler"]), [0, 1, 2])
            sira = out[g]["sira"]
            self.assertTrue(all(a != b for a, b in zip(sira, sira[1:])), sira)
            self.assertEqual([sira.count(i) for i in range(3)], [3, 3, 3])

    def test_shift_changes_go_through_the_lift(self):
        out = self.js("""[[at(7, 58), at(8, 6)], [at(15, 58), at(16, 6)], [at(23, 58), at(24, 6)]].map(([a, b]) => {
          const r = {};
          for (const g of ['guvenlik', 'sekreter']) r[g] = { gelen: [], giden: [], kaybolan: [] };
          let son = null, emu0 = null;
          gun('bos-ofis', a, b, 1, (ms, ak, emu, st, ev) => {
            for (const e of ev) { const x = Object.keys(r).find((g) => e.id === 'sus:' + g || (e.id || '').startsWith('sus:' + g + ':'));
              if (!x) continue;
              if (e.t === 'otelden') r[x].gelen.push(e.id);
              if (e.t === 'kayboldu') r[x].kaybolan.push([e.id, e.yer, e.walking]); }
            for (const g of Object.keys(r)) for (const x of ekip(ak, g)) if (x.cikis && !r[g].giden.includes(x.id)) r[g].giden.push(x.id);
            son = ak; emu0 = emu; });
          const v = d.vardiya(b, S);
          for (const g of Object.keys(r)) { r[g].yeni = TEAMS[g][v.nobetci].id; r[g].eski = TEAMS[g][v.onceki.kisi].id;
            const e = son.find((x) => x.id === r[g].eski);
            r[g].eskiOtelde = !!e && e.otel && /^otel-oda-\\d+$/.test(e.yer) && emu0.arrived(e.id); }
          return r; })""")
        for o in out:
            for g in ("guvenlik", "sekreter"):
                x = o[g]
                self.assertEqual(x["gelen"], [x["yeni"]], x)  # the incoming person walks in from the Otel
                self.assertEqual(x["giden"], [x["eski"]], x)  # the outgoing one walks to its Otel room …
                self.assertEqual(x["kaybolan"], [], x)
                self.assertTrue(x["eskiOtelde"], x)  # … and stays there

    def test_the_night_secretary_takes_a_three_oclock_decision_to_the_ceo_door(self):
        out = self.js("""(() => { const st = stintler('gece-karar', at(2, 55), at(3, 6), 'sus:sekreter', (x) => x.yer === 'ceo-kapi');
          let once = null, sonra = null;
          gun('gece-karar', at(2, 50), at(3, 10), 5, (ms, a) => { const s = nobette(a, 'sekreter')[0];
            if (ms === at(2, 55)) once = [s.yer, s.durum_metni]; if (ms === at(3, 9)) sonra = [s.yer, s.simge]; });
          return { st, once, sonra }; })()""")
        self.assertEqual(len(out["st"]), 1, out)
        self.assertTrue(out["st"][0]["ulasti"], out)
        self.assertEqual(out["once"], ["lobi-resepsiyon", "nöbette"])  # with nothing to do she sits at reception
        self.assertEqual(out["sonra"], ["lobi-resepsiyon", "?"])  # back at reception, the paper in hand

    def test_decisions_queued_at_a_shift_change_are_all_carried_and_never_two_at_the_door(self):
        out = self.js("""(() => { const spec = { projects: ['vitrin'], jobs: [], ceo: { state: 'idle' }, decisions: [
            { note: 'a.md', project: 'vitrin', title: 'A', asked: at(15, 59, 40), gone: at(17) },
            { note: 'b.md', project: 'vitrin', title: 'B', asked: at(15, 59, 40), gone: at(17) },
            { note: 'c.md', project: 'vitrin', title: 'C', asked: at(16, 0, 5), gone: at(17) }] };
          const stints = [], cur = new Map(); let iki = 0;
          gun(spec, at(15, 59), at(16, 6), 1, (ms, a, emu) => {
            const kapida = ekip(a, 'sekreter').filter((x) => x.yer === 'ceo-kapi' && !x.cikis);
            if (kapida.length > 1) iki++;
            for (const x of ekip(a, 'sekreter')) {
              const s = cur.get(x.id);
              if (x.yer === 'ceo-kapi' && !x.cikis) { if (!s) { const n = { id: x.id, ulasti: false }; stints.push(n); cur.set(x.id, n); }
                if (emu.arrived(x.id)) cur.get(x.id).ulasti = true; }
              else cur.delete(x.id); } });
          return { stints, iki }; })()""")
        self.assertEqual(out["iki"], 0, out)  # never two Sekreters on the CEO's door spot
        self.assertEqual(len(out["stints"]), 3, out)  # one trip per decision, across the change
        self.assertTrue(all(s["ulasti"] for s in out["stints"]), out)
        self.assertEqual(len({s["id"] for s in out["stints"]}), 2, out)  # the outgoing one carried one, the incoming the rest

    def test_the_doctor_takes_no_new_case_after_its_leave_time(self):
        out = self.js("""(() => { const git = d.personelGunu('sus:revir', S).git; const t0 = at(0) + git * M;
          const job = (i, end) => ({ note: `2026-11-12-18000${i}-vitrin.md`, project: 'vitrin', title: 'İş ' + i, tier: 'kod',
            model: 'opus', start: at(17), end, outcome: 'tikandi', sessionIdleFor: 3 * H });
          const spec = { ...F.SENARYOLAR['takildi-kirmizi'], jobs: [job(1, t0 - M + 20000), job(2, t0 + 50000)] };
          const geç = []; gun(spec, t0 - 3 * M, t0 + 6 * M, 1, (ms, a) => { const dr = a.find((x) => x.id === 'sus:revir');
            if (dr && dr.durum_metni === 'hastaya bakıyor' && ms > t0 + 45000) geç.push(ms); });
          return geç.length; })()""")
        self.assertEqual(out, 0)

    def test_the_on_shift_guard_keeps_his_duties_and_labels_say_nobette_at_night(self):
        out = self.js("""(() => { const yer = new Set(); let greet = 0;
          gun('bos-ofis', at(8, 0), at(9, 30), 2, (ms, a) => { const g = nobette(a, 'guvenlik')[0]; yer.add(g.yer);
            if (g.durum_metni === 'karşılıyor') greet++; });
          const gece = []; gun('bos-ofis', at(3, 0), at(3, 5), 5, (ms, a) => { for (const g of ['guvenlik', 'sekreter']) {
            const x = nobette(a, g)[0]; gece.push([x.etiket, x.durum_metni]); } });
          return { yer: [...yer], greet, gece: [...new Set(gece.map((x) => x.join('|')))].sort() }; })()""")
        self.assertGreater(out["greet"], 0)
        for y in out["yer"]:
            self.assertIn(y, ("lobi-nobet", "lobi-karsilama", "lobi-su", "lobi-kapi"))
        self.assertIn("Sekreter|nöbette", out["gece"])
        self.assertTrue(any(x.startswith("Güvenlik görevlisi|") for x in out["gece"]), out)
        self.assertTrue(all(x in ("Sekreter|nöbette", "Güvenlik görevlisi|nöbette", "Güvenlik görevlisi|su içiyor",
                                  "Güvenlik görevlisi|kapıya bakıyor") for x in out["gece"]), out)

    def test_hafif_shows_only_the_on_shift_person_standing_still(self):
        out = self.js("""(() => { const bad = [];
          gun('gece-karar', at(0), at(48), 60, (ms, a) => { for (const [g, y] of [['guvenlik', 'lobi-nobet'], ['sekreter', 'lobi-resepsiyon']]) {
            const e = ekip(a, g); if (e.length !== 1 || !e[0].nobetci || e[0].yer !== y) bad.push([ms, g, e.map((x) => x.id + '@' + x.yer)]); } },
            { hafif: true });
          return bad.slice(0, 5); })()""")
        self.assertEqual(out, [])

    def test_who_is_where_agrees_with_the_scene(self):
        out = self.js("""['bos-ofis', 'dort-mesgul', 'gece-karar'].flatMap((ad) => [at(3), at(7, 40), at(10, 30), at(17), at(20), at(23, 30)].map((t) => {
          let a = null, st = null; gun(ad, t - 4 * M, t + 1000, 5, (ms, x, emu, s) => { a = x; st = s; });
          const k = d.kimNerede(st, t, a);
          const sahnede = a.filter((x) => x.tur === 'sus' && !x.cikis && !x.otel).map((x) => x.id).sort();
          const ofiste = k.ofiste.filter((x) => x.id.startsWith('sus:') && x.durum !== 'cikiyor').map((x) => x.id).sort();
          const evde = new Set(k.evde.map((x) => x.id));
          // the Otel (owner decision 2026-11-14): everyone kimNerede has "at home" is drawn at the hotel (or walking there)
          const otelde = new Set(a.filter((x) => x.otel || x.cikis).map((x) => x.id));
          const otelDisi = [...evde].filter((i) => !otelde.has(i));
          const ajan = k.ofiste.filter((x) => !x.id.startsWith('sus:'));
          return { ad, t, fark: [sahnede.filter((i) => !ofiste.includes(i)), ofiste.filter((i) => !sahnede.includes(i))],
            evdeSahnede: sahnede.filter((i) => evde.has(i)), otelDisi,
            ajan: ajan.map((x) => x.id).sort(), ajanEvde: k.evde.filter((x) => !x.id.startsWith('sus:')).length,
            metin: ajan.filter((x) => x.id.startsWith('kadro:')).map((x) => x.metin),
            zaman: k.evde.every((x) => Number.isFinite(x.donus) && x.donus > t && (x.cikis === null || x.cikis <= t)),
            hepsi: k.ofiste.length + k.evde.length }; }))""", timeout=600)
        for o in out:
            with self.subTest(senaryo=o["ad"], t=o["t"]):
                self.assertEqual(o["fark"], [[], []], o)
                self.assertEqual(o["evdeSahnede"], [])
                self.assertEqual(o["otelDisi"], [], o)
                self.assertEqual(o["ajanEvde"], 0)  # agents never go home
                self.assertIn("ceo", o["ajan"])
                self.assertEqual([i for i in o["ajan"] if i.startswith("kadro:")],
                                 ["kadro:fable", "kadro:haiku", "kadro:opus", "kadro:sonnet"])
                self.assertIn("denetci:codex", o["ajan"])
                for m in o["metin"]:
                    self.assertIn(m, ("çalışıyor", "dinleniyor", "uyuyor", "molada", "yemekte", "kota doldu", "hata"))
                self.assertTrue(o["zaman"], o)

    def kart(self, ad, t):
        return self.js(f"""(() => {{ let a = null, st = null; const t = {t};
          gun('{ad}', t - 2 * M, t + 1000, 5, (ms, x, e, s) => {{ a = x; st = s; }});
          const g = nobette(a, 'guvenlik')[0];
          const k = d.kimNerede(st, t, a);
          const hepsi = [...k.ofiste, ...k.evde].map((e) => [e.id, h.kimNeredeMetni(e, t, st.sahne.saat_dilimi)]);
          return {{ k: h.karakterKarti(g, st, t, {{ aktorler: a }}), hepsi, evde: k.evde.length }}; }})()""")

    @staticmethod
    def kim_nerede(rows):
        """The card's who-is-where part: the rows from "Ofiste olanlar" on."""
        ads = [r["ad"] for r in rows]
        return rows[ads.index("Ofiste olanlar"):]

    def test_the_guards_card_groups_who_is_in_and_who_is_home(self):
        out = self.kart("ceo-uyuyor", "at(20)")
        rows = out["k"]["satirlar"]
        ads = [r["ad"] for r in rows]
        self.assertEqual(out["k"]["baslik"], "Güvenlik görevlisi")
        self.assertIn("Nöbette", ads)
        self.assertIn("Sonraki değişim", ads)
        kn = self.kim_nerede(rows)
        self.assertEqual([r["ad"] for r in kn if r["ad"]], ["Ofiste olanlar", "Otelde olanlar"])
        self.assertEqual(kn[[r["ad"] for r in kn].index("Otelde olanlar")]["metin"], f"{out['evde']} kişi")
        metin = [r["metin"] for r in kn]
        self.assertLessEqual(len(kn), 17, metin)  # one line per group, not per person (two kitchen teams since 2026-11-14)
        self.assertTrue(any(re.match(r"^CEO: (dinleniyor|uyuyor|molada)$", m) for m in metin), metin)
        # (all four in one state say it once: "Kadro: Stajyer, Uzman, Kıdemli, Genel Müdür · uyuyor")
        self.assertTrue(any(re.match(r"^Kadro: (Stajyer \w+, Uzman \w+, Kıdemli \w+, Genel Müdür \w+|Stajyer, Uzman, Kıdemli, Genel Müdür · \w+)$", m)
                            for m in metin), metin)
        self.assertTrue(any(m.startswith(("Denetçiler: Codex ", "Denetçiler: Codex, ")) for m in metin), metin)
        self.assertIn("Nöbette: Güvenlik görevlisi (3.), Sekreter (3.), IT uzmanı (2.), Yemekhane görevlisi (3.), Aşçı (3.) · 24:00'e kadar", metin)
        self.assertTrue(any(re.match(r"^Sosyal medya ve tasarım · 14 kişi · döner yarın 08:\d\d–08:\d\d$", m) for m in metin), metin)
        self.assertTrue(any(re.match(r"^Muhasebe, İK, İdari işler · 3 kişi · döner yarın 08:\d\d–08:\d\d$", m) for m in metin), metin)
        self.assertTrue(any(re.match(r"^Proje sorumluları · 1 kişi · döner yarın 08:\d\d$", m) for m in metin), metin)
        self.assertIn("Güvenlik (2 kişi) · sonraki vardiya yarın 00:00 / 16:00", metin)
        self.assertIn("Sekreter (2 kişi) · sonraki vardiya yarın 00:00 / 16:00", metin)
        # a group expands to its members, each with the full line as before ("çıktı … · döner …"); everyone once
        uyeler = [u for r in kn for u in (r.get("uyeler") or [])]
        self.assertEqual(len(uyeler), len(set(uyeler)))
        for i, m in out["hepsi"]:
            if i != "ceo":
                self.assertIn(m, uyeler)
        self.assertEqual(len(uyeler), len(out["hepsi"]) - 1)
        muh = [u for u in uyeler if u.startswith("Muhasebeci · otelde")]
        self.assertEqual(len(muh), 1, uyeler)
        self.assertRegex(muh[0], r"^Muhasebeci · otelde · çıktı 1[78]:\d\d · döner yarın 0[89]:\d\d$")
        self.assertTrue(any(re.match(r"^\d\. güvenlik görevlisi · nöbette · 16:00–24:00$", u) for u in uyeler), uyeler)
        self.assertTrue(any(re.match(r"^\d\. sekreter · otelde · çıktı (dün )?\d\d:00 · döner (yarın )?\d\d:00$", u) for u in uyeler), uyeler)
        self.assertTrue(all(r.get("anahtar") for r in kn if r.get("uyeler")))  # the page keeps an open group open
        self.assertTrue(all(isinstance(r["metin"], str) and "<" not in r["metin"] for r in rows))
        self.assertTrue(all(isinstance(u, str) and "<" not in u for u in uyeler))

    def test_the_grouped_card_by_night_and_by_day(self):
        gece = self.kim_nerede(self.kart("bos-ofis", "at(3)")["k"]["satirlar"])
        m = [r["metin"] for r in gece]
        self.assertLessEqual(len(gece), 17, m)  # (+ the two kitchen teams)
        self.assertIn("Nöbette: Güvenlik görevlisi (1.), Sekreter (1.), IT sorumlusu, Yemekhane görevlisi (1.), Aşçı (1.) · 08:00'e kadar", m)
        self.assertTrue(any(re.match(r"^Sosyal medya ve tasarım · 14 kişi · döner 08:\d\d–08:\d\d$", x) for x in m), m)
        self.assertIn("Güvenlik (2 kişi) · sonraki vardiya 08:00 / 16:00", m)
        self.assertIn("IT (2 kişi) · sonraki vardiya 08:00 / 16:00", m)
        gunduz = self.kim_nerede(self.kart("bos-ofis", "at(10, 30)")["k"]["satirlar"])
        m = [r["metin"] for r in gunduz]
        self.assertLessEqual(len(gunduz), 17, m)  # (+ the two kitchen teams)
        self.assertIn("Sosyal medya ve tasarım: 14 kişi", m)
        self.assertIn("Muhasebe, İK, İdari işler: 3 kişi", m)
        self.assertIn("Nöbette: Güvenlik görevlisi (2.), Sekreter (2.), IT uzmanı (1.), Yemekhane görevlisi (2.), Aşçı (2.) · 16:00'ya kadar", m)
        sos = next(r for r in gunduz if r["metin"].startswith("Sosyal medya"))
        self.assertEqual(len(sos["uyeler"]), 14)
        self.assertTrue(all(" · ofiste · geldi " in u for u in sos["uyeler"]), sos)

    def test_the_dative_of_a_time(self):
        out = self.js("""['00:00', '08:00', '16:00', '24:00', '12:30', '09:00', '10:00', '20:00', '07:45', '06:15', '03:00']
          .map(h.saatYonelme)""")
        self.assertEqual(out, ["00:00'a", "08:00'e", "16:00'ya", "24:00'e", "12:30'a", "09:00'a", "10:00'a", "20:00'ye",
                               "07:45'e", "06:15'e", "03:00'e"])

    def test_the_corner_line_outside_office_hours(self):
        out = self.js("""(() => { let a = null, st = null; gun('bos-ofis', at(20) - M, at(20) + 1000, 5, (ms, x, e, s) => { a = x; st = s; });
          const n = d.kimNerede(st, at(20), a).evde.length;
          const m = (mesai) => ({ ...st, sahne: { ...st.sahne, mesai } });
          return { n, gece: h.mesaiDisiSatiri(st, at(20)), kisa: h.mesaiDisiSatiri(st, at(20), { kisa: true }),
            gunduz: h.mesaiDisiSatiri(st, at(10)), yok: h.mesaiDisiSatiri(m(''), at(20)),
            dokuz: h.mesaiDisiSatiri(m('09:00-17:00'), at(20)), sekiz: h.mesaiDisiSatiri(m('08:00-17:00'), at(20)),
            ek: ['00:00', '01:00', '03:00', '06:00', '08:00', '09:00', '10:00', '12:30', '07:40', '07:45', '07:50', '06:15'].map(h.saatBulunma) }; })()""")
        self.assertEqual(out["gece"], f"Mesai dışı · {out['n']} kişi otelde · 08:30'da dönüyorlar")
        self.assertGreater(out["n"], 10)
        self.assertEqual(out["kisa"], f"Mesai dışı · {out['n']} otelde · 08:30")
        self.assertEqual(out["gunduz"], "")
        self.assertEqual(out["yok"], "")
        self.assertTrue(out["dokuz"].endswith("09:00'da dönüyorlar"), out)
        self.assertTrue(out["sekiz"].endswith("08:00'de dönüyorlar"), out)
        self.assertEqual(out["ek"], ["00:00'da", "01:00'de", "03:00'te", "06:00'da", "08:00'de", "09:00'da", "10:00'da",
                                     "12:30'da", "07:40'ta", "07:45'te", "07:50'de", "06:15'te"])
        app = (WEB / "app.js").read_text(encoding="utf-8")
        css = (WEB / "style.css").read_text(encoding="utf-8")
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mesai-disi"', html)
        self.assertIn("mesaiDisiSatiri(", app)
        self.assertIn("body.panel-acik .mesai-disi", css)


@yavas
@unittest.skipUnless(NODE, "node is not installed")
class DayWalkTest(unittest.TestCase):
    """A whole office day (08:30–18:30, a tick every 2 s) per scenario: nobody shares a spot with the IT team, the guards
    or the Sekreters, and their walking stays calm. One simulated day serves both teams (it used to be two days, one in
    ItTeamTest and one in ShiftTeamTest); one test per scenario, so the runner (test/hepsi.py) can run them side by side."""

    def check(self, ad):
        out = run_js(f"""(() => {{ {IT}\n{NB}\n const ad = '{ad}', step = 2;
          const grup = {{ it: (a) => itler(a), nb: (a) => [...ekip(a, 'guvenlik'), ...ekip(a, 'sekreter')] }};
          const ids = {{ it: (id) => id.startsWith('sus:sunucu'), nb: (id) => /^sus:(guvenlik|sekreter)/.test(id) }};
          const ortak = {{ it: new Set(), nb: new Set() }};
          const emu = gun(ad, at(8, 30), at(18, 30), step, (ms, a) => {{
            for (const g of ['it', 'nb']) for (const x of grup[g](a)) {{ if (x.cikis) continue;
              const y = a.find((z) => z !== x && z.yer === x.yer && !z.cikis && z.tur !== 'ozet');
              if (y) ortak[g].add(`${{x.id}}|${{y.id}}|${{x.yer}}`); }} }});
          const r = {{}};
          for (const g of ['it', 'nb']) {{ const st = new Map();
            for (const [id, s] of [...emu.bitmis, ...[...emu.v].map(([id, v]) => [id, v.stats])]) {{
              if (!ids[g](id)) continue;
              const t = st.get(id) || {{ w: 0, t: 0 }}; t.w += s.walkMs / 1000; t.t += s.ticks * step; st.set(id, t); }}
            r[g] = {{ ortak: [...ortak[g]].slice(0, 5), oran: Math.max(...[...st.values()].map((t) => t.w / Math.max(1, t.t))) }}; }}
          return r; }})()""", timeout=900)
        for g in ("it", "nb"):
            with self.subTest(senaryo=ad, ekip=g):
                self.assertEqual(out[g]["ortak"], [])
                self.assertLessEqual(out[g]["oran"], 0.11, out[g])

    def test_an_empty_office(self):
        self.check("bos-ofis")

    def test_a_server_room_warning(self):
        self.check("it-uyari")

    def test_four_busy_projects(self):
        self.check("dort-mesgul")

    def test_decisions_waiting(self):
        self.check("kararlar")


def run_scene_count(expr, timeout=240):
    """Builds the real web/scene.js Office in node with the fake DOM (test/npc/sahte-dom.mjs) and the vendored three.js;
    `expr` runs with Office, d, F and the helper say(office) (what one frame draws)."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        shutil.copytree(WEB / "vendor", t / "web" / "vendor")
        for f in (t / "web" / "vendor" / "three" / "addons").rglob("*.js"):
            f.write_text(f.read_text(encoding="utf-8").replace("from 'three'", "from '../../three.module.js'"), encoding="utf-8")
        for name in ("ofis-davranis.js", "ofis-sahne.js", "ofis-text.js"):
            shutil.copyfile(WEB / name, t / "web" / name)
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        scene = scene.replace("import * as THREE from 'three';",
                              "import * as THREE0 from './vendor/three/three.module.js'; import { FakeRenderer } from "
                              "'../npc/sahte-dom.mjs'; const THREE = { ...THREE0, WebGLRenderer: FakeRenderer };")
        scene = scene.replace("from 'three/addons/", "from './vendor/three/addons/")
        (t / "web" / "scene.js").write_text(scene, encoding="utf-8")
        (t / "npc").mkdir()
        for name in ("fixtures.mjs", "sahte-dom.mjs"):
            shutil.copyfile(NPC / name, t / "npc" / name)
        uri = lambda n: json.dumps((t / n).as_uri())  # noqa: E731
        code = (f"import {{ el }} from {uri('npc/sahte-dom.mjs')};\nimport {{ Office }} from {uri('web/scene.js')};\n"
                f"import * as d from {uri('web/ofis-davranis.js')};\nimport * as F from {uri('npc/fixtures.mjs')};\n"
                r"""
function say(office) {
  let draw = 0, cast = 0, tri = 0;
  const visible = (o) => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
  office.scene.traverse((o) => { if (!(o.isMesh || o.isSprite) || !visible(o)) return; draw++;
    if (o.isMesh && o.castShadow) cast++;
    const g = o.geometry; tri += g.index ? g.index.count / 3 : (g.attributes.position ? g.attributes.position.count / 3 : 0); });
  return { draw, cast, tri: Math.round(tri) };
}
function ofis(ad, ms, light = false) {
  const spec = F.SENARYOLAR[ad]; const st = F.durumOlustur(spec, ms);
  const plan = d.ofisPlani(st.projects, { max_running_per_project: 1, denetciler: d.denetciListesi(st.modeller) });
  const host = el('div'); el('div').appendChild(host);
  const office = new Office(host, el('div'), { light });
  let prev = null, a = null;
  for (let i = 0; i < 3; i++) { a = d.niyetler(st, ms + i * 1000, prev, { hafif: light, max_running_per_project: 1, plan }); prev = a; }
  office.setActors(a, plan);
  office.setDekor(d.dekorEkibi(plan, a, ms, st.sahne));
  for (let i = 0; i < 5; i++) office.frame();
  return { office, actors: a.length, liste: a };
}
"""
                f"const out = await ({expr});\nprocess.stdout.write(JSON.stringify(out), () => process.exit(0));")
        proc = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=timeout,
                              cwd=tmp, env=dict(os.environ, TZ="UTC"))
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-3000:])
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class ArGeUzmaniTest(unittest.TestCase):
    """The Ar-Ge odası (plan "Sonraki iş (6)"): the Ar-Ge uzmanı works at its desk exactly while an arge job is open (also
    at night), no robot stands for the arge jobs, nobody shares its spot, and the guard's card agrees with the scene."""

    def test_the_uzman_works_exactly_while_the_job_is_open_and_shares_no_spot(self):
        out = run_js("""(() => { const bad = [], ortak = new Set(), robot = new Set(); let gorev = 0, ulasti = 0;
          for (const [a, b] of [[at(1, 50), at(2, 45)], [at(8, 40), at(10, 10)]]) {
            gun('arge-gunu', a, b, 2, (ms, list, emu, st) => {
              const acik = st.tasks.find((t) => t.project === 'arge' && d.ARGE_ACIK.has(t.status));
              const u = list.find((x) => x.id === 'sus:arge');
              if (acik) { gorev++;
                if (!u || u.yer !== 'arge-masa' || !u.gorevde || u.arge_is !== acik.note) bad.push([ms, u && u.yer, acik.status]);
                else if (emu.arrived('sus:arge')) ulasti++;
                if (u && acik.status === 'karar-bekliyor' && u.poz !== 'bekliyor') bad.push([ms, 'poz', u.poz]); }
              else if (u && u.gorevde) bad.push([ms, 'gorevde without a job']);
              for (const x of list) if (x.proje === 'arge') robot.add(x.id);
              if (u && !u.cikis) { const y = list.find((z) => z !== u && z.yer === u.yer && !z.cikis && z.tur !== 'ozet');
                if (y) ortak.add(`${y.id}@${u.yer}`); } }); }
          return { bad: bad.slice(0, 5), ortak: [...ortak], robot: [...robot], gorev, ulasti }; })()""", timeout=400)
        self.assertEqual(out["bad"], [])
        self.assertEqual(out["ortak"], [])
        self.assertEqual(out["robot"], [])
        self.assertGreater(out["gorev"], 0)
        self.assertGreater(out["ulasti"], out["gorev"] * 0.8, out)  # it walks to the desk and stays there

    def test_who_is_where_agrees_with_the_scene(self):
        out = run_js("""[at(2, 15), at(9, 10), at(9, 25), at(11), at(23)].map((t) => {
          let a = null, st = null; gun('arge-gunu', t - 4 * M, t + 1000, 5, (ms, x, emu, s) => { a = x; st = s; });
          const k = d.kimNerede(st, t, a);
          const sahnede = a.filter((x) => x.tur === 'sus' && !x.cikis && !x.otel).map((x) => x.id).sort();
          const ofiste = k.ofiste.filter((x) => x.id.startsWith('sus:') && x.durum !== 'cikiyor').map((x) => x.id).sort();
          const uz = k.ofiste.find((x) => x.id === 'sus:arge');
          return { t, fark: [sahnede.filter((i) => !ofiste.includes(i)), ofiste.filter((i) => !sahnede.includes(i))],
            sorumlu: [...k.ofiste, ...k.evde].some((x) => x.id === 'sus:proje:arge'), uz: uz ? uz.metin || uz.durum : null }; })""",
                     timeout=400)
        for o in out:
            with self.subTest(t=o["t"]):
                self.assertEqual(o["fark"], [[], []], o)
                self.assertFalse(o["sorumlu"])  # the arge workspace has no project sorumlusu
        self.assertEqual(out[0]["uz"], "araştırma işi açık")  # at night, only for the job


@unittest.skipUnless(NODE, "node is not installed")
class DegerlendirmeEkibiTest(unittest.TestCase):
    """The end-of-day review team (bin/gunsonu.py, owner decision 2026-11-13): two staff at two Analist odası desks exactly while
    its work runs (the measurement's minutes, the review job open), never the Ar-Ge uzmanı's job, in the org chart under
    the Analist Müdürü, a card with the last run, and the scene's draw calls stay under the limit."""

    def test_the_team_sits_exactly_while_its_work_runs(self):
        out = run_js("""(() => { const bad = [], arge = []; let calisti = 0, ulasti = 0, bos = 0;
          gun('gun-sonu', at(19, 50), at(21, 10), 5, (ms, list, emu, st) => {
            const dd = d.degerlendirmeDurumu(st, ms);
            const ekip = list.filter((x) => x.gorevli === 'degerlendirme' && !x.cikis);
            if (dd.calisiyor) { calisti++;
              if (ekip.length !== 2 || new Set(ekip.map((x) => x.masa)).size !== 2 || ekip.some((x) => !/^analist-masa-\\d$/.test(x.masa) || !x.gorevde))
                bad.push([ms, ekip.map((x) => x.masa)]);
              if (ekip.length === 2 && ekip.every((x) => emu.arrived(x.id))) ulasti++;
              for (const x of ekip) { const y = list.find((z) => z !== x && !z.cikis && (z.yer === x.masa || z.masa === x.masa)); if (y) bad.push([ms, 'shared', y.id]); }
            } else { bos++; if (ekip.length) bad.push([ms, 'drawn while idle']); }
            const u = list.find((x) => x.id === 'sus:arge');
            if (u && u.arge_is) arge.push(ms);
          });
          const st = F.durumOlustur(F.SENARYOLAR['gun-sonu'], at(20, 32));
          const soru = d.niyetler(st, at(20, 32), null, {}).find((x) => x.id === 'sus:degerlendirme:1');
          const st2 = F.durumOlustur(F.SENARYOLAR['gun-sonu'], at(20, 10));
          const olcum = d.niyetler(st2, at(20, 10), null, {}).filter((x) => x.gorevli === 'degerlendirme').map((x) => [x.etiket, x.durum_metni]);
          const hafif = d.niyetler(F.durumOlustur(F.SENARYOLAR['gun-sonu'], at(20, 25)), at(20, 25), null, { hafif: true })
            .filter((x) => x.gorevli === 'degerlendirme').length;
          return { bad: bad.slice(0, 5), arge, calisti, ulasti, bos, soru: soru && [soru.poz, soru.durum_metni], olcum, hafif }; })()""",
                     timeout=400)
        self.assertEqual(out["bad"], [])
        self.assertEqual(out["arge"], [])  # the review job never seats the Ar-Ge uzmanı
        self.assertGreater(out["calisti"], 0)
        self.assertGreater(out["bos"], 0)
        self.assertGreater(out["ulasti"], out["calisti"] * 0.7, out)  # they walk to the desks and stay there
        self.assertEqual(out["soru"], ["bekliyor", "değerlendirme · Selin'in cevabını bekliyor"])
        self.assertEqual(out["olcum"], [["Ölçüm uzmanı", "günü ölçtü · 20:05"],
                                        ["Değerlendirme uzmanı", "kötü giden 2 durumu not etti"]])
        self.assertEqual(out["hafif"], 2)  # real work: also in hafif

    def test_who_is_where_and_the_org_chart_agree(self):
        out = run_js("""[at(19, 55), at(20, 25), at(22)].map((t) => { let a = null, st = null;
          gun('gun-sonu', t - 4 * M, t + 1000, 5, (ms, x, e, s) => { a = x; st = s; });
          const k = d.kimNerede(st, t, a);
          const sahnede = a.filter((x) => x.gorevli === 'degerlendirme' && !x.cikis).map((x) => x.id).sort();
          const ofiste = k.ofiste.filter((x) => x.id.startsWith('sus:degerlendirme')).map((x) => x.id).sort();
          const g = h.orgSemasi(st, t, a); let an = null;
          const walk = (n) => { if (n.id === 'sus:mudur:analist') an = n; n.cocuklar.forEach(walk); }; walk(g);
          const ekip = an.cocuklar.find((c) => c.id === 'degerlendirme-ekibi');
          return { sahnede, ofiste, ekip: ekip && { ad: ekip.ad, alt: ekip.alt, durum: ekip.durum,
            uyeler: ekip.cocuklar.map((c) => [c.ad, !!(c.aktor || c.kart)]) } }; })""")
        once, during, after = out
        for o in out:
            self.assertEqual(o["sahnede"], o["ofiste"])
            self.assertEqual(o["ekip"]["ad"], "Değerlendirme ekibi")
            self.assertEqual(o["ekip"]["uyeler"], [["Ölçüm uzmanı", True], ["Değerlendirme uzmanı", True]])
        self.assertEqual(once["sahnede"], [])
        self.assertEqual(during["sahnede"], ["sus:degerlendirme:0", "sus:degerlendirme:1"])
        self.assertEqual(during["ekip"]["durum"], "çalışıyor")
        self.assertEqual(after["ekip"]["durum"], "son: 12 Kasım")
        self.assertEqual(once["ekip"]["alt"], "gün sonu · 20:00–24:00")

    def test_the_card_shows_the_last_run_and_opens_the_review_job(self):
        out = run_js("""(() => { let a = null, st = null; const t = at(20, 25);
          gun('gun-sonu', t - 3 * M, t + 1000, 2, (ms, x, e, s) => { a = x; st = s; });
          const x = a.find((y) => y.id === 'sus:degerlendirme:1');
          const k = h.karakterKarti(x, st, t, { aktorler: a, veri: {} });
          const st2 = { ...st, gun_sonu: { acik: false, aktif_dk: 10, son: null, atlananlar: [] } };
          const kapali = h.degerlendirmeKarti(st2, t, {}).satirlar.map((r) => [r.ad, r.metin]);
          return { k, kapali }; })()""")
        k = out["k"]
        rows = {r["ad"]: r["metin"] for r in k["satirlar"] if r["ad"]}
        self.assertEqual(k["baslik"], "Değerlendirme uzmanı")
        self.assertIn("günü ölçer", rows["Görevi"])
        self.assertTrue(rows["Şu an"].startswith("kök nedenleri arıyor · Gün sonu değerlendirmesi"))
        self.assertEqual(rows["Pencere"], "her akşam 20:00–24:00 (bir kez)")
        self.assertEqual(rows["Son değerlendirme"], "12 Kasım · 20:05")
        self.assertEqual(rows["İşler"], "22 bitti · 1 takıldı · Kontrol ilk denemede 18/20")
        self.assertEqual(rows["Kötü giden"], "2 durum")
        self.assertEqual(rows["Not"], "GunSonu-2026-11-12 (Obsidian)")
        self.assertEqual(rows["Değerlendirme işi"], "çalışıyor")
        self.assertEqual(rows["Atlanan günler"], "10 Kasım")
        self.assertEqual(k["eylemler"], [{"tur": "is", "note": "2026-11-12-201000-arge.md", "metin": "Değerlendirme işini aç"}])
        self.assertIn(["Pencere", "kapalı (ofis.json gun_sonu)"], out["kapali"])
        self.assertIn(["Son değerlendirme", "henüz yok"], out["kapali"])


@unittest.skipUnless(NODE, "node is not installed")
class DekorTest(unittest.TestCase):
    """The owner, 2026-11-13: decorative people in the QA odası, the Analist odası and the team bays — purely visual, office
    hours, never on an actor's desk, never in furniture, a group line on the chart, a plain card with real counts."""

    def test_the_seats(self):
        out = run_js("""(() => { const st = F.durumOlustur(F.SENARYOLAR['dort-mesgul'], at(10, 30));
          const plan = d.ofisPlani(st.projects, { max_running_per_project: 1, denetciler: d.denetciListesi(st.modeller) });
          const y = d.dekorYerleri(plan);
          const say = {}; for (const x of y) say[x.oda] = (say[x.oda] || 0) + 1;
          const oda = new Map(plan.odalar.map((r) => [r.id, r]));
          const disarida = y.filter((x) => { const r = oda.get(x.oda); return !(x.x > r.x + 0.8 && x.x < r.x + r.w - 0.8 && x.z > r.z + 0.8 && x.z < r.z + r.d - 0.8); }).map((x) => x.id);
          const masaYanlis = y.filter((x) => x.oturan && !(plan.dugumler[x.yer] && plan.dugumler[x.yer].tur === 'masa' && plan.dugumler[x.yer].oda === x.oda)).map((x) => x.id);
          // a standing one: clear of every place (desks, helper spots, the manager's spot) and of the desks' furniture
          const yakin = [];
          for (const x of y.filter((z) => !z.oturan)) for (const n of Object.values(plan.dugumler)) {
            if (n.oda !== x.oda) continue;
            if (Math.hypot(n.x - x.x, n.z - x.z) < 1.0) yakin.push([x.id, n.id]);
            if (n.tur === 'masa' && Math.hypot(n.x - x.x, n.z + 1.3 - x.z) < 1.9) yakin.push([x.id, n.id, 'masa']); }
          return { say, n: y.length, ayri: new Set(y.map((x) => `${x.x},${x.z}`)).size, disarida, masaYanlis, yakin,
            ayni: JSON.stringify(y) === JSON.stringify(d.dekorYerleri(plan)), projeler: plan.projeler,
            qa: y.filter((x) => x.grup === 'qa').map((x) => x.yer) }; })()""")
        self.assertEqual(out["say"]["qa"], 3, out)
        self.assertEqual(out["say"]["analist"], 3, out)
        for p in out["projeler"]:
            self.assertEqual(out["say"][f"ekip-{p}"], 2, (p, out["say"]))
        self.assertEqual(out["ayri"], out["n"])
        self.assertEqual(out["disarida"], [])
        self.assertEqual(out["masaYanlis"], [])
        self.assertEqual(out["yakin"], [])
        self.assertTrue(out["ayni"])
        self.assertEqual(out["qa"], ["qa-masa-1", "qa-masa-3", None])  # the first desk of each kind stays for real reviews

    def test_office_hours_and_real_desks_first(self):
        out = run_js("""[at(3), at(10, 30), at(15, 59, 58), at(23)].map((ms) => {
          let a = null, st = null, plan = null; gun('dort-mesgul', ms - 4000, ms + 1000, 1, (t, x, emu, s, ev, p) => { a = x; st = s; plan = p; });
          const e = d.dekorEkibi(plan, a, ms, st.sahne);
          const dolu = new Set(a.flatMap((x) => [x.yer, x.masa]).filter(Boolean));
          return { n: e.length, ust: e.filter((x) => x.yer && dolu.has(x.yer)).map((x) => x.id),
            kimde: d.kimNerede(st, ms, a).ofiste.filter((x) => String(x.id).startsWith('dekor')).length,
            aktor: a.filter((x) => String(x.id).startsWith('dekor')).length,
            // an actor on a decorative seat takes it: that one is not shown
            alinan: (() => { const y = d.dekorYerleri(plan).find((x) => x.oturan);
              return d.dekorEkibi(plan, [...a, { id: 'x', yer: y.yer }], ms, st.sahne).some((x) => x.id === y.id); })() }; })""")
        self.assertEqual(out[0]["n"], 0, out)  # 03:00: everyone home
        self.assertEqual(out[3]["n"], 0, out)
        self.assertGreater(out[1]["n"], 10, out)
        self.assertGreater(out[2]["n"], 10, out)
        for o in out:
            self.assertEqual(o["ust"], [], o)
            self.assertEqual((o["kimde"], o["aktor"]), (0, 0), o)  # never a person in the data
            self.assertFalse(o["alinan"], o)

    def test_the_card_and_the_chart(self):
        out = run_js("""(() => { const ms = at(10, 30); const st = F.durumOlustur(F.SENARYOLAR['dort-mesgul'], ms);
          const p = st.projects[0].name;
          const kart = (a) => h.karakterKarti(a, st, ms);
          const g = h.orgSemasi(st, ms, null); const dugumler = [];
          const gez = (n) => { dugumler.push(n); (n.cocuklar || []).forEach(gez); }; gez(g);
          const q = h.bolumIsleri(st, ms, 'qa'), an = h.bolumIsleri(st, ms, 'analist');
          return { qa: kart({ id: 'dekor:qa:0', tur: 'dekor', grup: 'qa' }), an: kart({ id: 'dekor:analist:0', tur: 'dekor', grup: 'analist' }),
            pr: kart({ id: `dekor:proje:${p}:0`, tur: 'dekor', grup: 'proje', proje: p }), p,
            sayi: [q.inceleme.length, q.kontrol.length, an.plan_inceleme.length],
            acik: st.tasks.filter((t) => t.project === p && ['baslatiliyor', 'calisiyor', 'kontrolde', 'incelemede', 'karar-bekliyor'].includes(t.status)).length,
            ekip: dugumler.filter((n) => n.ekip).map((n) => [n.id, n.ekip]),
            kisi: dugumler.filter((n) => /dekor/.test(n.id)).length }; })()""")
        qa = out["qa"]
        self.assertEqual((qa["baslik"], qa["alt"]), ("QA ekibi", "görünüm amaçlı"))
        self.assertIn("gerçek bir çalışan ya da model oturumu değildir", qa["satirlar"][0]["metin"])
        self.assertEqual(qa["satirlar"][1], {"ad": "QA odası şu an", "metin": f"{out['sayi'][0]} inceleme · {out['sayi'][1]} Kontrol"})
        self.assertEqual(out["an"]["satirlar"][1]["metin"], f"{out['sayi'][2]} plan incelemesi")
        self.assertEqual(out["pr"]["baslik"], f"{out['p']} ekibi")
        self.assertEqual(out["pr"]["satirlar"][1]["metin"], f"{out['acik']} açık iş")
        for k in (qa, out["an"], out["pr"]):
            self.assertEqual(k["eylemler"], [])
        ekip = dict(out["ekip"])
        self.assertEqual(ekip["qa-odasi"], "QA ekibi: 3 kişi · görünüm amaçlı")
        self.assertEqual(ekip["analist-odasi"], "Analist ekibi: 3 kişi · görünüm amaçlı")
        self.assertEqual(ekip[f"sus:proje:{out['p']}"], f"{out['p']} ekibi: 2 kişi · görünüm amaçlı")
        self.assertEqual(out["kisi"], 0)  # group lines only, never a box per person
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("office.setDekor(dekorEkibi(plan, actors, Date.now(), state.sahne));", app)
        self.assertIn("h('span', 'sema-ekip', n.ekip)", app)

    def test_two_draw_calls_for_all_of_them_none_at_night_and_a_click_opens_the_card(self):
        out = run_scene_count("""(() => { const r = {};
          for (const [k, ms, light] of [['gun', F.at(10, 30), false], ['gece', F.at(3), false], ['hafif', F.at(10, 30), true]]) {
            const { office } = ofis('dort-mesgul', ms, light);
            const vis = (o) => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
            let draw = 0, inst = 0, cast = 0, yaya = 0, yayaCast = 0;
            // (the robots' instanced legs and arms are no decorative people; the street's pedestrians, 2026-11-14, are
            // counted on their own: two draw calls of their own, none in hafif)
            const Y = office.yaya ? [office.yaya.govde, office.yaya.bacak] : [];
            office.world.traverse((o) => { if (!o.isInstancedMesh || !vis(o) || o === office.bacak || o === office.kol) return;
              if (Y.includes(o)) { yaya++; if (o.castShadow) yayaCast++; return; }
              draw++; inst += o.count; if (o.castShadow) cast++; });
            r[k] = { draw, inst, cast, yaya, yayaCast, yayaN: office.yaya ? office.yaya.n : 0, list: office.dekor ? office.dekor.list.length : 0 };
            if (k === 'gun') { // a click on one: its plain card through onActor
              let got = null; office.onActor = (a) => { got = a; };
              const D = office.dekor; const i = 0;
              const hit = { object: D.govde, instanceId: i, distance: 1 };
              office.raycaster.intersectObjects = () => [hit];
              office.pick({ clientX: 10, clientY: 10 });
              r.tik = got; r.ilk = D.list[i].id;
              const m = new office.tmp.constructor(); const M4 = D.m.clone(); D.govde.getMatrixAt(0, M4); m.setFromMatrixPosition(M4);
              r.konum = [m.x - D.list[0].x, m.z - D.list[0].z];
            } }
          return r; })()""")
        self.assertEqual(out["gun"]["draw"], 2, out)  # the bodies, and the legs of the standing ones
        self.assertEqual(out["gun"]["cast"], 0, out)
        self.assertGreater(out["gun"]["list"], 10, out)
        self.assertEqual(out["gece"]["draw"], 0, out)
        self.assertEqual(out["hafif"]["draw"], 2, out)
        # the pedestrians: two draw calls for all of them by day and by night (fewer walk at night), none in hafif
        for k, n in (("gun", 8), ("gece", 2), ("hafif", 0)):
            self.assertEqual((out[k]["yaya"], out[k]["yayaN"], out[k]["yayaCast"]), (2 if n else 0, n, 0), (k, out[k]))
        self.assertEqual(out["tik"], {"id": out["ilk"], "tur": "dekor", "grup": out["tik"]["grup"],
                                      "proje": out["tik"]["proje"], "etiket": ""})
        for v in out["konum"]:
            self.assertAlmostEqual(v, 0, places=4)


@unittest.skipUnless(NODE, "node is not installed")
class WorkCalendarTest(unittest.TestCase):
    """The work calendar (owner decision 2026-11-13): weekends and Turkish public holidays are days off for the day-hours staff
    and the Sekreters; the guards and the IT team keep their 24/7 rotation; agents and real work are never affected."""

    def js(self, expr, timeout=400):
        return run_js("(() => { const gunMs = (y, mo, dd, hh = 0, mi = 0) => Date.UTC(y, mo - 1, dd, hh - 3, mi);\n"
                      "const ymd = (s) => { const [y, m, g] = s.split('-').map(Number); return { yil: y, ay: m, gun: g }; };\n"
                      f"return ({expr}); }})()", timeout=timeout)

    def test_weekdays_weekends_and_holidays(self):
        days = ["2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-10-29", "2026-12-31", "2027-01-01",
                "2026-04-23", "2026-05-01", "2026-05-19", "2026-07-15", "2026-08-30", "2029-10-29", "2029-01-01",
                "2026-03-19", "2026-03-20", "2026-03-22", "2026-03-23", "2026-05-26", "2026-05-27", "2026-05-29",
                "2026-05-30", "2026-06-01", "2027-03-08", "2027-03-09", "2027-03-11", "2027-03-12", "2027-05-15",
                "2027-05-16", "2027-05-17", "2027-05-19", "2027-05-20", "2028-02-25", "2028-02-26", "2028-02-28",
                "2028-02-29", "2028-05-04", "2028-05-05", "2028-05-08", "2028-05-09"]
        out = self.js(f"""Object.fromEntries({json.dumps(days)}.map((x) => [x, (({{ tur, ad }}) => `${{tur}}|${{ad}}`)(d.gunTuru(ymd(x)))]))""")
        want = {"2026-11-13": "is|", "2026-11-14": "hafta-sonu|", "2026-11-15": "hafta-sonu|", "2026-11-16": "is|",
                "2026-10-29": "tatil|Cumhuriyet Bayramı", "2026-12-31": "is|", "2027-01-01": "tatil|Yılbaşı",
                "2026-04-23": "tatil|Ulusal Egemenlik ve Çocuk Bayramı", "2026-05-01": "tatil|Emek ve Dayanışma Günü",
                "2026-05-19": "tatil|Atatürk'ü Anma, Gençlik ve Spor Bayramı", "2026-07-15": "tatil|Demokrasi ve Millî Birlik Günü",
                "2026-08-30": "tatil|Zafer Bayramı", "2029-10-29": "tatil|Cumhuriyet Bayramı", "2029-01-01": "tatil|Yılbaşı",
                # arife stays a work day (documented choice); the bayram days per Diyanet's tables
                "2026-03-19": "is|", "2026-03-20": "tatil|Ramazan Bayramı", "2026-03-22": "tatil|Ramazan Bayramı",
                "2026-03-23": "is|", "2026-05-26": "is|", "2026-05-27": "tatil|Kurban Bayramı",
                "2026-05-29": "tatil|Kurban Bayramı", "2026-05-30": "tatil|Kurban Bayramı", "2026-06-01": "is|",
                "2027-03-08": "is|", "2027-03-09": "tatil|Ramazan Bayramı", "2027-03-11": "tatil|Ramazan Bayramı",
                "2027-03-12": "is|", "2027-05-15": "hafta-sonu|", "2027-05-16": "tatil|Kurban Bayramı",
                "2027-05-17": "tatil|Kurban Bayramı", "2027-05-19": "tatil|Kurban Bayramı", "2027-05-20": "is|",
                "2028-02-25": "is|", "2028-02-26": "tatil|Ramazan Bayramı", "2028-02-28": "tatil|Ramazan Bayramı",
                "2028-02-29": "is|", "2028-05-04": "is|", "2028-05-05": "tatil|Kurban Bayramı",
                "2028-05-08": "tatil|Kurban Bayramı", "2028-05-09": "is|"}
        self.assertEqual(out, want)

    def test_year_boundary_and_the_next_work_day(self):
        out = self.js("""({ yilSonu: d.isGunuMu(gunMs(2026, 12, 31, 23, 59)), yilbasi: d.isGunuMu(gunMs(2027, 1, 1, 0, 1)),
          tatil: d.tatilAdi(gunMs(2027, 1, 1, 0, 1)),
          sonraki: [ymd('2026-12-31'), ymd('2027-05-14'), ymd('2026-10-28'), ymd('2026-11-13'), ymd('2026-11-16')]
            .map((x) => d.sonrakiIsGunu(x)).map((t) => `${t.yil}-${t.ay}-${t.gun}`) })""")
        self.assertEqual(out["yilSonu"], True)
        self.assertEqual(out["yilbasi"], False)
        self.assertEqual(out["tatil"], "Yılbaşı")
        self.assertEqual(out["sonraki"], ["2027-1-4", "2027-5-20", "2026-10-30", "2026-11-16", "2026-11-17"])

    def test_office_hours_and_staff_follow_the_calendar(self):
        out = self.js("""(() => { const s = { saat_dilimi: 'Europe/Istanbul' };
          const cmt = gunMs(2026, 11, 14, 10), cuma = gunMs(2026, 11, 13, 10);
          return { mesai: [d.mesaiMi(cuma, s), d.mesaiMi(cmt, s), d.mesaiMi(cmt, { ...s, mesai: '' })],
            ik: [d.personelSaati('sus:ik', cuma, s), d.personelSaati('sus:ik', cmt, s), d.personelSaati('sus:ik', cmt, { ...s, mesai: '' })],
            tatil: d.personelSaati('sus:muhasebe', gunMs(2026, 10, 29, 11), s) }; })()""")
        self.assertEqual(out["mesai"], [True, False, True])  # no office hours (the demo): no calendar either
        self.assertEqual(out["ik"], ["iceride", "evde", "iceride"])
        self.assertEqual(out["tatil"], "evde")

    def test_return_texts_after_a_friday_and_before_a_holiday(self):
        out = self.js("""(() => { const st = (ms) => F.durumOlustur(F.SENARYOLAR['bos-ofis'], ms);
          const tz = 'Europe/Istanbul';
          const satir = (ms, id) => { const k = d.kimNerede(st(ms), ms); return h.kimNeredeMetni(k.evde.find((e) => e.id === id), ms, tz); };
          const cuma = gunMs(2026, 11, 13, 20), cmt = gunMs(2026, 11, 14, 11), paz = gunMs(2026, 11, 15, 15);
          const arife = gunMs(2026, 10, 28, 20), tatil = gunMs(2026, 10, 29, 11), pzt = gunMs(2026, 11, 16, 3), per = gunMs(2026, 11, 12, 20);
          const n = (ms) => d.kimNerede(st(ms), ms).evde.length;
          const kose = (ms, o) => h.mesaiDisiSatiri(st(ms), ms, o);
          return { muh: [satir(cuma, 'sus:muhasebe'), satir(cmt, 'sus:muhasebe'), satir(arife, 'sus:muhasebe'), satir(per, 'sus:muhasebe')],
            n: [n(cuma), n(cmt), n(paz), n(tatil), n(per)],
            kose: [kose(cuma), kose(cmt), kose(cmt, { kisa: true }), kose(paz), kose(arife), kose(tatil), kose(pzt), kose(per)],
            sekreter: h.nobetSatirlari('sekreter', st(cmt), cmt).map((r) => `${r.ad}: ${r.metin}`).slice(0, 2),
            kart: h.kimNeredeSatirlari(d.kimNerede(st(cuma), cuma), cuma, tz).map((r) => r.metin)
              .filter((m) => /^Muhasebe, İK/.test(m)) }; })()""")
        self.assertRegex(out["muh"][0], r"^Muhasebeci · otelde · çıktı 1[78]:\d\d · döner pazartesi 0[89]:\d\d$")
        self.assertRegex(out["muh"][1], r"^Muhasebeci · otelde · çıktı dün 1[78]:\d\d · döner pazartesi 0[89]:\d\d$")
        self.assertRegex(out["muh"][2], r"^Muhasebeci · otelde · çıktı 1[78]:\d\d · döner 30 Ekim Cuma 0[89]:\d\d$")
        self.assertRegex(out["muh"][3], r"^Muhasebeci · otelde · çıktı 1[78]:\d\d · döner yarın 0[89]:\d\d$")
        n = out["n"]
        self.assertEqual(out["kose"], [
            f"Mesai dışı · {n[0]} kişi otelde · pazartesi 08:30'da dönüyorlar",
            f"Hafta sonu · {n[1]} kişi otelde · pazartesi 08:30'da dönüyorlar",
            f"Hafta sonu · {n[1]} otelde · Pzt 08:30",
            f"Hafta sonu · {n[2]} kişi otelde · pazartesi 08:30'da dönüyorlar",
            out["kose"][4], f"Resmî tatil (29 Ekim) · {n[3]} kişi otelde · cuma 08:30'da dönüyorlar",
            out["kose"][6], f"Mesai dışı · {n[4]} kişi otelde · 08:30'da dönüyorlar"])
        self.assertTrue(out["kose"][4].endswith("· 30 Ekim Cuma 08:30'da dönüyorlar"), out["kose"][4])
        self.assertTrue(out["kose"][6].startswith("Mesai dışı · ") and out["kose"][6].endswith(" 08:30'da dönüyorlar")
                        and "pazartesi" not in out["kose"][6], out["kose"][6])
        self.assertGreater(n[1], n[0])  # the Sekreters are home on Saturday too
        self.assertEqual(out["sekreter"][0], "Nöbette: kimse yok · hafta sonu")
        self.assertRegex(out["sekreter"][1], r"^Sonraki değişim: pazartesi 00:00 · \d\. sekreter gelir \(gece vardiyası\)$")
        self.assertTrue(out["kart"] and all("döner pazartesi" in m for m in out["kart"]), out["kart"])

    def test_guards_and_it_rotate_on_weekends_secretaries_and_day_staff_do_not(self):
        out = self.js("""(() => { const s = { saat_dilimi: 'Europe/Istanbul' };
          const say = (ekip, ms) => d.nobetEkibi(ekip, ms, s).filter((u) => u.durum === 'nobette').length;
          const cmt = gunMs(2026, 11, 14, 11), paz = gunMs(2026, 11, 15, 3), pzt = gunMs(2026, 11, 16, 0, 30);
          const cumaAksam = gunMs(2026, 11, 13, 23, 30), bayram = gunMs(2026, 5, 28, 12);
          let a = null; gun('bos-ofis', paz + 11 * H - 3 * M, paz + 11 * H + 1000, 5, (ms, x) => { a = x; });
          const sus = a.filter((x) => x.tur === 'sus' && !x.cikis && !x.otel);
          return { sayi: [cmt, paz, pzt, cumaAksam, bayram].map((ms) => [say('guvenlik', ms), say('sunucu', ms), say('sekreter', ms)]),
            nobetci: [cmt, paz].map((ms) => d.nobetEkibi('guvenlik', ms, s).findIndex((u) => u.durum === 'nobette')),
            sahne: sus.map((x) => x.gorevli).sort() }; })()""")
        self.assertEqual(out["sayi"], [[1, 1, 0], [1, 1, 0], [1, 1, 1], [1, 1, 1], [1, 1, 0]])
        self.assertNotEqual(out["nobetci"][0], -1)
        # Sunday 11:00: only the people on shift are on the floor (guard, IT and the kitchen's server and cook)
        self.assertEqual(out["sahne"], ["asci", "guvenlik", "sunucu", "yemekhane"])  # the kitchen teams too (2026-11-14)

    def test_an_agent_with_a_real_job_still_comes_on_saturday(self):
        out = self.js("""(() => { const cmt = gunMs(2026, 11, 14, 11);
          const spec = { ...F.SENARYOLAR['tek-proje-ceo-bosta'], jobs: [{ note: '2026-11-14-110000-vitrin.md', project: 'vitrin',
            title: 'Cumartesi işi', tier: 'kod', model: 'opus', start: cmt - 10 * M, end: cmt + H }] };
          let a = null, plan = null; gun(spec, cmt - 5 * M, cmt + 1000, 5, (ms, x, e, st, ev, p) => { a = x; plan = p; });
          const is = a.find((x) => x.tiklama && /110000-vitrin/.test(x.tiklama.note || ''));
          return { is: is ? [is.poz, is.masa ? 'masa' : ''] : null,
            dekor: d.dekorEkibi(plan, a, cmt, { saat_dilimi: 'Europe/Istanbul' }).length,
            dekorCuma: d.dekorEkibi(plan, [], gunMs(2026, 11, 13, 11), { saat_dilimi: 'Europe/Istanbul' }).length }; })()""")
        self.assertEqual(out["is"], ["yaziyor", "masa"])
        self.assertEqual(out["dekor"], 0)  # the decorative people stay home on Saturday
        self.assertGreater(out["dekorCuma"], 0)


@unittest.skipUnless(NODE, "node is not installed")
class NightSleepTest(unittest.TestCase):
    """The owner, 2026-11-13: at night everyone in the office off shift and without real work sleeps in a bed of the
    Dinlenme odası (20 beds, one each); the guard, the Sekreter and the IT person on shift stay awake at their duties."""

    def gece(self, spec, t0, t1, hafif=False):
        return run_js(f"""(() => {{ const spec = {spec}; let a = null, emu = null, st = null, plan = null;
          gun(spec, {t0}, {t1}, 5, (ms, x, e, s, ev, p) => {{ a = x; emu = e; st = s; plan = p; }}, {{ hafif: {'true' if hafif else 'false'} }});
          const k = d.kimNerede(st, {t1} - 5000, a);
          return {{ ajan: a.filter((x) => x.tur === 'ajan' || x.id === 'ceo')
              .map((x) => ({{ id: x.id, yer: x.yer, poz: x.poz, metin: x.durum_metni, vardi: emu.arrived(x.id), not: (x.tiklama || {{}}).note || '',
                tur: (plan.dugumler[x.yer] || {{}}).tur || '', oda: (plan.dugumler[x.yer] || {{}}).oda || '' }})),
            sus: a.filter((x) => x.tur === 'sus' && !x.cikis && !x.otel).map((x) => ({{ id: x.id, g: x.gorevli, poz: x.poz, nobetci: !!x.nobetci, yer: x.yer }})),
            otel: a.filter((x) => x.otel).map((x) => ({{ id: x.id, yer: x.yer, poz: x.poz, metin: x.durum_metni, vardi: emu.arrived(x.id) }})),
            kim: k.ofiste.filter((e) => e.grup === 'ajan').map((e) => [e.ad, e.metin]),
            guard: h.kimNeredeSatirlari(k, {t1} - 5000, 'Europe/Istanbul').flatMap((r) => [r.metin, ...(r.uyeler || [])]) }}; }})()""")

    def test_with_no_work_everyone_off_shift_sleeps_in_their_own_bed(self):
        out = self.gece("F.SENARYOLAR['bos-ofis']", "at(2, 40)", "at(3, 0)")
        ajan = out["ajan"]
        ids = {x["id"] for x in ajan}
        for i in ("ceo", "kadro:haiku", "kadro:sonnet", "kadro:opus", "kadro:fable", "denetci:codex", "denetci:glm",
                  "denetci:deepseek", "denetci:antigravity"):
            self.assertIn(i, ids)
        for x in ajan:
            with self.subTest(ajan=x["id"]):
                self.assertRegex(x["yer"], r"^dinlenme-yatak-\d+$")
                self.assertEqual(x["poz"], "yatiyor")
                self.assertEqual(x["metin"], "uyuyor")
                self.assertTrue(x["vardi"], x)  # it walked there and lies in the bed
        yerler = [x["yer"] for x in ajan]
        self.assertEqual(len(yerler), len(set(yerler)))  # one sleeper per bed
        # the Otel (owner decision 2026-11-14): everyone off shift of the staff sleeps there, each in its own room, hidden inside
        otel = out["otel"]
        self.assertGreaterEqual(len(otel), 30, otel)
        self.assertEqual(len({x["yer"] for x in otel}), len(otel))
        for x in otel:
            with self.subTest(otel=x["id"]):
                self.assertRegex(x["yer"], r"^otel-oda-\d+$")
                self.assertEqual((x["poz"], x["metin"]), ("otelde", "otelde · uyuyor"))
                self.assertTrue(x["vardi"], x)
        # awake: exactly the ones on shift (guard, Sekreter, IT, the kitchen's server and cook), at their posts
        self.assertEqual(sorted(x["g"] for x in out["sus"]), ["asci", "guvenlik", "sekreter", "sunucu", "yemekhane"])
        self.assertTrue(all(x["nobetci"] and x["poz"] != "yatiyor" for x in out["sus"]), out["sus"])
        # who-is-where: every agent "uyuyor"; the security reviewer is not "çalışıyor" without a real review (bug fix)
        self.assertTrue(all(m == "uyuyor" for _, m in out["kim"]), out["kim"])
        self.assertIn(["Güvenlik denetçisi", "uyuyor"], out["kim"])
        self.assertFalse(any("Güvenlik denetçisi · ofiste · çalışıyor" in m for m in out["guard"]), out["guard"])

    AJANLAR = ("ceo", "kadro:haiku", "kadro:sonnet", "kadro:opus", "kadro:fable", "denetci:codex", "denetci:glm",
               "denetci:deepseek", "denetci:antigravity")
    # the leisure rooms of a day off (owner decision 2026-11-14): never a desk, never a bed
    ORTAK = {"ortak-alan", "cay-ocagi", "oyun", "spor", "sigara", "masaj", "wc", "dus", "yemekhane", "koridor", ""}

    def assert_awake_in_the_common_areas(self, out, soz):
        ajan = out["ajan"]
        self.assertTrue(set(self.AJANLAR) <= {x["id"] for x in ajan}, ajan)
        for x in ajan:
            with self.subTest(ajan=x["id"]):
                self.assertNotIn(x["tur"], ("masa", "mudur-masasi", "yatak"), x)  # not at a work desk, not in a bed
                self.assertNotIn(x["poz"], ("yatiyor", "uyuyor"), x)
                self.assertNotIn("uyuyor", x["metin"], x)
                self.assertTrue(x["metin"].startswith(f"{soz} · "), x)
                self.assertNotRegex(x["metin"], r"· (hazır|boşta) ·", x)
        self.assertEqual(len({x["yer"] for x in ajan}), len(ajan))  # nobody shares a spot
        self.assertFalse(any(m == "uyuyor" for _, m in out["kim"]), out["kim"])

    def test_on_saturday_daytime_the_agents_are_awake_in_the_common_areas(self):
        # Owner decision 2026-11-14 (Saturday 10:22): "ofiste olanlar halen uyuyor" — by day on a day off they are awake
        out = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 10)", "at(48 + 10, 30)")
        self.assert_awake_in_the_common_areas(out, "hafta sonu")
        for x in out["ajan"]:
            self.assertTrue(x["tur"] == "koridor" or x["oda"] in self.ORTAK, x)
        # leisure: several of them play, drink, chat or read — not everyone resting in one place
        self.assertGreaterEqual(len({x["poz"] for x in out["ajan"]}), 3, out["ajan"])
        self.assertEqual(sorted(x["g"] for x in out["sus"]), ["asci", "guvenlik", "sunucu", "yemekhane"])  # no Sekreter at the weekend
        # the day staff and all three Sekreters spend Saturday at the Otel, awake by day ("otelde")
        self.assertTrue({"sus:sekreter", "sus:sekreter:1", "sus:sekreter:2", "sus:muhasebe"} <= {x["id"] for x in out["otel"]})
        self.assertEqual({x["metin"] for x in out["otel"]}, {"otelde"})
        self.assertIn(["Güvenlik denetçisi", "dinleniyor"], out["kim"])

    def test_on_saturday_daytime_in_hafif_too(self):
        out = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 10)", "at(48 + 10, 30)", hafif=True)
        self.assert_awake_in_the_common_areas(out, "hafta sonu")

    def test_on_a_holiday_daytime_too_and_the_busy_office(self):
        # 29 Ekim 2026 (Cumhuriyet Bayramı, a Thursday): the same as a weekend, with "tatil"
        out = self.gece("F.SENARYOLAR['dort-mesgul']", "at(-14 * 24 + 15)", "at(-14 * 24 + 15, 30)")
        self.assert_awake_in_the_common_areas(out, "tatil")

    def test_on_saturday_night_they_sleep_in_their_beds(self):
        out = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 23)", "at(48 + 23, 30)")
        for x in out["ajan"]:
            with self.subTest(ajan=x["id"]):
                self.assertRegex(x["yer"], r"^dinlenme-yatak-\d+$")
                self.assertEqual((x["poz"], x["metin"]), ("yatiyor", "uyuyor"))
                self.assertTrue(x["vardi"], x)
        # and they wake up at the work days' hour: before 08:30 asleep, after it awake
        once = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 8)", "at(48 + 8, 25)")
        self.assertTrue(all(x["poz"] == "yatiyor" for x in once["ajan"]), once["ajan"])
        sonra = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 8, 20)", "at(48 + 8, 45)")
        self.assertFalse(any(x["poz"] == "yatiyor" for x in sonra["ajan"]), sonra["ajan"])
        # bedtime is after dinner (20:00, meals 2026-11-14): awake at 18:45, asleep at 20:30
        aksam = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 18, 20)", "at(48 + 18, 45)")
        self.assertFalse(any(x["poz"] == "yatiyor" for x in aksam["ajan"]), aksam["ajan"])
        yatma = self.gece("F.SENARYOLAR['bos-ofis']", "at(48 + 20, 5)", "at(48 + 20, 30)")
        self.assertTrue(all(x["poz"] == "yatiyor" for x in yatma["ajan"]), yatma["ajan"])

    def test_a_real_job_on_saturday_daytime_takes_its_character_to_its_desk(self):
        out = run_js("""(() => { const spec = { ...F.SENARYOLAR['tek-proje-ceo-bosta'], jobs: [{ note: '2026-11-14-103000-vitrin.md',
            project: 'vitrin', title: 'Cumartesi işi', tier: 'kod', model: 'opus', start: at(48 + 10, 30), end: at(48 + 11, 30),
            sessionIdleFor: 0 }] };
          const iz = [];
          gun(spec, at(48 + 10), at(48 + 10, 50), 5, (ms, a, emu) => {
            const w = a.find((x) => x.tiklama && /103000-vitrin/.test(x.tiklama.note || '') && x.tur === 'ajan' && !x.cikis);
            const k = a.find((x) => x.id === 'kadro:opus');
            if (ms === at(48 + 10, 25) || ms === at(48 + 10, 45)) iz.push({ w: w ? [w.poz, w.masa && w.yer === w.masa, emu.arrived(w.id), w.durum_metni] : null,
              k: k ? [k.poz, k.durum_metni] : null }); });
          return iz; })()""")
        once, sirada = out
        self.assertIsNone(once["w"])
        self.assertTrue(once["k"][1].startswith("hafta sonu · "), once)  # awake before the job
        self.assertIsNone(sirada["k"])  # its body works the job (devral) …
        self.assertEqual(sirada["w"][:3], ["yaziyor", True, True])  # … at its desk, typing

    def test_a_real_job_at_night_wakes_its_character_and_it_goes_back_to_bed(self):
        out = run_js("""(() => { const spec = { ...F.SENARYOLAR['tek-proje-ceo-bosta'], jobs: [{ note: '2026-11-12-030000-vitrin.md',
            project: 'vitrin', title: 'Gece işi', tier: 'kod', model: 'opus', start: at(3), end: at(3, 20), sessionIdleFor: 0 }] };
          const iz = [];
          gun(spec, at(2, 40), at(3, 45), 5, (ms, a, emu) => {
            const w = a.find((x) => x.tiklama && /030000-vitrin/.test(x.tiklama.note || '') && x.tur === 'ajan' && !x.cikis);
            const k = a.find((x) => x.id === 'kadro:opus');
            if (ms === at(2, 55) || ms === at(3, 10) || ms === at(3, 44)) iz.push({ ms, w: w ? [w.poz, w.devral || ''] : null,
              k: k ? [k.yer, k.poz] : null, arrived: k ? emu.arrived(k.id) : null }); });
          return iz; })()""")
        once, sirada, sonra = out
        self.assertEqual(once["k"][1], "yatiyor")  # asleep before the job
        self.assertIsNone(sirada["k"])  # its body works the job (devral) …
        self.assertEqual(sirada["w"][0], "yaziyor")
        self.assertRegex(sonra["k"][0], r"^dinlenme-yatak-\d+$")  # … and goes back to bed after
        self.assertEqual(sonra["k"][1], "yatiyor")

    def test_the_rest_room_has_twenty_beds_and_clear_walkways(self):
        out = run_js("""(() => { const plan = d.ofisPlani(['vitrin'], { max_running_per_project: 1, denetciler: ['codex', 'glm'] });
          const oda = plan.odalar.find((r) => r.id === 'dinlenme');
          const yat = Object.values(plan.dugumler).filter((n) => n.tur === 'yatak');
          const kutular = d.mobilyaKutulari(plan).filter((b) => b.id.startsWith('yatak:'));
          const icinde = (n) => n.x >= oda.x && n.x <= oda.x + oda.w && n.z >= oda.z && n.z <= oda.z + oda.d;
          const ust = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.z0 < b.z1 && b.z0 < a.z1;
          let cakisma = 0; for (let i = 0; i < kutular.length; i++) for (let j = i + 1; j < kutular.length; j++) if (ust(kutular[i], kutular[j])) cakisma++;
          const yollar = yat.map((n) => d.yol(plan, 'dinlenme-kapi', n.id));
          return { n: yat.length, hepsiIcinde: yat.every(icinde), kutu: kutular.length, cakisma, w: oda.w, d: oda.d,
            ulasir: yollar.every((p) => Array.isArray(p) && p.length > 1),
            kesen: yollar.flatMap((p) => p.slice(1).map((id, i) => [p[i], id]))
              .filter(([a, b]) => d.kenarMobilyadan(plan, a, b)).length }; })()""")
        self.assertEqual(out["n"], 20)
        self.assertEqual(out["kutu"], 20)
        self.assertTrue(out["hepsiIcinde"])
        self.assertEqual(out["cakisma"], 0)
        self.assertGreater(out["w"], 19.5)  # enlarged (was 19.5 × 14.25)
        self.assertTrue(out["ulasir"])
        self.assertEqual(out["kesen"], 0)  # no walk crosses another bed


@unittest.skipUnless(NODE, "node is not installed")
class MealTest(unittest.TestCase):
    """The owner, 2026-11-14: breakfast every day (the staff right after arriving on a work day, the agents after waking, the
    people on shift at the morning handover), lunch as before on a work day and 12:30–13:30 for the agents on a day off,
    dinner 19:00–20:00 for everyone in the office (the people on shift one at a time) — in the Yemekhane."""
    AJANLAR = NightSleepTest.AJANLAR

    def izle(self, spec, t0, t1, step=5):
        # every tick: the eaters {id: [yer, metin]} and the people on shift
        return run_js(f"""(() => {{ const r = [];
          gun({spec}, {t0}, {t1}, {step}, (ms, a) => r.push({{ ms,
            yiyen: a.filter((x) => x.poz === 'yemek').map((x) => [x.id, x.yer, x.durum_metni]),
            nobet: a.filter((x) => x.nobetci && !x.cikis && !x.otel).map((x) => [x.gorevli, x.yer, x.poz]),
            durum: Object.fromEntries(a.filter((x) => x.tur === 'sus' || x.tur === 'ajan' || x.id === 'ceo').map((x) => [x.id, [x.yer, x.poz, !!x.otel, x.durum_metni]])) }}));
          return r; }})()""", timeout=600)

    def test_on_a_work_day_the_staff_have_breakfast_before_their_desk(self):
        r = self.izle("'bos-ofis'", "at(7, 45)", "at(9, 20)")
        ilk = {}  # the first state of each day-hours staff member in the office (not at / walking from the Otel)
        for t in r:
            for i, (yer, poz, otel, metin) in t["durum"].items():
                if not re.match(r"^sus:(sosyal|muhasebe|idari|ik|revir|psikolog|masaj|arge|mudur)", i) or otel:
                    continue
                ilk.setdefault(i, (yer, poz, metin))
        self.assertGreaterEqual(len(ilk), 20, ilk)
        kahvalti = [i for i, (yer, poz, m) in ilk.items() if poz == "yemek" and m == "kahvaltı ediyor" and yer.startswith("yemekhane-")]
        self.assertGreaterEqual(len(kahvalti), 0.9 * len(ilk), {i: v for i, v in ilk.items() if i not in kahvalti})
        son = r[-1]["durum"]
        self.assertFalse(any(son[i][1] == "yemek" and son[i][3] == "kahvaltı ediyor" for i in kahvalti))  # then on to work
        # the agents after waking (08:30) and the people on shift at the 08:00 handover
        yiyenler = {i for t in r for i, _, m in t["yiyen"] if "kahvaltı" in m}
        self.assertTrue({"ceo", "kadro:haiku", "denetci:codex"} <= yiyenler, yiyenler)
        self.assertTrue(any(re.match(r"^sus:(guvenlik|sekreter|sunucu)", i) for i in yiyenler), yiyenler)

    def test_on_saturday_the_agents_have_breakfast_lunch_and_dinner(self):
        for t0, t1, metin in (("at(48 + 9)", "at(48 + 10)", "kahvaltı ediyor"), ("at(48 + 12, 30)", "at(48 + 13, 30)", "öğle yemeğinde"),
                              ("at(48 + 19)", "at(48 + 20)", "akşam yemeğinde")):
            with self.subTest(metin=metin):
                r = self.izle("'bos-ofis'", t0, t1, 10)
                yiyen = {i for t in r for i, yer, m in t["yiyen"] if m == metin and yer.startswith("yemekhane-")}
                self.assertTrue(set(self.AJANLAR) <= yiyen, set(self.AJANLAR) - yiyen)

    def test_on_a_holiday_too(self):
        r = self.izle("'bos-ofis'", "at(-14 * 24 + 19)", "at(-14 * 24 + 20)", 10)
        yiyen = {i for t in r for i, _, m in t["yiyen"] if m == "akşam yemeğinde"}
        self.assertTrue(set(self.AJANLAR) <= yiyen, set(self.AJANLAR) - yiyen)

    def test_the_people_on_shift_eat_one_at_a_time_and_the_guard_never_leaves_his_post(self):
        for t0, t1 in (("at(18, 55)", "at(20, 5)"), ("at(7, 55)", "at(9)"), ("at(48 + 8, 55)", "at(48 + 10)")):
            with self.subTest(t0=t0):
                r = self.izle("'dort-mesgul'", t0, t1)
                for t in r:
                    yiyen = [g for g, yer, poz in t["nobet"] if poz == "yemek"]
                    self.assertLessEqual(len(yiyen), 1, t)
                    guard = [yer for g, yer, poz in t["nobet"] if g == "guvenlik"]
                    self.assertEqual(len(guard), 1, t)
                    self.assertTrue(guard[0].startswith("lobi-"), t)  # the post is never empty: he eats there
                    for g in ("yemekhane", "asci"):
                        self.assertEqual(sum(1 for x, _, _ in t["nobet"] if x == g), 1, (g, t))
                eaten = {g for t in r for g, _, poz in t["nobet"] if poz == "yemek"}
                self.assertTrue({"guvenlik", "sunucu", "yemekhane", "asci"} <= eaten, eaten)

    def test_unique_seats(self):
        for t0, t1 in (("at(8, 10)", "at(9)"), ("at(12)", "at(13)"), ("at(19)", "at(20)")):
            r = self.izle("'dort-mesgul'", t0, t1, 10)
            for t in r:
                yerler = [yer for _, yer, _ in t["yiyen"] if yer.startswith("yemekhane-")]
                self.assertEqual(len(yerler), len(set(yerler)), t["yiyen"])

    def test_a_working_character_skips_its_meal(self):
        out = run_js("""(() => { const spec = { ...F.SENARYOLAR['tek-proje-ceo-bosta'], jobs: [{ note: '2026-11-14-083000-vitrin.md',
            project: 'vitrin', title: 'Cumartesi işi', tier: 'kod', model: 'opus', start: at(48 + 8, 30), end: at(48 + 21),
            sessionIdleFor: 0 }] };
          const r = []; gun(spec, at(48 + 9), at(48 + 20), 30, (ms, a) => {
            const w = a.find((x) => x.tiklama && /083000-vitrin/.test(x.tiklama.note || '') && x.tur === 'ajan' && !x.cikis);
            const k = a.find((x) => x.id === 'kadro:sonnet');
            r.push([w ? w.poz : null, k ? k.poz : null]); });
          return r; })()""", timeout=600)
        self.assertTrue(all(w == "yaziyor" for w, _ in out), out[:5])  # never at a meal while its job runs
        self.assertIn("yemek", {k for _, k in out})  # an idle one does eat

    def test_the_ceo_stays_in_its_room_while_a_job_runs(self):
        # The owner, 2026-11-14: a job the CEO handed out is running -> the CEO waits in its room, no lunch, no round
        out = run_js("""(() => { const spec = { ...F.SENARYOLAR['tek-proje-ceo-bosta'], jobs: [{ note: '2026-11-14-124627-sozluk.md',
            project: 'vitrin', title: 'Okuma işi', tier: 'kolay', model: 'haiku', start: at(48 + 12, 20), end: at(48 + 14),
            sessionIdleFor: 0 }] };
          const r = []; gun(spec, at(48 + 12, 30), at(48 + 13, 50), 30, (ms, a) => {
            const c = a.find((x) => x.id === 'ceo'); r.push([c.yer, c.poz]); });
          return r; })()""", timeout=600)
        self.assertTrue(all(yer == "ceo-masa" and poz not in ("yemek", "yuruyor") for yer, poz in out), out[:6])


@unittest.skipUnless(NODE, "node is not installed")
class KitchenTest(unittest.TestCase):
    """The owner, 2026-11-14: the kitchen corner (a stove and a fridge beside the existing Bulaşıkhane) and two shift teams —
    three yemekhane görevlisi and three aşçı on the 24/7 rotation, one of each on duty at every minute."""

    def test_exactly_one_cook_and_one_server_on_duty_every_hour_incl_saturday_and_a_holiday(self):
        out = run_js("""(() => { const bad = []; let n = 0;
          for (const g of [0, 2, -14]) for (let hh = 0; hh < 24; hh++) for (const mm of [0, 30, 59]) {
            const t = at(g * 24 + hh, mm); n++;
            for (const e of ['yemekhane', 'asci']) if (d.nobetEkibi(e, t).filter((u) => u.durum === 'nobette').length !== 1) bad.push([e, g, hh, mm]);
          }
          const cizilen = []; gun('bos-ofis', at(48 + 7, 50), at(48 + 8, 20), 5, (ms, a) => {
            for (const e of ['yemekhane', 'asci']) cizilen.push(a.filter((x) => x.gorevli === e && x.nobetci && !x.otel).length); });
          return { n, bad, cizilen: [...new Set(cizilen)] }; })()""")
        self.assertEqual(out["bad"], [])
        self.assertEqual(out["cizilen"], [1])  # also across the 08:00 handover on Saturday

    def test_the_kitchen_corner_and_its_walkways(self):
        out = run_js("""(() => [['vitrin'], ['a', 'b', 'c', 'd']].map((pr) => {
          const plan = d.ofisPlani(pr, { max_running_per_project: 1, denetciler: ['codex', 'glm'] });
          const r = plan.odalar.find((o) => o.id === 'yemekhane'); const n = plan.dugumler;
          const icinde = (k) => n[k] && n[k].x > r.x && n[k].x < r.x + r.w && n[k].z >= r.bulasik.z && n[k].z < r.z + r.d;
          const yollar = ['yemekhane-ocak', 'yemekhane-dolap'].map((k) => d.yol(plan, 'yemekhane-kapi', k));
          return { icinde: ['yemekhane-ocak', 'yemekhane-dolap', 'yemekhane-bulasik'].every(icinde), ocak: !!r.bulasik.ocak, dolap: !!r.bulasik.dolap,
            ulasir: yollar.every((p) => Array.isArray(p) && p.length > 1),
            kesen: yollar.flatMap((p) => p.slice(1).map((id, i) => [p[i], id])).filter(([a, b]) => d.kenarMobilyadan(plan, a, b)).length,
            ayri: new Set(['yemekhane-ocak', 'yemekhane-dolap', 'yemekhane-bulasik', 'yemekhane-servis'].map((k) => `${n[k].x},${n[k].z}`)).size }; }))()""")
        for o in out:
            self.assertEqual(o, {"icinde": True, "ocak": True, "dolap": True, "ulasir": True, "kesen": 0, "ayri": 4})

    def test_meals_are_cooked_and_served_by_the_people_on_duty(self):
        out = run_js("""(() => { const r = {};
          for (const [ad, t0, t1] of [['kahvalti', at(8), at(8, 30)], ['ogle', at(12), at(12, 20)], ['aksam', at(19), at(19, 15)],
            ['cmt-kahvalti', at(48 + 9), at(48 + 9, 15)], ['gece', at(3), at(3, 20)]]) {
            const x = { servis: 0, pisir: 0, n: 0 };
            gun('bos-ofis', t0, t1, 10, (ms, a) => { x.n++;
              const s = a.find((y) => y.gorevli === 'yemekhane' && y.nobetci && !y.otel);
              const c = a.find((y) => y.gorevli === 'asci' && y.nobetci && !y.otel);
              if (s && s.yer === 'yemekhane-servis' && /servis|hazırlıyor/.test(s.durum_metni)) x.servis++;
              if (c && /^yemekhane-(ocak|dolap)$/.test(c.yer) && /pişiriyor|hazırlıyor|malzeme/.test(c.durum_metni)) x.pisir++; });
            r[ad] = x; }
          return r; })()""", timeout=600)
        for ad in ("kahvalti", "ogle", "aksam", "cmt-kahvalti"):
            with self.subTest(ogun=ad):
                self.assertGreater(out[ad]["servis"], 0, out[ad])
                self.assertEqual(out[ad]["pisir"], out[ad]["n"], out[ad])  # the cook works the whole meal
        self.assertEqual(out["gece"]["pisir"], 0, out["gece"])  # at 03:00 it cleans the kitchen instead

    def test_the_chart_who_is_where_the_card_and_the_otel(self):
        out = run_js("""(() => { const t = at(10); const st = F.durumOlustur(F.SENARYOLAR['bos-ofis'], t);
          const g = h.orgSemasi(st, t, null); const by = {}; const walk = (n, yol) => { by[n.id] = [n.ad, n.durum, yol]; n.cocuklar.forEach((c) => walk(c, [...yol, n.id])); }; walk(g, []);
          const k = d.kimNerede(st, t, null);
          const satir = h.kimNeredeSatirlari(k, t, 'Europe/Istanbul').map((r) => r.metin);
          const guests = d.otelKadrosu(Array.from({ length: 23 }, (_, i) => `p${i}`)).length;
          return { asci: by['ascilar'], ymk: by['yemekhane-ekibi'], satir, guests, oda: d.OTEL_ODA,
            nobette: k.ofiste.filter((e) => e.durum === 'nobette').map((e) => e.ekip),
            kartSatir: h.yemekhaneKarti(st, t, [], 'asci').satirlar.map((x) => `${x.ad}: ${x.metin}`) }; })()""")
        self.assertRegex(out["asci"][0], r"^Aşçılar \(3\)$")
        self.assertRegex(out["asci"][1], r"^nöbette: \d\. aşçı$")
        self.assertIn("ofis-hizmetleri", out["asci"][2])
        self.assertIn("sus:ik", out["asci"][2])
        self.assertRegex(out["ymk"][1], r"^nöbette: \d\. yemekhane görevlisi$")
        self.assertTrue({"yemekhane", "asci"} <= set(out["nobette"]), out["nobette"])
        self.assertTrue(any(re.match(r"^Aşçı \(2 kişi\)", m) for m in out["satir"]), out["satir"])
        self.assertTrue(any(re.match(r"^Yemekhane \(2 kişi\)", m) for m in out["satir"]), out["satir"])
        self.assertTrue(any(m.startswith("Nöbette:") and "Aşçı" in m for m in out["satir"]), out["satir"])
        self.assertLessEqual(out["guests"], out["oda"] - 8)  # ≥ 8 spare rooms with 23 projects
        self.assertTrue(any(x.startswith("Nöbette: ") and "aşçı" in x for x in out["kartSatir"]), out["kartSatir"])
        self.assertTrue(any(x.startswith("Akşam yemeği: 19:00–20:00") for x in out["kartSatir"]), out["kartSatir"])


@unittest.skipUnless(NODE, "node is not installed")
class OtelTest(unittest.TestCase):
    """The city, step 1 (owner decision 2026-11-14): the Otel in front of the lobby, where the people who used to go home stay —
    the day-hours staff outside their hours and on days off, the shift teams off shift. The agents keep the Dinlenme
    odası; the guests are hidden inside the closed building."""

    def test_enough_rooms_and_a_clear_short_path_from_the_lobby(self):
        out = run_js("""[0, 4, 12].map((n) => { const p = d.ofisPlani(Array.from({ length: n }, (_, i) => `p${i}`), { max_running_per_project: 2,
            denetciler: ['codex', 'glm', 'deepseek', 'antigravity'] });
          const odalar = Object.keys(p.dugumler).filter((id) => /^otel-oda-\\d+$/.test(id));
          const misafir = d.otelKadrosu(p.projeler);
          const w = p.yol('lobi-kapi', 'otel-kapi'), ids = w.map((x) => x.id);
          return { n, oda: odalar.length, misafir: misafir.length, uniq: new Set(misafir.map((x) => x.id)).size,
            yol: ids, kesen: ids.slice(1).filter((id, i) => d.kenarMobilyadan(p, ids[i], id)).length,
            uzunluk: d.yolUzunlugu(p, 'lobi-giris', 'otel-kapi'), otel: p.otel, W: p.genislik, D: p.derinlik,
            odalarIcinde: odalar.every((id) => { const q = p.dugumler[id]; return q.x > p.otel.x && q.x < p.otel.x + p.otel.w && q.z > p.otel.z && q.z < p.otel.z + p.otel.d; }),
            disarida: p.odalar.every((r) => r.z + r.d <= p.otel.z) }; })""")
        for o in out:
            with self.subTest(projects=o["n"]):
                self.assertGreaterEqual(o["oda"] - o["misafir"], 8, o)  # a room for everyone and spares
                self.assertEqual(o["uniq"], o["misafir"])
                self.assertEqual(o["yol"][-3:], ["lobi-giris", "otel-yol", "otel-kapi"])  # out through the entrance
                self.assertEqual(o["kesen"], 0)
                self.assertLess(o["uzunluk"], 15)  # a short path across the yard
                self.assertTrue(o["odalarIcinde"])
                self.assertTrue(o["disarida"])  # outside the floor: in front of it
                self.assertGreater(o["otel"]["z"], o["D"])
                self.assertLessEqual(o["otel"]["x"] + o["otel"]["w"], o["W"] + 1e-6)

    def test_evening_walk_to_the_hotel_and_morning_walk_back(self):
        out = run_js("""(() => { const iz = []; const olay = [];
          gun('bos-ofis', at(18, 0), at(34, 1), 5, (ms, a, emu, st, ev) => {
            for (const e of ev) if (e.id === 'sus:muhasebe' && (e.t === 'otele' || e.t === 'otelden' || e.t === 'kayboldu')) olay.push([e.t, ms]);
            const m = a.find((x) => x.id === 'sus:muhasebe');
            if ([at(17), at(21), at(24 + 3), at(24 + 7), at(24 + 10)].includes(ms) || (m && !iz.length)) iz.push([ms, m ? m.yer : null, m ? m.poz : null, m ? m.durum_metni : null, emu.arrived('sus:muhasebe')]); });
          return { iz, olay }; })()""", timeout=400)
        olay = [t for t, _ in out["olay"]]
        self.assertEqual(olay, ["otele", "otelden"], out)  # one walk there in the evening, one back in the morning
        yerler = {round(ms): (yer, poz, metin, var) for ms, yer, poz, metin, var in out["iz"]}
        geceler = [v for v in yerler.values() if v[0] and v[0].startswith("otel-oda-")]
        self.assertTrue(any(v[2] == "otelde · uyuyor" and v[3] for v in geceler), out)
        self.assertTrue(any(v[2] == "otelde" for v in geceler), out)  # 21:00: at the hotel, awake
        sabah = out["iz"][-1]
        self.assertFalse(str(sabah[1]).startswith("otel-oda-"), sabah)  # 10:00 the next day: back at work

    def test_hafif_draws_nobody_at_the_hotel_and_the_texts_say_otelde(self):
        out = run_js("""(() => { let a = null, st = null; gun('bos-ofis', at(3) - 4 * M, at(3), 5, (ms, x, e, s) => { a = x; st = s; }, { hafif: true });
          let b = null; gun('bos-ofis', at(3) - 4 * M, at(3), 5, (ms, x, e, s) => { b = x; });
          const k = d.kimNerede(st, at(3), b);
          return { hafif: a.filter((x) => x.otel).length, otel: b.filter((x) => x.otel).length,
            evde: k.evde.length, metin: h.kimNeredeMetni(k.evde.find((x) => x.id === 'sus:muhasebe'), at(3), 'Europe/Istanbul'),
            kose: h.mesaiDisiSatiri(st, at(3)), ajan: b.filter((x) => x.tur === 'ajan').every((x) => /^dinlenme-yatak-/.test(x.yer)),
            salon: b.filter((x) => x.otel && x.salonda).length }; })()""")
        self.assertEqual(out["hafif"], 0)
        self.assertEqual(out["otel"], out["evde"])  # everyone "at home" is a guest of the hotel
        self.assertRegex(out["metin"], r"^Muhasebeci · otelde · çıktı dün 1[78]:\d\d · döner 0[89]:\d\d$")
        self.assertEqual(out["kose"], f"Mesai dışı · {out['evde']} kişi otelde · 08:30'da dönüyorlar")
        self.assertTrue(out["ajan"])  # the agents still sleep in the office's Dinlenme odası

    def test_the_hotel_and_its_hidden_guests_cost_almost_nothing(self):
        out = run_scene_count("""(() => ['bos-ofis', 'dort-mesgul'].map((ad) => [F.at(3, 0), F.at(18, 45), F.at(11, 0)].map((t) => {
          const { office, liste } = ofis(ad, t);
          const gorunen = [...office.actors.values()].filter((v) => liste.find((a) => a.id === v.id && a.otel) && v.ch && v.ch.root.visible).length;
          const etiket = [...office.actors.values()].filter((v) => v.otelde && v.label && v.label.el.style.opacity !== '0').length;
          return { ad, t, ...say(office), misafir: liste.filter((a) => a.otel).length, gorunen, etiket,
            b: office.bounds, c: office.cerceve, otel: office.plan.otel, D: office.plan.derinlik }; })).flat())()""")
        for o in out:
            with self.subTest(senaryo=o["ad"], t=o["t"]):
                self.assertLess(o["draw"], PerformanceTest.DRAW_LIMIT, o)
                self.assertEqual(o["gorunen"], 0, o)  # hidden inside the building
                self.assertEqual(o["etiket"], 0, o)
        gece = [o for o in out if o["t"] == out[0]["t"]]
        self.assertTrue(all(o["misafir"] >= 30 for o in gece), gece)
        o = out[0]
        # the view frames the office; panning reaches the hotel (its far edge inside the pan bounds)
        self.assertLess(o["c"]["maxZ"], o["b"]["maxZ"])
        self.assertGreaterEqual(o["b"]["maxZ"] + 1e-6, o["otel"]["z"] + o["otel"]["d"] - o["D"] / 2)  # world: centred on the floor
        print("\nOtel draw calls:", [(x["ad"], x["t"], x["draw"]) for x in out])


@unittest.skipUnless(NODE, "node is not installed")
class SokakTest(unittest.TestCase):
    """The city, step 2 (owner decision 2026-11-14): a street across the yard between the office and the Otel — a road, a
    sidewalk on both sides, a crosswalk on the office–Otel path, lamps and trees — and a few anonymous pedestrians."""

    def test_the_street_lies_in_the_yard_and_the_staff_cross_on_the_crosswalk(self):
        out = run_js("""[0, 4, 12].map((n) => { const p = d.ofisPlani(Array.from({ length: n }, (_, i) => `p${i}`), { max_running_per_project: 1 });
            const s = p.sokak, w = p.yol('lobi-kapi', 'otel-kapi');
            const i = w.findIndex((x) => x.id === 'lobi-giris');
            return { n, s, D: p.derinlik, W: p.genislik, otel: p.otel, dis: p.dis, S: d.SOKAK_OLCU,
              disaridaki: w.slice(i).map((x) => [x.id, x.x, x.z]) }; })""")
        for o in out:
            with self.subTest(projects=o["n"]):
                s, S = o["s"], o["S"]
                self.assertGreater(s["kuzey"]["z0"], o["D"] + 2.3)  # past the office slab's lip
                self.assertEqual(s["kuzey"]["z1"], s["yol"]["z0"])
                self.assertEqual(s["yol"]["z1"], s["guney"]["z0"])
                self.assertLess(s["guney"]["z1"], o["otel"]["z"] - 1.1)  # before the hotel's slab
                self.assertLess(s["x0"], 0)
                self.assertGreater(s["x1"], o["W"])  # past both ends of the floor
                self.assertLessEqual(o["dis"]["x"], s["x0"])
                self.assertGreaterEqual(o["dis"]["x"] + o["dis"]["w"] + 1e-6, s["x1"])  # the pan bounds cover it
                # the staff's walk out of the lobby to the hotel is one straight line through the crosswalk's middle
                self.assertEqual([x[0] for x in o["disaridaki"]], ["lobi-giris", "otel-yol", "otel-kapi"])
                self.assertTrue(all(x[1] == s["gecit"]["x"] for x in o["disaridaki"]), o["disaridaki"])
                yol = [x for x in o["disaridaki"] if s["yol"]["z0"] <= x[2] <= s["yol"]["z1"]]
                self.assertEqual([x[0] for x in yol], ["otel-yol"])
                # lamps and trees: on the curb strips, clear of the crosswalk and the ends
                for x, z in s["lambalar"] + s["agaclar"]:
                    self.assertIn(z, (round(s["kuzey"]["z1"] - S["BORDUR"], 2), round(s["guney"]["z0"] + S["BORDUR"], 2)))
                    self.assertGreater(abs(x - s["gecit"]["x"]), s["gecit"]["w"] / 2 + 1)
                    self.assertTrue(s["x0"] + 2 < x < s["x1"] - 2)
                self.assertGreater(len(s["lambalar"]), 4)
                self.assertGreater(len(s["agaclar"]), 4)

    def test_pedestrians_keep_to_the_sidewalks_and_the_crosswalk_and_loop(self):
        out = run_js("""(() => { const p = d.ofisPlani(['a', 'b', 'c', 'd'], { max_running_per_project: 1 }); const s = p.sokak, S = d.SOKAK_OLCU;
          const r = d.yayaRotalari(s), kutu = d.mobilyaKutulari(p), R = S.GOVDE;
          const kotu = [], yon = { kuzey: new Set(), guney: new Set() }; let gecen = 0, dongu = 0;
          for (let i = 0; i < d.YAYA_EN_COK; i++) {
            for (let t = 0; t < 1500; t += 0.6) {
              const k = d.yayaKonumu(r, i, t);
              const kal = ['kuzey', 'guney'].find((n) => k.z - R >= s[n].z0 - 1e-6 && k.z + R <= s[n].z1 + 1e-6);
              const gecitte = Math.abs(k.x - s.gecit.x) <= s.gecit.w / 2 - R + 1e-6 && k.z >= s.kuzey.z0 && k.z <= s.guney.z1;
              if (!gecitte && !kal) kotu.push(['yolda', i, t, k.x, k.z]);
              if (k.x - R < s.x0 || k.x + R > s.x1) kotu.push(['uçta', i, t, k.x]);
              for (const [x, z] of s.lambalar) if (Math.hypot(k.x - x, k.z - z) < R + S.LAMBA) kotu.push(['lamba', i, t, x, z]);
              for (const [x, z] of s.agaclar) if (Math.hypot(k.x - x, k.z - z) < R + S.AGAC) kotu.push(['ağaç', i, t, x, z]);
              for (const b of kutu) if (k.x > b.x0 && k.x < b.x1 && k.z > b.z0 && k.z < b.z1) kotu.push(['mobilya', i, b.id]);
              if (kal && Math.abs(Math.sin(k.aci)) > 0.99) yon[kal].add(Math.sign(Math.sin(k.aci)));
              if (!kal) gecen++;
            }
            const k0 = d.yayaKonumu(r, i, 37), per = r[i % r.length].L / k0.hiz, k1 = d.yayaKonumu(r, i, 37 + per);
            if (Math.hypot(k0.x - k1.x, k0.z - k1.z) < 1e-6) dongu++;
          }
          return { kotu: kotu.slice(0, 10), yon: { kuzey: [...yon.kuzey], guney: [...yon.guney] }, gecen, dongu }; })()""")
        self.assertEqual(out["kotu"], [], out)  # never on the road off the crosswalk, never through a lamp or a tree
        self.assertEqual(sorted(out["yon"]["kuzey"]), [-1, 1])  # both directions on both sidewalks
        self.assertEqual(sorted(out["yon"]["guney"]), [-1, 1])
        self.assertGreater(out["gecen"], 0)  # some cross the road, on the crosswalk
        self.assertEqual(out["dongu"], 10)  # each walks a closed loop

    def test_pedestrian_counts_by_time_of_day_and_hafif_and_their_draw_calls(self):
        out = run_scene_count("""(() => { const sahne = { saat_dilimi: 'Europe/Istanbul' };
          const bak = (t, light = false) => { const { office } = ofis('dort-mesgul', t, light); const Y = office.yaya;
            const once = say(office).draw; let hits = [];
            if (Y) { Y.govde.raycast({}, hits); Y.bacak.raycast({}, hits); }
            const m0 = Y ? Y.govde.instanceMatrix.array.slice(0, 3 * 16) : null;
            for (let i = 0; i < 8; i++) office.frame();
            const m1 = Y ? Y.govde.instanceMatrix.array.slice(0, 3 * 16) : null;
            if (Y) { Y.govde.visible = Y.bacak.visible = false; }
            const B = office.bounds, sh = office.sun.shadow.camera, P = office.plan;
            return { n: Y ? Y.n : 0, govde: Y ? Y.govde.count : 0, bacak: Y ? Y.bacak.count : 0, cast: Y ? Y.govde.castShadow || Y.bacak.castShadow : false,
              fark: once - say(office).draw, hits: hits.length, yuruyor: !!m0 && m0.some((v, i) => v !== m1[i]),
              b: B, c: office.cerceve, yari: sh.right, sokak: P.sokak, W: P.genislik, D: P.derinlik }; };
          return { gun: bak(F.at(10, 30)), gece: bak(F.at(3, 45)), hafif: bak(F.at(10, 30), true),
            sayi: [9, 21, 6.5, 2].map((h) => d.yayaSayisi(F.at(0) + h * 3600000, sahne)), hafifSayi: d.yayaSayisi(F.at(10), sahne, true),
            ekip: d.dekorEkibi(d.ofisPlani(['a'], {}), [], F.at(10, 30), sahne).yaya }; })()""")
        g = out["gun"]
        self.assertEqual((g["n"], g["govde"], g["bacak"]), (8, 8, 16), g)
        self.assertEqual(g["fark"], 2, g)  # one InstancedMesh for the bodies, one for the legs
        self.assertFalse(g["cast"])
        self.assertEqual(g["hits"], 0)  # scenery: never picked
        self.assertTrue(g["yuruyor"])
        self.assertLessEqual(out["gece"]["n"], 3)
        self.assertGreaterEqual(out["gece"]["n"], 1)
        self.assertEqual(out["hafif"]["n"], 0)
        self.assertEqual(out["hafif"]["fark"], 0)
        self.assertEqual(out["sayi"], [8, 5, 5, 2])
        self.assertEqual(out["hafifSayi"], 0)
        self.assertEqual(out["ekip"], 8)
        # the default view frames the office only; panning, the camera depth and the sun's shadow box cover the street
        s, W, D, b = g["sokak"], g["W"], g["D"], g["b"]
        self.assertLess(g["c"]["maxZ"], s["kuzey"]["z0"] - D / 2)
        self.assertLessEqual(b["minX"], s["x0"] - W / 2)
        self.assertGreaterEqual(b["maxX"], s["x1"] - W / 2)
        self.assertGreaterEqual(b["maxZ"], s["guney"]["z1"] - D / 2)
        self.assertGreaterEqual(g["yari"], ((s["x1"] - W / 2) ** 2 + (s["guney"]["z1"] - D / 2) ** 2) ** 0.5)


@unittest.skipUnless(NODE, "node is not installed")
class PerformanceTest(unittest.TestCase):
    """Owner decision 2026-11-12 (the fan): fewer draw calls, robots-only shadows, a frame cap, cached walks."""

    # the draw-call limit: the peak (the 16:00 change, 685 after the vertex-coloured robot merge; 889 before) + ~40
    # 2026-11-13: with the 4th auditor desk (Antigravity) the 16:00 change draws 711 (10:30: 678; 3 helpers per job: 619)
    # — only 14 below the limit: look for savings in the next performance round
    # plan "Sonraki iş (9)" (2026-11-13): the dark desk screens, the unselectable room floors and the reserved bays' floors
    # are merged and only a typing desk draws its lit screen (static at 03:00: 254 instead of ~290), which pays for the
    # four managers' robots and the six new rooms: the 16:00 change draws 717 (10:30: 689; 3 helpers per job: 609;
    # 03:00: 363; hafif: 396)
    # 2026-11-13: the decorative people (two instanced meshes for all of them): 16:00 draws 719 (10:30: 691; 3 helpers
    # per job: 611; 03:00: 363; hafif: 398)
    # 2026-11-13: the work calendar adds nothing; the Dinlenme odası's 20 beds are static furniture merged per material
    # (no extra draw call); at night everyone off shift sleeps there (the robots only move) — see the numbers in
    # docs/gelistirici/sahne.md
    # 2026-11-14: measured as a walking sequence (below) the 16:00 change peaked at 732 — every standing or walking robot
    # drew its two legs separately; now all legs are one InstancedMesh: 695 there, 675 from scratch
    DRAW_LIMIT = 725

    @yavas
    def test_the_walking_sequence_stays_under_the_draw_limit(self):
        # the from-scratch count (ofis) misses the walkers: here the scene runs as on the page — a tick every few
        # seconds with `prev` carried and frames in between (0.25 s each), so the people walking between the office and
        # the Otel, the shift changes and the hand-overs are all on the floor at once; every tick is counted
        out = run_scene_count("""(() => {
          const seq = (ad, a, b, step) => { const spec = F.SENARYOLAR[ad];
            const host = el('div'); el('div').appendChild(host);
            const office = new Office(host, el('div'), { light: false });
            office.clock.getDelta = () => 0.25;
            let prev = null, plan = null, max = 0, at = 0, yuruyen = 0;
            for (let ms = a; ms < b; ms += step * 1000) {
              const st = F.durumOlustur(spec, ms);
              if (!plan) plan = d.ofisPlani(st.projects, { max_running_per_project: 1, denetciler: d.denetciListesi(st.modeller) });
              const x = d.niyetler(st, ms, prev, { hafif: false, max_running_per_project: 1, plan }); prev = x;
              office.setActors(x, plan); office.setDekor(d.dekorEkibi(plan, x, ms, st.sahne));
              for (let i = 0; i < step * 4; i++) office.frame();
              const c = say(office).draw; if (c > max) { max = c; at = ms; }
              yuruyen = Math.max(yuruyen, office.list.filter((v) => v.walk).length);
            }
            return { ad, max, saat: new Date(at + 3 * 3600000).toISOString().slice(11, 19), yuruyen };
          };
          return [seq('dort-mesgul', F.at(15, 55), F.at(16, 10), 2), seq('dort-mesgul', F.at(18), F.at(19, 15), 5),
            seq('dort-mesgul', F.at(7, 50), F.at(8, 50), 5), seq('dort-mesgul', F.at(48 + 8, 20), F.at(48 + 8, 50), 3),
            // the meals (2026-11-14): lunch, dinner, the 00:00 change of the kitchen teams too, Saturday's breakfast
            seq('dort-mesgul', F.at(12, 15), F.at(12, 40), 5), seq('dort-mesgul', F.at(18, 55), F.at(19, 30), 5),
            seq('dort-mesgul', F.at(23, 55), F.at(24, 10), 2), seq('dort-mesgul', F.at(48 + 8, 55), F.at(48 + 9, 30), 5)]; })()""",
            timeout=900)
        for o in out:
            with self.subTest(ad=o["ad"], saat=o["saat"]):
                self.assertGreater(o["yuruyen"], 1, o)  # people really walk in these windows
                self.assertLessEqual(o["max"], self.DRAW_LIMIT, o)
        self.assertLessEqual(out[0]["max"], 715, out[0])  # the 16:00 change keeps a safety margin

    def test_all_robot_legs_are_one_instanced_mesh_in_the_right_place_and_colour(self):
        out = run_scene_count("""(() => { const { office } = ofis('dort-mesgul', F.at(15, 59, 58));
          for (let i = 0; i < 8; i++) office.frame(); // some walk: their hips swing
          const B = office.bacak, m = new office.bacak.matrix.constructor(), p = (x) => [x.elements[12], x.elements[13], x.elements[14]];
          const c = (k) => [B.instanceColor.getX(k), B.instanceColor.getY(k), B.instanceColor.getZ(k)];
          let k = 0, kotu = 0, sayi = 0, ayakta = 0;
          for (const v of office.list) {
            if (!v.ch || !v.ch.root.visible) continue;
            const legs = v.ch.legs.filter((h) => h.visible);
            if (legs.length) ayakta++;
            for (const h of legs) {
              B.getMatrixAt(k, m); m.premultiply(B.matrixWorld); const a = p(m), b = p(h.userData.bacak.matrixWorld), r = c(k);
              const t = v.ch.legRenk;
              if (Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) > 1e-4 || Math.abs(r[0] - t.r) + Math.abs(r[1] - t.g) + Math.abs(r[2] - t.b) > 1e-4) kotu++;
              k++; sayi++;
            }
          }
          let ayri = 0; office.actorGroup.traverse((o) => { if (o.isMesh && !o.isInstancedMesh && o.geometry === B.geometry) ayri++; });
          return { count: B.count, sayi, kotu, ayakta, ayri, cast: B.castShadow, gorunur: B.visible }; })()""")
        self.assertGreater(out["ayakta"], 5, out)
        self.assertEqual(out["count"], out["sayi"], out)  # one instance per shown leg
        self.assertEqual(out["kotu"], 0, out)  # each at its hip's leg, in its robot's trim colour
        self.assertEqual(out["ayri"], 0, out)  # no robot draws a leg of its own any more
        self.assertTrue(out["cast"] and out["gorunur"], out)

    def test_a_night_with_everyone_asleep_stays_under_the_draw_limit(self):
        out = run_scene_count("""(() => ['bos-ofis', 'dort-mesgul'].map((ad) => { const { office, liste } = ofis(ad, F.at(3, 45));
          return { ad, ...say(office), yatan: liste.filter((a) => a.poz === 'yatiyor').length }; }))()""")
        for o in out:
            self.assertGreaterEqual(o["yatan"], 9, o)  # the CEO, the kadro and the auditors in their beds
            self.assertLess(o["draw"], self.DRAW_LIMIT, o)

    def test_a_four_project_office_draws_under_the_limit_and_only_robots_cast_shadows(self):
        out = run_scene_count("""(() => { const { office, actors } = ofis('dort-mesgul', F.at(10, 30));
          const vis = (o) => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
          const robots = (() => { let n = 0; office.actorGroup.traverse((o) => { if (o.isMesh && o.castShadow && vis(o)) n++; }); return n; })();
          return { ...say(office), robots, actors, auto: office.renderer.shadowMap.autoUpdate }; })()""")
        self.assertLess(out["draw"], self.DRAW_LIMIT, out)
        self.assertEqual(out["cast"], out["robots"], out)  # every shadow caster is a robot's part
        self.assertFalse(out["auto"])  # the shadow map is drawn only when something moved

    def test_the_evening_review_team_stays_under_the_draw_limit(self):
        # bin/gunsonu.py: the two Değerlendirme ekibi robots sit at existing Analist odası desks only in the evening
        # window while its work runs; the busy office at 20:25 with them stays under the limit
        out = run_scene_count("""(() => { const { office, actors, liste } = ofis('dort-mesgul-aksam', F.at(20, 25));
          return { ...say(office), actors, ekip: liste.filter((x) => x.gorevli === 'degerlendirme').length }; })()""")
        self.assertEqual(out["ekip"], 2, out)
        self.assertLess(out["draw"], self.DRAW_LIMIT, out)

    def test_a_shift_change_stays_under_the_draw_limit(self):
        # 16:00: the outgoing guard, Sekreter and IT person still walk to the lift while the incoming ones arrive
        out = run_scene_count("""(() => { const { office, actors, liste } = ofis('dort-mesgul', F.at(15, 59, 58));
          return { ...say(office), actors, iki: ['guvenlik', 'sekreter', 'sunucu'].map((g) => liste.filter((x) => x.gorevli === g && !x.otel).length) }; })()""")
        self.assertEqual(out["iki"][:2], [2, 2], out)  # the change is on the floor: two of each team
        self.assertLess(out["draw"], self.DRAW_LIMIT, out)

    def test_three_helpers_per_job_fit_their_spots_and_stay_under_the_draw_limit(self):
        # Step 3 (owner decision 2026-11-13): every job of four projects with 3 helpers at once (08:30)
        out = run_scene_count("""(() => { const { office, liste } = ofis('uc-yardimci', F.at(8, 30));
          const helpers = liste.filter((a) => a.id.includes('/alt:'));
          const by = {}; for (const h of helpers) { const p = h.id.split('/alt:')[0]; (by[p] = by[p] || []).push(h); }
          const ust = new Map(liste.map((a) => [a.id, a]));
          const yanlis = helpers.filter((h) => { const p = ust.get(h.id.split('/alt:')[0]);
            return !p || !p.masa || !h.yer.startsWith(`${p.masa}-yardimci-`) || h.yer.endsWith(`-${d.YARDIMCI_EN_COK}`); })
            .map((h) => [h.id, h.yer]);
          return { ...say(office), per: Object.values(by).map((l) => l.length), ozet: helpers.filter((h) => h.tur === 'ozet').length,
            yer: helpers.length, ayri: new Set(helpers.map((h) => h.yer)).size, yanlis }; })()""")
        self.assertEqual(out["yanlis"], [], out)  # each on its own parent's helper spots, never the "+N" one
        self.assertEqual(out["per"], [3, 3, 3, 3], out)
        self.assertEqual(out["ozet"], 0, out)  # no "+N": three fit the helper spots
        self.assertEqual(out["ayri"], out["yer"], out)  # every helper on its own spot
        self.assertLess(out["draw"], self.DRAW_LIMIT, out)

    def test_a_robots_still_parts_are_one_mesh_per_material_kind_with_vertex_colours(self):
        # plan B5 (owner decision 2026-11-12): a robot's still parts (shell, belt, visor, cheeks, accessories) share one
        # vertex-coloured material per surface kind; only the moving / glowing parts stay separate
        out = run_scene_count("""(() => { const { office } = ofis('dort-mesgul', F.at(10, 30));
          const vis = (o) => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
          // (the Otel's guests are hidden inside the building: nothing of them is drawn)
          return [...office.actors.values()].filter((v) => v.ch && v.ch.root.visible).map((v) => { let n = 0, vc = 0;
            v.ch.body.traverse((o) => { if (o.isMesh && vis(o)) { n++; if (o.material.vertexColors) vc++; } });
            return [v.id, n, vc]; }); })()""")
        for i, n, vc in out:
            with self.subTest(aktor=i):
                self.assertLessEqual(n, 9, (i, n))
                self.assertGreaterEqual(vc, 1)

    def test_merged_geometry_bounds_hold_every_vertex(self):
        # 2026-11-13 (the floor's front vanished when dragged): frustum culling reads a geometry's bounding sphere; a
        # merged mesh's bounds must come from its merged, moved vertices
        out = run_scene_count("""(() => { const { office } = ofis('dort-mesgul', F.at(10, 30));
          const v = new office.tmp.constructor(); let n = 0, merged = 0; const bad = [];
          office.scene.traverse((o) => { if (!o.isMesh || !o.geometry || !o.geometry.attributes.position) return;
            const g = o.geometry; const had = !!g.boundingSphere; if (!had) g.computeBoundingSphere();
            if (had && g.boundingBox) merged++;
            const P = g.attributes.position, sp = g.boundingSphere, bb = g.boundingBox;
            for (let i = 0; i < P.count; i++) { v.fromBufferAttribute(P, i); n++;
              if (v.distanceTo(sp.center) > sp.radius + 1e-3) { bad.push([o.name || o.uuid.slice(0, 6), 'sphere']); break; }
              if (bb && !bb.clone().expandByScalar(1e-3).containsPoint(v)) { bad.push([o.name || o.uuid.slice(0, 6), 'box']); break; } } });
          return { n, merged, bad: bad.slice(0, 5) }; })()""")
        self.assertEqual(out["bad"], [], out)
        self.assertGreater(out["merged"], 5, out)  # the static furniture and the robots' still parts are merged
        self.assertGreater(out["n"], 10000, out)

    def test_the_whole_floor_stays_between_near_and_far_wherever_the_view_goes(self):
        # The owner's screenshot 2026-11-13: dragged down, the lobby row and the bottom wing row were cut off along a
        # straight line (the camera was 73 units from its target with near = 0.1: they fell behind the near plane)
        out = run_scene_count("""(() => { const { office } = ofis('dort-mesgul', F.at(10, 30));
          const cam = office.camera, c = office.controls, V = office.tmp.constructor;
          const pts = []; const b = { min: new V(Infinity, Infinity, Infinity), max: new V(-Infinity, -Infinity, -Infinity) };
          office.scene.updateMatrixWorld(true);
          const p = new V();
          office.world.traverse((o) => { if (!o.isMesh || !o.geometry.attributes.position) return;
            if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
            const g = o.geometry.boundingBox;
            for (const x of [g.min.x, g.max.x]) for (const y of [g.min.y, g.max.y]) for (const z of [g.min.z, g.max.z]) {
              p.set(x, y, z).applyMatrix4(o.matrixWorld); b.min.min(p); b.max.max(p); } });
          for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) pts.push(new V(x, y, z));
          const bad = []; let lo = Infinity, hi = -Infinity, tried = 0;
          const R = office.derinlik.uzaklik;
          const B = office.bounds, pay = 1.5;
          const targets = [[B.minX - pay, B.minZ - pay], [B.maxX + pay, B.minZ - pay], [B.minX - pay, B.maxZ + pay],
            [B.maxX + pay, B.maxZ + pay], [0, 0]];
          for (const [tx, tz] of targets) for (let k = 0; k < 8; k++) for (const phi of [c.minPolarAngle, c.maxPolarAngle]) {
            const th = k * Math.PI / 4; tried++;
            c.target.set(tx, 0.8, tz);
            cam.position.set(tx + R * Math.sin(phi) * Math.sin(th), 0.8 + R * Math.cos(phi), tz + R * Math.sin(phi) * Math.cos(th));
            c.update(); cam.updateMatrixWorld(true);
            for (const q of pts) { const dz = -q.clone().applyMatrix4(cam.matrixWorldInverse).z; lo = Math.min(lo, dz); hi = Math.max(hi, dz);
              if (dz < cam.near || dz > cam.far) { bad.push([tx, tz, k, +phi.toFixed(2), +dz.toFixed(1)]); break; } } }
          // and the real drag path: the office dragged all the way down (the target to the floor's back corner)
          c.target.set(-1e4, 0.8, -1e4); office.clampTarget(); c.update(); cam.updateMatrixWorld(true);
          const dist = cam.position.distanceTo(c.target);
          const drag = pts.map((q) => -q.clone().applyMatrix4(cam.matrixWorldInverse).z);
          return { bad: bad.slice(0, 5), tried, lo, hi, near: cam.near, far: cam.far, R, dist,
            drag: [Math.min(...drag), Math.max(...drag)], W: office.plan.genislik, D: office.plan.derinlik }; })()""")
        self.assertEqual(out["bad"], [], out)
        self.assertEqual(out["tried"], 80)
        self.assertGreaterEqual(out["drag"][0], out["near"], out)
        self.assertLessEqual(out["drag"][1], out["far"], out)
        self.assertAlmostEqual(out["dist"], out["R"], places=3)  # OrbitControls keeps the distance (min = max)

    def test_the_turn_buttons_turn_45_degrees_around_the_view_centre_and_the_reset_turns_back(self):
        out = run_scene_count("""(() => { const { office } = ofis('dort-mesgul', F.at(10, 30));
          const c = office.controls, cam = office.camera;
          office.clock.getDelta = () => 0.25;
          const run = () => { for (let i = 0; i < 8; i++) office.frame(); };
          const a0 = c.getAzimuthalAngle(), t0 = c.target.clone(), z0 = cam.zoom;
          office.dondur(1); const anim = !!office.focusAnim; run();
          const a1 = c.getAzimuthalAngle(), d1 = cam.position.distanceTo(c.target), t1 = c.target.distanceTo(t0);
          office.dondur(-1); office.dondur(-1); run();
          const a2 = c.getAzimuthalAngle();
          for (let i = 0; i < 4; i++) office.dondur(-1); run();
          const a3 = c.getAzimuthalAngle();
          office.tumunuGoster(); run();
          const a4 = c.getAzimuthalAngle(), d4 = cam.position.distanceTo(c.target);
          return { a0, a1, a2, a3, a4, d1, d4, R: office.derinlik.uzaklik, t1, z: [z0, cam.zoom], anim,
            moved: office.userMoved }; })()""")
        pi = 3.141592653589793
        wrap = lambda a: (a + pi) % (2 * pi) - pi  # noqa: E731
        self.assertTrue(out["anim"])  # a smooth turn: an animation, counted as camera movement by the frame cap
        self.assertAlmostEqual(out["a0"], pi / 4, places=3)
        self.assertAlmostEqual(wrap(out["a1"] - out["a0"]), -pi / 4, places=3)
        self.assertAlmostEqual(wrap(out["a2"] - out["a0"]), pi / 4, places=3)
        self.assertAlmostEqual(wrap(out["a3"] - out["a0"] - 5 * pi / 4), 0, places=3)  # past ±π: no limit any more
        self.assertAlmostEqual(wrap(out["a4"] - pi / 4), 0, places=3)  # "Tümünü göster" turns back
        self.assertAlmostEqual(out["d1"], out["R"], places=3)
        self.assertAlmostEqual(out["d4"], out["R"], places=3)
        self.assertLess(out["t1"], 1e-6)  # around the view centre: the target stays
        self.assertFalse(out["moved"])  # after the reset the re-fit on resize is back on

    def test_the_frame_cap(self):
        out = run_js("""[h.hedefFps({ kamera: true }), h.hedefFps({ yuruyen: true }), h.hedefFps({ top: true }), h.hedefFps({})]""")
        self.assertEqual(out, [60, 30, 30, 9])
        scene = (WEB / "scene.js").read_text(encoding="utf-8")
        for need in ("hedefFps({ kamera, yuruyen: this.yuruyenVar", "Math.min(dpr, 1.5)", "antialias: !light && dpr <= 1.5",
                     "r.shadowMap.autoUpdate = false;", "this.statikBirlestir();",
                     "if (document.hidden || this.paused || this.labelsHidden) return;"):
            self.assertIn(need, scene)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("if (sahneGorunur()) renderScene();", app)  # no refresh while hidden / under a panel / Komuta

    def test_walks_are_cached_and_the_minute_mark_is_cheap(self):
        out = run_js("""(() => { const p = d.ofisPlani(Array.from({ length: 10 }, (_, i) => 'p' + i), { max_running_per_project: 4 });
          const ids = Object.keys(p.dugumler).sort();
          const t0 = performance.now(); let n = 0;
          for (let i = 0; i < 400; i++) { const a = ids[(i * 37) % ids.length], b = ids[(i * 91 + 5) % ids.length]; n += d.yol(p, a, b).length; }
          const first = performance.now() - t0;
          const t1 = performance.now();
          for (let i = 0; i < 400; i++) { const a = ids[(i * 37) % ids.length], b = ids[(i * 91 + 5) % ids.length]; d.yol(p, a, b); }
          const again = performance.now() - t1;
          const same = JSON.stringify(d.yol(p, 'asansor', 'ceo-masa')) === JSON.stringify(d.yol(p, 'asansor', 'ceo-masa'));
          return { first, again, same, n }; })()""")
        self.assertTrue(out["same"])
        self.assertLess(out["first"], 2000, out)  # 400 heap walks on ~1400 nodes
        self.assertLess(out["again"], out["first"] + 1, out)


@unittest.skipUnless(NODE, "node is not installed")
class GuardHeadcountTest(unittest.TestCase):
    """The guard's headcount (owner decision 2026-11-16): an idle leftover session holding a kadro's body is not "çalışıyor", and
    the workers beyond one body per kadro are counted on top of kimNerede's roster."""

    def test_an_undrawn_kadro_takes_its_bodys_state_and_extra_workers_count(self):
        out = run_js("""(() => { const st = { projects: [{ name: 'kasa' }], sahne: { saat_dilimi: 'Europe/Istanbul' } };
          const t = Date.UTC(2026, 10, 16, 11, 0);
          const w = (id, model, poz) => ({ id, tur: 'ajan', model, poz });
          const durum = (a) => d.kimNerede(st, t, a).ofiste.find((e) => e.id === 'kadro:opus').metin;
          return {
            bos: durum([w('oturum:eski', 'opus', 'bekliyor')]),
            calisan: durum([w('oturum:eski', 'opus', 'bekliyor'), w('is:a', 'opus', 'yaziyor')]),
            cizili: durum([w('kadro:opus', 'opus', 'yaziyor')]),
            hic: durum([]),
            fazla: [d.fazlaIsciSayisi([w('oturum:eski', 'opus', 'bekliyor')]),
              d.fazlaIsciSayisi([w('is:a', 'opus', 'yaziyor'), w('is:b', 'opus', 'yaziyor'), w('kadro:sonnet', 'sonnet', 'bekliyor'),
                w('is:c', 'sonnet', 'yaziyor'), { id: 'ozet', tur: 'ozet', etiket: '+3' }]),
              d.fazlaIsciSayisi(null)] }; })()""")
        self.assertEqual(out["bos"], "dinleniyor")      # was "çalışıyor": the idle leftover session holds the body
        self.assertEqual(out["calisan"], "çalışıyor")
        self.assertEqual(out["cizili"], "çalışıyor")
        self.assertEqual(out["hic"], "çalışıyor")       # a body not drawn at all still means it works as a job
        # opus: 2 workers, 1 is the kadro body -> 1; sonnet: kadro drawn + 1 worker -> 1; "+3" -> 3
        self.assertEqual(out["fazla"], [0, 5, 0])


if __name__ == "__main__":
    unittest.main()
