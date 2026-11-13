# approval.py - hashes everything that was approved so any later change marks the dashboard stale.
"""Approval set: signals, verifier code, hook config, wall config, MCP tool definitions."""
import hashlib
import json
import os

from . import util
from . import wall as _wall
from . import checks as _checks
from . import records as _records

PARTS = ("signals", "verifier_code", "hook_config", "wall_config", "mcp_tools")


def canon(obj):
    """Deterministic JSON text: sorted keys, fixed separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def h(obj):
    """sha256 of the canonical JSON of obj."""
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def _file_hash(path):
    """sha256 of a file's bytes, or the string 'missing'."""
    try:
        with open(os.path.expanduser(str(path)), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return "missing"


def _hook_section(cfg):
    """The 'hooks' object of the settings file at cfg['hook_settings_path'] (or a marker)."""
    p = cfg.get("hook_settings_path")
    if not p:
        return {"unset": True}
    try:
        with open(os.path.expanduser(p), "r", encoding="utf-8") as f:
            return {"hooks": json.load(f).get("hooks")}
    except FileNotFoundError:
        return {"missing": True}
    except (ValueError, AttributeError):
        return {"unreadable": True}


def compute(cfg, runner=None):
    """Return {"parts": {...5 hashes...}, "total": h, "wall_live": hash|None}."""
    specs = _checks.specs_from_cfg(cfg)
    code = {s.get("id", "?"): _file_hash(_checks._resolve(cfg, (s.get("params") or {}).get("script", "")))
            for s in specs if s.get("type") == "custom"}
    wall = cfg.get("wall") or {}
    live = _wall.live_hash(cfg, runner) if wall.get("tier") == "container" else (
        _wall.vm_hash(cfg, runner) if wall.get("tier") == "vm" and wall.get("check_cmd") else None)
    wall_part = {"declared": wall, "live": live,
                 "files": {str(f): _file_hash(f) for f in (wall.get("config_files") or [])}}
    tools = {str(m.get("name")): (_file_hash(m["tools_file"]) if m.get("tools_file") else "no tools_file")
             for m in ((cfg.get("declared") or {}).get("mcp_servers") or [])}
    parts = {"signals": h(cfg.get("signals")), "verifier_code": h(code), "hook_config": h(_hook_section(cfg)),
             "wall_config": h(wall_part), "mcp_tools": h(tools)}
    return {"parts": parts, "total": h(parts), "wall_live": live}


def _path(cfg):
    """Location of approval.json in the state dir."""
    return os.path.join(os.path.expanduser(cfg["state_dir"]), "approval.json")


def load(cfg):
    """Read approval.json, or None if never approved / unreadable."""
    try:
        with open(_path(cfg), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def approve(cfg, runner=None, recs=None):
    """Store the current hash set as approved and record old/new hash in the records log."""
    new = compute(cfg, runner)
    old = load(cfg)
    old_total = old.get("total") if old else "none"
    sd = os.path.expanduser(cfg["state_dir"])
    util.ensure_private_dir(sd)
    util.secure_write(_path(cfg), json.dumps({"ts": util.now(), "parts": new["parts"], "total": new["total"],
                                              "wall_live": new["wall_live"]}, indent=1))
    (recs or _records.Records(sd)).approval(old_total, new["total"], new["parts"])
    return new


def status(cfg, runner=None):
    """Return {"approved","stale","changed_parts"}; never-approved is approved False, stale False."""
    old = load(cfg)
    if not old:
        return {"approved": False, "stale": False, "changed_parts": []}
    cur = compute(cfg, runner)
    changed = [p for p in PARTS if cur["parts"].get(p) != (old.get("parts") or {}).get(p)]
    return {"approved": True, "stale": bool(changed), "changed_parts": changed}
