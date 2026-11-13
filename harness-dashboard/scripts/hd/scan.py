"""Marking scan: detects banner-style export-control/CUI markings in memory; never keeps matched text."""
import re

# Word boundaries that treat underscore as a separator (so ITAR_notes.txt matches, "bear" does not).
_B = r"(?<![A-Za-z0-9])"
_E = r"(?![A-Za-z0-9])"

MAX_SCAN_CHARS = 1_000_000  # per-string scan cap
BINARY_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".sldprt", ".sldasm", ".slddrw",
               ".step", ".stp", ".stl", ".dwg", ".dxf", ".zip")

# (name, compiled regex). Uppercase-only where lowercase would be a common word (EAR, CUI, ITAR).
DEFAULT_PATTERNS = [
    ("CUI", re.compile(_B + r"CUI" + _E)),
    ("CONTROLLED UNCLASSIFIED", re.compile(r"controlled\s+unclassified", re.I)),
    ("FOUO", re.compile(_B + r"(?:FOUO|FOR\s+OFFICIAL\s+USE\s+ONLY)" + _E, re.I)),
    ("ITAR", re.compile(_B + r"ITAR" + _E)),
    ("EAR", re.compile(_B + r"EAR(?:99)?" + _E)),
    ("export controlled", re.compile(r"export[\s\-]+controlled", re.I)),
    ("22 CFR", re.compile(_B + r"22\s*CFR" + _E, re.I)),
    ("15 CFR", re.compile(_B + r"15\s*CFR" + _E, re.I)),
    ("USML", re.compile(_B + r"USML" + _E)),
    ("ECCN", re.compile(_B + r"ECCN" + _E)),
    ("DFARS 252.204-7012", re.compile(r"DFARS\s*252\.204-7012", re.I)),
    ("Distribution Statement", re.compile(r"(?i:distribution\s+statement)\s+[B-F]" + _E)),
    ("NOFORN", re.compile(_B + r"NOFORN" + _E)),
]


def _is_binary_path(p):
    """True if a path has a binary/non-text extension."""
    return isinstance(p, str) and p.lower().endswith(BINARY_EXTS)


def _strings(obj, source, out):
    """Collect (source_field, string) pairs from a JSON-like value."""
    if isinstance(obj, str):
        out.append((source, obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, source, out)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, source, out)


class Scanner:
    """Scans events against default plus per-harness patterns; keeps only counts and (name, source) hits."""

    def __init__(self, extra_patterns=None):
        """Compile default and extra patterns; bad extra patterns are skipped and listed in bad_patterns."""
        self.patterns = list(DEFAULT_PATTERNS)
        self.bad_patterns = []
        for p in extra_patterns or []:
            try:
                self.patterns.append((str(p["name"]), re.compile(p["regex"])))
            except (re.error, KeyError, TypeError):
                self.bad_patterns.append(str(p.get("name") if isinstance(p, dict) else p))
        self.counts = {"scanned": 0, "not_scannable": 0, "hits": 0}

    def scan_event(self, ev):
        """Scan one event's text fields; returns [{'pattern','event_id','source'}] with no matched text."""
        fields = []
        for k in ("file_path", "task"):
            if isinstance(ev.get(k), str):
                fields.append((k, ev[k]))
        c = ev.get("content")
        if isinstance(c, dict):
            for k in ("input", "output"):
                _strings(c.get(k), "content." + k, fields)
        not_scannable = _is_binary_path(ev.get("file_path"))
        if any("\x00" in s for _, s in fields):
            not_scannable = True
        hits, seen = [], set()
        for source, text in fields:
            if "\x00" in text:
                continue
            text = text[:MAX_SCAN_CHARS]
            for name, rx in self.patterns:
                if (name, source) not in seen and rx.search(text):
                    seen.add((name, source))
                    hits.append({"pattern": name, "event_id": ev.get("event_id"), "source": source})
        if not_scannable:
            self.counts["not_scannable"] += 1
        elif fields:
            self.counts["scanned"] += 1
        self.counts["hits"] += len(hits)
        return hits
