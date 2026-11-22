"""Unity check lines (ticket 185): a `.sb/checks` line `unity: <command>` is sent into the Editor's own command queue
(`unity command --detach`, `unity job wait`) and takes no hub lock; `unity-session: <command>` takes the repo's Unity
lock for that one command and lets go right after. A job a recompile's reload dropped is sent once more, then is not
judged (the exit-75 path), never broken code. The fake `unity` (tests/fixtures/unity/fake_unity.py) replays Unity's
real output, recorded from the live Editor."""
import json
import os
import shlex
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_hub_runner import TEMPLATES, RunnerCase, git, state_fixture
import sbhub
import sbqueue
from sbhub import Hub, Supervisor, TicketRun

FAKE = Path(__file__).resolve().parent / "fixtures" / "unity" / "fake_unity.py"
DETACH = json.loads((FAKE.parent / "detach.json").read_text())


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


def fake_unity_on_path(folder):
    """A `unity` in `folder` that runs the fake; the folder is put first on PATH by the caller."""
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "unity"
    f.write_text("#!/bin/sh\nexec {} {} \"$@\"\n".format(shlex.quote(sys.executable), shlex.quote(str(FAKE))))
    f.chmod(0o755)


class Crash(BaseException):
    """The hub process dying mid-check (not an Exception, so nothing in the hub catches it)."""


