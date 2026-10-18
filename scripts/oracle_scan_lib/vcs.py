"""Git context collection.

Functions moved verbatim out of oracle_scan.py — behaviour is unchanged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from oracle_scan_lib.constants import sanitize_remote_url as _sanitize_remote_url
from oracle_scan_lib.io import safe_read as _safe_read


def get_git_context(path: Path) -> dict[str, Any]:
    """Récupère le contexte Git du projet."""
    ctx: dict[str, Any] = {"has_git": False}
    if not (path / ".git").exists():
        return ctx

    ctx["has_git"] = True

    def _run_git(*args: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(path), *args],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    ctx["branch"] = _run_git("branch", "--show-current") or "unknown"
    ctx["commit_count"] = _run_git("rev-list", "--count", "HEAD") or "?"
    ctx["last_commit_msg"] = _run_git("log", "-1", "--format=%s") or ""

    remotes_raw = _run_git("remote", "-v")
    if remotes_raw:
        remotes = []
        seen_remotes: set[tuple[str, str]] = set()
        for line in remotes_raw.split("\n"):
            parts = line.split()
            if len(parts) >= 3:
                name, url = parts[0], parts[1]
                key = (name, url)
                if key in seen_remotes:
                    # `git remote -v` lists every remote twice (fetch + push).
                    continue
                seen_remotes.add(key)
                remotes.append({
                    "name": name,
                    "url": _sanitize_remote_url(url),
                    "type": parts[2],
                })
        ctx["remotes"] = remotes

    # Detect .gitignore patterns
    gitignore = path / ".gitignore"
    if gitignore.is_file():
        content = _safe_read(gitignore)
        if content:
            ctx["gitignore_patterns"] = [ln.strip() for ln in content.split("\n")
                                         if ln.strip() and not ln.startswith("#")][:30]

    return ctx
