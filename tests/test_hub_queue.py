"""The hub's ticket queue and installed agents: Hub direct with fake tickets, then over HTTP and the CLI."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from helpers import SBMAP, HubCase, free_port  # noqa: E402
from sbhub import Hub  # noqa: E402


def tk(num, blocked=(), priority="C", **kw):
    t = {"map": "repo/one", "num": num, "title": f"T{num}", "why": "", "type": "implementation",
         "status": "open", "priority": priority, "blocked_by": list(blocked),
         "blocked_by_open": list(blocked), "paths": [], "tier": "sonnet", "has_done_when": True,
         "done_when": "ok", "question": "", "out": "", "checks": ["true"], "repo": "/r",
         "file": f"/v/{num}.md", "map_title": "One", "map_order": 1, "claimed_by": None}
    t.update(kw)
    return t


TICKETS = [tk(1, priority="B"), tk(2, blocked=[1], priority="A"), tk(3, type="grilling"),
           tk(4, priority="A"), tk(5, status="claimed", claimed_by="me")]


class QueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.h = Hub(self.home, run=lambda: json.dumps(TICKETS))
        self.h.tickets()  # state() only reads the cache; this fills it and seeds the queue

    def tearDown(self):
        self._tmp.cleanup()

    def keys(self, h=None):
        return [i["key"] for i in (h or self.h).state()["queue"]["items"]]

    def test_default_selection_is_every_ready_ticket(self):
        q = self.h.state()["queue"]
        self.assertEqual(self.keys(), ["repo/one#4", "repo/one#1"])
        self.assertEqual((q["paused"], q["agent"]), (False, None))
        self.assertTrue(all(i["state"] == "queued" and i["kind"] == "ticket" for i in q["items"]))

    def test_queue_set_orders_by_the_rule_and_bumps_the_version_once(self):
        v = self.h.state()["queue"]["version"]
        out = self.h.queue_set(["repo/one#2", "repo/one#1", "repo/one#4"], v)
        self.assertTrue(out["ok"])
        self.assertEqual(self.keys(), ["repo/one#4", "repo/one#1", "repo/one#2"])
        self.assertEqual(out["queue"]["version"], v + 1)

    def test_a_stale_version_is_refused_with_the_current_queue(self):
        v = self.h.state()["queue"]["version"]
        self.h.queue_set(["repo/one#1"], v)
        out = self.h.queue_set(["repo/one#4"], v)
        self.assertEqual((out["ok"], out["stale"]), (False, True))
        self.assertEqual([i["key"] for i in out["queue"]["items"]], ["repo/one#1"])
        self.assertEqual(self.keys(), ["repo/one#1"])
        self.assertEqual(out["queue"]["version"], v + 1)

    def test_unticking_removes_only_queued_items(self):
        v = self.h.state()["queue"]["version"]
        with self.h._lock:
            q = self.h._data["queue"]
            q["items"][0]["state"] = "running"
            q["items"].append({"key": "job1", "kind": "job", "agent": None, "state": "queued"})
        self.h.queue_set([], v)
        items = self.h.state()["queue"]["items"]
        self.assertEqual([(i["key"], i["state"]) for i in items], [("repo/one#4", "running"), ("job1", "queued")])

    def test_a_ticked_ticket_that_is_running_or_done_is_not_added_again(self):
        v = self.h.state()["queue"]["version"]
        with self.h._lock:
            self.h._data["queue"]["items"][0]["state"] = "done"
        self.h.queue_set(["repo/one#4", "repo/one#1"], v)
        self.assertEqual([(i["key"], i["state"]) for i in self.h.state()["queue"]["items"]],
                         [("repo/one#4", "done"), ("repo/one#1", "queued")])

    def test_move_clamps_and_never_moves_a_running_item(self):
        v = self.h.state()["queue"]["version"]
        self.h.queue_set(["repo/one#1", "repo/one#2", "repo/one#4"], v)
        out = self.h.queue_move("repo/one#2", 0, v + 1)  # cannot go before its blocker
        self.assertEqual(self.keys(), ["repo/one#4", "repo/one#1", "repo/one#2"])
        self.assertEqual(out["queue"]["version"], v + 2)
        self.h.queue_move("repo/one#4", 2, v + 2)
        self.assertEqual(self.keys(), ["repo/one#1", "repo/one#2", "repo/one#4"])
        with self.h._lock:
            self.h._data["queue"]["items"][0]["state"] = "running"
        with self.assertRaises(ValueError):
            self.h.queue_move("repo/one#1", 2, v + 3)
        self.assertEqual(self.h.queue_move("repo/one#4", 0, 1)["stale"], True)

    def test_pause_and_agents_bump_once_and_unknown_agent_is_refused(self):
        v = self.h.state()["queue"]["version"]
        self.assertEqual(self.h.queue_pause(True)["queue"]["version"], v + 1)
        self.assertTrue(self.h.state()["queue"]["paused"])
        with self.assertRaises(ValueError):
            self.h.queue_agent("nope")
        with self.assertRaises(ValueError):
            self.h.queue_item_agent("repo/one#1", "nope")
        self.assertEqual(self.h.state()["queue"]["version"], v + 1)
        with self.h._lock:
            self.h._data["installed"]["main"] = {"kind": "claude", "dir": "/x", "model": None, "limited_until": None}
        self.assertEqual(self.h.queue_agent("main")["queue"]["agent"], "main")
        self.h.queue_item_agent("repo/one#1", "main")
        agents = {i["key"]: i["agent"] for i in self.h.state()["queue"]["items"]}
        self.assertEqual(agents, {"repo/one#4": None, "repo/one#1": "main"})
        self.h.queue_item_agent("repo/one#1", None)
        self.assertEqual(self.h.state()["queue"]["version"], v + 4)

    def test_the_queue_survives_a_restart(self):
        v = self.h.state()["queue"]["version"]
        self.h.queue_set(["repo/one#1"], v)
        self.h.queue_pause(True)
        again = Hub(self.home, run=lambda: "not json")
        q = again.state()["queue"]
        self.assertEqual(([i["key"] for i in q["items"]], q["paused"], q["version"]), (["repo/one#1"], True, v + 2))

    def test_an_emptied_queue_is_not_refilled(self):
        v = self.h.state()["queue"]["version"]
        self.h.queue_set([], v)
        self.assertEqual(self.keys(), [])

    def test_tickets_carry_state_reason_and_queued_and_are_cached(self):
        calls = []

        def run():
            calls.append(1)
            return json.dumps(TICKETS)
        now = [100.0]
        h = Hub(self.home / "x", now=lambda: now[0], run=run)
        rows = {t["num"]: t for t in h.tickets()}
        self.assertEqual((rows[1]["state"], rows[1]["queued"]), ("ready", True))
        self.assertEqual((rows[2]["state"], rows[2]["queued"]), ("ready", False))  # its blocker is queued
        self.assertEqual(rows[3]["state"], "waits for you")
        self.assertEqual(rows[5]["state"], "claimed")
        h.queue_set([], h.state()["queue"]["version"])
        rows = {t["num"]: t for t in h.tickets()}
        self.assertEqual((rows[2]["state"], rows[2]["reason"]), ("blocked", "after T1"))
        self.assertEqual(len(calls), 1)
        now[0] += 16
        h.tickets()
        self.assertEqual(len(calls), 2)

    def test_state_never_runs_sbmap(self):
        calls = []
        h = Hub(self.home / "z", run=lambda: calls.append(1) or json.dumps(TICKETS))
        self.assertEqual(h.state()["queue"]["items"], [])
        self.assertEqual(calls, [])
        h.tickets()
        self.assertEqual(len(h.state()["queue"]["items"]), 2)

    def test_a_failed_sbmap_is_not_retried_at_once(self):
        calls = []
        now = [100.0]

        def run():
            calls.append(1)
            raise OSError("down")
        h = Hub(self.home / "f", now=lambda: now[0], run=None)
        h._run = run
        h.tickets()
        h.tickets()
        self.assertEqual(len(calls), 1)
        now[0] += 6
        h.tickets()
        self.assertEqual(len(calls), 2)

    def test_queue_set_with_sbmap_down_is_refused_and_changes_nothing(self):
        def run():
            raise OSError("down")
        h = Hub(self.home / "d", run=run)
        with self.assertRaises(ValueError) as e:
            h.queue_set(["repo/one#1"], 0)
        self.assertIn("tickets unavailable", str(e.exception))
        q = h.state()["queue"]
        self.assertEqual((q["version"], q["items"], q["seeded"]), (0, [], False))
        with self.assertRaises(ValueError):
            h.queue_move("repo/one#1", 0, 0)

    def test_queued_tickets_missing_from_a_fresh_list_are_kept(self):
        rows = [list(TICKETS)]
        now = [100.0]
        h = Hub(self.home / "k", now=lambda: now[0], run=lambda: json.dumps(rows[0]))
        h.tickets()
        rows[0] = [t for t in TICKETS if t["num"] != 4]
        now[0] += 20
        h.queue_set(["repo/one#4", "repo/one#1"], h.state()["queue"]["version"])
        self.assertEqual([i["key"] for i in h.state()["queue"]["items"]], ["repo/one#1", "repo/one#4"])

    def test_pause_does_not_stop_the_default_selection(self):
        h = Hub(self.home / "p", run=lambda: json.dumps(TICKETS))
        h.queue_pause(True)
        h.tickets()
        self.assertEqual(len(h.state()["queue"]["items"]), 2)

    def test_a_broken_sbmap_leaves_the_queue_unset(self):
        h = Hub(self.home / "y", run=lambda: "not json")
        self.assertEqual(h.state()["queue"]["items"], [])
        self.assertEqual(h.tickets(), [])


class ScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.h = Hub(self.root / "hub", run=lambda: "[]")

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, name, creds):
        d = self.home / name
        d.mkdir()
        if creds == "file":
            (d / ".credentials.json").write_text("{}")
        elif creds == "account":
            (d / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "x"}}))
        elif creds == "anon":
            (d / ".claude.json").write_text(json.dumps({"userID": "u"}))

    def test_signed_in_configs_are_named_by_folder_and_agy_is_found_on_path(self):
        self.config(".claude", "account")
        self.config(".claude-personal", "file")
        self.config(".claude-signed-out", "anon")
        self.config(".claude-empty", None)
        (self.home / ".claude-notadir").write_text("x")
        out = self.h.agents_scan(home=self.home, which=lambda n: "/bin/agy" if n == "agy" else None)
        self.assertEqual(set(out), {"main", "personal", "agy"})
        self.assertEqual(out["main"], {"kind": "claude", "dir": str(self.home / ".claude"), "model": None,
                                       "limited_until": None})
        self.assertEqual(out["agy"]["kind"], "agy")
        self.assertEqual(self.h.state()["installed"], out)

    def test_the_default_agent_is_never_agy_and_a_chosen_one_stays(self):
        self.h.agents_scan(home=self.home, which=lambda n: "/bin/agy")
        self.assertIsNone(self.h.state()["queue"]["agent"])
        self.config(".claude-personal", "file")
        self.config(".claude", "file")
        self.h.agents_scan(home=self.home, which=lambda n: "/bin/agy")
        self.assertEqual(self.h.state()["queue"]["agent"], "main")
        self.h.queue_agent("personal")
        self.h.agents_scan(home=self.home, which=lambda n: None)
        self.assertEqual(self.h.state()["queue"]["agent"], "personal")

    def test_a_scan_merges_and_never_deletes_hand_edits(self):
        self.config(".claude", "file")
        self.h.agents_scan(home=self.home, which=lambda n: None)
        with self.h._lock:
            inst = self.h._data["installed"]
            inst["main"]["model"] = "opus"
            inst["work"] = {"kind": "claude", "dir": "/w", "model": None, "limited_until": 5.0}
        out = self.h.agents_scan(home=self.home, which=lambda n: None)
        self.assertEqual((out["main"]["model"], out["work"]["dir"]), ("opus", "/w"))


class QueueHttpTest(HubCase):
    def setUp(self):
        self._tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp2.cleanup)
        self.vault = Path(self._tmp2.name) / "Vault"
        (self.vault / "wayfinder").mkdir(parents=True)
        env = {**os.environ, "SB_VAULT": str(self.vault), "PATH": "/usr/bin:/bin"}

        def sb(*a):
            subprocess.run([sys.executable, str(SBMAP), *a], env=env, check=True, capture_output=True, cwd=self.vault)
        sb("init", "repo/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.")
        sb("mapset", "repo/one", "checks=true")
        for t in ("A", "B"):
            sb("new", "repo/one", "--title", t, "--why", "Because.", "--done-when", "It works.", "--no-sync")
        patcher = mock.patch.dict(os.environ, {"SB_VAULT": str(self.vault), "HOME": str(self.root_home()),
                                                  "PATH": "/usr/bin:/bin"})
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def root_home(self):
        h = Path(self._tmp2.name) / "home"
        (h / ".claude-x").mkdir(parents=True)
        (h / ".claude-x" / ".credentials.json").write_text("{}")
        return h

    def test_tickets_and_queue_over_http(self):
        rows = self.get("/api/tickets")
        self.assertEqual([(r["num"], r["state"], r["queued"]) for r in rows], [(1, "ready", True), (2, "ready", True)])
        q = self.get("/api/state")["queue"]
        self.assertEqual([i["key"] for i in q["items"]], ["repo/one#1", "repo/one#2"])
        code, out = self.post("/api/queue/set", {"keys": ["repo/one#2"], "version": q["version"]})
        self.assertEqual((code, out["ok"]), (200, True))
        code, out = self.post("/api/queue/set", {"keys": [], "version": q["version"]})
        self.assertEqual((code, out["stale"]), (409, True))
        self.assertEqual([i["key"] for i in out["queue"]["items"]], ["repo/one#2"])

    def test_unknown_agent_is_400(self):
        self.assertEqual(self.post("/api/queue/agent", {"name": "nope"})[0], 400)
        self.assertEqual(self.post("/api/queue/item_agent", {"key": "repo/one#1", "name": "nope"})[0], 400)

    def test_scan_and_agents_cli(self):
        r = self.hub("agents", "--scan")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("x", r.stdout)
        self.assertEqual(list(self.get("/api/state")["installed"]), ["x"])
        self.assertEqual(self.get("/api/state")["queue"]["agent"], "x")
        self.assertIn("claude", self.hub("agents").stdout)

    def test_queue_cli(self):
        r = self.hub("queue")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("repo/one#1", r.stdout)
        self.assertEqual(self.hub("queue", "rm", "repo/one", "1").returncode, 0)
        self.assertEqual([i["key"] for i in self.get("/api/state")["queue"]["items"]], ["repo/one#2"])
        self.assertEqual(self.hub("queue", "add", "repo/one", "1").returncode, 0)
        self.assertEqual({i["key"] for i in self.get("/api/state")["queue"]["items"]}, {"repo/one#1", "repo/one#2"})
        self.assertEqual(self.hub("queue", "pause").returncode, 0)
        self.assertTrue(self.get("/api/state")["queue"]["paused"])
        self.hub("queue", "resume")
        self.assertFalse(self.get("/api/state")["queue"]["paused"])
        bad = self.hub("queue", "agent", "nope")
        self.assertEqual(bad.returncode, 1)

    def test_cli_exits_2_when_the_hub_is_down(self):
        down = free_port()
        for args in (["queue"], ["queue", "add", "m", "1"], ["queue", "rm", "m", "1"], ["queue", "pause"],
                     ["queue", "resume"], ["queue", "agent", "x"], ["agents"], ["agents", "--scan"]):
            r = self.hub(*args, port=down)
            self.assertEqual((r.returncode, r.stderr.strip()), (2, "sbhub: not running"), args)


if __name__ == "__main__":
    unittest.main()
