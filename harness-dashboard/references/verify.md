# Verification of PLAN.md VERIFY items (build-order step 0)

Checked 2026-11-13 against the live Claude Code docs (fetched as raw markdown from
`https://code.claude.com/docs/en/<page>.md`; the `/en/hooks`, `/en/settings`, `/en/permissions`,
`/en/mcp`, `/en/claude-directory`, `/en/data-usage`, `/en/cross-session-messaging` pages all loaded).
Note: `/en/iam` now serves the Authentication page, not permissions; permission rules are on `/en/permissions`.
Statuses: confirmed / contradicted / not found in docs. Quotes are verbatim from the fetched pages.
Not checked: the Claude Code binary itself. Nothing here was tested by running a hook.

Base URLs: H = https://code.claude.com/docs/en/hooks , P = .../permissions , S = .../settings-reference ,
D = .../claude-directory , M = .../mcp , U = .../data-usage

## 1. Hook event names

| Question | Answer | Source | Status |
|---|---|---|---|
| PreToolUse exists | Yes | H#pretooluse | confirmed |
| PostToolUse exists | Yes, fires on success only | H#posttooluse: "Runs immediately after a tool completes successfully." | confirmed |
| Failure event | `PostToolUseFailure` exists | H#posttoolusefailure: "Runs when a tool that started executing fails: the tool threw an error, or an MCP tool returned an error result." | confirmed |
| Subagent START event | `SubagentStart` exists | H#subagentstart: "Runs when Claude spawns a subagent with the Agent tool, when Claude resumes a subagent, and each time an in-process agent team teammate handles a new message." | confirmed |
| SubagentStop | exists | H#subagentstop: "Runs when a Claude Code subagent has finished responding." | confirmed |
| Permission prompt signal | Two options. `PermissionRequest` fires at once; `Notification` with `notification_type` `permission_prompt` fires only after ~6 s | H#permissionrequest: "Use this event when you need a signal the moment Claude asks for permission to use a tool. Claude Code runs a Notification hook with the `permission_prompt` type only after the prompt has waited about six seconds." | confirmed (and better event exists) |
| SessionStart / SessionEnd | exist | H#sessionstart, H#sessionend | confirmed |
| Stop | exists; does NOT run on user interrupt; API errors fire `StopFailure` instead | H#stop: "Does not run if the stoppage occurred due to a user interrupt." | confirmed |
| UserPromptSubmit | exists; also fires on cron/`/loop` turns, background subagent reports, cross-session messages | H#userpromptsubmit | confirmed |
| Other events relevant | `PermissionDenied` (auto-mode denials only), `StopFailure`, `PostToolBatch`, `TaskCreated/Completed`, `PreCompact`, `FileChanged`, `ConfigChange`, `InstructionsLoaded` (33 total in the lifecycle table) | H#hook-lifecycle | informational |

Rejected-before-execution calls (unknown tool, schema-invalid input, permission denial) fire NEITHER PostToolUse nor
PostToolUseFailure: H#posttoolusefailure: "This event doesn't fire for tool calls rejected before execution ... Permission denials fire `PreToolUse` but not this event".

## 2. Payload field names

