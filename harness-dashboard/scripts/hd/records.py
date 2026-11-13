# records.py - the records log (what the human decided), a hash-chained log in <state_dir>/records.jsonl.
import os

from . import util
from .chainlog import ChainLog


def _path(state_dir):
    """Path of records.jsonl inside a state dir."""
    return os.path.join(os.path.abspath(os.path.expanduser(state_dir)), "records.jsonl")


class Records:
    """Typed append/read API over the records chain log."""

    def __init__(self, state_dir):
        """Wrap a ChainLog on <state_dir>/records.jsonl (nothing is created until the first write)."""
        self.state_dir = os.path.abspath(os.path.expanduser(state_dir))
        self.log = ChainLog(_path(state_dir))

    def _add(self, type_, **fields):
        """Append one entry with type, ts, os_user plus fields; return the stored dict."""
        entry = {"type": type_, "ts": util.now(), "os_user": util.os_user()}
        entry.update(fields)
        return self.log.append(entry)

    def screening_confirmed(self, sources, file_count, listing_hash):
        """Record that the human re-confirmed screening of the data sources."""
        return self._add("screening_confirmed", sources=list(sources), file_count=file_count,
                         listing_hash=listing_hash)

    def approval(self, old_hash, new_hash, parts):
        """Record an approval (or re-approval) of the harness's trusted-part hashes."""
        return self._add("approval", old_hash=old_hash, new_hash=new_hash, parts=dict(parts))

    def mode_switch(self, old, new, confirmed):
        """Record a mode change and whether the human confirmed it."""
        return self._add("mode_switch", old=old, new=new, confirmed=bool(confirmed))

    def scan_hit(self, pattern, event_id, source):
        """Record a marking-scan hit by pattern name, event id and field name (never the matched text)."""
        return self._add("scan_hit", pattern=pattern, event_id=event_id, source=source)

    def incident_note(self, fields):
        """Record an incident note; fields is a free-form dict kept under 'fields'."""
        return self._add("incident_note", fields=dict(fields))

    def retention_hold(self, on, reason):
        """Record that retention deletion is paused (on=True) or released (on=False)."""
        return self._add("retention_hold", on=bool(on), reason=reason)

    def compliance_note(self, who, when, covers):
        """Record the compliance owner's agreement: who, when, and what it covers."""
        return self._add("compliance_note", who=who, when=when, covers=covers)

    def latest(self, type=None):
        """Return the newest entry of the given type (any type if None), or None."""
        found = None
        for e in self.log.iter():
            if type is None or e.get("type") == type:
                found = e
        return found

    def all(self, type=None):
        """Return all entries (oldest first), optionally filtered by type."""
        return [e for e in self.log.iter() if type is None or e.get("type") == type]


def hold_active(state_dir):
    """True if the most recent retention_hold entry has on == True."""
    last = None
    for e in ChainLog(_path(state_dir)).iter():
        if e.get("type") == "retention_hold":
            last = e
    return bool(last and last.get("on") is True)
