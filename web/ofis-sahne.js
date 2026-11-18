// Pure helpers of the 3D office scene (no DOM, no three.js): which way a character faces at a place, small offsets for
// actors that share a place, the label text and class, which actors get a label, walking along a path, and the rows
// of the workers' board (modelSatirlari: the side panel's "Çalışanlar" list and the live pill popover's).
// web/scene.js and web/app.js draw with them; tested with node in test/test_web.py.
//
// Angles are three.js rotation.y values for a character that faces +z at angle 0: facing (dx, dz) = atan2(dx, dz).
// Every text returned here is a plain string for textContent, never HTML.
import {
  DEFAULT_SAHNE, GUVENLIK_UNVAN, UNVAN, denetciAdi, donusMetni, guvenlikSatiriMi, isModeli, modelAilesi,
  ucretsizDenetciMi, unvanOf, yol, zamanMs, nowMs, enUzunCalisan, ofisSaati, ogleMi, SOSYAL_EKIBI, calismaSuresi,
  BILGI_PERSONELI, yuzdeMetni, EN_UZUN_MIN_MS, katmanModeli, onayAdimi, vardiya, nobetEkibi, NOBET_EKIPLERI, VARDIYALAR,
  VARDIYA_DK, nobetPlani, kimNerede, ekipVardiyasi, gunTuru, tatil, mesaiAraligi, MUDURLUKLER, mudurId, isDepartmani, planIsi, panelIncelemesi, GENEL_MUDUR,
  GUVENLIK, IT_EKIBI, testerUnvani, rolMetni, uzmanlikEki, UZMANLIK_BASLIK, UZMANLIK_SIRA, TESIS_PERSONELI, denetciListesi,
  DEKOR_EKIP, DEGERLENDIRME_EKIBI, degerlendirmeDurumu, ogunPencereleri, fazlaIsciSayisi, ARGE_PROJESI, sahip,
  bakilacakIsler,
} from './ofis-davranis.js';
import { postofficeWarnings, stepText, tokenMetni, tokenSayisi, usdText } from './ofis-text.js';
import { t as T } from './i18n.js'; // phase 1: only the NPC chat box's texts (npcSohbetKutusu, npcSohbetSonucu)

// world units per second (defined in ofis-davranis.js, which times the duty trips with it); the 4-project floor is about
// 144 x 93 units, so a walk across it takes about 40 s
export { YURUME_HIZI } from './ofis-davranis.js';
export const ETIKET_EN_COK = 24; // labels on screen at once (the rest of the actors are still drawn)
export const OFSET_YARICAP = 0.75; // two robots on one spot stand apart (a body is about 1 unit wide)

// Places where a character sits (a chair is drawn there); everywhere else it stands.
const OTURAN = new Set(['masa', 'mudur-masasi', 'sandalye', 'bekleme', 'tabure', 'resepsiyon', 'kafe', 'puf', 'bank']);

export function planAnahtari(plan) {
  return plan ? `${(plan.projeler || []).join('|')}#${plan.masa_sayisi}#${(plan.denetciler || []).join(',')}` : '';
}

// The look of an external auditor (shell and trim colour): Codex teal; each free reviewer its own colour, distinct
// from Codex and from the Claude families' shells; an unknown name a stable one from a small palette.
const DENETCI_RENK = {
  codex: { shell: '#C9E4DE', trim: '#57A497' },
  glm: { shell: '#F6DCCB', trim: '#C0714A' },
  deepseek: { shell: '#D6DCF5', trim: '#5468B8' },
  antigravity: { shell: '#D9DEE6', trim: '#55657E' }, // Antigravity (agy): slate, distinct from every Claude shell
  guvenlik: { shell: '#F5D5D2', trim: '#B5483F' }, // the security reviewer
};
const DENETCI_YEDEK = [{ shell: '#F3D6E4', trim: '#A85482' }, { shell: '#E5E9C8', trim: '#7E8A3A' },
  { shell: '#D8EEF6', trim: '#3E8AA8' }];
