// ?demo=1 — fake state and chat with no backend calls, for trying the page alone.
//
// The living office plays a scripted ~3-minute loop (DEMO_SAHNELERI): every event in order, each long enough to see —
// the resident Genel Müdür (kadro) waits in the lounge and walks to its desk when its job starts, a new job comes in through
// the lift, works, gets a helper, asks for a permission, runs its Kontrol, finishes (✓, tea,
// walks to the lift); a decision at the CEO's door (answering its card sends the job back to its desk); a Claude review
// at a Kıdemli Tester desk of the QA odası while the external auditors (Codex, GLM, DeepSeek) type in their room, then the hakem
// weighs their findings at an Uzmanlar odası desk; an escalation (the Stajyer carries the file to the Kıdemli's desk); lunch; a model's
// quota (its idle agent goes home, a free reviewer shows its "Evde" sign) and its return. demoDurumu(t, now) is the pure state at loop second t; createDemo plays it every
// two seconds and names the current scene with onSahne (a plain Turkish caption). ?demo_t=<s> starts the loop at second s.
// Its four projects fill the free cells of the compact floor, the cells left over are empty reserved bays.
// Lunch is shown by moving the demo's own lunch window (state.sahne.ogle) onto the current time with sahne.ogle_hepsi
// (every idle actor at the table at once in that scene): the real lunch logic (ogleMi, ogleYemekte) is unchanged.
import { ofisSaati, sahip } from './ofis-davranis.js';
import { tokenMetni } from './ofis-text.js';
// Language (phase 2): the captions, the chat lines and what the real server translates for the page (the usage
// popup, the limit pill, the Sunucu odası) follow the page's language; job titles, decision cards, notices and
// reports stay Turkish like the vault notes they stand for.
import { t as T, N_ } from './i18n.js';

const pad = (n) => String(n).padStart(2, '0');
const localIso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
const ago = (min) => new Date(Date.now() - min * 60000);

// A job as state.board carries it (bin/state.py recent_tasks); started / finished are minutes ago (null = not yet).
function job(note, project, status, title, startedMin, finishedMin, extra = {}) {
  return {
    note, project, status, title, started: startedMin == null ? '' : localIso(ago(startedMin)),
    finished: finishedMin == null ? '' : localIso(ago(finishedMin)), created: localIso(ago((startedMin || 10) + 1)),
    session: `ofis-${project}-demo`, short_id: 'a1b2c3d4', tier: '', model: '', spent: '', calls: '', budget: 3,
    max_calls: 120, escalated_from: '', workflow: '', step: '', step_kind: '', queue_position: null, held: false,
    depends: [], blocked: '', ...extra,
  };
}

// The same with absolute times (ms; null = not yet).
function jobAt(note, project, status, title, startedMs, finishedMs, extra = {}) {
  return {
    ...job(note, project, status, title, null, null, extra),
    started: startedMs == null ? '' : localIso(new Date(startedMs)),
    finished: finishedMs == null ? '' : localIso(new Date(finishedMs)),
    created: startedMs == null ? '' : localIso(new Date(startedMs - 60000)), ...extra,
  };
}

// GET /api/raporlar, /api/rapor?grup=…, /api/kalite with fake numbers (same shapes as bin/rapor.py, bin/karne.py).
const REPORTS = [
  { grup: 'giris-duzeltmeleri', baslik: 'Giriş ekranı düzeltmeleri', proje: 'ornek-uygulama', tur: 'grup', surum: 1,
    bitis: localIso(ago(200)), yazildi: localIso(ago(199)), toplam_usd: 1.8423, toplam_token: 642000, is_sayisi: 3,
    sonuclar: { bitti: 2, tikandi: 1 }, dogrulanmis_is_basina_usd: 0.9212, dogrulanmis_is_basina_token: 321000, token_eksik: 0,
    dogrulanan: 2, ilk_tur_gecen: 1,
    ilk_tur_olculen: 2, yeniden_is: 1, acik: 1 },
  { grup: 'faz5-deneme', baslik: 'faz5-deneme grubu', proje: 'blog', tur: 'grup', surum: 1, bitis: localIso(ago(1500)),
    yazildi: localIso(ago(1499)), toplam_usd: 0.022, is_sayisi: 2, sonuclar: { bitti: 2 },
    dogrulanmis_is_basina_usd: 0.011, dogrulanmis_is_basina_token: null, token_eksik: 0, dogrulanan: 2, ilk_tur_gecen: 2, ilk_tur_olculen: 2, yeniden_is: 0, acik: 0 },
];
const REPORT_TEXT = `# ornek-uygulama — Giriş ekranı düzeltmeleri (giris-duzeltmeleri)

> Bu raporu Ofis sunucusu grup bitince yazar (elle düzenleme). Dolar tutarları API fiyatıyla karşılığıdır (abonelikte para ödenmez).

## İşler

| İş | Katman / çalışan | Sonuç | Kontrol ilk turda | Kontrol denemesi | Devam | Yükseltme | API karşılığı ($) | Süre (dk) |
|---|---|---|---|---|---|---|---|---|
| [[2026-11-10-101500-ornek-uygulama]] | kod / opus | bitti | evet | 1 | 0 | — | 1.2000 | 34 |
| [[2026-11-10-101600-ornek-uygulama]] | kolay / haiku | bitti | hayır | 2 | 0 | — | 0.0423 | 5 |
| [[2026-11-10-101700-ornek-uygulama]] | genel / sonnet | takıldı | hayır | 2 | 0 | — | 0.6000 | 41 |

## Toplamlar

- Toplam kullanım: API karşılığı ~$1.84
- Doğrulanmış iş başına kullanım: API karşılığı ~$0.92 (2 iş kontrolü geçerek bitti)
- Toplam token: 642 bin token
- Doğrulanmış iş başına token: 321 bin token (2 iş kontrolü geçerek bitti)
- Kontrol ilk turda geçme: %50 (1/2)
- Yeniden iş: 1 (Kontrol geçmedi: 1, inceleme düzeltme istedi: 0, bir üst katmana taşındı: 0, devam ettirildi: 0)
- Döngü süresi (ilk başlangıç → son bitiş): 1 sa 20 dk

## Açık kalanlar

- [[2026-11-10-101700-ornek-uygulama]] takıldı. Sonucun son satırı: “test geçmedi”

## Düzeltmeler

- Bu grupta düzeltme gerekmedi.
`;
const quality = (proje, katman, model, n, done, first, measured, rework, verified, total, minutes, tokens = null, known = n) => ({
  proje, katman, model, is_sayisi: n, bitti: done, ilk_tur_gecen: first, ilk_tur_olculen: measured, yeniden_is: rework,
  dogrulanan: verified, toplam_usd: total, ort_usd: total / n, ort_dogrulanmis_usd: verified ? total / n : null,
  dogrulanmis_is_basina_usd: verified ? total / verified : null, ort_sure_dk: minutes, toplam_token: tokens,
  // the token twins (bin/karne.py _measure): known counts only; the rest is token_bilinmeyen, never 0
  token_bilinen: tokens === null ? 0 : known, token_bilinmeyen: tokens === null ? n : n - known,
  ort_token: tokens === null ? null : Math.round(tokens / known),
  dogrulanmis_is_basina_token: tokens === null || !verified ? null : Math.round(tokens / verified),
});
const QUALITY = {
  satirlar: [quality('blog', 'kolay', 'haiku', 7, 6, 6, 6, 2, 6, 0.0755, 3, 84200),
    quality('ornek-uygulama', 'genel', 'sonnet', 3, 2, 1, 3, 1, 1, 1.104, 18),
    quality('ornek-uygulama', 'inceleme', 'opus', 2, 1, 0, 0, 0, 0, 0.843, 12),
    quality('ornek-uygulama', 'kod', 'opus', 4, 3, 2, 3, 2, 3, 4.9, 41, 1830000)],
  modeller: [quality('', '', 'haiku', 7, 6, 6, 6, 2, 6, 0.0755, 3), quality('', '', 'opus', 6, 4, 2, 3, 2, 3, 5.743, 31),
    quality('', '', 'sonnet', 3, 2, 1, 3, 1, 1, 1.104, 18)],
  toplam: quality('', '', '', 16, 12, 9, 12, 5, 10, 6.9225, 18, 1914200, 11),
  is_sayisi: 16,
  // the NPC chat usage (bin/npc_sohbet.py): part of the office's totals, never of the quality metrics above
  npc_sohbet: { usd: 0.0136, token: 96000, token_bilinen: 11, soru: 11 },
  // phase 8 (bin/model_secimi.py page()): an open proposal, a running pilot and the effective mapping
  model_secimi: {
    oneriler: [{ proje: 'blog', katman: 'kolay', kimlik: 'blog-kolay-20261111093000-1', tur: 'model-onerisi', yon: 'asagi',
      mevcut_model: 'sonnet', model: 'haiku', not: '2026-11-11-blog-kolay-model-onerisi.md', basari: null, pilot_is: 3 }],
    pilotlar: [{ proje: 'ornek-uygulama', katman: 'genel', kimlik: 'ornek-uygulama-genel-20261110120000-1', yon: 'yukari',
      mevcut_model: 'sonnet', model: 'opus', effort: 'high', eklenen: 2, biten: 1, toplam: 3 }],
    eslesme: [['blog', 'kolay', 'sonnet', 'medium', 'proje'], ['blog', 'genel', 'sonnet', 'medium', 'katman'],
      ['ornek-uygulama', 'kolay', 'haiku', 'low', 'katman'], ['ornek-uygulama', 'genel', 'sonnet', 'medium', 'katman'],
      ['ornek-uygulama', 'kod', 'opus', 'high', 'katman']]
      .map(([proje, katman, model, effort, kaynak]) => ({ proje, katman, model, effort, kaynak })),
  },
};

