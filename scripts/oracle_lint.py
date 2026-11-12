#!/usr/bin/env python3
"""Project Oracle - context file linter.

Generating an ``AGENTS.md`` is easy. Writing one that helps rather than hurts
is not. Research from ETH Zurich (Gloaguen, Muendler, Mueller, Raychev, Vechev,
*ICLR 2026 Workshop on Memory for LLM-Based Agentic Systems*) found that
context files produce **no improvement in task success** while raising
inference cost by **over 20 %** - because unnecessary requirements make tasks
harder.

``oracle-lint`` reads an existing context file - yours, or one an agent
generated for you - and sorts every rule into four buckets:

    verified    the rule names something the repository confirms
    wrong       the rule contradicts the repository
    noise       unfalsifiable advice no agent can act on
    unverified  could not be judged either way (not counted against you)

Zero dependencies.

Usage:
    oracle-lint AGENTS.md
    oracle-lint CLAUDE.md --path . --json
    oracle-lint AGENTS.md --max-noise 30

Exit codes:
    0  no contradictions and noise within budget
    1  contradictions found, or noise over the budget
    2  usage error (missing file, bad path)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from version import __version__
except ImportError:  # scripts/ not on sys.path - visible, not silently wrong
    __version__ = "unknown"


# ── Model ─────────────────────────────────────────────────────────────────

VERIFIED = "verified"
WRONG = "wrong"
NOISE = "noise"
UNVERIFIED = "unverified"

VERDICTS = (VERIFIED, WRONG, NOISE, UNVERIFIED)


@dataclass
class Rule:
    """One instruction extracted from a context file."""

    line: int
    text: str
    verdict: str = UNVERIFIED
    note: str = ""


@dataclass
class LintResult:
    rules: list[Rule] = field(default_factory=list)

    def count(self, verdict: str) -> int:
        return sum(1 for r in self.rules if r.verdict == verdict)

    @property
    def judged(self) -> int:
        """Rules we could actually judge - unverified ones are excluded."""
        return sum(1 for r in self.rules if r.verdict != UNVERIFIED)

    @property
    def noise_ratio(self) -> float:
        if not self.judged:
            return 0.0
        return self.count(NOISE) / self.judged

    @property
    def useful_ratio(self) -> float:
        if not self.judged:
            return 0.0
        return self.count(VERIFIED) / self.judged


# ── Extraction ────────────────────────────────────────────────────────────

_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s")
_FENCE = re.compile(r"^\s*(?:```|~~~)")

# Lines that look like an instruction but are actually structure or commands.
_SKIP_STARTS = ("<!--", "---", "|", ">")


def extract_rules(text: str) -> list[Rule]:
    """Pull instruction lines out of a markdown context file.

    Bullets are the norm, but plenty of files write plain imperative
    paragraphs. Both are collected; headings, tables, code fences and HTML
    comments are skipped because they are structure, not instruction.
    """
    rules: list[Rule] = []
    in_fence = False

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()

        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        if _HEADING.match(line) or line.lstrip().startswith(_SKIP_STARTS):
            continue

        bullet = _BULLET.match(line)
        if bullet:
            rules.append(Rule(number, bullet.group(1).strip()))
            continue

        # A bare paragraph is only treated as an instruction if it opens with
        # an imperative or a modal - otherwise it is prose describing the repo.
        stripped = line.strip()
        if len(stripped) > 12 and _starts_imperatively(stripped):
            rules.append(Rule(number, stripped))

    return rules


_IMPERATIVE_START = re.compile(
    r"^(?:always|never|do not|don't|avoid|use|prefer|run|check|verify|make sure|"
    r"ensure|keep|write|follow|add|update|read|inspect|ask|treat|consider|"
    r"remember|never|must|should)\b",
    re.IGNORECASE,
)


def _starts_imperatively(text: str) -> bool:
    return bool(_IMPERATIVE_START.match(text))


# ── Noise detection ───────────────────────────────────────────────────────

# Advice no agent can act on: there is nothing to check, so it is pure token
# cost. These are the phrases the ETH study means by "unnecessary
# requirements" - they make the task harder by adding surface area.
_NOISE_PATTERNS = (
    (re.compile(r"\b(clean|maintainable|readable|elegant|robust|high[- ]quality)\s+"
                r"(code|solution|implementation|design)\b", re.IGNORECASE),
     "no definition of 'clean' to verify against"),
    (re.compile(r"\bbest practices?\b", re.IGNORECASE),
     "'best practices' names nothing specific"),
    (re.compile(r"\bbe\s+(careful|thorough|diligent|mindful|thoughtful)\b", re.IGNORECASE),
     "a mood, not a checkable rule"),
    (re.compile(r"\bthink\s+(before|carefully|through)\b", re.IGNORECASE),
     "a mood, not a checkable rule"),
    (re.compile(r"\bpay attention to\b", re.IGNORECASE),
     "a mood, not a checkable rule"),
    (re.compile(r"\bkeep\s+(it|things)\s+(simple|clean|tidy)\b", re.IGNORECASE),
     "no definition of 'simple' to verify against"),
    (re.compile(r"\bfollow\s+(good|standard|common)\s+(practices|conventions)\b", re.IGNORECASE),
     "names no convention file"),
    (re.compile(r"\balways\s+(test|verify|check)\s+your\s+(changes|work|code)\b", re.IGNORECASE),
     "restates the job of a coding agent"),
    (re.compile(r"\bmake sure\s+(everything|it|things)\s+"
                r"(works?|is\s+(correct|right|fine|ok|good))\b", re.IGNORECASE),
     "restates the job of a coding agent"),
    (re.compile(r"\bwrite\s+(good|quality|better)\s+code\b", re.IGNORECASE),
     "no definition of 'good' to verify against"),
    (re.compile(r"\bdon'?t\s+(break|mess\s+up)\b", re.IGNORECASE),
     "restates the job of a coding agent"),
)

# A rule that mentions one of these is anchored to something concrete, so it
# is not noise even if it also uses a vague word.
_ANCHORS = (
    re.compile(r"`[^`]+`"),                                  # inline code
    re.compile(r"\b[\w./-]+\.(?:py|js|jsx|ts|tsx|json|toml|ya?ml|md|cfg|ini|env|lock)\b"),
    # "make" alone would match "Make sure ..." - require the build tool's
    # actual shape, and let Makefile be named explicitly.
    re.compile(r"\b(?:npm|pnpm|yarn|bun|pip|uv|poetry|cargo|go|composer|"
               r"docker|php|python|node|deno)\b", re.IGNORECASE),
    re.compile(r"\bMakefile\b"),
    # `make build` is an anchor; `make sure` is not. Exclude the filler words
    # that follow "make" in ordinary English.
    re.compile(
        r"\bmake\s+(?!sure\b|certain\b|it\b|the\b|a\b|an\b|that\b|this\b|them\b|"
        r"sure\s+to\b|up\b|out\b)[a-zA-Z][\w-]*"
    ),
    re.compile(r"\b(?:pytest|vitest|jest|mocha|unittest|ruff|eslint|prettier|black|"
               r"mypy|tsc|flake8|pylint|biome|turbo|nx)\b", re.IGNORECASE),
    re.compile(r"\b(?:src|tests?|scripts?|docs?|lib|app|packages?|config)/"),
    re.compile(r"\b(?:conventional[ -]commits|semantic-release|keepachangelog)\b", re.IGNORECASE),
)


def _is_anchored(text: str) -> bool:
    """Whether the rule points at something concrete in the repository."""
    return any(pattern.search(text) for pattern in _ANCHORS)


def _noise_reason(text: str) -> str | None:
    """Return why a rule is noise, or None if it is not noise."""
    if _is_anchored(text):
        return None
    for pattern, reason in _NOISE_PATTERNS:
        if pattern.search(text):
            return reason
    return None


# ── Verification against the repository ───────────────────────────────────

_NPM_RUN = re.compile(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?([a-zA-Z0-9:_-]+)")
_NOT_SCRIPTS = {"install", "add", "remove", "update", "ci", "init", "create", "run", "exec"}

_TOOL_DEPS = {
    "pytest": ("pytest", "pyproject.toml"),
    "vitest": ("vitest", "package.json"),
    "jest": ("jest", "package.json"),
    "mocha": ("mocha", "package.json"),
    "ruff": ("ruff", "pyproject.toml"),
    "black": ("black", "pyproject.toml"),
    "mypy": ("mypy", "pyproject.toml"),
    "eslint": ("eslint", "package.json"),
    "prettier": ("prettier", "package.json"),
    "typescript": ("typescript", "package.json"),
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _node_scripts(root: Path) -> set[str] | None:
    data = _read_json(root / "package.json")
    if data is None:
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return set()
    return {k for k in scripts if isinstance(k, str)}


def _manifest_text(root: Path) -> str:
    """Concatenated manifest contents, used for tool-presence checks."""
    parts: list[str] = []
    for name in ("package.json", "pyproject.toml", "requirements.txt",
                 "composer.json", "Cargo.toml", "go.mod"):
        try:
            parts.append((root / name).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def _check_ts_strict(root: Path, text: str) -> tuple[str, str] | None:
    """Verify a TypeScript strict-mode claim against tsconfig.json."""
    if "strict" not in text.lower() or "typescript" not in text.lower():
        return None
    config = _read_json(root / "tsconfig.json")
    if config is None:
        return (WRONG, "tsconfig.json not found or unreadable")
    options = config.get("compilerOptions")
    strict = options.get("strict") if isinstance(options, dict) else None
    if strict is True:
        return (VERIFIED, "tsconfig.json sets compilerOptions.strict = true")
    return (WRONG, f"tsconfig.json does not enable strict (found {strict!r})")


def verify(text: str, root: Path, scripts: set[str] | None, manifests: str) -> tuple[str, str] | None:
    """Try to judge a rule against the repository.

    Returns ``(verdict, note)`` when the rule made a claim we can check, or
    None when it made none.
    """
    # 1. A cited script that does not exist is a contradiction, not noise.
    if scripts is not None:
        for match in _NPM_RUN.finditer(text):
            name = match.group(1)
            if name in _NOT_SCRIPTS or name.startswith("-"):
                continue
            if name not in scripts:
                have = ", ".join(sorted(scripts)) or "none"
                return (WRONG, f"`{match.group(0)}` does not exist (scripts: {have})")
            return (VERIFIED, f"`{match.group(0)}` exists in package.json")

    # 2. TypeScript strict mode.
    ts = _check_ts_strict(root, text)
    if ts is not None:
        return ts

    # 3. A named tool must appear in the manifests.
    lowered = text.lower()
    for tool, (_needle, manifest_name) in _TOOL_DEPS.items():
        if not re.search(rf"\b{re.escape(tool)}\b", lowered):
            continue
        if tool in manifests.lower():
            return (VERIFIED, f"{tool} is declared in {manifest_name}")
        return (WRONG, f"{tool} is not declared in any manifest")

    # 4. A cited config file that does not exist.
    for match in re.finditer(r"\b([\w./-]+\.(?:toml|ya?ml|json|cfg|ini))\b", text):
        candidate = match.group(1)
        mentions_path = "/" in candidate or candidate.count(".") > 1
        if mentions_path and not (root / candidate).exists():
            return (WRONG, f"{candidate} does not exist")

    return None


# ── Runner ────────────────────────────────────────────────────────────────


def lint(path: Path, root: Path) -> LintResult:
    """Extract, classify and score every rule in a context file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    result = LintResult(extract_rules(text))

    scripts = _node_scripts(root)
    manifests = _manifest_text(root)

    for rule in result.rules:
        judged = verify(rule.text, root, scripts, manifests)
        if judged is not None:
            rule.verdict, rule.note = judged
            continue
        reason = _noise_reason(rule.text)
        if reason is not None:
            rule.verdict, rule.note = NOISE, reason
            continue
        rule.verdict = UNVERIFIED

    return result


