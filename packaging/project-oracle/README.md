# project-oracle

Short install name for **[hermes-project-oracle](https://pypi.org/project/hermes-project-oracle/)**.
This package ships no code: it depends on the real distribution, which provides
the five `oracle-*` commands.

```bash
pipx install project-oracle
```

Because the console scripts come from the dependency, every command is on your
`PATH` after install: `oracle-lint`, `oracle-check`, `oracle-scan`,
`oracle-generate`, `oracle-vault`.

## What you get

`oracle-lint` audits the context file your coding agent reads and tells you which
rules the repository backs, which it contradicts, and which are unfalsifiable
noise:

```
$ oracle-lint AGENTS.md

✗ L5    Run `npm run test` before opening a pull request.
         `npm run test` does not exist (scripts: build, lint, start)
✓ L6    Build with `npm run build`.
         `npm run build` exists in package.json
⚠ L7    Always write clean, maintainable code.
         no definition of 'clean' to verify against
```

`oracle-check` does the same job for CI: it fails the build when the context has
drifted from the repository.

See the [main repository](https://github.com/iruzen-dono/hermes-project-oracle)
for the full documentation.

MIT.
