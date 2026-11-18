// Behaviour engine of the living office (no DOM, no three.js): who stands where and does what, derived only from the
// /api/state data. The scene (web/scene.js) draws the result; it never decides behaviour itself.
// Tested with node in test/test_web.py.
//
// API
// - UNVAN: model family -> {unvan, rank}. modelAilesi(model) -> haiku|sonnet|opus|fable|codex|"".
// - The external auditors: denetciListesi(modeller) -> ['codex', <free reviewers>...] (one desk each in the auditor's
//   room, options.denetciler of ofisPlani), denetciMasasi(ad), denetciAdi(ad) ("GLM"), ucretsizDenetciMi(row).
// - ofisPlani(projects, options) -> the floor as data: odalar (rooms with a logical rectangle and a door node),
//   dugumler (waypoints: corridor nodes, doors and places such as desks and seats, each {id, x, z, tur, oda}),
//   kenarlar (straight edges), masa_sayisi, ortak (the common area's rectangle) and kanat (the project wing's
//   rectangle with its grid: sutun, satir, yedek = empty reserved bays); plan.yol(a, b) = yol(plan, a, b).
//   kanatIzgarasi(T, options) -> the floor's grid for T projects (wing rows / columns, reserved bays, the cells). Review work sits at the Uzmanlar odası's desks; the meeting
//   room (Toplantı odası) stays an empty meeting room.
// - yol(plan, from, to) -> the shortest walk as [{id, x, z}] (Dijkstra on the edge lengths); [] when unknown.
// - niyetler(state, now, prev, options) -> the actor list (see the rule table in niyet()). Ids are stable across ticks
//   ("is:<note>", "oturum:<name>", "ceo", "denetci:<reviewer>", "hakem", "sus:cayci" / "sus:guvenlik" / "sus:sekreter"
//   / "sus:muhasebe" / "sus:idari" / "sus:ik" / "sus:proje:<p>" (staff: decoration with an info card), "<parent>/alt:<id>",
//   "ozet:<...>"); desks are kept
//   from `prev` (the previous result) while their owner exists. Deterministic for a given (state, now, prev): no
//   Math.random, no browser time zone — every wall clock is read in state.sahne.saat_dilimi through Intl.
// - ogleMi(now, sahne), ofisSaati(now, tz), zamanMs(value, tz, ofsetDk), donusMetni(donus, now, tz): time helpers.
//   `now` is required (nowMs throws on a missing or invalid time). Naive job stamps are the server's local time and
//   are read with state.sahne.sunucu_utc_ofset_dk when the server sends it (else in the office zone).
// - A room that is full (Uzmanlar odası, CEO door queue, tea corner, canteen, lobby, team desks, a parent's helpers)
//   gets one "+N" actor (tur 'ozet') instead of two actors on one spot; the last canteen chair is the CEO's.
// - The owner's name (ofis.json sahip_adi, /api/state.sahip; plan "2. Aşama" "Sahip adı"): sahipAyarla(state.sahip)
//   once per state (web/app.js), sahipAdi() / sahip(hal) read it (default "Sahip"), sahipEk(ad, hal) is the pure
//   Turkish case suffix (the same rule as bin/sahip.py ek). One copy for the page: ofis-text.js and ofis-sahne.js import it.
// Every text (etiket, durum_metni) is a plain string for textContent / canvas text, never HTML.

// --- the owner's name and its Turkish case suffixes ---
export const SAHIP_VARSAYILAN = 'Sahip';
import { aktifDil } from './i18n.js';

export const SAHIP_HALLERI = ['e', 'in', 'den', 'i', 'de']; // dative, genitive, ablative, accusative, locative
const SESLI = 'aeıioöuü';
const KALIN = 'aıou';
const DORTLU = { a: 'ı', ı: 'ı', o: 'u', u: 'u', e: 'i', i: 'i', ö: 'ü', ü: 'ü' };
const SERT = 'fstkçşhp';
const TURK_HARFLERI = 'abcçdefgğhıijklmnoöprsştuüvyz';
// any accented letter outside the Turkish alphabet as its base letter ("José" -> "jose", "Zoë" -> "zoe"), like
// bin/sahip.py _kucuk; the Turkish letters keep their own vowel (ö, ü, ı)
const tabanHarf = (c) => (TURK_HARFLERI.includes(c) || !/\p{L}/u.test(c) ? c : c.normalize('NFKD').replace(/\p{M}/gu, ''));

// name + apostrophe + the case suffix by vowel harmony: the last vowel picks a/e (ı/i/u/ü), a final vowel takes the
// buffer letter (y, n), a final voiceless consonant turns d into t; a proper name is never softened (Murat'a).
export function sahipEk(ad, hal) {
  if (!SAHIP_HALLERI.includes(hal)) throw new Error(`unknown case ${hal}`);
  const name = String(ad);
  // English (ofis.json dil, web/i18n.js): the bare name, the genitive "Name's" (bin/sahip.py ek_dilde)
  if (aktifDil() === 'en') return hal === 'in' ? `${name}'s` : name;
  const kucuk = name.replace(/I/g, 'ı').replace(/İ/g, 'i').toLowerCase().replace(/â/g, 'a').replace(/î/g, 'i').replace(/û/g, 'u');
  const harfler = [...[...kucuk].map(tabanHarf).join('')].filter((c) => /\p{L}/u.test(c));
  const sesliler = harfler.filter((c) => SESLI.includes(c));
  const sonSesli = sesliler.length ? sesliler[sesliler.length - 1] : 'e';
  const son = harfler.length ? harfler[harfler.length - 1] : 'e';
  const a = KALIN.includes(sonSesli) ? 'a' : 'e';
  const i = DORTLU[sonSesli];
  const sesliBiter = SESLI.includes(son);
  const d = SERT.includes(son) ? 't' : 'd';
  const ek = { e: (sesliBiter ? 'y' : '') + a, in: (sesliBiter ? 'n' : '') + i + 'n', den: d + a + 'n',
    i: (sesliBiter ? 'y' : '') + i, de: d + a }[hal];
  return `${name}'${ek}`;
}

let sahipSu = SAHIP_VARSAYILAN;
// /api/state.sahip ({adi, …}) or a plain name; anything else keeps the current name. Returns the name in use.
export function sahipAyarla(v) {
  const ad = v && typeof v === 'object' ? v.adi : v;
  if (typeof ad === 'string' && ad.trim() && ad.trim().length <= 40 && !/[[\]()·\n\r<>`#|]/.test(ad)) sahipSu = ad.trim();
  return sahipSu;
}
// Under node only (the tests): OFIS_SAHIP_ADI fills in the name like bin/sahip.py ENV; a browser has no `process`.
sahipAyarla(typeof process !== 'undefined' && process && process.env ? process.env.OFIS_SAHIP_ADI : undefined);
export const sahipAdi = () => sahipSu;
// the current name with a case suffix ("Ayşe'nin"); no hal = the bare name
export const sahip = (hal) => (hal ? sahipEk(sahipSu, hal) : sahipSu);

export const UNVAN = {
  haiku: { unvan: 'Stajyer', rank: 1 },
  sonnet: { unvan: 'Uzman', rank: 2 },
  opus: { unvan: 'Kıdemli', rank: 3 },
  fable: { unvan: 'Genel Müdür', rank: 4 }, // plan "Sonraki iş (9)": the former Müdür
  codex: { unvan: 'Dış denetçi', rank: 5 },
  ceo: { unvan: 'CEO', rank: 6 },
};
const BILINMEYEN = { unvan: 'Ajan', rank: 0 };
const AILELER = ['haiku', 'sonnet', 'opus', 'fable', 'codex'];

// The resident staff (kadro): one character per Claude model, idle in the shared lounge while no job of that model
// is in the office (the CEO is separate; the auditors have their own desks).
export const KADRO = ['haiku', 'sonnet', 'opus', 'fable'];
// a lounge seat per model; the Müdür (fable) idles at its own office desk and uses its lounge seat only when that
// desk is taken
const LOUNGE = KADRO;
export const MUDUR_MASASI = 'mudur-odasi-masa';
const kadroYeri = (f) => (f === 'fable' ? MUDUR_MASASI : `ortak-alan-${f}`);
const KADRO_ADI = { haiku: 'Haiku', sonnet: 'Sonnet', opus: 'Opus', fable: 'Fable' };
export const KUTLAMA_MS = 30000; // ✓ at the desk
export const CIKIS_MS = 60000; // then the walk to the lift, until 60 s after bitti
export const TASIMA_MS = 40000; // an escalated job: the old actor carries the file this long, then leaves
export const TIKANDI_GORUNUR_MS = 2 * 3600000; // a stuck job whose session is gone stays at its desk this long
export const YARDIMCI_EN_COK = 4;
export const DEFAULT_SAHNE = { ogle: '12:00-13:00', saat_dilimi: 'Europe/Istanbul' };
const FIXED_OFFSET_MS = 3 * 3600000; // the server's fallback zone (UTC+3) when the zone data is unavailable
// The Çaycı's routine (no real event to serve): a tea loop of CAYCI_TUR_MS — most of it brewing at the counter, then two
// stops on the common corridors (seeded per loop), each long enough to walk there and stand.
export const CAYCI_TUR_MS = 6 * 60000;
export const CAYCI_KALIS_MS = 10000; // a tea delivery: this long beside the desk after arriving
export const EN_UZUN_MIN_MS = 10 * 60000; // "en uzun çalışan": only a job that has been working at least this long
export const EN_UZUN_ARA_MS = 20 * 60000; // and at most one such tea round in this long
// The CEO's free time (owner decision 2026-11-12): CEO_ADIM_MS slots, each seeded to its desk / a round / a break / sleep with
// CEO_PAYLARI (percent; sleep only when dormant, else the desk). A round's stops each last the walk there plus
// CEO_DURAK_KALIS_MS (a round may run into the next slots); outside the office hours (mesai) a dormant CEO sleeps.
export const CEO_ADIM_MS = 150000;
export const CEO_PAYLARI = { masa: 30, tur: 25, mola: 25, uyku: 20 };
export const CEO_MOLALARI = ['cay', 'sigara', 'oyun'];
export const CEO_DURAK_KALIS_MS = 5000;
// the secretary: one trip to the CEO's door per new decision (a note not seen in the previous tick): the walk there
// plus SEKRETER_KALIS_MS at the door, then the walk back to reception before the next trip
export const SEKRETER_KALIS_MS = 6000;
// the guard: when someone new comes out of the lift he walks to the greeting spot and stays GUVENLIK_KALIS_MS there
export const GUVENLIK_KALIS_MS = 6000;
// idle life (molaPlani): every MOLA_ADIM_MS an idle actor picks its next break, seeded by its id and its own slot (each
// actor's slots start at its own seeded phase, so nobody switches in step with the others)
export const MOLA_ADIM_MS = 180000;
export const MOLA_CAY_MS = 25000; // a tea break: this long at the counter, then at a lounge table with the cup
export const MOLA_ETKINLIKLERI = ['dinlenme', 'cay', 'oyun', 'yuruyus', 'sigara', 'wc', 'uyku', 'spor', 'masaj'];
export const SPOR_MS = 110000; // a workout: this long on a machine or a mat, then (sometimes) the shower
export const WC_ICERDE_MS = 45000; // a restroom visit: inside until this far into the slot (the walk included),
export const WC_LAVABO_MS = 75000; // then at the sink until this, then back at its seat
export const UYKU_DILIM = [4, 6]; // a nap, once begun, holds its bed for 4-6 break slots (12-18 minutes)
export const MOLA_UZAK = 130; // a break place farther than this (walk length) from the actor's own seat is not chosen
// a nap needs a long idle: a kadro with no work of its model, an idle session, an idle auditor (molaPlani `uzun`)
export const KADRO_UYKU_MS = 30 * 60000;
export const OTURUM_UYKU_MS = 15 * 60000;
// Office hours (owner decision 2026-11-12, optional): state.sahne.mesai "HH:MM-HH:MM" in the office zone (ofis.json
// ofis_sahnesi.mesai; '' or 'yok' = none). Outside them the office staff are home (each with a seeded arrival and leave
// time within MESAI_SAPMA_DK of the edges: in and out through the lift), nobody plays, smokes or works out, idle agents
// rest or nap and a dormant CEO sleeps.
export const DEFAULT_MESAI = '08:30-18:30';
export const MESAI_SAPMA_DK = 20;
export const EVE_GIDIS_MS = 90000; // a leaving staff member walks to the lift this long, then is gone
// The cues of real events (B4, owner decision 2026-11-12), each short and carried by a tiny prop (the folder / a symbol):
export const KONTROL_ISARET_MS = 20000; // the first Kontrol failure: a "✗" at the desk this long
export const TESLIM_PENCERE_MS = 60000; // a new job: the free CEO carries it over within this long after it was added
export const IS_KALIS_MS = 5000; // a carried file: this long at the target after the walk
export const TOPLANTI_MS = 20000; // plan 7: the project sorumlusu's short meeting at a planning job's desk
export const TOPLANTI_PENCERE_MS = 180000; // … when the planning job started within this long
const INCELEME_ADIMLARI = new Set(['kod-inceleme', 'plan-inceleme']);
const FINAL = new Set(['bitti', 'tikandi', 'iptal', 'basarisiz']);

// A family's display name for labels, as on the side panel ("fable" -> "Fable"; the owner, 2026-11-11).
export function aileAdi(fam) {
  const f = String(fam || '');
  return f ? f[0].toUpperCase() + f.slice(1) : '';
}

export function modelAilesi(model) {
  if (typeof model !== 'string') return '';
  const low = model.toLowerCase();
  return AILELER.find((f) => low.includes(f)) || '';
}

// The tier defaults of ofis.json (`tiers`): a job whose model is not known yet (e.g. a queued one) takes its tier's.
export const KATMAN_MODEL = { kolay: 'haiku', genel: 'sonnet', kod: 'opus', inceleme: 'opus', planlama: 'fable' };

// A job's model: its own (server record), else its tier's default, else ''.
// katmanlar = /api/state.katmanlar (bin/state.py: the effective mapping — {genel: {tier: model}, projeler: {proje: {tier:
// model}}}, project overrides and running pilots included); without it the global defaults above.
export function isModeli(task, session = null, katmanlar = null) {
  const own = (session && session.model) || (task && task.model) || '';
  if (modelAilesi(own)) return own;
  const tier = (session && session.tier) || (task && task.tier) || '';
  const proje = (task && task.project) || (session && session.project) || '';
  return katmanModeli(katmanlar, proje, tier) || own;
}

// The model a tier maps to for a project: the project's effective entry, else the global one, else KATMAN_MODEL.
export function katmanModeli(katmanlar, proje, tier) {
  const k = katmanlar && typeof katmanlar === 'object' ? katmanlar : {};
  const own = k.projeler && k.projeler[proje] && k.projeler[proje][tier];
  const gen = k.genel && k.genel[tier];
  return (typeof own === 'string' && own) || (typeof gen === 'string' && gen) || KATMAN_MODEL[tier] || '';
}

export function unvanOf(model, fallback = BILINMEYEN) {
  return UNVAN[modelAilesi(model)] || fallback;
}

// plan "Sonraki iş (9)" step 2 (owner decision 2026-11-13): a job's specialisation (bin/uzmanlik.py, roller/*.json `baslik`;
// a test keeps this map equal to the profiles). The seniority stays with the model; the role a job shows is
// "<kıdem> <uzmanlık>" — "Kıdemli Backend", "Stajyer Mobil", "Kıdemli Tester". genel, an unknown key and the Genel
// Müdür (fable) add no word.
export const UZMANLIK_BASLIK = { backend: 'Backend', ui: 'UI', mobil: 'Mobil', test: 'Tester', analiz: 'Analist',
  guvenlik: 'Güvenlik', genel: 'Genel' };
export const UZMANLIK_SIRA = Object.keys(UZMANLIK_BASLIK);
const UZMANLIK_EKLI = new Set(['haiku', 'sonnet', 'opus']);
export function uzmanlikEki(model, uzmanlik) {
  const fam = modelAilesi(model);
  const key = typeof uzmanlik === 'string' ? uzmanlik : '';
  return UZMANLIK_EKLI.has(fam) && key !== 'genel' && Object.prototype.hasOwnProperty.call(UZMANLIK_BASLIK, key)
    ? UZMANLIK_BASLIK[key] : '';
}
export function rolMetni(model, uzmanlik, fallback = BILINMEYEN) {
  const u = unvanOf(model, fallback).unvan;
  const ek = uzmanlikEki(model, uzmanlik);
  return ek ? `${u} ${ek}` : u;
}
// A job's (or its session's) specialisation for display.
export const isUzmanligi = (t, s = null) => String((t && t.uzmanlik) || (s && s.uzmanlik) || '');

// --- the external auditors (dış denetçi heyeti, bin/denetci.py): Codex and the free reviewers ---

// Display names of the reviewers (state.modeller model = the reviewer's name in ofis.json); others are capitalised.
export const DENETCI_ADI = { codex: 'Codex', glm: 'GLM', deepseek: 'DeepSeek', antigravity: 'Antigravity', guvenlik: 'Güvenlik' };
// The security reviewer (bin/denetci.py SECURITY): a Claude call, so not a "Dış denetçi" and never free.
export const GUVENLIK = 'guvenlik';
export const GUVENLIK_UNVAN = 'Güvenlik denetçisi';
// its floor label (the owner, 2026-11-12: short labels; plan "Sonraki iş (9)": the IT güvenlik uzmanı of the Sunucu odası
// stands for the security reviewer's runs)
export const GUVENLIK_KISA = 'IT güvenlik uzmanı';
const DENETCI_AD = /^[a-z]{2,12}$/; // bin/denetci.py NAME

export function denetciAdi(ad) {
  const s = String(ad || '');
  return DENETCI_ADI[s] || (s ? s[0].toUpperCase() + s.slice(1) : '');
}

// A free reviewer's model row: unvan "Dış denetçi", a valid reviewer name that is not Codex nor a Claude family.
export function ucretsizDenetciMi(m) {
  return !!m && typeof m === 'object' && m.unvan === UNVAN.codex.unvan && typeof m.model === 'string' &&
    m.model !== 'codex' && m.model !== GUVENLIK && DENETCI_AD.test(m.model) && !modelAilesi(m.model);
}

// The security reviewer's model row (bin/state.py: model 'guvenlik', unvan "Güvenlik denetçisi", ajan_modeli).
export function guvenlikSatiriMi(m) {
  return !!m && typeof m === 'object' && m.model === GUVENLIK && m.unvan === GUVENLIK_UNVAN;
}

// The auditors with a desk: Codex always first, then the free reviewers in the order of the list (model rows or
// plain names), each once, and the security reviewer last when it has a row.
export function denetciListesi(list) {
  const out = ['codex'];
  let guvenlik = false;
  for (const x of Array.isArray(list) ? list : []) {
    const ad = typeof x === 'string' ? x : (ucretsizDenetciMi(x) || guvenlikSatiriMi(x) ? x.model : '');
    if (ad === GUVENLIK) { guvenlik = true; continue; }
    if (ad && DENETCI_AD.test(ad) && !modelAilesi(ad) && !out.includes(ad)) out.push(ad);
  }
  if (guvenlik) out.push(GUVENLIK);
  return out;
}

// The desk node of an auditor ('denetci-masa' stays Codex's).
export function denetciMasasi(ad) {
  return ad === 'codex' ? 'denetci-masa' : `denetci-masa-${ad}`;
}
// The auditors with a desk in the auditors' room: every one but the security reviewer (plan "Sonraki iş (9)": its runs
// show at the IT güvenlik desk in the Sunucu odası, as the IT güvenlik uzmanı).
export const odaDenetcileri = (list) => (Array.isArray(list) ? list : []).filter((ad) => ad !== GUVENLIK);

// The job that has been working longest without a break: status 'calisiyor' with a readable start, the earliest start
// first (ties by note); with `now` and `enAz` (ms) only a job working at least that long. null when none. Used by the tea
// server (tea to this desk) and the Çaycı's card.
export function enUzunCalisan(tasks, tz = DEFAULT_SAHNE.saat_dilimi, ofsetDk = null, now = null, enAz = 0) {
  let best = null;
  let bestT = Infinity;
  const ms = now === null ? null : nowMs(now);
  for (const t of Array.isArray(tasks) ? tasks : []) {
    if (!t || t.status !== 'calisiyor') continue;
    const s = zamanMs(t.started, tz, ofsetDk);
    if (s === null || (ms !== null && ms - s < enAz)) continue;
    if (s < bestT || (s === bestT && String(t.note) < String(best.note))) { best = t; bestT = s; }
  }
  return best;
}

// A seat for `id` from `seats` (a stable per-actor seed; a taken seat moves on to the next free one): the first seat from
// hash(id) on for which free(seat) holds; it is added to `taken`. null when none is free.
export function sabitKoltuk(id, seats, free = () => true, taken = null) {
  const n = seats.length;
  if (!n) return null;
  const start = hash(`${id}:koltuk`) % n;
  for (let i = 0; i < n; i++) {
    const c = seats[(start + i) % n];
    if (free(c)) { if (taken) taken.add(c); return c; }
  }
  return null;
}

// The actors that came in through the lift since the previous tick (ids not in prev): jobs, sessions, kadro, the CEO
// and staff arriving for their office hours — never the auditors (they appear at their desk), a helper (it appears
// beside its parent), a hand-over (`devral`: the same body walks on), one that is leaving or at home, or a "+N". []
// without a previous tick (the first render places everyone).
// The staff walking back in from the Otel in the morning (in the previous tick at the hotel, now at work) count as
// arrivals too: they come in through the lobby's entrance.
export function asansordenGelenler(actors, prev) {
  if (!Array.isArray(prev) || !prev.length) return [];
  const ids = new Set(prev.map((a) => a && a.id));
  const otelden = new Set(prev.filter((a) => a && a.otel).map((a) => a.id));
  return (Array.isArray(actors) ? actors : []).filter((a) => a && a.id && (!ids.has(a.id) || (otelden.has(a.id) && !a.otel)) &&
    a.tur !== 'alt-ajan' && a.tur !== 'ozet' && !a.denetci && !a.hakem && !a.devral && !a.cikis && a.poz !== 'evde' &&
    a.yer !== 'asansor');
}

// How long the jobs of a model family ran today (ms; started today, until their finish or now), in the office zone.
export function calismaSuresi(tasks, fam, ms, tz = DEFAULT_SAHNE.saat_dilimi, ofsetDk = null) {
  const p = parts(ms, tz);
  const gun = `${p.y}-${p2(p.mo)}-${p2(p.d)}`;
  let sum = 0;
  for (const t of Array.isArray(tasks) ? tasks : []) {
    if (!t || (fam && modelAilesi(isModeli(t)) !== fam)) continue;
    const s = zamanMs(t.started, tz, ofsetDk);
    if (s === null) continue;
    const sp = parts(s, tz);
    if (`${sp.y}-${p2(sp.mo)}-${p2(sp.d)}` !== gun) continue;
    const f = zamanMs(t.finished, tz, ofsetDk);
    const end = f !== null ? Math.min(f, ms) : (FINAL.has(t.status) ? s : ms);
    if (end > s) sum += end - s;
  }
  return sum;
}

// The doctor's (and the psychologist's) visits: prevDr = its actor of the previous tick ({yer, vakalar: [ids], ziyaret:
// {hedefler: [{yer, son}]}}), cases = the agents stuck or red-marked now with the spot to visit ({id, yer}), sure(from,
// to) = the walk's time (ms). One visit per case that is new since the previous tick, in order: each lasts the walk
// there (from the previous visit, else from where the doctor stood) plus DOKTOR_KALIS_MS; none on the first tick.
// Returns {vakalar, ziyaret | null, hedef | null}.
export function doktorZiyareti(prevDr, cases, ms, sure = () => 0) {
  const ids = cases.map((c) => c.id);
  const once = prevDr && Array.isArray(prevDr.vakalar) ? new Set(prevDr.vakalar) : null;
  let z = prevDr && prevDr.ziyaret && Array.isArray(prevDr.ziyaret.hedefler)
    ? { hedefler: prevDr.ziyaret.hedefler.filter((h) => h && h.yer && Number.isFinite(h.son)).map((h) => ({ ...h })) } : null;
  if (z && (!z.hedefler.length || ms >= z.hedefler[z.hedefler.length - 1].son)) z = null;
  if (once) {
    for (const c of cases) {
      if (once.has(c.id) || !c.yer) continue;
      const son = z ? z.hedefler[z.hedefler.length - 1] : null;
      const from = son ? son.yer : (prevDr && prevDr.yer) || null;
      const bas = son ? son.son : ms;
      const h = { yer: c.yer, son: bas + sure(from, c.yer) + DOKTOR_KALIS_MS };
      if (z) z.hedefler.push(h); else z = { hedefler: [h] };
    }
  }
  const cur = z ? z.hedefler.find((h) => ms < h.son) || null : null;
  return { vakalar: ids, ziyaret: z, hedef: cur ? cur.yer : null };
}

// The hand-over chain of a new job (plan "Sonraki iş (9)", carried on the CEO actor as `teslim`): when the CEO hands the
// file to the first receiver (the whole walk when nobody receives it).
export const teslimIlk = (t) => (t && Array.isArray(t.zincir) && t.zincir.length ? t.t[0] : t ? t.bitis : 0);
// Receiver `id`'s part of the chain at ms: null (not in it, or its part is over); {bekle: true, metin, gorevde} while the
// file has not reached it (it waits at its desk — "yeni işi bekliyor", then "yeni işi teslim alıyor" once the file is on
// its way to it; on duty, so one called in outside its office hours counts as in the office); {yer, metin,
// dosya: true} while it carries the file to the next receiver ("işi teslim ediyor") or to the job's robot ("işi masaya
// götürüyor").
export function teslimRolu(teslim, id, ms) {
  if (!teslim || !Array.isArray(teslim.zincir) || !Array.isArray(teslim.t) || !(ms < teslim.bitis)) return null;
  const k = teslim.zincir.findIndex((z) => z && z.id === id);
  if (k < 0) return null;
  if (ms < teslim.t[k]) {
    const sirada = k === 0 || ms >= teslim.t[k - 1];
    return { bekle: true, metin: sirada ? 'yeni işi teslim alıyor' : 'yeni işi bekliyor', gorevde: true };
  }
  const sonraki = teslim.zincir[k + 1] || null;
  if (sonraki && ms >= teslim.t[k + 1]) return null;
  return { yer: sonraki ? sonraki.ara : teslim.hedef, metin: sonraki ? 'işi teslim ediyor' : 'işi masaya götürüyor', dosya: true };
}

// The secretary's trips: prevSek = her actor of the previous tick ({karar_notlari, tasima: {bas, adet, ilk, gidis,
// donus}}), notlar = the notes of the decisions waiting now, sure = {ilk: the walk from where she stood to the CEO's door,
// gidis: from reception, donus: back} (ms, SEKRETER_KALIS_MS added here). One trip per note not seen in the previous
// tick (several at once queue up); none on the first tick and none while nothing waits. Returns {tasima | null, kapida}.
// Where a running trip (sekreterTasimasi's tasima) stands at ms: {kapida, kapiSonu (when the current door leg ends, or
// null when not at the door), baslayan (trips begun so far, ≤ adet)}. Used at a shift change: the outgoing Sekreter
// finishes the door leg she is on, the trips not begun yet go to the one coming on shift, who starts after the door is free.
export function tasimaAni(tasima, ms) {
  const t = tasima && Number.isFinite(tasima.bas) ? ms - tasima.bas : -1;
  if (t < 0) return { kapida: false, kapiSonu: null, baslayan: 0 };
  if (t < tasima.ilk) return { kapida: true, kapiSonu: tasima.bas + tasima.ilk, baslayan: 1 };
  const r = t - tasima.ilk - tasima.donus;
  if (r < 0) return { kapida: false, kapiSonu: null, baslayan: 1 };
  const dongu = tasima.gidis + tasima.donus;
  const j = Math.floor(r / dongu);
  const baslayan = Math.min(tasima.adet, j + 2);
  const kapida = baslayan === j + 2 && r % dongu < tasima.gidis;
  return { kapida, kapiSonu: kapida ? tasima.bas + tasima.ilk + tasima.donus + j * dongu + tasima.gidis : null, baslayan };
}
export function sekreterTasimasi(prevSek, notlar, ms, sure = {}) {
  const list = (Array.isArray(notlar) ? notlar : []).map(String);
  const p = prevSek && prevSek.tasima;
  let tasima = p && Number.isFinite(p.bas) && p.adet > 0 && [p.ilk, p.gidis, p.donus].every(Number.isFinite)
    ? { ...p } : null;
  const bitis = (t) => t.bas + t.ilk + t.donus + (t.adet - 1) * (t.gidis + t.donus);
  if (tasima && ms >= bitis(tasima)) tasima = null;
  const onceki = prevSek && Array.isArray(prevSek.karar_notlari) ? new Set(prevSek.karar_notlari) : null;
  const yeni = onceki ? list.filter((n) => !onceki.has(n)).length : 0;
  if (yeni) {
    if (tasima) tasima.adet += yeni;
    else {
      const k = SEKRETER_KALIS_MS;
      tasima = { bas: ms + Math.max(0, sure.bekle || 0), adet: yeni, ilk: (sure.ilk ?? sure.gidis ?? 15000) + k, gidis: (sure.gidis ?? 15000) + k,
        donus: sure.donus ?? 15000 };
    }
  }
  if (!list.length) tasima = null;
  let kapida = false;
  if (tasima) {
    const t = ms - tasima.bas;
    if (t < 0) kapida = false; // waiting at reception until the door is free
    else if (t < tasima.ilk) kapida = true;
    else {
      const r = t - tasima.ilk - tasima.donus;
      kapida = r >= 0 && r % (tasima.gidis + tasima.donus) < tasima.gidis;
    }
  }
  return { tasima, kapida };
}

// FNV-1a: the only source of "randomness" (stable for the same input).
export function hash(text) {
  let h = 0x811c9dc5;
  const s = String(text);
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

function kisa(text, max = 60) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

function notAdi(note) {
  return String(note || '').replace(/^\[\[|\]\]$/g, '').replace(/\.md$/, '');
}

// --- time (office zone, never the browser's) ---

const formatters = new Map();
function parts(epoch, tz) {
  let f = formatters.get(tz);
  if (f === undefined) {
    try {
      f = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit',
        day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) {
      f = null;
    }
    formatters.set(tz, f);
  }
  if (f === null) { // fixed UTC+3 like the server
    const d = new Date(epoch + FIXED_OFFSET_MS);
    return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(),
      mi: d.getUTCMinutes(), s: d.getUTCSeconds() };
  }
  // formatToParts is slow (it was half of every niyetler tick): the zone's UTC offset is read once per quarter hour
  // (every real zone changes its offset on a quarter-hour boundary) and the wall clock is plain arithmetic from it
  const q = Math.floor(epoch / QUARTER_MS);
  let offs = offsetCache.get(tz);
  if (!offs || offs.size > 20000) offsetCache.set(tz, offs = new Map());
  let off = offs.get(q);
  if (off === undefined) {
    const base = q * QUARTER_MS, p = {};
    for (const { type, value } of f.formatToParts(new Date(base))) p[type] = Number(value);
    off = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute, p.second) - base;
    offs.set(q, off);
  }
  const d = new Date(epoch + off);
  return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(),
    mi: d.getUTCMinutes(), s: d.getUTCSeconds() };
}
const QUARTER_MS = 15 * 60000;
const offsetCache = new Map();

function offsetMs(epoch, tz) {
  const base = Math.floor(epoch / 1000) * 1000;
  const p = parts(base, tz);
  return Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s) - base;
}

// `now` is required: a missing or unreadable time throws (a silent 0 would put 1970 on the screen).
export function nowMs(now) {
  let t = NaN;
  if (now instanceof Date) t = now.getTime();
  else if (typeof now === 'number') t = now;
  else if (typeof now === 'string') t = zamanMs(now, 'UTC') ?? NaN;
  if (!Number.isFinite(t)) throw new TypeError(`ofis-davranis: geçersiz zaman: ${String(now)}`);
  return t;
}

// ISO with an offset (+03:00, +0300, Z; fractions allowed) -> that instant. A naive "YYYY-MM-DDTHH:MM[:SS]" (the job
// notes' stamps, written in the server's local time) is read with `ofsetDk` = the server's UTC offset in minutes
// (state.sahne.sunucu_utc_ofset_dk) when given, else as a wall clock in the office zone tz. null when unreadable.
export function zamanMs(value, tz = DEFAULT_SAHNE.saat_dilimi, ofsetDk = null) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || !value) return null;
  const m = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?(Z|([+-])(\d{2}):?(\d{2}))?$/);
  if (!m) return null;
  const frac = m[7] ? Math.floor(Number(`0.${m[7]}`) * 1000) : 0;
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) + frac;
  if (Number.isNaN(wall)) return null;
  if (m[8] === 'Z') return wall;
  if (m[8]) return wall - (m[9] === '-' ? -1 : 1) * (Number(m[10]) * 60 + Number(m[11])) * 60000;
  if (Number.isFinite(ofsetDk)) return wall - ofsetDk * 60000;
  let epoch = wall - offsetMs(wall, tz);
  epoch = wall - offsetMs(epoch, tz); // the offset at the instant itself (DST edges)
  return epoch;
}

export function ofisSaati(now, tz = DEFAULT_SAHNE.saat_dilimi) {
  const p = parts(nowMs(now), tz);
  return { yil: p.y, ay: p.mo, gun: p.d, saat: p.h, dakika: p.mi };
}

function dakikaOf(text) {
  const m = String(text || '').match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

export function ogleMi(now, sahne) {
  return ogleDakikasi(now, sahne) !== null;
}

// Inside the lunch window: {gecen: minutes since it began, sure: its length in minutes, gun: the office date (seed)};
// else null.
function ogleDakikasi(now, sahne) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const [a, b] = String(s.ogle || '').split('-');
  let start = dakikaOf(a);
  let end = dakikaOf(b);
  if (start === null || end === null) {
    [start, end] = DEFAULT_SAHNE.ogle.split('-').map(dakikaOf);
  }
  const t = ofisSaati(now, s.saat_dilimi);
  const cur = t.saat * 60 + t.dakika + (nowMs(now) % 60000) / 60000;
  const sure = (end - start + 1440) % 1440; // equal start and end: an empty window (no lunch)
  const gecen = (cur - start + 1440) % 1440;
  if (!(gecen < sure)) return null;
  // the seed's date is the day the current window began (yesterday's, after midnight in an overnight window), so one
  // window has one seeded plan
  const g = ofisSaati(nowMs(now) - gecen * 60000, s.saat_dilimi);
  return { gecen, sure, gun: `${g.yil}-${g.ay}-${g.gun}` };
}

// The owner, 2026-11-12: nobody sits in the canteen for the whole lunch hour. Each one eats for a seeded part of it —
// OGLE_YEMEK_DK minutes (20-35 of a 60-minute window, scaled to its length), most starting in its first minutes
// (eight in ten start at minute 0-4), the others later (minute 20-25) — and spends the rest on ordinary
// idle life (molaPlani / personelRotasi). True while `id` eats now; false outside the lunch hour; seeded by id and
// the office date: deterministic, no Math.random.
export const OGLE_YEMEK_DK = [20, 35];
export function ogleYemekte(id, now, sahne) {
  const o = ogleDakikasi(now, sahne);
  if (!o) return false;
  const k = o.sure / 60;
  const h = hash(`${id}:ogle:${o.gun}`);
  const bas = (h % 10 < 8 ? (h >>> 4) % 5 : 20 + ((h >>> 4) % 6)) * k;
  const sure = (OGLE_YEMEK_DK[0] + ((h >>> 8) % (OGLE_YEMEK_DK[1] - OGLE_YEMEK_DK[0] + 1))) * k;
  return o.gecen >= bas && o.gecen < Math.min(o.sure, bas + sure);
}

// --- meals (owner decision 2026-11-14): breakfast, lunch and dinner in the Yemekhane, cooked and served around the clock ---
// The canteen's meal windows of the day (minutes of the office day): on a work day breakfast from half an hour before
// the office hours until 45 minutes into them (the staff eat right after they arrive, the agents after they wake),
// lunch in sahne.ogle (as before) and dinner 19:00–20:00; on a weekend or a holiday breakfast 09:00–10:00, lunch
// 12:30–13:30 and the same dinner. Without office hours (the demo): the lunch window only, as before.
export const KAHVALTI_DK = [15, 20]; // a breakfast lasts this long (seeded per person)
export const TATIL_KAHVALTI = [540, 600];
export const TATIL_OGLE = [750, 810];
export const AKSAM_YEMEGI = [1140, 1200];
export const OGUN_METNI = { kahvalti: 'kahvaltı ediyor', ogle: 'öğle yemeğinde', aksam: 'akşam yemeğinde' };
// the shift teams on duty eat one after another, never two at once (their posts are never all empty): the order and
// the length of each one's turn (minutes) at breakfast (from the day shift's start on a work day — the morning
// handover —, 09:00 on a day off) and at dinner (19:00)
export const NOBET_SOFRA_SIRASI = ['sekreter', 'sunucu', 'guvenlik', 'yemekhane', 'asci'];
export const NOBET_SOFRA_DK = { kahvalti: 12, aksam: 12 };
export function ogunPencereleri(now, sahne) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const m = mesaiAraligi(s);
  const [a, b] = String(s.ogle || '').split('-');
  let og = [dakikaOf(a), dakikaOf(b)];
  if (og[0] === null || og[1] === null) og = DEFAULT_SAHNE.ogle.split('-').map(dakikaOf);
  if (!m) return [{ tur: 'ogle', bas: og[0], son: og[1] }];
  if (!isGunuMu(nowMs(now), s)) {
    return [{ tur: 'kahvalti', bas: TATIL_KAHVALTI[0], son: TATIL_KAHVALTI[1] }, { tur: 'ogle', bas: TATIL_OGLE[0], son: TATIL_OGLE[1] },
      { tur: 'aksam', bas: AKSAM_YEMEGI[0], son: AKSAM_YEMEGI[1] }];
  }
  return [{ tur: 'kahvalti', bas: Math.min(m[0] - 30, VARDIYALAR[1].bas), bas_ajan: m[0], son: m[0] + 45 },
    { tur: 'ogle', bas: og[0], son: og[1] }, { tur: 'aksam', bas: AKSAM_YEMEGI[0], son: AKSAM_YEMEGI[1] }];
}
// The canteen's meal now (or `onceDk` minutes from now): {tur, gecen, sure} or null.
export function yemekPenceresi(now, sahne, onceDk = 0) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const ms = nowMs(now) + onceDk * 60000;
  const cur = gununDakikasi(ms, s.saat_dilimi);
  for (const p of ogunPencereleri(ms, s)) {
    if (cur >= p.bas && cur < p.son) return { tur: p.tur, gecen: cur - p.bas, sure: p.son - p.bas };
  }
  return null;
}
// The meal one person eats now: 'kahvalti' | 'ogle' | 'aksam' | null. Seeded by id and the office date (no
// Math.random). kim: 'ajan' (the CEO, the kadro, the auditors, the idle sessions: breakfast after waking, lunch as
// before on a work day and 12:30–13:30 on a day off, dinner 19:00–20:00), 'personel' (the day-hours staff: breakfast
// right after their own arrival `gel` on a work day, lunch as before, no dinner — they are at the Otel by then) or
// 'nobet' (the person on shift of team `ekip`: breakfast and dinner in its turn of NOBET_SOFRA_SIRASI, lunch as
// before — on a day off in the day-off window).
export function ogun(id, now, sahne, { kim = 'ajan', gel = null, ekip = '' } = {}) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const ms = nowMs(now);
  const m = mesaiAraligi(s);
  if (!m) return ogleYemekte(id, ms, s) ? 'ogle' : null;
  const cur = gununDakikasi(ms, s.saat_dilimi);
  const t = ofisSaati(ms, s.saat_dilimi);
  const gk = `${t.yil}-${t.ay}-${t.gun}`;
  const h = (k) => hash(`${id}:${k}:${gk}`);
  const icinde = (bas, dk) => cur >= bas && cur < bas + dk;
  const is = isGunuMu(ms, s);
  const sira = NOBET_SOFRA_SIRASI.indexOf(ekip);
  const kd = KAHVALTI_DK[0] + (h('kahvalti-sure') % (KAHVALTI_DK[1] - KAHVALTI_DK[0] + 1));
  if (kim === 'personel') {
    if (is && Number.isFinite(gel) && icinde(gel, kd)) return 'kahvalti';
  } else if (kim === 'nobet') {
    const b0 = is ? VARDIYALAR[1].bas : TATIL_KAHVALTI[0];
    if (sira >= 0 && icinde(b0 + sira * NOBET_SOFRA_DK.kahvalti, NOBET_SOFRA_DK.kahvalti)) return 'kahvalti';
  } else {
    const b0 = is ? m[0] : TATIL_KAHVALTI[0];
    if (icinde(b0 + (h('kahvalti') % 26), kd)) return 'kahvalti';
  }
  if (is) { if (ogleYemekte(id, ms, s)) return 'ogle'; }
  else if (kim !== 'personel' && icinde(TATIL_OGLE[0] + (h('ogle') % 26), 20 + (h('ogle-sure') % 16))) return 'ogle';
  if (kim === 'nobet') {
    if (sira >= 0 && icinde(AKSAM_YEMEGI[0] + sira * NOBET_SOFRA_DK.aksam, NOBET_SOFRA_DK.aksam)) return 'aksam';
  } else if (kim === 'ajan' && icinde(AKSAM_YEMEGI[0] + (h('aksam') % 21), 20 + (h('aksam-sure') % 6))) return 'aksam';
  return null;
}

const AYLAR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
// Turkish locative after a clock time, by its last spoken word: 16:30 -> 'da', 12:00 -> 'de', 13:00 -> 'te'.
const BIRLER = ['da', 'de', 'de', 'te', 'te', 'te', 'da', 'de', 'de', 'da'];
const ONLAR = ['da', 'da', 'de', 'da', 'ta', 'de'];
function saatEki(h, mi) {
  const n = mi === 0 ? h : mi;
  if (n === 0) return 'da';
  return n % 10 ? BIRLER[n % 10] : ONLAR[n / 10];
}
const p2 = (n) => String(n).padStart(2, '0');

// The possessive suffix after a number, by its last spoken word ("%90'ı", "%100'ü", "%50'si", "%85'i", "%96'sı"):
// the last vowel picks ı/i/u/ü, a word ending in a vowel takes the buffer "s". Integers ≥ 0; others get "'i".
const SON_KELIME = { 1: 'bir', 2: 'iki', 3: 'üç', 4: 'dört', 5: 'beş', 6: 'altı', 7: 'yedi', 8: 'sekiz', 9: 'dokuz',
  10: 'on', 20: 'yirmi', 30: 'otuz', 40: 'kırk', 50: 'elli', 60: 'altmış', 70: 'yetmiş', 80: 'seksen', 90: 'doksan' };
export function iyelikEki(n) {
  const x = Math.abs(Math.round(Number(n)));
  if (!Number.isFinite(x)) return 'i';
  const kelime = x === 0 ? 'sıfır' : x % 10 ? SON_KELIME[x % 10] : x % 100 ? SON_KELIME[x % 100]
    : x % 1000 ? 'yüz' : x % 1e6 ? 'bin' : x % 1e9 ? 'milyon' : 'milyar';
  const sesli = [...kelime].reverse().find((ch) => 'aıoueiöü'.includes(ch));
  const ek = { a: 'ı', ı: 'ı', o: 'u', u: 'u', e: 'i', i: 'i', ö: 'ü', ü: 'ü' }[sesli] || 'i';
  return 'aıoueiöü'.includes(kelime[kelime.length - 1]) ? `s${ek}` : ek;
}
// "%90'ı", "%100'ü": a percentage with its possessive suffix.
export const yuzdeMetni = (n) => `%${Math.round(Number(n))}'${iyelikEki(n)}`;

// "16:30'da döner" (same office day) or "12 Kas 09:00'da döner"; '' when unknown.
export function donusMetni(donus, now, tz = DEFAULT_SAHNE.saat_dilimi) {
  const t = zamanMs(donus, tz);
  if (t === null) return '';
  const a = parts(t, tz);
  const b = parts(nowMs(now), tz);
  const clock = `${p2(a.h)}:${p2(a.mi)}'${saatEki(a.h, a.mi)}`;
  const day = a.y === b.y && a.mo === b.mo && a.d === b.d ? '' : `${a.d} ${AYLAR[a.mo - 1]} `;
  return `${day}${clock} döner`;
}

// --- the floor plan ---

// Sizes (world units). A real office floor with breathing room, in two parts:
// - the common area (ortak alan bloğu, x 0..Wc): three rows with 4-wide corridors between them — the back row
//   (meeting room, the Müdür's office, the CEO's room in the middle, the external auditors), the middle row (the
//   Uzmanlar odası under the CEO's room: the quiet work room of the review work) and the front row (tea corner, the
//   shared lounge, canteen, the Revir). Its layout never depends on the number of projects (only the canteen grows
//   downwards); the auditor's room holds one desk per auditor, DENETCI_DX apart (a desk is about 2.3
//   wide), widens past ROOM_W for three or more and the common area widens with it so the CEO's room stays in its middle
//   with 2 units on each side.
// - one grid of bay-sized cells (the owner, 2026-11-12: a compact floor of about 1.3-1.8 : 1 instead of a long strip): rows
//   SATIR_ARA apart (row r at z = r * (TEAM_D + SATIR_ARA)), in two regions. The project wing (proje kanadı) right of
//   the common area behind a 4-wide spine corridor (omurga): columns TEAM_W apart, filled column by column away from
//   the spine; it has as many rows as the common area (with its canteen) is deep, at least TESIS_SATIR + 1, so a deeper
//   canteen gives the wing more rows and fewer columns. Under the common area (alt bölge, rows 3 and below): two
//   12-wide columns left of the canteen (off the left aisle) and one under the Revir (off the wing's corridors; 12
//   wide too, reaching a little past the Revir's left wall). The fixed facilities (TESIS_HUCRELERI) sit in cells of
//   the first TESIS_SATIR + 1 rows that never move; projects take the free wing cells, then the free 12-wide cells under the common area; the cells left over in
//   the used columns are empty reserved bays ("Boş ekip alanı · yeni proje"), so no cell stays bare. The bottom row's
//   project / reserved cells and the canteen reach the floor's edge. The lobby with the lift takes the wing's last two
//   cells of the bottom row: always the floor's front-right corner.
// The layout is drawn in these base units and then scaled by K (rooms, corridors and the spacing between places grow;
// the spots that belong to a piece of furniture — helpers and the "yan" spot beside a desk, the stools around a tea
// table — keep their distance to it).
// The owner, 2026-11-12: a roomier floor — K 1.3 -> 1.5, corridors (GAP) and the spine (OMURGA) 3.5 -> 4.
export const OLCU = { TEAM_W: 14, TEAM_GAP: 2, TEAM_D: 9.5, GAP: 4, TOP_D: 8, BOT_D: 8, MIN_W: 52, ROOM_W: 10,
  DESK_DX: 4, DESK_DZ: 2.4, DENETCI_DX: 3.6, K: 1.5, MUDUR_W: 7, SATIR_ARA: 3, TESIS_SATIR: 4, OMURGA: 4, UZMAN_W: 22,
  UZMAN_MASA: 6, DINLENME_W: 15, OYUN_W: 13, CAY_W: 11, SALON_W: 12, EN_BOY_MIN: 1.3, EN_AZ_SATIR: 6 };
// EN_AZ_SATIR (plan "Sonraki iş (9)", owner decision 2026-11-13): the floor has at least six rows, so the company's offices (the
// four managers, the QA and the Analist rooms) have fixed cells in rows 4 and 5 that never move when projects are added.
// The fixed facilities (the owner, 2026-11-12: they never move when projects are added). KANAT_TESISLERI lists them all;
// TESIS_HUCRELERI gives each its cell: [region, column, row] — 'kanat' = the wing (column 0 next to the spine), 'alt' =
// under the common area (column 0 under the tea corner, 1 under the lounge, 2 under the Revir). The
// Sigara odası (a terrace, not a facility bay) has the cell SIGARA_HUCRESI in front of the tea corner.
export const KANAT_TESISLERI = ['muhasebe', 'wc', 'idari', 'ik', 'sosyal', 'sosyal-studyo', 'revir', 'spor', 'dus',
  'psikolog', 'masaj', 'sunucu', 'arge', 'mudurluk-1', 'mudurluk-2', 'qa', 'analist'];
export const TESIS_HUCRELERI = {
  muhasebe: ['kanat', 0, 0], wc: ['kanat', 0, 1], idari: ['kanat', 0, 2],
  // the Sunucu odası (plan "Sonraki iş (5)", owner decision 2026-11-12): under İdari işler, next to the spine
  sunucu: ['kanat', 0, 3],
  ik: ['kanat', 1, 0], sosyal: ['kanat', 1, 1], 'sosyal-studyo': ['kanat', 1, 2],
  // the Ar-Ge odası (plan "Sonraki iş (6)", owner decision 2026-11-12): under the studio, in the wing's second column
  arge: ['kanat', 1, 3],
  // the company structure (plan "Sonraki iş (9)", owner decision 2026-11-13): two cells of manager offices under the Sunucu odası
  // and the Ar-Ge odası (Yazılım | IT, then QA | Analist), the QA odası below the first and the Analist odası across the
  // spine from it, under the Psikolog
  'mudurluk-1': ['kanat', 0, 4], 'mudurluk-2': ['kanat', 1, 4], qa: ['kanat', 0, 5], analist: ['alt', 2, 5],
  spor: ['alt', 1, 3], dus: ['alt', 1, 4], masaj: ['alt', 0, 4], psikolog: ['alt', 2, 4],
  // the Konferans salonu (plan "Sonraki iş (4)", owner decision 2026-11-12): under the Revir, next to the common area's front row
  konferans: ['alt', 2, 3],
  revir: ['on', 0, 0] }; // 'on': the front row's right end (where the lobby was before it moved to the corner)
// The conference hall: an announcement (state.duyuru, bin/duyuru.py son) gathers the idle kadro, the idle auditors and
// the off-duty staff on its chairs for DUYURU_MS after its delivery; the free CEO stands at the lectern; working agents
// stay at their desks with "duyuru alındı". In hafif nobody moves: only the screen shows the first line (salonEkrani).
export const DUYURU_MS = 60000;
// the gathering waits this much longer, so the listeners who walked over still sit for most of DUYURU_MS
export const DUYURU_TOPLANMA_MS = 45000;
export const SALON_KURSU = 'konferans-kursu';
export const SALON_SIRA = 3; // rows of chairs
export const SALON_KOLTUK = 6; // chairs per row
export const SIGARA_HUCRESI = ['alt', 0, 3];
// The agents' places on the terrace, in the order they are taken: the smoking corner first, then the benches, then
// the railing (sigara-yer-3 is the guard's, 4 the roaming staff's).
export const SIGARA_AJAN_YERLERI = [
  ...[0, 1, 2].map((i) => [`sigara-yer-${i}`, 'sigara', 'sigara molası']),
  ...[5, 6, 7, 8].map((i) => [`sigara-yer-${i}`, 'bekliyor', 'terasta oturuyor']),
  ['sigara-yer-9', 'bekliyor', 'terasta hava alıyor']];
// the office-type facilities: a desk for their staff NPC (sus:<key>) and the room's name
export const TESIS_ODALARI = { muhasebe: 'Muhasebe', idari: 'İdari işler', ik: 'İnsan kaynakları', revir: 'Revir',
  psikolog: 'Psikolog', masaj: 'Masaj odası', sunucu: 'Sunucu odası', arge: 'Ar-Ge odası' };
export const MUHASEBE_MASASI = 'muhasebe-masa';
// The company structure (plan "Sonraki iş (9)", owner decision 2026-11-13): the owner → CEO → Genel Müdür (the fable kadro) → four
// managers. The managers are staff NPCs (tur 'sus', gorevli 'mudur', informational, with office hours and a card), never a
// model session: the real work still runs through the tiers and the workflow steps, and each manager's card shows the
// real work in its area. hucre = the cell of its office (two offices per cell), oda = the office's name.
export const GENEL_MUDUR = 'Genel Müdür';
export const MUDURLUKLER = [
  { key: 'yazilim', ad: 'Yazılım Müdürü', departman: 'Yazılım', hucre: 'mudurluk-1', oda: 'Yazılım Müdürü odası',
    gorev: 'kod işlerini ve planlamayı yönetir; proje ekiplerinin (Stajyer · Uzman · Kıdemli) müdürüdür',
    ekip: ['Proje ekipleri: Stajyer · Uzman · Kıdemli', 'Uzmanlıklar: Backend · UI · Mobil', 'Proje sorumluları'] },
  { key: 'it', ad: 'IT Müdürü', departman: 'IT', hucre: 'mudurluk-1', oda: 'IT Müdürü odası',
    gorev: 'Sunucu odasını ve güvenliği yönetir; IT ekibi ile IT güvenlik uzmanı ona bağlıdır',
    ekip: ['IT ekibi: IT sorumlusu · 2 IT uzmanı (nöbetli)', 'IT güvenlik uzmanı (güvenlik denetçisi)'] },
  { key: 'qa', ad: 'QA Müdürü', departman: 'QA (Test)', hucre: 'mudurluk-2', oda: 'QA Müdürü odası',
    gorev: 'kod incelemelerini ve Kontrol çalıştırmalarını yönetir; QA odasının müdürüdür',
    ekip: ['QA odası: Stajyer Tester · Kıdemli Tester'] },
  { key: 'analist', ad: 'Analist Müdürü', departman: 'Analiz', hucre: 'mudurluk-2', oda: 'Analist Müdürü odası',
    gorev: 'plan incelemelerini yönetir; iş analistleri her projeye bakabilir',
    ekip: ['Analist odası: iş analistleri', 'Değerlendirme ekibi: gün sonu, 2 kişi (akşam penceresinde)'] },
];
// step 4 (bin/mudur.py): the manager card of /api/state.mudur_kararlari this manager (key) visits now — one it is
// looking at, or one it answered less than TOPLANTI_MS ago; null otherwise.
const MUDUR_KIMLIK = { 'yazilim-muduru': 'yazilim', 'qa-muduru': 'qa', 'analist-muduru': 'analist', 'it-muduru': 'it' };
export function mudurZiyareti(kararlar, key, ms, tz = DEFAULT_SAHNE.saat_dilimi, ofsetDk = null) {
  for (const k of Array.isArray(kararlar) ? kararlar : []) {
    if (!k || MUDUR_KIMLIK[k.mudur] !== key || !k.is) continue;
    if (k.durum === 'bakiyor') return k;
    const t = k.durum === 'cevapladi' ? zamanMs(k.cevaplandi, tz, ofsetDk) : null;
    if (t !== null && ms >= t && ms < t + TOPLANTI_MS) return k;
  }
  return null;
}
// The jobs a manager walks over to look at (owner decision 2026-11-18, "daha mantıklı"): the server's silent list
// (st.postoffice.silent: a working job's session idle over two minutes; a permission prompt is the owner's, not a
// manager's) and the stuck jobs (tikandi). Map note -> 'sessiz' | 'takildi'. Pure; real state only.
export function bakilacakIsler(st) {
  const out = new Map();
  const po = st && st.postoffice && typeof st.postoffice === 'object' ? st.postoffice : null;
  for (const x of po && Array.isArray(po.silent) ? po.silent : []) if (x && x.is && !x.izin) out.set(notAdi(x.is), 'sessiz');
  for (const t of Array.isArray(st && st.tasks) ? st.tasks : []) if (t && t.note && t.status === 'tikandi') out.set(notAdi(t.note), 'takildi');
  return out;
}
export const BAKIS_METNI = { sessiz: 'sessiz işe bakıyor', takildi: 'takılan işe bakıyor' };

// What a staff member at its desk says when it has no duty (owner decision 2026-11-18: real things, never filler): a
// short "masasında · …" from the state — a manager its department's open work (the Yazılım Müdürü also the busiest
// project), the doctor today's stuck jobs, the psychologist the jobs on a second Kontrol attempt, the İK the jobs at work,
// the Muhasebeci today's finished jobs, the İdari işler the schedules, a project sorumlusu its project's open jobs.
// `gorevli` as on the actor ('mudur' with `alan`, 'revir', 'psikolog', 'ik', 'muhasebe', 'idari', 'proje' with
// `proje`); 'masasında' when there is nothing real to say. Pure.
const ACIK_DURUMLAR = new Set(['baslatiliyor', 'calisiyor', 'kontrolde', 'incelemede', 'karar-bekliyor']);
export function masaSozu(gorevli, st, ms, { alan = '', proje = '' } = {}) {
  const s = st && typeof st === 'object' ? st : {};
  const tasks = (Array.isArray(s.tasks) ? s.tasks : []).filter((t) => t && t.note);
  const acik = tasks.filter((t) => ACIK_DURUMLAR.has(t.status) && !onayAdimi(t) && !argeIsi(t));
  const m = (x) => (x ? `masasında · ${x}` : 'masasında');
  if (gorevli === 'mudur') {
    if (alan === 'it') {
      const sv = s.sistem && typeof s.sistem === 'object' ? s.sistem : null;
      const ad = sv && { yesil: 'sistem rahat', sari: 'sistem yoğun', kirmizi: 'sistem çok yoğun' }[sv.seviye];
      return m(ad || '');
    }
    const is = acik.filter((t) => isDepartmani(t) === alan && (alan !== 'yazilim' || !planIsi(t)));
    const ad = { yazilim: 'kod işi', qa: 'inceleme', analist: 'plan incelemesi' }[alan];
    if (!ad) return m('');
    if (!is.length) return m(`açık ${ad} yok`);
    let ek = '';
    if (alan === 'yazilim') { // the busiest project: the most open jobs, then the name
      const say = new Map();
      for (const t of is) if (t.project) say.set(t.project, (say.get(t.project) || 0) + 1);
      const en = [...say].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))[0];
      if (en && say.size > 1) ek = ` · en yoğun: ${en[0]}`;
    }
    return m(`${is.length} ${ad} takipte${ek}`);
  }
  if (gorevli === 'revir') {
    const sh = { ...DEFAULT_SAHNE, ...(s.sahne || {}) };
    const ofset = Number.isFinite(sh.sunucu_utc_ofset_dk) ? sh.sunucu_utc_ofset_dk : null;
    const gunOf = (t) => { const o = ofisSaati(t, sh.saat_dilimi); return `${o.yil}-${o.ay}-${o.gun}`; };
    const gun = (v) => { const t = zamanMs(v, sh.saat_dilimi, ofset); return t === null ? '' : gunOf(t); };
    const bugun = Number.isFinite(ms) ? gunOf(ms) : '';
    const n = tasks.filter((t) => t.status === 'tikandi' && bugun && gun(t.finished) === bugun).length;
    return m(n ? `bugün ${n} iş takıldı` : 'ofis sağlıklı');
  }
  if (gorevli === 'psikolog') {
    const n = acik.filter((t) => Number(t.kontrol_deneme) >= 2).length;
    return m(n ? `${n} iş ikinci Kontrol denemesinde` : '');
  }
  if (gorevli === 'ik') {
    const n = acik.filter((t) => t.status === 'calisiyor').length;
    return m(n ? `${n} iş üzerinde çalışılıyor` : 'şu an çalışan iş yok');
  }
  if (gorevli === 'muhasebe') {
    const sum = s.summary && typeof s.summary === 'object' ? s.summary : {};
    const n = Number.isFinite(sum.finished_today) && sum.finished_today >= 0 ? Math.floor(sum.finished_today) : null;
    return m(n === null ? '' : n ? `bugün ${n} iş bitti` : 'bugün biten iş yok');
  }
  if (gorevli === 'idari') {
    const n = (Array.isArray(s.schedules) ? s.schedules : []).filter((z) => z && !z.duraklatildi).length;
    return m(n ? `${n} zamanlanmış iş` : '');
  }
  if (gorevli === 'proje') {
    const n = acik.filter((t) => t.project === proje).length;
    return m(n ? `${n} açık iş` : '');
  }
  return 'masasında';
}

export const MUDURLUK_ARA = 1.4; // the gap between the two offices of a cell (base units: 2.1 world, rooms never touch)
export const mudurlukOdasi = (key) => `mudurluk-${key}`;
export const mudurMasasi = (key) => `mudurluk-${key}-masa`;
export const mudurId = (key) => `sus:mudur:${key}`;
export const PLAN_MASASI = 'yazilim-plan-masa'; // plan steps and planlama work, in the Yazılım Müdürü's office
export const QA_MUDUR_YERI = 'qa-mudur-yer'; // where the QA Müdürü stands in the QA odası when a review starts
export const GM_KAPI_YERI = 'ceo-kapi-gm'; // where the Genel Müdür brings an approval summary to the CEO's door
export const EKIP_ODASI_MASA = 4; // desks of the QA odası and the Analist odası
// the QA odası's desks by seniority: a review run by haiku takes a Stajyer Tester desk first, any other a Kıdemli one
export const QA_MASALARI = { kidemli: ['qa-masa-0', 'qa-masa-1'], stajyer: ['qa-masa-2', 'qa-masa-3'] };
// The "Sosyal medya ve tasarım" department: one line per member (the owner, 2026-11-12: a new role is one line here). grup =
// its pod (platform / yaratici / influencer); alan = its platform or area; rol = what it will do. No real work yet:
// their cards say "Şu an atanmış iş yok".
export const SOSYAL_EKIBI = [
  { id: 'instagram', ad: 'Instagram uzmanı', grup: 'platform', alan: 'Instagram', rol: 'Instagram paylaşımlarını ve hikâyeleri planlayacak.' },
  { id: 'x', ad: 'X (Twitter) uzmanı', grup: 'platform', alan: 'X (Twitter)', rol: 'X paylaşımlarını ve duyuruları yazacak.' },
  { id: 'reddit', ad: 'Reddit uzmanı', grup: 'platform', alan: 'Reddit', rol: 'İlgili Reddit topluluklarında projeleri tanıtacak.' },
  { id: 'youtube', ad: 'YouTube uzmanı', grup: 'platform', alan: 'YouTube', rol: 'YouTube videolarını ve kanal düzenini planlayacak.' },
  { id: 'tiktok', ad: 'TikTok uzmanı', grup: 'platform', alan: 'TikTok', rol: 'Kısa TikTok videolarının fikirlerini üretecek.' },
  { id: 'pinterest', ad: 'Pinterest uzmanı', grup: 'platform', alan: 'Pinterest', rol: 'Pinterest panolarını ve görsel paylaşımları hazırlayacak.' },
  { id: 'linkedin', ad: 'LinkedIn uzmanı', grup: 'platform', alan: 'LinkedIn', rol: 'LinkedIn paylaşımlarını ve duyuruları hazırlayacak.' },
  { id: 'icerik', ad: 'İçerik üreticisi (metin)', grup: 'yaratici', alan: 'metin', rol: 'Paylaşımların ve sayfaların metinlerini yazacak.' },
  { id: 'video', ad: 'Video editörü', grup: 'yaratici', alan: 'video', rol: 'Videoları kurgulayıp platformlara göre hazırlayacak.' },
  { id: 'grafik', ad: 'Grafik tasarımcı', grup: 'yaratici', alan: 'görsel', rol: 'Paylaşımlar için görselleri hazırlayacak.' },
  { id: 'web', ad: 'Web site tasarımcısı', grup: 'yaratici', alan: 'web sitesi', rol: 'Projelerin tanıtım sayfalarını tasarlayacak.' },
  { id: 'uiux', ad: 'UI/UX tasarımcısı', grup: 'yaratici', alan: 'arayüz', rol: 'Uygulama ekranlarının kullanım ve görünüşünü tasarlayacak.' },
  { id: 'influencer', ad: 'Influencer ilişkileri sorumlusu', grup: 'influencer', alan: 'influencer', rol: 'Projeler için içerik üreticileriyle iş birliklerini yürütecek.' },
  { id: 'topluluk', ad: 'Topluluk yöneticisi', grup: 'influencer', alan: 'topluluk', rol: 'Yorumlara ve topluluk sorularına cevap verecek.' },
];
export const sosyalMasasi = (id) => `sosyal-masa-${id}`;
// ik: the İK ve İdari İşler Müdürü (the owner, 2026-11-13: the İK staff NPC is that manager in the org chart; reports to the
// Genel Müdür, the office's support staff report to it)
export const TESIS_PERSONELI = { muhasebe: 'Muhasebeci', idari: 'İdari işler sorumlusu', ik: 'İK ve İdari İşler Müdürü',
  revir: 'Ofis doktoru', psikolog: 'Ofis psikoloğu', masaj: 'Masajcı', sunucu: 'IT sorumlusu', arge: 'Ar-Ge uzmanı' };
// The Ar-Ge odası (plan "Sonraki iş (6)"): the research workspace of ofis.json's `arge` project. It is a facility, never a
// team bay: the arge project's jobs get no robot of their own — the Ar-Ge uzmanı (sus:arge) types at its desk while one
// runs (ARGE_ACIK) and stands for it. A whiteboard on the back wall, a bookshelf by the right wall and a second desk.
export const ARGE_PROJESI = 'arge';
export const ARGE_MASA_2 = 'arge-masa-2';
// A team's colour (its room, desks, robots' trim, decorative people, the page's chat dots): one list, indexed by the
// project's place among the registered projects without the arge workspace (the order of ofisPlani's plan.projeler),
// so the scene and the page always agree. projeler: names or /api/state.projects rows. Unknown / arge: `yoksa`.
export const ODA_RENKLERI = ['#CFE8D5', '#DDD5F3', '#CFE3F5', '#F7E7B4', '#F6D3D3', '#D3ECEC', '#FBE0C8', '#E6DDF2', '#E2EFC9', '#F3DCE6'];
export function projeRengi(proje, projeler, yoksa = null) {
  if (!proje || proje === ARGE_PROJESI) return yoksa;
  const names = (Array.isArray(projeler) ? projeler : []).map((p) => (typeof p === 'string' ? p : p && p.name))
    .filter((n) => n && n !== ARGE_PROJESI);
  const i = names.indexOf(proje);
  return i >= 0 ? ODA_RENKLERI[i % ODA_RENKLERI.length] : yoksa;
}
export const ARGE_ACIK = new Set(['baslatiliyor', 'calisiyor', 'kontrolde', 'karar-bekliyor']);
// An open research job of the Ar-Ge uzmanı: an arge job at work — never the end-of-day review job, which also works in
// the arge workspace but belongs to the Değerlendirme ekibi (t.gun_sonu, from the server record).
export const argeIsi = (t) => !!t && t.project === ARGE_PROJESI && ARGE_ACIK.has(t.status) && !t.gun_sonu;
// The Değerlendirme ekibi (the end-of-day review, bin/gunsonu.py; owner decision 2026-11-13): two staff of the Analist Müdürü at
// two desks of the Analist odası — existing furniture, the desks the decorative analysts leave for last — only while its
// work really runs: for DEGERLENDIRME_AKTIF minutes after the day's measurement (state.gun_sonu.son.olcum_iso, the
// server's own time; aktif_dk from the server) and while the review job is open (a task with gun_sonu at work). Never
// drawn otherwise; no new furniture, two robots only in those minutes.
export const DEGERLENDIRME_EKIBI = [
  { id: 'sus:degerlendirme:0', etiket: 'Ölçüm uzmanı' },
  { id: 'sus:degerlendirme:1', etiket: 'Değerlendirme uzmanı' },
];
export const DEGERLENDIRME_MASALARI = ['analist-masa-3', 'analist-masa-2', 'analist-masa-1', 'analist-masa-0'];
const DEGERLENDIRME_AKTIF = 10; // minutes, when the server does not say (gun_sonu.aktif_dk)
// {calisiyor, olcum (the measurement's minutes run now), is (the open review task or null), son (state.gun_sonu.son)}
export function degerlendirmeDurumu(st, ms) {
  const g = st && st.gun_sonu && typeof st.gun_sonu === 'object' ? st.gun_sonu : null;
  const son = g && g.son && typeof g.son === 'object' ? g.son : null;
  const tasks = Array.isArray(st && st.tasks) ? st.tasks : [];
  const is = tasks.filter((t) => t && t.gun_sonu && ARGE_ACIK.has(t.status))
    .sort((x, y) => (String(x.started || x.created || '') < String(y.started || y.created || '') ? 1 : -1))[0] || null;
  const t0 = son && son.olcum_iso ? Date.parse(son.olcum_iso) : NaN;
  const dk = g && Number.isFinite(Number(g.aktif_dk)) ? Number(g.aktif_dk) : DEGERLENDIRME_AKTIF;
  const olcum = Number.isFinite(t0) && ms >= t0 && ms < t0 + dk * 60000;
  return { calisiyor: olcum || !!is, olcum, is, son };
}
// The two members' state lines while the team works (index 0: the measurement, 1: the review); poz of each.
export function degerlendirmeMetinleri(d) {
  const saat = d.son && /^\d{2}:\d{2}$/.test(String(d.son.olcum_saati || '')) ? ` · ${d.son.olcum_saati}` : '';
  const kotu = d.son ? Math.max(0, Math.floor(Number(d.son.kotu) || 0)) : 0;
  const olcum = d.olcum ? `günü ölçtü${saat}` : `ölçüm hazır${saat}`;
  if (d.is) {
    const soru = d.is.status === 'karar-bekliyor';
    return [[olcum, 'yaziyor'], [soru ? `değerlendirme · ${sahip('in')} cevabını bekliyor`
      : `kök nedenleri arıyor · ${kisa(d.is.title || 'Gün sonu değerlendirmesi', 40)}`, soru ? 'bekliyor' : 'yaziyor']];
  }
  return [[olcum, 'yaziyor'], [kotu ? `kötü giden ${kotu} durumu not etti` : 'bugün kötü giden yok', 'yaziyor']];
}
export const ARGE_TAHTA_OLCU = [2.6, 0.5]; // the whiteboard on its stand (x, z; world units): web/scene.js draws it so
export const ARGE_KITAPLIK_OLCU = [0.6, 2.2]; // the bookshelf (x, z)
// The Sunucu odası: two groups of SUNUCU_KABIN server cabinets along its back wall, left and right of the door; the
// IT sorumlusu stands at SUNUCU_KABIN_YERI (in front of the left group) while a suggestion or a domain problem is
// open (state.sistem, bin/sistem.py ozet: its duty "uyarı var").
export const SUNUCU_KABIN = 3;
export const SUNUCU_TUR_MS = 600000; // the IT sorumlusu's round: a 10-minute slot …
export const SUNUCU_TUR_KALIS_MS = 90000; // … of which it spends this long at the cabinets (one slot in three)
export const KABIN_OLCU = [1.05, 2.2, 0.9]; // one cabinet (x, y, z; world units): web/scene.js draws it at this size
export const SUNUCU_KABIN_YERI = 'sunucu-kabin';
// The IT team (owner decision 2026-11-12): three people on a rotating 8-hour shift. Exactly one is on shift (nöbetçi) at any
// time and holds the server room's desk (IT_NOBET_MASASI) or the cabinets; only it works at the cabinets on a warning.
// The person whose day shift just ended stays as a colleague while its own office hours last (its desk
// IT_ARKADAS_MASASI, lunch, ordinary breaks) and may help at the second cabinet spot during a warning.
export const SUNUCU_KABIN_YERI_2 = 'sunucu-kabin-2';
export const IT_NOBET_MASASI = 'sunucu-masa';
export const IT_ARKADAS_MASASI = 'sunucu-masa-2';
export const IT_EKIBI = [
  { id: 'sus:sunucu', etiket: 'IT sorumlusu', ad: 'IT sorumlusu' },
  { id: 'sus:sunucu:1', etiket: 'IT uzmanı', ad: '1. IT uzmanı' },
  { id: 'sus:sunucu:2', etiket: 'IT uzmanı', ad: '2. IT uzmanı' },
];
// The guard and the Sekreter (plan "Sonraki iş (8)", owner decision 2026-11-12): three people each on the same rotating shifts.
// The first keeps the old single id ('sus:guvenlik' / 'sus:sekreter'); every member has the team's label.
export const GUVENLIK_EKIBI = [
  { id: 'sus:guvenlik', etiket: 'Güvenlik görevlisi', ad: '1. güvenlik görevlisi' },
  { id: 'sus:guvenlik:1', etiket: 'Güvenlik görevlisi', ad: '2. güvenlik görevlisi' },
  { id: 'sus:guvenlik:2', etiket: 'Güvenlik görevlisi', ad: '3. güvenlik görevlisi' },
];
export const SEKRETER_EKIBI = [
  { id: 'sus:sekreter', etiket: 'Sekreter', ad: '1. sekreter' },
  { id: 'sus:sekreter:1', etiket: 'Sekreter', ad: '2. sekreter' },
  { id: 'sus:sekreter:2', etiket: 'Sekreter', ad: '3. sekreter' },
];
// The kitchen (the owner, 2026-11-14: "meals are always ready"): the Yemekhane sorumlusu became three yemekhane görevlisi and
// three aşçı joined them, both teams on the same 24/7 rotation as the guards and the IT team (one of each on duty at any
// time, weekends and holidays too). The first server keeps the old single id 'sus:yemekhane'.
export const YEMEKHANE_EKIBI = [
  { id: 'sus:yemekhane', etiket: 'Yemekhane görevlisi', ad: '1. yemekhane görevlisi' },
  { id: 'sus:yemekhane:1', etiket: 'Yemekhane görevlisi', ad: '2. yemekhane görevlisi' },
  { id: 'sus:yemekhane:2', etiket: 'Yemekhane görevlisi', ad: '3. yemekhane görevlisi' },
];
export const ASCI_EKIBI = [
  { id: 'sus:asci', etiket: 'Aşçı', ad: '1. aşçı' },
  { id: 'sus:asci:1', etiket: 'Aşçı', ad: '2. aşçı' },
  { id: 'sus:asci:2', etiket: 'Aşçı', ad: '3. aşçı' },
];
// The shift teams by their gorevli: `arkadas` — the person whose day or evening shift just ended stays as a colleague
// while its own office hours last (the IT team only; the guard and the Sekreter go home when their shift ends);
// `isGunleri` — the team works only the shifts that begin on a work day (the work calendar, the owner, 2026-11-13: the
// Sekreters are off on weekends and public holidays; the guards and the IT team keep their 24/7 rotation).
export const NOBET_EKIPLERI = {
  sunucu: { ad: 'IT ekibi', uyeler: IT_EKIBI, arkadas: true },
  guvenlik: { ad: 'Güvenlik ekibi', uyeler: GUVENLIK_EKIBI, arkadas: false },
  sekreter: { ad: 'Sekreterler', uyeler: SEKRETER_EKIBI, arkadas: false, isGunleri: true },
  yemekhane: { ad: 'Yemekhane ekibi', uyeler: YEMEKHANE_EKIBI, arkadas: false },
  asci: { ad: 'Aşçılar', uyeler: ASCI_EKIBI, arkadas: false },
};
// the shifts in the office zone, minutes of the day: gece 00–08, gündüz 08–16, akşam 16–24
export const VARDIYALAR = [{ ad: 'gece', bas: 0 }, { ad: 'gündüz', bas: 480 }, { ad: 'akşam', bas: 960 }];
export const VARDIYA_DK = 480;
export const IT_VARDIYALAR = VARDIYALAR;
export const IT_VARDIYA_DK = VARDIYA_DK;
export const NOBET_CIKIS_PAYI_MS = 8000; // a leaving walk lasts the walk to the lift plus this (it always arrives)
export const IT_CIKIS_PAYI_MS = NOBET_CIKIS_PAYI_MS;
// Who is on which shift: on office day D (days since 1970-01-01 in the office zone) shift k is worked by person
// (k + D) mod 3. Two shifts in a row are never the same person, and the night moves to another person every day
// (each takes it once in three days: night → evening two days later → day the next day → night). The same for every team.
export const nobetKisisi = (gun, k) => (((k + gun) % 3) + 3) % 3;
export const itKisisi = nobetKisisi;
// The current shift (one for all teams): {gun, vardiya (index), ad, nobetci (person index), bas, son (ms), onceki:
// {kisi, vardiya}, sonraki: {kisi, vardiya, ad, bas}}.
export function vardiya(now, sahne) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const ms = nowMs(now);
  const t = ofisSaati(ms, s.saat_dilimi);
  const gun = Math.round(Date.UTC(t.yil, t.ay - 1, t.gun) / 86400000);
  const cur = gununDakikasi(ms, s.saat_dilimi);
  const k = Math.max(0, Math.min(2, Math.floor(cur / VARDIYA_DK)));
  const bas = Math.round((ms - (cur - k * VARDIYA_DK) * 60000) / 60000) * 60000;
  const son = bas + VARDIYA_DK * 60000;
  const [pg, pk] = k === 0 ? [gun - 1, 2] : [gun, k - 1];
  const [ng, nk] = k === 2 ? [gun + 1, 0] : [gun, k + 1];
  return { gun, vardiya: k, ad: VARDIYALAR[k].ad, nobetci: nobetKisisi(gun, k), bas, son,
    onceki: { kisi: nobetKisisi(pg, pk), vardiya: pk }, sonraki: { kisi: nobetKisisi(ng, nk), vardiya: nk, ad: VARDIYALAR[nk].ad, bas: son } };
}
export const itVardiyasi = vardiya;
const ekipOf = (ekip) => (typeof ekip === 'string' ? NOBET_EKIPLERI[ekip] : ekip) || null;
// Does the team work the shifts of office day `gun` (a day number)? Always, except an `isGunleri` team (with office
// hours) on a weekend or a public holiday.
function vardiyaAcik(e, gun, sahne) {
  return !e || !e.isGunleri || !mesaiAraligi(sahne) || isGunuMu(gundenTarih(gun));
}
// A team's current shift (vardiya) with the work calendar: {…vardiya, acik (the team works this shift), nobetci (person
// index, null when closed), sonraki: the team's next worked shift {kisi, vardiya, ad, bas} (it may be days away)}.
export function ekipVardiyasi(ekip, now, sahne) {
  const e = ekipOf(ekip);
  const v = vardiya(now, sahne);
  const acik = vardiyaAcik(e, v.gun, sahne);
  const out = { ...v, acik, nobetci: acik ? v.nobetci : null };
  if (vardiyaAcik(e, v.sonraki.vardiya === 0 ? v.gun + 1 : v.gun, sahne)) return out;
  const gun0 = v.bas - v.vardiya * VARDIYA_DK * 60000; // the office day's 00:00
  for (let i = v.vardiya + 1; i < 3 * 70; i++) {
    const g = v.gun + Math.floor(i / 3), k = i % 3;
    if (!vardiyaAcik(e, g, sahne)) continue;
    out.sonraki = { kisi: nobetKisisi(g, k), vardiya: k, ad: VARDIYALAR[k].ad, bas: gun0 + (g - v.gun) * 86400000 + k * VARDIYA_DK * 60000 };
    break;
  }
  return out;
}
// Each member of a shift team now: {…member, kisi, durum: 'nobette' | 'iceride' (an `arkadas` team only: the colleague
// whose day or evening shift just ended, while its own office hours last — personelSaati) | 'evde'}.
export function nobetEkibi(ekip, now, sahne) {
  const e = ekipOf(ekip);
  if (!e) return [];
  const v = ekipVardiyasi(e, now, sahne);
  return e.uyeler.map((u, kisi) => ({ ...u, kisi,
    durum: kisi === v.nobetci ? 'nobette'
      : e.arkadas && kisi === v.onceki.kisi && v.onceki.vardiya !== 0 && personelSaati(u.id, now, sahne) === 'iceride' ? 'iceride' : 'evde' }));
}
export const itEkibi = (now, sahne) => nobetEkibi('sunucu', now, sahne);
// One member's shifts around now: {simdiki: {bas, son} | null, onceki: the last one that ended, sonraki: the next one
// that starts} (ms; each member works one 8-hour shift a day; with `ekip`, only the shifts that team works — the
// Sekreters' next shift after a weekend or a holiday may be days away).
export function nobetPlani(kisi, now, sahne, ekip = null) {
  const ms = nowMs(now);
  const v = vardiya(ms, sahne);
  const e = ekipOf(ekip);
  const gun0 = v.bas - v.vardiya * VARDIYA_DK * 60000;
  let simdiki = null, onceki = null, sonraki = null;
  for (let g = -12; g <= 3 || (g <= 70 && !sonraki); g++) {
    if (!vardiyaAcik(e, v.gun + g, sahne)) continue;
    const k = (((kisi - (v.gun + g)) % 3) + 3) % 3;
    const bas = gun0 + g * 86400000 + k * VARDIYA_DK * 60000;
    const x = { bas, son: bas + VARDIYA_DK * 60000, vardiya: k, ad: VARDIYALAR[k].ad };
    if (bas <= ms && ms < x.son) simdiki = x;
    else if (x.son <= ms && (!onceki || x.son > onceki.son)) onceki = x;
    else if (bas > ms && (!sonraki || bas < sonraki.bas)) sonraki = x;
  }
  return { simdiki, onceki, sonraki };
}
// The walk home of a team member who was drawn in the previous tick (pa) and is off shift now: it walks to the lift and
// is gone only on arrival — the walk (sure(from, 'asansor')) plus NOBET_CIKIS_PAYI_MS, carried tick to tick in
// cikis_bitis. Returns {bitis, metin} while it walks, null when it is gone (or was not drawn).
export function nobetCikisi(pa, ms, sure, yer) {
  if (!pa || pa.otel) return null; // already at the Otel (oteleYerlestir draws it there)
  let bitis = pa.cikis && Number.isFinite(pa.cikis_bitis) ? pa.cikis_bitis : null;
  if (bitis === null && !pa.cikis) bitis = ms + sure(pa.yer || yer, 'asansor') + NOBET_CIKIS_PAYI_MS;
  if (bitis === null || ms >= bitis) return null;
  return { bitis, metin: pa.cikis_metni || (pa.nobetci || pa.devretti ? 'nöbeti devretti · otele gidiyor' : 'otele gidiyor') };
}
// puts a leaving member on its walk to the lift (nobetCikisi's result)
function eveYolla(a, c) {
  a.yer = 'asansor'; a.masa = null; a.poz = 'yuruyor'; a.cikis = true; a.cikis_bitis = c.bitis;
  a.cikis_metni = c.metin; a.durum_metni = c.metin; a.simge = null; delete a.gorevde;
}
export const sistemUyarisi = (st) => {
  const s = st && st.sistem && typeof st.sistem === 'object' ? st.sistem : null;
  return !!s && (Number(s.oneri) > 0 || Number(s.domain_sorunu) > 0);
};
// a massage needs a long working day: a kadro whose model's jobs ran this long today (molaPlani `yorgun`)
export const MASAJ_ESIGI_MS = 2 * 3600000;
// the doctor: one visit to the desk of every agent that newly got stuck (tikandi / basi-onde) or red-marked (hata)
export const DOKTOR_KALIS_MS = 8000; // a visit: this long beside the desk after arriving
// The informational staff (shown in hafif too): the facility staff and the project residents.
export function BILGI_PERSONELI(a) {
  return !!a && a.tur === 'sus' && (a.gorevli === 'proje' || a.gorevli === 'sosyal' || a.gorevli === 'yemekhane' ||
    a.gorevli === 'mudur' ||
    Object.prototype.hasOwnProperty.call(TESIS_PERSONELI, a.gorevli));
}
// beds in the Dinlenme odası (the owner, 2026-11-13: at night everyone off shift and without real work sleeps there; 20
// beds in two rows of ten facing each other across an aisle, the door's gap in the middle of the back row)
export const DINLENME_YATAK = 20;
export const YATAK_OLCU = [1.3, 2.6]; // one bed (x, z; world units): web/scene.js makeBed draws it at this size
// The Otel (the city, step 1 — the owner, 2026-11-14: "otel gibi düşün; ofis dışındaki kişilerin kaldığı yer"): a separate
// two-storey building in front of the lobby, outside the floor, across a short path from the lobby's entrance gap.
// The people who used to "go home" stay there instead: the day-hours staff (the managers, the social media team,
// Muhasebe / İK / İdari işler, the office services, the Ar-Ge uzmanı, the project residents) outside their office
// hours and on days off, and the shift teams' members off shift. They walk there from the office and back in the
// morning; inside they are hidden (a closed building: nobody is drawn in it). Each has its own room
// (otel-oda-<i>, otelKadrosu order: stable). The agents (CEO, kadro, auditors) still sleep in the office's Dinlenme odası.
export const OTEL_ODA = 72; // 18 × 4 (the kitchen teams, 2026-11-14, added five guests: ≥ 8 spare rooms up to 23 projects)
// base units: width, depth, the yard between it and the floor (9 since the street, the city step 2: it runs across the
// yard — 7 before)
export const OTEL_OLCU = { W: 26, D: 10, ARA: 9 };
export const OTEL_ON_EK = 'otel-oda-';
export const otelOdasiMi = (yer) => typeof yer === 'string' && yer.startsWith(OTEL_ON_EK);
// Everyone who stays at the Otel, in room order: [{id, gorevli, etiket, ...the fields its office actor carries}]. The
// fixed staff first (their rooms never move), the project residents last (one per project).
export function otelKadrosu(projeler = []) {
  const out = [];
  for (const m of MUDURLUKLER) out.push({ id: mudurId(m.key), gorevli: 'mudur', alan: m.key, etiket: m.ad });
  for (const u of SOSYAL_EKIBI) out.push({ id: `sus:sosyal:${u.id}`, gorevli: 'sosyal', rol: u.id, etiket: u.ad });
  for (const [k, ad] of Object.entries(TESIS_PERSONELI)) {
    if (k !== 'sunucu') out.push({ id: `sus:${k}`, gorevli: k, etiket: k === 'revir' ? 'Ofis doktoru' : ad });
  }
  out.push({ id: 'sus:cayci', gorevli: 'cayci', etiket: 'Çaycı' });
  for (const u of YEMEKHANE_EKIBI) out.push({ id: u.id, gorevli: 'yemekhane', etiket: u.etiket });
  for (const u of ASCI_EKIBI) out.push({ id: u.id, gorevli: 'asci', etiket: u.etiket });
  for (const u of IT_EKIBI) out.push({ id: u.id, gorevli: 'sunucu', it_kisi: IT_EKIBI.indexOf(u), etiket: u.etiket });
  for (const u of GUVENLIK_EKIBI) out.push({ id: u.id, gorevli: 'guvenlik', etiket: u.etiket });
  for (const u of SEKRETER_EKIBI) out.push({ id: u.id, gorevli: 'sekreter', etiket: u.etiket });
  for (const p of projeler || []) {
    if (p && p !== ARGE_PROJESI) out.push({ id: `sus:proje:${p}`, gorevli: 'proje', proje: p, etiket: `${aileAdi(p)} sorumlusu` });
  }
  return out;
}
// --- the street (the city, step 2 — owner decision 2026-11-14) ---
// A street across the yard between the floor's front edge and the Otel: a sidewalk on the office side (kuzey), the
// two-lane road (yol), a sidewalk on the hotel side (guney), running past both ends of the floor (UC). A crosswalk
// (gecit) where the office–Otel path crosses it: the staff's walk lobi-giris → otel-yol → otel-kapi is one straight
// line in x = the crosswalk's middle. Street lamps and trees stand on each sidewalk's curb strip (BORDUR from the road),
// alternating, never near the crosswalk or the ends. Pedestrians (yayalar) walk two lines per sidewalk (CIZGI, from its
// building-side edge), clear of the lamps and trees. World units (laid out after the scaling); pure.
export const SOKAK_OLCU = { ARA: 0.5, KALDIRIM: 2.6, YOL: 3.6, UC: 4, GECIT: 3.2, BORDUR: 0.4, CIZGI: [0.55, 1.55], ARALIK: 7.5,
  GOVDE: 0.5, AGAC: 0.15, LAMBA: 0.08 }; // GOVDE: a pedestrian's body radius; AGAC / LAMBA: a trunk's / pole's radius
export function sokakDuzeni(W, D, gecitX) {
  const S = SOKAK_OLCU, r2 = (v) => +v.toFixed(2);
  const z0 = r2(D + 2.3 + S.ARA); // past the office slab's lip
  const kuzey = { z0, z1: r2(z0 + S.KALDIRIM) };
  const yol = { z0: kuzey.z1, z1: r2(kuzey.z1 + S.YOL) };
  const guney = { z0: yol.z1, z1: r2(yol.z1 + S.KALDIRIM) };
  const x0 = -S.UC, x1 = r2(W + S.UC);
  const lambalar = [], agaclar = [];
  let k = 0;
  for (let x = x0 + 3; x <= x1 - 3; x += S.ARALIK, k++) {
    if (Math.abs(x - gecitX) < S.GECIT / 2 + 2) continue;
    const kz = r2(kuzey.z1 - S.BORDUR), gz = r2(guney.z0 + S.BORDUR);
    (k % 2 ? agaclar : lambalar).push([r2(x), kz]);
    (k % 2 ? lambalar : agaclar).push([r2(x), gz]);
  }
  return { x0, x1, kuzey, yol, guney, gecit: { x: gecitX, w: S.GECIT }, lambalar, agaclar,
    // the walking lines: the building side first, then the one nearer the curb
    cizgiler: { kuzey: S.CIZGI.map((c) => r2(kuzey.z0 + c)), guney: S.CIZGI.map((c) => r2(guney.z1 - c)) } };
}
// The pedestrians' closed routes (anonymous passers-by: scenery only — no actor, no label, never in kimNerede or the
// Şema): an oval on the north sidewalk, one on the south, and a loop on each side of the crosswalk that crosses the road
// only there. Each route = {pts, cum, L}; pure.
export function yayaRotalari(sokak) {
  if (!sokak) return [];
  const { x0, x1, gecit: { x: cx }, cizgiler: { kuzey: [kD, kY], guney: [gD, gY] } } = sokak;
  const xa = x0 + 0.8, xb = x1 - 0.8;
  const rotalar = [
    [[xa, kD], [xb, kD], [xb, kY], [xa, kY]],
    [[xb, gD], [xa, gD], [xa, gY], [xb, gY]],
    [[cx - 0.25, kD], [xa, kD], [xa, kY], [cx - 0.75, kY], [cx - 0.75, gY], [xa, gY], [xa, gD], [cx - 0.25, gD]],
    [[cx + 0.25, gD], [xb, gD], [xb, gY], [cx + 0.75, gY], [cx + 0.75, kY], [xb, kY], [xb, kD], [cx + 0.25, kD]],
  ];
  return rotalar.map((pts) => {
    const cum = [0];
    for (let i = 1; i <= pts.length; i++) {
      const a = pts[i - 1], b = pts[i % pts.length];
      cum.push(cum[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1]));
    }
    return { pts, cum, L: cum[pts.length] };
  });
}
export const YAYA_EN_COK = 10;
// Pedestrian i at scene time t (seconds): its route (i % 4, every second group walks it backwards), a calm seeded
// speed and phase. {x, z, aci (the heading, as yuzAcisi: atan2(dx, dz)), adim (the step phase), hiz}. Periodic in t
// with period L / hiz: the loop.
export function yayaKonumu(rotalar, i, t) {
  const r = rotalar[i % rotalar.length];
  if (!r || !(r.L > 0)) return null;
  const h = hash(`yaya:${i}`);
  const hiz = 0.75 + (h % 31) / 100; // 0.75–1.05 units a second: a stroll
  const geri = Math.floor(i / rotalar.length) % 2 === 1;
  let s = ((((h >>> 5) % 1000) / 1000) * r.L + hiz * t) % r.L;
  if (s < 0) s += r.L;
  if (geri) s = r.L - s;
  let k = 1;
  while (k < r.cum.length - 1 && r.cum[k] < s) k++;
  const a = r.pts[k - 1], b = r.pts[k % r.pts.length];
  const seg = r.cum[k] - r.cum[k - 1] || 1;
  const f = Math.min(1, Math.max(0, (s - r.cum[k - 1]) / seg));
  const dx = (b[0] - a[0]) * (geri ? -1 : 1), dz = (b[1] - a[1]) * (geri ? -1 : 1);
  return { x: a[0] + (b[0] - a[0]) * f, z: a[1] + (b[1] - a[1]) * f, aci: Math.atan2(dx, dz), adim: (hiz * t) / 0.55, hiz };
}
// How many walk now: 8 by day (07:00–20:00), 5 in the evening and the early morning (20:00–23:00, 06:00–07:00), 2 at
// night; none in hafif.
export function yayaSayisi(now, sahne, hafif = false) {
  if (hafif) return 0;
  const h = gununDakikasi(nowMs(now), { ...DEFAULT_SAHNE, ...(sahne || {}) }.saat_dilimi) / 60;
  return h >= 7 && h < 20 ? 8 : (h >= 20 && h < 23) || (h >= 6 && h < 7) ? 5 : 2;
}

// the hotel's state texts (labels, cards, the guard's lists, the Şema): asleep from OTEL_UYKU[0] to OTEL_UYKU[1] o'clock
export const OTEL_UYKU = [22, 8];
export const otelMetni = (ms, tz) => {
  const h = Math.floor(gununDakikasi(ms, tz) / 60);
  return h >= OTEL_UYKU[0] || h < OTEL_UYKU[1] ? 'otelde · uyuyor' : 'otelde';
};
export const YEMEKHANE_SERVIS = 'yemekhane-servis'; // the Yemekhane sorumlusu's counter
export const YEMEKHANE_BULASIK = 'yemekhane-bulasik'; // its place at the Bulaşıkhane's sink
// the kitchen (mutfak, 2026-11-14): the Bulaşıkhane's corner was the only kitchen-like place (a sink, a dishwasher, a
// plate rack, a tray trolley; no cooking spot), so the cooking spot extends that same strip: a stove and a fridge at
// its free right end; the cook on duty stands at the stove or at the fridge
export const YEMEKHANE_OCAK = 'yemekhane-ocak';
export const YEMEKHANE_DOLAP = 'yemekhane-dolap';
const YEMEK_BANT = 4.8; // one canteen band: a table with four chairs on each side
const BULASIK_D = 3.6; // the canteen's dishwashing corner (Bulaşıkhane) at its far end, below the last band

// Everyone who may sit in the canteen at once: the CEO, the four kadro, the auditors, every idle session the desks allow
// (T projects × N desks), the staff that eat there (the facility staff, the social media team, one resident per
// project; the Sekreter and the guard have their own two chairs, the tea server serves).
export function yemekKapasitesi(T, N, denetciSayisi) {
  const t = Math.max(0, Math.floor(Number(T) || 0)), n = Math.max(1, Math.floor(Number(N) || 1));
  return 1 + KADRO.length + Math.max(1, Math.floor(Number(denetciSayisi) || 1)) + t * n +
    Object.keys(TESIS_PERSONELI).length + SOSYAL_EKIBI.length + MUDURLUKLER.length + t;
}

export function masaSayisi(options = {}) {
  const per = Number.isFinite(Number(options.max_running_per_project)) ? Number(options.max_running_per_project) : 1;
  return Math.max(1, Math.min(6, per + 2));
}

// The common area's width (base units): the auditor room right of the centred CEO room, the meeting room + the
// Müdür's office left of it (2 units apart each).
function ortakGenislik(denetciler) {
  const { MIN_W, ROOM_W, TEAM_GAP, DENETCI_DX, MUDUR_W, UZMAN_W, DINLENME_W } = OLCU;
  const DW = Math.max(ROOM_W, +(DENETCI_DX * denetciler.length + 1.8).toFixed(2));
  // the middle row: the Uzmanlar odası centred, the Dinlenme odası (DINLENME_W wide at least) right of it
  return { DW, Wc: Math.max(MIN_W, 2 * DW + 2 * TEAM_GAP + ROOM_W, 2 * (ROOM_W + 2 * TEAM_GAP + MUDUR_W) + ROOM_W,
    2 * (UZMAN_W / 2 + TEAM_GAP + DINLENME_W)) };
}

// The floor's grid for T projects (base units): rows R, wing columns C, the depth D, the canteen's chair bands and
// the cells the projects and the reserved bays take, in order (hucreler: {bolge, sutun, satir, x, z, w}).
// R: as many rows as the common area (front row, canteen, the facility cells under it) is deep, rounded to the nearest
// row (at least EN_AZ_SATIR); C: the fewest columns (at least the facility columns) that hold every project and one
// reserved bay, plus more while the floor would be narrower than EN_BOY_MIN : 1.
function zeminIzgarasi(T, options = {}) {
  const { TEAM_W, TEAM_D, GAP, TOP_D, BOT_D, ROOM_W, OMURGA, SATIR_ARA, TESIS_SATIR, EN_BOY_MIN, EN_AZ_SATIR } = OLCU;
  const t = Math.max(0, Math.floor(Number(T) || 0));
  const N = masaSayisi(options);
  const denetciler = denetciListesi(options.denetciler);
  const { Wc } = ortakGenislik(odaDenetcileri(denetciler));
  const P = TEAM_D + SATIR_ARA;
  const zb = TOP_D + GAP + TEAM_D + GAP; // the front row
  const bantlar = Math.max(1, Math.ceil(yemekKapasitesi(t, N, denetciler.length) / 8));
  const yemekAlt = zb + Math.max(BOT_D, 2.4 + bantlar * YEMEK_BANT + 2.0 + BULASIK_D);
  const tesisAlt = (EN_AZ_SATIR - 1) * P + TEAM_D;
  const Dc = Math.max(zb + BOT_D, yemekAlt, tesisAlt);
  const R = Math.max(EN_AZ_SATIR, 1 + Math.round((Dc - TEAM_D) / P));
  const D = Math.max(Dc, (R - 1) * P + TEAM_D);
  const kx0 = Wc + OMURGA;
  const tesis = new Set([...Object.values(TESIS_HUCRELERI), SIGARA_HUCRESI].map((c) => c.join(':')));
  const LOBI_ALT = TESIS_SATIR - 1; // the first row of cells under the common area
  const kanatSutun = Math.max(...Object.values(TESIS_HUCRELERI).filter((c) => c[0] === 'kanat').map((c) => c[1])) + 1;
  const RW = TEAM_W - 2;
  const hucre = (bolge, sutun, satir) => ({ bolge, sutun, satir, z: satir * P,
    x: bolge === 'kanat' ? kx0 + sutun * TEAM_W : sutun === 2 ? Wc - RW : sutun * TEAM_W, w: RW });
  // the lobby (owner decision 2026-11-12): the floor's front-right corner, two cells wide — the wing's last two columns in its
  // bottom row; laid out after the wing, so it stays in the corner as the wing grows
  const lobiMi = (C, c, r) => r === R - 1 && (c === C - 1 || c === C - 2);
  const hucreler = (C) => {
    const out = [];
    for (let c = 0; c < C; c++) for (let r = 0; r < R; r++) {
      if (!tesis.has(`kanat:${c}:${r}`) && !lobiMi(C, c, r)) out.push(hucre('kanat', c, r));
    }
    for (let r = LOBI_ALT; r < R; r++) for (const c of [0, 1, 2]) if (!tesis.has(`alt:${c}:${r}`)) out.push(hucre('alt', c, r));
    return out;
  };
  let C = kanatSutun;
  while (hucreler(C).length < t + 1) C++;
  while ((kx0 + C * TEAM_W - 2) / D < EN_BOY_MIN) C++;
  const list = hucreler(C);
  const lobi = { x: kx0 + (C - 2) * TEAM_W, z: (R - 1) * P, w: 2 * TEAM_W - 2, d: D - (R - 1) * P };
  return { R, C, D, P, Wc, kx0, W: kx0 + C * TEAM_W - 2, zb, bantlar, hucreler: list, yedek: list.length - t, hucre,
    N, denetciler, lobi };
}

// The wing's grid for T projects (options as for ofisPlani): sutun (wing columns), satir (rows), yedek (empty reserved
// bays), tesis (the number of fixed facilities) and hucreler (the cells of the projects, then the reserved bays).
export function kanatIzgarasi(T, options = {}) {
  const z = zeminIzgarasi(T, options);
  return { sutun: z.C, satir: z.R, yedek: z.yedek, tesis: KANAT_TESISLERI.length,
    hucreler: z.hucreler.map(({ bolge, sutun, satir, x, z: zz, w }) => ({ bolge, sutun, satir, x, z: zz, w })) };
}

// The helper (subagent) spots of a desk at (x, z): two small columns on the desk's left, beside the chair (not behind
// it, where the parent would hide them), then the "+N" spot. YARDIMCI_EN_COK + 1 spots.
export function yardimciYerleri(x, z) {
  const out = [];
  for (let h = 0; h < YARDIMCI_EN_COK; h++) out.push([x - 1.15 - 0.6 * Math.floor(h / 2), z - 0.35 + 0.75 * (h % 2)]);
  out.push([x - 1.45, z - 1.05]);
  return out;
}

export function ofisPlani(projects, options = {}) {
  // the arge workspace is the Ar-Ge odası (a facility), never a team bay
  const names = (projects || []).map((p) => (typeof p === 'string' ? p : p && p.name))
    .filter((n) => n && n !== ARGE_PROJESI);
  const T = names.length;
  const { TEAM_W, TEAM_GAP, TEAM_D, GAP, TOP_D, BOT_D, ROOM_W, DESK_DX, DESK_DZ, DENETCI_DX, MUDUR_W,
    OMURGA, UZMAN_W, UZMAN_MASA, OYUN_W, CAY_W, SALON_W, SATIR_ARA, TESIS_SATIR } = OLCU;
  // the floor's grid (zeminIzgarasi): rows R, wing columns C, depth D, the common area's width Wc
  const izgara = zeminIzgarasi(T, options);
  const { R, C, D, P: SP, Wc, kx0, W, N, denetciler } = izgara;
  const { DW } = ortakGenislik(odaDenetcileri(denetciler));
  const zMid = TOP_D + GAP; // the middle row
  const zb = izgara.zb; // the front row
  const omurgaX = Wc + OMURGA / 2;
  const dugumler = {};
  const kenarlar = [];
  const odalar = [];
  const node = (id, x, z, tur, oda = null) => { dugumler[id] = { id, x: +x.toFixed(2), z: +z.toFixed(2), tur, oda }; return id; };
  const edge = (a, b) => kenarlar.push([a, b]);
  // corridors: 'o0' / 'o1' in the common area (behind / in front of the middle row), 'k0'..'k(R-2)' below each row of
  // the wing (from row 2 on they also reach the cells under the Revir), 'a2'..'a(R-2)' below each row of the cells
  // left of the canteen (off the left aisle)
  const corridorZ = { o0: TOP_D + GAP / 2, o1: zMid + TEAM_D + GAP / 2 };
  for (let k = 0; k < R - 1; k++) corridorZ[`k${k}`] = k * SP + TEAM_D + SATIR_ARA / 2;
  for (let k = TESIS_SATIR - 2; k < R - 1; k++) corridorZ[`a${k}`] = k * SP + TEAM_D + SATIR_ARA / 2;
  const doorsOn = Object.fromEntries(Object.keys(corridorZ).map((c) => [c, []]));
  const room = (id, tur, ad, x, z, w, d, corridor, extra = {}) => {
    const kapi = node(`${id}-kapi`, x + w / 2, z === 0 ? z + d : z, 'kapi', id);
    doorsOn[corridor].push(kapi);
    odalar.push({ id, tur, ad, x, z, w, d, kapi, ...extra });
    return kapi;
  };
  const place = (id, oda, tur, x, z, link) => { node(id, x, z, tur, oda); edge(link, id); return id; };
  const ek = {}; // spot id -> the furniture it belongs to: [x, z] in base units (kept at its distance when scaled)
  const helpers = (prefix, oda, x, z, link) => yardimciYerleri(x, z)
    .forEach(([hx, hz], h) => { ek[place(`${prefix}-${h}`, oda, 'yardimci', hx, hz, link)] = [x, z]; });
  // a desk with its helper spots and the "yan" spot beside it (where a file is handed over)
  const desk = (did, oda, tur, x, z, link) => {
    place(did, oda, tur, x, z, link);
    helpers(`${did}-yardimci`, oda, x, z, did);
    ek[place(`${did}-yan`, oda, 'yan', x + 1.3, z, did)] = [x, z];
  };

  // back row: meeting room (kept as an empty meeting room: review work sits in the Uzmanlar odası), CEO (glass,
  // centre), external auditor; the model board between the meeting room and the CEO's room, at the back edge, facing
  // the camera
  const cx = Wc / 2;
  let k = room('toplanti', 'toplanti', 'Toplantı odası', 0, 0, ROOM_W, TOP_D, 'o0');
  for (let i = 0; i < 6; i++) place(`toplanti-sandalye-${i}`, 'toplanti', 'sandalye', 2.6 + 2.4 * (i % 3), i < 3 ? 2.75 : 5.25, k);
  place('toplanti-ozet', 'toplanti', 'ozet', 9, 1.2, k);
  k = room('ceo', 'ceo', 'CEO odası', cx - ROOM_W / 2, 0, ROOM_W, TOP_D, 'o0');
  place('ceo-masa', 'ceo', 'masa', cx, 3.4, k);
  helpers('ceo-yardimci', 'ceo', cx, 3.4, 'ceo-masa');
  for (let i = 0; i < 6; i++) place(`ceo-kuyruk-${i}`, 'ceo', 'kuyruk', cx + 1.6 + 1.55 * i, corridorZ.o0 - 0.5, k);
  place('ceo-kuyruk-ozet', 'ceo', 'ozet', cx + 1.6 + 1.55 * 6, corridorZ.o0 - 0.5, k);
  // where the Genel Müdür stands when it brings a workflow's approval summary to the CEO's door (left of the door; the
  // Sekreter's spot is the door itself, the waiting jobs queue on the right)
  place(GM_KAPI_YERI, 'ceo', 'ayakta', cx - 1.6, corridorZ.o0 - 0.5, k);
  k = room('denetci', 'denetci', 'Dış denetçi', Wc - DW, 0, DW, TOP_D, 'o0');
  // (the security reviewer has no desk here: its runs show at the IT güvenlik desk in the Sunucu odası)
  const odadakiler = odaDenetcileri(denetciler);
  odadakiler.forEach((ad, i) => place(denetciMasasi(ad), 'denetci', 'masa',
    Wc - DW / 2 + DENETCI_DX * (i - (odadakiler.length - 1) / 2), 3.4, k));
  // the Müdür's private office (glass, smaller than the CEO's) between the meeting room and the CEO's room: the
  // fable kadro idles at its desk, planning / fable work is done there
  k = room('mudur', 'mudur', 'Genel Müdür odası', ROOM_W + TEAM_GAP, 0, MUDUR_W, TOP_D, 'o0');
  place(MUDUR_MASASI, 'mudur', 'mudur-masasi', ROOM_W + TEAM_GAP + MUDUR_W / 2, 3.4, k);
  helpers(`${MUDUR_MASASI}-yardimci`, 'mudur', ROOM_W + TEAM_GAP + MUDUR_W / 2, 3.4, MUDUR_MASASI);
  ek[place(`${MUDUR_MASASI}-yan`, 'mudur', 'yan', ROOM_W + TEAM_GAP + MUDUR_W / 2 + 1.3, 3.4, MUDUR_MASASI)] =
    [ROOM_W + TEAM_GAP + MUDUR_W / 2, 3.4];

  // middle row: the Uzmanlar odası (a quiet work room under the CEO's room): review work (inceleme tier, plan- and
  // kod-inceleme steps run by Claude) and the hakem type at its desks; two rows of three, a door on both corridors
  const ux = cx - UZMAN_W / 2;
  k = room('uzmanlar', 'uzmanlar', 'Uzmanlar odası', ux, zMid, UZMAN_W, TEAM_D, 'o0');
  const uAlt = node('uzmanlar-kapi-alt', cx, zMid + TEAM_D, 'kapi', 'uzmanlar');
  doorsOn.o1.push(uAlt);
  for (let i = 0; i < UZMAN_MASA; i++) {
    const did = `uzmanlar-masa-${i}`;
    desk(did, 'uzmanlar', 'masa', ux + 4 + 7 * (i % 3), zMid + 2.6 + 3.6 * Math.floor(i / 3), k);
    edge(uAlt, did);
  }
  place('uzmanlar-ozet', 'uzmanlar', 'ozet', ux + UZMAN_W - 1, zMid + 1.2, k);

  // the Oyun odası (middle row, left of the Uzmanlar odası; its size never depends on the projects): a table-tennis
  // table (two players face each other across it), a billiards table (one leans with the cue, the other waits), a
  // darts board on the back wall and a bean bag. Idle actors only (molaPlani); a door on both corridors.
  k = room('oyun', 'oyun', 'Oyun odası', 0, zMid, OYUN_W, TEAM_D, 'o0');
  const oAlt = node('oyun-kapi-alt', OYUN_W / 2, zMid + TEAM_D, 'kapi', 'oyun');
  doorsOn.o1.push(oAlt);
  const ping = [3.8, zMid + 3.4], bil = [9.2, zMid + 5.4], dart = [11.4, zMid + 0.5];
  const oyunYeri = (id, x, z, at) => { const n = place(id, 'oyun', 'oyun-yer', x, z, k); edge(oAlt, n); ek[n] = at; return n; };
  oyunYeri('oyun-pingpong-0', ping[0] - 2.1, ping[1], ping);
  oyunYeri('oyun-pingpong-1', ping[0] + 2.1, ping[1], ping);
  oyunYeri('oyun-bilardo-0', bil[0] - 2.0, bil[1], bil);
  oyunYeri('oyun-bilardo-1', bil[0] + 0.9, bil[1] + 1.9, bil);
  oyunYeri('oyun-dart', dart[0], dart[1] + 2.2, dart);
  ek[place('oyun-puf', 'oyun', 'puf', 1.6, zMid + 7.6, k)] = [1.6, zMid + 7.6];
  place('oyun-ozet', 'oyun', 'ozet', OYUN_W - 1, zMid + TEAM_D - 1.2, k);
  // two places to stand and watch a game (the roaming staff's: personelRotasi)
  for (let i = 0; i < 2; i++) { const n = place(`oyun-izleyici-${i}`, 'oyun', 'ayakta', 5.6 + 1.6 * i, zMid + 8.3, k); edge(oAlt, n); }

  // the Dinlenme odası (middle row, right of the Uzmanlar odası; fixed): DINLENME_YATAK beds, dim light. The dormant
  // CEO sleeps here (real state), at night everyone off shift and without real work (geceYatagi), by day long-idle
  // actors may nap (molaPlani 'uyku'). Two rows of ten beds — the back row's heads at the back wall with the door's gap
  // in the middle, the front row's heads at the curtain — and the aisle between them: one aisle node in the middle
  // and a foot spot in front of each bed (tur 'ayak'), so a sleeper walks along the aisle and never over another bed.
  const dx0 = ux + UZMAN_W + TEAM_GAP;
  const dw = Wc - dx0;
  k = room('dinlenme', 'dinlenme', 'Dinlenme odası', dx0, zMid, dw, TEAM_D, 'o0');
  {
    const K = OLCU.K, bw = YATAK_OLCU[0] / K, bd = YATAK_OLCU[1] / K; // a bed in base units
    const kapiBosluk = 1.9, kenar = 0.3, yari = DINLENME_YATAK / 4; // beds per half row
    const adim = (dw / 2 - kapiBosluk / 2 - kenar - bw) / (yari - 1);
    const xs = [];
    for (let i = 0; i < yari; i++) xs.push(dx0 + kenar + bw / 2 + i * adim);
    for (let i = yari - 1; i >= 0; i--) xs.push(dx0 + dw - kenar - bw / 2 - i * adim);
    const zArka = zMid + 0.25 + bd / 2, zOn = zMid + TEAM_D - 0.35 - bd / 2;
    const gang = place('dinlenme-gang', 'dinlenme', 'gang', dx0 + dw / 2, zMid + TEAM_D / 2, k);
    const satirlar = [[zArka, zArka + bd / 2 + 0.55], [zOn, zOn - bd / 2 - 0.55]];
    let i = 0;
    for (const [bz, az] of satirlar) {
      for (const bx of xs) {
        const id = `dinlenme-yatak-${i++}`;
        // laid out in base units at the bed's world size / K, so the whole room scales as one (no `ek`)
        place(id, 'dinlenme', 'yatak', bx, bz, place(`${id}-ayak`, 'dinlenme', 'ayak', bx, az, gang));
      }
    }
  }

  // front row: tea corner, the shared lounge, canteen (the Revir follows with the facilities)
  k = room('cay-ocagi', 'cay-ocagi', 'Çay ocağı', 0, zb, CAY_W, BOT_D, 'o1');
  place('cay-ocagi-tezgah', 'cay-ocagi', 'tezgah', 1.2, zb + 1.1, k);
  // the long counter (kettle, samovar, coffee machine, cups): two places to stand while getting a drink
  for (let i = 0; i < 2; i++) place(`cay-ocagi-tezgah-yer-${i}`, 'cay-ocagi', 'ayakta', 2.6 + 1.6 * i, zb + 2.0, k);
  // three small round tables with three stools each (idle agents sit there)
  const cayMasalari = [[2.4, zb + 4.6], [6.0, zb + 4.6], [9.4, zb + 4.6]];
  for (let i = 0; i < 9; i++) {
    const [tx, tz] = cayMasalari[Math.floor(i / 3)];
    const t = ((i % 3) * 2 * Math.PI) / 3;
    const id = place(`cay-ocagi-yer-${i}`, 'cay-ocagi', 'tabure', tx + 1.2 * Math.sin(t), tz + 1.2 * Math.cos(t), k);
    ek[id] = [tx, tz]; // the stool faces its table (hedef, set after scaling)
  }
  place('cay-ocagi-ozet', 'cay-ocagi', 'ozet', CAY_W - 1, zb + 1.2, k);
  // the staff's tea break (Sekreter 0, guard 1): never taken by the agents' tea spots
  for (let i = 0; i < 2; i++) place(`cay-ocagi-personel-${i}`, 'cay-ocagi', 'ayakta', 6.4 + 1.5 * i, zb + 2.0, k);
  place('cay-ocagi-personel-2', 'cay-ocagi', 'ayakta', 9.0, zb + 2.2, k); // the roaming staff's (personelRotasi)
  // the shared lounge (Ortak alan): one armchair per Claude model for its resident staff (kadro), spread over the
  // room's four corners around a low table, so their robots and labels never crowd
  const sx = CAY_W + TEAM_GAP;
  k = room('ortak-alan', 'ortak-alan', 'Ortak alan', sx, zb, SALON_W, BOT_D, 'o1');
  LOUNGE.forEach((f, i) => place(`ortak-alan-${f}`, 'ortak-alan', 'bekleme', sx + 1.7 + 8.6 * (i % 2), zb + 2.2 + 3.6 * Math.floor(i / 2), k));
  // two café tables in the middle with two chairs each: idle actors sit there with their cup
  const kafeMasalari = [[sx + SALON_W / 2, zb + 2.6], [sx + SALON_W / 2, zb + 5.6]];
  for (let i = 0; i < 4; i++) {
    const [tx, tz] = kafeMasalari[Math.floor(i / 2)];
    const id = place(`ortak-alan-yer-${i}`, 'ortak-alan', 'kafe', tx + (i % 2 ? 1.15 : -1.15), tz, k);
    ek[id] = [tx, tz];
  }
  // two places to stand and chat in the lounge (the roaming staff's: personelRotasi)
  for (let i = 0; i < 2; i++) place(`ortak-alan-sohbet-${i}`, 'ortak-alan', 'ayakta', sx + 4.0 + 4.0 * i, zb + 7.3, k);
  // the canteen sits between the cells under the common area (x 2 * TEAM_W .. the cells under the Revir), so the
  // facility cells fit left and right of it
  const yx = 2 * TEAM_W;
  const yw = Wc - (TEAM_W - TEAM_GAP) - TEAM_GAP - yx;
  // the canteen (owner decision 2026-11-12): a real chair for everyone who may be at lunch at once (yemekKapasitesi: the CEO,
  // the kadro, the auditors, every idle session the desks allow, the staff) — bands of eight chairs (four each side of a
  // table), growing downwards past the front row; it reaches the floor's edge (more bands where the room allows them);
  // the CEO's chair stays 'yemekhane-sandalye-7'
  const yd = D - zb;
  const bantlar = Math.max(izgara.bantlar, Math.floor((yd - BULASIK_D - 4.4) / YEMEK_BANT));
  // the Bulaşıkhane (owner decision 2026-11-12): a dishwashing corner at the canteen's far end, below the bands and the staff's
  // two chairs — a sink with a dishwasher, a rack and a tray trolley (scene); it never takes a chair's room
  const bz = zb + yd - BULASIK_D;
  k = room('yemekhane', 'yemekhane', 'Yemekhane', yx, zb, yw, yd, 'o1', {
    bulasik: { z: bz, lavabo: [yx + 2.2, zb + yd - 1.0], raf: [yx + 5.0, zb + yd - 0.8], araba: [yx + 7.8, zb + yd - 1.7],
      ocak: [yx + 10.2, zb + yd - 0.75], dolap: [yx + 12.6, zb + yd - 0.75] } });
  const yemekMasalari = [];
  for (let i = 0; i < bantlar * 8; i++) {
    const b = Math.floor(i / 8), j = i % 8;
    const z = zb + 2.4 + b * YEMEK_BANT + (j < 4 ? 0 : 2.4);
    place(`yemekhane-sandalye-${i}`, 'yemekhane', 'sandalye', yx + 1.6 + ((yw - 3.2) / 3) * (j % 4), z, k);
    if (j === 0) yemekMasalari.push([yx + 0.8, yx + yw - 0.8, zb + 3.6 + b * YEMEK_BANT]);
  }
  place('yemekhane-ozet', 'yemekhane', 'ozet', yx + yw - 1, zb + 1.2, k);
  // the Yemekhane sorumlusu's places (staff only, never a seat): the serving counter at the door, the end of each
  // band's table (where it collects the trays) and the sink of the Bulaşıkhane
  place(YEMEKHANE_SERVIS, 'yemekhane', 'servis', yx + 1.0, zb + 1.1, k);
  for (let b = 0; b < bantlar; b++) place(`yemekhane-masa-ucu-${b}`, 'yemekhane', 'servis', yx + yw - 0.45, zb + 3.6 + b * YEMEK_BANT, k);
  place(YEMEKHANE_BULASIK, 'yemekhane', 'servis', yx + 2.2, zb + yd - 2.1, k);
  place(YEMEKHANE_OCAK, 'yemekhane', 'servis', yx + 10.2, zb + yd - 2.1, k);
  place(YEMEKHANE_DOLAP, 'yemekhane', 'servis', yx + 12.6, zb + yd - 2.1, k);
  // two chairs after the last band for the staff's lunch (Sekreter, guard): never taken by the other canteen spots
  for (let i = 0; i < 2; i++) place(`yemekhane-personel-${i}`, 'yemekhane', 'sandalye', yx + 1.6 + 2.2 * i, zb + 2.4 + bantlar * YEMEK_BANT, k);

  // the cells (zeminIzgarasi): fixed facilities, then one bay per project (a manager's desk + N desks), then the empty
  // reserved bays. A cell's door opens onto the corridor above it (a top-row cell: below it); a cell with a corridor
  // below it gets a second door there (a facility only within the fixed rows, so it never changes with the projects).
  const koridorOf = (h) => (h.bolge === 'alt' && h.sutun < 2 ? 'a' : 'k');
  const bayOf = (h, son = false) => {
    const r = h.satir;
    // the bottom row's project / reserved cells reach the floor's edge
    const d = son && r === R - 1 ? D - h.z : TEAM_D;
    return { x0: h.x, z0: h.z, r, w: h.w, d, kor: `${koridorOf(h)}${r === 0 ? 0 : r - 1}`,
      alt: r > 0 && r < R - 1 ? `${koridorOf(h)}${r}` : null };
  };
  const tesisBay = (key) => { const [bolge, sutun, satir] = TESIS_HUCRELERI[key];
    if (bolge === 'on') return { x0: Wc - ROOM_W, z0: zb, w: ROOM_W, d: BOT_D, r: 0, kor: 'o1', alt: null };
    const b = bayOf(izgara.hucre(bolge, sutun, satir));
    return { ...b, alt: b.r > 0 && b.r < OLCU.EN_AZ_SATIR - 1 ? b.alt : null }; };
  // the fixed facilities first: Muhasebe (slot 0: a desk, shelves with binders, the accountant's seat) and the WC
  // (slot 1: a covered block with two doors at the back of the bay, two sinks beside it; the inside spots are hidden)
  // (slot 2 İdari işler, slot 3 İnsan kaynakları: offices like Muhasebe)
  for (const [key, ad] of Object.entries(TESIS_ODALARI)) {
    const { x0, z0, w: RW, d: OD, kor, alt: altKor } = tesisBay(key);
    const kk = room(key, key, ad, x0, z0, RW, OD, kor);
    const did = `${key}-masa`;
    place(did, key, 'masa', x0 + RW / 2, z0 + 3.6, kk);
    ek[place(`${did}-yan`, key, 'yan', x0 + RW / 2 + 1.3, z0 + 3.6, did)] = [x0 + RW / 2, z0 + 3.6];
    if (key === 'sunucu') { // the cabinets (drawn by the scene from r.sunucu) and the admin's spot in front of them
      const r = odalar[odalar.length - 1];
      r.sunucu = { gruplar: [[x0 + 2.6, z0 + 1.0], [x0 + RW - 2.6, z0 + 1.0]], kabin: SUNUCU_KABIN };
      const [g0, g1] = r.sunucu.gruplar;
      ek[place(SUNUCU_KABIN_YERI, key, 'kabin', g0[0], g0[1] + 1.6, kk)] = g0; // faces the cabinets (yuzAcisi)
      // the IT team (IT_EKIBI): the colleague who helps during a warning stands at the right group; an off-shift
      // colleague in the office sits at the second desk (bottom left), the on-shift one at the room's desk
      ek[place(SUNUCU_KABIN_YERI_2, key, 'kabin', g1[0], g1[1] + 1.6, kk)] = g1;
      place(IT_ARKADAS_MASASI, key, 'masa', x0 + 2.8, z0 + 6.0, did);
      // the IT güvenlik desk (plan "Sonraki iş (9)"): the IT güvenlik uzmanı — the security reviewer's runs — types here
      place(denetciMasasi(GUVENLIK), key, 'masa', x0 + RW - 2.8, z0 + 6.0, did);
    }
    if (key === 'arge') { // the whiteboard (back wall, left of the door), the bookshelf (right wall) and a second desk
      odalar[odalar.length - 1].arge = { tahta: [x0 + 2.8, z0 + 0.7], kitaplik: [x0 + RW - 0.7, z0 + 5.4] };
      place(ARGE_MASA_2, key, 'masa', x0 + 2.8, z0 + 6.0, did);
    }
    if (key === 'masaj') { // two massage tables in front, the masseur's spot beside each
      [x0 + 3.0, x0 + 8.4].forEach((x, i) => {
        const y = place(`masaj-yatak-${i}`, key, 'masaj-yatagi', x, z0 + 6.8, kk);
        ek[y] = [x, z0 + 6.8];
        ek[place(`masaj-yatak-${i}-yan`, key, 'yan', x + 1.4, z0 + 6.8, y)] = [x, z0 + 6.8];
      });
    }
    if (altKor) { // a second door onto the corridor below
      const alt = node(`${key}-kapi-alt`, x0 + RW / 2, z0 + TEAM_D, 'kapi', key);
      doorsOn[altKor].push(alt);
      edge(alt, did);
      if (key === 'masaj') { edge(alt, 'masaj-yatak-0'); edge(alt, 'masaj-yatak-1'); }
    }
  }
  // slots 4 and 5 (one above the other): the "Sosyal medya ve tasarım" department — the platform pod in the first
  // room, the creative and influencer pods in the studio (a mood board, a ring light, a camera); no real work yet
  for (const [key, ad, grup] of [['sosyal', 'Sosyal medya ve tasarım', ['platform']],
    ['sosyal-studyo', 'Sosyal medya ve tasarım · stüdyo', ['yaratici', 'influencer']]]) {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay(key);
    const kk = room(key, 'sosyal', ad, x0, z0, RW, TEAM_D, kor);
    const uyeler = SOSYAL_EKIBI.filter((u) => grup.includes(u.grup));
    const masalar = uyeler.map((u, i) => {
      const did = sosyalMasasi(u.id);
      // pods: three desks a row, 3.6 apart; a new pod starts a new row
      const pod = grup.indexOf(u.grup);
      const inPod = uyeler.filter((x) => x.grup === u.grup).indexOf(u);
      const rowsBefore = grup.slice(0, pod).reduce((n, g) => n + Math.ceil(uyeler.filter((x) => x.grup === g).length / 3), 0);
      place(did, key, 'masa', x0 + 2.4 + 3.6 * (inPod % 3), z0 + 2.6 + 2.5 * (rowsBefore + Math.floor(inPod / 3)), kk);
      return did;
    });
    if (altKor) {
      const alt = node(`${key}-kapi-alt`, x0 + RW / 2, z0 + TEAM_D, 'kapi', key);
      doorsOn[altKor].push(alt);
      for (const did of masalar) edge(alt, did);
    }
  }
  // slots 7 and 8: the Spor salonu (two treadmills, an exercise bike, a weight bench, mats) and the Duş beside it (a
  // covered block with two shower cubicles, like the WC). Idle actors only (molaPlani 'spor'); mats 2 and 3 are the
  // off-duty staff's
  {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay('spor');
    const kk = room('spor', 'spor', 'Spor salonu', x0, z0, RW, TEAM_D, kor);
    const alet = (id, tur, x, z) => { const n = place(id, 'spor', tur, x, z, kk); ek[n] = [x, z]; return n; };
    const spots = [alet('spor-kosu-0', 'spor-kosu', x0 + 2.2, z0 + 3.0), alet('spor-kosu-1', 'spor-kosu', x0 + 4.4, z0 + 3.0),
      alet('spor-bisiklet', 'spor-bisiklet', x0 + 6.8, z0 + 3.0), alet('spor-agirlik', 'spor-agirlik', x0 + 9.6, z0 + 3.0)];
    for (let i = 0; i < 4; i++) spots.push(alet(`spor-mat-${i}`, 'spor-mat', x0 + 2.4 + 2.4 * i, z0 + 6.8));
    if (altKor) {
      const alt = node('spor-kapi-alt', x0 + RW / 2, z0 + TEAM_D, 'kapi', 'spor');
      doorsOn[altKor].push(alt);
      for (const n of spots) edge(alt, n);
    }
  }
  {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay('dus');
    const kk = room('dus', 'dus', 'Duş', x0, z0, RW, TEAM_D, kor,
      { blok: { x: x0 + 0.8, z: z0 + 0.8, w: 4.6, d: 4.4 } });
    const gecit = place('dus-gecit', 'dus', 'gecit', x0 + 6.6, z0 + 6.2, kk);
    let prevDoor = gecit;
    [x0 + 4.25, x0 + 1.95].forEach((x, j) => {
      const i = 1 - j;
      const kapi = place(`dus-kapi-${i}`, 'dus', 'dus-kapi', x, z0 + 6.2, prevDoor);
      place(`dus-ici-${i}`, 'dus', 'dus-ic', x, z0 + 3, kapi);
      prevDoor = kapi;
    });
    place('dus-bank', 'dus', 'gecit', x0 + 9.4, z0 + 7.2, gecit); // a bench and towel hooks (scene)
    if (altKor) {
      const alt = node('dus-kapi-alt', x0 + RW / 2, z0 + TEAM_D, 'kapi', 'dus');
      doorsOn[altKor].push(alt);
      edge(alt, gecit);
    }
  }
  {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay('wc');
    const kk = room('wc', 'wc', 'WC', x0, z0, RW, TEAM_D, kor,
      { blok: { x: x0 + 0.8, z: z0 + 0.8, w: 4.6, d: 4.4 } });
    // the walk goes round the block: the room door -> a passage spot right of the block -> the cubicle doors
    const gecit = place('wc-gecit', 'wc', 'gecit', x0 + 6.6, z0 + 6.2, kk);
    let prevDoor = gecit;
    [x0 + 4.25, x0 + 1.95].forEach((x, j) => {
      const i = 1 - j;
      const kapi = place(`wc-kapi-${i}`, 'wc', 'wc-kapi', x, z0 + 6.2, prevDoor);
      place(`wc-ici-${i}`, 'wc', 'wc-ic', x, z0 + 3, kapi);
      prevDoor = kapi;
    });
    [x0 + 8.4, x0 + 10.2].forEach((x, i) => place(`wc-lavabo-${i}`, 'wc', 'lavabo', x, z0 + 7.2, gecit));
    if (altKor) { // its second door onto the corridor below, like a team bay
      const alt = node('wc-kapi-alt', x0 + RW / 2, z0 + TEAM_D, 'kapi', 'wc');
      doorsOn[altKor].push(alt);
      edge(alt, gecit);
    }
  }
  // the Konferans salonu: a screen on the back wall (left of the door), the lectern right of it facing the room, and
  // SALON_SIRA rows of SALON_KOLTUK chairs facing the screen; a second door onto the corridor below
  {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay('konferans');
    const kk = room('konferans', 'konferans', 'Konferans salonu', x0, z0, RW, TEAM_D, kor,
      { salon: { ekran: [x0 + 3.0, z0 + 0.35] } });
    place(SALON_KURSU, 'konferans', 'kursu', x0 + 9.0, z0 + 2.9, kk);
    const koltuklar = [];
    for (let i = 0; i < SALON_SIRA * SALON_KOLTUK; i++) {
      koltuklar.push(place(`konferans-sandalye-${i}`, 'konferans', 'sandalye', x0 + 1.6 + 1.75 * (i % SALON_KOLTUK),
        z0 + 4.7 + 1.55 * Math.floor(i / SALON_KOLTUK), kk));
    }
    if (altKor) {
      const alt = node('konferans-kapi-alt', x0 + RW / 2, z0 + TEAM_D, 'kapi', 'konferans');
      doorsOn[altKor].push(alt);
      for (const n of koltuklar) edge(alt, n);
    }
  }
  // the company structure (plan "Sonraki iş (9)", owner decision 2026-11-13): two cells of glass manager offices, two offices side
  // by side in each (a door on the corridor above and below), every office a manager's desk with the spot beside it where
  // a file is handed over; the Yazılım Müdürü's office also has the planning desk (plan steps and planlama work type
  // there), the others a visitor's spot (a meeting). The QA odası (the testers' desks: kod reviews run by Claude) and the
  // Analist odası (the business analysts' desks: plan reviews run by Claude), each with four desks in two rows.
  for (const hucre of ['mudurluk-1', 'mudurluk-2']) {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay(hucre);
    const OW = (RW - MUDURLUK_ARA) / 2;
    MUDURLUKLER.filter((m) => m.hucre === hucre).forEach((m, j) => {
      const id = mudurlukOdasi(m.key);
      const ox = x0 + j * (OW + MUDURLUK_ARA);
      const kk = room(id, 'mudurluk', m.oda, ox, z0, OW, TEAM_D, kor, { alan: m.key });
      const did = mudurMasasi(m.key);
      const mx = ox + OW / 2;
      place(did, id, 'mudur-masasi', mx, z0 + 2.6, kk);
      ek[place(`${did}-yan`, id, 'yan', mx + 1.3, z0 + 2.6, did)] = [mx, z0 + 2.6];
      const icerde = [did];
      if (m.key === 'yazilim') { desk(PLAN_MASASI, id, 'masa', mx, z0 + 6.4, kk); icerde.push(PLAN_MASASI); }
      else icerde.push(place(`${id}-ziyaret`, id, 'ziyaret', mx - 1.2, z0 + 6.6, kk));
      if (altKor) {
        const alt = node(`${id}-kapi-alt`, mx, z0 + TEAM_D, 'kapi', id);
        doorsOn[altKor].push(alt);
        for (const n of icerde) edge(alt, n);
      }
    });
  }
  for (const [key, ad] of [['qa', 'QA odası'], ['analist', 'Analist odası']]) {
    const { x0, z0, w: RW, kor, alt: altKor } = tesisBay(key);
    const kk = room(key, key, ad, x0, z0, RW, TEAM_D, kor);
    const masalar = [];
    for (let i = 0; i < EKIP_ODASI_MASA; i++) {
      const did = `${key}-masa-${i}`;
      desk(did, key, 'masa', x0 + 3.0 + 6.0 * (i % 2), z0 + 2.4 + 3.6 * Math.floor(i / 2), kk);
      masalar.push(did);
    }
    place(`${key}-ozet`, key, 'ozet', x0 + RW - 1, z0 + 1.2, kk);
    if (key === 'qa') masalar.push(place(QA_MUDUR_YERI, key, 'ayakta', x0 + RW / 2, z0 + 8.4, kk));
    if (altKor) {
      const alt = node(`${key}-kapi-alt`, x0 + RW / 2, z0 + TEAM_D, 'kapi', key);
      doorsOn[altKor].push(alt);
      for (const n of masalar) edge(alt, n);
    }
  }
  names.forEach((p, i) => {
    const { x0, z0, w: RW, d: BD, kor, alt: altKor } = bayOf(izgara.hucreler[i], true);
    const id = `ekip-${p}`;
    const kk = room(id, 'ekip', p, x0, z0, RW, BD, kor, { proje: p });
    const desks = [];
    const ekipMasasi = (did, x, z) => { desk(did, id, did.endsWith('-mudur') ? 'mudur-masasi' : 'masa', x, z, kk); desks.push(did); };
    ekipMasasi(`${id}-mudur`, x0 + RW / 2, z0 + 2.4);
    // plan 7: the visitor spot beside the manager's desk, where the CEO hands a new job's file to the sorumlu
    ek[place(`${id}-mudur-ziyaret`, id, 'ziyaret', x0 + RW / 2 + 2.6, z0 + 2.4, kk)] = [x0 + RW / 2, z0 + 2.4];
    for (let d = 0; d < N; d++) ekipMasasi(`${id}-masa-${d + 1}`, x0 + 2 + DESK_DX * (d % 3), z0 + 5.3 + DESK_DZ * Math.floor(d / 3));
    place(`${id}-ozet`, id, 'ozet', x0 + RW - 1, z0 + 1.2, kk);
    if (altKor) { // a second door onto the corridor below
      const alt = node(`${id}-kapi-alt`, x0 + RW / 2, z0 + TEAM_D, 'kapi', id);
      doorsOn[altKor].push(alt);
      for (const did of desks) edge(alt, did);
    }
  });
  for (let j = 0; j < izgara.yedek; j++) {
    const { x0, z0, w, d, kor } = bayOf(izgara.hucreler[T + j], true);
    room(`bos-ekip-${j + 1}`, 'bos-ekip', 'Boş ekip alanı · yeni proje', x0, z0, w, d, kor);
  }
  let otel = null; // the hotel outside the floor (laid out with the lobby: its path starts at the entrance)
  // the lobby (Giriş) in the floor's front-right corner, two cells wide, its door on the wing corridor above it: the
  // lift in its back wall at the right with the guard's post beside it, the Sekreter's reception desk in front of them,
  // and a guest waiting area on the left (six armchairs in two rows — the queued jobs wait there —, a low table,
  // plants, a water dispenser)
  {
    const { x: x0, z: z0, w, d } = izgara.lobi;
    const kk = room('lobi', 'lobi', 'Giriş', x0, z0, w, d, `k${R - 2}`,
      { lobi: { sehpa: [x0 + 5.2, z0 + 7.7], su: [x0 + 11.3, z0 + 1.0], bitkiler: [[x0 + 0.8, z0 + 0.9], [x0 + 0.8, z0 + d - 0.8],
        [x0 + 15.5, z0 + 0.9]] } });
    for (let i = 0; i < 6; i++) place(`lobi-koltuk-${i}`, 'lobi', 'bekleme', x0 + 2.6 + 2.6 * (i % 3), z0 + 3.0 + 2.8 * Math.floor(i / 3), kk);
    place('lobi-ozet', 'lobi', 'ozet', x0 + 10.6, z0 + 3.0, kk);
    place('asansor', 'lobi', 'asansor', x0 + w - 1.6, z0 + 1.2, kk); // the lift doors are in the lobby's back wall
    place('lobi-nobet', 'lobi', 'nobet', x0 + w - 3.2, z0 + 1.6, kk); // the security guard, beside the lift
    place('lobi-resepsiyon', 'lobi', 'resepsiyon', x0 + w - 7, z0 + 6.4, kk); // the secretary's reception desk
    place('lobi-karsilama', 'lobi', 'karsilama', x0 + w - 2.4, z0 + 2.2, kk); // where the guard greets an arrival
    place('lobi-su', 'lobi', 'su', x0 + 11.3, z0 + 2.2, kk); // in front of the water dispenser (the duty staff's break)
    // the Otel (the city, step 1): out through the lobby's entrance gap (its front, where the outer wall opens), a
    // short path across the yard to the hotel's door in its back wall, facing the office. The lobby's middle is clear
    // from its back door to the entrance (the armchairs are on the left, the reception desk on the right). Inside, a
    // hall node and one room node per guest in a grid (hidden spots: the building is closed).
    const cxL = x0 + w / 2;
    const { W: ow, D: od, ARA } = OTEL_OLCU;
    const giris = place('lobi-giris', 'lobi', 'giris', cxL, z0 + d, kk);
    const yolu = place('otel-yol', null, 'dis', cxL, z0 + d + ARA / 2, giris);
    otel = { id: 'otel', tur: 'otel', ad: 'Otel', x: cxL - ow / 2, z: z0 + d + ARA, w: ow, d: od, kapi: null, katlar: 2 };
    otel.kapi = place('otel-kapi', 'otel', 'kapi', cxL, otel.z, yolu);
    const hol = place('otel-hol', 'otel', 'hol', cxL, otel.z + 1.2, otel.kapi);
    const sutun = OTEL_ODA / 4;
    for (let i = 0; i < OTEL_ODA; i++) {
      place(`${OTEL_ON_EK}${i}`, 'otel', 'otel-oda', otel.x + 1 + (ow - 2) * ((i % sutun) + 0.5) / sutun,
        otel.z + 2.2 + (od - 3) * (Math.floor(i / sutun) + 0.5) / 4, hol);
    }
  }

  // the Sigara odası: an open-air terrace in front of the tea corner (the cell SIGARA_HUCRESI, off the left aisle; fixed
  // for any number of projects). The owner, 2026-11-12: room for about eight — the smoking corner at its left end (a standing
  // ashtray with four places around it: 0-2 the agents', 3 the guard's; 4 the roaming staff's), two benches (two seats
  // each: 5-8) and a place at the railing (9); plants and the railing (scene). SIGARA_AJAN_YERLERI = the agents' ones.
  let bankBak = null;
  {
    const { x0, z0, w, kor } = bayOf(izgara.hucre(...SIGARA_HUCRESI));
    const kul = [x0 + 2.4, z0 + 5.0];
    const banklar = [[x0 + 8.4, z0 + 8.75, 3.2, 0], [x0 + 11.1, z0 + 4.6, 3.0, 1]]; // [x, z, length, along z]
    const kapi = room('sigara', 'balkon', 'Sigara odası', x0, z0, w, TEAM_D, kor,
      { balkon: { kul, banklar, bitkiler: [[x0 + 0.8, z0 + 8.8], [x0 + 11.2, z0 + 0.9], [x0 + 6.2, z0 + 6.0]] } });
    [[-1.1, -1.2], [1.1, -1.2], [-1.1, 1.3], [1.1, 1.3]].forEach(([dx, dz], i) => {
      ek[place(`sigara-yer-${i}`, 'sigara', 'sigara', kul[0] + dx, kul[1] + dz, kapi)] = kul; });
    place('sigara-yer-4', 'sigara', 'sigara', x0 + 2.4, z0 + 8.2, kapi);
    const seats = [[banklar[0], -0.8, 0], [banklar[0], 0.8, 0], [banklar[1], 0, -0.7], [banklar[1], 0, 0.7]];
    seats.forEach(([b, dx, dz], i) => { ek[place(`sigara-yer-${5 + i}`, 'sigara', 'bank', b[0] + dx, b[1] + dz, kapi)] = [b[0], b[1]]; });
    place('sigara-yer-9', 'sigara', 'sigara', x0 + 7.4, z0 + 2.2, kapi);
    bankBak = [x0 + w / 2, z0 + TEAM_D / 2];
    // the terrace is drawn last (after the bays), like before
    odalar.push(odalar.splice(odalar.findIndex((r) => r.id === 'sigara'), 1)[0]);
  }

  // corridors: in the common area from the left aisle to the spine, in the wing from the spine (or the cells under the
  // Revir) to the right aisle, under the common area from the left aisle to the cells left of the canteen; the spine
  // joins the common and the wing corridors (they run at slightly different depths), the left aisle the common
  // corridors and the ones left of the canteen
  const omurga = [];
  const yolu = (c, solId, sagId, x0, x1) => {
    const z = corridorZ[c];
    const ids = [node(solId, x0, z, 'koridor'), node(sagId, x1, z, 'koridor')];
    const prefix = c[0] === 'o' ? `koridor-${c.slice(1)}` : c[0] === 'a' ? `alt-${c.slice(1)}` : `kanat-${c.slice(1)}`;
    for (const door of doorsOn[c]) {
      const cid = `${prefix}-${dugumler[door].x}`;
      if (!dugumler[cid]) ids.push(node(cid, dugumler[door].x, z, 'koridor'));
      edge(door, cid);
    }
    ids.sort((a, b) => dugumler[a].x - dugumler[b].x);
    for (let i = 1; i < ids.length; i++) edge(ids[i - 1], ids[i]);
  };
  yolu('o0', 'koridor-0-sol', 'koridor-0-sag', -1, omurgaX);
  yolu('o1', 'koridor-1-sol', 'koridor-1-sag', -1, omurgaX);
  edge('koridor-0-sol', 'koridor-1-sol');
  let solUc = 'koridor-1-sol';
  for (let c = TESIS_SATIR - 2; c < R - 1; c++) {
    yolu(`a${c}`, `alt-${c}-sol`, `alt-${c}-sag`, -1, TEAM_W + (TEAM_W - TEAM_GAP) / 2);
    edge(solUc, `alt-${c}-sol`);
    solUc = `alt-${c}-sol`;
  }
  omurga.push('koridor-0-sag', 'koridor-1-sag');
  for (let c = 0; c < R - 1; c++) {
    // a wing corridor at the depth of a common one shares its spine node (no two nodes on one spot)
    const ortakKor = ['o0', 'o1'].find((o) => Math.abs(corridorZ[o] - corridorZ[`k${c}`]) < 1e-9);
    const sol = ortakKor ? `koridor-${ortakKor.slice(1)}-sag` : `kanat-${c}-omurga`;
    yolu(`k${c}`, sol, `kanat-${c}-sag`, omurgaX, W + 1);
    if (!ortakKor) omurga.push(sol);
    if (c > 0) edge(`kanat-${c - 1}-sag`, `kanat-${c}-sag`);
  }
  omurga.sort((a, b) => dugumler[a].z - dugumler[b].z);
  for (let i = 1; i < omurga.length; i++) edge(omurga[i - 1], omurga[i]);

  // scale the layout (OLCU.K): rooms and places grow apart, furniture-bound spots keep their distance to it
  const { K } = OLCU;
  const r2 = (v) => +v.toFixed(2);
  for (const n of Object.values(dugumler)) {
    const a = ek[n.id];
    if (a) { n.x = r2(a[0] * K + (n.x - a[0])); n.z = r2(a[1] * K + (n.z - a[1])); }
    else { n.x = r2(n.x * K); n.z = r2(n.z * K); }
    if (n.tur === 'tabure' || n.tur === 'kafe' || n.tur === 'oyun-yer') n.hedef = [r2(a[0] * K), r2(a[1] * K)];
    if (n.tur === 'bank') n.hedef = [r2(bankBak[0] * K), r2(bankBak[1] * K)]; // a bench seat faces the terrace
  }
  for (const r of odalar) {
    r.x = r2(r.x * K); r.z = r2(r.z * K); r.w = r2(r.w * K); r.d = r2(r.d * K);
    if (r.blok) r.blok = { x: r2(r.blok.x * K), z: r2(r.blok.z * K), w: r2(r.blok.w * K), d: r2(r.blok.d * K) };
    const sc = ([x, z, ...rest]) => [r2(x * K), r2(z * K), ...rest];
    if (r.balkon) { // the terrace's furniture: positions scale, sizes stay
      r.balkon = { kul: sc(r.balkon.kul), banklar: r.balkon.banklar.map(sc), bitkiler: r.balkon.bitkiler.map(sc) };
    }
    if (r.bulasik) {
      const b = r.bulasik;
      r.bulasik = { z: r2(b.z * K), lavabo: sc(b.lavabo), raf: sc(b.raf), araba: sc(b.araba), ocak: sc(b.ocak), dolap: sc(b.dolap) };
    }
    if (r.lobi) r.lobi = { sehpa: sc(r.lobi.sehpa), su: sc(r.lobi.su), bitkiler: r.lobi.bitkiler.map(sc) }; // its furniture
    if (r.salon) r.salon = { ekran: sc(r.salon.ekran) }; // the hall's screen (the lectern: its node)
    if (r.sunucu) r.sunucu = { gruplar: r.sunucu.gruplar.map(sc), kabin: r.sunucu.kabin }; // cabinet groups: sizes stay
    if (r.arge) r.arge = { tahta: sc(r.arge.tahta), kitaplik: sc(r.arge.kitaplik) }; // the Ar-Ge odası: sizes stay
  }
  if (otel) Object.assign(otel, { x: r2(otel.x * K), z: r2(otel.z * K), w: r2(otel.w * K), d: r2(otel.d * K) });
  const sokak = otel ? sokakDuzeni(r2(W * K), r2(D * K), dugumler[otel.kapi].x) : null;
  const plan = { genislik: r2(W * K), derinlik: r2(D * K),
    yemek_masalari: yemekMasalari.map(([a, b, z]) => [r2(a * K), r2(b * K), r2(z * K)]), masa_sayisi: N, projeler: names, denetciler,
    odalar, dugumler, kenarlar, cay_masalari: cayMasalari.map(([x, z]) => [r2(x * K), r2(z * K)]),
    kafe_masalari: kafeMasalari.map(([x, z]) => [r2(x * K), r2(z * K)]),
    oyun: { pingpong: [r2(ping[0] * K), r2(ping[1] * K)], bilardo: [r2(bil[0] * K), r2(bil[1] * K)],
      dart: [r2(dart[0] * K), r2(dart[1] * K)] },
    ortak: { x: 0, z: 0, w: r2(Wc * K), d: r2((zb + BOT_D) * K) },
    kanat: { x: r2(kx0 * K), z: 0, w: r2((W - kx0) * K), d: r2(D * K), sutun: C, satir: R, yedek: izgara.yedek },
    omurga: { x: r2(omurgaX * K) },
    // the hotel outside the floor (never in odalar: the floor's rooms stay inside genislik × derinlik); dis = the
    // rectangle of everything outside the floor (the path and the hotel), for the camera's pan bounds and the shadows
    // (since the city step 2 also the street, which runs past both ends of the floor: sokak)
    otel, sokak, dis: otel ? { x: Math.min(otel.x, sokak.x0), z: r2(D * K), w: r2(Math.max(otel.x + otel.w, sokak.x1) - Math.min(otel.x, sokak.x0)),
      d: r2(otel.z + otel.d - D * K) } : null };
  mobilyadanKacin(plan);
  Object.defineProperty(plan, 'yol', { value: (a, b) => yol(plan, a, b), enumerable: false });
  return plan;
}

// --- furniture: the boxes a walk must go around (world units; web/scene.js draws the same pieces at these sizes) ---

// A desk's scale in the scene (x, y, z): a normal desk and the manager's / CEO's desk; the desk stands in front of its
// chair (the node): its depth starts 0.62 in front of the node.
export const MASA_OLCU = [1.05, 1.25, 1.2];
export const PATRON_MASA_OLCU = [1.15, 1.3, 1.25];
const MASA_W = 2.2, MASA_D = 1.1;
// [{id, x0, x1, z0, z1}]: desks, the canteen's band tables, the tea corner's and the lounge's round tables, the game
// tables, the lobby's low table and the covered WC / shower blocks.
export function mobilyaKutulari(plan) {
  const out = [];
  const nodes = (plan && plan.dugumler) || {};
  const kutu = (id, cx, cz, w, d) => out.push({ id, x0: cx - w / 2, x1: cx + w / 2, z0: cz - d / 2, z1: cz + d / 2 });
  for (const n of Object.values(nodes)) {
    if (n.tur === 'yatak' && n.oda === 'dinlenme') kutu(`yatak:${n.id}`, n.x, n.z, YATAK_OLCU[0], YATAK_OLCU[1]);
    if (n.tur !== 'masa' && n.tur !== 'mudur-masasi') continue;
    const s = n.tur === 'mudur-masasi' || n.oda === 'ceo' ? PATRON_MASA_OLCU : MASA_OLCU;
    out.push({ id: `masa:${n.id}`, x0: n.x - (MASA_W / 2) * s[0], x1: n.x + (MASA_W / 2) * s[0], z0: n.z + 0.62,
      z1: n.z + 0.62 + MASA_D * s[2] });
  }
  for (const [x0, x1, z] of plan.yemek_masalari || []) out.push({ id: `yemek-masasi:${z}`, x0, x1, z0: z - 0.6, z1: z + 0.6 });
  for (const [x, z] of plan.cay_masalari || []) kutu(`cay-masasi:${x}`, x, z, 1.4, 1.4);
  for (const [x, z] of plan.kafe_masalari || []) kutu(`kafe-masasi:${z}`, x, z, 1.3, 1.3);
  const o = plan.oyun || {};
  if (o.pingpong) kutu('pingpong', o.pingpong[0], o.pingpong[1], 2.7, 1.6);
  if (o.bilardo) kutu('bilardo', o.bilardo[0], o.bilardo[1], 2.6, 1.55);
  for (const r of plan.odalar || []) {
    if (r.blok) out.push({ id: `blok:${r.id}`, x0: r.blok.x, x1: r.blok.x + r.blok.w, z0: r.blok.z, z1: r.blok.z + r.blok.d, blok: true });
    if (r.lobi && r.lobi.sehpa) kutu('lobi-sehpa', r.lobi.sehpa[0], r.lobi.sehpa[1], 3.5, 1.4);
    if (r.sunucu) r.sunucu.gruplar.forEach(([x, z], i) => kutu(`sunucu-kabin:${i}`, x, z, r.sunucu.kabin * KABIN_OLCU[0], KABIN_OLCU[2]));
    if (r.arge) {
      kutu('arge-tahta', r.arge.tahta[0], r.arge.tahta[1], ...ARGE_TAHTA_OLCU);
      kutu('arge-kitaplik', r.arge.kitaplik[0], r.arge.kitaplik[1], ...ARGE_KITAPLIK_OLCU);
    }
  }
  return out;
}

const icinde = (p, b, m = 0) => p.x > b.x0 + m && p.x < b.x1 - m && p.z > b.z0 + m && p.z < b.z1 - m;
// Does the open segment a-b pass through box b (shrunk by m)? Liang-Barsky clipping.
function kesiyor(a, c, b, m = 0.05) {
  const x0 = b.x0 + m, x1 = b.x1 - m, z0 = b.z0 + m, z1 = b.z1 - m;
  let t0 = 0, t1 = 1;
  const dx = c.x - a.x, dz = c.z - a.z;
  for (const [p, q] of [[-dx, a.x - x0], [dx, x1 - a.x], [-dz, a.z - z0], [dz, z1 - a.z]]) {
    if (Math.abs(p) < 1e-12) { if (q < 0) return false; continue; }
    const r = q / p;
    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; } else { if (r < t0) return false; if (r < t1) t1 = r; }
  }
  return t1 - t0 > 1e-6 && t0 < 1 - 1e-6 && t1 > 1e-6;
}
// The boxes a segment between two nodes must not cross: a covered block is entered only by its own cubicles.
function engeller(boxes, a, b) {
  return boxes.filter((x) => !(x.blok && (/-ic$/.test(a.tur || '') || /-ic$/.test(b.tur || ''))) && !icinde(a, x, 0.02) && !icinde(b, x, 0.02));
}
export function kenarMobilyadan(plan, a, b, boxes = mobilyaKutulari(plan)) {
  const A = plan.dugumler[a], B = plan.dugumler[b];
  if (!A || !B) return null;
  return engeller(boxes, A, B).find((x) => kesiyor(A, B, x)) || null;
}

// Re-routes every edge that would walk through a piece of furniture around it: the shortest way through the corners of
// the room's furniture (each 0.6 off the box, inside the room), as new waypoints (tur 'gecit', never a break spot).
function mobilyadanKacin(plan) {
  const boxes = mobilyaKutulari(plan);
  if (!boxes.length) return;
  const nodes = plan.dugumler;
  const rooms = new Map(plan.odalar.map((r) => [r.id, r]));
  const odaIci = (p, r, m) => p.x > r.x + m && p.x < r.x + r.w - m && p.z > r.z + m && p.z < r.z + r.d - m;
  const kose = new Map(); // room id -> its furniture corners
  const koseler = (r) => {
    if (kose.has(r.id)) return kose.get(r.id);
    const list = [];
    for (const b of boxes) {
      if (b.blok || b.x1 < r.x || b.x0 > r.x + r.w || b.z1 < r.z || b.z0 > r.z + r.d) continue;
      for (const [x, z] of [[b.x0 - 0.6, b.z0 - 0.6], [b.x1 + 0.6, b.z0 - 0.6], [b.x0 - 0.6, b.z1 + 0.6], [b.x1 + 0.6, b.z1 + 0.6]]) {
        const p = { x: +x.toFixed(2), z: +z.toFixed(2) };
        if (odaIci(p, r, 0.35) && !kutulariOf(r).some((o) => icinde(p, o, -0.1))) list.push(p);
      }
    }
    kose.set(r.id, list);
    return list;
  };
  const odaKutulari = new Map(); // room id -> the boxes inside it (a walk inside a room meets only those)
  const kutulariOf = (r) => {
    if (!odaKutulari.has(r.id)) {
      odaKutulari.set(r.id, boxes.filter((b) => !(b.x1 < r.x || b.x0 > r.x + r.w || b.z1 < r.z || b.z0 > r.z + r.d)));
    }
    return odaKutulari.get(r.id);
  };
  const gorunurler = new Map(); // room id -> corner x corner: the straight walk between them is clear
  const gorunur = (r) => {
    if (!gorunurler.has(r.id)) {
      const pts = koseler(r);
      const eng = kutulariOf(r).filter((x) => !x.blok);
      gorunurler.set(r.id, pts.map((p) => pts.map((q) => p !== q && !eng.some((x) => kesiyor(p, q, x)))));
    }
    return gorunurler.get(r.id);
  };
  const yeniKenarlar = [];
  for (const [a, b] of plan.kenarlar) {
    const A = nodes[a], B = nodes[b];
    const odalar = A && B ? [...new Set([A.oda, B.oda])].map((id) => rooms.get(id)).filter(Boolean) : [];
    const eng = odalar.length ? engeller(odalar.flatMap(kutulariOf), A, B) : [];
    const temiz = (p, q) => !eng.some((x) => kesiyor(p, q, x));
    if (!A || !B || temiz(A, B)) { yeniKenarlar.push([a, b]); continue; }
    const r = rooms.get(A.oda) || rooms.get(B.oda);
    const pts = r ? koseler(r) : [];
    const gor = r ? gorunur(r) : [];
    // Dijkstra on the visibility graph {A, corners, B} (corner-to-corner visibility is computed once per room)
    const all = [A, ...pts, B];
    const n = all.length;
    const acik = (u, v) => {
      if (u > 0 && u < n - 1 && v > 0 && v < n - 1) return gor[u - 1][v - 1];
      return temiz(all[u], all[v]);
    };
    const dist = all.map(() => Infinity); const back = all.map(() => -1); const done = all.map(() => false);
    dist[0] = 0;
    for (;;) {
      let u = -1;
      for (let i = 0; i < n; i++) if (!done[i] && dist[i] < Infinity && (u < 0 || dist[i] < dist[u])) u = i;
      if (u < 0 || u === n - 1) break;
      done[u] = true;
      for (let v = 0; v < n; v++) {
        if (done[v] || v === u) continue;
        const d = dist[u] + Math.hypot(all[u].x - all[v].x, all[u].z - all[v].z);
        if (d < dist[v] - 1e-9 && acik(u, v)) { dist[v] = d; back[v] = u; }
      }
    }
    if (dist[all.length - 1] === Infinity) { yeniKenarlar.push([a, b]); continue; }
    const seq = [];
    for (let v = back[all.length - 1]; v > 0; v = back[v]) seq.unshift(all[v]);
    let prev = a;
    let i = 0;
    for (const p of seq) {
      const id = `gecit:${a}>${b}:${i++}`; // named after its edge: the same in every plan that has the edge
      nodes[id] = { id, x: p.x, z: p.z, tur: 'gecit', oda: r ? r.id : null };
      yeniKenarlar.push([prev, id]);
      prev = id;
    }
    yeniKenarlar.push([prev, b]);
  }
  plan.kenarlar.length = 0;
  plan.kenarlar.push(...yeniKenarlar);
}

// The scene's walking speed (world units per second; web/scene.js walks every actor at it). The engine uses it to give
// a duty trip (the Sekreter's, a visit, a greeting, a CEO round stop) the time the walk really takes.
export const YURUME_HIZI = 4;
// The graph of a plan, built once per plan object (the plan never changes after ofisPlani): the adjacency with edge
// lengths and a cache of the shortest walks (the graph is static, so a walk is computed once per (from, to)).
const grafCache = new WeakMap();
// a list read off the plan's nodes (the same plan always gives the same list; a plan is never changed once built):
// computed once per plan, not on every tick
const planListeleri = new WeakMap();
function planListesi(plan, ad, yap) {
  let m = planListeleri.get(plan);
  if (!m) planListeleri.set(plan, m = new Map());
  if (!m.has(ad)) m.set(ad, yap());
  return m.get(ad);
}

function grafOf(plan) {
  let g = grafCache.get(plan);
  if (g && g.kenarSayisi === plan.kenarlar.length) return g;
  const nodes = plan.dugumler;
  const adj = new Map();
  for (const [a, b] of plan.kenarlar) {
    if (!nodes[a] || !nodes[b]) continue;
    const w = Math.hypot(nodes[a].x - nodes[b].x, nodes[a].z - nodes[b].z);
    if (!adj.has(a)) adj.set(a, []);
    if (!adj.has(b)) adj.set(b, []);
    adj.get(a).push([b, w]); adj.get(b).push([a, w]);
  }
  g = { adj, yollar: new Map(), uzunluklar: new Map(), yakinlar: new Map(), kenarSayisi: plan.kenarlar.length };
  grafCache.set(plan, g);
  return g;
}
// A binary heap of [dist, id] (ties by id: the same walk as before for equal lengths).
const heapOnce = (x, y) => x[0] < y[0] - 1e-9 || (Math.abs(x[0] - y[0]) <= 1e-9 && x[1] < y[1]);
function heapPush(h, v) {
  h.push(v);
  for (let i = h.length - 1; i > 0;) { const p = (i - 1) >> 1; if (!heapOnce(h[i], h[p])) break; [h[i], h[p]] = [h[p], h[i]]; i = p; }
}
function heapPop(h) {
  const top = h[0]; const last = h.pop();
  if (h.length) {
    h[0] = last;
    for (let i = 0; ;) {
      const l = 2 * i + 1, r = l + 1; let m = i;
      if (l < h.length && heapOnce(h[l], h[m])) m = l;
      if (r < h.length && heapOnce(h[r], h[m])) m = r;
      if (m === i) break;
      [h[i], h[m]] = [h[m], h[i]]; i = m;
    }
  }
  return top;
}

// niyetler without options.plan (tests, the demo's first frame): the plan of the same projects and options is built once
// (a few recent ones are kept); app.js passes its own cached plan.
const planlar = new Map();
function planOnbellekli(projects, options) {
  const names = (projects || []).map((p) => (typeof p === 'string' ? p : p && p.name)).filter(Boolean);
  const key = JSON.stringify([names, masaSayisi(options), denetciListesi(options.denetciler)]);
  let p = planlar.get(key);
  if (!p) {
    p = ofisPlani(names, options);
    planlar.set(key, p);
    if (planlar.size > 8) planlar.delete(planlar.keys().next().value);
  }
  return p;
}

export function yol(plan, from, to) {
  const nodes = plan && plan.dugumler;
  if (!nodes || !nodes[from] || !nodes[to] || !Array.isArray(plan.kenarlar)) return [];
  const g = grafOf(plan);
  const key = `${from}>${to}`;
  const hit = g.yollar.get(key);
  if (hit) return hit.map((p) => ({ ...p }));
  const dist = new Map([[from, 0]]);
  const back = new Map();
  const done = new Set();
  const heap = [[0, from]];
  let found = false;
  while (heap.length) {
    const [d, cur] = heapPop(heap);
    if (done.has(cur) || d > dist.get(cur) + 1e-9) continue;
    if (cur === to) { found = true; break; }
    done.add(cur);
    for (const [n, w] of g.adj.get(cur) || []) {
      const nd = d + w;
      if (!dist.has(n) || nd < dist.get(n) - 1e-9) { dist.set(n, nd); back.set(n, cur); heapPush(heap, [nd, n]); }
    }
  }
  if (!found) { g.yollar.set(key, []); return []; }
  const out = [to];
  while (out[0] !== from) out.unshift(back.get(out[0]));
  const path = out.map((id) => ({ id, x: nodes[id].x, z: nodes[id].z }));
  g.yollar.set(key, path);
  return path.map((p) => ({ ...p }));
}

// The walk's length along the graph (world units); Infinity when there is no walk, 0 for the same spot.
export function yolUzunlugu(plan, from, to) {
  if (from === to && plan && plan.dugumler && plan.dugumler[from]) return 0;
  const g = plan && plan.dugumler && Array.isArray(plan.kenarlar) ? grafOf(plan) : null, key = `${from}>${to}`;
  let s = g ? g.uzunluklar.get(key) : undefined; // cached like the walk itself
  if (s !== undefined) return s;
  const p = yol(plan, from, to);
  if (!p.length) return Infinity;
  s = 0;
  for (let i = 1; i < p.length; i++) s += Math.hypot(p[i].x - p[i - 1].x, p[i].z - p[i - 1].z);
  if (g) g.uzunluklar.set(key, s);
  return s;
}

// How long a duty trip needs to walk from `from` to `to` (ms): the walk at YURUME_HIZI with a 15 % margin (the scene's
// offsets and turns) plus 1.5 s; an unknown start (null) or no walk counts as YURUME_YEDEK_MS.
export const YURUME_YEDEK_MS = 30000;
export function yurumeSuresi(plan, from, to) {
  const L = from ? yolUzunlugu(plan, from, to) : Infinity;
  if (!Number.isFinite(L)) return YURUME_YEDEK_MS;
  return Math.ceil((L / YURUME_HIZI) * 1150) + 1500;
}

// --- behaviour ---

function allTasks(state) {
  const seen = new Map();
  const add = (t) => { if (t && t.note && !seen.has(notAdi(t.note))) seen.set(notAdi(t.note), t); };
  (state.tasks || []).forEach(add);
  (state.board || []).forEach(add);
  for (const p of state.projects || []) (p.tasks || []).forEach(add);
  return [...seen.values()].sort((a, b) => {
    const ka = `${a.started || a.created || ''}|${notAdi(a.note)}`;
    const kb = `${b.started || b.created || ''}|${notAdi(b.note)}`;
    return ka < kb ? 1 : ka > kb ? -1 : 0;
  });
}

function etiketOf(proje, model, uzmanlik = '') {
  const fam = modelAilesi(model);
  const rol = rolMetni(model, uzmanlik);
  return fam ? `${proje} · ${rol} (${aileAdi(fam)})` : `${proje} · ${rol}`;
}

// A workflow's approval step (no session; bin/akis.py `onay`) and a review run by the review panel (inceleme_yurutucu
// codex, or the job's model "codex" / "heyet" that bin/akis.py writes after the panel's verdict).
// The approval step is the owner's: bin/akis.py writes katman `onay`, model `deniz` (older notes: genel/sonnet with the step
// kind onay) — never a robot, never a kadro, a title or a tier default.
export const onayAdimi = (t) => !!t && (t.step_kind === 'onay' || t.tier === 'onay' || t.model === 'deniz');
export const panelIncelemesi = (t) => !!t && (t.inceleme_yurutucu === 'codex' || t.model === 'codex' || t.model === 'heyet');

const isInceleme = (t, s) => INCELEME_ADIMLARI.has((s && s.step_kind) || (t && t.step_kind) || '') ||
  ((s && s.tier) || (t && t.tier)) === 'inceleme';
// plan "Sonraki iş (9)" (display only, from the job's own tier and step): planning work (tier planlama or a plan step) is
// written in the Yazılım Müdürü's office; a review goes to the Analist odası (a plan review) or the QA odası (the rest).
export const planIsi = (t, s) => ((s && s.step_kind) || (t && t.step_kind) || '') === 'plan' ||
  ((s && s.tier) || (t && t.tier) || '') === 'planlama';
export const incelemeOdasi = (t, s) => (((s && s.step_kind) || (t && t.step_kind) || '') === 'plan-inceleme' ? 'analist' : 'qa');
// The department whose manager a job belongs to: plan reviews -> Analist; kod reviews and inceleme-tier jobs -> QA;
// everything else (planning, kod, genel, kolay) -> Yazılım.
export function isDepartmani(t, s = null) {
  if (isInceleme(t, s)) return incelemeOdasi(t, s) === 'analist' ? 'analist' : 'qa';
  return 'yazilim';
}
// A tester's title by seniority, from the test specialisation (plan "Sonraki iş (9)" step 2): "Stajyer Tester", "Uzman
// Tester", "Kıdemli Tester" ("Genel Müdür (QA adına)" for fable).
export function testerUnvani(fam) {
  const u = UNVAN[fam];
  if (!u || fam === 'codex') return UZMANLIK_BASLIK.test;
  return fam === 'fable' ? `${u.unvan} (QA adına)` : rolMetni(fam, 'test');
}
// The floor label of a Claude review in the QA odası / the Analist odası (the model stays in parentheses, as for jobs).
// A job with its own specialisation shows it ("Kıdemli Tester" for a kod-inceleme step, routed to test); one without
// keeps the room's title.
function incelemeEtiketi(a, oda) {
  const fam = modelAilesi(a.model);
  const m = fam ? ` (${aileAdi(fam)})` : '';
  if (uzmanlikEki(fam, a.uzmanlik)) return `${a.proje} · ${rolMetni(fam, a.uzmanlik)}${m}`;
  return oda === 'analist' ? `${a.proje} · İş analisti · ${(UNVAN[fam] || BILINMEYEN).unvan}${m}` : `${a.proje} · ${testerUnvani(fam)}${m}`;
}

// The rule table ("gerçek durum önce gelir": a working agent never leaves its desk, never at lunch or at home).
// Returns {yer: 'masa'|'uzman'|'kuyruk'|'bosta'|'cikis'|'tasima', poz, simge, metin, oncelik}.
// yer 'uzman' = a desk in the Uzmanlar odası (review work: inceleme tier, plan- / kod-inceleme steps run by Claude).
// yer 'masa' = at its own desk; 'bosta' = tea corner / short wander / canteen at lunch. `calisiyor` = the session is
// busy or one of its subagents is still open (an idle parent waiting for its helper is working).
// oncelik orders the desk claims: 0 working / permission / Kontrol / decision, 1 starting or silent, 2 stuck or
// celebrating, 3 no desk needed (meeting, tea, home), 4 leaving.
function niyet({ session, calisiyor, task, kota, ms, escalatedTo, title }) {
  const status = session ? session.status : null;
  const busy = !!calisiyor;
  const job = task ? task.status : '';
  const open = task && !FINAL.has(job) && job !== 'sirada';
  const finishedAt = task ? task._bitis : null;
  const age = finishedAt === null ? Infinity : Math.max(0, ms - finishedAt);
  const w = (yer, poz, simge, metin, oncelik) => ({ yer, poz, simge, metin, oncelik });
  const isim = title ? ` · ${kisa(title, 40)}` : '';
  if (status === 'waiting') return w('masa', 'el-kaldirmis', '!', 'izin bekliyor', 0);
  if (open) {
    if (job === 'kontrolde') return w('masa', 'bekliyor', 'test', 'Kontrol çalışıyor', 0);
    if (job === 'karar-bekliyor') {
      if (busy) return w('masa', 'yaziyor', '?', `çalışıyor · ${sahip('in')} cevabını bekliyor`, 0);
      return w('kuyruk', 'bekliyor', '?', `${sahip('in')} cevabını bekliyor`, 0);
    }
    if (isInceleme(task, session) && session) {
      if (busy) return w('uzman', 'yaziyor', null, `inceliyor${isim}`, 3);
    } else if (busy) {
      return w('masa', 'yaziyor', null, `çalışıyor${isim}`, 0);
    }
    if (kota) return w('masa', 'evde', null, kota, 3);
    if (isInceleme(task, session) && session) return w('uzman', 'bekliyor', null, 'inceleme · sessiz', 3);
    if (!session) {
      if (job === 'baslatiliyor') return w('masa', 'yuruyor', null, 'geliyor', 1);
      return w('masa', 'bekliyor', null, 'oturum görünmüyor', 1);
    }
    if (job === 'baslatiliyor') return w('masa', 'bekliyor', null, 'başlıyor', 1);
    return w('masa', 'bekliyor', null, 'masada · sessiz', 1);
  }
  // a finished or stuck review stays where the review was done (the Uzmanlar odası), never at a team desk
  const inc = isInceleme(task, session);
  const w2 = (yer, ...rest) => w(inc && yer === 'masa' ? 'uzman' : yer, ...rest);
  if (busy) return w2('masa', 'yaziyor', job === 'bitti' && age < CIKIS_MS ? '✓' : null, 'çalışıyor', 0);
  if (task && job === 'tikandi' && escalatedTo) {
    if (age < TASIMA_MS) return w('tasima', 'yuruyor', null, 'dosyayı devrediyor', 4);
    if (age < CIKIS_MS) return w('cikis', 'yuruyor', null, 'çıkıyor', 4);
  } else if (task && job === 'tikandi') {
    if (session || age < TIKANDI_GORUNUR_MS) return w2('masa', 'basi-onde', 'kirmizi', 'takıldı', 2);
  } else if (task && job === 'bitti' && age < CIKIS_MS) {
    if (age < KUTLAMA_MS) return w2('masa', 'kutluyor', '✓', '✓ bitti', 2);
    if (!session) return w('cikis', 'yuruyor', '✓', 'çıkıyor', 4);
  }
  if (!session) return null; // nothing real to show
  if (kota) return w('masa', 'evde', null, kota, 3);
  return w('bosta', null, null, '', 3);
}

const acikYardimci = (list) => (list || []).some((h) => h && h.id && !h.bitti);

function kotaMetni(modeller, model, ms, tz) {
  const fam = modelAilesi(model);
  const m = fam && (modeller || []).find((x) => x && x.model === fam);
  if (!m || m.durum !== 'kota') return '';
  const d = donusMetni(m.donus, ms, tz);
  return d ? `Evde · ${d}` : 'Evde · kota doldu';
}

// A "+N" stand-in for actors that do not fit a room; never clickable.
// `gizliler`: the actors that did not fit ([{etiket, durum_metni, note}], at most 20; note = the job's note or ''),
// listed by the info card as they are (the card never recomputes them).
function ozetAktor(id, yer, proje, n, metin, gizliler = []) {
  return { id, tur: 'ozet', unvan: '', rank: 0, model: '', proje, yer, masa: null, poz: 'bekliyor', simge: null,
    etiket: `+${n}`, durum_metni: metin, tiklama: null,
    gizliler: gizliler.slice(0, 20).map((a) => ({ etiket: String(a.etiket || a.unvan || 'ajan'),
      durum_metni: String(a.durum_metni || ''), note: String((a.tiklama && a.tiklama.note) || '') })) };
}

// --- the work calendar (the owner, 2026-11-13: weekends and public holidays are days off) ---
// Visual only: it decides when the day-hours staff (personelSaati: managers, the facility staff, the social media team,
// the office services, the project residents, the decorative people) and the Sekreters come in. The guards and the IT
// team keep their 24/7 rotation; the agent characters (CEO, kadro, auditors, hakem) and every real job are never
// affected; the server (dispatcher, schedules, morning summary) knows nothing of it. Dates are office-zone calendar
// dates. Arife (the eve of a bayram) is an ordinary work day here — officially only its afternoon is off (from 13:00), and
// a half day would need a second leave time per day for every staff member; kept simple on purpose.
// Fixed holidays (Law 2429 on national and general holidays), every year: 'MM-DD' -> {ad, kisa}.
export const SABIT_TATILLER = {
  '01-01': { ad: 'Yılbaşı', kisa: 'Yılbaşı' },
  '04-23': { ad: 'Ulusal Egemenlik ve Çocuk Bayramı', kisa: '23 Nisan' },
  '05-01': { ad: 'Emek ve Dayanışma Günü', kisa: '1 Mayıs' },
  '05-19': { ad: "Atatürk'ü Anma, Gençlik ve Spor Bayramı", kisa: '19 Mayıs' },
  '07-15': { ad: 'Demokrasi ve Millî Birlik Günü', kisa: '15 Temmuz' },
  '08-30': { ad: 'Zafer Bayramı', kisa: '30 Ağustos' },
  '10-29': { ad: 'Cumhuriyet Bayramı', kisa: '29 Ekim' },
};
// Ramazan and Kurban Bayramı per year: [first day 'MM-DD', number of days, name]. Source: Diyanet İşleri Başkanlığı,
// "Dini Günler" tables (vakithesaplama.diyanet.gov.tr — 2026: dinigunler.php?yil=2026, 2027: icerik.php?icerik=154,
// 2028: icerik.php?icerik=185; read 2026-11-13). The arife days (2026-03-19, 2026-05-26, 2027-03-08, 2027-05-15,
// 2028-02-25, 2028-05-04) stay work days (see above). A year missing here still has its fixed holidays; add a row
// from Diyanet's table each year.
export const DINI_BAYRAMLAR = {
  2026: [['03-20', 3, 'Ramazan Bayramı'], ['05-27', 4, 'Kurban Bayramı']],
  2027: [['03-09', 3, 'Ramazan Bayramı'], ['05-16', 4, 'Kurban Bayramı']],
  2028: [['02-26', 3, 'Ramazan Bayramı'], ['05-05', 4, 'Kurban Bayramı']],
};
const gunNo = (y, m, d) => Math.round(Date.UTC(y, m - 1, d) / 86400000); // days since 1970-01-01
const gundenTarih = (g) => { const t = new Date(g * 86400000); return { yil: t.getUTCFullYear(), ay: t.getUTCMonth() + 1, gun: t.getUTCDate() }; };
const DINI_GUNLER = new Map(); // day number -> name
for (const [yil, satirlar] of Object.entries(DINI_BAYRAMLAR)) {
  for (const [md, adet, ad] of satirlar) {
    const [ay, gun] = md.split('-').map(Number);
    for (let i = 0; i < adet; i++) DINI_GUNLER.set(gunNo(Number(yil), ay, gun) + i, ad);
  }
}
// a calendar date from {yil, ay, gun}, a day number, or a moment (ms / Date: its date in the office zone of sahne)
function takvimGunu(x, sahne) {
  if (x && typeof x === 'object' && !(x instanceof Date) && Number.isFinite(x.yil)) return x;
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  return ofisSaati(nowMs(x), s.saat_dilimi);
}
// The public holiday on that date: {ad, kisa} or null.
export function tatil(x, sahne) {
  const t = takvimGunu(x, sahne);
  const dini = DINI_GUNLER.get(gunNo(t.yil, t.ay, t.gun));
  if (dini) return { ad: dini, kisa: dini };
  return SABIT_TATILLER[`${String(t.ay).padStart(2, '0')}-${String(t.gun).padStart(2, '0')}`] || null;
}
// The holiday's name ("Cumhuriyet Bayramı", "Kurban Bayramı") or '' on any other day.
export const tatilAdi = (x, sahne) => (tatil(x, sahne) || {}).ad || '';
// 0 = Sunday … 6 = Saturday
const haftaGunu = (t) => new Date(Date.UTC(t.yil, t.ay - 1, t.gun)).getUTCDay();
// The kind of day: {is (a work day), tur: 'is' | 'hafta-sonu' | 'tatil', ad, kisa} — a holiday wins over a weekend.
export function gunTuru(x, sahne) {
  const t = takvimGunu(x, sahne);
  const h = tatil(t);
  if (h) return { is: false, tur: 'tatil', ad: h.ad, kisa: h.kisa };
  const w = haftaGunu(t);
  return w === 0 || w === 6 ? { is: false, tur: 'hafta-sonu', ad: '', kisa: '' } : { is: true, tur: 'is', ad: '', kisa: '' };
}
// Monday to Friday and not a public holiday.
export const isGunuMu = (x, sahne) => gunTuru(x, sahne).is;
// The first work day after that date: {yil, ay, gun}.
export function sonrakiIsGunu(x, sahne) {
  const t = takvimGunu(x, sahne);
  let g = gunNo(t.yil, t.ay, t.gun);
  for (let i = 0; i < 60; i++) {
    g += 1;
    const d = gundenTarih(g);
    if (isGunuMu(d)) return d;
  }
  return gundenTarih(g);
}
// The calendar applies only with office hours (none, e.g. the demo: every day is open).
const takvimli = (sahne) => !!mesaiAraligi(sahne);
// the last moment it was dk o'clock at or before ms / the next one after ms (office zone)
function sonDk(ms, dk, tz) { const cur = gununDakikasi(ms, tz); return ms - ((((cur - dk) % 1440) + 1440) % 1440) * 60000; }
function ilkDk(ms, dk, tz) { const cur = gununDakikasi(ms, tz); const f = (((dk - cur) % 1440) + 1440) % 1440; return ms + (f || 1440) * 60000; }
// The next time it is dk o'clock on a work day (strictly after ms; every day without office hours).
export function sonrakiIsSaati(now, dk, sahne) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  let t = ilkDk(nowMs(now), dk, s.saat_dilimi);
  for (let i = 0; i < 60 && takvimli(s) && !isGunuMu(t, s); i++) t += 86400000;
  return t;
}
// The last time it was dk o'clock on a work day (at or before ms).
export function oncekiIsSaati(now, dk, sahne) {
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  let t = sonDk(nowMs(now), dk, s.saat_dilimi);
  for (let i = 0; i < 60 && takvimli(s) && !isGunuMu(t, s); i++) t -= 86400000;
  return t;
}

// --- time slots and office hours ---

// An actor's own break slot at `ms`: {dilim (the slot number), gecen (ms since the slot began)}. Every actor's slots
// start at its own seeded phase, so the office never switches in step.
export function molaDilimi(id, ms, adim = MOLA_ADIM_MS) {
  const f = hash(`${id}:faz`) % adim;
  return { dilim: Math.floor((ms + f) / adim), gecen: (ms + f) % adim };
}

function aralik(text) {
  const [a, b] = String(text || '').split('-');
  const s = dakikaOf(a), e = dakikaOf(b);
  return s === null || e === null || s === e ? null : [s, e];
}
// The office hours of a scene (state.sahne.mesai), [start, end] in minutes of the office day; null = none (always open).
export function mesaiAraligi(sahne) {
  const raw = sahne && Object.prototype.hasOwnProperty.call(sahne, 'mesai') ? sahne.mesai : DEFAULT_MESAI;
  if (raw === null || raw === false || raw === '' || raw === 'yok') return null;
  return aralik(raw) || aralik(DEFAULT_MESAI);
}
function gununDakikasi(ms, tz) {
  const t = ofisSaati(ms, tz);
  return t.saat * 60 + t.dakika + (ms % 60000) / 60000;
}
const aralikta = (cur, [s, e]) => (s < e ? cur >= s && cur < e : cur >= s || cur < e);
// Inside the office hours (true when there are none).
export function mesaiMi(now, sahne) {
  const m = mesaiAraligi(sahne);
  if (!m) return true;
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const ms = nowMs(now);
  // the work calendar: the window counts only when the day it began on is a work day
  return aralikta(gununDakikasi(ms, s.saat_dilimi), m) && isGunuMu(sonDk(ms, m[0], s.saat_dilimi), s);
}
// A day off's day hours (the owner, 2026-11-14: "ofiste olanlar halen uyuyor"): the office hours' clock window on a weekend
// or a public holiday — the agents are awake then and spend the day in the common areas; null-safe: false without
// office hours. The kind of day ({tur: 'hafta-sonu' | 'tatil', …}, gunTuru) when true, else null.
export function tatilGunduzu(now, sahne) {
  const m = mesaiAraligi(sahne);
  if (!m) return null;
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const ms = nowMs(now);
  if (!aralikta(gununDakikasi(ms, s.saat_dilimi), m)) return null;
  const g = gunTuru(sonDk(ms, m[0], s.saat_dilimi), s);
  return g.is ? null : g;
}
// The agents' sleeping time (GECE_UYKUSU): outside the office hours' start until dinner's end (AKSAM_YEMEGI, 20:00 —
// the later of the two), every day. Between the office hours' end and then (the evening) and on a day off's day hours
// they are awake in the common areas (serbestZaman); false without office hours.
export function uykuVaktiMi(now, sahne) {
  const m = mesaiAraligi(sahne);
  if (!m || mesaiMi(now, sahne)) return false;
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const son = m[0] < m[1] ? Math.max(m[1], AKSAM_YEMEGI[1]) : m[1];
  return !aralikta(gununDakikasi(nowMs(now), s.saat_dilimi), [m[0], son]);
}
// The agents' free waking time outside the office hours: {tur: 'hafta-sonu' | 'tatil' (a day off's day hours) |
// 'aksam' (a work day's evening until bedtime)} or null (office hours, or asleep).
export function serbestZaman(now, sahne) {
  if (!mesaiAraligi(sahne) || mesaiMi(now, sahne) || uykuVaktiMi(now, sahne)) return null;
  const g = tatilGunduzu(now, sahne) || gunTuru(nowMs(now), sahne);
  return g.is ? { ...g, tur: 'aksam' } : g;
}
// The label word of a free time: "hafta sonu" / "tatil" / "akşam".
export const tatilSozu = (g) => (g && g.tur === 'tatil' ? 'tatil' : g && g.tur === 'aksam' ? 'akşam' : 'hafta sonu');
// One staff member's own day: 'iceride' (at work), 'cikiyor' (its EVE_GIDIS_MS walk to the lift after its leave time) or
// 'evde' (personelSaati). Arrival and leave are seeded within ±MESAI_SAPMA_DK of the office hours; no office hours:
// always 'iceride'; on a weekend or a public holiday (the work calendar) always 'evde'.
// One staff member's own arrival and leave (minutes of the day, seeded within ±MESAI_SAPMA_DK of the office hours);
// null without office hours.
export function personelGunu(id, sahne) {
  const m = mesaiAraligi(sahne);
  if (!m) return null;
  const span = 2 * MESAI_SAPMA_DK + 1;
  return { gel: (m[0] + (hash(`${id}:gelis`) % span) - MESAI_SAPMA_DK + 1440) % 1440,
    git: (m[1] + (hash(`${id}:gidis`) % span) - MESAI_SAPMA_DK + 1440) % 1440 };
}
export function personelSaati(id, now, sahne) {
  const g = personelGunu(id, sahne);
  if (!g) return 'iceride';
  const s = { ...DEFAULT_SAHNE, ...(sahne || {}) };
  const ms = nowMs(now);
  const { gel, git } = g;
  const cur = gununDakikasi(ms, s.saat_dilimi);
  const ham = aralikta(cur, [gel, git]) ? 'iceride'
    : aralikta(cur, [git, (git + EVE_GIDIS_MS / 60000) % 1440]) ? 'cikiyor' : 'evde';
  // the work calendar: no day-hours staff on a weekend or a public holiday (its day = the day of its last arrival)
  return ham !== 'evde' && !isGunuMu(sonDk(ms, gel, s.saat_dilimi), s) ? 'evde' : ham;
}

// --- decorative people (the owner, 2026-11-13: "QA odasında, analist odasında, proje ekiplerinde NPC yok; sırf görünüm için
// olabilir") ---
// Purely visual figures so the QA odası, the Analist odası and the project team bays look staffed (since 2026-11-18 also
// the common areas, with a few slow walkers: dekorOrtakYerleri, DEKOR_YURUYUSLER). They are no actors:
// no data, no labels, never in kimNerede, the Çalışanlar list or the org chart's people (the chart shows one
// group line per room: DEKOR_EKIP). The scene draws all of them as one instanced body mesh (+ one for the standing ones'
// legs): two draw calls in total (web/scene.js setDekor). Each sits at a desk the real work leaves for last (the QA
// odası: the second Kıdemli and the second Stajyer Tester desk; the Analist odası: its last two desks; a team bay: its
// last two desks) or stands at the room's whiteboard; it gives its desk up (hidden) while an actor sits at or heads
// for it, and is home (hidden, no lift walk) outside its own seeded office hours (personelSaati).
export const DEKOR_EKIP = { qa: 3, analist: 3, proje: 2 }; // people per QA odası / Analist odası / team bay
// The fixed seats of the decorative people in a plan: [{id, grup: 'qa' | 'analist' | 'proje' | 'ortak', oda, proje, yer
// (the seat node, null for one standing at a whiteboard or walking), x, z, aci (null: as yuzAcisi), oturan, sit (the
// seat kind), yuruyen + rota (a walker: dekorRotasi)}]. Pure; the same plan gives the same list.
export function dekorYerleri(plan) {
  const nodes = (plan && plan.dugumler) || {};
  const out = [];
  const masada = (id, grup, oda, yer, proje = '') => {
    const n = nodes[yer];
    if (n) out.push({ id, grup, oda, proje, yer, x: n.x, z: n.z, aci: 0, oturan: true });
  };
  for (const r of (plan && plan.odalar) || []) {
    if (r.tur === 'qa' || r.tur === 'analist') {
      const masalar = r.tur === 'qa' ? [QA_MASALARI.kidemli[1], QA_MASALARI.stajyer[1]] : ['analist-masa-2', 'analist-masa-3'];
      masalar.forEach((yer, i) => masada(`dekor:${r.tur}:${i}`, r.tur, r.id, yer));
      // the third one stands at the whiteboard on the back wall (left of its middle: clear of the desks' helper spots),
      // turned three quarters towards it
      out.push({ id: `dekor:${r.tur}:${masalar.length}`, grup: r.tur, oda: r.id, proje: '', yer: null,
        x: +(r.x + r.w / 2 - 0.9).toFixed(2), z: +(r.z + 1.45).toFixed(2), aci: Math.PI * 0.82, oturan: false });
    } else if (r.tur === 'ekip' && r.proje) {
      const pre = `${r.id}-masa-`;
      const masalar = Object.keys(nodes).filter((k) => k.startsWith(pre) && /^\d+$/.test(k.slice(pre.length)))
        .sort((a, b) => Number(b.slice(pre.length)) - Number(a.slice(pre.length))).slice(0, DEKOR_EKIP.proje);
      masalar.forEach((yer, i) => masada(`dekor:proje:${r.proje}:${i}`, 'proje', r.id, yer, r.proje));
    }
  }
  // the common areas (owner decision 2026-11-18, "NPC'leri fazlalaştıralım"): seats the real actors use last
  let i = 0;
  for (const [yer, oturan] of dekorOrtakYerleri(plan)) {
    const n = nodes[yer];
    // aci null: the scene turns it like a real character on that spot (yuzAcisi); `sit` = the seat kind (its height)
    out.push({ id: `dekor:ortak:${i++}`, grup: 'ortak', oda: n.oda, proje: '', yer, x: n.x, z: n.z, aci: null, oturan,
      sit: oturan ? n.tur : '' });
  }
  // and a few who walk slowly along the plan's own walks (never through furniture), pausing at each stop
  DEKOR_YURUYUSLER.forEach((duraklar, k) => {
    const rota = dekorRotasi(plan, duraklar);
    if (!rota) return;
    const p = rota.bacaklar[0].pts[0];
    out.push({ id: `dekor:yuruyen:${k}`, grup: 'ortak', oda: null, proje: '', yer: null, x: p[0], z: p[1], aci: 0,
      oturan: false, yuruyen: true, rota });
  });
  return out;
}

// The common-area seats of the decorative people: [[node, seated]], only the nodes the plan has. The Toplantı odası (a
// meeting at its table: it stays empty of actors), the last table of the canteen (the chairs the agents take last), the
// tea corner's last round table, one café table of the Ortak alan, the bean bag and one billiards player of the Oyun odası.
// Never the lobby's armchairs (the queued jobs wait there) nor a desk.
export function dekorOrtakYerleri(plan) {
  const nodes = (plan && plan.dugumler) || {};
  const out = [['toplanti-sandalye-0', true], ['toplanti-sandalye-1', true], ['toplanti-sandalye-4', true]];
  const masalar = Array.isArray(plan && plan.yemek_masalari) ? plan.yemek_masalari : [];
  const son = masalar[masalar.length - 1];
  if (son) { // the two chairs face to face at the last table's left end, and the next one on its near side
    const yakin = Object.values(nodes).filter((n) => /^yemekhane-sandalye-\d+$/.test(n.id) && n.id !== 'yemekhane-sandalye-7' &&
      Math.abs(n.z - son[2]) < 2.5).sort((a, b) => a.x - b.x || a.z - b.z);
    const xs = [...new Set(yakin.map((n) => n.x))];
    for (const n of yakin.filter((m) => m.x === xs[0])) out.push([n.id, true]);
    const ikinci = yakin.find((m) => m.x === xs[1] && m.z < son[2]);
    if (ikinci) out.push([ikinci.id, true]);
  }
  out.push(['cay-ocagi-yer-7', true], ['cay-ocagi-yer-8', true], ['ortak-alan-yer-2', true], ['ortak-alan-yer-3', true],
    ['oyun-puf', true], ['oyun-bilardo-1', false]);
  return out.filter(([id]) => nodes[id]);
}

// The decorative walkers' stops (nodes with stable names on every plan): the front-row corridor, the back corridor, a
// wing corridor and the lobby's door to the spine. Each walks its stops in order and back to the first, pausing
// DEKOR_DURAK_S at each.
export const DEKOR_YURUYUSLER = [['koridor-1-sol', 'koridor-1-sag'], ['koridor-0-sag', 'koridor-0-sol'],
  ['kanat-2-omurga', 'kanat-2-sag'], ['lobi-kapi', 'kanat-4-omurga']];
export const DEKOR_HIZ = 0.8; // world units a second: slower than any actor (a stroll)
export const DEKOR_DURAK_S = 8;
// A walker's loop from its stops: {bacaklar: [{pts: [[x, z]], cum, L}] (the walk from stop k to stop k + 1 along `yol`,
// the plan's edges, so never through furniture), sure (one loop in seconds)}; null when a stop is missing or unreachable.
export function dekorRotasi(plan, duraklar) {
  const nodes = (plan && plan.dugumler) || {};
  if (!Array.isArray(duraklar) || duraklar.length < 2 || duraklar.some((d) => !nodes[d])) return null;
  const bacaklar = [];
  for (let k = 0; k < duraklar.length; k++) {
    const p = yol(plan, duraklar[k], duraklar[(k + 1) % duraklar.length]);
    if (p.length < 2) return null;
    const pts = p.map((q) => [q.x, q.z]);
    const cum = [0];
    for (let j = 1; j < pts.length; j++) cum.push(cum[j - 1] + Math.hypot(pts[j][0] - pts[j - 1][0], pts[j][1] - pts[j - 1][1]));
    bacaklar.push({ pts, cum, L: cum[cum.length - 1] });
  }
  const sure = bacaklar.reduce((s, b) => s + DEKOR_DURAK_S + b.L / DEKOR_HIZ, 0);
  return sure > 0 ? { bacaklar, sure } : null;
}
// A walker at scene time t (seconds): {x, z, aci (as yuzAcisi: atan2(dx, dz)), yuruyor}. Periodic in t: a pause at
// each stop, then the walk to the next. Pure.
export function dekorYuruyusu(rota, t) {
  if (!rota || !(rota.sure > 0)) return null;
  let s = ((Number(t) || 0) % rota.sure + rota.sure) % rota.sure;
  let aci = 0;
  for (const b of rota.bacaklar) {
    const yon = (j) => Math.atan2(b.pts[j][0] - b.pts[j - 1][0], b.pts[j][1] - b.pts[j - 1][1]);
    if (s < DEKOR_DURAK_S) return { x: b.pts[0][0], z: b.pts[0][1], aci: b.pts.length > 1 ? yon(1) : aci, yuruyor: false };
    s -= DEKOR_DURAK_S;
    const yolS = b.L / DEKOR_HIZ;
    if (s < yolS) {
      const u = s * DEKOR_HIZ;
      let j = 1;
      while (j < b.cum.length - 1 && b.cum[j] < u) j++;
      const seg = b.cum[j] - b.cum[j - 1] || 1;
      const f = Math.min(1, Math.max(0, (u - b.cum[j - 1]) / seg));
      const a = b.pts[j - 1], c = b.pts[j];
      return { x: a[0] + (c[0] - a[0]) * f, z: a[1] + (c[1] - a[1]) * f, aci: yon(j), yuruyor: true };
    }
    s -= yolS;
    aci = yon(b.pts.length - 1);
  }
  const b = rota.bacaklar[0];
  return { x: b.pts[0][0], z: b.pts[0][1], aci, yuruyor: false };
}
// The decorative people shown now: dekorYerleri minus the ones home (outside their seeded office hours) and the ones
// whose desk an actor uses (`yer` or `masa`, also while walking there). Each entry gets `faz` (a stable phase for its
// small idle movements).
export function dekorEkibi(plan, actors, now, sahne) {
  const dolu = new Set();
  for (const a of actors || []) {
    if (!a) continue;
    if (a.yer) dolu.add(a.yer);
    if (a.masa) dolu.add(a.masa);
  }
  const out = dekorYerleri(plan).filter((d) => !(d.yer && dolu.has(d.yer)) && personelSaati(d.id, now, sahne) === 'iceride')
    .map((d) => ({ ...d, faz: (hash(d.id) % 1000) / 1000 * 24 }));
  // the street's pedestrians walking now (yayaSayisi): carried on the list (not an entry of it) so the page's one
  // setDekor call brings the time of day to the scene; the scene draws none in hafif
  out.yaya = yayaSayisi(now, sahne);
  return out;
}

// --- who is where (plan "Sonraki iş (8)": the guard's card and the corner line outside the office hours) ---

// An agent's state as the engine drew it: 'çalışıyor', 'uyuyor', 'yemekte', 'molada', 'dinleniyor', 'kota doldu', 'hata'.
// An agent not drawn (a kadro whose body works as a job: devral) is working — kadroDurumu first asks its body.
function ajanDurumu(a) {
  if (!a) return 'çalışıyor';
  if (a.poz === 'evde') return 'kota doldu';
  if (a.simge === 'kirmizi') return 'hata';
  if (a.poz === 'yaziyor' || a.poz === 'toplanti' || a.simge === 'test') return 'çalışıyor';
  if (a.poz === 'yatiyor' || /uyuyor/.test(String(a.durum_metni || ''))) return 'uyuyor';
  if (a.poz === 'yemek') return 'yemekte';
  return a.mola ? 'molada' : 'dinleniyor';
}
// The drawn workers of a Claude family: its jobs and sessions, the hakem and the security reviewer (their `aile`) — the
// bodies a kadro of that family walks as (devral); leaving ones and the "+N" summaries are not here.
function aileIscileri(aktorler, f) {
  return (Array.isArray(aktorler) ? aktorler : []).filter((a) => a && a.tur === 'ajan' && !a.cikis && a.poz !== 'evde' &&
    ((/^(is|oturum):/.test(String(a.id)) || a.id === 'hakem') ? a.model === f : a.id === `denetci:${GUVENLIK}` && a.aile === f));
}
// A kadro's state: drawn -> as drawn; not drawn -> its body's (a worker of its family), working when any of them works.
// An idle leftover session of its model holds the body too (2026-11-16: "Kıdemli çalışıyor" while nothing ran).
function kadroDurumu(akt, aktorler, f) {
  const a = akt.get(`kadro:${f}`);
  if (a) return ajanDurumu(a);
  const w = aileIscileri(aktorler, f).map(ajanDurumu);
  return !w.length || w.includes('çalışıyor') ? 'çalışıyor' : w[0];
}
// The people in the office beyond kimNerede's roster (one body per kadro): a family's further workers (two Kıdemli jobs
// at once) and the "+N" summaries of the workers the floor could not fit. The guard's headcount adds them.
export function fazlaIsciSayisi(aktorler) {
  if (!Array.isArray(aktorler)) return 0;
  let n = 0;
  for (const f of KADRO) {
    const w = aileIscileri(aktorler, f).filter((a) => a.id !== `denetci:${GUVENLIK}`).length;
    const kadroCizili = aktorler.some((a) => a && a.id === `kadro:${f}` && !a.cikis);
    n += Math.max(0, w - (kadroCizili ? 0 : 1));
  }
  for (const a of aktorler) {
    if (a && a.tur === 'ozet' && !a.cikis) { const x = Number(String(a.etiket || '').replace(/^\+/, '')); if (Number.isFinite(x) && x > 0) n += x; }
  }
  return n;
}
// Who is in the office and who is home now, from the clock and the rules only (office hours with each one's seeded
// arrival and leave — personelGunu —, the shift teams' rotation — nobetEkibi / nobetPlani —, a project resident staying
// while its project has an open job); `aktorler` (the engine's actors now) only gives the agents' state. Agents (the CEO,
// the kadro, the auditors) never go home. Returns {ofiste: [entry], evde: [entry], mesai (inside the office hours),
// donus ('HH:MM' the office hours start, or null), donus_ms (outside the office hours: the next start on a work day),
// gun (today's kind, gunTuru — the work calendar)}; entry = {id, ad, grup: 'ajan' | 'nobet' | 'personel', durum:
// 'ofiste' | 'nobette' | 'cikiyor' | 'evde', metin, gelis, cikis, donus, bitis, vardiya} (ms or null).
export function kimNerede(state, now, aktorler = null) {
  const st = state && typeof state === 'object' ? state : {};
  const ms = nowMs(now);
  const sahne = { ...DEFAULT_SAHNE, ...(st.sahne || {}) };
  const tz = sahne.saat_dilimi;
  const m = mesaiAraligi(sahne);
  const cur = gununDakikasi(ms, tz);
  const geri = (dk) => ms - ((((cur - dk) % 1440) + 1440) % 1440) * 60000; // the last time it was dk o'clock
  const ofiste = [], evde = [];
  const ekle = (e) => (e.durum === 'evde' ? evde : ofiste).push({ gelis: null, cikis: null, donus: null, bitis: null,
    vardiya: null, metin: '', ...e });
  const akt = new Map((Array.isArray(aktorler) ? aktorler : []).filter((a) => a && a.id).map((a) => [a.id, a]));
  // the agents
  ekle({ id: 'ceo', ad: 'CEO', grup: 'ajan', durum: 'ofiste', metin: aktorler ? ajanDurumu(akt.get('ceo')) : '' });
  for (const f of KADRO) {
    ekle({ id: `kadro:${f}`, ad: `${UNVAN[f].unvan} (${KADRO_ADI[f]})`, grup: 'ajan', durum: 'ofiste',
      metin: aktorler ? kadroDurumu(akt, aktorler, f) : '' });
  }
  for (const ad of denetciListesi(st.modeller)) {
    // the security reviewer is drawn only while its review runs (a Claude call): not drawn means not at work — never
    // "çalışıyor" (ajanDurumu's undrawn = working holds for a kadro whose body works as a job, not for it); it rests
    // like the others, asleep at night
    const a = akt.get(`denetci:${ad}`);
    const metin = !aktorler ? '' : ad === GUVENLIK && !a ? (uykuVaktiMi(ms, sahne) ? 'uyuyor' : 'dinleniyor') : ajanDurumu(a);
    ekle({ id: `denetci:${ad}`, ad: ad === GUVENLIK ? GUVENLIK_UNVAN : denetciAdi(ad), grup: 'ajan', durum: 'ofiste', metin });
  }
  // the shift teams
  const v = vardiya(ms, sahne);
  for (const [g, e] of Object.entries(NOBET_EKIPLERI)) {
    for (const u of nobetEkibi(g, ms, sahne)) {
      const p = nobetPlani(u.kisi, ms, sahne, g);
      const x = { id: u.id, ad: u.ad, grup: 'nobet', ekip: g };
      if (u.durum === 'nobette') ekle({ ...x, durum: 'nobette', gelis: p.simdiki.bas, bitis: p.simdiki.son, vardiya: v.vardiya });
      else if (u.durum === 'iceride') ekle({ ...x, durum: 'ofiste', metin: 'nöbet dışı', gelis: p.onceki.bas });
      else {
        let cikis = p.onceki ? p.onceki.son : null;
        if (e.arkadas && p.onceki && p.onceki.vardiya !== 0) { // the IT colleague stayed after its day / evening shift
          const sonraki = p.onceki.son + VARDIYA_DK * 60000;
          const pg = personelGunu(u.id, sahne);
          if (!pg) cikis = sonraki;
          else if (personelSaati(u.id, p.onceki.son, sahne) === 'iceride') {
            const sonDk = gununDakikasi(p.onceki.son, tz);
            cikis = Math.min(sonraki, p.onceki.son + ((((pg.git - sonDk) % 1440) + 1440) % 1440) * 60000);
          }
          if (cikis > ms) cikis = p.onceki.son;
        }
        ekle({ ...x, durum: 'evde', cikis: p.onceki ? cikis : null, donus: p.sonraki ? p.sonraki.bas : null,
          vardiya: p.sonraki ? p.sonraki.vardiya : null });
      }
    }
  }
  // the office staff: their own office hours (a project resident also while its project has an open job)
  // (the arge workspace has no sorumlu: its Ar-Ge uzmanı is in the office while an arge job is open)
  const projeler = (Array.isArray(st.projects) ? st.projects : []).map((p) => (typeof p === 'string' ? p : p && p.name))
    .filter((p) => p && p !== ARGE_PROJESI);
  const tasks = Array.isArray(st.tasks) ? st.tasks : [];
  const personel = [['sus:cayci', 'Çaycı'], // (the kitchen teams are shift teams since 2026-11-14: below)
    ...Object.entries(TESIS_PERSONELI).filter(([k]) => !NOBET_EKIPLERI[k])
      .map(([k, ad]) => [`sus:${k}`, ad, k === 'arge' ? ARGE_PROJESI : undefined]),
    ...SOSYAL_EKIBI.map((u) => [`sus:sosyal:${u.id}`, u.ad]),
    ...MUDURLUKLER.map((m) => [mudurId(m.key), m.ad]),
    ...[...new Set(projeler)].map((p) => [`sus:proje:${p}`, `${aileAdi(p)} sorumlusu`, p])];
  // the Değerlendirme ekibi: in the office exactly while its work runs (it has no office hours; never drawn otherwise)
  const deg = degerlendirmeDurumu(st, ms);
  if (deg.calisiyor) {
    const metin = degerlendirmeMetinleri(deg);
    DEGERLENDIRME_EKIBI.forEach((u, i) => {
      const a = akt.get(u.id);
      if (aktorler && !a) return; // no free desk for it now: not drawn, so not counted in
      ekle({ id: u.id, ad: u.etiket, grup: 'personel', durum: 'ofiste', metin: a ? String(a.durum_metni || metin[i][0]) : metin[i][0] });
    });
  }
  for (const [id, ad, proje] of personel) {
    const x = { id, ad, grup: 'personel' };
    if (proje === ARGE_PROJESI ? tasks.some(argeIsi)
      : proje && tasks.some((t) => t && t.project === proje && !FINAL.has(t.status) && t.status !== 'sirada')) {
      ekle({ ...x, durum: 'ofiste', metin: proje === ARGE_PROJESI ? 'araştırma işi açık' : 'projesinin işi açık' });
      continue;
    }
    const pg = personelGunu(id, sahne);
    const d = personelSaati(id, ms, sahne);
    const a = akt.get(id);
    if (!pg) ekle({ ...x, durum: 'ofiste' });
    // called in for a duty outside its hours (a resident taking a new job's file over, a visit that ran on): the engine
    // drew it on that duty
    else if (d !== 'iceride' && a && a.gorevde && !a.cikis) ekle({ ...x, durum: 'ofiste', metin: String(a.durum_metni || 'görevde') });
    else if (d === 'iceride') ekle({ ...x, durum: 'ofiste', gelis: geri(pg.gel) });
    else if (d === 'cikiyor') ekle({ ...x, durum: 'cikiyor', metin: 'otele gidiyor', cikis: geri(pg.git) });
    else {
      // the work calendar: the leave after its last arrival on a work day, the next arrival on a work day
      const sure = ((((pg.git - pg.gel) % 1440) + 1440) % 1440) * 60000;
      let gel = oncekiIsSaati(ms, pg.gel, sahne);
      if (gel + sure > ms) gel = oncekiIsSaati(gel - 60000, pg.gel, sahne);
      ekle({ ...x, durum: 'evde', cikis: gel + sure, donus: sonrakiIsSaati(ms, pg.gel, sahne) });
    }
  }
  // gun: today's kind (gunTuru; null without office hours); donus_ms: the next start of the office hours on a work day
  return { ofiste, evde, mesai: mesaiMi(ms, sahne), donus: m ? saatMetni(m[0]) : null,
    donus_ms: m ? (mesaiMi(ms, sahne) ? null : sonrakiIsSaati(ms - 1, m[0], sahne)) : null, gun: m ? gunTuru(ms, sahne) : null };
}
const saatMetni = (dk) => `${String(Math.floor(dk / 60) % 24).padStart(2, '0')}:${String(dk % 60).padStart(2, '0')}`;

// --- the CEO's free time ---

function ceoTemel(slot) {
  const h = hash(`ceo:plan:${slot}`) % 100;
  const P = CEO_PAYLARI;
  return h < P.masa ? 'masa' : h < P.masa + P.tur ? 'tur' : h < P.masa + P.tur + P.mola ? 'mola' : 'uyku';
}
// A round's stops from the CEO's desk: up to two team doors (seeded), the auditors' room or the Uzmanlar odası, and its
// own door; each lasts the walk there plus CEO_DURAK_KALIS_MS. [{durak, son (ms after the round began)}].
export function ceoTurDuraklari(slot, plan) {
  const nodes = (plan && plan.dugumler) || {};
  const projeler = (plan && plan.projeler) || [];
  const bas = projeler.length ? hash(`ceo:tur-ekip:${slot}`) % projeler.length : 0;
  const ekipler = Array.from({ length: Math.min(2, projeler.length) }, (_, i) => `ekip-${projeler[(bas + i) % projeler.length]}-kapi`);
  const orta = hash(`ceo:tur-orta:${slot}`) % 2 ? 'denetci-kapi' : 'uzmanlar-kapi';
  const stops = [...ekipler, orta, 'ceo-kapi'].filter((id) => nodes[id]);
  let t = 0, from = 'ceo-masa';
  return stops.map((durak) => { t += yurumeSuresi(plan, from, durak) + CEO_DURAK_KALIS_MS; from = durak; return { durak, son: t }; });
}
// The CEO's free time at `ms` (idle or dormant with nothing open): {tur: 'masa' | 'tur' | 'mola' | 'uyku', durak (a
// round's stop), mola (a break's kind)}. Seeded by the slot: deterministic. `uyuyabilir` (dormant): sleep is possible,
// else that share is the desk. A round begun in an earlier slot goes on until its last stop is done. `gece` (outside
// the office hours): no round, no break — a dormant CEO sleeps, an idle one stays at its desk. By day the sleep share
// is a nap only in the lunch window (`ogle`, dormant); else a break (the owner, 2026-11-16: no sleeping in office hours).
export function ceoPlani(ms, plan, { uyuyabilir = false, gece = false, ogle = false } = {}) {
  if (gece) return { tur: uyuyabilir ? 'uyku' : 'masa' };
  const slot = Math.floor(ms / CEO_ADIM_MS);
  for (let back = 4; back >= 0; back--) { // an earlier round still running wins
    const s = slot - back;
    if (ceoTemel(s) !== 'tur') continue;
    const o = ms - s * CEO_ADIM_MS;
    const stops = ceoTurDuraklari(s, plan);
    const cur = stops.find((x) => o < x.son);
    if (cur) return { tur: 'tur', durak: cur.durak };
  }
  const t = ceoTemel(slot);
  if (t === 'tur') return { tur: 'masa' };
  if (t === 'mola') return { tur: 'mola', mola: CEO_MOLALARI[hash(`ceo:mola-turu:${slot}`) % CEO_MOLALARI.length] };
  if (t === 'uyku') {
    return uyuyabilir && ogle ? { tur: 'uyku' }
      : { tur: 'mola', mola: CEO_MOLALARI[hash(`ceo:gunduz:${slot}`) % CEO_MOLALARI.length] };
  }
  return { tur: 'masa' };
}

// The CEO's inspection round at `ms`: the stop it walks to, or null outside a round (ceoPlani).
export function ceoTuru(ms, plan) {
  const x = ceoPlani(ms, plan);
  return x.tur === 'tur' ? x.durak : null;
}

// Idle life. The break an idle actor takes in its own slot of `ms` (molaDilimi): 'dinlenme' (its own seat: the kadro's
// lounge armchair / the Müdür's desk, an idle session's tea stool), 'cay' (a drink: the counter, then a lounge table),
// 'oyun' (the Oyun odası), 'yuruyus' (a short walk), 'sigara' (the terrace), 'wc', 'spor', 'masaj' or 'uyku' (a nap: once
// begun it holds on for UYKU_DILIM slots). Seeded by id and slot; resting stays the most common. `zorla`
// (state.sahne.mola, the demo's own scene setting; the server never sends it) forces one. `gece` (outside the office
// hours): only resting or a nap. `tatil` (a day off's day hours): never a nap; 'sohbet' (a chat standing in the
// Ortak alan) joins the choices. By day in the office hours a nap only in the lunch window (`ogle`; the owner, 2026-11-16:
// "mesai saatlerinde uyumasınlar … dolaşsın, kahvesini içsin, odasında dursun"): else a tea, a walk or its seat.
const molaTemel = (id, dilim) => {
  const h = hash(`${id}:mola:${dilim}`) % 40;
  return h < 16 ? 'dinlenme' : h < 23 ? 'cay' : h < 29 ? 'oyun' : h < 32 ? 'yuruyus' : h < 34 ? 'spor'
    : h < 36 ? 'sigara' : h < 38 ? 'wc' : h < 39 ? 'uyku' : 'masaj';
};
const uykuBoyu = (id, dilim) => UYKU_DILIM[0] + (hash(`${id}:uyku-boyu:${dilim}`) % (UYKU_DILIM[1] - UYKU_DILIM[0] + 1));
const gunduzMolasi = (id, dilim) => ['cay', 'yuruyus', 'dinlenme'][hash(`${id}:gunduz:${dilim}`) % 3];
export function molaEtkinligi(id, ms, zorla = '', { gece = false, tatil = false, ogle = false } = {}) {
  if (zorla && MOLA_ETKINLIKLERI.includes(zorla)) return zorla;
  const { dilim } = molaDilimi(id, ms);
  // a day off's day hours (tatil): awake — no nap; resting becomes a chat or a game now and then
  if (tatil) {
    const e = molaTemel(id, dilim);
    if (e !== 'uyku' && e !== 'dinlenme') return e;
    const h = hash(`${id}:tatil-mola:${dilim}`) % 4;
    return h === 0 ? 'oyun' : h === 1 ? 'sohbet' : 'dinlenme';
  }
  const uyuyabilir = gece || ogle;
  if (uyuyabilir) {
    for (let b = 1; b < UYKU_DILIM[1]; b++) if (molaTemel(id, dilim - b) === 'uyku' && b < uykuBoyu(id, dilim - b)) return 'uyku';
  }
  const e = molaTemel(id, dilim);
  if (gece && e !== 'dinlenme' && e !== 'uyku') return hash(`${id}:gece:${dilim}`) % 3 ? 'dinlenme' : 'uyku';
  if (e === 'uyku' && !uyuyabilir) return gunduzMolasi(id, dilim);
  return e;
}

// The duty staff's own breaks (Sekreter, guard) when nothing needs them, always close to their post: the guard eats at
// his post and now and then drinks water at the lobby's dispenser or looks out of the lobby door — never farther; the
// Sekreter has lunch at her canteen chair (off duty only: no decision waits) and now and then water at the dispenser.
// null = at the post. The caller checks duty first.
export function personelMolasi(id, ms, plan, ogle) {
  const nodes = (plan && plan.dugumler) || {};
  const guard = /^sus:guvenlik(:|$)/.test(String(id));
  const { dilim } = molaDilimi(id, ms);
  const h = hash(`${id}:mola:${dilim}`) % 6;
  if (ogle) { // a meal: true (lunch, as before) or its kind (ogun)
    const tur = ogle === true ? 'ogle' : ogle;
    if (guard) return { yer: 'lobi-nobet', poz: 'yemek', metin: tur === 'ogle' ? 'nöbette yemek yiyor' : `nöbette · ${OGUN_METNI[tur]}`, mola: true };
    if (nodes['yemekhane-personel-0']) return { yer: 'yemekhane-personel-0', poz: 'yemek', metin: OGUN_METNI[tur] || OGUN_METNI.ogle, mola: true };
  }
  if (h === 0 && nodes['lobi-su']) return { yer: 'lobi-su', poz: 'cay', metin: 'su içiyor', mola: true };
  if (h === 1 && guard && nodes['lobi-kapi']) return { yer: 'lobi-kapi', poz: 'bekliyor', metin: 'kapıya bakıyor' };
  return null;
}

// The roaming staff's "personality" (owner decision 2026-11-12): staff without real work (the social media team, the facility
// staff off duty, a project resident while its project has no open job) choose among idle-life options with a seeded
// per-actor weight — some like their desk, some the tea corner, the game room, the gym, the terrace or a chat in the
// lounge. Returns {masa, cay, oyun, spor, sigara, salon, yuruyus} (integers, masa ≥ 2: the desk is always an option).
export const PERSONEL_SECENEKLERI = ['masa', 'cay', 'oyun', 'spor', 'sigara', 'salon', 'yuruyus'];
export function personelKisiligi(id) {
  const out = {};
  for (const k of PERSONEL_SECENEKLERI) out[k] = hash(`${id}:kisilik:${k}`) % 5;
  out.masa = 2 + (hash(`${id}:kisilik:masa`) % 9); // 2..10: from restless to a desk-lover
  return out;
}
// The spots of each option (staff-only, never an agent's); a corridor walk needs none.
const PERSONEL_YERLERI = {
  cay: [['cay-ocagi-personel-2', 'cay', 'çay içiyor']],
  oyun: [['oyun-izleyici-0', 'bekliyor', 'oyunu izliyor'], ['oyun-izleyici-1', 'bekliyor', 'oyunu izliyor']],
  spor: [['spor-mat-2', 'yoga', 'spor yapıyor'], ['spor-mat-3', 'yoga', 'spor yapıyor']],
  sigara: [['sigara-yer-4', 'sigara', 'sigara molası']],
  salon: [['ortak-alan-sohbet-0', 'bekliyor', 'sohbet ediyor'], ['ortak-alan-sohbet-1', 'bekliyor', 'sohbet ediyor']],
};
// The corridor nodes nearest a seat (a short walk stays near home): the six nearest by walk length.
function yakinKoridorlar(plan, ev) {
  const nodes = (plan && plan.dugumler) || {};
  const g = nodes[ev] && Array.isArray(plan.kenarlar) ? grafOf(plan) : null; // the same plan gives the same six: cached
  const hit = g && g.yakinlar.get(ev);
  if (hit) return hit.slice();
  const corridors = Object.keys(nodes).filter((k) => nodes[k].tur === 'koridor').sort();
  if (!ev || !nodes[ev]) return corridors;
  const out = corridors.map((c) => [yolUzunlugu(plan, ev, c), c]).filter(([d]) => Number.isFinite(d))
    .sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1)).slice(0, 6).map(([, c]) => c);
  if (g) g.yakinlar.set(ev, out);
  return out.slice();
}
// This slot's choice of one staff member (its own slot, molaDilimi): the option picked with its weights, mapped to a
// free spot (`dolu`: the spots taken this tick; the spot it held in the previous tick is kept first) no farther than
// MOLA_UZAK from its seat `ev`. null = at its seat. opts: {ev, onceki, gece} — at night (gece) always null.
export function personelRotasi(id, ms, plan, dolu = new Set(), opts = {}) {
  const nodes = (plan && plan.dugumler) || {};
  if (opts.gece) return null;
  const w = personelKisiligi(id);
  const { dilim } = molaDilimi(id, ms);
  const total = PERSONEL_SECENEKLERI.reduce((n, k) => n + w[k], 0);
  let r = hash(`${id}:secim:${dilim}`) % total;
  let secim = 'masa';
  for (const k of PERSONEL_SECENEKLERI) { if (r < w[k]) { secim = k; break; } r -= w[k]; }
  if (secim === 'masa') return null;
  const yakin = (y) => !opts.ev || !nodes[opts.ev] || yolUzunlugu(plan, opts.ev, y) <= MOLA_UZAK;
  if (secim === 'yuruyus') {
    const corridors = yakinKoridorlar(plan, opts.ev);
    return corridors.length ? { yer: corridors[hash(`${id}:yuruyus:${dilim}`) % corridors.length], poz: 'yuruyor',
      metin: 'biraz dolaşıyor', secim, mola: true } : null;
  }
  const spots = (PERSONEL_YERLERI[secim] || []).filter(([y]) => nodes[y] && !dolu.has(y) && yakin(y));
  const spot = spots.find(([y]) => y === opts.onceki) || spots[0];
  if (!spot) return null;
  dolu.add(spot[0]);
  return { yer: spot[0], poz: spot[1], metin: spot[2], secim, mola: true };
}

// The Yemekhane sorumlusu (owner decision 2026-11-12), seeded per YEMEKHANE_ADIM_MS slot, never on a seat:
// - in the last OGLE_HAZIRLIK_DK minutes before lunch it sets things out at the serving counter;
// - at lunch, until the first eaters finish (OGLE_YEMEK_DK[0] minutes), it serves at the counter; then it alternates —
//   collecting the trays at a table's end (a seeded band) for most of a slot, carrying them to the Bulaşıkhane and
//   washing at the sink for the rest;
// - outside lunch: at the counter or the Bulaşıkhane, or wherever its personality takes it (personelRotasi; not at night).
// Since 2026-11-14 the yemekhane görevlisi on duty (YEMEKHANE_EKIBI) does the same at every meal of yemekPenceresi
// (breakfast, lunch, dinner — weekends too); opts: {id (the member: its seeds), onceki, gece}.
// Returns {yer, poz, metin, gorevde, faz} (faz: hazirlik | servis | topluyor | yikiyor | serbest).
export const YEMEKHANE_ADIM_MS = 120000;
export const OGLE_HAZIRLIK_DK = 15;
export function yemekhaneSorumlusu(now, plan, sahne, dolu = new Set(), opts = {}) {
  const ms = nowMs(now);
  const nodes = (plan && plan.dugumler) || {};
  const seg = Math.floor(ms / YEMEKHANE_ADIM_MS);
  const id = opts.id || 'sus:yemekhane';
  const o = yemekPenceresi(ms, sahne);
  const servis = { yer: YEMEKHANE_SERVIS, poz: 'cay-al', metin: 'servis yapıyor', gorevde: true, faz: 'servis' };
  const yika = { yer: YEMEKHANE_BULASIK, poz: 'yikiyor', metin: 'bulaşık yıkıyor', gorevde: true, faz: 'yikiyor' };
  if (o) {
    if (o.gecen < OGLE_YEMEK_DK[0] * (o.sure / 60)) return servis;
    const t = ms - seg * YEMEKHANE_ADIM_MS;
    if (t >= 0.65 * YEMEKHANE_ADIM_MS && nodes[YEMEKHANE_BULASIK]) return yika;
    const uclar = Object.keys(nodes).filter((k) => /^yemekhane-masa-ucu-\d+$/.test(k))
      .sort((a, b) => Number(a.split('-').pop()) - Number(b.split('-').pop()));
    if (!uclar.length) return yika;
    return { yer: uclar[hash(`yemekhane:topla:${seg}`) % uclar.length], poz: 'tepsi', metin: 'tepsileri topluyor', gorevde: true,
      faz: 'topluyor' };
  }
  const sonra = yemekPenceresi(ms, sahne, OGLE_HAZIRLIK_DK);
  if (sonra && sonra.gecen < OGLE_HAZIRLIK_DK) {
    return { yer: YEMEKHANE_SERVIS, poz: 'cay-al', metin: OGUN_HAZIRLIK[sonra.tur], gorevde: true, faz: 'hazirlik' };
  }
  const { dilim } = molaDilimi(id, ms);
  const h = hash(`${id === 'sus:yemekhane' ? 'yemekhane' : id}:serbest:${dilim}`) % 4;
  if (h === 0) return { yer: YEMEKHANE_SERVIS, poz: 'bekliyor', metin: 'tezgâhta', gorevde: false, faz: 'serbest' };
  if (h === 1 && nodes[YEMEKHANE_BULASIK]) return { ...yika, metin: 'bulaşıkhaneyi topluyor', gorevde: false, faz: 'serbest' };
  const m = personelRotasi(id, ms, plan, dolu, { ev: YEMEKHANE_SERVIS, onceki: opts.onceki, gece: !!opts.gece });
  return m ? { yer: m.yer, poz: m.poz, metin: m.metin, gorevde: false, faz: 'serbest', mola: true }
    : { yer: YEMEKHANE_SERVIS, poz: 'bekliyor', metin: 'tezgâhta', gorevde: false, faz: 'serbest' };
}
const OGUN_HAZIRLIK = { kahvalti: 'kahvaltıyı hazırlıyor', ogle: 'öğle yemeğini hazırlıyor', aksam: 'akşam yemeğini hazırlıyor' };
// The aşçı on duty (ASCI_EKIBI, 2026-11-14), in the kitchen corner, never on a seat: from ASCI_HAZIRLIK_DK minutes
// before a meal until its end it cooks — at the stove most of each YEMEKHANE_ADIM_MS slot, a moment at the fridge —;
// otherwise it cleans the stove or tidies the fridge (seeded per slot). Returns {yer, poz, metin, gorevde, faz:
// pisiriyor | temizlik}.
export const ASCI_HAZIRLIK_DK = 45;
export function asciPlani(now, plan, sahne, opts = {}) {
  const ms = nowMs(now);
  const nodes = (plan && plan.dugumler) || {};
  const id = opts.id || 'sus:asci';
  const ocak = nodes[YEMEKHANE_OCAK] ? YEMEKHANE_OCAK : YEMEKHANE_BULASIK;
  const dolap = nodes[YEMEKHANE_DOLAP] ? YEMEKHANE_DOLAP : ocak;
  const seg = Math.floor(ms / YEMEKHANE_ADIM_MS);
  const t = ms - seg * YEMEKHANE_ADIM_MS;
  const p = yemekPenceresi(ms, sahne) || yemekPenceresi(ms, sahne, ASCI_HAZIRLIK_DK);
  if (p) {
    // a trip to the fridge in one slot of three (calm walking: the stove is its place)
    if (t >= 0.8 * YEMEKHANE_ADIM_MS && hash(`${id}:dolap:${seg}`) % 3 === 0) {
      return { yer: dolap, poz: 'cay-al', metin: 'malzeme alıyor', gorevde: true, faz: 'pisiriyor' };
    }
    return { yer: ocak, poz: 'yikiyor', metin: { kahvalti: 'kahvaltıyı hazırlıyor', ogle: 'öğle yemeğini pişiriyor', aksam: 'akşam yemeğini pişiriyor' }[p.tur],
      gorevde: true, faz: 'pisiriyor' };
  }
  const h = hash(`${id}:mutfak:${seg}`) % 3;
  if (h === 0) return { yer: dolap, poz: 'bekliyor', metin: 'dolabı düzenliyor', gorevde: false, faz: 'temizlik' };
  return { yer: ocak, poz: h === 1 ? 'yikiyor' : 'bekliyor', metin: h === 1 ? 'ocağı temizliyor' : 'mutfakta', gorevde: false, faz: 'temizlik' };
}

// The restroom door of an actor: a stable per-actor seed (the robots have no gender; no label or card names it).
export function wcKapisi(id) {
  return hash(`${id}:wc`) % 2;
}

// The places of the idle actors' breaks: list = [{id, kadro, uzun, yorgun, zorla, onceki (its place in the previous
// tick), ev (its own seat)}] (idle kadro, idle sessions, idle auditors, the CEO on a break — the caller never passes a
// working, waiting, Kontrol or permission actor, and none at lunch or in hafif). Returns Map id -> {yer, poz, metin,
// mola: true}; an actor left out (resting, or no free spot near its seat) stays at its own seat. Each pool hands out
// the spot an actor held in the previous tick first, then the free spots nearest its seat (never farther than
// MOLA_UZAK). Games need company: the first two players take the table-tennis table, the next two the billiards table
// (one leans with the cue, the other waits), one more throws darts, the next sits on the bean bag. opts: {doluYataklar,
// gece}.
export function molaPlani(list, ms, plan, zorla = '', opts = {}) {
  const out = new Map();
  const nodes = (plan && plan.dugumler) || {};
  const has = (id) => !!nodes[id];
  // a day off (tatil): the whole office is theirs, no distance limit
  const uzak = (a, y) => !opts.tatil && a.ev && has(a.ev) && yolUzunlugu(plan, a.ev, y) > MOLA_UZAK;
  const pool = (spots) => ({ spots: spots.filter(([y]) => has(y)), alinan: new Set() });
  const P = {
    tezgah: pool([0, 1].map((i) => [`cay-ocagi-tezgah-yer-${i}`])),
    kafe: pool([0, 1, 2, 3].map((i) => [`ortak-alan-yer-${i}`])),
    sigara: pool(SIGARA_AJAN_YERLERI),
    alet: pool([['spor-kosu-0', 'kosuyor'], ['spor-kosu-1', 'kosuyor'], ['spor-bisiklet', 'bisiklet'], ['spor-agirlik', 'agirlik'],
      ['spor-mat-0', 'yoga'], ['spor-mat-1', 'yoga']]),
    masaj: pool([0, 1].map((i) => [`masaj-yatak-${i}`])),
    // tatil only: the two standing chat places of the Ortak alan (the roaming staff's by day; they are at the Otel)
    sohbet: pool(opts.tatil ? [0, 1].map((i) => [`ortak-alan-sohbet-${i}`]) : []),
    yatak: pool(Array.from({ length: DINLENME_YATAK }, (_, i) => [`dinlenme-yatak-${i}`])
      .filter(([y]) => !(Array.isArray(opts.doluYataklar) && opts.doluYataklar.includes(y)))),
  };
  const sonra = (a) => (String(a.id).startsWith('denetci:') ? 1 : 0); // the office's own staff first
  const sorted = [...(list || [])].filter((a) => a && a.id).sort((a, b) => sonra(a) - sonra(b) || (a.id < b.id ? -1 : 1));
  const istek = []; // [{a, havuz, metin(spot) -> {poz, metin}}]
  const players = [];
  const tek = new Set(); // single places taken this tick (a WC cubicle, a shower)
  for (const a of sorted) {
    const { dilim, gecen } = molaDilimi(a.id, ms);
    const e = molaEtkinligi(a.id, ms, a.zorla || zorla, { gece: !!opts.gece, tatil: !!opts.tatil, ogle: !!opts.ogle });
    if (e === 'cay') {
      const drink = hash(`${a.id}:icecek:${dilim}`) % 2 ? 'kahve' : 'çay';
      if (gecen < MOLA_CAY_MS) istek.push({ a, havuz: P.tezgah, f: () => ({ poz: 'cay-al', metin: `${drink} alıyor` }) });
      else istek.push({ a, havuz: P.kafe, f: () => ({ poz: 'cay', metin: `${drink} içiyor · ortak alan` }) });
    } else if (e === 'sigara') istek.push({ a, havuz: P.sigara, f: (s) => ({ poz: s[1], metin: s[2] }) });
    else if (e === 'wc') {
      const kapi = wcKapisi(a.id);
      const yer = gecen < WC_ICERDE_MS ? `wc-ici-${kapi}` : gecen < WC_LAVABO_MS ? `wc-lavabo-${kapi}` : null;
      if (yer && has(yer) && !tek.has(`wc-${kapi}`) && !uzak(a, yer)) {
        tek.add(`wc-${kapi}`);
        out.set(a.id, yer.startsWith('wc-ici') ? { yer, poz: 'lavaboda', metin: 'lavaboda', mola: true }
          : { yer, poz: 'bekliyor', metin: 'ellerini yıkıyor', mola: true });
      }
    } else if (e === 'spor') {
      const dus = hash(`${a.id}:dus:${dilim}`) % 2 === 0;
      const kabin = wcKapisi(`${a.id}:dus`);
      if (gecen >= SPOR_MS && dus && has(`dus-ici-${kabin}`) && !tek.has(`dus-${kabin}`)) {
        tek.add(`dus-${kabin}`);
        out.set(a.id, { yer: `dus-ici-${kabin}`, poz: 'dusta', metin: 'duşta', mola: true });
      } else if (gecen < SPOR_MS) istek.push({ a, havuz: P.alet, f: (s) => ({ poz: s[1], metin: 'spor yapıyor' }) });
    } else if (e === 'masaj') {
      if (a.yorgun) istek.push({ a, havuz: P.masaj, f: () => ({ poz: 'masajda', metin: 'masajda' }) });
    } else if (e === 'uyku') {
      if (a.uzun) istek.push({ a, havuz: P.yatak, f: () => ({ poz: 'yatiyor', metin: opts.gece ? 'uyuyor' : 'dinleniyor · uyuyor' }) });
    } else if (e === 'sohbet') istek.push({ a, havuz: P.sohbet, f: () => ({ poz: 'bekliyor', metin: 'sohbet ediyor' }) });
    else if (e === 'oyun') players.push(a);
    else if (e === 'yuruyus') {
      const cs = yakinKoridorlar(plan, a.ev);
      if (cs.length) {
        out.set(a.id, { yer: cs[hash(`${a.id}:yuruyus:${dilim}`) % cs.length], poz: 'yuruyor',
          metin: a.kadro ? 'hazır · biraz dolaşıyor' : 'boşta · dolaşıyor', mola: true });
      }
    }
  }
  // pass 1: keep the spot held in the previous tick; pass 2: the nearest free spot to the actor's seat
  const ver = (r, s) => { r.havuz.alinan.add(s[0]); out.set(r.a.id, { yer: s[0], ...r.f(s), mola: true }); };
  const kalan = [];
  for (const r of istek) {
    const s = r.havuz.spots.find(([y]) => y === r.a.onceki && !r.havuz.alinan.has(y));
    if (s) ver(r, s); else kalan.push(r);
  }
  for (const r of kalan) {
    const free = r.havuz.spots.filter(([y]) => !r.havuz.alinan.has(y) && !uzak(r.a, y));
    if (!free.length) continue;
    const d = (y) => (r.a.ev && has(r.a.ev) ? yolUzunlugu(plan, r.a.ev, y) : 0);
    ver(r, free.slice().sort((x, y) => d(x[0]) - d(y[0]) || x[0].localeCompare(y[0], 'en', { numeric: true }))[0]);
  }
  const games = [];
  if (players.length >= 2 && has('oyun-pingpong-0')) {
    games.push(['oyun-pingpong-0', 'pingpong', 'masa tenisi oynuyor'], ['oyun-pingpong-1', 'pingpong', 'masa tenisi oynuyor']);
  }
  if (players.length - games.length >= 2 && has('oyun-bilardo-0')) {
    games.push(['oyun-bilardo-0', 'bilardo', 'bilardo oynuyor'], ['oyun-bilardo-1', 'bekliyor', 'bilardo oynuyor']);
  }
  if (has('oyun-dart')) games.push(['oyun-dart', 'dart', 'dart atıyor']);
  if (has('oyun-puf')) games.push(['oyun-puf', 'bekliyor', 'puf koltukta dinleniyor']);
  const oyunda = new Set();
  const oyuna = (a, g) => { oyunda.add(g[0]); out.set(a.id, { yer: g[0], poz: g[1], metin: g[2], mola: true }); };
  const bekleyen = [];
  for (const a of players) { const g = games.find((x) => x[0] === a.onceki && !oyunda.has(x[0])); if (g) oyuna(a, g); else bekleyen.push(a); }
  for (const a of bekleyen) { const g = games.find((x) => !oyunda.has(x[0])); if (g && !uzak(a, g[0])) oyuna(a, g); }
  return out;
}

// The announcement's window: {id, ilk_satir, alanlar (the sessions it reached), bitis} while it was delivered less than
// DUYURU_MS ago (a few seconds of clock skew allowed), else null.
export function duyuruPenceresi(state, now) {
  const st = state || {};
  const d = st.duyuru;
  if (!d || typeof d !== 'object' || typeof d.zaman !== 'string' || !d.zaman) return null;
  const sahne = { ...DEFAULT_SAHNE, ...(st.sahne || {}) };
  const ofset = Number.isFinite(sahne.sunucu_utc_ofset_dk) ? sahne.sunucu_utc_ofset_dk : null;
  const t0 = zamanMs(d.zaman, sahne.saat_dilimi, ofset);
  const ms = nowMs(now);
  if (t0 === null || ms < t0 - 5000 || ms - t0 >= DUYURU_MS + DUYURU_TOPLANMA_MS) return null;
  return { id: String(d.id || ''), ilk_satir: kisa(d.ilk_satir, 120),
    alanlar: new Set(Array.isArray(d.alanlar) ? d.alanlar.filter((x) => typeof x === 'string') : []), bitis: t0 + DUYURU_MS + DUYURU_TOPLANMA_MS };
}

// The conference hall's screen text now: the announcement's first line during its window (also in hafif), else ''
// (the scene shows the office's name). Plain text only: the scene draws it on a canvas with fillText.
export function salonEkrani(state, now) {
  const p = duyuruPenceresi(state, now);
  return p ? p.ilk_satir : '';
}

export function niyetler(state, now, prev = null, options = {}) {
  const st = state || {};
  const ms = nowMs(now);
  const sahne = { ...DEFAULT_SAHNE, ...(st.sahne || {}) };
  const tz = sahne.saat_dilimi;
  const ofset = Number.isFinite(sahne.sunucu_utc_ofset_dk) ? sahne.sunucu_utc_ofset_dk : null;
  const ogle = ogleMi(ms, sahne);
  // at lunch an idle actor eats only in its own seeded part of the hour (ogleYemekte); in hafif the whole hour, and
  // also with sahne.ogle_hepsi (the demo's lunch scene; never sent by the server)
  const hafif = !!options.hafif;
  // the meals (ogun, owner decision 2026-11-14): breakfast, lunch and dinner; `o` = {kim, gel, ekip} (ogun's options)
  const ogunu = (id, o = {}) => {
    if (ogle && (hafif || sahne.ogle_hepsi === true) && (!mesaiAraligi(sahne) || isGunuMu(ms, sahne))) return 'ogle';
    return ogun(id, ms, sahne, o);
  };
  const yemekte = (id, o) => !!ogunu(id, o);
  const yemekMetni = (id, o) => OGUN_METNI[ogunu(id, o)] || OGUN_METNI.ogle;
  // outside the office hours (sahne.mesai): no games, smoking or gym for the staff (they are at the Otel); the agents
  // sleep at night (uyku). A day off's day hours (tatil, owner decision 2026-11-14): the agents are awake and spend the day in
  // the common areas (molaPlani with `tatil`), never at their work desks unless real work takes them there
  const gece = !mesaiMi(ms, sahne);
  const tatil = gece ? serbestZaman(ms, sahne) : null;
  const uyku = gece && !tatil;
  const tatilMetni = (x) => `${tatilSozu(tatil)} · ${String(x).replace(/^(hazır|boşta) · /, '')}`;
  const plan = options.plan || planOnbellekli(st.projects || [], { denetciler: denetciListesi(st.modeller), ...options });
  const projects = new Set(plan.projeler);
  const prevDesk = new Map();
  const prevYer = new Map();
  const prevPoz = new Map();
  for (const a of prev || []) {
    if (!a || !a.id) continue;
    if (a.masa) prevDesk.set(a.id, a.masa);
    if (a.yer) prevYer.set(a.id, a.yer);
    prevPoz.set(a.id, a.poz);
  }
  const prevOf = (id) => (Array.isArray(prev) ? prev.find((a) => a && a.id === id) : null) || null;
  const sure = (from, to) => yurumeSuresi(plan, from, to);
  const katmanlar = st.katmanlar && typeof st.katmanlar === 'object' ? st.katmanlar : null;

  const tasks = allTasks(st).map((t) => ({ ...t, _bitis: zamanMs(t.finished, tz, ofset) }));
  // a new job to hand over (the teslim cue below) is real work: the CEO and the Genel Müdür skip or leave their meal for it
  const ceoTeslimde = !hafif && (() => {
    const pc0 = prevOf('ceo');
    if (pc0 && pc0.teslim && Number.isFinite(pc0.teslim.bitis) && ms < pc0.teslim.bitis) return true;
    const verilen = new Set(pc0 && Array.isArray(pc0.teslim_verilen) ? pc0.teslim_verilen : []);
    return tasks.some((t) => { const c0 = zamanMs(t.created, tz, ofset);
      return c0 !== null && ms >= c0 && ms < c0 + TESLIM_PENCERE_MS && !onayAdimi(t) && !panelIncelemesi(t) && !verilen.has(notAdi(t.note)); });
  })();
  const byNote = new Map(tasks.map((t) => [notAdi(t.note), t]));
  const escalatedTo = new Map();
  for (const t of tasks) if (t.escalated_from) escalatedTo.set(notAdi(t.escalated_from), t);
  const latestBySession = new Map();
  for (const t of tasks) if (t.session && !latestBySession.has(t.session)) latestBySession.set(t.session, t);

  const actors = [];
  const used = new Set();
  const make = (proje, session, task) => {
    const model = isModeli(task, session, katmanlar);
    const u = unvanOf(model);
    const calisiyor = !!session && (session.status === 'busy' || acikYardimci(session.alt_ajanlar));
    const kota = calisiyor ? '' : kotaMetni(st.modeller, model, ms, tz);
    const n = niyet({ session, calisiyor, task, kota, ms, escalatedTo: task && escalatedTo.get(notAdi(task.note)),
      title: task && task.title });
    if (!n) return;
    const id = task ? `is:${notAdi(task.note)}` : `oturum:${session.name}`;
    if (used.has(id)) return;
    used.add(id);
    const uz = isUzmanligi(task, session);
    const a = { id, tur: 'ajan', unvan: u.unvan, rank: u.rank, model: modelAilesi(model), proje, yer: null, masa: null,
      rol_metni: rolMetni(model, uz), uzmanlik: uz,
      poz: n.poz, simge: n.simge, etiket: etiketOf(proje, model, uz), durum_metni: n.metin,
      tiklama: task ? { note: task.note } : null, _n: n, _session: session, _task: task,
      _tier: (session && session.tier) || (task && task.tier) || '' };
    if (task) a.is_durumu = task.status;
    // a cue (B4): the first Kontrol failure — the job was in its Kontrol in the previous tick and is working again with
    // the result 'kaldi' — shows a small "✗" at the desk for KONTROL_ISARET_MS (never a red mark: nobody is stuck)
    const pa = task ? prevOf(id) : null;
    let isaret = pa && Number.isFinite(pa.kontrol_kaldi) && ms < pa.kontrol_kaldi ? pa.kontrol_kaldi : null;
    if (!isaret && pa && pa.is_durumu === 'kontrolde' && task.status === 'calisiyor' && task.kontrol_sonuc === 'kaldi') {
      isaret = ms + KONTROL_ISARET_MS;
    }
    if (isaret && task.status === 'calisiyor' && n.yer === 'masa') {
      a.kontrol_kaldi = isaret; a.simge = 'kaldi'; a.durum_metni = 'Kontrol geçmedi · düzeltiyor';
    }
    actors.push(a);
  };

  for (const s of st.sessions || []) {
    if (!s || !projects.has(s.project)) continue;
    const task = (s.note && byNote.get(notAdi(s.note))) || latestBySession.get(s.name) || null;
    make(s.project, s, task);
  }
  const listed = new Set((st.sessions || []).map((s) => s && s.name));
  const lobby = [];
  for (const t of tasks) {
    if (!projects.has(t.project) || (t.session && listed.has(t.session))) continue;
    // never a robot for work no Claude session does: a workflow's approval (the owner's decision: the Sekreter's paper and
    // the decision card show it) and a review the panel runs (Codex / the free reviewers: the auditors' desks and the
    // hakem show it), in any state
    if (onayAdimi(t) || panelIncelemesi(t)) continue;
    if (t.status === 'sirada') { lobby.push(t); continue; }
    if (t.status === 'incelemede') continue; // a Codex review: the auditor's desk shows it
    if (t.session && latestBySession.get(t.session) !== t) continue; // an older job of that session
    make(t.project, null, t);
  }

  // desks, claimed in order of oncelik (working first): each level first keeps its desks from prev, then takes a free
  // desk — one nobody below it held before, if possible. A lower level whose old desk went to a higher one moves; what
  // does not fit and must sit at a desk (or show its "Evde" sign there) is summarised as "+N" in the team area. The
  // manager's desk is only for Müdür / planning work.
  const ozet = [];
  const helperCount = (a) => (a._session && a._session.alt_ajanlar || []).filter((h) => h && h.id && !h.bitti).length;
  // plan "Sonraki iş (9)": the planning desk in the Yazılım Müdürü's office — the first planning worker (tier planlama or a
  // workflow's plan step, whichever model and project) that needs a desk works there; the one that sat there keeps it.
  // Its label says on whose behalf: the Genel Müdür (Fable) or its seniority, "(Yazılım Müdürü adına)".
  if (plan.dugumler[PLAN_MASASI]) {
    const plancilar = actors.filter((a) => a._n.yer === 'masa' && planIsi(a._task, a._session))
      .sort((a, b) => a._n.oncelik - b._n.oncelik || (prevDesk.get(b.id) === PLAN_MASASI) - (prevDesk.get(a.id) === PLAN_MASASI) ||
        (a.id < b.id ? -1 : 1));
    if (plancilar.length) plancilar[0].masa = PLAN_MASASI;
  }
  for (const a of actors) {
    if (!planIsi(a._task, a._session)) continue;
    a.rol = 'plan';
    a.etiket = `${a.etiket} (Yazılım Müdürü adına)`;
  }
  // the Genel Müdür's office desk: the first other fable-family worker that needs a desk (whichever project) works there —
  // the one that already sat there keeps it; other planning work uses its team's manager's desk
  if (plan.dugumler[MUDUR_MASASI]) {
    const boss = actors.filter((a) => a._n.yer === 'masa' && a.model === 'fable' && !a.masa)
      .sort((a, b) => a._n.oncelik - b._n.oncelik || (prevDesk.get(b.id) === MUDUR_MASASI) - (prevDesk.get(a.id) === MUDUR_MASASI) ||
        (a.id < b.id ? -1 : 1));
    if (boss.length) boss[0].masa = MUDUR_MASASI;
  }
  for (const p of plan.projeler) {
    const team = actors.filter((a) => a.proje === p);
    const desks = [`ekip-${p}-mudur`, ...Array.from({ length: plan.masa_sayisi }, (_, i) => `ekip-${p}-masa-${i + 1}`)];
    const taken = new Map();
    const claimed = new Set(team.map((a) => prevDesk.get(a.id)).filter(Boolean));
    const levels = [...new Set(team.map((a) => a._n.oncelik))].sort((x, y) => x - y);
    // within a level, those that must be shown at a desk (yer 'masa', e.g. an "Evde" sign) come first; an idle
    // agent (tea, wander, lunch) or one leaving never takes a free desk. Levels 0 and 1 (working, waiting, starting)
    // fall back to a free manager's desk when the regular desks are gone.
    const deskFirst = (a, b) => ((a._n.yer === 'masa' ? 0 : 1) - (b._n.yer === 'masa' ? 0 : 1)) || (a.id < b.id ? -1 : 1);
    for (const level of levels) {
      const group = team.filter((a) => a._n.oncelik === level).sort(deskFirst);
      for (const a of group) {
        const d = prevDesk.get(a.id);
        if (!a.masa && d && desks.includes(d) && !taken.has(d)) { taken.set(d, a.id); a.masa = d; }
      }
      for (const a of group) {
        if (a.masa || a._n.yer === 'bosta' || a._n.yer === 'cikis') continue;
        const boss = a.rank >= UNVAN.fable.rank || a._tier === 'planlama';
        let order = (boss ? desks : desks.slice(1)).filter((x) => !taken.has(x));
        if (!order.length && level <= 1 && !taken.has(desks[0])) order = [desks[0]];
        const d = order.find((x) => !claimed.has(x)) || order[0];
        if (d) { taken.set(d, a.id); a.masa = d; }
      }
    }
    const left = team.filter((a) => !a.masa && a._n.yer === 'masa');
    if (left.length) {
      for (const a of left) a._gizli = true;
      const yardimci = left.reduce((n, a) => n + helperCount(a), 0);
      ozet.push(ozetAktor(`ozet:ekip-${p}`, `ekip-${p}-ozet`, p, left.length,
        `${left.length} ajan daha: ${left.map((a) => a.durum_metni).join(', ')}` +
        (yardimci ? ` · ${yardimci} yardımcı` : ''), left));
    }
  }

  // places; a room that is full gets one "+N" stand-in instead of two actors on one spot. The last canteen chair is
  // the CEO's.
  const visible = actors.filter((a) => !a._gizli).sort((a, b) => (a.id < b.id ? -1 : 1));
  // the canteen chairs of the agents and the staff (every 'yemekhane-sandalye-<n>' but the CEO's, 7), in order
  const yemekYerleri = planListesi(plan, 'yemek', () => Object.keys(plan.dugumler)
    .filter((id) => /^yemekhane-sandalye-\d+$/.test(id) && id !== 'yemekhane-sandalye-7')
    .sort((a, b) => Number(a.slice(19)) - Number(b.slice(19))));
  const rooms = {
    kuyruk: { spots: 6, prefix: 'ceo-kuyruk-', ozet: 'ceo-kuyruk-ozet', list: [], metin: 'karar bekliyor' },
    uzmanlar: { spots: OLCU.UZMAN_MASA, prefix: 'uzmanlar-masa-', ozet: 'uzmanlar-ozet', list: [], metin: 'Uzmanlar odasında',
      masa: true },
    // plan "Sonraki iş (9)": a Claude kod review (and an inceleme-tier job) at a desk of the QA odası — a haiku review at a
    // Stajyer Tester desk first, any other at a Kıdemli Tester desk —, a plan review at a desk of the Analist odası
    qa: { spots: EKIP_ODASI_MASA, prefix: 'qa-masa-', ozet: 'qa-ozet', list: [], metin: 'QA odasında', masa: true,
      sira: (a) => (a.model === 'haiku' ? [...QA_MASALARI.stajyer, ...QA_MASALARI.kidemli] : [...QA_MASALARI.kidemli, ...QA_MASALARI.stajyer]) },
    analist: { spots: EKIP_ODASI_MASA, prefix: 'analist-masa-', ozet: 'analist-ozet', list: [], metin: 'Analist odasında',
      masa: true },
    yemek: { spots: yemekYerleri.length, yerler: yemekYerleri, prefix: 'yemekhane-sandalye-', ozet: 'yemekhane-ozet', list: [],
      metin: 'yemekte' },
    cay: { spots: 9, prefix: 'cay-ocagi-yer-', ozet: 'cay-ocagi-ozet', list: [], metin: 'çay ocağında' },
  };
  const molacilar = []; // idle actors whose break molaPlani chooses: [{id, kadro, a}]
  // a day off's day hours (tatil): the idle agents whose own seat is a work desk (the auditors, the Genel Müdür, the CEO)
  // and who got no leisure spot sit on the tea corner's stools instead: [{a, masa}] (masa: its seat is a desk)
  const tatilKoltuk = [];
  // GECE_UYKUSU (owner decision 2026-11-13): at night (uyku: outside the office hours' clock window, every day — a day off's day
  // hours are awake, see tatil; owner decision 2026-11-14) every agent character in the office without real work — the free CEO, the idle kadro (the Genel Müdür
  // too), the idle auditors, the idle sessions — sleeps in its own bed of the Dinlenme odası (molaPlani with the
  // break forced to 'uyku': the bed it held keeps, else the first free one; "uyuyor", lying). Also in hafif (places
  // only). Real work first: a job, a review, the hakem or the security reviewer takes the body to its desk (devral) and
  // it walks back to bed after. The people on shift (guard, Sekreter, IT) keep their duties; the staff are home.
  // the review panel's phase (state.denetim, bin/state.py): the hakem takes the first desk of the Uzmanlar odası
  const denetim = st.denetim && typeof st.denetim === 'object' ? st.denetim : null;
  const review = tasks.find((t) => t.status === 'incelemede' && t.inceleme_yurutucu === 'codex') || null;
  const denetimNot = denetim && typeof denetim.is === 'string' && denetim.is ? notAdi(denetim.is)
    : (review ? notAdi(review.note) : '');
  const reviewed = denetimNot ? byNote.get(denetimNot) || null : null;
  const reviewClick = denetimNot ? { note: reviewed ? reviewed.note : `${denetimNot}.md` } : null;
  const hakemModel = denetim && typeof denetim.hakem === 'string' ? denetim.hakem : '';
  let hakem = null;
  if (hakemModel) {
    const hu = unvanOf(hakemModel, UNVAN.sonnet);
    const hf = modelAilesi(hakemModel);
    hakem = { id: 'hakem', tur: 'ajan', hakem: true, unvan: hu.unvan, rank: hu.rank, model: hf,
      proje: reviewed ? reviewed.project : '', yer: null, masa: null, poz: 'yaziyor', simge: null,
      etiket: `Hakem (${aileAdi(hf) || kisa(hakemModel, 20)})`, ipucu: `Hakem (${aileAdi(hf) || kisa(hakemModel, 20)})`, durum_metni: 'bulguları tartıyor', tiklama: reviewClick };
    rooms.uzmanlar.list.push(hakem);
  }
  for (const a of visible) {
    const n = a._n;
    if (n.yer === 'masa') a.yer = a.masa;
    else if (n.yer === 'kuyruk') rooms.kuyruk.list.push(a);
    else if (n.yer === 'uzman') {
      const oda = incelemeOdasi(a._task, a._session);
      if (plan.dugumler[`${oda}-masa-0`]) { rooms[oda].list.push(a); a.rol = oda; a.etiket = incelemeEtiketi(a, oda); }
      else rooms.uzmanlar.list.push(a);
    }
    else if (n.yer === 'cikis') { a.yer = 'asansor'; a.cikis = true; }
    else if (n.yer === 'bosta') {
      if (yemekte(a.id)) { a.poz = 'yemek'; a.durum_metni = yemekMetni(a.id); rooms.yemek.list.push(a); }
      // at night (also in hafif) an idle session sleeps in a bed of the Dinlenme odası (GECE_UYKUSU)
      else if (uyku) molacilar.push({ id: a.id, kadro: false, uzun: true, a, onceki: prevYer.get(a.id), ev: null, zorla: 'uyku' });
      else if (hafif) { a.poz = 'cay'; a.durum_metni = 'boşta · çay molası'; a.mola = true; rooms.cay.list.push(a); }
      else { // its break is chosen with the idle kadro (molaPlani); a nap only after OTURUM_UYKU_MS idle
        const since = a._task ? a._task._bitis : null;
        molacilar.push({ id: a.id, kadro: false, uzun: since !== null && ms - since > OTURUM_UYKU_MS, a,
          onceki: prevYer.get(a.id), ev: 'cay-ocagi-yer-0' });
      }
    }
  }
  // the resident staff (kadro): per Claude model, while no job or session of that model is in the office (one
  // leaving through the lift does not count), its character idles in the shared lounge — at lunch in the canteen,
  // now and then a short wander (not in hafif); kota -> its "Evde" sign at the lounge seat, hata -> red mark. The
  // first new worker of a model takes the idle kadro over (`devral`: the scene walks that body from the lounge to the
  // desk); the last worker whose job ended walks back as the kadro instead of leaving through the lift.
  // A hakem or security-reviewer call is its model family at work too: that family's kadro takes the call over (walks
  // to its desk in the Uzmanlar odası / the security desk) and walks back after; with both at once the other comes by lift.
  const prevIds = new Set((prev || []).map((a) => a && a.id).filter(Boolean));
  const modelRowsK = Array.isArray(st.modeller) ? st.modeller : [];
  const secRow = modelRowsK.find((m) => guvenlikSatiriMi(m)) || null;
  const secWorking = denetim && Array.isArray(denetim.denetciler) ? denetim.denetciler.includes(GUVENLIK) : null;
  const secBusy = secWorking !== null ? secWorking : !!secRow && Number(secRow.calisan) > 0;
  const secShown = secBusy && !!plan.dugumler[denetciMasasi(GUVENLIK)] && (!!secRow || secWorking === true);
  const cagrilar = [
    { id: `denetci:${GUVENLIK}`, aile: secShown ? modelAilesi(secRow && secRow.ajan_modeli) || 'sonnet' : '' },
    { id: 'hakem', aile: hakem ? hakem.model : '' },
  ].filter((c) => c.aile);
  const devralCagri = {};
  const kadro = [];
  const kadroCikan = []; // kadro members walking out by the lift (their model's queued job started from the lobby)
  const kadroCikisi = (f, pk, bitis) => ({ id: `kadro:${f}`, tur: 'ajan', kadro: true, unvan: UNVAN[f].unvan,
    rank: UNVAN[f].rank, model: f, proje: '', yer: 'asansor', masa: null, poz: 'yuruyor', simge: null,
    etiket: `${UNVAN[f].unvan} (${KADRO_ADI[f]})`, kisa_etiket: `${UNVAN[f].unvan} (${KADRO_ADI[f]})`, durum_metni: 'çıkıyor',
    tiklama: null, cikis: true, cikis_bitis: bitis });
  for (const f of KADRO) {
    const fam = actors.filter((a) => a.model === f);
    const present = fam.filter((a) => a._n.yer !== 'cikis');
    const calls = cagrilar.filter((c) => c.aile === f);
    const kid = `kadro:${f}`;
    if (present.length || calls.length) {
      const pk = prevOf(kid);
      if (prevIds.has(kid) && !(pk && pk.cikis)) {
        // a worker new to the floor takes the idle kadro over (the same body walks to the desk); a queued job starting
        // from the lobby already has its body (the lobby robot walks to its desk), so the kadro walks out by the lift
        const yeni = present.filter((a) => !prevIds.has(a.id) || prevPoz.get(a.id) === 'lobide')
          .sort((a, b) => a._n.oncelik - b._n.oncelik || (a.id < b.id ? -1 : 1))[0];
        const call = calls.find((c) => !prevIds.has(c.id));
        if (yeni && !prevIds.has(yeni.id)) yeni.devral = kid;
        else if (yeni) kadroCikan.push(kadroCikisi(f, pk, ms + sure(prevYer.get(kid) || kadroYeri(f), 'asansor')));
        else if (call) devralCagri[call.id] = kid;
      } else if (pk && pk.cikis && Number.isFinite(pk.cikis_bitis) && ms < pk.cikis_bitis) {
        kadroCikan.push(kadroCikisi(f, pk, pk.cikis_bitis)); // still walking to the lift
      }
      continue;
    }
    const m = (Array.isArray(st.modeller) ? st.modeller : []).find((x) => x && x.model === f) || {};
    const u = UNVAN[f];
    const k = { id: kid, tur: 'ajan', kadro: true, unvan: u.unvan, rank: u.rank, model: f, proje: '',
      yer: kadroYeri(f), masa: f === 'fable' ? MUDUR_MASASI : null, poz: 'bekliyor', simge: null,
      // role first, the model in parentheses, as on the side panel ("Kıdemli (Opus)")
      etiket: `${u.unvan} (${KADRO_ADI[f]})`,
      kisa_etiket: `${u.unvan} (${KADRO_ADI[f]})`, durum_metni: 'hazır · iş bekliyor', tiklama: null };
    const leaving = fam.filter((a) => a._n.yer === 'cikis').sort((a, b) => (a.id < b.id ? -1 : 1))[0];
    if (leaving) leaving._gizli = true; // it walks back to the lounge as the kadro
    if (!prevIds.has(kid) && prev) {
      const was = leaving || (prev || []).find((a) => a && (a.model === f || a.aile === f) && a.tur === 'ajan' &&
        !a.kadro && (/^(is|oturum):/.test(a.id) || a.id === 'hakem' || a.id === `denetci:${GUVENLIK}`) &&
        !actors.some((x) => x.id === a.id && !x._gizli));
      if (was) k.devral = was.id;
    }
    if (m.durum === 'kota') {
      k.poz = 'evde';
      const d = donusMetni(m.donus, ms, tz);
      k.durum_metni = d ? `Evde · ${d}` : 'Evde · kota doldu';
    } else if (m.durum === 'hata') { k.simge = 'kirmizi'; k.durum_metni = 'son çağrı hata verdi'; }
    else if (m.durum === 'hazir' || m.durum === 'calisiyor') {
      if (yemekte(kid) && !(f === 'fable' && ceoTeslimde)) { k.poz = 'yemek'; k.durum_metni = gece ? yemekMetni(kid) : `hazır · ${yemekMetni(kid)}`; rooms.yemek.list.push(k); }
      // idle life (molaPlani), the Müdür too (owner decision 2026-11-12): its office desk is its seat when it rests. A nap only
      // when no work of its model is known for KADRO_UYKU_MS (the newest start / finish of that family's jobs)
      // at night (also in hafif) it sleeps in a bed (GECE_UYKUSU), also right after its body came back from a job
      else if (uyku) molacilar.push({ id: kid, kadro: true, uzun: true, a: k, onceki: prevYer.get(kid), ev: null, zorla: 'uyku' });
      else if (tatil && (hafif || k.devral)) tatilKoltuk.push({ a: k, masa: f === 'fable' });
      else if (!hafif && !k.devral) {
        const son = tasks.filter((t) => modelAilesi(isModeli(t)) === f)
          .map((t) => Math.max(t._bitis ?? -Infinity, zamanMs(t.started, tz, ofset) ?? -Infinity))
          .reduce((x, y) => Math.max(x, y), -Infinity);
        molacilar.push({ id: kid, kadro: true, uzun: !(son > ms - KADRO_UYKU_MS), masa: f === 'fable',
          yorgun: calismaSuresi(tasks, f, ms, tz, ofset) > MASAJ_ESIGI_MS, a: k, onceki: prevYer.get(kid), ev: kadroYeri(f) });
      }
    } else k.durum_metni = 'durumu bilinmiyor';
    // the Müdür's desk taken by another worker: the idle Müdür waits at its lounge seat instead
    if (f === 'fable' && k.yer === MUDUR_MASASI && actors.some((a) => a.masa === MUDUR_MASASI && !a._gizli)) {
      k.yer = 'ortak-alan-fable'; k.masa = null;
    }
    kadro.push(k);
  }
  if (hakem && devralCagri.hakem) hakem.devral = devralCagri.hakem;
  // the hakem right after the security reviewer of the same family: the same body walks on to the Uzmanlar odası
  if (hakem && !hakem.devral && !prevIds.has('hakem') && !cagrilar.some((c) => c.id === `denetci:${GUVENLIK}`)) {
    const sec = prevOf(`denetci:${GUVENLIK}`);
    if (sec && sec.aile === hakem.model) hakem.devral = sec.id;
  }

  // the external auditors: one desk each (Codex and the free reviewers of state.modeller). A reviewer at work types at
  // its desk (also while a quota flag is still live: the run is the newer fact; one away on a break walks back first);
  // else its model row decides: kota -> the "Evde" sign at its desk, hata -> red at its desk; hazir / bilinmiyor ->
  // idle life like the kadro (owner decision 2026-11-12): lunch in the canteen, the seeded breaks of molaPlani (not in hafif),
  // otherwise idle at the desk.
  // Who is at work comes from state.denetim (the server's panel marker) when it is there; without it (an older
  // server) a running Codex review is Codex at work and a free reviewer's own row says so.
  const modelRows = Array.isArray(st.modeller) ? st.modeller : [];
  const auditorList = plan.denetciler || denetciListesi(modelRows);
  const working = denetim && Array.isArray(denetim.denetciler) ? new Set(denetim.denetciler) : null;
  const auditors = [];
  auditorList.forEach((ad) => {
    const masa = denetciMasasi(ad);
    if (!plan.dugumler[masa]) return;
    const guvenlik = ad === GUVENLIK;
    const free = ad !== 'codex' && !guvenlik;
    const row = modelRows.find((m) => m && m.model === ad &&
      (guvenlik ? guvenlikSatiriMi(m) : free ? ucretsizDenetciMi(m) : true));
    if ((free || guvenlik) && !row && !(guvenlik && working && working.has(ad))) return; // the server lists them
    const m = row || {};
    const u = UNVAN.codex;
    const fam = guvenlik ? modelAilesi(m.ajan_modeli) || 'sonnet' : '';
    const a = { id: `denetci:${ad}`, tur: 'ajan', denetci: true, ucretsiz: free, unvan: guvenlik ? GUVENLIK_UNVAN : u.unvan,
      rank: u.rank, model: ad, proje: '', yer: masa, masa, poz: 'bekliyor', simge: null,
      // the floor shows the short name only ("Codex", "GLM", "IT güvenlik uzmanı"); the role is in the tooltip and the card
      etiket: guvenlik ? GUVENLIK_KISA : denetciAdi(ad), kisa_etiket: guvenlik ? GUVENLIK_KISA : denetciAdi(ad),
      ipucu: guvenlik ? `${GUVENLIK_KISA} · ${GUVENLIK_UNVAN} (${aileAdi(fam)})` : `${denetciAdi(ad)} · ${u.unvan}${free ? ' · ücretsiz' : ''}`,
      durum_metni: 'hazır', tiklama: null };
    if (guvenlik) { a.aile = fam; if (devralCagri[a.id]) a.devral = devralCagri[a.id]; } // its Claude family's kadro
    // (the security row mirrors its Claude model's state, so only its own `calisan` says it runs)
    const busy = working ? working.has(ad)
      : ad === 'codex' ? !!review : guvenlik ? Number(m.calisan) > 0 : m.durum === 'calisiyor';
    if (guvenlik && !busy) return; // a Claude call: shown only while it runs
    if (busy) {
      a.poz = 'yaziyor';
      const proje = reviewed ? reviewed.project : (review && !working ? review.project : '');
      a.durum_metni = proje ? `inceliyor · ${proje}` : 'inceliyor';
      a.tiklama = reviewClick;
    } else if (m.durum === 'kota') {
      a.poz = 'evde';
      const d = donusMetni(m.donus, ms, tz);
      a.durum_metni = d ? `Evde · ${d}` : 'Evde · kota doldu';
    } else if (m.durum === 'hata') { a.simge = 'kirmizi'; a.durum_metni = 'son çalışma hata verdi'; }
    else {
      if (m.durum !== 'hazir' && m.durum !== 'calisiyor') a.durum_metni = 'durumu bilinmiyor';
      if (m.durum !== 'calisiyor') { // idle (hazir / bilinmiyor): office life like the kadro
        // lunch only on a free canteen chair (an auditor never hides in the canteen's "+N"; else it eats at its desk)
        if (yemekte(a.id)) {
          if (rooms.yemek.list.length < rooms.yemek.spots) {
            a.poz = 'yemek'; a.durum_metni = gece ? yemekMetni(a.id) : `hazır · ${yemekMetni(a.id)}`; rooms.yemek.list.push(a);
          }
        }
        else if (uyku) molacilar.push({ id: a.id, kadro: true, uzun: true, a, onceki: prevYer.get(a.id), ev: null, zorla: 'uyku' });
        else if (!hafif) molacilar.push({ id: a.id, kadro: true, uzun: true, masa: true, a, onceki: prevYer.get(a.id), ev: masa });
        else if (tatil) tatilKoltuk.push({ a, masa: true });
      }
    }
    // a cue (B4): review findings going back — the kod job of a workflow works again right after that workflow's code
    // review finished (DÜZELT): an idle Codex carries the sheet to the kod desk (the walk plus IS_KALIS_MS there)
    if (ad === 'codex' && !busy && a.poz !== 'evde' && a.poz !== 'yemek' && !hafif && !uyku) {
      for (const t of tasks) {
        if (t.step_kind !== 'kod-inceleme' || t.status !== 'bitti' || !t.workflow || t._bitis === null || ms < t._bitis) continue;
        const kod = visible.find((x) => x._task && x._task.workflow === t.workflow && x._task.step_kind === 'kod' &&
          x._task.status === 'calisiyor' && x.masa && x.yer === x.masa);
        const hedef = kod && plan.dugumler[`${kod.masa}-yan`] ? `${kod.masa}-yan` : null;
        if (hedef && ms < t._bitis + sure(masa, hedef) + IS_KALIS_MS) {
          a.yer = hedef; a.poz = 'yuruyor'; a.dosya = true; a.durum_metni = 'bulguları götürüyor'; a.tiklama = { note: kod._task.note };
          const i = molacilar.findIndex((m) => m.a === a);
          if (i >= 0) molacilar.splice(i, 1); // the errand, not a break
          break;
        }
      }
    }
    auditors.push(a);
  });

  // idle life: tea / coffee, the Oyun odası, a short walk — only for the idle actors collected above (real state
  // first: a busy, waiting, Kontrol or permission actor is never among them); the others rest at their own seat
  // the CEO (owner decision 2026-11-12): asleep (dormant, real state) in the Dinlenme odası's first bed — in hafif too; idle
  // with nothing open (no queue, no decision for the owner, no open helper) it takes a break now and then, rarer than staff
  const ceoSt = st.ceo || {};
  const kararVar = (Array.isArray(st.decisions) ? st.decisions : []).some((x) => x && !x.answer_sent);
  // a job the office is running counts as open work too (the owner, 2026-11-14: while a job it handed out runs, the CEO
  // waits for its report in its room — no lunch, no round, no break)
  // (st.tasks is only the newest few; the summary's running count covers every active job — Codex 2026-11-14)
  const isSuruyor = Number(st.summary && st.summary.running) > 0 ||
    (Array.isArray(st.tasks) ? st.tasks : []).some((t) => t &&
      ['baslatiliyor', 'calisiyor', 'karar-bekliyor', 'incelemede', 'kontrolde'].includes(t.status));
  // ceoKendiIsi: the CEO's own open work; a running job only keeps it in its room (an announcement still takes it to
  // the lectern: the owner's own event, ~60 s)
  const ceoKendiIsi = ceoSt.state === 'busy' || ceoSt.state === 'waiting' || acikYardimci(ceoSt.alt_ajanlar) ||
    Number(ceoSt.queue) > 0 || kararVar;
  const ceoAcik = ceoKendiIsi || isSuruyor;
  // its free time (ceoPlani; the same plan in hafif, without the walking breaks and rounds: there the desk); it eats
  // only with nothing open; outside the office hours a dormant CEO sleeps and an idle one stays at its desk
  const ceoBos = (ceoSt.state === 'idle' || ceoSt.state === 'dormant') && !ceoAcik;
  const ceoYemekte = ceoBos && !uyku && !ceoTeslimde && yemekte('ceo');
  const ceoSerbest = ceoBos && !ceoYemekte;
  // handing a new job's file down the company is the CEO's own work: a job already running (isSuruyor) keeps it from
  // lunch, rounds and breaks, never from the hand-over (else a workflow's next step would never be carried)
  const ceoTeslimHazir = (ceoSt.state === 'idle' || ceoSt.state === 'dormant') && !ceoKendiIsi && !ceoYemekte;
  // at night the free CEO sleeps, idle or dormant (GECE_UYKUSU); by day only a dormant one; on a day off's day hours
  // (tatil) it is awake: a leisure break in the common areas (molaPlani), never its desk, no round
  const ceoPlan = ceoSerbest ? (tatil ? { tur: 'mola', mola: '' }
    : ceoPlani(ms, plan, { uyuyabilir: ceoSt.state === 'dormant' || gece, gece, ogle })) : null;
  const ceoYatak = !!ceoPlan && ceoPlan.tur === 'uyku' && !!plan.dugumler['dinlenme-yatak-0'];
  const ceoMola = {};
  if (ceoPlan && ceoPlan.tur === 'mola' && !hafif) {
    molacilar.push({ id: 'ceo', kadro: true, masa: !!tatil, a: ceoMola, zorla: ceoPlan.mola, onceki: prevYer.get('ceo'), ev: 'ceo-masa' });
  } else if (ceoPlan && tatil) tatilKoltuk.push({ a: ceoMola, masa: true });
  const mola = molaPlani(molacilar, ms, plan, typeof sahne.mola === 'string' ? sahne.mola : '',
    { doluYataklar: ceoYatak ? ['dinlenme-yatak-0'] : [], gece: uyku, tatil: !!tatil, ogle });
  for (const m of molacilar) {
    const x = mola.get(m.id);
    if (x) { m.a.yer = x.yer; m.a.poz = x.poz; m.a.durum_metni = tatil ? tatilMetni(x.metin) : x.metin; m.a.mola = true; }
    else if (!m.kadro) {
      m.a.poz = 'cay'; m.a.durum_metni = tatil ? tatilMetni('çay içiyor') : gece ? 'boşta · dinleniyor' : 'boşta · çay molası';
      m.a.mola = true; rooms.cay.list.push(m.a);
    } else if (tatil) tatilKoltuk.push({ a: m.a, masa: !!m.masa });
  }
  // tatil: one whose seat is a desk sits on a tea stool (reading or resting, seeded per slot); a kadro member rests in
  // its own armchair of the Ortak alan. The CEO first in the queue for a stool (it is placed below from ceoMola)
  for (const { a, masa } of tatilKoltuk) {
    const id = a === ceoMola ? 'ceo' : a.id;
    const okur = hash(`${id}:tatil:${molaDilimi(id, ms).dilim}`) % 2 === 0;
    a.durum_metni = tatilMetni(okur && masa ? 'kitap okuyor' : 'dinleniyor');
    if (!masa) continue;
    a.poz = 'bekliyor'; a.mola = true; a.tatil_koltuk = true;
    if (a.masa === MUDUR_MASASI) a.masa = null;
    if (a === ceoMola) rooms.cay.list.unshift(a); else rooms.cay.list.push(a);
  }
  // the canteen's chairs are stable: one who ate in the previous tick keeps its chair for the whole meal; a new eater
  // takes a free chair from its own seeded place (collisions move on to the next free chair), never by list position
  const yemekAlinan = new Set();
  const yemekAyrilan = new Map(); // chair -> the eater who keeps it
  for (const a of prev || []) {
    if (a && a.poz === 'yemek' && a.id !== 'ceo' && yemekYerleri.includes(a.yer) && yemekte(a.id)) yemekAyrilan.set(a.yer, a.id);
  }
  const yemekKoltugu = (id) => {
    const p0 = prevYer.get(id);
    if (p0 && yemekAyrilan.get(p0) === id && !yemekAlinan.has(p0)) { yemekAlinan.add(p0); return p0; }
    return sabitKoltuk(id, yemekYerleri, (c) => !yemekAlinan.has(c) && (!yemekAyrilan.has(c) || yemekAyrilan.get(c) === id), yemekAlinan);
  };
  for (const [key, r] of Object.entries(rooms)) {
    const kalan = [];
    if (key === 'yemek') {
      for (const a of r.list) { const c = yemekKoltugu(a.id); if (c) a.yer = c; else { a._gizli = true; kalan.push(a); } }
    } else {
      // a desk room (Uzmanlar odası): the spot is the actor's desk too (its screen lights up, helpers stand beside it);
      // the one that sat on a spot in the previous tick keeps it
      const spots = Array.from({ length: r.spots }, (_, i) => `${r.prefix}${i}`);
      const alinan = new Set();
      const yeni = [];
      for (const a of r.list) {
        const p0 = prevYer.get(a.id);
        if (p0 && spots.includes(p0) && !alinan.has(p0)) { alinan.add(p0); a.yer = p0; } else yeni.push(a);
      }
      for (const a of yeni) {
        const c = (r.sira ? r.sira(a) : spots).find((x) => !alinan.has(x));
        if (c) { alinan.add(c); a.yer = c; } else { a._gizli = true; kalan.push(a); }
      }
      if (r.masa) for (const a of r.list) if (!a._gizli) a.masa = a.yer;
    }
    if (kalan.length) {
      const extra = kalan.length;
      ozet.push(ozetAktor(`ozet:${key}`, r.ozet, '', extra, `${extra} ajan daha ${r.metin}`, kalan));
    }
  }
  for (const a of visible) {
    if (a._n.yer !== 'tasima') continue;
    const to = escalatedTo.get(notAdi(a._task.note));
    const target = actors.find((x) => x.id === `is:${notAdi(to.note)}`);
    a.hedef_id = `is:${notAdi(to.note)}`;
    a.dosya = true;
    a.yer = target && target.masa && !target._gizli ? `${target.masa}-yan` : null; // the lobby seat is filled below
  }

  // the lobby: queued jobs on the waiting seats (held ones say so)
  lobby.sort((a, b) => (a.project === b.project ? (a.queue_position || 99) - (b.queue_position || 99)
    : plan.projeler.indexOf(a.project) - plan.projeler.indexOf(b.project)));
  const out = [];
  // a queued job keeps its lobby seat from the previous tick; a new one takes a free seat from its seeded place
  const lobiKoltuklari = Array.from({ length: 6 }, (_, i) => `lobi-koltuk-${i}`);
  const lobiAlinan = new Set();
  const gosterilen = lobby.slice(0, 6);
  const lobiYeri = new Map();
  for (const t of gosterilen) {
    const p0 = prevYer.get(`is:${notAdi(t.note)}`);
    if (p0 && lobiKoltuklari.includes(p0) && !lobiAlinan.has(p0)) { lobiAlinan.add(p0); lobiYeri.set(t, p0); }
  }
  for (const t of gosterilen) {
    if (!lobiYeri.has(t)) lobiYeri.set(t, sabitKoltuk(`is:${notAdi(t.note)}`, lobiKoltuklari, (c) => !lobiAlinan.has(c), lobiAlinan));
  }
  lobby.forEach((t, i) => {
    if (i >= 6) return;
    const model = isModeli(t, null, katmanlar);
    const u = unvanOf(model);
    let text = t.queue_position ? `sırada ${t.queue_position}.` : 'sırada';
    if (t.held) text += ' · bekletiliyor';
    if (t.blocked) text += ' · engel var';
    out.push({ id: `is:${notAdi(t.note)}`, tur: 'ajan', unvan: u.unvan, rank: u.rank, model: modelAilesi(model),
      rol_metni: rolMetni(model, t.uzmanlik), uzmanlik: isUzmanligi(t),
      proje: t.project, yer: lobiYeri.get(t), masa: null, poz: 'lobide', simge: null,
      etiket: etiketOf(t.project, model, t.uzmanlik), durum_metni: text, tiklama: { note: t.note } });
  });
  if (lobby.length > 6) out.push(ozetAktor('ozet:lobi', 'lobi-ozet', '', lobby.length - 6, `${lobby.length - 6} iş daha sırada`));
  for (const a of visible) {
    if (a._n.yer === 'tasima' && !a.yer) {
      const seat = out.find((x) => x.id === a.hedef_id);
      a.yer = seat ? seat.yer : 'asansor';
    }
  }

  // helpers (subagents) next to their parent's desk (a team desk or its Uzmanlar odası desk); a parent away from its
  // desk (CEO door) gets one "+N"
  // for its helpers on its own spot; a hidden parent's helpers are counted in its team's "+N"
  const helpers = [];
  const addHelpers = (parentId, list, spot, proje, tiklama) => {
    const rows = [];
    for (const h of list || []) {
      if (!h || !h.id) continue;
      if (!h.bitti) { rows.push({ h, poz: 'yaziyor', simge: null, metin: kisa(h.gorev) || 'yardım ediyor' }); continue; }
      const t = zamanMs(h.son_yazma, tz, ofset);
      const age = t === null ? Infinity : Math.max(0, ms - t);
      // a finished helper shows ✓ beside its parent for a moment, then is gone (helpers never use the lift)
      if (age < 20000) rows.push({ h, poz: 'kutluyor', simge: '✓', metin: '✓ bitti' });
    }
    rows.forEach((r, i) => {
      if (i >= YARDIMCI_EN_COK) return;
      const u = unvanOf(r.h.model, UNVAN.haiku);
      const fam = modelAilesi(r.h.model);
      const a = { id: `${parentId}/alt:${r.h.id}`, tur: 'alt-ajan', unvan: u.unvan, rank: u.rank, model: fam, proje,
        yer: r.cikis ? 'asansor' : `${spot}-${i}`, masa: null, poz: r.poz, simge: r.simge,
        etiket: fam ? `Yardımcı · ${u.unvan} (${aileAdi(fam)})` : `Yardımcı · ${u.unvan}`, durum_metni: r.metin,
        tiklama, ebeveyn: parentId };
      if (r.cikis) a.cikis = true;
      helpers.push(a);
    });
    if (rows.length > YARDIMCI_EN_COK) {
      const extra = rows.length - YARDIMCI_EN_COK;
      helpers.push({ ...ozetAktor(`${parentId}/alt:+`, `${spot}-${YARDIMCI_EN_COK}`, proje, extra,
        `${extra} yardımcı daha`), ebeveyn: parentId });
    }
  };
  for (const a of visible) {
    if (!a._session || a._gizli || a.poz === 'evde') continue;
    if (a.masa && a.yer === a.masa) addHelpers(a.id, a._session.alt_ajanlar, `${a.masa}-yardimci`, a.proje, a.tiklama);
    else if (a.yer && helperCount(a)) {
      helpers.push({ ...ozetAktor(`${a.id}/alt:+`, a.yer, a.proje, helperCount(a), `${helperCount(a)} yardımcı`),
        ebeveyn: a.id });
    }
  }

  // a cue (B4, plan 7; extended by plan "Sonraki iş (9)"): a new job's file goes down the company — a job added a moment
  // ago (its `created`, within TESLIM_PENCERE_MS), the newest one: the free CEO walks it to the Genel Müdür (the spot
  // beside its desk), the Genel Müdür to the manager of the job's department (isDepartmani: Yazılım / QA / Analist), the
  // Yazılım Müdürü on to the project's sorumlu (the visitor spot beside the team's manager desk) and the last one carries
  // it to the job's robot (its lobby seat or beside its desk; it follows the robot from the lobby to its desk). Whoever is
  // not there (the Genel Müdür at work as a fable job, at lunch, at home on quota; a manager outside its office hours) is
  // skipped. Carried tick to tick on the CEO actor (`teslim`: {anahtar, proje, bolum, zincir: [{id, ev, ara}], t: [when
  // each receiver took the file], hedef, bitis}); every walk lasts until arrival, a hand-over waits until the receiver is
  // at its desk, and a job is handed over once (`teslim_verilen`). None in hafif.
  let teslim = null;
  const pc = prevOf('ceo');
  const teslimVerilen = new Set(pc && Array.isArray(pc.teslim_verilen) ? pc.teslim_verilen : []);
  const gmKadro = kadro.find((k) => k.id === 'kadro:fable') || null;
  const gmHazir = !!gmKadro && gmKadro.masa === MUDUR_MASASI && gmKadro.poz !== 'evde' && gmKadro.poz !== 'yemek' &&
    gmKadro.poz !== 'yatiyor' &&
    gmKadro.simge !== 'kirmizi' && !gmKadro.devral && !!plan.dugumler[`${MUDUR_MASASI}-yan`];
  // a manager is on the floor inside its own office hours (not in hafif)
  const mudurBurada = (key) => !hafif && !!plan.dugumler[mudurMasasi(key)] &&
    personelSaati(mudurId(key), ms, sahne) === 'iceride' && !(prevOf(mudurId(key)) || {}).cikis;
  if (!hafif) {
    const yerOf = new Map([...out, ...visible].filter((x) => x && x.yer).map((x) => [x.id, x]));
    const hedefOf = (r) => (!r ? null : r.poz === 'lobide' ? r.yer
      : r.masa && plan.dugumler[`${r.masa}-yan`] ? `${r.masa}-yan` : null);
    const eski = pc && pc.teslim && Array.isArray(pc.teslim.zincir) && Array.isArray(pc.teslim.t) &&
      Number.isFinite(pc.teslim.bitis) && ms < pc.teslim.bitis ? pc.teslim : null;
    if (eski && (ms >= teslimIlk(eski) || ceoTeslimHazir)) { // before the first hand-over the CEO must still be free
      teslim = { ...eski, zincir: eski.zincir.map((z) => ({ ...z })), t: [...eski.t] };
      const yeni = hedefOf(yerOf.get(`is:${teslim.anahtar}`));
      if (yeni && yeni !== teslim.hedef) { // the robot moved (lobby -> desk): the last carrier follows, its walk counts again
        const n = teslim.zincir.length;
        const son = n ? teslim.zincir[n - 1] : null;
        const aldi = n ? teslim.t[n - 1] : ms;
        const ps = son ? prevOf(son.id) : null;
        const from = !son ? (pc && pc.yer) || 'ceo-masa' : ms < aldi ? son.ev : (ps && ps.yer) || teslim.hedef;
        teslim.hedef = yeni;
        teslim.bitis = Math.max(teslim.bitis, Math.max(ms, aldi) + sure(from, yeni) + IS_KALIS_MS);
      }
    } else if (ceoTeslimHazir) {
      let best = null;
      for (const t of tasks) {
        if (onayAdimi(t) || panelIncelemesi(t) || teslimVerilen.has(notAdi(t.note))) continue;
        const c0 = zamanMs(t.created, tz, ofset);
        if (c0 === null || ms < c0 || ms >= c0 + TESLIM_PENCERE_MS || (best && c0 <= best.c0)) continue;
        const hedef = hedefOf(yerOf.get(`is:${notAdi(t.note)}`));
        if (hedef) best = { c0, t, hedef };
      }
      if (best) {
        const p = best.t.project;
        const bolum = isDepartmani(best.t);
        const zincir = [];
        if (gmHazir) zincir.push({ id: gmKadro.id, ev: MUDUR_MASASI, ara: `${MUDUR_MASASI}-yan` });
        if (mudurBurada(bolum) && plan.dugumler[`${mudurMasasi(bolum)}-yan`]) {
          zincir.push({ id: mudurId(bolum), ev: mudurMasasi(bolum), ara: `${mudurMasasi(bolum)}-yan` });
        }
        if (bolum === 'yazilim' && p && plan.dugumler[`ekip-${p}-mudur-ziyaret`]) {
          zincir.push({ id: `sus:proje:${p}`, ev: `ekip-${p}-mudur`, ara: `ekip-${p}-mudur-ziyaret` });
        }
        let bas = ms;
        let nerede = (pc && pc.yer) || 'ceo-masa';
        const t = [];
        for (const z of zincir) {
          const pz = prevOf(z.id);
          const evde = ms + sure((pz && pz.yer) || (z.id.startsWith('sus:proje:') ? 'asansor' : z.ev), z.ev);
          const T = Math.max(bas + sure(nerede, z.ara), evde) + IS_KALIS_MS;
          t.push(T); bas = T; nerede = z.ev;
        }
        teslim = { anahtar: notAdi(best.t.note), proje: p, bolum, zincir, t, hedef: best.hedef,
          bitis: bas + sure(nerede, best.hedef) + IS_KALIS_MS };
        teslimVerilen.add(teslim.anahtar);
      }
    }
  }
  // the Genel Müdür (the fable kadro): its part of the chain first; else, when a workflow's approval card is new (a
  // decision of kind akis-onay not seen in the previous tick; none on the first render), it carries the summary to the
  // CEO's door once (GM_KAPI_YERI: the walk there plus SEKRETER_KALIS_MS) — the Sekreter still brings the decision itself
  if (gmKadro) {
    const pg = prevOf(gmKadro.id);
    const onaylar = (Array.isArray(st.decisions) ? st.decisions : [])
      .filter((x) => x && x.kind === 'akis-onay' && !x.answer_sent).map((x) => String(x.note || ''));
    const rol = teslimRolu(teslim, gmKadro.id, ms);
    let ozetG = pg && pg.ozet_gorevi && Number.isFinite(pg.ozet_gorevi.bitis) && ms < pg.ozet_gorevi.bitis ? pg.ozet_gorevi : null;
    const bilinen = pg && Array.isArray(pg.onay_notlari) ? new Set(pg.onay_notlari) : null;
    if (!ozetG && !rol && bilinen && !hafif && gmHazir && plan.dugumler[GM_KAPI_YERI]) {
      const yeni = onaylar.find((n) => !bilinen.has(n));
      if (yeni) ozetG = { anahtar: yeni, bitis: ms + sure((pg && pg.yer) || MUDUR_MASASI, GM_KAPI_YERI) + SEKRETER_KALIS_MS };
    }
    gmKadro.onay_notlari = onaylar;
    // real state first: at home on quota, at lunch or red-marked it skips its leg (the next receiver still takes the file
    // at its time) and starts no summary trip
    const gmSerbest = gmKadro.poz !== 'evde' && gmKadro.poz !== 'yemek' && gmKadro.simge !== 'kirmizi';
    if (rol && gmSerbest) {
      delete gmKadro.mola;
      // (waiting: at its desk — unless a worker took that desk meanwhile, then where the kadro rule put it)
      gmKadro.yer = rol.bekle ? (gmKadro.masa === MUDUR_MASASI ? MUDUR_MASASI : gmKadro.yer) : rol.yer;
      gmKadro.poz = rol.bekle ? 'bekliyor' : 'yuruyor';
      gmKadro.durum_metni = rol.metin;
      if (rol.dosya) gmKadro.dosya = true;
      if (rol.gorevde) gmKadro.gorevde = true; // taking the file over: real work (its label turns green)
    } else if (ozetG && gmSerbest) {
      delete gmKadro.mola;
      gmKadro.ozet_gorevi = ozetG;
      gmKadro.yer = GM_KAPI_YERI; gmKadro.poz = 'yuruyor'; gmKadro.dosya = true;
      gmKadro.durum_metni = "onay özetini CEO'ya götürüyor";
    }
  }

  // the CEO (an open subagent counts as work: the CEO stays in its room)
  const ceo = st.ceo || {};
  const ceoUnvan = UNVAN.ceo;
  const c = { id: 'ceo', tur: 'ceo', unvan: ceoUnvan.unvan, rank: ceoUnvan.rank, model: '', proje: '', yer: 'ceo-masa',
    masa: 'ceo-masa', poz: 'uyuyor', simge: null, etiket: 'CEO', durum_metni: '', tiklama: { ceo: true } };
  const claudeKota = ['haiku', 'sonnet', 'opus', 'fable'].map((f) => (st.modeller || []).find((m) => m && m.model === f));
  const hesapKota = claudeKota.every((m) => m && m.durum === 'kota'); // every Claude model: the account's limit
  const ceoBusy = ceo.state === 'busy' || (ceo.state !== 'waiting' && acikYardimci(ceo.alt_ajanlar));
  if (ceo.state === 'waiting') { c.poz = 'el-kaldirmis'; c.simge = '!'; c.durum_metni = 'izin sorusunda bekliyor'; }
  else if (ceoBusy && ceo.state === 'busy' && ceo.tur_kapaniyor) { c.poz = 'bekliyor'; c.durum_metni = 'Cevap verdi · tur kapanıyor'; }
  else if (ceoBusy) { c.poz = 'yaziyor'; c.durum_metni = 'çalışıyor'; }
  else if (hesapKota && (ceo.state === 'idle' || ceo.state === 'dormant')) {
    c.poz = 'evde';
    const back = claudeKota.map((m) => zamanMs(m.donus, tz)).filter((x) => x !== null);
    const d = back.length ? donusMetni(Math.max(...back), ms, tz) : '';
    c.durum_metni = d ? `Evde · ${d}` : 'Evde · kota doldu';
  } else if (ceo.state === 'idle' || ceo.state === 'dormant') {
    // real state first: with something open (a queue, a helper, a decision for the owner) it stays at its desk, never at
    // lunch, on a round or on a break. The label tells where it is: "uyuyor" only in bed.
    c.poz = 'bekliyor'; c.durum_metni = 'odasında';
    if (ceoYemekte) { c.yer = 'yemekhane-sandalye-7'; c.poz = 'yemek'; c.durum_metni = yemekMetni('ceo'); c.mola = true; }
    else if (teslim && ceoTeslimHazir && ms < teslimIlk(teslim)) {
      c.yer = teslim.zincir.length ? teslim.zincir[0].ara : teslim.hedef; c.poz = 'yuruyor'; c.durum_metni = 'işi teslim ediyor';
      c.dosya = true;
    }
    else if (ceoYatak) { c.yer = 'dinlenme-yatak-0'; c.poz = 'yatiyor'; c.durum_metni = 'uyuyor'; }
    else if (ceoMola.yer) { c.yer = ceoMola.yer; c.poz = ceoMola.poz; c.durum_metni = ceoMola.durum_metni; c.mola = true; }
    else if (ceoPlan && ceoPlan.tur === 'tur' && !hafif) { c.yer = ceoPlan.durak; c.poz = 'yuruyor'; c.durum_metni = 'ofisi dolaşıyor'; }
  }
  else if (ceo.state === 'absent') c.durum_metni = 'henüz başlamadı';
  else c.durum_metni = 'durum bilinmiyor';
  if (ceo.queue) c.durum_metni += ` · sırada ${ceo.queue}`;
  if (teslim) c.teslim = teslim; // carried: the sorumlu reads it below, the next tick goes on with it
  if (teslimVerilen.size) c.teslim_verilen = [...teslimVerilen].slice(-20);
  if (c.poz !== 'evde') addHelpers('ceo', ceo.alt_ajanlar, 'ceo-yardimci', '', null);

  // an announcement just delivered: working agents stay at their desks with a small "duyuru alındı" mark (not in hafif)
  const pencere = hafif ? null : duyuruPenceresi(st, ms);
  if (pencere) {
    for (const a of visible) {
      if (a._gizli || !a._session || !pencere.alanlar.has(a._session.name) || !a.masa || a.yer !== a.masa) continue;
      a.duyuru_alindi = true;
      a.durum_metni = `${a.durum_metni} · duyuru alındı`;
    }
  }
  const result = [c, ...auditors.filter((a) => !a._gizli), ...visible.filter((a) => !a._gizli), ...kadro.filter((a) => !a._gizli),
    ...kadroCikan, ...(hakem ? [hakem] : []), ...ozet, ...out, ...helpers].map((a) => {
    const o = {};
    for (const [key, v] of Object.entries(a)) if (!key.startsWith('_')) o[key] = v;
    return o;
  });

  // decisions still waiting for the owner (one answered from the page — answer_sent — no longer sends anyone to the door)
  const acikKararlar = (Array.isArray(st.decisions) ? st.decisions : []).filter((x) => x && !x.answer_sent);
  // the staff's lunch: a free canteen chair (yemekKoltugu: stable for the whole meal)
  // (and breakfast right after its own arrival on a work day; ogun with kim 'personel')
  const yemegeGit = (a) => {
    const g = personelGunu(a.id, sahne);
    const o = { kim: 'personel', gel: g ? g.gel : null };
    if (hafif || (gece && !g) || !yemekte(a.id, o)) return false;
    if (ceoTeslimde && /^sus:(mudur|proje):/.test(a.id)) return false; // the hand-over chain of a new job comes first
    const ch = yemekKoltugu(a.id);
    if (!ch) return false;
    a.yer = ch; a.masa = null; a.poz = 'yemek'; a.durum_metni = yemekMetni(a.id, o); a.mola = true;
    return true;
  };
  const dolu = new Set(); // the staff spots taken this tick (mats and the roaming staff's spots)
  // a staff member at home is not drawn; one leaving walks to the lift (EVE_GIDIS_MS) and is gone
  const evdeMi = (a) => {
    const d = personelSaati(a.id, ms, sahne);
    if (d === 'evde') return true;
    if (d === 'cikiyor') { a.yer = 'asansor'; a.masa = null; a.poz = 'yuruyor'; a.durum_metni = 'otele gidiyor'; a.cikis = true; }
    return false;
  };

  // the Çaycı: real duties first — tea to a job that just finished (✓; each once), and at most every EN_UZUN_ARA_MS to
  // the agent working longest (at least EN_UZUN_MIN_MS) — each trip lasts its walk plus CAYCI_KALIS_MS; otherwise its tea
  // loop (CAYCI_TUR_MS: brewing at the counter, then two stops on the common corridors). None in hafif; home outside
  // its office hours.
  if (!hafif) {
    const a = { id: 'sus:cayci', tur: 'sus', gorevli: 'cayci', unvan: '', rank: 0, model: '', proje: '', yer: 'cay-ocagi-tezgah',
      masa: null, poz: 'cay', simge: null, etiket: 'Çaycı', durum_metni: 'çay demliyor', tiklama: null };
    if (!evdeMi(a)) {
      if (!a.cikis) {
        const pc = prevOf(a.id);
        const verilen = new Set(pc && Array.isArray(pc.cay_verilen) ? pc.cay_verilen : []);
        let gorev = pc && pc.cay_gorevi && Number.isFinite(pc.cay_gorevi.bitis) && ms < pc.cay_gorevi.bitis ? pc.cay_gorevi : null;
        let sonUzun = pc && Number.isFinite(pc.son_uzun) ? pc.son_uzun : -Infinity;
        const from = (pc && pc.yer) || 'cay-ocagi-tezgah';
        // the side spots a Sekreter's errand (an answer to a desk) is heading to in the previous tick: not for tea now
        const sekHedef = new Set((prev || []).filter((x) => x && x.gorevli === 'sekreter' && Array.isArray(x.isler))
          .flatMap((x) => x.isler.filter((i) => i && ms < i.bitis).map((i) => i.hedef)));
        if (!gorev) {
          const fresh = visible.filter((x) => x._task && x._task.status === 'bitti' && x.masa && x.poz === 'kutluyor' &&
            plan.dugumler[`${x.masa}-yan`] && !sekHedef.has(`${x.masa}-yan`) && !verilen.has(x.id))
            .sort((x, y) => y._task._bitis - x._task._bitis)[0];
          if (fresh) {
            const yer = `${fresh.masa}-yan`;
            gorev = { yer, bitis: ms + sure(from, yer) + CAYCI_KALIS_MS, metin: 'çay getiriyor', gorevde: true };
            verilen.add(fresh.id);
          } else if (ms - sonUzun >= EN_UZUN_ARA_MS && hash(`cayci:uzun:${Math.floor(ms / 60000)}`) % 4 === 0) {
            const masada = visible.filter((x) => x._task && x.masa && x.yer === x.masa && x.poz === 'yaziyor' && !x._gizli &&
              plan.dugumler[`${x.masa}-yan`] && !sekHedef.has(`${x.masa}-yan`));
            const uzun = enUzunCalisan(masada.map((x) => x._task), tz, ofset, ms, EN_UZUN_MIN_MS);
            const ua = uzun ? masada.find((x) => x._task === uzun) : null;
            if (ua) {
              const yer = `${ua.masa}-yan`;
              gorev = { yer, bitis: ms + sure(from, yer) + CAYCI_KALIS_MS, metin: 'en uzun çalışana çay götürüyor', gorevde: true };
              sonUzun = ms;
            }
          }
        }
        if (gorev) {
          a.yer = gorev.yer; a.poz = 'yuruyor'; a.durum_metni = gorev.metin; a.cay_gorevi = gorev;
          if (gorev.gorevde) a.gorevde = true;
        } else if (!gece) {
          const { dilim, gecen } = molaDilimi(a.id, ms, CAYCI_TUR_MS);
          const duraklar = planListesi(plan, 'cay-duraklari', () => Object.keys(plan.dugumler).filter((k) => /^koridor-[01]-/.test(k)).sort());
          if (duraklar.length && gecen >= 0.6 * CAYCI_TUR_MS) {
            const i = gecen < 0.8 * CAYCI_TUR_MS ? 0 : 1;
            a.yer = duraklar[hash(`cayci:${dilim}:${i}`) % duraklar.length]; a.poz = 'yuruyor'; a.durum_metni = 'çay dağıtıyor';
          }
        }
        a.cay_verilen = [...verilen].slice(-20);
        if (Number.isFinite(sonUzun)) a.son_uzun = sonUzun;
      }
      result.push(a);
    }
  }
  // the duty staff: the Sekreter and the guard are three people each on the rotating shifts (nobetEkibi; plan "Sonraki
  // iş (8)"): exactly one of each team is on shift at any time; at a change the incoming one comes out of the lift and
  // the outgoing one finishes the leg it is on, then walks to the lift (nobetCikisi). In hafif only the person on shift,
  // standing still at the post (no greeting walk, no trip, no break).
  const vNobet = vardiya(ms, sahne);
  // the role's memory: the member on shift in the previous tick (else one drawn there, e.g. a state from before the teams)
  const rolOnceki = (g) => (prev || []).find((x) => x && x.tur === 'sus' && x.gorevli === g && x.nobetci) ||
    (prev || []).find((x) => x && x.tur === 'sus' && x.gorevli === g && !x.cikis) || null;
  const nobetciYap = (a) => { a.nobetci = true; a.vardiya = vNobet.ad; a.vardiya_son = vNobet.son; };
  // the Sekreters work only on work days (the work calendar): on a weekend or a holiday nobody is on shift at
  // reception; the decision cards still work on the page, only nobody walks them to the CEO's door
  const vSekreter = ekipVardiyasi('sekreter', ms, sahne);
  {
    // the Sekreter at reception: with decisions waiting for the owner she holds the paper; for every new decision (a note
    // not seen in the previous tick) she takes it to the CEO's door once (sekreterTasimasi): the walk there, a moment at
    // the door, the walk back — also at night. With nothing to do she sits at reception.
    const notlar = acikKararlar.map((d) => String(d.note || d.title || ''));
    const rol = rolOnceki('sekreter');
    // the CEO's door is free again for the one on shift once an outgoing Sekreter's door leg there has ended (+1 s)
    let kapiBos = 0;
    for (const x of prev || []) {
      if (!x || x.gorevli !== 'sekreter' || !x.tasima || x.cikis) continue;
      const an = tasimaAni(x.tasima, ms);
      const onShift = vSekreter.nobetci !== null && SEKRETER_EKIBI[vSekreter.nobetci].id === x.id;
      if (!onShift && an.kapida) kapiBos = Math.max(kapiBos, an.kapiSonu + 1000);
    }
    const sekreterAktoru = (u, ps, nobetci) => {
      const sek = { id: u.id, tur: 'sus', gorevli: 'sekreter', unvan: '', rank: 0, model: '', proje: '',
        yer: 'lobi-resepsiyon', masa: null, poz: 'bekliyor', simge: null, etiket: u.etiket,
        durum_metni: gece ? 'nöbette' : 'resepsiyonda', tiklama: null };
      if (nobetci) nobetciYap(sek); else sek.devretti = true;
      if (notlar.length) {
        sek.simge = '?'; sek.dosya = true;
        sek.durum_metni = `${gece ? 'nöbette · ' : ''}${sahip('e')} ${notlar.length} soru bekliyor`;
      }
      sek.karar_notlari = notlar;
      // the one on shift takes the new decisions (the role's memory says which are new); the outgoing one only
      // finishes the trip it is on (no new one)
      let bilinen = rol && Array.isArray(rol.karar_notlari) ? rol.karar_notlari : [];
      if (nobetci && rol && rol.id !== u.id && rol.tasima) {
        // the first tick on shift: the trips the outgoing one has not begun are hers (they count as new)
        const kalan = Math.max(0, rol.tasima.adet - tasimaAni(rol.tasima, ms).baslayan);
        if (kalan) bilinen = bilinen.slice(0, Math.max(0, bilinen.length - kalan));
      }
      const onceki = nobetci
        ? (rol ? { ...(ps || { yer: 'asansor' }), karar_notlari: bilinen } : null)
        : { ...ps, karar_notlari: notlar };
      const tas = hafif ? { tasima: null, kapida: false } : sekreterTasimasi(onceki, notlar, ms, {
        ilk: sure((ps && ps.yer) || 'asansor', 'ceo-kapi'), gidis: sure('lobi-resepsiyon', 'ceo-kapi'),
        donus: sure('ceo-kapi', 'lobi-resepsiyon'), bekle: nobetci ? kapiBos - ms : 0 });
      if (tas.tasima) sek.tasima = tas.tasima;
      if (tas.kapida) { sek.yer = 'ceo-kapi'; sek.poz = 'yuruyor'; sek.durum_metni = 'karar götürüyor'; sek.gorevde = true; }
      // cues (B4): an answer picked up — a job that waited at the CEO's door in the previous tick works again: she
      // takes the answer from the CEO's door to its desk; a group report just written (state.son_rapor): she files it at
      // the CEO's door. Each errand: the walks plus IS_KALIS_MS at each end; one at a time, after the decision trips.
      // Only the one on shift takes new errands.
      const isler = (ps && Array.isArray(ps.isler) ? ps.isler : []).filter((x) => x && Number.isFinite(x.bitis) && ms < x.bitis);
      const nerede = (ps && ps.yer) || 'asansor';
      // a desk's side spot the Çaycı holds with a tea delivery now: she reaches it only after the Çaycı has gone
      const cay = result.find((x) => x.id === 'sus:cayci');
      const cayBitis = (yer) => (cay && cay.cay_gorevi && cay.cay_gorevi.yer === yer ? cay.cay_gorevi.bitis : 0);
      if (!hafif && nobetci && rol) {
        for (const a of visible) {
          const pa = prevOf(a.id);
          if (!pa || !/^ceo-kuyruk-/.test(pa.yer || '') || a.is_durumu !== 'calisiyor' || !a.masa) continue;
          const hedef = plan.dugumler[`${a.masa}-yan`] ? `${a.masa}-yan` : null;
          if (!hedef || isler.some((x) => x.anahtar === a.id)) continue;
          const bas = isler.length ? isler[isler.length - 1].bitis : ms;
          const t1 = Math.max(bas + sure(isler.length ? 'lobi-resepsiyon' : nerede, 'ceo-kapi') + IS_KALIS_MS,
            cayBitis(hedef) + 1000);
          isler.push({ anahtar: a.id, ara: 'ceo-kapi', hedef, t1, bitis: t1 + sure('ceo-kapi', hedef) + IS_KALIS_MS,
            metin: 'cevabı götürüyor' });
        }
        const r = st.son_rapor && typeof st.son_rapor === 'object' ? st.son_rapor : null;
        const ry = r ? zamanMs(r.yazildi, tz, ofset) : null;
        if (r && ry !== null && ms >= ry && ms - ry < 60000 && !isler.some((x) => x.anahtar === `rapor:${r.grup}`) &&
          !(Array.isArray(rol.raporlar) && rol.raporlar.includes(String(r.grup)))) {
          const bas = isler.length ? isler[isler.length - 1].bitis : ms;
          isler.push({ anahtar: `rapor:${r.grup}`, ara: null, hedef: 'ceo-kapi',
            t1: bas, bitis: bas + sure(nerede, 'ceo-kapi') + IS_KALIS_MS, metin: 'raporu dosyalıyor' });
        }
      }
      const raporlar = [...new Set([...(rol && Array.isArray(rol.raporlar) ? rol.raporlar : []),
        ...(ps && Array.isArray(ps.raporlar) ? ps.raporlar : []),
        ...isler.filter((x) => x.anahtar.startsWith('rapor:')).map((x) => x.anahtar.slice(6))])].slice(-10);
      if (raporlar.length) sek.raporlar = raporlar;
      if (isler.length) sek.isler = isler;
      const is0 = !tas.kapida && isler.find((x) => ms < x.bitis);
      if (is0) {
        sek.yer = is0.ara && ms < is0.t1 ? is0.ara : is0.hedef; sek.poz = 'yuruyor'; sek.dosya = true;
        sek.durum_metni = is0.metin; sek.gorevde = true;
      }
      // the outgoing one is on duty only while she is on a leg away from reception (the door, an errand); then she leaves
      if (!nobetci) return tas.kapida || is0 ? sek : null;
      const sekGorevli = notlar.length || tas.tasima || is0;
      const sekYemek = ogunu(sek.id, { kim: 'nobet', ekip: 'sekreter' });
      if (!hafif && !sekGorevli && (!gece || sekYemek)) {
        const m = personelMolasi(sek.id, ms, plan, sekYemek);
        if (m && !dolu.has(m.yer)) { sek.yer = m.yer; sek.poz = m.poz; sek.durum_metni = m.metin; if (m.mola) sek.mola = true; dolu.add(m.yer); }
      }
      return sek;
    };
    for (const u of nobetEkibi('sekreter', ms, sahne)) {
      const ps = prevOf(u.id);
      if (u.durum === 'nobette') { result.push(sekreterAktoru(u, ps, true)); continue; }
      if (hafif || !ps) continue;
      const gorevde = !ps.cikis && !ps.otel ? sekreterAktoru(u, ps, false) : null;
      if (gorevde) { result.push(gorevde); continue; }
      const c = nobetCikisi(ps, ms, sure, 'lobi-resepsiyon');
      if (!c) continue;
      const a = { id: u.id, tur: 'sus', gorevli: 'sekreter', unvan: '', rank: 0, model: '', proje: '', yer: 'asansor',
        masa: null, poz: 'yuruyor', simge: null, etiket: u.etiket, durum_metni: '', tiklama: null };
      eveYolla(a, c);
      result.push(a);
    }
  }
  // the office staff of the wing's facilities (Muhasebeci, İdari işler, İK, Revir, Psikolog, Masaj) at their desks:
  // informational, clickable; hafif keeps only the doctor (the rooms stay). Outside their office hours they are home;
  // the doctor too goes home at the end of its hours (no night call).
  const vakalar = result.filter((x) => x.tur !== 'sus' && (x.simge === 'kirmizi' || x.poz === 'basi-onde'))
    .map((x) => ({ id: x.id, yer: x.masa && plan.dugumler[`${x.masa}-yan`] ? `${x.masa}-yan` : null }));
  const uyariVar = sistemUyarisi(st);
  // the Ar-Ge odası: the open job of the arge workspace (the newest one) — its Ar-Ge uzmanı works at its desk meanwhile
  const argeIs = tasks.filter(argeIsi)
    .sort((x, y) => (String(x.started || x.created || '') < String(y.started || y.created || '') ? 1 : -1))[0] || null;
  for (const [key, etiket] of Object.entries(TESIS_PERSONELI)) {
    const masa = `${key}-masa`;
    const argeGorev = key === 'arge' && !!argeIs;
    // the IT team has its own block below (itEkibi); hafif keeps only the doctor here (and the Ar-Ge uzmanı at work)
    if (key === 'sunucu' || !plan.dugumler[masa] || (hafif && key !== 'revir' && !argeGorev)) continue;
    const a = { id: `sus:${key}`, tur: 'sus', gorevli: key, unvan: '', rank: 0, model: '', proje: '', yer: masa, masa,
      poz: 'yaziyor', simge: null, etiket, durum_metni: masaSozu(key, st, ms), tiklama: null };
    const pa = prevOf(a.id);
    let ziyarette = false;
    if (argeGorev) { // real work first: at its desk while the research job is open, also outside its office hours
      const soru = argeIs.status === 'karar-bekliyor';
      a.poz = soru ? 'bekliyor' : 'yaziyor';
      a.durum_metni = soru ? `araştırma · ${sahip('in')} cevabını bekliyor` : `araştırıyor · ${kisa(argeIs.title || 'Ar-Ge işi', 40)}`;
      a.gorevde = true;
      a.arge_is = argeIs.note;
      result.push(a);
      continue;
    }
    if (key === 'psikolog') { // a visit to the desk of a job on its second Kontrol attempt
      const cases = result.filter((x) => x.tur === 'ajan' && x.tiklama && x.tiklama.note && x.masa &&
        Number(((byNote.get(notAdi(x.tiklama.note)) || {}).kontrol_deneme)) >= 2)
        .map((x) => ({ id: x.id, yer: plan.dugumler[`${x.masa}-yan`] ? `${x.masa}-yan` : null }));
      const z = doktorZiyareti(pa, cases, ms, (f, t) => sure(f || masa, t));
      a.vakalar = z.vakalar;
      if (z.ziyaret) a.ziyaret = z.ziyaret;
      if (z.hedef && !hafif) { a.yer = z.hedef; a.masa = null; a.poz = 'bekliyor'; a.durum_metni = 'moral veriyor'; ziyarette = true; a.gorevde = true; }
    }
    if (key === 'masaj') { // beside a table while someone is on it
      const yatan = result.find((x) => x.poz === 'masajda' && /^masaj-yatak-\d$/.test(x.yer || ''));
      if (yatan && plan.dugumler[`${yatan.yer}-yan`]) { a.yer = `${yatan.yer}-yan`; a.masa = null; a.poz = 'bekliyor'; a.durum_metni = 'masaj yapıyor'; ziyarette = true; a.gorevde = true; }
    }
    if (key === 'revir') { // the doctor: duty (a visit) first; the visited agent is never moved, only visited
      a.etiket = 'Ofis doktoru';
      // not drawn in the previous tick (it was home): coming in by the lift in the morning every open case is new to it;
      // at home it visits nobody (no night call, plan "Sonraki iş (8)")
      const pd = pa || (Array.isArray(prev) && prev.length && personelSaati(a.id, ms, sahne) !== 'evde'
        ? { vakalar: [], yer: 'asansor' } : null);
      // past its own hours (or already walking out) it finishes the visit it is on and starts none
      const kapali = personelSaati(a.id, ms, sahne) !== 'iceride' || !!(pa && pa.cikis);
      const z = doktorZiyareti(pd, kapali ? [] : vakalar, ms, (f, t) => sure(f || masa, t));
      a.vakalar = kapali ? vakalar.map((c) => c.id) : z.vakalar;
      if (z.ziyaret) a.ziyaret = z.ziyaret;
      if (z.hedef && !hafif) { a.yer = z.hedef; a.masa = null; a.poz = 'bekliyor'; a.durum_metni = 'hastaya bakıyor'; ziyarette = true; a.gorevde = true; }
    }
    if (!ziyarette && evdeMi(a)) {
      // home; one still drawn in the previous tick and not yet walking out (a visit ran past its leave time) walks to
      // the lift first and is gone only on arrival
      const c = hafif ? null : nobetCikisi(pa, ms, sure, masa);
      if (!c) continue;
      eveYolla(a, c);
      result.push(a);
      continue;
    }
    if (!hafif && !ziyarette && !a.cikis && !yemegeGit(a)) { // off duty: lunch, else wherever its personality takes it
      const m = personelRotasi(a.id, ms, plan, dolu, { ev: masa, onceki: prevYer.get(a.id), gece });
      if (m) { a.yer = m.yer; a.masa = null; a.poz = m.poz; a.durum_metni = m.metin; a.mola = true; }
    }
    result.push(a);
  }
  // the Değerlendirme ekibi (bin/gunsonu.py): at two free desks of the Analist odası while its work runs — real events
  // only (degerlendirmeDurumu), also in hafif and outside the office hours; a desk an actor uses is never taken
  const deg = degerlendirmeDurumu(st, ms);
  if (deg.calisiyor) {
    const tutulan = new Set();
    for (const x of result) { if (x && !x.cikis) { if (x.yer) tutulan.add(x.yer); if (x.masa) tutulan.add(x.masa); } }
    const bos = DEGERLENDIRME_MASALARI.filter((m) => plan.dugumler[m] && !tutulan.has(m));
    const metin = degerlendirmeMetinleri(deg);
    DEGERLENDIRME_EKIBI.forEach((u, i) => {
      const pa = prevOf(u.id);
      const masa = pa && pa.masa && bos.includes(pa.masa) ? pa.masa : bos.find((m) => !result.some((x) => x.masa === m));
      if (!masa) return;
      bos.splice(bos.indexOf(masa), 1);
      result.push({ id: u.id, tur: 'sus', gorevli: 'degerlendirme', unvan: '', rank: 0, model: '', proje: '', yer: masa,
        masa, poz: metin[i][1], simge: null, etiket: u.etiket, durum_metni: metin[i][0], tiklama: null, gorevde: true,
        degerlendirme_is: deg.is ? deg.is.note : '' });
    });
  }
  // the managers (plan "Sonraki iş (9)"): staff NPCs at their office desks inside their office hours (lunch, else their
  // personality's roaming), hidden in hafif. Real events only: their part of the hand-over chain (teslimRolu); the QA
  // Müdürü walks to the QA odası when a review starts (a kod review or an inceleme-tier job, also one the panel runs:
  // within TOPLANTI_PENCERE_MS of its start, once per job, the walk plus TOPLANTI_MS); when a workflow's plan review
  // starts the Yazılım Müdürü meets the Analist Müdürü in its office (the walk plus TOPLANTI_MS, once per job; both inside
  // their hours, never during a hand-over).
  const ACIK_BASLAMIS = new Set(['baslatiliyor', 'calisiyor', 'incelemede', 'kontrolde']);
  const yeniBasladi = (t) => { const b0 = ACIK_BASLAMIS.has(t.status) ? zamanMs(t.started, tz, ofset) : null;
    return b0 !== null && ms >= b0 && ms < b0 + TOPLANTI_PENCERE_MS; };
  const pYaz = prevOf(mudurId('yazilim'));
  const planGorusulen = new Set(pYaz && Array.isArray(pYaz.plan_gorusulen) ? pYaz.plan_gorusulen : []);
  let planToplantisi = pYaz && pYaz.plan_toplantisi && Number.isFinite(pYaz.plan_toplantisi.bitis) &&
    ms < pYaz.plan_toplantisi.bitis ? pYaz.plan_toplantisi : null;
  const ziyaretYeri = `${mudurlukOdasi('analist')}-ziyaret`;
  if (!planToplantisi && mudurBurada('yazilim') && mudurBurada('analist') && plan.dugumler[ziyaretYeri] &&
    !teslimRolu(teslim, mudurId('yazilim'), ms) && !teslimRolu(teslim, mudurId('analist'), ms)) {
    const t = tasks.find((x) => !planGorusulen.has(notAdi(x.note)) && (x.step_kind === 'plan-inceleme') && yeniBasladi(x));
    if (t) {
      planToplantisi = { anahtar: notAdi(t.note),
        bitis: ms + sure((pYaz && pYaz.yer) || mudurMasasi('yazilim'), ziyaretYeri) + TOPLANTI_MS };
      planGorusulen.add(planToplantisi.anahtar);
    }
  }
  const sorunlu = bakilacakIsler(st);
  for (const m of MUDURLUKLER) {
    const masa = mudurMasasi(m.key);
    if (!plan.dugumler[masa] || hafif) continue;
    const a = { id: mudurId(m.key), tur: 'sus', gorevli: 'mudur', alan: m.key, unvan: '', rank: 0, model: '', proje: '',
      yer: masa, masa, poz: 'yaziyor', simge: null, etiket: m.ad, durum_metni: masaSozu('mudur', st, ms, { alan: m.key }),
      tiklama: null };
    const pa = prevOf(a.id);
    if (m.key === 'yazilim' && planGorusulen.size) a.plan_gorusulen = [...planGorusulen].slice(-10);
    // the reviews the QA Müdürü already visited are kept also while it is in a hand-over chain (no second visit)
    const gorulen = new Set(pa && Array.isArray(pa.gorulen) ? pa.gorulen : []);
    if (m.key === 'qa' && gorulen.size) a.gorulen = [...gorulen].slice(-10);
    // the silent / stuck jobs it already looked at (once per job), kept through every other duty
    const bakilan = new Set(pa && Array.isArray(pa.bakilan) ? pa.bakilan : []);
    if (bakilan.size) a.bakilan = [...bakilan].slice(-10);
    const rol = teslimRolu(teslim, a.id, ms);
    if (rol) { // the hand-over chain: at its desk until the file reaches it, then the leg to the next one
      if (rol.bekle) { a.poz = 'bekliyor'; a.durum_metni = rol.metin; if (rol.gorevde) a.gorevde = true; }
      else { a.yer = rol.yer; a.masa = null; a.poz = 'yuruyor'; a.dosya = true; a.durum_metni = rol.metin; a.gorevde = true; }
      result.push(a);
      continue;
    }
    if (evdeMi(a)) {
      const c = nobetCikisi(pa, ms, sure, masa);
      if (!c) continue;
      eveYolla(a, c);
      result.push(a);
      continue;
    }
    let gorevde = false;
    if (!a.cikis && m.key === 'qa' && plan.dugumler[QA_MUDUR_YERI]) {
      let iz = pa && pa.inceleme_ziyareti && Number.isFinite(pa.inceleme_ziyareti.bitis) && ms < pa.inceleme_ziyareti.bitis
        ? pa.inceleme_ziyareti : null;
      if (!iz) {
        const t = tasks.find((x) => !gorulen.has(notAdi(x.note)) && !onayAdimi(x) && isDepartmani(x) === 'qa' && yeniBasladi(x));
        if (t) {
          iz = { anahtar: notAdi(t.note), bitis: ms + sure((pa && pa.yer) || masa, QA_MUDUR_YERI) + TOPLANTI_MS };
          gorulen.add(iz.anahtar);
        }
      }
      if (gorulen.size) a.gorulen = [...gorulen].slice(-10);
      if (iz) {
        a.inceleme_ziyareti = iz;
        a.yer = QA_MUDUR_YERI; a.masa = null; a.poz = 'bekliyor'; a.durum_metni = 'incelemeyi başlatıyor'; a.gorevde = true;
        gorevde = true;
      }
    }
    // step 4 (bin/mudur.py): a manager looking at a technical question stands at the asking worker's desk, and stays
    // TOPLANTI_MS after its answer; real events only (st.mudur_kararlari), never during another duty
    if (!a.cikis && !gorevde) {
      const k = mudurZiyareti(st.mudur_kararlari, m.key, ms, tz, ofset);
      const soran = k && visible.find((x) => x._task && notAdi(x._task.note) === notAdi(k.is) && x.masa &&
        plan.dugumler[`${x.masa}-yan`]);
      if (soran) {
        a.yer = `${soran.masa}-yan`; a.masa = null; a.poz = 'bekliyor'; a.dosya = true; a.gorevde = true;
        a.durum_metni = k.durum === 'bakiyor' ? 'teknik soruya bakıyor' : 'teknik soruyu cevapladı';
        a.tiklama = { note: soran._task.note };
        gorevde = true;
      }
    }
    if (!a.cikis && planToplantisi && (m.key === 'yazilim' || m.key === 'analist')) {
      if (m.key === 'yazilim') {
        a.plan_toplantisi = planToplantisi;
        a.yer = ziyaretYeri; a.masa = null; a.poz = 'bekliyor'; a.dosya = true;
        a.durum_metni = 'planı Analist Müdürüyle görüşüyor';
      } else { a.poz = 'bekliyor'; a.durum_metni = 'plan incelemesini görüşüyor'; }
      a.gorevde = true;
      gorevde = true;
    }
    // owner decision 2026-11-18 ("daha mantıklı"): a silent or stuck job of its department (bakilacakIsler) — the manager
    // walks to that worker's desk and stands by it ("sessiz işe bakıyor · <iş>"), the walk plus TOPLANTI_MS, once per job;
    // a side spot someone already holds (the doctor's visit to a stuck desk comes first) waits for a later tick
    if (!gorevde && !a.cikis && m.key !== 'it') {
      let bz = pa && pa.bakis && Number.isFinite(pa.bakis.bitis) && ms < pa.bakis.bitis ? pa.bakis : null;
      if (!bz && sorunlu.size) {
        const x = visible.find((v) => v._task && v.masa && sorunlu.has(notAdi(v._task.note)) && !bakilan.has(notAdi(v._task.note)) &&
          !onayAdimi(v._task) && isDepartmani(v._task, v._session) === m.key && plan.dugumler[`${v.masa}-yan`] &&
          !result.some((y) => y.yer === `${v.masa}-yan`));
        if (x) {
          const anahtar = notAdi(x._task.note), hedef = `${x.masa}-yan`;
          bz = { anahtar, hedef, note: x._task.note, metin: `${BAKIS_METNI[sorunlu.get(anahtar)]} · ${kisa(x._task.title || anahtar, 30)}`,
            bitis: ms + sure((pa && pa.yer) || masa, hedef) + TOPLANTI_MS };
          bakilan.add(anahtar);
          a.bakilan = [...bakilan].slice(-10);
        }
      }
      if (bz) {
        a.bakis = bz;
        a.yer = bz.hedef; a.masa = null; a.poz = 'bekliyor'; a.durum_metni = bz.metin; a.tiklama = { note: bz.note };
        a.gorevde = true;
        gorevde = true;
      }
    }
    if (!gorevde && !a.cikis && !yemegeGit(a)) { // no duty: lunch, else wherever its personality takes it
      const r = personelRotasi(a.id, ms, plan, dolu, { ev: masa, onceki: prevYer.get(a.id), gece });
      if (r) { a.yer = r.yer; a.masa = null; a.poz = r.poz; a.durum_metni = r.metin; a.mola = true; }
    }
    result.push(a);
  }
  // the Sunucu odası's IT team (itEkibi): exactly one person on shift at any time; the others home or, after their
  // day shift, in the office as a colleague while their own office hours last
  if (plan.dugumler[IT_NOBET_MASASI]) {
    const v = itVardiyasi(ms, sahne);
    const kabin = plan.dugumler[SUNUCU_KABIN_YERI] ? SUNUCU_KABIN_YERI : null;
    const kabin2 = plan.dugumler[SUNUCU_KABIN_YERI_2] ? SUNUCU_KABIN_YERI_2 : null;
    const arkMasa = plan.dugumler[IT_ARKADAS_MASASI] ? IT_ARKADAS_MASASI : IT_NOBET_MASASI;
    const geceVardiyasi = v.vardiya === 0;
    let yardimVar = false;
    for (const u of itEkibi(ms, sahne)) {
      const pa = prevOf(u.id);
      const a = { id: u.id, tur: 'sus', gorevli: 'sunucu', it_kisi: u.kisi, unvan: '', rank: 0, model: '', proje: '',
        yer: IT_NOBET_MASASI, masa: IT_NOBET_MASASI, poz: 'yaziyor', simge: null, etiket: u.etiket, durum_metni: 'masasında',
        tiklama: null };
      if (u.durum === 'nobette') {
        // holds the room: never lunch or breaks (breakfast and dinner in its turn); duty ("uyarı var") at the cabinets,
        // also at night and in hafif
        a.nobetci = true; a.vardiya = v.ad; a.vardiya_son = v.son;
        a.durum_metni = geceVardiyasi ? 'nöbette' : 'masasında · nöbetçi';
        if (uyariVar && kabin) {
          a.yer = kabin; a.masa = null; a.durum_metni = 'nöbette · uyarı var · kabinlerde';
          a.gorevde = true;
        } else if (!hafif && ['kahvalti', 'aksam'].includes(ogunu(a.id, { kim: 'nobet', ekip: 'sunucu' })) &&
          plan.dugumler['yemekhane-personel-1'] && !dolu.has('yemekhane-personel-1')) {
          // breakfast and dinner in its turn (NOBET_SOFRA_SIRASI), only without a warning; still no lunch
          const tur = ogunu(a.id, { kim: 'nobet', ekip: 'sunucu' });
          dolu.add('yemekhane-personel-1');
          a.yer = 'yemekhane-personel-1'; a.masa = null; a.poz = 'yemek'; a.durum_metni = `nöbette · ${OGUN_METNI[tur]}`; a.mola = true;
        } else if (!hafif && kabin) {
          // a seeded round: in about one 10-minute slot of three it checks the cabinets for 90 s
          const tur = molaDilimi(`${a.id}:tur`, ms, SUNUCU_TUR_MS);
          if (hash(`${a.id}:tur:${tur.dilim}`) % 3 === 0 && tur.gecen < SUNUCU_TUR_KALIS_MS) {
            a.yer = kabin; a.masa = null; a.durum_metni = geceVardiyasi ? 'nöbette · kabinleri kontrol ediyor' : 'kabinleri kontrol ediyor';
          }
        }
        result.push(a);
        continue;
      }
      if (hafif) continue; // hafif: only the person on shift
      if (u.durum === 'iceride') {
        a.yer = arkMasa; a.masa = arkMasa; a.poz = 'yaziyor';
        if (uyariVar && kabin2 && !gece && !yardimVar) {
          // one colleague helps at the second cabinet spot while the warning lasts (office hours only)
          a.yer = kabin2; a.masa = null; a.durum_metni = 'uyarı var · kabinlerde yardım ediyor'; a.gorevde = true;
          yardimVar = true;
        } else if (!yemegeGit(a)) {
          const m = personelRotasi(a.id, ms, plan, dolu, { ev: arkMasa, onceki: prevYer.get(a.id), gece });
          if (m) { a.yer = m.yer; a.masa = null; a.poz = m.poz; a.durum_metni = m.metin; a.mola = true; }
        }
        result.push(a);
        continue;
      }
      // home: someone drawn in the previous tick walks to the lift first — the walk lasts until it arrives there
      const c = hafif ? null : nobetCikisi(pa, ms, sure, IT_NOBET_MASASI);
      if (!c) continue;
      eveYolla(a, c);
      result.push(a);
    }
  }
  // the kitchen teams (2026-11-14; hidden in hafif like the Yemekhane sorumlusu before): one yemekhane görevlisi and one
  // aşçı on duty at any time on the shared rotation (nobetEkibi); the server serves every meal at the counter
  // (yemekhaneSorumlusu), the cook works at the stove and the fridge (asciPlani). Each eats breakfast and dinner in its
  // turn (NOBET_SOFRA_SIRASI) on a staff chair. The outgoing one walks to the Otel at a change (nobetCikisi).
  if (!hafif && plan.dugumler[YEMEKHANE_SERVIS]) {
    for (const [ekip, sandalye] of [['yemekhane', 'yemekhane-personel-0'], ['asci', 'yemekhane-personel-1']]) {
      for (const u of nobetEkibi(ekip, ms, sahne)) {
        const a = { id: u.id, tur: 'sus', gorevli: ekip, unvan: '', rank: 0, model: '', proje: '', yer: YEMEKHANE_SERVIS,
          masa: null, poz: 'bekliyor', simge: null, etiket: u.etiket, durum_metni: '', tiklama: null };
        if (u.durum !== 'nobette') {
          const pa = prevOf(u.id);
          const c = nobetCikisi(pa, ms, sure, (pa && pa.yer) || YEMEKHANE_SERVIS);
          if (!c) continue;
          eveYolla(a, c);
          result.push(a);
          continue;
        }
        nobetciYap(a);
        const tur = ogunu(u.id, { kim: 'nobet', ekip });
        if ((tur === 'kahvalti' || tur === 'aksam') && plan.dugumler[sandalye] && !dolu.has(sandalye)) {
          dolu.add(sandalye);
          a.yer = sandalye; a.poz = 'yemek'; a.durum_metni = OGUN_METNI[tur]; a.mola = true;
          result.push(a);
          continue;
        }
        const y = ekip === 'asci' ? asciPlani(ms, plan, sahne, { id: u.id })
          : yemekhaneSorumlusu(ms, plan, sahne, dolu, { id: u.id, onceki: prevYer.get(u.id), gece });
        a.yer = y.yer; a.poz = y.poz; a.durum_metni = y.metin;
        if (y.gorevde) a.gorevde = true;
        if (y.mola) a.mola = true;
        result.push(a);
      }
    }
  }
  for (const u of SOSYAL_EKIBI) {
    const masa = sosyalMasasi(u.id);
    if (!plan.dugumler[masa] || hafif) continue; // hafif: the room only
    const a = { id: `sus:sosyal:${u.id}`, tur: 'sus', gorevli: 'sosyal', rol: u.id, unvan: '', rank: 0, model: '', proje: '',
      yer: masa, masa, poz: 'bekliyor', simge: null, etiket: u.ad, durum_metni: 'atanmış iş yok', tiklama: null };
    if (evdeMi(a)) continue;
    if (!a.cikis && !yemegeGit(a)) { // no real work yet: lunch, else its personality decides (personelRotasi)
      const m = personelRotasi(a.id, ms, plan, dolu, { ev: masa, onceki: prevYer.get(a.id), gece });
      if (m) { a.yer = m.yer; a.poz = m.poz; a.durum_metni = m.metin; a.mola = true; }
    }
    result.push(a);
  }
  for (const p of plan.projeler) {
    const mudur = `ekip-${p}-mudur`;
    if (!plan.dugumler[mudur] || hafif) continue;
    const dolu2 = result.some((x) => x.masa === mudur && x.tur !== 'sus');
    const r = { id: `sus:proje:${p}`, tur: 'sus', gorevli: 'proje', unvan: '', rank: 0, model: '', proje: p,
      yer: dolu2 ? `${mudur}-yan` : mudur, masa: dolu2 ? null : mudur, poz: dolu2 ? 'bekliyor' : 'yaziyor', simge: null,
      etiket: `${aileAdi(p)} sorumlusu`, durum_metni: dolu2 ? 'ekibin yanında' : masaSozu('proje', st, ms, { proje: p }),
      tiklama: null };
    // duty: while a job of its project is open it stays at its bay (also outside its office hours); else its
    // personality decides, and outside its hours it is home
    const acikIs = tasks.some((t) => t.project === p && !FINAL.has(t.status) && t.status !== 'sirada');
    // cues of real events (plan 7): its part of the hand-over chain of a new job of its project (teslimRolu: at its desk
    // to take the file, then the last leg to the job's robot) and, when a planning job of its project starts, a short
    // meeting at the planning worker's desk (the Yazılım Müdürü's planning desk). Carried on its own actor.
    const t0 = teslimRolu(teslim, r.id, ms);
    const op = prevOf(r.id);
    const gorusulen = new Set(op && Array.isArray(op.gorusulen) ? op.gorusulen : []);
    let gorusme = !t0 && op && op.gorusme && ms < op.gorusme.bitis ? { ...op.gorusme } : null;
    if (!t0 && !gorusme) {
      for (const t of tasks) {
        if (t.project !== p || gorusulen.has(notAdi(t.note)) || !['baslatiliyor', 'calisiyor'].includes(t.status)) continue;
        if (t.tier !== 'planlama' && t.step_kind !== 'plan') continue;
        const b0 = zamanMs(t.started, tz, ofset);
        if (b0 === null || ms < b0 || ms >= b0 + TOPLANTI_PENCERE_MS) continue;
        const w = result.find((x) => x.id === `is:${notAdi(t.note)}` && x.masa && x.yer === x.masa);
        const hedef = w && plan.dugumler[`${w.masa}-yan`] ? `${w.masa}-yan` : null;
        if (!hedef) continue;
        gorusme = { anahtar: notAdi(t.note), hedef, mudur: w.model === 'fable',
          bitis: ms + sure((op && op.yer) || r.yer, hedef) + TOPLANTI_MS };
        gorusulen.add(gorusme.anahtar);
        break;
      }
    }
    if (gorusulen.size) r.gorusulen = [...gorusulen].slice(-10);
    // owner decision 2026-11-18 ("daha mantıklı"): a job of its project just finished (bitti within KUTLAMA_MS) — it
    // stays at (or comes back to) its bay for the walk plus KUTLAMA_MS ("ekibini kutluyor · <iş>"), once per job, also
    // when nothing else of the project is open: it no longer walks off the very moment the last job is done
    const kutlanan = new Set(op && Array.isArray(op.kutlanan) ? op.kutlanan : []);
    let kutlama = !t0 && !gorusme && op && op.kutlama && ms < op.kutlama.bitis ? op.kutlama : null;
    if (!t0 && !gorusme && !kutlama && op && !op.cikis && !op.otel) { // only one already on the floor (never out of the blue)
      const t = tasks.find((x) => x.project === p && x.status === 'bitti' && x._bitis !== null && ms >= x._bitis &&
        ms - x._bitis < KUTLAMA_MS && !kutlanan.has(notAdi(x.note)));
      if (t) {
        kutlama = { anahtar: notAdi(t.note), metin: `ekibini kutluyor · ${kisa(t.title || notAdi(t.note), 30)}`,
          bitis: ms + sure((op && op.yer) || r.yer, r.yer) + KUTLAMA_MS };
        kutlanan.add(kutlama.anahtar);
      }
    }
    if (kutlanan.size) r.kutlanan = [...kutlanan].slice(-10);
    if (t0) {
      if (t0.bekle) { r.durum_metni = t0.metin; if (t0.gorevde) r.gorevde = true; }
      else { r.yer = t0.yer; r.masa = null; r.poz = 'yuruyor'; r.dosya = true; r.durum_metni = t0.metin; r.gorevde = true; }
    } else if (gorusme) {
      r.gorusme = gorusme;
      r.yer = gorusme.hedef; r.masa = null; r.poz = 'yuruyor'; r.gorevde = true;
      r.durum_metni = gorusme.mudur ? 'Genel Müdürle planı görüşüyor' : 'planı görüşüyor';
    } else if (kutlama) {
      r.kutlama = kutlama;
      r.poz = 'kutluyor'; r.durum_metni = kutlama.metin; r.gorevde = true;
    } else if (!acikIs) {
      if (evdeMi(r)) continue;
      if (!r.cikis && !yemegeGit(r)) {
        const m = personelRotasi(r.id, ms, plan, dolu, { ev: mudur, onceki: prevYer.get(r.id), gece });
        if (m) { r.yer = m.yer; r.masa = null; r.poz = m.poz; r.durum_metni = m.metin; r.mola = true; }
      }
    }
    result.push(r);
  }
  { // the guard team last: the arrivals greeted include the staff coming in for their office hours
    // the guard on shift beside the lift (one of three on the rotating shifts, nobetEkibi). When someone new comes out of
    // the lift — not a shift colleague arriving for its own shift — he walks to the greeting spot and stays
    // GUVENLIK_KALIS_MS there; his breaks stay in the lobby (personelMolasi) and none while a queued job waits in the
    // lobby or within a minute of a greeting. The outgoing one finishes a greeting, then walks to the lift.
    const gelenler = asansordenGelenler(result, prev).filter((x) => !(x.tur === 'sus' && NOBET_EKIPLERI[x.gorevli]));
    const uyeler = nobetEkibi('guvenlik', ms, sahne);
    const yeni = (u) => ({ id: u.id, tur: 'sus', gorevli: 'guvenlik', unvan: '', rank: 0, model: '', proje: '',
      yer: 'lobi-nobet', masa: null, poz: 'bekliyor', simge: null, etiket: u.etiket, durum_metni: gece ? 'nöbette' : 'girişte',
      tiklama: null });
    for (const u of uyeler) { // the outgoing first: a greeting it began holds the greeting spot until it ends
      if (u.durum === 'nobette' || hafif) continue;
      const og = prevOf(u.id);
      if (!og) continue;
      const guard = yeni(u);
      if (!og.cikis && Number.isFinite(og.karsilama_bitis) && ms < og.karsilama_bitis && og.yer === 'lobi-karsilama') {
        guard.yer = 'lobi-karsilama'; guard.durum_metni = 'karşılıyor'; guard.gorevde = true; guard.devretti = true;
        guard.karsilama_bitis = og.karsilama_bitis;
        dolu.add('lobi-karsilama');
        result.push(guard);
        continue;
      }
      const c = nobetCikisi(og, ms, sure, 'lobi-nobet');
      if (!c) continue;
      eveYolla(guard, c);
      result.push(guard);
    }
    const u = uyeler.find((x) => x.durum === 'nobette');
    const og = prevOf(u.id);
    let karsilama = og && Number.isFinite(og.karsilama_bitis) ? og.karsilama_bitis : 0;
    const guard = yeni(u);
    nobetciYap(guard);
    if (!hafif && gelenler.length && ms >= karsilama && !dolu.has('lobi-karsilama')) {
      karsilama = ms + sure((og && og.yer) || 'asansor', 'lobi-karsilama') + GUVENLIK_KALIS_MS;
    }
    if (karsilama) guard.karsilama_bitis = karsilama;
    if (!hafif && ms < karsilama) {
      if (plan.dugumler['lobi-karsilama']) { guard.yer = 'lobi-karsilama'; guard.durum_metni = 'karşılıyor'; guard.gorevde = true; }
    } else if (!hafif && !lobby.length && ms >= karsilama + 60000) {
      const m = personelMolasi(guard.id, ms, plan, ogunu(guard.id, { kim: 'nobet', ekip: 'guvenlik' }));
      if (m && (m.yer === 'lobi-nobet' || !dolu.has(m.yer))) {
        guard.yer = m.yer; guard.poz = m.poz; guard.durum_metni = m.metin; if (m.mola) guard.mola = true; dolu.add(m.yer);
      }
    }
    result.push(guard);
  }
  if (!hafif) oteleYerlestir(result, prev, plan, ms, (f, t) => sure(f, t), tz);
  if (pencere) salonaTopla(result, plan, ceoKendiIsi || !(ceoSt.state === 'idle' || ceoSt.state === 'dormant'));
  return result;
}

// The Otel (owner decision 2026-11-14): everyone of otelKadrosu who is not at work now stays at the hotel instead of vanishing
// "home". One walking out (cikis: its leave after its hours, a shift handed over) walks to its own hotel room instead of
// the lift ("otele gidiyor"); one not drawn by the rest of the engine (outside its hours, a day off, off shift) is drawn
// at its room — "otele gidiyor" until its walk there is done (otel_varis, carried tick to tick), then "otelde" /
// "otelde · uyuyor" (poz 'otelde': the scene hides it inside the closed building). In the morning the engine draws it
// at its desk again and the same body walks back from the hotel (the guard greets it: asansordenGelenler). Never in
// hafif (its people stand still at their posts there). Rooms: otelKadrosu order, so each guest's room is its own.
export function oteleYerlestir(result, prev, plan, ms, sure, tz) {
  if (!plan || !plan.otel) return result;
  const prevOf = new Map((Array.isArray(prev) ? prev : []).filter((a) => a && a.id).map((a) => [a.id, a]));
  const byId = new Map(result.map((a) => [a.id, a]));
  otelKadrosu(plan.projeler).forEach((k, i) => {
    const oda = `${OTEL_ON_EK}${i}`;
    if (!plan.dugumler[oda]) return; // more guests than rooms: the rest are simply not drawn (as before)
    const pa = prevOf.get(k.id) || null;
    const a = byId.get(k.id);
    const varis = (from) => (pa && Number.isFinite(pa.otel_varis) && pa.otel_varis > ms ? pa.otel_varis
      : ms + sure(from || oda, oda));
    if (a) {
      if (a.cikis) { // walking out: to its room, not to the lift
        a.otel_varis = pa && pa.cikis && Number.isFinite(pa.otel_varis) ? pa.otel_varis : ms + sure((pa && pa.yer) || a.masa || a.yer, oda);
        a.yer = oda; a.masa = null; a.poz = 'yuruyor';
        const metin = String(a.durum_metni || '').replace('eve gidiyor', 'otele gidiyor') || 'otele gidiyor';
        a.durum_metni = metin; a.cikis_metni = metin;
      }
      return;
    }
    const h = { id: k.id, tur: 'sus', unvan: '', rank: 0, model: '', proje: '', ...k, yer: oda, masa: null, poz: 'otelde',
      simge: null, durum_metni: otelMetni(ms, tz), tiklama: null, otel: true };
    // just out of the office (in the previous tick at work or walking out): its walk to the room goes on
    const bitis = pa ? (pa.otel ? pa.otel_varis : varis(pa.yer)) : null;
    if (Number.isFinite(bitis) && ms < bitis) {
      h.poz = 'yuruyor'; h.durum_metni = 'otele gidiyor'; h.otel_varis = bitis;
    }
    result.push(h);
  });
  return result;
}

// The gathering in the Konferans salonu (niyetler, during an announcement's window, never in hafif): the free CEO at the
// lectern; then, on the chairs in order, the idle kadro (not at home, no red mark), the idle auditors (not reviewing),
// the off-duty staff (no duty, no symbol, nothing carried). Who does not fit stays where it is; nobody else moves.
export function salonaTopla(actors, plan, ceoMesgul = false) {
  const nodes = plan && plan.dugumler;
  if (!nodes || !nodes[SALON_KURSU]) return actors;
  const koltuklar = Object.keys(nodes).filter((id) => /^konferans-sandalye-\d+$/.test(id))
    .sort((a, b) => Number(a.slice(19)) - Number(b.slice(19)));
  const ceo = actors.find((a) => a && a.id === 'ceo');
  if (ceo && !ceoMesgul && ceo.poz !== 'evde') {
    ceo.yer = SALON_KURSU; ceo.masa = null; ceo.poz = 'bekliyor'; ceo.simge = null; ceo.durum_metni = 'duyuruyu okuyor';
    ceo.salonda = true;
  }
  const dinler = (a) => (a.kadro ? a.poz !== 'evde' && a.simge !== 'kirmizi' && !a.dosya
    : a.denetci ? a.poz !== 'yaziyor' && a.poz !== 'evde' && a.simge !== 'kirmizi'
      : a.tur === 'sus' ? !a.gorevde && !a.simge && !a.tasima && !a.dosya && !a.otel : false);
  const sira = [...actors.filter((a) => a && a.kadro), ...actors.filter((a) => a && a.denetci),
    ...actors.filter((a) => a && a.tur === 'sus')].filter(dinler);
  sira.slice(0, koltuklar.length).forEach((a, i) => {
    a.yer = koltuklar[i];
    if (a.tur === 'sus') a.masa = null;
    a.poz = 'bekliyor';
    a.durum_metni = 'duyuruyu dinliyor';
    a.salonda = true;
  });
  return actors;
}
