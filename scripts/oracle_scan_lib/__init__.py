"""Shared I/O + constants for the Oracle scanner.

Split out of ``oracle_scan.py`` to keep that file focused on orchestration.
These two modules are behaviour-neutral: they only hold helpers and constant
tables that already existed in the scanner.
"""

from __future__ import annotations

from oracle_scan_lib.constants import (  # noqa: F401  (re-exported for callers)
    CREDENTIAL_IN_URL_RE,
    ENV_EXAMPLE_NAMES,
    LANGUAGE_MAP,
    NODE_FRAMEWORKS,
    NODE_TEST_PACKAGES,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    sanitize_remote_url,
)
from oracle_scan_lib.io import (  # noqa: F401
    load_toml,
    read_in_root,
    read_maybe_rooted,
    safe_read,
)

__all__ = [
    "CREDENTIAL_IN_URL_RE",
    "ENV_EXAMPLE_NAMES",
    "LANGUAGE_MAP",
    "NODE_FRAMEWORKS",
    "NODE_TEST_PACKAGES",
    "SKIP_DIRS",
    "SKIP_EXTENSIONS",
    "load_toml",
    "read_in_root",
    "read_maybe_rooted",
    "safe_read",
    "sanitize_remote_url",
]
