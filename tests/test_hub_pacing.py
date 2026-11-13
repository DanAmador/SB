"""The hub paces each account's usage: readings from the workers' stream-json and a probe, a learned cost per
ticket, the fit rule over a pool of agents, logouts, limits that resume elsewhere, and the brake. The fake
worker stands in for `claude -p`, a fake function for the probe: never a model, never port 8765, ~/.sb-hub,
the owner's vault or the real ~/.claude*."""
import http.server
import json
import subprocess
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from helpers import SCRIPT  # noqa: E402
from test_hub_runner import START, TEMPLATES, RunnerCase, git  # noqa: E402
import sbhub  # noqa: E402
from sbhub import Hub  # noqa: E402

R = datetime(2026, 11, 13, 4, 20).timestamp()  # the 5-hour window's reset, 3 h 20 after START


def tearDownModule():
    for k in list(TEMPLATES):  # built here for these maps; test_hub_runner builds its own again
        TEMPLATES.pop(k).cleanup()


def ev(five, resets=R, week=0.1, week_resets=R + 4 * 86400, status="allowed"):
    """One `rate_limit_event` line as `claude -p --output-format stream-json --verbose` prints it."""
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": status, "resetsAt": resets, "rateLimitType": "five_hour", "unifiedWindows": {
            "five_hour": {"utilization": five, "resetsAt": resets, "status": status},
            "seven_day": {"utilization": week, "resetsAt": week_resets, "status": "allowed"}}}}) + "\n"


