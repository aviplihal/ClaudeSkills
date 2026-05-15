#!/usr/bin/env bash
# server-security skill — read-only check runner.
#
# Emits tagged lines in the format:
#   LAYER|CHECK_ID|STATUS|DETAIL
# where STATUS is one of: PASS | FAIL | WARN | INFO | SKIP
#
# This script deliberately does NOT assign severity. Severity is a judgment call
# based on context (the baseline, the accepted-risk list, how long the condition
# has persisted). The skill's SKILL.md consumes this output and applies severity.
#
# This script is read-only. It must not mutate any state on the server. It is
# safe to run from cron, by hand, or from the skill's Phase 1.

set -uo pipefail

emit() {
  # $1 layer  $2 check id  $3 status  $4 detail
  printf '%s|%s|%s|%s\n' "$1" "$2" "$3" "$4"
}

printf '# server-security check run\n'
printf '# host: %s\n' "$(hostname)"
printf '# date: %s\n' "$(date -Iseconds)"
printf '# user: %s\n' "$(whoami)"
printf '\n'

# ---------- Layer 1: Cloudflare Access ----------
for host in exercisecoachsp.blueoxai.com investing.blueoxai.com; do
  for path in '/' '/docs' '/openapi.json'; do
    code=$(curl -sS -o /dev/null -w '%{http_code}' \
      "https://${host}${path}" 2>/dev/null || echo "000")
    id="cf_access_${host}_$(echo "$path" | tr -c 'a-zA-Z0-9' '_')"
    status=FAIL
    [ "$code" = "302" ] && status=PASS
    emit L1 "$id" "$status" "http=${code}"
  done

  end=$(echo | openssl s_client -servername "$host" -connect "$host:443" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
  if [ -n "$end" ]; then
    end_epoch=$(date -d "$end" +%s 2>/dev/null || echo 0)
    now=$(date +%s)
    days=$(( (end_epoch - now) / 86400 ))
    emit L1 "ssl_expiry_${host}" INFO "days_remaining=${days}"
  else
    emit L1 "ssl_expiry_${host}" SKIP "could_not_fetch_cert"
  fi
done

# ---------- Layer 2: Firewall & Ports ----------
ufw_line=$(sudo -n ufw status 2>/dev/null | head -1 || echo "unavailable")
case "$ufw_line" in
  *active*)   emit L2 ufw_active PASS "$ufw_line" ;;
  *inactive*) emit L2 ufw_active FAIL "$ufw_line" ;;
  *)          emit L2 ufw_active SKIP "$ufw_line" ;;
esac

while IFS= read -r line; do
  [ -z "$line" ] && continue
  addr=$(echo "$line" | awk '{print $4}')
  emit L2 listen_socket INFO "$addr"
done < <(ss -tlnH 2>/dev/null || true)

# ---------- Layer 3: Services ----------
for svc in docker tailscaled ollama ai-gateway; do
  state=inactive
  systemctl is-active --quiet "$svc" && state=active
  enabled=disabled
  systemctl is-enabled --quiet "$svc" 2>/dev/null && enabled=enabled
  status=PASS
  [ "$state" = inactive ] && status=FAIL
  [ "$status" = PASS ] && [ "$enabled" = disabled ] && status=WARN
  emit L3 "service_${svc}" "$status" "state=${state} enabled=${enabled}"
done

# ---------- Layer 4: Docker stack ----------
if ! command -v docker >/dev/null 2>&1; then
  emit L4 docker_available FAIL "docker_not_found"
