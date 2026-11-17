# Project Oracle 🧠

[![CI](https://github.com/iruzen-dono/project-oracle/actions/workflows/ci.yml/badge.svg)](https://github.com/iruzen-dono/project-oracle/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/project-oracle.svg)](https://pypi.org/project/project-oracle/)
[![Python](https://img.shields.io/pypi/pyversions/project-oracle.svg)](https://pypi.org/project/project-oracle/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/iruzen-dono/project-oracle/blob/main/LICENSE)

**Your `AGENTS.md` says `npm run test`. The repository deleted that script six
months ago.** Every coding agent reads the context file as truth and nobody
checks it. Project Oracle checks it: which lines the repository backs, which it
contradicts, and which are unfalsifiable noise — then writes the file in the
first place when you don't have one.

![oracle-lint reporting three contradictory rules and two noise rules in a real AGENTS.md](https://raw.githubusercontent.com/iruzen-dono/project-oracle/main/docs/demo.gif)

*A real run, unedited: `oracle-lint` on a project whose `AGENTS.md` had drifted —
three rules contradicted by the repository, two unfalsifiable, one verified, exit 1.*

**Zero dependencies**: pure Python 3.11+ standard library, cross-platform
(Windows, Linux, macOS).

## The problem

A context file rots exactly the way any untested doc rots. A script gets renamed,
a folder is deleted, a "convention" is copied from another project — and the
agent follows all of it with total confidence, then spends your tokens
rediscovering what the repository already knew. It is the one file in the repo
that nothing verifies.

## Audit the file you already have

```bash
pipx install project-oracle
oracle-lint AGENTS.md
```

Three verdicts, each one earned against the repository rather than guessed:

| Verdict | Means | Real output |
|---|---|---|
| ✗ **contradicted** | the repo disproves the rule | `` `npm run test` does not exist (scripts: build, lint, start) `` |
| ⚠ **noise** | nothing in it is checkable | `no definition of 'clean' to verify against` |
| ✓ **verified** | the repo backs the rule | `` `npm run build` exists in package.json `` |

It judges a rule by looking for the claim inside it: a cited script against
`package.json`, a declared tool (`pytest`, `vitest`, `jest`, `eslint`, `ruff`,
`black`, `mypy`, `prettier`, `typescript`) against the manifests, a cited config
file against the filesystem — any path or dotted name (`config/ruff.toml`,
`tsconfig.build.json`) plus recognisable names like `tsconfig.json`,
`pyproject.toml` or `docker-compose.yml` — and a TypeScript `strict` claim
against `tsconfig.json`. A citation introduced by "add" or "create" is advice
about a file that does not exist yet, not a false description of the repository,
so it is left alone. Anchored rules it cannot judge are reported as *not judged*
instead of being silently counted — `--all` lists them.

Exit is non-zero when too much of the file is noise, so it can gate CI:

```bash
oracle-lint AGENTS.md --max-noise 20     # allow 20% noise (default 50)
oracle-lint CLAUDE.md --strict           # any noise at all fails
oracle-lint AGENTS.md --json             # machine-readable
```

**Works on files you did not generate.** That is the point: an agent wrote your
`CLAUDE.md`, or you copied it from another project, or it drifted for a year
while nobody read it.

## Stop the drift in CI

`oracle-check` re-reads the repository and exits non-zero when the generated
context no longer matches it — so the stale file fails the build instead of
lying to the next agent:

```bash
oracle-check --path . --agents AGENTS.md
```

As a GitHub Action, with no install step — it runs the scripts from its own
checkout:

```yaml
- uses: actions/checkout@v5
- uses: iruzen-dono/project-oracle@v3
  with:
    agents: AGENTS.md
    lint: "true"      # also audit the file for noise
    max-noise: "20"   # fail above 20% noise
```

## Generate the file

When there is no context file yet, the scanner writes one — and it keeps the part
no scan can see. It interviews you for the project's intent and known pitfalls,
then embeds both, so the agent reads the landmines before it touches code.

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

# 3. (Optional) push a note into your Obsidian vault
oracle-vault --scan .oracle/scan-report.json --vault ~/Documents/"Obsidian Vault"
```

Four templates (`agents-md`, `claude-md`, an Obsidian note, or all in one pass),
`--output` accepting a directory (`.oracle/` or `.oracle`) or an explicit JSON
file path, and safe regeneration: content between `<!-- oracle:start/end -->`
markers is refreshed in place so your edits outside survive; anything else
requires `--force` and keeps a `.bak` backup.

## What the scanner gets right

- **Every framework, not just the first** — a Next.js + Express + Socket.IO + React project lists all four
- **Real, runnable commands** — npm scripts captured with their actual shell command, not just the name
- **Environment variable names** — read from `.env.example`; values are never copied and the real `.env` is never opened
- **Secret-safe git context** — remote URLs are credential-masked (`https://***@host/...`) and de-duplicated
- **28 languages detected** — Python, Java, Kotlin, TypeScript, Go, Rust, PHP, C#, Ruby, and more
- **Build system + test detection** — Maven, Gradle, npm/yarn/pnpm/bun, uv/pip, Cargo, Go modules, Composer; Jest, Vitest, pytest, JUnit, and test-file counts
- **Monorepo aware** — nested manifests discovered up to 2 levels deep
- **Honest numbers, fast** — `node_modules`, `.venv`, `.next`, `dist` and the rest are pruned *during* the walk instead of filtered afterwards, so a TypeScript project is reported as TypeScript (not 71 % JavaScript from its dependencies) and a 46 s scan of a Next.js repo finishes in under a second. `--include-vendored` restores the old walk-everything behaviour, and the choice is recorded in the report so `oracle-check` re-counts the same way
- **Cross-platform** — `pathlib` everywhere, no platform-specific code

## Install

Five commands land on your `PATH`: **`oracle-scan`**, **`oracle-generate`**,
**`oracle-vault`**, **`oracle-check`**, **`oracle-lint`**.

```bash
pipx install project-oracle
# or
uv tool install project-oracle
```

> **Renamed in 3.0.0.** The package used to be published as
> `hermes-project-oracle`, and the repository was `iruzen-dono/hermes-project-oracle`.
> The old name still installs: its final release is an empty pointer that depends
> on this package, so an existing install migrates itself on upgrade. New installs
> use the name above.

**As a skill** — for Claude Code, Cursor, Codex, Hermes. The zip carries only
what the skill needs (`SKILL.md`, `scripts/`, `references/`, plus `LICENSE` and
`README.md`), no `.git/`, tests or build artifacts:

```bash
git clone https://github.com/iruzen-dono/project-oracle.git
cd project-oracle
python package_skill.py          # builds project-oracle.zip + validates it

# Claude Code / generic SKILL.md agents
unzip project-oracle.zip -d ~/.claude/skills/

# Hermes Agent
unzip project-oracle.zip -d ~/.hermes/skills/
```

On Windows (PowerShell): `Expand-Archive project-oracle.zip -DestinationPath $HOME\.claude\skills\`

Running from a skill install instead? Prefix with `python $SKILL/scripts/`
(`SKILL=~/.claude/skills/project-oracle`) — the flags are identical. Run
any script with `--help` for all flags.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/oracle_lint.py` | Audit a context file: verified / contradicted / noise |
| `scripts/oracle_check.py` | Fail CI when the context has drifted from the repo |
| `scripts/oracle_scan.py` | Deep project scan → JSON report (28 languages, credential-safe) |
| `scripts/oracle_generate.py` | Report → context files (4 templates + optional intent file) |
| `scripts/oracle_vault.py` | Push a structured note into an Obsidian vault |

## Docs

- Full skill instructions: [`SKILL.md`](https://github.com/iruzen-dono/project-oracle/blob/main/SKILL.md)
- Interview script (intent + pitfalls): [`references/interview-script.md`](https://github.com/iruzen-dono/project-oracle/blob/main/references/interview-script.md)
- Example intent file: [`references/intent-example.json`](https://github.com/iruzen-dono/project-oracle/blob/main/references/intent-example.json)
- Example generated output: [`references/agents-md-example.md`](https://github.com/iruzen-dono/project-oracle/blob/main/references/agents-md-example.md)

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
