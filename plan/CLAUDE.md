# CLAUDE.md — Universal Project Instructions

> Universal across projects. Project specifics live in `PROJECT.md`. Read `KEY.md` first — it routes you to the section you need. Don't read this file end-to-end.

## 0. Boot (every session)

1. `cat KEY.md`. **No `KEY.md` → project unplanned → load `/Users/bluelobster/skills/plan/PLANNING.md` first.**
2. Read only the `PROJECT.md` sections `KEY.md` flags.
3. `tail -10 claude-progress.txt`.
4. `cat HANDOFF.md` if present.
5. `git log --oneline -10`.
6. Run `init.sh` if present; smoke-test before touching code.

Never `cat` whole files (`PROJECT.md`, `claude-progress.txt`, feature list) at start. That's what `KEY.md` prevents.

## 1. Core Rules

- One feature at a time; repo stays mergeable.
- Test as a human user — never mark done on code review alone.
- Async everywhere. Comment every file (top) and function.
- No dead/commented-out code, no `_old` files.
- Secrets in `.env` only. Parameterized queries only.
- Condense ruthlessly when editing any `.md`.
- Track recurring mistakes; once they stack, update the relevant `.md` to prevent recurrence.

## 2. Sessions & Sub-Agents

**Main session is an orchestrator, not a worker.** It plans, dispatches, integrates. All real work — reading files to understand them, implementing, debugging, search, test runs — goes to sub-agents. Main reads only `KEY.md`, short status files, and the condensed summaries agents return. Never `cat` a big file into main "to look" — send a scout.

**Token rules:** scope each task to ~50k. Sub-agent updates its working `.md` at 50k, forces `/handoff` at 60k (workers). Main + worktree-leads handoff at 100k (orchestrators).

**Scout first:** for any large/uncertain task, dispatch a cheap scout to verify path, scope, assumptions; use its note to write the real task prompt — without loading files into main.

**Sub-agents don't read `CLAUDE.md`** — put rules inline. Dispatch template:
```
Task: <one scoped unit>
Location: <files/dir>
Context: <issues from feature notes, relevant PROJECT.md facts>
Done looks like: <observable, human-verifiable>
Rules: one change, mergeable; async + comments; test as a human;
       parameterized queries; secrets in .env;
       update working .md at 50k; RUN /handoff AT 60K.
Completion message: <changed / passed / left / gotchas>, condensed.
```

**Loop:** plan → scout if needed → dispatch one job → integrate condensed return → repeat. ~100 tasks before main hits 100k, then `/handoff` (§4).

**Worktrees:** write to the **main** project's `claude-progress.txt` (absolute path), never the worktree's relative one — invisible until merged.

## 3. Commander Mode

Orchestrating parallel sub-agents across worktrees. You read state, decide, spawn, unblock — you don't write code.

State files: `agent_status.json`, `<worktree>/deps.json`, `claude-progress.txt`, `<worktree>/HANDOFF.md`. Per-worktree feature status lives in the main `PROJECT.md §4` table.

Startup:
```bash
cat agent_status.json
tail -20 claude-progress.txt
for d in .claude/worktrees/*/; do echo "=== $(basename $d) ==="; cat "$d/deps.json"; done
find . -name HANDOFF.md
git worktree list
```

Rules: never start a blocked track (check `deps.json`); handoffs before new work; one agent per worktree; merge in `deps.json` order, smoke-test first; read before acting.

**Spawn a worktree-lead** (runs its own track, handoffs at 100k, doesn't read `CLAUDE.md`):
```
Continuing <project> at <cwd>, branch <branch>. Read HANDOFF.md first.
Last commit: <hash> <msg>. Boot from HANDOFF.md + KEY.md only.
Rules: one feature at a time, mergeable, test as a human, async + comments,
       parameterized queries, secrets in .env.
Delegate real work to your own sub-agents (~50k scope, handoff at 60k).
Resume from: 1.<task> 2.<task>
RUN /handoff AT 100K TOKENS.
```

**After a sub-agent ends:** `find . -name HANDOFF.md` → archive `cp <path>/HANDOFF.md handoffs/<branch>_<date>.md` → set `agent_status.json` `handoff_pending`, bump `context_transfers` → spawn fresh from archive → on confirm, delete original → set `running`.

**Unblock:** run the blocked track's `check_command`; if pass, flip its dep `waiting`→`clear`; log to `claude-progress.txt`; spawn the blocked agent.

## 4. Handoff (`/handoff`)

Manual, or auto at 100k. **Load `/Users/bluelobster/skills/plan/HANDOFF_SKILL.md` and follow it.**

## 5. Planning a New Project

Fresh project or major redesign. **Load `/Users/bluelobster/skills/plan/PLANNING.md` and follow it.** Once at project start.

## 6. Worktrees

```bash
claude -w <name> "<task>"   # create isolated branch + dir, dispatch task
claude -w <name>            # resume existing worktree
git worktree list           # audit all active worktrees
git worktree remove .claude/worktrees/<name> && git branch -d wt/<name>   # cleanup
```
Branch convention: `wt/<name>` (the `deps.json` schema and commander references depend on this prefix).
Per-worktree files: `deps.json`, optional `HANDOFF.md`.

**Merging:** audit with `git worktree list`. Merge only passing branches: `git checkout main && git merge --no-ff wt/<name>`. Smoke-test after each merge; fix before the next. Append summary to `claude-progress.txt`. Never merge a broken branch — flag to the user.

`deps.json`:
```json
{ "branch": "wt/<name>",
  "depends_on": [ { "branch": "wt/<other>", "status": "waiting|clear",
    "check_command": "git log main --oneline | grep -q <marker>",
    "if_blocked": "skip <id>, work <id>" } ],
  "blocks": ["wt/<downstream>"] }
```
Never guess a dependency's values — leave a marker, note the blocker in `claude-progress.txt`.

## 7. Auto-Research

Measurable AI/ML pipeline to optimize in a loop — load `/Users/bluelobster/skills/plan/AUTORESEARCH.md`.
