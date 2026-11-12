"""A throwaway vault per test, and sbmap run against it as the agent runs it: a subprocess."""
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
from datetime import date
from pathlib import Path

SBMAP = Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts" / "sbmap.py"
TODAY = date.today().isoformat()


class VaultCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / "Vault"
        self.vault.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, path="/usr/bin:/bin", **extra):
        # PATH without /usr/local/bin keeps the real Obsidian CLI out of the tests
        return {**os.environ, "SB_VAULT": str(self.vault), "PATH": path, **extra}

    def sb(self, *args, stdin=None, ok=True, path="/usr/bin:/bin"):
        """Run sbmap; ok=True asserts exit 0, ok=False asserts non-zero, ok=None asserts nothing."""
        env = self.env(path)
        r = subprocess.run([sys.executable, str(SBMAP), *args], capture_output=True, text=True,
                           env=env, input=stdin, cwd=self.vault)
        if ok is True:
            self.assertEqual(r.returncode, 0, f"sbmap {' '.join(args)}\n{r.stdout}{r.stderr}")
        elif ok is False:
            self.assertNotEqual(r.returncode, 0, f"sbmap {' '.join(args)} should fail\n{r.stdout}")
        return r

    def popen_sb(self, *args):
        """Start sbmap without waiting; the caller waits on the Popen."""
        return subprocess.Popen([sys.executable, str(SBMAP), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.env(), cwd=self.vault)

    def write(self, rel, text):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def read(self, rel):
        return (self.vault / rel).read_text(encoding="utf-8")

    def exists(self, rel):
        return (self.vault / rel).exists()

    # ---- fixtures in the vault's own shape ----

    def ticket(self, map_folder, num, title, status="Project.Finished", type_="research", answer="An answer."):
        return self.write(f"wayfinder/{map_folder}/issues/{num:03d}-{title.lower().replace(' ', '-')}.md", f"""---
wayfinder: ticket
number: {num}
status: {status}
type: {type_}
map: "[[wayfinder/{map_folder}/map|Map]]"
tags:
  - wayfinder/ticket
---
# {title}

## Question

What?

## Answer

{answer}
""")

    def map(self, folder, title="Test map", status="Project.InProgress"):
        return self.write(f"wayfinder/{folder}/map.md", f"""---
wayfinder: map
status: {status}
tags:
  - wayfinder/map/{folder.replace('/', '-')}
---
# {title}

## Destination

Somewhere.

## Decisions so far

## Out of scope
""")


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


class HubCase(unittest.TestCase):
    """A running sbhub on a free port with a temp home; subclass it for tests."""
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

    def hub(self, *args, port=None, stdin=None):
        return subprocess.run([sys.executable, SCRIPT, *args, "--port", str(port or self.port)],
                              capture_output=True, text=True, env=self.env, timeout=30, input=stdin)

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
