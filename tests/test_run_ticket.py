"""`sbhub.py run-ticket`: one ticket run to its end, answered with one JSON result (the contract's RunTicketResult).

The same temp vault, repos and tests/fake_worker.py as the runner tests (RunnerCase). Most tests call
sbhub.run_ticket in process with the test hub (its fixed clock and launcher); one runs the real command, one
detaches it and reads it back with --status. Every result is also written to
contract/fixtures/run-ticket/<name>.json, which the contract's Vitest test parses with RunTicketResult."""
import json
import os
import re
import subprocess
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from helpers import SCRIPT  # noqa: E402
import sbhub  # noqa: E402
from test_hub_runner import RunnerCase, git  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "skills" / "sb" / "hub" / "packages" / "contract" / "fixtures" / "run-ticket"
KEYS = {"key", "state", "note", "commit", "checks", "media", "retry", "stop", "agent", "model", "tries", "stops", "base",
        "log", "report", "run", "tree", "branch"}


class RunTicketCase(RunnerCase):
    def run_ticket(self, key="repo/one#1", mode="commit", **kw):
        self.modes[key] = mode
        return sbhub.run_ticket(key, hub=self.hub, port=4321, **kw)

    def fixture(self, name, obj):
        """Write a result for the contract with paths, shas, pids and timings made stable."""
        text = json.dumps(obj, indent=1, sort_keys=True).replace(str(self.root), "/tmp/sb")
        text = re.sub(r"\b[0-9a-f]{40}\b", "0" * 40, text)
        text = re.sub(r"\b[0-9a-f]{9}\b", "0" * 9, text)
        text = re.sub(r"\d{4}-\d{2}-\d{2}-", "2026-11-13-", text)
        text = re.sub(r"-\d{8}-\d{6}-\d{6}\.", "-20261113-010000-000000.", text)
        text = re.sub(r"run-ticket/\d+\.json", "run-ticket/4242.json", text)
        text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", "2026-11-13 01:00", text)
        out = json.loads(text)

        def stable(o):
            if isinstance(o, dict):
                return {k: (0.5 if k == "secs" else 4242 if k == "pid" else stable(v)) for k, v in o.items()}
            return [stable(x) for x in o] if isinstance(o, list) else o
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / (name + ".json")).write_text(json.dumps(stable(out), indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def assertResult(self, res, state):
        self.assertEqual(set(res), KEYS)
        self.assertEqual(res["state"], state, res["note"])
        self.assertIn(res["state"], sbhub.RESULT_STATES)
        json.dumps(res)  # it is JSON as it stands


class RunTicketTest(RunTicketCase):
    def test_a_commit_is_checked_resolved_and_answered_with_its_checks_and_media(self):
        board = self.sup.runner.board("repo/one")
        media = Path(board).parent / "1-media"
        media.mkdir()
        (media / "after.png").write_bytes(b"\x89PNG")
        (media / "notes.txt").write_text("not a picture")
        res = self.run_ticket(agent="main")
        self.assertResult(res, "done")
        sha = git(self.repos["repo/one"], "log", "-1", "--format=%H", "--grep", "^Ticket: repo/one/001")
        self.assertEqual((res["commit"], res["note"]), (sha, "resolved, commit " + sha[:9]))
        self.assertEqual([(c["cmd"], c["code"]) for c in res["checks"]], [("true", 0)])
        self.assertIsInstance(res["checks"][0]["tail"], str)
        self.assertEqual(res["media"], ["after.png"])
        self.assertEqual((res["agent"], res["model"], res["tries"], res["retry"], res["stop"]), ("main", "sonnet", 1, None, None))
        self.assertEqual(Path(res["log"]).name, "1.log")
        self.assertIn("## Hub checks", Path(res["report"]).read_text(encoding="utf-8"))
        self.assertNotIn(1, self.open_tickets())
        # the hub's state is read, never written: its queue knows nothing of this run
        self.assertEqual(self.hub.state()["queue"]["items"], [])
        self.fixture("done", res)

    def test_no_commit_on_sonnet_answers_retry_on_opus_and_the_retry_fails_with_a_comment(self):
        res = self.run_ticket(mode="nothing")
        self.assertResult(res, "retry")
        self.assertEqual(res["retry"]["model"], "opus")
        self.assertIn("no commit", res["retry"]["reason"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")  # released for the retry
        self.fixture("retry", res)
        again = self.run_ticket(mode="nothing", model="opus", item={"tries": 1, "retry": res["retry"]["reason"]})
        self.assertResult(again, "failed")
        self.assertEqual((again["model"], again["tries"]), ("opus", 2))
        self.assertIn("The first try failed", self.launched[-1]["brief"])
        self.assertIn("no commit", self.ticket_text(1))
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.fixture("failed", again)

    def test_a_check_that_exits_75_answers_recheck_keeps_the_commit_and_the_claim(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=sh -c 'exit 75'", "--no-sync")
        res = self.run_ticket()
        self.assertResult(res, "recheck")
        self.assertTrue(res["commit"])
        self.assertIn("check could not run", res["note"])
        self.assertEqual(res["checks"][0]["code"], 75)
        self.assertEqual(self.open_tickets()[1]["status"], "claimed")
        self.assertNotIn("failed", self.ticket_text(1))
        self.assertIn("check could not run", Path(res["report"]).read_text(encoding="utf-8"))
        self.fixture("recheck", res)

    def test_a_failing_check_fails_with_the_checks_tail(self):
        self.sb("set", "repo/one", "001", "tier=opus", "checks=echo broke && false", "--no-sync")
        res = self.run_ticket()
        self.assertResult(res, "failed")
        self.assertTrue(res["commit"])
        self.assertEqual(res["checks"][0]["code"], 1)
        self.assertIn("broke", res["checks"][0]["tail"])

    def test_a_usage_limit_stops_with_its_reset(self):
        res = self.run_ticket(mode="limit")
        self.assertResult(res, "stopped")
        self.assertEqual(res["stop"], {"kind": "limit", "agent": "main", "until": datetime(2026, 11, 13, 4, 40).timestamp()})
        self.assertEqual(res["stops"], 1)
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        self.assertIsNone(self.hub.state()["installed"]["main"]["limited_until"])  # the queue applies it, not the run
        self.fixture("stopped-limit", res)

    def test_an_expired_login_stops_with_auth(self):
        res = self.run_ticket(mode="auth", agent="spare")
        self.assertResult(res, "stopped")
        self.assertEqual(res["stop"], {"kind": "auth", "agent": "spare", "until": None})
        self.fixture("stopped-auth", res)

    def test_a_third_stop_fails(self):
        res = self.run_ticket(mode="limit", item={"stops": 2})
        self.assertResult(res, "failed")
        self.assertEqual((res["stops"], res["stop"]["kind"]), (3, "limit"))
        self.assertIn("stopped 3 times", res["note"])

    def test_what_cannot_run_is_skipped_or_failed_without_a_worker(self):
        self.sb("claim", "repo/one", "002", "--by", "someone")
        res = self.run_ticket("repo/one#2")
        self.assertResult(res, "skipped")
        self.assertIn("claimed by someone", res["note"])
        self.fixture("skipped", res)
        self.assertResult(self.run_ticket("repo/one#9"), "skipped")
        res = self.run_ticket(agent="nobody")
        self.assertResult(res, "failed")
        self.assertIn("nobody is not an installed agent", res["note"])
        self.assertEqual(self.launched, [])

    def test_a_worker_past_the_limit_is_killed(self):
        res = self.run_ticket(mode="hang", model="opus", item={"tries": 1}, limit=1)
        self.assertResult(res, "failed")
        self.assertEqual(res["note"], "ran past 1 second")
        self.assertEqual(res["checks"], [])

    def ticket_text(self, num, folder="repo/one"):
        f = next((self.vault / "wayfinder" / folder / "issues").glob("{:03d}*.md".format(num)))
        return f.read_text(encoding="utf-8")


class RunTicketCommandTest(RunTicketCase):
    """The real command, as the TypeScript server will run it."""

    def env(self, **extra):
        return {**os.environ, "SB_HUB_HOME": str(self.root / "hub"), "SB_HUB_PORT": "1", **extra}

    def test_the_command_prints_one_json_result(self):
        self.hub._save()  # the installed agents the command reads
        r = subprocess.run([sys.executable, str(SCRIPT), "run-ticket", "repo/one#1", "--agent", "main"],
                           capture_output=True, text=True, env=self.env(FAKE_WORKER_MODE="commit"), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        self.assertResult(res, "done")
        self.assertIn('"CLAUDE_CONFIG_DIR": "{}"'.format(self.root / ".claude-main"), Path(res["log"]).read_text())
        bad = subprocess.run([sys.executable, str(SCRIPT), "run-ticket", "not a key"], capture_output=True, text=True,
                             env=self.env())
        self.assertEqual(bad.returncode, 2)

    def test_detach_prints_its_pid_and_status_reads_it_until_its_result(self):
        self.hub._save()
        r = subprocess.run([sys.executable, str(SCRIPT), "run-ticket", "repo/one#1", "--detach"], capture_output=True,
                           text=True, env=self.env(FAKE_WORKER_MODE="slow", FAKE_WORKER_SLEEP="1"), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        started = json.loads(r.stdout)
        self.assertEqual(set(started), {"pid", "log", "result", "status"})
        self.fixture("detached", started)

        def status():
            s = subprocess.run([sys.executable, str(SCRIPT), "run-ticket", "--status", str(started["pid"])],
                               capture_output=True, text=True, env=self.env(), timeout=30)
            self.assertEqual(s.returncode, 0, s.stderr)
            return json.loads(s.stdout)
        seen, end = [], time.time() + 60
        while time.time() < end:
            got = status()
            seen.append(got)
            if got["result"] is not None:
                break
            time.sleep(0.2)
        self.assertTrue(any(s["running"] for s in seen), seen)
        running = next(s for s in seen if s["running"])
        self.assertEqual((running["key"], running["note"]), ("repo/one#1", "running"))
        self.fixture("status-running", running)
        last = seen[-1]
        self.assertEqual((last["running"], last["note"]), (False, "ended: done"), Path(started["log"]).read_text())
        self.assertResult(last["result"], "done")
        self.assertEqual(Path(last["worker"]["log"]).name, "1.log")
        self.fixture("status-ended", last)
        unknown = subprocess.run([sys.executable, str(SCRIPT), "run-ticket", "--status", "1"], capture_output=True,
                                 text=True, env=self.env())
        self.assertEqual((unknown.returncode, json.loads(unknown.stdout)["known"]), (1, False))
        self.fixture("status-unknown", json.loads(unknown.stdout))


if __name__ == "__main__":
    unittest.main()
