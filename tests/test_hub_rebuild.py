"""A landed ticket that touches the hub's own code rebuilds its page and restarts the hub (fake build and restart)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import Hub, Rebuild, TicketRun, rebuild_kind  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


class RebuildTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        self.commit("README.md")
        self.hub = Hub(Path(self._tmp.name) / "home")
        self.calls, self.build_ok = [], True
        self.rb = Rebuild(self.hub, root=str(self.repo), build=self.build, restart=self.restart)

    def commit(self, *paths):
        for p in paths:
            f = self.repo / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(p + str(len(list(self.repo.rglob("*")))))
            git(self.repo, "add", p)
        git(self.repo, "commit", "-qm", "c")
        return git(self.repo, "rev-parse", "HEAD")

    def build(self):
        self.calls.append("build")
        return self.build_ok, "line1\nTS2322: bad type" if not self.build_ok else "ok"

    def restart(self):
        self.calls.append("restart")
        return True, ""

    def landed(self, *paths):
        base = git(self.repo, "rev-parse", "HEAD")
        sha = self.commit(*paths)
        runner = TicketRun.__new__(TicketRun)
        runner.rebuild = self.rb
        th = runner.rebuild_after(self.repo, base, sha)
        if th:
            th.join(10)
        return th

    def test_kinds(self):
        self.assertEqual(rebuild_kind(["skills/sb/hub/packages/server/src/a.ts"]), "restart")
        self.assertEqual(rebuild_kind(["skills/sb/scripts/sbhub_lan.py"]), "restart")
        self.assertEqual(rebuild_kind(["skills/sb/hub/packages/web/src/a.tsx"]), "web")
        self.assertEqual(rebuild_kind(["skills/sb/hub/packages/web/src/a.tsx", "skills/sb/scripts/sbhub.py"]), "restart")
        self.assertIsNone(rebuild_kind(["skills/sb/scripts/sbmap.py", "tests/test_hub.py", "README.md"]))

    def test_hub_paths_build_and_restart(self):
        self.landed("skills/sb/scripts/sbhub.py")
        self.assertEqual(self.calls, ["build", "restart"])

    def test_web_only_builds_without_restart(self):
        self.landed("skills/sb/hub/packages/web/src/x.tsx")
        self.assertEqual(self.calls, ["build"])

    def test_other_paths_do_nothing(self):
        self.assertIsNone(self.landed("skills/sb/scripts/sbmap.py", "tests/t.py"))
        self.assertEqual(self.calls, [])

    def test_another_checkout_does_nothing(self):
        self.rb.root = str(Path(self._tmp.name) / "elsewhere")
        self.assertIsNone(self.landed("skills/sb/scripts/sbhub.py"))
        self.assertEqual(self.calls, [])

    def test_a_failed_build_does_not_restart_and_tells_the_owner(self):
        self.build_ok = False
        self.landed("skills/sb/scripts/sbhub.py")
        self.assertEqual(self.calls, ["build"])
        qs = list(self.hub.state()["questions"].values())
        self.assertEqual(len(qs), 1)
        self.assertIn("TS2322: bad type", qs[0]["q"])

    def test_it_waits_while_a_ticket_of_the_repo_is_landing(self):
        self.rb.landing_in(str(self.repo), 1)
        self.commit("skills/sb/scripts/sbhub.py")
        th = self.rb.after(self.repo, ["skills/sb/scripts/sbhub.py"])
        th.join(1.5)
        self.assertEqual(self.calls, [])
        self.rb.landing_in(str(self.repo), -1)
        th.join(10)
        self.assertEqual(self.calls, ["build", "restart"])


if __name__ == "__main__":
    unittest.main()
