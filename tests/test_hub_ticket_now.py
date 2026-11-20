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


class BashCommandLabelTest(unittest.TestCase):
    """The real hook report: a Bash call without a description says its command, so the trail can name it."""

    def report(self, tin):
        return sbhub.event_report({"session_id": "s1", "cwd": "/w/p", "hook_event_name": "PreToolUse",
                                   "tool_name": "Bash", "tool_input": tin})

    def test_command_when_no_description(self):
        r = self.report({"command": "pnpm   typecheck\n&& echo ok"})
        self.assertEqual(r["trail"]["label"], "pnpm typecheck && echo ok")
        self.assertEqual(r["note"], "Bash: pnpm typecheck && echo ok")

    def test_description_still_wins(self):
        self.assertEqual(self.report({"description": "Typecheck", "command": "pnpm typecheck"})["trail"]["label"], "Typecheck")
