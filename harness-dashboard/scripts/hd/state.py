"""hd.state - pure builder of the dashboard payload from state_dir files, config and optional results.

Reads heartbeat.json, events.jsonl, records.jsonl, checks.json, approval.json, scan_counts.json.
Reports what was observed; never claims anything is true. Stdlib only.
"""
import json
import os
import statistics
from datetime import datetime, timedelta, timezone

HEARTBEAT_MAX_AGE_S = 30            # heartbeat older than this means no data from the collector
RANK = {"green": 0, "grey": 1, "amber": 2, "red": 3, "neutral": -1}
MAX_TAIL_BYTES = 8 * 1024 * 1024    # only the tail of big logs is read
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
NOT_OBSERVED = ("Not observed: what the API retains, unmarked controlled data, "
                "and anything that happens outside the hooks.")


def worse(a, b):
    """Return the worse of two colors (red > amber > grey > green)."""
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def _now_dt(now=None):
    """Normalise a now value (None, ISO string or datetime) to an aware UTC datetime."""
    if now is None:
        try:
            from hd import util
            now = util.now()
        except Exception:
            now = datetime.now(timezone.utc)
    if isinstance(now, str):
        return parse_ts(now) or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def parse_ts(s):
    """Parse an ISO-8601 timestamp (Z or offset) to an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _iso(d):
    """Format an aware datetime as ISO-8601 UTC with Z."""
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def humanize(seconds):
    """Render a duration in seconds as a short phrase like '3h' or '12m'."""
    s = int(max(seconds, 0))
    if s < 90:
        return "%ds" % s
    if s < 5400:
        return "%dm" % round(s / 60)
    if s < 172800:
        return "%dh" % round(s / 3600)
    return "%dd" % round(s / 86400)


def _read_json(path):
    """Read a JSON file, returning None when missing or malformed."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_jsonl(path, max_bytes=MAX_TAIL_BYTES):
    """Read dict lines from the tail of a JSONL file; bad lines are skipped."""
    out = []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        if size > max_bytes:
            data = data.split(b"\n", 1)[-1]      # drop the partial first line
    except OSError:
        return out
    for line in data.decode("utf-8", "replace").splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _ev_time(ev):
    """Trusted event time: recv_ts, else agent_ts (untrusted fallback)."""
    return parse_ts(ev.get("recv_ts")) or parse_ts(ev.get("agent_ts"))


def effective_mode(cfg):
    """Return (mode, mode_set); a missing mode is treated as strict."""
    m = cfg.get("mode")
    if m in ("strict", "standard"):
        return m, True
    return "strict", False


def _short(v, n=120):
    """Turn an untrusted value into a short display string."""
    if isinstance(v, dict):
        h = v.get("hash")
        return "path #%s" % h if h else "hidden"
    if v is None:
        return None
    return str(v)[:n]


# ---------------------------------------------------------------- sessions

def build_sessions(cfg, events, now):
    """Group events by session and apply the rule-based stuck detection."""
    mode, _ = effective_mode(cfg)
    th = dict({"no_event_minutes": 10, "repeat_call_limit": 5, "same_file_edit_limit": 8,
               "subagent_outlive_factor": 3.0, "budget_tool_calls": 500}, **(cfg.get("stuck") or {}))
    by = {}
    for ev in events:
        sid = ev.get("session_id")
        if isinstance(sid, str):
            by.setdefault(sid, []).append(ev)
    rows = []
    for sid, evs in by.items():
        last = evs[-1]
        lt = _ev_time(last) or now
        since = int((now - lt).total_seconds())
        kind = last.get("kind")
        tools = [e for e in evs if e.get("kind") in ("tool_pre", "tool_post", "tool_error")]
        pre = [e for e in evs if e.get("kind") == "tool_pre"] or \
              [e for e in evs if e.get("kind") == "tool_post"]
        started = {}
        done = []
        for e in evs:
            aid = e.get("agent_id")
            if e.get("kind") == "subagent_start" and aid:
                started[aid] = _ev_time(e)
            elif e.get("kind") == "subagent_stop" and aid:
                t0 = started.pop(aid, None)
                t1 = _ev_time(e)
                done.append((t1 - t0).total_seconds() if t0 and t1 else None)
        durations = [d for d in done if d is not None]
        reason = None
        if kind == "session_end":
            status = "done"
        elif kind == "permission_pending" or last.get("status") == "pending":
            status = "waiting on you"
        else:
            status = "idle" if kind in ("stop", "run_end") else "working"
            reason = _stuck_reason(th, evs, tools, pre, started, durations, since, status, now)
            if reason:
                status = "stuck"
        wo = None
        for e in reversed(evs):
            wo = e.get("task") or e.get("file_path")
            if wo:
                break
        if mode == "strict":
            working_on = "hidden (strict)" if wo else None
        else:
            working_on = _short(wo)
        last_tool = next((e.get("tool_name") for e in reversed(tools) if e.get("tool_name")), None)
        rows.append({"session_id": sid[:64], "harness": str(last.get("harness", cfg.get("name", "")))[:64],
                     "subagents_active": len(started), "subagents_done": len(done),
                     "working_on": working_on, "last_tool": _short(last_tool, 64),
                     "since_last_event_s": since, "status": status, "stuck_reason": reason})
    rows = [r for r in rows if not (r["status"] == "done" and r["since_last_event_s"] > 3600)]
    rows.sort(key=lambda r: r["since_last_event_s"])
    return rows[:30]


