"""Project Oracle — shared safe I/O helpers (single source of truth).

Atomic, symlink-safe file writes used by the scanner, the generator and the
vault integrator. A write NEVER follows a symlink out of its root and NEVER
leaves a partially-written file behind (temp file + ``os.replace``).

The helpers are imported by the three CLI scripts via a tiny try/except so
that each script still runs standalone when copied alone (the ``oracle_*.py``
entrypoints keep a local fallback). When executed from the ``scripts/`` folder
the real implementations below are used.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write", "refuse_symlink_escape"]


def refuse_symlink_escape(target: Path, must_stay_under_root: Path | None = None) -> None:
    """Raise ``ValueError`` if writing to ``target`` would traverse a symlink.

    Two protections:
      * If ``target`` already exists and is a symlink, writing through it would
        follow the link wherever it points — we refuse. This is the core guard
        against ``scan-report.json`` / ``AGENTS.md`` being a symlink that
        redirects the write outside the repo.
      * If ``must_stay_under_root`` is given (e.g. the Obsidian vault, where the
        whole tree is owned by Oracle), the resolved path must stay under that
        root. NOT used for the scanner's ``--output``, which may legitimately
        write outside the scanned project.

    Note: a *non-existent* path never traverses a link, and parent directories
    are not symlinks in practice here, so existence-of-target is the right test.
    """
    if target.is_symlink():
        resolved = target.resolve()
        raise ValueError(
            f"refusing to write through an existing symlink: {target} -> {resolved}"
        )
    if must_stay_under_root is not None:
        resolved = target.resolve()
        if not resolved.is_relative_to(must_stay_under_root.resolve()):
            raise ValueError(
                f"refusing to write outside the root: {target} -> {resolved}"
            )


def atomic_write(target: Path, content: str,
                 must_stay_under_root: Path | None = None) -> None:
    """Write ``content`` to ``target`` atomically and symlink-safely.

    * the parent directory is created if missing;
    * refuses to write through an existing symlink on ``target`` (see
      ``refuse_symlink_escape``);
    * content is written to a temp file in the SAME directory then moved with
      ``os.replace`` so a crash can never leave a truncated/partial file and a
      concurrent reader never observes a half-written file.

    Callers that need overwrite-protection logic (.bak, markers) do that
    BEFORE calling this; this helper only guarantees the final write is atomic
    and does not traverse a symlink.
    """
    target = Path(target)
    refuse_symlink_escape(target, must_stay_under_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same-directory temp file so os.replace stays on one filesystem (atomic).
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp_name, str(target))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise