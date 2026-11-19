"""The hub's answers, written as fixtures for the typed contract (skills/sb/hub/packages/contract).

A throwaway hub (a temp vault made through sbmap, a temp git repo, tests/fake_worker.py as `claude`, a fixed
clock) is driven into a state with agents, a queue, a question, a message and a lock; every route's answer is
written to contract/fixtures/<name>.json as {route, status, contentType, request?, body}. The contract's
Vitest test parses each one with its schema, so a field renamed here fails there. Paths, ids, dates and
timings are normalised so the files only change when a shape does."""
import hashlib
import http.server
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import uuid
from itertools import count
import urllib.request
from datetime import date, datetime
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from helpers import SBMAP, free_port  # noqa: E402
import sbhub  # noqa: E402
from sbhub import Hub, Supervisor, make_handler  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_worker.py"
FIXTURES = Path(__file__).resolve().parents[1] / "skills" / "sb" / "hub" / "packages" / "contract" / "fixtures"
START = datetime(2026, 11, 13, 1, 0).timestamp()
GIT_DATE = "2026-11-13T01:00:00"
DAY = "2026-11-13"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


class ContractFixturesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.vault, self.repo, home, binp = (self.root / n for n in ("Vault", "repo", "home", "bin"))
        for d in (self.vault / "wayfinder", home, binp, home / ".codex"):
            d.mkdir(parents=True)
        (home / ".codex" / "auth.json").write_text("{}")  # a signed-in Codex account for the scan
        for name in ("claude", "agy", "codex"):
            f = binp / name
            f.write_text("#!/bin/sh\nexec {} {} \"$@\"\n".format(shlex.quote(sys.executable), shlex.quote(str(FAKE))))
            f.chmod(0o755)
        env = {"SB_VAULT": str(self.vault), "PATH": "{}:/usr/bin:/bin".format(binp), "HOME": str(home),
               "SB_HUB_NOTIFY": "0", "FAKE_WORKER_MODE": "commit",
               "GIT_AUTHOR_DATE": GIT_DATE, "GIT_COMMITTER_DATE": GIT_DATE}  # the same shas every run
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("SB_HUB_PORT", "SB_HUB_AGENT", "SB_HUB_PARENT", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(k, None)
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        (self.repo / "README.md").write_text("x\n")
        (self.repo / ".sb").mkdir()  # the worker gets only named variables: the pinned commit dates must be named
        (self.repo / ".sb" / "env").write_text("GIT_AUTHOR_DATE\nGIT_COMMITTER_DATE\n")
        git(self.repo, "add", "README.md", ".sb/env")
        git(self.repo, "commit", "-q", "-m", "init")
        self.sb("init", "repo/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.", "--repo", str(self.repo))
        self.sb("mapset", "repo/one", "checks=true")
        for title, path in (("A", "one/"), ("B", "two/"), ("C", "three/"), ("D", "four/")):
            self.sb("new", "repo/one", "--title", title, "--why", "Because.", "--done-when", "It works.", "--paths", path,
                    "--no-sync")
        # a second map of the repo: queued whole, then moved before the first
        self.sb("init", "repo/two", "--title", "Two", "--why", "Why.", "--destination", "Elsewhere.", "--repo", str(self.repo))
        self.sb("mapset", "repo/two", "checks=true")
        for title in ("E", "F"):
            self.sb("new", "repo/two", "--title", title, "--why", "Because.", "--done-when", "It works.", "--paths", "five/",
                    "--no-sync")
        self.sb("new", "repo/two", "--title", "G", "--why", "Because.", "--type", "grilling", "--option", "Yes",
                "--option", "No", "--default", "1", "--no-sync")
        (self.vault / "wayfinder" / "repo" / "one" / "handoff.md").write_text(
            "---\ntitle: Handoff\n---\n# Handoff\n\nPick up at B.\n", encoding="utf-8")
        self.clock = Clock(START)
        self.hub = Hub(self.root / "hub", now=self.clock)
        with self.hub._lock:
            self.hub._data["installed"] = {n: {"kind": "claude", "dir": str(self.root / (".claude-" + n)), "model": None,
                                               "limited_until": None} for n in ("main", "spare")}
            self.hub._data["queue"]["agent"] = "main"
        self.sup = Supervisor(self.hub, port=4321)
        self.sup.close_off = False
        self.addCleanup(self.sup.stop)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), make_handler(self.hub))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        ids = count(1)  # question and message ids in order: 00000001, 00000002, ...
        ids_patch = mock.patch("sbhub.uuid.uuid4", side_effect=lambda: uuid.UUID(int=next(ids) << 96))
        ids_patch.start()
        self.addCleanup(ids_patch.stop)
        self.subs = {}  # text -> its stable stand-in
        self.written = []

    def sb(self, *a):
        return subprocess.run([sys.executable, str(SBMAP), *a], check=True, capture_output=True, text=True,
                              cwd=self.vault).stdout

    # ---- HTTP, and writing what came back ----

    def call(self, path, data=None):
        """(status, content type, raw body) of one request; a POST when `data` is given."""
        url = "http://127.0.0.1:{}{}".format(self.port, path)
        req = urllib.request.Request(url) if data is None else urllib.request.Request(
            url, json.dumps(data).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.headers.get("Content-Type"), e.read()

    def stable(self, text):
        for k, v in sorted(self.subs.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(k, v)
        text = re.sub(r"\b\d+(?:\.\d+)? s\b", "0.0 s", text)  # a check's seconds in a report
        return re.sub(r"\(\d+ \w+ ago\)", "(1 minute ago)", text)  # git's relative commit time

    def record(self, name, path, data=None, status=200):
        """Call the route, assert its status and write the fixture; returns the parsed JSON answer (or text)."""
        code, ctype, raw = self.call(path, data)
        self.assertEqual(code, status, "{} {}: {}".format(name, path, raw[:300]))
        fix = {"route": "{} {}".format("GET" if data is None else "POST", self.stable(path.split("?", 1)[0])),
               "status": code, "contentType": ctype}
        if data is not None:
            fix["request"] = data
        if ctype == "application/json":
            body = json.loads(raw)
            fix["body"] = json.loads(self.stable(raw.decode("utf-8")))  # before sorting: keys are normalised too
        elif ctype.startswith("text/"):
            body = raw.decode("utf-8")
            fix["body"] = body
        else:
            body = raw
            fix["bytes"] = len(raw)
        text = self.stable(json.dumps(fix, indent=2, sort_keys=True) + "\n")
        text = re.sub(r'"secs": [\d.]+', '"secs": 0.0', text)
        FIXTURES.mkdir(parents=True, exist_ok=True)
        f = FIXTURES / (name + ".json")
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
        self.written.append(f.name)
        return body

    def record_unity_stage(self):
        """The state answer while a ticket of a Unity project is in its stage (Supervisor._integrate) and another
        is queued for a Unity pass (Hub.queue_integrate). This repo is no Unity project, so the two items carry
        what the Supervisor writes there for the one answer, then go back as they were."""
        head = git(self.repo, "rev-parse", "HEAD")
        folder = self.vault / "wayfinder" / "repo" / "runs" / "2026-11-14-one"
        stage = {"key": None, "repo": str(self.repo), "before": head, "sha": head, "tree": None, "branch": "",
                 "only": True, "dirty": [], "folder": str(folder), "log": str(folder / "integrate.log")}
        with self.hub._lock:
            staged, passed = [i for i in self.hub._data["queue"]["items"] if i["kind"] == "ticket"][:2]
            kept = {i["key"]: json.loads(json.dumps(i)) for i in (staged, passed)}
            stage["key"] = staged["key"]
            staged.update(integrate=stage, integrate_only=True)
            passed.update(integrate_only=True)
        try:
            body = self.record("state-unity-stage", "/api/state")
        finally:
            with self.hub._lock:
                for i in (staged, passed):
                    was = kept[i["key"]]
                    i.clear()
                    i.update(was)
        got = {i["key"]: i for i in body["queue"]["items"]}
        self.assertEqual(got[staged["key"]]["integrate"]["sha"], head)
        self.assertTrue(got[passed["key"]]["integrate_only"])

    # ---- the run ----

    def test_every_route_answers_in_its_contract_shape(self):
        self.subs.update({str(self.root): "/fixture", quote(str(self.root), safe=""): quote("/fixture", safe=""),
                          date.today().isoformat(): DAY,
                          # the git guard hook in a worker's argv names this machine's python and checkout
                          str(sbhub.GUARD): "/fixture/sb/hooks/guard_git.py", sys.executable: "python3",
                          # the hub plugin a worker loads lives in whichever checkout runs the tests
                          str(sbhub.PLUGIN): "/fixture/mods/hub-report"})
        r = lambda name, data, status=200: self.record(name.replace("_", "-"), "/api/" + name.replace("_", "/", 1), data, status)

        # agents: a session, its alias, a worker it spawned, one that needs you
        project = str(self.repo)
        r("report", {"agent": "sess-1", "name": "main", "title": "Charting the hub", "asked": "chart it", "project": project,
                     "state": "working", "note": "reading sbhub.py", "done": 1, "total": 3})
        self.record("report-alias", "/api/report", {"agent": "sess-2", "alias": "sess-1", "state": "working"})
        self.record("report-spawn", "/api/report", {"agent": "sess-1", "spawn": "Read the routes"})
        self.record("report-worker", "/api/report", {"agent": "w-1", "role": "worker", "parent": "sess-1",
                                                       "state": "working", "project": project})
        self.record("report-map", "/api/report", {"agent": "sess-1", "map": "fixture/map"})
        self.record("report-needs-you", "/api/report", {"agent": "sess-3", "name": "other", "state": "needs you",
                                                          "note": "which port?"})
        self.hub.providers[project] = [sbhub.generic_provider(project)]

        # the trail: a read that ended, a command that failed, a subagent's run
        sess = {"session_id": "sess-1", "cwd": project}
        t0 = self.clock.t  # the rest of the fixtures keep their times
        for n, ev in enumerate((
                {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "sbhub.py"}},
                {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_input": {"file_path": "sbhub.py"}},
                {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"description": "run tests"}},
                {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_input": {"description": "run tests"}},
                {"hook_event_name": "SubagentStart", "agent_id": "w-1", "agent_type": "scout"},
                {"hook_event_name": "PreToolUse", "tool_name": "Grep", "tool_input": {"pattern": "claim"}})):
            self.clock.t += 1
            self.record("report-trail-%d" % n, "/api/report", sbhub.event_report({**sess, **ev}))
        self.record("trail", "/api/trail?agent=sess-1")
        self.record("trail-unknown", "/api/trail?agent=nope", status=404)
        self.clock.t = t0

        # a lock, and the answer to someone else's try
        r("lock", {"key": "port:5173", "by": "sess-1"})
        self.record("lock-held", "/api/lock", {"key": "port:5173", "by": "sess-3"}, 409)

        # a question waiting, and one answered
        waiting = r("ask", {"agent": "sess-3", "q": "Which port?", "options": ["5173", "5174"], "default": "5173",
                            "wait": 3600})["id"]
        answered = self.record("ask-answered", "/api/ask", {"agent": "sess-1", "q": "Ship it?", "options": ["yes", "no"],
                                                             "default": "no", "wait": 600})["id"]
        r("answer", {"qid": answered, "answer": "yes", "by": "you"})
        self.record("answer-unknown", "/api/answer", {"qid": "nope", "answer": "yes"}, 404)

        # messages: one delivered by the session's hook, one still waiting
        r("send", {"to": "sess-1", "text": "Use port 5174."})["id"]
        r("take", {"agent": "sess-1", "how": "UserPromptSubmit"})
        pending = self.record("send-pending", "/api/send", {"to": "w-1", "text": "Stop after the tests."})["id"]

        # the installed agents and the pool
        r("agents_scan", {})
        r("queue_agent", {"name": "main"})
        v = self.hub.state()["queue"]["version"]
        r("queue_agents", {"names": ["main", "spare"], "version": v})

        # ticket A runs on the fake worker to done, leaving a report, a log and a picture
        v = self.hub.state()["queue"]["version"]
        r("queue_set", {"keys": ["repo/one#1"], "version": v, "agent": "sess-1"})
        self.record("report-queue-worker", "/api/report", {"agent": "repo/one#1", "role": "worker", "parent": "queue",
                                                            "state": "working"})
        self.hub.night_start(drain=True)  # Start: queueing alone starts nothing (ticket 167)
        self.sup.tick()
        item = self.hub.state()["queue"]["items"][0]
        self.assertEqual(item["state"], "running", item)
        media = Path(item["run"]) / "1-media"
        media.mkdir()
        (media / "board.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        Path(item["run"], "1.md").write_text("# A\n\n## Self-checks\n\n- `true`: exit 0\n", encoding="utf-8")
        end = self.clock.t

        def a_state():  # when A is judged the night ends and A moves to the night's record
            q = self.hub.state()["queue"]
            return next((i["state"] for i in q["items"]), None) or self.hub.night(self.hub.nights()["nights"][0]["id"])["night"]["items"][0]["state"]
        for _ in range(400):
            self.sup.tick()
            if a_state() not in ("running", "landed", "review"):
                break
            threading.Event().wait(0.03)
        self.assertEqual(a_state(), "done", self.hub.state()["queue"])
        self.assertEqual(self.hub.state()["queue"]["night"], None)  # the only item was judged: the night ended as finished
        self.assertEqual(self.hub.nights()["nights"][0]["how"], "finished")
        self.clock.t = end + 60  # the ticket list's cache is read afresh
        self.sup.stop()
        r("queue_pause", {"paused": True})

        # tonight's queue: B and C ticked, two jobs, a stop time, B on the spare account
        v = self.hub.state()["queue"]["version"]
        r("queue_set", {"keys": ["repo/one#2", "repo/one#3"], "version": v})
        self.hub.night_start()  # the second run, held paused so nothing of it starts here
        r("queue_pause", {"paused": True})
        self.record("queue-set-stale", "/api/queue/set", {"keys": ["repo/one#2"], "version": v}, 409)
        v = self.hub.state()["queue"]["version"]
        r("queue_move", {"key": "repo/one#3", "to": 0, "version": v})
        v = self.hub.state()["queue"]["version"]
        mapped = r("queue_map", {"map": "repo/two", "version": v})
        self.assertEqual([x["key"] for x in mapped["left_out"]], ["repo/two#7"])  # G needs the owner
        v = self.hub.state()["queue"]["version"]
        moved = r("queue_move_map", {"map": "repo/two", "to": 0, "version": v})
        self.assertEqual(moved["queue"]["maps"], ["repo/two", "repo/one"])
        v = self.hub.state()["queue"]["version"]
        r("queue_options", {"stop_at": START + 6 * 3600, "final_review": True, "version": v})
        r("queue_item_agent", {"key": "repo/one#2", "name": "spare"})
        v = self.hub.state()["queue"]["version"]
        r("queue_parallel", {"repo": str(self.repo), "n": 2, "version": v})
        self.record("queue-parallel-refused", "/api/queue/parallel", {"repo": str(self.repo), "n": 9, "version": v + 1}, 400)
        self.record("queue-integrate-refused", "/api/queue/integrate", {"keys": []}, 400)  # a Unity pass names tickets
        self.sup._set_waits()  # each queued item says what it waits for (the queue is paused)
        for prompt in ("Audit the hub", "Tidy the README"):
            digest = hashlib.sha256((project + "\n" + prompt).encode("utf-8")).hexdigest()
            self.subs.update({digest: prompt[0].lower() * 64, digest[:12]: prompt[0].lower() * 12,
                              "job-" + digest[:6]: "job-" + prompt[0].lower() * 6})
        job = r("queue_job", {"project": project, "prompt": "Audit the hub", "agent": "main", "model": "opus",
                              "name": "audit", "at": "23:30"})["key"]
        spare = self.record("queue-job-plain", "/api/queue/job", {"project": project, "prompt": "Tidy the README"})["key"]
        for f in self.vault.rglob("*"):  # the side panel's trail shows file times
            os.utime(f, (START, START))

        # an older run that only the vault knows: its report, log and a picture, in a run folder no queue item points at
        old = self.vault / "wayfinder" / "repo" / "runs" / "2026-11-12-one"
        (old / "7-media").mkdir(parents=True)
        (old / "7.md").write_text("# 7: An older run\n\nCommit: abc1234 (branch sb/one)\n\n## Hub checks\n\n"
                                  "Checked by the sb hub at 2026-11-12 02:00: failed: check failed: pnpm test, commit abc1234.\n\n"
                                  "- `pnpm test`: exit 1, 3.5 s\n\n  ```\n  1 failed\n  ```\n", encoding="utf-8")
        (old / "7.log").write_text('{"type":"assistant","message":{"content":[{"type":"text","text":"Reading the tests."},'
                                   '{"type":"tool_use","name":"Read","input":{"file_path":"a.ts"}}]}}\nplain stderr line\n', encoding="utf-8")
        (old / "7-media" / "one.png").write_bytes(b"\x89PNG\r\n\x1a\nold")
        (old / "7-media" / "two.png").write_bytes(b"\x89PNG\r\n\x1a\nold2")
        for f in old.rglob("*"):
            os.utime(f, (START - 86400, START - 86400))

        # the guard hook refused a queued worker twice: the item carries refused and refused_lines
        for why in ("`git push` is refused", "`git stash` is refused"):
            self.hub.report({"agent": "repo/one#2", "role": "worker", "parent": "queue",
                             "trail": {"kind": "refused", "tool": "Bash", "label": why}})
        refused = next(i for i in self.hub.state()["queue"]["items"] if i["key"] == "repo/one#2")
        self.assertEqual(refused["refused"], 2)

        # every GET, in the state above
        self.record("state", "/api/state")
        self.record_unity_stage()
        self.record("runs", "/api/runs")
        self.record("runs-page", "/api/runs?limit=1&offset=1&since={}".format(int(START - 2 * 86400)))
        self.record("run", "/api/run?key=" + quote("repo/one#1"))
        self.record("run-vault", "/api/run?key=" + quote("repo/one#7"))
        self.record("run-unknown", "/api/run?key=nope", status=404)
        self.record("media-vault", "/api/media?key={}&name=two.png".format(quote("repo/one#7")))
        self.record("tickets", "/api/tickets")
        mp = self.record("map", "/api/map?map=repo/one")
        self.assertIn("done", {t["state"] for t in mp["tickets"]})
        self.record("map-unknown", "/api/map?map=repo/nowhere", status=404)
        self.sb("comment", "repo/one", "003", "--text", "Look at the queue first.")
        self.record("ticket", "/api/ticket?key=" + quote("repo/one#3"))
        self.record("ticket-unknown", "/api/ticket?key=" + quote("repo/one#99"), status=404)
        self.record("item-report", "/api/item/report?key=" + quote("repo/one#1"))
        self.record("item-log", "/api/item/log?key=" + quote("repo/one#1"))
        self.record("item-report-unknown", "/api/item/report?key=nope", status=404)
        self.record("media", "/api/media?key={}&name=board.png".format(quote("repo/one#1")))
        self.record("question", "/api/question/" + waiting)
        self.record("question-answered", "/api/question/" + answered)
        self.record("question-unknown", "/api/question/nope", status=404)
        self.record("not-found", "/api/nothing", status=404)

        # the answers that take things away
        r("queue_remove_job", {"key": spare, "version": self.hub.state()["queue"]["version"]})
        self.assertTrue(job)
        # the owner's Stop on a running ticket (B, made running by hand: no worker): marked, then ended by the
        # supervisor as stopped by you; a Stop with no reason is refused
        with self.hub._lock:
            b = next(i for i in self.hub._data["queue"]["items"] if i["key"] == "repo/one#2")
            b.update(state="running", started=self.clock.t, repo=str(self.repo), runner="spare")
        self.record("queue-stop-no-reason", "/api/queue/stop",
                    {"key": "repo/one#2", "reason": "", "version": self.hub.state()["queue"]["version"]}, 400)
        r("queue_stop", {"key": "repo/one#2", "reason": "It edits the wrong checkout.",
                         "version": self.hub.state()["queue"]["version"]})
        self.sup._reap()
        b = next(i for i in self.hub.state()["queue"]["items"] if i["key"] == "repo/one#2")
        self.assertEqual(b["state"], "skipped")
        self.assertTrue(b["note"].startswith("stopped by you: It edits the wrong checkout."), b["note"])
        # the night: Start opened it; a second start is refused; a stop after ends it as stopped
        nights = self.record("nights", "/api/nights")["nights"]
        self.assertEqual([n["state"] for n in nights], ["live", "ended"])
        live = nights[0]["id"]
        self.subs[live] = "night-fixture"
        self.subs[nights[1]["id"]] = "night-fixture-first"
        self.record("night", "/api/night?id=" + live)
        self.record("night-unknown", "/api/night?id=nope", status=404)
        self.record("night-start-refused", "/api/night/start", {"name": 5}, 400)  # a second start is refused too: test_hub_queue
        stopped = self.record("night-stop", "/api/night/stop", {"mode": "after"})["night"]
        self.assertEqual((stopped["state"], stopped["how"]), ("ended", "stopped"))
        self.assertTrue(stopped["not_reached"])
        self.record("night-stop-none", "/api/night/stop", {"mode": "now"}, 400)
        self.record("night-ended", "/api/night?id=" + live)
        self.record("night-start", "/api/night/start", {"name": "Second night", "by": "sess-1"})
        renamed = self.record("night-rename", "/api/night/rename", {"name": "Late shift"})["night"]
        self.assertEqual(renamed["name"], "Late shift")
        joined = r("run_join", {"agent": "sess-1", "role": "integrator"})  # a chat joins the live run (ticket 170)
        self.assertEqual(joined["joined"]["role"], "integrator")
        self.record("run-join-refused", "/api/run/join", {"agent": "sess-1", "role": "watcher"}, 400)
        r("run_leave", {"agent": "sess-1"})  # leaving twice is refused: test_hub
        r("unsend", {"id": pending})
        r("unlock", {"key": "port:5173", "by": "sess-1"})
        r("run_seen", {"key": "repo/one#1@1000"})
        r("agents_dismiss", {"agent": "sess-3"})
        r("agents_clear-quiet", {})
        self.assertEqual(r("review_now", {}), {"ok": True, "started": []})  # the queue was stopped: none starts
        self.record("missing-field", "/api/lock", {"key": "x"}, 400)
        self.record("bad-value", "/api/ask", {"agent": "a", "q": "?", "options": ["one"], "default": "one", "wait": 1}, 400)
        for action, text in (("comment", "Checked from the fixture."), ("tier", "opus"), ("checks", "true")):
            self.record("ticket-" + action, "/api/ticket/" + action, {"key": "repo/one#3", "text": text})
        self.sb("claim", "repo/one", "003", "--by", "someone")
        self.hub._fresh_tickets()
        self.record("ticket-release", "/api/ticket/release", {"key": "repo/one#3"})
        self.record("ticket-drop", "/api/ticket/drop", {"key": "repo/one#4", "text": "Not needed."})
        self.record("ticket-done", "/api/ticket/done", {"key": "repo/one#3", "text": "Done by hand."})

        stale = sorted(p.name for p in FIXTURES.glob("*.json") if p.name not in self.written)
        self.assertEqual(stale, [], "fixtures no route writes any more: delete them")


if __name__ == "__main__":
    unittest.main()
