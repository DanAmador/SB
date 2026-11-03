"""sbmap info: a map's bearings in a few lines, and a repo's open maps."""
import re

from helpers import VaultCase


class InfoTest(VaultCase):
    def init(self, folder, title, why):
        self.sb("init", folder, "--title", title, "--why", why, "--destination", "Somewhere.")

    def new(self, folder, title, why, *extra):
        self.sb("new", folder, "--title", title, "--why", why, "--no-sync", *extra)

    def test_one_map(self):
        self.init("repo/one", "Map one", "Because the owner wants one.")
        self.sb("summary", "repo/one", "--text", "Plain words here.")
        self.new("repo/one", "First step", "The first problem. And more.")
        self.new("repo/one", "Second step", "The second problem.", "--blocked-by", "1")
        self.new("repo/one", "Done step", "Already cleared.")
        self.sb("resolve", "repo/one", "3", "--gist", "done", "--answer", "Yes.", "--no-sync")
        out = self.sb("info", "repo/one").stdout
        self.assertIn("# Map one", out)
        self.assertIn("Plain words here.", out)
        self.assertIn("1 resolved", out)
        self.assertIn("▸ 001 First step — The first problem.", out)
        self.assertNotIn("And more", out)
        self.assertIn("blocked: 002", out)
        self.assertNotIn("Done step", out)

    def test_claimed_ticket_names_who(self):
        self.init("repo/one", "Map one", "Why.")
        self.new("repo/one", "First step", "The first problem.")
        self.sb("claim", "repo/one", "1", "--by", "night run", "--no-sync")
        out = self.sb("info", "repo/one").stdout
        self.assertRegex(out, r"\[night run[^\]]*\] 001 First step — The first problem\.")

    def test_repo_lists_only_open_maps(self):
        repo = self.vault.parent / "repo"
        repo.mkdir()
        self.init("repo/open", "Open map", "Why open.")
        self.sb("summary", "repo/open", "--text", "Open words. More words.")
        self.init("repo/shut", "Shut map", "Why shut.")
        self.sb("summary", "repo/shut", "--text", "Shut words.")
        p = self.vault / "wayfinder/repo/shut/map.md"
        p.write_text(re.sub(r"status: \S+", "status: Project.Finished", p.read_text(), count=1))
        out = self.sb("info", "--repo", str(repo)).stdout
        self.assertIn("open · Open map", out)
        self.assertIn("Open words.", out)
        self.assertNotIn("More words", out)
        self.assertNotIn("Shut", out)
