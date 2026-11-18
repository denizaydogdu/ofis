// Ofis page: live state over SSE, CEO chat drawer, decision cards, feed and the 3D office.
// All dynamic text goes through textContent — never innerHTML with data.
import { Office } from './scene.js';
import { createDemo } from './demo.js';
import { tekrarla } from './sayfa-anahtari.js';
import { dekorEkibi, denetciListesi, niyetler, ofisPlani, projeRengi, salonEkrani, sahip, sahipAyarla } from './ofis-davranis.js';
import { CALISANLAR_BASLIK, CALISANLAR_BOS, KART_LISTE_SINIRI, calisanGruplari, calisanHucreleri, calisanIpucu, calisanlarTablosu, donusTusu, karakterKarti, kartDuzeni, kaydirmaTusu, mesaiDisiSatiri, modelOzeti, modelSatirlari, orgSemasi, zoomTusu } from './ofis-sahne.js';
import {
  answerResult,
  budgetText, escalationText, postofficeWarnings, queueText,
  bildirimKarti, notKlasoru, obsidianHref, obsidianUri, wikiParcalari,
  stepText, verdictText, zamanlanmisSatirlari, olayRozeti,
  QUALITY_HEAD, boardColumns, budgetBar, minutesText, qualityCells, ratioText, reportBlocks, reportCostText, reportSummaryText,
  usdText, harcamaText, tokenMetni, MAPPING_HEAD, mappingCells, modelCardText, pilotText, kararIsaretleri,
  danismanMetni, danismanPilotuSatirlari,
  kaliteKutulari, reportVerifiedText, kararBildirimi, sekmeBasligi, kararArtti,
  seniBekleyenMetni, secenekDugmeleri, cevapBekleyenRozetleri,
  calisanMetni, canliPill, onayBiriktiMetni, onayBekletmeMetni, kotaDevamMetni, kartBolumleri, sinavMaddeleri, SINAV_BASLIGI, tarihMetni,
  mudurKarti, toastOlaylari, toastYigini, TOAST_SURE_MS,
  ceoToastlari, sohbetGorulmedi, okunmamisSayi, okunmamisMetni, sekmeSayisi,
  raporDugumu,
} from './ofis-text.js';
import {
  HAZIR_SORULAR, adimMetni, baglamCikar, baglamEkle, baglamEtiketi, bildirimEylemleri, bugunkuHarcama, ceoSimdiMetni,
  duyuruGovdesi, duyuruSonucu, mesajMetni, metinSiniri, siradaGostergesi, siraMetni, suAnGruplari,
  CEO_KAPANIYOR, turAltMetni, turAltlari,
} from './komuta.js';
import { yolCizgisi, yollariYenile } from './is-akisi.js';
import { kullanimGorunumu, limitPill } from './limitler.js';
import {
  GUVEN_IPUCU, SORUMLU, acikIsMetni, eklemeGovdesi, formDegerleri, guncellemeGovdesi, guvenRozeti, istemciHatalari,
  kirli, genelGovdesi, ofisAdiKirli, silmeSorusu, sonucMetni, sunucuHatalari, bosForm, FORM_ALANLARI,
} from './ayarlar.js';

const params = new URLSearchParams(location.search);
const DEMO = params.get('demo') === '1';
const LIGHT = params.get('hafif') === '1';
let pageNonce = document.querySelector('meta[name="ofis-token"]')?.getAttribute('content') || '';
const CEO = '__ceo__';

const $ = (id) => document.getElementById(id);
function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// --- Obsidian links: every [[note]] the page shows opens that note in the Obsidian app (owner decision 2026-11-13) ---
// GET /api/not-yolu (bin/notyolu.py) resolves a bare name to its path under OFIS/ (the hinted folder first, else the
// newest); the href is only ever obsidianHref(obsidianUri(...)) — the obsidian:// scheme, never javascript: — set with
// setAttribute; the link text is textContent. A note that is not found is retried after 30 s (it may be written later).
const notYollari = new Map();  // `${name}|${folder hint}` -> Promise<href | ''>
function notHref(ad, tercih = '') {
  const key = `${ad}|${tercih}`;
  if (!notYollari.has(key)) {
    const q = `/api/not-yolu?ad=${encodeURIComponent(ad)}${tercih ? `&tercih=${encodeURIComponent(tercih)}` : ''}`;
    const p = getJson(q).then((res) => (res && res.status === 200 && res.data
      ? obsidianHref(obsidianUri(res.data.kasa, res.data.yol)) : ''));
    p.then((href) => { if (!href) setTimeout(() => notYollari.delete(key), 30000); });
    notYollari.set(key, p);
  }
  return notYollari.get(key);
}
function notLinki(ad, gorunen, tercih = '', cls = 'obs-link') {
  const a = h('a', cls, gorunen || ad);
  const hint = tercih || notKlasoru(ad, '');
  a.title = 'Obsidian\'da aç';
  notHref(ad, hint).then((href) => {
    if (href) a.setAttribute('href', href);
    else { a.classList.add('is-missing'); a.title = 'Not Obsidian\'da bulunamadı'; }
  });
  a.addEventListener('click', (e) => {
    e.stopPropagation();  // never also opens the card or row the link sits in
    if (a.getAttribute('href')) return;
    e.preventDefault();
    notHref(ad, hint).then((href) => {
      if (href) { a.setAttribute('href', href); a.click(); } else toast('Bu not Obsidian\'da bulunamadı.');
    });
  });
  return a;
}
// text with its [[links]] as Obsidian links (plain text nodes otherwise)
function linkliEkle(parent, text, tercih = '') {
  for (const part of wikiParcalari(text)) {
    if (part.not) parent.appendChild(notLinki(part.not, part.gorunen, tercih));
    else if (part.metin) parent.appendChild(document.createTextNode(part.metin));
  }
  return parent;
}
const linkli = (tag, cls, text, tercih = '') => linkliEkle(h(tag, cls), text == null ? '' : String(text), tercih);

// --- formatting ---
const pad = (n) => String(n).padStart(2, '0');
function fmtUsage(n) {
  n = Number(n) || 0;
  if (n < 1000) return String(n);
  if (n < 1e6) return (n / 1000).toFixed(n < 10000 ? 1 : 0).replace('.', ',') + 'k';
  return (n / 1e6).toFixed(1).replace('.', ',') + 'M';
}
function parseTime(v) {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
const hhmm = (d) => (d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : '');
function rel(d) {
  if (!d) return '';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return 'şimdi';
  if (s < 3600) return `${Math.floor(s / 60)} dk`;
  if (s < 86400 && d.getDate() === new Date().getDate()) return `${Math.floor(s / 3600)} sa`;
  return hhmm(d);
}
const VERBS = {
  Edit: 'yazıyor', Write: 'yazıyor', MultiEdit: 'yazıyor', NotebookEdit: 'yazıyor', Read: 'okuyor',
  Bash: 'komut çalıştırıyor', Grep: 'arıyor', Glob: 'arıyor', SendMessage: 'mesaj gönderiyor', WebFetch: 'web okuyor',
  WebSearch: 'web arıyor', Agent: 'yardımcı çalıştırıyor', Skill: 'beceri kullanıyor',
};
function toolText(tool, fallback) {
  if (!tool) return fallback;
  const verb = VERBS[tool.name] || `${tool.name} kullanıyor`;
  return tool.target ? `${verb}: ${tool.target}` : verb;
}
const STATUS_TR = {
  calisiyor: 'çalışıyor', bekliyor: 'cevap bekliyor', uyuyor: 'uyuyor', bitti: 'bitti', tikandi: 'takıldı',
  basarisiz: 'başarısız', baslatiliyor: 'başlatılıyor', busy: 'çalışıyor', idle: 'hazır', dormant: 'uyuyor',
  absent: 'başlamadı', unknown: 'bilinmiyor', waiting: 'izin bekliyor',
  sirada: 'sırada', 'karar-bekliyor': 'karar bekliyor', incelemede: 'incelemede', iptal: 'iptal edildi',
  kontrolde: 'kontrolde',
};

// --- app state ---
let state = null;
let chat = [];
let online = false;
let selected = null;
const sentLocal = new Set();  // decision notes answered from this page
let chatRozetKey = '';  // the waiting CEO questions the chat's "cevap bekliyor" badges were drawn for (renderAsks)
let baseTitle = document.title;  // the tab title without the decision bell's "(N) " prefix: the office's name (renderOfisAdi)
let kararOnceki = null;  // the bell's last count (null before the first state: no pulse on load)
const optimistic = [];        // {text, queued} until it shows up in the transcript
const seenChat = new Set();
let chatSeeded = false;
let ceoOkunmamis = 0;  // CEO lines that arrived while the chat was not seen (badge on "CEO ile sohbet", tab title)
const feed = [];
function dotColor(name) {
  if (name === CEO) return '#F2784B';
  return projeRengi(name, state ? state.projects : [], '#E5DCCF');  // the same colour as the project's room
}

// --- 3D office ---
let office = null;
let schedKey = null; // the Zamanlanmış tab's last content (renderSchedules)
let yanBos = null; // the right panel collapsed (yanPanel), null before the first render
try {
  office = new Office($('scene'), $('labels'), { light: LIGHT, onSelect: (name) => selectRoom(name),
    onActor: (a, at) => openActor(a, at) });
} catch (e) {
  console.error('3D scene unavailable', e);
  $('scene').appendChild(h('p', 'empty', '3D görünüm bu tarayıcıda açılamadı; diğer paneller çalışmaya devam ediyor.'));
}

// The view controls (+ / − / ↺ / ↻ / ⟲) and the keys + / − / Q / E / 0 (not while typing, not with Ctrl/Meta/Alt, not
// while a panel, the chat or a dialog covers the scene). Zoom and turn count as moving the camera (no re-fit on resize)
// until "Tümünü göster", which also turns the view back to its default angle.
function zoomEt(ne) {
  if (!office) return;
  if (ne === 'yakin') office.yakinlastir(1);
  else if (ne === 'uzak') office.yakinlastir(-1);
  else if (ne === 'sola') office.dondur(-1);
  else if (ne === 'saga') office.dondur(1);
  else if (ne === 'tumu') office.tumunuGoster();
}
if (office) {
  $('zoom-yakin').addEventListener('click', () => zoomEt('yakin'));
  $('zoom-uzak').addEventListener('click', () => zoomEt('uzak'));
  $('zoom-sola').addEventListener('click', () => zoomEt('sola'));
  $('zoom-saga').addEventListener('click', () => zoomEt('saga'));
  $('zoom-tumu').addEventListener('click', () => zoomEt('tumu'));
  // the scene's keys (zoom + / − / 0, pan with the arrows / WASD) only while nothing covers the scene
  document.addEventListener('keydown', (e) => {
    const don = donusTusu(e);
    const ne = zoomTusu(e) || (don ? (don < 0 ? 'sola' : 'saga') : null);
    const yon = ne || !sahneHedefi(e.target) ? null : kaydirmaTusu(e);
    if ((!ne && !yon) || document.body.classList.contains('panel-acik') || $('drawer').classList.contains('is-open') ||
      !$('detail').hidden || !$('calisanlar').hidden || komutaOpen()) return;
    e.preventDefault();
    if (ne) zoomEt(ne);
    else office.kaydir(yon[0], yon[1]);
  });
  kaydirIpucu();
} else {
  $('zoom-kontrol').hidden = true;
}

// The arrow / WASD pan keys belong to the scene only when nothing else has the focus (the page itself) or the focus is
// in the scene: inside the side panel or another scroll area the arrows keep scrolling it.
function sahneHedefi(t) {
  return !t || t === document.body || t === document.documentElement || $('scene').contains(t);
}

// A one-time hint next to the zoom buttons: how to move around the floor. Closed with its ×, remembered per browser
// (storage may be unavailable: then it simply shows again); hidden on phones and touch screens by CSS.
function kaydirIpucu() {
  const KEY = 'ofis.kaydirIpucu.kapali';
  let closed = false;
  try { closed = window.localStorage.getItem(KEY) === '1'; } catch (e) { closed = false; }
  if (closed) return;
  const box = h('div', 'kaydir-ipucu');
  box.id = 'kaydir-ipucu';
  box.setAttribute('role', 'note');
  box.appendChild(h('span', '', 'Sürükle ya da iki parmakla kaydır · Sıkıştırarak yakınlaştır · Sağ tık ya da ↺ ↻: döndür'));
  const x = h('button', 'kaydir-ipucu-kapat', '×');
  x.type = 'button';
  x.setAttribute('aria-label', 'İpucunu kapat');
  x.title = 'Kapat';
  x.addEventListener('click', () => {
    box.remove();
    try { window.localStorage.setItem(KEY, '1'); } catch (e) { /* not remembered */ }
  });
  box.appendChild(x);
  $('zoom-kontrol').insertAdjacentElement('afterend', box);
}

// --- transport ---
// The demo plays a scripted loop of every scene event (demo.js DEMO_SAHNELERI) and names the current one in a small
// caption (textContent); ?demo_t=<s> starts the loop at second s.
function showDemoCaption(text) {
  const el = $('demo-caption');
  if (!el) return;
  el.textContent = text || '';
  el.hidden = !text;
}
const demo = DEMO ? createDemo({ onState: (s) => applyState(s), onChat: (c) => applyChat(c), onSahne: showDemoCaption,
  baslangic: Math.max(0, Number(params.get('demo_t')) || 0),
  mola: String(params.get('demo_mola') || '').slice(0, 20), ceo: String(params.get('demo_ceo') || '').slice(0, 20),
  duyuru: String(params.get('demo_duyuru') || '').slice(0, 120) }) : null;

// GET for the Raporlar / Kalite views and the report detail: {status, data}; the demo answers with fake data.
async function getJson(path) {
  if (demo) return demo.get(path);
  try {
    const res = await fetch(path, { cache: 'no-store' });
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    return { status: res.status, data };
  } catch {
    return { status: 0, data: null };
  }
}

async function post(path, body) {
  if (demo) return demo.post(path, body);
  const send = async (token) => {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Ofis-Token': token },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch { /* empty body */ }
    return { status: res.status, data };
  };
  // a restarted server with a new token: keep the draft, fetch the fresh token from the page, retry once
  const out = await tekrarla(send, pageNonce, path, body, {
    fetchHtml: async () => (await fetch('/', { cache: 'no-store' })).text(),
    storage: (() => { try { return window.sessionStorage; } catch { return null; } })() || { setItem() {}, removeItem() {} },
  });
  pageNonce = out.token;
  return out.res;
}

function setOnline(v) {
  if (online === v) return;
  online = v;
  renderTop();
  renderGreeting();
}

async function loadOnce() {
  try {
    const [s, c] = await Promise.all([fetch('/api/state'), fetch('/api/chat')]);
    if (!s.ok || !c.ok) throw new Error('bad status');
    applyState(await s.json());
    applyChat((await c.json()).messages || []);
    setOnline(true);
  } catch {
    setOnline(false);
  }
}

function connect() {
  if (demo) { online = true; $('demo-pill').hidden = false; renderTop(); return; }
  loadOnce();
  const source = new EventSource('/api/events');
  source.addEventListener('open', () => setOnline(true));
  source.addEventListener('error', () => setOnline(false));
  source.addEventListener('state', (e) => { try { applyState(JSON.parse(e.data)); setOnline(true); } catch { /* ignore */ } });
  source.addEventListener('chat', (e) => { try { applyChat(JSON.parse(e.data).messages || []); } catch { /* ignore */ } });
}

// --- state → feed diff ---
// Feed lines are one-liners: strip the Markdown marks the CEO uses and cut at a word boundary.
function feedText(text, max = 110) {
  const flat = (text || '').replace(/\*\*([^*]+)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*•]\s+/gm, '').replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  return cut.slice(0, Math.max(cut.lastIndexOf(' '), max * 0.6)).replace(/[,;:.\s]+$/, '') + '…';
}

// tur: the event's badge on the "Son olanlar" tab (olayRozeti); a notice also keeps its message (m) and is drawn there
// as the chat's own notice card
function pushFeed(text, color, time = new Date(), detail = null, tur = 'sistem', m = null) {
  feed.unshift({ text, color, time, detail, tur, m });
  if (feed.length > 40) feed.length = 40;
  renderFeed();
}

function diffState(prev, cur) {
  if (!prev) {
    for (const t of cur.tasks.slice(0, 6).reverse()) {
      feed.unshift({ text: `${t.project} · ${feedText(t.title, 80) || 'iş'} (${STATUS_TR[t.status] || t.status})`, color: dotColor(t.project), time: parseTime(t.started), detail: { kind: 'task', note: t.note },
        tur: t.status === 'bitti' ? 'is-bitti' : t.status === 'tikandi' || t.status === 'basarisiz' ? 'takildi' : 'is' });
    }
    for (const d of cur.decisions) feed.unshift({ text: `${d.project} soru sordu: ${d.title}`, color: '#F2784B', time: parseTime(d.asked), detail: decisionDetail(d), tur: 'soru' });
    renderFeed();
    return;
  }
  const prevTasks = new Map(prev.tasks.map((t) => [t.note, t]));
  for (const t of [...cur.tasks].reverse()) {
    const before = prevTasks.get(t.note);
    if (!before) pushFeed(`${t.project} işe başladı: ${feedText(t.title, 80) || 'yeni iş'}`, dotColor(t.project), new Date(), { kind: 'task', note: t.note }, 'is-basladi');
    else if (before.status !== t.status) {
      if (t.status === 'bitti') pushFeed(`${t.project} işi bitirdi: ${feedText(t.title, 80)}`, '#4E9F76', new Date(), { kind: 'task', note: t.note }, 'is-bitti');
      else if (t.status === 'tikandi' || t.status === 'basarisiz') pushFeed(`${t.project} takıldı: ${feedText(t.title, 80)}`, '#C0504D', new Date(), { kind: 'task', note: t.note }, 'takildi');
    }
  }
  const prevDec = new Set(prev.decisions.map((d) => d.note));
  const curDec = new Set(cur.decisions.map((d) => d.note));
  for (const d of cur.decisions) if (!prevDec.has(d.note)) pushFeed(`${d.project} soru sordu: ${d.title}`, '#F2784B', new Date(), decisionDetail(d), 'soru');
  for (const d of prev.decisions) {
    if (!curDec.has(d.note)) { pushFeed(`${d.project} sorusu cevaplandı`, '#4E9F76', new Date(), null, 'cevaplandi'); sentLocal.delete(d.note); }
  }
}

function applyState(s) {
  if (!s || !Array.isArray(s.projects)) return;
  const prev = state;
  state = s;
  sahipAyarla(s.sahip); // the owner's name (ofis.json sahip_adi) for every text below, before anything is drawn
  diffState(prev, s);
  isToastlari(toastOlaylari(prev, s)); // only changes since the last snapshot: nothing from before the page loaded
  renderAll();
}

