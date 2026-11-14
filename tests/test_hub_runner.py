"""The hub runs the queue: Supervisor.tick() by hand, a real temp vault through sbmap, temp git repos,
and tests/fake_worker.py standing in for `claude -p` (a `claude` on PATH that runs it). Never a model,
never port 8765, ~/.sb-hub, the owner's vault or the real ~/.claude*."""
import http.server
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from helpers import SBMAP, SCRIPT, free_port  # noqa: E402
import sbhub  # noqa: E402
import sbqueue  # noqa: E402
from sbhub import Hub, Supervisor  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_worker.py"
START = datetime(2026, 11, 13, 1, 0).timestamp()  # 01:00 local: the limit's 4:40am is later the same night


TEMPLATES = {}  # MAPS -> the built template, shared by the classes with the same maps


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


def make_repo(repo):
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")
    git(repo, "remote", "add", "origin", "https://example.invalid/t/{}.git".format(repo.name))
    (repo / "README.md").write_text("x\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init")


def alive(pid):
    """True while the process exists and is not a zombie."""
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


class RunnerCase(unittest.TestCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/")),)

    @classmethod
    def setUpClass(cls):
        """One vault (maps and tickets made through sbmap), repos and fake `claude`/`agy` per set of maps; each
        test copies them: building them is most of a test's time."""
        if cls.MAPS in TEMPLATES:
            cls._template = TEMPLATES[cls.MAPS]
            return
        cls._template = TEMPLATES[cls.MAPS] = tempfile.TemporaryDirectory()
        t = Path(cls._template.name).resolve()
        (t / "Vault" / "wayfinder").mkdir(parents=True)
        (t / "bin").mkdir()
        for name in ("claude", "agy"):
            f = t / "bin" / name
            f.write_text("#!/bin/sh\nexec {} {} \"$@\"\n".format(shlex.quote(sys.executable), shlex.quote(str(FAKE))))
            f.chmod(0o755)
        env = {**os.environ, "SB_VAULT": str(t / "Vault"), "PATH": "/usr/bin:/bin", "HOME": str(t)}

        def sb(*a):
            subprocess.run([sys.executable, str(SBMAP), *a], check=True, capture_output=True, env=env, cwd=t / "Vault")
        for folder, repo, *tickets in cls.MAPS:
            make_repo(t / repo)
            sb("init", folder, "--title", folder, "--why", "Why.", "--destination", "Somewhere.", "--repo", str(t / repo))
            sb("mapset", folder, "checks=true")
            for title, path in tickets:
                sb("new", folder, "--title", title, "--why", "Because.", "--done-when", "It works.", "--paths", path,
                   "--no-sync")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "t"
        template = Path(self._template.name).resolve()
        shutil.copytree(template, self.root, symlinks=True)
        for m in self.root.glob("Vault/wayfinder/**/map.md"):  # each map names its repo by absolute path
            m.write_text(m.read_text(encoding="utf-8").replace(str(template), str(self.root)), encoding="utf-8")
        self.vault = self.root / "Vault"
        (self.root / "home").mkdir()
        env = {"SB_VAULT": str(self.vault), "PATH": "{}:/usr/bin:/bin".format(self.root / "bin"),
               "HOME": str(self.root / "home"), "SB_HUB_NOTIFY": "0", "FAKE_WORKER_PIDS": str(self.root / "pids")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("SB_HUB_PORT", "SB_HUB_AGENT", "SB_HUB_PARENT", "FAKE_WORKER_MODE", "CLAUDE_CONFIG_DIR", "FAKE_REVIEW",
                  "FAKE_REVIEW_CALLS"):
            os.environ.pop(k, None)
        self.repos = {folder: self.root / repo for folder, repo, *_ in self.MAPS}
        self.clock = Clock(START)
        self.mode, self.modes, self.launched, self.reviewed = "commit", {}, [], []
        # item key -> what its fake second pass does (FAKE_REVIEW), default finished; a list: one per review, in turn
        # (its last is kept for any later one)
        self.verdicts = {}
        self.hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        with self.hub._lock:
            self.hub._data["installed"] = {n: {"kind": "claude", "dir": str(self.root / (".claude-" + n)), "model": None,
                                               "limited_until": None} for n in ("main", "spare")}
            self.hub._data["queue"]["agent"] = "main"
        self.sup = Supervisor(self.hub, port=4321)
        self.sup.close_off = False  # the morning close-off has its own tests (test_hub_pacing)
        self.addCleanup(self.sup.stop)

    def sb(self, *a, ok=True):
        r = subprocess.run([sys.executable, str(SBMAP), *a], capture_output=True, text=True, cwd=self.vault)
        if ok:
            self.assertEqual(r.returncode, 0, "sbmap {}\n{}{}".format(" ".join(a), r.stdout, r.stderr))
        return r

    def launcher(self, agent, brief, repo, model, env, log):
        """Workers go to `launched`, second passes (a brief naming review files) to `reviewed`, with the keys of the
        tickets it was handed."""
        key = env["SB_HUB_AGENT"]
        review = "\nWrite your review to: " in brief
        nums = re.findall(r"^Write your review to: .*?(\d+)-review\.md$", brief, re.M)
        keys = [sbqueue.map_of(key) + "#" + n for n in nums]
        (self.reviewed if review else self.launched).append(
            {"key": key, "keys": keys, "model": model, "brief": brief, "agent": agent, "log": log})
        fake = {"FAKE_WORKER_MODE": self.modes.get(key, self.mode)}
        if review and any(k in self.verdicts for k in keys):
            got = {}
            for k in keys:
                v = self.verdicts.get(k)
                if v is not None:
                    got[k.rsplit("#", 1)[1]] = (v.pop(0) if len(v) > 1 else v[0]) if isinstance(v, list) else v
            fake["FAKE_REVIEW"] = json.dumps(got)
        return sbhub.launch(agent, brief, repo, model, {**env, **fake}, log)

    # ---- reading the result ----

    def items(self):
        return {i["key"]: i for i in self.hub.state()["queue"]["items"]}

    def open_tickets(self, folder="repo/one"):
        rows = json.loads(self.sb("tickets", "--json").stdout)
        return {r["num"]: r for r in rows if r["map"] == folder}

    def until(self, cond, timeout=60):
        # returns as soon as cond holds; the long limit is for a loaded machine (several hub checks at once)
        end = time.time() + timeout
        while time.time() < end:
            self.sup.tick()
            got = cond()
            if got:
                return got
            time.sleep(0.03)
        self.fail("timed out; queue: {}".format(json.dumps(self.hub.state()["queue"], indent=1)))

    def tick_all(self):
        """The owner ticks every ready ticket (nothing is ever ticked on its own)."""
        rows = self.hub.tickets()
        ready = [t["map"] + "#" + str(t["num"]) for t in rows if t["state"] == "ready"]
        self.hub.queue_set(ready, self.hub.state()["queue"]["version"])

    def only(self, *nums, folder="repo/one"):
        """Just these tickets of the map ticked and resumed (a map's second pass waits for its whole run)."""
        self.hub.queue_set(["{}#{}".format(folder, n) for n in nums], self.hub.state()["queue"]["version"])
        self.hub.queue_pause(False)

    def resume(self):
        """The owner's ticks, then the resume: nothing starts before this."""
        self.tick_all()
        self.hub.queue_pause(False)

    def pids(self):
        """The hanging fake worker's pid and its child's, once it has written them."""
        f = Path(os.environ["FAKE_WORKER_PIDS"])
        end = time.time() + 5
        while not (f.exists() and f.read_text().endswith("\n")) and time.time() < end:
            time.sleep(0.02)
        return tuple(map(int, f.read_text().split()))

    def state_of(self, key):
        return self.items().get(key, {}).get("state")

    def board(self, folder="repo/one"):
        boards = sorted(self.vault.glob("wayfinder/repo/runs/*/*.md"))
        return "\n".join(b.read_text(encoding="utf-8") for b in boards)


class LimitTextTest(unittest.TestCase):
    def test_a_limit_with_no_reset_time_waits_an_hour(self):
        self.assertEqual(sbhub.limited_until("Usage limit reached. Try later.", START), START + 3600)
        self.assertEqual(sbhub.limited_until("You've hit your weekly limit · resets 23:10", START),
                         datetime(2026, 11, 13, 23, 10).timestamp())
        self.assertEqual(sbhub.limited_until("hit your session limit, resets 12:30am", START),
                         datetime(2026, 11, 14, 0, 30).timestamp())
        self.assertEqual(sbhub.limited_until("Spend limit reached, resets 1:00", START),
                         datetime(2026, 11, 14, 1, 0).timestamp())
        self.assertIsNone(sbhub.limited_until("all good, it resets 4:40 nothing", START))
        self.assertEqual(sbhub.ran_past(90 * 60), "ran past 90 minutes")


class TicketLoopTest(RunnerCase):
    def test_a_new_queue_starts_nothing_until_the_owner_resumes_it(self):
        self.sup.tick()
        self.assertEqual(self.hub.state()["queue"]["items"], [])  # nothing is ticked on its own
        self.tick_all()
        for _ in range(2):
            self.sup.tick()
        q = self.hub.state()["queue"]
        self.assertEqual((q["paused"], [i["state"] for i in q["items"]]), (True, ["queued", "queued"]))
        self.assertEqual(self.launched, [])
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.hub.queue_pause(False)
        self.mode = "hang"
        self.sup.tick()
        self.assertEqual(self.state_of("repo/one#1"), "running")

    def test_a_commit_in_its_paths_resolves_the_ticket_and_the_next_one_starts(self):
        self.resume()
        self.sup.tick()
        self.assertEqual((self.state_of("repo/one#1"), self.state_of("repo/one#2")), ("running", "queued"))
        self.until(lambda: self.state_of("repo/one#1") == "done")
        sha = git(self.repos["repo/one"], "log", "-1", "--format=%H", "--grep", "^Ticket: repo/one/001")
        self.assertEqual(self.items()["repo/one#1"]["commit"], sha)
        self.assertNotIn(1, self.open_tickets())
        done = next(self.vault.glob("wayfinder/repo/one/issues/done/001*.md")).read_text(encoding="utf-8")
        self.assertIn(sha, done)
        self.assertIn("## Answer", done)
        self.assertIn("sonnet", done)
        git(self.repos["repo/one"], "remote", "remove", "origin")  # sbmap stamps commits only with an origin
        self.until(lambda: self.state_of("repo/one#2") == "done")
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1", "repo/one#2"])
        sha2 = self.items()["repo/one#2"]["commit"]
        self.assertIn(sha2, next(self.vault.glob("wayfinder/repo/one/issues/done/002*.md")).read_text(encoding="utf-8"))
        # the real launch: claude's flags, the agent's config dir, the item's id, the run folder's log
        log = Path(self.launched[0]["log"]).read_text(encoding="utf-8")
        self.assertIn('argv: ["--permission-mode", "auto", "--model", "sonnet", "--settings", ', log)  # the git guard hook
        self.assertIn('"--output-format", "stream-json", "--verbose"]', log)
        self.assertIn('"CLAUDE_CONFIG_DIR": "{}"'.format(self.root / ".claude-main"), log)
        self.assertIn('"SB_HUB_AGENT": "repo/one#1", "SB_HUB_PARENT": "queue", "SB_HUB_PORT": "4321"', log)
        self.assertIn("cwd: " + str(self.repos["repo/one"]), log)
        self.assertEqual(Path(self.launched[0]["log"]).name, "1.log")
        self.assertIn("Ticket: repo/one/001", self.launched[0]["brief"])
        # the night's digest, once the last ticket ended
        board = self.board()
        self.assertIn("A: done, commit " + sha[:9], board)
        self.assertIn("B: done, commit", board)

    def test_a_commit_outside_its_paths_passes_and_names_the_files(self):
        self.sb("set", "repo/one", "001", "tier=opus", "--no-sync")
        self.modes = {"repo/one#1": "stray"}
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        done = next((self.vault / "wayfinder").rglob("done/001*.md")).read_text()
        self.assertIn("stray.txt", done)

    def test_a_failing_check_leaves_the_ticket_open_with_its_commit_in_place(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=test -f nope.txt", "--no-sync")
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        item = self.items()["repo/one#1"]
        self.assertIn("check failed: test -f nope.txt", item["note"])
        self.assertTrue(item["commit"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertIn(item["commit"], git(self.repos["repo/one"], "log", "--format=%H"))
        self.assertIn("check failed: test -f nope.txt", self.ticket_text(1))
        self.until(lambda: self.state_of("repo/one#2") == "done")
        board = self.board()
        self.assertIn("A: failed, check failed: test -f nope.txt", board)
        self.assertIn("B: done", board)

    def flaky(self, fails):
        """A check that exits 75 `fails` times, then 0; its calls are counted in a file."""
        script = self.root / "flaky.sh"
        script.write_text('n=$(cat "{c}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{c}"; '
                          '[ $n -le {f} ] && exit 75; exit 0\n'.format(c=self.root / "calls", f=fails))
        return "sh " + str(script)

    def calls(self):
        return int((self.root / "calls").read_text())

    def tick_later(self, secs):
        self.clock.t += secs
        self.sup.tick()

    def test_a_check_that_exits_75_keeps_the_commit_never_reruns_the_worker_and_is_rechecked_later(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=" + self.flaky(2), "--no-sync")
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "recheck")
        item = self.items()["repo/one#1"]
        self.assertIn("check could not run", item["note"])
        self.assertTrue(item["commit"])
        self.assertEqual(item["rechecks"], 0)
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")  # still held: neither failed nor released
        self.assertNotIn("failed", self.ticket_text(1))
        self.assertIn("could not run", (Path(item["log"]).parent / "1.md").read_text())
        self.assertEqual(self.calls(), 1)
        self.until(lambda: self.state_of("repo/one#2") == "landed")  # judged with the map's, once its checks ran
        # not due yet: nothing runs again
        self.tick_later(sbhub.RECHECK_EVERY - 60)
        self.assertEqual(self.calls(), 1)
        # due: still no answer, so waiting again
        self.tick_later(61)
        self.assertEqual((self.calls(), self.state_of("repo/one#1"), self.items()["repo/one#1"]["rechecks"]), (2, "recheck", 1))
        # due again: it answers, the review judges it and the ticket resolves with the same commit
        self.tick_later(sbhub.RECHECK_EVERY + 1)
        self.assertEqual((self.calls(), self.state_of("repo/one#1")), (3, "review"))
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(self.items()["repo/one#1"]["commit"], item["commit"])
        self.assertNotIn(1, self.open_tickets())
        self.assertEqual(self.state_of("repo/one#2"), "done")  # the one review judged both
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"]])
        self.assertEqual([x["key"] for x in self.launched].count("repo/one#1"), 1)  # the worker ran once

    def test_the_recheck_button_runs_the_checks_at_once_and_a_ticket_gives_up_after_six(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=" + self.flaky(99), "--no-sync")
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "recheck")
        for _ in range(sbhub.RECHECKS_MAX):
            self.tick_later(sbhub.RECHECK_EVERY + 1)
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["rechecks"], item["recheck_at"]), ("recheck", sbhub.RECHECKS_MAX, None))
        self.assertIn("press Recheck", item["note"])
        self.assertEqual(self.calls(), 1 + sbhub.RECHECKS_MAX)
        self.tick_later(10 * sbhub.RECHECK_EVERY)
        self.assertEqual(self.calls(), 1 + sbhub.RECHECKS_MAX)
        self.hub.ticket_action("recheck", "repo/one#1")
        self.sup.tick()
        self.assertEqual((self.calls(), self.items()["repo/one#1"]["rechecks"]), (2 + sbhub.RECHECKS_MAX, 1))
        with self.assertRaises(ValueError):
            self.hub.ticket_action("recheck", "repo/one#2")

    def test_a_worker_that_tries_sbmap_resolve_is_refused_and_the_ticket_stays_open(self):
        self.modes = {"repo/one#1": "resolve", "repo/one#2": "hang"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        log = Path(self.items()["repo/one#1"]["log"]).read_text(encoding="utf-8")
        self.assertIn('"permissionDecision": "deny"', log)
        self.assertIn("write a comment instead", log)
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertFalse(list(self.vault.glob("wayfinder/repo/one/issues/done/001*.md")))

    def test_no_commit_on_sonnet_retries_once_on_opus_then_fails(self):
        self.modes = {"repo/one#1": "nothing", "repo/one#2": "hang"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        runs = [x for x in self.launched if x["key"] == "repo/one#1"]
        self.assertEqual([x["model"] for x in runs], ["sonnet", "opus"])
        self.assertIn("no commit", runs[1]["brief"])
        self.assertNotIn("no commit", runs[0]["brief"])
        self.assertIn('"--model", "opus"', Path(runs[1]["log"]).read_text(encoding="utf-8"))
        self.assertEqual(self.items()["repo/one#1"]["tries"], 1)
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertIn("no commit", self.ticket_text(1))

    def ticket_text(self, num, folder="repo/one"):
        f = next((self.vault / "wayfinder" / folder / "issues").glob("{:03d}*.md".format(num)))
        return f.read_text(encoding="utf-8")


class ReviewTest(RunnerCase):
    """The second pass: once a ticket's commit and checks passed, an Opus session (the fake reviewer) judges it
    against its Done when, and only `finished` resolves it."""

    def ticket_text(self, num, folder="repo/one"):
        f = next((self.vault / "wayfinder" / folder / "issues").glob("{:03d}*.md".format(num)))
        return f.read_text(encoding="utf-8")

    def tick_later(self, secs):
        self.clock.t += secs
        self.sup.tick()

    def sha(self, num):
        return git(self.repos["repo/one"], "log", "-1", "--format=%H", "--grep", "^Ticket: repo/one/{:03d}".format(num))

    def test_a_finished_verdict_resolves_the_ticket_with_its_commit_and_the_review_file_is_on_the_item(self):
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item, sha = self.items()["repo/one#1"], self.sha(1)
        self.assertEqual((item["commit"], item["verdict"], item.get("checked")), (sha, "finished", None))
        # (4) the review file is in the run folder and its path is on the item
        self.assertEqual(item["review"], str(Path(item["run"]) / "1-review.md"))
        self.assertIn("Verdict: finished", Path(item["review"]).read_text(encoding="utf-8"))
        self.assertTrue((Path(item["run"]) / "1-review.log").is_file())
        done = next(self.vault.glob("wayfinder/repo/one/issues/done/001*.md")).read_text(encoding="utf-8")
        self.assertIn(sha, done)
        self.assertIn("The Opus review judged it finished: " + item["review"], done)
        # the review is briefed with the ticket, the commit's diff and the worker's report, and told to change nothing
        brief = self.reviewed[0]["brief"]
        self.assertIn("#1: A", brief)  # sbmap show
        self.assertIn("work for repo/one/001", brief)  # the diff
        self.assertIn("## Hub checks", brief)  # the worker's report, with the hub's checks appended
        self.assertIn("Change no code, commit nothing", brief)
        self.assertEqual(Path(self.reviewed[0]["log"]).name, "1-review.log")

    def test_partly_and_not_met_twice_leave_the_ticket_open_with_the_findings_and_name_the_verdict(self):
        self.verdicts = {"repo/one#1": "partly", "repo/one#2": "not met"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed" and self.state_of("repo/one#2") == "failed")
        tickets = self.open_tickets()
        for num, verdict in ((1, "partly"), (2, "not met")):
            item, sha = self.items()["repo/one#{}".format(num)], self.sha(num)
            self.assertEqual((item["verdict"], item["commit"]), (verdict, sha))
            self.assertTrue(item["note"].startswith(
                "judged {} by the Opus review after its second try: It works.".format(verdict)), item["note"])
            self.assertEqual((tickets[num]["status"], tickets[num]["claimed_by"]), ("open", None))
            text = self.ticket_text(num)
            self.assertIn("Opus review judged this ticket {} against its Done when".format(verdict), text)
            self.assertIn("- It works.: not met: the fake reviewer found no test for it", text)
            first = item["redo"]["commit"]
            self.assertIn("Both tries' commits, {} and {}, are left where they landed.".format(first[:9], sha[:9]), text)
            log = git(self.repos["repo/one"], "log", "--format=%H")
            self.assertIn(sha, log)  # the commits stay
            self.assertIn(first, log)
            self.assertEqual(item["review"], str(Path(item["run"]) / "{}-review.md".format(num)))
        self.assertIn("A: failed, judged partly by the Opus review", self.board())
        self.assertEqual(self.items()["repo/one#2"]["note"].count("not met"), 2)  # the verdict, and the item

    def test_the_reviewer_runs_on_opus_for_a_sonnet_ticket_and_an_opus_ticket(self):
        self.sb("set", "repo/one", "002", "tier=opus", "--no-sync")
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "done" and self.state_of("repo/one#2") == "done")
        self.assertEqual([(x["key"], x["model"]) for x in self.launched], [("repo/one#1", "sonnet"), ("repo/one#2", "opus")])
        self.assertEqual([(x["keys"], x["model"]) for x in self.reviewed], [(["repo/one#1", "repo/one#2"], "opus")])
        log = Path(self.reviewed[0]["log"]).read_text(encoding="utf-8")
        self.assertIn('"--model", "opus"', log)  # the real launch's flags
        self.assertIn('"CLAUDE_CONFIG_DIR": "{}"'.format(self.root / ".claude-main"), log)  # the worker's own account

    def counting_check(self):
        script = self.root / "count.sh"
        script.write_text('n=$(cat "{c}" 2>/dev/null || echo 0); echo $((n+1)) > "{c}"\n'.format(c=self.root / "calls"))
        return "sh " + str(script)

    def test_a_review_without_a_verdict_keeps_the_commit_and_the_claim_and_a_recheck_runs_the_review_only(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=" + self.counting_check(), "--no-sync")
        self.verdicts = {"repo/one#1": "none"}
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "recheck")
        item, sha = self.items()["repo/one#1"], self.sha(1)
        self.assertTrue(item["note"].startswith("review could not run: its review file names no verdict; "), item["note"])
        self.assertIn("the review runs again at", item["note"])
        self.assertEqual((item["commit"], item["verdict"], item["rechecks"]), (sha, None, 0))
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")  # neither resolved nor released
        self.assertNotIn("Opus review judged", self.ticket_text(1))
        self.assertEqual(int((self.root / "calls").read_text()), 1)
        # a crash on the next look is the same: could not run, counted as a recheck
        self.verdicts["repo/one#1"] = "crash"
        self.tick_later(sbhub.RECHECK_EVERY + 1)
        self.until(lambda: self.state_of("repo/one#1") == "recheck")
        item = self.items()["repo/one#1"]
        self.assertTrue(item["note"].startswith("review could not run: it exited 1 and wrote no review file"), item["note"])
        self.assertEqual((item["commit"], item["rechecks"]), (sha, 1))
        # the recheck that answers: the review runs again, never the worker or the checks, and the ticket resolves
        self.verdicts["repo/one#1"] = "finished"
        self.tick_later(sbhub.RECHECK_EVERY + 1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual((self.items()["repo/one#1"]["commit"], self.items()["repo/one#1"]["verdict"]), (sha, "finished"))
        self.assertEqual([x["key"] for x in self.launched].count("repo/one#1"), 1)
        self.assertEqual([x["key"] for x in self.reviewed], ["repo/one#1"] * 3)
        self.assertEqual(int((self.root / "calls").read_text()), 1)
        self.assertNotIn(1, self.open_tickets())

    def test_a_ticket_that_waits_on_a_landed_one_starts_and_both_are_judged_at_the_map_end(self):
        # the owner's default: what comes after a landed-but-unjudged ticket may start, the review judging it later
        self.sb("block", "repo/one", "002", "1", "--no-sync")
        self.verdicts = {"repo/one#1": ["not met", "not met"]}
        self.only(1, 2)
        self.until(lambda: self.state_of("repo/one#2") == "running")
        self.assertEqual((self.state_of("repo/one#1"), self.reviewed), ("landed", []))
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"], ["repo/one#1"]])
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1", "repo/one#2", "repo/one#1"])
        self.assertEqual(self.state_of("repo/one#2"), "done")


class MapReviewTest(RunnerCase):
    """One second pass per map, once the map's run has ended: a ticket whose checks pass lands, holds nothing, and the
    next one starts at once; the review then judges every landed ticket together."""
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "one/")),)  # both own the same path

    def ticket_text(self, num, folder="repo/one"):
        f = next(iter(sorted((self.vault / "wayfinder" / folder / "issues").glob("**/{:03d}*.md".format(num)))))
        return f.read_text(encoding="utf-8")

    def shas(self, num):
        out = git(self.repos["repo/one"], "log", "--reverse", "--format=%H", "--grep", "^Ticket: repo/one/{:03d}".format(num))
        return out.split()

    def test_a_ticket_whose_checks_pass_lands_and_frees_its_path_and_no_review_runs_while_the_map_has_work(self):
        self.modes = {"repo/one#2": "hang"}  # (1) the second ticket shares the first one's path
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "landed" and self.state_of("repo/one#2") == "running")
        item = self.items()["repo/one#1"]
        self.assertEqual((item["commit"], self.reviewed), (self.shas(1)[0], []))  # (1) it started before any review
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")  # the ticket stays open until judged
        for _ in range(5):  # (2) a running ticket of the map: no review starts
            self.sup.tick()
            time.sleep(0.05)
        self.assertEqual((self.state_of("repo/one#1"), self.reviewed), ("landed", []))
        # a ticket queued behind it holds the review back too
        self.assertEqual(self.sup.reviews, {})

    def test_when_the_maps_last_ticket_ends_one_review_on_opus_is_handed_every_landed_ticket(self):
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "done" and self.state_of("repo/one#2") == "done")
        self.assertEqual(len(self.reviewed), 1)  # (3) one review, for both
        rv = self.reviewed[0]
        self.assertEqual((rv["model"], rv["keys"]), ("opus", ["repo/one#1", "repo/one#2"]))
        for n in (1, 2):
            self.assertIn("work for repo/one/00{}".format(n), rv["brief"])  # each commit's diff
            self.assertIn(self.shas(n)[0], rv["brief"])
            self.assertIn("{}-review.md".format(n), rv["brief"])
        self.assertIn("#1: A", rv["brief"])  # each ticket, as sbmap show prints it
        self.assertIn("#2: B", rv["brief"])
        self.assertEqual(rv["brief"].count("## Hub checks"), 2)  # each worker's report
        # (4) finished resolves each ticket with its own commit
        for n in (1, 2):
            sha = self.shas(n)[0]
            self.assertEqual((self.items()["repo/one#{}".format(n)]["commit"], self.items()["repo/one#{}".format(n)]["verdict"]),
                             (sha, "finished"))
            self.assertIn(sha, self.ticket_text(n))
        self.assertEqual(self.open_tickets(), {})
        self.assertEqual(sbhub.review_limit(2), 20 * 60)  # 10 minutes plus 5 per ticket
        self.assertEqual(self.sup.reviews, {})

    def test_the_review_may_run_for_ten_minutes_plus_five_per_ticket(self):
        self.verdicts = {"repo/one#1": "slow"}
        os.environ["FAKE_REVIEW_SLEEP"] = "3"
        self.addCleanup(os.environ.pop, "FAKE_REVIEW_SLEEP", None)
        self.resume()
        self.until(lambda: "repo/one" in self.sup.reviews)
        self.assertEqual(self.sup.reviews["repo/one"]["limit"], (10 + 5 * 2) * 60)
        self.until(lambda: self.state_of("repo/one#1") == "done")

    def test_not_met_leaves_the_ticket_open_with_the_findings_and_queues_its_one_retry_which_alone_is_judged_next(self):
        self.verdicts = {"repo/one#2": ["not met", "finished"]}
        self.resume()
        self.until(lambda: self.items()["repo/one#2"].get("redo") is not None)
        item = self.items()["repo/one#2"]
        self.assertEqual(self.state_of("repo/one#1"), "done")  # (4) the finished one is resolved
        self.assertEqual((item["redo"]["verdict"], item["redo"]["commit"]), ("not met", self.shas(2)[0]))
        self.assertIn(item["state"], ("queued", "running"))
        self.assertEqual(self.open_tickets()[2]["status"] in ("open", "claimed"), True)  # not resolved
        self.assertIn("- It works.: not met: the fake reviewer found no test for it", self.ticket_text(2))
        self.assertIn("It gets one more try with these findings.", self.ticket_text(2))
        self.until(lambda: self.state_of("repo/one#2") == "done")
        # (5) the retry's review judges only it, both tries' commits together
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"], ["repo/one#2"]])
        second = self.reviewed[1]["brief"]
        self.assertNotIn(self.shas(1)[0], second)
        self.assertNotIn("1-review.md", second)
        self.assertIn("judge both tries' commits together", second)
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1", "repo/one#2", "repo/one#2"])

    def test_pausing_the_queue_starts_the_review_of_a_map_with_landed_tickets(self):
        self.modes = {"repo/one#1": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "1.5"
        self.addCleanup(os.environ.pop, "FAKE_WORKER_SLEEP", None)
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "running")
        self.hub.queue_pause(True)  # ticket 2 waits in the line; the run is over once ticket 1 ends
        self.until(lambda: self.state_of("repo/one#1") == "done")  # (6) judged while paused, 2 still queued
        self.assertEqual((self.state_of("repo/one#2"), [x["keys"] for x in self.reviewed]), ("queued", [["repo/one#1"]]))
        self.hub.queue_pause(False)
        self.until(lambda: self.state_of("repo/one#2") == "done")
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1"], ["repo/one#2"]])

    def test_a_queue_saved_with_items_in_the_old_review_state_loads_and_they_are_judged(self):
        self.modes = {"repo/one#2": "hang"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "landed" and self.state_of("repo/one#2") == "running")
        self.sup.stop()  # the hub ends; an older one had saved ticket 1 in state `review` with no pass running
        with self.hub._lock:
            q = self.hub._data["queue"]
            q["items"] = [i for i in q["items"] if i["key"] == "repo/one#1"]
            q["items"][0]["state"] = "review"
            self.hub._save()
        self.reviewed.clear()
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        self.assertEqual([i["state"] for i in hub.state()["queue"]["items"]], ["review"])
        sup = Supervisor(hub, port=4321)
        sup.close_off = False
        self.addCleanup(sup.stop)
        end = time.time() + 60
        while time.time() < end and hub.state()["queue"]["items"][0]["state"] != "done":
            sup.tick()
            time.sleep(0.03)
        item = hub.state()["queue"]["items"][0]
        self.assertEqual((item["state"], item["verdict"], item["commit"]), ("done", "finished", self.shas(1)[0]))
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1"]])
        self.assertNotIn(1, self.open_tickets())


class ReviewRetryTest(RunnerCase):
    """A ticket the review judges partly or not met gets one more try (the item's `redo`), briefed with the review's
    findings and its first commit; if that falls short too, it stays open and waits for the owner."""

    def ticket_text(self, num, folder="repo/one"):
        f = next(iter(sorted((self.vault / "wayfinder" / folder / "issues").glob("**/{:03d}*.md".format(num)))))
        return f.read_text(encoding="utf-8")

    def shas(self, num):
        """The ticket's commits, oldest first."""
        out = git(self.repos["repo/one"], "log", "--reverse", "--format=%H", "--grep", "^Ticket: repo/one/{:03d}".format(num))
        return out.split()

    def only_one(self):
        """Ticket 1 alone in the queue (a hanging ticket 2 would hold the repo its one more try needs)."""
        self.hub.queue_set(["repo/one#1"], self.hub.state()["queue"]["version"])
        self.hub.queue_pause(False)

    def runs(self, key="repo/one#1"):
        return [x for x in self.launched if x["key"] == key]

    def assert_second_brief(self, brief, first, verdict):
        self.assertIn("## This is the ticket's second try", brief)
        self.assertIn("The first try made commit {}, which is already in this branch: build on it, do not redo or "
                      "revert it.".format(first), brief)
        self.assertIn("judged that try {} against the Done when".format(verdict), brief)
        self.assertIn("- It works.: not met: the fake reviewer found no test for it", brief)  # the not-met line
        self.assertNotIn("- The commit names the ticket: met", brief)  # a met line is not a finding

    def test_not_met_then_finished_runs_the_worker_twice_briefed_with_the_findings_and_the_first_commit(self):
        self.verdicts = {"repo/one#1": ["not met", "finished"]}
        self.only_one()
        self.until(lambda: self.state_of("repo/one#1") == "done")
        runs, (first, second) = self.runs(), self.shas(1)
        self.assertEqual([x["model"] for x in runs], ["sonnet", "sonnet"])  # the same model, not a switch to opus
        self.assertNotIn("second try", runs[0]["brief"])
        self.assert_second_brief(runs[1]["brief"], first, "not met")
        item = self.items()["repo/one#1"]
        self.assertEqual((item["commit"], item["verdict"], item["redo"]["commit"], item["redo"]["verdict"]),
                         (second, "finished", first, "not met"))
        # the first review is kept beside the second; the second judges both commits together
        self.assertEqual(Path(item["redo"]["review"]).name, "1-review-1.md")
        self.assertIn("Verdict: not met", Path(item["redo"]["review"]).read_text(encoding="utf-8"))
        rv = [x["brief"] for x in self.reviewed if x["key"] == "repo/one#1"]
        self.assertEqual(len(rv), 2)
        self.assertIn("Commits {} (the first try) and {} (the second try)".format(first, second), rv[1])
        self.assertIn("judge both tries' commits together", rv[1])
        self.assertIn("show {} {}`".format(first, second), rv[1])
        self.assertNotIn(1, self.open_tickets())  # resolved
        done = self.ticket_text(1)
        self.assertIn(second, done)
        self.assertIn("It gets one more try with these findings.", done)

    def test_not_met_twice_ends_after_two_runs_open_with_both_findings_and_waiting_for_the_owner(self):
        self.verdicts = {"repo/one#1": "not met"}
        self.only_one()
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        for _ in range(3):  # nothing more starts for it
            self.sup.tick()
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(len([x for x in self.reviewed if x["key"] == "repo/one#1"]), 2)
        first, second = self.shas(1)
        t = self.open_tickets()[1]
        self.assertEqual((t["status"], t["claimed_by"]), ("open", None))
        text = self.ticket_text(1)
        self.assertEqual(text.count("- It works.: not met: the fake reviewer found no test for it"), 2)
        self.assertIn("It gets one more try with these findings.", text)
        self.assertIn("second try). Both tries' commits", text)
        self.assertIn("That was its second try: it waits for the owner.", text)
        self.assertIn(Path(self.items()["repo/one#1"]["redo"]["review"]).name, text)  # the first review, kept
        log = git(self.repos["repo/one"], "log", "--format=%H")
        self.assertTrue(first in log and second in log)  # nothing reverted
        # it ends `failed` with its verdict: the page lists ended failed runs under Waits for you (board.ts waitsFor)
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["verdict"], item["commit"]), ("failed", "not met", second))
        self.assertIsNotNone(item["ended"])
        self.assertTrue(item["note"].startswith("judged not met by the Opus review after its second try"), item["note"])

    def test_partly_is_handled_as_not_met(self):
        self.verdicts = {"repo/one#1": "partly", "repo/one#2": ["partly", "finished"]}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed" and self.state_of("repo/one#2") == "done")
        for key, num in (("repo/one#1", 1), ("repo/one#2", 2)):
            runs = self.runs(key)
            self.assertEqual(len(runs), 2, key)
            self.assert_second_brief(runs[1]["brief"], self.shas(num)[0], "partly")
            self.assertEqual(self.items()[key]["redo"]["verdict"], "partly")
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertNotIn(2, self.open_tickets())

    def test_a_ticket_stopped_at_a_usage_limit_before_any_review_still_gets_its_review_driven_try(self):
        self.mode, self.verdicts = "limit", {"repo/one#1": ["not met", "finished"]}
        self.only_one()
        self.until(lambda: self.hub.state()["installed"]["main"]["limited_until"])
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["stops"], item.get("redo"), self.reviewed), ("queued", 1, None, []))
        self.clock.t = datetime(2026, 11, 13, 4, 40).timestamp() + 1
        self.mode = "commit"
        self.until(lambda: self.state_of("repo/one#1") == "done")
        runs = self.runs()
        self.assertEqual(len(runs), 3)  # the stopped try, the try it resumed with, the review's one more try
        self.assertIn("An earlier try", runs[1]["brief"])
        self.assertNotIn("second try", runs[1]["brief"])
        self.assert_second_brief(runs[2]["brief"], self.shas(1)[0], "not met")
        self.assertNotIn("An earlier try", runs[2]["brief"])  # the stop is over: its resume note went
        item = self.items()["repo/one#1"]
        self.assertEqual((item["stops"], item["verdict"], item["redo"]["verdict"]), (1, "finished", "not met"))
        self.assertEqual(len([x for x in self.reviewed if x["key"] == "repo/one#1"]), 2)
        self.assertNotIn(1, self.open_tickets())


