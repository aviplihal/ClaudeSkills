# Harness Dashboard Skill: Plan (v9)

Status: v9 lets the model propose each harness's independent checks by reading the harness (Goal-first process, step 4), with guardrails so a model-written check is really independent. Before that, v8 added one recorded decision and one reworded goal to v7. (1) The compliance owner at work has agreed that data Avi screens as not-CUI may go to Claude, so Avi's screening is the sanctioned control. (2) The security goal is "built to support CMMC Level 2 practices", shown as a control mapping (Appendix A), never as a compliance claim. Work use is unlikely; the plan is sized for personal harnesses, with a short scope note for work. Claude Code, tmux, and Windows behavior in this plan comes from reviewers' own knowledge, not checked docs; items marked VERIFY must be checked against current docs before building on them.

## Problem
When I build an agent harness, I can't tell whether it is doing what I wanted or whether it is safe. I want a dashboard I can read in 30 seconds to 2 minutes (often on a phone) that tells me: is everything working, or is something wrong? It must work for any harness (car finder pipeline, CAD MCP server, etc.).

## Security goal: built to support CMMC Level 2 practices
**No compliance claim.** A tool cannot be CMMC compliant. CMMC certifies a contractor's own systems and practices; Level 2 is based on the 110 requirements of NIST SP 800-171 Rev 2. Those requirements protect CUI, and this dashboard is designed to hold none, so the standard is used here as a design benchmark, not an obligation. What the tool can do is make some of those practices easier to carry out and to show. Appendix A maps features to requirement families as supported / partial / gap / out of scope. The dashboard links to that mapping as a plain page: no badge, no score, no percentage, no color.

## Core principles
1. **Security comes from the wall (the sandbox). The dashboard is a window.** With a strong wall, a blinded dashboard is a quality problem, not a security problem. Anything let through the wall (API access, mounted folders, credentials) is still exposure and is listed.
2. **The dashboard reports what it observed, never what is true.** It never says "compliant", "CMMC", "meets 3.x.x", "safe", "no CUI", or "sandbox intact". Green means "every check I can run passed"; each block lists what it cannot see. A clean scan reads "no markings found in N scanned items (M not scannable)".
3. **Silence is no-data, never green.** The collector runs outside the wall and has its own heartbeat.
4. **Screening is mine; the tool backs it up.** My check of the data is the primary control, and at work it is the control the compliance owner agreed to. The tool keeps the screened boundary small, visible, and noisy when something crosses it. On screen, screening is always "your statement", never "checked".

## Data rule: screened before it goes in
**Recorded decision:** the compliance owner at work has agreed that data I screen as not-CUI may go to Claude. The tool stores this as a dated note (who agreed, when, what it covers) in the records log and shows it as "your statement". Still open: whether the agreement also covers unmarked export-controlled and customer-proprietary data (see open decisions).

My screening is a sound control for **what I hand over**. It does not cover **what the harness reaches by itself**, and that is where it realistically fails:
- **Reach beyond what I screened:** other files in the working folder or mounts, sync folders (Nextcloud), recent-file lists, git history, environment variables, an MCP server with wider access than the task needs.
- **Text I never looked at:** tool output, error messages and stack traces (full paths, part numbers, program names), filenames, CAD custom properties and title blocks that fill in automatically (contract numbers, distribution statements).
- **Content from outside:** scraped pages, emails, supplier documents the harness fetches.
- **Unmarked data:** "not CUI" is not the same as "not export-controlled". ITAR/EAR technical data and customer-proprietary data are often not marked CUI at all. Screening has to ask all three questions, and no scan can catch unmarked data.
- **Drift:** I screen once; the folder changes afterward. Screening is also done by one person, the builder, with no second check.
- **Second copies:** if a miss happens, the dashboard's logs and Claude Code's own transcripts hold a copy too.

