# test_state.py - unit tests for hd.state: verdict rules, stuck detection, security lines, forbidden words.
import atexit
import json
import os
import shutil
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from hd import state  # noqa: E402

NOW = datetime(2026, 6, 1, 15, 0, 0, tzinfo=timezone.utc)
FORBIDDEN = re.compile(r"(?i)(?<![a-z])(?:un|non-?)?(?:compliant|safe)(?![a-z])|\bcmmc\b|\bintact\b|no cui|sandbox intact|meets 3\.")
CONTROL = re.compile(r"(?i)\bcmmc\b")


def iso(d):
    """ISO Z string for a datetime."""
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class Env:
    """A temp state_dir plus helpers to write its files."""

    def __init__(self, **cfg):
        """Create the directory and config."""
        self.sd = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, self.sd, True)
        self.cfg = {"name": "t", "mode": "standard", "state_dir": self.sd, "goal": "g",
                    "wall": {"tier": "container"}, "data_sources": ["/x"], "stuck": {}, "middle": {"panels": []}}
        self.cfg.update(cfg)
        self.n = 0
        self.rec(type="screening_confirmed", sources=["/x"], file_count=1, listing_hash="h")

    def write(self, name, obj):
        """Write a JSON file."""
        with open(os.path.join(self.sd, name), "w") as f:
            json.dump(obj, f)

    def hb(self, age=1, chain_ok=True):
        """Write a heartbeat of the given age."""
        self.write("heartbeat.json", {"ts": iso(NOW - timedelta(seconds=age)), "pid": 1, "chain_ok": chain_ok, "chain_break_line": None if chain_ok else 4})

    def ev(self, kind, ago=5, sid="s1", **kw):
        """Append an event."""
        self.n += 1
        e = {"v": 1, "harness": "t", "session_id": sid, "kind": kind, "agent_ts": "x", "recv_ts": iso(NOW - timedelta(seconds=ago)), "event_id": "t-%d" % self.n}
        e.update(kw)
        with open(os.path.join(self.sd, "events.jsonl"), "a") as f:
            f.write(json.dumps(e) + "\n")

    def rec(self, **kw):
        """Append a record line."""
        with open(os.path.join(self.sd, "records.jsonl"), "a") as f:
            f.write(json.dumps(dict({"ts": iso(NOW), "os_user": "u"}, **kw)) + "\n")

    def build(self, **kw):
        """Run state.build with sane defaults for wall/approval."""
        kw.setdefault("wall", {"tier": "container", "running": True, "config_matches": True, "allowlist": "enforced", "detail": ""})
        kw.setdefault("approval", {"approved": True, "stale": False, "changed_parts": []})
        kw.setdefault("changed_since", 0)
        if "scan_counts.json" not in os.listdir(self.sd):
            self.write("scan_counts.json", {"scanned": 5, "not_scannable": 1, "hits": 0})
        return state.build(self.cfg, now=NOW, **kw)


def good_checks():
    """One independent pass."""
    return [{"id": "a", "state": "pass", "ts": iso(NOW), "independent": True}]


