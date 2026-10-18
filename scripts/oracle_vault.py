#!/usr/bin/env python3
"""
Project Oracle — Obsidian vault integration.

Pushes a structured project note into an Obsidian vault. The note content can
come from a scan report (--scan, renders the obsidian template) or from raw
markdown (--content).

Usage:
    python oracle_vault.py --scan .oracle/scan-report.json --vault ~/vault
    python oracle_vault.py --scan .oracle/scan-report.json --intent-file intent.json
    python oracle_vault.py --content "# My note" --name my-project
"""

import json
import re
import sys
from pathlib import Path

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
        if must_stay_under_root is not None:
            if not target.resolve().is_relative_to(must_stay_under_root.resolve()):
                raise ValueError(f"refusing to write outside the root: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent),
                                   prefix=f".{target.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, str(target))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

# Characters that must never appear in a single path component.
_UNSAFE_CHARS = re.compile(r'[/\\<>:"|?*\x00]')


def safe_component(value: str, fallback: str = "project") -> str:
    """Reduce user input to ONE safe path component (no traversal possible).

    `--name "../../escape"` becomes `escape`; `--category "../evil"` becomes
    `evil`. Anything empty or dot-only falls back to a sane default.
    """
    flat = str(value).replace("\\", "/").split("/")[-1].strip()
    cleaned = _UNSAFE_CHARS.sub("_", flat).strip(". ")
    return cleaned[:120] or fallback


def resolve_vault(configured_path: str | None = None) -> Path | None:
    """Locate the Obsidian vault."""
    if configured_path:
        return Path(configured_path).expanduser()

    candidates = [
        Path.home() / "Documents" / "Obsidian Vault",
        Path.home() / "Obsidian",
        Path.home() / "vault",
        Path.home() / "Documents" / "Obsidian",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def push_to_vault(vault: Path, project_name: str, content: str,
                  category: str = "05 - Projets", force: bool = False) -> Path:
    """Write the note into the vault's category folder.

    Safety guarantees:
    * name and category are reduced to a single path component — a crafted
      ``--name ../../escape`` can never write outside the vault;
    * the final resolved path is verified to stay under the vault root;
    * an existing note is NEVER overwritten silently (edited notes are
      human knowledge): without ``force`` this raises FileExistsError,
      with ``force`` a ``.bak`` copy is kept first.
    """
    vault_root = vault.resolve()
    target_dir = vault_root / safe_component(category, "Projets")
    note_path = (target_dir / f"{safe_component(project_name)}.md").resolve()
    if not note_path.is_relative_to(vault_root):
        raise ValueError(f"refusing to write outside the vault: {note_path}")

    target_dir.mkdir(parents=True, exist_ok=True)
    if note_path.exists():
        if not force:
            raise FileExistsError(
                f"{note_path} already exists — pass --force to overwrite "
                f"(a .bak copy will be kept)"
            )
        backup = note_path.with_suffix(".md.bak")
        atomic_write(backup, note_path.read_text(encoding="utf-8"),
                     must_stay_under_root=vault_root)
    atomic_write(note_path, content, must_stay_under_root=vault_root)
    return note_path


def render_note_from_scan(scan_path: Path, intent_path: Path | None) -> tuple[str, str]:
    """Render the obsidian note from a scan report. Returns (project_name, content)."""
    # Import the shared renderer from the sibling script (same directory).
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from oracle_generate import render_obsidian

    report = json.loads(scan_path.read_text(encoding="utf-8"))
    if intent_path and intent_path.exists():
        try:
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            if isinstance(intent, dict):
                report["intent"] = intent
        except json.JSONDecodeError:
            pass
    return report.get("project_name", "project"), render_obsidian(report)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Project Oracle — Obsidian vault")
    parser.add_argument("--scan", "-s", default=None,
                        help="Path to a scan JSON report (renders the obsidian note)")
    parser.add_argument("--content", "-c", default=None,
                        help="Raw markdown content (alternative to --scan)")
    parser.add_argument("--name", "-n", default=None,
                        help="Project name (defaults to scan report's project_name)")
    parser.add_argument("--intent-file", "-i", default=None,
                        help="Optional intent.json to embed in the note")
    parser.add_argument("--vault", "-v", default=None, help="Path to the Obsidian vault")
    parser.add_argument("--category", default="05 - Projets",
                        help="Category folder inside the vault (single folder name)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing note (a .bak copy is kept)")
    args = parser.parse_args()

    if not args.scan and not args.content:
        parser.error("Provide either --scan or --content")

    # Resolve content and name
    content = args.content
    name = args.name
    if args.scan:
        scan_path = Path(args.scan)
        if not scan_path.exists():
            print(json.dumps({"error": f"Scan report not found: {scan_path}"}))
            sys.exit(1)
        intent_path = Path(args.intent_file) if args.intent_file else None
        scan_name, content = render_note_from_scan(scan_path, intent_path)
        name = name or scan_name
    if not name:
        print(json.dumps({"error": "No project name: pass --name or use --scan"}))
        sys.exit(1)

    vault = resolve_vault(args.vault)
    if not vault:
        print(json.dumps({"error": "Obsidian vault not found. Pass --vault manually."}))
        sys.exit(1)

    try:
        note_path = push_to_vault(vault, name, content, args.category,
                                  force=args.force)
    except (FileExistsError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps({"path": str(note_path), "vault": str(vault)}))
    print(f"[ok] Note created: {note_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
