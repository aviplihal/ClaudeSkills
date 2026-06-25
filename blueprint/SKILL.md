---
name: blueprint
description: >
  Plans a new project from scratch by running a full automated planning pipeline: generate solutions → spike test → cull → score → repeat until one winner → adversarial stress test → ship PROJECT.md + KEY.md.
  Trigger when the user types /blueprint, "new project", "plan this out", "start planning", "create a plan", or any request to plan/design a project from scratch for a client.
---

# Blueprint Skill v2
**Trigger:** `/blueprint`, "new project", "plan this out", "start planning", "create a plan", or any request to plan/design a project from scratch for a client.

---

## Overview

This skill takes a client pain point + company context and runs a full automated planning pipeline: generate solutions → spike test → cull → score → repeat until one winner → adversarial stress test → ship PROJECT.md + KEY.md. Every run appends lessons to `PLANNING_LESSONS.md` and `TESTING_LESSONS.md` so the skill improves over time.

---

## Phase 0 — Load Memory

Before anything else, check if these files exist. If they do, read them and hold their contents — they will be injected into every planning and testing prompt as learned context:

- `~/skills/blueprint/PLANNING_LESSONS.md`
- `~/skills/blueprint/TESTING_LESSONS.md`

If they do not exist, create them with the header only:
```
# Planning Lessons
_Appended automatically after each blueprint run. Most recent entries at top._
```
```
# Testing Lessons  
_Appended automatically after each blueprint run. Most recent entries at top._
```

Hold both files' contents as `$PLANNING_MEMORY` and `$TESTING_MEMORY`. These are silent context — never print them to the user.

---

## Phase 1 — Intake

Ask the user ALL of these at once in a single numbered message. Do not start planning until you have answers.

```
Before I start planning, I need a few details:

1. Project name — What should this be called?

2. Client context — What does this company do, how big are they, what's their tech 
   maturity level? (e.g. "50-person logistics company, no internal dev team")

3. Pain point — What specific problem are they trying to solve? Paste notes from your 
   conversation if you have them.

4. Outcome definition — What does success look like for the client in 90 days?

5. Constraints — Any hard limits? (budget tier: low/mid/high, must be no-code, 
   must use their existing CRM, no external APIs, etc.)

6. Existing infrastructure — What tools/systems do they already have that we should 
   build on or integrate with?

7. Output location — Where should PROJECT.md and KEY.md be written?
   (Default: ~/projects/<project-name> — say "default" if that works)

8. Existing work — Have we built anything similar before? Name the project if so 
   and I'll pull reuse candidates from it.

9. Anything else — Deadlines, stakeholders, political constraints, prior failed attempts.
```

Wait for the user's reply. Do not proceed until all 9 are answered (partial answers are fine — use judgment for anything left blank).

---

## Phase 2 — Generate 10 Solutions

Spawn a **Planner sub-agent** with this task:

```
Task: Generate 10 distinct solution candidates for this client problem.

Client context: <intake answers>
Planning memory (prior lessons — apply these): <$PLANNING_MEMORY>

For each solution, produce:
  - ID: S01–S10
  - Name: short label
  - Core mechanism: one sentence on HOW it solves the problem
  - Key components: bullet list, max 5 items
  - Rough effort: Low / Med / High
  - Reuse potential: what from our prior work could be reused (check: <existing work from intake Q8>)
  - Fatal flaw: the single most likely way this fails

Make solutions genuinely diverse — don't generate 10 variations of the same idea.
Range from minimal/fast to ambitious/comprehensive. Include at least one no-code 
option and one highly automated option.

Output format: structured markdown table + one paragraph per solution.
Done looks like: 10 solutions with all fields populated.
```

Hold the output as `$SOLUTIONS_V1`. Print a one-line status to the user: `Generated 10 solution candidates. Running spike tests...`

---

## Phase 3 — Spike Test All 10

For each solution in `$SOLUTIONS_V1`, spawn a **Spike Test sub-agent**:

