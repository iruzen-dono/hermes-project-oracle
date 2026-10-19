"""Repository structure walk and nested-package discovery.

Functions moved verbatim out of oracle_scan.py — behaviour is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oracle_scan_lib.constants import SKIP_DIRS as _SKIP_DIRS
from oracle_scan_lib.detectors import (
    _detect_cargo,
    _detect_go,
    _detect_java_maven,
    _detect_node,
    _detect_php,
    _detect_python,
)


def _collect_nested_packages(path: Path, max_depth: int = 2, max_packages: int = 20) -> list[dict[str, Any]]:
    """Find package.json / pyproject.toml / pom.xml in subdirectories (monorepo support)."""
    found: list[dict[str, Any]] = []
    targets = {"package.json": _detect_node, "pyproject.toml": _detect_python,
               "pom.xml": _detect_java_maven, "Cargo.toml": _detect_cargo,
               "go.mod": _detect_go, "composer.json": _detect_php}

    def walk(p: Path, depth: int) -> None:
        if depth > max_depth or len(found) >= max_packages:
            return
        try:
            children = sorted(p.iterdir())
        except PermissionError:
            return
        for child in children:
            if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            for tname, scanner in targets.items():
                tf = child / tname
                if tf.is_file():
                    parsed = scanner(tf, path)  # pass project root for symlink guard
                    try:
                        rel = str(tf.relative_to(path).as_posix())
                    except ValueError:
                        rel = tf.name
                    try:
                        pkg_dir = str(tf.parent.relative_to(path).as_posix())
                    except ValueError:
                        pkg_dir = "."
                    if isinstance(parsed, dict):
                        # Audit #1: remember where each manifest lives so the
                        # generator can prefix commands with their directory
                        # (e.g. `cd backend && npm run dev`).
                        parsed["pkg_dir"] = pkg_dir
                    found.append({"file": rel, "parsed": parsed, "dir": pkg_dir})
                    break
            walk(child, depth + 1)

    walk(path, 1)
    return found


def get_structure(path: Path, max_depth: int = 3, skip_dirs: set[str] | None = None) -> list[dict[str, Any]]:
    """Produce a simplified tree view of the repository."""
    if skip_dirs is None:
        skip_dirs = _SKIP_DIRS

    structure: list[dict[str, Any]] = []

    def walk(p: Path, depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return
        for child in children:
            if child.name.startswith(".") and child.is_dir():
                continue
            if child.name in skip_dirs:
                continue
            # Security: never traverse or list a symlink escaping the repo root.
            try:
                if child.is_symlink() and not child.resolve().is_relative_to(path):
                    continue
            except OSError:
                continue
            try:
                rel = child.relative_to(path)
            except ValueError:
                continue

            if child.is_dir() and depth < max_depth:
                structure.append({
                    "name": child.name,
                    "path": str(rel.as_posix()),
                    "type": "directory",
                    "depth": depth,
                })
                walk(child, depth + 1)
            elif child.is_file() and depth <= 2:
                structure.append({
                    "name": child.name,
                    "path": str(rel.as_posix()),
                    "type": "file",
                    "depth": depth,
                })

    walk(path)
    return structure
