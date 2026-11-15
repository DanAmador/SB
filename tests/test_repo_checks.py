"""A ticket with no commands of its own runs the repo's .sb/checks (ticket > map > repo)."""
import json
import sys
from pathlib import Path

from helpers import VaultCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbqueue  # noqa: E402


class RepoChecksTest(VaultCase):
    def setUp(self):
        super().setUp()
        self.repo = Path(self._tmp.name) / "proj"
        (self.repo / ".sb").mkdir(parents=True)
        self.sb("init", "proj/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.", "--repo", str(self.repo))
        self.sb("new", "proj/one", "--title", "T", "--why", "Because.", "--done-when", "1. ok", "--no-sync")

    def write(self, text):
        (self.repo / ".sb" / "checks").write_text(text)

    def row(self):
        return json.loads(self.sb("tickets", "--json").stdout)[0]

    def test_repo_file_used_and_ticket_is_ready_with_it(self):
        self.write("# defaults\n\nmake test\n  \n  # more\nmake lint\n")
        r = self.row()
        self.assertEqual((r["checks"], r["checks_from"]), (["make test", "make lint"], "repo"))
        self.assertEqual(sbqueue.classify(r, set()), ("ready", "ready"))

    def test_ticket_beats_map_beats_repo(self):
        self.write("repo cmd\n")
        self.assertEqual(self.row()["checks_from"], "repo")
        self.sb("mapset", "proj/one", "checks=map cmd")
        self.assertEqual((self.row()["checks"], self.row()["checks_from"]), (["map cmd"], "map"))
        self.sb("set", "proj/one", "1", "checks=own cmd", "--no-sync")
        self.assertEqual((self.row()["checks"], self.row()["checks_from"]), (["own cmd"], "ticket"))

    def test_no_file_means_none(self):
        r = self.row()
        self.assertEqual((r["checks"], r["checks_from"]), ([], ""))
        self.write("# only a comment\n\n")
        self.assertEqual(self.row()["checks"], [])

    def test_edit_is_seen_on_the_next_read(self):
        # the queue classifies fresh `tickets --json` rows each pass, so an edited file reaches a queued ticket
        self.write("old cmd\n")
        self.assertEqual(self.row()["checks"], ["old cmd"])
        self.write("new cmd\n")
        self.assertEqual(self.row()["checks"], ["new cmd"])
