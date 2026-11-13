"""Tests for hd/scan.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from hd import scan  # noqa: E402

BANNERS = {
    "CUI": "CUI//SP-EXPT",
    "CONTROLLED UNCLASSIFIED": "Controlled Unclassified Information",
    "FOUO": "FOUO - handle accordingly",
    "ITAR": "This data is ITAR restricted",
    "EAR": "Subject to the EAR. ECCN EAR99",
    "export controlled": "This drawing is export controlled",
    "22 CFR": "per 22 CFR 120-130",
    "15 CFR": "15 CFR Parts 730-774",
    "USML": "USML Category VIII",
    "ECCN": "ECCN 9A610",
    "DFARS 252.204-7012": "DFARS 252.204-7012 applies",
    "Distribution Statement": "DISTRIBUTION STATEMENT D",
    "NOFORN": "SECRET//NOFORN",
}


def ev(**kw):
    """Build a minimal event dict."""
    return dict({"event_id": "h-1", "kind": "tool_post"}, **kw)


class ScanTests(unittest.TestCase):
    """Marking scan behavior."""

    def test_every_default_pattern_hits(self):
        """Each default pattern fires on its banner sample, in content.output."""
        names = {n for n, _ in scan.DEFAULT_PATTERNS}
        self.assertEqual(names, set(BANNERS))
        for name, text in BANNERS.items():
            s = scan.Scanner()
            hits = s.scan_event(ev(content={"output": "line\n" + text + "\nmore"}))
            self.assertIn(name, [h["pattern"] for h in hits], name)

    def test_benign_text_no_hit(self):
        """False-positive guards: year/ear/Ear/cuisine/near and distribution statements A or lowercase words."""
        s = scan.Scanner()
        for t in ("I hear the year is near", "cuisine", "Ear protection, Ear", "the CUIs", "distribution statement A",
                  "bear itar", "security", "Distribution statements are fine"):
            self.assertEqual(s.scan_event(ev(content={"output": t})), [], t)

    def test_hit_has_no_text(self):
        """A hit holds only pattern, event_id, source; never matched text."""
        s = scan.Scanner()
        hits = s.scan_event(ev(content={"input": {"cmd": "echo NOFORN-secret-xyz"}}, file_path="/tmp/ITAR_notes.txt"))
        self.assertEqual({h["source"] for h in hits}, {"content.input", "file_path"})
        for h in hits:
            self.assertEqual(set(h), {"pattern", "event_id", "source"})
            self.assertNotIn("secret-xyz", str(h))
            self.assertEqual(h["event_id"], "h-1")

    def test_task_scanned(self):
        """task field is scanned."""
        self.assertEqual(scan.Scanner().scan_event(ev(task="review USML list"))[0]["source"], "task")

    def test_not_scannable(self):
        """Binary extensions and NUL bytes count as not_scannable, not scanned."""
        s = scan.Scanner()
        s.scan_event(ev(file_path="/x/part.SLDPRT"))
        s.scan_event(ev(file_path="/x/pic.png"))
        s.scan_event(ev(content={"output": "ab\x00cd NOFORN"}))
        s.scan_event(ev(content={"output": "plain text"}))
        self.assertEqual(s.counts, {"scanned": 1, "not_scannable": 3, "hits": 0})

    def test_filename_of_binary_still_scanned(self):
        """A marking in a binary file's name is still caught."""
        s = scan.Scanner()
        self.assertEqual(len(s.scan_event(ev(file_path="/x/ITAR_bracket.step"))), 1)
        self.assertEqual(s.counts["not_scannable"], 1)

    def test_extra_patterns(self):
        """Per-harness extra patterns work and bad regexes are skipped."""
        s = scan.Scanner([{"name": "program X", "regex": r"Project\s+Falcon"}, {"name": "bad", "regex": "("}])
        hits = s.scan_event(ev(content={"output": "about Project Falcon"}))
        self.assertEqual(hits[0]["pattern"], "program X")
        self.assertEqual(s.bad_patterns, ["bad"])

    def test_counts_hits(self):
        """counts.hits accumulates."""
        s = scan.Scanner()
        s.scan_event(ev(content={"output": "ITAR and NOFORN"}))
        self.assertEqual(s.counts["hits"], 2)
        self.assertEqual(s.counts["scanned"], 1)


if __name__ == "__main__":
    unittest.main()
