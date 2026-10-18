---
name: hermes-project-oracle
description: Scans any codebase and generates AGENTS.md, CLAUDE.md, or Obsidian project notes with real build commands, every detected framework, environment variable names, and known project pitfalls. Use when the user asks to scan a project, generate AGENTS.md or CLAUDE.md, onboard onto an unfamiliar repository, document project architecture and conventions, or push a project summary into an Obsidian vault.
---

# Project Oracle

Deep project scanner. It analyses a codebase and produces agent-ready context
files (AGENTS.md, CLAUDE.md, Obsidian note) so any coding agent understands the
project's stack, commands, conventions, and landmines in seconds. Zero
dependencies — pure Python 3.11+ standard library, cross-platform.

Unlike a naive scan, this skill also captures **human knowledge a scan cannot
see**: it interviews you for the project's intent and its known pitfalls, then
embeds both in the generated file.

## When to Use

- First time on a project — generate its AGENTS.md / CLAUDE.md
- A repo with implicit conventions an agent won't infer from code alone
- Switching between projects — seed a clean context
- Documenting architecture into an Obsidian vault
- Onboarding a new developer or AI agent to an existing codebase

## Prerequisites

- Python 3.11+
- git (optional — adds branch/remote/commit context)
- An Obsidian vault (optional — only for the vault step)

## Procedure

Follow these steps in order. Do not skip the interview — it is what makes the
output genuinely useful.

### 1. Interview for intent and pitfalls

Ask the user (see `references/interview-script.md` for the full script):

1. What does this project do, and for whom?
2. What has broken or surprised you here before? (the landmines)
3. Which commands do you actually run day-to-day?
4. What must never be touched or overwritten?
5. Which conventions are unwritten but real?

Save the answers as `intent.json` (see `examples/intent-example.json`):
`{"purpose": "...", "pitfalls": [{"area": "...", "note": "..."}]}`.

### 2. Scan

```bash
python <skill_dir>/scripts/oracle_scan.py --path <project> --output <project>/.oracle/
```

`--output` accepts a directory (`.oracle/` or `.oracle`) or an explicit JSON
file path. The directory form writes `.oracle/scan-report.json`. Keep the
output **inside** the scanned project (as shown) so it stays out of version
control. Flags: `--depth N` (tree depth, default 3), `--skip-gitignore`,
`--verbose`.

The report contains languages, **all** detected frameworks, build systems,
runnable npm scripts, entry points, test frameworks + test-file counts,
environment variable **names** (never values), git context with **credential-
masked** remotes, an auto-detected project summary, and the project tree.
The report carries **no absolute paths** (it is safe to share), and when the
project has a `.gitignore`, `.oracle/` is added to it so the scan output
stays out of version control.

### 3. Generate

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

### 4. Verify before you save

- Read the generated file. Do the commands, frameworks, and env var names look right?
- Confirm **no secrets** and **no absolute paths** leaked in.
- If `AGENTS.md` / `CLAUDE.md` already existed without markers, the script
  already refused to touch it. Show the user the diff, and only pass
  `--force` after they confirm — the project may have a hand-tuned file
  worth preserving (its `.bak` backup is kept either way).

### 5. Vault (optional)

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
| `oracle_scan.py` | Deep project scan | `.oracle/scan-report.json` |
| `oracle_generate.py` | Report → context files | AGENTS.md / CLAUDE.md / Obsidian |
| `oracle_vault.py` | Push note into Obsidian | Note in vault |

## What makes this better than a plain generator

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
- **Huge repos (>10K files)** — the scan can take 5-10s; warn the user.
- **Intent is not detected** — the scan sees the stack, not the business.
  Always ask "what is this project for?".
- **Spring Boot + Kotlin** — detected as Kotlin + Spring, not just "Java".
- **Monorepo** — scan at the root, or per-module? Ask the user which they want.

## Verification

- `cat AGENTS.md | head -40` — do structure, conventions, and entry points look right?
- Run one simple task against the project to confirm the context loads.
- Confirm no secret or absolute path leaked into the generated file.

## Portability

Front matter uses only `name` and `description`, so this skill loads unchanged
in Claude Code, Cursor, Codex CLI, OpenClaw, Gemini CLI, and any
SKILL.md-compatible agent. Keep it that way — do not add agent-specific fields.