class StopsTest(RunnerCase):
    def test_a_usage_limit_waits_for_the_reset_and_releases_the_claim(self):
        self.mode = "limit"
        self.resume()
        self.until(lambda: self.hub.state()["installed"]["main"]["limited_until"])
        reset = datetime(2026, 11, 13, 4, 40).timestamp()
        self.assertEqual(self.hub.state()["installed"]["main"]["limited_until"], reset)
        self.assertEqual((self.state_of("repo/one#1"), self.state_of("repo/one#2")), ("queued", "queued"))
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        for _ in range(3):
            self.sup.tick()
        self.assertEqual(len(self.launched), 1)
        self.clock.t = reset + 1
        # the next try is judged on its own output, not the limit line the log still holds from the last one;
        # and a worker that commits correctly before it hits a limit is resolved, its agent not limited again
        self.mode, self.modes = "commit", {"repo/one#2": "commit-limit"}
        self.until(lambda: self.state_of("repo/one#2") == "done")
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1", "repo/one#1", "repo/one#2"])
        self.assertEqual(self.state_of("repo/one#1"), "done")
        self.assertIn("session limit", Path(self.launched[0]["log"]).read_text(encoding="utf-8"))
        self.assertEqual(self.hub.state()["installed"]["main"]["limited_until"], reset)
        self.assertEqual(self.open_tickets(), {})

    def test_a_worker_past_its_time_limit_has_its_whole_group_killed_and_a_sonnet_ticket_retries_on_opus(self):
        self.sup.limit = 1
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        groups = [self.pids()]
        Path(os.environ["FAKE_WORKER_PIDS"]).unlink()
        self.clock.t += 2
        self.sup.tick()  # killed, then retried on opus at once
        runs = [x for x in self.launched if x["key"] == "repo/one#1"]
        self.assertEqual([x["model"] for x in runs], ["sonnet", "opus"])
        self.assertIn("ran past", runs[1]["brief"])
        self.assertEqual((self.items()["repo/one#1"]["state"], self.items()["repo/one#1"]["tries"]), ("running", 1))
        groups.append(self.pids())
        self.clock.t += 2
        self.sup.tick()
        item = self.items()["repo/one#1"]
        self.assertEqual(item["state"], "failed")
        self.assertIn("ran past", item["note"])
        pids = [pid for g in groups for pid in g]
        end = time.time() + 5
        while any(map(alive, pids)) and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(any(map(alive, pids)))
        self.assertEqual(self.open_tickets()[1]["status"], "open")

    def test_three_failures_with_no_commit_pause_the_queue(self):
        self.sb("new", "repo/one", "--title", "C", "--why", "Because.", "--done-when", "It works.", "--no-sync")
        for n in ("001", "002", "003"):
            self.sb("set", "repo/one", n, "tier=opus", "--no-sync")
        self.mode = "nothing"
        self.resume()
        self.until(lambda: self.hub.state()["queue"]["paused"])
        q = self.hub.state()["queue"]
        self.assertEqual([i["state"] for i in q["items"]], ["failed"] * 3)
        self.assertIn("no commit", q["note"])

    def test_a_ticket_resolved_or_claimed_while_queued_is_skipped_with_its_new_state(self):
        self.resume()
        self.sb("resolve", "repo/one", "001", "--gist", "by hand", "--answer", "Done by hand.")
        self.sb("claim", "repo/one", "002", "--by", "a live session")
        self.sup.tick()
        items = self.items()
        self.assertEqual((items["repo/one#1"]["state"], items["repo/one#2"]["state"]), ("skipped", "skipped"))
        self.assertIn("no longer open", items["repo/one#1"]["note"])
        self.assertIn("claimed by a live session", items["repo/one#2"]["note"])
        self.assertEqual(self.launched, [])
        self.assertEqual(self.open_tickets()[2]["status"], "claimed")

    def test_a_reopened_blocker_skips_its_dependant(self):
        self.sb("block", "repo/one", "002", "1", "--no-sync")
        self.sb("resolve", "repo/one", "001", "--gist", "first", "--answer", "Done.")
        self.resume()
        self.assertEqual(list(self.items()), ["repo/one#2"])
        self.sb("set", "repo/one", "001", "status=open", "--no-sync")
        self.sup.tick()
        self.assertEqual(self.state_of("repo/one#2"), "skipped")
        self.assertIn("blocked", self.items()["repo/one#2"]["note"])

    def test_a_restarted_hub_requeues_a_running_item_and_releases_its_claim(self):
        self.tick_all()
        self.sb("claim", "repo/one", "001", "--by", "hub main")
        with self.hub._lock:
            self.hub._data["queue"]["items"][0].update(state="running", started=START)
            self.hub._data["queue"]["paused"] = True
            self.hub._save()
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        self.addCleanup(sup.stop)
        sup.tick()
        q = hub.state()["queue"]
        self.assertEqual((q["items"][0]["state"], q["paused"]), ("queued", True))  # the saved pause stays
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertEqual(self.launched, [])

    def test_a_worker_that_outlived_its_hub_is_waited_for_and_judged_never_run_twice(self):
        self.modes = {"repo/one#1": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "1.5"
        self.only(1)
        self.sup.tick()
        pid = self.items()["repo/one#1"]["pid"]
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)  # the hub died; a new one starts
        sup = Supervisor(hub)
        self.addCleanup(sup.stop)
        sup.tick()
        item = hub.state()["queue"]["items"][0]
        self.assertEqual((item["key"], item["state"], item["pid"]), ("repo/one#1", "running", pid))  # waited for
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1"])
        self.assertTrue(alive(pid))
        end = time.time() + 10
        while time.time() < end and hub.state()["queue"]["items"][0]["state"] in ("running", "landed", "review"):
            sup.tick()
            time.sleep(0.05)
        item = hub.state()["queue"]["items"][0]
        sha = git(self.repos["repo/one"], "log", "-1", "--format=%H", "--grep", "^Ticket: repo/one/001")
        self.assertEqual((item["state"], item["commit"]), ("done", sha))  # judged by the new hub, in code
        self.assertEqual([x["key"] for x in self.launched].count("repo/one#1"), 1)
        self.assertNotIn(1, self.open_tickets())

    def test_a_restart_never_releases_a_claim_a_session_holds(self):
        self.tick_all()
        self.sb("claim", "repo/one", "001", "--by", "a live session")
        with self.hub._lock:
            self.hub._data["queue"]["items"][0].update(state="running", started=START)
            self.hub._data["queue"]["paused"] = True
        self.sup.tick()
        self.assertEqual(self.state_of("repo/one#1"), "queued")
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")