```
Task: Spike test this solution candidate.

Solution: <S0X name, mechanism, components>
Client context: <intake>
Testing memory (prior lessons — apply these): <$TESTING_MEMORY>

Do the following:
1. List every assumption embedded in this solution (aim for 5–8).
2. For each assumption, classify: SAFE (well-proven), RISKY (uncertain), CRITICAL (plan-breaker if wrong).
3. For every RISKY or CRITICAL assumption, write a spike test — a minimal script or 
   concrete check (pseudocode is fine) that would confirm or deny it. The test must 
   be able to FAIL, not just pass.
4. Simulate running each spike test given realistic conditions for a 
   <client tech maturity> client.
5. Produce a verdict: PASS (proceed), WARN (proceed with caution, list what to watch), 
   KILL (fatal assumption failure — do not pursue).

Output: assumption list with classifications, spike test code/pseudocode, verdict + reason.
Done looks like: structured report with a clear PASS / WARN / KILL at the top.
```

Run all 10 spike tests in parallel (spawn all agents at once). Collect results. 

**Cull rule:** Remove any solution with verdict KILL. If fewer than 4 survive, keep the top 4 by WARN count instead of culling all KILLs.

Print status: `Spike tests complete. X/10 solutions survived. Entering scoring round...`

Hold survivors as `$SOLUTIONS_V2`.

---

## Phase 4 — Score and Cull (Iteration Loop)

This phase repeats until one solution (or one combination) remains.

### 4A — Score survivors

Spawn a **Scorer sub-agent**:

```
Task: Score these solution candidates on three metrics.

Solutions: <$SOLUTIONS_V2 or current survivor set>
Client intake: <full intake>
Planning memory: <$PLANNING_MEMORY>

Score each on a 1–10 scale for:

  FIDELITY: How directly does this solve what the client actually asked for?
    10 = solves the exact stated pain point with no translation needed
    1  = technically related but requires the client to change how they work

  COMPLEXITY: How complex is this to build and maintain? (lower = better score)
    10 = simple, uses proven patterns, maintainable by a generalist
    1  = highly complex, novel architecture, requires specialist knowledge

  REUSE: How much of this can be pulled from prior work?
    10 = >60% reusable from existing projects
    1  = built from scratch, no reuse

Weighted total = (FIDELITY × 0.45) + (COMPLEXITY × 0.30) + (REUSE × 0.25)

Also flag any two solutions that could be combined into something stronger than either alone.
Label these COMBO candidates with which solutions and why.

Output: scored table, ranked by weighted total, combo flags.
```

### 4B — Cull

- **Round 1 (≥5 survivors):** Drop bottom 40% by weighted score. Keep combos as single entries.
- **Round 2 (3–4 survivors):** Drop bottom 1–2. Develop remaining plans one level deeper.
- **Round 3 (2 survivors):** Run another spike test pass on remaining candidates (same format as Phase 3 but deeper — focus on integration points and edge cases). Drop the weaker one.
- **Final (1 survivor):** Proceed to Phase 5.

After each cull, print a brief status line showing how many remain and the top scorer.

### 4C — Deepen plans between culls

Before each scoring round (except the first), spawn a **Planner sub-agent** to develop surviving solutions further:

```
Task: Deepen these solution plans.

Solutions: <current survivors with scores>
Client intake: <full intake>
Prior spike test results: <accumulated results>
Planning memory: <$PLANNING_MEMORY>

For each surviving solution, expand:
  - Architecture diagram (ASCII is fine)
  - Step-by-step build sequence (phases, not just features)  
  - Integration points with client's existing systems
  - Data flow: what goes in, what comes out, where it's stored
  - Maintenance burden: who runs this after delivery?
  - Risk register: top 3 risks with mitigations

Do not add scope — deepen what's already there.
```

---

## Phase 5 — Adversarial Stress Test Loop

You now have one winning solution. Spawn **3 adversarial sub-agents in parallel**, each with a different attack angle:

