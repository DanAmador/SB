"""`sbmap check` warns when no layer (ticket, map, repo .sb/checks) has checks."""
from pathlib import Path

from helpers import VaultCase


class CheckRepoTest(VaultCase):
    def setUp(self):
        super().setUp()
        self.repo = Path(self._tmp.name) / "proj"
        (self.repo / ".sb").mkdir(parents=True)
        self.sb("init", "proj/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.", "--repo", str(self.repo))
        self.sb("new", "proj/one", "--title", "T", "--why", "Because.", "--done-when", "1. ok", "--no-sync")

    def out(self):
        r = self.sb("check", "proj/one")
        return r.stdout + r.stderr

    def test_warns_without_file(self):
        self.assertIn("no checks anywhere", self.out())

    def test_quiet_with_file(self):
        (self.repo / ".sb" / "checks").write_text("make test\n")
        self.assertNotIn("no checks anywhere", self.out())
