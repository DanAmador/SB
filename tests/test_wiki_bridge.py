"""sb's half of the wiki (wiki_bridge.py): tickets and research notes as sources, which wikibrain no
longer knows about, all through `sbmap wiki`."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from helpers import SBMAP, VaultCase

WIKIBRAIN = Path.home() / "Documents/Coding/wikiBrain/skills/wikibrain/scripts"


class Bridge(VaultCase):
    def setUp(self):
        super().setUp()
        env = {"WIKIBRAIN_CACHE": str(Path(self._tmp.name) / "cache")}
        if WIKIBRAIN.is_dir():
            env["WIKIBRAIN_DIR"] = str(WIKIBRAIN)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.sb("wiki", "init")
        self.map("semantra/plugin")
        self.ticket("semantra/plugin", 7, "Does it read links")

    def new(self, slug, sources, ok=True):
        return self.sb("wiki", "new", f"semantra/obsidian/{slug}", "--title", slug.capitalize(), "--type", "concept",
                       "--summary", "S.", "--sources", sources, "--about", "Obsidian.", ok=ok)

    def test_a_ticket_ref_becomes_its_full_path_link_and_must_be_resolved(self):
        self.new("links", "semantra/plugin#007")
        self.assertIn('"[[wayfinder/semantra/plugin/issues/007-does-it-read-links|Does it read links]]"',
                      self.read("wiki/semantra/obsidian/links.md"))
        self.ticket("semantra/plugin", 8, "Still open", status="Project.Planned")
        r = self.new("open", "semantra/plugin#8", ok=False)
        self.assertIn("semantra/plugin#8 is a ticket that is not resolved", r.stderr)
        self.sb("wiki", "check")

    def test_a_done_ticket_and_a_ticket_in_a_closed_map_still_resolve(self):
        p = self.vault / "wayfinder/semantra/plugin/issues/007-does-it-read-links.md"
        (p.parent / "done").mkdir()
        p.rename(p.parent / "done" / p.name)
        self.map("semantra/old")
        self.ticket("semantra/old", 3, "Old answer")
        (self.vault / "wayfinder/semantra/archive").mkdir()
        (self.vault / "wayfinder/semantra/old").rename(self.vault / "wayfinder/semantra/archive/old")
        self.new("links", "semantra/plugin#007,semantra/old#3")
        text = self.read("wiki/semantra/obsidian/links.md")
        self.assertIn("[[wayfinder/semantra/plugin/issues/done/007-does-it-read-links|", text)
        self.assertIn("[[wayfinder/semantra/archive/old/issues/003-old-answer|", text)
        self.sb("wiki", "check")

    def test_set_and_prose_with_a_hash_pass_through(self):
        self.write("wiki/raw/semantra/obsidian/r.md", "---\nwiki: raw\ntype: source\ntitle: R\nsource: s\n---\nB\n")
        self.new("links", "wiki/raw/semantra/obsidian/r")
        self.sb("wiki", "set", "semantra/obsidian/links", "sources+=semantra/plugin#007")
        self.assertIn("007-does-it-read-links|", self.read("wiki/semantra/obsidian/links.md"))
        self.sb("wiki", "supersede", "semantra/obsidian/links", "--claim", "S.", "--now", "fixes #12, then more",
                "--source", "wiki/raw/semantra/obsidian/r")
        self.assertIn("fixes #12, then more", self.read("wiki/semantra/obsidian/links.md"))

    def test_find_raw_reaches_research_notes_and_tickets(self):
        self.write("wayfinder/semantra/plugin/research/zebra.md", "# Zebra notes\n\nzebra\n")
        self.ticket("semantra/plugin", 9, "Zebra ticket")
        out = self.sb("wiki", "find", "zebra", "--raw").stdout
        self.assertIn("wayfinder/semantra/plugin/research/zebra", out)
        self.assertIn("wayfinder/semantra/plugin/issues/009-zebra-ticket", out)

    def test_backlog_adds_research_notes_and_resolved_research_tickets(self):
        self.write("wayfinder/semantra/plugin/research/notes.md", "---\ncreated: 2026-01-02\n---\n# Notes\n")
        self.ticket("semantra/plugin", 8, "Task done", type_="task")
        self.ticket("semantra/plugin", 9, "Open research", status="Project.Planned")
        self.map("monorepo/other")
        self.write("wayfinder/monorepo/other/research/elsewhere.md", "# Elsewhere\n")
        out = self.sb("wiki", "backlog").stdout
        self.assertIn("wayfinder/semantra/plugin/research/notes · 2026-01-02 · Notes", out)
        self.assertIn("wayfinder/semantra/plugin/issues/007-does-it-read-links", out)
        self.assertNotIn("008-task-done", out)
        self.assertNotIn("009-open-research", out)
        self.assertIn("3 on the backlog", out)
        self.assertNotIn("elsewhere", self.sb("wiki", "backlog", "--project", "semantra").stdout)
        self.new("links", "semantra/plugin#007")
        self.assertNotIn("007-does-it-read-links", self.sb("wiki", "backlog").stdout)

    def test_check_flags_open_tickets_tracker_notes_and_bare_numbers(self):
        self.new("links", "semantra/plugin#007")
        path = "wiki/semantra/obsidian/links.md"
        self.ticket("semantra/plugin", 8, "Still open", status="Project.Planned")
        text = self.read(path).replace("sources:\n", 'sources:\n  - "[[wayfinder/semantra/plugin/issues/008-still-open|#008]]"\n'
                                       '  - "[[wayfinder/semantra/plugin/map|Test map]]"\n')
        self.write(path, text + "\nSee #123.\n")
        out = self.sb("wiki", "check", ok=False).stdout
        self.assertIn("008-still-open is a ticket that is not resolved", out)
        self.assertIn("wayfinder/semantra/plugin/map is not a research note or a resolved ticket", out)
        self.assertIn("bare #123", out)
        self.assertIn("3 problem(s) from the maps", out)

    def test_migrate_relinks_the_maps_too(self):
        self.write("wiki/old/old.md", "---\nwiki: topic\ntype: topic\nsummary: Old.\ntags:\n  - wiki/topic\n---\n# Old\n\nOld.\n")
        self.write("wayfinder/semantra/plugin/report.md", "Findings: [[wiki/old/old|Old]]\n")
        self.sb("wiki", "migrate", "semantra", "--write")
        self.assertIn("[[wiki/semantra/old/old|Old]]", self.read("wayfinder/semantra/plugin/report.md"))

    def test_tend_without_repos_verifies_the_repos_the_maps_name(self):
        repo = Path(self._tmp.name) / "plugin"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        text = self.read("wayfinder/semantra/plugin/map.md").replace("status:", f"repo: {repo}\nstatus:", 1)
        self.write("wayfinder/semantra/plugin/map.md", text)
        self.sb("wiki", "tend", ok=None)
        r = self.sb("wiki", "tend", "--json", ok=None)
        self.assertIn(str(repo), r.stdout + r.stderr)


@unittest.skipUnless(WIKIBRAIN.is_dir(), "needs the wikibrain checkout")
class VaultOnly(unittest.TestCase):
    """`dump` keeps `tickets` in the vault, on top of whatever the clone already keeps there."""

    def setUp(self):
        sys.path[:0] = [str(SBMAP.parent), str(WIKIBRAIN)]
        self.addCleanup(lambda: [sys.path.remove(p) for p in (str(SBMAP.parent), str(WIKIBRAIN))])
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.clone = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", str(self.clone)], check=True)
        import wiki_bridge

        class Sb:
            @staticmethod
            def opt(args, name, default=None):
                return args[args.index(name) + 1] if name in args else default
        self.bridge, self.sbmod = wiki_bridge, Sb

    def test_tickets_join_what_the_clone_remembers_or_what_was_given(self):
        c = str(self.clone)
        self.assertEqual(self.bridge.vault_only(["dump", c], self.sbmod), ["dump", c, "--vault-only", "tickets"])
        subprocess.run(["git", "-C", c, "config", "wikibrain.vaultOnly", "notes"], check=True)
        self.assertEqual(self.bridge.vault_only(["dump", c], self.sbmod)[-1], "notes,tickets")
        subprocess.run(["git", "-C", c, "config", "wikibrain.vaultOnly", "notes,tickets"], check=True)
        self.assertEqual(self.bridge.vault_only(["dump", c], self.sbmod), ["dump", c])
        self.assertEqual(self.bridge.vault_only(["dump", c, "--vault-only", "x", "--base", "main"], self.sbmod),
                         ["dump", c, "--vault-only", "x,tickets", "--base", "main"])


if __name__ == "__main__":
    unittest.main()
