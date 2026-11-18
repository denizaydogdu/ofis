# The office page

> Moved verbatim from the CEO's `CLAUDE.md` on 2026-11-13 (split approved by the owner). In this text "you" is the
> CEO session. A section named in quotes ("see …") may live in another file: the index in
> [`../GELISTIRICI.md`](../GELISTIRICI.md) lists where each one is. The CEO's own rule set is `CLAUDE.md`; when a
> CEO-facing rule changes here, change `CLAUDE.md` too.

## The office page (for the owner)
- Run: `python3 bin/server.py` → prints `Ofis: http://127.0.0.1:8800` (or the next free port up to 8819).
  Python standard library only; binds 127.0.0.1; `Ctrl+C` stops it.
- **The office's name** (plan "Ayarlar sayfası" 1.6): ofis.json `ofis_adi` (default "Ofis"; `/api/state.ofis.adi`),
  set on the Ayarlar tab. The page's `<title>` is "Ofis" until the first state; `renderOfisAdi` (app.js, from
  `renderAll`, only when the name changes) then sets the tab title's base (`baseTitle`, the bell's "(N) " prefix goes
  in front of it), the top bar's text `#brand-ad` (textContent; no logo image) and the scene's lobby sign and the
  hall's idle screen (`Office.setOfisAdi`: the name drawn with fillText on a canvas). The favicon is the neutral
  `web/favicon.svg`. Internal names (`ofis.py`, `ofis-ceo`, `OFIS/`) stay. The greeting card stays "İyi günler.".
- **Language** (English option, phase 1, 2026-11-18): ofis.json `dil` (`tr` default | `en`; `/api/state.ofis.dil`,
  bin/dil.py `kod`), set on Ayarlar › Genel › "Dil / Language" (a select saved at once, `{islem: "genel", dil}`,
  `dilGovdesi` in web/ayarlar.js). The page keys its strings by their Turkish source text: `web/i18n.js` `t(tr, vars)`
  (imported as `T`; returns the input in Turkish, the `web/i18n-en.js` entry in English, `{name}` placeholders filled,
  an entry may be `{one, other}` chosen by `vars.n`), `N_('…')` marks a module constant translated where it is drawn
  (never `T()` at module top level), `yerel()` = `tr-TR` / `en-GB` for dates and numbers (Turkish casing helpers keep
  `tr`). Static HTML carries `data-t="<Turkish>"` (and `data-t-title` / `-placeholder` / `-aria-label`), translated by
  `ceviriUygula` at load and again on a change (`dilDinle` in app.js, from `renderDil` in `renderAll`); the last
  language is kept in localStorage `ofis-dil` (try/catch) so the first paint is right. Owner-name suffixes
  (`sahipEk`, bin/sahip.py `ek_dilde`) give the bare name / "Name's" in English. Server texts the page shows are
  translated at their API field with bin/dil.py `t(text, cfg)` (its own `EN`): the progress line's stop reasons, the
  usage popup (bin/kullanim.py), the limit pill (bin/limitler.py `sayfa`), the Sunucu odası, the Ayarlar errors
  (bin/dil.py `Metin`: the Turkish text with its template and form field — the answer carries `alanlar`, one field per
  error, so web/ayarlar.js `sunucuHatalari` no longer matches the text) and the NPC chat's answers. Codes, protocol
  prefixes, notice titles the page matches, vault notes, CEO notices and `ofis.py` output stay Turkish. A language
  change asks for a fresh CEO session (the `ofis.py ceo-yenile` flag; bin/ceo.py `yenile_iste`): its system text
  (`ceo_system_prompt(name, dil)`) and the reminder line (`(Reply to <Name> in plain English.)`, bin/sahip.py
  `hatirlatma`; `hatirlatmayi_sil` strips both forms) follow `dil`. Phase 2 (not yet): the scene and its cards
  (web/ofis-sahne.js except the NPC chat box, ofis-davranis.js role titles, scene.js, demo.js). test/test_dil.py checks
  that every `T('…')` / `N_('…')` / `data-t` literal has an English entry, no entry is unused and placeholders match
  (the same for bin/dil.py); test/webkopya.py copies the i18n modules next to the web modules the node tests load.
- **Decision bell** (the owner, 2026-11-12): next to the live pill a warning-tone button "N karar bekliyor" with an inline
  SVG bell (the count alone on a bar below 1100 px) while decisions wait for the owner — `state.decisions` minus the cards
  already answered from the page (`answer_sent`, or sent in this tab); `kararBildirimi` in `web/ofis-text.js`. A click
  opens the Komuta masası's Kararlar column with the oldest card's answer box focused. The browser tab title gets the
  "(N) " prefix (`sekmeBasligi`); one gentle pulse when the count rises (`kararArtti`, never on the first render, no
  animation under `prefers-reduced-motion`). Hidden when nothing waits; text only. No desktop notification. Its tooltip
  reads "N karar seni bekliyor — en eskisini aç: …"; the right panel's header repeats the count as "Seni bekleyen: N"
  (`seniBekleyenMetni`, manager cards excluded).
- **The CEO's own question** (owner decision 2026-11-14, `ofis.py sor`, `tur: ceo-sorusu`): a normal card in "CEO soruyor"
  (bell, toast), its options (`state.decisions[].options`) as buttons "A <metin>" (`secenekDugmeleri`; a click sends
  "A) <metin>" through `/api/answer`; Onayla/Reddet hidden when there are options, the free text box stays). In the CEO
  chat the CEO line of that turn gets an amber "cevap bekliyor" badge (`cevapBekleyenRozetleri`: a line that names the
  note wins, else the CEO line closest to `soruldu` within −5/+15 min); a click opens the card like the bell; the badge
  goes once the card is answered.
