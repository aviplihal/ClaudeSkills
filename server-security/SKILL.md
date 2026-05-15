---
name: server-security
description: >
  Audit the security posture of Asher's production Linux server (Ubuntu 24.04 at
  goldlobster@100.117.45.128 — Cloudflare-tunneled server-stack + Tailscale-only AI gateway).
  Trigger this skill aggressively whenever Asher says anything in the neighborhood of
  "run a security check", "test the server", "audit the server", "verify security posture",
  "run the security checklist", "check the firewall", "check for drift", "is X exposed",
  "am I still secure", "did anything change on the server", "review the hardening",
  "check my containers", or any variation that implies inspecting listening ports, running
  containers, SSH/Tailscale state, Cloudflare Access, secrets hygiene, or systemd hardening
  on this server. Prefer triggering when in doubt — Phase 1 of this skill is completely
  read-only and cannot harm the server just by running. The skill runs a bundled script,
  interprets the output against an expected-state baseline, produces a severity-ranked
  report, and then waits for Asher's approval before fixing anything.
---

# Server Security Skill

This skill audits Asher's server in three strictly-separated phases:

1. **Phase 1 — Check.** Run `scripts/run_checks.sh`, interpret output, produce report.
2. **Phase 2 — Offer fixes.** Classify findings, present options, wait for approval.
3. **Phase 3 — Apply fixes.** One approved fix at a time, with impact reasoning.

Phases never overlap. Phase 1 is read-only. Phase 2 is a conversation. Phase 3 only runs
after explicit approval for the specific fix being applied in the specific session.

The mechanical work — all the `curl`, `ss`, `docker inspect`, `systemctl`, `find` calls —
lives in `scripts/run_checks.sh`. Your job when this skill is invoked is to run that script,
interpret its tagged output against `references/baseline.md`, apply the severity guide below,
and produce the structured report. Then stop.

## Execution environment

This skill lives at `/home/goldlobster/.claude/skills/server-security/` on the server
itself. If you're already on the server (working directory is under `/home/goldlobster`,
`hostname` confirms it), run the script via Bash directly. If you're on a remote machine,
wrap it in SSH:

```bash
ssh goldlobster@100.117.45.128 'bash /home/goldlobster/.claude/skills/server-security/scripts/run_checks.sh'
```

Detect which mode you're in before the first command and state it in your opening line so
Asher knows where things are executing.

---

# Phase 1 — Run Checks

## Step 1: Run the script

```bash
bash /home/goldlobster/.claude/skills/server-security/scripts/run_checks.sh
```

The script is read-only and safe to run any time. It emits tagged lines in the format:

```
LAYER|CHECK_ID|STATUS|DETAIL
```

`LAYER` is one of `L1` through `L10` (Cloudflare Access, Firewall/Ports, Services, Docker,
Application, Tailscale, Secrets/Git, Host Hardening, Systemd Hardening, Cloudflare Tunnel).
`STATUS` is `PASS`, `FAIL`, `WARN`, `INFO`, or `SKIP`.

The script deliberately does **not** assign severity. Severity is a judgment call based on
context — the same `WARN` might be a `Medium` today and a `High` tomorrow depending on what
the server is hosting. Severity is your job.

## Step 2: Read the baseline

Before interpreting the output, read `references/baseline.md`. It contains:

- The authoritative list of expected services, containers, and ports
- The severity anchors for common findings (e.g. Postgres on host = Critical)
- The list of **accepted risks** which must appear in the report under their own heading,
  never as failures

You need this file to distinguish genuine drift from noise. An `INFO` line showing a
listening socket on `127.0.0.1:8001` is expected and fine. The same line showing
`0.0.0.0:8001` is a **Critical** finding. The script can't make that call — you can.

## Step 3: Assign severity

| Severity     | Use when                                                                 |
|--------------|--------------------------------------------------------------------------|
| **Critical** | Actively exploitable; direct data loss or full compromise risk           |
| **High**     | Significant exposure; easy to exploit with known techniques              |
| **Medium**   | Real risk but requires specific conditions                              |
| **Low**      | Defense-in-depth gap; minor hardening opportunity                        |
| **Info**     | Worth noting, no direct risk                                              |

Anchoring examples — calibrate against these when a finding is ambiguous:

