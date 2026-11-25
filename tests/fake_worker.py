#!/usr/bin/env python3
"""A stand-in for `claude -p` / `agy -p` / `codex exec` in the hub's runner tests: never a model.

The runner tests put a `claude` on PATH that runs this script with the launcher's own arguments, so
`sbhub.launch` is exercised for real. It reads the ticket and its paths from the brief (`-p`), prints
its arguments (the log keeps them), and does what FAKE_WORKER_MODE says (run as `codex exec <brief>`, its `limit`
and `auth` print Codex's JSON events instead):

  commit   commit a change inside the ticket's paths with the right trailer, exit 0
  stray    commit a file outside the ticket's paths, with the trailer, exit 0
  commit-limit  commit as `commit` does, then print a usage-limit line and exit 1
  nothing  commit nothing, exit 1
  no-change  commit nothing, write the report the brief names with a `## No change needed` heading, exit 0
  limit    print a usage-limit line, exit 1 (with FAKE_WORKER_RESET set, first a rate_limit_event whose 5-hour
           window is rejected until then)
  slow     commit as `commit` does, then sleep FAKE_WORKER_SLEEP seconds (default 2) before its result, exit 0
  auth     print the expired-login failure (an assistant message and an error result), exit 1
  job      a prompt, not a ticket: print a result naming the prompt's first line and the folder it was told, exit 0
  resolve  try `sbmap resolve` on its ticket the way the worker's PreToolUse hook (the launch's --settings) sees it:
           run only if the hook allows it, commit nothing, exit 1
  hang     start a child that sleeps, write both pids to FAKE_WORKER_PIDS, sleep past any limit

`codex sandbox -- true` exits 0, or fails as bubblewrap does with FAKE_CODEX_SANDBOX=broken.
A brief that opens `# Mend ` (templates/fix-build.md) makes it the fake build fixer, whatever the mode; FAKE_FIX says
what it does: `commit` writes base/fix.txt and commits it, `slow` sleeps 3 seconds and commits nothing, anything else
commits nothing. Each exits 0 with a one-line result.

A brief that opens the integrator's (templates/integrate.md) makes it the fake integrator, whatever the mode: it
appends a JSON line to FAKE_INTEGRATE_CALLS (cwd, env, start and end time, the hub's locks from FAKE_COMPILE_STATE),
then does what FAKE_INTEGRATE says (default works): `works` commits a fix (fix.txt), appends a line to the tracked
file FAKE_INTEGRATE_DIRTY when set (Unity writing during Play) and writes its report with `VERDICT: works`;
`broken` writes `VERDICT: broken`; `tried` commits the fix as `works` does, then writes `VERDICT: broken`;
`silent` writes no report; `no unity` commits nothing and writes `VERDICT: no unity` (it could not reach the Editor). FAKE_INTEGRATE_SLEEP: seconds it takes first.

A brief that names a review file (`Write your review to: <path>`, templates/review-brief.md) makes it the fake
reviewer instead, whatever the mode (it names one review file per landed ticket, `<num>-review.md`). FAKE_REVIEW
says what it does with each, a mode for all or a JSON object {"<num>": mode} (default finished):

  finished | partly | not met   write one line per Done-when item and that verdict, exit 0
  none     write the item lines but no verdict, exit 0
  crash    write nothing, exit 1
  slow     sleep FAKE_REVIEW_SLEEP seconds (default 2), then as finished

A ticket whose section lists In Play lines (`### Its In Play lines`) gets one item line for each, after the others:
`met: played on main` when the brief says the hub took the Unity lock for it, else `not played yet`.

Every review it runs appends a line to FAKE_REVIEW_CALLS when that is set: each file's name and mode.
A brief that also names a fit file (`Write how they fit to: <path>`, two tickets or more) gets FAKE_FIT written
there, its lines split on `|` (default `- They fit together: nothing to change.`).

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
CODEX_LIMIT = ("You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
               "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Nov 15th, 2026 3:04 AM.")
CODEX_AUTH = ("Your access token could not be refreshed because your refresh token has expired. "
              "Please log out and sign in again.")


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


def play_lines(brief, path):
    """The In Play lines the brief lists in the section of the ticket whose review goes to `path`."""
    parts = re.split(r"^Write your review to: (.+)$", brief, flags=re.M)
    for i in range(1, len(parts), 2):
        if parts[i].strip() == path:
            sec = parts[i - 1].rpartition("## The ticket")[2]
            m = re.search(r"^### Its In Play lines\n\n((?:- .+\n)+)", sec, re.M)
            return [l[2:] for l in m.group(1).splitlines()] if m else []
    return []


def reviewer(paths, brief=""):
    """The fake second pass: one review file per path the brief names (one per landed ticket, `<num>-review.md`),
    each with FAKE_REVIEW's verdict: a mode for all of them, or a JSON object {"<num>": mode} (others finished)."""
    raw = os.environ.get("FAKE_REVIEW", "finished")
    try:
        modes = json.loads(raw)
    except ValueError:
        modes = raw
    pick = lambda path: modes.get(re.match(r"(\d+)", os.path.basename(path)).group(1), "finished") \
        if isinstance(modes, dict) else modes
    if os.environ.get("FAKE_REVIEW_CALLS"):
        with open(os.environ["FAKE_REVIEW_CALLS"], "a", encoding="utf-8") as f:
            f.write(" ".join("{}:{}".format(os.path.basename(p), pick(p)) for p in paths) + "\n")
    crashed = False
    if "slow" in map(pick, paths):
        time.sleep(float(os.environ.get("FAKE_REVIEW_SLEEP") or 2))
    for path in paths:
        mode = pick(path)
        if mode == "crash":
            crashed = True
            continue
        mode = "finished" if mode == "slow" else mode
        met = "met" if mode == "finished" else "not met: the fake reviewer found no test for it"
        lines = ["# Review", "", "- It works.: " + met]
        if mode == "partly":
            lines.append("- The commit names the ticket: met")
        held = "The hub took the repo's Unity lock" in brief
        lines += ["- {}: {}".format(l, "met: played on main, it worked" if held else
                                    "not played yet: the Editor was not mine") for l in play_lines(brief, path)]
        if mode != "none":
            lines += ["", "Verdict: " + mode]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    for fit in re.findall(r"^Write how they fit to: (.+)$", brief, re.M):
        with open(fit.strip(), "w", encoding="utf-8") as f:
            f.write("\n".join((os.environ.get("FAKE_FIT") or "- They fit together: nothing to change.").split("|"))
                    + "\n")
    if crashed:
        print(json.dumps({"type": "result", "is_error": True, "result": "crashed"}), flush=True)
        return 1
    result({"type": "result", "subtype": "success", "is_error": False, "result": "Verdict: " + ", ".join(paths)})
    return 0


