"""Ecosystem detectors: manifests, build systems, frameworks, entry points.

Functions moved verbatim out of oracle_scan.py — behaviour is unchanged.
"""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from oracle_scan_lib.constants import (
    LANGUAGE_MAP as _LANGUAGE_MAP,
    NODE_FRAMEWORKS as _NODE_FRAMEWORKS,
    NODE_TEST_PACKAGES as _NODE_TEST_PACKAGES,
    SKIP_EXTENSIONS as _SKIP_EXTENSIONS,
)
from oracle_scan_lib.io import load_toml as _load_toml
from oracle_scan_lib.io import read_maybe_rooted as _read_maybe_rooted


def _find_config(path: Path, *names: str) -> Path | None:
    """Find the first existing config file among ``names``."""
    for name in names:
        p = path / name
        if p.is_file():
            return p
    return None


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
            name = re.split(r"[\s\[<>=!~;#@]", item.strip(), maxsplit=1)[0].strip()
            if name:
                out.append(name)
    return out


def _dedupe(items: list[str]) -> list[str]:
    """Stable dedupe preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _detect_python(pyproject: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a Python project via pyproject.toml."""
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(pyproject, root)
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


def _detect_node(package_json: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a Node.js project via package.json (multiple frameworks, full scripts)."""
    result: dict[str, Any] = {"present": True}
    if package_json is None:
        return result
    content = _read_maybe_rooted(package_json, root)
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
    result["frameworks"] = _dedupe(frameworks)
    if result["frameworks"]:
        result["framework"] = result["frameworks"][0]

    # Test evidence from deps + test script command.
    test_tools = [pkg for pkg in _NODE_TEST_PACKAGES if pkg in all_deps]
    if test_tools:
        result["test_tools"] = test_tools
    if isinstance(scripts, dict) and "test" in scripts:
        result["has_test_script"] = True
        result["test_command"] = str(scripts["test"])[:200]
    # Built-in runner: `node --test` needs no dependency (audit #2).
    # A test script invoking it (e.g. `node --test tests/*.mjs`) is real
    # evidence of a suite even with zero test deps installed.
    if isinstance(scripts, dict):
        for _cmd in scripts.values():
            if re.search(r"(^|[\s&|;])node\s+--test\b", str(_cmd)):
                result["has_test_script"] = True
                if "test_command" not in result:
                    result["test_command"] = str(_cmd)[:200]
                if "node --test" not in test_tools:
                    test_tools = [*test_tools, "node --test"]
                    result["test_tools"] = test_tools
                break

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


def _detect_java_maven(pom: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a Maven project."""
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(pom, root)
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


def _detect_gradle(build_file: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a Gradle project."""
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(build_file, root)
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


def _detect_cargo(cargo_toml: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a Rust project via Cargo.toml."""
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(cargo_toml, root)
    if not content:
        return result

    name = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if name:
        result["crate_name"] = name.group(1)

    desc = re.search(r'^description\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if desc:
        result["description"] = desc.group(1)[:200]

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


def _detect_go(go_mod: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a Go project via go.mod."""
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(go_mod, root)
    if not content:
        return result

    module = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
    if module:
        result["module"] = module.group(1)

    go_ver = re.search(r"^go\s+([\d.]+)", content, re.MULTILINE)
    if go_ver:
        result["go_version"] = go_ver.group(1)

    return result


def _detect_php(composer: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Analyse a PHP project via composer.json."""
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(composer, root)
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


def _detect_make(makefile: Path | None, root: Path | None = None) -> dict[str, Any]:
    """Extract runnable targets from a Makefile (audit #10).

    A Makefile listed as bare "Make" gives the agent nothing to run.
    Targets are the `name:` lines at column 0 (`.PHONY:` and variable
    assignments excluded); the first 15 are kept as `scripts`-like entries
    so the generator renders `make <target>`.
    """
    result: dict[str, Any] = {"present": True}
    content = _read_maybe_rooted(makefile, root)
    if not content:
        return result
    targets: dict[str, str] = {}
    for line in content.splitlines():
        if not line or line[0] in (" ", "\t", ".", "#", "$", "="):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?!:=|:?=)", line)
        if m:
            name = m.group(1)
            if name.lower() not in ("phony",) and name not in targets:
                targets[name] = f"make {name}"
                if len(targets) >= 15:
                    break
    if targets:
        result["scripts"] = targets
        result["pm"] = "make"
    return result


def detect_build_system(path: Path) -> list[dict[str, Any]]:
    """Detect build systems and config files."""
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
        ("Makefile", "Make", _detect_make),
        ("mix.exs", "Elixir/Mix", None),
        ("project.clj", "Clojure/Leiningen", None),
        ("stack.yaml", "Haskell/Stack", None),
        ("*.sln", ".NET Solution", None),
        ("pubspec.yaml", "Dart/Flutter", None),
    ]

    results: list[dict[str, Any]] = []
    for name, label, scanner in config_scanners:
        if "*" in name:
            # Glob pattern
            matches = list(path.glob(name))
            if matches:
                results.append({"file": name, "label": label, "files": len(matches)})
                continue
        f = path / name
        if f.is_file():
            entry: dict[str, Any] = {"file": f.name, "label": label}
            if scanner:
                parsed = scanner(f, path)  # pass project root for symlink guard
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
    return _dedupe(fws)


def detect_entry_points(path: Path) -> list[dict[str, str]]:
    """Find the project's entry points (startup files)."""
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
    # Audit #10: never classify a config/settings module as an entry point —
    # `backend/src/config/index.js` (or conf/, settings/, config.py) is
    # imported, never executed directly.
    _CONFIG_PARTS = {"config", "conf", "settings", "__tests__", "tests",
                     "test", "__mocks__", "mocks", "fixtures"}
    for pat, etype in patterns.items():
        for found in path.rglob(pat):
            if found.is_file() and not any(
                skip in found.parts for skip in ["node_modules", ".git", ".venv", "venv", "__pycache__"]
            ):
                try:
                    rel = found.relative_to(path)
                except ValueError:
                    continue
                if any(part.lower() in _CONFIG_PARTS for part in rel.parts[:-1]):
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
    pdata = _load_toml(_read_maybe_rooted(path / "pyproject.toml", path))
    if pdata:
        scripts_tbl = ((pdata.get("project") or {}).get("scripts") or {})
        for cname, target in list(scripts_tbl.items())[:10]:
            entries.append({
                "path": f"pyproject.toml:{cname}",
                "type": f"console_script -> {target}",
            })

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


def detect_languages(path: Path) -> list[dict[str, Any]]:
    """Count files per extension and return the detected languages."""
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
        for lang_name, lang_key in _LANGUAGE_MAP.values():
            if lang_key == key and lang_name:
                display = lang_name
                break
        result.append({
            "key": key,
            "name": display,
            "files": lang_scores[key],
            "ratio": round(lang_scores[key] / total * 100, 1),
        })
    return result
