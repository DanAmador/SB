"""Filing a ticket that reads like an open one is stopped before it lands, so agents add to the ticket that exists
instead of filing the same problem twice. Semantra (search by meaning) does the reading; without it nothing changes."""
import json
import sys
import time
import unittest

from helpers import VaultCase

MAP = "monorepo/overrides"


class LookAlikes(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", MAP, "--why", "Because.", "--title", "Overrides", "--destination", "Somewhere.",
                "--repo", "/code/monorepo")
        self.sb("init", "homestudio/other", "--why", "Because.", "--title", "Other", "--destination", "There.",
                "--repo", "/code/homestudio")
        self.first = self.new("Stop keeps the worker's work").stdout.strip()

    def fake_semantra(self, hits, sleep=0):
        """A `semantra` on PATH that answers search with `hits` and index with nothing, recording each call."""
        bin_ = self.vault.parent / "bin"
        bin_.mkdir(exist_ok=True)
        cli = bin_ / "semantra"
        cli.write_text(f"#!{sys.executable}\nimport json, sys, time\n"
                       f"open({str(bin_ / 'calls')!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                       f"time.sleep({sleep})\n"
                       f"print(json.dumps({{'hits': {hits!r}}}))\n")
        cli.chmod(0o755)
        self.calls = bin_ / "calls"
        return f"{bin_}:/usr/bin:/bin"

    def new(self, title, *extra, ok=True, path="/usr/bin:/bin", map_=MAP):
        return self.sb("new", map_, "--why", "Because.", "--title", title, "--no-sync", *extra, ok=ok, path=path)

    def issue(self, map_folder, name):
        return next(p for p in (self.vault / "wayfinder" / map_folder / "issues").glob("*.md") if name in p.name)

    def rel(self, p):
        return str(p.relative_to(self.vault))

    def test_an_open_ticket_that_reads_the_same_stops_the_new_one(self):
        first = self.rel(self.issue(MAP, "Stop keeps"))
        path = self.fake_semantra([{"path": first, "score": 1, "cosine": 0.56}])
        r = self.new("Stopping a worker saves its work", ok=False, path=path)
        self.assertIn(first, r.stderr)
        self.assertIn("sbmap comment", r.stderr)
        self.assertIn("--not-a-duplicate", r.stderr)
        self.assertEqual(len(list((self.vault / "wayfinder" / MAP / "issues").glob("*.md"))), 1)

    def test_not_a_duplicate_files_it_without_asking_semantra(self):
        first = self.rel(self.issue(MAP, "Stop keeps"))
        path = self.fake_semantra([{"path": first, "score": 1, "cosine": 0.9}])
        self.new("Stopping a worker saves its work", "--not-a-duplicate", path=path)
        self.assertFalse(self.calls.exists())

    def test_weak_resolved_or_other_project_hits_do_not_stop_it(self):
        other = self.rel(self.vault / self.new("Stop keeps work", map_="homestudio/other").stdout.strip())
        first = self.rel(self.issue(MAP, "Stop keeps"))
        done = self.write(f"wayfinder/{MAP}/issues/done/009 Old.md", "---\nstatus: Project.Finished\n---\n")
        path = self.fake_semantra([{"path": first, "score": 1, "cosine": 0.44},
                                   {"path": self.rel(done), "score": 1, "cosine": 0.9},
                                   {"path": other, "score": 1, "cosine": 0.9}])
        self.new("Stopping a worker saves its work", path=path)
        self.assertIn('"search"', self.calls.read_text())

    def test_a_slow_index_skips_the_check_and_says_so(self):
        first = self.rel(self.issue(MAP, "Stop keeps"))
        path = self.fake_semantra([{"path": first, "score": 1, "cosine": 0.9}], sleep=5)
        env_path = path
        r = self.sb_env("new", MAP, "--why", "Because.", "--title", "Slow", "--no-sync", path=env_path,
                        SB_SEMANTRA_TIMEOUT="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("duplicate check skipped", r.stderr)

    def test_a_finished_night_refreshes_the_index_in_the_background(self):
        path = self.fake_semantra([])
        self.sb("close", "--finished", path=path)
        for _ in range(50):
            if self.calls.exists() and '"index"' in self.calls.read_text():
                break
            time.sleep(0.1)
        call = json.loads(self.calls.read_text().splitlines()[0])
        self.assertEqual(call[:3], ["index", "--vault", str(self.vault)])

    def sb_env(self, *args, path, **extra):
        import subprocess
        from helpers import SBMAP
        return subprocess.run([sys.executable, str(SBMAP), *args], capture_output=True, text=True,
                              env=self.env(path, **extra), cwd=self.vault)


if __name__ == "__main__":
    unittest.main()
