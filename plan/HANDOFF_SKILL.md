# HANDOFF skill — `/handoff`

> Loaded only when `/handoff` runs (manually, or automatically at 100k tokens). Not resident in normal context. Writes `HANDOFF.md` (template at /Users/bluelobster/skills/plan/HANDOFF.md). Execute all phases without asking for approval between them.

---

**Phase 1 — Capture state.** Run git commands, check progress files, review config. Don't dump raw output.

**Phase 2 — Commit.**
- Stage specific files (never `git add .`).
- No secrets, no build artifacts.
- `[WIP]` prefix for partial work; normal message for complete units.
- Append to `claude-progress.txt`: `[YYYY-MM-DD] Done: ... Next: ...`

**Phase 3 — Write `HANDOFF.md` at repo root** (use the template at `/Users/bluelobster/skills/plan/HANDOFF.md`) with:
- Project overview and current state
- This session's work
- Completed items
- Next steps (ordered, specific, actionable)
- Key file locations
- Feature status (pass/fail per relevant feature)
- Dev env setup from scratch
- Gotchas and unresolved dependencies

**Phase 4 — Output a ready-to-paste prompt:**
- Project path, current branch
- One-line immediate next action from HANDOFF.md

**Phase 5 — Confirm and stop.** No summary, no offer to help further.

**Resume cleanup:** when a new session has read `HANDOFF.md` and confirmed it, archive it: `mv HANDOFF.md handoffs/<branch>_<YYYY-MM-DD>.md`. Don't leave a stale HANDOFF.md at repo root — the next-next session will think it has unfinished work.

Zero information loss — the next session should need nothing beyond `HANDOFF.md`.
