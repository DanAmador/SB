#!/usr/bin/env python3
"""A stand-in for `claude -p` / `agy -p` in the hub's runner tests: never a model.

The runner tests put a `claude` on PATH that runs this script with the launcher's own arguments, so
`sbhub.launch` is exercised for real. It reads the ticket and its paths from the brief (`-p`), prints
its arguments (the log keeps them), and does what FAKE_WORKER_MODE says:

  commit   commit a change inside the ticket's paths with the right trailer, exit 0
  stray    commit a file outside the ticket's paths, with the trailer, exit 0
  commit-limit  commit as `commit` does, then print a usage-limit line and exit 1
  nothing  commit nothing, exit 1
  limit    print a usage-limit line, exit 1 (with FAKE_WORKER_RESET set, first a rate_limit_event whose 5-hour
           window is rejected until then)
  slow     commit as `commit` does, then sleep FAKE_WORKER_SLEEP seconds (default 2) before its result, exit 0
  auth     print the expired-login failure (an assistant message and an error result), exit 1
  job      a prompt, not a ticket: print a result naming the prompt's first line and the folder it was told, exit 0
  hang     start a child that sleeps, write both pids to FAKE_WORKER_PIDS, sleep past any limit

Printed as `claude -p --output-format stream-json` does: the result is the last line. FAKE_WORKER_USAGE="0.30>0.45"
adds a rate_limit_event with 5-hour use 0.30 at the start and 0.45 just before the result (resetsAt from
FAKE_WORKER_RESET, weekly use from FAKE_WORKER_WEEK, default 0.1). The hub's usage probe (`-p "reply ok"`)
answers at once, whatever the mode.
"""
import json
import os
import re
import subprocess
import sys
import time


LIMIT = "You've hit your session limit · resets 4:40am (Europe/Madrid)"
AUTH = "Failed to authenticate: OAuth session expired and could not be refreshed"


def event(five, status="allowed"):
    reset = int(os.environ.get("FAKE_WORKER_RESET") or time.time() + 10800)
    week = float(os.environ.get("FAKE_WORKER_WEEK") or 0.1)
    print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": status, "resetsAt": reset, "rateLimitType": "five_hour", "unifiedWindows": {
            "five_hour": {"utilization": five, "resetsAt": reset, "status": status},
            "seven_day": {"utilization": week, "resetsAt": reset + 4 * 86400, "status": "allowed"}}}}), flush=True)


def result(obj):
    """The stream's last line, after the closing usage reading when FAKE_WORKER_USAGE asks for one."""
    usage = os.environ.get("FAKE_WORKER_USAGE")
    if usage:
        event(float(usage.split(">")[1]))
    print(json.dumps(obj), flush=True)


def main():
    argv = sys.argv[1:]
    brief = argv[argv.index("-p") + 1]
    print("argv: " + json.dumps(argv[argv.index("-p") + 2:]), flush=True)
    print("env: " + json.dumps({k: os.environ.get(k) for k in
                                ("CLAUDE_CONFIG_DIR", "SB_HUB_AGENT", "SB_HUB_PARENT", "SB_HUB_PORT")}), flush=True)
    print("cwd: " + os.getcwd(), flush=True)
    if brief == "reply ok":  # the hub's usage probe
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}))
        return 0
    if os.environ.get("FAKE_WORKER_USAGE"):
        event(float(os.environ["FAKE_WORKER_USAGE"].split(">")[0]))
    mode = os.environ.get("FAKE_WORKER_MODE", "commit")
    found = re.search(r"^\s*Ticket: (\S+)\s*$", brief, re.M)
    ticket = found.group(1) if found else None
    owned = re.search(r"^Files you own: (.+)\. Touch no other file\.$", brief, re.M)
    paths = owned.group(1).split(", ") if owned else ["work/"]
    if mode in ("commit", "stray", "commit-limit", "slow"):
        target = "stray.txt" if mode == "stray" else paths[0] + ("done.txt" if paths[0].endswith("/") else "")
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write("work for {}\n".format(ticket))
        subprocess.run(["git", "add", target], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: work\n\nTicket: " + ticket], check=True)
        if mode == "slow":
            time.sleep(float(os.environ.get("FAKE_WORKER_SLEEP") or 2))
        if mode == "commit-limit":
            result({"type": "result", "is_error": True, "result": LIMIT})
            return 1
        result({"type": "result", "subtype": "success", "is_error": False, "result": "done"})
        return 0
    if mode == "job":
        result({"type": "result", "subtype": "success", "is_error": False, "result": "did: " + brief.splitlines()[0]})
        return 0
    if mode == "nothing":
        result({"type": "result", "subtype": "success", "is_error": True, "result": "gave up"})
        return 1
    if mode == "limit":
        if os.environ.get("FAKE_WORKER_RESET"):
            event(1.0, "rejected")
        print(json.dumps({"type": "result", "is_error": True, "result": LIMIT}))
        return 1
    if mode == "auth":
        print(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": AUTH}]}, "error": "authentication_failed"}))
        print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": AUTH}))
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
