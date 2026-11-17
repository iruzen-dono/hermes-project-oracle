# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.3] — 2026-11-17

The PyPI page was the last surface still carrying claims the code could not back.

Two figures left the README. **"a 46 s scan of a Next.js repo finishes in under a
second"** could not be checked: the baseline came from a repository shape that is
not in the tree, and both clones used for testing have an empty `node_modules`,
so the pruning was never exercised at all. And **"not 71 % JavaScript from its
dependencies"** was simply wrong — on a fixture with 12 TypeScript files and a
4000-file `node_modules`, the scan reports TypeScript 100 % in 0.30 s, and
`--include-vendored` makes the same tree report JavaScript **99.7 %** across 4015
files. The mechanism is sound; the numbers attached to it were invented. The
README now carries the fixture instead.

Also removed: the emoji in the title, `(currently 77%)` beside the coverage
command, and a `pyproject` description that led with "Deep project scanner" rather
than the audit — the half with no equivalent.

**No runtime code changed.** This release exists because PyPI freezes the rendered
README into each release's metadata: the corrected page can only ship with a
version.

## [3.0.2] — 2026-11-17

`oracle-generate` wrote the current branch into every file it produced.

A generated `AGENTS.md` is committed, so `- **Branch**: `feat/whatever`` pinned a
value that changes on every checkout: the file was stale the moment it landed,
and regenerating from another branch produced a diff that meant nothing. Remotes
and the commit count stay — they only change when the repository does. Found by
generating this repository's own `AGENTS.md`.

- **fix**: no branch line in generated context files, pinned by a test
- **ci**: a `dogfood` job scans this repository and runs `oracle-check` and
  `oracle-lint` against the committed `AGENTS.md`, so it cannot drift from the
  code unnoticed
- **docs**: `CONTRIBUTING.md`, `SECURITY.md`, issue forms, and an `AGENTS.md`
  written for this repository's own contributors

## [3.0.1] — 2026-11-17

`oracle-check` reported false drift on every monorepo, immediately after a scan.

`oracle-scan` appends nested manifests in a second phase; `oracle-check`
re-derived the build-system set with a bare `detect_build_system`, which only
sees the root manifest. Comparing the two produced

    - packages/web/package.json (no longer present)

on a context file that had just been generated from that same repository. The CI
gate failed on exactly the layout the README advertises as monorepo aware, and
the GitHub Action inherited it.

Both sides now call one `detect_build_systems()`, and two tests pin the
agreement. Found by running the tool on three real projects — quotask,
memory-vault and this repository — not by the suite: 178 tests were green while
`oracle-check` was broken for anyone with a nested manifest.

- **fix**: nested manifests are visible to `oracle-check`
- **docs**: the README's demo GIF, licence badge and Docs links are absolute, so
  the PyPI page renders them instead of showing broken images

## [3.0.0] — 2026-11-17

Renamed. The package is now `project-oracle`, on PyPI and on GitHub.

`hermes` was the wrong prefix: on PyPI it collides with the Hermes model family,
so the tool was invisible in a search for what it does, and the name was 22
characters nobody types. The tool is not tied to any one agent — it checks the
context file *they all read*.

The old name is not abandoned, it is closed properly:

- `hermes-project-oracle` 3.0.0 is published as an **empty pointer**: no
  modules, no entry points, a single dependency on `project-oracle>=3.0.0`.
  `pip install -U hermes-project-oracle` therefore migrates an existing install
  in place, and its README says where it went.
- the GitHub repository was renamed `iruzen-dono/project-oracle`; GitHub
  redirects the old URLs. The action reference is now
  `iruzen-dono/project-oracle@v3`.
- the skill archive folder is now `project-oracle`, so unzipping into
  `~/.claude/skills/` no longer installs a directory named differently from the
  package it contains.

Nothing changed in the commands, the flags or the report format: this release
renames the box, not what is inside it.

## [2.5.1] — 2026-11-17

`oracle-lint` skipped every config file whose name has a single dot. The
cited-file check required a `/` or two dots, so

    - TypeScript settings live in `tsconfig.json`.

was never judged as a file claim — in a repository that has no `tsconfig.json`
it fell through to the tool check and came back ✓ because the word *TypeScript*
appears in `package.json`. Same false positive as 2.5.0, one level further out.

A bare filename is now judged when its absence would genuinely contradict the
repository: paths, dotted names, and a short list of config files people name on
purpose (`tsconfig.json`, `pyproject.toml`, `docker-compose.yml`, `package.json`,
…). A citation introduced by "add" or "create" is advice, not a claim, and is
left alone.

- **fix**: single-dot config files are judged, creation advice is not
- **build**: `.gitattributes` normalises line endings to LF in the index, so a
  Windows checkout and a Linux one produce the same bytes