class PacingCase(RunnerCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/")),)

    def setUp(self):
        super().setUp()
        self.sup.probe = self.probe
        self.probes, self.probe_out = [], {}
        self.agent_modes, self.agent_env, self.partial = {}, {}, None
        self.hub.queue_agents(["main", "spare"], None)

    def probe(self, agent, cwd):
        name = Path(agent["dir"]).name[len(".claude-"):]
        self.probes.append(name)
        return self.probe_out.get(name, "")

    def launcher(self, agent, brief, repo, model, env, log):
        key, name = env["SB_HUB_AGENT"], Path(agent["dir"]).name[len(".claude-"):]
        mode = self.agent_modes.get(name) or self.modes.get(key, self.mode)
        if key.startswith("job:") and mode == "commit":
            mode = "job"
        self.launched.append({"key": key, "model": model, "brief": brief, "name": name, "log": log})
        if self.partial and name == self.partial:  # this try commits part of the work before it stops
            (Path(repo) / "one").mkdir(exist_ok=True)
            (Path(repo) / "one" / "partial.txt").write_text("half\n")
            git(repo, "add", "one/partial.txt")
            git(repo, "commit", "-q", "-m", "wip")
        return sbhub.launch(agent, brief, repo, model,
                            {**env, "FAKE_WORKER_MODE": mode, **self.agent_env.get(name, {})}, log)

    def inst(self, name):
        return self.hub.state()["installed"][name]

    def running(self):
        return {k: i for k, i in self.items().items() if i["state"] == "running"}


class FitTest(PacingCase):
    MAPS = (("repo/one", "repoA", ("A", "one/"), ("B", "two/")),
            ("repo/two", "repoB", ("C", "three/")),
            ("repo/three", "repoC", ("D", "four/")))

    def test_an_item_goes_to_the_pool_agent_with_the_most_room(self):
        self.probe_out = {"main": ev(0.50), "spare": ev(0.20)}
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        self.assertEqual(sorted(self.probes), ["main", "spare"])
        self.assertEqual((self.launched[0]["key"], self.launched[0]["name"]), ("repo/one#1", "spare"))
        self.assertEqual(self.inst("main")["usage"]["five_hour"], 0.5)
        self.assertEqual(self.inst("main")["usage"]["five_hour_resets"], R)
        # the next item goes to main: spare has no learned cost yet, so it runs one worker
        self.assertEqual(self.launched[1]["name"], "main")
        self.sup.tick()
        self.assertEqual(sorted(self.probes), ["main", "spare"])  # at most one probe per agent per USAGE_STALE

    def test_nothing_fits_waits_with_a_note_then_a_reset_soon_fits(self):
        self.probe_out = {"main": ev(0.82), "spare": ev(0.85)}
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        self.assertEqual(self.launched, [])
        self.assertEqual(self.items()["repo/one#1"]["note"],
                         "waits: main 82% used, needs about 15%; resets 04:20 · spare 85% used, needs about 15%; "
                         "resets 04:20")
        # ten minutes before the reset the readings are refreshed: a ticket needs little of what is left
        self.clock.t = R - 600
        self.sup.tick()
        self.assertEqual(sorted(self.probes), ["main", "main", "spare", "spare"])
        self.assertEqual((self.launched[0]["key"], self.launched[0]["name"]), ("repo/one#1", "main"))

    def test_an_items_own_agent_wins_and_never_falls_back_to_the_pool(self):
        self.probe_out = {"main": ev(0.85), "spare": ev(0.10)}
        self.mode = "hang"
        self.hub.tickets()
        self.hub.queue_item_agent("repo/one#1", "main")
        self.hub.queue_pause(False)
        self.sup.tick()
        self.assertNotIn("repo/one#1", [x["key"] for x in self.launched])
        self.assertEqual(self.items()["repo/one#1"]["note"], "waits: main 85% used, needs about 15%; resets 04:20")

    def test_the_weekly_gate_holds_an_agent_with_room_in_its_window(self):
        self.probe_out = {"main": ev(0.10, week=0.85), "spare": ev(0.80)}
        self.resume()
        self.sup.tick()
        self.assertEqual(self.launched, [])
        note = self.items()["repo/one#1"]["note"]
        self.assertIn("main used 85% of its week; resets Tue 04:20", note)
        self.assertIn("spare 80% used, needs about 15%", note)

    def test_the_first_ticket_runs_alone_its_cost_is_learned_and_replaces_the_default(self):
        self.hub.queue_agents(["main"], None)
        self.probe_out = {"main": ev(0.65)}
        self.agent_env = {"main": {"FAKE_WORKER_USAGE": "0.65>0.77", "FAKE_WORKER_RESET": str(int(R))}}
        self.mode = "hang"
        self.hub.tickets()
        first = list(self.items())[0]
        self.modes = {first: "commit"}
        self.hub.queue_pause(False)
        self.sup.tick()
        self.sup.tick()
        self.assertEqual(list(self.running()), [first])  # no learned cost yet: one worker
        self.agent_env = {}
        self.until(lambda: self.state_of(first) == "done")
        self.assertEqual(self.inst("main")["costs"], {"sonnet": {"avg": 0.12, "n": 1}})
        self.assertEqual(self.inst("main")["usage"]["five_hour"], 0.77)
        # 77% + the learned 12% fits under 90% (the default 15% would not); a third would not fit
        self.until(lambda: len(self.running()) == 1)
        self.sup.tick()
        self.assertEqual(len(self.running()), 1)
        waiting = [i for i in self.items().values() if i["state"] == "queued" and i["note"].startswith("waits")]
        self.assertTrue(waiting)
        self.assertIn("main 77% used, 12% more held by its running work, needs about 12%", waiting[0]["note"])

    def test_two_workers_per_agent_at_most_and_one_per_repo(self):
        self.hub.queue_agents(["main"], None)
        with self.hub._lock:
            self.hub._data["installed"]["main"]["costs"] = {"sonnet": {"avg": 0.05, "n": 3}}
        self.probe_out = {"main": ev(0.10)}
        self.mode = "hang"
        self.resume()
        for _ in range(3):
            self.sup.tick()
        run = self.running()
        self.assertEqual(len(run), sbhub.MAX_PER_AGENT)
        self.assertEqual({i["runner"] for i in run.values()}, {"main"})
        self.assertEqual(len({i["repo"] for i in run.values()}), len(run))
        self.assertTrue(all(i["note"] == "" for i in self.items().values() if i["state"] == "queued"))  # busy only


class StopsTest(PacingCase):
    def test_a_logout_requeues_the_ticket_asks_the_owner_once_and_a_probe_clears_it(self):
        self.hub.queue_agents(["main"], None)
        self.probe_out = {"main": ev(0.10)}
        self.agent_modes = {"main": "auth"}
        self.resume()
        self.until(lambda: self.inst("main").get("login") == "expired")
        item = self.items()["repo/one#1"]
        self.assertEqual((item["state"], item["tries"]), ("queued", 0))
        self.assertIn("main is signed out", item["note"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")
        row = self.hub.state()["agents"]["sign-in:main"]
        self.assertEqual(row["state"], "needs you")
        self.assertIn("run `CLAUDE_CONFIG_DIR={} claude`, type /login".format(self.root / ".claude-main"), row["note"])
        self.agent_modes = {"main": "hang"}
        self.clock.t += 60
        for _ in range(3):
            self.sup.tick()
        self.assertEqual(len(self.launched), 1)  # a signed-out agent takes nothing
        self.assertEqual(self.hub.state()["agents"]["sign-in:main"]["at"], row["at"])  # asked once, not per tick
        self.clock.t = START + sbhub.USAGE_STALE
        self.sup.tick()  # the probe signs it back in; the ticket starts again
        self.assertIsNone(self.inst("main")["login"])
        self.assertNotIn("sign-in:main", self.hub.state()["agents"])
        self.assertEqual([x["name"] for x in self.launched], ["main", "main"])
        self.assertIn("An earlier try on main stopped when its login expired", self.launched[1]["brief"])

    def test_a_probe_that_shows_a_logout_marks_the_agent(self):
        self.hub.queue_agents(["main"], None)
        self.probe_out = {"main": '{"type":"assistant","error":"authentication_failed"}\n'}
        self.resume()
        self.sup.tick()
        self.assertEqual(self.inst("main")["login"], "expired")
        self.assertEqual(self.launched, [])
        self.assertIn("main is signed out", self.items()["repo/one#1"]["note"])

    def test_a_limit_mid_ticket_resumes_on_the_other_agent_from_its_first_base(self):
        base = git(self.repos["repo/one"], "rev-parse", "HEAD")
        self.probe_out = {"main": ev(0.10), "spare": ev(0.40)}
        reset = START + 3 * 3600
        self.agent_modes = {"main": "limit"}
        self.agent_env = {"main": {"FAKE_WORKER_RESET": str(int(reset))}}
        self.partial = "main"
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "done")
        self.assertEqual([x["name"] for x in self.launched[:2]], ["main", "spare"])
        self.assertEqual(self.inst("main")["limited_until"], reset)  # the rejected window's reset, not "4:40am"
        brief = self.launched[1]["brief"]
        self.assertIn("An earlier try on main stopped at its usage limit.", brief)
        self.assertIn("read `git log {}..HEAD` and `git diff -- one/` first".format(base), brief)
        self.assertIn("Its log: {}.".format(self.launched[0]["log"]), brief)
        item = self.items()["repo/one#1"]
        self.assertEqual(git(self.repos["repo/one"], "rev-parse", item["commit"] + "~2"), base)  # wip, then the ticket's
        self.assertEqual(item["base_sha"], base)
        self.assertEqual(self.items()["repo/one#1"]["tries"], 0)

    def test_the_brake_tells_a_worker_once_when_its_account_passes_95(self):
        self.hub.queue_agents(["main"], None)
        self.probe_out = {"main": ev(0.10)}
        self.agent_env = {"main": {"FAKE_WORKER_USAGE": "0.96>0.97", "FAKE_WORKER_RESET": str(int(R))}}
        self.mode = "hang"
        self.resume()
        self.sup.tick()
        self.hub.report({"agent": "repo/one#1", "role": "worker", "parent": "queue", "state": "working"})
        sent = lambda: [m for m in self.hub.state()["messages"].values() if m["to"] == "repo/one#1"]
        self.until(sent)
        for _ in range(3):
            self.sup.tick()
        self.assertEqual([m["text"] for m in sent()], [sbhub.BRAKE_TEXT])

    def test_a_job_with_usage_lines_keeps_its_result_and_teaches_a_cost(self):
        self.hub.queue_agents(["main"], None)
        self.probe_out = {"main": ev(0.10)}
        self.agent_env = {"main": {"FAKE_WORKER_USAGE": "0.10>0.18", "FAKE_WORKER_RESET": str(int(R))}}
        key = self.hub.queue_job("repo", "Audit it", None, "sonnet", "audit")["key"]
        self.hub.tickets()
        self.hub.queue_set([], self.hub.state()["queue"]["version"])
        self.hub.queue_pause(False)
        self.until(lambda: self.state_of(key) == "done")
        self.assertEqual(Path(self.items()[key]["result"]).read_text(encoding="utf-8").strip(), "did: Audit it")
        self.assertEqual(self.inst("main")["costs"]["sonnet"], {"avg": 0.08, "n": 1})


class ReadingTest(unittest.TestCase):
    def test_readings_and_what_the_agent_said(self):
        text = ("noise\n" + ev(0.3) + '{"type":"user","message":"a tool read: You have hit your session limit"}\n'
                + ev(1, status="rejected") + '{"type":"result","is_error":true,"result":"done"}\n')
        got = sbhub.readings(text)
        self.assertEqual([u["five_hour"] for u, _ in got], [0.3, 1.0])
        self.assertEqual([r for _, r in got], [None, R])
        self.assertEqual(got[0][0]["seven_day"], 0.1)
        said = sbhub._said(text)
        self.assertNotIn("session limit", said)  # tool output is not the agent hitting a limit
        self.assertIn("done", said)
        self.assertTrue(sbhub.logged_out(sbhub._said('{"type":"assistant","error":"authentication_failed"}')))

    def test_a_cost_falls_back_to_the_other_tier_then_the_default(self):
        self.assertEqual(sbhub._cost({}, "opus"), (0.30, False))
        self.assertEqual(sbhub._cost({"costs": {"sonnet": {"avg": 0.1, "n": 1}}}, "opus"), (0.2, True))
        self.assertEqual(sbhub._cost({"costs": {"opus": {"avg": 0.4, "n": 1}}}, "sonnet"), (0.2, True))


class FixRoundOneTest(PacingCase):
    def setup_main(self, **usage):
        with self.hub._lock:
            inst = self.hub._data["installed"]["main"]
            inst["usage"] = {"five_hour": 0.5, "five_hour_resets": R, "seven_day": 0.1,
                             "seven_day_resets": R + 86400, "at": START, **usage}
            inst["costs"] = {"sonnet": {"avg": 0.30, "n": 2}}
        return inst

    def test_only_a_worker_that_ran_alone_is_credited_with_the_rise(self):
        self.setup_main()
        running = [{"key": "a", "runner": "main", "model": "sonnet"}, {"key": "b", "runner": "main", "model": "sonnet"}]
        self.addCleanup(setattr, self.sup, "procs", {})  # fake runs: nothing for stop() to kill
        u0 = {"five_hour": 0.10, "five_hour_resets": R}
        self.sup.procs = {"a": {"agent": "main", "u0": u0, "alone": False},
                          "b": {"agent": "main", "u0": u0, "alone": False}}
        self.assertEqual(self.sup._load(running), {"main": [2, 0.60]})  # overlapped: each still owes its full cost
        self.sup.procs = {"a": {"agent": "main", "u0": {"five_hour": 0.40, "five_hour_resets": R}, "alone": True}}
        n, owed = self.sup._load(running[:1])["main"]
        self.assertEqual(n, 1)
        self.assertAlmostEqual(owed, 0.20)

    def test_a_failed_run_teaches_no_cost_and_a_cost_has_a_floor(self):
        self.hub.queue_agents(["main"], None)
        self.sb("set", "repo/one", "001", "tier=opus", "--no-sync")
        self.probe_out = {"main": ev(0.10)}
        self.agent_env = {"main": {"FAKE_WORKER_USAGE": "0.10>0.11", "FAKE_WORKER_RESET": str(int(R))}}
        self.modes = {"repo/one#1": "nothing", "repo/one#2": "hang"}
        self.resume()
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        self.assertNotIn("costs", self.inst("main"))
        self.assertEqual(sbhub._cost({"costs": {"sonnet": {"avg": 0.01, "n": 1}}}, "sonnet"), (0.05, True))
        self.assertEqual(sbhub._cost({"costs": {"sonnet": {"avg": 0.01, "n": 1}}}, "opus"), (0.10, True))

    def test_quoted_limit_text_is_not_a_stop(self):
        log = self.root / "cut.log"
        log.write_text('{"type":"user","x":"' + "a" * 200 + ' usage limit reached, resets 4:40am ' + "b" * 200 + '"}\n'
                       '{"type":"result","is_error":true,"result":"gave up"}\n')
        self.assertNotIn("usage limit", sbhub._tail(str(log), 0, size=300))  # the cut first line is dropped
        self.assertIn("gave up", sbhub._tail(str(log), 0, size=300))
        ok = '{"type":"result","is_error":false,"result":"fixed how the hub reads Failed to authenticate"}'
        self.assertFalse(sbhub.logged_out(sbhub._said(ok)))
        self.assertIsNone(sbhub.limited_until(sbhub._said(ok.replace("Failed to authenticate", "usage limit reached")),
                                              START))

    def test_an_item_that_stops_three_times_fails_in_plain_words(self):
        self.probe_out = {"main": ev(0.10), "spare": ev(0.20)}
        self.agent_modes = {"main": "limit", "spare": "limit"}
        env = {"FAKE_WORKER_RESET": str(int(START + 3600))}
        self.agent_env = {"main": env, "spare": env}
        self.resume()
        self.until(lambda: len(self.launched) == 2 and self.state_of("repo/one#1") == "queued")
        self.clock.t = START + 3601
        self.until(lambda: self.state_of("repo/one#1") == "failed")
        self.assertEqual([x["key"] for x in self.launched].count("repo/one#1"), 3)
        self.assertIn("stopped 3 times at a usage limit or a logout", self.items()["repo/one#1"]["note"])
        self.assertEqual(self.open_tickets()[1]["status"], "open")

    def test_a_big_cost_is_capped_and_an_idle_nearly_empty_account_always_takes_the_item(self):
        inst = {"kind": "claude", "costs": {"sonnet": {"avg": 0.5, "n": 1}},
                "usage": {"five_hour": 0.0, "five_hour_resets": R, "seven_day": 0.1, "seven_day_resets": R + 86400,
                          "at": START}}
        score, need, why = sbhub.Supervisor._fit("main", inst, "opus", {}, START)
        self.assertEqual((need, why), (sbhub.NEED_CAP, ""))
        self.assertIsNotNone(score)
        inst["usage"]["five_hour"] = 0.09
        with mock.patch.object(sbhub, "NEED_CAP", 2.0):
            self.assertIsNotNone(sbhub.Supervisor._fit("main", inst, "opus", {}, START)[0])
            inst["usage"]["five_hour"] = 0.10
            self.assertIsNone(sbhub.Supervisor._fit("main", inst, "opus", {}, START)[0])

    def test_a_resumed_item_that_cannot_start_keeps_its_repo(self):
        self.probe_out = {"main": ev(0.10), "spare": ev(0.70)}
        self.hub.tickets()
        with self.hub._lock:
            self.hub._data["installed"]["main"]["limited_until"] = R
            self.hub._data["queue"]["items"][0].update(
                tries=1, model="opus", resume={"agent": "main", "log": "x.log", "why": "at its usage limit"})
        self.hub.queue_pause(False)
        self.sup.tick()
        self.assertEqual(self.launched, [])  # the sonnet ticket behind it would fit on spare, but waits

    def test_an_old_or_reset_less_reading_counts_as_none(self):
        base = {"kind": "claude", "costs": {"sonnet": {"avg": 0.05, "n": 1}}}
        fresh = {"five_hour": 0.85, "five_hour_resets": R, "seven_day": 0.1, "seven_day_resets": R + 86400}
        old = {**base, "usage": {**fresh, "five_hour": 0.1, "at": START - 1801}}
        self.assertIsNone(sbhub.Supervisor._fit("main", old, "sonnet", {"main": [1, 0.05]}, START)[0])  # one worker
        self.assertIsNotNone(sbhub.Supervisor._fit("main", old, "sonnet", {}, START)[0])
        bare = {**base, "usage": {**fresh, "five_hour_resets": None, "at": START}}
        self.assertEqual(sbhub.Supervisor._fit("main", bare, "sonnet", {}, START), ((0, 0.0), 0.0, ""))

    def test_the_brake_for_a_job_names_no_trailer(self):
        self.hub.queue_agents(["main"], None)
        self.probe_out = {"main": ev(0.10)}
        self.agent_env = {"main": {"FAKE_WORKER_USAGE": "0.96>0.97", "FAKE_WORKER_RESET": str(int(R))}}
        self.mode = "hang"
        key = self.hub.queue_job("repo", "Audit it", None, "sonnet", "audit")["key"]
        self.hub.tickets()
        self.hub.queue_set([], self.hub.state()["queue"]["version"])
        self.hub.queue_pause(False)
        self.sup.tick()
        self.hub.report({"agent": key, "role": "worker", "parent": "queue", "state": "working"})
        sent = lambda: [m["text"] for m in self.hub.state()["messages"].values() if m["to"] == key]
        self.until(sent)
        self.assertEqual(sent(), ["Usage is at 95%: commit what passes now, write your result, and stop."])


class PoolTest(PacingCase):
    def test_the_pool_reads_an_old_single_agent_and_is_set_versioned_through_the_cli(self):
        self.assertEqual(sbhub.pool({"agent": "main"}), ["main"])
        self.assertEqual(sbhub.pool({"agent": None}), [])
        with self.assertRaises(ValueError):
            self.hub.queue_agents(["main", "nope"], None)
        v = self.hub.state()["queue"]["version"]
        self.assertTrue(self.hub.queue_agents(["spare"], v + 5)["stale"])
        self.hub.queue_agent("main")  # the page's one agent is a pool of one
        self.assertEqual(self.hub.state()["queue"]["agents"], ["main"])
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), sbhub.make_handler(self.hub))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        r = subprocess.run([sys.executable, SCRIPT, "queue", "agents", "spare", "main", "--port",
                            str(server.server_address[1])], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        q = self.hub.state()["queue"]
        self.assertEqual((q["agents"], q["agent"]), (["spare", "main"], "spare"))
        r = subprocess.run([sys.executable, SCRIPT, "queue", "--port", str(server.server_address[1])],
                           capture_output=True, text=True, timeout=60)
        self.assertIn("agents spare, main", r.stdout)


if __name__ == "__main__":
    unittest.main()
