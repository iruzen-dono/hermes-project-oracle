"""Tests for oracle-check — drift detection between a scan and the repository.

The point of the tool is to fail when a context file no longer matches the
code, so these tests are mostly about the false-negative direction: a drift
that goes unreported is worse than one reported twice.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oracle_check as oc  # noqa: E402


class TestNames(unittest.TestCase):
    """_names has to cope with every shape the scanner emits."""

    def test_list_of_strings(self):
        self.assertEqual(oc._names(["pytest", "ruff"]), {"pytest", "ruff"})

    def test_list_of_dicts_uses_first_identifying_key(self):
        items = [{"file": "package.json", "label": "Node.js"}]
        self.assertEqual(oc._names(items), {"package.json"})

    def test_list_of_dicts_falls_back_to_name(self):
        items = [{"name": "Python", "files": 12}]
        self.assertEqual(oc._names(items), {"Python"})

    def test_none_and_garbage_yield_empty_set(self):
        for value in (None, "not a list", 42, {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(oc._names(value), set())

    def test_skips_dicts_without_known_key(self):
        self.assertEqual(oc._names([{"unknown": "x"}, "kept"]), {"kept"})


class TestCheckResult(unittest.TestCase):
    def test_set_drift_reports_both_directions(self):
        result = oc.CheckResult()
        result.add_set_drift("frameworks", {"next", "react"}, {"next", "vue"})
        details = [f.detail for f in result.findings]
        self.assertTrue(any("+ vue" in d for d in details))
        self.assertTrue(any("- react" in d for d in details))
        self.assertEqual(len(result.errors), 2)

    def test_no_drift_is_silent(self):
        result = oc.CheckResult()
        result.add_set_drift("x", {"a"}, {"a"})
        self.assertEqual(result.findings, [])

    def test_errors_and_warnings_are_separated(self):
        result = oc.CheckResult()
        result.error("a", "boom")
        result.warn("b", "meh")
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.warnings), 1)


class TestLoadReport(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(oc._load_report(Path("does-not-exist.json")))

    def test_invalid_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("{ not json", encoding="utf-8")
            self.assertIsNone(oc._load_report(path))

    def test_valid_report_is_returned(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ok.json"
            path.write_text('{"project_name": "x"}', encoding="utf-8")
            data = oc._load_report(path)
            self.assertIsInstance(data, dict)
            self.assertEqual(data["project_name"], "x")

    def test_json_array_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "arr.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertIsNone(oc._load_report(path))


class TestManifestDrift(unittest.TestCase):
    """A removed script must be caught: the file is still there, the script isn't."""

    def _report(self, scripts):
        return {
            "build_systems": [
                {"file": "package.json", "parsed": {"scripts": scripts, "deps_sample": []}}
            ]
        }

    def test_removed_script_is_an_error(self):
        stored = self._report({"build": "next build", "test": "vitest"})
        fresh = self._report({"test": "vitest"})
        result = oc.CheckResult()
        oc._manifest_drift(stored, fresh, result)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("build", result.errors[0].detail)

    def test_added_script_is_an_error(self):
        stored = self._report({"test": "vitest"})
        fresh = self._report({"test": "vitest", "lint": "eslint ."})
        result = oc.CheckResult()
        oc._manifest_drift(stored, fresh, result)
        self.assertTrue(any("+ lint" in f.detail for f in result.errors))

    def test_identical_manifests_are_silent(self):
        stored = self._report({"test": "vitest"})
        result = oc.CheckResult()
        oc._manifest_drift(stored, stored, result)
        self.assertEqual(result.findings, [])

    def test_dependency_change_is_a_warning_not_an_error(self):
        stored = self._report({"test": "vitest"})
        fresh = self._report({"test": "vitest"})
        fresh["build_systems"][0]["parsed"]["deps_sample"] = ["vitest"]
        result = oc.CheckResult()
        oc._manifest_drift(stored, fresh, result)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.warnings), 1)

    def test_malformed_input_does_not_raise(self):
        result = oc.CheckResult()
        oc._manifest_drift({"build_systems": "nope"}, {"build_systems": None}, result)
        self.assertEqual(result.findings, [])


