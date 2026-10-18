"""Pytest configuration.

Put ``scripts/`` on ``sys.path`` so tests import the real modules (and so
``--cov`` hooks onto them instead of only the subprocess entrypoints).
Coverage inside subprocesses is intentionally not measured: the E2E tests
launch the CLIs with ``subprocess.run`` and chasing parallel coverage data
across temp cwd directories proved fragile (notably on Windows). The unit
tests in ``test_oracle_lib.py`` exercise the same code paths in-process.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

