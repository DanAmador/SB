"""sbhub's hook command: Claude Code events become reports, and never fail a session."""
import json
import sys
import unittest
from pathlib import Path

from helpers import HubCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbhub  # noqa: E402


def ev(name, **kw):
    return {"session_id": "abcdef123", "cwd": "/work/proj", "hook_event_name": name, **kw}


SESSION = {"agent": "abcdef123", "name": "proj abcdef", "project": "/work/proj", "role": "orchestrator"}


class EventReportTest(unittest.TestCase):
    def test_session_start(self):
        self.assertEqual(sbhub.event_report(ev("SessionStart")),
                         {**SESSION, "state": "idle", "note": "session started"})

    def test_user_prompt_submit(self):
        self.assertEqual(sbhub.event_report(ev("UserPromptSubmit")),
                         {**SESSION, "state": "working", "note": "reading your message"})

    def test_pre_tool_use_detail_order(self):
        r = sbhub.event_report(ev("PreToolUse", tool_name="Bash", tool_input={
            "description": "run tests", "file_path": "/x", "pattern": "p"}))
        self.assertEqual((r["state"], r["note"]), ("working", "Bash: run tests"))
        r = sbhub.event_report(ev("PreToolUse", tool_name="Read", tool_input={"file_path": "/x", "pattern": "p"}))
        self.assertEqual(r["note"], "Read: /x")
        r = sbhub.event_report(ev("PreToolUse", tool_name="Grep", tool_input={"pattern": "p"}))
        self.assertEqual(r["note"], "Grep: p")
        r = sbhub.event_report(ev("PreToolUse", tool_name="Task", tool_input={}))
        self.assertEqual(r["note"], "Task: ")

    def test_pre_tool_use_note_is_cut_to_90(self):
        r = sbhub.event_report(ev("PreToolUse", tool_name="Read", tool_input={"file_path": "x" * 200}))
        self.assertEqual(len(r["note"]), 90)

    def test_pre_tool_use_from_a_subagent_lands_on_it(self):
        r = sbhub.event_report(ev("PreToolUse", agent_id="w", tool_name="Grep", tool_input={"pattern": "p"}))
        self.assertEqual((r["agent"], r["role"], r["parent"], r["state"]), ("w", "worker", "abcdef123", "working"))

    def test_notification(self):
        r = sbhub.event_report(ev("Notification", message="needs permission"))
        self.assertEqual((r["agent"], r["state"], r["note"]), ("abcdef123", "needs you", "needs permission"))

    def test_stop(self):
        r = sbhub.event_report(ev("Stop"))
        self.assertEqual((r["agent"], r["state"], r["note"]), ("abcdef123", "your turn", "finished its turn"))

    def test_subagent_start_and_stop(self):
        r = sbhub.event_report(ev("SubagentStart", agent_id="w", agent_type="scout"))
        self.assertEqual(r, {"agent": "w", "name": "scout", "role": "worker", "parent": "abcdef123",
                             "state": "working", "note": "started"})
        r = sbhub.event_report(ev("SubagentStop", agent_id="w"))
        self.assertEqual(r, {"agent": "w", "role": "worker", "parent": "abcdef123",
                             "state": "done", "note": "finished"})

    def test_session_end(self):
        self.assertEqual(sbhub.event_report(ev("SessionEnd")), {"agent": "abcdef123", "state": "gone"})

    def test_other_events_are_ignored(self):
        self.assertIsNone(sbhub.event_report({"hook_event_name": "PreCompact"}))


class HookCommandTest(HubCase):
    def test_hook_never_fails(self):
        for stdin, port in (("{bad json", self.port), ("", self.port), ("[1]", self.port),
                            ('{"hook_event_name":"Stop"}', self.port),
                            ('{"session_id":"s","hook_event_name":"Stop","cwd":"/p"}', 1)):
            r = self.hub("hook", stdin=stdin, port=port)
            self.assertEqual(r.returncode, 0, stdin)

    def test_hook_reports_to_the_hub(self):
        self.hub("hook", stdin=json.dumps(ev("PreToolUse", tool_name="Grep", tool_input={"pattern": "claim"})))
        a = self.get("/api/state")["agents"]["abcdef123"]
        self.assertEqual((a["state"], a["note"]), ("working", "Grep: claim"))

    def test_a_subagents_tool_call_lands_on_the_worker(self):
        self.hub("hook", stdin=json.dumps(ev("SubagentStart", agent_id="w", agent_type="scout")))
        self.hub("hook", stdin=json.dumps(ev("PreToolUse", agent_id="w", tool_name="Grep",
                                             tool_input={"pattern": "claim"})))
        w = self.get("/api/state")["agents"]["w"]
        self.assertEqual((w["parent"], w["name"], w["note"]), ("abcdef123", "scout", "Grep: claim"))


if __name__ == "__main__":
    unittest.main()
