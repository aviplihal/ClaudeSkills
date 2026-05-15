---
name: handoff
description: >
  Prepares a complete context handoff so work can continue in a fresh chat with no
  information loss. Trigger when Asher types /handoff or says anything like "hand off",
  "pass to new chat", "start a new session", "context is getting full", "switch chats",
  or "prepare a handoff". Commits in-progress work, updates all progress and memory files,
  writes a HANDOFF.md, and produces a ready-to-paste prompt for the new chat.
---

# Handoff Skill

When invoked, execute all phases in order without stopping for approval. The goal is to
leave the repo in a clean, documented state and give Asher a single prompt to paste into
the next chat.

---

## Phase 1 — Capture current state

Run these commands and hold the results in mind. Do NOT print them raw to the user.

```bash
# Project detection
pwd
ls

# Git state
git status 2>/dev/null || echo "NO_GIT"
git log --oneline -10 2>/dev/null || echo "NO_GIT"
git diff --stat 2>/dev/null || echo ""
git stash list 2>/dev/null || echo ""

# Progress and feature state
cat claude-progress.txt 2>/dev/null || echo "NO_PROGRESS_FILE"
```

If inside a subdirectory of a git repo, also capture:
```bash
git -C <repo_root> log --oneline -10
git -C <repo_root> status
```

Also read:
- `feature_list.json` if it exists — note which features have `passes: true` vs `false`
- `CLAUDE.md` if it exists — to understand what project this is
- `WORKTREES.md` if it exists — to capture parallel work state
- Any active todo list from this session (from memory)

---

## Phase 2 — Commit any in-progress work

**If there are uncommitted changes:**

1. Determine if this is mid-feature (partial) or a complete unit of work.
2. If partial: commit with `[WIP] <description of what's in progress>` as the message.
3. If complete: commit with a normal message.
4. Always add specific files by name — never `git add -A` blindly. Skip `.env`, secrets,
   and binary build artifacts.
5. After committing, run `git status` to confirm clean.

**If working tree is already clean:** skip to Phase 3.

Always append to `claude-progress.txt` before committing:
```
[YYYY-MM-DD] HANDOFF: <one sentence on current state>. Next: <one sentence on what comes next>.
```

---

## Phase 3 — Write HANDOFF.md

Write `HANDOFF.md` to the project root (overwrite if it exists). This file is the source of
truth for the next chat. Structure:

```markdown
# Handoff — <Project Name>

**Date:** <today>
**Branch:** <current branch>
**Last commit:** <hash and message>

## What this project is
<2-3 sentences from CLAUDE.md — pipeline overview, what it does, where it runs>

## Current state
<What was being worked on in this session. Be specific: which feature, which file,
which function, what decision was being made.>

## What was completed this session
<Bulleted list of concrete things done — reference file paths and commit hashes>

## What to do next
<Numbered list of the immediate next steps, in order. First item should be actionable
immediately after reading this file.>

## Key file map
<Table or list of the most important files to know about:
- Config / entry points
- The files touched this session
- Files the next task will need>

## Feature status summary
<From feature_list.json: how many total, how many pass, which ones are in-flight>

## Active worktrees (if any)
<From WORKTREES.md or git worktree list: which branches exist and what each is for>

## How to start the dev environment
<From init.sh or CLAUDE.md>

## Things to watch out for
<Any gotchas, known issues, in-progress decisions that weren't finalized, or
dependencies that weren't resolved>
```

Commit `HANDOFF.md` and the updated `claude-progress.txt` together:
```
git add HANDOFF.md claude-progress.txt
git commit -m "Handoff: update progress log and context doc"
```

---

## Phase 4 — Print the handoff prompt

After committing, print this block to the user exactly as shown, filled in with real values.
This is what Asher pastes into the new chat.

---

```
Continuing work on <Project Name> at <absolute path to project root>.

This is a handoff from the previous chat session. Read HANDOFF.md in the project root first — it has the full context, current state, and next steps.

Session start checklist (from CLAUDE.md):
1. pwd → read claude-progress.txt → read feature_list.json → git log --oneline -20
2. Run init.sh if it exists, smoke-test before touching any code

Current branch: <branch>
Last commit: <hash> <message>

Resume from: <the specific next step — copy the first item from "What to do next" in HANDOFF.md>
```

---

## Phase 5 — Final confirmation to user

After printing the prompt, say:

> Handoff complete. Copy the block above and paste it into a new chat to continue.
> `HANDOFF.md` is committed to the repo and has the full context.

Nothing else. Do not summarize what you did. Do not offer to do more work.
