"""Tests for hermes-project-oracle.

Covers script validity, unit behaviour (URL sanitising, env parsing), and a
full end-to-end run: scan -> generate -> vault against a fixture project.
The E2E test asserts the output is safe (no leaked tokens, no env values, no
absolute paths) and complete (commands, frameworks, env names, pitfalls).
"""

import ast
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SCAN = SCRIPTS / "oracle_scan.py"
GENERATE = SCRIPTS / "oracle_generate.py"
VAULT = SCRIPTS / "oracle_vault.py"


def _run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None,
        encoding="utf-8", errors="replace",
    )


class TestProjectStructure(unittest.TestCase):
    """Verify the repo ships valid, present files."""

    def test_all_py_files_parse(self):
        py_files = list(REPO_ROOT.rglob("*.py"))
        self.assertGreater(len(py_files), 0, "No Python files found")
        for f in py_files:
            with self.subTest(file=f.relative_to(REPO_ROOT)):
                ast.parse(f.read_text(encoding="utf-8"), filename=str(f))

    def test_scripts_exist(self):
        scripts_dir = REPO_ROOT / "scripts"
        self.assertTrue(scripts_dir.exists())
        self.assertGreater(len(list(scripts_dir.rglob("*.py"))), 0)

    def test_readme_and_skill_exist(self):
        self.assertTrue((REPO_ROOT / "README.md").exists())
        self.assertTrue((REPO_ROOT / "SKILL.md").exists())
        self.assertTrue((REPO_ROOT / "LICENSE").exists())

    def test_skill_md_frontmatter_is_valid(self):
        """SKILL.md must have name + description per the Agensi/Anthropic spec."""
        text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"), "SKILL.md must start with frontmatter")
        fm = text.split("---", 2)[1]
        self.assertIn("name:", fm)
        self.assertIn("description:", fm)
        # Description must carry trigger phrases for reliable activation.
        self.assertRegex(fm, r"(?i)use when")


class TestSanitizeRemoteUrl(unittest.TestCase):
    """Credentials embedded in remote URLs must never survive into output."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))

    def test_masks_userinfo(self):
        from oracle_scan import _sanitize_remote_url
        out = _sanitize_remote_url("https://user:ghp_SECRET123@github.com/acme/demo.git")
        self.assertNotIn("ghp_SECRET123", out)
        self.assertNotIn("user:", out)
        self.assertIn("***", out)

    def test_drops_query_token(self):
        from oracle_scan import _sanitize_remote_url
        out = _sanitize_remote_url("https://github.com/acme/demo.git?token=abc123")
        self.assertNotIn("abc123", out)

    def test_ssh_untouched(self):
        from oracle_scan import _sanitize_remote_url
        self.assertEqual(
            _sanitize_remote_url("git@github.com:acme/demo.git"),
            "git@github.com:acme/demo.git",
        )


class TestDetectEnvFiles(unittest.TestCase):
    """Only variable NAMES from example files; real .env values never read."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))

    def test_names_only_from_example(self):
        from oracle_scan import detect_env_files
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env.example").write_text(
                "# comment\nSPOTIFY_CLIENT_ID=your-id-here\nHOST_PASSWORD=admin123\n",
                encoding="utf-8",
            )
            # A real .env must be ignored entirely.
            (root / ".env").write_text("SECRET_TOKEN=real-secret-value\n", encoding="utf-8")
            found = detect_env_files(root)
            self.assertIn(".env.example", found)
            names = found[".env.example"]
            self.assertIn("SPOTIFY_CLIENT_ID", names)
            self.assertIn("HOST_PASSWORD", names)
            # Values must not be present anywhere in the returned structure.
            blob = json.dumps(found)
            self.assertNotIn("your-id-here", blob)
            self.assertNotIn("real-secret-value", blob)
            # The real .env file must not appear as a source.
            self.assertNotIn(".env", [k for k in found if k == ".env"])