def _stuck_reason(th, evs, tools, pre, started, durations, since, status, now):
    """Return a plain-language stuck reason for a session, or None."""
    if status == "working" and since >= th["no_event_minutes"] * 60:
        return "no events for %s" % humanize(since)
    n = th["repeat_call_limit"]
    calls = [(e.get("tool_name"), _short(e.get("file_path") or e.get("task"), 200))
             for e in evs if e.get("kind") == "tool_pre"] or \
            [(e.get("tool_name"), _short(e.get("file_path") or e.get("task"), 200))
             for e in evs if e.get("kind") == "tool_post"]
    if len(calls) >= n and len(set(calls[-n:])) == 1:
        return "same call repeated %d times" % n
    errs = [(e.get("tool_name"), str(e.get("status"))) for e in tools if e.get("kind") == "tool_error"]
    tail = [e for e in tools][-n:]
    if len(tail) >= n and all(e.get("kind") == "tool_error" for e in tail) and len(set(errs[-n:])) == 1:
        return "same error repeated %d times" % n
    counts = {}
    for e in pre:
        if e.get("tool_name") in EDIT_TOOLS and e.get("file_path") is not None:
            k = json.dumps(e.get("file_path"), sort_keys=True)
            counts[k] = counts.get(k, 0) + 1
    if counts and max(counts.values()) >= th["same_file_edit_limit"]:
        return "same file edited %d times" % max(counts.values())
    if durations and started:
        med = statistics.median(durations)
        for t0 in started.values():
            if t0 and med > 0 and (now - t0).total_seconds() > th["subagent_outlive_factor"] * med:
                return "a subagent has run far longer than its siblings"
    if len(pre) >= th["budget_tool_calls"]:
        return "tool-call budget of %d reached" % th["budget_tool_calls"]
    return None


# ---------------------------------------------------------------- verdict

def _checks_list(checks):
    """Normalise checks.json content to a list of result dicts."""
    if isinstance(checks, dict):
        checks = checks.get("results")
    return [c for c in (checks or []) if isinstance(c, dict)]


def _is_claimed(c):
    """True when a check result is agent-claimed rather than independent."""
    return bool(c.get("agent_claimed")) or c.get("independent") is False or c.get("state") == "agent_claimed"