export function denetciRenk(ad) {
  if (DENETCI_RENK[ad]) return { ...DENETCI_RENK[ad] };
  let h = 0;
  for (const ch of String(ad || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return { ...DENETCI_YEDEK[h % DENETCI_YEDEK.length] };
}

export function oturmaYeri(plan, id) {
  const n = plan && plan.dugumler && plan.dugumler[id];
  return !!n && OTURAN.has(n.tur);
}

const toward = (from, to) => Math.atan2(to.x - from.x, to.z - from.z);

// The angle a character takes when it arrives at node `id`; null = keep the walking direction (corridors, doors).
// A bed's turn (0: pillow at the back wall; PI: a bed of the Dinlenme odası's front row, pillow at the curtain).
export function yatakAcisi(plan, id) {
  const n = plan && plan.dugumler && plan.dugumler[id];
  if (!n) return 0;
  const room = (plan.odalar || []).find((r) => r.id === n.oda);
  return room && n.oda === 'dinlenme' && n.z > room.z + room.d / 2 ? Math.PI : 0;
}
export function yuzAcisi(plan, id) {
  const nodes = plan && plan.dugumler;
  const n = nodes && nodes[id];
  if (!n) return null;
  switch (n.tur) {
    case 'masa': case 'mudur-masasi': case 'yardimci': case 'bekleme': case 'resepsiyon': case 'puf':
      return 0; // the desk (or the room) is in front, towards the camera
    case 'tabure': // a tea-corner stool faces its round table (a café chair its table, a player its game)
    case 'kafe': case 'oyun-yer': case 'bank': // a terrace bench seat faces the terrace
      return n.hedef ? Math.atan2(n.hedef[0] - n.x, n.hedef[1] - n.z) : null;
    case 'nobet': return nodes.asansor ? toward(n, nodes.asansor) + Math.PI * 0.6 : 0; // the guard faces the hall
    case 'kursu': return 0; // the conference hall's lectern faces the audience (towards the camera)
    case 'sandalye': { // meeting and canteen chairs face the table in the middle of their room / their band's table
      if (n.oda === 'konferans') return Math.PI; // the conference hall's chairs face the screen on its back wall
      const masalar = n.oda === 'yemekhane' && Array.isArray(plan.yemek_masalari) ? plan.yemek_masalari : [];
      if (masalar.length) {
        const t = masalar.reduce((b, m) => (Math.abs(m[2] - n.z) < Math.abs(b[2] - n.z) ? m : b), masalar[0]);
        return n.z > t[2] ? Math.PI : 0;
      }
      const room = (plan.odalar || []).find((r) => r.id === n.oda);
      return room && n.z > room.z + room.d / 2 ? Math.PI : 0;
    }
    case 'kuyruk': return nodes['ceo-kapi'] ? toward(n, nodes['ceo-kapi']) : null;
    case 'ayakta': return nodes['cay-ocagi-tezgah'] ? toward(n, nodes['cay-ocagi-tezgah']) : null;
    case 'tezgah': return Math.PI; // the counter stands against the back wall
    case 'kabin': return Math.PI; // the server room's cabinets stand against its back wall
    case 'yan': {
      const desk = nodes[id.replace(/-yan$/, '')];
      return desk ? toward(n, desk) : null;
    }
    case 'yatak': { // a sleeper lies with its head on the pillow: the back row's at the back wall, the front row's at
      // the curtain (yatakAcisi; web/scene.js turns the bed the same way)
      return yatakAcisi(plan, id);
    }
    case 'ayak': { // the foot of a bed: facing it
      const bed = nodes[id.replace(/-ayak$/, '')];
      return bed ? toward(n, bed) : null;
    }
    case 'asansor': return Math.PI; // the lift doors are in the lobby's back wall
    case 'servis': // the Yemekhane sorumlusu: the sink in front, the counter behind, a table's end to its left
      // the kitchen's stove and fridge stand against the back wall like the sink
      return id === 'yemekhane-bulasik' || id === 'yemekhane-ocak' || id === 'yemekhane-dolap' ? 0
        : id === 'yemekhane-servis' ? Math.PI : -Math.PI / 2;
    default: return null;
  }
}

// Actors on the same place get a small deterministic ring offset (sorted by id); a lone actor and a "+N" stay on
// the node.
// Returns Map id -> [dx, dz].
export function ortakOfsetler(actors, r = OFSET_YARICAP) {
  const by = new Map();
  const out = new Map();
  for (const a of actors || []) {
    if (!a || !a.id || !a.yer) continue;
    // a "+N" stand-in has no body: it never pushes a character off its spot (its label is separated on screen)
    if (a.tur === 'ozet') { out.set(a.id, [0, 0]); continue; }
    if (!by.has(a.yer)) by.set(a.yer, []);
    by.get(a.yer).push(a.id);
  }
  for (const ids of by.values()) {
    ids.sort();
    if (ids.length === 1) { out.set(ids[0], [0, 0]); continue; }
    ids.forEach((id, i) => {
      const t = (i / ids.length) * Math.PI * 2;
      out.set(id, [+(Math.cos(t) * r).toFixed(3), +(Math.sin(t) * r).toFixed(3)]);
    });
  }
  return out;
}

function kisa(text, max) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

// The label's group class (style.css .desk-label.grup-*), so the groups read apart at a glance: the AI workers (jobs,
// sessions, helpers, the kadro, the CEO), the auditors (Codex, the free reviewers, the security reviewer, the hakem),
// the staff (tea server, guard, secretary); a "+N" has none.
export function etiketGrubu(a) {
  if (!a || a.tur === 'ozet') return '';
  if (a.tur === 'sus') return 'grup-personel';
  if (a.denetci || a.hakem) return 'grup-denetci';
  return 'grup-ajan';
}

// Whether an actor is really at work now (the owner, 2026-11-14: "aynı durum olmalı çalışanlar için o anda"): staff on a
// duty (`gorevde` / a symbol); an agent, the CEO, a kadro member, an auditor or a helper typing on its job, review or
// decision (poz yaziyor / toplanti, the test icon), on a real duty (`gorevde`: a hand-over, a plan talk) or carrying a
// file (`dosya`: a hand-over leg, findings, an approval summary — every one from the state). A question, a problem or a
// finish keeps its own colour (durumSinifi checks those first). Its label is the green "is-gorevde" pill.
export function calisiyorMu(a) {
  if (!a || a.tur === 'ozet') return false;
  if (a.tur === 'sus') return !!(a.gorevde || a.simge);
  if (a.simge === '?' || a.simge === '!' || a.simge === 'kirmizi' || a.poz === 'el-kaldirmis' || a.poz === 'basi-onde') return false;
  if (a.poz === 'evde' || a.poz === 'uyuyor' || a.poz === 'yatiyor' || a.poz === 'yemek') return false;
  return a.poz === 'yaziyor' || a.poz === 'toplanti' || a.simge === 'test' || !!a.gorevde || !!a.dosya;
}

// The label's state class (style.css .desk-label.is-*): `is-gorevde` (the green pill) whenever calisiyorMu.
export function durumSinifi(a) {
  if (!a) return '';
  // staff: a real duty from the state (a question to carry, a visit, a greeting, a massage: `gorevde` / a symbol) gets the
  // green "working" pill; otherwise the plain staff look
  if (a.tur === 'sus') return a.gorevde || a.simge ? 'is-sus is-gorevde' : 'is-sus';
  if (a.tur === 'ozet') return 'is-ozet';
  if (a.simge === 'kirmizi' || a.poz === 'basi-onde') return 'is-stuck';
  if (a.simge === '?' || a.simge === '!' || a.poz === 'el-kaldirmis') return 'is-waiting';
  if (a.simge === '✓' || a.poz === 'kutluyor') return 'is-done';
  if (calisiyorMu(a)) return 'is-working is-gorevde';
  if (a.poz === 'evde' || a.poz === 'uyuyor' || a.poz === 'yatiyor') return 'is-sleeping';
  if (a.poz === 'lobide') return 'is-queued';
  return 'is-idle';
}

// Actors whose label shows its state text even at the default zoom: the CEO, a question / permission / problem,
// working agents and an agent at home (quota). The others show their name only until zoomed in (`yakin`) or hovered.
export function tamEtiket(a) {
  if (!a) return false;
  if (a.tur === 'ceo') return true;
  if (a.simge === '?' || a.simge === '!' || a.simge === 'kirmizi' || a.simge === 'kaldi') return true;
  if (a.dosya && (a.tur === 'ceo' || a.denetci)) return true; // carrying a file to someone (a real event)
  if (a.tur === 'ajan' && a.poz === 'evde') return true; // "Evde · 16:30'da döner": why the desk is empty
  if (a.tur === 'sus' && a.gorevde) return true; // staff on a real duty: "Sekreter · karar götürüyor"
  return a.tur === 'ajan' && (a.poz === 'yaziyor' || a.poz === 'toplanti' || a.simge === 'test');
}

// "Kıdemli (Opus)" -> "Kıdemli", "2 yardımcı (Haiku)" -> "2 yardımcı": the floor labels and the Çalışanlar list
// show the role only (owner decision 2026-11-12); a Claude model in parentheses is dropped, anything else ("(ücretsiz)") stays.
export function rolAdi(text) {
  return String(text == null ? '' : text).replace(/\s*\((?:haiku|sonnet|opus|fable)\)/gi, '').trim();
}

// {ad, durum, sinif, kucuk}: the bold name, a short state text and the classes. Inside its own team area an agent's
// name drops the project (the floor shows it); elsewhere (lobby, CEO door, meeting room, tea) it keeps it. A helper's
// label is small (name only unless it just finished); a walking actor shows only its name (`yuruyor`). At the default
// zoom (`yakin` false) only tamEtiket actors keep the state text, unless the label is hovered (`uzerinde`).
export function etiketBilgisi(a, { yuruyor = false, yakin = true, uzerinde = false } = {}) {
  const sinif = durumSinifi(a);
  const kucuk = a.tur === 'alt-ajan' || a.tur === 'sus';
  let ad = String(a.etiket || '');
  const own = a.proje && typeof a.yer === 'string' && a.yer.startsWith(`ekip-${a.proje}-`);
  if (own && a.tur === 'ajan' && ad.startsWith(`${a.proje} · `)) ad = ad.slice(a.proje.length + 3);
  if (a.tur === 'alt-ajan') ad = ad.replace(/^Yardımcı · /, 'Yardımcı ');
  let durum = kisa(a.durum_metni, a.tur === 'ozet' ? 30 : 32);
  // staff without a duty show their name only ("atanmış iş yok", "masasında"… never on the floor; owner decision 2026-11-12)
  const personelBos = a.tur === 'sus' && !a.gorevde && !a.simge;
  if (personelBos) durum = '';
  if (a.tur === 'alt-ajan' && a.simge !== '✓') durum = '';
  if (yuruyor && a.tur !== 'ozet') durum = '';
  if (!yakin && !uzerinde && a.tur !== 'ozet' && !tamEtiket(a)) durum = '';
  if (uzerinde && a.tur !== 'ozet' && !personelBos) durum = kisa(a.durum_metni, 60);
  // a quiet actor (idle staff, an idle auditor, decoration, a queued job…) shows a small name-only label at the
  // default zoom — its short name when it has one; hover or zoom brings the full label back
  const kompakt = !yakin && !uzerinde && a.tur !== 'ozet' && a.tur !== 'ceo' && !tamEtiket(a);
  if (kompakt && a.kisa_etiket) ad = String(a.kisa_etiket);
  ad = rolAdi(ad); // role first: the model only in the character card / tooltip
  return { ad: kisa(ad, 40), durum, sinif, kucuk, kompakt, grup: etiketGrubu(a) };
}

const ONCELIK = (a) => {
  if (a.tur === 'ceo') return 0;
  if (a.tur === 'sus') {
    // staff on duty (the Sekreter with a question, a visit, a greeting) before idle agents' helpers and other staff;
    // informational staff (facility desks, project residents, the social media team) last of all
    if (a.simge || a.gorevde) return 3.5;
    return BILGI_PERSONELI(a) ? 7 : 6;
  }
  if (a.simge === '?' || a.simge === '!' || a.simge === 'kirmizi') return 1;
  if (a.tur === 'ajan' && (a.poz === 'yaziyor' || a.simge === 'test' || a.poz === 'kutluyor')) return 2;
  if (a.tur === 'ajan') return 3;
  if (a.tur === 'ozet') return 4;
  if (a.tur === 'alt-ajan') return 5;
  return 6; // decorative
};

// The ids that get a label: the most important first (CEO, a question or a problem, working agents, other agents,
// summaries, helpers, decoration), at most `max`.
export function etiketSecimi(actors, max = ETIKET_EN_COK) {
  const list = (actors || []).filter((a) => a && a.id).slice()
    .sort((a, b) => ONCELIK(a) - ONCELIK(b) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return new Set(list.slice(0, Math.max(0, max)).map((a) => a.id));
}

// The points of a walk from the current position `from` ({x, z}) through the graph (fromNode -> toNode) to the final
// spot `to` ({x, z}, the node plus the actor's offset). Returns {pts: [[x, z]...], ids: [node id per point or null]}.
// An unknown node falls back to a straight line.
export function yuruyusYolu(plan, from, fromNode, toNode, to) {
  const path = fromNode && toNode ? yol(plan, fromNode, toNode) : [];
  const pts = [[from.x, from.z]];
  const ids = [null];
  const push = (x, z, id) => {
    const last = pts[pts.length - 1];
    if (Math.hypot(last[0] - x, last[1] - z) < 1e-3) { ids[ids.length - 1] = id; return; }
    pts.push([x, z]); ids.push(id);
  };
  for (let i = 0; i < path.length; i++) {
    if (i === path.length - 1) break; // the last node is replaced by the actor's own spot
    push(path[i].x, path[i].z, path[i].id);
  }
  push(to.x, to.z, toNode || null);
  return { pts, ids };
}

// The scene's frame cap (web/scene.js loop): about 60 fps only while the camera moves, about 30 while someone walks or
// the ping-pong ball flies, about 9 at rest (only the idle bob moves then).
export const FPS = { kamera: 60, hareket: 30, dinlenme: 9 };
export function hedefFps({ kamera = false, yuruyen = false, top = false } = {}) {
  return kamera ? FPS.kamera : yuruyen || top ? FPS.hareket : FPS.dinlenme;
}

// Precomputes the cumulative lengths of a walk.
export function yolHazirla(walk) {
  const cum = [0];
  for (let i = 1; i < walk.pts.length; i++) {
    const [x0, z0] = walk.pts[i - 1];
    const [x1, z1] = walk.pts[i];
    cum.push(cum[i - 1] + Math.hypot(x1 - x0, z1 - z0));
  }
  return { ...walk, cum, toplam: cum[cum.length - 1] };
}

// The position after walking `s` units: writes {x, z, aci, bitti, sonraki} into `out` (no allocation in the frame
// loop). `sonraki` = the node id the actor walks towards (to reroute from it), aci = the walking direction.
export function yolKonumu(walk, s, out) {
  const { pts, cum, toplam } = walk;
  if (pts.length === 1 || s >= toplam) {
    const last = pts[pts.length - 1];
    out.x = last[0]; out.z = last[1]; out.bitti = true; out.sonraki = walk.ids[walk.ids.length - 1];
    if (pts.length > 1) {
      const prev = pts[pts.length - 2];
      out.aci = Math.atan2(last[0] - prev[0], last[1] - prev[1]);
    }
    return out;
  }
  let i = 1;
  while (i < cum.length - 1 && cum[i] < s) i++;
  const seg = cum[i] - cum[i - 1] || 1;
  const k = Math.max(0, Math.min(1, (s - cum[i - 1]) / seg));
  const [x0, z0] = pts[i - 1];
  const [x1, z1] = pts[i];
  out.x = x0 + (x1 - x0) * k;
  out.z = z0 + (z1 - z0) * k;
  out.aci = Math.atan2(x1 - x0, z1 - z0);
  out.bitti = false;
  out.sonraki = walk.ids[i];
  return out;
}

// Shortest signed turn from angle a to b (radians, in -PI..PI).
export function aciFarki(a, b) {
  let d = (b - a) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return d;
}

// A label's place in the de-overlap pass (etiketleriYerlestir): {on, kalici}. `on` = lower is placed first (stays at
// its robot); `kalici` = never collapsed into a "+N" (the owner, 2026-11-14: a working / waiting label is never hidden).
// Order: the hovered label, a question / permission / problem (amber, red), really at work (green), the CEO, a finish,
// summaries, other agents, auditors and kadro, helpers, staff on duty, idle staff, decoration.
export function etiketOnceligi(a, { uzerinde = false } = {}) {
  if (!a) return { on: 9, kalici: false };
  if (uzerinde) return { on: -1, kalici: true };
  if (a.tur === 'ozet') return { on: 4, kalici: false };
  if (a.simge === '?' || a.simge === '!' || a.simge === 'kirmizi' || a.poz === 'el-kaldirmis' || a.poz === 'basi-onde') {
    return { on: 0, kalici: true };
  }
  if (calisiyorMu(a)) return { on: 1, kalici: true };
  if (a.tur === 'ceo') return { on: 2, kalici: true };
  if (a.simge === '✓' || a.poz === 'kutluyor') return { on: 3, kalici: false };
  if (a.tur === 'ajan') return { on: 5, kalici: false };
  if (a.tur === 'alt-ajan') return { on: 7, kalici: false };
  if (a.tur === 'sus') return { on: BILGI_PERSONELI(a) ? 9 : 8, kalici: false };
  return { on: 6, kalici: false }; // kadro, auditors, the hakem
}

// Label de-overlap with a "+N" overflow (the owner, 2026-11-14: names piled up unreadable in the meeting room / tea corner).
// items[i] = {x, y, w, h, on, kalici, gizli}: x = centre, y = bottom edge (px, before shifting), `on` / `kalici` from
// etiketOnceligi. The labels are placed by priority (`on`, then the one lowest on the screen, then the index: an
// O(n log n) sort); a label that overlaps one already placed is stacked above it with a `bosluk` px gap. When that
// would lift it more than `max` px from its robot it is collapsed into a "+N" chip on the label it first overlapped —
// unless it is `kalici`, which keeps stacking (never hidden). Writes dy (<= 0) and toplu (the index of the label whose
// chip holds it, or -1). Fills `cipler` (reused) with {sahip, uyeler: [index…]} in placing order and returns their
// count. Hidden labels (gizli) take no part. `order` and `cipler` are reusable arrays (little allocation per frame).
export function etiketleriYerlestir(items, n, order, cipler, { bosluk = 2, max = 48 } = {}) {
  order.length = n;
  for (let i = 0; i < n; i++) {
    order[i] = i;
    items[i].dy = 0; items[i].toplu = -1;
  }
  order.sort((p, q) => {
    const a = items[p], b = items[q];
    return ((a.on ?? 9) - (b.on ?? 9)) || (b.y - a.y) || (p - q);
  });
  let nc = 0;
  for (let i = 0; i < n; i++) {
    const ai = order[i];
    const a = items[ai];
    if (a.gizli) continue;
    let ilk = -1; // the first placed label it overlapped: the chip's owner if it collapses
    for (let pass = 0; pass <= i; pass++) {
      let moved = false;
      for (let j = 0; j < i; j++) {
        const bi = order[j];
        const b = items[bi];
        if (b.gizli || b.toplu >= 0) continue;
        const ab = a.y + a.dy;
        const bb = b.y + b.dy;
        if (Math.abs(a.x - b.x) * 2 < a.w + b.w && ab - a.h < bb && ab > bb - b.h) {
          if (ilk < 0) ilk = bi;
          a.dy = bb - b.h - bosluk - a.y;
          moved = true;
        }
      }
      if (!moved) break;
      if (a.dy < -max && !a.kalici) break;
    }
    if (a.dy < -max && !a.kalici && ilk >= 0) {
      a.dy = 0;
      a.toplu = ilk;
      let c = 0;
      while (c < nc && cipler[c].sahip !== ilk) c++;
      if (c === nc) {
        if (!cipler[nc]) cipler[nc] = { sahip: -1, uyeler: [] };
        cipler[nc].sahip = ilk; cipler[nc].uyeler.length = 0; nc++;
      }
      cipler[c].uyeler.push(ai);
    }
  }
  return nc;
}

// --- the workers' list (Çalışanlar) ---

export const MODEL_SIRASI = ['haiku', 'sonnet', 'opus', 'fable', 'codex'];
const KADRO = ['haiku', 'sonnet', 'opus', 'fable'];
const MODEL_ADI = { haiku: 'Haiku', sonnet: 'Sonnet', opus: 'Opus', fable: 'Fable', codex: 'Codex' };
const DURUMLAR = new Set(['hazir', 'calisiyor', 'kota', 'hata', 'bilinmiyor']);
export const HATA_EN_COK = 60;

function kisaMetin(text, max) {
  const t = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

// /api/state.modeller -> one row per model family, always in MODEL_SIRASI order (the Claude models, then Codex), then
// one row per free reviewer of the review panel in the server's order (only those the server lists):
// [{model, ad, unvan, durum, metin, kisa, ton, ucretsiz}], ton = ok | busy | warn | error | muted. `now` (ms, Date or
// ISO) and sahne.saat_dilimi (default Europe/Istanbul; fixed UTC+3 when the zone is unknown) only format the return
// time. Honest by construction: "kota" only for durum kota; a missing model, an unknown durum or unreadable data is
// "durumu bilinmiyor". Plain strings for textContent / canvas text, never HTML.
export function modelSatirlari(modeller, now, sahne) {
  const tz = (sahne && typeof sahne.saat_dilimi === 'string' && sahne.saat_dilimi) || DEFAULT_SAHNE.saat_dilimi;
  const by = new Map();
  const free = [];
  let guvenlik = null;
  for (const m of Array.isArray(modeller) ? modeller : []) {
    if (guvenlikSatiriMi(m)) { guvenlik = guvenlik || m; continue; }
    if (ucretsizDenetciMi(m)) {
      if (!free.some((x) => x.model === m.model)) free.push(m);
      continue;
    }
    const fam = m && typeof m === 'object' ? modelAilesi(m.model) : '';
    if (fam && !by.has(fam)) by.set(fam, m);
  }
  let ms = null;
  try { ms = nowMs(now); } catch (e) { ms = null; }
  const row = (m, model, ad, unvan, ucretsiz, rol = ad, modelAdi = '') => {
    const durum = DURUMLAR.has(m.durum) ? m.durum : 'bilinmiyor';
    const n = Math.max(0, Math.floor(Number(m.calisan) || 0));
    const durumlar = [];
    if (n > 0 || durum === 'calisiyor') durumlar.push(`${Math.max(n, 1)} çalışıyor`);
    let ton = 'muted';
    if (durum === 'hazir' || durum === 'calisiyor') {
      durumlar.push('hazır');
      ton = durum === 'calisiyor' ? 'busy' : 'ok';
    } else if (durum === 'kota') {
      durumlar.push('kota doldu');
      ton = 'warn';
      const t = zamanMs(m.donus, tz);
      if (t !== null && ms !== null) durumlar.push(t > ms ? donusMetni(t, ms, tz) : 'dönüş saati geçti');
    } else if (durum === 'hata') {
      const son = kisaMetin(m.son_hata, HATA_EN_COK);
      durumlar.push(son ? `hata: ${son}` : 'son çağrı hata verdi');
      ton = 'error';
    } else {
      durumlar.push('durumu bilinmiyor');
    }
    // office vocabulary (the owner, 2026-11-11): the role first, the model only in parentheses — "Stajyer (Haiku)";
    // a reviewer by its name ("Codex", "DeepSeek · ücretsiz", "Güvenlik denetçisi (Sonnet)").
    // kisa = the state without the name (the popover shows the name in its own column)
    const grup = KADRO.includes(model) ? 'kadro' : 'denetci';
    const adlar = ucretsiz ? [ad, 'ücretsiz'] : [ad];
    // rol / rol_metin: the role only (the side panel); pano_ad: the live pill popover's name column, role + model for a
    // Claude worker ("Uzman · Sonnet", "Güvenlik denetçisi · Sonnet"; owner decision 2026-11-12), a reviewer by its name;
    // ipucu: the tooltip naming the model, or a reviewer's role ("GLM · Dış denetçi · ücretsiz")
    return { model, ad, unvan, grup, durum, metin: [...adlar, ...durumlar].join(' · '), kisa: durumlar.join(' · '), ton,
      ucretsiz, rol, rol_metin: [rol, ...(ucretsiz ? ['ücretsiz'] : []), ...durumlar].join(' · '),
      pano_ad: modelAdi ? `${rol} · ${modelAdi}` : rol,
      ipucu: modelAdi ? `${rol} · model: ${modelAdi}`
        : unvan && unvan !== rol ? [rol, unvan, ...(ucretsiz ? ['ücretsiz'] : [])].join(' · ') : rol };
  };
  const kadro = (fam) => `${UNVAN[fam].unvan} (${MODEL_ADI[fam]})`;
  const gm = guvenlik ? MODEL_ADI[modelAilesi(guvenlik.ajan_modeli)] || 'Sonnet' : '';
  return [...KADRO.map((fam) => row(by.get(fam) || {}, fam, kadro(fam), UNVAN[fam].unvan, false, UNVAN[fam].unvan,
    MODEL_ADI[fam])),
    row(by.get('codex') || {}, 'codex', MODEL_ADI.codex, UNVAN.codex.unvan, false),
    ...free.map((m) => row(m, m.model, denetciAdi(m.model), UNVAN.codex.unvan, true)),
    ...(guvenlik ? [row(guvenlik, guvenlik.model, `${GUVENLIK_UNVAN} (${gm})`, GUVENLIK_UNVAN, false, GUVENLIK_UNVAN,
      gm)] : [])];
}

// The "Çalışanlar" groups in order: [{grup, baslik, rows}] (the side panel's subheadings and the popover's).
export const CALISAN_GRUPLARI = { kadro: 'Kadro', denetci: 'Denetçiler' };
export function calisanGruplari(rows) {
  const out = [];
  for (const r of Array.isArray(rows) ? rows : []) {
    const g = r && r.grup === 'kadro' ? 'kadro' : 'denetci';
    if (!out.length || out[out.length - 1].grup !== g) out.push({ grup: g, baslik: CALISAN_GRUPLARI[g], rows: [] });
    out[out.length - 1].rows.push(r);
  }
  return out;
}

// "Kıdemli (Opus)": a worker's role with its model in parentheses (the "Şu an iş başında" table, job cards); a
// reviewer "Dış denetçi (Codex)"; the role alone when the model is unknown.
export function calisanAdi(unvan, model) {
  const u = String(unvan || '').trim();
  const fam = modelAilesi(model);
  const m = MODEL_ADI[fam] || (model && model !== '—' ? denetciAdi(model) : '');
  if (!u) return m || '—';
  if (!m || u.includes('(')) return u;
  return `${u} (${m})`;
}

// Role only (the owner, 2026-11-12: the model only in the card / tooltip): "Kıdemli", "Hakem", "Güvenlik denetçisi"; a
// reviewer by its name ("Codex", "GLM"); "—" when nothing is known.
export function calisanRolu(unvan, model) {
  const u = rolAdi(unvan);
  const fam = modelAilesi(model);
  if (fam && fam !== 'codex') return u || UNVAN[fam].unvan;
  if (model && model !== '—' && (!u || u === UNVAN.codex.unvan)) return denetciAdi(model);
  return u || '—';
}
// The tooltip naming the model: "Kıdemli · model: Opus"; a reviewer just its name.
export function calisanIpucu(unvan, model) {
  const rol = calisanRolu(unvan, model);
  const fam = modelAilesi(model);
  return fam && fam !== 'codex' && MODEL_ADI[fam] ? `${rol} · model: ${MODEL_ADI[fam]}` : rol;
}

// One short line for the collapsed "Çalışanlar" section: the models that need attention, else "hepsi hazır".
export function modelOzeti(rows) {
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) return 'durum yükleniyor';
  const names = (d) => list.filter((r) => r.durum === d).map((r) => r.ad || r.model);
  const out = [];
  for (const [d, text] of [['kota', 'kota doldu'], ['hata', 'hata'], ['bilinmiyor', 'bilinmiyor']]) {
    const n = names(d);
    if (n.length) out.push(`${n.join(', ')}: ${text}`);
  }
  return out.length ? out.join(' · ') : 'hepsi hazır';
}

// --- "Şu an iş başında": the top bar's popover (one row per active agent) ---

export const CALISANLAR_BOS = 'Şu an iş başında kimse yok.';
export const CALISANLAR_BASLIK = ['Proje', 'İş', 'Çalışan', 'Katman', 'Durum', 'Süre', 'Kullanım', 'Yardımcı'];
const AKTIF_ISLER = new Set(['baslatiliyor', 'calisiyor', 'kontrolde', 'incelemede', 'karar-bekliyor']);
const ACIK_OTURUM = new Set(['busy', 'waiting']);
const IS_EN_COK = 48;

const notKoku = (note) => String(note || '').replace(/\.md$/, '');

// "<1 dk", "12 dk", "1 sa 5 dk"; "—" when the start is unknown or in the future.
export function sureMetni(baslangic, ms) {
  if (baslangic === null || ms === null || !Number.isFinite(baslangic) || baslangic > ms + 60000) return '—';
  const dk = Math.floor(Math.max(0, ms - baslangic) / 60000);
  if (dk < 1) return '<1 dk';
  return dk < 60 ? `${dk} dk` : `${Math.floor(dk / 60)} sa ${dk % 60} dk`;
}

// Open subagents: "2 yardımcı (haiku, sonnet)"; "—" when none.
export function yardimciMetni(list) {
  const open = (Array.isArray(list) ? list : []).filter((x) => x && x.id && !x.bitti);
  if (!open.length) return '—';
  const fams = [...new Set(open.map((x) => modelAilesi(x.model)).filter(Boolean))];
  return `${open.length} yardımcı${fams.length ? ` (${fams.map((f) => MODEL_ADI[f] || f).join(', ')})` : ''}`;
}

function harcamaMetni(t) {
  if (!t) return '—';
  const hasBudget = t.budget != null && t.budget !== '';
  if ((t.spent == null || t.spent === '') && !hasBudget) return '—';
  const tok = tokenMetni(t.tokens);
  return (tok ? `${tok} · ` : '') +
    `${usdText(t.spent === '' || t.spent == null ? 0 : t.spent)} / ${hasBudget ? usdText(t.budget) : '?'}`;
}

function isDurumu(t, s) {
  if (s && s.status === 'waiting') return 'izin bekliyor';
  const calisiyor = !!s && (s.status === 'busy' || yardimciMetni(s.alt_ajanlar) !== '—');
  switch (t && t.status) {
    case 'kontrolde': return 'Kontrol';
    case 'karar-bekliyor': return `${sahip('in')} cevabını bekliyor`;
    case 'baslatiliyor': return 'başlıyor';
    case 'incelemede': return calisiyor ? 'inceliyor' : 'incelemede';
    default:
      if (calisiyor) return 'çalışıyor';
      return s ? 'sessiz' : 'oturum görünmüyor';
  }
}

// state (/api/state) -> rows [{id, proje, is, unvan, model, katman, durum, sure, harcama, yardimci, ac, yolNot}], CEO first;
// yolNot = the open job's note on its own row only (app.js draws its progress line there); none on the CEO's, a
// session's without an open job, a reviewer's or the hakem's row.
// ac = {note} (the job's detail) | {ceo: true} (the CEO card). Active = a job in AKTIF_ISLER, a busy or waiting office
// session without such a job, the CEO when busy/waiting or with an open subagent, the review panel's reviewers at
// work and the hakem while it weighs their findings (denetimSatirlari).
// Plain strings for textContent, never HTML.
export function calisanlarTablosu(state, now) {
  const st = state || {};
  const sahne = { ...DEFAULT_SAHNE, ...(st.sahne || {}) };
  const tz = sahne.saat_dilimi;
  const ofset = Number.isFinite(sahne.sunucu_utc_ofset_dk) ? sahne.sunucu_utc_ofset_dk : null;
  let ms = null;
  try { ms = nowMs(now); } catch (e) { ms = null; }
  const rows = [];

  const ceo = st.ceo || {};
  const ceoYardimci = yardimciMetni(ceo.alt_ajanlar);
  if (ceo.state === 'busy' || ceo.state === 'waiting' || ceoYardimci !== '—') {
    rows.push({ id: 'ceo', proje: 'Ofis', is: `${sahip()} ile konuşma, işlerin dağıtımı`, unvan: UNVAN.ceo.unvan,
      model: modelAilesi(ceo.model) || '—', katman: '—',
      durum: ceo.state === 'waiting' ? 'izin bekliyor' : ceo.state === 'busy' && ceo.tur_kapaniyor ? 'Cevap verdi · tur kapanıyor' : 'çalışıyor', sure: '—',
      harcama: ceo.cost_today ? `bugün ${tokenMetni(ceo.usage_today) ? `${tokenMetni(ceo.usage_today)} · ` : ''}${usdText(ceo.cost_today)}` : '—',
      yardimci: ceoYardimci, ac: { ceo: true } });
  }

  const tasks = new Map();
  const add = (t) => { if (t && t.note && !tasks.has(notKoku(t.note))) tasks.set(notKoku(t.note), t); };
  (st.tasks || []).forEach(add);
  (st.board || []).forEach(add);
  for (const p of st.projects || []) (p.tasks || []).forEach(add);
  const sessions = (st.sessions || []).filter((s) => s && s.name);
  const sessionOf = (t) => sessions.find((s) => (s.note && notKoku(s.note) === notKoku(t.note))) ||
    sessions.find((s) => t.session && s.name === t.session) || null;

  // the workflow's approval step is the owner's decision, not an agent's work: it is no row here (its card is)
  const active = [...tasks.values()].filter((t) => AKTIF_ISLER.has(t.status) && !onayAdimi(t)).sort((a, b) => {
    const ka = `${a.started || a.created || ''}|${notKoku(a.note)}`;
    const kb = `${b.started || b.created || ''}|${notKoku(b.note)}`;
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
  const used = new Set();
  const reviews = []; // [{t, base}] of the review panel's jobs (Codex and the free reviewers, no session)
  const baseOf = (t, s) => ({ proje: t.project || (s && s.project) || '—',
    is: kisa(t.title || notKoku(t.note), IS_EN_COK) || '—',
    sure: sureMetni(zamanMs(t.started || t.created, tz, ofset), ms), ac: { note: t.note } });
  for (const t of active) {
    const s = sessionOf(t);
    if (s) used.add(s.name);
    const base = baseOf(t, s);
    if (t.status === 'incelemede' && t.inceleme_yurutucu === 'codex' && !s) {
      reviews.push({ t, base });
      continue;
    }
    const model = modelAilesi(isModeli(t, s, st.katmanlar));
    rows.push({ id: `is:${notKoku(t.note)}`, ...base, unvan: rolMetni(model, t.uzmanlik || (s && s.uzmanlik)), model: model || '—',
      katman: (s && s.tier) || t.tier || '—', durum: isDurumu(t, s), harcama: harcamaMetni(t),
      yardimci: yardimciMetni(s && s.alt_ajanlar), yolNot: t.note });
  }
  for (const s of sessions) {
    if (used.has(s.name) || !ACIK_OTURUM.has(s.status)) continue;
    const model = modelAilesi(s.model);
    rows.push({ id: `oturum:${s.name}`, proje: s.project || '—', is: '—', unvan: rolMetni(model, s.uzmanlik),
      model: model || '—', katman: s.tier || '—', durum: s.status === 'waiting' ? 'izin bekliyor' : 'çalışıyor',
      sure: sureMetni(zamanMs(s.started_at, tz, ofset), ms), harcama: '—', yardimci: yardimciMetni(s.alt_ajanlar),
      ac: s.note ? { note: s.note } : null });
  }
  rows.push(...denetimSatirlari(st.denetim, reviews, tasks, baseOf, st.modeller));
  return rows;
}

// The review panel's rows: with state.denetim (the server's panel marker) one row per reviewer at work and the hakem
// while it weighs the findings, on the job it reviews; without it (an older server) Codex on the first running review.
// A reviewer that is neither Codex nor a free reviewer of state.modeller (e.g. the Claude security reviewer
// "guvenlik") is listed without a price claim.
function denetimSatirlari(denetim, reviews, tasks, baseOf, modeller) {
  const d = denetim && typeof denetim === 'object' ? denetim : null;
  const note = d && typeof d.is === 'string' ? notKoku(d.is) : '';
  const hit = note ? reviews.find((r) => notKoku(r.t.note) === note) : reviews[0];
  const t = hit ? hit.t : (note && tasks.get(note)) || null;
  const base = hit ? hit.base : t ? baseOf(t, null)
    : { proje: '—', is: note ? kisa(note, IS_EN_COK) : '—', sure: '—', ac: note ? { note: `${note}.md` } : null };
  const katman = (t && t.tier) || 'inceleme';
  const free = new Set((Array.isArray(modeller) ? modeller : []).filter(ucretsizDenetciMi).map((m) => m.model));
  const reviewer = (ad) => ({ id: `denetci:${ad}`, ...base,
    unvan: ad === 'guvenlik' ? GUVENLIK_UNVAN : UNVAN.codex.unvan, model: ad, katman, durum: 'inceliyor',
    harcama: ad === 'codex' ? 'fiyat bilinmiyor' : free.has(ad) ? 'ücretsiz' : '—', yardimci: '—' });
  if (!d) return hit ? [reviewer('codex')] : [];
  const out = (Array.isArray(d.denetciler) ? d.denetciler : []).filter((ad) => typeof ad === 'string' && ad)
    .map(reviewer);
  if (typeof d.hakem === 'string' && d.hakem) {
    const fam = modelAilesi(d.hakem);
    out.push({ id: 'hakem', ...base, unvan: 'Hakem', model: fam || kisa(d.hakem, 20), katman,
      durum: 'bulguları tartıyor', harcama: '—', yardimci: '—' });
  }
  return out;
}

// The cells of a row in CALISANLAR_BASLIK order (role only; app.js puts calisanIpucu on the Çalışan cell).
export function calisanHucreleri(r) {
  return [r.proje, r.is, calisanRolu(r.unvan, r.model), r.katman, r.durum, r.sure, r.harcama, rolAdi(r.yardimci) || '—'];
}

// --- room names (small HTML labels at each room's front-left corner; lower priority than the actors' labels) ---

const ODA_ADI = { toplanti: 'Toplantı odası', ceo: 'CEO odası', mudur: 'Genel Müdür odası', denetci: 'Dış denetçiler', 'cay-ocagi': 'Çay ocağı',
  'ortak-alan': 'Ortak alan', oyun: 'Oyun odası', yemekhane: 'Yemekhane', lobi: 'Giriş', uzmanlar: 'Uzmanlar odası',
  'bos-ekip': 'Boş ekip alanı · yeni proje' };

// plan -> [{id, ad, x, z}] in plan coordinates: each room's name at its front-left corner (the corner nearest the
// camera's left), team areas "<proje> ekibi". Plain text.
export function odaEtiketleri(plan) {
  const out = [];
  for (const r of (plan && plan.odalar) || []) {
    const ad = r.tur === 'ekip' ? `${r.proje} ekibi` : ODA_ADI[r.tur] || r.ad || '';
    if (ad) out.push({ id: r.id, ad, x: +(r.x + 0.5).toFixed(2), z: +(r.z + r.d - 0.4).toFixed(2) });
  }
  const y = plan && plan.otel; // the hotel outside the floor
  if (y) out.push({ id: y.id, ad: y.ad, x: +(y.x + 0.5).toFixed(2), z: +(y.z + y.d - 0.4).toFixed(2) });
  return out;
}

// A room name stays only where it overlaps no visible actor label (rect: x = centre, y = bottom edge, w, h in px).
export function odaEtiketiGorunur(rect, actorRects) {
  for (const b of actorRects || []) {
    if (!b || b.gizli || b.toplu >= 0) continue; // a label folded into a "+N" is not on screen
    const by = b.y + (b.dy || 0);
    if (Math.abs(rect.x - b.x) * 2 < rect.w + b.w && rect.y - rect.h < by && rect.y > by - b.h) return false;
  }
  return true;
}

// --- the zoom controls (+ / − / ⟲ buttons at the scene's edge, keys + / − / 0) ---

export const ZOOM_ADIMI = 1.35; // one step in or out

// The camera zoom after one step in (yon > 0) or out (yon < 0), clamped to the camera's [min, max] zoom.
export function sonrakiZoom(zoom, yon, min, max) {
  const z = Number(zoom) > 0 ? Number(zoom) : 1;
  const next = yon > 0 ? z * ZOOM_ADIMI : yon < 0 ? z / ZOOM_ADIMI : z;
  const lo = Number(min) > 0 ? Number(min) : 0;
  const hi = Number(max) > 0 ? Number(max) : Infinity;
  return Math.min(hi, Math.max(lo, next));
}

// A key press -> 'yakin' (+ or =), 'uzak' (- or the minus sign), 'tumu' (0) or null: never with Ctrl / Meta / Alt (the
// browser's own zoom) and never while typing in a field (input, textarea, select, contenteditable).
export function zoomTusu(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey) return null;
  const t = e.target;
  const tag = t && typeof t.tagName === 'string' ? t.tagName.toUpperCase() : '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return null;
  if (e.key === '+' || e.key === '=') return 'yakin';
  if (e.key === '-' || e.key === '−') return 'uzak';
  if (e.key === '0') return 'tumu';
  return null;
}

// --- moving around the floor like a map (drag = pan, right-drag / Shift- or Alt-drag = rotate, arrows / WASD) ---

// The OrbitControls mapping by name (scene.js turns it into THREE.MOUSE / THREE.TOUCH): left drag and one finger pan
// across the floor, right drag rotates within the camera's limits (the wheel and the trackpad are scene.js's own:
// tekerlekTuru; OrbitControls zooms only for touch pinch and the middle-button drag); two
// fingers pinch-zoom and twist-rotate. Shift/Ctrl/Meta + left drag rotates too (OrbitControls swaps PAN and ROTATE
// for them); Alt + left drag is switched by scene.js.
export const FARE_DUGMELERI = Object.freeze({ LEFT: 'PAN', MIDDLE: 'DOLLY', RIGHT: 'ROTATE' });
export const DOKUNMA = Object.freeze({ ONE: 'PAN', TWO: 'DOLLY_ROTATE' });

export const KAYDIRMA_PAYI = 1.5; // world units the view centre may go past the floor's edge (the slab's lip included)

// The rectangle the camera's target may move in: the floor's real bounds ({minX, maxX, minZ, maxZ}, world coordinates,
// the whole floor — common area and project wing) widened by `pay`. Missing or broken bounds -> null (no clamp).
export function hedefSiniri(bounds, pay = KAYDIRMA_PAYI) {
  if (!bounds) return null;
  const { minX, maxX, minZ, maxZ } = bounds;
  if (![minX, maxX, minZ, maxZ].every(Number.isFinite) || minX > maxX || minZ > maxZ) return null;
  const p = Number.isFinite(pay) && pay > 0 ? pay : 0;
  return { minX: minX - p, maxX: maxX + p, minZ: minZ - p, maxZ: maxZ + p };
}

// The camera target (x, z) clamped into hedefSiniri(bounds, pay); without bounds it is returned unchanged.
export function hedefiSinirla(x, z, bounds, pay = KAYDIRMA_PAYI) {
  const s = hedefSiniri(bounds, pay);
  if (!s) return { x, z };
  return { x: Math.min(s.maxX, Math.max(s.minX, x)), z: Math.min(s.maxZ, Math.max(s.minZ, z)) };
}

// The orthographic camera's distance from its target and its near / far planes (2026-11-13, the owner's screenshot: with
// the camera 73 units from its target and near = 0.1, dragging the office down put the floor's front rows — the lobby,
// the bottom wing row — behind the near plane, so they were clipped along a straight line while their labels stayed).
// An orthographic view does not change with the distance, so the camera sits far enough back that every point of the
// floor (any height up to `yukseklik`: the wall board included) is in front of it for every target hedefiSinirla
// allows and every view angle: distance > the target rectangle's 3D diagonal; far covers the opposite side.
export const KAMERA_YUKSEKLIK_PAYI = 16; // world units: the slab's underside up to the top of the wall board
export function kameraDerinligi(bounds, pay = KAYDIRMA_PAYI, yukseklik = KAMERA_YUKSEKLIK_PAYI) {
  const s = hedefSiniri(bounds, pay);
  if (!s) return { uzaklik: 80, near: 1, far: 400 };
  const cap = Math.hypot(s.maxX - s.minX, s.maxZ - s.minZ, Math.max(0, Number(yukseklik) || 0));
  const uzaklik = Math.ceil(cap + 20);
  return { uzaklik, near: 1, far: Math.ceil(uzaklik + cap + 20) };
}

// --- turning the view (the owner, 2026-11-13: a full 360°; buttons ↺ ↻ and the keys Q / E) ---

// One step of the ↺ / ↻ buttons and the Q / E keys: 45 degrees around the current view centre.
export const DONUS_ADIMI = Math.PI / 4;

// An angle (radians) wrapped into (-π, π]; anything unreadable is 0.
export function aciyiSar(a) {
  const x = Number(a);
  if (!Number.isFinite(x)) return 0;
  let r = x % (2 * Math.PI);
  if (r <= -Math.PI) r += 2 * Math.PI;
  else if (r > Math.PI) r -= 2 * Math.PI;
  return r;
}

// The azimuth one step on (OrbitControls' theta: atan2(x, z) of the camera's offset). yon < 0 ("Sola döndür", ↺):
// the floor turns counter-clockwise on the screen (the camera's theta decreases); yon > 0 ("Sağa döndür", ↻):
// clockwise. Not wrapped, so an animation from the old angle to this one always turns the short way, by one step.
export function donusAcisi(aci, yon, adim = DONUS_ADIMI) {
  const a = Number.isFinite(Number(aci)) ? Number(aci) : 0;
  const s = yon > 0 ? 1 : yon < 0 ? -1 : 0;
  return a - s * (Number(adim) > 0 ? Number(adim) : DONUS_ADIMI);
}

// The angle to animate to for a reset to `hedef` from `aci`: hedef itself, moved by whole turns so the way is the
// shortest (at most half a turn).
export function sifirlamaAcisi(aci, hedef) {
  const a = Number.isFinite(Number(aci)) ? Number(aci) : 0;
  return a + aciyiSar((Number(hedef) || 0) - a);
}

// A key press -> -1 (q: Sola döndür), 1 (e: Sağa döndür) or null, with zoomTusu's guard (no Ctrl / Meta / Alt, never
// while typing in a field).
export function donusTusu(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey) return null;
  const t = e.target;
  const tag = t && typeof t.tagName === 'string' ? t.tagName.toUpperCase() : '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return null;
  const key = typeof e.key === 'string' ? e.key.toLowerCase() : '';
  if (key === 'q' || e.code === 'KeyQ') return -1;
  if (key === 'e' || e.code === 'KeyE') return 1;
  return null;
}

// A key press -> the screen direction to pan ([sağ, ileri]: [1, 0] right, [-1, 0] left, [0, 1] up / away, [0, -1]
// down / nearer) for the arrow keys and W A S D, or null. The same guard as zoomTusu (no Ctrl / Meta / Alt, never
// while typing in a field), and never on a tab / menu / option / slider that uses the arrows itself.
const KAYDIRMA_YONU = {
  ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1],
  a: [-1, 0], d: [1, 0], w: [0, 1], s: [0, -1],
  KeyA: [-1, 0], KeyD: [1, 0], KeyW: [0, 1], KeyS: [0, -1],
};
const OK_ROLLERI = ['tab', 'menuitem', 'option', 'slider', 'listbox', 'radio', 'spinbutton', 'tree', 'treeitem', 'grid'];
export function kaydirmaTusu(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey) return null;
  const t = e.target;
  const tag = t && typeof t.tagName === 'string' ? t.tagName.toUpperCase() : '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return null;
  const role = t && typeof t.getAttribute === 'function' ? String(t.getAttribute('role') || '').toLowerCase() : '';
  if (OK_ROLLERI.includes(role)) return null;
  const key = typeof e.key === 'string' && e.key.length === 1 ? e.key.toLowerCase() : e.key;
  const yon = KAYDIRMA_YONU[key] || KAYDIRMA_YONU[e.code];
  return yon ? [...yon] : null;
}

// One keyboard pan step in world units: half of the visible half-width at this zoom (zoomed in -> smaller steps).
export function kaydirmaAdimi(gorunurYariGenislik, zoom) {
  const w = Number(gorunurYariGenislik) > 0 ? Number(gorunurYariGenislik) : 10;
  const z = Number(zoom) > 0 ? Number(zoom) : 1;
  return (w / z) * 0.5;
}


// --- the wheel and the trackpad (scene.js owns every wheel over the scene; OrbitControls' own wheel zoom is off) ---

export const PINCH_K = 0.015; // zoom *= exp(-deltaY * k): macOS Chromium pinch deltas (±1–10 per event) take the fit to ~2x in one pinch
export const PINCH_EN_COK = 60; // one pinch event never moves more than this many deltaY units (no jumps)
export const TEKER_ADIMI = 1.2; // one mouse-wheel notch zooms by this factor

// What a wheel event means over the scene:
// - 'pinch': a trackpad pinch (macOS Chrome / Brave / Edge / Firefox send it as a wheel with ctrlKey and small,
//   fractional deltaY) -> smooth zoom towards the pointer;
// - 'yakinlastir': a mouse wheel notch (deltaMode 1 lines / 2 pages, or a large integer pixel step such as ±100 / ±120
//   with no deltaX; with or without Ctrl) -> one zoom step towards the pointer;
// - 'kaydir': a two-finger trackpad scroll (pixel deltas, fractional or small, or a deltaX) -> pan the floor like a map.
// null for a missing event or one that moves nothing.
export function tekerlekTuru(e) {
  if (!e) return null;
  const dx = Number(e.deltaX) || 0, dy = Number(e.deltaY) || 0;
  if (!dx && !dy) return null;
  const mode = Number(e.deltaMode) || 0;
  const fare = mode !== 0 || (dx === 0 && Number.isInteger(dy) && Math.abs(dy) >= 50);
  if (e.ctrlKey) return fare ? 'yakinlastir' : 'pinch';
  return fare ? 'yakinlastir' : 'kaydir';
}

// The zoom after one pinch event: zoom * exp(-deltaY * k) (deltaY clamped to ±PINCH_EN_COK), within [min, max].
export function pinchZoom(zoom, deltaY, min, max, k = PINCH_K) {
  const z = Number(zoom) > 0 ? Number(zoom) : 1;
  const d = Math.max(-PINCH_EN_COK, Math.min(PINCH_EN_COK, Number(deltaY) || 0));
  const lo = Number(min) > 0 ? Number(min) : 0;
  const hi = Number(max) > 0 ? Number(max) : Infinity;
  return Math.min(hi, Math.max(lo, z * Math.exp(-d * k)));
}

// The zoom after one mouse-wheel notch (deltaY < 0 in, > 0 out), within [min, max].
export function tekerZoom(zoom, deltaY, min, max) {
  const z = Number(zoom) > 0 ? Number(zoom) : 1;
  const dy = Number(deltaY) || 0;
  const next = dy < 0 ? z * TEKER_ADIMI : dy > 0 ? z / TEKER_ADIMI : z;
  const lo = Number(min) > 0 ? Number(min) : 0;
  const hi = Number(max) > 0 ? Number(max) : Infinity;
  return Math.min(hi, Math.max(lo, next));
}

// Zoom to the cursor on the orthographic camera: the floor point under a fixed screen pixel lies at target + A / zoom
// (A fixed for that pixel), so keeping the point P (under the cursor at zoom z0) fixed at zoom z1 moves the target T to
// T + (P - T) * (1 - z0 / z1). Returns the new target {x, z}; the camera moves by the same amount.
export function imlecZoomHedefi(tx, tz, px, pz, z0, z1) {
  if (!(z0 > 0) || !(z1 > 0) || ![tx, tz, px, pz].every(Number.isFinite)) return { x: tx, z: tz };
  const f = 1 - z0 / z1;
  return { x: tx + (px - tx) * f, z: tz + (pz - tz) * f };
}

// A two-finger scroll -> the floor pan in screen directions ([sağ, ileri], world units): the view follows the scroll as
// a page would (deltaY > 0 moves the view down / nearer, deltaX > 0 to the right); `birim` = world units per pixel.
export function tekerKaydirma(deltaX, deltaY, birim) {
  const u = Number(birim) > 0 ? Number(birim) : 0;
  return [(Number(deltaX) || 0) * u, -(Number(deltaY) || 0) * u];
}

// --- the character info card: clicking any character opens a small card (web/app.js draws it with textContent) ---

// What each tier's work is, in plain words; a role's work is the tiers that map to its model.
export const KATMAN_GOREVI = {
  kolay: 'kolay işler: test çalıştırma, durum kontrolü, biçimlendirme',
  genel: 'okuma, özetleme, araştırma',
  kod: 'kod yazma ve hata düzeltme',
  inceleme: 'inceleme',
  planlama: 'büyük işleri planlama, mimari',
};
// A role's work from the effective mapping (/api/state.katmanlar: global tiers, project overrides and running pilots;
// without it the defaults): the global tiers of its model, then "<proje>: <tier>" where a project maps a tier to it.
export function kadroGorevi(fam, katmanlar = null) {
  const k = katmanlar && typeof katmanlar === 'object' ? katmanlar : {};
  const tiers = Object.keys(KATMAN_GOREVI);
  const genel = tiers.filter((t) => modelAilesi(katmanModeli({ genel: k.genel }, '', t)) === fam);
  const parts = genel.map((t) => KATMAN_GOREVI[t]);
  const ozel = [];
  for (const [p, m] of Object.entries(k.projeler || {})) {
    for (const t of tiers) {
      if (m && modelAilesi(m[t]) === fam && !genel.includes(t)) ozel.push(`${p}: ${t}`);
    }
  }
  if (ozel.length) parts.push(`ayrıca ${ozel.join(', ')}`);
  return parts.join(', ');
}
// The default work of each role (the global defaults; kept for callers without a state).
export const KADRO_GOREVI = Object.fromEntries(['haiku', 'sonnet', 'opus', 'fable'].map((f) => [f, kadroGorevi(f)]));
const SONUC_ADI = { bitti: 'bitti', tikandi: 'takıldı', iptal: 'iptal edildi', basarisiz: 'başlatılamadı' };
const BITMIS = new Set(Object.keys(SONUC_ADI));
const SUS_ROL = {
  cayci: ['Çaycı', 'Ofisin çaycısı: çay demler, işini bitirenlere çay götürür.'],
  guvenlik: ['Güvenlik görevlisi', 'Girişte nöbet tutar, asansörden gelenleri karşılar. Üç kişi 8 saatlik vardiyayla sırayla nöbet tutar; kimin ofiste, kimin otelde olduğunu bilir.'],
  sekreter: ['Sekreter', "Resepsiyonda oturur; {sahip_i} bekleyen soruları CEO'nun kapısına taşır — gece de. Üç kişi 8 saatlik vardiyayla sırayla nöbet tutar."],
  muhasebe: ['Muhasebeci', 'Muhasebede oturur; kullanımı gün ve ay olarak tutar (dolar tutarları API karşılığıdır).'],
  idari: ['İdari işler sorumlusu', 'Ofisin işleyişine bakar: sunucu, sınırlar, zamanlanmış işler.'],
  ik: [TESIS_PERSONELI.ik, "Kadroyu ve denetçileri izler: kim ne durumda, bu ay nasıl çalıştı. Genel Müdür'e bağlıdır; sekreterler, güvenlik, muhasebe, idari işler, ofis hizmetleri ve sosyal medya ekibi ona bağlıdır."],
  psikolog: ['Ofis psikoloğu', 'Ekibin iş yüküne bakar: uzun süren, iki kez kalan, kullanım sınırına yaklaşan işler.'],
  masaj: ['Masajcı', 'Uzun çalışanları masaj masasında dinlendirir.'],
  revir: ['Ofis doktoru', 'Revirde oturur; ofisin sağlığına bakar: takılan işler, sessiz oturumlar, hatalar.'],
  sunucu: ['IT sorumlusu', 'IT ekibinden: sunucu odasına ve sisteme bakar — bilgisayarın yükü, süreç grupları, projelerin siteleri. Üç kişi 8 saatlik vardiyayla sırayla nöbet tutar. Yalnız öneri yazar, hiçbir şeyi kapatmaz.'],
  yemekhane: ['Yemekhane görevlisi', 'Yemekhanede kahvaltıda, öğlen ve akşam servis yapar; yemekten sonra tepsileri toplar ve bulaşıkhanede yıkar. Üç kişi 8 saatlik vardiyayla sırayla nöbet tutar — hafta sonu da.'],
  asci: ['Aşçı', 'Mutfakta (bulaşıkhanenin yanındaki ocak ve dolap) kahvaltıyı, öğle ve akşam yemeğini hazırlar; arada mutfağı temizler. Üç kişi 8 saatlik vardiyayla sırayla nöbet tutar — hafta sonu da.'],
  arge: ['Ar-Ge uzmanı', 'Ar-Ge odasında araştırır: yeni modeller ve ücretsiz katmanlar, Claude Code / Codex / OpenCode yenilikleri, projeler için öneriler. Araştırma işi açıkken masasında çalışır. Yalnız okur ve öneri getirir; hiçbir şeyi değiştirmez.'],
  degerlendirme: ['Değerlendirme ekibi', "Analist Müdürü'ne bağlı iki kişi. Her akşam bir kez günü ölçer: kim ne yaptı, Kontrol ilk denemede geçti mi, yeniden iş, durdurmalar, hatalar, kullanım. Kötü giden bir şey varsa bir değerlendirme işi açılır; kök nedenler ve öneriler gün sonu notuna eklenir. Yalnız ölçer ve öneri getirir; hiçbir şeyi değiştirmez."],
};
const SUS_KONU = { sekreter: 'kararlar ve takvim', guvenlik: 'giriş-çıkış ve güvenlik', cayci: 'molalar',
  yemekhane: 'yemekhane', asci: 'mutfak' };
// One card row {ad, metin}; `ek` adds the optional layout hints read by kartDuzeni (bolum, tablo, cubuk) — the text
// itself always stays in ad / metin.
const satir = (ad, metin, ek) => (ek ? { ad, metin: String(metin), ...ek } : { ad, metin: String(metin) });
const aileAdiOf = (m) => MODEL_ADI[modelAilesi(m)] || 'model bilinmiyor';

// "bugün 09:00", "10 Kas 14:05" in the office zone; "" when unknown.
function anMetni(t, ms, tz) {
  if (t === null || !Number.isFinite(t)) return '';
  try {
    const f = (x, o) => new Intl.DateTimeFormat('tr-TR', { timeZone: tz, ...o }).format(new Date(x));
    const gun = (x) => f(x, { year: 'numeric', month: '2-digit', day: '2-digit' });
    const saat = f(t, { hour: '2-digit', minute: '2-digit', hour12: false });
    if (ms !== null && gun(t) === gun(ms)) return `bugün ${saat}`;
    return `${f(t, { day: 'numeric', month: 'short' })} ${saat}`;
  } catch (e) { return ''; }
}

// --- the three staff cards (Sekreter, Güvenlik görevlisi, Çaycı): only what /api/state says; a missing value leaves its
// line out ---

// How long ago: "<1 dk", "12 dk", "2 sa", "3 gün"; '' when unknown or in the future.
export function bekleyisMetni(t, ms) {
  if (t === null || ms === null || !Number.isFinite(t) || !Number.isFinite(ms) || t > ms + 60000) return '';
  const dk = Math.floor(Math.max(0, ms - t) / 60000);
  if (dk < 1) return '<1 dk';
  if (dk < 60) return `${dk} dk`;
  const sa = Math.floor(dk / 60);
  return sa < 24 ? `${sa} sa` : `${Math.floor(sa / 24)} gün`;
}
export const RISK_METNI = { yuksek: 'yüksek risk', normal: 'normal risk', dusuk: 'düşük risk' };
// a model card still pending this long gets a reminder (bin/model_secimi.py: 3 days, then every 7)
export const HATIRLATMA_GUN = 3;
const MODEL_KARTLARI = new Set(['model-onerisi', 'model-pilot-sonucu', 'danisman-onerisi', 'danisman-pilot-sonucu']);
// a break the engine chose (molaPlani / personelRotasi / personelMolasi set `mola`), or lunch

// Shared context of the staff cards.
function personelBaglami(st, ms) {
  const sahne = { ...DEFAULT_SAHNE, ...(st.sahne || {}) };
  const tz = sahne.saat_dilimi;
  const ofset = Number.isFinite(sahne.sunucu_utc_ofset_dk) ? sahne.sunucu_utc_ofset_dk : null;
  const tasks = new Map();
  for (const t of [...(Array.isArray(st.tasks) ? st.tasks : []), ...(Array.isArray(st.board) ? st.board : [])]) {
    if (t && t.note && !tasks.has(notKoku(t.note))) tasks.set(notKoku(t.note), t);
  }
  const bugun = (t) => t !== null && ms !== null && anMetni(t, ms, tz).startsWith('bugün');
  const zaman = (v) => zamanMs(v, tz, ofset);
  const kararlar = (Array.isArray(st.decisions) ? st.decisions : []).filter((d) => d && d.note && !d.answer_sent);
  return { sahne, tz, ofset, tasks: [...tasks.values()], bugun, zaman, kararlar };
}
const isBasligi = (t) => kisa(t.title || notKoku(t.note), 60);
const saatOf = (t, tz) => {
  try {
    return new Intl.DateTimeFormat('tr-TR', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t));
  } catch (e) { return ''; }
};
// A decision as a card action: "<title> · 2 sa · yüksek risk" (the parts that are known).
function kararEylemi(d, b, ms) {
  const parts = [kisa(d.title || notKoku(d.note), 60), bekleyisMetni(b.zaman(d.asked), ms),
    d.guvenlik_acik ? 'açık güvenlik bulgusu' : '', RISK_METNI[d.risk] || ''].filter(Boolean);
  return { tur: 'karar', metin: parts.join(' · '), note: String(d.note) };
}

