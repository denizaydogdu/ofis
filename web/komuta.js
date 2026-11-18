// Pure helpers of the Komuta masası (the big CEO window; no DOM): the "Şu an" column grouped per project, the context
// chips that end a message with "İlgili: [[iş]]", the CEO's steps (GET /api/ceo/adimlar) as plain Turkish lines, the
// "CEO şu an: …" header and the actions of a system notice card. Every text is a plain string for textContent.
// Tested with node in test/test_komuta.py.
import { calisanIpucu, calisanRolu, calisanlarTablosu, rolAdi } from './ofis-sahne.js';
import { harcamaText, stepText, workflowProgressText } from './ofis-text.js';
import { sahip } from './ofis-davranis.js';
import { t as T, N_ } from './i18n.js';

// marked for translation: the page draws (and sends) T(q)
export const HAZIR_SORULAR = [N_('Durum nedir?'), N_('Bugün ne bitti?'), N_('Bekleyen kararlar neler?')];
export const BAGLAM_EN_COK = 5;

const kok = (note) => String(note || '').replace(/\.md$/, '');
const bos = (v) => (v == null || v === '' || v === '—' ? '' : String(v));
const KAPALI_AKIS = new Set(['bitti', 'iptal']);

function gorevler(state) {
  const map = new Map();
  const add = (t) => { if (t && t.note && !map.has(kok(t.note))) map.set(kok(t.note), t); };
  (state.tasks || []).forEach(add);
  (state.board || []).forEach(add);
  for (const p of state.projects || []) (p.tasks || []).forEach(add);
  return map;
}

// state (/api/state) -> {projeler: [{proje, isler: [{id, baslik, calisan, katman, durum, sure, harcama, yardimci, adim,
// note}], akislar: [{grup, baslik, ilerleme}], sirada, bekletilen, birikis}], denetim: [{id, calisan, is, durum, sure,
// note}], bos}. The rows are those of the "Şu an iş başında" table (ofis-sahne.js calisanlarTablosu) without the CEO
// (the chat column has its own header); the reviewers at work and the hakem stand apart. Projects keep the registry's
// order; a project with nothing active, queued or in a running workflow is left out.
export function suAnGruplari(state, now) {
  const st = state && typeof state === 'object' ? state : {};
  const tasks = gorevler(st);
  const rows = calisanlarTablosu(st, now).filter((r) => r.id !== 'ceo');
  const projeler = new Map();
  const grup = (ad) => {
    const key = ad || '—';
    if (!projeler.has(key)) projeler.set(key, { proje: key, isler: [], akislar: [], sirada: 0, bekletilen: 0, birikis: 0 });
    return projeler.get(key);
  };
  for (const p of st.projects || []) if (p && p.name) grup(p.name);
  const denetim = [];
  for (const r of rows) {
    const note = r.ac && r.ac.note ? r.ac.note : '';
    const t = note ? tasks.get(kok(note)) : null;
    if (r.id.startsWith('denetci:') || r.id === 'hakem') {
      denetim.push({ id: r.id, calisan: calisanRolu(r.unvan, r.model), calisan_ipucu: calisanIpucu(r.unvan, r.model),
        is: bos(r.is), durum: r.durum, sure: bos(r.sure), note });
      continue;
    }
    // role only ("Kıdemli"); the model in the row's tooltip (calisan_ipucu)
    grup(r.proje).isler.push({ id: r.id, baslik: (t && t.title) || bos(r.is) || kok(note) || T('iş'), calisan:
      calisanRolu(r.unvan, r.model), calisan_ipucu: calisanIpucu(r.unvan, r.model), katman: bos(r.katman),
      durum: r.durum, sure: bos(r.sure), harcama: bos(r.harcama), yardimci: bos(rolAdi(r.yardimci)),
      adim: t ? stepText(t) : '', note });
  }
  for (const t of tasks.values()) {
    if (t.status !== 'sirada') continue;
    const g = grup(t.project);
    g.sirada += 1;
    if (t.held) g.bekletilen += 1;
    if (t.onay_birikti === true) g.birikis += 1;
  }
  for (const w of Array.isArray(st.workflows) ? st.workflows : []) {
    if (!w || KAPALI_AKIS.has(w.durum)) continue;
    grup(w.proje).akislar.push({ grup: w.grup || '', baslik: w.baslik || w.grup || T('akış'), ilerleme: workflowProgressText(w) });
  }
  const list = [...projeler.values()].filter((g) => g.isler.length || g.sirada || g.akislar.length);
  return { projeler: list, denetim, bos: list.length === 0 && denetim.length === 0 };
}

