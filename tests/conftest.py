"""Pytest configuration.

Put ``scripts/`` on ``sys.path`` so tests import the real modules (and so
``--cov`` hooks onto them instead of only the subprocess entrypoints).
Subprocess coverage (audit #9): the E2E tests launch the CLIs via
``subprocess.run`` — with ``parallel = true`` in ``.coveragerc``, every child
process started with ``COVERAGE_PROCESS_START`` set writes its own data file,
later combined with ``coverage combine``. See ``_run`` in ``test_oracle.py``.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

