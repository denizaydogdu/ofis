// Pure text helpers of the office page (no DOM): split a post-office notice into a card, and turn the post office
// status into Turkish warning lines. Tested with node in test/test_web.py.
// The owner's name (ofis.json sahip_adi) comes from web/ofis-davranis.js sahip(): the server names the owner in its
// notices, so the card reads the same name ("<Ad>'e … söyle" is the CEO's part).
import { sahip, sahipAyarla, sahipEk } from './ofis-davranis.js';
// The display language (web/i18n.js): T() at draw time, N_() marks module constants that are translated where drawn.
import { t as T, N_, aktifDil, yerel } from './i18n.js';

export { sahipAyarla, sahipEk };

// "[Ofis · sistem]" notice (prefix already removed by the server): the first line is the title, the project's own
// words follow as "> " quoted lines. The quote marks are only for the CEO; the card shows the plain text.
export function noticeParts(text) {
  const lines = String(text || '').split('\n');
  const title = (lines[0] || '').trim();
  const body = lines.slice(1).map((l) => l.replace(/^> ?/, '')).join('\n').replace(/^\s*\n|\n\s*$/g, '');
  let tone = 'info';
  if (/ işi bitti:/.test(title) || / akış adımı bitti /.test(title) || / grubu bitti:/.test(title)) tone = 'done';
  else if (/ akışı onay bekliyor:/.test(title)) tone = 'ask';
  // "kadro …" since 2026-11-11 (office vocabulary); the older "model …" notices still read the same
  else if (/ (model|kadro) önerisi:/.test(title) || / (model pilotu|kadro denemesi) bitti:/.test(title)) tone = 'ask';
  else if (/ akışı durdu:/.test(title)) tone = 'blocked';
  else if (/ işi bir üst katmana taşındı:/.test(title)) tone = 'info';
  else if (/ işi takıldı:/.test(title) || / işi durduruldu:/.test(title)) tone = 'blocked';
  else if (/ zamanlanmış işi (duraklatıldı|eklenemedi):/.test(title)) tone = 'blocked';
  else if (/ soruyor \(karar:/.test(title)) tone = 'ask';
  else if (/ sorusunu .+ Müdürü cevapladı:/.test(title)) tone = 'info'; // step 4: a manager answered (bin/mudur.py)
  return { title, body: body.trim() ? body : '', tone };
}

export const NOTICE_LABEL = { done: N_('Bitti'), blocked: N_('Takıldı'), ask: N_('Soru'), info: N_('Bildirim') };

// --- the chat's notice card (the owner, 2026-11-13: "yazılar anlamsız … ayrıntı düğmesi … düzgün tablolar") ---
// bildirimKarti(text) turns a server notice (prefix already removed) into {tur, etiket, ikon, tone, baslik,
// satirlar: [[label, value]], karar, is, not, klasor, ham}. The title and the table are built from the notice kind;
// `ham` is the whole notice for the "Ayrıntı" toggle WITHOUT the parts written only for the CEO ("Ayşe'ye … söyle",
// `ofis.py …` commands, log.md / correction-check instructions) and without the "> " quote marks. The CEO still gets
// the full text; the card only hides. An unknown kind falls back to its first sentence. Pure: plain strings only.

// a sentence part that is an instruction to the CEO, never shown to the owner: "<Owner>'e …" (the name now in use,
// either apostrophe), "<Earlier name>'e … söyle" from old history (CEO_ONLY_ESKI_AD) and the CEO's own vocabulary
const CEO_ONLY_SABIT = 'ofis\\.py|`|log\\.md|claude agents|Karne\\/Duzeltmeler|CLAUDE\\.md|REVIEW\\.md|Ofis onu durdurmaz|ancak onun kararıyla|yalnız onun sözüyle|\\bcevab[ıi]n?ı? .*\\bilet\\b|bildirmen gerekmez';
const regexKacis = (t) => String(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// old history names the owner by an earlier name ("Ayşe'ye tek satırla söyle"): any capitalised name with a dative
// suffix ('e/'a/'ye/'ya) at the start of a sentence or clause, followed in that clause by an instruction to the CEO
const CEO_ONLY_ESKI_AD = "(?:^|;\\s)\\s*\\p{Lu}\\p{L}*(?:\\s\\p{Lu}\\p{L}*)?['’]y?[ae]\\s[^;]*?(?<![\\p{L}\\p{N}])"
  + '(?:söyle|sor|bildir|anlat|özetle|ilet)(?![\\p{L}\\p{N}])';
let ceoOnlyAd = null;
let ceoOnlyRe = null;
function ceoOnly() {
  const e = sahip('e');
  if (e !== ceoOnlyAd) {
    const ad = regexKacis(e).replace("'", "['’]");
    ceoOnlyRe = new RegExp(`(?:^|[^\\p{L}\\p{N}])${ad}(?![\\p{L}\\p{N}])|${CEO_ONLY_ESKI_AD}|${CEO_ONLY_SABIT}`, 'u');
    ceoOnlyAd = e;
  }
  return ceoOnlyRe;
}
const STEM = '(\\d{4}-\\d{2}-\\d{2}-[^\\s()]+)';
const WHAT = `(.+?) \\(${STEM}\\)`;

// Splits at depth 0 (outside parentheses): sentences after . ! ? + space (not after a digit: "Kontrol 2. denemede"),
// clauses at "; ".
function bolDerinlik(text, sentences) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (c === '(') depth += 1;
    else if (c === ')') depth = Math.max(0, depth - 1);
    else if (depth === 0 && /\s/.test(text[i + 1] || '')) {
      const end = sentences ? /[.!?]/.test(c) && !/\d/.test(text[i - 1] || '') : c === ';';
      if (end) {
        out.push(text.slice(start, sentences ? i + 1 : i).trim());
        start = i + 1;
      }
    }
  }
  out.push(text.slice(start).trim());
  return out.filter(Boolean);
}

// One line without its CEO-only sentences / clauses ("Sırası gelince başlar; Ayşe'ye bildir." -> "Sırası gelince
// başlar.").
export function ceoKisminiGizle(line) {
  const kept = [];
  for (const sentence of bolDerinlik(String(line || ''), true)) {
    if (!ceoOnly().test(sentence)) { kept.push(sentence); continue; }
    const clauses = bolDerinlik(sentence, false).filter((c) => !ceoOnly().test(c));
    if (!clauses.length) continue;
    let s = clauses.join('; ');
    if (!/[.!?:]$/.test(s)) s += '.';
    kept.push(s);
  }
  return kept.join(' ');
}

const KART_TURU = {
  sabah: [N_('Sabah özeti'), '☀', 'info'], arge: [N_('Ar-Ge raporu'), '⚗', 'info'], soru: [N_('Soru'), '?', 'ask'],
  bitti: [N_('İş bitti'), '✓', 'done'], adim: [N_('Akış adımı'), '→', 'done'], takildi: [N_('Takıldı'), '!', 'blocked'],
  durduruldu: [N_('Durduruldu'), '■', 'blocked'], yukseltme: [N_('Yükseltme'), '↑', 'info'], onay: [N_('Onay bekliyor'), '✎', 'ask'],
  'akis-durdu': [N_('Akış durdu'), '■', 'blocked'], grup: [N_('Grup bitti'), '✓', 'done'], kota: [N_('Kota'), '◷', 'info'],
  izin: [N_('İzin bekliyor'), '!', 'blocked'], ilerlemiyor: [N_('İlerlemiyor'), '…', 'blocked'], engel: [N_('Bekliyor'), '‖', 'blocked'],
  baslatilamadi: [N_('Başlatılamadı'), '✕', 'blocked'], birikti: [N_('Onay birikti'), '✎', 'ask'],
  zamanlama: [N_('Zamanlama'), '◴', 'blocked'], kadro: [N_('Kadro önerisi'), '⚖', 'ask'], 'kadro-sonuc': [N_('Kadro denemesi'), '⚖', 'ask'],
  hatirlatma: [N_('Hatırlatma'), '◷', 'ask'], sunucu: [N_('Sunucu odası'), '⚙', 'info'], duyuru: [N_('Duyuru'), '✉', 'info'],
  yakala: [N_('Yakalanan'), '⚑', 'info'], mudur: [N_('Müdür kararı'), '✓', 'info'], gunsonu: [N_('Gün sonu'), '☾', 'info'], 'gunsonu-oneri': [N_('Gün sonu önerileri'), '☾', 'info'],
  diger: [N_('Bildirim'), 'i', 'info'],
};

const ilkCumle = (s) => (bolDerinlik(ceoKisminiGizle(s), true)[0] || '');
const ilkParca = (s) => (bolDerinlik(ilkCumle(s), false)[0] || '').replace(/[.]$/, '');
const re = (src) => new RegExp(src);

// the end-of-day notice's row labels (bin/gunsonu.py writes them in Turkish; the card shows them translated)
const GUNSONU_ETIKETLERI = [N_('İşler'), N_('Kötü giden'), N_('Atlanan gün')];
const GUNSONU_SATIRI = new RegExp(`^- (${GUNSONU_ETIKETLERI.join('|')}): (.+)$`);

