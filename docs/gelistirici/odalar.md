# Announcements, Sunucu odası, Ar-Ge, project sorumlusu notes, morning summary

> Moved verbatim from the CEO's `CLAUDE.md` on 2026-11-13 (split approved by the owner). In this text "you" is the
> CEO session. A section named in quotes ("see …") may live in another file: the index in
> [`../GELISTIRICI.md`](../GELISTIRICI.md) lists where each one is. The CEO's own rule set is `CLAUDE.md`; when a
> CEO-facing rule changes here, change `CLAUDE.md` too.

## Announcements (duyurular)
The owner's announcement to every office session (`bin/duyuru.py`; owner decision 2026-11-12). The owner sends it from the page (the
Komuta masası's "Duyuru yap": the text, at most 2000 characters, and a duration — yalnız şimdi / bugün / bu hafta / a
date — `POST /api/duyuru` with the same Host / Origin / JSON / 16 KB / token checks as every POST); the CEO runs
`ofis.py duyuru` only on his explicit word. Project sessions are denied `ofis.py duyuru` (`DENIED_COMMANDS`).
- The server's trusted record is `durum/duyurular/<id>.json` (text, duration and end, source, the delivery state per
  session); the guard and the deny rules keep it out of reach (an unexpired record speaks as the owner in every contract).
  Never edit it. The vault note `OFIS/Duyurular/YYYY-MM-DD-<kısa>.md` (server-generated, display only) has the text
  (quoted as data), the duration and who it reached when.
- Delivery: one outbox message `[Ofis · Sahibin duyurusu] <id>` + the quoted text per session of every job at work
  (`calisiyor` / `baslatiliyor`), delivered like an answer (only when the session is idle, stop + resume, never into a
  running turn). A job that is not at work at delivery time (`kontrolde`: the session must not touch the folder during
  the Kontrol; `karar-bekliyor` / `incelemede`: it would run outside the limits; finished) never gets it: `iletilemedi`
  ("oturum o an çalışmıyordu"); `bitir` / `iptal` mark it so too. The same text again within 60 s is refused. The state per session is `bekliyor` / `iletildi` /
  `iletilemedi`. Once none waits you get ONE notice "<sahip>'in duyurusu N oturuma iletildi …": tell the owner in one line.
- The text is always data: every line is quoted with `> ` and a leading `[` is escaped (`\[`), so it can never forge a
  `[Sahip · …]` / `[Ofis · …]` line or a callout.
- Duration: `simdi` reaches only the sessions running now; `bugun` / `hafta` / a date also put it, until its end
  (23:59:59 of that day; `hafta` = Sunday), into the **"Geçerli duyurular"** section of `launch.contract` at every
  start and every resume of a project session (the newest five); after its end the section drops it by itself.
