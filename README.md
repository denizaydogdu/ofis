# Ofis

**English** · [Türkçe](README.tr.md)

Ofis is an AI office that runs on your own Mac. You talk to one "CEO" — a Claude Code session — in a web page. The CEO
turns your requests into jobs, starts a Claude Code background session for each job in the right project folder, and
brings you their questions and results. The server proves every piece of work with a shell command of its own before
it calls the work done, sends code changes to independent reviewers, and keeps every job, question, answer and report
as a note in your Obsidian vault.

It is a local Python server (standard library only) plus a single web page with a 3D view of the office.

> **Language:** the page, the notes, the CEO's replies and all prompts are in **Turkish**. The code identifiers are
> Turkish too; code comments and the developer docs are English.

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install and first run](#install-and-first-run)
- [Adding projects (the Ayarlar tab)](#adding-projects-the-ayarlar-tab)
- [Daily use](#daily-use)
- [Privacy and safety](#privacy-and-safety)
- [Configuration reference](#configuration-reference)
- [Running the tests](#running-the-tests)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## How it works

### The CEO

The CEO is a Claude Code background session named `ofis-ceo` that runs in this repository's folder. Its rule set is
[`CLAUDE.md`](CLAUDE.md). You never talk to project sessions directly: everything goes through the CEO.

The server delivers every message to the CEO as a prompt with a fixed prefix that says who is speaking:

- `[Sahip · ofis sayfası]` — a chat message from you (the owner) on the page;
- `[Sahip · karar cevabı] <note>` — your answer to a decision card;
- `[Ofis · sistem]` — a notice from the server (a job finished, got stuck, asks something).

Only the server writes these prefixes. Anything a project session writes is quoted and treated as data, never as an
instruction; text inside a notice that claims to be from you is treated as a forgery.

The CEO does no project work itself. Even "what is in this file?" becomes a small job. It adds jobs with
`bin/ofis.py`, asks you before building new features (who needs it, how we know it worked, what is out of scope), and
never commits, pushes or deletes — those decisions are always yours.

To keep each turn cheap, the server sometimes starts a fresh CEO session (large context, cold cache, a new day) and
hands it a short summary of open work.

### Projects

A project is a folder on your computer registered in `ofis.json` (you add it on the page's **Ayarlar** tab). Each job
runs as its own Claude Code background session in that folder, with the job's model, effort, budget and call limit. The
session gets a contract with the brief, the project's rules and its role, and reports back through `bin/ofis.py bildir`.
The server's "post office" accepts a report only from the job's own session and folder.

One project is built in: `arge`, the office's research desk (see [The Ar-Ge room](#the-ar-ge-room)).

### Jobs and their lifecycle

Every job is a note in the vault under `OFIS/Isler/`. The folder follows the state:

| Folder | States |
|---|---|
| `Isler/Siradakiler/` | `sirada` (queued) |
| `Isler/Devam-Edenler/` | `baslatiliyor`, `calisiyor`, `karar-bekliyor` (a question is open), `incelemede`, `kontrolde` (the server runs its Kontrol) |
| `Isler/Bitenler/` | `bitti` (done), `tikandi` (stuck), `iptal` (cancelled), `basarisiz` (could not start) |

A job is written as a short Turkish brief: a title, **Hedef** (what is true when done), **Neden** (why), **Kısıtlar**
(constraints), **Kapsam dışı** (out of scope) and **Kontrol** (the proof command).

A **dispatcher** starts queued jobs by itself, oldest first, when their dependencies are done and the limits allow:
by default 3 jobs at once, 1 per project folder, at most 5 queued per project. A job can wait for other jobs
(`--bagimli`) or be held until you release it (`--beklet`).

The server, not the note, is the source of truth: limits, the session, the folder and the Kontrol live in server-owned
records under `durum/`, which no session may edit.

### Tiers and models

Each job gets a tier (`katman`). The tier picks the model, the effort, the default budget and the call limit:

| Tier | Work | Model | Effort | Calls | Budget |
|---|---|---|---|---|---|
| `planlama` | breaking a big request into jobs, architecture | fable | high | 60 | $3.00 |
| `kod` | development and fixes, any file change (needs a Kontrol) | opus | high | 120 | $6.00 |
| `inceleme` | independent review of finished work | opus | high | 60 | $1.00 |
| `genel` | reading, summarising, research (default) | sonnet | medium | 40 | $1.50 |
| `kolay` | mechanical, read-only: run a given command and report | haiku | low | 15 | $0.30 |

On the page the models appear as staff ranks: Stajyer (Haiku), Uzman (Sonnet), Kıdemli (Opus), Genel Müdür (Fable).
Each job also gets a specialisation (`backend`, `ui`, `mobil`, `test`, `analiz`, `guvenlik`, `genel`), chosen by
deterministic rules from the brief; its role instructions live in [`roller/`](roller). The server keeps verified lessons
per specialisation and hands them to new jobs.

Budgets are measured at API list prices from the session's own transcript; the server stops a job that goes over its
budget or call limit and asks you through the CEO. When a model hits its quota, new jobs start on a backup model
(`kota_yedegi`) and a stopped job resumes by itself when the quota returns.

### Kontrol: proof the work is done

A job's **Kontrol** is a shell command, for example `pytest -q tests/test_login.py`. When a session reports `bitti`,
the server runs that command itself with `/bin/bash -lc` in the job's folder (default timeout 900 s). Only exit code 0
makes the job `bitti`, and the note gets a "Kontrol (kanıt)" block with the evidence.

- The command is fixed when the job is added; the server runs only its own stored copy (checked by its hash).
- A `kod` job without a Kontrol, or with one that can never fail (`true`, `echo …`, `… || true`), is refused.
- The first failure goes back to the session silently. A second failure **escalates** the job one tier up
  (`kolay → genel → kod → planlama`) as a new job, within limits; otherwise the job is `tikandi` and you are asked.

### Workflows and reviews

A workflow runs one piece of work as a chain of step jobs. Templates live in [`akislar/`](akislar):

| Template | Steps | For |
|---|---|---|
| `gelistir` | plan → plan review → code → code review → approval | a new feature, or a change across several files |
| `kucuk-is` | code → code review → approval | a small, clear fix |

- **The review panel** reviews the code: Codex (`codex` CLI) by default, plus optional free reviewers through
  OpenCode and Antigravity (`agy`) for projects you allow, since those send the diff to an outside service. Free
  reviewers only ever see a temporary, link-free copy of the change with all tools denied.
- A **risk classifier** decides how many reviewers must agree: changes to authentication, payments, CI, migrations,
  build files or agent instructions are high risk and also get a **security reviewer**; docs- or tests-only changes are
  low risk.
- A **hakem** (referee, one small Claude call) checks each serious finding and drops false or pre-existing ones. Only
  confirmed findings send the code back to the session (at most 2 rounds). If no external reviewer answers, a Claude
  review takes over.
- The last step is **your approval card**: evidence first (how it was tested, what the Kontrol proved and did not, the
  agent's decisions, the diff summary, the review, security, how to undo), then the plan and the cost.
- **No workflow ever commits, pushes or deletes.** After you approve, committing is still your separate decision.
- The first 3 runs of each template are on probation: every step waits for you to release it.

A **manager** (one small Claude call) may answer a project's purely technical question on your behalf; you can replace
that answer from its card. Anything about scope, money, deletion or releases always comes to you.

### Group reports

Jobs added together (`--grup`) and the steps of a workflow form a group. When all are final, the server writes one
report `OFIS/Raporlar/<group>.md` (outcome, usage, verified cost per job, first-pass ratio, rework, open items) and
sends the CEO a single notice instead of one per job.

### The Karne (scorecard)

The server keeps a scorecard under `OFIS/Karne/`: one row per finished job, a summary whose main metric is **verified
cost per job**, a correction log per project and a page that measures each reviewer. From these numbers it may propose
a different model for a tier; a proposal runs as a short pilot and changes the mapping only after your plain "yes".
When the same correction appears twice, the CEO proposes one line for that project's `CLAUDE.md` or `REVIEW.md` — again
only with your approval.

### The Ar-Ge room

The built-in `arge` project is a read-only research desk.

- Once a day the server does a free check (no model call): the CLI versions of `claude`, `codex`, `opencode` and the
  list of free OpenCode models, compared with the previous day.
- Research jobs (a daily schedule, if you set one up) write an Ar-Ge report to `OFIS/ArGe/`; every claim must have a
  source link.
- **Yakala**: write `yakala: <url>` in the chat, or use the Yakala box on the Komuta masası for a link or a small
  `.txt` / `.md` / `.pdf` file, and one research job reads it and recommends *kullan* (use), *fikir al* (take the idea) or *geç* (skip).

### The office page

`http://127.0.0.1:8800` shows a 3D office (three.js, vendored) where each project has a team room and each job is a
robot at a desk. Around it:

- the **CEO chat** and the **Komuta masası** (command desk) with the CEO's steps, the decision cards and announcements;
- a decision bell, "who is working now", per-job progress lines;
- tabs: **İşler** (job board), **Raporlar**, **Kalite** (the scorecard), **Zamanlanmış** (schedules), **Son olanlar**
  (event timeline) and **Ayarlar** (settings);
- rooms for the server status ("Sunucu odası": computer load and your domains), Ar-Ge, and the reviewers.

`?demo=1` shows a demo office with fake data, `?hafif=1` lowers the render quality for slower machines.

## Requirements

- **macOS.** Autostart uses a launchd LaunchAgent, and parts of the server use macOS commands. Other systems are not
  supported.
- **Python 3.9 or newer**, standard library only. Nothing to `pip install`.
- **Claude Code CLI**, logged in, with a Claude subscription or API access. The `claude` command must be on `PATH`.
- **An Obsidian vault.** The office writes into one folder of it (`OFIS/`). Obsidian itself only needs to be installed
  if you want to read the notes there; the page opens notes with `obsidian://` links.
- Optional: the **`codex`** CLI (the default code reviewer; without it the review falls back to Claude), **`opencode`**
  and **`agy`** (free extra reviewers), and **`node`** (only for the JavaScript tests).

## Install and first run

1. Clone the repository and create your settings file:

   ```sh
   git clone <repository-url> ofis
   cd ofis
   cp ofis.example.json ofis.json
   ```

   `ofis.json` is personal and git-ignored. The server never creates it for you.

2. Edit `ofis.json`:

   - `vault_ofis` — the `OFIS` folder inside your Obsidian vault, e.g. `~/Documents/Obsidian Vault/OFIS`;
   - `sahip_adi` — your name as the office should call you (1–40 characters; default `Sahip`, "owner");
   - `ofis_adi` — the office's name shown on the page (default `Ofis`).

   You can change both names later on the Ayarlar tab.

3. Create the folders the example points at — the vault's `OFIS` folder and the Ar-Ge workspace
   (`projects.arge.path`, `~/ofis-arge` in the example):

   ```sh
   mkdir -p "$HOME/Documents/Obsidian Vault/OFIS"
   mkdir -p ~/ofis-arge
   ```

   The Ar-Ge folder does not need to be a git repository.

4. Trust the folders in Claude Code. Claude Code refuses a background session in a folder you have not trusted, so run
   `claude` once in each folder and accept the trust prompt: this repository (the CEO runs here), the Ar-Ge folder, and
   later every project folder you add.

   ```sh
   cd ~/ofis-arge && claude    # accept the trust prompt, then exit
   ```

   A job for an untrusted folder is not lost: it stays queued and starts by itself once you accept the prompt.

5. Start the server:

   ```sh
   python3 bin/server.py
   ```

   It prints `Ofis: http://127.0.0.1:8800` (or the next free port up to 8819). Only one server runs at a time.

   Or let macOS start it at every login and restart it after a crash:

   ```sh
   python3 bin/autostart.py install     # --dry-run shows what it would do
   python3 bin/autostart.py status
   python3 bin/autostart.py uninstall
   ```

   The autostarted server logs to `~/Library/Logs/ofis/server.log`. Run `install` again after `claude` or `codex` move
   or your `PATH` changes.

6. Open `http://127.0.0.1:8800`, add a project on the **Ayarlar** tab and say hello to the CEO in the chat. The first
   message starts the CEO session.

## Adding projects (the Ayarlar tab)

The **Ayarlar** (settings) tab is the one place to edit projects; you do not need to hand-edit `ofis.json`. Every save
replaces the file atomically and the running server picks it up within seconds. The CEO gets a short notice about
each change.

**Fields**

| Field | Meaning |
|---|---|
| Proje adı | the project name: lower-case letters, digits and `-`, starts with a letter or digit, at most 40 characters; cannot be renamed later; `ofis` is reserved |
| Klasör yolu | the project folder, an absolute path (`/…` or `~/…`), e.g. `~/Dev/blog` |
| Açıklama | one-line description (required, at most 300 characters) |
| Proje kuralları | the project's rules for every job (`notes`, up to 2000 characters) |
| Gelişmiş → Hassas yollar | extra sensitive path globs that make a change high risk in review |
| Gelişmiş → Durup sorması gerekenler / Asla yapmaması gerekenler / Teslim biçimi | where the project stops and asks, what it never does, how it delivers |
| Gelişmiş → Domainler | host names (e.g. `blog.example.com`) that the Sunucu odası checks for HTTPS, certificate expiry and DNS |

**A folder is refused when it:**

- does not exist, or is not an absolute path;
- is the office's own folder, or inside or above it;
- is the Obsidian vault (the parent of `vault_ofis`), or inside or above it;
- is `~/Library` or a hidden folder right under your home folder (`~/.ssh`, `~/.claude`, …), or inside one;
- is already another project's folder (nested project folders are allowed);
- matches one of your forbidden folder names (`guvenlik.yasak_yollar`, see below).

Folders are compared by file identity, not by spelling, so a different case or a symbolic link does not get around
these rules.

**Removing and changing.** A project with open work cannot be removed: a queued or running job, an open workflow, or a
schedule (even a paused one) blocks it, and so does being the built-in `arge`. Changing a project's folder is refused
while it has an open job or workflow, and it turns that project's free outside reviewers off. Removing a project keeps
its folder and its vault notes. Model tiers are not editable here; they change only through the scorecard's model
cards.

Each project card shows whether Claude Code trusts its folder and, if not, the exact `cd <folder> && claude` command to
run.

## Daily use

**Chat with the CEO.** Write what you want in plain Turkish. The CEO adds jobs, tells you who got the work and reports
the result when the job is done. For a new feature it first asks three short questions (who needs it, how we will know
it worked, what is out of scope).

**Decision cards.** When a project asks something, a workflow needs approval, or the CEO needs a yes or no, a card
appears under "CEO soruyor" and the bell counts it. Answer on the card (a button for each option, or free text). Your
answer reaches the waiting session; a second answer to the same card is refused.

**Scheduled jobs.** Ask for recurring work ("every weekday at 09:00 …"). The CEO shows you the exact schedule (what,
project, days and time, budget per run, Kontrol) and adds it only after your yes. The Zamanlanmış tab lists them. A
schedule pauses itself after two failed runs in a row.

**Announcements.** "Duyuru yap" on the Komuta masası sends one message to every running project session — only now,
for today, for this week or until a date.

**Morning summary.** Every morning (default 08:30, `sabah_ozeti`) the server writes `OFIS/Ozetler/<date>.md`:
yesterday's finished jobs with their proof and usage, pending decisions, stuck jobs, today's queue. The CEO tells you
the gist in two or three sentences.

**End-of-day review.** In the evening window (`gun_sonu`, default 20:00–24:00) the server measures the day. On a bad day
it adds one review job whose suggestions go into `OFIS/GunSonu/`; code fixes still need your word.

**Usage, not spending.** Every amount is shown as **tokens first, then the API-equivalent dollars**, e.g.
`182 bin token · API karşılığı ~$0.41`. On a Claude subscription nothing is billed per job; the dollars are an estimate
at API list prices and budgets are usage caps. Optionally, the top bar can show your plan's 5-hour and weekly usage
limits: set `limitler.acik` and let your own Claude Code statusline script write `~/.claude/ofis/limitler.json`
(`{"five_hour": {"used_percentage", "resets_at"}, "seven_day": {…}, "saved_at"}`); the office only reads that file.

**Obsidian.** Job notes, decisions (`OFIS/Kararlar/`), reports and the scorecard are all plain Markdown with
`[[wikilinks]]`; links on the page open them in Obsidian. Notes the server writes are for reading — change state only
through the page or the CEO.

## Privacy and safety

**Your privacy rules: `ofis.json` → `guvenlik`.**

```json
"guvenlik": {
  "yasak_yollar": ["old-client"],
  "ozel_klasorler": ["Private"],
  "yasak_kelimeler": ["sifre", "password", "keychain"]
}
```

- `yasak_yollar` — names of folders that must stay outside the office. Any path component equal to the name, or the
  name followed by `-`, `.`, `_` or a space (`old-client-2`), is refused everywhere: launching, reports, Kontrol,
  reviews, the page, the settings.
- `ozel_klasorler` — private folders in your vault. The guard refuses paths inside them and protects them against
  destructive commands and recursive searches.
- `yasak_kelimeler` — words a file name or command must not contain. The example ships generic credential words.

Matching ignores case and Turkish dotted/dotless `i`. A missing `guvenlik` key means the neutral defaults. A
**malformed** value (a typo such as `yasak_yolar`, a string or `null` instead of a list, an unknown field) never
silently turns into the defaults: the server and `bin/ofis.py` refuse to start with a message naming the bad field, and
the guard hook blocks every guarded tool call until you fix the file. A server that is already running keeps its last
good rules.

**Personal deny rules.** The tracked [`.claude/settings.json`](.claude/settings.json) holds only generic rules: the
guard hook, protection of the server's records under `durum/`, no hand-started `claude --bg`, and denies for MCP tools
that could write files (filesystem, Serena, GitHub writes, Postgres). Put rules that name your own absolute paths
(private vault folders, credential notes, folders to keep out) in `.claude/settings.local.json`, which is git-ignored.
Claude Code merges the two lists.

**The guard hook** ([`bin/guard.py`](bin/guard.py)) runs before every Bash, Read, Edit, Write, NotebookEdit, Glob and
Grep call in this folder. It refuses paths inside private folders and the server's trusted records, refuses
destructive commands and recursive searches on their parent folders, and blocks on any unexpected input or its own
crash.

**Honest limits.** The hook is a text check. It does **not** see a shell variable other than `$HOME`, a script written
to a file and run later, code given to an interpreter (`python3 -c`, `node -e`), aliases and shell functions, paths fed
through `xargs` or taken from a program's output. MCP or plugin tools are checked by neither the hook nor the deny
rules, unless denied outright. Every session runs as the same OS user, so a project session that really tried could
act as the CEO; that is why a session's text is always treated as data and why the server acts only on its own records.
With no `ozel_klasorler` set, nothing marks your vault as holding private notes. Treat these protections as guard rails,
not as a sandbox. Details: [`docs/gelistirici/guvenlik.md`](docs/gelistirici/guvenlik.md).

**Network.** The server binds `127.0.0.1` only, checks the `Host` and `Origin` headers, and every POST needs a token
injected into the page. Besides Claude and Codex, only the free reviewers (the diff), the Ar-Ge research (web
searches; project names and descriptions only, never code) and the domain checks reach outside services; the free
reviewers run only for projects you list in `ucretsiz_denetci_projeler`.

## Configuration reference

The main keys of `ofis.json`, as in [`ofis.example.json`](ofis.example.json):

| Key | Meaning |
|---|---|
| `ofis_adi` | the office's name on the page |
| `sahip_adi` | your display name in every text the office writes |
| `ceo_session` | the CEO session's name (`ofis-ceo`) |
| `ceo_yenileme` | when to start a fresh CEO session: context size, cold cache, a new day |
| `vault_ofis` | the `OFIS` folder in your Obsidian vault |
| `projects` | the project registry: `path`, `description`, `notes` (+ optional `hassas_yollar`, `sorumlu`, `sistem`); edit on the Ayarlar tab |
| `tiers` | per tier: `model`, `effort`, default budget `butce_usd` |
| `default_tier` | the tier when none is given (`genel`) |
| `default_budget_usd` | budget for a tier without `butce_usd` |
| `default_max_calls` | model-call limit per tier |
| `max_running`, `max_running_per_project`, `max_queued_per_project` | dispatcher limits |
| `ladder`, `max_escalations` | the escalation order after two failed Kontrols, and how often |
| `kota_yedegi` | backup model when a model hits its quota |
| `denetciler` | the code reviewers (`codex`, `opencode`, `agy` entries) |
| `ucretsiz_denetci_projeler` | projects whose diffs may go to the free outside reviewers |
| `denetci_yeter_sayisi` | how many reviewer verdicts a review needs per risk level |
| `hakem` | the referee call's model and budget |
| `guvenlik_denetcisi` | the security reviewer's model, budget, and whether it also runs on normal risk |
| `mudur_karari` | managers answering technical questions: on/off, model, budget, timeout |
| `gun_sonu` | the end-of-day review: on/off, evening window, budget |
| `hafiza_saglik` | the daily read-only health check of the vault notes |
| `model_onerisi` | thresholds for the scorecard's model proposals and pilots |
| `ofis_sahnesi` | the scene's lunch hour and the office time zone (`saat_dilimi`, default: the system's) |
| `danisman_pilotu`, `zor_is_danismani` | an advisor model for code jobs: an A/B pilot (off) and for hard jobs |
| `yakala` | the Yakala inbox: on/off, budget per item, hourly limit, file size |
| `talimat_denetimi` | the prompt audit that runs when a tier's model changes |
| `jarvis` | an optional local A2A gate for a voice / menu-bar client (off by default) |
| `limitler` | the plan usage pill and its warning thresholds |
| `guvenlik` | your privacy rules (see above) |

Optional keys, not in the example: `kontrol_timeout_s` (900), `sabah_ozeti` (`"08:30"`), `max_bekleyen_onay` (2),
`akis_deneme_kosusu` (3), `codex_timeout_s` (900), `codex_bin` / `opencode_bin` / `agy_bin` (else found on `PATH`),
`sahipsiz_oturum_saat` (3). The full list with every detail is in [`docs/GELISTIRICI.md`](docs/GELISTIRICI.md#files).

## Running the tests

```sh
python3 test/hepsi.py            # everything, in parallel (run this before a commit)
python3 test/hepsi.py --hizli    # skip the slow tests
python3 test/hepsi.py web npc    # only test files whose name contains a word
python3 -I test/test_ofis.py     # one file
```

Never use `python3 -m unittest`: the `test` folder collides with Python's own `test` package. The tests of the page
run the JavaScript with `node` and are skipped when node is missing. No browser is needed.

## Troubleshooting

**A job stays queued: "Claude bu projenin klasörüne henüz güvenmiyor".** Claude Code does not trust the folder yet. Run
`cd <folder> && claude` once and accept the prompt (the Ayarlar tab shows the command). The job then starts by itself.

**"ofis: HATA Obsidian … notlarına erişilemiyor".** The server cannot read the vault folder. Check that `vault_ofis`
exists. If it does and the server was started by launchd, macOS privacy is blocking it: open System Settings → Privacy
& Security → Full Disk Access, add the python binary the message names (its real path; press ⌘⇧G to type it), then run
`python3 bin/autostart.py install` again. `python3 bin/autostart.py status` shows the error of the latest start.

**The server does not start.**

- `ayar dosyası bulunamadı` — there is no `ofis.json` yet: `cp ofis.example.json ofis.json` and edit it.
- `ofis.json needs 'ceo_session', 'vault_ofis' and 'projects'` — one of these keys is missing.
- `ofis.json'daki 'guvenlik.…' hatalı` — your privacy rules have the wrong shape; fix the named field.
- A JSON parse error — the file is not valid JSON (a missing comma, a trailing comma).
- `Ofis server already running` — another server is running (maybe the autostarted one); this one exits.

While `ofis.json` is broken, the guard hook also blocks the tool calls of Claude Code sessions in this folder.

**The CEO still follows old rules.** A running CEO session keeps the `CLAUDE.md` it started with. After you change
`CLAUDE.md`, run:

```sh
python3 bin/ofis.py ceo-yenile
```

The next message to the CEO then starts a fresh session with a handoff note.

**Where to look.** `python3 bin/ofis.py durum` prints the job table. The server's errors and important events are in
`OFIS/Sunucu/Hatalar-<YYYY-MM>.md` in your vault, and in the terminal or `~/Library/Logs/ofis/server.log`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The developer reference is [`docs/GELISTIRICI.md`](docs/GELISTIRICI.md).

## License

[MIT](LICENSE). The vendored three.js in `web/vendor/three/` keeps its own MIT license.
