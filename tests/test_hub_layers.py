"""Stack layers (ticket 194): a map's `stack` names git branches bottom to top, each merged into the next, and a
ticket's `layer` is the branch it is built on. The hub cuts the ticket's worktree from its layer's tip, lands it by
moving only the layer branch (the main folder never changes), merges the layer up into every branch above it with
merge commits, runs tickets of one layer side by side and lands them one at a time, and runs lower layers first.
Same harness as test_hub_worktrees: Supervisor.tick() by hand, a temp vault, temp repos, tests/fake_worker.py."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_hub_runner import TEMPLATES, RunnerCase, git, go, make_repo
import sbhub
import sbqueue

STACK = ("L1", "L2", "L3")


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


def make_stack(repo):
    """L1 from main, L2 from L1, L3 from L2, a commit of its own on each; the main folder stays on main."""
    prev = "main"
    for b in STACK:
        git(repo, "branch", b, prev)
        tree = repo.parent / "own-{}".format(b)
        git(repo, "worktree", "add", "-q", str(tree), b)
        (tree / "{}.txt".format(b)).write_text(b + "\n")
        git(tree, "add", ".")
        git(tree, "commit", "-q", "-m", "own " + b)
        git(repo, "worktree", "remove", str(tree))
        prev = b


def tip(repo, b):
    return git(repo, "rev-parse", "refs/heads/" + b)


def has(repo, b, sha):
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, "refs/heads/" + b]).returncode == 0


def parents(repo, sha):
    return git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]


class LayerTest(RunnerCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/"), ("C", "three/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        make_stack(self.repo)
        (self.repo / "owner.txt").write_text("the owner's unsaved work\n")  # the main folder is never touched
        self.main_head = git(self.repo, "rev-parse", "HEAD")
        self.sb("mapset", "repo/one", "stack=" + ",".join(STACK))
        patcher = mock.patch.object(sbhub, "INDEX_LOCK_WAIT", 0.3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def layer(self, num, branch):
        self.sb("set", "repo/one", "{:03d}".format(num), "layer=" + branch, "--no-sync")

    def checkout(self, branch):
        """A worktree of the owner's with `branch` checked out, as the monorepo's stack has."""
        tree = self.root / "wt-{}".format(branch)
        git(self.repo, "worktree", "add", "-q", str(tree), branch)
        return tree

    def main_untouched(self):
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.main_head)
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "?? owner.txt")
        self.assertFalse((self.repo / "one").exists())

    def test_sbmap_keeps_the_layer_and_the_stack_and_refuses_a_layer_off_the_stack(self):
        self.layer(1, "L2")
        row = self.open_tickets()[1]
        self.assertEqual((row["layer"], row["stack"]), ("L2", list(STACK)))
        self.assertIsNone(self.open_tickets()[2]["layer"])
        r = self.sb("set", "repo/one", "002", "layer=nope", "--no-sync", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not in the map's stack", r.stderr)
        self.layer(1, "")  # empty: no layer
        self.assertIsNone(self.open_tickets()[1]["layer"])

    def test_a_layer_ticket_starts_in_its_own_worktree_from_its_layers_tip(self):
        self.layer(1, "L2")
        self.mode = "hang"
        self.only(1)
        self.sup.tick()
        self.assertEqual(self.state_of("repo/one#1"), "running")
        item = self.items()["repo/one#1"]
        self.assertTrue(item["tree"] and Path(item["tree"]).is_dir())
        self.assertEqual(item["layer"], "L2")
        self.assertEqual(git(Path(item["tree"]), "rev-parse", "HEAD"), tip(self.repo, "L2"))
        self.assertNotEqual(tip(self.repo, "L2"), self.main_head)
        self.assertIn("layer `L2`", self.launched[0]["brief"])
        self.main_untouched()

    def test_landing_moves_only_its_layer_and_merges_it_up_the_stack(self):
        own1, own3 = self.checkout("L1"), self.checkout("L3")  # L2 is checked out nowhere: its ref moves alone
        before = {b: tip(self.repo, b) for b in STACK}
        self.layer(1, "L1")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item = self.items()["repo/one#1"]
        sha = item["commit"]
        self.assertEqual(tip(self.repo, "L1"), sha)  # fast-forwarded in its worktree
        self.assertIn("landed on the stack layer `L1`", self.reviewed[-1]["brief"])  # the review reads the layer
        self.assertIn("show L1:<path>", self.reviewed[-1]["brief"])
        self.assertEqual(parents(self.repo, sha), [before["L1"]])
        self.assertEqual((own1 / "one" / "done.txt").read_text(), "work for repo/one/001\n")
        for b in ("L2", "L3"):
            self.assertTrue(has(self.repo, b, sha), b)
            self.assertEqual(parents(self.repo, tip(self.repo, b))[0], before[b])  # one merge commit on top
            self.assertEqual(len(parents(self.repo, tip(self.repo, b))), 2)
        self.assertEqual(git(own3, "status", "--porcelain"), "")
        self.assertTrue((own3 / "one" / "done.txt").exists())  # merged in the worktree that has L3
        self.assertFalse(Path(item["tree"]).exists())
        self.assertEqual(git(self.repo, "branch", "--list", "sb/*"), "")
        self.main_untouched()

    def test_a_conflict_up_the_stack_fails_the_ticket_naming_the_branch(self):
        own3 = self.checkout("L3")
        (own3 / "one").mkdir()
        (own3 / "one" / "done.txt").write_text("L3's own line\n")
        git(own3, "add", ".")
        git(own3, "commit", "-q", "-m", "L3 writes one/done.txt")
        l3 = tip(self.repo, "L3")
        self.layer(1, "L1")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        item = self.items()["repo/one#1"]
        self.assertIn("merging L2 into L3 conflicts in one/done.txt", item["note"])
        self.assertEqual(len(self.launched), 1)  # its work is on its layer: never tried again
        self.assertTrue(has(self.repo, "L1", item["commit"]) and has(self.repo, "L2", item["commit"]))
        self.assertEqual(tip(self.repo, "L3"), l3)
        self.assertEqual(git(own3, "status", "--porcelain"), "")  # the merge was aborted
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.main_untouched()

    def test_tickets_of_one_layer_run_at_once_and_land_one_after_the_other(self):
        self.layer(1, "L1")
        self.layer(2, "L1")
        self.modes = {"repo/one#1": "slow", "repo/one#2": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "1.5"
        self.hub.queue_set(["repo/one#1", "repo/one#2"], self.hub.state()["queue"]["version"])
        self.hub.queue_item_agent("repo/one#2", "spare")
        go(self.hub)
        self.sup.tick()
        self.assertEqual([self.state_of("repo/one#1"), self.state_of("repo/one#2")], ["running", "running"])
        trees = {self.items()["repo/one#{}".format(n)]["tree"] for n in (1, 2)}
        self.assertEqual(len(trees), 2)
        self.until(lambda: all(self.state_of("repo/one#{}".format(n)) == "done" for n in (1, 2)))
        a, b = (self.items()["repo/one#{}".format(n)]["commit"] for n in (1, 2))
        self.assertEqual(git(self.repo, "rev-list", "--count", "{}..L1".format(self.main_head)), "3")  # own, a, b
        later = tip(self.repo, "L1")
        self.assertIn(later, (a, b))
        earlier = b if later == a else a
        self.assertEqual(parents(self.repo, later), [earlier])  # the second rebased onto the first: a line
        for br in ("L2", "L3"):
            self.assertTrue(has(self.repo, br, a) and has(self.repo, br, b), br)
        self.main_untouched()

    def test_a_lower_layer_runs_before_a_higher_one(self):
        self.layer(1, "L2")
        self.layer(2, "L1")
        self.modes = {"repo/one#2": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "1"
        self.hub.queue_set(["repo/one#1", "repo/one#2"], self.hub.state()["queue"]["version"])
        self.hub.queue_item_agent("repo/one#1", "spare")
        go(self.hub)
        self.sup.tick()
        self.assertEqual([self.state_of("repo/one#1"), self.state_of("repo/one#2")], ["queued", "running"])
        self.assertIn("lower layer L1", self.items()["repo/one#1"]["waits"]["text"])
        self.until(lambda: all(self.state_of("repo/one#{}".format(n)) == "done" for n in (1, 2)))
        low, high = (self.items()["repo/one#{}".format(n)]["commit"] for n in (2, 1))
        self.assertTrue(subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor", low, high]).returncode
                        == 0)  # the higher one was built on the lower one's work, merged up into L2
        self.assertTrue(has(self.repo, "L3", high) and not has(self.repo, "L1", high))
        self.main_untouched()


class MergeUpTest(unittest.TestCase):
    """merge_up and move_layer on a bare stack, no hub."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.repo = Path(d.name).resolve() / "r"
        make_repo(self.repo)
        make_stack(self.repo)

    def test_a_conflict_on_a_branch_checked_out_nowhere_names_it_and_moves_nothing(self):
        tree = self.repo.parent / "x"
        git(self.repo, "worktree", "add", "-q", str(tree), "L2")
        (tree / "L1.txt").write_text("L2's line\n")
        git(tree, "commit", "-q", "-am", "L2 edits L1.txt")
        git(self.repo, "worktree", "remove", str(tree))
        git(self.repo, "worktree", "add", "-q", str(tree), "L1")
        (tree / "L1.txt").write_text("L1's new line\n")
        git(tree, "commit", "-q", "-am", "L1 edits L1.txt")
        l2 = tip(self.repo, "L2")
        merged, why = sbhub.merge_up(str(self.repo), list(STACK))
        self.assertEqual(merged, [])
        self.assertEqual(why, "merging L1 into L2 conflicts in L1.txt")
        self.assertEqual(tip(self.repo, "L2"), l2)

    def test_a_layer_checked_out_in_the_main_folder_is_never_moved(self):
        git(self.repo, "checkout", "-q", "L1")
        old = tip(self.repo, "L1")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "x")
        new = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "reset", "-q", "--hard", old)
        why = sbhub.move_layer(str(self.repo), "L1", old, new)
        self.assertIn("checked out in the main folder", why)
        self.assertEqual(tip(self.repo, "L1"), old)

    def test_a_layer_that_moved_since_the_rebase_is_moved_again(self):
        old = tip(self.repo, "L1")
        self.assertEqual(sbhub.move_layer(str(self.repo), "L1", "0" * 40, old), sbhub.MOVED)

    def test_the_lower_layer_rule(self):
        t = {"map": "m", "num": 5, "repo": "/r", "layer": "L3", "stack": list(STACK)}
        items = [{"key": "m#1", "kind": "ticket", "state": "landed", "layer": "L1"},
                 {"key": "m#2", "kind": "ticket", "state": "queued"}]
        by = {"m#2": {"repo": "/r", "layer": "L2"}, "m#1": {"repo": "/r"}}
        self.assertEqual(sbqueue.lower_layer_first(t, items, by), ("m#2", "L2"))
        items[1]["state"] = "review"
        self.assertIsNone(sbqueue.lower_layer_first(t, items, by))
        self.assertEqual(sbqueue.layers_above({"layer": "L1", "stack": list(STACK)}), ["L2", "L3"])
        self.assertIn("not in its map's stack", sbqueue.layer_problem({"layer": "L9", "stack": list(STACK)}))


