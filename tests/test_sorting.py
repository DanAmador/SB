import unittest

from helpers import VaultCase

A, B = "acme/fix", "acme/other"
ISSUES = "wayfinder/acme/fix/issues"


class Sorting(VaultCase):
    """Finished work leaves the folder: cleared tickets go to issues/done/, closed maps to archive/,
    and every link naming a moved file follows it."""

    def setUp(self):
        super().setUp()
        for m in (A, B):
            self.sb("init", m, "--why", "Because.", "--title", m, "--destination", "Somewhere.", "--repo", "/code/acme")
        self.sb("new", A, "--title", "First", "--why", "Because.", "--paths", "a.py", "--no-sync")
        self.sb("new", A, "--title", "Second", "--why", "Because.", "--paths", "b.py", "--blocked-by", "1", "--no-sync")
        # another map's ticket links to #001 in its blockers and its prose, and a wiki note in a table
        self.sb("new", B, "--title", "Third", "--why", "Because.", "--blocked-by",
                "[[wayfinder/acme/fix/issues/001 First|001]]", "--no-sync")
        self.inbound = "wayfinder/acme/other/issues/003 Third.md"
        self.write(self.inbound, self.read(self.inbound) + "\nSee [[wayfinder/acme/fix/issues/001 First|#001]].\n")
        self.write("wiki/acme/note.md", "| t |\n|---|\n| [[wayfinder/acme/fix/issues/001 First\\|#001]] |\n"
                   "Map: [[wayfinder/acme/fix/map|Fix]]\n")

    def resolve(self, num="1"):
        self.sb("resolve", A, num, "--gist", "done", "--answer", "Yes.")

    def test_resolve_moves_the_ticket_to_done_and_rewrites_links_to_it(self):
        self.resolve()
        self.assertFalse(self.exists(f"{ISSUES}/001 First.md"))
        self.assertTrue(self.exists(f"{ISSUES}/done/001 First.md"))
        inbound = self.read(self.inbound)
        self.assertNotIn("[[wayfinder/acme/fix/issues/001 First|", inbound)
        self.assertIn('  - "[[wayfinder/acme/fix/issues/done/001 First|001]]"', inbound)
        self.assertIn("See [[wayfinder/acme/fix/issues/done/001 First|#001]].", inbound)
        self.assertIn("[[wayfinder/acme/fix/issues/done/001 First\\|#001]]", self.read("wiki/acme/note.md"))
        self.assertIn("- [First](issues/done/001%20First.md): done", self.read("wayfinder/acme/fix/map.md"))
        self.assertIn("[[wayfinder/acme/fix/issues/done/001 First|001]]", self.read(f"{ISSUES}/002 Second.md"))
        self.assertIn("0 problem(s)", self.sb("check", B).stdout)

    def test_reopening_moves_it_back(self):
        self.resolve()
        self.sb("set", A, "1", "status=open")
        self.assertTrue(self.exists(f"{ISSUES}/001 First.md"))
        self.assertFalse(self.exists(f"{ISSUES}/done"))  # the last one out leaves no empty folder
        self.assertIn("See [[wayfinder/acme/fix/issues/001 First|#001]].", self.read(self.inbound))
        self.assertIn("- [First](issues/001%20First.md): done", self.read("wayfinder/acme/fix/map.md"))
        self.sb("set", A, "1", "status=out-of-scope")
        self.assertTrue(self.exists(f"{ISSUES}/done/001 First.md"))
        self.sb("claim", A, "1", "--by", "me")
        self.assertTrue(self.exists(f"{ISSUES}/001 First.md"))

    def test_close_archives_the_map_and_rewrites_links_to_it(self):
        self.resolve()
        self.resolve("2")
        r = self.sb("close", A)
        self.assertIn("wayfinder/acme/archive/fix/report.md", r.stdout)
        self.assertFalse(self.exists("wayfinder/acme/fix"))
        self.assertTrue(self.exists("wayfinder/acme/archive/fix/issues/done/002 Second.md"))
        self.assertIn("See [[wayfinder/acme/archive/fix/issues/done/001 First|#001]].", self.read(self.inbound))
        self.assertIn("Map: [[wayfinder/acme/archive/fix/map|Fix]]", self.read("wiki/acme/note.md"))
        archived = self.read("wayfinder/acme/archive/fix/map.md")
        self.assertIn("![[wayfinder/acme/archive/fix/board.base#Frontier]]", archived)
        self.assertIn('file.inFolder("wayfinder/acme/archive/fix/issues")',
                      self.read("wayfinder/acme/archive/fix/board.base"))
        self.assertIn("map: \"[[wayfinder/acme/archive/fix/map|", self.read("wayfinder/acme/archive/fix/issues/done/001 First.md"))
        # it still answers to its name, keeps its slug, and maps says it is archived
        self.assertIn("2 resolved", self.sb("status", A).stdout)
        self.assertIn("wayfinder/map/acme-fix", archived)
        listing = self.sb("maps").stdout
        self.assertIn("acme/archive/fix", listing)
        self.assertIn("· archived", listing)
        self.assertIn("0 problem(s)", self.sb("check", B).stdout)
        self.assertEqual("004", self.sb("next", B).stdout.strip())

    def legacy(self):
        """What exists today: a resolved ticket left in issues/, an open one in done/, a map marked closed."""
        self.ticket("acme/fix", 1, "Old done")  # 001-old-done.md, resolved
        self.write(f"{ISSUES}/done/005 Open again.md", "---\nwayfinder: ticket\nnumber: 5\nstatus: Project.Planned\n---\n")
        self.map("acme/shut", status="Project.Finished")
        self.ticket("acme/shut", 6, "Shut")
        self.write("wiki/acme/old.md", "[[wayfinder/acme/fix/issues/001-old-done|#001]] [[wayfinder/acme/shut/map|S]]\n")

    def snapshot(self):
        return {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob("*") if p.is_file()}

    def test_migrate_sort_is_a_dry_run_until_write(self):
        for f in self.vault.glob(f"{ISSUES}/00[12] *.md"):
            f.unlink()
        self.legacy()
        before = self.snapshot()
        out = self.sb("migrate", "--sort", "--all").stdout
        self.assertEqual(before, self.snapshot())
        self.assertIn("dry run: nothing written", out)
        self.assertIn("3 ticket(s) and 1 map(s) would move", out)
        out = self.sb("migrate", "--sort", "--all", "--write").stdout
        self.assertIn("3 ticket(s) and 1 map(s) moved", out)
        self.assertTrue(self.exists(f"{ISSUES}/done/001-old-done.md"))
        self.assertTrue(self.exists(f"{ISSUES}/005 Open again.md"))
        self.assertTrue(self.exists("wayfinder/acme/archive/shut/issues/done/006-shut.md"))
        self.assertEqual("[[wayfinder/acme/fix/issues/done/001-old-done|#001]] [[wayfinder/acme/archive/shut/map|S]]\n",
                         self.read("wiki/acme/old.md"))
        self.assertIn("0 ticket(s) and 0 map(s) would move; 0 link rewrite(s) in 0 file(s)",
                      self.sb("migrate", "--sort", "--all").stdout)

    def test_read_commands_work_on_a_map_with_done_tickets(self):
        self.resolve()
        self.assertIn("1 open, 1 resolved", self.sb("status", A).stdout)
        self.assertIn("002\ttask\tSecond", self.sb("frontier", A).stdout)
        self.assertIn("status: resolved", self.sb("show", A, "1").stdout)
        self.assertIn("0 problem(s)", self.sb("check", A).stdout)
        self.assertIn("002 Second", self.sb("lanes", A).stdout)
        self.assertIn("t001 --> t002", self.sb("diagram", A).stdout)  # same map, not an external node
        self.assertIn("#001", self.sb("link", A, "1").stdout)


if __name__ == "__main__":
    unittest.main()
