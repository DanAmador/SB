#!/usr/bin/env python3
"""Send back a reply whose links to the Obsidian vault won't open from Claude Code Desktop.

  check.py    Stop hook: JSON on stdin; on a bad link, {"decision": "block", "reason": ...} on stdout

Claude Code Desktop opens `obsidian://open?path=<absolute path, fully encoded>` and `file://` links
in Obsidian. `obsidian://open?vault=…&file=…` and `obsidian:///…` open the browser instead, a plain
vault path can't be opened at all, and a [[wikilink]] is not a link outside Obsidian. The fix is the
line `sbmap uri <file>` prints. The hook blocks once per reply (never while `stop_hook_active`) and
lets the reply through whenever it can't read it: a broken check must never trap the owner.
"""
import json
import os
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

SBMAP = "python3 ~/.agents/skills/sb/scripts/sbmap.py uri"
_FENCE = re.compile(r"^ {0,3}(```|~~~).*?^ {0,3}\1[^\n]*$", re.M | re.S)
_INLINE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)", re.S)
_MDLINK = re.compile(r"\]\(\s*<?([^)>]+?)>?(?:\s+\"[^\"]*\")?\s*\)")
_WIKI = re.compile(r"!?\[\[[^\]\n]+\]\]")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_SUFFIX = re.compile(r"(#[^/]*|:\d+(?:-\d+)?)$")  # a #heading or :line after a file path

FIREFOX = "opens the browser, not Obsidian"
MISSING = "no such file (encoding mistake?)"
PLAIN = "a plain path: Claude Code Desktop can't open vault files"
WIKI = "a wikilink only works inside Obsidian"


def _prose(text):
    return _INLINE.sub(" ", _FENCE.sub(" ", text))


def _inside(path, vault):
    p = os.path.realpath(path)
    return p == vault or p.startswith(vault + os.sep)


def bad_links(text, vault, cwd):
    """[(the link as written, why it won't open)] for each vault link outside code."""
    vault = os.path.realpath(os.path.expanduser(vault)).rstrip(os.sep)
    prose, found = _prose(text), []
    for m in _MDLINK.finditer(prose):
        target = m.group(1).strip()
        if target.lower().startswith("obsidian:"):
            parts = urlsplit(target)
            paths = parse_qs(parts.query).get("path") if parts.netloc == "open" else None
            if not paths:
                found.append((target, FIREFOX))
            elif not os.path.exists(paths[0]):
                found.append((target, MISSING))
        elif not _SCHEME.match(target):
            path = unquote(_SUFFIX.sub("", target))
            if _inside(os.path.join(cwd, os.path.expanduser(path)), vault):
                found.append((target, PLAIN))
    found += [(m.group(0), WIKI) for m in _WIKI.finditer(prose)]
    return found


def _is_user_turn(entry):
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content")
    return isinstance(content, str) or any(
        isinstance(b, dict) and b.get("type") != "tool_result" for b in content or [])


def reply_text(data):
    """The text of the reply that just ended; "" when it can't be read."""
    last = data.get("last_assistant_message")
    if isinstance(last, str):
        return last
    try:
        with open(data["transcript_path"], encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
    except Exception:
        return ""
    start = max((i for i, e in enumerate(entries) if _is_user_turn(e)), default=-1) + 1
    texts = []
    for e in entries[start:]:
        if e.get("type") == "assistant":
            content = (e.get("message") or {}).get("content") or []
            texts += [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(texts)


def main(stdin, stdout):
    try:
        data = json.load(stdin)
        if not isinstance(data, dict) or data.get("stop_hook_active"):
            return 0
        vault = os.environ.get("SB_VAULT") or os.path.expanduser("~/Documents/Second Brain")
        found = bad_links(reply_text(data), vault, data.get("cwd") or os.getcwd())
    except Exception:
        return 0  # never trap a reply because the check failed
    if found:
        lines = [f"- `{link}`: {why}" for link, why in found[:5]]
        more = [f"- and {len(found) - 5} more"] if len(found) > 5 else []
        reason = "\n".join(
            ["These vault links won't open in Obsidian from Claude Code Desktop:", *lines, *more,
             f'Rewrite each as the line printed by: {SBMAP} "<vault file>". '
             "Send only the corrected links, not the whole reply again."])
        stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin, sys.stdout))