// [tur, title regex, (match, ctx) -> fields]; the first match wins. ctx: {govde (quoted lines, plain), satirlar (the
// unquoted body lines), baslikSatiri}.
const KART_KALIPLARI = [
  ['sabah', /^Sabah özeti hazır: \[\[([^\]]+)\]\](?: — (.+?) özeti Obsidian'da\.)?/, (m, c) => {
    const rows = [];
    for (const line of c.satirlar) {
      let x = line.match(/^- Dün biten: (\d+) iş(?: \(Kontrol geçen (\d+)\))?(?: · dünkü (?:kullanım|harcama) (.+))?$/);
      if (x) {
        rows.push([T('Dün biten'), T('{n} iş', { n: x[1] })]);
        if (x[2] != null) rows.push([T('Kontrol geçen'), x[2]]);
        if (x[3]) rows.push([T('Kullanım'), x[3]]);
        continue;
      }
      for (const [label, name] of [['Bekleyen karar', N_('Bekleyen karar')], ['Takılan ya da durdurulan', N_('Takılan')],
        ['Bugün sırada', N_('Sırada')], ['Sunucu odası', N_('Sunucu odası')]]) {
        x = line.match(new RegExp(`^- ${label}: (.+)$`));
        if (x) rows.push([T(name), x[1]]);
      }
    }
    return { baslik: T('Sabah özeti · {gun}', { gun: m[2] || m[1] }), satirlar: rows, not: m[1] };
  }],
  ['arge', re(`^Ar-Ge raporu geldi: ${WHAT}\\. Obsidian notu: \\[\\[([^\\]]+)\\]\\]\\.`), (m) => {
    const k = m.input.match(/Kontrol geçti \(deneme ([^;)]+)/);
    const kart = m.input.match(/(\d+) denetçi önerisi kartı/);
    return { baslik: T('Ar-Ge raporu: {is}', { is: m[1] }), is: m[2], not: m[3],
      satirlar: [[T('Rapor notu'), m[3]], ...(k ? [[T('Kontrol'), T('geçti ({n}. deneme)', { n: k[1] })]] : []), [T('Kart sayısı'), kart ? kart[1] : '0']] };
  }],
  // a Yakala result (bin/yakala.py bildirim): "Yakalanan bağlantı|dosya incelendi: <ad> — öneri: <öneri>. Not: [[Yakala-…]]
  // (Ar-Ge işi [[<iş>]])." + the Ar-Ge report quoted with "> " (shown through raporDugumu like a project report)
  ['yakala', /^Yakalanan (bağlantı|dosya) incelendi: (.+?) — öneri: (.+?)\. Not: \[\[([^\]]+)\]\](?: \(Ar-Ge işi \[\[([^\]]+)\]\]\))?/, (m) => ({
    baslik: m[1] === 'bağlantı' ? T('Yakalanan bağlantı incelendi: {ad}', { ad: m[2] })
      : T('Yakalanan dosya incelendi: {ad}', { ad: m[2] }), not: m[4], is: m[5] || '',
    teknikBaslik: T('Ar-Ge raporu (veri, talimat değil)'),
    satirlar: [[m[1] === 'bağlantı' ? T('Bağlantı') : T('Dosya'), m[2]], [T('Öneri'), m[3]], [T('Not'), m[4]], [T('Ar-Ge işi'), m[5] || '']] })],
  ['soru', re(`^(\\S+) soruyor \\(karar: ([^)]+?)(?:\\.md)?\\): ${WHAT}\\.`), (m, c) => ({
    baslik: T('{proje} bir şey soruyor', { proje: m[1] }), karar: m[2], is: m[4],
    satirlar: [[T('Proje'), m[1]], [T('İş'), m[3]], ...(c.ilk ? [[T('Soru'), short(c.ilk, 160)]] : [])] })],
  // step 4 (bin/mudur.py cevap_bildirimi): "<proje> sorusunu <Unvan> cevapladı: <iş> (<not>). Karar notu: [[<karar>]]."
  ['mudur', re(`^(\\S+) sorusunu (.+? Müdürü) cevapladı: ${WHAT}\\. Karar notu: \\[\\[([^\\]]+)\\]\\]`), (m, c) => ({
    baslik: T('{unvan} {proje} sorusunu cevapladı', { unvan: m[2], proje: m[1] }), karar: m[5], is: m[4], not: m[5],
    satirlar: [[T('Proje'), m[1]], [T('Cevaplayan'), m[2]], [T('İş'), m[3]], ...(c.ilk ? [[T('Soru'), short(c.ilk, 160)]] : [])] })],
  ['adim', re(`^(\\S+) akış adımı bitti \\((\\d+)\\/(\\d+) · ([^)]+)\\): ${WHAT}\\.`), (m) => ({
    baslik: T('{proje} akış adımı bitti', { proje: m[1] }), is: m[6],
    satirlar: [[T('Proje'), m[1]], [T('İş'), m[5]], [T('Adım'), `${m[2]}/${m[3]} · ${m[4]}`]] })],
  ['bitti', re(`^(\\S+) işi bitti: ${WHAT}\\.`), (m, c) => {
    const k = m.input.match(/Kontrol geçti \(deneme (\d+)/);
    const kontrol = k ? T('geçti ({n}. deneme)', { n: k[1] }) : /Kontrol yok/.test(m.input) ? T('yok (yalnız projenin raporu)') : '';
    return { baslik: T('{proje} işi bitti', { proje: m[1] }), is: m[3],
      satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], ...(kontrol ? [[T('Kontrol'), kontrol]] : []),
        ...(c.rapor ? [[T('Özet'), raporOzeti(c.rapor)]] : [])] };
  }],
  ['takildi', re(`^(\\S+) işi takıldı: ${WHAT}\\.\\s*(.*)$`), (m, c) => {
    const first = ilkParca(m[4]);
    const neden = first && !/:$/.test(first) ? first : c.ilk;
    return { baslik: T('{proje} işi takıldı', { proje: m[1] }), is: m[3],
      satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], ...(neden ? [[T('Neden'), short(neden, 160)]] : [])] };
  }],
  ['durduruldu', re(`^(\\S+) işi durduruldu: ${WHAT}\\.\\s*(.*)$`), (m) => {
    const parts = bolDerinlik(m[4], true);
    return { baslik: T('{proje} işi durduruldu', { proje: m[1] }), is: m[3],
      satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], ...(parts[0] ? [[T('Neden'), parts[0].replace(/\.$/, '')]] : []),
        ...(parts[1] && !ceoOnly().test(parts[1]) ? [[T('Oturum'), parts[1]]] : [])] };
  }],
  ['yukseltme', re(`^(\\S+) işi bir üst katmana taşındı: ${WHAT}\\.`), (m) => {
    const k = m.input.match(/Kontrol (\d+)\. denemede de geçmedi/);
    const t = m.input.match(/iş (\S+) yerine (\S+) katmanında/);
    const n = m.input.match(re(`yeniden açıldı: ${STEM}\\.`));
    return { baslik: T('{proje} işi bir üst katmana taşındı', { proje: m[1] }), is: m[3],
      satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], ...(k ? [[T('Neden'), T('Kontrol {n}. denemede de geçmedi', { n: k[1] })]] : []),
        ...(t ? [[T('Katman'), `${t[1]} → ${t[2]}`]] : []), ...(n ? [[T('Yeni iş'), n[1]]] : [])] };
  }],
  ['onay', /^(\S+) akışı onay bekliyor: (.+?) \(([^()\s]+)\)\. Kararlar notu yazıldı: (\S+?)\.(?:\s|$)/, (m) => ({
    baslik: T('{proje} akışı onayını bekliyor', { proje: m[1] }), karar: m[4],
    satirlar: [[T('Proje'), m[1]], [T('Akış'), m[2]], [T('Karar kartı'), m[4]]] })],
  ['akis-durdu', /^(\S+) akışı durdu: (.+?) \(([^()\s]+)\), adım (\S+) \(([^)]+)\)\. (.+?)\.(?:\s|$)/, (m) => ({
    baslik: T('{proje} akışı durdu', { proje: m[1] }),
    satirlar: [[T('Proje'), m[1]], [T('Akış'), m[2]], [T('Adım'), `${m[4]} · ${m[5]}`], [T('Neden'), m[6]]] })],
  ['grup', /^(\S+) grubu bitti: (.+?) \(([^()\s]+)\)\./, (m) => {
    const get = (r) => { const x = m.input.match(r); return x ? x[1] : ''; };
    const rapor = get(/Rapor: \[\[([^\]]+)\]\]/);
    const rows = [[T('İşler'), get(/(\d+ iş: [^.]+?)\.\s/)], [T('Kullanım'), get(/Toplam (?:kullanım|kayıtlı harcama):? ([^;]+);/)],
      [T('Açık kalan'), get(/açık kalan (\d+)/)], [T('Rapor'), rapor]].filter(([, v]) => v);
    return { baslik: T('{proje} grubu bitti: {grup}', { proje: m[1], grup: m[2] }), satirlar: rows, not: rapor };
  }],
  ['kota', re(`^(\\S+) işi: ${STEM} (kota döndüğü için|üçüncü kez kotaya takıldı)`), (m) => {
    const what = m.input.match(re(`(?:\\(|\\? )(.+?) \\(${m[2].replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\)`));
    return { baslik: m[3] === 'kota döndüğü için' ? T('{proje} işi kota döndü, devam ediyor', { proje: m[1] })
      : T('{proje} işi üçüncü kez kotaya takıldı', { proje: m[1] }), is: m[2],
    satirlar: [[T('Proje'), m[1]], [T('İş'), what ? what[1] : m[2]]] };
  }],
  ['izin', re(`^(\\S+) işi izin onayı bekliyor: ${WHAT}\\. Oturum (\\d+) dakikadır`), (m) => ({
    baslik: T('{proje} işi izin onayı bekliyor', { proje: m[1] }), is: m[3],
    satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], [T('Bekleme'), T('{n} dakika', { n: m[4] })]] })],
  ['ilerlemiyor', re(`^(\\S+) işi ilerlemiyor: ${WHAT}\\. Oturum (\\d+) dakika önce`), (m) => ({
    baslik: T('{proje} işi ilerlemiyor', { proje: m[1] }), is: m[3],
    satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], [T('Başlayalı'), T('{n} dakika', { n: m[4] })]] })],
  ['engel', re(`^(\\S+) işi bekliyor: ${WHAT}\\.\\s*(.*)$`), (m) => ({
    baslik: T('{proje} işi bekliyor', { proje: m[1] }), is: m[3],
    satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], ...(ilkParca(m[4]) ? [[T('Neden'), short(ilkParca(m[4]), 160)]] : [])] })],
  ['baslatilamadi', re(`^(\\S+) işi başlatılamadı: ${WHAT}\\.\\s*(.*)$`), (m) => ({
    baslik: T('{proje} işi başlatılamadı', { proje: m[1] }), is: m[3],
    satirlar: [[T('Proje'), m[1]], [T('İş'), m[2]], ...(ilkParca(m[4]) ? [[T('Neden'), short(ilkParca(m[4]), 160)]] : [])] })],
  ['birikti', /^Onay bekleyen (\d+) kart var/, (m) => ({
    baslik: T('Onay bekleyen kartlar birikti'), satirlar: [[T('Bekleyen kart'), m[1]]] })],
  ['zamanlama', /^(\S+) zamanlanmış işi (duraklatıldı|eklenemedi): (.+?)(?: \(|\.(?:\s|$)|$)/, (m) => ({
    baslik: m[2] === 'duraklatıldı' ? T('{proje} zamanlanmış işi duraklatıldı', { proje: m[1] })
      : T('{proje} zamanlanmış işi eklenemedi', { proje: m[1] }), satirlar: [[T('Proje'), m[1]], [T('İş'), m[3]]] })],
  ['kadro', /^(\S+) (?:kadro|model) önerisi: (\S+) işler için sonraki (\d+) iş (.+?) yerine (.+?) ile denensin mi\? Karar kartı: \[\[([^\]]+)\]\]/, (m) => ({
    baslik: T('{proje} için kadro önerisi', { proje: m[1] }), karar: m[6], not: m[6],
    satirlar: [[T('Proje'), m[1]], [T('Katman'), m[2]], [T('Öneri'), T('{eski} yerine {yeni}, {n} iş', { eski: m[4], yeni: m[5], n: m[3] })]] })],
  ['kadro-sonuc', /^(\S+) (?:kadro denemesi|model pilotu) bitti: (\S+) işler (.+?) ile \((\d+) iş\)\. (.+?)\. Karar kartı: \[\[([^\]]+)\]\]/, (m) => ({
    baslik: T('{proje} kadro denemesi bitti', { proje: m[1] }), karar: m[6], not: m[6],
    satirlar: [[T('Proje'), m[1]], [T('Katman'), m[2]], [T('Deneme'), T('{calisan}, {n} iş', { calisan: m[3], n: m[4] })], [T('Sonuç'), m[5]]] })],
  ['hatirlatma', /^(\S+) (?:kadro kararı (\d+) gündür cevap bekliyor|model denemesinin işi (\d+) gündür başlamadı)/, (m) => {
    const link = m.input.match(/\[\[([^\]]+)\]\]/);
    return { baslik: m[2] ? T('{proje} kadro kararı cevap bekliyor', { proje: m[1] })
      : T('{proje} kadro denemesinin işi başlamadı', { proje: m[1] }),
      karar: link ? link[1] : '', not: link ? link[1] : '',
      satirlar: [[T('Proje'), m[1]], [T('Bekleme'), T('{n} gün', { n: m[2] || m[3] })]] };
  }],
  // the end-of-day review (bin/gunsonu.py): "Gün sonu değerlendirmesi hazır: [[GunSonu-…]] — <gün>." + "- İşler: …",
  // "- Kötü giden: …"; then "Gün sonu önerileri eklendi: [[GunSonu-…]] — değerlendirme işi [[<iş>]] bitti."
  ['gunsonu', /^Gün sonu değerlendirmesi hazır: \[\[([^\]]+)\]\](?: — (.+?)\.)?$/, (m, c) => {
    const rows = [];
    for (const line of c.satirlar) {
      const x = line.match(GUNSONU_SATIRI);
      if (x) rows.push([T(x[1]), ceoKisminiGizle(x[2]).replace(/\[\[([^\]|]+)\]\]/g, '$1')]);
    }
    return { baslik: T('Gün sonu değerlendirmesi · {gun}', { gun: m[2] || m[1] }), satirlar: rows, not: m[1] };
  }],
  ['gunsonu-oneri', /^Gün sonu önerileri eklendi: \[\[([^\]]+)\]\] — değerlendirme işi \[\[([^\]]+)\]\] bitti\./, (m, c) => {
    const x = c.satirlar.map((l) => l.match(/^- Kod düzeltmesi: (\d+) · CLAUDE\.md satırı: (\d+) · REVIEW\.md satırı: (\d+)$/)).find(Boolean);
    return { baslik: T('Gün sonu önerileri eklendi'), not: m[1], is: m[2],
      satirlar: [[T('Not'), m[1]], ...(x ? [[T('Kod düzeltmesi'), x[1]], [T('Kural önerisi'), String(Number(x[2]) + Number(x[3]))]] : [])] };
  }],
  ['sunucu', /^Sunucu odası \(([^)]+)\): (.+?)\.(?:\s|$)/, (m) => ({
    baslik: T('Sunucu odası: {proje}', { proje: m[1] }), satirlar: [[T('Proje'), m[1]], [T('Durum'), m[2]]] })],
  // "<Owner>'in duyurusu N oturuma iletildi" (bin/duyuru.py notice; the owner's name in any form)
  ['duyuru', /^\S[^\n]{0,60}?['’]n?[ıiuü]n duyurusu (\d+) oturuma iletildi(?:, (\d+) oturuma iletilemedi)?/, (m) => {
    const link = m.input.match(/\[\[([^\]]+)\]\]/);
    return { baslik: T('{sahip_in} duyurusu iletildi', { sahip_in: sahip('in') }), not: link ? link[1] : '',
      satirlar: [[T('İletilen'), T('{n} oturum', { n: m[1] })], ...(m[2] ? [[T('İletilemeyen'), T('{n} oturum', { n: m[2] })]] : []),
        ...(link ? [[T('Not'), link[1]]] : [])] };
  }],
];

