#!/usr/bin/env python3
"""
Project Oracle — deep project scanner.

Analyses a codebase in depth and produces a structured JSON report covering
languages, frameworks, build systems, entry points, conventions, environment
variable names, git context, and project tree. Zero dependencies.

Usage:
    python oracle_scan.py --path /path/to/project --output .oracle/
    python oracle_scan.py --path . --output .oracle/scan-report.json --depth 2
    python oracle_scan.py --path . --output /dev/stdout

--output accepts a directory (`.oracle/` or `.oracle`) or an explicit
JSON file path (`report.json`). Cross-platform: Windows, Linux, macOS.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from version import __version__
except ImportError:  # scripts/ not on sys.path — visible, not silently wrong
    __version__ = "unknown"

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("oracle-scan")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _safe_read(path: Path, max_bytes: int = 50_000) -> str | None:
    """Lit un fichier texte si sa taille est raisonnable."""
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            log.debug("Skipping large file (%d bytes): %s", path.stat().st_size, path)
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        log.debug("Permission denied: %s", path)
        return None
    except Exception as exc:
        log.debug("Cannot read %s: %s", path, exc)
        return None


_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", ".env", "__pycache__",
    "target", "build", "dist", ".gradle", ".next", ".nuxt", ".output",
    ".vercel", ".cache", "vendor", "bundle", ".tox", ".eggs", "eggs",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
    ".stack-work", "result", "_build", "deps",
    "third_party", "third-party", "3rdparty",
    # Never scan our own output — a second run must not count itself.
    ".oracle",
}

_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".o", ".obj", ".lib", ".a",
    ".min.js", ".min.css",
    ".map", ".br",
}

_LANGUAGE_MAP: dict[str, tuple[str, str]] = {
    ".py": ("Python", "python"),
    ".java": ("Java", "java"),
    ".kt": ("Kotlin", "kotlin"),
    ".kts": ("Kotlin Script", "kotlin"),
    ".ts": ("TypeScript", "typescript"),
    ".tsx": ("TypeScript React", "typescript"),
    ".js": ("JavaScript", "javascript"),
    ".jsx": ("JavaScript React", "javascript"),
    ".mjs": ("JavaScript (ESM)", "javascript"),
    ".cjs": ("JavaScript (CJS)", "javascript"),
    ".go": ("Go", "go"),
    ".rs": ("Rust", "rust"),
    ".php": ("PHP", "php"),
    ".cs": ("C#", "csharp"),
    ".rb": ("Ruby", "ruby"),
    ".swift": ("Swift", "swift"),
    ".dart": ("Dart", "dart"),
    ".vue": ("Vue", "vue"),
    ".svelte": ("Svelte", "svelte"),
    ".astro": ("Astro", "astro"),
    ".sql": ("SQL", "sql"),
    ".r": ("R", "r"),
    ".scala": ("Scala", "scala"),
    ".ex": ("Elixir", "elixir"),
    ".exs": ("Elixir Script", "elixir"),
    ".clj": ("Clojure", "clojure"),
    ".hs": ("Haskell", "haskell"),
    ".ml": ("OCaml", "ocaml"),
}


# ── Detection functions ─────────────────────────────────────────────────────


def detect_languages(path: Path) -> list[dict[str, Any]]:
    """Compte les fichiers par extension et retourne les langages détectés."""
    counts: defaultdict[str, int] = defaultdict(int)
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        name = f.name
        # Skip common generated / minified
        if ".min." in name or name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext in _SKIP_EXTENSIONS:
            continue
        counts[ext] += 1

    lang_scores: defaultdict[str, int] = defaultdict(int)
    for ext, count in counts.items():
        if ext in _LANGUAGE_MAP:
            _, key = _LANGUAGE_MAP[ext]
            lang_scores[key] += count

    total = sum(lang_scores.values()) or 1
    result = []
    seen = set()
    for key in sorted(lang_scores, key=lambda k: -lang_scores[k]):
        if key in seen:
            continue
        seen.add(key)
        # Find the best display name for this key
        display = key
        for ext, (name, k) in _LANGUAGE_MAP.items():
            if k == key and name:
                display = name
                break
        result.append({
            "key": key,
            "name": display,
            "files": lang_scores[key],
            "ratio": round(lang_scores[key] / total * 100, 1),
        })
    return result


def _find_config(path: Path, *names: str) -> Path | None:
    """Cherche le premier fichier de config existant."""
    for name in names:
        p = path / name
        if p.is_file():
            return p
    return None


def _detect_python(pyproject: Path | None) -> dict[str, Any]:
    """Analyse un projet Python via pyproject.toml."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(pyproject) if pyproject else None
    if not content:
        return result

    # Build system
    bs = re.search(r'requires\s*=\s*\["([^"]+)"', content)
    if bs:
        result["build_system"] = bs.group(1)

    # Structured parse (PEP 621 / Poetry) — tomllib, stdlib 3.11+
    import tomllib as _tomllib
    try:
        data = _tomllib.loads(content)
    except Exception:
        data = None
    if data:
        proj = data.get("project", {}) or {}
        # PEP 621: list of requirement strings; Poetry: name->spec table.
        deps: list[str] = list(_flat_deps(proj.get("dependencies", [])))
        for group in (proj.get("optional-dependencies") or {}).values():
            deps.extend(_flat_deps(group))
        poetry = ((data.get("tool") or {}).get("poetry") or {})
        if not deps:
            deps = [d for d in _flat_deps(poetry.get("dependencies", {}))
                    if d.lower() != "python"]
        # Poetry also declares dependency groups (dev, test, …).
        for grp in (poetry.get("group") or {}).values():
            if isinstance(grp, dict):
                deps.extend(d for d in _flat_deps(grp.get("dependencies", {}))
                            if d.lower() != "python")
        if deps:
            result["deps_sample"] = deps[:30]
        # Issue #5: heuristic project summary straight from the manifest.
        if isinstance(proj.get("description"), str) and proj["description"].strip():
            result["description"] = proj["description"].strip()[:300]
        elif isinstance(poetry.get("description"), str) and poetry["description"].strip():
            result["description"] = poetry["description"].strip()[:300]
            result["description_source"] = "poetry"
        # Issue #3: [project.scripts] are declared entry points.
        scripts_tbl = proj.get("scripts") or {}
        if isinstance(scripts_tbl, dict) and scripts_tbl:
            result["console_scripts"] = {
                str(k): str(v) for k, v in list(scripts_tbl.items())[:15]
            }

    # Framework detection
    for fw, hints in [
        ("FastAPI", ["fastapi"]),
        ("Django", ["django"]),
        ("Flask", ["flask"]),
        ("Litestar", ["litestar"]),
        ("Pydantic", ["pydantic"]),
        ("Streamlit", ["streamlit"]),
        ("Reflex", ["reflex"]),
    ]:
        if any(h in content.lower() for h in hints):
            result["framework"] = fw
            break

    return result


