"""sbmap mapset, tier/checks on tickets, and `tickets --json`: what a queue needs to know."""
import json

from helpers import VaultCase


class QueueFactsTest(VaultCase):
    def init(self, folder, **kw):
        extra = [x for k, v in kw.items() for x in (f"--{k}", v)]
        self.sb("init", folder, "--title", folder, "--why", "Why.", "--destination", "Somewhere.", *extra)

    def new(self, folder, title, *extra):
        self.sb("new", folder, "--title", title, "--why", "Because.", "--no-sync", *extra)

    def tickets(self, *args):
        return json.loads(self.sb("tickets", "--json", *args).stdout)

    def by_num(self, rows, folder, num):
        return next(r for r in rows if r["num"] == num and r["map"].endswith(folder))

    def test_map_checks_apply_unless_ticket_has_own(self):
        self.init("repo/one")
        self.new("repo/one", "Plain")
        self.new("repo/one", "Own")
        self.sb("mapset", "repo/one", "checks=cmd one; cmd two")
        self.sb("set", "repo/one", "2", "checks=only this", "--no-sync")
        rows = self.tickets()
        self.assertEqual(self.by_num(rows, "one", 1)["checks"], ["cmd one", "cmd two"])
        self.assertEqual(self.by_num(rows, "one", 2)["checks"], ["only this"])
        self.assertIn("cmd one", self.sb("info", "repo/one").stdout)

    def test_tier_defaults_and_is_validated(self):
        self.init("repo/one")
        self.new("repo/one", "A")
        self.assertEqual(self.tickets()[0]["tier"], "sonnet")
        self.sb("set", "repo/one", "1", "tier=opus", "--no-sync")
        self.assertEqual(self.tickets()[0]["tier"], "opus")
        self.sb("set", "repo/one", "1", "tier=fast", "--no-sync", ok=False)

    def test_blocked_by_open_empties_after_resolve(self):
        self.init("repo/one")
        self.new("repo/one", "A")
        self.new("repo/one", "B")
        self.new("repo/one", "C", "--blocked-by", "1,2")
        self.sb("resolve", "repo/one", "1", "--gist", "g", "--answer", "y", "--no-sync")
        rows = self.tickets()
        self.assertEqual({r["num"] for r in rows}, {2, 3})
        c = self.by_num(rows, "one", 3)
        self.assertEqual(c["blocked_by"], [1, 2])
        self.assertEqual(c["blocked_by_open"], [2])
        self.sb("resolve", "repo/one", "2", "--gist", "g", "--answer", "y", "--no-sync")
        self.assertEqual(self.tickets()[0]["blocked_by_open"], [])

    def test_fields(self):
        self.init("repo/one")
        self.new("repo/one", "Full", "--done-when", "It works.", "--question", "Why?", "--out", "Other",
                 "--paths", "a.py,docs/", "--priority", "high")
        self.new("repo/one", "Bare")
        self.sb("set", "repo/one", "1", "status=claimed", "claimed_by=me", "--no-sync")
        rows = self.tickets()
        a, b = self.by_num(rows, "one", 1), self.by_num(rows, "one", 2)
        self.assertTrue(a["has_done_when"])
        self.assertEqual((a["done_when"], a["question"], a["out"]), ("It works.", "Why?", "Other"))
        self.assertEqual(a["paths"], ["a.py", "docs/"])
        self.assertEqual(a["priority"], "A")
        self.assertEqual(a["claimed_by"], "me")
        self.assertEqual(a["status"], "claimed")
        self.assertFalse(b["has_done_when"])
        self.assertIsNone(b["claimed_by"])
        self.assertEqual((a["title"], a["why"], a["type"]), ("Full", "Because.", "task"))

    def test_repo_filter_and_archived(self):
        self.init("alpha/one", repo="/x/alpha")
        self.init("beta/two", repo="/x/beta")
        self.new("alpha/one", "A")
        self.new("beta/two", "B")
        self.assertEqual({r["map_title"] for r in self.tickets()}, {"alpha/one", "beta/two"})
        rows = self.tickets("--repo", "/x/beta")
        self.assertEqual([r["map_title"] for r in rows], ["beta/two"])
        self.assertEqual(rows[0]["repo"], "/x/beta")
        self.sb("resolve", "alpha/one", "1", "--gist", "g", "--answer", "y", "--no-sync")
        self.sb("close", "alpha/one")
        self.assertEqual({r["map_title"] for r in self.tickets()}, {"beta/two"})

    def test_map_order_follows_map(self):
        self.init("repo/one")
        self.new("repo/one", "First")
        self.new("repo/one", "Second")
        self.new("repo/one", "Third")
        p = self.vault / "wayfinder/repo/one/map.md"
        files = {f.name[:3]: f.stem for f in (self.vault / "wayfinder/repo/one/issues").glob("*.md")}
        p.write_text(p.read_text().rstrip() + "\n\n" + "\n".join(f"[[{files[n]}]]" for n in ("003", "001", "002")) + "\n")
        rows = self.tickets()
        self.assertEqual([r["num"] for r in sorted(rows, key=lambda r: r["map_order"])], [3, 1, 2])
