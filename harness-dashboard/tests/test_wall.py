# Tests for the wall module (stdlib unittest only; docker is always faked).
import os, sys, json, tempfile, unittest, shutil, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from hd import wall


def inspect_json(running=True, binds=None, mounts=None, priv=False, net="bridge"):
    """Fake `docker inspect` stdout."""
    return json.dumps([{"State": {"Running": running}, "Mounts": mounts or [],
                        "HostConfig": {"Binds": binds or [], "Privileged": priv, "NetworkMode": net, "CapAdd": None}}])


def runner_for(out, rc=0, err=""):
    """Runner returning a canned result and recording calls."""
    calls = []
    def r(argv, timeout):
        calls.append((argv, timeout)); return rc, out, err
    r.calls = calls
    return r


class TestWall(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d, True)
        self.cfg = {"state_dir": self.d, "wall": {"tier": "container", "container_name": "cf"}}

    def approve_with(self, out):
        """Write approval.json holding the live hash of the given inspect output."""
        h = wall.config_hash(json.loads(out)[0])
        with open(os.path.join(self.d, "approval.json"), "w") as f:
            json.dump({"wall_live": h}, f)

    def test_container_running_and_matches(self):
        out = inspect_json(mounts=[{"Type": "bind", "Source": "/drop", "Destination": "/data", "RW": False}])
        self.approve_with(out)
        r = wall.check(self.cfg, runner_for(out))
        self.assertTrue(r["running"]); self.assertTrue(r["config_matches"])
        self.assertIn("config matches approval", r["detail"])

    def test_container_config_drift_detected(self):
        self.approve_with(inspect_json())
        r = wall.check(self.cfg, runner_for(inspect_json(binds=["/home:/h"])))
        self.assertFalse(r["config_matches"])
        self.assertIn("differs", r["detail"])

    def test_not_running(self):
        r = wall.check(self.cfg, runner_for(inspect_json(running=False)))
        self.assertIs(r["running"], False)

    def test_flags_docker_sock_and_privileged(self):
        out = inspect_json(priv=True, mounts=[{"Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock"}])
        r = wall.check(self.cfg, runner_for(out))
        self.assertIn("docker.sock", r["detail"]); self.assertIn("Privileged", r["detail"])
        r2 = wall.check(self.cfg, runner_for(inspect_json(binds=["/var/run/docker.sock:/s"])))
        self.assertIn("docker.sock", r2["detail"])

    def test_docker_errors_give_unknown_not_crash(self):
        self.assertIsNone(wall.check(self.cfg, runner_for("", 1, "Cannot connect to daemon"))["running"])
        self.assertIs(wall.check(self.cfg, runner_for("", 1, "Error: No such object: cf"))["running"], False)
        def boom(a, t): raise subprocess.TimeoutExpired(a, t)
        self.assertIsNone(wall.check(self.cfg, boom)["running"])
        def nodocker(a, t): raise FileNotFoundError()
        self.assertIsNone(wall.check(self.cfg, nodocker)["running"])
        self.assertIsNone(wall.check(self.cfg, runner_for("not json"))["running"])

    def test_inspect_uses_timeout_10(self):
        r = runner_for(inspect_json()); wall.check(self.cfg, r)
        self.assertEqual(r.calls[0][1], 10); self.assertEqual(r.calls[0][0][:2], ["docker", "inspect"])

    def test_account_tier_never_enforced(self):
        r = wall.check({"state_dir": self.d, "wall": {"tier": "account"}})
        self.assertEqual(r["allowlist"], "not enforced"); self.assertIsNone(r["running"])

    def test_none_tier_not_running(self):
        for cfg in ({"state_dir": self.d}, {"state_dir": self.d, "wall": {"tier": "none"}}):
            r = wall.check(cfg); self.assertIs(r["running"], False); self.assertEqual(r["tier"], "none")

    def test_vm_declared_only_unless_check_cmd(self):
        cfg = {"state_dir": self.d, "wall": {"tier": "vm"}}
        self.assertIsNone(wall.check(cfg)["running"])
        cfg["wall"]["check_cmd"] = "vmcheck --x"
        self.assertTrue(wall.check(cfg, runner_for("", 0))["running"])
        self.assertIs(wall.check(cfg, runner_for("", 1))["running"], False)

    def test_container_allowlist_matches_approved_config(self):
        """A running container whose config matches the approval reports the allowlist as matching it."""
        out = inspect_json()
        self.approve_with(out)
        self.assertEqual(wall.check(self.cfg, runner_for(out))["allowlist"], "matches approved config")
        self.assertEqual(wall.check(self.cfg, runner_for(inspect_json(binds=["/h:/h"])))["allowlist"], "unknown")
        self.assertEqual(wall.check(self.cfg, runner_for(inspect_json(running=False)))["allowlist"], "unknown")

    def test_vm_check_cmd_output_hash_vs_approval(self):
        """vm tier: check_cmd stdout hash equal to the approved part -> config matches; else unknown."""
        cfg = {"state_dir": self.d, "wall": {"tier": "vm", "check_cmd": "vmcheck"}}
        with open(os.path.join(self.d, "approval.json"), "w") as f:
            json.dump({"wall_live": wall.vm_hash(cfg, runner_for("rules-v1\n"))}, f)
        ok = wall.check(cfg, runner_for("rules-v1\n"))
        self.assertEqual((ok["running"], ok["config_matches"], ok["allowlist"]), (True, True, "matches approved config"))
        bad = wall.check(cfg, runner_for("rules-v2\n"))
        self.assertEqual((bad["config_matches"], bad["allowlist"]), (False, "unknown"))
        self.assertEqual(wall.check(cfg, runner_for("rules-v1\n", 1))["allowlist"], "unknown")

    def test_account_never_matches(self):
        self.assertEqual(wall.check({"state_dir": self.d, "wall": {"tier": "account"}})["allowlist"], "not enforced")

    def test_never_says_intact(self):
        src = open(wall.__file__).read().lower()
        self.assertNotIn("intact", src)
        for cfg in ({"wall": {"tier": "account"}}, {"wall": {"tier": "vm"}}, {}):
            cfg["state_dir"] = self.d
            self.assertNotIn("intact", json.dumps(wall.check(cfg)).lower())


if __name__ == "__main__":
    unittest.main()
