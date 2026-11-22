"""A finished ticket goes to the chat that queued it (ticket 172): with a chat joined to the run, a worktree ticket whose
checks pass is handed to that chat, rebased on its branch but not landed; the chat lands it or sends it back. Board-
queued tickets go to the free-est joined integrator; with none joined the hub lands and reviews as before. Same
harness as test_hub_worktrees: Supervisor.tick() by hand, a temp vault, temp repos and tests/fake_worker.py."""
import unittest

from test_hub_runner import TEMPLATES, RunnerCase, git, go
import sbhub
from sbhub import _handed_to, handed_lines


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


class IntegratorTest(RunnerCase):
    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "3")

    def queue(self, *nums, by=None):
        self.hub.queue_set(["repo/one#{}".format(n) for n in nums], self.hub.state()["queue"]["version"], agent=by)

    def handed(self, key):
        return self.state_of(key) == "handed"

    def test_a_finished_ticket_waits_for_the_chat_that_queued_it_and_lands_when_it_asks(self):
        self.queue(1, by="chat-a")
        go(self.hub)
        self.hub.join("chat-a", "implementer")  # any joined chat gets what it queued, whatever its role
        self.until(lambda: self.handed("repo/one#1"))
        item = self.items()["repo/one#1"]
        self.assertEqual((item["by"], item["handed"]["to"]), ("chat-a", "chat-a"))
        self.assertFalse((self.repo / "one" / "done.txt").exists())  # nothing landed yet
        self.assertIn(item["branch"], git(self.repo, "branch", "--list", "sb/*"))
        me, joined, waiting = _handed_to(self.hub.state(), "chat-a")
        self.assertEqual((me, joined, [i["key"] for i in waiting]), ("chat-a", True, ["repo/one#1"]))
        self.assertIn("sbhub.py integrate repo/one#1 land --agent chat-a", "\n".join(handed_lines(me, waiting)))
        with self.assertRaises(ValueError):
            self.hub.integrate("repo/one#1", "chat-b", "land")  # handed to another chat
        with self.assertRaises(ValueError):
            self.hub.integrate("repo/one#1", "chat-a", "back")  # sent back with no word why
        self.hub.integrate("repo/one#1", "chat-a", "land", "reads well")
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertTrue((self.repo / "one" / "done.txt").exists())
        self.assertNotIn(1, self.open_tickets())  # resolved as the chat's review: no Opus review runs
        item = self.items()["repo/one#1"]
        self.assertNotIn("handed", item)
        self.assertNotIn(sbhub.landing_lock(self.repo), self.hub.state()["locks"])
        self.assertEqual(_handed_to(self.hub.state(), "chat-a")[2], [])

    def test_a_ticket_sent_back_is_built_again_told_the_chats_note(self):
        self.queue(1, by="chat-a")
        go(self.hub)
        self.hub.join("chat-a", "integrator")
        self.until(lambda: self.handed("repo/one#1"))
        self.hub.integrate("repo/one#1", "chat-a", "back", "name the file after the ticket")
        self.until(lambda: len(self.launched) >= 2 and self.handed("repo/one#1"))
        self.assertIn("name the file after the ticket", self.launched[-1]["brief"])
        self.assertEqual(self.items()["repo/one#1"]["tries"], 1)

    def test_board_queued_tickets_go_to_the_free_est_integrator(self):
        self.queue(1, 2)  # from the board: nobody queued them
        go(self.hub)
        self.hub.join("int-1", "integrator")
        self.hub.join("int-2", "integrator")
        self.hub.join("builder", "implementer")  # an implementer gets only what it queued
        self.until(lambda: self.handed("repo/one#1") and self.handed("repo/one#2"))
        to = sorted(self.items()["repo/one#{}".format(n)]["handed"]["to"] for n in (1, 2))
        self.assertEqual(to, ["int-1", "int-2"])

    def test_with_no_chat_joined_the_hub_lands_it_as_before(self):
        self.queue(1, by="chat-a")  # it queued it, but never joined
        go(self.hub)
        self.until(lambda: self.state_of("repo/one#1") in ("landed", "review", "done"))
        self.assertTrue((self.repo / "one" / "done.txt").exists())

    def test_a_chat_that_leaves_hands_its_tickets_on_or_the_hub_lands_them(self):
        self.queue(1, by="chat-a")
        go(self.hub)
        self.hub.join("chat-a", "integrator")
        self.until(lambda: self.handed("repo/one#1"))
        self.hub.join("chat-b", "integrator")
        self.hub.leave("chat-a")
        self.assertEqual(self.items()["repo/one#1"]["handed"]["to"], "chat-b")
        self.hub.leave("chat-b")  # nobody is left: the hub lands it its own way
        self.until(lambda: self.state_of("repo/one#1") in ("landed", "review", "done"))
        self.assertTrue((self.repo / "one" / "done.txt").exists())

    def test_a_landing_waits_while_someone_holds_the_repos_landing_lock(self):
        self.queue(1, by="chat-a")
        go(self.hub)
        self.hub.join("chat-a", "integrator")
        self.until(lambda: self.handed("repo/one#1"))
        lock = sbhub.landing_lock(self.repo)
        self.assertTrue(self.hub.lock(lock, "chat-b")["ok"])  # another integrator lands by hand
        self.hub.integrate("repo/one#1", "chat-a", "land")
        for _ in range(3):
            self.sup.tick()
        self.assertTrue(self.handed("repo/one#1"))
        self.assertFalse((self.repo / "one" / "done.txt").exists())
        self.hub.unlock(lock, "chat-b")
        self.until(lambda: self.state_of("repo/one#1") == "done")



