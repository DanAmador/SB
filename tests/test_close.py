import unittest

from helpers import TODAY, VaultCase


class Close(VaultCase):
    def setUp(self):
        super().setUp()
        self.map("semantra/plugin", title="Semantra Obsidian plugin")
        self.ticket("semantra/plugin", 7, "Does it read links")
        self.ticket("semantra/plugin", 8, "Ship it", type_="task")

    def article_citing(self, slug, title, ref):
        self.sb("wiki", "new", f"semantra/obsidian/{slug}", "--title", title, "--type", "concept",
                "--summary", "S.", "--sources", ref, "--about", "Obsidian.")

    def test_refuses_while_tickets_are_open_or_claimed(self):
        self.ticket("semantra/plugin", 9, "Still open", status="Project.Planned")
        self.ticket("semantra/plugin", 10, "Held", status="Project.InProgress")
        r = self.sb("close", "semantra/plugin", ok=False)
        self.assertIn("009 Still open", r.stdout + r.stderr)
        self.assertIn("010 Held", r.stdout + r.stderr)
        self.assertFalse(self.exists("wayfinder/semantra/plugin/report.md"))
        self.assertIn("status: Project.InProgress", self.read("wayfinder/semantra/plugin/map.md"))

    def test_writes_the_report_with_its_findings_and_resolves_the_map(self):
        self.ticket("semantra/plugin", 9, "Dropped", status="Project.Dropped")
        self.sb("wiki", "init")
        self.article_citing("frontmatter-links", "Obsidian property links", "semantra/plugin#007")
        self.write("wiki/raw/general/obsidian/other.md", "---\nwiki: raw\ntype: source\ntitle: O\nsource: s\n---\nB\n")
        self.article_citing("unrelated", "Unrelated", "wiki/raw/general/obsidian/other")
        r = self.sb("close", "semantra/plugin")
        self.assertIn("wayfinder/semantra/archive/plugin/report.md", r.stdout)
        report = self.read("wayfinder/semantra/archive/plugin/report.md")
        self.assertTrue(report.startswith("---\nwayfinder: report\ntype: report\n"), report)
        self.assertIn('map: "[[wayfinder/semantra/archive/plugin/map|Semantra Obsidian plugin]]"', report)
        self.assertIn(f"closed: {TODAY}", report)
        self.assertIn('findings:\n  - "[[wiki/semantra/obsidian/frontmatter-links|Obsidian property links]]"\ntags:', report)
        self.assertNotIn("Unrelated", report)
        self.assertIn("# Semantra Obsidian plugin: ", report)
        self.assertIn("## Findings", report)
        self.assertIn("- [ ] <One sentence.> [[wiki/semantra/obsidian/frontmatter-links|Obsidian property links]]", report)
        self.assertIn("status: Project.Finished", self.read("wayfinder/semantra/archive/plugin/map.md"))

    def test_a_map_that_learned_nothing_has_no_findings_sections(self):
        self.sb("close", "semantra/plugin")
        report = self.read("wayfinder/semantra/archive/plugin/report.md")
        self.assertNotIn("findings:", report)
        self.assertNotIn("## Findings", report)
        self.assertNotIn("## Also learned", report)
        self.assertIn("## Outcome", report)
        self.assertIn("## Decisions later work must respect", report)

    def test_never_overwrites_a_report(self):
        self.write("wayfinder/semantra/plugin/report.md", "mine\n")
        self.sb("close", "semantra/plugin", ok=False)
        self.assertEqual(self.read("wayfinder/semantra/plugin/report.md"), "mine\n")


if __name__ == "__main__":
    unittest.main()


class CloseFinished(VaultCase):
    """`sbmap close --finished`: every map whose tickets have all ended closes on its own."""

    def setUp(self):
        super().setUp()
        self.map("semantra/done", title="All done")
        self.ticket("semantra/done", 1, "Built")
        self.ticket("semantra/done", 2, "Dropped", status="Project.Dropped")
        self.map("semantra/busy", title="Still going")
        self.ticket("semantra/busy", 3, "Built")
        self.ticket("semantra/busy", 4, "Open", status="Project.Planned")
        self.map("semantra/empty", title="Nothing yet")
        self.sb("summary", "semantra/done", "--text", "Why: because it mattered.")

    def test_closes_only_maps_whose_tickets_all_ended(self):
        r = self.sb("close", "--finished")
        self.assertIn("All done", r.stdout)
        self.assertTrue(self.exists("wayfinder/semantra/archive/done/report.md"))
        self.assertFalse(self.exists("wayfinder/semantra/archive/busy/report.md"))
        self.assertFalse(self.exists("wayfinder/semantra/archive/empty/report.md"))
        self.assertIn("status: Project.InProgress", self.read("wayfinder/semantra/busy/map.md"))

    def test_the_report_and_plain_words_say_it_closed_on_its_own(self):
        self.sb("close", "--finished")
        report = self.read("wayfinder/semantra/archive/done/report.md")
        self.assertIn("# All done: every ticket ended", report)
        self.assertIn("Closed on its own on " + TODAY + ": 1 ticket resolved, 1 out of scope.", report)
        self.assertNotIn("<One paragraph", report)
        self.assertNotIn("## Your calls", report)
        self.assertNotIn("## Decisions later work must respect", report)
        words = self.read("wayfinder/semantra/archive/done/map.md")
        self.assertIn("## In plain words\n\nClosed on its own on " + TODAY, words)
        self.assertIn("Why: because it mattered.", words)

    def test_a_dry_run_names_them_and_changes_nothing(self):
        r = self.sb("close", "--finished", "--dry-run")
        self.assertIn("All done", r.stdout)
        self.assertNotIn("Still going", r.stdout)
        self.assertFalse(self.exists("wayfinder/semantra/archive/done/report.md"))
        self.assertIn("status: Project.InProgress", self.read("wayfinder/semantra/done/map.md"))

