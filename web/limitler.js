// The owner's Claude plan usage limits in the top bar (owner decision 2026-11-14; /api/state.limitler from bin/limitler.py).
// Pure helper, tested with node in test/test_limitler.py. The page writes its result with textContent only.

export const LIMIT_UYARI = 80;   // amber from here
export const LIMIT_KRITIK = 95;  // red from here

function yuzde(p) {
  return p && !p.gecti && Number.isFinite(p.yuzde) ? Math.max(0, Math.min(100, Math.round(p.yuzde))) : null;
}

// {gizli, metin, ton ('' | 'uyari' | 'kritik'), ipucu} — hidden when there is no data at all.
export function limitPill(l) {
  if (!l || typeof l !== 'object') return { gizli: true, metin: '', ton: '', ipucu: '' };
  const parts = [];
  let enYuksek = null;
  for (const [ad, etiket] of [['haftalik', 'Haftalık'], ['bes_saat', '5 saat']]) {
    const p = l[ad];
    if (!p || typeof p !== 'object') continue;
    const y = yuzde(p);
    if (y === null) { if (p.gecti) parts.push(`${etiket} sıfırlandı`); continue; }
    parts.push(`${etiket} %${y}`);
    enYuksek = enYuksek === null ? y : Math.max(enYuksek, y);
  }
  if (!parts.length) return { gizli: true, metin: '', ton: '', ipucu: '' };
  const ton = enYuksek === null ? '' : enYuksek >= LIMIT_KRITIK ? 'kritik' : enYuksek >= LIMIT_UYARI ? 'uyari' : '';
  const ipucu = 'Claude kullanım sınırı' + (typeof l.metin === 'string' && l.metin ? `: ${l.metin}` : '')
    + (l.eski ? ' (son ölçüm eski: değerler bir Claude oturumu açılınca yenilenir)' : '');
  return { gizli: false, metin: parts.join(' · '), ton, ipucu };
}

// The popup under the pill (owner decision 2026-11-16; GET /api/kullanim from bin/kullanim.py): each window's percentage with a
// bar, its reset time and when it was measured, and "En çok kullananlar" of the chosen window (sekme: 'bes_saat' |
// 'haftalik'). The server writes every Turkish usage text (tokens first, "API karşılığı ~$x"); this only checks the
// shapes and picks what to show. durum: '' | 'yukleniyor' | 'hata'. The page writes the result with textContent only.
const SEKMELER = ['bes_saat', 'haftalik'];
const metin = (v, n = 200) => (typeof v === 'string' ? v.slice(0, n) : '');

function satirGorunumu(r) {
  if (!r || typeof r !== 'object') return null;
  const ad = metin(r.ad, 160);
  if (!ad) return null;
  return { ad, metin: metin(r.metin, 120), cikti: metin(r.cikti_metni, 60),
    fiyatEksik: r.fiyat_eksik === true, tur: metin(r.tur, 20) };
}

export function kullanimGorunumu(data, sekme, durum = '') {
  const d = data && typeof data === 'object' ? data : {};
  const s = SEKMELER.includes(sekme) ? sekme : 'bes_saat';
  const lim = d.limitler && typeof d.limitler === 'object' ? d.limitler : null;
  const pencereler = [];
  for (const p of Array.isArray(lim && lim.pencereler) ? lim.pencereler : []) {
    if (!p || typeof p !== 'object') continue;
    const y = yuzde(p);
    pencereler.push({
      etiket: metin(p.etiket, 30) || 'Sınır',
      yuzdeMetni: y !== null ? `%${y}` : p.gecti ? 'sıfırlandı' : 'bilinmiyor',
      genislik: y ?? 0,
      ton: y === null ? '' : y >= LIMIT_KRITIK ? 'kritik' : y >= LIMIT_UYARI ? 'uyari' : '',
      yenilenir: metin(p.yenilenir, 80),
      kalan: metin(p.kalan, 40),
    });
  }
  const olcum = lim ? [metin(lim.olculdu, 60), lim.eski ? metin(lim.eski_aciklama, 160) : ''].filter(Boolean).join(' · ') : '';
  const dag = d.dagilim && typeof d.dagilim === 'object' ? d.dagilim[s] : null;
  const satirlar = (Array.isArray(dag && dag.satirlar) ? dag.satirlar : []).map(satirGorunumu).filter(Boolean);
  const toplam = dag ? satirGorunumu(dag.toplam) : null;
  let bos = '';
  if (durum === 'yukleniyor' && !dag) bos = 'Yükleniyor…';
  else if (durum === 'hata' && !dag) bos = 'Kullanım dökümü alınamadı.';
  else if (!satirlar.length) bos = 'Bu aralıkta kayıtlı kullanım yok.';
  return {
    pencereler,
    sinirYok: !pencereler.length && !(durum && !data) ? 'Sınır bilgisi yok: bir Claude oturumu açılınca gelir.' : '',
    olcum,
    sekme: s,
    aralik: dag ? metin(dag.aralik, 80) : '',
    satirlar,
    toplam: satirlar.length ? toplam : null,
    fiyatNotu: satirlar.some((r) => r.fiyatEksik) ? 'Bazı çağrıların fiyatı bilinmiyor; API karşılığı onlarsız hesaplandı.' : '',
    bos,
    not: metin(d.not, 300),
  };
}
