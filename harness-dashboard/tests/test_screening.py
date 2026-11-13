# Tests for the screening module (stdlib unittest only).
import os, sys, tempfile, unittest, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from hd import screening, records, util


class TestScreening(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d, True)
        self.src = os.path.join(self.d, "drop"); os.mkdir(self.src)
        self.state = os.path.join(self.d, "state")
        self.cfg = {"data_sources": [self.src], "state_dir": self.state}
        self.recs = records.Records(self.state)
        self.make("a.txt", "aaa"); self.make("b.txt", "bb")

    def make(self, name, text, mtime=None):
        """Create/overwrite a file in the drop folder."""
        p = os.path.join(self.src, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f: f.write(text)
        if mtime: os.utime(p, (mtime, mtime))
        return p

    def test_listing_deterministic_and_sensitive(self):
        c1, h1 = screening.listing([self.src]); c2, h2 = screening.listing([self.src])
        self.assertEqual((c1, h1), (c2, h2)); self.assertEqual(c1, 2)
        self.make("a.txt", "aaaa")
        self.assertNotEqual(screening.listing([self.src])[1], h1)

    def test_listing_missing_source_is_empty(self):
        self.assertEqual(screening.listing([os.path.join(self.d, "nope")])[0], 0)

    def test_never_confirmed_is_none(self):
        self.assertIsNone(screening.changed_since(self.cfg, self.recs))

    def test_confirm_records_and_zero_changes(self):
        count, h = screening.confirm(self.cfg, self.recs)
        rec = self.recs.latest("screening_confirmed")
        self.assertEqual((rec["file_count"], rec["listing_hash"]), (2, h))
        self.assertEqual(screening.changed_since(self.cfg, self.recs), 0)
        self.assertEqual(os.stat(os.path.join(self.state, screening.SIDECAR)).st_mode & 0o777, 0o600)

    def test_counts_new_modified_removed(self):
        screening.confirm(self.cfg, self.recs)
        self.make("c.txt", "new")                      # new
        self.make("a.txt", "changed-content")          # modified (size)
        os.remove(os.path.join(self.src, "b.txt"))     # removed
        self.assertEqual(screening.changed_since(self.cfg, self.recs), 3)

    def test_old_mtime_replacement_still_counted(self):
        screening.confirm(self.cfg, self.recs)
        self.make("a.txt", "AAA", mtime=1000)          # same size, mtime in the past
        self.assertEqual(screening.changed_since(self.cfg, self.recs), 1)

    def test_fallback_without_sidecar(self):
        screening.confirm(self.cfg, self.recs)
        os.remove(os.path.join(self.state, screening.SIDECAR))
        self.assertEqual(screening.changed_since(self.cfg, self.recs), 0)
        self.make("c.txt", "new"); os.remove(os.path.join(self.src, "b.txt"))
        self.assertGreaterEqual(screening.changed_since(self.cfg, self.recs), 1)

    def test_sidecar_holds_no_filenames(self):
        screening.confirm(self.cfg, self.recs)
        self.assertNotIn("a.txt", open(os.path.join(self.state, screening.SIDECAR)).read())


if __name__ == "__main__":
    unittest.main()
