// Test support (test/test_npc.py): realistic /api/state fixtures for the living office's NPCs (shapes from bin/state.py build(), bin/duyuru.py son()).
// Every scenario is a function of the wall clock ms -> state; the day is 2026-11-12 in Europe/Istanbul (UTC+3).
export const TZ = 'Europe/Istanbul';
export const GUN0 = Date.UTC(2026, 10, 11, 21, 0, 0); // 2026-11-12 00:00 Istanbul
export const H = 3600000, M = 60000;
export const at = (hh, mm = 0, ss = 0) => GUN0 + hh * H + mm * M + ss * 1000;
const p2 = (n) => String(n).padStart(2, '0');
// naive server-local stamp (the server runs in Istanbul too: sunucu_utc_ofset_dk 180)
export function iso(ms) {
  const d = new Date(ms + 3 * H);
  return `${d.getUTCFullYear()}-${p2(d.getUTCMonth() + 1)}-${p2(d.getUTCDate())}T${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}:${p2(d.getUTCSeconds())}`;
}
const UNV = { haiku: 'Stajyer', sonnet: 'Uzman', opus: 'Kıdemli', fable: 'Genel Müdür' };
const KATMAN = { kolay: 'haiku', genel: 'sonnet', kod: 'opus', inceleme: 'opus', planlama: 'fable' };

// A job schedule entry -> its task row and session at ms.
// spec: {note, project, title, tier, model, created, start, end, outcome ('bitti'|'tikandi'), phases: [[from, to, status]],
//        sessionStatus: [[from, to, status]], helpers: [[from, to, id, model, gorev]], kontrol_deneme: [[from, n]],
//        sessionIdleFor (ms after end the session stays idle), extra}
function jobAt(spec, ms) {
  const created = spec.created ?? spec.start - 2 * M;
  if (ms < created) return null;
  const session = spec.session ?? `ofis-${spec.project}-${spec.note.split('-')[3]}`;
  let status = 'sirada';
  if (ms >= spec.start) status = 'calisiyor';
  if (spec.end != null && ms >= spec.end) status = spec.outcome || 'bitti';
  for (const [a, b, s] of spec.phases || []) if (ms >= a && ms < b) status = s;
  let kd = 0;
  for (const [a, n] of spec.kontrol_deneme || []) if (ms >= a) kd = n;
  let ks = '';
  for (const [a, v] of spec.kontrol_sonuc || []) if (ms >= a) ks = v;
  const spent = status === 'sirada' ? '' : String(Math.min(spec.budget ?? 3, 0.0005 * Math.max(0, (Math.min(ms, spec.end ?? ms) - spec.start) / 1000)).toFixed(4));
  const t = {
    note: spec.note, project: spec.project, status, title: spec.title, created: iso(created),
    started: ms >= spec.start ? iso(spec.start) : '', finished: spec.end != null && ms >= spec.end ? iso(spec.end) : '',
    session: ms >= spec.start ? session : '', short_id: 'a1b2c3d4', tier: spec.tier || '', model: spec.model ?? (KATMAN[spec.tier] || ''),
    spent, calls: status === 'sirada' ? '' : String(Math.floor((ms - spec.start) / 60000)), budget: spec.budget ?? 3,
    max_calls: spec.max_calls ?? 120, escalated_from: spec.escalated_from || '', workflow: spec.workflow || '', step: spec.step || '',
    step_kind: spec.step_kind || '', queue_position: status === 'sirada' ? (spec.queue_position ?? 1) : null,
    held: !!spec.held, depends: [], blocked: spec.blocked || '', kontrol_deneme: kd, kontrol_sonuc: ks, devam: spec.devam || 0,
    inceleme_yurutucu: spec.inceleme_yurutucu || '', tokens: null, ...(spec.extra || {}),
  };
  let ses = null;
  if (spec.noSession) return { t, ses: null };
  const idleFor = spec.sessionIdleFor ?? 10 * M;
  if (ms >= spec.start && (spec.end == null || ms < spec.end + idleFor)) {
    let sst = status === 'calisiyor' || status === 'baslatiliyor' ? 'busy' : 'idle';
    for (const [a, b, s] of spec.sessionStatus || []) if (ms >= a && ms < b) sst = s;
    const alt = [];
    for (const [a, b, id, model, gorev] of spec.helpers || []) {
      if (ms < a) continue;
      if (ms < b) alt.push({ id, model, gorev, son_yazma: iso(ms), bitti: false });
      else if (ms < b + 60000) alt.push({ id, model, gorev, son_yazma: iso(b), bitti: true });
    }
    ses = { name: session, project: spec.project, status: sst, kind: 'background', started_at: iso(spec.start),
      job_status: status, model: t.model, tier: t.tier, note: spec.note, step_kind: t.step_kind, alt_ajanlar: alt };
  }
  return { t, ses };
}