- **build**: `MANIFEST.in` keeps the sdist to code, docs and tests — the tarball
  no longer ships the stale metadata (`PKG-INFO`, `entry_points.txt`, `requires.txt`, `top_level.txt`); the residual `SOURCES.txt` is setuptools' own bookkeeping and cannot be pruned.
- **ci**: `publish.yml` publishes on a tag through PyPI trusted publishing (no
  stored token) and refuses a tag that disagrees with either distribution's
  version; CI now fails if the sdist ever carries build metadata again

## [2.5.0] — 2026-11-17

`oracle-lint` was answering "verified" to a claim the repository disproves.
Verification ran the tool-name check before the cited-file check, so

    - TypeScript settings live in `tsconfig.build.json`.

came back ✓ because the word *TypeScript* appears in `package.json` — while
`tsconfig.build.json` did not exist at all. A claim about a specific file is now
judged as a file claim first: a cited path that is missing is a contradiction,
whatever else the rule mentions. Regression test:
`test_missing_config_file_outranks_a_declared_tool`.

- **feat**: `action.yml` — the repository is now a GitHub Action. `oracle-check`
  runs straight from the action checkout (no install step), and `lint: true`
  additionally audits the file against a `max-noise` budget.
- **docs**: the README leads with the audit and the drift gate instead of the
  generator — the generator is the commodity, the contradiction check is not.
  A demo GIF is generated from a real `oracle-lint` run.

## [2.4.0] — 2026-11-17

The scanner was counting what it claimed to ignore. `SKIP_DIRS` was applied to
the *results* of the walk, never to the walk itself, so every counter descended
into `node_modules`, `.venv` and `.next` and then threw the entries away.

Measured on a real Next.js project (`trade-quote`, 10 680 vendored JS files):

| | 2.3.0 | 2.4.0 |
|---|---|---|
| Scan time | 46.65 s | **0.45 s** |
| Languages | JavaScript 71.1 % / TypeScript 28.9 % | **TypeScript 97.7 % / JavaScript 2.3 %** |
| Files | 52 | 52 (`--include-vendored`: 24 155) |

The old report contradicted itself in two consecutive log lines: 10 680 + 4 346
files counted, `Files: 52` printed underneath.

### Fixed

- **Pruned traversal** — new `oracle_scan_lib/files.py` (`walk_project`,
  `iter_project_files`, `count_project_entries`) prunes `SKIP_DIRS` while
  descending instead of filtering afterwards. Used by the language breakdown,
  the file/directory counts, the template count, the entry-point search and
  `oracle-check`.
- **Language breakdown** — a TypeScript codebase is no longer reported as
  mostly JavaScript because its dependencies are.
- **Entry points** — 33 separate `rglob` scans (each descending the whole tree)
  became one pruned walk: 16.6 s → 0.01 s on the same project. Vendored
  `index.js` / `main.py` files are no longer offered as your entry points.
- **Test-file count** — 27 `rglob` scans became one walk. A dependency shipping
  `*.test.js` no longer inflates the count.
- **JUnit detection** — same pruned walk instead of four `rglob` scans.
- **Projects under a skip-named parent** — a repository living in
  `.../build/my-app` used to report zero files, because skip names were matched
  against absolute path components. They are now matched per directory name.

### Added

- **`--include-vendored`** on `oracle-scan` (and `oracle-check`) restores the
  old walk-everything behaviour for projects that keep source inside a skipped
  directory. The choice is stored as `vendored_included` in the report, and
  `oracle-check` re-counts the same way without being told.

### Changed

- **Regenerate your scan report after upgrading.** Language percentages and
  file counts will differ from a 2.3.0 report on any repository with
  dependencies installed — that is the fix, and an old report will otherwise
  look like drift.
- `oracle-check`'s size check now compares like with like: the same pruned walk
  produces both numbers.

### Verified

- 165 tests / 1 541 subtests (16 new, all pinning the pruning), ruff clean,
  mypy clean, 77 % coverage.
- Old vs new report diffed on two repositories: only `languages` changed; build
  systems, frameworks, entry points, env names, conventions and summaries are
  byte-identical.

## [2.3.0] — 2026-11-12

Generating a context file is a solved problem. Knowing whether the one you
already have is any good is not. This release adds the audit side.

### Added

