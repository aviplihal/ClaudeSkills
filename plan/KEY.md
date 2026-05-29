# KEY.md — Token-Saver Reference

> Read this first. It tells you **which section** of which file to load for the task at hand. Never load whole files when you only need a section.

> **Maintenance:** generated/updated during project planning (`/Users/bluelobster/skills/plan/PLANNING.md`). Any time a new section is added to `PROJECT.md`, a new top-level `.md` is introduced, or a recurring task emerges that isn't routed here, update this file in the same commit.

---

## Routing by Task

| Task | Read these sections |
|---|---|
| Starting a session | `/Users/bluelobster/skills/plan/CLAUDE.md §0`, `KEY.md`, `claude-progress.txt` (tail -10), `HANDOFF.md` if exists |
| Running `/handoff` | `/Users/bluelobster/skills/plan/HANDOFF_SKILL.md` (+ template at `/Users/bluelobster/skills/plan/HANDOFF.md`) |
| Spawning sub-agents / orchestrating worktrees | `/Users/bluelobster/skills/plan/CLAUDE.md §3`, `agent_status.json`, all `deps.json` |
| Planning a new project / major redesign | `/Users/bluelobster/skills/plan/PLANNING.md`, `PROJECT.md` (template at `/Users/bluelobster/skills/plan/PROJECT.md` if new) |
| Working on a feature | `/Users/bluelobster/skills/plan/CLAUDE.md §2` (delegate it — don't do it in main), `PROJECT.md §4` (the feature row), `PROJECT.md §3` (pipeline), the relevant worktree spec in `PROJECT.md §5` |
| Dispatching / scoping a sub-agent | `/Users/bluelobster/skills/plan/CLAUDE.md §2` (delegation doctrine + dispatch template) |
| Setting up a worktree | `/Users/bluelobster/skills/plan/CLAUDE.md §6`, `PROJECT.md §5` for that worktree |
| Running tests | `PROJECT.md §6` (feasibility) or `PROJECT.md §7` (e2e), `TEST_LEARNINGS.md` |
| Optimization loop / auto-research | `/Users/bluelobster/skills/plan/AUTORESEARCH.md`, `PROJECT.md §8` |
| Hitting a gotcha-shaped problem | `PROJECT.md §10` |

---

## Routing by File

| File | Purpose | When to read | When NOT to read |
|---|---|---|---|
| `/Users/bluelobster/skills/plan/CLAUDE.md` | Universal rules, sessions, commander, worktrees | Load only the section KEY.md routes you to | Never read end-to-end at session start |
| `/Users/bluelobster/skills/plan/PLANNING.md` | New-project / redesign procedure | Once at project start | Normal sessions |
| `/Users/bluelobster/skills/plan/HANDOFF_SKILL.md` | The `/handoff` procedure | Only when `/handoff` runs | Normal work |
| `PROJECT.md` | This project's overview, files, features, worktrees, tests | Load only the §s relevant to current task | Never load whole at session start |
| `KEY.md` | This file. Pointers only. | Every session start | — |
| `HANDOFF.md` | Live handoff from previous session | If present at session start | After resuming, delete or archive |
| `claude-progress.txt` | Append-only shared log | `tail -10` at session start | Never `cat` the whole file |
| `agent_status.json` | Live sub-agent state | Commander mode only | — |
| `<worktree>/deps.json` | Dependency map | Before spawning agent on that worktree | — |
| `/Users/bluelobster/skills/plan/AUTORESEARCH.md` | Auto-research playbook | Only when running an optimization loop | — |
| `TEST_LEARNINGS.md` | Condensed test lessons (sidecar; create on first e2e run) | Before re-running e2e tests | — |
| `handoffs/<branch>_<date>.md` | Archived handoffs | Only for forensic / history | At session start |
| `init.sh` | Project boot script (optional; if present, run it) | Step 6 of boot sequence | — |

---

## Section Index for PROJECT.md

| § | Topic |
|---|---|
| 1 | Overview |
| 2 | Folder structure |
| 3 | Pipeline / architecture |
| 4 | Features |
| 5 | Worktrees |
| 6 | Feasibility tests |
| 7 | End-to-end tests |
| 8 | Improvements / auto-research hook |
| 9 | Project-specific coding conventions |
| 10 | Gotchas |

## Section Index for CLAUDE.md

| § | Topic |
|---|---|
| 0 | Boot sequence |
| 1 | Core rules |
| 2 | Sessions & sub-agents |
| 3 | Commander mode |
| 4 | Handoff — `/Users/bluelobster/skills/plan/HANDOFF_SKILL.md` |
| 5 | Planning — `/Users/bluelobster/skills/plan/PLANNING.md` |
| 6 | Worktrees |
| 7 | Auto-research pointer |

---

## Rule

If you're about to `cat` a whole file at session start and that file isn't `KEY.md` itself or a short status file, **stop**. Re-check this table. Load the section, not the file.
