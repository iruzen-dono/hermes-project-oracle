#!/usr/bin/env python3
"""
Project Oracle — deep project scanner.

Analyzes a codebase in depth and produces a structured JSON report covering
languages, frameworks, build systems, entry points, conventions, environment
variable names, git context, and project tree. Zero dependencies.

Usage:
    python oracle_scan.py --path /path/to/project --output .oracle/
    python oracle_scan.py --path . --output .oracle/scan-report.json --depth 2
    python oracle_scan.py --path . --output /dev/stdout

--output accepts a directory (`.oracle/` or `.oracle`) or an explicit
JSON file path (`report.json`). Cross-platform: Windows, Linux, macOS.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

try:
    from version import __version__
except ImportError:  # scripts/ not on sys.path — visible, not silently wrong
    __version__ = "unknown"

try:
    from safe_io import atomic_write
except ImportError:  # standalone copy — minimal atomic fallback (temp + replace)
    import contextlib
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

# The scanner and its helpers ship as a package next to this script; make the
# scripts/ directory importable whether this file is run as a script
# (sys.path[0] = scripts/) or imported from the repo root.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from oracle_scan_lib.constants import (  # noqa: E402
    SKIP_DIRS as _SKIP_DIRS,
    sanitize_remote_url as _sanitize_remote_url,  # noqa: F401 — re-export: tests import it from here
)
# (oracle_scan_lib.io is consumed by the lib modules, not by this CLI entrypoint.)

from oracle_scan_lib.conventions import detect_conventions, detect_env_files  # noqa: E402

from oracle_scan_lib.detectors import (  # noqa: E402
    detect_build_system,
    detect_entry_points,
    detect_frameworks,
    detect_languages,
)

from oracle_scan_lib.misc import _detect_misc, _entry_docstring  # noqa: E402

from oracle_scan_lib.structure import _collect_nested_packages, get_structure  # noqa: E402

from oracle_scan_lib.vcs import get_git_context  # noqa: E402


# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("oracle-scan")


# ── Helpers ─────────────────────────────────────────────────────────────────

# (I/O helpers and constant tables moved to oracle_scan_lib — see imports above.)


# ── Detection functions ─────────────────────────────────────────────────────


# (Node framework/test tables moved to oracle_scan_lib.constants.)


# (_load_toml moved to oracle_scan_lib.io.)


# (Example env-file names moved to oracle_scan_lib.constants.ENV_EXAMPLE_NAMES.)


# (URL credential masking moved to oracle_scan_lib.constants.sanitize_remote_url.)


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Oracle — deep project scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python oracle_scan.py --path . --output .oracle/\n"
            "  python oracle_scan.py -p ~/project -o report.json -d 2\n"
            "  python oracle_scan.py -p . -o /dev/stdout   # print only\n"
        ),
    )
    parser.add_argument("--path", "-p", default=".", help="Project path (default: .)")
    parser.add_argument("--output", "-o", default=".oracle/scan-report.json",
                        help="Output: a directory (writes scan-report.json inside) or "
                             "an explicit JSON file path (default: .oracle/scan-report.json)")
    parser.add_argument("--depth", "-d", type=int, default=3,
                        help="Max tree depth (default: 3)")
    parser.add_argument("--skip-gitignore", action="store_true",
                        help="Do not skip .gitignore patterns")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logs")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Resolve paths ──
    root = Path(args.path).resolve(strict=False)
    if not root.exists():
        log.error("Path does not exist: %s", root)
        sys.exit(1)
    if root.is_file():
        root = root.parent

    log.info("Scanning: %s", root)
    start = time.time()

    # ── Phase 1: Languages ──
    log.debug("Detecting languages...")
    languages = detect_languages(root)

    # ── Phase 2: Build systems ──
    log.debug("Detecting build systems...")
    build_systems = detect_build_system(root)

    # ── Phase 2b: Nested manifests (monorepo support) ──
    nested_packages = _collect_nested_packages(root)
    for np in nested_packages:
        build_systems.append({
            "file": np["file"],
            "label": f"nested: {Path(np['file']).name}",
            "parsed": np["parsed"],
        })

    # ── Phase 3: Frameworks (list — a project usually has several) ──
    log.debug("Detecting frameworks...")
    scan_context = {"project_path": str(root), "build_systems": build_systems}
    frameworks = detect_frameworks(scan_context)
    framework = frameworks[0] if frameworks else None

    # ── Phase 4: Entry points ──
    log.debug("Finding entry points...")
    entry_points = detect_entry_points(root)

    # ── Phase 5: Conventions ──
    log.debug("Detecting conventions...")
    conventions = detect_conventions(root)

    # ── Phase 5b: Environment variables (names only, from example files) ──
    log.debug("Scanning env example files...")
    env_vars = detect_env_files(root)

    # ── Phase 6: Structure ──
    log.debug("Mapping project structure (depth=%d)...", args.depth)
    structure = get_structure(root, args.depth)

    # ── Phase 7: Git ──
    log.debug("Getting git context...")
    git_context = get_git_context(root)

    # ── Phase 8: Miscellaneous ──
    log.debug("Misc metadata...")
    misc = _detect_misc(root)

    # ── Counts ──
    file_count = sum(1 for _ in root.rglob("*") if _.is_file()
                     and not any(s in _.parts for s in _SKIP_DIRS))
    dir_count = sum(1 for _ in root.rglob("*") if _.is_dir()
                    and not any(s in _.parts for s in _SKIP_DIRS))

    # ── Assemble ──
    # Heuristic project summary (issue #5), in priority order:
    #   1. manifest description (package.json / pyproject.toml [project])
    #   2. first README paragraph
    #   3. module docstring of the main entry point (server.py, main.py, …)
    # The interview stays optional; `summary_source` records where it came from.
    summary = None
    summary_source = None
    for bs in build_systems:
        parsed: Any = bs.get("parsed", {})
        if isinstance(parsed, dict) and parsed.get("description"):
            summary = parsed["description"]
            summary_source = f"manifest ({bs.get('file', 'unknown')})"
            break
    if not summary:
        summary = misc.get("readme_summary")
        if summary:
            summary_source = "README"
    if not summary:
        doc, doc_file = _entry_docstring(root)
        if doc:
            summary = doc
            summary_source = f"docstring ({doc_file})"

    report = {
        "tool": "project-oracle",
        "version": __version__,
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_name": root.name,
        # NOTE: no absolute path here — the report must be shareable.
        "summary": summary,
        "summary_source": summary_source,
        "file_count": file_count,
        "dir_count": dir_count,
        "languages": languages,
        "build_systems": build_systems,
        "framework": framework,
        "frameworks": frameworks,
        "entry_points": entry_points,
        "conventions": conventions,
        "env_vars": env_vars,
        "git": git_context,
        "misc": misc,
        "structure": structure,
    }

    elapsed = time.time() - start
    report["scan_duration_seconds"] = round(elapsed, 2)

    # ── Output ──
    # `--output` accepts a directory (`.oracle/` or `.oracle`) OR a file path.
    # A value ending in a path separator, an existing directory, or a name without
    # a `.json` suffix is treated as a directory and gets `scan-report.json` inside.
    output_path = Path(args.output)
    if str(output_path) in ("/dev/stdout", "-"):
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        looks_like_dir = (
            str(args.output).endswith(("/", "\\"))
            or output_path.is_dir()
            or output_path.suffix != ".json"
        )
        if looks_like_dir:
            output_path = output_path / "scan-report.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            output_path,
            json.dumps(report, indent=2, ensure_ascii=False),
        )
        log.info("Report written: %s (%d bytes)", output_path, output_path.stat().st_size)

        # Keep the scan output out of the project's VCS (issue: dirty repo).
        # Only touches an EXISTING .gitignore, and only when missing the rule.
        try:
            resolved_out = output_path.resolve()
            if resolved_out.is_relative_to(root):
                gitignore = root / ".gitignore"
                if gitignore.is_file():
                    gi = gitignore.read_text(encoding="utf-8", errors="replace")
                    if not any(line.strip() in (".oracle", ".oracle/", "/.oracle/")
                               for line in gi.splitlines()):
                        sep = "" if gi.endswith("\n") or not gi else "\n"
                        atomic_write(
                            gitignore,
                            gi + sep + ".oracle/\n",
                        )
                        log.info("Added .oracle/ to %s", gitignore)
        except OSError as exc:
            log.debug("Could not update .gitignore: %s", exc)

    # ── Summary ──
    lang_str = ", ".join(f"{g['name']} ({g['ratio']}%)" for g in languages[:4]) or "none"
    log.info("Done in %.2fs", elapsed)
    log.info("Languages: %s", lang_str)
    log.info("Frameworks: %s", ", ".join(frameworks) if frameworks else "none detected")
    log.info("Files: %d, Dirs: %d | Entries: %d", file_count, dir_count, len(entry_points))


if __name__ == "__main__":
    main()
