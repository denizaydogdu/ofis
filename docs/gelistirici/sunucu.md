# Server internals (state files, autostart, log rotation, error record, HTTP security)

> Moved verbatim from the CEO's `CLAUDE.md` on 2026-11-13 (split approved by the owner). In this text "you" is the
> CEO session. A section named in quotes ("see …") may live in another file: the index in
> [`../GELISTIRICI.md`](../GELISTIRICI.md) lists where each one is. The CEO's own rule set is `CLAUDE.md`; when a
> CEO-facing rule changes here, change `CLAUDE.md` too.

## Server internals (part of "The office page")
- The server keeps the CEO session id in `durum/ceo.json`, the CEO queue in `durum/ceo-queue.jsonl`, delivered
  notice keys in `durum/ceo-sent.txt`, the decision notes whose answer the owner already sent in `durum/ceo-cevaplar.txt`
  (with the CEO queue it refuses a second answer to the same card, 409 "Bu karara cevabın zaten iletildi", also after
  a restart; the card then shows "Cevap iletildi"; 30 minutes after a delivery a card whose note is still pending —
  you never ran `cevapla` — takes an answer again), the group report states in `durum/raporlar/`, and the office
  sessions it has seen in `durum/sessions.json`, the usage-limit notices already sent per window in `durum/limitler/uyarilar.json` (bin/limitler.py), the end-of-day review's day states in `durum/gunsonu/gunler/` (+
  `durum/gunsonu/ilk.json`, the feature's first day; bin/gunsonu.py, never edited by hand). The post office
  uses `durum/gelen/` (reports; rejected ones in `durum/gelen/reddedilen/`), `durum/giden/` (answers, named
  `<time_ns>-cevap-<note>.json`; undeliverable ones in `durum/giden/reddedilen/`) and `durum/kuyruk/` (one queue
  per project session). Job-note writers share the lock `durum/jobs.lock`; `durum/taslak/` holds the CEO's input
  files. If `ofis-ceo` does not exist, the first message starts it; a
  project session is never started by the server. A delivery whose `claude` call timed out is never re-sent: it is
  logged in the `*-unconfirmed.jsonl` file and shown as the last error. Only one server runs at a time
  (`durum/server.lock`); a second one exits (exit code 0) with "Ofis server already running".