Cheap backups (none of these is a compliance program):
1. **Screened drop folder as the only data source.** Each harness lists its data sources; the wall mounts only those (the existing C:\Transfer habit is this pattern). The mount list plus network allowlist *is* the allowlist; no separate mechanism. On the weak wall tier, add Claude Code permission deny rules as a backup (VERIFY rule syntax and that they cover Read and Bash).
2. **Screening statement with a dated record.** One line per harness: "Data sources: X. Avi says he screened these on DATE for CUI, export-controlled, and proprietary data." Labeled **your statement, not checked**. The collector counts files added or changed in those sources since that date and turns the line amber ("4 files changed since screening") until I re-confirm. One click, no forms. Each confirmation appends a record (time, OS user, sources, file count, hash of the file listing) to the records log, so the statement has a history rather than only a current value.
3. **Marking scan.** The collector scans captured text in memory (tool inputs/outputs, file paths, filenames) for banner-style markings: CUI, CONTROLLED UNCLASSIFIED, FOUO, ITAR, EAR, export controlled, 22 CFR, 15 CFR, USML, ECCN, DFARS 252.204-7012, Distribution Statement B through F, NOFORN, plus a per-harness list (program names, customer names). A hit turns Security red with pattern name, event ID, and source; the matched text is **not** stored. On by default for every harness.
4. **Pre-read check (optional, later).** A pre-tool hook scans a file for the same patterns before a Read and denies on a hit. This is the only safeguard that acts before the API sees the content (VERIFY that a pre-tool hook can deny; note that shell commands like `cat` bypass it).

Honest limits of the scan, shown on the dashboard: it finds markings, not controlled data; it cannot read images, PDFs without text, or CAD binaries (counted as "not scannable"); false positives happen (a document that merely discusses ITAR); and for tool output it usually fires **after** the content already went to the API, so it is a detector, not a preventer. It is also not a NIST SP 800-171 control; it is an extra detector that helps my screening.

**If a hit is real:** stop the harness, do not clean up or delete logs yourself, and tell whoever owns compliance at work. The tool helps in two ways: a hit **pauses retention deletion** for that harness until I release it (otherwise the 7-day purge would destroy the evidence I was told not to touch), and it opens a short **incident note** (time, pattern, event ID, what I stopped, who I told, when) saved to the records log. Find out now what compliance would want, before the first hit. (Reviewer's own knowledge: a spill of controlled data to an outside service may be reportable under contract or export rules; that is their call, not the tool's.)

## Strict mode
Strict mode is for harnesses on the work machine or with borderline-sensitive data. It reduces copies and surfaces; it does not make any data OK to send, and the name does not mean "approved for controlled data".

Strict changes exactly four things:
1. **No content capture.** Logs hold metadata only. The marking scan still runs in memory.
2. **Localhost only.** No phone view, no hosted copy.
3. **No remote MCP servers.** They are a third party beyond the API.
4. **File paths and task descriptions are treated as content** (hidden or shortened on screen, not logged in full).

Rules for the switch: mode is a required setting at setup. If it is missing, the harness is treated as Strict and the Security block says "mode not set" in amber. The setting lives outside the wall. Switching Strict to Standard needs my confirmation and is written to the records log. Setup has one rule in every mode: it reads the harness's own prompts, config, and code, which Claude Code already sees in that project, and never the data folders.

## Wall tiers
The Security block shows which tier a harness is on. It checks from outside that the wall is running and that its mount and network config match the approved hash. It reports "config matches approval", never "intact"; it cannot prove nothing escaped.
- **VM (strong):** own kernel, snapshot and revert. First setup is roughly one to two hours. The fiddly part is networking: allow only the API host, no shared folders beyond the drop folder, no stored credentials beyond what the harness needs.
- **Container (medium, fine for personal harnesses):** shares the host kernel; a careless mount (host folder, Docker socket) can let something out.
- **Separate Windows account (weak):** this is what the work CAD harness has today. It is file-permission separation, not a sandbox: same kernel, same network, shared folder. Shown as amber "account separation only", never green. The network allowlist is **not enforced** on this tier, so the deny-by-default line reads "not enforced". A Linux VM cannot run SolidWorks, so the strong option for the CAD harness is a Windows VM with its own SolidWorks install (license, GPU, and approval questions), or accepting the weak tier knowingly.
- **Windows caveats:** check the edition supports Hyper-V. WSL2 mounts C: and can run Windows programs by default, so it is weak until automount and interop are off. Docker Desktop runs inside a WSL2 VM; host mounts remain the weak point. Installing virtualization on a work machine may need approval.