| Finding                                              | Severity   |
|------------------------------------------------------|------------|
| Postgres listening on `0.0.0.0`                      | Critical   |
| SSH password auth enabled                            | Critical   |
| Unfamiliar key in `authorized_keys`                  | Critical   |
| `/docs` reachable publicly (not behind Access)       | High       |
| Unknown container running                            | High       |
| Unexpected port on `0.0.0.0`                         | High       |
| SSL cert expires in < 14 days                        | Medium     |
| FastAPI container running as root                    | Medium     |
| CLIENT_MAP mismatch between `.env` and container     | Medium     |
| Missing `X-Content-Type-Options` header              | Low        |
| `ai-gateway.service` missing `NoNewPrivileges`       | Low        |
| `apt list --upgradable` > 0, patches fresh           | Info       |
| `apt list --upgradable` > 0, patches > 14 days old   | Medium     |

When you're unsure between two severities, pick the higher one. The cost of Asher seeing
an over-flagged Medium is a two-second glance; the cost of under-flagging a real High is
a silent hole in the posture.

## Step 4: Produce the report

Produce the report as a **single block** at the end of Phase 1 — don't stream it out layer
by layer. Asher reads it as one scan.

```
## Security Check — goldlobster — <YYYY-MM-DD>

Overall: ✅ PASS | ⚠️ WARNINGS | ❌ FAILURES
Findings: <n> Critical · <n> High · <n> Medium · <n> Low · <n> Info

### Layer 1 — Cloudflare Access
✅ exercisecoachsp.blueoxai.com → 302 on /, /docs, /openapi.json
✅ investing.blueoxai.com → 302 on /, /docs, /openapi.json
✅ SSL cert expiry: 47 days

### Layer 2 — Firewall & Ports
✅ ufw active
✅ Port 8001 bound to 127.0.0.1 only
⚠️ [MEDIUM] Unexpected port 9999 open on 0.0.0.0 — process: <name>

### Layer 3 — Services
...

(one section per layer: Cloudflare Access, Firewall, Services, Docker, Application,
Tailscale, Secrets, Host Hardening, Systemd Hardening, Cloudflare Tunnel)

### Known Accepted Risks (not failures)
- FastAPI outbound internet via Docker NAT (intentional)
- Caddy/PostgreSQL on shared Docker bridge (until two-network split)
- Postgres password devpassword123 (no real client data yet)
```

**Formatting rules:**

- `✅` for pass, `⚠️` for warn, `❌` for fail, `❓` for unrunnable checks (script emitted
  `SKIP`, e.g. sudo required).
- Every `⚠️` and `❌` is prefixed with its severity in brackets: `⚠️ [MEDIUM] ...`.
- Overall status: `❌ FAILURES` if any Critical or High; `⚠️ WARNINGS` if any Medium or Low;
  `✅ PASS` if clean or only Info.
- One line per check, evidence inline (the port, mode, header, etc.).
- Accepted risks listed at the end, never counted as failures. If an accepted risk has
  *escalated* (e.g. real client data is now in the dev-password Postgres), that's a new
  finding — flag it separately per `references/baseline.md`.

---

# Phase 2 — Offer Fixes

After the report, read `references/fix-playbook.md` and write a single block like this:

```
---
<N> issues found. Want me to fix any of them?

Safe to auto-fix:
- <finding> — <one-line fix>
- ...

Needs discussion first:
- <finding> — <one-line reason the fix has impact>
- ...
```

The playbook has definitive classifications. The short version:

- **Safe to auto-fix**: file permission tightening, `.gitignore` additions, writing the
  SUID baseline (first run only). These don't restart anything or change any network path.
- **Needs discussion first**: anything that restarts a service, changes a network path,
  edits `/etc/ssh/sshd_config`, touches `.env`/`keys.json`/database state, or rotates
  a credential.

When a finding is ambiguous, default to **"needs discussion first"** and explain the
tradeoff. The cost of Asher saying "just do it" is ten seconds; the cost of an unintended
service restart or a locked-out SSH session is much higher.

After writing the Phase 2 block, **stop and wait**. Do not run anything else until Asher
replies.

---

# Phase 3 — Apply Fixes

