# schema.py - validate one untrusted channel line into a clean event dict (never raises).
import json

MAX_LINE_BYTES = 64 * 1024
KINDS = ("session_start", "session_end", "prompt", "tool_pre", "tool_post", "tool_error",
         "subagent_start", "subagent_stop", "permission_pending", "notification", "stop",
         "run_start", "run_end")
STATUSES = ("ok", "error", "denied", "pending")
REQUIRED = {"harness": str, "session_id": str, "agent_ts": str}
OPTIONAL = {"tool_name": str, "tool_use_id": str, "agent_id": str, "status": str,
            "file_path": str, "task": str, "host": str, "content": dict, "extra": dict}


def validate(raw_line):
    """Validate a raw line; return (event_dict, None) or (None, error_string). Never raises."""
    try:
        return _validate(raw_line)
    except Exception as e:  # defensive: untrusted input must never crash the collector
        return None, "invalid: %s" % type(e).__name__


def _validate(raw_line):
    """Do the actual checks for validate(); may raise, validate() catches."""
    if isinstance(raw_line, (bytes, bytearray)):
        if len(raw_line) > MAX_LINE_BYTES:
            return None, "line too large"
        raw_line = bytes(raw_line).decode("utf-8")
    if not isinstance(raw_line, str):
        return None, "line is not text"
    if len(raw_line.encode("utf-8", "replace")) > MAX_LINE_BYTES:
        return None, "line too large"
    try:
        obj = json.loads(raw_line)
    except ValueError:
        return None, "bad JSON"
    if not isinstance(obj, dict):
        return None, "not a JSON object"
    v = obj.get("v")
    if isinstance(v, bool) or v != 1 or not isinstance(v, int):
        return None, "bad or missing v"
    out = {"v": 1}
    for key, typ in REQUIRED.items():
        if key not in obj:
            return None, "missing field: %s" % key
        if not isinstance(obj[key], typ):
            return None, "wrong type: %s" % key
        out[key] = obj[key]
    kind = obj.get("kind")
    if "kind" not in obj:
        return None, "missing field: kind"
    if not isinstance(kind, str) or kind not in KINDS:
        return None, "unknown kind"
    out["kind"] = kind
    for key, typ in OPTIONAL.items():
        if key not in obj:
            continue
        val = obj[key]
        if val is None:
            if key == "agent_id":
                out[key] = None  # null agent_id means the main agent
            continue
        if not isinstance(val, typ):
            return None, "wrong type: %s" % key
        if key == "status" and val not in STATUSES:
            return None, "bad status"
        out[key] = val
    return out, None
