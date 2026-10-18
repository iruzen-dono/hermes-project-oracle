"""Package the skill into an Agensi-compliant ZIP.

Agensi requirements (from their checklist):
  - single top-level folder, named exactly like the SKILL.md `name`
  - SKILL.md at the root of that folder (not at the ZIP root, not nested twice)
  - supporting files allowed (references/, examples/, scripts/)
  - no symlinks, no binary/compiled files, no OS junk (.DS_Store, Thumbs.db)

Run: python package_skill.py  ->  writes hermes-project-oracle.zip
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
SKILL_MD = REPO / "SKILL.md"

# Directories never shipped.
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".oracle", "node_modules"}
# File suffixes never shipped (binaries / caches).
SKIP_SUFFIXES = {".pyc", ".pyo", ".pyd", ".DS_Store"}
# OS junk by exact name.
SKIP_NAMES = {"Thumbs.db", ".DS_Store", "desktop.ini"}
# Files never shipped by this packaging script itself.
SKIP_NAMES.add("package_skill.py")
SKIP_NAMES.add(REPO.name + ".zip")


def skill_name() -> str:
    """Read `name:` from the SKILL.md front matter (authoritative folder name)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        raise SystemExit("SKILL.md has no front matter")
    fm = m.group(1)
    nm = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
    if not nm:
        raise SystemExit("SKILL.md front matter has no `name:`")
    return nm.group(1).strip().strip('"').strip("'")


def should_ship(p: Path) -> bool:
    if p.name in SKIP_NAMES:
        return False
    if p.suffix in SKIP_SUFFIXES:
        return False
    if any(part in SKIP_DIRS for part in p.parts):
        return False
    if p.is_symlink():
        return False
    return p.is_file()


def main() -> None:
    name = skill_name()
    out = REPO / f"{name}.zip"
    if out.exists():
        out.unlink()

    shipped = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(REPO.rglob("*")):
            if not should_ship(p):
                continue
            rel = p.relative_to(REPO)
            arc = f"{name}/{rel.as_posix()}"  # single top-level folder
            zf.write(p, arc)
            shipped.append(arc)

    # ── Validate the archive against the Agensi rules ──
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert f"{name}/SKILL.md" in names, "SKILL.md not at folder root!"
    assert not any("/" in n[len(name) + 1:].rstrip("/") and n.count("/") == 1
                   and n.endswith("SKILL.md") for n in names), "nested SKILL.md?"
    assert not any(n.split("/", 1)[1].startswith("/") for n in names), "bad path!"
    bad = [n for n in names if n.split("/")[-1] in SKIP_NAMES
           or Path(n).suffix in SKIP_SUFFIXES]
    assert not bad, f"junk files in zip: {bad}"

    size = out.stat().st_size
    print(f"Skill name : {name}")
    print(f"Archive    : {out}")
    print(f"Files      : {len(shipped)}")
    print(f"Size       : {size} bytes ({size/1024:.1f} KB)")
    print("\nContents:")
    for s in shipped:
        print(f"  {s}")
    print("\nOK: SKILL.md at folder root, single top folder, no junk.")


if __name__ == "__main__":
    main()