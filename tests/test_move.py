"""A ticket moves to another map of its project with its number, history and every link to it intact,
so maps can be redrawn by topic without retyping tickets."""
import unittest

from helpers import VaultCase

SRC, DST = "proj/night", "proj/page"


class Move(VaultCase):
    def setUp(self):
        super().setUp()
        for m, title in ((SRC, "Night"), (DST, "Page"), ("other/maps", "Other")):
            self.sb("init", m, "--why", "Because.", "--title", title, "--destination", "Somewhere.",
                    "--repo", f"/code/{m.split('/')[0]}")
        self.a = self.new(SRC, "Stop keeps the work")
        self.b = self.new(SRC, "A recheck waits", "--blocked-by", str(self.num(self.a)))
        self.note = self.write("notes/elsewhere.md", f"See [[{self.key(self.a)}|the stop ticket]].\n")

    def new(self, map_, title, *extra):
        out = self.sb("new", map_, "--why", "Because.", "--title", title, "--no-sync", *extra).stdout.strip()
        return self.vault / out

    def num(self, path):
        return int(path.name.split(" ")[0].split("-")[0])

    def key(self, path):
        return str(path.relative_to(self.vault))[:-3]

    def test_the_ticket_lands_in_the_other_map_with_its_number_and_links(self):
        self.sb("move", SRC, str(self.num(self.a)), "--to", DST)
        moved = self.vault / "wayfinder" / DST / "issues" / self.a.name
        self.assertTrue(moved.exists())
        self.assertFalse(self.a.exists())
        text = moved.read_text(encoding="utf-8")
        self.assertIn(f"[[wayfinder/{DST}/map|Page]]", text)
        self.assertIn("wayfinder/map/proj-page", text)
        self.assertNotIn("wayfinder/map/proj-night", text)
        self.assertIn(f"Moved from [[wayfinder/{SRC}/map|Night]]", text)
        self.assertIn(self.key(moved), self.note.read_text(encoding="utf-8"))  # links elsewhere follow it
        self.assertIn(self.key(moved), self.b.read_text(encoding="utf-8"))  # and so does a blocker edge
        self.sb("check", SRC)
        self.sb("check", DST)

    def test_a_resolved_ticket_moves_into_done(self):
        self.sb("set", SRC, str(self.num(self.a)), "status=resolved", "--no-sync")
        self.sb("move", SRC, str(self.num(self.a)), "--to", DST)
        self.assertTrue((self.vault / "wayfinder" / DST / "issues" / "done" / self.a.name).exists())

    def test_it_refuses_a_claimed_ticket_and_another_project(self):
        self.sb("claim", SRC, str(self.num(self.a)), "--by", "a worker", "--no-sync")
        r = self.sb("move", SRC, str(self.num(self.a)), "--to", DST, ok=False)
        self.assertIn("claimed", r.stderr)
        r = self.sb("move", SRC, str(self.num(self.b)), "--to", "other/maps", ok=False)
        self.assertIn("project", r.stderr)
        self.assertTrue(self.a.exists() and self.b.exists())


if __name__ == "__main__":
    unittest.main()