// --- "İş bitti" toasts (owner decision 2026-11-14): top-right, at most TOAST_EN_COK, each ~6 s; a click opens the job's card
// (a decision: its answer card in the Komuta masası); × or Esc closes. No sound, no browser notification. Text only.
let toastlar = []; // [{...item, el, timer}], newest first
function toastKapat(item) {
  clearTimeout(item.timer);
  item.el.remove();
  toastlar = toastlar.filter((x) => x !== item);
}
function toastAc(item) {
  toastKapat(item);
  if (item.tur === 'ceo') ceoMesajinaGit(item.mesaj);
  else if (item.karar && (item.tur === 'soru' || item.tur === 'mudur')) {
    openKomuta(null);
    setTimeout(() => focusDecision(item.karar), 80);
  } else if (item.is) openDetail({ kind: 'task', note: item.is });
}
function isToastlari(yeni) {
  if (!yeni.length) return;
  const box = $('is-toastlar');
  const keep = toastYigini(toastlar, yeni);
  for (const x of toastlar) if (!keep.includes(x)) toastKapat(x);
  toastlar = keep.map((x) => {
    if (x.el) return x;
    const item = { ...x };
    const el = h('div', `is-toast tur-${x.tur}`);
    const text = h('div', 'is-toast-metin');
    text.append(h('span', 'is-toast-ikon', x.ikon), document.createTextNode(` ${x.metin}`));
    makeClickable(text, () => toastAc(item));
    const close = h('button', 'icon-btn', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Kapat');
    close.addEventListener('click', () => toastKapat(item));
    el.append(text, close);
    item.el = el;
    item.timer = setTimeout(() => toastKapat(item), TOAST_SURE_MS);
    return item;
  });
  for (const x of [...toastlar].reverse()) box.prepend(x.el); // newest on top
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && toastlar.length) [...toastlar].forEach(toastKapat);
});

// New CEO lines while the chat is not seen (closed, or the tab hidden): a toast and the unread badge. Never before the
// chat is seeded (applyChat calls this only afterwards).
function ceoYazdi(fresh) {
  const toasts = ceoToastlari(fresh, chatKey);
  if (!toasts.length) return;
  if (!sohbetGorulmedi($('drawer').classList.contains('is-open'), komutaOpen(), document.hidden)) return;
  isToastlari(toasts);
  ceoOkunmamis = okunmamisSayi(ceoOkunmamis, toasts.length, true);
  renderCeoRozet();
}
// Opening the chat (drawer or Komuta masası) clears the count; so does coming back to the tab while it is open.
function ceoOkundu() { ceoOkunmamis = 0; renderCeoRozet(); }
function renderCeoRozet() {
  const btn = $('open-chat-top');
  const sayi = $('open-chat-top-sayi');
  const metin = okunmamisMetni(ceoOkunmamis);
  sayi.textContent = metin;
  sayi.hidden = !metin;
  btn.setAttribute('aria-label', metin ? `CEO ile sohbet · ${ceoOkunmamis} okunmamış mesaj` : 'CEO ile sohbet');
  renderSekmeBasligi();
}
// A click on a "CEO yazdı" toast: open the chat scrolled to that line.
function ceoMesajinaGit(anahtar) {
  openKomuta(null);
  setTimeout(() => {
    if (komutaOpen()) setKomutaSekme('sohbet');
    const el = [...$('komuta-messages').children].find((x) => x.dataset && x.dataset.anahtar === anahtar);
    if (el) el.scrollIntoView({ block: 'center' });
  }, 80);
}
// The owner's chat lines: role "sahip" (bin/transcript.py ROLE), the old "deniz" read the same.
const sahipSatiri = (m) => !!m && (m.role === 'sahip' || m.role === 'deniz');
const chatKey = (m) => `${m.time}|${m.role}|${(m.text || '').slice(0, 80)}`;

function applyChat(messages) {
  const fresh = [];
  for (const m of messages) {
    const k = chatKey(m);
    if (!seenChat.has(k)) { seenChat.add(k); fresh.push(m); }
  }
  chat = messages;
  if (chatSeeded) {
    for (const m of fresh) {
      const when = parseTime(m.time) || new Date();
      if (m.role === 'ceo') {
        pushFeed(`CEO: ${feedText(m.text)}`, '#F2784B', when, { kind: 'message', kicker: 'CEO', title: 'CEO mesajı', text: m.text, time: when }, 'ceo');
      } else if (m.role === 'system' && m.kind === 'notice') {
        const c = bildirimKarti(m.text);
        pushFeed(`Ofis: ${feedText(c.baslik)}`, '#A79B8C', when,
          { kind: 'message', kicker: `Ofis · ${c.etiket}`, title: c.baslik, text: c.ham || c.baslik, time: when }, 'bildirim', m);
      } else if (m.role === 'system' && m.from) {
        const r = parseRelay(m);
        pushFeed(`${r.project} · ${r.label.toLocaleLowerCase('tr-TR')}: ${feedText(r.text)}`, '#A79B8C', when,
          { kind: 'message', kicker: `${r.project} · ${r.label}`, title: `${r.project} mesajı`, text: r.text, time: when, session: m.from }, 'proje');
      } else if (m.role === 'system') pushFeed(feedText(m.text, 120), '#A79B8C', when, { kind: 'message', kicker: 'Sistem', title: 'Sistem mesajı', text: m.text, time: when }, 'sistem');
    }
  }
  if (chatSeeded) ceoYazdi(fresh);
  chatSeeded = true;
  for (let i = optimistic.length - 1; i >= 0; i--) {
    if (messages.some((m) => sahipSatiri(m) && m.text === optimistic[i].text)) optimistic.splice(i, 1);
  }
  renderChat(fresh.length > 0);
  loadTurlar();
}

// The footer under each CEO reply (GET /api/ceo/turlar): read again when the chat or the CEO's state changes; the chat
// is rebuilt only when a footer changed.
let turlar = [];
let turKey = '';
let turSeq = 0;
let turTimer = null;
let turCeoKey = '';
function loadTurlar() {
  clearTimeout(turTimer);
  turTimer = setTimeout(async () => {
    const seq = ++turSeq;
    const res = await getJson('/api/ceo/turlar');
    if (seq !== turSeq || res.status !== 200 || !res.data || !Array.isArray(res.data.turlar)) return;
    const key = JSON.stringify(res.data.turlar);
    if (key === turKey) return;
    turKey = key;
    turlar = res.data.turlar;
    renderChat(false);
  }, 400);
}

function turAlti(tur) {
  const t = turAltMetni(tur);
  if (!t) return null;
  const box = h('div', 'msg-tur');
  for (const j of t.isler) {
    const b = h('button', 'msg-tur-is', j.metin);
    b.type = 'button';
    b.addEventListener('click', () => openDetail({ kind: 'task', note: j.note }));
    box.appendChild(b);
    const yol = yolCizgisi(stateTask(j.note), { kompakt: true });  // kept fresh by renderAll (yollariYenile)
    if (yol) {
      yol.setAttribute('data-yol-not', j.note);
      box.appendChild(yol);
    }
  }
  box.appendChild(h('small', null, t.metin));
  return box;
}

// --- rendering ---
function renderAll() {
  renderOfisAdi();
  renderSahipAdi();
  renderPostoffice();
  renderSchedules();
  renderModels();
  renderTop();
  renderGreeting();
  renderAsks();
  renderScene();
  renderTasks();
  renderRoomCard();
  renderChatMeta();
  renderKomuta();
  renderYakala();
  yollariYenile(document, stateTask);  // the jobs' progress lines under the CEO's "İş açıldı" lines
}

// The office's name (/api/state.ofis.adi, ofis.json ofis_adi, the Ayarlar tab; default "Ofis"): the tab title, the
// top bar and the scene's lobby sign / hall screen. Text only; redrawn only when it changes.
let ofisAdi = null;
function renderOfisAdi() {
  const o = state && state.ofis;
  const ad = (o && typeof o.adi === 'string' && o.adi.trim()) || 'Ofis';
  if (ad === ofisAdi) return;
  ofisAdi = ad;
  baseTitle = ad;
  $('brand-ad').textContent = ad;
  renderSekmeBasligi();
  if (office) office.setOfisAdi(ad);
}

// The owner's name in the page's static text (/api/state.sahip, ofis.json sahip_adi; web/ofis-davranis.js sahip):
// every <span class="sahip-in"> gets the genitive form ("Ayşe'nin"). Text only; redrawn only when it changes.
let sahipMetni = null;
function renderSahipAdi() {
  const ek = sahip('in');
  if (ek === sahipMetni) return;
  sahipMetni = ek;
  for (const el of document.querySelectorAll('.sahip-in')) el.textContent = ek;
}

// "Yakala" (bin/yakala.py): shown only while ofis.json yakala.acik; the last few captures as text (textContent only)
const YAKALA_DURUM = { bekliyor: 'sırada bekliyor', 'is-eklendi': 'Ar-Ge inceliyor', bitti: 'incelendi', kapandi: 'tamamlanamadı' };
function renderYakala() {
  const y = state && state.yakala && typeof state.yakala === 'object' ? state.yakala : null;
  $('yakala-yap').hidden = !(y && y.acik);
  const ul = $('yakala-son');
  ul.textContent = '';
  for (const it of (y && Array.isArray(y.son) ? y.son : []).slice(0, 5)) {
    const li = document.createElement('li');
    let t = `${String(it.baslik || '').slice(0, 60)} — ${YAKALA_DURUM[it.durum] || String(it.durum || '')}`;
    if (it.oneri) t += ` · öneri: ${String(it.oneri).slice(0, 20)}`;
    else if (it.hata) t += ' · iş eklenemedi, yeniden denenecek';
    li.textContent = t;
    ul.appendChild(li);
  }
}

// The owner's Claude plan usage limits (limitPill, web/limitler.js): hidden without data; amber ≥ 80 %, red ≥ 95 %
function renderLimit() {
  const el = $('limit-pill');
  if (!el) return;
  const lp = limitPill(online && state ? state.limitler : null);
  el.hidden = lp.gizli;
  el.textContent = lp.metin;
  el.title = lp.ipucu;
  el.setAttribute('aria-label', lp.ipucu);
  el.classList.toggle('is-uyari', lp.ton === 'uyari');
  el.classList.toggle('is-kritik', lp.ton === 'kritik');
  if (lp.gizli) uyariKapat('limit-pill');
}

function renderTop() {
  renderLimit();
  const pill = $('live-pill');
  pill.classList.toggle('is-down', !online);
  if (!online) { $('live-text').textContent = 'Sunucu kapalı'; renderCalisanlar(); return; }
  const n = state ? state.summary.working + (state.ceo.state === 'busy' ? 1 : 0) : 0;
  // one pill: who works, the running limit only at the limit, the approval backlog's hold (canliPill)
  const live = canliPill(state && state.summary, n);
  pill.classList.toggle('is-quiet', n === 0 && !live.ton);
  pill.classList.toggle('is-limit', live.ton === 'sinirda');
  $('live-text').textContent = live.metin;
  $('live-count').textContent = String(n);
  pill.title = live.baslik;
  pill.setAttribute('aria-label', `${live.metin} — şu an iş başında olanları göster`);
  const birikti = onayBiriktiMetni(state && state.summary);
  const chip = $('onay-birikti');  // a top-bar chip (the owner, 2026-11-13: no longer a strip in the right panel)
  if (chip) {
    chip.hidden = !birikti;
    $('onay-birikti-text').textContent = birikti;
    const ob = state && state.summary && state.summary.onay_birikti;
    $('onay-birikti-etiket').textContent = ob && ob.bekleyen ? `${ob.bekleyen} onay bekliyor` : 'Onay birikti';
    chip.title = birikti;
    if (!birikti) uyariKapat('onay-birikti');
  }
  const pending = state ? state.decisions.length : 0;
  const tc = $('tab-count-kararlar');
  tc.hidden = pending === 0;
  tc.textContent = String(pending);
  renderCalisanlar();
}

// Post office problems (state.postoffice): the "İletişim uyarısı" chip in the top bar, hidden when all is well; a
// click opens the lines under it (the owner, 2026-11-13: no longer a strip in the right panel).
function renderPostoffice() {
  const lines = postofficeWarnings(state && state.postoffice);
  const box = $('po-warn');
  if (!box) return;
  box.hidden = lines.length === 0;
  $('po-warn-etiket').textContent = lines.length > 1 ? `İletişim uyarısı · ${lines.length}` : 'İletişim uyarısı';
  $('po-warn-list').replaceChildren(...lines.map((line) => h('li', null, line)));
  if (!lines.length) uyariKapat('po-warn');
}

// The warning chips' detail (onay-birikti, po-warn): a click toggles it; Esc or a click outside closes it.
const UYARI_CIPLERI = ['onay-birikti', 'po-warn', 'limit-pill'];
function uyariKapat(id) {
  const chip = $(id);
  const panel = $(`${id}-detay`);
  if (!chip || !panel) return;
  panel.hidden = true;
  chip.setAttribute('aria-expanded', 'false');
}
for (const id of UYARI_CIPLERI) {
  const chip = $(id);
  if (!chip) continue;
  chip.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = $(`${id}-detay`).hidden;
    UYARI_CIPLERI.forEach(uyariKapat);
    if (open) { $(`${id}-detay`).hidden = false; chip.setAttribute('aria-expanded', 'true'); }
  });
}
document.addEventListener('click', (e) => {
  const t = e.target;
  if (t instanceof Element && t.closest('.uyari-kap')) return;
  UYARI_CIPLERI.forEach(uyariKapat);
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  for (const id of UYARI_CIPLERI) {
    const panel = $(`${id}-detay`);
    if (panel && !panel.hidden) { uyariKapat(id); $(id).focus(); }
  }
});

// The usage popup under the limit pill (owner decision 2026-11-16): opening it asks GET /api/kullanim (bin/kullanim.py; the
// server caches it 60 s) and shows each window's bar and reset time and "En çok kullananlar" of the chosen window
// (kullanimGorunumu, web/limitler.js). Text via textContent only; the bar's width is a clamped number.
let kullanimVeri = null;
let kullanimSekme = 'bes_saat';
let kullanimDurum = '';
function renderKullanim() {
  const g = kullanimGorunumu(kullanimVeri, kullanimSekme, kullanimDurum);
  $('limit-pencereler').replaceChildren(...g.pencereler.map((p) => {
    const dolu = h('span', `limit-bar-dolu${p.ton ? ` is-${p.ton}` : ''}`);
    dolu.style.width = `${Math.max(0, Math.min(100, p.genislik))}%`;
    const bar = h('div', 'limit-bar');
    bar.setAttribute('role', 'img');
    bar.setAttribute('aria-label', `${p.etiket} ${p.yuzdeMetni}`);
    bar.append(dolu);
    const ust = h('div', 'limit-pencere-ust');
    ust.append(h('span', null, p.etiket), h('strong', null, p.yuzdeMetni));
    const alt = h('p', 'limit-alt', [p.yenilenir, p.kalan].filter(Boolean).join(' · '));
    const kutu = h('div', 'limit-pencere');
    kutu.append(ust, bar, alt);
    return kutu;
  }), ...(g.sinirYok ? [h('p', 'limit-alt', g.sinirYok)] : []));
  $('limit-olcum').textContent = g.olcum;
  for (const b of document.querySelectorAll('.limit-sekme')) {
    const on = b.dataset.sekme === g.sekme;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  }
  $('limit-aralik').textContent = g.aralik;
  const satir = (r, cls) => {
    const li = h('li', cls);
    li.append(h('span', 'limit-ad', r.ad), h('span', 'limit-sayi', r.metin));
    if (r.cikti) li.append(h('span', 'limit-cikti', r.cikti));
    return li;
  };
  const items = g.satirlar.map((r) => satir(r, null));
  if (g.toplam) items.push(satir(g.toplam, 'is-toplam'));
  if (g.bos) items.push(h('li', 'is-bos', g.bos));
  $('limit-liste').replaceChildren(...items);
  $('limit-not').textContent = [g.fiyatNotu, g.satirlar.length ? g.not : ''].filter(Boolean).join(' ');
}
async function kullanimYukle() {
  if (kullanimDurum === 'yukleniyor') return;
  kullanimDurum = 'yukleniyor';
  renderKullanim();
  const res = await getJson('/api/kullanim');
  const ok = res && res.status === 200 && res.data && typeof res.data === 'object';
  if (ok) kullanimVeri = res.data;
  kullanimDurum = ok ? '' : 'hata';
  renderKullanim();
}
if ($('limit-pill')) {
  // registered after the generic toggle above: the panel is already open when this runs
  $('limit-pill').addEventListener('click', () => { if (!$('limit-pill-detay').hidden) kullanimYukle(); });
  for (const b of document.querySelectorAll('.limit-sekme')) {
    b.addEventListener('click', () => { kullanimSekme = b.dataset.sekme; renderKullanim(); });
  }
}

// The "Zamanlanmış" tab (state.schedules, bin/zamanla.py summaries; the owner, 2026-11-13: moved out of the side panel):
// one table row per schedule (ad, proje, ne zaman, sonraki, durum, son koşu) and, under it, each schedule's last runs
// as Obsidian links to their job notes (and the job a run was escalated to). Rebuilt only when its content changed.
function renderSchedules() {
  const rows = zamanlanmisSatirlari(state && state.schedules);
  const tc = $('tab-count-zamanlanmis');
  tc.hidden = rows.length === 0;
  tc.textContent = String(rows.length);
  const key = JSON.stringify(rows);
  if (key === schedKey) return;
  schedKey = key;
  $('sched-empty').hidden = rows.length > 0;
  $('sched-runs-title').hidden = rows.length === 0;
  $('sched-body').replaceChildren(...rows.map((r) => {
    const tr = h('tr', r.durum === 'duraklatıldı' ? 'is-paused' : null);
    const ad = h('td');
    ad.append(notLinki(r.ad, r.ad, 'Zamanlanmis'), h('div', 'muted', r.baslik));
    const durum = h('td', null, r.durum);
    if (r.neden) durum.append(h('div', 'muted', r.neden));
    const son = h('td');
    const k = r.kosular[0];
    if (k) son.append(notLinki(k.is, r.sonKosu, 'Isler'));
    else son.textContent = r.sonKosu;
    tr.append(ad, h('td', null, r.proje), h('td', null, r.zaman), h('td', null, r.sonraki), durum, son);
    return tr;
  }));
  $('sched-runs').replaceChildren(...rows.map((r) => {
    const box = h('section', 'sched-run');
    box.append(h('h4', null, `${r.baslik} · ${r.proje}`));
    if (!r.kosular.length) { box.append(h('p', 'muted', 'Henüz koşmadı.')); return box; }
    const ul = h('ul', 'sched-run-list');
    for (const x of r.kosular) {
      const li = h('li');
      if (x.zaman) li.append(h('time', null, x.zaman));
      li.append(notLinki(x.is, x.is, 'Isler'), h('span', `sched-sonuc sonuc-${x.sonuc === 'bitti' ? 'ok' : x.sonuc === 'sürüyor' ? 'acik' : 'kotu'}`, x.sonuc));
      if (x.son_is) li.append(document.createTextNode(' → '), notLinki(x.son_is, x.son_is, 'Isler'));
      ul.append(li);
    }
    box.append(ul);
    return box;
  }));
}

