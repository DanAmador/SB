"""The workers' PreToolUse hook (hooks/guard_git.py): what it refuses, what it lets through, and that a
refusal reaches the hub's trail and the run."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HubCase

ROOT = Path(__file__).resolve().parents[1] / "skills" / "sb"
GUARD = ROOT / "hooks" / "guard_git.py"
SBMAP = "python3 ~/.agents/skills/sb/scripts/sbmap.py"


def hook_env(env=None):
    """The hook's environment: a worker that runs this suite must not make the hook report to its own hub."""
    base = {k: v for k, v in os.environ.items() if k not in ("SB_HUB_AGENT", "SB_HUB_PORT", "SB_HUB_PARENT")}
    return {**base, **(env or {})}


def run_guard(tool, tin, cwd="/nonexistent-dir", env=None):
    r = subprocess.run([sys.executable, str(GUARD)], capture_output=True, text=True,
                       input=json.dumps({"tool_name": tool, "tool_input": tin, "cwd": cwd}),
                       env=hook_env(env))
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout else None


def bash(command, **kw):
    return run_guard("Bash", {"command": command}, **kw)


class RefusedTest(unittest.TestCase):
    def deny(self, out, way):
        self.assertIsNotNone(out)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn(way, out["permissionDecisionReason"])

    def test_sbmap_writes_but_comment(self):
        for sub in ("resolve", "close", "new", "set", "block", "claim", "init", "mapset", "summary"):
            self.deny(bash("{} {} repo/one 1 --by me".format(SBMAP, sub)), "write a comment instead")
        self.deny(bash("cd /x && sbmap close repo/one 1"), "write a comment instead")

    def test_git_that_fakes_or_rewrites_work(self):
        for c, way in (("git commit --allow-empty -m x", "No change needed"), ("git commit -q --amend", "No change needed"),
                       ("git push origin HEAD", "hub pushes"), ("git tag v1", "hub pushes"), ("git -C /x tag -d v1", "hub pushes"),
                       ("git reset --soft HEAD~1", "main checkout"), ("git reset HEAD file", "main checkout")):
            self.deny(bash(c), way)

    def test_a_reset_in_a_linked_worktree_is_not_the_main_checkouts(self):
        with tempfile.TemporaryDirectory() as d:
            main, tree = str(Path(d).resolve() / "main"), str(Path(d).resolve() / "tree")
            for c in (["init", "-q", main], ["-C", main, "commit", "-q", "--allow-empty", "-m", "i"],
                      ["-C", main, "worktree", "add", "-q", "--detach", tree]):
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + c, check=True, capture_output=True)
            self.deny(bash("git reset HEAD", cwd=main), "main checkout")
            self.assertIsNone(bash("git reset HEAD", cwd=tree))

    def test_rm_mv_and_redirects_inside_dot_git(self):
        for c in ("rm .git/index.lock", "rm -f /repo/.git/index.lock", "mv .git/HEAD /tmp/h", "echo x > .git/index.lock",
                  "echo x>>/r/.git/config", "cd r && rm -rf .git"):
            self.deny(bash(c), "git's own files")

    def test_write_and_edit_outside_the_workers_places(self):
        with tempfile.TemporaryDirectory() as d:
            d = str(Path(d).resolve())
            repo, run = Path(d) / "repo", Path(d) / "run"
            repo.mkdir()
            run.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            env = {"SB_HUB_RUN": str(run)}
            for tool in ("Write", "Edit"):
                # (the temp folder holds the throwaway repo, so "outside" is looked for elsewhere)
                for path in (os.path.expanduser("~/x.txt"), "/etc/x", "../../../../../../../etc/x",
                             "~/Documents/Second Brain/wayfinder/x.md".replace("~", os.path.expanduser("~"))):
                    self.deny(run_guard(tool, {"file_path": path}, cwd=str(repo), env=env), "instead")
                for path in (str(repo / "a.py"), "a.py", str(run / "7.md"), os.path.join(tempfile.gettempdir(), "t.txt"),
                             "/tmp/clean-tree/x"):
                    self.assertIsNone(run_guard(tool, {"file_path": path}, cwd=str(repo), env=env), path)


class AllowedTest(unittest.TestCase):
    def test_what_a_worker_may_keep_doing_gets_no_output(self):
        for c in ("{} show repo/one 1".format(SBMAP), "{} comment repo/one 1 --text 'R: x'".format(SBMAP),
                  "{} link repo/one 1".format(SBMAP), "{} uri repo/one 1".format(SBMAP),
                  "git add a.py", "git commit -m 'feat: x'", "git worktree add --detach /tmp/c HEAD",
                  "git worktree remove --force /tmp/c", "git diff", "git log -3", "git status", "git tag -l",
                  "git tag", "ls .github && cat .gitignore", "echo x > /tmp/a.txt", "rm /tmp/a.txt", "mv a.py b.py",
                  "pnpm test 2>&1 | tail"):
            self.assertIsNone(bash(c), c)

    def test_other_tools_are_left_alone(self):
        self.assertIsNone(run_guard("Read", {"file_path": "/etc/hosts"}))
        self.assertIsNone(run_guard("Grep", {"pattern": "x"}))


