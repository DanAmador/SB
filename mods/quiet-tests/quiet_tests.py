#!/usr/bin/env python3
"""Keep test output down to failures and totals, for agent Bash calls only.

  quiet_tests.py hook                         PreToolUse hook: JSON on stdin, rewrite on stdout
  quiet_tests.py filter RUNNER [--results F]  stdin -> failures + totals on stdout (always exit 0)

The hook wraps a recognised test command as `( set -o pipefail; { CMD } 2>&1 | filter )`, so the
command's exit code survives the pipe and the owner's own terminal is never touched.
"""
import json
import os
import re
import shlex
import sys
import time

# ---------------------------------------------------------------- detection

_PREFIX = r"(?:^|[;&|(]\s*|\n\s*)(?:\w+=\S*\s+)*"
_LAUNCH = (r"(?:(?:npx|bunx|yarn(?:\s+exec)?|pnpm(?:\s+(?:exec|dlx))?|npm\s+exec)"
           r"(?:\s+--?[\w-]+)*\s+(?:--\s+)?|(?:\S*/)?)")
_JS = re.compile(_PREFIX + _LAUNCH + r"(jest|vitest)(?=\s|$)")
_NX = re.compile(r"\bnx\s+(?:(?:affected|run-many)\b[^|;&\n]*?(?:-t|--target)[\s=]+test\b|test\b)"
                 r"|\bnx\s+affected:test\b")
_UNITTEST = re.compile(r"\bpython[\d.]*\s+(?:-\S+\s+)*-m\s+unittest\b")
_UNITY = re.compile(r"(?:^|\s)-runTests\b")
_RESULTS = re.compile(r"-testResults\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))")
_PIPE = re.compile(r"(?<!\|)\|(?!\|)")
_REDIRECT = re.compile(r"(?:^|\s)\d?>>?\s*[^&\s]")
_WATCH = re.compile(r"--watch(?:All)?(?:\s|$)")
_BG = re.compile(r"[^&]&\s*$")


def detect(command):
    """Return (runner, results_path) for a test run to filter, else None."""
    if "quiet_tests.py" in command or _PIPE.search(command) or _REDIRECT.search(command) \
            or _WATCH.search(command) or _BG.search(command):
        return None
    if _UNITY.search(command):
        m = _RESULTS.search(command)
        return "unity", next((g for g in m.groups() if g), None) if m else None
    if _NX.search(command):
        return "nx", None
    m = _JS.search(command)
    if m:
        return m.group(1), None
    if _UNITTEST.search(command):
        return "unittest", None
    return None


def rewrite(command, runner, results=None):
    me = shlex.quote(os.path.abspath(__file__))
    extra = " --results " + shlex.quote(results) if results else ""
    return f"( set -o pipefail; {{\n{command}\n}} 2>&1 | python3 {me} filter {runner}{extra} )"


def hook(stdin):
    try:
        data = json.load(stdin)
        if data.get("tool_name") != "Bash":
            return None
        tool_input = data["tool_input"]
        hit = detect(tool_input["command"])
        if not hit:
            return None
        new = dict(tool_input, command=rewrite(tool_input["command"], *hit))
        # No permissionDecision: the normal permission flow runs on the rewritten command.
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": new}}
    except Exception:
        return None  # never break a command because the hook failed

# ------------------------------------------------------------------- filter

_JS_SUMMARY = re.compile(r"^\s*(?:Test Suites|Test Files|Tests|Snapshots|Time|Start at|Duration)"
                         r"(?::|\s{2,})|^Ran all test suites|^\s*(?:>\s+)?NX\s|^\s*Failed tasks:|"
                         r"^\s*-\s+\S+:\S+\s*$")