// The workers' status (state.modeller): the "Çalışanlar" section of the live pill's popover ("Şu an iş başında") and
// the Komuta masası's Kararlar column, from the same rows (ofis-sahne.js modelSatirlari; the owner, 2026-11-13: no longer in
// the side panel). Re-rendered on every state and on the 1 s tick (the return time is relative to now); the Komuta
// list's DOM changes only when a row's text changes.
let modelKey = null;
function renderModels() {
  if (!state) return;
  const rows = modelSatirlari(state.modeller, Date.now(), state.sahne);
  const key = rows.map((r) => `${r.ton}|${r.metin}`).join('\n');
  renderCalisanlarKadro(rows);
  if (key === modelKey) return;
  modelKey = key;
  if ($('komuta-models-list')) {
    $('komuta-models-sum').textContent = modelOzeti(rows);
    $('komuta-models-list').replaceChildren(...calisanGruplari(rows).flatMap((g) => [h('li', 'models-group', g.baslik),
      ...g.rows.map((r) => {
        const li = h('li', `ton-${r.ton}`);
        li.append(h('span', 'dot'), h('span', null, r.rol_metin));
        li.title = r.ipucu;
        return li;
      })]));
  }
}

function greetingWord() {
  const hr = new Date().getHours();
  if (hr >= 5 && hr < 11) return 'Günaydın.';
  if (hr >= 11 && hr < 18) return 'İyi günler.';
  if (hr >= 18 && hr < 23) return 'İyi akşamlar.';
  return 'İyi geceler.';
}

// The greeting folds into a small pill a few seconds after load (it would cover the floor's top-left corner); a click
// opens or folds it again, and the choice is remembered in this browser (storage may be unavailable).
const SELAM_KEY = 'ofis.selam.acik';
{
  const greet = document.querySelector('.greeting');
  if (greet) {
    let keepOpen = false;
    try { keepOpen = window.localStorage.getItem(SELAM_KEY) === '1'; } catch (e) { keepOpen = false; }
    const fold = (compact) => {
      greet.classList.toggle('is-compact', compact);
      greet.setAttribute('aria-expanded', String(!compact));
    };
    greet.tabIndex = 0;
    greet.setAttribute('role', 'button');
    greet.setAttribute('aria-expanded', 'true');
    if (!keepOpen) setTimeout(() => fold(true), 6000);
    const toggle = () => {
      const compact = !greet.classList.contains('is-compact');
      fold(compact);
      try { window.localStorage.setItem(SELAM_KEY, compact ? '0' : '1'); } catch (e) { /* storage unavailable */ }
    };
    greet.addEventListener('click', toggle);
    greet.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  }
}

function renderGreeting() {
  $('greeting-title').textContent = greetingWord();
  if (!state) {
    $('greeting-text').textContent = online ? 'Ofisin durumu yükleniyor…' : 'Sunucuya ulaşılamıyor. Sunucu çalışıyor mu? (python3 bin/server.py)';
    return;
  }
  const s = state.summary;
  const parts = [s.tasks_today > 0 ? `Bugün ${s.tasks_today} iş başladı.` : 'Bugün henüz yeni iş başlamadı.'];
  const people = [`${s.working} ajan çalışıyor`];
  if (s.waiting) people.push(`${s.waiting} ajan cevabını bekliyor`);
  people.push(`${s.sleeping} ajan uyuyor`);
  parts.push(people.join(', ') + '.');
  parts.push(`Bugün toplam ${fmtUsage(s.usage_today)} token kullanıldı.`);
  parts.push(s.pending_decisions ? `Seni bekleyen ${s.pending_decisions} soru var.` : 'Bekleyen soru yok.');
  if (!online) parts.push('Sunucu şu an kapalı; son bilinen durum gösteriliyor.');
  else if (state.agents_error) parts.push('Oturum listesi okunamadı; durumlar eksik olabilir.');
  $('greeting-text').textContent = parts.join(' ');
}

// The living office: the behaviour engine (ofis-davranis.js) turns the state into actors, the scene draws and walks
// them. The plan is rebuilt only when the projects or the desks per team change; `prevActors` keeps desks stable.
let plan = null;
let planKey = '';
let prevActors = null;
function deskLimit() {
  const n = Number(state && state.summary && state.summary.max_running_per_project);
  return Number.isFinite(n) && n > 0 ? n : 1;
}

function renderScene() {
  if (!office || !state) return;
  const per = deskLimit();
  const denetciler = denetciListesi(state.modeller); // one desk per external auditor in the auditor's room
  const key = `${state.projects.map((p) => p.name).join('|')}#${per}#${denetciler.join(',')}`;
  if (key !== planKey) {
    plan = ofisPlani(state.projects, { max_running_per_project: per, denetciler });
    planKey = key;
    prevActors = null;
  }
  let actors;
  try {
    actors = niyetler(state, Date.now(), prevActors, { hafif: LIGHT, max_running_per_project: per, plan });
  } catch (e) {
    console.error('ofis sahnesi', e);
    return;
  }
  prevActors = actors;
  office.setActors(actors, plan);
  // the decorative people of the QA odası, the Analist odası and the team bays (purely visual; ofis-davranis.js dekorEkibi)
  office.setDekor(dekorEkibi(plan, actors, Date.now(), state.sahne));
  // the conference hall's screen: the announcement's first line for about a minute, else the office's name
  office.setDuyuru(salonEkrani(state, Date.now()));
  // the Sunucu odası's lights: the load colour and a cabinet's warning light (state.sistem, changed in place)
  office.setSistem(state.sistem);
  mesaiDisiGuncelle();
}

// Outside the office hours a small line above the zoom buttons: "Mesai dışı · N kişi otelde · 08:30'da dönüyorlar"
// (mesaiDisiSatiri: N from kimNerede, the time from the office hours; a phone shows the short form); hidden inside the
// office hours (and, by CSS, while a tab panel is open). Recomputed at most every 10 s. A click opens the card of the
// guard on shift (his "Ofiste olanlar" / "Evde olanlar"). textContent only.
let mesaiDisiSon = 0;
function mesaiDisiGuncelle() {
  const el = $('mesai-disi');
  if (!el || !state || Date.now() - mesaiDisiSon < 10000) return;
  mesaiDisiSon = Date.now();
  let uzun = '', kisa = '';
  try {
    uzun = mesaiDisiSatiri(state, Date.now());
    kisa = uzun ? mesaiDisiSatiri(state, Date.now(), { kisa: true }) : '';
  } catch (e) { uzun = ''; }
  $('mesai-disi-uzun').textContent = uzun;
  $('mesai-disi-kisa').textContent = kisa;
  el.setAttribute('aria-label', uzun);
  el.hidden = !uzun;
}
$('mesai-disi').addEventListener('click', () => {
  const g = (prevActors || []).find((x) => x && x.tur === 'sus' && x.gorevli === 'guvenlik' && x.nobetci);
  const r = $('mesai-disi').getBoundingClientRect();
  if (g) openActor(g, { x: Math.max(8, r.left - 200), y: Math.max(64, r.top - 260) });
});

// A click on a character: its job's detail (helpers open their parent's job), the CEO opens the CEO card.
// Clicking any character opens its small info card (karakterKarti in ofis-sahne.js) near the click; a job's detail,
// the command desk or the decisions open only from the card's buttons. Esc, a click outside or a tab panel closes it.
let kart = null; // {id, actor, x, y, at}
function openActor(a, at) {
  if (!a) return;
  const p = at && Number.isFinite(at.x) ? at : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  kart = { id: a.id, actor: a, x: p.x, y: p.y, at: Date.now() };
  kartGoster(true);
}
function kartKapat() {
  if (!kart) return;
  kart = null;
  const el = $('karakter-kart');
  if (el) el.hidden = true;
}
function kartGoster(place = false) {
  if (!kart || !state) return;
  const a = (prevActors || []).find((x) => x.id === kart.id) || kart.actor;
  kart.actor = a;
  kartVeriYukle(a);
  const k = karakterKarti(a, state, Date.now(), { aktorler: prevActors, veri: kartVeri });
  // rebuilt only when the card's content changed: a rebuild every second lost clicks on its buttons and the focus
  const anahtar = JSON.stringify(k);
  let el = $('karakter-kart');
  if (el && !place && kart.anahtar === anahtar && !el.hidden) return;
  kart.anahtar = anahtar;
  if (!el) {
    el = h('section', 'karakter-kart card');
    el.id = 'karakter-kart';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Karakter kartı');
    document.body.appendChild(el);
  }
  const head = h('header', 'karakter-kart-head');
  const titles = h('div', 'karakter-kart-baslik');
  titles.append(h('strong', null, k.baslik));
  if (k.alt) titles.append(h('span', 'karakter-kart-alt', k.alt));
  const x = h('button', 'icon-btn', '×');
  x.type = 'button';
  x.setAttribute('aria-label', 'Kapat');
  x.addEventListener('click', () => kartKapat());
  head.append(titles, x);
  // the folding parts (a group, a long list's rest) the viewer opened stay open when the card is rebuilt
  const acik = new Set([...el.querySelectorAll('details[data-anahtar][open]')].map((d) => d.dataset.anahtar));
  const govde = kartIcerigi(k, acik);
  const acts = h('div', 'karakter-kart-eylemler');
  for (const e of k.eylemler) {
    const b = h('button', 'btn btn-soft', e.metin);
    b.type = 'button';
    b.addEventListener('click', () => kartEylem(e));
    acts.append(b);
  }
  el.replaceChildren(head, ...(govde.childElementCount ? [govde] : []), ...(k.eylemler.length ? [acts] : []));
  el.hidden = false;
  if (!place) return;
  // near the click, kept inside the window
  const w = el.offsetWidth || 560, hgt = el.offsetHeight || 300;
  const left = Math.max(KART_KENAR, Math.min(window.innerWidth - w - KART_KENAR, kart.x + 14));
  const top = Math.max(64, Math.min(window.innerHeight - hgt - KART_KENAR, kart.y + 14));
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}
// The one character card component (owner decision 2026-11-13, "kartlar okunaklı olsun"): every character's card — staff,
// managers, kadro, jobs, reviewers, the CEO — is drawn here from kartDuzeni(k): titled sections; label / value rows (a
// load or budget figure with a status bar); lists, folded after KART_LISTE_SINIRI - 1 lines into a details element; the
// numbers as real tables (the shift, the process groups, the spending, the budget warnings); the guard's groups as
// details. createElement / textContent only (linkli for [[note]] links), never an HTML string.
const KART_KENAR = 16; // the card's gutter to the window edge (also on a phone)
function kartIcerigi(k, acik = new Set()) {
  const govde = h('div', 'kart-govde');
  for (const b of kartDuzeni(k)) {
    const sec = h('section', 'kart-bolum');
    sec.append(h('h3', 'kart-bolum-baslik', b.baslik));
    const maddeler = b.ogeler.filter((o) => o.tur === 'madde').length;
    const katla = maddeler > KART_LISTE_SINIRI;
    let dl = null, ul = null, fazla = null, sira = 0;
    for (const o of b.ogeler) {
      if (o.tur !== 'satir') dl = null;
      if (o.tur !== 'madde') ul = null;
      if (o.tur === 'satir') {
        if (!dl) { dl = h('dl', 'kart-satirlar'); sec.append(dl); }
        const dd = linkli('dd', null, o.metin);
        if (o.cubuk) {
          const bar = h('div', `kart-cubuk ton-${o.cubuk.ton}`);
          bar.setAttribute('aria-hidden', 'true'); // the value is in the text next to it
          const dolu = h('span');
          dolu.style.width = `${o.cubuk.yuzde}%`;
          bar.append(dolu);
          dd.append(bar);
        }
        dl.append(h('dt', null, o.ad), dd);
      } else if (o.tur === 'madde') {
        sira += 1;
        if (katla && sira === KART_LISTE_SINIRI) {
          fazla = h('details', 'kart-fazla');
          fazla.dataset.anahtar = `fazla:${b.baslik}`;
          if (acik.has(fazla.dataset.anahtar)) fazla.open = true;
          fazla.append(h('summary', null, `${maddeler - KART_LISTE_SINIRI + 1} satır daha`));
          sec.append(fazla);
          ul = null;
        }
        if (!ul) { ul = h('ul', 'kart-liste'); (fazla || sec).append(ul); }
        ul.append(linkli('li', null, o.metin));
      } else if (o.tur === 'grup') {
        const grup = h('details', 'karakter-kart-grup');
        grup.dataset.anahtar = o.anahtar;
        if (acik.has(o.anahtar)) grup.open = true;
        const liste = h('ul');
        for (const u of o.uyeler) liste.append(linkli('li', null, u));
        grup.append(h('summary', null, o.metin), liste);
        (fazla || sec).append(grup);
      } else if (o.tur === 'tablo') {
        const wrap = h('div', 'kart-tablo-wrap');
        const table = h('table', 'kart-tablo');
        if (o.baslik) table.append(h('caption', null, o.baslik));
        const tr = h('tr');
        for (const c of o.basliklar) { const th = h('th', null, c); th.scope = 'col'; tr.append(th); }
        const thead = h('thead');
        thead.append(tr);
        const tbody = h('tbody');
        for (const row of o.satirlar) {
          const r = h('tr');
          for (const c of row) r.append(linkli('td', null, c));
          tbody.append(r);
        }
        table.append(thead, tbody);
        wrap.append(table);
        sec.append(wrap);
      }
    }
    govde.append(sec);
  }
  return govde;
}
// The data some staff cards read besides /api/state (Muhasebeci, İdari işler, İK, project residents): fetched when the
// card opens and again every 30 s while it stays open; a failed read keeps the last value (or none: the line is left out).
const KART_VERISI = { muhasebe: ['muhasebe'], idari: ['idari'], ik: ['muhasebe', 'kalite'], proje: ['muhasebe'],
  sunucu: ['sistem'], arge: ['arge'] };
const KART_VERI_ARALIGI = 30000;
const kartVeri = {};
const kartVeriZamani = {};
function kartVeriYukle(a) {
  // (of the managers only the IT Müdürü reads the Sunucu odası's suggestions)
  const need = (a && a.tur === 'sus' && (a.gorevli === 'mudur' ? (a.alan === 'it' ? ['sistem'] : []) : KART_VERISI[a.gorevli])) || [];
  for (const key of need) {
    if (kartVeriZamani[key] && Date.now() - kartVeriZamani[key] < KART_VERI_ARALIGI) continue;
    kartVeriZamani[key] = Date.now();
    getJson(`/api/${key}`).then((res) => {
      if (res.status === 200 && res.data && typeof res.data === 'object') { kartVeri[key] = res.data; if (kart) kartGoster(false); }
    });
  }
}
function kartEylem(x) {
  kartKapat();
  if (x.tur === 'is' && x.note) openDetail({ kind: 'task', note: x.note });
  else if (x.tur === 'komuta') openKomuta();
  else if (x.tur === 'kararlar') setTab('kararlar');
  else if (x.tur === 'karar' && x.note) { openKomuta(); focusDecision(x.note); } // that decision's card, its box focused
  else if (x.tur === 'kalite') setTab('kalite');
  else if (x.tur === 'raporlar') setTab('raporlar');
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && kart) { kartKapat(); e.stopPropagation(); }
}, true);
document.addEventListener('click', (e) => {
  if (!kart || Date.now() - kart.at < 400) return; // the click that opened it (canvas or label)
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;
  if (t.closest('#karakter-kart')) return;
  kartKapat();
});
// the 3D office is refreshed only while it can be seen (owner decision 2026-11-12, performance): not while the tab is hidden, a tab
// panel covers the scene or the Komuta masası is open; the side panel's lists stay live (not while hidden)
function sahneGorunur() {
  return !document.hidden && !document.body.classList.contains('panel-acik') && !komutaOpen();
}
setInterval(() => {
  if (!state || document.hidden) return;
  if (sahneGorunur()) renderScene();
  renderModels(); renderCalisanlar(); renderSema(); if (kart) kartGoster(false);
}, 1000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && (komutaOpen() || $('drawer').classList.contains('is-open'))) ceoOkundu();
  else renderSekmeBasligi();  // the tab title's unread prefix shows only while the tab is hidden
  if (state && sahneGorunur()) renderScene();
});

// --- "Şu an iş başında": the top bar's pill opens a small table of the active agents (ofis-sahne.js) ---
const PILLS = ['live-pill'];
let calisanlarFrom = null; // the pill that opened it (focus goes back there)
// Rows are keyed by id: when only their text changes (Süre every minute) the cells are updated in place, so a focused
// row keeps its focus and a click mid-press still lands; the rows are rebuilt only when the set of rows changes.
let calisanlarIds = null;
const calisanlarRows = new Map(); // row id -> its latest data (the click handler reads it from here)
function calisanlarOpen() { return !$('calisanlar').hidden; }
// The popover's "Çalışanlar" section: the grouped employee list (Kadro, Denetçiler) with the state dot and the short
// state, like the former 3D wall board ("Uzman · Sonnet", "kota doldu · 16:30'da döner"); textContent only.
let kadroKey = null;
function renderCalisanlarKadro(rows) {
  const list = $('calisanlar-kadro');
  if (!list || !calisanlarOpen()) return;
  const key = rows.map((r) => `${r.ton}|${r.pano_ad}|${r.kisa}`).join('\n');
  if (key === kadroKey && list.childElementCount) return;
  kadroKey = key;
  list.replaceChildren(...calisanGruplari(rows).flatMap((g) => [h('li', 'models-group', g.baslik),
    ...g.rows.map((r) => {
      const li = h('li', `ton-${r.ton}`);
      li.append(h('span', 'dot'), h('b', null, r.pano_ad || r.rol), h('span', 'kisa', r.kisa));
      li.title = r.ipucu;
      return li;
    })]));
}
// The open job's compact progress line under its title in the İş cell (web/is-akisi.js, the same line as the job
// cards'): replaced on every redraw so the dots move; removed when the job has no line; none on a row without a job.
// The row's click opens the job's detail, the line included.
function calisanYolu(td, note) {
  const eski = td.querySelector('[data-yol-not]');
  const t = note ? stateTask(note) : null;
  const yol = t ? yolCizgisi(t, { kompakt: true }) : null;
  if (yol) {
    yol.setAttribute('data-yol-not', note);
    if (eski) eski.replaceWith(yol); else td.append(yol);
  } else if (eski) eski.remove();
}
function renderCalisanlar() {
  if (!calisanlarOpen()) return;
  if (state) renderCalisanlarKadro(modelSatirlari(state.modeller, Date.now(), state.sahne));
  const rows = calisanlarTablosu(state, Date.now());
  if (!$('calisanlar-headrow').childElementCount) {
    $('calisanlar-headrow').replaceChildren(...CALISANLAR_BASLIK.map((c) => h('th', null, c)));
  }
  const empty = $('calisanlar-empty');
  empty.hidden = rows.length > 0;
  empty.textContent = online ? CALISANLAR_BOS : 'Sunucu kapalı; çalışanlar okunamıyor.';
  if (!online) empty.hidden = false;
  const shown = online ? rows : [];
  calisanlarRows.clear();
  for (const r of shown) calisanlarRows.set(r.id, r);
  const ids = shown.map((r) => `${r.id}|${r.ac ? 1 : 0}`).join('\n');
  const body = $('calisanlar-body');
  if (ids === calisanlarIds && body.children.length === shown.length) {
    shown.forEach((r, n) => {
      const tds = body.children[n].children;
      calisanHucreleri(r).forEach((text, i) => {
        const span = tds[i] && tds[i].firstChild;
        if (span && span.textContent !== text) span.textContent = text;
      });
      if (tds[1]) calisanYolu(tds[1], r.yolNot);
    });
    return;
  }
  calisanlarIds = ids;
  const cls = ['c-proje', 'c-is', 'c-calisan', 'c-katman', 'c-durum', 'c-sure', 'c-harcama', 'c-yardimci'];
  body.replaceChildren(...shown.map((row) => {
    const tr = h('tr');
    const r = row;
    calisanHucreleri(r).forEach((text, i) => {
      const td = h('td', cls[i]);
      td.setAttribute('data-k', CALISANLAR_BASLIK[i]);
      td.append(h('span', null, text));
      if (i === 2) td.title = calisanIpucu(r.unvan, r.model); // the model only in the tooltip
      if (i === 1) calisanYolu(td, r.yolNot);
      tr.append(td);
    });
    if (r.ac) {
      makeClickable(tr, () => {
        const now = calisanlarRows.get(r.id) || r;
        if (!now.ac) return;
        closeCalisanlar(false);
        if (now.ac.ceo) selectRoom(CEO);
        else openDetail({ kind: 'task', note: now.ac.note });
      });
    }
    return tr;
  }));
}
function openCalisanlar(from) {
  calisanlarFrom = from || null;
  $('calisanlar').hidden = false;
  calisanlarIds = null;
  kadroKey = null;
  for (const id of PILLS) $(id).setAttribute('aria-expanded', 'true');
  renderCalisanlar();
  $('calisanlar-close').focus();
}
function closeCalisanlar(restoreFocus = true) {
  if (!calisanlarOpen()) return;
  $('calisanlar').hidden = true;
  for (const id of PILLS) $(id).setAttribute('aria-expanded', 'false');
  if (restoreFocus && calisanlarFrom) calisanlarFrom.focus();
  calisanlarFrom = null;
}
for (const id of PILLS) {
  $(id).addEventListener('click', (e) => {
    e.stopPropagation();
    if (calisanlarOpen()) closeCalisanlar();
    else openCalisanlar(e.currentTarget);
  });
}
$('calisanlar-close').addEventListener('click', () => closeCalisanlar());
document.addEventListener('click', (e) => {
  if (!calisanlarOpen()) return;
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;  // a row re-rendered under the pointer
  if (t.closest('#calisanlar, #live-pill')) return;
  closeCalisanlar(false);
});
document.addEventListener('keydown', (e) => {  // capture: Esc closes the popover before anything else
  if (e.key !== 'Escape' || !calisanlarOpen()) return;
  e.stopImmediatePropagation();
  closeCalisanlar();
}, true);