- **CEO session rotation** (owner decision 2026-11-14, `bin/ceo.py`, `bin/devir.py`, ofis.json `ceo_yenileme: {acik,
  baglam_esigi (150000), soguk_esik (60000), soguk_dk (55), gunluk (true)}`; missing or `acik` not true = off, exactly
  the old behaviour). Every CEO call re-reads its whole context (measured ~640K tokens: ≈ $0.30 a step warm, $4–5 cold).
  Right before a message goes to an idle or dormant CEO (never busy or at a permission prompt) the server starts a
  FRESH `ofis-ceo` session instead of resuming when (a) the newest call's context (input + cache read + cache creation)
  ≥ `baglam_esigi`, (b) the CEO has been idle ≥ `soguk_dk` minutes (cold cache) and its context ≥ `soguk_esik`, or
  (c) `gunluk` and the session began on an earlier office day. The first prompt is the handoff block (no model call,
  ≤ ~11 000 characters): open jobs, pending decisions and manager cards, the last 8 the owner ↔ CEO lines, the notices after
  the CEO's last reply, the other queued messages, schedules, the advisor pilot — every model/project/person text one
  inert quoted line (`ozet._veri`), between `[Ofis · devir notu · <id>]` and `[Ofis · devir notu sonu · <id>]`. The id
  (16 hex) is written to `durum/ceo.json` `devir_kimlikleri` before the start; the chat shows a recorded block as one
  system line "CEO yeni oturumla devam ediyor · devir notu verildi" and any other (an unknown id, no end line) unchanged
  as the owner's text. Only after claude confirmed the new session (its launch line, or one new `ofis-ceo` in `claude
  agents`) the old one is stopped with `claude stop` (only if still idle; never rm). `durum/ceo.json` keeps
  `session_ids` (every id; the global Codex Stop hook skips these and every OFIS_OTURUMU=1 session), `yenilemeler`
  (eski, yeni, zaman, neden; at most 50) and `baslangic`. A refused start falls back to resuming the old session with
  the plain message; a timed-out start is unconfirmed like any launch (never re-sent); either way no new attempt for 10
  minutes and one row in `OFIS/Sunucu` (kind `ceo`), as for every rotation. The page's chat, `/api/ceo/adimlar` and
  `/api/ceo/turlar` also read the last three sessions the CEO was rotated away from; today's CEO spending counts every
  recorded earlier session written today;
  `/api/state.ceo.baglam_token` is the current context size.
  **Forced rotation**: `python3 bin/ofis.py ceo-yenile` writes the flag `durum/ceo-yenile`; the next delivery to an
  idle or dormant CEO rotates with reason `elle` ("elle istendi"), also when `ceo_yenileme` is off; the flag is removed
  once a CEO session was started. Use it after CLAUDE.md or the message protocol changed. A fresh session also gets
  the owner's name in its system text (`ceo.ceo_system_prompt`, ofis.json `sahip_adi`).
- **Autostart at login** (macOS LaunchAgent, `bin/autostart.py`): `python3 bin/autostart.py install` writes
  `~/Library/LaunchAgents/local.ofis.server.plist` (the installing python and `bin/server.py` by absolute path, this
  folder as working directory, PATH with the folders of `claude` and `codex` found at install time plus the
  installing shell's PATH, HOME, LANG) and loads it with `launchctl bootstrap gui/<uid>`; from then on the server
  starts by itself at every login and launchd restarts it after a crash (not after a clean exit, so a second server
  — e.g. one started by hand — simply stops). The log is `~/Library/Logs/ofis/server.log`. `--dry-run` shows what
  would be done. Run `install` again after claude/codex move or PATH changes (it replaces only its own plist).
  `python3 bin/autostart.py status`: installed or not, loaded, pid, the page's port and any Obsidian access error of
  the latest start. **Turn it off**: `python3 bin/autostart.py uninstall` (`launchctl bootout` + removes only our
  plist; the running server stops, the log stays); afterwards start the server by hand again.
  macOS privacy: a python started by launchd may be refused the Obsidian vault under `~/Documents` ("Operation not
  permitted"). The server then logs one line starting with `ofis: HATA Obsidian` and keeps running (but cannot read
  jobs or decisions); `status` shows it. Fix: System Settings > Privacy & Security > Full Disk Access (Tam Disk
  Erişimi) → add the python binary the line names (its real path, e.g. under `/opt/homebrew/Cellar/…`; `+`, then
  ⌘⇧G to type the path), or allow Documents under Files and Folders when macOS asks; then `python3 bin/autostart.py
  install` again (or log out and in) to restart it.
  **Log rotation**: launchd keeps its own handle on `server.log`, so the server rotates it in place (`LogRotator` in
  `bin/server.py`, checked every 5 minutes): above 5 MB the last ~1 MB (from a line start) is copied to
  `server.log.1` (replaced) and `server.log` is truncated; the start lines (marker, port, an Obsidian error) are
  written back so `status` still works. It acts only when stdout is that very file opened with O_APPEND (a server
  started by hand is never touched) and never deletes anything.
  **Error record in the vault**: besides the local log the server keeps `OFIS/Sunucu/Hatalar-YYYY-MM.md`
  (`bin/olaylar.py`): only errors and important events — server start (pid, port), the Obsidian access error, the
  errors the post office / dispatcher / Kontrol / workflow / scheduler / karne / report loops log, rejected inbox and
  outbox files, failed or unconfirmed deliveries, page refresh failures, a crash of the server loop — never request
  lines or quoted project text. One table row per (Tür, İleti with numbers, ids and temp paths normalised) per month:
  a repeat updates Son görülme and Sayı. Written atomically, at most every 30 s (a new row at once), only as a plain
  file under `OFIS/Sunucu/`; when the vault cannot be written the server goes on and says so once in the local log.
- Security: requests must use Host `127.0.0.1:<port>`/`localhost:<port>`; POSTs need the exact Origin, JSON, a
  body ≤ 16 KB and the per-start `X-Ofis-Token` that is injected into the page (`/api/chat`, `/api/answer`,
  `/api/duyuru`, `/api/yakala`). No CORS. `/api/yakala` alone has a larger body limit (`yakala.govde_siniri`: the
  file limit of ofis.json `yakala.dosya_mb` in base64 + 64 KB; 16 KB while the box is off), checked before the body is
  read; it answers 409 while off and 429 over its hourly limit.
  The page's endpoints refuse any request with an `Authorization` header (403): the Jarvis key opens `/a2a` only.
- **The Jarvis gate** (owner decision 2026-11-14, scopes "durum-karar" / "durum-karar-is", `bin/jarvis.py`; security and threat model in
  `gelistirici/guvenlik.md`, client handoff in `gelistirici/jarvis-a2a.md`): an A2A-compatible door for Jarvis, the owner's
  local menu-bar app. `GET /.well-known/agent-card.json` (also `/.well-known/agent.json`) = the Agent Card (no key);
  `POST /a2a` = JSON-RPC 2.0 with `Authorization: Bearer <durum/jarvis_anahtari>`: A2A 1.0 `SendMessage` / `GetTask`
  and the 0.3 names `message/send` / `tasks/get` (the method picks the answer's shape); cancel, streaming, push and
  task lists are refused. Skills: `durum` (running / queued jobs with their progress-line step, pending decisions,
  the CEO's state, today's spending, the projects: Turkish text + the same as data), `projeler` ([{ad, aciklama}]
  from ofis.json projects, no paths), `kararlar` (the pending cards and the manager cards with options and the risk
  rule), `karar-cevapla` ({note, cevap, ekran_onayi}: `App.answer_decision`, the one answer path of POST
  `/api/answer`) and, only under kapsam "durum-karar-is", `is-ekle` ({proje, metin, dugme_onayi}: one
  `[Sahip · Jarvis]` prompt to the CEO via `App.sohbet_ilet`, the one chat path of POST `/api/chat`; it adds no job);
  anything else is a `rejected` task. ofis.json `jarvis: {acik, kapsam ("durum-karar" | "durum-karar-is"),
  dakika_sinir (60), is_saatlik_sinir (10)}`: off, missing or another kapsam = every Jarvis path answers 404. State:
  `durum/jarvis_anahtari` (the key, 0600, made on the first request while the gate is on), `durum/jarvis/cevaplar.json`
  (note → hash of the answer Jarvis delivered, for idempotency; at most 500); the tasks of a run live in memory (at
  most 200), `durum/jarvis/is_ekle.json` (is-ekle deliveries: message-id hash, server id `jarvis-<hex>`, time — for
  idempotency and the hourly limit; never the text; at most 500). A delivered Jarvis answer sets `cevap_kanali: Jarvis üzerinden` in the decision note (under the job lock)
  and logs one line `ofis: karar cevabı Jarvis üzerinden iletildi: <note>` (never the answer, never the key).