// Sekreter ("kararlar ve takvim"): the decisions waiting for the owner (each opens its card, oldest first), today's
// numbers, the next scheduled job, and the model cards that are due a reminder.
export function sekreterKarti(st, ms) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const eylemler = [];
  const acik = [...b.kararlar].sort((x, y) => (b.zaman(x.asked) ?? Infinity) - (b.zaman(y.asked) ?? Infinity) ||
    (String(x.note) < String(y.note) ? -1 : 1));
  if (acik.length) {
    satirlar.push(satir('Bekleyen', `${sahip('e')} ${acik.length} soru bekliyor`));
    acik.slice(0, 6).forEach((d) => eylemler.push(kararEylemi(d, b, ms)));
    if (acik.length > 6) eylemler.push({ tur: 'kararlar', metin: `Tüm kararları aç (${acik.length})` });
  } else if (Array.isArray(st.decisions)) satirlar.push(satir('Bekleyen', `${sahip('i')} bekleyen soru yok`));
  const sum = st.summary && typeof st.summary === 'object' ? st.summary : {};
  const sayi = (v) => (Number.isFinite(v) && v >= 0 ? Math.floor(v) : null);
  const basladi = sayi(sum.tasks_today), bitti = sayi(sum.finished_today);
  const bugun = [basladi !== null ? `${basladi} iş başladı` : '', bitti !== null ? `${bitti} iş bitti` : ''].filter(Boolean);
  if (bugun.length) satirlar.push(satir('Bugün', bugun.join(' · ')));
  const zl = (Array.isArray(st.schedules) ? st.schedules : []).filter((z) => z && !z.duraklatildi && b.zaman(z.sonraki) !== null)
    .sort((x, y) => b.zaman(x.sonraki) - b.zaman(y.sonraki) || (String(x.ad) < String(y.ad) ? -1 : 1));
  if (zl.length) {
    const z = zl[0];
    satirlar.push(satir('Sıradaki zamanlanmış iş', [kisa(z.baslik || z.ad, 60), z.proje, anMetni(b.zaman(z.sonraki), ms, b.tz)]
      .filter(Boolean).join(' · ')));
  }
  const durdu = (Array.isArray(st.schedules) ? st.schedules : []).filter((z) => z && z.duraklatildi).length;
  if (durdu) satirlar.push(satir('Duraklatılmış', `${durdu} zamanlanmış iş`));
  for (const d of acik) {
    const t = b.zaman(d.asked);
    if (!MODEL_KARTLARI.has(d.kind) || t === null || ms === null) continue;
    const gun = Math.floor((ms - t) / 86400000);
    if (gun >= HATIRLATMA_GUN) satirlar.push(satir('Hatırlatma', `${kisa(d.title || notKoku(d.note), 60)} · ${gun} gündür cevap bekliyor`));
  }
  satirlar.push(...nobetSatirlari('sekreter', st, ms)); // the team's shift (from the clock): who is on shift, the next change
  return { satirlar, eylemler };
}

// Güvenlik görevlisi ("giriş-çıkış ve güvenlik"): today's arrivals (jobs started) and departures (jobs finished), the
// last five; everyone in the office now (kimNerede + fazlaIsciSayisi; how many work from the drawn actors); open security findings and yüksek-risk cards (each
// opens its card); the message-delivery warnings (postofficeWarnings).
export function guvenlikKarti(st, ms, aktorler) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const eylemler = [];
  const olaylar = [];
  for (const t of b.tasks) {
    const s = b.zaman(t.started), f = b.zaman(t.finished);
    if (b.bugun(s)) olaylar.push({ t: s, ad: `Giriş ${saatOf(s, b.tz)}`, t2: t });
    if (b.bugun(f) && BITMIS.has(t.status)) olaylar.push({ t: f, ad: `Çıkış ${saatOf(f, b.tz)}`, t2: t });
  }
  olaylar.sort((x, y) => y.t - x.t || (x.ad < y.ad ? -1 : 1));
  olaylar.slice(0, 5).forEach((o) => satirlar.push(satir(o.ad, [o.t2.project, isBasligi(o.t2)].filter(Boolean).join(' · '))));
  // the headcount (the owner, 2026-11-16: "full 36 kişiyi saysın"): everyone in the office — kimNerede's roster (the agents,
  // the shift teams, the staff) plus the workers beyond one body per kadro —, the same number as "Ofiste olanlar"
  const k = ms !== null && Number.isFinite(ms) ? kimNerede(st, ms, Array.isArray(aktorler) ? aktorler : null) : null;
  const fazla = fazlaIsciSayisi(aktorler);
  if (k && Array.isArray(aktorler)) {
    let calisan = 0, yardimci = 0;
    for (const a of aktorler) {
      if (!a || a.tur === 'sus' || a.tur === 'ozet' || a.poz === 'evde' || a.cikis) continue;
      if (a.tur === 'alt-ajan') { yardimci++; continue; }
      if (a.poz === 'yaziyor' || a.poz === 'toplanti' || a.simge === 'test') calisan++;
    }
    const toplam = k.ofiste.length + fazla;
    const nobette = k.ofiste.filter((e) => e.durum === 'nobette').length;
    const parts = [`${calisan} çalışıyor`, `${nobette} nöbette`, `${Math.max(0, toplam - calisan - nobette)} diğer`];
    if (yardimci) parts.push(`${yardimci} yardımcı ayrıca`);
    satirlar.push(satir('Ofiste şimdi', `${toplam} kişi: ${parts.join(', ')}`));
  }
  if (Array.isArray(st.decisions)) {
    const riskli = b.kararlar.filter((d) => d.guvenlik_acik || d.risk === 'yuksek');
    const bulgu = riskli.filter((d) => d.guvenlik_acik).length;
    if (!riskli.length) satirlar.push(satir('Güvenlik', 'açık güvenlik bulgusu yok, yüksek riskli kart yok'));
    else {
      satirlar.push(satir('Güvenlik', [bulgu ? `${bulgu} açık güvenlik bulgusu` : '',
        riskli.length - bulgu ? `${riskli.length - bulgu} yüksek riskli kart` : ''].filter(Boolean).join(' · ')));
      riskli.slice(0, 4).forEach((d) => eylemler.push(kararEylemi(d, b, ms)));
    }
  }
  if (st.postoffice && typeof st.postoffice === 'object') {
    const lines = postofficeWarnings(st.postoffice);
    if (!lines.length) satirlar.push(satir('İletişim uyarıları', 'yok'));
    else lines.slice(0, 3).forEach((l, i) => satirlar.push(satir(i ? '' : 'İletişim uyarıları', l)));
    if (lines.length > 3) satirlar.push(satir('', `${lines.length - 3} uyarı daha`));
  }
  // who is where (kimNerede: the clock, the office hours, the leave times and the shifts; the agents' state from the
  // drawn actors): everyone in the office, then everyone at home with when they left and when they come back
  satirlar.push(...nobetSatirlari('guvenlik', st, ms, { ekipSatiri: false })); // the team's shift (from the clock)
  if (k) satirlar.push(...kimNeredeSatirlari(k, ms, b.tz, { fazla }));
  return { satirlar, eylemler };
}