Only enter this phase if Asher explicitly says to fix something. For each approved fix —
one at a time, never batched:

### 1. Restate

Say what you're about to do in one sentence, including the exact command(s).

### 2. Reason about impact

Write one short paragraph answering:

- Does this restart a running container or service? Which one, and how long is the outage?
- Does it change a network path (port, interface, firewall rule, DNS)?
- Does it touch a file another process has open?
- What's the rollback command if it goes wrong?

### 3. Apply or stop

- **If impact is zero** (file perms, gitignore, new baseline files): apply it, then verify
  with a read-only command that confirms the change took effect.
- **If impact is non-zero**: STOP. Do not apply. Instead say:
  > "This fix would <impact>. Safer alternative: <alternative>. How do you want to proceed?"
  > Then wait.

The fix playbook has suggested safer paths for most non-trivial findings. Use them.

### 4. Verify

After each fix, re-run **only the affected check**, not the whole script. Report the new
status of just the lines that changed. If the verification fails, stop immediately — don't
proceed to the next fix. A failed fix that cascades into another attempted fix is how small
problems become big ones.

---

# Operating principles

These aren't a list of `NEVER`s — they're the reasoning you apply to every action in this
skill. I'm writing them as principles rather than rules because a rigid list misses edge
cases; understanding *why* keeps you safe in situations the rules don't cover.

**Read-only until approved.** Phase 1 and Phase 2 don't mutate state, ever. The whole point
of a security audit is that it's cheap to run — if running it could break things, Asher
will stop running it, and then the server drifts silently. Protect that.

**Approval is per-fix, per-session.** "Yes, fix the permissions" authorizes *that* fix in
*this* session. It does not authorize the container restart you were going to propose
next, and it doesn't carry over to tomorrow.

**Impact reasoning before impact action.** Every fix that restarts a service, changes a
network path, or touches shared state gets one paragraph of impact reasoning *before* it
runs. The paragraph is cheap; the outage is not.

**SSH config changes require a recovery session.** Editing `sshd_config` without a second
SSH session already open is how people lock themselves out of servers permanently. If
Asher approves an `sshd_config` change, confirm he has a second session open *before*
touching the file. "I'll open one after" is not acceptable — the point is to have a
known-good session that survives the reload.

**Don't silently downgrade the security posture.** If a fix would weaken something (open a
port, relax a permission, disable a hardening directive), that's not a fix — surface it as
a question with the reasoning, and let Asher decide.

**Accepted risks are conditional.** The list in `references/baseline.md` is the canonical
set. If a condition changes — e.g., real client data starts flowing through the
dev-password Postgres — the acceptance no longer holds. Surface the change immediately
rather than continuing to treat it as accepted.

**Unfamiliar state is a question, not a warning.** If you see a SSH key you don't recognize,
an unexpected container, or a new listening port, *do not* silently classify it and move
on. Ask Asher. An attacker foothold looks exactly like a forgotten admin change — only
Asher can tell the difference.

---

# Repeat runs and drift

- **SUID baseline diffing.** If `suid_baseline.txt` exists in the skill directory, the
  script diffs against it. Surface any new or removed file as **Medium** with the diff
  inline. If the baseline doesn't exist, Phase 2 will offer to create it (first-run
  behavior).

- **Same-day terse mode.** If this skill ran earlier the same day, you can be terse — just
  the diff from the previous run's findings, with a timestamp reference. A full re-render
  of every passing check is noise when nothing changed.

- **Regression flagging.** If a finding was fixed in a previous run and has come back,
  flag it explicitly as **High** with "regression — previously fixed on <date>". A fix
  that didn't stick is a more interesting finding than a first-time failure because it
  means something is actively undoing the fix.

---

# Files in this skill

```
server-security/
├── SKILL.md                      this file (workflow + interpretation rules)
├── scripts/
│   └── run_checks.sh             the read-only check runner (also cron-safe)
├── references/
│   ├── baseline.md               expected state: ports, services, containers, risks
│   └── fix-playbook.md           classified fix commands for Phase 2/3
└── suid_baseline.txt             created on first approved run, used for drift diff
```

Progressive disclosure: `SKILL.md` is the entry point. The references are read on demand
when Phase 1/2/3 specifically need them. The script is executed, not read, on every run.
