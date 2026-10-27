import unittest

from helpers import VaultCase


class NewTicketsAndMaps(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", "monorepo/overrides", "--title", "Overrides", "--destination", "Somewhere.",
                "--repo", "/code/monorepo")

    def test_a_map_carries_its_project_as_a_property_and_a_tag(self):
        text = self.read("wayfinder/monorepo/overrides/map.md")
        self.assertIn("project: monorepo", text)
        self.assertIn("  - project/monorepo", text)

    def test_a_ticket_carries_its_project_and_an_operon_priority(self):
        path = self.sb("new", "monorepo/overrides", "--title", "First", "--no-sync").stdout.strip()
        text = (self.vault / path).read_text()
        self.assertIn("project: monorepo", text)
        self.assertIn("  - project/monorepo", text)
        self.assertIn("priority: C", text)

    def test_priority_words_map_to_operon_letters(self):
        for word, letter in (("high", "A"), ("low", "E"), ("urgent", "S"), ("B", "B")):
            path = self.sb("new", "monorepo/overrides", "--title", f"P {word}", "--priority", word,
                           "--no-sync").stdout.strip()
            self.assertIn(f"priority: {letter}", (self.vault / path).read_text(), word)
        self.sb("new", "monorepo/overrides", "--title", "Bad", "--priority", "whenever", ok=False)

    def test_aliases_are_text_so_obsidian_reads_them_as_aliases(self):
        path = self.sb("new", "monorepo/overrides", "--title", "First", "--no-sync").stdout.strip()
        self.assertIn('aliases:\n  - "#001"\n  - "001"\n', (self.vault / path).read_text())
        self.assertIn("number: 1\n", (self.vault / path).read_text())

    def test_set_maps_priority_too(self):
        self.sb("new", "monorepo/overrides", "--title", "First", "--no-sync")
        self.sb("set", "monorepo/overrides", "1", "priority=high", "--no-sync")
        self.assertIn("priority: A", self.read("wayfinder/monorepo/overrides/issues/001 First.md"))


class Boards(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", "monorepo/overrides", "--title", "Overrides", "--destination", "Somewhere.",
                "--repo", "/code/monorepo")

    def test_frontier_formulas_read_the_operon_statuses(self):
        for f in ("wayfinder/monorepo/overrides/board.base", "wayfinder/frontier.base"):
            text = self.read(f)
            self.assertIn('"Project.Finished"', text, f)
            self.assertIn('"Project.Dropped"', text, f)
            self.assertIn('status == "Project.Planned"', text, f)
            self.assertNotIn('status == "open"', text, f)
        self.assertIn('status == "Project.InProgress"', self.read("wayfinder/frontier.base"))

    def test_each_repo_gets_its_own_board(self):
        text = self.read("wayfinder/monorepo/board.base")
        self.assertIn('file.inFolder("wayfinder/monorepo")', text)
        self.assertIn("name: Frontier", text)
        self.assertIn("property: map", text)
        self.assertIn("[[wayfinder/monorepo/board.base]]", self.read("wayfinder/monorepo/overrides/map.md"))

    def test_the_all_maps_frontier_groups_by_project(self):
        self.assertIn("property: project", self.read("wayfinder/frontier.base"))


class MigrateBackfills(VaultCase):
    """Tickets written before projects and Operon priorities."""

    def setUp(self):
        super().setUp()
        self.map("monorepo/overrides")
        self.ticket("monorepo/overrides", 1, "Old one")
        p = "wayfinder/monorepo/overrides/issues/001-old-one.md"
        self.write(p, self.read(p).replace("type: research\n", "type: research\npriority: normal\n"))
        self.old = p

    def test_dry_run_reports_and_writes_nothing(self):
        out = self.sb("migrate", "monorepo/overrides").stdout
        self.assertIn("001: project monorepo", out)
        self.assertIn("priority normal -> C", out)
        self.assertIn("map.md: project monorepo", out)
        self.assertIn("dry run", out)
        self.assertNotIn("project", self.read(self.old))

    def test_write_backfills_and_rewrites_the_boards(self):
        self.write("wayfinder/monorepo/overrides/board.base", 'ready: status == "open"\n')
        self.sb("migrate", "monorepo/overrides", "--write")
        text = self.read(self.old)
        self.assertIn("project: monorepo", text)
        self.assertIn("  - project/monorepo", text)
        self.assertIn("priority: C", text)
        self.assertIn("project: monorepo", self.read("wayfinder/monorepo/overrides/map.md"))
        self.assertIn('status == "Project.Planned"', self.read("wayfinder/monorepo/overrides/board.base"))
        self.assertTrue(self.exists("wayfinder/monorepo/board.base"))
        again = self.sb("migrate", "monorepo/overrides").stdout
        self.assertNotIn("001:", again)
        self.assertNotIn("map.md: project", again)


if __name__ == "__main__":
    unittest.main()
