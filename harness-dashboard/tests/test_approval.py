# Tests for the approval module (stdlib unittest only; docker is faked).
import os, sys, json, tempfile, unittest, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from hd import approval, records, checks


class TestApproval(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d, True)
        self.f = self._mk
        self.settings = self.f("settings.json", json.dumps({"hooks": {"PreToolUse": ["a"]}, "other": 1}))
        self.tools = self.f("tools.json", "[1]")
        self.script = self.f("v.py", "print(1)")
        self.wallcfg = self.f("wall.cfg", "net=none")
        self.cfg = {"state_dir": os.path.join(self.d, "st"), "hook_settings_path": self.settings,
                    "signals": [{"id": "x", "type": "custom", "params": {"script": self.script}}],
                    "wall": {"tier": "vm", "config_files": [self.wallcfg]},
                    "declared": {"mcp_servers": [{"name": "m", "tools_file": self.tools}]}}
        self.recs = records.Records(self.cfg["state_dir"])

    def _mk(self, n, t):
        """Write a file in the temp dir and return its path."""
        p = os.path.join(self.d, n)
        with open(p, "w") as fh:
            fh.write(t)
        return p

    def test_deterministic_and_key_order_independent(self):
        a = approval.compute(self.cfg)
        b = approval.compute(json.loads(json.dumps(self.cfg)[::1]))
        self.assertEqual(a, b)
        self.assertEqual(approval.canon({"b": 1, "a": 2}), approval.canon({"a": 2, "b": 1}))
        self.assertEqual(set(a["parts"]), set(approval.PARTS))

    def test_status_lifecycle(self):
        self.assertEqual(approval.status(self.cfg), {"approved": False, "stale": False, "changed_parts": []})
        approval.approve(self.cfg, recs=self.recs)
        self.assertEqual(approval.status(self.cfg), {"approved": True, "stale": False, "changed_parts": []})

    def _stale_after(self, mutate, part):
        """Approve, mutate, and assert exactly `part` is reported stale."""
        approval.approve(self.cfg, recs=self.recs)
        mutate()
        st = approval.status(self.cfg)
        self.assertTrue(st["stale"]); self.assertEqual(st["changed_parts"], [part])

    def test_signals_change(self):
        self._stale_after(lambda: self.cfg["signals"][0].update(description="new"), "signals")

    def test_verifier_code_change(self):
        self._stale_after(lambda: open(self.script, "a").write("#x"), "verifier_code")

    def test_hook_config_change_only_hooks_section(self):
        approval.approve(self.cfg, recs=self.recs)
        open(self.settings, "w").write(json.dumps({"hooks": {"PreToolUse": ["a"]}, "other": 2}))
        self.assertFalse(approval.status(self.cfg)["stale"])      # non-hooks edit ignored
        open(self.settings, "w").write(json.dumps({"hooks": {"PreToolUse": ["a", "b"]}}))
        self.assertEqual(approval.status(self.cfg)["changed_parts"], ["hook_config"])

    def test_wall_config_file_change(self):
        self._stale_after(lambda: open(self.wallcfg, "a").write("x"), "wall_config")

    def test_wall_declared_change(self):
        self._stale_after(lambda: self.cfg["wall"].update(tier="container"), "wall_config")

    def test_mcp_tools_change(self):
        self._stale_after(lambda: open(self.tools, "w").write("[1,2]"), "mcp_tools")

    def test_live_container_drift_makes_wall_part_stale(self):
        self.cfg["wall"] = {"tier": "container", "container_name": "c"}
        out = {"v": json.dumps([{"State": {"Running": True}, "Mounts": [], "HostConfig": {"NetworkMode": "none"}}])}
        runner = lambda argv, t: (0, out["v"], "")
        approval.approve(self.cfg, runner=runner, recs=self.recs)
        self.assertFalse(approval.status(self.cfg, runner)["stale"])
        out["v"] = json.dumps([{"State": {"Running": True}, "Mounts": [], "HostConfig": {"NetworkMode": "host"}}])
        self.assertEqual(approval.status(self.cfg, runner)["changed_parts"], ["wall_config"])

    def test_approve_records_old_and_new_hash(self):
        first = approval.approve(self.cfg, recs=self.recs)
        self.cfg["signals"].append({"id": "y"})
        second = approval.approve(self.cfg, recs=self.recs)
        a = self.recs.all("approval")
        self.assertEqual(len(a), 2)
        self.assertEqual(a[0]["new_hash"] if "new_hash" in a[0] else a[0].get("new"), first["total"])
        last = a[1]
        self.assertIn(first["total"], json.dumps(last)); self.assertIn(second["total"], json.dumps(last))
        self.assertEqual(os.stat(os.path.join(self.cfg["state_dir"], "approval.json")).st_mode & 0o777, 0o600)

    def test_missing_files_hash_stably(self):
        os.remove(self.tools)
        self.assertEqual(approval.compute(self.cfg), approval.compute(self.cfg))


if __name__ == "__main__":
    unittest.main()
