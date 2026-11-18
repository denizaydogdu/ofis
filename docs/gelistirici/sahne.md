# The living office scene (3D, NPCs, performance, demo)

> Moved verbatim from the CEO's `CLAUDE.md` on 2026-11-13 (split approved by the owner). In this text "you" is the
> CEO session. A section named in quotes ("see …") may live in another file: the index in
> [`../GELISTIRICI.md`](../GELISTIRICI.md) lists where each one is. The CEO's own rule set is `CLAUDE.md`; when a
> CEO-facing rule changes here, change `CLAUDE.md` too.

## The living office scene (part of "The office page")
- **Performance** (NPC audit 2026-11-12, the owner's fan): the scene draws on change only, capped (`hedefFps`: about 60 fps
  while the camera moves, 30 while someone walks or the ball flies, 9 at rest; `setActors` draws the next frame at
  once), nothing while the tab is hidden, a tab panel covers the scene or the Komuta masası is open (app.js skips the 1 s
  `renderScene` then and catches up when the scene shows again); the pixel ratio is at most 1.5 and a screen above that
  gets no MSAA; the static furniture is merged into one mesh per shared material (`statikBirlestir`; the lift doors and
  the ping-pong ball stay, `userData.dinamik`), a robot's still parts (shell, belt, cheeks, accessories, the staff's
  tray) in one mesh per surface kind (roughness, metalness, side) with each part's colour as a vertex colour under a
  shared vertex-coloured material (`govdeBirlestir`, `renkliMat`; plan B5, the owner, 2026-11-12: about 6–8 draw calls per
  robot instead of 10–13; the eyes and the bulb (their own glow), the arms, the legs, the visor and the things in hand
  stay separate), an unlit desk glow is hidden, a desk's dark screen shares one material and is merged (its lit screen
  is a separate mesh drawn only while someone types there — a dim, waiting desk shows the dark screen), the floors of
  the rooms that cannot be selected and of the reserved bays share one material per colour and are merged (plan
  "Sonraki iş (9)", owner decision 2026-11-13) — measured with the fake-DOM counter (`run_scene_count`, scenario `dort-mesgul`,
  a fresh process): 689 draw calls at 10:30, 717 at the busy 16:00 shift change (two guards, two Sekreters, the IT
  team, the four managers; 711 before the company structure, 889 before the vertex-colour merge, ~2 900 originally),
  363 at 03:00, 396 in hafif and 609 with three helpers per job (with the decorative people, two draw calls more by
  day: 719 at 16:00, 691 at 10:30, 398 in hafif, 611 with three helpers; see "Decorative people"; with the wider common
  area of the 20-bed Dinlenme odası, 2026-11-13: 714 at 16:00, 689 at 10:30, 579 with three helpers, 386 in hafif, 365
  at 03:45 with everyone asleep — the beds are merged static furniture, the wider common area leaves fewer reserved
  bays; the end-of-day review team adds nothing at the 16:00 peak — 714 — and draws 389 at 20:25 with both of them at
  work, 369 without them; the Otel, 2026-11-14: the building adds no draw call — it uses the office's materials — and its
  guests are hidden inside, so the numbers are unchanged or lower: 694 at 16:00 (the off-shift guard, Sekreter and IT
  person are at the hotel, not on the floor, in this from-scratch count), 689 at 10:30, 368 at 03:45, 352 for the empty
  office at 03:45, 386 in hafif, 383 at 20:25, 579 with three helpers. Measured as a walking sequence (ticks every
  2–5 s with the scene's frames, `prev` carried) the peaks are the same as before the Otel: 688 during the evening
  walk-out (18:00–19:15), 649 in the morning walk-in, 401 at the 24:00 change, and **732 at the 16:00 change** —
  the same 732 at HEAD 68cef49, so it predates the Otel; the from-scratch count above stays under the limit). **Legs
  and arms instanced** (2026-11-14): each robot drew its two legs (shown while standing or walking) and its two arms as
  four separate meshes — the walkers of a shift change pushed it over; now every robot's legs are instances of ONE
  `InstancedMesh` and every robot's arms of a second one (`Office.bacaklariCiz`: the hips and the arm groups still move
  in `pose`, each marker's world matrix becomes its instance's, the instance colour is the robot's trim; they cast
  shadows like before, take no clicks, are never culled). Measured after it, with the meals, the kitchen corner and the
  six kitchen people: walking sequence **608 at the 16:00 change** (732 before), 633 at lunch (12:25), 579 in the
  morning walk-in and breakfast, 572 in the evening walk-out, 381 at dinner, 385 at the 24:00 change, 352 on Saturday's
  wake-up, 343 at Saturday's breakfast; from scratch 552 at 16:00 (694), 577 at 10:30 (689), 356 at 03:45 (368), 340
  for the empty office at 03:45 (352), 348 in hafif (386), 367 at 20:25 (383), 497 with three helpers (579), 322 on
  Saturday at 10:30. `PerformanceTest.test_the_walking_sequence_stays_under_the_draw_limit` now runs the sequence
  method (the 16:00, 18:00–19:15, 07:50–08:50, lunch, dinner and 24:00 windows, Saturday's wake-up and breakfast) and
  holds every peak ≤ `DRAW_LIMIT`, the 16:00 one ≤ 715; `test_all_robot_legs_are_one_instanced_mesh_…` checks the
  instances' places and colours. `test/test_npc.py` holds the peak under `DRAW_LIMIT` = 725; only the robots cast shadows and the
  shadow map is redrawn only while something moves (and every 2 s); walks come from a cached heap Dijkstra on a per-plan
  adjacency (`yol`; `yolUzunlugu`), and the label sizes are read in one pass per frame.
- `?hafif=1` lowers render quality (pixel ratio 1, no shadows, no tea server, no leg swing); `?demo=1` runs the page
  on fake data with no backend calls (also the board, reports and quality views). In the scene the demo plays a
  scripted ~3-minute loop (`web/demo.js`: `DEMO_SAHNELERI`, `DEMO_SURE` = 200 s; `demoDurumu(t, now)` is the pure
  state at loop second t) showing every event in order: a new job comes up the lift and waits in the lobby, goes to
  its desk and types, a helper (subagent) joins and leaves with ✓, a permission prompt (!), its Kontrol (test lamp),
  ✓ with the tea server, the walk to the lift; a decision at the CEO's door (?) — answering its card in the demo sends
  the job back to its desk —, a Claude review typing in the Uzmanlar odası while Codex, GLM and DeepSeek type in the
  auditor's room, then the Hakem (Sonnet) weighing their findings at an Uzmanlar odası desk, an escalation (the Stajyer carries the file to the
  Kıdemli's desk, then leaves), lunch (idle ones in the canteen), Sonnet's quota (its idle agent goes home, the
  Çalışanlar list says "kota doldu · HH:MM'de döner"; DeepSeek's "Evde" sign too) and its return. A small caption under the scene names the current scene in
  plain words of the page's language ("Demo · Yeni iş geliyor …"; English: see sayfa.md "Language"). `?demo_t=<s>` starts the loop at second s (screenshots). Lunch is
  shown by moving the demo's own `sahne.ogle` window onto the current time with `sahne.ogle_hepsi` (everyone idle eats at
  once in that scene; the server never sends it); the real lunch rule is unchanged.
  `?demo=1&hafif=1` works (no tea server, simpler walk). Its four projects fill the free cells of the compact
  floor, with the cells left over as empty reserved bays.

- **Living office scene.** The 3D view is one office floor with room to breathe (`OLCU` in `web/ofis-davranis.js`),
  in two parts. The **common area** (`plan.ortak`, its layout never depends on the number of projects): back row —
  meeting room, Genel Müdür odası, CEO room (glass, centred), the external auditors' room (one desk each, side by side,
  3.6 apart: Codex and every free reviewer of `modeller`, `odaDenetcileri(denetciListesi(…))` — never the security
  reviewer, whose desk is the IT güvenlik desk of the Sunucu odası; the room — and the common area, so the CEO's room
  stays centred — widens for three or more); middle row — the **Uzmanlar odası** (under the CEO's room, six desks in two
  rows): the quiet work room where the hakem weighs the findings (plan "Sonraki iş (9)": the Claude reviews moved to the
  QA odası and the Analist odası, see "Company structure"); full → one "+N"; left of it the
  **Oyun odası** (fixed size, `plan.oyun`: a table-tennis table, a billiards table, a darts board on the back wall, a
  bean bag; spots `oyun-pingpong-0/1` facing each other, `oyun-bilardo-0/1`, `oyun-dart`, `oyun-puf`); front row — the
  tea corner (a long counter: kettle, samovar, coffee machine, cups; two standing places `cay-ocagi-tezgah-yer-*`; three
  round tables with nine stools), the Ortak alan (four kadro armchairs, two café tables with four chairs
  `ortak-alan-yer-*`, a sofa), the canteen, the **Revir** at its right end. The **Toplantı odası** stays an empty
  meeting room (no actor is sent there; nothing honest maps to a meeting yet). **A compact floor** (the owner, 2026-11-12:
  about 1.3–1.8 : 1, no empty strips; `zeminIzgarasi` / `kanatIzgarasi(T, options)`): one grid of bay-sized cells,
  rows `SATIR_ARA` = 3 apart (row r at z = r × 12.5 base units, so a cell never moves when rows are added), in two
  regions. The **project wing** (`plan.kanat`) right of the common area behind a 4-unit spine corridor: columns filled
  column by column away from the spine, with **as many rows as the common area is deep** (front row, the canteen, the
  facility cells under it; rounded to the nearest row, at least 5) — a deeper canteen gives the wing more rows and
  fewer columns; the columns are the fewest that hold every project and one reserved bay, plus more while the floor
  would be narrower than 1.3 : 1. **Under the common area** (rows 3 and below): two 12-wide columns left of the canteen
  (off the left aisle, corridors `a<r>`) and one under the Revir (off the wing corridors). The fixed facilities
  (`KANAT_TESISLERI`, cells in `TESIS_HUCRELERI`, never moving when projects are added): in the wing's first two
  columns **Muhasebe**, **WC** (a covered block — walls and a closed lid — with two doors signed "Erkek WC" / "Kadın
  WC", sinks outside), **İdari işler** / **İnsan kaynakları**, **Sosyal medya ve tasarım** (two bays one above the
  other: the platform pod, then the studio with the creative and influencer pods; members in one data list
  `SOSYAL_EKIBI`, a new role is one line); under the common area the **Sigara odası** (the terrace, in front of the tea
  corner), **Spor salonu** (treadmills, a bike, a weight bench, mats) with the **Duş** (covered like the WC) below it,
  the **Masaj odası** and the **Psikolog**; the **Revir** in the front row's right end; the **Sunucu odası** (server
  cabinets with status lights; see "Sunucu odası") in the wing's first column under İdari işler; the **Ar-Ge odası**
  (a whiteboard, a bookcase, two desks; see "Ar-Ge odası") in the wing's second column under the studio — the `arge`
  project is this facility, never a team bay; the **company's offices** (plan "Sonraki iş (9)", see "Company
  structure"): two cells of glass manager offices in row 4 (wing column 0: **Yazılım Müdürü odası** | **IT Müdürü
  odası**, column 1: **QA Müdürü odası** | **Analist Müdürü odası**; two offices side by side per cell,
  `MUDURLUK_ARA` apart, a door on the corridor above and below), the **QA odası** in row 5 of wing column 0 and the
  **Analist odası** in row 5 under the Psikolog (across the spine from it). So the floor has at least `EN_AZ_SATIR` = 6
  rows (the facility cells never move). Team bays (12 × 9.5, low
  partitions all round; a manager's desk + `max_running_per_project + 2` desks 4 units apart, the server sends the
  limit in `summary`; helper spots, the project's floor colour, "<proje> ekibi") take the free wing cells, then the
  free cells under the common area (`kanatIzgarasi(T).hucreler`: project i in cell i); every cell left over in the used
  columns is an empty reserved bay ("Boş ekip alanı · yeni proje": pale floor, dashed outline, no desks), so no cell
  stays bare; the bottom row's bays and the canteen reach the floor's front edge. Adding projects grows the floor in
  both directions (the canteen deepens the rows, the wing adds columns). The **lobby** ("Giriş") is the floor's
  **front-right corner**, two cells wide: the wing's last two columns in its bottom row, laid out after the wing so it
  stays in the corner as projects are added (the outer wall's entrance gap is its front); the lift in its back wall
  with the guard's post and greeting spot beside it, the Sekreter's reception desk in front of them, and a guest
  waiting area (six armchairs `lobi-koltuk-*` in two rows — the queued jobs wait there —, a low table, plants, a water
  dispenser). Corridors run between the rows; the spine joins the common and the wing corridors, the left aisle the
  common corridors and the ones left of the canteen — rooms never touch, every place is reachable.
  reachable. Helpers stand in two small columns beside their parent's chair (`yardimciYerleri`), never behind it. The
  camera fits the whole floor in the area left of the side panel, again on a resize until the viewer
  moves the camera. **View controls** (the owner, 2026-11-13: moved to the bottom-LEFT, bottom-right felt too central): a
  small vertical button group at the scene's bottom-left corner with a 16px gutter (`--s2`; on a phone too, at the
  scene's bottom-left above the sheet): "+" (Yakınlaştır), "−" (Uzaklaştır), "↺" (Sola döndür), "↻" (Sağa döndür),
  "⟲" (Tümünü göster); keys + / − / Q / E / 0 when no field has focus (no Ctrl/Meta/Alt; not while a panel, the chat
  or a dialog is open). The demo caption and the one-time hint sit right of the group (the hint above the caption while
  one shows), the "Mesai dışı" line at the scene's bottom-right, left of the side panel. A zoom step is a smooth zoom
  towards the current view centre within the controls' min/max zoom (`sonrakiZoom`, `zoomTusu` in
  `web/ofis-sahne.js`). **Turning**: the azimuth is free (a full 360°; the tilt limits `minPolarAngle` 0.55 /
  `maxPolarAngle` 1.12 stay, so the camera never goes under the floor); ↺ / ↻ and Q / E turn one smooth 45° step
  around the current view centre (`Office.dondur`, `donusAcisi`, `DONUS_ADIMI`, `donusTusu`; ↺ turns the floor
  counter-clockwise on screen — OrbitControls' theta grows —, ↻ clockwise; a press during a turn adds a step). Only the
  camera's azimuth changes: the target (so `hedefiSinirla`), the zoom, the tilt and the side-panel view offset stay,
  and labels are projected as always. A turn is a `focusAnim`, so the frame cap draws it at the camera rate and nothing
  costs a frame at rest. Zoom and turn count as moving the camera (no re-fit on resize) until "Tümünü göster" re-fits
  the whole office, turns back to the default angle the short way (`sifirlamaAcisi`, `aciyiSar`) and turns the re-fit
  back on. **Camera depth** (2026-11-13, the owner's screenshot: dragged down, the lobby row and the bottom wing row were cut
  off along a straight line while their labels stayed): the orthographic camera was 73 units (`KAMERA` = [40, 46, 40])
  from its target with near = 0.1, so on a 144 × 108 floor a target at the back put the front rows up to 73 units
  behind the near plane. Now `kameraDerinligi(bounds)` (`web/ofis-sahne.js`) sets the camera's distance to the target
  rectangle's 3D diagonal + 20 (`KAMERA_YUKSEKLIK_PAYI` covers the height up to the wall board) and far to twice that,
  near = 1; `KAMERA` gives only the direction (`KAMERA_YONU`); OrbitControls keeps the distance (`minDistance` =
  `maxDistance`), also while a focus moves only the target. An orthographic view does not change with the distance.
  Merged geometry (`birlestir`) computes its bounding box and sphere from the merged vertices; the sun's shadow box is
  half the floor's diagonal (a square of max(W, D) left the corners without shadows) with the light moved back so no
  corner falls behind its near plane. The group sits in the HUD layer (`--z-hud`, below panels and popovers) and is
  hidden while a tab panel is open. **Moving around like a map**: left drag (one finger) pans across the floor, right drag (or Shift/Alt + left drag, a two-finger twist) turns the view (a full turn; the tilt stays within its limits); the arrow keys / W A S D pan one step (same guard as + / − / 0, and only while the focus is on the page itself or the scene — in the side panel the arrows scroll it). The camera keeps a symmetric frustum shifted by half the side panel in pixels (`setViewOffset`), so zooming never
  slides the view centre out of the visible area. The view centre is clamped to the floor's real bounds (common area and wing, `hedefiSinirla` in `web/ofis-sahne.js`), so every part of the office is reachable at any zoom. **Wheel and trackpad** are the scene's own (`Office.tekerlek`; OrbitControls' zoom is off except while a touch or the middle button is down, so phone pinch stays): a non-passive capture listener on the stage takes every wheel over the canvas, labels and HUD (never the side panel, overlays, cards or dialogs) and always `preventDefault`s, so a pinch never zooms the page; `tekerlekTuru` in `web/ofis-sahne.js` tells a trackpad pinch (wheel + ctrlKey, small deltas: `zoom *= exp(-deltaY * 0.015)`, ~2× per comfortable macOS Chromium pinch), a two-finger scroll (pans the floor like a map) and a mouse-wheel notch (deltaMode 1/2 or integer ≥ 50 px: one ×1.2 step); every zoom keeps the floor point under the pointer fixed (`imlecZoomHedefi`); Safari's `gesture*` events are mapped the same way; each counts as moving the camera. A one-time hint beside the zoom buttons ("Sürükle ya da iki parmakla kaydır · Sıkıştırarak yakınlaştır · Sağ tık ya da ↺ ↻: döndür", × closes it, remembered in localStorage; hidden on phones and touch screens). `web/ofis-davranis.js` (pure, no DOM)
  turns `/api/state` into actors with `niyetler(state, now, prev, {hafif, max_running_per_project, plan})` — real
  state first: a working agent never leaves its desk; "Evde" only on a certain quota. `web/scene.js` only draws them:
  `Office.setActors(actors, plan)` diffs by id (new ones come in through the lift, a changed place is walked along the
  plan's graph, `cikis` walks to the lift and leaves); `web/ofis-sahne.js` holds its pure helpers (facing, offsets,
  label text, walking, label separation). The title follows the model: haiku Stajyer (lanyard badge), sonnet Uzman
  (pin), opus Kıdemli (tie), fable Genel Müdür (jacket, glasses), codex Dış denetçi (clipboard), CEO (bow tie); helpers
  (subagents) are small; the grey "Çaycı" is decoration. Auditors (`denetci:<ad>`; the floor label is the short name
  only — "Codex", "GLM", "DeepSeek", the security reviewer "IT güvenlik uzmanı", the hakem "Hakem" — with the role in the label's
  tooltip `ipucu`, "GLM · Dış denetçi · ücretsiz", and in the card; own shell colour each, Codex teal, `denetciRenk`):
  at work (from `denetim`) they type at their desk and open the reviewed job (one away on a break walks back first;
  they appear at the desk, never through the lift; their labels float higher desk by desk, `etiket_yukseklik`, so the
  stack never covers a robot); `kota` → the "Evde · …" sign at the desk, `hata` → red at the desk; otherwise (hazir /
  bilinmiyor, not at work) they join the idle life like the kadro (owner decision 2026-11-12): lunch on a free canteen chair,
  the seeded breaks of `molaPlani` (not in hafif), else idle at the desk. While
  the hakem runs a "Hakem (sonnet) · bulguları tartıyor" actor types at the first desk of the Uzmanlar odası (opens the
  job); the security reviewer — shown as the **IT güvenlik uzmanı** — types at the IT güvenlik desk of the Sunucu odası
  (`denetciMasasi('guvenlik')`, plan "Sonraki iş (9)"), still only while it runs.
  **Kadro** (`kadro:<model>`; floor labels show the role only — `rolAdi` drops a Claude model in parentheses from the
  engine's `etiket`: "Genel Müdür", "Hakem", "blog · Kıdemli", "2 yardımcı"; Codex / GLM / DeepSeek keep their names; the
  model appears only in the character card and the tooltip): per Claude model, while no job or session of that model is in
  the office, its resident character idles — haiku/sonnet/opus in the "Ortak alan" lounge room (front row, armchairs
  well apart), the Genel Müdür (fable) at the desk of its own glass "Genel Müdür odası" (back row, between the meeting
  room and the CEO's room; fable-family work other than planning uses that desk — planning work, any model, the
  planning desk `PLAN_MASASI` of the Yazılım Müdürü's office, else its team's manager's desk; if the desk is ever
  taken the idle Genel Müdür uses its lounge seat); a hakem or security-reviewer call counts as its model family
  at work, so that family's kadro walks over as the hakem (to its Uzmanlar odası desk) / to the security desk and back (both at once: the other
  comes by lift); canteen
  in its seeded lunch slot — "hazır · iş bekliyor"; **idle life** (not in hafif, never while it eats; the Müdür keeps
  to its office):
  every `MOLA_ADIM_MS` (3 minutes; each actor's slots start at its own seeded phase, `molaDilimi`, so nobody switches
  in step) an idle kadro or idle session picks a seeded break (`molaEtkinligi`: mostly resting at its seat, else
  tea/coffee, a game or a short walk; `molaPlani` gives the places: the spot it held in the previous tick first, then
  the free one nearest its own seat, never farther than `MOLA_UZAK` along the walk; a short walk goes to one of the six
  corridor nodes nearest its seat): a drink means 25 s at the counter ("çay alıyor" /
  "kahve alıyor", poz `cay-al`), then a café table with the cup ("kahve içiyor · ortak alan"); games need company —
  the first two play table tennis (poz `pingpong`: bat swing, the ball bounces only while both stand there, none in
  hafif), the next two billiards (one leans with the cue, poz `bilardo`, the other waits; "bilardo oynuyor"), one
  more throws darts, the next sits on the bean bag; a busy, waiting, Kontrol or permission actor is never part of it.
  The demo's "Mola" scene forces the game break with its own `sahne.mola` (the server never sends it); `kota` → "Evde · …" sign at its seat, `hata`
  → red, else "durumu bilinmiyor". The first new worker of that model takes it over (`devral`: the scene walks the
  same body from the lounge to the desk), more workers come by lift; the last worker whose job ended walks back as the
  kadro instead of taking the lift. Decoration (tur `sus`, none in hafif, lowest label priority; a click on its body or
  its label opens its small card like any character):
  Çaycı; the "Yemekhane sorumlusu" (see Lunch for everyone); "Güvenlik görevlisi" beside the lift (turns to and nods at arrivals); "Sekreter" at the lobby reception —
  with decisions waiting (not yet answered from the page, `answer_sent`) she holds the paper (?) and walks to the CEO's
  door **once per new decision** (the count rose against the previous tick: `sekreterTasimasi`, several queue up; none on
  the first render; a new decision is a note not seen in the previous tick, so a card answered and another asked in the
  same tick still gets its trip). **Every duty trip lasts until arrival** (NPC audit 2026-11-12): its time is the walk
  along the plan at the scene's speed (`YURUME_HIZI`, `yurumeSuresi`: +15 % and 1.5 s) plus a stay — the Sekreter's
  trip (`SEKRETER_KALIS_MS` at the door, then the walk back before the next), a doctor / psychologist visit
  (`DOKTOR_KALIS_MS` beside the desk; one visit after the other), the guard's greeting (`GUVENLIK_KALIS_MS` at
  `lobi-karsilama`), each stop of the CEO's round (`CEO_DURAK_KALIS_MS`). The guard greets whoever comes out of the lift
  (`asansordenGelenler`: also staff arriving for their office hours; never an auditor, a helper, a hand-over or the first
  render). The Çaycı's duties: tea to a fresh ✓ (each job once) and at most every `EN_UZUN_ARA_MS` (20 min) to the desk
  of the job working longest — only one working at least `EN_UZUN_MIN_MS` (10 min, `enUzunCalisan(…, now, enAz)`);
  each trip lasts its walk plus `CAYCI_KALIS_MS`; otherwise its tea loop (`CAYCI_TUR_MS` = 6 min: brewing at the
  counter, then two stops on the common corridors). Off duty the duty staff stay close to their post
  (`personelMolasi`): the guard eats at his post ("nöbette yemek yiyor"), drinks water at the lobby's dispenser
  (`lobi-su`) or looks out of the lobby door — never farther, and no break while a queued job waits in the lobby or within
  a minute of a greeting; the Sekreter (no decision, no trip, no errand) drinks water at `lobi-su` and has lunch at her
  canteen chair `yemekhane-personel-0`; duty always wins. In hafif the duty staff (the Sekreter and the guard on shift, the Ofis doktoru inside its hours) stand still at their posts and every other staff member is
  hidden (the rooms stay; performance). **Lunch for everyone** (owner decision 2026-11-12): the canteen has a real chair for
  everyone who may eat at once (`yemekKapasitesi`: the CEO, the kadro, the auditors, an idle session per desk of every
  project, the facility staff, the social media team, the project residents; bands of eight chairs, growing downwards
  past the front row and reaching the floor's front edge; the CEO keeps chair 7, the Sekreter and the guard their two
  own chairs — the guard eats at his post); nobody stands outside or ends in a "+N". The chairs are stable (NPC audit
  2026-11-12): an eater keeps the chair it had in the previous tick for its whole meal, a new eater takes a free chair from
  its own seeded place (`sabitKoltuk`: collisions move on to the next free one), never by list position; queued jobs keep
  their lobby seat the same way. **Nobody eats the whole hour** (owner decision 2026-11-12,
  `ogleYemekte(id, now, sahne)`): each idle agent, kadro, auditor, the CEO and each staff member without a duty eats
  for a seeded 20–35 minutes of the window (scaled to its length), eight in ten starting in its first 0–4 minutes, the
  others at minute 20–25 (seeded by id and the date the window began, so an overnight window keeps one plan; an empty
  window such as `12:00-12:00` means no lunch); the rest of the hour is ordinary idle life (`molaPlani` /
  `personelRotasi`: games, the gym, a nap, tea, the terrace, a walk). Real work and duty always win; in hafif they eat
  the whole hour. At the canteen's far end the **Bulaşıkhane** (a tiled corner: a sink with a dishwasher, a plate rack,
  a tray trolley; `BULASIK_D` below the last band and the staff chairs, the room grows for it, never a seat less).
  The **yemekhane görevlisi** on duty (until 2026-11-14 one Yemekhane sorumlusu with office hours; now a shift team, see
  "Meals and the kitchen" below; hidden in hafif; `yemekhaneSorumlusu`, never on a seat): in the 15 minutes before a
  meal it sets things out at the serving counter (`yemekhane-servis`); at a meal it serves until the first eaters
  finish (20 minutes of a 60-minute window), then in each 2-minute slot collects the trays at a table's end
  (`yemekhane-masa-ucu-<band>`, poz `tepsi`) and carries them to the sink to wash (`yemekhane-bulasik`, poz `yikiyor`);
  outside the meals the counter or the Bulaşıkhane, a seeded break or, at night, a bed (`mutfakDisi`, see "Meals and the
  kitchen" below). Its card ("yemekhane",
  `yemekhaneKarti`): the team's shift rows, how many eat in the canteen now, today's meal windows and how far off lunch
  is (how many ate today is not known: no line). A staff label shows the name only — never "atanmış iş yok" or a similar idle
  text, not even on hover; a staff member on a real duty (`gorevde` or a symbol: the Sekreter's question or trip, the
  guard's greeting, a doctor / psychologist visit, a massage, the Çaycı's tea to a fresh ✓) gets a green pill with its
  state text (`is-gorevde`). The same green pill marks every character really at work (owner decision 2026-11-14; `calisiyorMu` in `web/ofis-sahne.js`): an agent typing on its running job, the CEO busy, a kadro member or the Genel Müdür in a hand-over (`gorevde` / carrying the file), a reviewer or the hakem reviewing; a question, a problem or a finish keeps its own colour, and the label goes back to normal when the work ends. Staff labels: one on duty (a question, a visit, a greeting: `gorevde`) ranks
  above idle agents' helpers, informational staff last. Staff without real work roam by a seeded **personality**
  (`personelKisiligi`: per-actor weights for the desk, tea, the game room, the gym, the terrace, a lounge chat, a walk;
  `personelRotasi` picks one per own 3-minute slot on staff-only spots no farther than `MOLA_UZAK` from its seat), so
  some stay put and others roam; duty always wins (visits,
  a project resident stays at its bay while a job of its project is open). Informational staff (tur `sus`, never
  workers): **Muhasebeci**, **İdari işler sorumlusu**,
  **İK ve İdari İşler Müdürü** (the İK staff NPC `sus:ik`, called "İK sorumlusu" before 2026-11-13; in the org chart it
  reports to the Genel Müdür and the support staff report to it) at their facility desks, and one **"<Proje> sorumlusu"** per team bay (at the manager's desk only while
  no worker needs it, else beside it). Every staff card (`karakterKarti` → `sekreterKarti`, `guvenlikKarti`,
  `cayciKarti`, `muhasebeKarti`, `idariKarti`, `ikKarti`, `projeKarti` in `web/ofis-sahne.js`) shows only what
  `/api/state` and the fetched data say, a missing value leaves its line out: Sekreter "kararlar ve takvim" (each
  waiting decision opens its card — oldest first, with its wait and risk —, today's started / finished counts
  `summary.tasks_today` / `finished_today`, the next schedule, model cards due a reminder); Güvenlik görevlisi
  "giriş-çıkış ve güvenlik" (the guard team's shift, today's jobs in and out, who is in the office, open security
  findings / yüksek-risk cards, "İletişim uyarıları" = `postofficeWarnings`, then "Ofiste olanlar" / "Otelde olanlar" —
  see "Who is where"); Çaycı "molalar" (who is on a break, the longest worker, time to lunch,
  today's top three spenders); Muhasebeci "harcamalar" (GET `/api/muhasebe`); İdari işler "ofis işleyişi" (`state.sunucu`
  + GET `/api/idari`: autostart, Obsidian access as `{sorun, python}` — the fix step names the python binary, never the
  vault's home path —, log size, limits; schedules); İK "çalışanlar" (the roster, this month
  per role from `/api/muhasebe`, pilots, kadro cards, the reviewers in short from `/api/kalite` `denetciler`); "<Proje>
  sorumlusu" "proje bilgisi" (description, folder name `projects[].klasor`, the summary of its note
  `OFIS/Projeler/<proje>.md` — rules, sensitive paths, the first lines of "Durup sorar" / "Asla yapmaz" / "Teslim" from
  `projects[].sorumlu` —, jobs now / queued / workflow, the last five finished, this month's spending). The page fetches a card's extra data when it opens and every 30 s while open;
  card buttons: open a job, a decision (`karar`: the Komuta masası's card, focused), the Kalite or Raporlar tab.
  **More idle life** (seeded, never for a working / waiting actor, none in hafif unless noted): the Müdür now takes the
  breaks too (rests at its office desk; work or quota keep it there); **the CEO's free time** (owner decision 2026-11-12,
  `ceoPlani`): an idle or dormant CEO with nothing open (no queue, no helper, no decision for the owner) splits its time in
  seeded 150-second slots (`CEO_PAYLARI`): about 30 % at its desk ("odasında"), 25 % an inspection round, 25 % a break
  (tea or coffee, the terrace or a game: `molaPlani` with the kind forced per entry), 20 % asleep in the **Dinlenme
  odası** (middle row right of the Uzmanlar odası, `DINLENME_W` = 15 base units wide — the common area is at least 56
  wide for it —: 20 beds, dim floor, a curtain; see "Night sleep") — first bed — only when dormant
  (idle: its desk instead; at night both sleep, see "Night sleep"); its label tells where it is ("uyuyor" only in bed, "odasında" only at its desk). Real state
  first: busy, waiting or with something open (a decision for the owner, a queue, a helper) it stays at its desk — never at
  lunch, on a round or on a break; with nothing open it eats in its lunch slot. Outside the office hours the free CEO
  sleeps, idle or dormant (owner decision 2026-11-13; before, an idle one stayed at its desk). hafif follows the same plan without the walks: the desk, or the bed in its
  sleep slots. Long-idle actors may nap there (`uyku`: a kadro with no work of its model for 30 min, an idle session idle
  15 min, idle auditors; at most the free beds; a nap, once begun, keeps its bed for 4–6 slots = 12–18 minutes,
  `UYKU_DILIM`; "dinleniyor · uyuyor", z's); `sigara` on the **Sigara odası** (an open terrace in
  front of the tea corner, off the left aisle, a whole cell; room for about eight (owner decision 2026-11-12): the smoking
  corner at its left end — a standing ashtray with four places, `sigara-yer-0..2` the agents', `-3` free (the guard now keeps to the lobby)
  (`-4` the roaming staff's) —, two benches with two seats each (`sigara-yer-5..8`, tur `bank`, "terasta oturuyor") and
  a place at the railing (`-9`, "terasta hava alıyor"); `SIGARA_AJAN_YERLERI` lists the agents' ones in order;
  plants and the railing; a cigarette with a faint smoke puff; "sigara molası"); `wc` (a door by a stable per-actor seed `wcKapisi`, inside — hidden, not clickable — for the first
  45 s of the slot, the walk included, then "ellerini yıkıyor" at the sink until 75 s, then back at its seat); `spor`
  (the gym's machines with their own movement, "spor yapıyor"; after 110 s sometimes the shower, hidden like the WC,
  "duşta"); `masaj` (only after a long working day: a
  kadro whose model's jobs ran over 2 h today, `calismaSuresi`; "masajda", the Masajcı stands beside the table). More
  staff (tur `sus`, informational, hidden in hafif except the doctor): the 14 members of **Sosyal medya ve tasarım** (cards: their
  role, area, "Şu an atanmış iş yok", the projects they would serve — they have no work yet); **Ofis doktoru** (Revir;
  card "ofis sağlığı": today's stuck jobs, silent / permission-waiting sessions from the message delivery's list,
  workers in "hata", the newest rows of the server's error record `state.olaylar` = `Olaylar.son(5)`; nothing wrong →
  "Ofis sağlıklı" with what was checked; one visit to the desk of each newly stuck or red-marked agent,
  `doktorZiyareti`, the agent is never moved); the **IT ekibi** (Sunucu odası: the IT sorumlusu and two IT uzmanı on a
  rotating 8-hour shift, exactly one on shift at any time — see "Sunucu odası"; card "IT ekibi": the shift, then GET
  `/api/sistem` — the status, the process groups as totals, the suggestions, the domains; in hafif only the person on
  shift, standing still); **Ofis psikoloğu** (card "iş yükü": open jobs running over an hour, a
  Kontrol on its second run ("Kontrol 2. kez çalışıyor"), a Kontrol that really failed (`kontrol_sonuc` `kaldi`: "bir
  kez kaldı" / "2 kez kaldı"; an escalation is named only when a job escalated from it exists), ≥ 80 % of budget or calls
  ("bütçenin %90'ı": `yuzdeMetni` / `iyelikEki` give the suffix), two devam rounds, a workflow's second review round —
  each with its rule-based advice; nothing → "Ekip rahat"; one visit on a job's second Kontrol attempt; tasks carry `kontrol_deneme`,
  `kontrol_sonuc`, `devam` from the note, display only); **Masajcı** (card: the longest working time today per role, who
  is on a table now). Screenshots: `?kart=<actor id>` opens a card at load,
  `?demo_mola=<break>&demo_ceo=<state>` force a break / the CEO's state in the demo.
  The CEO's inspection round (`ceoTuru` = the round slots of `ceoPlani`: about one in four 150-second slots; up to two
  team bays from a seeded one → the auditors' room or the Uzmanlar odası → its own door, `ceoTurDuraklari`; each stop
  lasts the walk there plus `CEO_DURAK_KALIS_MS`, a round may run into the next slots; "ofisi dolaşıyor") only when idle
  or asleep with nothing open, never outside the office hours. The tea corner has three round tables with
  stools (idle sessions rest there). Room names are small HTML labels at each room's
  front-left corner (`odaEtiketleri`; hidden under actor labels, on a phone only when zoomed in). Quiet actors (idle
  kadro, idle auditors, decoration, queued jobs) get a small name-only label ("Haiku · Stajyer", "GLM") until hovered
  or zoomed in; labels stay next to their robot: `etiketleriYerlestir` (`web/ofis-sahne.js`) places them by priority
  (`etiketOnceligi`: hovered, question / permission / problem, really at work, the CEO, … idle staff and decoration last;
  one sort per frame, all sizes read before any write), stacks an overlapping one above with a 2 px gap at most 48 px,
  and folds the rest of a crowd into a small "+N" chip at the right of the label they first overlap (hover or a
  click / tap lists the names; a reused DOM pool, no draw call); a working, waiting or hovered label is never folded —
  it keeps stacking (the owner, 2026-11-14: names piled up in the meeting room and tea corner). The layout is drawn in base units
  and scaled by `OLCU.K` = 1.5 (the owner, 2026-11-12: a roomier floor; corridors `GAP` and the spine `OMURGA` 4 base units;
  furniture-bound spots — helpers, `yan`, tea stools — keep their distance); every
  area has its own floor colour (`ROOM_TINT`) over a darker base floor. Labels are colour-coded by group
  (`etiketGrubu` → `.grup-ajan` indigo: AI workers, kadro, helpers, CEO; `.grup-denetci` teal: auditors, security
  reviewer, hakem; `.grup-personel` warm brown: staff NPCs; room names muted slate without a box); the state text keeps
  its status colour (a green pill = really at work); a small "Etiket renkleri" legend (closed by default, hidden on a phone) explains them.
  Stacking: a z-index scale in CSS tokens (`--z-scene` 0 < `--z-labels` 1 < `--z-hud` 5 < `--z-overlay` 15 <
  `--z-header` 20 < `--z-scrim` 30 < `--z-modal` 40 < `--z-toast` 50); the labels layer is its own stacking context,
  and while a tab panel is open (`body.panel-acik`) the labels and the legend are hidden and not placed. A low outer wall
  (1.2 high with windows on the far sides, a ledge on the near sides, a gap at the entrance) frames the floor; the
  camera is a little steeper (`KAMERA`) and the fit tighter; the greeting folds into a pill after 6 s (click toggles,
  remembered). Clicking **any** character (also decoration and "+N") opens its **info card** near the click
  (`karakterKarti(actor, state, now, {aktorler})` in `web/ofis-sahne.js`, laid out by `kartDuzeni` and drawn by the one
  card component `kartIcerigi` in `web/app.js` with textContent — titled sections, tables, status bars, see "Character
  cards — one component" in [`sayfa.md`](sayfa.md) —, popover
  layer `--z-overlay`, closed by Esc / a click outside / a tab panel): role, model, project and state; a job — title,
  step, time, spending · tokens / budget, "Kontrol: sunucu şu an çalıştırıyor" only while `kontrolde` (nothing is claimed for a running job), helpers, "İşi aç"; an idle kadro — what the role does, its
  last finished job ("İşi aç"), today's jobs and spending, "Model durumu" (the model's row, not its own state); a helper — its task and "Ana işi aç"; auditors /
  hakem — role, status, the job under review, Codex's last review, "Karnesi: Obsidian'da Karne/Denetciler"; the CEO —
  tool, queue, today's cost, "Komuta masasını aç"; staff — a friendly role line (the secretary: "<sahip>'e N soru
  bekliyor", "Kararları aç"); "+N" — a team's "+N" lists exactly the engine's hidden jobs (`gizliler` with their notes), the lobby / helpers found in the state. The open card is rebuilt only when its content changes (clicks and focus survive the 1 s refresh). Nothing opens directly any more. Labels are textContent only; at the default zoom only the
  CEO, a question / permission / problem, working agents and an agent at home ("Evde · …") show their state text, the others their name (full text
  on hover or when zoomed in); presses over a label go on to the camera and the wheel over it is the scene's. A job without a known model
  takes its tier's default for its title (queued jobs). Desks: working agents first (a free manager's desk is their
  fallback before "+N"), an "Evde" sign before idle agents, and idle agents take no free desk.
