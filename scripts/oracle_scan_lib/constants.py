"""Constant tables and tiny pure helpers shared by the scanner.

Behaviour-neutral: these are the tables and pure functions that used to live
inline in ``oracle_scan.py``. Names drop the leading underscore; the scanner
imports them back under its original local names.
"""

from __future__ import annotations

import re

# Directories never worth scanning (deps, build output, VCS, caches,
# and our own output so a second run does not count itself).
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", ".env", "__pycache__",
    "target", "build", "dist", ".gradle", ".next", ".nuxt", ".output",
    ".vercel", ".cache", "vendor", "bundle", ".tox", ".eggs", "eggs",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
    ".stack-work", "result", "_build", "deps",
    "third_party", "third-party", "3rdparty",
    # Never scan our own output — a second run must not count itself.
    ".oracle",
}

# File extensions that never contain analysable source.
SKIP_EXTENSIONS = {
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

# extension -> (display name, key)
LANGUAGE_MAP: dict[str, tuple[str, str]] = {
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

NODE_FRAMEWORKS: list[tuple[str, str]] = [
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

NODE_TEST_PACKAGES = ("jest", "vitest", "mocha", "playwright", "@playwright/test",
                      "cypress", "ava", "tap")

# Names commonly used for example env files (never the real .env).
ENV_EXAMPLE_NAMES = (".env.example", ".env.sample", ".env.template", ".env.dist")

# Matches credentials embedded in a URL authority component (user:token@host).
CREDENTIAL_IN_URL_RE = re.compile(r"//[^@/]+@")


def sanitize_remote_url(url: str) -> str:
    """Mask credentials embedded in a remote URL (tokens, passwords).

    `https://user:token@github.com/x/y.git` -> `https://***@github.com/x/y.git`
    Query-string tokens are dropped. SSH URLs (`git@host:...`) are untouched.
    """
    sanitized = CREDENTIAL_IN_URL_RE.sub("//***@", url)
    if "?" in sanitized:
        sanitized = sanitized.split("?", 1)[0] + "?<redacted>"
    return sanitized
