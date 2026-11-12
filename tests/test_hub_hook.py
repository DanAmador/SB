"""sbhub's hook command: Claude Code events become reports, and never fail a session."""
import json
import sys
import tempfile
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
        self.assertEqual(r["note"], "Task")  # no detail, no dangling colon

    def test_pre_tool_use_note_is_cut_to_90(self):
        r = sbhub.event_report(ev("PreToolUse", tool_name="Read", tool_input={"file_path": "x" * 200}))
        self.assertEqual(len(r["note"]), 90)

    def test_pre_tool_use_from_a_subagent_lands_on_it(self):
        r = sbhub.event_report(ev("PreToolUse", agent_id="w", tool_name="Grep", tool_input={"pattern": "p"}))
        self.assertEqual((r["agent"], r["role"], r["parent"], r["state"]), ("w", "worker", "abcdef123", "working"))

    def test_notification(self):
        r = sbhub.event_report(ev("Notification", message="needs permission"))
        self.assertEqual((r["agent"], r["state"], r["note"]), ("abcdef123", "needs you", "needs permission"))

    def test_an_idle_prompt_is_your_turn_not_needs_you(self):
        for kw in ({"notification_type": "idle_prompt", "message": "Claude is idle"},
                   {"message": "Claude is waiting for your input"}):
            r = sbhub.event_report(ev("Notification", **kw))
            self.assertEqual((r["state"], r["note"]), ("your turn", kw["message"]), kw)
        r = sbhub.event_report(ev("Notification", notification_type="permission_prompt",
                                  message="Claude is waiting for your input"))
        self.assertEqual(r["state"], "needs you")

    def test_a_bash_call_of_sbhub_report_names_the_session_alias(self):
        def bash(cmd, **kw):
            return sbhub.event_report(ev("PreToolUse", tool_name="Bash", tool_input={"command": cmd}, **kw))
        cmd = 'cd /x && python3 ~/.claude/skills/sb/scripts/sbhub.py report --agent night-run --note "a b"'
        self.assertEqual(bash(cmd)["alias"], "night-run")
        self.assertEqual(bash(cmd.replace("--agent night-run", "--agent=night-run"))["alias"], "night-run")
        for other in ("python3 sbhub.py report --note x", "python3 sbhub.py ask --agent a --q q",
                      'python3 sbhub.py report --agent "unclosed', "echo report --agent x",
                      "python3 sbhub.py report --agent"):
            r = bash(other)
            self.assertNotIn("alias", r, other)
            self.assertEqual(r["agent"], "abcdef123")
        self.assertNotIn("alias", bash(cmd, agent_id="w"))

    def test_an_mcp_sb_report_call_names_the_session_alias(self):
        for tname in ("sb_report", "mcp__sbhub__sb_report", "mcp__plugin_hub-report_sbhub__sb_report"):
            r = sbhub.event_report(ev("PreToolUse", tool_name=tname, tool_input={"agent": "night-run", "state": "working"}))
            self.assertEqual(r["alias"], "night-run", tname)
        worker_report = sbhub.event_report(ev("PreToolUse", tool_name="mcp__sbhub__sb_report",
                                              tool_input={"agent": "w1", "parent": "night-run"}))
        self.assertNotIn("alias", worker_report)
        role_worker = sbhub.event_report(ev("PreToolUse", tool_name="mcp__sbhub__sb_report",
                                            tool_input={"agent": "w1", "role": "worker"}))
        self.assertNotIn("alias", role_worker)

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

    def test_every_event_of_the_session_says_who_it_is(self):
        for name, kw in (("PreToolUse", {"tool_name": "Grep", "tool_input": {}}),
                         ("Notification", {"message": "m"}), ("Stop", {}),
                         ("UserPromptSubmit", {}), ("SessionStart", {})):
            r = sbhub.event_report(ev(name, **kw))
            self.assertEqual({k: r[k] for k in SESSION}, SESSION, name)

    def test_session_end(self):
        self.assertEqual(sbhub.event_report(ev("SessionEnd")), {"agent": "abcdef123", "state": "gone"})

    def test_other_events_are_ignored(self):
        self.assertIsNone(sbhub.event_report({"hook_event_name": "PreCompact"}))


def agy(**kw):
    return {"conversationId": "c1234567-89ab", "workspacePaths": ["/work/proj"], **kw}


AGY_SESSION = {"agent": "c1234567-89ab", "name": "proj c12345", "project": "/work/proj", "role": "orchestrator"}