# ── Reporting ─────────────────────────────────────────────────────────────


def _supports_unicode() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "✓✗⚠·→".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _sym() -> dict[str, str]:
    if _supports_unicode():
        return {
            "ok": "✓", "wrong": "✗", "noise": "⚠", "neutral": "·",
            "arrow": "→", "sep": "·",
        }
    return {
        "ok": "OK", "wrong": "X", "noise": "!", "neutral": "-",
        "arrow": "->", "sep": "|",
    }


_MARK = {VERIFIED: "ok", WRONG: "wrong", NOISE: "noise", UNVERIFIED: "neutral"}

_LABEL = {
    VERIFIED: "verified",
    WRONG: "contradicts the repository",
    NOISE: "noise",
    UNVERIFIED: "not judged",
}


def print_human(result: LintResult, path: Path, show_all: bool = False) -> None:
    sym = _sym()
    print(f"oracle-lint {__version__} - {path}")
    print()

    if not result.rules:
        print(f"{sym['neutral']} no rules found (is this a context file?)")
        return

    # Lines that describe the repo (stack, entry points, git stats) are
    # extracted as candidates but cannot be judged. Printing 26 of them buries
    # the three that matter, so they are hidden unless --all is passed.
    shown = result.rules if show_all else [r for r in result.rules if r.verdict != UNVERIFIED]

    if not shown:
        print(f"{sym['neutral']} no rule in this file could be judged")
    for rule in shown:
        mark = sym[_MARK[rule.verdict]]
        print(f"{mark} L{rule.line:<4} {rule.text[:88]}")
        if rule.note:
            print(f"         {rule.note}")

    print()
    total = len(result.rules)
    print(
        f"{result.count(VERIFIED)} verified {sym['sep']} "
        f"{result.count(WRONG)} wrong {sym['sep']} "
        f"{result.count(NOISE)} noise {sym['sep']} "
        f"{result.count(UNVERIFIED)} not judged"
    )
    if result.judged:
        pct = round(result.useful_ratio * 100)
        print(f"Score: {result.count(VERIFIED)} of {result.judged} judged rules are useful ({pct}%)")
    else:
        print(f"Score: nothing to judge - {total} rule(s) could not be checked")
    if not show_all and result.count(UNVERIFIED):
        print(f"({result.count(UNVERIFIED)} line(s) could not be judged - pass --all to list them)")
    if result.count(NOISE):
        print("Every noise rule is inference cost with no instruction in it. Delete them.")


