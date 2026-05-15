# Fix Playbook

Consulted during **Phase 2** (classifying findings into "safe to auto-fix" vs "needs
discussion first") and **Phase 3** (applying approved fixes). Not every finding will match
an entry here — for anything novel, default to "needs discussion first" and explain the
tradeoffs to Asher in prose.

Entries are organized by impact class, not by layer, because the question at fix time is
"what happens if I run this command" — and that's about impact, not about which check found it.

---

## Class A — No functionality impact (safe to auto-fix after approval)

These fixes don't restart any service, don't change any network path, and don't touch any
file another process has open. They can be applied directly once Asher says yes.

### Tighten file permissions

- **Findings**: `.env`, `keys.json`, `authorized_keys`, or `~/.ssh` has loose mode.
- **Fix**: `chmod 600 <file>` (or `chmod 700 ~/.ssh` for the dir)
- **Verify**: `stat -c '%a' <file>`
- **Rollback**: restore the old mode with `chmod <old> <file>` — read the old mode from the
  check output before running the fix.

### Add a pattern to .gitignore

- **Finding**: a sensitive file is untracked but not gitignored, so it's one `git add .`
  away from being committed.
- **Fix**: append the pattern (e.g. `.env`) to the repo's `.gitignore`.
- **Verify**: `git -C <repo> check-ignore <file>` exits 0.
- **Rollback**: remove the line. This edits a tracked file — there is no *state* impact, but
  the edit itself is visible to `git status`. Mention that to Asher so he knows to commit it.

### Write the SUID baseline (first-run only)

- **Finding**: `suid_baseline.txt` does not exist, so drift detection is disabled.
- **Fix**: `find / -xdev \( -perm -4000 -o -perm -2000 \) -type f 2>/dev/null | sort > /home/goldlobster/.claude/skills/server-security/suid_baseline.txt`
- **Verify**: `wc -l /home/goldlobster/.claude/skills/server-security/suid_baseline.txt`
  (should be > 0)
- **Rollback**: delete the file.
- **Note**: only safe to baseline if the current state is actually what Asher wants
  preserved. Before writing it, skim the file and confirm nothing looks out of place (new
  SUID binaries in `/home`, `/tmp`, or `/opt` are suspicious).

---

## Class B — Restart a running service (needs discussion first)

These fixes are correct but they restart or reload a running service. Never apply without
explicit approval for this specific change in this specific session.

### Add systemd hardening directives to ai-gateway.service

- **Finding**: `ai-gateway.service` lacks one or more of `NoNewPrivileges`, `ProtectSystem`,
  `ProtectHome`, `PrivateTmp`, `ProtectKernelTunables`, `ProtectKernelModules`,
  `ProtectControlGroups`, `LockPersonality`, `MemoryDenyWriteExecute`,
  `RestrictAddressFamilies`.
- **Ideal fix**: add a vetted block to `[Service]`:
  ```ini
  NoNewPrivileges=yes
  ProtectSystem=strict
  ProtectHome=read-only
  PrivateTmp=yes
  ProtectKernelTunables=yes
  ProtectKernelModules=yes
  ProtectControlGroups=yes
  LockPersonality=yes
  MemoryDenyWriteExecute=yes
  RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
  ReadWritePaths=/home/goldlobster/ai-gateway
  ```
- **Impact**: requires `systemctl daemon-reload` + `systemctl restart ai-gateway`. During
  the restart the gateway is briefly unreachable. `ReadWritePaths` is **required** because
  the service writes `usage.db`; without it, `ProtectSystem=strict` + `ProtectHome=read-only`
  will cause the service to fail on first write.
- **Safer path**: (1) edit the unit file, (2) `systemctl daemon-reload`, (3) `systemctl
  restart ai-gateway`, (4) immediately test: `curl -H "Authorization: Bearer <test-key>"
  http://100.117.45.128:11435/v1/models` — if it fails, revert the unit with
  `git diff`-tracked backup.
- **Rollback**: restore the previous unit file, `daemon-reload`, `restart`.

### Update a Docker container's restart policy

- **Finding**: a compose service is missing `restart: unless-stopped` or `restart: always`.
- **Ideal fix**: add the directive to `docker-compose.yml`.
- **Impact**: editing the compose file doesn't do anything by itself. Applying it requires
  `docker compose up -d <service>`, which recreates the container (brief outage).
- **Safer path**: wait for the next planned deploy window, or confirm Asher is OK with a
  ~5 second outage for the specific container.

### Cloudflare tunnel recovery

- **Finding**: tunnel not connected or errors in recent logs.
- **Ideal fix**: `docker restart cloudflared-tunnel` usually recovers transient issues.
- **Impact**: all public subdomains are unreachable for ~5-10 seconds while the tunnel
  reconnects.
- **Safer path**: before restarting, check the Cloudflare dashboard for the tunnel's health
  status. If Cloudflare already shows the tunnel as healthy, the issue is elsewhere (maybe
  the logs are just old). If it's genuinely broken, check whether the credentials file on
  disk has been touched — a missing or corrupted credentials file needs a re-auth, not a
  restart.

### Enable unattended-upgrades

- **Finding**: `unattended-upgrades` service inactive.
- **Ideal fix**: `sudo systemctl enable --now unattended-upgrades`
- **Impact**: from that point on, security updates install automatically overnight. Kernel
  updates require a reboot and won't auto-reboot unless explicitly configured. On this server
  (which hosts running services), Asher should choose this consciously.
- **Safer path**: ask before enabling. If Asher wants it, also discuss whether
  `Unattended-Upgrade::Automatic-Reboot` should be set.

---

## Class C — Network / firewall path changes (needs discussion first)

These change what can talk to what. A wrong change here can cut off access to the server,
expose a service, or break client traffic. Never apply without explicit approval.

### Unexpected listening port on a public interface

- **Finding**: `ss -tlnp` shows a port on `0.0.0.0` or a non-Tailscale interface that isn't
  22 or 80.
- **Ideal fix**: depends entirely on what the process is — kill it, reconfigure it to bind
  to loopback, add a ufw rule, or stop the service.
- **Safer path**: (1) identify the process with `ss -tlnp` and `ps aux`, (2) determine
  whether it's something Asher knows about, (3) if unknown, treat as potential compromise
  and investigate before killing.

### Postgres exposed on the host

- **Finding**: `docker ps` shows `0.0.0.0:5432` or `*:5432` for the postgres container.
- **Ideal fix**: remove the host port mapping from `docker-compose.yml`, then
  `docker compose up -d postgres`.
- **Impact**: restarts the postgres container. Any open connections drop. Any tooling that
  was using `localhost:5432` on the host breaks.
- **Safer path**: confirm no tool is using the host mapping (the FastAPI container talks
  over the bridge network, not the host port), schedule a short maintenance window.

### SSH config hardening (sshd_config)

- **Finding**: `PermitRootLogin yes`, `PasswordAuthentication yes`, or similar weakening.
- **Ideal fix**: edit `/etc/ssh/sshd_config`, set to the secure value, validate with
  `sudo sshd -t`, then `sudo systemctl reload ssh`.
- **Impact**: a typo or wrong value can lock Asher out of the server permanently.
- **Mandatory prerequisite**: **Asher must have a second SSH session already open** before
  touching this file. That session is the recovery path if the new config rejects future
  connections. Confirm the second session exists before editing; do not accept "I'll open
  one after" — the point is to have a known-good session that survives the reload.
- **Safer path**: (1) open second session, (2) edit config, (3) `sudo sshd -t`, (4) reload,
  (5) open a *new* test connection in a *third* session and verify login works, (6) only
  then close the original session.

### ufw rule changes

- **Finding**: ufw is missing a rule, or has an extra rule.
- **Ideal fix**: `sudo ufw allow/deny/delete <rule>`.
- **Impact**: can block the Tailscale interface, SSH, or the tunnel's traffic. A wrong rule
  here can also cut off the machine.
- **Safer path**: state the exact rule change in plain English, let Asher read it, get a
  yes, then run it. Never batch multiple ufw changes.

---

## Class D — Credential rotation (always needs discussion)

- **Postgres password rotation**: edit `.env`, recreate the postgres container with the new
  password, update any consumers. Complex; schedule a window. Do NOT attempt as a "fix" —
  present it as a project instead.
- **AI gateway API key rotation**: edit `keys.json`, restart `ai-gateway`, notify any
  consumers that the old key is gone. Same — this is a coordinated change, not a fix.
- **Cloudflare Access approved-email list**: cannot be changed from the server at all. This
  is a reminder: remind Asher to verify the approved list in the Cloudflare dashboard, and
  tell him the URL format (`https://one.dash.cloudflare.com/ > Access > Applications`).

---

## Quick classification cheat-sheet

When classifying a finding for the Phase 2 output block, ask:

1. **Does the fix touch a running process or network state?**
   - No → Class A (safe to auto-fix)
   - Yes → Class B, C, or D (needs discussion)

2. **Is there any recovery path if the fix goes wrong?**
   - No (e.g. sshd locks you out) → escalate to "mandatory prerequisite" wording
   - Yes → normal discussion

3. **Is the fix actually a multi-step project?**
   - Yes (credential rotation, database migration, two-network split) → present it as a
     project to plan, not a fix to apply

Default to "needs discussion first" when unsure. Asher approving a fix takes ten seconds;
an unintended outage takes much longer to diagnose and fix.
