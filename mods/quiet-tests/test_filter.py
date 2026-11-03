"""Run: python3 mods/quiet-tests/test_filter.py  (stdlib only; feeds samples, touches nothing else)"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quiet_tests as q  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NOISE = "\n".join(f"noise line {i}" for i in range(30))

JEST_PASS = f"PASS src/a.test.js\n  console.log\n    {NOISE}\nPASS src/b.test.js\n\n" \
    "Test Suites: 2 passed, 2 total\nTests:       5 passed, 5 total\nSnapshots:   0 total\nTime:        0.9 s\nRan all test suites.\n"
JEST_FAIL = f"PASS src/a.test.js\n  console.log\n    {NOISE}\nFAIL src/b.test.js\n  ● adds › works\n\n" \
    "    expect(received).toBe(expected)\n\n    Expected: 3\n    Received: 2\n\n      at Object.<anonymous> (src/b.test.js:3:17)\n\n" \
    "PASS src/c.test.js\n\nTest Suites: 1 failed, 2 passed, 3 total\nTests:       1 failed, 4 passed, 5 total\nTime:        0.9 s\nRan all test suites.\n"
VITEST_PASS = f" ✓ src/a.test.ts (2 tests) 3ms\n{NOISE}\n ✓ src/b.test.ts (1 test) 2ms\n\n Test Files  2 passed (2)\n      Tests  3 passed (3)\n   Duration  400ms\n"
VITEST_FAIL = f" ✓ src/a.test.ts (2 tests) 3ms\n{NOISE}\n ❯ src/b.test.ts (1 test | 1 failed) 5ms\n   × fails 2ms\n\n" \
    "⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯\n\n FAIL  src/b.test.ts > fails\nAssertionError: expected 1 to be 2\n ❯ src/b.test.ts:3:17\n\n" \
    "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n Test Files  1 failed | 1 passed (2)\n      Tests  1 failed | 2 passed (3)\n   Duration  400ms\n"
NX_FAIL = f"> nx run web:test\n\nweb:test: PASS src/a.test.js\nweb:test: {NOISE.splitlines()[0]}\nweb:test: FAIL src/b.test.js\nweb:test:   ● adds › works\nweb:test: \nweb:test:     expect(received).toBe(expected)\n\n" \
    " NX   Running target test for 2 projects failed\n\n   Failed tasks:\n\n   - web:test\n"
UNIT_PASS = f"{NOISE}\ntest_a (t.T) ... ok\n----------------------------------------------------------------------\nRan 3 tests in 0.001s\n\nOK\n"
UNIT_FAIL = f"{NOISE}\ntest_a (t.T) ... ok\ntest_b (t.T) ... FAIL\n\n======================================================================\nFAIL: test_b (t.T)\n" \
    "----------------------------------------------------------------------\nTraceback (most recent call last):\n  File \"t.py\", line 4, in test_b\nAssertionError: 1 != 2\n\n" \
    "----------------------------------------------------------------------\nRan 3 tests in 0.001s\n\nFAILED (failures=1)\n"


def run(runner, text, results=None):
    out = io.StringIO()
    q.run_filter(runner, results, io.StringIO(text), out)
    return out.getvalue()


class Filter(unittest.TestCase):
    def check(self, runner, text, keep, drop):
        out = run(runner, text)
        for k in keep:
            self.assertIn(k, out)
        for d in drop:
            self.assertNotIn(d, out)
        self.assertLess(len(out), len(text))

    def test_jest_pass(self):
        self.check("jest", JEST_PASS, ["Tests:       5 passed", "Test Suites: 2 passed"], ["noise line", "PASS src"])

    def test_jest_fail(self):
        self.check("jest", JEST_FAIL, ["FAIL src/b.test.js", "● adds › works", "Expected: 3", "Tests:       1 failed"],
                   ["noise line", "PASS src"])

    def test_vitest_pass(self):
        self.check("vitest", VITEST_PASS, ["Tests  3 passed"], ["noise line", "✓"])

    def test_vitest_fail(self):
        self.check("vitest", VITEST_FAIL, ["FAIL  src/b.test.ts > fails", "expected 1 to be 2", "Tests  1 failed"],
                   ["noise line", "✓"])

    def test_nx_fail(self):
        self.check("nx", NX_FAIL, ["FAIL src/b.test.js", "● adds", "Failed tasks:", "- web:test", "Running target test"],
                   ["PASS src", "noise line"])

    def test_unittest_pass(self):
        self.check("unittest", UNIT_PASS, ["Ran 3 tests", "OK"], ["noise line", "... ok"])

    def test_unittest_fail(self):
        self.check("unittest", UNIT_FAIL, ["FAIL: test_b", "AssertionError: 1 != 2", "FAILED (failures=1)", "Ran 3 tests"],
                   ["noise line", "test_a"])

    def test_crash_shows_tail(self):
        out = run("jest", "\n".join(f"line {i}" for i in range(100)) + "\nCannot find module 'x'\n")
        self.assertIn("Cannot find module 'x'", out)
        self.assertNotIn("line 10\n", out)

    def test_dup_failure_summary_not_repeated(self):
        text = JEST_FAIL.replace("Test Suites:", "Summary of all failing tests\nFAIL src/b.test.js\n  ● adds › works\n\nTest Suites:", 1)
        self.assertEqual(run("jest", text).count("● adds › works"), 1)


XML = """<test-run id="2" total="3" passed="{p}" failed="{f}" skipped="0" inconclusive="0" duration="0.5">
<test-suite><test-case fullname="Ns.T.Ok" result="Passed"/>
<test-case fullname="Ns.T.Ok2" result="Passed"/>
{case}</test-suite></test-run>"""
BAD = '<test-case fullname="Ns.T.Bad" result="Failed"><failure><message><![CDATA[Expected 1 but was 2]]></message><stack-trace><![CDATA[at Ns.T.Bad () in T.cs:12]]></stack-trace></failure></test-case>'


class Unity(unittest.TestCase):
    def xml(self, text):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "r.xml")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_failures_and_counts(self):
        out = run("unity", NOISE, self.xml(XML.format(p=2, f=1, case=BAD)))
        self.assertIn("total 3, passed 2, failed 1", out)
        self.assertIn("FAIL Ns.T.Bad", out)
        self.assertIn("Expected 1 but was 2", out)
        self.assertNotIn("noise line", out)
        self.assertNotIn("Ns.T.Ok", out)

    def test_pass(self):
        out = run("unity", NOISE, self.xml(XML.format(p=3, f=0, case="")))
        self.assertIn("passed 3, failed 0", out)
        self.assertNotIn("FAIL", out)

    def test_no_results_falls_back_to_log(self):
        log = NOISE + "\nAssets/A.cs(3,1): error CS1002: ; expected\nAborting batchmode due to failure:\n"
        out = run("unity", log, "/nonexistent/r.xml")
        self.assertIn("error CS1002", out)
        self.assertNotIn("noise line 3\n", out)


def hook(command, tool="Bash"):
    p = subprocess.run([sys.executable, os.path.join(HERE, "quiet_tests.py"), "hook"], capture_output=True, text=True,
                       input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool,
                                         "tool_input": {"command": command, "description": "d", "timeout": 5000}}))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout) if p.stdout.strip() else None


class Hook(unittest.TestCase):
    def test_jest_rewritten(self):
        out = hook("npx jest --ci src/")["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", out)
        self.assertIn("npx jest --ci src/", out["updatedInput"]["command"])
        self.assertIn("pipefail", out["updatedInput"]["command"])
        self.assertIn("filter jest", out["updatedInput"]["command"])
        self.assertEqual(out["updatedInput"]["timeout"], 5000)  # other fields survive

    def test_others_matched(self):
        for cmd, runner in [("pnpm exec vitest run", "vitest"), ("cd app && ./node_modules/.bin/jest", "jest"),
                            ("npx nx affected -t test", "nx"), ("nx test web", "nx"),
                            ("npx nx run-many --target=test --all", "nx"), ("python3 -m unittest -v", "unittest"),
                            ("/Applications/Unity/Unity -batchmode -runTests -testPlatform EditMode -testResults out.xml", "unity")]:
            with self.subTest(cmd):
                out = hook(cmd)
                self.assertIsNotNone(out)
                self.assertIn("filter " + runner, out["hookSpecificOutput"]["updatedInput"]["command"])
        self.assertIn("--results out.xml", hook("Unity -runTests -testResults out.xml")["hookSpecificOutput"]["updatedInput"]["command"])

    def test_passthrough(self):
        for cmd in ["ls", "git status", "npm install --save-dev jest", "echo jest", "npx jest | tail -5", "npx jest > out.txt",
                    "npx jest --watch", "npx jest &", "npx nx build web", "python3 script.py",
                    "npx jest quiet_tests.py"]:
            with self.subTest(cmd):
                self.assertIsNone(hook(cmd))
        self.assertIsNone(hook("jest", tool="Read"))

    def test_garbage_input_is_silent(self):
        p = subprocess.run([sys.executable, os.path.join(HERE, "quiet_tests.py"), "hook"], input="not json", capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (0, ""))


class ExitCode(unittest.TestCase):
    def sh(self, shell, cmd, runner="jest"):
        return subprocess.run([shell, "-c", q.rewrite(cmd, runner)], capture_output=True, text=True)

    def test_exit_code_survives_and_output_is_filtered(self):
        fail = "printf 'noise\\nFAIL src/b.test.js\\n  ● boom\\nTests:       1 failed, 1 total\\n'; echo err >&2; exit 3"
        for shell in ("bash", "zsh"):
            with self.subTest(shell):
                r = self.sh(shell, fail)
                self.assertEqual(r.returncode, 3)
                self.assertIn("● boom", r.stdout)
                self.assertIn("Tests:       1 failed", r.stdout)
                self.assertNotIn("noise\n", r.stdout)

    def test_pass_exit_zero(self):
        r = self.sh("bash", "printf 'noise\\nTests:       2 passed, 2 total\\n'")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("noise\n", r.stdout)

    def test_inner_pipeline_failure_counts(self):
        self.assertEqual(self.sh("bash", "false | cat").returncode, 1)


if __name__ == "__main__":
    unittest.main()