## Logs and records
Two stores, both outside the wall, both owner-only file permissions, neither inside a synced or backed-up folder (setup checks the path against known sync folders and warns).
- **Event log** (what the harness did). The collector stamps each line with its own receive time; agent-side timestamps are kept but not trusted.
- **Records log** (what I decided): screening confirmations, approvals and re-approvals, mode switches, scan hits, incident notes, retention holds, the compliance-owner note. Each entry has time and OS user name. Small, kept indefinitely.

Both are append-only and **hash-chained**: each line carries the hash of the previous one, and the collector checks the chain at startup and hourly. A break shows red "log chain broken at line N". This is **tamper-evident, not tamper-proof**: anyone with my OS account can still rewrite the whole file, and the dashboard says so.

Retention (my judgment, configurable per harness; NIST SP 800-171 sets no number of days):
- **Metadata** (event types, tool names, timestamps, statuses, verdicts): about 90 days.
- **Raw content** (tool inputs/outputs): off by default; about 7 days if turned on; always off in Strict.
- **Claude Code's own transcripts** hold full content regardless of the dashboard's settings. Set their cleanup period per harness and show it in the Security block (VERIFY the setting name and default).
- Deletion at the end of retention is an ordinary file delete, **not sanitization**; the dashboard says "deleted, not wiped". A scan hit pauses deletion (see above).
- Logs are not encrypted by the tool. The Security block shows a declared line for host disk encryption (BitLocker, FileVault, LUKS): "on, your statement" or "not stated" in amber.
- Redaction of secrets at the collector is pattern-based and best-effort; the dashboard says so.

## Architecture: fixed shell + declarative middle
**Fixed shell** (built once, same for every harness): verdict bar, Security block, Effects block, Sessions panel.

**Generated middle:** a declarative JSON spec drawn by the fixed renderer, so it cannot repaint the shell. Panel types: pipeline, tool inventory (calls per tool, last used, error rate, never-called flag), queue, data store. No custom panels for now.

**Event path:** hooks run **inside** the wall, so hook events are agent-side data: useful, but forgeable or suppressible by a misbehaving agent. They cross the wall over one channel (an append-only event file or socket). The collector outside treats every line as untrusted input (schema check, size limit, never executed). What the outside can vouch for by itself is the heartbeat, silence, the wall config, the log chain, and independent checks of results. All events use one small JSONL schema, so a non-Claude-Code harness can be added later by writing an adapter; that is out of scope until the skill works on Claude Code.

## Goal-first process
1. I state the goal; the skill restates it as a success condition.
2. The skill reads the harness's prompts, config, and code (not its data), classifies its shape, and maps its parts.
3. For each part: what would I see if it is working versus silently failing?
4. Signals are tagged **independently checked** (deterministic code outside the model, looking at results; the only kind that counts as proof) or **agent-claimed** (never green alone). **The model proposes the independent check for each success condition by reading the harness** (its outputs, tools, data sources, and code); I approve the list and do not write it. For each proposed check the model states: what is checked, against what independent source, what the check cannot catch, and how to break the stage so the check should fail. Guardrails:
   - **Declarative first.** Checks are built from a small library of check types: field present, count in range, value re-derived from the original source, file exists and size or hash matches, cross-reference between two outputs, time window, known-answer replay. Free-form check code is the exception: it needs my explicit review, runs read-only on a copy of the outputs, outside the wall, with network only to declared hosts. Model-written code running outside the wall is itself a risk, which is why the library comes first.
   - **Independent means a different path.** A check is independent only if it does not use the same tool, account, or data path the agent used to produce the result. The model must say why it is independent; if it cannot, the signal stays agent-claimed.
   - **No artifact, no proof.** If the goal produces nothing checkable (for example an open-ended chat), the model says "no independent check possible", the signal stays agent-claimed, and the dashboard offers a spot-check button for me.
   - **Checks are tested too.** Each proposed check goes through fault injection (step 7) before it counts; a check that never goes red is discarded.
   - **Shown in plain language and hashed** into the approval set (step 6). Example for a car finder: each shortlisted car re-fetches its listing and compares price and specs to the requested spec. For a tool-server harness, an example is checking the file or output a tool call claims to have produced.
   - **Strict mode:** the check's own network use must be on the allowlist, and it never logs fetched content.
