#!/usr/bin/env python3
"""PreToolUse hook for the hub's workers: refuse the git commands that rewrite a shared checkout.

Reads one Claude Code hook event on stdin. A Bash command that runs `git stash` (the stash stack is shared by
every worktree of a repo), or, in the repo's main checkout, `git checkout`, `restore`, `switch`, `rebase` or
`reset --hard`, is denied with the way out: compare against a clean tree in a throwaway `git worktree add`.
Anything else is allowed; a hook that cannot read its event allows too (exit 0, no output).
"""
import json
import os
import re
import shlex
import subprocess
import sys

WAY_OUT = ("Compare against a clean tree in a throwaway worktree instead: "
           "`git worktree add --detach /tmp/clean-tree HEAD`, run there, then `git worktree remove --force /tmp/clean-tree`.")
ALWAYS = {"stash"}
MAIN_ONLY = {"checkout", "switch", "rebase", "restore"}
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def segments(command):
    """The simple commands of a shell line, each as a token list (split on ; & | and newlines)."""
    for part in re.split(r"[;&|\n]+|\$\(|`|\(|\)", command):
        try:
            toks = shlex.split(part)
        except ValueError:
            toks = part.split()
        if toks:
            yield toks


def git_calls(command):
    """(directory option or None, subcommand, its arguments) for each `git` in the line."""
    for toks in segments(command):
        while toks and (re.fullmatch(r"\w+=\S*", toks[0]) or toks[0] in ("env", "sudo", "command", "time", "nohup")):
            toks = toks[1:]
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


def refusal(command, cwd, main=in_main_checkout):
    """The reason to refuse this command line, or None."""
    for where, sub, args in git_calls(command):
        if sub in ALWAYS:
            return "`git stash` is refused: the stash stack is shared by every worktree, and a pop can apply another run's stash."
        bad = (sub in MAIN_ONLY and not (sub == "restore" and "--staged" in args and "--worktree" not in args)
               or sub == "reset" and "--hard" in args)
        if bad:
            dir_ = (where if where and where.startswith("/") else (cwd + "/" + where if where else cwd)) or "."
            if main(dir_):
                return "`git {}` is refused in the main checkout: it rewrites tracked files other runs share.".format(sub)
    return None


def main():
    try:
        e = json.load(sys.stdin)
        if e.get("tool_name") != "Bash":
            return 0
        why = refusal((e.get("tool_input") or {}).get("command") or "", e.get("cwd") or ".")
    except (ValueError, AttributeError):
        return 0
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why + " " + WAY_OUT}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
