# Security

## What this tool touches

Project Oracle reads a repository in order to describe it. There is no server, no
telemetry, no network call, and no dependency beyond the Python standard library.

- It reads manifests, source files and `.env.example` — **variable names only**.
- It never opens `.env`, `.env.local`, or any file it treats as a secret holder.
- Git remotes are credential-masked (`https://***@host/...`) before reaching a
  report.
- `scan-report.json` carries no absolute paths, so it is safe to attach to an issue.

## The promise, precisely

If you find a path where a secret **value** can reach `scan-report.json`, a
generated context file, or the console, that is a vulnerability — even if nothing
ever leaves your machine. Same for a way to make the scanner read outside the
target repository.

## Reporting

Do not open a public issue. Use **Security -> Report a vulnerability** on this
repository, which opens a private advisory.

Include the command, the smallest repository shape that triggers it, and the
leaked fragment (redacted). You will get an answer within a few days. A fix ships
as a patch release, with credit unless you prefer otherwise.

## Supported versions

The latest patch of the current major version receives fixes.
