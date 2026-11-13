"""sbqueue's rules: classify, order, move, brief, verdict."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbqueue import brief, classify, key, move, order, verdict  # noqa: E402


def T(num, **kw):
    t = {"map": "r/m", "num": num, "title": f"T{num}", "why": "because", "type": "task",
         "status": "open", "priority": "C", "blocked_by": [], "blocked_by_open": [],
         "paths": [], "tier": "sonnet", "has_done_when": True, "done_when": "it works",
         "question": "Do the thing.", "out": "Other things.", "checks": ["true"],
         "repo": "/x", "map_order": num, "claimed_by": None}
    t.update(kw)
    return t


class ClassifyTest(unittest.TestCase):
    def test_rules_and_precedence(self):
        cases = [
            (T(1), set(), "ready"),
            (T(1, status="claimed", claimed_by="sess-9", type="grilling"), set(), "claimed"),
            (T(1, type="grilling", has_done_when=False), set(), "waits for you"),
            (T(1, type="architecture"), set(), "waits for you"),
            (T(1, has_done_when=False, checks=[]), set(), "not ready"),
            (T(1, checks=[]), set(), "not ready"),
            (T(1, blocked_by_open=[2]), set(), "blocked"),
            (T(1, blocked_by_open=[2]), {"r/m#2"}, "ready"),
            (T(1, blocked_by_open=["map x"]), {"r/m#2"}, "blocked"),
        ]
        for t, queued, want in cases:
            self.assertEqual(classify(t, queued)[0], want, t)

    def test_reasons(self):
        self.assertIn("sess-9", classify(T(1, status="claimed", claimed_by="sess-9"), set())[1])
        self.assertEqual(classify(T(1, has_done_when=False), set())[1], "no done-when")
        self.assertEqual(classify(T(1, checks=[]), set())[1], "no check commands")
        self.assertEqual(classify(T(1, blocked_by_open=[3, 2]), set(), [T(3), T(2)])[1], "after T3")
        self.assertEqual(classify(T(1, blocked_by_open=[3]), set())[1], "after ticket 3")
        self.assertEqual(classify(T(1, blocked_by_open=["map x"]), set())[1], "after map x")

    def test_missing_priority_is_c_and_num_may_be_text(self):
        self.assertEqual(key(T("007")), "r/m#7")


class OrderTest(unittest.TestCase):
    def test_blocker_moves_before_dependant(self):
        ts = [T(1, blocked_by_open=[2]), T(2)]
        self.assertEqual(order(ts, ["r/m#1", "r/m#2"]), ["r/m#2", "r/m#1"])

    def test_priority(self):
        ts = [T(1), T(2, priority="S")]
        self.assertEqual(order(ts, ["r/m#1", "r/m#2"]), ["r/m#2", "r/m#1"])

    def test_missing_priority_counts_as_c(self):
        a, b = T(1), T(2, priority="B")
        del a["priority"]
        self.assertEqual(order([a, b], ["r/m#1", "r/m#2"]), ["r/m#2", "r/m#1"])

    def test_more_unblocked_goes_first(self):
        ts = [T(1), T(2), T(3, blocked_by_open=[2]), T(4, blocked_by_open=[2])]
        self.assertEqual(order(ts, [key(t) for t in ts])[0], "r/m#2")

    def test_map_order_breaks_ties(self):
        ts = [T(1, map_order=5), T(2, map_order=1)]
        self.assertEqual(order(ts, ["r/m#1", "r/m#2"]), ["r/m#2", "r/m#1"])

    def test_unqueued_blocker_drops_dependant_and_its_dependants(self):
        ts = [T(1, blocked_by_open=[9]), T(2, blocked_by_open=[1]), T(3), T(4, blocked_by_open=["ref"])]
        self.assertEqual(order(ts, [key(t) for t in ts]), ["r/m#3"])

    def test_cycle_raises(self):
        ts = [T(1, blocked_by_open=[2]), T(2, blocked_by_open=[1])]
        with self.assertRaises(ValueError):
            order(ts, ["r/m#1", "r/m#2"])


class MoveTest(unittest.TestCase):
    def test_cannot_precede_blocker(self):
        ts = [T(1), T(2, blocked_by_open=[1]), T(3)]
        self.assertEqual(move(["r/m#1", "r/m#2", "r/m#3"], "r/m#2", 0, ts), ["r/m#1", "r/m#2", "r/m#3"])

    def test_blocker_cannot_pass_dependant(self):
        ts = [T(1), T(2, blocked_by_open=[1]), T(3)]
        self.assertEqual(move(["r/m#1", "r/m#2", "r/m#3"], "r/m#1", 2, ts), ["r/m#1", "r/m#2", "r/m#3"])

    def test_free_move(self):
        ts = [T(1), T(2), T(3)]
        self.assertEqual(move(["r/m#1", "r/m#2", "r/m#3"], "r/m#3", 0, ts), ["r/m#3", "r/m#1", "r/m#2"])


class BriefTest(unittest.TestCase):
    def test_contents(self):
        t = T(12, paths=["src/a.py", "docs/"], checks=["pytest -q", "ruff ."], why="the why text")
        b = brief(t, "A tool for X.", "/runs/night", "/repo", "main")
        for s in ["the why text", "it works", "src/a.py", "docs/", "pytest -q", "ruff .", "A tool for X.",
                  "Do the thing.", "Other things.", "/repo", "main", "Ticket: r/m/012", "sbmap.py"]:
            self.assertIn(s, b)
        self.assertTrue(b.rstrip().endswith("/runs/night/12.md") or "/runs/night/12.md" in b.splitlines()[-1])
        self.assertNotIn("<", b)
        self.assertNotIn("sbhub", b)

    def test_the_brief_is_the_template_filled(self):
        # the form the owner reads is the form the hub fills: a ticket without paths loses only that line
        b = brief(T(3, paths=[]), "bg", "/runs", "/repo", "main")
        self.assertNotIn("Files you own", b)
        self.assertNotIn("{", b)
        self.assertIn("Leave alone: Other things.", b)
        self.assertEqual(b.splitlines()[0], "Background: bg")

    def test_the_brief_asks_for_pictures_the_worker_looks_at_itself(self):
        b = brief(T(3), "bg", "/runs", "/repo", "main")
        line = next(x for x in b.splitlines() if "/runs/3-media/" in x)
        for s in ("shows on screen", "AGENTS.md or CLAUDE.md", "Playwright", "look at each one yourself",
                  "fix what looks wrong before you commit", ".png", ".mp4", ".webm", "at most 6 files", "8 MB", "20 s",
                  "`## Pictures`", "nothing on screen"):
            self.assertIn(s, line)


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "base.txt").write_text("x")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, files, trailer="Ticket: r/m/005"):
        for f in files:
            p = self.repo / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("y")
        git(self.repo, "add", ".")
        msg = "work" + (f"\n\n{trailer}" if trailer else "")
        git(self.repo, "commit", "-qm", msg)
        return git(self.repo, "rev-parse", "HEAD")

    def t(self, **kw):
        return T(5, paths=["src"], **kw)

    def test_no_commit(self):
        ok, why, sha = verdict(self.t(), self.repo, self.base)
        self.assertEqual((ok, sha), (False, None))
        self.assertTrue(why.startswith("no commit"))

    def test_no_trailer(self):
        self.commit(["src/a.py"], trailer=None)
        ok, why, sha = verdict(self.t(), self.repo, self.base)
        self.assertFalse(ok)
        self.assertIn("Ticket: r/m/005", why)

    def test_outside_paths(self):
        self.commit(["src/a.py", "other/b.py"])
        ok, why, sha = verdict(self.t(), self.repo, self.base)
        self.assertFalse(ok)
        self.assertIn("other/b.py", why)
        self.assertNotIn("src/a.py", why)

    def test_an_untrailered_commit_outside_paths_before_a_good_one_fails(self):
        self.commit(["other/sneaky.py"], trailer=None)
        sha = self.commit(["src/a.py"])
        ok, why, got = verdict(self.t(checks=["true"]), self.repo, self.base)
        self.assertEqual((ok, got), (False, sha))
        self.assertIn("other/sneaky.py", why)
        self.assertNotIn("src/a.py", why)

    def test_a_bad_base_says_so(self):
        self.commit(["src/a.py"])
        ok, why, sha = verdict(self.t(), self.repo, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual((ok, sha), (False, None))
        self.assertFalse(why.startswith("no commit"))
        self.assertIn("0123456789ab", why)

    def test_failing_check(self):
        self.commit(["src/a.py"])
        ok, why, sha = verdict(self.t(checks=["true", "echo boom; exit 3"]), self.repo, self.base)
        self.assertFalse(ok)
        self.assertIn("echo boom; exit 3", why)
        self.assertIn("boom", why)

    def test_timeout_names_command(self):
        self.commit(["src/a.py"])

        def run(*a, **k):
            raise subprocess.TimeoutExpired(a[0], k["timeout"])
        # git calls must still work, so only time out the check
        def sel(cmd, **k):
            if isinstance(cmd, str):
                return run(cmd, **k)
            return subprocess.run(cmd, **k)
        ok, why, sha = verdict(self.t(checks=["sleep 99"]), self.repo, self.base, run=sel)
        self.assertFalse(ok)
        self.assertIn("sleep 99", why)

    def test_pass(self):
        sha = self.commit(["src/a.py"])
        self.assertEqual(verdict(self.t(checks=["true"]), self.repo, self.base)[::2], (True, sha))

    def owned(self, paths, files):
        sha = self.commit(files)
        return verdict(T(5, paths=paths, checks=["true"]), self.repo, self.base)

    def test_a_test_beside_an_owned_file_counts_as_owned(self):
        ok, why, _ = self.owned(["pkg/src/dock/namedLayouts.ts"],
                                ["pkg/src/dock/namedLayouts.ts", "pkg/src/dock/namedLayouts.recovery.test.tsx",
                                 "pkg/src/dock/other.spec.ts"])
        self.assertTrue(ok, why)

    def test_a_test_in_the_packages_test_folder_counts_as_owned(self):
        ok, why, _ = self.owned(["pkg/src/host/plugin.ts"],
                                ["pkg/src/host/plugin.ts", "pkg/test/noSelfOpen.test.ts",
                                 "pkg/src/host/__tests__/plugin.test.ts", "tests/test_plugin.py", "pkg/test/helpers.ts"])
        self.assertTrue(ok, why)

    def test_a_test_beside_a_file_in_an_owned_folder_counts_as_owned(self):
        ok, why, _ = self.owned(["pkg/src/shared/host"], ["pkg/src/shared/host/a.ts", "pkg/src/shared/a.test.ts"])
        self.assertTrue(ok, why)

    def test_a_test_elsewhere_and_a_test_config_stay_outside(self):
        ok, why, _ = self.owned(["pkg/src/host/plugin.ts"],
                                ["pkg/src/host/plugin.ts", "other/src/x.test.ts", "pkg/src/ui/y.test.ts",
                                 "pkg/vitest.config.mts"])
        self.assertFalse(ok)
        for f in ("other/src/x.test.ts", "pkg/src/ui/y.test.ts", "pkg/vitest.config.mts"):
            self.assertIn(f, why)
        self.assertNotIn("plugin.ts", why)

    def test_no_paths_allows_any_file(self):
        sha = self.commit(["anywhere/x.py"])
        ok, _, got = verdict(T(5, paths=[]), self.repo, self.base)
        self.assertEqual((ok, got), (True, sha))


if __name__ == "__main__":
    unittest.main()
