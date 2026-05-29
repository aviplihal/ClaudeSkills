# PROJECT.md — `<PROJECT_NAME>`

> Per-project. Replace `<PROJECT_NAME>` and every `<placeholder>`. Sectioned so `KEY.md` can point to one section at a time. Keep every section condensed.

---

## 1. Overview

- **Purpose:** <one sentence: what this project does and for whom>
- **Key values:** <2–4 non-negotiables; e.g. "human in the loop", "no agent calls another directly">
- **Hosting:** <where it runs in prod>
- **Serving:** <how users reach it; which dir is served vs. dev>
- **Stack:** <languages, frameworks, infra in one line>

## 2. Folder Structure

| Path | What lives here | When to reference |
|---|---|---|
| `<dir>/` | <desc> | <when> |
| `<dir>/` | <desc> | <when> |

**Critical files** — read only when working in their domain:

| File | Section pointers (for KEY.md) |
|---|---|
| `<file>` | `<section>` for <topic>; `<section>` for <topic> |

## 3. Pipeline / Architecture

```
<text diagram of the data/control flow, end to end>
```

One paragraph naming each stage and what it owns.

## 4. Features

Each row is one feature. ID = `<worktree-id>-<number>` (worktree ID = 2 letters + 1 digit).

| ID | Section | Description | Definition of passing | Status |
|---|---|---|---|---|
| `bk1-01` | backend | <desc> | <human-verifiable pass criteria> | false |
| `bk1-02` | backend | <desc> | <pass criteria> | false |

Status is `true` only after end-to-end human-style test, never after code review.

## 5. Worktrees

Dependency map (drawn or table form):
```
wt/<a> → wt/<b> → wt/<c>
                  wt/<d>
```

Per-worktree spec:

### `wt/<name>` (ID: `<XX#>`)
- **Branch:** `wt/<name>`
- **Serving:** <where, if applicable>
- **Dependencies:** <list, or "none">
- **Contains:** <which feature IDs>
- **Definition of done:** <observable>
- **Mergeable when:** <observable>
- **How to test:** <one command or short procedure>

(repeat per worktree)

**Merge order:** `wt/<a> → wt/<b> → wt/<c>`. Smoke-test before each merge.

## 6. Feasibility Tests

Tests that validate the plan before full implementation. Each ≤ 60 min, isolated.

| Test | What it validates | Pass criteria |
|---|---|---|
| <name> | <which assumption> | <observable> |

## 7. End-to-End Tests

Full-stack tests that mimic a human user via MCPs / browser drivers / API calls. Run before any merge to main.

| Test | Flow | Pass criteria |
|---|---|---|
| <name> | <step 1 → step 2 → ...> | <observable> |

Maintain a `TEST_LEARNINGS.md` of condensed lessons from test runs. Update after each run.

## 8. Improvements / Auto-Research Hook

If this project has a measurable AI/ML pipeline:

- **Sections to optimize:** <list, e.g. "sketch cleanup", "BOM extraction">
- **Metric per section:** <how each is scored>
- **Benchmark size:** <count> examples (60 train / 20 validation / 20 holdout)
- **Win condition:** <e.g. ≥ X improvement, no regression > Y>

Full playbook in `/Users/bluelobster/skills/plan/AUTORESEARCH.md`.

## 9. Coding Conventions (project-specific)

Only overrides from `/Users/bluelobster/skills/plan/CLAUDE.md` section 1. Keep tight.

- <override or addition>
- <override or addition>

## 10. Gotchas

Append-only. Each entry one line. Empty section = no gotchas recorded yet (this is normal for new projects, not a missing section).

- `[YYYY-MM-DD]` <gotcha>
