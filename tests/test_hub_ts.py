"""The TypeScript server (skills/sb/hub/packages/server) on the hub's port, with sbhub.py as its child.

Every HubCase suite runs against it with SB_HUB_SERVER=ts; these tests run it in the default discovery too.
They skip without node 24 or the workspace's packages (pnpm --dir skills/sb/hub install).
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from helpers import HubCase, NODE, free_port, serve_command, wait_for

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "skills" / "sb" / "scripts" / "sbhub_service.sh"
HONO = ROOT / "skills" / "sb" / "hub" / "packages" / "server" / "node_modules" / "hono"


def node_major():
    try:
        out = subprocess.run([NODE, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


READY = node_major() >= 24 and HONO.exists()
WHY = "needs node 24 and `pnpm --dir skills/sb/hub install`"


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # a zombie still answers kill 0
    return "Z" not in subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout


@unittest.skipUnless(READY, WHY)
class TsServerTest(HubCase):
    ts = True

    def test_the_cli_reports_locks_and_reads_state_through_it(self):
        self.assertEqual(self.hub("report", "--agent", "a", "--state", "working", "--done", "1", "--total", "3").returncode, 0)
        a = self.get("/api/state")["agents"]["a"]
        self.assertEqual((a["state"], a["done"], a["total"]), ("working", "1", "3"))
        self.assertEqual(self.hub("lock", "unity", "--by", "a").stdout.strip(), "ok")
        held = self.hub("lock", "unity", "--by", "b")
        self.assertEqual((held.returncode, held.stderr.strip()), (1, "held by a"))
        self.assertEqual(self.hub("unlock", "unity", "--by", "a").returncode, 0)

    def test_the_root_opens_the_new_board_and_the_old_one_is_at_classic(self):
        get = lambda path: urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)
        built = (ROOT / "skills" / "sb" / "hub" / "packages" / "web" / "dist" / "index.html").exists()
        try:
            root = get("/").read().decode()
            self.assertIn('<div id="root">', root)
        except urllib.error.HTTPError as e:  # not built: it says how to build it
            self.assertFalse(built)
            with e:
                self.assertIn(b"pnpm --dir skills/sb/hub build", e.read())
        self.assertIn('<script src="board.js">', get("/classic").read().decode())

    def test_its_python_hub_listens_elsewhere(self):
        pid = int(Path(self._tmp.name, "hub-python.pid").read_text())
        self.assertTrue(alive(pid))
        cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
        self.assertIn("sbhub.py serve --port 0", cmd)


@unittest.skipUnless(READY, WHY)
class TsLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.env = {**os.environ, "SB_HUB_HOME": self._tmp.name, "SB_HUB_NOTIFY": "0", "SB_HUB_QUEUE": "0"}
        for k in ("SB_HUB_AGENT", "SB_HUB_PARENT"):
            self.env.pop(k, None)
        self.pidfile = Path(self._tmp.name, "hub-python.pid")
        self.addCleanup(self._reap)

    def _reap(self):
        for pid in getattr(self, "pids", []):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def start(self, port, args=None, env=None):
        p = subprocess.Popen(args or serve_command(port, ts=True), stdout=subprocess.PIPE, text=True, env=env or self.env)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        self.assertEqual(p.stdout.readline().strip(), f"sb hub on http://127.0.0.1:{port}")
        self.pids = [*getattr(self, "pids", []), int(self.pidfile.read_text())]
        return p

    def test_SB_HUB_PORT_is_honoured(self):
        port = free_port()
        from helpers import TS_SERVER
        self.start(port, [NODE, TS_SERVER], {**self.env, "SB_HUB_PORT": str(port)})

    def test_sigterm_stops_its_python_hub_too(self):
        p = self.start(free_port())
        child = int(self.pidfile.read_text())
        p.terminate()
        self.assertEqual(p.wait(timeout=10), 0)
        wait_for(lambda: not alive(child))
        self.assertFalse(self.pidfile.exists())

    def test_a_python_hub_left_by_a_killed_server_is_killed_by_the_next(self):
        p = self.start(free_port())
        orphan = int(self.pidfile.read_text())
        p.kill()  # as sbhub_service.sh restarts it: SIGKILL, so the workers live on
        p.wait()
        self.assertTrue(alive(orphan))
        self.start(free_port())
        wait_for(lambda: not alive(orphan))
        self.assertNotEqual(int(self.pidfile.read_text()), orphan)

    def test_a_taken_port_stops_it_before_any_python_hub_starts(self):
        port = free_port()
        self.start(port)
        first = int(self.pidfile.read_text())
        r = subprocess.run(serve_command(port, ts=True), capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot listen", r.stderr)
        self.assertTrue(alive(first))


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("plutil"), "macOS LaunchAgents")
class ServicePlistTest(unittest.TestCase):
    def plist(self, *args):
        r = subprocess.run(["bash", str(SERVICE), "plist", *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lint = subprocess.run(["plutil", "-lint", "-"], input=r.stdout, capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout)
        return r.stdout

    @unittest.skipUnless(shutil.which("node"), "node")
    def test_ts_starts_the_typescript_server_on_8765(self):
        out = self.plist("--ts")
        self.assertIn("/skills/sb/hub/packages/server/src/index.ts</string>", out)
        self.assertIn("<string>--port</string>\n    <string>8765</string>", out)
        self.assertNotIn("sbhub.py", out)

    def test_plain_still_starts_sbhub_py(self):
        out = self.plist()
        self.assertIn("/skills/sb/scripts/sbhub.py</string>\n    <string>serve</string>", out)
        self.assertNotIn("index.ts", out)


if __name__ == "__main__":
    unittest.main()