### Agent A — Integration Failure Hunter
```
Task: Find every place this plan assumes two systems will talk to each other smoothly.

Plan: <winning solution full plan>
Client context: <intake>
Testing memory: <$TESTING_MEMORY>

For each integration point:
1. What's the assumption?
2. What breaks it in a real client environment?
3. Write a spike test for the failure mode.
4. Simulate the spike test.
5. Verdict: SOLID / WATCH / WEAK

Flag any WEAK integrations as findings. For each finding, propose a mitigation or fallback.
```

### Agent B — Edge Case Hunter  
```
Task: Find every edge case in this plan that could cause silent failure or bad UX.

Plan: <winning solution full plan>
Client context: <intake>
Testing memory: <$TESTING_MEMORY>

Focus on:
- Empty states (what happens when there's no data?)
- Volume limits (what happens at 10x expected load?)
- Human error paths (what if the client's team does it wrong?)
- Timing issues (race conditions, stale data, delays)
- Partial failure (what if step 3 of 7 fails silently?)

For each edge case: describe it, write a spike test, simulate it, verdict SOLID/WATCH/WEAK.
Propose a fix for every WEAK.
```

### Agent C — Fit-to-Client Hunter
```
Task: Assess whether this plan actually fits this specific client's context.

Plan: <winning solution full plan>  
Client context: <intake — pay special attention to tech maturity, team size, constraints>
Testing memory: <$TESTING_MEMORY>

Challenge:
- Does this require skills the client doesn't have?
- Does this introduce tools they'll resist adopting?
- Is the maintenance burden realistic for their team?
- Does this actually match the 90-day success definition?
- Are there compliance, privacy, or data handling issues for their industry?

For each concern: describe it, assess severity (MINOR / MAJOR / BLOCKER), propose resolution.
```

### Stress Test Loop Condition

Collect all findings from A, B, C. Categorize each as:
- **Edge case** (minor, expected to exist, plan can ship)
- **Major issue** (structural — plan needs to change)

Calculate: `major_issue_rate = major_issues / total_features`

**If `major_issue_rate > 0.05`:**
- Apply all proposed mitigations to the plan
- Respawn all 3 agents on the updated plan
- Loop until rate drops to ≤5%
- Cap at 4 loops — if still above 5% after 4, flag remaining issues to the user and ask how to proceed

**If `major_issue_rate ≤ 0.05`:** Proceed to Phase 6.

Print status after each loop: `Stress test loop X: Y major issues found (Z%). <proceed or looping>`

---

## Phase 6 — Write Output Files

### PROJECT.md

Write to the output location from intake Q7. Include:

```markdown
# <Project Name>

## 1. Client Context
<company background, pain point, success definition>

## 2. Solution Overview  
<the winning solution: what it is, why it was chosen over alternatives>

## 3. Architecture
<ASCII diagram + component list>

## 4. Build Sequence
Phase 1 — <name> (<timeframe>)
  - Feature F01: <description>
  - Feature F02: <description>
  ...

Phase 2 — ...

## 5. Integration Map
<each integration point, what connects, what the fallback is>

## 6. Risk Register
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
...

## 7. Maintenance & Handoff
<who runs this, what breaks, how to fix it>

## 8. Discarded Solutions
<S01–S0X that were culled, one line each on why>

## 9. Open Questions
<anything unresolved that needs client input>
```

### KEY.md

```markdown
# <Project Name> — Session Key

## Quick Routing
- Start here: <entry point file or service>
- Main config: <config file path>
- Creds/env: <.env location or vault reference>

## Feature Index
| ID  | Feature | Status | Notes |
|-----|---------|--------|-------|
| F01 | ...     | TODO   |       |
...

## Sub-agent Handoff
Run /handoff to pass context to a new session.
```

Commit both files to the repo if a repo path was provided.

---

## Phase 7 — Append Lessons (Always Runs)

This phase always runs after every blueprint, even partial ones. It is what makes the skill compound over time.

### Update PLANNING_LESSONS.md

Spawn a **Lessons sub-agent**:

