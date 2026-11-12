"""sbhub's server and command line, run as real subprocesses against a free port."""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

from helpers import HubCase, free_port, wait_for, SCRIPT

sys.path.insert(0, os.path.dirname(SCRIPT))
import sbhub  # noqa: E402


class HubCliTest(HubCase):
    def test_report_shows_in_state(self):
        self.hub("report", "--agent", "a", "--project", ".", "--state", "working", "--done", "1", "--total", "5")
        a = self.get("/api/state")["agents"]["a"]
        self.assertEqual((a["state"], a["total"]), ("working", "5"))
        self.assertTrue(os.path.isabs(a["project"]))

    def test_second_lock_exits_1_and_names_the_holder(self):
        self.assertEqual(self.hub("lock", "k", "--by", "a").stdout.strip(), "ok")
        r = self.hub("lock", "k", "--by", "b")
        self.assertEqual((r.returncode, r.stderr.strip()), (1, "held by a"))
        self.assertEqual(self.hub("unlock", "k", "--by", "a").stdout.strip(), "ok")
        self.assertEqual(self.hub("lock", "k", "--by", "b").stdout.strip(), "ok")

    def test_http_lock_refusal_is_409(self):
        self.post("/api/lock", {"key": "k", "by": "a"})
        self.assertEqual(self.post("/api/lock", {"key": "k", "by": "b"})[0], 409)

    def test_ask_prints_the_owners_click(self):
        p = self.popen("ask", "--agent", "a", "--q", "q?", "--options", "x|y", "--default", "y", "--wait", "20")
        qid = wait_for(lambda: next(iter(self.get("/api/state")["questions"]), None))
        self.post("/api/answer", {"qid": qid, "answer": "x"})
        self.assertEqual(p.communicate(timeout=10)[0].strip(), "x")

    def test_ask_falls_back_to_its_default(self):
        r = self.hub("ask", "--agent", "a", "--q", "q?", "--options", "x|y", "--default", "y", "--wait", "2")
        self.assertEqual(r.stdout.strip(), "y")
        self.assertEqual(next(iter(self.get("/api/state")["questions"].values()))["by"], "default")

    def test_bad_question_is_refused(self):
        code, body = self.post("/api/ask", {"agent": "a", "q": "q?", "options": ["x"], "default": "x", "wait": 0})
        self.assertEqual((code, body["ok"]), (400, False))

    def test_unknown_question_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as c:
            self.get("/api/question/nope")
        c.exception.close()
        self.assertEqual(c.exception.code, 404)
        self.assertEqual(self.post("/api/answer", {"qid": "nope", "answer": "x"})[0], 404)

    def test_the_page_placeholder_is_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_the_page_is_served_and_names_its_endpoints(self):
        html = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/").read().decode()
        for needle in ("<title>sb hub</title>", "/api/state", "/api/answer", "prefers-color-scheme", "application/json"):
            self.assertIn(needle, html)

    def test_the_page_has_no_inline_handlers_and_no_outside_resource(self):
        html = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/").read().decode()
        self.assertNotIn("onclick", html.lower())
        for outside in ("http://", "https://", "//cdn", "@import", "url("):
            self.assertNotIn(outside, html)

    def test_state_command_prints_state(self):
        self.hub("report", "--agent", "a", "--state", "idle")
        self.assertIn("a", json.loads(self.hub("state").stdout)["agents"])

    def test_hub_down_never_fails_report_or_ask(self):
        down = free_port()
        self.assertEqual(self.hub("report", "--agent", "a", "--state", "working", port=down).returncode, 0)
        t = time.time()
        r = self.hub("ask", "--agent", "a", "--q", "q?", "--options", "x|y", "--default", "y", "--wait", "30", port=down)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "y"))
        self.assertLess(time.time() - t, 10)
        r = self.hub("lock", "k", "--by", "a", port=down)
        self.assertEqual((r.returncode, r.stderr.strip()), (2, "sbhub: not running"))
        self.assertEqual(self.hub("state", port=down).stdout.strip(), "{}")

    def raw_post(self, headers, path="/api/report", body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     json.dumps(body or {"agent": "a", "state": "idle"}).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def test_a_post_needs_the_json_content_type(self):
        self.assertEqual(self.raw_post({"Content-Type": "text/plain"}), 403)
        self.assertEqual(self.raw_post({}), 403)
        self.assertNotIn("a", self.get("/api/state")["agents"])

    def test_a_post_from_another_origin_is_refused(self):
        json_type = {"Content-Type": "application/json"}
        self.assertEqual(self.raw_post({**json_type, "Origin": "http://evil.example"}), 403)
        self.assertEqual(self.raw_post({**json_type, "Origin": "http://127.0.0.1:1"}), 403)
        self.assertEqual(self.raw_post({**json_type, "Origin": f"http://127.0.0.1:{self.port}"}), 200)
        self.assertEqual(self.raw_post({**json_type, "Origin": f"http://localhost:{self.port}"}), 200)

    def test_a_non_numeric_port_variable_falls_back(self):
        for bad in ("abc", "", "99999999"):
            os.environ["SB_HUB_PORT"] = bad
            try:
                self.assertEqual(sbhub.default_port(), 8765, bad)
            finally:
                del os.environ["SB_HUB_PORT"]
        os.environ["SB_HUB_PORT"] = "9000"
        try:
            self.assertEqual(sbhub.default_port(), 9000)
        finally:
            del os.environ["SB_HUB_PORT"]
        env = {**self.env, "SB_HUB_PORT": "abc"}
        r = subprocess.run([sys.executable, SCRIPT, "state"], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0)

    def raw_get(self, headers, path="/api/state"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, e.headers

    def test_a_request_for_another_host_is_refused(self):
        self.assertEqual(self.raw_get({"Host": f"evil.example:{self.port}"})[0], 403)
        self.assertEqual(self.raw_get({"Host": f"localhost:{self.port}"})[0], 200)
        self.assertEqual(self.raw_post({"Content-Type": "application/json", "Host": f"evil.example:{self.port}"}), 403)
        self.assertNotIn("a", self.get("/api/state")["agents"])

    def test_every_response_refuses_framing_and_sniffing(self):
        for path in ("/", "/api/state", "/nope"):
            headers = self.raw_get({}, path)[1]
            self.assertEqual((headers["X-Frame-Options"], headers["X-Content-Type-Options"]), ("DENY", "nosniff"))

    def test_the_page_heads_the_needs_you_box_and_wraps_a_long_session_row(self):
        html = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/").read().decode()
        self.assertIn("<h2>Needs you</h2>", html)
        self.assertIn(".row{flex-wrap:wrap}", html)

    def test_a_slow_notification_does_not_delay_the_answer(self):
        slow = []
        real = sbhub.notify
        sbhub.notify = lambda *a: (slow.append(a), time.sleep(3))
        self.addCleanup(setattr, sbhub, "notify", real)
        hub = sbhub.Hub(self._tmp.name)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), sbhub.make_handler(hub))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        p = subprocess.Popen([sys.executable, SCRIPT, "ask", "--agent", "a", "--q", "q?", "--options", "x|y",
                              "--default", "y", "--wait", "6", "--port", str(port)],
                             stdout=subprocess.PIPE, text=True, env=self.env)
        self.procs.append(p)
        qid = wait_for(lambda: next(iter(hub.state()["questions"]), None))
        time.sleep(1)
        hub.answer(qid, "x")
        self.assertEqual(p.communicate(timeout=10)[0].strip(), "x")
        self.assertEqual(len(slow), 1)

    def test_an_unexpected_error_is_a_500_not_a_dropped_connection(self):
        class Broken(sbhub.Hub):
            def report(self, d):
                raise RuntimeError("boom")

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), sbhub.make_handler(Broken(self._tmp.name)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        code, out = sbhub.call(server.server_address[1], "/api/report", {"agent": "a"})
        self.assertEqual((code, out["ok"]), (500, False))
        self.assertIn("boom", out["error"])


if __name__ == "__main__":
    unittest.main()