class VerdictTests(unittest.TestCase):
    """Verdict bar rules."""

    def test_missing_heartbeat_is_grey(self):
        e = Env(); e.ev("tool_pre")
        v = e.build(checks=good_checks())["verdict"]
        self.assertEqual(v["color"], "grey"); self.assertIn("no data from collector", v["reason"])

    def test_old_heartbeat_is_grey(self):
        e = Env(); e.hb(age=31); e.ev("tool_pre")
        self.assertEqual(e.build(checks=good_checks())["verdict"]["color"], "grey")

    def test_no_events_not_green(self):
        e = Env(); e.hb()
        self.assertNotEqual(e.build(checks=good_checks())["verdict"]["color"], "green")

    def test_green_path(self):
        e = Env(); e.hb(); e.ev("tool_pre")
        v = e.build(checks=good_checks())["verdict"]
        self.assertEqual(v["color"], "green"); self.assertEqual(v["goal"]["color"], "green")

    def test_agent_claimed_only_amber(self):
        e = Env(); e.hb(); e.ev("tool_pre")
        c = [{"id": "a", "state": "pass", "ts": iso(NOW), "independent": False, "agent_claimed": True}]
        g = e.build(checks=c)["verdict"]["goal"]
        self.assertEqual(g["color"], "amber"); self.assertIn("agent-claimed", g["reason"])

    def test_fail_red_could_not_check_amber(self):
        e = Env(); e.hb(); e.ev("tool_pre")
        self.assertEqual(e.build(checks=good_checks() + [{"id": "b", "state": "fail"}])["verdict"]["goal"]["color"], "red")
        self.assertEqual(e.build(checks=good_checks() + [{"id": "b", "state": "could_not_check"}])["verdict"]["goal"]["color"], "amber")

    def test_expected_run_by_passed(self):
        local = NOW.astimezone()
        e = Env(expected_run_by=(local - timedelta(minutes=10)).strftime("%H:%M"))
        # skip if the 10-minutes-ago time wrapped to the previous day
        if (local - timedelta(minutes=10)).date() != local.date():
            self.skipTest("midnight wrap")
        e.hb(); e.ev("tool_pre", ago=100000)
        g = e.build(checks=good_checks())["verdict"]["goal"]
        self.assertIn(g["color"], ("amber", "red")); self.assertIn("should have run by", g["reason"])

    def test_idle_before_expected(self):
        local = NOW.astimezone()
        if (local + timedelta(minutes=30)).date() != local.date():
            self.skipTest("midnight wrap")
        e = Env(expected_run_by=(local + timedelta(minutes=30)).strftime("%H:%M"))
        e.hb(); e.ev("tool_pre", ago=100000)
        g = e.build(checks=good_checks())["verdict"]["goal"]
        self.assertEqual(g["color"], "grey"); self.assertIn("idle", g["reason"])

    def test_safety_red_cases(self):
        e = Env(); e.hb(); e.ev("tool_pre")
        self.assertEqual(e.build(checks=good_checks(), wall={"tier": "none", "running": False, "config_matches": None, "allowlist": "not enforced", "detail": ""})["verdict"]["safety"]["color"], "red")
        self.assertEqual(e.build(checks=good_checks(), wall={"tier": "container", "running": False})["verdict"]["color"], "red")
        e.hb(chain_ok=False)
        self.assertEqual(e.build(checks=good_checks())["verdict"]["safety"]["color"], "red")
        e.hb(); e.rec(type="scan_hit", pattern="p", event_id="x", source="file_path"); e.rec(type="retention_hold", on=True, reason="r")
        v = e.build(checks=good_checks())["verdict"]
        self.assertEqual(v["safety"]["color"], "red"); self.assertEqual(v["color"], "red")

    def test_safety_amber_cases(self):
        e = Env(); e.hb(); e.ev("tool_pre")
        self.assertEqual(e.build(checks=good_checks(), approval={"approved": True, "stale": True, "changed_parts": ["wall_config"]})["verdict"]["safety"]["color"], "amber")
        self.assertEqual(e.build(checks=good_checks(), wall={"tier": "account", "running": None, "config_matches": None, "allowlist": "not enforced"})["verdict"]["safety"]["color"], "amber")
        e2 = Env(mode=None); e2.hb(); e2.ev("tool_pre")
        st = e2.build(checks=good_checks())
        self.assertEqual(st["verdict"]["safety"]["color"], "amber")
        self.assertIn("not set", st["security"][0]["text"])

    def test_stale_heartbeat_with_red_safety_still_red(self):
        e = Env(); e.ev("tool_pre")
        v = e.build(checks=good_checks(), wall={"tier": "none", "running": False})["verdict"]
        self.assertEqual(v["color"], "red")


