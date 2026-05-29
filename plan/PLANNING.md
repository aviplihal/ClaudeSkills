# PLANNING.md — New Project Skill

> Load once at the start of a project (or a major redesign). Not needed in normal sessions. Produces `PROJECT.md`, `KEY.md`, and (if applicable) the `AUTORESEARCH.md` config block.

---

## Strategy

- 5 Sonnet sub-agents + 1 Opus commander.
- Each Sonnet agent reads the brief independently and writes its own plan.
- Commander merges plans and finds weak spots.
- Weak spots go back to sub-agents to resolve.
- A review committee of agents checks the final plan; anything off goes back.

## Inter-Agent Communication

- Each sub-agent maintains a markdown file with a highly condensed version of its thinking.
- At 50k tokens, it updates the file. Commander spawns a fresh instance from the file.
- Commander uses a shared markdown file for cross-agent coordination.

## Feasibility Tests

Run in parallel during planning — each under 5 minutes, isolated, validating different parts of the plan.

## Deliverables (in this order)

1. Write `PROJECT.md` using the template at `/Users/bluelobster/skills/plan/PROJECT.md`.
2. Write/update `KEY.md` using the template at `/Users/bluelobster/skills/plan/KEY.md` — add a routing row for every new section, file, or recurring task introduced by the plan. **`KEY.md` is generated from `PROJECT.md`, not assumed to exist.** If `KEY.md` already exists from a prior plan, append/merge — do not overwrite blindly.
3. Write `AUTORESEARCH.md` config block (§12) only if the project triggers auto-research (see §0 of `/Users/bluelobster/skills/plan/AUTORESEARCH.md`).

## KEY.md Maintenance Rule

Any time a new section is added to `PROJECT.md`, a new top-level `.md` file is introduced, or a recurring task emerges that isn't already routed, update `KEY.md` in the same commit. Stale routing is worse than no routing — it leads Claude to the wrong section confidently.
