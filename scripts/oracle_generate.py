#!/usr/bin/env python3
"""
Project Oracle — context file generator.

Produces AGENTS.md, CLAUDE.md, or an Obsidian note from a scan JSON report.
Supports 4 templates and an optional intent file (project purpose + known
pitfalls) gathered from the user via interview.

Usage:
    python oracle_generate.py --scan .oracle/scan-report.json --template agents-md
    python oracle_generate.py -s report.json -t claude-md -o CLAUDE.md
    python oracle_generate.py -s report.json -t full -o context/
    python oracle_generate.py -s report.json -i intent.json
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from version import __version__
except ImportError:  # scripts/ not on sys.path — visible, not silently wrong
    __version__ = "unknown"

try:
    from safe_io import atomic_write
except ImportError:  # standalone copy — minimal atomic fallback (temp + replace)
    import os
    import tempfile

    def atomic_write(target: Path, content: str,
                     must_stay_under_root: Path | None = None) -> None:
        """Fallback atomic write (see safe_io.atomic_write for the full contract)."""
        target = Path(target)
        if target.is_symlink():
            raise ValueError(
                f"refusing to write through an existing symlink: {target}")
        if (must_stay_under_root is not None
                and not target.resolve().is_relative_to(must_stay_under_root.resolve())):
            raise ValueError(f"refusing to write outside the root: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent),
                                   prefix=f".{target.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, str(target))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("oracle-gen")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _t(text: str | None, default: str = "not specified") -> str:
    """Safe text with default."""
    return text if text else default


def _bullet(items: list[Any], formatter: Callable[[Any], str] = str,
            max_items: int = 10) -> list[str]:
    """Format a list as bullet points."""
    out = [f"- {formatter(item)}" for item in items[:max_items]]
    if len(items) > max_items:
        out.append(f"- *... and {len(items) - max_items} more*")
    return out


def _sanitize_untrusted(text: Any) -> str:
    """Neutralize text read from the scanned project before it is copied back.

    Text from an unknown repo (README, manifest, docstring, interview) is
    re-injected as *instructions* into AGENTS.md — it is an injection vector.
    Everything is flattened onto a single line (inserting a `##` title becomes
    impossible), update markers `<!-- oracle:… -->` are neutralized (otherwise
    the next regeneration would corrupt the file) and the remaining Markdown
    characters are escaped so text stays text.
    """
    # Strip C0 (0x00-0x1F) and C1 (0x80-0x9F) control chars, plus U+2028/2029
    # (line/paragraph separators that break files without being visible).
    # \t/\n/\r survive here and are collapsed to spaces by the split below;
    # everything else that is a control char (NUL, ESC, DEL, C1, …) is dropped.
    def _keep(ch: str) -> bool:
        o = ord(ch)
        if ch in ("\t", "\n", "\r"):
            return True
        if 0x2028 <= o <= 0x2029:  # line/paragraph separator
            return False
        if o < 0x20 or o in (0x7F, 0x85):  # C0 + DEL + NEL
            return False
        return not (0x80 <= o <= 0x9F)  # C1

    flat = "".join(ch for ch in str(text) if _keep(ch))
    flat = " ".join(flat.split())
    flat = flat.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    flat = flat.replace("`", "'")
    if len(flat) > 300:
        flat = flat[:297].rstrip() + "…"
    return flat


def _cite(text: Any) -> str:
    """Aplatit et présente le texte non fiable comme une citation (blockquote)."""
    return f"> {_sanitize_untrusted(text)}"


# ── Templates ───────────────────────────────────────────────────────────────


def _language_commands(report: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Evidence-based toolchain commands for Python, Rust and Go.

    A group is only produced when its manifest actually exists at the project
    root (``pyproject.toml``/``setup.py``, ``Cargo.toml``, ``go.mod``) — a
    command is never invented from a language count alone. Test and lint
    commands are added only when the scan found real configuration
    (pytest in detected test frameworks, ruff/black configured).
    """
    root_manifests = {
        Path(str(bs.get("file", ""))).name
        for bs in report.get("build_systems", [])
        if not str(bs.get("label", "")).startswith("nested:")
    }
    conv = report.get("conventions", {})
    groups: list[tuple[str, list[str]]] = []

    if root_manifests & {"pyproject.toml", "setup.py", "setup.cfg"}:
        cmds = ["python -m pip install -e ."]
        if "pytest" in (conv.get("test_frameworks") or []):
            cmds.append("python -m pytest")
        quality = set(conv.get("quality_tools") or [])
        if quality & {"ruff.toml", ".ruff.toml"}:
            cmds.append("ruff check .")
        if conv.get("python_formatter") == "Black":
            cmds.append("black .")
        groups.append(("Python", cmds))

    if "Cargo.toml" in root_manifests:
        groups.append(("Rust", ["cargo build", "cargo test"]))

    if "go.mod" in root_manifests:
        groups.append(("Go", ["go build ./...", "go test ./..."]))

    return groups


