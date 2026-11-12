#!/usr/bin/env python3
"""Project Oracle — drift checker.

A generated context file is only worth what it still matches. Code moves, a
manifest changes, a test runner gets swapped — and the ``AGENTS.md`` written
six weeks ago keeps telling agents to run commands that no longer exist.

``oracle-check`` re-reads the repository, compares it with a stored scan
report, and exits non-zero when they disagree, so CI can fail instead of
letting the context rot silently.

Zero dependencies.

Usage:
    oracle-check --path . --scan .oracle/scan-report.json
    oracle-check --path . --agents AGENTS.md
    oracle-check --path . --json          # machine-readable

Exit codes:
    0  context matches the repository
    1  drift detected
    2  usage error (missing report, bad path)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from version import __version__
except ImportError:  # scripts/ not on sys.path — visible, not silently wrong
    __version__ = "unknown"

from oracle_scan_lib.constants import SKIP_DIRS
from oracle_scan_lib.conventions import detect_conventions
from oracle_scan_lib.detectors import (
    detect_build_system,
    detect_entry_points,
    detect_frameworks,
    detect_languages,
)


# ── Result model ──────────────────────────────────────────────────────────


@dataclass
class Finding:
    """One difference between the stored report and the repository."""

    level: str  # "error" | "warn"
    category: str
    detail: str


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)

    def error(self, category: str, detail: str) -> None:
        self.findings.append(Finding("error", category, detail))

    def warn(self, category: str, detail: str) -> None:
        self.findings.append(Finding("warn", category, detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warn"]

    def add_set_drift(
        self, category: str, old: set[str], new: set[str], noun: str = ""
    ) -> None:
        """Record a difference between two sets of names."""
        for added in sorted(new - old):
            self.error(category, f"+ {added}{(' ' + noun) if noun else ''} (added)")
        for removed in sorted(old - new):
            self.error(category, f"- {removed}{(' ' + noun) if noun else ''} (no longer present)")


# ── Helpers ───────────────────────────────────────────────────────────────


def _names(items: Any) -> set[str]:
    """Extract a set of identifying names from a report field.

    Accepts the several shapes Oracle uses: a list of strings, a list of
    dicts carrying ``file``/``name``/``path``/``label``, or anything else —
    which yields an empty set rather than raising.
    """
    out: set[str] = set()
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict):
            for key in ("file", "name", "path", "label", "type"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    out.add(value)
                    break
    return out


def _load_report(path: Path) -> dict[str, Any] | None:
    """Load a scan report, returning None when it is absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _scan_now(root: Path) -> dict[str, Any]:
    """Re-read the parts of the repository that a context file depends on."""
    build_systems = detect_build_system(root)
    frameworks = detect_frameworks(
        {"project_path": str(root), "build_systems": build_systems}
    )
    return {
        "languages": detect_languages(root),
        "build_systems": build_systems,
        "frameworks": frameworks,
        "entry_points": detect_entry_points(root),
        "conventions": detect_conventions(root),
    }


def _count_files(root: Path) -> tuple[int, int]:
    """Count files and directories, using the scanner's own skip list.

    Sharing SKIP_DIRS with the scanner is what makes the number comparable
    with ``file_count`` in the report. A private list here silently produced
    a 2x false positive, because it counted the virtualenv.
    """
    skip = SKIP_DIRS
    files = dirs = 0
    try:
        for entry in root.rglob("*"):
            # Judge on the path relative to the root: an absolute path can
            # legitimately contain "build" or "dist" in a parent directory.
            try:
                parts = entry.relative_to(root).parts
            except ValueError:
                continue
            if any(part in skip for part in parts):
                continue
            if entry.is_file():
                files += 1
            elif entry.is_dir():
                dirs += 1
    except OSError:
        pass
    return files, dirs


# ── Command validation ────────────────────────────────────────────────────

# Only commands whose target is checkable are validated. A bare `npm install`
# is always valid; `npm run build` is not, when the build script was removed.
_CMD_PATTERNS = (
    re.compile(r"\bnpm run ([a-zA-Z0-9:_-]+)"),
    re.compile(r"\bpnpm (?:run )?([a-zA-Z0-9:_-]+)"),
    re.compile(r"\byarn (?:run )?([a-zA-Z0-9:_-]+)"),
    re.compile(r"\bcomposer (?:run-script )?([a-zA-Z0-9:_-]+)"),
)