// Minutes until lunch in the office zone: 'şu an öğle arası', 'öğle arası 45 dk sonra', '… bugün bitti'; '' unknown.
export function ogleMetni(ms, sahne) {
  if (ms === null || !Number.isFinite(ms)) return '';
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const dk = (x) => { const m = String(x || '').match(/^([01]\d|2[0-3]):([0-5]\d)$/); return m ? Number(m[1]) * 60 + Number(m[2]) : null; };
  let [a, e] = String(s.ogle || '').split('-').map(dk);
  if (a === null || e === null || a === undefined || e === undefined) [a, e] = DEFAULT_SAHNE.ogle.split('-').map(dk);
  try {
    if (ogleMi(ms, s)) return 'şu an öğle arası';
    const o = ofisSaati(ms, s.saat_dilimi);
    const cur = o.saat * 60 + o.dakika;
    if (cur < a) {
      const fark = a - cur;
      return `öğle arası ${fark < 60 ? `${fark} dk` : `${Math.floor(fark / 60)} sa${fark % 60 ? ` ${fark % 60} dk` : ''}`} sonra`;
    }
    return 'bugünkü öğle arası bitti';
  } catch (err) { return ''; }
}

// The kitchen teams' card ("yemekhane" / "asci", 2026-11-14): the team's shift rows (nobetSatirlari: who is on duty, until
// when, the next change and the team), then only what the page knows — how many eat in the canteen now (the drawn
// actors), the meal windows of today (ogunPencereleri) and the next meal.
const OGUN_ADI = { kahvalti: 'Kahvaltı', ogle: 'Öğle yemeği', aksam: 'Akşam yemeği' };
export function yemekhaneKarti(st, ms, aktorler, ekip = 'yemekhane') {
  const b = personelBaglami(st, ms);
  const satirlar = [...nobetSatirlari(ekip, st, ms)];
  if (Array.isArray(aktorler)) {
    const n = aktorler.filter((a) => a && a.poz === 'yemek' && /^yemekhane-/.test(String(a.yer || ''))).length;
    satirlar.push(satir('Yemekhanede', n ? `şu an ${n} kişi yemekte` : 'şu an kimse yemekte değil'));
  }
  try {
    for (const p of ogunPencereleri(ms, b.sahne)) satirlar.push(satir(OGUN_ADI[p.tur], `${saatDk(p.bas)}–${saatDk(p.son)}`, { bolum: 'Öğünler' }));
  } catch (err) { /* no clock: no meal rows */ }
  const ogle = ogleMetni(ms, b.sahne);
  if (ogle) satirlar.push(satir('', ogle));
  return { satirlar, eylemler: [] };
}

// Çaycı ("molalar"): who is on a break now and what they do (the drawn actors), the agent working longest, the time to
// lunch, today's three costliest jobs.
export function cayciKarti(st, ms, aktorler) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  if (Array.isArray(aktorler)) {
    const molada = aktorler.filter((a) => a && a.tur !== 'sus' && a.tur !== 'ozet' && a.poz !== 'evde' && !a.cikis &&
      (a.mola === true || a.poz === 'yemek'));
    if (!molada.length) satirlar.push(satir('Molada', 'şu an kimse molada değil'));
    molada.slice(0, 6).forEach((a, i) => satirlar.push(satir(i ? '' : 'Molada',
      `${rolAdi(a.etiket || a.unvan || 'ajan')} · ${a.durum_metni || 'molada'}`)));
    if (molada.length > 6) satirlar.push(satir('', `${molada.length - 6} kişi daha`));
  }
  const uzun = ms !== null ? enUzunCalisan(b.tasks, b.tz, b.ofset, ms, EN_UZUN_MIN_MS) : null;
  if (uzun && ms !== null) {
    const fam = modelAilesi(isModeli(uzun, null, st.katmanlar));
    const kim = calisanAdi(rolMetni(fam, uzun.uzmanlik), fam);
    satirlar.push(satir('En uzun çalışan', `${kim} · ${sureMetni(b.zaman(uzun.started), ms)} masasında · ${[uzun.project, isBasligi(uzun)].filter(Boolean).join(' · ')}`));
  }
  const ogle = ogleMetni(ms, b.sahne);
  if (ogle) satirlar.push(satir('Öğle arası', ogle));
  const harcayan = b.tasks.filter((t) => (b.bugun(b.zaman(t.started)) || b.bugun(b.zaman(t.finished))) && Number(t.spent) > 0)
    .sort((x, y) => Number(y.spent) - Number(x.spent) || (String(x.note) < String(y.note) ? -1 : 1)).slice(0, 3);
  harcayan.forEach((t, i) => {
    const tok = tokenMetni(t.tokens);
    satirlar.push(satir(i ? '' : 'Bugün en çok kullanan', `${isBasligi(t)} · ${tok ? `${tok} · ` : ''}${usdText(t.spent)}`));
  });
  return { satirlar, eylemler: [] };
}

// --- the wing's office staff (Muhasebeci, İdari işler, İK) and the project residents: their cards read /api/state and
// the data the page fetches when the card opens (secenek.veri: {muhasebe: GET /api/muhasebe, idari: GET /api/idari,
// kalite: GET /api/kalite}); a value not fetched yet or missing leaves its line out ---

const usdTok = (usd, tok) => {
  const t = tokenMetni(tok);
  return t ? `${t} · ${usdText(usd || 0)}` : usdText(usd || 0); // tokens first; unknown tokens: the dollars only (CLAUDE.md)
};
// A usage figure with its tokens first when known ("182 bin token · ≈$0,80"); the dollars alone otherwise (never "0 token").
const paraTok = (usd, tok) => {
  const t = tokenMetni(tok);
  return `${t ? `${t} · ` : ''}${usdText(usd || 0)}`;
};
// One part of a split list ("ornek-uygulama (400 bin token · ≈$1,20)"): parentheses keep the " · " separators unambiguous.
const parcaTok = (ad, usd, tok) => {
  const t = tokenMetni(tok);
  return t ? `${ad} (${t} · ${usdText(usd || 0)})` : `${ad} ${usdText(usd || 0)}`;
};
const oran = (a, b) => (Number(b) > 0 ? `%${Math.round((100 * a) / b)} (${a}/${b})` : '');
// The bytes of a file in plain words: "820 KB", "1,2 MB".
export function boyutMetni(n) {
  if (!Number.isFinite(n) || n < 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1048576).toFixed(1).replace('.', ',')} MB`;
}
const KARTLAR = { muhasebe: 'kullanım', idari: 'ofis işleyişi', ik: 'çalışanlar', proje: 'proje bilgisi', revir: 'ofis sağlığı',
  psikolog: 'iş yükü', masaj: 'masaj odası', sunucu: 'IT ekibi', arge: 'araştırma', degerlendirme: 'gün sonu' };

// "13 Kasım" of a day "YYYY-MM-DD" (the end-of-day review's dates); '' when it is not one.
const AY_ADI = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const gunAdi = (g) => { const m = String(g || '').match(/^\d{4}-(\d{2})-(\d{2})$/); return m ? `${Number(m[2])} ${AY_ADI[Number(m[1]) - 1] || ''}`.trim() : ''; };
// Değerlendirme ekibi ("gün sonu"; bin/gunsonu.py, state.gun_sonu): what it does now, the last run (its day, its numbers,
// the note's name, the review job and its suggestions), the skipped days and the evening hours. "Değerlendirme işini aç" opens
// the review job.
export function degerlendirmeKarti(st, ms, a = {}) {
  const satirlar = [];
  const eylemler = [];
  const g = st && st.gun_sonu && typeof st.gun_sonu === 'object' ? st.gun_sonu : null;
  if (a.durum_metni) satirlar.push(satir('Şu an', a.durum_metni));
  if (!g) { satirlar.push(satir('Gün sonu', 'bilgi yok')); return { satirlar, eylemler }; }
  satirlar.push(satir('Pencere', g.acik ? `her akşam ${g.pencere || '20:00–24:00'} (bir kez)` : 'kapalı (ofis.json gun_sonu)'));
  const son = g.son && typeof g.son === 'object' ? g.son : null;
  if (!son) satirlar.push(satir('Son değerlendirme', 'henüz yok'));
  else {
    satirlar.push(satir('Son değerlendirme', [gunAdi(son.gun) || son.gun, son.olcum_saati].filter(Boolean).join(' · ')));
    const x = son.sayilar && typeof son.sayilar === 'object' ? son.sayilar : {};
    const n = (v) => Math.max(0, Math.floor(Number(v) || 0));
    satirlar.push(satir('İşler', `${n(x.bitti)} bitti · ${n(x.tikandi)} takıldı${n(x.basarisiz) ? ` · ${n(x.basarisiz)} başlatılamadı` : ''}`
      + (n(x.kontrol) ? ` · Kontrol ilk denemede ${n(x.kontrol_ilk)}/${n(x.kontrol)}` : '')));
    if (Number(x.usd) > 0) {
      const tok = tokenMetni(x.token);
      satirlar.push(satir('Kullanım', `${tok ? `${tok} · ` : ''}${usdText(x.usd)}`));
    }
    satirlar.push(satir('Kötü giden', n(son.kotu) ? `${n(son.kotu)} durum` : 'yok'));
    if (son.not) satirlar.push(satir('Not', `${kisa(son.not, 40)} (Obsidian)`));
    if (son.is) {
      const t = (Array.isArray(st.tasks) ? st.tasks : []).find((x2) => x2 && notKoku(x2.note) === notKoku(son.is)) || null;
      const durum = son.rapor === 'bitti' ? `önerileri eklendi (${n(son.oneri)})` : son.rapor ? `tamamlanamadı (${son.rapor})`
        : t ? (t.status === 'sirada' ? 'sırada' : 'çalışıyor') : 'bekleniyor';
      satirlar.push(satir('Değerlendirme işi', durum));
      eylemler.push({ tur: 'is', note: String(son.is), metin: 'Değerlendirme işini aç' });
    } else if (n(son.kotu)) satirlar.push(satir('Değerlendirme işi', 'eklenemedi ya da ekleniyor'));
  }
  const atl = (Array.isArray(g.atlananlar) ? g.atlananlar : []).map(gunAdi).filter(Boolean);
  if (atl.length) satirlar.push(satir('Atlanan günler', atl.join(', ')));
  return { satirlar, eylemler };
}

// Ar-Ge uzmanı ("araştırma"; plan "Sonraki iş (6)"): the open research job (a.arge_is, from the engine), then GET /api/arge
// (bin/arge.py sayfa): the last report's summary lines, its reviewer suggestions (each with its decision card), the free
// daily check's diff (new / removed / renamed free models, version changes). "Raporu aç" opens the report's job.
export function argeKarti(st, ms, d, a = {}) {
  const satirlar = [];
  const eylemler = [];
  const isOf = (note) => (Array.isArray(st.tasks) ? st.tasks : []).find((t) => t && notKoku(t.note) === notKoku(note)) || null;
  if (a.arge_is) {
    const t = isOf(a.arge_is);
    satirlar.push(satir('Şu an', `araştırıyor · ${kisa((t && t.title) || notKoku(a.arge_is), 60)}`));
  }
  if (!d || typeof d !== 'object') {
    satirlar.push(satir('Ar-Ge', 'okunuyor…'));
  } else {
    const r = d.son_rapor && typeof d.son_rapor === 'object' ? d.son_rapor : null;
    if (!r) satirlar.push(satir('Son rapor', 'henüz rapor yok'));
    else {
      satirlar.push(satir('Son rapor', [r.gun, kisa(r.baslik || notKoku(r.is), 60)].filter(Boolean).join(' · ')));
      if (r.not) satirlar.push(satir('Not', `${kisa(r.not, 40)} (Obsidian)`));
      (Array.isArray(r.ozet) ? r.ozet : []).slice(0, 6).forEach((x, i) => satirlar.push(satir(i ? '' : 'Özet', kisa(x, 160))));
      const on = (Array.isArray(r.oneriler) ? r.oneriler : []).filter((o) => o && o.model);
      on.forEach((o, i) => satirlar.push(satir(i ? '' : 'Denetçi önerileri', `${kisa(o.model, 80)}${o.lisans ? ` · ${kisa(o.lisans, 40)}` : ''}${
        o.kart ? ' · karar kartı yazıldı' : o.lisans ? '' : ' · lisansı yazılmadı, kart açılmadı'}`)));
      if (r.is) eylemler.push({ tur: 'is', note: String(r.is), metin: 'Raporu aç' });
      for (const o of on) if (o.kart) eylemler.push({ tur: 'karar', note: String(o.kart), metin: `Kartı aç: ${kisa(o.model, 40)}` });
    }
    const f = d.fark && typeof d.fark === 'object' ? d.fark : null;
    const m = f && f.modeller && typeof f.modeller === 'object' ? f.modeller : null;
    if (!m) satirlar.push(satir('Model listesi', 'günlük kontrol henüz yapılmadı'));
    else if (m.durum === 'bilinmiyor') satirlar.push(satir('Model listesi', `${f.gun || ''} · bilinmiyor (opencode okunamadı)`));
    else if (m.durum === 'ilk') satirlar.push(satir('Model listesi', `${f.gun || ''} · ilk liste: ${m.sayi || 0} ücretsiz model`));
    else {
      const parca = [];
      if (Array.isArray(m.yeni) && m.yeni.length) parca.push(`Yeni: ${m.yeni.join(', ')}`);
      if (Array.isArray(m.kalkan) && m.kalkan.length) parca.push(`Kalkan: ${m.kalkan.join(', ')}`);
      if (Array.isArray(m.ad_degisen) && m.ad_degisen.length) parca.push(`Adı değişen: ${m.ad_degisen.map((x) => `${x[0]} → ${x[1]}`).join(', ')}`);
      satirlar.push(satir('Model listesi', `${f.gun || ''} (${f.onceki_gun || '—'} ile) · ${m.sayi || 0} ücretsiz model`));
      if (!parca.length) satirlar.push(satir('', 'ücretsiz model listesinde değişiklik yok'));
      for (const x of parca) satirlar.push(satir('', kisa(x, 300)));
    }
    const sv = f && Array.isArray(f.surumler) ? f.surumler.filter(Boolean) : [];
    sv.forEach((x, i) => satirlar.push(satir(i ? '' : 'Sürüm değişti', `${x.arac}: ${x.onceki} → ${x.simdi}`)));
    const su = d.surumler && typeof d.surumler === 'object' ? d.surumler : null;
    if (su) satirlar.push(satir('Sürümler', ['claude', 'codex', 'opencode'].filter((k) => su[k]).map((k) => `${k} ${su[k]}`).join(' · ')));
  }
  if (a.arge_is) eylemler.push({ tur: 'is', note: String(a.arge_is), metin: 'Çalışan işi aç' });
  return { satirlar, eylemler };
}

// Muhasebeci ("harcamalar"): today and this month (from the Karne rows + the open jobs' recorded spending), the
// verified cost per job, the three costliest jobs (each opens its job), the budget of the running jobs.
export function muhasebeKarti(st, ms, m) {
  const satirlar = [];
  const eylemler = [];
  if (!m || typeof m !== 'object') {
    satirlar.push(satir('Kullanım', 'okunuyor…'));
    eylemler.push({ tur: 'kalite', metin: 'Kalite sekmesini aç' });
    return { satirlar, eylemler };
  }
  const HR = { bolum: 'Kullanım' };
  const BT = { bolum: 'Kullanım sınırı' };
  const donem = (ad, x) => {
    if (!x || typeof x !== 'object') return;
    satirlar.push(satir(ad, `${usdTok(x.usd, x.token)} · ${x.is_sayisi || 0} iş`, HR));
    // the split as small tables (kartDuzeni): one row per project / role, the spending with its tokens
    const tablo = (anahtar, baslik, ilk, list, adOf) => ({ ...HR, tablo: { anahtar, baslik, basliklar: [ilk, 'Kullanım', 'İş'],
      satirlar: list.map((p) => [adOf(p), paraTok(p.usd, p.token), String(p.is_sayisi)]) } });
    const prl = (x.proje || []).filter((p) => p && p.is_sayisi);
    const pr = prl.map((p) => parcaTok(p.proje, p.usd, p.token));
    if (pr.length) satirlar.push(satir('', `projeye göre: ${pr.join(' · ')}`, tablo(`${ad}-proje`, `${ad} · projeye göre`, 'Proje', prl, (p) => p.proje)));
    const rll = (x.rol || []).filter((r) => r && r.is_sayisi);
    const rl = rll.map((r) => parcaTok(r.rol, r.usd, r.token));
    if (rl.length) satirlar.push(satir('', `unvana göre: ${rl.join(' · ')}`, tablo(`${ad}-rol`, `${ad} · unvana göre`, 'Unvan', rll, (r) => r.rol)));
    if (x.codex_fiyatsiz > 0) satirlar.push(satir('', `Codex incelemeleri (${x.codex_fiyatsiz}) fiyatsız: toplamda yok`, HR));
  };
  donem('Bugün', m.bugun);
  donem('Bu ay', m.bu_ay);
  const k = m.kalite || {};
  const KL = { bolum: 'Kalite' };
  if (Number.isFinite(k.dogrulanmis_is_basina_usd)) satirlar.push(satir('Doğrulanmış iş başına', `${paraTok(k.dogrulanmis_is_basina_usd, k.dogrulanmis_is_basina_token)} (bu ay)`, KL));
  const ilk = oran(k.ilk_tur_gecen, k.ilk_tur_olculen);
  if (ilk) satirlar.push(satir('İlk turda geçen', `${ilk} (bu ay)`, { ...KL,
    ...(Number(k.ilk_tur_olculen) > 0 ? cubukOf((100 * k.ilk_tur_gecen) / k.ilk_tur_olculen, true) : {}) }));
  for (const e of (Array.isArray(m.en_pahali) ? m.en_pahali : []).slice(0, 3)) {
    if (e && e.not) eylemler.push({ tur: 'is', note: String(e.not), metin: `${kisa(e.baslik || notKoku(e.not), 50)} · ${usdTok(e.usd, e.token)}` });
  }
  const b = m.butce || {};
  if (b.calisan > 0) {
    // the usage with its tokens; the cap (butce_usd) is a usage limit, dollars only (API equivalent)
    satirlar.push(satir('Kullanım sınırı', `${b.calisan} açık iş: ${paraTok(b.harcanan_usd, b.harcanan_token)}${Number.isFinite(b.butce_usd) ? ` / ${usdText(b.butce_usd)}` : ''}`,
      { ...BT, ...(b.butce_usd > 0 ? cubukOf((100 * (Number(b.harcanan_usd) || 0)) / b.butce_usd) : {}) }));
  }
  for (const x of Array.isArray(b.dikkat) ? b.dikkat : []) {
    if (!x || !x.not) continue;
    const durum = x.durum === 'asti' ? 'aştı' : 'sınıra yakın';
    satirlar.push(satir('Kullanım sınırı uyarısı', `${kisa(x.baslik || notKoku(x.not), 50)} · ${paraTok(x.usd, x.token)} / ${usdText(x.butce || 0)} · ${durum}`,
      { ...BT, tablo: { anahtar: 'butce-uyari', baslik: 'Kullanım sınırı uyarıları', basliklar: ['İş', 'Kullanılan', 'Sınır', 'Durum'],
        satirlar: [[kisa(x.baslik || notKoku(x.not), 50), paraTok(x.usd, x.token), usdText(x.butce || 0), durum]] } }));
  }
  eylemler.push({ tur: 'kalite', metin: 'Kalite sekmesini aç' });
  return { satirlar, eylemler };
}

// İdari işler sorumlusu ("ofis işleyişi"): the server start, autostart, the Obsidian access, the log size, the limits
// and the scheduled jobs. Base names only.
export function idariKarti(st, ms, d) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const sv = (st.sunucu && typeof st.sunucu === 'object') ? st.sunucu : (d && d.sunucu) || null;
  const bas = sv ? b.zaman(sv.baslangic) : null;
  if (bas !== null) satirlar.push(satir('Sunucu', `${anMetni(bas, ms, b.tz)} başladı · ${sureMetni(bas, ms)} çalışıyor`));
  if (d && typeof d === 'object') {
    if (d.otomatik_baslatma) satirlar.push(satir('Otomatik başlatma', d.otomatik_baslatma.kurulu ? 'kurulu: oturum açılınca kendiliğinden başlar' : 'kurulu değil: elle başlatılıyor'));
    if (d.obsidian) {
      satirlar.push(satir('Obsidian erişimi', !d.obsidian.sorun ? 'sorun yok'
        : `notlar okunamıyor — Sistem Ayarları > Gizlilik ve Güvenlik > Tam Disk Erişimi'ne ${typeof d.obsidian.python === 'string' && d.obsidian.python
          ? `şunu ekle: ${d.obsidian.python}` : 'sunucunun python programını ekle'}, sonra sunucuyu yeniden başlat`));
    }
    const g = d.gunluk || {};
    const gb = boyutMetni(g.boyut);
    if (gb) satirlar.push(satir('Günlük', `${g.dosya || 'server.log'} ${gb}${boyutMetni(g.yedek_boyut) ? ` (+ eski kısım ${boyutMetni(g.yedek_boyut)})` : ''} · 5 MB'ı geçince kısalır`));
    const l = d.limitler || {};
    if (Number.isFinite(l.max_running)) {
      satirlar.push(satir('Sınırlar', `aynı anda ${l.max_running} iş · proje başına ${l.max_running_per_project} · ` +
        `proje sırasında en çok ${l.max_queued_per_project} · bekleyen onay en çok ${l.max_bekleyen_onay}`));
    }
  }
  const zl = Array.isArray(st.schedules) ? st.schedules.filter(Boolean) : [];
  zl.slice(0, 5).forEach((z, i) => satirlar.push(satir(i ? '' : 'Zamanlanmış işler', [kisa(z.baslik || z.ad, 50), z.proje,
    z.duraklatildi ? 'duraklatıldı' : (b.zaman(z.sonraki) !== null ? `sonraki ${anMetni(b.zaman(z.sonraki), ms, b.tz)}` : '')]
    .filter(Boolean).join(' · '))));
  if (Array.isArray(st.schedules) && !zl.length) satirlar.push(satir('Zamanlanmış işler', 'yok'));
  return { satirlar, eylemler: [] };
}

// plan "Sonraki iş (9)" step 3: a specialisation's memory in one line (/api/state.hafiza, bin/hafiza.py ozet) — the
// lesson count, how many are verified, the newest lesson's date and the note as an Obsidian link ([[<key>-hafiza]]);
// '' without data. Only validated values reach the text (it is shown with textContent; the link is built by the page).
export function hafizaMetni(hafiza, key) {
  const h = hafiza && typeof hafiza === 'object' && Object.prototype.hasOwnProperty.call(hafiza, key) ? hafiza[key] : null;
  if (!h || typeof h !== 'object') return '';
  const n = Math.max(0, Math.floor(Number(h.ders) || 0));
  const v = Math.min(n, Math.max(0, Math.floor(Number(h.dogrulanmis) || 0)));
  const son = typeof h.son_tarih === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(h.son_tarih) ? h.son_tarih : '';
  const not = typeof h.not === 'string' && /^[a-z]{2,20}-hafiza$/.test(h.not) ? h.not : '';
  const parts = n ? [`${n} ders (${v} doğrulanmış)`] : ['henüz ders yok'];
  if (n && son) parts.push(`son ${son}`);
  if (not) parts.push(`[[${not}]]`);
  return parts.join(' · ');
}

