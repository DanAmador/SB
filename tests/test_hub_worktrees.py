"""Tickets of one repo side by side: a repo with `git config sb.parallel N` runs up to N tickets whose paths do not
overlap, each in its own git worktree on its own branch; a passed ticket is rebased onto the checkout's branch,
checked there, and fast-forwarded into the checkout. Same harness as test_hub_runner: Supervisor.tick() by hand,
a temp vault, temp repos and tests/fake_worker.py for `claude -p`."""
import json
import os
import re
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_hub_runner import TEMPLATES, RunnerCase, git, state_fixture
import sbhub
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
        patcher = mock.patch.object(sbhub, "INDEX_LOCK_WAIT", 0.3)  # a stale index.lock fails a landing at once
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_a_run_a_stale_git_lock_kept_from_landing_lands_again_without_its_worker(self):
        self.modes = {"repo/one#2": "slow"}  # keeps the night going a while, so the failed run stays on the line
        os.environ["FAKE_WORKER_SLEEP"] = "6"
        self.hub.queue_set(["repo/one#1", "repo/one#2"], self.hub.state()["queue"]["version"])
        self.hub.queue_item_agent("repo/one#2", "spare")
        lock = self.repo / ".git" / "index.lock"
        lock.write_text("")  # a git command that crashed long ago left its lock
        self.hub.queue_pause(False)
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        item = self.items()["repo/one#1"]
        self.assertTrue(item["note"].startswith("could not land"))
        self.assertTrue(Path(item["tree"]).is_dir())
        workers = len(self.launched)
        with self.assertRaisesRegex(ValueError, "not waiting"):
            self.hub.recheck_now("repo/one#2")  # running, not failed
        lock.unlink()
        self.hub.ticket_action("recheck", "repo/one#1")
        self.assertEqual(self.state_of("repo/one#1"), "recheck")
        self.until(lambda: self.state_of("repo/one#1") in ("done", "skipped", "failed"), timeout=60)
        self.assertEqual(self.state_of("repo/one#1"), "done")  # reviewed and closed: the hub held its ticket again
        self.assertNotIn(1, self.open_tickets())
        self.assertEqual(len(self.launched), workers)  # the worker did not run again; only the review did
        git(self.repo, "merge-base", "--is-ancestor", self.items()["repo/one#1"]["commit"], "HEAD")
        self.assertNotIn(item["tree"], self.trees())

    def move_to_two(self, num):
        """The real `sbmap move` of a ticket to a second map of the same repo."""
        if not (self.vault / "wayfinder/repo/two").exists():
            self.sb("init", "repo/two", "--title", "Two", "--why", "Why.", "--destination", "Somewhere.",
                    "--repo", str(self.repo))
            self.sb("mapset", "repo/two", "checks=true")
        self.sb("move", "repo/one", "{:03d}".format(num), "--to", "repo/two")

    def test_a_failed_run_whose_ticket_moved_to_another_map_lands_again_under_the_new_key(self):
        self.modes = {"repo/one#2": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "6"
        self.hub.queue_set(["repo/one#1", "repo/one#2"], self.hub.state()["queue"]["version"])
        self.hub.queue_item_agent("repo/one#2", "spare")
        lock = self.repo / ".git" / "index.lock"
        lock.write_text("")
        self.hub.queue_pause(False)
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        tree = self.items()["repo/one#1"]["tree"]
        lock.unlink()
        self.move_to_two(1)
        self.hub.ticket_action("recheck", "repo/one#1")  # the page still holds the old key
        keys = [i["key"] for i in self.hub.state()["queue"]["items"]]
        self.assertIn("repo/two#1", keys)
        self.assertNotIn("repo/one#1", keys)
        self.until(lambda: self.state_of("repo/two#1") in ("done", "skipped", "failed"), timeout=60)
        self.assertEqual(self.state_of("repo/two#1"), "done", self.items()["repo/two#1"]["note"])
        git(self.repo, "merge-base", "--is-ancestor", self.items()["repo/two#1"]["commit"], "HEAD")
        self.assertNotIn(tree, self.trees())

    def test_a_queued_ticket_that_moved_runs_under_the_new_map_and_a_restarted_hub_still_finds_it(self):
        self.mode = "hang"
        self.tick_all()
        self.move_to_two(1)
        self.hub.tickets(fresh=True)
        keys = [i["key"] for i in self.hub.state()["queue"]["items"]]
        self.assertIn("repo/two#1", keys)
        self.assertNotIn("repo/one#1", keys)
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)  # a restart reads the saved queue
        self.assertIn("repo/two#1", [i["key"] for i in hub.state()["queue"]["items"]])
        self.hub.queue_set(["repo/two#1"], self.hub.state()["queue"]["version"])
        self.hub.queue_pause(False)
        self.sup.tick()
        self.assertEqual(self.launched[0]["key"], "repo/two#1")
        self.assertEqual(self.state_of("repo/two#1"), "running")

    def test_a_worktree_worker_that_outlived_its_hub_is_judged_and_landed_by_the_next_one(self):
        self.modes = {"repo/one#1": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "1.5"
        self.hub.queue_set(["repo/one#1"], self.hub.state()["queue"]["version"])  # alone: its map's review follows it
        self.hub.queue_pause(False)
        self.sup.tick()
        tree = self.cwd_of("repo/one#1")
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)  # the hub died; a new one starts
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        end = time.time() + 10
        def one():  # judged: the night ended and the item is on its record
            return next((i for i in hub.state()["queue"]["items"] if i.get("night")), None) or hub.night(hub.nights()["nights"][0]["id"])["night"]["items"][0]
        while time.time() < end and one()["state"] in ("running", "landed", "review"):
            sup.tick()
            time.sleep(0.05)
        item = one()
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


