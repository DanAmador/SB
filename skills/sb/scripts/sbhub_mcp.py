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
Tools only the widget calls (no model tokens): sb_state, sb_answer
The widget (ui://sbhub/board.html) polls sb_state through the host, so it stays live while
nobody spends a token, and a click on an option answers the hub and tells the chat.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import CallToolResult, TextContent

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sbhub  # noqa: E402

BOARD_URI = "ui://sbhub/board.html"
BOARD_HTML = HERE / "sbhub_widget.html"
PORT = sbhub.default_port()
ALERT = ("needs you", "blocked")
EST = 5400  # a queue item's estimate, seconds: the hub page's 1.5 h


def hub(path, data=None, timeout=2):
    """sbhub.call, starting the hub once if it cannot be reached."""
    code, out = sbhub.call(PORT, path, data, timeout)
    if code == 0 and start_hub():
        code, out = sbhub.call(PORT, path, data, timeout)
    return code, out


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
    """The board in a few lines of text: what the model (and a text-only client) reads."""
    agents = s.get("agents", {})
    open_qs = {k: q for k, q in s.get("questions", {}).items() if q.get("answer") is None}
    workers = [a for a in agents.values() if a.get("role") == "worker"]
    tops = [a for a in agents.values() if a.get("role") != "worker"]
    need = [a for a in agents.values() if a.get("state") in ALERT]
    lines = ["{} sessions, {} workers, {} open questions, {} locks".format(
        len(tops), len(workers), len(open_qs), len(s.get("locks", {})))]
    for k, q in open_qs.items():
        lines.append("? [{}] {}: {} ({}; default {})".format(k, q["agent"], q["q"], " | ".join(q["options"]), q["default"]))
    for a in need:
        lines.append("! {} {}: {}".format(a.get("name") or a.get("agent"), a["state"], a.get("note", "")))
    for a in tops:
        done = " {}/{}".format(a["done"], a["total"]) if a.get("total") else ""
        lines.append("- {} [{}{}] {}".format(a.get("name") or a.get("agent"), a.get("state", "?"), done, a.get("note", "")[:80]))
    for k, l in s.get("locks", {}).items():
        lines.append("lock {} held by {}".format(k, l["by"]))
    decided = sorted((q for q in s.get("questions", {}).values() if q.get("answer") is not None),
                     key=lambda q: q.get("answered", 0))[-3:]
    for q in decided:
        lines.append("decided: {} -> {} (by {})".format(q["q"], q["answer"], q.get("by") or "you"))
    if queue_line(s):
        lines.append(queue_line(s))
    return "\n".join(lines)


def queue_line(s):
    """One line on tonight's queue ('' when it holds nothing to run), the numbers the hub page shows."""
    q, now = s.get("queue") or {}, s.get("now") or time.time()
    items = q.get("items", [])
    run = [i for i in items if i["state"] == "running"]
    wait = [i for i in items if i["state"] == "queued"]
    if not run and not wait:
        return ""
    start = min(i.get("started") or now for i in run) if run else now
    end = max(start + EST * (len(run) + len(wait)), now + EST * len(wait))
    line = "queue: {} queued, {} running, ends about {}".format(len(wait), len(run), time.strftime("%H:%M", time.localtime(end)))
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
            return result("The sb hub is not running and could not be started.", error=True)
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
    apps.add_html_resource(BOARD_URI, BOARD_HTML.read_text(encoding="utf-8"), title="sb board",
                           description="Live board of agent sessions, questions and locks.")
    mcp = MCPServer("sbhub", extensions=[apps], instructions=(
        "The sb hub coordinates agent sessions. Show the owner the live board with sb_board instead of "
        "writing status in chat. Ask real questions with sb_ask, never in prose. Report progress with "
        "sb_report and take shared resources (the Unity editor, a port) with sb_lock / sb_unlock."))

    @mcp.tool(description="Tonight's ticket queue on the hub: add or remove tickets by key '<map>#<num>' "
                          "(for example 'wayfinder/foo#3'), then it lists the queue. With no arguments it only "
                          "lists. A new queue starts paused: nothing runs until the owner resumes it on the hub "
                          "page. Tell the owner the count and the end time it returns.")
    def sb_queue(add: list[str] = [], remove: list[str] = []) -> CallToolResult:  # noqa: B006 (never mutated)
        code, s = hub("/api/state")
        if code != 200:
            return result("The sb hub is not running and could not be started; start it with "
                          "`python3 skills/sb/scripts/sbhub.py serve`, then try again.", error=True)
        q = s["queue"]
        if add or remove:
            for attempt in (0, 1):
                have = [i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
                want = [k for k in have if k not in remove] + [k for k in dict.fromkeys(add) if k not in have and k not in remove]
                code, out = hub("/api/queue/set", {"keys": want, "version": q["version"]}, timeout=75)
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
                          "or state 'blocked' / 'needs you' / 'done'.")
    def sb_report(agent: str, state: str = "", note: str = "", ticket: str = "", done: int | None = None,
                  total: int | None = None, parent: str = "", name: str = "", project: str = "",
                  role: str = "") -> str:
        d = {"agent": agent, "state": state, "note": note, "ticket": ticket, "parent": parent, "name": name,
             "role": role, "project": os.path.abspath(project) if project else ""}
        d.update({k: str(v) for k, v in (("done", done), ("total", total)) if v is not None})
        code, _ = hub("/api/report", {k: v for k, v in d.items() if v not in ("", None)})
        return "reported" if code == 200 else "hub not reachable; carry on"

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