def _goal(cfg, events, checks, now, hb_ok):
    """Compute the Goal chip and last-run info."""
    last_run = None
    run_ends = [e for e in events if e.get("kind") == "run_end"]
    if not run_ends:  # no explicit run_end: the latest session_end / stop event stands in
        run_ends = [e for e in events if e.get("kind") in ("session_end", "stop")][-1:]
    if run_ends:
        e = run_ends[-1]
        t = _ev_time(e) or now
        ex = e.get("extra") if isinstance(e.get("extra"), dict) else {}
        res = ex.get("result") or ("failed" if e.get("status") in ("error", "denied") else "passed")
        last_run = {"result": str(res)[:40], "ago": humanize((now - t).total_seconds()) + " ago"}
    if not events:
        return {"color": "grey", "reason": "no events recorded yet"}, last_run
    results = _checks_list(checks)
    fails = [c for c in results if c.get("state") == "fail"]
    unk = [c for c in results if c.get("state") == "could_not_check"]
    passes = [c for c in results if c.get("state") == "pass" and not _is_claimed(c)]
    claimed = [c for c in results if c.get("state") == "pass" and _is_claimed(c)]
    if last_run and last_run["result"] == "failed":
        return {"color": "red", "reason": "last run failed %s" % last_run["ago"]}, last_run
    if fails:
        return {"color": "red", "reason": "check failed: %s" % str(fails[0].get("id"))[:60]}, last_run
    # should-have-run-by rule
    erb = cfg.get("expected_run_by")
    if erb:
        try:
            hh, mm = [int(x) for x in str(erb).split(":")]
            local = now.astimezone()
            due = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            ran = any(k.get("kind") in ("run_start", "session_start") and
                      (_ev_time(k) or now).astimezone().date() == local.date() for k in events)
            if not ran:
                if local < due:
                    if hb_ok:
                        return {"color": "grey", "reason": "idle, expected to run by %s" % erb}, last_run
                else:
                    col = "red" if local - due > timedelta(hours=1) else "amber"
                    return {"color": col, "reason": "should have run by %s" % erb}, last_run
        except (ValueError, TypeError):
            pass
    if unk:
        return {"color": "amber", "reason": "could not check: %s" % str(unk[0].get("id"))[:60]}, last_run
    newest = max([parse_ts(c.get("ts")) for c in results if parse_ts(c.get("ts"))] or [None], key=lambda x: x or now - timedelta(days=9999))
    if passes and newest and (now - newest) > timedelta(hours=24):
        return {"color": "amber", "reason": "checks last ran %s ago" % humanize((now - newest).total_seconds())}, last_run
    if passes:
        return {"color": "green", "reason": "%d independent check%s passed, none failed"
                % (len(passes), "" if len(passes) == 1 else "s")}, last_run
    if claimed:
        return {"color": "amber", "reason": "agent-claimed only: no independent check passed"}, last_run
    return {"color": "amber", "reason": "no independent checks have run"}, last_run


# ---------------------------------------------------------------- security

def _line(key, label, color, text, **extra):
    """Build one security-block line."""
    d = {"key": key, "label": label, "color": color, "text": text}
    d.update(extra)
    return d


def _names(items):
    """Names only from a list like ['A=secret', 'B'] so values never show."""
    return [str(i).split("=", 1)[0][:60] for i in (items or [])]