- The page: `/api/state.duyuru` = the latest announcement's `{id, ilk_satir, zaman (first delivery; creation when no
  session was running), sayi, hedef, alanlar}`; the Konferans salonu shows it (see the office page).

## Sunucu odası (the computer and the projects' domains)
Plan "Sonraki iş (5)", owner decision 2026-11-12. `bin/sistem.py`, read-only.
- **The computer** (`GET /api/sistem`, same Host check as every GET, no POST): the standard library and macOS's own
  commands only — `sysctl` (cores, load, memory size, boot time, the kernel's memory pressure level), `vm_stat`,
  `memory_pressure` when present, `ps -axo pid,pcpu,rss,comm`, `df -k /` (fullness = size − available: APFS),
  `pmset -g batt`; Docker only when `docker` is on PATH and its daemon answers `docker stats --no-stream --format
  '{{.CPUPerc}}\t{{.MemUsage}}'` (numbers only). Argument lists, no shell, a timeout of at most 3 s each; one sample is
  cached 20 s. The server samples every 20 s only while the page is watched (the sustained-CPU rule needs regular
  samples). Shown: CPU load and cores, memory used and pressure, disk fullness, battery, uptime, Docker's containers
  (count, %CPU, memory) and per **group** the process count, %CPU and memory: Java, Node (also npm/npx), Python, Docker
  (Docker Desktop, Colima/Lima, OrbStack and — only beside one of them — their virtual machine / qemu), Tarayıcılar (Chrome, Brave, Safari, Firefox, Edge
  and their helpers), Claude oturumları (the `claude` CLI only, with how many are idle; not the desktop app), Codex/OpenCode, Ofis sunucusu (this server's own
  pid), Diğer. The level `seviye` (yesil / sari / kirmizi) follows the 1-minute load per core (0.7 / 1.0) and the memory
  pressure (uyari → at least sarı, kritik → kırmızı).
- **Privacy (hard rule)**: grouping only by the executable's base name from `comm`; the page gets group totals only —
  never a command line, a path, a project, container or user name, never the base names inside a group, and nothing of
  that is stored. A process whose `comm` reaches a forbidden project, the credential notes or the private folders is not counted at all
  (`adimlar.forbidden`, the guard's patterns), and `sistem.temizle` drops every string of the output that matches them
  as the last filter.
- **Suggestions** (rule-based text, `oneriler`): Docker holding ≥ 1 GB while its containers are idle; ≥ 6 idle Claude
  processes; disk over 90 %; memory pressure (or under 10 % free); a group over 150 % CPU in the last 3 samples; the
  browsers over 100 % while the office page is open ("?hafif=1"). **The office never closes, kills or deletes
  anything**; each suggestion says the decision is the owner's. You relay one only when the owner asks.
- **Domains**: `ofis.json` → `projects.<P>.sistem: {domainler: ["site.com", …], eposta_domaini: "site.com",
  cloudflare: true|false}`, optional; nobody invents one. Until a list exists the IT ekibi's card says "Domain
  listesi henüz yok — Ar-Ge ilk çalışmasında soracak". The owner enters the domains himself on the page's **Ayarlar** tab
  (a project's "Gelişmiş" → Domainler, host names only; bin/ayarlar.py validates them and keeps `eposta_domaini` /
  `cloudflare`; see `sayfa.md` "Ayarlar"); the CEO no longer writes this key by hand — when the owner names domains in
  the chat, tell him to add them there. The server's domain loop (`DomainKontrol`, its
  own thread, reads `ofis.json` again every pass) checks every registered domain every 6 hours and contacts nothing
  else: HTTPS (a HEAD request with a 5 s timeout: the status code; days until the TLS certificate expires, `ssl`), DNS
  (the A records; whether they are in Cloudflare's published IPv4 ranges — a static list in the code with its source
  URL), MX (`dig` when installed, else "bilinmiyor"). No API keys. The result is cached in `durum/sistem/domainler.json` (a trusted record since
  2026-11-12: only the server writes it; the guard and the deny rules block hand edits).
- **Notice**: a site that does not open (no answer, a certificate that does not verify, a 5xx), a certificate with
  fewer than 14 days left, or a DNS change (the new A records share no address with the previous ones; not counted:
  a failed lookup, a pool that keeps some address, Cloudflare moving between its own addresses)
  sends you one notice "Sunucu odası (<proje>): <domain> açılmıyor / sertifikası N gün içinde bitiyor / DNS değişti: …"
  — once per problem until it changes (a site that opens again and fails later is a new problem; a notice that could
  not be queued is tried again on the next pass). Tell the owner in one
  line; the office changes nothing.
- **Scene**: the fixed **Sunucu odası** facility (wing column 0, under İdari işler): two groups of three server
  cabinets with status lights in the load's colour (green / yellow / red, grey before the first sample) and a red
  beacon on a cabinet while a domain problem is open (`/api/state.sistem` = `{seviye, oneri, domain_sorunu}` from the
  cache, never a command; `Office.setSistem` changes two materials in place, nothing per frame).
- **The IT ekibi** (owner decision 2026-11-12; `IT_EKIBI`, `itVardiyasi`, `itEkibi` in `web/ofis-davranis.js` — the shared
  shift helper of the three shift teams, see "Nöbet düzeni"): three NPCs —
  the **IT sorumlusu** (`sus:sunucu`, the team lead's title) and two **IT uzmanı** (`sus:sunucu:1`, `sus:sunucu:2`;
  the card calls them "1. / 2. IT uzmanı"). **Shifts** in the office zone: gece 00:00–08:00, gündüz 08:00–16:00, akşam
  16:00–24:00. **Rotation**: on office day D (days since 1970-01-01 in the office zone) shift k (0 gece, 1 gündüz,
  2 akşam) is worked by person (k + D) mod 3 — the night moves to another person every day (each takes it once in
  three days), two consecutive shifts are never the same person, everyone works one 8-hour shift a day.
  - **Exactly one on-shift person (nöbetçi)** at any time holds the server room: its desk (`sunucu-masa`) or the
    cabinets (`sunucu-kabin`); no lunch, no breaks away; a seeded round to the cabinets in about one 10-minute slot of
    three (90 s, "kabinleri kontrol ediyor"). Label: "nöbette" on the night shift, else "masasında · nöbetçi".
  - **Duty** "uyarı var" (a suggestion or a domain problem open): only the nöbetçi works at the cabinets ("nöbette ·
    uyarı var · kabinlerde", typing, facing them), on every shift and in hafif. During office hours the colleague in the
    office (below) helps at the second cabinet spot (`sunucu-kabin-2`, "uyarı var · kabinlerde yardım ediyor") while it
    lasts.
  - **Off shift**: the person whose day shift ended at 16:00 stays as a colleague while its own office hours last
    (`personelSaati`: seeded within ±20 min of the end): its desk `sunucu-masa-2`, lunch, ordinary staff breaks
    (`personelRotasi`). The night person goes to the **Otel** at 08:00, the evening person at 24:00; the others stay at
    the Otel (see "The Otel" in [`sahne.md`](sahne.md); before 2026-11-14 they went "home"); the walk crosses the street on its crosswalk — "The street" there). Without
    office hours (`mesai: ""`, the demo) the person of the previous shift stays (never after a night shift).
  - **Shift changes** at 08:00 / 16:00 / 24:00: the incoming person walks in from the Otel to the desk (one first seen
    on this page load comes out of the lift); the outgoing one ("nöbeti devretti · otele gidiyor") — and a colleague
    whose day is over ("otele gidiyor") — walks to its own Otel room (`cikis_bitis` / `otel_varis`, carried tick to
    tick) and is hidden inside on arrival.
  - **hafif**: only the nöbetçi, standing still at the desk (or the cabinet on duty).
  - **Card "IT ekibi"** (`sistemKarti` → `itEkibiSatirlari`, textContent; from the clock, GET `/api/sistem` every 30 s
    while open): who is on shift ("Nöbette": name, shift and its hours), "Nöbet bitişi", "Sonraki değişim" (time and who
    comes), each member's state (nöbette / ofiste / otelde), then the status, the groups, the suggestions and the domains.
  - The room has the plan spots `sunucu-masa`, `sunucu-masa-2` (a second desk), `sunucu-kabin`, `sunucu-kabin-2`; no two
    actors share one (test/test_npc.py `ItTeamTest` simulates whole days).

## Ar-Ge odası (research)
Plan "Sonraki iş (6)", owner decision 2026-11-12; `bin/arge.py`. The office's research desk: the `arge` project in `ofis.json`
(folder `~/Dev/ofis-arge`, a plain folder with a README — not a git repository: a job there has no base commit and no
git state, which is fine for read-only research; never in `ucretsiz_denetci_projeler`). Its `notes` are its rules:
read-only research; only the office projects' names and descriptions may leave the machine, never code; a source link
for every claim, inventing is forbidden; every model suggestion states its license.
- **The free daily check** (server code, no model call; the Ar-Ge thread): once per office day — the first pass after
  midnight, so also once at a server start when today's is not done — it runs, one after another with a 10 s timeout
  each, `opencode models`, `claude --version`, `codex --version`, `opencode --version` (ofis.json `codex_bin` /
  `opencode_bin`, else PATH; argument lists, no shell; never while a Kontrol or a review runs; the network only through
  those CLIs' own commands). A missing or failing tool is "bilinmiyor"; an unknown model list is never read as "every
  model removed". Results (free data, not a trusted record): `durum/arge/gunler/YYYY-MM-DD.json` (the day's lists,
  versions and diff; 90 days of history) and `durum/arge/son_fark.json` (the last diff: new / removed / renamed free
  models — `-free` / `:free` names and opencode's own unversioned ones like `big-pickle` — against the last earlier day
  whose list was known, and the version changes). No notice of its own: the diff goes into the day's Ar-Ge note and
  onto the Ar-Ge uzmanı's card.
- **The daily research job** is a schedule that waits for the owner's yes: the brief is ready in
  `durum/taslak/arge-gunluk.json` (ad `arge-gunluk`, tier `genel`, $1.5, every day 09:00, no Kontrol). Run `zamanla
  ekle --brief-dosya durum/taslak/arge-gunluk.json` **only after the owner's explicit yes on that exact schedule**. The
  first run's extra tasks are a separate one-off job (`durum/taslak/arge-ilk.json`: a local review model for a 16 GB
  M1 Pro, the domain-list question to the owner as a `bildir soru`, job definitions for "Sürüm Notu Yazarı" and "Risk
  Kaydı"); add it with `ekle --brief-dosya durum/taslak/arge-ilk.json` only on his word too.
- **The report**: a `bitti` from an arge job (its server record) is only *kept* by the post office: the job's pending
  report `durum/arge/raporlar/<iş>.json` (id = the job + a hash of the text; a newer report of the job replaces it). If
  it cannot be saved, the inbox file stays and is retried like any report; it is deleted only after the record is safe.
  The report is kept inside the post office's apply step, under the job lock and after its status check, BEFORE the
  job's status changes (2026-11-13): while it cannot be saved the job stays running (no Kontrol, no notice); the writer
  never sees the job bitti with an older report on record; a report the job no longer accepts (its Kontrol finished
  meanwhile) is rejected and never replaces the pending one.
  The Ar-Ge thread's writer (every 15 s) is the ONE place that writes: for each pending report whose job is `bitti` and
  whose server record says `kontrol_sonuc` yok or gecti (no Kontrol, or it passed; a `bitir` by hand never publishes it) `yaz_ve_bildir` writes `OFIS/ArGe/ArGe-YYYY-MM-DD.md` (every arge report of the office
  day in one note, quoted as data with no callouts, plus the day's free check), then the cards, then ONE notice "Ar-Ge
  raporu geldi … Obsidian notu: [[ArGe-YYYY-MM-DD]] …" (key `arge-<id>`) — **tell the owner in one line** what the research
  found. The done set `durum/arge/yazilanlar.json` keeps it to once: never written twice, never told twice (a queue
  failure or a restart between writing and telling only tells it later). Once written, its pending record is removed. A report whose Kontrol failed stays
  pending until the job's next report replaces it. An arge job's own done notice is withheld (the post office's, and the Kontrol
  worker's on a pass): the writer's notice is the one, and it says "Kontrol geçti (deneme N …)" when it did. The Kontrol
  worker withholds its notice only while an Ar-Ge record (pending or written) exists for the job; without one (its
  save kept failing and the report was rejected — the page shows it) the normal done notice comes. Stuck, stopped and
  escalation notices of arge jobs come as usual. (The "ArGe-" prefix keeps
  the name apart from the morning summary's `OFIS/Ozetler/YYYY-MM-DD.md`, so the bare link is unique.) Never edit the
  note.
- **Reviewer suggestions**: a report line `ÖNERİ-DENETÇİ: <model> | <lisans> | <neden>` (the brief asks for it; parsed
  tolerantly) becomes a pending card `Kararlar/YYYY-MM-DD-arge-denetci-onerisi.md` (`tur: denetci-onerisi`, "Denetçi
  olarak denensin mi?") — only with a model name and a license, at most three per report, never a second card for a
  model whose card is pending; no line, no card. The notice names the cards: tell the owner a card waits. His answer goes
  through `cevapla` word for word (no session waits; it returns `onay`). A yes changes nothing by itself: adding the
  model to the review panel (`denetciler`) and its trial are a separate change the owner approves — the CEO never edits
  `ofis.json` for it.
- **The domain question**: the first run asks the owner the projects' domains with a question card; he enters them on
  the Ayarlar tab as described in "Sunucu odası".
- **Scene**: the fixed **Ar-Ge odası** (wing column 1, under the studio): a whiteboard, a bookcase, two desks. The
  **Ar-Ge uzmanı** (`sus:arge`, staff with office hours) works at its desk while an arge job is open ("araştırıyor ·
  <title>"; waiting for the owner's answer: "<sahip>'in cevabını bekliyor"), also outside its hours; the arge jobs get no robot
  and no team bay of their own (the arge workspace has no project sorumlusu either). Its card ("araştırma", GET
  `/api/arge`: `arge.sayfa`) shows the running job, the last report's summary lines, its suggestions with their cards,
  the note's name (`ArGe-YYYY-MM-DD`, in Obsidian), the free-model diff and the versions; "Raporu aç" opens the report's job, "Kartı aç" a suggestion's card.
- Its vault family `OFIS/ArGe` needs one `index.md` row: add it once.

### Yakala (owner decision 2026-11-14; bin/yakala.py)
The owner drops a link or a small file; it becomes ONE Ar-Ge research job. Full behaviour in the module doc of
`bin/yakala.py`; in short:
- **Switch** ofis.json `yakala: {acik, butce_usd (0.5), saatlik_sinir (10), dosya_mb (2)}`; missing / not `acik` =
  nothing new is accepted (items at work still finish).
- **Sources**: the page's "Yakala" box in the Komuta masası (under "Duyuru yap"; shown only while on; POST
  `/api/yakala` `{url, not}` or `{dosya_adi, dosya (base64), not}`) and the CEO's `ofis.py yakala --url … [--not …]`
  (denied for project sessions). `/api/state.yakala` = `yakala.sayfa`: `{acik, dosya_mb, saatlik_sinir, uzantilar,
  son}` (the last 5 items, no path).
- **Validation**: http/https only, URL character set only, no user:password@, no IP literal in any spelling, no
  localhost / single-label / private-suffix host (no DNS lookup: a public name resolving to a private address is not
  caught); note ≤ 300 characters, one line; file .txt/.md/.markdown/.pdf by extension AND content (PDF magic, strict
  UTF-8 text without NUL / control characters), ≤ `dosya_mb`. Rolling hourly limit over page + CLI (429); the same URL
  within 24 h returns the existing item (`tekrar`).
- **Storage** `durum/yakala/<id>/kayit.json` (+ `ek.<ext>`, mode 0600, never executed); one flock
  (`durum/yakala/.kilit`) across the page, the CLI and the server thread.
- **Job** through `ofis.add_job` (postoffice._add_job): project `arge`, tier `genel`, budget `butce_usd`,
  specialisation `analiz`, no Kontrol; record `yakala: <id>` (records.YAKALA, never from a note) keeps it off the Ar-Ge
  report path and withholds its done notice (postoffice). Crash-safe `ekleniyor` mark + adoption; a refused add (queue
  full) is retried every 10 minutes by the `Yakala` thread. Reading the stored file from `~/Dev/ofis-arge` may raise a
  permission prompt in the session (the usual "izin bekliyor" notice).
- **Result** (the `Yakala` thread, single writer): `OFIS/ArGe/Yakala-YYYY-MM-DD-<kisa>-<id4>.md` (source, note,
  recommendation from the report's `ÖNERİ: kullan | fikir al | geç` line, the report quoted line by line through
  `ozet._veri`) and ONE notice "Yakalanan bağlantı incelendi: … — öneri: …" / "Yakalanan dosya incelendi: …" (key
  `yakala-<id>`). A job ending stuck / failed / cancelled only gets its note.

## Project sorumlusu notes (OFIS/Projeler)
Plan "Sonraki iş (7)", owner decision 2026-11-12; `bin/sorumlu.py`. Every registered project (except the `arge` workspace)
has a sorumlu, for now with the generic name "<proje> sorumlusu". Projects are added, changed and removed on the
page's **Ayarlar** tab (`sayfa.md` "Ayarlar"); a new project's note appears within a minute (the 60 s thread).
- **The note** `OFIS/Projeler/<proje>.md` is written by the server (a thread every 60 s; deterministic, no clock in the
  text, atomic, only when its text changed, never through a link, never outside `OFIS/Projeler`, never a forbidden
  project). Sections: Proje (description, folder base name), **Proje kuralları** (`ofis.json` `projects.<P>.notes`,
  quoted), Hassas yollar (`hassas_yollar` plus the office-wide classes of `bin/risk.py`), **Nerede durup sorar**, **Asla
  yapmaz**, **Teslim biçimi**, İşler (running, queued, the last five finished — bare links), Bekleyen kararlar, Bu ayki
  harcama ($ · tokens), Son grup raporu. Job titles and decision titles are quoted as data (one line, brackets escaped).
  **Read it before adding a job for that project; never edit it** (server-generated, like Karne and Raporlar).
- **The three sections** come from the optional `ofis.json` key `projects.<P>.sorumlu: {dur_sor, asla, teslim}` (each a
  string or a list of strings; the owner sets them on the Ayarlar tab — "Gelişmiş" → Durup sorması gerekenler / Asla
  yapmaması gerekenler / Teslim biçimi, one per line; the CEO no longer writes this key by hand). A missing or empty one is
  derived in code — from the notes' sentences (an approval / permission rule → "Nerede durup sorar", a "never / no …"
  rule → "Asla yapmaz"), the sensitive paths and the office's own rules — and the note marks it "(varsayılan)". The
  defaults live in `bin/sorumlu.py`, never in `ofis.json`.
- **Contract**: `launch.contract` gets a "Proje kuralları" section (the rules and the three sections, capped at about
  2400 characters) at every start and every resume of a project session (the post office passes ofis.json to
  `resume_flags`). Planning work (tier `planlama`, which is also a workflow's plan step) also gets a short "Proje özeti"
  (description, jobs at work, queued, finished last) quoted as data. The full note stays in the vault.
- The page: `state.projects[].sorumlu` = `{kurallar, hassas_yollar, dur_sor, asla, teslim, varsayilan}`; the project
  sorumlusu's card shows the rules and the first lines of the three sections.
- Its family needs one `index.md` row (Vault rules): add it once.

## Sabah özeti (the morning summary)
`bin/ozet.py`, owner decision 2026-11-12. Every morning at `ofis.json` `sabah_ozeti` (optional, "HH:MM", default "08:30", in the
office zone `ofis_sahnesi.saat_dilimi`) the server writes `OFIS/Ozetler/YYYY-MM-DD.md` (deterministic, no model call):
yesterday's finished jobs with their Kontrol proof (from the server record, never the editable note: no record →
"kontrol bilinmiyor") and $ · tokens, the pending decisions, the stuck or stopped jobs,
today's queue and schedules, one line per project, yesterday's total spending of the jobs (the CEO's own is not in
it), the Sunucu odası's open suggestions and domain problems. Then ONE notice "Sabah özeti hazır: [[YYYY-MM-DD]] …"
with 3–5 key lines: **tell the owner briefly, in plain Turkish** (two or three sentences: what finished, what waits for
him, anything stuck), nothing more. A summary missed while the server was off is caught up once and only within 24
hours; never two for one day (the state `durum/ozet/son.json` and the note itself are both checked). Never edit the
note. Its family needs one `index.md` row: add it once. The note starts with a short "## Kısaca" table (Dün biten,
Kontrol geçen, Dünkü harcama, Bekleyen karar, Takılan, Bugün sırada, Sunucu odası), then the sections. A section "Dünkü gün sonu
değerlendirmesi" names yesterday's end-of-day note `[[GunSonu-YYYY-MM-DD]]` (bad cases, review job) or says the evening
window was skipped (`gunsonu.dunku`; see "End-of-day review" in `isler.md`).