// --- "Şema" (plan "Sonraki iş (9)" step 1): the org chart from real data (orgSemasi in ofis-sahne.js) — the owner → CEO →
// Genel Müdür → the four managers, the İK ve İdari İşler Müdürü (the support staff) and the Ar-Ge uzmanı → their teams,
// who is in the office, on shift or home, each node's state. textContent
// only; a person's node opens its character card (the actor drawn now, else the node's own minimal one). Rebuilt only
// when its content changed.
let semaFrom = null;
let semaKey = null;
// 'kota': a reviewer stopped by its quota — not at the Otel (only staff who stay there show "otelde")
const SEMA_YER = { ofiste: 'ofiste', nobette: 'nöbette', evde: 'otelde', kota: 'kota doldu', cikiyor: 'çıkıyor' };
function semaOpen() { return !$('sema').hidden; }
function semaDugumu(n) {
  const li = h('li', 'sema-dugum');
  const kart = (prevActors || []).find((a) => a.id === n.aktor) || n.kart;
  const el = h(kart ? 'button' : 'div', `sema-kutu${n.yer ? ` yer-${n.yer}` : ''}`);
  if (kart) el.type = 'button';
  el.append(h('b', null, n.ad));
  if (n.alt) el.append(h('span', 'sema-alt', n.alt));
  if (n.ekip) el.append(h('span', 'sema-ekip', n.ekip)); // a decorative group line ("QA ekibi: 3 kişi · görünüm amaçlı")
  if (n.yer && SEMA_YER[n.yer]) el.append(h('span', 'sema-yer', SEMA_YER[n.yer]));
  if (n.durum) el.append(h('span', 'sema-durum', n.durum));
  if (kart) {
    el.addEventListener('click', () => {
      const r = el.getBoundingClientRect();
      const a = (prevActors || []).find((x) => x.id === n.aktor) || n.kart;
      closeSema(false);
      openActor(a, { x: r.left, y: r.top });
    });
  }
  li.append(el);
  if (n.cocuklar && n.cocuklar.length) {
    const ul = h('ul');
    ul.append(...n.cocuklar.map(semaDugumu));
    li.append(ul);
  }
  return li;
}
function renderSema() {
  if (!semaOpen() || !state) return;
  const agac = orgSemasi(state, Date.now(), prevActors);
  const key = JSON.stringify(agac);
  if (key === semaKey && $('sema-agac').childElementCount) return;
  semaKey = key;
  $('sema-agac').replaceChildren(semaDugumu(agac));
}
function openSema(from) {
  semaFrom = from || null;
  $('sema').hidden = false;
  semaKey = null;
  $('sema-btn').setAttribute('aria-expanded', 'true');
  renderSema();
  $('sema-close').focus();
}
function closeSema(restoreFocus = true) {
  if (!semaOpen()) return;
  $('sema').hidden = true;
  $('sema-btn').setAttribute('aria-expanded', 'false');
  if (restoreFocus && semaFrom) semaFrom.focus();
  semaFrom = null;
}
$('sema-btn').addEventListener('click', (e) => {
  e.stopPropagation();
  if (semaOpen()) closeSema(); else openSema(e.currentTarget);
});
$('sema-close').addEventListener('click', () => closeSema());
document.addEventListener('click', (e) => {
  if (!semaOpen()) return;
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;
  if (t.closest('#sema, #sema-btn')) return;
  closeSema(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !semaOpen()) return;
  e.stopImmediatePropagation();
  closeSema();
}, true);

// decision cards are kept per note so typed text survives re-renders
const askCards = { side: new Map(), wide: new Map(), komuta: new Map() };

function buildAsk(d) {
  const card = h('article', 'ask');
  const meta = h('div', 'ask-meta');
  const dot = h('span', 'avatar-dot');
  dot.style.background = dotColor(d.project);
  const asked = parseTime(d.asked);
  meta.append(dot, h('span', null, `${d.project} · ${asked ? hhmm(asked) : d.asked || ''}`));
  const risk = h('span', 'ask-risk');  // an approval card's risk level (badge)
  meta.append(risk);
  const title = h('div', 'ask-title');
  const warn = h('p', 'ask-warn');  // an open security finding: this card does not look approvable
  warn.setAttribute('role', 'alert');
  const mnot = h('p', 'ask-mudur-not');  // step 4: a manager looks at / answered this question (mudurKarti)
  mnot.hidden = true;
  const q = h('p', 'ask-q');
  const ta = h('textarea', 'input');
  ta.rows = 2;
  ta.maxLength = 4000;
  ta.placeholder = 'Cevabın…';
  ta.setAttribute('aria-label', `${d.project} sorusuna cevap`);
  const evidence = h('div', 'ask-evidence');  // a workflow's approval card: evidence first, the summary last
  const quiz = h('div', 'ask-quiz');  // the optional "Kendini yokla": answers hidden behind "Cevabı göster"
  const secenekler = h('div', 'ask-secenekler');  // the CEO's own question (ceo-sorusu): one button per option
  secenekler.hidden = true;
  const actions = h('div', 'ask-actions');
  const yes = h('button', 'btn btn-soft btn-sm', 'Onayla'); yes.type = 'button';
  const no = h('button', 'btn btn-soft btn-sm', 'Reddet'); no.type = 'button';
  const send = h('button', 'btn btn-primary btn-sm', 'Cevapla'); send.type = 'button';
  const sent = h('span', 'ask-sent', 'Cevap iletildi — CEO notu güncelleyecek.');
  actions.append(yes, no, send);
  card.append(meta, title, warn, mnot, q, evidence, quiz, secenekler, ta, actions, sent);
  const buttons = [yes, no, send];
  const submit = async (text) => {
    if (!text.trim()) { ta.focus(); return; }
    const all = [...buttons, ...secenekler.querySelectorAll('button')];
    all.forEach((b) => { b.disabled = true; });
    const ok = await answer(d.note, text.trim());
    all.forEach((b) => { b.disabled = false; });
    if (ok) { sentLocal.add(d.note); ta.value = ''; renderAsks(); }
  };
  yes.addEventListener('click', () => submit('Onaylıyorum'));
  no.addEventListener('click', () => submit('Hayır'));
  send.addEventListener('click', () => submit(ta.value));
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(ta.value); });
  card.parts = { ta, actions, sent, title, q, evidence, quiz, risk, warn, yes, no, mnot, secenekler, submit };
  return card;
}

// The option buttons of the CEO's own question (ceo-sorusu): "A" + its text; a click sends "A) <text>" through the
// normal answer POST. Rebuilt only when the options change (textContent only).
function renderSecenekler(card, secim) {
  const host = card.parts.secenekler;
  const key = JSON.stringify(secim);
  if (host.dataset.key === key) return;
  host.dataset.key = key;
  host.replaceChildren(...secim.map((o) => {
    const b = h('button', 'btn btn-soft btn-sm ask-secenek');
    b.type = 'button';
    b.append(h('b', null, o.kod), document.createTextNode(` ${o.metin}`));
    b.title = `${o.kod} seçeneğini cevap olarak gönder`;
    b.addEventListener('click', () => card.parts.submit(o.cevap));
    return b;
  }));
}

// "Kendini yokla (isteğe bağlı)": each question with its answer behind a "Cevabı göster" toggle (details/summary,
// textContent only); an opened answer stays open across re-renders. Never required for the approval.
function renderQuiz(host, items) {
  const opened = new Set([...host.querySelectorAll('details[open]')].map((x) => x.dataset.key));
  host.hidden = items.length === 0;
  if (!items.length) { host.replaceChildren(); return; }
  host.replaceChildren(h('div', 'ask-quiz-title', SINAV_BASLIGI), ...items.map((it) => {
    const row = h('div', 'ask-quiz-row');
    const toggle = h('details', 'ask-quiz-answer');
    toggle.dataset.key = it.baslik;
    toggle.open = opened.has(it.baslik);
    toggle.append(h('summary', null, 'Cevabı göster'), h('p', null, it.cevap));
    row.append(h('p', 'ask-quiz-q', `${it.baslik}. ${it.soru}`), toggle);
    return row;
  }));
}

// the cards of the right panel: the owner's decisions, then (step 4) the questions a manager looks at or answered
function askItems() {
  const decisions = state && Array.isArray(state.decisions) ? state.decisions : [];
  const mudurler = state && Array.isArray(state.mudur_kararlari) ? state.mudur_kararlari : [];
  return [...decisions, ...mudurler.map((d) => ({ ...d, _mudur: true }))];
}

function syncAsks(map, host, empty) {
  const decisions = askItems();
  const keep = new Set(decisions.map((d) => d.note));
  for (const [note, card] of map) if (!keep.has(note)) { card.remove(); map.delete(note); }
  for (const d of decisions) {
    let card = map.get(d.note);
    if (!card) { card = buildAsk(d); map.set(d.note, card); }
    card.parts.title.textContent = d.title || d.note;
    const qText = questionBody(d);  // rebuilt only when it changed: the links keep their state between refreshes
    if (card.parts.q.dataset.metin !== qText) { card.parts.q.dataset.metin = qText; linkliEkle(card.parts.q.replaceChildren() || card.parts.q, qText); }
    // risk badge and the open-security warning (text only); Onayla stays clickable but looks secondary: the owner decides
    const isaret = kararIsaretleri(d);
    const mk = d._mudur ? mudurKarti(d) : null;  // a manager card: its badge, the answer, only "Cevapla"
    card.parts.risk.textContent = mk ? mk.rozet : isaret.risk ? isaret.risk.metin : '';
    card.parts.risk.className = `ask-risk ${mk ? mk.sinif : isaret.risk ? isaret.risk.sinif : ''}`;
    card.parts.risk.hidden = !mk && !isaret.risk;
    card.parts.warn.textContent = isaret.uyari;
    card.parts.warn.hidden = !isaret.uyari;
    card.parts.mnot.textContent = mk ? mk.ipucu : '';
    card.parts.mnot.hidden = !mk;
    const secim = mk ? [] : secenekDugmeleri(d);
    renderSecenekler(card, secim);
    card.parts.yes.hidden = !!mk || secim.length > 0;  // the options are the answers; a free text box stays
    card.parts.no.hidden = !!mk || secim.length > 0;
    card.parts.ta.placeholder = mk ? mk.yer : 'Cevabın…';
    card.parts.yes.classList.toggle('is-secondary', !!isaret.uyari);
    const ev = mk ? (mk.cevap ? [{ title: 'Müdürün cevabı', text: mk.cevap }] : []) : kartBolumleri(d.evidence);
    const opened = new Set([...card.parts.evidence.querySelectorAll('details[open]')].map((x) => x.dataset.key));
    const ilk = mk && card.dataset.mudurCevap !== mk.cevap;  // the manager's answer opens once when it arrives
    if (mk) card.dataset.mudurCevap = mk.cevap;
    card.parts.evidence.replaceChildren(...ev.map((e) => {
      const box = h('details', 'ask-ev');
      box.dataset.key = e.title;
      box.open = opened.has(e.title) || (ilk && e.title === 'Müdürün cevabı');
      box.append(h('summary', null, e.title), linkli('pre', 'proof-text', e.text));
      return box;
    }));
    card.parts.evidence.hidden = ev.length === 0;
    renderQuiz(card.parts.quiz, sinavMaddeleri(d.quiz));
    const isSent = d.answer_sent || sentLocal.has(d.note);
    card.parts.ta.hidden = isSent;
    card.parts.actions.hidden = isSent;
    card.parts.secenekler.hidden = isSent || !secim.length;
    card.parts.sent.hidden = !isSent;
    host.appendChild(card); // re-appending keeps the server order
  }
  empty.hidden = decisions.length > 0;
}

function renderAsks() {
  syncAsks(askCards.side, $('ask-list'), $('ask-empty'));
  syncAsks(askCards.wide, $('ask-list-wide'), $('ask-empty-wide'));
  syncAsks(askCards.komuta, $('ask-list-komuta'), $('ask-empty-komuta'));
  const n = state ? state.decisions.length : 0;
  $('ask-count').textContent = n ? String(n) : '';
  $('komuta-ask-count').textContent = n ? String(n) : '';
  $('komuta-karar-sayi').hidden = n === 0;
  $('komuta-karar-sayi').textContent = String(n);
  renderKararBildirimi();
  const bekleyen = seniBekleyenMetni(kararSayisi);
  $('side-bekleyen').textContent = bekleyen;
  $('side-bekleyen').hidden = !bekleyen;
  const rozetKey = JSON.stringify(rozetKararlari().map((d) => [d.note, d.asked]));
  if (rozetKey !== chatRozetKey) { chatRozetKey = rozetKey; renderChat(false); }
  yanPanel();
}

// the CEO's own questions that still wait: their CEO chat line gets the "cevap bekliyor" badge (renderChatBox)
function rozetKararlari() {
  const list = state && online && Array.isArray(state.decisions) ? state.decisions : [];
  return list.filter((d) => d && d.kind === 'ceo-sorusu' && !d.answer_sent && !sentLocal.has(d.note));
}

// The right panel holds only "CEO soruyor" (owner decision 2026-11-13; the approval-backlog and delivery warnings are top-bar
// chips). With no question it collapses (html.yan-bos: --side-w 0, the panel hidden) and the scene is fitted to the
// full width; it comes back with the first question — the owner's or a manager's card (step 4). (yanBos: near `office`.)
function yanPanel() {
  const bos = !askItems().length;
  if (bos === yanBos) return;
  yanBos = bos;
  document.documentElement.classList.toggle('yan-bos', bos);
  if (office) office.resize();
}

// The top bar's decision bell (the owner, 2026-11-12): "N karar bekliyor" next to the live pill while decisions wait for
// the owner (cards answered from the page do not count), the tab title's "(N) " prefix, one gentle pulse when the count
// rises (none on the first render; none under prefers-reduced-motion, see style.css). Text only.
let kararSayisi = 0;
function renderSekmeBasligi() {
  document.title = sekmeBasligi(baseTitle, sekmeSayisi(kararSayisi, ceoOkunmamis, document.hidden));
}
function renderKararBildirimi() {
  const info = kararBildirimi(state && online ? state.decisions : [], sentLocal);
  const bell = $('karar-bildirim');
  bell.hidden = info.sayi === 0;
  $('karar-bildirim-sayi').textContent = info.sayi ? String(info.sayi) : '';
  $('karar-bildirim-metin').textContent = info.metin;
  bell.title = info.baslik;
  bell.setAttribute('aria-label', info.baslik || 'Bekleyen karar yok');
  bell.dataset.note = info.enEski || '';
  kararSayisi = info.sayi;
  renderSekmeBasligi();
  if (kararArtti(kararOnceki, info.sayi)) {
    bell.classList.remove('is-pulse');
    void bell.offsetWidth;  // restart the animation
    bell.classList.add('is-pulse');
  }
  kararOnceki = state ? info.sayi : null;
}
$('karar-bildirim').addEventListener('animationend', (e) => e.currentTarget.classList.remove('is-pulse'));
$('karar-bildirim').addEventListener('click', (e) => {
  const note = e.currentTarget.dataset.note;
  openKomuta(e.currentTarget);
  // the Komuta masası's Kararlar column, the oldest card's answer box focused — after openKomuta's own input focus
  if (note) setTimeout(() => focusDecision(note), 80);
});

function renderFeed() {
  fillFeed($('komuta-feed'), 12);
  renderOlaylar();
}

// The "Son olanlar" tab (the owner, 2026-11-13: moved out of the side panel): the same events as a timeline in the notice
// cards' look — a notice is the chat's own notice card (noticeCard: badge, title, facts, actions, Ayrıntı); every other
// event a card of the same shape with its badge (olayRozeti), its text and its time; a click opens its detail. Drawn
// only while the tab is open (and when it opens).
function renderOlaylar() {
  const box = $('olay-akisi');
  if (!box || $('overlay-olaylar').hidden) return;
  if (!feed.length) { box.replaceChildren(h('li', 'empty', 'Bu sayfa açıldığından beri bir şey olmadı.')); return; }
  box.replaceChildren(...feed.map((item) => {
    const li = h('li', 'olay');
    const once = rel(item.time);
    li.append(h('time', 'olay-zaman', once && once !== hhmm(item.time) ? `${hhmm(item.time)} · ${once}` : hhmm(item.time)));
    if (item.m) { li.append(noticeCard(item.m)); return li; }
    const r = olayRozeti(item.tur);
    const card = h('div', `msg relay notice ${r.tone}`);
    const head = h('div', 'relay-head');
    const badge = h('span', `relay-badge ${r.tone}`);
    badge.append(h('span', 'notice-icon', r.ikon), document.createTextNode(` ${r.etiket}`));
    head.append(badge);
    card.append(head, linkli('div', 'notice-title', item.text));
    if (item.detail) makeClickable(card, () => openDetail(item.detail));
    li.append(card);
    return li;
  }));
}
function fillFeed(ul, max) {
  if (!ul) return;
  ul.replaceChildren();
  if (!feed.length) { ul.appendChild(h('li', 'muted', 'Henüz bir şey olmadı.')); return; }
  for (const item of feed.slice(0, max)) {
    const li = h('li');
    const dot = h('span', 'dot');
    dot.style.background = item.color || '#A79B8C';
    li.append(dot, h('span', 'txt', item.text), h('time', null, rel(item.time)));
    if (item.detail) makeClickable(li, () => openDetail(item.detail));
    ul.appendChild(li);
  }
}
setInterval(renderFeed, 30000);

