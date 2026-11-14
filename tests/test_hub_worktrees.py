"""Tickets of one repo side by side: a repo with `git config sb.parallel N` runs up to N tickets whose paths do not
overlap, each in its own git worktree on its own branch; a passed ticket is rebased onto the checkout's branch,
checked there, and fast-forwarded into the checkout. Same harness as test_hub_runner: Supervisor.tick() by hand,
a temp vault, temp repos and tests/fake_worker.py for `claude -p`."""
import os
import re
import time
import unittest
from pathlib import Path

from test_hub_runner import TEMPLATES, RunnerCase, git
from sbhub import Hub, Supervisor


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


class WorktreeTest(RunnerCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/"), ("C", "one/sub/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "3")
        with self.hub._lock:  # a third account, so the agents' own limit never decides these tests
            self.hub._data["installed"]["third"] = {"kind": "claude", "dir": str(self.root / ".claude-third"),
                                                    "model": None, "limited_until": None}

    def cwd_of(self, key):
        """The folder the fake worker ran in, from its log, once it printed it."""
        def read():
            log = self.items().get(key, {}).get("log")
            text = Path(log).read_text(encoding="utf-8") if log and Path(log).exists() else ""
            m = re.search(r"^cwd: (.+)$", text, re.M)
            return m and m.group(1)
        return self.until(read)

    def trees(self):
        out = git(self.repo, "worktree", "list", "--porcelain")
        return [l[len("worktree "):] for l in out.splitlines() if l.startswith("worktree ")]

    def spread(self):
        """Each ticket on its own account."""
        self.hub.queue_item_agent("repo/one#2", "spare")
        self.hub.queue_item_agent("repo/one#3", "third")

    def test_tickets_with_separate_paths_run_at_once_each_in_its_own_worktree(self):
        self.mode = "hang"
        self.tick_all()
        self.spread()
        self.hub.queue_pause(False)
        self.sup.tick()
        self.sup.tick()
        self.assertEqual([self.state_of("repo/one#{}".format(n)) for n in (1, 2, 3)],
                         ["running", "running", "queued"])  # C's one/sub/ lies under A's one/: it waits
        one, two = self.cwd_of("repo/one#1"), self.cwd_of("repo/one#2")
        self.assertEqual(len({one, two, str(self.repo)}), 3)
        self.assertEqual(sorted(self.trees()[1:]), sorted([one, two]))
        self.assertTrue(str(one).startswith(str(self.root / "hub")))
        items = self.items()
        self.assertEqual(git(Path(one), "rev-parse", "--abbrev-ref", "HEAD"), items["repo/one#1"]["branch"])
        self.assertIn(one, self.launched[0]["brief"])  # the brief names the worktree it works in
        self.assertIn(items["repo/one#1"]["branch"], self.launched[0]["brief"])

    def test_finished_worktree_tickets_land_on_the_checkout_and_their_worktrees_go(self):
        self.tick_all()
        self.spread()
        self.hub.queue_pause(False)
        self.until(lambda: all(self.state_of("repo/one#{}".format(n)) == "done" for n in (1, 2, 3)))
        log = git(self.repo, "log", "--format=%B")
        for n in (1, 2, 3):
            self.assertIn("Ticket: repo/one/{:03d}".format(n), log)
            sha = self.items()["repo/one#{}".format(n)]["commit"]
            git(self.repo, "merge-base", "--is-ancestor", sha, "HEAD")  # its recorded commit is on the branch
        for f in ("one/done.txt", "two/done.txt", "one/sub/done.txt"):
            self.assertTrue((self.repo / f).exists(), f)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(self.trees(), [str(self.repo)])
        self.assertEqual(git(self.repo, "branch", "--list", "sb/*"), "")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(self.open_tickets(), {})

    def test_a_ticket_whose_commit_conflicts_with_the_checkout_fails_and_keeps_its_branch(self):
        self.modes = {"repo/one#1": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "0.5"
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        self.cwd_of("repo/one#1")
        (self.repo / "one").mkdir(exist_ok=True)
        (self.repo / "one" / "done.txt").write_text("the owner's own line\n")
        git(self.repo, "add", "one/done.txt")
        git(self.repo, "commit", "-q", "-m", "owner")
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        item = self.items()["repo/one#1"]
        self.assertIn("could not land", item["note"])
        self.assertIn(item["branch"], item["note"])
        self.assertIn(item["branch"], git(self.repo, "branch", "--list", "sb/*"))
        self.assertEqual((self.repo / "one" / "done.txt").read_text(), "the owner's own line\n")
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertEqual(git(Path(item["tree"]), "status", "--porcelain"), "")  # no rebase left half done

    def test_a_worktree_worker_that_outlived_its_hub_is_judged_and_landed_by_the_next_one(self):
        self.modes = {"repo/one#1": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "1.5"
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        tree = self.cwd_of("repo/one#1")
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)  # the hub died; a new one starts
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        end = time.time() + 10
        while time.time() < end and hub.state()["queue"]["items"][0]["state"] in ("running", "review"):
            sup.tick()
            time.sleep(0.05)
        item = hub.state()["queue"]["items"][0]
        self.assertEqual((item["key"], item["state"]), ("repo/one#1", "done"))
        self.assertIn("Ticket: repo/one/001", git(self.repo, "log", "-1", "--format=%B"))
        self.assertNotIn(tree, self.trees())


    def test_a_worker_lost_with_its_hub_goes_on_in_the_same_worktree_with_its_work_kept(self):
        import signal
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        tree = Path(self.cwd_of("repo/one#1"))
        pid, child = self.pids()
        os.killpg(pid, signal.SIGKILL)  # the old hub ended its workers as it stopped
        end = time.time() + 5
        while time.time() < end and self.sup.procs["repo/one#1"]["p"].poll() is None:
            time.sleep(0.02)
        (tree / "one").mkdir(exist_ok=True)
        (tree / "one" / "half.txt").write_text("work the lost worker had not committed\n")
        self.sup.procs.clear()  # this hub is gone: the next one finds only what it saved
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        sup.tick()  # requeued and started again in the same pass
        item = hub.state()["queue"]["items"][0]
        self.assertEqual((item["state"], item["resume"]["why"]), ("running", "when the hub stopped"))
        self.assertEqual(self.launched[-1]["key"], "repo/one#1")
        self.assertIn("An earlier try", self.launched[-1]["brief"])
        self.assertTrue((tree / "one" / "half.txt").exists())  # the same worktree, not a fresh one


class ProjectRootTest(unittest.TestCase):
    """A session or worker that reports from a subfolder or a worktree shows under its repo's checkout, so the
    board has one project per repo, not one per folder an agent stood in."""

    def test_a_subfolder_and_a_worktree_report_as_their_checkout_and_a_plain_folder_as_itself(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "init")
        (repo / "pkg" / "src").mkdir(parents=True)
        tree = root / "trees" / "t-001"
        git(repo, "worktree", "add", "-q", "-b", "sb/t-001", str(tree))
        (tree / "pkg").mkdir()
        plain = root / "plain"
        plain.mkdir()
        hub = Hub(root / "hub")
        for agent, where in (("a", repo / "pkg" / "src"), ("b", tree / "pkg"), ("c", plain)):
            hub.report({"agent": agent, "state": "working", "project": str(where)})
        agents = hub.state()["agents"]
        self.assertEqual([agents[k]["project"] for k in "abc"], [str(repo), str(repo), str(plain)])


if __name__ == "__main__":
    unittest.main()