class TestNodeScripts(unittest.TestCase):
    def test_reads_declared_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps({"scripts": {"build": "next build"}}), encoding="utf-8"
            )
            self.assertEqual(oc._node_scripts(root), {"build"})

    def test_missing_manifest_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(oc._node_scripts(Path(td)))

    def test_manifest_without_scripts_returns_empty_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text('{"name": "x"}', encoding="utf-8")
            self.assertEqual(oc._node_scripts(root), set())

    def test_broken_manifest_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text("{ broken", encoding="utf-8")
            self.assertIsNone(oc._node_scripts(root))


class TestCheckCommands(unittest.TestCase):
    def _root_with_scripts(self, td, scripts):
        root = Path(td)
        (root / "package.json").write_text(json.dumps({"scripts": scripts}), encoding="utf-8")
        return root

    def test_flags_unknown_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root_with_scripts(td, {"test": "vitest"})
            result = oc.CheckResult()
            checked = oc._check_commands("Run `npm run deploy`.", root, result)
            self.assertEqual(checked, 1)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("deploy", result.errors[0].detail)

    def test_accepts_known_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root_with_scripts(td, {"test": "vitest"})
            result = oc.CheckResult()
            oc._check_commands("Run `npm run test`.", root, result)
            self.assertEqual(result.errors, [])

    def test_install_is_not_treated_as_a_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root_with_scripts(td, {"test": "vitest"})
            result = oc.CheckResult()
            checked = oc._check_commands("First `npm install`.", root, result)
            self.assertEqual(checked, 0)
            self.assertEqual(result.errors, [])

    def test_no_manifest_means_no_validation(self):
        with tempfile.TemporaryDirectory() as td:
            result = oc.CheckResult()
            oc._check_commands("Run `npm run whatever`.", Path(td), result)
            self.assertEqual(result.errors, [])


