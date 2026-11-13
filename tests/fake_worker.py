#!/usr/bin/env python3
"""A stand-in for `claude -p` / `agy -p` in the hub's runner tests: never a model.

The runner tests put a `claude` on PATH that runs this script with the launcher's own arguments, so
`sbhub.launch` is exercised for real. It reads the ticket and its paths from the brief (`-p`), prints
its arguments (the log keeps them), and does what FAKE_WORKER_MODE says:

  commit   commit a change inside the ticket's paths with the right trailer, exit 0
  stray    commit a file outside the ticket's paths, with the trailer, exit 0
  commit-limit  commit as `commit` does, then print a usage-limit line and exit 1
  nothing  commit nothing, exit 1
  limit    print a usage-limit line, exit 1
  job      a prompt, not a ticket: print a result naming the prompt's first line and the folder it was told, exit 0
  hang     start a child that sleeps, write both pids to FAKE_WORKER_PIDS, sleep past any limit
"""
import json
import os
import re
import subprocess
import sys
import time


LIMIT = "You've hit your session limit · resets 4:40am (Europe/Madrid)"


def main():
    argv = sys.argv[1:]
    brief = argv[argv.index("-p") + 1]
    print("argv: " + json.dumps(argv[argv.index("-p") + 2:]), flush=True)
    print("env: " + json.dumps({k: os.environ.get(k) for k in
                                ("CLAUDE_CONFIG_DIR", "SB_HUB_AGENT", "SB_HUB_PARENT", "SB_HUB_PORT")}), flush=True)
    print("cwd: " + os.getcwd(), flush=True)
    mode = os.environ.get("FAKE_WORKER_MODE", "commit")
    found = re.search(r"^\s*Ticket: (\S+)\s*$", brief, re.M)
    ticket = found.group(1) if found else None
    owned = re.search(r"^Files you own: (.+)\. Touch no other file\.$", brief, re.M)
    paths = owned.group(1).split(", ") if owned else ["work/"]
    if mode in ("commit", "stray", "commit-limit"):
        target = "stray.txt" if mode == "stray" else paths[0] + ("done.txt" if paths[0].endswith("/") else "")
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write("work for {}\n".format(ticket))
        subprocess.run(["git", "add", target], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: work\n\nTicket: " + ticket], check=True)
        if mode == "commit-limit":
            print(json.dumps({"type": "result", "is_error": True, "result": LIMIT}))
            return 1
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "done"}))
        return 0
    if mode == "job":
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                          "result": "did: " + brief.splitlines()[0]}))
        return 0
    if mode == "nothing":
        print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "gave up"}))
        return 1
    if mode == "limit":
        print(json.dumps({"type": "result", "is_error": True, "result": LIMIT}))
        return 1
    if mode == "hang":
        child = subprocess.Popen(["sleep", "60"])
        with open(os.environ["FAKE_WORKER_PIDS"], "w", encoding="utf-8") as f:
            f.write("{} {}\n".format(os.getpid(), child.pid))
        time.sleep(60)
        return 0
    print("unknown mode " + mode, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
