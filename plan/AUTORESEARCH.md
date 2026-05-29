# AUTORESEARCH.md — Universal Auto-Research Playbook

> A long-running optimization loop. A **grunt AI** makes one targeted change per experiment; a **review team** of senior LLM agents steers direction every N hours; an **evaluator** scores against a fixed benchmark. Universal across projects — plug in your runner host, eval host, and target metric.

---

## 0. When to Use

Trigger this playbook when:
- The project has a measurable pipeline (single scalar metric per run)
- A frozen benchmark of ≥ 60 diverse examples exists or can be built
- You want continuous improvement while away from the keyboard

If any is false, do not start. Build the benchmark first.

---

## 1. Roles

| Role | Where it runs | Job |
|---|---|---|
| **Grunt AI** | `<RUNNER_HOST>` (dedicated machine, GUI app preferred) | One fresh session per experiment. Reads `hypotheses_queue.md`, makes exactly one change to `target.<ext>`, writes `DONE` to `experiment_status.txt`. |
| **Orchestrator** | `<RUNNER_HOST>` (service, KeepAlive) | Drives the loop: feeds hypothesis → grunt → sync → evaluate → keep/revert → log. |
| **Watchdog** | `<RUNNER_HOST>` (every 60s) | Detects dead grunt process, relaunches, re-queues current experiment. |
| **Heartbeat** | `<RUNNER_HOST>` (every 10 min) | Writes timestamp to `<EVAL_HOST>:<EVAL_DIR>/heartbeat.txt`. Stale = something died. |
| **Review team** (3 agents, every N hours) | API calls from orchestrator | Trend Analyst, Hygiene Checker, Hypothesis Generator. See §5. |
| **Evaluator** | `<EVAL_HOST>` | Runs `evaluate.<ext>` against benchmark, returns one float. **Read-only — never modified.** |

`<RUNNER_HOST>` and `<EVAL_HOST>` may be the same machine, but isolating them is safer.

---

## 2. File Layout (on `<EVAL_HOST>:<EVAL_DIR>`)

```
<EVAL_DIR>/
├── target.<ext>            ← THE ONLY FILE THE GRUNT EDITS
├── evaluate.<ext>          ← READ-ONLY; protected by hygiene check
├── config.json             ← read, never edit
├── hypotheses_queue.md     ← review team writes; orchestrator pops
├── experiment_status.txt   ← grunt writes DONE; orchestrator polls
├── heartbeat.txt           ← runner-host writes every 10 min
├── STOP                    ← create this to halt the loop cleanly
├── benchmark/
│   └── <section>/001/ ... NNN/    ← each example: input + ground_truth
└── log/
    ├── history.md          ← append-only experiment log
    ├── best.<ext>          ← copy of best target.<ext> so far
    └── weekly/week_N.md    ← Sunday-cron Opus summaries
```

---

## 3. One Experiment Cycle

```
1. Check STOP file → exit cleanly if present
2. Pop next hypothesis from hypotheses_queue.md
3. Copy grunt prompt (hypothesis + target.<ext> path + DONE rule) to clipboard
4. Open fresh grunt session, submit, watch experiment_status.txt (timeout: 10 min)
5. rsync target.<ext> → <EVAL_HOST>
6. ssh <EVAL_HOST> "<run evaluate.<ext>>" → capture metric
7. Compare to current best:
     WIN  → update log/best.<ext>, log KEEP
     LOSS → rsync log/best.<ext> back as target.<ext>, log REVERT
8. Append result to log/history.md (format in §4)
9. Remove completed hypothesis from queue
10. Loop
```

**Win condition:** improvement ≥ `<METRIC_DELTA>` AND no single example regresses by more than `<MAX_REGRESSION>`. A change that improves 80 and regresses 5 is REVERT.

---

## 4. Log Format (`log/history.md`)

```markdown
## Experiment <N> — <YYYY-MM-DD HH:MM>

**Section:** <which part of the pipeline>
**Hypothesis:** <specific, testable prediction>
**Change:** <exact edit to target.<ext>>
**Metric before:** <value>
**Metric after:** <value>
**Decision:** KEEP / REVERT
**Learning:** <one sentence>
```

Hypothesis is logged before the result is known. Always.

---

## 5. Review Team (every N hours, parallel API calls)

| Agent | Input | Output |
|---|---|---|
| **Trend Analyst** | full `history.md`, current metric vs. baseline, last N hours of experiments | Trajectory analysis. Flags if stuck (no win in 30+ exps), suspicious jumps, regressions |
| **Hygiene Checker** | diff `target.<ext>` vs `best.<ext>`, diff `evaluate.<ext>` vs git HEAD, last 10 log entries | Verifies reverts actually happened, evaluator unmodified, log format intact. HALTS LOOP if evaluator changed. |
| **Hypothesis Generator** | full `history.md`, current `best.<ext>`, directions-to-explore-and-avoid from `PROJECT.md §8` | 5 ranked hypotheses written to `hypotheses_queue.md` |

