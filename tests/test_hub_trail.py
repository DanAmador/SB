"""sbhub keeps each agent's last 40 actions, fed by the hook events the hub already receives."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import Hub, event_report  # noqa: E402


def ev(name, **kw):
    return {"session_id": "abcdef123", "cwd": "/work/proj", "hook_event_name": name, **kw}


class TrailTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = 1000.0
        self.h = Hub(Path(self._tmp.name), now=lambda: self.t)

    def feed(self, name, dt=1, **kw):
        self.t += dt
        self.h.report(event_report(ev(name, **kw)))

    def test_a_pre_and_post_pair_and_a_failure_read_back(self):
        read = {"tool_name": "Read", "tool_input": {"file_path": "/x.py"}}
        bash = {"tool_name": "Bash", "tool_input": {"description": "run tests"}}
        self.feed("PreToolUse", **read)
        self.feed("PostToolUse", **read)
        self.feed("PreToolUse", **bash)
        self.assertEqual(self.h.trail("abcdef123")["actions"][-1]["end"], None)  # still running
        self.feed("PostToolUseFailure", **bash)
        t = self.h.trail("abcdef123")
        self.assertEqual(t["actions"], [
            {"tool": "Read", "label": "/x.py", "start": 1001.0, "end": 1002.0, "ok": True, "sub": False},
            {"tool": "Bash", "label": "run tests", "start": 1003.0, "end": 1004.0, "ok": False, "sub": False}])
        self.assertIsNone(t["ctx"])

    def test_prompt_stop_and_subagents(self):
        self.feed("UserPromptSubmit", prompt="do it")
        self.feed("SubagentStart", agent_id="w", agent_type="scout")
        self.feed("PreToolUse", agent_id="w", tool_name="Grep", tool_input={"pattern": "p"})
        self.feed("SubagentStop", agent_id="w")
        self.feed("Stop")
        a = self.h.trail("abcdef123")["actions"]
        self.assertEqual([(x["tool"], x["sub"], x["ok"]) for x in a],
                         [("prompt", False, True), ("scout", True, True), ("stop", False, True)])
        self.assertEqual(self.h.trail("w")["actions"][0]["tool"], "Grep")

    def test_the_ring_keeps_forty_and_state_does_not_carry_it(self):
        self.feed("SessionStart")
        before = len(json.dumps(self.h.state()))
        for i in range(60):
            self.feed("PostToolUse", tool_name="Read", tool_input={"file_path": str(i)})
        a = self.h.trail("abcdef123")["actions"]
        self.assertEqual((len(a), a[0]["label"], a[-1]["label"]), (40, "20", "59"))
        self.assertNotIn("trail", json.dumps(self.h.state()))
        self.assertLess(abs(len(json.dumps(self.h.state())) - before), 80)  # only `at` and `note` moved

    def test_an_ended_session_drops_its_trail_after_ten_minutes(self):
        self.feed("PostToolUse", tool_name="Read")
        self.h.report({"agent": "abcdef123", "state": "gone"})
        self.t += 599
        self.assertEqual(len(self.h.trail("abcdef123")["actions"]), 1)
        self.t += 2
        with self.assertRaises(KeyError):
            self.h.trail("abcdef123")

    def test_a_context_percent_is_kept_when_a_report_gives_one(self):
        self.h.report({"agent": "a", "trail": {"kind": "pre", "tool": "Read", "label": ""}, "ctx": 42})
        self.assertEqual(self.h.trail("a")["ctx"], 42)


if __name__ == "__main__":
    unittest.main()
