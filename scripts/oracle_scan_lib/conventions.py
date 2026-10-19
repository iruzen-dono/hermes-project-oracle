"""Project conventions: tests, linting, line length, CI, editor, env files.

Functions moved verbatim out of oracle_scan.py — behaviour is unchanged.
"""

from __future__ import annotations

import contextlib
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
    """Detect quality tools, CI, test frameworks and conventions."""
    conv: dict[str, Any] = {}

    # ── Test frameworks ──
    detected_tests = _detect_test_frameworks(path)
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
    line_length = _detect_line_length(path)
    if line_length is not None:
        conv["line_length"], conv["line_length_source"] = line_length

    # Formatter: only when a config actually declares it.
    formatter = _detect_python_formatter(path, conv.get("quality_tools", []))
    if formatter:
        conv["python_formatter"] = formatter

    # ── CI/CD ──
    conv["ci_cd"] = _detect_ci_cd(path)

    # ── Docker ──
    conv["docker"] = _detect_docker(path)

    # ── Commit convention ──
    commit_convention = _detect_commit_convention(path)
    if commit_convention:
        conv["commit_convention"] = commit_convention

    # ── Editor ──
    editor = _detect_editor(path)
    if editor:
        conv["editor"] = editor

    # ── Monorepo detection ──
    conv["is_monorepo"] = _is_monorepo(path)

    # ── Test files on disk (evidence, not just config markers) ──
    conv["test_file_count"] = _count_test_files(path)

    return conv


def _detect_pytest(path: Path) -> bool:
    """True when pytest is evidenced by config or a real dependency (never bare pyproject)."""
    pdata = _load_toml(_read_maybe_rooted(path / "pyproject.toml", path))
    if not pdata:
        return False
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
        return bool(has_cfg or has_dep)
    except Exception:  # noqa: BLE001 — malformed manifest must not crash the scan
        return False


def _detect_node_test_deps(path: Path) -> list[str]:
    """Test frameworks named in package.json (dependencies + devDependencies)."""
    found: list[str] = []
    manifests = [path / "package.json"]
    with contextlib.suppress(OSError):
        manifests.extend(
            child / "package.json"
            for child in path.iterdir()
            if child.is_dir() and not child.name.startswith(".")
            and child.name not in _SKIP_DIRS
        )
    pkg_test_map = {
        "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
        "playwright": "Playwright", "@playwright/test": "Playwright",
        "cypress": "Cypress", "ava": "Ava", "tap": "tap",
    }
    for pkg in manifests:
        if not pkg.is_file():
            continue
        content = _safe_read(pkg)
        if not content:
            continue
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            continue
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for dep, tname in pkg_test_map.items():
            if dep in deps and tname not in found:
                found.append(tname)
        # Built-in runner needs no dependency (audit #2): any npm script
        # invoking `node --test` is evidence of a suite.
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict) and "node --test" not in found:
            for _cmd in scripts.values():
                if re.search(r"(^|[\s&|;])node\s+--test\b", str(_cmd)):
                    found.append("node --test")
                    break
    return found


def _detect_test_frameworks(path: Path) -> list[str]:
    """Detect test frameworks from config markers and real dependencies."""
    test_markers: dict[str, list[str]] = {
        "pytest": ["pytest.ini", "conftest.py"],
        "Jest": ["jest.config.js", "jest.config.ts", "jest.config.mjs"],
        "Vitest": ["vitest.config.ts", "vitest.config.js"],
        "Mocha": [".mocharc.js", ".mocharc.yml"],
        "PHPUnit": ["phpunit.xml", "phpunit.xml.dist"],
        "Pest": ["pest.php", "pest.xml"],
        "Cargo test": ["Cargo.toml"],
        "Go test": ["go.mod"],
        "RSpec": [".rspec"],
    }

    detected: list[str] = []
    for framework, markers in test_markers.items():
        if any((path / marker).is_file() for marker in markers):
            detected.append(framework)
    # Audit #5: JUnit is NOT implied by a bare pom.xml / build.gradle — only
    # when a real junit/jupiter/surefire dependency or a *Test file exists.
    if _detect_junit(path) and "JUnit 5" not in detected:
        detected.append("JUnit 5")
    if _detect_pytest(path) and "pytest" not in detected:
        detected.append("pytest")
    for tname in _detect_node_test_deps(path):
        if tname not in detected:
            detected.append(tname)
    return detected


def _detect_junit(path: Path) -> bool:
    """True when JUnit is evidenced by a dependency or a test file (never a bare pom)."""
    pom = path / "pom.xml"
    if pom.is_file():
        content = (_safe_read(pom) or "").lower()
        if any(marker in content for marker in (
            "junit", "jupiter", "surefire", "failsafe", "testng", "mockito", "assertj",
        )):
            return True
    gradle = path / "build.gradle"
    if gradle.is_file():
        content = (_safe_read(gradle) or "").lower()
        if any(marker in content for marker in (
            "junit", "jupiter", "testng", "mockito", "assertj", "usejunitplatform",
        )):
            return True
    # A *Test.java / *Tests.java file is itself evidence of a JUnit-style suite.
    for pat in ("*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt"):
        try:
            for f in path.rglob(pat):
                if any(s in f.parts for s in _SKIP_DIRS):
                    continue
                return True
        except OSError:
            continue
    return False


