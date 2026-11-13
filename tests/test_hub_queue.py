"""The hub's ticket queue and installed agents: Hub direct with fake tickets, then over HTTP and the CLI."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from helpers import SBMAP, HubCase, free_port  # noqa: E402
from sbhub import Hub, Supervisor, make_handler  # noqa: E402


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
        self.h.tickets()  # state() only reads the cache; this fills it (and ticks nothing)
        self.h.queue_set(["repo/one#1", "repo/one#4"], self.h.state()["queue"]["version"])  # the owner's ticks

    def tearDown(self):
        self._tmp.cleanup()

    def keys(self, h=None):
        return [i["key"] for i in (h or self.h).state()["queue"]["items"]]

    def test_nothing_is_ticked_until_the_owner_ticks_it(self):
        fresh = Hub(self.home / "fresh", run=lambda: json.dumps(TICKETS))
        fresh.tickets()
        self.assertEqual(fresh.state()["queue"]["items"], [])  # reading the tickets never queues one
        q = self.h.state()["queue"]
        self.assertEqual(self.keys(), ["repo/one#4", "repo/one#1"])
        self.assertEqual((q["paused"], q["agent"]), (True, None))  # a new queue waits for the owner's resume
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

    def test_a_failed_or_skipped_ticket_ticked_again_is_queued_afresh(self):
        v = self.h.state()["queue"]["version"]
        with self.h._lock:
            a, b = self.h._data["queue"]["items"]
            a.update(state="failed", note="the worker exited 1", ended=5.0, tries=1, started=4.0, commit="abc",
                     retry="it failed", agent="main", digested=True)
            b.update(state="skipped", note="past the stop time", ended=6.0)
        self.h.queue_set([], v)  # unticked: they stay as they ended
        self.assertEqual([i["state"] for i in self.h.state()["queue"]["items"]], ["failed", "skipped"])
        self.h.queue_set(["repo/one#4", "repo/one#1"], v + 1)
        items = {i["key"]: i for i in self.h.state()["queue"]["items"]}
        self.assertEqual(list(items), ["repo/one#4", "repo/one#1"])
        for i in items.values():
            self.assertEqual((i["state"], i["note"], i["ended"], i["tries"], i["started"], i["commit"]),
                             ("queued", "", None, 0, None, None))
            self.assertNotIn("retry", i)
            self.assertNotIn("digested", i)
        self.assertEqual(items["repo/one#4"]["agent"], "main")  # the owner's agent choice stays

    def test_a_queued_job_can_be_removed_and_queued_again(self):
        prompt = "Audit it"
        with self.h._lock:
            self.h._data["installed"]["main"] = {"kind": "claude", "dir": "/x", "model": None, "limited_until": None}
        with mock.patch("sbhub.project_repo", return_value="/r"):
            key = self.h.queue_job("repo", prompt, "main")["key"]
            v = self.h.state()["queue"]["version"]
            self.assertTrue(self.h.queue_remove_job(key, v - 1)["stale"])
            out = self.h.queue_remove_job(key, v)
            self.assertEqual((out["ok"], [i["key"] for i in out["queue"]["items"]]), (True, ["repo/one#4", "repo/one#1"]))
            again = self.h.queue_job("repo", prompt, "main")["key"]  # no longer a duplicate
            v = self.h.state()["queue"]["version"]
            with self.assertRaises(ValueError):
                self.h.queue_remove_job("repo/one#4", v)  # a ticket is unticked, not removed
            with self.h._lock:
                next(i for i in self.h._data["queue"]["items"] if i["key"] == again)["state"] = "running"
            with self.assertRaises(ValueError):
                self.h.queue_remove_job(again, v)  # running and finished items are never removed
            with self.assertRaises(ValueError):
                self.h.queue_remove_job("job:nope:1", v)
        self.assertEqual(self.h.state()["queue"]["version"], v)

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

    def test_a_new_queue_is_paused_and_a_resumed_one_stays_resumed_after_a_restart(self):
        with tempfile.TemporaryDirectory() as fresh:
            self.assertTrue(Hub(fresh).state()["queue"]["paused"])
        self.h.queue_pause(False)
        again = Hub(self.home, run=lambda: json.dumps(TICKETS))
        again.tickets()
        self.assertFalse(again.state()["queue"]["paused"])

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
        h.tickets()
        h.queue_set(["repo/one#1", "repo/one#4"], h.state()["queue"]["version"])
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
        self.assertEqual(len(h.state()["queue"]["items"]), 0)

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
        h.queue_set(["repo/one#4", "repo/one#1"], h.state()["queue"]["version"])
        rows[0] = [t for t in TICKETS if t["num"] != 4]
        now[0] += 20
        h.queue_set(["repo/one#4", "repo/one#1"], h.state()["queue"]["version"])
        self.assertEqual([i["key"] for i in h.state()["queue"]["items"]], ["repo/one#1", "repo/one#4"])

    def test_a_resumed_fresh_queue_still_ticks_nothing(self):
        h = Hub(self.home / "p", run=lambda: json.dumps(TICKETS))
        h.queue_pause(False)
        h.tickets()
        self.assertEqual(len(h.state()["queue"]["items"]), 0)

    def test_a_broken_sbmap_leaves_the_queue_unset(self):
        h = Hub(self.home / "y", run=lambda: "not json")
        self.assertEqual(h.state()["queue"]["items"], [])
        self.assertEqual(h.tickets(), [])


class MediaTest(unittest.TestCase):
    """A worker's pictures and clips: recorded when its item ends, served only by name from its own media folder."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.h = Hub(self.home, run=lambda: json.dumps(TICKETS))
        self.h.tickets()
        self.h.queue_set(["repo/one#1", "repo/one#4"], self.h.state()["queue"]["version"])
        self.run = self.home / "runs" / "night"
        media = self.run / "4-media"
        media.mkdir(parents=True)
        for n in ("b.png", "a.png", "clip.mp4", "notes.txt", "c.JPG", "d.gif", "e.webp", "f.webm", "g.jpeg"):
            (media / n).write_bytes(b"0123456789" + n.encode())
        (self.run / "4.md").write_text("the report")
        with self.h._lock:
            for i in self.h._data["queue"]["items"]:
                i.update(state="running", run=str(self.run))
        sup = Supervisor(self.h, port=4321)
        sup._end("repo/one#4", "done", commit="abc")
        sup._end("repo/one#1", "failed", note="no commit")  # its run has no 1-media folder
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.h))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def get(self, key, name, headers=None):
        """(status, content type, body, headers) of one GET /api/media."""
        from urllib.parse import quote
        url = "http://127.0.0.1:{}/api/media?key={}&name={}".format(self.port, quote(key, safe=""), quote(name, safe=""))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5) as r:
                return r.status, r.headers.get("Content-Type"), r.read(), r.headers
        except urllib.error.HTTPError as e:
            with e:
                return e.code, None, e.read(), e.headers

    def test_an_ended_item_records_its_media_sorted_known_kinds_only_at_most_six(self):
        items = {i["key"]: i for i in self.h.state()["queue"]["items"]}
        self.assertEqual(items["repo/one#4"]["media"], ["a.png", "b.png", "c.JPG", "clip.mp4", "d.gif", "e.webp"])
        self.assertEqual(items["repo/one#1"]["media"], [])

    def test_a_listed_file_is_served_with_its_type(self):
        code, ctype, body, h = self.get("repo/one#4", "a.png")
        self.assertEqual((code, ctype, body), (200, "image/png", b"0123456789a.png"))
        self.assertEqual(self.get("repo/one#4", "clip.mp4")[1], "video/mp4")
        self.assertEqual(self.get("repo/one#4", "c.JPG")[1], "image/jpeg")
        self.assertEqual(h.get("Accept-Ranges"), "bytes")

    def test_a_range_of_a_clip_is_a_206(self):
        code, ctype, body, h = self.get("repo/one#4", "clip.mp4", {"Range": "bytes=2-5"})
        self.assertEqual((code, body, h.get("Content-Range")), (206, b"2345", "bytes 2-5/18"))
        self.assertEqual(self.get("repo/one#4", "clip.mp4", {"Range": "bytes=-3"})[2], b"mp4")
        self.assertEqual(self.get("repo/one#4", "clip.mp4", {"Range": "bytes=99-"})[0], 416)

    def test_anything_else_is_an_empty_404(self):
        (self.run / "4-media" / "a.png").unlink()
        for key, name in (("repo/one#4", "notes.txt"), ("repo/one#4", "f.webm"), ("repo/one#4", "../4.md"),
                          ("repo/one#4", "..\\4.md"), ("repo/one#4", "4-media/b.png"), ("repo/one#4", ""),
                          ("repo/one#4", "a.png"), ("repo/one#1", "a.png"), ("repo/one#9", "b.png"), ("", "b.png")):
            code, _, body, _ = self.get(key, name)
            self.assertEqual((code, body), (404, b""), (key, name))

    def test_a_listed_name_that_now_leads_outside_its_folder_is_a_404(self):
        b = self.run / "4-media" / "b.png"
        b.unlink()
        b.symlink_to(self.run / "4.md")
        self.assertEqual(self.get("repo/one#4", "b.png")[:3:2], (404, b""))
        with self.h._lock:  # a name planted in the saved state is still checked against the folder
            self.h._data["queue"]["items"][0]["media"] = ["../4.md"]
        self.assertEqual(self.get("repo/one#4", "../4.md")[0], 404)


