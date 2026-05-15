---
name: repo-hygiene
description: >
  Clean up a codebase after a major implementation or when the repo feels messy — without
  changing any behavior. Its core job is fixing the file and folder structure (moving files
  into domain folders, killing junk drawers like /utils and /helpers, renaming files after
  what they do, splitting mixed-domain files, collapsing shallow or redundant folders), and
  from there renames vague code to be explicit, removes dead and duplicate code, rewrites
  comments to explain WHY, and refreshes CLAUDE.md. Use this skill whenever the user says
  things like "clean up the repo", "clean up the file structure", "repo hygiene", "refactor
  the structure", "reorganize the folders", "fix the folder structure", "the file layout is
  a mess", "move these files where they belong", "remove dead code", "tidy up the codebase",
  "post-implementation cleanup", "the repo feels messy", "update CLAUDE.md", or "reduce
  duplication". Also use proactively after a large feature merge, or when the user complains
  that AI keeps making mistakes in a specific codebase — that is almost always a sign the
  structure or the code has become too implicit. Does NOT add features, fix bugs, or change
  program behavior.
---

# Repo Hygiene

You are cleaning up a codebase so that humans can navigate it and AI agents can work in it
without getting lost. Two audiences, one standard: code that says what it means.

**The only hard boundary:** working code stays working. Every cleanup step is a trade between
risk and readability. If a rename or a move cannot be verified safely, leave it and flag it
in the audit. This skill is a gardener, not a renovator — no new features, no behavioral
changes, no "while I'm here" refactors.

---

## Why this matters

Messy code hurts twice. Humans have to hold too much in their head to make a change. AI agents
start every session with zero context, so they pay the worst price — vague names and scattered
files lead to wrong guesses, which lead to real bugs. Most of the time when someone says "the
AI keeps screwing up in this repo," the real problem is the code itself is ambiguous, or the
file layout forces the reader to chase logic across the tree.

Cleanup is not cosmetic. It is the difference between a repo that compounds well over time and
one that fights every change.

---

## Core principles

### Structure is the first thing a reader sees

Before anyone reads a line of code, they read the tree. A clean tree answers "where does this
live?" in one glance. A messy one — junk drawers, files named by type, shallow folders with
one item, duplicated concerns across branches — costs every reader time, every time.

**Start with a healthy top-level hierarchy.** The root of the repo should make the shape of
the system obvious at a glance. For most projects that means a clean split between major
execution environments:

```
repo-root/
  frontend/        ← client-side code, UI, browser-only assets
  backend/         ← server, routes, DB access, background jobs
  shared/          ← types, validation schemas, constants used by both
  scripts/         ← one-off CLI tools, migrations, dev scripts
  docs/            ← human-facing documentation
```

Alternative names for the same pattern (pick one and use consistently): `client`/`server`,
`web`/`api`, or `app`/`api`. Mobile lives as a peer: `mobile/` next to `frontend/` and
`backend/`. Pure libraries and CLIs don't need this split — don't invent folders a project
doesn't need.

**Inside each top-level folder, group by domain.** Folders are named by domain (`/auth`,
`/orders`, `/notifications`), not by type (`/utils`, `/helpers`, `/services`, `/types`).
Each domain owns its own routes, services, models, and types so a contributor can work in
one folder without hopping across the tree. Truly shared utilities live in
`/lib/[what-it-does]` — never in a generic catch-all.

Files are named after **what they do**, not what category they belong to:

```
❌ utils.ts, helpers.ts, misc.ts, types.ts, service.ts
✅ orderValidator.ts, stripeWebhookParser.ts, sessionManager.ts
```

A healthy tree has the property that, given a feature name, a new contributor can guess the
folder it lives in before grepping. If they can't, the structure is costing you.

### Explicit beats clever

Explicit names, explicit types, explicit conditions. If a reader — human or AI — has to pause
to figure out what something means, rename it.

```
❌ process(), handleData(), result, data, flag, temp
✅ validateAndQueueOrder(), parseStripeWebhook(), createdOrderId, rawApiResponse
```

On every exported function, write the parameter and return types out. Don't chain three
ternaries when an `if/else` with a named variable reads cleaner. Replace magic numbers with
named constants.

### Comments explain WHY, not WHAT

The code already says what it does. A comment earns its space only when it says something the
code cannot — the reason behind a decision, a constraint from outside the codebase, an
invariant that is not obvious.

