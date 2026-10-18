"""Safe file-reading helpers shared by the scanner.

Behaviour-neutral: moved verbatim out of ``oracle_scan.py``. Every helper here
returns ``None`` instead of raising, so a corrupt or oversized manifest degrades
the report instead of crashing the scan (the deliberate best-effort contract).
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("oracle-scan")


def read_in_root(target: Path, root: Path, max_bytes: int = 50_000) -> str | None:
    """Read a file ONLY if it stays inside the project root.

    A symlink whose ``resolve()`` escapes the root (e.g. ``pyproject.toml ->
    /etc/...``) is refused, so no content outside the scanned project can
    leak into the report or into the generated context files.
    """
    try:
        resolved_root = root.resolve()
        resolved_target = target.resolve()
    except OSError:
        return None
    if not resolved_target.is_relative_to(resolved_root):
        log.debug("Refusing symlink escaping the project root: %s", target)
        return None
    return safe_read(resolved_target, max_bytes=max_bytes)


def safe_read(path: Path, max_bytes: int = 50_000) -> str | None:
    """Read a text file when its size is reasonable."""
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            log.debug("Skipping large file (%d bytes): %s", path.stat().st_size, path)
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        log.debug("Permission denied: %s", path)
        return None
    except Exception as exc:
        log.debug("Cannot read %s: %s", path, exc)
        return None


def read_maybe_rooted(target: Path | None, root: Path | None) -> str | None:
    """Read a manifest, enforcing the root boundary when root is provided."""
    if not target:
        return None
    if root:
        return read_in_root(target, root)
    return safe_read(target)


def load_toml(content: str | None) -> dict | None:
    """Parse TOML text, returning ``None`` on missing or malformed content."""
    if not content:
        return None
    try:
        import tomllib

        return tomllib.loads(content)
    except Exception as exc:  # noqa: BLE001 — malformed manifest must not crash the scan
        log.debug("Cannot parse TOML: %s", exc)
        return None