- **`oracle-lint`** — reads an existing `AGENTS.md` or `CLAUDE.md` (yours, or
  one an agent generated for you) and sorts every rule into four buckets:
  - **verified** — the rule names something the repository confirms
    (`npm run build` exists, `vitest` is declared, `tsconfig.json` sets
    `strict: true`).
  - **wrong** — the rule contradicts the repository. A cited script that was
    deleted, a tool absent from every manifest, a config file that is not
    there.
  - **noise** — unfalsifiable advice: "write clean, maintainable code",
    "follow best practices", "be careful". Nothing to check, so it is pure
    inference cost.
  - **not judged** — could not be decided either way. Deliberately excluded
    from the score rather than counted against the file.
  - Prints a score: how many of the judged rules are actually useful.
  - `--json`, `--max-noise N` (default 50 %), `--strict` (any noise fails).
  - Exit `0` clean, `1` contradictions or noise over budget, `2` usage error.

### Why

Gloaguen et al. (ETH Zurich SRI / LogicStar, *ICLR 2026 Workshop on Memory for
LLM-Based Agentic Systems*) measured context files across coding agents and
LLMs: **no improvement in task success rates**, and **over 20 % more inference
cost**. Their conclusion — *"unnecessary requirements from context files make
tasks harder; human-written context files should describe only minimal
requirements"* — is the premise of this command. Every tool in this space
generates volume. This one measures it.

### Notes

- `make` was an anchor for Makefile, which made `Make sure ...` count as a
  concrete reference. It now requires `Makefile`, `make <target>`, with the
  English filler words excluded.
- 44 tests in `tests/test_oracle_lint.py`, weighted toward not calling real
  rules noise.

## [2.2.0] — 2026-11-12

Context files rot. A generated `AGENTS.md` keeps telling agents to run
`npm run build` long after that script was deleted, and nothing notices. This
release makes the drift visible, and lets CI refuse it.

### Added

- **`oracle-check`** — compares a stored scan report with the repository as it
  is now. Exits `0` when they agree, `1` on drift, `2` on usage error, so it
  drops into any CI job as a gate.
  - **Manifest contents, not just presence** — deleting a script from
    `package.json` leaves the file in place, so a file-list comparison sees
    nothing. `oracle-check` compares the scripts and console entry points
    themselves.
  - **`--agents`** — validates that commands cited in a context file still
    exist. `npm run deploy` in an `AGENTS.md` whose manifest has no `deploy`
    script is reported by name, with the scripts that *do* exist.
  - **`--json`** — machine-readable output for CI annotations.
  - **`--strict`** — promotes warnings (dependency changes, size swings) to
    errors.
  - Structural drift across build systems, languages, frameworks, entry
    points, test frameworks, quality tools, CI providers and commit
    convention.
- **31 tests** in `tests/test_oracle_check.py`, weighted toward the
  false-negative direction: a drift that goes unreported is worse than one
  reported twice.

### Notes

- `_count_files` judges skip lists against paths *relative to the project
  root*. An absolute path can legitimately contain `build` or `dist` in a
  parent directory, which previously would have suppressed the whole count.

## [2.1.0] — 2026-11-12

Distribution release. The tool now installs as a real Python package instead of
requiring a clone + zip unpack. No scanner behaviour changed.

### Added

- **`pyproject.toml`** — build via setuptools, PEP 639 license expression, version
  read dynamically from `scripts/version.py` (single source of truth, no drift).
- **Console entry points** — `oracle-scan`, `oracle-generate`, `oracle-vault` on
  `PATH` after `pipx install hermes-project-oracle` or `uv tool install`.
- **`--version` flag** on all three CLIs (`oracle-scan 2.1.0`).
- **CI `package` job** — builds sdist + wheel, runs `twine check`, installs the
  wheel and smoke-tests every entry point.
- README badges: CI status, PyPI version, supported Python versions, license.

### Changed

- CI test job now runs `pip install -e .`, so a broken `pyproject.toml` fails on
  the three-OS matrix instead of only on release.
- README install section leads with the one-command CLI install; the skill-zip
  path is kept as the documented alternative for Claude Code / Cursor / Codex /
  Hermes users.
- README quick start uses the `oracle-*` commands, with a note on the equivalent
  `python $SKILL/scripts/...` invocation for skill installs.
- Development section documents `pip install -e ".[dev]"`, mypy and the coverage
  command.

## [2.0.1] — current scanner behaviour

Baseline of the scanner as it ships today; no earlier history was recorded.

- Deep scan across 28 languages, monorepo-aware, credential-safe (remote URLs
  masked, `.env` values never copied).
- Four output templates: `agents-md`, `claude-md`, `obsidian`, `full`.
- Intent + pitfalls interview, embedded into the generated file.
- Safe regeneration through `<!-- oracle:start/end -->` markers, `--force` and
  `.bak` backups otherwise.
- 61 tests / 983 subtests across Windows, macOS and Linux, 77 % coverage.

[2.1.0]: https://github.com/iruzen-dono/hermes-project-oracle/compare/v2.0.1...v2.1.0
