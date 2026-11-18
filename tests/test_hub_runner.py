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


def state_fixture(state, root, name):
    """Write a real /api/state answer, its temp paths, shas, times and pids made stable, as a contract fixture the
    hub's Vitest tests parse (packages/contract/fixtures/state/<name>)."""
    text = json.dumps(state, indent=1, sort_keys=True).replace(str(root), "/tmp/sb")
    text = re.sub(r"\b[0-9a-f]{40}\b", "0" * 40, text)
    text = re.sub(r"\b[0-9a-f]{9}\b", "0" * 9, text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}-", "2026-11-13-", text)
    text = re.sub(r'"(secs|pid|check_minutes|run_minutes)": [\d.e-]+', r'"\1": 0', text)
    # a worker's start time from ps: left live, every run of the tests edits this tracked fixture and a landing
    # that touches it then meets what looks like someone's unsaved edit
    text = re.sub(r'"pid_start": "[^"]+"', '"pid_start": "Mon Nov 16 10:05:45 2026"', text)
    text = re.sub(r"worktrees/[^/\"]+-[0-9a-f]{6}/", "worktrees/repoA-000000/", text)
    text = re.sub(r'"session": "[0-9a-f-]{36}"', '"session": "00000000-0000-0000-0000-000000000000"', text)
    fixture = Path(SCRIPT).resolve().parents[1] / "hub" / "packages" / "contract" / "fixtures" / "state" / name
    fixture.parent.mkdir(exist_ok=True)
    fixture.write_text(text + "\n", encoding="utf-8")


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
        for name in ("claude", "agy", "codex"):
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
        self.sessions = False  # True: each new Claude session leaves its file where Claude keeps it
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

    def launcher(self, agent, brief, repo, model, env, log, **kw):
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
        p = sbhub.launch(agent, brief, repo, model, {**env, **fake, **{k: v for k, v in os.environ.items() if k.startswith("FAKE_")}}, log, **kw)
        if self.sessions and p.session and not kw:  # as Claude does: a new session's file, under its config dir
            f = sbhub.session_file(agent["dir"], repo, p.session)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('{"type":"user"}\n', encoding="utf-8")
        return p

    # ---- reading the result ----

    def items(self):
        """Every item by key: the live line, and the items of nights that ended (they leave the line)."""
        out = {i["key"]: i for n in self.hub.nights()["nights"][::-1] for i in self.hub.night(n["id"])["night"]["items"]}
        out.update({i["key"]: i for i in self.hub.state()["queue"]["items"]})
        return out

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
        end = time.time() + 30  # 5 s ran out at load 35 (ticket 153's runs): a served hub starts its worker late
        while not (f.exists() and f.read_text().endswith("\n")) and time.time() < end:
            time.sleep(0.02)
        return tuple(map(int, f.read_text().split()))

    def state_of(self, key):
        return self.items().get(key, {}).get("state")

    def printed(self, log, n, what="argv"):
        """The first `n` tries' `argv` (lists) or `cwd` as the fake worker printed them, waiting for the n-th."""
        end = time.time() + 10
        while True:
            text = Path(log).read_text(encoding="utf-8")
            lines = [x[len(what) + 2:] for x in text.splitlines() if x.startswith(what + ": ")]
            if len(lines) >= n or time.time() > end:
                return [json.loads(x) for x in lines] if what == "argv" else lines
            time.sleep(0.02)

    def board(self, folder="repo/one"):
        boards = sorted(self.vault.glob("wayfinder/repo/runs/*/*.md"))
        return "\n".join(b.read_text(encoding="utf-8") for b in boards)


class UncleanCheckoutTest(RunnerCase):
    """A worktree ticket whose work cannot land because the owner's checkout holds unsaved changes to its files:
    it waits on its branch (not failed, its map going on), and lands on its own once they are saved or cleared."""
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "2")

    def wait_unclean(self):
        """Ticket A runs while the checkout holds an unsaved one/done.txt, the file its commit adds."""
        (self.repo / "one").mkdir(exist_ok=True)
        (self.repo / "one" / "done.txt").write_text("the owner's unsaved line\n")
        self.only(1)
        self.hub.queue_pause(False)
        self.until(lambda: self.state_of("repo/one#1") not in (None, "queued", "running"))
        return self.items()["repo/one#1"]

    def test_work_that_overlaps_unsaved_files_waits_for_a_clean_checkout_with_the_files_named(self):
        item = self.wait_unclean()
        self.assertEqual(item["state"], "unclean")
        self.assertEqual(item["blocking"], ["one/done.txt"])
        self.assertIn("waiting for a clean checkout", item["note"])
        self.assertIn("one/done.txt", item["note"])
        self.assertIn(item["branch"], item["note"])
        self.assertIn(item["branch"], git(self.repo, "branch", "--list", "sb/*"))  # its branch and worktree stay
        self.assertTrue(Path(item["tree"]).is_dir())
        self.assertEqual((self.repo / "one" / "done.txt").read_text(), "the owner's unsaved line\n")
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")  # not failed: the hub still holds it
        self.assertEqual(self.sup.streak, (None, 0))
        for _ in range(3):  # still unsaved: each pass looks and it keeps waiting
            self.sup.tick()
        self.assertEqual(self.state_of("repo/one#1"), "unclean")
        self.assertEqual(self.items()["repo/one#1"]["commit"], item["commit"])
        # the hub's own /api/state answer with the waiting item, for the contract's Vitest test to parse
        state_fixture(self.hub.state(), self.root, "unclean.json")

    def test_an_unstaged_edit_to_a_tracked_file_the_branch_changes_waits_with_its_whole_name(self):
        # git status says " M one/done.txt" for it: the leading space is part of the entry, not padding to strip
        (self.repo / "one").mkdir(exist_ok=True)
        (self.repo / "one" / "done.txt").write_text("base\n")
        git(self.repo, "add", "one/done.txt")
        git(self.repo, "commit", "-q", "-m", "base")
        (self.repo / "one" / "done.txt").write_text("base\nthe owner's unsaved line\n")
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True,
                                        text=True).stdout, " M one/done.txt\n")
        self.only(1)
        self.hub.queue_pause(False)
        self.until(lambda: self.state_of("repo/one#1") not in (None, "queued", "running"))
        item = self.items()["repo/one#1"]
        self.assertEqual(item["state"], "unclean", item.get("note"))
        self.assertEqual(item["blocking"], ["one/done.txt"])
        self.assertIn("one/done.txt", item["note"])
        self.assertEqual(self.sup.streak, (None, 0))
        (self.repo / "one" / "done.txt").write_text("base\n")  # the edit undone: the file matches HEAD again
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), item["commit"])
        self.assertIn("work for repo/one/001", (self.repo / "one" / "done.txt").read_text())

    def test_once_the_files_are_cleared_the_next_pass_lands_it_rebased_onto_the_moved_checkout(self):
        item = self.wait_unclean()
        self.assertEqual(item["state"], "unclean")
        (self.repo / "one" / "done.txt").unlink()  # cleared, and the owner committed something else meanwhile
        (self.repo / "owner.txt").write_text("owner\n")
        git(self.repo, "add", "owner.txt")
        git(self.repo, "commit", "-q", "-m", "owner")
        owner = git(self.repo, "rev-parse", "HEAD")
        self.until(lambda: self.state_of("repo/one#1") == "done")
        sha = self.items()["repo/one#1"]["commit"]
        self.assertNotEqual(sha, item["commit"])  # rebased onto the owner's commit
        self.assertEqual(git(self.repo, "rev-parse", sha + "^"), owner)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), sha)
        self.assertIn("work for repo/one/001", (self.repo / "one" / "done.txt").read_text())
        self.assertEqual(git(self.repo, "branch", "--list", "sb/*"), "")
        self.assertNotIn(1, self.open_tickets())

    def test_a_saved_edit_lands_it_without_a_rebase_when_the_checkout_did_not_move(self):
        item = self.wait_unclean()
        (self.repo / "one" / "done.txt").unlink()
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(self.items()["repo/one#1"]["commit"], item["commit"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), item["commit"])

    def test_a_later_ticket_of_its_map_that_touches_other_files_still_runs_and_lands(self):
        item = self.wait_unclean()
        self.assertEqual(item["state"], "unclean")
        self.hub.queue_set(["repo/one#1", "repo/one#2"], self.hub.state()["queue"]["version"])
        self.until(lambda: self.state_of("repo/one#2") == "done")
        self.assertIn("work for repo/one/002", (self.repo / "two" / "done.txt").read_text())
        self.assertEqual(self.state_of("repo/one#1"), "unclean")  # it still waits for its file
        self.assertFalse(self.hub.state()["queue"]["paused"])

    def test_unsaved_names_each_kind_of_change_whole_from_git_status(self):
        for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
            (self.repo / name).write_text(name + "\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "files")
        (self.repo / "a.txt").write_text("changed\n")  # " M", first in the list: its leading space must stay
        (self.repo / "b.txt").write_text("staged\n")
        git(self.repo, "add", "b.txt")  # "M "
        git(self.repo, "mv", "c.txt", "e.txt")  # "R ", with its old name after it
        (self.repo / "d.txt").unlink()  # " D"
        (self.repo / "f.txt").write_text("new\n")  # "??"
        self.assertEqual(sorted(sbhub.unsaved(self.repo)), ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt"])
        self.assertEqual(sbhub.unsaved(self.repo, ["a.txt"]), ["a.txt"])
        (self.repo / "a.txt").write_text("a.txt\n")
        self.assertEqual(sbhub.unsaved(self.repo, ["a.txt"]), [])

    def test_a_branch_that_no_longer_rebases_fails_for_the_owner_with_its_branch_kept(self):
        item = self.wait_unclean()
        git(self.repo, "add", "one/done.txt")  # the owner commits their own one/done.txt: the two clash
        git(self.repo, "commit", "-q", "-m", "owner")
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        got = self.items()["repo/one#1"]
        self.assertIn("could not land: its commits conflict", got["note"])
        self.assertIn("one/done.txt", got["note"])
        self.assertIn(item["branch"], got["note"])
        self.assertIn(item["branch"], git(self.repo, "branch", "--list", "sb/*"))
        self.assertEqual(git(Path(item["tree"]), "status", "--porcelain"), "")  # no rebase left half done
        self.assertEqual((self.repo / "one" / "done.txt").read_text(), "the owner's unsaved line\n")
        self.assertEqual(self.open_tickets()[1]["status"], "open")


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


class CodexTextTest(unittest.TestCase):
    def test_codex_names_its_wait_or_its_clock_time(self):
        self.assertEqual(sbhub.limited_until("You've hit your usage limit. Upgrade to Pro or try again in 1 day "
                                             "2 hours 5 minutes.", START), START + 86400 + 7200 + 300)
        self.assertEqual(sbhub.limited_until("You've hit your usage limit. Try again at 9:31 PM.", START),
                         datetime(2026, 11, 13, 21, 31).timestamp())
        self.assertIsNone(sbhub.limited_until("try again in 5 minutes", START))  # no limit named: no stop

    def test_codex_errors_are_what_it_said_and_tool_output_is_not(self):
        log = "\n".join(json.dumps(e) for e in (
            {"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "usage limit reached"}},
            {"type": "error", "message": "boom"},
            {"type": "turn.failed", "error": {"message": "401 Unauthorized"}},
            {"id": "0", "msg": {"type": "error", "message": "old"}}))
        said = sbhub._said(log)
        self.assertEqual(said.splitlines(), ["boom", "401 Unauthorized", "old"])
        self.assertTrue(sbhub.logged_out(said))

    def test_a_codex_jobs_result_is_its_last_agent_message(self):
        log = "\n".join(json.dumps(e) for e in (
            {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "done: wrote it"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1}}))
        self.assertEqual(sbhub._job_result(log), "done: wrote it")
        self.assertEqual(sbhub._job_result(json.dumps({"msg": {"type": "agent_message", "message": "old"}})), "old")


def codex_session(home, day, name, *limits, mtime=None):
    """A Codex session file under home/sessions/<day>/ with one token_count event per (five, week) used percent."""
    d = Path(home) / "sessions" / day
    d.mkdir(parents=True, exist_ok=True)
    f = d / "rollout-{}.jsonl".format(name)
    lines = [json.dumps({"type": "session_meta", "payload": {"id": name}})]
    for five, week in limits:
        lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": five, "window_minutes": 300, "resets_at": START + 3600},
            "secondary": {"used_percent": week, "window_minutes": 10080, "resets_at": START + 86400}}}}))
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mtime:
        os.utime(f, (mtime, mtime))
    return f


class CodexUsageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_the_newest_sessions_last_limits_are_the_reading(self):
        codex_session(self.home, "2026/11/12", "old", (90.0, 90.0), mtime=START - 86400)
        codex_session(self.home, "2026/11/13", "a", (3.0, 20.0), (4.0, 21.0), mtime=START - 60)
        codex_session(self.home, "2026/11/13", "b", mtime=START)  # just started: no limits yet
        self.assertEqual(sbhub.codex_usage(self.home), {"five_hour": 0.04, "five_hour_resets": START + 3600,
                                                        "seven_day": 0.21, "seven_day_resets": START + 86400})

    def test_no_sessions_no_reading(self):
        self.assertIsNone(sbhub.codex_usage(self.home))
        codex_session(self.home, "2026/11/13", "a")
        self.assertIsNone(sbhub.codex_usage(self.home))


class CodexRunTest(RunnerCase):
    """A Codex account in the pool takes tickets as a Claude account does; its limit and logout take it out."""

    def setUp(self):
        super().setUp()
        with self.hub._lock:
            self.hub._data["installed"] = {"codex": {"kind": "codex", "dir": str(self.root / ".codex"), "model": None,
                                                     "limited_until": None}}
            self.hub._data["queue"]["agent"] = "codex"

    def test_a_codex_accounts_use_is_read_from_its_sessions_while_the_queue_is_paused(self):
        codex_session(self.root / ".codex", "2026/11/13", "a", (4.0, 21.0))
        self.sup.tick()
        u = self.hub.state()["installed"]["codex"]["usage"]
        self.assertEqual((u["five_hour"], u["seven_day"], u["at"]), (0.04, 0.21, START))
        codex_session(self.root / ".codex", "2026/11/13", "a", (9.0, 22.0))
        self.sup.tick()
        self.assertEqual(self.hub.state()["installed"]["codex"]["usage"]["five_hour"], 0.04)  # once per USAGE_STALE
        self.clock.t += sbhub.USAGE_STALE
        self.sup.tick()
        self.assertEqual(self.hub.state()["installed"]["codex"]["usage"]["five_hour"], 0.09)

    def test_codex_usage_is_off_with_sb_hub_codex_usage_0(self):
        codex_session(self.root / ".codex", "2026/11/13", "a", (4.0, 21.0))
        with mock.patch.dict(os.environ, {"SB_HUB_CODEX_USAGE": "0"}):
            sup = Supervisor(self.hub, port=4321)
        self.addCleanup(sup.stop)
        self.assertFalse(sup.codex_usage)
        self.sup.codex_usage = False
        self.sup.tick()
        self.assertNotIn("usage", self.hub.state()["installed"]["codex"])

    def test_a_ticket_runs_on_codex_exec_under_its_account_and_resolves(self):
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item, log = self.items()["repo/one#1"], self.launched[0]["log"]
        argv = self.printed(log, 1)[0]
        self.assertEqual(argv[:4], ["--json", "-C", str(self.repos["repo/one"]), "--skip-git-repo-check"])
        self.assertNotIn("-m", argv)  # no model named: the account's own default, never sonnet
        self.assertEqual(argv[argv.index("-s") + 1], "workspace-write")
        roots = json.loads(next(a for a in argv if a.startswith("sandbox_workspace_write.writable_roots=")).split("=", 1)[1])
        self.assertIn(str(self.repos["repo/one"] / ".git"), roots)
        self.assertIsNone(item.get("session"))
        self.assertEqual(json.loads(self.printed(log, 1, "env")[0])["CODEX_HOME"], str(self.root / ".codex"))
        self.assertEqual(self.open_tickets(), {2: self.open_tickets()[2]})

    def test_a_codex_usage_limit_takes_the_account_out_until_the_wait_it_names(self):
        self.mode = "limit"
        self.only(1)
        self.until(lambda: self.hub.state()["installed"]["codex"]["limited_until"])
        self.assertEqual(self.hub.state()["installed"]["codex"]["limited_until"], START + 86400 + 7200 + 300)
        self.assertEqual(self.state_of("repo/one#1"), "queued")
        self.assertEqual(self.open_tickets()[1]["status"], "open")

    def test_a_signed_out_codex_account_is_marked_and_its_ticket_waits(self):
        self.mode = "auth"
        self.only(1)
        self.until(lambda: self.hub.state()["installed"]["codex"].get("login") == "expired")
        self.assertEqual(self.state_of("repo/one#1"), "queued")
        self.assertEqual(len(self.launched), 1)

    def test_failed_tries_on_codex_come_back_with_no_model_never_sonnet_or_opus(self):
        script = self.root / "fails.sh"  # exits 1 twice, then 0
        script.write_text('n=$(cat "{c}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{c}"; [ $n -le 2 ] && exit 1; '
                          'exit 0\n'.format(c=self.root / "fails"))
        self.sb("set", "repo/one", "001", "checks=sh " + str(script), "--no-sync")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        runs = [x for x in self.launched if x["key"] == "repo/one#1"]
        self.assertEqual([x["model"] for x in runs], [None, None, None])
        self.assertNotIn("-m", self.printed(runs[2]["log"], 3)[2])


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
        self.assertRegex(log, r'argv: \["--session-id", "[0-9a-f-]{36}", "--permission-mode", "auto", "--model", "sonnet", '
                              r'"--settings", ')  # its own session; the git guard hook
        self.assertIn('"--output-format", "stream-json", "--verbose", "--setting-sources", "project,local", "--strict-mcp-config"', log)
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

    def test_no_commit_three_times_tries_twice_on_sonnet_then_opus_then_waits_for_you_with_every_reason(self):
        self.modes = {"repo/one#1": "nothing", "repo/one#2": "hang"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        runs = [x for x in self.launched if x["key"] == "repo/one#1"]
        self.assertEqual([x["model"] for x in runs], ["sonnet", "sonnet", "opus"])  # tries 1-2 on its tier, 3 on opus
        self.assertNotIn("no commit", runs[0]["brief"])
        self.assertIn("## This is try 2 of 5", runs[1]["brief"])
        self.assertIn("- try 1 (sonnet): no commit", runs[1]["brief"])
        self.assertIn("- try 2 (sonnet): no commit", runs[2]["brief"])
        self.assertIn('"--model", "opus"', Path(runs[2]["log"]).read_text(encoding="utf-8"))
        item = self.items()["repo/one#1"]
        self.assertEqual((item["tries"], len(item["fails"])), (3, 3))
        self.assertIn("the same failure 3 tries in a row with no new commit", item["note"])
        self.assertIn("try 3 (opus): no commit", item["note"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertIn("no commit", self.ticket_text(1))

    def ticket_text(self, num, folder="repo/one"):
        f = next((self.vault / "wayfinder" / folder / "issues").glob("{:03d}*.md".format(num)))
        return f.read_text(encoding="utf-8")


class SpendTest(RunnerCase):
    """A ticket's note says what it cost (sbmap spend), written when the hub ends the item."""

    def props(self, num=1, folder="repo/one"):
        f = next((self.vault / "wayfinder" / folder / "issues").glob("**/{:03d}*.md".format(num)))
        head = f.read_text(encoding="utf-8").split("---")[1]
        return dict(l.split(": ", 1) for l in head.splitlines() if ": " in l)

    def line(self, i, o, c, cost):
        return json.dumps({"type": "result", "is_error": False, "modelUsage": {"claude-opus-5-5": {
            "inputTokens": i, "outputTokens": o, "cacheReadInputTokens": c, "costUSD": cost}}}) + "\n"

    def test_two_tries_of_one_log_add_up_on_the_note_and_a_second_run_adds_again(self):
        key, log = "repo/one#1", self.root / "w.log"
        first = self.line(10, 20, 30, 1.5)
        log.write_text(first + "noise\n" + self.line(1, 2, 3, 0.25), encoding="utf-8")
        got = sbhub.log_spend(str(log))
        self.assertEqual(got, {"tokens_in": 11, "tokens_out": 22, "cache_read": 33, "cost_usd": 1.75})
        self.hub.queue_set([key], self.hub.state()["queue"]["version"])
        with self.hub._lock:
            item = self.hub._data["queue"]["items"][0]
            item.update(started=self.clock(), night="n1", model="opus", runner="main")
        q = self.sup
        item = dict(item)
        for start, mins in ((0, 10), (len(first), 30)):  # the second try's output begins after the first's
            item["started"] = self.clock() - mins * 60
            q._add_spend(item, {"log": str(log), "start": start, "agent": "spare" if start else "main"},
                         {"checks": [{"secs": 60}]})
        q._note_spend(key, "done")
        p = self.props()
        self.assertEqual((p["run_minutes"], p["check_minutes"], p["tries"]), ("40", "2", "2"))
        self.assertEqual((p["tokens_in"], p["tokens_out"], p["cache_read"], p["cost_usd"]), ("12", "24", "36", "2"))  # try 1 read both lines, try 2 the last
        self.assertEqual((p["model"], p["account"], p["night"], p["outcome"]), ("opus", "spare", "n1", "done"))
        self.assertNotIn("spend", self.items()[key])
        self.sb("spend", "repo/one", "1", "run_minutes=5", "tries=1", "outcome=failed")  # a run again adds
        p = self.props()
        self.assertEqual((p["run_minutes"], p["tries"], p["tokens_in"], p["outcome"]), ("45", "3", "12", "failed"))

    def test_a_ticket_with_no_usage_in_its_log_gets_the_times_and_no_tokens(self):
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") in ("done", "failed"))
        p = self.props()
        self.assertEqual((p["tries"], p["outcome"], p["account"], p["model"]), ("1", "done", "main", "sonnet"))
        self.assertIn("run_minutes", p)
        self.assertIn("check_minutes", p)
        for k in ("tokens_in", "tokens_out", "cache_read", "cost_usd"):
            self.assertNotIn(k, p)


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
        self.assertIn("review: met\n", done)  # the verdict and the review are properties a board shows
        self.assertIn("review_note: ", done)
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
            self.assertIn("review: {}\n".format(verdict), text)
            first = item["redo"]["commit"]
            self.assertIn("Both tries' commits, {} and {}, are left where they landed.".format(first[:9], sha[:9]), text)
            log = git(self.repos["repo/one"], "log", "--format=%H")
            self.assertIn(sha, log)  # the commits stay
            self.assertIn(first, log)
            self.assertEqual(item["review"], str(Path(item["run"]) / "{}-review.md".format(num)))
        self.assertIn("A: failed, judged partly by the Opus review", self.board())
        self.assertEqual(self.items()["repo/one#2"]["note"].count("not met"), 2)  # the verdict, and the item

    def test_a_night_that_ends_closes_the_maps_it_finished(self):
        self.sup.close_off = True  # the morning housekeeping, which closing finished maps is part of
        self.only(1, 2)
        self.until(lambda: (self.vault / "wayfinder/repo/archive/one/report.md").is_file())
        report = (self.vault / "wayfinder/repo/archive/one/report.md").read_text(encoding="utf-8")
        self.assertIn("Closed on its own on ", report)
        self.assertIn("2 tickets resolved", report)

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

    def own_rebuild(self):
        """This repo is the one the hub runs from; its build and restart are fakes that note their calls."""
        self.calls = []
        repo = os.path.realpath(str(self.repos["repo/one"]))
        rb = sbhub.Rebuild(self.hub, root=repo, build=lambda: (self.calls.append("build"), (True, ""))[1],
                           restart=lambda: (self.calls.append("restart"), (True, ""))[1])
        self.sup.runner.rebuild = rb
        return rb, repo

    def test_no_review_starts_while_a_restart_is_pending_for_the_repo_and_one_starts_once_it_is_done(self):
        rb, repo = self.own_rebuild()
        rb.pending[repo] = "restart"
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "landed")
        for _ in range(5):
            self.sup.tick()
            time.sleep(0.05)
        self.assertEqual((self.state_of("repo/one#1"), self.reviewed), ("landed", []))
        rb.pending.clear()  # the restart is done
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(len(self.reviewed), 1)

    def test_a_review_template_naming_a_field_the_hub_cannot_fill_asks_for_one_restart_not_a_recheck(self):
        rb, repo = self.own_rebuild()
        real, tries = self.sup.runner.review_start, []

        def review_start(entries):
            tries.append(1)
            if len(tries) == 1:
                raise KeyError("review-brief.md names diff_max, which the hub cannot fill")
            return real(entries)
        self.sup.runner.review_start = review_start
        self.only(1)
        self.until(lambda: self.calls == ["build", "restart"])
        self.assertNotEqual(self.state_of("repo/one#1"), "recheck")
        self.until(lambda: self.state_of("repo/one#1") == "done")  # the restarted hub's review
        self.assertEqual((self.calls, len(tries)), (["build", "restart"], 2))

    def test_the_same_unfillable_template_after_the_restart_falls_back_to_the_recheck(self):
        # the restarted hub is a new process: what was asked is kept in the hub's home, so no restart loop
        _, repo = self.own_rebuild()
        err = "review-brief.md names diff_max, which the hub cannot fill"
        self.assertTrue(self.sup._restart_once(repo, err))
        self.assertFalse(self.sup._restart_once(repo, err))
        again = Supervisor(self.hub, port=4321)
        self.assertFalse(again._restart_once(repo, err))
        self.assertTrue(again._restart_once(repo, err.replace("diff_max", "lines")))  # a new field: one more

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
        def one():  # judged: the night ended and the item is on its record
            return next((i for i in hub.state()["queue"]["items"] if i.get("night")), None) or hub.night(hub.nights()["nights"][0]["id"])["night"]["items"][0]
        end = time.time() + 60
        while time.time() < end and one()["state"] != "done":
            sup.tick()
            time.sleep(0.03)
        item = one()
        self.assertEqual((item["state"], item["verdict"], item["commit"]), ("done", "finished", self.shas(1)[0]))
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1"]])
        self.assertNotIn(1, self.open_tickets())


class TimedReviewTest(RunnerCase):
    """A busy map's landed tickets get their review once the oldest waited review_every() (25 minutes), counted from
    `landed_at` in the queue file; the map-end review takes only the leftovers; POST /api/review/now starts the same
    review at once for every map with landed tickets, busy or not."""
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/"), ("C", "three/")),
            ("repo/two", "repoB", ("D", "four/"), ("E", "five/")))

    def landed_ago(self, minutes, *keys):
        """Back-date these tickets' landing, as if they landed `minutes` ago."""
        with self.hub._lock:
            for i in self.hub._data["queue"]["items"]:
                if i["key"] in keys:
                    self.assertEqual(i["state"], "landed")
                    i["landed_at"] = self.clock.t - minutes * 60
            self.hub._save()

    def restart(self):
        """The hub stops (its workers and reviews killed) and a new one loads the queue file the old one wrote."""
        self.sup.stop()
        self.hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        self.sup = Supervisor(self.hub, port=4321)
        self.sup.close_off = False
        self.addCleanup(self.sup.stop)

    def two_landed_and_one_running(self):
        self.only(1, 2, 3)
        self.until(lambda: [self.state_of("repo/one#{}".format(n)) for n in (1, 2, 3)] == ["landed", "landed", "running"])
        self.assertEqual(self.reviewed, [])

    def test_two_tickets_landed_26_minutes_ago_get_one_review_while_the_third_runs_and_it_alone_at_the_maps_end(self):
        self.modes = {"repo/one#3": "slow"}
        os.environ["FAKE_WORKER_SLEEP"] = "4"
        self.addCleanup(os.environ.pop, "FAKE_WORKER_SLEEP", None)
        self.two_landed_and_one_running()
        self.landed_ago(26, "repo/one#1", "repo/one#2")
        self.until(lambda: self.reviewed)
        self.assertEqual(self.state_of("repo/one#3"), "running")  # the map is still busy
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"]])
        self.until(lambda: self.state_of("repo/one#3") == "done")
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"], ["repo/one#3"]])
        self.assertEqual([self.state_of("repo/one#{}".format(n)) for n in (1, 2)], ["done", "done"])

    def test_a_ticket_landed_10_minutes_ago_waits_and_the_clock_counts_from_its_landing_across_a_restart(self):
        self.modes = {"repo/one#3": "hang"}
        self.two_landed_and_one_running()
        self.landed_ago(10, "repo/one#1", "repo/one#2")
        landed = self.items()["repo/one#1"]["landed_at"]
        for _ in range(5):
            self.sup.tick()
        self.assertEqual((self.reviewed, self.sup.reviews), ([], {}))  # 10 minutes: not yet
        self.assertEqual(self.hub.state()["review_next_at"], landed + 25 * 60)
        self.restart()  # the landing time is in the queue file: a restart does not reset the clock
        on_disk = json.loads((self.root / "hub" / "state.json").read_text(encoding="utf-8"))["queue"]["items"]
        self.assertEqual(next(i["landed_at"] for i in on_disk if i["key"] == "repo/one#1"), landed)
        self.until(lambda: self.state_of("repo/one#3") == "running")  # the worker the restart killed runs again
        for _ in range(5):
            self.sup.tick()
        self.assertEqual(self.reviewed, [])
        self.clock.t += 16 * 60  # 26 minutes since the landing, 16 since the restart
        self.until(lambda: self.reviewed)
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"]])
        self.assertEqual(self.hub.state()["review_next_at"], None)  # nothing landed waits outside the review

    def test_a_review_running_when_the_hub_restarts_is_started_once_by_the_new_hub(self):
        self.modes = {"repo/one#3": "hang"}
        self.verdicts = {"repo/one#1": "slow"}
        os.environ["FAKE_REVIEW_SLEEP"] = "30"
        self.addCleanup(os.environ.pop, "FAKE_REVIEW_SLEEP", None)
        self.two_landed_and_one_running()
        self.landed_ago(26, "repo/one#1", "repo/one#2")
        self.until(lambda: "repo/one" in self.sup.reviews)
        self.restart()  # the review was killed; its tickets stay `review` in the queue file
        self.assertEqual([self.state_of("repo/one#{}".format(n)) for n in (1, 2)], ["review", "review"])
        self.reviewed.clear()
        for _ in range(10):
            self.sup.tick()
            time.sleep(0.03)
        self.assertEqual([x["keys"] for x in self.reviewed], [["repo/one#1", "repo/one#2"]])  # once, not twice
        self.assertEqual(self.sup.review_now(), [])  # the owner's Review now takes nothing it holds

    def test_review_now_over_http_starts_both_busy_maps_from_the_queue_file_and_nothing_while_they_run(self):
        self.modes = {"repo/one#2": "hang", "repo/two#5": "hang"}
        self.verdicts = {"repo/one#1": "slow", "repo/two#4": "slow"}
        os.environ["FAKE_REVIEW_SLEEP"] = "30"
        self.addCleanup(os.environ.pop, "FAKE_REVIEW_SLEEP", None)
        self.hub.queue_set(["repo/one#1", "repo/one#2", "repo/two#4", "repo/two#5"], self.hub.state()["queue"]["version"])
        for key in ("repo/two#4", "repo/two#5"):  # one ticket per agent: the second map runs on the spare one
            self.hub.queue_item_agent(key, "spare")
        self.hub.queue_pause(False)
        want = {"repo/one#1": "landed", "repo/one#2": "running", "repo/two#4": "landed", "repo/two#5": "running"}
        self.until(lambda: {k: self.state_of(k) for k in want} == want)
        self.assertEqual(self.reviewed, [])  # both maps are busy and nothing waited 25 minutes
        self.restart()  # the new hub reads the queue file the running one wrote
        server = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), sbhub.make_handler(self.hub))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        self.assertEqual(sbhub.call(port, "/api/review/now", {}, timeout=70), (200, {"ok": True, "started": ["repo/one", "repo/two"]}))
        self.assertEqual(sorted(x["keys"] for x in self.reviewed), [["repo/one#1"], ["repo/two#4"]])
        self.assertEqual(sbhub.call(port, "/api/review/now", {}, timeout=70), (200, {"ok": True, "started": []}))  # they still run
        self.assertEqual(len(self.reviewed), 2)
        r = subprocess.run([sys.executable, str(SCRIPT), "review-now", "--port", str(port)], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, "review started: none\n"))


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

    def test_the_one_more_try_resumes_the_first_tries_session_told_the_findings(self):
        self.sessions, self.verdicts = True, {"repo/one#1": ["not met", "finished"]}
        self.only_one()
        self.until(lambda: len(self.runs()) == 2)
        first, again = self.runs()
        argvs = self.printed(first["log"], 2)
        self.assertEqual(argvs[1][argvs[1].index("--resume") + 1], argvs[0][argvs[0].index("--session-id") + 1])
        self.assertTrue(again["brief"].startswith("Your work landed and the Opus review read it."), again["brief"])
        self.assert_second_brief(again["brief"], self.shas(1)[0], "not met")

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


