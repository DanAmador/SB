"""Which session is in charge of which map: `report --map`, the queue writes, a worker's row, a dismissal."""
import json
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sbhub import Hub  # noqa: E402
from test_hub_queue import TICKETS  # noqa: E402


class ChargeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.h = Hub(self.home, run=lambda: json.dumps(TICKETS))
        self.h.tickets()
        for s in ("s1", "s2"):
            self.h.report({"agent": s, "state": "working"})

    def v(self):
        return self.h.state()["queue"]["version"]

    def test_report_map_sets_the_row_map(self):
        self.h.report({"agent": "s1", "map": "repo/one"})
        self.assertEqual(self.h.state()["agents"]["s1"]["map"], "repo/one")

    def test_queue_set_from_a_session_puts_it_in_charge_and_a_second_does_not_take_over(self):
        self.assertTrue(self.h.queue_set(["repo/one#1"], self.v(), "s1")["ok"])
        self.assertEqual(self.h.state()["charge"], {"repo/one": "s1"})
        self.h.queue_set(["repo/one#1", "repo/one#4"], self.v(), "s2")
        self.assertEqual(self.h.state()["charge"], {"repo/one": "s1"})

    def test_queue_map_from_a_session_puts_it_in_charge(self):
        self.assertTrue(self.h.queue_map("repo/one", self.v(), "s2")["ok"])
        self.assertEqual(self.h.state()["charge"], {"repo/one": "s2"})

    def test_an_unknown_session_or_none_takes_no_charge(self):
        self.h.queue_set(["repo/one#1"], self.v(), "ghost")
        self.h.queue_set(["repo/one#1", "repo/one#4"], self.v())
        self.assertEqual(self.h.state()["charge"], {})

    def test_a_queue_worker_row_has_its_map_and_in_charge(self):
        self.h.queue_set(["repo/one#1"], self.v(), "s1")
        self.h.report({"agent": "repo/one#1", "role": "worker", "parent": "queue", "state": "working"})
        w = self.h.state()["agents"]["repo/one#1"]
        self.assertEqual((w["map"], w["in_charge"]), ("repo/one", "s1"))

    def test_a_worker_of_a_map_nobody_is_in_charge_of_has_no_in_charge(self):
        self.h.report({"agent": "repo/one#1", "role": "worker", "parent": "queue", "state": "working"})
        w = self.h.state()["agents"]["repo/one#1"]
        self.assertEqual((w["map"], "in_charge" in w), ("repo/one", False))

    def test_a_dismissed_or_ended_session_is_no_longer_in_charge(self):
        self.h.queue_set(["repo/one#1"], self.v(), "s1")
        self.h.report({"agent": "repo/one#1", "role": "worker", "parent": "queue", "state": "working"})
        self.h.agents_dismiss("s1")
        s = self.h.state()
        self.assertEqual(s["charge"], {})
        self.assertNotIn("in_charge", s["agents"]["repo/one#1"])
        self.h.queue_set(["repo/one#1", "repo/one#4"], self.v(), "s2")  # now s2 may take it
        self.assertEqual(self.h.state()["charge"], {"repo/one": "s2"})
        self.h.report({"agent": "s2", "state": "gone"})
        self.assertEqual(self.h.state()["charge"], {})

    def test_a_state_file_saved_before_this_loads(self):
        old = {"agents": {"a": {"state": "idle", "at": time.time()}}, "locks": {}, "questions": {}, "aliases": {}, "messages": {}}
        home = self.home / "old"
        home.mkdir()
        (home / "state.json").write_text(json.dumps(old))
        h = Hub(home)
        self.assertEqual(h.state()["charge"], {})
        self.assertIn("a", h.state()["agents"])


if __name__ == "__main__":
    unittest.main()
