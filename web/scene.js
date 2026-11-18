// Procedural isometric office ("living office"): one floor built from the behaviour engine's plan (web/ofis-davranis.js
// ofisPlani) — CEO room (glass), meeting room, external auditors, one open team area per project,
// tea corner, canteen and the lobby with the lift — and one character per actor (niyetler). No model files: primitives
// and a few canvas textures for text. The characters are "Pıtır", a rounded capsule robot with a visor; the title
// (unvan) adds an accessory, the model family tints the shell.
//
// API: new Office(host, labelHost, {light, onSelect(roomName|null), onActor(actor, {x, y})}) — any character click;
//      office.setActors(actors, plan) — diff by actor id: new ones come in through the lift (except on the first
//      render), a changed place is walked along the plan's graph, `cikis` walks to the lift and leaves;
//      office.select(roomName) — highlights and frames a team area ('<project>') or the CEO room ('__ceo__').
// Behaviour is never decided here: the scene only draws what the engine says. Label text goes through textContent.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { ODA_RENKLERI, projeRengi, ARGE_KITAPLIK_OLCU, ARGE_TAHTA_OLCU, GUVENLIK_UNVAN, KABIN_OLCU, MASA_OLCU, PATRON_MASA_OLCU, UNVAN, YAYA_EN_COK, dekorYerleri, dekorYuruyusu, otelOdasiMi, yayaKonumu,
  yayaRotalari, yayaSayisi } from './ofis-davranis.js';
import {
  YURUME_HIZI, aciFarki, denetciRenk, etiketBilgisi, etiketOnceligi, odaEtiketiGorunur, odaEtiketleri, etiketSecimi, etiketleriYerlestir, ortakOfsetler, oturmaYeri, planAnahtari, yolHazirla, yolKonumu,
  sonrakiZoom, yuruyusYolu, yuzAcisi, yatakAcisi, FARE_DUGMELERI, DOKUNMA, hedefiSinirla, kaydirmaAdimi, hedefFps,
  tekerlekTuru, pinchZoom, tekerZoom, imlecZoomHedefi, tekerKaydirma, kameraDerinligi, donusAcisi, sifirlamaAcisi,
} from './ofis-sahne.js';

export const ROOM_COLORS = ODA_RENKLERI; // a team's colour: projeRengi (ofis-davranis.js), shared with the page's chat dots
export const CEO_COLOR = '#F9D9C4';
const ACCENT = '#F2784B';
const BG = '#FBF4EA';
// the HUD drawn over the scene: the wheel / a pinch over it still moves the camera (never the page zoom)
const SAHNE_USTU = '.zoom-kontrol, .kaydir-ipucu, .demo-caption, .hud-sol';
const Y0 = 0.33; // floor top where characters stand
const CHAR = 1.7; // character scale (big, readable at the default zoom; furniture below is sized to match)
const DESK = MASA_OLCU; // desk scale x/y/z (the engine's furniture boxes use the same: walks go around them)
const BOSS = PATRON_MASA_OLCU; // the manager's and the CEO's desk
const CHAIR = [1.15, 1.3, 1.15];
const SIT = { masa: -0.08, 'mudur-masasi': -0.08, sandalye: -0.08, bekleme: -0.22, tabure: -0.08, resepsiyon: -0.08,
  kafe: -0.08, puf: -0.42, bank: -0.08 }; // seated
const scale3 = (o, v) => { o.scale.set(v[0], v[1], v[2]); return o; };
// every area its own soft floor colour (one warm palette); the base floor (corridors) is darker so rooms stand out
const ROOM_TINT = { toplanti: '#DCD2F0', ceo: '#F8D2BA', mudur: '#F3E1A6', denetci: '#C9E8DA', 'cay-ocagi': '#F4D29E',
  'ortak-alan': '#D3E2C4', yemekhane: '#F0C9B4', lobi: '#DDD8D0', uzmanlar: '#D2DDF2', oyun: '#E7D3EE',
  // the wing's facilities, the terrace and the (dim) rest room
  muhasebe: '#E8DDBF', idari: '#D6E3D2', ik: '#EBD5D2', wc: '#DCE5EA', sosyal: '#F2D7E6', revir: '#E3EEF0',
  spor: '#D9E8E0', dus: '#D6E1EE', psikolog: '#E9E1F2', masaj: '#F1E3D3', balkon: '#DDCCA9', dinlenme: '#CEC7DE',
  konferans: '#D5DCEB', sunucu: '#D3D8DF', arge: '#E2EBD6',
  // the company structure (plan "Sonraki iş (9)"): the managers' glass offices share one tint, the QA and Analist rooms
  mudurluk: '#EFE3C4', qa: '#D5E5EE', analist: '#E4DDF0' };
// the Sunucu odası's status lights (state.sistem.seviye): green / yellow / red, grey before the first sample
const SISTEM_ISIK = { yesil: '#35C76A', sari: '#F2C230', kirmizi: '#E5484D' };
const SISTEM_ISIK_YOK = '#8A94A3';
// an empty reserved team bay of the project wing: a pale floor with a dashed outline, no furniture
const BOS_EKIP = '#E6D9C6';
const BASE_FLOOR = '#D8C2A2';
// shell tint per model family (the title follows the model)
const SHELL = { haiku: '#E4F4E7', sonnet: '#DEEBFA', opus: '#ECE2FA', fable: '#FBE9C6', codex: '#C9E4DE' };
const CODEX_TRIM = '#3F7F76';
const SUS_TRIM = '#AEB3BD';
// the camera's offset from the floor's centre (azimuth 45 degrees): a little steeper than before, so the floor fills
// more of the (wide) scene area
// more of the (wide) scene area. Only its direction counts: the distance comes from kameraDerinligi (the floor's size)
const KAMERA = [40, 46, 40];
const KAMERA_YONU = new THREE.Vector3(...KAMERA).normalize();
// the default azimuth (OrbitControls' theta, atan2(x, z)): "Tümünü göster" turns the view back to it
const KAMERA_ACISI = Math.atan2(KAMERA[0], KAMERA[2]);
export const FIT_MARGIN_PX = 28; // the camera fit's clear margin on every side of the floor (px)

// --- shared materials and geometries (never per frame) ---
const mats = new Map();
function mat(color, opts = {}) {
  const key = color + JSON.stringify(opts);
  if (!mats.has(key)) mats.set(key, new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0, ...opts }));
  return mats.get(key);
}
const geos = new Map();
function geo(key, make) {
  let g = geos.get(key);
  if (!g) { g = make(); geos.set(key, g); }
  return g;
}
const rbox = (w, h, d, s = 2, r = 0.05) => geo(`rb:${w}:${h}:${d}:${s}:${r}`, () => new RoundedBoxGeometry(w, h, d, s, r));
const box = (w, h, d) => geo(`b:${w}:${h}:${d}`, () => new THREE.BoxGeometry(w, h, d));
const cyl = (rt, rb, h, seg = 12) => geo(`c:${rt}:${rb}:${h}:${seg}`, () => new THREE.CylinderGeometry(rt, rb, h, seg));
const sphere = (r, w = 10, hh = 8) => geo(`s:${r}:${w}:${hh}`, () => new THREE.SphereGeometry(r, w, hh));
function shade(hex, f) {
  const c = new THREE.Color(hex);
  const hsl = {}; c.getHSL(hsl);
  c.setHSL(hsl.h, Math.min(1, hsl.s * (f < 1 ? 1.05 : 0.9)), Math.max(0, Math.min(1, hsl.l * f)));
  return '#' + c.getHexString();
}
function mesh(g, material, { cast = true, receive = true } = {}) {
  const m = new THREE.Mesh(g, material);
  m.castShadow = cast; m.receiveShadow = receive;
  return m;
}

function canvasTexture(c) {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function glyphTexture(char, fg, bg) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  if (bg) { g.fillStyle = bg; g.beginPath(); g.arc(64, 64, 56, 0, Math.PI * 2); g.fill(); }
  g.fillStyle = fg;
  g.font = '700 84px Inter, system-ui, sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(char, 64, 70);
  return canvasTexture(c);
}
function glowTexture(rgb) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, `rgba(${rgb},0.95)`); grd.addColorStop(0.45, `rgba(${rgb},0.6)`); grd.addColorStop(1, `rgba(${rgb},0)`);
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  return canvasTexture(c);
}
let duman = null; // the smoke puff texture (the terrace), made on first need
let textures;
function getTextures() {
  if (!textures) {
    textures = {
      q: glyphTexture('?', '#FFFFFF', ACCENT),
      bang: glyphTexture('!', '#FFFFFF', '#E39A2D'),
      red: glyphTexture('!', '#FFFFFF', '#C9483F'),
      z: glyphTexture('z', '#7C86A2', null),
      ok: glyphTexture('✓', '#FFFFFF', '#4E9F76'),
      kaldi: glyphTexture('✗', '#FFFFFF', '#E0803A'),
      glow: glowTexture('160,220,255'),
      lamp: glowTexture('255,214,90'),
    };
  }
  return textures;
}
function sprite(tex, size, opacity = 1, additive = false) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, transparent: true, opacity, depthWrite: false,
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
  }));
  s.scale.set(size, size, 1);
  return s;
}
// One shared material per symbol: the test lamp blinks for everyone at once.
let simgeMats;
function getSimgeMats() {
  if (!simgeMats) {
    const t = getTextures();
    const m = (tex, additive = false) => new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false,
      blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending });
    simgeMats = { '?': m(t.q), '!': m(t.bang), '✓': m(t.ok), kirmizi: m(t.red), test: m(t.lamp, true),
      kaldi: m(t.kaldi) }; // the first Kontrol failure: a small orange "✗" (no red: nobody is stuck)
  }
  return simgeMats;
}

// A flat text plate: room names on the floor, the "Evde" sign. Fits the font to the width.
function textCanvas(text, w, h, { fg = '#6B5E50', bg = null, border = null, font = 600, size = 0.62 } = {}) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  if (bg) {
    g.fillStyle = bg;
    g.beginPath();
    g.roundRect ? g.roundRect(3, 3, w - 6, h - 6, 18) : g.rect(3, 3, w - 6, h - 6);
    g.fill();
    if (border) { g.strokeStyle = border; g.lineWidth = 4; g.stroke(); }
  }
  let px = Math.round(h * size);
  g.font = `${font} ${px}px Inter, system-ui, sans-serif`;
  while (px > 10 && g.measureText(text).width > w - 28) { px -= 2; g.font = `${font} ${px}px Inter, system-ui, sans-serif`; }
  g.fillStyle = fg; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, w / 2, h / 2 + 2);
  return c;
}

// --- the office's name (ofis.json ofis_adi, the Ayarlar tab; default "Ofis") on the lobby sign and the conference
// hall's idle screen: canvas textures drawn once (and again only when the name or the screen text changes); static and
// cheap, so they stay in hafif too. Text is drawn with fillText only (never HTML). ---
// The name centred on one line, the largest size (≤ px) that fits the width.
function adYaz(g, ad, w, h, pad, renk, px) {
  const metin = String(ad || '');
  if (!metin) return;
  g.fillStyle = renk; g.textAlign = 'center'; g.textBaseline = 'middle';
  let size = px;
  g.font = `700 ${size}px Inter, system-ui, sans-serif`;
  while (size > 16 && g.measureText(metin).width > w - 2 * pad) { size -= 4; g.font = `700 ${size}px Inter, system-ui, sans-serif`; }
  g.fillText(metin, w / 2, h / 2 + 2, w - 2 * pad);
}
// The lobby sign: the name in dark letters on a light plate.
function levhaCiz(c, ad) {
  const g = c.getContext('2d');
  g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = '#FFFFFF';
  g.beginPath();
  if (g.roundRect) g.roundRect(4, 4, c.width - 8, c.height - 8, 28); else g.rect(4, 4, c.width - 8, c.height - 8);
  g.fill();
  adYaz(g, ad, c.width, c.height, 48, '#0A0F1C', 132);
}
// The hall's screen: the announcement's first line (wrapped to at most three lines) on a dark screen, else the
// office's name in light letters.
function ekranCiz(c, metin, ad) {
  const g = c.getContext('2d');
  const w = c.width, h = c.height;
  g.fillStyle = '#16203A'; g.fillRect(0, 0, w, h);
  if (!metin) { adYaz(g, ad, w, h, 56, '#F5F7FA', 72); return; }
  g.fillStyle = '#22D3EE'; g.fillRect(0, 0, w, 10);
  g.fillStyle = '#9FB3D9'; g.font = '600 26px Inter, system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'top';
  g.fillText('DUYURU', w / 2, 24);
  g.fillStyle = '#F5F7FA'; g.font = '700 36px Inter, system-ui, sans-serif';
  const words = String(metin).split(/\s+/);
  const lines = [];
  let line = '';
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (g.measureText(next).width > w - 48 && line) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  const shown = lines.slice(0, 3);
  if (lines.length > 3) shown[2] = `${shown[2].replace(/.{0,2}$/, '')}…`;
  shown.forEach((l, i) => g.fillText(l, w / 2, 76 + i * 46, w - 40));
}

// --- furniture ---

function makeDesk(roomColor, big = false) {
  const g = new THREE.Group();
  const top = mesh(rbox(2.2, 0.12, 1.1, 2, 0.05), mat(big ? '#DDBB8E' : '#E9CFA9'));
  top.position.y = 0.95; g.add(top);
  for (const [x, z] of [[-1, -0.45], [1, -0.45], [-1, 0.45], [1, 0.45]]) {
    const leg = mesh(cyl(0.05, 0.05, 0.9, 8), mat('#C9A97F')); leg.position.set(x, 0.45, z); g.add(leg);
  }
  if (big) { // the manager's desk has a front panel
    const panel = mesh(rbox(2.1, 0.7, 0.06, 1, 0.02), mat('#D2AE80')); panel.position.set(0, 0.55, 0.5); g.add(panel);
  }
  // laptop: low enough to keep the character's face visible from the camera
  const lap = new THREE.Group();
  const base = mesh(rbox(0.8, 0.04, 0.55, 1, 0.02), mat('#D4D7DE'));
  base.position.y = 1.03; lap.add(base);
  const lid = new THREE.Group();
  lid.position.set(0, 1.05, 0.26);
  const shell = mesh(rbox(0.8, 0.52, 0.035, 1, 0.015), mat('#C3C7D0'));
  shell.position.y = 0.26; lid.add(shell);
  // the dark screen shares one material (merged with the static furniture: no draw call of its own); the lit screen is
  // its own mesh in front of it, drawn only while someone works there (frame) — plan "Sonraki iş (9)": the desks of the
  // new rooms cost no draw call while nobody sits there
  const screen = new THREE.Mesh(geo('screen', () => new THREE.PlaneGeometry(0.7, 0.42)), mat('#2B3242', { roughness: 0.4 }));
  screen.position.set(0, 0.26, -0.02); screen.rotation.y = Math.PI; lid.add(screen);
  const screenMat = new THREE.MeshStandardMaterial({ color: '#2B3242', emissive: '#7FD3FF', emissiveIntensity: 0.0, roughness: 0.4 });
  const lit = new THREE.Mesh(geo('screen', () => new THREE.PlaneGeometry(0.7, 0.42)), screenMat);
  lit.position.set(0, 0.26, -0.03); lit.rotation.y = Math.PI; lit.visible = false; lit.userData.dinamik = true; lid.add(lit);
  lid.rotation.x = 0.28;
  lap.add(lid);
  const glow = sprite(getTextures().glow, 1.6, 0, true);
  glow.visible = false; // lit only while someone works there (frame)
  glow.position.set(0, 1.35, -0.2); lap.add(glow);
  g.add(lap);
  const mug = mesh(cyl(0.09, 0.08, 0.18, 12), mat(shade(roomColor, 0.8)));
  mug.position.set(0.8, 1.1, 0.15); g.add(mug);
  return { group: g, screenMat, lit, glow, level: 0, target: 0 };
}

function makeChair(color = '#9AA3B5') {
  const g = new THREE.Group();
  const seatMat = mat(color);
  const seat = mesh(cyl(0.42, 0.42, 0.12, 20), seatMat);
  seat.position.y = 0.58; g.add(seat);
  const post = mesh(cyl(0.05, 0.05, 0.5, 8), mat('#6E7686'));
  post.position.y = 0.3; g.add(post);
  const foot = mesh(cyl(0.32, 0.36, 0.06, 16), mat('#6E7686'));
  foot.position.y = 0.04; g.add(foot);
  const back = mesh(rbox(0.8, 0.7, 0.12, 2, 0.05), seatMat);
  back.position.set(0, 1.05, -0.42); back.rotation.x = -0.12; g.add(back);
  return g;
}

function makeArmchair(color) {
  const g = new THREE.Group();
  const m = mat(color);
  const seat = mesh(rbox(1.0, 0.3, 0.9, 2, 0.1), m); seat.position.y = 0.42; g.add(seat);
  const back = mesh(rbox(1.0, 0.7, 0.2, 2, 0.08), m); back.position.set(0, 0.8, -0.38); g.add(back);
  for (const x of [-0.5, 0.5]) {
    const arm = mesh(rbox(0.16, 0.45, 0.85, 2, 0.06), mat(shade(color, 0.9))); arm.position.set(x, 0.6, 0); g.add(arm);
  }
  return g;
}

function makePlant() {
  const g = new THREE.Group();
  const pot = mesh(cyl(0.32, 0.24, 0.5, 16), mat('#E7A57F'));
  pot.position.y = 0.25; g.add(pot);
  const soil = mesh(cyl(0.29, 0.29, 0.04, 16), mat('#8B6B4E'));
  soil.position.y = 0.49; g.add(soil);
  const leaf = mat('#7DB98A');
  for (const [x, y, z, s] of [[0, 0.85, 0, 1.1], [0.2, 0.7, 0.12, 0.8], [-0.18, 0.72, -0.1, 0.85], [0.05, 1.1, -0.05, 0.7]]) {
    const l = mesh(sphere(0.28, 12, 10), leaf); l.position.set(x, y, z); l.scale.set(s, s * 1.25, s); g.add(l);
  }
  return g;
}

function makeShelf(color) {
  const g = new THREE.Group();
  const board = mat('#E9CFA9');
  for (const y of [1.0, 1.5]) {
    const b = mesh(rbox(0.35, 0.06, 1.4, 1, 0.02), board);
    b.position.set(0, y, 0); g.add(b);
  }
  const bookColors = [shade(color, 0.75), '#F2B880', '#A9C6E8', '#E8A9B8'];
  let z = -0.55;
  for (let i = 0; i < 6; i++) {
    const h = 0.28 + (i % 3) * 0.06;
    const book = mesh(box(0.22, h, 0.12), mat(bookColors[i % bookColors.length]));
    book.position.set(0, 1.03 + h / 2, z); z += 0.17; g.add(book);
  }
  return g;
}

// --- the wing's facilities, the terrace and the rest room (shared geometries and materials; built once) ---

// A shelf of binders (Muhasebe, İdari işler): coloured binder spines on two boards.
function makeBinderShelf(colors) {
  const g = new THREE.Group();
  const frame = mat('#D9C3A0');
  const side = mesh(rbox(0.4, 1.9, 1.9, 1, 0.03), frame); side.position.set(0, 0.95, 0); g.add(side);
  for (const y of [0.55, 1.25]) {
    for (let i = 0; i < 6; i++) {
      const b = mesh(box(0.3, 0.5, 0.18), mat(colors[i % colors.length]));
      b.position.set(0.12, y + 0.27, -0.72 + i * 0.27); g.add(b);
    }
  }
  return g;
}
// A small calculator on the accountant's desk.
function makeCalculator() {
  const g = new THREE.Group();
  const body = mesh(rbox(0.36, 0.06, 0.48, 1, 0.02), mat('#4A4F5A')); body.position.y = 0.03; g.add(body);
  const screen = mesh(box(0.28, 0.01, 0.1), mat('#BFE3C9', { emissive: '#7FBF94', emissiveIntensity: 0.3 })); screen.position.set(0, 0.07, -0.15); g.add(screen);
  const key = mat('#E7E3DC');
  for (let i = 0; i < 9; i++) { const k = mesh(box(0.07, 0.02, 0.07), key); k.position.set(-0.09 + (i % 3) * 0.09, 0.07, -0.02 + Math.floor(i / 3) * 0.09); g.add(k); }
  return g;
}
// A bed of the Dinlenme odası: frame, mattress, pillow, a folded blanket (along z, its head at the back).
function makeBed() {
  const g = new THREE.Group();
  const frame = mesh(rbox(1.3, 0.35, 2.6, 2, 0.06), mat('#9C8A74')); frame.position.y = 0.18; g.add(frame);
  const mattress = mesh(rbox(1.18, 0.22, 2.45, 2, 0.08), mat('#F2EEF6')); mattress.position.y = 0.46; g.add(mattress);
  const pillow = mesh(rbox(0.8, 0.14, 0.42, 2, 0.06), mat('#FFFFFF')); pillow.position.set(0, 0.62, -0.95); g.add(pillow);
  const blanket = mesh(rbox(1.2, 0.08, 1.1, 2, 0.04), mat('#8E97C4')); blanket.position.set(0, 0.6, 0.55); g.add(blanket);
  return g;
}
// A wash basin on a small cabinet with a mirror (the WC's sink area).
function makeSink() {
  const g = new THREE.Group();
  const cab = mesh(rbox(0.9, 0.85, 0.55, 2, 0.04), mat('#E9E4DD')); cab.position.y = 0.43; g.add(cab);
  const bowl = mesh(cyl(0.3, 0.22, 0.12, 16), mat('#FFFFFF')); bowl.position.set(0, 0.92, 0); g.add(bowl);
  const tap = mesh(cyl(0.03, 0.03, 0.22, 8), mat('#B9C0C8', { metalness: 0.5, roughness: 0.3 })); tap.position.set(0, 1.05, -0.2); g.add(tap);
  const mirror = mesh(box(0.7, 0.8, 0.04), mat('#D7EAF2', { metalness: 0.2, roughness: 0.15 })); mirror.position.set(0, 1.6, -0.3); g.add(mirror);
  return g;
}
// The terrace: a standing ashtray and a slatted bench.
function makeAshtray() {
  const g = new THREE.Group();
  const pole = mesh(cyl(0.05, 0.05, 0.9, 8), mat('#6E7178')); pole.position.y = 0.45; g.add(pole);
  const base = mesh(cyl(0.22, 0.25, 0.06, 14), mat('#5B5E66')); base.position.y = 0.03; g.add(base);
  const top = mesh(cyl(0.2, 0.16, 0.12, 14), mat('#8A8D94')); top.position.y = 0.95; g.add(top);
  return g;
}
function makeBench(len = 2.4) {
  const g = new THREE.Group();
  const wood = mat('#B48A5E');
  for (let i = 0; i < 3; i++) { const sl = mesh(box(len, 0.06, 0.14), wood); sl.position.set(0, 0.5, -0.18 + i * 0.18); g.add(sl); }
  const leg = mat('#5E5248');
  for (const x of [-len / 2 + 0.2, len / 2 - 0.2]) { const l = mesh(box(0.08, 0.5, 0.5), leg); l.position.set(x, 0.25, 0); g.add(l); }
  return g;
}

function makeTable(w, d, color = '#E9CFA9') {
  const g = new THREE.Group();
  const top = mesh(rbox(w, 0.1, d, 2, 0.04), mat(color)); top.position.y = 0.95; g.add(top);
  for (const sx of [-1, 1]) {
    const leg = mesh(box(0.1, 0.9, d * 0.7), mat('#C9A97F')); leg.position.set(sx * (w / 2 - 0.25), 0.45, 0); g.add(leg);
  }
  return g;
}

