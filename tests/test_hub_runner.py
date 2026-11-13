"""The hub runs the queue: Supervisor.tick() by hand, a real temp vault through sbmap, temp git repos,
and tests/fake_worker.py standing in for `claude -p` (a `claude` on PATH that runs it). Never a model,
never port 8765, ~/.sb-hub, the owner's vault or the real ~/.claude*."""
import http.server
import json
import os
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
from sbhub import Hub, Supervisor  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_worker.py"
START = datetime(2026, 11, 13, 1, 0).timestamp()  # 01:00 local: the limit's 4:40am is later the same night


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
        """One vault (maps and tickets made through sbmap), repos and fake `claude`/`agy` per class; each
        test copies them: building them is most of a test's time."""
        cls._template = tempfile.TemporaryDirectory()
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

    @classmethod
    def tearDownClass(cls):
        cls._template.cleanup()

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
        for k in ("SB_HUB_PORT", "SB_HUB_AGENT", "SB_HUB_PARENT", "FAKE_WORKER_MODE", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(k, None)
        self.repos = {folder: self.root / repo for folder, repo, *_ in self.MAPS}
        self.clock = Clock(START)
        self.mode, self.modes, self.launched = "commit", {}, []
        self.hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        with self.hub._lock:
            self.hub._data["installed"] = {n: {"kind": "claude", "dir": str(self.root / (".claude-" + n)), "model": None,
                                               "limited_until": None} for n in ("main", "spare")}
            self.hub._data["queue"]["agent"] = "main"
        self.sup = Supervisor(self.hub, port=4321)
        self.addCleanup(self.sup.stop)

    def sb(self, *a, ok=True):
        r = subprocess.run([sys.executable, str(SBMAP), *a], capture_output=True, text=True, cwd=self.vault)
        if ok:
            self.assertEqual(r.returncode, 0, "sbmap {}\n{}{}".format(" ".join(a), r.stdout, r.stderr))
        return r

    def launcher(self, agent, brief, repo, model, env, log):
        key = env["SB_HUB_AGENT"]
        self.launched.append({"key": key, "model": model, "brief": brief, "agent": agent, "log": log})
        return sbhub.launch(agent, brief, repo, model, {**env, "FAKE_WORKER_MODE": self.modes.get(key, self.mode)}, log)

    # ---- reading the result ----

    def items(self):
        return {i["key"]: i for i in self.hub.state()["queue"]["items"]}

    def open_tickets(self, folder="repo/one"):
        rows = json.loads(self.sb("tickets", "--json").stdout)
        return {r["num"]: r for r in rows if r["map"] == folder}

    def until(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            self.sup.tick()
            got = cond()
            if got:
                return got
            time.sleep(0.03)
        self.fail("timed out; queue: {}".format(json.dumps(self.hub.state()["queue"], indent=1)))

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
    def test_a_commit_in_its_paths_resolves_the_ticket_and_the_next_one_starts(self):
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
        self.assertIn('argv: ["--permission-mode", "auto", "--model", "sonnet", "--output-format", "json"]', log)
        self.assertIn('"CLAUDE_CONFIG_DIR": "{}"'.format(self.root / ".claude-main"), log)
        self.assertIn('"SB_HUB_AGENT": "repo/one#1", "SB_HUB_PARENT": "queue", "SB_HUB_PORT": "4321"', log)
        self.assertIn("cwd: " + str(self.repos["repo/one"]), log)
        self.assertEqual(Path(self.launched[0]["log"]).name, "1.log")
        self.assertIn("Ticket: repo/one/001", self.launched[0]["brief"])
        # the night's digest, once the last ticket ended
        board = self.board()
        self.assertIn("A: done, commit " + sha[:9], board)
        self.assertIn("B: done, commit", board)

    def test_a_commit_outside_its_paths_fails_leaves_the_commit_and_the_next_ticket_runs(self):
        self.sb("set", "repo/one", "001", "tier=opus", "--no-sync")
        self.modes = {"repo/one#1": "stray"}
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        item = self.items()["repo/one#1"]
        self.assertIn("stray.txt", item["note"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertIn("stray.txt", self.sb("show", "repo/one", "001").stdout + self.ticket_text(1))
        self.assertIn("Ticket: repo/one/001", git(self.repos["repo/one"], "log", "--format=%B"))
        self.until(lambda: self.state_of("repo/one#2") == "done")

    def test_a_failing_check_leaves_the_ticket_open_with_its_commit_in_place(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=test -f nope.txt", "--no-sync")
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

    def test_no_commit_on_sonnet_retries_once_on_opus_then_fails(self):
        self.modes = {"repo/one#1": "nothing", "repo/one#2": "hang"}
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


class StopsTest(RunnerCase):
    def test_a_usage_limit_waits_for_the_reset_and_releases_the_claim(self):
        self.mode = "limit"
        self.until(lambda: self.hub.state()["installed"]["main"]["limited_until"])
        reset = datetime(2026, 11, 13, 4, 40).timestamp()
        self.assertEqual(self.hub.state()["installed"]["main"]["limited_until"], reset)
        self.assertEqual((self.state_of("repo/one#1"), self.state_of("repo/one#2")), ("queued", "queued"))
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        for _ in range(3):
            self.sup.tick()
        self.assertEqual(len(self.launched), 1)
        self.clock.t = reset + 1
        self.mode = "hang"
        self.sup.tick()
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1", "repo/one#1"])
        self.assertEqual(self.state_of("repo/one#1"), "running")

    def test_a_worker_past_its_time_limit_has_its_whole_group_killed(self):
        self.sup.limit = 1
        self.sb("set", "repo/one", "001", "tier=opus", "--no-sync")
        self.mode = "hang"
        self.sup.tick()
        leader, child = self.pids()
        self.clock.t += 2
        self.sup.tick()
        item = self.items()["repo/one#1"]
        self.assertEqual(item["state"], "failed")
        self.assertIn("ran past", item["note"])
        end = time.time() + 5
        while (alive(leader) or alive(child)) and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(alive(leader) or alive(child))
        self.assertEqual(self.open_tickets()[1]["status"], "open")

    def test_three_failures_with_no_commit_pause_the_queue(self):
        self.sb("new", "repo/one", "--title", "C", "--why", "Because.", "--done-when", "It works.", "--no-sync")
        for n in ("001", "002", "003"):
            self.sb("set", "repo/one", n, "tier=opus", "--no-sync")
        self.mode = "nothing"
        self.until(lambda: self.hub.state()["queue"]["paused"])
        q = self.hub.state()["queue"]
        self.assertEqual([i["state"] for i in q["items"]], ["failed"] * 3)
        self.assertIn("no commit", q["note"])

    def test_a_ticket_resolved_or_claimed_while_queued_is_skipped_with_its_new_state(self):
        self.hub.tickets()  # seeds the queue
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
        self.hub.tickets()
        self.assertEqual(list(self.items()), ["repo/one#2"])
        self.sb("set", "repo/one", "001", "status=open", "--no-sync")
        self.sup.tick()
        self.assertEqual(self.state_of("repo/one#2"), "skipped")
        self.assertIn("blocked", self.items()["repo/one#2"]["note"])

    def test_a_restarted_hub_requeues_a_running_item_and_releases_its_claim(self):
        self.hub.tickets()
        self.sb("claim", "repo/one", "001", "--by", "hub main")
        with self.hub._lock:
            self.hub._data["queue"]["items"][0].update(state="running", started=START)
            self.hub._data["queue"]["paused"] = True
            self.hub._save()
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        self.addCleanup(sup.stop)
        sup.tick()
        self.assertEqual(hub.state()["queue"]["items"][0]["state"], "queued")
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertEqual(self.launched, [])

    def test_a_worker_that_outlived_its_hub_is_killed_before_its_ticket_is_queued_again(self):
        self.mode = "hang"
        self.sup.tick()
        leader, child = self.pids()
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)  # the hub died; a new one starts
        hub.queue_pause(True)
        sup = Supervisor(hub)
        self.addCleanup(sup.stop)
        sup.tick()
        self.assertEqual(hub.state()["queue"]["items"][0]["state"], "queued")
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        end = time.time() + 5
        while (alive(leader) or alive(child)) and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(alive(leader) or alive(child))

    def test_a_restart_never_releases_a_claim_a_session_holds(self):
        self.hub.tickets()
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
        self.hub.tickets()
        self.assertEqual(list(self.items()), ["repo/one#1", "repo/two#3", "repo/one#2"])
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
        self.hub.tickets()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), sbhub.make_handler(self.hub))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = str(server.server_address[1])
        env = {**os.environ, "SB_HUB_AGENT": "repo/one#1", "SB_HUB_PARENT": "queue", "SB_HUB_PORT": port}
        for e in ({"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/w/p"},
                  {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "/w/p", "tool_name": "Bash",
                   "tool_input": {"command": "python3 sbhub.py report --agent other"}}):
            r = subprocess.run([sys.executable, SCRIPT, "hook"], input=json.dumps(e), capture_output=True, text=True,
                               env=env, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
        agents = self.hub.state()["agents"]
        self.assertEqual(list(agents), ["repo/one#1"])
        row = agents["repo/one#1"]
        self.assertEqual((row["role"], row["parent"], row["ticket"], row["state"]), ("worker", "queue", "A", "working"))


if __name__ == "__main__":
    unittest.main()