class SessionTests(unittest.TestCase):
    """Stuck detection."""

    def rows(self, e):
        """Build and return sessions."""
        e.hb()
        return e.build()["sessions"]

    def test_waiting_on_you(self):
        e = Env(); e.ev("tool_pre", ago=900); e.ev("permission_pending", ago=800)
        self.assertEqual(self.rows(e)[0]["status"], "waiting on you")

    def test_no_events_stuck(self):
        e = Env(); e.ev("tool_pre", ago=700, tool_name="Read")
        r = self.rows(e)[0]
        self.assertEqual(r["status"], "stuck"); self.assertIn("no events", r["stuck_reason"])

    def test_repeat_call(self):
        e = Env()
        for i in range(5):
            e.ev("tool_pre", ago=50 - i, tool_name="Bash", task="ls")
        r = self.rows(e)[0]
        self.assertEqual(r["status"], "stuck"); self.assertIn("same call", r["stuck_reason"])

    def test_repeat_error(self):
        e = Env()
        for i in range(5):
            e.ev("tool_error", ago=50 - i, tool_name="Bash", status="error")
        self.assertIn("same error", self.rows(e)[0]["stuck_reason"])

    def test_same_file_edit(self):
        e = Env(stuck={"same_file_edit_limit": 3})
        for i in range(3):
            e.ev("tool_pre", ago=50 - i * 2, tool_name="Edit", file_path="/a/b.py")
            e.ev("tool_pre", ago=49 - i * 2, tool_name="Read", file_path="/a/c%d.py" % i)
        self.assertIn("same file", self.rows(e)[0]["stuck_reason"])

    def test_subagent_outlives(self):
        e = Env()
        e.ev("subagent_start", ago=3000, agent_id="a1"); e.ev("subagent_stop", ago=2940, agent_id="a1")
        e.ev("subagent_start", ago=2900, agent_id="a2"); e.ev("subagent_stop", ago=2840, agent_id="a2")
        e.ev("subagent_start", ago=600, agent_id="a3"); e.ev("tool_post", ago=5, tool_name="Read", agent_id="a3")
        r = self.rows(e)[0]
        self.assertEqual((r["subagents_active"], r["subagents_done"]), (1, 2))
        self.assertIn("subagent", r["stuck_reason"])

    def test_budget(self):
        e = Env(stuck={"budget_tool_calls": 4})
        for i in range(4):
            e.ev("tool_pre", ago=20 - i, tool_name="Read", file_path="/f%d" % i)
        self.assertIn("budget", self.rows(e)[0]["stuck_reason"])

    def test_working_idle_done(self):
        e = Env(); e.ev("tool_pre", ago=5, tool_name="Read", sid="w"); e.ev("stop", ago=5, sid="i"); e.ev("session_end", ago=5, sid="d")
        st = {r["session_id"]: r["status"] for r in self.rows(e)}
        self.assertEqual(st, {"w": "working", "i": "idle", "d": "done"})

    def test_strict_hides_working_on(self):
        e = Env(mode="strict"); e.ev("tool_pre", tool_name="Edit", file_path={"hash": "abc", "basename_len": 3}, task="secret task")
        r = self.rows(e)[0]
        self.assertEqual(r["working_on"], "hidden (strict)")
        e2 = Env(mode="standard"); e2.ev("tool_pre", tool_name="Edit", file_path="/p/q.py")
        self.assertEqual(self.rows(e2)[0]["working_on"], "/p/q.py")

class Round2Tests(unittest.TestCase):
    """Wall-green rule, last-run derivation, released-hold wording, hook-scan unavailability."""

    def sec(self, st):
        """Security lines keyed by key."""
        return {l["key"]: l for l in st["security"]}

    def test_wall_green_only_with_matching_config(self):
        """Container/vm green needs running, config match and an enforced/matching allowlist."""
        e = Env(); e.hb(); e.ev("tool_pre")
        w = {"tier": "container", "running": True, "config_matches": True, "allowlist": "matches approved config"}
        self.assertEqual(self.sec(e.build(wall=w))["wall"]["color"], "green")
        self.assertEqual(self.sec(e.build(wall=dict(w, tier="vm")))["wall"]["color"], "green")
        for bad in (dict(w, allowlist="unknown"), dict(w, allowlist="not enforced"), dict(w, config_matches=None),
                    dict(w, tier="account")):
            self.assertEqual(self.sec(e.build(wall=bad))["wall"]["color"], "amber", bad)

    def test_last_run_from_stop_or_session_end(self):
        """Without run_end events, the latest stop/session_end defines last_run; an error status means failed."""
        e = Env(); e.hb(); e.ev("tool_pre", ago=100); e.ev("stop", ago=50)
        v = e.build(checks=good_checks())["verdict"]
        self.assertEqual(v["last_run"]["result"], "passed")
        e.ev("stop", ago=10, status="error")
        v = e.build(checks=good_checks())["verdict"]
        self.assertEqual(v["last_run"]["result"], "failed")
        self.assertEqual(v["goal"]["color"], "red")

    def test_released_hold_shows_past_hits_neutral(self):
        """After release, old hits are neutral text; a hit after the release brings the amber back."""
        e = Env(); e.hb(); e.ev("tool_pre")
        e.rec(type="scan_hit", pattern="p", event_id="x", source="file_path")
        e.rec(type="retention_hold", on=True, reason="r")
        e.rec(type="retention_hold", on=False, reason="done", ts="2026-06-01T12:00:00Z")
        e.write("scan_counts.json", {"scanned": 5, "not_scannable": 0, "hits": 1})
        ln = self.sec(e.build(checks=good_checks()))["marking_scan"]
        self.assertEqual(ln["text"], "1 past marking hit; hold released 2026-06-01T12:00:00Z")
        self.assertEqual(ln["color"], "neutral")
        e.rec(type="scan_hit", pattern="p", event_id="y", source="task")
        self.assertEqual(self.sec(e.build(checks=good_checks()))["marking_scan"]["color"], "amber")

    def test_scan_detail_mentions_transcripts(self):
        """The marking-scan detail says transcripts are not held."""
        e = Env(); e.hb(); e.ev("tool_pre")
        d = self.sec(e.build())["marking_scan"]["detail"]
        self.assertIn("Claude Code transcripts are not held; they follow cleanupPeriodDays", d)

    def test_scan_unavailable_goes_amber(self):
        """Events whose hook scan was unavailable turn the marking-scan line amber with a count."""
        e = Env(); e.hb(); e.ev("tool_pre", extra={"scan": {"unavailable": True}}); e.ev("tool_post", extra={"scan": {"unavailable": True}})
        ln = self.sec(e.build(checks=good_checks()))["marking_scan"]
        self.assertEqual(ln["color"], "amber")
        self.assertTrue(ln["text"].startswith("scan unavailable in hook for 2 events"))

    def test_chain_wording(self):
        """Chain text says 'checks passed' and never 'intact'; a break leads the copies line."""
        e = Env(); e.hb(); e.ev("tool_pre")
        self.assertIn("log chain checks passed", self.sec(e.build())["copies"]["text"])
        self.assertNotIn("intact", json.dumps(e.build()).lower())
        e.hb(chain_ok=False)
        self.assertTrue(self.sec(e.build())["copies"]["text"].startswith("log chain BROKEN at line 4"))


