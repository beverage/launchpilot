---
name: decide
description: Log a decision in DECISIONS.md at the moment it is made, as "HH:MM · decision · why · who". Use whenever a human makes or changes a call (scope, a cut, the demo story, data, a model, a dependency), or when you make a notable technical choice.
argument-hint: "decision · why · who"
---

# decide

1. If the arguments lack a why or a who, ask for them first. A decision without a why is the one that gets re-argued at 14:00.
2. Read DECISIONS.md for an earlier line this one changes or reverses. If there is one, say so in the new line ("replaces 11:20") and tell the user which line it was.
3. Run `scripts/decide "$ARGUMENTS"` from the repo root.
4. In the same commit, bring along what the call changes: the workstreams table in docs/PLAN.md for a cut or new task (a cut task's status becomes `cut`), README.md if it changes what the product does. A settled open question comes off the Open decisions list in docs/PLAN.md.