function modelRows(sessions, tasks, over = {}, ms = 0, denetim = null) {
  const fam = (m) => ['haiku', 'sonnet', 'opus', 'fable'].find((f) => String(m || '').includes(f)) || '';
  const busy = {};
  for (const s of sessions) if (s.status === 'busy') { const f = fam(s.model); if (f) busy[f] = (busy[f] || 0) + 1; }
  if (denetim && denetim.hakem) busy[fam(denetim.hakem)] = (busy[fam(denetim.hakem)] || 0) + 1;
  const rows = ['haiku', 'sonnet', 'opus', 'fable'].map((m) => ({ model: m, unvan: UNV[m], calisan: busy[m] || 0,
    durum: busy[m] ? 'calisiyor' : 'hazir', donus: null, son_hata: null }));
  for (const ad of ['codex', 'glm', 'deepseek', 'antigravity']) {
    const n = denetim && (denetim.denetciler || []).includes(ad) ? 1 : 0;
    rows.push({ model: ad, unvan: 'Dış denetçi', calisan: n, durum: n ? 'calisiyor' : 'hazir', donus: null, son_hata: null });
  }
  const sec = !!denetim && (denetim.denetciler || []).includes('guvenlik');
  const sonnet = rows.find((r) => r.model === 'sonnet');
  rows.push({ model: 'guvenlik', unvan: 'Güvenlik denetçisi', ajan_modeli: 'sonnet', calisan: sec ? 1 : 0,
    durum: sec ? 'calisiyor' : (sonnet.durum === 'calisiyor' ? 'hazir' : sonnet.durum), donus: null, son_hata: null });
  for (const [m, patch] of Object.entries(over)) {
    const r = rows.find((x) => x.model === m);
    if (r) Object.assign(r, typeof patch === 'function' ? patch(ms) : patch);
  }
  return rows;
}

const PROJ = { vitrin: 'Dilek uygulaması', kasa: 'Kişisel muhasebe', blog: 'Kişisel blog', atolye: 'Tasarım atölyesi',
  p5: 'Proje 5', p6: 'Proje 6', p7: 'Proje 7', p8: 'Proje 8', p9: 'Proje 9', p10: 'Proje 10' };

