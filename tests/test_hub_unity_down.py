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


if __name__ == "__main__":
    unittest.main()
