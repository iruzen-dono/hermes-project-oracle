"""In-process unit tests for the shared oracle libraries.

The CLI-level behaviour is covered end-to-end by ``test_oracle.py`` (which
runs the scripts in subprocesses). These tests import the modules directly to
exercise the security-sensitive helpers the E2E path cannot reach: symlink
escape guards, TOML hardening, URL credential masking and vault traversal
protection.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from oracle_scan_lib import constants as k  # noqa: E402
from oracle_scan_lib import io  # noqa: E402
from oracle_scan_lib import structure  # noqa: E402
from oracle_scan_lib import vcs  # noqa: E402
from oracle_vault import push_to_vault, safe_component  # noqa: E402
from safe_io import atomic_write, refuse_symlink_escape  # noqa: E402


class TestSafeRead(unittest.TestCase):
    """read_in_root must refuse symlinks escaping the scanned root."""

    def test_reads_normal_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
            self.assertIn("name='x'", io.read_in_root(root / "pyproject.toml", root))

    def test_refuses_symlink_escaping_root(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            secret = Path(outside) / "secret.txt"
            secret.write_text("TOP-SECRET-VALUE", encoding="utf-8")
            link = root / "pyproject.toml"
            try:
                link.symlink_to(secret)
            except OSError:
                self.skipTest("symlinks unavailable on this platform")
            self.assertIsNone(
                io.read_in_root(link, root),
                "a symlink escaping the root must never be read",
            )

    def test_refuses_dangling_and_oversized(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIsNone(io.read_in_root(root / "missing.toml", root))
            big = root / "big.txt"
            big.write_text("x" * 60_000, encoding="utf-8")
            self.assertIsNone(io.safe_read(big), "oversized files must be skipped")


class TestTomlAndUrl(unittest.TestCase):
    """Manifest parsing and remote-URL credential masking."""

    def test_load_toml_handles_invalid(self):
        self.assertIsNone(io.load_toml(None))
        self.assertIsNone(io.load_toml(""))
        self.assertIsNone(io.load_toml("= not toml =="))
        self.assertEqual(io.load_toml('name = "x"')["name"], "x")

    def test_sanitize_remote_url(self):
        # Credentials are masked, never echoed: user-info -> ***@.
        # NOTE: EXAMPLE-USER / EXAMPLE-TOKEN are obviously-fake placeholders
        # (not real secrets) so secret-scanners never flag this test.
        self.assertEqual(
            k.sanitize_remote_url("https://EXAMPLE-USER:EXAMPLE-TOKEN@github.com/org/repo.git"),
            "https://***@github.com/org/repo.git",
        )
        self.assertNotIn("EXAMPLE-TOKEN", k.sanitize_remote_url(
            "https://EXAMPLE-USER:EXAMPLE-TOKEN@github.com/org/repo.git"))
        self.assertEqual(
            k.sanitize_remote_url("https://github.com/org/repo.git"),
            "https://github.com/org/repo.git",
        )



class TestVaultPathSafety(unittest.TestCase):
    """safe_component + push_to_vault must never write outside the vault."""

    def test_safe_component_blocks_traversal(self):
        self.assertEqual(safe_component("../../escape"), "escape")
        self.assertEqual(safe_component("..\\..\\win"), "win")
        self.assertEqual(safe_component("..."), "project")
        self.assertEqual(safe_component(""), "project")
        self.assertEqual(safe_component("a/b/../c"), "c")

    def test_push_to_vault_refuses_escape_and_protects_edits(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            vault = Path(td) / "vault"
            vault.mkdir()
            outside = Path(out)

            note = push_to_vault(vault, "proj", "v1", category="Notes", force=True)
            self.assertTrue(note.is_relative_to(vault))

            # An existing note is never overwritten silently.
            with self.assertRaises(FileExistsError):
                push_to_vault(vault, "proj", "v2", category="Notes", force=False)
            self.assertEqual(note.read_text(encoding="utf-8"), "v1")

            # --force keeps a .bak copy first.
            push_to_vault(vault, "proj", "v3", category="Notes", force=True)
            self.assertEqual(note.read_text(encoding="utf-8"), "v3")
            self.assertEqual(note.with_suffix(".md.bak").read_text(encoding="utf-8"), "v1")

            # A traversal attempt lands INSIDE the vault, never outside.
            escape = push_to_vault(vault, "../..", "x", category="../evil", force=True)
            self.assertTrue(escape.is_relative_to(vault.resolve()))
            self.assertFalse(any(outside.iterdir()), "nothing may be written outside")

    def test_atomic_write_refuses_symlink_and_enforces_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inside = root / "sub" / "f.txt"
            atomic_write(inside, "data")
            self.assertEqual(inside.read_text(encoding="utf-8"), "data")
            # Atomic rewrite of an existing regular file.
            atomic_write(inside, "data2")
            self.assertEqual(inside.read_text(encoding="utf-8"), "data2")

            outside = root.parent / "atomic-escape.txt"
            try:
                link = root / "link.txt"
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable on this platform")

            # Refuses to write *through* a symlink, wherever it points.
            with self.assertRaises(ValueError):
                atomic_write(link, "nope")
            with self.assertRaises(ValueError):
                refuse_symlink_escape(link)

            # With must_stay_under_root, an escaping target is refused too.
            with self.assertRaises(ValueError):
                atomic_write(outside, "nope", must_stay_under_root=root)
            # And the safe case still succeeds.
            ok = root / "ok.txt"
            atomic_write(ok, "ok", must_stay_under_root=root)
            self.assertEqual(ok.read_text(encoding="utf-8"), "ok")
            self.assertFalse(outside.exists(), "nothing may be written outside")


class TestStructureAndGit(unittest.TestCase):
    """Structure walk and git context stay hardened."""

    def test_structure_skips_symlinked_dirs(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            (root / "real").mkdir()
            (root / "real" / "a.py").write_text("x=1", encoding="utf-8")
            ext = Path(outside) / "leak.txt"
            ext.write_text("secret", encoding="utf-8")
            try:
                (root / "leak").symlink_to(ext.parent, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable on this platform")
            names = {e["name"] for e in structure.get_structure(root)}
            self.assertIn("real", names)
            self.assertNotIn("leak", names)

    def test_git_context_non_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = vcs.get_git_context(Path(td))
            self.assertFalse(ctx["has_git"])


if __name__ == "__main__":
    unittest.main()