// Builds a state from a spec: {projects, jobs: [spec], decisions: [{note, asked, answered, gone, ...}], ceo: fn(ms) | obj,
// over: model overrides, denetim: fn(ms), duyuru: fn(ms), per (max_running_per_project)}
export function durumOlustur(spec, ms) {
  const tasks = [];
  const sessions = [];
  for (const j of spec.jobs || []) {
    const r = jobAt(j, ms);
    if (!r) continue;
    tasks.push(r.t);
    if (r.ses) sessions.push(r.ses);
  }
  for (const s of spec.idleSessions || []) {
    if (s.from != null && ms < s.from) continue;
    if (s.to != null && ms >= s.to) continue;
    sessions.push({ name: s.name, project: s.project, status: 'idle', kind: 'background', started_at: iso(s.from ?? GUN0),
      job_status: '', model: s.model || 'claude-sonnet-4-5', tier: '', note: s.note || '', step_kind: '', alt_ajanlar: [] });
  }
  tasks.sort((a, b) => (b.started || b.created).localeCompare(a.started || a.created));
  const decisions = [];
  for (const d of spec.decisions || []) {
    if (ms < d.asked || (d.gone != null && ms >= d.gone)) continue;
    decisions.push({ note: d.note, project: d.project, title: d.title, kind: d.kind || 'soru', asked: iso(d.asked).slice(0, 16),
      source: d.source || '', answer_sent: d.answered != null && ms >= d.answered, risk: d.risk || undefined,
      guvenlik_acik: !!d.guvenlik_acik, question: 'Soru metni' });
  }
  const denetim = typeof spec.denetim === 'function' ? spec.denetim(ms) : null;
  const ceo = typeof spec.ceo === 'function' ? spec.ceo(ms) : { state: 'idle', queue: 0, alt_ajanlar: [], ...(spec.ceo || {}) };
  const projects = (spec.projects || []).map((name) => ({ name, description: PROJ[name] || name, klasor: name,
    status: 'uyuyor', sessions: sessions.filter((s) => s.project === name).length, usage_today: 0, cost_today: 0,
    last_tool: null, tasks: tasks.filter((t) => t.project === name).slice(0, 5) }));
  const duyuru = typeof spec.duyuru === 'function' ? spec.duyuru(ms, sessions) : null;
  return {
    today: '2026-11-12', projects, sessions, ceo: { name: 'ofis-ceo', cost_today: 0.42, usage_today: 120000, current_tool: null, ...ceo },
    decisions, tasks, board: tasks.slice(0, 30), board_hidden: 0, workflows: spec.workflows || [], schedules: spec.schedules || [],
    summary: { tasks_today: tasks.filter((t) => t.started.startsWith('2026-11-12')).length,
      finished_today: tasks.filter((t) => ['bitti', 'tikandi', 'iptal', 'basarisiz'].includes(t.status) && t.finished.startsWith('2026-11-12')).length,
      pending_decisions: decisions.length, running: tasks.filter((t) => ['baslatiliyor', 'calisiyor', 'kontrolde'].includes(t.status)).length,
      max_running: 3, max_running_per_project: spec.per ?? 1, onay_birikti: { bekleyen: 0, sinir: 2 } },
    agents_error: null,
    postoffice: { errors: [], rejected_reports: 0, rejected_answers: 0, silent: spec.silent ? spec.silent(ms) : [] },
    modeller: modelRows(sessions, tasks, spec.over || {}, ms, denetim),
    denetim, sahne: { ogle: spec.ogle || '12:00-13:00', saat_dilimi: TZ, sunucu_utc_ofset_dk: 180 },
    sunucu: { baslangic: iso(GUN0 - 2 * H), pid: 1234, port: 8800 }, olaylar: [], duyuru,
    son_rapor: typeof spec.son_rapor === 'function' ? spec.son_rapor(ms) : null,
    sistem: typeof spec.sistem === 'function' ? spec.sistem(ms) : (spec.sistem || null),
    gun_sonu: typeof spec.gun_sonu === 'function' ? spec.gun_sonu(ms) : (spec.gun_sonu || null),
  };
}

