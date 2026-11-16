"""A decision ticket lists its options with the recommended one marked, and the owner's answer is stored as its ruling."""
import json
import sys
import unittest
from pathlib import Path

from helpers import VaultCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/sb/scripts"))
import sbqueue  # noqa: E402

MAP = "monorepo/choices"


class Decisions(VaultCase):
    def setUp(self):
        super().setUp()
        self.sb("init", MAP, "--why", "Because.", "--title", "Choices", "--destination", "Somewhere.",
                "--repo", "/code/monorepo")

    def grill(self, *extra, ok=True):
        return self.sb("new", MAP, "--why", "Because.", "--title", "Which one", "--type", "grilling",
                       "--question", "Badges or text?", "--no-sync", "--not-a-duplicate", *extra, ok=ok)

    def row(self):
        return json.loads(self.sb("tickets", "--json").stdout)[0]

    def test_a_decision_ticket_without_options_or_a_default_is_refused(self):
        self.grill(ok=False)
        self.grill("--option", "Badges", ok=False)
        self.grill("--option", "Badges", "--option", "Text", ok=False)
        self.grill("--option", "Badges", "--option", "Text", "--default", "3", ok=False)

    def test_options_are_a_list_with_the_default_marked(self):
        path = self.vault / self.grill("--option", "Badges on GitHub", "--option", "Text only",
                                       "--default", "2").stdout.strip()
        self.assertIn("## Options\n\n- Badges on GitHub\n- ➡️ Text only\n", path.read_text())
        self.assertEqual(self.row()["options"], [{"text": "Badges on GitHub", "recommended": False},
                                                 {"text": "Text only", "recommended": True}])
        self.assertIsNone(self.row()["ruling"])

    def test_a_ruling_picks_an_option_adds_words_and_takes_it_off_the_owners_list(self):
        self.grill("--option", "Badges", "--option", "➡️ Text")
        self.assertEqual(sbqueue.classify(self.row(), set())[0], "waits for you")
        self.sb("rule", MAP, "001", "--pick", "9", ok=False)
        self.sb("rule", MAP, "001", "--pick", "2", "--text", "but keep one badge")
        row = self.row()
        self.assertEqual(row["ruling"], "Text but keep one badge")
        self.assertIn("R: Text but keep one badge", Path(row["file"]).read_text())
        self.assertEqual(sbqueue.classify(row, set())[0], "not ready")

    def test_a_ruling_in_the_owners_own_words(self):
        self.grill("--option", "Badges", "--option", "Text", "--default", "1")
        self.sb("rule", MAP, "001", ok=False)  # nothing given
        self.assertIsNone(self.row()["ruling"])
        self.sb("rule", MAP, "001", "--text", "Neither: drop the table")
        self.assertEqual(self.row()["ruling"], "Neither: drop the table")

    def test_set_rewrites_an_old_question_into_context_and_options(self):
        self.sb("new", MAP, "--why", "Because.", "--title", "Old one", "--type", "task", "--question",
                "Options: (a) X; (b) Y. ➡️ (b)", "--done-when", "Answered.", "--no-sync")
        self.sb("set", MAP, "001", "options=➡️ X\\n➡️ Y", "--no-sync", ok=False)
        self.sb("set", MAP, "001", "options=X\\nY", "--no-sync", ok=False)
        self.sb("set", MAP, "001", "question=Which look?", "options=- X\\n- ➡️ Y", "--no-sync")
        text = Path(self.row()["file"]).read_text()
        self.assertIn("## Question\n\nWhich look?\n\n## Options\n\n- X\n- ➡️ Y\n\n## Done when\n\nAnswered.", text)


if __name__ == "__main__":
    unittest.main()