// The İK card's presence counts (owner decision 2026-11-18) from kimNerede: {ofiste (everyone in, also on shift and
// not walking out), ajan (the CEO, the kadro, the auditors), personel (the rest in), nobette: ['Güvenlik · Ali', …] (the
// shift teams' people on shift, short names), otelde, yolda (walking to the Otel)}; null when it cannot be read. Pure.
export function ikVarligi(st, ms, aktorler = null) {
  let k = null;
  try { k = kimNerede(st && typeof st === 'object' ? st : {}, ms, aktorler); } catch (e) { return null; }
  const ofiste = k.ofiste.filter((e) => e.durum !== 'cikiyor');
  const ajan = ofiste.filter((e) => e.grup === 'ajan').length;
  const nobette = ofiste.filter((e) => e.durum === 'nobette').map((e) => `${NOBET_KISA[e.ekip] || 'Nöbet'} · ${rolKisa(e.ad)}`);
  return { ofiste: ofiste.length, ajan, personel: ofiste.length - ajan, nobette, otelde: k.evde.length,
    yolda: k.ofiste.length - ofiste.length };
}
// İK sorumlusu ("çalışanlar"): the roster by role with each one's state, this month's performance per role, open kadro
// proposals and running pilots (each pending card opens), the reviewers' scorecard in short.
export function ikKarti(st, ms, veri = {}, aktorler = null) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const eylemler = [];
  const rows = modelSatirlari(st.modeller, ms, b.sahne);
  rows.forEach((r, i) => satirlar.push(satir(i === 0 ? 'Kadro' : (r.grup === 'denetci' && rows[i - 1].grup !== 'denetci' ? 'Denetçiler' : ''),
    `${r.ad} · ${r.kisa || 'durumu bilinmiyor'}`)));
  const m = veri.muhasebe;
  for (const r of (m && Array.isArray(m.bu_ay_rol_kalite) ? m.bu_ay_rol_kalite : [])) {
    const parts = [`${r.is_sayisi} iş`];
    const ilk = oran(r.ilk_tur_gecen, r.ilk_tur_olculen);
    if (ilk) parts.push(`ilk turda ${ilk}`);
    if (Number.isFinite(r.dogrulanmis_is_basina_usd)) parts.push(`doğrulanmış iş başına ${paraTok(r.dogrulanmis_is_basina_usd, r.dogrulanmis_is_basina_token)}`);
    satirlar.push(satir(`Bu ay · ${r.rol}`, parts.join(' · ')));
  }
  // plan "Sonraki iş (9)" step 2: every specialisation with this month's jobs (GET /api/muhasebe bu_ay_uzmanlik)
  if (m && Array.isArray(m.bu_ay_uzmanlik)) {
    const by = new Map(m.bu_ay_uzmanlik.filter((u) => u && typeof u.uzmanlik === 'string').map((u) => [u.uzmanlik, u]));
    UZMANLIK_SIRA.forEach((key, i) => {
      const u = by.get(key);
      satirlar.push(satir(i ? '' : 'Uzmanlıklar · bu ay', `${UZMANLIK_BASLIK[key]} · ${u ? Number(u.is_sayisi) || 0 : 0} iş`));
    });
    const eski = by.get('');
    if (eski && eski.is_sayisi) satirlar.push(satir('', `uzmanlığı kayıtlı değil · ${eski.is_sayisi} iş`));
  }
  // plan "Sonraki iş (9)" step 3: each specialisation's memory (lessons, the newest one's date, its note)
  if (st.hafiza && typeof st.hafiza === 'object') {
    UZMANLIK_SIRA.filter((key) => hafizaMetni(st.hafiza, key)).forEach((key, i) => {
      satirlar.push(satir(i ? '' : 'Hafıza', `${UZMANLIK_BASLIK[key]} · ${hafizaMetni(st.hafiza, key)}`));
    });
  }
  const k = veri.kalite;
  const ms2 = k && k.model_secimi;
  for (const p of (ms2 && Array.isArray(ms2.pilotlar) ? ms2.pilotlar : [])) {
    satirlar.push(satir('Kadro denemesi', `${p.proje} · ${p.katman}: ${aileAdiOf(p.model)} deneniyor (${p.biten}/${p.toplam})`));
  }
  const dp = ms2 && ms2.danisman;  // the advisor pilot (bin/danisman.py), only while it runs
  if (dp && dp.durum === 'pilot') {
    satirlar.push(satir('Danışman denemesi', `${dp.katman} · ${aileAdiOf(dp.model)} danışman (${Number(dp.eklenen) || 0}/${Number(dp.is_sayisi) || 0} iş)`));
  }
  for (const d of b.kararlar.filter((x) => MODEL_KARTLARI.has(x.kind))) eylemler.push(kararEylemi(d, b, ms));
  for (const [i, x] of (k && Array.isArray(k.denetciler) ? k.denetciler : []).filter((x) => x && x.ad).entries()) {
    satirlar.push(satir(i ? '' : 'Denetçi karnesi', `${denetciAdi(x.ad)} · ${x.tur} tur${oran(x.gecerli, x.ciddi) ? ` · ciddi bulguların ${oran(x.gecerli, x.ciddi)} geçerli` : ''}`));
  }
  // owner decision 2026-11-18: who is in now (kimNerede, the guard's card's source): in the office, on shift, at the Otel
  const v = ikVarligi(st, ms, aktorler);
  if (v) {
    satirlar.push(satir('Ofiste', `${v.ofiste} kişi (${v.ajan} çalışan · ${v.personel} personel)`, { bolum: 'Şu an' }));
    if (v.nobette.length) satirlar.push(satir('Nöbette', v.nobette.join(', '), { bolum: 'Şu an' }));
    satirlar.push(satir('Otelde', `${v.otelde ? `${v.otelde} kişi` : 'kimse yok'}${v.yolda ? ` · ${v.yolda} kişi otele gidiyor` : ''}`, { bolum: 'Şu an' }));
  }
  eylemler.push({ tur: 'kalite', metin: 'Kalite sekmesini aç' });
  return { satirlar, eylemler };
}

// The Sosyal medya team ("sosyal medya"): no real work yet — the card says so honestly; the projects it would serve.
export function sosyalKarti(st, a) {
  const u = SOSYAL_EKIBI.find((x) => x.id === a.rol) || null;
  const satirlar = [satir('Görevi', u ? u.rol : 'Projeler için sosyal medya işleri yapacak.')];
  if (u) satirlar.push(satir('Alan', u.alan));
  satirlar.push(satir('Şu an', 'Şu an atanmış iş yok'));
  const ps = (Array.isArray(st.projects) ? st.projects : []).map((p) => p && p.name).filter(Boolean);
  if (ps.length) satirlar.push(satir('Hizmet edeceği projeler', ps.join(', ')));
  return { satirlar, eylemler: [] };
}

// Ofis doktoru ("ofis sağlığı"): today's stuck jobs (each opens), silent / permission-waiting sessions (the message
// delivery's own list), workers in "hata" with their last error, the newest rows of the server's error record. With
// nothing wrong: "Ofis sağlıklı" and what was checked.
export function doktorKarti(st, ms) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const eylemler = [];
  const takilan = b.tasks.filter((t) => t.status === 'tikandi' && b.bugun(b.zaman(t.finished)));
  takilan.slice(0, 4).forEach((t, i) => {
    satirlar.push(satir(i ? '' : 'Takılan işler', [t.project, isBasligi(t), anMetni(b.zaman(t.finished), ms, b.tz)].filter(Boolean).join(' · ')));
    eylemler.push({ tur: 'is', note: String(t.note), metin: `İşi aç: ${kisa(isBasligi(t), 40)}` });
  });
  const po = st.postoffice && typeof st.postoffice === 'object' ? st.postoffice : null;
  const sessiz = po && Array.isArray(po.silent) ? po.silent.filter(Boolean) : [];
  sessiz.slice(0, 4).forEach((x, i) => {
    const dk = Math.max(2, Math.floor((Number(x.seconds) || 0) / 60));
    satirlar.push(satir(i ? '' : 'Oturumlar', `${x.proje || '—'} · ${x.izin ? `${dk} dakikadır izin bekliyor` : `${dk} dakikadır sessiz`}`));
  });
  // owner decision 2026-11-18: the open jobs whose Kontrol failed (they are fixing it now), each opens
  const kaldi = b.tasks.filter((t) => AKTIF_IS.has(t.status) && t.kontrol_sonuc === 'kaldi');
  kaldi.slice(0, 4).forEach((t, i) => {
    const n = Math.floor(Number(t.kontrol_deneme) || 0);
    satirlar.push(satir(i ? '' : 'Kontrol\'ü geçmeyen', [t.project, isBasligi(t), n >= 2 ? `${n}. deneme` : 'düzeltiyor'].filter(Boolean).join(' · ')));
    eylemler.push({ tur: 'is', note: String(t.note), metin: `İşi aç: ${kisa(isBasligi(t), 40)}` });
  });
  const rows = modelSatirlari(st.modeller, ms, b.sahne).filter((r) => r.durum === 'hata');
  rows.forEach((r, i) => satirlar.push(satir(i ? '' : 'Hata veren', `${r.ad} · ${r.kisa}`)));
  const ol = Array.isArray(st.olaylar) ? st.olaylar.filter((x) => x && x.ileti) : [];
  const sorun = takilan.length + sessiz.length + rows.length + kaldi.length;
  if (!sorun) {
    const kontrol = ['takılan iş yok', 'Kontrol\'ü geçmeyen iş yok'];
    if (po) kontrol.push('sessiz oturum yok');
    if (Array.isArray(st.modeller)) kontrol.push('hata veren çalışan yok');
    satirlar.push(satir('Durum', 'Ofis sağlıklı'));
    satirlar.push(satir('Bakılanlar', kontrol.join(' · ')));
  }
  ol.slice(0, 5).forEach((x, i) => satirlar.push(satir(i ? '' : 'Sunucu kaydı',
    `${x.son || ''} · ${x.tur} · ${kisa(x.ileti, 80)}${x.sayi > 1 ? ` (${x.sayi} kez)` : ''}`)));
  return { satirlar, eylemler };
}

// IT sorumlusu ("sunucu odası ve sistem", GET /api/sistem — bin/sistem.py): the computer's load, memory, disk,
// battery and uptime, the process groups as totals only (never a process name), the rule-based suggestions and the
// projects' domains. Text only; a missing value leaves its line out. The office never closes or deletes anything.
const SEVIYE_ADI = { yesil: 'yeşil (rahat)', sari: 'sarı (yoğun)', kirmizi: 'kırmızı (çok yoğun)' };
const BASKI_ADI = { normal: 'normal', uyari: 'yüksek', kritik: 'kritik' };
const virgul = (x, n = 1) => (Number.isFinite(x) ? Number(x).toFixed(n).replace('.', ',') : '');
const gbMetni = (mb) => (Number.isFinite(mb) ? `${virgul(mb / 1024)} GB` : '');
// A shift team's rows (nobetEkibi / vardiya, from the clock in the office zone; one helper for the IT team, the guards and
// the Sekreters): who is on shift now and until when, the next change and who comes, then (ekip: true) each member's
// state.
const saatDk = (dk) => `${String(Math.floor(dk / 60)).padStart(2, '0')}:${String(dk % 60).padStart(2, '0')}`;
const vardiyaAraligi = (k) => `${saatDk(VARDIYALAR[k].bas)}–${saatDk(VARDIYALAR[k].bas + VARDIYA_DK)}`;
const NOBET_DURUM_ADI = { nobette: 'nöbette', iceride: 'ofiste (nöbet dışı)', evde: 'otelde' };
export function nobetSatirlari(ekip, st, ms, { ekipSatiri = true } = {}) {
  const e = NOBET_EKIPLERI[ekip];
  if (!e || ms === null || !Number.isFinite(ms)) return [];
  const sahne = (st && st.sahne) || {};
  const tz = sahne.saat_dilimi || DEFAULT_SAHNE.saat_dilimi;
  const v = ekipVardiyasi(ekip, ms, sahne);
  const y = e.uyeler[v.sonraki.kisi];
  const nb = { bolum: 'Nöbet' }; // the card's "Nöbet" section; the team as a table (kartDuzeni)
  const satirlar = [];
  if (v.nobetci === null) { // the Sekreters on a weekend or a public holiday (the work calendar)
    const g = gunTuru(ms, sahne);
    satirlar.push(satir('Nöbette', `kimse yok · ${g.tur === 'tatil' ? `resmî tatil (${g.kisa})` : 'hafta sonu'}`, nb));
  } else {
    satirlar.push(satir('Nöbette', `${e.uyeler[v.nobetci].ad} · ${v.ad} vardiyası (${vardiyaAraligi(v.vardiya)})`, nb));
    const bitis = anMetni(v.son, ms, tz);
    if (bitis) satirlar.push(satir('Nöbet bitişi', bitis, nb));
  }
  // "bugün 16:00" as before; another day by the work calendar's words ("yarın 00:00", "pazartesi 00:00")
  const anOf = (t) => ((gunSozu(t, ms, tz) || {}).fark === 0 ? anMetni(t, ms, tz) : gunluSaat(t, ms, tz));
  satirlar.push(satir('Sonraki değişim', `${anOf(v.sonraki.bas) || saatDk(VARDIYALAR[v.sonraki.vardiya].bas)} · ${y.ad} gelir (${v.sonraki.ad} vardiyası)`, nb));
  if (ekipSatiri) {
    nobetEkibi(ekip, ms, sahne).forEach((u, i) => {
      // the member's shift: the current one's hours, else when the next one starts (from the same clock)
      const p = nobetPlani(u.kisi, ms, sahne, ekip);
      const vrd = u.durum === 'nobette' ? vardiyaAraligi(v.vardiya)
        : p && p.sonraki ? `sıradaki ${anOf(p.sonraki.bas) || saatDk(VARDIYALAR[p.sonraki.vardiya].bas)}` : '';
      satirlar.push(satir(i ? '' : 'Ekip', `${u.ad} · ${NOBET_DURUM_ADI[u.durum] || u.durum}`, { ...nb,
        tablo: { anahtar: `nobet-${ekip}`, baslik: 'Ekip', basliklar: ['Kişi', 'Durum', 'Vardiya'],
          satirlar: [[u.ad, NOBET_DURUM_ADI[u.durum] || u.durum, vrd]] } }));
    });
  }
  return satirlar;
}
export const itEkibiSatirlari = (st, ms) => nobetSatirlari('sunucu', st, ms);

// The work calendar's day words (the owner, 2026-11-13: on Friday evening the staff return "pazartesi", not "yarın").
const GUN_ADLARI = ['pazar', 'pazartesi', 'salı', 'çarşamba', 'perşembe', 'cuma', 'cumartesi'];
const GUN_KISA = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
const AY_ADLARI = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const buyukHarf = (w) => w.charAt(0).toLocaleUpperCase('tr-TR') + w.slice(1);
// The day of moment t seen from ms in the office zone: {fark (days), metin: '' (today), 'dün', 'yarın', a weekday
// ('pazartesi': two to six days ahead with only a weekend between; 'cuma': two to six days back), or the date with its
// weekday ('2 Ocak Cuma': further ahead, or a public holiday lies between), kisa (the phone's form: 'yarın', 'Pzt',
// '2 Oca'), hafta (the weekday's name: 'pazartesi'), haftaKisa ('Pzt')}; null when unknown. Pure.
export function gunSozu(t, ms, tz = DEFAULT_SAHNE.saat_dilimi) {
  if (t === null || ms === null || !Number.isFinite(t) || !Number.isFinite(ms)) return null;
  let a, b;
  try { a = ofisSaati(ms, tz); b = ofisSaati(t, tz); } catch (e) { return null; }
  const no = (x) => Math.round(Date.UTC(x.yil, x.ay - 1, x.gun) / 86400000);
  const ga = no(a), gb = no(b), fark = gb - ga;
  const w = new Date(gb * 86400000).getUTCDay();
  const hafta = { hafta: GUN_ADLARI[w], haftaKisa: GUN_KISA[w] };
  const tarih = { metin: `${b.gun} ${AY_ADLARI[b.ay - 1]} ${buyukHarf(GUN_ADLARI[w])}`, kisa: `${b.gun} ${AY_ADLARI[b.ay - 1].slice(0, 3)}` };
  if (fark === 0) return { fark, metin: '', kisa: '', ...hafta };
  if (fark === -1) return { fark, metin: 'dün', kisa: 'dün', ...hafta };
  if (fark === 1) return { fark, metin: 'yarın', kisa: 'yarın', ...hafta };
  if (fark >= 2 && fark <= 6) {
    let tatilVar = false;
    for (let g = ga + 1; g < gb; g++) {
      const d = new Date(g * 86400000);
      if (tatil({ yil: d.getUTCFullYear(), ay: d.getUTCMonth() + 1, gun: d.getUTCDate() })) tatilVar = true;
    }
    return tatilVar ? { fark, ...tarih, ...hafta } : { fark, metin: GUN_ADLARI[w], kisa: GUN_KISA[w], ...hafta };
  }
  if (fark <= -2 && fark >= -6) return { fark, metin: GUN_ADLARI[w], kisa: GUN_KISA[w], ...hafta };
  return { fark, ...tarih, ...hafta };
}
// "HH:MM", "dün HH:MM", "yarın HH:MM", "pazartesi HH:MM", "2 Ocak Cuma HH:MM" (gunSozu) in the office zone; a time
// more than six days back keeps "12 Kas HH:MM"; '' when unknown.
function gunluSaat(t, ms, tz) {
  if (t === null || !Number.isFinite(t) || ms === null) return '';
  try {
    const g = gunSozu(t, ms, tz);
    if (!g) return '';
    const saat = saatOf(t, tz);
    if (g.fark < -6) return anMetni(t, ms, tz);
    return g.metin ? `${g.metin} ${saat}` : saat;
  } catch (e) { return ''; }
}
// One line of the guard's lists (the people "at home" stay at the Otel, owner decision 2026-11-14): "Muhasebeci · otelde · çıktı 18:41 · döner yarın 08:22", "2. sekreter · nöbette ·
// 16:00–24:00", "CEO · ofiste · uyuyor", "Çaycı · ofiste · geldi 08:27".
export function kimNeredeMetni(e, ms, tz) {
  const parts = [e.ad];
  if (e.durum === 'nobette') {
    parts.push('nöbette');
    if (Number.isInteger(e.vardiya)) parts.push(vardiyaAraligi(e.vardiya));
  } else if (e.durum === 'evde') {
    parts.push('otelde');
    const c = gunluSaat(e.cikis, ms, tz), d = gunluSaat(e.donus, ms, tz);
    if (c) parts.push(`çıktı ${c}`);
    if (d) parts.push(`döner ${d}`);
  } else if (e.durum === 'cikiyor') {
    parts.push('otele gidiyor');
  } else {
    parts.push(e.metin === 'nöbet dışı' ? 'ofiste (nöbet dışı)' : 'ofiste');
    if (e.metin && e.metin !== 'nöbet dışı') parts.push(e.metin);
    const g = gunluSaat(e.gelis, ms, tz);
    if (g) parts.push(`geldi ${g}`);
  }
  return parts.join(' · ');
}

// The dative of a spoken time: "08:00" -> "08:00'e", "16:00" -> "16:00'ya", "24:00" -> "24:00'e" (the minutes, or the
// hour on the full hour; "00:00" is sıfır).
const YONELME_BIRLER = { 0: 'a', 1: 'e', 2: 'ye', 3: 'e', 4: 'e', 5: 'e', 6: 'ya', 7: 'ye', 8: 'e', 9: 'a' };
const YONELME_ONLAR = { 1: 'a', 2: 'ye', 3: 'a', 4: 'a', 5: 'ye' };
export function saatYonelme(hhmm) {
  const m = String(hhmm || '').match(/^(\d\d):(\d\d)$/);
  if (!m) return String(hhmm || '');
  const sayi = Number(m[2]) || Number(m[1]);
  const ek = sayi % 10 ? YONELME_BIRLER[sayi % 10] : sayi ? YONELME_ONLAR[Math.floor(sayi / 10) % 10] || 'a' : 'a';
  return `${hhmm}'${ek}`;
}

// The departments of the office staff in the guard's card (kimNerede's grup 'personel'), in this order.
const KIM_BOLUMLERI = [
  { id: 'mudur', ad: 'Müdürler', uyar: (id) => id.startsWith('sus:mudur:') },
  { id: 'sosyal', ad: 'Sosyal medya ve tasarım', uyar: (id) => id.startsWith('sus:sosyal:') },
  { id: 'idari', ad: 'Muhasebe, İK, İdari işler', uyar: (id) => ['sus:muhasebe', 'sus:ik', 'sus:idari'].includes(id) },
  { id: 'hizmet', ad: 'Ofis hizmetleri', uyar: (id) => ['sus:cayci', 'sus:revir', 'sus:psikolog', 'sus:masaj'].includes(id) },
  { id: 'proje', ad: 'Proje sorumluları', uyar: (id) => id.startsWith('sus:proje:') },
  { id: 'diger', ad: 'Diğer personel', uyar: () => true },
];
const NOBET_KISA = { guvenlik: 'Güvenlik', sekreter: 'Sekreter', sunucu: 'IT', yemekhane: 'Yemekhane', asci: 'Aşçı' };
const NOBET_SIRASI = ['guvenlik', 'sekreter', 'sunucu', 'yemekhane', 'asci'];
// Several times in one text: "08:30–08:45" / "08:00 / 16:00", a shared day word said once ("yarın 08:13–08:48",
// "pazartesi 08:13–08:48").
function saatlerMetni(ts, ms, tz, ayrac) {
  const m = [...new Set(ts.filter((t) => Number.isFinite(t)))].sort((x, y) => x - y).map((t) => gunluSaat(t, ms, tz))
    .filter(Boolean);
  if (!m.length) return '';
  const on = m[0].match(/^(.+ )\d\d:\d\d$/); // a shared day word ("yarın ", "pazartesi ", "2 Ocak Cuma ")
  if (on && m.every((x) => x.startsWith(on[1]) && /^\d\d:\d\d$/.test(x.slice(on[1].length)))) return on[1] + m.map((x) => x.slice(on[1].length)).join(ayrac);
  return m.join(ayrac);
}
// A shift member's short name for the "Nöbette" line: "Güvenlik görevlisi (2.)", "IT uzmanı (1.)", "IT sorumlusu".
function nobetciAdi(e) {
  const u = ((NOBET_EKIPLERI[e.ekip] || {}).uyeler || []).find((x) => x.id === e.id);
  const n = String(e.ad || '').match(/^(\d+)\. /);
  const ad = (u && u.etiket) || e.ad;
  return n ? `${ad} (${n[1]}.)` : ad;
}
const rolKisa = (ad) => String(ad || '').replace(/\s*\([^)]*\)$/, '');
const grupSatiri = (metin, uyeler, anahtar) => ({ ad: '', metin: String(metin), uyeler, anahtar });
// The guard's "Ofiste olanlar" / "Otelde olanlar" (kimNerede's result), grouped (the owner, 2026-11-12: about 45 lines became
// about a dozen): in the office the CEO, the kadro by role and the auditors with their state, the people on shift, the
// other staff by department; at home each department and each off-shift team with a count and one return time. A group
// row carries `uyeler` (every member's full line, kimNeredeMetni: "Muhasebeci · evde · çıktı 18:22 · döner yarın
// 08:35") and a stable `anahtar`; the page shows it as a details element. Plain strings only.
export function kimNeredeSatirlari(k, ms, tz, { fazla = 0 } = {}) {
  const satirlar = [];
  const ofiste = (k && k.ofiste) || [], evde = (k && k.evde) || [];
  const metin = (e) => kimNeredeMetni(e, ms, tz);
  const durumlu = (e) => (e.metin ? `${rolKisa(e.ad)} ${e.metin.replace(/ · /g, ' ')}` : rolKisa(e.ad));
  // fazla: the workers beyond one body per kadro (fazlaIsciSayisi), so the guard's two counts agree
  satirlar.push(satir('Ofiste olanlar', `${ofiste.length + (Number(fazla) > 0 ? Number(fazla) : 0)} kişi`));
  const ajan = ofiste.filter((e) => e.grup === 'ajan');
  const ceo = ajan.find((e) => e.id === 'ceo');
  if (ceo) satirlar.push(satir('', `CEO: ${ceo.metin || 'ofiste'}`));
  const kadro = ajan.filter((e) => e.id.startsWith('kadro:'));
  // everyone of a group in one state says it once: "Kadro: Stajyer, Uzman, Kıdemli, Genel Müdür · uyuyor"
  const liste = (x) => {
    const m = x[0].metin;
    return x.length > 1 && m && x.every((e) => e.metin === m)
      ? `${x.map((e) => rolKisa(e.ad)).join(', ')} · ${m.replace(/ · /g, ' ')}` : x.map(durumlu).join(', ');
  };
  if (kadro.length) satirlar.push(grupSatiri(`Kadro: ${liste(kadro)}`, kadro.map(metin), 'ofiste:kadro'));
  const denetci = ajan.filter((e) => e.id !== 'ceo' && !e.id.startsWith('kadro:'));
  if (denetci.length) satirlar.push(grupSatiri(`Denetçiler: ${liste(denetci)}`, denetci.map(metin), 'ofiste:denetci'));
  const sira = (e) => NOBET_SIRASI.indexOf(e.ekip);
  const nobette = ofiste.filter((e) => e.durum === 'nobette').sort((x, y) => sira(x) - sira(y));
  if (nobette.length) {
    const son = nobette.find((e) => Number.isInteger(e.vardiya));
    const kadar = son ? ` · ${saatYonelme(saatDk(VARDIYALAR[son.vardiya].bas + VARDIYA_DK))} kadar` : '';
    satirlar.push(grupSatiri(`Nöbette: ${nobette.map(nobetciAdi).join(', ')}${kadar}`, nobette.map(metin), 'ofiste:nobet'));
  }
  // the other people in the office: the shift teams' colleagues off shift, then the staff by department
  const diger = ofiste.filter((e) => e.grup !== 'ajan' && e.durum !== 'nobette');
  for (const g of NOBET_SIRASI) {
    const x = diger.filter((e) => e.grup === 'nobet' && e.ekip === g);
    if (x.length) satirlar.push(grupSatiri(`${NOBET_KISA[g]} (nöbet dışı): ${x.length} kişi`, x.map(metin), `ofiste:nobet-disi:${g}`));
  }
  const bolum = (e) => KIM_BOLUMLERI.find((b) => b.uyar(e.id));
  for (const b of KIM_BOLUMLERI) {
    const x = diger.filter((e) => e.grup !== 'nobet' && bolum(e) === b);
    if (!x.length) continue;
    const cik = x.filter((e) => e.durum === 'cikiyor').length;
    satirlar.push(grupSatiri(`${b.ad}: ${x.length} kişi${cik ? ` (${cik} otele gidiyor)` : ''}`, x.map(metin), `ofiste:${b.id}`));
  }
  satirlar.push(satir('Otelde olanlar', evde.length ? `${evde.length} kişi` : 'kimse otelde değil'));
  for (const b of KIM_BOLUMLERI) {
    const x = evde.filter((e) => e.grup !== 'nobet' && bolum(e) === b);
    if (!x.length) continue;
    const ds = x.map((e) => e.donus).filter(Number.isFinite);
    const donus = ds.length ? saatlerMetni([Math.min(...ds), Math.max(...ds)], ms, tz, '–') : '';
    satirlar.push(grupSatiri([b.ad, `${x.length} kişi`, donus ? `döner ${donus}` : ''].filter(Boolean).join(' · '),
      x.map(metin), `evde:${b.id}`));
  }
  for (const g of NOBET_SIRASI) {
    const x = evde.filter((e) => e.grup === 'nobet' && e.ekip === g);
    if (!x.length) continue;
    const donus = saatlerMetni(x.map((e) => e.donus), ms, tz, ' / ');
    satirlar.push(grupSatiri(`${NOBET_KISA[g]} (${x.length} kişi)${donus ? ` · sonraki vardiya ${donus}` : ''}`,
      x.map(metin), `evde:nobet:${g}`));
  }
  return satirlar;
}

