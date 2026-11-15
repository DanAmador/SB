"""What a ticket's properties say about it at a glance: its model, who checks it, how its second pass went, and
whether it was filed while a night ran."""
import json
import unittest
from pathlib import Path

from helpers import VaultCase

MAP = "monorepo/overrides"


class TicketFields(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", MAP, "--why", "Because.", "--title", "Overrides", "--destination", "Somewhere.",
                "--repo", "/code/monorepo")

    def new(self, title, *extra, ok=True):
        r = self.sb("new", MAP, "--why", "Because.", "--title", title, "--no-sync", *extra, ok=ok)
        return (self.vault / r.stdout.strip()) if ok else r

    def test_a_new_ticket_names_its_model_and_who_checks_it(self):
        text = self.new("First").read_text()
        self.assertIn("tier: sonnet\n", text)
        self.assertIn("check: tests\n", text)
        text = self.new("Second", "--tier", "opus", "--check", "owner").read_text()
        self.assertIn("tier: opus\n", text)
        self.assertIn("check: owner\n", text)

    def test_unknown_model_or_checker_is_refused(self):
        self.new("Bad", "--tier", "haiku", ok=False)
        self.new("Bad", "--check", "someone", ok=False)
        self.new("Good")
        self.sb("set", MAP, "001", "check=someone", "--no-sync", ok=False)
        self.sb("set", MAP, "001", "review=great", "--no-sync", ok=False)
        self.sb("set", MAP, "001", "check=owner", "review=partly", "--no-sync")
        text = next(self.vault.glob("wayfinder/monorepo/overrides/issues/001*.md")).read_text()
        self.assertIn("check: owner\n", text)
        self.assertIn("review: partly\n", text)

    def test_a_ticket_filed_while_a_night_runs_says_which_night(self):
        hub = Path(self._tmp.name) / "hub"
        hub.mkdir()
        night = {"id": "night-1", "name": "Night of 2026-11-15, 02:15", "state": "live", "items": []}
        (hub / "state.json").write_text(json.dumps({"queue": {"night": "night-1", "items": []}, "nights": [night]}))
        self.hub_home = str(hub)
        self.assertIn('filed_during: "Night of 2026-11-15, 02:15"\n', self.new("During").read_text())
        night["state"] = "ended"
        (hub / "state.json").write_text(json.dumps({"queue": {"night": None, "items": []}, "nights": [night]}))
        self.assertNotIn("filed_during", self.new("After").read_text())

    def test_no_hub_means_no_night(self):
        self.assertNotIn("filed_during", self.new("Alone").read_text())

    def test_resolve_records_the_review_verdict_and_links_the_review(self):
        self.new("Reviewed")
        self.new("Unreviewed")
        self.sb("new", MAP, "--why", "Because.", "--title", "Looked into", "--type", "research", "--no-sync")
        review = self.vault / "wayfinder/monorepo/runs/night/1-review.md"
        review.parent.mkdir(parents=True)
        review.write_text("Verdict: finished\n")
        self.sb("resolve", MAP, "001", "--gist", "g", "--answer", "a", "--review", "met", "--review-file", str(review),
                "--no-sync")
        self.sb("resolve", MAP, "002", "--gist", "g", "--answer", "a", "--no-sync")
        self.sb("resolve", MAP, "003", "--gist", "g", "--answer", "a", "--no-sync")
        self.sb("resolve", MAP, "002", "--gist", "g", "--answer", "a", "--review", "fine", "--no-sync", ok=False)
        done = self.vault / "wayfinder/monorepo/overrides/issues/done"
        one = next(done.glob("001*.md")).read_text()
        self.assertIn("review: met\n", one)
        self.assertIn('review_note: "[[wayfinder/monorepo/runs/night/1-review|review]]"\n', one)
        self.assertIn("review: skipped\n", next(done.glob("002*.md")).read_text())
        self.assertNotIn("review:", next(done.glob("003*.md")).read_text())  # research has no second pass

    def test_the_queue_facts_carry_who_checks(self):
        self.new("Mine", "--check", "owner")
        rows = json.loads(self.sb("tickets", "--json").stdout)
        self.assertEqual(rows[0]["check"], "owner")

    def test_the_boards_show_the_new_fields(self):
        self.sb("board", MAP)
        board = (self.vault / "wayfinder/monorepo/overrides/board.base").read_text()
        for field in ("review", "check", "tier", "filed_during"):
            self.assertIn(f"      - {field}\n", board)


if __name__ == "__main__":
    unittest.main()