def render_agents_md(report: dict[str, Any]) -> str:
    """Generate a complete, standard AGENTS.md."""
    name = report.get("project_name", "project")
    langs = report.get("languages", [])
    frameworks = report.get("frameworks") or (
        [report["framework"]] if report.get("framework") else []
    )
    entries = report.get("entry_points", [])
    conventions = report.get("conventions", {})
    git = report.get("git", {})
    misc = report.get("misc", {})
    build_systems = report.get("build_systems", [])
    env_vars = report.get("env_vars", {})
    intent = report.get("intent", {})

    lang_summary = ", ".join(g["name"] for g in langs[:5]) or "not detected"
    fw_str = ", ".join(frameworks) if frameworks else "not specified"

    lines = [
        f"# {name} — Project Context",
        "",
        (
            f"*Generated by Project Oracle v{report.get('version') or __version__} — "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        ),
        "",
    ]

    # Purpose & pitfalls FIRST — agents must grasp the "why" before the "how".
    # Human knowledge (interview) wins; a heuristic scan summary is a fallback
    # (issue #5) so a skipped interview never leaves the file without context.
    # All of this text comes from an untrusted project, so it is flattened,
    # marker-escaped and quoted, never recopied verbatim as instructions.
    if intent.get("purpose"):
        lines.append("## Project intent")
        lines.append(_cite(intent["purpose"]))
        lines.append("")
    elif report.get("summary"):
        lines.append("## Project summary")
        lines.append(_cite(report["summary"]))
        lines.append("")
        src = report.get("summary_source") or "auto-detected"
        lines.append(f"*(source: {_sanitize_untrusted(src)})*")
        lines.append("")
    if intent.get("pitfalls"):
        lines.append("## Known pitfalls")
        lines.append("*(reported by the project owner — read before touching these areas)*")
        for p in intent["pitfalls"][:15]:
            if isinstance(p, dict):
                title = _sanitize_untrusted(p.get("area", "General"))
                note = _sanitize_untrusted(p.get("note", ""))
                lines.append(f"- **{title}**: {note}")
            else:
                lines.append(f"- {_sanitize_untrusted(p)}")
        lines.append("")

    lines.append("## Stack")
    lines.append(f"- **Languages**: {lang_summary}")
    lines.append(f"- **Frameworks**: {fw_str}")
    lines.append(
        f"- **Size**: {report.get('file_count', '?')} files, "
        f"{report.get('dir_count', '?')} directories"
    )
    lines.append("")

    # Build systems (root manifests)
    root_bs = [bs for bs in build_systems if not bs.get("label", "").startswith("nested:")]
    nested_bs = [bs for bs in build_systems if bs.get("label", "").startswith("nested:")]
    if root_bs:
        lines.append("### Build systems & manifests")
        for bs in root_bs:
            label = bs.get("label", bs.get("file", "?"))
            parsed = bs.get("parsed", {})
            extra = ""
            if isinstance(parsed, dict):
                if parsed.get("frameworks"):
                    extra = f" → {', '.join(parsed['frameworks'])}"
                elif parsed.get("framework"):
                    extra = f" → {parsed['framework']}"
                if parsed.get("pm"):
                    extra += f" (pm: {parsed['pm']})"
            lines.append(f"- `{label}`{extra}")
        lines.append("")

    # npm scripts with their real commands (agents need runnable commands)
    npm_scripts: dict[str, str] = {}
    pm = "npm"
    for bs in build_systems:
        parsed = bs.get("parsed", {})
        if isinstance(parsed, dict) and isinstance(parsed.get("scripts"), dict):
            for k, v in parsed["scripts"].items():
                npm_scripts.setdefault(k, v)
            if parsed.get("pm") and not bs.get("label", "").startswith("nested:"):
                pm = parsed["pm"]
    if npm_scripts:
        run = {"npm": "npm run", "yarn": "yarn", "pnpm": "pnpm run",
               "bun": "bun run"}.get(pm, "npm run")
        lines.append("### Commands (from package.json)")
        for k, v in list(npm_scripts.items())[:12]:
            lines.append(f"- `{run} {k}` → `{v}`")
        lines.append("")

    # Per-language toolchain commands (Python / Rust / Go) — only when the
    # root manifest that makes them real was seen during the scan.
    lang_cmds = _language_commands(report)
    if lang_cmds:
        lines.append("### Language commands")
        for lang, cmds in lang_cmds:
            lines.append(f"- **{lang}**: " + " · ".join(f"`{c}`" for c in cmds))
        lines.append("")

    if nested_bs:
        lines.append("### Nested packages (monorepo)")
        for bs in nested_bs[:10]:
            parsed = bs.get("parsed", {})
            fws: list[str] = []
            if isinstance(parsed, dict):
                fws = parsed.get("frameworks") or (
                    [parsed["framework"]] if parsed.get("framework") else []
                )
            suffix = f" — {', '.join(fws)}" if fws else ""
            lines.append(f"- `{bs.get('file', '?')}`{suffix}")
        lines.append("")

    # Languages detail
    if langs:
        lines.append("### Language breakdown")
        max_files = max(g["files"] for g in langs) if langs else 0
        bar_width = 24
        for lang in langs[:6]:
            bar_len = int((lang["files"] / max_files) * bar_width) if max_files else 0
            bar = "#" * bar_len
            lines.append(
                f"- {lang['name']:22s} {bar:<{bar_width}} {lang['files']:5d} ({lang['ratio']}%)"
            )
        lines.append("")

    # Environment variables — names only, values are never copied
    if env_vars:
        lines.append("## Environment variables")
        lines.append("*(names only — values are never copied; see the example file for format)*")
        for fname, names in env_vars.items():
            lines.append(f"- From `{fname}`: " + ", ".join(f"`{n}`" for n in names[:20]))
        lines.append("")

    # Entry points
    if entries:
        lines.append("## Entry points")
        lines.extend(f"- `{ep['path']}` — {ep['type']}" for ep in entries[:8])
        if len(entries) > 8:
            lines.append(f"- *... and {len(entries) - 8} more*")
        lines.append("")

    # Tests
    if conventions.get("test_frameworks") or conventions.get("test_file_count"):
        lines.append("## Tests")
        if conventions.get("test_frameworks"):
            lines.append(f"- Frameworks: {', '.join(conventions['test_frameworks'])}")
        if conventions.get("test_file_count"):
            lines.append(f"- Test files found: {conventions['test_file_count']}")
        if conventions.get("quality_tools"):
            lines.append(
                "- Quality tooling: "
                + ", ".join(f"`{t}`" for t in conventions["quality_tools"][:8])
            )
        lines.append("")

    if conventions.get("ci_cd"):
        lines.append("## CI/CD")
        lines.extend(_bullet(conventions["ci_cd"]))
        lines.append("")

    if conventions.get("docker"):
        docker = conventions["docker"]
        docker_str = []
        if docker.get("has_dockerfile"):
            docker_str.append("Dockerfile")
        if docker.get("has_compose"):
            docker_str.append("docker-compose")
        if docker_str:
            lines.append("## Docker")
            lines.append(f"- {' | '.join(docker_str)}")
            lines.append("")

    # Git
    if git.get("has_git"):
        lines.append("## Git")
        lines.append(f"- **Branch**: `{git.get('branch', '?')}`")
        if git.get("remotes"):
            lines.append("- **Remote(s)**:")
            lines.extend(
                f"  - `{r['name']}` → {r['url']}" for r in git["remotes"][:3]
            )
        if git.get("commit_count"):
            lines.append(f"- **Commits**: {git['commit_count']}")
        lines.append("")

    # Misc
    if misc:
        extra_lines = []
        if misc.get("readme"):
            extra_lines.append("README present")
        if misc.get("license"):
            extra_lines.append("LICENSE present")
        if misc.get("changelog"):
            extra_lines.append("CHANGELOG present")
        if misc.get("is_monorepo"):
            extra_lines.append("MONOREPO")
        if extra_lines:
            lines.append("## Repository")
            lines.extend("  - " + x for x in extra_lines)
            lines.append("")

    # Rules for the agent
    lines.append("## Rules for agents")
    lines.append("")
    lines.append("1. **Read before writing** — inspect existing files and conventions first")
    lines.append("2. **Follow project conventions** (lint, formatting, commit style)")
    has_tests = bool(
        conventions.get("test_frameworks") or conventions.get("test_file_count")
    )
    if has_tests:
        lines.append("3. **Verify lint/build/tests** pass before proposing a change")
    else:
        lines.append(
            "3. **Verify lint/build** passes before proposing a change "
            "(no test suite detected — do not invent one)"
        )
    lines.append("4. **Ask for clarification** when a spec or ticket is ambiguous")
    lines.append("5. **Do not modify config files** without asking")
    if conventions.get("editor"):
        lines.append(
            f"6. **Editor**: this project uses {conventions['editor']} — respect its settings"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "*Generated by Project Oracle — "
        "github.com/iruzen-dono/hermes-project-oracle*"
    )
    lines.append("")

    return "\n".join(lines)