function makeKettleCorner() {
  const g = new THREE.Group();
  const counter = mesh(rbox(2.3, 0.95, 0.6, 2, 0.05), mat('#E8D2B4')); counter.position.y = 0.47; g.add(counter);
  const top = mesh(rbox(2.4, 0.06, 0.66, 1, 0.02), mat('#CDB08C')); top.position.y = 0.97; g.add(top);
  const kettle = new THREE.Group();
  const body = mesh(cyl(0.13, 0.16, 0.26, 16), mat('#D9DDE4', { metalness: 0.3, roughness: 0.4 })); body.position.y = 0.13; kettle.add(body);
  const lid = mesh(sphere(0.08, 10, 8), mat('#B7BCC6')); lid.position.y = 0.28; kettle.add(lid);
  const spout = mesh(cyl(0.02, 0.04, 0.16, 8), mat('#B7BCC6')); spout.position.set(0.17, 0.16, 0); spout.rotation.z = -0.9; kettle.add(spout);
  const handle = mesh(geo('kettle-handle', () => new THREE.TorusGeometry(0.09, 0.018, 6, 12, Math.PI)), mat('#8C6E52'));
  handle.position.set(-0.13, 0.18, 0); handle.rotation.z = Math.PI / 2; kettle.add(handle);
  kettle.position.set(-0.6, 1.0, 0); g.add(kettle);
  ['#F2B880', '#A9C6E8', '#E8A9B8'].forEach((c, i) => {
    const cup = mesh(cyl(0.07, 0.06, 0.12, 10), mat(c)); cup.position.set(0.1 + i * 0.25, 1.06, 0.05); g.add(cup);
  });
  const jar = mesh(cyl(0.1, 0.1, 0.22, 12), mat('#C98E5B')); jar.position.set(0.85, 1.11, -0.1); g.add(jar);
  // a small samovar with its teapot on top
  const brass = mat('#D6A85A', { metalness: 0.45, roughness: 0.35 });
  const sam = new THREE.Group();
  const foot = mesh(cyl(0.12, 0.15, 0.06, 14), brass); foot.position.y = 0.03; sam.add(foot);
  const urn = mesh(cyl(0.17, 0.14, 0.36, 16), brass); urn.position.y = 0.24; sam.add(urn);
  const neck = mesh(cyl(0.07, 0.1, 0.08, 12), brass); neck.position.y = 0.46; sam.add(neck);
  const pot = mesh(sphere(0.1, 12, 10), mat('#F4F1EC')); pot.position.y = 0.56; sam.add(pot);
  const tap = mesh(cyl(0.015, 0.015, 0.12, 6), brass); tap.position.set(0, 0.16, 0.17); tap.rotation.x = Math.PI / 2; sam.add(tap);
  sam.position.set(-1.0, 1.0, -0.05); g.add(sam);
  return g;
}

// a tea-corner stool (no back: robots sit facing their round table)
function makeStool() {
  const g = new THREE.Group();
  const seat = mesh(cyl(0.34, 0.32, 0.1, 18), mat('#C9A97F')); seat.position.y = 0.58; g.add(seat);
  const post = mesh(cyl(0.05, 0.05, 0.5, 8), mat('#8C6E52')); post.position.y = 0.3; g.add(post);
  const foot = mesh(cyl(0.24, 0.28, 0.05, 14), mat('#8C6E52')); foot.position.y = 0.03; g.add(foot);
  return g;
}

// a small round tea table with two glasses
function makeRoundTable() {
  const g = new THREE.Group();
  const top = mesh(cyl(0.62, 0.62, 0.07, 24), mat('#E9CFA9')); top.position.y = 0.92; g.add(top);
  const post = mesh(cyl(0.07, 0.07, 0.86, 8), mat('#C9A97F')); post.position.y = 0.46; g.add(post);
  const foot = mesh(cyl(0.3, 0.34, 0.05, 16), mat('#C9A97F')); foot.position.y = 0.03; g.add(foot);
  for (const [x, z] of [[-0.2, 0.1], [0.22, -0.12]]) {
    const glass = mesh(cyl(0.06, 0.05, 0.13, 10), mat('#C7764A', { roughness: 0.3 })); glass.position.set(x, 1.02, z); g.add(glass);
  }
  return g;
}

// --- the Oyun odası and the bigger tea corner (static props, shared geometry; nothing here animates in hafif) ---

// a table-tennis table, long side along x: green top with white lines, a net across the middle
function makePingPongTable() {
  const g = new THREE.Group();
  const top = mesh(box(2.6, 0.06, 1.5), mat('#2F7D5B')); top.position.y = 0.93; g.add(top);
  const line = mesh(box(2.6, 0.005, 0.03), mat('#FFFFFF')); line.position.y = 0.965; g.add(line);
  const net = mesh(box(0.03, 0.16, 1.6), mat('#F4F1EC')); net.position.y = 1.04; g.add(net);
  for (const [x, z] of [[-1.15, -0.6], [1.15, -0.6], [-1.15, 0.6], [1.15, 0.6]]) {
    const leg = mesh(cyl(0.04, 0.04, 0.9, 6), mat('#5B6270')); leg.position.set(x, 0.45, z); g.add(leg);
  }
  return g;
}

// a billiards table: wooden frame, green felt, a few balls
function makeBilliardTable() {
  const g = new THREE.Group();
  const frame = mesh(rbox(2.5, 0.22, 1.45, 2, 0.06), mat('#7A4E2D')); frame.position.y = 0.86; g.add(frame);
  const felt = mesh(box(2.2, 0.03, 1.15), mat('#2E8B57')); felt.position.y = 0.98; g.add(felt);
  for (const [x, z] of [[-1.05, -0.55], [1.05, -0.55], [-1.05, 0.55], [1.05, 0.55]]) {
    const leg = mesh(cyl(0.09, 0.07, 0.76, 8), mat('#6A4226')); leg.position.set(x, 0.38, z); g.add(leg);
  }
  ['#F4F1EC', '#E0B43A', '#C6463B', '#3B5BA9', '#2B2B2B'].forEach((c, i) => {
    const b = mesh(sphere(0.055, 10, 8), mat(c)); b.position.set(-0.5 + i * 0.25, 1.05, (i % 2 ? 0.18 : -0.12)); g.add(b);
  });
  return g;
}

// a darts board on the wall (faces +z)
function makeDartBoard() {
  const g = new THREE.Group();
  const ring = (r, c, z) => { const m = mesh(cyl(r, r, 0.04, 20), mat(c)); m.rotation.x = Math.PI / 2; m.position.z = z; g.add(m); };
  ring(0.36, '#2B2B2B', 0); ring(0.28, '#E8DCC0', 0.01); ring(0.18, '#C6463B', 0.02); ring(0.06, '#2E8B57', 0.03);
  return g;
}

// a bean bag (a squashed soft ball)
function makeBeanBag() {
  const g = new THREE.Group();
  const bag = mesh(sphere(0.62, 14, 10), mat('#E39B5B')); bag.scale.set(1.1, 0.55, 1.1); bag.position.y = 0.34; g.add(bag);
  const dent = mesh(sphere(0.4, 12, 8), mat('#D4884A')); dent.scale.set(1, 0.35, 1); dent.position.set(0, 0.62, 0.1); g.add(dent);
  return g;
}

// the tea corner's second counter: a coffee machine, a cup stack and a sugar jar
function makeCoffeeMachine() {
  const g = new THREE.Group();
  const counter = mesh(rbox(2.6, 0.95, 0.6, 2, 0.05), mat('#E8D2B4')); counter.position.y = 0.47; g.add(counter);
  const top = mesh(rbox(2.7, 0.06, 0.66, 1, 0.02), mat('#CDB08C')); top.position.y = 0.97; g.add(top);
  const body = mesh(rbox(0.6, 0.62, 0.45, 2, 0.05), mat('#3E434C')); body.position.set(-0.7, 1.31, -0.04); g.add(body);
  const spout = mesh(box(0.3, 0.06, 0.12), mat('#9AA3B5')); spout.position.set(-0.7, 1.16, 0.2); g.add(spout);
  const light = mesh(sphere(0.03, 6, 6), mat('#7DD3A0', { emissive: '#7DD3A0', emissiveIntensity: 0.8 }));
  light.position.set(-0.55, 1.5, 0.19); g.add(light);
  for (let i = 0; i < 4; i++) {
    const cup = mesh(cyl(0.07, 0.06, 0.1, 10), mat(['#F2B880', '#A9C6E8', '#E8A9B8', '#F4F1EC'][i]));
    cup.position.set(0.1 + (i % 2) * 0.2, 1.05 + Math.floor(i / 2) * 0.1, 0.05); g.add(cup);
  }
  const jar = mesh(cyl(0.1, 0.1, 0.2, 12), mat('#F4F1EC')); jar.position.set(0.8, 1.1, -0.05); g.add(jar);
  return g;
}

// the secretary's reception counter (in front of her chair) with a little lamp
function makeReception() {
  const g = new THREE.Group();
  const body = mesh(rbox(2.2, 1.0, 0.55, 2, 0.06), mat('#D9C2A0')); body.position.set(0, 0.5, 0.85); g.add(body);
  const top = mesh(rbox(2.3, 0.06, 0.7, 1, 0.02), mat('#B98A5A')); top.position.set(0, 1.03, 0.8); g.add(top);
  const lamp = mesh(cyl(0.05, 0.12, 0.1, 10), mat('#4E9F76')); lamp.position.set(0.75, 1.11, 0.75); g.add(lamp);
  const book = mesh(box(0.4, 0.04, 0.3), mat('#FFFFFF')); book.position.set(-0.4, 1.08, 0.8); g.add(book);
  const chair = makeChair('#8C95A8'); g.add(chair);
  return g;
}

// --- character ---

const ARM_Y = -0.08;
const ARM_Z = 0.36;

function makeCharacter(color, isCeo, { shell = '#FFF8F0', unvan = '', tur = 'ajan' } = {}) {
  const root = new THREE.Group();
  const body = new THREE.Group();
  root.add(body);
  const shellMat = mat(shell);
  const trimMat = mat(shade(color, 0.72));
  const torso = mesh(geo('torso', () => new THREE.CapsuleGeometry(0.36, 0.34, 6, 16)), shellMat);
  body.add(torso);
  const belt = mesh(cyl(0.37, 0.37, 0.12, 20), trimMat);
  belt.position.y = -0.12; body.add(belt);
  const visor = mesh(rbox(0.5, 0.26, 0.12, 2, 0.06), mat('#2E3445', { roughness: 0.35 }));
  visor.position.set(0, 0.22, 0.31); body.add(visor);
  const eyeMat = new THREE.MeshStandardMaterial({ color: '#BFF3E0', emissive: '#7FF0C8', emissiveIntensity: 0.9 });
  // both eyes in one mesh (they always blink together): one draw call
  const eyeGeo = geo('eyes', () => birlestir([new THREE.Matrix4().makeTranslation(-0.11, 0, 0), sphere(0.045, 10, 8),
    new THREE.Matrix4().makeTranslation(0.11, 0, 0), sphere(0.045, 10, 8)]));
  const e = new THREE.Mesh(eyeGeo, eyeMat);
  e.position.set(0, 0.22, 0.38); e.scale.set(1, 1.3, 0.5); body.add(e);
  const eyes = [e];
  for (const x of [-0.24, 0.24]) {
    const cheek = new THREE.Mesh(geo('cheek', () => new THREE.CircleGeometry(0.04, 12)), mat('#F6A7A0'));
    cheek.position.set(x, 0.1, 0.345); cheek.rotation.y = x > 0 ? 0.55 : -0.55; body.add(cheek);
  }
  const stalk = mesh(cyl(0.018, 0.018, 0.22, 6), trimMat);
  stalk.position.y = 0.62; body.add(stalk);
  const bulbMat = new THREE.MeshStandardMaterial({ color: ACCENT, emissive: ACCENT, emissiveIntensity: 0.2 });
  const bulb = mesh(sphere(0.06, 12, 10), bulbMat);
  bulb.position.y = 0.76; body.add(bulb);
  // the arms: an empty group each (it moves in pose and holds the things in hand); the sphere itself is drawn for all
  // robots as ONE InstancedMesh in the trim colour (Office.bacaklariCiz, like the legs)
  const arms = [];
  for (const x of [-0.3, 0.3]) {
    const a = new THREE.Group();
    a.position.set(x, ARM_Y, ARM_Z); body.add(a); arms.push(a);
  }
  // little legs: hidden while seated (the chair is there), they swing while walking. Each hip keeps an empty marker
  // where the leg is; the legs of all robots are drawn as ONE InstancedMesh in the trim colour (Office.bacaklariCiz)
  const legs = [];
  for (const x of [-0.14, 0.14]) {
    const hip = new THREE.Group();
    hip.position.set(x, 0.58, 0);
    const leg = new THREE.Object3D();
    leg.position.y = -0.27; hip.add(leg);
    hip.userData.bacak = leg;
    root.add(hip); legs.push(hip);
  }

  // title accessories
  const front = (m, x, y, z) => { m.position.set(x, y, z); body.add(m); return m; };
  const helper = tur === 'alt-ajan';
  if (unvan === UNVAN.haiku.unvan || helper) { // lanyard with a badge
    for (const s of [-1, 1]) {
      const cord = mesh(cyl(0.012, 0.012, 0.3, 4), mat('#4D7FC4'));
      cord.rotation.z = s * 0.5; front(cord, s * 0.08, 0.02, 0.36);
    }
    front(mesh(box(0.15, 0.19, 0.025), mat('#FFFFFF')), 0, -0.14, 0.375);
    front(mesh(box(0.15, 0.05, 0.03), mat('#4D7FC4')), 0, -0.07, 0.377);
  }
  if (unvan === UNVAN.sonnet.unvan) { // a round pin
    const pin = mesh(cyl(0.055, 0.055, 0.025, 14), mat('#E8B84A', { metalness: 0.4, roughness: 0.35 }));
    pin.rotation.x = Math.PI / 2; pin.rotation.z = 0.45; front(pin, -0.17, -0.02, 0.33);
  }
  if (unvan === UNVAN.opus.unvan) { // a tie
    front(mesh(box(0.08, 0.06, 0.04), mat('#9E3F35')), 0, 0.03, 0.365);
    const blade = mesh(geo('tie', () => new THREE.ConeGeometry(0.065, 0.28, 4)), mat('#B5523B'));
    blade.rotation.z = Math.PI; blade.rotation.y = Math.PI / 4; blade.scale.z = 0.35; front(blade, 0, -0.13, 0.36);
  }
  if (unvan === UNVAN.fable.unvan) { // a jacket open at the front, and glasses
    const jacket = mesh(geo('jacket', () => new THREE.CylinderGeometry(0.385, 0.39, 0.4, 22, 1, true, 0.75, Math.PI * 2 - 1.5)),
      mat('#3D4A66', { side: THREE.DoubleSide }));
    front(jacket, 0, -0.07, 0);
    for (const s of [-1, 1]) {
      const lapel = mesh(box(0.08, 0.3, 0.03), mat('#33405A'));
      lapel.rotation.z = s * -0.35; lapel.rotation.y = s * 0.7; front(lapel, s * 0.21, -0.02, 0.29);
    }
    const frame = mat('#F2D9A6', { metalness: 0.5, roughness: 0.3 });
    for (const x of [-0.11, 0.11]) front(mesh(geo('lens', () => new THREE.TorusGeometry(0.07, 0.014, 6, 16)), frame), x, 0.22, 0.39);
    const bridge = mesh(cyl(0.01, 0.01, 0.08, 4), frame); bridge.rotation.z = Math.PI / 2; front(bridge, 0, 0.23, 0.39);
  }
  if (isCeo) { // a small bow tie
    for (const s of [-1, 1]) {
      const wing = mesh(geo('bow', () => new THREE.ConeGeometry(0.07, 0.14, 4)), mat(ACCENT));
      wing.rotation.z = s * Math.PI / 2; front(wing, s * 0.07, 0.0, 0.37);
    }
  }
  if (tur === 'sus') { // apron
    const apron = mesh(geo('apron', () => new THREE.CylinderGeometry(0.375, 0.38, 0.46, 18, 1, true, -0.95, 1.9)),
      mat('#FFFFFF', { side: THREE.DoubleSide }));
    front(apron, 0, -0.16, 0);
    front(mesh(box(0.16, 0.08, 0.02), mat('#E3D9CC')), 0.0, -0.22, 0.385);
  }

  // things in hand, shown by pose
  const items = {};
  const cup = mesh(cyl(0.06, 0.05, 0.1, 10), mat('#F2B880'));
  cup.position.set(0, 0.07, 0.05); arms[1].add(cup); items.cup = cup;
  const fork = new THREE.Group();
  const handle = mesh(cyl(0.012, 0.012, 0.22, 4), mat('#C9CED8', { metalness: 0.5 })); fork.add(handle);
  const head = mesh(box(0.05, 0.06, 0.012), mat('#C9CED8', { metalness: 0.5 })); head.position.y = 0.13; fork.add(head);
  fork.position.set(0, 0.08, 0.04); fork.rotation.x = 0.5; arms[1].add(fork); items.fork = fork;
  const folder = mesh(box(0.06, 0.36, 0.3), mat('#F0C75E')); folder.position.set(0.4, -0.06, 0.08); body.add(folder);
  items.folder = folder;
  if (tur === 'sus') {
    const tray = new THREE.Group();
    tray.add(mesh(cyl(0.26, 0.24, 0.03, 18), mat('#C8CCD4', { metalness: 0.3 })));
    for (const x of [-0.1, 0.1]) { const c = mesh(cyl(0.05, 0.04, 0.09, 8), mat('#F2B880')); c.position.set(x, 0.06, 0); tray.add(c); }
    tray.position.set(0, -0.02, 0.55); body.add(tray); items.tray = tray;
  }
  if (unvan === UNVAN.codex.unvan || unvan === GUVENLIK_UNVAN) { // the auditor's clipboard
    const clip = new THREE.Group();
    clip.add(mesh(box(0.27, 0.35, 0.02), mat('#B98A5A')));
    const paper = mesh(box(0.22, 0.27, 0.005), mat('#FFFFFF')); paper.position.set(0, -0.02, 0.013); clip.add(paper);
    const top = mesh(box(0.1, 0.04, 0.03), mat('#8E9AAE', { metalness: 0.5 })); top.position.y = 0.16; clip.add(top);
    clip.position.set(0.05, 0.08, 0.1); clip.rotation.x = -0.5; arms[0].add(clip); items.clipboard = clip;
  }
  for (const k of ['cup', 'fork', 'folder']) items[k].visible = false;
  // the parts that never move on their own (shell, belt, visor, cheeks, accessories) in one mesh per material: fewer
  // draw calls per robot (performance); the eyes, the bulb, the arms and the things in hand stay separate
  // the staff's tray never moves on its own either: its parts join the merge
  govdeBirlestir(body, new Set([...eyes, bulb, ...arms, folder]), `${shell}|${color}|${unvan}|${tur}|${isCeo ? 1 : 0}`,
    items.tray ? [items.tray] : []);

  body.position.y = 1.08;
  const badge = new THREE.Sprite(getSimgeMats()['?']);
  badge.scale.set(0.6, 0.6, 1); badge.position.set(0, 2.3, 0); badge.visible = false; root.add(badge);
  return { root, body, eyes, arms, legs, legRenk: trimMat.color, bulbMat, eyeMat, badge, items, zs: null, baseY: 1.08 };
}
const bacakGeo = () => geo('leg', () => new THREE.CapsuleGeometry(0.075, 0.32, 4, 8));
const kolGeo = () => sphere(0.09, 10, 8);