QUALITY.denetciler = [{ ad: 'codex', tur: 9, karar: 9, ciddi: 6, gecerli: 4 }, { ad: 'glm', tur: 7, karar: 6, ciddi: 5, gecerli: 2 },
  { ad: 'deepseek', tur: 4, karar: 3, ciddi: 2, gecerli: 1 }];

// GET /api/muhasebe (bin/muhasebe.py ozet): fake but internally consistent numbers for the Muhasebeci's card; the
// NPC chat usage (npc_sohbet) is inside the period totals and never in the job counts
const tot = (usd, token, n, proje, rol, codex = 0) => ({ usd, token, token_bilinen: token === null ? 0 : n, is_sayisi: n,
  codex_fiyatsiz: codex, proje: proje.map(([p, u, t, k]) => ({ proje: p, usd: u, token: t, token_bilinen: t === null ? 0 : k, is_sayisi: k })),
  rol: rol.map(([r, u, t, k]) => ({ rol: r, usd: u, token: t, token_bilinen: t === null ? 0 : k, is_sayisi: k })) });
const NPC = (usd, token, soru) => ({ usd, token, soru });
const MUHASEBE = {
  saat_dilimi: 'Europe/Istanbul',
  bugun: { ...tot(4.8336, 1690000, 5, [['atolye', 2.85, 1240000, 1], ['ornek-uygulama', 1.12, 412000, 1], ['kasa', 0.8523, 18300, 2],
    ['blog', 0.0081, null, 1]], [['Stajyer', 0.0081, null, 1], ['Uzman', 0.0423, 18300, 1], ['Kıdemli', 1.93, 412000, 2],
    ['Genel Müdür', 2.85, 1240000, 1]], 1), npc_sohbet: NPC(0.0032, 19700, 2) },
  bu_ay: { ...tot(38.4256, 14296000, 41, [['ornek-uygulama', 17.204, 6100000, 16], ['atolye', 11.85, 5200000, 9], ['kasa', 8.31, 2700000, 11],
    ['blog', 1.048, 200000, 5]], [['Stajyer', 0.75, 380000, 12], ['Uzman', 6.2, 2900000, 14], ['Kıdemli', 22.9, 8100000, 12],
    ['Genel Müdür', 8.562, 2820000, 3]], 4), npc_sohbet: NPC(0.0136, 96000, 11) },
  kalite: { dogrulanmis_is_basina_usd: 1.2391, dogrulanmis_is_basina_token: 458000, toplam_token: 14200000, token_bilinmeyen: 0,
    ilk_tur_gecen: 24, ilk_tur_olculen: 31, dogrulanan: 31 },
  bu_ay_rol_kalite: [{ rol: 'Stajyer', is_sayisi: 12, ilk_tur_gecen: 10, ilk_tur_olculen: 11, dogrulanan: 10, dogrulanmis_is_basina_usd: 0.075, dogrulanmis_is_basina_token: 38000 },
    { rol: 'Uzman', is_sayisi: 14, ilk_tur_gecen: 8, ilk_tur_olculen: 10, dogrulanan: 11, dogrulanmis_is_basina_usd: 0.5636, dogrulanmis_is_basina_token: 264000 },
    { rol: 'Kıdemli', is_sayisi: 12, ilk_tur_gecen: 5, ilk_tur_olculen: 8, dogrulanan: 8, dogrulanmis_is_basina_usd: 2.8625, dogrulanmis_is_basina_token: 1010000 },
    { rol: 'Genel Müdür', is_sayisi: 3, ilk_tur_gecen: 1, ilk_tur_olculen: 2, dogrulanan: 2, dogrulanmis_is_basina_usd: 4.281, dogrulanmis_is_basina_token: 1410000 }],
  en_pahali: [{ not: 'c.md', baslik: 'Ana sayfa yeniden tasarım taslağı', proje: 'atolye', usd: 2.85, token: 1240000, acik: true },
    { not: 'a.md', baslik: 'Onboarding ekranındaki metinleri düzelt', proje: 'ornek-uygulama', usd: 1.12, token: 412000, acik: true },
    { not: 'r.md', baslik: 'Kod incelemesi: İletişim formu', proje: 'atolye', usd: 0.31, token: null, acik: false }],
  butce: { calisan: 3, harcanan_usd: 4.0123, harcanan_token: 1652000, token_bilinen: 2, butce_usd: 9,
    dikkat: [{ not: 'c.md', baslik: 'Ana sayfa yeniden tasarım taslağı', proje: 'atolye', usd: 2.85, token: 1240000, butce: 3, durum: 'yakin' }] },
};
// GET /api/kullanim (bin/kullanim.py): the usage popup under the limit pill; office display names and numbers only
const kSatir = (ad, tur, n, cikti, usd) => ({ ad, tur, token: n, cikti_token: cikti, usd,
  fiyat_eksik: false, oturum_sayisi: 1,
  metin: T('{tok} · API karşılığı ~${usd}', { tok: tokenMetni(n), usd: usd.toFixed(2) }),
  cikti_metni: T('çıktı {tok}', { tok: tokenMetni(cikti) }) });
