// Test support (test/test_npc.py). Emulates web/scene.js setActors + step() walking (no three.js): who walks where, at YURUME_HIZI along the plan's
// graph, with the same spawn / hand-over / lift rules. Used to measure walking time against the engine's slots.
import { YURUME_HIZI, ortakOfsetler, yolHazirla, yolKonumu } from '../web/ofis-sahne.js';
import { yol } from '../web/ofis-davranis.js';
// the same as ofis-sahne.js yuruyusYolu, with yol() cached per (from, to): the result is identical, only faster
const yolCache = new WeakMap();
function yuruyusYolu(plan, from, fromNode, toNode, to) {
  let c = yolCache.get(plan); if (!c) yolCache.set(plan, c = new Map());
  const k = `${fromNode}>${toNode}`;
  let path = c.get(k); if (!path) c.set(k, path = fromNode && toNode ? yol(plan, fromNode, toNode) : []);
  const pts = [[from.x, from.z]]; const ids = [null];
  const push = (x, z, id) => { const last = pts[pts.length - 1]; if (Math.hypot(last[0] - x, last[1] - z) < 1e-3) { ids[ids.length - 1] = id; return; } pts.push([x, z]); ids.push(id); };
  for (let i = 0; i < path.length - 1; i++) push(path[i].x, path[i].z, path[i].id);
  push(to.x, to.z, toNode || null);
  return { pts, ids };
}

export class SahneEmu {
  constructor(plan) { this.plan = plan; this.v = new Map(); this.first = true; this.wk = {}; this.bitmis = []; }
  xz(yer, off) { const n = this.plan.dugumler[yer]; return n ? { x: n.x + (off ? off[0] : 0), z: n.z + (off ? off[1] : 0) } : null; }
  placeAt(v, yer, d) { v.yer = yer; v.dest = d; v.walk = null; v.pos = { ...d }; }
  walkTo(v, yer, d, ms) {
    const fromNode = v.walk ? v.walk.sonraki || v.yer : v.yer;
    if (v.walk && !v.walk.arrived) v.stats.aborted++;
    v.walk = { yol: yolHazirla(yuruyusYolu(this.plan, v.pos, fromNode, yer, d)), s: 0, sonraki: fromNode, from: v.yer, bas: ms };
    v.stats.walks++;
    v.stats.walkLen += v.walk.yol.toplam;
    v.yer = yer; v.dest = d;
  }
  setActors(list, ms) {
    const OTEL = /^otel-oda-\d+$/;
    const first = this.first; this.first = false;
    const offs = ortakOfsetler(list);
    const ids = new Set(list.map((a) => a.id));
    const seen = new Set();
    const events = [];
    for (const a of list) {
      seen.add(a.id);
      let v = this.v.get(a.id);
      const dest = this.xz(a.yer, offs.get(a.id));
      const still = a.tur === 'ozet' || a.poz === 'evde';
      const old = !v && !first && dest && a.devral && !ids.has(a.devral) ? this.v.get(a.devral) : null;
      if (old) {
        this.v.delete(old.id); old.id = a.id; this.v.set(a.id, old); old.fading = false; v = old;
        events.push({ t: 'devral', from: a.devral, to: a.id });
        if (still) this.placeAt(v, a.yer, dest); else this.walkTo(v, a.yer, dest, ms);
      } else if (!v) {
        if (!dest || (a.cikis && !first)) { if (!dest) events.push({ t: 'yer-yok', id: a.id, yer: a.yer }); continue; }
        v = { id: a.id, a, pos: null, yer: null, dest: null, walk: null, fading: false,
          stats: { walks: 0, aborted: 0, walkLen: 0, walkMs: 0, ticks: 0, arrivals: 0 } };
        this.v.set(a.id, v);
        const lift = this.xz('asansor');
        // (scene.js: one first seen at the Otel is simply there)
        if (first || still || a.denetci || a.tur === 'alt-ajan' || a.otel || !lift || a.yer === 'asansor') this.placeAt(v, a.yer, dest);
        else { this.placeAt(v, 'asansor', lift); this.walkTo(v, a.yer, dest, ms); events.push({ t: 'asansorden', id: a.id }); }
      } else {
        if (v.fading && !a.cikis) v.fading = false;
        const lift = this.xz('asansor');
        if (v.a.poz === 'evde' && !still && dest && lift && !a.denetci) { this.placeAt(v, 'asansor', lift); this.walkTo(v, a.yer, dest, ms); }
        else if (dest && (a.yer !== v.yer || Math.abs(dest.x - v.dest.x) + Math.abs(dest.z - v.dest.z) > 0.01)) {
          // the Otel: a walk to one's own room ('otele') and the walk back in from it ('otelden')
          if (OTEL.test(a.yer || '') && !OTEL.test(v.yer || '')) events.push({ t: 'otele', id: a.id, yer: a.yer });
          if (OTEL.test(v.yer || '') && !OTEL.test(a.yer || '')) events.push({ t: 'otelden', id: a.id });
          if (still || v.a.tur === 'ozet') this.placeAt(v, a.yer, dest); else this.walkTo(v, a.yer, dest, ms);
        }
      }
      v.a = a;
    }
    for (const [id, v] of this.v) if (!seen.has(id)) { if (!v.fading) events.push({ t: 'kayboldu', id, yer: v.yer, walking: !!v.walk }); this.bitmis.push([id, v.stats]); this.v.delete(id); }
    return events;
  }
  // advance every walker by dt seconds; returns nothing (stats in v.stats)
  advance(dt, gunduz = true) {
    for (const v of this.v.values()) {
      v.stats.ticks++;
      if (gunduz) v.stats.gunTick = (v.stats.gunTick || 0) + 1;
      if (!v.walk) continue;
      v.stats.walkMs += dt * 1000;
      if (gunduz) v.stats.gunWalkMs = (v.stats.gunWalkMs || 0) + dt * 1000;
      v.walk.s += YURUME_HIZI * dt;
      const w = yolKonumu(v.walk.yol, v.walk.s, this.wk);
      v.pos = { x: w.x, z: w.z };
      v.walk.sonraki = w.sonraki;
      if (w.bitti) { v.walk = null; v.stats.arrivals++; }
    }
  }
  // true when the actor stands at its place (not walking)
  arrived(id) { const v = this.v.get(id); return !!v && !v.walk; }
}
