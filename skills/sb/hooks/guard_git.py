#!/usr/bin/env python3
"""PreToolUse hook for the hub's workers: refuse what a worker must never do, each with a line naming the way out.

Reads one Claude Code hook event on stdin and denies:
  Bash  `git stash`; in the repo's main checkout `git checkout`, `restore`, `switch`, `rebase` and any `git reset`;
        `git commit --allow-empty` or `--amend`, `git push`, `git tag` (listing tags is fine);
        an sbmap write other than `comment` (resolve, close, new, set, block, claim, init, mapset, summary:
        the hub closes the ticket); `rm`, `mv` or a `>` redirect aimed inside a `.git` folder;
        with SB_HUB_UNITY=off (a ticket worker of a Unity project), any `unity` command: the Unity stage is the
        integrator's, on the main folder, after the work lands.
        For every worker, integrator and review: a test run in the Unity Editor (`unity test`, `unity command
        run_tests`, an eval or eval_file that calls the Test Runner), whose save-scenes box freezes the night.
  Write, Edit, MultiEdit, NotebookEdit  a file outside the worker's repo or worktree, its run folder
        (SB_HUB_RUN) and the system temp folder.
Anything else is allowed; a hook that cannot read its event allows too (exit 0, no output).

Every refusal is also reported to the hub (SB_HUB_AGENT and SB_HUB_PORT, which the hub sets for its workers) as a
`refused` trail action, so the run shows "refused: ..." with a count.

LIMIT: Bash is checked by reading the command line (split on ; & | and quotes), not by running it. It is a
strong fence, not a wall: a script file, `eval`, a variable or an interpreter one-liner can still do what the
line does not show. A refusal tells the worker; it is not a guarantee.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

WAY_OUT = ("Compare against a clean tree in a throwaway worktree instead: "
           "`git worktree add --detach /tmp/clean-tree HEAD`, run there, then `git worktree remove --force /tmp/clean-tree`.")
SBMAP_WRITES = {"resolve", "close", "new", "set", "block", "claim", "init", "mapset", "summary"}
SBMAP_WAY_OUT = "The hub closes the ticket: write a comment instead (`sbmap comment <map> <num> --text \"R: ...\"`)."
GIT_WAY_OUT = ("Commit real changes once, by pathspec, as a new commit; when nothing needs to change, make no commit and "
               "say so in your report under `## No change needed`. The hub pushes and tags.")
DOT_GIT_WAY_OUT = "Never touch git's own files: a lock file under .git belongs to a live git process; wait for it or say so in your report."
WRITE_WAY_OUT = "Write inside your repo or worktree, the run folder, or the system temp folder instead."
ALWAYS = {"stash"}
MAIN_ONLY = {"checkout", "switch", "rebase", "restore"}
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
WRAPPERS = ("env", "sudo", "command", "time", "nohup")
UNITY_WAY_OUT = ("Unity is the ticket's last stage, not yours: after you commit, the hub lands your work on the main "
                 "folder and an integrator compiles and plays it in the one Unity Editor, one ticket at a time. Write "
                 "what to play under `## Play checks` in your report, and check the APIs you call by reading their "
                 "source instead.")
UNITY_POLL_WAY_OUT = ("Do not poll Unity by hand: it keeps the Editor and its lock busy longer than the check needs. Run "
                      "the project's check in one command: `unity command sb_check`, or the repo's `tools/compile` when "
                      "it has one; when the repo has neither, write the check as a `[CliCommand]` tagged `sb/check`.")
UNITY_TEST_WAY_OUT = ("Never start a test run in the Unity Editor: Unity first asks to save the open scenes (Save / "
                      "Cancel / Don't Save), and that box holds the Editor until a person clicks it, which stops every "
                      "ticket of the night (2026-11-23: 5.5 hours). A test the ticket asks for is done when it is "
                      "written and compiles: say so under its check, and the owner runs the suite.")
LOOPS = {"while", "until", "for"}


def segments(command):
    """The simple commands of a shell line, each as a token list (split on ; & | and newlines)."""
    for part in re.split(r"[;&|\n]+|\$\(|`|\(|\)", command):
        try:
            toks = shlex.split(part)
        except ValueError:
            toks = part.split()
        if toks:
            yield toks


def _bare(toks):
    """The tokens without leading VAR=value words and wrappers such as env or sudo."""
    while toks and (re.fullmatch(r"\w+=\S*", toks[0]) or toks[0] in WRAPPERS):
        toks = toks[1:]
    return toks


def git_calls(command):
    """(directory option or None, subcommand, its arguments) for each `git` in the line."""
    for toks in segments(command):
        toks = _bare(toks)
        if not toks or toks[0].rsplit("/", 1)[-1] != "git":
            continue
        i, where = 1, None
        while i < len(toks) and toks[i].startswith("-"):
            if toks[i] == "-C" and i + 1 < len(toks):
                where = toks[i + 1]
            i += 2 if toks[i] in GIT_OPTS_WITH_ARG else 1
        if i < len(toks):
            yield where, toks[i], toks[i + 1:]


def in_main_checkout(cwd):
    """True unless cwd is a linked worktree (its git dir differs from the repo's common dir)."""
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--absolute-git-dir", "--git-common-dir"],
                             capture_output=True, text=True, timeout=5).stdout.split("\n")
        git_dir, common = out[0].strip(), out[1].strip()
        if not git_dir or not common:
            return True
        return os.path.realpath(git_dir) == os.path.realpath(os.path.join(cwd, common))
    except (OSError, subprocess.SubprocessError, IndexError):
        return True


