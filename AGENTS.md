# AGENTS.md: rules for every coding agent on this repo

Before any task, read [docs/PLAN.md](docs/PLAN.md) (the build plan and the task board) and [DECISIONS.md](DECISIONS.md) (why things are the way they are).
If a request conflicts with a logged decision, ask the human. Never quietly undo a logged decision.

## The one rule

The deployed app must run the demo journey at every commit on `main`. Break things on a branch; merge only when the journey still runs. Without an API key or a database the agents fall back to rules, and that fallback must keep working.

## Decisions

- When a human makes or changes a call (scope, a cut, the demo story, data, a model, a dependency), log it in the same commit as the change: `scripts/decide "decision · why · who"`, or `/decide` in Claude Code. It appends `- HH:MM · decision · why · who` to DECISIONS.md.
- Log your own notable technical choices the same way, with your agent's name as the who: a new dependency, a workaround, something cut for time.
- No why, no line: ask for it.
- Never edit or delete a line. A reversal is a new line that names the time of the line it replaces.

## Tasks

- The workstreams table in docs/PLAN.md is the board. Check a task's owner and status before starting it, then claim it: name in Owner, status `doing`.
- Change the table on `main` in its own small commit, never on a feature branch (`Board: A2 doing, Alex`). Pull first; push right away so the others see it.
- PR open: `review` and its link. Merged: `done`. Cut: `cut`, plus a line in DECISIONS.md.
- New work gets a row with the next number in its workstream (A agents, B UI, C data and Aiven, D pitch).

## Before you hand back

- Every call made during your session is a line in DECISIONS.md.
- The board shows the truth for every task you touched.
- `git status` is clean, or you have said what is left and why.

## Hygiene

- This repo is public. Secrets live in `.env.local`, which is gitignored: never commit keys and never print their values.
- Short branches. One feature per commit.
