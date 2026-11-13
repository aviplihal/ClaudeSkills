---
name: harness-dashboard
description: >
  Set up and run a read-only status dashboard for an agent harness (a Claude Code project
  that runs agents, tools, or MCP servers) so the owner can tell in under two minutes whether
  it is doing what they wanted. Trigger on "set up a dashboard for my harness", "is my harness
  working", "harness dashboard", "monitor this agent", "watch this pipeline", "how do I know
  my agent is doing its job", "add monitoring to this harness", or any request to check,
  verify, or watch a Claude Code agent setup. The skill reads the harness (not its data),
  proposes independent checks, installs hooks, has the owner approve, fault-injects the
  dashboard, then starts the collector and a localhost server. It never claims the harness
  or its data is compliant or safe.
---

# Harness Dashboard Skill

Builds a dashboard for one harness. Source of truth for requirements is `PLAN.md` (v9); module
names and signatures are in `INTERFACES.md`; the Claude Code facts this skill relies on were
checked in `references/verify.md` (read it before writing any hook JSON). The code lives in
`scripts/hd/` (Python 3.11+, stdlib only). Paths below are relative to this skill's folder.

The procedure is goal-first. Do the phases in order. Do not start the collector or tell the
owner the dashboard is trustworthy until Phase 8 passes.

## Ground rules (read first)

1. **Read the harness, never its data.** Read prompts, `CLAUDE.md`, `.claude/`, `.mcp.json`,
   config and code. Never open the data folders, drop folders, outputs, logs or transcripts for
   content. Listing file names and counts is allowed; reading contents is not. This holds in
   every mode.
2. **Security comes from the wall; the dashboard is a window.** Hooks run inside the wall, so
   their events are agent-side and can be forged or suppressed. Only the collector, heartbeat,
   wall check, log chain and independent checks are vouched for from outside.
3. **Silence is no-data, never green.** Agent-claimed signals are never green alone.
4. **Mode is required.** Ask for `standard` or `strict`. If unset, the harness is treated as
   strict and the dashboard says "mode not set" in amber. Strict means: no content capture,
   localhost only, no remote MCP servers, paths and task text hidden or shortened. It does not
   make any data OK to send.
5. **Never write** into any config, UI string, summary or message to the owner: "compliant",
   "CMMC compliant", "safe", "intact", "no CUI", "meets 3.x.x", "sandbox intact". Say what was
   observed. A clean scan reads "no markings found in N scanned items (M not scannable)". The
   "Control mapping" link is the only CMMC reference. Screening is always "your statement,
   not checked". Logs are "tamper-evident, not tamper-proof"; deletion is "deleted, not wiped".
6. **Do not commit, publish or host** a dashboard that has real data. Mockups use fake data.
7. Do not edit the harness's wall, mounts, credentials or settings without the owner saying so
   for that specific change. Show the exact change and wait.

## Phase 1: Restate the goal as a success condition

Ask the owner what the harness is for. Reply with one sentence in the form "The harness
succeeds when <observable result> by <time or trigger>; it fails when <observable bad
result>." Get a yes before continuing. If the goal is open-ended (a chat), say now that it may
have no independent check (Phase 4).

## Phase 2: Read the harness and classify its shape

Read only prompts, config and code. Record, in a short working note (not in the repo):
- Shape: **pipeline** (batch run with stages), **tool server** (MCP server the agent calls),
  **daemon** (long-running, schedule), or **chat** (interactive). Say which and why.
- Parts: stages or tools, what each produces, where outputs land, what runs it and when,
  which MCP servers (local stdio or remote), which hosts it reaches, what data sources it
  reads, which `.claude/settings.json` applies.
- Data sources: the screened drop folder(s) the harness is meant to read. Flag anything else
  it can reach (other mounts, sync folders, env vars, git history, wider MCP access). Those are
  exposure to list, not data to read.

## Phase 3: What would working versus silently failing look like?

For each part, write two lines: what the owner would see if it works, and what they would see
if it fails silently (wrong output that looks fine, stage skipped, tool never called, stale
result). The silent-failure line is where checks go.

## Phase 4: Propose independent checks (declarative library)

For each success condition, propose a check built from the `hd.checks` types (see
INTERFACES.md): `field_present`, `count_in_range`, `rederive`, `file_hash`, `cross_ref`,
`time_window`, `known_answer` (needs a review hash, below). Every proposal states, in plain language:
- **what** is checked and **against what independent source**;
- `independent_because`: why this is a different path from the tool, account and data the agent
  used (if you cannot say, the signal stays agent-claimed);
- `cannot_catch`: what the check misses;
- `how_to_break`: a concrete way to make the stage fail so the check must go red.