export function bildirimKarti(text) {
  const lines = String(text || '').split('\n');
  const first = (lines[0] || '').trim();
  const rest = lines.slice(1);
  const quoted = rest.filter((l) => /^>/.test(l)).map((l) => l.replace(/^> ?/, ''));
  const plain = rest.filter((l) => !/^>/.test(l)).map((l) => l.trim()).filter(Boolean);
  const ctx = { satirlar: plain, ilk: (quoted.find((l) => l.trim()) || '').trim(), rapor: quoted.join('\n').trim() };
  let tur = 'diger';
  let f = null;
  for (const [kind, pattern, build] of KART_KALIPLARI) {
    const m = first.match(pattern);
    if (m) { tur = kind; f = build(m, ctx); break; }
  }
  if (!f) {
    const shown = ilkCumle(first);
    f = { baslik: shown ? short(shown, 140) : T('Bildirim'), satirlar: [] };
  }
  const [etiket, ikon, tone] = KART_TURU[tur];
  const not = f.not || '';
  const ham = [ceoKisminiGizle(first), ...rest.map((l) => (/^>/.test(l) ? l.replace(/^> ?/, '') : ceoKisminiGizle(l)))]
    .join('\n').replace(/\n+$/, '').replace(/^\n+/, '');
  return { tur, etiket: T(etiket), ikon, tone, baslik: f.baslik, satirlar: f.satirlar.filter(([, v]) => v !== '' && v != null),
    karar: f.karar || '', is: f.is || '', not, klasor: not ? notKlasoru(not, tur) : '', ham,
    teknik: ctx.rapor, teknikBaslik: f.teknikBaslik || T('Teknik rapor (projenin kendi metni)') };
}

// --- Obsidian links: every [[note]] on the page opens the note in the Obsidian app ---

