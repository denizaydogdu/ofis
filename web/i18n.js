// The page's language (ofis.json `dil`: 'tr' | 'en', default 'tr'; /api/state.ofis.dil, the Ayarlar tab's Genel).
// Strings are keyed by their Turkish source text: t('Kaydet') returns it as is in Turkish and the English entry of
// web/i18n-en.js in English (the Turkish text when an entry is missing). `{name}` placeholders are filled from vars in
// both languages; an English entry may be {one, other}, chosen by vars.n (1 = one).
// Rules for callers: never call t() at module top level (the language can change while the page is open) — mark such
// constants with N_('…') and translate them where they are drawn; never translate what code parses (protocol prefixes,
// status codes, vault folder names, notice titles the page matches). test/test_dil.py checks that every t('…'),
// N_('…') and data-t literal of the translated files has an English entry, and that no entry is unused.
import { EN } from './i18n-en.js';

export const DILLER = ['tr', 'en'];
export const DIL_ANAHTARI = 'ofis-dil'; // localStorage: the last language, so the first paint is right
let dil = 'tr';
try {
  const v = globalThis.localStorage && globalThis.localStorage.getItem(DIL_ANAHTARI);
  if (DILLER.includes(v)) dil = v;
} catch { /* storage unavailable */ }
// Under node only (the tests): OFIS_DIL picks the language; a browser has no `process`.
try {
  if (typeof process !== 'undefined' && process && process.env && DILLER.includes(process.env.OFIS_DIL)) dil = process.env.OFIS_DIL;
} catch { /* no process */ }

const dinleyiciler = [];

export const aktifDil = () => dil;

// Sets the language (an unknown value is ignored); remembers it and calls the listeners when it changed. -> changed?
export function dilAyarla(d) {
  if (!DILLER.includes(d) || d === dil) return false;
  dil = d;
  try { globalThis.localStorage && globalThis.localStorage.setItem(DIL_ANAHTARI, d); } catch { /* storage unavailable */ }
  for (const fn of dinleyiciler.slice()) {
    try { fn(d); } catch (e) { console.error(e); }
  }
  return true;
}

// fn(dil) after every change.
export function dilDinle(fn) { dinleyiciler.push(fn); }

// The locale for dates and numbers. Turkish casing helpers keep 'tr' themselves.
export const yerel = () => (dil === 'en' ? 'en-GB' : 'tr-TR');

// Marks a Turkish literal for translation without translating it (a module constant); t() it where it is drawn.
export const N_ = (s) => s;

function doldur(s, vars) {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k] ?? '') : m));
}

// The text in the current language, placeholders filled.
export function t(tr, vars) {
  const kaynak = String(tr ?? '');
  let s = kaynak;
  if (dil === 'en') {
    const e = Object.prototype.hasOwnProperty.call(EN, kaynak) ? EN[kaynak] : undefined;
    if (typeof e === 'string') s = e;
    else if (e && typeof e === 'object') s = (vars && Number(vars.n) === 1 ? e.one : e.other) ?? kaynak;
  }
  return doldur(s, vars);
}

// The static HTML: data-t="<Turkish>" sets the text; data-t-title / data-t-placeholder / data-t-aria-label set that
// attribute. Only leaf elements carry data-t (textContent replaces the children).
const ATTRS = [['data-t-title', 'title'], ['data-t-placeholder', 'placeholder'], ['data-t-aria-label', 'aria-label']];
export function ceviriUygula(root) {
  const r = root || (typeof document !== 'undefined' ? document : null);
  if (!r || !r.querySelectorAll) return;
  for (const el of r.querySelectorAll('[data-t]')) el.textContent = t(el.getAttribute('data-t'));
  for (const [veri, attr] of ATTRS) {
    for (const el of r.querySelectorAll(`[${veri}]`)) el.setAttribute(attr, t(el.getAttribute(veri)));
  }
  if (typeof document !== 'undefined' && r === document && document.documentElement) document.documentElement.lang = dil;
}