// --- İşler board (phase 7): Sıradakiler / Devam edenler / Bitenler; a workflow is one card with its steps ---
const BOARD_COLS = ['sirada', 'devam', 'biten'];
const BOARD_EMPTY = { sirada: 'Sırada iş yok.', devam: 'Şu an çalışan iş yok.', biten: 'Henüz biten iş yok.' };

function renderTasks() {
  const tasks = state ? (state.board || state.tasks) : [];
  const cols = boardColumns(tasks, state ? state.workflows : [], 20, state ? state.board_hidden : 0);
  for (const col of BOARD_COLS) {
    const items = cols[col];
    $(`board-${col}`).replaceChildren(...(items.length
      ? items.map((it) => (it.kind === 'task' ? boardCard(it.task) : workflowCard(it)))
      : [h('p', 'empty', BOARD_EMPTY[col])]));
    $(`board-count-${col}`).textContent = items.length ? String(items.length) : '';
  }
  $('board-more').hidden = cols.bitenGizli === 0;
  $('board-more').textContent = `Daha eski ${cols.bitenGizli} biten iş Obsidian'da (OFIS/Isler/Bitenler).`;
}

// One job card: title, project, tier/model, status, budget bars, queue state, escalation mark, workflow step.
function boardCard(t, inWorkflow = false) {
  const card = h('article', inWorkflow ? 'bcard bstep' : 'bcard');
  const head = h('div', 'bcard-head');
  if (inWorkflow) head.append(h('span', 'bcard-step', stepText(t) || 'adım'));
  else {
    const dot = h('span', 'avatar-dot');
    dot.style.background = dotColor(t.project);
    head.append(dot, h('span', 'bcard-project', t.project || '—'));
  }
  head.append(h('span', `badge ${t.status}`, STATUS_TR[t.status] || t.status));
  const title = h('div', 'bcard-title', feedText(t.title, 120) || t.note);
  const esc = escalationText(t);
  if (esc) title.append(h('span', 'esc-mark', esc));
  card.append(head, title);
  const who = [t.tier, calisanMetni(t.model, t.uzmanlik)].filter(Boolean).join(' · ');
  if (who) card.append(h('small', 'task-queue', who));
  const queue = queueText(t);
  if (queue) card.append(h('small', 'task-queue', queue));
  const held = onayBekletmeMetni(t);  // a kod job the dispatcher holds while approval cards pile up
  if (held) card.append(h('small', 'task-queue is-held', held));
  const resumed = kotaDevamMetni(t);  // Step 5: resumed after its quota came back
  if (resumed) card.append(h('small', 'task-queue', resumed));
  const advisor = danismanMetni(t);  // the advisor pilot's arm B / the mapped advisor (bin/danisman.py)
  if (advisor) card.append(h('small', 'task-queue', advisor));
  const yol = yolCizgisi(t, { kompakt: true });  // the job's progress line (web/is-akisi.js)
  if (yol) card.append(yol);
  if (t.status === 'sirada') {
    // nothing spent yet: the limits as one line instead of two empty bars
    const lim = budgetBar(t);
    const text = lim && [lim.money && `kullanım sınırı ${usdText(t.budget)}`, lim.calls && `en çok ${t.max_calls} çağrı`]
      .filter(Boolean).join(' · ');
    if (text) card.append(h('small', 'task-queue', text));
  } else {
    const bars = budgetBars(budgetBar(t));
    if (bars) card.append(bars);
  }
  makeClickable(card, () => openDetail({ kind: 'task', note: t.note }));
  return card;
}

function workflowCard(g) {
  const card = h('article', 'bcard bflow');
  const first = g.tasks[0] || {};
  const head = h('div', 'bcard-head');
  const dot = h('span', 'avatar-dot');
  dot.style.background = dotColor(first.project);
  head.append(dot, h('span', 'bcard-project', `${first.project || '—'} · akış`));
  card.append(head, h('div', 'bcard-title', feedText(g.title, 120)));
  if (g.progress) card.append(h('small', 'task-queue', g.progress));
  const steps = h('div', 'bflow-steps');
  steps.append(...g.tasks.map((t) => boardCard(t, true)));
  card.append(steps);
  return card;
}

// The budget bars of a card: money and model calls against the job's limits; red once a limit is passed.
function budgetBars(bar) {
  if (!bar) return null;
  const box = h('div', 'bbars');
  for (const [label, part] of [['Kullanım sınırı', bar.money], ['Çağrı', bar.calls]]) {
    if (!part) continue;
    const row = h('div', part.over ? 'bbar is-over' : 'bbar');
    row.title = `${label}: ${part.text}`;
    const track = h('div', 'usage-track');
    const fill = h('div', 'usage-fill');
    fill.style.width = `${Math.max(part.pct, part.pct > 0 ? 2 : 0)}%`;
    track.appendChild(fill);
    row.append(h('span', 'bbar-label', label), track, h('span', 'bbar-text', part.text));
    box.appendChild(row);
  }
  return box;
}

// --- Raporlar (phase 7): GET /api/raporlar, one report through the detail modal ---
function fmtDay(v) {
  const d = parseTime(v);
  return d ? `${d.toLocaleDateString('tr-TR')} ${hhmm(d)}` : '';
}

async function loadReports() {
  const list = $('report-list');
  if (!list.childElementCount) list.replaceChildren(h('p', 'muted', 'Raporlar okunuyor…'));
  const res = await getJson('/api/raporlar');
  if (res.status !== 200 || !res.data) {
    list.replaceChildren(h('p', 'empty', res.status === 0 ? 'Sunucu kapalı.' : 'Raporlar okunamadı.'));
    $('report-empty').hidden = true;
    return;
  }
  const reports = res.data.raporlar || [];
  list.replaceChildren(...reports.map(reportCard));
  $('report-empty').hidden = reports.length > 0;
}

function reportCard(r) {
  const card = h('article', 'rcard');
  const kicker = [r.proje, fmtDay(r.bitis || r.yazildi), r.tur === 'akis' ? 'akış' : 'grup',
    r.surum > 1 ? `sürüm ${r.surum}` : ''].filter(Boolean).join(' · ');
  card.append(h('p', 'rcard-kicker', kicker), h('div', 'bcard-title', r.baslik || r.grup),
    h('p', 'rcard-line', reportSummaryText(r)),
    h('p', 'rcard-line', `Toplam kullanım: ${reportCostText(r)} · Doğrulanmış iş başına: ${reportVerifiedText(r)}`));
  if (r.acik) card.append(h('p', 'rcard-line rcard-open', `Açık kalan: ${r.acik}`));
  makeClickable(card, () => openDetail({ kind: 'report', grup: r.grup }));
  return card;
}

async function renderReport(grup) {
  const seq = ++detailSeq;
  showDetail('Rapor', 'Yükleniyor…', [h('p', 'empty-note', 'Rapor okunuyor…')]);
  const res = await getJson(`/api/rapor?grup=${encodeURIComponent(grup)}`);
  if (seq !== detailSeq) return;
  const r = res.status === 200 ? res.data : null;
  if (!r) { showDetail('Rapor', 'Rapor bulunamadı', [h('p', 'empty-note', 'Bu rapor okunamadı ya da silinmiş.')]); return; }
  const nodes = [];
  let skippedTitle = false;
  for (const b of reportBlocks(r.metin)) {
    if (b.type === 'h' && b.level === 1 && !skippedTitle) { skippedTitle = true; continue; }  // the modal title
    if (b.type === 'h') nodes.push(h('h3', null, b.text));
    else if (b.type === 'quote') nodes.push(linkli('p', 'empty-note report-quote', b.linkli ?? b.text));
    else if (b.type === 'p') nodes.push(linkli('p', 'report-p', b.linkli ?? b.text));
    else if (b.type === 'list') {
      const ul = h('ul', 'report-list-items');
      ul.append(...b.items.map((item, i) => linkli('li', null, (b.linkli || [])[i] ?? item)));
      nodes.push(ul);
    } else if (b.type === 'table') nodes.push(reportTable(b));
  }
  showDetail([document.createTextNode(`${r.proje || 'rapor'} · ${r.grup}`)], r.baslik || r.grup, nodes);
}

function reportTable(b) {
  const wrap = h('div', 'table-wrap');
  const table = h('table', 'tasks report-table');
  const head = h('tr');
  head.append(...b.head.map((c) => h('th', null, c)));
  const thead = h('thead');
  thead.appendChild(head);
  const body = h('tbody');
  for (const row of b.rows) {
    const tr = h('tr');
    for (const cell of row) {
      const td = h('td');
      if (cell.note) {
        const a = h('span', 'link', cell.text);  // a job of the group: opens its detail (← Geri returns here)
        makeClickable(a, () => openDetail({ kind: 'task', note: cell.note }));
        td.appendChild(a);
      } else linkliEkle(td, cell.linkli ?? cell.text);
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  table.append(thead, body);
  wrap.appendChild(table);
  return wrap;
}

// --- Kalite (phase 7): GET /api/kalite — the scorecard numbers per project × tier × model and per model ---
const MAIN_COL = QUALITY_HEAD.indexOf('Doğrulanmış iş başına');

async function loadQuality() {
  const res = await getJson('/api/kalite');
  const q = res.status === 200 && res.data ? res.data : null;
  const stats = $('quality-stats');
  if (!q) {
    stats.replaceChildren(h('p', 'empty', res.status === 0 ? 'Sunucu kapalı.' : 'Karne okunamadı.'));
    return;
  }
  const t = q.toplam;
  $('quality-empty').hidden = !!t;
  stats.replaceChildren(...kaliteKutulari(t).map((k) => statTile(k.etiket, k.deger, k.ipucu, k.ana)));
  fillQualityTable($('quality-head'), $('quality-body'), QUALITY_HEAD, (q.satirlar || []).map(qualityCells), MAIN_COL);
  fillQualityTable($('quality-model-head'), $('quality-models'), QUALITY_HEAD.slice(2),
    (q.modeller || []).map((m) => qualityCells({ ...m, proje: '', katman: '' }).slice(2)), MAIN_COL - 2);
  renderModelChoice(q.model_secimi || {});
}

// Phase 8: open model cards, running pilots and the effective mapping (bin/model_secimi.py).
function renderModelChoice(ms) {
  const items = [...(ms.oneriler || []).map(modelCardText), ...(ms.pilotlar || []).map(pilotText),
    ...danismanPilotuSatirlari(ms.danisman)];  // the advisor pilot (bin/danisman.py)
  $('model-cards').replaceChildren(...(items.length ? items.map((t) => h('li', null, t))
    : [h('li', 'muted', 'Açık kadro önerisi ya da deneme yok.')]));
  fillQualityTable($('mapping-head'), $('mapping-body'), MAPPING_HEAD, (ms.eslesme || []).map(mappingCells), -1);
}

function statTile(label, value, hint, main = false) {
  const tile = h('div', main ? 'stat is-main' : 'stat');
  tile.append(h('span', 'stat-label', label), h('strong', 'stat-value', value), h('span', 'stat-hint', hint));
  return tile;
}

function fillQualityTable(headRow, body, head, rows, mainCol) {
  headRow.replaceChildren(...head.map((c, i) => h('th', i === mainCol ? 'is-main' : null, c)));
  body.replaceChildren(...rows.map((cells) => {
    const tr = h('tr');
    tr.append(...cells.map((c, i) => h('td', i === mainCol ? 'is-main' : null, c)));
    return tr;
  }));
}

function selectRoom(name) {
  selected = name;
  if (office) office.select(name);
  renderRoomCard();
}

function renderRoomCard() {
  const card = $('room-card');
  if (!selected || !state) { card.hidden = true; return; }
  const tasksUl = $('room-tasks');
  tasksUl.replaceChildren();
  if (selected === CEO) {
    const c = state.ceo;
    $('room-dot').style.background = '#F2784B';
    $('room-name').textContent = 'CEO';
    $('room-status').className = `badge ${c.state}`;
    $('room-status').textContent = STATUS_TR[c.state] || c.state;
    $('room-tool').textContent = toolText(c.current_tool, '—');
    $('room-tokens').textContent = `${fmtUsage(c.usage_today)} token · ~${fmtUsd(c.cost_today || 0)}`;
    $('room-sessions').textContent = c.queue ? `sırada ${c.queue} mesaj` : (c.session_id ? c.session_id.slice(0, 8) : '—');
    tasksUl.appendChild(h('li', 'muted', 'CEO işleri dağıtır, soruları sana getirir.'));
  } else {
    const p = state.projects.find((x) => x.name === selected);
    if (!p) { card.hidden = true; return; }
    $('room-dot').style.background = dotColor(p.name);
    $('room-name').textContent = p.name;
    $('room-status').className = `badge ${p.status}`;
    $('room-status').textContent = STATUS_TR[p.status] || p.status;
    $('room-tool').textContent = p.last_tool ? `${p.last_tool.name}${p.last_tool.target ? ' · ' + p.last_tool.target : ''}` : '—';
    $('room-tokens').textContent = `${fmtUsage(p.usage_today)} token · ~${fmtUsd(p.cost_today || 0)}`;
    $('room-sessions').textContent = p.sessions ? `${p.sessions} açık oturum` : 'açık oturum yok';
    if (!p.tasks.length) tasksUl.appendChild(h('li', 'muted', 'Bu projede henüz iş yok.'));
    for (const t of p.tasks) {
      const li = h('li');
      const label = h('span', null, feedText(t.title, 70) || t.note);
      const esc = escalationText(t);
      if (esc) label.append(h('span', 'esc-mark', esc));
      const spend = budgetText(t);
      if (spend) label.append(h('small', 'task-budget', spend));
      const queue = queueText(t);
      if (queue) label.append(h('small', 'task-queue', queue));
      const held = onayBekletmeMetni(t);
      if (held) label.append(h('small', 'task-queue is-held', held));
      li.append(label, h('span', `badge ${t.status}`, STATUS_TR[t.status] || t.status));
      makeClickable(li, () => openDetail({ kind: 'task', note: t.note }));
      tasksUl.appendChild(li);
    }
  }
  card.hidden = false;
}
$('room-close').addEventListener('click', () => selectRoom(null));

// --- chat drawer ---
function renderChatMeta() {
  if (!state) return;
  const c = state.ceo;
  const kapaniyor = c.state === 'busy' && !!c.tur_kapaniyor;
  $('typing').hidden = c.state !== 'busy' || kapaniyor;
  $('queue-note').textContent = c.queue ? `sırada: ${c.queue} mesaj` : '';
  const bits = [`CEO · ${kapaniyor ? CEO_KAPANIYOR : (STATUS_TR[c.state] || c.state)}`, `bugün ${fmtUsage(c.usage_today)} token`];
  if (c.state === 'busy' && !kapaniyor && c.current_tool) bits.push(`şu an: ${c.current_tool.name}`);
  const ceoKey = `${c.state}|${kapaniyor}`;
  if (ceoKey !== turCeoKey) { turCeoKey = ceoKey; loadTurlar(); }
  if (c.last_error) bits.push('son hata: ' + c.last_error.slice(0, 80));
  $('drawer-sub').textContent = bits.join(' · ');
  $('komuta-queue-note').textContent = c.queue ? `sırada: ${c.queue} mesaj` : '';
}

// Minimal, safe Markdown for CEO replies: **bold**, `code`, "- " bullets, blank-line paragraphs.
// Builds DOM nodes with textContent only; never parses data as HTML.
function inlineMd(parent, text) {
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) linkliEkle(parent, text.slice(last, m.index));
    const tok = m[0];
    parent.appendChild(tok.startsWith('**') ? linkli('strong', null, tok.slice(2, -2)) : h('code', null, tok.slice(1, -1)));
    last = m.index + tok.length;
  }
  if (last < text.length) linkliEkle(parent, text.slice(last));
}

function mdBlock(text) {
  const root = h('div', 'md');
  let list = null;
  let para = null;
  for (const raw of (text || '').split('\n')) {
    const line = raw.replace(/\s+$/, '');
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      para = null;
      if (!list) { list = h('ul'); root.appendChild(list); }
      const li = h('li');
      inlineMd(li, bullet[1]);
      list.appendChild(li);
    } else if (!line.trim()) {
      list = null; para = null;
    } else {
      list = null;
      if (!para) { para = h('p'); root.appendChild(para); } else para.appendChild(h('br'));
      inlineMd(para, line);
    }
  }
  return root;
}

// A project session's message relayed into the CEO conversation ("[ornek-uygulama] DONE: ..."), shown as a card.
const RELAY_KIND = { DONE: ['Bitti', 'done'], 'BİTTİ': ['Bitti', 'done'], BITTI: ['Bitti', 'done'],
  BLOCKED: ['Tıkandı', 'blocked'], 'TIKANDI': ['Tıkandı', 'blocked'] };
const expandedRelays = new Set();  // survives re-renders: renderChat rebuilds the list every time

function parseRelay(m) {
  const body = (m.text || '').replace(/^[^:\n]+:\s*/, '');  // drop "ofis-ornek-uygulama-...: "
  const match = body.match(/^\[([^\]\n]{1,40})\]\s*(?:([A-Za-zİıŞşÇçĞğÖöÜü]+):)?\s*([\s\S]*)$/);
  if (!match) return { project: m.from || 'proje', label: 'Mesaj', tone: 'info', text: body };
  const [, project, kindWord, rest] = match;
  const kind = kindWord && RELAY_KIND[kindWord.toLocaleUpperCase('tr-TR')];
  if (kind) return { project, label: kind[0], tone: kind[1], text: rest };
  const text = kindWord ? `${kindWord}: ${rest}` : rest;
  return { project, label: /\?\s*$/.test(text.split('\n')[0]) ? 'Soru' : 'Mesaj', tone: 'info', text };
}

function relayCard(m) {
  const r = parseRelay(m);
  const key = chatKey(m);
  const card = h('div', 'msg relay');
  const head = h('div', 'relay-head');
  head.appendChild(h('span', 'relay-project', r.project));
  head.appendChild(h('span', `relay-badge ${r.tone}`, r.label));
  head.appendChild(h('time', null, hhmm(parseTime(m.time))));
  card.appendChild(head);
  const body = linkli('div', 'relay-body', r.text.trim());
  const long = r.text.length > 280;
  if (long && !expandedRelays.has(key)) body.classList.add('is-clamped');
  card.appendChild(body);
  if (long) {
    const more = h('button', 'relay-more', expandedRelays.has(key) ? 'Daha az göster' : 'Devamını göster');
    more.type = 'button';
    more.addEventListener('click', () => {
      if (expandedRelays.has(key)) expandedRelays.delete(key); else expandedRelays.add(key);
      renderChat(false);
    });
    card.appendChild(more);
  }
  if (m.from) card.appendChild(h('span', 'relay-session', m.from));
  return card;
}