If nothing checkable is produced, say "no independent check possible", keep that signal
agent-claimed and give the owner the spot-check button. Free-form checks, `custom` and
`known_answer`, run code outside the wall and need the owner's explicit review. `custom` takes
`params.reviewed_hash` = sha256 of the script. `known_answer` takes `params.reviewed_hash` =
`hd.checks.known_answer_hash(cfg, params)` (sha256 of the argv plus the contents of every argv
element that is a file); compute it only after the owner has read the command and those files.
A mismatch reads "could not check: not reviewed". Both run with a minimal environment (PATH,
HOME, LANG, HD_OUTPUTS_DIR), but **network is not restricted in this build for free-form or
known_answer checks: review them for network use.** In strict mode the check's network use must be on the allowlist and it never logs fetched
content. The owner approves the list; they do not write it.

## Phase 5: Write harness.json

Create the state dir (default `~/.harness-dashboard/<name>/`, mode 0700, never inside a
Nextcloud, Dropbox, OneDrive, iCloud or Google Drive folder; `hd.util.in_sync_folder` warns)
and `harness.json` with the schema in INTERFACES.md: `name`, `mode`, `goal`, `channel_path`,
`state_dir`, `data_sources`, `wall`, `expected_run_by`, `stuck`, `retention`, `scan`
(extra patterns, e.g. program and customer names the owner supplies),
`transcript_cleanup_days` (the declared `cleanupPeriodDays`, Claude Code default 30),
`disk_encryption`, `dependencies`, `declared`, `signals` (the Phase 4 checks), `middle`
(panels: pipeline, tool_inventory, queue, data_store). Set `hook_settings_path`. Leave
`disk_encryption` null unless the owner states it. File mode 0600. `channel_path` must be the
one file the wall can write (in the shared folder). Load it with `hd.config.load` to confirm it
parses.

## Phase 6: Install the hook

Hooks are agent-side. Add `scripts/hd/hook.py` to the **harness's** `.claude/settings.json`
(show the diff and wait for a yes). Event names and fields were verified in
`references/verify.md`; use only those. Entries are event, then matcher group, then handler.
Merge into any existing `hooks` object; never replace other hooks.

```json
{
  "hooks": {
    "SessionStart":       [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "UserPromptSubmit":   [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "PreToolUse":         [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "PostToolUse":        [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "PostToolUseFailure": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "PermissionRequest":  [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "PermissionDenied":   [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "Notification":       [{"matcher": "permission_prompt", "hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "SubagentStart":      [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "SubagentStop":       [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "Stop":               [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "StopFailure":        [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 5}]}],
    "SessionEnd":         [{"hooks": [{"type": "command", "command": "python3 /ABS/hd/hook.py --channel CHANNEL --harness NAME", "timeout": 2}]}]
  }
}
```

Add `--capture-content` only in standard mode and only if the owner wants content logged
(default off). The marking scan runs inside the hook in every mode, capture on or off, on
`tool_input`, `tool_response`, `prompt`, `file_path` and `task`; the hook reports only pattern
and field names in `extra.scan`, never matched text. **Copy `scan.py` next to `hook.py`** (the
hook loads it from its own directory; without it every event says "scan unavailable in hook"
and the marking-scan line goes amber). For the owner's own markings (program or customer names)
write a JSON list of `{"name": ..., "regex": ...}` and append `--patterns FILE` to every hook
command. `/ABS` and `CHANNEL` are absolute paths the wall can reach; if the harness runs
in a container or VM, use the paths as seen from inside. Facts to keep in mind:
- Hooks must exit 0 and print nothing. Stdout on `SessionStart` and `UserPromptSubmit` is
  injected into the agent's context, and exit 2 on some events blocks the agent.
- `PermissionRequest` (instant) and `Notification` `permission_prompt` (about 6 s later) both
  mean "waiting on you". `StopFailure` ends a turn on an API error (shown as an error stop),
  and `PermissionDenied` (auto mode only) is a denied tool call.
- `PostToolUse` does not fire on failed calls; `PostToolUseFailure` does. A tool call with a
  `PreToolUse` and neither is denied, cancelled, or still running; the dashboard does not call
  that an error.
- Subagent tool calls carry `agent_id`; main-session calls do not.
- `disableAllHooks` in a settings file silences hooks, and the harness's own `.claude/settings.json`
  is hashed into the approval set so an edit marks the dashboard stale.

If the harness's settings are managed by someone else, stop and tell the owner; do not work
around it.

## Phase 7: Wall tier, honestly

Ask how the harness is isolated, then record `wall` in harness.json and tell the owner the
tier in plain terms:
- **VM (strong):** own kernel, snapshot and revert; allow only the API host, no shared folders
  beyond the drop folder. Setup is about one to two hours; give steps if asked. Set
  `wall.check_cmd` to a command run from outside that prints the VM's firewall/mount rules; its
  stdout hash is stored at approval and compared live (no `check_cmd`: running not verified).