class PlayReviewTest(RunnerCase):
    """In Play lines (ticket 148): a Done-when item starting `In Play` is left by the worker and played by the map's
    review on main under the repo's Unity lock, which the hub takes for it and frees after; a lock busy past ten
    minutes starts the review without it, the lines are `not played yet`, and a ticket whose only open items are those
    resolves as landed, waiting for the owner's look, on the night's checklist note. The tickets are made through
    sbmap, so the hub reads their Done when as sbmap really writes it."""
    PLAY = "In Play: a dash then Rewind rolls the body back, the console clean."

    def setUp(self):
        super().setUp()
        self.sb("set", "repo/one", "001", "done_when=1. It works.\\n2. " + self.PLAY, "--no-sync")
        self.takes = []
        real = self.hub.lock

        def lock(key, by, **kw):
            self.takes.append((key, by))
            return real(key, by, **kw)
        self.hub.lock = lock

    def chat_holds_unity(self):
        """A chat session (a listed agent, so the hub never lets its lock go as orphaned) holds the Editor."""
        self.hub.report({"agent": "chat-unity", "role": "chat", "state": "working"})
        self.assertTrue(self.hub.lock("unity:repoA", "chat-unity")["ok"])
        self.takes.clear()

    def test_the_worker_brief_lists_the_in_play_line_as_played_by_the_review(self):
        self.assertEqual(self.open_tickets()[1]["done_when"], "1. It works.\n2. " + self.PLAY)  # what sbmap wrote
        self.only(1)
        self.until(lambda: self.launched)
        brief = self.launched[0]["brief"]
        self.assertIn(sbqueue.PLAY_BRIEF + "\n- " + self.PLAY + "\n", brief)
        self.assertIn("played by the review, leave it", brief.lower())

    def test_a_review_with_in_play_lines_takes_the_unity_lock_plays_them_and_frees_it(self):
        self.verdicts = {"repo/one#1": "slow"}
        os.environ["FAKE_REVIEW_SLEEP"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_REVIEW_SLEEP", None)
        self.only(1)
        self.until(lambda: "repo/one" in self.sup.reviews)
        held = self.hub.state()["locks"].get("unity:repoA")
        self.assertEqual((held or {}).get("by"), "sb-hub review repo/one")  # held while the review runs
        brief = self.reviewed[0]["brief"]
        self.assertIn("The hub took the repo's Unity lock `unity:repoA` for you", brief)
        self.assertIn("### Its In Play lines\n\n- " + self.PLAY, brief)
        item = self.items()["repo/one#1"]
        self.assertIn("Its screenshots go in: " + str(Path(item["run"]) / "1-media"), brief)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertNotIn("unity:repoA", self.hub.state()["locks"])  # freed once it ended
        self.assertEqual(self.takes, [("unity:repoA", "sb-hub review repo/one")])
        item = self.items()["repo/one#1"]
        self.assertEqual((item["verdict"], item.get("look")), ("finished", None))  # played and met: nothing to look at
        self.assertIn(self.PLAY + ": met: played on main", Path(item["review"]).read_text(encoding="utf-8"))

    def test_a_review_without_in_play_lines_never_takes_the_unity_lock(self):
        self.only(2)
        self.until(lambda: self.state_of("repo/one#2") == "done")
        self.assertEqual(len(self.reviewed), 1)
        self.assertEqual(self.takes, [])
        self.assertNotIn("Unity lock", self.reviewed[0]["brief"])
        self.assertNotIn("In Play", self.reviewed[0]["brief"])
        self.assertNotIn("Played by the review", self.launched[0]["brief"])

    def test_a_lock_busy_over_ten_minutes_starts_the_review_without_it_and_the_ticket_waits_for_your_look(self):
        self.chat_holds_unity()
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "landed")
        for secs in (0, 60, sbhub.REVIEW_LOCK_WAIT - 120):  # busy, under ten minutes: the review waits
            self.clock.t += secs
            self.sup.tick()
            self.hub.report({"agent": "chat-unity", "role": "chat", "state": "working"})
        self.assertEqual((self.reviewed, self.state_of("repo/one#1")), ([], "landed"))
        self.assertTrue(self.items()["repo/one#1"]["note"].startswith("waits for Unity to play its In Play lines"))
        self.clock.t += 121  # past ten minutes since it first found the lock busy
        self.until(lambda: self.state_of("repo/one#1") == "done")
        brief = self.reviewed[0]["brief"]
        self.assertIn("the repo's Unity lock `unity:repoA` has been held by chat-unity for over ten minutes", brief)
        self.assertIn("`not played yet`, never `not met`", brief)
        self.assertEqual(self.hub.state()["locks"]["unity:repoA"]["by"], "chat-unity")  # never taken from the chat
        self.assertTrue(all(by == "sb-hub review repo/one" for _, by in self.takes))
        item = self.items()["repo/one#1"]
        review = Path(item["review"]).read_text(encoding="utf-8")
        self.assertIn("- " + self.PLAY + ": not played yet", review)
        self.assertNotIn("not met", review)
        # landed, waits for your look: resolved, no redo, not failed, and on the night's one checklist
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1"])
        self.assertNotIn(1, self.open_tickets())
        self.assertIn(sbhub.LOOK, item["note"])
        note = Path(item["look"]["note"])
        self.assertEqual(note, Path(item["run"]).parent / "{}-validate.md".format(Path(item["run"]).name[:10]))
        self.assertEqual(item["look"]["lines"], ["- " + self.PLAY + ": not played yet: the Editor was not mine"])
        text = note.read_text(encoding="utf-8")
        self.assertIn("tags:\n  - wayfinder/run\n  - wayfinder/validate", text)
        self.assertIn("> [!summary] In plain words", text)
        done = next(self.vault.glob("wayfinder/repo/one/issues/done/001*.md"))
        rel = str(done.relative_to(self.vault))[:-3]
        self.assertIn("- [ ] **A**: a dash then Rewind rolls the body back, the console clean. [[{}|#1]]".format(rel),
                      text)
        self.assertTrue(done.is_file())  # the wikilink names the ticket's note where it now is
        self.assertIn(sbhub.LOOK, done.read_text(encoding="utf-8"))
        self.assertEqual(self.sup.streak, (None, 0))

    def test_a_partly_verdict_with_a_code_item_not_met_still_gets_its_one_more_try(self):
        self.chat_holds_unity()
        self.verdicts = {"repo/one#1": "partly"}
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "landed")
        self.sup.tick()
        self.clock.t += sbhub.REVIEW_LOCK_WAIT + 1
        self.hub.report({"agent": "chat-unity", "role": "chat", "state": "working"})
        self.until(lambda: len(self.launched) == 2)
        item = self.items()["repo/one#1"]
        self.assertEqual(item["redo"]["findings"], ["- It works.: not met: the fake reviewer found no test for it"])
        self.assertNotIn("look", item)
        self.assertFalse(list(Path(item["run"]).parent.glob("*-validate.md")))

    def test_a_restarted_hub_frees_a_review_lock_no_review_holds(self):
        self.hub.lock("unity:repoA", "sb-hub review repo/one")  # left by a hub that stopped while its review ran
        self.sup.review_now()
        self.assertNotIn("unity:repoA", self.hub.state()["locks"])


