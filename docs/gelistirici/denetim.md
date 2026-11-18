# Workflows and the review panel

> Moved verbatim from the CEO's `CLAUDE.md` on 2026-11-13 (split approved by the owner). In this text "you" is the
> CEO session. A section named in quotes ("see …") may live in another file: the index in
> [`../GELISTIRICI.md`](../GELISTIRICI.md) lists where each one is. The CEO's own rule set is `CLAUDE.md`; when a
> CEO-facing rule changes here, change `CLAUDE.md` too.

## Workflows (akışlar)
A workflow runs one piece of work as a chain of steps, each an ordinary job (note, server record, budget, limits,
karne row), started by the dispatcher in order. Templates are trusted files in this repository (`akislar/<name>.json`;
never edit them without the owner); a template the server cannot validate refuses the workflow. Shipped:
| Template | Steps | Use it for |
|---|---|---|
| `gelistir` | plan → plan-inceleme → kod → kod-inceleme → onay | a new feature or a change across several files: the plan is written and independently reviewed before any code |
| `kucuk-is` | kod → kod-inceleme → onay | a small, clear fix whose plan is obvious |
Plain jobs (`ekle`) stay right for reading, research, status checks, and anything that changes no code or needs no
approval card. A workflow always needs a runnable Kontrol (its kod step).

Start one with `python3 bin/ofis.py akis <template> --proje P --baslik "<kısa başlık>" --hedef "…" --kontrol "<cmd>"
[--neden …] [--kisitlar …] [--kapsam-disi …] [--butce USD]` or with `--brief-dosya durum/taslak/<ad>.json` (fields
`proje`, `baslik`, `hedef`, `neden`, `kisitlar`, `kapsam_disi`, `kontrol`, `butce`). It prints the workflow id (`grup`,
e.g. `akis-1111-100000-blog`) and the step jobs. Ask the owner the "what not to build" questions first, as for any new
feature. The steps' tiers come from the template (plan: planlama, reviews: inceleme, kod: kod). The workflow's queued
steps count as one entry in the project's queue.
- **Budget**: `--butce` is the whole workflow's budget (default: the sum of its session steps' tier budgets —
  `gelistir` $11, `kucuk-is` $7); it is split by weight — plan 2, plan-inceleme 1, kod 4, kod-inceleme 1 (each share
  at least $0.10, a review share at least $0.50: one Claude review cost $0.42 when Codex gave no verdict). The onay step
  has no session: its job shows katman `onay`, model `deniz` (the owner's approval, never a model worker). Each
  step job is limited and stopped like any job (Budget and call limit); a kod step can still be escalated (Escalation).
  A new review round is opened only while the workflow's recorded spending + the round's share stays within 2 × the
  workflow's budget; otherwise the workflow stops and you ask the owner.
- **How it runs** (server code, no model): a step starts only after the previous one passed. Each step's prompt is
  built by the server from the trusted brief and the earlier steps' outputs (kept in `durum/akislar/<grup>/`, quoted
  as data, trimmed to the 4000-character limit): the plan review reads the plan, the kod step gets the approved plan,
  the code review gets the kod report and `git diff --stat` since the kod step's base commit.
- **Verdicts**: a review must end its report with `KARAR: ONAY` or `KARAR: DÜZELT`; reviewers look for correctness,
  security and behaviour only (no style), argue against each finding before reporting it, and label findings
  BLOCKER / MAJOR / MINOR. A BLOCKER/MAJOR finding is never an approval; MINOR-only counts as ONAY (the minors go on
  the approval card). A missing or garbled verdict counts as DÜZELT once; the second time the workflow stops.
  Plan DÜZELT → a new plan job (fresh session) with the findings and a new plan review (at most 2 plan rounds). Code
  DÜZELT → the findings go to the kod job's own session (`[Ofis · inceleme bulguları]`), its Kontrol runs again, then
  a new review (at most 2 review rounds). Over these limits the workflow **stops** and you get one notice ("akışı
  durdu"): ask the owner, then `python3 bin/ofis.py akis-karar <grup> devam` (the stopped step counts as passed; the
  open findings appear on the approval card) or `… iptal` (cancels the open steps; stop running sessions yourself).
  Never run `akis-karar` without the owner's answer.