5. Events come from hooks and transcripts, not from the agent logging about itself. VERIFY hook names, payload fields, and transcript location.
6. I approve the signal list, the data sources, and the mode. Signal list, verifier code, hook config, wall config, and MCP tool definitions are hashed into the approval set, stored outside the wall; any change forces re-approval and marks the dashboard stale. Each approval is written to the records log with the old and new hash. VERIFY how to read tool definitions from a local MCP server without going through the agent.
7. Fault injection before trusting any dashboard: break each stage on purpose and confirm it goes red.

## Verdict bar rules
- One overall color (green / amber / red / grey-idle) with a one-sentence reason, plus two chips: **Goal** and **Safety**. Overall is the worse of the two, so a missing wall cannot hide behind a passing run and a red Security block does not hide whether the run worked.
- Per-run verdict ("last run passed, 3h ago") so finished runs don't go amber.
- Idle needs an expected "should have run by" time and a collector heartbeat, so idle can't mask a harness that never started.
- Every payload carries a server timestamp; the page shows data age and greys itself out when it cannot refresh.
- "Check failed" and "could not check" are separate states.
- Stuck thresholds are per harness. No-data is never green.

## Sessions panel
One row per running task: harness, subagent count (active/finished), what each is working on, last tool call, time since last event, status (working / waiting on you / stuck / idle / done). "What each is working on" and file paths are content, not metadata: hidden in Strict and on the phone. Stuck detection is rule-based, no model calls: no events for N minutes, repeated same call or error, permission prompt pending (its own status), same file edited repeatedly, subagent far outliving siblings, budget exceeded. VERIFY subagent-start hook, whether the post-tool hook fires on failed calls, and subagent attribution.

## Security block (fixed shell)
Every line is labeled as **observed**, **declared (unverified)**, or **your statement**.
- **Mode:** Standard or Strict, or "not set".
- **Wall:** tier, running or not, config matches approval or not, network allowlist enforced or not.
- **Data sources and screening statement**, with the changed-since-screening count and the date of the last record.
- **Marking scan:** hits, items scanned, items not scannable; retention hold on or off.
- **Declared** permissions, env vars, network hosts: neutral color, computed from the effective merged config. Processes inherit the full environment, so declared env is not the real env.
- **Observed-but-undeclared** hosts and tools, once observation exists.
- **Secrets in scope:** cannot be listed for remote MCP servers; says so.
- **Copies:** where logs, records, and transcripts live, how long they are kept, log chain status, host disk encryption (your statement).
- **Dependencies:** lockfile date and "last reviewed" date; amber after 90 days without review.
- **User:** "single-user tool; actions recorded under OS user NAME". Shared use is not supported.
- **Not observed:** a fixed line listing what this dashboard cannot see (what the API retains, unmarked controlled data, anything outside hooks).
- **Control mapping:** link to the Appendix A page.

## Security design
Still matters behind a strong wall:
- **Secrets and sensitive text in logs:** redact at the collector before writing; metadata by default.
- **Changed or malicious MCP tool definitions:** hash at approval, flag changes; pin packages with a hash lockfile; prefer stdlib-only servers. Pinning freezes known flaws along with everything else, so each review of the Dependencies line includes running a vulnerability check on the lockfile and re-pinning.
- **Unauthenticated reads:** per-session random token and Host/Origin checks on every endpoint, reads included (DNS rebinding). Localhost, random port, no CORS, vendored JS. The token is long and random, compared in constant time, never written to any log, and removed from the address bar after first load. After 15 minutes without activity the page blanks and needs a fresh link from the terminal. The token identifies a session, not a person.
- **Untrusted content:** logs, scraped pages, tool descriptions, and model output render as plain text under a strict CSP.
- **API data flow:** Claude Code sends prompts and file contents to the API, wall or not. It is handled by screening plus a small reach (the data rule above) and, at work, by the compliance owner's agreement. It is the largest data flow in the system and no dashboard feature changes it.
- **Phone (Standard only):** verdict and metadata, never content, no-store headers, VPN, read-only. Encryption on this path is whatever the VPN provides; the page says which VPN is declared.
- **Publishing:** a dashboard with real data is never published or hosted; mockups use fake data.

