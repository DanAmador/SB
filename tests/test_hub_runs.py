"""The run listing behind History (sbruns.py): queue items and the vault's run folders, merged, newest first, paged."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbruns  # noqa: E402

REPORT = ("# 7: An older run\n\nCommit: abc1234 (branch sb/one)\n\n## Hub checks\n\n"
          "Checked by the sb hub at 2026-11-12 02:00: failed: check failed: pnpm test, commit abc1234.\n\n"
          "- `pnpm test`: exit 1, 3.5 s\n\n  ```\n  1 failed\n  ```\n- `true`: timed out, 20.0 s\n")


def item(key, state="done", ended=1000.0, **more):
    return {"key": key, "kind": "ticket", "agent": "main", "state": state, "note": "", "commit": None, "tries": 1,
            "started": ended - 600, "ended": ended, **more}


class RunsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        self.folder = self.vault / "wayfinder" / "proj" / "runs" / "2026-11-12-one"
        (self.folder / "7-media").mkdir(parents=True)
        (self.folder / "7.md").write_text(REPORT, encoding="utf-8")
        (self.folder / "7.log").write_text(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading."}]}}) + "\nstderr\n")
        (self.folder / "7-media" / "a.png").write_bytes(b"png")
        (self.folder / "7-media" / "notes.txt").write_text("not a picture")
        os.utime(self.folder / "7.md", (500, 500))

    def keys(self, items, **kw):
        return [r["key"] for r in sbruns.list_runs(self.vault, items, **kw)["runs"]]

    def test_the_vault_run_is_read_from_its_report(self):
        (run,) = sbruns.list_runs(self.vault, [])["runs"]
        self.assertEqual((run["key"], run["map"], run["project"], run["title"]), ("proj/one#7", "proj/one", "proj", "An older run"))
        self.assertEqual((run["outcome"], run["commit"], run["pictures"], run["reason"]),
                         ("failed", "abc1234", ["a.png"], "pnpm test failed"))
        self.assertEqual(run["ended"], 500)

    def test_queue_items_and_the_vault_merge_newest_first(self):
        items = [item("proj/one#7", "done", ended=2000.0, run=str(self.folder), commit="fff0000"),
                 item("proj/one#8", "skipped", ended=1500.0, note="claimed: someone"),
                 item("proj/one#9", "running"), {**item("job:x"), "kind": "job"}]
        runs = sbruns.list_runs(self.vault, items)["runs"]
        self.assertEqual([r["key"] for r in runs], ["proj/one#7", "proj/one#8"])  # a running item and a job are not runs
        self.assertEqual((runs[0]["outcome"], runs[0]["commit"], runs[0]["pictures"], runs[0]["reason"]), ("done", "fff0000", ["a.png"], ""))
        self.assertEqual((runs[1]["outcome"], runs[1]["reason"]), ("skipped", "someone else had claimed it"))

    def test_a_key_in_the_cleared_log_too_keeps_its_newest_end(self):
        items = [item("proj/one#8", "failed", ended=100.0, note="no commit after abc"), item("proj/one#8", "done", ended=900.0)]
        (run,) = [r for r in sbruns.list_runs(self.vault, items)["runs"] if r["key"] == "proj/one#8"]
        self.assertEqual((run["outcome"], run["ended"]), ("done", 900.0))

    def test_since_and_paging(self):
        items = [item("proj/one#%d" % n, ended=1000.0 + n) for n in range(10, 15)]
        page = sbruns.list_runs(self.vault, items, since=900, offset=1, limit=2)
        self.assertEqual((page["total"], page["offset"], page["limit"]), (5, 1, 2))
        self.assertEqual([r["key"] for r in page["runs"]], ["proj/one#13", "proj/one#12"])
        self.assertEqual(self.keys(items, since=1013), ["proj/one#14", "proj/one#13"])

    def test_detail_carries_checks_report_and_a_readable_log(self):
        d = sbruns.detail(self.vault, [], "proj/one#7")
        self.assertEqual([(c["cmd"], c["code"], c["secs"]) for c in d["checks"]], [("pnpm test", 1, 3.5), ("true", None, 20.0)])
        self.assertEqual(d["checks"][0]["tail"], "1 failed")
        self.assertIn("An older run", d["report"])
        self.assertEqual(d["log"], "Reading.\nstderr")
        with self.assertRaises(KeyError):
            sbruns.detail(self.vault, [], "proj/one#99")

    def test_a_queue_item_keeps_its_own_checks(self):
        checks = [{"cmd": "make", "code": 0, "secs": 1.0, "tail": ""}]
        d = sbruns.detail(self.vault, [item("proj/one#7", run=str(self.folder), checks=checks)], "proj/one#7")
        self.assertEqual(d["checks"], checks)

    def test_media_names_never_leave_the_folder(self):
        self.assertEqual(sbruns.media_file(self.vault, [], "proj/one#7", "a.png").name, "a.png")
        for bad in ("../7.md", "notes.txt", "a/b.png", "", "..", "missing.png"):
            with self.assertRaises(KeyError, msg=bad):
                sbruns.media_file(self.vault, [], "proj/one#7", bad)

    def test_plain_reasons(self):
        r = sbruns.plain_reason
        self.assertEqual(r("no commit after abc123", "failed"), "ended without a commit")
        self.assertEqual(r("check failed: pnpm test\nmore", "failed"), "pnpm test failed")
        self.assertEqual(r("", "failed"), "no reason recorded")
        self.assertEqual(r("blocked: after Draw", "skipped"), "waited on “Draw”")
        self.assertEqual(r("no longer open: dropped: merged into 12", "skipped"), "its ticket was dropped while it waited: merged into 12")


if __name__ == "__main__":
    unittest.main()
