# checks.py - declarative independent-check library: specs in, pass/fail/could_not_check out.
"""Declarative checks run by deterministic code outside the model.

Spec: {"id","description","type","params","independent_because","cannot_catch","how_to_break"}.
Types: field_present, count_in_range, rederive, file_hash, cross_ref, time_window,
known_answer, custom (only with params.reviewed_hash == sha256 of the script).
A spec without independent_because is still run but marked independent=False
(agent_claimed=True): it can never count as proof.
Result: {"id","state","detail","ts","independent","agent_claimed"}.
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import util

TIMEOUT_S = 60          # known_answer / custom timeout
MAX_FETCH_BYTES = 1_000_000


class _Fail(Exception):
    """Raised inside a check when the condition is genuinely false (state=fail)."""


class _Cannot(Exception):
    """Raised inside a check when it could not be evaluated (state=could_not_check)."""


# ---------------------------------------------------------------- helpers

def _resolve(cfg, p):
    """Resolve a params path: absolute/~ as given, else under the first data source (or cwd)."""
    p = os.path.expanduser(str(p))
    if os.path.isabs(p):
        return p
    srcs = (cfg or {}).get("data_sources") or []
    base = os.path.expanduser(srcs[0]) if srcs else os.getcwd()
    return os.path.join(base, p)


def _sha256_file(path):
    """sha256 hex of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path, missing_is_fail=True):
    """Load a JSON file; a missing file is a fail (output absent) or could-not-check."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise (_Fail if missing_is_fail else _Cannot)("file missing")
    except ValueError:
        raise _Fail("file is not valid JSON")


def _walk(obj, path):
    """Follow a dotted path ('a.b.0.c') through dicts/lists; raises KeyError if absent."""
    cur = obj
    for part in [p for p in str(path or "").split(".") if p != ""]:
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(part)
    return cur


def _get(obj, path):
    """Like _walk but turns lookup errors into a plain Fail ('path not found')."""
    try:
        return _walk(obj, path)
    except (KeyError, IndexError, ValueError, TypeError):
        raise _Fail("path not found")


def _read_values(cfg, ref, missing_is_fail=True):
    """Read {'file','path'} from a local JSON file or JSONL (path applied per line)."""
    f = _resolve(cfg, ref["file"])
    if f.endswith(".jsonl"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
        except FileNotFoundError:
            raise (_Fail if missing_is_fail else _Cannot)("file missing")
        except ValueError:
            raise _Fail("file is not valid JSONL")
        return rows if not ref.get("path") else [_get(r, ref["path"]) for r in rows]
    return _get(_load_json(f, missing_is_fail), ref.get("path", ""))


def _ids(cfg, ref):
    """Collect a set of string ids from a ref ({'file','path','key'?})."""
    vals = _read_values(cfg, ref)
    if isinstance(vals, dict):
        vals = list(vals.keys())
    if not isinstance(vals, list):
        raise _Fail("not a list")
    out = set()
    for v in vals:
        if isinstance(v, dict):
            if "key" not in ref or ref["key"] not in v:
                raise _Fail("item lacks key")
            v = v[ref["key"]]
        out.add(str(v))
    return out


def _parse_ts(s):
    """Parse an ISO-8601 timestamp (Z or offset) to an aware datetime."""
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now_dt():
    """Current time as a datetime, via util.now() so tests can override the clock."""
    return _parse_ts(util.now())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so a response cannot send us to a host outside the allowlist."""

    def redirect_request(self, *a, **k):
        return None


def default_fetcher(url):
    """Real http_get: no redirects, 10 s timeout, size-capped. Only called after host check."""
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(url, timeout=10) as r:
        return r.read(MAX_FETCH_BYTES).decode("utf-8", "replace")


def _host_allowed(url, allowed):
    """True only for http(s) URLs whose parsed hostname is exactly in allowed_hosts."""
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        return False
    return u.hostname.lower() in {str(h).lower() for h in (allowed or [])}


