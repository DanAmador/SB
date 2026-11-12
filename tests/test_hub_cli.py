"""sbhub's server and command line, run as real subprocesses against a free port."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts" / "sbhub.py")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(fn, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


class HubCliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "SB_HUB_HOME": self._tmp.name, "SB_HUB_NOTIFY": "0"}
        self.env.pop("SB_HUB_PORT", None)
        self.port = free_port()
        self.procs = []
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._kill_all)
        self.server = subprocess.Popen([sys.executable, SCRIPT, "serve", "--port", str(self.port)],
                                       stdout=subprocess.PIPE, text=True, env=self.env)
        self.procs.append(self.server)
        self.assertEqual(self.server.stdout.readline().strip(), f"sb hub on http://127.0.0.1:{self.port}")

    def _kill_all(self):
        for p in self.procs:
            p.kill()
            p.wait()
            if p.stdout:
                p.stdout.close()

    def hub(self, *args, port=None):
        return subprocess.run([sys.executable, SCRIPT, *args, "--port", str(port or self.port)],
                              capture_output=True, text=True, env=self.env, timeout=30)

    def popen(self, *args):
        p = subprocess.Popen([sys.executable, SCRIPT, *args, "--port", str(self.port)],
                             stdout=subprocess.PIPE, text=True, env=self.env)
        self.procs.append(p)
        return p

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return json.load(r)

    def post(self, path, data):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(data).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

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


if __name__ == "__main__":
    unittest.main()