// The small corner line outside the office hours: "Mesai dışı · 31 kişi otelde · 08:30'da dönüyorlar" (kisa, a phone:
// "Mesai dışı · 31 otelde · 08:30"); '' inside the office hours or without any. N = kimNerede's home list. The work
// calendar: on a weekend "Hafta sonu · …", on a public holiday "Resmî tatil (29 Ekim) · …", and when the next work day
// is not today or tomorrow its day word comes before the time ("pazartesi 08:30'da dönüyorlar"; phone "Pzt 08:30").
// The people "at home" stay at the Otel now (owner decision 2026-11-14): "Mesai dışı · 31 kişi otelde · 08:30'da dönüyorlar".
export function mesaiDisiSatiri(st, now, { kisa: kisaMi = false } = {}) {
  const s = st && typeof st === 'object' ? st : {};
  let ms;
  try { ms = nowMs(now); } catch (e) { return ''; }
  const sahne = { ...DEFAULT_SAHNE, ...(s.sahne || {}) };
  if (!mesaiAraligi(sahne)) return '';
  const k = kimNerede(s, ms);
  if (k.mesai || !k.donus) return '';
  const n = k.evde.length;
  const g = k.gun || {};
  const bas = g.tur === 'hafta-sonu' ? 'Hafta sonu' : g.tur === 'tatil' ? `Resmî tatil (${g.kisa})` : 'Mesai dışı';
  const gs = Number.isFinite(k.donus_ms) ? gunSozu(k.donus_ms, ms, sahne.saat_dilimi) : null;
  // an ordinary evening or night needs no day word (as before); after a work day the next work day's name, and on a
  // day off the weekday even when it is tomorrow ("Hafta sonu · … · pazartesi 08:30'da dönüyorlar")
  const gunlu = !!gs && (gs.fark >= 2 || (gs.fark === 1 && g.tur && g.tur !== 'is'));
  const soz = !gunlu ? '' : gs.fark === 1 ? (kisaMi ? gs.haftaKisa : gs.hafta) : kisaMi ? gs.kisa : gs.metin;
  return kisaMi ? `${bas} · ${n} otelde · ${soz ? `${soz} ` : ''}${k.donus}`
    : `${bas} · ${n} kişi otelde · ${soz ? `${soz} ` : ''}${saatBulunma(k.donus)} dönüyorlar`;
}
// "08:30" -> "08:30'da" (the locative suffix of the spoken time: the minutes, or the hour on the full hour).
const SAYI_EKI = { 0: 'da', 1: 'de', 2: 'de', 3: 'te', 4: 'te', 5: 'te', 6: 'da', 7: 'de', 8: 'de', 9: 'da' };
const ONLUK_EKI = { 1: 'da', 2: 'de', 3: 'da', 4: 'ta', 5: 'de' };
export function saatBulunma(hhmm) {
  const m = String(hhmm || '').match(/^(\d\d):(\d\d)$/);
  if (!m) return String(hhmm || '');
  const sayi = Number(m[2]) || Number(m[1]) % 24;
  const ek = sayi % 10 ? SAYI_EKI[sayi % 10] : sayi ? ONLUK_EKI[Math.floor(sayi / 10) % 10] || 'da' : 'da';
  return `${hhmm}'${ek}`;
}
// the "Bilgisayar" section and a status bar per load figure (kartDuzeni; 70 % and up warns, 90 % and up is bad; with
// yuksekIyi — a pass rate — the other way round: under 70 % warns, under 40 % is bad)
const PC = { bolum: 'Bilgisayar' };
function cubukOf(yuzde, yuksekIyi = false) {
  if (!Number.isFinite(yuzde)) return {};
  const ton = yuksekIyi ? (yuzde < 40 ? 'kotu' : yuzde < 70 ? 'uyari' : 'iyi') : (yuzde >= 90 ? 'kotu' : yuzde >= 70 ? 'uyari' : 'iyi');
  return { cubuk: { yuzde: Math.max(0, Math.min(100, Math.round(yuzde))), ton } };
}
export function sistemKarti(st, ms, d) {
  const satirlar = itEkibiSatirlari(st, ms);
  const eylemler = [];
  const oz = st && st.sistem && typeof st.sistem === 'object' ? st.sistem : null;
  if (!d || typeof d !== 'object') {
    satirlar.push(satir('Durum', oz && SEVIYE_ADI[oz.seviye] ? `yük ${SEVIYE_ADI[oz.seviye]} · okunuyor…` : 'okunuyor…', PC));
    return { satirlar, eylemler };
  }
  const c = d.cpu || {};
  const cpu = [SEVIYE_ADI[d.seviye] ? `yük ${SEVIYE_ADI[d.seviye]}` : '', Number.isFinite(c.cekirdek) ? `${c.cekirdek} çekirdek` : '',
    Array.isArray(c.yuk) && Number.isFinite(c.yuk[0]) ? `ortalama yük ${virgul(c.yuk[0], 2)}` : '',
    Number.isFinite(c.yuk_orani) ? `çekirdek başına %${Math.round(c.yuk_orani * 100)}` : ''].filter(Boolean);
  if (cpu.length) satirlar.push(satir('İşlemci', cpu.join(' · '), { ...PC, ...cubukOf(Number.isFinite(c.yuk_orani) ? c.yuk_orani * 100 : NaN) }));
  const b = d.bellek || {};
  const bel = [Number.isFinite(b.kullanilan_gb) && Number.isFinite(b.toplam_gb) ? `${virgul(b.kullanilan_gb)} / ${virgul(b.toplam_gb)} GB kullanılıyor` : '',
    BASKI_ADI[b.baski] ? `baskı ${BASKI_ADI[b.baski]}` : '', Number.isFinite(b.bos_yuzde) ? `%${b.bos_yuzde} boş` : ''].filter(Boolean);
  const belYuzde = Number.isFinite(b.kullanilan_gb) && b.toplam_gb > 0 ? (100 * b.kullanilan_gb) / b.toplam_gb
    : Number.isFinite(b.bos_yuzde) ? 100 - b.bos_yuzde : NaN;
  if (bel.length) satirlar.push(satir('Bellek', bel.join(' · '), { ...PC, ...cubukOf(belYuzde) }));
  const dk = d.disk;
  if (dk && Number.isFinite(dk.dolu_yuzde)) satirlar.push(satir('Disk', `%${dk.dolu_yuzde} dolu${Number.isFinite(dk.bos_gb) ? ` · ${virgul(dk.bos_gb)} GB boş` : ''}`, { ...PC, ...cubukOf(dk.dolu_yuzde) }));
  if (d.pil && Number.isFinite(d.pil.yuzde)) satirlar.push(satir('Pil', `%${d.pil.yuzde}${d.pil.durum && d.pil.durum !== 'bilinmiyor' ? ` · ${d.pil.durum}` : ''}`, PC));
  if (Number.isFinite(d.acik_kalma_sn)) {
    const sa = Math.floor(d.acik_kalma_sn / 3600);
    satirlar.push(satir('Açık kalma', sa >= 24 ? `${Math.floor(sa / 24)} gün ${sa % 24} saat` : `${sa} saat ${Math.floor((d.acik_kalma_sn % 3600) / 60)} dk`, PC));
  }
  if (d.docker && Number.isFinite(d.docker.konteyner)) {
    satirlar.push(satir('Docker', `${d.docker.konteyner} konteyner · %${virgul(d.docker.cpu)} işlemci · ${gbMetni(d.docker.bellek_mb)}`, PC));
  }
  // the groups: totals only (bin/sistem.py never sends a process name)
  (Array.isArray(d.gruplar) ? d.gruplar : []).filter((g) => g && g.ad && g.sayi > 0).forEach((g, i) => {
    satirlar.push(satir(i ? '' : 'Süreç grupları', `${g.ad}: ${g.sayi} süreç · %${Math.round(Number(g.cpu) || 0)} işlemci · ${gbMetni(Number(g.bellek_mb) || 0)}`
      + (Number.isFinite(g.bosta) && g.bosta ? ` · ${g.bosta} boşta` : ''), { tablo: { anahtar: 'surec', basliklar: ['Grup', 'Adet', 'CPU %', 'Bellek', 'Boşta'],
      satirlar: [[g.ad, String(g.sayi), `%${Math.round(Number(g.cpu) || 0)}`, gbMetni(Number(g.bellek_mb) || 0), Number.isFinite(g.bosta) ? String(g.bosta) : '']] } }));
  });
  const on = (Array.isArray(d.oneriler) ? d.oneriler : []).filter((o) => o && o.metin);
  if (on.length) on.forEach((o, i) => satirlar.push(satir(i ? '' : 'Öneriler', kisa(o.metin, 240))));
  else satirlar.push(satir('Öneriler', 'Öneri yok: bilgisayar rahat'));
  const dom = d.domainler && typeof d.domainler === 'object' ? d.domainler : null;
  if (dom && !dom.liste_var) satirlar.push(satir('Domainler', dom.metin || 'Domain listesi henüz yok'));
  else if (dom) {
    (Array.isArray(dom.domainler) ? dom.domainler : []).forEach((x, i) => {
      if (!x || !x.domain) return;
      const h = x.https;
      const parts = [];
      if (!h) parts.push('henüz kontrol edilmedi');
      else {
        parts.push(h.acildi ? `açılıyor${h.durum_kodu ? ` (${h.durum_kodu})` : ''}` : `açılmıyor${h.hata ? ` (${h.hata})` : ''}`);
        if (Number.isFinite(h.gun)) parts.push(`sertifika ${h.gun} gün`);
      }
      if (x.dns) parts.push(x.dns.bulundu === false ? 'DNS bulunamadı' : x.dns.cloudflare ? 'Cloudflare' : 'Cloudflare değil');
      if (x.dns && x.dns.cloudflare_bekleniyor && x.dns.bulundu !== false && !x.dns.cloudflare) parts.push('Cloudflare bekleniyordu');
      const sor = (Array.isArray(x.sorunlar) ? x.sorunlar : []).map((s) => s && s.metin).filter(Boolean);
      if (sor.length) parts.push(`sorun: ${sor.join(', ')}`);
      satirlar.push(satir(i ? '' : 'Domainler', `${x.domain} · ${parts.join(' · ')}`));
    });
    (Array.isArray(dom.eposta) ? dom.eposta : []).forEach((x, i) => {
      if (!x || !x.domain) return;
      const mx = Array.isArray(x.mx) ? (x.mx.length ? x.mx.slice(0, 3).join(', ') : 'MX kaydı yok') : 'MX bilinmiyor';
      satirlar.push(satir(i ? '' : 'E-posta', `${x.domain} · ${mx}`));
    });
    if (dom.son_kontrol) {
      const t = zamanMs(dom.son_kontrol, (st.sahne && st.sahne.saat_dilimi) || 'Europe/Istanbul',
        st.sahne && st.sahne.sunucu_utc_ofset_dk);
      const an = anMetni(t, ms, (st.sahne && st.sahne.saat_dilimi) || 'Europe/Istanbul');
      if (an) satirlar.push(satir('Son kontrol', an));
    }
  }
  satirlar.push(satir('Not', `Ofis hiçbir şeyi kapatmaz ya da silmez; karar ${sahip('in')}.`));
  return { satirlar, eylemler };
}

// Ofis psikoloğu ("iş yükü"): the open jobs under pressure, each with a short advice line from the office rules
// (CLAUDE.md: escalation after two failed Kontrols, budget and call limits need the owner's yes, devam rounds). Nothing: "Ekip rahat".
export function psikologKarti(st, ms) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const eylemler = [];
  const acik = b.tasks.filter((t) => AKTIF_IS.has(t.status) && !onayAdimi(t)); // the approval step is the owner's
  const ekle = (t, durum, ogut) => {
    satirlar.push(satir(kisa(isBasligi(t), 40), `${durum} — ${ogut}`));
    if (!eylemler.some((e) => e.note === t.note)) eylemler.push({ tur: 'is', note: String(t.note), metin: `İşi aç: ${kisa(isBasligi(t), 40)}` });
  };
  for (const t of acik) {
    const s0 = b.zaman(t.started);
    if (s0 !== null && ms !== null && ms - s0 > 3600000) ekle(t, `${sureMetni(s0, ms)} çalışıyor`, 'ilerlemiyorsa CEO oturumun son mesajlarına bakar');
    // the Kontrol: only what really happened (kontrol_sonuc 'kaldi' = the last run failed); an escalation only when
    // a job escalated from this one exists
    const deneme = Number(t.kontrol_deneme) || 0;
    const kaldi = t.kontrol_sonuc === 'kaldi';
    const yukseldi = b.tasks.some((x) => x.escalated_from && notKoku(x.escalated_from) === notKoku(t.note));
    if (t.status === 'kontrolde' && deneme >= 2) ekle(t, `Kontrol ${deneme}. kez çalışıyor`, `geçmezse iş bir üst katmana taşınır ya da ${sahip('e')} sorulur`);
    else if (kaldi && deneme >= 2) ekle(t, `Kontrol ${deneme} kez kaldı`, yukseldi ? 'iş bir üst katmanda sürüyor' : 'brif yeniden yazılsın');
    else if (kaldi && deneme === 1 && t.status === 'calisiyor') ekle(t, 'Kontrol bir kez kaldı', 'ajan düzeltiyor; ikinci kez kalırsa iş bir üst katmana taşınır');
    const spent = Number(t.spent), budget = Number(t.budget);
    if (budget > 0 && spent / budget >= 0.8) ekle(t, `kullanım sınırının ${yuzdeMetni((100 * spent) / budget)} kullanıldı`, `devam için ${sahip('in')} onayı gerekir`);
    const calls = Number(t.calls), max = Number(t.max_calls);
    if (max > 0 && calls / max >= 0.8) ekle(t, `çağrı sınırının ${yuzdeMetni((100 * calls) / max)} kullanıldı`, 'sınırı aşınca iş durur');
    if (Number(t.devam) >= 2) ekle(t, `${t.devam} kez devam edildi`, 'işi daha küçük parçalara bölmek iyi olur');
  }
  for (const w of (Array.isArray(st.workflows) ? st.workflows : []).filter((w) => w && w.durum !== 'bitti' && w.durum !== 'iptal')) {
    if (Number(w.inceleme_turu) >= 2 || Number(w.plan_turu) >= 2) {
      satirlar.push(satir(kisa(w.baslik || w.grup, 40), `${Math.max(Number(w.inceleme_turu) || 0, Number(w.plan_turu) || 0)}. inceleme turu — iki turda da düzelmezse akış durur, ${sahip()} karar verir`));
    }
  }
  if (!satirlar.length) satirlar.push(satir('Durum', 'Ekip rahat'));
  return { satirlar, eylemler: eylemler.slice(0, 4) };
}

// Masajcı ("masaj odası"): who worked longest today (per role, the jobs' start → finish / now), who is on a table now.
export function masajKarti(st, ms, aktorler) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  if (ms !== null) {
    const sure = ['haiku', 'sonnet', 'opus', 'fable'].map((f) => [f, calismaSuresi(b.tasks, f, ms, b.tz, b.ofset)])
      .filter(([, x]) => x > 0).sort((x, y) => y[1] - x[1]);
    sure.slice(0, 4).forEach(([f, x], i) => satirlar.push(satir(i ? '' : 'Bugün en çok çalışan',
      `${calisanAdi(unvanOf(f).unvan, f)} · ${sureMetni(ms - x, ms)}`)));
  }
  if (Array.isArray(aktorler)) {
    const yatan = aktorler.filter((a) => a && a.poz === 'masajda');
    satirlar.push(satir('Şu an masajda', yatan.length ? yatan.map((a) => rolAdi(a.etiket || a.unvan || 'ajan')).join(', ') : 'kimse yok'));
  }
  return { satirlar, eylemler: [] };
}

const AKTIF_IS = new Set(['baslatiliyor', 'calisiyor', 'kontrolde', 'incelemede', 'karar-bekliyor']);
const IS_DURUMU = { baslatiliyor: 'başlıyor', calisiyor: 'çalışıyor', kontrolde: 'Kontrol çalışıyor', incelemede: 'incelemede',
  'karar-bekliyor': '{sahip_in} kararını bekliyor' };
const isDurumuMetni = (status) => (IS_DURUMU[status] || status || '').replace('{sahip_in}', sahip('in'));
// "<Proje> sorumlusu" ("proje bilgisi"): the project's description and folder name, what runs now, the queue, the last
// finished jobs, this month's spending of the project.
export function projeKarti(st, ms, proje, veri = {}) {
  const b = personelBaglami(st, ms);
  const satirlar = [];
  const eylemler = [];
  const p = (Array.isArray(st.projects) ? st.projects : []).find((x) => x && x.name === proje) || null;
  if (p && p.description) satirlar.push(satir('Proje', kisa(p.description, 120)));
  if (p && p.klasor) satirlar.push(satir('Klasör', p.klasor));
  // the summary of its note OFIS/Projeler/<proje>.md (bin/sorumlu.py): the rules and the three sections
  const so = p && p.sorumlu && typeof p.sorumlu === 'object' ? p.sorumlu : null;
  if (so) {
    if (so.kurallar) satirlar.push(satir('Kurallar', kisa(so.kurallar, 160)));
    if (Array.isArray(so.hassas_yollar) && so.hassas_yollar.length) satirlar.push(satir('Hassas yollar', kisa(so.hassas_yollar.join(', '), 120)));
    for (const [key, ad] of [['dur_sor', 'Durup sorar'], ['asla', 'Asla yapmaz'], ['teslim', 'Teslim']]) {
      const list = Array.isArray(so[key]) ? so[key].filter((x) => typeof x === 'string' && x) : [];
      list.slice(0, 2).forEach((x, i) => satirlar.push(satir(i ? '' : ad, kisa(x, 110))));
      if (list.length > 2) satirlar.push(satir('', `+${list.length - 2} madde (notta)`));
    }
  }
  const mine = b.tasks.filter((t) => t.project === proje);
  const aktif = mine.filter((t) => AKTIF_IS.has(t.status));
  aktif.slice(0, 4).forEach((t, i) => {
    const fam = modelAilesi(isModeli(t, null, st.katmanlar));
    // the approval step is the owner's: no worker's role
    satirlar.push(satir(i ? '' : 'Şimdi', [isBasligi(t), onayAdimi(t) ? '' : calisanAdi(rolMetni(fam, t.uzmanlik), fam),
      onayAdimi(t) ? `${sahip('in')} onayını bekliyor` : isDurumuMetni(t.status),
      sureMetni(b.zaman(t.started), ms)].filter((x) => x && x !== '—').join(' · ')));
    eylemler.push({ tur: 'is', note: String(t.note), metin: `İşi aç: ${kisa(isBasligi(t), 40)}` });
  });
  if (!aktif.length) satirlar.push(satir('Şimdi', 'çalışan iş yok'));
  const sira = mine.filter((t) => t.status === 'sirada');
  if (sira.length) {
    const held = sira.filter((t) => t.held).length, engel = sira.filter((t) => t.blocked).length;
    satirlar.push(satir('Sırada', [`${sira.length} iş`, held ? `${held} bekletiliyor` : '', engel ? `${engel} engelli` : ''].filter(Boolean).join(' · ')));
  }
  for (const w of (Array.isArray(st.workflows) ? st.workflows : []).filter((w) => w && w.proje === proje && w.durum !== 'bitti' && w.durum !== 'iptal')) {
    if (Number.isFinite(w.tamam) && Number.isFinite(w.toplam)) satirlar.push(satir('Akış', `${kisa(w.baslik || w.grup, 50)} · ${w.tamam}/${w.toplam} adım`));
  }
  const biten = mine.filter((t) => BITMIS.has(t.status) && b.zaman(t.finished) !== null)
    .sort((x, y) => b.zaman(y.finished) - b.zaman(x.finished)).slice(0, 5);
  biten.forEach((t, i) => {
    const cost = t.spent !== '' && t.spent != null ? usdTok(t.spent, t.tokens) : '';
    satirlar.push(satir(i ? '' : 'Son işler', [isBasligi(t), SONUC_ADI[t.status], anMetni(b.zaman(t.finished), ms, b.tz), cost].filter(Boolean).join(' · ')));
  });
  if (biten[0]) eylemler.push({ tur: 'is', note: String(biten[0].note), metin: `Son işi aç: ${kisa(isBasligi(biten[0]), 40)}` });
  const m = veri.muhasebe;
  const ay = m && m.bu_ay && Array.isArray(m.bu_ay.proje) ? m.bu_ay.proje.find((x) => x && x.proje === proje) : null;
  if (ay) satirlar.push(satir('Bu ay kullanım', `${usdTok(ay.usd, ay.token)} · ${ay.is_sayisi} iş`));
  else if (m && m.bu_ay) satirlar.push(satir('Bu ay kullanım', `${usdText(0)} · 0 iş`));
  eylemler.push({ tur: 'raporlar', metin: 'Raporlar sekmesini aç' });
  return { satirlar, eylemler };
}

// --- the company structure (plan "Sonraki iş (9)" step 1, owner decision 2026-11-13) ---

const AKTIF_BOLUM = new Set(['baslatiliyor', 'calisiyor', 'kontrolde', 'incelemede', 'karar-bekliyor']);
// An open job's line on a manager's card: "ornek-uygulama · Bildirimler · Kıdemli (Opus) · çalışıyor · 12 dk".
function bolumIsSatiri(t, b, ms, st) {
  const fam = modelAilesi(isModeli(t, null, st.katmanlar));
  const kim = panelIncelemesi(t) ? 'denetçi heyeti' : isDepartmani(t) === 'qa' ? testerUnvani(fam)
    : isDepartmani(t) === 'analist' ? 'İş analisti' : calisanAdi(rolMetni(fam, t.uzmanlik), fam);
  return [t.project, isBasligi(t), kim, isDurumuMetni(t.status), sureMetni(b.zaman(t.started), ms)]
    .filter((x) => x && x !== '—').join(' · ');
}
// The open work of a department now (display only, from the jobs' own tier, step and status).
export function bolumIsleri(st, ms, alan) {
  const b = personelBaglami(st && typeof st === 'object' ? st : {}, ms);
  const aktif = b.tasks.filter((t) => AKTIF_BOLUM.has(t.status) && !onayAdimi(t));
  if (alan === 'yazilim') {
    return { kod: aktif.filter((t) => isDepartmani(t) === 'yazilim' && !planIsi(t)), plan: aktif.filter((t) => planIsi(t)) };
  }
  if (alan === 'qa') {
    return { inceleme: aktif.filter((t) => isDepartmani(t) === 'qa'), kontrol: aktif.filter((t) => t.status === 'kontrolde') };
  }
  if (alan === 'analist') return { plan_inceleme: aktif.filter((t) => isDepartmani(t) === 'analist') };
  if (alan === 'it') {
    const s = st && st.sistem && typeof st.sistem === 'object' ? st.sistem : null;
    const guv = (Array.isArray(st && st.decisions) ? st.decisions : []).filter((d) => d && d.guvenlik_acik && !d.answer_sent);
    const den = st && st.denetim && typeof st.denetim === 'object' ? st.denetim : null;
    return { sistem: s, guvenlik: guv, guvenlik_calisiyor: !!den && Array.isArray(den.denetciler) && den.denetciler.includes(GUVENLIK),
      incelenen: den && typeof den.is === 'string' ? den.is : '' };
  }
  return {};
}

