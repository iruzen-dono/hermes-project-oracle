---
name: hermes-project-oracle
description: Audits, verifies and generates the context file a coding agent reads (AGENTS.md, CLAUDE.md, Obsidian notes). Tells you which rules the repository backs, which it contradicts, and which are unfalsifiable noise; fails CI when the file has drifted; generates the file with real build commands, every detected framework, environment variable names, and known project pitfalls. Use when the user asks to scan a project, audit or lint an existing AGENTS.md/CLAUDE.md, stop context drift in CI, generate a context file, onboard onto an unfamiliar repository, or push a project summary into an Obsidian vault.
---

# Project Oracle

Two halves, and the audit is the one nothing else does:

- **Audit** an existing context file — `AGENTS.md`, `CLAUDE.md`, one an agent
  wrote, one copied from another project. Every line is judged against the
  repository: *verified*, *contradicted*, or *noise*.
- **Generate** the file when there is none, including the human knowledge a
  static scan cannot see.

Zero dependencies — pure Python 3.11+ standard library, cross-platform.

## When to Use

- A repo already has an `AGENTS.md` / `CLAUDE.md` — audit it before trusting it
- The context file may have drifted (a renamed script, a deleted folder, a
  framework that is no longer used)
- A CI gate is wanted so a stale context file fails the build
- First time on a project — generate its AGENTS.md / CLAUDE.md
- A repo with implicit conventions an agent won't infer from code alone
- Documenting architecture into an Obsidian vault

## Prerequisites

- Python 3.11+
- git (optional — adds branch/remote/commit context)
- An Obsidian vault (optional — only for the vault step)

## Procedure

Start with the audit if the project already has a context file: it decides
whether the file is worth keeping or must be regenerated.

### 1. Audit the existing file

```bash
python <skill_dir>/scripts/oracle_lint.py AGENTS.md --path <project>
```

Three verdicts, each earned against the repository:

| Verdict | Means |
|---|---|
| ✗ contradicted | the repo disproves it — a cited script that does not exist, a tool not in the manifests, a config file that is absent, a `strict` claim the `tsconfig.json` contradicts |
| ⚠ noise | nothing in it can be checked ("always write clean code") |
| ✓ verified | the repository backs it |

Exit is non-zero when the noise ratio exceeds the budget, so it can gate CI:
`--max-noise 20` (default 50), `--strict` (any noise fails), `--json`,
`--all` (also list rules that could not be judged).

Report the contradictions to the user **with the repository evidence** — that
is the part they cannot get from a plain lint. Then either fix the file in
place or regenerate it.

### 2. Gate the drift in CI (optional)

```bash
python <skill_dir>/scripts/oracle_check.py --path <project> --agents AGENTS.md
```

`oracle-check` re-reads the repository and exits non-zero when the generated
context no longer matches it. It compares against `.oracle/scan-report.json`,
so scan first if the report is missing — which is always the case on a fresh
CI checkout, because `.oracle/` is gitignored.

### 3. Interview for intent and pitfalls

Ask the user (see `references/interview-script.md` for the full script):

1. What does this project do, and for whom?
2. What has broken or surprised you here before? (the landmines)
3. Which commands do you actually run day-to-day?
4. What must never be touched or overwritten?
5. Which conventions are unwritten but real?

Save the answers as `intent.json` (see `references/intent-example.json`):
`{"purpose": "...", "pitfalls": [{"area": "...", "note": "..."}]}`.

### 4. Scan

```bash
python <skill_dir>/scripts/oracle_scan.py --path <project> --output <project>/.oracle/
```

`--output` accepts a directory (`.oracle/` or `.oracle`) or an explicit JSON
file path. The directory form writes `.oracle/scan-report.json`. Keep the
output **inside** the scanned project (as shown) so it stays out of version
control. Flags: `--depth N` (tree depth, default 3), `--skip-gitignore`,
`--include-vendored` (count `node_modules`/`.venv`/`.next` too — off by
default, because they are not your code), `--verbose`.

The report contains languages, **all** detected frameworks, build systems,
runnable npm scripts, entry points, test frameworks + test-file counts,
environment variable **names** (never values), git context with **credential-
masked** remotes, an auto-detected project summary, and the project tree.
The report carries **no absolute paths** (it is safe to share), and when the
project has a `.gitignore`, `.oracle/` is added to it so the scan output
stays out of version control.

### 5. Generate