class AntigravityEventReportTest(unittest.TestCase):
    def test_session_start_and_pre_invocation(self):
        self.assertEqual(sbhub.event_report(agy(), event="SessionStart"),
                         {**AGY_SESSION, "state": "idle", "note": "session started"})
        self.assertEqual(sbhub.event_report(agy(), event="PreInvocation"),
                         {**AGY_SESSION, "state": "working", "note": "thinking"})

    def test_post_tool_use_and_aliasing(self):
        r = sbhub.event_report(agy(toolCall={"name": "run_command", "args": {
            "toolSummary": "Run tests", "CommandLine": "python3 sbhub.py report --agent night-run"}}),
            event="PostToolUse")
        self.assertEqual((r["state"], r["note"], r["alias"]), ("working", "run_command: Run tests", "night-run"))
        r2 = sbhub.event_report(agy(toolCall={"name": "call_mcp_tool", "args": {
            "ToolName": "sb_report", "Arguments": {"agent": "agy-run"}}}), event="PostToolUse")
        self.assertEqual(r2["alias"], "agy-run")
        r3 = sbhub.event_report(agy(toolCall={"name": "call_mcp_tool", "args": {
            "ToolName": "sb_report", "Arguments": {"agent": "w1", "parent": "agy-run"}}}), event="PostToolUse")
        self.assertNotIn("alias", r3)

    def test_stop_and_error(self):
        self.assertEqual(sbhub.event_report(agy(terminationReason="NO_TOOL_CALL"), event="Stop"),
                         {**AGY_SESSION, "state": "your turn", "note": "finished its turn"})
        self.assertEqual(sbhub.event_report(agy(terminationReason="ERROR", error="boom"), event="Stop"),
                         {**AGY_SESSION, "state": "blocked", "note": "boom"})


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

    def test_antigravity_hook_prints_empty_json_and_reports(self):
        r = self.hub("hook", "--event", "PostToolUse", stdin=json.dumps(
            agy(toolCall={"name": "read_file", "args": {"Path": "/work/proj/a.py"}})))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "{}"))
        a = self.get("/api/state")["agents"]["c1234567-89ab"]
        self.assertEqual((a["state"], a["note"]), ("working", "read_file: /work/proj/a.py"))


if __name__ == "__main__":
    unittest.main()


class SessionsSayWhatTheyAreDoing(unittest.TestCase):
    """A row is named by the session's own title and ticket, not by a folder and an id."""

    def test_the_title_is_the_last_one_in_the_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "s.jsonl"
            t.write_text('{"type":"custom-title","customTitle":"Old"}\n{"type":"user"}\nnot json\n'
                         '{"type":"custom-title","customTitle":"Hub lock fix"}\n{"type":"assistant"}\n')
            self.assertEqual(sbhub.session_title(str(t)), "Hub lock fix")
            self.assertIsNone(sbhub.session_title(str(Path(d) / "missing.jsonl")))
            self.assertIsNone(sbhub.session_title(None))

    def test_a_prompt_is_kept_as_what_was_asked(self):
        r = sbhub.event_report({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/p",
                                "prompt": "fix the lock\nand then " + "x" * 300})
        self.assertEqual(r["asked"], ("fix the lock and then " + "x" * 300)[:140])

    def test_a_claim_names_the_ticket_by_its_title(self):
        with tempfile.TemporaryDirectory() as d:
            issues = Path(d) / "wayfinder" / "repo" / "effort" / "issues"
            issues.mkdir(parents=True)
            (issues / "012 Two agents cannot claim one ticket.md").write_text("")
            cmd = 'python3 ~/.claude/skills/sb/scripts/sbmap.py claim repo/effort 012 --by "me"'
            self.assertEqual(sbhub.claimed_ticket(cmd, vault=d), "Two agents cannot claim one ticket")
            self.assertEqual(sbhub.claimed_ticket(cmd.replace("012", "099"), vault=d), "repo/effort 099")
            self.assertIsNone(sbhub.claimed_ticket("echo claim", vault=d))
            self.assertIsNone(sbhub.claimed_ticket('unbalanced "quote', vault=d))

    def test_a_subagent_is_named_by_what_it_was_sent_to_do(self):
        with tempfile.TemporaryDirectory() as d:
            h = sbhub.Hub(Path(d))
            h.report(sbhub.event_report({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": "/p",
                                         "tool_name": "Agent", "tool_input": {"description": "Review Task 6"}}))
            h.report(sbhub.event_report({"hook_event_name": "SubagentStart", "session_id": "s", "cwd": "/p",
                                         "agent_id": "w1", "agent_type": "general-purpose"}))
            h.report(sbhub.event_report({"hook_event_name": "SubagentStart", "session_id": "s", "cwd": "/p",
                                         "agent_id": "w2", "agent_type": "scout"}))
            agents = h.state()["agents"]
            self.assertEqual(agents["w1"]["ticket"], "Review Task 6")
            self.assertNotIn("ticket", agents["w2"])
            self.assertNotIn("spawn", agents["s"])

    def test_a_connector_tool_is_named_by_its_last_word(self):
        r = sbhub.event_report({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": "/p",
                                "tool_name": "mcp__Claude_Browser__navigate", "tool_input": {}})
        self.assertEqual(r["note"], "navigate")

    def test_a_message_from_another_agent_is_not_what_the_owner_asked(self):
        for prompt in ('<agent-message from="a1">report</agent-message>', "[SYSTEM NOTIFICATION - NOT USER INPUT] x",
                       "<system-reminder>x</system-reminder>", "Another Claude session sent a message: <agent-message>"):
            r = sbhub.event_report({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/p", "prompt": prompt})
            self.assertNotIn("asked", r, prompt)
