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
        self.write("wiki/raw/general/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\n---\nBody.\n")
        self.sb("wiki", "new", "general/obsidian/frontmatter-links", "--title", "Frontmatter links",
                "--type", "concept", "--summary", "Property links lose their name.",
                "--sources", "wiki/raw/general/obsidian/link-cache", "--aliases", "frontmatterLinks, fm links",
                "--about", "How Obsidian stores and indexes notes.")
        text = self.read("wiki/general/obsidian/frontmatter-links.md")
        self.assertTrue(text.startswith("---\nwiki: article\ntype: concept\nproject: general\nstatus: current\n"), text)
        self.assertIn(f"updated: {TODAY}", text)
        self.assertIn('  - "[[wiki/raw/general/obsidian/link-cache|Link cache]]"', text)
        self.assertIn("  - frontmatterLinks\n  - fm links\n", text)
        self.assertIn("  - wiki/concept", text)
        self.assertIn("# Frontmatter links\n\n## Overview\n\nProperty links lose their name.", text)
        folder = self.read("wiki/general/obsidian/obsidian.md")
        self.assertIn("wiki: topic", folder)
        self.assertIn("type: topic", folder)
        self.assertIn("How Obsidian stores and indexes notes.", folder.split("---", 2)[2])

    def test_new_refuses_a_taken_slug_a_new_topic_without_about_and_a_dated_slug(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/p/t/s.md", "---\nwiki: raw\ntype: source\ntitle: S\nsource: x\n---\nB\n")
        base = ["--type", "concept", "--summary", "S.", "--sources", "wiki/raw/p/t/s"]
        self.sb("wiki", "new", "p/topic/thing", "--title", "Thing", *base, ok=False)  # no --about
        self.sb("wiki", "new", "p/topic/thing", "--title", "Thing", *base, "--about", "A topic.")
        self.sb("wiki", "new", "p/topic/thing", "--title", "Thing", *base, ok=False)
        self.sb("wiki", "new", "p/topic/2026-plan", "--title", "Plan", *base, ok=False)
        self.sb("wiki", "new", "p/raw/thing2", "--title", "T", *base, "--about", "x", ok=False)

    def test_new_refuses_sources_that_name_no_note_or_the_wrong_class(self):
        self.sb("wiki", "init")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "wiki/raw/p/t/missing", "--about", "x", ok=False)
        self.write("Notes/mine.md", "# Mine\n")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "Notes/mine", "--about", "x", ok=False)

    def test_new_synthesis_is_archived_and_cites_articles(self):
        self.sb("wiki", "init")
        self.write("wiki/raw/p/t/s.md", "---\nwiki: raw\ntype: source\ntitle: S\nsource: x\n---\nB\n")
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "wiki/raw/p/t/s", "--about", "x")
        self.sb("wiki", "new", "p/t/how-a-works", "--title", "How A works", "--type", "synthesis",
                "--summary", "A works.", "--sources", "p/t/a")
        text = self.read("wiki/p/t/how-a-works.md")
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
        self.sb("wiki", "new", "p/t/a", "--title", "A", "--type", "concept", "--summary", "S.",
                "--sources", "semantra/plugin#007", "--about", "x")
        self.assertIn('"[[wayfinder/semantra/plugin/issues/007-does-it-read-links|#007]]"',
                      self.read("wiki/p/t/a.md"))
        self.sb("wiki", "new", "p/t/b", "--title", "B", "--type", "concept", "--summary", "S.",
                "--sources", "semantra/plugin#8", ok=False)


class Seeded(VaultCase):
    """A wiki with one topic, one source and one article."""

    def setUp(self):
        super().setUp()
        self.sb("wiki", "init")
        self.write("wiki/raw/general/obsidian/link-cache.md", "---\nwiki: raw\ntype: source\ntitle: Link cache\n"
                   "source: https://example.com/a\ncreated: 2026-01-02\n---\n"
                   "The cache holds 42K links, measured on 2026-03-01.\n")
        self.sb("wiki", "new", "general/obsidian/frontmatter-links", "--title", "Obsidian property links",
                "--type", "concept", "--summary", "Property links lose their property name.",
                "--sources", "wiki/raw/general/obsidian/link-cache", "--aliases", "frontmatterLinks",
                "--about", "How Obsidian stores notes.")
        self.article = "wiki/general/obsidian/frontmatter-links.md"

    def append(self, rel, text):
        self.write(rel, self.read(rel) + text)