# sk4te's real .sb/checks (2026-11-16), its compile line marked to run in the checkout after landing
SK4TE_CHECKS = """# sk4te's fast loop: sb runs these, one per line, for any ticket with no checks of its own or its map's.
after-landing: python3 .sb/checks-compile.py
"""

# stands in for sk4te's .sb/checks-compile.py (which asks the one open Unity): it notes where it ran, whether the
# ticket's work was there and who held the locks, then passes or fails as FAKE_COMPILE says (one word per run)
FAKE_COMPILE = """import json, os, subprocess, sys, time
log = os.environ["FAKE_COMPILE_LOG"]
runs = open(log).read().count("\\n") if os.path.exists(log) else 0
locks = json.load(open(os.environ["FAKE_COMPILE_STATE"])).get("locks", {})
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
with open(log, "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "work": os.path.exists("one/done.txt"), "head": head,
                        "locks": locks, "at": time.time()}) + "\\n")
modes = os.environ.get("FAKE_COMPILE", "pass").split(",")
if modes[min(runs, len(modes) - 1)] == "fail":
    print("Assets/One.cs(3,1): error CS1002: ; expected")
    sys.exit(1)
"""


class Crash(BaseException):
    """The hub process dying mid-landing (not an Exception, so nothing in the hub catches it)."""


