#!/usr/bin/env python3
"""
Hermes Project Oracle — Intégration Obsidian.
Pousse une note de projet structurée dans le vault Obsidian.
"""

import json
import sys
from pathlib import Path


def resolve_vault(configured_path: str | None = None) -> Path | None:
    """Trouve le chemin du vault Obsidian."""
    if configured_path:
        return Path(configured_path)

    # Chemins courants
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
    """Écrit la note dans le bon dossier du vault."""
    target_dir = vault / category
    target_dir.mkdir(parents=True, exist_ok=True)
    note_path = target_dir / f"{project_name}.md"
    note_path.write_text(content, encoding="utf-8")
    return note_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes Project Oracle — Vault")
    parser.add_argument("--content", "-c", required=True, help="Contenu markdown de la note")
    parser.add_argument("--name", "-n", required=True, help="Nom du projet")
    parser.add_argument("--vault", "-v", default=None, help="Chemin du vault Obsidian")
    parser.add_argument("--category", default="05 - Projets", help="Catégorie dans le vault")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    if not vault:
        print(json.dumps({"error": "Vault Obsidian non trouvé. Passe --vault manuellement."}))
        sys.exit(1)

    note_path = push_to_vault(vault, args.name, args.content, args.category)
    print(json.dumps({"path": str(note_path), "vault": str(vault)}))
    print(f"[✓] Note créée : {note_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