// A manager's card (Yazılım / QA / Analist / IT Müdürü): its department, whom it reports to, its people (the IT team's
// shift live) and the real work in its area right now — Yazılım: the running kod jobs (and planning); QA: the reviews and
// the Kontrol runs; Analist: the plan reviews; IT: the Sunucu odası's suggestions and the open security findings. Only
// what /api/state (and GET /api/sistem for IT, veri.sistem) says; a missing value leaves its line out.
export function mudurKarti(st, ms, alan, aktorler = null, veri = {}) {
  const s = st && typeof st === 'object' ? st : {};
  const m = MUDURLUKLER.find((x) => x.key === alan);
  const satirlar = [];
  const eylemler = [];
  if (!m) return { satirlar, eylemler };
  const b = personelBaglami(s, ms);
  satirlar.push(satir('Departman', m.departman));
  satirlar.push(satir('Bağlı olduğu', GENEL_MUDUR));
  m.ekip.forEach((e, i) => satirlar.push(satir(i ? '' : 'Ekibi', e)));
  const x = bolumIsleri(s, ms, alan);
  const liste = (ad, list, bos) => {
    if (!list.length) { satirlar.push(satir(ad, bos)); return; }
    list.slice(0, 4).forEach((t, i) => {
      satirlar.push(satir(i ? '' : ad, bolumIsSatiri(t, b, ms, s)));
      eylemler.push({ tur: 'is', note: String(t.note), metin: `İşi aç: ${kisa(isBasligi(t), 40)}` });
    });
    if (list.length > 4) satirlar.push(satir('', `+${list.length - 4} iş daha`));
  };
  // owner decision 2026-11-18: the department's jobs that need a look (silent now, or stuck today), each opens
  sorunluIsler(s, ms, alan).forEach(({ t, neden }, i) => {
    satirlar.push(satir(i ? '' : 'Bakılması gereken', [t.project, isBasligi(t), neden].filter(Boolean).join(' · ')));
    eylemler.push({ tur: 'is', note: String(t.note), metin: `İşi aç: ${kisa(isBasligi(t), 40)}` });
  });
  if (alan === 'yazilim') {
    const projeler = (Array.isArray(s.projects) ? s.projects : []).map((p) => (p && p.name) || p).filter((p) => p && p !== ARGE_PROJESI);
    if (projeler.length) satirlar.push(satir('Proje ekipleri', projeler.join(', ')));
    liste('Kod işleri', x.kod, 'şu an çalışan kod işi yok');
    if (x.plan.length) liste('Planlama', x.plan, '');
    uzmanligaGore(x.kod, s).forEach(([ad, kim], i) => satirlar.push(satir(i ? '' : 'Uzmanlığa göre', `${ad}: ${kim}`)));
  } else if (alan === 'qa') {
    const qa = (Array.isArray(aktorler) ? aktorler : []).filter((a) => a && /^qa-masa-\d$/.test(a.yer || '') && a.tur === 'ajan');
    if (qa.length) satirlar.push(satir('QA odasında', qa.map((a) => rolAdi(a.etiket)).join(', ')));
    liste('İncelemeler', x.inceleme, 'şu an inceleme yok');
    liste('Kontrol', x.kontrol, 'şu an çalışan Kontrol yok');
  } else if (alan === 'analist') {
    liste('Plan incelemeleri', x.plan_inceleme, 'şu an plan incelemesi yok');
  } else if (alan === 'it') {
    const it = nobetEkibi('sunucu', ms, b.sahne).find((u) => u.durum === 'nobette');
    if (it) satirlar.push(satir('Nöbette', it.ad));
    const sis = x.sistem;
    if (sis) {
      satirlar.push(satir('Sunucu odası', [SEVIYE_ADI[sis.seviye] ? `yük ${SEVIYE_ADI[sis.seviye]}` : '',
        `${Number(sis.oneri) || 0} öneri`, `${Number(sis.domain_sorunu) || 0} domain sorunu`].filter(Boolean).join(' · ')));
    } else satirlar.push(satir('Sunucu odası', 'henüz ölçülmedi'));
    const on = (veri && veri.sistem && Array.isArray(veri.sistem.oneriler) ? veri.sistem.oneriler : []).filter((o) => o && o.metin);
    on.slice(0, 3).forEach((o, i) => satirlar.push(satir(i ? '' : 'Öneriler', kisa(o.metin, 200))));
    if (x.guvenlik_calisiyor) {
      const t = b.tasks.find((t2) => notKoku(t2.note) === notKoku(x.incelenen));
      satirlar.push(satir('IT güvenlik uzmanı', `şu an inceliyor${t ? ` · ${isBasligi(t)}` : ''}`));
    }
    if (x.guvenlik.length) {
      x.guvenlik.forEach((d, i) => { satirlar.push(satir(i ? '' : 'Güvenlik bulguları', kisa(d.title || notKoku(d.note), 80)));
        eylemler.push(kararEylemi(d, b, ms)); });
    } else satirlar.push(satir('Güvenlik bulguları', 'açık güvenlik bulgusu yok'));
  }
  return { satirlar, eylemler };
}

// A department's jobs that need a look now (owner decision 2026-11-18): the silent ones (the server's list) and the ones
// stuck today, of the department `alan` (isDepartmani; the IT has none): [{t, neden: 'sessiz' | 'takıldı'}], at most
// four, silent first. Pure.
export function sorunluIsler(st, ms, alan) {
  const s = st && typeof st === 'object' ? st : {};
  if (!['yazilim', 'qa', 'analist'].includes(alan)) return [];
  const b = personelBaglami(s, ms);
  const neden = bakilacakIsler(s);
  const out = [];
  for (const t of b.tasks) {
    const n = neden.get(notKoku(t.note));
    if (!n || onayAdimi(t) || isDepartmani(t) !== alan) continue;
    if (n === 'takildi' && !b.bugun(b.zaman(t.finished))) continue;
    out.push({ t, neden: n === 'sessiz' ? 'sessiz' : 'takıldı' });
  }
  return out.sort((x, y) => (x.neden === y.neden ? 0 : x.neden === 'sessiz' ? -1 : 1)).slice(0, 4);
}

// The Yazılım Müdürü's people by specialisation (plan "Sonraki iş (9)" step 2): [[title, "ornek-uygulama Kıdemli, blog Stajyer"]]
// over its open kod work, in the profiles' order; work without a specialisation (genel, older jobs) under "Genel".
export function uzmanligaGore(tasks, st = {}) {
  const groups = new Map();
  for (const t of tasks || []) {
    const fam = modelAilesi(isModeli(t, null, st && st.katmanlar));
    const key = uzmanlikEki(fam, t.uzmanlik) ? t.uzmanlik : 'genel';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(`${t.project || '—'} ${unvanOf(fam).unvan}`);
  }
  return UZMANLIK_SIRA.filter((k) => groups.has(k)).map((k) => [UZMANLIK_BASLIK[k], groups.get(k).join(', ')]);
}

// The Genel Müdür's card (the fable kadro): the org summary — its managers (present or home, kimNerede) and the
// open work of each department, and the workflow approval cards waiting for the owner.
export function genelMudurOzeti(st, ms, aktorler = null) {
  const s = st && typeof st === 'object' ? st : {};
  const out = [];
  if (ms === null) return out;
  const k = kimNerede(s, ms, aktorler);
  const nerede = new Map([...k.ofiste, ...k.evde].map((e) => [e.id, e]));
  // the four managers, the İK ve İdari İşler Müdürü (the İK staff NPC) and the Ar-Ge uzmanı report to it (orgSemasi)
  out.push(satir('Bağlı müdürler', [...MUDURLUKLER.map((m) => [mudurId(m.key), m.ad]), ['sus:ik', TESIS_PERSONELI.ik],
    ['sus:arge', TESIS_PERSONELI.arge]].map(([id, ad]) => {
    const e = nerede.get(id);
    return `${ad} (${!e ? 'bilinmiyor' : e.durum === 'evde' ? 'otelde' : e.durum === 'cikiyor' ? 'çıkıyor' : 'ofiste'})`;
  }).join(', ')));
  const say = (alan) => { const x = bolumIsleri(s, ms, alan); return Object.values(x).filter(Array.isArray).reduce((n, l) => n + l.length, 0); };
  const sis = s.sistem && typeof s.sistem === 'object' ? s.sistem : null;
  const guv = (Array.isArray(s.decisions) ? s.decisions : []).filter((d) => d && d.guvenlik_acik && !d.answer_sent).length;
  const y = bolumIsleri(s, ms, 'yazilim'), q = bolumIsleri(s, ms, 'qa');
  out.push(satir('Şirket şu an', [`Yazılım: ${y.kod.length} kod · ${y.plan.length} plan`,
    `QA: ${q.inceleme.length} inceleme · ${q.kontrol.length} Kontrol`, `Analiz: ${say('analist')} plan incelemesi`,
    `IT: ${sis ? Number(sis.oneri) || 0 : 0} öneri · ${guv} güvenlik bulgusu`].join(' · ')));
  const onay = (Array.isArray(s.decisions) ? s.decisions : []).filter((d) => d && d.kind === 'akis-onay' && !d.answer_sent).length;
  if (onay) out.push(satir('Onay bekleyen', `${onay} akış onay kartı (özeti CEO'ya götürür)`));
  return out;
}

// The org chart ("Şema"): the owner → CEO → Genel Müdür → the four managers → their teams, from real data only — who is in
// the office, on shift or home (kimNerede, the shifts), and each node's state (the actors drawn now: their state text;
// a role whose body works as a job is "çalışıyor"). Node: {id, ad, alt, durum, yer: 'ofiste' | 'nobette' | 'evde' (at the
// Otel) | 'kota' (a reviewer whose quota is full: "kota doldu") | 'cikiyor' | '', aktor (an actor id whose card the node opens, or null), kart (a minimal actor for one not drawn now),
// cocuklar}. Plain strings only.
export function orgSemasi(st, now, aktorler = null) {
  const s = st && typeof st === 'object' ? st : {};
  let ms = null;
  try { ms = nowMs(now); } catch (e) { ms = null; }
  const akt = new Map((Array.isArray(aktorler) ? aktorler : []).filter((a) => a && a.id).map((a) => [a.id, a]));
  const k = ms === null ? { ofiste: [], evde: [] } : kimNerede(s, ms, aktorler);
  const nerede = new Map([...k.ofiste, ...k.evde].map((e) => [e.id, e]));
  const durumOf = (id, yoksa = '') => { const a = akt.get(id); return a ? String(a.durum_metni || '') : yoksa; };
  const yerOf = (id) => { const e = nerede.get(id); return e ? (e.durum === 'ofiste' ? 'ofiste' : e.durum) : ''; };
  const dugum = (id, ad, alt, durum, yer, kart, cocuklar = []) => ({ id, ad, alt, durum, yer, aktor: akt.has(id) ? id : null,
    kart: kart || null, cocuklar });
  const personel = (id, ad, gorevli, extra = {}) => {
    const e = nerede.get(id);
    const durum = akt.has(id) ? durumOf(id) : e && e.durum === 'evde' ? 'otelde' : '';
    return dugum(id, ad, extra.alt || '', durum, yerOf(id), { id, tur: 'sus', gorevli, etiket: ad, durum_metni: durum, ...extra.kart });
  };
  const ajan = (id, ad, alt, yoksa, kart = null) => {
    const durum = durumOf(id, yoksa);
    return dugum(id, ad, alt, durum, 'ofiste', kart && { ...kart, durum_metni: durum });
  };
  // the kadro: one per Claude family; a family whose body works as a job (devral) is not drawn: "çalışıyor"
  const kadroKarti = (f) => ({ id: `kadro:${f}`, tur: 'ajan', kadro: true, model: f, unvan: UNVAN[f].unvan,
    etiket: `${UNVAN[f].unvan} (${MODEL_ADI[f]})` });
  const kadro = (f) => ajan(`kadro:${f}`, UNVAN[f].unvan, MODEL_ADI[f], 'çalışıyor', kadroKarti(f));
  const projeler = (Array.isArray(s.projects) ? s.projects : []).map((p) => (p && p.name) || p).filter((p) => p && p !== ARGE_PROJESI);
  const b = personelBaglami(s, ms);
  const acikIs = (p) => b.tasks.filter((t) => t.project === p && AKTIF_BOLUM.has(t.status) && !onayAdimi(t)).length;
  const y = bolumIsleri(s, ms, 'yazilim'), q = bolumIsleri(s, ms, 'qa'), an = bolumIsleri(s, ms, 'analist');
  const odadakiler = (re) => [...akt.values()].filter((a) => a.tur === 'ajan' && re.test(a.yer || ''))
    .map((a) => dugum(a.id, rolAdi(a.etiket), a.proje || '', String(a.durum_metni || ''), 'ofiste', null));
  const mudur = (key, cocuklar) => {
    const m = MUDURLUKLER.find((x) => x.key === key);
    const n = personel(mudurId(key), m.ad, 'mudur', { alt: m.departman, kart: { alan: key } });
    n.cocuklar = cocuklar;
    return n;
  };
  const yazilim = mudur('yazilim', [
    dugum('kadro', 'Kadro (kıdem)', 'Stajyer · Uzman · Kıdemli', '', '', null, ['haiku', 'sonnet', 'opus'].map(kadro)),
    dugum('projeler', 'Proje ekipleri', `${y.kod.length} kod işi${y.plan.length ? ` · ${y.plan.length} plan` : ''}`, '', '', null,
      projeler.map((p) => { const n = personel(`sus:proje:${p}`, `${aileAdiOf2(p)} sorumlusu`, 'proje', { alt: `${p} ekibi`, kart: { proje: p } });
        const c = acikIs(p); n.durum = [n.durum, c ? `${c} açık iş` : ''].filter(Boolean).join(' · ');
        n.ekip = dekorSatiri(`${p} ekibi`, DEKOR_EKIP.proje); return n; })),
  ]);
  // the Değerlendirme ekibi (bin/gunsonu.py): its two members, in the office only while its work runs
  const deg = ms === null ? { calisiyor: false } : degerlendirmeDurumu(s, ms);
  const gs = s.gun_sonu && typeof s.gun_sonu === 'object' ? s.gun_sonu : null;
  const degUyeleri = DEGERLENDIRME_EKIBI.map((u) => {
    const n = personel(u.id, u.etiket, 'degerlendirme', { alt: 'Değerlendirme ekibi', kart: { etiket: u.etiket } });
    if (!n.durum) n.durum = 'akşam çalışır';
    return n;
  });
  const degDurum = deg.calisiyor ? 'çalışıyor' : !gs || !gs.acik ? 'kapalı'
    : gs.son && gs.son.gun ? `son: ${gunAdi(gs.son.gun) || gs.son.gun}` : 'henüz çalışmadı';
  const analist = mudur('analist', [Object.assign(dugum('analist-odasi', 'Analist odası', 'iş analistleri',
    `${an.plan_inceleme.length} plan incelemesi`, '', null, odadakiler(/^analist-masa-\d$/)),
  { ekip: dekorSatiri('Analist ekibi', DEKOR_EKIP.analist) }),
  dugum('degerlendirme-ekibi', 'Değerlendirme ekibi', `gün sonu · ${(gs && gs.pencere) || '20:00–24:00'}`, degDurum, '', null, degUyeleri)]);
  // a shift team (IT, guard, Sekreter): every member with its shift from kimNerede — "gündüz vardiyası · 08:00–16:00" on
  // shift, "sıradaki vardiya 16:00" at home —; the team's own line names who is on shift now
  const tz = b.sahne.saat_dilimi;
  const vardiyaMetni = (e) => {
    if (!e) return '';
    if (e.durum === 'nobette' && Number.isInteger(e.vardiya) && VARDIYALAR[e.vardiya]) {
      return `${VARDIYALAR[e.vardiya].ad} vardiyası · ${vardiyaAraligi(e.vardiya)}`;
    }
    if (e.metin === 'nöbet dışı') return 'nöbet dışı';
    const d = e.durum === 'evde' ? gunluSaat(e.donus, ms, tz) : '';
    return d ? `sıradaki vardiya ${d}` : '';
  };
  const nobetEkibiDugumu = (id, ad, alt, gorevli) => {
    const uyeler = NOBET_EKIPLERI[gorevli].uyeler.map((u) => {
      const n = personel(u.id, u.ad, gorevli, { alt: u.etiket, kart: { etiket: u.etiket } });
      n.durum = [/^otelde/.test(n.durum) ? '' : n.durum, vardiyaMetni(nerede.get(u.id))].filter(Boolean).join(' · ');
      return n;
    });
    const nobetci = uyeler.filter((n) => n.yer === 'nobette').map((n) => n.ad);
    return dugum(id, ad, alt, nobetci.length ? `nöbette: ${nobetci.join(', ')}` : '', '', null, uyeler);
  };
  // the review panel's outside reviewers (QA): each one's real state — the actor drawn now ("hazır", "inceliyor · P",
  // "Evde · …"), else its model row ("hazır", "1 çalışıyor · hazır", "kota doldu · …"); "evde" while its quota is full
  const modelRows = modelSatirlari(s.modeller, ms, b.sahne);
  const denetciDugumu = (ad) => {
    const id = `denetci:${ad}`;
    const a = akt.get(id);
    const r = modelRows.find((x) => x.model === ad && x.grup === 'denetci') || null;
    const durum = a ? String(a.durum_metni || '') : (r && r.kisa) || 'durumu bilinmiyor';
    const evde = a ? a.poz === 'evde' : !!r && r.durum === 'kota';
    const ucretsiz = ad !== 'codex';
    // a quota stop is not a hotel stay (review, 2026-11-14): its own place 'kota', never 'evde' (which reads "otelde")
    return dugum(id, denetciAdi(ad), ucretsiz ? `${UNVAN.codex.unvan} · ücretsiz` : UNVAN.codex.unvan, durum, evde ? 'kota' : 'ofiste',
      { id, tur: 'ajan', denetci: true, ucretsiz, model: ad, unvan: UNVAN.codex.unvan, etiket: denetciAdi(ad), durum_metni: durum });
  };
  const disDenetciler = denetciListesi(s.modeller).filter((ad) => ad !== GUVENLIK).map(denetciDugumu);
  const inceleyen = disDenetciler.filter((n) => /^(inceliyor|\d+ çalışıyor)/.test(n.durum)).length;
  const hakem = (() => { const a = akt.get('hakem');
    return dugum('hakem', 'Hakem', 'denetçilerin bulgularını tartar', a ? String(a.durum_metni || '') : 'incelemede çağrılır',
      a ? 'ofiste' : '', a ? null : { id: 'hakem', tur: 'ajan', hakem: true, etiket: 'Hakem', durum_metni: 'incelemede çağrılır' }); })();
  const qa = mudur('qa', [Object.assign(dugum('qa-odasi', 'QA odası', 'Stajyer Tester · Kıdemli Tester',
    `${q.inceleme.length} inceleme · ${q.kontrol.length} Kontrol`, '', null, odadakiler(/^qa-masa-\d$/)),
  { ekip: dekorSatiri('QA ekibi', DEKOR_EKIP.qa) }),
  dugum('dis-denetciler', 'Dış denetçiler', 'kod incelemesi', inceleyen ? `${inceleyen} inceliyor` : '', '', null, disDenetciler),
  hakem]);
  const it = mudur('it', [
    nobetEkibiDugumu('it-ekibi', 'IT ekibi', 'Sunucu odası · nöbetli', 'sunucu'),
    (() => { const id = `denetci:${GUVENLIK}`; const a = akt.get(id);
      return dugum(id, 'IT güvenlik uzmanı', GUVENLIK_UNVAN, a ? String(a.durum_metni || '') : 'çağrıldığında çalışır', a ? 'ofiste' : '',
        { id, tur: 'ajan', denetci: true, model: GUVENLIK, aile: 'sonnet', etiket: 'IT güvenlik uzmanı', durum_metni: 'çağrıldığında çalışır' }); })(),
  ]);
  // the İK ve İdari İşler Müdürü (the İK staff NPC, owner decision 2026-11-13) and the office's support staff under it
  const tek = (key, alt) => personel(`sus:${key}`, TESIS_PERSONELI[key], key, { alt });
  const ik = tek('ik', 'İnsan kaynakları ve idari işler');
  ik.cocuklar = [
    nobetEkibiDugumu('sekreterler', 'Sekreterler', 'Resepsiyon · nöbetli', 'sekreter'),
    nobetEkibiDugumu('guvenlik-ekibi', 'Güvenlik ekibi', 'Giriş · nöbetli', 'guvenlik'),
    tek('muhasebe', 'Muhasebe'),
    tek('idari', 'İdari işler'),
    dugum('ofis-hizmetleri', 'Ofis hizmetleri', 'çay, yemek, sağlık', '', '', null, [
      personel('sus:cayci', 'Çaycı', 'cayci', { alt: 'Çay ocağı' }),
      nobetEkibiDugumu('ascilar', `Aşçılar (${NOBET_EKIPLERI.asci.uyeler.length})`, 'Mutfak · nöbetli', 'asci'),
      nobetEkibiDugumu('yemekhane-ekibi', `Yemekhane (${NOBET_EKIPLERI.yemekhane.uyeler.length})`, 'Yemekhane · nöbetli', 'yemekhane'),
      tek('revir', 'Revir'), tek('psikolog', 'Psikolog'), tek('masaj', 'Masaj odası')]),
    dugum('sosyal-ekip', 'Sosyal medya ve tasarım', `${SOSYAL_EKIBI.length} kişi`, '', '', null,
      SOSYAL_EKIBI.map((u) => personel(`sus:sosyal:${u.id}`, u.ad, 'sosyal', { alt: u.alan, kart: { rol: u.id } }))),
  ];
  const arge = tek('arge', 'Ar-Ge odası');
  const gm = ajan('kadro:fable', GENEL_MUDUR, MODEL_ADI.fable, 'çalışıyor', kadroKarti('fable'));
  gm.cocuklar = [yazilim, qa, analist, it, ik, arge];
  const c = st && s.ceo ? s.ceo : {};
  const ceo = dugum('ceo', 'CEO', '', durumOf('ceo', c.state || ''), 'ofiste', { id: 'ceo', tur: 'ceo', etiket: 'CEO' }, [gm]);
  return dugum('deniz', sahip(), 'kurucu', '', '', null, [ceo]);
}
// The org chart's group line of the decorative people of a room (owner decision 2026-11-13): one line on the room's box, never a
// box per person — they are figures, not staff.
const dekorSatiri = (ad, n) => `${ad}: ${n} kişi · görünüm amaçlı`;
// The card of a decorative person (scene.js setDekor; actor {tur: 'dekor', grup, proje}): what it is, plainly, and the
// room's real numbers already in the org chart — nothing invented.
export function dekorKarti(st, ms, a) {
  const s = st && typeof st === 'object' ? st : {};
  const grup = a && a.grup;
  const ne = satir('Ne', 'Odanın boş görünmemesi için konmuş bir figür; gerçek bir çalışan ya da model oturumu değildir, '
    + 'iş yapmaz ve hiçbir sayıya katılmaz.');
  if (grup === 'qa') {
    const q = bolumIsleri(s, ms, 'qa');
    return { baslik: 'QA ekibi', alt: 'görünüm amaçlı', satirlar: [ne,
      satir('QA odası şu an', `${q.inceleme.length} inceleme · ${q.kontrol.length} Kontrol`)], eylemler: [] };
  }
  if (grup === 'analist') {
    const an = bolumIsleri(s, ms, 'analist');
    return { baslik: 'Analist ekibi', alt: 'görünüm amaçlı', satirlar: [ne,
      satir('Analist odası şu an', `${an.plan_inceleme.length} plan incelemesi`)], eylemler: [] };
  }
  if (grup === 'ortak') { // the common areas' people (2026-11-18): where it is, and the office's real numbers now
    const b = personelBaglami(s, ms);
    const acik = b.tasks.filter((t) => AKTIF_BOLUM.has(t.status) && !onayAdimi(t)).length;
    const yer = a.yuruyen ? 'koridorda yürüyor' : ODA_ADI[a.oda] || '';
    return { baslik: 'Ofisten biri', alt: 'görünüm amaçlı', satirlar: [ne, ...(yer ? [satir('Nerede', yer)] : []),
      satir('Ofiste şu an', `${acik} açık iş · ${b.kararlar.length} bekleyen soru`)], eylemler: [] };
  }
  const p = String((a && a.proje) || '');
  const b = personelBaglami(s, ms);
  const c = b.tasks.filter((t) => t.project === p && AKTIF_BOLUM.has(t.status) && !onayAdimi(t)).length;
  return { baslik: p ? `${p} ekibi` : 'Proje ekibi', alt: 'görünüm amaçlı', satirlar: [ne,
    satir(p ? `${p} şu an` : 'Şu an', `${c} açık iş`)], eylemler: [] };
}
const aileAdiOf2 = (p) => { const x = String(p || ''); return x ? x[0].toUpperCase() + x.slice(1) : ''; };

