"""A Unity dialog waiting for a click (ticket 190): while anything in a Unity repo runs, the hub lists Unity's windows
once a minute and puts 'Unity shows <title>: click it' on the board and the phone. It never clicks."""
import json
import subprocess
import sys
import unittest
from unittest import mock

from test_hub_runner import RunnerCase, tearDownModule  # noqa: F401  (the shared templates' cleanup)
import sbhub

MAIN = {"owner": "Unity", "name": "SampleScene - sk4te - macOS - Unity 6000.7.0b10 <Metal>", "layer": 0, "w": 3000, "h": 1400}


class WindowListTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "the macOS window list")
    def test_the_real_window_list_answers_in_the_shape_the_hub_reads(self):
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", sbhub.WINDOW_LIST_JS], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)  # every on-screen window of every app, as CoreGraphics gives them
        self.assertTrue(rows)
        for w in rows:
            self.assertEqual(set(w), {"owner", "name", "layer", "w", "h"})
        found = sbhub.unity_windows()  # whatever Unity has open now, if anything
        self.assertTrue(all(w["owner"] == "Unity" for w in found))
        sbhub.unity_dialogs(found)  # and the real rows go through the dialog filter

    def test_off_macos_or_with_a_failing_osascript_there_are_no_windows(self):
        bad = mock.Mock(return_value=subprocess.CompletedProcess([], 1, "", "boom"))
        with mock.patch.object(sbhub.sys, "platform", "darwin"):
            self.assertEqual(sbhub.unity_windows(run=bad), [])
        with mock.patch.object(sbhub.sys, "platform", "linux"):
            self.assertEqual(sbhub.unity_windows(), [])

    def test_a_small_titled_window_beside_the_editor_is_a_dialog_and_the_editor_alone_is_not(self):
        pop = {"owner": "Unity", "name": "Scene Modified Externally", "layer": 0, "w": 400, "h": 160}
        hub = {"owner": "Unity Hub", "name": "Projects", "layer": 0, "w": 300, "h": 200}
        self.assertEqual(sbhub.unity_dialogs([MAIN, pop, hub]), ["Scene Modified Externally"])
        self.assertEqual(sbhub.unity_dialogs([MAIN]), [])
        self.assertEqual(sbhub.unity_dialogs([dict(MAIN, name="")]), [])  # one untitled window: cannot be told apart
        self.assertEqual(sbhub.unity_dialogs([MAIN, dict(pop, name="")]), ["a window"])
        self.assertEqual(sbhub.unity_dialogs([MAIN, dict(pop, layer=25)]), [])  # menus and tooltips sit above layer 0
        self.assertEqual(sbhub.dialog_text(["A", "B"]), "Unity shows A, B: click it")


class DialogWatchTest(RunnerCase):
    MAPS = (("repo/one", "game", ("A", "one/")),)

    def setUp(self):
        super().setUp()
        self.repo = self.repos["repo/one"]
        (self.repo / "ProjectSettings").mkdir()
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.5.5f1\n")
        self.told, self.shown, self.looks = [], [MAIN], []
        p = mock.patch.object(sbhub, "notify", lambda title, text: self.told.append(text))
        p.start()
        self.addCleanup(p.stop)

        def windows():
            self.looks.append(self.clock())
            return list(self.shown)
        self.sup.windows = windows
        with self.hub._lock:
            self.hub._data["queue"]["items"].append({"key": "repo/one#9", "kind": "ticket", "state": "running",
                                                     "repo": str(self.repo), "note": "", "runner": sbhub.CHAT_RUNNER})

    def rows(self):
        return {a: v for a, v in self.hub.state()["agents"].items() if a.startswith("unity-dialog:")}

    def look(self, state="running"):
        with self.hub._lock:
            self.hub._data["queue"]["items"][-1]["state"] = state
        self.sup._unity_dialogs()
        self.until(lambda: not self.sup.dialog_busy)

    def test_a_dialog_is_named_once_listed_once_a_minute_and_gone_when_it_closes(self):
        self.look()
        self.assertEqual(self.rows(), {})
        self.shown = [MAIN, {"owner": "Unity", "name": "Scene Modified Externally", "layer": 0, "w": 400, "h": 160}]
        self.look()
        self.assertEqual(len(self.looks), 1)  # not again before a minute
        self.clock.t += sbhub.DIALOG_POLL
        self.look()
        [row] = self.rows().values()
        self.assertEqual(row["note"], "Unity shows Scene Modified Externally: click it")
        self.assertEqual(row["state"], "needs you")
        self.assertEqual(self.told, ["{}: Unity shows Scene Modified Externally: click it".format(self.repo.name)])
        self.clock.t += sbhub.DIALOG_POLL
        self.look()
        self.assertEqual(len(self.told), 1)  # the same dialog is not told twice
        self.shown = [MAIN]
        self.clock.t += sbhub.DIALOG_POLL
        self.look()
        self.assertEqual(self.rows(), {})

    def test_nothing_running_in_the_repo_means_no_listing(self):
        self.look("queued")
        self.assertEqual(self.looks, [])

    def test_a_repo_that_is_not_a_unity_project_is_never_listed(self):
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").unlink()
        self.look()
        self.assertEqual(self.looks, [])