Orchestrator drains the queue between reviews. If queue empties before next review, grunt generates its own (lower quality, fine as filler).

**Weekly cron (Sunday 00:00):** one Opus agent reads the full week of `history.md`, writes `log/weekly/week_N.md`. On return, you read N weekly files, not thousands of log lines.

---

## 6. Benchmark (most important upfront investment)

Per section being optimized:
- **Total examples:** ≥ 100 (or `<BENCHMARK_SIZE>`)
- **Split:** 60 train (used in loop) / 20 validation (checked at each review) / 20 holdout (never touched until end)
- **Diversity coverage** — document explicitly in `PROJECT.md §8`:
  - Simple cases and complex cases
  - Each geometry / data shape type the pipeline supports
  - Sparse and dense inputs
  - Clean and slightly noisy inputs
  - With and without optional annotations / fields

The grunt and the orchestrator never see ground truth. Only `evaluate.<ext>` does.

---

## 7. Runner Host Setup

```
Auto-login: ON
Energy: prevent sleep (system + display)
SSH: ON
Screen sharing: ON (for remote inspection)
Grunt app: in Login Items
Grunt app: auto-updates disabled (e.g. "update.mode": "none")
SSH key: passwordless to <EVAL_HOST>
```

Services as system-managed agents (launchd / systemd):

| Service | Behavior |
|---|---|
| Orchestrator | KeepAlive |
| Watchdog | every 60s |
| Heartbeat | every 10 min |
| Weekly summary | Sunday 00:00 cron |

---

## 8. Risk Mitigations

| Risk | Mitigation |
|---|---|
| Grunt crashes | Watchdog relaunches; re-queues current experiment |
| Runner reboots | All services KeepAlive; grunt in Login Items; auto-login on |
| Grunt update dialog | Auto-updates disabled |
| Experiment hangs (no DONE) | 10-min timeout; log TIMEOUT, revert, next hypothesis |
| Network blip | rsync retries 3× with exponential backoff before logging ERROR |
| Metric gaming | Hygiene Checker reviews target diff every review |
| Evaluator modified | Hygiene Checker diffs vs git HEAD; halts loop |
| Plateau (no win in 30 exps) | Trend Analyst flags; review team shifts focus to next section |
| Eval host down | Heartbeat alert; orchestrator logs ERROR and pauses |

**Remote kill switch:** `ssh <EVAL_HOST> "touch <EVAL_DIR>/STOP"`. Orchestrator checks at start of each cycle, finishes current experiment, exits cleanly.

---

## 9. Guiding Rules

1. **Never edit the evaluator.** If changed, the entire experiment is invalid.
2. **One change per experiment.** Multiple changes make causality impossible.
3. **Log hypothesis before result.** Always write prediction first.
4. **Clean revert.** Restore `target.<ext>` to exactly the previous working state, not a best guess.
5. **Across-the-board wins only.** Improvement on some examples with regression on others is REVERT.
6. **No CLI grunt sessions when a GUI subscription is in play** — CLI doesn't draw on the subscription quota.
7. **Optimize one section at a time** unless explicitly cleared — changes across sections interact and confound the metric.

---

## 10. Build Phases (when standing up auto-research for a new project)

| Phase | Duration | Deliverable |
|---|---|---|
| 1. Runner setup | 1 day | Auto-login, SSH, services, grunt configured |
| 2. Benchmark | 1–2 weeks | 100 diverse examples per section, organized, split documented |
| 3. Evaluator | 2–3 days | `evaluate.<ext>` scores against benchmark, returns float; baseline = Experiment 0 |
| 4. Orchestrator + watchdog + heartbeat + review cron + weekly cron | 2–3 days | All services running as managed agents |
| 5. Validation run | 48 hours | Run the full loop while present. Verify reverts are clean, reviews fire on schedule, heartbeat alerts work, kill switch works, history.md looks sane |
| 6. Depart | 1 hour | Heartbeat live, hypothesis queue seeded, kill switch saved, screen sharing accessible |

---

## 11. Monitoring While Away

- **Heartbeat:** `ssh <EVAL_HOST> "cat <EVAL_DIR>/heartbeat.txt"` → timestamp < 15 min old
- **Progress:** `ssh <EVAL_HOST> "tail -50 <EVAL_DIR>/log/history.md"`
- **Visual:** Screen sharing into runner host
- **Kill:** `ssh <EVAL_HOST> "touch <EVAL_DIR>/STOP"`
- **Weekly:** read `log/weekly/week_N.md` each Sunday

---

## 12. Project-Specific Config (fill in `PROJECT.md §8`)

```
<RUNNER_HOST>:        <hostname or IP>
<EVAL_HOST>:          <hostname or IP>
<EVAL_DIR>:           <abs path on eval host>
<ext>:                <py | js | ts | ...>
<METRIC_DELTA>:       <minimum improvement to KEEP>
<MAX_REGRESSION>:     <per-example regression that disqualifies a win>
<BENCHMARK_SIZE>:     <total examples per section>
<REVIEW_INTERVAL>:    <hours between review team runs>
Sections to optimize: <list>
```