def _flat_deps(d: Any) -> list[str]:
    """Extract bare package names from a dependency container.

    Accepts PEP 621's list of requirement strings ("flask>=3.0",
    "requests[security]~=2.31") or a Poetry-style mapping ({name: spec}).
    """
    if isinstance(d, dict):
        return [str(name) for name in d]
    out: list[str] = []
    if isinstance(d, list):
        for item in d:
            if not isinstance(item, str):
                continue
            name = re.split(r"[\s\[<>=!~;#@]", item.strip(), 1)[0].strip()
            if name:
                out.append(name)
    return out


_NODE_FRAMEWORKS: list[tuple[str, str]] = [
    # (package name, display name) — meta-frameworks first, then servers, then UI libs.
    ("next", "Next.js"), ("nuxt", "Nuxt"), ("remix", "Remix"), ("gatsby", "Gatsby"),
    ("astro", "Astro"), ("@angular/core", "Angular"), ("angular", "Angular"),
    ("@nestjs/core", "NestJS"), ("nest", "NestJS"),
    ("express", "Express"), ("fastify", "Fastify"), ("koa", "Koa"), ("hapi", "Hapi"),
    ("socket.io", "Socket.IO"),
    ("react", "React"), ("react-native", "React Native"), ("expo", "Expo"),
    ("vue", "Vue"), ("svelte", "Svelte"), ("solid-js", "SolidJS"),
    ("vite", "Vite"), ("webpack", "Webpack"), ("tailwindcss", "Tailwind CSS"),
]

_NODE_TEST_PACKAGES = ("jest", "vitest", "mocha", "playwright", "@playwright/test",
                       "cypress", "ava", "tap")


