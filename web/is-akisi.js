// The per-job progress line ("yol çizgisi", owner decision 2026-11-14): CEO aldı → <unvan> aldı → <oda> çalışıyor
// ("Ar-Ge odasında" / "<proje> masasında") → Kontrol → rapor geldi → CEO'ya ulaştı → sana iletildi. The server builds task.yol from real records only
// (bin/state.py is_yolu); this file turns it into display steps (pure: yolAdimlari, yolOzeti) and DOM nodes
// (yolCizgisi). textContent / createElement only.

import { ARGE_PROJESI, isModeli, modelAilesi, rolMetni } from './ofis-davranis.js';
import { t as T, N_ } from './i18n.js';

export const YOL_SIRASI = ['alindi', 'verildi', 'calisiyor', 'kontrol', 'rapor', 'ceo', 'iletildi'];
const BEKLEME = { cevap: N_('senin cevabını bekliyor'), izin: N_('izin bekliyor') };
const DURUMLAR = new Set(['tamam', 'simdi', 'bekliyor', 'hata', 'atlandi', 'yok', 'bilinmiyor']);

// Who took the job, as the page and the scene title the worker: the Ar-Ge uzmanı for an arge job, else "<kıdem>
// <uzmanlık>" from the job's own model (else its tier's default). The Genel Müdür shows only when his model really runs the job.
function calisanUnvani(t) {
  if (t.project === ARGE_PROJESI) return T('Ar-Ge uzmanı');
  const fam = modelAilesi(isModeli(t));
  return fam ? rolMetni(fam, t.uzmanlik) : T('Çalışan');
}

function odaMetni(t) {
  if (t.project === ARGE_PROJESI) return T('Ar-Ge odasında');
  return t.project ? T('{proje} masasında', { proje: String(t.project).slice(0, 40) }) : T('masasında');
}

function etiket(adim, durum, t) {
  switch (adim) {
    case 'alindi': return T('CEO aldı');
    case 'verildi': return durum === 'simdi' ? T('{unvan} alacak', { unvan: calisanUnvani(t) })
      : T('{unvan} aldı', { unvan: calisanUnvani(t) });
    case 'calisiyor': return T('{oda} çalışıyor', { oda: odaMetni(t) });
    case 'kontrol': return durum === 'atlandi' ? T('Kontrol yok') : T('Kontrol');
    case 'rapor': return T('rapor geldi');
    case 'ceo': return T("CEO'ya ulaştı");
    default: return T('sana iletildi');
  }
}

// "YYYY-MM-DDTHH:MM:SS" -> "HH:MM" ('' when not a stamp).
export function saatDakika(zaman) {
  const m = /^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})/.exec(String(zaman || ''));
  return m ? `${m[1]}:${m[2]}` : '';
}

// task -> [{adim, etiket, durum, sinif, zaman, ek}] in the line's order, or [] for a task without a yol.
// durum is the server's; sinif adds "bekleme" (amber: a question / permission prompt). ek = the small text under
// the step: its time (done), what it waits for, the reason word (stopped), "bilinmiyor".
export function yolAdimlari(task) {
  const t = task && typeof task === 'object' ? task : {};
  const yol = Array.isArray(t.yol) ? t.yol : [];
  const byStep = new Map(yol.filter((x) => x && typeof x === 'object').map((x) => [x.adim, x]));
  if (!byStep.size) return [];
  return YOL_SIRASI.map((adim) => {
    const x = byStep.get(adim) || {};
    const durum = DURUMLAR.has(x.durum) ? x.durum : 'bekliyor';
    const not = String(x.not || '');
    const bekleme = durum === 'simdi' && BEKLEME[not] ? T(BEKLEME[not]) : '';
    let ek = '';
    if (durum === 'tamam') ek = saatDakika(x.zaman);
    else if (durum === 'simdi') ek = bekleme || T('şimdi');
    else if (durum === 'hata') ek = not.slice(0, 40) || T('durdu');
    else if (durum === 'bilinmiyor') ek = T('bilinmiyor');
    return { adim, etiket: etiket(adim, durum, t), durum, sinif: bekleme ? 'bekleme' : durum, zaman: String(x.zaman || ''), ek };
  });
}

// The compact form's label: the current step (simdi or hata), else the last step done; '' without a line.
export function yolOzeti(task) {
  const adimlar = yolAdimlari(task);
  if (!adimlar.length) return '';
  const simdi = adimlar.find((a) => a.durum === 'simdi' || a.durum === 'hata');
  const son = simdi || [...adimlar].reverse().find((a) => a.durum === 'tamam');
  if (!son) return '';
  return son.ek && son.durum !== 'tamam' && son.ek !== T('şimdi') ? `${son.etiket} · ${son.ek}` : son.etiket;
}

// The line's aria-label: the compact form names its step for screen readers (its dots carry only a title).
export function yolEtiketi(task, kompakt) {
  const ozet = kompakt ? yolOzeti(task) : '';
  return ozet ? T('İşin yolu: {ozet}', { ozet }) : T('İşin yolu');
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// The line as DOM: full (the job's detail: every step with its label and time) or kompakt (a row of dots and the
// current step's label). onNote(note) opens a job (the "→ yeni iş" link of an escalated job). null without a line.
export function yolCizgisi(task, { kompakt = false, onNote = null } = {}) {
  const adimlar = yolAdimlari(task);
  if (!adimlar.length) return null;
  const box = el('div', kompakt ? 'yol yol-kompakt' : 'yol');
  box.setAttribute('role', 'list');
  box.setAttribute('aria-label', yolEtiketi(task, kompakt));
  for (const a of adimlar) {
    const step = el('span', `yol-adim yol-${a.sinif}`);
    step.setAttribute('role', 'listitem');
    step.title = `${a.etiket}${a.ek ? ` · ${a.ek}` : ''}`;
    step.appendChild(el('span', 'yol-nokta'));
    if (!kompakt) {
      step.appendChild(el('span', 'yol-etiket', a.etiket));
      if (a.ek) step.appendChild(el('small', 'yol-ek', a.ek));
    }
    box.appendChild(step);
  }
  if (kompakt) box.appendChild(el('span', 'yol-ozet', yolOzeti(task)));
  const yeni = task && typeof task.escalated_to === 'string' ? task.escalated_to : '';
  if (yeni && !kompakt) {  // the compact form says "üst katmana taşındı"; its row opens the job's detail
    const link = el('button', 'yol-yeni', T('→ yeni iş'));
    link.type = 'button';
    link.title = yeni.replace(/\.md$/, '');
    if (onNote) {
      link.addEventListener('click', (ev) => { ev.stopPropagation(); onNote(yeni); });
    }
    box.appendChild(link);
  }
  return box;
}

// The chat's compact lines are drawn with the chat (not on every state push): this replaces each one marked with
// data-yol-not under `root` by a fresh one from bul(note) (the live state's job), so the dots move without redrawing
// the chat.
export function yollariYenile(root, bul) {
  if (!root || typeof root.querySelectorAll !== 'function') return;
  for (const eski of root.querySelectorAll('[data-yol-not]')) {
    const note = eski.getAttribute('data-yol-not');
    const yeni = yolCizgisi(bul(note), { kompakt: true });
    if (!yeni) continue;
    yeni.setAttribute('data-yol-not', note);
    eski.replaceWith(yeni);
  }
}
