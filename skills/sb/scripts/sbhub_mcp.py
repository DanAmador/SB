#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2.3,<3"]
# ///
"""sbhub_mcp: the hub's second face, an MCP server whose tools draw live widgets in chat.

A thin client of the hub (`sbhub.py serve`): it holds no state of its own and starts the hub
when it is down. Run over stdio by Claude Code through the hub-report mod's .mcp.json:

  uv run --script sbhub_mcp.py

Tools the model sees:  sb_board, sb_ask, sb_queue, sb_report, sb_lock, sb_unlock
Tools only the widget calls (no model tokens): sb_state, sb_api, sb_answer
The widget (ui://sbhub/board.html) is the hub's new board (packages/web, built) with every /api/ read sent through
sb_api by sbhub_widget_bridge.js, so it stays live while nobody spends a token; a click on a question's option
answers the hub through sb_answer.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import CallToolResult, TextContent

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sbhub  # noqa: E402

BOARD_URI = "ui://sbhub/board.html"
DIST = HERE.parent / "hub" / "packages" / "web" / "dist"  # the new board's build: pnpm --dir skills/sb/hub build
BRIDGE = HERE / "sbhub_widget_bridge.js"
PORT = sbhub.default_port()
# The hub's state is near 1 MB; a host refuses or cuts a tool result that size, so sb_api sends it in parts.
API_PART = 150_000
API_CACHE = {}
ALERT = ("needs you", "blocked")
EST = 5400  # a queue item's estimate, seconds: the hub page's 1.5 h


NOT_BUILT = ("<!doctype html><meta charset=utf-8><body style='font:13px system-ui;padding:8px'>"
             "The board is not built: run <code>pnpm --dir skills/sb/hub build</code>, then start a new session.")


def board_html():
    """The new board as one html file: its stylesheet and script inlined (a widget loads no files), the bridge first."""
    try:
        page = (DIST / "index.html").read_text(encoding="utf-8")
        css = "".join("<style>{}</style>".format((DIST / m).read_text(encoding="utf-8"))
                      for m in re.findall(r'<link rel="stylesheet"[^>]*href="\./([^"]+)"', page))
        js = "".join("<script type=module>{}</script>".format((DIST / m).read_text(encoding="utf-8").replace("</script", "<\\/script"))
                     for m in re.findall(r'<script type="module"[^>]*src="\./([^"]+)"', page))
    except OSError:
        return NOT_BUILT
    page = re.sub(r'<script type="module"[^>]*></script>|<link rel="stylesheet"[^>]*>', "", page)
    bridge = "<script>{}</script>".format(BRIDGE.read_text(encoding="utf-8"))
    return page.replace("</head>", bridge + css + "</head>", 1).replace("</body>", js + "</body>", 1)


def hub(path, data=None, timeout=2):
    """sbhub.call, starting the hub once if it cannot be reached."""
    code, out = sbhub.call(PORT, path, data, timeout)
    if code == 0 and start_hub():
        code, out = sbhub.call(PORT, path, data, timeout)
    return code, out


HUB_DOWN = ("The sb hub is not running. Do not start it yourself: tell the owner, who runs it as a service "
            "(skills/sb/scripts/sbhub_service.sh).")


def start_hub():
    """Start `sbhub.py serve` detached; True once it answers (within ~4 s)."""
    if os.environ.get("SB_HUB_AUTOSTART") == "0":
        return False
    home = Path(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub")
    home.mkdir(parents=True, exist_ok=True)
    try:
        with open(home / "serve.log", "ab") as log:
            # the system python, not uv's throwaway env: the hub outlives this server
            subprocess.Popen([shutil.which("python3") or sys.executable,
                              str(HERE / "sbhub.py"), "serve", "--port", str(PORT)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    except OSError:
        return False
    for _ in range(40):
        time.sleep(0.1)
        if sbhub.call(PORT, "/api/state", timeout=0.5)[0] == 200:
            return True
    return False


def result(text, structured=None, error=False):
    return CallToolResult(content=[TextContent(type="text", text=text)],
                          structured_content=structured, is_error=error)


def summary(s):
    """The board as a few plain lines (at most 7; 8 with the widget hint): what a phone, a text-only client and the model read."""
    now = s.get("now") or time.time()
    agents = s.get("agents", {})
    items = (s.get("queue") or {}).get("items", [])
    need = ["{}: {} ({})".format(q["agent"], q["q"], " | ".join(q["options"]))
            for q in s.get("questions", {}).values() if q.get("answer") is None]
    need += ["{} {}: {}".format(a.get("name") or a.get("agent"), a["state"], a.get("note", ""))
             for a in agents.values() if a.get("state") in ALERT]
    lines = ["Needs you: " + "; ".join(need) if need else "Nothing needs you."]
    run = [i for i in items if i["state"] == "running"]
    for i in run[:3]:
        mins = int((now - i["started"]) // 60) if i.get("started") else 0
        lines.append("Running: {} on {}, {} min".format((i.get("name") or i["key"])[:50], i.get("agent") or "default", mins))
    if len(run) > 3:
        lines.append("and {} more running".format(len(run) - 3))
    wait = [i for i in items if i["state"] == "queued"]
    q = s.get("queue") or {}
    if run or wait:
        lines.append("Queued: {}{}".format(len(wait), " (paused until you resume it)" if q.get("paused") else ""))
    use = []
    for n, e in (s.get("installed") or {}).items():
        u, lim = e.get("usage") or {}, e.get("limited_until") or 0
        if lim > now:
            use.append("{} at its limit until {}".format(n, time.strftime("%H:%M", time.localtime(lim))))
        elif u.get("five_hour") is not None:
            r = u.get("five_hour_resets") or 0
            use.append("{} {:.0f}% of 5 hours{}".format(n, 100 * u["five_hour"], ", resets " + time.strftime("%H:%M", time.localtime(r)) if r > now else ""))
    if use:
        lines.append("Accounts: " + "; ".join(use))
    decided = sorted((x for x in s.get("questions", {}).values() if x.get("answer") is not None),
                     key=lambda x: x.get("answered", 0))[-2:]
    for x in decided:
        lines.append("decided: {} -> {} (by {})".format(x["q"], x["answer"], x.get("by") or "you"))
    end = ends(s)
    if end:
        lines.append("Ends about " + end)
    return "\n".join(lines[:7])


def ends(s):
    """HH:MM the queue should finish ('' when it holds nothing to run)."""
    q, now = s.get("queue") or {}, s.get("now") or time.time()
    items = q.get("items", [])
    run = [i for i in items if i["state"] == "running"]
    wait = [i for i in items if i["state"] == "queued"]
    if not run and not wait:
        return ""
    start = min(i.get("started") or now for i in run) if run else now
    return time.strftime("%H:%M", time.localtime(max(start + EST * (len(run) + len(wait)), now + EST * len(wait))))


def queue_line(s):
    """One line on tonight's queue ('' when it holds nothing to run), the numbers the hub page shows."""
    q, now = s.get("queue") or {}, s.get("now") or time.time()
    items = q.get("items", [])
    run = [i for i in items if i["state"] == "running"]
    wait = [i for i in items if i["state"] == "queued"]
    if not run and not wait:
        return ""
    line = "queue: {} queued, {} running, ends about {}".format(len(wait), len(run), ends({"queue": q, "now": now}))
    return line + (" (paused: nothing starts until the owner resumes it)" if q.get("paused") else "")


