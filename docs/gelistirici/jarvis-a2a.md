# Jarvis ↔ Ofis over A2A — handoff for the Jarvis developer

Ofis exposes a small A2A server for Jarvis. Two scopes, both approved by the owner on 2026-11-14 (ofis.json
`jarvis.kapsam`):
- `durum-karar`: **office status, the project list, list pending decisions, answer one**.
- `durum-karar-is` (scope 3): the same **plus `is-ekle`** — the owner's spoken request for new work, handed to the CEO
  as if he had typed it in the office page's chat. The office never adds a job directly from Jarvis; the CEO does,
  following its usual rules (it may ask back with a decision card).

Nothing else — no free chat. The Agent Card lists `is-ekle` only when the scope allows it; read the card at start. Server code: `bin/jarvis.py`; security
rules: `docs/gelistirici/guvenlik.md` ("The Jarvis gate").

## Where
| What | Value |
|---|---|
| Agent Card | `GET http://127.0.0.1:8800/.well-known/agent-card.json` (also `/.well-known/agent.json`); no key needed |
| Endpoint | `POST http://127.0.0.1:8800/a2a`, JSON-RPC 2.0, `Content-Type: application/json`, body ≤ 16 KB |
| Key | `~/Dev/ajan-ofisi/durum/jarvis_anahtari` (one line, mode 0600) → `Authorization: Bearer <key>` |
| Switch | ofis.json `jarvis.acik`; when off every path above answers **404** |
| Scope | ofis.json `jarvis.kapsam`: `durum-karar` or `durum-karar-is`; `jarvis.is_saatlik_sinir` (default 10) |

The port is 8800 unless it was taken (the server then uses the next free one up to 8819; the card's `url` names the
real one). Use `127.0.0.1` or `localhost` as the host — any other Host header is 403. Send **no `Origin` header**
(a request with one is 403: browsers are kept out). Read the key file at start and again after a 401 (it is
regenerated if someone deletes it and restarts the server). Never log or display the key.

Limits: 60 requests a minute in total (failed ones count) → `429` + `Retry-After: 60`. HTTP errors outside JSON-RPC:
`401` bad/missing key, `403` Host/peer/Origin, `404` gate off, `413` body too large, `415` not JSON.

## Protocol
A2A **1.0** JSON-RPC binding (`SendMessage`, `GetTask`; parts `{"text": …}` / `{"data": {…}}`; roles `ROLE_USER` /
`ROLE_AGENT`; states `TASK_STATE_*`; the result of `SendMessage` is `{"task": {…}}`). For 0.3 clients the same calls
work as `message/send` / `tasks/get` with `kind` fields, roles `user` / `agent`, lowercase states and the task as the
result itself. The method you call picks the shape of the answer. An `A2A-Version` header, if sent, must be 0.3 or 1.x.

No streaming, push notifications, task listing or cancelling (`-32004` / `-32002`). Every `SendMessage` returns a
task that is already final — `TASK_STATE_COMPLETED`, `TASK_STATE_REJECTED`, `TASK_STATE_FAILED` — or
`TASK_STATE_INPUT_REQUIRED` (continue it by sending a message with its `taskId`). Tasks are kept in memory for this
server run only (at most 200); `GetTask` after a restart → `-32001`. Re-sending the same `messageId` returns the same
task without doing anything again.

**Choosing the skill**: put it in `message.metadata.skill`, or in a data part's `skill` field, or send a text part that
is exactly `durum`, `projeler` or `kararlar`. Free text is never interpreted — it comes back `TASK_STATE_REJECTED`. Turn speech
into a skill call on the Jarvis side.

Output: a completed task has one artifact (name = the skill) with a Turkish `text` part (short, fit to read aloud)
and a `data` part with the same content as JSON. A rejected / input-required / failed task has the reason in
`status.message` (text + data `{"kod": …}`).

## `durum` — office status
```json
{"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
 "params": {"message": {"messageId": "6f1c…", "role": "ROLE_USER", "parts": [{"text": "durum"}]}}}
```
Result (shortened):
```json
{"jsonrpc": "2.0", "id": 1, "result": {"task": {
  "id": "…", "contextId": "…", "metadata": {"skill": "durum"},
  "status": {"state": "TASK_STATE_COMPLETED", "timestamp": "2026-11-14T16:47:38.510Z", "message": {…}},
  "artifacts": [{"artifactId": "…", "name": "durum", "parts": [
    {"text": "Ofis durumu: 1 iş çalışıyor, 0 iş sırada.\n- blog — Giriş sayfası: blog masasında çalışıyor\nBekleyen karar: 2 (1 tanesi yüksek riskli).\nCEO: boşta.\nBugünkü kullanım: $0.41 · 182 bin token."},
    {"data": {
      "calisan": [{"not": "2026-11-14-100000-blog.md", "baslik": "Giriş sayfası", "proje": "blog",
                   "durum": "calisiyor", "adim": {"adim": "calisiyor", "etiket": "blog masasında çalışıyor", "not": ""},
                   "harcanan_usd": 0.41, "butce_usd": 6.0}],
      "sirada": [],
      "bekleyen_karar": 2, "yuksek_riskli_karar": 1,
      "ceo": {"durum": "idle", "etiket": "boşta", "kuyruk": 0},
      "bugun": {"gun": "2026-11-14", "isler_usd": 0.41, "ceo_usd": 0.0, "toplam_usd": 0.41, "toplam_token": 182000},
      "limitler": null,
      "projeler": [{"ad": "blog", "aciklama": "Blog — first project connected to the office."}]},
     "mediaType": "application/json"}]}]}}}
```
`adim.adim` is the job's current step: `verildi` (queued / starting; label "çalışan işi alacak" / "çalışan işi aldı",
"Ar-Ge uzmanı …" for the Ar-Ge desk), `calisiyor` ("<proje> masasında çalışıyor", "Ar-Ge odasında çalışıyor"),
`kontrol`, `rapor`, `ceo` — the same wording as the page's progress line; `adim.not` says what it waits for ("senin cevabını bekliyor", "izin bekliyor"). `toplam_token` is `null` when unknown.

