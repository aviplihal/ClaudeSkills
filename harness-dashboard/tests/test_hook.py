"""Tests for hd/hook.py: standalone hook behavior (run as a subprocess, as Claude Code would)."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "scripts", "hd", "hook.py")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "hd"))
import hook  # noqa: E402  (loaded directly, not via hd, to prove it is standalone)


def run_hook(payload, channel, extra_args=(), raw=None):
    """Run hook.py as a subprocess with the payload on stdin; returns CompletedProcess."""
    data = raw if raw is not None else json.dumps(payload)
    return subprocess.run([sys.executable, HOOK, "--channel", channel, "--harness", "h1", *extra_args],
                          input=data, capture_output=True, text=True, timeout=20)


class HookTests(unittest.TestCase):
    """Behavior of the hook script."""

    def setUp(self):
        """Create a temp channel path."""
        self.d = tempfile.TemporaryDirectory()
        self.ch = os.path.join(self.d.name, "chan.jsonl")

    def tearDown(self):
        """Clean temp dir."""
        self.d.cleanup()

    def lines(self):
        """Return parsed channel lines."""
        if not os.path.exists(self.ch):
            return []
        return [json.loads(l) for l in open(self.ch).read().splitlines()]

    def test_no_hd_import(self):
        """hook.py source must not import hd."""
        src = open(HOOK).read()
        self.assertNotIn("import hd", src)
        self.assertNotIn("from hd", src)

    def test_pre_tool_basic_exit0_silent(self):
        """PreToolUse maps to tool_pre, exit 0, empty stdout."""
        r = run_hook({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Read",
                      "tool_use_id": "t1", "tool_input": {"file_path": "/a/b.txt"}}, self.ch)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        ev = self.lines()[0]
        self.assertEqual(ev["kind"], "tool_pre")
        self.assertEqual(ev["file_path"], "/a/b.txt")
        self.assertEqual(ev["harness"], "h1")
        self.assertNotIn("content", ev)

    def test_content_only_with_flag(self):
        """content appears only with --capture-content."""
        p = {"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash",
             "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}}
        run_hook(p, self.ch)
        run_hook(p, self.ch, ["--capture-content"])
        a, b = self.lines()
        self.assertNotIn("content", a)
        self.assertEqual(b["content"]["input"], {"command": "ls"})

    def test_post_error_status(self):
        """PostToolUse with an error response gets status error."""
        run_hook({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash",
                  "tool_response": {"is_error": True}}, self.ch)
        run_hook({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash",
                  "tool_response": {"stdout": "ok"}}, self.ch)
        a, b = self.lines()
        self.assertEqual(a["status"], "error")
        self.assertEqual(b["status"], "ok")

    def test_notification_mapping(self):
        """Permission notifications become permission_pending; others stay notification."""
        run_hook({"hook_event_name": "Notification", "session_id": "s",
                  "message": "Claude needs your permission to use Bash"}, self.ch)
        run_hook({"hook_event_name": "Notification", "session_id": "s", "message": "Claude is waiting"}, self.ch)
        a, b = self.lines()
        self.assertEqual(a["kind"], "permission_pending")
        self.assertEqual(b["kind"], "notification")

    def test_permission_request_and_notification_split(self):
        """PermissionRequest and permission_prompt notifications are permission_pending; others are not."""
        run_hook({"hook_event_name": "PermissionRequest", "session_id": "s", "tool_name": "Bash",
                  "tool_input": {"command": "ls"}}, self.ch)
        run_hook({"hook_event_name": "Notification", "session_id": "s", "notification_type": "permission_prompt",
                  "message": "x"}, self.ch)
        run_hook({"hook_event_name": "Notification", "session_id": "s", "notification_type": "idle_prompt",
                  "message": "needs your permission"}, self.ch)
        run_hook({"hook_event_name": "Notification", "session_id": "s", "message": "needs your permission"}, self.ch)
        a, b, c, d = self.lines()
        self.assertEqual([x["kind"] for x in (a, b, c, d)],
                         ["permission_pending", "permission_pending", "notification", "permission_pending"])
        self.assertEqual(a["status"], "pending")
        self.assertNotIn("tool_use_id", a)

    def test_failure_events(self):
        """PostToolUseFailure keeps is_interrupt, StopFailure is stop/error, PermissionDenied is tool_error/denied."""
        run_hook({"hook_event_name": "PostToolUseFailure", "session_id": "s", "tool_name": "Bash",
                  "error": "Exit code 1", "is_interrupt": True}, self.ch)
        run_hook({"hook_event_name": "StopFailure", "session_id": "s"}, self.ch)
        run_hook({"hook_event_name": "PermissionDenied", "session_id": "s", "tool_name": "Bash",
                  "tool_use_id": "t9", "reason": "no"}, self.ch)
        a, b, c = self.lines()
        self.assertEqual((a["kind"], a["status"], a["extra"]["is_interrupt"]), ("tool_error", "error", True))
        self.assertNotIn("Exit code", json.dumps(a))
        self.assertEqual((b["kind"], b["status"]), ("stop", "error"))
        self.assertEqual((c["kind"], c["status"], c["tool_use_id"]), ("tool_error", "denied", "t9"))

    def test_scan_runs_with_capture_off_and_stores_no_text(self):
        """A marking in tool_response is reported (pattern + field only) though content is not captured."""
        run_hook({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash",
                  "tool_input": {"command": "cat f"}, "tool_response": {"stdout": "x CUI//SP-ZZQ77 y"}}, self.ch)
        raw = open(self.ch).read()
        ev = json.loads(raw)
        self.assertNotIn("ZZQ77", raw)
        self.assertNotIn("content", ev)
        self.assertEqual(ev["extra"]["scan"]["hits"], [{"pattern": "CUI", "source": "tool_response"}])
        self.assertFalse(ev["extra"]["scan"]["not_scannable"])

    def test_scan_sources_and_patterns_file(self):
        """prompt, file_path and task are scanned; --patterns adds per-harness patterns; binary paths are not scannable."""
        pf = os.path.join(self.d.name, "p.json")
        json.dump([{"name": "proj", "regex": "PROJ-\\d+"}], open(pf, "w"))
        run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "see PROJ-42"}, self.ch, ["--patterns", pf])
        run_hook({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Read",
                  "tool_input": {"file_path": "/a/ITAR_notes.pdf"}}, self.ch)
        run_hook({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Task",
                  "tool_input": {"description": "handle NOFORN data"}}, self.ch)
        a, b, c = self.lines()
        self.assertEqual(a["extra"]["scan"]["hits"], [{"pattern": "proj", "source": "prompt"}])
        self.assertEqual(b["extra"]["scan"]["hits"][0]["source"], "file_path")
        self.assertTrue(b["extra"]["scan"]["not_scannable"])
        self.assertIn({"pattern": "NOFORN", "source": "task"}, c["extra"]["scan"]["hits"])

    def test_scan_unavailable_when_scan_py_missing(self):
        """If scan.py cannot be loaded the event says so; the hook still exits 0, silent, and writes the event."""
        d = os.path.join(self.d.name, "bare")
        os.mkdir(d)
        import shutil
        shutil.copy(HOOK, d)
        r = subprocess.run([sys.executable, os.path.join(d, "hook.py"), "--channel", self.ch, "--harness", "h1"],
                           input=json.dumps({"hook_event_name": "Stop", "session_id": "s"}), capture_output=True,
                           text=True, timeout=20)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.lines()[0]["extra"]["scan"], {"unavailable": True})

    def test_subagent_task_and_agent_id(self):
        """Task tool description becomes task; agent_id copied."""
        run_hook({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Task", "agent_id": "a1",
                  "tool_input": {"description": "do thing"}}, self.ch)
        ev = self.lines()[0]
        self.assertEqual(ev["task"], "do thing")
        self.assertEqual(ev["agent_id"], "a1")

    def test_garbage_input_exit0(self):
        """Invalid JSON, empty stdin, unknown event: exit 0, silent, nothing written."""
        for raw in ("not json", "", "[1,2]", json.dumps({"hook_event_name": "Weird"})):
            r = run_hook(None, self.ch, raw=raw)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")
        self.assertEqual(self.lines(), [])

    def test_unwritable_channel_exit0(self):
        """An unwritable channel path still exits 0 with stderr only."""
        r = run_hook({"hook_event_name": "Stop", "session_id": "s"}, "/nonexistent-dir/x/chan.jsonl")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn("hook", r.stderr)

    def test_truncation_keeps_valid_json_under_limit(self):
        """Huge content is shrunk so the line is <= 60 KiB and valid JSON."""
        big = "A" * 500_000
        run_hook({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Bash",
                  "tool_input": {"command": big}, "tool_response": {"stdout": big}}, self.ch, ["--capture-content"])
        raw = open(self.ch, "rb").read()
        self.assertLessEqual(len(raw), 60 * 1024)
        self.assertEqual(raw.count(b"\n"), 1)
        json.loads(raw)

    def test_huge_file_path_still_valid(self):
        """Absurd file_path is cut so the line stays valid and bounded."""
        run_hook({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Read",
                  "tool_input": {"file_path": "/x" * 100_000}}, self.ch)
        raw = open(self.ch, "rb").read()
        self.assertLessEqual(len(raw), 60 * 1024)
        json.loads(raw)

    def test_main_returns_zero_inprocess(self):
        """main() returns 0 even when stdin is None-like garbage."""
        self.assertEqual(hook.main(["--channel", self.ch, "--harness", "h"], io.StringIO("{{")), 0)


if __name__ == "__main__":
    unittest.main()
