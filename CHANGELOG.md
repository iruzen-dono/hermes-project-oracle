# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
