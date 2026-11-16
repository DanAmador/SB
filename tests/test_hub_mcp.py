"""sbhub_mcp, the hub's chat face, driven by an in-memory MCP client against a real hub.

Needs the mcp package; skipped without it. Run it with:
  uv run --no-project --with 'mcp>=2.3,<3' python -m unittest tests.test_hub_mcp
"""
import asyncio
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HUB = Path(__file__).resolve().parents[1] / "skills" / "sb" / "hub"
from helpers import SBMAP, HubCase, SCRIPT, serve_command, wait_for

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

    def test_the_widget_is_the_new_board_in_one_file_and_reads_through_sb_api(self):
        built = (self.mod.DIST / "index.html").exists()
        html = self.mod.board_html()
        if not built:
            return self.assertIn("pnpm --dir skills/sb/hub build", html)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn('<div id="root">', html)
        self.assertLess(html.index("window.__SB_WIDGET__"), html.index("<script type=module>"))  # the bridge runs first
        for outside in ('src="./', 'href="./', "<link rel=\"stylesheet\""):
            self.assertNotIn(outside, html)
        self.assertIn("sb_api", html)
        self.assertIn("sb_answer", html)
        self.assertFalse((self.mod.HERE / "sbhub_widget.html").exists())

    def test_sb_api_reads_the_hub_and_only_its_api(self):
        self.hub("report", "--agent", "a", "--state", "idle")
        ok = self.run_client(lambda c: c.call_tool("sb_api", {"path": "/api/state"}))
        self.assertEqual(ok.structured_content["status"], 200)
        self.assertIn("a", json.loads(ok.structured_content["body"])["agents"])
        for bad in ("/", "/api/../x", "http://evil/api/state"):
            self.assertTrue(self.run_client(lambda c: c.call_tool("sb_api", {"path": bad})).is_error, bad)

@unittest.skipIf(Client is None, "mcp is not installed")
class HubMcpStateTest(McpBase):
    """The chat card's state read: the TypeScript hub's real /api/state, relayed by sb_api in parts, parsed by the contract."""
    ts = True

    def read_all(self, path):
        first = self.run_client(lambda c: c.call_tool("sb_api", {"path": path})).structured_content
        body, parts = first["body"], first["parts"]
        for i in range(1, parts):
            part = self.run_client(lambda c: c.call_tool("sb_api", {"path": path, "part": i}))
            self.assertFalse(part.is_error)
            body += part.structured_content["body"]
        return first["status"], parts, body

    def test_sb_api_state_in_parts_parses_by_the_contract(self):
        self.hub("report", "--agent", "a", "--state", "idle")
        self.hub("ask", "--agent", "a", "--q", "Pick one", "--options", "x,y")
        self.mod.API_PART = 100  # the test state is small; cut it so it needs several parts
        self.addCleanup(setattr, self.mod, "API_PART", 150_000)
        status, parts, body = self.read_all("/api/state")
        self.assertEqual(status, 200)
        self.assertGreater(parts, 1, (len(body), self.mod.API_PART))
        self.assertEqual(json.loads(body), self.get("/api/state") | {"now": json.loads(body)["now"]})
        script = ("import { answerSchema } from %s;"
                  "const r = answerSchema('GET /api/state', 200).safeParse(JSON.parse(process.argv[1]));"
                  "if (!r.success) { console.error(JSON.stringify(r.error.issues)); process.exit(1); }" %
                  json.dumps(str(HUB / "packages" / "contract" / "src" / "index.ts")))
        out = subprocess.run(["node", "--input-type=module", "-e", script, body], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_later_part_without_a_first_read_says_so(self):
        r = self.run_client(lambda c: c.call_tool("sb_api", {"path": "/api/never", "part": 1}))
        self.assertTrue(r.is_error)


@unittest.skipIf(Client is None, "mcp is not installed")
class HubCardTest(McpBase):
    """The chat card against the Python hub as it really answers (no `links` on a queue item): the bridge, sb_api in parts
    and the board's typed client together, and the card coming back by itself after the hub restarts."""
    ts = False

    def shim(self):
        test = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                call = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                r = test.run_client(lambda c: c.call_tool(call["name"], call["arguments"]))
                out = json.dumps({"structuredContent": r.structured_content, "isError": r.is_error}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def lines(self, probe):
        q = queue.Queue()
        threading.Thread(target=lambda: [q.put(l.strip()) for l in probe.stdout], daemon=True).start()
        return q

    def next_line(self, q, until, secs):
        end, seen = time.time() + secs, []
        while time.time() < end:
            try:
                line = q.get(timeout=0.5)
            except queue.Empty:
                continue
            seen.append(line)
            if line.startswith(until):
                return line, secs - (end - time.time())
        self.fail("no %r line within %s s: %s" % (until, secs, seen[-5:]))

    def test_the_card_shows_the_python_hubs_state_and_comes_back_after_a_restart(self):
        project = Path(self._tmp.name) / "proj"
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        self.assertTrue(self.hub("queue", "job", "--project", str(project), "--prompt", "x").stdout.strip())
        items = self.get("/api/state")["queue"]["items"]
        self.assertTrue(items and all("links" not in i for i in items), items)  # what the Python hub really serves
        self.mod.API_PART = 300  # cut the answer so it is relayed in several parts, as the real one is
        self.addCleanup(setattr, self.mod, "API_PART", 150_000)
        shim = self.shim()
        probe = subprocess.Popen(["node", "--experimental-transform-types", "--no-warnings", str(Path(__file__).with_name("hub_card_probe.mjs")),
                                  str(HUB / "packages" / "web" / "src" / "lib" / "api.ts"),
                                  str(Path(self.mod.__file__).with_name("sbhub_widget_bridge.js")),
                                  "http://127.0.0.1:%d/" % shim, "1000"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(probe.kill)
        q = self.lines(probe)
        first, _ = self.next_line(q, "ok", 30)  # the host's first start offered no tools; the bridge asked again
        self.assertEqual(first, "ok 2")
        self.server.kill()
        self.server.wait()
        self.server.stdout.close()
        self.next_line(q, "fail", 10)  # the card sees the hub gone
        self.server = subprocess.Popen(serve_command(self.port, False), stdout=subprocess.PIPE, text=True, env=self.env)
        self.procs.append(self.server)
        self.assertEqual(self.server.stdout.readline().strip(), "sb hub on http://127.0.0.1:%d" % self.port)
        _, took = self.next_line(q, "ok", 10)
        self.assertLess(took, 10)


if __name__ == "__main__":
    unittest.main()
