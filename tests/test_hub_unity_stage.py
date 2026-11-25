"""A Unity project's tickets end in a Unity stage: the worker codes in its own worktree and may not drive the Editor;
once its work lands in the main folder, an integrator runs there holding the repo's Unity lock, compiles and plays it,
fixes what is broken, and only then is the ticket judged. One ticket at a time: the others wait for the Editor with
no try spent. Same harness as test_hub_worktrees (tests/fake_worker.py is the worker and the integrator)."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_hub_runner import TEMPLATES, RunnerCase, git, go
from test_hub_worktrees import FAKE_COMPILE, SK4TE_CHECKS
import sbhub
from sbhub import Hub, Supervisor


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


class UnityStageTest(RunnerCase):
    MAPS = (("repo/one", "game", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "2")
        self.sb("mapset", "repo/one", "checks=")  # the repo's .sb/checks decides, as in sk4te
        (self.repo / ".sb").mkdir()
        (self.repo / ".sb" / "checks").write_text(SK4TE_CHECKS)
        (self.repo / ".sb" / "checks-compile.py").write_text(FAKE_COMPILE)
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.5.5f1\n")
        (self.repo / "Player.prefab").write_text("prefab\n")
        git(self.repo, "add", ".sb", "ProjectSettings", "Player.prefab")
        git(self.repo, "commit", "-q", "-m", "a unity project")
        self.log, self.calls = self.root / "compile.jsonl", self.root / "integrate.jsonl"
        env = mock.patch.dict(os.environ, FAKE_COMPILE_LOG=str(self.log), FAKE_INTEGRATE_CALLS=str(self.calls),
                              FAKE_COMPILE_STATE=str(self.root / "hub" / "state.json"))
        env.start()  # every FAKE_ variable as it was once the test ends
        self.addCleanup(env.stop)
        for k in ("FAKE_INTEGRATE", "FAKE_INTEGRATE_DIRTY", "FAKE_INTEGRATE_SLEEP", "FAKE_COMPILE"):
            os.environ.pop(k, None)
        patcher = mock.patch.multiple(sbhub, LAND_LOCK_POLL=0.05, LAND_LOCK_WAIT=30, UNITY_POLL=0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.lock = "unity:" + self.repo.name

    def stages(self):
        return [json.loads(l) for l in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def compiles(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def workers(self):
        return [l for l in self.launched if not l["brief"].startswith("# Bring ")]

    def test_the_worker_is_fenced_off_unity_and_the_integrator_plays_it_on_main_holding_the_lock(self):
        os.environ["FAKE_INTEGRATE_DIRTY"] = "Player.prefab"
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "done")
        [worker] = self.workers()
        self.assertIn("## Unity is the last stage, not yours", worker["brief"])
        self.assertIn('"SB_HUB_UNITY": "off"', Path(worker["log"]).read_text())
        self.assertIn("/worktrees/", Path(worker["log"]).read_text())  # it worked in its own worktree
        [stage] = self.stages()
        self.assertEqual(os.path.realpath(stage["cwd"]), os.path.realpath(self.repo))  # the main folder
        self.assertEqual(stage["unity"], "integrator")
        self.assertEqual(stage["locks"][self.lock]["by"], "sb-hub landing repo/one#1")  # it held the Editor
        [ran] = self.compiles()
        self.assertGreaterEqual(ran["at"], stage["end"])  # the compile ran after the integrator, with its fix in
        self.assertEqual(ran["head"], git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(git(self.repo, "log", "--format=%s", before + "..HEAD").splitlines(),
                         ["fix(integrate): it builds", "feat: work"])
        self.assertEqual(self.hub.state()["locks"], {})
        self.assertEqual((self.repo / "Player.prefab").read_text(), "prefab\n")  # Unity's own write restored
        folder = Path(self.items()["repo/one#1"]["run"])
        self.assertIn("written by Unity during Play", (folder / "1-unity-leftovers.patch").read_text())
        self.assertNotIn("integrate", self.items()["repo/one#1"])
        self.assertNotIn(1, self.open_tickets())

    def test_an_integrator_that_cannot_make_it_work_backs_the_whole_stage_out_and_the_worker_tries_again(self):
        os.environ["FAKE_INTEGRATE"] = "broken"
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: len(self.workers()) == 2)
        self.assertEqual(git(self.repo, "diff", before, "HEAD"), "")  # main's files as before the landing
        retry = self.workers()[1]["brief"]
        self.assertIn("the integrator could not make it work in Unity", retry)
        self.assertIn("1-integrate.md", retry)  # told to read the integrator's report
        self.assertEqual(self.compiles(), [])  # nothing compiled a stage the integrator called broken
        self.until(lambda: self.hub.state()["locks"] == {})

    def test_the_first_unity_stage_runs_on_sonnet_and_the_stage_after_a_failed_one_on_opus(self):
        os.environ["FAKE_INTEGRATE"] = "broken"
        self.only(1)
        self.until(lambda: len(self.workers()) == 2)
        os.environ["FAKE_INTEGRATE"] = "works"
        self.until(lambda: self.state_of("repo/one#1") == "done")
        integrators = [l["model"] for l in self.launched if l["brief"].startswith("# Bring ")]
        self.assertEqual(integrators, ["sonnet", "opus"])
        self.assertEqual([w["model"] for w in self.workers()], ["sonnet", "sonnet"])  # the worker's own tier stays

    def chat_commit(self):
        """Someone else's commit on main while a Unity stage holds the Editor (sk4te 2026-11-17 18:38: a chat
        session's tools/play and pen fix)."""
        (self.repo / "chat.txt").write_text("a chat session's work\n")
        git(self.repo, "add", "chat.txt")
        git(self.repo, "commit", "-q", "-m", "fix(tools): a chat session's own fix")
        return git(self.repo, "rev-parse", "HEAD")

    def back_out(self):
        [sha] = git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()
        return sha

    def test_a_back_out_undoes_only_the_ticket_and_its_integrator_never_a_commit_made_meanwhile(self):
        os.environ.update(FAKE_INTEGRATE="tried", FAKE_INTEGRATE_SLEEP="1.5")
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: self.items()["repo/one#1"].get("integrate"))
        # the landing is main's first commit after before: HEAD is already the integrator's fix on a busy machine
        landed = git(self.repo, "rev-list", "--first-parent", "--reverse", before + "..HEAD").split()[0]
        chat = self.chat_commit()
        self.until(lambda: len(self.workers()) == 2)
        revert = self.back_out()
        self.assertEqual(git(self.repo, "diff", "--name-only", revert + "^", revert).split(),
                         ["fix.txt", "one/done.txt"])  # the ticket's file and the integrator's, nothing else
        self.assertEqual(git(self.repo, "show", "HEAD:chat.txt"), "a chat session's work")
        fix = git(self.repo, "log", "--format=%H", "--grep=^fix(integrate)", before + "..HEAD").split()
        undoes = [l.split()[1] for l in git(self.repo, "log", "-1", "--format=%B", revert).splitlines()
                  if l.startswith("Undoes: ")]
        self.assertEqual(sorted(undoes), sorted(fix + [landed]))
        self.assertNotIn(chat, undoes)

    def test_a_restart_backs_out_only_the_stage_and_keeps_a_commit_made_meanwhile(self):
        os.environ["FAKE_INTEGRATE_SLEEP"] = "30"
        self.only(1)
        self.until(lambda: self.items()["repo/one#1"].get("integrate"))
        run = self.sup.procs.pop("repo/one#1")
        sbhub._kill_group(run["p"], grace=0)  # the integrator dies with its hub
        chat = self.chat_commit()
        os.environ["FAKE_INTEGRATE_SLEEP"] = "0"
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        self.hub, self.sup = hub, sup
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertNotIn("chat.txt", git(self.repo, "diff", "--name-only", self.back_out() + "^", self.back_out()))
        self.assertEqual(git(self.repo, "show", "HEAD:chat.txt"), "a chat session's work")
        self.assertEqual(git(self.repo, "merge-base", "--is-ancestor", chat, "HEAD"), "")

    def test_a_second_ticket_waits_for_the_editor_with_no_try_spent_and_the_stages_never_overlap(self):
        os.environ["FAKE_INTEGRATE_SLEEP"] = "1.5"
        self.only(1, 2)
        self.until(lambda: self.state_of("repo/one#1") == "done" and self.state_of("repo/one#2") == "done",
                   timeout=240)
        a, b = sorted(self.stages(), key=lambda s: s["start"])
        self.assertGreaterEqual(b["start"], a["end"])  # one Unity stage at a time
        self.assertEqual(len(self.workers()), 2)  # each worker ran once: waiting was no try
        for key in ("repo/one#1", "repo/one#2"):
            self.assertLessEqual(self.items()[key].get("tries") or 0, 1)
        self.assertEqual(self.hub.state()["locks"], {})

    def test_a_hub_restart_during_a_stage_whose_integrator_died_backs_it_out_and_lands_it_again(self):
        os.environ["FAKE_INTEGRATE_SLEEP"] = "30"
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1)
        self.until(lambda: self.items()["repo/one#1"].get("integrate"))
        run = self.sup.procs.pop("repo/one#1")
        sbhub._kill_group(run["p"], grace=0)  # the integrator dies with its hub
        self.assertNotEqual(git(self.repo, "rev-parse", "HEAD"), before)
        os.environ["FAKE_INTEGRATE_SLEEP"] = "0"
        hub = Hub(self.root / "hub", now=self.clock, launcher=self.launcher)
        sup = Supervisor(hub)
        sup.close_off = False
        self.addCleanup(sup.stop)
        self.hub, self.sup = hub, sup
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual(len(self.workers()), 1)  # landed again without running its worker
        self.assertEqual(len(self.launched) - len(self.workers()), 2)  # a second integrator, to the end
        self.assertEqual(len(git(self.repo, "log", "--format=%H", "--grep=Undoes-landing:", "HEAD").split()), 1)
        self.assertEqual(hub.state()["locks"], {})


    def failed_in_main(self):
        """Ticket 1 landed and played, then judged partly by its review twice (as party-playtest's were): failed,
        open again, its work in main."""
        self.verdicts["repo/one#1"] = "partly"
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "failed", timeout=180)
        self.assertIn(1, self.open_tickets())
        return git(self.repo, "rev-parse", "HEAD")

    def test_a_unity_pass_plays_a_failed_ticket_on_main_with_no_worker_and_it_lands(self):
        before = self.failed_in_main()
        workers, stages = len(self.workers()), len(self.stages())
        self.verdicts["repo/one#1"] = "finished"  # the review judges it again after the pass, met this time
        self.hub.queue_integrate(["repo/one#1"])
        go(self.hub)
        self.until(lambda: len(self.stages()) == stages + 1 and self.state_of("repo/one#1") == "done")
        self.assertEqual(len(self.workers()), workers)  # no worker ran
        brief = self.launched[-1]["brief"]
        self.assertIn("Its work landed earlier", brief)
        stage = self.stages()[-1]
        self.assertEqual(stage["locks"][self.lock]["by"], "sb-hub landing repo/one#1")
        self.assertEqual(git(self.repo, "log", "--format=%s", before + "..HEAD"), "fix(integrate): it builds")
        self.assertEqual(self.hub.state()["locks"], {})
        self.assertNotIn("integrate_only", self.items()["repo/one#1"])
        self.assertNotIn(1, self.open_tickets())  # resolved by the review after the pass

    def test_a_unity_pass_that_cannot_fix_it_undoes_its_fixes_and_goes_back_to_the_owner(self):
        before = self.failed_in_main()
        workers, stages = len(self.workers()), len(self.stages())
        os.environ["FAKE_INTEGRATE"] = "broken"
        self.hub.queue_integrate(["repo/one#1"])
        go(self.hub)
        self.until(lambda: len(self.stages()) == stages + 1 and self.state_of("repo/one#1") == "failed")
        self.assertEqual(len(self.workers()), workers)
        self.assertIn("the Unity pass: the integrator could not make it work", self.items()["repo/one#1"]["note"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), before)  # nothing to undo: no empty revert either
        self.assertEqual(self.hub.state()["locks"], {})

    def test_only_a_failed_unity_ticket_can_be_queued_for_a_pass(self):
        with self.assertRaises(ValueError):
            self.hub.queue_integrate(["repo/one#2"])

    def test_a_refused_pass_changes_none_of_the_tickets_it_named(self):
        self.failed_in_main()
        with self.assertRaises(ValueError):
            self.hub.queue_integrate(["repo/one#1", "repo/one#2"])  # 2 never ran
        self.assertEqual(self.state_of("repo/one#1"), "failed")
        self.assertFalse(any(i.get("integrate_only") for i in self.hub._data["queue"]["items"]))


class GuardTest(unittest.TestCase):
    def test_a_unity_worker_may_not_run_the_unity_cli_and_others_may(self):
        sys.path.insert(0, str(Path(sbhub.__file__).resolve().parents[1] / "hooks"))
        import guard_git
        off = {"SB_HUB_UNITY": "off"}
        for line in ("unity command recompile", "~/.unity/bin/unity status --json", "cd x && unity command eval 'a'",
                     "/Applications/Unity/Hub/Editor/6000.5.5f1/Unity.app/Contents/MacOS/Unity -batchmode"):
            self.assertIn("Unity is the ticket's last stage", guard_git.refusal(line, ".", main=lambda d: False, env=off))
        self.assertIsNone(guard_git.refusal("grep -rn unity Assets", ".", main=lambda d: False, env=off))
        for env in ({}, {"SB_HUB_UNITY": "integrator"}):
            self.assertIsNone(guard_git.refusal("unity command recompile", ".", main=lambda d: False, env=env))
