import os
import subprocess
import unittest
from pathlib import Path

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


class ResolveStampsTheCommit(VaultCase):
    MAP = "monorepo/overrides"

    def setUp(self):
        super().setUp()
        self.clone = Path(self._tmp.name) / "clone"
        self.git("init", "-q", "-b", "main", str(self.clone))
        self.git("-C", str(self.clone), "remote", "add", "origin", "git@github.com:acme/widgets.git")
        (self.clone / "a.py").write_text("a\n")
        (self.clone / "docs").mkdir()
        (self.clone / "docs" / "b.md").write_text("b\n")
        self.git("-C", str(self.clone), "add", ".")
        self.git("-C", str(self.clone), "commit", "-q", "-m", "work")
        self.sha = self.git("-C", str(self.clone), "rev-parse", "HEAD").stdout.strip()
        self.sb("init", self.MAP, "--title", "Overrides", "--destination", "Somewhere.", "--repo", str(self.clone))
        self.sb("new", self.MAP, "--title", "First", "--paths", "planned/", "--no-sync")
        self.ticket_path = "wayfinder/monorepo/overrides/issues/001 First.md"

    def git(self, *args):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, env=env)

    def gh(self, body):
        """A fake gh first on PATH; the suite never reaches the network."""
        d = Path(self._tmp.name) / "bin"
        d.mkdir(exist_ok=True)
        (d / "gh").write_text(f"#!/bin/sh\n{body}\n")
        (d / "gh").chmod(0o755)
        return f"{d}:/usr/bin:/bin"

    def resolve(self, *extra, **kw):
        return self.sb("resolve", self.MAP, "1", "--gist", "done", "--answer", "Yes.", "--no-sync", *extra, **kw)

    def test_the_commit_gives_the_ticket_its_provenance_and_its_pr(self):
        path = self.gh(f'echo \'[{{"url": "https://github.com/acme/widgets/pull/7"}}]\'; '
                       f'[ "$4" = "{self.sha}" ] || exit 1')
        self.resolve("--commit", self.sha[:8], path=path)
        text = self.read(self.ticket_path)
        self.assertIn(f"repo: acme/widgets\ncommit: {self.sha}\nref: main\npr: ", text)
        self.assertIn('pr: "https://github.com/acme/widgets/pull/7"', text)
        self.assertIn("paths:\n  - a.py\n  - docs/b.md\n", text)
        self.assertNotIn("planned/", text)
        self.assertIn("status: Project.Finished", text)
        self.sb("check", self.MAP, ok=None)
        self.assertNotIn("001", self.sb("check", self.MAP, ok=None).stdout.replace("001 First", ""))

    def test_paths_override_the_diff_and_no_gh_leaves_no_pr(self):
        self.resolve("--commit", self.sha, "--paths", "x/,y.py", "--repo-root", str(self.clone))
        text = self.read(self.ticket_path)
        self.assertIn("paths:\n  - x/\n  - y.py\n", text)
        self.assertNotIn("pr:", text)

    def test_a_failing_gh_or_no_pr_is_silent(self):
        for body in ("exit 1", "echo []", "echo not json"):
            self.resolve("--commit", self.sha, path=self.gh(body))
            self.assertNotIn("pr:", self.read(self.ticket_path), body)
            self.sb("set", self.MAP, "1", "status=open", "--no-sync")

    def test_a_commit_off_the_current_branch_has_no_ref(self):
        self.git("-C", str(self.clone), "checkout", "-q", "-b", "side")
        (self.clone / "c.py").write_text("c\n")
        self.git("-C", str(self.clone), "add", ".")
        self.git("-C", str(self.clone), "commit", "-q", "-m", "side")
        side = self.git("-C", str(self.clone), "rev-parse", "HEAD").stdout.strip()
        self.git("-C", str(self.clone), "checkout", "-q", "main")
        self.resolve("--commit", side)
        text = self.read(self.ticket_path)
        self.assertIn(f"commit: {side}\n", text)
        self.assertNotIn("ref:", text)
        self.assertIn("paths:\n  - c.py\n", text)

    def test_an_unknown_sha_writes_nothing(self):
        before = self.read(self.ticket_path), self.read("wayfinder/monorepo/overrides/map.md")
        self.resolve("--commit", "deadbeef", ok=False)
        self.assertEqual(before, (self.read(self.ticket_path), self.read("wayfinder/monorepo/overrides/map.md")))

    def test_a_resolve_without_a_commit_stamps_nothing(self):
        self.resolve()
        text = self.read(self.ticket_path)
        for key in ("repo:", "commit:", "ref:", "pr:"):
            self.assertNotIn(key, text)
        self.assertIn("planned/", text)
        self.assertIn("status: Project.Finished", text)
