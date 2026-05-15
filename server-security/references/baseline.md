# Server Security Baseline — Expected State

Authoritative reference for the `server-security` skill. Any deviation from what's listed
here is drift, and should be flagged according to the severity guide in `../SKILL.md`.

## Host

- Address: `goldlobster@100.117.45.128` (Tailscale, stable)
- OS: Ubuntu 24.04.x LTS
- SSH: key-only (no password auth)

## Systemd services — must be active AND enabled

- `docker`
- `tailscaled`
- `ollama`
- `ai-gateway`

Any of these inactive is a **High**. Any enabled-but-inactive (or active-but-disabled) is a
**Medium** — it means state has drifted from the intended configuration even if things happen
to work right now.

## Docker containers — must be running

- `server-stack-fastapi-1`
- `server-stack-postgres-1`
- `server-stack-caddy-1`
- `cloudflared-tunnel`

Any not running is **High**. Any unexpected container running is **High** until identified —
an attacker pivot would look exactly like this.

## Listening ports

| Port  | Interface             | Process        | If wrong                                 |
|-------|-----------------------|----------------|------------------------------------------|
| 22    | `0.0.0.0`             | sshd           | — (Tailscale ACL limits reach)           |
| 80    | `0.0.0.0`             | docker/caddy   | — (cloudflared needs this)               |
| 8001  | `127.0.0.1` only      | docker/fastapi | **Critical** if exposed beyond loopback  |
| 11434 | `127.0.0.1` only      | ollama         | **Critical** if exposed beyond loopback  |
| 11435 | `100.117.45.128` only | ai-gateway     | **High** if on `0.0.0.0`                 |
| 5432  | internal bridge only  | postgres       | **Critical** if on host                  |

Anything else listening on `0.0.0.0`, `*`, or `[::]` is drift: **High**, investigate before
reasoning about severity further.

Port 443 was intentionally removed — Cloudflare provides TLS, Caddy only speaks HTTP on
port 80 to the tunnel. If 443 shows up in `ss -tlnp`, that's drift (**High**).

## Public subdomains (Cloudflare Access protected)

- `exercisecoachsp.blueoxai.com` → internal id `ecsp`
- `investing.blueoxai.com` → internal id `investing`

Unauthenticated requests must get a `302` Cloudflare Access challenge. A `200` on any path
(`/`, `/docs`, `/openapi.json`) means Cloudflare Access is bypassed — **High**. On a new
subdomain being onboarded, escalate to **Critical** because the client hasn't yet audited
their data surface.

Internal IDs (`ecsp`, `investing`, and anything else in `CLIENT_MAP`) must never appear in
response bodies, response headers, or logs. A leak here is **High** — it maps a public
subdomain to an internal key, which is the first half of a tenant-boundary attack.

## Known accepted risks — do NOT flag as failures

List these in the report under "Known Accepted Risks", never as findings.

1. **FastAPI container has outbound internet via Docker NAT.** Intentional, unused today. If
   the report shows the container is *actually making* outbound connections we didn't expect
   (check `docker logs` or netstat inside the container), that's a new finding — don't swallow
   it under the accepted risk.

2. **Caddy and PostgreSQL share one Docker bridge.** Accepted until the two-network split is
   implemented. Postgres requires auth on that bridge. The mitigation is the auth — if the
   auth disappears (e.g. Postgres config gets a `trust` rule), the acceptance no longer holds.

3. **Postgres password is `devpassword123`.** Known weak. Acceptable because no real client
   data is in the database yet. **The moment real client data starts flowing, this becomes
   Critical** — surface it as such and ask if the password has been rotated.

## Authorized SSH keys

`~/.ssh/authorized_keys` should only contain keys Asher recognizes. The check emits each
key's fingerprint — if one is unfamiliar, do NOT silently flag it as a warning; ask Asher
about it directly. A key he doesn't recognize is a potential compromise and warrants
immediate attention (**Critical**).

## Git repos

- `/home/goldlobster/server-stack` — private GitHub origin
- `/home/goldlobster/ai-gateway` — private GitHub origin

Neither should have `.env` or `keys.json` tracked in the working tree or in history. If
either appears in history, the secret is considered compromised even if the repo is private:
rotation is required, not just a `.gitignore` update.

## File permissions

| File                                             | Expected mode |
|--------------------------------------------------|---------------|
| `/home/goldlobster/server-stack/.env`            | `600`         |
| `/home/goldlobster/ai-gateway/keys.json`         | `600`         |
| `~/.ssh/authorized_keys`                         | `600`         |
| `~/.ssh`                                         | `700`         |

Looser = **High** for the secret files, **Medium** for the SSH files. The asymmetry is because
the secret files contain credentials directly, while the SSH files are one hop removed.