def render_claude_md(report: dict[str, Any]) -> str:
    """Generate a CLAUDE.md focused on code conventions."""
    name = report.get("project_name", "project")
    langs = report.get("languages", [])
    conventions = report.get("conventions", {})

    lines = [
        f"# CLAUDE.md — {name}",
        "",
        "## General conventions",
        "- Follow the project's existing conventions before your own",
        "- Write readable, maintainable code",
        "- No mass refactoring without discussion",
        "",
    ]

    # Per-language sections. Rules come from DETECTED project config —
    # never invented: an agent obeying a rule the project does not have
    # is worse than no rule at all.
    lang_map = {g["key"]: g["name"] for g in langs}

    if "python" in lang_map:
        lines.extend(["## Python", "- **Idiom**: PEP 8, snake_case, PascalCase classes"])
        if conventions.get("line_length"):
            source = conventions.get("line_length_source", "project config")
            lines.append(
                f"- **Line length**: {conventions['line_length']} characters ({source})"
            )
        if conventions.get("python_formatter"):
            lines.append(f"- **Formatter**: {conventions['python_formatter']} (configured)")
        lines.append("- Mirror the naming and structure of the module you are editing")
        lines.append("")
    if "typescript" in lang_map or "javascript" in lang_map:
        ts = "TypeScript" if "typescript" in lang_map else "JavaScript"
        lines.extend([
            f"## {ts}",
            f"- **Style**: {'strict mode, no implicit any' if ts == 'TypeScript' else 'ES2022+'}",
            "- **Names**: camelCase variables/functions, PascalCase classes/types",
            "- **Imports**: prefer named imports",
            "- **Async**: async/await, not .then()",
            "",
        ])
    if "java" in lang_map or "kotlin" in lang_map:
        lang = "Kotlin" if "kotlin" in lang_map else "Java"
        lines.extend([
            f"## {lang}",
            "- **Names**: camelCase methods/variables, PascalCase classes",
            "- **Imports**: no wildcards (except in Kotlin)",
            "- **Nullability**: use Optional / explicit ?: handling",
            "",
        ])
    if "go" in lang_map:
        lines.extend([
            "## Go",
            "- **Style**: gofmt, snake_case, no getters/setters",
            "- **Errors**: always handle them, never ignore",
            "- **Exports**: Capital = exported, lowercase = private",
            "",
        ])
    if "rust" in lang_map:
        lines.extend([
            "## Rust",
            "- **Style**: rustfmt, snake_case, PascalCase types",
            "- **Errors**: Result<T, E> over panic!",
            "- **Unsafe**: only when necessary, documented",
            "",
        ])
    if "php" in lang_map:
        lines.extend([
            "## PHP",
            "- **Style**: PSR-12, camelCase, strict typing",
            "- **Laravel conventions**: if present, follow the framework's conventions",
            "- **Eloquent**: query scopes, accessors/mutators where useful",
            "",
        ])

    # Tests — only when there is real evidence (config or test files on disk)
    if conventions.get("test_frameworks"):
        lines.append("## Tests")
        lines.extend(f"- Test runner: `{tf}`" for tf in conventions["test_frameworks"])
        if conventions.get("test_file_count"):
            lines.append(
                f"- {conventions['test_file_count']} test file(s) found on disk"
            )
        lines.append("")

    lines.extend([
        "## Git",
    ])
    commit_conv = conventions.get("commit_convention", "")
    if commit_conv.startswith("conventional-commits"):
        lines.append(
            "- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`"
        )
    elif commit_conv:
        lines.append(f"- Commit style: {commit_conv}")
    else:
        lines.append("- Match the existing commit message style")
    lines.extend([
        "- One PR = one concern",
    ])
    if commit_conv:
        # Only suggest squashing when a structured convention is actually in use.
        lines.append("- Squash if needed before merging")
    lines.append("")
    lines.extend([
        "## Review",
        "- Review your code before proposing it",
    ])
    if conventions.get("test_frameworks") or conventions.get("test_file_count"):
        lines.append("- Verify tests pass")
    else:
        lines.append("- No test suite detected — do not invent one; verify by running the app")
    lines.extend([
        "- Verify no warnings / errors remain",
        "",
        f"*Generated by Project Oracle — {name}*",
        "",
    ])

    return "\n".join(lines)


