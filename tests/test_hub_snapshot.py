"""sbhub_snapshot: refuses cleanly without a hub; with one and Chrome, writes a PNG."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import HubCase, free_port, SCRIPT

SNAP = str(Path(SCRIPT).with_name("sbhub_snapshot.py"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class SnapshotTest(HubCase):
    def run_snap(self, *args):
        return subprocess.run([sys.executable, SNAP, *args], capture_output=True, text=True, env=self.env, timeout=120)

    @unittest.skipUnless(os.path.exists(CHROME), "Chrome is not installed")
    def test_no_hub_is_refused_in_one_line(self):
        r = self.run_snap("--port", str(free_port()))
        self.assertEqual((r.returncode, r.stdout, len(r.stderr.strip().splitlines())), (2, "", 1))

    @unittest.skipUnless(os.path.exists(CHROME), "Chrome is not installed")
    def test_writes_a_png(self):
        out = os.path.join(self._tmp.name, "board.png")
        r = self.run_snap("--port", str(self.port), "--out", out)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, out), r.stderr)
        with open(out, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