class TestEndToEnd(unittest.TestCase):
    """scan -> generate -> vault against a realistic Node.js fixture."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.proj = self.root / "demo-app"
        self.proj.mkdir()
        self._build_fixture(self.proj)
        self._git_init(self.proj)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _build_fixture(proj: Path):
        (proj / "package.json").write_text(json.dumps({
            "name": "demo-app",
            "version": "1.0.0",
            "scripts": {
                "dev": "node --watch src/index.js",
                "build": "esbuild src/index.js --bundle --outfile=dist/bundle.js",
                "test": "vitest run",
            },
            "dependencies": {
                "express": "^4.18.0",
                "socket.io": "^4.7.0",
                "react": "^18.2.0",
                "next": "^14.0.0",
            },
            "devDependencies": {"vitest": "^1.0.0", "typescript": "^5.0.0"},
        }, indent=2), encoding="utf-8")
        (proj / ".env.example").write_text(
            "# Copy to .env and fill in\n"
            "SPOTIFY_CLIENT_ID=\n"
            "SPOTIFY_CLIENT_SECRET=\n"
            "HOST_PASSWORD=\n",
            encoding="utf-8",
        )
        (proj / "src").mkdir()
        (proj / "src" / "index.js").write_text(
            "const express = require('express');\nconst app = express();\n", encoding="utf-8"
        )
        (proj / "tests").mkdir()
        (proj / "tests" / "sample.test.js").write_text(
            "import { expect, it } from 'vitest';\nit('works', () => expect(1).toBe(1));\n",
            encoding="utf-8",
        )
        (proj / "README.md").write_text("# demo-app\n", encoding="utf-8")

    @staticmethod
    def _git_init(proj: Path):
        def git(*a):
            subprocess.run(["git", "-C", str(proj), *a], capture_output=True, text=True)
        git("init", "-q", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        # A remote WITH an embedded token, as found in the wild.
        git("remote", "add", "origin",
            "https://user:ghp_SECRET123@github.com/acme/demo-app.git")
        git("add", ".")
        git("commit", "-q", "-m", "init")

    def test_full_pipeline(self):
        oracle_dir = self.root / ".oracle"
        # Scan (directory output — the documented, previously broken form)
        r = _run(SCAN, "--path", str(self.proj), "--output", str(oracle_dir) + "/")
        self.assertEqual(r.returncode, 0, f"scan failed: {r.stderr}")
        report_path = oracle_dir / "scan-report.json"
        self.assertTrue(report_path.exists(),
                        "--output .oracle/ must create .oracle/scan-report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        # Frameworks: ALL of them, not just the first.
        fws = report.get("frameworks", [])
        for expected in ("Express", "Socket.IO", "React", "Next.js"):
            self.assertIn(expected, fws, f"framework {expected} not detected: {fws}")
        # npm scripts keep their commands, not just names.
        node_bs = next(bs for bs in report["build_systems"]
                       if bs.get("file") == "package.json")
        scripts = node_bs["parsed"]["scripts"]
        self.assertEqual(scripts["dev"], "node --watch src/index.js")
        self.assertEqual(scripts["test"], "vitest run")
        # Env var names detected, values never copied.
        self.assertIn(".env.example", report.get("env_vars", {}))
        self.assertIn("SPOTIFY_CLIENT_ID", report["env_vars"][".env.example"])
        self.assertNotIn("ghp_SECRET123", json.dumps(report), "token leaked into report")
        # Remote URL masked + deduplicated (git lists fetch+push separately).
        remotes = report["git"]["remotes"]
        origin = [x for x in remotes if x["name"] == "origin"]
        self.assertEqual(len(origin), 1, f"origin not deduplicated: {remotes}")
        self.assertNotIn("ghp_SECRET123", origin[0]["url"])
        self.assertIn("***", origin[0]["url"])
        # Test evidence: config marker AND files on disk.
        self.assertIn("Vitest", report["conventions"]["test_frameworks"])
        self.assertGreater(report["conventions"]["test_file_count"], 0)

        # ── 2. Generate with an intent file ──
        intent = {
            "purpose": "A demo party app that plays music and lets guests vote.",
            "pitfalls": [
                {"area": "Spotify tokens",
                 "note": "Refresh tokens are written to .data/tokens.json — never log it."},
                {"area": "Websockets",
                 "note": "Socket.IO rooms must be re-joined after a server restart."},
            ],
        }
        intent_path = self.root / "intent.json"
        intent_path.write_text(json.dumps(intent), encoding="utf-8")

        out_md = self.proj / "AGENTS.md"
        r = _run(GENERATE, "--scan", str(report_path), "--template", "agents-md",
                 "--output", str(out_md), "--intent-file", str(intent_path))
        self.assertEqual(r.returncode, 0, f"generate failed: {r.stderr}")
        md = out_md.read_text(encoding="utf-8")
        # Commands are present and runnable.
        self.assertIn("npm run dev", md)
        self.assertIn("node --watch src/index.js", md)
        # Env var names present, values absent.
        self.assertIn("SPOTIFY_CLIENT_ID", md)
        self.assertNotIn("ghp_SECRET123", md)
        # Frameworks listed.
        for fw in ("Express", "Socket.IO", "React", "Next.js"):
            self.assertIn(fw, md)
        # Intent and pitfalls embedded.
        self.assertIn("Project intent", md)
        self.assertIn("Known pitfalls", md)
        self.assertIn("Websockets", md)
        # No absolute paths (machine-specific) leaked into the doc.
        self.assertNotIn(str(self.proj), md)
        # English output (marketplace-ready).
        self.assertIn("## Stack", md)
        self.assertNotIn("non spécifié", md)

        # ── 3. Vault push from the scan report ──
        vault_dir = self.root / "vault"
        vault_dir.mkdir()
        r = _run(VAULT, "--scan", str(report_path), "--vault", str(vault_dir),
                 "--intent-file", str(intent_path))
        self.assertEqual(r.returncode, 0, f"vault failed: {r.stderr}")
        note = vault_dir / "05 - Projets" / "demo-app.md"
        self.assertTrue(note.exists(), "vault note not created")
        note_text = note.read_text(encoding="utf-8")
        self.assertTrue(note_text.startswith("---"), "note must have frontmatter")
        self.assertIn("Socket.IO", note_text)
        self.assertIn("Known pitfalls", note_text)

    def test_scan_output_file_form_still_works(self):
        """--output with an explicit .json path writes that exact file."""
        out = self.root / "custom-report.json"
        r = _run(SCAN, "--path", str(self.proj), "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        self.assertFalse(out.is_dir())


class TestPythonProjectRegressions(unittest.TestCase):
    """Regression tests for code-review findings, against a Python fixture.

    Covers: #1 overwrite protection, #2 dependencies + invented conventions,
    #3 entry points + pytest false positive, #5 auto summary,
    #6 self-scan / absolute paths / .gitignore, #7 packaging validation.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.proj = self.root / "acme-api"
        self.proj.mkdir()
        (self.proj / "pyproject.toml").write_text(
            "[project]\n"
            'name = "acme-api"\n'
            'description = "Tiny service that serves acme widgets for the demo dashboard."\n'
            'dependencies = ["flask>=3.0", "requests~=2.31"]\n'
            "\n"
            "[project.scripts]\n"
            'acme-cli = "cli:main"\n'
            "\n"
            "[tool.ruff]\n"
            "line-length = 100\n",
            encoding="utf-8",
        )
        (self.proj / "server.py").write_text(
            '"""Server entry point."""\n\n\n'
            "def create_app():\n"
            "    return None\n\n\n"
            'if __name__ == "__main__":\n'
            "    create_app()\n",
            encoding="utf-8",
        )
        (self.proj / "bootstrap.py").write_text(
            "def boot():\n    pass\n", encoding="utf-8"
        )
        (self.proj / "cli.py").write_text(
            "def main():\n    print('hi')\n", encoding="utf-8"
        )
        (self.proj / "app").mkdir()
        (self.proj / "app" / "__init__.py").write_text("", encoding="utf-8")
        (self.proj / "README.md").write_text(
            "# acme-api\n\n"
            "Serves acme widgets over HTTP for the demo dashboard team.\n",
            encoding="utf-8",
        )
        (self.proj / ".gitignore").write_text("dist/\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _scan(self):
        # Output INSIDE the project — the documented usage (`--output .oracle/`).
        oracle = self.proj / ".oracle"
        r = _run(SCAN, "--path", str(self.proj), "--output", str(oracle) + "/")
        self.assertEqual(r.returncode, 0, f"scan failed: {r.stderr}")
        report_path = oracle / "scan-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return report_path, report

    # ── Issue #2: real dependencies from pyproject (tomllib, not regex) ──

    def test_issue2_real_dependencies_detected(self):
        _, report = self._scan()
        pyproject_bs = next(
            bs for bs in report["build_systems"] if bs["file"] == "pyproject.toml"
        )
        deps = pyproject_bs["parsed"].get("deps_sample", [])
        self.assertIn("flask", deps, f"flask missing from {deps}")
        self.assertIn("requests", deps, f"requests missing from {deps}")
        # The old regex leaked manifest KEYS as if they were dependencies.
        for bogus in ("name", "description", "dependencies", "version"):
            self.assertNotIn(bogus, deps, f"manifest key '{bogus}' leaked into deps")

    # ── Issue #3: entry points from patterns, [project.scripts], __main__ ──

    def test_issue3_entry_points_detected(self):
        _, report = self._scan()
        paths = {ep["path"] for ep in report["entry_points"]}
        self.assertIn("server.py", paths, f"entry_points: {report['entry_points']}")
        self.assertIn("bootstrap.py", paths, f"entry_points: {report['entry_points']}")
        self.assertTrue(
            any(p.startswith("pyproject.toml:acme-cli") for p in paths),
            f"[project.scripts] not surfaced: {report['entry_points']}",
        )

    # ── Issue #3: pyproject alone must NOT declare pytest ──

    def test_issue3_no_pytest_false_positive(self):
        _, report = self._scan()
        self.assertNotIn(
            "pytest", report["conventions"]["test_frameworks"],
            "pyproject.toml without any pytest evidence must not imply pytest",
        )


    # ── Issue #2: CLAUDE.md must detect conventions, never invent them ──

    def test_issue2_claude_md_contains_no_invented_conventions(self):
        report_path, _ = self._scan()
        out = self.proj / "CLAUDE.md"
        r = _run(GENERATE, "--scan", str(report_path), "--template", "claude-md",
                 "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        claude = out.read_text(encoding="utf-8")
        for invented in ("88 chars", "Google style", "BEFORE code",
                         "type hints required", "Conventional commits"):
            self.assertNotIn(invented, claude, f"invented convention: {invented}")
        # Detected facts ARE reported (ruff line-length in pyproject).
        self.assertIn("100 characters", claude)

    # ── Issue #1: never overwrite an existing file without consent ──

    def test_issue1_refuses_overwrite_without_force(self):
        report_path, _ = self._scan()
        out = self.proj / "AGENTS.md"
        out.write_text("HAND EDIT — do not lose me.\n", encoding="utf-8")
        r = _run(GENERATE, "--scan", str(report_path), "--template", "agents-md",
                 "--output", str(out))
        self.assertEqual(r.returncode, 2,
                         f"expected exit 2, got {r.returncode}: {r.stderr}")
        self.assertEqual(out.read_text(encoding="utf-8"),
                         "HAND EDIT — do not lose me.\n",
                         "file was modified despite refusal")

    def test_issue1_force_overwrites_with_backup(self):
        report_path, _ = self._scan()
        out = self.proj / "AGENTS.md"
        out.write_text("HAND EDIT — do not lose me.\n", encoding="utf-8")
        r = _run(GENERATE, "--scan", str(report_path), "--template", "agents-md",
                 "--output", str(out), "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        new_content = out.read_text(encoding="utf-8")
        self.assertIn("## Stack", new_content)
        backup = out.with_name("AGENTS.md.bak")
        self.assertTrue(backup.exists(), "--force must save a .bak backup")
        self.assertEqual(backup.read_text(encoding="utf-8"),
                         "HAND EDIT — do not lose me.\n")

    def test_issue1_markers_enable_inplace_updates(self):
        report_path, _ = self._scan()
        out = self.proj / "AGENTS.md"
        # Fresh create: wrapped in markers automatically.
        r = _run(GENERATE, "--scan", str(report_path), "--template", "agents-md",
                 "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        first = out.read_text(encoding="utf-8")
        self.assertIn("<!-- oracle:start -->", first)
        # A user appends a personal note OUTSIDE the marked section...
        out.write_text(first + "\nMY PERSONAL NOTE\n", encoding="utf-8")
        # ...then regenerates: note survives, marked body is refreshed.
        r = _run(GENERATE, "--scan", str(report_path), "--template", "agents-md",
                 "--output", str(out))
        self.assertEqual(r.returncode, 0,
                         f"regeneration with markers must not need --force: {r.stderr}")
        merged = out.read_text(encoding="utf-8")
        self.assertIn("MY PERSONAL NOTE", merged, "text outside markers was lost")
        self.assertIn("## Stack", merged)

    # ── Issue #5: heuristic summary without an interview ──

    def test_issue5_auto_summary_without_interview(self):
        report_path, report = self._scan()
        self.assertTrue(report.get("summary"), "report.summary must be filled")
        # Attribution: this fixture has a pyproject description — it wins.
        self.assertEqual(report.get("summary_source"), "manifest (pyproject.toml)",
                         f"unexpected summary source: {report.get('summary_source')}")
        out = self.proj / "AGENTS.md"
        r = _run(GENERATE, "--scan", str(report_path), "--template", "agents-md",
                 "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        md = out.read_text(encoding="utf-8")
        self.assertIn("Project summary", md)
        self.assertIn("acme widgets", md)

    def test_issue5_summary_source_readme_then_docstring(self):
        # No manifest description and no useful README → first real README paragraph.
        bare = self.root / "readme-proj"
        bare.mkdir()
        (bare / "pyproject.toml").write_text(
            '[project]\nname = "bare"\n', encoding="utf-8"
        )
        (bare / "README.md").write_text(
            "# bare\n\nA tiny reader that parses CSV files into dictionaries.\n",
            encoding="utf-8",
        )
        r = _run(SCAN, "--path", str(bare), "--output", "-")
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads(r.stdout)
        self.assertIn("CSV", report.get("summary", ""))
        self.assertEqual(report.get("summary_source"), "README")

        # No README at all, no description → module docstring of the entry point.
        silent = self.root / "silent-proj"
        silent.mkdir()
        (silent / "main.py").write_text(
            '"""Orchestrates the nightly billing export for finance."""\n\n'
            "def main():\n    pass\n",
            encoding="utf-8",
        )
        r = _run(SCAN, "--path", str(silent), "--output", "-")
        self.assertEqual(r.returncode, 0, r.stderr)
        report = json.loads(r.stdout)
        self.assertIn("billing export", report.get("summary", ""))
        self.assertEqual(report.get("summary_source"), "docstring (main.py)")


    # ── Issue #6: no self-scan, no absolute paths, VCS stays clean ──

    def test_issue6_second_scan_does_not_count_itself(self):
        _, first = self._scan()
        _, second = self._scan()
        self.assertEqual(first["file_count"], second["file_count"],
                         "a second scan counted .oracle/ output")
        self.assertEqual(first["dir_count"], second["dir_count"],
                         "a second scan counted the .oracle directory")

    def test_issue6_report_is_shareable_and_gitignore_updated(self):
        _, report = self._scan()
        dump = json.dumps(report)
        self.assertNotIn(str(self.proj), dump,
                         "absolute path leaked into the scan report")
        self.assertNotIn("project_path", report,
                         "absolute project_path must not be in the report")
        gi = (self.proj / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".oracle", gi,
                      "scan must keep its output out of the project's VCS")

    # ── Issue #7: package validation must be falsifiable and -O-safe ──

    def test_issue7_validate_archive_catches_nested_skill_md(self):
        sys.path.insert(0, str(REPO_ROOT))
        try:
            import package_skill
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as td:
            bad_zip = Path(td) / "bad.zip"
            with zipfile.ZipFile(bad_zip, "w") as zf:
                zf.writestr("hermes-project-oracle/SKILL.md", "---\nname: x\n")
                zf.writestr("hermes-project-oracle/nested/SKILL.md", "dup")
                zf.writestr("hermes-project-oracle/scripts/run.py", "print(1)\n")
            errors = package_skill.validate_archive(
                bad_zip, "hermes-project-oracle"
            )
        self.assertTrue(errors, "nested SKILL.md must be reported as an error")
        self.assertTrue(any("SKILL.md" in e for e in errors), errors)

    def test_issue7_ship_filter_excludes_dev_artifacts(self):
        sys.path.insert(0, str(REPO_ROOT))
        try:
            import package_skill
        finally:
            sys.path.pop(0)
        cases = {
            REPO_ROOT / "hermes-project-oracle.zip": False,
            REPO_ROOT / "tests" / "test_oracle.py": False,
            REPO_ROOT / ".github" / "workflows" / "ci.yml": False,
            REPO_ROOT / ".venv" / "lib" / "x.py": False,
            REPO_ROOT / ".env": False,
            REPO_ROOT / "SKILL.md": True,
            REPO_ROOT / "scripts" / "oracle_scan.py": True,
        }
        for path, expected in cases.items():
            with self.subTest(path=str(path)):
                self.assertEqual(package_skill.should_ship(path), expected)


class TestVaultSafety(unittest.TestCase):
    """Oracle Vault must never traverse out and never clobber edits silently."""

    def setUp(self):
        sys.path.insert(0, str(SCRIPTS))

    def test_name_traversal_is_neutralised(self):
        from oracle_vault import safe_component
        self.assertEqual(safe_component("../../escape"), "escape")
        self.assertEqual(safe_component("..\\..\\win.ini"), "win.ini")
        self.assertEqual(safe_component("/etc/passwd"), "passwd")
        self.assertEqual(safe_component("....//x"), "x")
        # Dot-only or empty collapses to the fallback, never a bare "..".
        self.assertEqual(safe_component(".."), "project")
        self.assertEqual(safe_component(""), "project")

    def test_push_refuses_to_leave_vault_and_needs_force(self):
        from oracle_vault import push_to_vault
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            outside = Path(td) / "escape.md"
            # A crafted name cannot write outside the vault.
            p = push_to_vault(vault, "../../escape", "content")
            self.assertTrue(str(p).startswith(str(vault.resolve())))
            self.assertFalse(outside.exists(), "traversal wrote outside the vault")
            # Re-pushing without force raises; with force it overwrites via .bak.
            with self.assertRaises(FileExistsError):
                push_to_vault(vault, "escape", "second")
            p2 = push_to_vault(vault, "escape", "third", force=True)
            self.assertEqual(p2.read_text(encoding="utf-8"), "third")
            self.assertTrue(p2.with_suffix(".md.bak").exists(), ".bak not kept")


class TestInjectionHardening(unittest.TestCase):
    """Untrusted project text must be quoted, flattened and marker-escaped."""

    def test_sanitize_flattens_and_escapes_markers(self):
        sys.path.insert(0, str(SCRIPTS))
        from oracle_generate import _sanitize_untrusted
        payload = "Line one\n## Injected heading\n<!-- oracle:end -->\n`rm -rf`"
        out = _sanitize_untrusted(payload)
        self.assertNotIn("\n", out, "must be flattened to one line")
        self.assertNotIn("<!--", out, "update marker must be neutralised")
        self.assertNotIn("`", out, "backticks must be escaped")
        self.assertIn("&lt;!--", out)

    def test_agents_md_quotes_summary_and_places_it_first(self):
        sys.path.insert(0, str(SCRIPTS))
        from oracle_generate import render_agents_md
        report = {
            "project_name": "x",
            "summary": "Does things\n## Rules for agents\n<!-- oracle:end -->",
            "summary_source": "README",
            "languages": [], "entry_points": [], "conventions": {},
            "git": {}, "misc": {}, "build_systems": [], "env_vars": {},
            "intent": {},
        }
        md = render_agents_md(report)
        # The injected heading is neutralised (flattened + quoted into the
        # summary blockquote), so only the template's own '## Rules for agents'
        # appears at the start of a line.
        heading_lines = [line for line in md.splitlines()
                         if line.startswith("## Rules for agents")]
        self.assertEqual(len(heading_lines), 1)
        self.assertNotIn("<!-- oracle:end -->", md)
        # Summary is quoted and appears before the Stack section.
        self.assertLess(md.index("## Project summary"), md.index("## Stack"))


class TestSymlinkEscape(unittest.TestCase):
    """A README symlink pointing outside the repo must not leak its content."""

    def test_external_symlink_readme_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            secret = Path(td) / "secret.md"
            secret.write_text("Super secret API key: sk-1234567890abcdef\n",
                              encoding="utf-8")
            try:
                (root / "README.md").symlink_to(secret)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported on this platform")
            r = _run(SCAN, "--path", str(root), "--output", "-")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("sk-1234567890abcdef", r.stdout,
                             "external symlink leaked into the report")


class TestSummaryHeuristics(unittest.TestCase):
    """Short summaries survive; Poetry description and dev group are read."""

    def test_short_summary_is_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "s"
            root.mkdir()
            (root / "README.md").write_text("Tiny lib for parsing.\n",
                                            encoding="utf-8")
            r = _run(SCAN, "--path", str(root), "--output", "-")
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout)
            self.assertEqual(report.get("summary_source"), "README")

    def test_poetry_description_and_dev_group(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "poetry"
            root.mkdir()
            (root / "pyproject.toml").write_text(
                "[tool.poetry]\n"
                'name = "demo"\n'
                'description = "A poetry-described tool"\n'
                "[tool.poetry.dependencies]\n"
                'python = "^3.11"\n'
                'flask = "^3.0"\n'
                "[tool.poetry.group.dev.dependencies]\n"
                'pytest = "^8.0"\n',
                encoding="utf-8")
            (root / "main.py").write_text("def main():\n    pass\n",
                                          encoding="utf-8")
            r = _run(SCAN, "--path", str(root), "--output", "-")
            self.assertEqual(r.returncode, 0, r.stderr)
            report = json.loads(r.stdout)
            # No [project] table → the summary came from the pyproject manifest.
            self.assertEqual(report.get("summary_source"),
                             "manifest (pyproject.toml)")
            self.assertIn("A poetry-described tool", report.get("summary", ""))
            deps = json.dumps(report)
            self.assertIn("pytest", deps, "poetry dev group not read")
            self.assertIn("flask", deps)


if __name__ == "__main__":
    unittest.main()