// ---- the scenarios ----
const J = (o) => o;
// 4 busy projects: every project gets a job every 2 hours 08:00-20:00, each 1 h 45 min; helpers; a night job at 02:00
function dortProjeIsleri(projs, yardimci = 2) {
  const tiers = { vitrin: ['kod', 'opus'], kasa: ['genel', 'sonnet'], blog: ['kolay', 'haiku'], atolye: ['planlama', 'fable'] };
  const jobs = [];
  projs.forEach((p, pi) => {
    for (let k = 0; k < 6; k++) {
      const start = at(8 + 2 * k, 5 * pi);
      const [tier, model] = tiers[p] || ['kod', 'opus'];
      jobs.push(J({ note: `2026-11-12-${p2(8 + 2 * k)}${p2(5 * pi)}00-${p}.md`, project: p, title: `${p} işi ${k + 1}`, tier, model,
        created: start - 30 * M, start, end: start + 105 * M, outcome: k === 3 && p === 'kasa' ? 'tikandi' : 'bitti',
        helpers: k % 2 !== 0 ? [] : yardimci === 3
          // Step 3 (owner decision 2026-11-13): a kod session gives independent parts to at most 3 helpers at once
          ? ['a', 'b', 'c'].map((x, i) => [start + 10 * M, start + 40 * M, `h${k}${x}`, 'claude-sonnet-4-5', `Parça ${i + 1}`])
          : [[start + 10 * M, start + 25 * M, `h${k}a`, 'claude-haiku-4-5', 'Dosyaları tarıyor'],
            [start + 12 * M, start + 20 * M, `h${k}b`, 'claude-haiku-4-5', 'Testleri çalıştırıyor']],
        phases: [[start + 90 * M, start + 95 * M, 'kontrolde']], sessionIdleFor: 10 * M }));
    }
  });
  // a night job
  jobs.push(J({ note: '2026-11-12-020000-vitrin.md', project: 'vitrin', title: 'Gece bağımlılık güncellemesi', tier: 'kod',
    model: 'opus', start: at(2), end: at(3, 30), outcome: 'bitti', sessionIdleFor: 5 * M }));
  // a review step in the Uzmanlar odası (Claude review), 15:00-15:20
  jobs.push(J({ note: '2026-11-12-150000-kasa-inceleme.md', project: 'kasa', title: 'Kod incelemesi: CSV', tier: 'inceleme',
    model: 'opus', step_kind: 'kod-inceleme', workflow: 'akis-kasa', step: '4', start: at(15), end: at(15, 20), outcome: 'bitti' }));
  // a lobby backlog 09:00-17:00: 8 queued jobs
  for (let i = 0; i < 8; i++) {
    const p = projs[i % projs.length];
    jobs.push(J({ note: `2026-11-12-0900${p2(i)}-${p}-sira.md`, project: p, title: `Sıradaki iş ${i + 1}`, tier: 'kolay',
      model: '', created: at(9), start: at(17), end: at(17, 30), queue_position: Math.floor(i / projs.length) + 1, held: i === 5 }));
  }
  return jobs;
}
const ceoGun = (ms) => {
  // the CEO is busy now and then (the owner writes), idle otherwise, dormant at night
  const h = (ms - GUN0) / H;
  if (h < 7 || h >= 23) return { state: 'dormant', queue: 0, alt_ajanlar: [] };
  const m = Math.floor((ms - GUN0) / M) % 60;
  return m < 8 ? { state: 'busy', queue: 0, alt_ajanlar: [], current_tool: 'Bash' } : { state: 'idle', queue: 0, alt_ajanlar: [] };
};

