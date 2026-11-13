#!/usr/bin/env python3
"""Claude Code hook script: reads one hook payload on stdin, appends one JSONL event to the channel.

Runs INSIDE the wall as a standalone stdlib script (no dependency on the hd package). Always exits 0,
prints nothing on stdout, and logs problems to stderr only so it can never block the agent.
It also runs the marking scan in memory on every event (scan.py must sit next to this file; optional
--patterns FILE adds per-harness patterns) and reports only pattern names and field names in extra.scan.
"""
import argparse
import datetime
import importlib.util
import json
import os
import sys

MAX_LINE = 60 * 1024  # truncate every appended line to at most 60 KiB (collector limit is 64 KiB)

# Single mapping table: Claude Code hook_event_name -> event kind. (VERIFY names against Claude Code docs.)
HOOK_MAP = {
    "PreToolUse": "tool_pre",
    "PostToolUse": "tool_post",
    "PostToolUseFailure": "tool_error",
    "SubagentStart": "subagent_start",
    "SubagentStop": "subagent_stop",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "UserPromptSubmit": "prompt",
    "Notification": "notification",  # split on notification_type in extract()
    "PermissionRequest": "permission_pending",  # fires the moment the prompt is shown (no tool_use_id)
    "PermissionDenied": "tool_error",  # status "denied" (auto-mode denials)
    "Stop": "stop",
    "StopFailure": "stop",  # API-error turn end; status "error"
}
SCAN_MAX_HITS = 20  # cap on hits reported per event
TASK_TOOLS = ("Task", "Agent")  # tools whose tool_input.description is the subagent task