def build_security(cfg, hb, events, records, scan_counts, wall, approval, changed, now):
    """Build every Security-block line in PLAN.md order."""
    lines = []
    mode, mode_set = effective_mode(cfg)
    if mode_set:
        lines.append(_line("mode", "your statement", "neutral", "Mode: %s" % mode.capitalize()))
    else:
        lines.append(_line("mode", "your statement", "amber", "Mode: not set (treated as Strict)"))

    # wall
    tier = (wall or {}).get("tier") or (cfg.get("wall") or {}).get("tier") or "none"
    if wall is None:
        wall = {"tier": tier, "running": None, "config_matches": None, "allowlist": "unknown", "detail": ""}
    running = wall.get("running")
    parts = ["tier %s" % tier]
    parts.append({True: "running", False: "not running", None: "running not observed"}[running])
    cm = wall.get("config_matches")
    parts.append({True: "config matches approval", False: "config differs from approval",
                  None: "config match not observed"}[cm])
    parts.append("network allowlist %s" % wall.get("allowlist", "unknown"))
    if wall.get("detail"):
        parts.append(str(wall["detail"])[:200])
    if tier == "none" or running is False:
        wcol = "red"
    elif tier not in ("vm", "container") or running is not True or cm is not True \
            or wall.get("allowlist") not in ("enforced", "matches approved config"):
        wcol = "amber"
    else:
        wcol = "green"
    if wcol == "red":  # lead with the reason so the verdict line explains itself
        parts.insert(0, "not running" if running is False else "no wall configured")
    lines.append(_line("wall", "observed" if running is not None else "declared (unverified)",
                       wcol, "Wall: " + "; ".join(parts)))

    # data sources + screening
    srcs = cfg.get("data_sources") or []
    scr = records.get("screening_confirmed")
    last_rec = records.get("_last_ts")
    txt = "%d data source%s" % (len(srcs), "" if len(srcs) == 1 else "s")
    col = "neutral"
    if scr:
        txt += "; screening statement recorded %s" % scr.get("ts", "?")
    else:
        txt += "; no screening statement recorded"
        col = "amber" if srcs else "neutral"
    if changed is not None:
        txt += "; %d changed since screening" % changed
        if changed > 0:
            col = "amber"
    txt += "; last record %s" % (last_rec or "none")
    lines.append(_line("data_sources", "your statement", col, txt))

    # marking scan
    sc = scan_counts or {}
    n, m, hits = sc.get("scanned", 0), sc.get("not_scannable", 0), sc.get("hits", 0)
    hold = records.get("hold", False)
    hits_rec = records.get("hit_count", 0)
    released = records.get("released_ts")
    after = records.get("hits_after_release", 0)
    unavail = sum(1 for e in events if isinstance(e.get("extra"), dict) and isinstance(e["extra"].get("scan"), dict)
                  and e["extra"]["scan"].get("unavailable") is True)
    past_only = bool(not hold and released and hits_rec and not after)   # hits all happened before the release
    if hold:
        scol = "red"
    elif (hits or hits_rec) and not past_only:
        scol = "amber"
    else:
        scol = "neutral"
    if past_only:
        stxt = "%d past marking hit%s; hold released %s" % (hits_rec, "" if hits_rec == 1 else "s", released)
    elif hits or hits_rec:
        stxt = "%d marking hit%s in %d scanned items (%d not scannable)" % (max(hits, hits_rec), "" if max(hits, hits_rec) == 1 else "s", n, m)
    elif scan_counts is None:
        stxt = "no scan counts available"
        scol = "amber"
    else:
        stxt = "no markings found in %d scanned items (%d not scannable)" % (n, m)
    if unavail:
        stxt = "scan unavailable in hook for %d events; %s" % (unavail, stxt)
        scol = "red" if hold else "amber"
    lines.append(_line("marking_scan", "observed", scol, stxt,
                       detail="retention hold %s; Claude Code transcripts are not held; they follow cleanupPeriodDays"
                              % ("on" if hold else "off"), hold=bool(hold)))

    # declared
    d = cfg.get("declared") or {}
    lines.append(_line("declared", "declared (unverified)", "neutral",
                       "Declared permissions: %s; env var names: %s; hosts: %s. Declared env is not the real env."
                       % (", ".join(_names(d.get("permissions"))) or "none",
                          ", ".join(_names(d.get("env"))) or "none",
                          ", ".join(_names(d.get("hosts"))) or "none")))

    # observed but undeclared
    allowed = set(_names(d.get("hosts"))) | set(_names((cfg.get("wall") or {}).get("allowlist_hosts")))
    seen_hosts = sorted({str(e["host"])[:100] for e in events if isinstance(e.get("host"), str)} - allowed)
    perms = [p.split("(")[0] for p in _names(d.get("permissions"))]
    seen_tools = sorted({str(e["tool_name"])[:60] for e in events if isinstance(e.get("tool_name"), str)})
    und_tools = [t for t in seen_tools if perms and not any(t == p or t.startswith(p) for p in perms)]
    if not events:
        lines.append(_line("undeclared", "observed", "neutral", "Observed but undeclared: no events observed yet"))
    elif seen_hosts or und_tools:
        lines.append(_line("undeclared", "observed", "amber",
                           "Observed but undeclared: hosts %s; tools %s"
                           % (", ".join(seen_hosts) or "none", ", ".join(und_tools) or "none")))
    else:
        lines.append(_line("undeclared", "observed", "neutral", "Observed but undeclared: none seen in hook events"))

    # secrets in scope
    remote = [str(s.get("name"))[:60] for s in (d.get("mcp_servers") or []) if isinstance(s, dict) and s.get("remote")]
    stxt = "Secrets in scope cannot be listed for remote MCP servers."
    scol = "neutral"
    if remote:
        stxt += " Remote servers declared: %s." % ", ".join(remote)
        scol = "red" if mode == "strict" else "amber"
        if mode == "strict":
            stxt += " Strict mode does not allow remote MCP servers."
    lines.append(_line("secrets", "declared (unverified)", scol, stxt))

    # copies
    ret = cfg.get("retention") or {}
    chain_ok = (hb or {}).get("chain_ok")
    chain = "log chain checks passed" if chain_ok is True else (
        "log chain BROKEN at line %s%s" % ((hb or {}).get("chain_break_line"),
                                           (" (%s)" % str(hb["chain_break_reason"])[:60]) if (hb or {}).get("chain_break_reason") else "")
        if chain_ok is False else "log chain not observed")
    enc = "on (your statement)" if cfg.get("disk_encryption") == "on" else "not stated"
    tc = cfg.get("transcript_cleanup_days")
    ctxt = ("Copies: logs and records in %s, metadata kept %s days, content kept %s days; transcripts cleaned %s; %s; disk encryption %s"
            % (cfg.get("state_dir", "?"), ret.get("metadata_days", "?"), ret.get("content_days", "?"),
               ("after %s days (declared)" % tc) if tc else "on Claude Code's default schedule (not declared)", chain, enc))
    if chain_ok is False:  # lead with the break so it is the verdict reason
        ctxt = chain + "; " + ctxt.replace("; " + chain, "")
    lines.append(_line("copies", "observed", "red" if chain_ok is False else "neutral", ctxt))

    # dependencies
    dep = cfg.get("dependencies") or {}
    if not (dep.get("lockfile") or dep.get("last_reviewed")):
        lines.append(_line("dependencies", "declared (unverified)", "neutral", "Dependencies: none declared"))
    else:
        rev = dep.get("last_reviewed")
        rd = parse_ts(str(rev) + "T00:00:00Z") if rev else None
        if rd is None:
            dcol, rtxt = "amber", "never reviewed"
        elif (now - rd).days > 90:
            dcol, rtxt = "amber", "last reviewed %s (over 90 days ago)" % rev
        else:
            dcol, rtxt = "neutral", "last reviewed %s" % rev
        lines.append(_line("dependencies", "declared (unverified)", dcol,
                           "Dependencies: lockfile %s; %s" % (dep.get("lockfile", "none"), rtxt)))

    # user
    try:
        from hd import util
        user = util.os_user()
    except Exception:
        import getpass
        user = getpass.getuser()
    lines.append(_line("user", "observed", "neutral",
                       "single-user tool; actions recorded under OS user %s" % user))
    lines.append(_line("not_observed", "observed", "neutral", NOT_OBSERVED))
    lines.append(_line("control_mapping", "observed", "neutral", "Control mapping", link="mapping"))

    # approval line is folded into wall/stale handling by the caller
    return lines