def _min_env(outputs_dir=None):
    """Minimal environment for check subprocesses: PATH, HOME, LANG (if set) and HD_OUTPUTS_DIR only."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}
    env.setdefault("PATH", "")
    if outputs_dir is not None:
        env["HD_OUTPUTS_DIR"] = outputs_dir
    return env


def known_answer_hash(cfg, params):
    """Review hash for a known_answer check: sha256 of canonical JSON of the argv plus the sha256 of every
    argv element that is an existing file. The skill computes this at approval; any change breaks it."""
    cmd = params.get("command")
    files = {}
    for a in cmd if isinstance(cmd, list) else []:
        if isinstance(a, str) and a:
            path = a if os.path.isabs(a) else _resolve(cfg, a)
            try:
                if os.path.isfile(path):
                    files[a] = _sha256_file(path)
            except OSError:
                files[a] = "unreadable"
    text = json.dumps({"command": cmd, "files": files}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _temp_copy(cfg, paths):
    """Copy the given files/dirs into a fresh temp dir; returns the dir path."""
    d = tempfile.mkdtemp(prefix="hd-check-")
    for p in paths or []:
        src = _resolve(cfg, p)
        dst = os.path.join(d, os.path.basename(src.rstrip("/")))
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    return d


def _make_readonly(root):
    """Strip write bits from everything under root (files first, dirs last)."""
    for dp, dns, fns in os.walk(root, topdown=False):
        for n in fns:
            fp = os.path.join(dp, n)
            os.chmod(fp, os.stat(fp).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        os.chmod(dp, os.stat(dp).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _rm_tree(root):
    """Remove a temp tree even if we made it read-only."""
    for dp, dns, fns in os.walk(root):
        os.chmod(dp, 0o700)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- check types

def _field_present(cfg, p, ctx):
    """Value at json path exists and is non-empty; optional p.fields required on it (or on each item)."""
    v = _get(_load_json(_resolve(cfg, p["file"])), p.get("path", ""))
    if v is None or v == "" or v == [] or v == {}:
        raise _Fail("value empty")
    fields = p.get("fields") or []
    if fields:
        items = v if isinstance(v, list) else [v]
        for i, it in enumerate(items):
            for fld in fields:
                if not isinstance(it, dict) or it.get(fld) in (None, ""):
                    raise _Fail("field %r missing in item %d" % (fld, i))
    return "present"


def _count_in_range(cfg, p, ctx):
    """Number of items (list/dict length, or JSONL lines) lies within [min, max]."""
    v = _read_values(cfg, {"file": p["file"], "path": ""}) if str(p["file"]).endswith(".jsonl") \
        else _get(_load_json(_resolve(cfg, p["file"])), p.get("path", ""))
    if not hasattr(v, "__len__") or isinstance(v, str):
        raise _Fail("not a collection")
    n = len(v)
    lo, hi = p.get("min"), p.get("max")
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise _Fail("count %d outside %s..%s" % (n, lo, hi))
    return "count %d in %s..%s" % (n, lo, hi)


def _norm(v):
    """Normalize a value for comparison: numbers by value, everything else stripped string."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return repr(float(v))
    s = str(v).strip().replace(",", "") if not isinstance(v, str) else v.strip()
    try:
        return repr(float(s.replace(",", "").lstrip("$")))
    except ValueError:
        return s


def _rederive(cfg, p, ctx):
    """Re-read a value from the original source and compare to the value in the output."""
    out_val = _read_values(cfg, p["output"])
    src = p["source"]
    kind = src.get("kind")
    if kind == "json_path":
        src_val = _read_values(cfg, src, missing_is_fail=False)
    elif kind == "http_get":
        url = src.get("url", "")
        if not _host_allowed(url, src.get("allowed_hosts") or p.get("allowed_hosts")):
            raise _Cannot("host not in allowed_hosts")          # rejected before any network call
        import re
        fetch = ctx.get("fetcher") or default_fetcher
        try:
            body = fetch(url)
        except Exception as e:
            raise _Cannot("fetch failed (%s)" % type(e).__name__)
        m = re.search(src["regex"], body)
        if not m:
            raise _Fail("pattern not found at source")
        src_val = m.group(src.get("group", 1) if m.groups() else 0)
    else:
        raise _Cannot("unknown reader")
    if _norm(out_val) != _norm(src_val):
        raise _Fail("output value differs from source")
    return "matches source"


def _file_hash(cfg, p, ctx):
    """File exists, size in range, and (optionally) sha256 equals the expected value."""
    f = _resolve(cfg, p["file"])
    try:
        size = os.stat(f).st_size
    except FileNotFoundError:
        raise _Fail("file missing")
    lo, hi = p.get("min_size"), p.get("max_size")
    if (lo is not None and size < lo) or (hi is not None and size > hi):
        raise _Fail("size %d outside %s..%s" % (size, lo, hi))
    if p.get("sha256") and _sha256_file(f) != p["sha256"]:
        raise _Fail("sha256 differs")
    return "file ok (%d bytes)" % size


def _cross_ref(cfg, p, ctx):
    """Every id in output A also appears in B."""
    a, b = _ids(cfg, p["a"]), _ids(cfg, p["b"])
    missing = a - b
    if missing:
        raise _Fail("%d id(s) in A not found in B" % len(missing))
    return "all %d ids found" % len(a)


def _time_window(cfg, p, ctx):
    """File mtime (or a timestamp field in a JSON file) is within max_age_hours of now."""
    f = _resolve(cfg, p["file"])
    if p.get("path"):
        ts = _parse_ts(_get(_load_json(f), p["path"]))
    else:
        try:
            ts = datetime.fromtimestamp(os.stat(f).st_mtime, timezone.utc)
        except FileNotFoundError:
            raise _Fail("file missing")
    age_h = (_now_dt() - ts).total_seconds() / 3600.0
    if age_h > float(p["max_age_hours"]) or age_h < -0.1:
        raise _Fail("age %.1f h outside window of %s h" % (age_h, p["max_age_hours"]))
    return "age %.1f h" % age_h