def queue_text(q, s=None):
    """The queue as a few text lines: the summary, then each live item."""
    lines = [queue_line({"queue": q, "now": (s or {}).get("now")}) or "queue: empty"]
    for i in q.get("items", []):
        if i["state"] in ("queued", "running"):
            lines.append("- {} [{}]{}".format(i["key"], i["state"], " " + i["name"] if i.get("name") else ""))
    return "\n".join(lines[:9] + (["..."] if len(lines) > 9 else []))


def board_state(focus=None):
    code, s = hub("/api/state")
    if code != 200:
        return None
    s = {k: v for k, v in s.items() if k != "aliases"}
    if focus:
        s["focus"] = focus
    return s


def snapshot(focus=None, **extra):
    """What a board or ask result carries into the conversation: the rows and the open questions only.
    Provider widgets and decided questions are most of the state's size and the model never needs
    them; a widget that can call tools pulls the whole state through sb_state, one that cannot
    draws this."""
    s = board_state(focus)
    if s is None:
        return {**({"focus": focus} if focus else {}), **extra}
    keep = ("agent", "name", "title", "project", "role", "parent", "ticket", "state", "note", "done", "total", "at")
    return {"agents": {k: {f: a[f] for f in keep if f in a} for k, a in s["agents"].items()},
            "questions": {k: q for k, q in s["questions"].items() if q.get("answer") is None or k == focus},
            "locks": s["locks"], "now": s["now"],
            "queue": {"paused": s["queue"].get("paused"), "agent": s["queue"].get("agent"),
                      **{n: sum(i["state"] == n for i in s["queue"].get("items", [])) for n in ("queued", "running")},
                      "items": [{f: i.get(f) for f in ("key", "kind", "state", "name", "started")}
                                for i in s["queue"].get("items", [])[:5]]} if s.get("queue") else None,
            **({"focus": focus} if focus else {}), **extra}