class ConcurrencyTest(RunnerCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/")),
            ("repo/two", "repoB", ("C", "three/")))

    def test_one_ticket_per_repo_and_per_agent(self):
        self.mode = "hang"
        self.resume()
        self.assertEqual(list(self.items()), ["repo/one#1", "repo/one#2", "repo/two#3"])  # map by map
        self.sup.tick()
        self.sup.tick()
        self.assertEqual([self.state_of(k) for k in ("repo/one#1", "repo/two#3", "repo/one#2")],
                         ["running", "queued", "queued"])
        self.sb("claim", "repo/one", "002", "--by", "a live session")  # for a while: it is not about to start
        self.hub.queue_item_agent("repo/two#3", "spare")
        self.sup.tick()
        self.sup.tick()
        self.assertEqual([self.state_of(k) for k in ("repo/one#1", "repo/two#3", "repo/one#2")],
                         ["running", "running", "queued"])
        self.assertEqual(self.items()["repo/one#2"]["note"], "")  # not judged while its repo is busy
        self.assertEqual([(x["key"], x["agent"]["dir"]) for x in self.launched],
                         [("repo/one#1", str(self.root / ".claude-main")),
                          ("repo/two#3", str(self.root / ".claude-spare"))])


class JobsTest(RunnerCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/")),
            ("repo/two", "repoB", ("C", "three/")))

    def launcher(self, agent, brief, repo, model, env, log):
        key = env["SB_HUB_AGENT"]
        mode = self.modes.get(key, self.mode)
        if key.startswith("job:") and mode == "commit":  # a prompt has no ticket to commit for
            mode = "job"
        self.launched.append({"key": key, "model": model, "brief": brief, "agent": agent, "log": log, "repo": repo})
        return sbhub.launch(agent, brief, repo, model, {**env, "FAKE_WORKER_MODE": mode}, log)

    def setUp(self):
        super().setUp()
        repo = self.repos["repo/two"]  # built alike, the two repos share a head: give one its own
        (repo / "other.txt").write_text("y\n")
        git(repo, "add", "other.txt")
        git(repo, "commit", "-q", "-m", "other")

    def jobs(self):
        return [i for i in self.hub.state()["queue"]["items"] if i["kind"] == "job"]

    def seed(self, key):
        self.hub.report({"agent": key, "role": "worker", "parent": "queue", "state": "working", "note": "reading"})

    def test_a_ticket_and_a_job_that_end_leave_their_agent_rows_done(self):
        self.seed("repo/one#1")
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item = self.items()["repo/one#1"]
        row = self.hub.state()["agents"]["repo/one#1"]
        self.assertEqual((row["state"], row["at"], row["since"]), ("done", item["ended"], item["ended"]))
        out = self.hub.queue_job("repo", "Audit the thing", "main", "sonnet", "audit")
        self.seed(out["key"])
        self.until(lambda: self.state_of(out["key"]) == "done")
        row = self.hub.state()["agents"][out["key"]]
        self.assertEqual((row["state"], row["at"]), ("done", self.items()[out["key"]]["ended"]))

    def test_a_hub_that_starts_with_an_ended_item_and_a_working_row_repairs_the_row(self):
        self.seed("repo/one#1")
        self.seed("repo/one#2")
        with self.hub._lock:
            self.hub._data["queue"]["items"] = [
                {"key": "repo/one#1", "kind": "ticket", "state": "failed", "ended": self.clock.t - 5},
                {"key": "repo/one#2", "kind": "ticket", "state": "running"}]
            self.hub._save()
        again = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        agents = again.state()["agents"]
        self.assertEqual((agents["repo/one#1"]["state"], agents["repo/one#1"]["at"]), ("done", self.clock.t - 5))
        self.assertEqual(agents["repo/one#2"]["state"], "working")

    def test_a_jobs_result_lands_in_its_run_folder_and_the_item_links_it(self):
        out = self.hub.queue_job("repo", "Audit the thing\nin detail", "main", "sonnet", "audit")
        self.resume()
        self.until(lambda: self.state_of(out["key"]) == "done")
        item = self.items()[out["key"]]
        folder = Path(item["run"])
        self.assertEqual((folder.parent, folder.name.endswith("-audit")), (self.vault / "wayfinder/repo/runs", True))
        self.assertEqual(Path(item["result"]).read_text(encoding="utf-8").strip(), "did: Audit the thing")
        self.assertIn("did: Audit the thing", (folder / "job.log").read_text(encoding="utf-8"))
        self.assertEqual((item["kind"], self.launched[0]["repo"], self.launched[0]["model"]),
                         ("job", str(self.repos["repo/one"]), "sonnet"))
        self.assertIn(str(folder), self.launched[0]["brief"])

    def test_a_queue_with_final_review_gets_one_review_job_per_touched_repo_after_its_last_ticket(self):
        bases = {r: git(self.repos[r], "rev-parse", "HEAD") for r in self.repos}
        self.tick_all()
        v = self.hub.state()["queue"]["version"]
        self.assertTrue(self.hub.queue_options(None, True, v)["ok"])
        self.assertTrue(self.hub.queue_options(None, True, v)["stale"])
        self.resume()
        self.until(lambda: len(self.jobs()) == 2)
        for _ in range(3):
            self.sup.tick()
        jobs = self.jobs()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(sorted(j["repo"] for j in jobs), sorted(map(str, self.repos.values())))
        for j in jobs:
            self.assertEqual((j["agent"], j["model"]), ("main", "opus"))
            self.assertIn("since " + bases["repo/one" if j["repo"].endswith("repoA") else "repo/two"], j["prompt"])
            self.assertIn("Review the commits of tonight's tickets", j["prompt"])
        self.assertTrue(all(self.state_of(k) == "done" for k in ("repo/one#1", "repo/one#2", "repo/two#3")))
        self.until(lambda: all(j["state"] == "done" for j in self.jobs()))
        self.assertEqual(len(self.jobs()), 2)

    def test_past_the_stop_time_nothing_starts_and_the_rest_are_skipped(self):
        self.tick_all()
        job = self.hub.queue_job("repo", "Audit it", "main")["key"]
        self.hub.queue_options(START + 60, False, self.hub.state()["queue"]["version"])
        self.resume()
        self.clock.t = START + 120
        self.sup.tick()
        self.assertEqual(self.launched, [])
        notes = {i["state"] + ": " + i["note"] for i in self.hub.state()["queue"]["items"]}
        self.assertEqual(notes, {"skipped: past the stop time"})
        self.assertEqual(self.state_of(job), "skipped")

    def test_the_stop_time_also_ends_what_waits_for_an_agents_reset(self):
        self.mode = "limit"
        self.hub.queue_options(START + 3600, False, self.hub.state()["queue"]["version"])
        self.resume()
        self.until(lambda: self.hub.state()["installed"]["main"]["limited_until"])
        self.assertEqual(self.state_of("repo/one#1"), "queued")
        self.clock.t = START + 3601
        self.sup.tick()
        self.assertEqual({i["state"] for i in self.hub.state()["queue"]["items"]}, {"skipped"})
        self.assertEqual(len(self.launched), 1)

    def test_a_duplicate_job_within_a_day_is_refused_naming_the_earlier_item_and_accepted_after_a_day(self):
        first = self.hub.queue_job("repo", "Audit it", "main", None, "audit")["key"]
        with self.assertRaises(ValueError) as e:
            self.hub.queue_job("repo", "Audit it", "spare", "opus", "other name")
        self.assertIn(first, str(e.exception))
        self.hub.queue_job("repo", "Audit it too", "main")  # another prompt is no duplicate
        self.clock.t = START + 86401
        again = self.hub.queue_job("repo", "Audit it", "main")["key"]
        self.assertNotEqual(again, first)
        self.assertEqual(len(self.jobs()), 3)
        with self.assertRaises(ValueError):
            self.hub.queue_job("nowhere", "x", "main")

    def test_a_duplicate_ignores_the_prompts_surrounding_whitespace(self):
        first = self.hub.queue_job("repo", "Audit it", "main")["key"]
        with self.assertRaises(ValueError) as e:
            self.hub.queue_job("repo", "  Audit it\n\n", "main")
        self.assertIn(first, str(e.exception))

    def test_a_job_for_a_checkout_path_runs_in_it_with_a_shared_run_folder(self):
        loose = self.root / "loose"
        make_repo(loose)
        key = self.hub.queue_job(str(loose), "Tidy the readme", "main", None, "tidy")["key"]
        self.resume()
        self.until(lambda: self.state_of(key) == "done")
        item = self.items()[key]
        folder = Path(item["run"])
        self.assertEqual((folder.parent, folder.name.endswith("-tidy")), (self.vault / "wayfinder/runs", True))
        self.assertEqual((item["repo"], self.launched[0]["repo"]), (str(loose), str(loose)))
        self.assertEqual(Path(item["result"]).read_text(encoding="utf-8").strip(), "did: Tidy the readme")
        plain = self.root / "plain"
        plain.mkdir()
        for bad in (str(plain), str(self.root / "missing"), "relative/path"):
            with self.assertRaises(ValueError):
                self.hub.queue_job(bad, "x", "main")

    def test_a_night_past_its_stop_time_drops_it_so_the_next_days_items_run(self):
        self.tick_all()
        self.hub.queue_options(START + 60, False, self.hub.state()["queue"]["version"])
        self.resume()
        self.clock.t = START + 120
        self.sup.tick()
        q = self.hub.state()["queue"]
        self.assertEqual({i["state"] for i in q["items"]}, {"skipped"})
        self.assertIsNone(q.get("stop_at"))
        self.clock.t = START + 86400
        key = self.hub.queue_job("repo", "Audit it", "main")["key"]
        self.until(lambda: self.state_of(key) == "done")

    def test_a_stop_time_is_kept_while_a_worker_still_runs(self):
        self.mode = "hang"
        self.hub.queue_options(START + 60, False, self.hub.state()["queue"]["version"])
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "running")
        self.clock.t = START + 120
        self.sup.tick()
        self.assertEqual(self.hub.state()["queue"]["stop_at"], START + 60)
        self.assertEqual(self.state_of("repo/one#1"), "running")

    def test_a_limited_agent_requeues_the_job_until_its_reset(self):
        self.mode = "limit"
        key = self.hub.queue_job("repo", "Audit it", "main", "sonnet", "audit")["key"]
        self.resume()
        self.until(lambda: self.hub.state()["installed"]["main"]["limited_until"])
        reset = datetime(2026, 11, 13, 4, 40).timestamp()
        self.assertEqual(self.state_of(key), "queued")
        for _ in range(3):
            self.sup.tick()
        tries = [x for x in self.launched if x["key"] == key]
        self.assertEqual(len(tries), 1)
        self.clock.t = reset + 1
        self.mode = "job"
        self.until(lambda: self.state_of(key) == "done")
        tries = [x for x in self.launched if x["key"] == key]
        self.assertEqual(len(tries), 2)
        self.assertEqual(Path(tries[0]["log"]), Path(tries[1]["log"]))
        self.assertEqual(Path(self.items()[key]["result"]).read_text(encoding="utf-8").strip(), "did: Audit it")

    def test_a_failed_job_is_failed_without_a_retry(self):
        self.mode = "nothing"
        key = self.hub.queue_job("repo", "Audit it", "main", "sonnet")["key"]
        self.resume()
        self.until(lambda: self.state_of(key) == "failed")
        self.assertEqual([x["key"] for x in self.launched].count(key), 1)