def _known_answer(cfg, p, ctx):
    """Run a human-reviewed argv (params.reviewed_hash, no shell, minimal env) in a temp copy; stdout must equal expected."""
    cmd = p.get("command")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) for c in cmd):
        raise _Cannot("command must be a non-empty list")
    if not p.get("reviewed_hash") or p["reviewed_hash"] != known_answer_hash(cfg, p):
        raise _Cannot("not reviewed")  # free-form code needs the same human review gate as custom checks
    d = _temp_copy(cfg, p.get("copy"))
    try:
        r = subprocess.run(cmd, input=p.get("stdin", ""), capture_output=True, text=True,
                           cwd=d, env=_min_env(d), timeout=p.get("timeout", TIMEOUT_S))
    except subprocess.TimeoutExpired:
        raise _Cannot("timed out")
    except OSError as e:
        raise _Cannot("could not run (%s)" % type(e).__name__)
    finally:
        _rm_tree(d)
    if r.returncode != 0:
        raise _Fail("command exited %d" % r.returncode)
    if r.stdout.strip() != str(p["expected"]).strip():
        raise _Fail("output differs from expected")
    return "known answer matched"


def _custom(cfg, p, ctx):
    """Run a human-reviewed script read-only on a temp copy of the outputs; exit 0 = pass."""
    script = _resolve(cfg, p["script"])
    try:
        actual = _sha256_file(script)
    except FileNotFoundError:
        raise _Cannot("script missing")
    if not p.get("reviewed_hash") or p["reviewed_hash"] != actual:
        raise _Cannot("custom check not reviewed (hash mismatch)")
    d = _temp_copy(cfg, p.get("outputs"))
    try:
        _make_readonly(d)
        env = _min_env(d)
        try:
            r = subprocess.run([sys.executable, script] + [str(a) for a in p.get("args", [])],
                               capture_output=True, text=True, cwd=d, env=env,
                               timeout=p.get("timeout", TIMEOUT_S))
        except subprocess.TimeoutExpired:
            raise _Cannot("timed out")
    finally:
        _rm_tree(d)
    if r.returncode != 0:
        raise _Fail("script exited %d" % r.returncode)
    return "reviewed script passed"


TYPES = {"field_present": _field_present, "count_in_range": _count_in_range,
         "rederive": _rederive, "file_hash": _file_hash, "cross_ref": _cross_ref,
         "time_window": _time_window, "known_answer": _known_answer, "custom": _custom}


# ---------------------------------------------------------------- public API

def run_check(cfg, spec, fetcher=None):
    """Run one spec; never raises. Returns {"id","state","detail","ts","independent","agent_claimed"}."""
    cid = spec.get("id", "?") if isinstance(spec, dict) else "?"
    independent = bool(isinstance(spec, dict) and str(spec.get("independent_because") or "").strip())
    try:
        fn = TYPES.get(spec.get("type"))
        if fn is None:
            raise _Cannot("unknown check type")
        detail = fn(cfg, spec.get("params") or {}, {"fetcher": fetcher})
        state = "pass"
    except _Fail as e:
        state, detail = "fail", str(e)
    except _Cannot as e:
        state, detail = "could_not_check", str(e)
    except Exception as e:       # any other error: never leak content, just the type
        state, detail = "could_not_check", "error (%s)" % type(e).__name__
    return {"id": cid, "state": state, "detail": detail[:200], "ts": util.now(),
            "independent": independent, "agent_claimed": not independent}


def specs_from_cfg(cfg):
    """Extract the list of check specs from cfg['signals'] (a list, or {'checks': [...]})."""
    s = (cfg or {}).get("signals")
    if isinstance(s, dict):
        s = s.get("checks")
    return [x for x in (s or []) if isinstance(x, dict)]


def run_all(cfg, fetcher=None, write=True):
    """Run every spec in cfg and write <state_dir>/checks.json (a JSON list of results)."""
    results = [run_check(cfg, s, fetcher) for s in specs_from_cfg(cfg)]
    sd = cfg.get("state_dir") if isinstance(cfg, dict) else None
    if write and sd:
        sd = os.path.expanduser(sd)
        util.ensure_private_dir(sd)
        util.secure_write(os.path.join(sd, "checks.json"), json.dumps(results, indent=1))
    return results


def fault_test(cfg, spec, break_fn, restore_fn=None, fetcher=None):
    """Confirm a check passes, goes red (state fail) after break_fn(), then optionally restore.

    Returns {"id","baseline","after_break","detects_break"}; detects_break is True only
    when baseline=pass and after_break=fail (could_not_check does NOT count as detection).
    """
    before = run_check(cfg, spec, fetcher)["state"]
    try:
        break_fn()
        after = run_check(cfg, spec, fetcher)["state"]
    finally:
        if restore_fn:
            restore_fn()
    return {"id": spec.get("id"), "baseline": before, "after_break": after,
            "detects_break": before == "pass" and after == "fail"}