- **Container (medium):** shares the host kernel; a careless mount (host folder, Docker socket)
  or privileged mode can let something out. `hd.wall` flags both. The network config is part of
  the approved hash, so Wall turns green only while running and matching it ("allowlist matches
  approved config"), never from a claim that the network is blocked.
- **Separate account (weak):** file-permission separation only. Shown amber "account separation
  only", network allowlist "not enforced". Add best-effort Claude Code deny rules as a backup,
  e.g. `Read(//abs/path/to/off-limits/**)` (a single leading `/` is not absolute). Tell the
  owner these cover built-in file tools and recognized `cat`/`head`/`sed`, not scripts that open
  files themselves; they are not a wall.
- **None:** the Security block shows no wall.
On Windows: check Hyper-V support; WSL2 mounts C: and runs Windows programs by default, so it is
weak until automount and interop are off. Never say the wall is "intact"; the dashboard reports
"config matches approval".

## Phase 8: Approve, then fault-inject

1. Show the owner the signal list (with `independent_because`, `cannot_catch`, `how_to_break`),
   the data sources, the mode, the hook JSON, the wall tier and the declared MCP tool files.
   For local stdio MCP servers, produce each `tools_file` from outside the wall by running
   `tools/list` against the server yourself (the docs give no hook or CLI route to tool
   definitions); remote servers are listed as "not observed".
2. Only after an explicit yes: `python3 -c "from hd import approval, config; approval.approve(config.load('harness.json'))"`
   (run with `scripts` on `PYTHONPATH`). This stores the hash set outside the wall and writes a
   records-log entry. Any later change to signals, verifier code, hook config, wall config or
   MCP tools forces re-approval and shows "stale".
3. **Fault injection before trusting it.** For every stage, break it as the check's
   `how_to_break` says and confirm the dashboard goes red (or the right state). Also:
   - edit one line in `events.jsonl`: the chain must show red "log chain BROKEN at line N";
     delete its last line: red too ("tail missing or changed"); purge refuses on a broken chain;
   - kill the collector: the dashboard must go grey "no data from collector" within 30 s;
   - run with no events: idle needs the "should have run by" time to turn amber.
   A check that never goes red is discarded. Undo each fault. Tell the owner what you broke.
   The suite (including `tests/test_fault_injection.py`, the real hook through to the verdict) is
   `python3 -m unittest discover -s tests`; the live tests above are yours to run.

## Phase 9: Start it

From `scripts` (outside the wall, as the owner's OS user):

```bash
python3 -m hd.collector --config ~/.harness-dashboard/NAME/harness.json
python3 -m hd.server    --config ~/.harness-dashboard/NAME/harness.json
```

Run each in its own terminal or a background task. The server binds 127.0.0.1, picks a random
port and prints one URL containing a session token in the fragment. Give that URL to the owner
once; do not paste it into logs, notes or commits. The page expires after 15 minutes idle; a new
link comes from restarting the server. The first screening statement is the owner's to confirm
on the page: it records "<owner> says they screened X on DATE", labeled "your statement, not checked".
If a compliance owner has agreed to the screening arrangement, record it with
`Records.compliance_note(who, when, covers)` using the owner's own words.

## How to read a result back to the owner

State what the bar says and what it cannot see. Example: "Green: 2 independent checks passed;
the harness may still be producing wrong output the checks cannot see (see 'cannot catch')."
Never promote agent-claimed to proven. "Check failed" and "could not check" are different.

## If a scan hit is real

A hit turns Security red with the pattern name, event ID and source; the matched text is not
stored. If the owner confirms it is real:
1. Stop the harness. Do not clean up or delete logs, and do not edit `events.jsonl`.
2. Tell the owner to inform whoever owns compliance at work now; whether it is reportable is
   their call, not the tool's.
3. The hit already paused the dashboard's retention purge and opened an incident note in the
   records log. Help fill it in (time, pattern, event ID, what was stopped, who was told, when).
4. The retention hold covers the dashboard's logs only. Claude Code transcripts are not held.
   Claude Code keeps its own transcript copy (plaintext under `~/.claude/projects/`) and its
   sweep deletes by `cleanupPeriodDays` (default 30). The dashboard cannot pause that sweep:
   say so, and copy the transcript out or raise `cleanupPeriodDays` for that project only if the
   owner approves.
5. Release the hold only on the owner's instruction (`POST /api/hold/release`, recorded).
The scan finds markings, not controlled data; unmarked export-controlled or proprietary data is
not found, and tool output is often scanned after it has already gone to the API. Say that.

## Control mapping

The dashboard serves `references/control-mapping.md` as a plain "Control mapping" page: no
badge, no score, no color. Link it; do not summarize it as a status. It is a design aid, not an
assessment.

## What this build does not do

- **Ask** (the read-only question box), the **phone view over VPN**, and **Make change** are
  not built. Standard and strict both serve localhost only.
- No **pre-read deny** hook or stop-the-run on a hit; the scan detects, it does not prevent.
- No OS-level observation of effects; the Effects block reads "not observed in this build".
- No adapters for harnesses other than Claude Code, and no browser terminal.
- It does not read data folders, encrypt logs, sanitize on delete, or verify the owner's
  screening. It does not stop what the API receives.
If the owner asks for one of these, say it is out of scope for this build and point to
`PLAN.md` build-order steps 6, 7 and 10.
