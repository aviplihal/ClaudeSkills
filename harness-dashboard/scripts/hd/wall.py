# wall.py - checks the wall from outside: is it running, does its config match what was approved.
"""Wall check. Reports 'config matches approval', never a claim that nothing escaped.

Docker is called through an injectable runner: runner(argv, timeout) -> (rc, stdout, stderr).
"""
import hashlib
import json
import os
import shlex
import subprocess

DOCKER_TIMEOUT_S = 10


def default_runner(argv, timeout):
    """Run argv (no shell) with a timeout; returns (rc, stdout, stderr)."""
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def _canon(obj):
    """Canonical JSON text: sorted keys, no spaces."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def config_hash(info):
    """Hash of the security-relevant parts of one docker-inspect object."""
    hc = info.get("HostConfig") or {}
    mounts = sorted(({"Type": m.get("Type"), "Source": m.get("Source"), "Destination": m.get("Destination"),
                      "RW": m.get("RW")} for m in (info.get("Mounts") or [])), key=_canon)
    part = {"Mounts": mounts, "NetworkMode": hc.get("NetworkMode"),
            "Binds": sorted(hc.get("Binds") or []), "Privileged": bool(hc.get("Privileged")),
            "CapAdd": sorted(hc.get("CapAdd") or [])}
    return hashlib.sha256(_canon(part).encode()).hexdigest()


def flags(info):
    """Human-readable risk flags: docker.sock mounts, privileged mode, host networking."""
    hc = info.get("HostConfig") or {}
    out = []
    spots = [str(m.get("Source", "")) + " " + str(m.get("Destination", "")) for m in (info.get("Mounts") or [])]
    spots += [str(b) for b in (hc.get("Binds") or [])]
    if any("docker.sock" in s for s in spots):
        out.append("docker.sock mounted")
    if hc.get("Privileged"):
        out.append("Privileged")
    if hc.get("NetworkMode") == "host":
        out.append("host network")
    return out


def inspect(cfg, runner=None):
    """docker inspect the configured container. Returns (info|None, running|None, error|None)."""
    name = ((cfg.get("wall") or {}).get("container_name"))
    if not name:
        return None, None, "no container_name configured"
    try:
        rc, out, err = (runner or default_runner)(["docker", "inspect", str(name)], DOCKER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, None, "docker inspect timed out"
    except OSError:
        return None, None, "docker not available"
    if rc != 0:
        if "no such" in (err or "").lower():
            return None, False, "container not found"
        return None, None, "docker inspect failed"
    try:
        info = json.loads(out)[0]
    except (ValueError, IndexError, TypeError):
        return None, None, "docker inspect output unreadable"
    return info, bool((info.get("State") or {}).get("Running")), None


def live_hash(cfg, runner=None):
    """Config hash of the live container, or None if it cannot be inspected."""
    info, _, _ = inspect(cfg, runner)
    return config_hash(info) if info else None


def _run_vm_cmd(cfg, runner=None):
    """Run the vm tier's check_cmd; return (rc, stdout) or (None, None) if it is absent or cannot run."""
    cmd = (cfg.get("wall") or {}).get("check_cmd")
    if not cmd:
        return None, None
    try:
        rc, out, _ = (runner or default_runner)(shlex.split(cmd) if isinstance(cmd, str) else list(cmd),
                                                DOCKER_TIMEOUT_S)
        return rc, out
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None, None


def vm_hash(cfg, runner=None):
    """sha256 of the vm check_cmd's stdout (rc 0 only), or None; recorded at approval, compared live."""
    rc, out = _run_vm_cmd(cfg, runner)
    return hashlib.sha256((out or "").encode("utf-8", "replace")).hexdigest() if rc == 0 else None


def _approved_live(cfg):
    """The container config hash recorded in approval.json at approval time, or None."""
    try:
        with open(os.path.join(os.path.expanduser(cfg["state_dir"]), "approval.json")) as f:
            return json.load(f).get("wall_live")
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def check(cfg, runner=None):
    """Return {"tier","running","config_matches","allowlist","detail"} for the harness wall."""
    wall = cfg.get("wall") or {}
    tier = wall.get("tier") or "none"
    res = {"tier": tier, "running": None, "config_matches": None, "allowlist": "unknown", "detail": ""}
    if tier == "container":
        info, running, err = inspect(cfg, runner)
        res["running"] = running
        if info is None:
            res["detail"] = err or "container not inspectable"
            return res
        fl = flags(info)
        approved = _approved_live(cfg)
        if approved is not None:
            res["config_matches"] = (config_hash(info) == approved)
        bits = ["running" if running else "not running"]
        bits.append("config matches approval" if res["config_matches"] else
                    "config differs from approval" if res["config_matches"] is False else
                    "no approved config to compare")
        if fl:
            bits.append("flags: " + ", ".join(fl))
        if running and res["config_matches"] is True:
            res["allowlist"] = "matches approved config"  # the network config is part of the approved hash
        res["detail"] = "; ".join(bits)
    elif tier == "vm":
        cmd = wall.get("check_cmd")
        rc, out = _run_vm_cmd(cfg, runner)
        res["running"] = (rc == 0) if rc is not None else None
        bit = "no check command, running not verified"
        if cmd:
            bit = "check command run"
            approved = _approved_live(cfg)
            if rc == 0 and approved is not None:
                match = hashlib.sha256((out or "").encode("utf-8", "replace")).hexdigest() == approved
                res["config_matches"] = match
                if match:
                    res["allowlist"] = "matches approved config"
                bit += "; output " + ("matches approval" if match else "differs from approval")
        res["detail"] = "VM tier declared; " + bit
    elif tier == "account":
        res["allowlist"] = "not enforced"
        res["detail"] = "account separation only; network allowlist not enforced; never green"
    else:
        res["tier"] = "none"
        res["running"] = False
        res["allowlist"] = "not enforced"
        res["detail"] = "no wall configured"
    return res