// An "[Ofis · sistem]" notice: a compact card (owner decision 2026-11-13) — a kind badge with its icon, one plain title line, the
// key facts as a small two-column table, the actions (Cevapla, İşi aç, Notu aç) and the notice itself only behind a
// collapsed "Ayrıntı" toggle. The parts written only for the CEO are never shown (bildirimKarti hides them); the CEO's
// plain reply follows as its own message. textContent only; [[links]] open in Obsidian.
const openRaw = new Set();  // chat keys whose "Ayrıntı" is open: survives the re-render of the chat
function noticeCard(m) {
  const c = bildirimKarti(m.text);
  const key = chatKey(m);
  const card = h('div', `msg relay notice ${c.tone} notice-${c.tur}`);
  const head = h('div', 'relay-head');
  const badge = h('span', `relay-badge ${c.tone}`);
  badge.append(h('span', 'notice-icon', c.ikon), document.createTextNode(` ${c.etiket}`));
  head.append(h('span', 'relay-project', 'Ofis'), badge, h('time', null, hhmm(parseTime(m.time))));
  card.append(head, linkli('div', 'notice-title', c.baslik, c.klasor));
  if (c.satirlar.length) {
    const facts = h('dl', 'notice-facts');
    for (const [label, value] of c.satirlar) {
      const dd = value === c.not ? h('dd') : linkli('dd', null, value, c.klasor);
      if (value === c.not) dd.appendChild(notLinki(c.not, value, c.klasor));
      facts.append(h('dt', null, label), dd);
    }
    card.appendChild(facts);
  }
  card.appendChild(noticeActions(m, c));
  if (c.teknik) { // the project's own report, structured and folded (the owner, 2026-11-14: the plain blob was unreadable)
    const raw = h('details', 'notice-raw');
    raw.open = openRaw.has(key);
    raw.addEventListener('toggle', () => { if (raw.open) openRaw.add(key); else openRaw.delete(key); });
    raw.append(h('summary', null, c.teknikBaslik), raporDugumu(c.teknik, document));
    card.appendChild(raw);
  } else if (c.ham) {
    const raw = h('details', 'notice-raw');
    raw.open = openRaw.has(key);
    raw.addEventListener('toggle', () => { if (raw.open) openRaw.add(key); else openRaw.delete(key); });
    raw.append(h('summary', null, 'Ayrıntı'), linkli('pre', 'notice-raw-text', c.ham, c.klasor));
    card.appendChild(raw);
  }
  return card;
}

// The notice's actions: "Cevapla" for a pending decision it names (jumps to that card), "İşi aç" for its job, "Notu aç"
// for the Obsidian note it names. Only the server's own words are matched (the title line and the parsed fields), never
// the quoted project text.
function noticeActions(m, c) {
  const first = String(m.text || '').split('\n')[0];
  const e = bildirimEylemleri(`${first} ${c.karar} ${c.is}`, askItems(),
    state ? [...(state.board || []), ...state.tasks] : []);
  const row = h('div', 'notice-actions');
  if (e.karar) {
    const reply = h('button', 'btn btn-primary btn-sm', 'Cevapla');
    reply.type = 'button';
    reply.addEventListener('click', () => { if (!komutaOpen()) openKomuta(); focusDecision(e.karar); });
    row.appendChild(reply);
  }
  const job = e.is || (c.is ? `${c.is}.md` : '');
  if (job) {
    const open = h('button', 'btn btn-soft btn-sm', 'İşi aç');
    open.type = 'button';
    open.addEventListener('click', () => openDetail({ kind: 'task', note: job }));
    row.appendChild(open);
  }
  if (c.not) row.appendChild(notLinki(c.not, 'Notu aç', c.klasor, 'btn btn-soft btn-sm obs-link'));
  row.hidden = !row.childElementCount;
  return row;
}

function renderChat(grew) {
  renderChatBox($('messages'), grew, false);
  if (komutaOpen()) renderChatBox($('komuta-messages'), grew, true);
}

function renderChatBox(box, grew, eylemli) {
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  const keepScroll = box.scrollTop;
  box.replaceChildren();
  if (!chat.length && !optimistic.length) box.appendChild(h('p', 'msg system', 'Henüz konuşma yok. CEO\'ya ilk mesajını yaz.'));
  const altlar = turAltlari(chat, turlar);
  const rozetler = cevapBekleyenRozetleri(chat, rozetKararlari());
  chat.forEach((m, i) => {
    if (m.role === 'system' && m.kind === 'notice') { box.appendChild(noticeCard(m)); return; }
    if (m.role === 'system' && m.from) { box.appendChild(relayCard(m)); return; }
    const role = sahipSatiri(m) ? 'sahip' : m.role === 'ceo' ? 'ceo' : 'system';
    const b = h('div', `msg ${role}`);
    if (role === 'ceo') b.dataset.anahtar = chatKey(m);
    if (m.note) b.appendChild(h('span', 'note-ref', `Karar cevabı · ${m.note}`));
    // a request the owner spoke to Jarvis (bin/jarvis.py is-ekle): his own line, marked with the channel
    if (m.kanal) b.appendChild(h('span', 'note-ref', m.proje ? `${m.kanal} · ${m.proje}` : m.kanal));
    b.appendChild(role === 'ceo' ? mdBlock(m.text) : document.createTextNode(m.text || ''));
    for (const r of role === 'ceo' ? rozetler[i] || [] : []) {
      // amber "cevap bekliyor": opens the card in the Komuta masası's Kararlar column (like the bell)
      const rz = h('button', 'msg-bekliyor', 'cevap bekliyor');
      rz.type = 'button';
      rz.title = `Kararını kartta bekliyor: ${r.baslik}`;
      rz.addEventListener('click', (e) => { openKomuta(e.currentTarget); setTimeout(() => focusDecision(r.note), 80); });
      b.appendChild(rz);
    }
    if (role !== 'system') b.appendChild(h('time', null, hhmm(parseTime(m.time))));
    const alt = altlar[i] ? turAlti(altlar[i]) : null;
    if (alt) b.appendChild(alt);
    box.appendChild(b);
  });
  for (const o of optimistic) {
    const b = h('div', 'msg sahip pending');
    b.appendChild(document.createTextNode(o.text));
    b.appendChild(h('time', null, o.queued ? 'sırada' : 'iletildi'));
    box.appendChild(b);
  }
  box.scrollTop = grew || nearBottom ? box.scrollHeight : keepScroll;
}

function openDrawer() {
  ceoOkundu();
  $('drawer').classList.add('is-open');
  $('drawer').setAttribute('aria-hidden', 'false');
  $('scrim').hidden = false;
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
  setTimeout(() => $('drawer-input').focus(), 200);
}
function closeDrawer() {
  $('drawer').classList.remove('is-open');
  $('drawer').setAttribute('aria-hidden', 'true');
  $('scrim').hidden = true;
}

let toastTimer = null;
function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3600);
}

function explain(status, data) {
  if (status === 409) return 'CEO\'ya ulaşılamadı. ' + (data.error || '');
  if (status === 403) return 'İstek reddedildi; sayfayı yenile.';
  if (status === 0) return 'Sunucu kapalı.';
  return data.error || `Hata (${status}).`;
}

async function sendChat(text) {
  text = text.trim();
  if (!text) return false;
  if (text.length > 4000) { toast('Mesaj en fazla 4000 karakter olabilir.'); return false; }
  let res;
  try { res = await post('/api/chat', { text }); } catch { res = { status: 0, data: {} }; }
  if (res.status !== 202) { toast(explain(res.status, res.data)); return false; }
  const queued = res.data.status === 'queued';
  if (!demo) optimistic.push({ text, queued });
  if (queued) toast('CEO meşgul; mesajın sıraya alındı.');
  renderChat(true);
  return true;
}

// true when the card should show "cevap iletildi" (also when the server says the first answer already went)
async function answer(note, text) {
  let res;
  try { res = await post('/api/answer', { note, answer: text }); } catch { res = { status: 0, data: {} }; }
  const out = answerResult(res.status, res.data || {});
  toast(out.text);
  return out.sent;
}

$('open-chat-top').addEventListener('click', () => openKomuta());
$('drawer-close').addEventListener('click', closeDrawer);
$('scrim').addEventListener('click', closeDrawer);
$('drawer-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const ta = $('drawer-input');
  const btn = e.target.querySelector('button[type=submit]');
  btn.disabled = true;
  if (await sendChat(ta.value)) ta.value = '';
  btn.disabled = false;
  ta.focus();
});
$('drawer-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('drawer-form').requestSubmit(); }
});

// --- Komuta masası: the big CEO window (the owner, 2026-11-11). Three columns — "Şu an" (jobs per project, reviewers),
// the chat (the same conversation as the drawer: one `chat` array, no polling of its own besides the CEO's steps),
// pending decisions with the grouped Çalışanlar list, today's spending and "Son olanlar". Narrow: three tabs. While it
// is open the 3D frames stop and the scene's labels are hidden. Text only (textContent), keyboard reachable, focus
// stays inside (and inside the task sheet opened over it). ---
let komutaFrom = null;      // what had focus before it opened (focus goes back there)
let baglam = [];            // context chips: [{note, baslik}] -> "İlgili: [[note]]" under the next message
let adim = null;            // the last GET /api/ceo/adimlar
let adimTimer = null;
let adimSeq = 0;
let suAnKey = '';
const ADIM_ARALIGI = 3000;  // ms between step reads while the window is open
function komutaOpen() { return !$('komuta').hidden; }

function openKomuta(from) {
  if (komutaOpen()) { $('komuta-input').focus(); return; }
  komutaFrom = from || document.activeElement;
  ceoOkundu();
  if ($('drawer').classList.contains('is-open')) closeDrawer();
  closeCalisanlar(false);
  $('komuta').hidden = false;
  document.body.classList.add('komuta-acik');
  if (office) { office.setPaused(true); office.setLabelsHidden(true); }
  suAnKey = '';
  renderKomuta();
  renderChatBox($('komuta-messages'), true, true);
  loadAdimlar();
  clearInterval(adimTimer);
  adimTimer = setInterval(loadAdimlar, ADIM_ARALIGI);
  window.scrollTo(0, 0);
  setTimeout(() => $('komuta-input').focus({ preventScroll: true }), 50);
}

function closeKomuta() {
  if (!komutaOpen()) return;
  if (!$('detail').hidden && $('detail').classList.contains('in-komuta')) closeDetail();
  $('komuta').hidden = true;
  document.body.classList.remove('komuta-acik');
  clearInterval(adimTimer);
  adimTimer = null;
  adimSeq++;
  if (office) { office.setPaused(false); office.setLabelsHidden(document.body.classList.contains('panel-acik')); }
  if (state && sahneGorunur()) renderScene(); // catch up at once (the refresh skipped while it was open)
  if (komutaFrom && komutaFrom.isConnected) komutaFrom.focus();
  komutaFrom = null;
}

async function loadAdimlar() {
  const seq = ++adimSeq;
  const res = await getJson('/api/ceo/adimlar');
  if (seq !== adimSeq || !komutaOpen()) return;
  adim = res.status === 200 && res.data && Array.isArray(res.data.adimlar) ? res.data : null;
  renderAdimlar();
}

function renderAdimlar() {
  const c = state ? state.ceo : null;
  $('ceo-simdi').textContent = online ? ceoSimdiMetni(c, adim) : 'CEO şu an: sunucu kapalı';
  $('ceo-simdi').classList.toggle('is-busy', !!c && c.state === 'busy');
  const list = adim ? adim.adimlar : [];
  $('ceo-adimlar-sayi').textContent = list.length ? `(${list.length})` : '';
  $('ceo-adim-list').replaceChildren(...(list.length ? list.map((a) => {
    const li = h('li');
    li.append(h('time', null, hhmm(parseTime(a.zaman))), h('span', null, adimMetni(a)));
    return li;
  }) : [h('li', 'muted', adim ? 'Henüz bir adım yok.' : 'Adımlar okunuyor…')]));
}

// "Şu an": per project the active jobs, workflow progress and the queue; reviewers and the hakem apart. Rebuilt only
// when a text changes (Süre every minute); the focused row keeps its focus across a rebuild.
function renderSuAn() {
  const g = suAnGruplari(state, Date.now());
  const key = JSON.stringify(g);
  if (key === suAnKey) return;
  suAnKey = key;
  const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.suan : null;
  const nodes = [];
  for (const p of g.projeler) {
    const box = h('section', 'suan-proje');
    const head = h('div', 'suan-proje-head');
    const dot = h('span', 'avatar-dot');
    dot.style.background = dotColor(p.proje);
    head.append(dot, h('strong', null, p.proje));
    const sira = siraMetni(p);
    if (sira) head.append(h('small', 'suan-sira', sira));
    box.appendChild(head);
    for (const w of p.akislar) box.appendChild(h('p', 'suan-akis', `Akış: ${feedText(w.baslik, 60)} · ${w.ilerleme || 'sürüyor'}`));
    for (const it of p.isler) box.appendChild(suAnRow(it));
    nodes.push(box);
  }
  if (g.denetim.length) {
    const box = h('section', 'suan-proje suan-denetim');
    box.appendChild(h('div', 'suan-proje-head', 'Denetim'));
    for (const d of g.denetim) {
      box.appendChild(suAnRow({ id: d.id, baslik: d.is || 'inceleme', calisan: d.calisan, durum: d.durum, sure: d.sure,
        calisan_ipucu: d.calisan_ipucu, harcama: '', yardimci: '', adim: '', note: d.note }));
    }
    nodes.push(box);
  }
  $('suan-list').replaceChildren(...nodes);
  $('suan-empty').hidden = !g.bos;
  if (focused) {
    const again = $('suan-list').querySelector(`[data-suan="${CSS.escape(focused)}"]`);
    if (again) again.focus();
  }
}

function suAnRow(it) {
  const row = h('article', 'suan-is');
  row.dataset.suan = it.id;
  row.append(h('div', 'suan-is-title', feedText(it.baslik, 90)));
  row.append(h('div', 'suan-is-meta', [it.calisan, it.durum, it.sure].filter(Boolean).join(' · ')));
  row.title = [it.calisan_ipucu, it.note ? 'Ayrıntıyı aç ve mesaja bağlam olarak ekle' : ''].filter(Boolean).join(' — ');
  const extra = [it.adim, it.harcama, it.yardimci].filter(Boolean).join(' · ');
  if (extra) row.append(h('div', 'suan-is-extra', extra));
  if (it.note) {
    makeClickable(row, () => {
      baglam = baglamEkle(baglam, { note: it.note, baslik: it.baslik });
      renderBaglam();
      openDetail({ kind: 'task', note: it.note });
    });
  }
  return row;
}

function renderBaglam() {
  const host = $('baglam-list');
  host.replaceChildren(...baglam.map((c) => {
    const chip = h('button', 'baglam-chip');
    chip.type = 'button';
    chip.append(h('span', null, baglamEtiketi(c)), h('span', 'baglam-x', '×'));
    chip.setAttribute('aria-label', `${baglamEtiketi(c)} — bağlamdan çıkar`);
    chip.addEventListener('click', () => { baglam = baglamCikar(baglam, c.note); renderBaglam(); $('komuta-input').focus(); });
    return chip;
  }));
  host.hidden = baglam.length === 0;
  $('komuta-input').maxLength = metinSiniri(baglam);  // the chip line counts toward the 4000 characters
}

function renderKomuta() {
  if (!komutaOpen()) return;
  renderSuAn();
  renderAdimlar();
  const c = state ? state.ceo : null;
  const sira = siradaGostergesi(c);
  $('komuta-sirada').textContent = sira;
  $('komuta-sirada').hidden = !sira;
  $('komuta-harcama').textContent = state ? bugunkuHarcama(state) : '—';
  $('komuta-harcama').title = 'API fiyatıyla karşılığı; abonelikte para ödenmez';
}

// "Cevapla" on a notice: the decision's card in the right column (the Kararlar tab on a narrow screen), its box focused.
function focusDecision(note) {
  setKomutaSekme('kararlar');
  const card = askCards.komuta.get(note);
  if (!card) { toast('Bu karar artık beklemiyor.'); return; }
  card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  card.classList.add('is-flash');
  setTimeout(() => card.classList.remove('is-flash'), 1600);
  if (!card.parts.ta.hidden) card.parts.ta.focus();
}

function setKomutaSekme(sekme) {
  $('komuta-cols').dataset.sekme = sekme;
  for (const b of document.querySelectorAll('.komuta-tab')) {
    const on = b.dataset.sekme === sekme;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', String(on));
    b.tabIndex = on ? 0 : -1;
  }
  if (sekme === 'sohbet') { const box = $('komuta-messages'); box.scrollTop = box.scrollHeight; }
}
for (const b of document.querySelectorAll('.komuta-tab')) {
  b.addEventListener('click', () => setKomutaSekme(b.dataset.sekme));
  b.addEventListener('keydown', (e) => {  // arrow keys move between the tabs
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const tabs = [...document.querySelectorAll('.komuta-tab')];
    const i = tabs.indexOf(b) + (e.key === 'ArrowRight' ? 1 : -1);
    const next = tabs[(i + tabs.length) % tabs.length];
    setKomutaSekme(next.dataset.sekme);
    next.focus();
    e.preventDefault();
  });
}

// quick questions go into the composer (the owner sends them himself: a click never costs a CEO turn by accident)
$('hazir-sorular').replaceChildren(...HAZIR_SORULAR.map((q) => {
  const b = h('button', 'hazir-soru', q);
  b.type = 'button';
  b.addEventListener('click', () => { const ta = $('komuta-input'); ta.value = q; ta.focus(); });
  return b;
}));
renderBaglam();

