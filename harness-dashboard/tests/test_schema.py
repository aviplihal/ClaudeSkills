# Tests for the hd module named in the file name (stdlib unittest only).
import json, os, stat, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hd import schema


def good(**kw):
    """Build a valid event dict, overridden by kw."""
    e = {"v": 1, "harness": "h", "session_id": "s", "kind": "tool_pre", "agent_ts": "t"}
    e.update(kw)
    return e


class TestSchema(unittest.TestCase):
    """Tests for hd.schema.validate."""

    def test_ok(self):
        """A valid event passes and keeps optional fields."""
        ev, err = schema.validate(json.dumps(good(tool_name="Bash", status="ok", agent_id=None, content={"input": "x"})))
        self.assertIsNone(err)
        self.assertEqual(ev["tool_name"], "Bash")
        self.assertIn("agent_id", ev)

    def test_unknown_keys_dropped(self):
        """Unknown top-level keys (including recv_ts/event_id) are dropped."""
        ev, err = schema.validate(json.dumps(good(evil="x", recv_ts="1", event_id="h-1")))
        self.assertIsNone(err)
        for k in ("evil", "recv_ts", "event_id"):
            self.assertNotIn(k, ev)

    def test_too_large(self):
        """Lines over 64 KiB are rejected."""
        ev, err = schema.validate(json.dumps(good(task="a" * 70000)))
        self.assertIsNone(ev)
        self.assertIn("large", err)
        ok, _ = schema.validate(json.dumps(good(task="a" * 60000)))
        self.assertIsNotNone(ok)

    def test_bad_json_and_types(self):
        """Garbage, non-objects, None, bytes-garbage are rejected without raising."""
        for raw in ["{nope", "[1]", "null", "", "\x00", None, 5, b"\xff\xfe"]:
            ev, err = schema.validate(raw)
            self.assertIsNone(ev, raw)
            self.assertTrue(err)

    def test_missing_and_wrong_required(self):
        """Each required field missing or mistyped is rejected."""
        for k in ("v", "harness", "session_id", "kind", "agent_ts"):
            e = good()
            del e[k]
            self.assertIsNone(schema.validate(json.dumps(e))[0], k)
        for k, bad in [("v", 2), ("v", True), ("v", "1"), ("harness", 3), ("session_id", None), ("agent_ts", 5)]:
            self.assertIsNone(schema.validate(json.dumps(good(**{k: bad})))[0], k)

    def test_unknown_kind_and_optional_types(self):
        """Unknown kind, bad status, wrong optional types are rejected."""
        self.assertIsNone(schema.validate(json.dumps(good(kind="rm_rf")))[0])
        self.assertIsNone(schema.validate(json.dumps(good(kind=3)))[0])
        self.assertIsNone(schema.validate(json.dumps(good(status="weird")))[0])
        self.assertIsNone(schema.validate(json.dumps(good(content="str")))[0])
        self.assertIsNone(schema.validate(json.dumps(good(extra=[1])))[0])
        self.assertIsNone(schema.validate(json.dumps(good(file_path=7)))[0])

    def test_all_kinds(self):
        """Every documented kind is accepted."""
        for k in schema.KINDS:
            self.assertIsNotNone(schema.validate(json.dumps(good(kind=k)))[0], k)
        self.assertEqual(len(schema.KINDS), 13)


if __name__ == "__main__":
    unittest.main()