// "2 iş sırada · 1 bekletiliyor (the owner bırakınca başlar) · 1 onay birikişi nedeniyle bekliyor"; '' when nothing waits.
export function siraMetni(g) {
  if (!g || !g.sirada) return '';
  const parts = [T('{n} iş sırada', { n: g.sirada })];
  if (g.bekletilen) parts.push(T('{n} bekletiliyor ({sahip} bırakınca başlar)', { n: g.bekletilen, sahip: sahip() }));
  if (g.birikis) parts.push(T('{n} onay birikişi nedeniyle bekliyor', { n: g.birikis }));
  return parts.join(' · ');
}

// --- context chips: a job clicked in "Şu an" goes with the next message ---

const NOT_KOKU = /^[\p{L}\p{N}_.-]{1,120}$/u;

// [{note, baslik}] with `item` added once (by note), at most BAGLAM_EN_COK (the oldest drops); a bad note is ignored.
export function baglamEkle(list, item) {
  const cur = Array.isArray(list) ? list.filter((x) => x && x.note) : [];
  const note = kok(item && item.note);
  if (!NOT_KOKU.test(note) || cur.some((x) => kok(x.note) === note)) return cur;
  const next = [...cur, { note, baslik: String((item && item.baslik) || note).slice(0, 80) }];
  return next.slice(-BAGLAM_EN_COK);
}

export function baglamCikar(list, note) {
  return (Array.isArray(list) ? list : []).filter((x) => x && kok(x.note) !== kok(note));
}

// The chip's label: "İlgili: <title>" (shortened).
export function baglamEtiketi(item) {
  const t = String((item && item.baslik) || (item && item.note) || '').replace(/\s+/g, ' ').trim();
  return T('İlgili: {baslik}', { baslik: t.length > 40 ? `${t.slice(0, 39)}…` : t });
}

// The message as sent: the owner's text, then one plain line "İlgili: [[a]], [[b]]" for the chips (the CEO opens the job
// notes by these links). '' when there is no text.
export function mesajMetni(text, chips) {
  const body = String(text || '').trim();
  if (!body) return '';
  const notes = (Array.isArray(chips) ? chips : []).map((x) => kok(x && x.note)).filter((n) => NOT_KOKU.test(n));
  const uniq = [...new Set(notes)];
  return uniq.length ? `${body}\n\nİlgili: ${uniq.map((n) => `[[${n}]]`).join(', ')}` : body;
}

// The length of the chip line mesajMetni adds ("\n\nİlgili: [[a]], …"); 0 without chips.
export function baglamSatiriUzunlugu(chips) {
  return mesajMetni('x', chips).length - 1;
}

// How long the owner's own text may be so that text + chip line stays within the server's 4000 characters.
export const MESAJ_EN_COK = 4000;
export function metinSiniri(chips) {
  return Math.max(1, MESAJ_EN_COK - baglamSatiriUzunlugu(chips));
}

// --- the CEO's steps and its header line ---

// marked for translation (T() where drawn)
const GECMIS = { Read: N_('okudu'), Edit: N_('düzenledi'), MultiEdit: N_('düzenledi'), Write: N_('yazdı'),
  NotebookEdit: N_('düzenledi'), Bash: N_('çalıştırdı'), Grep: N_('aradı'), Glob: N_('aradı'),
  SendMessage: N_('mesaj gönderdi'), Agent: N_('yardımcı çalıştırdı'), Task: N_('yardımcı çalıştırdı'),
  Skill: N_('beceri kullandı'), WebFetch: N_('web sayfası okudu'), WebSearch: N_("web'de aradı") };
const SIMDI = { Read: N_('okuyor'), Edit: N_('düzenliyor'), MultiEdit: N_('düzenliyor'), Write: N_('yazıyor'),
  NotebookEdit: N_('düzenliyor'), Bash: N_('komut çalıştırıyor'), Grep: N_('arıyor'), Glob: N_('arıyor'),
  SendMessage: N_('mesaj gönderiyor'), Agent: N_('yardımcı çalıştırıyor'), Task: N_('yardımcı çalıştırıyor'),
  Skill: N_('beceri kullanıyor'), WebFetch: N_('web sayfası okuyor'), WebSearch: N_("web'de arıyor") };
