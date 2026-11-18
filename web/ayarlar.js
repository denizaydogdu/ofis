// The Ayarlar tab's pure helpers (plan "Ayarlar sayfası" 1.5): form values from a GET /api/ayarlar project row, the
// POST /api/ayarlar bodies (a new project, only the changed fields of an existing one, the office name), the checks
// that mirror the server's rules (bin/ayarlar.py; the server stays the judge), the server's errors placed under their
// fields and the plain Turkish texts (t(): the display language, web/i18n.js). No DOM here: app.js draws the tab;
// tested with node in test/test_ayarlar_web.py.
import { t as T, N_ } from './i18n.js';

// The form's fields (all strings; the list fields hold one item per line).
export const FORM_ALANLARI = ['ad', 'path', 'description', 'notes', 'hassas_yollar', 'dur_sor', 'asla', 'teslim', 'domainler'];
export const SORUMLU = ['dur_sor', 'asla', 'teslim'];
const LISTE_ALANLARI = ['hassas_yollar', 'dur_sor', 'asla', 'teslim', 'domainler'];
// bin/ayarlar.py HOST: a host name only (no scheme, no path)
const HOST = /^(?=.{1,253}$)(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$/;

// A textarea's lines: trimmed, empty ones dropped.
export function satirlar(text) {
  return String(text == null ? '' : text).split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}
const listeMetni = (v) => (Array.isArray(v) ? v : typeof v === 'string' && v ? [v] : [])
  .filter((x) => typeof x === 'string').join('\n');
const metin = (v) => (typeof v === 'string' ? v : '');

export function bosForm() {
  return Object.fromEntries(FORM_ALANLARI.map((k) => [k, '']));
}

// A GET /api/ayarlar project row -> the form's values (null -> an empty form).
export function formDegerleri(p) {
  if (!p || typeof p !== 'object') return bosForm();
  const s = p.sorumlu && typeof p.sorumlu === 'object' ? p.sorumlu : {};
  const sis = p.sistem && typeof p.sistem === 'object' ? p.sistem : {};
  return {
    ad: metin(p.ad), path: metin(p.path), description: metin(p.description), notes: metin(p.notes),
    hassas_yollar: listeMetni(p.hassas_yollar), dur_sor: listeMetni(s.dur_sor), asla: listeMetni(s.asla),
    teslim: listeMetni(s.teslim), domainler: listeMetni(sis.domainler),
  };
}

// The same values, normalised for comparing: strings trimmed, lists as their lines.
function normal(v) {
  const f = { ...bosForm(), ...(v || {}) };
  const out = {};
  for (const k of FORM_ALANLARI) out[k] = LISTE_ALANLARI.includes(k) ? satirlar(f[k]).join('\n') : String(f[k] || '').trim();
  out.domainler = out.domainler.toLowerCase();
  return out;
}

// True when the form differs from where it started (whitespace alone is no change). No start: never dirty.
export function kirli(baslangic, simdiki) {
  if (!baslangic) return false;
  const a = normal(baslangic), b = normal(simdiki);
  return FORM_ALANLARI.some((k) => a[k] !== b[k]);
}

// {islem: 'proje-ekle', proje} for a new project: empty optional fields are left out.
export function eklemeGovdesi(v) {
  const f = { ...bosForm(), ...(v || {}) };
  const proje = { ad: f.ad.trim(), path: f.path.trim(), description: f.description.trim() };
  if (f.notes.trim()) proje.notes = f.notes.trim();
  const hassas = satirlar(f.hassas_yollar);
  if (hassas.length) proje.hassas_yollar = hassas;
  const sorumlu = {};
  for (const k of SORUMLU) { const l = satirlar(f[k]); if (l.length) sorumlu[k] = l; }
  if (Object.keys(sorumlu).length) proje.sorumlu = sorumlu;
  const doms = satirlar(f.domainler).map((d) => d.toLowerCase());
  if (doms.length) proje.sistem = { domainler: doms };
  return { islem: 'proje-ekle', proje };
}

// {islem: 'proje-guncelle', proje: {ad, …only the changed fields}} or null when nothing changed. An emptied field is
// sent empty ("" / []: the server removes it). sorumlu and sistem are replaced whole by the server: an untouched
// sorumlu section keeps its stored value (a single line stays a string) and sistem keeps its other keys (the mail
// domain, cloudflare), which the form does not show.
export function guncellemeGovdesi(onceki, v) {
  const p = onceki || {};
  const a = normal(formDegerleri(p)), b = normal(v);
  const f = { ...bosForm(), ...(v || {}) };
  const proje = { ad: metin(p.ad) };
  for (const k of ['path', 'description', 'notes']) if (a[k] !== b[k]) proje[k] = f[k].trim();
  if (a.hassas_yollar !== b.hassas_yollar) proje.hassas_yollar = satirlar(f.hassas_yollar);
  if (SORUMLU.some((k) => a[k] !== b[k])) {
    const eski = p.sorumlu && typeof p.sorumlu === 'object' ? p.sorumlu : {};
    const sorumlu = {};
    for (const k of SORUMLU) {
      const l = satirlar(f[k]);
      if (!l.length) continue;
      sorumlu[k] = a[k] === b[k] && eski[k] != null ? eski[k] : l;
    }
    proje.sorumlu = sorumlu;
  }
  if (a.domainler !== b.domainler) {
    const eski = p.sistem && typeof p.sistem === 'object' ? p.sistem : {};
    proje.sistem = { ...eski, domainler: satirlar(f.domainler).map((d) => d.toLowerCase()) };
  }
  return Object.keys(proje).length > 1 ? { islem: 'proje-guncelle', proje } : null;
}

// The checks the page can make before sending (the server checks again, and more: the folder must exist, …).
// -> [{alan, metin}] (empty = fine). duzenleme: an existing project (its name cannot change and is not checked).
export function istemciHatalari(v, kurallar = {}, { duzenleme = false } = {}) {
  const f = { ...bosForm(), ...(v || {}) };
  const out = [];
  const add = (alan, m) => out.push({ alan, metin: m });
  if (!duzenleme) {
    const ad = f.ad.trim();
    let re = null;
    try { re = new RegExp(`^(?:${kurallar.ad_regex || '[a-z0-9][a-z0-9-]{0,39}'})$`); } catch { re = /^[a-z0-9][a-z0-9-]{0,39}$/; }
    if (!re.test(ad)) add('ad', T('Proje adı küçük harf, rakam ve tireden oluşmalı, harf ya da rakamla başlamalı (en çok 40).'));
    else if ((kurallar.ayrilmis || ['ofis']).includes(ad)) add('ad', T("'{ad}' adı ayrılmış; başka bir ad seçin.", { ad }));
  }
  const path = f.path.trim();
  if (!path) add('path', T('Klasör yolu boş olamaz.'));
  else if (!/^[/~]/.test(path)) add('path', T('Klasör yolu tam yol olmalı (/ ya da ~ ile başlamalı).'));
  const d = f.description.trim();
  const dSinir = Number(kurallar.aciklama_siniri) || 300;
  if (!d) add('description', T('Açıklama zorunlu.'));
  else if (/[\r\n]/.test(d)) add('description', T('Açıklama tek satır olmalı.'));
  else if (d.length > dSinir) add('description', T('Açıklama en çok {sinir} karakter olabilir.', { sinir: dSinir }));
  const nSinir = Number(kurallar.notlar_siniri) || 2000;
  if (f.notes.trim().length > nSinir) add('notes', T('Proje kuralları en çok {sinir} karakter olabilir.', { sinir: nSinir }));
  const hSayi = Number(kurallar.hassas_sayisi) || 20;
  if (satirlar(f.hassas_yollar).length > hSayi) add('hassas_yollar', T('{ad} en çok {sayi} satır olabilir.', { ad: T('Hassas yollar'), sayi: hSayi }));
  const kotu = satirlar(f.domainler).filter((x) => !HOST.test(x.toLowerCase()));
  if (kotu.length) add('domainler', T('Domainler yalnız host adı olmalı (ornek.com gibi; https:// ya da yol yok): {liste}',
    { liste: kotu.slice(0, 3).join(', ') }));
  return out;
}

// The field a server error belongs to ('' = the form as a whole); the texts come from bin/ayarlar.py.
export function hataAlani(m) {
  const t = String(m || '');
  if (/^Proje adı|^'[^']*' (adı ayrılmış|adında bir proje zaten)/.test(t)) return 'ad';
  if (/^(Klasör|Bu klasör|Proje klasörü)/.test(t)) return 'path';
  if (/^Açıklama/.test(t)) return 'description';
  if (/^Proje kuralları/.test(t)) return 'notes';
  if (/^Hassas yollar/.test(t)) return 'hassas_yollar';
  const s = /^Sorumlu · (dur_sor|asla|teslim)/.exec(t);
  if (s) return s[1];
  if (/^(Domainler|E-posta domaini)/.test(t)) return 'domainler';
  if (/^Ofis adı/.test(t)) return 'ofis_adi';
  if (/^(Adın|Bu ad ofisin)/.test(t)) return 'sahip_adi'; // bin/sahip.py dogrula
  if (/^NPC sohbeti/.test(t)) return 'npc_sohbet'; // bin/npc_sohbet.py dogrula
  return '';
}

// A refused POST's body ({error, hatalar, alanlar}) -> [{alan, metin}]. The server sends each error's field in
// `alanlar` (bin/ayarlar.py: bin/dil.py Metin.alan; "" = the form as a whole), so the texts may be in any language;
// an answer without it (an older server) falls back to matching the Turkish text.
export function sunucuHatalari(data) {
  if (!data || typeof data !== 'object') return [];
  const list = Array.isArray(data.hatalar) && data.hatalar.length ? data.hatalar : data.error ? [data.error] : [];
  const alanlar = Array.isArray(data.alanlar) && Array.isArray(data.hatalar) && data.hatalar.length ? data.alanlar : null;
  return list.map((x, i) => [x, i]).filter(([x]) => typeof x === 'string' && x)
    .map(([x, i]) => ({ alan: alanlar ? (typeof alanlar[i] === 'string' ? alanlar[i] : '') : hataAlani(x), metin: x }));
}

// The language switch (bin/dil.py dogrula): {govde: {islem: 'genel', dil}} or {hata}.
export function dilGovdesi(dil, kurallar = {}) {
  const diller = Array.isArray(kurallar.diller) && kurallar.diller.length ? kurallar.diller : ['tr', 'en'];
  if (!diller.includes(dil)) return { hata: T('Dil şunlardan biri olmalı: {diller}.', { diller: diller.join(', ') }) };
  return { govde: { islem: 'genel', dil } };
}

// True when the office name field differs from its baseline (the name when the tab was drawn or last saved);
// whitespace alone is no change. No baseline (the tab not drawn yet): never dirty.
export function ofisAdiKirli(baslangic, simdiki) {
  if (baslangic == null) return false;
  return String(simdiki == null ? '' : simdiki).trim() !== String(baslangic).trim();
}

// {govde: {islem: 'genel', ofis_adi}} or {hata}.
export function ofisAdiGovdesi(value, kurallar = {}) {
  const ad = String(value == null ? '' : value).trim();
  const sinir = Number(kurallar.ofis_adi_siniri) || 40;
  if (!ad) return { hata: T('Ofis adı boş olamaz.') };
  if (/[\r\n]/.test(ad)) return { hata: T('Ofis adı tek satır olmalı.') };
  if (ad.length > sinir) return { hata: T('Ofis adı en çok {sinir} karakter olabilir.', { sinir }) };
  return { govde: { islem: 'genel', ofis_adi: ad } };
}

// The owner's name (bin/sahip.py dogrula, the same rule): '' when usable, else the Turkish error.
export function sahipAdiHatasi(value, kurallar = {}) {
  const ad = String(value == null ? '' : value).trim();
  const sinir = Number(kurallar.sahip_adi_siniri) || 40;
  if (!ad) return T('Adın boş olamaz.');
  if (ad.length > sinir) return T('Adın en çok {sinir} karakter olabilir.', { sinir });
  if (!/^\p{L}[\p{L}\p{N} .'’-]*$/u.test(ad) || ad.includes('  ')) {
    return T('Adın harfle başlamalı; yalnız harf, rakam, boşluk, nokta, kesme işareti ve tire içerebilir (köşeli parantez, · ya da satır sonu olamaz).');
  }
  const katli = ad.toLocaleLowerCase('tr-TR').normalize('NFKD').replace(/\p{M}/gu, '').replace(/ı/g, 'i');
  if (katli === 'ofis' || katli === 'ceo') return T('Bu ad ofisin kendi konuşmacılarına ayrılmış (Ofis, CEO); başka bir ad yaz.');
  return '';
}

// The Genel section's one POST: {govde: {islem: 'genel', ofis_adi, sahip_adi}} or {hata, alan}.
export function genelGovdesi(ofisAdi, sahipAdi, kurallar = {}) {
  const o = ofisAdiGovdesi(ofisAdi, kurallar);
  if (o.hata) return { hata: o.hata, alan: 'ofis_adi' };
  const h = sahipAdiHatasi(sahipAdi, kurallar);
  if (h) return { hata: h, alan: 'sahip_adi' };
  return { govde: { islem: 'genel', ofis_adi: o.govde.ofis_adi, sahip_adi: String(sahipAdi).trim() } };
}

// The NPC chat switch (bin/npc_sohbet.py dogrula, the same rule): {govde: {islem: 'genel', npc_sohbet: {acik,
// saatlik_sinir}}} or {hata}. The limit is a whole number 1..npc_saatlik_en_cok (200).
export function npcSohbetGovdesi(acik, saatlik, kurallar = {}) {
  const enCok = Number(kurallar.npc_saatlik_en_cok) || 200;
  const metin = String(saatlik == null ? '' : saatlik).trim();
  const n = Number(metin);
  if (!/^\d+$/.test(metin) || !Number.isInteger(n) || n < 1 || n > enCok) {
    return { hata: T('NPC sohbeti · saatlik sınır 1 ile {sinir} arasında bir tam sayı olmalı.', { sinir: enCok }) };
  }
  return { govde: { islem: 'genel', npc_sohbet: { acik: acik === true, saatlik_sinir: n } } };
}

// Claude Code's trust of the project's folder (GET /api/ayarlar guven: true / false / null).
export function guvenRozeti(guven) {
  if (guven === true) return { ton: 'ok', metin: T('Claude bu klasöre güveniyor') };
  if (guven === false) return { ton: 'uyari', metin: T('Claude bu klasöre henüz güvenmiyor') };
  return { ton: 'bilinmiyor', metin: T('Güven durumu bilinmiyor') };
}
// marked for translation: the page draws T(GUVEN_IPUCU)
export const GUVEN_IPUCU = N_("İşler başlayabilsin diye bu komutu Terminal'de bir kez çalıştır ve çıkan güven sorusunu onayla:");

export function acikIsMetni(n) {
  const k = Number(n) || 0;
  return k > 0 ? T('{n} açık iş', { n: k }) : T('Açık iş yok');
}

export function silmeSorusu(ad) {
  return T("'{ad}' projesi ofisten kaldırılsın mı?\n\nBu projeye artık iş verilemez ve ekip odası ofisten kalkar. Obsidian'daki notları olduğu gibi durur; klasöründeki dosyalara dokunulmaz.", { ad });
}

const ISLEM_SONUCU = { 'proje-ekle': N_("'{ad}' projesi eklendi."), 'proje-guncelle': N_("'{ad}' projesi güncellendi."),
  'proje-sil': N_("'{ad}' projesi silindi.") };

// The line after a POST /api/ayarlar answer.
export function sonucMetni(status, data) {
  const d = data || {};
  if (status === 200) {
    if (d.islem === 'genel') {
      const a = Array.isArray(d.alanlar) ? d.alanlar : [];
      if (a.length === 1 && a[0] === 'dil') return T('Dil kaydedildi.');
      return a.length === 1 && a[0] === 'npc_sohbet' ? T('NPC sohbeti ayarı kaydedildi.') : T('Ofis adı kaydedildi.');
    }
    return T(ISLEM_SONUCU[d.islem] || N_("'{ad}' projesi kaydedildi."), { ad: d.ad });
  }
  if (status === 0) return T('Sunucuya ulaşılamadı; değişiklik kaydedilmedi.');
  if (status === 403) return T('İstek reddedildi; sayfayı yenileyip tekrar dene. Yazdıkların duruyor.');
  if (typeof d.error === 'string' && d.error) return d.error;
  return T('Kaydedilemedi (hata {status}).', { status });
}
