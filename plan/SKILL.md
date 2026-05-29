---
name: plan
description: >
  Plans a new project or major redesign by first gathering all required context from Asher,
  then producing PROJECT.md, KEY.md, and (if applicable) an AUTORESEARCH.md config block.
  Trigger when Asher types /plan, "new project", "plan this out", "plan a new project",
  "start planning", "create a plan", or asks to plan or design a project from scratch.
---

# Plan Skill

When invoked, work through the phases below in order. Do not skip the intake phase —
a plan is only as good as the brief it is built from.

---

## Phase 1 — Intake (collect everything before planning)

Ask Asher the following questions. Ask them all at once in a single message, numbered,
so he can answer in one reply. Do NOT start planning until you have answers.

```
Before I start planning, I need a few details:

1. **Project name** — What should this project be called?

2. **Git repo** — Where does (or will) the repo live?
   - Existing repo: provide the absolute path (e.g. /Users/bluelobster/projects/foo)
   - New repo: provide the parent directory and I will run git init
   - Remote only: provide the clone URL and I will clone it

3. **Output location** — Where should PROJECT.md, KEY.md, and related plan files be
   written? (Default: the repo root — just say "repo root" if that works.)

4. **What it does** — One or two sentences: what does this project do, and for whom?

5. **Tech stack** — Languages, frameworks, major libraries, infra (e.g. "Python + FastAPI,
   Postgres, deployed on Fly.io").

6. **Hosting & serving** — Where will it run in prod? How do users reach it?

7. **Key constraints** — Any hard non-negotiables? (e.g. "no external API calls",
   "must run offline", "human always approves before any write")

8. **Existing code?** — Is there already code in the repo I should read before planning?
   If yes, name the most important files or directories (I'll send a scout to read them).

9. **AI/ML pipeline?** — Does this project include a measurable AI or ML pipeline
   (e.g. model calls whose output quality can be scored)? Yes / No.
   If yes, what is the metric or signal we'd optimize?

10. **Anything else** — Deadlines, team size, known risks, prior attempts, or anything
    else I should factor in.
```

Wait for Asher's reply before proceeding.

---

## Phase 2 — Scout (if existing code)

If Asher named existing files or directories in question 8, dispatch a scout sub-agent
before writing any plan:

```
Task: Read and summarize the existing codebase for planning context.
Location: <files/dirs Asher named>
Context: Planning a new project called <name>. Need to understand current structure
         before writing PROJECT.md.
Done looks like: A condensed summary — folder structure, key entry points, major
                 dependencies, and any gotchas visible in the code. Under 400 words.
Rules: Read only, no edits. Condense ruthlessly.
Completion message: Summary of findings, condensed.
```

Hold the scout's summary. Do not print it to Asher — use it when writing the plan.

---

## Phase 3 — Resolve the repo

Based on Asher's answer to question 2:

- **Existing repo:** verify it is a git repo with `git status`.
- **New repo:** `mkdir -p <path> && cd <path> && git init`.
- **Remote URL:** `git clone <url> <local-path>`.

Confirm the repo path to Asher in one line before proceeding.

---

## Phase 4 — Run the planning process

Load `/Users/bluelobster/skills/plan/PLANNING.md` and follow it exactly, using:

- The intake answers as the project brief (no need to ask Asher again).
- The scout summary (if any) as additional context for the sub-agents.
- The output location from question 3 as the destination for all generated files.

Pass the full intake context inline to each sub-agent — they do not read CLAUDE.md.

---

## Phase 5 — Confirm completion

After PROJECT.md, KEY.md (and AUTORESEARCH.md if applicable) are written and committed,
tell Asher:

> Plan complete. Files written to <output location>:
> - PROJECT.md — project overview, features, worktrees, tests
> - KEY.md — session routing index
> (If applicable:) AUTORESEARCH.md config block added to PROJECT.md §8
>
> Run /handoff at any time to pass context to a new chat.
> Start a feature by telling me which feature ID to work on first.

Nothing else. Do not summarize the plan contents — they are in the files.