class ReadyTreeTest(unittest.TestCase):
    """A hub worktree gets the main folder's node_modules linked in and the repo's husky hooks made there."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.repo = Path(d.name).resolve() / "r"
        make_repo(self.repo)
        (self.repo / ".gitignore").write_text("node_modules/\n")  # a trailing slash: a link is not ignored by it
        (self.repo / ".husky").mkdir()
        (self.repo / ".husky" / "pre-commit").write_text("exit 0\n")
        (self.repo / "apps" / "web").mkdir(parents=True)
        (self.repo / "apps" / "web" / "x.txt").write_text("x\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "app")
        for nm in (self.repo / "node_modules", self.repo / "apps" / "web" / "node_modules"):
            (nm / "pkg" / "node_modules" / "deep").mkdir(parents=True)
            (nm / "pkg" / "index.js").write_text("ok\n")
        husky = self.repo / "node_modules" / ".bin" / "husky"
        husky.parent.mkdir()
        husky.write_text("#!/bin/sh\nmkdir -p .husky/_ && echo \"*\" > .husky/_/.gitignore && pwd > .husky/_/made-in\n")
        husky.chmod(0o755)

    def test_a_new_worktree_links_node_modules_runs_husky_and_drops_cleanly(self):
        tree = self.repo.parent / "home" / "t1"
        self.assertIsNone(sbhub.make_tree(str(self.repo), str(tree), "sb/t1", "HEAD"))
        for rel in ("node_modules", "apps/web/node_modules"):
            self.assertTrue((tree / rel).is_symlink(), rel)
            self.assertEqual(os.path.realpath(tree / rel), str(self.repo / rel))
        self.assertFalse((tree / "node_modules" / "pkg" / "node_modules").is_symlink())  # none inside another
        self.assertEqual((tree / ".husky" / "_" / "made-in").read_text().strip(), str(tree))
        self.assertEqual(git(tree, "status", "--porcelain"), "")  # the links are never unsaved work
        self.assertEqual(sbhub.unsaved(str(tree)), [])
        sbhub.drop_tree(str(self.repo), str(tree), "sb/t1")
        self.assertFalse(tree.exists())
        self.assertEqual((self.repo / "node_modules" / "pkg" / "index.js").read_text(), "ok\n")
        self.assertEqual((self.repo / "apps" / "web" / "node_modules" / "pkg" / "index.js").read_text(), "ok\n")

    def test_sb_node_modules_names_another_checkout_to_link_from(self):
        other = self.repo.parent / "other"
        (other / "node_modules" / "theirs").mkdir(parents=True)
        (other / "apps" / "web" / "node_modules").mkdir(parents=True)
        git(self.repo, "config", "sb.nodeModules", str(other / "node_modules"))  # its node_modules or the checkout
        tree = self.repo.parent / "home" / "t3"
        self.assertIsNone(sbhub.make_tree(str(self.repo), str(tree), "sb/t3", "HEAD"))
        self.assertEqual(os.path.realpath(tree / "node_modules"), str(other / "node_modules"))
        self.assertEqual(os.path.realpath(tree / "apps" / "web" / "node_modules"), str(other / "apps" / "web" / "node_modules"))
        self.assertFalse((tree / ".husky" / "_").exists())  # the other checkout has no husky: none ran
        sbhub.drop_tree(str(self.repo), str(tree), "sb/t3")
        git(self.repo, "config", "sb.nodeModules", str(self.repo.parent / "missing"))
        self.assertEqual(sbhub.modules_source(str(self.repo)), str(self.repo))  # a folder without packages: main's

    def test_a_repo_without_husky_or_packages_gets_a_plain_worktree(self):
        bare = self.repo.parent / "plain"
        make_repo(bare)
        tree = self.repo.parent / "home" / "t2"
        self.assertIsNone(sbhub.make_tree(str(bare), str(tree), "sb/t2", "HEAD"))
        self.assertFalse(os.path.lexists(tree / "node_modules"))
        self.assertEqual(git(tree, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
