# Interview script: intent & pitfalls

A static scan detects the stack — it cannot detect *why* the project exists or
where the bodies are buried. This short interview fills that gap. Ask these five
questions, then save the answers as `intent.json`.

Ask them in order. Take short, concrete answers — not essays.

## 1. What does this project do, and for whom?

Establishes the **purpose**. A one-or-two-sentence answer is enough.

> "A music party app: guests join a room from their phone and vote on what
> plays next. Built for house parties."

## 2. What has broken or surprised you here before?

The **landmines**. These become `pitfalls`. Push for specifics — the best
answers name a symptom, a cause, and a fix.

> "Spotify tokens expired mid-party and the whole room stalled."

Follow up: *"What exactly was the symptom, the cause, and how did you fix it?"*

## 3. Which commands do you actually run day-to-day?

Catches the gap between `package.json` and reality — the script everyone runs
is rarely the one in the docs.

> "`npm run dev` — but you have to set `HOST_PASSWORD` first or it won't boot."

## 4. What must never be touched or overwritten?

Protects hand-tuned files from being clobbered by a future agent.

> "Don't rewrite `spotifyOAuth.js` — the token-refresh logic is fragile."

## 5. Which conventions are unwritten but real?

The rules a new contributor only learns the hard way.

> "All socket events go through `server/events.js` — never emit directly."

## Writing the answers

Map each answer into `intent.json`:

- Question 1 → `purpose` (a short paragraph)
- Question 2 → `pitfalls[]`, one entry per landmine, each with `area` + `note`
- Questions 3-5 → fold into `pitfalls[]` or the `purpose` as fits

The generator embeds `purpose` under **Project intent** and each pitfall under
**Known pitfalls**, so the agent reads the landmines before it touches code.