def build_server():
    apps = Apps()

    @apps.tool(resource_uri=BOARD_URI, title="sb board",
               meta={"ui/resourceUri": BOARD_URI},
               description="Show the owner a live board of every agent session, its workers, open questions "
                           "and locks, inside the chat. The board updates itself; call it once, then do not "
                           "describe its contents again.")
    def sb_board(ctx: Context) -> CallToolResult:
        s = board_state()
        if s is None:
            return result(HUB_DOWN, error=True)
        text = summary(s)
        if client_supports_apps(ctx):
            text += "\n(The owner sees this live in the widget above; no need to repeat it.)"
        return result(text, snapshot())

    @apps.tool(resource_uri=BOARD_URI, visibility=["app"], title="sb state",
               description="The hub's current state, for the board widget.")
    def sb_state() -> CallToolResult:
        s = board_state()
        if s is None:
            return result("hub not reachable", {"down": True})
        return result("{} agents".format(len(s["agents"])), s)

    @apps.tool(resource_uri=BOARD_URI, visibility=["app"], title="sb api",
               description="One read-only GET of the hub's /api/ for the board widget, in parts of at most API_PART "
                           "characters: part 0 reads the hub, the later parts slice that same answer.")
    def sb_api(path: str, part: int = 0) -> CallToolResult:
        if not path.startswith("/api/") or ".." in path:
            return result("only GET /api/ paths", error=True)
        if part > 0:
            got = API_CACHE.get(path)
            if got is None or part >= len(got[1]):
                return result("part gone, read again from part 0", error=True)
            return result("{} part {}".format(path, part), {"status": got[0], "body": got[1][part], "parts": len(got[1])})
        try:
            with urllib.request.urlopen("http://127.0.0.1:{}{}".format(PORT, path), timeout=10) as r:
                status, body, kind = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            with e:
                status, body, kind = e.code, e.read(), e.headers.get("Content-Type", "")
        except (OSError, ValueError):
            return result("hub not reachable", {"down": True})
        if not kind.startswith("application/json"):
            return result("not json", {"status": 415, "body": '{"ok": false, "error": "not json"}', "parts": 1})
        text = body.decode("utf-8")
        parts = [text[i:i + API_PART] for i in range(0, len(text), API_PART)] or [""]
        API_CACHE[path] = (status, parts)
        while len(API_CACHE) > 8:
            API_CACHE.pop(next(iter(API_CACHE)))
        return result("{} {}".format(status, path), {"status": status, "body": parts[0], "parts": len(parts)})

    @apps.tool(resource_uri=BOARD_URI, visibility=["app"], title="sb answer",
               description="Record the owner's choice for an open question.")
    def sb_answer(qid: str, answer: str) -> CallToolResult:
        code, out = hub("/api/answer", {"qid": qid, "answer": answer, "by": "you"})
        if code != 200:
            return result(out.get("error") or "hub not reachable", error=True)
        return result("answered {}: {}".format(qid, answer), {"ok": True})

    @apps.tool(resource_uri=BOARD_URI, title="sb ask",
               meta={"ui/resourceUri": BOARD_URI},
               description="Ask the owner one multiple-choice question (2 to 4 options, plain words, default "
                           "first). It shows as buttons in this chat and in every sb board and the hub page. "
                           "With block_seconds 0 (the default, for interactive chat) it returns at once: end your "
                           "turn, and the owner's click arrives as their next message (if their next message is about "
                           "something else, sb_board's text lists what was decided). For subagents or unattended "
                           "runs, pass block_seconds > 0 (e.g. 600) so it waits and returns the answer. "
                           "Unanswered after default_after seconds, the default applies and is recorded as decided by default.")
    def sb_ask(question: str, options: list[str], default: str, agent: str = "chat",
               default_after: float = 600, block_seconds: float = 0) -> CallToolResult:
        code, out = hub("/api/ask", {"agent": agent, "q": question, "options": options,
                                     "default": default, "wait": default_after})
        if code != 200:
            if code == 0:
                return result("The hub is down; take the default: {}".format(default), {"answer": default})
            return result(out.get("error") or "the hub refused the question", error=True)
        qid = out["id"]
        deadline = time.time() + max(0.0, min(block_seconds, 3600))
        while time.time() < deadline:
            c, q = sbhub.call(PORT, "/api/question/" + qid)
            if c == 200 and q.get("answer") is not None:
                return result("The owner chose: {} ({}).".format(q["answer"], "by default" if q["by"] == "default" else "by them"),
                              snapshot(qid, answer=q["answer"]))
            time.sleep(1)
        return result("Asked [{}]. The owner sees buttons in the widget. End your turn now; their choice "
                      "comes back as their next message. If none comes within {:g} minutes, '{}' applies."
                      .format(qid, default_after / 60, default), snapshot(qid))

    # read at build time, so an edit to the widget lands with the next session
    apps.add_html_resource(BOARD_URI, board_html(), title="sb board",
                           description="The sb hub board: runs, queue, what waits for you, sessions and history; read-only.")
    mcp = MCPServer("sbhub", extensions=[apps], instructions=(
        "The sb hub coordinates agent sessions. Show the owner the live board with sb_board instead of "
        "writing status in chat. Ask real questions with sb_ask, never in prose. Report progress with "
        "sb_report and take shared resources (the Unity editor, a port) with sb_lock / sb_unlock."))

    @mcp.tool(description="Tonight's ticket queue on the hub: add or remove tickets by key '<map>#<num>' "
                          "(for example 'wayfinder/foo#3'), then it lists the queue. Pass your own agent id as `agent` when adding, so the hub knows you are in charge of those maps. With no arguments it only "
                          "lists. A new queue starts paused: nothing runs until the owner resumes it on the hub "
                          "page. Tell the owner the count and the end time it returns.")
    def sb_queue(add: list[str] = [], remove: list[str] = [], agent: str = "") -> CallToolResult:  # noqa: B006 (never mutated)
        code, s = hub("/api/state")
        if code != 200:
            return result(HUB_DOWN, error=True)
        q = s["queue"]
        if add or remove:
            for attempt in (0, 1):
                have = [i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
                want = [k for k in have if k not in remove] + [k for k in dict.fromkeys(add) if k not in have and k not in remove]
                code, out = hub("/api/queue/set", {"keys": want, "version": q["version"],
                                              **({"agent": agent} if agent and add else {})}, timeout=75)
                if code == 409 and out.get("queue") and attempt == 0:
                    q = out["queue"]  # someone wrote first: once more, from what they left
                    continue
                break
            if code == 0:
                return result("The sb hub stopped answering; nothing was changed.", error=True)
            if not out.get("ok"):
                return result("The queue changed twice meanwhile; try again." if out.get("stale")
                              else out.get("error") or "the hub refused it", error=True)
            q = out["queue"]
            live = {i["key"] for i in q["items"] if i["state"] in ("queued", "running")}
            missed = [k for k in add if k not in live]
            text = queue_text(q, s)
            if missed:
                text += "\nnot queued (not a ready open ticket, or already finished): " + ", ".join(missed)
            return result(text, {"ok": True})
        return result(queue_text(q, s), {"ok": True})

    @mcp.tool(description="Tell the hub what this agent is doing. Hooks report tool use already; use this for "
                          "what they cannot know: the ticket, a run's progress (done of total), a parent run, "
                          "the map this session is in charge of ('<project>/<map>'), or state 'blocked' / 'needs you' / 'done'.")
    def sb_report(agent: str, state: str = "", note: str = "", ticket: str = "", done: int | None = None,
                  total: int | None = None, parent: str = "", name: str = "", project: str = "",
                  role: str = "", map: str = "") -> str:  # noqa: A002 (the field's name)
        d = {"agent": agent, "state": state, "note": note, "ticket": ticket, "parent": parent, "name": name,
             "role": role, "map": map, "project": os.path.abspath(project) if project else ""}
        d.update({k: str(v) for k, v in (("done", done), ("total", total)) if v is not None})
        code, out = hub("/api/report", {k: v for k, v in d.items() if v not in ("", None)})
        if code != 200:
            return "hub not reachable; carry on"
        if ticket and "ref" in out and out["ref"] is None:
            return ("reported, but '{}' names no open ticket, so the run page cannot show it: report the ticket "
                    "as '<project>/<map>#<number>', e.g. 'sk4te/party-playtest#1060'").format(ticket)
        return "reported" + (" as " + out["ref"] if out.get("ref") else "")

    @mcp.tool(description="Join the live run as 'integrator' (reviews and lands finished tickets) or 'implementer' "
                          "(builds tickets itself). Only joined chats show on the board; the hub drops hook events "
                          "from chats that never joined. Any number of chats may join; joining again changes the role.")
    def sb_join(agent: str, role: str = "integrator") -> str:
        code, out = hub("/api/run/join", {"agent": agent, "role": role})
        if code == 0:
            return HUB_DOWN
        if code != 200:
            return "not joined: {}".format(out.get("error") if isinstance(out, dict) else out)
        return "joined run {} as {}".format(out["joined"]["night"], out["joined"]["role"])

    @mcp.tool(description="Leave the run joined with sb_join: the board stops showing this chat.")
    def sb_leave(agent: str) -> str:
        code, out = hub("/api/run/leave", {"agent": agent})
        if code == 0:
            return HUB_DOWN
        return "left the run" if code == 200 else "not left: {}".format(out.get("error") if isinstance(out, dict) else out)

    @mcp.tool(description="Take a lock on a shared resource only one agent may use at a time. Returns 'ok' or "
                          "'held by <agent>': do work that needs no lock, then try again.")
    def sb_lock(key: str, by: str) -> str:
        code, out = hub("/api/lock", {"key": key, "by": by})
        if code == 0:
            return "hub not reachable; go on unlocked"
        return "ok" if out.get("ok") else "held by {}".format(out.get("held_by", "someone"))

    @mcp.tool(description="Release a lock taken with sb_lock (same key and by).")
    def sb_unlock(key: str, by: str) -> str:
        code, _ = hub("/api/unlock", {"key": key, "by": by})
        return "ok" if code == 200 else "hub not reachable"

    return mcp


def main():
    build_server().run("stdio")


if __name__ == "__main__":
    main()
