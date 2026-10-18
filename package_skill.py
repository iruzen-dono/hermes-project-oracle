"""Package the skill into an Agensi-compliant ZIP.

Agensi requirements (from their checklist):
  - single top-level folder, named exactly like the SKILL.md `name`
  - SKILL.md at the root of that folder (not at the ZIP root, not nested twice)
  - supporting files allowed (references/, examples/, scripts/)
  - no symlinks, no binary/compiled files, no OS junk (.DS_Store, Thumbs.db)

Run: python package_skill.py  ->  writes <skill-name>.zip

Validation lives in `validate_archive()` and raises SystemExit (never bare
`assert`, which `python -O` silently strips).
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
SKILL_MD = REPO / "SKILL.md"

# Directories never shipped: VCS, caches, venvs and repo-dev tooling.
# `tests/` and `.github/` are development artifacts — the skill runtime does
# not need them, and installing the skill must stay lean.
SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".oracle",
    "node_modules", ".venv", "venv", "tests", ".github",
}
# File suffixes never shipped (binaries, caches, archives). Excluding every
# `.zip` guarantees the archive can never include itself, whatever the clone
# folder happens to be named.
SKIP_SUFFIXES = {".pyc", ".pyo", ".pyd", ".DS_Store", ".zip"}
# OS junk / secrets / repo-dev files by exact name.
SKIP_NAMES = {"Thumbs.db", ".DS_Store", "desktop.ini", ".env",
              "package_skill.py", "ruff.toml", ".gitignore"}


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



def validate_archive(zip_path: Path, name: str) -> list[str]:
    """Check the archive against the Agensi rules. Returns a list of problems.

    Explicit checks, not `assert`: validation must still run under `python -O`.
    """
    errors: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        if not names:
            return ["archive is empty"]

        # Exactly one top-level folder, named after the skill.
        tops = {n.split("/", 1)[0] for n in names}
        if tops != {name}:
            errors.append(
                f"top-level folder must be exactly '{name}/', got {sorted(tops)}"
            )

        # Exactly one SKILL.md and it must sit at the folder root.
        skill_files = [n for n in names if n.endswith("SKILL.md")]
        if skill_files != [f"{name}/SKILL.md"]:
            errors.append(
                f"expected exactly '{name}/SKILL.md', found {skill_files}"
            )

        # No absolute or drive-letter paths inside the archive.
        for n in names:
            if n.startswith("/") or n.startswith("\\") or re.match(r"^[A-Za-z]:", n):
                errors.append(f"absolute path in archive: {n}")
                break

        # No junk (binaries, venvs, caches, the zip itself...).
        bad = [
            n for n in names
            if n.split("/")[-1] in SKIP_NAMES
            or Path(n).suffix in SKIP_SUFFIXES
            or any(part in SKIP_DIRS for part in Path(n).parts)
        ]
        if bad:
            errors.append(f"junk files in zip: {bad}")

        # No symlinks (type 0o120000 in the upper mode bits).
        for info in zf.infolist():
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                errors.append(f"symlink in archive: {info.filename}")
                break

        # Agensi: text-only payload — a NUL byte means binary content.
        for info in zf.infolist():
            if info.is_dir():
                continue
            if b"\x00" in zf.read(info.filename):
                errors.append(f"binary content: {info.filename}")
                break

    return errors


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

    errors = validate_archive(out, name)
    if errors:
        out.unlink(missing_ok=True)
        raise SystemExit("Archive INVALID:\n  - " + "\n  - ".join(errors))

    size = out.stat().st_size
    print(f"Skill name : {name}")
    print(f"Archive    : {out}")
    print(f"Files      : {len(shipped)}")
    print(f"Size       : {size} bytes ({size / 1024:.1f} KB)")
    print("\nContents:")
    for s in shipped:
        print(f"  {s}")
    print("\nOK: single top folder, SKILL.md at folder root, no junk, text-only.")


if __name__ == "__main__":
    main()