def integrator(brief):
    """The fake integrator (see the module's doc)."""
    start = time.time()
    time.sleep(float(os.environ.get("FAKE_INTEGRATE_SLEEP") or 0))
    mode = os.environ.get("FAKE_INTEGRATE", "works")
    out = re.search(r"Write it to `([^`]+)`", brief).group(1)
    ticket = re.search(r"^# Bring (\S+) into", brief).group(1)
    if mode in ("works", "tried"):
        with open("fix.txt", "a", encoding="utf-8") as f:
            f.write("fix for {}\n".format(ticket))
        subprocess.run(["git", "add", "fix.txt"], check=True)
        subprocess.run(["git", "commit", "-q", "-m", "fix(integrate): it builds\n\nTicket: " + ticket], check=True)
        if os.environ.get("FAKE_INTEGRATE_DIRTY"):
            with open(os.environ["FAKE_INTEGRATE_DIRTY"], "a", encoding="utf-8") as f:
                f.write("written by Unity during Play\n")
    if mode != "silent":
        with open(out, "w", encoding="utf-8") as f:
            f.write("## In plain words\n\nPlayed it.\n\nVERDICT: {}\n".format(
                mode if mode in ("works", "no unity") else "broken"))
    calls = os.environ.get("FAKE_INTEGRATE_CALLS")
    if calls:
        state = os.environ.get("FAKE_COMPILE_STATE")
        locks = json.load(open(state)).get("locks", {}) if state and os.path.exists(state) else {}
        with open(calls, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ticket": ticket, "cwd": os.getcwd(), "unity": os.environ.get("SB_HUB_UNITY"),
                                "locks": locks, "start": start, "end": time.time()}) + "\n")
    result({"type": "result", "subtype": "success", "is_error": False, "result": "integrated"})
    return 0


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["sandbox"]:  # `codex sandbox -- true`: FAKE_CODEX_SANDBOX=broken fails as bubblewrap does
        if os.environ.get("FAKE_CODEX_SANDBOX") == "broken":
            print("bwrap: setting up uid map: Permission denied", file=sys.stderr)
            return 1
        return 0
    codex = argv[:1] == ["exec"]
    at = 0 if codex else argv.index("-p")
    brief = argv[at + 1]
    print("argv: " + json.dumps(argv[at + 2:]), flush=True)
    env = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "SB_HUB_AGENT", "SB_HUB_PARENT", "SB_HUB_PORT")}
    if codex:
        env["CODEX_HOME"] = os.environ.get("CODEX_HOME")
    if os.environ.get("SB_HUB_UNITY"):  # only a Unity project's worker or integrator has it
        env["SB_HUB_UNITY"] = os.environ["SB_HUB_UNITY"]
    print("env: " + json.dumps(env), flush=True)
    print("cwd: " + os.getcwd(), flush=True)
    if brief == "reply ok":  # the hub's usage probe
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}))
        return 0
    if brief.startswith("# Bring ") and "You are the sb hub's integrator" in brief:
        return integrator(brief)
    review = re.findall(r"^Write your review to: (.+)$", brief, re.M)
    if review:
        return reviewer([r.strip() for r in review], brief)
    if os.environ.get("FAKE_WORKER_USAGE"):
        event(float(os.environ["FAKE_WORKER_USAGE"].split(">")[0]))
    if brief.startswith("# Mend "):
        fix = os.environ.get("FAKE_FIX", "")
        if fix == "slow":
            time.sleep(3)
        if fix == "commit":
            os.makedirs("base", exist_ok=True)
            with open("base/fix.txt", "w", encoding="utf-8") as f:
                f.write("mended\n")
            subprocess.run(["git", "add", "base/fix.txt"], check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fix(build): the shared file builds with both"], check=True)
        said = "Mended: the shared file builds again." if fix == "commit" else "Could not mend it: it needs a ruling."
        result({"type": "result", "subtype": "success", "is_error": False, "result": said})
        return 0
    mode = os.environ.get("FAKE_WORKER_MODE", "commit")
    found = re.search(r"^\s*Ticket: (\S+)\s*$", brief, re.M)
    ticket = found.group(1) if found else None
    owned = re.search(r"^Files you own: (.+?)\. Start there\b", brief, re.M)
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
    if mode == "resolve":
        found = re.search(r"^Read the ticket first: (.+?) show (\S+) (\d+)$", brief, re.M)
        sbmap, map_, num = found.groups()
        cmd = "python3 {} resolve {} {} --commit abc".format(sbmap, map_, num)
        hook = json.loads(argv[argv.index("--settings") + 1])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        tool_event = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": os.getcwd()}
        out = subprocess.run(hook, shell=True, input=json.dumps(tool_event), capture_output=True, text=True).stdout
        print("hook: " + out.strip(), flush=True)
        if "deny" not in out:
            subprocess.run(cmd, shell=True, check=False)
        result({"type": "result", "subtype": "success", "is_error": True, "result": "tried to resolve"})
        return 1
    if mode == "job":
        result({"type": "result", "subtype": "success", "is_error": False, "result": "did: " + brief.splitlines()[0]})
        return 0
    if mode == "no-change":
        report = re.search(r"^- Write your report to (\S+?):", brief, re.M).group(1)
        with open(report, "w", encoding="utf-8") as f:
            f.write("# {}\n\n## No change needed\n\nIt already works: the fake looked.\n".format(ticket))
        result({"type": "result", "subtype": "success", "is_error": False, "result": "no change needed"})
        return 0
    if mode == "nothing":
        result({"type": "result", "subtype": "success", "is_error": True, "result": "gave up"})
        return 1
    if codex and mode in ("limit", "auth"):
        print(json.dumps({"type": "thread.started", "thread_id": "t1"}))
        print(json.dumps({"type": "error", "message": CODEX_LIMIT if mode == "limit" else CODEX_AUTH}))
        print(json.dumps({"type": "turn.failed", "error": {"message": CODEX_LIMIT if mode == "limit" else CODEX_AUTH}}))
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
