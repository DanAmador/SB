"""A check whose output says Unity has no instance for the ticket's own worktree fails at once (ticket 188)."""
import subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbqueue  # noqa: E402


def git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


class SetupWrong(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = Path(self.tmp.name) / "main"
        self.main.mkdir()
        git("init", "-q", cwd=self.main)
        git("commit", "-q", "--allow-empty", "-m", "base", cwd=self.main)
        self.tree = Path(self.tmp.name) / "tree"
        git("worktree", "add", "-q", "--detach", str(self.tree), cwd=self.main)
        git("commit", "-q", "--allow-empty", "-m", "work\n\nTicket: m/p/007", cwd=self.tree)
        self.base = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=self.tree, capture_output=True,
                                   text=True).stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def ticket(self, src):
        return {"map": "m/p", "num": 7, "type": "task", "paths": [], "checks_from": src,
                "checks": ["echo 'No Pipeline instance found for project: {}' >&2; exit 75".format(self.tree)]}

    def test_worktree_fails_and_names_source(self):
        for src, words in (("ticket", "ticket's own"), ("map", "map's"), ("repo", ".sb/checks")):
            ok, why, _ = sbqueue.verdict(self.ticket(src), self.tree, self.base)
            self.assertIs(ok, False)
            self.assertIn("set up wrong", why)
            self.assertIn("echo 'No Pipeline", why)
            self.assertIn(words, why)

    def test_main_folder_still_rechecks(self):
        out = sbqueue._run_checks(["echo EDITOR_NOT_RUNNING >&2; exit 75"], self.main, subprocess.run)
        self.assertTrue(out.startswith(sbqueue.NOT_RUN))


if __name__ == "__main__":
    unittest.main()
