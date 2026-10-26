import unittest

from helpers import TODAY, VaultCase


class Close(VaultCase):
    def setUp(self):
        super().setUp()
        self.map("semantra/plugin", title="Semantra Obsidian plugin")
        self.ticket("semantra/plugin", 7, "Does it read links")
        self.ticket("semantra/plugin", 8, "Ship it", type_="task")

    def article_citing(self, slug, title, ref):
        self.sb("wiki", "new", f"obsidian/{slug}", "--title", title, "--type", "concept",
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
        self.write("wiki/raw/obsidian/other.md", "---\nwiki: raw\ntype: source\ntitle: O\nsource: s\n---\nB\n")
        self.article_citing("unrelated", "Unrelated", "wiki/raw/obsidian/other")
        r = self.sb("close", "semantra/plugin")
        self.assertIn("wayfinder/semantra/plugin/report.md", r.stdout)
        report = self.read("wayfinder/semantra/plugin/report.md")
        self.assertTrue(report.startswith("---\nwayfinder: report\ntype: report\n"), report)
        self.assertIn('map: "[[wayfinder/semantra/plugin/map|Semantra Obsidian plugin]]"', report)
        self.assertIn(f"closed: {TODAY}", report)
        self.assertIn('findings:\n  - "[[wiki/obsidian/frontmatter-links|Obsidian property links]]"\ntags:', report)
        self.assertNotIn("Unrelated", report)
        self.assertIn("# Semantra Obsidian plugin: ", report)
        self.assertIn("## Findings", report)
        self.assertIn("- [ ] <One sentence.> [[wiki/obsidian/frontmatter-links|Obsidian property links]]", report)
        self.assertIn("status: Project.Finished", self.read("wayfinder/semantra/plugin/map.md"))

    def test_a_map_that_learned_nothing_has_no_findings_sections(self):
        self.sb("close", "semantra/plugin")
        report = self.read("wayfinder/semantra/plugin/report.md")
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
