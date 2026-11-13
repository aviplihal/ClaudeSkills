# Tests for the hd module named in the file name (stdlib unittest only).
import json, os, stat, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hd import chainlog, util


class TestChainLog(unittest.TestCase):
    """Tests for hd.chainlog.ChainLog."""

    def setUp(self):
        """Create a temp dir and a log path inside a new subdirectory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sub", "log.jsonl")
        self.log = chainlog.ChainLog(self.path)

    def fill(self, n=5):
        """Append n entries."""
        for i in range(n):
            self.log.append({"i": i})

    def lines(self):
        """Return the raw file lines (no newline)."""
        return open(self.path, encoding="utf-8").read().split("\n")[:-1]

    def put(self, lines, trailing_nl=True):
        """Overwrite the file with the given lines."""
        open(self.path, "w", encoding="utf-8").write("\n".join(lines) + ("\n" if trailing_nl else ""))

    def test_chain_structure(self):
        """prev is sha of previous stored text; h is sha of canonical JSON without h; genesis is zeros."""
        self.fill(3)
        ls = self.lines()
        objs = [json.loads(x) for x in ls]
        self.assertEqual(objs[0]["prev"], "0" * 64)
        self.assertEqual(objs[1]["prev"], util.sha256_hex(ls[0]))
        self.assertEqual(objs[2]["prev"], util.sha256_hex(ls[1]))
        body = {k: v for k, v in objs[1].items() if k != "h"}
        self.assertEqual(objs[1]["h"], util.sha256_hex(json.dumps(body, sort_keys=True, separators=(",", ":"))))
        self.assertEqual(self.log.verify(), (True, None))

    def test_empty_and_missing(self):
        """A missing file verifies and iterates empty."""
        self.assertEqual(self.log.verify(), (True, None))
        self.assertEqual(list(self.log.iter()), [])

    def test_modes(self):
        """File is 0600 and its new dir is 0700."""
        self.fill(1)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.path)).st_mode), 0o700)

    def test_detect_edit(self):
        """Editing a line is detected at that line."""
        self.fill()
        ls = self.lines()
        o = json.loads(ls[2]); o["i"] = 99; ls[2] = json.dumps(o, sort_keys=True, separators=(",", ":"))
        self.put(ls)
        self.assertEqual(self.log.verify(), (False, 3))

    def test_detect_edit_with_recomputed_h(self):
        """Editing a line and fixing its h still breaks at the next line."""
        self.fill()
        ls = self.lines()
        o = json.loads(ls[2]); o["i"] = 99; o.pop("h")
        o["h"] = util.sha256_hex(json.dumps(o, sort_keys=True, separators=(",", ":")))
        ls[2] = json.dumps(o, sort_keys=True, separators=(",", ":"))
        self.put(ls)
        self.assertEqual(self.log.verify(), (False, 4))

    def test_detect_delete(self):
        """Deleting a middle line is detected where the gap is."""
        self.fill()
        ls = self.lines()
        del ls[2]
        self.put(ls)
        self.assertEqual(self.log.verify(), (False, 3))

    def test_detect_delete_first(self):
        """Deleting the first line is detected at line 1."""
        self.fill()
        self.put(self.lines()[1:])
        self.assertEqual(self.log.verify(), (False, 1))

    def test_detect_reorder(self):
        """Swapping two lines is detected."""
        self.fill()
        ls = self.lines()
        ls[1], ls[2] = ls[2], ls[1]
        self.put(ls)
        self.assertEqual(self.log.verify(), (False, 2))

    def test_detect_truncated_last(self):
        """A partially written last line, or a missing final newline, is detected."""
        self.fill()
        ls = self.lines()
        self.put(ls[:-1] + [ls[-1][:20]], trailing_nl=False)
        self.assertEqual(self.log.verify(), (False, 5))
        self.put(ls, trailing_nl=False)
        self.assertEqual(self.log.verify(), (False, 5))

    def test_append_after_truncation_stays_broken(self):
        """Appending after a truncated line does not hide the break."""
        self.fill(3)
        ls = self.lines()
        self.put(ls[:-1] + [ls[-1][:20]], trailing_nl=False)
        self.log.append({"i": 7})
        self.assertEqual(self.log.verify(), (False, 3))

    def test_append_returns_entry_and_iter(self):
        """append returns the stored dict; iter yields entries in order."""
        e = self.log.append({"a": 1, "prev": "x", "h": "y"})
        self.assertEqual(e["prev"], "0" * 64)
        self.log.append({"a": 2})
        self.assertEqual([x["a"] for x in self.log.iter()], [1, 2])

    def test_threads(self):
        """Concurrent appenders (two instances, many threads) keep the chain valid."""
        other = chainlog.ChainLog(self.path)

        def work(lg, base):
            """Append 25 entries."""
            for i in range(25):
                lg.append({"n": base + i})
        ts = [threading.Thread(target=work, args=(self.log if k % 2 else other, k * 100)) for k in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(list(self.log.iter())), 150)
        self.assertEqual(self.log.verify(), (True, None))

    def test_large_line_tail(self):
        """Tail reading works for lines bigger than the first read chunk."""
        self.log.append({"big": "x" * 50000})
        self.log.append({"i": 1})
        self.assertEqual(self.log.verify(), (True, None))

    def test_rewrite_without(self):
        """Purge removes matches, writes a chain_rebased marker first, and the chain still verifies."""
        self.fill(6)
        old_tail = util.sha256_hex(self.lines()[-1])
        n = self.log.rewrite_without(lambda e: e.get("i", 99) < 3)
        self.assertEqual(n, 3)
        ents = list(self.log.iter())
        self.assertEqual(ents[0]["type"], "chain_rebased")
        self.assertEqual(ents[0]["removed"], 3)
        self.assertEqual(ents[0]["old_tail_hash"], old_tail)
        self.assertEqual([e["i"] for e in ents[1:]], [3, 4, 5])
        self.assertEqual(self.log.verify(), (True, None))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.log.append({"i": 6})
        self.assertEqual(self.log.verify(), (True, None))

    def test_rewrite_nothing_and_everything(self):
        """No match leaves the file untouched; removing all leaves just the marker."""
        self.fill(2)
        before = open(self.path).read()
        self.assertEqual(self.log.rewrite_without(lambda e: False), 0)
        self.assertEqual(open(self.path).read(), before)
        self.assertEqual(self.log.rewrite_without(lambda e: True), 2)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.log.verify(), (True, None))
        self.assertEqual(chainlog.ChainLog(os.path.join(self.tmp.name, "none")).rewrite_without(lambda e: True), 0)

    def test_sync_warning(self):
        """A path inside a sync folder produces a warning; a normal path does not."""
        self.assertEqual(self.log.warnings, [])
        w = chainlog.ChainLog(os.path.join(self.tmp.name, "Dropbox", "l.jsonl"))
        self.assertTrue(w.warnings)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "Dropbox")))


if __name__ == "__main__":
    unittest.main()
