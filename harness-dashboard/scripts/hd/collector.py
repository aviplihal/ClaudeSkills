"""Collector: reads the untrusted channel file, validates/scans/redacts events, writes the hash-chained event log.

Everything read from the channel is untrusted data: schema-checked, size-limited, never executed or echoed.
Run: python3 -m hd.collector --config harness.json [--once]
"""
import argparse
import json
import os
import signal
import tempfile
import time
from datetime import datetime, timedelta, timezone

from . import chainlog, config as hdconfig, records as hdrecords, redact, schema, util
from .scan import Scanner

POLL_SECONDS = 2.0
VERIFY_EVERY_SECONDS = 3600
MAX_READ_BYTES = 4 * 1024 * 1024  # per poll
MAX_LINE = schema.MAX_LINE_BYTES


SCAN_MAX_HITS = 20     # cap on hook-reported hits per event
SCAN_SOURCES_MAX = 40  # cap on a reported source/field name


def clean_scan(extra):
    """Validate the untrusted extra.scan dict; return a clean dict or None when absent or malformed."""
    sc = extra.get("scan") if isinstance(extra, dict) else None
    if not isinstance(sc, dict):
        return None
    out = {}
    if sc.get("unavailable") is True:
        out["unavailable"] = True
    if "hits" in sc or "not_scannable" in sc:
        hits = []
        raw = sc.get("hits")
        for h in (raw if isinstance(raw, list) else [])[:SCAN_MAX_HITS]:
            if isinstance(h, dict) and isinstance(h.get("pattern"), str) and h["pattern"] \
                    and isinstance(h.get("source"), str) and h["source"]:
                hits.append({"pattern": h["pattern"][:64], "source": h["source"][:SCAN_SOURCES_MAX]})
        out["hits"] = hits
        out["not_scannable"] = sc.get("not_scannable") is True
    return out or None


def _tail_of(path):
    """Return the non-blank lines (bytes) of a file, or [] when it is missing."""
    try:
        with open(path, "rb") as f:
            return [x for x in f.read().split(b"\n") if x]
    except OSError:
        return []


