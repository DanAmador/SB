"""sbhub's Hub: agents, locks and questions with defaults, kept in a state file."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import Hub  # noqa: E402


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

    def test_state_survives_a_restart(self):
        self.h.lock("k", "a")
        self.assertEqual(Hub(self.home).state()["locks"]["k"]["by"], "a")

    def test_a_session_silent_for_a_day_is_dropped_with_its_workers(self):
        h = self.h
        h.report({"agent": "a", "state": "working"})
        h.report({"agent": "w", "role": "worker", "parent": "a", "state": "working"})
        self.t += 86401
        self.assertEqual(h.state()["agents"], {})


if __name__ == "__main__":
    unittest.main()
