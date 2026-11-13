# Tests for the hd module named in the file name (stdlib unittest only).
import json, os, stat, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hd import config


class TestConfig(unittest.TestCase):
    """Tests for hd.config."""

    def _load(self, obj):
        """Write obj as harness.json in a temp dir and load it."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "harness.json")
            json.dump(obj, open(p, "w"))
            return config.load(p)

    def test_defaults(self):
        """Missing fields get INTERFACES defaults; state_dir derives from name."""
        c = self._load({"name": "car"})
        self.assertEqual(c["retention"], {"metadata_days": 90, "content_days": 7, "capture_content": False})
        self.assertEqual(c["stuck"]["repeat_call_limit"], 5)
        self.assertEqual(c["stuck"]["budget_tool_calls"], 500)
        self.assertEqual(c["wall"]["tier"], "none")
        self.assertEqual(c["declared"]["mcp_servers"], [])
        self.assertIsNone(c["expected_run_by"])
        self.assertEqual(c["state_dir"], os.path.expanduser("~/.harness-dashboard/car"))

    def test_partial_nested_merge_and_tilde(self):
        """Partial nested dicts merge with defaults; ~ is expanded."""
        c = self._load({"name": "x", "retention": {"content_days": 3}, "channel_path": "~/c.jsonl",
                        "data_sources": ["~/drop"], "state_dir": "~/s"})
        self.assertEqual(c["retention"]["metadata_days"], 90)
        self.assertEqual(c["retention"]["content_days"], 3)
        self.assertEqual(c["channel_path"], os.path.expanduser("~/c.jsonl"))
        self.assertEqual(c["data_sources"], [os.path.expanduser("~/drop")])
        self.assertNotIn("~", c["state_dir"])

    def test_mode(self):
        """Missing or invalid mode is strict and not set; explicit modes are set."""
        self.assertEqual(config.effective_mode(self._load({})), ("strict", False))
        self.assertEqual(config.effective_mode({"mode": "loose"}), ("strict", False))
        self.assertEqual(config.effective_mode({"mode": "strict"}), ("strict", True))
        self.assertEqual(config.effective_mode({"mode": "standard"}), ("standard", True))

    def test_bad_json_raises(self):
        """A non-object config raises ValueError."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.json")
            open(p, "w").write("[1]")
            with self.assertRaises(ValueError):
                config.load(p)


if __name__ == "__main__":
    unittest.main()