def render_obsidian(report: dict[str, Any]) -> str:
    """Generate a structured note for an Obsidian vault."""
    name = report.get("project_name", "project")
    langs = report.get("languages", [])
    frameworks = report.get("frameworks") or (
        [report["framework"]] if report.get("framework") else []
    )
    git = report.get("git", {})
    misc = report.get("misc", {})
    intent = report.get("intent", {})
    now = datetime.now()

    tags = ["project"]
    tags.extend(
        fw.lower().replace(" ", "-").replace("/", "-").replace(".", "")
        for fw in frameworks[:3]
    )
    tags.extend(g["key"] for g in langs[:3])

    lines = [
        "---",
        f"tags: [{', '.join(tags)}]",
        f"date_created: {now.strftime('%Y-%m-%d')}",
        f"date_scanned: {now.strftime('%Y-%m-%d %H:%M')}",
        f"files_count: {report.get('file_count', '?')}",
        f"frameworks: [{', '.join(frameworks) if frameworks else 'none'}]",
        "---",
        "",
        f"# {name}",
        "",
        "## Stack",
    ]
    lang_str = ", ".join(f"{g['name']} ({g['ratio']}%)" for g in langs[:5])
    lines.append(f"- **Languages**: {lang_str}")
    if frameworks:
        lines.append(f"- **Frameworks**: {', '.join(frameworks)}")
    lines.append(
        f"- **Size**: {report.get('file_count', '?')} files, "
        f"{report.get('dir_count', '?')} directories"
    )
    lines.append("")

    entries = report.get("entry_points", [])
    if entries:
        lines.extend(
            ["## Entry points"]
            + _bullet(entries, lambda e: f"`{e['path']}` → {e['type']}", 8)
        )
        lines.append("")

    if git.get("has_git"):
        lines.append("## Git")
        lines.append(f"- **Branch**: `{git.get('branch', '?')}`")
        lines.extend(
            f"- `{r['name']}`: `{r['url']}`"
            for r in git.get("remotes", [])[:3]
        )
        lines.append("")

    conv = report.get("conventions", {})
    lines.extend([
        "## Conventions",
        f"- Tests: {', '.join(conv.get('test_frameworks', ['not detected']))}",
        f"- CI/CD: {', '.join(conv.get('ci_cd', ['not detected']))}",
    ])
    if misc.get("is_monorepo"):
        lines.append("- **Monorepo**: yes")

    if intent.get("purpose"):
        lines.extend(["", "## Intent", "", str(intent["purpose"]).strip()])
    if intent.get("pitfalls"):
        lines.extend(["", "## Known pitfalls"])
        for p in intent["pitfalls"][:15]:
            if isinstance(p, dict):
                lines.append(f"- **{p.get('area', 'General')}**: {p.get('note', '')}")
            else:
                lines.append(f"- {p}")

    lines.extend([
        "",
        "## Notes",
        "",
        "*Generated by Project Oracle — "
        "github.com/iruzen-dono/hermes-project-oracle*",
        "",
    ])
    return "\n".join(lines)