def _parse_ts(s):
    """Parse an ISO-8601 Z timestamp to an aware datetime, or None."""
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class Collector:
    """Ingests channel lines into the event log for one harness."""

    def __init__(self, cfg):
        """Set up logs, scanner, counters; restore the monotonic event counter; verify chains."""
        self.cfg = cfg
        self.state_dir = cfg["state_dir"]
        self.channel = cfg["channel_path"]
        util.ensure_private_dir(self.state_dir)
        self.events = chainlog.ChainLog(os.path.join(self.state_dir, "events.jsonl"))
        self.records = hdrecords.Records(self.state_dir)
        self.scanner = Scanner((cfg.get("scan") or {}).get("extra_patterns") or [])
        self.offset_path = os.path.join(self.state_dir, "channel.offset")
        self.counts_path = os.path.join(self.state_dir, "scan_counts.json")
        self.heartbeat_path = os.path.join(self.state_dir, "heartbeat.json")
        self.rejected = 0
        self.ingested = 0
        self.offset_resets = 0
        self.chain_ok, self.chain_break_line, self.chain_break_reason = True, None, None
        self.purge_refused = False
        self._last_verify = 0.0
        self._tails = {"events": None, "records": None}   # remembered {"lines","hash"} per log
        self._tail_breaks = {}                            # log name -> recorded line count at the break
        self._load_prev_tails()
        self._counts = {"scanned": 0, "not_scannable": 0, "hits": 0}
        try:
            with open(self.counts_path) as f:
                prev = json.load(f)
            for k in self._counts:
                self._counts[k] = int(prev.get(k, 0))
        except (OSError, ValueError, TypeError):
            pass
        self._next_id = self._restore_counter()
        self.verify_chains()

    def _load_prev_tails(self):
        """Restore the remembered log tails from the previous heartbeat (validated; bad data is ignored)."""
        try:
            with open(self.heartbeat_path) as f:
                prev = json.load(f)
        except (OSError, ValueError):
            return
        for name in self._tails:
            t = prev.get(name + "_tail") if isinstance(prev, dict) else None
            if isinstance(t, dict) and isinstance(t.get("lines"), int) and not isinstance(t["lines"], bool) \
                    and t["lines"] >= 0 and (t.get("hash") is None or isinstance(t.get("hash"), str)):
                self._tails[name] = {"lines": t["lines"], "hash": t.get("hash")}

    def _check_tail(self, name, log):
        """Compare a log with its remembered tail: shrinkage or a changed line marks a (sticky) break.
        Lines appended by other processes are fine; the remembered tail only advances while no break exists."""
        lines = _tail_of(log.path)
        rec = self._tails.get(name)
        if rec and rec["lines"] > 0 and name not in self._tail_breaks:
            n = rec["lines"]
            if len(lines) < n or util.sha256_hex(lines[n - 1]) != rec["hash"]:
                self._tail_breaks[name] = n
        if name not in self._tail_breaks:
            self._tails[name] = {"lines": len(lines), "hash": util.sha256_hex(lines[-1]) if lines else None}

    def _reset_tail(self, name, log):
        """Re-baseline a log's remembered tail from the file (after a legitimate rewrite by purge)."""
        self._tail_breaks.pop(name, None)
        self._tails[name] = None
        self._check_tail(name, log)

    def _restore_counter(self):
        """Return the next event number: one past the highest event_id suffix in the event log."""
        top = 0
        for e in self.events.iter():
            eid = e.get("event_id")
            if isinstance(eid, str) and "-" in eid:
                try:
                    top = max(top, int(eid.rsplit("-", 1)[1]))
                except ValueError:
                    pass
        return top + 1

    def _read_offset(self):
        """Load the saved channel offset (0 if absent or unreadable)."""
        try:
            with open(self.offset_path) as f:
                return max(0, int(f.read().strip()))
        except (OSError, ValueError):
            return 0

    def _save_offset(self, off):
        """Persist the channel offset."""
        util.secure_write(self.offset_path, str(off))

    def verify_chains(self):
        """Verify both logs; remember the first break (events wins) for the heartbeat."""
        ok_e, line_e = self.events.verify()
        ok_r, line_r = self.records.log.verify()
        self._check_tail("events", self.events)
        self._check_tail("records", self.records.log)
        tail_line = self._tail_breaks.get("events") or self._tail_breaks.get("records")
        self.chain_ok = ok_e and ok_r and not self._tail_breaks
        self.chain_break_line = line_e if not ok_e else (line_r if not ok_r else tail_line)
        self.chain_break_reason = None if self.chain_ok else (
            "hash chain mismatch" if not (ok_e and ok_r) else "tail missing or changed")
        self._last_verify = time.monotonic()
        return self.chain_ok, self.chain_break_line

    def _mode_capture(self):
        """Return (effective_mode, capture_content) where capture is forced off in strict."""
        mode, _ = hdconfig.effective_mode(self.cfg)
        cap = bool((self.cfg.get("retention") or {}).get("capture_content"))
        return mode, (cap and mode == "standard")

    def _handle_event(self, ev):
        """Stamp, scan (before redaction), react to hits, redact, store one validated event."""
        ev["recv_ts"] = util.now()  # trusted; agent_ts stays as sent
        ev["event_id"] = "%s-%d" % (self.cfg.get("name", "harness"), self._next_id)
        self._next_id += 1
        before = dict(self.scanner.counts)
        hits = self.scanner.scan_event(ev)
        hits = self._merge_hook_scan(ev, hits, before)
        if hits:
            first = hits[0]
            for h in hits:
                self.records.scan_hit(h["pattern"], h["event_id"], h["source"])
            self.records.retention_hold(True, "marking scan hit: %s in %s (event %s)"
                                        % (first["pattern"], first["source"], first["event_id"]))
            self.records.incident_note({"status": "open", "pattern": first["pattern"],
                                        "event_id": first["event_id"]})
        mode, cap = self._mode_capture()
        self.events.append(redact.redact_event(ev, mode, cap))
        self.ingested += 1

    def _merge_hook_scan(self, ev, hits, before):
        """Fold the hook's in-memory scan (extra.scan, untrusted) into the collector's hits.

        Hook sources get a 'hook:' prefix (agent-side), hits are deduped per (event_id, pattern), and one
        event is counted once. The stored extra.scan is replaced by the validated form."""
        extra = ev.get("extra")
        hs = clean_scan(extra)
        if isinstance(extra, dict):
            extra = dict(extra)
            if hs is None:
                extra.pop("scan", None)
            else:
                extra["scan"] = {"hits": [dict(h, source="hook:" + h["source"]) for h in hs.get("hits", [])],
                                 "not_scannable": hs.get("not_scannable", False)} if "hits" in hs else {}
                if hs.get("unavailable"):
                    extra["scan"]["unavailable"] = True
            ev["extra"] = extra
        if not hs or "hits" not in hs:
            return hits
        seen = {h["pattern"] for h in hits}
        merged = list(hits)
        for h in hs["hits"]:
            if h["pattern"] not in seen:
                seen.add(h["pattern"])
                merged.append({"pattern": h["pattern"], "event_id": ev.get("event_id"), "source": "hook:" + h["source"]})
        cnt = self.scanner.counts
        cnt["hits"] += len(merged) - len(hits)
        was_scanned = cnt["scanned"] > before["scanned"]
        was_ns = cnt["not_scannable"] > before["not_scannable"]
        if not was_scanned and not was_ns:
            cnt["not_scannable" if hs["not_scannable"] else "scanned"] += 1
        elif was_scanned and hs["not_scannable"]:
            cnt["scanned"] -= 1
            cnt["not_scannable"] += 1
        return merged

    def _split_lines(self, data):
        """Split a chunk into (complete_lines, bytes_consumed); an over-long unterminated tail is consumed as one bad line."""
        lines, pos = [], 0
        while True:
            nl = data.find(b"\n", pos)
            if nl == -1:
                break
            lines.append(data[pos:nl])
            pos = nl + 1
        if len(data) - pos > MAX_LINE:  # unterminated and already too big: reject it
            lines.append(data[pos:])
            pos = len(data)
        return lines, pos

    def poll_once(self):
        """Ingest any new channel lines; write scan counters and heartbeat; return stats."""
        stats = {"ingested": 0, "rejected": 0, "offset_reset": False}
        off = self._read_offset()
        try:
            size = os.path.getsize(self.channel)
        except (OSError, TypeError):
            size = None
        if size is not None:
            if off > size:  # channel truncated or replaced
                off = 0
                self.offset_resets += 1
                stats["offset_reset"] = True
            if size > off:
                with open(self.channel, "rb") as f:
                    f.seek(off)
                    data = f.read(min(size - off, MAX_READ_BYTES))
                lines, used = self._split_lines(data)
                before_i, before_r = self.ingested, self.rejected
                for raw in lines:
                    if not raw.strip():
                        continue
                    if len(raw) > MAX_LINE:
                        self.rejected += 1
                        continue
                    ev, err = schema.validate(raw)
                    if ev is None:
                        self.rejected += 1  # counted only; the line is never echoed
                        continue
                    self._handle_event(ev)
                stats["ingested"] = self.ingested - before_i
                stats["rejected"] = self.rejected - before_r
                off += used
        self._save_offset(off)
        self._check_tail("events", self.events)
        self._check_tail("records", self.records.log)
        if self._tail_breaks:
            self.chain_ok = False
            self.chain_break_line = self.chain_break_line or self._tail_breaks.get("events") or self._tail_breaks.get("records")
            self.chain_break_reason = self.chain_break_reason or "tail missing or changed"
        for k, v in self.scanner.counts.items():
            self._counts[k] += v
            self.scanner.counts[k] = 0
        util.secure_write(self.counts_path, json.dumps(self._counts))
        if time.monotonic() - self._last_verify >= VERIFY_EVERY_SECONDS:
            self.verify_chains()
        self.write_heartbeat()
        return stats

    def write_heartbeat(self):
        """Write heartbeat.json (ts, pid, chain state, rejected count, offset resets)."""
        hb = {"ts": util.now(), "pid": os.getpid(), "chain_ok": self.chain_ok,
              "chain_break_line": self.chain_break_line, "rejected": self.rejected,
              "ingested": self.ingested, "offset_resets": self.offset_resets,
              "chain_break_reason": self.chain_break_reason, "purge_refused": self.purge_refused,
              "events_tail": self._tails.get("events"), "records_tail": self._tails.get("records")}
        util.secure_write(self.heartbeat_path, json.dumps(hb))

    def purge(self):
        """Apply retention (drop old events, strip old content); skipped entirely while a hold is active."""
        if hdrecords.hold_active(self.state_dir):
            return {"skipped": True, "reason": "retention hold active", "removed": 0, "stripped": 0}
        self.verify_chains()  # never rewrite a log whose chain is broken: that would launder tampering
        if "events" in self._tail_breaks or not self.events.verify()[0]:
            self.purge_refused = True
            self.write_heartbeat()
            return {"skipped": True, "reason": "log chain broken", "removed": 0, "stripped": 0}
        self.purge_refused = False
        ret = self.cfg.get("retention") or {}
        now = _parse_ts(util.now())
        meta_cut = now - timedelta(days=ret.get("metadata_days", 90))
        content_cut = now - timedelta(days=ret.get("content_days", 7))
        stripped = [0]

        def old_event(e):
            """Predicate: drop events older than metadata retention; strip old content in place."""
            ts = _parse_ts(e.get("recv_ts"))
            if ts is None:
                return False
            if ts < meta_cut:
                return True
            if "content" in e and ts < content_cut:
                del e["content"]
                stripped[0] += 1
            return False

        removed = self.events.rewrite_without(old_event)
        if removed == 0 and stripped[0]:
            self._rewrite_stripped(content_cut)  # rewrite_without leaves the file alone when nothing is removed
        self._reset_tail("events", self.events)
        self.write_heartbeat()
        return {"skipped": False, "removed": removed, "stripped": stripped[0]}

    def _rewrite_stripped(self, content_cut):
        """Rebuild the event chain with old content removed (with a chain_rebased marker), atomically."""
        log = self.events
        with log._lock:
            kept = list(log.iter())
            old_tail = util.sha256_hex(chainlog._canon(kept[-1])) if kept else None
            n = 0
            for e in kept:
                ts = _parse_ts(e.get("recv_ts"))
                if ts and ts < content_cut and "content" in e:
                    del e["content"]
                    n += 1
            marker = {"type": "chain_rebased", "ts": util.now(), "removed": 0, "stripped": n,
                      "old_tail_hash": old_tail}
            out, prev = [], chainlog.GENESIS
            for obj in [marker] + kept:
                entry = {k: v for k, v in obj.items() if k not in ("prev", "h")}
                entry["prev"] = prev
                entry["h"] = chainlog._entry_hash(entry)
                text = chainlog._canon(entry)
                out.append(text)
                prev = util.sha256_hex(text)
            fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(log.path))
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(out) + "\n")
                os.replace(tmp, log.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise


def main(argv=None):
    """CLI entry: poll the channel every 2 s (or once), purge daily, until interrupted."""
    ap = argparse.ArgumentParser(prog="hd.collector")
    ap.add_argument("--config", required=True)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    col = Collector(hdconfig.load(args.config))
    if args.once:
        col.poll_once()
        return 0
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    last_purge = 0.0
    try:
        while not stop:
            col.poll_once()
            if time.monotonic() - last_purge > 86400 or last_purge == 0.0:
                col.purge()
                last_purge = time.monotonic()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