$('komuta-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const ta = $('komuta-input');
  const btn = e.target.querySelector('button[type=submit]');
  const text = mesajMetni(ta.value, baglam);
  if (!text) { ta.focus(); return; }
  if (text.length > 4000) { toast('Mesaj, bağlam satırıyla birlikte en çok 4000 karakter olabilir.'); return; }
  btn.disabled = true;
  if (await sendChat(text)) { ta.value = ''; baglam = []; renderBaglam(); }
  btn.disabled = false;
  ta.focus();
});
$('komuta-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('komuta-form').requestSubmit(); }
});
$('komuta-close').addEventListener('click', () => closeKomuta());
// "Duyuru yap" (the owner's announcement to every office session): POST /api/duyuru with the page token like every POST
$('duyuru-sure-sec').addEventListener('change', () => { $('duyuru-tarih').hidden = $('duyuru-sure-sec').value !== 'tarih'; });
$('duyuru-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const ta = $('duyuru-metin');
  const btn = $('duyuru-gonder');
  const g = duyuruGovdesi(ta.value, $('duyuru-sure-sec').value, $('duyuru-tarih').value);
  if (g.hata) { toast(g.hata); ta.focus(); return; }
  btn.disabled = true;
  let r;
  try { r = await post('/api/duyuru', g.govde); } catch { r = { status: 0, data: {} }; }
  btn.disabled = false;
  if (r.status === 202) {
    ta.value = '';
    $('duyuru-durum').textContent = duyuruSonucu(r.data);
  } else {
    toast((r.data && r.data.error) || 'Duyuru gönderilemedi.');
  }
});
// "Yakala": a link (http/https; the host punycoded by URL) or one small file (base64) -> POST /api/yakala
function dosyaBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => { const v = String(r.result || ''); resolve(v.slice(v.indexOf(',') + 1)); };
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}
$('yakala-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const y = (state && state.yakala) || {};
  const url = $('yakala-url').value.trim();
  const file = $('yakala-dosya').files && $('yakala-dosya').files[0];
  const govde = { not: $('yakala-not').value.trim().slice(0, 300) };
  if (!!url === !!file) { toast('Ya bir bağlantı ya da bir dosya ver (ikisinden biri).'); return; }
  if (url) {
    let u;
    try { u = new URL(url); } catch { u = null; }
    if (!u || !['http:', 'https:'].includes(u.protocol)) { toast('Yalnız http ve https bağlantıları yakalanır.'); return; }
    govde.url = u.href;
  } else {
    const mb = Number(y.dosya_mb) || 2;
    if (file.size > mb * 1024 * 1024) { toast(`Dosya en çok ${mb} MB olabilir.`); return; }
    if (!/\.(txt|md|markdown|pdf)$/i.test(file.name)) { toast('Yalnız .txt, .md ve .pdf dosyaları yakalanır.'); return; }
    try { govde.dosya = await dosyaBase64(file); } catch { toast('Dosya okunamadı.'); return; }
    govde.dosya_adi = file.name.slice(0, 200);
  }
  const btn = $('yakala-gonder');
  btn.disabled = true;
  let r;
  try { r = await post('/api/yakala', govde); } catch { r = { status: 0, data: {} }; }
  btn.disabled = false;
  if (r.status === 202) {
    $('yakala-url').value = '';
    $('yakala-not').value = '';
    $('yakala-dosya').value = '';
    const d = r.data || {};
    $('yakala-durum').textContent = d.tekrar ? 'Bu bağlantı zaten yakalanmıştı; Ar-Ge ona bakıyor.'
      : d.is ? 'Yakalandı: Ar-Ge uzmanına iş olarak verildi. Sonucu CEO söyleyecek.'
        : 'Yakalandı; Ar-Ge kuyruğu dolu, iş birazdan eklenecek.';
  } else {
    toast(r.status === 429 ? ((r.data && r.data.error) || 'Saatlik sınır doldu.') : explain(r.status, r.data || {}));
  }
});
// A typed draft moves with the switch (joined to a draft already there) and the source is cleared, so an old draft
// can never be sent from the other window later.
function moveDraft(from, to) {
  const draft = from.value;
  if (!draft.trim()) return;
  to.value = to.value.trim() ? `${to.value.replace(/\s+$/, '')}\n${draft}` : draft;
  from.value = '';
}
$('komuta-kucult').addEventListener('click', () => {
  moveDraft($('komuta-input'), $('drawer-input'));
  baglam = [];  // the drawer has no chips: they must not ride along with a later, unrelated message
  renderBaglam();
  closeKomuta();
  openDrawer();
});
$('drawer-expand').addEventListener('click', () => {
  moveDraft($('drawer-input'), $('komuta-input'));
  closeDrawer();
  openKomuta($('open-chat-top'));
});
// a click on the backdrop (outside the card) closes it
$('komuta').addEventListener('click', (e) => { if (e.target === $('komuta')) closeKomuta(); });

// Focus stays inside the window (and the task sheet opened over it): Tab / Shift+Tab wrap around.
const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select, summary, [tabindex]:not([tabindex="-1"])';
function visibleFocusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest('[hidden]') && el.getClientRects().length > 0);
}
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Tab' || !komutaOpen()) return;
  const roots = [$('komuta')];
  if (!$('detail').hidden) roots.push($('detail'));
  const items = roots.flatMap(visibleFocusables);
  if (!items.length) return;
  const i = items.indexOf(document.activeElement);
  const next = e.shiftKey ? (i <= 0 ? items[items.length - 1] : items[i - 1]) : (i < 0 || i === items.length - 1 ? items[0] : items[i + 1]);
  e.preventDefault();
  next.focus();
});
setInterval(() => { if (state && komutaOpen()) renderSuAn(); }, 1000);
if (params.get('komuta') === '1') setTimeout(() => openKomuta(), 300);  // ?komuta=1 opens it at load (screenshots)
// ?kart=<actor id> opens that character's card once it is on the floor (screenshots: ?demo=1&kart=sus:sekreter)
const kartParam = params.get('kart');
if (kartParam && /^[\w:.-]{1,80}$/.test(kartParam)) {
  const t0 = Date.now();
  const tick = setInterval(() => {
    const a = (prevActors || []).find((x) => x.id === kartParam);
    if (a || Date.now() - t0 > 15000) { clearInterval(tick); if (a) openActor(a, { x: window.innerWidth * 0.3, y: 120 }); }
  }, 300);
}

// --- Ayarlar (plan "Ayarlar sayfası" 1.5): the office name and the projects, GET / POST /api/ayarlar ---
// Drawn only when the tab opens and after a save (never from renderAll: a state push must not wipe a form being
// edited). The form is plain fields; the bodies, the checks and the texts are web/ayarlar.js. A refused save keeps
// everything typed (also on 403: sayfa-anahtari.js retries once with a fresh token). The demo saves nothing.
let ayarlar = null;  // the last GET /api/ayarlar body
let ayarForm = null; // {mod: 'ekle' | 'duzenle', proje (the row being edited), baslangic (form values at open), donus}
let ayarGenelBaslangic = null; // the office name field's value when the tab was drawn
let ayarSahipBaslangic = null; // the owner's name field's value when the tab was drawn

function ayarAlani(alan) { return $(`ayar-f-${alan}`); }
function ayarDegerleri() {
  return Object.fromEntries(FORM_ALANLARI.map((k) => [k, ayarAlani(k).value]));
}
// Unsaved edits on the tab: the project form, the office name or the owner's name.
function ayarlarKirli() {
  if (ayarForm && kirli(ayarForm.baslangic, ayarDegerleri())) return true;
  return ofisAdiKirli(ayarGenelBaslangic, $('ayar-ofis-adi').value)
    || ofisAdiKirli(ayarSahipBaslangic, $('ayar-sahip-adi').value);
}
function ayarDurum(text) { $('ayar-durum').textContent = text || ''; }

function ayarHatalariGoster(hatalar) {
  const genel = [];
  for (const k of FORM_ALANLARI) {
    const p = $(`ayar-f-${k}-hata`);
    p.textContent = ''; p.hidden = true;
    ayarAlani(k).removeAttribute('aria-invalid');
  }
  let ilk = null;
  for (const e of hatalar) {
    const p = e.alan && $(`ayar-f-${e.alan}-hata`);
    if (!p) { genel.push(e.metin); continue; }
    p.textContent = p.textContent ? `${p.textContent} ${e.metin}` : e.metin;
    p.hidden = false;
    ayarAlani(e.alan).setAttribute('aria-invalid', 'true');
    if (!ilk) ilk = ayarAlani(e.alan);
  }
  const ul = $('ayar-form-hatalar');
  ul.replaceChildren(...genel.map((m) => h('li', null, m)));
  ul.hidden = !genel.length;
  if (ilk) {
    if (ilk.closest('details') && !ilk.closest('details').open) ilk.closest('details').open = true;
    ilk.focus();
  }
}

async function loadAyarlar() {
  ayarDurum('Yükleniyor…');
  const r = await getJson('/api/ayarlar');
  if (r.status !== 200 || !r.data) {
    ayarDurum(r.status === 0 ? 'Sunucuya ulaşılamadı.' : 'Ayarlar okunamadı.');
    return;
  }
  ayarDurum('');
  renderAyarlar(r.data);
}

function renderAyarlar(data) {
  ayarlar = data;
  const ad = typeof data.ofis_adi === 'string' ? data.ofis_adi : 'Ofis';
  $('ayar-ofis-adi').maxLength = Number(data.kurallar && data.kurallar.ofis_adi_siniri) || 40;
  // an unsaved office name (a project saved or deleted meanwhile) keeps its text and its baseline
  if (!ofisAdiKirli(ayarGenelBaslangic, $('ayar-ofis-adi').value)) {
    $('ayar-ofis-adi').value = ad;
    ayarGenelBaslangic = ad;
    $('ayar-ofis-adi-hata').hidden = true;
    $('ayar-ofis-adi').removeAttribute('aria-invalid');
  }
  const sahipAd = typeof data.sahip_adi === 'string' ? data.sahip_adi : sahip();
  $('ayar-sahip-adi').maxLength = Number(data.kurallar && data.kurallar.sahip_adi_siniri) || 40;
  if (!ofisAdiKirli(ayarSahipBaslangic, $('ayar-sahip-adi').value)) {
    $('ayar-sahip-adi').value = sahipAd;
    ayarSahipBaslangic = sahipAd;
    $('ayar-sahip-adi-hata').hidden = true;
    $('ayar-sahip-adi').removeAttribute('aria-invalid');
  }
  const list = $('ayar-projeler');
  const rows = Array.isArray(data.projeler) ? data.projeler : [];
  list.replaceChildren(...rows.map(ayarKarti));
  $('ayar-projeler-bos').hidden = rows.length > 0;
}

function ayarKarti(p) {
  const card = h('article', 'ayar-kart');
  card.dataset.proje = p.ad;
  const head = h('div', 'ayar-kart-bas');
  const dot = h('span', 'avatar-dot');
  dot.style.background = dotColor(p.ad);
  head.append(dot, h('strong', 'ayar-kart-ad', p.ad));
  if (p.yerlesik) head.append(h('span', 'badge ayar-rozet', 'Yerleşik'));
  const g = guvenRozeti(p.guven);
  head.append(h('span', `badge ayar-rozet guven-${g.ton}`, g.metin));
  card.append(head);
  if (p.description) card.append(h('p', 'ayar-kart-aciklama', p.description));
  const facts = h('p', 'ayar-kart-bilgi');
  const klasor = h('span', 'ayar-kart-klasor', p.path || '—');
  if (p.tam_yol && p.tam_yol !== p.path) klasor.title = p.tam_yol;
  facts.append(klasor, h('span', null, ' · '), h('span', null, acikIsMetni(p.acik_is_sayisi)));
  card.append(facts);
  if (p.guven === false && p.ipucu) {
    const box = h('div', 'ayar-ipucu-kutu');
    box.append(h('p', 'ayar-ipucu', GUVEN_IPUCU));
    const row = h('div', 'ayar-komut');
    const code = h('code', null, p.ipucu);
    const kopya = h('button', 'btn btn-soft btn-sm', 'Kopyala');
    kopya.type = 'button';
    kopya.setAttribute('aria-label', `${p.ad} için güven komutunu kopyala`);
    kopya.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(p.ipucu); toast('Komut kopyalandı.'); } catch {
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(code);
        sel.removeAllRanges(); sel.addRange(range);
        toast('Kopyalanamadı; komut seçildi, Cmd+C ile kopyala.');
      }
    });
    row.append(code, kopya);
    box.append(row);
    card.append(box);
  }
  if (p.yerlesik) card.append(h('p', 'ayar-ipucu', 'Ar-Ge odasının çalışma klasörü; silinemez, yalnız klasörü değiştirilebilir.'));
  const actions = h('div', 'ayar-kart-eylem');
  const duzenle = h('button', 'btn btn-soft btn-sm', 'Düzenle');
  duzenle.type = 'button';
  duzenle.dataset.eylem = 'duzenle';
  duzenle.setAttribute('aria-label', `${p.ad} projesini düzenle`);
  duzenle.addEventListener('click', () => ayarFormAc('duzenle', p, duzenle));
  actions.append(duzenle);
  if (!p.yerlesik) {
    const sil = h('button', 'btn btn-danger btn-sm', 'Sil');
    sil.type = 'button';
    sil.setAttribute('aria-label', `${p.ad} projesini sil`);
    sil.addEventListener('click', () => ayarSil(p, sil));
    actions.append(sil);
  }
  card.append(actions);
  return card;
}

function ayarFormAc(mod, proje, donus) {
  if (ayarForm && ayarlarKirli() && !confirm('Açık formdaki kaydedilmemiş değişiklikler silinsin mi?')) return;
  const degerler = mod === 'duzenle' ? formDegerleri(proje) : bosForm();
  for (const k of FORM_ALANLARI) ayarAlani(k).value = degerler[k];
  const k = (ayarlar && ayarlar.kurallar) || {};
  ayarAlani('description').maxLength = Number(k.aciklama_siniri) || 300;
  ayarAlani('notes').maxLength = Number(k.notlar_siniri) || 2000;
  ayarAlani('ad').disabled = mod === 'duzenle';
  $('ayar-f-ad-ipucu').textContent = mod === 'duzenle' ? 'Proje adı değiştirilemez.'
    : 'Küçük harf, rakam ve tire (ör. musteri-paneli). Sonradan değiştirilemez.';
  $('ayar-form-baslik').textContent = mod === 'duzenle' ? `${proje.ad} projesini düzenle` : 'Yeni proje';
  // the advanced section opens by itself when it already holds something
  $('ayar-gelismis').open = ['hassas_yollar', ...SORUMLU, 'domainler'].some((x) => degerler[x]);
  ayarForm = { mod, proje: mod === 'duzenle' ? proje : null, baslangic: degerler, donus };
  ayarHatalariGoster([]);
  $('ayar-proje-form').hidden = false;
  $('ayar-projeler').hidden = true;
  $('ayar-projeler-bos').hidden = true;
  $('ayar-proje-ekle').hidden = true;
  ayarDurum('');
  (mod === 'duzenle' ? ayarAlani('path') : ayarAlani('ad')).focus();
}

// Closes the project form (no question: the callers ask). odak: where the focus goes (default: where it came from;
// false: nowhere, the tab is closing).
function ayarFormKapat(odak) {
  const donus = ayarForm && ayarForm.donus;
  ayarForm = null;
  $('ayar-proje-form').hidden = true;
  $('ayar-projeler').hidden = false;
  $('ayar-projeler-bos').hidden = !!(ayarlar && ayarlar.projeler && ayarlar.projeler.length);
  $('ayar-proje-ekle').hidden = false;
  if (odak === false) return;
  const el = odak || (donus && donus.isConnected ? donus : $('ayar-proje-ekle'));
  if (el && !$('overlay-ayarlar').hidden) el.focus();
}

// One POST /api/ayarlar: the demo saves nothing; a refusal keeps what was typed.
async function ayarGonder(govde) {
  if (demo) return { status: -1, data: { error: 'Demo modunda kaydedilmez.' } };
  try { return await post('/api/ayarlar', govde); } catch { return { status: 0, data: {} }; }
}

$('ayar-proje-ekle').addEventListener('click', (e) => ayarFormAc('ekle', null, e.currentTarget));
$('ayar-form-vazgec').addEventListener('click', () => {
  if (ayarlarKirli() && !confirm('Kaydedilmemiş değişiklikler silinsin mi?')) return;
  ayarFormKapat();
});
$('ayar-proje-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!ayarForm) return;
  const degerler = ayarDegerleri();
  const duzenleme = ayarForm.mod === 'duzenle';
  const yerel = istemciHatalari(degerler, (ayarlar && ayarlar.kurallar) || {}, { duzenleme });
  if (yerel.length) { ayarHatalariGoster(yerel); return; }
  const govde = duzenleme ? guncellemeGovdesi(ayarForm.proje, degerler) : eklemeGovdesi(degerler);
  if (!govde) { ayarFormKapat(); ayarDurum('Değişiklik yok; bir şey kaydedilmedi.'); return; }
  const btn = $('ayar-form-kaydet');
  btn.disabled = true;
  const r = await ayarGonder(govde);
  btn.disabled = false;
  if (r.status === 200) {
    const ad = govde.proje.ad;
    ayarFormKapat($('ayar-proje-ekle'));
    if (r.data && r.data.ayarlar) renderAyarlar(r.data.ayarlar);
    ayarDurum(sonucMetni(200, r.data));
    const kart = [...$('ayar-projeler').children].find((c) => c.dataset.proje === ad);
    const btnDuzenle = kart && kart.querySelector('button[data-eylem="duzenle"]');
    if (btnDuzenle) btnDuzenle.focus();
    return;
  }
  const hatalar = r.status === 400 || r.status === 404 || r.status === 409 ? sunucuHatalari(r.data) : [];
  ayarHatalariGoster(hatalar.length ? hatalar : [{ alan: '', metin: sonucMetni(r.status, r.data) }]);
});

async function ayarSil(p, btn) {
  if (!confirm(silmeSorusu(p.ad))) { btn.focus(); return; }
  btn.disabled = true;
  const r = await ayarGonder({ islem: 'proje-sil', ad: p.ad });
  btn.disabled = false;
  if (r.status === 200) {
    if (r.data && r.data.ayarlar) renderAyarlar(r.data.ayarlar);
    ayarDurum(sonucMetni(200, r.data));
    $('ayar-proje-ekle').focus();
    return;
  }
  // 409: the server's reason (an open job, a schedule, a workflow, a built-in project)
  const metin = (sunucuHatalari(r.data)[0] || {}).metin || sonucMetni(r.status, r.data);
  ayarDurum(`Silinemedi: ${metin}`);
  btn.focus();
}

// The Genel section: the office's name and the owner's name, saved together (POST {islem: 'genel', ofis_adi,
// sahip_adi}); an error shows under its own field.
$('ayar-genel-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const alanlar = { ofis_adi: ['ayar-ofis-adi', 'ayar-ofis-adi-hata'], sahip_adi: ['ayar-sahip-adi', 'ayar-sahip-adi-hata'] };
  const goster = (alan, m) => {
    const [i, hh] = alanlar[alan];
    const input = $(i);
    const hata = $(hh);
    hata.textContent = m; hata.hidden = !m;
    if (m) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
  };
  const temizle = () => { goster('ofis_adi', ''); goster('sahip_adi', ''); };
  const g = genelGovdesi($('ayar-ofis-adi').value, $('ayar-sahip-adi').value, (ayarlar && ayarlar.kurallar) || {});
  temizle();
  if (g.hata) { goster(g.alan, g.hata); $(alanlar[g.alan][0]).focus(); return; }
  const btn = $('ayar-genel-kaydet');
  btn.disabled = true;
  const r = await ayarGonder(g.govde);
  btn.disabled = false;
  if (r.status === 200) {
    ayarGenelBaslangic = g.govde.ofis_adi;
    ayarSahipBaslangic = g.govde.sahip_adi;
    $('ayar-ofis-adi').value = g.govde.ofis_adi;
    $('ayar-sahip-adi').value = g.govde.sahip_adi;
    if (r.data && r.data.ayarlar) ayarlar = r.data.ayarlar;
    ayarDurum(sonucMetni(200, r.data));
    return;
  }
  const ilk = sunucuHatalari(r.data)[0] || {};
  const alan = ilk.alan === 'sahip_adi' ? 'sahip_adi' : 'ofis_adi';
  goster(alan, r.status === 400 ? (ilk.metin || sonucMetni(r.status, r.data)) : sonucMetni(r.status, r.data));
  $(alanlar[alan][0]).focus();
});