INTEGRATOR = {"SB_HUB_UNITY": "integrator"}
# Lines copied verbatim from real sk4te integrator logs (wayfinder/sk4te/runs/*/*-integrate.log).
REAL_POLLS = (
    "cat /tmp/c1290b.txt; cd /Users/danamador/Documents/Coding/sk4te; unity command recompile_status --format json | head -30",
    "cd /Users/danamador/Documents/Coding/sk4te; unity command recompile --format json | head -30; for i in $(seq 1 40); do s=$(unity command recompile_status --format json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(json.dumps(d[\"data\"][\"result\"]))' 2>/dev/null); echo \"$s\"; echo \"$s\" | grep -q '\"completed\"' && break; sleep 10; done",
    "cd /Users/danamador/Documents/Coding/sk4te; for i in $(seq 1 40); do s=$(unity command recompile_status --format json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[\"data\"][\"result\"].get(\"status\"))' 2>/dev/null); echo \"$s\"; [ \"$s\" = completed ] && break; sleep 5; done; unity command console --tail 20 --level error",
    "cd /Users/danamador/Documents/Coding/sk4te; sleep 20; unity command editor_status --format json | grep -E 'status|compiling|domainReload'; unity command recompile_status --format json | grep -E '\"status\"|Failed'; unity command console --tail 20 --level error",
    "cd /Users/danamador/Documents/Coding/sk4te; grep -n \"eval\" tools/compile | head; unity command recompile_status 2>&1 | tail -2",
)


class IntegratorPollTest(RefusedTest):
    def test_real_hand_written_polls_are_refused_with_the_way_out(self):
        for c in REAL_POLLS:
            out = bash(c, env=INTEGRATOR)
            self.deny(out, "unity command sb_check")
            self.assertIn("tools/compile", out["permissionDecisionReason"])
            self.assertIn("[CliCommand]", out["permissionDecisionReason"])

    def test_a_loop_or_sleep_next_to_a_unity_command_is_refused(self):
        for c in ("while true; do unity command editor_status; sleep 2; done", "until unity command sb_check; do :; done",
                  "unity command editor_status && sleep 5", "for i in 1 2 3; do unity command console --tail 5; done"):
            self.deny(bash(c, env=INTEGRATOR), "unity command sb_check")

    def test_a_timeout_prefix_does_not_hide_a_poll(self):
        for c in ("timeout 20 unity command recompile_status",
                  "timeout -k 5 30 unity command recompile_status --format json",
                  "for i in 1 2 3 4 5 6; do r=$(timeout 20 unity command editor_status --format json 2>&1); "
                  "[ -n \"$r\" ] && break; done"):  # the last is a real integrator loop from sk4te's logs
            self.deny(bash(c, env=INTEGRATOR), "unity command sb_check")
        out = bash("timeout 60 unity command sb_check", env=INTEGRATOR)
        self.assertFalse(out)

    def test_the_project_checks_stay_allowed_for_an_integrator(self):
        for c in ("unity command sb_check", "tools/compile", "unity command recompile",
                  "unity command editor_status --format json", "cd /x; unity command console --tail 20 --level error",
                  "sleep 5", "for f in a b; do echo $f; done"):
            self.assertIsNone(bash(c, env=INTEGRATOR), c)

    def test_a_worker_and_a_plain_session_are_as_before(self):
        poll = REAL_POLLS[1]
        out = bash(poll, env={"SB_HUB_UNITY": "off"})  # a worker: every unity command, with the worker's own way out
        self.deny(out, "last stage")
        self.assertNotIn("hand-written poll", out["permissionDecisionReason"])
        plain = {k: v for k, v in hook_env().items() if k != "SB_HUB_UNITY"}
        for c in REAL_POLLS:
            r = subprocess.run([sys.executable, str(GUARD)], capture_output=True, text=True, env=plain,
                               input=json.dumps({"tool_name": "Bash", "tool_input": {"command": c}, "cwd": "/nonexistent-dir"}))
            self.assertEqual(r.stdout, "", c)


class RefusalReachesTheTrail(HubCase):
    def test_a_refusal_is_on_the_workers_trail_with_its_label(self):
        env = {"SB_HUB_AGENT": "repo/one#1", "SB_HUB_PORT": str(self.port)}
        out = bash("{} resolve repo/one 1".format(SBMAP), env=env)
        self.assertEqual(out["permissionDecision"], "deny")
        out = bash("git push", env=env)
        acts = self.get("/api/trail?agent=" + "repo/one%231")["actions"]
        self.assertEqual([a["tool"] for a in acts], ["Bash", "Bash"])
        self.assertTrue(all(a["ok"] is False for a in acts))
        self.assertIn("sbmap resolve", acts[0]["label"])

    def test_an_integrators_poll_refusal_is_on_the_trail(self):
        env = {"SB_HUB_AGENT": "repo/one#1", "SB_HUB_PORT": str(self.port), "SB_HUB_UNITY": "integrator"}
        self.assertEqual(bash(REAL_POLLS[0], env=env)["permissionDecision"], "deny")
        acts = self.get("/api/trail?agent=" + "repo/one%231")["actions"]
        self.assertEqual(len(acts), 1)
        self.assertIs(acts[0]["ok"], False)
        self.assertIn("recompile_status", acts[0]["label"])

    def test_no_hub_no_failure(self):
        self.assertEqual(bash("git push", env={"SB_HUB_AGENT": "a", "SB_HUB_PORT": "1"})["permissionDecision"], "deny")