class UnityLineTest(unittest.TestCase):
    """The line kinds on their own: TicketRun's runner against a real Hub's locks, the fake `unity` on PATH."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "game"
        self.repo.mkdir()
        fake_unity_on_path(self.root / "bin")
        self.hub = Hub(self.root / "hub")
        self.runner = TicketRun(self.hub, 4321)
        self.log = self.root / "unity.jsonl"
        env = mock.patch.dict(os.environ, PATH="{}:{}".format(self.root / "bin", os.environ["PATH"]),
                              FAKE_UNITY_LOG=str(self.log), FAKE_UNITY_STATE=str(self.root / "hub" / "state.json"))
        env.start()
        self.addCleanup(env.stop)
        for k in ("FAKE_UNITY_WAIT", "FAKE_UNITY_SLEEP", "FAKE_UNITY_DETACH"):
            os.environ.pop(k, None)
        patcher = mock.patch.multiple(sbhub, LAND_LOCK_POLL=0.05, LAND_LOCK_WAIT=30)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lock = "unity:game"
        self.landing = {"key": "game/map#7", "repo": str(self.repo), "before": "a" * 40, "sha": "b" * 40,
                        "tree": "", "branch": ""}
        self.recorded = []

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def check(self, *lines, landing=None):
        return self.runner.run_checks(list(lines), self.repo, sbhub._recording(self.recorded), "", landing)

    def test_the_line_kinds_are_after_landing_lines_and_keep_their_mark(self):
        lines = ["pnpm test", "after-landing: python3 c.py", "unity: sb_check", "unity-session: sb_compile --x 1"]
        self.assertEqual(sbqueue.before_landing(lines), ["pnpm test"])
        self.assertEqual(sbqueue.after_landing(lines), ["python3 c.py", "unity: sb_check", "unity-session: sb_compile --x 1"])
        self.assertIn("only the hub runs", sbqueue._run_checks(["unity: sb_check"], self.repo, None))

    def test_a_unity_line_queues_a_detached_job_and_passes_on_the_real_job_answer(self):
        self.assertIsNone(self.check("unity: editor_status"))
        send, wait = self.calls()
        self.assertEqual(send["argv"], ["command", "editor_status", "--detach", "--json", "--project-path", str(self.repo)])
        job = DETACH["data"]["jobId"][:-4] + "0001"
        self.assertEqual(wait["argv"], ["job", "wait", job, "--json", "--timeout", str(sbhub.UNITY_JOB_WAIT)])
        self.assertEqual([os.path.realpath(c["cwd"]) for c in (send, wait)], [os.path.realpath(self.repo)] * 2)
        self.assertEqual([c["code"] for c in self.recorded], [0, 0])  # both calls kept for the board
        self.assertEqual(self.hub.state()["locks"], {})

    def test_a_command_s_args_go_after_its_name(self):
        self.assertIsNone(self.check("unity: sb_check --since 'a b'"))
        self.assertEqual(self.calls()[0]["argv"][:4], ["command", "sb_check", "--since", "a b"])

    def test_a_unity_line_passes_while_another_holder_has_the_unity_lock(self):
        self.assertTrue(self.hub.lock(self.lock, "chat")["ok"])
        os.environ["FAKE_UNITY_SLEEP"] = "0.3"
        began = time.time()
        self.assertIsNone(self.check("unity: sb_check", landing=self.landing))
        self.assertLess(time.time() - began, 10)  # it never waited for the lock
        for c in self.calls():
            self.assertEqual(c["locks"][self.lock]["by"], "chat")  # the chat held it all along
        self.assertEqual(self.hub.state()["locks"][self.lock]["by"], "chat")

    def test_a_result_with_ok_false_fails_the_check_with_its_findings(self):
        os.environ["FAKE_UNITY_WAIT"] = "fail"
        failed = self.check("unity: sb_check")
        self.assertTrue(failed.startswith("check failed: unity: sb_check"))
        self.assertIn("missing script on Player", failed)
        self.assertEqual(sbhub._failed_cmd(failed), "unity: sb_check")

    def test_a_command_that_threw_fails(self):
        os.environ["FAKE_UNITY_WAIT"] = "error"
        failed = self.check("unity: sb_check")
        self.assertTrue(failed.startswith("check failed: unity: sb_check"))
        self.assertIn("NullReferenceException", failed)

    def test_an_editor_that_was_compiling_is_not_judged(self):
        os.environ["FAKE_UNITY_WAIT"] = "compiling"
        failed = self.check("unity: editor_status")
        self.assertTrue(failed.startswith(sbqueue.NOT_RUN), failed)
        self.assertIn("compiling", failed.splitlines()[0])

    def test_an_editor_that_is_not_running_is_not_judged(self):
        os.environ["FAKE_UNITY_DETACH"] = "down"
        failed = self.check("unity: sb_check")
        self.assertTrue(failed.startswith(sbqueue.NOT_RUN), failed)
        self.assertEqual(len(self.calls()), 1)  # nothing to wait for

    def test_a_lost_job_is_sent_once_more_and_passes_when_the_second_one_completes(self):
        os.environ["FAKE_UNITY_WAIT"] = "lost,ok"
        self.assertIsNone(self.check("unity: sb_check"))
        sends = [c for c in self.calls() if c["argv"][0] == "command"]
        self.assertEqual(len(sends), 2)

    def test_a_job_lost_twice_is_not_judged_never_broken_code(self):
        os.environ["FAKE_UNITY_WAIT"] = "lost"
        failed = self.check("unity: sb_check")
        self.assertTrue(failed.startswith(sbqueue.NOT_RUN), failed)
        self.assertIn(sbhub.UNITY_LOST, failed)
        self.assertEqual([c["argv"][:2] for c in self.calls()],
                         [["command", "sb_check"], ["job", "wait"], ["command", "sb_check"], ["job", "wait"]])
        self.assertEqual([c["code"] for c in self.recorded], [0, 6, 0, 6])  # Unity's own exit code for it

    def test_a_session_waits_for_the_lock_holds_it_only_while_its_command_runs_and_lets_go_when_it_fails(self):
        self.assertTrue(self.hub.lock(self.lock, "chat")["ok"])
        os.environ.update(FAKE_UNITY_WAIT="ok,fail", FAKE_UNITY_SLEEP="0.3")
        freed = []

        def unlock():
            freed.append(time.time())
            self.hub.unlock(self.lock, "chat")
        timer = threading.Timer(3.0, unlock)  # room for the lockless line to start under a loaded parallel run
        timer.start()
        self.addCleanup(timer.cancel)
        failed = self.check("unity: editor_status", "unity-session: sb_compile", "unity: sb_check",
                            landing=self.landing)
        self.assertTrue(failed.startswith("check failed: unity-session: sb_compile"), failed)
        first, first_wait, send, wait = self.calls()  # the lockless line, then the session; the last never ran
        self.assertEqual((first["argv"][1], send["argv"][1], wait["argv"][:2]),
                         ("editor_status", "sb_compile", ["job", "wait"]))
        self.assertLess(first_wait["at"], freed[0])  # the lockless line did not wait for the chat
        self.assertEqual(first_wait["locks"][self.lock]["by"], "chat")
        self.assertGreater(send["at"], freed[0])  # the session waited for the chat to let go
        for c in (send, wait):
            self.assertEqual(c["locks"][self.lock]["by"], "sb-hub landing game/map#7")
            self.assertEqual(c["locks"][self.lock]["landing"]["key"], "game/map#7")  # a restart can back it out
        self.assertEqual(self.hub.state()["locks"], {})  # let go, though it failed

    def test_a_session_inside_a_landing_that_holds_the_lock_keeps_it(self):
        self.assertTrue(self.hub.lock(self.lock, sbhub._landing_by(self.landing), landing=self.landing)["ok"])
        self.assertIsNone(self.check("unity-session: sb_compile", landing=self.landing))
        self.assertEqual(self.hub.state()["locks"][self.lock]["by"], "sb-hub landing game/map#7")

    def test_a_session_that_cannot_get_the_lock_is_not_judged(self):
        self.assertTrue(self.hub.lock(self.lock, "chat")["ok"])
        with mock.patch.object(sbhub, "LAND_LOCK_WAIT", 0.2):
            failed = self.check("unity-session: sb_compile", landing=self.landing)
        self.assertTrue(failed.startswith(sbqueue.NOT_RUN), failed)
        self.assertIn("held by chat", failed)
        self.assertEqual(self.calls(), [])

    def test_the_build_recheck_runs_a_unity_line_beside_a_chat_and_never_waits_for_a_session(self):
        self.assertTrue(self.hub.lock(self.lock, "chat")["ok"])
        self.assertTrue(self.runner.check_main(self.repo, {"cmd": "unity: sb_check", "after": True}, "c" * 40))
        began = time.time()
        self.assertIsNone(self.runner.check_main(self.repo, {"cmd": "unity-session: sb_compile", "after": True},
                                                 "c" * 40))  # the Editor is busy: not judged, at once
        self.assertLess(time.time() - began, 5)
        self.assertEqual(len(self.calls()), 2)  # only the unity: line reached Unity
        self.hub.unlock(self.lock, "chat")
        os.environ["FAKE_UNITY_WAIT"] = "fail"
        self.assertFalse(self.runner.check_main(self.repo, {"cmd": "unity-session: sb_compile", "after": True},
                                                "c" * 40))
        self.assertEqual(self.hub.state()["locks"], {})


CHECKS = """# a game's checks as the hub reads them: a recompile under the lock, then a read-only check in Unity's queue
unity-session: sb_compile
unity: sb_check
"""


class UnityLandingTest(RunnerCase):
    """The lines in a real landing: tickets made through sbmap, the repo's .sb/checks read by sbmap, the hub's own
    landing and state file, the fake worker. A repo without ProjectSettings has no Unity stage, so only the lines'
    own locking is at work."""
    MAPS = (("repo/one", "game", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "2")
        self.sb("mapset", "repo/one", "checks=")
        (self.repo / ".sb").mkdir()
        (self.repo / ".sb" / "checks").write_text(CHECKS)
        git(self.repo, "add", ".sb")
        git(self.repo, "commit", "-q", "-m", "checks")
        fake_unity_on_path(self.root / "bin")  # the harness's bin is first on PATH
        self.log, self.state = self.root / "unity.jsonl", self.root / "hub" / "state.json"
        env = mock.patch.dict(os.environ, FAKE_UNITY_LOG=str(self.log), FAKE_UNITY_STATE=str(self.state))
        env.start()
        self.addCleanup(env.stop)
        for k in ("FAKE_UNITY_WAIT", "FAKE_UNITY_SLEEP", "FAKE_UNITY_DETACH"):
            os.environ.pop(k, None)
        patcher = mock.patch.multiple(sbhub, LAND_LOCK_POLL=0.05, LAND_LOCK_WAIT=30)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lock = "unity:" + self.repo.name

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def restart(self):
        self.sup.procs.clear()  # this hub is gone: the next one finds only what it saved
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        self.hub, self.sup = hub, sup

    def test_sbmap_hands_the_hub_the_lines_with_their_marks(self):
        row = next(t for t in self.hub.tickets(fresh=True) if t["num"] == 1)
        self.assertEqual(row["checks"], ["unity-session: sb_compile", "unity: sb_check"])

    def test_it_lands_with_the_lock_held_only_for_the_session_line(self):
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        send, wait, check, check_wait = self.calls()
        self.assertEqual((send["argv"][1], check["argv"][1]), ("sb_compile", "sb_check"))
        for c in (send, wait):  # the recompile under the landing's lock
            self.assertEqual(c["locks"][self.lock]["by"], "sb-hub landing repo/one#1")
        for c in (check, check_wait):  # the read-only check with no lock at all
            self.assertEqual(c["locks"], {})
        self.assertEqual([os.path.realpath(c["cwd"]) for c in (send, check)], [os.path.realpath(self.repo)] * 2)
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD"), "")
        self.assertEqual(self.hub.state()["locks"], {})
        self.assertNotIn("checking", self.hub.state()["queue"])

    def test_a_lost_job_backs_the_landing_out_to_land_again_with_no_try_spent(self):
        os.environ["FAKE_UNITY_WAIT"] = "ok,lost,lost,ok"
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "recheck")
        item = self.items()["repo/one#1"]
        self.assertIn(sbqueue.NOT_RUN, item["note"])
        self.assertLessEqual(item.get("tries") or 0, 1)  # not a failed try: the code was not judged
        self.assertEqual(len(git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()), 1)
        self.assertEqual(self.hub.state()["locks"], {})

    def crash_in(self, kind):
        """Run ticket 1 until its `kind` line is in Unity, then the hub dies there: its state file as it was then."""
        snap = self.root / "state-at-crash.json"
        real = sbhub.unity_check

        def die(line, cwd, run=None, wait=None):
            if line.startswith(kind):
                shutil.copy(self.state, snap)
                raise Crash()
            return real(line, cwd, run, wait)
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        with mock.patch.object(sbhub, "unity_check", die):
            with self.assertRaises(Crash):
                self.until(lambda: False)
        shutil.copy(snap, self.state)  # a killed hub runs no `finally`: what it saved last is all there is
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD"), before)  # landed, unchecked
        return json.loads(self.state.read_text())

    def test_a_restart_during_a_unity_line_leaves_no_lock_and_the_landing_is_backed_out_and_lands_again(self):
        saved = self.crash_in(sbqueue.UNITY)
        self.assertEqual(saved["locks"], {})  # it never took one
        self.assertIn("repo/one#1", saved["queue"]["checking"])
        workers = len(self.launched)
        self.restart()
        state_fixture(self.hub.state(), self.root, "checking.json")  # the page must read a hub mid-check too
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(len(self.launched), workers)  # landed again without running its worker
        self.assertEqual(len(git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()), 1)
        self.assertEqual((self.repo / "one" / "done.txt").read_text().count("work for"), 1)
        self.assertEqual(self.hub.state()["locks"], {})
        self.assertNotIn("checking", self.hub.state()["queue"])

    def test_a_restart_during_a_session_line_is_cleared_by_the_after_landing_recovery(self):
        saved = self.crash_in(sbqueue.UNITY_SESSION)
        self.assertEqual(saved["locks"][self.lock]["landing"]["key"], "repo/one#1")  # the lock with its landing
        self.restart()
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(len(git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()), 1)
        self.assertEqual(self.hub.state()["locks"], {})
        self.assertNotIn("checking", self.hub.state()["queue"])


class UnityStageLinesTest(UnityLandingTest):
    """A Unity project (it has ProjectSettings): the integrator's stage keeps the lock as before; once it ends, the
    lock is let go for the `unity:` line and taken again for the session's one command."""
    MAPS = (("repo/one", "game", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.7.0b10\n")
        git(self.repo, "add", "ProjectSettings")
        git(self.repo, "commit", "-q", "-m", "a unity project")
        self.calls_of = self.root / "integrate.jsonl"
        env = mock.patch.dict(os.environ, FAKE_INTEGRATE_CALLS=str(self.calls_of), FAKE_COMPILE_STATE=str(self.state))
        env.start()
        self.addCleanup(env.stop)
        for k in ("FAKE_INTEGRATE", "FAKE_INTEGRATE_DIRTY", "FAKE_INTEGRATE_SLEEP"):
            os.environ.pop(k, None)
        patcher = mock.patch.multiple(sbhub, UNITY_POLL=0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_it_lands_with_the_lock_held_only_for_the_session_line(self):
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        [stage] = [json.loads(l) for l in self.calls_of.read_text().splitlines()]
        self.assertEqual(stage["locks"][self.lock]["by"], "sb-hub landing repo/one#1")  # the stage held it
        # the stage's own take of the lock asks Unity to drop unsaved scenes first (`command eval`, not a job)
        send, wait, check, check_wait = [c for c in self.calls() if c["argv"][:2] != ["command", "eval"]]
        self.assertGreaterEqual(send["at"], stage["end"])  # the lines ran once the integrator ended
        for c in (send, wait):
            self.assertEqual(c["locks"][self.lock]["by"], "sb-hub landing repo/one#1")
        for c in (check, check_wait):
            self.assertEqual(c["locks"], {})
        self.assertEqual(self.hub.state()["locks"], {})

    # the base class's other landing tests are its own; the stage's restarts are test_hub_unity_stage's
    test_a_lost_job_backs_the_landing_out_to_land_again_with_no_try_spent = None
    test_a_restart_during_a_unity_line_leaves_no_lock_and_the_landing_is_backed_out_and_lands_again = None
    test_a_restart_during_a_session_line_is_cleared_by_the_after_landing_recovery = None
    test_sbmap_hands_the_hub_the_lines_with_their_marks = None


if __name__ == "__main__":
    unittest.main()