def _detect_node(package_json: Path | None) -> dict[str, Any]:
    """Analyse un projet Node.js via package.json (frameworks multiples, scripts complets)."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(package_json) if package_json else None
    if not content:
        return result

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return result

    scripts = data.get("scripts", {})
    if isinstance(scripts, dict):
        # Keep the command, not just the name: agents need `npm run build`, not `build`.
        result["scripts"] = {
            k: (str(v)[:200] + "…" if len(str(v)) > 200 else str(v))
            for k, v in list(scripts.items())[:15]
        }
    all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    if not isinstance(all_deps, dict):
        all_deps = {}
    result["deps_sample"] = list(all_deps.keys())[:50]
    # One-line project purpose (issue #5): package.json description field.
    if isinstance(data.get("description"), str) and data["description"].strip():
        result["description"] = data["description"].strip()[:300]

    # Framework detection — collect ALL matches, not just the first.
    frameworks = [display for pkg, display in _NODE_FRAMEWORKS if pkg in all_deps]
    seen_fw: set[str] = set()
    result["frameworks"] = [fw for fw in frameworks if not (fw in seen_fw or seen_fw.add(fw))]
    if result["frameworks"]:
        result["framework"] = result["frameworks"][0]

    # Test evidence from deps + test script command.
    test_tools = [pkg for pkg in _NODE_TEST_PACKAGES if pkg in all_deps]
    if test_tools:
        result["test_tools"] = test_tools
    if isinstance(scripts, dict) and "test" in scripts:
        result["has_test_script"] = True
        result["test_command"] = str(scripts["test"])[:200]

    # Package manager detection
    for pm_file, pm_name in [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
    ]:
        if (package_json.parent / pm_file).exists():
            result["pm"] = pm_name
            break
    if "pm" not in result and isinstance(data.get("packageManager"), str):
        result["pm"] = data["packageManager"].split("@")[0]

    # TypeScript + Node engine constraint
    if "typescript" in all_deps or (package_json.parent / "tsconfig.json").exists():
        result["typescript"] = True
    engines = data.get("engines", {})
    if isinstance(engines, dict) and engines.get("node"):
        result["node_engine"] = str(engines["node"])[:50]

    return result


def _detect_java_maven(pom: Path | None) -> dict[str, Any]:
    """Analyse un projet Maven."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(pom) if pom else None
    if not content:
        return result

    artifact = re.search(r"<artifactId>([^<]+)</artifactId>", content)
    if artifact:
        result["artifact"] = artifact.group(1)

    group = re.search(r"<groupId>([^<]+)</groupId>", content)
    if group:
        result["group"] = group.group(1)

    if "spring-boot" in content.lower():
        result["framework"] = "Spring Boot"
    if "kotlin" in content.lower():
        result["language"] = "Kotlin"
    if "quarkus" in content.lower():
        result["framework"] = "Quarkus"

    return result


def _detect_gradle(build_file: Path | None) -> dict[str, Any]:
    """Analyse un projet Gradle."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(build_file) if build_file else None
    if not content:
        return result

    plugins = re.findall(r'id\s+["\']([^"\']+)["\']', content)
    if plugins:
        result["plugins"] = plugins

    if "spring" in content.lower() and "boot" in content.lower():
        result["framework"] = "Spring Boot"
    if "org.jetbrains.kotlin" in content:
        result["language"] = "Kotlin"

    return result


def _detect_cargo(cargo_toml: Path | None) -> dict[str, Any]:
    """Analyse un projet Rust via Cargo.toml."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(cargo_toml) if cargo_toml else None
    if not content:
        return result

    name = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if name:
        result["crate_name"] = name.group(1)

    # Detect key frameworks
    for fw, patterns in [
        ("Axum", ["axum"]),
        ("Actix-web", ["actix-web"]),
        ("Rocket", ["rocket"]),
        ("Tokio", ["tokio"]),
        ("Serde", ["serde"]),
        ("Leptos", ["leptos"]),
        ("Yew", ["yew"]),
        ("Tauri", ["tauri"]),
    ]:
        if any(p in content.lower() for p in patterns):
            result["framework"] = fw
            break

    return result


