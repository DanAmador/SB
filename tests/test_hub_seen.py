"""The hub keeps which ended runs the owner has opened (POST api/run/seen), in state.json."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import Hub, SEEN_KEPT  # noqa: E402


class SeenTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.hub = Hub(self.home, now=lambda: 1000.0)

    def test_a_new_hub_has_seen_nothing(self):
        self.assertEqual(self.hub.state()["seen"], [])

    def test_a_mark_is_in_state_and_survives_a_restart(self):
        self.assertEqual(self.hub.run_seen("repo/one#1@900"), {"ok": True})
        self.assertEqual(self.hub.state()["seen"], ["repo/one#1@900"])
        saved = json.loads((self.home / "state.json").read_text())
        self.assertEqual(saved["seen"], ["repo/one#1@900"])
        self.assertEqual(Hub(self.home, now=lambda: 1000.0).state()["seen"], ["repo/one#1@900"])

    def test_marking_twice_keeps_one_and_the_oldest_marks_drop(self):
        self.hub.run_seen("a#1@1")
        self.hub.run_seen("a#1@1")
        self.assertEqual(self.hub.state()["seen"], ["a#1@1"])
        for n in range(SEEN_KEPT + 5):
            self.hub.run_seen("b#1@{}".format(n))
        seen = self.hub.state()["seen"]
        self.assertEqual(len(seen), SEEN_KEPT)
        self.assertEqual(seen[-1], "b#1@{}".format(SEEN_KEPT + 4))

    def test_an_empty_key_is_refused(self):
        for bad in ("", "  ", None, 3):
            with self.assertRaises(ValueError):
                self.hub.run_seen(bad)


if __name__ == "__main__":
    unittest.main()
