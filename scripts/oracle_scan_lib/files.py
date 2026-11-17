"""Pruned filesystem traversal shared by every Oracle command.

``SKIP_DIRS`` only saves work when it prunes the descent. ``Path.rglob`` walks
straight into ``node_modules``, ``.venv`` and ``.next`` and leaves the caller to
filter the results afterwards, so the exclusion cost exactly nothing: on a
Next.js project the language breakdown counted 10 680 vendored JavaScript files
(71 % of the "project") and a mere file count took seconds. Pruning during the
walk fixes both the wrong numbers and the time spent producing them.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from oracle_scan_lib.constants import SKIP_DIRS


def walk_project(
    root: Path, *, include_vendored: bool = False
) -> Iterator[tuple[Path, list[str], list[str]]]:
    """Yield ``(directory, subdirectories, files)`` like ``os.walk``, pruned.

    ``SKIP_DIRS`` is applied to each directory *name* before descending, so a
    vendored tree is never entered. Judging names rather than absolute path
    components also fixes a silent bug: a project living under ``.../build/``
    or ``.../dist/`` used to report zero files, because every path contained
    one of the skip names.

    ``include_vendored`` restores the old walk-everything behaviour for the
    rare project that genuinely keeps source inside a skipped directory.
    """
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if not include_vendored:
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        # Deterministic order: the same repository must produce the same report.
        dirnames.sort()
        filenames.sort()
        yield Path(dirpath), dirnames, filenames


def iter_project_files(
    root: Path, *, include_vendored: bool = False
) -> Iterator[Path]:
    """Yield every file of the project, skipping vendored trees during descent."""
    for dirpath, _dirnames, filenames in walk_project(
        root, include_vendored=include_vendored
    ):
        for name in filenames:
            yield dirpath / name


def count_project_entries(
    root: Path, *, include_vendored: bool = False
) -> tuple[int, int]:
    """Return ``(files, directories)`` for the project, excluding vendored trees."""
    files = directories = 0
    for _dirpath, dirnames, filenames in walk_project(
        root, include_vendored=include_vendored
    ):
        files += len(filenames)
        directories += len(dirnames)
    return files, directories