```
❌ // Loop through users            (the for-loop already says this)
❌ // Return true if admin          (isAdmin() already says this)
✅ // Stripe sends duplicate events — idempotency check must run before state update
✅ // Denormalized intentionally — this query runs at high volume and can't afford the join
✅ // Third-party SDK is 1-indexed; looks wrong but isn't
```

One sentence, directly above the relevant block. Every complex function deserves one sentence
at the top explaining *why it exists*.

### Cohesion over line count

File length is a symptom, not a disease. A 600-line auth module with one coherent concern is
healthy. A 200-line file mixing auth with email formatting is a split candidate.

**Split test:** can you name both halves accurately without using the words "helpers",
"utils", or "misc"? If not, leave it alone. The fragmented files would end up worse than the
long one.

### Locality of behavior

Related logic lives together. Deep inheritance trees and long helper chains scatter a single
concept across five files — both humans and AI pay the cost of chasing imports. Flat and
local beats clever DRY almost every time.

---

## Workflow

Work in phases. Run the project's tests after each one, so if something breaks you know which
phase caused it. The phases are ordered safest first — audit before any edit, structure before
renames, renames before deletions.

### Phase 1 — Audit (read-only)

Produce `HYGIENE_AUDIT.md` at the repo root. This is a scratchpad: it gets deleted at the end,
and it does not get committed. The point is to build a full picture before editing anything.

Look for, in roughly this order of priority:

- **Structural smells** — these are the highest-leverage findings because fixing them makes
  every later phase easier:
  - Missing or muddled top-level split — frontend and backend code mixed in one tree, or
    no clear `frontend/`/`backend/` (or `client/`/`server`, `web/`/`api`) separation at
    the root when the project has both
  - Junk drawers (`/utils`, `/helpers`, `/misc`, `/common`, `/shared`, `/core`)
  - Type-named folders (`/services`, `/models`, `/controllers`, `/types`) when the project
    has enough real domains to group by feature instead
  - One feature's code scattered across layers (`/controllers/auth.ts`,
    `/services/auth.ts`, `/models/auth.ts`) that would read better as a single `/auth/` folder
  - Files named by type rather than content (`utils.ts`, `helpers.ts`, `service.ts`)
  - Mixed-domain files — a single file doing two unrelated jobs
  - Shallow folders (one file inside) or near-duplicate sibling folders
  - Inconsistent casing (camelCase, kebab-case, and snake_case mixed in the same tree)
- **Vague names** — functions, variables, and files that should be more explicit
- **Duplicates** — the same function defined in more than one place
- **Dead code** — commented-out blocks, unused imports, unused exports (only ones tooling confirms)
- **Missing comments** — non-trivial logic with no explanation of intent

