"""Tests for hd/redact.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from hd import redact  # noqa: E402


class RedactTests(unittest.TestCase):
    """Secret redaction, path shortening, event redaction."""

    def test_secret_patterns(self):
        """Each secret family is replaced and counted."""
        samples = ["sk-ant-api03-abcdefghijkl", "sk-abcdefghijklmnopqrstuv", "ghp_" + "a" * 30,
                   "AKIAABCDEFGHIJKLMNOP", "xoxb-1234567890-abcdef", "Authorization: Bearer abc123def456ghi",
                   "API_KEY=hunter2hunter2", "password = 'p@ss word'", "SECRET=abc",
                   "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"]
        for s in samples:
            out, n = redact.redact_text("x " + s + " y")
            self.assertGreaterEqual(n, 1, s)
            self.assertNotIn("hunter2", out)
            self.assertNotIn("abcdefghijkl", out)
            self.assertNotIn("MIIabc", out)

    def test_benign_untouched(self):
        """Normal text passes through with zero redactions."""
        out, n = redact.redact_text("hello world, the key idea is token economy")
        self.assertEqual(n, 0)
        self.assertEqual(out, "hello world, the key idea is token economy")

    def test_shorten_path(self):
        """Shortened path keeps last component (<=16) and a hash, not the directories."""
        s = redact.shorten_path("/secret/program/a_very_long_filename_here.step")
        self.assertTrue(s.startswith("…/a_very_long_file#"))
        self.assertNotIn("secret", s)
        self.assertEqual(len(s.split("#")[1]), 8)
        self.assertEqual(s, redact.shorten_path("/secret/program/a_very_long_filename_here.step"))

    def test_event_strict_strips(self):
        """Strict drops content and shortens file_path/task even if capture is true."""
        ev = {"kind": "tool_pre", "file_path": "/a/b/c.txt", "task": "build secret thing",
              "content": {"input": "x"}}
        out = redact.redact_event(ev, "strict", True)
        self.assertNotIn("content", out)
        self.assertTrue(out["file_path"].startswith("…/c.txt#"))
        self.assertNotIn("secret", out["task"])
        self.assertIn("content", ev)  # input not mutated

    def test_event_standard_capture_off(self):
        """Standard with capture off drops content but keeps path."""
        out = redact.redact_event({"file_path": "/a/b", "content": {"input": "x"}}, "standard", False)
        self.assertNotIn("content", out)
        self.assertEqual(out["file_path"], "/a/b")

    def test_event_standard_capture_on_redacts(self):
        """Standard with capture on redacts secrets inside nested content."""
        ev = {"content": {"input": {"cmd": "export TOKEN=abc123456"}, "output": ["Bearer abcdefghijk"]}}
        out = redact.redact_event(ev, "standard", True)
        self.assertNotIn("abc123456", str(out))
        self.assertNotIn("abcdefghijk", str(out))
        self.assertGreaterEqual(out["extra"]["redactions"], 2)


if __name__ == "__main__":
    unittest.main()
