"""sbhub_mcp, the hub's chat face, driven by an in-memory MCP client against a real hub.

Needs the mcp package; skipped without it. Run it with:
  uv run --no-project --with 'mcp>=2.3,<3' python -m unittest tests.test_hub_mcp
"""
import asyncio
import os
import sys
import threading
import time
import unittest

from helpers import HubCase, SCRIPT, wait_for

try:
    from mcp.client import advertise
    from mcp.client.client import Client
    from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
except ImportError:  # the stdlib-only suite still runs
    Client = None

sys.path.insert(0, os.path.dirname(SCRIPT))


@unittest.skipIf(Client is None, "mcp is not installed")
class HubMcpTest(HubCase):
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
        self.assertIn("alpha blocked: no editor", r.content[0].text)
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


if __name__ == "__main__":
    unittest.main()
