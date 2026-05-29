# HANDOFF.md — Template

> Written at the end of every session (or at 100k tokens). The next session reads only this file plus `KEY.md`. Zero information loss is the goal.

> Delete or archive after the next session has confirmed it has read it.

---

## Project

`<project name>` — `<one sentence on current state>`

## This Session

`[YYYY-MM-DD]` — `<branch>` — `<short summary, ≤ 3 lines>`

## Completed

- `<item 1>`
- `<item 2>`

## Next Steps (ordered, actionable)

1. `<exact next action — no re-reading required to start>`
2. `<next>`
3. `<next>`

## Key File Locations

| File | What it does | Path |
|---|---|---|
| `<file>` | `<role>` | `<abs path>` |

## Feature Status (relevant features only)

| ID | Description | Status |
|---|---|---|
| `<id>` | `<desc>` | passes / fails / wip |

## Dev Env (from scratch)

```
<commands to get running, copy-paste exact>
```

## Gotchas / Unresolved Dependencies

- `<gotcha 1>`
- `<unresolved dep>`

---

## Ready-to-Paste Resume Prompt

```
Continuing work on <project> at <abs path>.
Branch: <branch>
Last commit: <hash> <message>

Read HANDOFF.md first. Boot sequence per /Users/bluelobster/skills/plan/CLAUDE.md §0.

Immediate next action: <one-liner from Next Steps #1>

Run /handoff at 100k tokens.
```