class SecurityTests(unittest.TestCase):
    """Security block lines and forbidden words."""

    KEYS = ["mode", "wall", "approval", "data_sources", "marking_scan", "declared", "undeclared", "secrets",
            "copies", "dependencies", "user", "not_observed", "control_mapping"]

    def full(self):
        """A rich state payload."""
        e = Env(declared={"permissions": ["Bash(ls:*)"], "env": ["A=secretvalue"], "hosts": ["h.example"], "mcp_servers": [{"name": "r", "remote": True}]},
                dependencies={"lockfile": "x.lock", "last_reviewed": "2026-01-01"})
        e.hb(); e.ev("tool_pre", tool_name="Zed", host="evil.example"); e.ev("run_end", status="ok")
        e.rec(type="scan_hit", pattern="p", event_id="x", source="task")
        return e.build(checks=good_checks()), e

    def test_order_labels_and_fixed_lines(self):
        st, _ = self.full()
        self.assertEqual([l["key"] for l in st["security"]], self.KEYS)
        for l in st["security"]:
            self.assertIn(l["label"], ("observed", "declared (unverified)", "your statement"))
        by = {l["key"]: l for l in st["security"]}
        self.assertTrue(by["not_observed"]["text"].startswith("Not observed:"))
        self.assertEqual(by["control_mapping"]["text"], "Control mapping")
        self.assertNotIn("secretvalue", json.dumps(st))
        self.assertEqual(by["dependencies"]["color"], "amber")
        self.assertEqual(by["undeclared"]["color"], "amber")
        self.assertEqual(by["secrets"]["color"], "amber")

    def test_clean_scan_text_exact(self):
        e = Env(); e.hb(); e.ev("tool_pre")
        e.write("scan_counts.json", {"scanned": 12, "not_scannable": 3, "hits": 0})
        by = {l["key"]: l for l in e.build()["security"]}
        self.assertEqual(by["marking_scan"]["text"], "no markings found in 12 scanned items (3 not scannable)")

    def test_forbidden_words_absent(self):
        st, _ = self.full()
        txt = json.dumps(st)
        self.assertIsNone(FORBIDDEN.search(txt), FORBIDDEN.search(txt))
        self.assertIsNone(CONTROL.search(txt))
        e = Env(); e.hb(); e.ev("tool_pre")
        self.assertIsNone(FORBIDDEN.search(json.dumps(e.build())))

    def test_static_files_forbidden_words(self):
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "hd", "static")
        for n in ("index.html", "app.js", "style.css"):
            with open(os.path.join(d, n)) as f:
                t = f.read()
            self.assertIsNone(FORBIDDEN.search(t), n)
            self.assertIsNone(CONTROL.search(t), n)
            self.assertNotIn("innerHTML", t.replace("never innerHTML", ""))
            self.assertIsNone(re.search(r"https?://(?!127\.0\.0\.1)", t), n)


class MiddleTests(unittest.TestCase):
    """Middle panels."""

    def test_panels(self):
        e = Env(middle={"panels": [{"type": "tool_inventory", "title": "Tools", "declared_tools": ["Read", "Never"]},
                                   {"type": "mystery", "title": "<b>x</b>"}]})
        e.hb(); e.ev("tool_pre", tool_name="Read"); e.ev("tool_error", tool_name="Read")
        m = e.build()["middle"]
        rows = {r["tool"]: r for r in m[0]["rows"]}
        self.assertTrue(rows["Never"]["never_called"]); self.assertEqual(rows["Read"]["error_rate"], 1.0)
        self.assertEqual(m[1]["type"], "unsupported")


if __name__ == "__main__":
    unittest.main()