_NOT_SCRIPTS = {"install", "add", "remove", "update", "ci", "init", "create"}


def _node_scripts(root: Path) -> set[str] | None:
    """Return the script names declared by package.json, or None if absent."""
    manifest = root / "package.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return set()
    return {k for k in scripts if isinstance(k, str)}


def _check_commands(text: str, root: Path, result: CheckResult) -> int:
    """Verify that commands cited in a context file still exist. Returns the
    number of commands actually validated."""
    scripts = _node_scripts(root)
    checked = 0
    for pattern in _CMD_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            if name in _NOT_SCRIPTS or name.startswith("-"):
                continue
            checked += 1
            if scripts is not None and name not in scripts:
                result.error(
                    "commands",
                    f"`{match.group(0)}` - no such script in package.json "
                    f"(have: {', '.join(sorted(scripts)) or 'none'})",
                )
    return checked


def _manifest_drift(
    stored: dict[str, Any], fresh: dict[str, Any], result: CheckResult
) -> None:
    """Compare manifest *contents*, not just their presence.

    Deleting a script from package.json leaves the file where it was, so a
    file-list comparison sees nothing. The scripts are what a context file
    tells an agent to run, so they are what has to be compared.
    """

    def index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for entry in report.get("build_systems") or []:
            if isinstance(entry, dict) and isinstance(entry.get("file"), str):
                parsed = entry.get("parsed")
                out[entry["file"]] = parsed if isinstance(parsed, dict) else {}
        return out

    old, new = index(stored), index(fresh)
    for name in sorted(set(old) & set(new)):
        for key in ("scripts", "console_scripts"):
            before, after = old[name].get(key), new[name].get(key)
            if isinstance(before, dict) and isinstance(after, dict):
                result.add_set_drift(f"{name} {key}", set(before), set(after))
        # A changed dependency list is a warning: adding a library does not
        # invalidate the context, swapping the test runner does.
        before = old[name].get("deps_sample")
        after = new[name].get("deps_sample")
        if isinstance(before, list) and isinstance(after, list) and set(before) != set(after):
            added = sorted(set(after) - set(before))
            removed = sorted(set(before) - set(after))
            result.warn(
                f"{name} dependencies",
                f"added {added or 'none'}, removed {removed or 'none'}",
            )


# ── Reporting ─────────────────────────────────────────────────────────────


def _supports_unicode(stream: Any = None) -> bool:
    """Whether the output stream can carry ✓ ✗ ⚠ →.

    A Windows console defaults to cp1252, where printing ✓ raises
    UnicodeEncodeError and the tool dies mid-report instead of reporting.
    """
    target = stream if stream is not None else sys.stdout
    encoding = getattr(target, "encoding", None) or "ascii"
    try:
        "✓✗⚠→".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _sym() -> dict[str, str]:
    """Symbol set for the current output stream."""
    if _supports_unicode():
        return {"ok": "✓", "error": "✗", "warn": "⚠", "arrow": "→"}
    return {"ok": "OK", "error": "X", "warn": "!", "arrow": "->"}


def _print_human(result: CheckResult, root: Path, stored: dict[str, Any]) -> None:
    scan_time = stored.get("scan_time", "unknown")
    version = stored.get("version", "unknown")
    print(f"oracle-check {__version__} - {root}")
    print(f"  stored scan: {scan_time} (v{version})")
    print()

    sym = _sym()
    if not result.findings:
        print(f"{sym['ok']} context matches the repository")
        return

    for finding in result.findings:
        print(f"{sym.get(finding.level, '?')} {finding.category}: {finding.detail}")

    print()
    parts = []
    if result.errors:
        parts.append(f"{len(result.errors)} drift(s)")
    if result.warnings:
        parts.append(f"{len(result.warnings)} warning(s)")
    print(", ".join(parts))
    if result.errors:
        print("Run `oracle-scan --path . --output .oracle/` to refresh the context.")


