# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