def _detect_go(go_mod: Path | None) -> dict[str, Any]:
    """Analyse un projet Go via go.mod."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(go_mod) if go_mod else None
    if not content:
        return result

    module = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
    if module:
        result["module"] = module.group(1)

    go_ver = re.search(r"^go\s+([\d.]+)", content, re.MULTILINE)
    if go_ver:
        result["go_version"] = go_ver.group(1)

    return result


def _detect_php(composer: Path | None) -> dict[str, Any]:
    """Analyse un projet PHP via composer.json."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(composer) if composer else None
    if not content:
        return result

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return result

    result["name"] = data.get("name", "")

    deps = {**data.get("require", {}), **data.get("require-dev", {})}
    result["deps_sample"] = list(deps.keys())[:30]

    if "laravel/framework" in deps or "laravel" in content.lower():
        result["framework"] = "Laravel"
    elif "symfony" in content.lower():
        result["framework"] = "Symfony"
    elif "livewire" in content.lower():
        result["framework"] = "Livewire"

    return result


def detect_build_system(path: Path) -> list[dict[str, str]]:
    """Détecte les systèmes de build et fichiers de config."""
    config_scanners = [
        ("pyproject.toml", "Python/pyproject", _detect_python),
        ("setup.py", "Python/setup.py", None),
        ("setup.cfg", "Python/setup.cfg", None),
        ("package.json", "Node.js", _detect_node),
        ("pom.xml", "Maven", _detect_java_maven),
        ("build.gradle", "Gradle (Groovy)", _detect_gradle),
        ("build.gradle.kts", "Gradle (Kotlin DSL)", _detect_gradle),
        ("Cargo.toml", "Rust/Cargo", _detect_cargo),
        ("go.mod", "Go Module", _detect_go),
        ("composer.json", "PHP/Composer", _detect_php),
        ("Gemfile", "Ruby/Bundler", None),
        ("CMakeLists.txt", "CMake", None),
        ("Makefile", "Make", None),
        ("mix.exs", "Elixir/Mix", None),
        ("project.clj", "Clojure/Leiningen", None),
        ("stack.yaml", "Haskell/Stack", None),
        ("*.sln", ".NET Solution", None),
        ("pubspec.yaml", "Dart/Flutter", None),
    ]

    results = []
    for name, label, scanner in config_scanners:
        if "*" in name:
            # Glob pattern
            matches = list(path.glob(name))
            if matches:
                results.append({"file": name, "label": label, "files": len(matches)})
                continue
        f = path / name
        if f.is_file():
            entry = {"file": f.name, "label": label}
            if scanner:
                parsed = scanner(f)
                entry["parsed"] = parsed
            results.append(entry)

    return results


def detect_frameworks(scan: dict[str, Any]) -> list[str]:
    """Collect every framework found across parsed configs (a project usually has several)."""
    fws: list[str] = []
    for bs in scan.get("build_systems", []):
        parsed = bs.get("parsed", {})
        if not isinstance(parsed, dict):
            continue
        for key in ("frameworks", "framework"):
            val = parsed.get(key)
            if isinstance(val, str):
                fws.append(val)
            elif isinstance(val, list):
                fws.extend(v for v in val if isinstance(v, str))

    # Special files heuristic (only if nothing was detected yet)
    if not fws:
        special: list[tuple[str, str]] = [
            ("manage.py", "Django"),
            ("app.py", "Flask"),
            ("artisan", "Laravel"),
            ("bin/console", "Symfony"),
        ]
        root = Path(scan.get("project_path", "."))
        for fname, fw in special:
            if (root / fname).is_file():
                fws.append(fw)
                break

    # Dedupe, keep order
    seen: set[str] = set()
    return [fw for fw in fws if not (fw in seen or seen.add(fw))]


