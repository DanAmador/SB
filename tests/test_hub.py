"""sbhub's Hub: agents, locks and questions with defaults, kept in a state file."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import Hub, event_report  # noqa: E402


class HubTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.t = 1000.0
        self.h = Hub(self.home, now=lambda: self.t)

    def tearDown(self):
        self._tmp.cleanup()

    def test_report_merges_and_keeps_earlier_fields(self):
        h = self.h
        h.report({"agent": "a", "project": "/p", "role": "orchestrator", "state": "working", "total": 5})
        h.report({"agent": "a", "state": "idle", "note": ""})
        a = h.state()["agents"]["a"]
        self.assertEqual((a["state"], a["total"], a["project"]), ("idle", 5, "/p"))

    def test_since_marks_when_the_state_last_changed(self):
        h = self.h
        h.report({"agent": "a", "state": "working", "note": "Read: x"})
        self.t += 30
        h.report({"agent": "a", "state": "working", "note": "Edit: y"})
        h.report({"agent": "a", "note": "no state given"})
        self.assertEqual(h.state()["agents"]["a"]["since"], 1000.0)
        self.t += 30
        h.report({"agent": "a", "state": "your turn"})
        self.assertEqual(h.state()["agents"]["a"]["since"], 1060.0)
        self.t += 5
        h.report({"agent": "a", "state": "working"})
        self.assertEqual(h.state()["agents"]["a"]["since"], 1065.0)

    def test_an_agent_reported_without_a_state_has_no_since(self):
        self.h.report({"agent": "a", "note": "hello"})
        self.assertNotIn("since", self.h.state()["agents"]["a"])

    def test_state_carries_each_agents_id_for_the_page(self):
        h = self.h
        h.report({"agent": "night-run", "state": "working"})
        h.report({"agent": "w1", "role": "worker", "parent": "night-run"})
        got = h.state()["agents"]
        self.assertEqual((got["night-run"]["agent"], got["w1"]["agent"], got["w1"]["parent"]), ("night-run", "w1", "night-run"))

    def test_needs_you_fires_once_per_transition(self):
        h = self.h
        self.assertTrue(h.report({"agent": "a", "state": "needs you"})["needs_you"])
        self.assertFalse(h.report({"agent": "a", "state": "needs you"})["needs_you"])

    def test_gone_removes_the_session_and_its_workers(self):
        h = self.h
        h.report({"agent": "a", "state": "working"})
        h.report({"agent": "w", "role": "worker", "parent": "a", "state": "working"})
        h.report({"agent": "a", "state": "gone"})
        self.assertEqual(h.state()["agents"], {})

    def test_lock_refuses_a_second_holder(self):
        h = self.h
        self.assertTrue(h.lock("unity-editor", "a")["ok"])
        self.assertEqual(h.lock("unity-editor", "b"), {"ok": False, "held_by": "a"})
        h.unlock("unity-editor", "b")
        self.assertFalse(h.lock("unity-editor", "b")["ok"])
        h.unlock("unity-editor", "a")
        self.assertTrue(h.lock("unity-editor", "b")["ok"])

    def test_ask_needs_two_to_four_options_and_a_listed_default(self):
        for opts, d in ((["only"], "only"), (list("abcde"), "a"), (["a", "b"], "c")):
            with self.assertRaises(ValueError):
                self.h.ask("a", "q?", opts, d, 0)

    def test_default_applies_at_the_deadline(self):
        h = self.h
        qid = h.ask("a", "q?", ["x", "y"], "y", 60)["id"]
        self.assertIsNone(h.state()["questions"][qid]["answer"])
        self.t += 61
        q = h.state()["questions"][qid]
        self.assertEqual((q["answer"], q["by"]), ("y", "default"))

    def test_first_answer_stands(self):
        h = self.h
        qid = h.ask("a", "q?", ["x", "y"], "y", 60)["id"]
        h.answer(qid, "x")
        h.answer(qid, "y")
        self.assertEqual(h.question(qid)["answer"], "x")
        with self.assertRaises(ValueError):
            h.answer(h.ask("a", "q2?", ["x", "y"], "y", 60)["id"], "z")

    def test_a_late_answer_does_not_replace_the_default(self):
        h = self.h
        qid = h.ask("a", "q?", ["x", "y"], "y", 60)["id"]
        self.t += 61
        h.answer(qid, "x")
        q = h.question(qid)
        self.assertEqual((q["answer"], q["by"]), ("y", "default"))

    def test_ask_wait_must_be_a_number_of_zero_or_more(self):
        for wait in (-1, "5", None, True):
            with self.assertRaises(ValueError):
                self.h.ask("a", "q?", ["x", "y"], "y", wait)

    def test_a_corrupt_or_empty_state_file_starts_empty(self):
        for text in ("", "{not json", "[]"):
            (self.home / "state.json").write_text(text, encoding="utf-8")
            self.assertEqual(Hub(self.home).state()["agents"], {})

    def test_a_finished_worker_leaves_after_ten_minutes(self):
        h = self.h
        h.report({"agent": "a", "state": "working"})
        h.report({"agent": "w", "role": "worker", "parent": "a", "state": "done"})
        h.report({"agent": "v", "role": "worker", "parent": "a", "state": "working"})
        self.t += 601
        h.report({"agent": "a", "state": "working"})
        self.assertEqual(sorted(h.state()["agents"]), ["a", "v"])

    def test_state_survives_a_restart(self):
        self.h.lock("k", "a")
        self.assertEqual(Hub(self.home, now=lambda: self.t).state()["locks"]["k"]["by"], "a")

    def test_a_session_silent_for_a_day_is_dropped_with_its_workers(self):
        h = self.h
        h.report({"agent": "a", "state": "working"})
        h.report({"agent": "w", "role": "worker", "parent": "a", "state": "working"})
        self.t += 86401
        self.assertEqual(h.state()["agents"], {})

    def test_a_decided_question_is_stamped_when_it_is_decided(self):
        h = self.h
        ids = []
        for i in range(6):
            self.t += 1
            qid = h.ask("a", "q{}?".format(i), ["x", "y"], "y", 60 if i % 2 else 0)["id"]
            ids.append(qid)
            if i % 2:
                h.answer(qid, "x")
            else:
                h.state()  # the default applies on this settle
        qs = h.state()["questions"]
        self.assertEqual([qs[q]["answered"] for q in ids], [1001.0, 1002.0, 1003.0, 1004.0, 1005.0, 1006.0])

    def test_only_the_fifty_latest_decided_questions_are_kept(self):
        h = self.h
        decided = []
        for i in range(55):
            self.t += 1
            qid = h.ask("a", "q?", ["x", "y"], "y", 60)["id"]
            h.answer(qid, "x")
            decided.append(qid)
        still = h.ask("a", "open?", ["x", "y"], "y", 600)["id"]
        qs = h.state()["questions"]
        self.assertEqual(set(qs), set(decided[5:]) | {still})

    def test_ask_refuses_bad_waits_questions_and_options(self):
        for q, opts, wait in (("q?", ["x", "y"], float("nan")), ("q?", ["x", "y"], float("inf")),
                              ("q?", ["x", "x"], 5), ("q?", ["x", ""], 5), ("q?", ["x", 1], 5),
                              ("", ["x", "y"], 5), (None, ["x", "y"], 5), ("q?", "xy", 5)):
            with self.assertRaises(ValueError, msg=(q, opts, wait)):
                self.h.ask("a", q, opts, "x", wait)

    def test_a_lock_whose_holder_is_gone_expires_after_ten_minutes(self):
        h = self.h
        h.report({"agent": "a", "state": "working"})
        h.lock("listed", "a")
        h.lock("orphan", "ghost")
        self.t += 599
        self.assertEqual(set(h.state()["locks"]), {"listed", "orphan"})
        self.t += 2
        self.assertEqual(set(h.state()["locks"]), {"listed"})

    def test_a_lock_held_through_an_alias_does_not_expire(self):
        h = self.h
        h.report({"agent": "s1", "alias": "night-run", "state": "working"})
        h.lock("editor", "night-run")
        h.lock("port", "s1")
        self.t += 700
        self.assertEqual(set(h.state()["locks"]), {"editor", "port"})


def hook(sid, name, **kw):
    return event_report({"session_id": sid, "cwd": "/work/proj", "hook_event_name": name, **kw})


REPORT = ('python3 ~/.claude/skills/sb/scripts/sbhub.py report --agent night-run --role orchestrator '
          '--done 1 --total 5 --note "x"')


class OneRowPerSessionTest(unittest.TestCase):
    """A session that reports as `--agent X` is X: its hook events and its workers land on X's row."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.t = 1000.0
        self.h = h = Hub(self.home, now=lambda: self.t)
        h.report(hook("s1", "SessionStart"))
        h.report(hook("s1", "SubagentStart", agent_id="early", agent_type="scout"))
        h.report(hook("s1", "PreToolUse", tool_name="Bash", tool_input={"command": REPORT}))
        h.report({"agent": "night-run", "role": "orchestrator", "done": "1", "total": "5", "note": "x"})
        h.report(hook("s1", "SubagentStart", agent_id="late", agent_type="scout"))
        h.report(hook("s1", "Stop"))

    def test_the_session_and_its_reports_are_one_row(self):
        agents = self.h.state()["agents"]
        self.assertNotIn("s1", agents)
        a = agents["night-run"]
        self.assertEqual((a["done"], a["total"], a["state"], a["project"], a.get("name")),
                         ("1", "5", "your turn", "/work/proj", None))
        self.assertEqual((agents["early"]["parent"], agents["late"]["parent"]), ("night-run", "night-run"))

    def test_the_alias_survives_a_restart(self):
        h = Hub(self.home, now=lambda: self.t)
        h.report(hook("s1", "UserPromptSubmit"))
        self.assertNotIn("s1", h.state()["agents"])
        self.assertEqual(h.state()["agents"]["night-run"]["state"], "working")

    def test_session_end_removes_the_row_its_workers_and_the_alias(self):
        h = self.h
        h.report(hook("s1", "SessionEnd"))
        self.assertEqual(h.state()["agents"], {})
        h.report(hook("s1", "Stop"))
        self.assertEqual(list(h.state()["agents"]), ["s1"])

    def test_a_worker_session_shows_once_under_its_run(self):
        h = self.h
        h.report(hook("s2", "SessionStart"))
        cmd = REPORT.replace("night-run --role orchestrator", "ticket-012 --role worker --parent night-run")
        h.report(hook("s2", "PreToolUse", tool_name="Bash", tool_input={"command": cmd}))
        h.report({"agent": "ticket-012", "role": "worker", "parent": "night-run", "state": "working"})
        h.report(hook("s2", "PreToolUse", tool_name="Read", tool_input={"file_path": "/x"}))
        agents = h.state()["agents"]
        self.assertNotIn("s2", agents)
        w = agents["ticket-012"]
        self.assertEqual((w["role"], w["parent"], w["note"]), ("worker", "night-run", "Read: /x"))


if __name__ == "__main__":
    unittest.main()