# ── Template Registry ───────────────────────────────────────────────────────

TEMPLATES: dict[str, tuple[str, Callable[[dict[str, Any]], str]]] = {
    "agents-md": ("AGENTS.md", render_agents_md),
    "claude-md": ("CLAUDE.md", render_claude_md),
    "obsidian": ("project.md", render_obsidian),
}


# ── Safe output — never destroy hand-written content silently ──────────────

MARKER_START = "<!-- oracle:start -->"
MARKER_END = "<!-- oracle:end -->"


def _wrap_markers(content: str) -> str:
    """Wrap generated content in update markers (skipped for YAML frontmatter)."""
    if content.startswith("---"):
        # Obsidian-style frontmatter must stay at byte 0 of the file.
        return content
    return f"{MARKER_START}\n{content.strip()}\n{MARKER_END}\n"


def render_final(out_path: Path, content: str, force: bool) -> tuple[str, str]:
    """Compute the final text `out_path` SHOULD contain, without writing it.

    Same decision rules as `write_output`:
      * file missing            -> markers-wrapped content (frontmatter files
                                   are left untouched by `_wrap_markers`)
      * file has oracle markers -> ONLY the text between them is replaced
      * file exists, no markers -> refuse with exit code 2 unless `force`

    Returns ``(final_text, action)`` with action in
    ``{"created", "merged", "overwritten"}``. Nothing is written and no
    backup is made — `--check`/`--diff` rely on that purity.
    """
    if not out_path.exists():
        return _wrap_markers(content), "created"

    existing = out_path.read_text(encoding="utf-8")
    start = existing.find(MARKER_START)
    end = existing.find(MARKER_END)
    if start != -1 and end != -1 and end >= start:
        merged = (
            existing[: start + len(MARKER_START)]
            + "\n"
            + content.strip()
            + "\n"
            + existing[end:]
        )
        return merged, "merged"

    if not force:
        log.error(
            "%s already exists and carries no %s/%s markers.\n"
            "  • Re-run with --force to overwrite it (the current file is\n"
            "    first backed up to %s), or\n"
            "  • Wrap the parts you want regenerated with those markers so\n"
            "    future runs update in place and keep your edits.",
            out_path, MARKER_START, MARKER_END, out_path.name + ".bak",
        )
        sys.exit(2)

    return _wrap_markers(content), "overwritten"