def _approval_line(approval):
    """Build the approval line shown after Wall (inserted by build)."""
    if approval is None:
        return _line("approval", "observed", "amber", "Approval: not computed")
    if not approval.get("approved"):
        return _line("approval", "observed", "amber", "Approval: no approved set recorded")
    if approval.get("stale"):
        return _line("approval", "observed", "amber",
                     "Approval: stale, changed since approval: %s" % ", ".join(map(str, approval.get("changed_parts") or [])))
    return _line("approval", "observed", "neutral", "Approval: matches the approved set")


# ---------------------------------------------------------------- middle

def build_middle(cfg, events, state_dir):
    """Merge cfg.middle panel specs with computed data; unknown types become notices."""
    panels = ((cfg.get("middle") or {}).get("panels")) or []
    out = []
    for p in panels:
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        title = str(p.get("title") or t or "panel")[:80]
        if t == "tool_inventory":
            out.append({"type": t, "title": title, "rows": _tool_inventory(cfg, p, events)})
        elif t == "pipeline":
            stages = []
            for s in (p.get("stages") or []):
                if not isinstance(s, dict):
                    continue
                tool = s.get("tool")
                cnt = sum(1 for e in events if e.get("kind") == "tool_post" and e.get("tool_name") == tool)
                stages.append({"label": str(s.get("label") or tool)[:60], "count": cnt})
            out.append({"type": t, "title": title, "stages": stages})
        elif t in ("queue", "data_store"):
            name = os.path.basename(str(p.get("source") or ""))
            data = _read_json(os.path.join(state_dir, "panels", name)) if name else None
            if isinstance(data, list):
                data = {"count": len(data)}
            if not isinstance(data, dict):
                data = {}
            clean = {str(k)[:40]: (v if isinstance(v, (int, float, bool)) else str(v)[:80]) for k, v in list(data.items())[:12]}
            out.append({"type": t, "title": title, "values": clean, "observed": bool(data)})
        else:
            out.append({"type": "unsupported", "title": title, "note": "unsupported panel type; not rendered"})
    return out