class NoCommandsTest(RunnerCase):
    """A ticket with a Done when and no check commands on any layer (ticket, map, repo .sb/checks) runs: the command
    step has nothing to run, and the Opus review (the fake reviewer's file, in review-brief.md's shape and read by
    sbqueue.review_verdict) is its only judge."""

    def setUp(self):
        super().setUp()
        self.sb("mapset", "repo/one", "checks=")
        rows = self.open_tickets()
        self.assertEqual([(rows[n]["checks"], rows[n]["checks_from"]) for n in (1, 2)], [([], "")] * 2)

    def test_it_is_ready_and_a_finished_review_resolves_it(self):
        self.assertEqual({t["num"]: t["state"] for t in self.hub.tickets() if t["map"] == "repo/one"},
                         {1: "ready", 2: "ready"})
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item = self.items()["repo/one#1"]
        self.assertEqual(item["verdict"], "finished")
        self.assertIn(sbqueue.NO_CHECKS_BRIEF, self.launched[0]["brief"])  # the worker is told the review judges it
        self.assertIn("no check commands: the Opus review", self.reviewed[0]["brief"])  # the hub's checks section
        done = next(self.vault.glob("wayfinder/repo/one/issues/done/001*.md")).read_text(encoding="utf-8")
        self.assertIn("it has no check commands, so the Opus review of its Done when was its only check", done)
        self.assertIn("review: met\n", done)

    def test_partly_and_not_met_fail_the_try_with_the_reviewers_not_met_line(self):
        self.verdicts = {"repo/one#1": "partly", "repo/one#2": "not met"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed" and self.state_of("repo/one#2") == "failed")
        line = "It works.: not met: the fake reviewer found no test for it"
        for num, verdict in ((1, "partly"), (2, "not met")):
            item = self.items()["repo/one#{}".format(num)]
            self.assertEqual(len([x for x in self.launched if x["key"] == item["key"]]), 2)  # the try failed: one more
            self.assertEqual(item["redo"]["findings"], ["- " + line])
            self.assertEqual(item["note"], "judged {} by the Opus review after its second try: {}".format(verdict, line))
            self.assertEqual(self.open_tickets()[num]["status"], "open")


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

    def stop_with_a_session(self):
        """Ticket 1 alone starts on main, a session whose file is kept as Claude keeps it, and stops at main's usage
        limit. Returns the session's id."""
        self.sessions, self.modes = True, {"repo/one#1": "limit"}
        self.only(1)
        self.until(lambda: self.launched)
        return self.items()["repo/one#1"]["session"]

    def test_a_launched_worker_runs_as_a_new_session_its_item_keeps(self):
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item, argv = self.items()["repo/one#1"], self.printed(self.launched[0]["log"], 1)[0]
        self.assertEqual(argv[argv.index("--session-id") + 1], item["session"])
        self.assertNotIn("--resume", argv)
        self.assertEqual(item["session_dir"], str(self.root / ".claude-main"))

    def test_a_usage_limit_resumes_its_session_on_a_free_account_in_the_same_tree(self):
        with self.hub._lock:
            self.hub._data["queue"]["agents"] = ["main", "spare"]
        sid = self.stop_with_a_session()
        self.until(lambda: len(self.launched) == 2)  # main is limited: spare takes it at once
        first, again = self.launched
        argv, cwd = self.printed(again["log"], 2)[1], self.printed(again["log"], 2, "cwd")
        self.assertEqual(again["agent"]["dir"], str(self.root / ".claude-spare"))
        self.assertEqual(argv[argv.index("--resume") + 1], sid)
        self.assertNotIn("--session-id", argv)
        self.assertEqual((again["model"], cwd[1]), (first["model"], cwd[0]))  # its model, in the same tree
        self.assertTrue(sbhub.session_file(self.root / ".claude-spare", cwd[0], sid).is_file())  # copied to spare
        self.assertTrue(again["brief"].startswith("This session stopped at its usage limit on main"), again["brief"])
        self.assertIn("  Ticket: repo/one/001\n", again["brief"])
        self.assertNotIn("Files you own", again["brief"])  # a short prompt, not the whole brief again

    def test_a_resume_that_fails_at_once_starts_afresh_told_the_old_log(self):
        sid = self.stop_with_a_session()
        self.until(lambda: self.items()["repo/one#1"].get("resume"))
        self.clock.t = datetime(2026, 11, 13, 4, 40).timestamp() + 1
        self.modes = {"repo/one#1": "nothing"}  # the resumed session ends with an error before any turn
        self.until(lambda: len(self.launched) == 2)
        self.modes = {}
        self.until(lambda: self.state_of("repo/one#1") == "done")
        item, argvs = self.items()["repo/one#1"], self.printed(self.launched[0]["log"], 3)
        self.assertEqual(argvs[1][argvs[1].index("--resume") + 1], sid)
        self.assertNotIn("--resume", argvs[2])
        self.assertNotEqual(argvs[2][argvs[2].index("--session-id") + 1], sid)
        fresh = self.launched[2]["brief"]
        self.assertIn("Files you own", fresh)
        self.assertIn("An earlier try on main stopped at its usage limit", fresh)
        self.assertIn(self.launched[0]["log"], fresh)
        self.assertEqual((item["stops"], item["tries"]), (1, 0))  # the failed resume is no stop and no failed try

    def test_a_session_too_old_missing_or_on_agy_is_not_resumed(self):
        d = self.root / ".claude-main"
        f = sbhub.session_file(d, self.root, "s1")
        f.parent.mkdir(parents=True)
        f.write_text("{}\n", encoding="utf-8")
        item, claude = {"session": "s1", "session_dir": str(d)}, {"kind": "claude", "dir": str(d)}
        self.assertEqual(sbhub.resumable(item, claude, self.root), "s1")
        self.assertIsNone(sbhub.resumable(item, claude, self.root, now=lambda: time.time() + sbhub.SESSION_DAY + 60))
        self.assertIsNone(sbhub.resumable({**item, "session": "s2"}, claude, self.root))
        self.assertIsNone(sbhub.resumable(item, {"kind": "agy", "dir": None}, self.root))

    def test_a_worker_past_its_time_limit_has_its_whole_group_killed_and_is_tried_again_then_waits_for_you(self):
        self.sup.limit = 1
        self.modes = {"repo/one#1": "hang", "repo/one#2": "nothing"}
        self.resume()
        self.sup.tick()
        groups = []
        for _ in range(sbhub.SAME_MAX):
            groups.append(self.pids())
            Path(os.environ["FAKE_WORKER_PIDS"]).unlink()
            self.clock.t += 2
            self.sup.tick()  # killed, then tried again at once
        runs = [x for x in self.launched if x["key"] == "repo/one#1"]
        self.assertEqual([x["model"] for x in runs], ["sonnet", "sonnet", "opus"])
        self.assertIn("ran past", runs[1]["brief"])
        item = self.items()["repo/one#1"]
        self.assertEqual(item["state"], "failed")  # the same failure three times, no commit: the owner looks
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
        self.assertEqual([i["state"] for i in self.items().values()], ["failed"] * 3)  # the night ended: its record
        self.assertIn("no commit", q["note"])

    def test_a_ticket_resolved_or_claimed_while_queued_is_skipped_with_its_new_state(self):
        self.resume()
        self.sb("resolve", "repo/one", "001", "--gist", "by hand", "--answer", "Done by hand.")
        self.sb("claim", "repo/one", "002", "--by", "a live session")
        self.sup.tick()
        items = self.items()
        self.assertEqual((items["repo/one#1"]["state"], items["repo/one#2"]["state"]), ("skipped", "skipped"))
        self.assertTrue(items["repo/one#1"]["note"].startswith("no longer open: resolved"), items["repo/one#1"]["note"])  # read from its closed note
        self.assertTrue(items["repo/one#1"].get("title"))  # the closed ticket keeps its name on the board
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
        def one():  # judged: the night ended and the item is on its record
            return next((i for i in hub.state()["queue"]["items"] if i.get("night")), None) or hub.night(hub.nights()["nights"][0]["id"])["night"]["items"][0]
        end = time.time() + 60  # as until(): 10 s ran out at load 30 (ticket 153's runs)
        while time.time() < end and one()["state"] in ("running", "landed", "review"):
            sup.tick()
            time.sleep(0.05)
        item = one()
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


class RetryTest(RunnerCase):
    """A failed try goes back to the queue from its kept work, up to five tries (3-5 on Opus), first when its map waits
    on it; the same failure three times with no new commit, or the fifth try, goes to the owner. Stops are no try."""
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/"), ("C", "three/")),)

    def failing_check(self, fails):
        """A check that exits 1 `fails` times, then 0."""
        script = self.root / "fails.sh"
        script.write_text('n=$(cat "{c}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{c}"; '
                          '[ $n -le {f} ] && exit 1; exit 0\n'.format(c=self.root / "fails", f=fails))
        return "sh " + str(script)

    def limit(self, name, until):
        with self.hub._lock:
            self.hub._data["installed"][name]["limited_until"] = until

    def runs(self, key):
        return [x for x in self.launched if x["key"] == key]

    def test_a_check_failing_twice_lands_on_the_third_try_on_opus_from_the_second_tries_work(self):
        self.sb("set", "repo/one", "001", "checks=" + self.failing_check(2), "--no-sync")
        self.sessions = True  # a failed try's session is kept, yet a retry starts a new one
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        runs = self.runs("repo/one#1")
        self.assertEqual([x["model"] for x in runs], ["sonnet", "sonnet", "opus"])
        item = self.items()["repo/one#1"]
        first, second = (f["commit"] for f in item["fails"])
        self.assertEqual([f["why"] for f in item["fails"]], ["check failed: " + self.failing_check(2)] * 2)
        self.assertNotEqual(first, second)
        self.assertEqual(item["base_sha"], second)  # the third try started on the second try's commit
        self.assertEqual(git(self.repos["repo/one"], "rev-parse", item["commit"] + "^"), second)
        self.assertEqual((self.repos["repo/one"] / "one" / "done.txt").read_text().count("work for"), 3)
        self.assertIn("## This is try 3 of 5", runs[2]["brief"])
        self.assertIn("- try 2 (sonnet): check failed", runs[2]["brief"])
        self.assertIn("commit " + second[:9], runs[2]["brief"])
        self.assertIn("go on from it", runs[2]["brief"])
        self.assertIn("Files you own", runs[2]["brief"])  # the whole brief: a new session
        self.assertIn("The last try's report: /r/1.md", sbhub.retry_brief({"retry": "x"}, None, None, "abc", "/r/1.md"))
        self.assertNotIn(1, self.open_tickets())

    def test_a_ticket_its_map_waits_on_is_tried_again_before_an_unrelated_ticket_of_its_repo(self):
        self.sb("block", "repo/one", "002", "1", "--no-sync")
        self.hub.queue_set(["repo/one#1", "repo/one#2", "repo/one#3"], self.hub.state()["queue"]["version"])
        self.hub.queue_item_agent("repo/one#1", "spare")
        self.modes = {"repo/one#1": "nothing"}
        self.hub.queue_pause(False)
        self.sup.tick()
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1"])
        self.limit("spare", START + 3600)  # its next try cannot start yet: main is free for the others
        self.until(lambda: self.items()["repo/one#1"].get("tries") == 1)
        for _ in range(3):
            self.sup.tick()
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1"])  # C waits though main is free
        self.assertEqual(self.state_of("repo/one#3"), "queued")
        self.assertIn("next try of repo/one#1", self.items()["repo/one#3"]["waits"]["text"])
        self.limit("spare", None)
        self.modes = {}
        self.until(lambda: {self.state_of("repo/one#2"), self.state_of("repo/one#3")} <= {"landed", "review", "done"})
        keys = [x["key"] for x in self.launched]
        self.assertEqual(keys[:2], ["repo/one#1", "repo/one#1"])  # its next try first, then the rest of its repo
        self.assertEqual(sorted(keys[2:]), ["repo/one#2", "repo/one#3"])

    def test_the_same_failure_three_times_with_no_new_commit_waits_for_you_and_the_map_goes_on(self):
        self.modes = {"repo/one#1": "nothing"}
        self.only(1, 3)
        self.until(lambda: self.state_of("repo/one#3") in ("landed", "review", "done"))
        item = self.items()["repo/one#1"]
        self.assertEqual(item["state"], "failed")
        self.assertEqual(len(self.runs("repo/one#1")), sbhub.SAME_MAX)
        self.assertEqual(len(item["fails"]), 3)
        self.assertIn("the same failure 3 tries in a row with no new commit", item["note"])
        for n in (1, 2, 3):
            self.assertIn("try {} (".format(n), item["note"])
        self.assertIn("work for repo/one/003", (self.repos["repo/one"] / "three" / "done.txt").read_text())
        self.assertFalse(self.hub.state()["queue"]["paused"])

    def test_the_fifth_failed_try_waits_for_you_even_with_new_commits(self):
        self.sb("set", "repo/one", "001", "checks=" + self.failing_check(99), "--no-sync")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        self.assertEqual([x["model"] for x in self.runs("repo/one#1")], ["sonnet", "sonnet", "opus", "opus", "opus"])
        self.assertIn("5 tries, the most it gets", self.items()["repo/one#1"]["note"])

    def test_a_usage_limit_stop_leaves_the_try_count_unchanged(self):
        self.modes = {"repo/one#1": "nothing"}
        self.only(1)
        self.sup.tick()
        self.modes = {"repo/one#1": "limit"}  # its second try hits the limit
        self.until(lambda: self.hub.state()["installed"]["main"]["limited_until"])
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["tries"], len(item["fails"]), item["stops"]), ("queued", 1, 1, 1))
        self.assertEqual([x["model"] for x in self.runs("repo/one#1")], ["sonnet", "sonnet"])
        self.limit("main", None)
        self.modes = {}
        self.until(lambda: self.state_of("repo/one#1") == "done")
        runs = self.runs("repo/one#1")
        self.assertEqual([x["model"] for x in runs], ["sonnet", "sonnet", "sonnet"])  # still try 2: not on opus
        self.assertIn("## This is try 2 of 5", runs[2]["brief"])

    def test_after_a_hub_restart_the_try_count_and_the_kept_work_survive(self):
        self.sb("set", "repo/one", "001", "checks=" + self.failing_check(1), "--no-sync")
        self.only(1)
        self.sup.tick()
        self.limit("main", START + 3600)  # the second try waits, so the hub restarts between the tries
        self.until(lambda: self.items()["repo/one#1"].get("tries") == 1)
        self.limit("main", None)
        self.hub._save()
        commit = self.items()["repo/one#1"]["fails"][0]["commit"]
        self.sup.stop()
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        with hub._lock:
            hub._data["installed"]["main"]["limited_until"] = None
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        item = next(i for i in hub.state()["queue"]["items"] if i["key"] == "repo/one#1")
        self.assertEqual((item["state"], item["tries"], item["fails"][0]["commit"]), ("queued", 1, commit))
        self.assertTrue(item["retry"].startswith("check failed"))
        def one():  # the live line's item, or the ended night's record of it
            return next((i for i in hub.state()["queue"]["items"] if i["key"] == "repo/one#1"), None) or next(
                i for i in hub.night(hub.nights()["nights"][0]["id"])["night"]["items"] if i["key"] == "repo/one#1")
        end = time.time() + 60
        while time.time() < end and one()["state"] not in ("done", "failed"):
            sup.tick()
            time.sleep(0.03)
        item = one()
        self.assertEqual(item["state"], "done")
        self.assertEqual(item["base_sha"], commit)  # the second try went on from the first try's commit
        self.assertIn("## This is try 2 of 5", self.runs("repo/one#1")[1]["brief"])