const KULLANIM = () => ({
  limitler: { pencereler: [
    { ad: 'haftalik', etiket: T('Haftalık'), yuzde: 54, gecti: false, yenilenir: T("perşembe 22:00'de yenilenir"), kalan: T('3 gün sonra') },
    { ad: 'bes_saat', etiket: T('5 saatlik'), yuzde: 62, gecti: false, yenilenir: T("bugün 21:00'de yenilenir"), kalan: T('2 sa 14 dk sonra') }],
  eski: false, olculdu: T("bugün 18:44'te ölçüldü"), eski_aciklama: '' },
  dagilim: {
    bes_saat: { baslangic: 0, tahmini: false, aralik: T("Bu pencere: 16:00'dan beri"), satirlar: [
      kSatir('Onboarding metinleri (ornek-uygulama)', 'is', 4200000, 31000, 2.41),
      kSatir('CEO', 'ceo', 1800000, 9000, 1.12),
      kSatir('CSV dışa aktarımı (kasa)', 'is', 950000, 12000, 0.61),
      kSatir(T('Ofis dışı diğer oturumlar'), 'diger', 300000, 4000, 0.18)],
    toplam: kSatir(T('Toplam'), 'toplam', 7250000, 56000, 4.32) },
    haftalik: { baslangic: 0, tahmini: false, aralik: T("Bu pencere: perşembe 22:00'den beri"), satirlar: [
      kSatir(T('Geliştirici oturumu'), 'gelistirici', 61000000, 410000, 38.2),
      kSatir('CEO', 'ceo', 22000000, 95000, 14.9),
      kSatir('Onboarding metinleri (ornek-uygulama)', 'is', 9800000, 74000, 5.6),
      kSatir('Jarvis', 'jarvis', 4100000, 30000, 2.7),
      kSatir(T('Ofis dışı diğer oturumlar'), 'diger', 2300000, 21000, 1.4)],
    toplam: kSatir(T('Toplam'), 'toplam', 99200000, 630000, 62.8) },
  },
  not: T('Plan yüzdesi tokenlarla birebir orantılı değildir (önbellekten okunan tokenlar daha hafif sayılır); bu liste kimin en çok kullandığını gösterir, kesin payını değil.'),
  hesaplandi: 0,
});

// GET /api/idari (bin/muhasebe.py idari): the office's operations
const IDARI = { limitler: { max_running: 3, max_running_per_project: 1, max_queued_per_project: 5, max_bekleyen_onay: 2 },
  otomatik_baslatma: { kurulu: true, dosya: 'local.ofis.server.plist' }, obsidian: { sorun: false, python: null },
  gunluk: { dosya: 'server.log', boyut: 1843200, yedek_boyut: 1048576 } };

// GET /api/sistem (bin/sistem.py): the computer's status as group totals only, one suggestion, no domain list yet
const SISTEM = () => ({ cpu: { cekirdek: 10, yuk: [7.4, 6.8, 6.1], yuk_orani: 0.74 },
  bellek: { toplam_gb: 16, kullanilan_gb: 12.6, yuzde: 79, baski: 'normal', bos_yuzde: 31 },
  disk: { toplam_gb: 460.4, bos_gb: 66.6, dolu_yuzde: 86 }, pil: { yuzde: 94, durum: T('şarj oluyor'), kaynak: T('adaptör') },
  acik_kalma_sn: 9 * 86400 + 2 * 3600, seviye: 'sari', docker: { konteyner: 0, cpu: 0, bellek_mb: 0 },
  gruplar: [{ ad: 'Node', sayi: 31, cpu: 42.1, bellek_mb: 2900 }, { ad: 'Python', sayi: 9, cpu: 6.3, bellek_mb: 610 },
    { ad: 'Docker', sayi: 3, cpu: 1.2, bellek_mb: 2150 }, { ad: T('Tarayıcılar'), sayi: 34, cpu: 88.4, bellek_mb: 3800 },
    { ad: T('Claude oturumları'), sayi: 4, cpu: 7.2, bellek_mb: 1300, bosta: 3 }, { ad: 'Codex/OpenCode', sayi: 2, cpu: 1.3, bellek_mb: 190 },
    { ad: T('Ofis sunucusu'), sayi: 1, cpu: 2.1, bellek_mb: 85 }, { ad: T('Diğer'), sayi: 412, cpu: 61.5, bellek_mb: 2600 }],
  oneriler: [{ tur: 'docker-bosta', metin: T("Docker 2,1 GB bellek tutuyor ama hiç konteyner çalışmıyor. Kullanmıyorsan Docker Desktop'ı kapatmak belleği rahatlatır (karar {sahip}).",
    { sahip: sahip('in') }) }],
  domainler: { liste_var: false, metin: T('Domain listesi henüz yok — Ar-Ge ilk çalışmasında soracak'), domainler: [], eposta: [],
    sorun_sayisi: 0, son_kontrol: null } });

// --- the scripted loop ---

// [id, start second, caption]; a scene lasts until the next one starts, the last one until DEMO_SURE.
export const DEMO_SAHNELERI = [
  ['acilis', 0, N_('Ofis açılıyor')],
  ['gelis', 5, N_('Yeni iş geliyor: asansörden çıkıp lobide sırasını bekliyor')],
  ['calisma', 13, N_('Sırası geldi: masasına geçti, çalışıyor')],
  ['yardimci', 21, N_('Yardımcı (alt ajan) geldi, yanında çalışıyor')],
  ['yardimci-bitti', 31, N_('Yardımcı işini bitirdi ✓ ve çıkıyor')],
  ['izin', 37, N_('İzin sorusu: ajan elini kaldırdı (!)')],
  ['kontrol', 46, N_('Kontrol çalışıyor: test lambası yanıp sönüyor')],
  ['bitti', 55, N_('İş bitti ✓ — Çaycı çay getiriyor')],
  ['mola', 70, N_('Mola: boştakiler oyun odasında masa tenisi oynuyor')],
  ['cikis', 85, N_('İşini bitiren ajan asansöre yürüyor')],
  ['karar', 91, N_("Karar bekleniyor: ajan CEO'nun kapısında (?) — “CEO soruyor” kartını cevaplayabilirsin")],
  ['inceleme', 111, N_('Yüksek riskli inceleme: Codex, GLM ve DeepSeek denetçi odasında, IT güvenlik uzmanı Sunucu odasında; Claude incelemesi QA odasında')],
  ['hakem', 119, N_('Hakem (Sonnet) Uzmanlar odasında denetçilerin bulgularını tartıyor')],
  ['yukseltme', 137, N_("Yükseltme: Stajyer dosyayı Kıdemli'nin masasına götürüyor")],
  ['ogle', 161, N_('Öğle arası: boştakiler yemekhanede, çalışanlar masasında')],
  ['kota', 177, N_("Sonnet'in kotası doldu: boştaki Sonnet ajanı evde; DeepSeek'in de kotası doldu")],
  ['donus', 191, N_('Kota açıldı: ajan asansörle geri dönüyor')],
].map(([id, bas, metin]) => ({ id, bas, metin }));
export const DEMO_SURE = 200;
// the demo's running limit: its busiest moment runs exactly this many jobs (the pill shows "5/5 · sınırda" then,
// never more than the limit)
export const DEMO_MAX_RUNNING = 5;
const AN = Object.fromEntries(DEMO_SAHNELERI.map((x) => [x.id, x.bas])); // loop second of each scene

// The scene at loop second t (wrapped into 0..DEMO_SURE).
export function demoSahnesi(t) {
  const s = ((Number(t) % DEMO_SURE) + DEMO_SURE) % DEMO_SURE;
  let cur = DEMO_SAHNELERI[0];
  for (const x of DEMO_SAHNELERI) if (x.bas <= s) cur = x;
  const i = DEMO_SAHNELERI.indexOf(cur);
  const son = i + 1 < DEMO_SAHNELERI.length ? DEMO_SAHNELERI[i + 1].bas : DEMO_SURE;
  return { ...cur, sira: i, t: s, kalan: son - s };
}