// state + actor (+ secenek.aktorler: the actors drawn now, for a "+N") -> {baslik, alt, satirlar: [{ad, metin}], eylemler: [{tur: 'is', metin, note} | {tur: 'komuta', metin}
// | {tur: 'kararlar', metin}]}. Only what the state says: a missing value leaves its line out, never invents one.
// Plain strings for textContent, never HTML.
// The shared character card's layout (owner decision 2026-11-13, "kartlar okunaklı olsun"): karakterKarti's flat rows grouped
// into titled sections for the one card component in app.js (kartIcerigi). Rules, in order:
// - a row with `bolum` goes into the section of that name (a new one when the previous section has another name);
// - a row without a name (ad '') continues the section before it;
// - a named row followed by unnamed rows opens a section of its own, named after the row (a list);
// - any other named row gathers in "Özet" (the first section) or "Diğer bilgiler" (a later one).
// Items: {tur: 'satir', ad, metin, cubuk?: {yuzde 0-100, ton iyi|uyari|kotu}} (label and value, an optional status
// bar), {tur: 'madde', metin} (a list line), {tur: 'grup', metin, uyeler, anahtar} (a folding group), {tur: 'tablo',
// anahtar, baslik, basliklar, satirlar} (rows with the same tablo.anahtar in a row form one table). Every row lands in
// exactly one item: its text, or for a table row the same facts in cells — the layout never drops or invents data.
// Pure; plain strings.
export const KART_LISTE_SINIRI = 6; // a list longer than this shows its first KART_LISTE_SINIRI - 1 lines, the rest folded
export function kartDuzeni(k) {
  const rows = (k && Array.isArray(k.satirlar) ? k.satirlar : []).filter((r) => r && typeof r === 'object');
  const bolumler = [];
  let cur = null;
  const ac = (baslik, tur) => { cur = { baslik: String(baslik), tur, ogeler: [] }; bolumler.push(cur); };
  const ekle = (r, madde) => {
    const t = r.tablo;
    if (t && Array.isArray(t.basliklar) && Array.isArray(t.satirlar)) {
      const hucreler = t.satirlar.filter(Array.isArray).map((x) => t.basliklar.map((_, i) => String(x[i] ?? '')));
      const son = cur.ogeler[cur.ogeler.length - 1];
      if (son && son.tur === 'tablo' && son.anahtar === String(t.anahtar || '')) son.satirlar.push(...hucreler);
      else {
        cur.ogeler.push({ tur: 'tablo', anahtar: String(t.anahtar || ''), baslik: String(t.baslik || ''),
          basliklar: t.basliklar.map(String), satirlar: hucreler });
      }
      return;
    }
    if (Array.isArray(r.uyeler)) {
      cur.ogeler.push({ tur: 'grup', metin: String(r.metin), uyeler: r.uyeler.map(String), anahtar: String(r.anahtar || r.metin) });
      return;
    }
    if (madde || !r.ad) { cur.ogeler.push({ tur: 'madde', metin: String(r.metin) }); return; }
    const o = { tur: 'satir', ad: String(r.ad), metin: String(r.metin) };
    if (r.cubuk && Number.isFinite(r.cubuk.yuzde)) {
      o.cubuk = { yuzde: Math.max(0, Math.min(100, Math.round(r.cubuk.yuzde))),
        ton: ['iyi', 'uyari', 'kotu'].includes(r.cubuk.ton) ? r.cubuk.ton : 'iyi' };
    }
    cur.ogeler.push(o);
  };
  rows.forEach((r, i) => {
    const next = rows[i + 1];
    if (r.bolum) {
      if (!cur || cur.baslik !== String(r.bolum)) ac(r.bolum, 'bolum');
      ekle(r, false);
    } else if (!r.ad) {
      if (!cur) ac('Özet', 'ozet');
      ekle(r, true);
    } else if (next && !next.ad && !next.bolum) {
      ac(r.ad, 'liste');
      ekle(r, true);
    } else {
      if (!cur || cur.tur !== 'ozet') ac(bolumler.length ? 'Diğer bilgiler' : 'Özet', 'ozet');
      ekle(r, false);
    }
  });
  return bolumler;
}

// NPC chat (owner decision 2026-11-18, "gerçekten akıllı NPC'ler"; bin/npc_sohbet.py): the role key POST /api/npc-sohbet
// takes for a staff character, or null for one that stays plain (decor, tea, kitchen, masseur, social media, the
// Değerlendirme ekibi, the kadro, jobs, the CEO). The server checks the key again against its own fixed set. Pure.
const SOHBET_ROLLERI = new Set(['sekreter', 'muhasebe', 'idari', 'ik', 'psikolog', 'revir', 'sunucu', 'arge', 'guvenlik']);
const SOHBET_MUDURLERI = new Set(['yazilim', 'qa', 'analist', 'it']);
export const NPC_SORU_SINIRI = 500; // bin/npc_sohbet.py SORU_SINIRI
export function npcSohbetRolu(a) {
  if (!a || a.tur !== 'sus') return null;
  const key = a.gorevli || String(a.id || '').replace(/^sus:/, '');
  if (SOHBET_ROLLERI.has(key)) return key;
  if (key === 'mudur' && SOHBET_MUDURLERI.has(a.alan)) return `mudur:${a.alan}`;
  if (key === 'proje' && /^[a-z0-9][a-z0-9-]{0,39}$/.test(String(a.proje || ''))) return `proje:${a.proje}`;
  return null;
}
// The card's question box: {kutu: true} when the owner can ask, else {kutu: false, ipucu} — the one-line hint (off in
// ofis.json npc_sohbet, or the demo). Pure.
export function npcSohbetKutusu(st, demo = false) {
  if (demo) return { kutu: false, ipucu: T('Soru sormak demo modunda çalışmaz.') };
  const n = st && typeof st === 'object' ? st.npc_sohbet : null;
  if (!n || n.acik !== true) return { kutu: false, ipucu: T('Bu karaktere soru sormak için Ayarlar › Genel’den NPC sohbetini aç.') };
  return { kutu: true, ipucu: '' };
}
// The answer area after POST /api/npc-sohbet: {cevap, alt} on 200 (alt = the usage line, tokens first), else {hata}
// in plain Turkish (the server's own message when it sent one). Text only: the page sets it with textContent. Pure.
export function npcSohbetSonucu(status, data) {
  const d = data && typeof data === 'object' ? data : {};
  if (status === 200 && typeof d.cevap === 'string' && d.cevap.trim()) {
    return { cevap: d.cevap.trim(), alt: typeof d.kullanim === 'string' && d.kullanim ? T('Kullanım: {kullanim}', { kullanim: d.kullanim }) : '' };
  }
  if (status === 0) return { hata: T('Sunucuya ulaşılamadı; biraz sonra yeniden dene.') };
  if (status === 403) return { hata: T('İstek reddedildi; sayfayı yenileyip tekrar dene.') };
  if (typeof d.error === 'string' && d.error) return { hata: d.error };
  return { hata: T('Cevap alınamadı (hata {status}).', { status }) };
}

export function karakterKarti(actor, state, now, secenek = {}) {
  const a = actor && typeof actor === 'object' ? actor : {};
  const st = state && typeof state === 'object' ? state : {};
  const sahne = { ...DEFAULT_SAHNE, ...(st.sahne || {}) };
  const tz = sahne.saat_dilimi;
  const ofset = Number.isFinite(sahne.sunucu_utc_ofset_dk) ? sahne.sunucu_utc_ofset_dk : null;
  let ms = null;
  try { ms = nowMs(now); } catch (e) { ms = null; }
  const tasks = new Map();
  const add = (t) => { if (t && t.note && !tasks.has(notKoku(t.note))) tasks.set(notKoku(t.note), t); };
  (st.tasks || []).forEach(add);
  (st.board || []).forEach(add);
  const taskOf = (note) => (note ? tasks.get(notKoku(note)) || null : null);
  const sessions = (st.sessions || []).filter((x) => x && x.name);
  const sessionOf = (t) => (t ? sessions.find((x) => x.note && notKoku(x.note) === notKoku(t.note)) ||
    sessions.find((x) => t.session && x.name === t.session) || null : null);
  const rows = modelSatirlari(st.modeller, ms, sahne);
  const rowOf = (model) => rows.find((r) => r.model === model) || null;
  const durum = String(a.durum_metni || '');
  const out = { baslik: String(a.etiket || a.unvan || 'Karakter'), alt: durum, satirlar: [], eylemler: [] };
  const modelSatiri = (m) => { const n = MODEL_ADI[modelAilesi(m)]; if (n) out.satirlar.push(satir('Model', n)); };
  const isAc = (note, metin = 'İşi aç') => { if (note) out.eylemler.push({ tur: 'is', metin, note: String(note) }); };
  const sonuc = (t) => [kisa(t.title || notKoku(t.note), 60), SONUC_ADI[t.status] || t.status,
    anMetni(zamanMs(t.finished, tz, ofset), ms, tz)].filter(Boolean).join(' · ');

  if (a.tur === 'dekor') return dekorKarti(st, ms, a);
  if (a.tur === 'ceo') {
    const c = st.ceo || {};
    out.baslik = 'CEO';
    out.satirlar.push(satir('Görevi', `${sahip('in')} isteklerini işlere çevirir, soruları ona taşır`));
    if (durum) out.satirlar.push(satir('Durum', durum));
    if (c.current_tool) out.satirlar.push(satir('Şu an', kisa(c.current_tool, 60)));
    const q = Math.max(0, Math.floor(Number(c.queue) || 0));
    if (q) out.satirlar.push(satir('Sırada', `${q} mesaj`));
    if (c.cost_today) {
      const tok = tokenMetni(c.usage_today);
      out.satirlar.push(satir('Bugün', `${tok ? `${tok} · ` : ''}${usdText(c.cost_today)}`));
    }
    out.eylemler.push({ tur: 'komuta', metin: 'Komuta masasını aç' });
    return out;
  }
  if (a.tur === 'sus') {
    const key = a.gorevli || String(a.id || '').replace(/^sus:/, '');
    const [ad, rolHam] = SUS_ROL[key] || [out.baslik, 'Ofisin çalışanlarından.'];
    const rol = rolHam.replace('{sahip_i}', sahip('i')); // the owner's name, read now (the Ayarlar tab can change it)
    out.baslik = ad;
    out.satirlar.push(satir('Görevi', rol));
    const veri = secenek.veri && typeof secenek.veri === 'object' ? secenek.veri : {};
    if (key === 'sosyal') {
      out.baslik = String(a.etiket || 'Sosyal medya');
      const k = sosyalKarti(st, a);
      out.alt = 'sosyal medya ve tasarım';
      out.satirlar = k.satirlar;
      return out;
    }
    if (key === 'sunucu') out.baslik = String(a.etiket || ad); // IT sorumlusu (the lead) or IT uzmanı
    if (key === 'degerlendirme') out.baslik = String(a.etiket || ad); // Ölçüm uzmanı / Değerlendirme uzmanı
    if (key === 'mudur') { // plan "Sonraki iş (9)": a manager — its department, its people and the real work in its area
      const m = MUDURLUKLER.find((x) => x.key === a.alan);
      out.baslik = (m && m.ad) || String(a.etiket || 'Müdür');
      out.satirlar = [satir('Görevi', m ? `${m.gorev}. Bir model oturumu değildir: gerçek işler katmanlar ve akış adımlarıyla yürür.` : 'Müdür')];
    }
    if (key === 'proje') {
      out.baslik = String(a.etiket || 'Proje sorumlusu');
      out.satirlar = [satir('Görevi', `${a.proje || 'proje'} ekibinin işi varken masasında oturur; projenin durumunu bilir. Bir çalışan değildir.`)];
    }
    const ek = key === 'sekreter' ? sekreterKarti(st, ms)
      : key === 'guvenlik' ? guvenlikKarti(st, ms, secenek.aktorler)
      : key === 'cayci' ? cayciKarti(st, ms, secenek.aktorler)
      : key === 'yemekhane' ? yemekhaneKarti(st, ms, secenek.aktorler, 'yemekhane')
      : key === 'asci' ? yemekhaneKarti(st, ms, secenek.aktorler, 'asci')
      : key === 'muhasebe' ? muhasebeKarti(st, ms, veri.muhasebe)
      : key === 'idari' ? idariKarti(st, ms, veri.idari)
      : key === 'ik' ? ikKarti(st, ms, veri, secenek.aktorler)
      : key === 'revir' ? doktorKarti(st, ms)
      : key === 'sunucu' ? sistemKarti(st, ms, veri.sistem)
      : key === 'arge' ? argeKarti(st, ms, veri.arge, a)
      : key === 'degerlendirme' ? degerlendirmeKarti(st, ms, a)
      : key === 'psikolog' ? psikologKarti(st, ms)
      : key === 'masaj' ? masajKarti(st, ms, secenek.aktorler)
      : key === 'proje' ? projeKarti(st, ms, a.proje, veri)
      : key === 'mudur' ? mudurKarti(st, ms, a.alan, secenek.aktorler, veri) : null;
    if (key === 'mudur' && ek) { out.alt = 'departman'; out.satirlar.push(...ek.satirlar); out.eylemler.push(...ek.eylemler); return out; }
    if (ek) { out.alt = SUS_KONU[key] || KARTLAR[key]; out.satirlar.push(...ek.satirlar); out.eylemler.push(...ek.eylemler); }
    return out;
  }
  if (a.tur === 'ozet') {
    // "+N": the actors that did not fit, found in the state — the jobs of that team / the queued jobs / the helpers
    // that no drawn actor (secenek.aktorler) stands for; elsewhere (full rooms) its own summary line
    out.baslik = String(a.etiket || '+');
    out.alt = 'sığmayanlar';
    const shown = new Set((Array.isArray(secenek.aktorler) ? secenek.aktorler : []).map((x) => x && x.id));
    const id = String(a.id || '');
    const isAdi = (t) => { const f = modelAilesi(isModeli(t, sessionOf(t), st.katmanlar)); return calisanAdi(rolMetni(f, t.uzmanlik), f); };
    let hidden = [];
    if (id.startsWith('ozet:ekip-') && Array.isArray(a.gizliler)) {
      // exactly the team's jobs the engine left out (a job drawn elsewhere — a Codex review, the CEO-door queue — is
      // never among them)
      hidden = a.gizliler.filter((g) => g && (g.note || g.etiket)).map((g) => {
        const t = taskOf(g.note);
        return t ? satir(isAdi(t), kisa(t.title || notKoku(t.note), 60)) : satir(rolAdi(g.etiket || 'ajan'), g.durum_metni || '—');
      });
    } else if (id === 'ozet:lobi') {
      hidden = [...tasks.values()].filter((t) => t.status === 'sirada' && !shown.has(`is:${notKoku(t.note)}`))
        .map((t) => satir(`${t.project || '—'} · ${isAdi(t)}`, kisa(t.title || notKoku(t.note), 60)));
    } else if (id.endsWith('/alt:+')) {
      const parent = id.slice(0, -'/alt:+'.length);
      const t = parent.startsWith('is:') ? taskOf(parent.slice(3)) : null;
      const ses = parent === 'ceo' ? st.ceo : sessionOf(t) || sessions.find((x) => `oturum:${x.name}` === parent);
      hidden = ((ses && ses.alt_ajanlar) || []).filter((x) => x && x.id && !x.bitti && !shown.has(`${parent}/alt:${x.id}`))
        .map((x) => satir(`Yardımcı (${aileAdiOf(x.model)})`, kisa(x.gorev, 60) || 'yardım ediyor'));
    }
    // a full common room (canteen, tea corner, Uzmanlar odası, CEO's door): the engine lists them (gizliler)
    if (!hidden.length && Array.isArray(a.gizliler)) {
      hidden = a.gizliler.filter((g) => g && g.etiket).map((g) => satir(rolAdi(g.etiket), g.durum_metni || '—'));
    }
    out.satirlar.push(...hidden.slice(0, 20));
    if (!out.satirlar.length && durum) out.satirlar.push(satir('Durum', durum));
    return out;
  }
  if (a.tur === 'alt-ajan') {
    out.baslik = rolAdi(out.baslik);
    modelSatiri(a.model);
    const parentNote = a.tiklama && a.tiklama.note;
    const parent = taskOf(parentNote);
    const hid = String(a.id || '').split('/alt:')[1] || '';
    const ses = sessionOf(parent) || (String(a.ebeveyn || '') === 'ceo' ? st.ceo : null);
    const h = ((ses && ses.alt_ajanlar) || []).find((x) => x && x.id === hid) || null;
    out.satirlar.push(satir('Görevi', (h && kisa(h.gorev, 200)) || durum || '—'));
    if (durum) out.satirlar.push(satir('Durum', durum));
    if (parent) out.satirlar.push(satir('Ana iş', kisa(parent.title || notKoku(parent.note), 80)));
    else if (a.ebeveyn === 'ceo') out.satirlar.push(satir('Ana iş', 'CEO'));
    isAc(parentNote, 'Ana işi aç');
    return out;
  }
  if (a.denetci || a.hakem) {
    const ad = String(a.model || '');
    const guvenlik = ad === 'guvenlik';
    if (a.hakem) {
      out.baslik = 'Hakem';
      modelSatiri(a.model);
      out.satirlar.push(satir('Görevi', 'hakem: denetçilerin ciddi bulgularını tek tek tartar, geçerli olanları ayırır'));
    } else if (guvenlik) {
      // plan "Sonraki iş (9)": the IT güvenlik uzmanı at the IT güvenlik desk of the Sunucu odası stands for its runs
      out.baslik = 'IT güvenlik uzmanı';
      modelSatiri(a.aile || 'sonnet');
      out.satirlar.push(satir('Görevi', `${GUVENLIK_UNVAN}: değişikliğin getirdiği güvenlik açıklarını arar`));
      out.satirlar.push(satir('Bağlı olduğu', 'IT Müdürü'));
    } else {
      out.baslik = denetciAdi(ad) || out.baslik;
      out.satirlar.push(satir('Görevi', a.ucretsiz
        ? 'dış denetçi: kod incelemesi yapar; ücretsiz, yalnız izinli projelerde'
        : 'dış denetçi: kod incelemesi yapar, bulguları önem sırasıyla yazar'));
    }
    const r = !a.hakem && !guvenlik ? rowOf(ad) : null;
    out.satirlar.push(satir('Durum', (r && r.kisa) || durum || 'durumu bilinmiyor'));
    const cur = a.tiklama && a.tiklama.note;
    if (cur) {
      const t = taskOf(cur);
      out.satirlar.push(satir('İncelediği iş', t ? kisa(t.title || notKoku(t.note), 80) : notKoku(cur)));
    }
    if (ad === 'codex') {
      const last = [...tasks.values()].filter((t) => BITMIS.has(t.status) && /^codex/.test(String(t.inceleme_yurutucu || '')))
        .sort((x, y) => (zamanMs(y.finished, tz, ofset) || 0) - (zamanMs(x.finished, tz, ofset) || 0))[0];
      if (last) out.satirlar.push(satir('Son incelemesi', sonuc(last)));
    }
    out.satirlar.push(satir('Karnesi', "Obsidian'da Karne/Denetciler"));
    isAc(cur);
    return out;
  }
  if (a.kadro) {
    const f = modelAilesi(a.model);
    out.baslik = String(a.unvan || (UNVAN[f] && UNVAN[f].unvan) || 'Kadro');
    modelSatiri(f);
    const gorev = kadroGorevi(f, st.katmanlar);
    if (gorev) out.satirlar.push(satir('Görevi', gorev));
    const r = rowOf(f);
    // the model's row (all its workers, e.g. "1 çalışıyor · hazır"), not this character's own state (that is `alt`)
    out.satirlar.push(satir('Model durumu', (r && r.kisa) || 'durumu bilinmiyor'));
    if (durum) out.alt = durum;
    if (f === 'fable') out.satirlar.push(...genelMudurOzeti(st, ms, secenek.aktorler));
    const fam = [...tasks.values()].filter((t) => modelAilesi(isModeli(t, null, st.katmanlar)) === f);
    const last = fam.filter((t) => BITMIS.has(t.status) && zamanMs(t.finished, tz, ofset) !== null)
      .sort((x, y) => zamanMs(y.finished, tz, ofset) - zamanMs(x.finished, tz, ofset))[0];
    if (last) {
      const cost = last.spent !== '' && last.spent != null ? paraTok(last.spent, last.tokens) : '';
      out.satirlar.push(satir('Son işi', [sonuc(last), cost].filter(Boolean).join(' · ')));
      isAc(last.note);
    }
    if (ms !== null) {
      const gun = anMetni(ms, ms, tz);
      const today = fam.filter((t) => { const s = zamanMs(t.started, tz, ofset); return s !== null && anMetni(s, ms, tz).startsWith('bugün'); });
      if (gun && today.length) {
        const sum = today.reduce((n, t) => n + (Number(t.spent) || 0), 0);
        // only the known token counts; how many jobs have none (never counted as 0)
        const known = today.map((t) => tokenSayisi(t.tokens)).filter((n) => n !== null);
        const missing = today.length - known.length;
        const tok = known.length ? ` · ${tokenMetni(known.reduce((a, n) => a + n, 0))}${missing ? ` (${missing} işte kayıtlı değil)` : ''}` : '';
        out.satirlar.push(satir('Bugün', `${today.length} iş${tok} · ${usdText(sum)}`));
      }
    }
    return out;
  }
  // a job (or an office session) of a project
  const note = a.tiklama && a.tiklama.note;
  const t = taskOf(note);
  const ses = sessionOf(t) || sessions.find((x) => `oturum:${x.name}` === a.id) || null;
  out.baslik = String(a.rol_metni || a.unvan || 'Ajan'); // "Kıdemli Backend" (plan "Sonraki iş (9)" step 2)
  out.alt = [a.proje, durum].filter(Boolean).join(' · ');
  modelSatiri(a.model);
  if (t) {
    out.satirlar.push(satir('İş', kisa(t.title || notKoku(t.note), 120)));
    const adim = stepText(t);
    if (adim) out.satirlar.push(satir('Adım', adim));
    const tier = (ses && ses.tier) || t.tier;
    if (tier) out.satirlar.push(satir('Katman', tier));
    if (t.status !== 'sirada') out.satirlar.push(satir('Süre', sureMetni(zamanMs(t.started || t.created, tz, ofset), ms)));
    out.satirlar.push(satir('Kullanım', harcamaMetni(t)));
    // only what /api/state knows: a running job may have no Kontrol or may have failed one already
    if (t.status === 'kontrolde') out.satirlar.push(satir('Kontrol', 'sunucu şu an çalıştırıyor'));
    else if (BITMIS.has(t.status)) out.satirlar.push(satir('Sonuç', SONUC_ADI[t.status]));
    // plan "Sonraki iş (9)" step 3: the memory of the job's specialisation (its note opens in Obsidian)
    const hm = t.uzmanlik ? hafizaMetni(st.hafiza, t.uzmanlik) : '';
    if (hm) out.satirlar.push(satir('Hafıza', hm));
  } else if (ses && ses.tier) out.satirlar.push(satir('Katman', ses.tier));
  const yard = yardimciMetni(ses && ses.alt_ajanlar);
  if (yard !== '—') out.satirlar.push(satir('Yardımcılar', yard));
  isAc(note);
  return out;
}