## `projeler` — the office's projects (both scopes)
```json
{"jsonrpc": "2.0", "id": 6, "method": "SendMessage",
 "params": {"message": {"messageId": "…", "role": "ROLE_USER", "parts": [{"text": "projeler"}]}}}
```
Data part of the artifact (name + the first line of the description; never a path):
```json
{"projeler": [{"ad": "atolye", "aciklama": "Atolye — borsa verisi işleme platformu (…)."},
              {"ad": "blog", "aciklama": "Blog — first project connected to the office."}]}
```
Use the `ad` values for `is-ekle`'s `proje` (e.g. to map "blog'a …" in speech to a project). The same list is in
`durum`'s data as `projeler`.

## `kararlar` — pending decisions
```json
{"jsonrpc": "2.0", "id": 2, "method": "SendMessage",
 "params": {"message": {"messageId": "…", "role": "ROLE_USER", "parts": [{"data": {"skill": "kararlar"}}]}}}
```
Data part of the artifact:
```json
{"kararlar": [
  {"note": "2026-11-14-blog-ceo-sorusu.md", "baslik": "Test yaklaşımı", "proje": "blog", "tur": "ceo-sorusu",
   "soru": "Hangisini seçelim?", "secenekler": [{"kod": "A", "metin": "Birim testler"}, {"kod": "B", "metin": "Uçtan uca"}],
   "risk": "normal", "risk_nedeni": "", "ekran_onayi_gerekir": false, "soruldu": "2026-11-14T10:00",
   "cevap_iletildi": false},
  {"note": "2026-11-14-blog-push.md", "baslik": "blog — main", "proje": "blog", "tur": "proje-sorusu",
   "soru": "main dalına zorla gönderelim mi?", "secenekler": [], "risk": "yuksek",
   "risk_nedeni": "zorla gönderme ya da geçmişi yeniden yazma", "ekran_onayi_gerekir": true,
   "soruldu": "2026-11-14T11:00", "cevap_iletildi": false}]}
```
`tur`: `proje-sorusu` (a project asks), `ceo-sorusu` (the CEO asks; has options), `akis-onay` (a workflow's approval
card), `mudur-karari` (a manager answered or is looking; the owner's answer replaces the manager's), and the office's own
cards (`claude-md-onerisi`, `model-onerisi`, …). `soru` is at most 300 characters. `cevap_iletildi: true` = an answer
is already on its way (from the page or Jarvis); a new one will be refused.