def detect_entry_points(path: Path) -> list[dict[str, str]]:
    """Trouve les points d'entrée du projet (fichiers de démarrage)."""
    patterns = {
        "main.py": "application_entry",
        "app.py": "application_entry",
        "cli.py": "cli_entry",
        "run.py": "application_entry",
        "server.py": "server_entry",
        "bootstrap.py": "bootstrap_entry",
        "wsgi.py": "wsgi_entry",
        "asgi.py": "asgi_entry",
        "manage.py": "django_entry",
        "launcher.py": "bootstrap_entry",
        "start.py": "bootstrap_entry",
        "mcp_server.py": "mcp_entry",
        "__main__.py": "module_entry",
        "artisan": "laravel_cli",
        "Program.cs": "dotnet_entry",
        "main.rs": "rust_entry",
        "main.go": "go_entry",
        "index.tsx": "react_entry",
        "index.ts": "ts_entry",
        "index.js": "js_entry",
        "pages/_app.tsx": "nextjs_entry",
        "pages/_app.js": "nextjs_entry",
        "src/main.tsx": "react_entry",
        "src/main.ts": "ts_entry",
        "src/main.js": "js_entry",
        "src/main.rs": "rust_entry",
        "src/server.py": "server_entry",
        "src/cli.py": "cli_entry",
        "lib/main.dart": "flutter_entry",
    }

    entries = []
    for pat, etype in patterns.items():
        for found in path.rglob(pat):
            if found.is_file() and not any(
                skip in found.parts for skip in ["node_modules", ".git", ".venv", "venv", "__pycache__"]
            ):
                try:
                    rel = found.relative_to(path)
                except ValueError:
                    continue
                entries.append({"path": str(rel.as_posix()), "type": etype})

    # Spring Boot patterns (Application.kt, Application.java)
    for pattern in ("**/Application.kt", "**/Application.java",
                    "**/*Application.kt", "**/*Application.java"):
        for found in path.glob(pattern):
            if found.is_file() and ".git" not in found.parts:
                try:
                    rel = found.relative_to(path)
                except ValueError:
                    continue
                entries.append({"path": str(rel.as_posix()), "type": "spring_boot_entry"})

    # Declared console scripts: [project.scripts] in pyproject.toml (issue #3)
    pyproject_toml = path / "pyproject.toml"
    if pyproject_toml.is_file():
        try:
            import tomllib as _tl
            pdata = _tl.loads(pyproject_toml.read_text(encoding="utf-8"))
            scripts_tbl = ((pdata.get("project") or {}).get("scripts") or {})
            for cname, target in list(scripts_tbl.items())[:10]:
                entries.append({
                    "path": f"pyproject.toml:{cname}",
                    "type": f"console_script -> {target}",
                })
        except Exception:
            pass

    # Python entry points: `if __name__ == "__main__"` verified with ast
    # (covers server.py, bootstrap.py or any script without a canonical name).
    for py_file in sorted(path.glob("*.py")) + sorted(path.glob("src/*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        has_main = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            for node in ast.walk(tree)
        )
        if has_main:
            try:
                rel = py_file.relative_to(path)
            except ValueError:
                continue
            entries.append({"path": str(rel.as_posix()), "type": "python_main"})

    # Deduplicate by path
    seen = set()
    unique = []
    for e in entries:
        if e["path"] not in seen:
            seen.add(e["path"])
            unique.append(e)

    return unique[:15]


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
    pyproject_path = path / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            import tomllib as _tl
            pdata = _tl.loads(pyproject_path.read_text(encoding="utf-8"))
            has_cfg = isinstance(pdata.get("tool", {}).get("pytest"), dict)
            deps_list: list[str] = []
            proj_tbl = pdata.get("project", {}) or {}
            deps_list.extend(_flat_deps(proj_tbl.get("dependencies", [])))
            for grp in (proj_tbl.get("optional-dependencies") or {}).values():
                deps_list.extend(_flat_deps(grp))
            for grp in (pdata.get("dependency-groups") or {}).values():
                deps_list.extend(_flat_deps(grp))
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
            import tomllib as _tl
            tdata = _tl.loads(toml_path.read_text(encoding="utf-8"))
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
        import tomllib as _tl
        if (path / "pyproject.toml").is_file():
            _pd = _tl.loads((path / "pyproject.toml").read_text(encoding="utf-8"))
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


_ENV_EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template", ".env.dist")


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


def _collect_nested_packages(path: Path, max_depth: int = 2, max_packages: int = 20) -> list[dict[str, Any]]:
    """Find package.json / pyproject.toml / pom.xml in subdirectories (monorepo support)."""
    found: list[dict[str, Any]] = []
    targets = {"package.json": _detect_node, "pyproject.toml": _detect_python,
               "pom.xml": _detect_java_maven, "Cargo.toml": _detect_cargo,
               "go.mod": _detect_go, "composer.json": _detect_php}

    def walk(p: Path, depth: int) -> None:
        if depth > max_depth or len(found) >= max_packages:
            return
        try:
            children = sorted(p.iterdir())
        except PermissionError:
            return
        for child in children:
            if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            for tname, scanner in targets.items():
                tf = child / tname
                if tf.is_file():
                    parsed = scanner(tf)
                    try:
                        rel = str(tf.relative_to(path).as_posix())
                    except ValueError:
                        rel = tf.name
                    found.append({"file": rel, "parsed": parsed})
                    break
            walk(child, depth + 1)

    walk(path, 1)
    return found


def get_structure(path: Path, max_depth: int = 3, skip_dirs: set[str] | None = None) -> list[dict[str, Any]]:
    """Produit une arborescence simplifiée."""
    if skip_dirs is None:
        skip_dirs = _SKIP_DIRS

    structure: list[dict[str, Any]] = []

    def walk(p: Path, depth: int = 0) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return
        for child in children:
            if child.name.startswith(".") and child.is_dir():
                continue
            if child.name in skip_dirs:
                continue
            try:
                rel = child.relative_to(path)
            except ValueError:
                continue

            if child.is_dir() and depth < max_depth:
                structure.append({
                    "name": child.name,
                    "path": str(rel.as_posix()),
                    "type": "directory",
                    "depth": depth,
                })
                walk(child, depth + 1)
            elif child.is_file() and depth <= 2:
                structure.append({
                    "name": child.name,
                    "path": str(rel.as_posix()),
                    "type": "file",
                    "depth": depth,
                })

    walk(path)
    return structure


_CREDENTIAL_IN_URL_RE = re.compile(r"//[^@/]+@")


def _sanitize_remote_url(url: str) -> str:
    """Mask credentials embedded in a remote URL (tokens, passwords).

    `https://user:token@github.com/x/y.git` -> `https://***@github.com/x/y.git`
    Query-string tokens are dropped. SSH URLs (`git@host:...`) are untouched.
    """
    sanitized = _CREDENTIAL_IN_URL_RE.sub("//***@", url)
    if "?" in sanitized:
        sanitized = sanitized.split("?", 1)[0] + "?<redacted>"
    return sanitized


def get_git_context(path: Path) -> dict[str, Any]:
    """Récupère le contexte Git du projet."""
    ctx: dict[str, Any] = {"has_git": False}
    if not (path / ".git").exists():
        return ctx

    ctx["has_git"] = True

    def _run_git(*args: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(path), *args],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    ctx["branch"] = _run_git("branch", "--show-current") or "unknown"
    ctx["commit_count"] = _run_git("rev-list", "--count", "HEAD") or "?"
    ctx["last_commit_msg"] = _run_git("log", "-1", "--format=%s") or ""

    remotes_raw = _run_git("remote", "-v")
    if remotes_raw:
        remotes = []
        seen_remotes: set[tuple[str, str]] = set()
        for line in remotes_raw.split("\n"):
            parts = line.split()
            if len(parts) >= 3:
                name, url = parts[0], parts[1]
                key = (name, url)
                if key in seen_remotes:
                    # `git remote -v` lists every remote twice (fetch + push).
                    continue
                seen_remotes.add(key)
                remotes.append({
                    "name": name,
                    "url": _sanitize_remote_url(url),
                    "type": parts[2],
                })
        ctx["remotes"] = remotes

    # Detect .gitignore patterns
    gitignore = path / ".gitignore"
    if gitignore.is_file():
        content = _safe_read(gitignore)
        if content:
            ctx["gitignore_patterns"] = [ln.strip() for ln in content.split("\n")
                                         if ln.strip() and not ln.startswith("#")][:30]

    return ctx


def _detect_misc(path: Path) -> dict[str, Any]:
    """Diverses métadonnées sur le projet."""
    misc: dict[str, Any] = {}

    # Root files
    misc["readme"] = any(
        (path / f).is_file() for f in ["README.md", "README.rst", "README.txt", "README"]
    )
    misc["license"] = any(
        (path / f).is_file() for f in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]
    )
    misc["changelog"] = any(
        (path / f).is_file() for f in ["CHANGELOG.md", "CHANGELOG", "HISTORY.md"]
    )
    misc["contributing"] = (path / "CONTRIBUTING.md").is_file()
    misc["code_of_conduct"] = (path / "CODE_OF_CONDUCT.md").is_file()

    # Config files at root
    config_files = []
    for f in path.iterdir():
        if f.is_file() and f.suffix in (".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf"):
            config_files.append(f.name)
    misc["config_files"] = config_files[:20]

    # Template engines
    template_exts = {".j2", ".jinja", ".hbs", ".handlebars", ".ejs", ".pug", ".haml", ".liquid", ".twig"}
    template_count = sum(
        1 for f in path.rglob("*") if f.is_file() and f.suffix in template_exts
        and not any(s in f.parts for s in _SKIP_DIRS)
    )
    misc["template_count"] = template_count

    # Issue #5: heuristic project summary — first real paragraph of the README.
    for readme_name in ("README.md", "readme.md", "README.rst"):
        readme_path = path / readme_name
        if not readme_path.is_file():
            continue
        # Security: never read a README that is a symlink escaping the repo —
        # an external file could leak secrets into the report / AGENTS.md.
        try:
            if readme_path.is_symlink() and not readme_path.resolve().is_relative_to(path):
                continue
        except OSError:
            continue
        try:
            text = readme_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            break
        para: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            # Headers, badges, tables and code fences always end the block.
            if not stripped or stripped.startswith(("#", "!", "|", "```")):
                if para:
                    break
                continue
            # At paragraph start, skip list/badge/link/HTML openers; but once a
            # paragraph has begun, keep a continuation line even if it starts
            # with '[', '-', '*' or '<'.
            if not para and stripped.startswith(("[", "-", "*", "<")):
                continue
            para.append(stripped)
            if sum(len(p) for p in para) > 240:
                break
        if para:
            summary = " ".join(para)[:300]
            if len(summary) >= 12:
                misc["readme_summary"] = summary
        break

    return misc