class TicketActionTest(unittest.TestCase):
    """The page's side panel: a ticket's details and its actions, each a hub call that runs sbmap on a throwaway vault."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.vault = root / "Vault"
        (self.vault / "wayfinder").mkdir(parents=True)
        patcher = mock.patch.dict(os.environ, {"SB_VAULT": str(self.vault), "PATH": "/usr/bin:/bin"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sb("init", "repo/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.")
        self.sb("mapset", "repo/one", "checks=true")
        for t in ("A", "B"):
            self.sb("new", "repo/one", "--title", t, "--why", "Because.", "--done-when", "It works.", "--no-sync")
        (self.vault / "wayfinder" / "repo" / "one" / "handoff.md").write_text(
            "---\ntitle: Handoff\n---\n# Handoff\n\nPick up at B.\n", encoding="utf-8")
        self.h = Hub(root / "home")
        self.h.tickets()

    def sb(self, *a):
        return subprocess.run([sys.executable, str(SBMAP), *a], check=True, capture_output=True, text=True,
                              cwd=self.vault).stdout

    def row(self, num):
        return next((t for t in self.h.tickets() if t["num"] == num), None)

    def text(self, num):
        return next((self.vault / "wayfinder" / "repo" / "one" / "issues").glob("**/{:03d} *.md".format(num))).read_text()

    def test_details_carry_comments_the_maps_checks_its_handoff_and_obsidian_links(self):
        self.sb("comment", "repo/one", "001", "--text", "Looked at it.")
        d = self.h.ticket_detail("repo/one#1")
        self.assertEqual(d["title"], "A")
        self.assertTrue(any("Looked at it." in c for c in d["comments"]))
        self.assertEqual(d["map_checks"], ["true"])
        self.assertEqual([(f["name"], f["first"]) for f in d["trail"]], [("handoff.md", "Pick up at B.")])
        for uri in (d["uri"], d["map_uri"], d["trail"][0]["uri"]):
            self.assertTrue(uri.startswith("obsidian://open?path="), uri)

    def test_details_of_an_unknown_or_odd_key_are_a_key_error(self):
        for key in ("repo/one#9", "repo/none#1", "../one#1", "repo/one", "/etc#1"):
            with self.assertRaises(KeyError, msg=key):
                self.h.ticket_detail(key)

    def test_done_resolves_it_with_the_typed_line_and_the_list_updates_at_once(self):
        out = self.h.ticket_action("done", "repo/one#1", "Done by hand")
        self.assertTrue(out["ok"])
        self.assertIsNone(self.row(1))
        self.assertIn("Done by hand", self.text(1))
        self.assertIn("Project.Finished", self.text(1))

    def test_drop_rules_it_out_with_the_reason_as_a_comment(self):
        self.h.ticket_action("drop", "repo/one#2", "Not needed any more")
        self.assertIsNone(self.row(2))
        self.assertIn("Not needed any more", self.text(2))
        self.assertIn("Project.Dropped", self.text(2))

    def test_release_reopens_a_claimed_ticket_and_refuses_an_open_one(self):
        self.sb("claim", "repo/one", "002", "--by", "someone", "--no-sync")
        self.h.tickets(fresh=True)
        self.h.ticket_action("release", "repo/one#2")
        self.assertEqual((self.row(2)["status"], self.row(2)["claimed_by"]), ("open", None))
        with self.assertRaisesRegex(ValueError, "not claimed"):
            self.h.ticket_action("release", "repo/one#1")

    def test_comment_tier_and_the_maps_checks(self):
        self.h.ticket_action("comment", "repo/one#1", "A note from the page")
        self.assertIn("A note from the page", self.text(1))
        self.h.ticket_action("tier", "repo/one#1", "opus")
        self.assertEqual(self.row(1)["tier"], "opus")
        with self.assertRaisesRegex(ValueError, "tier must be one of"):  # sbmap's own message
            self.h.ticket_action("tier", "repo/one#1", "gpt")
        self.h.ticket_action("checks", "repo/one#1", "true; echo ok")
        self.assertEqual(self.row(2)["checks"], ["true", "echo ok"])

    def test_a_ticket_a_worker_runs_is_left_alone_and_empty_words_are_refused(self):
        with self.h._lock:
            self.h._data["queue"]["items"].append({**Hub._item("repo/one#1"), "state": "running"})
        before = self.text(1)
        for action in ("done", "drop", "release", "comment", "tier", "checks"):
            with self.assertRaisesRegex(ValueError, "a worker is running it", msg=action):
                self.h.ticket_action(action, "repo/one#1", "opus")
        self.assertEqual(self.text(1), before)
        for action in ("done", "drop", "comment", "checks"):
            with self.assertRaises(ValueError, msg=action):
                self.h.ticket_action(action, "repo/one#2", "  ")
        with self.assertRaises(ValueError):
            self.h.ticket_action("explode", "repo/one#2", "x")


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
        self.assertEqual([(r["num"], r["state"], r["queued"]) for r in rows], [(1, "ready", False), (2, "ready", False)])
        self.post("/api/queue/set", {"keys": ["repo/one#1", "repo/one#2"], "version": self.get("/api/state")["queue"]["version"]})
        q = self.get("/api/state")["queue"]
        self.assertEqual([i["key"] for i in q["items"]], ["repo/one#1", "repo/one#2"])
        code, out = self.post("/api/queue/set", {"keys": ["repo/one#2"], "version": q["version"]})
        self.assertEqual((code, out["ok"]), (200, True))
        code, out = self.post("/api/queue/set", {"keys": [], "version": q["version"]})
        self.assertEqual((code, out["stale"]), (409, True))
        self.assertEqual([i["key"] for i in out["queue"]["items"]], ["repo/one#2"])

    def test_ticket_details_and_actions_over_http(self):
        code, out = self.post("/api/ticket/tier", {"key": "repo/one#1", "text": "gpt"})
        self.assertEqual(code, 400)
        self.assertIn("tier must be one of", out["error"])  # sbmap's message, for the panel
        self.assertEqual(self.post("/api/ticket/comment", {"key": "repo/one#1", "text": "From the page"})[0], 200)
        d = self.get("/api/ticket?key=repo%2Fone%231")
        self.assertTrue(any("From the page" in c for c in d["comments"]))
        with self.assertRaises(urllib.error.HTTPError) as c:
            self.get("/api/ticket?key=repo%2Fone%239")
        c.exception.close()
        self.assertEqual(c.exception.code, 404)
        self.assertEqual(self.post("/api/ticket/explode", {"key": "repo/one#1", "text": "x"})[0], 404)

    def test_unknown_agent_is_400(self):
        self.assertEqual(self.post("/api/queue/agent", {"name": "nope"})[0], 400)
        self.assertEqual(self.post("/api/queue/item_agent", {"key": "repo/one#1", "name": "nope"})[0], 400)
        self.assertEqual(self.post("/api/queue/remove_job", {"key": "repo/one#1", "version": 0})[0], 400)
        v = self.get("/api/state")["queue"]["version"]
        self.assertEqual(self.post("/api/queue/remove_job", {"key": "job:x:1", "version": v - 1})[0], 409)

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
        self.assertEqual(self.hub("queue", "add", "repo/one", "2").returncode, 0)  # a fresh queue: only what is added
        self.assertEqual([i["key"] for i in self.get("/api/state")["queue"]["items"]], ["repo/one#2"])
        self.assertEqual(self.hub("queue", "add", "repo/one", "1").returncode, 0)
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
