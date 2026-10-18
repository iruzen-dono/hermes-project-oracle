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


if __name__ == "__main__":
    unittest.main()
