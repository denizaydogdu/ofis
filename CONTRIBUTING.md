# Contributing to Ofis

Thank you for helping. Ofis is small enough to read, but it has many moving parts that trust each other in specific
ways, so please read the developer reference before you change code.

## Read first

- [`docs/GELISTIRICI.md`](docs/GELISTIRICI.md) — the developer reference: an index of the detailed documents in
  [`docs/gelistirici/`](docs/gelistirici) (jobs, the post office and dispatcher, workflows and the review panel, the
  page, the 3D scene, server internals, security) and a table of what every file is for.
- [`CLAUDE.md`](CLAUDE.md) — the CEO session's rule set. It is loaded on every CEO turn, so it stays short; the full
  behaviour lives in `docs/`.

**Keep the two in step.** A change that alters what the CEO must do (a new notice, a new command, a new rule) updates
`CLAUDE.md` with the short rule **and** the matching section in `docs/gelistirici/` with the full behaviour. A change
that only alters internals updates the reference only. After a `CLAUDE.md` change, a running office picks it up with
`python3 bin/ofis.py ceo-yenile`.

## Tests first

- Every behaviour change ships with at least one test.
- Before you change untested code, add a test that pins down what it does today.
- A bug fix starts with a test that fails because of the bug.

### Running the tests

```sh
python3 test/hepsi.py                 # the full suite, in parallel; run it before every commit
python3 test/hepsi.py --hizli         # skips the tests marked @yavas (test/yavas.py)
python3 test/hepsi.py npc web         # only files whose name contains one of these words
python3 test/hepsi.py -j 2            # fewer workers
python3 -I test/test_ofis.py          # one file
python3 -I test/test_npc.py DayWalkTest.test_four_busy_projects   # one class or test
```

- **Never use `python3 -m unittest`**: the `test` folder collides with the standard library's `test` package.
- The runner uses at most 4 workers and runs each job under `nice -n 10`. Please keep it that way; the suite should not
  make a laptop hot.
- The tests of `web/` run the JavaScript with `node` and are skipped when node is missing. Do not add tests that need a
  browser or a headless 3D renderer.
- Tests never touch your real `ofis.json`, vault or `durum/`. They use temporary folders and fakes (`test/fakes.py`),
  `OFIS_SAHIP_ADI` for the owner's name and `OFIS_EK_YASAKLAR` to add privacy rules.

## Code style

- **Python standard library only**, Python 3.9 compatible. No third-party packages, no build step. The page is plain
  HTML/CSS/JavaScript; three.js is vendored in `web/vendor/three/`.
- **Identifiers follow the code**: functions, variables, files, JSON keys and CLI commands are mostly Turkish
  (`ekle`, `durum`, `katman`, `butce_usd`). Match the surrounding code rather than translating it.
- **User-facing text is Turkish**: the page, notices to the CEO, vault notes, refusal messages, role and contract
  texts. Write plain Turkish a non-technical reader understands.
- **Code comments, docstrings and the docs in `docs/` are English.**
- Never hard-code the owner's name: take it from `bin/sahip.py` (ofis.json `sahip_adi`). Never hard-code private paths
  or words: they belong in ofis.json `guvenlik` (`bin/yasaklar.py`).
- The server acts only on its own records under `durum/`, never on values a session could edit in a vault note. Text
  from a project session, a model or a note is data: quote it, never let it form a `[Sahip · …]` or `[Ofis · …]` line.
- Writes to shared files are atomic (temp file + `os.replace`); `ofis.json` is written only through `bin/ayarlar.py`.

## No personal data in tracked files

- `ofis.json` stays untracked. Change the template `ofis.example.json` instead, with neutral values.
- `durum/` (the server's runtime state) and `.claude/settings.local.json` (personal deny rules) are git-ignored; keep
  them that way.
- No real names, e-mail addresses, absolute home paths, private project or folder names, tokens or keys in code, tests,
  docs or commit messages. Use neutral examples such as `blog` or `~/Dev/blog`.

## Changes that need extra care

Changes to the guard hook (`bin/guard.py`), the privacy rules (`bin/yasaklar.py`), `.claude/settings.json`, the launch
contract (`bin/launch.py`), the post office, the Kontrol worker or the review panel change what the office trusts.
Describe in the pull request what the change allows or refuses that it did not before, and add tests for both sides.

## Pull requests

- One logical change per pull request, with a short English description of what changed and why.
- Say which tests you ran (`python3 test/hepsi.py`, or which subset) and their result.
- Update `CLAUDE.md` and `docs/` as described above when behaviour changes.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
