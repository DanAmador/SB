"""sbhub_lan.py: the hub's own page, read-only, on the WiFi behind a secret token; run against a throwaway hub."""
import json
import os
import re
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from helpers import HubCase, free_port, wait_for

LAN = str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts" / "sbhub_lan.py")


class LanTest(HubCase):
    def setUp(self):
        super().setUp()
        self.lan_port = free_port()
        # 127.0.0.1 in a test: binding every interface would ask the macOS firewall
        p = subprocess.Popen([sys.executable, LAN, "serve", "--port", str(self.lan_port), "--hub-port", str(self.port),
                              "--bind", "127.0.0.1"], stdout=subprocess.PIPE, text=True, env=self.env)
        self.procs.append(p)
        self.assertIn(f":{self.lan_port}/v/", p.stdout.readline())
        self.token = Path(self._tmp.name, "lan-token").read_text().strip()

    def req(self, path, data=None, headers=None):
        """(status, body bytes) of one request to the phone page's server."""
        h = {"Content-Type": "application/json"} if data is not None else {}
        r = urllib.request.Request(f"http://127.0.0.1:{self.lan_port}{path}",
                                   None if data is None else json.dumps(data).encode(), {**h, **(headers or {})})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def v(self, rest=""):
        return f"/v/{self.token}/{rest}"

    def test_the_token_is_32_url_safe_characters_made_once(self):
        self.assertRegex(self.token, r"^[A-Za-z0-9_-]{32}$")
        r = subprocess.run([sys.executable, LAN, "url", "--port", "9999"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout.strip(), rf"^http://\d+\.\d+\.\d+\.\d+:9999/v/{self.token}/$")
        self.assertEqual(Path(self._tmp.name, "lan-token").read_text().strip(), self.token)
        self.assertEqual(os.stat(Path(self._tmp.name, "lan-token")).st_mode & 0o077, 0)

    def test_without_the_token_every_path_is_an_empty_404(self):
        for path in ("/", "/board.js", "/api/state", "/v/", "/v/wrong/", "/v/wrong/api/state", f"/v/{self.token[:-1]}/"):
            self.assertEqual(self.req(path), (404, b""), path)
        self.assertEqual(self.req("/v/wrong/api/queue/clear-finished", {}), (404, b""))

    def test_it_serves_the_hubs_own_page_read_only_and_its_renderer(self):
        code, page = self.req(self.v())
        self.assertEqual(code, 200)
        self.assertIn(b"<title>sb hub</title>", page)
        self.assertIn(b'data-readonly="1"', page)
        code, js = self.req(self.v("board.js"))
        self.assertEqual((code, js[:30]), (200, Path(LAN).with_name("sbhub_board.js").read_bytes()[:30]))
        self.assertNotIn(b'data-readonly="1"', urllib.request.urlopen(f"http://127.0.0.1:{self.port}/").read())

    def test_reads_go_through_and_only_three_display_writes_do(self):
        self.hub("report", "--agent", "a", "--project", ".", "--state", "idle")
        code, body = self.req(self.v("api/state"))
        self.assertEqual(code, 200)
        self.assertIn("a", json.loads(body)["agents"])
        for path in ("api/queue/set", "api/queue/pause", "api/send", "api/answer", "api/ticket/done", "api/report"):
            self.assertEqual(self.req(self.v(path), {"keys": [], "version": 0, "paused": False})[0], 403, path)
        code, body = self.req(self.v("api/queue/clear-finished"), {})
        self.assertEqual((code, json.loads(body)["ok"]), (200, True))
        self.assertEqual(self.req(self.v("api/agents/clear-quiet"), {})[0], 200)
        self.assertEqual(self.req(self.v("api/agents/dismiss"), {"agent": "a"})[0], 200)
        self.assertNotIn("a", self.get("/api/state")["agents"])
        self.assertEqual(self.req(self.v("api/queue/clear-finished"), {}, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req(self.v("api/queue/clear-finished"), {}, {"Content-Type": "text/plain"})[0], 403)

    def test_a_picture_the_hub_does_not_have_is_its_empty_404(self):
        self.assertEqual(self.req(self.v("api/media?key=repo%2Fone%231&name=a.png"), headers={"Range": "bytes=0-1"}), (404, b""))

    def test_a_hub_that_is_down_is_a_502_not_a_hang(self):
        self.server.kill()
        self.server.wait()
        wait_for(lambda: self.req(self.v("api/state"))[0] == 502)


if __name__ == "__main__":
    unittest.main()