class SuiteSendsNothingToTheWorkersHub(unittest.TestCase):
    def test_a_stub_hub_named_in_the_environment_hears_nothing_from_the_suite(self):
        import http.server
        import threading
        posts = []

        class Stub(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                posts.append(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        live = {"SB_HUB_AGENT": "repo/one#1", "SB_HUB_PORT": str(server.server_address[1]), "SB_HUB_PARENT": "queue"}
        # the guard's own suites, run as a worker would run them: the stub's address is in the test process's environment
        r = subprocess.run([sys.executable, "-m", "unittest", "test_hub_lock.GuardTest", "test_hub_guard.RefusedTest",
                            "test_hub_guard.AllowedTest"], capture_output=True, text=True, cwd=Path(__file__).parent,
                           env={**os.environ, **live})
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertEqual(posts, [])
        # and the control: the hook does post when its own environment names a hub
        self.assertEqual(bash("git push", env=live)["permissionDecision"], "deny")
        self.assertEqual(len(posts), 1)


class RefusalCountsOnTheRun(unittest.TestCase):
    def test_the_queue_item_and_the_run_carry_a_count_and_the_lines(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import sbhub
        import sbruns
        with tempfile.TemporaryDirectory() as d:
            hub = sbhub.Hub(Path(d))
            hub._data["queue"]["items"].append({"key": "repo/one#1", "kind": "ticket", "state": "running"})
            for why in ("`sbmap resolve` is refused for a worker", "`git push` is refused"):
                hub.report({"agent": "repo/one#1", "role": "worker", "parent": "queue",
                            "trail": {"kind": "refused", "tool": "Bash", "label": why}})
            item = hub.state()["queue"]["items"][0]
            self.assertEqual(item["refused"], 2)
            item["state"] = "failed"
            run = sbruns._run(d, "repo/one#1", item, None)
            self.assertEqual(run["refused"], 2)
            self.assertEqual(run["refused_lines"][0], "refused: Bash: `sbmap resolve` is refused for a worker")


class UnityTestRunRefusalTest(RefusedTest):
    """A test run in the live Editor is refused to every hub session: Unity's Test Runner first asks to save modified
    scenes, and that box froze the 2026-11-23 night for 5.5 hours."""
    # copied from the 2026-11-22 night's integrator logs (wayfinder/sk4te/runs/2026-11-22-level-popit/*.log)
    REAL = ("cd /Users/danamador/Documents/Coding/sk4te; unity command run_tests --mode editor --filter MousePickTests "
            "--timeout 300 --format json 2>&1 | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d)'")

    def test_a_test_run_is_refused_to_an_integrator_a_review_and_a_worker(self):
        for env in (INTEGRATOR, {"SB_HUB_AGENT": "review-1"}, {}):
            for c in (self.REAL, "unity test Assets/Tests --mode EditMode", "unity command run_tests",
                      "unity command eval --code 'var api = ScriptableObject.CreateInstance<TestRunnerApi>(); api.Execute(s);'"):
                self.deny(bash(c, env=env), "written and compiles")
                self.deny(bash(c, env=env), "`unity command sb_tests --filter <name>`")  # the way out, by name
        self.deny(bash(self.REAL, env={"SB_HUB_UNITY": "off"}), "last stage")  # a worker: no unity at all, as before

    def test_an_eval_file_that_starts_the_test_runner_is_refused_and_another_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            runner, probe = Path(d) / "run_tests.cs", Path(d) / "probe.cs"
            runner.write_text("var api = UnityEngine.ScriptableObject.CreateInstance<UnityEditor.TestTools.TestRunner.Api.TestRunnerApi>();")
            probe.write_text("return UnityEngine.Application.isPlaying;")
            self.deny(bash("unity command eval_file --file run_tests.cs --format json", cwd=d, env=INTEGRATOR), "save the open scenes")
            self.assertIsNone(bash("unity command eval_file --file {} --format json".format(probe), env=INTEGRATOR))

    def test_reading_test_state_and_the_checks_stay_allowed(self):
        for c in ("unity command test_status --format json", "unity command list_tests --mode EditMode | wc -c",
                  "unity command sb_check", "tools/compile", "unity command sb_tests --filter SbChecksTests",
                  "grep -rn TestRunnerApi Assets/Tests"):
            self.assertIsNone(bash(c, env=INTEGRATOR), c)


if __name__ == "__main__":
    unittest.main()