def _inside_dot_git(path):
    return bool(re.search(r"(^|/)\.git(/|$)", path))


def other_refusal(command):
    """A refusal (reason and way out) for an sbmap write or a `.git` tampering in the line, or None."""
    for toks in segments(command):
        toks = _bare(toks)
        if not toks:
            continue
        for i, t in enumerate(toks[:3]):  # `python3 .../sbmap.py resolve ...`, or sbmap on PATH
            if t.rsplit("/", 1)[-1] in ("sbmap", "sbmap.py"):
                sub = next((x for x in toks[i + 1:] if not x.startswith("-")), None)
                if sub in SBMAP_WRITES:
                    return "`sbmap {}` is refused for a worker. {}".format(sub, SBMAP_WAY_OUT)
                break
        if toks[0].rsplit("/", 1)[-1] in ("rm", "mv") and any(_inside_dot_git(x) for x in toks[1:] if not x.startswith("-")):
            return "`{}` inside a .git folder is refused. {}".format(toks[0], DOT_GIT_WAY_OUT)
    if any(_inside_dot_git(m) for m in re.findall(r"\d?>>?\s*([^\s;&|<>]+)", command)):
        return "A redirect into a .git folder is refused. " + DOT_GIT_WAY_OUT
    return None


def unity_refusal(command, env=os.environ):
    """A worker of a Unity project (SB_HUB_UNITY=off) never drives the Editor: any `unity` command is refused."""
    if env.get("SB_HUB_UNITY") != "off":
        return None
    for toks in segments(command):
        toks = _bare(toks)
        if toks and (toks[0].rsplit("/", 1)[-1] == "unity" or "/Unity.app/" in toks[0]):
            return "`{}` is refused for a ticket worker. {}".format(" ".join(toks[:3]), UNITY_WAY_OUT)
    return None