- **Scene HUD corners** (owner decision 2026-11-13; details in [`sahne.md`](sahne.md)): the view controls "+ − ↺ ↻ ⟲"
  (`#zoom-kontrol`, `--z-hud`) sit at the scene's bottom-left with a 16px gutter (on a phone too, above the sheet); the
  demo caption and the one-time hint ("… Sağ tık ya da ↺ ↻: döndür") right of them, the hint above the caption while one
  shows; the "Mesai dışı" line at the scene's bottom-right, left of the side panel. Keys: + / − / 0 zoom, Q / E turn
  45°, the arrows / W A S D pan; ⟲ also turns the view back to its default angle. The office turns a full 360°.
- **The top bar stays on one line** (owner decision 2026-11-14): no item in it wraps (`white-space: nowrap`); on a wide screen
  its tabs, pills, clock and "CEO ile sohbet" are a little smaller; the tab row may shrink and then scrolls inside its
  own row (never the page); the clock drops its long date below 1700px first.
- **"İş bitti" toasts** (owner decision 2026-11-14): `#is-toastlar`, top-right under the top bar (a phone: full width with the
  16px gutter). `toastOlaylari(prev, cur)` (`web/ofis-text.js`) diffs two `/api/state` snapshots — only changes, so
  nothing that existed before the page loaded pops up — into: a job done ("✓ <proje> işi bitti · <başlık>"), stuck /
  failed to start ("<proje> işi takıldı / başlatılamadı · …"), a new decision ("CEO soruyor · <proje>: <başlık>") and a
  manager's new decision (a `mudur_kararlari` card that turns `cevapladi`). `toastYigini` keeps at most 3, newest first,
  one per event; each closes after ~6 s, with × or Esc (Esc closes all). A click opens the job's card, or for a
  decision its answer card in the Komuta masası. Text only; no sound, no browser notification prompt.