def print_json(result: LintResult, path: Path) -> None:
    payload = {
        "tool": "project-oracle-lint",
        "version": __version__,
        "file": str(path),
        "total": len(result.rules),
        "verified": result.count(VERIFIED),
        "wrong": result.count(WRONG),
        "noise": result.count(NOISE),
        "unverified": result.count(UNVERIFIED),
        "noise_ratio": round(result.noise_ratio, 4),
        "useful_ratio": round(result.useful_ratio, 4),
        "rules": [
            {"line": r.line, "verdict": r.verdict, "text": r.text, "note": r.note}
            for r in result.rules
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Project Oracle - lint a context file for noise and contradictions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  oracle-lint AGENTS.md\n"
            "  oracle-lint CLAUDE.md --path . --json\n"
            "  oracle-lint AGENTS.md --max-noise 20 --strict\n"
        ),
    )
    parser.add_argument("file", help="Context file to lint (AGENTS.md, CLAUDE.md, ...)")
    parser.add_argument("--path", "-p", default=".",
                        help="Repository the rules are checked against (default: .)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--max-noise", type=int, default=50,
                        help="Noise budget in percent of judged rules (default: 50)")
    parser.add_argument("--strict", action="store_true",
                        help="Any noise at all is a failure")
    parser.add_argument("--all", action="store_true",
                        help="Also list rules that could not be judged")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_absolute():
        path = Path(args.path).resolve(strict=False) / path
    if not path.is_file():
        print(f"error: not a file: {path}", file=sys.stderr)
        sys.exit(2)

    root = Path(args.path).resolve(strict=False)
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        sys.exit(2)

    try:
        result = lint(path, root)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print_json(result, path)
    else:
        print_human(result, path, show_all=args.all)

    budget = 0.0 if args.strict else args.max_noise / 100
    failed = result.count(WRONG) > 0 or result.noise_ratio > budget
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
