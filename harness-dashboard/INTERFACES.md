# harness-dashboard — build interfaces (v1 build)

Source of truth for requirements: `PLAN.md` (v9). This file fixes module boundaries so
parallel builders fit together. If PLAN.md and this file disagree on behavior, PLAN.md wins;
on names/signatures, this file wins.

## Scope of this build
Plan build-order steps 1–5 as a reusable, harness-agnostic package (plus tests and the
fault-injection suite of step 3). NOT in this build: Ask (step 7), phone/VPN view (6),
Make change, pre-read hook enforcement, adapters, actually walling a specific harness
(the skill's SKILL.md tells the user how; the code checks the wall from outside).

## Hard rules for all code
- Python 3.11+ **stdlib only**. No pip installs. Tests use `unittest` (`python3 -m unittest discover -s harness-dashboard/tests`).
- Package lives at `harness-dashboard/scripts/hd/` (import as `hd`; tests add `harness-dashboard/scripts` to `sys.path`).
- Comment the top of every file and every function (one line is fine).
- Never write the words "compliant", "CMMC", "safe", "no CUI", "sandbox intact", "meets 3." into any UI string or state field (Appendix A link text "Control mapping" is the only CMMC reference; tests grep for this).
- Never store the matched text of a marking-scan hit. Never log the session token.
- Any file the tool creates (logs, records, heartbeat, state) gets mode 0600, dirs 0700.
- Timestamps: ISO-8601 UTC with `Z`, from `hd.util.now()` (overridable in tests).
- Do not commit. Do not touch anything outside `~/Projects/ClaudeSkills/harness-dashboard/`.

## Directory layout per harness (outside the wall)
`<state_dir>/` (default `~/.harness-dashboard/<harness_name>/`):
- `harness.json` — config (below)
- `events.jsonl` — event log (hash-chained)
- `records.jsonl` — records log (hash-chained)
- `heartbeat.json` — collector heartbeat `{"ts":..., "pid":..., "chain_ok":bool, "chain_break_line":int|null}`
- `channel.offset` — collector's read offset into the channel file
- `approval.json` — approved hash set (written by `hd.approval`)
- `checks.json` — last independent-check results (written by `hd.checks`)
The **channel** (`channel_path` in config) is the one file the wall can write: hooks append JSONL there.

## harness.json (config)
```json
{
  "name": "car-finder",
  "mode": "standard" | "strict" | null,          // null/missing => treated as strict, "mode not set" amber
  "goal": "plain-language success condition",
  "channel_path": "/path/inside-shared-folder/events.channel.jsonl",
  "state_dir": "~/.harness-dashboard/car-finder",
  "data_sources": ["/abs/path/drop-folder"],
  "wall": {"tier": "vm"|"container"|"account"|"none", "container_name": "...", "config_files": ["..."], "allowlist_hosts": ["api.anthropic.com"]},
  "expected_run_by": "HH:MM" | null,              // daily "should have run by" (local time); null = no schedule
  "stuck": {"no_event_minutes": 10, "repeat_call_limit": 5, "same_file_edit_limit": 8, "subagent_outlive_factor": 3.0, "budget_tool_calls": 500},
  "retention": {"metadata_days": 90, "content_days": 7, "capture_content": false},
  "scan": {"extra_patterns": [{"name":"program X","regex":"..."}]},
  "transcript_cleanup_days": null,               // declared Claude Code cleanupPeriodDays
  "disk_encryption": "on" | null,                // your statement
  "dependencies": {"lockfile": "path", "last_reviewed": "YYYY-MM-DD"},
  "declared": {"permissions": [], "env": [], "hosts": [], "mcp_servers": [{"name":"x","remote":false,"tools_file":"path"}]},
  "signals": "checks spec, see hd.checks",
  "middle": {"panels": [ ... see hd.render spec ... ]}
}
```
`hd.config.load(path) -> dict` fills defaults and expands `~`. `hd.config.effective_mode(cfg) -> ("strict"|"standard", mode_set: bool)`.

## Event schema (channel + events.jsonl)
One JSON object per line, max 64 KiB per raw line (longer lines rejected, counted).
Required: `v` (=1), `harness` (str), `session_id` (str), `kind` (enum below), `agent_ts` (str, untrusted).
Optional: `tool_name`, `tool_use_id`, `agent_id` (subagent id or null for main), `status` ("ok"|"error"|"denied"|"pending"), `file_path`, `task` (description), `host`, `content` (dict: `input`, `output`, only when capture on and mode standard), `extra` (dict, small).
`kind` ∈ `session_start, session_end, prompt, tool_pre, tool_post, tool_error, subagent_start, subagent_stop, permission_pending, notification, stop, run_start, run_end`.
Collector adds: `recv_ts` (trusted), `event_id` (`<harness>-<monotonic int>`), and replaces `content` per mode/redaction. Strict: `file_path` and `task` stored as `{"hash": sha256[:12], "basename_len": n}`-style shortened form via `hd.redact.shorten_path`.

## Module ownership and API

### Builder A — storage core: `util.py`, `config.py`, `schema.py`, `chainlog.py`, `records.py`
- `util.now() -> str`, `util.set_clock(fn)`, `util.os_user() -> str`, `util.secure_write(path, text)`, `util.ensure_private_dir(path)`, `util.sha256_hex(bytes|str) -> str`.
- `util.SYNC_FOLDER_MARKERS` + `util.in_sync_folder(path) -> str|None` (Nextcloud, Dropbox, OneDrive, iCloud `Mobile Documents`, Google Drive, `CloudStorage`, Syncthing, Time-Machine-excluded is NOT checked). Returns marker name or None.
- `schema.validate(raw_line: str) -> (dict|None, error: str|None)` — size check, JSON parse, required fields, types, kind enum, strips unknown top-level keys into `extra`-free drop.
- `chainlog.ChainLog(path)`: `.append(obj: dict) -> dict` (adds `prev` = hash of previous line text, `h` = sha256 of canonical JSON of obj incl. prev; genesis prev = "0"*64), `.verify() -> (ok: bool, break_line: int|None)` (1-based), `.iter() -> iterator[dict]`, `.rewrite_without(predicate) -> int` (retention purge: rebuilds chain, appends nothing, returns removed count; writes a `chain_rebased` marker as first line noting removed count + old tail hash). Owner-only perms. `__init__` warns via `.warnings` list if path is in a sync folder.
- `records.Records(state_dir)` wraps a ChainLog on `records.jsonl`. Every entry: `{"type", "ts", "os_user", ...}`. Methods: `screening_confirmed(sources, file_count, listing_hash)`, `approval(old_hash, new_hash, parts: dict)`, `mode_switch(old, new, confirmed: bool)`, `scan_hit(pattern, event_id, source)`, `incident_note(fields: dict)`, `retention_hold(on: bool, reason)`, `compliance_note(who, when, covers)`, `latest(type) -> dict|None`, `all(type=None) -> list`.
- `records.hold_active(state_dir) -> bool` (last retention_hold entry on==True).

### Builder B — ingest: `hook.py`, `redact.py`, `scan.py`, `collector.py`
- `hook.py`: executable `python3 hook.py --channel PATH --harness NAME`. Reads one Claude Code hook JSON from stdin, maps `hook_event_name` → `kind` via a single table `HOOK_MAP` at top of file (PreToolUse→tool_pre, PostToolUse→tool_post, PostToolUseFailure→tool_error, SubagentStart→subagent_start, SubagentStop→subagent_stop, SessionStart→session_start, SessionEnd→session_end, UserPromptSubmit→prompt, Notification(permission)→permission_pending, Stop→stop). Copies `session_id`, `tool_name`, `tool_use_id`, `agent_id` if present, `tool_input.file_path` → `file_path`, Task/Agent `description` → `task`. Includes `content` only if `--capture-content`. Appends one line (O_APPEND, single write, truncated to 60 KiB) to channel. **Always exits 0 and prints nothing** (never blocks the agent); errors go to stderr only. Field names are VERIFY items: keep all payload-field access in one function `extract(payload)` so it is easy to correct.
- `redact.py`: `redact_text(s) -> (s, n_redactions)` for API keys (sk-, sk-ant-, ghp_, AKIA, xox*, Bearer tokens, `KEY=`/`SECRET=`/`TOKEN=`/`PASSWORD=` assignments, private-key blocks). `shorten_path(p) -> str` ("…/<last component truncated to 16>#<sha256[:8]>"). `redact_event(ev, mode, capture) -> ev`.
- `scan.py`: `DEFAULT_PATTERNS` list of `(name, compiled_regex)` covering PLAN.md list (CUI as a word/banner, CONTROLLED UNCLASSIFIED, FOUO, ITAR, EAR as banner-ish `\bEAR\b` uppercase only / "EAR99", export controlled, 22 CFR, 15 CFR, USML, ECCN, DFARS 252.204-7012, Distribution Statement [B-F], NOFORN). `Scanner(extra_patterns)`. `.scan_event(ev) -> list[{"pattern","event_id","source"}]` scanning tool inputs/outputs, file_path, task, filenames — **before** redaction/strip, in memory; `source` is the field name, never the text. `.counts -> {"scanned": n, "not_scannable": m, "hits": k}`; binary-looking content (NUL bytes, or file_path with extension in `.png .jpg .jpeg .gif .pdf .sldprt .sldasm .slddrw .step .stp .stl .dwg .dxf .zip`) counts as not_scannable.
- `collector.py`: `Collector(cfg)`. `.poll_once() -> dict stats` reads new channel lines from saved offset, validates (schema), stamps `recv_ts` + `event_id`, scans, on hit → `Records.scan_hit` + `Records.retention_hold(True, ...)` + opens incident note stub, redacts, writes to events ChainLog, updates scan counters in `<state_dir>/scan_counts.json`, writes heartbeat. `.verify_chains()` at startup and hourly (both logs) → heartbeat chain fields. `.purge()` retention: drop events older than metadata_days, strip `content` older than content_days, **skipped entirely if hold active**. `main()`: `python3 -m hd.collector --config harness.json [--once]` loop every 2 s. Rejected lines counted in heartbeat (`rejected`), never executed or echoed.

### Builder C — trust: `checks.py`, `approval.py`, `wall.py`, `screening.py`
- `checks.py`: declarative check library. A check spec: `{"id","description","type","params","independent_because","cannot_catch","how_to_break"}`. Types: `field_present`, `count_in_range`, `rederive` (re-read a value from the original source file/URL via a declared reader: `json_path` on a local file, or `http_get` + regex limited to `allowed_hosts`), `file_hash` (exists, size range, optional sha256), `cross_ref` (every id in output A appears in B), `time_window` (file mtime / field timestamp within N hours), `known_answer` (run a declared command on a fixed input, compare to expected; command must be in params, runs with `cwd` = a temp copy, timeout 60s). Free-form code type `custom` is **rejected unless** `params.reviewed_hash` equals sha256 of the script file. Spec missing `independent_because` → check is forced to `agent_claimed`. `run_all(cfg) -> list[{"id","state": "pass"|"fail"|"could_not_check","detail","ts"}]`, writes `<state_dir>/checks.json`. Never raises for a single check; exceptions → `could_not_check`.
- `approval.py`: `compute(cfg) -> {"parts": {"signals": h, "verifier_code": h, "hook_config": h, "wall_config": h, "mcp_tools": h}, "total": h}` (hook config = the `hooks` section of the harness's `.claude/settings.json` path given in `cfg["hook_settings_path"]`; verifier code = hashes of any `custom` scripts; mcp tools = hash of each declared `tools_file` contents). `approve(cfg)` writes approval.json and `Records.approval(old,new,parts)`. `status(cfg) -> {"approved": bool, "stale": bool, "changed_parts": [...]}`.
- `wall.py`: `check(cfg) -> {"tier", "running": bool|None, "config_matches": bool|None, "allowlist": "enforced"|"not enforced"|"unknown", "detail"}`. Container: `docker inspect <name>` via subprocess (timeout 10s), running = State.Running, config hash over Mounts + NetworkMode + HostConfig.Binds/Privileged/CapAdd compared to approval part `wall_config`; flag Docker socket mounts and privileged as detail. VM: declared only (running None unless `wall.check_cmd` given). Account: running None, allowlist "not enforced". None/missing: running False. Never says "intact".
- `screening.py`: `listing(sources) -> (file_count, listing_hash)` over relative path+size+mtime; `changed_since(cfg, records) -> int|None` (files with mtime > last screening ts, plus added/removed vs. count); `confirm(cfg)` → `Records.screening_confirmed`.

### Builder D — view: `state.py`, `server.py`, `static/index.html`, `static/app.js`, `static/style.css`
- `state.py`: `build(cfg, now=None) -> dict` (pure function of files in state_dir + config + checks/wall/approval results passed in or read from files). Returns:
  - `verdict`: `{"color": "green"|"amber"|"red"|"grey", "reason": str, "goal": {"color","reason"}, "safety": {"color","reason"}, "last_run": {"result","ago"}|null, "data_age_s": int, "server_ts": str}`. Overall = worse of goal/safety (red>amber>grey>green for "worse"; grey only if both grey/idle). No heartbeat or heartbeat older than 30 s → overall grey "no data from collector", never green. Goal is green only if ≥1 independent check passed and none failed; only agent-claimed signals → at best amber "agent-claimed only". "check failed" (red) ≠ "could not check" (amber).
  - `sessions`: list of rows `{"session_id","harness","subagents_active","subagents_done","working_on","last_tool","since_last_event_s","status"}` with status ∈ working / waiting on you / stuck / idle / done from rule-based detection (PLAN.md Sessions panel rules, thresholds from cfg.stuck). `working_on` hidden (`null`, `"hidden (strict)"`) in strict.
  - `security`: list of lines `{"key","label": "observed"|"declared (unverified)"|"your statement","color","text"}` covering every bullet in PLAN.md "Security block", in that order, including the fixed "Not observed" line and a "Control mapping" link line.
  - `middle`: the cfg.middle spec merged with computed data for panel types `pipeline`, `tool_inventory` (calls per tool, last used, error rate, never-called flag vs declared tools), `queue`, `data_store`. Unknown panel types → rendered as an "unsupported panel" notice, never executed.
  - `stale`: approval stale flag.
- `server.py`: `python3 -m hd.server --config harness.json [--port 0]`. Binds 127.0.0.1 only (strict and standard in this build). Random port by default. Generates 32-byte urlsafe token per process; prints the URL `http://127.0.0.1:PORT/#t=TOKEN` to stdout once (fragment, so it isn't in server logs/Referer); JS moves it to memory and `history.replaceState` removes it. Every endpoint, including static files and `/api/state`, requires `Authorization: Bearer TOKEN` **or** for the initial HTML load only a one-time `?t=`… — simplest correct approach: serve a tiny token-free bootstrap HTML at `/` that contains no data, then all data/assets go through `/api/*` with the bearer header (vendored JS inline in the bootstrap is fine). Compare with `hmac.compare_digest`. Check `Host` ∈ {`127.0.0.1:PORT`, `localhost:PORT`} and, if `Origin` present, it must match → else 403. Headers on every response: `Cache-Control: no-store`, strict CSP (`default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. No CORS headers. Idle expiry: if no authenticated request for 15 min, token invalidated; page shows "expired — get a fresh link from the terminal". Endpoints: `GET /api/state`, `GET /api/mapping` (Appendix A as plain text/markdown), `POST /api/screening/confirm`, `POST /api/hold/release`, `POST /api/approve` (desktop confirmation: requires JSON body `{"confirm": true}`), `POST /api/mode` (`{"mode":..., "confirm": true}`; strict→standard requires confirm, recorded). Never log the token; override `log_message` to drop query strings and auth.
- Front end: no CDN, no frameworks. Render all untrusted strings with `textContent` only (never innerHTML with data). Phone-first: verdict bar (big color + one sentence + Goal/Safety chips + data age; greys out if refresh fails or data_age > 30 s), then Sessions, Security, Effects placeholder ("Effects: not observed in this build"), middle panels. Poll `/api/state` every 3 s. Color is never the only signal (text labels too). Works at 360 px width.

## Tests (each builder writes tests for its own modules in `harness-dashboard/tests/test_<module>.py`)
Integration + fault-injection suite (`tests/test_fault_injection.py`) is written after merge, by the integrator.
