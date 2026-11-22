"""A Unity dialog waiting for a click (ticket 190): while anything in a Unity repo runs, the hub lists Unity's windows
once a minute and puts 'Unity shows <title>: click it' on the board and the phone. It never clicks."""
import json
import subprocess
import sys
import threading
import time
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
        self.assertEqual(sbhub.unity_dialogs([dict(MAIN, name="")]), [])  # one big untitled window: the editor
        lone = {"owner": "Unity", "name": "", "layer": 0, "w": 260, "h": 304}  # what this Mac's list really showed
        self.assertEqual(sbhub.unity_dialogs([lone]), ["a window"])
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

    def test_the_watcher_looks_while_the_tick_is_held_by_a_running_check(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.shown = [MAIN, {"owner": "Unity", "name": "Reimport", "layer": 0, "w": 400, "h": 160}]
        with mock.patch.object(sbhub, "DIALOG_TICK", 0.05), mock.patch.object(self.sup, "tick", lambda: gate.wait(30)), \
                mock.patch.object(self.hub, "agents_scan", lambda: None):
            with self.hub._lock:
                self.hub._data["queue"]["items"][-1]["state"] = "running"
            th = threading.Thread(target=self.sup.run, daemon=True)
            th.start()  # its tick never returns: a check is running
            end = time.time() + 20  # not `until`: it ticks, and this tick is the one held
            while not self.rows() and time.time() < end:
                time.sleep(0.05)
            self.assertEqual([r["note"] for r in self.rows().values()], ["Unity shows Reimport: click it"])
            self.sup.stopped = True
            gate.set()

    def test_nothing_running_in_the_repo_means_no_listing(self):
        self.look("queued")
        self.assertEqual(self.looks, [])

    def test_a_repo_that_is_not_a_unity_project_is_never_listed(self):
        (self.repo / "ProjectSettings" / "ProjectVersion.txt").unlink()
        self.look()
        self.assertEqual(self.looks, [])


POP = {"owner": "Unity", "name": "Scene Modified Externally", "layer": 0, "w": 400, "h": 160}


class PopupWatchdogTest(DialogWatchTest):
    """The popup watchdog: a Unity dialog up for 10 minutes while a night runs gets its Editor quit (gracefully, then
    forced) and started again on the same project and version, at most twice a night per repo; the items that waited
    on Unity are checked again once it is ready. Never with a chat holding the Unity lock, in Play, or with the owner
    at the keyboard. A restarted Editor that shows a dialog again asks the owner once and is left alone. No real
    Editor: `unity` and `ioreg` go through a fake."""

    # the dialog watcher's own tests run once, in DialogWatchTest
    test_a_dialog_is_named_once_listed_once_a_minute_and_gone_when_it_closes = None
    test_the_watcher_looks_while_the_tick_is_held_by_a_running_check = None
    test_nothing_running_in_the_repo_means_no_listing = None
    test_a_repo_that_is_not_a_unity_project_is_never_listed = None

    def setUp(self):
        super().setUp()
        self.calls, self.idle, self.editor, self.state, self.graceful = [], 3600, True, "ready", True
        self.after_open = [MAIN]
        self.answers = False  # True: the Editor answers editor_status, whatever windows it shows
        self.sup.unity_cmd = self.cmd
        with self.hub._lock:
            self.night = self.hub._night_start()["id"]
            self.hub._save()

    def cmd(self, argv, **kw):
        self.calls.append(list(argv))
        rc, out = 0, ""
        if argv[0] == "ioreg":
            out = '    | |   "HIDIdleTime" = {}\n'.format(int(self.idle * 1e9))
        elif argv[:2] == ["unity", "status"]:
            inst = [{"projectPath": str(self.repo), "editorVersion": "6000.5.5f1", "pid": 4242, "state": self.state}]
            out = json.dumps({"success": True, "data": {"instances": inst if self.editor else []}})
        elif argv[:3] == ["unity", "command", "editor_status"]:  # a modal holds the main thread: no answer
            blocked = any(w is not MAIN for w in self.shown) and not self.answers
            out = json.dumps({"success": not blocked, "data": {"result": {} if not blocked else None},
                              "errors": [{"message": "EDITOR_BLOCKED_BY_DIALOG"}] if blocked else []})
            rc = 1 if blocked else 0
        elif argv[:2] == ["unity", "close"]:
            if "--force" in argv or self.graceful:
                self.editor = False
            else:
                rc = 1
        elif argv[:3] == ["unity", "projects", "open"]:
            self.editor, self.state, self.shown = True, "ready", list(self.after_open)
        return subprocess.CompletedProcess(argv, rc, out, "")

    def unity_calls(self):
        return [c[1:3] if c[1] == "projects" else c[1:2] + (["--force"] if "--force" in c else []) for c in self.calls
                if c[0] == "unity" and c[1] not in ("status", "command")]

    def popup_for(self, minutes):
        """Looks once a minute with the dialog up, `minutes` of them after the first."""
        self.shown = [MAIN, POP]
        self.look()
        for _ in range(minutes):
            self.clock.t += sbhub.DIALOG_POLL
            self.look()

    def restarts(self):
        with self.hub._lock:
            night = self.hub._night_live() or {}
            return dict((night.get("unity_restarts") or {}).get(str(self.repo)) or {}), list(night.get("log") or [])

    def test_a_dialog_up_ten_minutes_in_a_night_restarts_the_editor_and_rechecks_what_waited(self):
        self.sup.tick = lambda: None  # what is rechecked would run at once: here it only shows it is due
        with self.hub._lock:
            self.hub._data["queue"]["unity_down"] = {str(self.repo): {"since": self.clock(), "at": self.clock(), "why": "x"}}
            self.hub._data["queue"]["items"].insert(0, {"key": "repo/one#8", "kind": "ticket", "state": "queued",
                                                     "repo": str(self.repo), "note": "waits for Unity",
                                                     "unity_down": str(self.repo)})
            self.hub._data["queue"]["items"].insert(0, {"key": "repo/one#1", "kind": "ticket", "state": "recheck",
                                                     "repo": str(self.repo), "note": "", "recheck_at": self.clock() + 9999})
            self.hub._save()
        self.popup_for(9)
        self.assertEqual(self.unity_calls(), [])  # nine minutes: not yet
        self.clock.t += sbhub.DIALOG_POLL
        self.look()
        self.assertEqual(self.unity_calls(), [["close"], ["projects", "open"]])
        [opened] = [c for c in self.calls if c[1:3] == ["projects", "open"]]
        self.assertEqual(opened[3:], [str(self.repo), "--editor-version", "6000.5.5f1", "--non-interactive"])
        rec, log = self.restarts()
        self.assertEqual(rec["n"], 1)
        [line] = log
        self.assertIn("restarted the Editor (1 of 2 tonight)", line["text"])
        self.assertIn("Scene Modified Externally", line["text"])
        board = self.hub.state()["agents"]["unity-restart:" + str(self.repo)]
        self.assertEqual(board["note"], line["text"].split(": ", 1)[1])  # said once, the same words
        self.assertEqual(self.rows(), {})  # the dialog's row is gone with it
        self.assertNotIn("unity_down", self.hub.state()["queue"])
        items = self.items()
        self.assertNotIn("unity_down", items["repo/one#8"])
        self.assertEqual(items["repo/one#1"]["recheck_at"], self.clock())
        self.assertEqual(self.hub.state()["questions"], {})

    def test_no_restart_without_a_night_with_a_chat_on_the_lock_with_the_owner_here_or_in_play(self):
        def stays(why):
            self.calls.clear()
            self.sup.dialog_since.clear()
            self.popup_for(12)
            self.assertEqual(self.unity_calls(), [], why)
        self.idle = 30
        stays("the owner is at the keyboard")
        self.idle = 3600
        self.state = "playing"
        stays("in Play")
        self.state = "ready"
        self.hub.lock(sbhub.unity_lock(self.repo), "chat-sk4te")
        stays("a chat holds the Unity lock")
        self.hub.unlock(sbhub.unity_lock(self.repo), "chat-sk4te")
        with self.hub._lock:
            self.hub._night_live()["state"] = "ended"
            self.hub._data["queue"]["night"] = None
        stays("no night")

    def test_a_window_that_stays_up_while_the_editor_answers_is_no_popup(self):
        self.answers = True  # a floating window of its own: no modal holds the main thread
        self.popup_for(15)
        self.assertEqual(self.unity_calls(), [])

    def test_a_graceful_quit_that_fails_is_forced(self):
        self.graceful = False
        self.popup_for(10)
        self.assertEqual(self.unity_calls(), [["close"], ["close", "--force"], ["projects", "open"]])

    def test_at_most_two_restarts_a_night(self):
        for _ in range(3):
            self.popup_for(10)
            self.clock.t += sbhub.DIALOG_POLL
            self.shown = [MAIN]
            self.look()
            self.clock.t += sbhub.DIALOG_POLL
        self.assertEqual([c for c in self.unity_calls() if c == ["projects", "open"]], [["projects", "open"]] * 2)
        self.assertEqual(self.restarts()[0]["n"], 2)

    def test_a_dialog_again_after_the_restart_asks_the_owner_once_and_stops_restarting(self):
        self.after_open = [MAIN, dict(POP, name="Enter Safe Mode?")]
        self.popup_for(10)
        [q] = self.hub.state()["questions"].values()
        self.assertEqual((q["default"], q["options"]), ("leave it", ["leave it", "restart it once more"]))
        self.assertIn("Enter Safe Mode?", q["q"])
        rec, log = self.restarts()
        self.assertTrue(rec["stopped"])
        self.assertIn("It restarts it no more tonight", log[-1]["text"])
        self.popup_for(30)
        self.assertEqual(len([c for c in self.unity_calls() if c == ["projects", "open"]]), 1)  # left alone
        self.assertEqual(len(self.hub.state()["questions"]), 1)  # asked once
        [qid] = self.hub.state()["questions"]
        self.hub.answer(qid, "restart it once more")
        self.after_open = [MAIN]
        self.clock.t += sbhub.DIALOG_POLL
        self.popup_for(10)
        self.assertEqual(len([c for c in self.unity_calls() if c == ["projects", "open"]]), 2)

    def test_the_editors_launch_arguments_are_never_read(self):
        self.popup_for(10)
        self.assertTrue(self.calls)
        self.assertEqual({c[0] for c in self.calls}, {"ioreg", "unity"})  # no ps, no lsof: nothing reads its command line
