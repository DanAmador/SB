"""A fake `unity` CLI for the hub's Unity check lines (tests/test_hub_unity_checks.py). It replays Unity's real output,
the JSON files beside it, recorded from the live Editor (Pipeline 0.8.0-exp.1, sk4te, 2026-11-20):

- detach.json: `unity command editor_status --detach --json`
- job_wait.json: `unity job wait <id> --json` of that job
- job_wait_unknown.json: `unity job wait nope000 --json` (exit 6), the same answer as job_status_unknown.json
- editor_status.json: `unity command editor_status --json`
- editor_not_running.json: `unity command editor_status --json` for a project no Editor has open (exit 12), recorded
  from the real CLI on 2026-11-22

Only `command ... --detach` and `job wait` are answered. Each call is logged to FAKE_UNITY_LOG (one JSON line: argv,
cwd, time, and the hub's locks read from FAKE_UNITY_STATE at that moment). FAKE_UNITY_WAIT is a comma list, one word
per `job wait` call in turn (the last repeats):
  ok         job_wait.json as recorded (state completed, no `ok`: it passes)
  lost       job_wait_unknown.json, exit 6 (a reload dropped the job)
  fail       job_wait.json with result.ok = false and one finding (a check that found something)
  compiling  job_wait.json with editor_status's result as a compiling Editor reports it
  error      job_wait.json with state failed and an error message (the command threw)
FAKE_UNITY_SLEEP: seconds each `job wait` takes. FAKE_UNITY_DETACH=down: `command` answers as an Editor that is not
running does (no JSON), exit 1.
`command editor_status` without --detach (the hub asking whether Unity answers, ticket 189) answers editor_status.json;
FAKE_UNITY_STATUS=down answers editor_not_running.json with exit 12 instead, as the real CLI does.
`command eval` (the hub closing the open scenes around a git write) answers in the shape the live Editor gave on
2026-11-22 (data.result.result is the code's returned string). The close answers FAKE_UNITY_SCENES (default: one
scene, Assets/Scenes/Main.unity, loaded and active; `playing` for an Editor in Play; `down` for no Editor, exit 12);
the restore answers "restored 1". Each eval's log line carries `head`, the project's HEAD at that moment.
FAKE_UNITY_RESTORE is a comma list, one word per restore eval in turn (the last repeats): `ok` (the default) answers
"restored 1"; `lost` answers nothing, exit 1, as when the eval's budget ran out or a reload dropped the reply.
"""
import copy
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def sample(name):
    with open(os.path.join(HERE, name)) as f:
        return json.load(f)


def head(argv):
    """The HEAD of the project an eval names (--project-path), or None."""
    if "--project-path" not in argv:
        return None
    r = subprocess.run(["git", "-C", argv[argv.index("--project-path") + 1], "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def log(argv):
    path = os.environ.get("FAKE_UNITY_LOG")
    if not path:
        return 0
    try:
        with open(os.environ["FAKE_UNITY_STATE"]) as f:
            locks = json.load(f).get("locks", {})
    except (KeyError, OSError, ValueError):
        locks = {}
    row = {"argv": argv, "cwd": os.getcwd(), "at": time.time(), "locks": locks}
    if argv[:2] == ["command", "eval"]:
        row["head"] = head(argv)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")
    with open(path) as f:
        return sum(1 for line in f if '"job", "wait"' in line)


def main(argv):
    waits = log(argv)
    if argv[:2] == ["command", "editor_status"] and "--detach" not in argv:
        if os.environ.get("FAKE_UNITY_STATUS") == "down":
            print(json.dumps(sample("editor_not_running.json"), indent=2))
            return 12
        print(json.dumps(sample("editor_status.json"), indent=2))
        return 0
    if argv[:2] == ["command", "eval"] and "--detach" not in argv:
        code = argv[argv.index("--code") + 1] if "--code" in argv else ""
        scenes = os.environ.get("FAKE_UNITY_SCENES") or "11Assets/Scenes/Main.unity"
        if scenes == "down":
            print(json.dumps(sample("editor_not_running.json"), indent=2))
            return 12
        if "restore scenes" in code:
            with open(os.environ["FAKE_UNITY_LOG"]) as f:
                tries = sum(1 for line in f if "restore scenes" in line)
            modes = (os.environ.get("FAKE_UNITY_RESTORE") or "ok").split(",")
            if modes[min(tries - 1, len(modes) - 1)] == "lost":
                print("Error: the command timed out")
                return 1
        answer = ("playing" if scenes == "playing" else "closed\n" + scenes) if "close scenes" in code else \
            "restored 1" if "restore scenes" in code else ""
        print(json.dumps({"success": True, "command": "command", "data": {
            "command": "eval", "parameters": {"code": code}, "result": {
                "output": None, "diagnostics": [], "success": True, "result": answer}}, "errors": [], "warnings": []}))
        return 0
    if argv[:1] == ["command"] and "--detach" in argv:
        if os.environ.get("FAKE_UNITY_DETACH") == "down":
            print("Error: no Unity Editor is running for this project")
            return 1
        out = sample("detach.json")
        out["command"] = "command " + argv[1]
        out["data"]["command"] = argv[1]
        out["data"]["jobId"] = "{}{:04d}".format(out["data"]["jobId"][:-4], waits + 1)  # a new id per send
        print(json.dumps(out, indent=2))
        return 0
    if argv[:2] == ["job", "wait"]:
        time.sleep(float(os.environ.get("FAKE_UNITY_SLEEP") or 0))
        modes = (os.environ.get("FAKE_UNITY_WAIT") or "ok").split(",")
        mode = modes[min(waits - 1, len(modes) - 1)]
        if mode == "lost":
            print(json.dumps(sample("job_wait_unknown.json"), indent=2))
            return 6
        out = sample("job_wait.json")
        out["data"]["jobId"] = argv[2]
        if mode == "fail":
            out["data"]["result"] = {"ok": False, "editor": "ready",
                                     "findings": ["Assets/Scenes/Main.unity: missing script on Player"]}
        elif mode == "compiling":
            result = copy.deepcopy(sample("editor_status.json")["data"]["result"])
            result.update(status="compiling", compiling=True)
            out["data"]["result"] = result
        elif mode == "error":
            out["data"].update(state="failed", result=None, error="NullReferenceException: sb_check broke")
        print(json.dumps(out, indent=2))
        return 0
    print("fake unity: not answered: " + " ".join(argv), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