- **NPC audit 2026-11-12** (the owner: "act like one brain"; `test/test_npc.py` simulates whole days with the scene's
  walking emulated, `test/npc/`):
  - **Only real Claude work becomes a robot.** A workflow's approval step (katman `onay` / model `deniz`, or step kind
    `onay`: `onayAdimi`) is the owner's decision — the Sekreter's paper and the decision card, never a robot, a kadro, a title
    or a tier default, no row in "Şu an iş başında". A review the panel runs (`inceleme_yurutucu` codex, or the model
    `codex` / `heyet` bin/akis.py writes: `panelIncelemesi`) never becomes a robot in the lobby or a ✓ at a team desk and
    gets no tea; only the auditors and the hakem show it. A Claude review's ✓ or stuck state stays where it was done
    (the QA odası or the Analist odası).
  - **The page reads the server record** (bin/state.py): `tasks[].tier`, `model` and `step_kind` come from the job's
    server record when it has them (the note otherwise); `state.katmanlar` = the effective mapping (global tiers,
    project overrides, running pilots) drives the fallback model of a job without one (`katmanModeli`) and the kadro
    card's "Görevi" (`kadroGorevi`); `state.son_rapor` = the newest group report; `state.sahne.mesai`.
  - **Hand-overs.** A worker new to the floor takes its idle kadro over (`devral`); a queued job starting from the lobby
    already has its body (the lobby robot walks to its desk), so the kadro walks out by the lift ("çıkıyor") — nobody fades
    in place. The hakem right after the security reviewer of the same family takes over that body. A helper (subagent)
    appears beside its parent and is gone after its ✓ (never the lift).
  - **No walking through furniture.** `mobilyaKutulari(plan)` = the desks, the canteen's band tables, the tea and café
    tables, the game tables, the lobby's low table, the covered WC / shower blocks (the scene draws them at these sizes:
    `MASA_OLCU`, `PATRON_MASA_OLCU`); `ofisPlani` re-routes every edge that would cross one around its corners
    (waypoints `gecit:<a>><b>:<i>`, tur `gecit`, never a break spot).
  - **Office hours** (optional, `ofis.json` `ofis_sahnesi.mesai`, default `08:30-18:30`; `""` or `"yok"` = none; read by
    bin/state.py `mesai()`, `mesaiMi` / `personelSaati` on the page; both follow the work calendar below): outside them the office staff (Muhasebeci, İdari,
    İK, the social media team, the doctor, psychologist, Masajcı, Çaycı; a project resident unless
    its project has an open job) stay at the **Otel** (see "The Otel" below; before 2026-11-14 they went "home") — each
    walks there at a seeded time within ±20 min of the end ("otele gidiyor"; `personelGunu` = its seeded arrival and
    leave) and walks back in through the lobby's entrance in the morning, greeted by the
    guard. **The doctor has no night call** (plan "Sonraki iş (8)", owner decision 2026-11-12): it goes home like the others even
    while a job is stuck or red; past its leave time (or walking out) it starts no new visit, a visit it is on ends
    first, then it walks to the lift; coming in
    in the morning it visits the cases still open. The guard, the Sekreter and the IT team are on rotating shifts (see
    "Nöbet düzeni" below). At night nobody plays, smokes or works out: idle agents rest or nap. The demo sets `mesai: ''`.
  - **The work calendar** (the owner, 2026-11-13: "hafta sonu ve resmî tatiller tatil"; `web/ofis-davranis.js`, pure, office
    zone dates): `gunTuru(x)` → `{is, tur: 'is' | 'hafta-sonu' | 'tatil', ad, kisa}`, `isGunuMu(x)`, `tatil(x)` /
    `tatilAdi(x)`, `sonrakiIsGunu(x)`, `sonrakiIsSaati(ms, dk)` / `oncekiIsSaati(ms, dk)` (x = a moment, a day or
    `{yil, ay, gun}`). Holidays: the fixed ones of Law 2429 for any year (`SABIT_TATILLER`: 1 Ocak, 23 Nisan, 1 Mayıs,
    19 Mayıs, 15 Temmuz, 30 Ağustos, 29 Ekim) and Ramazan / Kurban Bayramı per year (`DINI_BAYRAMLAR`, 2026–2028, from
    Diyanet's "Dini Günler" tables, source in the comment; add a row each year — a missing year keeps the fixed
    holidays). **Arife is a work day** (officially its afternoon is off from 13:00; a half day would need a second leave
    time per staff member — kept simple on purpose). Effect, visual only — the server's dispatcher, schedules and the
    morning summary know nothing of it: on a weekend or a holiday `mesaiMi` is false (the night logic for the staff: no
    games, the corner line shows; the agents are awake by day since 2026-11-14 — see "Days off and evenings awake") and `personelSaati` says `evde` for every day-hours person (managers, the facility staff, the
    social media team, the office services, the project residents unless their project has an open job, the decorative
    people), so the org chart, the guard's card, `kimNerede` and `dekorEkibi` follow; their return is the next work
    day's arrival (`sonrakiIsSaati`). The Sekreters (`NOBET_EKIPLERI.sekreter.isGunleri`) work only the shifts that
    begin on a work day (`ekipVardiyasi`, `nobetPlani(…, ekip)`): on a weekend or a holiday nobody sits at reception, the
    decision cards still work on the page, only nobody walks them to the CEO's door; Friday's evening shift leaves at
    00:00, Monday's night shift comes at 00:00. The guards and the IT team keep their 24/7 rotation every day. Agents and
    real work are never affected (a job on Saturday brings its character exactly as after hours). Without office hours
    (the demo) there is no calendar either. Day words (`gunSozu` in `web/ofis-sahne.js`): "yarın", a weekday for two to
    six days ahead with only a weekend between ("döner pazartesi 08:10"), the date with its weekday when a holiday lies
    between or further ("döner 30 Ekim Cuma 08:10"), a weekday for the last six days ("çıktı cuma 18:22"). The Sekreters'
    card on a day off: "Nöbette: kimse yok · hafta sonu" / "· resmî tatil (29 Ekim)" and "Sonraki değişim: pazartesi
    00:00 · …". Tests: `WorkCalendarTest` in `test/test_npc.py`.
  - **Nöbet düzeni** (plan "Sonraki iş (8)", owner decision 2026-11-12; `web/ofis-davranis.js`): the **Güvenlik görevlisi** and
    the **Sekreter** are three people each (`GUVENLIK_EKIBI`: `sus:guvenlik`, `sus:guvenlik:1`, `sus:guvenlik:2` — "1.–3.
    güvenlik görevlisi"; `SEKRETER_EKIBI`: `sus:sekreter`, `:1`, `:2` — "1.–3. sekreter"; every member's label is
    "Güvenlik görevlisi" / "Sekreter") on the IT team's rotating shifts. **One helper for all three teams**
    (`NOBET_EKIPLERI` = {sunucu, guvenlik, sekreter} with `arkadas` — only the IT team keeps the colleague whose day
    shift just ended): `vardiya(now, sahne)` (the shift: gece 00–08, gündüz 08–16, akşam 16–24 in the office zone;
    person `(k + D) mod 3`; `itVardiyasi` is the same function), `nobetEkibi(ekip, now, sahne)` (each member nobette /
    iceride / evde; `itEkibi` = `nobetEkibi('sunucu')`), `nobetPlani(kisi, now, sahne)` (a member's current, last and
    next shift) and `nobetCikisi` (the walk home: to the lift, gone only on arrival — the walk plus `NOBET_CIKIS_PAYI_MS`,
    carried in `cikis_bitis`). Exactly one guard and one Sekreter are on shift at any minute (`nobetci: true`,
    `vardiya`, `vardiya_son` on the actor); a second person of a team is on the floor only in the minutes after a change:
    the incoming one comes out of the lift, the outgoing one finishes the leg it is on (the guard a greeting; the
    Sekreter her leg to the CEO's door or an errand; the trips she has not begun go to the one coming on shift, who waits
    at reception until the door is free again — `tasimaAni`, the `bekle` of `sekreterTasimasi`) and then walks to the
    lift ("nöbeti devretti · eve gidiyor"). The guard on shift keeps every duty: the post `lobi-nobet`, greeting arrivals
    (not a shift colleague arriving for its own shift; never while the outgoing one still holds `lobi-karsilama`), the
    lobby breaks and lunch at his post. The Sekreter on shift keeps the decision trips to the CEO's door, the answer and
    report cues — also at night (the role's memory, `karar_notlari` / `raporlar`, passes from the one on shift in the
    previous tick, so a change never re-sends a trip); with nothing to do she sits at reception; breaks and lunch only
    inside the office hours. Labels: "Güvenlik görevlisi" / "Sekreter" with "nöbette" at night ("girişte" /
    "resepsiyonda" by day). hafif: only the person on shift of each team, standing still at the post. Cards: the
    Sekreter's and the guard's start with the team's shift rows (`nobetSatirlari(ekip, st, ms)` — "Nöbette", "Nöbet
    bitişi", "Sonraki değişim"; the IT card uses the same, `itEkibiSatirlari`). The Çaycı and a Sekreter errand never
    share a desk's side spot (the errand waits for the tea delivery; the Çaycı skips a desk an errand is heading to).
  - **Who is where** (`kimNerede(state, now, aktorler)`, pure, from the clock and the rules only — office hours with each
    one's seeded arrival / leave, the shifts, a resident staying for its project's open job, a staff member the engine
    drew on a duty outside its hours; the agents' state from the actors): `{ofiste, evde, mesai, donus}` with every staff
    member and every agent character (`{id, ad, grup, durum: ofiste | nobette | cikiyor | evde, metin, gelis, cikis,
    donus, bitis, vardiya}`). The CEO, the kadro and the auditors never go home ("ofiste" with their state: çalışıyor,
    dinleniyor, uyuyor, molada, yemekte, kota doldu, hata). The guard's card lists "Ofiste olanlar" and "Otelde olanlar"
    **grouped** (the owner, 2026-11-12: ~45 lines became ~13 at night; `kimNeredeSatirlari(k, ms, tz)` in `web/ofis-sahne.js`,
    pure): in the office "CEO: uyuyor", "Kadro: Stajyer dinleniyor, Uzman uyuyor, Kıdemli çalışıyor, Genel Müdür dinleniyor",
    "Denetçiler: Codex dinleniyor, GLM uyuyor, …", the people on shift "Nöbette: Güvenlik görevlisi (2.), Sekreter (1.),
    IT sorumlusu · 08:00'e kadar" (`saatYonelme`: the time's dative), a shift team's colleague off shift "IT (nöbet
    dışı): 1 kişi", the other staff by department "Sosyal medya ve tasarım: 14 kişi" (departments: Sosyal medya ve
    tasarım; Muhasebe, İK, İdari işler; Ofis hizmetleri — Çaycı, Yemekhane, doctor, psychologist, Masajcı; Proje
    sorumluları); at home each department with a count and one return range "Sosyal medya ve tasarım · 14 kişi · döner
    08:13–08:48" (a shared "yarın" said once) and each shift team "Güvenlik (2 kişi) · sonraki vardiya 08:00 / 16:00".
    A group row carries `uyeler` — every member's full line as before (`kimNeredeMetni`: "Muhasebeci · otelde · çıktı
    18:22 · döner yarın 08:35", "2. sekreter · nöbette · 16:00–24:00", "Çaycı · ofiste · geldi 08:27") — and a stable
    `anahtar`; the page (`kartGoster` in `web/app.js`) shows it as a `details.karakter-kart-grup` (summary = the group
    line, a list of the members; textContent only) and keeps a group the viewer opened open across the card's rebuilds.
  - **The corner line outside the office hours** (`mesaiDisiSatiri(st, now, {kisa})` in `web/ofis-sahne.js`; `#mesai-disi`
    in the HUD layer at the scene's bottom-right): "Mesai dışı · N kişi otelde · 08:30'da dönüyorlar" (N = `kimNerede`'s home
    list, the time = the office hours' start with its suffix, `saatBulunma`); a phone shows "Mesai dışı · N evde ·
    08:30". With the work calendar: "Hafta sonu · N kişi otelde · pazartesi 08:30'da dönüyorlar", "Resmî tatil (29 Ekim) ·
    N kişi evde · cuma 08:30'da dönüyorlar", and after a Friday "Mesai dışı · … · pazartesi 08:30'da dönüyorlar" (a
    phone: "Hafta sonu · N otelde · Pzt 08:30"; an ordinary evening keeps no day word). Hidden inside the office hours,
    without office hours and while a tab panel is open; recomputed at most every 10 s; a click opens the card of the
    guard on shift.
  - **Night sleep** (`GECE_UYKUSU`, owner decision 2026-11-13; `uykuVaktiMi`): from the end of dinner (`AKSAM_YEMEGI`, 20:00 —
    or the office hours' end when later) until the office hours' start, every day (a weekend or a holiday too; see
    "Days off and evenings awake" below) every agent character in the office without real work — the free CEO (idle or dormant; bed 0), the idle kadro
    (the Genel Müdür too), the idle auditors (Codex, GLM, DeepSeek, Antigravity, …), the idle sessions — walks to its
    own bed in the Dinlenme odası and sleeps ("uyuyor", lying; `molaPlani` with the break forced to `uyku`: the bed it
    held stays its own, else the first free one; 20 beds, one sleeper each; with more sleepers the rest rest at their
    seat / the tea stools). In hafif too (places only). The people on shift stay awake at their duties (the guard, the
    Sekreter with her trips to the CEO's door, the IT person on a server warning) — except the kitchen pair on duty, who
    have no night work and sleep here too (beds from 19 down, see "Meals and the kitchen"); the day staff are at the Otel. A real job,
    review, hakem or security call takes the body from the bed to the desk (`devral`) and it walks back to bed after;
    an asleep Genel Müdür takes no file in the hand-over chain. The hakem and the security reviewer are drawn only
    while they run; `kimNerede` no longer counts the undrawn security reviewer as "çalışıyor" (bug: the guard's card
    said "Güvenlik denetçisi · ofiste · çalışıyor" at night with no work) — it is "dinleniyor", at night "uyuyor".
    **The room**: two rows of ten beds (`YATAK_OLCU` 1.3 × 2.6) facing each other across an aisle, the back row with the
    door's gap in its middle; an aisle node `dinlenme-gang` and a foot spot `dinlenme-yatak-<i>-ayak` (tur `ayak`) per
    bed, so a sleeper walks the aisle and never over another bed (each bed is a box in `mobilyaKutulari`); the front
    row's beds turn to the curtain (`yatakAcisi`). The beds are static furniture merged per material
    (`statikBirlestir`): 20 beds cost no extra draw call. Tests: `NightSleepTest` in `test/test_npc.py`, the room in
    `test/test_ofis_plani.py`.
  - **The Otel** (the city, step 1 — the owner, 2026-11-14: "otel gibi düşün; ofis dışındaki kişilerin kaldığı yer"; the
    long-term idea — a small city with a pub, a cinema, a restaurant, a café, a street — is not built yet). A separate
    two-storey building in front of the lobby, outside the floor (`plan.otel` = {x, z, w, d, kapi, katlar}, never in
    `plan.odalar`: the floor's rooms stay inside `genislik` × `derinlik`; `OTEL_OLCU` = 26 × 10 base units, 9 from the
    floor's front edge (7 before the street), so its 4.4-unit height never hides the lobby from the default angle). The path: the lobby's
    back door → `lobi-giris` (the lobby's front, the outer wall's entrance gap) → `otel-yol` (tur `dis`) → `otel-kapi`
    (its back wall, facing the office) → `otel-hol` → one room per guest `otel-oda-<i>` (tur `otel-oda`, `OTEL_ODA` =
    72 in an 18 × 4 grid since the kitchen teams, 64 before). **Who stays there**: the people who used to "go home" — `otelKadrosu(projeler)` in room order:
    the four managers, the 14 of the social media team, the facility staff (Muhasebeci, İdari, İK, doctor,
    psychologist, Masajcı, Ar-Ge uzmanı), the Çaycı, the three of each shift team (IT, guards, Sekreters, yemekhane
    görevlileri, aşçılar — since 2026-11-14) and one sorumlu per project: 41 + T guests, 31 − T spare rooms (≥ 8 spares
    up to 23 projects).
    The agents (CEO, kadro, auditors, idle sessions) still sleep in the office's Dinlenme odası at night ("Night
    sleep" above; the coordinator's first brief sent them to a dorm — the owner changed the design the same day). The
    decorative people stay as before (hidden outside their hours, no walk). **How** (`oteleYerlestir`, a pass at the
    end of `niyetler`, never in hafif): one walking out (`cikis`: its leave after its hours, a shift handed over) walks
    to its own room instead of the lift ("otele gidiyor", `otel_varis` = its walk there, carried tick to tick); one the
    rest of the engine does not draw (outside its hours, a day off, off shift) is drawn at its room with `otel: true`
    — "otele gidiyor" until `otel_varis`, then poz `otelde` with "otelde · uyuyor" from 22:00 to 08:00 (`OTEL_UYKU`)
    and "otelde" otherwise (`otelMetni`). `nobetCikisi` ignores a guest (no second walk out). In the morning the engine
    draws it at its desk again and the same body walks back through the entrance; the guard greets it
    (`asansordenGelenler` counts a guest of the previous tick that is now at work). The scene hides whoever stands in
    a room (`otelOdasiMi(a.yer)` and not walking: robot and label, like the WC), so the guests cost no draw call; a
    page opened at night places them there directly (no lift). Texts: the guard's card "Otelde olanlar" ("kimse otelde
    değil"), "Muhasebeci · otelde · çıktı 18:22 · döner yarın 08:35", "… (N otele gidiyor)"; the corner line "Mesai
    dışı · N kişi otelde · 08:30'da dönüyorlar" (phone "· N otelde ·"); the Şema's badge "otelde"; the "döner
    pazartesi 08:10" logic is unchanged (`kimNerede` still calls them `evde` internally). **Drawing**
    (`Office.buildHotel`): its own slab and lip, a paved path from the entrance gap, a closed block (walls, a band
    between the storeys, a roof with an overhang), windows on the two faces the camera sees, a glass front door, the
    back door and two plants — no rooms or beds inside (nobody is drawn there). Only the office's own materials (outer
    wall, wall cap, bed frame, slab, glass), merged by `statikBirlestir` into existing draw calls: **the hotel adds no
    draw call**; nothing casts a shadow. The room label "Otel" (`odaEtiketleri`). **Camera**: `fit()` frames the office only
    (`this.cerceve`); `this.bounds` (the pan clamp `hedefiSinirla`, `kameraDerinligi`) includes `plan.dis` (the path
    and the hotel), and the sun's shadow box covers the farthest corner of both. Tests: `OtelTest` in
    `test/test_npc.py` (rooms and spares, the path, the evening and morning walks, hafif, texts, draw calls,
    hidden guests, the pan bounds); the shift and office-hours tests now expect the walk to and from the hotel.
  - **The street** (the city, step 2 — owner decision 2026-11-14; `sokakDuzeni`, `plan.sokak`, `SOKAK_OLCU` in
    `web/ofis-davranis.js`; `Office.buildStreet`): across the yard between the floor's front edge and the Otel, past
    both ends of the floor (`UC` = 4), a sidewalk on the office side (`kuzey`, 2.6 wide), a two-lane road (`yol`, 3.6,
    a dashed centre line), a sidewalk on the hotel side (`guney`), a curb along each, a zebra crossing (`gecit`, 3.2
    wide) centred on the office–Otel path, street lamps and trees alternating every 7.5 on the curb strips (0.4 from the
    road), none within 3.6 of the crosswalk or near the ends. The yard grew from 7 to 9 base units for it. The staff's
    walk lobi-giris → otel-yol → otel-kapi is one straight line in the crosswalk's middle (`otel-yol` lies on the
    road): everyone walking between the office and the Otel crosses there. The hotel's paved path is drawn only off
    the street (office → north sidewalk, south sidewalk → hotel). Only the office's existing materials (the server
    room's metal for the asphalt, light grey sidewalks, the wall cap's curbs, white markings, the dark grey lamp posts
    with the ring light's warm lamp, wood trunks and the plants' leaves): merged by `statikBirlestir`, **the street
    adds no draw call**; nothing casts a shadow. `plan.dis` (the pan bounds, `kameraDerinligi`, the sun's shadow box)
    spans the street; `fit()` still frames the office only. **Pedestrians** (`yayaRotalari`, `yayaKonumu`,
    `yayaSayisi`, `Office.setYaya` / `yayaKonumla`): anonymous passers-by on four closed loops — an oval on each
    sidewalk (two walking lines each, 0.55 and 1.55 from the building-side edge, clear of the lamps and trees) and a loop
    on each side of the crosswalk that crosses the road only on it; every second group walks its loop backwards, at a
    seeded 0.75–1.05 units a second. 8 by day (07:00–20:00), 5 from 20:00 to 23:00 and from 06:00 to 07:00, 2 at night,
    none in hafif (`YAYA_EN_COK` = 10). `dekorEkibi` carries the number as the list's `yaya` property (the page's one
    `setDekor` call brings it, app.js unchanged). Scenery only: no label, no card, not clickable (`raycast` is a no-op),
    never in `kimNerede`, the Şema or the Çalışanlar list. Drawn as ONE InstancedMesh for the bodies (the decorative
    people's lower-detail body at 0.8 × a character, a coat colour each) and ONE for the legs (two swinging instances
    each): **two draw calls**, no shadows, `frustumCulled` off; they move with the scene's frames (no faster frame
    rate: at rest they step at 9 fps). Measured (walking sequence): **610 at the 16:00 change** (608 before), 633 at
    lunch (631), 574 in the evening walk-out (572); from scratch 579 at 10:30 (577), 583 at 16:00 (581), 358 at 03:45
    (356), 348 in hafif (unchanged). Tests: `SokakTest` in `test/test_npc.py` (the layout and the crosswalk walk, the
    pedestrians' sidewalks / crosswalk / lamps / trees / furniture / loops / both directions, the counts by time of day
    and hafif, their two draw calls, not picked, the camera and shadow bounds).
  - **Days off and evenings awake** (owner decision 2026-11-14, Saturday 10:22: "ofiste olanlar halen uyuyor";
    `tatilGunduzu`, `serbestZaman`, `uykuVaktiMi` in `web/ofis-davranis.js`): the agents (the CEO, the kadro, the
    auditors, the idle sessions) sleep only from dinner's end (20:00) to the office hours' start. On a weekend or a
    holiday inside the office hours' clock window (08:30–18:30 by default, the work days' wake-up and evening times),
    and on every evening from the office hours' end until 20:00, they are awake in the common areas: `molaPlani` with
    `tatil` — no nap, no distance limit, resting turns into a game or a chat now and then (`sohbet`: the Ortak alan's two
    standing places, which are the roaming staff's by day), plus the usual tea, café, games, gym, terrace and walks. One
    whose own seat is a work desk (the auditors, the Genel Müdür, the CEO) and who got no leisure spot sits on a tea
    stool ("kitap okuyor" or "dinleniyor", seeded per slot), never at its desk; a kadro member rests in its Ortak alan
    armchair; in hafif too (places only). The CEO has no round then. Texts: "hafta sonu · dinleniyor", "tatil · masa
    tenisi oynuyor", "akşam · sohbet ediyor" (`tatilSozu`; "hazır · " / "boşta · " dropped); never "uyuyor" by day.
    Real work wakes and moves a character exactly as before (a job takes the body to its desk, `devral`). The Otel's
    guests stay at the Otel on days off (unchanged). The security reviewer's undrawn text in `kimNerede` follows
    `uykuVaktiMi`. The corner line ("Hafta sonu · N kişi otelde · …") counts the Otel's guests only and never claimed
    that anyone sleeps: unchanged. Tests: `NightSleepTest` (Saturday 10:30 awake, not in beds, not at desks, in hafif
    too; a holiday; Saturday 08:25 asleep, 08:45 awake, 18:45 awake, 20:30 asleep; a real job on Saturday takes its
    character to its desk).
  - **Meals and the kitchen** (owner decision 2026-11-14; `ogunPencereleri`, `yemekPenceresi`, `ogun` in
    `web/ofis-davranis.js`): three meals in the Yemekhane, seeded per person and day (no randomness), unique chairs
    (`yemekKoltugu`), real work first (a working character never eats; the Sekreter not while a decision waits; the IT
    person on shift not during a warning). Windows: on a work day breakfast from 30 minutes before the office hours (or
    the 08:00 shift change) until 45 minutes into them, lunch as before (`sahne.ogle`, `ogleYemekte`), dinner
    `AKSAM_YEMEGI` 19:00–20:00; on a weekend or a holiday breakfast 09:00–10:00, lunch 12:30–13:30, the same dinner
    (without office hours, the demo: lunch only, as before). Who: the agents ("kahvaltı ediyor" 15–20 min starting in
    the first 25 minutes of their breakfast window — after waking —, "öğle yemeğinde", "akşam yemeğinde" 20–25 min
    from 19:00–19:20); the day-hours staff a breakfast right after their own seeded arrival (`personelGunu().gel`: they
    walk from the Otel to the canteen, then to their desks) and lunch as before, no dinner (they are at the Otel by
    then); the people on shift breakfast and dinner **one at a time** in `NOBET_SOFRA_SIRASI` (Sekreter, IT, guard,
    yemekhane, aşçı: 12 minutes each from 08:00 on a work day / 09:00 on a day off and from 19:00) — the guard eats at
    his post ("nöbette · akşam yemeğinde"), the others on the two staff chairs; the IT person on shift still takes no
    lunch. Bedtime moved to 20:00 for it (above). **The kitchen** (what existed: the canteen's serving counter
    `yemekhane-servis` and the Bulaşıkhane at its far end — a sink with a dishwasher, a plate rack and a tray trolley;
    no cooking spot): the same strip got a stove with four burners and a tall fridge at its free right end
    (`r.bulasik.ocak` / `.dolap`, nodes `yemekhane-ocak` / `yemekhane-dolap`, tur `servis`, facing the back wall), drawn
    in the dishwasher's, the trolley's and the rack's materials — merged by `statikBirlestir`, **no extra draw call**.
    **The kitchen teams**: the Yemekhane sorumlusu became three **yemekhane görevlisi** (`YEMEKHANE_EKIBI`,
    `sus:yemekhane`, `:1`, `:2`) and three **aşçı** joined (`ASCI_EKIBI`, `sus:asci`, `:1`, `:2`), both in
    `NOBET_EKIPLERI` on the guards' 24/7 rotation (one of each on duty at every minute, weekends and holidays too; the
    off-shift ones at the Otel; a change walks the outgoing one to the Otel, `nobetCikisi`). The server serves every
    meal (`yemekhaneSorumlusu`); the cook (`asciPlani`) cooks from 45 minutes before a meal to its end at the stove
    (poz `yikiyor`, "öğle yemeğini pişiriyor", "kahvaltıyı hazırlıyor") with a moment at the fridge ("malzeme alıyor")
    in each 2-minute slot, and otherwise cleans the stove or tidies the fridge. **Between meals** (owner decision
    2026-11-18: "aşçı gece hep mutfakta duruyor … NPC'ler biraz daha akıllı olabilir"; `mutfakDisi`, shared by the cook
    and the yemekhane görevlisi): at night (`uykuVaktiMi`, from 20:00 until the office hours' start, unless their meal's
    prep — 45 / 15 minutes — or the meal has begun) both sleep in the Dinlenme odası ("uyuyor"; the bed held in the
    previous tick, else the free bed with the highest number, so the agents filling from bed 0 rarely meet them; no
    free bed: dozing on the staff chair, "kestiriyor"), and the prep wakes them before breakfast; by day, per own
    15-minute slot (`MUTFAK_MOLA_MS`, seeded per member) two slots in five start with a 9-minute break
    (`MUTFAK_MOLA_KALIS_MS`): tea at `cay-ocagi-personel-2` ("çay molasında"), a chat at `ortak-alan-sohbet-<i>`
    ("sohbet ediyor") or a corridor walk near the canteen ("biraz dolaşıyor"), on the plan's paths, then back to the
    kitchen / counter. So food is always cooked and served; no
    "hazır yemek" fallback is needed (both posts can never be empty). Page: the Şema lists "Aşçılar (3) · nöbette: 2.
    aşçı" and "Yemekhane (3)" under İK ve İdari İşler Müdürü → Ofis hizmetleri; the guard's card groups them like the
    other shift teams ("Nöbette: … Aşçı (2.) …", "Aşçı (2 kişi) · sonraki vardiya …"); their cards ("yemekhane" /
    "asci") start with the team's shift rows, then the canteen, today's meal windows ("Öğünler") and lunch. The Otel:
    `OTEL_ODA` 72 (18 × 4) for 41 + T guests: ≥ 8 spare rooms up to 23 projects. Tests: `MealTest`, `KitchenTest` in
    `test/test_npc.py` (`test_kitchen_staff_sleep_at_night_break_between_meals_and_work_the_meals`: 03:00, 22:00 and a
    Saturday night in bed, breakfast / dinner prep and lunch at work, 13:00–18:00 mostly in the kitchen with a few
    breaks, never through furniture); the canteen tests in `test/test_ofis_plani.py`.
  - **The announcement gathering** lasts `DUYURU_MS` + `DUYURU_TOPLANMA_MS` (60 + 45 s), so the listeners who walked
    over still sit for most of a minute.
  - **Cues of real events** (B4, owner decision 2026-11-12; each short, from /api/state only, carried by the folder or the badge
    every robot already has): a new job's file goes down the company (plan 7, extended by plan "Sonraki iş (9)") — see
    "Company structure" for the chain CEO → Genel Müdür → the department's manager → the project's sorumlu (project work
    only) → the worker; the last carrier takes it to the job's robot (lobby seat or desk, "işi masaya götürüyor"; it
    follows the robot from the lobby to its desk); carried tick to tick on the CEO actor (`teslim`, `teslim_verilen`:
    each walk lasts until arrival, a job once);
    when a planning job (tier `planlama` or a plan step) of the project starts, its sorumlu walks to the planning worker's
    desk — the planning desk in the Yazılım Müdürü's office — for a short meeting ("Genel Müdürle planı görüşüyor" when
    the planner is Fable, else "planı görüşüyor"; `TOPLANTI_MS` 20 s after
    the walk, within `TOPLANTI_PENCERE_MS` of its start, once per job: `gorusme`, `gorusulen`); the first Kontrol failure (Kontrol in the previous tick, now
    working with `kontrol_sonuc` `kaldi`) shows an orange "✗" (`simge` `kaldi`, "Kontrol geçmedi · düzeltiyor",
    `KONTROL_ISARET_MS` 20 s; not red: nobody is stuck, no doctor); review findings going back (the kod step works again
    right after its workflow's code review finished) — an idle Codex carries the sheet to the kod desk ("bulguları
    götürüyor"); an answer picked up (a job that waited at the CEO's door works again) — the Sekreter takes it from the
    CEO's door to the job's desk ("cevabı götürüyor"); a group report just written (`son_rapor`) — the Sekreter files
    it at the CEO's door ("raporu dosyalıyor"). Each lasts its walks plus `IS_KALIS_MS`; the Sekreter's errands queue
    after her decision trips.
  - **Labels and cards.** A staff member on a real duty shows its short duty text in the green pill at the default zoom
    ("Sekreter · karar götürüyor"); the Çaycı's "Molada" lists every break the engine chose (`mola: true`: tea, games,
    the terrace, the gym, WC, shower, massage, a nap, a walk, lunch) and never the CEO's round; unknown tokens show the
    dollars only.