```
Task: Extract planning lessons from this blueprint run.

Intake: <full intake>
Solutions generated: <$SOLUTIONS_V1>
Culling decisions: <what was cut and why at each round>
Winner: <final solution>
Stress test findings: <all findings from Phase 5>

Extract lessons in these categories:
  PATTERN — something that worked well and should be repeated
  ANTIPATTERN — something that failed or was repeatedly culled for the same reason
  REUSE — a specific component, pattern, or approach worth reusing in future projects
  METRIC — a scoring adjustment (e.g. "fidelity weight should be higher for no-code clients")

Format each lesson as:
  ### [CATEGORY] <short title>
  **When:** <context in which this applies>
  **Lesson:** <what to do or avoid>
  **Evidence:** <what happened in this run that proves it>

Prepend to PLANNING_LESSONS.md (most recent at top). Max 5 lessons per run.
```

### Update TESTING_LESSONS.md

```
Task: Extract testing lessons from this blueprint run.

Spike test results: <all Phase 3 + Phase 5 results>
Stress test loop count: <how many loops it took>
Major issues found: <list>
Issues that were false positives: <list>

Extract lessons:
  ASSUMPTION — a class of assumption that consistently proved RISKY for this type of project
  SPIKE — a spike test pattern that reliably caught real issues
  FALSE_POSITIVE — a concern that looked serious but wasn't (so future agents don't over-weight it)
  THRESHOLD — any insight about when to KILL vs WARN

Format same as planning lessons. Prepend to TESTING_LESSONS.md. Max 5 lessons per run.
```

---

## Phase 8 — Confirm Completion

Tell the user:

```
Blueprint complete. Written to <output location>:

  PROJECT.md  — solution architecture, build sequence, risk register
  KEY.md      — session routing index and feature tracker

Stress test cleared: <X> major issues resolved over <N> loops.
Lessons appended: PLANNING_LESSONS.md (+X), TESTING_LESSONS.md (+X)

Run /handoff at any time to pass context to a new session.
Tell me which feature ID to start on first.
```

Nothing else. Do not summarize the plan — it is in the files.

---

## Sub-agent Template

Every sub-agent spawned by this skill must include this header:

```
You are a sub-agent operating inside the Blueprint skill pipeline.
You do NOT have access to CLAUDE.md or any global config.
All context you need is provided inline in this task.
Complete your task, produce the requested output format exactly, then stop.
Do not ask clarifying questions — use your best judgment given the context provided.
```

---

## Cull Summary Table

| Phase | Survivors In | Rule | Survivors Out |
|-------|-------------|------|---------------|
| Post Phase 3 spike | 10 | Kill all KILL verdicts (min 4) | ~6 |
| Score Round 1 | ~6 | Drop bottom 40% | ~4 |
| Score Round 2 | ~4 | Drop bottom 1–2, deepen rest | 2–3 |
| Score Round 3 | 2–3 | Deep spike test, drop weakest | 1 |
| Phase 5 stress | 1 | Loop until <5% major issue rate | 1 (hardened) |

---

## File Locations (defaults)

| File | Default Path |
|------|-------------|
| PLANNING_LESSONS.md | `~/skills/blueprint/PLANNING_LESSONS.md` |
| TESTING_LESSONS.md | `~/skills/blueprint/TESTING_LESSONS.md` |
| PROJECT.md | `<output location from intake>/PROJECT.md` |
| KEY.md | `<output location from intake>/KEY.md` |

---

## Notes

- **Parallelism:** Phase 3 spike tests and Phase 5 stress agents run in parallel. Everything else is sequential.
- **Combo solutions:** If two solutions are flagged as COMBO candidates, treat the combination as a single entry going forward. Score it fresh.
- **Partial intake:** If the user can't answer some intake questions, proceed with what you have. Note gaps in PROJECT.md §9 (Open Questions).
- **Token efficiency:** Sub-agents receive only the context they need for their task — do not pass the full conversation history, only extracted relevant fields.
- **No user interruptions:** Do not surface intermediate results or ask for approval between phases. Only interrupt if the stress test loop hits the 4-loop cap without clearing the threshold.
