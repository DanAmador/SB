"""One hub runs the queue per home (flock on queue.lock), and the worker's git guard hook."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HubCase, free_port, SCRIPT

ROOT = Path(__file__).resolve().parents[1] / "skills" / "sb"
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import guard_git  # noqa: E402
import sbhub  # noqa: E402


class QueueLockTest(HubCase):
    ts = False

    def test_first_hub_holds_the_lock(self):
        self.assertEqual(self.get("/api/state")["queue_lock"]["mine"], True)

    def test_a_second_hub_on_one_home_serves_read_only_and_starts_nothing(self):
        port = free_port()
        env = {**self.env, "SB_HUB_QUEUE": "1"}  # even asked to run the queue, it must not
        p = subprocess.Popen([sys.executable, SCRIPT, "serve", "--port", str(port)], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), f"sb hub on http://127.0.0.1:{port}")
        code, state = sbhub.call(port, "/api/state")
        self.assertEqual(code, 200)
        self.assertFalse(state["queue_lock"]["mine"])
        self.assertIn(f"pid {self.server.pid}", state["queue_lock"]["holder"])
        code, out = sbhub.call(port, "/api/queue/pause", {"paused": False})
        self.assertEqual(code, 409)
        self.assertIn("read-only", out["error"])
        self.assertTrue(sbhub.call(port, "/api/state")[1]["queue"]["paused"])

    def test_the_lock_frees_when_its_holder_ends(self):
        home = tempfile.mkdtemp()
        f, who = sbhub.take_queue_lock(home)
        self.assertIsNone(who)
        g, who = sbhub.take_queue_lock(home)
        self.assertIsNone(g)
        self.assertIn("pid", who)
        f.close()
        g, who = sbhub.take_queue_lock(home)
        self.assertIsNone(who)
        g.close()


class GuardTest(unittest.TestCase):
    def run_hook(self, command, cwd="/nonexistent-dir"):
        r = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard_git.py")], capture_output=True, text=True,
                           input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}))
        self.assertEqual(r.returncode, 0)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout else None

    def test_refuses_git_stash_and_names_the_way_out(self):
        out = self.run_hook("pnpm test; git stash; pnpm test; git stash pop")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("git worktree add", out["permissionDecisionReason"])

    def test_allows_git_worktree_add(self):
        self.assertIsNone(self.run_hook("git worktree add --detach /tmp/clean HEAD"))
        self.assertIsNone(self.run_hook("git status && git log -3 && git diff"))

    def test_refuses_what_rewrites_the_main_checkout(self):
        for c in ("git checkout -- src/a.ts", "git checkout main", "git restore .", "git reset --hard HEAD~1",
                  "git switch other", "git rebase main", "git -C /repo stash apply", "FOO=1 git stash"):
            self.assertEqual(self.run_hook(c)["permissionDecision"], "deny", c)

    def test_allows_staged_restore_but_a_reset_of_any_kind_is_refused_in_main(self):
        self.assertEqual(self.run_hook("git reset --soft HEAD~1")["permissionDecision"], "deny")  # the ticket: any reset
        self.assertIsNone(self.run_hook("git restore --staged a.py"))

    def test_a_linked_worktree_may_check_out_but_never_stash(self):
        with tempfile.TemporaryDirectory() as d:
            main, tree = Path(d, "main"), Path(d, "tree")
            for c in (["init", "-q", str(main)],):
                subprocess.run(["git", *c], check=True)
            subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                            "--allow-empty", "-m", "x"], check=True)
            subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "--detach", str(tree)], check=True)
            self.assertIsNone(self.run_hook("git checkout -- .", cwd=str(tree)))
            self.assertEqual(self.run_hook("git checkout -- .", cwd=str(main))["permissionDecision"], "deny")
            self.assertEqual(self.run_hook("git stash", cwd=str(tree))["permissionDecision"], "deny")


class WorkerGetsTheGuardTest(unittest.TestCase):
    def test_launch_passes_the_hook_and_the_rule(self):
        seen = {}
        real = subprocess.Popen
        subprocess.Popen = lambda cmd, **kw: seen.update(cmd=cmd) or type("P", (), {})()
        try:
            sbhub.launch({"kind": "claude"}, "do it", tempfile.gettempdir(), "sonnet", {}, tempfile.mktemp())
        finally:
            subprocess.Popen = real
        cmd = seen["cmd"]
        settings = json.loads(cmd[cmd.index("--settings") + 1])
        self.assertIn("guard_git.py", settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
        self.assertIn("git worktree add", cmd[cmd.index("-p") + 1])


if __name__ == "__main__":
    unittest.main()