def _print_json(result: CheckResult, root: Path) -> None:
    payload = {
        "tool": "project-oracle-check",
        "version": __version__,
        "path": str(root),
        "ok": not result.errors,
        "errors": [
            {"category": f.category, "detail": f.detail} for f in result.errors
        ],
        "warnings": [
            {"category": f.category, "detail": f.detail} for f in result.warnings
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Oracle - detect drift between a stored scan and the repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  oracle-check --path .\n"
            "  oracle-check --path . --agents AGENTS.md\n"
            "  oracle-check -p . -s .oracle/scan-report.json --json\n"
        ),
    )
    parser.add_argument("--path", "-p", default=".", help="Project path (default: .)")
    parser.add_argument(
        "--scan",
        "-s",
        default=".oracle/scan-report.json",
        help="Stored scan report (default: .oracle/scan-report.json)",
    )
    parser.add_argument(
        "--agents", "-a", default=None,
        help="Context file whose cited commands should be validated (optional)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as drift")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    root = Path(args.path).resolve(strict=False)
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    report_path = Path(args.scan)
    if not report_path.is_absolute():
        report_path = root / report_path

    stored = _load_report(report_path)
    if stored is None:
        print(f"error: no readable scan report at {report_path}", file=sys.stderr)
        print("Run `oracle-scan --path . --output .oracle/` first.", file=sys.stderr)
        sys.exit(2)

    result = CheckResult()
    fresh = _scan_now(root)

    # ── Structural drift ──
    result.add_set_drift(
        "build systems",
        _names(stored.get("build_systems")),
        _names(fresh.get("build_systems")),
    )
    result.add_set_drift(
        "languages",
        {
            entry.get("name", "")
            for entry in stored.get("languages", [])
            if isinstance(entry, dict)
        },
        {
            entry.get("name", "")
            for entry in fresh.get("languages", [])
            if isinstance(entry, dict)
        },
    )
    result.add_set_drift(
        "frameworks",
        _names(stored.get("frameworks")),
        _names(fresh.get("frameworks")),
    )
    result.add_set_drift(
        "entry points",
        _names(stored.get("entry_points")),
        _names(fresh.get("entry_points")),
    )

    # ── Manifest contents (scripts, console entry points) ──
    _manifest_drift(stored, fresh, result)

    # ── Convention drift (the part agents actually obey) ──
    stored_conv = stored.get("conventions")
    fresh_conv = fresh.get("conventions")
    old_conv: dict[str, Any] = stored_conv if isinstance(stored_conv, dict) else {}
    new_conv: dict[str, Any] = fresh_conv if isinstance(fresh_conv, dict) else {}
    for key, label in (
        ("test_frameworks", "test frameworks"),
        ("quality_tools", "quality tools"),
        ("ci_cd", "CI providers"),
    ):
        result.add_set_drift(label, _names(old_conv.get(key)), _names(new_conv.get(key)))

    old_commit = old_conv.get("commit_convention")
    new_commit = new_conv.get("commit_convention")
    if old_commit != new_commit:
        result.error(
            "commit convention",
            f"{old_commit!r} {_sym()['arrow']} {new_commit!r}",
        )

    # ── Size drift: a quiet warning, since it is not automatically wrong ──
    old_files = stored.get("file_count")
    new_files, _ = _count_files(root)
    if isinstance(old_files, int) and old_files > 0:
        delta = new_files - old_files
        if abs(delta) >= max(10, old_files // 4):
            pct = round(delta / old_files * 100)
            result.warn(
                "size",
                f"{old_files} {_sym()['arrow']} {new_files} files ({delta:+d}, {pct:+d}%)",
            )

    # ── Command validation, if a context file was given ──
    checked_commands = 0
    if args.agents:
        agents_path = Path(args.agents)
        if not agents_path.is_absolute():
            agents_path = root / agents_path
        try:
            text = agents_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            result.warn("commands", f"cannot read {agents_path} - skipped")
        else:
            checked_commands = _check_commands(text, root, result)

    if args.strict:
        for finding in result.warnings:
            finding.level = "error"

    if args.json:
        _print_json(result, root)
    else:
        _print_human(result, root, stored)
        if args.agents and checked_commands:
            print(f"  ({checked_commands} command(s) validated against the repository)")

    sys.exit(1 if result.errors else 0)


if __name__ == "__main__":
    main()