## `karar-cevapla` — answer one decision
```json
{"jsonrpc": "2.0", "id": 3, "method": "SendMessage",
 "params": {"message": {"messageId": "…", "role": "ROLE_USER",
   "parts": [{"data": {"skill": "karar-cevapla", "note": "2026-11-14-blog-ceo-sorusu.md", "cevap": "A",
                       "ekran_onayi": false}}]}}}
```
- `note`: the `note` from `kararlar`. `cevap`: an option code (`"A"` becomes `"A) <option text>"`, exactly like the
  page's option button) or free text (≤ 4000 characters). `ekran_onayi`: boolean, see the risk rule.
- Completed: `{"note", "cevap" (as sent to the CEO), "iletim": "delivered" | "queued", "zaten_iletildi": false,
  "kanal": "Jarvis üzerinden"}`. The answer reaches the CEO exactly as a page answer (`[Sahip · karar cevabı] <note>`);
  the decision note is marked `cevap_kanali: Jarvis üzerinden`.
- Same answer again (also with a new `messageId`, also after a server restart): completed with `"zaten_iletildi":
  true`, nothing is sent twice.
- Rejected, `data.kod`: `yok` (no such note), `cevaplanmis` (already answered), `gecersiz` (bad note name), `eksik`
  (no note), `secenek-yok` (the card has no such option), `cevap-iletildi` (another answer is already on its way),
  `uzun`. Failed: `ceo-ulasilamiyor` (try again later).
- Input required: `cevap-gerekli` (empty answer) or `ekran_onayi_gerekir` (below).

### The risk rule (`ekran_onayi`)
A card is `risk: "yuksek"` when it is about commit / push / force push / merge / release / branch, deleting, history
rewrite (amend, squash, reset), money / budget or a budget / call-limit increase, an ofis.json change (model and
advisor cards), when the card's own risk level is high, or when it has an open security finding. The `kararlar` list
already carries `risk` and `ekran_onayi_gerekir`.

For such a card send `"ekran_onayi": true` **only after the owner pressed an on-screen confirm button in Jarvis** — never
from a voice "evet". Without it the answer is not sent and the task comes back:
```json
{"status": {"state": "TASK_STATE_INPUT_REQUIRED", "message": {"role": "ROLE_AGENT", "parts": [
  {"text": "Bu karar yüksek riskli (zorla gönderme ya da geçmişi yeniden yazma). Cevabı ekrandaki onay düğmesiyle ver; sesle onay yetmez."},
  {"data": {"kod": "ekran_onayi_gerekir", "note": "…", "risk": "yuksek", "risk_nedeni": "…", "ekran_onayi_gerekir": true},
   "mediaType": "application/json"}]}}}
```
After the button, continue the same task (the note and the answer are remembered):
```json
{"jsonrpc": "2.0", "id": 4, "method": "SendMessage",
 "params": {"message": {"messageId": "…", "role": "ROLE_USER", "taskId": "<the task id>",
   "parts": [{"data": {"ekran_onayi": true}}]}}}
```

## `is-ekle` — give the office new work (only scope `durum-karar-is`)
Show the owner the transcribed text on screen with a **"Gönder"** button; send only after he pressed it.
```json
{"jsonrpc": "2.0", "id": 8, "method": "SendMessage",
 "params": {"message": {"messageId": "9b2e…", "role": "ROLE_USER",
   "parts": [{"data": {"skill": "is-ekle", "proje": "blog",
                       "metin": "Giriş sayfasındaki hata mesajını Türkçeleştir", "dugme_onayi": true}}]}}}
```
- `metin`: the owner's words **verbatim** as transcribed (do not summarise or rewrite), non-empty, ≤ 2000 characters, in
  one data part (two parts with `metin` → rejected `tek-mesaj`).
- `proje`: `""` (the CEO decides) or an `ad` from `projeler`; anything else → rejected `proje-yok` (data lists the
  known names).
- `dugme_onayi`: must be the boolean `true`, set **only by the on-screen Gönder button** — never from a voice "evet".
  Otherwise the task is `TASK_STATE_INPUT_REQUIRED` with `kod: dugme_onayi_gerekir`; after the button, continue the
  same task with `{"taskId": "<id>", "parts": [{"data": {"dugme_onayi": true}}]}` (the text is remembered).
- The CEO receives exactly what the page chat would deliver, with its own first line:
  ```
  [Sahip · Jarvis]
  Proje: blog
  Giriş sayfasındaki hata mesajını Türkçeleştir
  ```
  (no `Proje:` line when `proje` is empty). The office page shows it as the owner's own message, marked
  "Jarvis üzerinden". The CEO's reply appears in the page chat; use `durum` / `kararlar` to follow up (a question
  from the CEO becomes a decision card).
- Completed data: `{"iletildi": true, "mesaj_kimligi": "jarvis-3f9a1c0b2d4e", "iletim": "delivered" | "queued",
  "zaten_iletildi": false, "proje": "blog", "kanal": "Jarvis üzerinden"}` (`queued` = the CEO is busy; it gets it
  next).
- **Idempotent by `messageId`**: re-sending the same `messageId` (also after a server restart) → completed with
  `"zaten_iletildi": true` and the same `mesaj_kimligi`; nothing is delivered twice. Use a new `messageId` for each
  new request.
- Rejected `kod`: `kapsam-disi` (scope is `durum-karar`), `uzun`, `gecersiz` (wrong field type), `proje-yok`,
  `tek-mesaj`, `saatlik-sinir` (more than `jarvis.is_saatlik_sinir`, default 10, deliveries in the last hour).
  Input required: `metin-gerekli`, `dugme_onayi_gerekir`. Failed: `ceo-ulasilamiyor` (try again later with the same
  `messageId`).

## Get a task again
```json
{"jsonrpc": "2.0", "id": 5, "method": "GetTask", "params": {"id": "<task id>"}}
```

## Everything else
Any other skill or free text → `TASK_STATE_REJECTED` with "Bu kapıdan yalnız şunlar istenebilir: …" and
`data.beceriler` = the skills of the current scope. JSON-RPC errors: `-32700` bad JSON, `-32600` not a JSON-RPC request (batches are not supported),
`-32601` unknown method, `-32602` bad params (no `messageId`, no `parts`, role not user, a finished `taskId`),
`-32001` task not found, `-32002` cancel, `-32004` streaming / push / list, `-32009` unsupported `A2A-Version`.