def write_output(out_path: Path, content: str, force: bool) -> str:
    """Write `content` without clobbering existing work (see `render_final`
    for the decision rules). Backs up to `.bak` before an overwrite.

    Returns one of: "created", "merged", "overwritten".
    """
    final, action = render_final(out_path, content, force)
    if action == "created":
        out_path.parent.mkdir(parents=True, exist_ok=True)
    elif action == "merged":
        log.info("Updated marked section in %s — text outside markers preserved",
                 out_path)
    elif action == "overwritten":
        existing = out_path.read_text(encoding="utf-8")
        backup = out_path.with_name(out_path.name + ".bak")
        atomic_write(backup, existing)
        log.warning("Overwrote %s — previous content saved to %s", out_path, backup)
    atomic_write(out_path, final)
    return action


def _dry_run(plan: list[tuple[str, Path, Any]], report: dict[str, Any],
             show_diff: bool, force: bool) -> int:
    """Implement ``--check`` / ``--diff``: compute drift without writing anything.

    For every planned output, compute the text ``write_output`` WOULD put on
    disk (markers-aware) and compare it with the file currently there. Prints
    ``{"changed": bool, "paths": [...]}`` on stdout, plus a unified diff to
    stdout when ``show_diff``. Returns the process exit code: 3 when at least
    one output would change, 0 when everything is already up to date.

    ``force`` is passed as True so that an existing marker-less file is
    reported as drift instead of aborting with the overwrite refusal: the
    question answered here is "would the bytes change", not "may I write".
    """
    changed_paths: list[str] = []
    for tname, out_path, renderer in plan:
        try:
            content = renderer(report)
        except Exception as exc:  # noqa: BLE001 — a broken report must not kill a drift check
            log.error("Failed to render %s: %s", tname, exc)
            continue
        final, action = render_final(out_path, content, force)
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        if existing == final:
            log.info("Up to date: %s", out_path)
            continue
        changed_paths.append(str(out_path))
        if show_diff:
            sys.stdout.writelines(
                difflib.unified_diff(
                    (existing or "").splitlines(keepends=True),
                    final.splitlines(keepends=True),
                    fromfile=f"a/{out_path}",
                    tofile=f"b/{out_path}",
                )
            )
        else:
            verb = "create" if existing is None else f"write ({action})"
            log.info("Would %s: %s", verb, out_path)
    print(json.dumps({"changed": bool(changed_paths), "paths": changed_paths}))
    return 3 if changed_paths else 0


