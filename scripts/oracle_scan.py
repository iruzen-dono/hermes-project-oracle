#!/usr/bin/env python3
"""
Hermes Project Oracle — Scan de projet.

Analyse en profondeur un projet logiciel et produit un rapport JSON structuré
contenant langages, framework, dépendances, conventions, points d'entrée,
et arborescence.

Usage:
    python oracle_scan.py --path /chemin/du/projet --output .oracle/
    python oracle_scan.py --path . --depth 2 --skip-gitignore

Cross-platform: Windows, Linux, macOS.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

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
    ".map", ".br", ".gz",
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

    # Dependencies (quick scan)
    deps = re.findall(r'(?:^|\n)(\w[\w.-]+)\s*[=~<>!]', content)
    if deps:
        result["deps_sample"] = deps[:30]

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


def _detect_node(package_json: Path | None) -> dict[str, Any]:
    """Analyse un projet Node.js via package.json."""
    result: dict[str, Any] = {"present": True}
    content = _safe_read(package_json) if package_json else None
    if not content:
        return result

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return result

    scripts = data.get("scripts", {})
    result["scripts"] = list(scripts.keys())[:15]
    all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    result["deps_sample"] = list(all_deps.keys())[:50]
    result["has_test_script"] = "test" in scripts

    # Framework detection
    fw_map = {
        "next": "Next.js", "react": "React", "vue": "Vue",
        "svelte": "Svelte", "astro": "Astro", "nuxt": "Nuxt",
        "express": "Express", "fastify": "Fastify", "nest": "NestJS",
        "remix": "Remix", "gatsby": "Gatsby", "solid": "SolidJS",
        "angular": "Angular",
    }
    for dep, fw in fw_map.items():
        if dep in all_deps:
            result["framework"] = fw
            break

    # Package manager detection
    for pm_file, pm_name in [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lockb", "bun"),
    ]:
        if (package_json.parent / pm_file).exists():
            result["pm"] = pm_name
            break

    # TypeScript
    if "typescript" in all_deps or (package_json.parent / "tsconfig.json").exists():
        result["typescript"] = True

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


def detect_framework(scan: dict[str, Any]) -> str | None:
    """Déduit le framework principal de toutes les configs parsées."""
    # Check explicit framework in parsed configs
    for key in ("parsed",):
        for bs in scan.get("build_systems", []):
            parsed = bs.get("parsed", {})
            if isinstance(parsed, dict) and parsed.get("framework"):
                return parsed["framework"]

    # Special files heuristic
    special: list[tuple[str, str]] = [
        ("manage.py", "Django"),
        ("app.py", "Flask"),
        ("main.py", ""),
        ("artisan", "Laravel"),
        ("bin/console", "Symfony"),
    ]
    root = Path(scan.get("project_path", "."))
    for fname, fw in special:
        if (root / fname).is_file():
            return fw if fw else None

    return None


def detect_entry_points(path: Path) -> list[dict[str, str]]:
    """Trouve les points d'entrée du projet (fichiers de démarrage)."""
    patterns = {
        "main.py": "application_entry",
        "app.py": "application_entry",
        "cli.py": "cli_entry",
        "run.py": "application_entry",
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
        "pytest": ["pytest.ini", "conftest.py", "pyproject.toml"],
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
            # Check content for pyproject/pom.xml/gradle
            if marker == "pyproject.toml":
                content = _safe_read(path / "pyproject.toml")
                if content and framework.lower() in content.lower():
                    detected_tests.append(framework)
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

    # ── Editor ──
    if (path / ".vscode").is_dir():
        conv["editor"] = "vscode"
    if (path / ".idea").is_dir():
        conv["editor"] = "intellij"
    if (path / ".cursor").is_dir():
        conv["editor"] = "cursor"

    # ── Monorepo detection ──
    conv["is_monorepo"] = _is_monorepo(path)

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
        for line in remotes_raw.split("\n"):
            parts = line.split()
            if len(parts) >= 3:
                remotes.append({"name": parts[0], "url": parts[1], "type": parts[2]})
        ctx["remotes"] = remotes

    # Detect .gitignore patterns
    gitignore = path / ".gitignore"
    if gitignore.is_file():
        content = _safe_read(gitignore)
        if content:
            ctx["gitignore_patterns"] = [l.strip() for l in content.split("\n")
                                         if l.strip() and not l.startswith("#")][:30]

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

    return misc


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hermes Project Oracle — Scan de projet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples:\n"
            "  python oracle_scan.py --path . --output .oracle/\n"
            "  python oracle_scan.py -p ~/projet -o rapport.json -d 2 --skip-gitignore\n"
            "  python oracle_scan.py -p . -o /dev/stdout  # juste stdout\n"
        ),
    )
    parser.add_argument("--path", "-p", default=".", help="Chemin du projet (défaut: .)")
    parser.add_argument("--output", "-o", default=".oracle/scan-report.json",
                        help="Fichier JSON de sortie (défaut: .oracle/scan-report.json)")
    parser.add_argument("--depth", "-d", type=int, default=3,
                        help="Profondeur max de l'arborescence (défaut: 3)")
    parser.add_argument("--skip-gitignore", action="store_true",
                        help="Ne pas ignorer les motifs .gitignore")
    parser.add_argument("--verbose", "-v", action="store_true", help="Logs détaillés")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Resolve paths ──
    root = Path(args.path).resolve(strict=False)
    if not root.exists():
        log.error("Le chemin n'existe pas: %s", root)
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

    # ── Phase 3: Framework ──
    log.debug("Detecting framework...")
    # Collect all parsed configs
    all_parsed = {}
    for bs in build_systems:
        if "parsed" in bs:
            all_parsed[bs["file"]] = bs["parsed"]
    # Flatten framework detection
    scan_context = {"project_path": str(root), "build_systems": build_systems}
    framework = detect_framework(scan_context)

    # ── Phase 4: Entry points ──
    log.debug("Finding entry points...")
    entry_points = detect_entry_points(root)

    # ── Phase 5: Conventions ──
    log.debug("Detecting conventions...")
    conventions = detect_conventions(root)

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
    report = {
        "tool": "hermes-project-oracle",
        "version": "1.0.0",
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_name": root.name,
        "project_path": str(root),
        "file_count": file_count,
        "dir_count": dir_count,
        "languages": languages,
        "build_systems": build_systems,
        "framework": framework,
        "entry_points": entry_points,
        "conventions": conventions,
        "git": git_context,
        "misc": misc,
        "structure": structure,
    }

    elapsed = time.time() - start
    report["scan_duration_seconds"] = round(elapsed, 2)

    # ── Output ──
    output_path = Path(args.output)
    if str(output_path) == "/dev/stdout":
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Report written: %s (%d bytes)", output_path, output_path.stat().st_size)

    # ── Summary ──
    lang_str = ", ".join(f"{l['name']} ({l['ratio']}%)" for l in languages[:4]) or "none"
    log.info("Done in %.2fs", elapsed)
    log.info("Languages: %s", lang_str)
    log.info("Framework: %s", framework or "none detected")
    log.info("Files: %d, Dirs: %d | Entries: %d", file_count, dir_count, len(entry_points))


if __name__ == "__main__":
    main()