// "HH:MM-HH:MM" in the office zone: around now during lunch, else the usual 12:30-13:30 (moved by 12 hours when now
// happens to fall into it).
function ogleAraligi(now, tz, lunch) {
  const hm = (ms) => { const o = ofisSaati(ms, tz); return `${pad(o.saat)}:${pad(o.dakika)}`; };
  if (lunch) return `${hm(now - 60000)}-${hm(now + 30 * 60000)}`;
  const o = ofisSaati(now, tz);
  const m = o.saat * 60 + o.dakika;
  return m >= 12 * 60 + 30 && m < 13 * 60 + 30 ? '00:30-01:30' : '12:30-13:30';
}

// The script's sessions in the shape of state.sessions (bin/state.py: the job's model, tier and step joined in).
export function demoOturumlari(live, tasks, now) {
  return (live || []).map((x) => {
    const job = (tasks || []).find((j) => j.note === x.note) || {};
    return { name: x.name, project: x.project, status: x.status, kind: 'background', started_at: now,
      job_status: job.status || '', model: job.model || x.model || '', tier: job.tier || '', note: x.note || '',
      step_kind: job.step_kind || '', alt_ajanlar: (x.alt || []).map((h) => ({ ...h })) };
  });
}

// The demo's live part at loop second t and wall clock now (ms): tasks, sessions (state.sessions shape), decisions,
// model states, scene settings and the caption. opts.cevap = {t} when the owner answered the decision card at loop second
// t (the job goes back to its desk 2.5 s later); opts.today = 'YYYY-MM-DD'. Deterministic for (t, now, opts).
export function demoDurumu(t, now, opts = {}) {
  const sc = demoSahnesi(t);
  const s = sc.t;
  const at = (sec) => now - (s - sec) * 1000; // the wall clock of loop second sec
  const today = opts.today || localIso(new Date(now)).slice(0, 10);
  const tz = 'Europe/Istanbul';
  const tasks = [];
  const live = [];
  const ses = (name, project, status, note, x = {}) => live.push({ name, project, status, note, ...x });

  // steady work: ornek-uygulama (Kıdemli), kasa (Uzman); two idle sessions (tea, wander, lunch, home)
  tasks.push(jobAt('a.md', 'ornek-uygulama', 'calisiyor', 'Onboarding ekranındaki metinleri düzelt', at(0) - 40 * 60000, null,
    { tier: 'kod', model: 'opus', spent: '1.12', tokens: 412000, calls: '38', session: 'ofis-ornek-uygulama-a' }));
  ses('ofis-ornek-uygulama-a', 'ornek-uygulama', 'busy', 'a.md');
  tasks.push(jobAt('b.md', 'kasa', 'calisiyor', 'Aylık rapor CSV dışa aktarımı', at(0) - 25 * 60000, null,
    { tier: 'genel', model: 'sonnet', spent: '0.0423', tokens: 18300, calls: '9', max_calls: 40, session: 'ofis-kasa-b' }));
  ses('ofis-kasa-b', 'kasa', 'busy', 'b.md');
  ses('ofis-blog-bos', 'blog', 'idle', '', { model: 'claude-sonnet-4-5' });
  ses('ofis-atolye-bos', 'atolye', 'idle', '', { model: 'claude-haiku-4-5' });

  // the new job: lobby -> desk -> helper -> permission -> Kontrol -> ✓ -> lift
  if (s >= AN.gelis) {
    const n = { tier: 'kolay', model: 'haiku', max_calls: 15, session: 'ofis-blog-n1' };
    if (s < AN.calisma) {
      tasks.push(jobAt('n1.md', 'blog', 'sirada', 'RSS beslemesindeki tarih biçimi', null, null,
        { ...n, session: '', queue_position: 1, created: localIso(new Date(at(AN.gelis))) }));
    } else if (s < AN.bitti) {
      const status = s < AN.kontrol ? 'calisiyor' : 'kontrolde';
      tasks.push(jobAt('n1.md', 'blog', status, 'RSS beslemesindeki tarih biçimi', at(AN.calisma), null,
        { ...n, spent: '0.004', calls: String(3 + Math.floor((s - AN.calisma) / 4)) }));
      const alt = [];
      if (s >= AN.yardimci) {
        alt.push({ id: 'yardimci-1', model: 'claude-haiku-4-5', gorev: 'Tarih biçimlerini tarıyor',
          bitti: s >= AN['yardimci-bitti'], son_yazma: localIso(new Date(s >= AN['yardimci-bitti'] ? at(AN['yardimci-bitti']) : now)) });
      }
      const status2 = s >= AN.izin && s < AN.kontrol ? 'waiting' : s >= AN.kontrol ? 'idle' : 'busy';
      ses('ofis-blog-n1', 'blog', status2, 'n1.md', { alt });
    } else {
      tasks.push(jobAt('n1.md', 'blog', 'bitti', 'RSS beslemesindeki tarih biçimi', at(AN.calisma), at(AN.bitti),
        { ...n, spent: '0.0081', calls: '11' }));
    }
  }
  tasks.push(jobAt('e.md', 'blog', 'sirada', 'Etiket sayfası', null, null,
    { queue_position: 2, held: true, tier: 'kolay', model: 'haiku', session: '', created: localIso(new Date(at(0) - 30 * 60000)) }));

  // the decision: atolye's Genel Müdür waits at the CEO's door until the owner answers (or the scene ends)
  const c = { tier: 'planlama', model: 'fable', spent: '2.85', tokens: 1240000, calls: '41', max_calls: 60, session: 'ofis-atolye-c' };
  const answered = opts.cevap && Number.isFinite(opts.cevap.t) && opts.cevap.t >= AN.karar && s >= opts.cevap.t + 2.5;
  const asking = s >= AN.karar && s < AN.inceleme && !answered;
  const decisions = [];
  // until its job starts the Genel Müdür (fable) is the resident staff idling in the lounge; then it walks to the desk
  if (s >= AN.calisma) {
    tasks.push(jobAt('c.md', 'atolye', asking ? 'karar-bekliyor' : 'calisiyor', 'Ana sayfa yeniden tasarım taslağı',
      at(AN.calisma), null, c));
    ses('ofis-atolye-c', 'atolye', asking ? 'idle' : 'busy', 'c.md');
  }
  if (asking) {
    decisions.push({
      note: `${today}-atolye-renk-paleti.md`, project: 'atolye', title: 'atolye — Ana renk paleti',
      question: 'Ana sayfada sıcak şeftali paleti mi, yoksa mevcut lacivert tema mı kalsın? Önerim şeftali: marka diliyle uyumlu ve kontrast testlerinden geçiyor.',
      asked: localIso(new Date(at(AN.karar))).slice(0, 16), source: 'ofis-atolye-c', answer_sent: !!opts.cevap,
    });
  }

  // a workflow's approval card (from the escalation scene on, after kasa's review): evidence first — the Kontrol, what it proved and did not prove, the
  // agent's own decisions — the summary last, then the optional quiz (answers behind "Cevabı göster")
  if (s >= AN.yukseltme) {
    decisions.push(demoOnayKarti(today, at(AN.yukseltme), 'kasa', 'CSV dışa aktarımında tarih biçimi', 'normal'));
  }
  // the approval backlog (bin/dispatcher.py): in the lunch scene a second card waits, so new kod work is held
  const birikti = sc.id === 'ogle';
  if (birikti) {
    decisions.push(demoOnayKarti(today, at(AN.ogle), 'ornek-uygulama', 'Giriş ekranında boş parola uyarısı', 'yuksek'));
    tasks.push(jobAt('h.md', 'kasa', 'sirada', 'Fatura PDF şablonunu güncelle', null, null,
      { tier: 'kod', model: 'opus', session: '', queue_position: 1, onay_birikti: true,
        created: localIso(new Date(at(AN.ogle))) }));
  }

  // the review: queued in the lobby, then at a Kıdemli Tester desk of the QA odası, then ✓ and out
  const r = { tier: 'inceleme', model: 'opus', max_calls: 60, step_kind: 'kod-inceleme', session: 'ofis-atolye-r' };
  if (s < AN.inceleme) {
    tasks.push(jobAt('r.md', 'atolye', 'sirada', 'Kod incelemesi: İletişim formu', null, null, { ...r, session: '', queue_position: 1, created: localIso(new Date(at(0) - 20 * 60000)) }));
  } else if (s < AN.yukseltme) {
    tasks.push(jobAt('r.md', 'atolye', 'calisiyor', 'Kod incelemesi: İletişim formu', at(AN.inceleme), null,
      { ...r, spent: '0.2', calls: '5' }));
    ses('ofis-atolye-r', 'atolye', 'busy', 'r.md');
  } else {
    tasks.push(jobAt('r.md', 'atolye', 'bitti', 'Kod incelemesi: İletişim formu', at(AN.inceleme), at(AN.yukseltme),
      { ...r, spent: '0.31', calls: '8' }));
  }

  // the review panel: kasa's code review step goes to the external auditors (Codex + the free GLM and DeepSeek), then
  // the hakem (Sonnet, no session of its own) weighs their findings; the server's marker is state.denetim
  const p = { tier: 'inceleme', model: '', max_calls: 60, step_kind: 'kod-inceleme', inceleme_yurutucu: 'codex',
    workflow: 'akis-demo-kasa', step: '2', session: '' };
  let denetim = null;
  if (s >= AN.inceleme && s < AN.yukseltme) {
    tasks.push(jobAt('p.md', 'kasa', 'incelemede', 'Kod incelemesi: CSV dışa aktarımı', at(AN.inceleme), null, p));
    denetim = s < AN.hakem
      ? { is: 'p.md', denetciler: ['codex', 'glm', 'deepseek', 'guvenlik'], hakem: '',
        baslangic: localIso(new Date(at(AN.inceleme))) }
      : { is: 'p.md', denetciler: [], hakem: 'sonnet', baslangic: localIso(new Date(at(AN.hakem))) };
  } else if (s >= AN.yukseltme) {
    tasks.push(jobAt('p.md', 'kasa', 'bitti', 'Kod incelemesi: CSV dışa aktarımı', at(AN.inceleme), at(AN.yukseltme), p));
  }

  // the escalation: the Stajyer's job is stuck after two Kontrols; a Kıdemli takes it over
  const g = { tier: 'genel', model: 'haiku', max_calls: 40, session: 'ofis-ornek-uygulama-g' };
  if (s < AN.yukseltme) {
    tasks.push(jobAt('g.md', 'ornek-uygulama', 'calisiyor', 'Bildirim izinleri ekranı', at(0) - 30 * 60000, null,
      { ...g, spent: '0.09', tokens: 96500, calls: '22' }));
    ses('ofis-ornek-uygulama-g', 'ornek-uygulama', 'busy', 'g.md');
  } else {
    tasks.push(jobAt('g.md', 'ornek-uygulama', 'tikandi', 'Bildirim izinleri ekranı', at(0) - 30 * 60000, at(AN.yukseltme),
      { ...g, spent: '0.12', tokens: 128000, calls: '29' }));
    tasks.push(jobAt('h.md', 'ornek-uygulama', 'calisiyor', 'Bildirim izinleri ekranı', at(AN.yukseltme), null,
      { tier: 'kod', model: 'opus', spent: '0.05', calls: '2', escalated_from: 'g.md', session: 'ofis-ornek-uygulama-h' }));
    ses('ofis-ornek-uygulama-h', 'ornek-uygulama', 'busy', 'h.md');
  }

  // history for the İşler tab (no actor: finished long ago)
  tasks.push(jobAt('d.md', 'blog', 'bitti', 'Yazı listesinde sayfalama', at(0) - 180 * 60000, at(0) - 150 * 60000,
    { tier: 'kolay', model: 'haiku', spent: '0.0111', calls: '6', max_calls: 15, session: '' }));
  const wf = (note, n, kind, startMin, endMin, extra) => tasks.push(jobAt(note, 'ornek-uygulama', 'bitti',
    `${{ plan: 'Plan', 'plan-inceleme': 'Plan incelemesi', kod: 'Kod', 'kod-inceleme': 'Kod incelemesi', onay: 'Onay' }[kind]}: Profil fotoğrafı yükleme`,
    at(0) - startMin * 60000, at(0) - endMin * 60000, { workflow: 'akis-demo-ornek-uygulama', step: String(n), step_kind: kind,
      budget: kind === 'kod' ? 6 : 1.5, session: '', ...extra }));
  wf('w1.md', 1, 'plan', 240, 220, { tier: 'planlama', model: 'fable', spent: '0.62', calls: '14', max_calls: 60 });
  wf('w2.md', 2, 'plan-inceleme', 218, 210, { tier: 'inceleme', model: 'opus', spent: '0.28', calls: '6', max_calls: 60 });
  wf('w3.md', 3, 'kod', 208, 160, { tier: 'kod', model: 'opus', spent: '2.10', calls: '64' });
  wf('w4.md', 4, 'kod-inceleme', 158, 150, { tier: 'inceleme', model: 'opus', spent: '0.25', calls: '5', max_calls: 60 });
  wf('w5.md', 5, 'onay', 149, 120, {});

  // models: busy sessions per family; Sonnet's quota during the quota scene (back two hours later)
  const quota = s >= AN.kota && s < AN.donus;
  const fam = (m) => ['haiku', 'sonnet', 'opus', 'fable'].find((f) => String(m).includes(f)) || '';
  const busy = {};
  for (const x of live) {
    if (x.status !== 'busy') continue;
    const t2 = tasks.find((j) => j.note === x.note);
    const f = fam((t2 && t2.model) || x.model || '');
    if (f) busy[f] = (busy[f] || 0) + 1;
  }
  if (denetim && denetim.hakem) busy.sonnet = (busy.sonnet || 0) + 1; // the hakem's call
  if (denetim && denetim.denetciler.includes('guvenlik')) busy.sonnet = (busy.sonnet || 0) + 1; // the security call
  const back = Math.ceil((now + 2 * 3600000) / 300000) * 300000; // two hours later, on a 5-minute mark
  const modeller = ['haiku', 'sonnet', 'opus', 'fable'].map((m) => {
    const n = busy[m] || 0;
    const out = { model: m, unvan: { haiku: 'Stajyer', sonnet: 'Uzman', opus: 'Kıdemli', fable: 'Genel Müdür' }[m], calisan: n,
      durum: n ? 'calisiyor' : 'hazir', donus: null, son_hata: null };
    if (m === 'sonnet' && quota) Object.assign(out, { durum: 'kota', donus: new Date(back).toISOString(),
      son_hata: "You've hit your usage limit (demo)." });
    return out;
  });
  // the external auditors: Codex and the free reviewers (bin/model_durum.py rows: model = the reviewer's name)
  for (const ad of ['codex', 'glm', 'deepseek']) {
    const n = denetim && denetim.denetciler.includes(ad) ? 1 : 0;
    const out = { model: ad, unvan: 'Dış denetçi', calisan: n, durum: n ? 'calisiyor' : 'hazir', donus: null,
      son_hata: null };
    if (ad === 'deepseek' && quota) Object.assign(out, { durum: 'kota', son_hata: 'kota doldu (provider.quota)' });
    modeller.push(out);
  }
  // the security reviewer (a Claude call, bin/state.py): working while it runs, else its model's (Sonnet's) state
  const sonnet = modeller.find((x) => x.model === 'sonnet');
  const sec = !!denetim && denetim.denetciler.includes('guvenlik');
  modeller.push({ model: 'guvenlik', unvan: 'Güvenlik denetçisi', ajan_modeli: 'sonnet', calisan: sec ? 1 : 0,
    // like bin/state.py: idle, another Sonnet session at work never makes it "calisiyor"
    durum: sec ? 'calisiyor' : (sonnet.durum === 'calisiyor' ? 'hazir' : sonnet.durum), donus: sec ? null : sonnet.donus,
    son_hata: sec ? null : sonnet.son_hata });

  // mesai '': the demo plays every scene whatever the hour (no office hours: the staff are always in)
  const sahne = { ogle: ogleAraligi(now, tz, sc.id === 'ogle'), ...(sc.id === 'ogle' ? { ogle_hepsi: true } : {}), saat_dilimi: tz, mesai: '',
    sunucu_utc_ofset_dk: -new Date(now).getTimezoneOffset() };
  // the break scene: the demo's own setting sends every idle actor to the Oyun odası (the real schedule is seeded by
  // time, so a scripted loop could otherwise miss it; the server never sends `mola`)
  if (sc.id === 'mola') sahne.mola = 'oyun';
  const metin = sc.id === 'karar' && answered ? T('Cevap iletildi: ajan CEO kapısından masasına dönüyor') : T(sc.metin);
  const onay = decisions.filter((x) => x.kind === 'akis-onay').length;
  return { sahne_id: sc.id, sahne_metni: metin, tasks, live, decisions, modeller, denetim, sahne,
    onay_birikti: { bekleyen: onay, sinir: 2 } };
}

