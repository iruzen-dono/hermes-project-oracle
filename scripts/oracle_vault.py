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
import sys
from pathlib import Path


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
                  category: str = "05 - Projets") -> Path:
    """Write the note into the vault's category folder."""
    target_dir = vault / category
    target_dir.mkdir(parents=True, exist_ok=True)
    note_path = target_dir / f"{project_name}.md"
    note_path.write_text(content, encoding="utf-8")
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
                        help="Category folder inside the vault")
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

    note_path = push_to_vault(vault, name, content, args.category)
    print(json.dumps({"path": str(note_path), "vault": str(vault)}))
    print(f"[ok] Note created: {note_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
