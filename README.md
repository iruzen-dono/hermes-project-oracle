# Project Oracle 🧠

[![CI](https://github.com/iruzen-dono/hermes-project-oracle/actions/workflows/ci.yml/badge.svg)](https://github.com/iruzen-dono/hermes-project-oracle/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hermes-project-oracle.svg)](https://pypi.org/project/hermes-project-oracle/)
[![Python](https://img.shields.io/pypi/pyversions/hermes-project-oracle.svg)](https://pypi.org/project/hermes-project-oracle/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Deep project scanner that generates agent-ready context files.**

Scan any codebase and produce `AGENTS.md`, `CLAUDE.md`, or an Obsidian project
note so a coding agent — Claude Code, Cursor, Codex CLI, OpenClaw, Gemini, or
Hermes — understands the stack, the real commands, the conventions, and the
landmines instantly. **Zero dependencies**: pure Python 3.11+ standard library,
cross-platform (Windows, Linux, macOS).

Unlike a plain generator, Project Oracle also captures **human knowledge a scan
cannot see**. It interviews you for the project's intent and known pitfalls, then
embeds both in the generated file — so the agent reads the landmines before it
touches code.

## Features

- **Every framework, not just the first** — a Next.js + Express + Socket.IO + React project lists all four
- **Real, runnable commands** — npm scripts captured with their actual shell command, not just the name
- **Environment variable names** — read from `.env.example`; values are never copied and the real `.env` is never opened
- **Secret-safe git context** — remote URLs are credential-masked (`https://***@host/...`) and de-duplicated
- **28 languages detected** — Python, Java, Kotlin, TypeScript, Go, Rust, PHP, C#, Ruby, and more
- **Build system + test detection** — Maven, Gradle, npm/yarn/pnpm/bun, uv/pip, Cargo, Go modules, Composer; Jest, Vitest, pytest, JUnit, and test-file counts
- **Monorepo aware** — nested manifests discovered up to 2 levels deep
- **Intent + pitfalls interview** — embeds project purpose and known landmines
- **Safe regeneration** — an existing file is never clobbered silently: content
  between `<!-- oracle:start/end -->` markers is refreshed in place (your edits
  outside survive), anything else requires `--force` and keeps a `.bak` backup
- **Multi-template output** — AGENTS.md, CLAUDE.md, Obsidian note, or all in one pass
- **Drift detection** — `oracle-check` re-reads the repo and exits non-zero when
  the generated context no longer matches it, so CI fails instead of letting a
  stale AGENTS.md tell agents to run commands that were deleted months ago
- **Context audit** — `oracle-lint` scores an existing AGENTS.md: which rules
  the repository confirms, which it contradicts, and which are unfalsifiable
  noise. Works on files you did not generate.
- **Cross-platform** — `pathlib` everywhere, no platform-specific code

## Install

**As a CLI** — one command, nothing to clone:

```bash
pipx install hermes-project-oracle
# or
uv tool install hermes-project-oracle
```

Five commands land on your `PATH`: **`oracle-scan`**, **`oracle-generate`**,
**`oracle-vault`**, **`oracle-check`**, **`oracle-lint`**.

**As a skill** — for Claude Code, Cursor, Codex, Hermes. The zip carries only
what the skill needs (`SKILL.md`, `scripts/`, `references/`), no `.git/`, tests
or build artifacts:

```bash
git clone https://github.com/iruzen-dono/hermes-project-oracle.git
cd hermes-project-oracle
python package_skill.py          # builds hermes-project-oracle.zip + validates it

# Claude Code / generic SKILL.md agents
unzip hermes-project-oracle.zip -d ~/.claude/skills/

# Hermes Agent
unzip hermes-project-oracle.zip -d ~/.hermes/skills/
```

On Windows (PowerShell): `Expand-Archive hermes-project-oracle.zip -DestinationPath $HOME\.claude\skills\`

## Quick start

```bash
# 1. Scan a project (writes <project>/.oracle/scan-report.json,
#    and adds .oracle/ to the project's .gitignore when missing)
oracle-scan --path /path/to/project --output /path/to/project/.oracle/

# 2. Generate AGENTS.md, embedding the interview answers
oracle-generate \
  --scan .oracle/scan-report.json \
  --template agents-md \
  --output /path/to/project/AGENTS.md \
  --intent-file .oracle/intent.json

# 3. In CI: fail the build when the context has gone stale
oracle-check --path . --agents AGENTS.md

# 4. Audit a context file you already have (yours or an agent's)
oracle-lint AGENTS.md

# 5. (Optional) push a note into your Obsidian vault
oracle-vault --scan .oracle/scan-report.json --vault ~/Documents/"Obsidian Vault"
```

Running from a skill install instead? Prefix with `python $SKILL/scripts/`
(`SKILL=~/.claude/skills/hermes-project-oracle`) — the flags are identical.

`--output` accepts a directory (`.oracle/` or `.oracle`) or an explicit JSON
file path. Run any script with `--help` for all flags.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/oracle_scan.py` | Deep project scan → JSON report (28 languages, credential-safe) |
| `scripts/oracle_generate.py` | Report → context files (4 templates + optional intent file) |
| `scripts/oracle_vault.py` | Push a structured note into an Obsidian vault |

## Docs

- Full skill instructions: [`SKILL.md`](SKILL.md)
- Interview script (intent + pitfalls): [`references/interview-script.md`](references/interview-script.md)
- Example intent file: [`references/intent-example.json`](references/intent-example.json)
- Example generated output: [`references/agents-md-example.md`](references/agents-md-example.md)

## Development

```bash
pip install -e ".[dev]"
ruff check .                    # lint (deterministic via ruff.toml)
mypy scripts/ --ignore-missing-imports
pytest tests/ -v                # unit + end-to-end (scan → generate → vault)
pytest tests/ --cov=scripts     # coverage (currently 77%)
```

The end-to-end test builds a fixture Node project, runs the full pipeline, and
asserts the output is safe (no leaked tokens, no env values, no absolute paths)
and complete (commands, frameworks, env names, pitfalls).

## Contributing

PRs welcome! Keep it cross-platform, add tests, preserve the zero-dependency
promise, and never introduce network calls or credential collection.

## License

MIT
