"""hd.demo - start the dashboard on a throwaway state_dir filled with FAKE data so the UI can be eyeballed.

Run: python3 -m hd.demo   (from harness-dashboard/scripts). Fake harness "demo-car-finder"; nothing real is read or written
outside a temp directory, which is removed on exit.
"""
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

from . import server


def _iso(d):
    """ISO Z string for a datetime."""
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _writer(sd):
    """Return (append_event, append_record) helpers; use hd.chainlog when available so logs verify."""
    try:
        from .chainlog import ChainLog
        ev, rc = ChainLog(os.path.join(sd, "events.jsonl")), ChainLog(os.path.join(sd, "records.jsonl"))
        return ev.append, rc.append
    except Exception:
        def mk(name):
            """Plain JSONL appender fallback."""
            def add(obj):
                with open(os.path.join(sd, name), "a") as f:
                    f.write(json.dumps(obj) + "\n")
            return add
        return mk("events.jsonl"), mk("records.jsonl")


def build_demo(sd):
    """Write fake config, logs, checks and heartbeat into sd; return the config dict."""
    now = datetime.now(timezone.utc)
    cfg = {"name": "demo-car-finder", "mode": "standard", "goal": "Find 3 matching used cars each morning (FAKE DEMO DATA)",
           "state_dir": sd, "data_sources": ["/fake/drop-folder"], "wall": {"tier": "container", "container_name": "demo"},
           "stuck": {"no_event_minutes": 10, "repeat_call_limit": 5},
           "declared": {"permissions": ["Read", "Bash(ls:*)", "WebFetch"], "env": ["API_KEY"], "hosts": ["api.example.test"], "mcp_servers": []},
           "retention": {"metadata_days": 90, "content_days": 7}, "disk_encryption": "on",
           "dependencies": {"lockfile": "demo.lock", "last_reviewed": "2026-01-15"},
           "middle": {"panels": [{"type": "tool_inventory", "title": "Tool inventory", "declared_tools": ["Read", "WebFetch", "Grep"]},
                                 {"type": "pipeline", "title": "Pipeline", "stages": [{"label": "pages fetched", "tool": "WebFetch"}, {"label": "files read", "tool": "Read"}]},
                                 {"type": "chart3d", "title": "Unknown panel type"}]}}
    with open(os.path.join(sd, "harness.json"), "w") as f:
        json.dump(cfg, f)
    add_ev, add_rec = _writer(sd)
    n = [0]

    def ev(kind, ago, sid, **kw):
        """Append one fake event."""
        n[0] += 1
        e = {"v": 1, "harness": "demo-car-finder", "session_id": sid, "kind": kind, "agent_ts": "fake",
             "recv_ts": _iso(now - timedelta(seconds=ago)), "event_id": "demo-%d" % n[0]}
        e.update(kw)
        add_ev(e)

    ev("run_start", 3000, "sess-main")
    for i in range(6):
        ev("tool_pre", 2900 - i * 60, "sess-main", tool_name="WebFetch", host="api.example.test", task="fetch listings page %d" % i)
        ev("tool_post", 2895 - i * 60, "sess-main", tool_name="WebFetch", status="ok")
    ev("tool_pre", 20, "sess-main", tool_name="Read", file_path="/fake/drop-folder/notes.txt")
    ev("tool_pre", 30, "sess-sub", tool_name="Grep", task="rank candidates")
    for i in range(6):
        ev("tool_pre", 400 - i * 20, "sess-stuck", tool_name="Bash", task="ls /fake")
    ev("permission_pending", 15, "sess-wait", tool_name="Bash")
    ev("tool_pre", 20, "sess-evil", tool_name="WebFetch", host="unknown.example.test")
    ev("session_end", 30, "sess-done")
    add_rec({"type": "screening_confirmed", "ts": _iso(now - timedelta(days=2)), "os_user": "demo", "sources": ["/fake/drop-folder"], "file_count": 12, "listing_hash": "fake"})
    add_rec({"type": "scan_hit", "ts": _iso(now - timedelta(minutes=5)), "os_user": "demo", "pattern": "FAKE-PATTERN", "event_id": "demo-3", "source": "task"})
    add_rec({"type": "retention_hold", "ts": _iso(now - timedelta(minutes=5)), "os_user": "demo", "on": True, "reason": "fake scan hit"})
    with open(os.path.join(sd, "checks.json"), "w") as f:
        json.dump([{"id": "three_results", "state": "pass", "detail": "3 results", "ts": _iso(now), "independent": True},
                   {"id": "price_rederive", "state": "fail", "detail": "price differs from source", "ts": _iso(now), "independent": True}], f)
    with open(os.path.join(sd, "scan_counts.json"), "w") as f:
        json.dump({"scanned": 140, "not_scannable": 6, "hits": 1}, f)
    with open(os.path.join(sd, "approval.json"), "w") as f:
        json.dump({"approved": True}, f)
    return cfg


def _beat(sd, stop):
    """Refresh the fake heartbeat every 5 seconds until stop is set."""
    while not stop.is_set():
        with open(os.path.join(sd, "heartbeat.json"), "w") as f:
            json.dump({"ts": _iso(datetime.now(timezone.utc)), "pid": os.getpid(), "chain_ok": True, "chain_break_line": None}, f)
        stop.wait(5)


def main():
    """Create the demo, start the server and print the URL."""
    sd = tempfile.mkdtemp(prefix="hd-demo-")
    os.chmod(sd, 0o700)
    cfg = build_demo(sd)
    stop = threading.Event()
    threading.Thread(target=_beat, args=(sd, stop), daemon=True).start()
    time.sleep(0.2)
    srv = server.make_server(cfg, 0, config_path=os.path.join(sd, "harness.json"),
                             overrides={"wall": {"tier": "container", "running": True, "config_matches": True, "allowlist": "enforced", "detail": "FAKE"},
                                        "approval": {"approved": True, "stale": True, "changed_parts": ["hook_config"]},
                                        "changed": 2})
    print("FAKE DEMO DATA. Open: http://127.0.0.1:%d/#t=%s" % (srv.app.port, srv.app.token), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        shutil.rmtree(sd, ignore_errors=True)


if __name__ == "__main__":
    main()
