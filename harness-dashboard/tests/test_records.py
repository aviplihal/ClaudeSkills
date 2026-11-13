# Tests for the hd module named in the file name (stdlib unittest only).
import json, os, stat, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hd import records, util


class TestRecords(unittest.TestCase):
    """Tests for hd.records."""

    def setUp(self):
        """Fixed clock and a temp state dir."""
        util.set_clock(lambda: "2026-01-02T03:04:05Z")
        self.addCleanup(util.set_clock, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sd = os.path.join(self.tmp.name, "state")
        self.r = records.Records(self.sd)

    def test_entries_and_common_fields(self):
        """Every method writes type, ts, os_user and its own fields; chain verifies."""
        self.r.screening_confirmed(["/d"], 4, "abc")
        self.r.approval("o", "n", {"signals": "h"})
        self.r.mode_switch("strict", "standard", True)
        self.r.scan_hit("ITAR", "h-1", "task")
        self.r.incident_note({"told": "me"})
        self.r.retention_hold(True, "hit")
        self.r.compliance_note("Bob", "2026-01-01", "screened data")
        es = self.r.all()
        self.assertEqual([e["type"] for e in es], ["screening_confirmed", "approval", "mode_switch", "scan_hit",
                                                   "incident_note", "retention_hold", "compliance_note"])
        for e in es:
            self.assertEqual(e["ts"], "2026-01-02T03:04:05Z")
            self.assertEqual(e["os_user"], util.os_user())
        self.assertEqual(es[0]["file_count"], 4)
        self.assertEqual(es[3]["source"], "task")
        self.assertEqual(self.r.log.verify(), (True, None))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.sd, "records.jsonl")).st_mode), 0o600)

    def test_latest_all(self):
        """latest and all filter by type; empty gives None / []."""
        self.assertIsNone(self.r.latest("approval"))
        self.assertEqual(self.r.all(), [])
        self.r.mode_switch("a", "b", False)
        self.r.mode_switch("b", "c", True)
        self.assertEqual(self.r.latest("mode_switch")["new"], "c")
        self.assertEqual(len(self.r.all("mode_switch")), 2)
        self.assertEqual(self.r.latest()["new"], "c")
        self.assertEqual(self.r.all("approval"), [])

    def test_hold_active(self):
        """hold_active follows the last retention_hold entry."""
        self.assertFalse(records.hold_active(self.sd))
        self.r.retention_hold(True, "x")
        self.assertTrue(records.hold_active(self.sd))
        self.r.scan_hit("p", "e", "s")
        self.assertTrue(records.hold_active(self.sd))
        self.r.retention_hold(False, "released")
        self.assertFalse(records.hold_active(self.sd))
        self.assertFalse(records.hold_active(os.path.join(self.tmp.name, "nope")))


if __name__ == "__main__":
    unittest.main()
