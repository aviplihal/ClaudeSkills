# screening.py - fingerprints the declared data sources so drift since "I screened these" is visible.
"""Screening statement support: file listing hash and changed-since count.

Filenames are never stored: the sidecar snapshot holds only hashed keys.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from . import util
from . import records as _records

SIDECAR = "screening_listing.json"     # <state_dir>/: hashed-key snapshot taken at confirm time


def _snapshot(sources):
    """Return {key: (size, mtime_ns)} for every regular file under the sources (symlinks not followed)."""
    snap = {}
    for src in sources or []:
        root = os.path.expanduser(str(src))
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root, followlinks=False):
            for n in fns:
                fp = os.path.join(dp, n)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                key = "%s\t%s" % (root, os.path.relpath(fp, root))
                snap[key] = (st.st_size, st.st_mtime_ns)
    return snap


def _hash_snapshot(snap):
    """sha256 over sorted 'path size mtime_ns' lines."""
    lines = ["%s\t%d\t%d" % (k, v[0], v[1]) for k, v in sorted(snap.items())]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def listing(sources):
    """Return (file_count, listing_hash) over relative path + size + mtime_ns of all files."""
    snap = _snapshot(sources)
    return len(snap), _hash_snapshot(snap)


def _hk(key):
    """Short hash of a snapshot key so the sidecar holds no filenames."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _last_screening(records):
    """Latest screening record from a Records-like object (tries both plausible type names)."""
    for t in ("screening_confirmed", "screening"):
        rec = records.latest(t)
        if rec:
            return rec
    return None


def _ts_ns(ts):
    """ISO-8601 Z timestamp -> epoch nanoseconds."""
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def _load_sidecar(cfg):
    """Read the confirm-time snapshot, or None."""
    try:
        with open(os.path.join(os.path.expanduser(cfg["state_dir"]), SIDECAR), "r") as f:
            return json.load(f)
    except (OSError, ValueError, KeyError):
        return None


def changed_since(cfg, records):
    """Count files new/modified/removed since the last screening record; None if never confirmed."""
    last = _last_screening(records)
    if not last:
        return None
    snap = _snapshot(cfg.get("data_sources"))
    cur_hash = _hash_snapshot(snap)
    if last.get("listing_hash") == cur_hash:
        return 0
    side = _load_sidecar(cfg)
    if side and side.get("listing_hash") == last.get("listing_hash"):
        old = side.get("files", {})
        cur = {_hk(k): list(v) for k, v in snap.items()}
        new = sum(1 for k in cur if k not in old)
        removed = sum(1 for k in old if k not in cur)
        modified = sum(1 for k in cur if k in old and cur[k] != old[k])
        return new + removed + modified
    # fallback (no exact snapshot): mtime newer than the record, plus a shrinking file count
    try:
        t_ns = _ts_ns(last["ts"])
        newer = sum(1 for v in snap.values() if v[1] > t_ns)
    except (KeyError, ValueError):
        newer = 0
    removed = max(0, int(last.get("file_count") or 0) - len(snap))
    return max(1, newer + removed)     # hash differs, so at least one thing changed


def confirm(cfg, recs=None):
    """Record 'I screened these sources now': hash listing, write sidecar, append a record."""
    sources = cfg.get("data_sources") or []
    snap = _snapshot(sources)
    count, h = len(snap), _hash_snapshot(snap)
    sd = os.path.expanduser(cfg["state_dir"])
    util.ensure_private_dir(sd)
    util.secure_write(os.path.join(sd, SIDECAR), json.dumps(
        {"listing_hash": h, "files": {_hk(k): list(v) for k, v in snap.items()}}))
    (recs or _records.Records(sd)).screening_confirmed(sources, count, h)
    return count, h