Matters less behind a strong wall (cheap defaults only):
- Agent tampering with its own events: the outside heartbeat, wall check, and independent checks cover the important part.
- tmux messaging is dropped; use an inbox file plus a hook (VERIFY).

## Ask and Make change
- **Ask** (read-only, no tools, available in both modes): deterministic checks run first for "why isn't this tool called?" (server connected? tool in the session's tool list? denied? name mismatch?). Sonnet then explains, labeled "seen in logs" versus "my inference", quoting its source line. It sees only what the log holds, which in Strict is metadata. Haiku is not trusted with absence-of-evidence questions. Ask costs tokens only when used.
- **Make change:** deferred. Use Claude Code itself to edit the dashboard. If built later: the editor sees click context, request, and middle spec, never raw logs; it emits a patch applied by deterministic code against a path allowlist; edits to harness files are a separate desktop-only step with confirmation.
- Right-click / long-press menu carries element IDs and metadata to Ask.

## Constraints
- The live view costs no tokens: it reads logs and file events and uses rule-based logic.
- Phone-first readability for the verdict bar and stage chips (Standard mode).

## Build order
The v8 additions ride inside existing steps (marked **new**); no step was added.

0. **Check the VERIFY items** against current docs (hooks and payloads, subagent events, transcript location and cleanup, permission rules, pre-tool deny). About half a day; the rest of the plan rests on them.
1. **Car finder, personal, Standard:** put it behind a wall (container or VM), collector outside, one event channel, metadata-only log, token on every request, localhost. Built together because adding the wall and outside collector afterward means redoing the event path. **New:** collector receive-time stamps; hash chain and owner-only permissions on the log; sync-folder check on the log path; token hygiene and 15-minute idle expiry.
2. Sessions panel, verdict bar with Goal and Safety chips, one independent check, heartbeat, idle and no-data states.
3. Fault-injection test. **New:** include "edit a log line" (chain must go red) and "kill the collector" (must go no-data).
4. Security block: wall tier and config check, declared-as-unverified, MCP tool-definition hashing, data sources with screening statement, marking scan. **New:** records log (screening confirmations, approvals, mode switches, hits, incident notes, with OS user); retention hold on a hit; Dependencies line; disk-encryption and User lines; Appendix A as a linked page.
5. Strict mode switch (four settings, required-at-setup rule, downgrade confirmation).
6. Phone verdict view over VPN, Standard only.
7. Read-only Ask with deterministic checks first.
8. A second shape (chat-style or daemon), then package as the skill: shape classification, approval flow, drift detection.
9. **Only if I decide to use it at work:** the CAD MCP harness (tool inventory panel) as the first Strict harness. Read the work scope note first; blocked on the work-only open decisions.
10. Later: pre-read check, stop-the-run on a scan hit, OS-observed effects, Make change, adapters for non-Claude-Code harnesses, browser terminal.

## If this is ever used at work
- **The company's scope, not mine.** A work install becomes part of the company's environment. Whether and how it is in the CMMC assessment scope is the compliance owner's call, and it would need to appear in their system security plan. Appendix A can feed that plan; it is not one.
- **Asset type.** With screening holding, the dashboard holds logs and configuration, not CUI. DoD CIO guidance treats systems that hold only security protection data (logs, configuration, passwords) as security protection assets. (Checked by the main session against DoD guidance; not re-checked in this review.) Whether this tool counts as one depends on whether the machine it watches is in the CUI environment at all.
- **If CUI were ever involved, stop.** The Claude API is an external cloud service. DoD CIO guidance says a cloud provider that processes, stores or transmits CUI must meet FedRAMP Moderate or equivalent under DFARS 252.204-7012; there is no registry, and the contractor evaluates the evidence. (Same basis as above.) Nothing in this dashboard satisfies that. Encryption protecting CUI would also need to be FIPS-validated (3.13.11), which this tool, a consumer VPN, and default disk encryption settings do not promise.
- **Export control is separate.** CMMC and CUI rules do not cover ITAR/EAR; unmarked technical data is the more likely miss.
- **CMMC rollout status: unverified.** One third-party trade site (govconinabox.com, last checked Nov 6 2026) says DoD suspended Phase 2 (C3PAO assessments) on July 13, 2026 while Phase 1 self-assessments and DFARS 7012 still apply. This was not confirmed on a DoD page. Do not plan around it; ask the compliance owner.
- **Revision note.** NIST's own Rev 2 document is marked withdrawn (May 14, 2024) and superseded by Rev 3 (seen on the NIST PDF). From my knowledge, not checked: CMMC Level 2 still assesses against Rev 2. Confirm before relying on requirement numbers.

## Open decisions for Avi
- **What exactly does the compliance owner's agreement cover?** CUI only, or also unmarked export-controlled (ITAR/EAR) technical data and customer-proprietary data? Which Claude account? Is it written down with a date? The tool stores whatever I enter as "your statement"; a written note from the owner is the real record.
- **Scan hit:** alert plus retention hold (v8 default), or also stop the run? What does work want done if a hit is real?
- Extra scan patterns per harness (program names, customer names, part-number formats).
- Confirm retention: 90 days metadata, content off (7 days if on), records log kept indefinitely.
- Independent checks are now proposed by the model per harness; the only decision left is approving each list. Which harness should be the first test of this?
- Phone access method for Standard harnesses (which VPN).
- **Work only:** wall for the CAD harness (stay on the separate Windows account, weak and amber, or move to a Windows VM; is Hyper-V available and approved?).

## What changed from v8
- **Independent checks are model-proposed, with guardrails.** Resolves the open decision "which independent check proves each harness's goal". Declarative check library first, free-form code only after my review; a check must use a different path than the agent; "no independent check possible" is a valid answer; each check is fault-injected before it counts.

## What changed from v7 (in v8)
- **Compliance-owner decision recorded.** The owner has agreed that data I screen as not-CUI may go to Claude. The v7 open decision "who at work knows / has agreed" is removed; what remains is narrower (does the agreement cover export-controlled and proprietary data, which account, is it written).
- **Goal reworded** to "built to support CMMC Level 2 practices", with an explicit no-compliance-claim note. "CMMC" and requirement numbers are added to the words the dashboard never uses as a status.
- **Appendix A added:** control mapping by NIST SP 800-171 Rev 2 family. It corrects the first-pass mapping: no family is fully "lined up"; the marking scan is not a System and Information Integrity control; deny-by-default holds only on VM and container tiers; Identification and Authentication, Media Protection, and flaw remediation were missing.
- **Cheap fixes added inside existing build steps:** records log with OS user (dated screening record, approvals, incident notes); hash-chained, owner-only logs kept out of sync folders; collector-side timestamps; token hygiene and idle expiry; retention hold on a scan hit (v7's 7-day purge contradicted "do not delete logs"); Dependencies review line; declared disk-encryption line; honest "deleted, not wiped" wording.
- **"Log retention" became "Logs and records".** States that 90 days is my choice, not a number from the standard.
- **Work use demoted.** The CAD harness moved from step 8 to an optional step 9; packaging as a skill no longer waits on it. New "If this is ever used at work" scope note (asset scope, FedRAMP-equivalent point, export control, unverified Phase 2 status, Rev 2 versus Rev 3).
- **Trimmed:** v6-history asides (the rename explanation, the cut list, the payload-signing note) removed.

## Appendix A: Control mapping (NIST SP 800-171 Rev 2)
How to read it. This is a design aid, not an assessment, and no row means "compliant". The requirements are written for systems holding CUI; this tool is designed to hold none. **V** = requirement wording checked in this review against the NIST SP 800-171 Rev 2 PDF (long requirements were checked as excerpts). **K** = from the reviewer's own knowledge, wording not checked. Which feature supports which requirement is the reviewer's judgment in every row; no assessor has looked at it.

| Family | Supported by | Partial | Gap | Out of scope (organizational) | Basis |
|---|---|---|---|---|---|
| 3.1 Access Control | Wall mounts and allowlist limit where data can flow (3.1.3). Page reachable only with the token, localhost (3.1.1). | Idle expiry gives session end (3.1.11) but not a pattern-hiding lock (3.1.10). Phone view is remote access (3.1.12, 3.1.13): encryption is the VPN's, not the tool's. External connections are listed, not controlled (3.1.20). | One token gives one level of access: no roles or least privilege (3.1.2, 3.1.5). No limit on failed attempts (3.1.8); a long random token is the substitute. | Who is an authorized user; OS screen lock; account management. | V |
| 3.2 Awareness and Training | None | None | None | Whole family. | K |
| 3.3 Audit and Accountability | Timestamped event log with retention (3.3.1). Heartbeat and "silence is no-data" alert on logging failure (3.3.4). Dashboard and Ask give reduction and reporting (3.3.6). | Tracing to a person (3.3.2): OS user name on records, single-user only. Log protection (3.3.8): owner-only files and a hash chain, tamper-evident only. Timestamps (3.3.7): collector-stamped, but syncing the host clock is the host's job. Hook events are agent-side and forgeable, which limits 3.3.1. | No separation between the person who runs the harness and the person who manages the logs (3.3.9). | Regular log review (3.3.3, 3.3.5); how long to keep logs (the standard gives no number). | V |
| 3.4 Configuration Management | Hashed approval set is a baseline for the harness (3.4.1). Change forces re-approval, logged (3.4.3). Wall with allowlist, no remote MCP in Strict (3.4.6, 3.4.7). | Hash lockfile restricts what the harness installs (3.4.8), for the harness only. | No security impact analysis step before a change (3.4.4); re-approval is where I would do it. | Baselines and inventory of company systems; OS hardening settings (3.4.2); user-installed software (3.4.9). | V |
| 3.5 Identification and Authentication | Token required on every request (3.5.2, for a session). Token never logged (3.5.10, in spirit). | Identifies a session, not a person or device (3.5.1). | No multifactor (3.5.3); it relies on the OS logon. | Password rules (3.5.7); MFA; account lifecycle. | V |
| 3.6 Incident Response | Scan hit goes red; incident note; retention hold. These support tracking and documenting (3.6.2). | None | None | The incident-handling capability itself, reporting to authorities, testing (3.6.1, 3.6.3). The tool only preserves and records. | V |
| 3.7 Maintenance | None | None | None | Whole family (3.7.1). | V for 3.7.1, else K |
| 3.8 Media Protection | Content capture off by default keeps content out of logs. Sync-folder check reduces stray copies and backups (3.8.9). | Owner-only permissions on logs (3.8.2). | End-of-retention deletion is not sanitization (3.8.3). The marking scan detects markings; it does not apply them. | Physical control of media (3.8.1); encrypted transport (3.8.6); disposal. | V |
| 3.9 Personnel Security | None | None | None | Whole family (3.9.1). | V for 3.9.1, else K |
| 3.10 Physical Protection | None | None | None | Whole family (3.10.1). | V for 3.10.1, else K |
| 3.11 Risk Assessment | None | Dependencies line prompts a vulnerability check on the lockfile (3.11.2), only when I run it. | None | Periodic risk assessment (3.11.1). | V |
| 3.12 Security Assessment | Fault injection is a small self-test of the tool. | Security block and this appendix can feed a system security plan (3.12.4). | None | Assessing controls, the plan itself (3.12.1, 3.12.4). | V |
| 3.13 System and Communications Protection | Deny-by-default network allowlist on VM and container tiers (3.13.6). Collector outside the wall, one channel across it (3.13.1, 3.13.2). Token plus Host/Origin checks (3.13.15). | Weak tier: allowlist not enforced. In transit (3.13.8): localhost traffic stays on the machine; the phone path depends on the VPN; API traffic is Claude Code's TLS, outside the tool. | Logs not encrypted at rest by the tool (3.13.16); relies on declared host disk encryption. No FIPS-validated cryptography (3.13.11). | Key management (3.13.10); network architecture (3.13.5); choosing validated crypto. | V |
| 3.14 System and Information Integrity | Observed-but-undeclared hosts and tools help spot unauthorized use (3.14.7), once observation exists. | Outbound monitoring (3.14.6) covers only the harness, and only at tiers where the wall can see traffic. Flaw remediation (3.14.1): Dependencies review line; pinning alone delays fixes. | None the tool should close. | Malicious code protection and scanning (3.14.2, 3.14.4, 3.14.5); watching security advisories (3.14.3). | V |

Not a mapped control: the **marking scan** and the **screening statement**. They are helpers for my own screening. The nearest requirement is controlling the flow of CUI (3.1.3), and a pattern scan that fires after content has left does not satisfy it.