// A demo approval card in the card's order (bin/akis.py approval_card via bin/state.py pending_decisions).
function demoOnayKarti(today, asked, project, baslik, risk) {
  const yuksek = risk === 'yuksek';
  return {
    note: `${today}-akis-${project}-onay.md`, project, title: `${project} — Onay: ${baslik}`, kind: 'akis-onay', risk,
    guvenlik_acik: false, asked: localIso(new Date(asked)).slice(0, 16), source: '', answer_sent: false,
    question: `Risk: ${yuksek ? 'yüksek — kimlik doğrulama dosyasına dokunuyor' : 'normal — uygulama kodu değişti'}.\n` +
      `«${baslik}» akışı bitti (kucuk-is, 3 adım). Değişiklikleri onaylıyor musun? Hiçbir şey commit edilmedi, push yapılmadı.`,
    evidence: [
      { title: 'Nasıl test edildi', text: '- Kontrol: sunucu komutu proje klasöründe kendisi çalıştırdı → çıkış kodu 0 · süre 14 sn. Komut:\n\npytest -q tests/test_export.py\n\n- Çıktının sonu:\n\n6 passed in 1.42s\n- İnceleme: dış denetçi heyeti (codex ONAY, glm ONAY); hakem çağrılmadı (ciddi bulgu yok); karar ONAY; 1 tur.' },
      { title: 'Kontrol neyi kanıtladı / kanıtlamadı', text: 'Kanıt değerlendiricisi (Uzman, Sonnet), hakemin ayarlarıyla tek çağrı, Kontrol komutunu ve farkı okuyarak yazdı; bu bir değerlendirmedir, kanıt değildir (kendi sözleri, veri):\n- Kanıtladı:\n- CSV satırlarında tarih ISO biçiminde yazılıyor\n- boş tablo başlık satırıyla dışa aktarılıyor\n- Kanıtlamadı (elle bakılacaklar):\n- Excel\'in Türkçe yerel ayarıyla açılışı denenmedi\n- 10 000+ satırlık dosyada süre ölçülmedi' },
      { title: 'Ajanın kararları ve varsayımları', text: 'Kod ajanının bitti raporundaki «Verdiğim kararlar ve varsayımlar» bölümü (ajanın kendi sözleri, veri):\n- Ayırıcı noktalı virgül (Türkçe Excel varsayılanı) seçildi.\n- Saat dilimi Europe/Istanbul varsayıldı.\n- PDF dışa aktarımı kapsam dışı sayıldı.' },
      { title: 'Değişiklik özeti', text: 'git diff --stat (proje klasöründe, sunucu salt okunur çalıştırdı):\n\n export.py            | 18 +++++++++++-------\n tests/test_export.py | 24 ++++++++++++++++++++++++\n 2 files changed, 35 insertions(+), 7 deletions(-)' },
      { title: 'İnceleme', text: '- Karar: ONAY\n- Yürütücü: dış denetçi heyeti (codex, glm)\n- MINOR bulgu yok.' },
      { title: 'Güvenlik', text: 'Güvenlik denetçisi bu incelemede çalışmadı (risk normal).' },
      { title: 'Nasıl geri alınır', text: `Taban commit: 3f2a9c1 · yalnız ${sahip()} çalıştırır\n\ngit --literal-pathspecs restore --source 3f2a9c1 --staged --worktree -- export.py tests/test_export.py` },
      { title: 'Plan özeti', text: 'Plan adımı yok (küçük iş).' },
      { title: 'Kullanım', text: '- Toplam kayıtlı kullanım: API karşılığı ~$0.94 (akış kullanım sınırı ~$9 API karşılığı)' },
    ],
    quiz: [
      { soru: 'Dışa aktarımda hangi ayırıcı kullanılıyor?', cevap: 'Noktalı virgül (;)' },
      { soru: 'Boş tablo dışa aktarılınca dosyada ne olur?', cevap: 'Yalnız başlık satırı olur' },
    ],
  };
}

