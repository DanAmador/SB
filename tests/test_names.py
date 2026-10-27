import unittest

from helpers import VaultCase

MAP = "monorepo/names"
ISSUES = "wayfinder/monorepo/names/issues"


class TicketNames(VaultCase):
    """Operon names a file task by its file name, and a Route node links by its label, so a
    ticket's file is named `NNN Title` and its title is a property, not an H1."""

    def setUp(self):
        super().setUp()
        self.sb("init", MAP, "--title", "Names", "--destination", "Somewhere.", "--repo", "/code/monorepo")

    def new(self, title, *extra):
        return self.sb("new", MAP, "--title", title, "--no-sync", *extra).stdout.strip()

    def test_the_file_is_named_number_then_title_and_the_title_is_a_property(self):
        path = self.new("Build sbmap lanes")
        self.assertTrue(path.endswith("issues/001 Build sbmap lanes.md"), path)
        text = (self.vault / path).read_text()
        self.assertIn("title: Build sbmap lanes\n", text)
        body = text.split("\n---\n", 1)[1]
        self.assertTrue(body.startswith("## Question"), body[:40])

    def test_characters_obsidian_forbids_in_names_are_dropped_from_the_file_only(self):
        path = self.new('Fix: a/b? [x] #1 | "q"')
        self.assertTrue(path.endswith('issues/001 Fix a b x 1 q.md'), path)
        self.assertIn('title: "Fix: a/b? [x] #1 | \\"q\\""', (self.vault / path).read_text())

    def test_show_and_status_read_the_title_property(self):
        self.new("Build sbmap lanes")
        self.assertIn("#1: Build sbmap lanes", self.sb("show", MAP, "1").stdout)
        self.assertIn("001 [task] Build sbmap lanes", self.sb("status", MAP).stdout)

    def test_a_legacy_ticket_still_takes_its_title_from_the_h1(self):
        self.ticket("monorepo/names", 7, "Old one", status="Project.Planned", type_="task")
        self.assertIn("#7: Old one", self.sb("show", MAP, "7").stdout)

    def test_route_nodes_are_labelled_with_the_file_name_and_link_to_it(self):
        self.new("First")
        self.new("Second", "--blocked-by", "1")
        out = self.sb("diagram", MAP).stdout
        self.assertIn('t001["001 First"]', out)
        self.assertIn("class t001,t002 internal-link", out)

    def test_resolve_links_the_decision_and_check_stays_clean(self):
        self.new("First, then more")
        self.sb("resolve", MAP, "1", "--gist", "done", "--answer", "Yes.", "--no-sync")
        self.assertIn("- [First, then more](issues/001%20First,%20then%20more.md): done",
                      self.read("wayfinder/monorepo/names/map.md"))
        self.assertNotIn("missing from the map's Decisions", self.sb("check", MAP, ok=None).stdout)


if __name__ == "__main__":
    unittest.main()