class Read(Seeded):
    def test_index_prints_one_line_per_article_and_write_stamps_a_table(self):
        out = self.sb("wiki", "index").stdout
        self.assertIn("# general\n## obsidian: How Obsidian stores notes.", out)
        self.assertIn("wiki/general/obsidian/frontmatter-links · concept · current · Property links lose", out)
        idx = self.read("wiki/index.md")
        self.assertIn("| [[wiki/general/obsidian/frontmatter-links\\|Obsidian property links]] | concept |", idx)
        self.assertIn(f"| {TODAY} |", idx)

    def test_index_without_a_wiki_says_so(self):
        import shutil
        shutil.rmtree(self.vault / "wiki")
        self.assertIn("sbmap wiki init", self.sb("wiki", "index").stdout)

    def test_link_prints_the_full_path_wikilink(self):
        for arg in ("general/obsidian/frontmatter-links", self.article, "[[wiki/general/obsidian/frontmatter-links]]"):
            self.assertEqual(self.sb("wiki", "link", arg).stdout.strip(),
                             "[[wiki/general/obsidian/frontmatter-links|Obsidian property links]]")

    def test_show_prints_the_outline_and_callouts_not_the_body(self):
        self.append(self.article, "\nA long paragraph only --full prints.\n\n## Links lose their name\n\n"
                    "> [!question] Disputed\n> Two sources disagree.\n\nMore.\n")
        out = self.sb("wiki", "show", "general/obsidian/frontmatter-links").stdout
        self.assertIn("# Obsidian property links", out)
        self.assertIn("status: current", out)
        self.assertIn("Property links lose their property name.", out)
        self.assertIn("## Links lose their name", out)
        self.assertIn("> Two sources disagree.", out)
        self.assertNotIn("More.", out)
        self.assertIn("More.", self.sb("wiki", "show", "general/obsidian/frontmatter-links", "--full").stdout)

    def test_show_prints_a_callout_in_the_overview_once(self):
        self.append(self.article, "\n> [!warning] Outdated (2026-10-01)\n> Was X.\n")
        self.assertEqual(self.sb("wiki", "show", self.article).stdout.count("> Was X."), 1)

    def test_find_scores_title_over_summary_over_body(self):
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "Where Obsidian keeps parsed links.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.append("wiki/general/obsidian/metadata-cache.md", "\nIt mentions frontmatterLinks once.\n")
        out = self.sb("wiki", "find", "FRONTMATTERLINKS").stdout.splitlines()
        self.assertTrue(out[0].startswith("wiki/general/obsidian/frontmatter-links"), out)
        self.assertTrue(out[1].startswith("wiki/general/obsidian/metadata-cache"), out)
        self.assertNotIn("link-cache", "\n".join(out))
        self.assertIn("wiki/raw/general/obsidian/link-cache", self.sb("wiki", "find", "42K", "--raw").stdout)
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
        r = self.sb("wiki", "raw", "general/obsidian", "--title", "2026 Bases syntax", "--source",
                    "https://example.com/bases", "--author", "Obsidian", "--from", "-",
                    stdin="Bases filter with  two spaces.\n")
        path = r.stdout.strip()
        self.assertEqual(path, "wiki/raw/general/obsidian/bases-syntax-2026.md")
        text = self.read(path)
        for line in ("wiki: raw", "type: source", "title: 2026 Bases syntax", '"https://example.com/bases"',
                     "author: Obsidian", "published: Unknown", f"created: {TODAY}", "  - wiki/source"):
            self.assertIn(line, text)
        self.assertTrue(text.endswith("---\nBases filter with  two spaces.\n"), text)

    def test_raw_suffixes_a_taken_slug_and_refuses_a_known_url(self):
        src = self.write("scratch.txt", "Text.\n")
        a = self.sb("wiki", "raw", "general/obsidian", "--title", "Link cache", "--source", "pasted by the owner",
                    "--from", str(src)).stdout.strip()
        self.assertEqual(a, "wiki/raw/general/obsidian/link-cache-2.md")
        r = self.sb("wiki", "raw", "general/other", "--title", "Again", "--source", "https://example.com/a",
                    "--from", str(src), ok=False)
        self.assertIn("wiki/raw/general/obsidian/link-cache", r.stdout + r.stderr)