Common to all events (H#common-input-fields): `session_id`, `transcript_path`, `cwd`, `hook_event_name`,
plus `prompt_id`, `scratchpad_dir`, `permission_mode`, `effort` (not on every event). Status: confirmed.

| Field | Where | Status |
|---|---|---|
| `tool_name`, `tool_input`, `tool_use_id` | PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest, PermissionDenied. Quote: "PreToolUse hooks receive `tool_name`, `tool_input`, and `tool_use_id`." | confirmed |
| `tool_response` | PostToolUse only; schema depends on the tool (Write example: `{"filePath":..., "type":"create"}`). Quote: "The input includes both `tool_input`, the arguments sent to the tool, and `tool_response`, the result it returned." | confirmed |
| `duration_ms` | PostToolUse and PostToolUseFailure, optional | new, not in INTERFACES |
| `error` (string), `is_interrupt` (optional bool) | PostToolUseFailure. Quote: "`error` String describing what went wrong. The format depends on the tool that failed". Docs say key on `tool_name`, `is_interrupt`, and the `Exit code N` first line, treat the rest as display text | new |
| `mcp_server` `{name, source}` | PreToolUse/PostToolUse/PostToolUseFailure for MCP tools | new |
| `file_path` | `tool_input.file_path` for Write/Edit/Read, always absolute | confirmed. Quote: "`tool_input.file_path` is always absolute" |
| `description` for subagent task | Agent tool: `tool_input` has `prompt`, `description`, `subagent_type`, `model`. The tool is named **`Agent`** | confirmed |
| `agent_id`, `agent_type` | "`agent_id` and `agent_type` tell your script which agent a hook fired in". Present on SubagentStart/SubagentStop and on tool events that fire inside a subagent. H (hook locations): "When a subagent calls a tool, tool events such as `PreToolUse` and `PostToolUse` fire the same configured hooks as in the main conversation, and the input carries the `agent_id` and `agent_type` common input fields that identify the subagent." Main-session events omit `agent_id` (so None means main). `agent_type` is also set for the main agent when started with `--agent`, so do not use `agent_type` alone to detect a subagent | confirmed |
| SubagentStop extras | `stop_hook_active`, `agent_id`, `agent_type`, `agent_transcript_path` (subagent's own transcript in `subagents/`), `last_assistant_message`, `background_tasks`, `session_crons`. Fires also for Claude Code's internal agents (prompt suggestions, `/btw`); for those `agent_type` is the session's agent name or "" | confirmed |
| Notification | `message`, optional `title`, `notification_type` | confirmed |
| SessionStart | `source` ("startup","resume","clear","compact","fork"), optional `model`, `agent_type`, `session_title` | confirmed |
| SessionEnd | `reason` ("clear","resume","logout","prompt_input_exit","other"). Default timeout 1.5 s | confirmed |
| UserPromptSubmit | `prompt` | confirmed |
| Stop | `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons` | confirmed |

## 3. Does PostToolUse fire on failed calls?

No. Failures go to `PostToolUseFailure` (H#posttooluse: "For tool calls that fail, add the same hook under PostToolUseFailure.").
Status: confirmed, with one nuance: a user-cancelled tool fires neither ("Cancelling a running tool does not fire this hook").
A call that is denied or schema-rejected also fires neither. So `tool_pre` without a matching `tool_post`/`tool_error` is a real
state (denied, cancelled, hung, rejected) and the collector must not treat it as "error".

## 4. How a PreToolUse hook denies

Both work (H#pretooluse-decision-control):
- Exit 2: "A hook that blocks by exiting 2 routes the same way as "deny": Claude sees the stderr message as the denial reason." ("Exit 2 blocks even when your hook prints JSON.")
- Exit 0 plus JSON: `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`. Values: allow / deny / ask / defer. Top-level `decision`/`reason` are deprecated for this event.
- Precedence across hooks: `deny` > `defer` > `ask` > `allow`. Deny rules in settings beat a hook's "allow" (P, "Precedence among rules, hooks, and mods").
- Any other nonzero exit code is a non-blocking error: the action goes ahead.
Status: confirmed. Caveats for the later pre-read check (not in this build): PreToolUse does not fire for `@file` mentions in a prompt
("no PreToolUse hook fires for them, including hooks matching Read"), and a Read-matcher hook does not see `cat` (a Bash call).

## 5. Transcript location and cleanup setting

- Location: `~/.claude/projects/<project>/<session>.jsonl`; subagents under `projects/<project>/<session>/subagents/`; big tool outputs under `.../<session>/tool-results/`. D#cleaned-up-automatically table. The hook payload gives the path directly as `transcript_path`. Docs warn the file "is written asynchronously and may lag the in-memory conversation". Status: confirmed.
- Setting name: `cleanupPeriodDays`. S#cleanupperioddays: "**Type**: number of days, a whole number, minimum `1`. **Default**: `30`." "Setting `0` fails validation, so pick a large value such as `3650`". Scope: any settings file. Status: confirmed (name and default 30 days). `0` does NOT disable cleanup.
- Related: `desktopSessionCleanupPeriodDays` (Claude Desktop/Cowork sessions, default no limit).
- Stop writing transcripts: env var `CLAUDE_CODE_SKIP_PROMPT_HISTORY` ("to skip writing transcripts and prompt history in any mode"); `claude purge` deletes a project's state. D#plaintext-storage.
- Transcripts are plaintext, owner permissions only: D: "Transcripts and history are not encrypted at rest. OS file permissions are the only protection."
- Transcript content includes "the system prompt, tool definitions, and parameters of the requests Claude Code sent the model" (D table).
- The sweep: "Claude Code runs the deletion as a background sweep after a session starts"; so a transcript can outlive its period until the next session start. The Security block should say "deleted by Claude Code's sweep", not a guaranteed day count.
- Relevant to a scan-hit retention hold: the docs give no way to pause the sweep for one project except raising `cleanupPeriodDays` (user/project settings) or copying the transcript out. Mark as not found in docs.

## 6. Permission deny rule syntax for Read and Bash

P#permission-rule-syntax: rules are `Tool` or `Tool(specifier)`; deny is evaluated first across all scopes.
- Read: `"permissions": {"deny": ["Read(./.env)", "Read(./secrets/**)", "Read(//Users/alice/drop/**)", "Read(~/Documents/*.pdf)"]}`. Pattern types (gitignore syntax): `//path` absolute, `~/path` home, `/path` relative to the settings source (project root in project settings; **`~/.claude/` in user settings**), `path` or `./path` relative to cwd. Quote: "A pattern like `/Users/alice/file` isn't an absolute path."
- `Write`, `Glob`, `Grep` path rules do not match; use `Edit(...)` and `Read(...)` instead (P#write-glob-grep-path-rules-dont-match).
- Bash: `Bash(curl *)`, `Bash(npm test *)`; `*` wildcard on the whole command text; deny matches any subcommand of a compound command.
- Coverage of Read: P warning: "Read and Edit deny rules apply to Claude's built-in file tools, to file commands Claude Code recognizes in Bash, such as `cat`, `head`, `tail`, `sed`, and `tee`, and to the targets of Bash redirections ... They don't apply to ... arbitrary subprocesses that read or write files indirectly, like a Python or Node script that opens files itself." And "Claude makes a best-effort attempt to apply `Read(path)` deny rules to all built-in tools that read files like Grep and Glob."
- Bash deny is not a boundary: "a deny or ask rule covers the invocation Claude usually produces and isn't a security boundary around the program" (`Bash(curl *)` does not stop `/usr/bin/curl` or `sh -c 'curl ...'`).
- OS-level enforcement requires the sandbox (P#how-permissions-interact-with-sandboxing).
Status: syntax confirmed; "covers Read and Bash" is confirmed only as best-effort, not complete. On the weak wall tier the dashboard must label deny rules "best effort", never as a wall.

## 7. MCP tool definitions: hooks, and reading them without the agent

- Do hooks see tool definitions? No. Hook payloads carry only `tool_name` (`mcp__<server>__<tool>`, plugin servers `mcp__plugin_<plugin>_<server>__<tool>`) and `mcp_server: {name, source}`. No description or schema field is documented. Status: not found in docs (and the field lists above show it absent).
- MCP tool naming (H#match-mcp-tools): "MCP tools follow the naming pattern `mcp__<server>__<tool>`"; matcher `mcp__memory__.*`.
- Where local servers are configured (M): local/user scope in `~/.claude.json` under the project path; project scope in `.mcp.json` at the project root. "Stdio servers run as local processes on your machine."
- Discovery protocol (M#failed-discovery-requests): "After a server connects, Claude Code sends it capability discovery requests such as `tools/list`, `prompts/list`, and `resources/list`." Servers can change tools live via `list_changed` ("Claude Code fetches the updated list from that server").
- `claude mcp list` / `claude mcp get <name>` show connection status only. The docs do not say they print tool definitions. Status: not found in docs.
- Recommended way without the agent: the collector (outside the wall) reads the server's launch command from `.mcp.json` / `~/.claude.json`, spawns it itself (stdio) and sends JSON-RPC `initialize`, `notifications/initialized`, `tools/list`, then hashes the result. This is the MCP protocol call Claude Code itself makes (confirmed above) but is NOT a documented Claude Code feature; it only works for local stdio servers that start without side effects. Remote servers: cannot be hashed this way without their credentials; list as "not observed". The transcript also records tool definitions in the request parameters (D table) but that is agent-side data inside the wall.
- Also note `list_changed` means a hash taken at approval can go stale mid-session without any config change; hash again on each collector start/hourly.

## 8. Inbox-file-plus-hook alternative to tmux messaging

Mechanisms (all in H):
- `UserPromptSubmit`: plain stdout or `hookSpecificOutput.additionalContext` is "added to Claude's context alongside the submitted prompt". Also fires on cron/`/loop` turns and background-subagent reports. Default timeout 30 s.
- `SessionStart`: `additionalContext` "at the start of the conversation, before the first prompt".
- `Stop`: `hookSpecificOutput.additionalContext` or `decision:"block"` + `reason` makes the conversation continue so Claude acts on it; guarded by `stop_hook_active` and an 8-consecutive-continuation cap (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`). H#stop-decision-control.
- `PostToolUse` / `PreToolUse` also accept `additionalContext` (PreToolUse table) for mid-turn delivery.
- Each string capped at 10,000 characters; docs advise factual statements rather than imperatives.
- Limitation: delivery happens only when one of those events fires; nothing wakes a fully idle session (async hooks: "If the session is idle, the response waits until the next user interaction", except an `asyncRewake` hook exiting 2).
- Built-in alternative: cross-session messaging (Claude Code v2.1.224+; page `/en/cross-session-messaging`) lets Claude message other sessions on the machine; not needed for this build.
Status: confirmed. Inbox pattern is feasible: hook reads `<state>/inbox/<session>.md`, prints it as `additionalContext`, then renames it. Any hook that prints to stdout on an event that treats stdout as context pollutes the agent's context (see Impact).

## 9. Other facts the build depends on

- Hook config shape (H#configuration): `{"hooks": {"<Event>": [{"matcher": "...", "hooks": [{"type":"command","command":"...", "timeout": N, "async": true}]}]}}`. Three levels: event, matcher group, handler. Matcher omitted or `"*"` matches all.
- Notification matcher values: `permission_prompt`, `idle_prompt`, etc. (H#notification).
- Hooks run inside subagents too (see section 2).
- Hook edits in settings files are picked up by the watcher ("Direct edits to hooks in settings files are normally picked up automatically").
- `disableAllHooks: true` in a settings file turns off all non-managed hooks. A project `.claude/settings.json` can override a user-level value. So an agent with edit access to its own `.claude/settings.json` can silence the hooks; the approval hash of `hook_config` and the collector's silence detection are the right defenses (already in the plan).
- Hooks are agent-side, in the harness's environment; a hook process "inherits the parent environment".
- Exit code 2 on PostToolUse/PostToolUseFailure/Notification/SessionEnd/SubagentStart does not block anything; for SessionStart/SubagentStart/SessionEnd stderr goes to the user only.
- Plain stdout on exit 0 from `UserPromptSubmit` and `SessionStart` is injected into Claude's context. So `hook.py` must print nothing (INTERFACES already says this).
- SessionEnd timeout default is 1.5 s; hook.py must finish in well under that (single append, no heavy imports).
- Settings precedence: managed > command line > project local > shared project > user (S, settings page). `permissions.deny` lists merge across files.
- `transcript_path` for subagent events is the main session transcript; the subagent's own is `agent_transcript_path`.

## Impact on the build (corrections to INTERFACES.md, hook.py)

1. HOOK_MAP is keyed on `hook_event_name`, but Notification needs a second key. `Notification` -> if `payload["notification_type"] == "permission_prompt"` then `permission_pending` else `notification`. Do not assume every Notification is a permission prompt.
2. Add `PermissionRequest` -> `permission_pending` (fires the moment the prompt is shown). Its payload has `tool_name`, `tool_input`, `permission_suggestions` and NO `tool_use_id` (H#permissionrequest-input: "but without `tool_use_id`"), so `tool_use_id` is optional for this kind and the collector must not require it. Keep Notification/permission_prompt as a slower fallback (~6 s); to avoid double counting, treat a session as 'waiting on you' from either and clear it on the next tool_pre/tool_post/prompt/stop for that session.
3. `PostToolUseFailure` -> `tool_error` is correct and necessary. `PostToolUse` -> `tool_post` always `status="ok"` (it never fires on failure). `tool_error` gets `status="error"`; capture `error` (first line only, e.g. "Exit code 1") and `is_interrupt` into `extra`; do not store the full `error` string outside `content` (it can hold paths and output).
4. `SubagentStart` exists: the mapping in INTERFACES is right. Add: `agent_type` (put in `extra`), and on SubagentStop `agent_transcript_path` (extra) and `last_assistant_message` (content only). SubagentStop also fires for internal agents (empty `agent_type` possible); do not count those as subagents of the Sessions panel without a matching prior `subagent_start` for the same `agent_id`.
5. Subagent attribution: `agent_id` is present on tool events fired inside a subagent and ABSENT in the main session. Use `payload.get("agent_id")` for every event; `None` means main. Do not use `agent_type` as the subagent flag.
6. `tool_post` / `tool_error` and the missing-completion case: add handling for the collector "tool_pre without a post" (denied, cancelled, rejected pre-execution, or still running). The "denied" status can only be inferred from a permission denial in the transcript or `PermissionDenied` (auto mode only); recommend adding `PermissionDenied` -> `tool_error` with `status="denied"` (fields: `tool_name`, `tool_input`, `tool_use_id`, `reason`).
7. `Task/Agent description`: the tool is named `Agent` now. Match `tool_name in ("Agent", "Task")`; `description` is in `tool_input.description` (also `subagent_type`, `prompt`; `prompt` is content, do not copy it).
8. `file_path`: take `tool_input.file_path` (absolute for Read/Write/Edit). Other tools (Glob, Grep) use `path`/`pattern`, Bash has only `command`; no file_path for those. `Bash` `tool_input.command` is content (scan it, store only in content when capture is on).
9. `SessionStart.source`, `SessionEnd.reason`, `Stop.last_assistant_message`: put `source`/`reason` in `extra`; `last_assistant_message` is content. `Stop` does not fire on user interrupt or API error: add `StopFailure` -> `stop` with `status="error"` so a failed turn is not read as silence. Add to the `kind` set only if the schema owner agrees; otherwise map to `stop` with `extra.failure=true`.
10. Never print on stdout, always exit 0: confirmed required. Stdout on `UserPromptSubmit`/`SessionStart` is injected into the agent's context, and non-zero exits other than 2 are only warnings but exit 2 on `PreToolUse`/`UserPromptSubmit`/`Stop` would BLOCK the agent. Wrap `main()` in try/except and `sys.exit(0)`.
11. Settings snippet (the SKILL.md uses this): one matcher-group per event with `"matcher": "*"` for tool events, `"timeout"` set small (e.g. 5; SessionEnd needs the hook to finish in <1.5 s unless `timeout` is raised). `PermissionRequest` and `Notification` entries are matcher-less or `permission_prompt`.
12. `cleanupPeriodDays`: field `transcript_cleanup_days` in harness.json should be documented as the declared value of `cleanupPeriodDays`; default 30 when unset; minimum 1. The Security text for unset should read "Claude Code default: 30 days (not set by this harness)".
13. `approval.compute` mcp_tools part: the docs give no hook or CLI route to tool definitions. Hash declared `tools_file` contents (as designed); the file must be produced by running `tools/list` against the local stdio server from outside the wall (outside-the-wall helper), not copied from agent output. Note `list_changed` drift (re-hash periodically).
14. The `permissions.deny` weak-tier backup: document syntax `Read(//abs/path/**)`; leading single `/` in user settings is relative to `~/.claude/`; label as best-effort (`cat` recognized, Python scripts not).
15. Pre-read hook (later): note `@file` mentions bypass PreToolUse; set `CLAUDE_CODE_DISABLE_FILE_MENTIONS=1` or a Read deny rule.
16. Transcript retention hold: cannot pause Claude Code's sweep; say so in the incident procedure ("copy the transcript out before the next session start, or raise `cleanupPeriodDays`").