def _detect_line_length(path: Path) -> tuple[int, str] | None:
    """Detect the configured max line length (observed only, never invented)."""
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
                    return tbl["line-length"], src
        except Exception:
            continue
    if (path / ".editorconfig").is_file():
        ec = _safe_read(path / ".editorconfig") or ""
        m = re.search(r"max_line_length\s*=\s*(\d+)", ec)
        if m:
            return int(m.group(1)), "from .editorconfig"
    return None


def _detect_python_formatter(path: Path, quality_tools: list[str]) -> str | None:
    """Detect the Python formatter only when a config actually declares it."""
    try:
        if (path / "pyproject.toml").is_file():
            _pd = _load_toml(_read_maybe_rooted(path / "pyproject.toml", path)) or {}
            if isinstance((_pd.get("tool") or {}).get("black"), dict):
                return "Black"
        if (path / "ruff.toml").is_file() or (path / ".ruff.toml").is_file() \
                or "ruff.toml" in quality_tools:
            return "Ruff"
    except Exception:
        pass
    return None


def _detect_ci_cd(path: Path) -> list[str]:
    """Return the CI systems whose marker files/dirs exist."""
    ci_markers = [
        (".github/workflows", "GitHub Actions"),
        (".gitlab-ci.yml", "GitLab CI"),
        (".circleci/config.yml", "CircleCI"),
        ("Jenkinsfile", "Jenkins"),
        (".drone.yml", "Drone"),
        (".woodpecker.yml", "Woodpecker"),
        (".buildkite/pipeline.yml", "Buildkite"),
    ]
    return [name for dirname, name in ci_markers if (path / dirname).exists()]


def _detect_docker(path: Path) -> dict[str, bool]:
    """Return which Docker artefacts exist (Dockerfile, compose, ignore)."""
    docker: dict[str, bool] = {}
    for f in path.iterdir():
        if f.name == "Dockerfile" or f.name.startswith("Dockerfile."):
            docker["has_dockerfile"] = True
        if f.name in ("docker-compose.yml", "docker-compose.yaml"):
            docker["has_compose"] = True
    if (path / ".dockerignore").is_file():
        docker["has_dockerignore"] = True
    return docker


def _detect_commit_convention(path: Path) -> str | None:
    """Return the commit convention when there is evidence, else None."""
    if (path / ".commitlintrc.json").is_file() or (path / "commitlint.config.js").is_file():
        return "conventional-commits"
    if (path / "cliff.toml").is_file():
        return "conventional-commits (git-cliff)"
    if (path / ".github/semantic.yml").is_file():
        return "semantic-prs"
    if (path / ".git").exists():
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
                    return "conventional-commits (observed in git log)"
        except Exception:
            pass
    return None


def _detect_editor(path: Path) -> str | None:
    """Return the detected editor folder, last match wins (vscode < idea < cursor)."""
    editor = None
    if (path / ".vscode").is_dir():
        editor = "vscode"
    if (path / ".idea").is_dir():
        editor = "intellij"
    if (path / ".cursor").is_dir():
        editor = "cursor"
    return editor


def _is_monorepo(path: Path) -> bool:
    """Simple heuristic to detect a monorepo."""
    markers = 0
    # Multiple build systems — audit #2: two nested manifests already make a
    # monorepo (e.g. backend/ + frontend/ each with a package.json).
    builds = 0
    try:
        children = list(path.iterdir())
    except OSError:
        children = []
    for bs in ["pom.xml", "build.gradle", "Cargo.toml", "go.mod",
               "package.json", "pyproject.toml"]:
        for child in children:
            if child.is_dir() and (child / bs).is_file():
                builds += 1
    if builds >= 2:
        return True
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
                "*.test.mjs", "*.test.cjs", "*.test.mts", "*.test.cts",
                "*.spec.ts", "*.spec.js", "*.spec.tsx",
                "*.spec.mjs", "*.spec.cjs",
                "*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt")
    count = 0
    for pat in patterns:
        for f in path.rglob(pat):
            if any(s in f.parts for s in _SKIP_DIRS):
                continue
            count += 1
    # Bare `*.mjs` / `*.cjs` under a tests/ (or __tests__/) folder are real
    # suites for the built-in `node --test` runner (audit #2): the runner
    # needs no config file and no dependency, the folder layout is the
    # only marker. Count them once (patterns above already cover *.test.mjs).
    for test_dir_name in ("tests", "test", "__tests__"):
        for f in path.rglob(f"{test_dir_name}/*.mjs"):
            if any(s in f.parts for s in _SKIP_DIRS):
                continue
            if ".test." in f.name or ".spec." in f.name:
                continue  # already counted above
            count += 1
        for f in path.rglob(f"{test_dir_name}/*.cjs"):
            if any(s in f.parts for s in _SKIP_DIRS):
                continue
            if ".test." in f.name or ".spec." in f.name:
                continue
            count += 1
    return count
