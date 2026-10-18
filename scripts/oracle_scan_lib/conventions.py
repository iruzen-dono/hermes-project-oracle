"""Project conventions: tests, linting, line length, CI, editor, env files.

Functions moved verbatim out of oracle_scan.py — behaviour is unchanged.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from oracle_scan_lib.constants import ENV_EXAMPLE_NAMES as _ENV_EXAMPLE_NAMES
from oracle_scan_lib.constants import SKIP_DIRS as _SKIP_DIRS
from oracle_scan_lib.detectors import _flat_deps
from oracle_scan_lib.io import load_toml as _load_toml
from oracle_scan_lib.io import read_maybe_rooted as _read_maybe_rooted
from oracle_scan_lib.io import safe_read as _safe_read


def detect_conventions(path: Path) -> dict[str, Any]:
    """Détecte les outils de qualité, CI, tests, et conventions."""
    conv: dict[str, Any] = {}

    # ── Test frameworks ──
    test_markers: dict[str, list[str]] = {
        "pytest": ["pytest.ini", "conftest.py"],
        "JUnit 5": ["pom.xml", "build.gradle"],
        "Jest": ["jest.config.js", "jest.config.ts", "jest.config.mjs"],
        "Vitest": ["vitest.config.ts", "vitest.config.js"],
        "Mocha": [".mocharc.js", ".mocharc.yml"],
        "PHPUnit": ["phpunit.xml", "phpunit.xml.dist"],
        "Pest": ["pest.php", "pest.xml"],
        "Cargo test": ["Cargo.toml"],
        "Go test": ["go.mod"],
        "RSpec": [".rspec"],
    }

    detected_tests = []
    for framework, markers in test_markers.items():
        for marker in markers:
            f = path / marker
            if f.is_file():
                detected_tests.append(framework)
                break
            if marker == "pom.xml":
                content = _safe_read(path / "pom.xml")
                if content and "junit" in content.lower():
                    if "junit5" in content.lower() or "jupiter" in content.lower():
                        if "JUnit 5" not in detected_tests:
                            detected_tests.append("JUnit 5")
                    elif "JUnit" not in detected_tests:
                        detected_tests.append("JUnit")
            if marker == "build.gradle" or marker == "build.gradle.kts":
                content = _safe_read(path / marker)
                if content and "junit" in content.lower():
                    detected_tests.append(framework)

    # ── pytest: positive evidence only (issue: pyproject alone is NOT proof) ──
    pdata = _load_toml(_read_maybe_rooted(path / "pyproject.toml", path))
    if pdata:
        try:
            has_cfg = isinstance(pdata.get("tool", {}).get("pytest"), dict)
            deps_list: list[str] = []
            proj_tbl = pdata.get("project", {}) or {}
            deps_list.extend(_flat_deps(proj_tbl.get("dependencies", [])))
            for grp in (proj_tbl.get("optional-dependencies") or {}).values():
                deps_list.extend(_flat_deps(grp))
            for grp in (pdata.get("dependency-groups") or {}).values():
                deps_list.extend(_flat_deps(grp))
            # Poetry declares dev/test groups separately (poetry.group.*.dependencies).
            _poetry = ((pdata.get("tool") or {}).get("poetry") or {})
            for _grp_tbl in (_poetry.get("group") or {}).values():
                if isinstance(_grp_tbl, dict):
                    deps_list.extend(_flat_deps(_grp_tbl.get("dependencies", {})))
            has_dep = any(d.lower().startswith("pytest") for d in deps_list)
            if (has_cfg or has_dep) and "pytest" not in detected_tests:
                detected_tests.append("pytest")
        except Exception:
            pass

    # ── Test frameworks from package.json dependencies ──
    # Reading actual dependencies is more reliable than hunting config files.
    pkg = path / "package.json"
    if pkg.is_file():
        content = _safe_read(pkg)
        if content:
            try:
                data = json.loads(content)
                deps = {**data.get("dependencies", {}),
                        **data.get("devDependencies", {})}
                pkg_test_map = {
                    "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
                    "playwright": "Playwright", "@playwright/test": "Playwright",
                    "cypress": "Cypress", "ava": "Ava", "tap": "tap",
                }
                for dep, tname in pkg_test_map.items():
                    if dep in deps and tname not in detected_tests:
                        detected_tests.append(tname)
            except json.JSONDecodeError:
                pass

    conv["test_frameworks"] = list(set(detected_tests))

    # ── Linting / Formatting ──
    lint_files = [
        ".eslintrc.js", ".eslintrc.json", ".eslintrc.yaml", ".eslintrc.yml",
        ".prettierrc", ".prettierrc.js", ".prettierrc.json", ".prettierrc.yaml",
        "prettier.config.js",
        ".ruff.toml", "ruff.toml",
        ".flake8", "setup.cfg",
        ".editorconfig",
        ".php-cs-fixer.php", ".php-cs-fixer.dist.php",
        ".php_cs", ".php_cs.dist",
        "checkstyle.xml",
        ".ktlint.kts",
        ".golangci.yml", ".golangci.yaml",
        "biome.json", "biome.jsonc",
        "oxlintrc.json",
        "deno.json", "deno.jsonc",
    ]
    conv["quality_tools"] = [f for f in lint_files if (path / f).is_file()]

    # ── Detected settings — never invent rules, only report observed ones ──
    line_length = None
    line_length_source = None
    for toml_name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
        toml_path = path / toml_name
        if not toml_path.is_file():
            continue
        try:
            tdata = _load_toml(_read_maybe_rooted(toml_path, path))
            if tdata is None:
                continue
            # line-length may sit at the root (standalone ruff.toml), under
            # [ruff], under [tool.ruff] or under [tool.black] (pyproject).
            candidates = [
                (tdata, f"from {toml_name}"),
                (tdata.get("ruff") or {}, f"from {toml_name} [ruff]"),
                ((tdata.get("tool") or {}).get("ruff") or {},
                 f"from {toml_name} [tool.ruff]"),
                ((tdata.get("tool") or {}).get("black") or {},
                 f"from {toml_name} [tool.black]"),
            ]
            for tbl, src in candidates:
                if isinstance(tbl, dict) and isinstance(tbl.get("line-length"), int):
                    line_length = tbl["line-length"]
                    line_length_source = src
                    break
            if line_length is not None:
                break
        except Exception:
            continue
    if line_length is None and (path / ".editorconfig").is_file():
        ec = _safe_read(path / ".editorconfig") or ""
        m = re.search(r"max_line_length\s*=\s*(\d+)", ec)
        if m:
            line_length = int(m.group(1))
            line_length_source = "from .editorconfig"
    if line_length is not None:
        conv["line_length"] = line_length
        conv["line_length_source"] = line_length_source

    # Formatter: only when a config actually declares it.
    try:
        if (path / "pyproject.toml").is_file():
            _pd = _load_toml(_read_maybe_rooted(path / "pyproject.toml", path)) or {}
            if isinstance((_pd.get("tool") or {}).get("black"), dict):
                conv["python_formatter"] = "Black"
        if "python_formatter" not in conv and (
            (path / "ruff.toml").is_file() or (path / ".ruff.toml").is_file()
            or "ruff.toml" in conv.get("quality_tools", [])
        ):
            conv["python_formatter"] = "Ruff"
    except Exception:
        pass

    # ── CI/CD ──
    ci_markers = [
        (".github/workflows", "GitHub Actions"),
        (".gitlab-ci.yml", "GitLab CI"),
        (".circleci/config.yml", "CircleCI"),
        ("Jenkinsfile", "Jenkins"),
        (".drone.yml", "Drone"),
        (".woodpecker.yml", "Woodpecker"),
        (".buildkite/pipeline.yml", "Buildkite"),
    ]
    conv["ci_cd"] = [name for dirname, name in ci_markers if (path / dirname).exists()]

    # ── Docker ──
    docker: dict[str, bool] = {}
    for f in path.iterdir():
        if f.name == "Dockerfile" or f.name.startswith("Dockerfile."):
            docker["has_dockerfile"] = True
        if f.name in ("docker-compose.yml", "docker-compose.yaml"):
            docker["has_compose"] = True
    if (path / ".dockerignore").is_file():
        docker["has_dockerignore"] = True
    conv["docker"] = docker

    # ── Commit convention ──
    if (path / ".commitlintrc.json").is_file() or (path / "commitlint.config.js").is_file():
        conv["commit_convention"] = "conventional-commits"
    elif (path / "cliff.toml").is_file():
        conv["commit_convention"] = "conventional-commits (git-cliff)"
    elif (path / ".github/semantic.yml").is_file():
        conv["commit_convention"] = "semantic-prs"
    elif (path / ".git").exists():
        # Observe the history instead of guessing (evidence, not invention).
        try:
            proc = subprocess.run(
                ["git", "-C", str(path), "log", "--oneline", "-30"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                sample = [ln for ln in proc.stdout.splitlines() if ln.strip()]
                conv_re = re.compile(
                    r"^\w+ (feat|fix|chore|docs|refactor|test|style|perf|build|ci)"
                    r"(\([^)]*\))?!?:"
                )
                hits = sum(1 for ln in sample if conv_re.search(ln))
                if sample and hits / len(sample) >= 0.6:
                    conv["commit_convention"] = "conventional-commits (observed in git log)"
        except Exception:
            pass

    # ── Editor ──
    if (path / ".vscode").is_dir():
        conv["editor"] = "vscode"
    if (path / ".idea").is_dir():
        conv["editor"] = "intellij"
    if (path / ".cursor").is_dir():
        conv["editor"] = "cursor"

    # ── Monorepo detection ──
    conv["is_monorepo"] = _is_monorepo(path)

    # ── Test files on disk (evidence, not just config markers) ──
    conv["test_file_count"] = _count_test_files(path)

    return conv


def _is_monorepo(path: Path) -> bool:
    """Heuristique simple pour détecter un monorepo."""
    markers = 0
    # Multiple build systems
    builds = 0
    for bs in ["pom.xml", "build.gradle", "Cargo.toml", "go.mod",
               "package.json", "pyproject.toml"]:
        for child in path.iterdir():
            if child.is_dir() and (child / bs).is_file():
                builds += 1
    if builds >= 3:
        markers += 1
    # Standard monorepo descriptors
    if (path / "lerna.json").is_file() or (path / "nx.json").is_file() \
       or (path / "turbo.json").is_file() or (path / "rush.json").is_file():
        markers += 2
    # packages/ or apps/ directory with many sub-projects
    for subdir in ["packages", "apps", "modules", "services"]:
        d = path / subdir
        if d.is_dir():
            count = sum(1 for c in d.iterdir() if c.is_dir())
            if count >= 3:
                markers += 1
                break
    return markers >= 2


def _parse_env_names(content: str) -> list[str]:
    """Extract valid variable names from env-file content (values ignored)."""
    names: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            var = line.split("=", 1)[0].strip()
            if var and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var):
                names.append(var)
    return sorted(set(names))


def detect_env_files(path: Path) -> dict[str, list[str]]:
    """Extract variable NAMES from example env files (never values, never real .env).

    Checks the project root and one level of subdirectories (monorepo support,
    e.g. backend/.env.example). Keys are relative paths.
    """
    found: dict[str, list[str]] = {}
    candidates: list[Path] = [path / n for n in _ENV_EXAMPLE_NAMES]
    try:
        for child in path.iterdir():
            if child.is_dir() and child.name not in _SKIP_DIRS and not child.name.startswith("."):
                candidates.extend(child / n for n in _ENV_EXAMPLE_NAMES)
    except PermissionError:
        pass

    for f in candidates:
        if not f.is_file():
            continue
        # Security: never read an example file that is a symlink escaping the repo.
        try:
            if f.is_symlink() and not f.resolve().is_relative_to(path):
                continue
        except OSError:
            continue
        content = _safe_read(f, max_bytes=20_000)
        if content is None:
            continue
        names = _parse_env_names(content)
        if names:
            try:
                key = f.relative_to(path).as_posix()
            except ValueError:
                key = f.name
            found[key] = names
    return found


def _count_test_files(path: Path) -> int:
    """Count test files by naming convention (test_*.py, *.test.ts, *_test.go...)."""
    patterns = ("test_*.py", "*_test.py", "*_test.go", "*_test.rs",
                "*.test.ts", "*.test.tsx", "*.test.js", "*.test.jsx",
                "*.spec.ts", "*.spec.js", "*.spec.tsx",
                "*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt")
    count = 0
    for pat in patterns:
        for f in path.rglob(pat):
            if any(s in f.parts for s in _SKIP_DIRS):
                continue
            count += 1
    return count
