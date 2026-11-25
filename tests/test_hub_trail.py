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



class StuckTest(unittest.TestCase):
    """A queue worker's row in /api/state carries `stuck` ({why, since}) when its trail shows it going in circles
    (ticket 195), else null."""
    KEY = "repo/one#1"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = 1000.0
        self.h = Hub(Path(self._tmp.name), now=lambda: self.t)

    def act(self, kind, tool, label="", dt=10, ctx=None):
        self.t += dt
        d = {"agent": self.KEY, "role": "worker", "parent": "queue", "state": "working",
             "trail": {"kind": kind, "tool": tool, "label": label}}
        self.h.report({**d, "ctx": ctx} if ctx is not None else d)

    def call(self, tool, label="", ok=True, ctx=None):
        self.act("pre", tool, label, ctx=ctx)
        self.act("post" if ok else "fail", tool, label, dt=5)

    def stuck(self):
        return self.h.state()["agents"][self.KEY]["stuck"]

    def test_a_normal_run_is_not_stuck(self):
        for _ in range(4):
            self.call("Read", "/a.py")
            self.call("Bash", "pnpm test")
            self.call("Edit", "/a.py", ctx=40)
            self.call("Bash", "pnpm test", ok=False)  # a failing test now and then is work, not a loop
        self.assertIsNone(self.stuck())

    def test_the_same_command_three_times_in_a_row(self):
        self.call("Edit", "/a.py")
        self.call("Bash", "pnpm vitest run src/a.test.ts")
        start = self.t + 10
        for _ in range(3):
            self.call("Bash", "pnpm vitest run src/a.test.ts --reporter dot")
        self.assertEqual(self.stuck(), {"why": "ran the same command 3 times in a row: pnpm vitest run src/a.test.ts "
                                               "--reporter dot", "since": start})
        self.call("Read", "/a.py")
        self.assertIsNone(self.stuck())

    def test_three_failed_tool_calls_in_a_row(self):
        self.call("Read", "/a.py")
        self.call("Read", "/missing.py", ok=False)
        first = self.t
        self.call("Grep", "nothing", ok=False)
        self.assertIsNone(self.stuck())
        self.call("Bash", "make", ok=False)
        self.assertEqual(self.stuck(), {"why": "3 failed tool calls in a row", "since": first})

    def test_no_file_changed_for_fifteen_minutes(self):
        self.call("Edit", "/a.py")
        edited = self.t  # its Write ended then
        for i in range(80):
            self.call("Read", "/{}.py".format(i))  # 15 s a call: 20 minutes of reading
            if self.t - edited < 15 * 60:
                self.assertIsNone(self.stuck())
        self.assertEqual(self.stuck(), {"why": "changed no file for 20 minutes", "since": edited})
        self.call("Write", "/b.py")
        self.assertIsNone(self.stuck())

    def test_context_past_seventy_percent(self):
        self.call("Edit", "/a.py", ctx=69)
        self.assertIsNone(self.stuck())
        self.call("Read", "/a.py", ctx=72)
        over = self.t - 5  # its pre carried the 72
        self.call("Read", "/b.py", ctx=74)
        self.assertEqual(self.stuck(), {"why": "context at 74%", "since": over})

    def test_a_chat_session_and_a_finished_worker_carry_no_flag(self):
        self.h.report({"agent": "chat-1", "state": "working", "trail": {"kind": "pre", "tool": "Read", "label": ""},
                       "ctx": 95})
        self.assertNotIn("stuck", self.h.state()["agents"]["chat-1"])
        for _ in range(3):
            self.call("Bash", "make")
        self.h.report({"agent": self.KEY, "state": "done"})
        self.assertIsNone(self.stuck())

if __name__ == "__main__":
    unittest.main()
