"""How a skipped run says where its ticket stands now: never "claimed by None"."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbhub  # noqa: E402


class TicketNowTest(unittest.TestCase):
    def test_a_claim_names_who_holds_it(self):
        self.assertEqual(sbhub._ticket_now({"status": "claimed", "claimed_by": "a live session"}), "claimed by a live session")

    def test_a_claim_with_no_name_is_someone_else(self):
        self.assertEqual(sbhub._ticket_now({"status": "claimed", "claimed_by": None}), "claimed by someone else")

    def test_an_open_ticket_is_not_called_claimed(self):
        self.assertEqual(sbhub._ticket_now({"status": "open", "claimed_by": None}), "now open")


if __name__ == "__main__":
    unittest.main()
