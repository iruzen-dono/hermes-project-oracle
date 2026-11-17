"""Keep the two published distributions from drifting apart.

`hermes-project-oracle` is now a migration pointer: it ships no code and exists
only to pull `project-oracle` for installs created before the rename. That makes
three invariants load-bearing, and none of them are enforced by the packaging
tool itself:

- the pointer's version must equal the real one, or `pip install -U` on the old
  name resolves to a release that does not exist yet;
- its dependency floor must equal that same version, or an upgrade can land on an
  older `project-oracle` than the pointer claims to deliver;
- it must define no packages and no entry points, or installing it next to
  `project-oracle` writes the same `oracle_*.py` modules twice.
"""

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "pyproject.toml"
LEGACY = ROOT / "packaging" / "hermes-project-oracle" / "pyproject.toml"


def _version_file() -> str:
    text = (ROOT / "scripts" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    assert match is not None, "scripts/version.py has no __version__"
    return match.group(1)


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


class TestDistributionMetadata(unittest.TestCase):
    def test_the_real_distribution_is_project_oracle(self):
        self.assertEqual(_load(MAIN)["project"]["name"], "project-oracle")

    def test_legacy_version_matches_the_source_of_truth(self):
        legacy = _load(LEGACY)["project"]
        self.assertEqual(
            legacy["version"],
            _version_file(),
            "packaging/hermes-project-oracle/pyproject.toml must be bumped with "
            "scripts/version.py",
        )

    def test_legacy_pulls_the_matching_release(self):
        legacy = _load(LEGACY)["project"]
        deps = legacy.get("dependencies", [])
        self.assertEqual(len(deps), 1, f"expected exactly one dependency, got {deps}")
        self.assertTrue(
            deps[0].startswith("project-oracle"),
            f"the pointer must depend on project-oracle, got {deps[0]}",
        )
        floor = deps[0].split(">=")[-1].strip()
        self.assertEqual(
            floor,
            legacy["version"],
            f"pointer requires >={floor} but is itself {legacy['version']}",
        )

    def test_legacy_ships_no_code(self):
        legacy = _load(LEGACY)["project"]
        self.assertNotIn(
            "scripts", legacy, "the pointer must not define its own entry points"
        )
        tool = _load(LEGACY).get("tool", {}).get("setuptools", {})
        self.assertEqual(tool.get("packages"), [], "the pointer must ship no packages")

    def test_readme_is_included_in_both_distributions(self):
        """`readme` points at a file that has to exist at build time."""
        for path in (MAIN, LEGACY):
            project = _load(path)["project"]
            readme = path.parent / project["readme"]
            self.assertTrue(readme.is_file(), f"{readme} referenced by {path} is missing")


if __name__ == "__main__":
    unittest.main()