// "a [[b]] c" -> [{metin: 'a '}, {not: 'b', gorunen: 'b'}, {metin: ' c'}]; "[[b|Label]]" shows Label, "[[b#x]]" opens
// b. A name with a path (/, \) or starting with "." stays plain text.
export function wikiParcalari(text) {
  const s = String(text == null ? '' : text);
  const out = [];
  const add = (metin) => {
    if (!metin) return;
    const last = out[out.length - 1];
    if (last && last.metin != null) last.metin += metin; else out.push({ metin });
  };
  let at = 0;
  for (const m of s.matchAll(/\[\[([^[\]|#\n]{1,200})(?:#[^[\]|\n]*)?(?:\|([^[\]\n]{1,200}))?\]\]/g)) {
    const name = m[1].trim();
    add(s.slice(at, m.index));
    if (!name || /[\\/]/.test(name) || name.startsWith('.')) add(m[0]);
    else out.push({ not: name, gorunen: (m[2] || '').trim() || name });
    at = m.index + m[0].length;
  }
  add(s.slice(at));
  return out.length ? out : [{ metin: '' }];
}

// The OFIS sub-folder a note most likely lives in (the server prefers it when a bare name exists in several folders,
// e.g. [[2026-11-13]] is the morning summary); '' when nothing hints.
export function notKlasoru(ad, tur) {
  const n = String(ad || '');
  if (/^ArGe-/.test(n) || /^Yakala-/.test(n)) return 'ArGe'; // the Yakala notes live there too (bin/yakala.py)
  if (/^GunSonu-/.test(n)) return 'GunSonu'; // the end-of-day review notes (bin/gunsonu.py)
  if (/^[a-z]{2,20}-hafiza$/.test(n)) return 'Calisanlar'; // the worker memory notes (bin/hafiza.py)
  if (tur === 'sabah') return 'Ozetler';
  if (tur === 'grup') return 'Raporlar';
  if (tur === 'duyuru') return 'Duyurular';
  if (['soru', 'onay', 'kadro', 'kadro-sonuc', 'hatirlatma', 'birikti', 'mudur'].includes(tur)) return 'Kararlar';
  if (/^\d{4}-\d{2}-\d{2}$/.test(n)) return 'Ozetler';
  if (/^\d{4}-\d{2}-\d{2}-\d{4,6}-/.test(n)) return 'Isler';
  return '';
}

// obsidian://open?vault=<vault>&file=<path> for a note under OFIS (the path relative to the vault, without .md);
// '' for anything else.
export function obsidianUri(kasa, yol) {
  const v = String(kasa || '');
  const p = String(yol || '');
  if (!v || /[\x00-\x1f]/.test(v) || /[\x00-\x1f\\]/.test(p)) return '';
  const parts = p.split('/');
  if (parts.length < 2 || parts[0] !== 'OFIS' || parts.some((x) => !x || x === '.' || x === '..')) return '';
  return `obsidian://open?vault=${encodeURIComponent(v)}&file=${encodeURIComponent(p)}`;
}

// The only href a note link ever gets: an obsidian://open URI (never javascript:, data:, http…).
export function obsidianHref(u) {
  return typeof u === 'string' && /^obsidian:\/\/open\?vault=[^&\s]+&file=[^&\s]+$/.test(u) ? u : '';
}

// "ofis-ornek-uygulama-1110-183820-ab12" -> "ornek-uygulama"
export function projectOfSession(name) {
  const s = String(name || '');
  const m = s.match(/^ofis-(.+?)-\d{4}-\d{6}-[0-9a-z]+$/);
  if (m) return m[1];
  return s.replace(/^ofis-/, '').split('-')[0] || s;
}

function short(text, max = 160) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

// One Turkish line per problem the post office reports; [] when all is well.
export function postofficeWarnings(po) {
  if (!po || typeof po !== 'object') return [];
  const out = [];
  const add = (line) => { if (!out.includes(line)) out.push(line); };
  const sessionErrors = new Set();
  const sessionLines = [];
  for (const [name, s] of Object.entries(po.sessions || {})) {
    if (s && s.error) {
      sessionErrors.add(s.error);
      // a launch whose line claude printed differently: the answer WAS delivered (bin/channel.py is_launch_warning);
      // the server drops the line after a confirmed delivery or fork, or once the job is final
      const launch = /^warning: .*without the expected launch line(?:; output: ([\s\S]*))?$/.exec(String(s.error));
      sessionLines.push(launch
        ? T("{proje} oturumuna cevap iletildi, ama claude'un çıktısı tanınmadı", { proje: projectOfSession(name) }) +
          (launch[1] ? `: ${short(launch[1], 320)}` : '')
        : T('{proje} oturumuna cevap iletilemiyor: {hata}', { proje: projectOfSession(name), hata: short(s.error) }));
    }
  }
  if (po.last_error && !sessionErrors.has(po.last_error)) add(T('Mesaj iletilemedi: {hata}', { hata: short(po.last_error) }));
  sessionLines.forEach(add);
  for (const s of po.silent || []) {
    const minutes = Math.max(2, Math.floor((Number(s.seconds) || 0) / 60));
    const who = s.proje || projectOfSession(s.oturum);
    add(s.izin
      ? T('{proje} işi {n} dakikadır izin bekliyor: oturum bir izin sorusunda duruyor, kendiliğinden ilerlemez', { proje: who, n: minutes })
      : T('{proje} işi {n} dakikadır sessiz: oturum boşta, rapor gelmedi', { proje: who, n: minutes }));
  }
  if (po.rejected > 0) add(T('{n} proje raporu kabul edilmedi', { n: po.rejected }));
  if (po.rejected_outbox > 0) add(T('{n} cevap projeye ulaştırılamadı', { n: po.rejected_outbox }));
  return out;
}

// Budget use of an active job ("$1,25 / $5,00 · 12 / 40 çağrı"); "" for a finished job or when no limit is known.
// spent / calls are the server's recorded harcanan_usd / cagri (updated in steps), budget / max_calls the limits.
const ACTIVE = new Set(['baslatiliyor', 'calisiyor', 'karar-bekliyor', 'incelemede', 'kontrolde']);

// Below $0,10 three significant digits ($0,002, $0,0123), else two decimals: a small budget is never "$0,00".
function usd(v) {
  const n = Number(v) || 0;
  if (n !== 0 && Math.abs(n) < 0.1) {
    return '≈$' + n.toLocaleString(yerel(), { maximumSignificantDigits: 3 });
  }
  return '≈$' + n.toLocaleString(yerel(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Token counts next to the dollars. Twin of bin/budget.py token_text (keep both in step; test_web checks the same
// cases): "850 token", "12,4 bin token", "182 bin token", "1,2 mn token"; "" when unknown (a job from before tokens
// were recorded) — never "0 token" for a missing value.
export function tokenSayisi(v) {
  if (v == null || v === '' || typeof v === 'boolean') return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? Math.floor(n) : null;
}

// A count of tenths as "12,4" / "1" (no ",0"). Integer arithmetic, half-up: the same digits as bin/budget.py.
function onda(t) {
  return t % 10 ? `${Math.floor(t / 10)}${aktifDil() === 'en' ? '.' : ','}${t % 10}` : String(t / 10);
}

export function tokenMetni(v) {
  const n = tokenSayisi(v);
  if (n === null) return '';
  if (n < 1000) return T('{n} token', { n });
  if (n < 999500) {
    const t = Math.floor((n + 50) / 100);
    return T('{n} bin token', { n: t < 1000 ? onda(t) : Math.floor((n + 500) / 1000) });
  }
  const t = Math.floor((n + 50000) / 100000);
  return T('{n} mn token', { n: t < 1000 ? onda(t) : Math.floor((n + 500000) / 1000000) });
}

// "$0,41 · 182 bin token"; the dollars alone when the tokens are unknown; "—" when nothing is known.
export function harcamaText(spent, tokens) {
  const tok = tokenMetni(tokens);
  if ((spent == null || spent === '') && !tok) return '—';
  const money = spent == null || spent === '' ? '' : usd(spent);
  return [tok, money].filter(Boolean).join(' · ');
}

export function budgetText(t) {
  if (!t || !ACTIVE.has(t.status) || t.step_kind === 'onay') return '';  // the approval step has no session
  const hasBudget = t.budget != null && t.budget !== '';
  const hasCalls = t.max_calls != null && t.max_calls !== '';
  if (!hasBudget && !hasCalls) return '';
  const tok = tokenMetni(t.tokens);
  const money = `${tok ? `${tok} · ` : ''}${usd(t.spent)} / ${hasBudget ? usd(t.budget) : '?'}`;
  return `${money} · ${T('{n} / {max} çağrı', { n: Number(t.calls) || 0, max: hasCalls ? t.max_calls : '?' })}`;
}

// Phase 3 (dispatcher). A queued job: its place in its project's queue, a hold, the jobs it waits for and an engel
// (a dependency that got stuck or was cancelled). "" for a job that is not queued.
const stemOf = (n) => String(n || '').replace(/\.md$/, '');

export function queueText(t) {
  if (!t || t.status !== 'sirada' || t.queue_position == null) return '';
  const parts = [T('sırada {n}.', { n: t.queue_position })];
  if (t.held) parts.push(T('bekletiliyor ({sahip} bırakınca başlar)', { sahip: sahip() }));
  if (t.blocked) parts.push(T('engel: {neden}', { neden: t.blocked }));
  else if (t.depends && t.depends.length) parts.push(T('bekliyor: {isler}', { isler: t.depends.map(stemOf).join(', ') }));
  return parts.join(' · ');
}

// The top bar: running jobs against the global limit ("2/3 çalışıyor").
export function runningText(summary) {
  if (!summary || summary.max_running == null || summary.running == null) return '';
  return T('{n}/{max} çalışıyor', { n: summary.running, max: summary.max_running });
}

// The one top-bar pill (the owner, 2026-11-11: the separate N/M pill was confusing). n = working agents (CEO included).
// -> {metin, ton: '' | 'sinirda', baslik}. The running limit shows only when it matters (at the limit), and a hold
// by the approval backlog (summary.onay_birikti) is appended.
export function canliPill(summary, n) {
  const s = summary || {};
  const max = Number(s.max_running);
  const running = Number(s.running);
  const known = Number.isFinite(max) && max > 0 && Number.isFinite(running);
  const atLimit = known && running >= max;
  let metin = n > 0 ? T('{n} ajan çalışıyor', { n }) : T('Herkes dinleniyor');
  if (known && running > max) metin = T('{n} çalışıyor · sınır {max} aşıldı', { n: running, max });  // never "5/4"
  else if (atLimit) metin = T('{n}/{max} · sınırda, yeni işler sırada', { n: running, max });
  if (onayBiriktiMetni(s)) metin += ` · ${T('onay bekleniyor')}`;
  const baslik = known ? T('Aynı anda en çok {max} iş çalışır (ofis.json max_running) — şu an iş başında olanları göster', { max })
    : T('Şu an iş başında');
  return { metin, ton: atLimit ? 'sinirda' : '', baslik };
}

// The top bar's decision bell (the owner, 2026-11-12): the pending decision cards (state.decisions) without the ones
// already answered from the page (answer_sent, or sent in this tab: `gonderilen` notes) -> {sayi, metin, baslik,
// enEski: the oldest card's note (by `asked`; unknown times last), null when nothing waits}.
export function kararBildirimi(decisions, gonderilen = []) {
  const sent = new Set(Array.isArray(gonderilen) ? gonderilen : [...(gonderilen || [])]);
  const list = (Array.isArray(decisions) ? decisions : [])
    .filter((d) => d && typeof d === 'object' && d.note && !d.answer_sent && !sent.has(d.note));
  if (!list.length) return { sayi: 0, metin: '', baslik: '', enEski: null };
  const at = (d) => { const x = Date.parse(d.asked); return Number.isFinite(x) ? x : Infinity; };
  const oldest = list.reduce((a, d) => (at(d) < at(a) ? d : a));
  const n = list.length;
  return { sayi: n, metin: T('{n} karar bekliyor', { n }),
    baslik: T('{n} karar seni bekliyor — en eskisini aç: {baslik}', { n, baslik: oldest.title || oldest.note }), enEski: oldest.note };
}

// The right panel header's "Seni bekleyen: N" (owner decision 2026-11-14): the bell's count (kararBildirimi.sayi: decision
// cards incl. the CEO's own questions, answered ones and manager cards left out); "" when nothing waits.
export const seniBekleyenMetni = (n) => (Number.isFinite(n) && n > 0 ? T('Seni bekleyen: {n}', { n }) : '');

// --- The CEO's own question (`ofis.py sor`, tur: ceo-sorusu; owner decision 2026-11-14) ---
export const CEO_SORUSU = 'ceo-sorusu';
const SECENEK_KODU = /^[A-E]$/;
// The answer buttons of a ceo-sorusu card: [{kod, metin, cevap}] (at most 5, valid codes only, no duplicates);
// `cevap` is what the button sends through the normal answer POST ("A) <metin>", so the note reads plainly and
// `cevapla` still finds the choice). Any other card: [].
export function secenekDugmeleri(d) {
  if (!d || typeof d !== 'object' || d.kind !== CEO_SORUSU || !Array.isArray(d.options)) return [];
  const seen = new Set();
  const out = [];
  for (const o of d.options) {
    const kod = o && typeof o === 'object' ? String(o.kod || '') : '';
    const metin = o && typeof o === 'object' ? String(o.metin || '').replace(/\s+/g, ' ').trim() : '';
    if (!SECENEK_KODU.test(kod) || !metin || seen.has(kod)) continue;
    seen.add(kod);
    out.push({ kod, metin, cevap: `${kod}) ${metin}` });
    if (out.length === 5) break;
  }
  return out;
}

// The "cevap bekliyor" badges of the CEO chat: for each ceo-sorusu card that still waits (not answered from the page:
// answer_sent or a `gonderilen` note), the CEO line of the same turn. A CEO line that names the note (its name without
// ".md") wins (the last one); else the CEO line closest in time to the card's `asked`, within 5 minutes before and
// 15 after (the reply ends the turn that ran `ofis.py sor`). -> {<chat index>: [{note, baslik}]}; a card without a
// matching line gets no badge (its card and the bell still show it).
export const ROZET_ONCE_MS = 5 * 60 * 1000;
export const ROZET_SONRA_MS = 15 * 60 * 1000;
export function cevapBekleyenRozetleri(chat, decisions, gonderilen = []) {
  const sent = new Set(Array.isArray(gonderilen) ? gonderilen : [...(gonderilen || [])]);
  const lines = (Array.isArray(chat) ? chat : []).map((m, i) => ({ m, i }))
    .filter(({ m }) => m && typeof m === 'object' && m.role === 'ceo' && String(m.text || '').trim());
  const out = {};
  for (const d of Array.isArray(decisions) ? decisions : []) {
    if (!d || typeof d !== 'object' || d.kind !== CEO_SORUSU || !d.note || d.answer_sent || sent.has(d.note)) continue;
    const kok = String(d.note).replace(/\.md$/, '');
    // the whole name only: "…-ceo-sorusu" must not match a line that names "…-ceo-sorusu-2"
    const adi = new RegExp(`(?<![\\w-])${kok.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\w-])`, 'u');
    let hit = null;
    for (const x of lines) if (kok && adi.test(String(x.m.text))) hit = x;
    if (!hit) {
      const at = Date.parse(d.asked);
      if (Number.isFinite(at)) {
        let best = Infinity;
        for (const x of lines) {
          const t = Date.parse(x.m.time);
          if (!Number.isFinite(t) || t < at - ROZET_ONCE_MS || t > at + ROZET_SONRA_MS) continue;
          if (Math.abs(t - at) < best) { best = Math.abs(t - at); hit = x; }
        }
      }
    }
    if (hit) (out[hit.i] = out[hit.i] || []).push({ note: d.note, baslik: String(d.title || d.note) });
  }
  return out;
}

// --- "İş bitti" toasts (the owner, 2026-11-14: a finished job was visible only inside the CEO chat) ---
// The events between two /api/state snapshots that get a toast: a job done, a job stuck / failed to start, a new
// decision for the owner ("CEO soruyor"), a manager's new decision. Only changes count: without an earlier snapshot (the
// page just loaded) nothing — what existed before the page opened never pops up. Each item = {anahtar (dedupe key),
// tur ('bitti' | 'takildi' | 'soru' | 'mudur'), ikon, metin, is (job note) | karar (decision note)}; text only.
export const TOAST_EN_COK = 3;
export const TOAST_SURE_MS = 6000;
const toastKisa = (x, max = 80) => {
  const t = String(x == null ? '' : x).replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
};
export function toastOlaylari(prev, cur) {
  if (!prev || typeof prev !== 'object' || !cur || typeof cur !== 'object') return [];
  const liste = (o, k) => (Array.isArray(o[k]) ? o[k].filter((x) => x && typeof x === 'object' && x.note) : []);
  const out = [];
  const once = new Map(liste(prev, 'tasks').map((t) => [t.note, t.status]));
  for (const t of liste(cur, 'tasks')) {
    const was = once.get(t.note);
    if (was === t.status) continue;
    const proje = toastKisa(t.project, 40) || T('Bir proje');
    const baslik = toastKisa(t.title) || T('iş');
    if (t.status === 'bitti') {
      out.push({ anahtar: `bitti:${t.note}`, tur: 'bitti', ikon: '✓', metin: T('{proje} işi bitti · {baslik}', { proje, baslik }), is: t.note });
    } else if (t.status === 'tikandi' || t.status === 'basarisiz') {
      out.push({ anahtar: `${t.status}:${t.note}`, tur: 'takildi', ikon: '!',
        metin: t.status === 'basarisiz' ? T('{proje} işi başlatılamadı · {baslik}', { proje, baslik })
          : T('{proje} işi takıldı · {baslik}', { proje, baslik }), is: t.note });
    }
  }
  const sorular = new Set(liste(prev, 'decisions').map((d) => d.note));
  for (const d of liste(cur, 'decisions')) {
    if (sorular.has(d.note) || d.answer_sent) continue;
    out.push({ anahtar: `soru:${d.note}`, tur: 'soru', ikon: '?',
      metin: T('CEO soruyor · {proje}: {baslik}', { proje: toastKisa(d.project, 40) || T('ofis'),
        baslik: toastKisa(d.title) || T('bir karar bekliyor') }), karar: d.note });
  }
  // a manager's decision: a card that newly reads "cevapladi" (a new card or one the manager was still looking at)
  const mudur = new Map(liste(prev, 'mudur_kararlari').map((d) => [d.note, d.durum]));
  for (const d of liste(cur, 'mudur_kararlari')) {
    if (d.durum !== 'cevapladi' || mudur.get(d.note) === 'cevapladi') continue;
    out.push({ anahtar: `mudur:${d.note}`, tur: 'mudur', ikon: '✓',
      metin: T('Müdür kararı · {unvan} · {proje}: {baslik}', { unvan: toastKisa(d.unvan, 30) || T('Müdür'),
        proje: toastKisa(d.project, 40) || T('ofis'), baslik: toastKisa(d.title) || T('teknik soru') }),
      karar: d.note, is: String(d.is || '') });
  }
  return out;
}

// The toast stack after adding `yeni`: newest first, one per key, at most `max` (the oldest drop off).
export function toastYigini(yigin, yeni, max = TOAST_EN_COK) {
  const list = [...(Array.isArray(yeni) ? yeni : [])].reverse().concat(Array.isArray(yigin) ? yigin : []);
  const seen = new Set();
  return list.filter((x) => x && !seen.has(x.anahtar) && seen.add(x.anahtar)).slice(0, Math.max(0, max));
}

// A manager card of /api/state.mudur_kararlari (step 4, bin/mudur.py kararlar): {rozet, sinif, cevap, ipucu, yer}.
// "bakiyor": the manager is looking at the question (the owner may answer first); "cevapladi": its answer went to the
// session and the owner may replace it. Text only.
export function mudurKarti(d) {
  const x = d && typeof d === 'object' ? d : {};
  const unvan = String(x.unvan || T('Müdür'));
  if (x.durum === 'bakiyor') {
    return { rozet: T('{unvan} bakıyor', { unvan }), sinif: 'is-mudur-bakiyor', cevap: '',
      ipucu: T('Teknik bir soru: önce müdür bakıyor. İstersen sen şimdi cevapla; senin cevabın geçerli olur.'),
      yer: T('Cevabın (isteğe bağlı)…') };
  }
  return { rozet: T('Müdür kararı · {unvan}', { unvan }), sinif: 'is-mudur', cevap: String(x.cevap || ''),
    ipucu: T('{unvan} cevapladı, cevap oturuma iletildi. Değiştirmek istersen kendi cevabını yaz: senin cevabın geçerli olur.', { unvan }),
    yer: T('Müdürün cevabını değiştirmek için cevabın…') };
}

// --- "CEO yazdı" toasts and the unread badge (the owner, 2026-11-14: a CEO reply went unnoticed while the chat was closed) ---
// `fresh` = the chat lines that are new since the last /api/chat snapshot (never the ones that existed at load: the
// caller passes none before the chat is seeded). Only the CEO's own replies count (not the owner's, notices, relays).
export const ceoSatiri = (m) => !!m && typeof m === 'object' && m.role === 'ceo' && String(m.text || '').trim() !== '';
// The toast items for the new CEO lines: {anahtar, tur: 'ceo', ikon, metin: "CEO yazdı: <first ~80 chars>", mesaj: key}.
export function ceoToastlari(fresh, anahtarOf) {
  return (Array.isArray(fresh) ? fresh : []).filter(ceoSatiri).map((m) => {
    const key = typeof anahtarOf === 'function' ? anahtarOf(m) : `${m.time}|${m.role}`;
    return { anahtar: `ceo:${key}`, tur: 'ceo', ikon: '💬', metin: T('CEO yazdı: {metin}', { metin: toastKisa(m.text) }), mesaj: key };
  });
}
// The chat counts as "not seen" while neither the drawer nor the Komuta masası is open, or the tab is hidden.
export const sohbetGorulmedi = (cekmeceAcik, komutaAcik, sekmeGizli) => !!sekmeGizli || !(cekmeceAcik || komutaAcik);
// The unread count after `yeni` new CEO lines: grows only while the chat is not seen; a seen chat resets it.
export function okunmamisSayi(onceki, yeni, gorulmedi) {
  const n = Number.isFinite(onceki) && onceki > 0 ? Math.floor(onceki) : 0;
  if (!gorulmedi) return 0;
  return n + (Number.isFinite(yeni) && yeni > 0 ? Math.floor(yeni) : 0);
}
// The badge text on "CEO ile sohbet": '' for none, the number, "9+" above nine.
export const okunmamisMetni = (n) => (!Number.isFinite(n) || n < 1 ? '' : n > 9 ? '9+' : String(Math.floor(n)));
// The number in the tab title's "(N) " prefix: the waiting decisions, plus the unread CEO lines while the tab is hidden.
export function sekmeSayisi(karar, okunmamis, sekmeGizli) {
  const k = Number.isFinite(karar) && karar > 0 ? karar : 0;
  const u = sekmeGizli && Number.isFinite(okunmamis) && okunmamis > 0 ? okunmamis : 0;
  return k + u;
}

// The browser tab title with the "(N) " prefix while N decisions wait (an older prefix is replaced).
export function sekmeBasligi(base, n) {
  const clean = String(base || '').replace(/^\(\d+\) /, '');
  return n > 0 ? `(${n}) ${clean}` : clean;
}

// The bell pulses once when the count rises; never on the first render (prev unknown).
export function kararArtti(prev, cur) {
  return Number.isFinite(prev) && Number.isFinite(cur) && cur > prev;
}

// summary.onay_birikti = {bekleyen, sinir} (bin/dispatcher.py) -> the strip's line, or '' when nothing is held.
export function onayBiriktiMetni(summary) {
  const o = summary && summary.onay_birikti;
  if (!o || typeof o !== 'object') return '';
  const n = o.bekleyen;
  const max = o.sinir;
  if (!Number.isInteger(n) || !Number.isInteger(max) || max <= 0 || n < max) return '';
  return T('Onay bekleyen {n} kart var; yeni kod işleri bekliyor', { n });
}

// A queued job held by the approval backlog (task.onay_birikti from /api/state) -> the board's line.
// Step 4: a queued job whose model and its quota backup are both on quota (task.kota_bekliyor) waits too.
export function onayBekletmeMetni(t) {
  if (t && t.onay_birikti === true) return T('onay birikişi nedeniyle bekliyor');
  return t && typeof t.kota_bekliyor === 'string' && t.kota_bekliyor ? T('kota nedeniyle bekliyor: {model}', { model: t.kota_bekliyor }) : '';
}

// Step 5: a running job the server resumed after its usage limit reset (task.kota_devam = the time, server record).
export function kotaDevamMetni(t) {
  const m = t && typeof t.kota_devam === 'string' ? /T(\d{2}):(\d{2})/.exec(t.kota_devam) : null;
  return m ? T('kota döndü, devam ettirildi ({saat})', { saat: `${m[1]}:${m[2]}` }) : '';
}

// --- an approval card: evidence first, the summary last; the optional quiz ---

// The card's sections in reading order (bin/akis.py approval_card, bin/state.py EVIDENCE). Unknown titles keep their
// place before the summary; "Plan özeti" and "Kullanım" (older cards: "Maliyet") always come last.
export const KART_SIRASI = ['Nasıl test edildi', 'Kontrol (kanıt)', 'Kontrol neyi kanıtladı / kanıtlamadı',
  'Ajanın kararları ve varsayımları', 'Değişiklik özeti', 'İnceleme', 'Güvenlik', 'Nasıl geri alınır', 'Plan özeti',
  'Kullanım', 'Maliyet'];
export function kartBolumleri(evidence) {
  const list = Array.isArray(evidence) ? evidence.filter((e) => e && typeof e.title === 'string') : [];
  const rank = (e) => {
    const i = KART_SIRASI.indexOf(e.title);
    return i >= 0 ? i : KART_SIRASI.indexOf('Plan özeti') - 0.5;
  };
  return list.map((e, i) => [e, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0]);
}

// d.quiz = [{soru, cevap}] -> [{baslik, soru, cevap}] (strings only, at most 3); [] when there is none.
export function sinavMaddeleri(quiz) {
  if (!Array.isArray(quiz)) return [];
  return quiz.filter((q) => q && typeof q.soru === 'string' && typeof q.cevap === 'string' && q.soru && q.cevap)
    .slice(0, 3).map((q, i) => ({ baslik: T('Soru {n}', { n: i + 1 }), soru: q.soru, cevap: q.cevap }));
}
export const SINAV_BASLIGI = N_('Kendini yokla (isteğe bağlı)'); // drawn with T() (app.js)

// A job reopened one tier up after its Kontrol failed twice (escalated_from = the job it replaces).
export function escalationText(t) {
  return t && t.escalated_from ? T('↑ yükseltme') : '';
}

// Phase 4 (workflows). A workflow step's label ("adım 2 · plan incelemesi"); "" for a plain job.
const STEP_TR = { plan: N_('plan'), 'plan-inceleme': N_('plan incelemesi'), kod: N_('kod'), 'kod-inceleme': N_('kod incelemesi'),
  onay: N_('onay') };

export function stepText(t) {
  if (!t || !t.step_kind) return '';
  return T('adım {n} · {tur}', { n: t.step, tur: STEP_TR[t.step_kind] ? T(STEP_TR[t.step_kind]) : t.step_kind });
}

// "2/5 adım" plus what the workflow waits for when it is not simply running.
// (`deniz` is the stored state of a workflow stopped for the owner's decision: bin/akis.py keeps the value)
const WORKFLOW_STATE = { deniz: N_('durdu, {sahip_in} kararı bekleniyor'), 'onay-bekliyor': N_('onay bekliyor'), bitti: N_('bitti'),
  iptal: N_('iptal edildi'), ceo: N_("{sahip_in} cevabı CEO'da") };

export function workflowProgressText(w) {
  if (!w || w.toplam == null) return '';
  const extra = WORKFLOW_STATE[w.durum] ? T(WORKFLOW_STATE[w.durum], { sahip_in: sahip('in') }) : '';
  return T('{tamam}/{toplam} adım', { tamam: Number(w.tamam) || 0, toplam: w.toplam }) + (extra ? ` · ${extra}` : '');
}

// Tasks (newest first) with the steps of one workflow gathered at the place of its newest step, in step order
// (rounds by creation): [{kind: 'workflow', id, title, progress, tasks}] or [{kind: 'task', task}].
export function groupTasks(tasks, workflows) {
  const info = new Map((workflows || []).map((w) => [w.grup, w]));
  const out = [];
  const groups = new Map();
  for (const t of tasks || []) {
    if (!t.workflow) { out.push({ kind: 'task', task: t }); continue; }
    let g = groups.get(t.workflow);
    if (!g) {
      const w = info.get(t.workflow);
      g = { kind: 'workflow', id: t.workflow, title: w ? w.baslik : t.workflow,
        progress: w ? workflowProgressText(w) : '', tasks: [] };
      groups.set(t.workflow, g);
      out.push(g);
    }
    g.tasks.push(t);
  }
  for (const g of groups.values()) {
    g.tasks.sort((a, b) => (Number(a.step) - Number(b.step)) || String(a.created || '').localeCompare(String(b.created || ''))
      || String(a.note).localeCompare(String(b.note)));
  }
  return out;
}

// The task detail's workflow line: "Karar: DÜZELT · tur 2 · yürütücü: codex".
export function verdictText(w) {
  if (!w) return '';
  const parts = [];
  if (w.karar) parts.push(T('Karar: {karar}', { karar: w.karar === 'onay' ? T('ONAY') : w.karar === 'duzelt' ? T('DÜZELT') : T('okunamadı') }));
  parts.push(T('tur {n}', { n: w.tur_no || 1 }));
  if (w.yurutucu && w.tur === 'kod-inceleme') parts.push(T('yürütücü: {ad}', { ad: w.yurutucu }));
  return parts.join(' · ');
}

// The outcome of POST /api/answer for a decision card: ok = the answer was taken now, sent = the card shows
// "cevap iletildi" instead of the answer box (also when the server refuses a second answer: the first one already
// went to the CEO), text = the toast.
export function answerResult(status, data) {
  const d = data || {};
  if (status === 202) {
    return { ok: true, sent: true, text: d.status === 'queued' ? T('Cevap sıraya alındı; CEO boşalınca iletilecek.') : T("Cevap CEO'ya iletildi.") };
  }
  if (status === 409 && d.kod === 'cevap-iletildi') return { ok: false, sent: true, text: String(d.error || T('Bu karara cevabın zaten iletildi.')) };
  if (status === 409) return { ok: false, sent: false, text: `${T("CEO'ya ulaşılamadı.")} ${d.error || ''}` };
  if (status === 403) return { ok: false, sent: false, text: T('İstek reddedildi; sayfayı yenile.') };
  if (status === 0) return { ok: false, sent: false, text: T('Sunucu kapalı.') };
  return { ok: false, sent: false, text: d.error || T('Hata ({status}).', { status }) };
}

// --- The "Zamanlanmış" tab (owner decision 2026-11-13): one table row per schedule from state.schedules (bin/zamanla.py
// summaries) with the links to its last runs. Job names are bare note names (no ".md") for the Obsidian links. ---
export const KOSU_SONUCU = { bitti: N_('bitti'), tikandi: N_('takıldı'), basarisiz: N_('başlatılamadı'), iptal: N_('iptal edildi'),
  yok: N_('not bulunamadı'), '': N_('sürüyor') };
const kosuSonucu = (k) => (Object.prototype.hasOwnProperty.call(KOSU_SONUCU, k) ? T(KOSU_SONUCU[k]) : '');
const notAdi = (x) => String(x || '').replace(/\.md$/, '');
const slotMetni = (s) => {
  const m = String(s || '').match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[2]}.${m[1]} ${m[3]}` : '';
};
export function zamanlanmisSatirlari(schedules) {
  return (Array.isArray(schedules) ? schedules : []).filter((s) => s && typeof s === 'object' && s.ad).map((s) => {
    // the newest runs (older servers send only the last one: son_is / son_sonuc)
    let kosular = (Array.isArray(s.kosular) ? s.kosular : []).filter((r) => r && r.is).map((r) => ({
      zaman: slotMetni(r.slot), is: notAdi(r.is), sonuc: kosuSonucu(r.sonuc || '') || String(r.sonuc),
      son_is: notAdi(r.son_is) }));
    if (!kosular.length && s.son_is) {
      kosular = [{ zaman: '', is: notAdi(s.son_is), sonuc: kosuSonucu(s.son_sonuc || '') || String(s.son_sonuc), son_is: '' }];
    }
    const son = kosular[0] || null;
    return {
      ad: String(s.ad), proje: String(s.proje || ''), baslik: short(s.baslik || s.ad, 80), zaman: String(s.zaman || ''),
      sonraki: s.duraklatildi ? '—' : (slotMetni(s.sonraki) || '—'),
      durum: s.duraklatildi ? T('duraklatıldı') : T('etkin'), neden: s.duraklatildi ? String(s.neden || '') : '',
      duraklatildi: !!s.duraklatildi, // the code (app.js styles the row by it, not by the translated text)
      // the last run's result; a run with no job note yet but a known result (an older server) says so
      sonKosu: son ? `${son.sonuc}${son.zaman ? ` · ${son.zaman}` : ''}` : (s.son_sonuc ? kosuSonucu(s.son_sonuc) : T('henüz koşmadı')),
      kosular,
    };
  });
}

// --- The "Son olanlar" tab (owner decision 2026-11-13): each event's badge in the notice cards' look (bildirimKarti's tones:
// done, blocked, ask, info). A notice keeps its own badge (bildirimKarti); the page's own events use these. ---
const OLAY_ROZETI = {
  'is-basladi': [N_('İş başladı'), '▶', 'info'], 'is-bitti': [N_('İş bitti'), '✓', 'done'], takildi: [N_('Takıldı'), '!', 'blocked'],
  is: [N_('İş'), '•', 'info'], soru: [N_('Soru'), '?', 'ask'], cevaplandi: [N_('Cevaplandı'), '✓', 'done'], ceo: ['CEO', '✉', 'info'],
  proje: [N_('Proje mesajı'), '✉', 'info'], sistem: [N_('Sistem'), 'i', 'info'],
};
export function olayRozeti(tur) {
  const [etiket, ikon, tone] = OLAY_ROZETI[tur] || OLAY_ROZETI.sistem;
  return { etiket: T(etiket), ikon, tone };
}

// --- Phase 7: the İşler board, the Raporlar list and the Kalite panel ---

const FINAL = new Set(['bitti', 'tikandi', 'iptal', 'basarisiz']);
const WORKFLOW_CLOSED = new Set(['bitti', 'iptal', 'ceo']);

// The board column of one job: Sıradakiler, Devam edenler (running, waiting for a decision, in review or Kontrol)
// or Bitenler.
export function boardColumn(status) {
  if (status === 'sirada') return 'sirada';
  return FINAL.has(status) ? 'biten' : 'devam';
}

// A workflow is one card in one column: a running step puts it in "devam"; a closed workflow (approved, cancelled,
// handed to the CEO) is "biten"; one stopped for the owner needs attention, so "devam"; one with only queued steps left
// waits in "sirada"; anything else (every step final) is "biten".
function workflowColumn(item, w) {
  const cols = item.tasks.map((t) => boardColumn(t.status));
  if (cols.includes('devam')) return 'devam';
  if (w && WORKFLOW_CLOSED.has(w.durum)) return 'biten';
  if (w && w.durum === 'deniz') return 'devam';
  return cols.includes('sirada') ? 'sirada' : 'biten';
}

const itemTasks = (item) => (item.kind === 'task' ? [item.task] : item.tasks);
const latest = (item, pick) => itemTasks(item).map(pick).map(String).sort().pop() || '';
const earliest = (item, pick) => itemTasks(item).map(pick).map(String).filter(Boolean).sort()[0] || '';

// The board (state.board): {sirada, devam, biten, bitenGizli} — items as groupTasks() gives them. Sıradakiler oldest
// first (the dispatcher starts them in that order), Devam edenler newest start first, Bitenler newest end first and
// at most `doneLimit` (bitenGizli = how many finished items are not shown, plus `serverHidden`: the finished jobs the
// server did not send at all, state.board_hidden).
export function boardColumns(tasks, workflows, doneLimit = 20, serverHidden = 0) {
  const info = new Map((workflows || []).map((w) => [w.grup, w]));
  const cols = { sirada: [], devam: [], biten: [] };
  for (const item of groupTasks(tasks, workflows)) {
    const col = item.kind === 'task' ? boardColumn(item.task.status) : workflowColumn(item, info.get(item.id));
    cols[col].push(item);
  }
  const by = (key, desc) => (a, b) => (desc ? -1 : 1) * key(a).localeCompare(key(b));
  cols.sirada.sort(by((i) => earliest(i, (t) => t.created || t.started), false));
  cols.devam.sort(by((i) => latest(i, (t) => t.started || t.created), true));
  cols.biten.sort(by((i) => latest(i, (t) => t.finished || t.started || t.created), true));
  const hidden = Math.max(0, cols.biten.length - doneLimit) + (Number(serverHidden) || 0);
  cols.biten = cols.biten.slice(0, doneLimit);
  return { ...cols, bitenGizli: hidden };
}

const positive = (v) => v != null && v !== '' && Number(v) > 0;
const percent = (used, limit) => Math.min(100, Math.max(0, Math.round((100 * used) / limit)));

// A job's budget bars: recorded spending against butce_usd and model calls against max_cagri, for any status (a
// finished job shows its final spending). null when no limit is known, and for the approval step (no session).
export function budgetBar(t) {
  if (!t || t.step_kind === 'onay') return null;
  const hasBudget = positive(t.budget);
  const hasCalls = positive(t.max_calls);
  if (!hasBudget && !hasCalls) return null;
  const spent = Number(t.spent) || 0;
  const calls = Number(t.calls) || 0;
  return {
    money: hasBudget ? { pct: percent(spent, Number(t.budget)), over: spent > Number(t.budget),
      text: `${tokenMetni(t.tokens) ? `${tokenMetni(t.tokens)} · ` : ''}${usd(spent)} / ${usd(t.budget)}` } : null,
    calls: hasCalls ? { pct: percent(calls, Number(t.max_calls)), over: calls > Number(t.max_calls),
      text: T('{n} / {max} çağrı', { n: calls, max: t.max_calls }) } : null,
  };
}

// An amount from the server (Kalite, Raporlar); "—" when it is unknown (never "$0,00" for a missing value).
export function usdText(v) {
  return v == null || v === '' ? '—' : usd(v);
}

// "%50 (1/2)" like Ozet.md; "—" when nothing was measured.
export function ratioText(hits, total) {
  const n = Number(total) || 0;
  return n ? T('%{oran} ({gecen}/{toplam})', { oran: Math.round((100 * (Number(hits) || 0)) / n), gecen: Number(hits) || 0, toplam: n }) : '—';
}

export function minutesText(m) {
  if (m == null || m === '') return '—';
  const n = Number(m) || 0;
  return n < 120 ? T('{n} dk', { n }) : T('{sa} sa {dk} dk', { sa: Math.floor(n / 60), dk: n % 60 });
}

// A dollar metric with its token twin ("$0,27 · 182 bin token"); the dollars alone when the tokens are unknown and
// "—" when the dollars are unknown (a metric with no verified job has neither: never the tokens alone, never "0 token").
export function paraTokenMetni(usdValue, tokens) {
  if (usdValue == null || usdValue === '') return '—';
  const tok = tokenMetni(tokens);
  return (tok ? `${tok} · ` : '') + usd(usdValue);
}

// A total token count with how many jobs have none ("1,5 mn token (1 işte kayıtlı değil)"); "—" when none is known.
export function tokenToplamMetni(r) {
  const tok = tokenMetni(r && r.toplam_token);
  if (!tok) return '—';
  const missing = Number(r.token_bilinmeyen ?? r.token_eksik) || 0;
  return tok + (missing > 0 ? ` ${T('({n} işte kayıtlı değil)', { n: missing })}` : '');
}

// A report's recorded total; a Codex review has no known price, so the total leaves it out and says so.
export function reportCostText(r) {
  if (!r || r.toplam_usd == null || r.toplam_usd === '') return '—';
  const tok = tokenMetni(r.toplam_token) ? `${tokenToplamMetni(r)} · ` : '';
  return tok + usdText(r.toplam_usd) + (r.fiyat_bilinmiyor ? ` ${T('(Codex hariç; fiyatı bilinmiyor)')}` : '');
}

// A report's verified cost per job with its tokens (all known tokens / the jobs done with a passed Kontrol).
export function reportVerifiedText(r) {
  if (!r || r.dogrulanmis_is_basina_usd == null) return T('yok (kontrolü geçerek biten iş yok)');
  return paraTokenMetni(r.dogrulanmis_is_basina_usd, r.dogrulanmis_is_basina_token);
}

// "3 iş: 2 bitti, 1 takıldı" for a group report in the list.
const OUTCOME_TR = [['bitti', N_('bitti')], ['tikandi', N_('takıldı')], ['iptal', N_('iptal')], ['basarisiz', N_('başlatılamadı')]];

export function reportSummaryText(r) {
  const counts = (r && r.sonuclar) || {};
  const total = Number(r && r.is_sayisi) || 0;
  if (!total) return T('iş yok');
  const known = new Set(OUTCOME_TR.map(([k]) => k));
  const parts = OUTCOME_TR.filter(([k]) => counts[k]).map(([k, label]) => `${counts[k]} ${T(label)}`);
  for (const [k, n] of Object.entries(counts)) if (!known.has(k) && n) parts.push(`${n} ${k}`);
  return T('{n} iş: {liste}', { n: total, liste: parts.join(', ') });
}

// Office vocabulary (the owner, 2026-11-11): a worker by its role, the model in parentheses — "Kıdemli (Opus)". Any
// model id ("opus", "claude-opus-5-5") -> its role; an unknown id is shown as it is; '' / missing -> ''.
const CALISAN = { haiku: [N_('Stajyer'), 'Haiku'], sonnet: [N_('Uzman'), 'Sonnet'], opus: [N_('Kıdemli'), 'Opus'],
  fable: [N_('Genel Müdür'), 'Fable'], codex: [N_('Dış denetçi'), 'Codex'] };
// plan "Sonraki iş (9)" step 2: the specialisation's title after the seniority ("Kıdemli Backend (Opus)"); the same
// map as ofis-davranis.js UZMANLIK_BASLIK (a test keeps both equal to roller/*.json). genel and the Genel Müdür add none.
export const UZMANLIK_ADI = { backend: 'Backend', ui: 'UI', mobil: N_('Mobil'), test: 'Tester', analiz: N_('Analist'),
  guvenlik: N_('Güvenlik'), genel: N_('Genel') }; // translated where drawn (calisanMetni)
export function calisanMetni(model, uzmanlik = '') {
  if (typeof model !== 'string' || !model.trim()) return '';
  const low = model.toLowerCase();
  const fam = Object.keys(CALISAN).find((f) => low.includes(f));
  if (!fam) return model;
  const ek = ['haiku', 'sonnet', 'opus'].includes(fam) && uzmanlik !== 'genel' &&
    Object.prototype.hasOwnProperty.call(UZMANLIK_ADI, uzmanlik) ? ` ${T(UZMANLIK_ADI[uzmanlik])}` : '';
  return `${T(CALISAN[fam][0])}${ek} (${CALISAN[fam][1]})`;
}

// The Kalite table: one row per project × tier × worker (GET /api/kalite `satirlar`).
// N_: app.js draws the heads with T()
export const QUALITY_HEAD = [N_('Proje'), N_('Katman'), N_('Çalışan'), N_('İş'), N_('Bitti'), N_('İlk denemede geçti'), N_('Yeniden iş'),
  N_('Doğrulanmış iş başına'), N_('Ortalama kullanım'), N_('Ortalama süre'), N_('Token')];

export function qualityCells(r) {
  return [r.proje || '', r.katman || '', calisanMetni(r.model), String(Number(r.is_sayisi) || 0),
    ratioText(r.bitti, r.is_sayisi), ratioText(r.ilk_tur_gecen, r.ilk_tur_olculen), ratioText(r.yeniden_is, r.is_sayisi),
    paraTokenMetni(r.dogrulanmis_is_basina_usd, r.dogrulanmis_is_basina_token), paraTokenMetni(r.ort_usd, r.ort_token),
    minutesText(r.ort_sure_dk), tokenToplamMetni(r)];
}

// The Kalite view's tiles over every row (GET /api/kalite `toplam`): [{etiket, deger, ipucu, ana}]; dollars with
// their token twins, and how many jobs have no token count (never counted as 0). [] without rows.
export function kaliteKutulari(t) {
  if (!t || typeof t !== 'object') return [];
  const missing = Number(t.token_bilinmeyen) || 0;
  const eksik = missing > 0 && tokenMetni(t.toplam_token) ? ` · ${T('{n} işin token sayısı kayıtlı değil', { n: missing })}` : '';
  return [
    { etiket: T('Doğrulanmış iş başına kullanım'), deger: paraTokenMetni(t.dogrulanmis_is_basina_usd, t.dogrulanmis_is_basina_token),
      ipucu: T('{n} iş kontrolü geçerek bitti', { n: Number(t.dogrulanan) || 0 }) + eksik, ana: true },
    { etiket: T('İlk denemede geçti'), deger: ratioText(t.ilk_tur_gecen, t.ilk_tur_olculen), ipucu: T('kontrolü çalışan işler'), ana: false },
    { etiket: T('Yeniden iş'), deger: ratioText(t.yeniden_is, t.is_sayisi), ipucu: T('en az bir düzeltme gereken'), ana: false },
    { etiket: T('Bitti'), deger: ratioText(t.bitti, t.is_sayisi), ipucu: T('ortalama süre {sure}', { sure: minutesText(t.ort_sure_dk) }), ana: false },
    { etiket: T('Toplam kullanım'), deger: paraTokenMetni(t.toplam_usd, t.toplam_token),
      ipucu: T('iş başına ortalama {deger}', { deger: paraTokenMetni(t.ort_usd, t.ort_token) }), ana: false },
  ];
}

// --- Phase 8: model selection in the Kalite view (GET /api/kalite `model_secimi`, bin/model_secimi.py) ---
export const MAPPING_HEAD = [N_('Proje'), N_('Katman'), N_('Çalışan'), 'Effort', N_('Kaynak')]; // N_: app.js draws with T()
const SOURCE_TR = { proje: N_('projeye özel (onaylı pilot)'), katman: N_('genel tablo') };

// The effective mapping: one row per project × tier.
export function mappingCells(e) {
  return [e.proje || '', e.katman || '', calisanMetni(e.model) || '—', e.effort || '—', SOURCE_TR[e.kaynak] ? T(SOURCE_TR[e.kaynak]) : e.kaynak || '—'];
}

// "ornek-uygulama · kolay: haiku → sonnet denemesi — 1/3 iş eklendi, 0 bitti"
export function pilotText(p) {
  if (!p) return '';
  const total = Number(p.toplam) || 0;
  return T('{proje} · {katman}: {eski} → {yeni} denemesi — {eklenen}/{toplam} iş eklendi, {biten} bitti', { proje: p.proje,
    katman: p.katman, eski: calisanMetni(p.mevcut_model), yeni: calisanMetni(p.model), eklenen: Number(p.eklenen) || 0, toplam: total,
    biten: Number(p.biten) || 0 });
}

// An open model card: a proposal (asks for a pilot) or a pilot result (asks for the mapping change, or only closes).
export function modelCardText(c) {
  if (!c) return '';
  const head = `${c.proje} · ${c.katman}: ${calisanMetni(c.mevcut_model)} → ${calisanMetni(c.model)}`;
  if (c.tur === 'model-onerisi') {
    return c.yon === 'asagi'
      ? T('{bas} — daha ucuz çalışan için {n} işlik deneme öneriliyor (karar bekliyor)', { bas: head, n: Number(c.pilot_is) || 0 })
      : T('{bas} — daha deneyimli çalışan için {n} işlik deneme öneriliyor (karar bekliyor)', { bas: head, n: Number(c.pilot_is) || 0 });
  }
  return c.basari
    ? T('{bas} — deneme başarılı; eşleme değişikliği soruluyor (karar bekliyor)', { bas: head })
    : T('{bas} — deneme kanıtlamadı; eşleme değişmeyecek (kart kapanmayı bekliyor)', { bas: head });
}

// --- The advisor pilot (bin/danisman.py; GET /api/kalite `model_secimi.danisman`, a job's `danisman`) ---
// A job's card: "Danışman: Fable" when its sessions run with an advisor (arm B, the mapped advisor or the hard-job
// rule), followed by its reason when the server recorded one ("Danışman: Fable — zor iş: …"); '' else. Plain text:
// the caller puts it in with textContent.
export function danismanMetni(t) {
  const m = t && typeof t.danisman === 'string' ? t.danisman.trim() : '';
  if (!m) return '';
  const fam = Object.keys(CALISAN).find((f) => m.toLowerCase().includes(f));
  const neden = typeof t.danisman_nedeni === 'string' ? t.danisman_nedeni.trim() : '';
  return T('Danışman: {ad}', { ad: fam ? CALISAN[fam][1] : m }) + (neden ? ` — ${neden}` : '');
}

const DANISMAN_DURUM = { oneri: N_('öneri kartı karar bekliyor'), pilot: N_('deneme sürüyor'), sonuc: N_('sonuç kartı karar bekliyor'),
  bos: N_('deneme yok') };

// The Kalite view's lines: the pilot's state, then one line per arm once measured, then the mapping when it exists.
export function danismanPilotuSatirlari(d) {
  if (!d || typeof d !== 'object') return [];
  const adv = (calisanMetni(d.model) || d.model || '').replace(/^.*\((.+)\)$/, '$1');
  const durum = DANISMAN_DURUM[d.durum] ? T(DANISMAN_DURUM[d.durum]) : d.durum || '';
  let head = T('Danışman denemesi · {katman} işler, {danisman} danışman — {durum}', { katman: d.katman || '', danisman: adv, durum });
  if (d.durum === 'pilot') {
    const a = d.A || {}, b = d.B || {};
    head += ` ${T('({eklenen}/{toplam} iş · A {a_eklenen} iş, {a_biten} bitti · B {b_eklenen} iş, {b_biten} bitti)', {
      eklenen: Number(d.eklenen) || 0, toplam: Number(d.is_sayisi) || 0, a_eklenen: Number(a.eklenen) || 0,
      a_biten: Number(a.biten) || 0, b_eklenen: Number(b.eklenen) || 0, b_biten: Number(b.biten) || 0 })}`;
    if (d.acik === false) head += ` · ${T('anahtar kapalı, yeni iş almıyor')}`;
  } else if (d.durum === 'sonuc') {
    head += ` · ${d.basari ? T('başarılı; kalıcı olması soruluyor') : T('kanıtlamadı; bırakılması öneriliyor')}`;
  }
  const out = [head];
  for (const [kol, ad] of [['A', N_('A (danışmansız)')], ['B', N_('B (danışmanlı)')]]) {
    const m = d.sonuc && d.sonuc[kol];
    if (!m) continue;
    const cagri = m.danisman_cagri === null || m.danisman_cagri === undefined ? T('bilinmiyor') : String(m.danisman_cagri);
    out.push(T('{kol}: ilk denemede geçti {oran} · yeniden iş {is} iş / {tur} tur · doğrulanmış iş başına {deger}', {
      kol: T(ad), oran: ratioText(m.ilk_tur_gecen, m.ilk_tur_olculen), is: Number(m.yeniden_is) || 0,
      tur: Number(m.yeniden_is_turu) || 0, deger: paraTokenMetni(m.dogrulanmis_is_basina_usd, m.dogrulanmis_is_basina_token) })
      + (kol === 'B' ? ` · ${T('danışman çağrısı {n}', { n: cagri })}` : ''));
  }
  if (d.eslesme) out.push(T('Eşleme: {katman} işleri {danisman} danışmanla başlar', { katman: d.katman, danisman: calisanMetni(d.eslesme) || d.eslesme }));
  return out;
}

// A report's markdown as plain blocks for the page (rendered with textContent only): headings, "> " quotes, "- "
// lists, tables and paragraphs. [[link|alias]] shows the alias, [[link]] the name, **bold** its text; a table cell
// that is exactly a job note link carries the note so the page can open that job.
const JOB_STEM = /^\d{4}-\d{2}-\d{2}-[\w-]+$/;

export function plainLinks(text) {
  return String(text || '').replace(/\[\[([^\]|]*)\|([^\]]*)\]\]/g, '$2').replace(/\[\[([^\]]*)\]\]/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1');
}

// the same text with its [[links]] kept (the page makes them Obsidian links: `linkli` next to `text`)
const boldsuz = (text) => String(text || '').replace(/\*\*([^*]+)\*\*/g, '$1');

function tableCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
}

export function reportBlocks(text) {
  let lines = String(text || '').split('\n');
  if (lines[0] === '---') {
    const end = lines.indexOf('---', 1);
    if (end > 0) lines = lines.slice(end + 1);
  }
  const out = [];
  let open = null;  // the block that the next line of the same kind extends
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    const head = line.match(/^(#{1,6})\s+(.*)$/);
    if (head) { out.push({ type: 'h', level: head[1].length, text: plainLinks(head[2]) }); open = null; continue; }
    if (!line.trim()) { open = null; continue; }
    if (line.startsWith('|')) {
      if (/^\|[\s:|-]+\|$/.test(line)) continue;  // the separator row
      const cells = tableCells(line);
      if (open && open.type === 'table') {
        open.rows.push(cells.map((c) => {
          const link = c.match(/^\[\[([^\]|]+)\]\]$/);
          return { text: plainLinks(c), linkli: boldsuz(c), note: link && JOB_STEM.test(link[1]) ? `${link[1]}.md` : '' };
        }));
      } else {
        open = { type: 'table', head: cells.map(plainLinks), rows: [] };
        out.push(open);
      }
      continue;
    }
    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      if (open && open.type === 'quote') { open.text += `\n${plainLinks(quote[1])}`; open.linkli += `\n${boldsuz(quote[1])}`; }
      else { open = { type: 'quote', text: plainLinks(quote[1]), linkli: boldsuz(quote[1]) }; out.push(open); }
      continue;
    }
    const item = line.match(/^\s*[-*]\s+(.*)$/);
    if (item) {
      if (open && open.type === 'list') { open.items.push(plainLinks(item[1])); open.linkli.push(boldsuz(item[1])); }
      else { open = { type: 'list', items: [plainLinks(item[1])], linkli: [boldsuz(item[1])] }; out.push(open); }
      continue;
    }
    if (open && open.type === 'p') { open.text += `\n${plainLinks(line)}`; open.linkli += `\n${boldsuz(line)}`; }
    else { open = { type: 'p', text: plainLinks(line), linkli: boldsuz(line) }; out.push(open); }
  }
  return out;
}

// --- an approval card's risk level and open security finding (bin/akis.py frontmatter, via bin/state.py) ---

const RISK_METNI = { dusuk: N_('düşük'), normal: N_('normal'), yuksek: N_('yüksek') };
export const GUVENLIK_UYARISI = N_('Açık güvenlik bulgusu var — bu haliyle onaylanmamalı'); // kararIsaretleri gives it translated

// A decision -> {risk: {metin, sinif} | null, uyari: '' | GUVENLIK_UYARISI}. Only the server's exact values count.
export function kararIsaretleri(d) {
  const risk = d && Object.prototype.hasOwnProperty.call(RISK_METNI, d.risk) ? d.risk : '';
  return { risk: risk ? { metin: T('Risk: {seviye}', { seviye: T(RISK_METNI[risk]) }), sinif: `risk-${risk}` } : null,
    uyari: d && d.guvenlik_acik === true ? T(GUVENLIK_UYARISI) : '' };
}

// --- the top-bar clock: time and date in the office zone (state.sahne.saat_dilimi), never the browser's ---

// (instant ms, IANA zone) -> {saat: '23:04', tarih: 'Çarşamba, 11 Kasım 2026', kisa: 'Çar 11 Kas'}. An unknown zone
// falls back to Europe/Istanbul.
export function tarihMetni(now, tz) {
  const zone = (() => {
    try { new Intl.DateTimeFormat(yerel(), { timeZone: tz }); return tz; } catch (e) { return 'Europe/Istanbul'; }
  })();
  const d = new Date(now);
  const saat = new Intl.DateTimeFormat(yerel(), { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: zone })
    .format(d);
  // built from the parts: ICU versions order the long form differently ("11 Kasım 2026 Çarşamba")
  const l = Object.fromEntries(new Intl.DateTimeFormat(yerel(), { weekday: 'long', day: 'numeric', month: 'long',
    year: 'numeric', timeZone: zone }).formatToParts(d).map((x) => [x.type, x.value]));
  const tarih = `${l.weekday}, ${l.day} ${l.month} ${l.year}`;
  const p = Object.fromEntries(new Intl.DateTimeFormat(yerel(), { weekday: 'short', day: 'numeric', month: 'short',
    timeZone: zone }).formatToParts(d).map((x) => [x.type, x.value]));
  const kisa = [p.weekday, p.day, p.month].filter(Boolean).join(' ');
  return { saat, tarih, kisa };
}

// --- The project's own report, structured (the owner, 2026-11-14: "Özet ve Ayrıntı tek uzun düz yazı") ---
// raporBicimle(text) is a pure formatter: project text -> blocks
//   {tip: 'baslik', metin} | {tip: 'liste', ogeler: [str]} | {tip: 'paragraf', metin} | {tip: 'tablo', baslik: [str]|null, satirlar: [[str]]}.
// The text stays exact (only whitespace at the line ends and the bullet marker of list items / table rows is dropped);
// it is data: no markdown, no HTML, no links are interpreted. raporDugumu(text, doc) (doc = the page's document, passed
// in so this file stays DOM-free) builds the DOM with createElement / textContent only. uzunListe(line) shortens a very long comma-separated file list.
const RAPOR_AYIRAC = ' | ';
const RAPOR_MADDE = /^\s*[-•*]\s+(.*)$/;
const RAPOR_UZUN_PARAGRAF = 280;
const tuyle = (s) => s.split(RAPOR_AYIRAC).length - 1;
const RAPOR_MD_AYRAC = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$/; // a Markdown table's "|---|:--:|" line
const mdHucreler = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((x) => x.trim());

// ALL-CAPS-ish: at least 3 letters, at least 70 % of them upper case (text inside parentheses is ignored).
function buyukHarfli(line) {
  const s = line.replace(/\([^()]*\)/g, ' ');
  let letters = 0;
  let upper = 0;
  for (const ch of s) {
    const u = ch.toLocaleUpperCase('tr');
    const l = ch.toLocaleLowerCase('tr');
    if (u === l) continue;
    letters += 1;
    if (ch === u) upper += 1;
  }
  return letters >= 3 && upper / letters >= 0.7;
}

function baslikMi(line) {
  if (line.length > 140) return false;
  if (/:$/.test(line)) return true;
  const numbered = /^\d+[).]\s+(\S.*)$/.exec(line);
  if (numbered) return buyukHarfli(numbered[1]);
  return buyukHarfli(line);
}

// "ÖZET: some sentence" -> heading "ÖZET:" + the rest as a paragraph
function baslikGovde(line) {
  const m = /^([^\s:][^:]{1,38}):\s+(\S.*)$/.exec(line);
  return m && buyukHarfli(m[1]) && !/[a-zçğıöşü]/.test(m[1].replace(/\([^()]*\)/g, '')) ? [`${m[1]}:`, m[2]] : null;
}

// "A sentence. Another one." -> sentences (a split needs . ! ? + space + an upper-case letter or digit, and no digit
// before the full stop: "Kontrol 2. denemede" stays whole)
export function cumleleriBol(text) {
  const s = String(text || '');
  const out = [];
  let start = 0;
  for (let i = 0; i < s.length; i += 1) {
    if (!/[.!?]/.test(s[i]) || !/\s/.test(s[i + 1] || '')) continue;
    if (/\d/.test(s[i - 1] || '')) continue;
    const next = s.slice(i + 1).trimStart()[0] || '';
    if (!next || !(/\d/.test(next) || (next !== next.toLocaleLowerCase('tr') && next === next.toLocaleUpperCase('tr')))) continue;
    out.push(s.slice(start, i + 1).trim());
    start = i + 1;
  }
  out.push(s.slice(start).trim());
  return out.filter(Boolean);
}

// a long paragraph -> several, cut at sentence ends (greedy, up to RAPOR_UZUN_PARAGRAF characters each)
function paragrafBol(text) {
  if (text.length <= RAPOR_UZUN_PARAGRAF) return [text];
  const out = [];
  let cur = '';
  for (const sentence of cumleleriBol(text)) {
    if (cur && (cur.length + 1 + sentence.length) > RAPOR_UZUN_PARAGRAF) { out.push(cur); cur = sentence; }
    else cur = cur ? `${cur} ${sentence}` : sentence;
  }
  if (cur) out.push(cur);
  return out;
}

export function raporBicimle(text) {
  const lines = String(text == null ? '' : text).replace(/\r/g, '').split('\n').map((l) => l.replace(/\s+$/, ''));
  const blocks = [];
  let list = null;
  const flush = () => { list = null; };
  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i];
    const line = raw.trim();
    if (!line) { flush(); continue; }
    // Markdown, as the Ar-Ge reports write it: "## Başlık" is a heading; "| a | b |" + "|---|---|" + rows is a table
    const md = /^#{1,6}\s+(\S.*?)\s*#*$/.exec(line);
    if (md) { flush(); blocks.push({ tip: 'baslik', metin: md[1] }); continue; }
    if (/^\|.*\|$/.test(line) && RAPOR_MD_AYRAC.test((lines[i + 1] || '').trim())) {
      const rows = [];
      let j = i + 2;
      for (; j < lines.length && /^\|.*\|$/.test(lines[j].trim()); j += 1) rows.push(mdHucreler(lines[j]));
      flush();
      blocks.push({ tip: 'tablo', baslik: mdHucreler(line), satirlar: rows });
      i = j - 1;
      continue;
    }
    const madde = RAPOR_MADDE.exec(line);
    const bare = madde ? madde[1] : line;
    // a table: a header with >= 2 " | " (or "(a | b | c)" inside a heading line) and following rows with the same count
    const paren = /\(([^()]*\|[^()]*)\)/.exec(line);
    const parenCols = paren && tuyle(paren[1]) >= 2 ? paren[1].split(RAPOR_AYIRAC).map((x) => x.trim()) : null;
    const cols = parenCols ? parenCols.length : (tuyle(bare) >= 2 ? tuyle(bare) + 1 : 0);
    if (cols) {
      const rows = [];
      let j = i + 1;
      for (; j < lines.length; j += 1) {
        const r = lines[j].trim().replace(/^[-•*]\s+/, '');
        if (!r || r.split(RAPOR_AYIRAC).length !== cols) break;
        rows.push(r.split(RAPOR_AYIRAC).map((x) => x.trim()));
      }
      if (rows.length) {
        flush();
        if (parenCols) {
          blocks.push({ tip: 'baslik', metin: line });
          blocks.push({ tip: 'tablo', baslik: parenCols, satirlar: rows });
        } else {
          blocks.push({ tip: 'tablo', baslik: bare.split(RAPOR_AYIRAC).map((x) => x.trim()), satirlar: rows });
        }
        i = j - 1;
        continue;
      }
    }
    if (madde) {
      if (!list) { list = { tip: 'liste', ogeler: [] }; blocks.push(list); }
      list.ogeler.push(madde[1]);
      continue;
    }
    flush();
    const split = baslikGovde(line);
    if (split) {
      blocks.push({ tip: 'baslik', metin: split[0] });
      for (const p of paragrafBol(split[1])) blocks.push({ tip: 'paragraf', metin: p });
    } else if (baslikMi(line)) {
      blocks.push({ tip: 'baslik', metin: line });
    } else {
      for (const p of paragrafBol(line)) blocks.push({ tip: 'paragraf', metin: p });
    }
  }
  return blocks;
}

// A line that is mostly a comma-separated file list (>= 8 items, none with a space, most with "." or "/"):
// {onek, ogeler, sonek, kisa, tam} with `kisa` = the prefix + the first `kac` items + "… ve N dosya daha"; else null.
export function uzunListe(line, kac = 5) {
  const tam = String(line == null ? '' : line);
  const parts = tam.split(', ');
  if (parts.length < kac + 3) return null;
  let onek = '';
  const colon = parts[0].lastIndexOf(': ');
  if (colon >= 0) { onek = parts[0].slice(0, colon + 2); parts[0] = parts[0].slice(colon + 2); }
  const sonek = (/[.;]$/.exec(parts[parts.length - 1]) || [''])[0];
  if (sonek) parts[parts.length - 1] = parts[parts.length - 1].slice(0, -1);
  if (parts.some((p) => !p || /\s/.test(p) || p.length > 90)) return null;
  if (parts.filter((p) => /[./]/.test(p)).length < parts.length * 0.7) return null;
  const kalan = parts.length - kac;
  return { onek, ogeler: parts, sonek, kisa: `${onek}${parts.slice(0, kac).join(', ')}${T('… ve {n} dosya daha', { n: kalan })}`, tam };
}

// A text node, or (for a long file list) a span with the short form and a "tümünü göster" toggle.
function raporMetni(doc, parent, text) {
  const long = uzunListe(text);
  if (!long) { parent.append(doc.createTextNode(text)); return; }
  const span = doc.createElement('span');
  span.textContent = long.kisa;
  const btn = doc.createElement('button');
  btn.type = 'button';
  btn.className = 'rapor-toggle';
  btn.textContent = T('tümünü göster');
  let open = false;
  btn.addEventListener('click', () => {
    open = !open;
    span.textContent = open ? long.tam : long.kisa;
    btn.textContent = open ? T('daha az göster') : T('tümünü göster');
  });
  parent.append(span, doc.createTextNode(' '), btn);
}

// The structured DOM of a project report: textContent / createTextNode / createElement only (no markup is parsed).
export function raporDugumu(text, doc) {
  const root = doc.createElement('div');
  root.className = 'rapor';
  const el = (tag, cls, txt) => {
    const e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) raporMetni(doc, e, txt);
    return e;
  };
  for (const b of raporBicimle(text)) {
    if (b.tip === 'baslik') root.append(el('p', 'rapor-baslik', b.metin));
    else if (b.tip === 'paragraf') root.append(el('p', 'rapor-paragraf', b.metin));
    else if (b.tip === 'liste') {
      const ul = el('ul', 'rapor-liste');
      for (const o of b.ogeler) ul.append(el('li', null, o));
      root.append(ul);
    } else if (b.tip === 'tablo') {
      const wrap = el('div', 'rapor-tablo-kap');
      const table = el('table', 'rapor-tablo');
      if (b.baslik) {
        const tr = el('tr');
        for (const c of b.baslik) tr.append(el('th', null, c));
        const thead = el('thead');
        thead.append(tr);
        table.append(thead);
      }
      const tbody = el('tbody');
      for (const r of b.satirlar) {
        const tr = el('tr');
        for (const c of r) tr.append(el('td', null, c));
        tbody.append(tr);
      }
      table.append(tbody);
      wrap.append(table);
      root.append(wrap);
    }
  }
  return root;
}

// The card's one-line summary of a project report: the first sentence (<= 160 characters) of the paragraph after an
// "ÖZET" heading, else of the first paragraph / list item / heading.
export function raporOzeti(text, max = 160) {
  const blocks = raporBicimle(text);
  const flat = (b) => (b.tip === 'liste' ? b.ogeler[0] : b.tip === 'tablo' ? '' : b.metin);
  let pick = null;
  const at = blocks.findIndex((b) => b.tip === 'baslik' && /^(ÖZET|OZET)\b/i.test(b.metin));
  if (at >= 0 && blocks[at + 1] && flat(blocks[at + 1])) pick = flat(blocks[at + 1]);
  if (pick == null) {
    const body = blocks.find((b) => b.tip !== 'baslik' && flat(b));
    pick = body ? flat(body) : (blocks.map(flat).find(Boolean) || '');
  }
  return short(cumleleriBol(pick)[0] || '', max);
}
