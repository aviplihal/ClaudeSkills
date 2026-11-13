# chainlog.py - append-only JSONL log where each line carries the hash of the previous line (tamper-evident).
import json
import os
import tempfile
import threading

from . import util

GENESIS = "0" * 64
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path):
    """Return the process-wide re-entrant lock for a log path (shared by all ChainLog instances)."""
    key = os.path.realpath(path)
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = _LOCKS[key] = threading.RLock()
        return lk


def _canon(obj):
    """Canonical JSON text: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entry_hash(obj):
    """sha256 of the canonical JSON of obj excluding its own 'h' field."""
    return util.sha256_hex(_canon({k: v for k, v in obj.items() if k != "h"}))


class ChainLog:
    """A hash-chained, owner-only JSONL file."""

    def __init__(self, path):
        """Remember the path; record a warning if it sits in a sync folder. Creates nothing."""
        self.path = os.path.abspath(os.path.expanduser(path))
        self.warnings = []
        marker = util.in_sync_folder(self.path)
        if marker:
            self.warnings.append("log path is inside a synced folder (%s): %s" % (marker, self.path))
        self._lock = _lock_for(self.path)

    def _tail(self):
        """Return (last_line_text|None, ends_with_newline) reading only the end of the file."""
        try:
            f = open(self.path, "rb")
        except FileNotFoundError:
            return None, True
        with f:
            size = f.seek(0, 2)
            if size == 0:
                return None, True
            chunk = 8192
            while True:
                start = max(0, size - chunk)
                f.seek(start)
                data = f.read(size - start)
                stripped = data[:-1] if data.endswith(b"\n") else data
                idx = stripped.rfind(b"\n")
                if idx != -1 or start == 0:
                    break
                chunk *= 2
            return stripped[idx + 1:].decode("utf-8", "replace"), data.endswith(b"\n")

    def append(self, obj):
        """Chain obj (adds prev and h), append it as one O_APPEND write, return the stored dict."""
        with self._lock:
            util.ensure_private_dir(os.path.dirname(self.path))
            last, nl = self._tail()
            prev = GENESIS if last is None else util.sha256_hex(last)
            entry = {k: v for k, v in obj.items() if k not in ("prev", "h")}
            entry["prev"] = prev
            entry["h"] = _entry_hash(entry)
            line = _canon(entry)
            payload = (line + "\n") if nl else ("\n" + line + "\n")
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.fchmod(fd, 0o600)
                data = payload.encode("utf-8")
                while data:
                    n = os.write(fd, data)
                    data = data[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            return entry

    def verify(self):
        """Return (True, None) if the chain is intact, else (False, first_bad_line_1_based)."""
        with self._lock:
            try:
                with open(self.path, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                return True, None
        if not data:
            return True, None
        lines = data.split(b"\n")
        has_nl = data.endswith(b"\n")
        if has_nl:
            lines.pop()
        expected = GENESIS
        for i, raw in enumerate(lines, 1):
            if i == len(lines) and not has_nl:
                return False, i  # truncated last line
            try:
                text = raw.decode("utf-8")
                obj = json.loads(text)
            except ValueError:
                return False, i
            if not isinstance(obj, dict) or obj.get("prev") != expected or obj.get("h") != _entry_hash(obj):
                return False, i
            expected = util.sha256_hex(text)
        return True, None

    def iter(self):
        """Yield each parseable entry as a dict, oldest first (unparseable lines are skipped)."""
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            return
        for raw in data.split(b"\n"):
            if not raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj

    def rewrite_without(self, predicate):
        """Drop entries where predicate(entry) is true, rebuild the chain with a chain_rebased
        marker first, replace the file atomically, and return the removed count (0 = untouched)."""
        with self._lock:
            try:
                with open(self.path, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                return 0
            raw_lines = [x for x in data.split(b"\n") if x]
            if not raw_lines:
                return 0
            old_tail = util.sha256_hex(raw_lines[-1])
            kept, removed = [], 0
            for raw in raw_lines:
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except ValueError:
                    obj = None
                if not isinstance(obj, dict) or predicate(obj):
                    removed += 1
                else:
                    kept.append(obj)
            if removed == 0:
                return 0
            marker = {"type": "chain_rebased", "ts": util.now(), "removed": removed,
                      "old_tail_hash": old_tail}
            out_lines, prev = [], GENESIS
            for obj in [marker] + kept:
                entry = {k: v for k, v in obj.items() if k not in ("prev", "h")}
                entry["prev"] = prev
                entry["h"] = _entry_hash(entry)
                text = _canon(entry)
                out_lines.append(text)
                prev = util.sha256_hex(text)
            util.ensure_private_dir(os.path.dirname(self.path))
            fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(self.path))
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(out_lines) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            return removed