def _utc_now():
    """Return the agent-side timestamp (untrusted) as ISO-8601 UTC with Z."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_error_response(resp):
    """Return True if a tool_response payload indicates the tool failed (VERIFY shape)."""
    if isinstance(resp, dict):
        if resp.get("is_error") is True or resp.get("isError") is True:
            return True
        if resp.get("success") is False:
            return True
        if resp.get("error"):
            return True
    return False


def _is_permission_notification(payload):
    """True for a permission Notification: notification_type decides; text fallback only when it is absent."""
    ntype = payload.get("notification_type")
    if ntype:
        return str(ntype) == "permission_prompt"
    return "permission" in str(payload.get("message") or "").lower()


def load_scanner(patterns_file=None):
    """Load scan.py from this file's directory (no hd import); return (Scanner|None, module|None, patterns_ok)."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan.py")
        spec = importlib.util.spec_from_file_location("hd_scan_standalone", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException:  # noqa: BLE001 - a missing scan.py must not break the hook
        return None, None, False
    extra, ok = None, True
    if patterns_file:
        try:
            with open(patterns_file, "r", encoding="utf-8") as f:
                extra = json.load(f)
            if not isinstance(extra, list):
                extra, ok = None, False
        except (OSError, ValueError):
            extra, ok = None, False
    try:
        sc = mod.Scanner(extra)
    except BaseException:  # noqa: BLE001
        return None, None, False
    if sc.bad_patterns:
        ok = False
    return sc, mod, ok


def scan_payload(sc, mod, payload, ev):
    """Scan tool_input, tool_response, prompt, file_path and task in memory; return the extra.scan dict (no text)."""
    fields = []
    for src, val in (("file_path", ev.get("file_path")), ("task", ev.get("task")), ("prompt", payload.get("prompt")),
                     ("tool_input", payload.get("tool_input")), ("tool_response", payload.get("tool_response"))):
        mod._strings(val, src, fields)
    not_scannable = mod._is_binary_path(ev.get("file_path")) or any("\x00" in t for _, t in fields)
    hits, seen = [], set()
    for src, text in fields:
        if "\x00" in text:
            continue
        text = text[:mod.MAX_SCAN_CHARS]
        for name, rx in sc.patterns:
            if name not in seen and len(hits) < SCAN_MAX_HITS and rx.search(text):
                seen.add(name)  # one hit per pattern; the first field (in the order above) is reported
                hits.append({"pattern": str(name)[:64], "source": src})
    if not fields and not not_scannable:
        return None
    return {"hits": hits, "not_scannable": bool(not_scannable)}


def extract(payload, harness, capture_content=False, patterns_file=None):
    """Map a raw hook payload to an event dict (with in-memory marking scan in extra.scan)."""
    if not isinstance(payload, dict):
        return None
    name = payload.get("hook_event_name")
    kind = HOOK_MAP.get(name)
    if kind is None:
        return None
    if name == "Notification" and _is_permission_notification(payload):
        kind = "permission_pending"
    tool_input = payload.get("tool_input")
    tool_response = payload.get("tool_response")
    ev = {
        "v": 1,
        "harness": harness,
        "session_id": str(payload.get("session_id") or ""),
        "kind": kind,
        "agent_ts": _utc_now(),
    }
    for src, dst in (("tool_name", "tool_name"), ("tool_use_id", "tool_use_id"), ("agent_id", "agent_id")):
        if payload.get(src) is not None:
            ev[dst] = str(payload[src])
    if kind == "tool_pre":
        ev["status"] = "pending"
    elif kind == "tool_post":
        ev["status"] = "error" if _is_error_response(tool_response) else "ok"
    elif kind == "tool_error":
        ev["status"] = "denied" if name == "PermissionDenied" else "error"
    elif name == "StopFailure":
        ev["status"] = "error"
    elif kind == "permission_pending":
        ev["status"] = "pending"
    if isinstance(tool_input, dict):
        fp = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path")
        if isinstance(fp, str):
            ev["file_path"] = fp
        if payload.get("tool_name") in TASK_TOOLS and isinstance(tool_input.get("description"), str):
            ev["task"] = tool_input["description"]
    extra = {}
    if payload.get("notification_type"):
        extra["notification_type"] = str(payload["notification_type"])[:64]
    if name == "PostToolUseFailure" and isinstance(payload.get("is_interrupt"), bool):
        extra["is_interrupt"] = payload["is_interrupt"]
    try:  # scan in memory in EVERY mode, independent of capture_content
        sc, mod, pat_ok = load_scanner(patterns_file)
        if sc is None:
            extra["scan"] = {"unavailable": True}
        else:
            res = scan_payload(sc, mod, payload, ev)
            if res is not None:
                if not pat_ok:
                    res["unavailable"] = True  # per-harness patterns could not all be loaded
                extra["scan"] = res
            elif not pat_ok:
                extra["scan"] = {"unavailable": True}
    except BaseException:  # noqa: BLE001
        extra["scan"] = {"unavailable": True}
    if extra:
        ev["extra"] = extra
    if capture_content:
        content = {}
        if tool_input is not None:
            content["input"] = tool_input
        if tool_response is not None:
            content["output"] = tool_response
        if kind == "prompt" and payload.get("prompt") is not None:
            content["input"] = payload.get("prompt")
        if kind == "notification" and payload.get("message") is not None:
            content["output"] = payload.get("message")
        if content:
            ev["content"] = content
    return ev


def _shrink_strings(obj, limit):
    """Return a copy of obj with every string cut to `limit` characters."""
    if isinstance(obj, str):
        return obj[:limit]
    if isinstance(obj, dict):
        return {k: _shrink_strings(v, limit) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shrink_strings(v, limit) for v in obj]
    return obj


def encode_event(ev):
    """Serialize ev to one newline-terminated line of bytes, <= MAX_LINE, still valid JSON."""
    def enc(e):
        """Compact JSON encode to bytes."""
        return (json.dumps(e, separators=(",", ":"), ensure_ascii=True, default=str) + "\n").encode("ascii")
    data = enc(ev)
    limit = MAX_LINE
    while len(data) > limit and "content" in ev:
        for cap in (8000, 2000, 500, 100):
            ev = dict(ev, content=_shrink_strings(ev["content"], cap))
            data = enc(ev)
            if len(data) <= limit:
                return data
        ev = {k: v for k, v in ev.items() if k != "content"}
        ev["extra"] = dict(ev.get("extra") or {}, content_dropped=True)
        data = enc(ev)
    if len(data) > limit:
        for k in ("file_path", "task"):
            if k in ev:
                ev[k] = str(ev[k])[:500]
        data = enc(ev)
    return data[:limit - 1] + b"\n" if len(data) > limit else data


def append_line(channel, data):
    """Append bytes to the channel with a single O_APPEND write."""
    fd = os.open(channel, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def main(argv=None, stdin=None):
    """Entry point: never raises, always returns 0, never writes to stdout."""
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument("--channel", required=True)
        ap.add_argument("--harness", required=True)
        ap.add_argument("--capture-content", action="store_true")
        ap.add_argument("--patterns", default=None)  # JSON list of {name, regex} per-harness patterns
        args, _ = ap.parse_known_args(argv)
        raw = (stdin or sys.stdin).read()
        payload = json.loads(raw)
        ev = extract(payload, args.harness, args.capture_content, args.patterns)
        if ev is not None:
            append_line(args.channel, encode_event(ev))
    except BaseException as exc:  # noqa: BLE001 - hook must never block the agent
        try:
            sys.stderr.write("harness-dashboard hook: %s: %s\n" % (type(exc).__name__, exc))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