- Living office behaviour (step 2 of the living-office plan): `web/ofis-davranis.js` is a pure module that turns `/api/state` into actors (who stands where, pose, icon, plain-text label) and the floor plan with its waypoint graph; real state first (a busy agent never leaves its desk; "Evde" only on a concrete `kota`), lunch read in `sahne.saat_dilimi`, naive job stamps with `sahne.sunucu_utc_ofset_dk` (the server's local UTC offset), full rooms as one "+N", no randomness.
- **Company structure** (plan "Sonraki iş (9)" step 1, the owner, 2026-11-13: managers make technical decisions later; roles
  and rules, not a model call per layer; memory automatic and evidence-based; step by step). The owner → CEO → **Genel
  Müdür** (the former Müdür: the fable kadro, `UNVAN.fable` "Genel Müdür"; the model stays Fable) → four managers
  (`MUDURLUKLER` in `web/ofis-davranis.js`: Yazılım Müdürü, QA Müdürü — "QA (Test)" —, Analist Müdürü, IT Müdürü), each
  with its own glass office (see the floor layout). The managers are staff NPCs (`sus:mudur:<key>`, tur `sus`,
  gorevli `mudur`, `alan` = key; informational, office hours with a seeded arrival / leave, lunch, the personality's
  roaming, hidden in hafif) — never a model session: the real work still runs through the tiers and the workflow steps.
  **The IT sorumlusu stays the IT ekibi's lead on its rotating shift and reports to the new IT Müdürü** (office hours,
  its own office); the IT güvenlik uzmanı (the security reviewer's runs, at the IT güvenlik desk of the Sunucu odası)
  reports to the IT Müdürü too. The teams: the project bays (Yazılım: Stajyer / Uzman / Kıdemli by model), the **QA
  odası** (four desks: `QA_MASALARI` — two Kıdemli Tester desks first for any review, two Stajyer Tester desks first for
  a haiku review), the **Analist odası** (four business-analyst desks). No NPC sits at those desks: only real Claude
  reviews do.
  - **Where the real workflow steps show** (display only, from the job's own tier and step: `planIsi`, `incelemeOdasi`,
    `isDepartmani`): a plan step / planlama work types at the planning desk `PLAN_MASASI` of the Yazılım Müdürü's office
    (overflow: its team's manager's desk), labelled "<proje> · Genel Müdür (Yazılım Müdürü adına)" for Fable — the
    Genel Müdür's own model does the Yazılım Müdürü's planning (the honest way round: the manager NPC has no model) —
    else "<proje> · <kıdem> (Yazılım Müdürü adına)"; a plan review run by Claude at an Analist odası desk ("<proje> · İş
    analisti · <kıdem>"); a kod review (or an inceleme-tier job) run by Claude at a QA odası desk ("<proje> · Kıdemli
    Tester", `testerUnvani`: Stajyer / Uzman / Kıdemli Tester by model); the kod step at the team bay as before (by
    seniority); the panel stays in the auditors' room and the hakem in the Uzmanlar odası; full rooms → "+N"
    (`ozet:qa`, `ozet:analist`).
  - **Specialisation on the labels** (step 2, see "Specialisation" in `isler.md`): a job's actor carries `rol_metni`
    ("Kıdemli Backend", `rolMetni(model, uzmanlik)`) and `uzmanlik`; its floor label is "<proje> · <kıdem> <uzmanlık>
    (<Model>)", the card's title `rol_metni`; `unvan` stays the seniority (the robot's accessories). The QA odası's title
    comes from the test profile (`testerUnvani` = `rolMetni(fam, 'test')`); a review with its own specialisation shows
    it. genel and the Genel Müdür add no word. No new robots, no new meshes.
  - **The hand-over chain of a new job** (`teslim` on the CEO actor: `{anahtar, proje, bolum, zincir: [{id, ev, ara}], t,
    hedef, bitis}`, `teslimIlk`, `teslimRolu`): a job added within `TESLIM_PENCERE_MS`, the newest one, while the CEO is
    free: the CEO walks the file to the spot beside the Genel Müdür's desk ("işi teslim ediyor"), the Genel Müdür to the
    spot beside the department manager's desk (`isDepartmani`: plan reviews → Analist, kod reviews / inceleme jobs → QA,
    the rest → Yazılım), the Yazılım Müdürü on to the project sorumlu's visitor spot (`ekip-<p>-mudur-ziyaret`; project
    work only), and the last carrier to the job's robot ("işi masaya götürüyor"). A receiver waits at its desk ("yeni işi
    bekliyor", then "yeni işi teslim alıyor" while the file is on its way to it; on duty, so one called in outside its
    hours counts as in the office); a hand-over waits until the receiver is at its desk; every walk lasts until arrival;
    whoever is not there is skipped (the Genel Müdür working as a fable job, eating, at home on quota, red; a manager
    outside its office hours); once per job; none in hafif. The Genel Müdür's leg is drawn on the fable kadro.
  - **Other cues** (real events only, each once per job, never in hafif, never outside the office hours of the manager):
    when a review starts (a kod review or an inceleme-tier job — also one the panel runs —, within
    `TOPLANTI_PENCERE_MS` of its `started`) the QA Müdürü walks to `QA_MUDUR_YERI` in the QA odası ("incelemeyi
    başlatıyor", the walk plus `TOPLANTI_MS`); when a workflow's plan review starts the Yazılım Müdürü meets the Analist
    Müdürü in its office (`mudurluk-analist-ziyaret`, "planı Analist Müdürüyle görüşüyor"; the Analist Müdürü "plan
    incelemesini görüşüyor" at its desk; not while either is on a hand-over leg); when a workflow's approval card is new
    (a decision of kind `akis-onay` not seen in the previous tick; none on the first render) the free Genel Müdür carries
    the summary to `GM_KAPI_YERI` beside the CEO's door ("onay özetini CEO'ya götürüyor", the walk plus
    `SEKRETER_KALIS_MS`) — the Sekreter still brings the decision itself to the door.
  - **Cards** (`web/ofis-sahne.js`): a manager's card (`mudurKarti`, "departman"): its department, "Bağlı olduğu: Genel
    Müdür", its people (`MUDURLUKLER[].ekip`; the IT Müdürü's also who of the IT team is on shift) and the real work in
    its area now (`bolumIsleri`): Yazılım — the running kod jobs (and planning), QA — the reviews and the Kontrol runs,
    Analist — the plan reviews, IT — the Sunucu odası's level, suggestions (GET `/api/sistem`, fetched for the IT Müdürü's card only) and the
    open security findings (decisions with `guvenlik_acik`) and a running security review; each job opens its detail. The
    Genel Müdür's card (the fable kadro) adds the org summary (`genelMudurOzeti`: its four managers in / home, the open
    work per department, the approval cards waiting). The IT güvenlik uzmanı's card says it reports to the IT Müdürü.
  - **Who is where**: the managers are a department of their own ("Müdürler") in `kimNerede` / the guard's card.
  - **The org chart** ("Şema", `orgSemasi(state, now, actors)`): see the office page.
  - **Değerlendirme ekibi** (the end-of-day review, `bin/gunsonu.py`; owner decision 2026-11-13): two staff of the Analist
    Müdürü, `sus:degerlendirme:0` "Ölçüm uzmanı" and `sus:degerlendirme:1` "Değerlendirme uzmanı" (gorevli
    `degerlendirme`), at two free desks of the Analist odası (`DEGERLENDIRME_MASALARI`: the desks the decorative analysts
    use, which hide meanwhile; a desk an actor uses is never taken) — existing furniture, no new draw call but their
    robots. Real events only (`degerlendirmeDurumu(state, ms)`): for `state.gun_sonu.aktif_dk` (10) minutes after the
    day's measurement (`son.olcum_iso`, the server's time) — "günü ölçtü · 20:05" / "kötü giden N durumu not etti" — and
    while the review job (a task with `gun_sonu`) is open — "kök nedenleri arıyor · <title>", waiting for the owner:
    "değerlendirme · <sahip>'in cevabını bekliyor" (`degerlendirmeMetinleri`). Also in hafif and outside office hours;
    never drawn otherwise. `kimNerede` lists them exactly while drawn. The review job works in the arge workspace but
    never seats the Ar-Ge uzmanı (`argeIsi` leaves `gun_sonu` tasks out).
  - **Decorative people** (the owner, 2026-11-13: "QA odasında, analist odasında, proje ekiplerinde NPC yok; sırf görünüm
    için olabilir"): purely visual figures so these rooms look staffed — `DEKOR_EKIP`: 3 in the QA odası, 3 in the
    Analist odası, 2 per team bay. `dekorYerleri(plan)` (pure, fixed per plan): the QA odası's second Kıdemli and second
    Stajyer Tester desk (`qa-masa-1`, `qa-masa-3`: the first desk of each kind stays for real reviews), the Analist
    odası's last two desks, a team bay's two last desks, and in each of the two rooms one standing at the whiteboard
    (left of its middle, three quarters turned to it, clear of every place and desk). `dekorEkibi(plan, actors, now,
    sahne)` (app.js `renderScene` → `Office.setDekor`) drops the ones home — each with its own seeded office hours
    (`personelSaati`; outside them hidden at once, no lift walk) — and the one whose desk an actor sits at or heads for
    (`yer` / `masa`: real work always wins the desk). They never walk, so they never cross furniture; small calm movements
    only (a slow sway, a short look aside once in 24 s, a seated one breathes; static in hafif). They are no actors: no
    data, no label, not in `kimNerede`, the Çalışanlar list or the cues. **Cost: two draw calls for all of them**, any
    number: one `InstancedMesh` of a merged lower-detail robot body (vertex colours, room tint as instance colour: QA
    blue, Analist lilac, a team its floor colour) and one of the standing ones' legs; no shadows; none at night. Measured
    (`run_scene_count`, `dort-mesgul`): 719 draw calls at the 16:00 shift change (717 before), 691 at 10:30, 611 with
    three helpers per job, 363 at 03:00, 398 in hafif — under `DRAW_LIMIT` 725. A click on one opens a plain card
    (`dekorKarti`, actor `{tur: 'dekor', grup, proje}`): "QA ekibi" / "Analist ekibi" / "<proje> ekibi" · "görünüm
    amaçlı", a line that it is a figure, not a worker or a model session, and the room's real numbers already on the
    chart ("N inceleme · M Kontrol", "N plan incelemesi", "N açık iş"); no actions. The org chart shows them only as one
    group line on the existing box (`ekip`: "QA ekibi: 3 kişi · görünüm amaçlı" on the QA odası, "Analist ekibi: …" on the
    Analist odası, "<proje> ekibi: 2 kişi · görünüm amaçlı" on each project sorumlusu), never a box per person. Tests:
    `DekorTest` in `test/test_npc.py`.
  - **A busier office** (owner decision 2026-11-18, "NPC'leri fazlalaştıralım"): more decorative people (`grup: 'ortak'`,
    same instanced meshes, so **no new draw call**): seated on the common-area seats the real actors take last
    (`dekorOrtakYerleri`: three at the Toplantı odası's table — it stays empty of actors —, three at the canteen's last
    table, the tea corner's last round table, one café table of the Ortak alan, the bean bag; one billiards player
    standing; never a desk or a lobby armchair), turned like a real character on that spot (`yuzAcisi`, the seat's own
    height `sit`), and four walkers (`DEKOR_YURUYUSLER`: the front-row corridor, the back corridor, a wing corridor, the
    lobby door to the spine) that stroll at `DEKOR_HIZ` 0.8 units/s along `yol` between their stops — the plan's own
    walks, never through furniture — pausing `DEKOR_DURAK_S` 8 s at each (`dekorRotasi`, `dekorYuruyusu`: pure,
    periodic in the scene's time; a small bob, the standing legs mesh). Same rules: own seeded office hours, none at
    night, a seat an actor uses or heads for is given up, never in `kimNerede` / Çalışanlar / cues; hafif keeps the
    seated ones (static) and drops the walkers. They move with the scene's frames (9 fps at rest, no faster frame rate;
    the dekor meshes are not frustum-culled). Day count 14 → 30 (26 in hafif). Measured (`run_scene_count`,
    `dort-mesgul`): from scratch 576 at 10:30 (576 before), 574 at 16:00 (576), 615 at 12:25 (615), 358 at 03:45 (358),
    348 in hafif (348); walking sequence 603 at the 16:00 change (605), 633 at lunch (633) — under `DRAW_LIMIT` 725.
    Tests: `DekorOrtakTest`.
  - **More logical behaviour** (owner decision 2026-11-18, "daha mantıklı"; real state only, `MantikliDavranisTest`):
    a **silent or stuck job** (`bakilacakIsler`: `postoffice.silent` without a permission prompt, `tikandi`) → its
    department's manager (Yazılım / QA / Analist by `isDepartmani`; the IT has none) walks to that worker's desk side spot
    and stands by it — "sessiz işe bakıyor · <iş>" / "takılan işe bakıyor · <iş>", the walk plus `TOPLANTI_MS`, once per
    job (`bakilan`), only on no other duty; a side spot someone holds waits (the doctor's visit to a stuck desk comes
    first, never both on one spot). A **job just finished** (bitti within `KUTLAMA_MS`) keeps its project sorumlusu at its
    bay for the walk plus `KUTLAMA_MS` ("ekibini kutluyor · <iş>", once per job, only one already on the floor) — before,
    it walked off the very moment its project's last job was done. **Idle desk lines say real things** (`masaSozu`):
    the managers their department's open work ("masasında · 3 kod işi takipte · en yoğun: blog", "… inceleme …", the IT
    Müdürü the system's load), the doctor today's stuck jobs or "ofis sağlıklı", the psychologist the jobs on a second
    Kontrol, the İK the jobs at work, the Muhasebeci today's finished jobs, the İdari işler the schedules, a project
    sorumlusu its open jobs; plain "masasında" when there is nothing real to say.
- **Konferans salonu** (owner decision 2026-11-12): a fixed facility cell under the Revir (`TESIS_HUCRELERI.konferans`, `alt`
  column 2 row 3; it took a project cell, so the wing gets its third column one project earlier): a screen on a stand
  at the back wall, a lectern (`konferans-kursu`) and three rows of six chairs facing the screen. For `DUYURU_MS`
  (60 s) after an announcement's `zaman` (`duyuruPenceresi`): the free CEO (idle / asleep, nothing open) stands at the
  lectern ("duyuruyu okuyor"); the idle kadro, the idle auditors and the off-duty staff take the chairs in that order
  ("duyuruyu dinliyor", `salonaTopla`; who does not fit stays put); working agents stay at their desks with
  "· duyuru alındı" when their session is in `alanlar`. The screen (a canvas, fillText only) shows the first line
  (`salonEkrani`, `Office.setDuyuru`), otherwise the office's name (`ofis_adi`, `Office.setOfisAdi`); the lobby has a
  sign with the same name behind the reception desk. In hafif nobody moves and no mark is shown: only the screen text. `?demo=1&demo_duyuru=<first line>` fakes
  an announcement at load (screenshots); the demo's own "Duyuru yap" does the same.