class Set(Seeded):
    def setUp(self):
        super().setUp()
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "Where Obsidian keeps parsed links.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.other = "wiki/general/obsidian/metadata-cache.md"

    def test_set_replaces_scalars_and_stamps_today(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "summary=New summary.", "reviewed=today")
        text = self.read(self.article)
        self.assertIn("summary: New summary.", text)
        self.assertIn(f"reviewed: {TODAY}", text)
        self.assertIn("| New summary. |", self.read("wiki/index.md"))

    def test_set_adds_and_drops_list_refs(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/metadata-cache")
        self.assertIn('related:\n  - "[[wiki/general/obsidian/metadata-cache|Metadata cache]]"', self.read(self.article))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related-=general/obsidian/metadata-cache")
        self.assertNotIn("related:", self.read(self.article))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/nope", ok=False)

    def test_disputes_are_written_on_both_ends(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "disputes+=general/obsidian/metadata-cache")
        self.assertIn("[[wiki/general/obsidian/frontmatter-links|Obsidian property links]]", self.read(self.other))
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "disputes-=general/obsidian/metadata-cache")
        self.assertNotIn("disputes:", self.read(self.other))

    def test_superseded_by_marks_outdated_on_one_end_and_supersedes_on_the_other(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "superseded_by+=general/obsidian/metadata-cache")
        self.assertIn("status: outdated", self.read(self.article))
        self.assertIn("supersedes:\n  - \"[[wiki/general/obsidian/frontmatter-links|", self.read(self.other))
        self.sb("wiki", "set", "general/obsidian/metadata-cache", "supersedes-=general/obsidian/frontmatter-links")
        self.assertIn("status: current", self.read(self.article))
        self.assertNotIn("superseded_by", self.read(self.article))

    def test_set_refuses_an_unknown_status(self):
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "status=wrong", ok=False)


class Log(Seeded):
    def test_log_appends_a_dated_entry_with_links(self):
        self.sb("wiki", "log", "learn", "--subject", "general/obsidian/frontmatter-links", "--disposition", "New",
                "--raw", "wiki/raw/general/obsidian/link-cache")
        self.sb("wiki", "log", "ask", "--subject", "Archived: general/obsidian/frontmatter-links")
        self.sb("wiki", "log", "learn", "--subject", "no material: Clippings/A page.md")
        log = self.read("wiki/log.md")
        self.assertIn(f"## [{TODAY}] learn | [[wiki/general/obsidian/frontmatter-links|Obsidian property links]]\n"
                      "- Disposition: New\n- Raw: [[wiki/raw/general/obsidian/link-cache|Link cache]]\n", log)
        self.assertIn(f"## [{TODAY}] ask | Archived: [[wiki/general/obsidian/frontmatter-links|", log)
        self.assertTrue(log.endswith(f"## [{TODAY}] learn | no material: Clippings/A page.md\n"), log)
        self.sb("wiki", "log", "forget", "--subject", "x", ok=False)


