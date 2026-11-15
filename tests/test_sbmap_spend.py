"""sbmap spend: a ticket's cost on its note; the numbers add to the ones already there."""
from helpers import VaultCase


class SpendTest(VaultCase):
    def test_numbers_add_and_labels_replace(self):
        self.sb("init", "r/m", "--title", "m", "--why", "w", "--destination", "d")
        self.sb("new", "r/m", "--title", "t", "--why", "w", "--done-when", "x", "--no-sync")
        self.sb("spend", "r/m", "1", "run_minutes=10.5", "tries=1", "model=sonnet", "outcome=failed")
        self.sb("spend", "r/m", "1", "run_minutes=4.5", "tries=1", "tokens_in=7", "model=opus", "outcome=done")
        text = next(self.vault.glob("wayfinder/**/001*.md")).read_text(encoding="utf-8")
        for line in ("run_minutes: 15", "tries: 2", "tokens_in: 7", "model: opus", "outcome: done"):
            self.assertIn(line, text)
        self.assertNotIn("tokens_out", text)
        self.sb("spend", "r/m", "1", "bogus=1", ok=False)