class OwnerStopTest(RunnerCase):
    """The page's Stop (POST /api/queue/stop): the worker's whole group ends within seconds, its work stays, the
    ticket says stopped by you with the reason and is unclaimed, and the queue moves on."""

    def gone(self, *pids, within=10):
        end = time.time() + within
        while any(map(alive, pids)) and time.time() < end:
            time.sleep(0.05)
        return not any(map(alive, pids))

    def ticket_text(self, num):
        return next(self.vault.glob("wayfinder/repo/one/issues/{:03d}*.md".format(num))).read_text(encoding="utf-8")

    def test_stop_kills_the_worker_and_its_child_keeps_its_work_and_the_next_ticket_starts(self):
        self.modes = {"repo/one#1": "hang"}
        self.resume()
        self.sup.tick()
        leader, child = self.pids()
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")
        repo = self.repos["repo/one"]
        (repo / "one").mkdir()
        (repo / "one" / "half.txt").write_text("half done\n")  # its work so far: left where it is
        (repo / "README.md").write_text("x\nedited\n")
        v = self.hub.state()["queue"]["version"]
        self.assertTrue(self.hub.queue_stop("repo/one#1", "  it edits the wrong checkout ", v)["ok"])
        self.assertEqual(self.items()["repo/one#1"]["note"], "stopping, by you: it edits the wrong checkout")
        t0 = time.time()
        self.sup.tick()
        self.assertTrue(self.gone(leader, child), "the worker or its child still runs")
        self.assertLess(time.time() - t0, 10)
        item = self.items()["repo/one#1"]
        self.assertEqual(item["state"], "skipped")
        self.assertTrue(item["note"].startswith("stopped by you: it edits the wrong checkout."), item["note"])
        self.assertEqual(item["stop_asked"]["reason"], "it edits the wrong checkout")
        self.assertIsNone(item["pid"])
        # its work is kept: nothing stashed, reset or deleted
        self.assertEqual((repo / "one" / "half.txt").read_text(), "half done\n")
        self.assertEqual((repo / "README.md").read_text(), "x\nedited\n")
        self.assertEqual(git(repo, "stash", "list"), "")
        # the ticket: unclaimed, with the reason and where the work is
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        text = self.ticket_text(1)
        self.assertIn("Stopped by you from the hub page: it edits the wrong checkout.", text)
        self.assertIn("README.md", text)
        self.assertIn("one/half.txt", text)
        # the queue moved on, and the stopped ticket never ran again, on any model
        self.until(lambda: self.state_of("repo/one#2") in ("running", "landed", "review", "done"))
        for _ in range(3):
            self.sup.tick()
        self.assertEqual([x["key"] for x in self.launched].count("repo/one#1"), 1)
        self.assertEqual(self.state_of("repo/one#1"), "skipped")
        self.assertFalse(self.hub.state()["queue"]["paused"])  # not a failure: no streak, no pause

    def test_a_stop_after_a_hub_restart_kills_the_worker_the_old_hub_started(self):
        self.mode = "hang"
        self.only(1)
        self.sup.tick()
        leader, child = self.pids()
        old = [r["p"] for r in self.sup.procs.values()]
        self.sup.procs.clear()  # the old hub died without killing it
        self.addCleanup(lambda: [p.wait(timeout=10) for p in old])  # reaped once the new hub's Stop killed it
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub, port=4321)
        sup.close_off = False
        self.addCleanup(sup.stop)
        sup.tick()
        self.assertEqual(hub.state()["queue"]["items"][0]["state"], "running")  # adopted, waited for
        self.assertTrue(alive(leader))
        self.assertTrue(hub.queue_stop("repo/one#1", "stuck", hub.state()["queue"]["version"])["ok"])
        sup.tick()
        self.assertTrue(self.gone(leader, child), "the worker or its child still runs")
        item = next(i for n in hub.nights()["nights"] for i in hub.night(n["id"])["night"]["items"]
                    if i["key"] == "repo/one#1")
        self.assertEqual(item["state"], "skipped")
        self.assertIn("stopped by you: stuck", item["note"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertIn("Stopped by you from the hub page: stuck.", self.ticket_text(1))
        self.assertEqual([x["key"] for x in self.launched], ["repo/one#1"])

    def test_only_a_running_item_can_be_stopped_and_only_with_a_reason(self):
        self.tick_all()
        v = self.hub.state()["queue"]["version"]
        with self.assertRaisesRegex(ValueError, "not a running item"):
            self.hub.queue_stop("repo/one#1", "why", v)
        with self.assertRaisesRegex(ValueError, "say why"):
            self.hub.queue_stop("repo/one#1", "  ", v)


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
        return sbhub.launch(agent, brief, repo, model, {**env, **{k: v for k, v in os.environ.items() if k.startswith("FAKE_")},
                                      "FAKE_WORKER_MODE": mode}, log)

    def setUp(self):
        super().setUp()
        repo = self.repos["repo/two"]  # built alike, the two repos share a head: give one its own
        (repo / "other.txt").write_text("y\n")
        git(repo, "add", "other.txt")
        git(repo, "commit", "-q", "-m", "other")

    def jobs(self):
        return [i for i in self.items().values() if i["kind"] == "job"]

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
        notes = {i["state"] + ": " + i["note"] for i in self.items().values()}  # the night ended: its items are on its record
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
        self.assertEqual({i["state"] for i in self.items().values()}, {"skipped"})
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
        self.assertEqual({i["state"] for i in self.items().values()}, {"skipped"})
        self.assertEqual(self.hub.nights()["nights"][0]["how"], "stop_time")
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
    def test_launch_gives_a_claude_worker_only_the_hubs_tools_and_the_named_environment(self):
        repo = self.root / "envrepo"
        (repo / ".sb").mkdir(parents=True)
        (repo / ".sb" / "env").write_text("UNITY_PATH\n# c\n\n", encoding="utf-8")
        (repo / ".mcp.json").write_text("{}", encoding="utf-8")
        with mock.patch.dict(os.environ, {"UNITY_PATH": "u", "OPENAI_API_KEY": "k", "LC_ALL": "C", "SB_HUB_PORT": "1"}), \
                mock.patch.object(sbhub.subprocess, "Popen") as popen, mock.patch.object(sbhub, "_exe", return_value="claude"):
            sbhub.launch({"kind": "claude", "dir": "/cfg"}, "b", str(repo), "sonnet", {"SB_HUB_AGENT": "a"}, str(self.root / "l"))
            sbhub.launch({"kind": "agy"}, "b", str(self.root), "m", {}, str(self.root / "l"))
        argv, env = popen.call_args_list[0].args[0], popen.call_args_list[0].kwargs["env"]
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")
        self.assertEqual(Path(argv[argv.index("--plugin-dir") + 1]), Path(sbhub.__file__).resolve().parents[3] / "mods" / "hub-report")
        self.assertEqual([a for a, b in zip(argv, argv[1:]) if a == "--mcp-config" and b], ["--mcp-config"] * 2)
        self.assertTrue(argv[-1].endswith("envrepo/.mcp.json"))
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/cfg")
        self.assertEqual((env["UNITY_PATH"], env["LC_ALL"], env["SB_HUB_AGENT"], env["SB_HUB_PORT"]), ("u", "C", "a", "1"))
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", popen.call_args_list[1].kwargs["env"])
        self.assertNotIn("UNITY_PATH", popen.call_args_list[1].kwargs["env"])

    def test_launch_starts_codex_with_its_model_and_the_sandbox_its_entry_names(self):
        log = self.root / "codex.log"
        p = sbhub.launch({"kind": "codex", "dir": "/cx", "model": None, "sandbox": "bypass"}, "Ticket: m/001\n",
                         str(self.repos["repo/one"]), "gpt-x", {"SB_HUB_AGENT": "m#1", "SB_HUB_PARENT": "queue",
                                                                "SB_HUB_PORT": "1", "FAKE_WORKER_MODE": "nothing"}, str(log))
        self.assertEqual(os.getpgid(p.pid), p.pid)
        self.assertEqual(p.wait(timeout=10), 1)
        self.assertIsNone(p.session)
        text = log.read_text(encoding="utf-8")
        self.assertIn('"-m", "gpt-x", "--dangerously-bypass-approvals-and-sandbox"]', text)
        self.assertIn('"CODEX_HOME": "/cx"', text)
        self.assertIsNone(sbhub.resumable({"session": "s", "session_dir": "/d"}, {"kind": "codex"}, self.root))

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
        (self.repos["repo/one"] / ".sb").mkdir()  # a repo names the variables its tools need
        (self.repos["repo/one"] / ".sb" / "env").write_text("FAKE_WORKER_MODE\nFAKE_WORKER_PIDS\n", encoding="utf-8")
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