def _tool_inventory(cfg, panel, events):
    """Calls per tool, last used, error rate, and never-called flags for declared tools."""
    stats = {}
    for e in events:
        tn = e.get("tool_name")
        if not isinstance(tn, str):
            continue
        s = stats.setdefault(tn[:60], {"calls": 0, "errors": 0, "last": None})
        if e.get("kind") in ("tool_pre",):
            s["calls"] += 1
        if e.get("kind") == "tool_error" or (e.get("kind") == "tool_post" and e.get("status") == "error"):
            s["errors"] += 1
        t = _ev_time(e)
        if t and (s["last"] is None or t > s["last"]):
            s["last"] = t
    for s in stats.values():
        if s["calls"] == 0:
            s["calls"] = s["errors"]
    declared = panel.get("declared_tools") or [p.split("(")[0] for p in _names((cfg.get("declared") or {}).get("permissions"))]
    rows = []
    for name, s in sorted(stats.items()):
        rows.append({"tool": name, "calls": s["calls"], "last_used": _iso(s["last"]) if s["last"] else None,
                     "error_rate": round(s["errors"] / s["calls"], 3) if s["calls"] else 0.0, "never_called": False})
    for d in declared:
        if str(d)[:60] not in stats:
            rows.append({"tool": str(d)[:60], "calls": 0, "last_used": None, "error_rate": 0.0, "never_called": True})
    return rows


# ---------------------------------------------------------------- records

def _records_summary(state_dir):
    """Summarise records.jsonl: latest screening, hold, hit count, last record time."""
    recs = read_jsonl(os.path.join(state_dir, "records.jsonl"))
    out = {"hold": False, "hit_count": 0, "screening_confirmed": None, "_last_ts": None,
           "released_ts": None, "hits_after_release": 0}
    for r in recs:
        t = r.get("type")
        if r.get("ts"):
            out["_last_ts"] = r["ts"]
        if t == "scan_hit":
            out["hit_count"] += 1
            out["hits_after_release"] += 1
        elif t == "retention_hold":
            out["hold"] = bool(r.get("on"))
            out["released_ts"] = None if r.get("on") else r.get("ts")
            out["hits_after_release"] = 0
        elif t == "screening_confirmed":
            out["screening_confirmed"] = r
    return out


# ---------------------------------------------------------------- build

def build(cfg, now=None, wall=None, approval=None, checks=None, changed_since=None):
    """Build the full dashboard payload; wall/approval/checks/changed_since are optional overrides."""
    now = _now_dt(now)
    sd = os.path.expanduser(str(cfg.get("state_dir") or "."))
    hb = _read_json(os.path.join(sd, "heartbeat.json"))
    events = read_jsonl(os.path.join(sd, "events.jsonl"))
    records = _records_summary(sd)
    scan_counts = _read_json(os.path.join(sd, "scan_counts.json"))
    if checks is None:
        checks = _read_json(os.path.join(sd, "checks.json"))
    if approval is None:
        af = _read_json(os.path.join(sd, "approval.json"))
        if isinstance(af, dict):
            approval = {"approved": True, "stale": bool(af.get("stale")), "changed_parts": af.get("changed_parts") or []}
    hbt = parse_ts((hb or {}).get("ts"))
    data_age = int((now - hbt).total_seconds()) if hbt else None
    hb_ok = data_age is not None and data_age <= HEARTBEAT_MAX_AGE_S

    goal, last_run = _goal(cfg, events, checks, now, hb_ok)
    sec_lines = build_security(cfg, hb, events, records, scan_counts, wall, approval, changed_since, now)
    sec_lines.insert(2, _approval_line(approval))
    scol, sreason = "green", "every check this dashboard can run on the wall and logs passed"
    for ln in sec_lines:
        if ln["color"] in ("red", "amber") and RANK[ln["color"]] > RANK[scol]:
            scol, sreason = ln["color"], ln["text"].split(";")[0][:160]
    if scol == "red":
        reds = [l["text"].split(";")[0] for l in sec_lines if l["color"] == "red"]
        sreason = "; ".join(reds)[:200]

    if not hb_ok:
        goal = {"color": "grey", "reason": "no data from collector"}
    color = worse(goal["color"], scol)
    if not hb_ok:
        if scol == "red":
            color, reason = "red", "no data from collector; also: " + sreason
        else:
            color, reason = "grey", "no data from collector"
    else:
        reason = goal["reason"] if goal["color"] == color else sreason

    mode, mode_set = effective_mode(cfg)
    return {
        "harness": str(cfg.get("name", ""))[:80],
        "goal_text": str(cfg.get("goal") or "")[:300],
        "mode": mode, "mode_set": mode_set,
        "verdict": {"color": color, "reason": reason, "goal": goal,
                    "safety": {"color": scol, "reason": sreason},
                    "last_run": last_run, "data_age_s": data_age, "server_ts": _iso(now)},
        "sessions": build_sessions(cfg, events, now),
        "security": sec_lines,
        "middle": build_middle(cfg, events, sd),
        "effects": "Effects: not observed in this build",
        "stale": bool(approval and approval.get("stale")),
    }
