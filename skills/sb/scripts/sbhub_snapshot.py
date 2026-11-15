#!/usr/bin/env python3
"""sbhub_snapshot: the hub page as a phone-width picture, and the night as one phone-width note.

  python3 sbhub_snapshot.py [--out PNG] [--port N]

Renders http://127.0.0.1:<port>/ (port: --port, else SB_HUB_PORT, else 8765) at 430 px wide with headless
Chrome and prints the PNG's absolute path (default out: a temp file). Exits 2 with one line when Chrome is
missing, the hub does not answer, or Chrome writes no picture in time.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_TIMEOUT = 60  # a safety net: --timeout ends the page after 8 s of real time (virtual time could hang for ever)

NEXT_SHOWN = 5  # the next queued tickets a map's block lists
WAITING_SHOWN = 10


def _one(text, n=140):
    """One line of at most n characters, with nothing that would break a wikilink or a list."""
    t = " ".join(str(text or "").replace("[[", "[").replace("]]", "]").replace("|", "/").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "\u2026"


def night_note(queue, rows, now, files=None, steps=None, reports=None):
    """The text of wayfinder/runs/hub-now.md: the night, map by map, for a phone. Pure.

    queue: the hub's queue dict (paused, items). rows: the open tickets (title, state, reason, map, num).
    now: epoch seconds. files: ticket key -> its vault path without .md; steps: running key -> its last
    action; reports: key -> a report's vault path without .md. A ticket with no file shows its key as text.
    The first line after the frontmatter carries the time; everything below it depends on the state only."""
    files, steps, reports = files or {}, steps or {}, reports or {}
    items = [i for i in queue.get("items", []) if i.get("kind") == "ticket" and "#" in i["key"]]
    day = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    title = {"{}#{}".format(t["map"], int(t["num"])): t.get("title") for t in rows or []}

    by_key = {i["key"]: i for i in items}

    def link(key):
        num = key.rsplit("#", 1)[1]
        t = title.get(key) or by_key.get(key, {}).get("title")  # rows hold open tickets only: an ended one has the queue item's title
        if t:
            label = _one("{:03d} {}".format(int(num), t))
        elif files.get(key):
            label = _one(files[key].rsplit("/", 1)[-1])  # the ticket file's name, "075 Title"
        else:
            label = key
        return "[[{}|{}]]".format(files[key], label) if key in files else label

    live = [i for i in items if i["state"] in ("queued", "running", "review", "recheck")]
    kind = "paused" if queue.get("paused") else "running" if live else "empty"
    out = ["---", "tags:", "  - wayfinder/run", "---",
           "Written {} \u00b7 queue {}".format(time.strftime("%Y-%m-%d %H:%M", time.localtime(now)), kind)]
    maps = {}
    for i in items:
        ended = i["state"] in ("done", "failed", "skipped") and (i.get("ended") or 0) >= day
        if i["state"] in ("queued", "running", "review", "recheck") or ended:
            maps.setdefault(i["key"].rsplit("#", 1)[0], []).append(i)
    for m, its in maps.items():
        by = lambda *s: [i for i in its if i["state"] in s]
        run, nxt, rec, rev = by("running"), by("queued"), by("recheck"), by("review")
        end = sorted(by("done", "failed", "skipped"), key=lambda i: -(i.get("ended") or 0))
        counts = ["{} {}".format(n, w) for w, n in (("running", len(run)), ("in review", len(rev)), ("queued", len(nxt)), ("rechecking", len(rec)),
                  ("done", len(by("done"))), ("failed", len(by("failed"))), ("skipped", len(by("skipped")))) if n]
        out += ["", "## [[wayfinder/{}/map|{}]]".format(m, m), " \u00b7 ".join(counts)]
        if run:
            out += ["", "**Running**"]
            for i in run:
                mins = max(0, int((now - i["started"]) // 60)) if i.get("started") else 0
                out.append("- {} \u00b7 {} min \u00b7 {}".format(link(i["key"]), mins, _one(steps.get(i["key"]) or "no step yet", 80)))
        if rev:
            out += ["", "**In review**"] + ["- {} \u00b7 {}".format(link(i["key"]), _one(i.get("note"), 100)) for i in rev]
        if rec:
            out += ["", "**Checks to rerun**"] + ["- {} \u00b7 {}".format(link(i["key"]), _one(i.get("note"), 100)) for i in rec]
        if nxt:
            out += ["", "**Next**"]
            out += ["{}. {}".format(n, link(i["key"])) for n, i in enumerate(nxt[:NEXT_SHOWN], 1)]
            if len(nxt) > NEXT_SHOWN:
                out.append("and {} more".format(len(nxt) - NEXT_SHOWN))
        if end:
            out += ["", "**Ended today**"]
            for i in end:
                rep = " \u00b7 [[{}|report]]".format(reports[i["key"]]) if i["key"] in reports else ""
                out.append("- {} \u00b7 {}{}{}".format(link(i["key"]), i["state"],
                           " \u2014 " + _one(i.get("note")) if i.get("note") else "", rep))
    waits = [t for t in rows or [] if t.get("state") == "waits for you" and t["map"] in maps]
    owner = ["- {} \u00b7 {}".format(link("{}#{}".format(t["map"], int(t["num"]))), _one(t.get("reason"), 80))
             for t in waits[:WAITING_SHOWN]]
    owner += ["- {} \u00b7 failed, needs a look".format(link(i["key"])) for its in maps.values() for i in its if i["state"] == "failed"]
    out += ["", "## Waits for you"] + (owner or ["nothing"])
    if len(waits) > WAITING_SHOWN:
        out.append("and {} more".format(len(waits) - WAITING_SHOWN))
    return "\n".join(out) + "\n"


def same_note(a, b):
    """True when two notes differ at most in the time on their first line."""
    cut = lambda t: t.split("\n", 5)[5:] if t else None
    return cut(a) == cut(b)


def write_whole(path, text):
    """Replace the file with `text` in one step: a hidden temp file beside it, then a rename."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main(argv=None):
    p = argparse.ArgumentParser(prog="sbhub_snapshot.py")
    p.add_argument("--out")
    p.add_argument("--port", type=int, default=int(os.environ.get("SB_HUB_PORT") or 8765))
    a = p.parse_args(argv)
    if not os.path.exists(CHROME):
        print("snapshot: Google Chrome is not installed", file=sys.stderr)
        return 2
    url = "http://127.0.0.1:{}/".format(a.port)
    try:
        urllib.request.urlopen(url + "api/state", timeout=3).close()
    except (OSError, ValueError):
        print("snapshot: the hub is not answering on port {}".format(a.port), file=sys.stderr)
        return 2
    out = os.path.abspath(a.out) if a.out else tempfile.mkstemp(suffix=".png", prefix="sbhub-")[1]
    late = False
    with tempfile.TemporaryDirectory() as prof:
        try:
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=430,2200",
                            "--timeout=8000", "--user-data-dir=" + prof, "--screenshot=" + out, url],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=CHROME_TIMEOUT)
        except subprocess.TimeoutExpired:  # Chrome killed
            late = True
    if not os.path.exists(out) or not os.path.getsize(out):
        print("snapshot: Chrome took more than {} s and wrote no picture".format(CHROME_TIMEOUT) if late
              else "snapshot: Chrome wrote no picture", file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