// Leaving the tab with unsaved edits asks first (a click outside, Esc, another tab). Yes: the edits are dropped.
// The project form is closed either way, so the tab opens on the list next time.
function ayarlardanCikilsinMi() {
  if ($('overlay-ayarlar').hidden) return true;
  if (ayarlarKirli() && !confirm('Ayarlar\'da kaydedilmemiş değişiklikler var. Yine de kapatılsın mı?')) return false;
  if (ayarForm) ayarFormKapat(false);
  ayarGenelBaslangic = null;
  ayarSahipBaslangic = null;
  return true;
}

// --- tabs ---
const OVERLAYS = ['kararlar', 'isler', 'raporlar', 'kalite', 'zamanlanmis', 'olaylar', 'ayarlar'];
const openOverlay = () => OVERLAYS.map((n) => $(`overlay-${n}`)).find((o) => !o.hidden);

function setTab(tab) {
  if (tab !== 'ayarlar' && !ayarlardanCikilsinMi()) return;  // unsaved edits on the Ayarlar tab: asked first
  const ayarlarAcikti = !$('overlay-ayarlar').hidden;  // a second click on the open tab must not reload (and wipe) it
  for (const b of document.querySelectorAll('.tab')) {
    const on = b.dataset.tab === tab;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', String(on));
  }
  for (const name of OVERLAYS) $(`overlay-${name}`).hidden = tab !== name;
  // a panel over the scene: hide the scene's labels and legend (CSS) and skip placing them each frame
  document.body.classList.toggle('panel-acik', tab !== 'ofis');
  if (tab !== 'ofis') kartKapat();
  if (office) office.setLabelsHidden(tab !== 'ofis');
  if (tab === 'ofis' && state && sahneGorunur()) renderScene(); // the scene again: catch up at once
  // reports and the scorecard change only when a group or a job finishes: read them each time the tab opens
  if (tab === 'raporlar') loadReports();
  if (tab === 'kalite') loadQuality();
  if (tab === 'zamanlanmis') { schedKey = null; renderSchedules(); }
  if (tab === 'olaylar') renderOlaylar();
  if (tab === 'ayarlar' && !ayarlarAcikti) loadAyarlar();
}
// ?sekme=<tab> opens a tab panel at load (screenshots: ?demo=1&hafif=1&sekme=kalite; the 3D frames stop under it)
const sekmeParam = params.get('sekme');
if (OVERLAYS.includes(sekmeParam)) setTimeout(() => setTab(sekmeParam), 300);
for (const b of document.querySelectorAll('.tab')) b.addEventListener('click', () => setTab(b.dataset.tab));

// The tab panels (Kararlar, İşler, Raporlar, Kalite) close on any click outside their card (like the other popups).
// Clicks on the tabs, the detail modal opened from a card, and the chat drawer are not "outside".
document.addEventListener('click', (e) => {
  if (!openOverlay()) return;
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;  // a row re-rendered under the pointer
  if (t.closest('.overlay-inner, .tab, #detail, #drawer, #scrim, #komuta')) return;
  setTab('ofis');
});

// The room card closes on a click outside it too. The 3D canvas handles its own clicks (another room or empty floor).
document.addEventListener('click', (e) => {
  if ($('room-card').hidden || !selected) return;
  const t = e.target;
  if (!(t instanceof Element) || !t.isConnected) return;
  if (t.closest('#room-card, canvas, .desk-label, #detail, #drawer, #scrim, .overlay, #komuta')) return;
  selectRoom(null);
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!$('detail').hidden) detailBack();
  else if (komutaOpen()) closeKomuta();
  else if ($('drawer').classList.contains('is-open')) closeDrawer();
  else if (openOverlay()) setTab('ofis');
  else selectRoom(null);
});

// --- detail modal: full task note or full message ---
function makeClickable(el, onOpen) {
  el.classList.add('is-clickable');
  el.tabIndex = 0;
  el.setAttribute('role', 'button');
  el.addEventListener('click', onOpen);
  el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(); } });
}

// The card title already shows the question ("ornek-uygulama — Soru: …"); drop the body's first line when it repeats it.
function questionBody(d) {
  const text = (d.question || '').replace(/^\s+/, '');
  const [first, ...rest] = text.split('\n');
  const q = first.replace(/^\s*Soru:\s*/i, '').trim();
  if (q && (d.title || '').includes(q)) return rest.join('\n').replace(/^\s+/, '');
  return text;
}

function decisionDetail(d) {
  return { kind: 'message', kicker: `${d.project} · Soru`, title: d.title || 'Soru', text: questionBody(d), time: parseTime(d.asked) };
}

let detailReturnFocus = null;
let detailSeq = 0;

function showDetail(kicker, titleText, nodes) {
  const kick = $('detail-kicker');
  kick.replaceChildren(...(Array.isArray(kicker) ? kicker : [document.createTextNode(kicker || '')]));
  $('detail-title').textContent = titleText;
  $('detail-body').replaceChildren(...nodes);
  $('detail').classList.toggle('in-komuta', komutaOpen());
  $('detail').hidden = false;
  $('detail-body').scrollTop = 0;
  $('detail-close').focus();
}

function closeDetail() {
  $('detail').hidden = true;
  viewStack = [];
  currentView = null;
  detailSeq++;
  if (detailReturnFocus && detailReturnFocus.isConnected) detailReturnFocus.focus();
  detailReturnFocus = null;
}

function section(heading, content) {
  const nodes = [h('h3', null, heading)];
  nodes.push(content && content.trim() ? mdBlock(content) : h('p', 'empty-note', 'Henüz yazılmamış.'));
  return nodes;
}

function fmtWhen(v) {
  const d = v instanceof Date ? v : parseTime(v);
  return d ? `${d.toLocaleDateString('tr-TR')} ${hhmm(d)}` : (v || '—');
}

// A job of the live state (board first: it has every open job), for its progress line; null when not listed.
function stateTask(note) {
  return (state ? [...(state.board || []), ...(state.tasks || [])] : []).find((x) => x && x.note === note) || null;
}

async function fetchTask(note) {
  if (demo) {
    const t = (state ? [...(state.board || []), ...state.tasks] : []).find((x) => x.note === note);
    return t ? { ...t, task: t.title, result: '', decisions: [] } : null;
  }
  const res = await fetch(`/api/task?note=${encodeURIComponent(note)}`, { cache: 'no-store' });
  if (!res.ok) return null;
  return res.json();
}

// The detail modal keeps a small history: opening a view from inside the modal (a session in the token breakdown,
// a task) pushes the current view, and "← Geri" / Esc return to it. "Kapat" closes the whole stack.
let currentView = null;
let viewStack = [];

function showView(view, push = true) {
  if ($('detail').hidden) {
    viewStack = [];
    detailReturnFocus = document.activeElement;
  } else if (push && currentView) {
    viewStack.push(currentView);
  }
  currentView = view;
  $('detail-back').hidden = viewStack.length === 0;
  if (view.kind === 'report') return renderReport(view.grup);
  return view.kind === 'usage' ? renderUsage(view.project) : renderDetail(view);
}

function openDetail(detail) { return showView(detail); }
function openUsage(project) { return showView({ kind: 'usage', project }); }

function detailBack() {
  const prev = viewStack.pop();
  if (!prev) { closeDetail(); return; }
  showView(prev, false);
}

async function renderDetail(detail) {
  if (detail.kind === 'message') {
    const kicker = [document.createTextNode(detail.kicker || '')];
    if (detail.time) kicker.push(h('span', null, `· ${fmtWhen(detail.time)}`));
    const nodes = [mdBlock(detail.text || '')];
    if (detail.session) nodes.push(h('p', 'empty-note', `Oturum: ${detail.session}`));
    showDetail(kicker, detail.title, nodes);
    return;
  }
  const seq = ++detailSeq;
  showDetail('İş', 'Yükleniyor…', [h('p', 'empty-note', 'İş notu okunuyor…')]);
  let t = null;
  try { t = await fetchTask(detail.note); } catch { t = null; }
  if (seq !== detailSeq) return;  // closed or another detail opened meanwhile
  if (!t) { showDetail('İş', 'İş notu bulunamadı', [h('p', 'empty-note', 'Bu iş notu okunamadı ya da silinmiş.')]); return; }
  const kicker = [document.createTextNode(t.project || 'iş'), h('span', `badge ${t.status}`, STATUS_TR[t.status] || t.status)];
  const meta = h('dl', 'meta-grid');
  for (const [k, v] of [['Başladı', fmtWhen(t.started)], ['Bitti', t.finished ? fmtWhen(t.finished) : '—'],
    ['Oturum', t.session || '—'], ['Not', t.note]]) {
    meta.append(h('dt', null, k), h('dd', null, v));
  }
  const spend = budgetText(t);
  if (spend) meta.append(h('dt', null, 'Kullanım sınırı'), h('dd', null, spend));
  else if (harcamaText(t.spent, t.tokens) !== '—') meta.append(h('dt', null, 'Kullanım'), h('dd', null, harcamaText(t.spent, t.tokens)));
  // an escalated job and the job it replaced link each other (escalation ladder)
  for (const [label, prefix, link] of [[escalationText(t), 'önceki deneme: ', t.escalated_from],
    ['Yeni deneme', 'bir üst katmanda: ', t.escalated_to]]) {
    if (!link) continue;
    const a = h('span', 'link', prefix + link.replace(/\.md$/, ''));
    makeClickable(a, () => openDetail({ kind: 'task', note: link }));
    const dd = h('dd');
    dd.appendChild(a);
    meta.append(h('dt', null, label), dd);
  }
  const nodes = [meta, ...section('Görev', t.task), ...section('Sonuç', t.result)];
  const yol = yolCizgisi(stateTask(t.note), { onNote: (n) => openDetail({ kind: 'task', note: n }) });
  if (yol) nodes.splice(1, 0, yol);
  if (t.workflow) {
    // phase 4: the step's workflow, its verdict, findings and review rounds (from the server's workflow state)
    const w = t.workflow;
    const box = h('div', 'proof');
    box.appendChild(h('h3', null, `Akış: ${w.baslik}`));
    box.appendChild(h('p', 'empty-note', `${w.sablon} · adım ${w.adim}/${w.toplam} · ${stepText({ step: w.adim, step_kind: w.tur })}`));
    box.appendChild(h('p', null, verdictText(w)));
    if (w.inceleme_turu > 1 || w.plan_turu > 1) {
      box.appendChild(h('p', 'empty-note', `Plan turu: ${w.plan_turu || 0} · inceleme turu: ${w.inceleme_turu || 0}`));
    }
    if (w.bulgular && w.bulgular.length) box.appendChild(linkli('pre', 'proof-text', w.bulgular.join('\n')));
    if (w.deniz) box.appendChild(h('p', 'empty-note', `Akış durduğunda ${sahip()} devam dedi; bu adım geçmiş sayıldı.`));
    if (w.durma_nedeni) box.appendChild(h('p', 'empty-note', `Akış durdu: ${w.durma_nedeni}`));
    nodes.push(box);
  }
  for (const k of t.kontrol || []) {
    // the server-run Kontrol: the proof that the job is done (a project's own "bitti" is not)
    const box = h('div', 'proof');
    box.appendChild(h('h3', null, k.title || 'Kontrol (kanıt)'));
    const facts = h('dl', 'meta-grid');
    facts.append(h('dt', null, 'Çıkış kodu'), h('dd', null, k.exit_code || '—'),
      h('dt', null, 'Süre'), h('dd', null, k.duration || '—'));
    box.append(h('p', 'empty-note', 'Komut'), h('pre', 'proof-text', k.command || '—'), facts,
      h('p', 'empty-note', 'Çıktının sonu'), h('pre', 'proof-text', k.output || '(çıktı yok)'));
    nodes.push(box);
  }
  if (t.decisions && t.decisions.length) {
    nodes.push(h('h3', null, 'İlgili kararlar'));
    for (const d of t.decisions) {
      const box = h('div', 'decision');
      box.appendChild(h('strong', null, d.title));
      box.appendChild(mdBlock(`Soru: ${d.question || '—'}`));
      box.appendChild(mdBlock(`Cevap: ${d.answer || (d.status === 'bekliyor' ? 'bekliyor' : '—')}`));
      nodes.push(box);
    }
  }
  showDetail(kicker, t.title || 'İş', nodes);
}

// --- token breakdown for one room ---
const USAGE_LABELS = [
  ['cache_read_input_tokens', 'Önbellekten okunan', 'Her adımda yeniden okunan bağlam (kurallar, önceki mesajlar). Çok ucuz, ama toplamın büyük kısmı budur.'],
  ['cache_creation_input_tokens', 'Önbelleğe yazılan', 'Bağlamın ilk kez önbelleğe alınması.'],
  ['input_tokens', 'Yeni girdi', 'Önbellekte olmayan yeni metin.'],
  ['output_tokens', 'Üretilen', 'Çalışanın yazdığı cevaplar ve araç çağrıları.'],
];

// "claude-opus-5-5" -> "Opus 5.5"; unknown ids are shown as they are.
function modelName(id) {
  const m = /^claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d+))?/.exec(id || '');
  if (!m) return id || 'bilinmiyor';
  return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? '.' + m[3] : ''}`;
}

// List-price estimate in USD, Turkish number format ("$1,25"); tiny amounts read "<$0,01".
function fmtUsd(v) {
  if (v == null) return 'fiyat bilinmiyor';
  if (v > 0 && v < 0.01) return '<$0,01';
  return '$' + v.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function bar(label, value, max, hint, cost) {
  const row = h('div', 'usage-row');
  const head = h('div', 'usage-head');
  const right = h('span', 'usage-amount');
  right.append(h('strong', null, fmtUsage(value)));
  if (cost !== undefined) right.append(h('span', 'usage-cost', fmtUsd(cost)));
  head.append(h('span', null, label), right);
  const track = h('div', 'usage-track');
  const fill = h('div', 'usage-fill');
  fill.style.width = `${max ? Math.max(1, Math.round((value / max) * 100)) : 0}%`;
  track.appendChild(fill);
  row.append(head, track);
  if (hint) row.appendChild(h('p', 'usage-hint', hint));
  return row;
}

async function renderUsage(project) {
  const seq = ++detailSeq;
  const name = project === 'ceo' ? 'CEO' : project;
  showDetail(`${name} · bugün`, 'Token dökümü', [h('p', 'empty-note', 'Hesaplanıyor…')]);
  let d = null;
  if (!demo) {
    try {
      const res = await fetch(`/api/usage?project=${encodeURIComponent(project)}`, { cache: 'no-store' });
      d = res.ok ? await res.json() : null;
    } catch { d = null; }
  }
  if (seq !== detailSeq) return;
  if (!d) { showDetail(`${name} · bugün`, 'Token dökümü', [h('p', 'empty-note', demo ? 'Demo modunda döküm yok.' : 'Döküm alınamadı.')]); return; }
  const cost = d.cost || {};
  const nodes = [h('p', 'usage-total', `Bugün toplam ${fmtUsage(d.total)} token · yaklaşık ${fmtUsd(cost.total)}`)];
  nodes.push(h('p', 'usage-hint', `Tutarlar Anthropic liste fiyatıyla tahmindir (fiyatlar: ${d.prices_as_of || '—'}). `
    + 'Abonelikte token başına fatura yok; kullanım limitinden düşer.'
    + (d.unpriced_calls ? ` ${d.unpriced_calls} çağrının fiyatı bilinmiyor, tutara katılmadı.` : '')));
  if (!d.total) {
    nodes.push(h('p', 'empty-note', 'Bugün bu odada token kullanılmadı.'));
    showDetail(`${name} · bugün`, 'Token dökümü', nodes);
    return;
  }
  nodes.push(h('h3', null, 'Türüne göre'));
  const maxField = Math.max(...USAGE_LABELS.map(([k]) => d.fields[k] || 0));
  for (const [k, label, hint] of USAGE_LABELS) nodes.push(bar(label, d.fields[k] || 0, maxField, hint, cost[k] || 0));
  const models = Object.entries(d.by_model || {}).sort((a, b) => b[1].total - a[1].total);
  if (models.length) {
    nodes.push(h('h3', null, 'Unvana göre'));
    const maxModel = Math.max(...models.map(([, v]) => v.total), 1);
    for (const [id, v] of models) nodes.push(bar(`${calisanMetni(id) || modelName(id)} · ${v.calls} çağrı`, v.total, maxModel, null, v.cost));
  }
  nodes.push(h('h3', null, d.sessions.length > 1 ? 'Oturumlara göre' : 'Oturum'));
  for (const sess of d.sessions) {
    const box = h('div', 'decision usage-session');
    const head = h('div', 'usage-head');
    const amount = h('span', 'usage-amount');
    amount.append(h('strong', null, fmtUsage(sess.total)), h('span', 'usage-cost', fmtUsd((sess.cost || {}).total)));
    head.append(h('strong', null, sess.task ? feedText(sess.task, 70) : sess.name), amount);
    box.appendChild(head);
    const sessModels = Object.keys(sess.by_model || {}).map(modelName).join(', ');
    box.appendChild(h('p', 'usage-hint', `${sess.name} · ${sess.calls} çağrı${sessModels ? ' · ' + sessModels : ''}`));
    const toolCost = sess.cost_by_tool || {};
    const tools = Object.entries(sess.by_tool).sort((a, b) => b[1] - a[1]).map(([t, v]) => [t, v, toolCost[t]]);
    if (sess.other) tools.push(['Cevap / düşünme', sess.other, sess.cost_other]);
    const maxTool = Math.max(...tools.map(([, v]) => v), 1);
    for (const [tool, v, c] of tools.slice(0, 8)) box.appendChild(bar(tool, v, maxTool, null, c === undefined ? null : c));
    if (sess.note) makeClickable(box, () => openDetail({ kind: 'task', note: sess.note }));
    nodes.push(box);
  }
  nodes.push(h('p', 'usage-hint', 'Araç satırı, o aracı kullanan çağrıların tokenidir (yaklaşık).'));
  showDetail(`${name} · bugün`, 'Token dökümü', nodes);
}

makeClickable($('room-tokens'), () => { if (selected) openUsage(selected === CEO ? 'ceo' : selected); });
$('room-tokens').title = 'Tokenin nereye gittiğini göster';

$('detail-close').addEventListener('click', closeDetail);
$('detail-back').addEventListener('click', detailBack);
$('detail').addEventListener('click', (e) => { if (e.target === $('detail')) closeDetail(); });

// --- clock ---
// the office zone (state.sahne.saat_dilimi), never the browser's; a narrow top bar shows the short date
function tick() {
  const t = tarihMetni(Date.now(), state && state.sahne && state.sahne.saat_dilimi);
  $('clock-time').textContent = t.saat;
  $('clock-date').textContent = t.tarih;
  $('clock-date-short').textContent = t.kisa;
}
tick();
setInterval(tick, 10000);

renderAll();
renderFeed();
connect();
