"""sbhub_snapshot: refuses cleanly without a hub; with one and Chrome, writes a PNG."""
import os
import subprocess
import sys
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import HubCase, free_port, SCRIPT

sys.path.insert(0, str(Path(SCRIPT).parent))
import sbhub  # noqa: E402
import sbhub_snapshot  # noqa: E402

SNAP = str(Path(SCRIPT).with_name("sbhub_snapshot.py"))
sys.path.insert(0, str(Path(SNAP).parent))
import sbhub_snapshot  # noqa: E402


class SnapshotTest(HubCase):
    def run_snap(self, *args):
        return subprocess.run([sys.executable, SNAP, *args], capture_output=True, text=True, env=self.env, timeout=120)

    @unittest.skipUnless(sbhub_snapshot.chrome(), "Chrome is not installed")
    def test_no_hub_is_refused_in_one_line(self):
        r = self.run_snap("--port", str(free_port()))
        self.assertEqual((r.returncode, r.stdout, len(r.stderr.strip().splitlines())), (2, "", 1))

    @unittest.skipUnless(sbhub_snapshot.chrome(), "Chrome is not installed")
    def test_writes_a_png(self):
        out = os.path.join(self._tmp.name, "board.png")
        r = self.run_snap("--port", str(self.port), "--out", out)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, out), r.stderr)
        with open(out, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")


NOW = time.mktime((2026, 11, 14, 15, 0, 0, 0, 0, -1))
ROWS = [{"map": "a/one", "num": n, "title": t, "state": "ready", "reason": "ready"}
        for n, t in ((1, "Alpha"), (2, "Beta"), (3, "Gamma"))] + [
    {"map": "b/two", "num": 7, "title": "Seven", "state": "ready", "reason": "ready"},
    {"map": "b/two", "num": 8, "title": "Grill me", "state": "waits for you", "reason": "a grilling ticket needs you"},
    {"map": "c/idle", "num": 1, "title": "Idle", "state": "waits for you", "reason": "x"}]
ITEMS = [
    {"key": "a/one#1", "kind": "ticket", "state": "done", "note": "all checks passed", "ended": NOW - 600},
    {"key": "a/one#2", "kind": "ticket", "state": "running", "started": NOW - 12 * 60},
    {"key": "a/one#3", "kind": "ticket", "state": "queued"},
    {"key": "b/two#7", "kind": "ticket", "state": "failed", "note": "check |npm test| failed", "ended": NOW - 60},
    {"key": "b/two#4", "kind": "ticket", "state": "queued"},
    {"key": "b/two#9", "kind": "ticket", "state": "done", "note": "old", "ended": NOW - 3 * 86400},
    {"key": "x", "kind": "job", "state": "queued"}]
FILES = {"a/one#1": "wayfinder/a/one/issues/001 Alpha", "a/one#2": "wayfinder/a/one/issues/002 Beta",
         "b/two#7": "wayfinder/b/two/issues/007 Seven"}


class NightNoteTest(unittest.TestCase):
    def note(self, paused=False, items=ITEMS):
        return sbhub_snapshot.night_note({"paused": paused, "items": items}, ROWS, NOW, FILES,
                                         {"a/one#2": "Edit sbhub.py"}, {"a/one#1": "wayfinder/a/one/runs/n/1"})

    def test_two_maps_blocks_counts_order_links(self):
        t = self.note()
        lines = t.splitlines()
        self.assertEqual(lines[:5], ["---", "tags:", "  - wayfinder/run", "---", lines[4]])
        self.assertTrue(lines[4].startswith("Written 2026-11-14 15:00") and lines[4].endswith("queue running"))
        self.assertLess(t.index("## [[wayfinder/a/one/map|a/one]]"), t.index("## [[wayfinder/b/two/map|b/two]]"))
        self.assertNotIn("c/idle", t)  # nothing of that map runs, waits or ended today
        self.assertIn("1 running \u00b7 1 queued \u00b7 1 done", t)
        self.assertIn("1 queued \u00b7 1 failed", t)
        self.assertIn("- [[wayfinder/a/one/issues/002 Beta|002 Beta]] \u00b7 12 min \u00b7 Edit sbhub.py", t)
        self.assertIn("1. 003 Gamma", t)  # no file known: the title shows as plain text
        self.assertIn("- [[wayfinder/a/one/issues/001 Alpha|001 Alpha]] \u00b7 done \u2014 all checks passed"
                      " \u00b7 [[wayfinder/a/one/runs/n/1|report]]", t)
        self.assertIn("failed \u2014 check /npm test/ failed", t)  # a pipe would break the link syntax
        self.assertNotIn("old", t)  # ended three days ago
        self.assertNotIn("x \u00b7", t)  # jobs are not tickets
        owner = t.split("## Waits for you")[1]
        self.assertIn("008 Grill me", owner)
        self.assertIn("failed, needs a look", owner)
        self.assertNotIn("Idle", owner)

    def test_ended_ticket_not_in_rows_shows_its_title(self):
        item = {"key": "a/one#50", "kind": "ticket", "state": "done", "ended": NOW - 5, "title": "Shipped thing"}
        t = sbhub_snapshot.night_note({"paused": False, "items": [item]}, ROWS, NOW, {})
        self.assertIn("- 050 Shipped thing \u00b7 done", t)
        gone = dict(item, key="a/one#51", title=None)
        t = sbhub_snapshot.night_note({"paused": False, "items": [gone]}, ROWS, NOW, {"a/one#51": "wayfinder/a/one/issues/done/051 From file"})
        self.assertIn("|051 From file]]", t)

    def test_queue_word(self):
        self.assertTrue(self.note(paused=True).splitlines()[4].endswith("queue paused"))
        self.assertTrue(self.note(items=[]).splitlines()[4].endswith("queue empty"))
        self.assertIn("nothing", self.note(items=[]).split("## Waits for you")[1])

    def test_time_alone_is_not_a_change(self):
        a = self.note()
        b = sbhub_snapshot.night_note({"paused": False, "items": ITEMS}, ROWS, NOW + 60, FILES,
                                      {"a/one#2": "Edit sbhub.py"}, {"a/one#1": "wayfinder/a/one/runs/n/1"})
        self.assertTrue(sbhub_snapshot.same_note(a, b) is False)  # the minute count moved
        c = sbhub_snapshot.night_note({"paused": False, "items": [dict(i, started=i.get("started") and i["started"] + 60) for i in ITEMS]},
                                      ROWS, NOW + 60, FILES, {"a/one#2": "Edit sbhub.py"}, {"a/one#1": "wayfinder/a/one/runs/n/1"})
        self.assertTrue(sbhub_snapshot.same_note(a, c))

    def test_write_replaces_whole_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "runs" / "hub-now.md"
            sbhub_snapshot.write_whole(p, "one\n" * 50)
            with mock.patch("os.replace", wraps=__import__("os").replace) as rep:
                sbhub_snapshot.write_whole(p, "two\n")
            self.assertEqual(p.read_text(), "two\n")
            self.assertEqual(rep.call_count, 1)
            self.assertNotEqual(Path(rep.call_args[0][0]), p)  # the text went to a temp file first
            self.assertEqual([x.name for x in Path(d, "runs").iterdir()], ["hub-now.md"])


class NightNoteWriteTest(unittest.TestCase):
    def test_supervisor_writes_only_when_the_text_changes(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "V"
            (vault / "wayfinder").mkdir(parents=True)
            hub = sbhub.Hub(Path(d) / "home", run=lambda: json.dumps([]))
            hub.tickets()
            hub.queue_pause(False)
            sup = sbhub.Supervisor(hub, port=1)
            sup.note_path = vault / "wayfinder" / "runs" / "hub-now.md"
            with mock.patch.dict("os.environ", {"SB_VAULT": str(vault)}), \
                    mock.patch.object(sbhub_snapshot, "write_whole", wraps=sbhub_snapshot.write_whole) as w:
                sup._night_note()
                sup._night_note()
                self.assertEqual(w.call_count, 1)
                self.assertTrue(sup.note_path.read_text().splitlines()[4].endswith("queue empty"))
                with hub._lock:
                    hub._data["queue"]["items"].append({"key": "r/m#1", "kind": "ticket", "state": "queued"})
                sup._night_note()
                self.assertEqual(w.call_count, 2)
                self.assertIn("1 queued", sup.note_path.read_text())

    def test_new_wait_and_new_day_rewrite_while_nothing_runs_and_same_shape_leaves_the_disk_note(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "V"
            (vault / "wayfinder").mkdir(parents=True)
            hub = sbhub.Hub(Path(d) / "home", run=lambda: json.dumps([]))
            hub.tickets()
            sup = sbhub.Supervisor(hub, port=1)
            sup.note_path = vault / "wayfinder" / "runs" / "hub-now.md"
            clock = [NOW]
            hub.now = lambda: clock[0]
            with hub._lock:
                hub._data["queue"]["items"] += [{"key": "r/m#1", "kind": "ticket", "state": "queued"},
                                                {"key": "r/m#3", "kind": "ticket", "state": "done", "ended": NOW - 60}]
            with mock.patch.dict("os.environ", {"SB_VAULT": str(vault)}), \
                    mock.patch.object(sbhub_snapshot, "write_whole", wraps=sbhub_snapshot.write_whole) as w:
                sup._night_note()
                self.assertEqual(w.call_count, 1)
                # no-rewrite path against the note on disk: the supervisor forgets its text, the shape is the same
                clock[0] += 60
                sup.note_seen = (None, 0, "")
                sup._night_note()
                self.assertEqual(w.call_count, 1)  # same text on disk: not rewritten
                self.assertIn("Written 2026-11-14 15:00", sup.note_path.read_text())
                # a new grilling ticket waits: rewritten although nothing runs
                hub._tcache = (hub._tcache[0], [{"map": "r/m", "num": 2, "title": "Grill", "state": "waits for you", "reason": "a grilling ticket needs you"}])
                sup._night_note()
                self.assertEqual(w.call_count, 2)
                self.assertIn("002 Grill", sup.note_path.read_text())
                sup._night_note()
                self.assertEqual(w.call_count, 2)
                # a new day: only the date moved, and yesterday's ended ticket drops out of the note
                self.assertIn("r/m#3", sup.note_path.read_text())
                clock[0] += 86400
                sup._night_note()
                self.assertEqual(w.call_count, 3)
                self.assertNotIn("r/m#3", sup.note_path.read_text())


if __name__ == "__main__":
    unittest.main()