class LaunchAndHookTest(RunnerCase):
    def test_launch_starts_agy_in_its_own_group_with_its_model(self):
        log = self.root / "agy.log"
        p = sbhub.launch({"kind": "agy", "dir": None, "model": "gemini-x"}, "Ticket: m/001\n", str(self.repos["repo/one"]),
                         "gemini-x", {"SB_HUB_AGENT": "m#1", "SB_HUB_PARENT": "queue", "SB_HUB_PORT": "1",
                                      "FAKE_WORKER_MODE": "nothing"}, str(log))
        self.assertEqual(os.getpgid(p.pid), p.pid)
        self.assertEqual(p.wait(timeout=10), 1)
        self.assertIn('argv: ["--model", "gemini-x", "--output-format", "json"]', log.read_text(encoding="utf-8"))

    def test_serve_finds_the_agents_runs_the_queue_and_kills_its_workers_when_stopped(self):
        cfg = self.root / "home" / ".claude-x"
        cfg.mkdir()
        (cfg / ".credentials.json").write_text("{}")
        port = free_port()
        env = {**os.environ, "SB_HUB_HOME": str(self.root / "served"), "FAKE_WORKER_MODE": "hang"}
        env.pop("SB_HUB_QUEUE", None)
        p = subprocess.Popen([sys.executable, SCRIPT, "serve", "--port", str(port)], stdout=subprocess.PIPE,
                             text=True, env=env)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        self.assertEqual(p.stdout.readline().strip(), "sb hub on http://127.0.0.1:{}".format(port))
        r = subprocess.run([sys.executable, SCRIPT, "queue", "add", "repo/one", "1", "--port", str(port)],
                           capture_output=True, text=True, env=env, timeout=70)  # nothing is ticked on its own
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, SCRIPT, "queue", "resume", "--port", str(port)], capture_output=True,
                           text=True, env=env, timeout=30)  # a new queue waits for this
        self.assertEqual(r.returncode, 0, r.stderr)
        leader, child = self.pids()
        state = json.loads(subprocess.run([sys.executable, SCRIPT, "state", "--port", str(port)], capture_output=True,
                                          text=True, env=env, timeout=20).stdout)
        self.assertEqual((sorted(state["installed"]), state["queue"]["agent"]), (["agy", "x"], "x"))  # never agy
        item = state["queue"]["items"][0]
        self.assertEqual((item["key"], item["state"], item["runner"]), ("repo/one#1", "running", "x"))
        self.assertIn('"SB_HUB_PORT": "{}"'.format(port), Path(item["log"]).read_text(encoding="utf-8"))
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=15)
        end = time.time() + 5
        while (alive(leader) or alive(child)) and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(alive(leader) or alive(child))

    def test_the_hook_reports_a_hub_worker_under_its_ticket(self):
        self.tick_all()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), sbhub.make_handler(self.hub))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = str(server.server_address[1])
        env = {**os.environ, "SB_HUB_AGENT": "repo/one#1", "SB_HUB_PARENT": "queue", "SB_HUB_PORT": port}
        e = {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "/w/p", "tool_name": "Bash",
             "tool_input": {"command": "python3 sbhub.py report --agent other"}}  # its alias is dropped too
        r = subprocess.run([sys.executable, SCRIPT, "hook"], input=json.dumps(e), capture_output=True, text=True,
                           env=env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        agents = self.hub.state()["agents"]
        self.assertEqual(list(agents), ["repo/one#1"])
        row = agents["repo/one#1"]
        self.assertEqual((row["role"], row["parent"], row["ticket"], row["state"]), ("worker", "queue", "A", "working"))


if __name__ == "__main__":
    unittest.main()
