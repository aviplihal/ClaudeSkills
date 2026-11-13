"""Tests for hd/collector.py (uses Builder A's storage modules)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from hd import collector, config, records, util  # noqa: E402


def line(**kw):
    """Build one valid channel line (JSON text)."""
    ev = {"v": 1, "harness": "t", "session_id": "s1", "kind": "tool_post", "agent_ts": "2000-01-01T00:00:00Z",
          "tool_name": "Bash"}
    ev.update(kw)
    return json.dumps(ev)


class CollectorTests(unittest.TestCase):
    """Collector ingest, scan, redaction, retention."""

    def setUp(self):
        """Temp state dir and channel; fixed clock."""
        self.d = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.d.name, "state")
        self.ch = os.path.join(self.d.name, "chan.jsonl")
        open(self.ch, "w").close()
        self.now = "2026-01-10T00:00:00Z"
        util.set_clock(lambda: self.now)

    def tearDown(self):
        """Restore clock and clean up."""
        util.set_clock(None)
        self.d.cleanup()

    def mk(self, mode="standard", capture=False, **over):
        """Create a Collector with a config dict."""
        cfg = {"name": "t", "mode": mode, "state_dir": self.state, "channel_path": self.ch,
               "retention": {"metadata_days": 90, "content_days": 7, "capture_content": capture},
               "scan": {"extra_patterns": []}}
        cfg.update(over)
        return collector.Collector(cfg)

    def feed(self, *lines, raw=False):
        """Append lines to the channel."""
        with open(self.ch, "ab") as f:
            for l in lines:
                f.write(l if raw else (l + "\n").encode())

    def events(self, col):
        """Return stored events (excluding chain markers)."""
        return [e for e in col.events.iter() if "event_id" in e]

    def test_ingest_stamps_trusted_times_and_ids(self):
        """recv_ts comes from util.now; agent_ts kept; event ids are sequential."""
        col = self.mk()
        self.feed(line(), line(agent_ts="1999"))
        st = col.poll_once()
        self.assertEqual(st["ingested"], 2)
        evs = self.events(col)
        self.assertEqual([e["event_id"] for e in evs], ["t-1", "t-2"])
        self.assertEqual(evs[0]["recv_ts"], self.now)
        self.assertEqual(evs[1]["agent_ts"], "1999")
        self.assertTrue(col.events.verify()[0])

    def test_rejected_counted_not_echoed(self):
        """Bad JSON, wrong schema, oversized lines count as rejected and are not stored."""
        col = self.mk()
        self.feed("{not json", '{"v":2}', "[1]", line(kind="evil"), "x" * 70000, '{"__import__":"os"}', line())
        col.poll_once()
        hb = json.load(open(os.path.join(self.state, "heartbeat.json")))
        self.assertEqual(hb["rejected"], 6)
        self.assertEqual(len(self.events(col)), 1)
        self.assertNotIn("evil", open(os.path.join(self.state, "events.jsonl")).read())

    def test_unterminated_oversize_tail_rejected(self):
        """A huge line without newline is rejected rather than buffered forever."""
        col = self.mk()
        self.feed(b"y" * 70000, raw=True)
        col.poll_once()
        self.assertEqual(col.rejected, 1)

    def test_partial_line_waits(self):
        """A line without trailing newline is not consumed until complete."""
        col = self.mk()
        self.feed(line().encode()[:20], raw=True)
        self.assertEqual(col.poll_once()["ingested"], 0)
        self.feed((line()[20:] + "\n").encode(), raw=True)
        self.assertEqual(col.poll_once()["ingested"], 1)

    def test_offset_persists_across_restart(self):
        """A new Collector does not re-ingest old lines and continues event ids."""
        col = self.mk()
        self.feed(line(), line())
        col.poll_once()
        col2 = self.mk()
        self.assertEqual(col2.poll_once()["ingested"], 0)
        self.feed(line())
        col2.poll_once()
        self.assertEqual([e["event_id"] for e in self.events(col2)], ["t-1", "t-2", "t-3"])

    def test_channel_truncation_resets_offset(self):
        """Offset beyond file size resets to 0, is recorded in heartbeat, and new data is ingested."""
        col = self.mk()
        self.feed(line(), line())
        col.poll_once()
        open(self.ch, "w").close()
        self.feed(line())
        st = col.poll_once()
        self.assertTrue(st["offset_reset"])
        self.assertEqual(st["ingested"], 1)
        hb = json.load(open(os.path.join(self.state, "heartbeat.json")))
        self.assertEqual(hb["offset_resets"], 1)

    def test_missing_channel_still_heartbeats(self):
        """No channel file: no crash, heartbeat still written."""
        os.unlink(self.ch)
        col = self.mk()
        col.poll_once()
        hb = json.load(open(os.path.join(self.state, "heartbeat.json")))
        self.assertTrue(hb["chain_ok"])
        self.assertEqual(hb["pid"], os.getpid())

    def test_strict_strips_content_and_shortens(self):
        """Strict: no content stored even if capture is on; file_path/task shortened."""
        col = self.mk(mode="strict", capture=True)
        self.feed(line(content={"input": "hello"}, file_path="/proj/dir/file.txt", task="build a widget"))
        col.poll_once()
        e = self.events(col)[0]
        self.assertNotIn("content", e)
        self.assertTrue(e["file_path"].startswith("…/file.txt#"))
        self.assertNotIn("widget", e["task"])

    def test_mode_unset_is_strict(self):
        """mode None behaves as strict."""
        col = self.mk(mode=None, capture=True)
        self.feed(line(content={"input": "hello"}, file_path="/a/b.txt"))
        col.poll_once()
        self.assertNotIn("content", self.events(col)[0])

    def test_standard_capture_off_no_content(self):
        """Standard with capture off stores no content but keeps the path."""
        col = self.mk()
        self.feed(line(content={"input": "hello"}, file_path="/a/b.txt"))
        col.poll_once()
        e = self.events(col)[0]
        self.assertNotIn("content", e)
        self.assertEqual(e["file_path"], "/a/b.txt")

    def test_standard_capture_on_redacts_secret(self):
        """Standard+capture keeps content with secrets redacted."""
        col = self.mk(capture=True)
        self.feed(line(content={"input": "run", "output": "TOKEN=abcdef123456 done"}))
        col.poll_once()
        c = self.events(col)[0]["content"]
        self.assertNotIn("abcdef123456", json.dumps(c))
        self.assertEqual(c["input"], "run")

    def test_scan_hit_records_hold_incident_no_text(self):
        """A hit writes scan_hit, hold, open incident stub, and never stores the matched text, even in strict."""
        col = self.mk(mode="strict")
        self.feed(line(content={"output": "header NOFORN-ZEBRA9"}))
        col.poll_once()
        rec = records.Records(self.state)
        hit = rec.latest("scan_hit")
        self.assertEqual((hit["pattern"], hit["event_id"], hit["source"]), ("NOFORN", "t-1", "content.output"))
        self.assertTrue(records.hold_active(self.state))
        note = rec.latest("incident_note")["fields"]
        self.assertEqual(note, {"status": "open", "pattern": "NOFORN", "event_id": "t-1"})
        for fn in ("events.jsonl", "records.jsonl"):
            self.assertNotIn("ZEBRA9", open(os.path.join(self.state, fn)).read())
        counts = json.load(open(os.path.join(self.state, "scan_counts.json")))
        self.assertEqual(counts["hits"], 1)
        self.assertEqual(counts["scanned"], 1)

    def test_scan_counts_accumulate_and_survive_restart(self):
        """scan_counts.json accumulates across polls and restarts."""
        col = self.mk()
        self.feed(line(content={"output": "a"}), line(file_path="/x/p.png"))
        col.poll_once()
        col2 = self.mk()
        self.feed(line(content={"output": "b"}))
        col2.poll_once()
        counts = json.load(open(os.path.join(self.state, "scan_counts.json")))
        self.assertEqual(counts, {"scanned": 2, "not_scannable": 1, "hits": 0})

    def test_purge_drops_old_and_strips_content(self):
        """Without a hold: events past metadata_days drop, content past content_days is stripped."""
        col = self.mk(capture=True)
        for ts in ("2025-06-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-09T00:00:00Z"):
            self.now = ts
            self.feed(line(content={"output": "data"}))
            col.poll_once()
        self.now = "2026-01-10T00:00:00Z"
        res = col.purge()
        self.assertFalse(res["skipped"])
        self.assertEqual(res["removed"], 1)
        evs = self.events(col)
        self.assertEqual(len(evs), 2)
        self.assertNotIn("content", evs[0])  # 9 days old > 7
        self.assertIn("content", evs[1])
        self.assertTrue(col.events.verify()[0])

    def test_purge_strip_only_when_nothing_removed(self):
        """Content stripping works even when no event is old enough to be deleted."""
        col = self.mk(capture=True)
        self.now = "2026-01-01T00:00:00Z"
        self.feed(line(content={"output": "data"}))
        col.poll_once()
        self.now = "2026-01-10T00:00:00Z"
        res = col.purge()
        self.assertEqual((res["removed"], res["stripped"]), (0, 1))
        self.assertNotIn("content", self.events(col)[0])
        self.assertTrue(col.events.verify()[0])

    def test_purge_skipped_while_hold_active(self):
        """After a scan hit, purge deletes and strips nothing, even for ancient events."""
        col = self.mk(capture=True)
        self.now = "2025-01-01T00:00:00Z"
        self.feed(line(content={"output": "old data"}), line(content={"output": "ITAR drawing"}))
        col.poll_once()
        self.now = "2026-01-10T00:00:00Z"
        before = open(os.path.join(self.state, "events.jsonl")).read()
        res = col.purge()
        self.assertTrue(res["skipped"])
        self.assertEqual(open(os.path.join(self.state, "events.jsonl")).read(), before)
        # releasing the hold lets purge run again
        records.Records(self.state).retention_hold(False, "released")
        self.assertFalse(col.purge()["skipped"])

    def test_chain_break_shown_in_heartbeat(self):
        """Tampering with the event log is reported by verify_chains and heartbeat."""
        col = self.mk()
        self.feed(line(), line())
        col.poll_once()
        p = os.path.join(self.state, "events.jsonl")
        txt = open(p).read().replace('"tool_name":"Bash"', '"tool_name":"Edit"', 1)
        open(p, "w").write(txt)
        ok, brk = col.verify_chains()
        self.assertFalse(ok)
        self.assertEqual(brk, 1)
        col.write_heartbeat()
        hb = json.load(open(os.path.join(self.state, "heartbeat.json")))
        self.assertFalse(hb["chain_ok"])
        self.assertEqual(hb["chain_break_line"], 1)

    # ---- hook-reported scan results

    def scan_extra(self, **sc):
        """Build an extra dict carrying a hook scan result."""
        return {"scan": sc}

    def test_hook_scan_hits_feed_records_hold_and_incident(self):
        """Hook hits (capture off) create a hook:-prefixed record, hold and incident; no text is stored."""
        col = self.mk()
        self.feed(line(extra=self.scan_extra(hits=[{"pattern": "CUI", "source": "tool_response"}], not_scannable=False)))
        col.poll_once()
        hits = col.records.all("scan_hit")
        self.assertEqual([(h["pattern"], h["source"]) for h in hits], [("CUI", "hook:tool_response")])
        self.assertTrue(records.hold_active(self.state))
        self.assertEqual(len(col.records.all("incident_note")), 1)
        ev = self.events(col)[0]
        self.assertEqual(ev["extra"]["scan"]["hits"], [{"pattern": "CUI", "source": "hook:tool_response"}])

    def test_hook_and_collector_hits_deduped_and_counted_once(self):
        """The same pattern seen by both scanners is one record; the event counts as scanned once."""
        col = self.mk(capture=True)
        self.feed(line(content={"output": "this is CUI"}, extra=self.scan_extra(
            hits=[{"pattern": "CUI", "source": "tool_response"}, {"pattern": "ITAR", "source": "prompt"}], not_scannable=False)))
        col.poll_once()
        self.assertEqual(sorted(h["pattern"] for h in col.records.all("scan_hit")), ["CUI", "ITAR"])
        counts = json.load(open(os.path.join(self.state, "scan_counts.json")))
        self.assertEqual((counts["scanned"], counts["not_scannable"], counts["hits"]), (1, 0, 2))

    def test_hook_scan_counts_event_without_visible_fields(self):
        """With capture off the hook's scan is the only evidence; it is counted (scanned or not scannable)."""
        col = self.mk()
        self.feed(line(extra=self.scan_extra(hits=[], not_scannable=False)),
                  line(extra=self.scan_extra(hits=[], not_scannable=True)))
        col.poll_once()
        counts = json.load(open(os.path.join(self.state, "scan_counts.json")))
        self.assertEqual((counts["scanned"], counts["not_scannable"], counts["hits"]), (1, 1, 0))

    def test_hook_scan_validated(self):
        """Untrusted extra.scan: hits capped at 20, names cut to 64, malformed shapes dropped."""
        col = self.mk()
        many = [{"pattern": "P%d" % i, "source": "prompt"} for i in range(50)]
        self.feed(line(extra=self.scan_extra(hits=many + ["x", {"pattern": 5}, {"pattern": "z"}], not_scannable="yes")),
                  line(extra=self.scan_extra(hits=[{"pattern": "N" * 200, "source": "task"}])),
                  line(extra={"scan": "garbage"}), line(extra={"scan": {"hits": "no"}}))
        col.poll_once()
        evs = self.events(col)
        self.assertEqual(len(evs[0]["extra"]["scan"]["hits"]), 20)
        self.assertFalse(evs[0]["extra"]["scan"]["not_scannable"])
        self.assertEqual(len(evs[1]["extra"]["scan"]["hits"][0]["pattern"]), 64)
        self.assertNotIn("scan", evs[2]["extra"])
        self.assertEqual(evs[3]["extra"]["scan"]["hits"], [])

    def test_scan_unavailable_kept_on_event(self):
        """An unavailable marker survives so the dashboard can report it."""
        col = self.mk()
        self.feed(line(extra=self.scan_extra(unavailable=True)))
        col.poll_once()
        self.assertEqual(self.events(col)[0]["extra"]["scan"], {"unavailable": True})
        self.assertEqual(col.records.all("scan_hit"), [])

    # ---- chain integrity

    def test_purge_refuses_on_broken_chain(self):
        """A tampered events log is never rewritten by purge; the refusal is in the heartbeat."""
        self.now = "2020-01-01T00:00:00Z"
        col = self.mk()
        self.feed(line(), line(), line())
        col.poll_once()
        self.now = "2026-01-10T00:00:00Z"
        p = os.path.join(self.state, "events.jsonl")
        txt = open(p).read().replace('"tool_name":"Bash"', '"tool_name":"Edit"', 1)
        open(p, "w").write(txt)
        before = open(p).read()
        res = col.purge()
        self.assertEqual((res["skipped"], res["reason"]), (True, "log chain broken"))
        self.assertEqual(open(p).read(), before)
        self.assertTrue(json.load(open(os.path.join(self.state, "heartbeat.json")))["purge_refused"])

    def test_purge_still_works_and_rebaselines_tail(self):
        """A good purge removes old events and the tail record follows the rewritten file (no false alarm)."""
        self.now = "2020-01-01T00:00:00Z"
        col = self.mk()
        self.feed(line())
        col.poll_once()
        self.now = "2026-01-10T00:00:00Z"
        self.feed(line())
        col.poll_once()
        self.assertEqual(col.purge()["removed"], 1)
        self.assertTrue(col.verify_chains()[0])
        self.assertFalse(json.load(open(os.path.join(self.state, "heartbeat.json")))["purge_refused"])

    def test_tail_recorded_in_heartbeat(self):
        """Heartbeat carries line count and last-line hash for both logs."""
        col = self.mk()
        self.feed(line())
        col.poll_once()
        hb = json.load(open(os.path.join(self.state, "heartbeat.json")))
        self.assertEqual(hb["events_tail"]["lines"], 1)
        self.assertEqual(len(hb["events_tail"]["hash"]), 64)
        self.assertEqual(hb["records_tail"]["lines"], 0)

    def test_deleted_last_event_line_detected_live_and_after_restart(self):
        """Deleting the last line leaves a valid chain, but the remembered tail catches it."""
        col = self.mk()
        self.feed(line(), line(), line())
        col.poll_once()
        p = os.path.join(self.state, "events.jsonl")
        lines = open(p).read().splitlines()
        open(p, "w").write("\n".join(lines[:-1]) + "\n")
        ok, brk = col.verify_chains()
        self.assertFalse(ok)
        self.assertEqual(brk, 3)
        col.write_heartbeat()
        hb = json.load(open(os.path.join(self.state, "heartbeat.json")))
        self.assertEqual((hb["chain_ok"], hb["chain_break_line"], hb["chain_break_reason"]),
                         (False, 3, "tail missing or changed"))
        col2 = self.mk()  # a restarted collector reads the previous heartbeat and still notices
        self.assertFalse(col2.chain_ok)
        self.assertEqual(col2.chain_break_line, 3)

    def test_replaced_last_line_detected_after_poll(self):
        """Delete the last line and let new events append: the changed line at the recorded position is caught."""
        col = self.mk()
        self.feed(line(), line())
        col.poll_once()
        p = os.path.join(self.state, "events.jsonl")
        first = open(p).read().splitlines()[0]
        open(p, "w").write(first + "\n")
        self.feed(line())
        col.poll_once()
        self.assertFalse(col.chain_ok)
        self.assertEqual(col.chain_break_reason, "tail missing or changed")

    def test_records_tail_deletion_detected_but_appends_are_fine(self):
        """Records appended by another process are legitimate; deleting the last record is not."""
        col = self.mk()
        col.records.screening_confirmed(["/x"], 1, "h")
        col.poll_once()
        other = records.Records(self.state)  # another process (e.g. the server) writing records
        other.mode_switch("strict", "standard", True)
        col.poll_once()
        self.assertTrue(col.verify_chains()[0])
        p = os.path.join(self.state, "records.jsonl")
        rows = open(p).read().splitlines()
        open(p, "w").write("\n".join(rows[:-1]) + "\n")
        self.assertFalse(col.verify_chains()[0])
        self.assertEqual(col.chain_break_line, 2)

    def test_file_modes(self):
        """State files are owner-only."""
        col = self.mk()
        self.feed(line())
        col.poll_once()
        for fn in ("events.jsonl", "heartbeat.json", "channel.offset", "scan_counts.json"):
            self.assertEqual(os.stat(os.path.join(self.state, fn)).st_mode & 0o077, 0, fn)

    def test_config_load_roundtrip(self):
        """Collector accepts a config produced by hd.config.load."""
        p = os.path.join(self.d.name, "harness.json")
        json.dump({"name": "t", "mode": "standard", "state_dir": self.state, "channel_path": self.ch}, open(p, "w"))
        col = collector.Collector(config.load(p))
        self.feed(line())
        self.assertEqual(col.poll_once()["ingested"], 1)


if __name__ == "__main__":
    unittest.main()