class TwoMapsTest(RunnerCase):
    """Two maps of one repo, in turn: what the first map's hand-off holds back, and how a dead chat lets go."""
    MAPS = (("repo/one", "repoA", ("A", "one/")),
            ("repo/two", "repoT", ("C", "three/")))

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "3")
        m = next(self.vault.glob("wayfinder/repo/two/map.md"))  # the second map works in the first map's repo
        m.write_text(m.read_text(encoding="utf-8").replace(str(self.repos["repo/two"]), str(self.repo)),
                     encoding="utf-8")
        self.hub.tickets()

    def queue(self, *keys, by=None):
        self.hub.queue_set(list(keys), self.hub.state()["queue"]["version"], agent=by)

    def one_handed(self, to="chat-a"):
        """repo/one#1 handed to `to`, repo/two#2 queued behind its map."""
        self.queue("repo/one#1", "repo/two#2", by=to)
        go(self.hub)
        self.hub.join(to, "integrator")
        self.until(lambda: self.state_of("repo/one#1") == "handed")

    def test_a_ticket_waiting_its_maps_turn_names_the_map_and_what_holds_it(self):
        self.one_handed()
        for _ in range(3):
            self.sup.tick()
        self.assertEqual(self.state_of("repo/two#2"), "queued")
        self.assertEqual(self.items()["repo/two#2"]["note"], "waits: one first (1 handed to chat-a)")
        self.hub.integrate("repo/one#1", "chat-a", "land")
        self.until(lambda: self.state_of("repo/two#2") not in ("queued",))
        self.assertFalse(self.items()["repo/two#2"]["note"].startswith("waits: "))

    def test_the_map_note_names_a_sessions_id_short_and_counts_what_it_does_not_show(self):
        items = [{"key": "r/a#{}".format(n), "kind": "ticket", "state": s, "handed": {"to": to}}
                 for n, s, to in ((1, "queued", None), (2, "handed", "25108735-1a2b-4c3d-8e9f-001122334455"),
                                  (3, "running", None), (4, "unclean", None), (5, "queued", None), (6, "done", None))]
        self.assertEqual(sbhub.map_wait_note(items, "/r", "r/a", lambda i: "/r"),
                         "waits: a first (2 handed to 25108735…, 4 waiting for a clean checkout, 3 running, "
                         "1 queued, 1 more)")


    def test_a_chat_that_ended_lets_go_at_once_and_the_hub_lands_it_so_the_next_map_starts(self):
        self.one_handed()
        self.hub.report({"agent": "chat-a", "state": "gone"})  # its session ended, never to come back
        self.until(lambda: self.state_of("repo/one#1") in ("landed", "review", "done"))
        self.assertTrue((self.repo / "one" / "done.txt").exists())
        self.until(lambda: self.state_of("repo/two#2") != "queued")  # its map's turn came
        self.assertEqual(self.items()["repo/one#1"]["orphaned_from"], ["chat-a"])

    def test_a_quiet_chat_keeps_it_30_minutes_then_it_goes_to_another_integrator_then_to_the_hub(self):
        self.one_handed()
        self.hub.join("chat-b", "integrator")
        self.clock.t += 20 * 60
        self.hub.report({"agent": "chat-a", "state": "working", "note": "reading the diff"})
        self.clock.t += 20 * 60  # 40 min since the hand-off, 20 since it last spoke: still its
        self.sup.tick()
        self.assertEqual(self.items()["repo/one#1"]["handed"]["to"], "chat-a")
        self.clock.t += 11 * 60
        self.hub.report({"agent": "chat-b", "state": "working"})
        self.sup.tick()
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["handed"]["to"]), ("handed", "chat-b"))
        self.assertEqual(item["note"], "chat-a has said nothing for 31 min; waits for chat-b to review and land it")
        self.clock.t += 31 * 60  # chat-b lets it lie too; chat-a is never handed it again
        self.hub.report({"agent": "chat-a", "state": "working"})
        self.sup.tick()
        item = self.items()["repo/one#1"]
        self.assertEqual(item["orphaned_from"], ["chat-a", "chat-b"])
        self.assertTrue(item["note"].startswith("chat-b has said nothing for 31 min and no other integrator is joined"),
                        item["note"])
        self.until(lambda: self.state_of("repo/one#1") in ("landed", "review", "done"))
        self.assertTrue((self.repo / "one" / "done.txt").exists())


    def test_a_joined_integrator_or_the_owner_lands_what_a_gone_chat_held_and_a_quiet_one_is_waited_for(self):
        self.one_handed()
        self.hub.join("chat-b", "integrator")
        self.hub.join("builder", "implementer")
        with self.assertRaisesRegex(ValueError, "chat-a still looks after it"):
            self.hub.integrate("repo/one#1", "chat-b", "land")  # chat-a is alive: it is still chat-a's
        with self.hub._lock:  # chat-a's session ended between two ticks of the hub
            self.hub._remove("chat-a")
        with self.assertRaisesRegex(ValueError, "only a joined integrator or the owner"):
            self.hub.integrate("repo/one#1", "builder", "land")  # an implementer does not stand in
        self.hub.integrate("repo/one#1", "chat-b", "land", "reads well")
        item = self.items()["repo/one#1"]
        self.assertEqual((item["handed"]["to"], item["handed"]["from"], item["orphaned_from"]),
                         ("chat-b", "chat-a", ["chat-a"]))
        self.assertEqual(item["note"], "chat-a is not in the run; chat-b asked to land it")
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertTrue((self.repo / "one" / "done.txt").exists())

    def test_the_owner_sends_back_what_a_gone_chat_held(self):
        self.one_handed()
        with self.hub._lock:
            self.hub._remove("chat-a")
        self.hub.integrate("repo/one#1", sbhub.OWNER, "back", "name the file after the ticket")
        self.until(lambda: len(self.launched) >= 2)
        self.assertIn("sent back by owner: name the file after the ticket", self.launched[-1]["brief"])

    def test_leaving_as_a_chat_that_never_joined_still_lets_go_of_what_was_handed_to_it(self):
        self.one_handed()
        with self.hub._lock:  # as on 2026-11-20: its row is gone, the hand-off is still in its name
            self.hub._remove("chat-a")
        self.hub.join("chat-b", "integrator")
        self.hub.leave("chat-a")
        self.assertEqual(self.items()["repo/one#1"]["handed"]["to"], "chat-b")
        with self.assertRaisesRegex(ValueError, "not joined the run and nothing is handed to it"):
            self.hub.leave("chat-a")  # nothing is left in its name


if __name__ == "__main__":
    unittest.main()
