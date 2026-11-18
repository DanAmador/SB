"""In Play lines (ticket 148): which Done-when items are Editor checks, and how the worker's and the review's briefs
name them. The hub's own flow (the Unity lock, the checklist note) is in test_hub_runner.PlayReviewTest."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
import sbqueue  # noqa: E402


def ticket(done_when):
    return {"num": 7, "map": "repo/one", "title": "T", "why": "W", "question": "", "out": "", "paths": ["a/"],
            "done_when": done_when, "checks": ["true"]}


class PlayLinesTest(unittest.TestCase):
    def test_numbered_items_on_one_line_as_sbmap_tickets_prints_many_done_whens(self):
        dw = "1. A test: the hub resolves it. 2. In Play: a dash rolls back. 3. The checks pass."
        self.assertEqual(sbqueue.done_items(dw), ["A test: the hub resolves it.", "In Play: a dash rolls back.",
                                                  "The checks pass."])
        self.assertEqual(sbqueue.play_lines(dw), ["In Play: a dash rolls back."])

    def test_list_lines_a_continued_line_and_the_older_comma_and_bare_forms(self):
        dw = "- It works.\n- In Play: a Bat comes to you\n  when you hold the button.\n3. In Play, Stasis shows blue."
        self.assertEqual(sbqueue.play_lines(dw), ["In Play: a Bat comes to you when you hold the button.",
                                                  "In Play, Stasis shows blue."])
        self.assertEqual(sbqueue.play_lines("In Play the gun pushes as before. Console clean."),
                         ["In Play the gun pushes as before. Console clean."])

    def test_no_editor_check_has_no_play_lines(self):
        for dw in ("", "1. A test passes. 2. In the Playground nothing changes.", "In Playground mode it opens."):
            self.assertEqual(sbqueue.play_lines(dw), [], dw)


class BriefsTest(unittest.TestCase):
    def test_the_worker_is_told_to_leave_the_in_play_line_and_a_ticket_without_one_is_told_nothing(self):
        brief = sbqueue.brief(ticket("1. It works. 2. In Play: a dash rolls back."), "Why.", "/run", "/repo", "b")
        self.assertIn("Done when: 1. It works. 2. In Play: a dash rolls back.\n" + sbqueue.PLAY_BRIEF +
                      "\n- In Play: a dash rolls back.\n", brief)
        self.assertNotIn("Played by the review", sbqueue.brief(ticket("1. It works."), "Why.", "/run", "/repo", "b"))

    def section(self, play):
        return sbqueue.review_section("#7: T", "/repo", ["abc"], "diff", "/run/7.md", "report", "/run/7-review.md",
                                      play=play, media="/run/7-media")

    def test_the_review_brief_lists_the_lines_and_says_whether_the_hub_holds_the_lock(self):
        sec = self.section(["In Play: a dash rolls back."])
        self.assertIn("### Its In Play lines\n\n- In Play: a dash rolls back.\n\nIts screenshots go in: /run/7-media\n\n"
                      "### The worker's report", sec)
        held = sbqueue.review_brief([sec], "/repo", unity={"lock": "unity:repo", "held": True})
        self.assertIn("The hub took the repo's Unity lock `unity:repo` for you", held)
        self.assertIn("record what you saw", held)
        self.assertIn(sbqueue.PLAY_VERDICT, held)
        busy = sbqueue.review_brief([sec], "/repo", unity={"lock": "unity:repo", "held": False, "who": "chat-1"})
        self.assertIn("held by chat-1 for over ten minutes", busy)
        self.assertIn("`not played yet`, never `not met`", busy)
        self.assertNotIn("The hub took", busy)

    def test_a_review_with_no_in_play_line_reads_as_before(self):
        plain = sbqueue.review_brief([self.section([])], "/repo")
        self.assertNotIn("In Play", plain)
        self.assertNotIn("Unity", plain)
        self.assertIn("\nSay nothing along the way.", plain)
        self.assertNotIn("\n\n\n", plain)

    def test_not_played_lines_are_told_apart_from_not_met_ones(self):
        findings = ["- It works.: met", "- In Play: a dash: not played yet: busy", "- In Play: x: not met. Not played.",
                    "- Tests: not met"]
        self.assertEqual(sbqueue.not_played(findings), findings[1:3])


if __name__ == "__main__":
    unittest.main()