```bash
python <skill_dir>/scripts/oracle_generate.py \
  --scan .oracle/scan-report.json \
  --template agents-md \
  --output <project>/AGENTS.md \
  --intent-file .oracle/intent.json
```

Templates: `agents-md`, `claude-md`, `obsidian`, `full` (all three in one pass).
Omit `--intent-file` if the user skipped the interview — the generator then
falls back to an auto-detected summary (pyproject `description` or README).

**Existing files are never clobbered silently:**

- Target does not exist → created (wrapped in `<!-- oracle:start -->` …
  `<!-- oracle:end -->` markers so later runs update it in place).
- Target exists and carries the markers → only the marked section is
  regenerated; the user's text outside the markers is preserved.
- Target exists without markers → the generator refuses (exit 2). Ask the
  user, then re-run with `--force` (the previous file is saved as `.bak`).

### 6. Verify before you save

- Re-run `oracle_lint` on what you just generated. If the generator emitted a
  rule the repository contradicts, that is a bug worth reporting, not fixable
  prose.
- Read the generated file. Do the commands, frameworks, and env var names look right?
- Confirm **no secrets** and **no absolute paths** leaked in.
- If `AGENTS.md` / `CLAUDE.md` already existed without markers, the script
  already refused to touch it. Show the user the diff, and only pass
  `--force` after they confirm — the project may have a hand-tuned file
  worth preserving (its `.bak` backup is kept either way).

### 7. Vault (optional)

```bash
python <skill_dir>/scripts/oracle_vault.py \
  --scan .oracle/scan-report.json \
  --vault <path-to-vault> \
  --intent-file .oracle/intent.json
```

`--vault` is auto-detected from common locations if omitted. `--content`/`--name`
can be used instead of `--scan` to push a raw markdown note.

## Quick Reference

| Script | Role | Output |
|--------|------|--------|
| `oracle_lint.py` | Audit a context file against the repo | verified / contradicted / noise |
| `oracle_check.py` | Fail CI when the context has drifted | exit 1 + drift list |
| `oracle_scan.py` | Deep project scan | `.oracle/scan-report.json` |
| `oracle_generate.py` | Report → context files | AGENTS.md / CLAUDE.md / Obsidian |
| `oracle_vault.py` | Push note into Obsidian | Note in vault |

## What makes this better than a plain generator

- **It judges the file that already exists** — a generator only ever writes;
  `oracle-lint` checks each rule against the repository and names the evidence.
- **Drift fails the build** — `oracle-check` exits non-zero when the file no
  longer matches the code, instead of letting a stale rule instruct the agent.
- **Every framework, not just the first** — a Next.js + Express + Socket.IO +
  React project lists all four.
- **Real commands** — npm scripts are captured with their actual shell command,
  not just the script name.
- **Environment variables** — names are read from `.env.example` (values are
  never copied; the real `.env` is never opened).
- **Secret-safe git** — remote URLs are masked (`https://***@host/...`) and
  de-duplicated; tokens never reach the output.
- **Monorepo aware** — nested `package.json` / `pyproject.toml` / `pom.xml` are
  discovered up to 2 levels deep.
- **Intent + pitfalls** — the interview output is embedded so the agent knows
  the landmines no static scan can detect.

## Pitfalls

- **Existing AGENTS.md** — never overwrite without asking; propose a merge.
- **Audit before generate** — regenerating a hand-tuned file to "fix" two
  contradictions throws away everything the team wrote.
- **`oracle-check` without a scan report** — it exits 2 and tells you to scan
  first. In CI, always scan then check.
- **Huge repos (>10K files)** — the scan can take 5-10s; warn the user.
- **Intent is not detected** — the scan sees the stack, not the business.
  Always ask "what is this project for?".
- **Spring Boot + Kotlin** — detected as Kotlin + Spring, not just "Java".
- **Monorepo** — scan at the root, or per-module? Ask the user which they want.

## Verification

- `oracle_lint AGENTS.md` returns no contradiction on a file you just generated.
- `cat AGENTS.md | head -40` — do structure, conventions, and entry points look right?
- Run one simple task against the project to confirm the context loads.
- Confirm no secret or absolute path leaked into the generated file.

## Portability

Front matter uses only `name` and `description`, so this skill loads unchanged
in Claude Code, Cursor, Codex CLI, OpenClaw, Gemini CLI, and any
SKILL.md-compatible agent. Keep it that way — do not add agent-specific fields.
