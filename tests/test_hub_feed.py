"""The live feed of a running worker (sbruns.feed_events, Hub.feed, GET /api/item/feed): its log read as it grows."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbhub  # noqa: E402
import sbruns  # noqa: E402


def say(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def tool(tid, name, **inp):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}})


def result(tid, text, error=False):
    return json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": text}], "is_error": error}]}})


class FeedEventsTest(unittest.TestCase):
    def test_a_claude_log_reads_as_sentences_calls_and_results(self):
        log = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5"}),
            json.dumps({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 50}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": ""}]}}),
            say("Reading the ticket first."),
            tool("t1", "Bash", command="grep -n foo bar.py\nsecond line", description="Find foo"),
            json.dumps({"type": "rate_limit_event", "rate_limit_info": {}}),
            result("t1", "bar.py:3: foo"),
            tool("t2", "Edit", file_path="/x/bar.py", old_string="a", new_string="b"),
            result("t2", "no match", error=True),
            json.dumps({"type": "result", "subtype": "success", "result": "Done."}),
            "a line on stderr",
        ])
        self.assertEqual(sbruns.feed_events(log), [
            {"k": "start", "model": "claude-sonnet-5-5"},
            {"k": "say", "text": "Reading the ticket first."},
            {"k": "tool", "id": "t1", "name": "Bash", "arg": "grep -n foo bar.py"},
            {"k": "result", "id": "t1", "ok": True, "text": "bar.py:3: foo"},
            {"k": "tool", "id": "t2", "name": "Edit", "arg": "/x/bar.py"},
            {"k": "result", "id": "t2", "ok": False, "text": "no match"},
            {"k": "end", "ok": True, "text": "Done."},
            {"k": "line", "text": "a line on stderr"},
        ])

    def test_a_long_result_is_cut(self):
        (_, r) = sbruns.feed_events("\n".join([tool("t", "Read", file_path="/a"), result("t", "x" * 5000)]))
        self.assertLessEqual(len(r["text"]), sbruns.FEED_TEXT + 1)
        self.assertTrue(r["text"].endswith("…"))

    def test_an_owner_message_handed_by_a_hook_shows(self):
        out = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
                          sbruns.OWNER_SAYS + "Wrap up now."}})
        line = json.dumps({"type": "system", "subtype": "hook_response", "hook_event": "PostToolUse", "stdout": out})
        self.assertEqual(sbruns.feed_events(line), [{"k": "owner", "text": "Wrap up now."}])

    def test_a_codex_log_reads_too(self):
        log = "\n".join([
            json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "Looking."}}),
            json.dumps({"type": "item.completed", "item": {"id": "i2", "type": "command_execution", "command": "ls",
                                                           "aggregated_output": "a\nb", "exit_code": 0}}),
        ])
        self.assertEqual([e["k"] for e in sbruns.feed_events(log)], ["say", "tool", "result"])


class HubFeedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.log = self.home / "7.log"
        self.log.write_text("old try\n")
        self.start = self.log.stat().st_size
        with open(self.log, "a") as f:
            f.write(say("First.") + "\n")
        item = {"key": "proj/one#7", "kind": "ticket", "state": "running", "log": str(self.log), "log_start": self.start}
        q = {"version": 3, "seeded": True, "paused": False, "agent": None, "items": [item]}
        (self.home / "state.json").write_text(json.dumps({"queue": q}))
        self.hub = sbhub.Hub(self.home, run=lambda: "[]")

    def append(self, text):
        with open(self.log, "a") as f:
            f.write(text)

    def test_it_reads_this_try_then_only_what_was_added(self):
        a = self.hub.feed("proj/one#7")
        self.assertEqual((a["log"], a["events"], a["live"], a["cut"]), ("7.log", [{"k": "say", "text": "First."}], False, False))
        self.assertEqual(self.hub.feed("proj/one#7", a["offset"], "7.log")["events"], [])
        third = say("Third.") + "\n"
        self.append(say("Second.") + "\n" + third[:20])  # the last line is still being written
        b = self.hub.feed("proj/one#7", a["offset"], "7.log")
        self.assertEqual(b["events"], [{"k": "say", "text": "Second."}])
        self.append(third[20:])
        c = self.hub.feed("proj/one#7", b["offset"], "7.log")
        self.assertEqual(c["events"], [{"k": "say", "text": "Third."}])

    def test_another_log_or_a_bad_offset_opens_afresh(self):
        a = self.hub.feed("proj/one#7")
        for after, log in ((a["offset"], "1-integrate.log"), (10 ** 9, "7.log"), (0, "7.log")):
            self.assertEqual(self.hub.feed("proj/one#7", after, log)["events"], [{"k": "say", "text": "First."}], (after, log))

    def test_a_running_worker_is_read_from_its_own_log(self):
        integ = self.home / "7-integrate.log"
        integ.write_text(say("Compiling.") + "\n")

        class Sup:
            procs = {"proj/one#7": {"log": str(integ), "start": 0}}
        self.hub.supervisor = Sup()
        a = self.hub.feed("proj/one#7")
        self.assertEqual((a["log"], a["live"], a["events"]), ("7-integrate.log", True, [{"k": "say", "text": "Compiling."}]))

    def test_a_long_log_opens_on_its_end_at_a_whole_line(self):
        self.append("".join(say("line {}".format(n)) + "\n" for n in range(4000)))
        a = self.hub.feed("proj/one#7")
        self.assertTrue(a["cut"])
        self.assertEqual(a["events"][-1], {"k": "say", "text": "line 3999"})
        self.assertTrue(all(e["k"] == "say" for e in a["events"]))  # no half line read as stderr

    def test_an_unknown_item_is_a_key_error(self):
        with self.assertRaises(KeyError):
            self.hub.feed("proj/one#8")


if __name__ == "__main__":
    unittest.main()
