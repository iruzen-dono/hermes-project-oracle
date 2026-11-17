# Contributing

This is a small tool with a narrow promise, so the rules are short — and mostly
about not widening it by accident.

## Setup

```bash
git clone https://github.com/iruzen-dono/project-oracle
cd project-oracle
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before you push — what CI runs

```bash
ruff check .
mypy scripts/ --ignore-missing-imports
pytest tests/ -q
python package_skill.py         # builds the skill zip and validates it
```

CI repeats these on Python 3.11, 3.12 and 3.13 across Ubuntu, macOS and Windows,
then builds both distributions, asserts the sdist carries no stale build
metadata, and **executes the composite action** against a drifted fixture. If it
is green locally and red there, it is a platform difference — say so in the PR
instead of retrying until it passes.

Required checks must pass before anything merges to `main`. There is no bypass.

## The non-negotiables

- **Zero runtime dependencies** — standard library only, in `scripts/`.
- **No network calls, no credential collection** — the tool reads repositories
  and nothing else. `.env` is never opened; `.env.example` is read for names only.
- **Cross-platform** — `pathlib` everywhere, no string path arithmetic.
- **A behaviour change ships with a test that would have failed before.**

## Adding a lint rule (the most likely contribution)

`oracle-lint` judges a rule by finding a checkable claim inside it. One lives in
`verify()` in `scripts/oracle_lint.py`, and **the order of the checks matters**:

1. **Cited script** — `_NPM_RUN` against the `scripts` of `package.json`.
2. **TypeScript strictness** — a `strict` claim against `tsconfig.json`.
3. **Cited file** — `_CONFIG_FILE` plus `_is_file_claim()`: any path or dotted
   name is a claim; a bare single-dot name only if it is in `_CONFIG_NAMES`.
4. **Declared tool** — `_TOOL_DEPS` against the manifests.

Then:

- Return `(VERIFIED, note)` or `(WRONG, note)` **with the evidence inside the
  note**. `does not exist (scripts: build, lint, start)` tells the reader what to
  do; `invalid` does not.
- Add a test in `tests/test_oracle_lint.py` for **both directions**: the claim
  that holds, and the one the repository disproves.
- If the rule can fire on advice rather than description ("add a `package.json`
  if you need Node"), skip it the way `_CREATION_VERBS` does.

**Do not make the linter guess.** A rule it cannot judge must be reported as
*not judged* — never scored as verified, never counted as noise. The whole value
of the tool is that a verdict is earned from the repository.

## Commits and pull requests

- Conventional commits: `fix(lint): ...`, `feat(check): ...`, `docs: ...`
- One logical change per commit. The body explains **why**, and what breaks if
  the change is reverted.
- A PR that changes behaviour says how it was verified: the command and its
  output, not "tested locally".
- Adding a dependency to `scripts/` will almost certainly be declined.

## Reporting

- **Bug** — use the issue template; include the version, the OS and the command.
- **Wrong verdict** — the worst kind of bug here. Include the rule verbatim, the
  verdict you got, and what the repository actually contains.
- **Security** — see [`SECURITY.md`](SECURITY.md). Never in a public issue.
