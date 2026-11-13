"""sbhub_mcp, the hub's chat face, driven by an in-memory MCP client against a real hub.

Needs the mcp package; skipped without it. Run it with:
  uv run --no-project --with 'mcp>=2.3,<3' python -m unittest tests.test_hub_mcp
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import SBMAP, HubCase, SCRIPT, wait_for

try:
    from mcp.client import advertise
    from mcp.client.client import Client
    from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
except ImportError:  # the stdlib-only suite still runs
    Client = None

sys.path.insert(0, os.path.dirname(SCRIPT))


@unittest.skipIf(Client is None, "mcp is not installed")
class McpBase(HubCase):
    def setUp(self):
        super().setUp()
        old = os.environ.get("SB_HUB_AUTOSTART")
        os.environ["SB_HUB_AUTOSTART"] = "0"
        self.addCleanup(lambda: os.environ.pop("SB_HUB_AUTOSTART") if old is None else os.environ.update(SB_HUB_AUTOSTART=old))
        import sbhub_mcp
        sbhub_mcp.PORT = self.port
        self.mod = sbhub_mcp

    def run_client(self, fn, apps=True):
        async def go():
            ext = [advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})] if apps else []
            async with Client(self.mod.build_server(), extensions=ext) as c:
                return await fn(c)
        return asyncio.run(go())


@unittest.skipIf(Client is None, "mcp is not installed")
class HubMcpTest(McpBase):
    def test_board_tool_points_at_the_widget(self):
        async def fn(c):
            tools = {t.name: t for t in (await c.list_tools()).tools}
            res = await c.read_resource(self.mod.BOARD_URI)
            return tools, res
        tools, res = self.run_client(fn)
        self.assertEqual(tools["sb_board"].meta["ui"]["resourceUri"], self.mod.BOARD_URI)
        self.assertEqual(tools["sb_board"].meta["ui/resourceUri"], self.mod.BOARD_URI)
        self.assertEqual(tools["sb_ask"].meta["ui/resourceUri"], self.mod.BOARD_URI)
        self.assertEqual(tools["sb_state"].meta["ui"]["visibility"], ["app"])
        self.assertEqual(tools["sb_answer"].meta["ui"]["visibility"], ["app"])
        self.assertEqual(res.contents[0].mime_type, APP_MIME_TYPE)
        self.assertIn("ui/initialize", res.contents[0].text)

    def test_board_returns_text_and_the_state(self):
        self.hub("report", "--agent", "a", "--name", "alpha", "--state", "blocked", "--note", "no editor")
        r = self.run_client(lambda c: c.call_tool("sb_board", {}))
        self.assertIn("Needs you: alpha blocked: no editor", r.content[0].text)
        # the model gets the few summary lines only: the widget pulls the state itself (sb_state),
        # so a board never puts every provider log into the conversation
        self.assertEqual(r.structured_content["agents"]["a"]["state"], "blocked")
        self.assertNotIn("providers", r.structured_content)
        state = self.run_client(lambda c: c.call_tool("sb_state", {}))
        self.assertIn("a", state.structured_content["agents"])
        self.assertNotIn("aliases", state.structured_content)

    def test_the_board_text_says_what_was_just_decided(self):
        # the chat message a click sends can fail to arrive: the agent reads the choice here instead
        async def fn(c):
            asked = await c.call_tool("sb_ask", {"question": "Ship it?", "options": ["yes", "no"], "default": "no"})
            await c.call_tool("sb_answer", {"qid": asked.structured_content["focus"], "answer": "yes"})
            return await c.call_tool("sb_board", {})
        r = self.run_client(fn)
        self.assertIn("decided: Ship it? -> yes (by you)", r.content[0].text)

    def test_ask_returns_at_once_and_the_widget_answers(self):
        async def fn(c):
            asked = await c.call_tool("sb_ask", {"question": "Ship it?", "options": ["yes", "no"], "default": "no"})
            qid = asked.structured_content["focus"]
            self.assertNotIn("providers", asked.structured_content)
            await c.call_tool("sb_answer", {"qid": qid, "answer": "yes"})
            return asked, qid
        asked, qid = self.run_client(fn)
        self.assertIn("End your turn", asked.content[0].text)
        q = self.get("/api/question/" + qid)
        self.assertEqual((q["answer"], q["by"]), ("yes", "you"))

    def test_blocking_ask_returns_the_click(self):
        def click():
            qid = wait_for(lambda: next(iter(self.get("/api/state")["questions"]), None))
            self.post("/api/answer", {"qid": qid, "answer": "b"})
        threading.Thread(target=click, daemon=True).start()
        r = self.run_client(lambda c: c.call_tool("sb_ask", {"question": "q?", "options": ["a", "b"], "default": "a",
                                                             "block_seconds": 20}))
        self.assertEqual(r.structured_content["answer"], "b")

    def test_lock_and_report(self):
        async def fn(c):
            first = await c.call_tool("sb_lock", {"key": "unity", "by": "a"})
            second = await c.call_tool("sb_lock", {"key": "unity", "by": "b"})
            await c.call_tool("sb_report", {"agent": "a", "state": "working", "done": 2, "total": 5})
            return first, second
        first, second = self.run_client(fn)
        self.assertEqual((first.content[0].text, second.content[0].text), ("ok", "held by a"))
        a = self.get("/api/state")["agents"]["a"]
        self.assertEqual((a["done"], a["total"]), ("2", "5"))

    def test_hub_down_degrades(self):
        self.mod.PORT = 1  # nothing listens there, and autostart is off
        r = self.run_client(lambda c: c.call_tool("sb_ask", {"question": "q?", "options": ["a", "b"], "default": "a"}))
        self.assertEqual(r.structured_content["answer"], "a")
        r = self.run_client(lambda c: c.call_tool("sb_board", {}))
        self.assertTrue(r.is_error)


@unittest.skipIf(Client is None, "mcp is not installed")
class HubMcpQueueTest(McpBase):
    """sb_queue and the queue line, against a hub that reads a throwaway vault with two ready tickets."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vault = Path(tmp.name) / "Vault"
        (vault / "wayfinder").mkdir(parents=True)
        env = {**os.environ, "SB_VAULT": str(vault), "PATH": "/usr/bin:/bin"}

        def sb(*a):
            subprocess.run([sys.executable, str(SBMAP), *a], env=env, check=True, capture_output=True, cwd=vault)
        sb("init", "repo/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.")
        sb("mapset", "repo/one", "checks=true")
        for t in ("A", "B"):
            sb("new", "repo/one", "--title", t, "--why", "Because.", "--done-when", "It works.", "--no-sync")
        patcher = mock.patch.dict(os.environ, {"SB_VAULT": str(vault), "PATH": "/usr/bin:/bin"})
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()
        self.get("/api/tickets")
        self.post("/api/queue/set", {"keys": ["repo/one#1", "repo/one#2"],
                                     "version": self.get("/api/state")["queue"]["version"]})  # ticking is explicit

    def keys(self):
        return [i["key"] for i in self.get("/api/state")["queue"]["items"]]

    def test_sb_queue_removes_and_adds_by_key(self):
        r = self.run_client(lambda c: c.call_tool("sb_queue", {"remove": ["repo/one#1"]}))
        self.assertFalse(r.is_error, r.content[0].text)
        self.assertEqual(self.keys(), ["repo/one#2"])
        self.assertIn("1 queued", r.content[0].text)
        r = self.run_client(lambda c: c.call_tool("sb_queue", {"add": ["repo/one#1"]}))
        self.assertEqual(sorted(self.keys()), ["repo/one#1", "repo/one#2"])
        self.assertIn("repo/one#1", r.content[0].text)
        self.assertNotIn("providers", r.structured_content or {})

    def test_sb_queue_retries_once_on_a_stale_version(self):
        real, bumped = self.mod.hub, []

        def racing(path, data=None, timeout=2):
            if path == "/api/queue/set" and not bumped:
                bumped.append(1)
                real("/api/queue/pause", {"paused": True})  # another writer got in first
            return real(path, data, timeout)
        with mock.patch.object(self.mod, "hub", racing):
            r = self.run_client(lambda c: c.call_tool("sb_queue", {"remove": ["repo/one#2"]}))
        self.assertFalse(r.is_error, r.content[0].text)
        self.assertEqual(self.keys(), ["repo/one#1"])

    def test_sb_queue_says_so_when_the_hub_is_down(self):
        self.mod.PORT = 1
        r = self.run_client(lambda c: c.call_tool("sb_queue", {"add": ["repo/one#1"]}))
        self.assertTrue(r.is_error)
        self.assertIn("not running", r.content[0].text)

    def test_sb_queue_with_nothing_to_change_just_reads(self):
        r = self.run_client(lambda c: c.call_tool("sb_queue", {}))
        self.assertFalse(r.is_error)
        self.assertIn("2 queued", r.content[0].text)
        self.assertEqual(len(self.keys()), 2)

    def test_the_board_text_has_the_queue_line(self):
        r = self.run_client(lambda c: c.call_tool("sb_board", {}))
        self.assertRegex(r.content[0].text, r"Queued: 2.*\nEnds about \d\d:\d\d")
        q = r.structured_content["queue"]  # trimmed for the model: no provider data, five lines at most
        self.assertLessEqual(len(q["items"]), 5)
        self.assertNotIn("providers", r.structured_content)

    def test_the_board_text_has_no_queue_line_for_an_empty_queue(self):
        self.post("/api/queue/set", {"keys": [], "version": self.get("/api/state")["queue"]["version"]})
        r = self.run_client(lambda c: c.call_tool("sb_board", {}))
        self.assertNotIn("Queued", r.content[0].text)

    def test_the_board_text_is_a_few_plain_lines(self):
        now = time.time()
        s = {"now": now, "agents": {}, "questions": {}, "locks": {},
             "queue": {"paused": False, "items": [
                 {"key": "m#1", "state": "running", "name": "Fix the thing", "agent": "work", "started": now - 600}]
                 + [{"key": "m#%d" % n, "state": "queued"} for n in range(2, 13)]},
             "installed": {"work": {"usage": {"five_hour": 0.42, "five_hour_resets": now + 3600}},
                           "alt": {"limited_until": now + 7200}}}
        t = self.mod.summary(s)
        hm = lambda x: time.strftime("%H:%M", time.localtime(x))
        self.assertIn("Nothing needs you.", t)
        self.assertIn("Running: Fix the thing on work, 10 min", t)
        self.assertIn("Queued: 11", t)
        self.assertIn("work 42% of 5 hours, resets " + hm(now + 3600), t)
        self.assertIn("alt at its limit until " + hm(now + 7200), t)
        self.assertRegex(t, r"Ends about \d\d:\d\d")
        self.assertTrue(5 <= len(t.splitlines()) <= 8)

    def test_the_snapshot_counts_the_whole_queue(self):
        items = [{"key": "m#%d" % n, "kind": "ticket", "state": "queued"} for n in range(11)]
        items.append({"key": "m#99", "kind": "ticket", "state": "running"})
        fake = {"agents": {}, "questions": {}, "locks": {}, "now": 1, "queue": {"items": items}}
        with mock.patch.object(self.mod, "board_state", lambda focus=None: fake):
            q = self.mod.snapshot()["queue"]
        self.assertEqual((q["queued"], q["running"], len(q["items"])), (11, 1, 5))

    def test_the_widget_has_no_emoji_and_draws_the_queue(self):
        html = self.mod.BOARD_HTML.read_text(encoding="utf-8")
        emoji = [c for c in html if ord(c) >= 0x2190 and c not in "\u2026\u2192\u00b7\u201c\u201d\u25b8"]
        self.assertEqual(emoji, [], "emoji or pictograph characters left in the widget")
        self.assertIn("git-branch", html)
        self.assertIn("s.queue", html)


if __name__ == "__main__":
    unittest.main()