def _module_docstring(path: Path) -> str | None:
    """First docstring of a Python file, flattened to one line (issue #5)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    doc = ast.get_docstring(tree)
    if doc:
        text = " ".join(doc.split())[:300]
        if len(text) >= 12:
            return text
    return None


def _entry_docstring(path: Path) -> tuple[str | None, str | None]:
    """Best one-liner from a canonical entry point, then any root script."""
    canonical = ("server.py", "main.py", "app.py", "cli.py", "run.py",
                 "__main__.py", "bootstrap.py", "manage.py", "wsgi.py", "asgi.py")
    ordered = [path / n for n in canonical if (path / n).is_file()]
    ordered += [p for p in sorted(path.glob("*.py"))
                if p.name.startswith("_") is False and p not in ordered]
    for py in ordered:
        # Security: never read a script that is a symlink escaping the repo.
        try:
            if py.is_symlink() and not py.resolve().is_relative_to(path):
                continue
        except OSError:
            continue
        doc = _module_docstring(py)
        if doc:
            return doc, py.name
    return None, None


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Oracle — deep project scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python oracle_scan.py --path . --output .oracle/\n"
            "  python oracle_scan.py -p ~/project -o report.json -d 2\n"
            "  python oracle_scan.py -p . -o /dev/stdout   # print only\n"
        ),
    )
    parser.add_argument("--path", "-p", default=".", help="Project path (default: .)")
    parser.add_argument("--output", "-o", default=".oracle/scan-report.json",
                        help="Output: a directory (writes scan-report.json inside) or "
                             "an explicit JSON file path (default: .oracle/scan-report.json)")
    parser.add_argument("--depth", "-d", type=int, default=3,
                        help="Max tree depth (default: 3)")
    parser.add_argument("--skip-gitignore", action="store_true",
                        help="Do not skip .gitignore patterns")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logs")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Resolve paths ──
    root = Path(args.path).resolve(strict=False)
    if not root.exists():
        log.error("Path does not exist: %s", root)
        sys.exit(1)
    if root.is_file():
        root = root.parent

    log.info("Scanning: %s", root)
    start = time.time()

    # ── Phase 1: Languages ──
    log.debug("Detecting languages...")
    languages = detect_languages(root)

    # ── Phase 2: Build systems ──
    log.debug("Detecting build systems...")
    build_systems = detect_build_system(root)

    # ── Phase 2b: Nested manifests (monorepo support) ──
    nested_packages = _collect_nested_packages(root)
    for np in nested_packages:
        build_systems.append({
            "file": np["file"],
            "label": f"nested: {Path(np['file']).name}",
            "parsed": np["parsed"],
        })

    # ── Phase 3: Frameworks (list — a project usually has several) ──
    log.debug("Detecting frameworks...")
    scan_context = {"project_path": str(root), "build_systems": build_systems}
    frameworks = detect_frameworks(scan_context)
    framework = frameworks[0] if frameworks else None

    # ── Phase 4: Entry points ──
    log.debug("Finding entry points...")
    entry_points = detect_entry_points(root)

    # ── Phase 5: Conventions ──
    log.debug("Detecting conventions...")
    conventions = detect_conventions(root)

    # ── Phase 5b: Environment variables (names only, from example files) ──
    log.debug("Scanning env example files...")
    env_vars = detect_env_files(root)

    # ── Phase 6: Structure ──
    log.debug("Mapping project structure (depth=%d)...", args.depth)
    structure = get_structure(root, args.depth)

    # ── Phase 7: Git ──
    log.debug("Getting git context...")
    git_context = get_git_context(root)

    # ── Phase 8: Miscellaneous ──
    log.debug("Misc metadata...")
    misc = _detect_misc(root)

    # ── Counts ──
    file_count = sum(1 for _ in root.rglob("*") if _.is_file()
                     and not any(s in _.parts for s in _SKIP_DIRS))
    dir_count = sum(1 for _ in root.rglob("*") if _.is_dir()
                    and not any(s in _.parts for s in _SKIP_DIRS))

    # ── Assemble ──
    # Heuristic project summary (issue #5), in priority order:
    #   1. manifest description (package.json / pyproject.toml [project])
    #   2. first README paragraph
    #   3. module docstring of the main entry point (server.py, main.py, …)
    # The interview stays optional; `summary_source` records where it came from.
    summary = None
    summary_source = None
    for bs in build_systems:
        parsed = bs.get("parsed", {})
        if isinstance(parsed, dict) and parsed.get("description"):
            summary = parsed["description"]
            summary_source = f"manifest ({bs.get('file', 'unknown')})"
            break
    if not summary:
        summary = misc.get("readme_summary")
        if summary:
            summary_source = "README"
    if not summary:
        doc, doc_file = _entry_docstring(root)
        if doc:
            summary = doc
            summary_source = f"docstring ({doc_file})"

    report = {
        "tool": "project-oracle",
        "version": __version__,
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_name": root.name,
        # NOTE: no absolute path here — the report must be shareable.
        "summary": summary,
        "summary_source": summary_source,
        "file_count": file_count,
        "dir_count": dir_count,
        "languages": languages,
        "build_systems": build_systems,
        "framework": framework,
        "frameworks": frameworks,
        "entry_points": entry_points,
        "conventions": conventions,
        "env_vars": env_vars,
        "git": git_context,
        "misc": misc,
        "structure": structure,
    }

    elapsed = time.time() - start
    report["scan_duration_seconds"] = round(elapsed, 2)

    # ── Output ──
    # `--output` accepts a directory (`.oracle/` or `.oracle`) OR a file path.
    # A value ending in a path separator, an existing directory, or a name without
    # a `.json` suffix is treated as a directory and gets `scan-report.json` inside.
    output_path = Path(args.output)
    if str(output_path) in ("/dev/stdout", "-"):
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        looks_like_dir = (
            str(args.output).endswith(("/", "\\"))
            or output_path.is_dir()
            or output_path.suffix != ".json"
        )
        if looks_like_dir:
            output_path = output_path / "scan-report.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Report written: %s (%d bytes)", output_path, output_path.stat().st_size)

        # Keep the scan output out of the project's VCS (issue: dirty repo).
        # Only touches an EXISTING .gitignore, and only when missing the rule.
        try:
            resolved_out = output_path.resolve()
            if resolved_out.is_relative_to(root):
                gitignore = root / ".gitignore"
                if gitignore.is_file():
                    gi = gitignore.read_text(encoding="utf-8", errors="replace")
                    if not any(line.strip() in (".oracle", ".oracle/", "/.oracle/")
                               for line in gi.splitlines()):
                        sep = "" if gi.endswith("\n") or not gi else "\n"
                        gitignore.write_text(
                            gi + sep + ".oracle/\n", encoding="utf-8"
                        )
                        log.info("Added .oracle/ to %s", gitignore)
        except OSError as exc:
            log.debug("Could not update .gitignore: %s", exc)

    # ── Summary ──
    lang_str = ", ".join(f"{g['name']} ({g['ratio']}%)" for g in languages[:4]) or "none"
    log.info("Done in %.2fs", elapsed)
    log.info("Languages: %s", lang_str)
    log.info("Frameworks: %s", ", ".join(frameworks) if frameworks else "none detected")
    log.info("Files: %d, Dirs: %d | Entries: %d", file_count, dir_count, len(entry_points))


if __name__ == "__main__":
    main()
