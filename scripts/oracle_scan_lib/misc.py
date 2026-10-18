"""Misc metadata: README summary, licenses, docstrings (issue #5 fallback).

Functions moved verbatim out of oracle_scan.py — behaviour is unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from oracle_scan_lib.constants import SKIP_DIRS as _SKIP_DIRS


def _detect_misc(path: Path) -> dict[str, Any]:
    """Miscellaneous metadata about the project."""
    misc: dict[str, Any] = {}

    # Root files
    misc["readme"] = any(
        (path / f).is_file() for f in ["README.md", "README.rst", "README.txt", "README"]
    )
    misc["license"] = any(
        (path / f).is_file() for f in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]
    )
    misc["changelog"] = any(
        (path / f).is_file() for f in ["CHANGELOG.md", "CHANGELOG", "HISTORY.md"]
    )
    misc["contributing"] = (path / "CONTRIBUTING.md").is_file()
    misc["code_of_conduct"] = (path / "CODE_OF_CONDUCT.md").is_file()

    # Config files at root
    config_files = [
        f.name for f in path.iterdir()
        if f.is_file()
        and f.suffix in (".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf")
    ]
    misc["config_files"] = config_files[:20]

    # Template engines
    template_exts = {".j2", ".jinja", ".hbs", ".handlebars", ".ejs", ".pug", ".haml", ".liquid", ".twig"}
    template_count = sum(
        1 for f in path.rglob("*") if f.is_file() and f.suffix in template_exts
        and not any(s in f.parts for s in _SKIP_DIRS)
    )
    misc["template_count"] = template_count

    # Issue #5: heuristic project summary — first real paragraph of the README.
    for readme_name in ("README.md", "readme.md", "README.rst"):
        readme_path = path / readme_name
        if not readme_path.is_file():
            continue
        # Security: never read a README that is a symlink escaping the repo —
        # an external file could leak secrets into the report / AGENTS.md.
        try:
            if readme_path.is_symlink() and not readme_path.resolve().is_relative_to(path):
                continue
        except OSError:
            continue
        try:
            text = readme_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            break
        para: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            # Headers, badges, tables and code fences always end the block.
            if not stripped or stripped.startswith(("#", "!", "|", "```")):
                if para:
                    break
                continue
            # At paragraph start, skip list/badge/link/HTML openers; but once a
            # paragraph has begun, keep a continuation line even if it starts
            # with '[', '-', '*' or '<'.
            if not para and stripped.startswith(("[", "-", "*", "<")):
                continue
            para.append(stripped)
            if sum(len(p) for p in para) > 240:
                break
        if para:
            summary = " ".join(para)[:300]
            if len(summary) >= 12:
                misc["readme_summary"] = summary
        break

    return misc


def _module_docstring(path: Path, root: Path | None = None) -> str | None:
    """First docstring of a Python file, flattened to one line (issue #5)."""
    try:
        if root is not None and not path.resolve().is_relative_to(root.resolve()):
            return None  # symlink escaping the repo root — never read it
    except OSError:
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    doc = ast.get_docstring(tree)
    if doc:
        text = " ".join(doc.split())[:300]
        if len(text) >= 12:
            return text
    return None


def _entry_docstring(path: Path) -> tuple[str | None, str | None]:
    """Best one-liner from a canonical entry point, then any root script."""
    canonical = ("server.py", "main.py", "app.py", "cli.py", "run.py",
                 "__main__.py", "bootstrap.py", "manage.py", "wsgi.py", "asgi.py")
    ordered = [path / n for n in canonical if (path / n).is_file()]
    ordered += [p for p in sorted(path.glob("*.py"))
                if p.name.startswith("_") is False and p not in ordered]
    for py in ordered:
        # Security: never read a script that is a symlink escaping the repo.
        try:
            if py.is_symlink() and not py.resolve().is_relative_to(path):
                continue
        except OSError:
            continue
        doc = _module_docstring(py, path)
        if doc:
            return doc, py.name
    return None, None
