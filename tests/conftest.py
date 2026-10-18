"""Pytest configuration.

Importing ``scripts/`` packages them on ``sys.path`` so that ``--cov`` hooks
onto the real modules instead of only the subprocess entrypoints.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))