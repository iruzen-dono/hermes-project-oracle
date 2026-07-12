"""Tests for hermes-project-oracle imports and script structure."""

import ast
import unittest
from pathlib import Path


class TestProjectOracle(unittest.TestCase):
    """Verify the oracle scripts are syntactically valid."""

    def setUp(self):
        self.repo_root = Path(__file__).resolve().parent.parent

    def test_all_py_files_parse(self):
        """Every .py file in the repo must parse as valid Python."""
        py_files = list(self.repo_root.rglob("*.py"))
        self.assertGreater(len(py_files), 0, "No Python files found")

        for f in py_files:
            with self.subTest(file=f.relative_to(self.repo_root)):
                source = f.read_text(encoding="utf-8")
                ast.parse(source, filename=str(f))

    def test_scripts_exist(self):
        """scripts/ directory must have at least one .py file."""
        scripts_dir = self.repo_root / "scripts"
        self.assertTrue(scripts_dir.exists())
        py_scripts = list(scripts_dir.rglob("*.py"))
        self.assertGreater(len(py_scripts), 0)

    def test_readme_exists(self):
        """README.md must exist."""
        readme = self.repo_root / "README.md"
        self.assertTrue(readme.exists())
        self.assertGreater(readme.stat().st_size, 100)

    def test_skill_md_exists(self):
        """SKILL.md must exist."""
        skill = self.repo_root / "SKILL.md"
        self.assertTrue(skill.exists())
        self.assertGreater(skill.stat().st_size, 100)

    def test_license_exists(self):
        """LICENSE must exist."""
        license_file = self.repo_root / "LICENSE"
        self.assertTrue(license_file.exists())
