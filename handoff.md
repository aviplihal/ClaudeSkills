Prepare a context handoff for transitioning to a new chat session. Execute all five phases sequentially without seeking intermediate approval.

## Phase 1 — Capture current state

Run git commands, check progress files, and review configuration documents to understand the current project state. Do not display raw output to the user.

## Phase 2 — Commit uncommitted work

Stage and commit any uncommitted changes:
- Use specific file names when staging (never `git add .` or `git add -A`)
- Avoid committing secrets or build artifacts
- Label partial work as `[WIP]` in the commit message; complete units get a normal message
- Update `claude-progress.txt` with a timestamped entry describing what was done

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

## Phase 4 — Generate handoff prompt

Output a ready-to-paste prompt containing:
- Project path and current branch
- One-line immediate next action taken directly from the HANDOFF.md next steps

## Phase 5 — Confirm

Confirm handoff is ready. No summary, no offers to help further — just confirm and stop.

## Rules

- Execute all phases without asking for approval between them
- Document "gotchas" and unresolved dependencies explicitly
- Keep the handoff prompt concise and immediately actionable
- Zero information loss is the goal — the next session should need nothing beyond HANDOFF.md