export const SENARYOLAR = {
  'bos-ofis': { projects: [], jobs: [], ceo: { state: 'idle' } },
  'tek-proje-ceo-bosta': {
    projects: ['vitrin'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-100000-vitrin.md', project: 'vitrin', title: 'Giriş ekranı', tier: 'kod', model: 'opus',
      start: at(10), end: at(11, 30), outcome: 'bitti', sessionIdleFor: 60 * M })],
  },
  'dort-mesgul': { projects: ['vitrin', 'kasa', 'blog', 'atolye'], jobs: dortProjeIsleri(['vitrin', 'kasa', 'blog', 'atolye']), ceo: ceoGun },
  'ceo-uyuyor': { projects: ['vitrin'], jobs: [], ceo: { state: 'dormant' } },
  'kararlar': {
    projects: ['vitrin', 'atolye'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-093000-atolye.md', project: 'atolye', title: 'Renk paleti planı', tier: 'planlama', model: 'fable',
      start: at(9, 30), end: at(13), outcome: 'bitti', phases: [[at(10), at(11), 'karar-bekliyor']], sessionStatus: [[at(10), at(11), 'idle']] })],
    decisions: [
      { note: '2026-11-12-vitrin-soru-1.md', project: 'vitrin', title: 'vitrin — Bildirim metni', asked: at(9), gone: at(16) },
      { note: '2026-11-12-atolye-renk.md', project: 'atolye', title: 'atolye — Renk paleti', asked: at(10), answered: at(11), gone: at(11, 5) },
      { note: '2026-11-12-vitrin-soru-2.md', project: 'vitrin', title: 'vitrin — Dil seçimi', asked: at(10), gone: at(16), risk: 'yuksek' },
      { note: '2026-11-09-vitrin-kod-model-onerisi.md', project: 'vitrin', title: 'vitrin kod kadro önerisi', kind: 'model-onerisi', asked: at(-72), gone: at(16) },
    ],
  },
  'takildi-kirmizi': {
    projects: ['vitrin', 'kasa'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-080000-vitrin.md', project: 'vitrin', title: 'Ödeme ekranı', tier: 'kod', model: 'opus',
      start: at(8), end: at(10), outcome: 'tikandi', sessionIdleFor: 8 * H }),
    J({ note: '2026-11-12-090000-kasa.md', project: 'kasa', title: 'Rapor', tier: 'genel', model: 'sonnet', start: at(9), end: at(17), outcome: 'bitti' })],
    over: { sonnet: (ms) => (ms >= at(14) && ms < at(15) ? { durum: 'hata', son_hata: 'API Error 500' } : {}),
      codex: (ms) => (ms >= at(16) && ms < at(16, 30) ? { durum: 'hata', son_hata: 'codex çıkış kodu 1' } : {}) },
  },
  'kontrol': {
    projects: ['vitrin'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-093000-vitrin.md', project: 'vitrin', title: 'Profil fotoğrafı', tier: 'kod', model: 'opus',
      start: at(9, 30), end: at(10, 40), outcome: 'bitti', phases: [[at(10), at(10, 10), 'kontrolde'], [at(10, 30), at(10, 40), 'kontrolde']],
      sessionStatus: [[at(10), at(10, 10), 'idle'], [at(10, 30), at(10, 40), 'idle']], kontrol_deneme: [[at(10), 1], [at(10, 30), 2]] })],
  },
  'izin': {
    projects: ['vitrin'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-093000-vitrin.md', project: 'vitrin', title: 'Bildirim izinleri', tier: 'kod', model: 'opus',
      start: at(9, 30), end: at(11), outcome: 'bitti', sessionStatus: [[at(10), at(10, 30), 'waiting']] })],
    silent: (ms) => (ms >= at(10, 2) && ms < at(10, 30) ? [{ proje: 'vitrin', izin: true, seconds: (ms - at(10)) / 1000, job: '2026-11-12-093000-vitrin.md' }] : []),
  },
  'codex-kota': {
    projects: ['kasa'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-110000-kasa-inc.md', project: 'kasa', title: 'Kod incelemesi: fatura', tier: 'inceleme', model: '',
      step_kind: 'kod-inceleme', inceleme_yurutucu: 'codex', start: at(11), end: at(11, 15), outcome: 'bitti', noSession: true,
      phases: [[at(11), at(11, 15), 'incelemede']] })],
    denetim: (ms) => (ms >= at(11) && ms < at(11, 10) ? { is: '2026-11-12-110000-kasa-inc.md', denetciler: ['codex', 'glm', 'guvenlik'], hakem: '', baslangic: iso(at(11)) }
      : ms >= at(11, 10) && ms < at(11, 15) ? { is: '2026-11-12-110000-kasa-inc.md', denetciler: [], hakem: 'sonnet', baslangic: iso(at(11, 10)) } : null),
    over: { codex: (ms) => (ms >= at(9) && ms < at(13) ? { durum: 'kota', donus: new Date(at(13)).toISOString(), son_hata: 'usage limit' } : {}),
      deepseek: (ms) => (ms >= at(9) && ms < at(13) ? { durum: 'kota', donus: null, son_hata: 'provider.quota' } : {}) },
  },
  'ogle': {
    projects: ['vitrin', 'kasa', 'blog', 'atolye'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-113000-vitrin.md', project: 'vitrin', title: 'Uzun iş', tier: 'kod', model: 'opus', start: at(11, 30), end: at(14), outcome: 'bitti' })],
    idleSessions: ['kasa', 'blog', 'atolye'].map((p, i) => ({ name: `ofis-${p}-bos`, project: p, model: ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-5'][i] })),
  },
  'duyuru': {
    projects: ['vitrin', 'kasa'], ceo: { state: 'idle' },
    jobs: [J({ note: '2026-11-12-140000-vitrin.md', project: 'vitrin', title: 'Uzun iş', tier: 'kod', model: 'opus', start: at(14), end: at(16), outcome: 'bitti' }),
      J({ note: '2026-11-12-140500-kasa.md', project: 'kasa', title: 'Rapor', tier: 'genel', model: 'sonnet', start: at(14, 5), end: at(16), outcome: 'bitti' })],
    duyuru: (ms, sessions) => (ms >= at(15) ? { id: '20261112-150000-ab12', ilk_satir: 'Yarın 10:00 bakım var', zaman: iso(at(15)), sayi: 2, hedef: 2,
      alanlar: ['ofis-vitrin-140000', 'ofis-kasa-140500'] } : null),
  },
};
SENARYOLAR.hafif = { ...SENARYOLAR['dort-mesgul'], hafif: true };
SENARYOLAR['uc-yardimci'] = { ...SENARYOLAR['dort-mesgul'], jobs: dortProjeIsleri(['vitrin', 'kasa', 'blog', 'atolye'], 3) };
// the Sunucu odası's IT team: a suggestion open 02:00-03:00 (night shift alone) and 14:00-17:00 (across the 16:00 change,
// with the day-shift colleague in the office afterwards)
SENARYOLAR['it-uyari'] = { projects: ['vitrin'], jobs: [], ceo: { state: 'idle' },
  sistem: (ms) => ({ seviye: 'sari', domain_sorunu: 0,
    oneri: (ms >= at(2) && ms < at(3)) || (ms >= at(14) && ms < at(17)) ? 1 : 0 }) };
// the Ar-Ge odası (plan "Sonraki iş (6)"): the arge workspace's research jobs — one at night, the daily one at 09:00 with a
// question to the owner in the middle — beside a vitrin job; the Ar-Ge uzmanı stands for them (no robot of their own)
SENARYOLAR['arge-gunu'] = { projects: ['vitrin', 'arge'], ceo: { state: 'idle' }, jobs: [
  J({ note: '2026-11-12-020000-arge.md', project: 'arge', title: 'Gece Ar-Ge', tier: 'genel', model: 'sonnet',
    start: at(2), end: at(2, 30), outcome: 'bitti', sessionIdleFor: 5 * M }),
  J({ note: '2026-11-12-090000-arge.md', project: 'arge', title: 'Günlük Ar-Ge taraması', tier: 'genel', model: 'sonnet',
    start: at(9), end: at(9, 50), outcome: 'bitti', phases: [[at(9, 20), at(9, 30), 'karar-bekliyor']], sessionIdleFor: 10 * M }),
  J({ note: '2026-11-12-093000-vitrin.md', project: 'vitrin', title: 'Giriş ekranı', tier: 'kod', model: 'opus',
    start: at(9, 30), end: at(10, 30), outcome: 'bitti' })] };
// the end-of-day review (bin/gunsonu.py; owner decision 2026-11-13): the measurement at 20:05 (2 bad cases), the review job in
// the arge workspace 20:20-20:50 (a question to the owner 20:30-20:35); state.gun_sonu as bin/gunsonu.py ozet_durumu sends it
export function gunSonuDurumu(ms, olcum = at(20, 5), is = '2026-11-12-201000-arge.md') {
  const son = ms < olcum ? null : { gun: '2026-11-12', not: 'GunSonu-2026-11-12', olcum_zamani: iso(olcum).replace('T', ' '),
    olcum_saati: iso(olcum).slice(11, 16), olcum_iso: new Date(olcum).toISOString(),
    sayilar: { bitti: 22, tikandi: 1, basarisiz: 0, kontrol: 20, kontrol_ilk: 18, usd: 4.2, token: 1800000 },
    kotu: 2, is, rapor: ms >= at(20, 50) ? 'bitti' : '', oneri: ms >= at(20, 50) ? 3 : 0 };
  return { acik: true, pencere: '20:00–24:00', aktif_dk: 10, son, atlananlar: ['2026-11-10'] };
}
const gunSonuIsi = () => J({ note: '2026-11-12-201000-arge.md', project: 'arge', title: 'Gün sonu değerlendirmesi — 12 Kasım 2026',
  tier: 'genel', model: 'sonnet', created: at(20, 5), start: at(20, 20), end: at(20, 50), outcome: 'bitti',
  phases: [[at(20, 30), at(20, 35), 'karar-bekliyor']], sessionIdleFor: 5 * M, extra: { gun_sonu: '2026-11-12' } });
SENARYOLAR['gun-sonu'] = { projects: ['vitrin', 'arge'], ceo: { state: 'idle' }, gun_sonu: (ms) => gunSonuDurumu(ms),
  jobs: [J({ note: '2026-11-12-193000-vitrin.md', project: 'vitrin', title: 'Akşam işi', tier: 'kod', model: 'opus',
    start: at(19, 30), end: at(20, 40), outcome: 'tikandi' }), gunSonuIsi()] };
// the busiest office in the evening window, with the team at work (the draw-call budget)
SENARYOLAR['dort-mesgul-aksam'] = { ...SENARYOLAR['dort-mesgul'], projects: ['vitrin', 'kasa', 'blog', 'atolye', 'arge'],
  jobs: [...SENARYOLAR['dort-mesgul'].jobs, gunSonuIsi()], gun_sonu: (ms) => gunSonuDurumu(ms) };
// the biggest office (performance): 10 projects, 6 desks each, all busy with helpers, 20 queued, 5 decisions, a review
export function buyukOfis() {
  const projs = ['vitrin', 'kasa', 'blog', 'atolye', 'p5', 'p6', 'p7', 'p8', 'p9', 'p10'];
  const jobs = [];
  projs.forEach((p, pi) => {
    for (let d = 0; d < 6; d++) {
      const fam = ['opus', 'sonnet', 'haiku', 'fable', 'opus', 'sonnet'][d];
      jobs.push(J({ note: `2026-11-12-0${d}${p2(pi)}00-${p}.md`, project: p, title: `${p} iş ${d}`, tier: { opus: 'kod', sonnet: 'genel', haiku: 'kolay', fable: 'planlama' }[fam],
        model: fam, start: at(8, d), end: null, helpers: [[at(8, 30), at(23), `h${d}a`, 'claude-haiku-4-5', 'tarıyor'], [at(8, 30), at(23), `h${d}b`, 'claude-sonnet-4-5', 'test']] }));
    }
    for (let q = 0; q < 2; q++) jobs.push(J({ note: `2026-11-12-0900${q}-${p}-q.md`, project: p, title: 'sıradaki', tier: 'kolay', created: at(8), start: at(23), end: at(23, 30) }));
  });
  return { projects: projs, jobs, per: 4, ceo: { state: 'busy', alt_ajanlar: [{ id: 'c1', model: 'claude-haiku-4-5', gorev: 'okuyor', bitti: false }] },
    decisions: [0, 1, 2, 3, 4].map((i) => ({ note: `2026-11-12-k${i}.md`, project: projs[i], title: `karar ${i}`, asked: at(9, i) })),
    denetim: () => ({ is: '2026-11-12-000000-vitrin.md', denetciler: ['codex', 'glm', 'deepseek', 'guvenlik'], hakem: '', baslangic: iso(at(9)) }) };
}

// B1 event scenarios
SENARYOLAR.yukseltme = {
  projects: ['vitrin'], ceo: { state: 'idle' },
  jobs: [J({ note: '2026-11-12-090000-vitrin-g.md', project: 'vitrin', title: 'Bildirim izinleri', tier: 'kolay', model: 'haiku',
    start: at(9), end: at(10), outcome: 'tikandi', sessionIdleFor: 0, kontrol_deneme: [[at(9, 40), 1], [at(9, 55), 2]] }),
  J({ note: '2026-11-12-100000-vitrin-h.md', project: 'vitrin', title: 'Bildirim izinleri', tier: 'kod', model: 'opus',
    created: at(10), start: at(10, 0, 15), end: at(11), outcome: 'bitti', escalated_from: '2026-11-12-090000-vitrin-g.md',
    helpers: [[at(10, 5), at(10, 8), 'y1', 'claude-haiku-4-5', 'Dosyaları tarıyor']] })],
  decisions: [{ note: '2026-11-12-akis-vitrin-onay.md', project: 'vitrin', title: 'vitrin — Onay: bildirimler', kind: 'akis-onay', risk: 'yuksek', asked: at(14), answered: at(14, 20), gone: at(14, 21) }],
};
SENARYOLAR['kota-sonnet'] = {
  projects: ['kasa'], ceo: { state: 'idle' },
  jobs: [J({ note: '2026-11-12-100000-kasa.md', project: 'kasa', title: 'Rapor', tier: 'genel', model: 'sonnet', start: at(10), end: at(12, 50), outcome: 'bitti', sessionIdleFor: 4 * H })],
  over: { sonnet: (ms) => (ms >= at(13) && ms < at(15) ? { durum: 'kota', donus: new Date(at(15)).toISOString(), son_hata: 'usage limit' } : {}) },
};

// B4 cue scenarios
SENARYOLAR['ipuclari'] = {
  projects: ['vitrin', 'kasa'], ceo: { state: 'idle' },
  jobs: [
    // a new job added at 09:00 (queued), started at 09:02
    J({ note: '2026-11-12-090000-vitrin.md', project: 'vitrin', title: 'Yeni iş', tier: 'kod', model: 'opus',
      created: at(9), start: at(9, 2), end: at(9, 40), outcome: 'bitti',
      phases: [[at(9, 20), at(9, 25), 'kontrolde']], sessionStatus: [[at(9, 20), at(9, 25), 'idle']],
      kontrol_deneme: [[at(9, 20), 1]], kontrol_sonuc: [[at(9, 25), 'kaldi']] }),
    // a workflow: kod 10:00-10:30, its code review 10:31-10:40 (Codex), DÜZELT: the kod job works again from 10:40
    J({ note: '2026-11-12-100000-kasa.md', project: 'kasa', title: 'Kod', tier: 'kod', model: 'opus', step_kind: 'kod', workflow: 'akis-k',
      start: at(10), end: at(11), outcome: 'bitti', phases: [[at(10, 30), at(10, 40), 'bitti']],
      sessionStatus: [[at(10, 30), at(10, 40), 'idle']] }),
    J({ note: '2026-11-12-103100-kasa-inc.md', project: 'kasa', title: 'Kod incelemesi', tier: 'inceleme', model: '',
      step_kind: 'kod-inceleme', workflow: 'akis-k', inceleme_yurutucu: 'codex', created: at(10, 30), start: at(10, 31),
      end: at(10, 40), outcome: 'bitti', noSession: true, phases: [[at(10, 31), at(10, 40), 'incelemede']] }),
  ],
  denetim: (ms) => (ms >= at(10, 31) && ms < at(10, 40) ? { is: '2026-11-12-103100-kasa-inc.md', denetciler: ['codex'], hakem: '', baslangic: iso(at(10, 31)) } : null),
  son_rapor: (ms) => (ms >= at(11, 30) ? { grup: 'giris', baslik: 'Giriş', yazildi: iso(at(11, 30)) } : null),
};

// The company structure (plan "Sonraki iş (9)" step 1): one workflow of vitrin — its plan (Fable) 09:00-09:30, the plan
// review (Claude) 09:31-09:45, the kod step 09:46-10:30, the code review (Claude, Stajyer: haiku) 10:31-10:40 — and
// its approval card at 10:41; each step is added two minutes before it starts (it waits in the lobby).
SENARYOLAR.sirket = {
  projects: ['vitrin'], ceo: { state: 'idle' },
  jobs: [
    J({ note: '2026-11-12-090000-vitrin-plan.md', project: 'vitrin', title: 'Bildirimler planı', tier: 'planlama', model: 'fable',
      step_kind: 'plan', workflow: 'akis-w', step: '1', start: at(9), end: at(9, 30), outcome: 'bitti' }),
    J({ note: '2026-11-12-093100-vitrin-pinc.md', project: 'vitrin', title: 'Plan incelemesi', tier: 'inceleme', model: 'opus',
      step_kind: 'plan-inceleme', workflow: 'akis-w', step: '2', start: at(9, 31), end: at(9, 45), outcome: 'bitti' }),
    J({ note: '2026-11-12-094600-vitrin-kod.md', project: 'vitrin', title: 'Bildirimler', tier: 'kod', model: 'opus',
      step_kind: 'kod', workflow: 'akis-w', step: '3', start: at(9, 46), end: at(10, 30), outcome: 'bitti' }),
    J({ note: '2026-11-12-103100-vitrin-kinc.md', project: 'vitrin', title: 'Kod incelemesi', tier: 'inceleme', model: 'haiku',
      step_kind: 'kod-inceleme', workflow: 'akis-w', step: '4', start: at(10, 31), end: at(10, 40), outcome: 'bitti' }),
  ],
  decisions: [{ note: '2026-11-12-akis-w-onay.md', project: 'vitrin', title: 'vitrin — Onay: bildirimler', kind: 'akis-onay',
    risk: 'normal', asked: at(10, 41), gone: at(11, 30) }],
};