Useful starting commands (adapt to the project's language and tooling):

```bash
# Largest source files — anything over ~400 lines is worth a cohesion review
find . -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.py" \) \
  -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "*/dist/*" \
  -exec wc -l {} + | sort -rn | head -30

# Unused TypeScript exports
npx ts-unused-exports tsconfig.json 2>/dev/null || true

# Python unused imports / dead code
python -m pyflakes . 2>/dev/null || true
```

Group findings in the audit by phase (structure, names, dead code, comments). Later phases
will work straight off this list.

### Phase 2 — Structure (the heart of this skill)

Execute the structural moves surfaced in the audit. Order matters — each step sets up the
next, and small batches keep breakages easy to trace.

1. **Fix the top-level split first.** If frontend and backend share one tree, separate them
   into `frontend/` and `backend/` (or the project's equivalent pair) with anything shared
   in a peer `shared/`. Everything downstream depends on this being right.

2. **Move files into domain folders** inside each top-level folder. Start with the
   unambiguous wins — junk-drawer files whose correct home is obvious. Move a small batch,
   update every import, run tests, verify green, then continue.

3. **Rename files from type-based to content-based.** `utils.ts`, `helpers.ts`, `service.ts`
   aren't names — they're placeholders. Replace with verb-or-noun names describing the
   contents (examples in the structure principle above).

4. **Split mixed-domain files.** Apply the split test: can you name both halves without
   "helpers"/"utils"/"misc"? If not, the split is wrong — leave it.

5. **Collapse shallow or redundant folders.** A folder with one file, or a near-duplicate of
   a sibling, usually wants to be merged. Extra depth lengthens imports without adding clarity.

6. **Standardize casing.** Pick one convention (camelCase, kebab-case, snake_case) per file
   type and apply it across the tree.

**When moving files:**

- Use the editor's move/rename tool — it updates every import at once, which is safer and
  faster than manual find/replace.
- Never move `.env`, CI configs, lockfiles, migrations, or deployment manifests. Those have
  semantics beyond location and are outside this skill's scope.
- If a file's correct home is ambiguous, leave it and flag it in the audit for the user
  to decide.

### Phase 3 — Explicit code

Rename, don't rewrite. Clarity without behavioral change.

- Vague functions → full verb-noun phrases: `process()` → `validateAndEnqueuePayment()`
- Vague variables → what they actually hold: `result` → `createdOrderId`
- Exported functions get explicit parameter and return types
- Nested ternaries → named variables with `if/else`
- Magic numbers → named constants

Use the editor's rename/refactor tool when available — it updates every reference at once,
which is both safer and faster than manual find/replace. Run tests after each batch so a
breakage has a small diff to investigate.

### Phase 4 — Dead code and duplicates

**Duplicates:** read both versions end to end. Confirm they really do the same thing (small
differences in error handling, logging, or arguments often hide real divergence). Keep the
better version, move it to the domain that owns it, update every call site, delete the other.

**Dead code, safest first:**
1. Commented-out blocks — read them first. Sometimes they're intentionally disabled, not dead.
2. Unused imports
3. Unused exports — only when tooling confirms. Never delete on a hunch.
4. Unreachable code after unconditional `return` or `throw`

The rule: no deletion without tooling confirmation or manual verification of every call site.
When in doubt, leave it and note it in the audit.

### Phase 5 — Comments

Two moves, in order:

**Remove** comments that restate code the reader can already see. They add noise and go stale
as the code changes.

**Add** comments wherever a reader would have to guess at intent — non-obvious decisions,
business rules not derivable from the code, sequencing dependencies, third-party quirks, edge
cases that look wrong but aren't. One sentence, above the relevant block, written for someone
who has never seen this repo before.

### Phase 6 — CLAUDE.md

CLAUDE.md is how both new developers and AI agents onboard to the project. Keep it under ~150
lines. Never include a file tree — it goes stale and misleads. Document conventions and the
*why* behind them instead.

A solid template (adapt to the project, don't copy blindly):

```markdown
# [Project Name]

## What this is
One paragraph — what it does and who uses it.

## Tech stack
- Runtime and language versions
- Key frameworks
- Database and how it's accessed
- Key third-party services

## How to run
Install, dev, test, build — exact commands.

## How code is organized
Describe the pattern. Example: "Features are grouped by domain in `/src/[domain]`. Each
domain owns its routes, services, and types. Shared utilities live in `/src/lib/[name]`."

## Conventions
- Function naming: full verb-noun
- Exported functions: explicit parameter and return types
- Comments: explain why, one sentence above complex logic
- Cohesion over line count

## Danger zones
Files or areas that need extra caution — auth, payments, migrations.

## Things AI gets wrong here
The most valuable section in the file. Every time an AI makes the same mistake, write the
pattern down here.
- [mistake] → [what to do instead]
```

The "Things AI gets wrong here" section has the highest ROI in the whole file. It shortens
every future session in this repo.

### Phase 7 — Verify and clean up

Not optional. Run the project's standard checks. Typical set:

```bash
# Adapt to the project
npx tsc --noEmit   # type check passes
npm test           # tests pass
npm run build      # build succeeds
```

If anything fails, the cleanup introduced a bug. Revert the last phase, find the cause, then
try again. Do not commit a broken cleanup "to fix later" — that defeats the whole point.

Finally, delete `HYGIENE_AUDIT.md`. It was scaffolding, not output.

---

## What this skill never does

- Break working code, for any reason
- Split cohesive files just to hit a line-count target
- Introduce new abstractions, patterns, or libraries
- Delete code without tooling confirmation or manual verification of every call site
- Touch `.env`, CI configuration, migrations, or deployment files — those are outside the
  scope of hygiene and mistakes there are expensive

If the user asks for any of these during a cleanup pass, stop and flag it as a separate task.
Hygiene is a narrow mandate; keeping it narrow is what makes it safe to run regularly.

---
