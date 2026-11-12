"""Tests for oracle-lint - the context-file noise detector.

Two failure modes matter here, and they pull in opposite directions:

- calling a real, checkable rule "noise" teaches the user to ignore the tool;
- calling unfalsifiable advice "verified" defeats the entire point.

Most tests below pin the second, because that is the claim the tool makes.
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

import oracle_lint as ol  # noqa: E402


class TestExtraction(unittest.TestCase):
    def test_bullets_are_extracted_with_line_numbers(self):
        text = "# Title\n\n- First rule.\n- Second rule.\n"
        rules = ol.extract_rules(text)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].line, 3)
        self.assertEqual(rules[0].text, "First rule.")

    def test_numbered_list_is_extracted(self):
        rules = ol.extract_rules("1. Do this.\n2. Do that.\n")
        self.assertEqual([r.text for r in rules], ["Do this.", "Do that."])

    def test_headings_are_not_rules(self):
        rules = ol.extract_rules("# Rules\n## Sub\n- Real rule.\n")
        self.assertEqual(len(rules), 1)

    def test_code_fences_are_skipped(self):
        text = "- Real rule.\n```bash\nnpm run build\n```\n- Another rule.\n"
        rules = ol.extract_rules(text)
        self.assertEqual(len(rules), 2)
        self.assertNotIn("npm run build", [r.text for r in rules])

    def test_tables_and_html_comments_are_skipped(self):
        text = "| a | b |\n<!-- hidden -->\n> quote\n- Kept.\n"
        rules = ol.extract_rules(text)
        self.assertEqual([r.text for r in rules], ["Kept."])

    def test_imperative_paragraph_is_extracted(self):
        rules = ol.extract_rules("Always run the tests before committing.\n")
        self.assertEqual(len(rules), 1)

    def test_descriptive_paragraph_is_not_extracted(self):
        rules = ol.extract_rules("This repository is a Next.js application.\n")
        self.assertEqual(rules, [])

    def test_empty_and_blank_input(self):
        for text in ("", "\n\n\n", "   \n  \n"):
            with self.subTest(text=text):
                self.assertEqual(ol.extract_rules(text), [])


class TestAnchors(unittest.TestCase):
    """A concrete reference makes a rule actionable, whatever else it says."""

    def test_inline_code_anchors(self):
        self.assertTrue(ol._is_anchored("Write maintainable code in `src/app.py`"))

    def test_file_path_anchors(self):
        self.assertTrue(ol._is_anchored("Run the build with package.json"))

    def test_tool_name_anchors(self):
        self.assertTrue(ol._is_anchored("Use pytest for tests"))

    def test_directory_anchors(self):
        self.assertTrue(ol._is_anchored("Sources live in src/"))

    def test_vague_sentence_is_not_anchored(self):
        self.assertFalse(ol._is_anchored("Always write clean, maintainable code"))


class TestNoiseDetection(unittest.TestCase):
    def _noise(self, text):
        return ol._noise_reason(text)

    def test_clean_code_is_noise(self):
        self.assertIsNotNone(self._noise("Always write clean, maintainable code."))

    def test_best_practices_is_noise(self):
        self.assertIsNotNone(self._noise("Follow best practices."))

    def test_be_careful_is_noise(self):
        self.assertIsNotNone(self._noise("Be careful with edge cases."))

    def test_think_before_is_noise(self):
        self.assertIsNotNone(self._noise("Think carefully before editing."))

    def test_keep_it_simple_is_noise(self):
        self.assertIsNotNone(self._noise("Keep things simple."))

    def test_make_sure_it_works_is_noise(self):
        self.assertIsNotNone(self._noise("Make sure everything works."))

    def test_dont_break_is_noise(self):
        self.assertIsNotNone(self._noise("Don't break the build."))

    def test_anchored_vague_rule_is_not_noise(self):
        """The vague word is excused when something concrete is named."""
        self.assertIsNone(self._noise("Run `npm run build` to keep code clean."))

    def test_specific_rule_is_not_noise(self):
        self.assertIsNone(self._noise("Tests use vitest."))

    def test_unknown_rule_is_not_noise(self):
        self.assertIsNone(self._noise("Use 4-space indentation."))


class TestVerification(unittest.TestCase):
    def _root(self, td, **files):
        root = Path(td)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if isinstance(content, str) else json.dumps(content),
                            encoding="utf-8")
        return root

    def test_existing_script_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"package.json": {"scripts": {"build": "next build"}}})
            verdict, note = ol.verify(
                "Run `npm run build`.", root, ol._node_scripts(root), ol._manifest_text(root)
            )
            self.assertEqual(verdict, ol.VERIFIED)

    def test_missing_script_contradicts_the_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"package.json": {"scripts": {"build": "next build"}}})
            verdict, note = ol.verify(
                "Run `npm run deploy`.", root, ol._node_scripts(root), ol._manifest_text(root)
            )
            self.assertEqual(verdict, ol.WRONG)
            self.assertIn("deploy", note)

    def test_install_is_not_treated_as_a_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"package.json": {"scripts": {}}})
            verdict = ol.verify(
                "First `npm install`.", root, ol._node_scripts(root), ol._manifest_text(root)
            )
            self.assertIsNone(verdict)

    def test_ts_strict_true_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"tsconfig.json": {"compilerOptions": {"strict": True}}})
            verdict, _ = ol.verify(
                "TypeScript strict mode is required.", root, None, ol._manifest_text(root)
            )
            self.assertEqual(verdict, ol.VERIFIED)

    def test_ts_strict_false_is_a_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"tsconfig.json": {"compilerOptions": {"strict": False}}})
            verdict, _ = ol.verify(
                "TypeScript strict mode is required.", root, None, ol._manifest_text(root)
            )
            self.assertEqual(verdict, ol.WRONG)

    def test_ts_claim_without_tsconfig_is_a_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            verdict, _ = ol.verify("TypeScript strict mode is required.", Path(td), None, "")
            self.assertEqual(verdict, ol.WRONG)

    def test_declared_tool_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"package.json": {"devDependencies": {"vitest": "^2"}}})
            verdict, _ = ol.verify("Tests use vitest.", root, None, ol._manifest_text(root))
            self.assertEqual(verdict, ol.VERIFIED)

    def test_undeclared_tool_is_a_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, **{"package.json": {"name": "x"}})
            verdict, _ = ol.verify("Tests use jest.", root, None, ol._manifest_text(root))
            self.assertEqual(verdict, ol.WRONG)

    def test_missing_config_file_is_a_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            verdict, _ = ol.verify(
                "Formatting is in config/ruff.toml.", Path(td), None, ""
            )
            self.assertEqual(verdict, ol.WRONG)

    def test_claim_with_nothing_checkable_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(ol.verify("Use 4-space indentation.", Path(td), None, ""))


class TestScoring(unittest.TestCase):
    def test_ratios_ignore_unjudged_rules(self):
        result = ol.LintResult([
            ol.Rule(1, "a", ol.VERIFIED),
            ol.Rule(2, "b", ol.WRONG),
            ol.Rule(3, "c", ol.NOISE),
            ol.Rule(4, "d", ol.NOISE),
            ol.Rule(5, "e", ol.UNVERIFIED),
        ])
        self.assertEqual(result.judged, 4)
        self.assertAlmostEqual(result.noise_ratio, 0.5)
        self.assertAlmostEqual(result.useful_ratio, 0.25)

    def test_empty_result_does_not_divide_by_zero(self):
        result = ol.LintResult([])
        self.assertEqual(result.noise_ratio, 0.0)
        self.assertEqual(result.useful_ratio, 0.0)


class TestReporting(unittest.TestCase):
    def _result(self):
        return ol.LintResult([
            ol.Rule(3, "Run `npm run build`.", ol.VERIFIED, "exists"),
            ol.Rule(4, "Write clean code.", ol.NOISE, "no definition"),
        ])

    def test_json_is_valid(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ol.print_json(self._result(), Path("/x/AGENTS.md"))
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["verified"], 1)
        self.assertEqual(payload["noise"], 1)
        self.assertEqual(len(payload["rules"]), 2)

    def test_human_output_lists_rules_and_score(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ol.print_human(self._result(), Path("/x/AGENTS.md"))
        text = buf.getvalue()
        self.assertIn("L3", text)
        self.assertIn("Score:", text)

    def test_empty_file_message(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ol.print_human(ol.LintResult([]), Path("/x/AGENTS.md"))
        self.assertIn("no rules found", buf.getvalue())

    def test_ascii_symbols_are_encodable_in_cp1252(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        original = ol.sys.stdout
        ol.sys.stdout = stream
        try:
            sym = ol._sym()
        finally:
            ol.sys.stdout = original
        for value in sym.values():
            value.encode("cp1252")  # must not raise


class TestEndToEnd(unittest.TestCase):
    def _run(self, td, *args):
        script = REPO_ROOT / "scripts" / "oracle_lint.py"
        return subprocess.run(
            [sys.executable, str(script), *args], capture_output=True, text=True
        )

    def _project(self, td, agents, pkg=None):
        root = Path(td)
        if pkg is not None:
            (root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        (root / "AGENTS.md").write_text(agents, encoding="utf-8")
        return root

    def test_clean_file_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._project(
                td,
                "- Run `npm run build`.\n- Tests use vitest.\n",
                {"scripts": {"build": "b"}, "devDependencies": {"vitest": "^2"}},
            )
            proc = self._run(td, "AGENTS.md", "--path", str(root))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_contradiction_exits_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._project(td, "- Run `npm run deploy`.\n", {"scripts": {}})
            proc = self._run(td, "AGENTS.md", "--path", str(root))
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertIn("deploy", proc.stdout)

    def test_missing_file_exits_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            proc = self._run(td, "NOPE.md", "--path", td)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)

    def test_json_output_is_parseable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._project(td, "- Write clean code.\n")
            proc = self._run(td, "AGENTS.md", "--path", str(root), "--json")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["tool"], "project-oracle-lint")
            self.assertGreaterEqual(payload["noise"], 1)

    def test_strict_mode_fails_on_any_noise(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._project(td, "- Run `npm run build`.\n- Write good code.\n",
                                 {"scripts": {"build": "b"}})
            normal = self._run(td, "AGENTS.md", "--path", str(root))
            strict = self._run(td, "AGENTS.md", "--path", str(root), "--strict")
            self.assertEqual(normal.returncode, 0, normal.stdout)
            self.assertEqual(strict.returncode, 1, strict.stdout)


if __name__ == "__main__":
    unittest.main()
