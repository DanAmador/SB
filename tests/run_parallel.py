#!/usr/bin/env python3
"""Run the suite with each test class in its own process, several at once, largest classes first.

    python3 tests/run_parallel.py [-j N] [pattern]

Most tests wait (on a hub, git, a fake worker's sleep) rather than compute, so this takes the suite from
about 8 minutes to about 2. Exit 0 only when every class passed; a failing class's output is printed whole.
"""
import argparse
import os
import re
import subprocess
import sys
import time
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def groups(pattern):
    """`module.Class` for each class with tests, by test count, largest first; a module that fails to import
    is one group named by the module, so its own run reports the error."""
    sys.path.insert(0, str(TESTS))
    count = Counter()

    def walk(suite):
        for t in suite:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            elif type(t).__module__ == "unittest.loader":  # _FailedTest: the id ends in the module's name
                count[t.id().rsplit(".", 1)[-1]] += 1
            else:
                count["{}.{}".format(type(t).__module__, type(t).__name__)] += 1

    walk(unittest.defaultTestLoader.discover(str(TESTS), pattern=pattern, top_level_dir=str(TESTS)))
    return [g for g, _ in count.most_common()]


def run(group):
    start = time.time()
    r = subprocess.run([sys.executable, "-m", "unittest", "-q", group], cwd=TESTS, capture_output=True,
                       text=True, errors="replace")
    ran = int((re.search(r"^Ran (\d+) tests?", r.stderr, re.M) or [0, 0])[1])
    skipped = int((re.search(r"skipped=(\d+)", r.stderr) or [0, 0])[1])
    return group, r.returncode, ran, skipped, time.time() - start, r.stderr + r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-j", type=int, default=os.cpu_count() or 4, help="classes at once (default: CPU count)")
    ap.add_argument("pattern", nargs="?", default="test*.py")
    a = ap.parse_args()
    start = time.time()
    todo = groups(a.pattern)
    if not todo:
        print("No tests found for " + a.pattern, file=sys.stderr)
        return 5  # what `unittest discover` exits with when it finds none
    with ThreadPoolExecutor(max(1, a.j)) as pool:
        results = list(pool.map(run, todo))
    failed = [r for r in results if r[1] != 0]
    for group, _, _, _, _, out in failed:
        print("=" * 70, "\nFAILED: " + group, "\n" + out, file=sys.stderr)
    ran, skipped = sum(r[2] for r in results), sum(r[3] for r in results)
    slow = sorted(results, key=lambda r: -r[4])[:3]
    print("Slowest classes: " + ", ".join("{} {:.0f}s".format(r[0], r[4]) for r in slow), file=sys.stderr)
    print("Ran {} tests in {:.1f}s ({} classes, {} at once)".format(ran, time.time() - start, len(todo), a.j),
          file=sys.stderr)
    print("FAILED ({} classes: {})".format(len(failed), ", ".join(r[0] for r in failed)) if failed else
          "OK" + (" (skipped={})".format(skipped) if skipped else ""), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