// Merges [matrix, geometry, matrix, geometry, ...] into one indexed geometry (position and normal only: the shared
// materials have no texture), each copy moved by its matrix. `colors` (one THREE.Color per copy) adds a vertex colour
// attribute: each copy keeps its own material's colour under one vertex-coloured material.
function birlestir(list, colors = null) {
  let nv = 0, ni = 0;
  for (let i = 0; i < list.length; i += 2) {
    const g = list[i + 1];
    nv += g.attributes.position.count;
    ni += g.index ? g.index.count : g.attributes.position.count;
  }
  const pos = new Float32Array(nv * 3), nor = new Float32Array(nv * 3);
  const col = colors ? new Float32Array(nv * 3) : null;
  const idx = nv > 65535 ? new Uint32Array(ni) : new Uint16Array(ni);
  const v = new THREE.Vector3(), nm = new THREE.Matrix3();
  let ov = 0, oi = 0;
  for (let i = 0; i < list.length; i += 2) {
    const m = list[i], g = list[i + 1];
    nm.getNormalMatrix(m);
    const P = g.attributes.position, N = g.attributes.normal;
    const c = colors ? colors[i / 2] : null;
    for (let k = 0; k < P.count; k++) {
      v.fromBufferAttribute(P, k).applyMatrix4(m); pos.set([v.x, v.y, v.z], (ov + k) * 3);
      v.fromBufferAttribute(N, k).applyMatrix3(nm).normalize(); nor.set([v.x, v.y, v.z], (ov + k) * 3);
      if (c) col.set([c.r, c.g, c.b], (ov + k) * 3);
    }
    if (g.index) for (let k = 0; k < g.index.count; k++) idx[oi + k] = g.index.getX(k) + ov;
    else for (let k = 0; k < P.count; k++) idx[oi + k] = k + ov;
    oi += g.index ? g.index.count : P.count;
    ov += P.count;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  if (col) out.setAttribute('color', new THREE.BufferAttribute(col, 3));
  out.setIndex(new THREE.BufferAttribute(idx, 1));
  // frustum culling reads these: computed from the merged (moved) vertices, never a part's own
  out.computeBoundingBox();
  out.computeBoundingSphere();
  return out;
}

// One shared vertex-coloured material per surface kind (roughness, metalness, side): the robots' merged still parts.
const renkliMats = new Map();
const yuzeyAnahtari = (m) => `${m.roughness}|${m.metalness}|${m.side}`;
function renkliMat(m) {
  const k = yuzeyAnahtari(m);
  if (!renkliMats.has(k)) {
    renkliMats.set(k, new THREE.MeshStandardMaterial({ color: '#FFFFFF', vertexColors: true, roughness: m.roughness,
      metalness: m.metalness, side: m.side }));
  }
  return renkliMats.get(k);
}

// A robot body's still parts merged into one mesh per surface kind, each part keeping its own colour as a vertex colour
// (plan B5, the owner, 2026-11-12: about 13 draw calls per robot became about 7). The shared materials (mat) only: the
// eyes and the bulb have their own glowing materials and stay separate, like the arms, the things in hand and `keep`.
// Cached per look (the same robot type reuses its geometry). Colours are the materials' linear values, which is what
// three.js expects of vertex colours, so the merged parts look as before.
const govdeCache = new Map();
function govdeBirlestir(body, keep, key, duz = []) {
  for (const g of duz) { // a still group (the tray): its parts become the body's own, at the same place
    g.updateMatrix();
    for (const c of [...g.children]) {
      c.updateMatrix(); c.matrix.premultiply(g.matrix); c.matrix.decompose(c.position, c.quaternion, c.scale);
      g.remove(c); body.add(c);
    }
    body.remove(g);
  }
  const shared = new Set(mats.values());
  const parts = body.children.filter((o) => o.isMesh && !keep.has(o) && shared.has(o.material) && !o.material.map
    && o.material.emissive.getHex() === 0 && !o.material.transparent);
  const by = new Map();
  for (const o of parts) {
    o.updateMatrix();
    const k = yuzeyAnahtari(o.material);
    if (!by.has(k)) by.set(k, { list: [], colors: [], parts: [], m: o.material });
    const b = by.get(k);
    b.list.push(o.matrix.clone(), o.geometry); b.colors.push(o.material.color); b.parts.push(o);
  }
  for (const [k, b] of by) {
    if (b.parts.length < 2) continue; // a single part: nothing to gain
    const ck = `${key}#${k}`;
    let g = govdeCache.get(ck);
    if (!g) { g = birlestir(b.list, b.colors); govdeCache.set(ck, g); }
    for (const o of b.parts) body.remove(o);
    body.add(mesh(g, renkliMat(b.m)));
  }
}

// --- decorative people (owner decision 2026-11-13; ofis-davranis.js dekorYerleri / dekorEkibi) ---
// One merged, vertex-coloured robot body (lower detail, no cheeks or accessories, the eyes not glowing) shared by every
// decorative person through ONE InstancedMesh, tinted per room with instance colours; the standing ones' legs are a
// second InstancedMesh. Two draw calls for all of them, whatever their number; no shadows, no labels.
const DEKOR_BOY = CHAR * 0.94; // a touch smaller than a real character
const DEKOR_TON = { qa: '#CFE2F0', analist: '#E2D8F2' };
let dekorGeo = null;
function dekorGeometrileri() {
  if (dekorGeo) return dekorGeo;
  const T = (x, y, z) => new THREE.Matrix4().makeTranslation(x, y, z);
  const C = (hex) => new THREE.Color(hex);
  const by = 1.08; // the body's height in a character (makeCharacter)
  const eyes = T(0, by + 0.22, 0.37).multiply(new THREE.Matrix4().makeScale(1, 1.3, 0.5));
  const govde = birlestir([
    T(0, by, 0), new THREE.CapsuleGeometry(0.36, 0.34, 4, 10),
    T(0, by - 0.12, 0), new THREE.CylinderGeometry(0.37, 0.37, 0.12, 14),
    T(0, by + 0.22, 0.31), new THREE.BoxGeometry(0.5, 0.26, 0.12),
    eyes.clone().multiply(T(-0.11, 0, 0)), new THREE.SphereGeometry(0.045, 8, 6),
    eyes.clone().multiply(T(0.11, 0, 0)), new THREE.SphereGeometry(0.045, 8, 6),
    T(0, by + 0.62, 0), new THREE.CylinderGeometry(0.018, 0.018, 0.22, 5),
    T(0, by + 0.76, 0), new THREE.SphereGeometry(0.06, 8, 6),
    T(-0.3, by + ARM_Y, ARM_Z), new THREE.SphereGeometry(0.09, 8, 6),
    T(0.3, by + ARM_Y, ARM_Z), new THREE.SphereGeometry(0.09, 8, 6),
  ], [C('#FFFFFF'), C('#B9BFCB'), C('#2E3445'), C('#BFF3E0'), C('#BFF3E0'), C('#B9BFCB'), C('#F2B880'), C('#B9BFCB'),
    C('#B9BFCB')]);
  const bacak = birlestir([T(-0.14, 0.31, 0), new THREE.CapsuleGeometry(0.075, 0.32, 3, 6),
    T(0.14, 0.31, 0), new THREE.CapsuleGeometry(0.075, 0.32, 3, 6)], [C('#B9BFCB'), C('#B9BFCB')]);
  const malzeme = new THREE.MeshStandardMaterial({ color: '#FFFFFF', vertexColors: true, roughness: 0.6 });
  dekorGeo = { govde, bacak, malzeme };
  return dekorGeo;
}

// the street's pedestrians (Office.setYaya): a bit smaller than the decorative people, a coat colour each; one leg
// (its hip at the origin) for the legs' InstancedMesh
const YAYA_BOY = CHAR * 0.8;
const YAYA_RENK = ['#F2C6A0', '#BFD7EA', '#D8C8E8', '#CDE5C4', '#F3D9A4', '#E8C1C8', '#C9D3DA', '#E2D3BF', '#B9D9D2', '#EAD0B0'];
let yayaBacakGeo = null;
function yayaBacagi() {
  if (!yayaBacakGeo) yayaBacakGeo = birlestir([new THREE.Matrix4().makeTranslation(0, -0.24, 0), new THREE.CapsuleGeometry(0.075, 0.32, 3, 6)],
    [new THREE.Color('#B9BFCB')]);
  return yayaBacakGeo;
}

// --- the office ---

export class Office {
  constructor(host, labelHost, { light = false, onSelect = () => {}, onActor = () => {} } = {}) {
    this.host = host;
    this.labelHost = labelHost;
    this.light = light;
    this.onSelect = onSelect;
    this.onActor = onActor;
    this.actors = new Map(); // id -> visual
    this.list = []; // the same visuals as an array (the frame loop iterates without allocating)
    this.desks = new Map(); // desk node id -> desk
    this.deskList = [];
    this.floors = new Map(); // room name ('<project>' | '__ceo__') -> {floor, centre}
    this.planKey = '';
    this.plan = null;
    this.seeded = false;
    this.selected = null;
    this.disposables = [];
    this.ofisAdi = 'Ofis'; // the name on the lobby sign and the hall's idle screen (setOfisAdi)
    this.clock = new THREE.Clock();
    this.focusAnim = null;
    this.wk = { x: 0, z: 0, aci: 0, bitti: false, sonraki: null };

    // performance (owner decision 2026-11-12, the fan): the pixel ratio stays at most 1.5 and a Retina screen above that gets no
    // MSAA (its pixels already smooth the edges); the shadow map is drawn only when something moved (frame)
    const dpr = Number(window.devicePixelRatio) || 1;
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: !light && dpr <= 1.5, powerPreference: light ? 'low-power' : 'default' });
    r.setPixelRatio(light ? 1 : Math.min(dpr, 1.5));
    r.shadowMap.enabled = !light;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.shadowMap.autoUpdate = false;
    this.golgeZamani = -Infinity;
    host.appendChild(r.domElement);

    const scene = this.scene = new THREE.Scene();
    scene.background = new THREE.Color(BG);
    // near / far and the camera's distance follow the floor's size (kameraDerinligi, set in buildPlan)
    this.derinlik = kameraDerinligi(null);
    this.camera = new THREE.OrthographicCamera(-10, 10, 10, -10, this.derinlik.near, this.derinlik.far);
    this.camera.position.copy(KAMERA_YONU).multiplyScalar(this.derinlik.uzaklik);
    this.kure = new THREE.Spherical(); // the ↺ / ↻ turn (frame), no allocation per frame
    this.ofset = new THREE.Vector3();
    this.camera.zoom = 1;

    scene.add(new THREE.HemisphereLight('#FFF6EC', '#E3CDB4', 1.6));
    const sun = this.sun = new THREE.DirectionalLight('#FFFFFF', 1.9);
    sun.position.set(14, 26, 8);
    sun.castShadow = !light;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0008;
    sun.shadow.normalBias = 0.02;
    scene.add(sun, sun.target);

    this.world = new THREE.Group();
    scene.add(this.world);

    const c = this.controls = new OrbitControls(this.camera, r.domElement);
    c.enableDamping = true;
    c.dampingFactor = 0.08;
    c.minPolarAngle = 0.55;
    c.maxPolarAngle = 1.12;
    // a full turn around the view centre (owner decision 2026-11-13); the tilt limits keep the camera above the floor
    c.minAzimuthAngle = -Infinity;
    c.maxAzimuthAngle = Infinity;
    c.minZoom = 0.6;
    c.maxZoom = 3.2;
    // the wheel, the trackpad pinch and Safari's gesture events are ours (tekerlek below): OrbitControls' own zoom is
    // switched on only while touch pointers (phone pinch) or the middle button are down — its wheel zoom never runs
    c.enableZoom = false;
    c.rotateSpeed = 0.6;
    // like a map: left drag / one finger pans across the floor plane (screenSpacePanning off), right drag (or
    // Shift/Ctrl/Meta/Alt + left drag, two-finger twist) rotates within the limits above, wheel / pinch zooms
    c.screenSpacePanning = false;
    c.panSpeed = 1;
    c.mouseButtons = { LEFT: THREE.MOUSE[FARE_DUGMELERI.LEFT], MIDDLE: THREE.MOUSE[FARE_DUGMELERI.MIDDLE],
      RIGHT: THREE.MOUSE[FARE_DUGMELERI.RIGHT] };
    c.touches = { ONE: THREE.TOUCH[DOKUNMA.ONE], TWO: THREE.TOUCH[DOKUNMA.TWO] };
    c.addEventListener('change', () => { this.clampTarget(); this.kameraZamani = performance.now(); });
    // Alt + left drag rotates as well (OrbitControls itself swaps only for Shift/Ctrl/Meta): switched on the host's
    // capture phase, before OrbitControls sees the press (labels forward their presses to the canvas, so they pass
    // here too), and back on release
    const dokunmalar = new Set();
    host.addEventListener('pointerdown', (e) => {
      c.mouseButtons.LEFT = THREE.MOUSE[e.altKey && e.button === 0 ? 'ROTATE' : FARE_DUGMELERI.LEFT];
      // touch pinch and the middle-button drag keep OrbitControls' dolly (its wheel zoom stays off: the wheel is ours)
      if (e.pointerType === 'touch' || e.button === 1) { dokunmalar.add(e.pointerId); c.enableZoom = true; }
    }, { capture: true });
    const dokunmaBitti = (e) => {
      if (!dokunmalar.delete(e.pointerId)) return;
      if (!dokunmalar.size) c.enableZoom = false;
    };
    window.addEventListener('pointerup', dokunmaBitti, { capture: true });
    window.addEventListener('pointercancel', dokunmaBitti, { capture: true });
    // the cursor: an open hand over the floor (CSS), a closed one while dragging; the hover's pointer comes back after
    c.addEventListener('start', () => { r.domElement.style.cursor = 'grabbing'; this.surukleniyor = true; this.kameraZamani = performance.now(); });
    c.addEventListener('end', () => { r.domElement.style.cursor = ''; this.surukleniyor = false; this.kameraZamani = performance.now(); });

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    let down = null;
    r.domElement.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; this.focusAnim = null; });
    // until the viewer moves or zooms the camera, a resized window is framed again (the floor stays whole)
    this.userMoved = false;
    // only a real drag (>= 5 px, the same threshold as a click in pick) or a wheel zoom counts; a plain click or tap
    // fires OrbitControls' 'start' too and must not stop the re-fit
    r.domElement.addEventListener('pointerup', (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) >= 5) this.userMoved = true;
    });
    // The wheel over the whole scene area (canvas, labels, the HUD over the scene, the gaps between them): never the
    // browser's page zoom or scroll. A trackpad pinch (wheel + ctrlKey) zooms smoothly towards the pointer, a
    // two-finger scroll pans the floor, a mouse wheel notch zooms one step towards the pointer (tekerlekTuru). Captured
    // on the stage before OrbitControls; the side panel, overlays, cards and dialogs keep the browser default.
    this.olayAlani = host.parentElement || host;
    this.jest = null; // Safari pinch: {z0} between gesturestart and gestureend
    this.olayAlani.addEventListener('wheel', (e) => {
      if (!this.sahneOlayi(e)) return;
      e.preventDefault();
      e.stopPropagation();
      this.tekerlek(e);
    }, { passive: false, capture: true });
    // Safari (WebKit) pinches with gesture events: the page zoom is prevented and the scale drives the camera zoom
    for (const tur of ['gesturestart', 'gesturechange', 'gestureend']) {
      this.olayAlani.addEventListener(tur, (e) => {
        if (!this.sahneOlayi(e)) return;
        e.preventDefault();
        this.jestOlayi(tur, e);
      }, { passive: false, capture: true });
    }
    // hovering a character (or its label) shows its full label; throttled raycast
    this.hoverId = null;
    this.yakin = false;
    let lastMove = 0;
    r.domElement.addEventListener('pointermove', (e) => {
      if (e.buttons || e.timeStamp - lastMove < 120) return;
      lastMove = e.timeStamp;
      const v = this.actorAt(e);
      this.setHover(v ? v.id : null);
    });
    r.domElement.addEventListener('pointerleave', () => this.setHover(null));
    r.domElement.addEventListener('pointerup', (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) {
        // a press that began on a label (forwarded below) is a click on that label's character
        const cur = this.labelDown && this.actors.get(this.labelDown);
        if (this.labelDown) {
          // the browser's click lands on the label's and canvas's common ancestor: swallow it once so the page's
          // "click outside" handlers do not undo what this click opened
          const swallow = (ev) => ev.stopPropagation();
          window.addEventListener('click', swallow, { capture: true, once: true });
          setTimeout(() => window.removeEventListener('click', swallow, { capture: true }), 300);
          if (cur) this.onActor(cur.a, { x: e.clientX, y: e.clientY }); // every character opens its info card
        }
        else this.pick(e);
      }
      down = null;
      this.labelDown = null;
    });

    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    this.tmp = new THREE.Vector3();
    // The frame cap (hedefFps): about 60 fps only while the camera moves, about 30 while someone walks (or the ball
    // flies), about 9 at rest; a change of the actors (setActors) draws the next frame at once. Nothing while the tab
    // is hidden, a tab panel covers the scene or the Komuta masası is open.
    this.kameraZamani = -Infinity;
    this.yuruyenVar = false;
    this.kirli = true;
    let son = -Infinity;
    const loop = (now) => {
      this.raf = requestAnimationFrame(loop);
      if (document.hidden || this.paused || this.labelsHidden) return;
      const t = Number.isFinite(now) ? now : performance.now();
      const kamera = !!this.focusAnim || !!this.surukleniyor || t - this.kameraZamani < 400;
      const fps = hedefFps({ kamera, yuruyen: this.yuruyenVar, top: !!(this.top && this.top.on) });
      if (!this.kirli && t - son < 1000 / fps - 2) return;
      son = t;
      this.kirli = false;
      this.frame();
    };
    loop();
  }

  // Width (px) covered by the right-hand side panel; the scene is centred in the area left of it.
  // A collapsed panel (html.yan-bos: --side-w 0, owner decision 2026-11-13) covers nothing: the full width.
  rightInset(w) {
    if (window.innerWidth < 1000) return 0;
    const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--side-w'));
    const side = Number.isFinite(v) ? v : 360;
    return side > 0 ? Math.min(w * 0.5, side + 48) : 0;
  }

  resize() {
    const w = this.host.clientWidth || 1, h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    const view = this.viewSize || 26;
    const ppu = h / view;
    this.inset = this.rightInset(w);
    const visible = w - this.inset;
    this.visHalfW = visible / 2 / ppu;
    // a symmetric frustum, shifted by half the side panel in pixels: the view centre stays in the middle of the visible
    // area at every zoom (world-unit offsets would scale with the zoom and slide a zoomed-in view out of sight)
    Object.assign(this.camera, { left: -w / 2 / ppu, right: w / 2 / ppu, top: view / 2, bottom: -view / 2 });
    this.camera.setViewOffset(w, h, this.inset / 2, 0, w, h);
    this.camera.updateProjectionMatrix();
    if (this.bounds && !this.userMoved && !this.selected && !this.fitting) {
      this.fitting = true;
      this.fit();
      this.fitting = false;
    }
  }

  // Frames the whole floor in the visible area (the office only: the Otel outside it may stay partly off-screen,
  // reachable by panning — this.bounds, the pan bounds, include it).
  fit() {
    const b = this.cerceve || this.bounds;
    if (!b) return;
    const c = new THREE.Vector3((b.minX + b.maxX) / 2, 0.8, (b.minZ + b.maxZ) / 2);
    this.center = c;
    this.controls.target.copy(c);
    // the default view angle (also a reset of ↺ / ↻ and of a drag-turn), at the floor's camera distance
    this.camera.position.copy(KAMERA_YONU).multiplyScalar(this.derinlik.uzaklik).add(c);
    this.camera.lookAt(c);
    this.camera.updateMatrixWorld();
    let hx = 0, hy = 0;
    const v = new THREE.Vector3();
    const pts = [];
    for (const x of [b.minX, b.maxX]) for (const z of [b.minZ, b.maxZ]) for (const y of [-0.6, 2.2]) pts.push([x, y, z]);
    for (const [x, y, z] of pts) {
      v.set(x, y, z).applyMatrix4(this.camera.matrixWorldInverse);
      hx = Math.max(hx, Math.abs(v.x));
      hy = Math.max(hy, Math.abs(v.y));
    }
    const view = this.viewSize || 26;
    // a clear margin in pixels (FIT_MARGIN_PX) on every side: the floor's corners (the lounge's left tip, the wing's
    // right tip) never touch the screen edge or the side panel, whatever the floor's width
    const h = this.host.clientHeight || 1;
    const ppu = h / view;
    const mx = FIT_MARGIN_PX / ppu, my = FIT_MARGIN_PX / ppu;
    const zoom = Math.min(Math.max(0.1, this.visHalfW - mx) / hx, Math.max(0.1, view / 2 - my) / hy);
    this.fitZoom = Math.max(0.25, Math.min(zoom, 2.4));
    this.controls.minZoom = this.fitZoom * 0.6;
    this.controls.maxZoom = Math.max(3.2, this.fitZoom * 4);
    this.camera.zoom = this.fitZoom;
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  // The zoom buttons / keys: one smooth step in (yon > 0) or out (yon < 0) towards the current view centre, clamped to
  // the controls' min/max zoom. Counts as the viewer moving the camera (no re-fit on resize) until tumunuGoster().
  yakinlastir(yon) {
    const z1 = sonrakiZoom(this.focusAnim ? this.focusAnim.z1 : this.camera.zoom, yon, this.controls.minZoom, this.controls.maxZoom);
    this.userMoved = true;
    const t = this.controls.target.clone();
    this.focusAnim = { from: t, to: t.clone(), z0: this.camera.zoom, z1, t: 0, ...this.kalanDonus() };
  }

  // A ↺ / ↻ turn still under way when a zoom or a pan step starts: the new animation finishes it (from where the
  // camera is now), so a quick + after ↻ never leaves the view at half a step.
  kalanDonus() {
    const f = this.focusAnim;
    if (!f || !Number.isFinite(f.aci1)) return {};
    return { aci0: this.controls.getAzimuthalAngle(), aci1: f.aci1 };
  }

  // The ↺ / ↻ buttons and the Q / E keys: one smooth 45-degree turn (donusAcisi) around the current view centre; the
  // target, the zoom and the tilt stay, so hedefiSinirla, the labels and the side-panel offset are untouched. A press
  // during a turn adds a step to where that turn was going. Counts as the viewer moving the camera (frame cap and no
  // re-fit on resize) until tumunuGoster(), which turns back to the default angle.
  dondur(yon) {
    const f = this.focusAnim;
    const aci0 = this.controls.getAzimuthalAngle();
    const aci1 = donusAcisi(f && Number.isFinite(f.aci1) ? f.aci1 : aci0, yon);
    const t = this.controls.target.clone();
    this.userMoved = true;
    this.kameraZamani = performance.now();
    this.kirli = true;
    this.focusAnim = { from: t, to: t.clone(), z0: this.camera.zoom, z1: f ? f.z1 : this.camera.zoom, t: 0, aci0, aci1 };
  }

  // Whether a wheel / gesture event belongs to the scene (its own wheel handling, no page zoom): over the canvas, the
  // labels, the stage itself (gaps) or the HUD drawn over the scene — never the side panel, an overlay, a card, a dialog.
  sahneOlayi(e) {
    const t = e.target;
    if (!t || t === this.olayAlani) return true;
    if (t.nodeType !== 1 || !this.olayAlani.contains(t)) return false;
    if (this.host.contains(t) || this.labelHost.contains(t)) return true;
    return !!t.closest(SAHNE_USTU);
  }

  // The floor point (y = 0.8, the target's height) under a client pixel, or null.
  zeminNoktasi(cx, cy) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    this.pointer.set(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const o = this.raycaster.ray.origin, d = this.raycaster.ray.direction;
    if (Math.abs(d.y) < 1e-6) return null;
    const s = (0.8 - o.y) / d.y;
    return { x: o.x + d.x * s, z: o.z + d.z * s };
  }

  // Zooms to z1 at once, keeping the floor point under (cx, cy) where it is (imlecZoomHedefi); without a pointer the
  // view centre stays. Counts as the viewer moving the camera.
  imleceZoom(z1, cx, cy) {
    const cam = this.camera, c = this.controls;
    const z = Math.min(c.maxZoom, Math.max(c.minZoom, z1));
    this.focusAnim = null;
    this.userMoved = true;
    const p = Number.isFinite(cx) && Number.isFinite(cy) ? this.zeminNoktasi(cx, cy) : null;
    if (p) {
      const t = c.target;
      const k = imlecZoomHedefi(t.x, t.z, p.x, p.z, cam.zoom, z);
      cam.position.x += k.x - t.x;
      cam.position.z += k.z - t.z;
      t.x = k.x; t.z = k.z;
    }
    cam.zoom = z;
    cam.updateProjectionMatrix();
    this.clampTarget();
    c.update();
  }

  // One wheel event over the scene (see the listener in the constructor).
  tekerlek(e) {
    const tur = tekerlekTuru(e);
    if (!tur) return;
    const c = this.controls;
    if (tur === 'pinch') {
      if (this.jest) return; // Safari also pinching with gesture events: one source only
      this.imleceZoom(pinchZoom(this.camera.zoom, e.deltaY, c.minZoom, c.maxZoom), e.clientX, e.clientY);
    } else if (tur === 'yakinlastir') {
      this.imleceZoom(tekerZoom(this.camera.zoom, e.deltaY, c.minZoom, c.maxZoom), e.clientX, e.clientY);
    } else {
      const cam = this.camera;
      const h = this.renderer.domElement.clientHeight || this.host.clientHeight || 1;
      const birim = (cam.top - cam.bottom) / cam.zoom / h;
      const [sag, ileri] = tekerKaydirma(e.deltaX, e.deltaY, birim);
      const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).setY(0);
      const fwd = new THREE.Vector3();
      cam.getWorldDirection(fwd).setY(0);
      if (right.lengthSq() < 1e-6 || fwd.lengthSq() < 1e-6) return;
      right.normalize(); fwd.normalize();
      const d = right.multiplyScalar(sag).addScaledVector(fwd, ileri);
      this.focusAnim = null;
      this.userMoved = true;
      c.target.add(d);
      cam.position.add(d);
      this.clampTarget();
      c.update();
    }
  }

  // Safari's pinch: the gesture's scale relative to its start drives the zoom (towards the pointer).
  jestOlayi(tur, e) {
    if (tur === 'gesturestart') { this.jest = { z0: this.camera.zoom }; return; }
    if (!this.jest) return;
    const s = Number(e.scale);
    if (s > 0) this.imleceZoom(this.jest.z0 * s, e.clientX, e.clientY);
    if (tur === 'gestureend') this.jest = null;
  }

  // "Tümünü göster": the whole office again, and the re-fit on resize is back on.
  tumunuGoster() {
    this.focusAnim = null;
    this.userMoved = false;
    if (this.selected) { this.select(null, false); this.onSelect(null); }
    const aci = this.controls.getAzimuthalAngle();
    this.fit(); // also the default view angle and tilt (KAMERA_YONU)
    // then a short turn back from the angle the viewer had (the shortest way, sifirlamaAcisi) instead of a jump
    if (Number.isFinite(aci) && Math.abs(aci - KAMERA_ACISI) > 1e-3) {
      const t = this.controls.target.clone();
      this.focusAnim = { from: t, to: t.clone(), z0: this.camera.zoom, z1: this.camera.zoom, t: 0,
        aci0: aci, aci1: sifirlamaAcisi(aci, KAMERA_ACISI), sifirla: true };
    }
  }

  // Keyboard pan (arrows / WASD): one smooth step across the floor in screen directions (sag: right +, ileri: up +),
  // the camera moving with its target (the view angle stays). Counts as the viewer moving the camera.
  kaydir(sag, ileri) {
    const cam = this.camera;
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0).setY(0);
    const fwd = new THREE.Vector3();
    cam.getWorldDirection(fwd).setY(0);
    if (right.lengthSq() < 1e-6 || fwd.lengthSq() < 1e-6) return;
    right.normalize(); fwd.normalize();
    const step = kaydirmaAdimi(this.visHalfW, cam.zoom);
    const f = this.focusAnim;
    const from = this.controls.target.clone();
    const base = f && f.tasi ? f.to.clone() : from.clone();
    const to = base.addScaledVector(right, sag * step).addScaledVector(fwd, ileri * step);
    const k = hedefiSinirla(to.x, to.z, this.bounds);
    to.set(k.x, 0.8, k.z);
    this.userMoved = true;
    this.focusAnim = { from, to, z0: cam.zoom, z1: f ? f.z1 : cam.zoom, t: 0, tasi: true, ...this.kalanDonus() };
  }

  // The view centre stays over the floor: clamped to the floor's real bounds (common area and project wing, plus the
  // slab's lip and a small margin; hedefiSinirla), the camera moving by the same amount so the view angle never
  // changes at the edge.
  clampTarget() {
    const t = this.controls.target;
    const k = hedefiSinirla(t.x, t.z, this.bounds);
    const dx = k.x - t.x, dy = 0.8 - t.y, dz = k.z - t.z;
    if (!dx && !dy && !dz) return;
    t.set(k.x, 0.8, k.z);
    this.camera.position.x += dx;
    this.camera.position.y += dy;
    this.camera.position.z += dz;
  }

  // --- the floor (rebuilt only when the plan key — projects + desks per team — changes) ---

  buildPlan(plan) {
    this.planKey = planAnahtari(plan);
    this.plan = plan;
    for (const v of this.list) if (v.label) v.label.el.remove();
    this.actors.clear();
    this.list.length = 0;
    this.seeded = false;
    for (const d of this.disposables) d.dispose();
    this.disposables = [];
    this.world.clear();
    this.desks.clear();
    this.deskList = [];
    this.floors.clear();
    this.lift = null;
    if (this.bacak) this.bacak.dispose();
    if (this.kol) this.kol.dispose();
    this.bacak = null; // the robots' legs and arms (bacaklariCiz), rebuilt with the actor group
    this.kol = null;
    this.top = null; // the ping-pong ball (buildRoom 'oyun')
    this.salon = null; // the conference hall's screen (buildRoom 'konferans')
    this.levha = null; // the lobby's name sign (buildRoom 'lobi')
    this.sunucu = null; // the Sunucu odası's lights (buildRoom 'sunucu', setSistem)
    this.dekor = null; // the decorative people's instanced meshes (setDekor), rebuilt for the new plan
    this.yaya = null; // the street's pedestrians (setYaya), rebuilt for the new plan

    const W = plan.genislik, D = plan.derinlik;
    this.world.position.set(-W / 2, 0, -D / 2);
    const slab = mesh(new RoundedBoxGeometry(W + 4, 0.8, D + 4, 3, 0.35), mat(BASE_FLOOR), { cast: false });
    slab.position.set(W / 2, -0.1, D / 2);
    const lip = mesh(new RoundedBoxGeometry(W + 4.6, 0.35, D + 4.6, 3, 0.17), mat('#DCC6A8'), { cast: false });
    lip.position.set(W / 2, -0.62, D / 2);
    this.world.add(slab, lip);
    this.disposables.push(slab.geometry, lip.geometry);

    this.buildPerimeter(plan);
    if (plan.otel) this.buildHotel(plan, plan.otel);
    if (plan.sokak) this.buildStreet(plan, plan.sokak);
    plan.odalar.forEach((room) => this.buildRoom(plan, room));
    for (const r of this.roomLabels || []) r.el.remove();
    this.roomLabels = odaEtiketleri(plan).map((r) => {
      const el = document.createElement('div');
      el.className = r.id.startsWith('bos-ekip-') ? 'room-label is-bos' : 'room-label';
      el.textContent = r.ad;
      this.labelHost.appendChild(el);
      return { ...r, el, w: -1, h: 14, lx: NaN, ly: NaN, gor: null };
    });
    this.buildPlaces(plan);
    this.statikBirlestir();
    this.actorGroup = new THREE.Group();
    this.world.add(this.actorGroup);

    const pad = 2.3; // the slab's lip: the whole floor stays in the frame
    // cerceve = the office (the default view frames it); bounds = everything the view may pan to: the office and the
    // Otel outside it (plan.dis: the path and the hotel, with its own slab's lip)
    this.cerceve = { minX: -W / 2 - pad, maxX: W / 2 + pad, minZ: -D / 2 - pad, maxZ: D / 2 + pad };
    this.bounds = { ...this.cerceve };
    if (plan.dis) {
      const o = plan.dis;
      this.bounds = { minX: Math.min(this.bounds.minX, o.x - W / 2 - pad), maxX: Math.max(this.bounds.maxX, o.x + o.w - W / 2 + pad),
        minZ: Math.min(this.bounds.minZ, o.z - D / 2 - pad), maxZ: Math.max(this.bounds.maxZ, o.z + o.d - D / 2 + pad) };
    }
    const ext = Math.max(W, D) / 2 + pad;
    this.extent = ext;
    // the camera's distance and near / far from the floor's size (kameraDerinligi): no part of the floor ever falls
    // behind the near plane or beyond the far plane, wherever the view centre is panned and however it is turned;
    // OrbitControls keeps that distance (min = max distance), also while a focus moves only the target
    const dz = this.derinlik = kameraDerinligi(this.bounds);
    Object.assign(this.camera, { near: dz.near, far: dz.far });
    this.controls.minDistance = this.controls.maxDistance = dz.uzaklik;
    // the sun's shadow box covers the whole floor seen along the light: half the floor's diagonal (a square of
    // max(W, D) missed the corners), with the light far enough back that no corner falls behind its near plane
    // (the Otel included: its guests walk there and cast shadows; the box is centred on the floor's middle)
    const B = this.bounds;
    const yari = Math.hypot(Math.max(-B.minX, B.maxX), Math.max(-B.minZ, B.maxZ)) + 2;
    const s = this.sun.shadow.camera;
    const gunes = new THREE.Vector3(14, 30, 8).normalize().multiplyScalar(yari + 20);
    Object.assign(s, { left: -yari, right: yari, top: yari, bottom: -yari, near: 1, far: 2 * yari + 40 });
    s.updateProjectionMatrix();
    this.sun.position.copy(gunes);
    this.viewSize = Math.max(18, ext * 1.75);
    this.resize();
    this.fit();
    this.select(this.selected && this.floors.has(this.selected) ? this.selected : null, false);
  }

  // The static furniture in a few draw calls (owner decision 2026-11-12, performance): every mesh of the floor with a shared
  // material (mat()) that never moves is baked into one merged mesh per material; meshes with their own material (a
  // desk's screen, a room's floor that lights up when selected, text plates) and dynamic ones (userData.dinamik: the
  // lift doors, the ping-pong ball) stay. Static furniture casts no shadow (only the robots do); it still receives them.
  statikBirlestir() {
    const ortak = new Set(mats.values());
    this.world.updateMatrixWorld(true);
    const ters = new THREE.Matrix4().copy(this.world.matrixWorld).invert();
    const gruplar = new Map();
    const kaldir = [];
    const dinamik = (o) => { for (let p = o; p && p !== this.world; p = p.parent) if (p.userData.dinamik) return true; return false; };
    this.world.traverse((o) => {
      if (!o.isMesh) return;
      if (!ortak.has(o.material) || dinamik(o) || !o.visible) { o.castShadow = false; return; }
      const g = o.geometry;
      if (!g.attributes.position || !g.attributes.normal) return;
      const key = `${o.material.uuid}|${o.receiveShadow ? 1 : 0}`;
      if (!gruplar.has(key)) gruplar.set(key, { material: o.material, receive: o.receiveShadow, list: [] });
      gruplar.get(key).list.push(new THREE.Matrix4().multiplyMatrices(ters, o.matrixWorld), g);
      kaldir.push(o);
    });
    for (const o of kaldir) o.parent.remove(o);
    for (const grp of gruplar.values()) {
      const merged = birlestir(grp.list);
      this.disposables.push(merged);
      const m = new THREE.Mesh(merged, grp.material);
      m.castShadow = false; m.receiveShadow = grp.receive;
      m.matrixAutoUpdate = false;
      this.world.add(m);
    }
  }

  // The Otel (the city, step 1 — owner decision 2026-11-14): a two-storey building in front of the lobby, outside the floor, where
  // the people who used to go home stay. Its own slab with a lip, a paved path from the lobby's entrance gap to its door
  // (in the back wall, facing the office), a closed block — walls, a floor band, rows of windows on the two faces the
  // camera sees, a roof with an overhang — and two plants by the door. A closed building on purpose: its guests are not
  // drawn inside (the scene hides them on arrival), so neither rooms nor beds need drawing; low (two storeys) and far
  // enough out that it never hides the lobby. Shared materials: statikBirlestir merges it per material (the office's
  // slab, wall, path, window, bed-frame and plant materials: the hotel adds no draw call); nothing casts a shadow.
  buildHotel(plan, y) {
    const g = new THREE.Group();
    const D = plan.derinlik, e = 1.7, lip = 0.8;
    const slab = mesh(new RoundedBoxGeometry(y.w + 2 * lip, 0.8, y.d + 2 * lip, 3, 0.35), mat(BASE_FLOOR), { cast: false });
    slab.position.set(y.x + y.w / 2, -0.1, y.z + y.d / 2);
    const rim = mesh(new RoundedBoxGeometry(y.w + 2 * lip + 0.6, 0.35, y.d + 2 * lip + 0.6, 3, 0.17), mat('#DCC6A8'), { cast: false });
    rim.position.set(y.x + y.w / 2, -0.62, y.z + y.d / 2);
    g.add(slab, rim);
    this.disposables.push(slab.geometry, rim.geometry);
    // the path: from the office slab's front edge (past the entrance gap) to the hotel's slab, the width of the gap;
    // since the street (city step 2) only the two pieces off it: the office to the north sidewalk, the south sidewalk
    // to the hotel (the road between is crossed on the crosswalk, buildStreet)
    const kapi = plan.dugumler[y.kapi];
    const x = kapi ? kapi.x : y.x + y.w / 2;
    const parca = (z0, z1) => {
      if (z1 - z0 < 0.2) return;
      const path = mesh(box(2.6, 0.2, +(z1 - z0).toFixed(2)), mat('#DCC6A8'), { cast: false });
      path.position.set(x, 0.12, (z0 + z1) / 2); g.add(path);
      for (let z = z0 + 0.6; z < z1 - 0.3; z += 1.2) { // paving stones
        const st = mesh(box(2.0, 0.04, 0.8), mat('#D2B48F'), { cast: false }); st.position.set(x, 0.24, z); g.add(st);
      }
    };
    const z0 = D + e + 0.3, z1 = y.z - lip;
    if (plan.sokak) { parca(z0, plan.sokak.kuzey.z0); parca(plan.sokak.guney.z1, z1); }
    else parca(z0, z1);
    // the building: KAT storeys of KAT_H, a band between them, a roof with an overhang
    const KAT = y.katlar || 2, KAT_H = 1.9, H = KAT * KAT_H;
    // the office's own colours (outer wall, wall cap, bed frame): merged into existing draw calls, the hotel adds none
    const duvar = mat('#E3CCAE'), bant = mat('#D2B48F'), cati = mat('#9C8A74');
    const govde = mesh(box(y.w, H, y.d), duvar, { cast: false }); govde.position.set(y.x + y.w / 2, 0.3 + H / 2, y.z + y.d / 2); g.add(govde);
    for (let k = 1; k < KAT; k++) {
      const b = mesh(box(y.w + 0.12, 0.14, y.d + 0.12), bant, { cast: false }); b.position.set(y.x + y.w / 2, 0.3 + k * KAT_H, y.z + y.d / 2); g.add(b);
    }
    const roof = mesh(box(y.w + 0.9, 0.3, y.d + 0.9), cati, { cast: false }); roof.position.set(y.x + y.w / 2, 0.3 + H + 0.15, y.z + y.d / 2); g.add(roof);
    // windows (the office's glass and frame materials) on the front and the right face, one per room column and storey
    const pane = mat('#CFE7F2', { roughness: 0.15 }), frame = mat('#FFF8EE');
    const pencere = (px, py, pz, alongX) => {
      const f = mesh(alongX ? box(1.3, 0.95, 0.05) : box(0.05, 0.95, 1.3), frame, { cast: false }); f.position.set(px, py, pz); g.add(f);
      const q = mesh(alongX ? box(1.1, 0.75, 0.06) : box(0.06, 0.75, 1.1), pane, { cast: false }); q.position.set(px, py, pz); g.add(q);
    };
    for (let k = 0; k < KAT; k++) {
      const py = 0.3 + k * KAT_H + KAT_H * 0.55;
      const nx = Math.max(1, Math.floor(y.w / 2.6));
      for (let i = 0; i < nx; i++) {
        const px = y.x + (y.w * (i + 0.5)) / nx;
        if (k === 0 && Math.abs(px - (y.x + y.w / 2)) < 1.6) continue; // the front entrance's place (a glass door below)
        pencere(px, py, y.z + y.d + 0.03, true);
      }
      const nz = Math.max(1, Math.floor(y.d / 2.6));
      for (let i = 0; i < nz; i++) pencere(y.x + y.w + 0.03, py, y.z + (y.d * (i + 0.5)) / nz, false);
    }
    const kapiCam = mesh(box(2.0, 1.5, 0.06), pane, { cast: false }); kapiCam.position.set(y.x + y.w / 2, 0.3 + 0.75, y.z + y.d + 0.04); g.add(kapiCam);
    // the back door (towards the office, where the guests go in) and two plants beside it
    const arka = mesh(box(1.6, 1.5, 0.06), frame, { cast: false }); arka.position.set(x, 0.3 + 0.75, y.z - 0.04); g.add(arka);
    for (const px of [x - 1.9, x + 1.9]) {
      const pl = makePlant(); pl.position.set(px, 0.3, y.z - 0.45); pl.scale.setScalar(0.75); g.add(pl);
    }
    this.world.add(g);
  }

  // The street (the city, step 2 — owner decision 2026-11-14; ofis-davranis.js sokakDuzeni): across the yard between the floor
  // and the Otel, a two-lane road with a dashed centre line, a sidewalk with a curb on both sides, a zebra crossing
  // where the office–Otel path meets it, street lamps and trees on the curb strips. Only the office's own materials
  // (the server room's metal for the asphalt, the counter's light grey for the sidewalks, the wall cap for the curbs,
  // white, the antenna post's dark grey and the ring light for the lamps, the kettle's wood and the plants' leaves for
  // the trees): statikBirlestir merges it into existing draw calls; nothing casts a shadow.
  buildStreet(plan, s) {
    const g = new THREE.Group();
    const L = +(s.x1 - s.x0).toFixed(2), cx = (s.x0 + s.x1) / 2;
    const add = (m, x, y, z) => { m.position.set(x, y, z); g.add(m); return m; };
    const asfalt = mat('#5B616B'), kaldirim = mat('#E9E4DD'), bordur = mat('#D2B48F'), beyaz = mat('#FFFFFF');
    const YOL = +(s.yol.z1 - s.yol.z0).toFixed(2), KAL = +(s.kuzey.z1 - s.kuzey.z0).toFixed(2);
    // the road's top a little below the sidewalks (0.22 against 0.3: the floor's top, where the people stand)
    add(mesh(box(L, 0.72, YOL), asfalt, { cast: false }), cx, -0.14, (s.yol.z0 + s.yol.z1) / 2);
    for (const k of [s.kuzey, s.guney]) {
      add(mesh(box(L, 0.8, KAL), kaldirim, { cast: false }), cx, -0.1, (k.z0 + k.z1) / 2);
      const kenar = k === s.kuzey ? k.z1 - 0.1 : k.z0 + 0.1; // the curb along the road
      add(mesh(box(L, 0.06, 0.2), bordur, { cast: false }), cx, 0.32, kenar);
    }
    // the dashed centre line, broken at the crosswalk; the zebra's bars run along the walk across the road
    const gx = s.gecit.x, gw = s.gecit.w, zm = (s.yol.z0 + s.yol.z1) / 2;
    for (let x = s.x0 + 1; x + 1.6 <= s.x1 - 0.5; x += 3.2) {
      if (x + 1.6 > gx - gw / 2 - 0.4 && x < gx + gw / 2 + 0.4) continue;
      add(mesh(box(1.6, 0.03, 0.14), beyaz, { cast: false }), x + 0.8, 0.235, zm);
    }
    const bar = mesh(box(0.34, 0.03, +(YOL - 0.5).toFixed(2)), beyaz, { cast: false });
    for (let i = 0, n = Math.max(2, Math.floor(gw / 0.64)); i < n; i++) add(bar.clone(), gx - gw / 2 + 0.32 + i * ((gw - 0.64) / (n - 1)), 0.235, zm);
    // street lamps: a pole, an arm over the road and a lamp (the ring light's warm material)
    const direk = mat('#6E7686'), isik = mat('#FFF6DD', { emissive: '#FFE9A8', emissiveIntensity: 0.7 });
    for (const [x, z] of s.lambalar) {
      const yon = z < zm ? 1 : -1; // the arm leans over the road
      add(mesh(cyl(0.16, 0.2, 0.16, 10), direk, { cast: false }), x, 0.38, z);
      add(mesh(cyl(0.06, 0.08, 3.4, 8), direk, { cast: false }), x, 2.0, z);
      add(mesh(box(0.08, 0.08, 0.8), direk, { cast: false }), x, 3.66, z + yon * 0.36);
      add(mesh(box(0.34, 0.12, 0.44), isik, { cast: false }), x, 3.58, z + yon * 0.72);
    }
    // trees: a trunk and a two-ball crown above the pedestrians' heads (makePlant's leaves)
    const govde = mat('#8C6E52'), yaprak = mat('#7DB98A');
    for (const [x, z] of s.agaclar) {
      add(mesh(cyl(0.12, 0.15, 3.0, 8), govde, { cast: false }), x, 1.8, z);
      add(mesh(sphere(0.8, 12, 10), yaprak, { cast: false }), x, 3.85, z).scale.set(1, 0.9, 1);
      add(mesh(sphere(0.55, 10, 8), yaprak, { cast: false }), x + 0.3, 4.45, z - 0.15);
    }
    this.world.add(g);
  }

  // The street's pedestrians (yayaSayisi of them now; none in hafif): anonymous passers-by on their loops
  // (yayaRotalari / yayaKonumu). Scenery only: no label, no card, not clickable, never in who-is-where or the Şema.
  // ONE InstancedMesh for the bodies (the decorative people's lower-detail body, tinted per pedestrian) and ONE for the
  // legs (two instances each, swinging): two draw calls for all of them; no shadows.
  setYaya(n) {
    if (!this.plan || !this.plan.sokak) return;
    const say = this.light ? 0 : Math.max(0, Math.min(YAYA_EN_COK, Math.floor(Number(n) || 0)));
    if (!this.yaya) {
      if (!say) return;
      const { govde, malzeme } = dekorGeometrileri();
      const yap = (g, cap) => {
        const m = new THREE.InstancedMesh(g, malzeme, cap);
        m.castShadow = false; m.receiveShadow = true;
        m.count = 0; m.visible = false; m.frustumCulled = false; m.userData.dinamik = true;
        m.raycast = () => {}; // scenery: never picked
        this.world.add(m);
        return m;
      };
      const Y = this.yaya = { govde: yap(govde, YAYA_EN_COK), bacak: yap(yayaBacagi(), 2 * YAYA_EN_COK), n: 0,
        rotalar: yayaRotalari(this.plan.sokak), m: new THREE.Matrix4(), b: new THREE.Matrix4(), r: new THREE.Matrix4(),
        q: new THREE.Quaternion(), p: new THREE.Vector3(), s: new THREE.Vector3(), y: new THREE.Vector3(0, 1, 0), renk: new THREE.Color() };
      for (let i = 0; i < YAYA_EN_COK; i++) Y.govde.setColorAt(i, Y.renk.set(YAYA_RENK[i % YAYA_RENK.length]));
      Y.govde.instanceColor.needsUpdate = true;
    }
    const Y = this.yaya;
    if (say === Y.n) return;
    Y.n = say;
    Y.govde.count = say; Y.bacak.count = 2 * say;
    Y.govde.visible = Y.bacak.visible = say > 0;
    if (say) this.yayaKonumla(this.clock.elapsedTime);
    this.kirli = true;
  }

  yayaKonumla(t) {
    const Y = this.yaya;
    for (let i = 0; i < Y.n; i++) {
      const k = yayaKonumu(Y.rotalar, i, t);
      if (!k) continue;
      const sal = Math.sin(k.adim * Math.PI);
      Y.p.set(k.x, Y0 + Math.abs(sal) * 0.04, k.z);
      Y.q.setFromAxisAngle(Y.y, k.aci);
      Y.s.setScalar(YAYA_BOY);
      Y.m.compose(Y.p, Y.q, Y.s);
      Y.govde.setMatrixAt(i, Y.m);
      for (const j of [0, 1]) { // the hips at 0.55, the legs swinging in turn
        Y.b.makeTranslation(j ? 0.14 : -0.14, 0.55, 0).multiply(Y.r.makeRotationX((j ? 1 : -1) * sal * 0.45));
        Y.bacak.setMatrixAt(2 * i + j, Y.b.premultiply(Y.m));
      }
    }
    Y.govde.instanceMatrix.needsUpdate = true;
    Y.bacak.instanceMatrix.needsUpdate = true;
  }

  // A low outer wall around the floor, like a cut-away dollhouse: 1.2 high on the two far sides (with windows), a thin
  // ledge on the two near sides so it never hides a room or a robot, and a gap at the entrance (the lobby's front).
  buildPerimeter(plan) {
    const W = plan.genislik, D = plan.derinlik, e = 1.7, cast = !this.light;
    const wall = mat('#E3CCAE'), cap = mat('#D2B48F'), pane = mat('#CFE7F2', { roughness: 0.15 }), frame = mat('#FFF8EE');
    const g = new THREE.Group();
    const seg = (x0, z0, x1, z1, H) => {
      const alongX = Math.abs(z1 - z0) < 1e-6;
      const len = +(alongX ? x1 - x0 : z1 - z0).toFixed(2);
      if (len < 0.1) return;
      const w = mesh(alongX ? box(len, H, 0.25) : box(0.25, H, len), wall, { cast });
      w.position.set((x0 + x1) / 2, 0.3 + H / 2, (z0 + z1) / 2); g.add(w);
      const c = mesh(alongX ? box(len, 0.06, 0.32) : box(0.32, 0.06, len), cap, { cast: false });
      c.position.set((x0 + x1) / 2, 0.3 + H + 0.03, (z0 + z1) / 2); g.add(c);
    };
    seg(-e, -e, W + e, -e, 1.2); // far side along x
    seg(-e, -e, -e, D + e, 1.2); // far side along z
    seg(W + e, -e, W + e, D + e, 0.22); // near ledges
    // the entrance: the lobby's front (the floor's front-right corner)
    const lobby = plan.odalar.find((r) => r.tur === 'lobi');
    const gap = lobby ? [lobby.x + lobby.w / 2 - 1.6, lobby.x + lobby.w / 2 + 1.6] : null;
    if (gap) { seg(-e, D + e, gap[0], D + e, 0.22); seg(gap[1], D + e, W + e, D + e, 0.22); }
    else seg(-e, D + e, W + e, D + e, 0.22);
    // windows on the far walls
    for (let x = 4; x < W - 2; x += 7) {
      const f = mesh(box(2.4, 0.62, 0.04), frame, { cast: false }); f.position.set(x, 1.05, -e + 0.14); g.add(f);
      const p = mesh(box(2.2, 0.5, 0.05), pane, { cast: false }); p.position.set(x, 1.05, -e + 0.16); g.add(p);
    }
    for (let z = 4; z < D - 2; z += 7) {
      const f = mesh(box(0.04, 0.62, 2.4), frame, { cast: false }); f.position.set(-e + 0.14, 1.05, z); g.add(f);
      const p = mesh(box(0.05, 0.5, 2.2), pane, { cast: false }); p.position.set(-e + 0.16, 1.05, z); g.add(p);
    }
    this.world.add(g);
  }

  textPlate(text, w, h, opts, cw = 512, ch = 96) {
    const tex = canvasTexture(textCanvas(text, cw, ch, opts));
    const m = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false });
    const g = new THREE.PlaneGeometry(w, h);
    this.disposables.push(tex, m, g);
    return new THREE.Mesh(g, m);
  }

  buildRoom(plan, r) {
    const g = new THREE.Group();
    if (r.tur === 'bos-ekip') { this.buildReservedBay(r, g); return; }
    const team = r.tur === 'ekip';
    const color = team ? projeRengi(r.proje, plan.projeler, '#EFE6DA') : ROOM_TINT[r.tur] || '#EFE6DA';
    const floorGeo = new RoundedBoxGeometry(r.w, 0.06, r.d, 1, 0.03);
    const name = team ? r.proje : r.tur === 'ceo' ? '__ceo__' : null; // (the Genel Müdür's office is not a selectable room)
    // only a selectable room's floor keeps its own material (it lights up when selected); the others share one per colour
    // and are merged with the static furniture (plan "Sonraki iş (9)": the four managers' offices are one draw call)
    const floorMat = name ? new THREE.MeshStandardMaterial({ color, roughness: 0.9 }) : mat(color, { roughness: 0.9 });
    this.disposables.push(floorGeo);
    if (name) this.disposables.push(floorMat);
    const floor = mesh(floorGeo, floorMat, { cast: false });
    floor.position.set(r.x + r.w / 2, 0.3, r.z + r.d / 2);
    floor.userData.room = name;
    g.add(floor);
    if (name) this.floors.set(name, { floor, color, centre: new THREE.Vector3(r.x + r.w / 2 - plan.genislik / 2, 0.8, r.z + r.d / 2 - plan.derinlik / 2) });

    if (r.tur === 'balkon') { this.buildBalcony(plan, r, g); return; }
    // walls: the far sides only (back = smallest z, left = smallest x), so the camera looks in; a door on the back
    // edge leaves a gap. The CEO room is glass all round.
    const door = plan.dugumler[r.kapi];
    // the CEO's, the Genel Müdür's and the four managers' offices are glass all round
    const glass = r.tur === 'ceo' || r.tur === 'mudur' || r.tur === 'mudurluk';
    const wallMat = glass ? mat('#CFE7F2', { transparent: true, opacity: 0.28, roughness: 0.1, depthWrite: false }) : mat(shade(color, 0.9));
    const capMat = mat(glass ? '#E6D8C6' : shade(color, 0.8));
    const H = glass ? 1.3 : 1.1;
    const wallX = (x0, x1, z, gapX = null) => { // along x at depth z
      const parts = gapX === null ? [[x0, x1]] : [[x0, gapX - 0.85], [gapX + 0.85, x1]];
      for (const [a, b] of parts) {
        if (b - a < 0.1) continue;
        const w = mesh(box(+(b - a).toFixed(2), H, 0.2), wallMat, { cast: !glass });
        w.position.set((a + b) / 2, 0.3 + H / 2, z); g.add(w);
        const cap = mesh(box(+(b - a).toFixed(2), 0.05, 0.24), capMat); cap.position.set((a + b) / 2, 0.3 + H + 0.02, z); g.add(cap);
      }
    };
    const wallZ = (z0, z1, x) => { // along z at x
      const w = mesh(box(0.2, H, +(z1 - z0).toFixed(2)), wallMat, { cast: !glass });
      w.position.set(x, 0.3 + H / 2, (z0 + z1) / 2); g.add(w);
      const cap = mesh(box(0.24, 0.05, +(z1 - z0).toFixed(2)), capMat); cap.position.set(x, 0.3 + H + 0.02, (z0 + z1) / 2); g.add(cap);
    };
    if (team) { // low partitions all round (a gap at both doors): the team areas read as separate, robots stay visible
      const P = 0.42;
      const low = mat(shade(color, 0.86));
      const part = (x0, x1, z0, z1, gaps) => {
        const alongX = Math.abs(z1 - z0) < 1e-6;
        let spans = [[alongX ? x0 : z0, alongX ? x1 : z1]];
        for (const gp of gaps) spans = spans.flatMap(([a, b]) => (gp > a && gp < b ? [[a, gp - 1.1], [gp + 1.1, b]] : [[a, b]]));
        for (const [a, b] of spans) {
          if (b - a < 0.1) continue;
          const len = +(b - a).toFixed(2);
          const w = mesh(alongX ? box(len, P, 0.14) : box(0.14, P, len), low, { cast: false });
          if (alongX) w.position.set((a + b) / 2, 0.3 + P / 2, z0); else w.position.set(x0, 0.3 + P / 2, (a + b) / 2);
          g.add(w);
        }
      };
      const doors = [r.kapi, `${r.id}-kapi-alt`].map((id) => plan.dugumler[id]).filter(Boolean);
      const gx = (z) => doors.filter((d) => Math.abs(d.z - z) < 0.01).map((d) => d.x);
      part(r.x, r.x + r.w, r.z + 0.07, r.z + 0.07, gx(r.z));
      part(r.x, r.x + r.w, r.z + r.d - 0.07, r.z + r.d - 0.07, gx(r.z + r.d));
      part(r.x + 0.07, r.x + 0.07, r.z, r.z + r.d, []);
      part(r.x + r.w - 0.07, r.x + r.w - 0.07, r.z, r.z + r.d, []);
    } else {
      const backDoor = door && Math.abs(door.z - r.z) < 0.01 ? door.x : null;
      wallX(r.x, r.x + r.w, r.z + 0.1, backDoor);
      wallZ(r.z, r.z + r.d, r.x + 0.1);
      if (glass) {
        wallZ(r.z, r.z + r.d, r.x + r.w - 0.1);
        wallX(r.x, r.x + r.w, r.z + r.d - 0.1, door ? door.x : null);
      }
    }

    // the room's name is a small HTML label (odaEtiketleri, placeLabels), readable at any zoom

    const at = (o, x, z, ry = 0) => { o.position.set(x, 0.3, z); o.rotation.y = ry; g.add(o); return o; };
    if (r.tur === 'toplanti') { // the table spans its chairs (the floor is scaled, the furniture is not)
      const ch = Object.values(plan.dugumler).filter((n) => n.oda === 'toplanti' && n.tur === 'sandalye');
      const xs = ch.map((n) => n.x), zs = ch.map((n) => n.z);
      const tw = ch.length ? Math.max(...xs) - Math.min(...xs) + 1.4 : 6, td = ch.length ? Math.max(1.0, Math.max(...zs) - Math.min(...zs) - 1.6) : 1.0;
      scale3(at(makeTable(+tw.toFixed(2), +(td / 1.25).toFixed(2)), r.x + r.w / 2, ch.length ? (Math.min(...zs) + Math.max(...zs)) / 2 : r.z + r.d / 2), [1, 1.25, 1.25]);
      const board = mesh(box(3, 0.8, 0.05), mat('#FFFFFF')); board.position.set(r.x + r.w / 2, 1.0, r.z + 0.24); g.add(board);
      const frame = mesh(box(3.1, 0.06, 0.08), mat('#B9BEC9')); frame.position.set(r.x + r.w / 2, 0.58, r.z + 0.26); g.add(frame);
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.8);
    } else if (r.tur === 'ceo') {
      at(makePlant(), r.x + r.w - 0.8, r.z + 0.9);
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.8);
      at(makeShelf(color), r.x + 0.5, r.z + r.d - 2.3);
    } else if (r.tur === 'mudur') {
      at(makePlant(), r.x + r.w - 0.7, r.z + 0.9).scale.setScalar(0.8);
      at(makeShelf(color), r.x + 0.5, r.z + r.d - 2.3).scale.setScalar(0.9);
    } else if (r.tur === 'mudurluk') { // a manager's glass office (plan "Sonraki iş (9)"): a shelf and a plant, shared materials
      at(makePlant(), r.x + r.w - 0.7, r.z + 0.9).scale.setScalar(0.75);
      at(makeShelf(color), r.x + 0.5, r.z + r.d - 2.3).scale.setScalar(0.85);
    } else if (r.tur === 'qa' || r.tur === 'analist') { // the QA odası / the Analist odası: a whiteboard and a plant
      const board = mesh(box(2.4, 0.7, 0.05), mat('#FFFFFF')); board.position.set(r.x + r.w / 2, 1.0, r.z + 0.24); g.add(board);
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.8);
    } else if (r.tur === 'uzmanlar') { // the quiet work room of the review work: shelves, plants, a whiteboard
      at(makeShelf(color), r.x + 0.5, r.z + r.d - 2.3);
      at(makeShelf(color), r.x + r.w - 0.5, r.z + r.d - 2.3);
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.8);
      at(makePlant(), r.x + r.w - 0.8, r.z + 0.9).scale.setScalar(0.8);
      const board = mesh(box(2.4, 0.7, 0.05), mat('#FFFFFF')); board.position.set(r.x + r.w * 0.25, 1.0, r.z + 0.24); g.add(board);
    } else if (r.tur === 'denetci') {
      at(makeShelf(color), r.x + r.w - 0.5, r.z + r.d - 2.3);
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.8);
    } else if (r.tur === 'cay-ocagi') {
      at(makeKettleCorner(), r.x + 1.5, r.z + 0.5);
      at(makeCoffeeMachine(), r.x + 4.3, r.z + 0.5);
      at(makePlant(), r.x + r.w - 0.7, r.z + r.d - 0.8).scale.setScalar(0.8);
      const fridge = mesh(rbox(0.8, 1.6, 0.7, 2, 0.08), mat('#F4F1EC')); fridge.position.set(r.x + 0.55, 1.1, r.z + 2.0); g.add(fridge);
      for (const [x, z] of plan.cay_masalari || []) scale3(at(makeRoundTable(), x, z), [1.1, 1.25, 1.1]);
    } else if (r.tur === 'ortak-alan') { // the lounge: a rug, a low table in the middle, plants, a shelf
      const rug = mesh(box(+(r.w * 0.62).toFixed(2), 0.02, +(r.d * 0.55).toFixed(2)), mat('#E2C9A8'), { cast: false });
      rug.position.set(r.x + r.w / 2, 0.34, r.z + r.d / 2); g.add(rug);
      // two café tables with cups (their chairs are plan places, buildPlaces) and a sofa against the back wall
      for (const [x, z] of plan.kafe_masalari || []) scale3(at(makeRoundTable(), x, z), [1.0, 1.1, 1.0]);
      const sofa = scale3(at(makeArmchair('#B8C9A6'), r.x + r.w / 2, r.z + 0.75), [2.2, 1.0, 0.9]);
      sofa.rotation.y = 0;
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.85);
      at(makePlant(), r.x + r.w - 0.8, r.z + r.d - 0.8).scale.setScalar(0.85);
      at(makeShelf(color), r.x + r.w - 0.5, r.z + 1.3).scale.setScalar(0.85);
    } else if (r.tur === 'oyun') { // table tennis, billiards, darts and a bean bag (places: plan.oyun, buildPlaces)
      const o = plan.oyun || {};
      if (o.pingpong) {
        at(makePingPongTable(), o.pingpong[0], o.pingpong[1]);
        // the ball (animated only while two play, never in hafif: frame)
        const ball = mesh(sphere(0.06, 8, 6), mat('#FFFFFF', { emissive: '#FFFFFF', emissiveIntensity: 0.2 }), { cast: false });
        ball.position.set(o.pingpong[0], 1.1, o.pingpong[1]); ball.visible = false; ball.userData.dinamik = true; g.add(ball);
        this.top = { ball, x: o.pingpong[0], z: o.pingpong[1], on: false };
      }
      if (o.bilardo) at(makeBilliardTable(), o.bilardo[0], o.bilardo[1]);
      if (o.dart) { const b = makeDartBoard(); b.position.set(o.dart[0], 1.75, r.z + 0.18); g.add(b); }
      at(makePlant(), r.x + r.w - 0.8, r.z + r.d - 0.8).scale.setScalar(0.8);
      at(makeShelf(color), r.x + 0.5, r.z + 2.4).scale.setScalar(0.85);
    } else if (r.tur === 'yemekhane') {
      // the Bulaşıkhane at the far end: a tiled floor strip, a sink with a dishwasher, a rack of plates, a tray trolley
      const B = r.bulasik;
      if (B) {
        const tile = mesh(box(r.w - 0.3, 0.02, r.z + r.d - B.z - 0.15), mat('#E4E8EA'), { cast: false });
        tile.position.set(r.x + r.w / 2, 0.34, (B.z + r.z + r.d) / 2); g.add(tile);
        const sink = at(makeSink(), B.lavabo[0], B.lavabo[1]); sink.rotation.y = Math.PI;
        const dw = mesh(rbox(0.8, 0.85, 0.6, 2, 0.04), mat('#C7CDD4', { metalness: 0.35, roughness: 0.4 }));
        dw.position.set(B.lavabo[0] + 1.0, 0.73, B.lavabo[1]); g.add(dw);
        const rack = mesh(box(1.6, 1.4, 0.45), mat('#B9C0C8', { metalness: 0.4, roughness: 0.4 }));
        rack.position.set(B.raf[0], 1.0, B.raf[1]); g.add(rack);
        for (let i = 0; i < 6; i++) {
          const pl = mesh(cyl(0.16, 0.16, 0.03, 12), mat('#FFFFFF')); pl.rotation.x = Math.PI / 2;
          pl.position.set(B.raf[0] - 0.6 + i * 0.24, 1.15 + (i % 2) * 0.3, B.raf[1]); g.add(pl);
        }
        const cart = mesh(box(0.8, 0.9, 0.5), mat('#9AA3B5', { metalness: 0.3 })); cart.position.set(B.araba[0], 0.8, B.araba[1]); g.add(cart);
        for (let i = 0; i < 3; i++) {
          const tray = mesh(box(0.7, 0.03, 0.42), mat('#D9B98F')); tray.position.set(B.araba[0], 0.6 + i * 0.25, B.araba[1]); g.add(tray);
        }
        // the kitchen (2026-11-14): a stove with four burners and a tall fridge at the strip's free right end, in the
        // dishwasher's, the trolley's and the rack's materials (statikBirlestir merges them: no extra draw call)
        if (B.ocak) {
          const stove = mesh(rbox(1.6, 0.9, 0.7, 2, 0.04), mat('#C7CDD4', { metalness: 0.35, roughness: 0.4 }));
          stove.position.set(B.ocak[0], 0.75, B.ocak[1]); g.add(stove);
          for (let i = 0; i < 4; i++) {
            const burner = mesh(cyl(0.17, 0.17, 0.03, 12), mat('#9AA3B5', { metalness: 0.3 }));
            burner.position.set(B.ocak[0] - 0.38 + (i % 2) * 0.76, 1.215, B.ocak[1] - 0.15 + Math.floor(i / 2) * 0.3); g.add(burner);
          }
        }
        if (B.dolap) {
          const fridge = mesh(rbox(1.0, 2.1, 0.75, 2, 0.05), mat('#B9C0C8', { metalness: 0.4, roughness: 0.4 }));
          fridge.position.set(B.dolap[0], 1.35, B.dolap[1]); g.add(fridge);
        }
      }
      // one long table per band of chairs (plan.yemek_masalari: [x0, x1, z]), plates on each
      for (const [x0, x1, z] of plan.yemek_masalari || []) {
        scale3(at(makeTable(+(x1 - x0).toFixed(2), 0.9), (x0 + x1) / 2, z), [1, 1.25, 1.3]);
        for (let i = 0; i < 4; i++) {
          const plate = mesh(cyl(0.16, 0.14, 0.03, 14), mat('#FFFFFF'));
          plate.position.set(x0 + 0.9 + i * (x1 - x0 - 1.8) / 3, 1.56, z - 0.2 + (i % 2) * 0.4); g.add(plate);
        }
      }
      at(makePlant(), r.x + r.w - 0.7, r.z + 0.9).scale.setScalar(0.8);
    } else if (r.tur === 'lobi') {
      const L = r.lobi; // the guest waiting area: a low table, plants, a water dispenser (plan positions)
      if (L) {
        const t = makeTable(3.4, 1.3, '#CDB79A'); t.scale.y = 0.5; at(t, L.sehpa[0], L.sehpa[1]);
        L.bitkiler.forEach(([x, z]) => at(makePlant(), x, z));
        const su = mesh(rbox(0.5, 1.1, 0.5, 2, 0.05), mat('#EEF1F4')); su.position.set(L.su[0], 0.85, L.su[1]); g.add(su);
        const tank = mesh(cyl(0.2, 0.2, 0.45, 14), mat('#BFE0F2', { transparent: true, opacity: 0.8 }));
        tank.position.set(L.su[0], 1.62, L.su[1]); g.add(tank);
      } else at(makePlant(), r.x + 0.7, r.z + r.d - 0.8);
      this.buildLift(plan, g);
      // the office's name on a sign on the back wall behind the reception desk (setOfisAdi redraws it)
      const rec = plan.dugumler['lobi-resepsiyon'];
      if (rec) {
        const c = document.createElement('canvas'); c.width = 1024; c.height = 256;
        const tex = canvasTexture(c);
        const m = new THREE.MeshBasicMaterial({ map: tex, transparent: true });
        const geo = new THREE.PlaneGeometry(4.4, 1.1);
        this.disposables.push(tex, m, geo);
        const sign = new THREE.Mesh(geo, m);
        sign.position.set(rec.x, 2.0, r.z + 0.24);
        g.add(sign);
        this.levha = { c, tex };
        levhaCiz(c, this.ofisAdi);
        tex.needsUpdate = true;
      }
    } else if (r.tur === 'konferans') { // the hall: a screen on a stand at the back wall, the lectern, a plant
      this.buildHall(plan, r, g);
    } else if (r.tur === 'arge') { // the Ar-Ge odası: a whiteboard on its stand, a bookcase, a plant (the desks: buildPlaces)
      this.buildArGe(r, g, at);
      at(makePlant(), r.x + r.w - 0.8, r.z + 0.9).scale.setScalar(0.8);
    } else if (r.tur === 'sunucu') { // server cabinets with status lights (setSistem), a plant
      this.buildServerRoom(r, g);
      at(makePlant(), r.x + r.w - 0.8, r.z + r.d - 0.8).scale.setScalar(0.8);
    } else if (r.tur === 'muhasebe' || r.tur === 'idari' || r.tur === 'ik') {
      // binders along the back wall, a plant; the accountant's calculator, the office manager's filing cabinet, the HR
      // pin board (the desk itself is a plan place: buildPlaces)
      const cols = r.tur === 'muhasebe' ? ['#C9483F', '#3F6FB5', '#E3B341', '#4E9F76'] : r.tur === 'idari'
        ? ['#6E8B74', '#B5A27A', '#7A8FB5'] : ['#C98C9C', '#A6B9D9', '#E7C38B'];
      at(makeBinderShelf(cols), r.x + 0.5, r.z + 2.2);
      at(makeBinderShelf(cols), r.x + r.w - 0.5, r.z + 2.2);
      at(makePlant(), r.x + r.w - 0.8, r.z + r.d - 0.8).scale.setScalar(0.8);
      const masa = plan.dugumler[`${r.id}-masa`];
      if (masa && r.tur === 'muhasebe') at(makeCalculator(), masa.x + 0.55, masa.z + 0.95);
      if (r.tur === 'idari') {
        const cab = mesh(rbox(0.7, 1.3, 0.6, 2, 0.04), mat('#9AA7B4')); cab.position.set(r.x + r.w - 1.6, 0.95, r.z + 0.6); g.add(cab);
      }
      if (r.tur === 'ik') {
        const pin = mesh(box(2.2, 1.0, 0.05), mat('#D9B98F')); pin.position.set(r.x + r.w / 2, 1.3, r.z + 0.24); g.add(pin);
        ['#FFF3B0', '#CDE7F7', '#F7D3DC', '#D6F0D2'].forEach((c, i) => {
          const note = mesh(box(0.34, 0.34, 0.02), mat(c)); note.position.set(r.x + r.w / 2 - 0.75 + i * 0.5, 1.35 + (i % 2) * 0.12, r.z + 0.28); g.add(note);
        });
      }
    } else if (r.tur === 'sosyal' && r.id !== 'sosyal-studyo') { // the platform pod: screens on the desks, a plant
      at(makePlant(), r.x + r.w - 0.8, r.z + r.d - 0.8).scale.setScalar(0.8);
      at(makeShelf(color), r.x + 0.35, r.z + 1.3).scale.setScalar(0.85);
    } else if (r.tur === 'sosyal') { // the studio: a mood board on the back wall, a ring light and a camera on tripods
      const board = mesh(box(3.2, 1.2, 0.05), mat('#FFFFFF')); board.position.set(r.x + r.w / 2, 1.35, r.z + 0.24); g.add(board);
      ['#F7B5C8', '#B5D8F7', '#FCE38A', '#B8E0C2', '#D7C2F2', '#F9C99B'].forEach((c, i) => {
        const card = mesh(box(0.42, 0.34, 0.02), mat(c)); card.position.set(r.x + r.w / 2 - 1.15 + (i % 3) * 1.15, 1.6 - Math.floor(i / 3) * 0.48, r.z + 0.28); g.add(card);
      });
      const tx = r.x + r.w - 1.4, tz = r.z + 1.6;
      for (let i = 0; i < 3; i++) {
        const leg = mesh(cyl(0.025, 0.025, 1.5, 6), mat('#3E434C'));
        const ang = (i * 2 * Math.PI) / 3;
        leg.position.set(tx + Math.sin(ang) * 0.22, 1.0, tz + Math.cos(ang) * 0.22);
        leg.rotation.set(Math.cos(ang) * 0.15, 0, -Math.sin(ang) * 0.15); g.add(leg);
      }
      const ring = mesh(new THREE.TorusGeometry(0.38, 0.05, 8, 24), mat('#FFF6DD', { emissive: '#FFE9A8', emissiveIntensity: 0.7 }));
      this.disposables.push(ring.geometry);
      ring.position.set(tx, 1.95, tz); g.add(ring);
      const cam = mesh(rbox(0.45, 0.3, 0.3, 1, 0.04), mat('#2F333B')); cam.position.set(r.x + r.w - 0.9, 1.75, r.z + r.d - 1.4); g.add(cam);
      const lens = mesh(cyl(0.1, 0.1, 0.2, 12), mat('#555B66')); lens.rotation.x = Math.PI / 2; lens.position.set(r.x + r.w - 0.9, 1.75, r.z + r.d - 1.65); g.add(lens);
      const pole = mesh(cyl(0.03, 0.03, 1.45, 6), mat('#3E434C')); pole.position.set(r.x + r.w - 0.9, 1.0, r.z + r.d - 1.4); g.add(pole);
    } else if (r.tur === 'wc' || r.tur === 'dus') {
      this.buildRestrooms(plan, r, g);
      if (r.tur === 'dus') { // a bench with towels outside the cubicles
        const bank = plan.dugumler['dus-bank'];
        if (bank) {
          at(makeBench(2.0), bank.x, bank.z);
          ['#F7D3DC', '#CDE7F7', '#FFF3B0'].forEach((c, i) => { const t = mesh(box(0.5, 0.06, 0.4), mat(c)); t.position.set(bank.x - 0.6 + i * 0.6, 0.86, bank.z); g.add(t); });
        }
      }
    } else if (r.tur === 'psikolog') { // a couch, an armchair, a plant, a soft rug
      const rug = mesh(box(4.0, 0.02, 2.6), mat('#D9C6E8'), { cast: false }); rug.position.set(r.x + r.w / 2, 0.34, r.z + r.d - 2.6); g.add(rug);
      scale3(at(makeArmchair('#B7A6CF'), r.x + r.w / 2 - 1.6, r.z + r.d - 2.6), [2.0, 1.0, 0.9]);
      at(makeArmchair('#9C8BB8'), r.x + r.w / 2 + 1.8, r.z + r.d - 2.6);
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.85);
      at(makeShelf(color), r.x + r.w - 0.5, r.z + 2.0).scale.setScalar(0.85);
    } else if (r.tur === 'masaj') { // the tables (places: masaj-yatak-*), towels, a plant, a candle light
      for (const n of Object.values(plan.dugumler).filter((x) => x.tur === 'masaj-yatagi')) {
        const top = mesh(rbox(0.9, 0.16, 2.2, 2, 0.06), mat('#F4EDE4')); top.position.set(n.x, 0.95, n.z); g.add(top);
        for (const dz of [-0.9, 0.9]) { const l = mesh(box(0.7, 0.62, 0.08), mat('#B48A5E')); l.position.set(n.x, 0.6, n.z + dz); g.add(l); }
        const towel = mesh(box(0.8, 0.05, 0.5), mat('#FFFFFF')); towel.position.set(n.x, 1.06, n.z - 0.75); g.add(towel);
      }
      at(makePlant(), r.x + 0.8, r.z + 0.9).scale.setScalar(0.85);
      const candle = mesh(cyl(0.08, 0.08, 0.2, 10), mat('#FFE2A8', { emissive: '#FFC56A', emissiveIntensity: 0.8 })); candle.position.set(r.x + r.w - 0.8, 1.0, r.z + 0.8); g.add(candle);
    } else if (r.tur === 'revir') { // an examination bed, a cabinet with a red cross, a plant (the desk: buildPlaces)
      const bed = scale3(at(makeBed(), r.x + r.w - 2.2, r.z + 4.4), [0.9, 1.0, 0.9]);
      bed.rotation.y = 0;
      const cab = mesh(rbox(1.0, 1.6, 0.55, 2, 0.04), mat('#F4F4F2')); cab.position.set(r.x + 1.2, 1.1, r.z + 0.6); g.add(cab);
      const red = mat('#D64541');
      const c1 = mesh(box(0.36, 0.1, 0.02), red); c1.position.set(r.x + 1.2, 1.4, r.z + 0.89); g.add(c1);
      const c2 = mesh(box(0.1, 0.36, 0.02), red); c2.position.set(r.x + 1.2, 1.4, r.z + 0.89); g.add(c2);
      at(makePlant(), r.x + r.w - 0.8, r.z + 0.9).scale.setScalar(0.8);
    } else if (r.tur === 'spor') { // treadmills, a bike, a weight bench with dumbbells, mats (places: spor-*)
      const metal = mat('#5B616B'), belt = mat('#2F333B');
      for (const n of Object.values(plan.dugumler).filter((x) => x.oda === 'spor')) {
        if (n.tur === 'spor-kosu') {
          const b = mesh(rbox(0.9, 0.18, 1.9, 1, 0.04), belt); b.position.set(n.x, 0.39, n.z); g.add(b);
          const post = mesh(box(0.08, 1.1, 0.08), metal); post.position.set(n.x, 0.95, n.z - 0.9); g.add(post);
          const pan = mesh(box(0.7, 0.35, 0.1), metal); pan.position.set(n.x, 1.5, n.z - 0.9); g.add(pan);
        } else if (n.tur === 'spor-bisiklet') {
          const frame = mesh(box(0.2, 0.7, 1.1), metal); frame.position.set(n.x, 0.65, n.z); g.add(frame);
          const wheel = mesh(cyl(0.32, 0.32, 0.12, 16), belt); wheel.rotation.z = Math.PI / 2; wheel.position.set(n.x, 0.65, n.z - 0.55); g.add(wheel);
          const bar = mesh(box(0.6, 0.06, 0.06), metal); bar.position.set(n.x, 1.35, n.z - 0.45); g.add(bar);
        } else if (n.tur === 'spor-agirlik') {
          const bench = mesh(rbox(0.5, 0.12, 1.6, 1, 0.04), mat('#C9483F')); bench.position.set(n.x, 0.75, n.z + 0.2); g.add(bench);
          const leg = mesh(box(0.4, 0.45, 0.1), metal); leg.position.set(n.x, 0.5, n.z + 0.85); g.add(leg);
          for (const dx of [-0.75, 0.75]) {
            const db = mesh(cyl(0.12, 0.12, 0.35, 10), belt); db.rotation.z = Math.PI / 2; db.position.set(n.x + dx, 0.42, n.z + 1.1); g.add(db);
          }
        } else if (n.tur === 'spor-mat') {
          const m = mesh(box(0.9, 0.03, 1.9), mat(['#7FA3C9', '#9BC9A3', '#E3B341', '#D98C8C'][Number(n.id.slice(-1)) % 4]), { cast: false });
          m.position.set(n.x, 0.33, n.z); g.add(m);
        }
      }
      const mirror = mesh(box(4.0, 1.4, 0.04), mat('#D7EAF2', { metalness: 0.2, roughness: 0.15 })); mirror.position.set(r.x + r.w / 2, 1.3, r.z + 0.24); g.add(mirror);
    } else if (r.tur === 'dinlenme') { // dim: a darker floor (ROOM_TINT), a soft lamp, a curtain along the front
      const curtain = mesh(box(+(r.w - 0.6).toFixed(2), 1.6, 0.06), mat('#7E76A0', { transparent: true, opacity: 0.55 }), { cast: false });
      curtain.position.set(r.x + r.w / 2, 1.1, r.z + r.d - 0.25); g.add(curtain);
      const lamp = mesh(cyl(0.18, 0.26, 0.3, 12), mat('#F4D9A0', { emissive: '#F4C46A', emissiveIntensity: 0.6 })); lamp.position.set(r.x + 0.8, 1.1, r.z + 0.8); g.add(lamp);
      const stand = mesh(cyl(0.04, 0.04, 0.8, 8), mat('#6E6278')); stand.position.set(r.x + 0.8, 0.7, r.z + 0.8); g.add(stand);
    } else if (team) {
      at(makePlant(), r.x + r.w - 0.6, r.z + r.d - 0.7).scale.setScalar(0.75);
      at(makeShelf(color), r.x + 0.35, r.z + 1.3).scale.setScalar(0.85);
    }
    this.world.add(g);
  }

  // The restrooms (WC): a covered block — walls and a closed lid, so the camera never sees inside — with two doors on
  // its front face and a sign above each ("Erkek WC", "Kadın WC"); the sinks stand outside (buildPlaces 'lavabo').
  buildRestrooms(plan, r, g) {
    const b = r.blok;
    if (!b) return;
    const H = 2.3;
    const wall = mat('#C9D3DA');
    const block = mesh(box(b.w, H, b.d), wall); block.position.set(b.x + b.w / 2, 0.3 + H / 2, b.z + b.d / 2); g.add(block);
    const lid = mesh(rbox(+(b.w + 0.3).toFixed(2), 0.16, +(b.d + 0.3).toFixed(2), 1, 0.04), mat('#9FAAB3'));
    lid.position.set(b.x + b.w / 2, 0.3 + H + 0.08, b.z + b.d / 2); g.add(lid);
    const dus = r.tur === 'dus';
    const signs = dus ? ['Duş 1', 'Duş 2'] : ['Erkek WC', 'Kadın WC'];
    for (let i = 0; i < 2; i++) {
      const n = plan.dugumler[`${dus ? 'dus' : 'wc'}-kapi-${i}`];
      if (!n) continue;
      const door = mesh(rbox(1.0, 1.85, 0.08, 1, 0.03), mat(dus ? '#9FC3C9' : i ? '#D98C8C' : '#7FA3C9')); door.position.set(n.x, 0.3 + 0.93, b.z + b.d + 0.04); g.add(door);
      const knob = mesh(sphere(0.05, 8, 6), mat('#E9E4DD')); knob.position.set(n.x + 0.32, 1.25, b.z + b.d + 0.1); g.add(knob);
      const plate = this.textPlate(signs[i], 1.3, 0.3, { fg: '#2F3640', bg: '#FFFFFF', border: '#9FAAB3', size: 0.6 }, 256, 60);
      plate.position.set(n.x, 0.3 + 2.05, b.z + b.d + 0.05); g.add(plate);
    }
  }

  // The Sigara odası: an open-air terrace — a wooden deck, a railing on its open sides (a gap at the door), a standing
  // ashtray, a plant and a bench. No walls.
  buildBalcony(plan, r, g) {
    const rail = mat('#7C6A58');
    const post = (x, z) => { const p = mesh(cyl(0.05, 0.05, 1.0, 6), rail); p.position.set(x, 0.8, z); g.add(p); };
    const bar = (x0, z0, x1, z1) => {
      const len = Math.hypot(x1 - x0, z1 - z0);
      const m = mesh(box(Math.abs(x1 - x0) > 0.01 ? +len.toFixed(2) : 0.08, 0.08, Math.abs(z1 - z0) > 0.01 ? +len.toFixed(2) : 0.08), rail);
      m.position.set((x0 + x1) / 2, 1.28, (z0 + z1) / 2); g.add(m);
      const steps = Math.max(1, Math.round(len / 1.2));
      for (let i = 0; i <= steps; i++) post(x0 + ((x1 - x0) * i) / steps, z0 + ((z1 - z0) * i) / steps);
    };
    const x0 = r.x + 0.1, x1 = r.x + r.w - 0.1, z0 = r.z + 0.1, z1 = r.z + r.d - 0.1;
    bar(x0, z1, x1, z1);
    bar(x0, z0, x0, z1);
    bar(x1, z0, x1, z1);
    const door = plan.dugumler[r.kapi];
    if (door) { bar(x0, z0, door.x - 1.0, z0); bar(door.x + 1.0, z0, x1, z0); }
    const at = (o, x, z, ry = 0) => { o.position.set(x, 0.3, z); o.rotation.y = ry; g.add(o); return o; };
    const b = r.balkon; // the plan's furniture: the ashtray (smoking corner), the benches, the plants
    if (b) {
      at(makeAshtray(), b.kul[0], b.kul[1]);
      for (const [x, z, len, dik] of b.banklar) at(makeBench(len), x, z, dik ? Math.PI / 2 : 0);
      b.bitkiler.forEach(([x, z], i) => { at(makePlant(), x, z).scale.setScalar(i === 2 ? 0.65 : 0.8); });
    } else {
      at(makeAshtray(), r.x + r.w / 2, r.z + r.d / 2 - 0.3);
      at(makeBench(2.6), r.x + r.w / 2, r.z + r.d - 0.8);
      at(makePlant(), r.x + 0.8, r.z + r.d - 0.8).scale.setScalar(0.8);
      at(makePlant(), r.x + r.w - 0.8, r.z + 0.9).scale.setScalar(0.7);
    }
    this.world.add(g);
  }

  // An empty reserved bay of the project wing ("Boş ekip alanı · yeni proje"): a pale, thin floor and a dashed low
  // outline — no desks, not selectable; its name is a room label like the others.
  buildReservedBay(r, g) {
    const floorGeo = new RoundedBoxGeometry(r.w, 0.03, r.d, 1, 0.015);
    // one shared material: every reserved bay's floor is merged into one draw call
    const floorMat = mat(BOS_EKIP, { roughness: 0.95, transparent: true, opacity: 0.75 });
    this.disposables.push(floorGeo);
    const floor = mesh(floorGeo, floorMat, { cast: false });
    floor.position.set(r.x + r.w / 2, 0.29, r.z + r.d / 2);
    g.add(floor);
    const dash = mat(shade(BOS_EKIP, 0.8));
    const L = 0.9, GAP = 0.6, H = 0.12;
    const side = (x0, z0, x1, z1) => {
      const alongX = Math.abs(z1 - z0) < 1e-6;
      const len = alongX ? x1 - x0 : z1 - z0;
      for (let a = 0; a + L <= len + 1e-6; a += L + GAP) {
        const m = mesh(alongX ? box(L, H, 0.1) : box(0.1, H, L), dash, { cast: false });
        if (alongX) m.position.set(x0 + a + L / 2, 0.3 + H / 2, z0); else m.position.set(x0, 0.3 + H / 2, z0 + a + L / 2);
        g.add(m);
      }
    };
    side(r.x, r.z + 0.1, r.x + r.w, r.z + 0.1);
    side(r.x, r.z + r.d - 0.1, r.x + r.w, r.z + r.d - 0.1);
    side(r.x + 0.1, r.z, r.x + 0.1, r.z + r.d);
    side(r.x + r.w - 0.1, r.z, r.x + r.w - 0.1, r.z + r.d);
    this.world.add(g);
  }

  // The lift: a steel frame in the lobby's back wall with two sliding doors, facing the room (and the camera).
  // The Konferans salonu's screen (a canvas: the announcement's first line or the office's name, setDuyuru) and lectern
  // (the CEO stands behind it at the node 'konferans-kursu'); the chairs are plan places (buildPlaces).
  buildHall(plan, r, g) {
    const ekran = r.salon && r.salon.ekran;
    if (ekran) {
      const c = document.createElement('canvas'); c.width = 512; c.height = 256;
      const tex = canvasTexture(c);
      const m = new THREE.MeshBasicMaterial({ map: tex });
      const geo = new THREE.PlaneGeometry(5.2, 2.6);
      this.disposables.push(tex, m, geo);
      const frame = mesh(box(5.5, 2.9, 0.12), mat('#2B3242'), { cast: false });
      frame.position.set(ekran[0], 2.35, r.z + 0.26); g.add(frame);
      const screen = new THREE.Mesh(geo, m);
      screen.position.set(ekran[0], 2.35, r.z + 0.33); g.add(screen);
      for (const dx of [-2.2, 2.2]) {
        const leg = mesh(box(0.12, 0.95, 0.12), mat('#5B616B'), { cast: false });
        leg.position.set(ekran[0] + dx, 0.75, r.z + 0.26); g.add(leg);
      }
      this.salon = { c, tex, metin: null };
      this.ekraniCiz();
    }
    const k = plan.dugumler['konferans-kursu'];
    if (k) {
      const body = mesh(rbox(1.1, 1.15, 0.55, 2, 0.05), mat('#8C6A4A'));
      body.position.set(k.x, 0.3 + 0.58, k.z + 0.75); g.add(body);
      const top = mesh(box(1.25, 0.06, 0.7), mat('#B98A5A'));
      top.position.set(k.x, 0.3 + 1.18, k.z + 0.7); top.rotation.x = 0.18; g.add(top);
      const mic = mesh(cyl(0.03, 0.03, 0.35, 8), mat('#2F333B'));
      mic.position.set(k.x + 0.3, 0.3 + 1.38, k.z + 0.55); g.add(mic);
    }
    const plant = makePlant(); plant.position.set(r.x + r.w - 0.8, 0.3, r.z + 0.9); plant.scale.setScalar(0.8); g.add(plant);
  }

  // The Ar-Ge odası (plan "Sonraki iş (6)"): a whiteboard on two legs with a few written lines and a marker tray at
  // r.arge.tahta, a bookcase with three rows of books at r.arge.kitaplik (both at ofis-davranis.js's sizes, so walks go
  // around them). Static pieces with shared materials only: statikBirlestir merges them into the existing groups.
  buildArGe(r, g, at) {
    const a = r.arge;
    if (!a) return;
    const [TW] = ARGE_TAHTA_OLCU;
    const [tx, tz] = a.tahta;
    const gri = mat('#9AA7B4');
    const board = mesh(box(TW, 1.1, 0.06), mat('#FFFFFF')); board.position.set(tx, 1.75, tz); g.add(board);
    const tray = mesh(box(TW + 0.1, 0.05, 0.14), gri); tray.position.set(tx, 1.18, tz + 0.05); g.add(tray);
    for (const dx of [-1, 1]) {
      const leg = mesh(box(0.06, 1.95, 0.06), gri); leg.position.set(tx + dx * (TW / 2 + 0.03), 1.275, tz); g.add(leg);
    }
    ['#3F6FB5', '#C9483F', '#3F6FB5', '#4E9F76'].forEach((c, i) => {
      const line = mesh(box(1.4 - i * 0.25, 0.03, 0.01), mat(c), { cast: false });
      line.position.set(tx - 0.65 + i * 0.12, 2.08 - i * 0.2, tz + 0.04); g.add(line);
    });
    const [kx, kz] = a.kitaplik;
    const [KW, KD] = ARGE_KITAPLIK_OLCU;
    const frame = mesh(rbox(KW - 0.1, 1.9, KD, 1, 0.03), mat('#D9C3A0')); frame.position.set(kx, 1.25, kz); g.add(frame);
    const cols = ['#C9483F', '#3F6FB5', '#E3B341', '#4E9F76', '#A9C6E8', '#E8A9B8'];
    for (const y of [0.35, 0.95, 1.55]) {
      for (let i = 0; i < 7; i++) {
        const h = 0.34 + (i % 3) * 0.06;
        const book = mesh(box(0.22, h, 0.2), mat(cols[(i + Math.round(y * 10)) % cols.length]));
        book.position.set(kx - 0.12, 0.3 + y + h / 2, kz - KD / 2 + 0.25 + i * 0.27); g.add(book);
      }
    }
  }

  // The Sunucu odası: SUNUCU_KABIN cabinets side by side per group (r.sunucu.gruplar). Their bodies use shared materials
  // (merged by statikBirlestir); the status lights of all cabinets are ONE merged mesh with its own material, the warning
  // beacon on the first cabinet another (hidden — no draw call — unless a domain problem is open). setSistem changes the
  // two materials in place; nothing runs per frame.
  buildServerRoom(r, g) {
    const s = r.sunucu;
    if (!s || !Array.isArray(s.gruplar)) return;
    const [KW, KH, KD] = KABIN_OLCU;
    const leds = [];
    const ledGeo = box(0.16, 0.05, 0.02);
    const m4 = (x, y, z) => new THREE.Matrix4().makeTranslation(x, y, z);
    let first = null;
    for (const [gx, gz] of s.gruplar) {
      for (let k = 0; k < s.kabin; k++) {
        const x = gx + (k - (s.kabin - 1) / 2) * KW;
        const body = mesh(rbox(KW - 0.05, KH, KD, 2, 0.03), mat('#2F333B'));
        body.position.set(x, 0.3 + KH / 2, gz); g.add(body);
        const door = mesh(box(KW - 0.2, KH - 0.25, 0.02), mat('#5B616B'), { cast: false });
        door.position.set(x, 0.3 + KH / 2, gz + KD / 2 + 0.01); g.add(door);
        for (let i = 0; i < 4; i++) leds.push(m4(x - 0.22 + (i % 2) * 0.16, 0.3 + KH - 0.45 - 0.32 * Math.floor(i / 2), gz + KD / 2 + 0.03), ledGeo);
        if (!first) first = [x, gz];
      }
    }
    const isik = new THREE.MeshStandardMaterial({ color: SISTEM_ISIK_YOK, emissive: SISTEM_ISIK_YOK, emissiveIntensity: 0.9, roughness: 0.4 });
    const ledMerged = birlestir(leds);
    const ledMesh = new THREE.Mesh(ledMerged, isik);
    ledMesh.matrixAutoUpdate = false;
    g.add(ledMesh);
    const uyari = new THREE.MeshStandardMaterial({ color: '#E5484D', emissive: '#E5484D', emissiveIntensity: 1.2, roughness: 0.3 });
    const beacon = new THREE.Mesh(cyl(0.12, 0.14, 0.22, 10), uyari);
    beacon.position.set(first[0], 0.3 + KH + 0.11, first[1]);
    beacon.visible = false;
    g.add(beacon);
    this.disposables.push(isik, ledMerged, uyari);
    this.sunucu = { isik, beacon, anahtar: null };
    this.isiklariUygula();
  }

  // state.sistem ({seviye, oneri, domain_sorunu} from bin/sistem.py ozet, or null): the cabinets' lights follow the load
  // (green / yellow / red), a cabinet's beacon lights while a domain problem is open. Changed only when it changes.
  setSistem(oz) {
    this.sistemDurum = oz && typeof oz === 'object' ? { seviye: oz.seviye || null, uyari: Number(oz.domain_sorunu) > 0 } : null;
    this.isiklariUygula();
  }

  isiklariUygula() {
    const S = this.sunucu;
    if (!S) return;
    const d = this.sistemDurum || { seviye: null, uyari: false };
    const anahtar = `${d.seviye}|${d.uyari}`;
    if (S.anahtar === anahtar) return;
    S.anahtar = anahtar;
    const c = SISTEM_ISIK[d.seviye] || SISTEM_ISIK_YOK;
    S.isik.color.set(c);
    S.isik.emissive.set(c);
    S.isik.emissiveIntensity = SISTEM_ISIK[d.seviye] ? 0.9 : 0.25;
    S.beacon.visible = d.uyari;
  }

  // The hall screen's text (app.js: salonEkrani(state, now) — '' shows the office's name). Redrawn only when it changes.
  setDuyuru(metin) {
    const t = typeof metin === 'string' ? metin : '';
    if (this.duyuruMetni === t && (!this.salon || this.salon.metin === t)) return;
    this.duyuruMetni = t;
    this.ekraniCiz();
  }

  // The office's name (app.js from /api/state.ofis.adi): the lobby sign and the hall's idle screen. Redrawn only when
  // it changes; a plan built later draws it at once (buildRoom, buildHall).
  setOfisAdi(ad) {
    const t = typeof ad === 'string' && ad.trim() ? ad.trim() : 'Ofis';
    if (this.ofisAdi === t) return;
    this.ofisAdi = t;
    if (this.levha) { levhaCiz(this.levha.c, t); this.levha.tex.needsUpdate = true; }
    if (this.salon && !this.salon.metin) this.ekraniCiz();
  }

  ekraniCiz() {
    const s = this.salon;
    if (!s) return;
    s.metin = this.duyuruMetni || '';
    ekranCiz(s.c, s.metin, this.ofisAdi);
    s.tex.needsUpdate = true;
  }

  // The decorative people shown now (dekorEkibi): their places, poses and room tints into the two instanced meshes
  // (built once per plan with room for every seat). Nobody shown: the meshes are hidden (no draw call).
  setDekor(list) {
    if (!this.plan) return;
    // hafif keeps it light: the seated and standing ones only (static), never a walker
    const items = (Array.isArray(list) ? list : []).filter((d) => d && Number.isFinite(d.x) && Number.isFinite(d.z) &&
      !(this.light && d.yuruyen))
      // a common-area seat (aci null) faces like a real character on that spot
      .map((d) => (Number.isFinite(d.aci) ? d : { ...d, aci: (d.yer && yuzAcisi(this.plan, d.yer)) || 0 }));
    if (!this.dekor) {
      const { govde, bacak, malzeme } = dekorGeometrileri();
      const cap = Math.max(1, dekorYerleri(this.plan).length);
      const yap = (g) => {
        const m = new THREE.InstancedMesh(g, malzeme, cap);
        m.castShadow = false; m.receiveShadow = !this.light;
        m.count = 0; m.visible = false; m.userData.dinamik = true;
        m.frustumCulled = false; // the walkers move: never culled by a stale bounding sphere
        this.world.add(m);
        return m;
      };
      this.dekor = { govde: yap(govde), bacak: yap(bacak), list: [], bacaklar: [], m: new THREE.Matrix4(),
        q: new THREE.Quaternion(), p: new THREE.Vector3(), s: new THREE.Vector3(), y: new THREE.Vector3(0, 1, 0),
        renk: new THREE.Color(), anahtar: '' };
      this.dekor.govde.userData.dekor = true;
    }
    const D = this.dekor;
    const cap = D.govde.instanceMatrix.count;
    D.list = items.slice(0, cap);
    D.bacaklar = [];
    D.list.forEach((d, i) => {
      // the common areas' people: a coat colour each (the pedestrians' palette); a room's people its tint
      // (by a hash of its id, not its list index: a hidden desk figure must not recolour the others)
      D.renk.set(d.grup === 'ortak' ? YAYA_RENK[[...String(d.id)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % YAYA_RENK.length]
        : DEKOR_TON[d.grup] || projeRengi(d.proje, this.plan.projeler, '#E3D2BF'));
      D.govde.setColorAt(i, D.renk);
      if (!d.oturan) D.bacaklar.push(i);
    });
    D.govde.count = D.list.length;
    D.bacak.count = D.bacaklar.length;
    D.govde.visible = D.list.length > 0;
    D.bacak.visible = D.bacaklar.length > 0;
    if (D.govde.instanceColor) D.govde.instanceColor.needsUpdate = true;
    this.dekorKonumla(0);
    D.govde.boundingSphere = null; D.bacak.boundingSphere = null; // recomputed (frustum culling, picking)
    const anahtar = D.list.map((d) => d.id).join(',');
    if (anahtar !== D.anahtar) { D.anahtar = anahtar; this.kirli = true; }
    // the street's pedestrians: dekorEkibi carries how many walk now (yaya); an older caller: from the clock
    this.setYaya(Number.isInteger(list && list.yaya) ? list.yaya : yayaSayisi(Date.now()));
  }

  // Places every decorative person: seated at its desk (SIT, no legs) or standing; `t` > 0 adds the small calm
  // movements (a slow sway, now and then a short look around; a seated one also breathes). Static in hafif.
  dekorKonumla(t) {
    const D = this.dekor;
    if (!D || !D.list.length) return;
    let b = 0;
    for (let i = 0; i < D.list.length; i++) {
      const d = D.list[i];
      let aci = d.aci, dy = 0, x = d.x, z = d.z;
      const w = d.yuruyen ? dekorYuruyusu(d.rota, t + (d.faz || 0)) : null;
      if (w) { // a walker: along its loop, a small bob while it walks
        x = w.x; z = w.z; aci = w.aci;
        if (w.yuruyor) dy = Math.abs(Math.sin(t * 5.5 + (d.faz || 0))) * 0.035;
      } else if (t > 0) {
        const p = t + (d.faz || 0);
        const c = p % 24; // once in 24 s: a 3 s look to one side and back
        aci += Math.sin(p * 0.45) * 0.07 + (c < 3 ? Math.sin((c / 3) * Math.PI) * 0.45 * ((d.faz || 0) > 12 ? 1 : -1) : 0);
        if (d.oturan) dy = Math.sin(p * 1.1) * 0.012;
      }
      D.p.set(x, Y0 + (d.oturan ? SIT[d.sit] ?? SIT.masa : 0) + dy, z);
      D.q.setFromAxisAngle(D.y, aci);
      D.s.setScalar(DEKOR_BOY);
      D.m.compose(D.p, D.q, D.s);
      D.govde.setMatrixAt(i, D.m);
      if (!d.oturan) D.bacak.setMatrixAt(b++, D.m);
    }
    D.govde.instanceMatrix.needsUpdate = true;
    if (b) D.bacak.instanceMatrix.needsUpdate = true;
  }

  buildLift(plan, g) {
    const n = plan.dugumler.asansor;
    const room = plan.odalar.find((r) => r.id === 'lobi');
    if (!n || !room) return;
    const z = room.z + 0.22;
    const steel = mat('#B7BEC9', { metalness: 0.45, roughness: 0.35 });
    const back = mesh(box(1.7, 2.2, 0.08), mat('#8E97A5')); back.position.set(n.x, 1.4, z - 0.1); g.add(back);
    for (const s of [-1, 1]) {
      const post = mesh(box(0.16, 2.3, 0.18), steel); post.position.set(n.x + s * 0.85, 1.45, z); g.add(post);
    }
    const beam = mesh(box(1.86, 0.22, 0.2), steel); beam.position.set(n.x, 2.6, z); g.add(beam);
    const lamp = mesh(box(0.3, 0.08, 0.05), new THREE.MeshStandardMaterial({ color: '#FFE3A0', emissive: '#FFC861', emissiveIntensity: 0.6 }));
    lamp.position.set(n.x, 2.6, z + 0.11); g.add(lamp);
    const doors = [-1, 1].map((s) => {
      const d = mesh(box(0.82, 2.1, 0.06), mat('#D3D9E2', { metalness: 0.35, roughness: 0.3 }));
      d.position.set(n.x + s * 0.41, 1.35, z); g.add(d);
      d.userData.dinamik = true; // they slide: never merged
      return d;
    });
    this.lift = { doors, x: n.x, z: n.z, open: 0, want: false };
  }

  // Furniture at the plan's places: desks with chairs, meeting and canteen chairs, lobby seats.
  buildPlaces(plan) {
    for (const n of Object.values(plan.dugumler)) {
      const ry = yuzAcisi(plan, n.id) || 0;
      if (n.tur === 'masa' || n.tur === 'mudur-masasi') {
        const big = n.tur === 'mudur-masasi' || n.oda === 'ceo';
        const s = big ? BOSS : DESK;
        const room = plan.odalar.find((r) => r.id === n.oda);
        const color = room && room.tur === 'ekip' ? projeRengi(room.proje, plan.projeler, CEO_COLOR)
          : ROOM_TINT[room ? room.tur : ''] || CEO_COLOR;
        const desk = makeDesk(color, big);
        scale3(desk.group, s);
        desk.group.position.set(n.x, 0.3, n.z + 0.62 + 0.55 * s[2]); // the robot's front + half the desk
        this.world.add(desk.group);
        const chair = makeChair(big ? '#8C95A8' : '#9AA3B5');
        scale3(chair, CHAIR);
        chair.position.set(n.x, 0.3, n.z);
        this.world.add(chair);
        this.desks.set(n.id, desk);
        this.deskList.push(desk);
      } else if (n.tur === 'sandalye') {
        const chair = makeChair(n.oda === 'yemekhane' ? '#C9A97F' : '#A7A0C4');
        scale3(chair, [0.95, 1.3, 0.95]);
        chair.position.set(n.x, 0.3, n.z);
        chair.rotation.y = ry;
        this.world.add(chair);
      } else if (n.tur === 'tabure') {
        const stool = makeStool();
        scale3(stool, [1.0, 1.3, 1.0]);
        stool.position.set(n.x, 0.3, n.z);
        this.world.add(stool);
      } else if (n.tur === 'kafe') { // a café chair facing its table
        const chair = makeChair('#B9A27F');
        scale3(chair, [0.95, 1.3, 0.95]);
        chair.position.set(n.x, 0.3, n.z);
        chair.rotation.y = ry;
        this.world.add(chair);
      } else if (n.tur === 'yatak') { // static: merged with the furniture (statikBirlestir), 20 beds cost no extra draw call
        const bed = makeBed();
        bed.position.set(n.x, 0.3, n.z);
        bed.rotation.y = yatakAcisi(plan, n.id);
        this.world.add(bed);
      } else if (n.tur === 'lavabo') {
        const sink = makeSink();
        sink.position.set(n.x, 0.3, n.z - 0.7);
        this.world.add(sink);
      } else if (n.tur === 'puf') {
        const bag = makeBeanBag();
        bag.position.set(n.x, 0.3, n.z);
        this.world.add(bag);
      } else if (n.tur === 'resepsiyon') {
        const desk = makeReception();
        scale3(desk, [1.0, 1.25, 1.0]);
        desk.position.set(n.x, 0.3, n.z);
        this.world.add(desk);
      } else if (n.tur === 'bekleme') {
        const seat = makeArmchair('#C9B7A2');
        scale3(seat, [0.95, 1.2, 0.95]);
        seat.position.set(n.x, 0.3, n.z);
        this.world.add(seat);
      }
    }
  }

  // --- actors ---

  spotXZ(yer, off) {
    const n = this.plan && yer ? this.plan.dugumler[yer] : null;
    if (!n) return null;
    return { x: n.x + (off ? off[0] : 0), z: n.z + (off ? off[1] : 0) };
  }

  // Diff by id. First render: everyone appears at their place. Later: new actors come in through the lift and walk
  // to their place; a changed place is walked along the graph; `cikis` walks to the lift and leaves; an actor that is
  // no longer listed fades out where it is.
  setActors(actors, plan) {
    if (!plan) return;
    this.kirli = true; // a new state: draw the next frame at once
    if (planAnahtari(plan) !== this.planKey) this.buildPlan(plan);
    this.plan = plan;
    const first = !this.seeded;
    this.seeded = true;
    const list = (actors || []).filter((a) => a && a.id);
    const offs = ortakOfsetler(list);
    const withLabel = etiketSecimi(list, this.host.clientWidth < 600 ? 8 : undefined); // fewer on a phone (decoration first to go)
    const seen = new Set();
    const ids = new Set(list.map((a) => a.id));
    // the ping-pong ball flies only while two players stand at the table
    const oyuncular = list.filter((a) => a.poz === 'pingpong' && /^oyun-pingpong-/.test(a.yer || '')).map((a) => a.id);
    if (this.top) { this.top.on = oyuncular.length >= 2; this.top.ids = oyuncular; }
    for (const a of list) {
      seen.add(a.id);
      let v = this.actors.get(a.id);
      const dest = this.spotXZ(a.yer, offs.get(a.id));
      const still = a.tur === 'ozet' || a.poz === 'evde';
      // a hand-over (`devral`, e.g. the lounge's kadro becomes the new job's worker, or back): the same body walks on
      const old = !v && !first && dest && a.devral && !ids.has(a.devral) ? this.actors.get(a.devral) : null;
      if (old) {
        this.actors.delete(old.id);
        old.id = a.id;
        old.root.userData.aktor = a.id;
        this.actors.set(a.id, old);
        if (old.label) { old.label.el.remove(); old.label = null; } // rebuilt with the new id
        old.fading = 0; old.root.scale.setScalar(1);
        v = old;
        if (still) this.placeAt(v, a.yer, dest); else this.walkTo(v, a.yer, dest);
      } else if (!v) {
        if (!dest || (a.cikis && !first)) continue; // a leaver never seen: nothing to show
        v = this.spawn(a);
        const lift = this.spotXZ('asansor');
        // the external auditors (and the security reviewer) are calls, not people: they appear at their desk; a helper
        // (subagent) is started by its parent at its desk: it appears beside it
        // one first seen at the Otel (a page opened at night) is simply there
        if (first || still || a.denetci || a.tur === 'alt-ajan' || a.otel || !lift || a.yer === 'asansor') this.placeAt(v, a.yer, dest);
        else { this.placeAt(v, 'asansor', lift); this.walkTo(v, a.yer, dest); }
      } else {
        if (v.fading && !a.cikis) { v.fading = 0; v.root.scale.setScalar(1); } // listed again: stays
        const lift = this.spotXZ('asansor');
        if (v.a.poz === 'evde' && !still && dest && lift && !a.denetci) { // back from home: in through the lift
          this.placeAt(v, 'asansor', lift);
          this.walkTo(v, a.yer, dest);
        } else if (dest && (a.yer !== v.yer || Math.abs(dest.x - v.dest.x) + Math.abs(dest.z - v.dest.z) > 0.01)) {
          if (still || v.a.tur === 'ozet') this.placeAt(v, a.yer, dest);
          else this.walkTo(v, a.yer, dest);
        }
      }
      this.apply(v, a, withLabel.has(a.id));
    }
    for (let i = this.list.length - 1; i >= 0; i--) { // backwards: remove() splices this.list
      const v = this.list[i];
      if (seen.has(v.id) || v.fading) continue;
      if (!v.ch || !v.ch.root.visible) this.remove(v);
      else v.fading = 1;
    }
  }

  spawn(a) {
    const root = new THREE.Group();
    root.userData.aktor = a.id;
    this.actorGroup.add(root);
    const v = { id: a.id, a, root, ch: null, key: '', yer: null, dest: { x: 0, z: 0 }, walk: null, aci: 0, hedefAci: 0,
      fading: 0, phase: (this.list.length * 1.731) % 10, label: null, labelWalk: null, sign: null, signText: '',
      lx: NaN, ly: NaN, lh: 2.1, lw: -1, lhp: 20, item: { x: 0, y: 0, w: 0, h: 0, dy: 0, gizli: false, on: 9, kalici: false, toplu: -1 } };
    this.actors.set(a.id, v);
    this.list.push(v);
    return v;
  }

  remove(v) {
    if (v.label) v.label.el.remove();
    if (v.sign) { v.sign.material.map.dispose(); v.sign.material.dispose(); }
    this.actorGroup.remove(v.root);
    this.actors.delete(v.id);
    const i = this.list.indexOf(v);
    if (i >= 0) this.list.splice(i, 1);
    if (v.ch) { v.ch.eyeMat.dispose(); v.ch.bulbMat.dispose(); }
  }

  placeAt(v, yer, xz) {
    v.yer = yer;
    v.dest = xz;
    v.walk = null;
    v.root.position.set(xz.x, Y0, xz.z);
    const f = yuzAcisi(this.plan, yer);
    v.aci = v.hedefAci = f === null ? Math.PI / 4 : f;
    v.root.rotation.y = v.aci;
  }

  walkTo(v, yer, xz) {
    this.yuruyenVar = true; this.kirli = true;
    const from = { x: v.root.position.x, z: v.root.position.z };
    const fromNode = v.walk ? v.walk.sonraki || v.yer : v.yer;
    v.walk = { yol: yolHazirla(yuruyusYolu(this.plan, from, fromNode, yer, xz)), s: 0, sonraki: fromNode };
    v.yer = yer;
    v.dest = xz;
  }

  // Applies the actor's look: the character (rebuilt only when tur/title/model/project change), the "Evde" sign,
  // the symbol, things in hand and the label.
  apply(v, a, hasLabel) {
    const prev = v.a;
    v.a = a;
    const key = `${a.tur}|${a.unvan}|${a.model}|${a.proje}`;
    if (key !== v.key && a.tur !== 'ozet') {
      if (v.ch) { v.root.remove(v.ch.root); v.ch.eyeMat.dispose(); v.ch.bulbMat.dispose(); }
      v.ch = this.character(a);
      v.root.add(v.ch.root);
    }
    v.key = key;
    const ch = v.ch;
    const home = a.poz === 'evde';
    if (ch) {
      ch.root.visible = !home;
      const s = ch.root.scale.x;
      v.lh = (a.tur === 'alt-ajan' ? 2.0 : 2.15) * s + (a.simge ? 0.35 * s : 0);
      ch.badge.visible = !!a.simge && !!getSimgeMats()[a.simge];
      if (ch.badge.visible) ch.badge.material = getSimgeMats()[a.simge];
      ch.items.cup.visible = a.poz === 'cay';
      ch.items.fork.visible = a.poz === 'yemek';
      ch.items.folder.visible = !!a.dosya;
      if (ch.zs && a.poz !== 'uyuyor' && a.poz !== 'yatiyor') for (const z of ch.zs) z.visible = false;
      if (ch.sigara && a.poz !== 'sigara') { ch.sigara.visible = false; for (const p of ch.duman) p.visible = false; }
    } else v.lh = 1.3;
    // the "Evde · …" sign stands on the empty chair
    if (home) {
      const text = a.durum_metni || 'Evde';
      if (!v.sign || v.signText !== text) {
        if (v.sign) { v.root.remove(v.sign); v.sign.material.map.dispose(); v.sign.material.dispose(); }
        const tex = canvasTexture(textCanvas(text, 384, 96, { fg: '#5D6478', bg: '#FFF8EE', border: '#D9CDBD', size: 0.36 }));
        v.sign = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
        v.sign.scale.set(1.6, 0.4, 1);
        v.sign.position.y = 1.15;
        v.signText = text;
        v.root.add(v.sign);
      }
      v.lh = 1.9;
    } else if (v.sign) {
      v.root.remove(v.sign); v.sign.material.map.dispose(); v.sign.material.dispose(); v.sign = null; v.signText = '';
    }
    // label (textContent only)
    if (hasLabel && !v.label) {
      const el = document.createElement('div');
      const strong = document.createElement('strong');
      const st = document.createElement('span');
      st.className = 'st';
      el.append(strong, st);
      const id = a.id;
      el.addEventListener('pointerenter', () => this.setHover(id));
      el.addEventListener('pointerleave', () => { if (this.hoverId === id) this.setHover(null); });
      // Labels take the pointer only to hover and click; presses go on to the canvas (the wheel is the stage's, see
      // tekerlek), so the camera still orbits, pans and zooms over a label (OrbitControls captures the pointer on the canvas). A short press
      // without moving is a click on the label's character (see the canvas pointerup).
      const canvas = this.renderer.domElement;
      el.addEventListener('pointerdown', (e) => {
        this.labelDown = id;
        canvas.dispatchEvent(new PointerEvent('pointerdown', e));
      });
      el.addEventListener('contextmenu', (e) => e.preventDefault());
      this.labelHost.appendChild(el);
      v.label = { el, strong, st };
      v.labelWalk = null;
    } else if (!hasLabel && v.label) {
      v.label.el.remove();
      v.label = null;
    }
    if (v.label && (prev !== a || v.labelWalk === null)) this.labelText(v);
  }

  labelText(v) {
    const walking = !!v.walk;
    const info = etiketBilgisi(v.a, { yuruyor: walking, yakin: this.yakin, uzerinde: this.hoverId === v.id });
    const L = v.label;
    let changed = false;
    if (L.strong.textContent !== info.ad) { L.strong.textContent = info.ad; changed = true; }
    const st = info.durum ? `· ${info.durum}` : '';
    if (L.st.textContent !== st) { L.st.textContent = st; changed = true; }
    // the tooltip names the role when the floor shows only a short name ("Codex" -> "Codex · Dış denetçi")
    const tip = typeof v.a.ipucu === 'string' ? v.a.ipucu : '';
    if (L.el.title !== tip) L.el.title = tip;
    const cls = `desk-label ${info.sinif}${info.grup ? ` ${info.grup}` : ''}${info.kucuk ? ' is-small' : ''}${info.kompakt ? ' is-compact' : ''}${v.a.tur === 'ceo' ? ' is-ceo' : ''}${walking ? ' is-walking' : ''}`;
    if (L.el.className !== cls) { L.el.className = cls; changed = true; }
    v.labelWalk = walking;
    // its place in the de-overlap pass (a working / waiting / hovered label is never folded into a "+N")
    const pr = etiketOnceligi(v.a, { uzerinde: this.hoverId === v.id });
    v.item.on = pr.on; v.item.kalici = pr.kalici;
    if (changed) v.lw = -1; // measured again on the next frame
  }

  character(a) {
    const fam = a.model || '';
    let trim = projeRengi(a.proje, this.plan ? this.plan.projeler : [], '#E3D2BF');
    let shell = SHELL[fam] || '#FFF8F0';
    if (a.tur === 'ceo') { trim = CEO_COLOR; shell = '#FFF8F0'; }
    if (a.tur === 'sus') { trim = SUS_TRIM; shell = '#F1EEEA'; }
    if (fam === 'codex') trim = shade(CODEX_TRIM, 1.38);
    else if (a.denetci) ({ shell, trim } = denetciRenk(fam)); // a free reviewer: its own colours
    const ch = makeCharacter(trim, a.tur === 'ceo', { shell, unvan: a.unvan, tur: a.tur });
    let s = CHAR;
    if (a.tur === 'alt-ajan') s *= 0.7;
    else if (a.unvan === UNVAN.haiku.unvan) s *= 0.9;
    else if (a.tur === 'ceo') s *= 1.08;
    ch.root.scale.setScalar(s);
    return ch;
  }

  // --- picking and selection ---

  setHover(id) {
    if (id === this.hoverId) return;
    const old = this.hoverId && this.actors.get(this.hoverId);
    this.hoverId = id;
    if (old && old.label) this.labelText(old);
    const v = id && this.actors.get(id);
    if (v && v.label) this.labelText(v);
    this.renderer.domElement.style.cursor = v ? 'pointer' : '';
  }

  // The actor under the pointer (bodies only), or null.
  actorAt(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    if (!this.actorGroup) return null;
    const hits = this.raycaster.intersectObjects(this.actorGroup.children, true);
    for (const h of hits) {
      if (h.object.isSprite) continue;
      let o = h.object;
      while (o && o !== this.actorGroup) {
        if (o.userData.aktor) { const v = this.actors.get(o.userData.aktor) || null; return v && v.icerde ? null : v; }
        o = o.parent;
      }
    }
    return null;
  }

  pick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.world.children, true);
    for (const h of hits) {
      if (h.object.isSprite || !h.object.visible) continue;
      let o = h.object;
      if (o.userData.dekor && this.dekor && Number.isInteger(h.instanceId)) { // a decorative person: its plain card
        const d = this.dekor.list[h.instanceId];
        if (d) {
          this.onActor({ id: d.id, tur: 'dekor', grup: d.grup, proje: d.proje || '', etiket: '',
            ...(d.grup === 'ortak' ? { oda: d.oda || '', yuruyen: !!d.yuruyen } : {}) }, { x: e.clientX, y: e.clientY });
          return;
        }
      }
      while (o && o !== this.world) {
        if (o.userData.aktor) {
          const v = this.actors.get(o.userData.aktor);
          if (v && v.icerde) break; // hidden in the WC: not clickable
          if (v) this.onActor(v.a, { x: e.clientX, y: e.clientY }); // every character opens its info card
          return;
        }
        if (o.userData.room !== undefined) {
          const name = o.userData.room;
          this.select(name);
          this.onSelect(name);
          return;
        }
        o = o.parent;
      }
    }
    this.select(null);
    this.onSelect(null);
  }

  select(name, animate = true) {
    const prev = this.selected && this.floors.get(this.selected);
    if (prev) prev.floor.material.emissive.set('#000000');
    this.selected = name;
    const room = name && this.floors.get(name);
    if (room) {
      room.floor.material.emissive.set(room.color);
      room.floor.material.emissiveIntensity = 0.22;
    }
    if (!animate) return;
    const home = this.center ? this.center.clone() : new THREE.Vector3(0, 0.8, 0);
    const z = this.fitZoom || 1;
    const target = room ? room.centre.clone() : home;
    this.focusAnim = { from: this.controls.target.clone(), to: target, z0: this.camera.zoom, z1: room ? Math.max(1.4, z * 2.2) : z, t: 0 };
  }

  // --- frame loop (no allocations) ---

  // A tab panel covers the scene: the labels are hidden by CSS and not placed (set again when the panel closes).
  setLabelsHidden(hidden) {
    const was = !!this.labelsHidden;
    this.labelsHidden = !!hidden;
    if (was && !this.labelsHidden) { this.clock.getDelta(); this.kirli = true; } // no jump after the panel
  }

  // The Komuta masası covers the whole page: no frames are drawn while it is open (the last one stays, dimmed by its
  // backdrop); the clock's delta is dropped on resume so nothing jumps.
  setPaused(paused) {
    const was = !!this.paused;
    this.paused = !!paused;
    if (was && !this.paused) { this.clock.getDelta(); this.kirli = true; }
  }


  frame() {
    // at ~9 fps a frame is ~0.11 s apart: the cap keeps walks at their speed, a long pause never jumps
    const dt = Math.min(this.clock.getDelta(), 0.25);
    const t = this.clock.elapsedTime;
    if (this.focusAnim) {
      const f = this.focusAnim;
      f.t = Math.min(1, f.t + dt / 0.6);
      const k = 1 - Math.pow(1 - f.t, 3);
      if (f.tasi) { // a keyboard pan: the camera moves with its target
        const tg = this.controls.target;
        const px = tg.x, py = tg.y, pz = tg.z;
        tg.lerpVectors(f.from, f.to, k);
        this.camera.position.x += tg.x - px;
        this.camera.position.y += tg.y - py;
        this.camera.position.z += tg.z - pz;
      } else this.controls.target.lerpVectors(f.from, f.to, k);
      if (Number.isFinite(f.aci1)) { // a ↺ / ↻ turn around the target: the distance and the tilt stay
        const tg = this.controls.target;
        this.ofset.copy(this.camera.position).sub(tg);
        this.kure.setFromVector3(this.ofset);
        this.kure.theta = f.aci0 + (f.aci1 - f.aci0) * k;
        this.ofset.setFromSpherical(this.kure);
        this.camera.position.copy(tg).add(this.ofset);
      }
      this.camera.zoom = f.z0 + (f.z1 - f.z0) * k;
      this.camera.updateProjectionMatrix();
      if (f.t >= 1) this.focusAnim = null;
    }
    this.controls.update();
    // the ping-pong ball: bounces between the two players once both have arrived (never in hafif)
    if (this.top && !this.light) {
      const T = this.top;
      let on = T.on;
      if (on) for (const id of T.ids) { const v = this.actors.get(id); if (!v || v.walk) on = false; }
      T.ball.visible = on;
      if (on) {
        T.ball.position.x = T.x + Math.sin(t * 3) * 1.1;
        T.ball.position.y = 1.0 + Math.abs(Math.cos(t * 3)) * 0.35;
      }
    }
    // zoomed in well past the default: every label shows its state text
    const yakin = this.camera.zoom >= (this.fitZoom || 1) * 1.7;
    if (yakin !== this.yakin) {
      this.yakin = yakin;
      for (let i = 0; i < this.list.length; i++) if (this.list[i].label) this.labelText(this.list[i]);
    }
    const sm = getSimgeMats();
    sm.test.opacity = Math.sin(t * 6) > 0 ? 1 : 0.25;
    for (let i = 0; i < this.deskList.length; i++) this.deskList[i].target = 0;
    if (this.lift) this.lift.want = false;
    for (let i = this.list.length - 1; i >= 0; i--) this.step(this.list[i], t, dt);
    if (this.actorGroup) this.bacaklariCiz();
    if (this.dekor && this.dekor.list.length && !this.light) this.dekorKonumla(t);
    if (this.yaya && this.yaya.n) this.yayaKonumla(t);
    for (let i = 0; i < this.deskList.length; i++) {
      const d = this.deskList[i];
      d.level += (d.target - d.level) * Math.min(1, dt * 4);
      const work = d.target > 0.9 ? 1 : 0;
      // only a typing desk lights its screen (a dim, waiting desk shows the merged dark screen: no draw call of its own)
      d.lit.visible = d.level > 0.5;
      d.screenMat.emissiveIntensity = d.level * (0.9 + work * Math.sin(t * 9) * 0.12);
      d.glow.material.opacity = d.level > 0.5 ? (d.level - 0.5) * 0.9 * (1 + Math.sin(t * 3) * 0.15) : 0;
      d.glow.visible = d.level > 0.5; // an unlit glow is no draw call
    }
    if (this.lift) {
      const L = this.lift;
      L.open += ((L.want ? 1 : 0) - L.open) * Math.min(1, dt * 4);
      L.doors[0].position.x = L.x - 0.41 - L.open * 0.62;
      L.doors[1].position.x = L.x + 0.41 + L.open * 0.62;
    }
    // the shadows: only the robots cast; the map is drawn again only while something moves (and every 2 s for the small
    // idle movements)
    let yuruyen = false;
    for (let i = 0; i < this.list.length && !yuruyen; i++) if (this.list[i].walk || this.list[i].fading) yuruyen = true;
    this.yuruyenVar = yuruyen;
    if (yuruyen || t - this.golgeZamani > 2) { this.renderer.shadowMap.needsUpdate = true; this.golgeZamani = t; }
    this.renderer.render(this.scene, this.camera);
    if (!this.labelsHidden) this.placeLabels(); // no label work while a panel covers the scene
  }

  step(v, t, dt) {
    const a = v.a;
    if (v.fading) {
      v.fading = Math.max(0, v.fading - dt * 2.2);
      v.root.scale.setScalar(Math.max(0.001, v.fading));
      if (this.lift && v.yer === 'asansor') this.lift.want = true;
      if (v.fading <= 0) this.remove(v);
      return;
    }
    if (v.walk) {
      v.walk.s += YURUME_HIZI * dt;
      const w = yolKonumu(v.walk.yol, v.walk.s, this.wk);
      v.root.position.x = w.x;
      v.root.position.z = w.z;
      v.walk.sonraki = w.sonraki;
      v.hedefAci = w.aci;
      if (w.bitti) {
        v.walk = null;
        const f = yuzAcisi(this.plan, v.yer);
        if (f !== null) v.hedefAci = f;
        if (a.cikis && v.yer === 'asansor') v.fading = 1;
      }
      if (this.lift && Math.hypot(v.root.position.x - this.lift.x, v.root.position.z - this.lift.z) < 1.8) this.lift.want = true;
    }
    else if (a.cikis && v.yer === 'asansor') v.fading = 1; // already at the lift (e.g. on the first render)
    if (a.gorevli === 'guvenlik' && !v.walk) this.gozetle(v);
    // a restroom visit: hidden inside the covered block once there (not while walking); its label takes no clicks. A
    // guest of the Otel (its place is its room) is hidden inside the closed building the same way, its label too
    // (otelde): no robot and no label is drawn for the people staying there (performance: no draw call at night)
    const otelde = otelOdasiMi(a.yer) && !v.walk;
    const icerde = (a.poz === 'lavaboda' || a.poz === 'dusta' || otelde) && !v.walk;
    v.otelde = otelde;
    if (v.ch && a.poz !== 'evde' && v.ch.root.visible === icerde) v.ch.root.visible = !icerde;
    v.icerde = icerde;
    v.aci += aciFarki(v.aci, v.hedefAci) * Math.min(1, dt * 8);
    v.root.rotation.y = v.aci;
    if (v.label && v.labelWalk !== !!v.walk) this.labelText(v);
    if (!v.ch || !v.ch.root.visible) return;
    if (!v.walk && v.yer === a.masa) {
      const d = this.desks.get(v.yer);
      if (d) d.target = a.poz === 'yaziyor' ? 1 : (a.poz === 'bekliyor' || a.poz === 'el-kaldirmis' || a.poz === 'basi-onde') ? 0.35 : 0;
    }
    this.pose(v, t);
  }

  // The robots' legs and arms (performance, 2026-11-14: the 16:00 shift change drew 732 with everyone walking — two
  // draw calls per standing or walking robot for the legs, two for the arms of every robot): every shown leg of every
  // robot is one instance of ONE InstancedMesh, every arm one instance of a second one, tinted with its robot's trim
  // colour (instance colour, the same material settings as before). The hips still swing and the arms still move
  // (pose); each leg's marker and each arm group gives the instance its matrix, so walking, typing, the guard's nod, a
  // fade-out and the scale look the same; the things in hand stay on the arm groups. Both cast shadows like the parts
  // did; they take no clicks (the body is picked); never culled (they span the floor).
  bacaklariCiz() {
    let nb = 0, nk = 0;
    for (let i = 0; i < this.list.length; i++) {
      const ch = this.list[i].ch;
      if (!ch || !ch.root.visible) continue;
      for (const h of ch.legs) if (h.visible) nb++;
      nk += ch.arms.length;
    }
    const yap = (eski, g, n) => {
      if (eski && eski.instanceMatrix.count >= n) return eski;
      if (eski) { this.actorGroup.remove(eski); eski.dispose(); }
      if (!this.bacakMat) this.bacakMat = new THREE.MeshStandardMaterial({ color: '#FFFFFF', roughness: 0.85, metalness: 0 });
      const cap = Math.max(64, 2 * n);
      const B = new THREE.InstancedMesh(g, this.bacakMat, cap);
      B.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      B.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3);
      B.instanceColor.setUsage(THREE.DynamicDrawUsage);
      B.castShadow = true; B.receiveShadow = true; B.frustumCulled = false;
      B.raycast = () => {};
      B.userData.dinamik = true;
      this.actorGroup.add(B);
      return B;
    };
    this.bacak = yap(this.bacak, bacakGeo(), nb);
    this.kol = yap(this.kol, kolGeo(), nk);
    if (!this.bacakM) this.bacakM = { m: new THREE.Matrix4(), ters: new THREE.Matrix4() };
    const B = this.bacak, K = this.kol;
    B.count = nb; B.visible = nb > 0;
    K.count = nk; K.visible = nk > 0;
    if (!nb && !nk) return;
    this.actorGroup.updateMatrixWorld(true);
    const { m, ters } = this.bacakM;
    ters.copy(this.actorGroup.matrixWorld).invert();
    let kb = 0, kk = 0;
    for (let i = 0; i < this.list.length; i++) {
      const ch = this.list[i].ch;
      if (!ch || !ch.root.visible) continue;
      for (const h of ch.legs) {
        if (!h.visible) continue;
        B.setMatrixAt(kb, m.multiplyMatrices(ters, h.userData.bacak.matrixWorld));
        B.setColorAt(kb, ch.legRenk);
        kb++;
      }
      for (const a of ch.arms) {
        K.setMatrixAt(kk, m.multiplyMatrices(ters, a.matrixWorld));
        K.setColorAt(kk, ch.legRenk);
        kk++;
      }
    }
    for (const X of [B, K]) { X.instanceMatrix.needsUpdate = true; X.instanceColor.needsUpdate = true; }
  }

  // the guard: turns towards the nearest robot walking near the entrance and nods; else faces the hall
  gozetle(v) {
    let best = null, bd = 6;
    for (let i = 0; i < this.list.length; i++) {
      const o = this.list[i];
      if (o === v || !o.walk || !o.ch || !o.ch.root.visible) continue;
      const d = Math.hypot(o.root.position.x - v.root.position.x, o.root.position.z - v.root.position.z);
      if (d < bd) { bd = d; best = o; }
    }
    v.selam = !!best;
    if (best) v.hedefAci = Math.atan2(best.root.position.x - v.root.position.x, best.root.position.z - v.root.position.z);
    else { const f = yuzAcisi(this.plan, v.yer); if (f !== null) v.hedefAci = f; }
  }

  pose(v, t) {
    const { ch, a } = v;
    const p = t + v.phase;
    const walking = !!v.walk;
    const seated = !walking && oturmaYeri(this.plan, v.yer);
    const poz = walking ? 'yuruyor' : a.poz;
    const body = ch.body;
    const l = ch.arms[0], r = ch.arms[1];
    let by = ch.baseY, rx = 0, ry = 0;
    l.position.set(-0.3, ARM_Y, ARM_Z);
    r.position.set(0.3, ARM_Y, ARM_Z);
    let eye = Math.sin(p * 0.9) > 0.985 ? 0.2 : 1.3;
    let eyeGlow = 0.9, bulb = 0.15;
    ch.legs[0].visible = ch.legs[1].visible = !seated;
    if (ch.cue) ch.cue.visible = poz === 'bilardo';
    ch.root.position.y = seated ? SIT[this.plan.dugumler[v.yer].tur] || 0 : 0;
    ch.legs[0].rotation.x = ch.legs[1].rotation.x = 0;
    if (poz === 'yuruyor' && walking) {
      const k = p * 9;
      by += Math.abs(Math.sin(k)) * 0.05;
      rx = 0.08;
      if (!this.light) {
        ch.legs[0].rotation.x = Math.sin(k) * 0.6;
        ch.legs[1].rotation.x = -Math.sin(k) * 0.6;
        l.position.z = ARM_Z * 0.6 + Math.sin(k) * 0.12;
        r.position.z = ARM_Z * 0.6 - Math.sin(k) * 0.12;
      }
    } else if (poz === 'yaziyor') {
      by += Math.abs(Math.sin(p * 5)) * 0.05;
      ry = Math.sin(p * 1.3) * 0.08;
      l.position.y = ARM_Y + Math.max(0, Math.sin(p * 18)) * 0.06;
      r.position.y = ARM_Y + Math.max(0, Math.sin(p * 18 + Math.PI)) * 0.06;
      bulb = 0.5 + Math.max(0, Math.sin(p * 4)) * 1.2;
    } else if (poz === 'el-kaldirmis') {
      r.position.set(0.36, 0.42 + Math.sin(p * 6) * 0.04, 0.18);
      bulb = 0.9;
    } else if (poz === 'uyuyor') {
      by -= 0.06; rx = 0.38; eye = 0.18; eyeGlow = 0.15;
    } else if (poz === 'masajda') { // lying face down on a massage table
      by += 0.7; rx = 1.4; eye = 0.15; eyeGlow = 0.1;
      ch.legs[0].visible = ch.legs[1].visible = false;
    } else if (poz === 'yatiyor') { // asleep on a bed of the Dinlenme odası: lying on its back, eyes closed
      by += 0.55; rx = -1.35; eye = 0.12; eyeGlow = 0.1;
      ch.legs[0].visible = ch.legs[1].visible = false;
    } else if (poz === 'kosuyor') { // on a treadmill (static in hafif)
      const k = this.light ? 0 : Math.sin(p * 9);
      by += Math.abs(k) * 0.08; l.position.z = ARM_Z + k * 0.12; r.position.z = ARM_Z - k * 0.12;
    } else if (poz === 'bisiklet') {
      by += 0.25; const k = this.light ? 0 : Math.sin(p * 5); rx = 0.2; by += k * 0.02;
    } else if (poz === 'agirlik') { // lifts the dumbbells
      const k = this.light ? 0 : Math.max(0, Math.sin(p * 2.2));
      l.position.set(-0.36, ARM_Y + k * 0.35, 0.12); r.position.set(0.36, ARM_Y + k * 0.35, 0.12);
    } else if (poz === 'yoga') { // arms up, a slow stretch
      const k = this.light ? 0 : Math.sin(p * 0.8);
      l.position.set(-0.3, 0.45 + k * 0.05, 0.1); r.position.set(0.3, 0.45 + k * 0.05, 0.1); ry = k * 0.15;
    } else if (poz === 'sigara') { // on the terrace: the hand with the cigarette goes to the mouth now and then
      const puff = this.light ? false : (p % 6) < 1.4;
      r.position.set(0.24, puff ? 0.5 : ARM_Y + 0.05, puff ? 0.34 : ARM_Z + 0.08);
      this.sigara(ch, r, p);
    } else if (poz === 'cay') {
      const sip = (p % 5) < 1.1;
      r.position.set(0.28, sip ? 0.12 : ARM_Y + 0.04, sip ? 0.42 : ARM_Z + 0.04);
      by += Math.sin(p * 1.6) * 0.015;
    } else if (poz === 'cay-al') { // at the counter: reaches for the kettle / the coffee machine
      r.position.set(0.3, ARM_Y + 0.12, 0.42 + (this.light ? 0 : Math.max(0, Math.sin(p * 2)) * 0.06));
    } else if (poz === 'pingpong') { // the bat arm swings; a little hop (static in hafif)
      const k = this.light ? 0 : Math.sin(p * 6);
      r.position.set(0.34 + k * 0.06, ARM_Y + 0.12, 0.3 + k * 0.16);
      if (!this.light) by += Math.abs(Math.sin(p * 6)) * 0.04;
    } else if (poz === 'bilardo') { // leans over the table, the cue arm strokes now and then
      rx = 0.42;
      const k = this.light ? 0 : Math.max(0, Math.sin(p * 1.4)) * 0.12;
      l.position.set(-0.22, ARM_Y + 0.02, 0.42); r.position.set(0.22, ARM_Y + 0.02, 0.2 - k);
      if (!ch.cue) {
        const cue = mesh(cyl(0.015, 0.025, 1.5, 6), mat('#C9A97F'), { cast: false });
        cue.rotation.x = Math.PI / 2; cue.position.set(0.18, ARM_Y + 0.0, 0.55); ch.body.add(cue); ch.cue = cue;
      }
      ch.cue.position.z = 0.55 - k;
    } else if (poz === 'dart') { // aims, then throws
      const k = this.light ? 0 : Math.max(0, Math.sin(p * 1.8));
      r.position.set(0.3, ARM_Y + 0.32 + k * 0.06, 0.12 + k * 0.3);
    } else if (poz === 'yikiyor') { // at the Bulaşıkhane's sink: both hands scrub (static in hafif)
      const k = this.light ? 0 : Math.sin(p * 7);
      l.position.set(-0.22 + k * 0.05, ARM_Y + 0.1, 0.42); r.position.set(0.22 - k * 0.05, ARM_Y + 0.1, 0.42);
      rx = 0.15;
    } else if (poz === 'tepsi') { // collecting the trays: both arms forward, carrying a stack
      l.position.set(-0.24, ARM_Y + 0.14, 0.4); r.position.set(0.24, ARM_Y + 0.14, 0.4);
      by += Math.sin(p * 2) * 0.015;
    } else if (poz === 'yemek') {
      r.position.y = ARM_Y + 0.04 + Math.max(0, Math.sin(p * 3)) * 0.14;
      rx = 0.12;
    } else if (poz === 'basi-onde') {
      rx = 0.36; by -= 0.03; eye = 0.6; eyeGlow = 0.35;
    } else if (poz === 'toplanti') {
      rx = Math.pow(Math.max(0, Math.sin(p * 0.8)), 8) * 0.25;
      bulb = 0.4;
    } else if (poz === 'kutluyor') {
      by += Math.max(0, Math.sin(p * 6)) * 0.18;
      l.position.set(-0.36, 0.3, 0.2); r.position.set(0.36, 0.3, 0.2);
      bulb = 1.2;
    } else if (poz === 'lobide') {
      ry = Math.sin(p * 0.5) * 0.3;
    } else if (poz === 'bekliyor') {
      by += Math.sin(p * 1.6) * 0.015;
      bulb = a.simge === '?' ? 0.9 : 0.3;
    } else {
      by += Math.sin(p * 1.6) * 0.015;
    }
    if (v.selam) rx = Math.max(0, Math.sin(p * 4)) * 0.22; // the guard nods to an arrival
    body.position.y = by;
    body.rotation.x += (rx - body.rotation.x) * 0.12;
    body.rotation.y = ry;
    for (let i = 0; i < ch.eyes.length; i++) ch.eyes[i].scale.y += (eye - ch.eyes[i].scale.y) * 0.3;
    ch.eyeMat.emissiveIntensity = eyeGlow;
    ch.bulbMat.emissiveIntensity = bulb;
    if (ch.badge.visible) ch.badge.position.y = 2.35 + Math.sin(p * 2.4) * 0.08;
    // z's above a sleeper (created on first need)
    if (poz === 'uyuyor' || poz === 'yatiyor') {
      if (!ch.zs) {
        ch.zs = [0, 1, 2].map(() => { const s = sprite(getTextures().z, 0.35, 0); ch.root.add(s); return s; });
      }
      for (let i = 0; i < 3; i++) {
        const z = ch.zs[i];
        const k = ((p * 0.35 + i / 3) % 1);
        z.visible = true;
        z.position.set(0.25 + k * 0.35, 1.9 + k * 0.9, 0.1);
        z.material.opacity = Math.sin(k * Math.PI) * 0.9;
        const sc = 0.22 + k * 0.25; z.scale.set(sc, sc, 1);
      }
    }
  }

  // The cigarette in the hand and a faint smoke: a tiny white stick on the arm, three small grey sprites that rise and
  // fade (created once per character on first need, one shared texture; no allocation per frame; still in hafif).
  sigara(ch, arm, p) {
    if (!ch.sigara) {
      const stick = mesh(cyl(0.018, 0.018, 0.16, 6), mat('#F4F1EA'), { cast: false });
      const tip = mesh(cyl(0.02, 0.02, 0.03, 6), mat('#E2683C', { emissive: '#E2683C', emissiveIntensity: 0.8 }), { cast: false });
      tip.position.y = 0.09; stick.add(tip);
      stick.rotation.x = Math.PI / 2;
      ch.body.add(stick); ch.sigara = stick;
      if (!duman) duman = glowTexture('205,205,210');
      ch.duman = [0, 1, 2].map(() => { const s = sprite(duman, 0.22, 0); s.material.depthWrite = false; ch.root.add(s); return s; });
    }
    ch.sigara.visible = true;
    ch.sigara.position.set(arm.position.x + 0.02, arm.position.y + 0.02, arm.position.z + 0.12);
    for (let i = 0; i < ch.duman.length; i++) {
      const s = ch.duman[i];
      if (this.light) { s.visible = false; continue; }
      const k = (p * 0.4 + i / ch.duman.length) % 1;
      s.visible = true;
      s.position.set(0.3 + k * 0.15, 1.3 + k * 0.9, 0.35);
      s.material.opacity = Math.sin(k * Math.PI) * 0.35;
      const sc = 0.18 + k * 0.3; s.scale.set(sc, sc, 1);
    }
  }

  // The "+N" chips of folded labels (etiketleriYerlestir): one small DOM element per chip from a reused pool, at the
  // right of the label it sits on; hover or a click/tap lists the names (textContent only). Writes only what changed.
  placeChips(cipler, nc, items, owners) {
    const pool = this.chipPool || (this.chipPool = []);
    for (let c = 0; c < nc; c++) {
      let ch = pool[c];
      if (!ch) {
        const el = document.createElement('div');
        el.className = 'etiket-cip';
        const sayi = document.createElement('span');
        sayi.className = 'sayi';
        const liste = document.createElement('span');
        liste.className = 'liste';
        el.append(sayi, liste);
        el.addEventListener('click', (e) => { e.stopPropagation(); el.classList.toggle('acik'); });
        el.addEventListener('pointerleave', () => el.classList.remove('acik'));
        this.labelHost.appendChild(el);
        ch = pool[c] = { el, sayi, liste, x: NaN, y: NaN, metin: '', gor: false };
      }
      const s = items[cipler[c].sahip];
      const right = this.renderer.domElement.clientWidth - (this.inset || 0) - 34; // kept inside the visible area
      const x = Math.round(Math.min(s.x + s.w / 2 + 3, right)), y = s.y + s.dy;
      if (x !== ch.x || y !== ch.y) {
        ch.el.style.transform = `translate(${x}px, ${y}px) translate(0, -100%)`;
        ch.x = x; ch.y = y;
      }
      const uy = cipler[c].uyeler;
      let metin = '';
      for (let k = 0; k < uy.length; k++) metin += (k ? '\n' : '') + owners[uy[k]].label.strong.textContent;
      if (metin !== ch.metin) {
        ch.sayi.textContent = `+${uy.length}`;
        ch.liste.textContent = metin;
        ch.el.title = metin.replace(/\n/g, ', ');
        ch.metin = metin;
      }
      if (!ch.gor) { ch.el.style.display = ''; ch.gor = true; }
    }
    for (let c = nc; c < pool.length; c++) {
      const ch = pool[c];
      if (ch.gor) { ch.el.style.display = 'none'; ch.el.classList.remove('acik'); ch.gor = false; }
    }
  }

  // Projects the labels, then stacks or folds overlapping ones (etiketleriYerlestir) so crowded spots stay readable.
  placeLabels() {
    const w = this.renderer.domElement.clientWidth, h = this.renderer.domElement.clientHeight;
    const ox = this.world.position.x, oz = this.world.position.z;
    const items = this.labelItems || (this.labelItems = []);
    const owners = this.labelOwners || (this.labelOwners = []);
    let n = 0;
    // every size read first, in one pass, before any style write of this frame (one layout at most, never a
    // read-after-write per label)
    for (let i = 0; i < this.list.length; i++) {
      const v = this.list[i];
      if (v.label && v.lw < 0) { v.lw = v.label.el.offsetWidth; v.lhp = v.label.el.offsetHeight; }
    }
    for (const r of this.roomLabels || []) if (r.w < 0) { r.w = r.el.offsetWidth; r.h = r.el.offsetHeight; }
    for (let i = 0; i < this.list.length; i++) {
      const v = this.list[i];
      if (!v.label) continue;
      const s = v.fading ? v.fading : 1;
      this.tmp.set(v.root.position.x + ox, Y0 + v.lh * s, v.root.position.z + oz).project(this.camera);
      const it = v.item;
      it.x = Math.round((this.tmp.x * 0.5 + 0.5) * w);
      it.y = Math.round((-this.tmp.y * 0.5 + 0.5) * h);
      it.w = v.lw; it.h = v.lhp;
      // labels under the side panel are hidden (the panel would cover them anyway)
      it.gizli = v.otelde || (v.fading ? v.fading < 0.3 : !(this.tmp.z < 1 && it.x > -50 && it.x < w - (this.inset || 0) + 20));
      // a label near the edge (e.g. the auditors' on a phone) is pulled inside the visible area instead of cut off
      const right = w - (this.inset || 0) - 4 - it.w / 2;
      if (!it.gizli && right >= 4 + it.w / 2) it.x = Math.min(Math.max(it.x, 4 + it.w / 2), right);
      items[n] = it; owners[n] = v; n++;
    }
    // by priority (working / waiting first, idle last): an overlapping label is stacked above, at most a little (it
    // stays next to its robot); one that would go further is folded into a "+N" chip — never a working or waiting one
    const cipler = this.labelChips || (this.labelChips = []);
    const nc = etiketleriYerlestir(items, n, this.labelOrder || (this.labelOrder = []), cipler, { max: 48 });
    for (let i = 0; i < n; i++) {
      const v = owners[i], it = items[i];
      const gizli = it.gizli || it.toplu >= 0;
      const y = it.y + it.dy;
      if (it.x !== v.lx || y !== v.ly) {
        v.label.el.style.transform = `translate(${it.x}px, ${y}px) translate(-50%, -100%)`;
        v.lx = it.x; v.ly = y;
      }
      const op = gizli ? '0' : '1';
      if (v.label.el.style.opacity !== op) v.label.el.style.opacity = op;
      const pe = gizli || v.icerde ? 'none' : ''; // a hidden label (under the side panel, in a "+N") is not clickable
      if (v.label.el.style.pointerEvents !== pe) v.label.el.style.pointerEvents = pe; // nobody is clicked inside the WC
    }
    this.placeChips(cipler, nc, items, owners);
    // room names: small, below the actors' labels in priority — hidden where an actor label is, and on a phone only
    // when zoomed in
    const phone = w < 600;
    const rect = this.roomRect || (this.roomRect = { x: 0, y: 0, w: 0, h: 0 });
    items.length = n;
    for (const r of this.roomLabels || []) {
      this.tmp.set(r.x + ox, 0.45, r.z + oz).project(this.camera);
      rect.x = Math.round((this.tmp.x * 0.5 + 0.5) * w);
      rect.y = Math.round((-this.tmp.y * 0.5 + 0.5) * h);
      rect.w = r.w; rect.h = r.h;
      const inView = this.tmp.z < 1 && rect.x > r.w / 2 && rect.x < w - (this.inset || 0) - r.w / 2 && rect.y > r.h && rect.y < h;
      const gor = inView && (!phone || this.yakin) && odaEtiketiGorunur(rect, items);
      if (rect.x !== r.lx || rect.y !== r.ly) {
        r.el.style.transform = `translate(${rect.x}px, ${rect.y}px) translate(-50%, -100%)`;
        r.lx = rect.x; r.ly = rect.y;
      }
      if (gor !== r.gor) { r.el.style.opacity = gor ? '1' : '0'; r.gor = gor; }
    }
  }
}
