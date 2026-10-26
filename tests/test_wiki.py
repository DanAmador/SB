import unittest

from helpers import TODAY, VaultCase


class InitAndNew(VaultCase):
    def test_init_creates_the_layout_and_never_overwrites(self):
        self.sb("wiki", "init")
        for f in ("wiki/index.md", "wiki/log.md", "wiki/wiki.base", "wiki/README.md"):
            self.assertTrue(self.exists(f), f)
        self.assertTrue((self.vault / "wiki/raw").is_dir())
        self.assertIn("%% sb:index:start %%", self.read("wiki/index.md"))
        self.assertIn("![[wiki/wiki.base#Needs attention]]", self.read("wiki/index.md"))
        self.write("wiki/log.md", "mine\n")
        self.sb("wiki", "init")
        self.assertEqual(self.read("wiki/log.md"), "mine\n")

    def test_new_article_scaffolds_properties_heading_and_overview(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\n---\nBody.\n")
        self.sb("wiki", "new", "obsidian/frontmatter-links", "--title", "Frontmatter links",
                "--type", "concept", "--summary", "Property links lose their name.",
                "--sources", "wiki/raw/obsidian/link-cache", "--aliases", "frontmatterLinks, fm links",
                "--about", "How Obsidian stores and indexes notes.")
        text = self.read("wiki/obsidian/frontmatter-links.md")
        self.assertTrue(text.startswith("---\nwiki: article\ntype: concept\nstatus: current\n"), text)
        self.assertIn(f"updated: {TODAY}", text)
        self.assertIn('  - "[[wiki/raw/obsidian/link-cache|Link cache]]"', text)
        self.assertIn("  - frontmatterLinks\n  - fm links\n", text)
        self.assertIn("  - wiki/concept", text)
        self.assertIn("# Frontmatter links\n\n## Overview\n\nProperty links lose their name.", text)
        folder = self.read("wiki/obsidian/obsidian.md")
        self.assertIn("wiki: topic", folder)
        self.assertIn("type: topic", folder)
        self.assertIn("How Obsidian stores and indexes notes.", folder.split("---", 2)[2])

    def test_new_refuses_a_taken_slug_a_new_topic_without_about_and_a_dated_slug(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/t/s.md", "---\nwiki: raw\ntype: source\ntitle: S\nsource: x\n---\nB\n")
        base = ["--type", "concept", "--summary", "S.", "--sources", "wiki/raw/t/s"]
        self.sb("wiki", "new", "topic/thing", "--title", "Thing", *base, ok=False)  # no --about
        self.sb("wiki", "new", "topic/thing", "--title", "Thing", *base, "--about", "A topic.")
        self.sb("wiki", "new", "topic/thing", "--title", "Thing", *base, ok=False)
        self.sb("wiki", "new", "topic/2026-plan", "--title", "Plan", *base, ok=False)
        self.sb("wiki", "new", "raw/thing2", "--title", "T", *base, "--about", "x", ok=False)

    def test_new_refuses_sources_that_name_no_note_or_the_wrong_class(self):
        self.sb("wiki", "init")
        self.sb("wiki", "new", "t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "wiki/raw/t/missing", "--about", "x", ok=False)
        self.write("Notes/mine.md", "# Mine\n")
        self.sb("wiki", "new", "t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "Notes/mine", "--about", "x", ok=False)

    def test_new_synthesis_is_archived_and_cites_articles(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/t/s.md", "---\nwiki: raw\ntype: source\ntitle: S\nsource: x\n---\nB\n")
        self.sb("wiki", "new", "t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "wiki/raw/t/s", "--about", "x")
        self.sb("wiki", "new", "t/how-a-works", "--title", "How A works", "--type", "synthesis",
                "--summary", "A works.", "--sources", "t/a")
        text = self.read("wiki/t/how-a-works.md")
        self.assertIn("wiki: synthesis", text)
        self.assertIn(f"archived: {TODAY}", text)
        self.assertIn('summary: "[Archived] A works."', text)
        self.assertNotIn("status:", text)
        self.assertNotIn("updated:", text)
        self.assertIn("## Overview\n\nA works.", text)

    def test_ticket_sources_are_full_path_links_and_must_be_resolved(self):
        self.sb("wiki", "init")
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Does it read links")
        self.ticket("semantra/plugin", 8, "Still open", status="Project.Planned")
        self.sb("wiki", "new", "t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "semantra/plugin#007", "--about", "x")
        self.assertIn('"[[wayfinder/semantra/plugin/issues/007-does-it-read-links|#007]]"',
                      self.read("wiki/t/a.md"))
        self.sb("wiki", "new", "t/b", "--title", "B", "--type", "concept", "--summary", "S.",
                "--sources", "semantra/plugin#8", ok=False)


class Seeded(VaultCase):
    """A wiki with one topic, one source and one article."""

    def setUp(self):
        super().setUp()
        self.sb("wiki", "init")
        self.write("wiki/raw/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\ncreated: 2026-01-02\n---\n"
                   "The cache holds 42K links, measured on 2026-03-01.\n")
        self.sb("wiki", "new", "obsidian/frontmatter-links", "--title", "Obsidian property links",
                "--type", "concept", "--summary", "Property links lose their property name.",
                "--sources", "wiki/raw/obsidian/link-cache", "--aliases", "frontmatterLinks",
                "--about", "How Obsidian stores notes.")
        self.article = "wiki/obsidian/frontmatter-links.md"

    def append(self, rel, text):
        self.write(rel, self.read(rel) + text)


class Read(Seeded):
    def test_index_prints_one_line_per_article_and_write_stamps_a_table(self):
        out = self.sb("wiki", "index").stdout
        self.assertIn("## obsidian: How Obsidian stores notes.", out)
        self.assertIn("wiki/obsidian/frontmatter-links · concept · current · Property links lose", out)
        idx = self.read("wiki/index.md")
        self.assertIn("| [[wiki/obsidian/frontmatter-links\\|Obsidian property links]] | concept |", idx)
        self.assertIn(f"| {TODAY} |", idx)

    def test_index_without_a_wiki_says_so(self):
        import shutil
        shutil.rmtree(self.vault / "wiki")
        self.assertIn("sbmap wiki init", self.sb("wiki", "index").stdout)

    def test_link_prints_the_full_path_wikilink(self):
        for arg in ("obsidian/frontmatter-links", self.article, "[[wiki/obsidian/frontmatter-links]]"):
            self.assertEqual(self.sb("wiki", "link", arg).stdout.strip(),
                             "[[wiki/obsidian/frontmatter-links|Obsidian property links]]")

    def test_show_prints_the_outline_and_callouts_not_the_body(self):
        self.append(self.article, "\nA long paragraph only --full prints.\n\n## Links lose their name\n\n"
                    "> [!question] Disputed\n> Two sources disagree.\n\nMore.\n")
        out = self.sb("wiki", "show", "obsidian/frontmatter-links").stdout
        self.assertIn("# Obsidian property links", out)
        self.assertIn("status: current", out)
        self.assertIn("Property links lose their property name.", out)
        self.assertIn("## Links lose their name", out)
        self.assertIn("> Two sources disagree.", out)
        self.assertNotIn("More.", out)
        self.assertIn("More.", self.sb("wiki", "show", "obsidian/frontmatter-links", "--full").stdout)

    def test_show_prints_a_callout_in_the_overview_once(self):
        self.append(self.article, "\n> [!warning] Outdated (2026-10-01)\n> Was X.\n")
        self.assertEqual(self.sb("wiki", "show", self.article).stdout.count("> Was X."), 1)

    def test_find_scores_title_over_summary_over_body(self):
        self.sb("wiki", "new", "obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "Where Obsidian keeps parsed links.", "--sources", "wiki/raw/obsidian/link-cache")
        self.append("wiki/obsidian/metadata-cache.md", "\nIt mentions frontmatterLinks once.\n")
        out = self.sb("wiki", "find", "FRONTMATTERLINKS").stdout.splitlines()
        self.assertTrue(out[0].startswith("wiki/obsidian/frontmatter-links"), out)
        self.assertTrue(out[1].startswith("wiki/obsidian/metadata-cache"), out)
        self.assertNotIn("link-cache", "\n".join(out))
        self.assertIn("wiki/raw/obsidian/link-cache", self.sb("wiki", "find", "42K", "--raw").stdout)
        self.assertEqual(self.sb("wiki", "find", "nothingmatches").stdout.strip(), "no matches")

    def test_find_raw_reaches_clippings_research_and_resolved_tickets(self):
        self.write("Clippings/Some page.md", "---\nsource: https://x.org\n---\nzebra here\n")
        self.map("m/one")
        self.write("wayfinder/m/one/research/notes.md", "# Notes\n\nzebra again\n")
        self.ticket("m/one", 1, "Zebra ticket")
        self.ticket("m/one", 2, "Zebra open", status="Project.Planned")
        out = self.sb("wiki", "find", "zebra", "--raw").stdout
        self.assertIn("Clippings/Some page", out)
        self.assertIn("wayfinder/m/one/research/notes", out)
        self.assertIn("wayfinder/m/one/issues/001-zebra-ticket", out)
        self.assertNotIn("002-zebra-open", out)


class Raw(Seeded):
    def test_raw_keeps_the_text_exactly_with_clipper_properties(self):
        r = self.sb("wiki", "raw", "obsidian", "--title", "2026 Bases syntax", "--source",
                    "https://example.com/bases", "--author", "Obsidian", "--from", "-",
                    stdin="Bases filter with  two spaces.\n")
        path = r.stdout.strip()
        self.assertEqual(path, "wiki/raw/obsidian/bases-syntax-2026.md")
        text = self.read(path)
        for line in ("wiki: raw", "type: source", "title: 2026 Bases syntax", '"https://example.com/bases"',
                     "author: Obsidian", "published: Unknown", f"created: {TODAY}", "  - wiki/source"):
            self.assertIn(line, text)
        self.assertTrue(text.endswith("---\nBases filter with  two spaces.\n"), text)

    def test_raw_suffixes_a_taken_slug_and_refuses_a_known_url(self):
        src = self.write("scratch.txt", "Text.\n")
        a = self.sb("wiki", "raw", "obsidian", "--title", "Link cache", "--source", "pasted by the owner",
                    "--from", str(src)).stdout.strip()
        self.assertEqual(a, "wiki/raw/obsidian/link-cache-2.md")
        r = self.sb("wiki", "raw", "other", "--title", "Again", "--source", "https://example.com/a",
                    "--from", str(src), ok=False)
        self.assertIn("wiki/raw/obsidian/link-cache", r.stdout + r.stderr)


class Set(Seeded):
    def setUp(self):
        super().setUp()
        self.sb("wiki", "new", "obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "Where Obsidian keeps parsed links.", "--sources", "wiki/raw/obsidian/link-cache")
        self.other = "wiki/obsidian/metadata-cache.md"

    def test_set_replaces_scalars_and_stamps_today(self):
        self.sb("wiki", "set", "obsidian/frontmatter-links", "summary=New summary.", "reviewed=today")
        text = self.read(self.article)
        self.assertIn("summary: New summary.", text)
        self.assertIn(f"reviewed: {TODAY}", text)
        self.assertIn("| New summary. |", self.read("wiki/index.md"))

    def test_set_adds_and_drops_list_refs(self):
        self.sb("wiki", "set", "obsidian/frontmatter-links", "related+=obsidian/metadata-cache")
        self.assertIn('related:\n  - "[[wiki/obsidian/metadata-cache|Metadata cache]]"', self.read(self.article))
        self.sb("wiki", "set", "obsidian/frontmatter-links", "related-=obsidian/metadata-cache")
        self.assertNotIn("related:", self.read(self.article))
        self.sb("wiki", "set", "obsidian/frontmatter-links", "related+=obsidian/nope", ok=False)

    def test_disputes_are_written_on_both_ends(self):
        self.sb("wiki", "set", "obsidian/frontmatter-links", "disputes+=obsidian/metadata-cache")
        self.assertIn("[[wiki/obsidian/frontmatter-links|Obsidian property links]]", self.read(self.other))
        self.sb("wiki", "set", "obsidian/frontmatter-links", "disputes-=obsidian/metadata-cache")
        self.assertNotIn("disputes:", self.read(self.other))

    def test_superseded_by_marks_outdated_on_one_end_and_supersedes_on_the_other(self):
        self.sb("wiki", "set", "obsidian/frontmatter-links", "superseded_by+=obsidian/metadata-cache")
        self.assertIn("status: outdated", self.read(self.article))
        self.assertIn("supersedes:\n  - \"[[wiki/obsidian/frontmatter-links|", self.read(self.other))
        self.sb("wiki", "set", "obsidian/metadata-cache", "supersedes-=obsidian/frontmatter-links")
        self.assertIn("status: current", self.read(self.article))
        self.assertNotIn("superseded_by", self.read(self.article))

    def test_set_refuses_an_unknown_status(self):
        self.sb("wiki", "set", "obsidian/frontmatter-links", "status=wrong", ok=False)


class Log(Seeded):
    def test_log_appends_a_dated_entry_with_links(self):
        self.sb("wiki", "log", "learn", "--subject", "obsidian/frontmatter-links", "--disposition", "New",
                "--raw", "wiki/raw/obsidian/link-cache")
        self.sb("wiki", "log", "ask", "--subject", "Archived: obsidian/frontmatter-links")
        self.sb("wiki", "log", "learn", "--subject", "no material: Clippings/A page.md")
        log = self.read("wiki/log.md")
        self.assertIn(f"## [{TODAY}] learn | [[wiki/obsidian/frontmatter-links|Obsidian property links]]\n"
                      "- Disposition: New\n- Raw: [[wiki/raw/obsidian/link-cache|Link cache]]\n", log)
        self.assertIn(f"## [{TODAY}] ask | Archived: [[wiki/obsidian/frontmatter-links|", log)
        self.assertTrue(log.endswith(f"## [{TODAY}] learn | no material: Clippings/A page.md\n"), log)
        self.sb("wiki", "log", "forget", "--subject", "x", ok=False)


class Backlog(Seeded):
    def test_backlog_lists_uncited_unlogged_sources_oldest_first(self):
        self.write("wiki/raw/obsidian/newer.md", "---\nwiki: raw\ntitle: Newer\ncreated: 2026-05-01\n---\nx\n")
        self.write("Clippings/Older.md", "---\ncreated: 2026-02-01\n---\nx\n")
        self.write("Clippings/Dismissed.md", "---\ncreated: 2026-01-01\n---\nx\n")
        self.map("m/one")
        self.ticket("m/one", 1, "Research done")
        self.ticket("m/one", 2, "Task done", type_="task")
        self.sb("wiki", "log", "learn", "--subject", "no material: Clippings/Dismissed.md")
        out = self.sb("wiki", "backlog").stdout
        lines = [l.split(" ")[0] for l in out.splitlines() if l.startswith(("wiki/", "Clippings/", "wayfinder/"))]
        # a note without `created` sorts by its file time: today, so last
        self.assertEqual(lines, ["Clippings/Older", "wiki/raw/obsidian/newer",
                                 "wayfinder/m/one/issues/001-research-done"])
        self.assertIn("3 on the backlog", out)
        limited = self.sb("wiki", "backlog", "--limit", "1").stdout
        self.assertIn("Clippings/Older", limited)
        self.assertNotIn("newer", limited)
        self.assertIn("3 on the backlog", limited)


class Check(Seeded):
    def problems(self, *expected):
        r = self.sb("wiki", "check", ok=False)
        for e in expected:
            self.assertIn(e, r.stdout)
        return r.stdout

    def test_a_clean_wiki_passes(self):
        out = self.sb("wiki", "check").stdout
        self.assertIn("0 problem(s)", out)

    def test_fix_restamps_a_stale_index(self):
        idx = self.read("wiki/index.md").replace("| concept |", "| entity |")
        self.write("wiki/index.md", idx)
        self.problems("index.md: the index block is out of date")
        self.sb("wiki", "check", "--fix")
        self.assertIn("| concept |", self.read("wiki/index.md"))

    def test_fix_repoints_moved_links_and_drops_dead_related(self):
        self.sb("wiki", "new", "obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/obsidian/link-cache")
        self.sb("wiki", "set", "obsidian/frontmatter-links", "related+=obsidian/metadata-cache")
        self.append(self.article, "\nSee [[wiki/obsidian/metadata-cache|the cache]].\n")
        self.write("wiki/obsidian/gone.md", "---\nwiki: article\n---\n# Gone\n")
        self.sb("wiki", "set", "obsidian/frontmatter-links", "related+=obsidian/gone")
        (self.vault / "wiki/obsidian/gone.md").unlink()
        (self.vault / "wiki/cache").mkdir()
        self.write("wiki/cache/cache.md", "---\nwiki: topic\ntype: topic\nsummary: Caches.\n---\n# Cache\n\nCaches.\n")
        (self.vault / "wiki/obsidian/metadata-cache.md").rename(self.vault / "wiki/cache/metadata-cache.md")
        self.problems("moved", "obsidian/gone")
        self.sb("wiki", "check", "--fix")
        text = self.read(self.article)
        self.assertIn("[[wiki/cache/metadata-cache|Metadata cache]]", text)
        self.assertIn("[[wiki/cache/metadata-cache|the cache]]", text)
        self.assertNotIn("gone", text)

    def test_format_problems(self):
        self.write("wiki/obsidian/bad.md", "---\nwiki: article\ntype: concept\nstatus: wrong\n---\n# Bad\n")
        self.write("wiki/obsidian/deep/note.md", "---\nwiki: article\n---\n# Deep\n")
        self.write("wiki/orphan/2026-plan.md", "---\nwiki: article\n---\n# Plan\n")
        self.write("wiki/raw/x/frontmatter-links.md", "---\nwiki: raw\ntitle: T\nsource: s\n---\nB\n")
        self.problems("bad.md: unknown status 'wrong'", "bad.md: missing summary", "bad.md: missing sources",
                      "deep/note.md: deeper than wiki/<topic>/", "orphan: no folder note",
                      "2026-plan.md: slug starts with digits and a dash",
                      "slug 'frontmatter-links' is taken twice")

    def test_status_must_match_the_callouts_and_supersession(self):
        self.append(self.article, "\n> [!question] Disputed\n> A and B.\n\n> [!warning] Outdated\n> Was X.\n")
        self.problems("status is current; the rule makes it disputed", "Outdated callout without its date")

    def test_reciprocal_ends_must_both_exist(self):
        self.sb("wiki", "new", "obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/obsidian/link-cache")
        text = self.read(self.article).replace("tags:", 'disputes:\n  - "[[wiki/obsidian/metadata-cache|M]]"\ntags:')
        self.write(self.article, text)
        self.problems("metadata-cache.md: missing disputes back to wiki/obsidian/frontmatter-links")

    def test_link_problems(self):
        self.map("m/one")
        self.ticket("m/one", 3, "Open one", status="Project.Planned")
        self.write("Notes/mine.md", "# Mine\n")
        text = self.read(self.article).replace(
            "sources:\n", 'sources:\n  - "[[Notes/mine|Mine]]"\n  - "[[wayfinder/m/one/issues/003-open-one|#003]]"\n')
        self.write(self.article, text + "\nSee [mine](../../Notes/mine.md), [[mine]], #123 and [[wiki/nowhere|x]].\n")
        self.problems("Notes/mine is not a raw note", "003-open-one is a ticket that is not resolved",
                      "markdown link to a vault note", "wikilink by bare file name: [[mine]]",
                      "bare #123", "broken link: [[wiki/nowhere|x]]")

    def test_links_inside_code_are_text(self):
        self.append(self.article, "\nSee [[wiki/obsidian/obsidian|the topic]]. Write `[[mine]]` or `#123`, never bare.\n\n```\n[[other]] #456\n```\n")
        self.sb("wiki", "check")

    def test_grounding_suspects_are_printed_and_never_counted(self):
        self.append(self.article, "\nThe cache holds 42K links; 99.9% stay. \u201cA quote that no source holds at all\u201d.\n")
        out = self.sb("wiki", "check").stdout
        suspects = out[out.index("grounding suspect"):]
        self.assertIn("99.9%", suspects)
        self.assertIn("A quote that no source holds at all", suspects)
        self.assertNotIn("42K", suspects)
        self.assertIn("on the backlog", out)


if __name__ == "__main__":
    unittest.main()