_RULES = {  # runner -> (block start, block end, always-keep summary)
    "js": (re.compile(r"^\s*(?:FAIL\b|●\s|⎯+\s*Failed)"),
           re.compile(r"^\s*(?:PASS\b|✓|⎯+$)"), _JS_SUMMARY),
    "unittest": (re.compile(r"^(?:={20,}$|(?:FAIL|ERROR): )"),
                 re.compile(r"^Ran \d+ tests?"),
                 re.compile(r"^(?:Ran \d+ tests?|OK\b|FAILED \(|NO TESTS RAN)")),
}
_RULES["jest"] = _RULES["vitest"] = _RULES["nx"] = _RULES["js"]
_NX_PREFIX = re.compile(r"^\S+:\S+: ")
_VITEST_LINE = re.compile(r"^\s*(?:×|❯\s.*\bfailed\b)")
_UNITTEST_LINE = re.compile(r"\.\.\. (?:FAIL|ERROR)$")
_DUP = "Summary of all failing tests"


def filter_lines(lines, runner):
    start, end, summary = _RULES[runner]
    kept, in_block, found, dup = [], False, False, False
    for raw in lines:
        line = raw.rstrip("\n")
        m = _NX_PREFIX.sub("", line) if runner == "nx" else line
        if _DUP in m:
            dup, in_block = True, False
        if summary.search(m):
            kept.append(line)
            found = True
            in_block = False
        elif end.search(m):
            in_block = False
        elif start.search(m) and not dup:
            kept.append(line)
            in_block = found = True
        elif in_block:
            kept.append(line)
        elif _VITEST_LINE.search(m) or (runner == "unittest" and _UNITTEST_LINE.search(m)):
            kept.append(line)
    if not found:  # a crash or compile error: no totals, so show the tail instead of nothing
        kept = [l.rstrip("\n") for l in lines[-40:]]
        kept.insert(0, "[quiet-tests: no failures or totals found; last lines follow]")
    return kept


_UNITY_LOG = re.compile(r"error CS\d+|Compilation failed|compiler errors|^\s*(?:FAIL|Failed|Error)\b|"
                        r"Exception:|Test run|Saving (?:results|test)|batchmode", re.I)


def unity_xml(path, since):
    import xml.etree.ElementTree as ET
    if not path or not os.path.exists(path) or os.path.getmtime(path) < since - 2:
        return None
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    run = root if root.tag == "test-run" else root.find(".//test-run")
    if run is None:
        return None
    out = ["Unity tests: total %s, passed %s, failed %s, skipped %s, inconclusive %s (%ss)" % (
        *(run.get(k, "?") for k in ("total", "passed", "failed", "skipped", "inconclusive")),
        run.get("duration", "?"))]
    for case in run.iter("test-case"):
        if (case.get("result") or "").startswith("Failed"):
            out.append("FAIL " + (case.get("fullname") or case.get("name") or "?"))
            msg = (case.findtext("failure/message") or case.findtext("output") or "").strip()
            stack = (case.findtext("failure/stack-trace") or "").strip().splitlines()[:4]
            out += ["    " + l for l in msg.splitlines()[:8] + stack]
    return out


def filter_unity(lines, results, since):
    out = unity_xml(results, since)
    if out:
        return out
    kept = [l.rstrip("\n") for l in lines if _UNITY_LOG.search(l)][-60:]
    note = "[quiet-tests: no fresh -testResults file; log lines that matter, then the tail]"
    return [note] + kept + [l.rstrip("\n") for l in lines[-15:]]


def run_filter(runner, results, stdin, stdout):
    since = time.time()
    lines = stdin.readlines()
    out = filter_unity(lines, results, since) if runner == "unity" else filter_lines(lines, runner)
    out.append("[quiet-tests: %d of %d lines shown]" % (len(out), len(lines)))
    stdout.write("\n".join(out) + "\n")


def main(argv):
    if argv[:1] == ["hook"]:
        out = hook(sys.stdin)
        if out:
            print(json.dumps(out))
    elif argv[:1] == ["filter"] and len(argv) > 1:
        results = argv[argv.index("--results") + 1] if "--results" in argv else None
        run_filter(argv[1], results, sys.stdin, sys.stdout)
    else:
        sys.exit("usage: quiet_tests.py hook | filter RUNNER [--results FILE]")


if __name__ == "__main__":
    main(sys.argv[1:])