class Backlog(Seeded):
    def test_backlog_lists_uncited_unlogged_sources_oldest_first(self):
        self.write("wiki/raw/general/obsidian/newer.md", "---\nwiki: raw\ntitle: Newer\ncreated: 2026-05-01\n---\nx\n")
        self.write("Clippings/Older.md", "---\ncreated: 2026-02-01\n---\nx\n")
        self.write("Clippings/Dismissed.md", "---\ncreated: 2026-01-01\n---\nx\n")
        self.map("m/one")
        self.ticket("m/one", 1, "Research done")
        self.ticket("m/one", 2, "Task done", type_="task")
        self.sb("wiki", "log", "learn", "--subject", "no material: Clippings/Dismissed.md")
        out = self.sb("wiki", "backlog").stdout
        lines = [l.split(" ")[0] for l in out.splitlines() if l.startswith(("wiki/", "Clippings/", "wayfinder/"))]
        # a note without `created` sorts by its file time: today, so last
        self.assertEqual(lines, ["Clippings/Older", "wiki/raw/general/obsidian/newer",
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
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache")
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/metadata-cache")
        self.append(self.article, "\nSee [[wiki/general/obsidian/metadata-cache|the cache]].\n")
        self.write("wiki/general/obsidian/gone.md", "---\nwiki: article\n---\n# Gone\n")
        self.sb("wiki", "set", "general/obsidian/frontmatter-links", "related+=general/obsidian/gone")
        (self.vault / "wiki/general/obsidian/gone.md").unlink()
        (self.vault / "wiki/general/cache").mkdir()
        self.write("wiki/general/cache/cache.md", "---\nwiki: topic\ntype: topic\nsummary: Caches.\n---\n# Cache\n\nCaches.\n")
        (self.vault / "wiki/general/obsidian/metadata-cache.md").rename(self.vault / "wiki/general/cache/metadata-cache.md")
        self.problems("moved", "general/obsidian/gone")
        self.sb("wiki", "check", "--fix")
        text = self.read(self.article)
        self.assertIn("[[wiki/general/cache/metadata-cache|Metadata cache]]", text)
        self.assertIn("[[wiki/general/cache/metadata-cache|the cache]]", text)
        self.assertNotIn("gone", text)

    def test_format_problems(self):
        self.write("wiki/general/obsidian/bad.md", "---\nwiki: article\ntype: concept\nstatus: wrong\n---\n# Bad\n")
        self.write("wiki/general/obsidian/deep/note.md", "---\nwiki: article\n---\n# Deep\n")
        self.write("wiki/general/orphan/2026-plan.md", "---\nwiki: article\n---\n# Plan\n")
        self.write("wiki/raw/general/x/frontmatter-links.md", "---\nwiki: raw\ntitle: T\nsource: s\n---\nB\n")
        self.problems("bad.md: unknown status 'wrong'", "bad.md: missing summary", "bad.md: missing sources",
                      "deep/note.md: deeper than wiki/<project>/<topic>/", "orphan: no folder note",
                      "2026-plan.md: slug starts with digits and a dash",
                      "slug 'frontmatter-links' is taken twice")

    def test_status_must_match_the_callouts_and_supersession(self):
        self.append(self.article, "\n> [!question] Disputed\n> A and B.\n\n> [!warning] Outdated\n> Was X.\n")
        self.problems("status is current; the rule makes it disputed", "Outdated callout without its date")

    def test_reciprocal_ends_must_both_exist(self):
        self.sb("wiki", "new", "general/obsidian/metadata-cache", "--title", "Metadata cache", "--type", "entity",
                "--summary", "S.", "--sources", "wiki/raw/general/obsidian/link-cache")
        text = self.read(self.article).replace("tags:", 'disputes:\n  - "[[wiki/general/obsidian/metadata-cache|M]]"\ntags:')
        self.write(self.article, text)
        self.problems("metadata-cache.md: missing disputes back to wiki/general/obsidian/frontmatter-links")

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
        self.append(self.article, "\nSee [[wiki/general/obsidian/obsidian|the topic]]. Write `[[mine]]` or `#123`, never bare.\n\n```\n[[other]] #456\n```\n")
        self.sb("wiki", "check")

    def test_grounding_suspects_are_printed_and_never_counted(self):
        self.append(self.article, "\nThe cache holds 42K links; 99.9% stay. \u201cA quote that no source holds at all\u201d.\n")
        out = self.sb("wiki", "check").stdout
        suspects = out[out.index("grounding suspect"):]
        self.assertIn("99.9%", suspects)
        self.assertIn("A quote that no source holds at all", suspects)
        self.assertNotIn("42K", suspects)
        self.assertIn("on the backlog", out)


class Projects(Seeded):
    """Every note lives under its project: the repo's folder name under wayfinder/, or general."""

    def setUp(self):
        super().setUp()
        self.map("monorepo/overrides")
        self.ticket("monorepo/overrides", 5, "The override data model", answer="Overrides key by part id.")
        self.sb("wiki", "new", "monorepo/part-hierarchy/part-ids", "--title", "Part ids", "--type", "entity",
                "--summary", "How parts are identified.", "--sources", "monorepo/overrides#005",
                "--about", "The product's part tree.")

    def test_new_writes_the_project_on_the_article_and_its_folder_note(self):
        self.assertIn("project: monorepo", self.read("wiki/monorepo/part-hierarchy/part-ids.md"))
        self.assertIn("project: monorepo", self.read("wiki/monorepo/part-hierarchy/part-hierarchy.md"))
        self.assertIn("project: general", self.read(self.article))

    def test_new_without_a_project_names_the_one_its_sources_come_from(self):
        r = self.sb("wiki", "new", "part-hierarchy/more", "--title", "More", "--type", "concept",
                    "--summary", "S.", "--sources", "monorepo/overrides#005", ok=False)
        self.assertIn("monorepo/part-hierarchy/more", r.stderr)

    def test_raw_needs_a_project_and_records_it(self):
        self.sb("wiki", "raw", "obsidian", "--title", "T", "--source", "x", "--from", "-", stdin="B\n", ok=False)
        path = self.sb("wiki", "raw", "monorepo/part-hierarchy", "--title", "T", "--source", "x",
                       "--from", "-", stdin="B\n").stdout.strip()
        self.assertEqual(path, "wiki/raw/monorepo/part-hierarchy/t.md")
        self.assertIn("project: monorepo", self.read(path))

    def test_index_groups_by_project_and_narrows_to_one_plus_general(self):
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Links")
        self.sb("wiki", "new", "semantra/graph/edges", "--title", "Edges", "--type", "concept",
                "--summary", "S.", "--sources", "semantra/plugin#007", "--about", "The graph.")
        idx = self.read("wiki/index.md")
        self.assertLess(idx.index("## general"), idx.index("## monorepo"))
        self.assertIn("## monorepo\n\n### part-hierarchy\n", idx)
        out = self.sb("wiki", "index", "--project", "monorepo").stdout
        self.assertIn("# monorepo\n## part-hierarchy: The product's part tree.", out)
        self.assertIn("# general", out)
        self.assertNotIn("semantra", out)

    def test_find_and_backlog_narrow_to_a_project_plus_general(self):
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Part ids elsewhere")
        out = self.sb("wiki", "find", "part", "--raw", "--project", "monorepo").stdout
        self.assertIn("wiki/monorepo/part-hierarchy/part-ids", out)
        self.assertNotIn("semantra", out)
        self.assertIn("semantra", self.sb("wiki", "find", "part", "--raw").stdout)
        self.write("wiki/raw/general/obsidian/loose.md", "---\nwiki: raw\ntitle: L\ncreated: 2026-01-01\n---\nx\n")
        back = self.sb("wiki", "backlog", "--project", "monorepo").stdout
        self.assertIn("loose", back)
        self.assertNotIn("semantra", back)

    def test_check_keeps_the_project_property_in_step_with_the_folder(self):
        path = "wiki/monorepo/part-hierarchy/part-ids.md"
        self.write(path, self.read(path).replace("project: monorepo", "project: semantra"))
        r = self.sb("wiki", "check", ok=False)
        self.assertIn("part-ids.md: project is semantra; its folder says monorepo", r.stdout)
        self.sb("wiki", "check", "--fix")
        self.assertIn("project: monorepo", self.read(path))

    def test_check_flags_the_old_layout(self):
        self.write("wiki/oldtopic/oldtopic.md", "---\nwiki: topic\ntype: topic\nsummary: S.\n---\n# Old\n\nS.\n")
        self.assertIn("old layout", self.sb("wiki", "check", ok=False).stdout)


class Migrate(VaultCase):
    """A wiki written before projects: topics straight under wiki/."""

    def setUp(self):
        super().setUp()
        self.sb("wiki", "init")
        self.map("monorepo/overrides")
        self.ticket("monorepo/overrides", 5, "The override data model")
        self.write("wiki/part-hierarchy/part-hierarchy.md",
                   "---\nwiki: topic\ntype: topic\nsummary: Parts.\ntags:\n  - wiki/topic\n---\n# Part hierarchy\n\nParts.\n")
        self.write("wiki/part-hierarchy/part-ids.md", """---
wiki: article
type: entity
status: current
summary: Ids.
updated: 2026-10-26
sources:
  - "[[wayfinder/monorepo/overrides/issues/005-the-override-data-model|#005]]"
  - "[[wiki/raw/part-hierarchy/dump|Dump]]"
tags:
  - wiki/entity
---
# Part ids

## Overview

Ids. See [[wiki/part-hierarchy/part-hierarchy|the topic]].
""")
        self.write("wiki/raw/part-hierarchy/dump.md", "---\nwiki: raw\ntype: source\ntitle: Dump\nsource: x\n---\nIds.\n")
        self.sb("wiki", "log", "learn", "--subject", "wiki/part-hierarchy/part-ids")
        self.write("wayfinder/monorepo/overrides/report.md", "Findings: [[wiki/part-hierarchy/part-ids|Part ids]]\n")
        self.write("Notes/mine.md", "My link: [[wiki/part-hierarchy/part-ids|Part ids]]\n")

    def test_dry_run_lists_the_moves_and_writes_nothing(self):
        out = self.sb("wiki", "migrate", "monorepo").stdout
        self.assertIn("wiki/part-hierarchy -> wiki/monorepo/part-hierarchy", out)
        self.assertIn("wiki/raw/part-hierarchy -> wiki/raw/monorepo/part-hierarchy", out)
        self.assertIn("dry run", out)
        self.assertTrue(self.exists("wiki/part-hierarchy/part-ids.md"))

    def test_write_moves_relinks_and_leaves_a_clean_wiki(self):
        out = self.sb("wiki", "migrate", "monorepo", "--write").stdout
        art = self.read("wiki/monorepo/part-hierarchy/part-ids.md")
        self.assertIn("project: monorepo", art)
        self.assertIn("[[wiki/raw/monorepo/part-hierarchy/dump|Dump]]", art)
        self.assertIn("[[wiki/monorepo/part-hierarchy/part-hierarchy|the topic]]", art)
        self.assertIn("project: monorepo", self.read("wiki/monorepo/part-hierarchy/part-hierarchy.md"))
        self.assertNotIn("project", self.read("wiki/raw/monorepo/part-hierarchy/dump.md"))  # raw is never edited
        self.assertIn("[[wiki/monorepo/part-hierarchy/part-ids|", self.read("wiki/log.md"))
        self.assertIn("[[wiki/monorepo/part-hierarchy/part-ids|", self.read("wayfinder/monorepo/overrides/report.md"))
        self.assertIn("[[wiki/part-hierarchy/part-ids|", self.read("Notes/mine.md"))  # the owner's note
        self.assertIn("Notes/mine.md", out)
        self.assertFalse(self.exists("wiki/part-hierarchy"))
        self.sb("wiki", "check")

    def test_only_the_named_topics_move(self):
        self.write("wiki/obsidian/obsidian.md", "---\nwiki: topic\ntype: topic\nsummary: O.\n---\n# Obsidian\n\nO.\n")
        self.sb("wiki", "migrate", "monorepo", "part-hierarchy", "--write")
        self.assertTrue(self.exists("wiki/obsidian/obsidian.md"))
        self.sb("wiki", "migrate", "general", "--write")
        self.assertTrue(self.exists("wiki/general/obsidian/obsidian.md"))


if __name__ == "__main__":
    unittest.main()