def _file_text(path, cwd):
    try:
        with open(path if os.path.isabs(path) else os.path.join(cwd or ".", path), encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


def unity_test_refusal(command, cwd=None):
    """Any hub session: a test run in the live Editor is refused (`unity test`, `unity command run_tests`, and an eval
    or eval_file whose code calls the Test Runner). Unity's Test Runner asks to save modified scenes first, and that
    native box freezes the Editor's main thread until someone clicks it."""
    for toks in segments(command):
        toks = _bare(toks)
        if not toks or toks[0].rsplit("/", 1)[-1] != "unity":
            continue
        words = [t for t in toks[1:] if not t.startswith("-")]
        if words[:1] == ["test"] or (words[:1] == ["command"] and "run_tests" in words[1:2]):
            return "`{}` is refused. {}".format(" ".join(toks[:3]), UNITY_TEST_WAY_OUT)
        if words[:1] == ["command"] and words[1:2] == ["eval_file"] and "--file" in toks[:-1]:
            if "TestRunnerApi" in _file_text(toks[toks.index("--file") + 1], cwd):
                return "An eval_file that starts the Test Runner is refused. " + UNITY_TEST_WAY_OUT
    if re.search(r"\bunity\b[^\n]*\bcommand\s+eval\b", command) and "TestRunnerApi" in command:
        return "An eval that starts the Test Runner is refused. " + UNITY_TEST_WAY_OUT
    return None


def unity_poll_refusal(command, env=os.environ):
    """An integrator (SB_HUB_UNITY=integrator) checks Unity with one command: a hand-written poll is refused.

    A poll is `unity command recompile_status` run directly, or `unity command` inside a while/until/for loop or
    next to a `sleep`. `unity command recompile`, `editor_status`, `sb_check` and `tools/compile` stay allowed."""
    if env.get("SB_HUB_UNITY") != "integrator":
        return None
    unity, loop, sleep, status = None, False, False, False
    for toks in segments(command):
        loop = loop or toks[0] in LOOPS
        while toks and toks[0] in LOOPS | {"do", "then", "if", "elif", "!", "{"}:
            toks = toks[1:]
        toks = _bare(toks)
        while toks[:1] == ["timeout"]:  # `timeout 20 unity command ...`: the real logs wrap polls in it
            toks = _bare([t for t in toks[1:]][next((i for i, t in enumerate(toks[1:]) if not t.startswith("-")
                                                    and not re.fullmatch(r"[\d.]+[smhd]?", t)), len(toks)):])
        if not toks:
            continue
        if toks[0].rsplit("/", 1)[-1] == "unity" and toks[1:2] == ["command"]:
            unity = unity or toks
            status = status or toks[2:3] == ["recompile_status"]
        sleep = sleep or toks[0] == "sleep"
    if unity and (status or loop or sleep):
        what = "`unity command recompile_status`" if status else "A `unity command` in a loop or next to `sleep`"
        return "{} is refused for the integrator: a hand-written poll. {}".format(what, UNITY_POLL_WAY_OUT)
    return None


def refusal(command, cwd, main=in_main_checkout, env=os.environ):
    """The reason to refuse this command line, or None."""
    other = (other_refusal(command) or unity_refusal(command, env) or unity_test_refusal(command, cwd)
             or unity_poll_refusal(command, env))
    if other:
        return other
    for where, sub, args in git_calls(command):
        if sub in ALWAYS:
            return "`git stash` is refused: the stash stack is shared by every worktree, and a pop can apply another run's stash. " + WAY_OUT
        if sub == "commit" and ("--amend" in args or "--allow-empty" in args):
            return "`git commit {}` is refused. {}".format("--amend" if "--amend" in args else "--allow-empty", GIT_WAY_OUT)
        listing = sub == "tag" and (not args or {"-l", "--list", "-n"} & set(args))
        if sub == "push" or sub == "tag" and not listing:
            return "`git {}` is refused. {}".format(sub, GIT_WAY_OUT)
        if sub in MAIN_ONLY and not (sub == "restore" and "--staged" in args and "--worktree" not in args) or sub == "reset":
            dir_ = (where if where and where.startswith("/") else (cwd + "/" + where if where else cwd)) or "."
            if main(dir_):
                return "`git {}` is refused in the main checkout: it rewrites tracked files or the branch other runs share. {}".format(sub, WAY_OUT)
    return None


def _toplevel(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return os.path.realpath(out or cwd)


def write_refusal(tool_input, cwd, env=os.environ):
    """The reason to refuse a Write or Edit of this file, or None when it is in the repo, run folder or temp."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        return None
    path = os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd, path))
    roots = [_toplevel(cwd), os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp")]
    if env.get("SB_HUB_RUN"):
        roots.append(os.path.realpath(env["SB_HUB_RUN"]))
    if any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots):
        return None
    return "Writing {} is refused: it is outside your repo or worktree, the run folder and temp. {}".format(path, WRITE_WAY_OUT)


def report(tool, why, env=os.environ):
    """Tell the hub (the worker's trail) about a refusal; never fails the hook."""
    key, port = env.get("SB_HUB_AGENT"), env.get("SB_HUB_PORT")
    if not key or not port:
        return
    try:
        import urllib.request
        body = {"agent": key, "role": "worker", "parent": env.get("SB_HUB_PARENT") or "queue",
                "trail": {"kind": "refused", "tool": tool, "label": why.split(". ")[0][:140]}}
        req = urllib.request.Request("http://127.0.0.1:{}/api/report".format(port), json.dumps(body).encode("utf-8"),
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).close()
    except Exception:
        pass


def main():
    try:
        e = json.load(sys.stdin)
        tool, tin, cwd = e.get("tool_name"), e.get("tool_input") or {}, e.get("cwd") or "."
        if tool == "Bash":
            why = refusal(tin.get("command") or "", cwd)
        elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            why = write_refusal(tin, cwd)
        else:
            return 0
    except (ValueError, AttributeError):
        return 0
    if why:
        report(tool, why)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
