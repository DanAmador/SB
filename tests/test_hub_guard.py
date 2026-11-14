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


def run_guard(tool, tin, cwd="/nonexistent-dir", env=None):
    r = subprocess.run([sys.executable, str(GUARD)], capture_output=True, text=True,
                       input=json.dumps({"tool_name": tool, "tool_input": tin, "cwd": cwd}),
                       env={**os.environ, **(env or {})})
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

    def test_no_hub_no_failure(self):
        self.assertEqual(bash("git push", env={"SB_HUB_AGENT": "a", "SB_HUB_PORT": "1"})["permissionDecision"], "deny")


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


if __name__ == "__main__":
    unittest.main()
