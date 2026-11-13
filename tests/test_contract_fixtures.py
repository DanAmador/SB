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
        for d in (self.vault / "wayfinder", home, binp):
            d.mkdir(parents=True)
        for name in ("claude", "agy"):
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
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-q", "-m", "init")
        self.sb("init", "repo/one", "--title", "One", "--why", "Why.", "--destination", "Somewhere.", "--repo", str(self.repo))
        self.sb("mapset", "repo/one", "checks=true")
        for title, path in (("A", "one/"), ("B", "two/"), ("C", "three/"), ("D", "four/")):
            self.sb("new", "repo/one", "--title", title, "--why", "Because.", "--done-when", "It works.", "--paths", path,
                    "--no-sync")
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

    # ---- the run ----

    def test_every_route_answers_in_its_contract_shape(self):
        self.subs.update({str(self.root): "/fixture", quote(str(self.root), safe=""): quote("/fixture", safe=""),
                          date.today().isoformat(): DAY})
        r = lambda name, data, status=200: self.record(name.replace("_", "-"), "/api/" + name.replace("_", "/", 1), data, status)

        # agents: a session, its alias, a worker it spawned, one that needs you
        project = str(self.repo)
        r("report", {"agent": "sess-1", "name": "main", "title": "Charting the hub", "asked": "chart it", "project": project,
                     "state": "working", "note": "reading sbhub.py", "done": 1, "total": 3})
        self.record("report-alias", "/api/report", {"agent": "sess-2", "alias": "sess-1", "state": "working"})
        self.record("report-spawn", "/api/report", {"agent": "sess-1", "spawn": "Read the routes"})
        self.record("report-worker", "/api/report", {"agent": "w-1", "role": "worker", "parent": "sess-1",
                                                       "state": "working", "project": project})
        self.record("report-needs-you", "/api/report", {"agent": "sess-3", "name": "other", "state": "needs you",
                                                          "note": "which port?"})
        self.hub.providers[project] = [sbhub.generic_provider(project)]

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
        r("queue_set", {"keys": ["repo/one#1"], "version": v})
        r("queue_pause", {"paused": False})
        self.sup.tick()
        item = self.hub.state()["queue"]["items"][0]
        self.assertEqual(item["state"], "running", item)
        media = Path(item["run"]) / "1-media"
        media.mkdir()
        (media / "board.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        Path(item["run"], "1.md").write_text("# A\n\n## Self-checks\n\n- `true`: exit 0\n", encoding="utf-8")
        end = self.clock.t
        for _ in range(400):
            self.sup.tick()
            if self.hub.state()["queue"]["items"][0]["state"] != "running":
                break
            threading.Event().wait(0.03)
        self.assertEqual(self.hub.state()["queue"]["items"][0]["state"], "done", self.hub.state()["queue"])
        self.clock.t = end + 60  # the ticket list's cache is read afresh
        self.sup.stop()
        r("queue_pause", {"paused": True})

        # tonight's queue: B and C ticked, two jobs, a stop time, B on the spare account
        v = self.hub.state()["queue"]["version"]
        r("queue_set", {"keys": ["repo/one#2", "repo/one#3"], "version": v})
        self.record("queue-set-stale", "/api/queue/set", {"keys": ["repo/one#2"], "version": v}, 409)
        v = self.hub.state()["queue"]["version"]
        r("queue_move", {"key": "repo/one#3", "to": 0, "version": v})
        v = self.hub.state()["queue"]["version"]
        r("queue_options", {"stop_at": START + 6 * 3600, "final_review": True, "version": v})
        r("queue_item_agent", {"key": "repo/one#2", "name": "spare"})
        for prompt in ("Audit the hub", "Tidy the README"):
            digest = hashlib.sha256((project + "\n" + prompt).encode("utf-8")).hexdigest()
            self.subs.update({digest: prompt[0].lower() * 64, digest[:12]: prompt[0].lower() * 12,
                              "job-" + digest[:6]: "job-" + prompt[0].lower() * 6})
        job = r("queue_job", {"project": project, "prompt": "Audit the hub", "agent": "main", "model": "opus",
                              "name": "audit", "at": "23:30"})["key"]
        spare = self.record("queue-job-plain", "/api/queue/job", {"project": project, "prompt": "Tidy the README"})["key"]
        for f in self.vault.rglob("*"):  # the side panel's trail shows file times
            os.utime(f, (START, START))

        # every GET, in the state above
        self.record("state", "/api/state")
        self.record("tickets", "/api/tickets")
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
        r("queue_clear-finished", {"version": self.hub.state()["queue"]["version"]})
        r("unsend", {"id": pending})
        r("unlock", {"key": "port:5173", "by": "sess-1"})
        r("agents_dismiss", {"agent": "sess-3"})
        r("agents_clear-quiet", {})
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