else
  expected="server-stack-fastapi-1 server-stack-postgres-1 server-stack-caddy-1 cloudflared-tunnel"
  running=$(docker ps --format '{{.Names}}' 2>/dev/null | sort)

  for name in $expected; do
    if grep -qx "$name" <<< "$running"; then
      emit L4 "container_${name}" PASS "running"
    else
      emit L4 "container_${name}" FAIL "not_running"
    fi
  done

  for name in $running; do
    if ! echo " $expected " | grep -q " $name "; then
      emit L4 container_unexpected WARN "$name"
    fi
  done

  for cid in $(docker ps -q 2>/dev/null); do
    cname=$(docker inspect --format '{{.Name}}' "$cid" | sed 's|^/||')
    priv=$(docker inspect --format '{{.HostConfig.Privileged}}' "$cid")
    user=$(docker inspect --format '{{.Config.User}}' "$cid")
    ro=$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$cid")
    restart=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$cid")
    emit L4 "container_${cname}_meta" INFO \
      "privileged=${priv} user=${user:-root} readonly=${ro} restart=${restart}"

    if [ "$priv" = "true" ]; then
      emit L4 "container_${cname}_privileged" FAIL "privileged=true"
    fi

    mounts=$(docker inspect --format '{{range .Mounts}}{{.Source}} {{end}}' "$cid")
    if echo "$mounts" | grep -q 'docker.sock'; then
      emit L4 "container_${cname}_dockersock" FAIL "mounts_docker_sock"
    fi

    img=$(docker inspect --format '{{.Image}}' "$cid")
    created=$(docker inspect --format '{{.Created}}' "$cid")
    emit L4 "container_${cname}_image" INFO "image=${img:0:20} created=${created}"
  done

  pg_host_bind=$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null \
    | grep postgres | grep -E '0\.0\.0\.0|^\*|:::' || true)
  if [ -n "$pg_host_bind" ]; then
    emit L4 postgres_host_binding FAIL "$pg_host_bind"
  else
    emit L4 postgres_host_binding PASS "not_exposed"
  fi

  sock_perms=$(stat -c '%a %U %G' /var/run/docker.sock 2>/dev/null || echo "unknown")
  emit L4 docker_sock_perms INFO "$sock_perms"

  env_map=$(grep '^CLIENT_MAP=' /home/goldlobster/server-stack/.env 2>/dev/null \
    | cut -d= -f2- || true)
  cont_map=$(docker exec server-stack-fastapi-1 printenv CLIENT_MAP 2>/dev/null || true)
  if [ -n "$env_map" ] && [ "$env_map" = "$cont_map" ]; then
    emit L4 client_map_match PASS "match"
  elif [ -z "$env_map" ] && [ -z "$cont_map" ]; then
    emit L4 client_map_match SKIP "not_set_in_either"
  else
    emit L4 client_map_match WARN "env_vs_container_drift"
  fi
fi

# ---------- Layer 5: Application (internal port, bypasses Cloudflare) ----------
#
# Routing is Host-based per client. Known routes per client:
#   exercisecoachsp.blueoxai.com → /exercises (tenant: ecsp)
#   investing.blueoxai.com       → /trades    (tenant: investing)
# /health is host-agnostic (liveness probe).
#
# check_app tests a (host, path) pair and a status family. It also scans the body
# for tracebacks and internal tenant id leakage — those are findings regardless
# of the status code.

check_app() {
  local id="$1" host="$2" path="$3" expect="$4"
  local body; body=$(mktemp)
  local code
  code=$(curl -sS -H "Host: ${host}" "http://127.0.0.1:8001${path}" \
    -o "$body" -w '%{http_code}' 2>/dev/null || echo "000")

  if grep -qiE 'Traceback|File "|line [0-9]+, in ' "$body"; then
    emit L5 "app_${id}_traceback" FAIL "python_traceback_in_body"
  fi

  # Tenant ID reflection: look for JSON fields that return the internal id in
  # the body. Naive word-grep is a bad detector because some internal ids (e.g.
  # 'investing') collide with natural English. Structured reflection is both
  # more precise and directly matches the CLAUDE.md rule that internal ids must
  # never appear in response bodies.
  leak=$(grep -oE '"(client_id|tenant_id|internal_id|client|tenant)"[[:space:]]*:[[:space:]]*"[^"]+"' \
    "$body" | head -1)
  if [ -n "$leak" ]; then
    emit L5 "app_${id}_internal_id_leak" FAIL "${leak}"
  fi

  local status=FAIL
  case "$expect" in
    200) [ "$code" = 200 ] && status=PASS ;;
    404) [ "$code" = 404 ] && status=PASS ;;
    4xx) [[ "$code" =~ ^4 ]] && status=PASS ;;
    5xx) [[ "$code" =~ ^5 ]] && status=PASS ;;
  esac
  emit L5 "app_${id}" "$status" "http=${code}"
  rm -f "$body"
}

# Liveness (host-agnostic)
check_app health_alive "exercisecoachsp.blueoxai.com" /health 200

# Tenant routing: known host + known tenant route → 200
check_app known_ecsp_route      "exercisecoachsp.blueoxai.com" /exercises 200
check_app known_investing_route "investing.blueoxai.com"       /trades    200

# Tenant isolation: unknown host on any tenant route → 404
check_app unknown_host_on_exercises "notarealclient.blueoxai.com" /exercises 404
check_app unknown_host_on_trades    "notarealclient.blueoxai.com" /trades    404

# Cross-tenant: ecsp host trying to reach investing's route should NOT succeed.
# Acceptable outcomes are 404 (route not mounted for this tenant) or 4xx. A 200
# here means the router is leaking routes across tenants — High severity.
check_app cross_tenant_ecsp_to_trades      "exercisecoachsp.blueoxai.com" /trades    4xx
check_app cross_tenant_investing_to_exercises "investing.blueoxai.com"    /exercises 4xx