// mola / ceo (screenshots only, ?demo_mola=uyku&demo_ceo=dormant): force one idle-life break and the CEO's state.
// duyuru (screenshots only, ?demo_duyuru=<first line>): an announcement delivered at load (the conference hall).
// GET /api/ayarlar in the demo (bin/ayarlar.py ozet's shape) from the demo's projects; the demo saves nothing (app.js
// says "Demo modunda kaydedilmez" before any POST /api/ayarlar).
function demoAyarlar(s) {
  const rows = s.projects.map((p, i) => ({
    ad: p.name, path: `~/Dev/${p.klasor || p.name}`, tam_yol: `/Users/ornek/Dev/${p.klasor || p.name}`,
    description: p.description || '', notes: '', hassas_yollar: [], sorumlu: {}, sistem: {}, yerlesik: false,
    acik_is_sayisi: s.tasks.filter((t) => t.project === p.name && !['bitti', 'tikandi', 'iptal', 'basarisiz'].includes(t.status)).length,
    guven: i === s.projects.length - 1 ? false : true,
    ipucu: i === s.projects.length - 1 ? `cd /Users/ornek/Dev/${p.klasor || p.name} && claude` : '',
  }));
  rows.push({ ad: 'arge', path: '~/Dev/arge', tam_yol: '/Users/ornek/Dev/arge', description: 'Ar-Ge odasının çalışma klasörü',
    notes: '', hassas_yollar: [], sorumlu: {}, sistem: {}, yerlesik: true, acik_is_sayisi: 0, guven: true, ipucu: '' });
  return { ofis_adi: (s.ofis && s.ofis.adi) || 'Ofis', projeler: rows, kurallar: {
    ad_regex: '[a-z0-9][a-z0-9-]{0,39}', ayrilmis: ['ofis'], yerlesik: ['arge'], aciklama_siniri: 300, notlar_siniri: 2000,
    ofis_adi_siniri: 40, hassas_sayisi: 20, sorumlu_alanlari: ['dur_sor', 'asla', 'teslim'],
    sistem_alanlari: ['domainler', 'eposta_domaini', 'cloudflare'],
    alanlar: ['path', 'description', 'notes', 'hassas_yollar', 'sorumlu', 'sistem'],
    islemler: ['proje-ekle', 'proje-guncelle', 'proje-sil', 'genel'] } };
}

