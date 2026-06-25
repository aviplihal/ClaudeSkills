---
name: handoff
description: >
  Prepares a complete context handoff so work can continue in a fresh chat with no
  information loss. Trigger when the user types /handoff or says anything like "hand off",
  "pass to new chat", "start a new session", "context is getting full", "switch chats",
  or "prepare a handoff". Commits in-progress work, updates all progress and lesson files,
  writes a HANDOFF.md, and produces a ready-to-paste prompt for the new chat.
---

# Handoff Skill

Prepare a context handoff for transitioning to a new chat session. Execute all phases sequentially without seeking intermediate approval.

---

## Phase 1 — Capture current state

Run git commands, check progress files, and review configuration documents to understand the current project state. Do not display raw output to the user.

---

## Phase 2 — Commit uncommitted work

Stage and commit any uncommitted changes:
- Use specific file names when staging (never `git add .` or `git add -A`)
- Avoid committing secrets or build artifacts
- Label partial work as `[WIP]` in the commit message; complete units get a normal message
- Update `claude-progress.txt` with a timestamped entry describing what was done

---

## Phase 2.5 — Append lessons

Check which lesson files are relevant to this session and append to them. Read the existing file first so you don't duplicate entries already there.

**Determine session type:**
- If this session worked from a blueprint plan → write to `PLANNING_LESSONS.md`
- If this session ran tests or spike tests → write to `TESTING_LESSONS.md`
- If this session built features → write to `IMPLEMENTATION_LESSONS.md`
- If this session delivered to a client or closed a project → write to `DELIVERY_LESSONS.md`
- A session can trigger multiple files. Apply all that fit.

**File locations:** `~/skills/blueprint/<file>.md`. Create the file with the header below if it doesn't exist.

```
# <Type> Lessons
_Appended automatically at each /handoff. Most recent entries at top._
```

**For each applicable file, spawn a Lessons sub-agent:**

```
Task: Extract lessons from this session and prepend them to <FILENAME>.

Session summary: <what was worked on this session from claude-progress.txt>
Git diff summary: <what actually changed — files touched, features completed, things that broke>
Project context: <project name, client type, tech stack>
Existing lessons (do not duplicate): <current contents of the target file>

Extract 2–4 lessons. Prioritize specificity over volume — one sharp lesson beats three vague ones.

Categories:
  For PLANNING_LESSONS.md:
    PATTERN      — something that worked and should be repeated in future plans
    ANTIPATTERN  — something the plan got wrong that reality corrected
    ESTIMATE     — a sizing or effort assumption that was off, and by how much
    REUSE        — a component or pattern worth pulling into future projects

  For TESTING_LESSONS.md:
    ASSUMPTION   — a class of assumption that consistently proved risky for this project type
    SPIKE        — a spike test pattern that reliably caught real issues
    FALSE_POS    — a concern that looked serious but wasn't (don't over-index on it next time)
    COVERAGE_GAP — a failure mode the spike tests missed that only showed up in implementation

  For IMPLEMENTATION_LESSONS.md:
    FRICTION     — something that took significantly longer than the plan estimated, and why
    INTEGRATION  — an integration point that broke or required rework mid-build
    SIMPLIFY     — something the plan over-engineered; what the simpler version was
    PATTERN      — an implementation approach worth reusing

  For DELIVERY_LESSONS.md:
    ADOPTION     — did the client actually use what was built? What got ignored?
    CONFUSION    — what confused the client or required extra explanation?
    SCOPE_DRIFT  — features that changed after delivery and why
    OUTCOME      — did the solution actually solve the stated pain point?

Format each lesson as:
  ### [CATEGORY] <short title>
  **When:** <context in which this applies — project type, tech stack, client maturity>
  **Lesson:** <what to do or avoid, stated as a directive>
  **Evidence:** <what happened in this session that proves it>

Prepend to the file (newest at top). Do not rewrite existing entries.
Output: the new entries only, ready to prepend.
```

Prepend the sub-agent's output to the file. Commit the updated lesson files in the same commit as `claude-progress.txt` — do not make a separate commit.

Do not surface lesson content to the user. One-line status only: `Lessons appended: IMPLEMENTATION_LESSONS.md (+3 entries)`

---

## Phase 3 — Create HANDOFF.md

Write a `HANDOFF.md` file at the repo root as the authoritative handoff document. Include:

- **Project overview** — what this project is and its current state
- **Current session work** — what was done this session
- **Completed items** — what is fully done
- **Next steps** — ordered list of what to do next, specific and actionable
- **Key file locations** — important files and what they do
- **Feature status** — each relevant feature and whether it passes/works
- **Development environment setup** — how to get running from scratch
- **Gotchas and unresolved dependencies** — anything that would surprise a new session

---

## Phase 4 — Generate handoff prompt

Output a ready-to-paste prompt containing:
- Project path and current branch
- One-line immediate next action taken directly from the HANDOFF.md next steps

---

## Phase 5 — Confirm

Confirm handoff is ready. No summary, no offers to help further — just confirm and stop.

---

## Rules

- Execute all phases without asking for approval between them
- Document "gotchas" and unresolved dependencies explicitly
- Keep the handoff prompt concise and immediately actionable
- Zero information loss is the goal — the next session should need nothing beyond HANDOFF.md
- Lesson files are committed alongside progress updates — never as a standalone commit
- Never surface raw lesson content to the user during handoff
