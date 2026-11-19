"""A joined chat takes a queued ticket and builds it itself (ticket 173): the ticket gets its own worktree and branch
(never the repo's main folder, ticket 133) and the hub's claim, no worker starts for it, and `done` runs its checks
and hands it on as a worker's would be. Same harness as test_hub_integrator: Supervisor.tick() by hand, a temp vault,
temp repos and tests/fake_worker.py."""
import re
import subprocess
import unittest
from pathlib import Path

from test_hub_runner import TEMPLATES, RunnerCase, git
import sbhub
from sbhub import _sent_back, back_lines


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


class ChatTakeTest(RunnerCase):
    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]

    def start(self, *nums):
        self.hub.queue_set(["repo/one#{}".format(n) for n in nums], self.hub.state()["queue"]["version"])
        self.hub.night_start(drain=True)  # no tick yet: no worker has started

    def build(self, got):
        """What a chat does in the ticket's worktree: a commit inside its paths, with its Ticket trailer."""
        ticket = re.search(r"^\s*Ticket: (\S+)\s*$", got["brief"], re.M).group(1)
        f = Path(got["tree"]) / "one" / "done.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("built by a chat\n")
        git(got["tree"], "add", "one/done.txt")
        subprocess.run(["git", "-C", got["tree"], "commit", "-q", "-m", "feat: built\n\nTicket: " + ticket], check=True)

    def test_a_chat_takes_a_ticket_in_its_own_worktree_and_no_worker_runs_it(self):
        self.start(1)
        self.hub.join("chat-a", "implementer")
        with self.assertRaises(ValueError):
            self.hub.take_ticket("chat-b", "repo/one#1")  # not joined
        got = self.hub.take_ticket("chat-a", "repo/one#1")
        self.assertTrue(Path(got["tree"]).is_dir())
        self.assertNotEqual(Path(got["tree"]).resolve(), Path(self.repo).resolve())  # never the main folder
        self.assertIn(got["branch"], git(self.repo, "branch", "--list", "sb/*"))
        self.assertIn("Files you own:", got["brief"])
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["runner"], item["agent"]), ("running", sbhub.CHAT_RUNNER, "chat-a"))
        self.assertTrue(self.open_tickets()[1]["claimed_by"].startswith("hub chat chat-a"))
        for _ in range(3):
            self.sup.tick()
        self.assertEqual(self.launched, [])  # no worker for it, and it is not taken for lost
        self.assertEqual(self.state_of("repo/one#1"), "running")
        self.hub.join("chat-b", "implementer")
        with self.assertRaisesRegex(ValueError, "already runs: chat chat-a builds it"):
            self.hub.take_ticket("chat-b", "repo/one#1")
        with self.assertRaises(ValueError):
            self.hub.ticket_done("chat-b", "repo/one#1")  # taken by another chat
        self.build(got)
        self.hub.ticket_done("chat-a", "repo/one#1", "built it")
        # no integrator joined: it lands the hub's way, and its map's review judges it
        self.until(lambda: self.state_of("repo/one#1") in ("landed", "review", "done"))
        self.assertTrue((self.repo / "one" / "done.txt").exists())
        item = self.items()["repo/one#1"]
        self.assertEqual(item["runner"], "chat chat-a")
        self.assertNotIn("done_ask", item)
        self.assertEqual(self.launched, [])

    def test_a_ticket_a_worker_runs_cannot_be_taken(self):
        self.modes["repo/one#1"] = "slow"
        self.start(1)
        self.until(lambda: self.state_of("repo/one#1") == "running")
        self.hub.join("chat-a", "implementer")
        with self.assertRaisesRegex(ValueError, "already runs: a worker on"):
            self.hub.take_ticket("chat-a", "repo/one#1")

    def test_with_an_integrator_joined_the_chats_ticket_is_handed_to_it(self):
        self.start(1)
        self.hub.join("chat-a", "implementer")
        self.hub.join("int-1", "integrator")
        got = self.hub.take_ticket("chat-a", "repo/one#1")
        self.build(got)
        self.hub.ticket_done("chat-a", "repo/one#1")
        self.until(lambda: self.state_of("repo/one#1") == "handed")
        item = self.items()["repo/one#1"]
        self.assertEqual(item["handed"]["to"], "int-1")
        self.assertIn("built by chat-a", item["note"])
        self.assertFalse((self.repo / "one" / "done.txt").exists())  # the integrator lands it

    def test_failing_checks_send_it_back_to_the_chat_with_no_try_spent(self):
        self.start(1)
        self.hub.join("chat-a", "implementer")
        self.hub.take_ticket("chat-a", "repo/one#1")
        self.assertEqual(_sent_back(self.hub.state(), "chat-a"), {})
        self.hub.ticket_done("chat-a", "repo/one#1")  # nothing committed
        self.until(lambda: "chat_back" in self.items()["repo/one#1"])
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["runner"], item["tries"]), ("running", sbhub.CHAT_RUNNER, 0))
        self.assertNotIn("done_ask", item)
        self.assertIn("repo/one#1", _sent_back(self.hub.state(), "chat-a"))
        self.assertIn("sbhub.py done repo/one#1 --agent chat-a", "\n".join(back_lines("chat-a", [item])))
        self.assertEqual(self.launched, [])

    def test_a_chat_that_leaves_gives_its_ticket_back_and_a_worker_goes_on_from_its_work(self):
        self.start(1)
        self.hub.join("chat-a", "implementer")
        got = self.hub.take_ticket("chat-a", "repo/one#1")
        self.hub.leave("chat-a")
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item.get("from_chat")), ("queued", True))
        self.assertEqual(self.open_tickets()[1]["status"], "open")  # the chat's claim is let go
        self.until(lambda: any(x["key"] == "repo/one#1" for x in self.launched))
        self.assertEqual(self.items()["repo/one#1"]["tree"], got["tree"])  # the worker goes on in the chat's worktree
        self.until(lambda: self.state_of("repo/one#1") in ("landed", "review", "done"))

    def test_the_owners_stop_ends_a_chats_ticket_and_lets_its_claim_go(self):
        self.start(1)
        self.hub.join("chat-a", "implementer")
        self.hub.take_ticket("chat-a", "repo/one#1")
        self.hub.queue_stop("repo/one#1", "not tonight", self.hub.state()["queue"]["version"])
        self.until(lambda: self.state_of("repo/one#1") == "skipped")
        self.assertIn("stopped by you: not tonight", self.items()["repo/one#1"]["note"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")


if __name__ == "__main__":
    unittest.main()