export function createDemo({ onState, onChat, onSahne = null, baslangic = 0, mola = '', ceo = '', duyuru = '' }) {
  const today = localIso(new Date()).slice(0, 10);
  const tools = [
    { name: 'Edit', target: 'OnboardingView.swift' }, { name: 'Read', target: 'README.md' },
    { name: 'Bash', target: '' }, { name: 'Write', target: 'plan.md' }, { name: 'Grep', target: '' },
  ];
  const project = (name, description, used, tool) => ({
    name, description, status: 'uyuyor', sessions: 0, usage_today: used,
    last_tool: tool ? { ...tool, time: new Date().toISOString() } : null, tasks: [],
  });
  const s = {
    today,
    projects: [
      { ...project('ornek-uygulama', 'Örnek mobil uygulama', 214000, tools[0]), cost_today: 1.2041, klasor: 'ornek-uygulama' },
      { ...project('atolye', 'Atölye sitesi', 48000, tools[1]), cost_today: 0.3105, klasor: 'atolye-site' },
      { ...project('blog', 'Kişisel blog', 6000, null), cost_today: 0.0123, klasor: 'blog' },
      { ...project('kasa', 'Gelir gider takibi', 91000, tools[3]), cost_today: 0.6522, klasor: 'kasa' },
    ],
    sessions: [],
    ceo: { state: 'idle', session_id: 'demo', queue: 0, name: 'ofis-ceo', usage_today: 36000, cost_today: 0.4123,
      current_tool: null, last_error: null },
    decisions: [],
    tasks: [],
    workflows: [{ grup: 'akis-demo-ornek-uygulama', baslik: 'Profil fotoğrafı yükleme', sablon: 'gelistir', proje: 'ornek-uygulama',
      durum: 'bitti', tamam: 5, toplam: 5 }],
    summary: {},
    // the schedules (bin/zamanla.py summaries) and the message delivery (bin/postoffice.py status) for the staff cards
    schedules: [
      { ad: 'sabah-testleri', proje: 'ornek-uygulama', baslik: 'Sabah test koşusu', zaman: 'her gün 08:30',
        sonraki: `${localIso(new Date(Date.now() + 86400000)).slice(0, 10)}T08:30`, duraklatildi: false, neden: '',
        son_is: '', son_sonuc: 'bitti', kosular: [
          { slot: `${localIso(new Date()).slice(0, 10)}T08:30`, is: 'demo-sabah-testleri-2.md', sonuc: 'bitti', son_is: '' },
          { slot: `${localIso(new Date(Date.now() - 86400000)).slice(0, 10)}T08:30`, is: 'demo-sabah-testleri-1.md', sonuc: 'bitti', son_is: '' }] },
      { ad: 'haftalik-ozet', proje: 'kasa', baslik: 'Haftalık gider özeti', zaman: 'pzt 09:00', sonraki: '',
        duraklatildi: true, neden: 'iki koşu takıldı', son_is: '', son_sonuc: 'tikandi', kosular: [
          { slot: `${localIso(new Date(Date.now() - 7 * 86400000)).slice(0, 10)}T09:00`, is: 'demo-haftalik-ozet-2.md', sonuc: 'tikandi', son_is: '' },
          { slot: `${localIso(new Date(Date.now() - 14 * 86400000)).slice(0, 10)}T09:00`, is: 'demo-haftalik-ozet-1.md', sonuc: 'tikandi', son_is: '' }] },
    ],
    // the newest rows of the server's error record (bin/olaylar.py son): the Ofis doktoru's card
    olaylar: [{ tur: 'teslim', ileti: 'ofis-blog-n1: delivery unconfirmed (claude timed out)', sayi: 1,
      son: `${localIso(new Date(Date.now() - 50 * 60000)).slice(0, 16).replace('T', ' ')}` }],
    sunucu: { baslangic: localIso(new Date(Date.now() - (3 * 60 + 25) * 60000)), pid: 4242 },
    // the Sunucu odası's lights (bin/sistem.py ozet): busy, one suggestion open (the IT sorumlusu's duty)
    sistem: { seviye: 'sari', oneri: 1, domain_sorunu: 0 },
    postoffice: { inbox: 0, outbox: 0, rejected: 0, rejected_outbox: 0, sessions: {}, last_error: null, silent: [] },
    agents_error: null,
    sahne: {},
    modeller: [],
    denetim: null,
    // The owner's Claude plan usage limits (bin/limitler.py sayfa): the top bar's pill; a click opens the usage popup
    limitler: { haftalik: { yuzde: 54, sifirlanma: Math.floor(Date.now() / 1000) + 3 * 86400, gecti: false },
      bes_saat: { yuzde: 62, sifirlanma: Math.floor(Date.now() / 1000) + 8040, gecti: false },
      olculdu: Math.floor(Date.now() / 1000) - 120, eski: false,
      metin: T("Haftalık sınır %54 · perşembe 22:00'de sıfırlanır · 5 saatlik %62 · 21:00'de"), kisa: T('Haftalık %54 · 5 saat %62') },
  };
  const chat = [
    { role: 'sahip', text: T('Günaydın. Bugün ornek-uygulama ve kasa işlerini başlat.'), time: ago(45).toISOString() },
    { role: 'ceo', text: T('Günaydın {sahip}. İkisini de başlattım; ornek-uygulama onboarding metinlerinde, kasa CSV dışa aktarımında.', { sahip: sahip() }), time: ago(44).toISOString() },
    // an office notice inline in the conversation (the Komuta masası gives it "Ayrıntı" / "Cevapla")
    { role: 'system', kind: 'notice', time: ago(12).toISOString(),
      text: `kasa akışı onay bekliyor: CSV dışa aktarımında tarih biçimi (akis-demo-kasa). Kararlar notu yazıldı: ${today}-akis-kasa-onay. Kartta kanıt var.` },
    { role: 'ceo', text: T("kasa'nın CSV işi onay bekliyor; kanıt kartta. **Risk normal**, Kontrol geçti."), time: ago(11).toISOString() },
  ];
  // GET /api/ceo/adimlar: the CEO's last tool steps (bin/adimlar.py shape: names and short targets only)
  const ADIMLAR = [
    ['Bash', 'python3 ofis.py durum', 'çalıştırdı', 2], ['Read', 'Index.md', 'okudu', 3],
    ['Read', `${today}-akis-kasa-onay.md`, 'okudu', 11], ['Write', 'cevap-1.txt', 'yazdı', 14],
    ['Bash', 'python3 ofis.py cevapla', 'çalıştırdı', 14], ['Grep', 'Kararlar', 'aradı', 20],
    ['Edit', 'Index.md', 'düzenledi', 21], ['Bash', 'claude agents', 'çalıştırdı', 30],
  ];

  // the loop clock: second `baslangic` of the script at page load; the decision answer is kept until the loop wraps
  const t0 = Date.now() - (Number(baslangic) || 0) * 1000;
  let cevap = null;
  let lastT = -1;
  let lastSahne = '';
  function fill() {
    const now = Date.now();
    const t = ((now - t0) / 1000) % DEMO_SURE;
    if (t < lastT) cevap = null; // a new loop
    lastT = t;
    const d = demoDurumu(t, now, { today, cevap });
    s.tasks = d.tasks;
    s.decisions = d.decisions;
    s.modeller = d.modeller;
    s.denetim = d.denetim;
    s.sahne = mola ? { ...d.sahne, mola } : d.sahne;
    if (['idle', 'dormant', 'busy'].includes(ceo)) s.ceo.state = ceo;
    s.board = s.tasks;
    s.board_hidden = 12; // older finished jobs the server would not send ("Daha eski 12 biten iş")
    for (const p of s.projects) {
      p.tasks = s.tasks.filter((x) => x.project === p.name).slice(0, 5);
      const mine = d.live.filter((x) => x.project === p.name && x.note);
      p.sessions = mine.length;
      p.status = mine.some((x) => x.status === 'waiting') || d.decisions.some((x) => x.project === p.name) ? 'bekliyor'
        : mine.some((x) => x.status === 'busy') ? 'calisiyor' : 'uyuyor';
    }
    s.sessions = demoOturumlari(d.live, s.tasks, now);
    const count = (st) => s.projects.filter((p) => p.status === st).length;
    const total = s.projects.reduce((a, p) => a + p.usage_today, s.ceo.usage_today);
    s.summary = {
      tasks_today: s.tasks.filter((x) => x.started.startsWith(today)).length,
      finished_today: s.tasks.filter((x) => ['bitti', 'tikandi', 'iptal', 'basarisiz'].includes(x.status) &&
        String(x.finished || '').startsWith(today)).length,
      working: count('calisiyor'), waiting: count('bekliyor'), sleeping: count('uyuyor'),
      usage_today: total, pending_decisions: s.decisions.length,
      running: s.tasks.filter((x) => ['baslatiliyor', 'calisiyor', 'kontrolde'].includes(x.status)).length,
      max_running: DEMO_MAX_RUNNING,
      max_running_per_project: 1,
      onay_birikti: d.onay_birikti,
    };
    if (onSahne && d.sahne_metni !== lastSahne) { lastSahne = d.sahne_metni; onSahne(d.sahne_metni, d.sahne_id); }
  }
  const emitState = () => { fill(); onState(structuredClone(s)); };
  const emitChat = () => onChat(structuredClone(chat));

  if (duyuru) s.duyuru = { id: 'demo', ilk_satir: duyuru, zaman: localIso(new Date()), sayi: 0, hedef: 0, alanlar: [] };

  let tick = 0;
  setInterval(() => {
    tick++;
    for (const p of s.projects) {
      if (p.status !== 'calisiyor') continue;
      p.usage_today += 400 + ((tick * 7919 + p.name.length * 104729) % 1500);
      if (tick % 4 === 0) p.last_tool = { ...tools[(tick / 4 + p.name.length) % tools.length], time: new Date().toISOString() };
    }
    emitState();
  }, 2000); // every 2 s: often enough for the script (scenes last 5 s or more), light on the side panels

  function ceoReply(text, delay = 2600) {
    s.ceo.state = 'busy';
    s.ceo.current_tool = { name: 'Read', target: 'Index.md', time: new Date().toISOString() };
    emitState();
    setTimeout(() => {
      chat.push({ role: 'ceo', text, time: new Date().toISOString() });
      s.ceo.state = 'idle'; s.ceo.current_tool = null; s.ceo.usage_today += 4200;
      emitChat(); emitState();
    }, delay);
  }

  async function post(path, body) {
    await new Promise((r) => setTimeout(r, 250));
    if (path === '/api/chat') {
      const busy = s.ceo.state === 'busy';
      chat.push({ role: 'sahip', text: body.text, time: new Date().toISOString() });
      emitChat();
      if (busy) {
        s.ceo.queue += 1; emitState();
        setTimeout(() => { s.ceo.queue = Math.max(0, s.ceo.queue - 1); ceoReply(T('Sıradaki mesajını da aldım. (demo)')); }, 3000);
        return { status: 202, data: { status: 'queued' } };
      }
      ceoReply(T('Tamam, not aldım. (demo cevabı)'));
      return { status: 202, data: { status: 'delivered' } };
    }
    if (path === '/api/answer') {
      const d = s.decisions.find((x) => x.note === body.note);
      if (!d) return { status: 404, data: { error: 'no such decision note' } };
      cevap = { t: lastT };
      chat.push({ role: 'sahip', text: body.answer, note: body.note, time: new Date().toISOString() });
      emitChat(); emitState();
      setTimeout(() => {
        chat.push({ role: 'ceo', text: T('Cevabını {proje} oturumuna olduğu gibi ilettim; ajan masasına dönüyor.', { proje: d.project }), time: new Date().toISOString() });
        emitChat(); emitState();
      }, 2600);
      return { status: 202, data: { status: 'delivered' } };
    }
    if (path === '/api/duyuru') { // the conference hall gathers for about a minute (no session is reached in the demo)
      const first = String(body.metin || '').trim().split('\n')[0].slice(0, 120);
      s.duyuru = { id: 'demo', ilk_satir: first, zaman: localIso(new Date()), sayi: 0, hedef: 0, alanlar: [] };
      emitState();
      return { status: 202, data: { duyuru: 'demo', hedef: 0, bitis: '' } };
    }
    return { status: 404, data: { error: 'not found' } };
  }

  async function get(path) {
    await new Promise((r) => setTimeout(r, 150));
    if (path === '/api/raporlar') return { status: 200, data: { raporlar: structuredClone(REPORTS) } };
    if (path === '/api/kalite') return { status: 200, data: structuredClone(QUALITY) };
    if (path === '/api/muhasebe') {
      return { status: 200, data: { ...structuredClone(MUHASEBE), gun: today, ay: today.slice(0, 7) } };
    }
    if (path === '/api/sistem') return { status: 200, data: SISTEM() };
    if (path === '/api/kullanim') return { status: 200, data: KULLANIM() };
    if (path === '/api/ayarlar') return { status: 200, data: demoAyarlar(s) }; // the Ayarlar tab: read only in the demo
    if (path === '/api/idari') return { status: 200, data: { ...structuredClone(IDARI), sunucu: s.sunucu, obsidian: { sorun: false, python: null } } };
    if (path === '/api/ceo/adimlar') {
      const busy = s.ceo.state === 'busy';
      const adimlar = ADIMLAR.map(([arac, hedef, ozet, min]) => ({ zaman: ago(min).toISOString(), arac, hedef, ozet }));
      if (busy) adimlar.unshift({ zaman: new Date().toISOString(), arac: 'Read', hedef: 'Index.md', ozet: 'okudu' });
      return { status: 200, data: { adimlar: adimlar.slice(0, 10), durum: s.ceo.state,
        arac_simdi: busy ? { arac: 'Read', hedef: 'Index.md', ozet: 'okuyor' } : null, sure_sn: busy ? 4 : 120 } };
    }
    if (path === '/api/ceo/turlar') { // the footer under each CEO reply (bin/adimlar.py ceo_turlari)
      const isler = [{ note: '2026-11-11-091500-ornek-uygulama.md', baslik: 'Onboarding metinleri', unvan: 'Kıdemli', akis: '', adim_sayisi: 0 }];
      const turlar = chat.filter((x) => x.role === 'ceo').map((x, i) => ({ cevap_zaman: x.time, adim: 2 + (i % 3),
        isler: i === 0 ? isler : [], usd: 0.03 + 0.01 * i, token: 12000 + 900 * i, fiyat_eksik: false })).reverse();
      return { status: 200, data: { turlar, kapaniyor: false } };
    }
    const m = path.match(/^\/api\/rapor\?grup=(.+)$/);
    const r = m && REPORTS.find((x) => x.grup === decodeURIComponent(m[1]));
    if (!r) return { status: 404, data: { error: 'not found' } };
    const metin = r.grup === 'giris-duzeltmeleri' ? REPORT_TEXT
      : `# ${r.proje} — ${r.baslik} (${r.grup})\n\n## Toplamlar\n\n- Demo raporu.\n`;
    return { status: 200, data: { ...structuredClone(r), metin } };
  }

  setTimeout(() => { emitState(); emitChat(); }, 0);
  return { post, get };
}
