"""Regression tests for the pruned traversal (v2.4.0).

Before this, ``SKIP_DIRS`` was applied *after* the walk: every counter entered
``node_modules``, ``.venv`` and ``.next`` and then threw the results away. On a
Next.js project that meant a 46 s scan, a language breakdown claiming 71 %
JavaScript for a TypeScript codebase (10 680 vendored files), and a file count
of 52 printed right next to it.

These tests pin the three properties that make the fix real:

1. vendored trees are never entered (not merely filtered out afterwards),
2. the numbers the report prints can no longer contradict each other,
3. a project that lives under a directory named like a skip entry still scans.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from oracle_check import _count_files  # noqa: E402
from oracle_scan_lib.conventions import _count_test_files  # noqa: E402
from oracle_scan_lib.detectors import detect_entry_points, detect_languages  # noqa: E402
from oracle_scan_lib.files import (  # noqa: E402
    count_project_entries,
    iter_project_files,
    walk_project,
)
from oracle_scan_lib.misc import _detect_misc  # noqa: E402


def _touch(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_node_project(root: Path, vendored: int = 200) -> Path:
    """A tiny TypeScript project with a bulky fake node_modules."""
    _touch(root / "src" / "app.ts", "export const app = 1;\n")
    _touch(root / "src" / "server.ts", "export const server = 1;\n")
    _touch(root / "package.json", '{"name": "fixture"}\n')
    pkg = root / "node_modules" / "dep"
    pkg.mkdir(parents=True, exist_ok=True)
    for i in range(vendored):
        _touch(pkg / f"module{i}.js", "module.exports = {};\n")
    return root


class TestPrunedWalk(unittest.TestCase):
    """``walk_project`` must not descend into a skipped directory at all."""

    def test_vendored_dirs_are_never_yielded(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td))
            seen = [p for p, _dirs, _files in walk_project(root)]
            self.assertFalse(
                [p for p in seen if "node_modules" in p.parts],
                "the walk entered node_modules instead of pruning it",
            )

    def test_include_vendored_restores_the_old_walk(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=5)
            seen = [p for p, _dirs, _files in walk_project(root, include_vendored=True)]
            self.assertTrue([p for p in seen if "node_modules" in p.parts])

    def test_project_under_a_skip_named_parent_still_scans(self):
        """A repo living under ``.../build/`` used to report zero files."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "build" / "my-app"
            _touch(root / "main.py", "print('hi')\n")
            _touch(root / "lib" / "util.py", "VALUE = 1\n")
            files, dirs = count_project_entries(root)
            self.assertEqual((files, dirs), (2, 1))
            self.assertEqual(len(list(iter_project_files(root))), 2)

    def test_skip_dir_inside_the_project_is_still_pruned(self):
        """Pruning is judged per directory name, not per absolute path."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            _touch(root / "keep.py")
            _touch(root / "dist" / "bundled.js")
            files, dirs = count_project_entries(root)
            self.assertEqual(files, 1)
            self.assertEqual(dirs, 0)


class TestLanguageHonesty(unittest.TestCase):
    """The report must not count code it says it is not counting."""

    def test_languages_ignore_vendored_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td))
            langs = detect_languages(root)
            self.assertEqual([lang["key"] for lang in langs], ["typescript"])
            self.assertEqual(langs[0]["files"], 2)
            self.assertEqual(langs[0]["ratio"], 100.0)

    def test_include_vendored_opt_in_sees_the_vendored_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=40)
            langs = detect_languages(root, include_vendored=True)
            keys = {lang["key"]: lang["files"] for lang in langs}
            self.assertEqual(keys["javascript"], 40)
            self.assertEqual(keys["typescript"], 2)

    def test_file_count_and_languages_agree(self):
        """The exact contradiction that shipped: 52 files vs 15 026 counted."""
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=150)
            files, _dirs = count_project_entries(root)
            counted = sum(lang["files"] for lang in detect_languages(root))
            self.assertEqual(files, 3)  # app.ts, server.ts, package.json — none vendored
            self.assertEqual(counted, 2)  # only the two .ts files are source
            self.assertLessEqual(counted, files)

    def test_template_count_ignores_vendored_templates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _touch(root / "index.html")
            _touch(root / "templates" / "page.j2")
            _touch(root / "node_modules" / "pkg" / "packed.j2")
            self.assertEqual(_detect_misc(root)["template_count"], 1)
            self.assertEqual(
                _detect_misc(root, include_vendored=True)["template_count"], 2
            )


class TestEntryPoints(unittest.TestCase):
    """Entry-point detection was 33 full-tree ``rglob`` scans."""

    def test_vendored_entry_candidates_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=3)
            _touch(root / "node_modules" / "dep" / "index.js")
            _touch(root / "node_modules" / "dep" / "main.py")
            entries = detect_entry_points(root)
            paths = [entry["path"] for entry in entries]
            self.assertEqual(paths, [])
            self.assertFalse([p for p in paths if p.startswith("node_modules")])

    def test_project_entry_point_is_still_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=3)
            _touch(root / "src" / "main.ts", "console.log('boot')\n")
            entries = {entry["path"]: entry["type"] for entry in detect_entry_points(root)}
            self.assertEqual(entries.get("src/main.ts"), "ts_entry")

    def test_spring_boot_entry_is_still_found(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _touch(root / "src" / "main" / "java" / "DemoApplication.java", "class X {}\n")
            types = [entry["type"] for entry in detect_entry_points(root)]
            self.assertIn("spring_boot_entry", types)


class TestTestFileCount(unittest.TestCase):
    """Vendored packages ship ``*.test.js``; those are not your tests."""

    def test_vendored_tests_are_not_counted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _touch(root / "tests" / "app.test.ts")
            for i in range(25):
                _touch(root / "node_modules" / "dep" / f"dep{i}.test.js")
            self.assertEqual(_count_test_files(root), 1)

    def test_bare_node_test_files_in_tests_dir_are_counted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _touch(root / "tests" / "runner.mjs")
            _touch(root / "__tests__" / "other.cjs")
            _touch(root / "tests" / "named.test.mjs")
            self.assertEqual(_count_test_files(root), 3)


class TestCheckerAgreesWithScanner(unittest.TestCase):
    """``oracle-check`` must count exactly like the report it validates."""

    def test_same_counts_feed_both_sides(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td))
            self.assertEqual(
                _count_files(root), count_project_entries(root)
            )

    def test_include_vendored_propagates_to_the_checker(self):
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=7)
            pruned, _ = _count_files(root)
            vendored, _ = _count_files(root, include_vendored=True)
            self.assertEqual(pruned, 3)
            self.assertEqual(vendored, 10)


class TestScanIncludeVendored(unittest.TestCase):
    """End-to-end: the flag lands in the report and the checker follows it."""

    def test_flag_is_recorded_and_the_checker_honours_it(self):
        import json
        import subprocess

        scripts = REPO_ROOT / "scripts"
        with tempfile.TemporaryDirectory() as td:
            root = _make_node_project(Path(td), vendored=30)
            out = root / ".oracle"
            scan = subprocess.run(
                [sys.executable, str(scripts / "oracle_scan.py"),
                 "-p", str(root), "-o", str(out), "--include-vendored"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(scan.returncode, 0, scan.stdout + scan.stderr)

            report = json.loads((out / "scan-report.json").read_text(encoding="utf-8"))
            self.assertIs(report["vendored_included"], True)
            langs = {lang["key"]: lang["files"] for lang in report["languages"]}
            self.assertEqual(langs.get("javascript"), 30)
            self.assertEqual(report["file_count"], 33)

            # The checker re-scans without being told anything: it must read the
            # mode from the report, otherwise every such report looks drifted.
            check = subprocess.run(
                [sys.executable, str(scripts / "oracle_check.py"),
                 "-p", str(root), "-s", str(out / "scan-report.json")],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertNotIn("size", check.stdout)


if __name__ == "__main__":
    unittest.main()
