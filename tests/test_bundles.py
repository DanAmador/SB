import json
import shutil
import unittest
from pathlib import Path

from helpers import VaultCase

MAP = "monorepo/bundles"
REAL = Path(__file__).parent / "fixtures" / "night-spend"  # a copy of the vault's sb-workflow/night-spend open tickets

class Bundles(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", MAP, "--why", "Because.", "--title", "Bundles", "--destination", "Somewhere.", "--repo", "/code/monorepo")

    def new(self, title, paths=None, blocked=None, tier=None):
        args = ["new", MAP, "--title", title, "--why", "Because.", "--no-sync"]
        if paths:
            args += ["--paths", paths]
        if blocked:
            args += ["--blocked-by", blocked]
        if tier:
            args += ["--tier", tier]
        self.sb(*args)

    def rows(self):
        return {r["num"]: r for r in json.loads(self.sb("tickets", "--json").stdout)}

    def test_three_tickets_bundle_and_read_back(self):
        for n in "abc":
            self.new(n)
        self.new("d", tier="opus")
        self.assertIn("runs on sonnet", self.sb("bundle", MAP, "3,1,2", "--name", "trio").stdout)
        rows = self.rows()
        self.assertEqual([(rows[n]["bundle"], rows[n]["position"]) for n in (3, 1, 2)],
                         [("trio", 1), ("trio", 2), ("trio", 3)])
        self.assertEqual((rows[4]["bundle"], rows[4]["position"]), (None, None))
        self.assertIn("[bundle trio #1]", self.sb("info", MAP).stdout)
        self.assertIn("runs on opus", self.sb("bundle", MAP, "3,4", "--name", "trio").stdout)  # renaming replaces
        self.assertIsNone(self.rows()[1]["bundle"])
        self.sb("bundle", MAP, "--clear", "trio")
        self.assertIsNone(self.rows()[3]["bundle"])
        self.sb("bundle", MAP, "--clear", "trio", ok=False)

    def test_refusals(self):
        for n in "abcde":
            self.new(n)
        self.new("late", blocked="1")                       # 6, blocked by 1
        self.assertIn("2 to 4", self.sb("bundle", MAP, "1,2,3,4,5", "--name", "big", ok=False).stderr)
        self.sb("bundle", MAP, "1", "--name", "one", ok=False)
        self.assertIn("blocked by 001", self.sb("bundle", MAP, "6,1", "--name", "bad", ok=False).stderr)
        self.sb("bundle", MAP, "1,6", "--name", "good")
        self.sb("init", "monorepo/other", "--why", "B.", "--title", "O", "--destination", "S.", "--repo", "/code/monorepo")
        self.sb("new", "monorepo/other", "--title", "x", "--why", "B.", "--no-sync")
        self.assertIn("not in", self.sb("bundle", MAP, "2,9", "--name", "x", ok=False).stderr)
        self.assertIn("already in bundle good", self.sb("bundle", MAP, "1,2", "--name", "x", ok=False).stderr)
        self.assertIsNone(self.rows()[2]["bundle"])

    def test_suggest_pair_not_the_unrelated(self):
        self.new("a", paths="src/x.py")
        self.new("b", paths="src")
        self.new("c", paths="docs/y.md")
        out = self.sb("bundle", MAP, "--suggest").stdout
        self.assertIn(" 1,2 ", out)
        self.assertNotIn("3", out.split("#")[0])
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_suggest_chain_capped_at_four_and_skips_bundled(self):
        self.new("a")
        for i in range(2, 7):
            self.new(str(i), blocked=str(i - 1))
        got = json.loads(self.sb("bundle", MAP, "--suggest", "--json").stdout)
        self.assertEqual([g["tickets"] for g in got], [[1, 2, 3, 4], [5, 6]])
        self.sb("bundle", MAP, "1,2", "--name", "first")
        got = json.loads(self.sb("bundle", MAP, "--suggest", "--json").stdout)
        self.assertEqual([g["tickets"] for g in got], [[3, 4, 5, 6]])

    def test_suggest_on_a_copy_of_the_real_night_spend_map(self):
        shutil.copytree(REAL, self.vault / "wayfinder" / "sb-workflow" / "night-spend")
        real = "sb-workflow/night-spend"
        got = json.loads(self.sb("bundle", real, "--suggest", "--json").stdout)
        self.assertTrue(got)
        for g in got:
            self.assertTrue(2 <= len(g["tickets"]) <= 4)
        lanes = json.loads(self.sb("lanes", real, "--json").stdout)
        self.assertTrue(lanes["lanes"] or lanes["serial"])
        first = got[0]["tickets"]
        self.sb("bundle", real, ",".join(map(str, first)), "--name", "real")
        again = json.loads(self.sb("bundle", real, "--suggest", "--json").stdout)
        self.assertTrue(all(not set(first) & set(g["tickets"]) for g in again))

if __name__ == "__main__":
    unittest.main()
