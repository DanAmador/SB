"""When Unity stops answering (ticket 189): an integrator that ended `no unity`, or a Unity check line that was not
judged, makes the hub ask editor_status itself. While the Editor does not answer, nothing lands and no integrator
starts in that repo, its tickets say 'waits for Unity: not answering since HH:MM' with no try spent, the owner is
told once, and the hub carries on by itself once editor_status answers. The fake `unity` replays the real CLI's
answers: editor_status.json from the live Editor, editor_not_running.json from the CLI with no Editor open."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_hub_runner import TEMPLATES, RunnerCase, git, go
from test_hub_unity_checks import fake_unity_on_path
from test_hub_worktrees import FAKE_COMPILE, SK4TE_CHECKS
import sbhub
import sbqueue


def tearDownModule():
    for t in TEMPLATES.values():
        t.cleanup()
    TEMPLATES.clear()


class EditorAnswersTest(unittest.TestCase):
    """editor_answers and unity_unjudged on what the real producers print."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "game"
        self.repo.mkdir()
        fake_unity_on_path(self.root / "bin")
        env = mock.patch.dict(os.environ, PATH="{}:{}".format(self.root / "bin", os.environ["PATH"]),
                              FAKE_UNITY_LOG=str(self.root / "unity.jsonl"),
                              FAKE_UNITY_STATE=str(self.root / "none.json"))
        env.start()
        self.addCleanup(env.stop)
        for k in ("FAKE_UNITY_STATUS", "FAKE_UNITY_DETACH", "FAKE_UNITY_WAIT"):
            os.environ.pop(k, None)

    def test_a_live_editor_answers_and_one_no_editor_has_open_does_not(self):
        self.assertEqual(sbhub.editor_answers(self.repo), "")
        os.environ["FAKE_UNITY_STATUS"] = "down"
        why = sbhub.editor_answers(self.repo)
        self.assertIn("No Pipeline instance found for project", why)  # the real CLI's EDITOR_NOT_RUNNING words
        [call] = [json.loads(l) for l in (self.root / "unity.jsonl").read_text().splitlines()][-1:]
        self.assertEqual(call["argv"][:2], ["command", "editor_status"])
        self.assertIn(str(self.repo), call["argv"])
        self.assertNotIn("--detach", call["argv"])

    def test_a_frozen_editor_that_never_answers_counts_as_not_answering(self):
        def hang(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        self.assertIn("did not answer", sbhub.editor_answers(self.repo, run=hang))

    def test_a_unity_line_the_editor_did_not_take_is_unjudged_and_a_failed_one_is_not(self):
        os.environ["FAKE_UNITY_DETACH"] = "down"
        note = sbhub.unity_check("unity: sb_check", self.repo)  # what the hub's own check runner writes
        self.assertTrue(note.startswith(sbqueue.NOT_RUN), note)
        self.assertTrue(sbhub.unity_unjudged("after landing, " + note))
        os.environ.pop("FAKE_UNITY_DETACH")
        os.environ["FAKE_UNITY_WAIT"] = "fail"
        failed = sbhub.unity_check("unity: sb_check", self.repo)
        self.assertTrue(failed.startswith("check failed"), failed)
        self.assertFalse(sbhub.unity_unjudged(failed))  # a real finding is broken code, not a missing Editor
        self.assertFalse(sbhub.unity_unjudged(sbqueue.NOT_RUN + ": python3 .sb/checks-compile.py"))  # a shell line
        self.assertTrue(sbhub.unity_unjudged(sbhub.NO_UNITY + "; backed out, it lands again"))


class UnityDownTest(RunnerCase):
    MAPS = (("repo/one", "game", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        git(self.repo, "config", "sb.parallel", "2")
        self.sb("mapset", "repo/one", "checks=")
        (self.repo / ".sb").mkdir()
        (self.repo / ".sb" / "checks").write_text(SK4TE_CHECKS)
        (self.repo / ".sb" / "checks-compile.py").write_text(FAKE_COMPILE)
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.5.5f1\n")
        git(self.repo, "add", ".sb", "ProjectSettings")
        git(self.repo, "commit", "-q", "-m", "a unity project")
        fake_unity_on_path(self.root / "bin")
        self.log, self.calls = self.root / "compile.jsonl", self.root / "integrate.jsonl"
        self.ulog = self.root / "unity.jsonl"
        env = mock.patch.dict(os.environ, FAKE_COMPILE_LOG=str(self.log), FAKE_INTEGRATE_CALLS=str(self.calls),
                              FAKE_COMPILE_STATE=str(self.root / "hub" / "state.json"),
                              PATH="{}:{}".format(self.root / "bin", os.environ["PATH"]),
                              FAKE_UNITY_LOG=str(self.ulog), FAKE_UNITY_STATE=str(self.root / "hub" / "state.json"))
        env.start()
        self.addCleanup(env.stop)
        for k in ("FAKE_INTEGRATE", "FAKE_INTEGRATE_DIRTY", "FAKE_INTEGRATE_SLEEP", "FAKE_COMPILE",
                  "FAKE_UNITY_STATUS"):
            os.environ.pop(k, None)
        self.told = []
        patcher = mock.patch.multiple(sbhub, LAND_LOCK_POLL=0.05, LAND_LOCK_WAIT=30, UNITY_POLL=0, LOCK_POLL=0,
                                      notify=lambda title, text: self.told.append(text))
        patcher.start()
        self.addCleanup(patcher.stop)

    def stages(self):
        return [json.loads(l) for l in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def workers(self):
        return [l for l in self.launched if not l["brief"].startswith("# Bring ")]

    def asked(self):
        """The hub's own editor_status calls (a Unity line's are sent --detach)."""
        rows = [json.loads(l) for l in self.ulog.read_text().splitlines()] if self.ulog.exists() else []
        return [r for r in rows if r["argv"][:2] == ["command", "editor_status"] and "--detach" not in r["argv"]]

    def unity_told(self):
        """The owner's alerts about Unity (others, such as an index.lock left in the checkout, are not this one's)."""
        return [t for t in self.told if "Unity is not answering" in t]

    def down(self):
        return (self.hub.state()["queue"].get("unity_down") or {}).get(str(self.repo))

    def waiting(self, key):
        return self.items().get(key, {}).get("unity_down") == str(self.repo)

    def test_no_unity_pauses_the_repo_until_editor_status_answers_and_no_try_is_spent(self):
        os.environ.update(FAKE_UNITY_STATUS="down", FAKE_INTEGRATE="no unity")
        before = git(self.repo, "rev-parse", "HEAD")
        self.only(1, 2)
        self.until(lambda: self.waiting("repo/one#1") and self.waiting("repo/one#2"), timeout=180)
        self.assertEqual(len(self.stages()), 1)  # the second ticket's integrator never started
        self.assertEqual(len(self.workers()), 2)
        self.assertEqual(git(self.repo, "diff", before, "HEAD"), "")  # the first landing backed out, the second never landed
        since = sbhub._hm(self.clock())
        for key in ("repo/one#1", "repo/one#2"):
            item = self.items()[key]
            self.assertTrue(item["note"].startswith("waits for Unity: not answering since " + since), item["note"])
            self.assertIn("with no try spent", item["note"])
            self.assertLessEqual(item.get("tries") or 0, 1)
            self.assertFalse(item.get("rechecks"))
            self.assertIsNone(item.get("recheck_at"))
        self.assertEqual(len(self.asked()), 1)  # asked once, after the integrator's `no unity`
        self.assertIn("No Pipeline instance found", self.down()["why"])
        self.assertEqual(len(self.unity_told()), 1, self.told)

        for _ in range(5):  # nothing is asked again before UNITY_DOWN_POLL, and nothing moves
            self.sup.tick()
        self.assertEqual(len(self.asked()), 1)
        self.clock.t += sbhub.UNITY_DOWN_POLL
        self.until(lambda: len(self.asked()) == 2)
        self.until(lambda: self.down()["at"] == self.clock())
        self.assertEqual(len(self.unity_told()), 1, self.told)  # one message for the whole silence
        self.assertTrue(self.waiting("repo/one#1") and self.waiting("repo/one#2"))
        self.assertEqual(len(self.stages()), 1)

        os.environ.update(FAKE_UNITY_STATUS="", FAKE_INTEGRATE="works")
        self.clock.t += sbhub.UNITY_DOWN_POLL
        self.until(lambda: self.state_of("repo/one#1") == "done" and self.state_of("repo/one#2") == "done",
                   timeout=240)
        self.assertIsNone(self.down())
        self.assertEqual(len(self.stages()), 3)  # one Unity stage each once it answered
        self.assertEqual(len(self.workers()), 2)  # no worker ran again: waiting was no try
        for key in ("repo/one#1", "repo/one#2"):
            self.assertLessEqual(self.items()[key].get("tries") or 0, 1)
        self.assertEqual(len(self.unity_told()), 1, self.told)
        self.assertEqual(self.hub.state()["locks"], {})

    def test_an_editor_that_answers_after_no_unity_changes_nothing(self):
        os.environ["FAKE_INTEGRATE"] = "no unity"
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "recheck", timeout=120)
        self.assertEqual(len(self.asked()), 1)
        self.assertIsNone(self.down())
        item = self.items()["repo/one#1"]
        self.assertIn(sbhub.NO_UNITY, item["note"])  # the usual recheck: it lands again
        self.assertNotIn("unity_down", item)
        self.assertEqual(self.unity_told(), [])

    def test_a_unity_pass_waits_while_unity_does_not_answer(self):
        self.verdicts["repo/one#1"] = "partly"
        self.only(1)
        self.until(lambda: self.state_of("repo/one#1") == "failed", timeout=180)
        stages = len(self.stages())
        with self.hub._lock:
            self.hub._data["queue"]["unity_down"] = {str(self.repo): {"since": self.clock(), "at": self.clock(),
                                                                      "why": "no answer"}}
        os.environ["FAKE_UNITY_STATUS"] = "down"
        self.verdicts["repo/one#1"] = "finished"
        self.hub.queue_integrate(["repo/one#1"])
        go(self.hub)
        w = self.until(lambda: self.items()["repo/one#1"].get("waits"))
        for _ in range(5):
            self.sup.tick()
        self.assertEqual(len(self.stages()), stages)  # no integrator started
        self.assertEqual(self.items()["repo/one#1"]["state"], "queued")
        self.assertEqual(w["kind"], "unity")
        self.assertTrue(w["text"].startswith("waits for Unity: not answering since "), w)
        os.environ["FAKE_UNITY_STATUS"] = ""
        self.clock.t += sbhub.UNITY_DOWN_POLL
        self.until(lambda: len(self.stages()) == stages + 1, timeout=120)

    def test_a_landing_unity_could_not_reach_gives_the_lock_back_once_main_is_backed_out(self):
        # 2026-11-22, sk4te/build-mode#1390: the revert landed, replaying the work in its worktree failed, and the
        # Unity lock stayed held until a person freed it
        os.environ["FAKE_INTEGRATE"] = "no unity"
        before = git(self.repo, "rev-parse", "HEAD")
        with mock.patch.object(sbhub, "replay_tree", lambda *a: "git rebase of its worktree onto the revert failed: "
                                                                 "Rebasing (1/1)"):
            self.only(1)
            self.until(lambda: self.state_of("repo/one#1") == "failed", timeout=120)
        self.assertEqual(git(self.repo, "diff", before, "HEAD"), "")  # the main folder is backed out
        self.assertNotIn(sbhub.unity_lock(self.repo), self.hub.state()["locks"])
        note = self.items()["repo/one#1"]["note"]
        self.assertIn(sbhub.NO_UNITY, note)
        self.assertIn("The {} lock was given back".format(sbhub.unity_lock(self.repo)), note)
        self.assertNotIn(sbhub.UNDO_FAILED, note)

    def test_a_landing_whose_revert_itself_failed_still_keeps_the_lock(self):
        os.environ["FAKE_INTEGRATE"] = "no unity"
        with mock.patch.object(sbhub, "revert_landing", lambda *a, **k: ("git merge --ff-only of the revert failed: "
                                                                         "boom", None)):
            self.only(1)
            self.until(lambda: self.state_of("repo/one#1") == "failed", timeout=120)
        self.assertIn(sbhub.unity_lock(self.repo), self.hub.state()["locks"])  # main still holds it: nothing lands on top
        self.assertIn(sbhub.UNDO_FAILED, self.items()["repo/one#1"]["note"])


class ScenesClosedTest(unittest.TestCase):
    """Every git write the hub makes in a Unity project's main folder (a landing, a back-out, a stage's leftovers
    restored) runs with the Editor on an empty untitled scene, so a rewritten scene file can never raise Unity's
    "modified externally: Reload / Ignore?" box (the 11-17 and 11-22 nights); the scene setup comes back after it.
    The fake `unity` answers the evals in the live Editor's shape and logs the project's HEAD at each."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.repo = self.root / "game"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.5.5f1\n")
        (self.repo / "Assets").mkdir()
        (self.repo / "Assets" / "Main.unity").write_text("scene v1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "a unity project")
        self.before = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "Assets" / "Main.unity").write_text("scene v2\n")
        git(self.repo, "commit", "-q", "-am", "the landing")
        self.sha = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "reset", "-q", "--hard", self.before)
        fake_unity_on_path(self.root / "bin")
        self.ulog = self.root / "unity.jsonl"
        env = mock.patch.dict(os.environ, PATH="{}:{}".format(self.root / "bin", os.environ["PATH"]),
                              FAKE_UNITY_LOG=str(self.ulog), FAKE_UNITY_STATE=str(self.root / "none.json"))
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("FAKE_UNITY_SCENES", None)

    def evals(self):
        rows = [json.loads(l) for l in self.ulog.read_text().splitlines()] if self.ulog.exists() else []
        return [(r["argv"][r["argv"].index("--code") + 1], r["head"]) for r in rows if r["argv"][:2] == ["command", "eval"]]

    def test_a_landing_closes_the_open_scenes_writes_then_refreshes_and_opens_them_again(self):
        os.environ["FAKE_UNITY_SCENES"] = "10Assets/Scenes/Persistent.unity\n11Assets/Scenes/Play\"ground.unity"
        self.assertIsNone(sbhub.land(self.repo, self.sha))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.sha)
        [(close, at_close), (restore, at_restore)] = self.evals()
        self.assertIn("close scenes", close)
        self.assertIn("NewSceneSetup.EmptyScene", close)  # an empty untitled scene, unsaved changes dropped
        self.assertIn("isPlaying", close)
        self.assertEqual(at_close, self.before)  # closed before the merge
        self.assertEqual(at_restore, self.sha)  # opened again after it
        self.assertLess(restore.index("AssetDatabase.Refresh()"), restore.index("RestoreSceneManagerSetup"))
        self.assertIn('path = @"Assets/Scenes/Persistent.unity", isLoaded = true, isActive = false', restore)
        self.assertIn('path = @"Assets/Scenes/Play""ground.unity", isLoaded = true, isActive = true', restore)

    def test_a_back_out_and_a_stages_leftovers_are_written_with_the_scenes_closed_too(self):
        sbhub.land(self.repo, self.sha)
        self.ulog.unlink()
        err, new = sbhub.revert_landing(self.repo, self.before, self.sha, "no unity")
        self.assertIsNone(err)
        [(close, at_close), (restore, at_restore)] = self.evals()
        self.assertEqual((at_close, at_restore), (self.sha, new))
        self.ulog.unlink()
        (self.repo / "Assets" / "Main.unity").write_text("Unity wrote this in Play\n")
        self.assertEqual(sbhub.tidy_stage(self.repo, [], self.root / "left.patch"), ["Assets/Main.unity"])
        self.assertEqual([("close scenes" in c, "restore scenes" in c) for c, _ in self.evals()],
                         [(True, False), (False, True)])

    def test_in_play_or_with_no_editor_nothing_is_closed_and_the_write_goes_ahead(self):
        for scenes in ("playing", "down"):
            git(self.repo, "reset", "-q", "--hard", self.before)
            os.environ["FAKE_UNITY_SCENES"] = scenes
            self.assertIsNone(sbhub.land(self.repo, self.sha))
            self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.sha)
        self.assertEqual([("close scenes" in c) for c, _ in self.evals()], [True, True])  # no restore after either

    def test_a_folder_that_is_not_a_unity_project_asks_unity_nothing(self):
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").unlink()
        self.assertIsNone(sbhub.land(self.repo, self.sha))
        self.assertEqual(self.evals(), [])

    def test_main_is_backed_out_once_the_revert_is_on_the_branch_or_the_landing_never_got_there(self):
        landing = {"repo": str(self.repo), "before": self.before, "sha": self.sha}
        self.assertTrue(sbhub.main_backed_out(landing))  # not landed
        sbhub.land(self.repo, self.sha)
        self.assertFalse(sbhub.main_backed_out(landing))
        sbhub.revert_landing(self.repo, self.before, self.sha, "no unity")
        self.assertTrue(sbhub.main_backed_out(landing))

    def test_the_old_reload_of_dirty_scenes_is_gone(self):
        self.assertFalse(hasattr(sbhub, "drop_unsaved_scenes"))


if __name__ == "__main__":
    unittest.main()
