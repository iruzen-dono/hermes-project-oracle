#!/usr/bin/env python3
"""
Hermes Project Oracle — Générateur de fichiers de contexte.

Produit AGENTS.md, CLAUDE.md, ou note Obsidian à partir
d'un rapport de scan JSON. Supporte 4 templates.

Usage:
    python oracle_generate.py --scan .oracle/scan-report.json --template agents-md
    python oracle_generate.py -s rapport.json -t claude-md -o CLAUDE.md
    python oracle_generate.py -s rapport.json -t full -o ./
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("oracle-gen")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _t(text: str | None, default: str = "non spécifié") -> str:
    """Safe text with default."""
    return text if text else default


def _bullet(items: list[Any], formatter: callable = str, max_items: int = 10) -> list[str]:
    """Format a list as bullet points."""
    out = [f"- {formatter(item)}" for item in items[:max_items]]
    if len(items) > max_items:
        out.append(f"- *... et {len(items) - max_items} de plus*")
    return out


def _framework_badge(framework: str | None) -> str:
    """Return an emoji badge for a framework."""
    badges = {
        "Spring Boot": "🍃", "Django": "🎸", "FastAPI": "⚡",
        "Flask": "🌶️", "Next.js": "▲", "React": "⚛️",
        "Laravel": "🎨", "Symfony": "🎭", "Vue": "💚",
        "Express": "🚂", "NestJS": "🏗️", "Svelte": "🧡",
        "Astro": "🚀", "Gatsby": "🔥", "Rocket": "🚀",
        "Axum": "🪓", "Actix-web": "🦀", "Tauri": "📦",
        "Tokio": "🔄", "Serde": "📋",
    }
    return badges.get(framework or "", "📦")


# ── Templates ───────────────────────────────────────────────────────────────


def render_agents_md(report: dict[str, Any]) -> str:
    """Génère un AGENTS.md complet et standard."""
    name = report.get("project_name", "projet")
    langs = report.get("languages", [])
    framework = report.get("framework")
    entries = report.get("entry_points", [])
    conventions = report.get("conventions", {})
    git = report.get("git", {})
    misc = report.get("misc", {})
    build_systems = report.get("build_systems", [])

    lang_summary = ", ".join(f"{l['name']}" for l in langs[:4]) or "non détecté"
    fw_badge = _framework_badge(framework)
    fw_str = f"{fw_badge} {framework}" if framework else "non spécifié"

    lines = [
        f"# {name} — Contexte Projet",
        "",
        f"*Généré par Hermes Project Oracle — {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "## 📋 Stack technique",
        f"- **Langages** : {lang_summary}",
        f"- **Framework** : {fw_str}",
        f"- **Taille** : {report.get('file_count', '?')} fichiers, {report.get('dir_count', '?')} dossiers",
        f"- **Scan** : {report.get('scan_duration_seconds', 0):.1f}s",
        "",
    ]

    # Build systems
    if build_systems:
        lines.append("### Systèmes de build")
        for bs in build_systems:
            label = bs.get("label", bs.get("file", "?"))
            parsed = bs.get("parsed", {})
            extra = ""
            if isinstance(parsed, dict):
                if parsed.get("framework"):
                    extra = f" → {parsed['framework']}"
                if parsed.get("deps_sample"):
                    extra += f" ({len(parsed['deps_sample'])} dépendances)"
                if parsed.get("pm"):
                    extra += f" | pm: {parsed['pm']}"
            lines.append(f"- `{label}`{extra}")
        lines.append("")

    # Languages detail
    if langs:
        lines.append("### Répartition des langages")
        max_files = max(l["files"] for l in langs) if langs else 0
        bar_width = 30
        for lang in langs[:6]:
            bar_len = int((lang["files"] / max_files) * bar_width) if max_files else 0
            bar = "█" * bar_len
            lines.append(f"- {lang['name']:25s} │{bar:<{bar_width}}│ {lang['files']:5d} ({lang['ratio']}%)")
        lines.append("")

    # Entry points
    if entries:
        lines.append("## 🚪 Points d'entrée")
        for ep in entries[:8]:
            lines.append(f"- `{ep['path']}` — `{ep['type']}`")
        if len(entries) > 8:
            lines.append(f"- *... et {len(entries) - 8} autres*")
        lines.append("")

    # Conventions
    if conventions.get("test_frameworks"):
        lines.append("## 🧪 Tests")
        lines.append(f"- Framework(s) : {', '.join(conventions['test_frameworks'])}")
        if conventions.get("quality_tools"):
            lines.append(f"- Qualité : {', '.join(f'`{t}`' for t in conventions['quality_tools'][:8])}")
        lines.append("")

    if conventions.get("ci_cd"):
        lines.append("## 🔄 CI/CD")
        lines.extend(_bullet(conventions["ci_cd"]))
        lines.append("")

    if conventions.get("docker"):
        docker = conventions["docker"]
        docker_str = []
        if docker.get("has_dockerfile"):
            docker_str.append("Dockerfile ✓")
        if docker.get("has_compose"):
            docker_str.append("docker-compose ✓")
        if docker_str:
            lines.append("## 🐳 Docker")
            lines.append(f"- {' | '.join(docker_str)}")
            lines.append("")

    # Git
    if git.get("has_git"):
        lines.append("## 🔗 Git")
        lines.append(f"- **Branche** : `{git.get('branch', '?')}`")
        if git.get("remotes"):
            lines.append(f"- **Remote(s)** :")
            for r in git["remotes"][:3]:
                lines.append(f"  - `{r['name']}` → {r['url']}")
        if git.get("commit_count"):
            lines.append(f"- **Commits** : {git['commit_count']}")
        lines.append("")

    # Misc
    if misc:
        extra_lines = []
        if misc.get("readme"):
            extra_lines.append("README ✓")
        if misc.get("license"):
            extra_lines.append("LICENSE ✓")
        if misc.get("changelog"):
            extra_lines.append("CHANGELOG ✓")
        if misc.get("is_monorepo"):
            extra_lines.append("📦 MONOREPO")
        if extra_lines:
            lines.append("## 📄 Infos")
            lines.extend("  - " + x for x in extra_lines)
            lines.append("")

    # Rules for the agent
    lines.append("## ⚙️ Règles pour l'agent")
    lines.append("")
    lines.append("1. **Lis avant d'écrire** — utilise `read_file`, `search_files`")
    lines.append("2. **Respecte les conventions** du projet (lint, tests, commit style)")
    lines.append("3. **Vérifie le lint/build** avant de proposer une PR")
    lines.append("4. **Demande clarification** si une spec ou un ticket est ambigu")
    lines.append("5. **Ne modifie pas** les fichiers de config sans demander")
    if conventions.get("editor"):
        lines.append(f"6. **Éditeur** : ce projet utilise {conventions['editor']} — respecte ses settings")
    lines.append("")
    lines.append("---")
    lines.append(f"*Généré automatiquement — voir `.oracle/scan-report.json` pour les données brutes*")
    lines.append("")

    return "\n".join(lines)


def render_claude_md(report: dict[str, Any]) -> str:
    """Génère un CLAUDE.md avec les conventions de code."""
    name = report.get("project_name", "projet")
    langs = report.get("languages", [])
    conventions = report.get("conventions", {})

    lines = [
        f"# CLAUDE.md — {name}",
        "",
        "## 📐 Conventions générales",
        "- Suis les conventions du projet avant les miennes",
        "- Écris du code lisible, typé, et testé",
        "- Pas de refactor massif sans en discuter",
        "",
    ]

    # Per-language rules
    lang_map = {l["key"]: l["name"] for l in langs}

    if "python" in lang_map:
        lines.extend([
            "## 🐍 Python",
            "- **Style** : PEP 8, snake_case, 88 chars max (Black)",
            "- **Typage** : type hints obligatoires sur les fonctions publiques",
            "- **Imports** : stdlib > tiers > local, groupe alphabétique",
            "- **f-strings** : préférées à format() ou concaténation",
            "- **Docstrings** : format Google (Summary, Args, Returns)",
            "",
        ])
    if "typescript" in lang_map or "javascript" in lang_map:
        ts = "TypeScript" if "typescript" in lang_map else "JavaScript"
        lines.extend([
            f"## 💛 {ts}",
            f"- **Style** : {'strict mode, types implicites interdits' if 'TypeScript' in ts else 'ES2022+'}",
            "- **Noms** : camelCase variables/fonctions, PascalCase classes/types",
            "- **Imports** : préférer les imports nommés",
            "- **Async** : async/await, pas de .then()",
            "",
        ])
    if "java" in lang_map or "kotlin" in lang_map:
        lang = "Kotlin" if "kotlin" in lang_map else "Java"
        lines.extend([
            f"## ☕ {lang}",
            "- **Noms** : camelCase méthodes/variables, PascalCase classes",
            "- **Imports** : wildcards interdits (sauf en Kotlin)",
            "- **Nullable** : utiliser Optional/?: explicite",
            "",
        ])
    if "go" in lang_map:
        lines.extend([
            "## 🔵 Go",
            "- **Style** : gofmt, snake_case, pas de getters/setters",
            "- **Erreurs** : toujours les gérer, jamais ignorer",
            "- **Exports** : capital = exporté, minuscule = privé",
            "",
        ])
    if "rust" in lang_map:
        lines.extend([
            "## 🦀 Rust",
            "- **Style** : rustfmt, snake_case, PascalCase types",
            "- **Erreurs** : Result<T, E> plutôt que panic!",
            "- **Unsafe** : uniquement si nécessaire, documenté",
            "",
        ])
    if "php" in lang_map:
        lines.extend([
            "## 🐘 PHP",
            "- **Style** : PSR-12, camelCase, typage strict",
            "- **Conventions Laravel** : si présent, suivre les conventions du framework",
            "- **Eloquent** : query scopes, accessors/mutators si utile",
            "",
        ])

    # Test
    if conventions.get("test_frameworks"):
        lines.append("## 🧪 Tests")
        for tf in conventions["test_frameworks"]:
            lines.append(f"- Utilise `{tf}` — écris les tests AVANT le code (si possible)")
        lines.append("")

    lines.extend([
        "## 🔗 Git",
        "- Commits conventionnels : `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`",
        "- Une PR = une seule préoccupation",
        "- Squash si nécessaire",
        "",
        "## 📋 Review",
        "- Revis ton code avant de le proposer",
        "- Vérifie que les tests passent",
        "- Vérifie l'absence de warnings / erreurs",
        "",
        f"*Généré par Hermes Project Oracle — {name}*",
        "",
    ])

    return "\n".join(lines)


def render_obsidian(report: dict[str, Any]) -> str:
    """Génère une note structurée pour Obsidian vault."""
    name = report.get("project_name", "projet")
    langs = report.get("languages", [])
    framework = report.get("framework", "")
    git = report.get("git", {})
    misc = report.get("misc", {})
    now = datetime.now()

    tags = ["projet"]
    if framework:
        tags.append(framework.lower().replace(" ", "-").replace("/", "-").replace(".", ""))
    for l in langs[:3]:
        tags.append(l["key"])

    lines = [
        "---",
        f"tags: [{', '.join(tags)}]",
        f"date_creation: {now.strftime('%Y-%m-%d')}",
        f"date_scan: {now.strftime('%Y-%m-%d %H:%M')}",
        f"files_count: {report.get('file_count', '?')}",
        f"framework: {framework or 'none'}",
        "---",
        "",
        f"# {name}",
        "",
        "## Stack",
    ]
    lang_str = ", ".join(f"{l['name']} ({l['ratio']}%)" for l in langs[:5])
    lines.append(f"- **Langages** : {lang_str}")
    if framework:
        lines.append(f"- **Framework** : {framework}")
    lines.append(f"- **Taille** : {report.get('file_count', '?')} fichiers, {report.get('dir_count', '?')} dossiers")
    lines.append("")

    entries = report.get("entry_points", [])
    if entries:
        lines.extend(["## Points d'entrée"] + _bullet(entries, lambda e: f"`{e['path']}` → {e['type']}", 8))
        lines.append("")

    if git.get("has_git"):
        lines.append("## Git")
        lines.append(f"- **Branche** : `{git.get('branch', '?')}`")
        for r in git.get("remotes", []):
            lines.append(f"- `{r['name']}` : `{r['url']}`")

    lines.extend([
        "",
        "## Conventions",
        f"- Tests : {', '.join(report.get('conventions', {}).get('test_frameworks', ['non détecté']))}",
        f"- CI/CD : {', '.join(report.get('conventions', {}).get('ci_cd', ['non détecté']))}",
    ])
    if misc.get("is_monorepo"):
        lines.append("- **Monorepo** : oui")

    lines.extend([
        "",
        "## Notes",
        "",
        "*Généré par Hermes Project Oracle — scanner voir `.oracle/scan-report.json`*",
        "",
    ])
    return "\n".join(lines)


# ── Template Registry ───────────────────────────────────────────────────────

TEMPLATES: dict[str, tuple[str, callable]] = {
    "agents-md": ("AGENTS.md", render_agents_md),
    "claude-md": ("CLAUDE.md", render_claude_md),
    "obsidian": ("projet.md", render_obsidian),
}


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hermes Project Oracle — Générateur de fichiers de contexte",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples:\n"
            "  python oracle_generate.py --scan .oracle/scan-report.json\n"
            "  python oracle_generate.py -s rapport.json -t claude-md -o CLAUDE.md\n"
            "  python oracle_generate.py -s rapport.json -t full -o contexte/\n"
        ),
    )
    parser.add_argument("--scan", "-s", required=True, help="Chemin du rapport JSON (scan)")
    parser.add_argument("--output", "-o", default="AGENTS.md", help="Fichier de sortie")
    parser.add_argument("--template", "-t", default="agents-md",
                        choices=list(TEMPLATES.keys()) + ["full"],
                        help="Template à générer (défaut: agents-md)")
    parser.add_argument("--name", "-n", default=None,
                        help="Override du nom de projet pour le fichier")
    parser.add_argument("--verbose", "-v", action="store_true", help="Logs détaillés")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Load report ──
    scan_path = Path(args.scan)
    if not scan_path.exists():
        log.error("Rapport introuvable: %s", scan_path)
        sys.exit(1)
    try:
        report: dict[str, Any] = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("JSON invalide: %s", exc)
        sys.exit(1)

    project_name = args.name or report.get("project_name", "projet")
    report["project_name"] = project_name

    # ── Render ──
    if args.template == "full":
        generated = []
        for tname, (fname, renderer) in TEMPLATES.items():
            if args.output.endswith(fname):
                out_path = Path(args.output)
            else:
                out_path = Path(args.output) / fname if Path(args.output).is_dir() else Path(args.output)
            try:
                content = renderer(report)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")
                generated.append(str(out_path))
                log.info("Generated: %s", out_path)
            except Exception as exc:
                log.error("Failed to generate %s: %s", tname, exc)
        print(json.dumps({"generated": generated}))
    else:
        fname, renderer = TEMPLATES[args.template]
        output_map = {
            "agents-md": f"{project_name}-AGENTS.md",
            "claude-md": f"{project_name}-CLAUDE.md",
            "obsidian": f"{project_name}.md",
        }
        out_path = Path(args.output)
        if out_path.is_dir():
            out_path = out_path / output_map.get(args.template, fname)
        try:
            content = renderer(report)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            log.info("Generated: %s (%d lines)", out_path, content.count("\n") + 1)
            print(json.dumps({"generated": [str(out_path)]}))
        except Exception as exc:
            log.error("Generation failed: %s", exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