# SQL injection in Host header against a routed path (so the payload actually
# reaches the routing logic rather than being stopped at a non-existent /).
check_app sqli_host_on_exercises "x'; DROP TABLE users;--" /exercises 4xx

# Missing Host header entirely (curl omits it with --header 'Host:')
code=$(curl -sS --header 'Host:' "http://127.0.0.1:8001/exercises" \
  -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
status=FAIL
[[ "$code" =~ ^(400|404) ]] && status=PASS
emit L5 app_missing_host "$status" "http=${code}"

# Response security headers (on a real routed response, not / which 404s)
headers=$(curl -sSI -H 'Host: exercisecoachsp.blueoxai.com' \
  http://127.0.0.1:8001/exercises 2>/dev/null || true)
for h in X-Content-Type-Options X-Frame-Options Content-Security-Policy; do
  if echo "$headers" | grep -qi "^${h}:"; then
    emit L5 "header_${h}" PASS "present"
  else
    emit L5 "header_${h}" WARN "missing"
  fi
done

# ---------- Layer 6: Tailscale & SSH keys ----------
if command -v tailscale >/dev/null 2>&1; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    emit L6 tailscale_peer INFO "$line"
  done < <(tailscale status 2>/dev/null || true)
else
  emit L6 tailscale_available FAIL "not_installed"
fi

if [ -f ~/.ssh/authorized_keys ]; then
  perm=$(stat -c '%a' ~/.ssh/authorized_keys)
  status=WARN
  [ "$perm" = "600" ] && status=PASS
  emit L6 authorized_keys_perms "$status" "mode=${perm}"
  while IFS= read -r key; do
    [ -z "$key" ] && continue
    fp=$(echo "$key" | ssh-keygen -lf - 2>/dev/null || echo "unparsed")
    emit L6 authorized_key INFO "$fp"
  done < ~/.ssh/authorized_keys
fi

ssh_dir_perm=$(stat -c '%a' ~/.ssh 2>/dev/null || echo "")
status=WARN
[ "$ssh_dir_perm" = "700" ] && status=PASS
emit L6 ssh_dir_perms "$status" "mode=${ssh_dir_perm}"

# ---------- Layer 7: Secrets & Git ----------
for repo in server-stack ai-gateway; do
  if [ -d "/home/goldlobster/${repo}/.git" ]; then
    tracked=$(git -C "/home/goldlobster/${repo}" ls-files 2>/dev/null \
      | grep -E '(^|/)\.env$|keys\.json$' || true)
    if [ -n "$tracked" ]; then
      emit L7 "git_tracked_secrets_${repo}" FAIL "$tracked"
    else
      emit L7 "git_tracked_secrets_${repo}" PASS "no_secrets_tracked"
    fi
    hist=$(git -C "/home/goldlobster/${repo}" log --all --full-history --oneline -- \
      .env keys.json 2>/dev/null | head -3 || true)
    if [ -n "$hist" ]; then
      emit L7 "git_history_secrets_${repo}" FAIL "secrets_in_history"
    else
      emit L7 "git_history_secrets_${repo}" PASS "clean_history"
    fi
  else
    emit L7 "git_repo_${repo}" SKIP "not_a_git_repo"
  fi
done

env_perm=$(stat -c '%a' /home/goldlobster/server-stack/.env 2>/dev/null || echo missing)
case "$env_perm" in
  600|400) emit L7 env_file_perms PASS "mode=${env_perm}" ;;
  missing) emit L7 env_file_perms SKIP "file_missing" ;;
  *)       emit L7 env_file_perms WARN "mode=${env_perm}" ;;
esac

keys_perm=$(stat -c '%a' /home/goldlobster/ai-gateway/keys.json 2>/dev/null || echo missing)
case "$keys_perm" in
  600|400) emit L7 keys_json_perms PASS "mode=${keys_perm}" ;;
  missing) emit L7 keys_json_perms SKIP "file_missing" ;;
  *)       emit L7 keys_json_perms WARN "mode=${keys_perm}" ;;
esac

if grep -q 'devpassword123' /home/goldlobster/server-stack/.env 2>/dev/null; then
  emit L7 postgres_dev_password INFO "accepted_risk_devpassword123"
fi

# ---------- Layer 8: Host hardening ----------
sshd_out=$(sudo -n sshd -T 2>/dev/null || true)
if [ -n "$sshd_out" ]; then
  for key in permitrootlogin passwordauthentication pubkeyauthentication \
             permitemptypasswords maxauthtries; do
    val=$(echo "$sshd_out" | awk -v k="$key" 'tolower($1)==k {print $2}' | head -1)
    emit L8 "sshd_${key}" INFO "${val:-unset}"
  done