- **"CEO yazdı" toast and unread badge** (owner decision 2026-11-14): a NEW CEO chat line (role `ceo`, from `applyChat`'s
  `fresh`; never the lines that existed at load, never the owner's, notices or relays) that arrives while neither the
  drawer nor the Komuta masası is open, or the tab is hidden, gives a toast "CEO yazdı: <first ~80 chars>" in the same
  stack (`ceoToastlari`; max 3, ~6 s, ×, Esc; a click opens the Komuta masası on the chat tab scrolled to that line,
  `data-anahtar` on the message) and raises a count on the top-bar "CEO ile sohbet" button (`#open-chat-top-sayi`,
  `okunmamisSayi` / `okunmamisMetni`, "9+" above nine); opening the drawer or the window clears it (so does returning
  to the tab while the chat is open). While the tab is hidden the title carries "(N) " with the waiting decisions plus
  the unread lines (`sekmeSayisi` -> `sekmeBasligi`), restored on focus. Text only; no sound, no notification prompt.
- **Usage limit pill** (owner decision 2026-11-14): right of the live pill `#limit-pill` shows the owner's Claude plan usage
  ("Haftalık %54 · 5 saat %62", `limitPill` in `web/limitler.js` from `/api/state.limitler`, bin/limitler.py); amber
  from 80 %, red from 95 % (the higher window decides); the tooltip has the reset times and, when the reading is older
  than 30 minutes, when it was measured; hidden without data or while the server is down; hidden below 720px. Text only.
  **Usage popup** (owner decision 2026-11-16): the pill is a button; a click opens `#limit-pill-detay` (the top bar's warning-chip
  component: `.uyari-kap` / `.uyari-detay`, `UYARI_CIPLERI` toggles it, Esc or a click outside closes it) and asks
  `GET /api/kullanim` (bin/kullanim.py; read-only, the Host check of every GET, computed only on request and cached
  60 s). The popup (`kullanimGorunumu` in `web/limitler.js`, tested in `test/test_kullanim.py`) shows each window
  (Haftalık, 5 saatlik) with its percentage and a bar (same tones as the pill), "çarşamba 22:00'de yenilenir · 2 gün 6 sa
  sonra" and "bugün 15:17'de ölçüldü" (+ the old-reading explanation), then "En çok kullananlar" of the current 5-hour
  window or, on the "Bu hafta" toggle, the current weekly window: rows sorted by tokens ("9,6 mn token · API karşılığı
  ~$4.85", "çıktı 45 bin token"), a Toplam row and the note that the plan's percentage is not exactly proportional to
  tokens. Every usage text is written by the server (budget.token_text / spend_text); the page uses textContent only.
  Rows: "CEO"; an office job by its title and project ("Onboarding metinleri (blog)", else "blog işi" / "Ofis
  işi"); "Müdür ve hakem çağrıları" (unnamed `claude -p` sessions in a registered project's folder and the review
  panel's `ofis-denetci-` copies); "Geliştirici oturumu" (any other non-`claude -p` session in this repository's folder);
  "Jarvis" (sessions in `~/Dev/jarvis`, `kullanim.JARVIS_KLASORU`); everything else in ONE row "Ofis dışı diğer
  oturumlar"; more than 12 rows: the smallest merged into "Daha küçük N kullanım". Forbidden folders
  (`transcript.forbidden_folder`) are never listed, opened or counted. The response has display names and numbers only
  (no paths, folder names, session ids or message text). The demo (`?demo=1`) answers it from `web/demo.js` KULLANIM.
- The top bar has ONE live pill (`canliPill`): "Herkes dinleniyor" / "N ajan çalışıyor"; the running limit only at the
  limit ("3/3 · sınırda, yeni işler sırada", warning tone; above it "5 çalışıyor · sınır 4 aşıldı", never "5/4") and " · onay bekleniyor" while the approval backlog holds kod
  work; its tooltip explains `max_running`. Next to it the clock shows the time and the Turkish date in the office zone
  (`sahne.saat_dilimi`, `tarihMetni`: "23:04 · Çarşamba, 11 Kasım 2026"; a narrow bar shows "Çar 11 Kas"). The pill
  opens "Şu an iş başında": one row per active agent (CEO,
  every running/active job or busy session, the reviewers at work and the hakem from `denetim` — older servers:
  Codex while it reviews) with project, job, title, the worker ("Çalışan": the role only — "Kıdemli", "Codex", "Hakem";
  the model in the cell's tooltip, `calisanRolu` / `calisanIpucu`; the Komuta "Şu an" view likewise), tier, state,
  time since start, spending (dollars · tokens) and open helpers; a row opens the job (or the CEO card). Below those
  rows a **"Çalışanlar"** section lists every employee (see the Çalışanlar list below: grouped, state dot, name column
  `pano_ad`, short state `kisa`; textContent only); with nobody working the popover still opens, says "Şu an iş başında
  kimse yok." and shows the whole list. On a phone it is a full-width sheet (the owner, 2026-11-12: the 3D wall board and the
  phone's floating board are gone; the popover covers them).

- **Çalışanlar list** (shown to the owner as "Çalışanlar"). `/api/state.modeller` (`bin/model_durum.py`) is shown from
  the same rows (`modelSatirlari` in `web/ofis-sahne.js`), grouped (`grup`, `calisanGruplari`): **Kadro** —
  "Stajyer", "Uzman", "Kıdemli", "Genel Müdür" — then **Denetçiler** — "Codex", "DeepSeek · ücretsiz", "GLM · ücretsiz", "Antigravity · ücretsiz",
  "Güvenlik denetçisi" (e.g. "Kıdemli · kota doldu · 16:30'da döner"): in the Komuta masası's Kararlar column **role
  only** (the rows' `rol` / `rol_metin`, the model only in the tooltip `ipucu` "Kıdemli · model: Opus" and in the
  character card; `ad` keeps "Kıdemli (Opus)" for data), and in the live pill's popover with the name column
  `pano_ad` (role + model for a Claude worker: "Uzman · Sonnet", "Güvenlik denetçisi · Sonnet"; Codex / GLM / DeepSeek
  by name), the state dot and the short `kisa` text. "kota" is shown only for `durum: kota`; anything unread is
  "durumu bilinmiyor". (the owner, 2026-11-13: the side panel's own copy of the list, folded on a phone, is gone — the
  popover has the same list.) (the owner, 2026-11-12: the 3D wall board above the meeting room is gone, and with it the plan's
  `pano` node and its camera-fit corners.)

- **Şema** (the org chart; plan "Sonraki iş (9)" step 1, owner decision 2026-11-13): a "Şema" button in the top bar (after the
  decision bell) opens a popover (`#sema`, modal layer, a full-width sheet on a phone; Esc / ✕ / a click outside close
  it) with the tree from `orgSemasi(state, now, actors)` in `web/ofis-sahne.js`: the owner → CEO → Genel Müdür → Yazılım /
  QA / Analist / IT Müdürü, the **İK ve İdari İşler Müdürü** and the **Ar-Ge uzmanı** → their teams (the kadro by
  seniority and the project teams with their sorumlu; the QA odası and the Analist odası with the reviews sitting there
  now; under QA also the **Dış denetçiler** — Codex and the free reviewers `state.modeller` lists, each with its real
  state: the actor drawn now ("hazır", "inceliyor · P", "Evde · …"), else its model row's `kisa`; "evde" while its quota
  is full; the group line counts the ones reviewing — and the **Hakem** ("incelemede çağrılır" until `denetim.hakem`
  draws it); the IT ekibi and the IT güvenlik uzmanı; under İK — the İK staff NPC `sus:ik`, renamed "İK ve İdari İşler
  Müdürü" (owner decision 2026-11-13; no new 3D character) — the Sekreterler and the Güvenlik ekibi, the Muhasebeci, the İdari
  işler sorumlusu, "Ofis hizmetleri" (Çaycı, Yemekhane sorumlusu, Ofis doktoru, Ofis psikoloğu, Masajcı) and "Sosyal
  medya ve tasarım" (`SOSYAL_EKIBI`)). A shift team (IT, Sekreter, guard) lists its three people, the group line names
  the one on shift ("nöbette: 2. sekreter"), and each member its shift ("gündüz vardiyası · 08:00–16:00", "sıradaki
  vardiya 16:00", "nöbet dışı"). The decorative people of the scene (see "Decorative people" in `sahne.md`) appear only
  as one group line on an existing box (node field `ekip`, shown as `.sema-ekip`: "QA ekibi: 3 kişi · görünüm amaçlı",
  "Analist ekibi: 3 kişi · …", "<proje> ekibi: 2 kişi · …" on each sorumlu), never as boxes. Under the Analist Müdürü, beside the
  Analist odası, the **Değerlendirme ekibi** (end-of-day review, `bin/gunsonu.py`): "gün sonu · 20:00–24:00", state
  "çalışıyor" / "son: 13 Kasım" / "kapalı" / "henüz çalışmadı", its two members (Ölçüm uzmanı, Değerlendirme uzmanı;
  "akşam çalışır" while not drawn) opening their card. Every character `kimNerede` knows and every staff actor the scene draws has exactly one
  node (`test_npc.py` checks it over a day). Each node: name, role, a badge "ofiste" / "nöbette" / "evde" / "çıkıyor"
  from `kimNerede` and the shifts, and its state text from the actors drawn now — real data only. The Genel Müdür's card
  lists the İK ve İdari İşler Müdürü and the Ar-Ge uzmanı under "Bağlı müdürler" too. textContent only (`semaDugumu` in `web/app.js`); rebuilt
  only when its content changed; a person's node closes the popover and opens its character card (the actor drawn now,
  else the node's own minimal actor `kart`, e.g. a manager at home); group nodes are not clickable.
- **Komuta masası** (the big CEO window; the owner, 2026-11-11). "CEO ile sohbet" in the top bar opens it; the small chat
  drawer stays and its "Genişlet" button opens the window ("Küçült" goes back; a typed draft moves along); both show
  the same conversation (one chat array from the SSE stream, no polling of its own). About 92vw × 90vh over a dimmed
  office, in the modal layer (`--z-modal`); while it is open the 3D frames stop (`Office.setPaused`) and the scene's
  labels are hidden; Esc / ✕ / a click on the backdrop close it, Tab stays inside it. Three columns: **Şu an** (per
  project the active jobs — title, "Kıdemli (Opus)", plain state, time, $ · tokens, open helpers, workflow step —, a
  running workflow's "2/3 adım", the queue with held / backlog marks, then the reviewers at work and the hakem from
  `denetim`; a click opens the job's detail as a right-hand sheet over the window and adds a chip "İlgili: <title>" to
  the composer: a sent message then ends with the plain line `İlgili: [[<note>]], …` — chips removable, at most
  five); **the chat** (header "CEO şu an: <state> · <current tool in plain words> · <duration>", a folding "Son
  adımlar" list of the CEO's last ~10 tool steps, notices inline as notice cards (see "Notice cards" below), a queued indicator while the CEO is busy, quick questions "Durum
  nedir? / Bugün ne bitti? / Bekleyen kararlar neler?" that only fill the composer, a textarea: Enter sends,
  Shift+Enter a new line, the same POST `/api/chat`); **Kararlar** (the pending decision cards answerable in place —
  the same card component with risk badge, security warning, evidence-first sections and quiz —, the grouped
  Çalışanlar list, today's spending (dollars · tokens) and "Son olanlar"). Below 1100 px the columns become three tabs
  "Sohbet | Şu an | Kararlar"; on a phone it is a full-screen sheet with the same tabs. Pure helpers in
  `web/komuta.js` (`suAnGruplari`, `mesajMetni`, `adimMetni`, `ceoSimdiMetni`, …; tested in `test/test_komuta.py`);
  `?komuta=1` opens it at load (screenshots); the demo fakes the steps. The CEO's steps come from the read-only
  `GET /api/ceo/adimlar` → `{adimlar: [{zaman, arac, hedef, ozet}] newest first, durum, arac_simdi, sure_sn}`
  (`bin/adimlar.py`): the tail of the CEO transcript, cached by inode/size/mtime; only tool names and a safe target
  (a base name; for a shell command only the program — plus one plain subcommand for known programs (`git status`,
  `claude agents`, `python3 ofis.py durum`, `cat Index.md`), never the arguments of echo/grep/curl/ssh/sed/env/…, and
  no word with `:` `@` `%` `=` or that looks like a credential —; a peer session, a skill, a web host —
  never assistant text or thinking, never a file's content or a full path); a step whose path, command or name reaches
  a forbidden project, the credential notes or the private vault folders (ofis.json `guvenlik`, the guard's patterns) is dropped entirely. Same Host check as
  every GET. **Under every CEO reply** (the drawer and the Komuta masası) one small footer line from the read-only
  `GET /api/ceo/turlar` → `{turlar: [{basla, bitis, cevap_zaman, adim, isler: [{note, baslik, unvan, katman, akis,
  adim_sayisi}], usd, token, fiyat_eksik, kapaniyor}] newest first (≤ 30), kapaniyor}` (`bin/adimlar.py`
  `ceo_turlari`, deterministic, no model call): "CEO kendisi baktı · 3 adım · iş açılmadı · $0,03 · 12 bin token", or
  one "İş açıldı: <başlık> → <unvan>" per job an `ofis.py ekle` / `akis` / `baslat` of that turn printed (a button that
  opens the job; a workflow once, "· akış, N adım") and the steps with the cost. Steps follow the same safe-target rules
  (a step reaching a forbidden place is not counted and its result never read); the cost is the turn's calls at list
  price (`bin/pricing.py`); the footer sits under the turn's last reply line (`turAltlari`: its `cevap_zaman`).
  **"Cevap verdi · tur kapanıyor"**: while the CEO's reply is written, no tool call pends and the turn-end record
  (`turn_duration`; not `stop_hook_summary`, after which a blocking Stop hook may continue the turn) is not there yet, `state.ceo.tur_kapaniyor` is true and the CEO header, the
  drawer line, the "Şu an iş başında" row and the CEO's label and card say so instead of "çalışıyor".
  **Across a CEO session rotation** (`gelistirici/sunucu.md`): the chat, the steps and the turns also read the last
  three sessions the CEO was rotated away from (oldest first); the new session's first prompt shows as one system line
  "CEO yeni oturumla devam ediyor · devir notu verildi". `state.ceo.baglam_token` = the context size of the CEO's newest
  model call (None when unknown); `usage_today` / `cost_today` count today's earlier CEO sessions too.
- **The right panel** (owner decision 2026-11-13) keeps only **"CEO soruyor"**: the pending decision cards and (step 4) the
  manager cards of `mudur_kararlari` ("<Unvan> bakıyor" / "Müdür kararı · <Unvan>" badge via `mudurKarti`, the
  manager's answer, only "Cevapla": the owner's answer replaces the manager's; see "Managers answer technical questions" in
  `isler.md`). The approval-backlog and "İletişim uyarısı" warnings are **two chips in the top bar** (`#onay-birikti`,
  `#po-warn`, next to the decision bell): hidden while there is nothing to say; a click opens the same detail text
  under the chip (`#…-detay`; Esc or a click outside closes it). With no question it collapses: `yanPanel` in `web/app.js` sets `html.yan-bos` (`--side-w: 0px`, the panel hidden) and calls
  `office.resize()`; `rightInset` in `web/scene.js` then leaves no room for it and the camera fit uses the full width
  (unless the viewer moved the camera). The first question brings it back. "Çalışanlar" (the live pill's popover),
  "Zamanlanmış işler" and "Son olanlar" (two tabs, below) are no longer in it.
- **NPC chat** (owner decision 2026-11-18, "gerçekten akıllı NPC'ler"; bin/npc_sohbet.py, `gelistirici/sunucu.md`): the
  cards of the Sekreter, the four managers, Muhasebeci, İdari işler, İK, doctor, psychologist, IT sorumlusu, Ar-Ge
  uzmanı, guard and each project sorumlusu (`npcSohbetRolu` in web/ofis-sahne.js; the rest stay plain) end with a
  "Soru sor" section: an input (≤ 500) and "Sor" → `POST /api/npc-sohbet {npc, soru}`; "Düşünüyor…" while it waits,
  then the answer (textContent only) and a "Kullanım: … token · API karşılığı ~$X" line, or the server's Turkish error
  (`npcSohbetSonucu`). The box is one element per opened card (`sohbet` in app.js), kept in place across the card's
  rebuilds so typing and focus survive; it goes when the card closes. Off (`/api/state.npc_sohbet.acik` false, the
  default) the section shows only a hint to turn it on in Ayarlar › Genel; in the demo "Soru sormak demo modunda
  çalışmaz." (`npcSohbetKutusu`).
- **Character cards — one component** (owner decision 2026-11-13, "kartlar okunaklı olsun"). Every character's card (staff,
  managers, IT ekibi, guard, İK, Ar-Ge, doctor, secretary, kadro, jobs, helpers, reviewers, the CEO) is
  `karakterKarti` → `kartDuzeni(k)` (`web/ofis-sahne.js`, pure) → `kartIcerigi` (`web/app.js`, createElement /
  textContent / `linkli` only). `kartDuzeni` groups the card's flat rows into **titled sections**: a row's optional
  `bolum` names its section; a named row followed by unnamed rows opens a section of its own (a list); other named rows
  gather in "Özet" / "Diğer bilgiler". Items: label / value rows (optional `cubuk: {yuzde, ton iyi|uyari|kotu}` → a
  status bar: CPU, memory and disk on the IT card — 70 % warns, 90 % is bad —, the running jobs' budget, the first-pass
  rate), list lines (a list longer than `KART_LISTE_SINIRI` = 6 shows 5 and folds the rest into a
  `details.kart-fazla` "N satır daha"), the guard's groups (`details.karakter-kart-grup`), and **tables** (rows with the
  same `tablo.anahtar` in a row): the shift (`nobetSatirlari`: "Nöbet" section, table Kişi / Durum / Vardiya — the
  current shift's hours or "sıradaki <time>" from `nobetPlani`), the process groups (Grup / Adet / CPU % / Bellek /
  Boşta), the accountant's spending per project and per role (Proje|Unvan / Harcama / İş) and the budget warnings (İş
  / Harcanan / Bütçe / Durum). The hints never change a row's `ad` / `metin`; a table row shows the same facts in
  cells. The card is about 560 px wide (`min(560px, 92vw, 100vw − 32px)`), 14 px text, at most 80vh with its own
  scroll and a sticky title; placed near the click with a 16 px gutter (`KART_KENAR`); on a phone a label sits above
  its value and nothing scrolls sideways (a wide table scrolls inside its own box). Opened details (groups, folded
  lists) stay open across the 1 s rebuild (`details[data-anahtar]`).
  **More useful staff cards** (owner decision 2026-11-18, "daha yetenekli"; no model call, pure helpers in
  `web/ofis-sahne.js`): a manager's card (Yazılım / QA / Analist) lists "Bakılması gereken" — its department's silent
  jobs (`postoffice.silent`) and the ones stuck today, each opens (`sorunluIsler`); the doctor's card adds
  "Kontrol'ü geçmeyen" (open jobs with `kontrol_sonuc` `kaldi`, "düzeltiyor" / "N. deneme", each opens); the İK card ends
  with a "Şu an" section — "Ofiste" N kişi (çalışan · personel), "Nöbette" (each shift team's person on shift), "Otelde"
  — from `kimNerede`, the guard's card's source (`ikVarligi`). A common-area decorative person's card: "Ofisten biri" ·
  "görünüm amaçlı", where it is (the room, or "koridorda yürüyor") and the office's open jobs and waiting questions now.
- Tabs: **Ofis** (3D), **Kararlar**, **İşler** — a three-column board (Sıradakiler / Devam edenler / Bitenler, the 20
  newest finished; a workflow is one card with its steps and progress; each card: project, tier/model, status, budget
  and call bars, queue state, escalation mark; a click opens the job detail) from `state.board` (`state.board_hidden`
  = finished jobs not sent); **Raporlar** — the
  group reports (`GET /api/raporlar` → `{raporlar: [{grup, baslik, proje, tur, surum, bitis, yazildi, toplam_usd,
  is_sayisi, sonuclar, dogrulanmis_is_basina_usd (= toplam_usd / dogrulanan), dogrulanan, ilk_tur_gecen,
  ilk_tur_olculen, yeniden_is, acik, fiyat_bilinmiyor (a Codex review: the total leaves it out), toplam_token,
  dogrulanmis_is_basina_token (= toplam_token / dogrulanan), token_eksik}]}`; the card shows both with tokens),
  newest first; `GET /api/rapor?grup=G` → the same + `metin`, the markdown body shown as text; `grup` must match the
  `--grup` rule, else 400; only plain files directly in `OFIS/Raporlar`); **Kalite** — the scorecard numbers
  (`GET /api/kalite` → `{satirlar: [per proje × katman × model], modeller: [per model], toplam, is_sayisi}`, computed
  by `karne.quality()` from the Kayitlar rows and correction logs, the same code as `Ozet.md`; the tiles and table
  cells show every dollar metric with its tokens — `kaliteKutulari`, `qualityCells`, `paraTokenMetni`,
  `tokenToplamMetni` in `web/ofis-text.js`; phase 8 adds
  `model_secimi: {eslesme: [{proje, katman, model, effort, kaynak}], pilotlar: [{…, eklenen, biten, toplam}],
  oneriler: [open model cards]}` from `model_secimi.page()`, shown under "Kadro ve görev dağılımı"; the per-model table
  is "Unvana göre", the column "Çalışan"). The vault notes the server writes use the same words: Karne `Kayitlar` /
  `Ozet` show the column "Çalışan" with cells like "Kıdemli (opus)" (`karne.worker`; older notes with a "Model" header
  or a plain "opus" cell still parse: `karne.model_of`), the group report's "Katman / çalışan", `Denetciler.md`'s
  "Çalışan", the model-selection cards "Kadro önerisi" / "Kadro denemesi sonucu" ("Stajyer (Haiku) yerine Uzman
  (Sonnet)"; frontmatter keeps the ids) and their CEO notices ("kadro önerisi:", "kadro denemesi bitti:"). All three are
  read-only GETs; the page has no POST besides chat, answers, announcements (`/api/duyuru`), Yakala and the
  Ayarlar tab (`/api/ayarlar`).
  **Zamanlanmış** (owner decision 2026-11-13, after Kalite; a count badge with the number of schedules) — a table Ad (the
  schedule's note `OFIS/Zamanlanmis/<ad>` as an Obsidian link, with its title) / Proje / Ne zaman / Sonraki / Durum
  ("etkin" or "duraklatıldı" with the reason) / Son koşu (the last run's result and time, linking its job note), and
  under it one box per schedule with its last runs ("11.11 09:00 · <job note> · bitti", and "→ <job>" when a run was
  escalated), every job a bare-name Obsidian link (`notLinki`, folder hint `Isler`). Data: `state.schedules`
  (`bin/zamanla.py summaries`), which also carries `kosular: [{slot, is, sonuc, son_is}]`, the newest `PAGE_RUNS` = 5
  runs; an older server's `son_is` / `son_sonuc` still give one run (`zamanlanmisSatirlari` in `web/ofis-text.js`).
  **Son olanlar** — the page's event list (the same `feed` the Komuta masası shows in short) as a timeline, newest
  first: a server notice is the chat's own notice card (`noticeCard`: badge, title, facts, actions, Ayrıntı), every
  other event (a job started / finished / stuck, a question asked / answered, a CEO or project message) a card of the
  same shape with its badge (`olayRozeti`: İş başladı ▶, İş bitti ✓, Takıldı !, Soru ?, Cevaplandı ✓, CEO ✉, Proje
  mesajı ✉, Sistem i) and its time; a click opens its detail. It lists what happened while the page is open (no server
  history). Both tabs are full-panel views like Kalite (the 3D frames stop under them), also on a phone (the tab bar
  scrolls sideways); `?sekme=zamanlanmis|olaylar` opens one at load.
- **Ayarlar** (plan "Ayarlar sayfası" 1.5; the last tab, `?sekme=ayarlar` opens it at load): the office's settings,
  edited by the owner — the CEO no longer edits projects in `ofis.json` by hand. `GET /api/ayarlar` (bin/ayarlar.py
  `ozet`: `ofis_adi`, `sahip_adi`, `projeler[]` with `path`, `tam_yol`, `description`, `notes`, `hassas_yollar`, `sorumlu`,
  `sistem`, `yerlesik`, `acik_is_sayisi`, `guven` (Claude Code's folder trust: true / false / null) and `ipucu`
  (`cd <folder> && claude` when untrusted), `kurallar`) is read **only when the tab opens and after a save** — never
  from `renderAll`, so a state push never wipes a form being typed; a second click on the open tab does not reload it.
  Sections: **Genel** (the language select "Dil / Language" — see Language above —; the NPC chat switch — "NPC sohbeti" checkbox + "Saatte en çok N soru", its own Kaydet →
  `{islem: "genel", npc_sohbet: {acik, saatlik_sinir}}`, `npcSohbetGovdesi` in web/ayarlar.js; bin/npc_sohbet.py
  `dogrula` checks it again —; Ofis adı and Senin adın — the owner's name, ofis.json `sahip_adi`, plan "2. Aşama" — + one Kaydet → `{islem: "genel", ofis_adi, sahip_adi}`; `genelGovdesi` / `sahipAdiHatasi` in web/ayarlar.js, an error under its own field; `/api/state.sahip` names the owner in every page text through web/ofis-davranis.js `sahipAyarla`, and `<span class="sahip-in">` in index.html gets the genitive form) and **Projeler**: one card per project (colour
  dot = `projeRengi`, name, "Yerleşik" badge for `arge`, trust badge, description, folder (the resolved path in the
  tooltip), "N açık iş", for an untrusted folder the command with a Kopyala button, Düzenle and — not for `arge` — Sil)
  and "Proje ekle". The form (the list is hidden while it is open; focus goes to the first field and back to the
  button that opened it): Proje adı (disabled when editing: no rename), Klasör yolu, Açıklama, Proje kuralları
  (`notes`), and a collapsible **Gelişmiş** (open by itself when it holds something): Hassas yollar, Durup sorması
  gerekenler / Asla yapmaması gerekenler / Teslim biçimi (`sorumlu`), Domainler (`sistem.domainler`), one item per
  line. The pure helpers are `web/ayarlar.js` (tested in `test/test_ayarlar_web.py`): `istemciHatalari` mirrors the
  server's rules (the server checks again, also that the folder exists), `eklemeGovdesi` drops empty optional fields,
  `guncellemeGovdesi` sends only the changed fields (an emptied one as "" / [] = removed; an untouched `sorumlu`
  section keeps its stored value, `sistem` keeps `eposta_domaini` and `cloudflare`, which the form does not show; no
  change = no request), `sunucuHatalari` / `hataAlani` put a refusal's `hatalar` under their fields (the rest in a
  list under the form; the first bad field gets the focus and `aria-invalid`). Sil asks first (`confirm`,
  `silmeSorusu`: the vault notes and the folder stay); a refused delete (409: an open job, a schedule, a workflow,
  the built-in `arge`) shows the server's reason in the status line. The server checks a folder by file identity, not
  by its spelling (macOS folders are case-insensitive): not the office's folder, the vault, or another project's same
  folder in any case, not inside or above the first two, not `~/Library` or a hidden folder right under home (`~/.ssh`,
  `~/.claude`, …), and stores it in the file system's own case. A changed folder is refused (409) while the project
  has an open job or workflow (schedules do not block), and turns the project's free outside reviewers off
  (`ucretsiz_denetci_kaldirildi: true` in the answer; the CEO's notice says so). Saving or deleting a project never
  overwrites an unsaved office name (`ofisAdiKirli`). Leaving the tab (another tab, Esc, a click
  outside) with unsaved edits asks first; yes drops them. Forms are `novalidate` with `preventDefault` + the page's
  `post()` (CSP `form-action 'none'`); a refusal (also 403, which `sayfa-anahtari.js` retries once with a fresh
  token) keeps everything typed. The demo answers the GET from its own projects (`demoAyarlar`) and saves nothing
  ("Demo modunda kaydedilmez."). A saved project reaches `/api/state.projects` with the next state push, so the scene
  grows (or loses) a team room by itself; the server tells the CEO with one notice (see `CLAUDE.md`).
- Living office data in `/api/state` (display only; the scene uses it in later steps):
  `sessions[]` also carry their unfinished job (`job_status`, `model`, `tier`, `note`, `step_kind`; `status` stays the
  session's own busy/idle/waiting) and `alt_ajanlar: [{id, model, gorev, son_yazma, bitti}]` (open subagents, plus
  those finished in the last minute, at most 8; `bin/alt_ajan.py`); `ceo.alt_ajanlar` likewise; `tasks[]` carry
  `inceleme_yurutucu` from the server record. `modeller: [{model, unvan, calisan, durum, donus, son_hata}]` for haiku,
  sonnet, opus, fable, codex (Stajyer, Uzman, Kıdemli, Genel Müdür, Dış denetçi): `durum` is `kota` only on a concrete
  usage-limit message (Claude: an office transcript's usage-limit record, `donus` = its reset time in the office zone;
  Codex: its newest run's strict `codex_kota` flag — codex itself exited with a usage-limit error — and `donus` from
  its "try again at …" time, `codex_donus`; once that reset time has passed Codex is `hazir` again; `codex_zamani` is stamped only when codex really ran), else `hata`,
  `calisiyor`, `hazir` or `bilinmiyor` (`bin/model_durum.py`). `sahne: {ogle, saat_dilimi}` from ofis.json
  `ofis_sahnesi` (default `12:00-13:00`, `Europe/Istanbul`; the page decides lunch in that zone). `sistem:
  {seviye, oneri, domain_sorunu}` or null (the Sunucu odası's lights, `bin/sistem.py ozet` from its cache).

## The job's progress line ("yol çizgisi", owner decision 2026-11-14)
- **What.** Every job shows its stage as a line of steps: CEO aldı → `<unvan>` aldı → `<oda>` çalışıyor →
  Kontrol → rapor geldi → CEO'ya ulaştı → sana iletildi. Done steps are green with their HH:MM; the current one is
  highlighted (amber with "senin cevabını bekliyor" / "izin bekliyor"); a stopped one red with its reason word
  (takıldı, iptal, başlatılamadı, bütçe doldu, çağrı sınırı, üst katmana taşındı); "Kontrol yok" grey; later steps
  faint. An escalated job's full line links "→ yeni iş" (`escalated_to`). Where: the job detail (full, under the
  facts), each İşler card and under each "İş açıldı: …" line of the CEO chat (compact: dots + the current step's
  label; the chat's lines are refreshed in place on every state push, `yollariYenile`), and under the İş cell of
  each open job's row in the live pill's "Şu an iş başında" popover (compact; the row's `yolNot` from
  `calisanlarTablosu`, drawn and refreshed by `calisanYolu` in `web/app.js` without rebuilding the row; no line on the
  CEO's, a reviewer's or a job-less session's row; the row's click still opens the job). The compact form's
  `aria-label` names the current step (`yolEtiketi`). `web/is-akisi.js` (`yolAdimlari`, `yolOzeti`, `yolEtiketi`
  pure; `yolCizgisi` DOM, textContent only); CSS block "İş yolu çizgisi" at the end of
  `web/style.css`; wraps on a phone, the compact form clips inside its box.
- **Data: real records only** (`bin/state.py` `is_yolu`, `yol_ekle`): `/api/state` tasks (also `board`, projects'
  tasks) carry `yol: [{adim, durum, zaman, not}]`, adim in `alindi, verildi, calisiyor, kontrol, rapor, ceo,
  iletildi`, durum `tamam | simdi | bekliyor | hata | atlandi | yok | bilinmiyor`, `not` = the reason word or
  `cevap` / `izin`. alindi = `olusturuldu`; verildi = `baslangic` (the key is historic: it is the step "the worker took the job"; the server has no
  record of a Genel Müdür hand-over, the scene's hand-over chain is visual only, so the line never shows one). The page
  names the worker and the place itself (`web/is-akisi.js`): `<unvan> aldı` = the job's model/tier and uzmanlık
  (`rolMetni`: "Kıdemli Backend", "Uzman Güvenlik"; an arge job "Ar-Ge uzmanı"; queued: "… alacak"), `<oda> çalışıyor`
  = "Ar-Ge odasında" for the arge project, else "`<proje>` masasında"; çalışıyor ends at the last inbox message's arrival
  (its id's ns stamp); Kontrol = `kontrolde` / `kontrol_sonuc` (atlandi without the server's `kontrol_ozet` or with
  `kontrol_sonuc` yok); rapor = `bitis` of a final status; CEO'ya ulaştı = the CEO channel's sent log
  (`durum/ceo-sent.txt`, each line now `<key>\t<local time>`, `Channel.sent_times()`): the earliest delivery at or
  after `bitis` of the job's outcome notice — `kontrol-|yukseltme-|butce-|cagri-|baslatma-<stem>…`, `gelen-<its last
  message id>` or its group's `rapor-<grup>-v<n>`; sana iletildi = the CEO's reply (`cevap_zaman`, `bin/adimlar.py`
  turns of the current and the last rotated transcripts' tails) in the first turn that began within 30 s before
  the delivery or later and did not end before it. Tied by time only: a delivery older than the turns read, or a
  sent-log line written before times were kept, gives `bilinmiyor` — never an invented step.

## Notice cards and Obsidian links (the owner, 2026-11-13)
- **Notice cards.** Every `[Ofis · sistem]` notice shows in the chat (drawer and Komuta masası alike) as a compact card
  built by `bildirimKarti(text)` in `web/ofis-text.js`: a badge with a kind icon (sabah özeti, Ar-Ge raporu, soru, iş
  bitti, akış adımı, takıldı, durduruldu, yükseltme, onay bekliyor, akış durdu, grup bitti, kota, izin bekliyor,
  ilerlemiyor, bekliyor, başlatılamadı, onay birikti, zamanlama, kadro önerisi / denemesi, hatırlatma, sunucu odası,
  duyuru), ONE plain Turkish title line, the key facts as a two-column table parsed from the server's own wording
  (e.g. sabah özeti → Dün biten / Kontrol geçen / Harcama / Bekleyen karar / Takılan / Sırada / Sunucu odası; Ar-Ge →
  Rapor notu / Kontrol / Kart sayısı; soru → Proje / İş / Soru; gün sonu → İşler / Kötü giden / Atlanan gün; gün sonu
  önerileri → Not / Kod düzeltmesi / Kural önerisi; a `GunSonu-` note opens from `OFIS/GunSonu`), the actions where they exist (Cevapla, İşi aç, Notu
  aç) and the notice text only behind a collapsed "Ayrıntı" toggle. The parts written for you (sentences or clauses
  with "<sahip>'e …", `ofis.py …` commands, log.md and correction-check instructions) are never shown to the owner — you
  still get the full text. An unknown kind falls back to its first sentence + Ayrıntı. Your plain reply under it is
  shown as it is. A new notice wording needs its pattern in `KART_KALIPLARI` (tests: `test/test_bildirim.py`).
- **Obsidian links.** Keep writing bare `[[note]]` links: every `[[note]]` the page shows (your replies, notice cards,
  decision cards, job detail, reports, staff cards) and every "Notu aç" button opens the note in the Obsidian app
  (`obsidian://open?vault=<vault folder name>&file=<path under OFIS without .md>`). The page asks the read-only
  `GET /api/not-yolu?ad=<name>[&tercih=<folder>]` (`bin/notyolu.py`: plain files under OFIS/ only, no symlink, no
  hidden folder, nothing that reaches a forbidden project or a private / credential path; else 404); a bare name in several folders →
  the folder the context hints (the morning summary → `Ozetler`, a group report → `Raporlar`, a decision →
  `Kararlar`, `ArGe-…` → `ArGe`), else the newest. The href is set only through `obsidianHref` (the `obsidian://open`
  scheme, never `javascript:`), the link text is textContent.
- **Değerlendirme ekibi card** ("gün sonu"; `degerlendirmeKarti` in `web/ofis-sahne.js`, from `/api/state.gun_sonu` =
  `gunsonu.ozet_durumu`: `{acik, pencere, aktif_dk, son: {gun, not, olcum_zamani, olcum_saati, olcum_iso, sayilar,
  kotu, is, rapor, oneri}, atlananlar}`, no extra endpoint): Şu an, Pencere ("her akşam 20:00–24:00 (bir kez)" or
  "kapalı"), Son değerlendirme (day · time), İşler (bitti / takıldı / Kontrol ilk denemede), Harcama, Kötü giden, Not
  (`GunSonu-…`, in Obsidian), Değerlendirme işi (sırada / çalışıyor / önerileri eklendi (N) / tamamlanamadı) with
  "Değerlendirme işini aç", Atlanan günler. Each task in `/api/state.tasks` carries `gun_sonu` (the record's day, else
  "").