class TestCountFiles(unittest.TestCase):
    def test_skips_noise_directories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("x = 1", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "dep.js").write_text("1", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref", encoding="utf-8")
            files, dirs = oc._count_files(root)
            self.assertEqual(files, 1)

    def test_virtualenv_is_not_counted(self):
        """A private skip list here produced a 2x false positive once.

        The count has to use the scanner's own SKIP_DIRS, otherwise a fresh
        clone and a working clone disagree for no reason the user can see.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.py").write_text("x = 1", encoding="utf-8")
            venv = root / ".venv" / "Lib" / "site-packages"
            venv.mkdir(parents=True)
            (venv / "dep.py").write_text("y = 2", encoding="utf-8")
            files, _ = oc._count_files(root)
            self.assertEqual(files, 1)

    def test_parent_named_build_does_not_wipe_the_count(self):
        """An absolute path containing 'build' must not skip everything."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "build" / "project"
            root.mkdir(parents=True)
            (root / "a.py").write_text("x = 1", encoding="utf-8")
            files, _ = oc._count_files(root)
            self.assertEqual(files, 1)


class TestEndToEnd(unittest.TestCase):
    """The real thing: scan a project, change it, expect a non-zero exit."""

    def _scan(self, root):
        scan = REPO_ROOT / "scripts" / "oracle_scan.py"
        proc = subprocess.run(
            [sys.executable, str(scan), "--path", str(root), "--output", str(root / ".oracle")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def _check(self, root, *extra):
        check = REPO_ROOT / "scripts" / "oracle_check.py"
        return subprocess.run(
            [sys.executable, str(check), "--path", str(root), *extra],
            capture_output=True,
            text=True,
        )

    def test_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps({"name": "x", "scripts": {"build": "next build"}}), encoding="utf-8"
            )
            (root / "index.js").write_text("1\n", encoding="utf-8")
            self._scan(root)
            proc = self._check(root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("matches", proc.stdout)

    def test_removed_script_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "package.json"
            manifest.write_text(
                json.dumps({"name": "x", "scripts": {"build": "next build"}}), encoding="utf-8"
            )
            (root / "index.js").write_text("1\n", encoding="utf-8")
            self._scan(root)
            manifest.write_text(json.dumps({"name": "x", "scripts": {}}), encoding="utf-8")
            proc = self._check(root)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertIn("build", proc.stdout)

    def test_missing_report_exits_two(self):
        with tempfile.TemporaryDirectory() as td:
            proc = self._check(Path(td))
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)

    def test_json_output_is_parseable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
            self._scan(root)
            proc = self._check(root, "--json")
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["errors"], [])


class TestReporting(unittest.TestCase):
    """The output paths are what CI reads, so they get tested directly."""

    def test_json_output_is_valid_and_complete(self):
        result = oc.CheckResult()
        result.error("scripts", "- build")
        result.warn("size", "39 → 83 files")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_json(result, Path("/tmp/x"))
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["errors"]), 1)
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertEqual(payload["errors"][0]["category"], "scripts")

    def test_json_ok_when_only_warnings(self):
        result = oc.CheckResult()
        result.warn("size", "grew")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_json(result, Path("/tmp/x"))
        self.assertTrue(json.loads(buf.getvalue())["ok"])

    def test_human_output_reports_match(self):
        result = oc.CheckResult()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_human(result, Path("/tmp/x"), {"scan_time": "t", "version": "1"})
        self.assertIn("matches", buf.getvalue())

    def test_human_output_marks_errors_and_suggests_rescan(self):
        result = oc.CheckResult()
        result.error("scripts", "- build")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_human(result, Path("/tmp/x"), {"scan_time": "t"})
        text = buf.getvalue()
        self.assertIn("✗", text)
        self.assertIn("oracle-scan", text)

    def test_human_output_marks_warnings(self):
        result = oc.CheckResult()
        result.warn("size", "grew")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_human(result, Path("/tmp/x"), {})
        self.assertIn("⚠", buf.getvalue())


class TestManifestConsoleScripts(unittest.TestCase):
    def test_removed_console_script_is_detected(self):
        stored = {
            "build_systems": [
                {
                    "file": "pyproject.toml",
                    "parsed": {"console_scripts": {"a": "x:main", "b": "y:main"}},
                }
            ]
        }
        fresh = {
            "build_systems": [
                {"file": "pyproject.toml", "parsed": {"console_scripts": {"a": "x:main"}}}
            ]
        }
        result = oc.CheckResult()
        oc._manifest_drift(stored, fresh, result)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("b", result.errors[0].detail)


class TestStrictMode(unittest.TestCase):
    def test_strict_promotes_warnings_to_errors(self):
        """--strict must turn a warning-only run into a failure."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "package.json").write_text(
                json.dumps({"name": "x", "scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            (root / "index.js").write_text("1\n", encoding="utf-8")
            scan = REPO_ROOT / "scripts" / "oracle_scan.py"
            subprocess.run(
                [sys.executable, str(scan), "--path", str(root), "--output", str(root / ".oracle")],
                capture_output=True,
                check=True,
            )
            # Adding files triggers a size warning, not an error.
            for i in range(40):
                (root / f"extra{i}.js").write_text("1\n", encoding="utf-8")
            check = REPO_ROOT / "scripts" / "oracle_check.py"
            normal = subprocess.run(
                [sys.executable, str(check), "--path", str(root)],
                capture_output=True, text=True,
            )
            strict = subprocess.run(
                [sys.executable, str(check), "--path", str(root), "--strict"],
                capture_output=True, text=True,
            )
            self.assertEqual(normal.returncode, 0, normal.stdout)
            self.assertEqual(strict.returncode, 1, strict.stdout)


if __name__ == "__main__":
    unittest.main()
