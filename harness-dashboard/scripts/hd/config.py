# config.py - load harness.json, fill defaults, expand ~, and report the effective mode.
import copy
import json
import os

DEFAULTS = {
    "name": "harness",
    "mode": None,
    "goal": "",
    "channel_path": None,
    "state_dir": None,  # derived from name when absent
    "data_sources": [],
    "wall": {"tier": "none", "container_name": None, "config_files": [], "allowlist_hosts": []},
    "expected_run_by": None,
    "stuck": {"no_event_minutes": 10, "repeat_call_limit": 5, "same_file_edit_limit": 8,
              "subagent_outlive_factor": 3.0, "budget_tool_calls": 500},
    "retention": {"metadata_days": 90, "content_days": 7, "capture_content": False},
    "scan": {"extra_patterns": []},
    "transcript_cleanup_days": None,
    "disk_encryption": None,
    "dependencies": {"lockfile": None, "last_reviewed": None},
    "declared": {"permissions": [], "env": [], "hosts": [], "mcp_servers": []},
    "signals": [],
    "middle": {"panels": []},
    "hook_settings_path": None,
}


def _merge(default, given):
    """Recursively overlay given onto a deep copy of default (dict values merge, others replace)."""
    out = copy.deepcopy(default)
    for k, v in given.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _expand(p):
    """Expand ~ in a path string; leave None and non-strings alone."""
    return os.path.expanduser(p) if isinstance(p, str) else p


def load(path):
    """Read a harness.json, fill defaults, expand ~ in path fields, and return the config dict."""
    path = os.path.abspath(os.path.expanduser(path))
    with open(path, "r", encoding="utf-8") as f:
        given = json.load(f)
    if not isinstance(given, dict):
        raise ValueError("harness.json must contain a JSON object")
    cfg = _merge(DEFAULTS, given)
    if not isinstance(cfg.get("name"), str) or not cfg["name"]:
        cfg["name"] = "harness"
    if not cfg.get("state_dir"):
        cfg["state_dir"] = os.path.join("~", ".harness-dashboard", cfg["name"])
    cfg["state_dir"] = _expand(cfg["state_dir"])
    cfg["channel_path"] = _expand(cfg["channel_path"])
    cfg["hook_settings_path"] = _expand(cfg["hook_settings_path"])
    cfg["data_sources"] = [_expand(x) for x in cfg["data_sources"]]
    cfg["wall"]["config_files"] = [_expand(x) for x in cfg["wall"]["config_files"]]
    cfg["dependencies"]["lockfile"] = _expand(cfg["dependencies"]["lockfile"])
    for srv in cfg["declared"]["mcp_servers"]:
        if isinstance(srv, dict) and "tools_file" in srv:
            srv["tools_file"] = _expand(srv["tools_file"])
    cfg["config_path"] = path
    return cfg


def effective_mode(cfg):
    """Return (mode, mode_set): 'standard' only if explicitly set so; anything else is ('strict', False/True)."""
    mode = cfg.get("mode")
    if mode == "standard":
        return ("standard", True)
    if mode == "strict":
        return ("strict", True)
    return ("strict", False)