class AfterLandingTest(RunnerCase):
    """A repo whose .sb/checks marks a line `after-landing: ` (sk4te's Unity compile): the hub lands the ticket under
    the repo's Unity lock, runs that line in the checkout with the work in, and backs the landing out with one
    revert commit when it fails."""
    MAPS = (("repo/one", "game", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "2")
        self.sb("mapset", "repo/one", "checks=")  # no map checks: the repo's .sb/checks decides, as in sk4te
        (self.repo / ".sb").mkdir()
        (self.repo / ".sb" / "checks").write_text(SK4TE_CHECKS)
        (self.repo / ".sb" / "checks-compile.py").write_text(FAKE_COMPILE)
        git(self.repo, "add", ".sb")
        git(self.repo, "commit", "-q", "-m", "checks")
        self.log = self.root / "compile.jsonl"
        os.environ.update(FAKE_COMPILE_LOG=str(self.log), FAKE_COMPILE_STATE=str(self.root / "hub" / "state.json"))
        patcher = mock.patch.multiple(sbhub, LAND_LOCK_POLL=0.05, LAND_LOCK_WAIT=30)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lock = "unity:" + self.repo.name

    def compiles(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_the_checks_come_from_the_repo_file_with_the_mark(self):
        row = next(t for t in self.hub.tickets(fresh=True) if t["num"] == 1)
        self.assertEqual(row["checks"], ["after-landing: python3 .sb/checks-compile.py"])  # through the real sbmap

    def test_a_failing_compile_after_landing_is_reverted_by_one_commit_and_the_ticket_tries_again(self):
        os.environ["FAKE_COMPILE"] = "fail,pass"
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        first, second = self.compiles()
        # the first compile ran in the checkout with the ticket's work in, under the hub's lock
        self.assertEqual(os.path.realpath(first["cwd"]), os.path.realpath(self.repo))
        self.assertTrue(first["work"])
        self.assertEqual(first["locks"][self.lock]["by"], "sb-hub landing repo/one#1")
        landed = first["head"]
        self.assertNotEqual(landed, before)
        git(self.repo, "merge-base", "--is-ancestor", landed, "HEAD")  # its commit is in main ...
        reverts = git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()
        self.assertEqual(len(reverts), 1)  # ... then backed out by one revert commit on top of it
        self.assertEqual(git(self.repo, "rev-parse", reverts[0] + "^"), landed)
        self.assertEqual(git(self.repo, "diff", before, reverts[0]), "")  # main's files as before the landing
        self.assertIn("error CS1002", git(self.repo, "log", "-1", "--format=%B", reverts[0]) + self.launched[1]["brief"])
        # queued again, its worker told why: its second try, on its own tier
        self.assertEqual(len(self.launched), 2)
        self.assertEqual(self.launched[1]["model"], "sonnet")
        self.assertIn("## This is try 2 of 5", self.launched[1]["brief"])
        self.assertIn("after landing, check failed: python3 .sb/checks-compile.py", self.launched[1]["brief"])
        self.assertIn("error CS1002", self.launched[1]["brief"])
        # the second try landed on a building main, carrying the first try's work again
        self.assertTrue(second["work"])
        self.assertEqual((self.repo / "one" / "done.txt").read_text().count("work for"), 2)
        self.assertEqual(self.hub.state()["locks"], {})

    def test_a_passing_compile_after_landing_leaves_it_landed_and_the_lock_released(self):
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        [ran] = self.compiles()
        self.assertEqual(os.path.realpath(ran["cwd"]), os.path.realpath(self.repo))
        self.assertTrue(ran["work"])
        self.assertIn(self.lock, ran["locks"])
        self.assertEqual(ran["head"], git(self.repo, "rev-parse", "HEAD"))
        self.assertNotEqual(ran["head"], before)
        self.assertEqual(git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD"), "")
        self.assertEqual(self.hub.state()["locks"], {})
        self.assertNotIn(1, self.open_tickets())

    def test_a_landing_waits_while_a_chat_session_holds_the_unity_lock(self):
        self.hub.report({"agent": "chat", "state": "working", "project": str(self.repo)})
        self.assertTrue(self.hub.lock(self.lock, "chat")["ok"])
        before = git(self.repo, "rev-parse", "HEAD")
        freed = []

        def unlock():
            freed.append(time.time())
            self.assertEqual(git(self.repo, "rev-parse", "HEAD"), before)  # nothing landed while it was held
            self.hub.unlock(self.lock, "chat")
        timer = threading.Timer(1.5, unlock)
        self.only(1)
        self.until(lambda: self.launched and self.state_of("repo/one#1") == "running")
        timer.start()
        self.addCleanup(timer.cancel)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        [ran] = self.compiles()
        self.assertTrue(freed)
        self.assertGreater(ran["at"], freed[0])  # it landed only after sb_unlock
        self.assertTrue(ran["work"])
        self.assertEqual(self.hub.state()["locks"], {})

    def test_a_hub_restart_while_a_landing_holds_the_lock_backs_it_out_and_lands_it_again(self):
        before = git(self.repo, "rev-parse", "HEAD")

        def die(*a, **k):
            raise Crash()
        self.only(1)
        with mock.patch.object(self.sup.runner, "after_landing", die):
            with self.assertRaises(Crash):
                self.until(lambda: False)
        # the hub died fast-forwarded and locked: the ticket's work is in main, unchecked
        landed = git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(landed, before)
        self.assertIn("landing", json.loads((self.root / "hub" / "state.json").read_text())["locks"][self.lock])
        state_fixture(self.hub.state(), self.root, "landing.json")  # the page must still read a hub mid-landing
        self.sup.procs.clear()  # this hub is gone: the next one finds only what it saved
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        workers = len(self.launched)
        end = time.time() + 60
        self.hub, self.sup = hub, sup  # the harness's items() and until() read and tick the new hub
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(len(self.launched), workers)  # landed again without running its worker
        self.assertEqual(hub.state()["locks"], {})
        [ran] = self.compiles()
        self.assertTrue(ran["work"])  # compiled with its work in, this time to the end
        [revert] = git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()
        self.assertEqual(git(self.repo, "rev-parse", revert + "^"), landed)
        self.assertEqual(git(self.repo, "diff", before, revert), "")
        self.assertEqual(ran["head"], git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual((self.repo / "one" / "done.txt").read_text().count("work for"), 1)


# stands in for sk4te's compile for the blame tests: one word of FAKE_COMPILE per run. `pass` passes (a stale
# Editor that saw nothing), `75` could not run, `broken` fails naming FAKE_COMPILE_BROKEN while that file is in the
# checkout, `sticky` names it and fails whatever is there. FAKE_COMPILE_LOCK makes it leave .git/index.lock behind as it ends (Unity or a chat's git in the
# checkout at that moment): removed after that many seconds, or kept with `keep`
BLAME_COMPILE = """import json, os, subprocess, sys, time
log = os.environ["FAKE_COMPILE_LOG"]
runs = open(log).read().count("\\n") if os.path.exists(log) else 0
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
with open(log, "a") as f:
    f.write(json.dumps({"head": head, "at": time.time()}) + "\\n")
modes = os.environ.get("FAKE_COMPILE", "pass").split(",")
mode = modes[min(runs, len(modes) - 1)]
lock = os.environ.get("FAKE_COMPILE_LOCK")
if lock and mode != "pass":
    open(".git/index.lock", "w").close()
    if lock != "keep":
        subprocess.Popen(["sh", "-c", "sleep {}; rm -f .git/index.lock".format(lock)])
if mode == "75":
    print("the Editor did not answer")
    sys.exit(75)
broken = os.environ.get("FAKE_COMPILE_BROKEN", "")
if mode == "sticky" or mode == "broken" and broken and os.path.exists(broken):
    print("compile errors:")
    print(broken + "(49,92): error CS0117: 'Lash' does not contain a definition for 'HitHeldSeconds'")
    sys.exit(1)
"""


class BlameTest(RunnerCase):
    """A compile after landing that fails in files the landing did not touch blames the earlier landing that last
    touched them (2026-11-16: 1223 landed a test that did not compile, and 1231 and 1221 were backed out for it)."""
    MAPS = (("repo/one", "game", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "2")  # worktrees: a ticket lands into the checkout
        self.sb("mapset", "repo/one", "checks=")
        (self.repo / ".sb").mkdir()
        (self.repo / ".sb" / "checks").write_text(SK4TE_CHECKS)
        (self.repo / ".sb" / "checks-compile.py").write_text(BLAME_COMPILE)
        git(self.repo, "add", ".sb")
        git(self.repo, "commit", "-q", "-m", "checks")
        self.log = self.root / "compile.jsonl"
        os.environ.update(FAKE_COMPILE_LOG=str(self.log), FAKE_COMPILE_BROKEN="one/done.txt")
        for k in ("FAKE_COMPILE", "FAKE_COMPILE_LOCK"):
            self.addCleanup(os.environ.pop, k, None)
        patcher = mock.patch.multiple(sbhub, LAND_LOCK_POLL=0.05, LAND_LOCK_WAIT=30)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: (self.repo / ".git" / "index.lock").unlink(missing_ok=True))
        self.lock = "unity:" + self.repo.name

    def reverts(self):
        return git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()

    def build(self):
        return (self.hub.state()["queue"].get("builds") or {}).get(str(self.repo), {})

    def test_a_ticket_that_lands_on_a_broken_build_backs_out_the_one_that_broke_it_and_stays(self):
        os.environ["FAKE_COMPILE"] = "pass,broken"  # A's own compile passes on a stale Editor; B's sees A's error
        self.sb("block", "repo/one", "2", "1")  # B starts once A landed, as 1231 came after 1223
        self.only(1, 2)
        a = self.until(lambda: (self.items().get("repo/one#1") or {}).get("fails") and
                       self.state_of("repo/one#2") in ("landed", "done") and self.items()["repo/one#1"])
        [revert] = self.reverts()
        mark = git(self.repo, "log", "-1", "--format=%B", revert)
        self.assertIn("error CS0117", mark)
        self.assertIn("once repo/one#2 landed on top", mark)
        landed_a = re.search(r"Undoes-landing: (\w+)\.\.(\w+)", mark).group(2)
        self.assertIn("Ticket: repo/one/001", git(self.repo, "log", "-1", "--format=%B", landed_a))
        # B stays landed and the build is green on top of A's back-out
        self.assertTrue((self.repo / "two" / "done.txt").exists())
        self.assertFalse((self.repo / "one" / "done.txt").exists())
        self.assertEqual(self.build().get("green"), git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(len(self.compiles()), 3)  # A's, B's, and B's again once A was out
        # A goes back to the front, its work replayed on its branch on top of the revert, its worker told why
        self.assertIn(a["state"], ("queued", "running"))
        self.assertIn("the hub backed your landing out", a["retry"])
        self.assertIn("one/done.txt(49,92): error CS0117", a["retry"])
        self.assertEqual(a["first_base"], revert)
        self.assertIn("work for repo/one/001", (Path(a["tree"]) / "one" / "done.txt").read_text())
        self.assertEqual(git(a["tree"], "merge-base", "--is-ancestor", revert, "HEAD"), "")
        self.assertEqual(self.hub.state()["locks"], {})

    def test_a_blame_that_does_not_mend_the_build_is_undone_and_the_new_landing_is_backed_out(self):
        os.environ["FAKE_COMPILE"] = "pass,sticky"  # the error stays whatever is backed out: A was not the cause
        self.sb("block", "repo/one", "2", "1")
        self.only(1, 2)
        b = self.until(lambda: (self.items().get("repo/one#2") or {}).get("fails") and self.items()["repo/one#2"])
        subjects = git(self.repo, "log", "--format=%s", "HEAD").splitlines()[:3]
        self.assertTrue(subjects[0].startswith("revert: back out feat: work"))  # B, backed out last
        self.assertTrue(subjects[1].startswith("revert: back out revert:"))  # A's back-out, undone
        self.assertTrue(subjects[2].startswith("revert: back out feat: work"))  # A's back-out
        self.assertTrue((self.repo / "one" / "done.txt").exists())  # A's work stays landed
        self.assertFalse((self.repo / "two" / "done.txt").exists())
        self.assertIn("after landing, check failed", b["retry"])
        self.assertEqual(self.items()["repo/one#1"].get("fails"), None)  # A was not queued again

    def test_a_ticket_whose_own_files_break_is_backed_out_itself_and_never_the_one_before(self):
        os.environ["FAKE_COMPILE"] = "broken"
        self.only(1)
        self.until(lambda: (self.items().get("repo/one#1") or {}).get("fails"))
        [revert] = self.reverts()
        self.assertIn("repo/one/001", git(self.repo, "log", "-1", "--format=%B",
                                          re.search(r"\.\.(\w+)", git(self.repo, "log", "-1", "--format=%B",
                                                                      revert)).group(1)))
        self.assertEqual(self.build()["errors_by"], "repo/one#1")
        self.assertFalse(self.build().get("broken"))

    def test_a_back_out_waits_for_a_git_lock_someone_holds_for_a_moment(self):
        os.environ.update(FAKE_COMPILE="broken,pass", FAKE_COMPILE_LOCK="1")
        self.only(1)
        self.until(lambda: (self.items().get("repo/one#1") or {}).get("fails"))
        self.assertEqual(len(self.reverts()), 1)  # the revert waited for the lock instead of failing
        self.assertFalse(self.build().get("broken"))
        self.assertEqual(self.hub.state()["locks"], {})

    def test_a_landing_that_cannot_be_backed_out_keeps_the_lock_so_nothing_lands_on_the_broken_build(self):
        os.environ.update(FAKE_COMPILE="broken", FAKE_COMPILE_LOCK="keep")
        with mock.patch.multiple(sbhub, INDEX_LOCK_WAIT=0.3, LAND_LOCK_WAIT=0.2):
            self.only(1)
            a = self.until(lambda: self.state_of("repo/one#1") == "failed" and self.items()["repo/one#1"])
            # its work is still in the checkout: it waits for the owner instead of landing again on top
            self.assertIn("could NOT be backed out", a["note"])
            self.assertIn("lock stays held", a["note"])
            self.assertEqual(len(a["fails"]), 1)
            self.assertEqual(self.reverts(), [])
            self.assertEqual(self.hub.state()["locks"][self.lock]["by"], "sb-hub landing repo/one#1")
            build = self.build()
            self.assertTrue(build["broken"])
            self.assertEqual(build["errors_by"], "repo/one#1")
            head = git(self.repo, "rev-parse", "HEAD")
            self.only(2)
            # the next ticket's work waits on its branch: it does not land on the broken build
            b = self.until(lambda: "could not land yet" in ((self.items().get("repo/one#2") or {}).get("note") or "")
                           and self.items()["repo/one#2"])
            self.assertIn(self.lock, b["note"])
            self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)

    def test_a_check_that_could_not_run_says_what_was_last_known_broken(self):
        os.environ["FAKE_COMPILE"] = "broken,75"
        self.only(1)
        a = self.until(lambda: self.state_of("repo/one#1") == "recheck" and self.items()["repo/one#1"])
        self.assertIn("could not run", a["note"])
        self.assertIn("not judged; the last compile errors the hub saw were in done.txt (after repo/one#1",
                      a["note"].splitlines()[0])

    def compiles(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []


class LandingOfTest(unittest.TestCase):
    """Real data: sk4te's landings of 2026-11-16 18:40-18:48, their messages as the workers wrote them (1223's
    Ticket line sits above a Co-Authored-By paragraph, so it is not a git trailer)."""

    def setUp(self):
        import tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.repo = Path(d.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        self.base = self.commit("Assets/Scripts/Lash.cs", "base")
        self.market = self.commit("Assets/Scripts/Market.cs", "fix(market): Hot Potato becomes Switchblade\n\n"
                                  "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\n\n"
                                  "Ticket: sk4te/party-playtest/1222")
        self.held = self.commit("Assets/Tests/PlayMode/HeldCostsEnergyTests.cs", "test(energy): a Play probe reads a "
                                "held lash draining per second\n\nTicket: sk4te/party-playtest/1223\n\n"
                                "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        self.cards = self.commit("Assets/Tests/EditMode/SocketCountTests.cs", "test(cards): a count per socket\n\n"
                                 "Ticket: sk4te/party-playtest/1231\n\n"
                                 "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        self.files = sbhub.compile_errors("compile errors:\nAssets/Tests/PlayMode/HeldCostsEnergyTests.cs(49,92): "
                                          "error CS0117: 'Lash' does not contain a definition for 'HitHeldSeconds'")[0]

    def commit(self, path, msg):
        f = self.repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f.read_text() + "x\n" if f.exists() else "x\n")
        git(self.repo, "add", path)
        git(self.repo, "commit", "-q", "-m", msg)
        return git(self.repo, "rev-parse", "HEAD")

    def test_the_compile_errors_name_their_files_once(self):
        self.assertEqual(self.files, ["Assets/Tests/PlayMode/HeldCostsEnergyTests.cs"])

    def test_the_ticket_landing_on_top_blames_1223_not_itself(self):
        got = sbhub.landing_of(self.repo, self.files, self.cards + "^")
        self.assertEqual(got, {"key": "sk4te/party-playtest#1223", "ticket": "sk4te/party-playtest/1223",
                               "before": self.market, "sha": self.held})

    def test_a_landing_before_tonight_is_never_blamed(self):
        self.assertIsNone(sbhub.landing_of(self.repo, self.files, self.cards, since=self.held))

    def test_a_fix_with_no_ticket_is_never_blamed(self):
        fixed = self.commit("Assets/Tests/PlayMode/HeldCostsEnergyTests.cs", "fix(test): reads it from LashNode")
        self.assertIsNone(sbhub.landing_of(self.repo, self.files, fixed))

    def test_a_landing_already_backed_out_is_never_blamed_again(self):
        err, _ = sbhub.revert_landing(self.repo, self.market, self.held, "it broke the build")
        self.assertIsNone(err)
        self.assertIsNone(sbhub.landing_of(self.repo, self.files, self.cards))


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
