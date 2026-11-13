# test_fault_injection.py - PLAN.md step 3: break things on purpose and assert the dashboard says so.
"""End-to-end fault injection.

Every scenario runs the REAL hook.py as a subprocess (JSON on stdin, writing a temp channel), feeds the
channel through Collector.poll_once, and builds the verdict with state.build. Temp dirs only; wall,
approval and checks are injected dicts; no network, no docker. Each test asserts the verdict color AND
the reason text. A final test greps every scenario's state for forbidden words.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from hd import collector, records, state, util  # noqa: E402

HOOK = os.path.join(HERE, "..", "scripts", "hd", "hook.py")
CLOCK = "2026-06-01T15:00:00Z"
FORBIDDEN = re.compile(r"(?i)(?<![a-z])(?:un|non-?)?(?:compliant|safe|intact)(?![a-z])|\bcmmc\b|no cui|meets 3\.")
SENTINEL = "ZQ7731SENTINEL"   # unique text placed next to a marking; it must never be stored anywhere

GOOD_WALL = {"tier": "container", "running": True, "config_matches": True,
             "allowlist": "matches approved config", "detail": ""}
GOOD_APPROVAL = {"approved": True, "stale": False, "changed_parts": []}
GOOD_CHECKS = [{"id": "report-total", "state": "pass", "ts": CLOCK, "independent": True, "agent_claimed": False}]


class World:
    """One temp harness: config, collector, channel and helpers to drive the real hook."""

    def __init__(self, mode="standard", capture=False):
        """Create temp dirs, a collector, and the human screening record."""
        self.dir = tempfile.mkdtemp(prefix="hdfi-")
        self.state_dir = os.path.join(self.dir, "state")
        self.channel = os.path.join(self.dir, "chan.jsonl")
        self.cfg = {"name": "fi", "goal": "produce the weekly report", "state_dir": self.state_dir,
                    "channel_path": self.channel, "data_sources": ["/data/in"], "wall": {"tier": "container"},
                    "retention": {"metadata_days": 90, "content_days": 7, "capture_content": capture},
                    "scan": {"extra_patterns": []}}
        if mode:
            self.cfg["mode"] = mode
        self.capture = capture
        self.col = collector.Collector(self.cfg)
        self.col.records.screening_confirmed(["/data/in"], 3, "h")

    def hook(self, payload):
        """Run hook.py as Claude Code would (stdin JSON); assert it is silent and exits 0."""
        args = [sys.executable, HOOK, "--channel", self.channel, "--harness", "fi"]
        if self.capture:
            args.append("--capture-content")
        r = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, timeout=20)
        assert r.returncode == 0 and r.stdout == "", (r.returncode, r.stdout, r.stderr)

    def healthy_traffic(self):
        """A normal short session: start, one tool call, completed."""
        self.hook({"hook_event_name": "SessionStart", "session_id": "s1", "source": "startup"})
        self.hook({"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read", "tool_use_id": "t1",
                   "tool_input": {"file_path": "/data/in/a.csv"}})
        self.hook({"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Read", "tool_use_id": "t1",
                   "tool_input": {"file_path": "/data/in/a.csv"}, "tool_response": {"content": "a,b\n1,2"}})
        self.col.poll_once()

    def events_path(self):
        """Path of the hash-chained event log."""
        return os.path.join(self.state_dir, "events.jsonl")

    def build(self, now=None, **over):
        """state.build with healthy injected inputs; override any of wall/approval/checks."""
        kw = {"wall": GOOD_WALL, "approval": GOOD_APPROVAL, "checks": GOOD_CHECKS, "changed_since": 0}
        kw.update(over)
        return state.build(self.cfg, now=now or "2026-06-01T15:00:01Z", **kw)

    def all_state_bytes(self):
        """Concatenate every file under the state dir (to prove matched text is stored nowhere)."""
        blob = b""
        for dp, _, fns in os.walk(self.state_dir):
            for fn in fns:
                with open(os.path.join(dp, fn), "rb") as f:
                    blob += f.read()
        return blob


class FaultInjection(unittest.TestCase):
    """Each scenario_* method returns a state payload; each test_* asserts color and reason on it."""

    def setUp(self):
        """Fixed clock so recv_ts, heartbeat and verdict share one timeline."""
        util.set_clock(lambda: CLOCK)
        self._worlds = []

    def tearDown(self):
        """Restore the clock and remove temp dirs."""
        util.set_clock(None)
        for w in self._worlds:
            shutil.rmtree(w.dir, True)

    def world(self, **kw):
        """Create a World that is cleaned up after the test."""
        w = World(**kw)
        self._worlds.append(w)
        return w

    def verdict(self, st):
        """Return (color, reason) of a state payload."""
        return st["verdict"]["color"], st["verdict"]["reason"]

    # ---- scenarios (each builds its own world and returns the state)

    def scenario_baseline(self):
        """Independent check passes, container wall ok, approved, screened, mode standard."""
        w = self.world()
        w.healthy_traffic()
        return w.build()

    def scenario_collector_dead(self):
        """The collector stopped: its heartbeat is 60 s old."""
        w = self.world()
        w.healthy_traffic()
        return w.build(now="2026-06-01T15:01:00Z")

    def scenario_edited_line(self):
        """One byte of an event line is edited after the fact."""
        w = self.world()
        w.healthy_traffic()
        with open(w.events_path()) as f:
            txt = f.read()
        self.assertIn('"tool_name":"Read"', txt)
        with open(w.events_path(), "w") as f:
            f.write(txt.replace('"tool_name":"Read"', '"tool_name":"Rexd"', 1))
        w.col.verify_chains()
        w.col.write_heartbeat()
        return w.build()

    def scenario_deleted_last_line(self):
        """The newest event line is deleted (the remaining chain still verifies)."""
        w = self.world()
        w.healthy_traffic()
        with open(w.events_path()) as f:
            rows = f.read().splitlines()
        with open(w.events_path(), "w") as f:
            f.write("\n".join(rows[:-1]) + "\n")
        w.col.verify_chains()
        w.col.write_heartbeat()
        return w.build()

    def scenario_marking_capture_off(self):
        """A CUI banner appears in a tool_response while content capture is OFF."""
        w = self.world(capture=False)
        w.healthy_traffic()
        w.hook({"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_use_id": "t2",
                "tool_input": {"command": "cat memo.txt"},
                "tool_response": {"stdout": "CUI//SP-PROPIN %s memo body" % SENTINEL}})
        w.col.poll_once()
        self.world_cui = w
        return w.build()

    def scenario_failing_check(self):
        """An independent check fails."""
        w = self.world()
        w.healthy_traffic()
        return w.build(checks=GOOD_CHECKS + [{"id": "totals-match", "state": "fail", "ts": CLOCK, "independent": True}])

    def scenario_could_not_check(self):
        """A check could not be evaluated (not a pass, not a failure)."""
        w = self.world()
        w.healthy_traffic()
        return w.build(checks=GOOD_CHECKS + [{"id": "source-reachable", "state": "could_not_check", "ts": CLOCK,
                                              "independent": True}])

    def scenario_wall_down(self):
        """The wall is not running."""
        w = self.world()
        w.healthy_traffic()
        return w.build(wall=dict(GOOD_WALL, running=False, allowlist="unknown"))

    def scenario_approval_stale(self):
        """A trusted part changed after approval."""
        w = self.world()
        w.healthy_traffic()
        return w.build(approval={"approved": True, "stale": True, "changed_parts": ["signals"]})

    def scenario_mode_unset(self):
        """The human never stated a mode."""
        w = self.world(mode=None)
        w.healthy_traffic()
        return w.build()

    def scenario_no_events(self):
        """The collector is alive but nothing has ever happened."""
        w = self.world()
        w.col.poll_once()
        return w.build()

    def scenario_agent_claimed_only(self):
        """The only passing check is one the agent claims itself."""
        w = self.world()
        w.healthy_traffic()
        return w.build(checks=[{"id": "self-report", "state": "pass", "ts": CLOCK, "independent": False,
                                "agent_claimed": True}])

    # ---- assertions

    def test_healthy_baseline_is_green(self):
        """Everything healthy -> green, and the reason names the independent check."""
        st = self.scenario_baseline()
        color, reason = self.verdict(st)
        self.assertEqual(color, "green")
        self.assertEqual(reason, "1 independent check passed, none failed")
        self.assertEqual(st["verdict"]["safety"]["color"], "green")

    def test_dead_collector_is_grey_no_data(self):
        """A 60 s old heartbeat -> grey 'no data from collector', never green."""
        st = self.scenario_collector_dead()
        self.assertEqual(self.verdict(st), ("grey", "no data from collector"))
        self.assertEqual(st["verdict"]["data_age_s"], 60)

    def test_edited_event_line_is_red_chain_broken(self):
        """Editing a stored event -> red, reason names the broken log chain and the line."""
        color, reason = self.verdict(self.scenario_edited_line())
        self.assertEqual(color, "red")
        self.assertIn("log chain BROKEN at line", reason)

    def test_deleted_last_line_is_red(self):
        """Deleting the newest event -> red with the tail-missing reason."""
        color, reason = self.verdict(self.scenario_deleted_last_line())
        self.assertEqual(color, "red")
        self.assertIn("log chain BROKEN at line", reason)
        self.assertIn("tail missing or changed", reason)

    def test_marking_with_capture_off_is_caught_held_and_not_stored(self):
        """The hook scans in memory: Safety red, hold on, purge skipped, matched text stored nowhere."""
        st = self.scenario_marking_capture_off()
        w = self.world_cui
        color, reason = self.verdict(st)
        self.assertEqual((color, st["verdict"]["safety"]["color"]), ("red", "red"))
        self.assertIn("marking hit", reason)
        self.assertTrue(records.hold_active(w.state_dir))
        hits = w.col.records.all("scan_hit")
        self.assertEqual([(h["pattern"], h["source"]) for h in hits], [("CUI", "hook:tool_response")])
        purge = w.col.purge()
        self.assertEqual((purge["skipped"], purge["reason"]), (True, "retention hold active"))
        blob = w.all_state_bytes()
        self.assertNotIn(SENTINEL.encode(), blob)
        self.assertNotIn(b"PROPIN", blob)
        with open(w.channel, "rb") as f:   # the hook itself never wrote the text either (capture off)
            self.assertNotIn(SENTINEL.encode(), f.read())
        ms = {l["key"]: l for l in st["security"]}["marking_scan"]
        self.assertTrue(ms["hold"])
        self.assertIn("transcripts are not held", ms["detail"])

    def test_failing_check_is_goal_red(self):
        """A failing independent check -> Goal red, reason names the check."""
        st = self.scenario_failing_check()
        self.assertEqual(self.verdict(st), ("red", "check failed: totals-match"))
        self.assertEqual(st["verdict"]["goal"]["color"], "red")
        self.assertEqual(st["verdict"]["safety"]["color"], "green")

    def test_could_not_check_is_amber_with_its_own_reason(self):
        """could_not_check -> amber, and the wording differs from the agent-claimed case."""
        color, reason = self.verdict(self.scenario_could_not_check())
        self.assertEqual((color, reason), ("amber", "could not check: source-reachable"))
        self.assertNotEqual(reason, self.verdict(self.scenario_agent_claimed_only())[1])

    def test_wall_not_running_is_red(self):
        """Wall down -> Safety red naming the wall."""
        st = self.scenario_wall_down()
        color, reason = self.verdict(st)
        self.assertEqual((color, st["verdict"]["safety"]["color"]), ("red", "red"))
        self.assertEqual(reason, "Wall: not running")

    def test_stale_approval_is_amber(self):
        """Approval stale -> amber, naming the changed part."""
        self.assertEqual(self.verdict(self.scenario_approval_stale()),
                         ("amber", "Approval: stale, changed since approval: signals"))

    def test_mode_unset_is_amber_not_set(self):
        """No mode stated -> amber 'not set' (treated as Strict)."""
        st = self.scenario_mode_unset()
        self.assertEqual(self.verdict(st), ("amber", "Mode: not set (treated as Strict)"))
        self.assertEqual(st["mode"], "strict")

    def test_no_events_ever_is_not_green(self):
        """A live collector but zero events -> grey, never green."""
        color, reason = self.verdict(self.scenario_no_events())
        self.assertNotEqual(color, "green")
        self.assertEqual((color, reason), ("grey", "no events recorded yet"))

    def test_only_agent_claimed_checks_is_not_green(self):
        """Only agent-claimed checks -> amber, reason says no independent check passed."""
        color, reason = self.verdict(self.scenario_agent_claimed_only())
        self.assertEqual(color, "amber")
        self.assertEqual(reason, "agent-claimed only: no independent check passed")

    def test_no_forbidden_word_in_any_scenario(self):
        """No scenario's state contains a forbidden claim word."""
        names = sorted(n for n in dir(self) if n.startswith("scenario_"))
        self.assertGreaterEqual(len(names), 12)
        for n in names:
            txt = json.dumps(getattr(self, n)())
            m = FORBIDDEN.search(txt)
            self.assertIsNone(m, "%s: %s" % (n, m and txt[max(0, m.start() - 40):m.end() + 40]))


if __name__ == "__main__":
    unittest.main()