# ── Main ────────────────────────────────────────────────────────────────────


def _plan_outputs(args: argparse.Namespace,
                  project_name: str) -> list[tuple[str, Path, Any]]:
    """Resolve ``(template_name, out_path, renderer)`` for the selected template(s).

    Extracted from ``main`` so the write path and the ``--check``/``--diff``
    dry-run path resolve destinations identically.
    """
    if args.template == "full":
        plan: list[tuple[str, Path, Any]] = []
        for tname, (fname, renderer) in TEMPLATES.items():
            if args.output.endswith(fname):
                out_path = Path(args.output)
            else:
                out_path = (
                    Path(args.output) / fname
                    if Path(args.output).is_dir()
                    else Path(args.output)
                )
            plan.append((tname, out_path, renderer))
        return plan

    fname, renderer = TEMPLATES[args.template]
    output_map = {
        "agents-md": f"{project_name}-AGENTS.md",
        "claude-md": f"{project_name}-CLAUDE.md",
        "obsidian": f"{project_name}.md",
    }
    out_path = Path(args.output)
    if out_path.is_dir():
        out_path = out_path / output_map.get(args.template, fname)
    return [(args.template, out_path, renderer)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Oracle — context file generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python oracle_generate.py --scan .oracle/scan-report.json\n"
            "  python oracle_generate.py -s report.json -t claude-md -o CLAUDE.md\n"
            "  python oracle_generate.py -s report.json -t full -o context/\n"
            "  python oracle_generate.py -s report.json -i intent.json\n"
        ),
    )
    parser.add_argument("--scan", "-s", required=True, help="Path to the scan JSON report")
    parser.add_argument("--output", "-o", default="AGENTS.md", help="Output file or directory")
    parser.add_argument("--template", "-t", default="agents-md",
                        choices=list(TEMPLATES.keys()) + ["full"],
                        help="Template to generate (default: agents-md)")
    parser.add_argument("--name", "-n", default=None,
                        help="Override the project name used in the output")
    parser.add_argument("--intent-file", "-i", default=None,
                        help="Path to an intent.json (project purpose + known pitfalls) "
                             "gathered from the user; embedded in the generated file")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing output file (its previous content "
                             "is saved to a .bak file). Without it, existing files are "
                             "only updated in place when they carry "
                             f"{MARKER_START}/{MARKER_END} markers")
    parser.add_argument("--check", action="store_true",
                        help="Dry run: write nothing, print "
                             '{"changed": ..., "paths": [...]} and exit 3 when the '
                             "output would differ from what is on disk (0 when up "
                             "to date)")
    parser.add_argument("--diff", action="store_true",
                        help="Dry run: write nothing, print a unified diff of the "
                             "pending changes to stdout and exit 3 when non-empty "
                             "(0 when up to date)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logs")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Load report ──
    scan_path = Path(args.scan)
    if not scan_path.exists():
        log.error("Report not found: %s", scan_path)
        sys.exit(1)
    try:
        report: dict[str, Any] = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON: %s", exc)
        sys.exit(1)

    project_name = args.name or report.get("project_name", "project")
    report["project_name"] = project_name

    # ── Load intent (user interview output) ──
    if args.intent_file:
        intent_path = Path(args.intent_file)
        if intent_path.exists():
            try:
                intent = json.loads(intent_path.read_text(encoding="utf-8"))
                if isinstance(intent, dict):
                    report["intent"] = intent
                    log.info("Intent loaded: %s", intent_path)
            except json.JSONDecodeError as exc:
                log.warning("Intent file is not valid JSON, ignoring: %s", exc)
        else:
            log.warning("Intent file not found, ignoring: %s", intent_path)

    # ── Render ──
    plan = _plan_outputs(args, project_name)

    # Dry run: --check / --diff never touch the filesystem.
    if args.check or args.diff:
        sys.exit(_dry_run(plan, report, show_diff=args.diff, force=True))

    if args.template == "full":
        generated = []
        for tname, out_path, renderer in plan:
            try:
                content = renderer(report)
                write_output(out_path, content, args.force)
                generated.append(str(out_path))
                log.info("Generated: %s", out_path)
            except SystemExit:
                raise
            except Exception as exc:
                log.error("Failed to generate %s: %s", tname, exc)
        print(json.dumps({"generated": generated}))
    else:
        _tname, out_path, renderer = plan[0]
        try:
            content = renderer(report)
            action = write_output(out_path, content, args.force)
            log.info("Generated: %s (%d lines, %s)", out_path,
                     content.count("\n") + 1, action)
            print(json.dumps({"generated": [str(out_path)], "action": action}))
        except SystemExit:
            raise
        except Exception as exc:
            log.error("Generation failed: %s", exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
