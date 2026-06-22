# Hermes Project Oracle 🧠

**Deep project scanner for [Hermes Agent](https://hermes-agent.nousresearch.com).**  
Scan any codebase and generate AGENTS.md, CLAUDE.md, or Obsidian vault notes so your agent understands the project instantly.

## Features

- **28 languages detected** — Python, Java, Kotlin, TypeScript, Go, Rust, PHP, C#, Ruby, and more
- **Framework auto-detection** — Spring Boot, Next.js, Laravel, Django, FastAPI, React Native, Flutter
- **Build system detection** — Maven, Gradle, npm/yarn/pnpm, uv/pip, Cargo, Go modules, Composer
- **Convention detection** — ESLint, Prettier, Ruff, Black, Checkstyle, EditorConfig, commit style, CI/CD
- **Multi-template output** — AGENTS.md, CLAUDE.md, Obsidian vault notes, or all in one pass
- **Cross-platform** — Windows, Linux, macOS (pathlib everywhere, no platform-specific code)
- **Zero dependencies** — pure Python 3.11+ stdlib

## Quick Start

```bash
# Clone the repo
git clone https://github.com/iruzen-dono/hermes-project-oracle.git

# Copy to your Hermes skills
cp -r hermes-project-oracle ~/.hermes/skills/hermes-project-oracle

# Scan a project
python ~/.hermes/skills/hermes-project-oracle/scripts/oracle_scan.py \
  --path /path/to/your/project \
  --output .oracle/

# Generate AGENTS.md
python ~/.hermes/skills/hermes-project-oracle/scripts/oracle_generate.py \
  --scan .oracle/scan-report.json \
  --template agents-md \
  --output /path/to/your/project/AGENTS.md
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/oracle_scan.py` | Deep project scan → JSON report (288 file extensions, AST-informed) |
| `scripts/oracle_generate.py` | Report → context files (4 templates: agents-md, claude-md, obsidian, full) |
| `scripts/oracle_vault.py` | Push a structured note into Obsidian vault |

## Requirements

- Hermes Agent (any profile)
- Python 3.11+
- Git (optional, for git context in scans)

## Documentation

Full skill documentation in `SKILL.md`. The skill is auto-discovered by Hermes when placed in `~/.hermes/skills/`.

## Contributing

PRs welcome! Keep it cross-platform, add tests, preserve the zero-dependency promise.

## License

MIT