else
  emit L8 sshd_config SKIP "sudo_required_or_unavailable"
fi

fails=$(sudo -n journalctl -u ssh --since '24 hours ago' 2>/dev/null \
  | grep -ciE 'failed password|invalid user' || echo "0")
emit L8 ssh_failed_logins_24h INFO "count=${fails}"

if [ -x /usr/lib/update-notifier/apt-check ]; then
  upd=$(/usr/lib/update-notifier/apt-check 2>&1 || echo "0;0")
  emit L8 apt_updates INFO "$upd"
fi

if systemctl is-active --quiet unattended-upgrades 2>/dev/null; then
  emit L8 unattended_upgrades PASS "active"
else
  emit L8 unattended_upgrades WARN "inactive"
fi

for k in kernel.randomize_va_space net.ipv4.tcp_syncookies \
         net.ipv4.conf.all.rp_filter net.ipv4.conf.all.accept_redirects \
         net.ipv4.conf.all.send_redirects; do
  v=$(sysctl -n "$k" 2>/dev/null || echo "?")
  emit L8 "sysctl_${k//./_}" INFO "$v"
done

suid_now=$(mktemp)
find / -xdev \( -perm -4000 -o -perm -2000 \) -type f 2>/dev/null | sort > "$suid_now"
baseline="/home/goldlobster/.claude/skills/server-security/suid_baseline.txt"
if [ -f "$baseline" ]; then
  diff_out=$(diff -u "$baseline" "$suid_now" | grep -E '^[+-][^+-]' || true)
  if [ -z "$diff_out" ]; then
    emit L8 suid_drift PASS "no_drift"
  else
    summary=$(echo "$diff_out" | head -5 | tr '\n' ';' | tr -s ' ')
    emit L8 suid_drift WARN "$summary"
  fi
else
  emit L8 suid_baseline INFO "baseline_missing"
fi
rm -f "$suid_now"

ww=$(find /etc /home/goldlobster/server-stack /home/goldlobster/ai-gateway \
  -xdev -type f -perm -0002 2>/dev/null | head -5 || true)
if [ -z "$ww" ]; then
  emit L8 world_writable_files PASS "none"
else
  emit L8 world_writable_files WARN "$(echo "$ww" | tr '\n' ';')"
fi

# ---------- Layer 9: Systemd hardening (ai-gateway) ----------
if command -v systemd-analyze >/dev/null 2>&1; then
  exposure=$(systemd-analyze security ai-gateway.service --no-pager 2>/dev/null \
    | grep -oE 'exposure level.*' | head -1)
  emit L9 ai_gateway_exposure INFO "${exposure:-unknown}"
fi

unit_file=/etc/systemd/system/ai-gateway.service
if [ -f "$unit_file" ]; then
  for d in NoNewPrivileges ProtectSystem ProtectHome PrivateTmp \
           ProtectKernelTunables ProtectKernelModules ProtectControlGroups \
           LockPersonality MemoryDenyWriteExecute RestrictAddressFamilies; do
    if grep -q "^${d}=" "$unit_file"; then
      emit L9 "unit_${d}" PASS "set"
    else
      emit L9 "unit_${d}" WARN "missing"
    fi
  done
fi

# ---------- Layer 10: Cloudflare Tunnel ----------
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx cloudflared-tunnel; then
  logs=$(docker logs --tail 30 cloudflared-tunnel 2>&1 || true)
  if echo "$logs" | grep -qiE 'Registered tunnel connection|connection.*registered'; then
    emit L10 tunnel_connected PASS "registered_in_recent_logs"
  else
    emit L10 tunnel_connected WARN "no_registered_connection_in_last_30_lines"
  fi
  if echo "$logs" | grep -qiE 'error|unauthori[sz]ed|failed to'; then
    emit L10 tunnel_log_errors WARN "errors_in_recent_logs"
  else
    emit L10 tunnel_log_errors PASS "clean"
  fi
  mounts_ro=$(docker inspect --format '{{range .Mounts}}{{.Destination}}:{{.RW}} {{end}}' \
    cloudflared-tunnel 2>/dev/null)
  emit L10 tunnel_mounts INFO "${mounts_ro:-none}"
  rp=$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' cloudflared-tunnel 2>/dev/null)
  status=WARN
  { [ "$rp" = always ] || [ "$rp" = unless-stopped ]; } && status=PASS
  emit L10 tunnel_restart_policy "$status" "$rp"
  nets=$(docker inspect --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' \
    cloudflared-tunnel 2>/dev/null)
  emit L10 tunnel_networks INFO "${nets:-none}"
else
  emit L10 tunnel_container SKIP "not_running"
fi

printf '\n# end of check run\n'