- **The review panel (dış denetçi heyeti, `bin/denetci.py`)** reviews the code by default. Reviewers come from
  ofis.json `denetciler` (`{"ad": "codex", "tur": "codex"}` and `{"ad": "glm", "tur": "opencode", "model":
  "opencode/glm-5.3-flash-free"}`-style entries; without the key: Codex alone). They run in parallel, each with the
  timeout `codex_timeout_s` (default 900 s):
  - **Codex** runs in every project as before (`codex exec -C <folder> -s read-only review --ephemeral -o <file>
    "<instructions>"`; codex 0.167 refuses `--base` together with a prompt, so the instructions name the base commit
    — `git diff <taban_commit>` — and list the changed and untracked new files).
  - **Free reviewers** (OpenCode: GLM and DeepSeek; Antigravity below) send the diff to an outside service, so they run only for the
    projects in `ucretsiz_denetci_projeler` (the owner's decision: `["blog"]`; never a forbidden path). They never see
    the real folder: the server makes a temporary `git worktree add --detach` copy at the base commit, applies the kod
    step's changes (tracked diff and untracked new files), runs `opencode run --standalone -m <model> --format json`
    there with every tool permission denied (edit, shell, web, …), the diff embedded in the prompt, and always removes
    the copy afterwards. The copy holds no symbolic link (`core.symlinks=false`, then every link removed), and OpenCode
    reads no other config (`OPENCODE_CONFIG` / `OPENCODE_CONFIG_DIR` dropped, `~/.claude` loading disabled). A
    server start removes `ofis-denetci-*` copies a killed server left behind and runs `git worktree prune` in every
    registered project. `opencode_bin` (optional) else `opencode` on PATH.
  - **Antigravity** (`{"ad": "antigravity", "tur": "agy", "model": "gemini-3.8-flash-high"}`, owner decision 2026-11-13; the 4th
    reviewer, free, so only for `ucretsiz_denetci_projeler`: its free plan's data may be used for training) runs in the
    same temporary copy: `agy -p "<instructions + the embedded diff>" --mode plan --sandbox --disable-slash-commands --model <model>
    --output-format json --print-timeout <codex_timeout_s>s`, stdin `/dev/null`, never
    `--dangerously-skip-permissions`; the prompt says to use no tool and read only the embedded diff. The report is the
    JSON's `response`; `denied_actions` go into the round file (`reddedilen_eylemler`). Non-zero exit or a status other
    than SUCCESS → `hata`; quota only when that error's `error` field names quota / rate limit / 429 /
    RESOURCE_EXHAUSTED (no real sample yet: the raw error text is logged once per distinct text, "antigravity raw
    error", to tighten the match later); an empty response or no KARAR line is skipped like the others. Hakem, karne
    row, model row "Antigravity · ücretsiz" (unvan "Dış denetçi"), desk, slate colour and quota "Evde" work as for the
    OpenCode reviewers. `agy_bin` (optional) else `agy` on PATH (tests: `$OFIS_AGY_BIN` points nowhere, `FakeAgy`).
    `--disable-slash-commands` keeps the embedded diff from being expanded as a slash command (added after the review,
    confirmed by the coordinator's canary on 2026-11-13). Watch item: agy loads the owner's own agy user config; today it
    has no MCP servers and no plugins. Guard: before a run `agy mcp list` and `agy plugin list` must print only their
    "nothing configured" lines (`denetci.agy_user_config`; the result is kept in `durum/denetciler/agy-ayar.json` for
    10 minutes and only while the newest mtime of `~/.gemini/antigravity-cli`, `~/.gemini/config` and
    `~/.gemini/settings.json` is unchanged, so an added plugin or MCP server is seen at once; a list that cannot be
    read is not kept); otherwise Antigravity is skipped as `hata` "agy kullanıcı ayarında MCP/eklenti
    var" (logged once). If the owner adds agy MCP servers or plugins, give the reviewer a restrictive `--settings` first.
  - **Quorum and backups ("en az N göz + yedek", owner decision 2026-11-13)**: a round needs N general verdicts before it may
    approve — ofis.json `denetci_yeter_sayisi` `{"dusuk": 1, "normal": 2, "yuksek": 3}` (defaults in code; the security
    reviewer never counts), capped at the external reviewers allowed for the project (Codex plus the free ones where
    allowed; coordinator 2026-11-13): a Codex-only project needs one verdict at every level, so no Claude review is added
    where none ran before; a reviewer skipped for quota still counts toward the cap. Before the round (`denetci.round_plan`) a reviewer whose model status is a known quota
    (Codex's strict flag, matched by type `codex` whatever the reviewer's name; a free reviewer's quota round) is skipped (`atlananlar`; no row, so its quota is never
    renewed by a skip) and the round is filled up to N from the backup order: the free reviewers allowed for the
    project (config order), then Codex, then the Claude review (a project not in `ucretsiz_denetci_projeler` has only
    Codex and the Claude review). During the round (`DenetciHeyeti._run_round`) a reviewer that errors, hits its quota,
    times out or writes no KARAR line is replaced at once by the next backup while N is not reached or on the way;
    **hedge**: when every other reviewer is done and the last one runs longer than max(2 × the slowest finished one,
    120 s) while its verdict is still needed, the next backup starts beside it — the first verdict counts, the other's
    process group is killed (status `durduruldu`: never an error, never a Codex status). `codex_timeout_s` still caps
    each. Fewer than N verdicts never approve: the step goes to the Claude review with the verdicts that arrived as
    data in its prompt ("yeter sayıya ulaşmadı"); a confirmed BLOCKER/MAJOR is a DÜZELT below N too. Backups and hedges only exist where
    the risk level leaves reviewers out of the first group (düşük): in blog a düşük Codex review that runs over
    120 s gets a free reviewer beside it, and Codex is stopped when that one answers first. The round file keeps
    `yeter_sayi`, `karar_sayisi`, `yeter_sayi_karsilandi`, `atlananlar`, `yedekler`, `hedge` and each backup row's
    `yedek` (why); Denetciler.md counts "Yedek olarak" and "Durduruldu" per reviewer.
  - **Hakem**: when any reviewer (Codex too) reports a BLOCKER/MAJOR finding, one `claude -p` call (`hakem`:
    `{"model": "sonnet", "butce_usd": 0.15}`, read-only tools, in the copy or else the real folder) judges each
    finding GEÇERLİ/GEÇERSİZ and merges duplicates. Only confirmed findings make the review DÜZELT and go to the kod
    session; otherwise it is ONAY and the minors plus the rejected findings ("hakem reddetti") go on the approval card.
    If the hakem fails, a finding counts only if Codex reported it or two reviewers reported the same issue (the card
    says so). A finding's own BULGU line always wins over an `AYNI` merge. Its cost is the review job's recorded
    spending; Codex and the free models are not priced (group reports add the hakem's cost and say "Codex hariç").
    The hakem also tags each confirmed finding YENİ (this change brought it) or ÖNCEDEN (the code was already like
    that at the base commit and the change did not make it reachable): a pre-existing finding never goes to the kod
    session and never causes DÜZELT; the card lists it under "Önceden vardı (bu değişiklik getirmedi)". It names each
    finding's bug class; the kod session gets the findings grouped by class with "fix every instance of this class".
  - **What the Kontrol proved, and the quiz** (the hakem's extra outputs): the hakem's call also gets the kod step's
    Kontrol command (from the trusted copy, quoted as data) and writes 2–5 `KANITLADI: …` and 2–5 `KANITLAMADI: …` lines
    (what the command really shows, what it does not — paths not run, cases not tried); for normal / yüksek risk or a
    change of more than 80 changed lines also 2–3 `SORU: … | CEVAP: …` understanding questions. A round without a hakem
    (no serious finding) on normal / yüksek risk (or a large change) makes one small separate `claude -p` call with the
    hakem's settings and budget instead (the "kanıt değerlendiricisi"; `KANIT_HEAD`); only one of the two runs per round,
    each capped by `hakem.butce_usd`. Its cost is added to the review job's spending like the hakem's (Karne/Denetciler.md
    lists it next to the hakem). düşük risk skips it (the card says so). Parsed tolerantly (`denetci.parse_proof`,
    `parse_quiz`), kept in the round file (`kanit`, `sinav`), always quoted as data; nothing is ever invented — without
    it the card says "Bu iş için değerlendirilemedi (<why>)". A quiz-only call (a large düşük-risk change) records the
    proof as skipped ("düşük risk: hızlı inceleme"), never as unreadable. Every quoted line of agent text on a card
    (plan, kod report, findings, quiz answers) has a leading Obsidian callout `[!` escaped as `\[!` (`kontrol.no_callout`),
    so a report can never render as a callout box in the vault; the page shows the plain text.
  - **Convergence (review round 2+)**: the server records a git tree of the folder's state at every review round
    (a temporary index; the real index, working tree and refs are untouched). In the next round every reviewer gets
    only the diff since that state plus the findings already reported, and is told not to report a fixed or known
    finding again; the hakem still sees the whole diff since the base commit and says for each finding sent last
    round whether it is fixed (`ÖNCEKİ <n>: DÜZELDİ | DÜZELMEDİ`). The 2-round cap is unchanged.
  - A reviewer that errors, times out, hits its quota (OpenCode: only the `provider.quota` / `provider.rate-limit`
    error event) or writes no `KARAR:` line is skipped for that round. If **no** reviewer gives a verdict, the same
    step becomes a Claude review (tier inceleme) by itself; the step shows `inceleme_yurutucu: claude (codex yok:
    <neden>)`.
  - Measurement: the server keeps every round in `durum/denetciler/turlar/<iş>.json` (and each reviewer's text in
    the workflow's outputs) and rewrites the vault note `OFIS/Karne/Denetciler.md` (per reviewer: rounds, verdicts,
    serious findings, how many were confirmed, average time, errors, quota, timeouts; the hakem's totals; and the
    noise measurement — what became of each serious finding: düzeltildi, etkisiz (found again after the fix),
    reddedildi (the hakem rejected it), önceden vardı, bekliyor — as rates per reviewer). Read it
    when the owner asks which reviewer is worth keeping; turning one off is his decision. The page gets a model row for
    each free reviewer (unvan "Dış denetçi") while some project may use them, and each a desk in the auditor's room.
    `durum/denetciler/calisan.json` (written by the panel: the reviewers at work and the reviewed job, then the
    hakem's phase with its model) is `/api/state.denetim` = `{is, denetciler, hakem, baslangic}` or null (a file of an
    earlier server process is ignored); while the hakem runs its model counts as working and that review's Codex not.
    The security reviewer gets a row (`model: guvenlik`, unvan "Güvenlik denetçisi", `ajan_modeli`) while ofis.json
    has `guvenlik_denetcisi` or it runs: `calisiyor` while the marker names it, else its Claude model's own state; on
    the floor it has the last auditor desk and types there only while it runs (never "ücretsiz"). Decision cards carry
    `risk` (dusuk|normal|yuksek, from the card's frontmatter) and `guvenlik_acik`; the page shows a risk badge and,
    with an open security finding, "Açık güvenlik bulgusu var — bu haliyle onaylanmamalı" with Onayla made visually
    secondary (still clickable). The approval card's evidence is shown in the card's order, evidence first and the
    summary last (`kartBolumleri`: Nasıl test edildi, Kontrol neyi kanıtladı / kanıtlamadı, Ajanın kararları ve
    varsayımları, Değişiklik özeti, İnceleme, Güvenlik, Nasıl geri alınır, Plan özeti, Maliyet); the optional quiz
    (`d.quiz`, parsed by bin/state.py) comes last with each answer behind a "Cevabı göster" toggle; a
    `review-md-onerisi` card shows like a `claude-md-onerisi` one.
  - **Risk-based review** (`bin/risk.py`, deterministic): before the panel runs, the change (changed paths and line
    counts since the base commit) is classified. **yüksek** when it touches a sensitive path — authentication /
    sessions / tokens / password reset / permissions, payment / billing / subscriptions / purchases, CI and deployment
    files (`.github/workflows`, `.gitlab-ci`, fastlane, Jenkinsfile, Dockerfile, k8s/terraform), database migrations and
    schemas, installer / updater / release config, secrets and key files (`.env*`, `*secret*`, keystores), agent and
    tool configuration and instructions (CLAUDE.md, AGENTS.md, `.claude/`, `.mcp.json`, `.github/actions/`,
    `.github/copilot-instructions.md`, `.github/instructions|prompts/`, `.cursor/`, `.cursorrules`, `.clinerules`,
    `.windsurf/rules/`, `.roo/rules`, `.junie/`, `.vscode/tasks.json`, `.envrc`, `.gitignore`, `.gitattributes`), test
    infrastructure (conftest.py, pytest.ini, jest/vitest config, …: it changes what the Kontrol proves), app permissions
    (Info.plist, entitlements, AndroidManifest.xml), dependency and build files (package.json, pubspec.yaml,
    build.gradle, Podfile, requirements*.txt / .in, constraints*.txt, CMakeLists.txt, Makefile, …) — or a glob of the
    project's own list ofis.json `projects.<P>.hassas_yollar`; **düşük** when only documentation or tests change
    (recognised by the file name — `*.md`, README/LICENSE/CHANGELOG-style names (a plain `.txt` is not documentation),
    `test_*.py`, `*_test.*`, `*.spec.*`, `LoginTests.swift` — never by a docs/ or spec/ folder; the keyword checks
    still look at such a file's folders) and at most 40 lines; **normal** otherwise (lockfile-only changes are normal). File names in
    the reasons are escaped (line breaks and similar characters as `\uXXXX`), so a file name can never forge a card
    line.
    **Hidden changes** (`bin/gitsafe.py`): a kod session can hide a change through its own git state
    (`assume-unchanged` / `skip-worktree`, a clean filter in `.git/config` + `.git/info/attributes`, an ignore rule).
    So every server git read runs without the global attributes / excludes files and with every configured filter
    driver neutralised (`-c filter.<name>.clean=cat`, `smudge=cat`, `process=` (off), `required=false`: the server never
    executes a filter command a session configured), lists untracked files with the repository's own `.gitignore`
    files only (never `.git/info/exclude`), and the review compares flagged files — and,
    when the local git state changed since the kod step started (`taban_git_ozet`, recorded at its start), every file
    with a filter — byte for byte with the base commit. A hidden change joins the change (the reviewers, the snapshot,
    the card's undo list) and forces yüksek with the reason "git durumu değişikliği gizleyebilir: …". yüksek → every reviewer (the free ones still only in their projects)
    plus the security reviewer, and the hakem as always when there is a serious finding; düşük → Codex alone (or the
    first reviewer; the others are backups, started one at a time when it gives no verdict — see Quorum), the hakem only for a BLOCKER/MAJOR; normal → as
    before. The level is on the review job's server record (`risk`, `risk_nedenleri`), in the round file and on the
    card. It never lowers the Kontrol or the approval card: the owner's plain approval is always needed.
  - **Security reviewer** (`guvenlik`): one more `claude -p` call (ofis.json `guvenlik_denetcisi`: `{"model": "sonnet",
    "butce_usd": 0.2, "her_zaman": false}`; read-only tools, plan mode, `--safe-mode`, like the hakem) that looks only
    at security issues the change introduced (injection, authorization / ownership checks, secrets, unsafe
    deserialization, path traversal, SSRF, crypto misuse, sensitive data in logs, …), with BLOCKER/MAJOR/MINOR labels and
    a `KARAR:` line. It runs on yüksek risk always, on normal risk only with `her_zaman: true`. Its serious findings go
    through the hakem like the others (listed as "(guvenlik)") and count even when the hakem fails; a confirmed one
    makes the review DÜZELT. It never approves on its own: if no other reviewer gives a verdict, the Claude review takes
    over. Its cost is added to the review job's spending (with the hakem's) and shown in `Karne/Denetciler.md`; when the
    step falls back to the Claude review, that cost is kept on the record as `on_harcama_usd`, which the budget meter
    adds to the Claude session's own cost (job spending, workflow total, the 2× check and the karne all include it); that
    job's `butce_usd` grows by the same amount, so the Claude review keeps its full share.
  - **REVIEW.md**: when the project has a `REVIEW.md` at its root **in the base commit** (the kod session's own edit
    of it is never used), its text (plain text, capped at 3000 characters) is quoted as project guidance data into every
    reviewer's prompt, the security reviewer's, the hakem's and the Claude review's. The office never creates or edits
    a REVIEW.md; a line is added only through a proposal the owner approved (see "Corrections and CLAUDE.md proposals").
- **Probation**: the first `akis_deneme_kosusu` runs of each template (ofis.json, default 3; counted in
  `durum/akislar/sayac.json`) hold every step (`beklet`): the owner releases each step himself (`ofis.py serbest <iş>` only
  after he said so), so he watches the first runs.
- **Approval card (`onay`)**: no session; the server writes a pending Kararlar note (`tur: akis-onay`); you get a
  notice ("akışı onay bekliyor"). **Evidence first, the summary last** — its sections in order: **Soru** (short; starts
  with the risk: "Risk: yüksek — <reasons>", and whether the deep review ran) → **Nasıl test edildi** (the Kontrol
  command, exit code, duration, when it last passed, the end of its output, one line on the reviewers / hakem / security
  reviewer) → **Kontrol neyi kanıtladı / kanıtlamadı** (the hakem's two short lists, see the review panel; "Bu iş için
  değerlendirilemedi" when missing, a düşük-risk skip said so) → **Ajanın kararları ve varsayımları** (the kod job's
  bitti report section "Verdiğim kararlar ve varsayımlar", quoted as data; "Kod ajanı karar listesi vermedi" when it is
  missing) → **Değişiklik özeti** (`git diff --stat`) → **İnceleme** (verdict, executor, rounds, findings) →
  **Güvenlik** → **Nasıl geri alınır** → **Plan özeti** → **Maliyet** → optional **Kendini yokla (isteğe bağlı)**
  (the hakem's 2–3 questions; each answer in a collapsed `> [!note]- Cevap` callout; never needed for the approval) →
  Commit (nothing was committed). **Güvenlik** ("Açık güvenlik bulgusu yok", or the open findings; an open one
  adds `guvenlik: acik-bulgu` to the frontmatter and the line "Açık güvenlik bulgusu var: bu değişiklik bu haliyle
  onaylanmamalı" to the question) and **Nasıl geri alınır** (the base commit, commits since, changed and untracked files
  and suggested commands — text only, marked "yalnız the owner çalıştırır"; the office never runs them, and neither do
  you): `git --literal-pathspecs restore` / `rm` (so a file named `*` or `:!x` is never read as a pattern), only the
  `git clean -n` preview for new files (deleting them is the owner's own call; no `git clean -f` is ever suggested), and
  `git revert` for commits last. The paths that were already modified or untracked when the kod step started
  (`git status` recorded at its start: `taban_kirli` on the server record) are left out of every command and listed
  apart; when that state is unknown every path is marked "taban'dan önce de var olabilir" and the commands that change
  files are written commented out (`# …`) under a warning. Added files get `git rm --cached` (the file stays) plus the
  preview; the office never suggests a deletion. Tell the owner in one line that the card is waiting (the
  evidence is on the card); say so plainly when its risk is yüksek or a security finding is open. His answer goes through
  `cevapla` as usual, word for word: a plain approval ("Onaylıyorum", "evet", "tamam") closes the workflow; anything
  else (a change request, a condition) closes the card, marks the approval job `tikandi` and is yours to handle — add
  new jobs or a new workflow for it, or ask him. **No workflow ever commits, pushes or deletes**: after an approval,
  commit/push is still a separate decision of the owner (and the project's own rules).
- Workflow steps are not told one by one (no "akış adımı bitti" notice any more): the workflow goes on by itself
  and its group report is the one message when it is closed (see "Group reports").
