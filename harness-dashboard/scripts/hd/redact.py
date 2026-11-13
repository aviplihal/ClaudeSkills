"""Best-effort secret redaction and path shortening for events (pattern-based, not a guarantee)."""
import hashlib
import re

# (compiled regex, replacement) pairs; order matters (private-key blocks first).
_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), "[REDACTED:private-key]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"), "[REDACTED:api-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED:github-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws-key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:slack-token]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD))\s*=\s*(?:\"[^\"]*\"|'[^']*'|\S+)"), r"\1=[REDACTED]"),
]
MAX_STRING = 4000  # cap per stored content string


def redact_text(s):
    """Redact secrets in a string; returns (new_string, number_of_redactions)."""
    total = 0
    for rx, rep in _PATTERNS:
        s, n = rx.subn(rep, s)
        total += n
    return s, total


def shorten_path(p):
    """Shorten a path to '…/<last component, max 16 chars>#<sha256[:8]>' (hash of the full string)."""
    p = str(p)
    last = re.split(r"[\\/]", p.rstrip("\\/"))[-1]
    return "…/%s#%s" % (last[:16], hashlib.sha256(p.encode("utf-8", "replace")).hexdigest()[:8])


def _walk(obj):
    """Recursively redact strings in a JSON-like value; returns (value, count)."""
    if isinstance(obj, str):
        s, n = redact_text(obj)
        if len(s) > MAX_STRING:
            s = s[:MAX_STRING] + "[truncated]"
        return s, n
    if isinstance(obj, dict):
        out, total = {}, 0
        for k, v in obj.items():
            out[k], n = _walk(v)
            total += n
        return out, total
    if isinstance(obj, list):
        out, total = [], 0
        for v in obj:
            nv, n = _walk(v)
            out.append(nv)
            total += n
        return out, total
    return obj, 0


def redact_event(ev, mode, capture):
    """Return a copy of ev with content stripped (strict or capture off) or redacted, paths shortened in strict."""
    ev = dict(ev)
    strict = mode != "standard"
    if strict or not capture:
        ev.pop("content", None)
    elif isinstance(ev.get("content"), dict):
        ev["content"], n = _walk(ev["content"])
        if n:
            ev["extra"] = dict(ev.get("extra") or {}, redactions=n)
    for k in ("file_path", "task"):
        if k in ev and isinstance(ev[k], str):
            if strict and k == "file_path":
                ev[k] = shorten_path(ev[k])
            elif strict:  # task is free text, not a path: keep only a hash and length
                ev[k] = "[task #%s, %d chars]" % (hashlib.sha256(ev[k].encode("utf-8", "replace")).hexdigest()[:8], len(ev[k]))
            else:
                ev[k], _ = redact_text(ev[k])
    return ev
