import json
import unittest

from helpers import VaultCase

MAP = "monorepo/lanes"


class Lanes(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", MAP, "--title", "Lanes", "--destination", "Somewhere.", "--repo", "/code/monorepo")

    def new(self, title, paths=None, blocked=None):
        args = ["new", MAP, "--title", title, "--no-sync"]
        if paths:
            args += ["--paths", paths]
        if blocked:
            args += ["--blocked-by", blocked]
        return self.sb(*args).stdout.strip()

    def lanes(self, *extra):
        return json.loads(self.sb("lanes", MAP, "--json", *extra).stdout)

    def test_paths_are_a_list_property_from_new_and_set(self):
        path = self.new("First", paths="src/a.py,docs/")
        text = (self.vault / path).read_text()
        self.assertIn("paths:\n  - src/a.py\n  - docs/", text)
        self.sb("set", MAP, "1", "paths=src/b.py", "--no-sync")
        self.assertIn("paths:\n  - src/b.py\n", (self.vault / path).read_text())

    def test_the_split_009_draws(self):
        self.new("Core", paths="a/x.py")                  # 1: opens lane A
        self.new("Web", paths="b")                        # 2: disjoint, opens lane B
        self.new("Web detail", paths="b/y.py")            # 3: inside b, joins lane B
        self.new("After core", paths="c", blocked="1")    # 4: blocked by 1, joins lane A
        self.new("Both", paths="a/x.py,b/z.py")           # 5: conflicts A and B, serial
        self.new("Unknown")                               # 6: no paths, serial and flagged
        out = self.lanes()
        self.assertEqual([(l["lane"], l["tickets"]) for l in out["lanes"]], [("A", [1, 4]), ("B", [2, 3])])
        self.assertEqual(out["lanes"][0]["paths"], ["a/x.py", "c"])
        self.assertEqual(out["serial"], [5, 6])
        self.assertEqual(out["needs_paths"], [6])

    def test_at_max_a_disjoint_ticket_joins_the_shortest_lane(self):
        self.new("One", paths="a")
        self.new("Two", paths="b")
        self.new("Three", paths="b2")                     # not inside b: prefixes are per component
        self.new("Four", paths="d")
        out = self.lanes()
        self.assertEqual([l["tickets"] for l in out["lanes"]], [[1, 3], [2, 4]])
        self.assertEqual(out["serial"], [])

    def test_max_one_is_a_single_lane(self):
        self.new("One", paths="a")
        self.new("Two", paths="b")
        self.assertEqual(self.lanes("--max", "1")["lanes"], [{"lane": "A", "tickets": [1, 2], "paths": ["a", "b"]}])

    def test_a_ticket_touching_the_serial_tail_goes_serial(self):
        self.new("One", paths="a")
        self.new("Two", paths="b")
        self.new("Both", paths="a,b")                     # 3: serial
        self.new("After both", paths="z", blocked="3")    # 4: blocked by a serial ticket
        self.new("Shares with both", paths="a/deep")      # 5: overlaps 1 and 3: serial
        self.assertEqual(self.lanes()["serial"], [3, 4, 5])

    def test_resolved_and_claimed_tickets_are_left_out(self):
        self.new("Done", paths="a")
        self.new("Taken", paths="b")
        self.new("Open", paths="c", blocked="1")
        self.sb("set", MAP, "1", "status=resolved", "--no-sync")
        self.sb("claim", MAP, "2", "--by", "someone", "--no-sync")
        out = self.lanes()
        self.assertEqual([l["tickets"] for l in out["lanes"]], [[3]])

    def test_plain_text_names_each_lane(self):
        self.new("One", paths="a")
        self.new("Unknown")
        text = self.sb("lanes", MAP).stdout
        self.assertIn("lane A", text)
        self.assertIn("serial", text)
        self.assertIn("needs paths", text)


if __name__ == "__main__":
    unittest.main()