const cevir = (s) => (s ? T(s) : s);
const kisalt = (s, n) => {
  const t = String(s || '').replace(/[\u0000-\u001f\u007f\u2028\u2029]/g, ' ').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

// One step: "okudu: Index.md", "çalıştırdı: python3 ofis.py durum", "aradı".
export function adimMetni(a) {
  if (!a || typeof a !== 'object') return '';
  const arac = kisalt(a.arac, 40);
  const verb = kisalt(a.ozet, 40) || cevir(GECMIS[arac]) || (arac ? T('{arac} kullandı', { arac }) : T('bir adım attı'));
  const hedef = kisalt(a.hedef, 48);
  return hedef ? `${verb}: ${hedef}` : verb;
}

// What the CEO does now, from arac_simdi or the state's current_tool ({name, target}): "komut çalıştırıyor: ofis.py".
export function simdiMetni(aracSimdi, currentTool) {
  if (aracSimdi && aracSimdi.arac) {
    const verb = kisalt(aracSimdi.ozet, 40) || cevir(SIMDI[aracSimdi.arac])
      || T('{arac} kullanıyor', { arac: kisalt(aracSimdi.arac, 40) });
    const hedef = kisalt(aracSimdi.hedef, 48);
    return hedef ? `${verb}: ${hedef}` : verb;
  }
  if (currentTool && currentTool.name) {
    const verb = cevir(SIMDI[currentTool.name]) || T('{arac} kullanıyor', { arac: kisalt(currentTool.name, 40) });
    const hedef = kisalt(currentTool.target, 48);
    return hedef ? `${verb}: ${hedef}` : verb;
  }
  return '';
}

// Seconds -> "<1 dk", "12 dk", "1 sa 5 dk"; '' when unknown.
export function sureYazisi(sn) {
  const n = Number(sn);
  if (sn == null || sn === '' || !Number.isFinite(n) || n < 0) return '';
  const dk = Math.floor(n / 60);
  if (dk < 1) return T('<1 dk');
  return dk < 60 ? T('{dk} dk', { dk }) : T('{sa} sa {dk} dk', { sa: Math.floor(dk / 60), dk: dk % 60 });
}

const CEO_DURUM = { busy: N_('çalışıyor'), idle: N_('hazır'), dormant: N_('uyuyor'), waiting: N_('izin bekliyor'),
  absent: N_('başlamadı'), unknown: N_('bilinmiyor') };

// "CEO şu an: çalışıyor · komut çalıştırıyor: python3 ofis.py durum · 3 dk" / "CEO şu an: hazır · son işi 5 dk önce
// bitti". `ceo` = state.ceo (the state is the fresher of the two), `adim` = GET /api/ceo/adimlar or null.
export const CEO_KAPANIYOR = N_('Cevap verdi · tur kapanıyor'); // the page draws T(CEO_KAPANIYOR)
export function ceoSimdiMetni(ceo, adim) {
  const c = ceo && typeof ceo === 'object' ? ceo : {};
  const durum = c.state || (adim && adim.durum) || 'unknown';
  // the reply is written and nothing runs; only Claude Code's turn-end record is still missing (state.ceo.tur_kapaniyor)
  if (durum === 'busy' && c.tur_kapaniyor) return T('CEO şu an: {durum}', { durum: T(CEO_KAPANIYOR) });
  const parts = [T('CEO şu an: {durum}', { durum: T(CEO_DURUM[durum] || CEO_DURUM.unknown) })];
  const sure = sureYazisi(adim && adim.sure_sn);
  if (durum === 'busy' || durum === 'waiting') {
    parts.push(simdiMetni(adim && adim.arac_simdi, c.current_tool) || T('düşünüyor ya da cevap yazıyor'));
    if (sure) parts.push(sure);
  } else if (sure) {
    parts.push(T('son işi {sure} önce bitti', { sure }));
  }
  return parts.join(' · ');
}

// --- the footer under each CEO reply (GET /api/ceo/turlar, bin/adimlar.py; owner decision 2026-11-12) ---

// One turn -> {metin, isler: [{note, metin}]} or null: "CEO kendisi baktı · 3 adım · iş açılmadı · $0,03 · 12 bin
// token" when it opened no job; else one "İş açıldı: <başlık> → <unvan>" per job (a link to its detail) and the steps
// with the cost. Plain strings for textContent.
export function turAltMetni(tur) {
  if (!tur || typeof tur !== 'object') return null;
  const n = Math.max(0, Math.floor(Number(tur.adim) || 0));
  const usd = Number(tur.usd) > 0 || !tur.fiyat_eksik ? tur.usd : null;
  const para = harcamaText(usd, tur.token);
  const paraSon = para && para !== '—' ? [para] : [];
  const isler = (Array.isArray(tur.isler) ? tur.isler : []).filter((j) => j && j.note).map((j) => {
    const kim = kisalt(j.unvan || j.katman || '', 30);
    const akis = j.akis ? ` · ${Number(j.adim_sayisi) > 0 ? T('akış, {n} adım', { n: Number(j.adim_sayisi) }) : T('akış')}` : '';
    const baslik = T('İş açıldı: {baslik}', { baslik: kisalt(j.baslik || kok(j.note), 80) });
    return { note: String(j.note), metin: `${baslik}${kim ? ` → ${kim}` : ''}${akis}` };
  });
  if (isler.length) return { metin: [T('{n} adım', { n }), ...paraSon].join(' · '), isler };
  const ilk = n ? [T('CEO kendisi baktı'), T('{n} adım', { n })] : [T('CEO kendisi cevapladı')];
  return { metin: [...ilk, T('iş açılmadı'), ...paraSon].join(' · '), isler: [] };
}

// chat lines + turns -> {index of the chat line: turn}: each turn goes under its last CEO reply line (the line whose
// time is the turn's cevap_zaman; several lines of one turn share it — the last one wins).
export function turAltlari(chat, turlar) {
  const byTime = new Map();
  for (const t of Array.isArray(turlar) ? turlar : []) {
    if (t && typeof t.cevap_zaman === 'string' && t.cevap_zaman && !byTime.has(t.cevap_zaman)) byTime.set(t.cevap_zaman, t);
  }
  const out = {};
  const last = new Map();
  (Array.isArray(chat) ? chat : []).forEach((m, i) => {
    if (m && m.role === 'ceo' && byTime.has(m.time)) last.set(m.time, i);
  });
  for (const [time, i] of last) out[i] = byTime.get(time);
  return out;
}

// The queued indicator under the chat: '' when the CEO is free and nothing waits.
export function siradaGostergesi(ceo) {
  const c = ceo && typeof ceo === 'object' ? ceo : {};
  const q = Number(c.queue) || 0;
  if (q > 0) return T('Mesajın sırada: CEO şu anki işini bitirince okuyacak ({n} mesaj bekliyor).', { n: q });
  if (c.state === 'busy') return T('CEO çalışıyor; şimdi yazarsan mesajın sıraya girer.');
  if (c.state === 'waiting') return T('CEO bir izin sorusunda bekliyor; mesajlar kuyrukta.');
  return '';
}

// --- system notice cards in the chat: their actions ---

// The notice title (its first line, the server's own words — never the quoted project text) -> {karar: a pending
// decision note it names, is: a known job note it names}; '' when none.
export function bildirimEylemleri(title, decisions, tasks) {
  const text = String(title || '');
  const karar = (Array.isArray(decisions) ? decisions : []).find((d) => d && d.note && kok(d.note).length > 8 &&
    text.includes(kok(d.note)));
  const is = (Array.isArray(tasks) ? tasks : []).find((t) => t && t.note && kok(t.note).length > 8 &&
    text.includes(kok(t.note)));
  return { karar: karar ? karar.note : '', is: is ? is.note : '' };
}

// Today's usage: all tokens first, then the CEO's and every project's API-equivalent cost -> "182 bin token · ≈$1,23".
export function bugunkuHarcama(state) {
  const st = state && typeof state === 'object' ? state : {};
  const cost = (Number(st.ceo && st.ceo.cost_today) || 0) +
    (st.projects || []).reduce((a, p) => a + (Number(p && p.cost_today) || 0), 0);
  const tok = st.summary ? st.summary.usage_today : null;
  return harcamaText(cost, tok);
}

// --- "Duyuru yap": the owner's announcement to every office session (POST /api/duyuru, bin/duyuru.py) ---

export const DUYURU_EN_COK = 2000; // bin/duyuru.py MAX_METIN
export const DUYURU_SURELERI = ['simdi', 'bugun', 'hafta', 'tarih'];

// The POST body from the form: {govde: {metin, sure}} or {hata: '<Turkish message>'}. secim: simdi | bugun | hafta |
// tarih (then tarih is the input's YYYY-MM-DD value).
export function duyuruGovdesi(metin, secim, tarih = '') {
  const m = String(metin || '').trim();
  if (!m) return { hata: T('Duyuru metni boş.') };
  if (m.length > DUYURU_EN_COK) return { hata: T('Duyuru en çok {sinir} karakter olabilir.', { sinir: DUYURU_EN_COK }) };
  if (!DUYURU_SURELERI.includes(secim)) return { hata: T('Süre seçilmedi.') };
  if (secim === 'tarih') {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(tarih || ''))) return { hata: T('Son günü seç.') };
    return { govde: { metin: m, sure: tarih } };
  }
  return { govde: { metin: m, sure: secim } };
}

// The line under the form after the server accepted it (202 {duyuru, hedef, bitis}).
export function duyuruSonucu(data) {
  const n = Number(data && data.hedef) || 0;
  const kime = n ? T('{n} çalışan oturuma iletilecek', { n }) : T('şu an çalışan oturum yok');
  const bitis = data && typeof data.bitis === 'string' && data.bitis
    ? T('; {zaman} saatine kadar yeni işlere de eklenir', { zaman: data.bitis.slice(0, 16).replace('T', ' ') }) : '';
  return T('Duyuru kaydedildi: {kime}{bitis}.', { kime, bitis });
}
