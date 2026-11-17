"""Keep the two shipped distributions from drifting apart.

`project-oracle` is a dependency-only alias for `hermes-project-oracle`, so its
version lives in a second pyproject.toml. Nothing else compares them: publishing
the alias at a version older than the real package silently installs a stale
release, which is worse than not shipping the alias at all.
"""

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "pyproject.toml"
ALIAS = ROOT / "packaging" / "project-oracle" / "pyproject.toml"


def _version_file() -> str:
    text = (ROOT / "scripts" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    assert match is not None, "scripts/version.py has no __version__"
    return match.group(1)


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


class TestDistributionMetadata(unittest.TestCase):
    def test_alias_version_matches_the_source_of_truth(self):
        alias = _load(ALIAS)["project"]
        self.assertEqual(
            alias["version"],
            _version_file(),
            "packaging/project-oracle/pyproject.toml must be bumped with "
            "scripts/version.py",
        )

    def test_alias_depends_on_the_real_distribution(self):
        """The alias ships no code: every command comes from the dependency.

        The floor has to be the alias's own version. Pinning `>=2.5.0` on a
        2.5.1 alias would happily resolve to the 2.5.0 release it was meant to
        replace — installing an older package than the one asked for.
        """
        project = _load(ALIAS)["project"]
        deps = project.get("dependencies", [])
        self.assertEqual(len(deps), 1, f"expected exactly one dependency, got {deps}")
        self.assertTrue(
            deps[0].startswith("hermes-project-oracle"),
            f"alias must depend on hermes-project-oracle, got {deps[0]}",
        )
        floor = deps[0].split(">=")[-1].strip()
        self.assertEqual(
            floor,
            project["version"],
            f"alias requires >={floor} but is itself {project['version']}",
        )
        self.assertNotIn(
            "scripts", project, "the alias must not define its own entry points"
        )

    def test_alias_declares_no_python_packages(self):
        tool = _load(ALIAS).get("tool", {}).get("setuptools", {})
        self.assertEqual(tool.get("packages"), [], "the alias must ship no packages")

    def test_readme_is_included_in_both_distributions(self):
        """`readme` points at a file that has to exist at build time."""
        for path in (MAIN, ALIAS):
            project = _load(path)["project"]
            readme = ROOT / path.parent / project["readme"]
            self.assertTrue(readme.is_file(), f"{readme} referenced by {path} is missing")


if __name__ == "__main__":
    unittest.main()
