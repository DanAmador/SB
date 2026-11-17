"""sbhub: the hub that sb sessions report to.

Hub holds the rules and the state (agents, locks, questions with defaults) and
saves them to $SB_HUB_HOME/state.json (default ~/.sb-hub/). `serve` puts it on
127.0.0.1 (port 8765, or --port, or SB_HUB_PORT); the other commands talk to it
and never fail a session when it is down.

  sbhub.py serve  [--port N]          run the hub
  sbhub.py report --agent A [--name N] [--project PATH] [--role R] [--parent A] [--map PROJECT/MAP]
                  [--ticket T] [--state S] [--note N] [--done N] [--total N]
                                      tell the hub what a session is doing; always exits 0
  sbhub.py lock   <key> --by A        take a lock: prints ok, or exits 1 "held by <who>";
  sbhub.py unlock <key> --by A        release it; hub down exits 2 "sbhub: not running"
  sbhub.py ask    --agent A --q "..." --options "a|b|c" --default a [--wait SECONDS]
                                      ask the owner; prints the chosen option, or the
                                      default at the deadline or with the hub down
  sbhub.py state                      the hub's state as JSON ({} when it is down)
  sbhub.py send   --to A "text"       queue a message for a session or worker; its own hook
                                      delivers it (mid-turn, at the end of its turn, or with
                                      the next prompt)
  sbhub.py queue                      tonight's ticket queue in run order, with each ticket's state
  sbhub.py queue add|rm <map> <NNN>...   tick or untick tickets (running and finished items stay)
  sbhub.py night start [--name N]     open tonight's night (queuing with none live opens one too); a second start is refused
  sbhub.py night stop [--mode after]  start nothing new, let what runs finish, end the night as stopped; lists what it never reached
  sbhub.py night [show]               every night, newest first, with its counts
  sbhub.py queue integrate <map> <NNN>...   a Unity pass for failed tickets whose work is in the checkout: no
                                      worker, the integrator plays what the review found short and fixes it
  sbhub.py queue pause|resume         hold or release the queue
  sbhub.py queue job --project P --agent A [--model M] [--name N] [--at HH:MM] (--prompt T | --prompt-file F)
                                      queue a one-off job (never started before --at);
                                      P is a wayfinder project or the absolute path of a git checkout
  sbhub.py queue agent <name>         the agent that runs the night's items (an installed one)
  sbhub.py queue agents <name>...     the night's pool of agents: each item goes to the one where its likely
                                      usage fits with the most room left (an item's own agent still wins)
  sbhub.py agents [--scan]            the installed agents; --scan finds ~/.claude* configs and agy
  sbhub.py trust  <project path>      let the hub run that project's own .sb/providers scripts
  sbhub.py untrust <project path>     stop doing so (both work with the hub stopped)
  sbhub.py run-ticket <map>#<num> [--agent A] [--model M] [--item JSON] [--limit SECONDS]
                                      run one ticket to its end, as the queue does (claim, worker, checks,
                                      Opus review, resolve or comment, release) and print one JSON result (the contract's
                                      RunTicketResult); exit 0 when done. --item carries an earlier try's queue
                                      fields (tries, stops, retry, resume, base_sha, tree, branch, redo)
  sbhub.py run-ticket <map>#<num> ... --detach   start it in the background: prints its pid and files
  sbhub.py run-ticket --status <pid>  a detached run: running, its worker, and its result once it ended
  sbhub.py hook                       read one Claude Code hook event on stdin and report it;
                                      always exits 0 (the hub-report mod runs this)

Every command but `serve` also takes --port N.

`serve` also runs tonight's queue (SB_HUB_QUEUE=0 serves the board only). A new queue waits paused until
the owner resumes it (`queue resume`); a resumed queue stays so across restarts. Every 5 s it starts the next
queued ticket whose agent and repo are free as a headless worker (`claude -p` in auto mode, or `agy -p`),
with SB_HUB_AGENT=<ticket key> and SB_HUB_PARENT=queue so `hook` reports it as that item's worker; when the
worker exits it checks the commit, paths and checks in code; when they pass, the work lands and the ticket is
`landed` (not judged yet): it holds no files, and what comes after it may start. When a map has nothing queued,
running or in checks left, ONE second pass on Opus (`claude -p` from templates/review-brief.md) judges every landed
ticket of it against its Done when and writes <run>/<num>-review.md for each; only a `finished` verdict resolves a
ticket (pausing the queue counts as the run's end). Partly or not met queue it once more at the front, its brief
naming the first commit and the review's not-met lines; a second verdict short of finished leaves it open with
both findings, failed, for the owner. A review never reverts a commit; only a failed after-landing check or Unity
stage does, and only the ticket's own commits, each named on an `Undoes:` line.

It paces each Claude account: workers print their account's 5-hour and weekly use (stream-json), a one-line
Haiku probe reads an idle one, and an item starts only where its learned cost fits under GATE_5H (weekly under
GATE_7D); one cut off by a limit or a logout goes back to the front for another account of the pool.
"""
import argparse
import ast
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sbhub_snapshot
import sbqueue
import sbruns

# A chat's ticket counts as worked on while it reports one of these and was heard from within CHAT_IDLE seconds;
# every stretch of work is kept in chat_runs for CHAT_RUNS_KEPT seconds, so a run's history shows it after it ends.
CHAT_WORKING = ("working", "waiting", "needs you", "blocked")
CHAT_IDLE = 1800
CHAT_RUNS_KEPT = 7 * 86400
AGENT_FIELDS = ("name", "title", "asked", "project", "role", "parent", "ticket", "map", "state", "note", "done", "total")
ALERT_STATES = ("needs you", "blocked")
SILENT_LIMIT = 86400
ORPHAN_LOCK_LIMIT = 600
SILENT_LOCK_LIMIT = 1800  # a lock whose holder has not reported this long is let go: a dead session held Unity 5 h
NOTE_EVERY = 300  # hub-now.md is rewritten at most this often while something runs
TRAIL_KEPT = 40  # actions kept per agent for the Sessions view
TRAIL_LIMIT = 600  # an ended agent's trail goes this long after it ended
DONE_WORKER_LIMIT = 600  # a finished worker stays on its session's row this long
DECIDED_KEPT = 50
SENT_KEPT = 30  # finished messages kept for the page's log
MESSAGE_MAX = 4000


_KEEP = object()  # an argument the caller left out, as against None, which clears it


class Hub:
    def __init__(self, home, now=time.time, run=None, launcher=None):
        self.home = Path(home)
        self.queue_lock = None  # {mine, holder}: set by serve; None outside it
        self.supervisor = None  # the Supervisor running the queue, once one is made (POST /api/review/now)
        self._run = run  # () -> the open tickets (list or JSON); sbmap when None
        self.launcher = launcher or launch  # starts one worker; tests hand in their own
        self._tcache = (0.0, None)
        self._renamed = {}  # old queue key -> its key after sbmap move
        self._mcache = {}  # map -> (when, sbmap's answer or None when it had none), for /api/map
        self._tfailed = None  # when sbmap last failed
        self.now = now
        self._lock = threading.Lock()
        self.providers = {}
        self.queued = set()
        self._roots = {}  # a folder an agent reported from -> the checkout it belongs to (see project_root)
        self.changed = threading.Event()
        # agent -> {"ring": the last TRAIL_KEPT actions, "ctx": context percent or None, "ended": when or None}.
        # Held in memory only, and kept out of api/state
        self._trails = {}
        self.queue_kick = threading.Event()  # set by every queue write: the supervisor ticks at once
        # aliases: session id -> the agent id that session reports as (`report --agent X`)
        self._data = {"agents": {}, "locks": {}, "questions": {}, "aliases": {}, "messages": {},
                      # a new queue waits paused until the owner resumes it: nothing runs on its own
                      "queue": {"version": 0, "seeded": False, "paused": True, "agent": None, "items": [],
                                # the queued maps in run order: a repo finishes its first one before the next
                                "maps": []},
                      "installed": {},
                      # map ("<project>/<map>") -> the live session that queued it: who is in charge of it
                      "charge": {},
                      # runs the owner has opened ("<key>@<ended>"), oldest first; Waits for you leaves them out
                      "seen": []}
        path = self.home / "state.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            self._data.update(saved)
        self._migrate_nights()
        self._sync_maps(self._data["queue"])  # a queue saved before maps: its maps in their first tickets' order
        with self._lock:
            self._end_rows()  # rows of items that ended while no hub was watching
            if self._night_settle():  # a night left stopping with nothing at work ends now
                self._save()

    def _save(self):
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.home / "state.json.tmp"
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        os.replace(tmp, self.home / "state.json")

    def _resolve(self, agent):
        return self._data["aliases"].get(agent, agent)

    def _remove(self, agent):
        """Drop an agent, its workers and every alias to or from it."""
        agents, aliases = self._data["agents"], self._data["aliases"]
        agents.pop(agent, None)
        self._trail_ended(agent)
        for k in [k for k, v in agents.items() if v.get("parent") == agent]:
            self._trail_ended(k)
            del agents[k]
        charge = self._data.setdefault("charge", {})
        for m in [m for m, who in charge.items() if who not in agents]:
            del charge[m]  # a session that ends or is dismissed is no longer in charge
        for k in [k for k, v in aliases.items() if agent in (k, v)]:
            del aliases[k]

    def _alias(self, sid, target):
        """From now on session `sid` is `target`: fold its row and its workers into target's."""
        agents = self._data["agents"]
        self._data["aliases"][sid] = target
        mine = agents.pop(sid, None) or {}
        row = agents.setdefault(target, {})
        for f in ("project", "at"):
            if f in mine and f not in row:
                row[f] = mine[f]
        for v in agents.values():
            if v.get("parent") == sid:
                v["parent"] = target

    def _settle(self):
        """Apply defaults whose deadline passed and keep the latest decided questions; drop agents
        silent for a day and locks whose holder is no longer listed after ten minutes."""
        now = self.now()
        changed = False
        questions = self._data["questions"]
        for q in questions.values():
            if q["answer"] is None and now >= q["deadline"]:
                q["answer"], q["by"], q["answered"] = q["default"], "default", now
                changed = True
        decided = sorted((k for k, q in questions.items() if q["answer"] is not None),
                         key=lambda k: questions[k].get("answered", questions[k]["asked"]))
        for k in decided[:-DECIDED_KEPT]:
            del questions[k]
            changed = True
        for k, v in list(self._data["agents"].items()):
            age = now - v.get("at", now)
            if k in self._data["agents"] and (age > SILENT_LIMIT or age > DONE_WORKER_LIMIT
                                              and v.get("role") == "worker" and v.get("state") == "done"):
                self._remove(k)
                changed = True
        for k, t in list(self._trails.items()):
            if t["ended"] is not None and now - t["ended"] > TRAIL_LIMIT:
                del self._trails[k]
        for k, held in list(self._data["locks"].items()):
            if held.get("landing"):
                continue  # the hub's own landing: it lets go when the landing ends, a restarted hub undoes it
            holder = self._data["agents"].get(self._resolve(held["by"]))
            gone = holder is None and now - held["at"] > ORPHAN_LOCK_LIMIT
            silent = holder is not None and now - max(holder.get("at", now), held["at"]) > SILENT_LOCK_LIMIT
            if gone or silent:
                del self._data["locks"][k]
                changed = True
        messages = self._data["messages"]
        for m in messages.values():
            if m["delivered"] is None and not m.get("lost") and m["to"] not in self._data["agents"]:
                m["lost"] = now  # its session ended before its hook could deliver it
                changed = True
        finished = sorted((k for k, m in messages.items() if m["delivered"] is not None or m.get("lost")),
                          key=lambda k: messages[k]["at"])
        for k in finished[:-SENT_KEPT]:
            del messages[k]
            changed = True
        if changed:
            self._save()

    def _end_rows(self, only=None):
        """Every agent row of a queue item that ended (done, failed, skipped) reads `done` at the item's end time,
        never `working`. `only` limits it to one item key. Call with the lock held; returns whether a row changed."""
        agents, changed = self._data["agents"], False
        for i in self._data["queue"]["items"]:
            row = agents.get(i["key"])
            if i["state"] not in ("done", "failed", "skipped") or row is None or only not in (None, i["key"]):
                continue
            if row.get("state") != "done":
                at = i.get("ended") or self.now()
                row.update(state="done", at=at, since=at)
                self._trail_ended(i["key"])
                changed = True
        return changed

    def _trail_ended(self, agent):
        t = self._trails.get(agent)
        if t and t["ended"] is None:
            t["ended"] = self.now()

    def _trail_add(self, agent, tr, ctx):
        """Fold one hook event (`tr`: kind, tool, label) into the agent's ring of actions."""
        now = self.now()
        t = self._trails.setdefault(agent, {"ring": [], "ctx": None, "ended": None})
        t["ended"] = None
        ring, kind = t["ring"], tr.get("kind")
        tool, label = str(tr.get("tool") or "")[:60], str(tr.get("label") or "")[:140]
        if isinstance(ctx, (int, float)) and not isinstance(ctx, bool):
            t["ctx"] = max(0, min(100, ctx))

        def open_one(sub, name=None):
            return next((a for a in reversed(ring) if a["end"] is None and a["sub"] == sub
                         and (name is None or a["tool"] == name)), None)

        def action(sub=False, end=None, ok=None):
            ring.append({"tool": tool, "label": label, "start": now, "end": end, "ok": ok, "sub": sub})

        if kind == "pre":
            action()
        elif kind in ("post", "fail"):
            a = open_one(False, tool)
            if a is None:
                action(end=now, ok=kind == "post")
            else:
                a["end"], a["ok"] = now, kind == "post"
        elif kind == "substart":
            action(sub=True)
        elif kind == "substop":
            a = open_one(True)
            if a:
                a["end"], a["ok"] = now, True
        elif kind == "refused":
            action(end=now, ok=False)
        elif kind in ("prompt", "stop"):
            if kind == "stop":
                for a in ring:
                    if a["end"] is None:
                        a["end"], a["ok"] = now, True
            action(end=now, ok=True)
        del ring[:-TRAIL_KEPT]

    def _refused(self, agent, tr):
        """A refusal of the guard hook lands on the queue item of that worker: a count and the last few lines."""
        item = next((i for i in self._data["queue"]["items"] if i["key"] == agent), None)
        if item is not None:
            line = "refused: {}: {}".format(tr.get("tool") or "", tr.get("label") or "")[:140]
            item["refused"] = item.get("refused", 0) + 1
            item["refused_lines"] = (item.get("refused_lines", []) + [line])[-5:]
            self._data["queue"]["version"] += 1

    def trail(self, agent):
        """The last actions of one agent, oldest first; KeyError when it has none."""
        with self._lock:
            self._settle()
            t = self._trails[self._resolve(agent)]
            return {"agent": self._resolve(agent), "ctx": t["ctx"], "ended": t["ended"],
                    "actions": [dict(a) for a in t["ring"]]}

    def report(self, d):
        if isinstance(d.get("project"), str) and d["project"]:  # outside the lock: it may ask git once
            where = d["project"]
            if where not in self._roots:
                self._roots[where] = project_root(where)
            d = {**d, "project": self._roots[where]}
        with self._lock:
            sid, alias = d["agent"], d.get("alias")
            if isinstance(alias, str) and alias and alias != sid:
                self._alias(sid, alias)
            agent = self._resolve(sid)
            if d.get("state") == "gone":
                self._remove(agent)
                self._save()
                return {"ok": True, "needs_you": False, "agent": agent}
            new = agent not in self._data["agents"]
            a = self._data["agents"].setdefault(agent, {})
            before = a.get("state")
            tr = d.get("trail")
            if isinstance(tr, dict) and tr.get("kind") == "refused":
                self._refused(agent, tr)
            if isinstance(tr, dict):
                boss = self._resolve(d.get("parent")) if tr.get("kind") in ("substart", "substop") else agent
                self._trail_add(boss, tr, d.get("ctx"))
            if isinstance(d.get("spawn"), str) and d["spawn"]:
                # what this session just sent a subagent to do: the next worker it starts is named by it
                a["spawns"] = (a.get("spawns", []) + [d["spawn"][:60]])[-10:]
            if new and d.get("role") == "worker" and not d.get("ticket"):
                boss = self._data["agents"].get(self._resolve(d.get("parent")), {})
                if boss.get("spawns"):
                    d = {**d, "ticket": boss["spawns"].pop(0)}
            if d.get("role") == "worker" and d.get("parent") == "queue" and not d.get("ticket"):
                title = self._queue_title(agent)  # a worker the hub started: its id is its ticket's key
                if title:
                    d = {**d, "ticket": title}
            if usable_project(d.get("project")) and d["project"] not in self.providers and d["project"] not in self.queued:
                self.queued.add(d["project"])
                self.changed.set()
            session = d.get("session")
            if isinstance(session, str) and session:
                if a.setdefault("session", session) != session:
                    d = {**d, "asked": None, "note": None}  # a helper's session (loop checker) inherited our name
            for f in AGENT_FIELDS:
                if d.get(f) in (None, ""):
                    continue
                if agent != sid and (f in ("name", "role") or f == "project" and f in a):
                    continue  # a session's hook events never rename the agent it reports as
                a[f] = self._resolve(d[f]) if f == "parent" else d[f]
            rows = self._tcache[1]
            if rows is not None and a.get("ticket"):  # every report, a hook's too: a chat started before counts
                was = a.get("ref")
                ref = ticket_ref(a.get("ticket"), a.get("map"), a.get("project"), rows)
                if ref:
                    a["ref"] = ref  # the open ticket it works on, so the run counts and draws it
                else:
                    a.pop("ref", None)
                if was and was != ref and was not in {sbqueue.key(t) for t in rows}:
                    self._chat_closed(agent, was)
            a["at"] = self.now()
            self._chat_run(agent, a)
            after = a.get("state")
            if after is not None and (after != before or "since" not in a):
                a["since"] = a["at"]  # when the agent entered its current state, for "working 14m"
            if after == "done" and a.get("role") == "worker":
                self._trail_ended(agent)
            self._save()
            out = {"ok": True, "needs_you": after in ALERT_STATES and after != before, "agent": agent}
            if d.get("ticket") not in (None, "") and rows is not None:
                out["ref"] = a.get("ref")  # null: the ticket named no open ticket the hub knows
            return out

    def _chat_run(self, agent, a):
        """Keep the stretch of work a chat (not a queue worker) does on its matched ticket: one row from its first
        report on it to its last, in the run that was live when it started. A gap over CHAT_IDLE starts a new row."""
        ref, now = a.get("ref"), self.now()
        if not ref or a.get("parent") == "queue" or a.get("state") not in CHAT_WORKING:
            return
        runs = self._data.setdefault("chat_runs", [])
        run = next((r for r in reversed(runs) if r["agent"] == agent and r["key"] == ref), None)
        if run is not None and now - run["last"] < CHAT_IDLE:
            run["last"] = now
            return
        runs.append({"key": ref, "agent": agent, "night": self._data["queue"].get("night"), "started": now, "last": now})
        self._data["chat_runs"] = [r for r in runs if now - r["last"] < CHAT_RUNS_KEPT][-500:]

    def _chat_closed(self, agent, key):
        """The ticket a chat worked on left the open list (resolved): its latest stretch on it ended with it done."""
        run = next((r for r in reversed(self._data.get("chat_runs") or []) if r["agent"] == agent and r["key"] == key), None)
        if run is not None:
            run["closed"] = True

    def _queue_title(self, key):
        item = next((i for i in self._data["queue"]["items"] if i["key"] == key), None)
        if item and item.get("title"):
            return item["title"]
        return next((t.get("title") for t in self._tcache[1] or [] if sbqueue.key(t) == key), None)

    def lock(self, key, by, landing=None):
        """`landing`: the hub's own landing that takes it (see TicketRun._land), kept with the lock so a restarted hub
        can undo a landing it left half done."""
        with self._lock:
            held = self._data["locks"].get(key)
            if held and held["by"] != by:
                return {"ok": False, "held_by": held["by"]}
            self._data["locks"][key] = {"by": by, "at": self.now(), **({"landing": landing} if landing else {})}
            self._save()
            return {"ok": True}

    def unlock(self, key, by):
        with self._lock:
            held = self._data["locks"].get(key)
            if held and held["by"] == by:
                del self._data["locks"][key]
                self._save()
            return {"ok": True}

    def ask(self, agent, q, options, default, wait):
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not math.isfinite(wait) or wait < 0:
            raise ValueError("wait must be a number of seconds, 0 or more")
        if not isinstance(q, str) or not q:
            raise ValueError("the question must be text")
        if not isinstance(options, list) or not 2 <= len(options) <= 4:
            raise ValueError("a question takes two to four options")
        if not all(isinstance(o, str) and o for o in options) or len(set(options)) != len(options):
            raise ValueError("the options must be distinct, non-empty text")
        if default not in options:
            raise ValueError("the default must be one of the options")
        qid = uuid.uuid4().hex[:8]
        with self._lock:
            now = self.now()
            self._data["questions"][qid] = {
                "agent": agent, "q": q, "options": list(options), "default": default,
                "asked": now, "deadline": now + wait, "answer": None, "by": None}
            self._save()
        return {"ok": True, "id": qid}

    def answer(self, qid, answer, by="you"):
        with self._lock:
            self._settle()
            q = self._data["questions"][qid]
            if answer not in q["options"]:
                raise ValueError("the answer must be one of the options")
            if q["answer"] is None:
                q["answer"], q["by"], q["answered"] = answer, by, self.now()
                self._save()
            return {"ok": True}

    def send(self, to, text):
        """Queue a message from the owner for one session or worker; its hook delivers it."""
        if not isinstance(to, str) or not to:
            raise ValueError("say which session the message is for")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("the message is empty")
        if len(text) > MESSAGE_MAX:
            raise ValueError("a message is at most {} characters".format(MESSAGE_MAX))
        with self._lock:
            agent = self._resolve(to)
            if agent not in self._data["agents"]:
                raise ValueError("no such session")
            mid = uuid.uuid4().hex[:8]
            self._data["messages"][mid] = {"to": agent, "text": text.strip(), "at": self.now(),
                                           "delivered": None, "how": None}
            self._save()
        return {"ok": True, "id": mid}

    def unsend(self, mid):
        """Take back a message its session has not picked up yet."""
        with self._lock:
            m = self._data["messages"][mid]
            if m["delivered"] is not None:
                raise ValueError("already delivered")
            del self._data["messages"][mid]
            self._save()
            return {"ok": True}

    def take(self, agent, how):
        """The queued messages for an agent, oldest first, marked delivered (by `how`: the hook event)."""
        with self._lock:
            me = self._resolve(agent)
            mine = sorted((m for m in self._data["messages"].values()
                           if m["to"] == me and m["delivered"] is None and not m.get("lost")),
                          key=lambda m: m["at"])
            for m in mine:
                m["delivered"], m["how"] = self.now(), how if isinstance(how, str) else None
            if mine:
                self._save()
            return {"ok": True, "messages": [m["text"] for m in mine]}

    def question(self, qid):
        with self._lock:
            self._settle()
            return dict(self._data["questions"][qid])

    def state(self):
        with self._lock:
            self._settle()
            out = json.loads(json.dumps({k: v for k, v in self._data.items() if k != "nights"}))
            charge = out.setdefault("charge", {})
            for k, v in out["agents"].items():
                v["agent"] = k
                if v.get("role") == "worker" and v.get("parent") == "queue":
                    v["map"] = sbqueue.map_of(k)
                    if charge.get(v["map"]) in out["agents"]:
                        v["in_charge"] = charge[v["map"]]
            out = {**out, "now": self.now(), "providers": dict(self.providers),
                   "review_next_at": review_next_at(out["queue"]["items"])}
            if self.queue_lock is not None:
                out["queue_lock"] = dict(self.queue_lock)
            return out

    # ---- tonight's queue and the installed agents ----

    def _fetch(self, run=None):
        """Open tickets from sbmap (or `run`, which returns the list or its JSON); None when that failed."""
        try:
            if run is None:
                run = self._run or (lambda: subprocess.run(
                    [sys.executable, str(SBMAP), "tickets", "--json"], capture_output=True, text=True,
                    timeout=60, check=True).stdout)
            rows = run()
            rows = json.loads(rows) if isinstance(rows, (str, bytes)) else rows
            return rows if isinstance(rows, list) else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _open_tickets(self, run=None, fresh=False):
        """The cached sbmap list (15 s), or None when sbmap failed and nothing is cached. An explicit
        `run` or `fresh` skips the cache. Runs outside the lock: sbmap is slow."""
        with self._lock:
            at, rows = self._tcache
            failed = self._tfailed
        if run is None and not fresh:
            if rows is not None and self.now() - at < TICKETS_CACHED_FOR:
                return rows
            if failed is not None and self.now() - failed < TICKETS_FAILED_FOR:
                return rows
        got = self._fresh_tickets(run)
        if got is not None:
            return got
        with self._lock:
            return self._tcache[1]

    def _fresh_tickets(self, run=None):
        """The open tickets read now, which also refreshes the cache; None when sbmap failed (never the cache)."""
        got = self._fetch(run)
        with self._lock:
            if got is not None:
                self._tcache = (self.now(), got)
                self._rekey(got)
            self._tfailed = None if got is not None else self.now()
        return got

    def _rekey(self, rows):
        """A ticket moved to another map (sbmap move) keeps its queue item: same project and number, the item's
        key and map become the new map's. Items a worker or review holds wait; the caller holds the lock."""
        q = self._data["queue"]
        have = {sbqueue.key(t) for t in rows}
        new = {(t["map"].split("/")[0], int(t["num"])): t for t in rows}  # a map is <project>/<effort>
        moved = False
        for i in q["items"]:
            if i.get("kind") != "ticket" or i["key"] in have or i["state"] in ("running", "review") or "#" not in i["key"]:
                continue
            t = new.get((i["key"].split("/")[0], int(i["key"].rsplit("#", 1)[1])))
            if t and sbqueue.key(t) not in {x["key"] for x in q["items"]}:
                self._renamed[i["key"]] = sbqueue.key(t)
                i["key"], moved = sbqueue.key(t), True
                if "map" in i:
                    i["map"] = t["map"]
        if moved:
            q["version"] += 1
            self._save()

    def _moved(self, key):
        """`key` as the queue names it now: the tickets are read afresh (the cache may predate an sbmap move),
        which re-keys an item whose ticket moved to another map."""
        if "#" in key:
            self._fresh_tickets()
        return self._renamed.get(key, key)

    def tickets(self, run=None, fresh=False):
        """Open tickets with `state`/`reason` (sbqueue.classify) and `queued`. Reading them never ticks one:
        only the owner's own ticks queue a ticket."""
        rows = self._open_tickets(run, fresh) or []
        with self._lock:
            live = self._live_keys()
        queued = {sbqueue.key(t) for t in rows} & live
        return [{**t, "queued": sbqueue.key(t) in queued,
                 **dict(zip(("state", "reason"), sbqueue.classify(t, live, rows)))} for t in rows]

    MAP_NAME = re.compile(r"[\w.\- ]+(?:/[\w.\- ]+)*")

    def map_tickets(self, name):
        """One map and every ticket of it, resolved and out of scope too (sbmap `tickets --map`, cached like the
        ticket list), each with the hub's state word, its place in the queue and its last run's outcome.
        KeyError when there is no such map."""
        if not isinstance(name, str) or ".." in name or not self.MAP_NAME.fullmatch(name):
            raise KeyError(name)
        now = self.now()
        with self._lock:
            at, got = self._mcache.get(name, (0.0, None))
        if now - at >= TICKETS_CACHED_FOR:
            rc, out, _ = sbmap_call("tickets", "--json", "--map", name)
            try:
                got = json.loads(out) if rc == 0 else None
            except ValueError:
                got = None
            with self._lock:
                self._mcache = {k: v for k, v in self._mcache.items() if now - v[0] < TICKETS_CACHED_FOR}
                self._mcache[name] = (now, got)
        if got is None:
            raise KeyError(name)
        rows = {t["num"]: t for t in self.tickets() if t["map"] == got["map"]}
        with self._lock:
            q = self._data["queue"]
            items = [i for i in q["items"] if i["kind"] == "ticket"]
            place = {i["key"]: n for n, i in enumerate((i for i in items if i["state"] == "queued"), 1)}
            ran = {}
            past = [i for n in self._data.get("nights") or [] for i in n.get("items") or [] if i["kind"] == "ticket"]
            for i in [i for i in q.get("cleared") or [] if i["kind"] == "ticket"] + past + items:  # the newest wins
                if i["state"] != "queued":
                    ran[i["key"]] = {"state": i["state"], "note": i.get("note") or "", "ended": i.get("ended")}
        out = []
        for t in got["tickets"]:
            key = "{}#{}".format(got["map"], t["num"])
            word = {"resolved": "done", "out-of-scope": "out of scope"}.get(t["status"]) or (
                rows[t["num"]]["state"] if t["num"] in rows else "claimed" if t["status"] == "claimed" else "not ready")
            out.append({**t, "state": word, "place": place.get(key), "last_run": ran.get(key)})
        return {**got, "tickets": out}

    def _live_keys(self):
        return {i["key"] for i in self._data["queue"]["items"]
                if i["kind"] == "ticket" and i["state"] in ("queued", "running", "landed", "review", "unclean")}

    @staticmethod
    def _item(key):
        return {"key": key, "kind": "ticket", "agent": None, "state": "queued", "note": "", "commit": None,
                "tries": 0, "started": None, "ended": None}

    def _apply_selection(self, q, keys, rows):
        """Queued tickets become `keys`; every other item stays where it was, in front. What was queued keeps its
        place (the owner's drops are not re-sorted); a new ticket goes last in its map, after its blockers and
        before what waits on it, and a new map after the queued ones (sbqueue.order). A failed or skipped ticket
        that is ticked again is queued afresh (a stop time or a passing error is no reason to keep it out); a
        running or done one is never queued twice."""
        want = set(keys)
        have = {i["key"]: i for i in q["items"] if i["kind"] == "ticket"}
        before = [i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
        again = lambda i: i["kind"] == "ticket" and (
            i["state"] == "queued" or i["state"] in ("failed", "skipped") and i["key"] in want)
        keep = [i for i in q["items"] if not again(i)]
        taken = {i["key"] for i in keep if i["kind"] == "ticket"}
        keys = [k for k in dict.fromkeys(keys) if k not in taken]
        running = taken & self._live_keys()
        maps = sbqueue.map_list(q.get("maps"), [i["key"] for i in keep if i["key"] in running] + before)
        ordered = [k for k in sbqueue.order(rows, keys + sorted(running), maps) if k in keys]
        known = {sbqueue.key(t) for t in rows}
        ordered += [k for k in keys if k not in known and k in have]  # no longer listed: kept, not dropped
        seq = [k for k in before if k in ordered]
        for k in ordered:
            if k not in seq:
                m = sbqueue.map_of(k)
                end = max((n + 1 for n, x in enumerate(seq) if sbqueue.map_of(x) == m), default=len(seq))
                seq = sbqueue.move(seq, k, end, rows)
        q["maps"] = sbqueue.map_list(maps, seq)
        freed = sbqueue.chains(rows, seq + sorted(running))
        fresh = lambda k: {**self._item(k), "note": "frees %d" % freed[k] if freed.get(k) else ""}
        q["items"] = keep + [self._afresh(have.get(k)) or fresh(k) for k in seq]

    @staticmethod
    def _sync_maps(q):
        """The queued maps: each map with a ticket queued or at work, in the owner's order, a map not named yet
        after them where its first ticket is; the queued tickets are arranged map by map, each keeping its place
        inside its map. Every other item stays where it is."""
        items = q.setdefault("items", [])
        live = [i["key"] for i in items if i.get("kind") == "ticket" and i.get("state") in ("queued",) + sbqueue.HOLDING]
        q["maps"] = [m for m in sbqueue.map_list(q.get("maps"), live) if any(sbqueue.map_of(k) == m for k in live)]
        place = {m: n for n, m in enumerate(q["maps"])}
        at = [n for n, i in enumerate(items) if i.get("kind") == "ticket" and i.get("state") == "queued"]
        ranked = sorted((items[n] for n in at), key=lambda i: place.get(sbqueue.map_of(i["key"]), len(place)))
        for n, i in zip(at, ranked):
            items[n] = i

    def _afresh(self, item):
        """A failed or skipped item queued again: its last try's outcome is cleared; the owner's agent stays."""
        if item is None or item["state"] == "queued":
            return item
        for f in ("retry", "digested", "runner", "pid", "pid_start", "result", "base_sha", "first_base", "resume", "stops",
                  "log_start", "checked", "verdict", "review", "redo", "stop_asked", "fails"):
            item.pop(f, None)
        item.update(state="queued", note="", ended=None, tries=0, started=None, commit=None)
        return item

    def _queue_write(self, version, change, needs_tickets=False, by=None):
        """One accepted queue write: stale versions are refused, the rest bump the version once. What it adds
        joins the live night; with none live, it starts one (by `by`, the session that queued)."""
        rows = []
        if needs_tickets:
            rows = self._open_tickets()
            if rows is None:
                raise ValueError("tickets unavailable")
        with self._lock:
            q = self._data["queue"]
            if version is not None and version != q["version"]:
                return {"ok": False, "stale": True, "queue": json.loads(json.dumps(q))}
            live = self._night_live()
            backup = json.loads(json.dumps(q)) if live and live["state"] == "stopping" else None
            change(q, rows)
            new = [i for i in q["items"] if not i.get("night") and not i.get("close_off")]
            if new and backup is not None:
                self._data["queue"] = backup
                raise ValueError("the night is stopping: queue again once it has ended")
            if new:
                live = live or self._night_start(by=by)
                for i in new:
                    i["night"] = live["id"]
            self._sync_maps(q)
            self._night_settle()
            q["version"] += 1
            self._save()
            self.queue_kick.set()
            return {"ok": True, "queue": json.loads(json.dumps(q))}

    # ---- nights: one sb tonight, with a start, an end and the items that belong to it ----

    NIGHT_ENDED = ("done", "failed", "skipped")

    def _ever(self, q):
        """Every item the hub still holds, the live line first, then each night's record newest first, then cleared."""
        past = [i for n in reversed(self._data.get("nights") or []) for i in n.get("items") or []]
        return q["items"] + past + (q.get("cleared") or [])

    def _night_live(self):
        """The night that is live or stopping, or None."""
        nid = self._data["queue"].get("night")
        return next((n for n in self._data.get("nights") or [] if n["id"] == nid), None)

    def _night_start(self, name=None, by=None):
        """Open a night (the lock is held). ValueError while another is live or stopping."""
        live = self._night_live()
        if live:
            raise ValueError("a night is already {}: {} ({})".format(live["state"], live["name"], live["id"]))
        now = self.now()
        stamp = datetime.fromtimestamp(now)
        ids = {n["id"] for n in self._data["nights"]}
        base = "night-" + stamp.strftime("%Y%m%d-%H%M%S")
        nid, k = base, 1
        while nid in ids:
            k += 1
            nid = "{}-{}".format(base, k)
        night = {"id": nid, "name": (str(name).strip() if name else "") or stamp.strftime("Night of %Y-%m-%d, %H:%M"),
                 "started": now, "by": self._resolve(by) if isinstance(by, str) and by else None, "state": "live",
                 "ended": None, "how": None, "not_reached": []}
        self._data["nights"].append(night)
        self._data["queue"]["night"] = nid
        return night

    def _migrate_nights(self):
        """A state saved before nights: its ended items become one ended night, 'Before runs'; what is queued or
        at work becomes a live night started now."""
        d, now = self._data, self.now()
        q = d["queue"]
        if "nights" in d:
            q.setdefault("night", None)
            return
        d["nights"], q["night"] = [], None
        items = q.setdefault("items", [])
        ended = [i for i in items if i.get("state") in self.NIGHT_ENDED]
        rest = [i for i in items if i.get("state") not in self.NIGHT_ENDED]
        if ended:
            stamps = [i[f] for i in ended for f in ("started", "created") if i.get(f)] or [now]
            done = max([i["ended"] for i in ended if i.get("ended")] or [now])
            for i in ended:
                i["night"] = "night-before-runs"
            d["nights"].append({"id": "night-before-runs", "name": "Before runs", "started": min(stamps), "by": None,
                                "state": "ended", "ended": done, "how": "finished", "not_reached": [], "items": ended})
        q["items"] = rest
        live = [i for i in rest if not i.get("close_off")]
        if live:
            night = self._night_start()
            for i in live:
                i["night"] = night["id"]
        if items:
            self._save()

    @staticmethod
    def _night_counts(items, not_reached):
        states = [i.get("state") for i in items]
        return {"items": len(items), "queued": states.count("queued"), "done": states.count("done"),
                "failed": states.count("failed"), "skipped": states.count("skipped"),
                "running": sum(1 for s in states if s not in ("queued", "done", "failed", "skipped")),
                "not_reached": len(not_reached)}

    def _night_view(self, night, with_items=False):
        items = night.get("items")
        if items is None:
            items = [i for i in self._data["queue"]["items"] if i.get("night") == night["id"]]
        out = {k: night[k] for k in ("id", "name", "started", "by", "state", "ended", "how", "not_reached")}
        out["counts"] = self._night_counts(items, night["not_reached"])
        if with_items:
            out["items"] = items
        return json.loads(json.dumps(out))

    def nights(self):
        """Every night, newest first, with its counts and without its items."""
        with self._lock:
            return {"nights": [self._night_view(n) for n in reversed(self._data["nights"])]}

    def night(self, nid):
        """One night with its items; KeyError when there is none."""
        with self._lock:
            n = next((n for n in self._data["nights"] if n["id"] == nid), None)
            if n is None:
                raise KeyError(nid)
            return {"night": self._night_view(n, with_items=True)}

    def night_start(self, name=None, by=None):
        with self._lock:
            night = self._night_start(name, by)
            self._data["queue"]["version"] += 1
            self._save()
            return {"ok": True, "night": self._night_view(night)}

    def night_rename(self, name):
        """Give the live (or stopping) night another name."""
        name = str(name or "").strip()
        if not name:
            raise ValueError("a night needs a name")
        with self._lock:
            night = self._night_live()
            if night is None:
                raise ValueError("no night is live")
            night["name"] = name
            self._data["queue"]["version"] += 1
            self._save()
            return {"ok": True, "night": self._night_view(night)}

    def night_stop(self, mode):
        """Stop after: nothing new starts, what runs finishes and is judged, then the night ends as stopped by
        you. What it never reached leaves the line, stays open and is listed on the night."""
        if mode != "after":
            raise ValueError("mode must be 'after'")
        with self._lock:
            night = self._night_live()
            if night is None:
                raise ValueError("no night is live")
            night["state"] = "stopping"
            self._night_settle()
            self._data["queue"]["version"] += 1
            self._save()
            self.queue_kick.set()
            return {"ok": True, "night": self._night_view(night)}

    def _night_settle(self, ending=True):
        """(the lock is held) Look at the live night: while it stops, what is queued leaves the line as not
        reached; once none of its items is queued or at work it ends, and its items leave the line for its record.
        Finished close-off jobs, which belong to no night, go to the cleared log. True when anything changed."""
        q = self._data["queue"]
        changed = False
        gone = [i for i in q["items"] if not i.get("night") and i.get("state") in self.NIGHT_ENDED]
        if gone:
            q["items"] = [i for i in q["items"] if i not in gone]
            q["cleared"] = ((q.get("cleared") or []) + gone)[-CLEARED_KEPT:]
            changed = True
        night = self._night_live()
        if night is None:
            return changed
        mine = [i for i in q["items"] if i.get("night") == night["id"]]
        stopping = night["state"] == "stopping"
        if stopping:
            for i in [i for i in mine if i["state"] == "queued"]:
                night["not_reached"].append({"key": i["key"], "title": i.get("title") or self._queue_title(i["key"]) or ""})
                q["items"].remove(i)
                mine.remove(i)
                changed = True
            q["maps"] = [m for m in q.get("maps") or [] if any(sbqueue.map_of(i["key"]) == m for i in q["items"])]
        # A stopping night waits only for work in flight: an item that landed, rechecks or waits on a clean
        # checkout cannot be started or judged while the night stops, so it must not hold the night open
        # (night-20261117-014410 stayed 'stopping' 17 hours on such items).
        open_states = ("running", "review") if stopping else None
        if not ending or any((i["state"] in open_states) if stopping else (i["state"] not in self.NIGHT_ENDED)
                             for i in mine) or not (stopping or mine):
            return changed
        how = "stopped" if stopping else "stop_time" if night.get("stop_time") else "finished"
        night.pop("stop_time", None)
        night.update(state="ended", ended=self.now(), how=how, items=mine)
        q["items"] = [i for i in q["items"] if i not in mine]
        q["night"] = None
        q["version"] += 1
        return True

    def _take_charge(self, agent, maps):
        """Session `agent` is in charge of each of `maps` that no other live session is in charge of."""
        agent = self._resolve(agent) if isinstance(agent, str) and agent else None
        if agent is None or agent not in self._data["agents"]:
            return
        charge = self._data.setdefault("charge", {})
        for m in maps:
            if charge.get(m) not in self._data["agents"]:
                charge[m] = agent

    def queue_set(self, keys, version, agent=None):
        """Replace the ticket selection (jobs, running and finished items untouched). A live session `agent`
        that adds tickets is in charge of their maps, unless another live session already is."""
        def change(q, rows):
            queued = {i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"}
            self._apply_selection(q, list(keys), rows)
            q["seeded"] = True
            self._take_charge(agent, {sbqueue.map_of(k) for k in keys if k not in queued})
        return self._queue_write(version, change, needs_tickets=True, by=agent)

    def queue_move(self, key, to_index, version):
        """Move a queued ticket among the queued tickets, clamped by its blockers and dependents."""
        def change(q, rows):
            queued = [i for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
            by = {i["key"]: i for i in queued}
            if key not in by:
                raise ValueError("not a queued ticket: {}".format(key))
            moved = sbqueue.move([i["key"] for i in queued], key, int(to_index), rows)
            others = [i for i in q["items"] if i not in queued]
            q["items"] = others + [by[k] for k in moved]
        return self._queue_write(version, change, needs_tickets=True)

    def queue_map(self, name, version, agent=None):
        """Queue every open ticket of map `name` that can run, in order, at the map's place (last when it is new):
        what waits on an earlier ticket of the map comes too and starts when that one lands. The answer's
        `left_out` names each ticket left out with why (it needs the owner, has no done-when or checks, is claimed,
        or waits on a map that is not queued)."""
        left = []

        def change(q, rows):
            if not any(t["map"] == name for t in rows):
                raise ValueError("no open ticket in map {}".format(name))
            queued = [i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
            keys, out = sbqueue.map_queueable(rows, name, self._live_keys())
            left.extend({"key": k, "reason": r} for k, r in out)
            q["maps"] = sbqueue.map_list(q.get("maps"), queued + keys)
            self._apply_selection(q, queued + keys, rows)
            q["seeded"] = True
            if keys:
                self._take_charge(agent, {name})
        out = self._queue_write(version, change, needs_tickets=True, by=agent)
        return {**out, "left_out": left} if out["ok"] else out

    def queue_move_map(self, name, to_index, version):
        """Move a queued map to place `to_index` among the queued maps; its tickets keep their order."""
        def change(q, rows):
            self._sync_maps(q)
            maps = list(q["maps"])
            if name not in maps:
                raise ValueError("not a queued map: {}".format(name))
            maps.remove(name)
            maps.insert(max(0, min(int(to_index), len(maps))), name)
            q["maps"] = maps
        return self._queue_write(version, change)

    def queue_remove_job(self, key, version):
        """Take a queued job out of the queue; it no longer counts as a duplicate. Running and finished
        items are never removed, and tickets are unticked with queue_set."""
        def change(q, rows):
            item = next((i for i in q["items"] if i["key"] == key), None)
            if item is None or item["kind"] != "job":
                raise ValueError("not a job in the queue: {}".format(key))
            if item["state"] != "queued":
                raise ValueError("only a queued job can be removed; this one is {}".format(item["state"]))
            q["items"].remove(item)
        return self._queue_write(version, change)

    def queue_stop(self, key, reason, version):
        """The owner's Stop: a running item is marked `stop_asked` with the reason; the supervisor's next tick (at
        once: the write kicks it) kills its worker's whole process group and ends it as stopped by you (_stop_asked).
        Its work is never stashed, reset or deleted."""
        words = " ".join(str(reason or "").split())
        if not words:
            raise ValueError("say why it stops")

        def change(q, rows):
            item = next((i for i in q["items"] if i["key"] == key), None)
            if item is None or item["state"] != "running":
                raise ValueError("not a running item: {}".format(key))
            item["stop_asked"] = {"reason": words, "at": self.now()}
            item["note"] = "stopping, by you: " + words
        return self._queue_write(version, change)

    def run_seen(self, key):
        """Mark one ended run looked at (`<key>@<ended>`). It leaves Waits for you and stays in History;
        nothing in the queue or the vault changes. Marking twice is harmless."""
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key is the run's key and its end time")
        with self._lock:
            seen = [k for k in self._data.get("seen") or [] if k != key] + [key]
            self._data["seen"] = seen[-SEEN_KEPT:]
            self._save()
            return {"ok": True}

    def agents_dismiss(self, agent):
        """Take one session row (and its workers) off the board; the session itself is never stopped or told,
        and its next hook event brings its row back."""
        with self._lock:
            agent = self._resolve(agent)
            if agent not in self._data["agents"]:
                raise ValueError("no such session")
            self._remove(agent)
            self._save()
            return {"ok": True}

    def review_now(self):
        """POST /api/review/now: the queue's supervisor starts every review the timer would, at once; a hub that runs
        no queue (read-only beside another) starts none."""
        sup = self.supervisor
        return {"ok": True, "started": sup.review_now() if sup else []}

    def agents_clear_quiet(self):
        """Take off the board every row idle or waiting on "your turn" for over QUIET_FOR, and every finished
        worker; display state only, like agents_dismiss."""
        with self._lock:
            now, agents = self.now(), self._data["agents"]
            quiet = [k for k, a in agents.items()
                     if a.get("role") == "worker" and a.get("state") == "done"
                     or a.get("state") in ("idle", "your turn") and now - (a.get("since") or a.get("at") or now) > QUIET_FOR]
            for k in quiet:
                if k in agents:
                    self._remove(k)
            self._save()
            return {"ok": True, "cleared": len(quiet)}

    def item_file(self, key, what):
        """(path, text) of a queue item's worker report (`report`) or log (`log`, its last LOG_SERVED bytes);
        the path is the item's own, never one from the request. KeyError when it has none."""
        with self._lock:
            q = self._data["queue"]
            item = next((i for i in self._ever(q) if i["key"] == key), None)
        if item is None:
            raise KeyError(key)
        if what == "log":
            path = item.get("log")
        elif item["kind"] == "job":
            path = item.get("result")
        else:
            path = item.get("run") and str(Path(item["run"]) / "{}.md".format(key.rsplit("#", 1)[-1]))
        if not path or not os.path.isfile(path):
            raise KeyError(key)
        return path, _tail(path, 0, LOG_SERVED) if what == "log" else Path(path).read_text(encoding="utf-8", errors="replace")

    def _run_items(self):
        with self._lock:
            q = self._data["queue"]
            return json.loads(json.dumps(self._ever(q)))

    def runs(self, since=0, offset=0, limit=100):
        """Every run for History: the queue's finished ticket items and the vault's run folders, newest first."""
        return sbruns.list_runs(_vault(), self._run_items(), since, offset, limit)

    def run(self, key):
        """One run with its checks, report and the end of its log; KeyError when nobody knows it."""
        return sbruns.detail(_vault(), self._run_items(), key)

    def _media_dir(self, item):
        """A ticket item's media folder, <run folder>/<num>-media, or None for a job or an item that never ran."""
        if item.get("kind") == "job" or not item.get("run") or "#" not in item["key"]:
            return None
        return Path(item["run"]) / "{}-media".format(item["key"].rsplit("#", 1)[-1])

    def media_of(self, key):
        """The pictures and clips a worker left for this item (see media_in)."""
        with self._lock:
            item = next((i for i in self._data["queue"]["items"] if i["key"] == key), None)
        d = item and self._media_dir(item)
        return media_in(d.parent, d.name.split("-", 1)[0]) if d else []

    def media_file(self, key, name):
        """(path, content type) of one of an item's recorded media; KeyError for a name it did not record, a name
        with a path in it, or a file that now resolves outside its media folder."""
        with self._lock:
            q = self._data["queue"]
            item = next((dict(i) for i in self._ever(q) if i["key"] == key), None)
        if item is None or not name or name not in (item.get("media") or []) or any(c in name for c in ("/", "\\", "..")):
            raise KeyError(name)
        d = self._media_dir(item)
        f = d and (d / name).resolve()
        if not f or f.parent != d.resolve() or f.suffix.lower() not in MEDIA_TYPES or not f.is_file():
            raise KeyError(name)
        return f, MEDIA_TYPES[f.suffix.lower()]

    # ---- the page's side panel: a ticket's details and actions; the vault is written only through sbmap ----

    def _ticket_file(self, key):
        """(map, num, the open row or None, the ticket's file or None) of a well-formed key; KeyError otherwise."""
        m = re.fullmatch(r"([\w.-]+(?:/[\w.-]+)*)#(\d+)", str(key))
        if not m or any(p in ("", ".", "..") for p in m.group(1).split("/")):
            raise KeyError(key)
        name, num = m.group(1), int(m.group(2))
        row = next((t for t in self._open_tickets() or [] if sbqueue.key(t) == "{}#{}".format(name, num)), None)
        if row and row.get("file") and os.path.isfile(row["file"]):
            return name, num, row, Path(row["file"])
        issues = _vault() / "wayfinder" / name / "issues"  # resolved and dropped ones live in issues/done
        found = sorted(p for d in (issues, issues / "done") for p in d.glob("{:03d}[ -]*.md".format(num)))
        return name, num, row, (found[0] if found else None)

    def ticket_detail(self, key):
        """What the side panel shows beyond the ticket row: its comments, its map's checks, the map's handoff,
        checkpoint and newest run board (age and first line), and obsidian:// links built by `sbmap uri`."""
        name, num, row, path = self._ticket_file(key)
        if path is None:
            raise KeyError(key)
        text = path.read_text(encoding="utf-8", errors="replace")
        rc, out, _ = sbmap_call("info", name)
        checks = next((l[len("checks: "):].split("; ") for l in out.splitlines() if l.startswith("checks: ")), [])
        rc, out, _ = sbmap_call("status", name)
        line = next((l for l in out.splitlines() if l.startswith("handoff/checkpoint: ")), "")
        files = [_vault() / f for f in line[len("handoff/checkpoint: "):].split(", ") if f and f != "none"]
        own = [f for f in files if f.name in ("handoff.md", "checkpoint.md")]
        runs = [f for f in files if f not in own][:1]  # sbmap lists run boards newest first
        trail = []
        for f in own + runs:
            if f.is_file():
                trail.append({"name": f.name, "path": str(f), "at": f.stat().st_mtime, "first": _first_words(f),
                              "uri": obsidian_uri(f)})
        comments = re.search(r"^## Comments[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        named = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", text.split("\n---", 1)[0] if text.startswith("---\n") else "", re.M)
        return {"key": key, "title": (row or {}).get("title") or (named.group(1) if named else _first_words(path, heading=True)),
                "file": str(path),
                "open": row is not None, "comments": [c.strip() for c in re.split(r"\n(?=- )", comments.group(1).strip())
                                                       if c.strip()] if comments else [],
                "map_checks": checks, "trail": trail, "uri": obsidian_uri(path),
                "map_uri": obsidian_uri(_vault() / "wayfinder" / name / "map.md")}

    def ticket_action(self, action, key, text=None, commit=None):
        """Done, Drop, Release, Comment, Tier or Checks on one ticket through sbmap; refused while a queue worker
        runs it. A failed sbmap raises ValueError with sbmap's message; a done one refreshes the ticket list."""
        if action not in TICKET_ACTIONS:
            raise ValueError("unknown action: {}".format(action))
        key = self._moved(key)
        if action == "recheck":
            return self.recheck_now(key)
        with self._lock:
            busy = next((i["state"] for i in self._data["queue"]["items"]
                         if i["key"] == key and i["state"] in ("running", "review")), None)
        if busy:
            raise ValueError("a worker is running it; wait until it ends" if busy == "running" else
                             "its Opus review is running; wait until it ends")
        try:
            name, num, row, path = self._ticket_file(key)
        except KeyError:
            raise ValueError("no such ticket") from None
        words = " ".join(str(text or "").split())
        if action in ("done", "drop", "comment", "rule", "checks", "tier", "done_when") and not words:
            raise ValueError("type a line first")
        if action != "comment" and row is None:
            raise ValueError("the ticket is no longer open")
        nnn = "{:03d}".format(num)
        if action == "done":
            sha = str(commit or "").strip()
            calls = [["resolve", name, nnn, "--gist", words, "--answer", "Closed from the hub page: " + words]
                     + (["--commit", sha] if sha else []) + (["--repo-root", row["repo"]] if sha and row.get("repo") else [])]
        elif action == "drop":
            calls = [["comment", name, nnn, "--text", "Dropped from the hub page: " + words],
                     ["set", name, nnn, "status=out-of-scope"]]
        elif action == "release":
            if row.get("status") != "claimed":
                raise ValueError("it is not claimed")
            calls = [["set", name, nnn, "status=open"]]
        elif action == "comment":
            if path is None:
                raise ValueError("no such ticket")
            calls = [["comment", name, nnn, "--text", words]]
        elif action == "rule":
            calls = [["rule", name, nnn, "--text", words]]
        elif action == "tier":
            calls = [["set", name, nnn, "tier=" + words]]
        elif action in STEER:
            label, old_key = STEER[action]
            old = row.get(old_key) or ""
            old = "; ".join(str(x) for x in old) if isinstance(old, list) else str(old)
            if action == "done_when":
                change = ["set", name, nnn, "done_when=" + str(text).strip().replace("\n", "\\n")]
            elif action == "paths":
                change = ["set", name, nnn, "paths=" + ",".join(p.strip() for p in str(text or "").splitlines() if p.strip())]
            else:
                change = ["block", name, nnn, ",".join(r.strip() for r in re.split(r"[,\s]+", str(text or "")) if r.strip()) or "none"]
            rc, out, err = sbmap_call(*change)
            if rc != 0:
                raise ValueError(err or out or "sbmap failed")
            calls = [["comment", name, nnn, "--text", "Owner changed {} from the hub; it was: {}".format(
                label, " ".join(old.split()) or "empty")]]
        else:
            calls = [["mapset", name, "checks=" + str(text).strip()]]
        for c in calls:
            rc, out, err = sbmap_call(*c)
            if rc != 0:
                raise ValueError(err or out or "sbmap failed")
        self._fresh_tickets()
        return {"ok": True}

    def queue_integrate(self, keys):
        """A Unity pass for failed tickets of a Unity project whose work is in the checkout already: each is queued
        again (a ticket of a night that ended joins the live one, as a copy of its last item), and when it starts
        no worker runs: the integrator takes the repo's Unity lock, plays what the ticket's review found short on
        the checkout and fixes it (Supervisor._pass)."""
        keys = [self._moved(k) for k in keys]
        if not keys:
            raise ValueError("name the tickets")

        def failed(i, k):  # failed, or queued again by the keep-trying rule (it has a try's commit) and not started
            return (i["key"] == k and i["kind"] == "ticket" and is_unity(i.get("repo"))
                    and (i["state"] == "failed" or i["state"] == "queued" and i.get("commit") and i.get("fails")))

        def change(q, rows):  # every ticket is found before any is changed: a refusal changes nothing
            plan, bad = [], []
            for k in keys:
                item = next((i for i in q["items"] if failed(i, k)), None)
                old = None
                if item is None and not any(i["key"] == k for i in q["items"] if i["state"] not in self.NIGHT_ENDED):
                    old = next((i for n in reversed(self._data["nights"]) for i in reversed(n.get("items") or [])
                                if failed(i, k)), None)
                if item is None and old is None:
                    bad.append(k)
                plan.append((k, item, old))
            if bad:
                raise ValueError("not a failed ticket of a Unity project: " + ", ".join(bad))
            for k, item, old in plan:
                if item is None:
                    q["items"] = [i for i in q["items"] if i["key"] != k]
                    item = {**json.loads(json.dumps(old)), "night": None}
                    q["items"].append(item)
                item.update(state="queued", integrate_only=True, ended=None, started=None, pid=None, pid_start=None,
                            note="queued for a Unity pass: the integrator plays what its review found short, on the "
                            "main folder")
        out = self._queue_write(None, change)
        return {"ok": out["ok"], "queued": keys}

    def recheck_now(self, key):
        """The Recheck button: the ticket's checks run again at the next tick, and the count starts over. Also Land
        again: a failed run whose commit waits in its kept worktree goes back to its checks on the kept commit, so
        it is rebased, checked, landed and reviewed without its worker running again."""
        key = self._moved(key)
        with self._lock:
            item = next((dict(i) for i in self._data["queue"]["items"]
                         if i["key"] == key and (i["state"] == "recheck" or landing_failed(i))), None)
        if item is None:
            raise ValueError("its checks are not waiting to be run again")
        if item["state"] != "recheck":  # a failed run let go of its ticket: the hub holds it again, so the review can close it
            name, _, num = key.rpartition("#")
            rc, out, err = sbmap_call("claim", name, "{:03d}".format(int(num)), "--by", "hub " + str(item.get("runner") or "land-again"))
            if rc != 0:
                raise ValueError("could not take the ticket back: " + (err or out).strip())
            self.tickets(fresh=True)
        with self._lock:
            item = next((i for i in self._data["queue"]["items"]
                         if i["key"] == key and (i["state"] == "recheck" or landing_failed(i))), None)
            if item is None:
                raise ValueError("its checks are not waiting to be run again")
            if item["state"] != "recheck":
                item.update(state="recheck", checked=None, ended=None, review=None, verdict=None,
                            note="lands again: its checks run on the commit it kept")
            item.update(recheck_at=0, rechecks=0)
            self._data["queue"]["version"] += 1
            self._save()
        return {"ok": True}

    def queue_pause(self, paused):
        def change(q, rows):
            q["paused"] = bool(paused)
            if not q["paused"]:
                q.pop("note", None)  # the reason it was paused no longer holds
        return self._queue_write(None, change)

    def queue_parallel(self, repo, n, version):
        """Set how many tickets run at once in `repo` (git config sb.parallel, 1 to 8); the queue looks again."""
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= PARALLEL_MAX:
            raise ValueError("n must be a whole number from 1 to {}".format(PARALLEL_MAX))
        if not usable_project(repo):
            raise ValueError("repo is not a folder here: {}".format(repo))

        def change(q, rows):
            rc, _, err = _git_run(repo, "config", "sb.parallel", str(n), timeout=10)
            if rc != 0:
                raise ValueError("could not write git config sb.parallel: {}".format(err))
            q.setdefault("repos", {}).setdefault(repo, {"running": 0, "side_by_side": 0})["at_once"] = n
        return self._queue_write(version, change)

    def queue_agent(self, name):
        """The one agent that runs tonight's items unless an item names its own (a pool of one)."""
        def change(q, rows):
            if name not in self._data["installed"]:
                raise ValueError("unknown agent: {}".format(name))
            q["agent"], q["agents"] = name, [name]
        return self._queue_write(None, change)

    def queue_agents(self, names, version):
        """The night's pool, in order: each item goes to the one it fits on with the most room left; ties go
        to the first. `agent` becomes the first, for what still reads one agent."""
        def change(q, rows):
            if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
                raise ValueError("name one or more agents")
            unknown = [n for n in names if n not in self._data["installed"]]
            if unknown:
                raise ValueError("unknown agent: {}".format(", ".join(unknown)))
            q["agents"] = list(dict.fromkeys(names))
            q["agent"] = q["agents"][0]
        return self._queue_write(version, change)

    def queue_item_agent(self, key, name=_KEEP, model=_KEEP):
        """The account (`name`, None for the pool) and/or the model ("sonnet", "opus"; None for the ticket's own
        tier) a queued item runs on; an argument left out stays as it is."""
        def change(q, rows):
            item = next((i for i in q["items"] if i["key"] == key and i["state"] == "queued"), None)
            if item is None:
                raise ValueError("not a queued item: {}".format(key))
            if name is not _KEEP and name is not None and name not in self._data["installed"]:
                raise ValueError("unknown agent: {}".format(name))
            if model is not _KEEP and model not in (None, "sonnet", "opus"):
                raise ValueError("unknown model: {}".format(model))
            if name is not _KEEP:
                item["agent"] = name
            if model is not _KEEP and not item.get("tries"):
                item["model"] = model
        return self._queue_write(None, change)

    def queue_options(self, stop_at, final_review, version):
        """Tonight's stop time (epoch seconds, or None for none) and whether a final review job follows the
        last ticket."""
        if stop_at is not None:
            stop_at = float(stop_at)

        def change(q, rows):
            q["stop_at"] = stop_at
            q["final_review"] = bool(final_review)
        return self._queue_write(version, change)

    def queue_job(self, project, prompt, agent=None, model=None, name=None, at=None):
        """Queue a one-off job: `prompt` run headless in the repo of the wayfinder project folder `project`,
        or in `project` itself when it is an absolute path to a git checkout (its run folder is then a shared
        one, wayfinder/runs/). Refused as a duplicate (ValueError naming the earlier item) when the same
        project and prompt were queued within the last day. `at` ("HH:MM", local) holds it until the next
        time the clock shows that."""
        not_before = next_clock(at, self.now()) if at else None
        if not str(prompt or "").strip():
            raise ValueError("a job needs a prompt")
        project = str(project or "").strip()
        if os.path.isabs(project):
            repo = project = os.path.normpath(project)
            if not os.path.isdir(repo) or not os.path.exists(os.path.join(repo, ".git")):
                raise ValueError("not a git checkout (no .git in it): {}".format(project))
        else:
            repo = project_repo(project)
        if repo is None:
            raise ValueError("unknown project (no map in wayfinder/{} names a repo folder): {}".format(project, project))
        if agent is not None and agent not in self._data["installed"]:
            raise ValueError("unknown agent: {}".format(agent))
        return self._queue_job(project, repo, prompt, agent, model, name, not_before=not_before)

    def _queue_job(self, project, repo, prompt, agent, model, name, not_before=None, close_off=False):
        """The job item's key is `job:<first 12 of its hash>:<n>`, n counting the jobs with that hash so far."""
        digest = hashlib.sha256((project + "\n" + prompt.strip()).encode("utf-8")).hexdigest()
        made = []

        def change(q, rows):
            now = self.now()
            same = [i for i in q["items"] if i["kind"] == "job" and i.get("hash") == digest]
            for i in same:
                if now - (i.get("created") or 0) < JOB_DUPLICATE_WINDOW:
                    raise ValueError("duplicate of {} ({}), queued less than a day ago".format(
                        i["key"], i.get("name") or "job"))
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-") or "job-" + digest[:6]
            key = "job:{}:{}".format(digest[:12], len(same) + 1)
            q["items"].append({"key": key, "kind": "job", "agent": agent, "model": model, "project": project,
                               "repo": repo, "prompt": prompt, "hash": digest, "name": slug, "title": slug,
                               "state": "queued", "note": "", "commit": None, "tries": 0, "created": now,
                               "started": None, "ended": None,
                               **({"not_before": not_before} if not_before else {}),
                               **({"close_off": True} if close_off else {})})
            made.append(key)
        out = self._queue_write(None, change)
        return {**out, "key": made[0]}

    def agents_scan(self, home=None, which=shutil.which):
        """Find the installed agents and merge them into `installed`; hand-edited entries are kept.

        A Claude config is `~/.claude` or `~/.claude-<name>` (named `main`, or <name>) that holds a
        sign-in: a `.credentials.json`, or a `.claude.json` with an `oauthAccount`. On this machine
        `~/.claude`, `~/.claude-personal` and `~/.claude-assembio` have no `.credentials.json` (the
        login is in the keychain) and each has `.claude.json` with `oauthAccount`, so that is the
        marker; a folder without either is not an agent. `agy` counts when `which("agy")` finds it.
        The queue's default agent is set to `main` (else the first by name) if none is chosen yet,
        and is never `agy`."""
        home = Path(home) if home else Path.home()
        found = {}
        for d in sorted(home.glob(".claude*")):
            if d.name != ".claude" and not d.name.startswith(".claude-") or not d.is_dir():
                continue
            if not ((d / ".credentials.json").is_file() or _signed_in(d / ".claude.json")):
                continue
            found["main" if d.name == ".claude" else d.name[len(".claude-"):]] = {
                "kind": "claude", "dir": str(d), "model": None, "limited_until": None}
        if which("agy"):
            found["agy"] = {"kind": "agy", "dir": None, "model": None, "limited_until": None}
        with self._lock:
            inst = self._data["installed"]
            for name, entry in found.items():
                inst.setdefault(name, entry)
            q = self._data["queue"]
            claudes = sorted(n for n, e in inst.items() if e.get("kind") == "claude")
            if q["agent"] is None and claudes:
                q["agent"] = "main" if "main" in claudes else claudes[0]
                q["version"] += 1
            self._save()
            return json.loads(json.dumps(inst))

    def trusted(self):
        return read_trusted(self.home)


SBMAP = Path(__file__).resolve().parent / "sbmap.py"
JOB_DUPLICATE_WINDOW = 86400  # the same project and prompt is refused again for this long
SEEN_KEPT = 2000  # runs marked seen that the hub remembers; older marks drop off
CLEARED_KEPT = 300  # finished items cleared off the queue list that the page's log still shows
QUIET_FOR = 2 * 3600  # a row idle or on "your turn" this long is quiet (agents_clear_quiet)
LOG_SERVED = 1 << 20  # the end of a worker's log the page can open
# a worker's pictures and clips, in <run folder>/<num>-media/: the kinds the board shows, how many, how big
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm"}
MEDIA_MAX, MEDIA_BYTES = 6, 8 << 20
CHECK_TAIL = 40  # output lines kept per check
CLOSE_OFF_AT = (9, 0)  # the morning close-off job's local time
CLOSE_OFF = Path(__file__).resolve().parents[1] / "templates" / "close-off.md"
# a build held for a break no ticket owns gets one fix run: a job in the repo's main folder, briefed from this
FIX_BUILD = Path(__file__).resolve().parents[1] / "templates" / "fix-build.md"
FIX_MODEL = "opus"
FIX_ASK_WAIT = 12 * 3600


def next_clock(hhmm, now):
    """The next epoch time (after `now`) the local clock shows "HH:MM"; ValueError for anything else."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(hhmm or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("a time is HH:MM, e.g. 09:00")
    at = datetime.fromtimestamp(now).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    if at.timestamp() <= now:
        at += timedelta(days=1)
    return at.timestamp()


def _recording(checks):
    """A `run` for sbqueue.verdict that also keeps each check (the shell commands) as {cmd, code, secs, tail}:
    code None when it timed out, tail its last CHECK_TAIL output lines."""
    def run(cmd, **kw):
        if not kw.get("shell"):
            return subprocess.run(cmd, **kw)
        began = time.time()
        try:
            r = subprocess.run(cmd, **kw)
        except subprocess.TimeoutExpired:
            checks.append({"cmd": cmd, "code": None, "secs": round(time.time() - began, 1),
                           "tail": "timed out after 20 minutes"})
            raise
        out = ((r.stdout or "") + (r.stderr or "")).splitlines()[-CHECK_TAIL:]
        checks.append({"cmd": cmd, "code": r.returncode, "secs": round(time.time() - began, 1),
                       "tail": "\n".join(line[:300] for line in out)})
        return r
    return run


def hub_checks_section(passed, reason, sha, checks, report_text, stamp):
    """The `## Hub checks` section the hub appends to a worker's report: the verdict, each check, and the
    worker's own `## Self-checks` section (or "none reported")."""
    lines = ["", "## Hub checks", "", "Checked by the sb hub at {}: {}{}.".format(
        stamp, "passed" if passed else firstline(reason) if passed is None else "failed: " + firstline(reason), ", commit " + sha[:9] if sha else "")]
    if not checks:
        lines.append("No check ran ({}).".format("the ticket has no check commands: the Opus review of its Done when "
                                                 "is its only check" if passed and reason.startswith("commit and checks")
                                                 else "the verdict stopped before the checks"))
    for c in checks:
        lines += ["", "- `{}`: {}, {} s".format(c["cmd"], "timed out" if c["code"] is None else "exit {}".format(c["code"]),
                                              c["secs"]), "", "  ```", *("  " + l for l in c["tail"].splitlines()), "  ```"]
    m = re.search(r"^## Self-checks[^\n]*\n(.*?)(?=^## |\Z)", report_text or "", re.M | re.S)
    lines += ["", "### The worker's self-checks", "", (m.group(1).strip() if m and m.group(1).strip() else "none reported"), ""]
    return "\n".join(lines)


TICKET_ACTIONS = ("done", "drop", "release", "comment", "rule", "tier", "checks", "recheck", "done_when", "paths", "after")
# the steering fields: action -> (what the comment calls it, the ticket row's key for its old value)
STEER = {"done_when": ("Done when", "done_when"), "paths": ("files", "paths"), "after": ("what it comes after", "blocked_by")}


def sbmap_call(*args):
    """(exit code, stdout, stderr) of one sbmap command, run as the agents run it."""
    try:
        r = subprocess.run([sys.executable, str(SBMAP), *args], capture_output=True, text=True, errors="replace",
                           timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def obsidian_uri(path):
    """The obsidian:// link `sbmap uri` prints for a vault file, or '' when it has none."""
    rc, out, _ = sbmap_call("uri", str(path))
    i = out.rfind("](obsidian://")
    return out[i + 2:-1] if rc == 0 and i >= 0 and out.endswith(")") else ""


def _first_words(path, heading=False):
    """A note's first line of prose (after its properties and headings): what a handoff says first."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        text = text[end + 4:] if end >= 0 else text
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if heading:
        return next((l.lstrip("# ") for l in lines if l.startswith("# ")), Path(path).stem)
    return next((l for l in lines if not l.startswith(("#", ">", "```"))), lines[0].lstrip("# ") if lines else "")[:200]


def firstline(text):
    return next((l.strip() for l in str(text or "").splitlines() if l.strip()), "")
REFRESH_EVERY = 15
TICKETS_CACHED_FOR = 15
TICKETS_FAILED_FOR = 5  # after a failed sbmap, no new try for this long

# ---- the runner: the hub starts a headless worker per queued ticket and checks it in code ----

WORKER_LIMIT = 90 * 60  # a worker still running after this long has its process group killed
TICK_EVERY = 5
RECHECK_EVERY = 10 * 60  # a ticket whose check could not run (exit 75): its checks run again this often
REVIEW_EVERY_MIN = 25  # a landed ticket waits at most this long for its review while its map still runs


def review_every():
    """Seconds a landed ticket waits before the timer reviews it on a busy map (env SB_REVIEW_EVERY_MIN overrides)."""
    try:
        return float(os.environ.get("SB_REVIEW_EVERY_MIN") or REVIEW_EVERY_MIN) * 60
    except ValueError:
        return REVIEW_EVERY_MIN * 60


def review_next_at(items):
    """When the timer next looks at a busy map: the oldest landed ticket's landing plus review_every(), over maps
    with no review running (their items in state `review`); None when nothing waits."""
    held = {sbqueue.map_of(i["key"]) for i in items if i["kind"] == "ticket" and i["state"] == "review"}
    at = [i.get("landed_at") or 0 for i in items
          if i["kind"] == "ticket" and i["state"] == "landed" and sbqueue.map_of(i["key"]) not in held]
    return min(at) + review_every() if at else None


RECHECKS_MAX = 6  # ...this many times, then it waits for the Recheck button
REVIEW_BASE, REVIEW_EACH = 10 * 60, 5 * 60  # a map's second pass may run 10 minutes plus 5 per ticket, then it is killed


def review_limit(n):
    """Seconds a second pass over `n` tickets may run before it is killed (the review could not run)."""
    return REVIEW_BASE + REVIEW_EACH * max(1, n)


REVIEW_MODEL = "opus"  # the second pass runs on Opus, whichever model did the work
# A ticket's tries, each with its own counter on its queue item, none of which spends another's:
#   tries     failed tries so far (`fails` holds each one's model, reason and commit): a failed try is queued again
#             at the front from its kept work, up to TRIES_MAX tries, from OPUS_FROM on Opus (`retry`); then, or after
#             SAME_MAX alike failures with no new commit, it fails for the owner. A ticket its map waits on goes again
#             before anything else of its repo starts.
#   stops     runs cut off by a usage limit or a logout, queued again at the front (STOPS_MAX)
#   rechecks  a check that exited 75, or a review that could not run, run again alone (RECHECKS_MAX)
#   redo      the one more try the Opus review asks for: its first verdict was partly or not met. The field holds the
#             first try's commit and findings; once it is set there is no other, and a second verdict that is not
#             finished leaves the ticket open, waiting for the owner. A verdict never reverts a commit.
LOG_TAIL = 65536  # the end of a worker's log that is searched for a limit message
# what an agent prints when its plan's usage runs out (case-insensitive); any other failure is just `failed`
LIMIT_PATTERNS = ("usage limit reached", "hit your session limit", "hit your weekly limit", "spend limit")
RESET = re.compile(r"\bresets\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap]m)?", re.I)


def limited_until(text, now):
    """When an agent whose output is `text` may run again: None when it hit no limit; the next time the
    message's reset clock time (`resets 4:40am`, `resets 23:10`) comes round; else an hour from now."""
    if not any(p in text.lower() for p in LIMIT_PATTERNS):
        return None
    for m in RESET.finditer(text):
        hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if not (m.group(2) or half) or half and not 1 <= hour <= 12:
            continue
        hour = hour % 12 + (12 if half == "pm" else 0) if half else hour
        if hour > 23 or minute > 59:
            continue
        at = datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at.timestamp() <= now:
            at += timedelta(days=1)
        return at.timestamp()
    return now + 3600


def ran_past(limit):
    n, unit = (round(limit / 60), "minute") if limit >= 60 else (round(limit), "second")
    return "ran past {} {}{}".format(n, unit, "" if n == 1 else "s")


# ---- pacing: each Claude account's usage, read from its workers' stream-json and a one-line probe ----

USAGE_STALE = 600  # a reading older than this is refreshed by a probe; at most one probe per agent this often
GATE_5H = 0.90  # nothing starts that would take an account's 5-hour window past this
GATE_7D = 0.80  # nothing starts on an account whose week is used past this
BRAKE_5H = 0.95  # a running worker whose account passes this is told, once, to wrap up
MAX_PER_AGENT = 4  # workers at once on one account (one while it has no learned cost)
TICKET_SECONDS = 4500  # about how long a ticket runs: a window resetting sooner refills before it needs it all
DEFAULT_COST = {"sonnet": 0.15, "opus": 0.30}  # share of a 5-hour window per ticket until one is learned
WINDOW = 5 * 3600
SAME_WINDOW = 600  # two readings whose reset times are this close belong to one window
PROBE_TIMEOUT = 90
BRAKE_TEXT = "Usage is at 95%: commit what passes now with the ticket's trailer, write your report, and stop."
BRAKE_JOB_TEXT = "Usage is at 95%: commit what passes now, write your result, and stop."
NEED_CAP = 0.60  # no item is judged to need more of a window than this: a big learned cost never blocks for good
IDLE_FLOOR = 0.10  # an account running nothing and under this much 5-hour use always takes an eligible item
READING_OLD = 1800  # a reading older than this counts as none (one worker; the probe is due long before)
STOPS_MAX = 3  # an item cut off by a limit or a logout this many times ends failed
TRIES_MAX = 5  # a ticket whose try failed is queued again, from its kept work, up to this many tries in all
OPUS_FROM = 3  # ...the first tries on its own tier, this one and later on Opus (an agy agent keeps its model)
SAME_MAX = 3  # the same failure this many tries in a row with no new commit: it waits for the owner sooner
AUTH_PATTERNS = ("authentication_failed", "failed to authenticate", "oauth session expired")
RESUME = ("\n## An earlier try stopped\n\nAn earlier try on {agent} stopped {why}. Its changes may already be in "
          "the tree, committed or not: read `git log {base}..HEAD` and {diff} first, continue from there, do not "
          "redo finished work. Its log: {log}.\n")
# what a resumed session is told (it keeps its first brief): what happened, then where to go on from
CONTINUE = ("{what}\nYour work so far is in this tree, committed or not: read `git log {base}..HEAD` and `git status`, "
            "go on from there and do not redo finished work. Finish as your brief said: verify, commit with this "
            "trailer, and write your report to {report}.\n\n  Ticket: {ticket}\n")
REDO = ("\n## This is the ticket's second try\n\n{work} The Opus review judged that try {verdict} against the Done "
        "when (its review: {review}). Fix what it found not met:\n{findings}\nThe next review judges both tries' "
        "commits together; there is no third try.\n")


def redo_brief(redo):
    """What a review-driven second try's worker is told beyond its usual brief: the first try's commit, named as work
    to build on, and the review's not-met lines."""
    sha = redo.get("commit")
    work = ("The first try made commit {}, which is already in this branch: build on it, do not redo or revert it."
            .format(sha) if sha else "The first try made no commit (its report said no change was needed).")
    findings = "\n".join(redo.get("findings") or []) or "(the review named no line not met: read it)"
    return REDO.format(work=work, verdict=redo.get("verdict") or "not met", review=redo.get("review") or "none kept",
                       findings=findings)


def retry_brief(item, tree, branch, base, report=None):
    """What a ticket's later try (a new session) is told: which try it is, every earlier try's failure and commit,
    the last one's whole reason and report, and where the work so far is, to go on from."""
    fails = item.get("fails") or []
    where = ("on branch {} in this worktree".format(branch) if tree else "in this checkout")
    lines = "\n".join("- try {} ({}): {}{}".format(n, f.get("model"), f.get("why"),
                                                   ", commit " + f["commit"][:9] if f.get("commit") else "")
                      for n, f in enumerate(fails, 1))
    return ("\n## This is try {n} of {most}\n\nEarlier tries failed:\n{lines}\nThe last one's reason in full:\n{why}\n"
            "{report}Their work is kept {where}: read `git log {base}..HEAD` and `git status` first and go on from it; "
            "do not start over and do not revert it. Fix what failed.\n").format(
                n=len(fails) + 1, most=TRIES_MAX, lines=lines, why=item["retry"], where=where, base=base[:12],
                report="The last try's report: {}\n".format(report) if report else "")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def readings(text):
    """The usage readings in a stream-json log, oldest first: (usage, rejected_until) per `rate_limit_event`
    line, usage = {five_hour, five_hour_resets, seven_day, seven_day_resets}; rejected_until is the latest
    reset of a window the event marks `rejected`, else None."""
    out = []
    for line in text.splitlines():
        if '"rate_limit_event"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("type") != "rate_limit_event":
            continue
        info = d.get("rate_limit_info") if isinstance(d.get("rate_limit_info"), dict) else {}
        wins = info.get("unifiedWindows") if isinstance(info.get("unifiedWindows"), dict) else {
            info.get("rateLimitType"): info}
        five, week = (w if isinstance(w, dict) else {} for w in (wins.get("five_hour"), wins.get("seven_day")))
        if _num(five.get("utilization")) is None:
            continue
        u = {"five_hour": _num(five["utilization"]), "five_hour_resets": _num(five.get("resetsAt")),
             "seven_day": _num(week.get("utilization")), "seven_day_resets": _num(week.get("resetsAt"))}
        rejected = [_num(w.get("resetsAt")) for w in (five, week, info)
                    if w.get("status") == "rejected" and _num(w.get("resetsAt")) is not None]
        out.append((u, max(rejected) if rejected else None))
    return out


def _said(text):
    """What the agent itself printed: each JSON line's `error`, the `result` of one marked `is_error`, and every
    line that is not JSON (stderr, agy's output). Tool output inside the stream is left out: a worker that read a file
    naming a usage limit has not hit one."""
    out = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        if not isinstance(d, dict):
            out.append(line)
            continue
        if isinstance(d.get("error"), str):
            out.append(d["error"])
        if d.get("is_error") is True and isinstance(d.get("result"), str):  # a summary that went well is not a stop
            out.append(d["result"])
    return "\n".join(out)


def logged_out(said):
    """The agent's own output (see _said) says its login expired."""
    return any(p in said.lower() for p in AUTH_PATTERNS)


def _tier(model):
    return "opus" if "opus" in str(model or "") else "sonnet"


def _same_window(a, b):
    return abs((a.get("five_hour_resets") or 0) - (b.get("five_hour_resets") or 0)) <= SAME_WINDOW


def _cost(inst, tier):
    """(share of a 5-hour window one item of `tier` costs on this agent, whether it is learned): its own
    average, else its other tier's (opus twice sonnet), never under a third of DEFAULT_COST; else DEFAULT_COST."""
    costs, floor = inst.get("costs") or {}, round(DEFAULT_COST[tier] / 3, 4)  # one cheap run never makes a ticket free
    if tier in costs:
        return max(floor, costs[tier]["avg"]), True
    other = "sonnet" if tier == "opus" else "opus"
    if other in costs:
        return max(floor, costs[other]["avg"] * (2 if tier == "opus" else 0.5)), True
    return DEFAULT_COST[tier], False


def _hm(ts, fmt="%H:%M"):
    return datetime.fromtimestamp(ts).strftime(fmt) if ts else "unknown"


def _pct(x):
    return "{}%".format(round(100 * x))


def pool(q):
    """The night's agents in order: `agents`, or a state from before pools, its one `agent`."""
    return list(q.get("agents") or ([q["agent"]] if q.get("agent") else []))


def probe_usage(agent, cwd):
    """One tiny Haiku call under the agent's config dir; its output carries a `rate_limit_event` (or the login
    failure). '' when it could not run."""
    env = {**os.environ, "SB_HUB_PORT": "1"}  # ponytail: its own hooks report to a closed port: never a board row
    for k in ("SB_HUB_AGENT", "SB_HUB_PARENT"):
        env.pop(k, None)
    if agent.get("dir"):
        env["CLAUDE_CONFIG_DIR"] = agent["dir"]
    try:
        Path(cwd).mkdir(parents=True, exist_ok=True)
        r = subprocess.run([_exe("claude", env), "-p", "reply ok", "--model", "haiku", "--output-format",
                            "stream-json", "--verbose"], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, errors="replace", timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout + "\n" + r.stderr


def _exe(name, env):
    found = shutil.which(name, path=env.get("PATH"))
    local = Path.home() / ".local" / "bin" / name  # where the Claude installer puts it
    return found or (str(local) if local.exists() else name)


GUARD = Path(__file__).resolve().parent.parent / "hooks" / "guard_git.py"
# every Claude worker gets this PreToolUse hook: it refuses what a worker must never do (see hooks/guard_git.py)
GUARD_SETTINGS = {"hooks": {"PreToolUse": [{"matcher": "Bash|Write|Edit|MultiEdit|NotebookEdit", "hooks": [
    {"type": "command", "command": "{} {}".format(shlex.quote(sys.executable), shlex.quote(str(GUARD)))}]}]}}
GIT_RULE = ("\n\nGit rule: never run git stash, stash pop/apply, checkout or restore of tracked files, reset --hard, "
            "switch or rebase in a shared checkout; a hook refuses them, as it refuses sbmap resolve/close/new/set/claim and the "
            "like, an empty or amended commit, push, tag, reset, rm or mv inside .git, and a Write or Edit outside the repo, "
            "the run folder and temp. To compare with a clean tree, make a "
            "throwaway worktree (git worktree add --detach /tmp/clean-tree HEAD), run there, then remove it.\n")


PLUGIN = Path(__file__).resolve().parents[3] / "mods" / "hub-report"  # the hub's tools and message hooks
ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "CLAUDE_CONFIG_DIR")


def worker_env(repo, env):
    """A worker's environment: the named variables of the hub's own, the repo's `.sb/env` names (one per line), then
    `env` (the hub's ids). Nothing else of the hub's environment reaches a worker."""
    try:
        extra = [l.strip() for l in (Path(repo) / ".sb" / "env").read_text(encoding="utf-8").splitlines()]
    except OSError:
        extra = []
    keep = set(ENV_KEEP) | {l for l in extra if l and not l.startswith("#")}
    return {**{k: v for k, v in os.environ.items() if k in keep or k.startswith(("LC_", "SB_HUB_"))}, **env}


def launch(agent, brief, repo, model, env, log, resume=None):
    """Start one headless worker and return its Popen: the only place that knows the agents' commands.
    Own process group, cwd the ticket's repo, stdout and stderr to `log`; `env` adds the hub's ids. A Claude worker
    runs as a new session (`--session-id`) or, with `resume`, goes on with that one; the Popen's `session` is its id
    (None for agy)."""
    full = worker_env(repo, env)
    brief += GIT_RULE
    session = None
    if agent.get("kind") == "agy":
        cmd = [_exe("agy", full), "-p", brief] + (["--model", model] if model else []) + ["--output-format", "json"]
    else:
        if agent.get("dir"):
            full["CLAUDE_CONFIG_DIR"] = agent["dir"]
        session = resume or str(uuid.uuid4())
        cmd = [_exe("claude", full), "-p", brief, "--resume" if resume else "--session-id", session,
               "--permission-mode", "auto", "--model", model, "--settings", json.dumps(GUARD_SETTINGS),
               "--output-format", "stream-json", "--verbose",  # stream-json carries the account's usage
               "--setting-sources", "project,local", "--strict-mcp-config", "--plugin-dir", str(PLUGIN),
               "--mcp-config", str(PLUGIN / ".mcp.json")]  # --strict-mcp-config skips the plugin's own server: pass it
        if (Path(repo) / ".mcp.json").is_file():  # the repo's own MCP servers (Unity for a game) stay
            cmd += ["--mcp-config", str(Path(repo) / ".mcp.json")]
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        p = subprocess.Popen(cmd, cwd=repo, env=full, stdin=subprocess.DEVNULL, stdout=out,
                             stderr=subprocess.STDOUT, start_new_session=True)
    p.session = session
    return p


SESSION_DAY = 86400  # a session older than this is not resumed: the try starts afresh, told the old log


def config_dir(agent):
    """The Claude config dir an agent's workers run under (where their sessions are kept)."""
    return agent.get("dir") or os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")


def session_file(config, cwd, sid):
    """Where Claude Code keeps a session: <config>/projects/<cwd, each character not a letter or digit a dash>/<id>.jsonl.
    ponytail: Claude shortens a very long cwd's folder name with a hash; such a session is not found, so it starts
    afresh."""
    return Path(config) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd)) / (sid + ".jsonl")


def resumable(item, agent, cwd, now=time.time):
    """The session id a stopped or reviewed ticket goes on with on `agent` in `cwd`, or None for a fresh start: no
    session kept, an agy agent, its file missing or older than SESSION_DAY, or it could not be copied into this
    agent's account (a session lives in one account's folder)."""
    sid, was = item.get("session"), item.get("session_dir")
    if not sid or not was or agent.get("kind") == "agy":
        return None
    src = session_file(was, cwd, sid)
    try:
        if now() - src.stat().st_mtime > SESSION_DAY:
            return None
        dst = session_file(config_dir(agent), cwd, sid)
        if dst != src:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except OSError:
        return None
    return sid


def resume_failed(run):
    """A resumed worker that ended with an error before its session took a turn: the session could not go on."""
    rc = getattr(run.get("p"), "returncode", None)
    return bool(run.get("resumed")) and rc not in (None, 0) and \
        '"type":"assistant"' not in _tail(run["log"], run.get("start") or 0).replace(" ", "")


def _kill_group(p, grace=3.0):
    """Kill a worker's whole process group: TERM, `grace` seconds, then KILL for whatever is left."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5)):
        try:
            os.killpg(p.pid, sig)
        except OSError:
            pass
        try:
            p.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            pass


def _proc_start(pid):
    """The process's start time as ps prints it: with the pid, it tells one process from a later reuse."""
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _pid_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # it exists, owned by someone else
    return True


class _Adopted:
    """A worker an earlier hub started that still runs: not this hub's child, so only its pid (and, when ps
    confirmed it, its start time: `sure`) is known. Quacks like the Popen parts the supervisor uses."""

    def __init__(self, pid, started):
        self.pid, self.started, self.sure, self.returncode = pid, started, bool(started), None

    def poll(self):
        try:
            out = subprocess.run(["ps", "-o", "stat=", "-o", "lstart=", "-p", str(self.pid)], capture_output=True,
                                 text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None  # ps cannot tell: still waited for (the 90-minute limit still ends it)
        stat, _, began = out.partition(" ")
        alive = bool(out) and not stat.startswith("Z") and (not self.sure or began.strip() == self.started)
        return None if alive else 0

    def wait(self, timeout=None):
        end = time.time() + (timeout or 0)
        while self.poll() is None:
            if time.time() >= end:
                raise subprocess.TimeoutExpired("worker {}".format(self.pid), timeout)
            time.sleep(0.05)
        return 0


def _result_ok(text):
    """The stream's last `result` line says it went well (`is_error` false)."""
    for line in reversed(text.splitlines()):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("type") == "result":
            return d.get("is_error") is False
    return False


def log_spend(path, start=0):
    """{tokens_in, tokens_out, cache_read, cost_usd} summed over the `result` lines of a worker log from byte
    `start` (one try's output), read from each line's per-model usage (modelUsage, or
    model_usage_since_last_result); None when the log has no result line or cannot be read."""
    try:
        with open(path, "rb") as f:
            f.seek(start)
            text = f.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return None
    out, seen = {"tokens_in": 0, "tokens_out": 0, "cache_read": 0, "cost_usd": 0.0}, False
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("type") != "result":
            continue
        use = d.get("model_usage_since_last_result") or d.get("modelUsage")
        if not isinstance(use, dict):
            continue
        seen = True
        for u in use.values():
            if isinstance(u, dict):
                out["tokens_in"] += int(u.get("inputTokens") or 0)
                out["tokens_out"] += int(u.get("outputTokens") or 0)
                out["cache_read"] += int(u.get("cacheReadInputTokens") or 0)
                out["cost_usd"] += float(u.get("costUSD") or 0)
    out["cost_usd"] = round(out["cost_usd"], 4)
    return out if seen else None


# The hub's own reads (`git status`, `diff`) never take the checkout's index.lock, so they cannot make a landing's
# merge or revert fail; a write that meets someone else's index.lock waits for it (INDEX_LOCK_WAIT seconds).
# On 2026-11-16 a revert met one, the broken landing stayed, and the next ticket was blamed for its error.
GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
INDEX_LOCK_WAIT = 5
UNDO_FAILED = "could NOT be backed out"
# a check that fails only in files the ticket never touched: the build is broken by something else, so it is not
# the ticket's try; the ticket waits (`held`), its repo starts nothing new, and the failing check runs again on the
# checkout's newest commit when that moves or every HELD_EVERY seconds until it passes
HELD = "the build is broken outside its files"
HELD_EVERY = 5 * 60


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=60, env=GIT_ENV)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


# ---- tickets side by side: a repo with `git config sb.parallel N` runs up to N tickets whose paths do not overlap,
# each in its own worktree on its own branch; a passed one is rebased onto the checkout's branch, checked there and
# fast-forwarded into the checkout ----

QUEUE_TRIES = 4  # `queue add` / `queue rm` write this often while the queue keeps changing under them
PARALLEL_MAX = 8  # tickets at once in one repo, whatever its git config says
LAND_TRIES = 3  # rebase, check and fast-forward again this often when the checkout gained commits meanwhile
LAND_LOCK_WAIT = 600  # a landing with after-landing checks waits this long for the repo's Unity lock, then rechecks later
LAND_LOCK_POLL = 2
MOVED = "moved"


def _git_run(repo, *args, timeout=120, strip=True):
    """(returncode, stdout, stderr) of one git command in `repo`; (1, '', why) when git could not run. strip=False
    keeps stdout as git wrote it, for output whose leading spaces mean something (`status --porcelain`)."""
    end = time.time() + INDEX_LOCK_WAIT
    while True:
        try:
            r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args], capture_output=True,
                               text=True, timeout=timeout, env=GIT_ENV)
        except (OSError, subprocess.SubprocessError) as e:
            return 1, "", str(e)
        if r.returncode == 0 or "index.lock" not in r.stderr or time.time() >= end:
            return r.returncode, r.stdout.strip() if strip else r.stdout, r.stderr.strip()
        time.sleep(0.25)  # another git in this checkout holds its index for a moment: wait it out


def project_root(path):
    """The checkout a folder belongs to: its repo's main checkout (a worktree's too), the folder itself outside git."""
    rc, common, _ = _git_run(path, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=10)
    root = str(Path(common).parent) if rc == 0 and common and Path(common).name == ".git" else \
        _git(path, "rev-parse", "--show-toplevel")
    if not root:
        return path
    try:  # inside the checkout itself: the reported spelling, cut back to it (macOS /var is /private/var to git)
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return root  # a worktree elsewhere: its main checkout, as git names it
    up = Path(path)
    for _ in rel.parts:
        up = up.parent
    return str(up)


def parallel_of(repo):
    """How many tickets may run at once in `repo`, each in its own worktree: `git config sb.parallel`, else 1."""
    try:
        n = int(_git(repo, "config", "--get", "sb.parallel") or 1)
    except ValueError:
        return 1
    return max(1, min(n, PARALLEL_MAX))


def paths_overlap(a, b):
    """True when two tickets' path lists could touch the same file: either names none, or one path lies in another."""
    a = [str(x).strip().strip("/") for x in a or []]
    b = [str(y).strip().strip("/") for y in b or []]
    if not a or not b:
        return True
    return any(not x or not y or x == y or x.startswith(y + "/") or y.startswith(x + "/") for x in a for y in b)


def shared_path(a, b):
    """The first path of `a` that meets one of `b` (their overlap rule), or None; a ticket naming no path meets all."""
    a = [str(x).strip().strip("/") for x in a or []]
    b = [str(y).strip().strip("/") for y in b or []]
    for x in a:
        for y in b:
            if not x or not y or x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                return max(x, y, key=len) or "/"
    return "any path" if not a or not b else None


def side_by_side(paths):
    """The most tickets (each a list of paths) of which no two overlap: exact up to 24 of them, else a greedy count."""
    n = len(paths)
    clash = [sum(1 << j for j in range(n) if j != i and paths_overlap(paths[i], paths[j])) for i in range(n)]
    if n > 24:
        left, count = (1 << n) - 1, 0
        while left:
            i = min((i for i in range(n) if left >> i & 1), key=lambda i: bin(clash[i] & left).count("1"))
            left &= ~(clash[i] | 1 << i)
            count += 1
        return count

    def best(left):
        if not left:
            return 0
        i = (left & -left).bit_length() - 1
        return max(best(left & ~(1 << i)), 1 + best(left & ~(1 << i) & ~clash[i]))
    return best((1 << n) - 1)


def tree_of(home, repo, map_name, num):
    """(folder, branch) of a ticket's own worktree: under the hub's home, one folder per repo."""
    tag = hashlib.sha1(str(repo).encode()).hexdigest()[:6]
    name = "{}-{:03d}".format(re.sub(r"[^A-Za-z0-9._-]+", "-", str(map_name)).strip("-"), int(num))
    return str(Path(home) / "worktrees" / "{}-{}".format(Path(repo).name, tag) / name), "sb/" + name


def make_tree(repo, tree, branch, base):
    """A fresh worktree at `tree` on `branch`, reset to `base` (an old one there goes first): None, or why not."""
    if Path(tree).exists():
        _git_run(repo, "worktree", "remove", "--force", tree)
        shutil.rmtree(tree, ignore_errors=True)
    _git_run(repo, "worktree", "prune")
    Path(tree).parent.mkdir(parents=True, exist_ok=True)
    rc, out, err = _git_run(repo, "worktree", "add", "--quiet", "-B", branch, tree, base)
    return None if rc == 0 else (err or out or "git worktree add failed")


def landing_failed(item):
    """A failed ticket run whose commit waits in its kept worktree (it could not land, or a check of it failed or
    broke): Land again checks it once more and lands it, without its worker running again."""
    return (item.get("kind") == "ticket" and item.get("state") == "failed" and bool(item.get("tree"))
            and bool(item.get("commit")) and Path(item["tree"]).is_dir())


def drop_tree(repo, tree, branch):
    """Remove a ticket's worktree and its branch once its work is on the checkout's branch."""
    _git_run(repo, "worktree", "remove", "--force", tree)
    shutil.rmtree(tree, ignore_errors=True)
    _git_run(repo, "worktree", "prune")
    _git_run(repo, "branch", "-D", branch)


def rebase_tree(tree, onto):
    """Replay the worktree's commits onto `onto`, the checkout's newest commit: None, or why not (the rebase is
    undone, so the worktree stays as the worker left it)."""
    if _git_run(tree, "merge-base", "--is-ancestor", onto, "HEAD")[0] == 0:
        return None  # already on top of it
    rc, out, err = _git_run(tree, "rebase", "--autostash", onto, timeout=300)
    if rc == 0:
        return None
    clash = _git(tree, "diff", "--name-only", "--diff-filter=U").split()
    _git_run(tree, "rebase", "--abort")
    if clash:
        return "its commits conflict with {} on the checkout's branch in {}".format(
            onto[:9], ", ".join(clash[:5]) + (" and {} more".format(len(clash) - 5) if len(clash) > 5 else ""))
    return "git rebase onto {} failed: {}".format(onto[:9], firstline(err or out))


def unsaved(repo, paths=None):
    """The checkout's files with unsaved changes (modified, staged, deleted or untracked), of `paths` when given."""
    rc, out, _ = _git_run(repo, "status", "--porcelain", "-z", "--untracked-files=all", "--", *(paths or []),
                           strip=False)
    if rc != 0:
        return None
    names, parts = [], out.split("\0")
    while parts:
        entry = parts.pop(0)
        if len(entry) > 3:
            names.append(entry[3:])
            if entry[0] in "RC" and parts:  # a rename's old name follows it
                names.append(parts.pop(0))
    return names

def land(repo, sha):
    """Fast-forward the checkout's branch to `sha`: None when done, MOVED when the checkout gained commits since
    the rebase (rebase again), a list of files when the merge refused because the checkout holds unsaved changes to
    files the branch changes (the work waits for them, see Supervisor._unclean), else why not (the checkout is left
    as it was)."""
    if not _git(repo, "symbolic-ref", "-q", "HEAD"):
        return "the checkout is not on a branch"
    head = _git(repo, "rev-parse", "HEAD")
    if not head or _git_run(repo, "merge-base", "--is-ancestor", head, sha)[0] != 0:
        return MOVED
    rc, out, err = _git_run(repo, "merge", "--ff-only", "--quiet", sha, timeout=300)
    if rc == 0:
        return None
    changed = _git(repo, "diff", "--name-only", "-z", head, sha).split("\0")
    blocking = sorted(set(unsaved(repo) or ()) & {n for n in changed if n})
    return blocking or "git merge --ff-only into the checkout failed: " + (err or out or "no reason given")


_DROP_UNSAVED_SCENES = r"""
if (UnityEngine.Application.isPlaying) return "";
var dirty = new System.Collections.Generic.List<string>();
for (int i = 0; i < UnityEngine.SceneManagement.SceneManager.sceneCount; i++)
{
    var s = UnityEngine.SceneManagement.SceneManager.GetSceneAt(i);
    if (s.isDirty) dirty.Add(string.IsNullOrEmpty(s.path) ? "(untitled)" : s.path);
}
if (dirty.Count == 0) return "";
var setup = System.Array.FindAll(UnityEditor.SceneManagement.EditorSceneManager.GetSceneManagerSetup(),
    x => !string.IsNullOrEmpty(x.path));
UnityEditor.SceneManagement.EditorSceneManager.NewScene(
    UnityEditor.SceneManagement.NewSceneSetup.EmptyScene, UnityEditor.SceneManagement.NewSceneMode.Single);
if (setup.Length > 0)
{
    if (!System.Array.Exists(setup, x => x.isActive)) setup[0].isActive = true;
    if (!System.Array.Exists(setup, x => x.isLoaded)) setup[0].isLoaded = true;
    UnityEditor.SceneManagement.EditorSceneManager.RestoreSceneManagerSetup(setup);
}
return string.Join(", ", dirty);
"""


def drop_unsaved_scenes(repo):
    """Reload every open scene with unsaved changes from disk, so a landing or a revert that rewrites a scene file
    never stops the Editor on Unity's "scene has been modified externally" dialog, which blocks its main thread
    until someone clicks it (2026-11-17: a night of Unity passes timed out behind one). Unsaved scene edits are
    lost; a scripted scene change never asks. Does nothing in Play mode, outside a Unity project, or with the
    Editor down. The scenes it dropped, or ""."""
    if not is_unity(repo):
        return ""
    try:
        r = subprocess.run(["unity", "command", "eval", "--project-path", str(repo), "--format", "json",
                            "--code", _DROP_UNSAVED_SCENES], capture_output=True, text=True, timeout=60)
        out = r.stdout
        data = json.JSONDecoder().raw_decode(out[out.find("{"):])[0] if r.returncode == 0 and "{" in out else {}
        dropped = ((data.get("data") or {}).get("result") or {}).get("result") or ""
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return ""
    if dropped:
        print("sb hub: dropped unsaved scenes before taking Unity: {}".format(dropped), file=sys.stderr, flush=True)
    return str(dropped)


def _landing_by(landing):
    return "sb-hub landing " + landing["key"]


def unity_lock(repo):
    """The lock a repo's one Unity editor goes by: chat sessions take it with sb_lock, the hub while it lands."""
    return "unity:" + Path(str(repo)).name


# ---- the Unity stage: a Unity project's workers never drive the Editor; each landed ticket gets an integrator run
# in the main folder, holding the repo's Unity lock until it ends, one ticket at a time (templates/integrate.md)
INTEGRATE = Path(__file__).resolve().parents[1] / "templates" / "integrate.md"
INTEGRATE_MODEL = "opus"
INTEGRATE_MINUTES = 45
UNITY_WAIT = "waits for Unity"  # a recheck note: another ticket is in its Unity stage; not a try, not counted
UNITY_POLL = 2 * 60
UNITY_WORKER = ("\n\n## Unity is the last stage, not yours\n\nThis is a Unity project, and you work in your own folder. "
                "The one Unity Editor has the main folder open, so it never sees your code: any `unity` command is "
                "refused for you, and so is starting a batch Editor or a clone. This overrides the repo's rule to "
                "validate in the live Editor. After you commit, the hub lands your work on the main folder, and an "
                "integrator compiles it and plays it there, one ticket at a time. You cannot compile, so read the "
                "source of every type and member you call before you use it. In your report, add a section "
                "`## Play checks`: numbered steps that show your change working in Play, each with what should "
                "happen and the numbers to measure.\n")


def is_unity(repo):
    """A Unity project (it has ProjectSettings/ProjectVersion.txt): its tickets end in a Unity stage."""
    return bool(repo) and (Path(str(repo)) / "ProjectSettings" / "ProjectVersion.txt").is_file()


def dirty_files(repo):
    """The tracked files with unsaved changes in the checkout."""
    rc, out, _ = _git_run(repo, "status", "--porcelain", "--untracked-files=no", timeout=60, strip=False)
    return sorted({l[3:].split(" -> ")[-1].strip('"') for l in out.splitlines() if len(l) > 3}) if rc == 0 else []


def tidy_stage(repo, before, patch):
    """Tracked files the Unity stage left changed that were clean when it began (Unity writes some during Play): their
    changes saved to `patch`, then the files restored, so the next landing meets a clean checkout. The files."""
    left = [f for f in dirty_files(repo) if f not in set(before)]
    if left:
        rc, out, _ = _git_run(repo, "diff", "--", *left, timeout=60)
        try:
            Path(patch).write_text(out if rc == 0 else "", encoding="utf-8")
        except OSError:
            return []  # nothing restored when its changes could not be kept
        _git_run(repo, "checkout", "--", *left, timeout=60)
    return left


def stage_verdict(report):
    """The integrator's last `VERDICT:` line (works, broken, no unity), or None when it wrote none."""
    try:
        text = Path(report).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = re.findall(r"^\s*VERDICT:\s*(works|broken|no unity)\s*$", text, re.M | re.I)
    return found[-1].lower() if found else None


def stage_commits(repo, sha, key):
    """The commits after the landing `sha` whose Ticket line names the ticket `key` (map#num): its Unity stage's own
    fixes, newest first. Whatever anyone else committed meanwhile is not among them."""
    own = []
    for row in _git(repo, "log", "--format=%H\x1f%B\x1e", "{}..HEAD".format(sha)).split("\x1e"):
        h, _, body = row.partition("\x1f")
        m = re.fullmatch(r"(.+)/0*(\d+)", (re.findall(r"^Ticket: *(\S+) *$", body, re.M) or [""])[-1])
        if h.strip() and m and "{}#{}".format(m.group(1), int(m.group(2))) == key:
            own.append(h.strip())
    return own

def revert_landing(repo, before, sha, why, own=()):
    """Undo one landing, the commits before..sha, and `own`, the commits its Unity stage made after it (newest first),
    by one new commit on the checkout's branch that names each of them on an `Undoes:` line. Only those: whatever
    else came after the landing is kept. History is never rewritten. (None, the revert's sha), or (why not, None).
    Nothing to undo when sha is not on the branch or a revert of it is already there."""
    own = list(own)
    head = _git(repo, "rev-parse", "HEAD")
    if not head or (before == sha and not own) or _git_run(repo, "merge-base", "--is-ancestor", sha, head)[0] != 0:
        return None, None
    mark = "Undoes-landing: {}..{}".format(before, sha)
    if _git(repo, "log", "--format=%H", "--fixed-strings", "--grep=" + mark, "{}..{}".format(sha, head)):
        return None, None
    top = head
    steps = [(c + "^", c) for c in own] + ([(before, sha)] if before != sha else [])
    for n, (base, tip) in enumerate(steps):  # each undone on top of the last; a step is a commit only in between
        rc, out, err = _git_run(repo, "merge-tree", "--write-tree", "--merge-base", tip, top, base)
        if rc != 0:
            return "git merge-tree could not undo {}: {}".format(tip[:9], firstline(err or out)), None
        tree = out.split()[0]
        if n < len(steps) - 1:
            rc, top, err = _git_run(repo, "commit-tree", tree, "-p", top, "-m", "sb hub: a step of a back-out")
            if rc != 0:
                return "git commit-tree failed: " + firstline(err), None
            top = top.strip()
    undone = own + (_git(repo, "rev-list", "{}..{}".format(before, sha)).split() if before != sha else [])
    msg = "revert: back out {}\n\n{}\n\n{}\n{}\n".format(_git(repo, "log", "-1", "--format=%s", sha), why, mark,
                                                       "\n".join("Undoes: " + c for c in undone))
    rc, new, err = _git_run(repo, "commit-tree", tree, "-p", head, "-m", msg)
    if rc != 0:
        return "git commit-tree failed: " + firstline(err), None
    rc, out, err = _git_run(repo, "merge", "--ff-only", "--quiet", new.strip(), timeout=300)
    if rc != 0:
        return "git merge --ff-only of the revert failed: " + firstline(err or out), None
    return None, new.strip()


def replay_tree(tree, before, onto):
    """After a revert: the worktree's commits since `before` (the ones the revert undid, and any after them) replayed on
    top of `onto`, the revert, so the next try and landing carry the work again. None, or why not."""
    if not tree or not Path(tree).is_dir() or _git_run(tree, "merge-base", "--is-ancestor", onto, "HEAD")[0] == 0:
        return None  # no worktree, or already replayed
    rc, out, err = _git_run(tree, "rebase", "--autostash", "--reapply-cherry-picks", "--onto", onto, before, timeout=300)
    if rc == 0:
        return None
    _git_run(tree, "rebase", "--abort")
    return "git rebase of its worktree onto the revert failed: " + firstline(err or out)


def undo_landing(landing, why):
    """A landing's revert in the checkout, then its work replayed in its worktree: None, or why not."""
    err, new = revert_landing(landing["repo"], landing["before"], landing["sha"], why, landing.get("own") or ())
    if err:
        return err
    head = new or _git(landing["repo"], "rev-parse", "HEAD")
    return replay_tree(landing.get("tree"), landing["before"], head) if head else None


# a compiler's error line names its file: "Assets/Tests/X.cs(49,92): error CS0117: ..." (C#, tsc --pretty false)
ERROR_LINE = re.compile(r"^\s*([^\s(:][^(:]*?\.\w+)\(\d+,\d+\): error\b.*$", re.M)


def compile_errors(text):
    """(files, lines) a check's output names in its compile errors, each once, in order."""
    found = list(ERROR_LINE.finditer(text or ""))
    return (list(dict.fromkeys(m.group(1).strip() for m in found)),
            list(dict.fromkeys(m.group(0).strip() for m in found)))


def broken_elsewhere(failed, changed):
    """The files a failed check's compile errors name when none of them is one the ticket changed (`changed`): the
    build is broken by something else. [] when they name a file of its own, or no file at all."""
    files, _ = compile_errors(failed)
    return files if files and not set(files) & set(changed) else []


def _failed_cmd(failed):
    """The command of a check failure in words ("check failed: <cmd>")."""
    first = (failed or "").splitlines()[0] if failed else ""
    return first.split(": ", 1)[1] if ": " in first else first


def landing_of(repo, files, upto, since=None):
    """The ticket landing that last touched `files` on the checkout's branch, after `since` (tonight's first base;
    None: no lower bound) up to `upto`: {key, ticket, before, sha}, its commits being
    the run of first-parent commits that carry its `Ticket:` trailer. None when no landing in that range touched
    them, when the newest commit touching them carries no trailer (someone's own fix, not a ticket), or when that
    landing is already backed out."""
    span = "{}..{}".format(since, upto) if since and _git_run(repo, "merge-base", "--is-ancestor", since,
                                                             upto)[0] == 0 else upto
    last = _git(repo, "log", "--first-parent", "-n1", "--format=%H", span, "--", *files)
    if not last:
        return None
    # the Ticket line, wherever it sits in the message (a worker may put Co-Authored-By after it)
    rows = [r.split("\x1f") for r in _git(repo, "log", "--first-parent", "-n", "400", span, "--format=%H\x1f%B\x1e")
            .split("\x1e")]
    rows = [(r[0].strip(), (re.findall(r"^Ticket: *(\S+) *$", r[1], re.M) or [""])[-1])
            for r in rows if len(r) == 2 and r[0].strip()]
    at = next((n for n, (sha, _) in enumerate(rows) if sha == last), None)
    if at is None or not rows[at][1]:
        return None
    ticket, newest, oldest = rows[at][1], at, at
    while newest > 0 and rows[newest - 1][1] == ticket:
        newest -= 1
    while oldest + 1 < len(rows) and rows[oldest + 1][1] == ticket:
        oldest += 1
    before = _git(repo, "rev-parse", rows[oldest][0] + "^")
    sha = rows[newest][0]
    if not before:
        return None
    mark = "Undoes-landing: {}..{}".format(before, sha)
    if _git(repo, "log", "--format=%H", "--fixed-strings", "--grep=" + mark, "{}..HEAD".format(sha)):
        return None
    m = re.fullmatch(r"(.+)/0*(\d+)", ticket)
    return {"key": "{}#{}".format(m.group(1), int(m.group(2))) if m else ticket, "ticket": ticket,
            "before": before, "sha": sha}


def _tail(path, start=0, size=LOG_TAIL):
    """The end of a log from byte `start` on (whole lines only): one try's output, as tries of an item share its log."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            at = max(start, f.tell() - size)
            f.seek(at)
            data = f.read()
    except (OSError, TypeError):
        return ""
    if at > start:  # cut inside a line: that partial line could be any quoted text, so it is dropped
        data = data[data.find(b"\n") + 1:] if b"\n" in data else b""
    return data.decode("utf-8", "replace")


def _vault():
    return Path(os.environ.get("SB_VAULT") or Path.home() / "Documents" / "Second Brain")


def closed_note(key):
    """(title, words) of a ticket that left the open list: how it closed and its last comment, so a run skipped for
    it says why (dropped and merged into another, resolved elsewhere) and not only that it closed. (None, "") when
    its note cannot be found."""
    m = re.fullmatch(r"([\w.-]+(?:/[\w.-]+)*)#(\d+)", str(key))
    if not m or any(p in ("", ".", "..") for p in m.group(1).split("/")):
        return None, ""
    issues = _vault() / "wayfinder" / m.group(1) / "issues"
    found = sorted(p for d in (issues / "done", issues) for p in d.glob("{:03d}[ -]*.md".format(int(m.group(2)))))
    try:
        text = found[0].read_text(encoding="utf-8", errors="replace") if found else ""
    except OSError:
        return None, ""
    head = text.split("\n---", 1)[0] if text.startswith("---\n") else ""
    title = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", head, re.M)
    status = re.search(r"^status:\s*Project\.(\w+)", head, re.M)
    said = re.findall(r"^- \*\*[\d-]+\*\*: (.+)$", text, re.M)
    how = {"Dropped": "dropped", "Finished": "resolved"}.get(status.group(1) if status else "", "closed")
    last = re.sub(r"^(?:R|Ruling):\s*", "", said[-1]).strip() if said else ""
    return (title.group(1) if title else None), (how + ": " + last if last else how) if text else ""


def project_repo(project):
    """The repo folder a wayfinder project's maps name (`repo:` in a map.md), or None."""
    if not re.fullmatch(r"[\w.-]+", str(project)):
        return None
    for md in sorted((_vault() / "wayfinder" / project).glob("*/map.md")):
        try:
            m = re.search(r"^repo:\s*[\"'`]?(.+?)[\"'`]?\s*$", md.read_text(encoding="utf-8"), re.M)
        except OSError:
            continue
        if m and usable_project(m.group(1)):
            return m.group(1)
    return None


REVIEW_PROMPT = ("Review the commits of tonight's tickets on this branch (`git log --grep '^Ticket: '` since {}) "
                 "against each ticket's Done when; write findings to the run folder; change no code.")


def _project_of(map_name):
    """A map's wayfinder project folder, as sbmap names it: the folder prefix, else the name before a dash."""
    parts = map_name.split("/")
    return parts[0] if len(parts) > 1 else map_name.split("-", 1)[0]


def _job_result(text):
    """A headless run's final text: the `result` of the last JSON line that has one, else the log's end."""
    for line in reversed(text.splitlines()):
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict) and isinstance(got.get("result"), str):
            return got["result"]
    return text[-4000:]


def _plain_words(t):
    """The map's `## In plain words`, read from the map.md beside the ticket's issues/ folder."""
    try:
        body = (Path(t["file"]).parents[1] / "map.md").read_text(encoding="utf-8")
    except (OSError, KeyError, IndexError, TypeError):
        body = ""
    m = re.search(r"^## In plain words\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return (m.group(1).strip() if m else "") or t.get("map_title") or t["map"]


def _hub_holds(t):
    """The hub's own claim (`hub <agent>, <time>`) is on this ticket row."""
    return bool(t) and t["status"] == "claimed" and str(t.get("claimed_by") or "").startswith("hub ")


def _fail_class(reason):
    """`no commit`, or the failing check command: three in a row of one class pause the queue."""
    first = reason.splitlines()[0] if reason else ""
    if first.startswith("no commit"):
        return "no commit"
    for lead in ("check failed: ", "check timed out after 20 minutes: "):
        if first.startswith(lead):
            return "the check " + first[len(lead):]
    return None


def media_in(run_folder, num):
    """The sorted names of the pictures and clips a worker left in <run folder>/<num>-media: known kinds, at most
    MEDIA_MAX, none over MEDIA_BYTES (the phone page forwards a file whole)."""
    d = Path(run_folder) / "{}-media".format(int(num)) if run_folder else None
    if not d or not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir()
                  if p.suffix.lower() in MEDIA_TYPES and p.is_file() and p.stat().st_size <= MEDIA_BYTES)[:MEDIA_MAX]


# ---- one ticket from its claim to its end: `sbhub.py run-ticket` and the queue's Supervisor both run a ticket
# through TicketRun, so there is one way to run a ticket. Its answer is one result (the contract's
# RunTicketResult): what happened, and what the queue does next (retry on another model, or wait for a limit) ----

RESULT_STATES = ("done", "failed", "skipped", "retry", "stopped", "recheck", "redo", "unclean")
STOP_WHY = {"auth": "when its login expired", "limit": "at its usage limit"}


def stop_of(run, now):
    """{kind, agent, until} when this try's own output shows a logout (kind `auth`, until None) or a usage limit
    (kind `limit`: a rejected window's exact reset, else the reset its message names); None otherwise."""
    text = _tail(run["log"], run.get("start", 0))
    said = _said(text)
    if run.get("auth") or logged_out(said):
        return {"kind": "auth", "agent": run["agent"], "until": None}
    rejected = next((r for u, r in reversed(readings(text)) if r and r > now), None)
    until = rejected or limited_until(said, now)
    return None if until is None else {"kind": "limit", "agent": run["agent"], "until": until}

# ---- a landed change to the hub's own code: the page is rebuilt (not in git) and the hub restarts itself ----

HUB_DIR = "skills/sb/hub"
HUB_WEB = HUB_DIR + "/packages/web/"
REBUILD_TAIL = 12  # lines of a failed build shown to the owner
SERVICE_SH = Path(__file__).resolve().parent / "sbhub_service.sh"
RESTART_HOLD = 120  # seconds no review starts after the real restart was sent, while the service ends this process


SCRIPTS = "skills/sb/scripts/"
TEMPLATES = "skills/sb/templates/"
_LOADED = {}


def hub_modules():
    """The scripts the hub loads: sbhub.py's imports that live beside it, and theirs in turn (read from the code,
    not listed by hand), as repo paths. A change to any of them is not in the running hub until it restarts."""
    here = Path(__file__).resolve().parent
    if here not in _LOADED:
        seen, todo = set(), [Path(__file__).stem]
        while todo:
            name = todo.pop()
            f = here / (name + ".py")
            if name in seen or not f.is_file():
                continue
            seen.add(name)
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    todo.extend(a.name.split(".")[0] for a in n.names)
                elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                    todo.append(n.module.split(".")[0])
        _LOADED[here] = {SCRIPTS + n + ".py" for n in seen}
    return _LOADED[here]


def rebuild_kind(paths):
    """What a landed change to `paths` needs: "restart" (the hub's server, the scripts it imports or the templates
    it fills: build, then restart), "web" (only the page: build, no restart) or None (nothing of the hub's)."""
    kind = None
    for p in paths:
        if p.startswith(HUB_WEB) or p == HUB_DIR + "/README.md":
            kind = kind or "web"
        elif (p.startswith(HUB_DIR + "/") or p.startswith(TEMPLATES) or re.fullmatch(SCRIPTS + r"sbhub[^/]*\.py", p)
              or p in hub_modules()):
            return "restart"
    return kind


class Rebuild:
    """Rebuilds the board and restarts the hub after a ticket landed in the checkout this hub runs from.

    `build()` and `restart()` return (ok, text): the real ones run pnpm and `sbhub_service.sh restart` (detached:
    it ends this very process, whose workers are adopted by the next one). A build waits until no ticket of the
    repo is landing, and a failed build leaves the running hub alone and puts a line in Waits for you."""

    def __init__(self, hub, root=None, build=None, restart=None, wait=True):
        self.hub, self.wait = hub, wait
        self.root = root or _git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel")
        self.build = build or self._build
        self.restart = restart or self._restart
        self.cond = threading.Condition()
        self.landing = {}  # repo -> tickets landing now
        self.pending = {}  # repo -> "web" | "restart", waiting for the build
        self.working = set()  # repos whose build or restart is under way
        self.going = {}  # repo -> until when this process, restarted by the service, is about to end
        self.thread = None

    def mine(self, repo):
        return bool(self.root) and os.path.realpath(str(repo)) == os.path.realpath(self.root)

    def landing_in(self, repo, delta):
        repo = os.path.realpath(str(repo))
        with self.cond:
            self.landing[repo] = self.landing.get(repo, 0) + delta
            self.cond.notify_all()

    def after(self, repo, paths):
        """A ticket landed with these changed paths: start a rebuild when they are the hub's own and the checkout is
        the one this hub runs from. Returns the thread (tests join it), or None."""
        kind = rebuild_kind(paths) if self.mine(repo) else None
        return self.ask(repo, kind) if kind else None

    def busy(self, repo):
        """A rebuild or restart is waiting or under way for `repo`: nothing may start a review on it."""
        repo = os.path.realpath(str(repo))
        with self.cond:
            return repo in self.pending or repo in self.working or self.going.get(repo, 0) > time.time()

    def ask(self, repo, kind):
        """Queue a rebuild of `kind` for `repo` (after() and a review that needs a restart both come here)."""
        repo = os.path.realpath(str(repo))
        with self.cond:
            old = self.pending.get(repo)
            self.pending[repo] = "restart" if "restart" in (old, kind) else kind
            if self.thread:
                return self.thread  # the running one takes it (it clears self.thread under the lock as it ends)
            self.thread = threading.Thread(target=self._run, args=(repo,), daemon=True)
            self.thread.start()
            return self.thread

    def _run(self, repo):
        while True:
            with self.cond:
                while self.landing.get(repo):
                    self.cond.wait(1)
                kind = self.pending.pop(repo, None)
                if kind:
                    self.working.add(repo)
                else:
                    self.working.discard(repo)
                    self.thread = None  # under the lock: a later ask() starts a new one, none is lost
                    return
            ok, text = self.build()
            if not ok:
                self._tell("The hub's page did not build after a merge; the running hub is unchanged. Last lines:\n"
                           + "\n".join(text.strip().splitlines()[-REBUILD_TAIL:]))
                continue
            if kind == "restart":
                ok, text = self.restart()
                if not ok:
                    self._tell("The hub was rebuilt but did not restart: " + firstline(text))
                elif self.restart == self._restart:
                    with self.cond:  # the service is ending this process: no review starts on the old code meanwhile
                        self.going[repo] = time.time() + RESTART_HOLD

    def _tell(self, text):
        try:
            self.hub.ask("hub", text, ["Got it", "Dismiss"], "Got it", 10 * 365 * 86400)
        except ValueError:
            pass

    def _build(self):
        try:
            r = subprocess.run(["pnpm", "--dir", str(Path(self.root) / HUB_DIR), "build"], capture_output=True,
                               text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
        return r.returncode == 0, (r.stdout + r.stderr)

    def _restart(self):
        try:  # its own session: it kills this process, and must not go down with it
            subprocess.Popen(["bash", str(SERVICE_SH), "restart"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            return False, str(e)
        return True, ""


class TicketRun:
    """Start a ticket's worker (`start`) and judge it once it ended (`finish`). It claims, briefs, launches, checks,
    resolves or comments, and releases through sbmap; it never touches the hub's queue state: the caller applies the
    result (the Supervisor to its queue item; `run-ticket` prints it).

    `hub` gives the clock (`now`), the home, the launcher and the fresh ticket rows; `item` is the queue item's
    fields from earlier tries (tries, stops, retry, resume, base_sha, tree, branch); `run` is the dict a started
    worker lives in: p, t, agent, inst, base, log, start, folder, tree, branch."""

    def __init__(self, hub, port, limit=WORKER_LIMIT, stopping=lambda: False):
        self.hub, self.port, self.limit, self.stopping = hub, port, limit, stopping
        self.rebuild = Rebuild(hub)
        self.backed_out = None  # the Supervisor's: an earlier landing was backed out for a later one's compile

    @staticmethod
    def sbmap(*args):
        return sbmap_call(*args)

    @staticmethod
    def result(item, state, note, run=None, commit=None, checks=None, retry=None, stop=None, model=None, verdict=None,
               review=None, redo=None):
        """The one answer of a ticket's run (see RESULT_STATES). `verdict` is the second pass's (finished, partly or
        not met; None when none ran or it printed none) and `review` its file in the run folder. `redo`: the
        review-driven try, {commit, verdict, findings, review, base} of the first try; on a `redo` result it is the
        one just asked for, else the item's (None when it had none)."""
        run = run or {}
        t = run.get("t") or {}
        folder = run.get("folder") or (str(Path(run["log"]).parent) if run.get("log") else None)
        num = int(t["num"]) if t.get("num") is not None else int(item["key"].rsplit("#", 1)[-1])
        report = str(Path(folder) / "{}.md".format(num)) if folder else None
        return {"key": item["key"], "state": state, "note": note, "commit": commit, "checks": list(checks or []),
                "media": media_in(folder, num) if state in ("done", "failed") else [],
                "retry": retry, "stop": stop, "agent": run.get("agent"), "model": model or item.get("model"),
                "tries": int(item.get("tries") or 0) + 1, "stops": int(item.get("stops") or 0),
                "base": run.get("base"), "log": run.get("log"),
                "report": report if report and os.path.isfile(report) else None, "run": folder,
                "tree": run.get("tree"), "branch": run.get("branch"), "verdict": verdict,
                "review": review if review and os.path.isfile(review) else None,
                "redo": redo if redo is not None else item.get("redo")}

    def rebuild_after(self, repo, base, sha):
        """A resolved ticket's commit: rebuild (and restart) when it touched the hub's own code."""
        rc, out, _ = _git_run(repo, "diff", "--name-only", "{}..{}".format(base, sha)) if base else (1, "", "")
        return self.rebuild.after(repo, out.split()) if rc == 0 else None

    # ---- the ticket's row and its claim ----

    def row(self, key):
        """(found, row): the ticket read now; found is False when sbmap could not be read."""
        rows = self.hub._fresh_tickets()
        if rows is None:
            return False, None
        return True, next((t for t in rows if sbqueue.key(t) == key), None)

    def release(self, key):
        """Reopen the ticket when the hub holds its claim (`hub <agent>`); a session's claim, or a ticket
        resolved meanwhile, is left alone."""
        found, t = self.row(key)
        if _hub_holds(t):
            self.sbmap("set", t["map"], "{:03d}".format(int(t["num"])), "status=open")

    def board(self, map_name):
        """The map's run board for today (`sbmap run <map>`), or None when sbmap failed."""
        rc, out, err = self.sbmap("run", map_name)
        if rc != 0 or not out:
            return None
        return str(_vault() / out.splitlines()[-1])  # sbmap prints it vault-relative (absolute outside the vault)

    # ---- starting ----

    def start(self, item, t, name, inst, board=None):
        """(run, None) once the worker runs, or (None, result) when it could not start: the board, the base
        commit, the worktree, the claim or the launch failed. `item["model"]` is the model it runs on."""
        key, nnn = item["key"], "{:03d}".format(int(t["num"]))
        board = board if board is not None else self.board(t["map"])
        tree, branch = item.get("tree"), item.get("branch")
        bare = {"t": t, "agent": name, "inst": inst, "tree": tree, "branch": branch}
        # a later try (cut off by a limit, or after a failed one) goes on in the worktree it had
        reuse = bool(tree) and bool(item.get("resume") or item.get("tries")) and Path(tree).is_dir()
        where = tree if tree else t["repo"]
        # a try after one cut off by a limit or a logout keeps its base: the verdict sees all of the ticket's commits
        base = item.get("resume") and item.get("base_sha") or _git(where if reuse else t["repo"], "rev-parse", "HEAD")
        if board is None or not base:
            return None, self.result(item, "failed", "could not start: " + (
                "sbmap run failed" if board is None else "the repo has no commit to start from"), bare)
        if tree and not reuse:
            why = make_tree(t["repo"], tree, branch, base)
            if why:
                return None, self.result(item, "failed", "could not start: could not make its worktree: " + firstline(why),
                                         bare)
        if _hub_holds(t):  # a claim of the hub's own left from an earlier try: reopened, then claimed afresh
            self.sbmap("set", t["map"], nnn, "status=open")
        rc, out, err = self.sbmap("claim", t["map"], nnn, "--by", "hub " + name)
        if rc != 0:
            return None, self.result(item, "skipped", "could not claim it: " + (err or out), bare)
        folder = Path(board).parent
        log = str(folder / "{}.log".format(int(t["num"])))
        # a stop, a restart or the review's one more try goes on with the try's own session (an opus retry is a new
        # one); with none to go on with, it starts afresh as below
        going_on = item.get("resume") or item.get("redo") and not item.get("retry")
        sid = resumable(item, inst, where) if going_on else None
        if sid:
            r = item.get("resume")
            what = ("This session stopped {}{}; the hub resumed it.".format(r["why"], " on " + r["agent"] if r.get(
                "agent") else "") if r else "Your work landed and the Opus review read it." + redo_brief(item["redo"]))
            brief = CONTINUE.format(what=what, base=base[:12], report=folder / "{}.md".format(int(t["num"])),
                                    ticket="{}/{}".format(t["map"], nnn))
        else:
            brief = sbqueue.brief(t, _plain_words(t), str(folder), where, branch or
                                  _git(t["repo"], "rev-parse", "--abbrev-ref", "HEAD") or "the current branch")
        if item.get("retry") and not sid:
            prev = Path(item["run"]) / "{}.md".format(int(t["num"])) if item.get("run") else None
            brief += retry_brief(item, tree, branch, item.get("first_base") or base,
                                 str(prev) if prev and prev.is_file() else None)
        if item.get("redo") and not sid:
            brief += redo_brief(item["redo"])
        if item.get("resume") and not sid:
            r, paths = item["resume"], " ".join(t.get("paths") or [])
            brief += RESUME.format(agent=r["agent"], why=r["why"], base=base, log=r.get("log") or log,
                                   diff="`git diff -- {}`".format(paths) if paths else "`git diff`")
        env = {"SB_HUB_AGENT": key, "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.port),
               "SB_HUB_RUN": str(folder)}
        try:
            start = os.path.getsize(log)  # launch appends: this try's output begins here
        except OSError:
            start = 0
        if is_unity(t["repo"]):  # the guard refuses the Editor to the worker; the integrator has it after landing
            env["SB_HUB_UNITY"] = "off"
            brief += UNITY_WORKER
        run = {**bare, "base": base, "first_base": item.get("first_base") or base, "log": log, "start": start,
               "folder": str(folder), "resumed": bool(sid)}
        try:
            if self.stopping():
                raise OSError("the hub is stopping")
            # the resume goes only to a resumed launch: a test's launcher may take the six plain arguments
            run["p"] = self.hub.launcher(inst, brief, where, item["model"], env, log, **({"resume": sid} if sid else {}))
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            self.release(key)
            return None, self.result(item, "failed", "could not start the worker: {}".format(e), run)
        run["session"] = getattr(run["p"], "session", None)
        run["session_dir"] = config_dir(inst) if run["session"] else None
        return run, None

    # ---- judging ----

    def finish(self, item, run, over, recheck=False):
        """The result of a worker that ended (`over`: it ran past the limit and was killed): checked in code,
        then `landed` (its commit and checks passed and its work landed: its map's second pass judges it when the
        map's run ends, see review_start and review_end; `checked` is the hub's reason), retried, stopped for a limit or a logout, or failed with a
        comment on the ticket. A check that exited 75 could not run: the result is `recheck`, the commit and the
        claim stay, the worker is not run again. `recheck`: only the checks run again (no stop or opus retry is
        looked for)."""
        t = run["t"]
        tree, branch = run.get("tree"), run.get("branch")
        checks = []
        if over:
            passed, reason, sha = False, ran_past(self.limit), None
        elif not tree:
            report = Path(run["log"]).parent / "{}.md".format(int(t["num"])) if run.get("log") else None
            passed, reason, sha = sbqueue.verdict(t, t["repo"], run["base"], run=_recording(checks), report=report,
                                                    first_base=run.get("first_base"))
            self.report_checks(t, run, passed, reason, sha, checks)
        else:
            passed, reason, sha, checks = self.land(t, run, tree)
            self.report_checks(t, run, passed, reason, sha, checks)
            if run.get("integrate"):  # landed in the checkout, the Unity lock held: the Supervisor starts its stage
                return {**self.result(item, "integrate", "landed; its Unity stage starts", run, sha, checks),
                        "integrate": run["integrate"], "t": t}
        if run.get("blocking"):
            return {**self.result(item, "unclean", "landed on its branch {}, waiting for a clean checkout: unsaved "
                                  "changes to {}".format(branch, ", ".join(run["blocking"])), run, sha, checks),
                    "blocking": run["blocking"]}
        if passed is None:
            return self.result(item, "recheck", reason.splitlines()[0], run, sha, checks)
        if tree and not passed:
            reason += "\nIts work stays on branch {} in {}.".format(branch, tree)
        if passed:  # a worker that did the work lands, whatever it printed afterwards; its map's second pass judges it
            wait = "landed, not judged yet: the Opus review judges it when its map's run ends, or once it waited {} " \
                   "minutes".format(int(review_every() // 60))
            return {**self.result(item, "landed", wait, run, sha, checks), "checked": reason}
        # a failed run whose own output (not an earlier try's) names a usage limit or a logout is tried again
        if not over and not recheck:
            stopped = self.stopped(item, run, checks)
            if stopped:
                return stopped
            if resume_failed(run):  # no try and no stop: queued again at the front, to start afresh
                self.release(item["key"])
                note = "its session could not be resumed on {}; it starts afresh".format(run["agent"])
                return {**self.result(item, "stopped", note, run, sha, checks), "stops": int(item.get("stops") or 0),
                        "fresh": True}
        return self.again(item, run, reason, sha, checks)

    def again(self, item, run, reason, sha, checks=()):
        """A try that failed (its check, its landing, its time, no commit): `retry`, queued again at the front from
        its kept work with every try's reason, up to TRIES_MAX tries, from OPUS_FROM on Opus; `failed` for the owner
        after the last, or once the same failure came SAME_MAX tries in a row with no new commit. A stop at a limit
        or a logout never gets here: it is no try."""
        t = run["t"]
        fails = list(item.get("fails") or []) + [{"model": item.get("model") or t.get("tier") or "sonnet",
                                                   "why": firstline(reason)[:300], "commit": sha}]
        last = [(_fail_class(f["why"]) or f["why"], f["commit"]) for f in fails[-SAME_MAX:]]
        same = len(last) == SAME_MAX and len(set(last)) == 1
        stuck = UNDO_FAILED in reason  # its work is still in the checkout: another try would land on top of it
        if len(fails) < TRIES_MAX and not same and not stuck:
            opus = len(fails) + 1 >= OPUS_FROM and (run.get("inst") or {}).get("kind") != "agy"  # agy keeps its model
            model = "opus" if opus else fails[-1]["model"]
            self.release(item["key"])
            return self.result(item, "retry", "try {} of {} failed, try {} {}: {}".format(
                len(fails), TRIES_MAX, len(fails) + 1, "on " + model, firstline(reason)), run, sha, checks,
                retry={"model": model, "reason": reason, "fails": fails})
        why = ("its landing could not be backed out" if stuck else
               "the same failure {} tries in a row with no new commit".format(SAME_MAX) if same else
               "{} tries, the most it gets".format(len(fails)))
        every = "\n".join("try {} ({}): {}{}".format(n, f["model"], f["why"], ", commit " + f["commit"][:9]
                                                    if f.get("commit") else "") for n, f in enumerate(fails, 1))
        out = self.fail(item, run, "{}\nIt waits for you after {}. Every try:\n{}".format(reason, why, every), sha, checks)
        return {**out, "fails": fails}

    def stopped(self, item, run, checks=()):
        """A `stopped` result when this try's own output shows a logout or a usage limit (a rejected window's
        exact reset, else the reset its message names), else None. The claim is released and the item goes back
        to the queue's front for any agent that fits; after STOPS_MAX stops it fails instead."""
        stop = stop_of(run, self.hub.now())
        if stop is None:
            return None
        run["stopped"] = True
        stops = (item.get("stops") or 0) + 1
        auth, until = stop["kind"] == "auth", stop["until"]
        why = STOP_WHY[stop["kind"]]
        if stops >= STOPS_MAX:  # something keeps cutting it off: the owner looks rather than the queue looping
            out = self.fail(item, run, "stopped {} times at a usage limit or a logout (the last on {}, {}); not tried "
                            "again".format(stops, run["agent"], why), None, checks)
            return {**out, "stop": stop, "stops": stops}
        self.release(item["key"])
        note = "{} stopped {}{}; queued again at the front".format(
            run["agent"], why, "" if auth else " (until {})".format(_hm(until)))
        return {**self.result(item, "stopped", note, run, checks=checks, stop=stop), "stops": stops}

    def land(self, t, run, tree):
        self.rebuild.landing_in(t["repo"], 1)
        try:
            return self._land(t, run, tree)
        finally:
            self.rebuild.landing_in(t["repo"], -1)

    def _land(self, t, run, tree):
        """(passed, reason, sha, checks) of a worktree ticket: its commits rebased onto the checkout's newest commit,
        judged there, then fast-forwarded into the checkout; the worktree and branch go once it landed.
        Check lines marked `after-landing: ` (sbqueue.AFTER_LANDING) run in the checkout itself after the
        fast-forward, under the repo's Unity lock (waiting while a chat session holds it); one that fails backs the
        landing out with one revert commit and the work is replayed on its branch for the next try."""
        report = Path(run["log"]).parent / "{}.md".format(int(t["num"])) if run.get("log") else None
        after = sbqueue.after_landing(t["checks"])
        first = {**t, "checks": sbqueue.before_landing(t["checks"])}
        checks, sha = [], None
        for _ in range(LAND_TRIES):
            checks = []
            head = _git(t["repo"], "rev-parse", "HEAD")
            why = rebase_tree(tree, head) if head else "the checkout has no commit"
            if why:
                return False, "could not land: " + why, None, checks
            passed, reason, sha = sbqueue.verdict(first, tree, head, run=_recording(checks), report=report,
                                                    first_base=run.get("first_base"))
            elsewhere = broken_elsewhere(reason, _git(tree, "diff", "--name-only", head, sha).split()) \
                if passed is False and sha else []
            if elsewhere and self.check_main(t["repo"], {"cmd": _failed_cmd(reason), "after": False}, head) is False:
                # the newest commit it was rebased on does not build either: not this ticket's try
                self.build_mark(t["repo"], errors=compile_errors(reason)[1], by=sbqueue.key(t), held={
                    "cmd": _failed_cmd(reason), "after": False, "files": elsewhere, "head": head,
                    "at": self.hub.now()})
                return None, "{} ({}): {}".format(HELD, ", ".join(elsewhere[:3]), reason), sha, checks
            if not passed:
                return passed, reason, sha, checks
            stage = is_unity(t["repo"])
            locked = (after or stage) and sha and {"key": sbqueue.key(t), "repo": str(t["repo"]), "before": head,
                                                   "sha": sha, "tree": str(tree), "branch": run.get("branch") or ""}
            if locked:
                held = self.take_unity(locked)
                if held:
                    return None, "could not land yet: {}".format(held), sha, checks
            why = land(t["repo"], sha) if sha else None
            if why is None and sha:
                run["landed_on"] = head
            if locked and why is None and stage:  # its Unity stage: the lock stays held until the integrator ends
                run["integrate"] = {**locked, "dirty": dirty_files(t["repo"])}
                return True, reason, sha, checks
            if locked and why is None:
                failed = self.after_landing(locked, after, checks)
                if failed:
                    return failed + (sha, checks)
            elif locked:
                self.hub.unlock(unity_lock(t["repo"]), _landing_by(locked))
            if why == MOVED:
                continue  # someone committed on the checkout meanwhile: on top of that, and checked again
            if isinstance(why, list):  # unsaved edits to its files in the checkout: it waits on its branch for them
                run["blocking"] = why
                return None, "could not land yet: the checkout has unsaved changes to " + ", ".join(why), sha, checks
            if why:
                return False, "could not land: " + why, sha, checks
            drop_tree(t["repo"], tree, run.get("branch") or "")
            return passed, reason, sha, checks
        return False, "could not land: the checkout kept gaining commits ({} tries)".format(LAND_TRIES), sha, checks

    def integrated(self, item, run, over):
        """The result of a ticket whose Unity stage ended: the integrator's run in the main folder, the repo's Unity
        lock held since the landing. Files Unity left changed are saved to a patch and restored, then:
        `works` (or no verdict): the after-landing checks run on the main folder with the integrator's fixes in
        (after_landing, which lets go of the lock), and it is `landed` when they pass;
        `broken`, or a run past its limit: the whole stage is backed out, and the ticket is tried again, told the
        integrator's report; `no unity`: backed out, not a try, it lands again at its recheck."""
        t, stage = run["t"], dict(item.get("integrate") or run.get("integrate"))
        repo, num = stage["repo"], int(t["num"])
        folder = Path(stage.get("folder") or run.get("folder") or Path(run["log"]).parent)
        report = folder / "{}-integrate.md".format(num)
        tidy_stage(repo, stage.get("dirty") or [], folder / "{}-unity-leftovers.patch".format(num))
        head = _git(repo, "rev-parse", "HEAD") or stage["sha"]
        landing = {**{k: stage.get(k) for k in ("key", "repo", "before", "tree", "branch", "sha")},
                   "own": stage_commits(repo, stage["sha"], stage["key"])}
        verdict = "broken" if over else stage_verdict(report)
        tell = "\nThe integrator's report: {}".format(report) if report.is_file() else ""
        checks = []
        if verdict in ("broken", "no unity"):
            why = ("the integrator ran past {} minutes".format(int(self.limit // 60)) if over else
                   "the integrator could not make it work in Unity" if verdict == "broken" else
                   "the integrator could not reach the Unity Editor")
            err = undo_landing(landing, why)
            if err:  # the lock stays held, so nothing lands on top until the owner looks
                self.build_mark(repo, broken=True, by=landing["key"])
                threading.Thread(target=notify, daemon=True, args=("sb hub: needs you", "{}: {} could not be backed "
                                 "out of the main folder".format(Path(repo).name, landing["key"]))).start()
                return self.fail(item, run, "{}, and {}: {}\nThe {} lock stays held: fix the main folder, then free "
                                 "it.{}".format(why, UNDO_FAILED, err, unity_lock(repo), tell), head, checks)
            self.hub.unlock(unity_lock(repo), _landing_by(landing))
            if stage.get("only"):  # a Unity pass: its fixes undone, the ticket is the owner's again
                return self.fail(item, run, "the Unity pass: {}; its fixes were backed out.{}".format(why, tell),
                                 stage["sha"], checks)
            if verdict == "no unity":
                return self.result(item, "recheck", why + "; backed out, it lands again", run, stage["sha"], checks)
            return self.again(item, run, "{}; its landing was backed out.{}".format(why, tell), stage["sha"], checks)
        failed = self.after_landing(landing, sbqueue.after_landing(t["checks"]), checks)
        if failed:
            passed, reason = failed
            if stage.get("only"):
                return self.fail(item, run, "the Unity pass: " + reason + tell, stage["sha"], checks)
            if passed is None:
                return self.result(item, "recheck", reason.splitlines()[0], run, stage["sha"], checks)
            return self.again(item, run, reason + tell, stage["sha"], checks)
        if stage.get("tree"):
            drop_tree(repo, stage["tree"], stage.get("branch") or "")
        run["landed_on"] = stage["before"]
        note = "landed and played in Unity{}; the Opus review judges it when its map's run ends".format(
            "" if verdict else " (the integrator wrote no verdict)")
        return {**self.result(item, "landed", note, run, head, checks),
                "checked": "the integrator's verdict: {}".format(verdict or "none")}

    def in_stage(self, key):
        """True while the queue item `key` is in its Unity stage (its integrator runs)."""
        with self.hub._lock:
            return any(i["key"] == key and i.get("integrate") for i in self.hub._data["queue"]["items"])

    def take_unity(self, landing):
        """Take the repo's Unity lock for this landing, waiting up to LAND_LOCK_WAIT while someone else holds it:
        None once held, else who holds it."""
        key, by = unity_lock(landing["repo"]), _landing_by(landing)
        end = time.time() + LAND_LOCK_WAIT
        while True:
            got = self.hub.lock(key, by, landing=landing)
            if got.get("ok"):
                drop_unsaved_scenes(landing["repo"])
                return None
            other = str(got.get("held_by") or "")[len("sb-hub landing "):]
            if other and str(got.get("held_by")).startswith("sb-hub landing ") and self.in_stage(other):
                return "{}: {} is in its Unity stage".format(UNITY_WAIT, other)  # it may hold it long: no wait
            if time.time() >= end or self.stopping():
                return "{} is held by {}".format(key, got.get("held_by"))
            time.sleep(LAND_LOCK_POLL)

    def after_landing(self, landing, cmds, checks):
        """Run the after-landing checks in the checkout, which holds the ticket's work now; then let go of the Unity
        lock. None when they pass, else (passed, reason): False when one failed (the landing is reverted, the ticket
        tried again or failed as any failed check), None when one could not run (reverted too: it lands again at
        its recheck).
        A compile that fails only in files this landing did not touch blames the earlier landing that last touched
        them since the build was last green: that one is backed out (and queued again through `backed_out`), the
        checks run again, and this ticket stays landed when they pass. A landing that cannot be backed out keeps
        the Unity lock, so nothing lands on a broken build until it is fixed."""
        repo, keep = landing["repo"], False
        try:
            changed = "\n".join([_git(repo, "diff", "--name-only", landing["before"], landing["sha"])] + [
                _git(repo, "show", "--name-only", "--format=", c) for c in landing.get("own") or ()]).strip()
            failed = sbqueue._run_checks(cmds, repo, _recording(checks), changed)
            if failed and not failed.startswith(sbqueue.NOT_RUN):
                failed = self._blame_earlier(landing, failed, set(changed.split()), cmds, checks)
            if not failed:
                self.build_mark(repo, green=_git(repo, "rev-parse", "HEAD"))
                return None
            files, lines = compile_errors(failed)
            elsewhere = [] if failed.startswith(sbqueue.NOT_RUN) else broken_elsewhere(failed, changed.split())
            if failed.startswith(sbqueue.NOT_RUN):  # the board shows the first line: what was last known broken
                head, _, rest = failed.partition("\n")
                failed = "{}; {}\n{}".format(head, self.last_errors(repo), rest)
            elif lines:
                self.build_mark(repo, errors=lines, by=landing["key"])
            why = "{}\nIt landed on {} as {}; the hub backed it out.".format(
                failed, Path(repo).name, landing["sha"][:9])
            err = undo_landing(landing, failed.splitlines()[0])
            if err:  # the checkout keeps the broken work: nothing lands on it, and the owner must see it
                keep = True
                self.build_mark(repo, broken=True, errors=lines, by=landing["key"])
                why = ("{}\nIt landed on {} as {} and " + UNDO_FAILED + ": {}\nThe {} lock stays held, so nothing "
                       "else lands on the broken build: fix it, then free the lock.").format(
                    failed, Path(repo).name, landing["sha"][:9], err, unity_lock(repo))
                threading.Thread(target=notify, daemon=True, args=("sb hub: needs you", "{}: the build is broken "
                                 "and {} could not be backed out".format(Path(repo).name, landing["key"]))).start()
            elif elsewhere:  # backed out, its work kept on its branch: is the main folder broken without it too?
                alone = sbqueue._run_checks(cmds, repo, _recording(checks), "")
                if alone is None:  # it builds without this landing: the clash is this ticket's to mend, its try
                    self.build_mark(repo, green=_git(repo, "rev-parse", "HEAD"))
                    return False, ("after landing, {}\nThe main folder builds without your work, so the clash is "
                                   "between your change and {}: mend it on your branch (you may change those "
                                   "files).").format(why, ", ".join(elsewhere[:5]))
                self.build_mark(repo, held={"cmd": _failed_cmd(failed), "after": True, "files": elsewhere,
                                            "head": _git(repo, "rev-parse", "HEAD"), "at": self.hub.now()})
                return None, "after landing, {} ({}): {}".format(HELD, ", ".join(elsewhere[:3]), why)
            return (None if failed.startswith(sbqueue.NOT_RUN) and not err else False), "after landing, " + why
        finally:
            if not keep:
                self.hub.unlock(unity_lock(repo), _landing_by(landing))

    def _blame_earlier(self, landing, failed, mine, cmds, checks):
        """`failed` when this landing's own files are among the errors' or no earlier landing of tonight is to
        blame; else the earlier landing that last touched the error files is backed out and the checks run again.
        The blame sticks only when that makes them pass (None); when they still fail, the back-out is undone and
        what failed is returned, so this landing is backed out as before."""
        repo = landing["repo"]
        files, lines = compile_errors(failed)
        if not files or mine & set(files):
            return failed
        with self.hub._lock:
            since = ((self.hub._data["queue"].get("bases") or {}).get(str(repo)) or {}).get("sha")
        culprit = landing_of(repo, files, landing["before"], since)
        if culprit is None or culprit["key"] == landing["key"]:
            return failed
        err, revert = revert_landing(repo, culprit["before"], culprit["sha"], "its files do not compile once {} "
                                     "landed on top: {}".format(landing["key"], lines[0] if lines else firstline(failed)))
        if err or not revert:
            return failed
        again = sbqueue._run_checks(cmds, repo, _recording(checks),
                                    _git(repo, "diff", "--name-only", landing["before"], landing["sha"]))
        if again:  # backing it out did not mend the build: it was not that landing, so it goes back in
            revert_landing(repo, _git(repo, "rev-parse", revert + "^"), revert,
                           "backing out {} did not mend the build".format(culprit["key"]))
            return again
        if self.backed_out:
            self.backed_out({**culprit, "repo": repo, "revert": revert, "files": files, "errors": lines,
                             "after": landing["key"]})
        return None

    def build_of(self, repo):
        with self.hub._lock:
            return dict((self.hub._data["queue"].get("builds") or {}).get(str(repo)) or {})

    def build_mark(self, repo, green=None, broken=None, errors=None, by=None, held=None):
        """What the hub knows of a repo's build: `green`, the newest commit whose after-landing checks passed (it
        clears the rest); `errors`, the last compile errors it saw, with the ticket and time; `broken` while the
        checkout keeps a build that does not compile (the board says so); `held` while the build is broken outside
        any ticket's files: {cmd, after, files, head, at}, the check that failed and where it last ran."""
        with self.hub._lock:
            q = self.hub._data["queue"]
            b = q.setdefault("builds", {}).setdefault(str(repo), {})
            if green:
                b.clear()
                b["green"] = green
            if errors:
                b.update(errors=list(errors)[:10], errors_by=by, errors_at=self.hub.now())
            if broken:
                b["broken"] = True
            if held:
                b["held"] = held
            q["version"] += 1
            self.hub._save()

    def check_main(self, repo, held, head):
        """Whether the check that held `repo` passes on its newest commit `head` now: True, False, or None when it
        could not run (the Unity lock is busy, or the tool did not answer). An after-landing check runs in the
        checkout under the Unity lock; any other in a clean copy of `head`."""
        if held.get("after"):
            by = "sb-hub build check"
            if not self.hub.lock(unity_lock(repo), by).get("ok"):
                return None
            try:
                failed = sbqueue._run_checks([held["cmd"]], repo, subprocess.run, "")
            finally:
                self.hub.unlock(unity_lock(repo), by)
        else:
            d = sbqueue._clean_copy(repo, head, subprocess.run)
            if d is None:
                return None
            try:
                failed = sbqueue._run_checks([held["cmd"]], d, subprocess.run, "")
            finally:
                sbqueue._drop_clean_copy(repo, d, subprocess.run)
        if failed and failed.startswith(sbqueue.NOT_RUN):
            return None
        if failed and self.build_of(repo).get("held"):
            self.build_mark(repo, errors=compile_errors(failed)[1], by=self.build_of(repo).get("errors_by"),
                            held={**self.build_of(repo)["held"], "head": head, "at": self.hub.now()})
        return not failed

    def last_errors(self, repo):
        """For a check that could not run, one line: not judged, and the last compile errors the hub saw in this repo
        (their files, the landing and the time), or that it saw none since its last green build; the errors follow."""
        b = self.build_of(repo)
        if not b.get("errors"):
            return "not judged; the hub has seen no compile error in {} since its last green build".format(
                Path(str(repo)).name)
        files = list(dict.fromkeys((e.split("(")[0] or e).rsplit("/", 1)[-1] for e in b["errors"]))
        return "not judged; the last compile errors the hub saw were in {} (after {}, {}):\n{}".format(
            ", ".join(files), b.get("errors_by"), _hm(b["errors_at"]), "\n".join(b["errors"]))

    def report_checks(self, t, run, passed, reason, sha, checks):
        """Append the hub's verdict and every check to the worker's report in the run folder (a run file, not a
        ticket: written directly), so the run itself shows what was tested."""
        report = Path(run["log"]).parent / "{}.md".format(int(t["num"]))
        try:
            text = report.read_text(encoding="utf-8") if report.exists() else ""
            stamp = datetime.fromtimestamp(self.hub.now()).strftime("%Y-%m-%d %H:%M")
            with open(report, "a", encoding="utf-8") as f:
                f.write(hub_checks_section(passed, reason, sha, checks, text, stamp))
        except OSError as e:
            print("sb hub queue: report for {}: {}".format(t["map"], e), file=sys.stderr, flush=True)

    def resolve(self, item, run, sha, reason="", checks=(), review=None):
        key, t = item["key"], run["t"]
        judged = dict(verdict="finished", review=review) if review else {}
        found, now_t = self.row(key)
        if found and not _hub_holds(now_t):
            return self.result(item, "skipped", "passed its checks, but the ticket changed while it ran ({})".format(
                "no longer open" if now_t is None else "claimed by " + str(now_t.get("claimed_by"))), run, sha, checks,
                **judged)
        listed = "; ".join("`{}`".format(c) for c in t["checks"])
        tail = "Model: {} on agent {} (try {}). Worker's report: {}/{}.md; its log: {}.".format(
            item.get("model"), run["agent"], (item.get("tries") or 0) + 1, Path(run["log"]).parent, int(t["num"]),
            run["log"])
        if review:
            tail += " The Opus review judged it finished: {}.".format(review)
        nnn = "{:03d}".format(int(t["num"]))
        # the second pass's verdict as properties a board shows; none given: sbmap marks a task `skipped`
        judged_by = ["--review", "met", "--review-file", review] if review else []
        if not sha:  # research that needed no commit: its findings are the report
            rc, out, err = self.sbmap("resolve", t["map"], nnn, "--gist", t["title"], "--answer",
                                      "Checked by the sb hub in code: {}. {}".format(reason, tail), *judged_by)
            if rc != 0:
                return {**self.fail(item, run, "the report is written, but sbmap resolve failed: " + (err or out), None,
                                    checks), **judged}
            return self.result(item, "done", "resolved: {}, findings in the report".format(
                "no change needed" if reason.startswith("no change needed") else "research"), run, None, checks,
                **judged)
        ran = ("every check exited 0 ({n} of {n}): {}".format(listed, n=len(t["checks"])) if t["checks"] else
               "it has no check commands, so the Opus review of its Done when was its only check")
        answer = "Checked by the sb hub in code: commit {} carries `Ticket: {}/{:03d}` and {}. {}{} {}".format(
            sha, t["map"], int(t["num"]), ran, reason[:1].upper(), reason[1:] + ".", tail)
        rc, out, err = self.sbmap("resolve", t["map"], nnn, "--gist", t["title"], "--answer", answer,
                                  "--commit", sha, "--repo-root", t["repo"], *judged_by)
        if rc != 0 and "remote" in err:  # sbmap stamps a commit only in a repo with an origin: name it in the gist
            rc, out, err = self.sbmap("resolve", t["map"], nnn, "--gist", "{} ({})".format(t["title"], sha[:9]),
                                      "--answer", answer, *judged_by)
        if rc != 0:
            return {**self.fail(item, run, "checks passed, but sbmap resolve failed: " + (err or out), sha, checks),
                    **judged}
        return self.result(item, "done", "resolved, commit " + sha[:9], run, sha, checks, **judged)

    # ---- the second pass: an Opus session judges the landed work against the ticket's Done when ----

    @staticmethod
    def review_file(run, t):
        return str(Path(run["folder"]) / "{}-review.md".format(int(t["num"]))) if run.get("folder") else None

    def _review_agent(self, run):
        """(name, entry) of the Claude account the review runs on: the worker's own when it is a Claude one, else
        the first installed Claude account, else plain `claude`."""
        installed = self.hub._data.get("installed") or {}
        name = run.get("agent")
        inst = run.get("inst") or installed.get(name) or {}
        if inst.get("kind") == "claude":
            return name, dict(inst)
        for n, e in sorted(installed.items()):
            if e.get("kind") == "claude":
                return n, dict(e)
        return "claude", {"kind": "claude", "dir": None, "model": None}

    def review_start(self, entries):
        """Start ONE second pass on REVIEW_MODEL in the map's repo over `entries`, a list of (item, run, sha): each
        landed ticket. It is briefed from templates/review-brief.md with every ticket (`sbmap show`), its commits'
        diff and its worker's report, and writes <run>/<num>-review.md for each (any earlier one is removed first,
        so an old verdict is never read). Returns {p, agent, inst, log, start, files (item key -> review file),
        keys, limit}; OSError, ValueError or SubprocessError when it could not start."""
        item0, run0, _ = entries[0]
        t0 = run0["t"]
        if not run0.get("folder"):
            raise ValueError("the run folder is not recorded")
        cap = max(6000, sbqueue.DIFF_MAX // len(entries))
        sections, files = [], {}
        for item, run, sha in entries:
            t = run["t"]
            rc, shown, err = self.sbmap("show", t["map"], "{:03d}".format(int(t["num"])))
            # a review-driven second try is judged with the first try's commit: both, oldest first
            redo = item.get("redo") or {}
            shas = [c for c in dict.fromkeys((redo.get("commit"), sha)) if c]
            diff = ""
            for c in shas:
                rc2, one, err2 = _git_run(t["repo"], "show", "--stat", "--patch", "--format=fuller", c)
                if rc2 != 0:
                    raise ValueError("git show {} failed: {}".format(c[:9], firstline(err2)))
                diff += one
            folder = Path(run["folder"])
            report = folder / "{}.md".format(int(t["num"]))
            try:
                report_text = report.read_text(encoding="utf-8", errors="replace")
            except OSError:
                report_text = ""
            review = Path(self.review_file(run, t))
            review.unlink(missing_ok=True)
            files[item["key"]] = str(review)
            sections.append(sbqueue.review_section(shown if rc == 0 else "", t["repo"], shas, diff, report,
                                                   report_text, review, redo=redo or None, second=sha, diff_max=cap))
        brief = sbqueue.review_brief(sections, t0["repo"])
        folder = Path(run0["folder"])
        log = str(folder / ("{}-review.log".format(int(t0["num"])) if len(entries) == 1 else "review.log"))
        try:
            start = os.path.getsize(log)
        except OSError:
            start = 0
        name, inst = self._review_agent(run0)
        if self.stopping():
            raise OSError("the hub is stopping")
        env = {"SB_HUB_AGENT": item0["key"], "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.port),
               "SB_HUB_RUN": str(folder)}
        p = self.hub.launcher(inst, brief, t0["repo"], REVIEW_MODEL, env, log)
        return {"p": p, "agent": name, "inst": inst, "log": log, "start": start, "files": files,
                "keys": [i["key"] for i, _, _ in entries], "limit": review_limit(len(entries))}

    def review_end(self, item, run, sha, checked, checks, rv, over=False):
        """The result once the second pass ended: `finished` resolves the ticket with its commit; `partly` and `not
        met` leave it open and claimed by nobody, with the findings as a comment and the commit where it landed
        (result `failed`, naming the verdict); a review that crashed, ran past its limit or wrote no verdict
        could not run: `recheck`, the commit and the claim stay and only the review runs again."""
        t = run["t"]
        path = ((rv or {}).get("files") or {}).get(item["key"]) or self.review_file(run, t)
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace") if path else ""
        except OSError:
            text = ""
        verdict = None if over else sbqueue.review_verdict(text)
        if verdict is None:
            code = getattr(rv.get("p"), "returncode", None) if rv else None
            why = ("it ran past {} minutes".format(int((rv or {}).get("limit") or review_limit(1)) // 60) if over else
                   "it wrote no review file" if not text else "its review file names no verdict")
            if code not in (None, 0) and not over:
                why = "it exited {} and {}".format(code, why[3:])
            return {**self.result(item, "recheck", "review could not run: " + why, run, sha, checks, review=path),
                    "checked": checked}
        if verdict == "finished":
            return self.resolve(item, run, sha, checked, checks, review=path)
        # partly or not met: the first time, one more try with the findings (`redo`, once); after that try,
        # the ticket waits for the owner. Either way the findings go on the ticket and no commit is reverted.
        first = not item.get("redo") and (item.get("tries") or 0) + 1 < TRIES_MAX  # the redo is a try too
        findings = sbqueue.review_findings(text)
        not_met = [f for f in findings if re.search(r"\bnot met\b", f, re.I)]
        if first and path:  # the second try's review writes <num>-review.md afresh: the first one is kept beside it
            kept = Path(path).with_name("{}-review-1.md".format(int(t["num"])))
            try:
                os.replace(path, kept)
                path = str(kept)
            except OSError:
                pass
        commits = [c[:9] for c in dict.fromkeys(((item.get("redo") or {}).get("commit"), sha)) if c]
        landed = ("The worker made no commit." if not commits else "The commit {} is left where it landed.".format(
            commits[0]) if len(commits) == 1 else "Both tries' commits, {} and {}, are left where they landed.".format(
            *commits))
        then = ("It gets one more try with these findings." if first else
                "That was its second try: it waits for the owner.")
        text_c = "The sb hub's Opus review judged this ticket {} against its Done when ({} on agent {}{}). {} {}\n  " \
                 "{}\n  Review: {}".format(
                     verdict, item.get("model"), run.get("agent"), "" if first else ", second try", landed, then,
                     "\n  ".join(findings) or "(the review lists no item)", path)
        self.sbmap("comment", t["map"], "{:03d}".format(int(t["num"])), "--text", text_c)
        self.sbmap("set", t["map"], "{:03d}".format(int(t["num"])), "review=" + verdict, "--no-sync")
        self.release(item["key"])
        if first:
            redo = {"commit": sha, "verdict": verdict, "findings": not_met or findings,
                    "review": path, "base": item.get("base_sha") or run.get("base")}
            note = "judged {} by the Opus review; one more try with its findings{}".format(
                verdict, ": " + not_met[0][2:] if not_met else "")
            return self.result(item, "redo", note[:2000], run, sha, checks, verdict=verdict, review=path, redo=redo)
        note = "judged {} by the Opus review after its second try{}".format(
            verdict, ": " + not_met[0][2:] if not_met else "")
        return self.result(item, "failed", note[:2000], run, sha, checks, verdict=verdict, review=path)

    def fail(self, item, run, reason, sha, checks=()):
        """Leave the ticket open with the reason as a comment and release the claim."""
        t = run["t"]
        text = "The sb hub's run of this ticket failed ({} on agent {}): {}{}".format(
            item.get("model"), run["agent"], reason.replace("\n", "\n  "),
            "\n  The commit {} is left in place.".format(sha[:9]) if sha else "")
        self.sbmap("comment", t["map"], "{:03d}".format(int(t["num"])), "--text", text)
        self.release(item["key"])
        return self.result(item, "failed", reason[:2000], run, sha, checks)


class Supervisor:
    """Runs tonight's queue, one pass per `tick()` (every TICK_EVERY s from `serve`; tests call it).

    It owns each item's state from its worker's process and the verdict checked in code: nothing waits on
    a worker reaching the hub. Every state change happens under the hub's lock; sbmap, git and the workers
    run outside it. The workers' Popen handles live here, in memory: a `running` item with none (the hub
    restarted) has its leftover process group killed, its claim released, and is queued again."""

    def __init__(self, hub, port=None, limit=WORKER_LIMIT, probe=None):
        self.hub, self.port = hub, port or default_port()
        self.runner = TicketRun(hub, self.port, limit, stopping=lambda: self.stopped)  # every ticket's try runs here
        self.runner.backed_out = self._backed_out
        self.probe = probe or probe_usage  # (agent entry, cwd) -> its output; tests hand in their own
        self.probe_async, self.probing = True, []  # probes run in their own thread (tests may run them inline)
        self.close_off = True  # the daily morning close-off job (tests of other things turn it off)
        # item key -> {p, t (the ticket row it started from), agent, inst, base, log, start, pos (log read up to),
        # u0/u1 (its first and newest usage reading), alone (no other worker on its agent overlapped it), braked}
        self.procs = {}
        self.reviews = {}  # map -> its second pass's {p, agent, inst, log, start, files, keys, limit, at}, while it runs
        self.review_lock = threading.Lock()  # the tick's reviews and POST /api/review/now never start one map twice
        hub.supervisor = self  # POST /api/review/now reaches the reviews through it
        self.streak = (None, 0)  # the failure class of the last failed items in a row, and how many
        self.stopped = False
        self.unlanded = False  # the landings an earlier hub left half done are undone at the first tick
        self.note_path = None  # wayfinder/runs/hub-now.md: `serve` sets it; tests leave the vault alone
        self.note_seen = (None, 0, "")  # (the queue's shape at the last write, when, the text written)

    @property
    def limit(self):
        """How long a worker may run before its process group is killed (the runner's, so both agree)."""
        return self.runner.limit

    @limit.setter
    def limit(self, value):
        self.runner.limit = value

    def run(self, every=TICK_EVERY):
        """The daemon thread `serve` starts: find the agents once if none are known, then tick forever."""
        with self.hub._lock:
            scan = not self.hub._data["installed"]
        if scan:
            self.hub.agents_scan()
        while not self.stopped:
            try:
                self.tick()
            except Exception as e:  # one bad pass never stops the queue
                print("sb hub queue: {}: {}".format(type(e).__name__, e), file=sys.stderr, flush=True)
            self.hub.queue_kick.wait(every)  # or sooner, when the owner changes the queue (a resume)
            self.hub.queue_kick.clear()

    def stop(self):
        """Kill every worker's process group; their items are queued again when the hub next starts."""
        self.stopped = True
        for th in self.probing:
            th.join(timeout=5)
        for run in list(self.procs.values()):
            if getattr(run["p"], "sure", True):  # an adopted pid ps could not confirm is never killed
                _kill_group(run["p"], grace=1)
        self.procs.clear()
        for rv in list(self.reviews.values()):  # its items stay `review`: the next hub starts the review afresh
            _kill_group(rv["p"], grace=1)
        self.reviews.clear()

    def sbmap(self, *args):
        try:
            r = subprocess.run([sys.executable, str(SBMAP), *args], capture_output=True, text=True,
                               errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            return 1, "", str(e)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def tick(self):
        if not self.unlanded:
            self._unland()
        self.hub.tickets()  # keeps the page's ticket cache fresh and seeds the queue (both cached)
        self._watch()
        self._reap()
        self._reviews()  # a review that ended is judged before the night's end is looked for
        self._final_review()
        self._close_off()
        self._settle_night(False)  # a night that stops starts nothing new
        if not self.stopped:
            self._held_builds()
            self._rechecks()
            self._unclean()
            self._reviews()  # and one a recheck asked for starts at once
            self._probe()
            self._start()
        self._set_waits()
        self._digest()
        self._settle_night()
        self._night_note()

    def _settle_night(self, ending=True):
        """A stopping night drops what is queued; with `ending`, a night whose items are all judged ends. The tick
        ends it only after the board and the digest have read its items. A night that ends closes every map whose
        tickets have all ended (`sbmap close --finished`), with the morning close-off's housekeeping."""
        with self.hub._lock:
            live = self.hub._data["queue"].get("night")
            if self.hub._night_settle(ending):
                self.hub._save()
            ended = bool(live) and self.hub._data["queue"].get("night") is None
        if ended and self.close_off:
            rc, out, err = self.sbmap("close", "--finished")
            print("sb hub queue: closed the finished maps: {}".format(out or "none") if rc == 0 else
                  "sb hub queue: closing the finished maps failed: {}".format(err or out), file=sys.stderr, flush=True)

    def _night_note(self):
        """Keep the vault's hub-now.md current: on a start or an end, and every NOTE_EVERY s while something
        runs; written only when its text (not its time) changed. Never breaks a tick."""
        if self.note_path is None:
            return
        try:
            now = self.hub.now()
            with self.hub._lock:
                q = json.loads(json.dumps(self.hub._data["queue"]))
            waiting = tuple(sorted("{}#{}".format(t["map"], int(t["num"])) for t in self.hub._tcache[1] or []
                                   if t.get("state") == "waits for you"))
            shape = (q["paused"], tuple((i["key"], i["state"]) for i in q["items"]), waiting, time.strftime("%Y-%m-%d", time.localtime(now)))
            old, at, text = self.note_seen
            running = any(i["state"] == "running" for i in q["items"])
            if shape == old and not (running and now - at >= NOTE_EVERY):
                return
            rows = self.hub._tcache[1] or []
            files, steps, reports = {}, {}, {}
            vault = _vault()
            rel = lambda p: Path(p).resolve().relative_to(vault.resolve()).with_suffix("").as_posix()
            for i in q["items"]:
                if i["kind"] != "ticket" or "#" not in i["key"]:
                    continue
                try:
                    _, _, row, path = self.hub._ticket_file(i["key"])
                    files[i["key"]] = rel(path) if path else None
                    if not files[i["key"]]:
                        del files[i["key"]]
                except (KeyError, ValueError):
                    pass
                if i.get("run"):
                    r = Path(i["run"]) / "{}.md".format(i["key"].rsplit("#", 1)[-1])
                    if r.is_file():
                        try:
                            reports[i["key"]] = rel(r)
                        except ValueError:
                            pass
                if i["state"] == "running":
                    try:
                        acts = self.hub.trail(i["key"])["actions"]
                        steps[i["key"]] = (acts[-1]["label"] or acts[-1]["tool"]) if acts else ""
                    except KeyError:
                        pass
            new = sbhub_snapshot.night_note(q, rows, now, files, steps, reports)
            self.note_seen = (shape, now, new)
            if not sbhub_snapshot.same_note(text or self._note_on_disk(), new):
                sbhub_snapshot.write_whole(self.note_path, new)
        except Exception as e:  # the phone note is a convenience: a tick goes on without it
            err = "{}: {}".format(type(e).__name__, e)
            if err != getattr(self, "note_err", None):  # once per error, not once per tick
                self.note_err = err
                print("sbhub: hub-now.md not written: " + err, file=sys.stderr)

    def _note_on_disk(self):
        try:
            return Path(self.note_path).read_text(encoding="utf-8")
        except OSError:
            return None

    # ---- usage: each account's readings, its learned costs, the brake, the login ----

    def _consume(self, run, final=False):
        """Read what the worker printed since the last look: its usage readings and a login failure."""
        pos = run.get("pos", run.get("start", 0))
        try:
            with open(run["log"], "rb") as f:
                f.seek(pos)
                data = f.read()
        except OSError:
            return
        end = len(data) if final else data.rfind(b"\n") + 1  # a line still being written waits for the next look
        if not end:
            return
        run["pos"] = pos + end
        text = data[:end].decode("utf-8", "replace")
        if logged_out(_said(text)):
            run["auth"] = True
        got = readings(text)
        for u, _ in got:
            run.setdefault("u0", u)
            run["u1"] = u
        self._usage(run["agent"], got)

    def _usage(self, name, got):
        """Store an agent's newest reading; a window marked rejected limits it until its exact reset; a cost
        waiting for the reading after its ticket (see _learn) is learned from it."""
        if not got:
            return
        now = self.hub.now()
        with self.hub._lock:
            inst = self.hub._data["installed"].get(name)
            if inst is None:
                return
            u, rejected = got[-1]
            inst["usage"] = {**u, "at": now}
            if rejected and rejected > now:
                inst["limited_until"] = rejected
            wait = inst.pop("pending", None)
            if wait and _same_window(wait["u0"], u):
                self._add_cost(inst, wait["tier"], u["five_hour"] - wait["u0"]["five_hour"])
            self.hub._save()

    @staticmethod
    def _add_cost(inst, tier, cost):
        """One more measured cost into the agent's running average for `tier` (under the hub's lock)."""
        c = inst.setdefault("costs", {}).get(tier) or {"avg": 0.0, "n": 0}
        n = c["n"] + 1
        inst["costs"][tier] = {"avg": round((c["avg"] * c["n"] + max(0.0, cost)) / n, 4), "n": n}

    def _learn(self, run, model):
        """A finished worker's cost: the rise of its agent's 5-hour use from its first reading to its last, when
        both are in one window and no other worker of that agent overlapped it. With one reading only, the
        next reading of the agent (the probe that follows) closes it."""
        u0, u1 = run.get("u0"), run.get("u1")
        if not run.get("alone") or u0 is None:
            return
        with self.hub._lock:
            inst = self.hub._data["installed"].get(run["agent"])
            if inst is None:
                return
            if u1 is u0:
                inst["pending"] = {"tier": _tier(model), "u0": u0}
            elif _same_window(u0, u1):
                self._add_cost(inst, _tier(model), u1["five_hour"] - u0["five_hour"])
            self.hub._save()

    def _watch(self):
        """Each running worker's new readings, and the brake: past BRAKE_5H its worker is told once to wrap up.
        The message reaches it only through its own hooks; without them it is never delivered."""
        now = self.hub.now()
        for run in list(self.procs.values()):
            self._consume(run)
        with self.hub._lock:
            usage = {n: e.get("usage") for n, e in self.hub._data["installed"].items()}
        for key, run in list(self.procs.items()):
            u = usage.get(run["agent"])
            if run.get("braked") or not u or (u.get("five_hour_resets") or 0) <= now or u["five_hour"] < BRAKE_5H:
                continue
            try:
                self.hub.send(key, BRAKE_JOB_TEXT if key.startswith("job:") else BRAKE_TEXT)
                run["braked"] = True
            except ValueError:
                pass  # its session has not reported yet: tried again next tick

    def _probe(self):
        """A one-line Haiku call for each Claude agent of the pool (or named by an item) that could take a queued
        item, runs nothing, and has no reading newer than USAGE_STALE; at most one per agent per USAGE_STALE.
        It is also how a signed-out agent is found signed in again."""
        now = self.hub.now()
        with self.hub._lock:
            q = self.hub._data["queue"]
            if q["paused"]:
                return
            queued = [i for i in q["items"] if i["state"] == "queued" and (i.get("not_before") or 0) <= now]
            names = dict.fromkeys(n for i in queued for n in ([i["agent"]] if i.get("agent") else pool(q)))
            busy = {i.get("runner") for i in q["items"] if i["state"] == "running"}
            todo = []
            for n in names:
                inst = self.hub._data["installed"].get(n)
                if inst is None or inst.get("kind") != "claude" or n in busy or (inst.get("limited_until") or 0) > now:
                    continue
                u = inst.get("usage")
                fresh = u and now - u.get("at", 0) < USAGE_STALE and not inst.get("pending")
                if fresh and inst.get("login") != "expired" or now - (inst.get("probed") or 0) < USAGE_STALE:
                    continue
                inst["probed"] = now
                todo.append((n, dict(inst)))
            if todo:
                self.hub._save()
        if not todo:
            return
        if not self.probe_async:
            self._probe_run(todo)
            return
        # off the tick: a slow probe never holds up starts, time limits or the brake (M6)
        th = threading.Thread(target=self._probe_run, args=(todo,), daemon=True)
        self.probing = [x for x in self.probing if x.is_alive()] + [th]
        th.start()

    def _probe_run(self, todo):
        for n, inst in todo:
            try:
                text = self.probe(inst, str(self.hub.home / "probe"))
                got = readings(text)
                if logged_out(_said(text)):
                    self._signed_out(n)
                elif got:
                    self._signed_in(n)
                self._usage(n, got)
            except Exception as e:  # a probe never takes the hub down
                if not self.stopped:
                    print("sb hub probe {}: {}: {}".format(n, type(e).__name__, e), file=sys.stderr, flush=True)

    def _signed_out(self, name):
        """Mark the agent signed out and, once per expiry, ask the owner to sign it in."""
        with self.hub._lock:
            inst = self.hub._data["installed"].get(name)
            if inst is None or inst.get("login") == "expired":
                return
            inst["login"] = "expired"
            self.hub._save()
        text = "Sign in to {}: run `CLAUDE_CONFIG_DIR={} claude`, type /login".format(name, inst.get("dir") or "~/.claude")
        self.hub.report({"agent": "sign-in:" + name, "name": "Sign in to " + name, "role": "orchestrator",
                         "state": "needs you", "note": text})
        notify("sb hub: needs you", text)

    def _signed_in(self, name):
        with self.hub._lock:
            inst = self.hub._data["installed"].get(name)
            if inst is None or inst.get("login") != "expired":
                return
            inst["login"] = None
            self.hub._remove("sign-in:" + name)
            self.hub._save()

    # ---- state, always under the hub's lock ----

    def _update(self, key, front=False, drop=(), **fields):
        """Change one item; `front` puts it first among the queued ones; the fields in `drop` are removed."""
        with self.hub._lock:
            q = self.hub._data["queue"]
            item = next((i for i in q["items"] if i["key"] == key), None)
            if item is None:
                return
            for f in drop:
                item.pop(f, None)
            item.update(fields)
            self.hub._end_rows(key)
            if front:
                q["items"].remove(item)
                at = next((n for n, i in enumerate(q["items"]) if i["state"] == "queued"), len(q["items"]))
                q["items"].insert(at, item)
            q["version"] += 1
            self.hub._save()

    def _add_spend(self, item, run, res=None, over=False):
        """Add this try's cost (worker minutes, check minutes, tokens from its part of the log) to the item's
        `spend`; it goes on the ticket's note when the item ends (_note_spend)."""
        now = self.hub.now()
        began = item.get("started")
        got = log_spend(run.get("log"), run.get("start") or 0) if run.get("log") else None
        with self.hub._lock:
            cur = next((i for i in self.hub._data["queue"]["items"] if i["key"] == item["key"]), None)
            prev = dict((cur or {}).get("spend") or {})
        spend = {"run_minutes": prev.get("run_minutes", 0) + (max(0, now - began) / 60 if began else 0),
                 "check_minutes": prev.get("check_minutes", 0) + sum(c.get("secs") or 0 for c in (res or {}).get("checks") or []) / 60,
                 "tries": prev.get("tries", 0) + 1, "model": item.get("model") or (run.get("t") or {}).get("tier") or "sonnet",
                 "account": run.get("agent") or item.get("runner")}
        for k in ("tokens_in", "tokens_out", "cache_read", "cost_usd"):
            if prev.get(k) is not None or got:
                spend[k] = (prev.get(k) or 0) + (got[k] if got else 0)
        self._update(item["key"], spend=spend)

    def _note_spend(self, key, state):
        """The item's `spend` on its ticket's note (sbmap spend adds to what the note has), then cleared."""
        with self.hub._lock:
            item = next((dict(i) for i in self.hub._data["queue"]["items"] if i["key"] == key), None)
        spend = (item or {}).get("spend")
        if item is None or item["kind"] != "ticket" or not spend:
            return
        try:
            m, _, num = key.rpartition("#")
            args = ["{}={}".format(k, round(spend[k], 4) if isinstance(spend[k], float) else spend[k])
                    for k in ("run_minutes", "check_minutes", "tries", "tokens_in", "tokens_out", "cache_read", "cost_usd")
                    if spend.get(k) is not None]
            args += ["{}={}".format(k, v) for k, v in (("model", spend.get("model")), ("account", spend.get("account")),
                                                      ("night", item.get("night")), ("outcome", state)) if v]
            rc, out, err = self.runner.sbmap("spend", m, num, *args)
            if rc != 0:
                print("sb hub queue: spend for {}: {}".format(key, err or out), file=sys.stderr, flush=True)
                return
        except Exception as e:  # the note is a record: never blocks the item's end
            print("sb hub queue: spend for {}: {}".format(key, e), file=sys.stderr, flush=True)
            return
        self._update(key, drop=("spend",))

    def _end(self, key, state, **fields):
        if state in ("done", "failed"):
            fields.setdefault("media", self.hub.media_of(key))
        self._note_spend(key, state)
        self._update(key, state=state, ended=self.hub.now(), pid=None, pid_start=None, **fields)

    def _row(self, key):
        return self.runner.row(key)

    def _release(self, key):
        self.runner.release(key)

    # ---- workers that ended, ran too long, or were lost with a restart ----

    def _reap(self):
        with self.hub._lock:
            running = [dict(i) for i in self.hub._data["queue"]["items"]
                       if i["state"] == "running"]
        for item in running:
            if item.get("stop_asked"):  # the owner's Stop, before a restart's recovery could queue it again
                self._stop_asked(item)
                continue
            run = self.procs.get(item["key"])
            if run is None:
                self._recover(item)
                continue
            ended = run["p"].poll() is not None
            over = not ended and self.hub.now() - (item.get("started") or self.hub.now()) > self.limit
            if not (ended or over):
                continue
            if not run.get("adopted") or over and run["p"].sure:  # an ended adopted pid may be reused: left alone
                _kill_group(run["p"], grace=3 if over else 0)  # also whatever it left running
            del self.procs[item["key"]]
            self._consume(run, final=True)
            try:
                (self._finish_job if item["kind"] == "job" else self._finish)(item, run, over)
            except Exception as e:  # the item still ends, never resolved
                why = "the hub could not check it: {}: {}".format(type(e).__name__, e)
                if item["kind"] == "job" or run.get("t") is None:
                    self._end(item["key"], "failed", note=why)
                else:
                    self._apply(item, self.runner.fail(item, run, why, None))
            with self.hub._lock:
                now_item = next((i for i in self.hub._data["queue"]["items"] if i["key"] == item["key"]), {})
            # only finished work says what an item costs: a worker whose checks passed (it landed, or waits to) counts
            if now_item.get("state") in ("done", "landed", "unclean"):
                self._learn(run, item.get("model") or "sonnet")

    def _stop_asked(self, item):
        """The owner's Stop (Hub.queue_stop): kill the worker's whole process group, its helpers included (one an
        earlier hub started too, known by the pid and start time on the item), then end the item as stopped by you:
        never tried again, never sent to Opus, not a usage stop and not a failure. A ticket's claim is released and
        a comment names the reason and where the work is; that work is left exactly where it is."""
        key, asked = item["key"], item["stop_asked"]
        run = self.procs.pop(key, None)
        if run is None and item.get("pid"):  # this hub did not start it (it restarted): the item knows the worker
            pid, started = item["pid"], item.get("pid_start")
            sure = bool(started) and _proc_start(pid) == started
            run = {"p": _Adopted(pid, started if sure else None), "adopted": True, "agent": item.get("runner"),
                   "log": item.get("log"), "start": item.get("log_start") or 0}
        left = False
        if run is not None:
            if getattr(run["p"], "sure", True):  # a pid ps could not tie to the worker is never killed
                _kill_group(run["p"], grace=3)
                left = run["p"].poll() is None
            else:
                left = _pid_exists(run["p"].pid)
            if run.get("log") and run.get("agent"):
                try:
                    self._consume(run, final=True)  # its usage readings still pace its account
                except Exception:
                    pass
        if run is not None and run.get("log"):
            self._add_spend(item, run)
        if item.get("integrate"):
            self._unstage(item, "stopped by you during its Unity stage", None, requeue=False)
        where = self._work_left(item)
        note = "stopped by you: " + asked["reason"]
        if left:
            note += "; its process {} could not be confirmed as the worker, so it was left alone".format(
                run["p"].pid)
        if item["kind"] == "ticket":
            num = "{:03d}".format(int(key.rsplit("#", 1)[1]))
            self.sbmap("comment", sbqueue.map_of(key), num, "--text",
                       "Stopped by you from the hub page: {}. {}".format(asked["reason"].rstrip("."), where))
            self._release(key)
        self._end(key, "skipped", note=note + ". " + where)

    def _work_left(self, item):
        """Where a stopped worker's work is, in words: its branch and worktree, else the checkout's changed files."""
        if item.get("tree"):
            return "Its work stays on branch {} in the worktree {}.".format(item.get("branch"), item["tree"])
        repo = item.get("repo")
        if not repo:
            return "It had no checkout yet."
        names = []
        for args in (("diff", "--name-only", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
            rc, out, _ = _git_run(repo, *args)
            names += [n for n in out.splitlines() if n and n not in names] if rc == 0 else []
        made = ""
        if item.get("base_sha"):
            rc, out, _ = _git_run(repo, "rev-list", "--count", "{}..HEAD".format(item["base_sha"]))
            if rc == 0 and out.strip() not in ("", "0"):
                made = " Commits since it started: {} (on the checkout's branch).".format(out.strip())
        files = ("Files left changed in the checkout {}: {}.".format(repo, ", ".join(names)) if names else
                 "No file is left changed in the checkout {}.".format(repo))
        return files + made

    def _job_stopped(self, item, run):
        """True when a job's own output shows a logout or a usage limit: its agent waits and the job goes back to
        the front (after STOPS_MAX stops it fails)."""
        stop = stop_of(run, self.hub.now())
        if stop is None:
            return False
        run["stopped"] = True
        stops = (item.get("stops") or 0) + 1
        if stops >= STOPS_MAX:
            self._agent_stopped(stop)
            self._end(item["key"], "failed", note="stopped {} times at a usage limit or a logout (the last on {}, {}); "
                      "not tried again".format(stops, run["agent"], STOP_WHY[stop["kind"]]))
            return True
        self._apply(item, {"state": "stopped", "stop": stop, "stops": stops, "log": run["log"],
                           "note": "{} stopped {}{}; queued again at the front".format(
                               run["agent"], STOP_WHY[stop["kind"]],
                               "" if stop["kind"] == "auth" else " (until {})".format(_hm(stop["until"])))})
        return True

    def _agent_stopped(self, stop):
        """The agent a worker stopped on waits: limited until the reset, or signed out until the owner signs in."""
        if stop.get("until") is not None:
            with self.hub._lock:
                inst = self.hub._data["installed"].get(stop["agent"])
                if inst is not None:
                    inst["limited_until"] = stop["until"]
                self.hub._save()
        if stop["kind"] == "auth":
            self._signed_out(stop["agent"])

    def _apply(self, item, res, judged=True):
        """Put a TicketRun result (or a job's stop) on the queue: the item ends, or goes back to the front of the
        queue (a retry on another model, or a stop at a limit or a logout); three failures of one class in a row
        pause the queue."""
        key, state = item["key"], res["state"]
        if res.get("stop"):
            self._agent_stopped(res["stop"])
        if state == "stopped":  # a stop keeps its session to go on with; a resume that failed (`fresh`) drops it
            stop = res.get("stop")
            more = {"resume": {"agent": stop["agent"], "log": res["log"], "why": STOP_WHY[stop["kind"]]}} if stop else {}
            self._update(key, front=True, drop=("session", "session_dir") if res.get("fresh") else (), state="queued",
                         pid=None, pid_start=None, started=None, stops=res["stops"], note=res["note"], **more)
            return
        if state == "integrate":
            self._integrate(item, res)
            return
        if state == "recheck" and UNITY_WAIT in (res.get("note") or ""):  # another ticket holds the Editor
            self._update(key, state="recheck", ended=None, commit=res["commit"], pid=None, pid_start=None, started=None,
                         recheck_at=self.hub.now() + UNITY_POLL, checked=None,
                         note=res["note"] + "; it lands when the Editor is free, with no try spent")
            return
        if state == "landed":  # the checks passed and the work landed: its map's second pass judges it (_reviews)
            self._update(key, state="landed", ended=None, landed_at=self.hub.now(), commit=res["commit"],
                         checked=res["checked"], pid=None,
                         pid_start=None, rechecks=None, recheck_at=None, verdict=None, review=None, note=res["note"])
            return
        if state == "unclean":  # its work waits on its branch until the checkout's copies of its files are saved
            first = item.get("state") != "unclean"
            self._update(key, state="unclean", ended=None, commit=res["commit"], blocking=res["blocking"], pid=None,
                         pid_start=None, started=None, rechecks=None, recheck_at=None, checked=None, note=res["note"])
            if first:  # one alert, not one per loop pass
                threading.Thread(target=notify, daemon=True, args=("sb hub: needs you", "{}: waiting for a clean "
                                 "checkout: save or clear {}".format(key, ", ".join(res["blocking"])))).start()
            return
        if state == "recheck" and HELD in (res.get("note") or ""):  # not its try: it waits for a green build
            self._update(key, state="recheck", ended=None, commit=res["commit"], pid=None, pid_start=None, started=None,
                         rechecks=None, recheck_at=None, checked=None, held=item.get("repo"),
                         note=res["note"] + "; it lands once the build is green again, with no try spent")
            return
        if state == "recheck":
            again = item.get("state") == "recheck" or item.get("state") == "review" and item.get("rechecks") is not None
            n = (item.get("rechecks") or 0) + 1 if again else 0
            more = n < RECHECKS_MAX
            what = "the review runs" if res.get("checked") is not None else "the checks run"
            self._update(key, state="recheck", ended=None, commit=res["commit"], pid=None, pid_start=None, started=None,
                         rechecks=n, recheck_at=self.hub.now() + RECHECK_EVERY if more else None,
                         checked=res.get("checked"), review=res.get("review"), verdict=None,
                         note=res["note"] + ("; {} again at {}".format(what, _hm(self.hub.now() + RECHECK_EVERY))
                                             if more else
                                             "; rechecked {} times, press Recheck to try again".format(RECHECKS_MAX)))
            return
        if state == "redo":  # the review's one more try: first in the queue, on the model it had, from the newest
            # commit (its first try's included), told the findings; a stop's resume and an opus retry's reason go
            fails = list(item.get("fails") or []) + [{"model": item.get("model") or "sonnet",
                                                       "why": firstline(res["note"])[:300], "commit": res["commit"]}]
            self._update(key, front=True, drop=("resume", "retry"), state="queued", tries=len(fails), fails=fails,
                         redo=res["redo"], commit=res["commit"], verdict=res["verdict"], review=res["review"],
                         first_base=None, checked=None, rechecks=None, recheck_at=None, pid=None, pid_start=None,
                         started=None, ended=None, note=res["note"])
            return
        if state == "retry":  # its next try: first in the queue, from its kept work (its worktree, or the checkout)
            fails = res["retry"]["fails"]
            self._update(key, front=True, state="queued", tries=len(fails), fails=fails, model=res["retry"]["model"],
                         retry=res["retry"]["reason"], commit=res["commit"], pid=None, pid_start=None, started=None,
                         rechecks=None, recheck_at=None, note=res["note"])
            return
        # a worker that never started leaves the item's commit (an earlier try's) as it was
        fields = {"commit": res["commit"]} if judged or res["commit"] else {}
        if res.get("media"):
            fields["media"] = res["media"]
        if res.get("fails"):
            fields.update(fails=res["fails"], tries=len(res["fails"]))
        if res.get("verdict") or res.get("review"):
            fields.update(verdict=res.get("verdict"), review=res.get("review"), checked=None)
        self._end(key, state, note=res["note"], **fields)
        if state == "done":
            self.streak = (None, 0)
        elif state == "failed" and judged:
            self._count_failure(res["note"])

    def _count_failure(self, reason):
        cls = _fail_class(reason)
        n = self.streak[1] + 1 if cls is not None and self.streak[0] == cls else 1
        self.streak = (cls, n if cls is not None else 0)
        if cls is not None and n >= 3:
            with self.hub._lock:
                q = self.hub._data["queue"]
                q["paused"] = True
                q["note"] = "paused: three tickets in a row failed with {}".format(cls)
                q["version"] += 1
                self.hub._save()
            self.streak = (None, 0)

    def _backed_out(self, c):
        """A landed ticket whose files broke the build once a later ticket landed on top: its landing was reverted
        (TicketRun._blame_earlier). It goes back to the front of the queue as its next try, its work replayed on its
        branch on top of the revert and its worker told why; one that was no longer waiting for its review is left
        as it is and the owner is told."""
        key, repo = c["key"], c["repo"]
        with self.hub._lock:
            item = next((dict(i) for i in self.hub._data["queue"]["items"] if i["key"] == key), None)
        why = ("after {} landed on top, the build did not compile in your files, so the hub backed your landing "
               "out (revert {}):\n{}").format(c["after"], c["revert"][:9], "\n".join(c["errors"][:5]))
        note = "backed out: its files broke the build ({}); queued again".format(", ".join(c["files"][:3]))
        if item is None or item.get("state") != "landed" or item.get("kind") != "ticket":
            threading.Thread(target=notify, daemon=True, args=("sb hub: needs you", "{}: backed out, its files broke "
                             "the build; it was {}, so it is not queued again".format(
                                 key, item.get("state") if item else "not in the queue"))).start()
            return
        fails = list(item.get("fails") or []) + [{"model": item.get("model") or "sonnet", "why": firstline(why)[:300],
                                                   "commit": c["sha"]}]
        if len(fails) >= TRIES_MAX:
            self._end(key, "failed", note="{}\nIt waits for you after {} tries.".format(why, len(fails)), fails=fails,
                      tries=len(fails))
            return
        tree, branch = item.get("tree"), item.get("branch")
        if not tree or not branch:
            m = re.fullmatch(r"(.+)#(\d+)", key)
            tree, branch = tree_of(self.hub.home, repo, m.group(1), m.group(2))
        err = make_tree(repo, tree, branch, c["sha"]) or replay_tree(tree, c["before"], c["revert"])
        self._update(key, front=True, state="queued", tries=len(fails), fails=fails, retry=why, commit=c["sha"],
                     tree=None if err else tree, branch=None if err else branch, first_base=c["revert"],
                     landed_at=None, verdict=None, review=None, checked=None, pid=None, pid_start=None,
                     started=None, ended=None, note=note + ("" if not err else "; its work could not be replayed on "
                                                             "a branch: " + firstline(err)))

    def _unland(self):
        """A hub that stopped while a landing held a repo's Unity lock (its work fast-forwarded into the checkout,
        its after-landing checks not yet passed) left it half landed: the landing is backed out by a revert, its
        work replayed on its branch, the lock let go, and the ticket lands again at once as a recheck (its worker
        does not run again). Landings run inside the tick, so at the first tick none of this hub's is under way."""
        self.unlanded = True
        with self.hub._lock:
            held = [(k, dict(v)) for k, v in self.hub._data["locks"].items() if v.get("landing")]
        for k, v in held:
            landing = v["landing"]
            with self.hub._lock:
                it = next((dict(i) for i in self.hub._data["queue"]["items"] if i["key"] == landing["key"]), None)
            if it and it.get("integrate"):
                if it.get("pid") and it.get("pid_start") and _proc_start(it["pid"]) == it["pid_start"]:
                    continue  # its integrator still runs: _recover adopts it, and it is judged when it ends
                self._unstage(it, "the hub stopped during its Unity stage", landing.get("tree"))
                continue
            err = undo_landing(landing, "the hub stopped before its after-landing checks passed")
            if err:  # the lock stays, so nothing else lands on top until the owner looks
                print("sb hub: could not undo the landing of {}: {}".format(landing["key"], err), file=sys.stderr,
                      flush=True)
                continue
            self.hub.unlock(k, v["by"])
            with self.hub._lock:
                item = next((dict(i) for i in self.hub._data["queue"]["items"] if i["key"] == landing["key"]), None)
            if item and item["state"] in ("running", "recheck"):
                self._update(item["key"], state="recheck", recheck_at=self.hub.now(), pid=None, pid_start=None,
                             note="the hub stopped while it landed: backed out, it lands again")

    def _integrate(self, item, res):
        """A Unity project's ticket landed in the main folder and holds the repo's Unity lock: its integrator starts
        there (templates/integrate.md) and the item runs until it ends; _finish judges it (TicketRun.integrated).
        One whose integrator cannot start (or whose agent is not Claude) is judged at once, on its checks alone."""
        key, t = item["key"], res["t"]
        num, folder = int(t["num"]), Path(res["run"])
        stage = {**res["integrate"], "folder": str(folder), "log": str(folder / "{}-integrate.log".format(num))}
        with self.hub._lock:
            name = item.get("runner")
            inst = dict(self.hub._data["installed"].get(name) or {})
        run = {"t": t, "agent": name, "inst": inst, "base": res["base"], "first_base": item.get("first_base"),
               "log": stage["log"], "start": 0, "folder": str(folder), "tree": stage["tree"],
               "branch": stage["branch"], "integrate": stage}
        repo, nnn = stage["repo"], "{:03d}".format(num)
        try:
            if inst.get("kind") == "agy" or not inst:
                raise OSError("its agent cannot run the integrator")
            landed = ("Its work landed earlier and is in this folder. The Opus review judged it short: read its findings "
                      "in `{}` and play each one it marks not met or not played. Fix what is really broken, or "
                      "measure that it works.".format(res.get("review") or "(no review file kept)")
                      if stage.get("only") else "Its work has just landed in this folder as `{}..{}`.".format(
                          stage["before"][:12], stage["sha"][:12]))
            brief = INTEGRATE.read_text(encoding="utf-8").format(
                ticket="{}/{}".format(t["map"], nnn), repo_name=Path(repo).name, repo=repo, title=t["title"],
                landed=landed, lock=unity_lock(repo),
                sbmap="python3 " + shlex.quote(str(SBMAP)), map=t["map"], num3=nnn,
                done_when=t.get("done_when") or "(none written)", minutes=INTEGRATE_MINUTES,
                report=res.get("report") or folder / "{}.md".format(num), out=folder / "{}-integrate.md".format(num))
            env = {"SB_HUB_AGENT": key, "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.runner.port),
                   "SB_HUB_RUN": str(folder), "SB_HUB_UNITY": "integrator"}
            if self.runner.stopping():
                raise OSError("the hub is stopping")
            run["p"] = self.hub.launcher(inst, brief, repo, INTEGRATE_MODEL, env, stage["log"])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
            print("sb hub queue: {}: no integrator ({}); judged on its checks".format(key, e), file=sys.stderr,
                  flush=True)
            got = self.runner.integrated({**item, "integrate": stage}, run, False)
            self._apply(item, got)
            return
        self._track(key, run)
        self._update(key, state="running", integrate=stage, commit=res["commit"], started=self.hub.now(),
                     pid=run["p"].pid, pid_start=_proc_start(run["p"].pid),
                     note="in its Unity stage: the integrator builds and plays it on the main folder")

    def _pass(self, item, t, name):
        """A Unity pass (Hub.queue_integrate): no worker. The integrator takes the repo's Unity lock on the checkout
        as it stands and plays what the ticket's review found short; it is judged as any Unity stage
        (TicketRun.integrated), except that a pass that fails goes back to the owner. With the Editor busy it
        waits in the queue."""
        key, repo, nnn = item["key"], t["repo"], "{:03d}".format(int(t["num"]))
        head = _git(repo, "rev-parse", "HEAD")
        landing = {"key": key, "repo": str(repo), "before": head, "sha": head, "tree": None, "branch": "",
                   "only": True}
        got = self.hub.lock(unity_lock(repo), _landing_by(landing), landing=landing) if head else {
            "ok": False, "held_by": "nobody (the checkout has no commit)"}
        if not got.get("ok"):
            self._update(key, state="queued", started=None, note="{}: {} holds the Editor".format(
                UNITY_WAIT, got.get("held_by")))
            return
        drop_unsaved_scenes(repo)
        rc, out, err = self.runner.sbmap("claim", t["map"], nnn, "--by", "hub " + name)
        if rc != 0:
            self.hub.unlock(unity_lock(repo), _landing_by(landing))
            self._end(key, "skipped", note="could not claim it: " + (err or out))
            return
        board = self._board(t["map"])
        folder = Path(board).parent if board else Path(item.get("run") or self.hub.home)
        report = folder / "{}.md".format(int(t["num"]))
        self._integrate(item, {"t": t, "run": str(folder), "integrate": {**landing, "dirty": dirty_files(repo)},
                               "base": head, "commit": item.get("commit") or head, "review": item.get("review"),
                               "report": str(report) if report.is_file() else None})

    def _unstage(self, item, why, tree=None, requeue=True):
        """Back a Unity stage out whole (the landing and the integrator's commits after it) and let go of the Unity
        lock; with `requeue`, it lands again as a recheck (its worker does not run again)."""
        stage = item["integrate"]
        repo = stage["repo"]
        tidy_stage(repo, stage.get("dirty") or [], Path(stage.get("folder") or self.hub.home) /
                   "{}-unity-leftovers.patch".format(item["key"].rsplit("#", 1)[-1]))
        landing = {**stage, "tree": tree or stage.get("tree"), "own": stage_commits(repo, stage["sha"], stage["key"])}
        err = undo_landing(landing, why)
        if err:  # the lock stays, so nothing else lands on top until the owner looks
            print("sb hub: could not undo the Unity stage of {}: {}".format(item["key"], err), file=sys.stderr,
                  flush=True)
            return
        self.hub.unlock(unity_lock(repo), _landing_by(landing))
        if requeue and stage.get("only") and item["state"] == "running":  # a Unity pass starts over
            self._update(item["key"], drop=("integrate",), state="queued", pid=None, pid_start=None, started=None,
                         note=why + ": its fixes backed out, the pass runs again")
            return
        self._update(item["key"], drop=("integrate", "integrate_only"))
        if requeue and item["state"] in ("running", "recheck"):
            self._update(item["key"], state="recheck", recheck_at=self.hub.now(), pid=None, pid_start=None,
                         note=why + ": backed out, it lands again")

    def _recover(self, item):
        """A `running` item this hub did not start (it restarted). When its worker still runs, it is waited for
        and judged when it ends, never started twice; otherwise its claim is released and it is queued again.
        The same worker is known by its pid and start time; when ps cannot tell, a live pid is waited for too,
        but never killed (it might be another process by now)."""
        pid, started = item.get("pid"), item.get("pid_start")
        now_start = _proc_start(pid) if pid else None
        sure = bool(started) and now_start == started
        if pid and (sure or (not started or now_start is None) and _pid_exists(pid)):
            with self.hub._lock:
                inst = dict(self.hub._data["installed"].get(item.get("runner")) or {})
            self.procs[item["key"]] = {"p": _Adopted(pid, started if sure else None), "t": None, "adopted": True,
                                       "agent": item.get("runner"), "inst": inst, "base": item.get("base_sha"),
                                       "first_base": item.get("first_base"),
                                       "log": (item.get("integrate") or {}).get("log") or item.get("log"),
                                       "start": 0 if item.get("integrate") else item.get("log_start") or 0, "alone": False,
                                       "tree": item.get("tree"), "branch": item.get("branch"), "folder": item.get("run")}
            self._update(item["key"], note="running on {}, started before the hub restarted".format(item.get("runner")))
            return
        if item["kind"] == "ticket":
            self._release(item["key"])
        # its work so far (committed or not, in its worktree or the checkout) is kept: the next try goes on from it
        resume = {"agent": item.get("runner"), "log": item.get("log"), "why": "when the hub stopped"} \
            if item["kind"] == "ticket" and item.get("base_sha") else item.get("resume")
        self._update(item["key"], state="queued", pid=None, pid_start=None, started=None, resume=resume,
                     note="queued again: the hub stopped while it ran")

    def _finish(self, item, run, over):
        key = item["key"]
        if run.get("t") is None:  # a worker started before the hub restarted: its ticket is read now
            found, row = self._row(key)
            if row is None or not run.get("base"):
                self._end(key, "skipped" if found else "failed", note="its worker ended after a hub restart, but "
                          + ("the ticket is no longer open" if found else "the tickets could not be read to check it"))
                return
            run["t"] = row
        if item.get("integrate"):  # its Unity stage ended: judged on the integrator's verdict and the checks
            res = self.runner.integrated(item, run, over)
            self._update(key, drop=("integrate", "integrate_only"))
        else:
            res = self.runner.finish(item, run, over)
        self._add_spend(item, run, res, over)
        if not over:
            self._update(key, checks=res["checks"])
        self._apply(item, res)
        if res["state"] == "done" and res["commit"] and run.get("t"):
            self.runner.rebuild_after(run["t"]["repo"], run.get("landed_on") or run.get("base"), res["commit"])

    def _rechecks(self):
        """Each `recheck` item that is due: only its checks run again, on the commit its worker made."""
        now = self.hub.now()
        with self.hub._lock:
            due = [dict(i) for i in self.hub._data["queue"]["items"]
                   if i["kind"] == "ticket" and i["state"] == "recheck" and i.get("recheck_at") is not None
                   and i["recheck_at"] <= now]
        for item in due:
            try:
                self._recheck(item)
            except Exception as e:  # tried again at the next due time, never failed for it
                self._update(item["key"], recheck_at=self.hub.now() + RECHECK_EVERY,
                             note="the recheck did not run: {}: {}".format(type(e).__name__, e))

    def _held_builds(self):
        """A repo whose build is broken outside any ticket's files holds its tickets. It gets one fix run (a job in
        its main folder, templates/fix-build.md) per break. The check that failed runs again on the checkout's newest
        commit when that moved, when the fix run ended, or every HELD_EVERY; once it passes the build is green and
        every ticket it held lands again at once (a recheck, its worker not run), with no try spent. A fix run that
        ended without mending it asks the owner once."""
        now = self.hub.now()
        with self.hub._lock:
            builds = {r: json.loads(json.dumps(b)) for r, b in (self.hub._data["queue"].get("builds") or {}).items()
                      if b.get("held")}
        for repo, b in builds.items():
            if "fix" not in b:
                self._start_fix(repo, b)
                continue  # its check runs again once the fix run ended (or the checkout moved)
            h, fix = b["held"], b["fix"]
            head = _git(repo, "rev-parse", "HEAD")
            if not head or head == h.get("head") and now < (h.get("at") or 0) + HELD_EVERY:
                continue
            if not fix.get("ended") and head == h.get("head"):
                continue  # the fix run is still at it: its own commit is what the next check judges
            ok = self.runner.check_main(repo, h, head)
            if ok:
                self.runner.build_mark(repo, green=head)
            elif ok is False and fix.get("ended") and not fix.get("asked"):
                self._ask_fix(repo, b)
        with self.hub._lock:
            builds = self.hub._data["queue"].get("builds") or {}
            free = [i["key"] for i in self.hub._data["queue"]["items"]
                    if i.get("held") and not (builds.get(i["held"]) or {}).get("held")]
        for key in free:
            self._update(key, held=None, recheck_at=now, note="the build is green again: it lands now")

    def _start_fix(self, repo, b):
        """Queue the one fix run of this break, first in the queue, briefed with the check and its errors."""
        h = b["held"]
        name = Path(repo).name
        try:
            template = FIX_BUILD.read_text(encoding="utf-8")
        except OSError as e:
            print("sb hub queue: fix-build template: {}".format(e), file=sys.stderr, flush=True)
            return
        prompt = template
        for k, v in (("{repo_name}", name), ("{repo}", repo), ("{cmd}", h["cmd"]), ("{head}", h["head"][:12]),
                     ("{since}", b.get("errors_by") or "a landing"), ("{files}", ", ".join(h.get("files") or [])),
                     ("{errors}", "\n".join(b.get("errors") or []) or "(none recorded)"), ("{lock}", unity_lock(repo))):
            prompt = prompt.replace(k, v)
        try:
            key = self.hub._queue_job(repo, repo, prompt, None, FIX_MODEL, "fix-build-" + name)["key"]
        except ValueError as e:  # the same break was handed to a fix run less than a day ago
            key = None
            print("sb hub queue: fix run for {}: {}".format(name, e), file=sys.stderr, flush=True)
        with self.hub._lock:
            got = (self.hub._data["queue"].get("builds") or {}).get(repo)
            if got is not None and got.get("held"):
                got["fix"] = {"key": key, "ended": key is None}
                self.hub._data["queue"]["version"] += 1
                self.hub._save()
        if key:
            self._update(key, front=True, fix_build=repo, title="mend {}'s build".format(name))

    def _fix_ended(self, item, run, result, ok):
        """A fix run ended: its cost goes on its run board, and the check runs again at the next pass."""
        repo = item["fix_build"]
        spend = log_spend(run.get("log"), run.get("start") or 0) or {}
        minutes = max(0, self.hub.now() - (item.get("started") or self.hub.now())) / 60
        board = Path(run["log"]).parent / (Path(run["log"]).parent.name + ".md")
        try:
            said = firstline(Path(result).read_text(encoding="utf-8")) if result else ""
            with open(board, "a", encoding="utf-8") as f:
                f.write("\n- {} fix run for {}'s build {}: {}. Cost: ${:.2f}, {:.0f} min ({}).\n".format(
                    _hm(self.hub.now()), Path(repo).name, "ended" if ok else "failed",
                    said.rstrip(".") or "no word from it",
                    spend.get("cost_usd") or 0, minutes, item.get("model") or FIX_MODEL))
        except OSError as e:
            print("sb hub queue: fix run board: {}".format(e), file=sys.stderr, flush=True)
        with self.hub._lock:
            b = (self.hub._data["queue"].get("builds") or {}).get(repo)
            if b and b.get("fix", {}).get("key") == item["key"]:
                b["fix"]["ended"] = True
                if b.get("held"):
                    b["held"]["at"] = 0  # judged again at the next pass, whatever the checkout's commit
                self.hub._data["queue"]["version"] += 1
                self.hub._save()

    def _ask_fix(self, repo, b):
        """The fix run could not mend it: the owner is asked once, and the tickets keep waiting."""
        name, h = Path(repo).name, b["held"]
        q = ("{}'s build is broken in {} and the fix run could not mend it. Its tickets wait, with no try spent, "
             "until the check passes on the main folder: `{}`. The fix run's report is on its run board.").format(
            name, ", ".join(Path(f).name for f in h.get("files") or []) or "files the hub could not name", h["cmd"])
        got = self.hub.ask(b["fix"].get("key") or "sb-hub", q, ["I'll mend it by hand", "Leave it until morning"],
                           "Leave it until morning", FIX_ASK_WAIT)
        with self.hub._lock:
            cur = (self.hub._data["queue"].get("builds") or {}).get(repo)
            if cur and cur.get("fix"):
                cur["fix"]["asked"] = got["id"]
                self.hub._data["queue"]["version"] += 1
                self.hub._save()
        threading.Thread(target=notify, daemon=True, args=("sb hub: needs you", "{}: the build is broken and the "
                         "fix run could not mend it".format(name))).start()

    def _unclean(self):
        """Each item waiting for a clean checkout whose blocking files are now saved or cleared (one git status on
        them): its kept commit is rebased onto the checkout's newest commit, checked and landed, as a recheck is.
        A rebase that conflicts fails it with its branch kept; files still unsaved keep it waiting."""
        with self.hub._lock:
            waiting = [dict(i) for i in self.hub._data["queue"]["items"]
                       if i["kind"] == "ticket" and i["state"] == "unclean"]
        for item in waiting:
            if not item.get("repo") or unsaved(item["repo"], item.get("blocking") or []) != []:
                continue
            try:
                self._recheck(item)
            except Exception as e:  # tried again at the next pass, never failed for it
                self._update(item["key"], note="the landing did not run: {}: {}".format(type(e).__name__, e))

    def _recheck(self, item):
        key = item["key"]
        found, row = self._row(key)
        if not found:  # the tickets could not be read: not a try
            self._update(key, recheck_at=self.hub.now() + RECHECK_EVERY)
            return
        if row is None:
            self._end(key, "skipped", note="no longer open: it was resolved or dropped while its checks waited")
            return
        if item.get("checked") is not None:  # the checks passed and the review could not run: only it runs again
            self._update(key, state="review", recheck_at=None, note="the review runs again")  # in its map's next one
            return
        run = {"t": row, "agent": item.get("runner"), "inst": {}, "base": item.get("base_sha"),
               "first_base": item.get("first_base"), "log": item.get("log"), "folder": item.get("run"),
               "tree": item.get("tree"), "branch": item.get("branch")}
        if not run["base"] or not run["log"]:
            self._end(key, "failed", note="cannot recheck: the run's base commit or log is not recorded")
            return
        res = self.runner.finish(item, run, False, recheck=True)
        self._update(key, checks=res["checks"])
        self._apply(item, res)
        if res["state"] == "done" and res["commit"]:
            self.runner.rebuild_after(row["repo"], run.get("landed_on") or run.get("base"), res["commit"])

    def _reviews(self):
        """A map's second pass: one per map at a time, started when the map's run has ended, when its oldest landed
        ticket waited review_every(), or on the owner's Review now, judging the landed tickets no review holds
        (`_start_reviews`); once it ended or ran past its limit, each ticket is judged: resolved, left open with
        the findings, or `recheck` when its review could not run (`_review_end`). A review is a process like a worker:
        the tick never waits for it, and it holds no repo and no agent slot, so other tickets start meanwhile."""
        for m, rv in list(self.reviews.items()):
            try:
                ended = rv["p"].poll() is not None
                over = not ended and self.hub.now() - rv["at"] > rv["limit"]
                if not (ended or over):
                    continue
                _kill_group(rv["p"], grace=3 if over else 0)
                del self.reviews[m]
                self._consume(rv, final=True)  # its usage readings pace its account like a worker's
                self._review_end(rv, over)
            except Exception as e:  # the commits and the claims stay: the review runs again later
                self.reviews.pop(m, None)
                for key in rv["keys"]:
                    with self.hub._lock:
                        item = next((dict(i) for i in self.hub._data["queue"]["items"]
                                     if i["key"] == key and i["state"] == "review"), None)
                    if item:
                        self._apply(item, self._review_failed(item, "{}: {}".format(type(e).__name__, e)))
        if not self.stopped:
            try:
                self._start_reviews()
            except Exception as e:  # tried again at the next look
                print("sb hub queue: reviews: {}: {}".format(type(e).__name__, e), file=sys.stderr, flush=True)

    @staticmethod
    def _review_failed(item, why):
        return {"state": "recheck", "commit": item.get("commit"), "checked": item.get("checked") or "",
                "review": None, "note": "review could not run: " + why}

    def review_now(self):
        """POST /api/review/now and `sbhub review-now`: start, at once, the review the timer would start for every map
        with landed tickets no review holds, busy or not. The maps started, sorted."""
        if self.stopped:
            return []
        return self._start_reviews(now=True)

    def _start_reviews(self, now=False):
        """Start ONE second pass per map over its landed tickets: those in state `landed`, and any in state `review`
        that no running second pass holds (a hub that restarted, or one that saved the old state). A map gets it when
        its run has ended (no item of it queued, running or in checks; a paused queue's queued items do not count),
        or, still busy, once its oldest such ticket landed review_every() ago (`landed_at`, kept in the queue file, so
        a restart does not reset the clock), or at once with `now` (the owner's Review now). One review at a time per
        map: a map with one running waits for it, and a running review's tickets are never taken again. The map-end
        review is the same call, so it takes only the leftovers. Returns the maps started."""
        with self.review_lock:
            return self._start_reviews_locked(now)

    def _start_reviews_locked(self, now):
        with self.hub._lock:
            q = self.hub._data["queue"]
            covered = {k for rv in self.reviews.values() for k in rv["keys"]}
            groups, busy = {}, set()
            for i in q["items"]:
                if i["kind"] != "ticket":
                    continue
                m, st = sbqueue.map_of(i["key"]), i["state"]
                if st in ("landed", "review") and i["key"] not in covered:
                    groups.setdefault(m, []).append(dict(i))
                elif st == "running" or st == "queued" and not q["paused"] or st == "recheck" and i.get("checked") is None:
                    busy.add(m)
            due = self.hub.now() - review_every()
            groups = {m: g for m, g in groups.items() if m not in self.reviews and (
                now or m not in busy or min(i.get("landed_at") or 0 for i in g) <= due)}
        started = []
        if not groups:
            return started
        rows = self.hub._fresh_tickets()
        if rows is None:
            return started  # the tickets could not be read: tried again at the next look
        by = {sbqueue.key(t): t for t in rows}
        for m, group in groups.items():
            if any(by.get(i["key"]) and self.runner.rebuild.busy(by[i["key"]]["repo"]) for i in group):
                continue  # the hub is about to restart on new code: no review starts on code it has not loaded
            entries = []
            for item in group:
                row = by.get(item["key"])
                if row is None:
                    self._end(item["key"], "skipped", note="no longer open: it was resolved or dropped before its review")
                    continue
                entries.append((item, self._review_run(item, row), item.get("commit")))
            if not entries:
                continue
            try:
                rv = self.runner.review_start(entries)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
                repo = entries[0][1]["t"]["repo"]
                if (isinstance(e, KeyError) and "cannot fill" in str(e) and self.runner.rebuild.mine(repo)
                        and self._restart_once(repo, str(e))):
                    # the template names a field this running code lacks: restart once, then try again, no 10-minute wait
                    self.runner.rebuild.ask(repo, "restart")
                    continue
                for item, _, _ in entries:
                    self._apply(item, self._review_failed(item, "could not start it: {}".format(e)))
                continue
            rv["at"] = self.hub.now()
            self.reviews[m] = rv
            started.append(m)
            for item, _, _ in entries:
                self._update(item["key"], state="review", review=rv["files"][item["key"]],
                             note="the Opus review runs on {}".format(rv["agent"]))
        return sorted(started)

    def _restart_once(self, repo, error):
        """True the first time `error` (a template naming a field the hub cannot fill) is seen for `repo`, and noted
        in the hub's home so the restarted hub, meeting the same error, falls back to the recheck instead of looping."""
        path = self.hub.home / "restart-asked.json"
        try:
            seen = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}
        if not isinstance(seen, dict) or seen.get(repo) == error:
            return False
        seen[repo] = error
        try:
            self.hub.home.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(seen), encoding="utf-8")
        except OSError:
            return False  # it could not be noted: no restart that might repeat
        return True

    def _review_run(self, item, row):
        return {"t": row, "agent": item.get("runner"), "inst": {}, "base": item.get("base_sha"),
                "first_base": item.get("first_base"), "log": item.get("log"), "folder": item.get("run"),
                "tree": item.get("tree"), "branch": item.get("branch")}

    def _review_end(self, rv, over):
        """Each ticket the ended second pass held is judged from its own review file."""
        for key in rv["keys"]:
            with self.hub._lock:
                item = next((dict(i) for i in self.hub._data["queue"]["items"]
                             if i["key"] == key and i["state"] == "review"), None)
            if item is None:
                continue
            found, row = self._row(key)
            if not found:
                raise OSError("the tickets could not be read")
            if row is None:
                self._end(key, "skipped", note="no longer open: it was resolved or dropped while its review ran")
                continue
            run = self._review_run(item, row)
            res = self.runner.review_end(item, run, item.get("commit"), item.get("checked") or "",
                                         item.get("checks") or [], rv, over)
            self._apply(item, res)
            if res["state"] == "done" and res["commit"]:  # after a second try, both tries' changes count
                self.runner.rebuild_after(row["repo"], (item.get("redo") or {}).get("base") or item.get("base_sha"),
                                          res["commit"])

    def _finish_job(self, item, run, over):
        """A job has no claim, verdict or retry: exit 0 is done, anything else failed, except a usage limit,
        which queues it again for the agent's reset. Its result text is saved in its run folder."""
        key, code = item["key"], run["p"].returncode
        text = _tail(run["log"], run.get("start", 0))
        if run.get("adopted"):  # not this hub's child: its exit code is lost, its result line says how it went
            code = 0 if _result_ok(text) else 1
        if not over and code != 0 and self._job_stopped(item, run):
            return
        result = Path(run["log"]).parent / "result.md"
        result.write_text(_job_result(text) + "\n", encoding="utf-8")
        if over:
            self._end(key, "failed", result=str(result), note=ran_past(self.limit))
        elif code == 0:
            self._end(key, "done", result=str(result), note="done; result in " + str(result.parent))
        else:
            self._end(key, "failed", result=str(result), note="the worker exited {}".format(code))
        if item.get("fix_build"):
            self._fix_ended(item, run, result, code == 0 and not over)

    def _close_off(self):
        """Once a day, while the queue holds anything besides close-off jobs, queue the morning close-off for
        the next CLOSE_OFF_AT: a job (the pool's agent, sonnet) that writes the morning note into the shared
        run folder <date>-close-off, checks and summarises each map that had items, then clears finished
        items. Its prompt is templates/close-off.md."""
        if not self.close_off:
            return
        now = self.hub.now()
        at = next_clock("{:02d}:{:02d}".format(*CLOSE_OFF_AT), now)
        day = datetime.fromtimestamp(at).strftime("%Y-%m-%d")
        with self.hub._lock:
            q = self.hub._data["queue"]
            others = [i for i in q["items"] if not i.get("close_off")]
            if not others or q.get("close_off_day") == day:
                return
            q["close_off_day"] = day
            maps = sorted({i.get("map") or i["key"].rsplit("#", 1)[0] for i in others if i["kind"] == "ticket"})
            self.hub._save()
        try:
            template = CLOSE_OFF.read_text(encoding="utf-8")
        except OSError as e:
            print("sb hub queue: close-off template: {}".format(e), file=sys.stderr, flush=True)
            return
        prompt = (template.replace("{date}", day).replace("{port}", str(self.port))
                  .replace("{maps}", "\n".join("- " + m for m in maps) or "- (none: only jobs ran)"))
        folder = self.hub.home / "close-off"  # its working folder: it changes no repo
        folder.mkdir(parents=True, exist_ok=True)
        try:
            self.hub._queue_job(str(folder), str(folder), prompt, None, "sonnet", "close-off", not_before=at,
                                close_off=True)
        except ValueError:
            pass  # already queued

    def _final_review(self):
        """When the last ticket item has ended: with `final_review` on, one review job per touched repo."""
        with self.hub._lock:
            q = self.hub._data["queue"]
            if any(i["kind"] == "ticket" and i["state"] in ("queued", "running", "landed", "review")
                   for i in q["items"]):
                return
            bases, q["bases"] = q.get("bases") or {}, {}
            if not bases:
                return
            # with a pool the review goes where it fits; with one agent, on it
            on, agent = q.get("final_review"), q["agent"] if len(pool(q)) <= 1 else None
            q["version"] += 1
            self.hub._save()
        for repo, b in bases.items():
            if not on:
                break
            try:
                self.hub._queue_job(b["project"], repo, REVIEW_PROMPT.format(b["sha"]), agent, "opus",
                                    "final-review-" + Path(repo).name)
            except ValueError:
                pass  # already queued

    # ---- starting the next tickets ----

    def _load(self, running):
        """agent -> [its running workers, the share of its 5-hour window they still need]: a worker's cost
        less the rise its agent's use has already shown since it started (only when it runs alone), never below 0."""
        load = {}
        for i in running:
            inst = self.hub._data["installed"].get(i.get("runner")) or {}
            run = self.procs.get(i["key"]) or {}
            u, u0 = inst.get("usage"), run.get("u0")
            # only a worker alone on its account owns the rise; overlapped ones still owe their whole cost
            rise = u["five_hour"] - u0["five_hour"] if run.get("alone") and u and u0 and _same_window(u, u0) else 0.0
            l = load.setdefault(i.get("runner"), [0, 0.0])
            l[0] += 1
            l[1] += max(0.0, _cost(inst, _tier(i.get("model")))[0] - rise)
        return load

    @staticmethod
    def _fit(name, inst, tier, load, now):
        """(score, need, why) for one more item of `tier` on agent `name`: score is None when it does not fit,
        why then a plain reason (empty when the agent is only busy). With no reading (agy, or a probe not yet
        answered) an agent runs one worker; measured agents rank first, then by the soonest weekly reset, the soonest
        five-hour reset and the room left after it."""
        if inst is None:
            return None, 0.0, "{} is not an installed agent".format(name)
        if inst.get("login") == "expired":
            return None, 0.0, "{} is signed out until you sign in to it".format(name)
        if (inst.get("limited_until") or 0) > now:
            return None, 0.0, "{} is at its usage limit until {}".format(name, _hm(inst["limited_until"]))
        n, owed = load.get(name, (0, 0.0))
        u = inst.get("usage") if inst.get("kind") == "claude" else None
        if u and (now - (u.get("at") or 0) > READING_OLD or not u.get("five_hour_resets")):
            u = None  # too old to trust, or a window with no known reset: as good as no reading
        if not u:
            return ((0, 0.0), 0.0, "") if n == 0 else (None, 0.0, "")
        week_resets = u.get("seven_day_resets")
        week = (u.get("seven_day") or 0.0) if not week_resets or week_resets > now else 0.0
        if week >= GATE_7D:
            return None, 0.0, "{} used {} of its week; resets {}".format(name, _pct(week), _hm(week_resets, "%a %H:%M"))
        cost, learned = _cost(inst, tier)
        if n >= (MAX_PER_AGENT if learned else 1):
            return None, 0.0, ""
        resets = u.get("five_hour_resets") or 0
        five, left = (u["five_hour"], resets - now) if resets > now else (0.0, WINDOW)  # a reset window is empty
        need = min(NEED_CAP, cost * min(1.0, left / TICKET_SECONDS))
        room = GATE_5H - five - owed - need
        # among accounts that fit: the week that resets soonest first (none known: after), then the five hours
        # that reset soonest (an empty, already reset window: after), then the most room
        order = (1, -(week_resets if week_resets and week_resets > now else float("inf")),
                 -(resets if resets > now else float("inf")), room)
        if n == 0 and five < IDLE_FLOOR:
            return order, need, ""  # an idle, nearly empty account is never left waiting
        if room < -1e-9:
            return None, need, "{} {} used{}, needs about {}; resets {}".format(
                name, _pct(five), ", {} more held by its running work".format(_pct(owed)) if owed >= 0.005 else "",
                _pct(need), _hm(resets))
        return order, need, ""

    def _pick(self, q, item, t, load, now):
        """(agent, its entry, need) for the agent the item fits on whose week resets soonest, then five hours, then most room (ties: pool order),
        or (None, None, why): why is a note naming each agent's use and reset when usage alone stops it,
        empty when an agent is only busy. An item's own agent wins and never falls back to the pool."""
        names = [item["agent"]] if item.get("agent") else pool(q)
        model = item.get("model") if item.get("tries") or item["kind"] == "job" else item.get("model") or (t or {}).get("tier")
        best, whys, busy = None, [], False
        for name in names:
            inst = self.hub._data["installed"].get(name)
            score, need, why = self._fit(name, inst, _tier(model), load, now)
            if score is not None:
                if best is None or score > best[0]:
                    best = (score, name, inst, need)
            elif why:
                whys.append(why)
            else:
                busy = True
        if best:
            return best[1], best[2], best[3]
        return None, None, "waits: " + " · ".join(whys) if whys and not busy else ""

    @staticmethod
    def _retry_first(items, by):
        """{repo: key} of the first queued ticket on a later try that a queued ticket of its map waits on: nothing
        else of its repo starts before it goes again."""
        waited = {sbqueue._blocker_key(by[i["key"]], b) for i in items if i["state"] == "queued" and i["key"] in by
                  for b in by[i["key"]]["blocked_by_open"]}
        out = {}
        for i in items:
            if i["kind"] == "ticket" and i["state"] == "queued" and i.get("tries") and i["key"] in waited:
                out.setdefault((by.get(i["key"]) or {}).get("repo") or i.get("repo"), i["key"])
        return out

    def _start(self):
        now = self.hub.now()
        with self.hub._lock:
            q = self.hub._data["queue"]
            if q.get("stop_at") and now >= q["stop_at"]:  # also what waits for an agent's reset
                waiting = [i for i in q["items"] if i["state"] == "queued"]
                for i in waiting:
                    i.update(state="skipped", note="past the stop time", ended=now)
                night = self.hub._night_live()
                if waiting and night:
                    night["stop_time"] = True
                ended = not any(i["state"] == "running" for i in q["items"])
                if ended:  # the night is over: tomorrow's items are not skipped at once
                    q["stop_at"] = None
                if waiting or ended:
                    q["version"] += 1
                    self.hub._save()
                return
            cached = {sbqueue.key(t): t for t in self.hub._tcache[1] or []}
            load = self._load([i for i in q["items"] if i["state"] == "running"])
            startable, noted = [], False
            for i in q["items"]:
                if i["state"] != "queued":
                    continue
                if (i.get("not_before") or 0) > now:  # a timed job: never before its time
                    why = "waits until {}".format(_hm(i["not_before"]))
                    if i.get("note") != why:
                        i["note"], noted = why, True
                    continue
                name, inst, why = self._pick(q, i, cached.get(i["key"]), load, now)
                if name:
                    startable.append(i)
                elif why and i.get("note") != why:  # the owner reads why it waits
                    i["note"], noted = why, True
                elif not why and str(i.get("note") or "").startswith("waits: "):  # only busy now: the reason went
                    i["note"], noted = "", True
            if noted:
                q["version"] += 1
                self.hub._save()
            if q["paused"] or not startable:
                return  # nothing could start: no need to read the tickets
            tickets = any(i["kind"] == "ticket" for i in startable)
        rows = self.hub._fresh_tickets() if tickets else []  # re-read just before starting: the vault may have changed
        if rows is None:
            return
        by = {sbqueue.key(t): t for t in rows}
        # the hub's own claim left by a release that failed is no claim against its own queued item
        mine = {k: ({**t, "status": "open", "claimed_by": None} if _hub_holds(t) else t) for k, t in by.items()}
        picks, changed = [], False
        with self.hub._lock:
            q = self.hub._data["queue"]
            if q["paused"]:
                return
            live = self.hub._live_keys()
            self.hub._sync_maps(q)
            # whole maps first: in each repo only the first queued map with work or something to start runs; a map
            # with neither is stuck, and what is left of it is skipped naming the ticket it is stuck on
            current, stuck = sbqueue.current_maps(q["items"], mine, q["maps"], live)
            for m, ks in stuck.items():
                for k in ks:
                    root, why = sbqueue.stuck_on(k, mine, live, q["items"])
                    title = (by.get(root) or {}).get("title") or next(
                        (i.get("title") for i in q["items"] if i["key"] == root and i.get("title")), "")
                    item = next(i for i in q["items"] if i["key"] == k)
                    note = ("blocked: after {} ({}, {}): the map is stuck on it".format(title or root, root, why)
                            if root != k else "the map is stuck on {}{} ({})".format(root, " " + title if title else "", why))
                    item.update(state="skipped", ended=now, note=note, **({"title": by[k]["title"]} if k in by else {}))
                    changed = True
            if stuck:
                self.hub._sync_maps(q)
            running = [i for i in q["items"] if i["state"] == "running"]
            landed = {i["key"] for i in q["items"] if i["state"] == "landed"}  # not judged yet: no longer holds anything
            load, par = self._load(running), {}
            busy = {}  # repo -> the paths of each worktree ticket running in it; None for one in the checkout itself
            first = self._retry_first(q["items"], by)
            for i in running:
                busy.setdefault(i.get("repo"), []).append(list(i.get("paths") or []) if i.get("tree") else None)

            def parallel(repo):
                if repo not in par:
                    par[repo] = parallel_of(repo) if repo and usable_project(repo) else 1
                return par[repo]

            def room(repo, paths):  # a repo is free, or runs worktree tickets none of whose paths meet these
                b = busy.get(repo) or []
                return not b or (parallel(repo) > len(b) and None not in b
                                 and not any(paths_overlap(paths, x) for x in b))

            def take(name, need):  # what this pass started counts against its agent at once
                l = load.setdefault(name, [0, 0.0])
                l[0] += 1
                l[1] += need
            for item in q["items"]:
                if item["state"] != "queued" or (item.get("not_before") or 0) > now:
                    continue
                if item["kind"] == "job":
                    if busy.get(item.get("repo")):
                        continue
                    name, inst, need = self._pick(q, item, None, load, now)
                    if name is None:
                        if item.get("resume"):  # its last try's work is in the tree: nothing else goes first
                            busy.setdefault(item.get("repo"), []).append(None)
                        continue
                    item.update(state="running", runner=name, started=now, ended=None, note="starting")
                    take(name, need)
                    busy.setdefault(item.get("repo"), []).append(None)
                    picks.append((dict(item), None, name, dict(inst)))
                    changed = True
                    continue
                t = by.get(item["key"])
                repo = (t or {}).get("repo") or item.get("repo")
                if repo in current and current[repo] != sbqueue.map_of(item["key"]):
                    continue  # an earlier map of its repo is not finished: it waits its map's turn
                if ((q.get("builds") or {}).get(str(repo)) or {}).get("held"):
                    continue  # its repo's build is broken outside any ticket: nothing new starts on it
                if first.get(repo, item["key"]) != item["key"]:
                    continue  # a failed ticket its map waits on goes again before anything else of its repo
                if t is not None and not room(t.get("repo"), t.get("paths")):
                    continue  # its repo is busy: it is not about to start, so it is not judged yet
                name, inst, need = self._pick(q, item, t, load, now)
                if name is None:
                    if item.get("resume") and t is not None and not item.get("tree"):
                        busy.setdefault(t.get("repo"), []).append(None)  # its last try's work is in the checkout
                    continue  # no agent has room for it now (the first pass noted why)
                skip, gone = None, None
                if t is None:
                    gone, why = closed_note(item["key"])
                    skip = "no longer open: " + (why or "resolved or out of scope since it was queued")
                else:
                    state, reason = sbqueue.classify(mine[item["key"]], live, rows)
                    if state != "ready":
                        skip = "{}: {}".format(state, reason)
                    elif not usable_project(t.get("repo")):
                        skip = "its map's repo is not a folder here: {}".format(t.get("repo") or "none")
                if skip:
                    item.update(state="skipped", note=skip, ended=now, **({"title": t["title"] if t else gone} if t or gone else {}))
                    changed = True
                    continue
                if any(sbqueue._blocker_key(t, b) not in landed for b in t["blocked_by_open"]):
                    continue  # a blocker is queued ahead of it: it waits for it (one that landed does not hold it)
                model = (item.get("model") if item.get("tries") or item.get("model") else
                         inst.get("model") if inst.get("kind") == "agy" else t.get("tier") or "sonnet")
                if parallel(t["repo"]) > 1 or is_unity(t["repo"]):  # its own worktree; a later try keeps it
                    tree, branch = ((item["tree"], item["branch"]) if item.get("tree") and item.get("branch")
                                    else tree_of(self.hub.home, t["repo"], t["map"], t["num"]))
                    paths = list(t.get("paths") or [])
                else:
                    tree, branch, paths = None, None, None
                item.update(state="running", runner=name, repo=t["repo"], map=t["map"], title=t["title"],
                            model=model, started=now, ended=None, note="starting", tree=tree, branch=branch,
                            paths=paths)
                take(name, need)
                busy.setdefault(t["repo"], []).append(paths if tree else None)
                picks.append((dict(item), t, name, dict(inst)))
                changed = True
            if changed:
                q["version"] += 1
                self.hub._save()
        for item, t, name, inst in picks:
            if t is None:
                self._launch_job(item, name, inst)
            else:
                self._launch(item, t, name, inst)

    def _set_waits(self):
        """Say on each queued item what it waits for (item["waits"] = {kind, with, text}, gone once it does not) and
        keep queue["repos"]: per repo with anything queued or running, how many run at once, run now, and the most
        queued tickets that could run side by side. Read from the cached ticket list; never starts anything."""
        now = self.hub.now()
        with self.hub._lock:
            q = self.hub._data["queue"]
            by = {sbqueue.key(t): t for t in self.hub._tcache[1] or []}
            items = q["items"]
            running = [i for i in items if i["state"] == "running"]
            landed = {i["key"] for i in items if i["state"] == "landed"}
            load, par, repos = self._load(running), {}, {}

            def at_once(repo):
                if repo not in par:
                    par[repo] = parallel_of(repo) if repo and usable_project(repo) else 1
                return par[repo]
            try:
                current, _ = sbqueue.current_maps(items, by, q.get("maps") or [], self.hub._live_keys())
            except (KeyError, TypeError, ValueError):
                current = {}
            queued_paths = {}
            changed = False
            keys = {x["key"] for x in items}

            first = self._retry_first(items, by)

            def ahead(t):  # a blocker still in the queue that has not landed
                return next((k for k in (sbqueue._blocker_key(t, b) for b in t["blocked_by_open"])
                             if k in keys and k not in landed), None)
            for i in items:
                if i["state"] != "queued":
                    if i.pop("waits", None) is not None:
                        changed = True
                    continue
                t = by.get(i["key"])
                repo = (t or {}).get("repo") or i.get("repo")
                if i["kind"] == "ticket" and t is not None:
                    queued_paths.setdefault(repo, []).append(list(t.get("paths") or []))
                w = None
                here = [r for r in running if r.get("repo") == repo]
                if q["paused"]:
                    w = ("paused", None, "the queue is paused: nothing new starts")
                elif (i.get("not_before") or 0) > now:
                    w = ("time", None, "starts at {}".format(_hm(i["not_before"])))
                elif ((q.get("builds") or {}).get(str(repo)) or {}).get("held"):
                    h = q["builds"][str(repo)]["held"]
                    w = ("build", None, "{}'s build is broken in {}: nothing new starts until it builds again".format(
                        Path(repo or "").name, ", ".join(Path(f).name for f in h.get("files") or []) or "files"))
                elif t is not None and ahead(t):
                    w = ("after", ahead(t), "comes after {}, which has not landed".format(ahead(t)))
                elif repo in current and current[repo] != sbqueue.map_of(i["key"]):
                    w = ("after", current[repo], "comes after the map {}".format(current[repo]))
                elif i["kind"] == "ticket" and first.get(repo, i["key"]) != i["key"]:
                    w = ("after", first[repo], "comes after the next try of {}, which its map waits on".format(first[repo]))
                elif here and i["kind"] == "ticket":
                    for r in here:
                        shared = shared_path(r.get("paths"), (t or {}).get("paths")) if r.get("tree") else None
                        if shared:
                            w = ("files", r["key"], "shares {} with {}, which is running".format(shared, r["key"]))
                            break
                    if w is None and (None in [r.get("paths") if r.get("tree") else None for r in here]
                                      or len(here) >= at_once(repo)):
                        w = ("limit", None, "{} already runs its {} at once".format(Path(repo or "").name or "the repo",
                                                                                   at_once(repo)))
                elif here:  # a job waits for its repo to be empty
                    w = ("limit", None, "{} already runs {} at once".format(Path(repo or "").name or "the repo", len(here)))
                if w is None:
                    name, _, why = self._pick(q, i, t, load, now)
                    if name is None:
                        w = ("account", None, why[len("waits: "):] if why.startswith("waits: ") else
                             "no account has room right now")
                new = {"kind": w[0], "with": w[1], "text": w[2]} if w else None
                if i.get("waits") != new:
                    if new:
                        i["waits"] = new
                    else:
                        i.pop("waits", None)
                    changed = True
            for i in running:
                if i.get("repo"):
                    repos.setdefault(i["repo"], 0)
            for repo in queued_paths:
                repos.setdefault(repo, 0)
            out = {}
            for repo in repos:
                out[repo] = {"at_once": at_once(repo),
                             "running": sum(1 for r in running if r.get("repo") == repo),
                             "side_by_side": side_by_side(queued_paths.get(repo, []))}
            if q.get("repos") != out:
                q["repos"], changed = out, True
            if changed:
                self.hub._save()

    def _board(self, map_name, remember=True):
        """The map's run board for tonight (`sbmap run <map>` once a night), or None when sbmap failed."""
        with self.hub._lock:
            board = self.hub._data["queue"].get("runs", {}).get(map_name)
        if board:
            return board
        rc, out, err = self.sbmap("run", map_name)
        if rc != 0 or not out:
            return None
        board = str(_vault() / out.splitlines()[-1])  # sbmap prints it vault-relative (absolute outside the vault)
        if remember:
            with self.hub._lock:
                self.hub._data["queue"].setdefault("runs", {})[map_name] = board
                self.hub._save()
        return board

    def _track(self, key, run):
        """Hold a started worker; a cost is learned only from a worker no other one of its agent overlapped."""
        others = [r for r in self.procs.values() if r["agent"] == run["agent"]]
        for r in others:
            r["alone"] = False
        run["alone"] = not others
        self.procs[key] = run

    def _launch(self, item, t, name, inst):
        if item.get("integrate_only"):
            self._pass(item, t, name)
            return
        run, res = self.runner.start(item, t, name, inst, board=self._board(t["map"]))
        if res is not None:
            self._apply(item, res, judged=False)
            return
        key, base = item["key"], run["base"]
        with self.hub._lock:  # the night's first base of each repo, for the final review
            self.hub._data["queue"].setdefault("bases", {}).setdefault(
                t["repo"], {"sha": base, "project": _project_of(t["map"])})
            self.hub._save()
        self._track(key, run)
        p = run["p"]
        sess = {"session": run["session"], "session_dir": run["session_dir"]} if run.get("session") else {}
        self._update(key, drop=() if sess else ("session", "session_dir"), base_sha=base,
                     first_base=run.get("first_base") or base, log=run["log"], log_start=run["start"], run=run["folder"],
                     pid=p.pid, pid_start=_proc_start(p.pid), note="running on {} ({})".format(name, item["model"]),
                     **sess)

    def _launch_job(self, item, name, inst):
        key = item["key"]
        folder = item.get("run")
        if not folder:  # a job queued again after a limit keeps its folder
            shared = os.path.isabs(item["project"])  # a checkout outside the wayfinder projects
            rc, out, err = self.sbmap("run", *(("--shared", item["name"]) if shared else (item["project"], item["name"])))
            if rc != 0 or not out:
                self._end(key, "failed", note="could not start: sbmap run failed: " + (err or out))
                return
            folder = str((_vault() / out.splitlines()[-1]).parent)
        log = str(Path(folder) / "job.log")
        brief = "{}\n\nWrite any file this job produces to this folder: {}\n".format(item["prompt"], folder)
        if item.get("resume"):
            r = item["resume"]
            brief += ("\nAn earlier try on {} stopped {}. What it wrote may already be in that folder; its log: {}. "
                      "Continue from there, do not redo finished work.\n").format(r["agent"], r["why"], log)
        model = item.get("model") or (inst.get("model") if inst.get("kind") == "agy" else "sonnet")
        env = {"SB_HUB_AGENT": key, "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.port),
               "SB_HUB_RUN": str(folder)}
        try:
            start = os.path.getsize(log)  # launch appends: this try's output begins here
        except OSError:
            start = 0
        try:
            if self.stopped:
                raise OSError("the hub is stopping")
            p = self.hub.launcher(inst, brief, item["repo"], model, env, log)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            self._end(key, "failed", note="could not start the worker: {}".format(e))
            return
        self._track(key, {"p": p, "agent": name, "inst": inst, "log": log, "start": start})
        self._update(key, log=log, log_start=start, run=folder, pid=p.pid, pid_start=_proc_start(p.pid),
                     note="running on {} ({})".format(name, model))

    # ---- the night's digest ----

    def _digest(self):
        """When the last ticket item has ended, append what happened to each touched map's run board."""
        with self.hub._lock:
            q = self.hub._data["queue"]
            tickets = [i for i in q["items"] if i["kind"] == "ticket"]
            if any(i["state"] in ("queued", "running", "landed", "review") for i in tickets):
                return
            ended = [i for i in tickets if i["state"] in ("done", "failed", "skipped") and not i.get("digested")]
            if not ended:
                return
            for i in ended:
                i["digested"] = True
            ended = [dict(i) for i in ended]
            runs, q["runs"] = q.get("runs", {}), {}
            q["version"] += 1
            self.hub._save()
        by_map = {}
        for i in ended:
            by_map.setdefault(i.get("map") or i["key"].rsplit("#", 1)[0], []).append(i)
        stamp = datetime.fromtimestamp(self.hub.now()).strftime("%Y-%m-%d %H:%M")
        for m, items in by_map.items():
            board = runs.get(m) or self._board(m, remember=False)
            if not board:
                continue
            lines = ["", "## The night's digest, {}".format(stamp), ""]
            for state in ("done", "failed", "skipped"):
                for i in items:
                    if i["state"] != state:
                        continue
                    why = ("commit " + (i.get("commit") or "")[:9] if state == "done" else
                           (i.get("note") or "").splitlines()[0] if i.get("note") else "no reason recorded")
                    lines.append("- {}: {}, {}".format(i.get("title") or i["key"], state, why))
            try:
                with open(board, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except OSError as e:
                print("sb hub queue: digest for {}: {}".format(m, e), file=sys.stderr, flush=True)


def _signed_in(path):
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("oauthAccount"))
    except (OSError, ValueError, AttributeError):
        return False


def _run(cmd, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=20, **kw)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def generic_provider(project):
    """Branch, uncommitted files, last commit and the vault's maps for a project."""
    git = ["git", "-c", "core.fsmonitor=false", "-C", project]
    branch = _run(git + ["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    dirty = len(_run(git + ["status", "--porcelain"]).splitlines())
    last = _run(git + ["log", "-1", "--format=%s (%cr)"]) or "none"
    maps = _run([sys.executable, str(SBMAP), "maps", "--repo", project]).splitlines()[:8]
    return {"title": "Repo and maps", "icon": "git", "widgets": [
        {"kind": "status", "label": "Branch", "value": branch, "level": "ok"},
        {"kind": "status", "label": "Uncommitted files", "value": str(dirty), "level": "warn" if dirty else "ok"},
        {"kind": "status", "label": "Last commit", "value": last, "level": "ok"},
        {"kind": "log", "label": "Maps in the vault", "lines": maps}]}


def _provider_error(name, reason):
    return {"title": name, "widgets": [
        {"kind": "status", "label": "provider", "value": str(reason)[:120], "level": "bad"}]}


def ticket_ref(text, map_, project, rows):
    """The open ticket ('<map>#<num>') a session's free-text `ticket` names, or None when it names none for sure.
    Ticket numbers are unique within a repo, so a number is enough once the project or map narrows the rows:
    'sk4te/party-playtest#1060', 'party-playtest 1060', '#1060' or '1060' with the project known, or the exact title."""
    if not isinstance(text, str) or not text.strip() or not rows:
        return None
    keys = {sbqueue.key(t) for t in rows}
    m = re.search(r"([\w.-]+/[\w.-]+)#0*(\d+)", text)
    if m:
        k = "{}#{}".format(m.group(1), int(m.group(2)))
        return k if k in keys else None
    pool = rows
    if isinstance(map_, str) and "/" in map_:
        pool = [t for t in rows if t["map"].split("/")[0] == map_.split("/")[0]]
    elif isinstance(project, str) and project:
        pool = [t for t in rows if t["map"].split("/")[0].lower() == Path(project).name.lower()]
    nums = {int(n) for n in re.findall(r"(?<![\w.])#?0*(\d{1,5})(?![\w.])", text)}
    hit = (len(nums) == 1 and [t for t in pool if int(t["num"]) in nums]) or \
          [t for t in pool if (t.get("title") or "").strip().lower() == text.strip().lower()]
    return sbqueue.key(hit[0]) if len(hit) == 1 else None


def usable_project(p):
    """Only an absolute path to a directory that exists is a project."""
    return isinstance(p, str) and os.path.isabs(p) and os.path.isdir(p)


def read_trusted(home):
    try:
        return set((Path(home) / "trusted").read_text(encoding="utf-8").split("\n")) - {""}
    except OSError:
        return set()


def set_trusted(home, project, yes):
    paths = sorted(read_trusted(home) - {project} | ({project} if yes else set()))
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / "trusted").write_text("".join(p + "\n" for p in paths), encoding="utf-8")


def _scripts(project):
    """Executable regular files in <project>/.sb/providers/, by name; symlinks are skipped."""
    folder = Path(project) / ".sb" / "providers"
    if folder.is_symlink():
        return []
    try:
        return sorted(f for f in folder.iterdir()
                      if f.is_file() and not f.is_symlink() and os.access(f, os.X_OK))
    except OSError:
        return []


def run_providers(project, timeout=120, trusted=True):
    """The generic provider, then each script in <project>/.sb/providers/ by name (if trusted)."""
    out = [generic_provider(project)]
    files = _scripts(project)
    if files and not trusted:
        out.append({"title": "Project providers", "widgets": [
            {"kind": "status", "label": "Not trusted yet", "value": "run: sbhub trust <project>", "level": "warn"}]})
        return out
    for f in files:
        try:
            # its own process group, so a timeout kills what it started too (a test suite), not only the script
            p = subprocess.Popen([str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                                 cwd=project, start_new_session=True)
            try:
                stdout, stderr = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(p, grace=1)
                p.communicate()
                raise
            r = subprocess.CompletedProcess(p.args, p.returncode, stdout, stderr)
            if r.returncode != 0:
                out.append(_provider_error(f.name, "exit {}: {}".format(r.returncode, r.stderr.strip() or r.stdout.strip())))
                continue
            d = json.loads(r.stdout)
            if not isinstance(d, dict) or not isinstance(d.get("widgets"), list):
                raise ValueError("output is not an object with a widgets list")
            if not all(isinstance(w, dict) for w in d["widgets"]):
                raise ValueError("every widget must be an object")
            if not isinstance(d.get("title", ""), str) or not isinstance(d.get("icon", ""), str):
                raise ValueError("title and icon must be text")
            out.append({**d, "title": d.get("title") or f.name})
        except subprocess.TimeoutExpired:
            out.append(_provider_error(f.name, "timed out after {:g} s".format(timeout)))
        except (OSError, ValueError) as e:
            out.append(_provider_error(f.name, e))
    return out


def refresh_loop(hub, every=REFRESH_EVERY):
    """Run the providers for each project with an agent, one project at a time, forever."""
    while True:
        with hub._lock:
            projects = sorted({a["project"] for a in hub._data["agents"].values() if usable_project(a.get("project"))})
        trusted = hub.trusted()
        for p in projects:
            try:
                result = run_providers(p, trusted=p in trusted)
            except Exception as e:  # one project's failure never stops the others' refresh
                result = [_provider_error("providers", "{}: {}".format(type(e).__name__, e))]
            with hub._lock:
                hub.providers[p] = result
        with hub._lock:
            for p in [p for p in hub.providers if p not in projects]:
                del hub.providers[p]
            hub.queued &= set(projects)
        hub.changed.wait(every)
        hub.changed.clear()


DEFAULT_PORT = 8765


def notify(title, text):
    """One macOS notification; skipped off macOS or with SB_HUB_NOTIFY=0."""
    if sys.platform != "darwin" or os.environ.get("SB_HUB_NOTIFY") == "0":
        return
    script = "display notification {} with title {}".format(json.dumps(text), json.dumps(title))
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def default_port():
    try:
        port = int(os.environ.get("SB_HUB_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT
    return port if 0 < port < 65536 else DEFAULT_PORT


def make_handler(hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, ctype="application/json", headers=()):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path, ctype):
            """A whole file, or the one byte range asked for (a phone plays a video only from ranges)."""
            data = path.read_bytes()  # ponytail: read whole, fine while media stay under MEDIA_BYTES
            n, m = len(data), re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
            if not m or not (m[1] or m[2]):
                return self.send(200, data, ctype, [("Accept-Ranges", "bytes")])
            a, b = (int(m[1]), min(int(m[2] or n - 1), n - 1)) if m[1] else (max(0, n - int(m[2])), n - 1)
            if a > b:
                return self.send(416, b"", ctype, [("Content-Range", "bytes */{}".format(n))])
            self.send(206, data[a:b + 1], ctype, [("Accept-Ranges", "bytes"), ("Content-Range", "bytes {}-{}/{}".format(a, b, n))])

        def for_this_hub(self):
            """The Host must name the hub itself: a page that rebinds its own name to 127.0.0.1 gets nothing."""
            port = self.server.server_address[1]
            if self.headers.get("Host") in ("127.0.0.1:{}".format(port), "localhost:{}".format(port)):
                return True
            self.send(403, {"ok": False, "error": "forbidden"})
            return False

        def do_GET(self):
            if not self.for_this_hub():
                return
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                self.send(200, hub.state())
            elif path == "/api/trail":
                from urllib.parse import parse_qs, urlsplit
                try:
                    self.send(200, hub.trail((parse_qs(urlsplit(self.path).query).get("agent") or [""])[0]))
                except KeyError:
                    self.send(404, {"ok": False, "error": "no trail for that agent"})
            elif path == "/api/tickets":
                self.send(200, hub.tickets())
            elif path == "/api/map":
                from urllib.parse import parse_qs, urlsplit
                try:
                    self.send(200, hub.map_tickets((parse_qs(urlsplit(self.path).query).get("map") or [""])[0]))
                except KeyError:
                    self.send(404, {"ok": False, "error": "no such map"})
            elif path == "/api/ticket":
                from urllib.parse import parse_qs, urlsplit
                try:
                    self.send(200, hub.ticket_detail((parse_qs(urlsplit(self.path).query).get("key") or [""])[0]))
                except (KeyError, OSError):
                    self.send(404, {"ok": False, "error": "no such ticket"})
            elif path in ("/api/item/report", "/api/item/log"):
                from urllib.parse import parse_qs, urlsplit
                key = (parse_qs(urlsplit(self.path).query).get("key") or [""])[0]
                try:
                    self.send(200, hub.item_file(key, path.rsplit("/", 1)[-1])[1].encode("utf-8"),
                              "text/plain; charset=utf-8")
                except KeyError:
                    self.send(404, {"ok": False, "error": "no such file for that item"})
            elif path == "/api/media":
                from urllib.parse import parse_qs, urlsplit
                qs = parse_qs(urlsplit(self.path).query)
                key, name = (qs.get("key") or [""])[0], (qs.get("name") or [""])[0]
                try:
                    try:
                        found = hub.media_file(key, name)
                    except KeyError:  # a run the queue never had: its folder in the vault; a queue item's media stay as it recorded them
                        items = hub._run_items()
                        if any(i["key"] == key for i in items):
                            raise
                        f = sbruns.media_file(_vault(), items, key, name)
                        found = (f, MEDIA_TYPES[f.suffix.lower()])
                    self.send_file(*found)
                except (KeyError, OSError):
                    self.send(404, b"", "text/plain")
            elif path == "/api/nights":
                self.send(200, hub.nights())
            elif path == "/api/night":
                from urllib.parse import parse_qs, urlsplit
                try:
                    self.send(200, hub.night((parse_qs(urlsplit(self.path).query).get("id") or [""])[0]))
                except KeyError:
                    self.send(404, {"ok": False, "error": "no such night"})
            elif path == "/api/runs":
                from urllib.parse import parse_qs, urlsplit
                qs = parse_qs(urlsplit(self.path).query)
                try:
                    n = {k: int(float((qs.get(k) or [d])[0])) for k, d in (("since", 0), ("offset", 0), ("limit", 100))}
                except ValueError:
                    return self.send(400, {"ok": False, "error": "since, offset and limit are numbers"})
                self.send(200, hub.runs(n["since"], n["offset"], n["limit"]))
            elif path == "/api/run":
                from urllib.parse import parse_qs, urlsplit
                try:
                    self.send(200, hub.run((parse_qs(urlsplit(self.path).query).get("key") or [""])[0]))
                except (KeyError, OSError):
                    self.send(404, {"ok": False, "error": "no such run"})
            elif path.startswith("/api/question/"):
                try:
                    self.send(200, hub.question(path[len("/api/question/"):]))
                except KeyError:
                    self.send(404, {"ok": False, "error": "no such question"})
            else:
                self.send(404, {"ok": False, "error": "not found"})

        def from_the_page_or_a_program(self):
            """A POST must be JSON and not from another origin: a web page cannot post to the hub."""
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                return False
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            return origin is None or origin in ("http://127.0.0.1:{}".format(port), "http://localhost:{}".format(port))

        def do_POST(self):
            if not self.for_this_hub():
                return
            path = self.path.split("?", 1)[0]
            if not self.from_the_page_or_a_program():
                self.send(403, {"ok": False, "error": "forbidden"})
                return
            if path.startswith("/api/queue/") and hub.queue_lock and not hub.queue_lock["mine"]:
                self.send(409, {"ok": False, "error": "this hub is read-only: {} holds the queue lock".format(
                    hub.queue_lock["holder"])})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                d = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(d, dict):
                    raise ValueError("the body must be a JSON object")
                code, out, alert = 200, None, None
                if path == "/api/report":
                    out = hub.report(d)
                    if out["needs_you"]:
                        alert = ("sb hub: needs you", "{}: {}".format(out["agent"], d.get("note") or d.get("state")))
                elif path == "/api/lock":
                    out = hub.lock(d["key"], d["by"])
                    code = 200 if out["ok"] else 409
                elif path == "/api/unlock":
                    out = hub.unlock(d["key"], d["by"])
                elif path == "/api/ask":
                    out = hub.ask(d["agent"], d["q"], d["options"], d["default"], d["wait"])
                    alert = ("sb hub: question", "{}: {}".format(d["agent"], d["q"]))
                elif path == "/api/answer":
                    out = hub.answer(d["qid"], d["answer"], d.get("by", "you"))
                elif path == "/api/send":
                    out = hub.send(d["to"], d["text"])
                elif path == "/api/unsend":
                    out = hub.unsend(d["id"])
                elif path == "/api/take":
                    out = hub.take(d["agent"], d.get("how"))
                elif path == "/api/queue/set":
                    out = hub.queue_set(d["keys"], d["version"], d.get("agent"))
                elif path == "/api/queue/move":
                    out = hub.queue_move(d["key"], d["to"], d["version"])
                elif path == "/api/queue/map":
                    out = hub.queue_map(d["map"], d["version"], d.get("agent"))
                elif path == "/api/queue/move_map":
                    out = hub.queue_move_map(d["map"], d["to"], d["version"])
                elif path == "/api/queue/pause":
                    out = hub.queue_pause(d["paused"])
                elif path == "/api/queue/parallel":
                    out = hub.queue_parallel(d["repo"], d["n"], d["version"])
                elif path == "/api/queue/agent":
                    out = hub.queue_agent(d["name"])
                elif path == "/api/queue/agents":
                    out = hub.queue_agents(d["names"], d["version"])
                elif path == "/api/queue/options":
                    out = hub.queue_options(d.get("stop_at"), d.get("final_review", False), d["version"])
                elif path == "/api/queue/job":
                    out = hub.queue_job(d["project"], d["prompt"], d.get("agent"), d.get("model"), d.get("name"),
                                        d.get("at") or None)
                elif path == "/api/queue/integrate":
                    out = hub.queue_integrate(d["keys"])
                elif path == "/api/queue/remove_job":
                    out = hub.queue_remove_job(d["key"], d["version"])
                elif path == "/api/queue/stop":
                    out = hub.queue_stop(d["key"], d["reason"], d["version"])
                elif path == "/api/night/start":
                    out = hub.night_start(d.get("name"), d.get("by"))
                elif path == "/api/night/stop":
                    out = hub.night_stop(d["mode"])
                elif path == "/api/night/rename":
                    out = hub.night_rename(d["name"])
                elif path == "/api/run/seen":
                    out = hub.run_seen(d["key"])
                elif path == "/api/agents/dismiss":
                    out = hub.agents_dismiss(d["agent"])
                elif path == "/api/agents/clear-quiet":
                    out = hub.agents_clear_quiet()
                elif path == "/api/review/now":
                    out = hub.review_now()
                elif path.startswith("/api/ticket/") and path[len("/api/ticket/"):] in TICKET_ACTIONS:
                    out = hub.ticket_action(path[len("/api/ticket/"):], d["key"], d.get("text"), d.get("commit"))
                elif path == "/api/queue/item_agent":
                    out = hub.queue_item_agent(d["key"], d["name"] if "name" in d else _KEEP, d["model"] if "model" in d else _KEEP)
                elif path == "/api/agents/scan":
                    out = {"ok": True, "installed": hub.agents_scan()}
                else:
                    code, out = 404, {"ok": False, "error": "not found"}
                if out.get("stale"):
                    code = 409
                self.send(code, out)
                if alert:  # after the answer: a slow osascript must not time the caller out
                    threading.Thread(target=notify, args=alert, daemon=True).start()
            except KeyError as e:
                missing = e.args[0] if e.args else ""
                if path == "/api/answer" and missing == d.get("qid"):
                    self.send(404, {"ok": False, "error": "no such question"})
                elif path == "/api/unsend" and missing == d.get("id"):
                    self.send(404, {"ok": False, "error": "no such message"})
                else:
                    self.send(400, {"ok": False, "error": "missing field {}".format(missing)})
            except (ValueError, TypeError) as e:
                self.send(400, {"ok": False, "error": str(e)})
            except Exception as e:
                self.send(500, {"ok": False, "error": "{}: {}".format(type(e).__name__, e)})

    return Handler


def _interrupt(*_):
    raise KeyboardInterrupt


def take_queue_lock(home):
    """Take the exclusive flock on <home>/queue.lock for this process. Returns (fd, None) when it is ours (the
    file then names this pid), or (None, holder) when another hub holds it; holder is what that hub wrote."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    f = open(home / "queue.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        who = f.read().strip() or "unknown"
        f.close()
        return None, who
    f.seek(0)
    f.truncate()
    f.write("pid {} since {}\n".format(os.getpid(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    f.flush()
    return f, None


def serve(port):
    home = Path(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub")
    lock, holder = take_queue_lock(home)
    hub = Hub(home)
    hub.queue_lock = {"mine": lock is not None, "holder": ("pid {}".format(os.getpid()) if lock else holder)}
    if lock is None:
        print("sb hub: {} holds {} - this hub serves read-only and starts no run".format(
            holder, home / "queue.lock"), file=sys.stderr, flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(hub))
    threading.Thread(target=refresh_loop, args=(hub,), daemon=True).start()
    supervisor = None
    if lock is not None and os.environ.get("SB_HUB_QUEUE") != "0":
        supervisor = Supervisor(hub, port=server.server_address[1])
        if (_vault() / "wayfinder").is_dir():
            supervisor.note_path = _vault() / "wayfinder" / "runs" / "hub-now.md"
        threading.Thread(target=supervisor.run, daemon=True).start()
    signal.signal(signal.SIGTERM, _interrupt)  # a stopped hub kills its workers, as Ctrl-C does
    print("sb hub on http://127.0.0.1:{}".format(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if supervisor:
            supervisor.stop()


def call(port, path, data=None, timeout=2):
    """(HTTP status, JSON body) from the hub; (0, {}) when it cannot be reached."""
    url = "http://127.0.0.1:{}{}".format(port, path)
    req = urllib.request.Request(url) if data is None else urllib.request.Request(
        url, json.dumps(data).encode("utf-8"), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        with e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}
    except (OSError, ValueError):
        return 0, {}


def cmd_report(a):
    d = {k: getattr(a, k) for k in AGENT_FIELDS if getattr(a, k, None) is not None}
    d["agent"] = a.agent
    if "project" in d:
        d["project"] = os.path.abspath(d["project"])
    call(a.port, "/api/report", d)
    return 0


def cmd_lock(a, verb):
    code, out = call(a.port, "/api/" + verb, {"key": a.key, "by": a.by})
    if code == 0:
        print("sbhub: not running", file=sys.stderr)
        return 2
    if out.get("ok"):
        print("ok")
        return 0
    print("held by {}".format(out.get("held_by", "someone")), file=sys.stderr)
    return 1


def cmd_ask(a):
    options = a.options.split("|")
    code, out = call(a.port, "/api/ask", {"agent": a.agent, "q": a.q, "options": options,
                                          "default": a.default, "wait": a.wait})
    if code != 200:
        print(a.default)
        return 0
    qid, deadline = out["id"], time.time() + a.wait
    while time.time() < deadline:
        code, q = call(a.port, "/api/question/" + qid)
        if code == 200 and q.get("answer") is not None:
            print(q["answer"])
            return 0
        if code == 0:
            break
        time.sleep(min(1, max(0, deadline - time.time())))
    code, q = call(a.port, "/api/question/" + qid)
    print(q.get("answer") if code == 200 and q.get("answer") is not None else a.default)
    return 0


def reported_agent(command):
    """X in a shell command that runs `sbhub.py report --agent X`, else None."""
    if not isinstance(command, str) or not command:
        return None
    try:
        words = shlex.split(command)
    except (ValueError, AttributeError):
        return None
    for i, w in enumerate(words):
        if w.endswith("sbhub.py") and words[i + 1:i + 2] == ["report"]:
            for j, a in enumerate(words[i + 2:], i + 2):
                if a == "--agent" and j + 1 < len(words):
                    return words[j + 1] or None
                if a.startswith("--agent="):
                    return a[len("--agent="):] or None
    return None


def session_title(transcript):
    """The title the Claude app gave a session: the last `custom-title` line near the end of its transcript."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 262144))
            tail = f.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return None
    for line in reversed(tail.splitlines()):
        if '"custom-title"' in line:
            try:
                title = json.loads(line).get("customTitle")
            except ValueError:
                continue
            if isinstance(title, str) and title.strip():
                return title.strip()[:80]
    return None


def claimed_ticket(command, vault=None):
    """The ticket a shell command claims with `sbmap.py claim <map> <NNN>`, by its title in the vault."""
    try:
        words = shlex.split(command) if isinstance(command, str) else []
    except ValueError:
        return None
    for i, w in enumerate(words):
        if w.endswith("sbmap.py") and words[i + 1:i + 2] == ["claim"] and len(words) > i + 3:
            where, num = words[i + 2], words[i + 3]
            root = Path(vault or os.environ.get("SB_VAULT") or Path.home() / "Documents" / "Second Brain")
            try:
                for f in sorted((root / "wayfinder" / where / "issues").glob(num + "*.md")):
                    title = f.stem[len(num):].strip(" -")
                    if title:
                        return title[:80]
            except OSError:
                pass
            return "{} {}".format(where, num)
    return None


def _mcp_alias(tname, tin):
    """Agent name when an MCP sb_report call reports an orchestrator (not a worker)."""
    if not (tname == "sb_report" or (tname.startswith("mcp__") and tname.endswith("__sb_report"))):
        return None
    if not isinstance(tin, dict) or tin.get("parent") or tin.get("role") == "worker":
        return None
    agent = tin.get("agent")
    return agent if isinstance(agent, str) and agent else None


def _agy_event_report(e, event):
    """The report body for one Antigravity hook event, or None if ignored."""
    cid = e.get("conversationId")
    if not isinstance(cid, str) or not cid:
        return None
    ws = e.get("workspacePaths")
    cwd = ws[0] if isinstance(ws, list) and ws and isinstance(ws[0], str) else ""
    session = {"agent": cid, "name": "{} {}".format(os.path.basename(cwd.rstrip("/")), cid[:6]),
               "project": cwd, "role": "orchestrator"} if cwd else {"agent": cid, "role": "orchestrator"}
    if event == "SessionStart":
        return {**session, "state": "idle", "note": "session started"}
    if event == "PreInvocation":
        return {**session, "state": "working", "note": "thinking"}
    if event == "PostToolUse":
        tc = e.get("toolCall") or {}
        tname = tc.get("name") or ""
        args = tc.get("args") or {}
        detail = next((args[k] for k in ("toolSummary", "CommandLine", "Path", "TargetFile", "Query",
                                         "question", "note", "Role") if args.get(k)), "")
        r = {"state": "working", "note": "{}: {}".format(tname, detail)[:90]}
        if tname == "run_command":
            alias = reported_agent(args.get("CommandLine"))
        elif tname == "call_mcp_tool" and args.get("ToolName") == "sb_report":
            alias = _mcp_alias("sb_report", args.get("Arguments"))
        else:
            alias = _mcp_alias(tname, args)
        return {**session, **r, **({"alias": alias} if alias else {})}
    if event == "Stop":
        if e.get("terminationReason") == "ERROR" or e.get("error"):
            return {**session, "state": "blocked", "note": str(e.get("error") or "error")[:90]}
        return {**session, "state": "your turn", "note": "finished its turn"}
    return None


def _tool_detail(e):
    """The tool of a PreToolUse, PostToolUse or PostToolUseFailure event and what it works on."""
    tin = e.get("tool_input") or {}
    detail = next((tin[k] for k in ("description", "file_path", "pattern", "question", "note") if tin.get(k)), "")
    return e["tool_name"].rsplit("__", 1)[-1], detail  # mcp__Server__navigate -> navigate


def event_report(e, event=None):
    """The report body for one Claude Code or Antigravity hook event, or None if ignored."""
    if event or ("conversationId" in e and "hook_event_name" not in e):
        return _agy_event_report(e, event)
    name, sid, cwd = e.get("hook_event_name"), e.get("session_id"), e.get("cwd")
    # every event of the session's own carries who it is: the hub often starts after the session did
    session = {"agent": sid, "name": "{} {}".format(os.path.basename(cwd.rstrip("/")), sid[:6]),
               "project": cwd, "role": "orchestrator"} if sid and cwd else {"agent": sid}
    if name == "SessionStart":
        return {**session, "state": "idle", "note": "session started"}
    if name == "UserPromptSubmit":
        asked = " ".join(e["prompt"].split())[:140] if isinstance(e.get("prompt"), str) else ""
        if asked.startswith(("<", "[SYSTEM", "Another Claude session")):
            asked = ""  # a subagent's hand-back or a system notice, not the owner's words
        return {**session, "state": "working", "note": "reading your message", **({"asked": asked} if asked else {}),
                "trail": {"kind": "prompt", "tool": "prompt", "label": asked}}
    if name in ("PostToolUse", "PostToolUseFailure"):
        tool, detail = _tool_detail(e)
        trail = {"kind": "post" if name == "PostToolUse" else "fail", "tool": tool, "label": detail}
        if e.get("agent_id"):
            return {"agent": e["agent_id"], "role": "worker", "parent": sid, "trail": trail}
        return {**session, "trail": trail}
    if name == "PreToolUse":
        tin = e.get("tool_input") or {}
        tool, detail = _tool_detail(e)
        r = {"state": "working", "note": ("{}: {}".format(tool, detail) if detail else tool)[:90],
             "trail": {"kind": "pre", "tool": tool, "label": detail}}
        if e.get("agent_id"):
            return {**r, "agent": e["agent_id"], "role": "worker", "parent": sid}
        tname = e["tool_name"]
        alias = reported_agent(tin.get("command")) if tname == "Bash" else _mcp_alias(tname, tin)
        ticket = claimed_ticket(tin.get("command")) if tname == "Bash" else None
        spawn = tin.get("description") if tname in ("Agent", "Task") else None
        return {**session, **r, **({"alias": alias} if alias else {}), **({"ticket": ticket} if ticket else {}),
                **({"spawn": spawn} if isinstance(spawn, str) and spawn else {})}
    if name == "Notification":
        idle = (e["notification_type"] == "idle_prompt" if "notification_type" in e
                else "waiting for your input" in e["message"])
        return {**session, "state": "your turn" if idle else "needs you", "note": e["message"]}
    if name == "Stop":
        return {**session, "state": "your turn", "note": "finished its turn",
                "trail": {"kind": "stop", "tool": "stop", "label": ""}}
    if name == "SubagentStart":
        return {"agent": e["agent_id"], "name": e["agent_type"], "role": "worker", "parent": sid,
                "state": "working", "note": "started",
                "trail": {"kind": "substart", "tool": e["agent_type"], "label": "started"}}
    if name == "SubagentStop":
        return {"agent": e["agent_id"], "role": "worker", "parent": sid, "state": "done", "note": "finished",
                "trail": {"kind": "substop", "tool": "", "label": "finished"}}
    if name == "SessionEnd":
        return {"agent": sid, "state": "gone"}
    return None


def worker_report(r, e, agent, parent):
    """A hook event of a worker the hub started (SB_HUB_AGENT=<ticket key>): the session reports as that
    queue item, a worker under `parent` whose ticket the hub fills in; its own subagents report under it;
    its end leaves the row done rather than gone."""
    if e.get("agent_id"):
        return {**r, "parent": agent}
    if r.get("state") == "gone":
        return {"agent": agent, "role": "worker", "parent": parent, "state": "done", "note": "finished"}
    mine = {k: v for k, v in r.items() if k not in ("alias", "name", "title", "spawn")}
    return {**mine, "session": r.get("agent"), "agent": agent, "role": "worker", "parent": parent}


# Claude Code events whose hook output can hand the session text, and how it does so
DELIVERS = {"UserPromptSubmit": "context", "PostToolUse": "context", "Stop": "block", "SubagentStop": "block"}


def delivery(e, messages):
    """The hook output that hands queued owner messages to the session or worker, or None."""
    name = e.get("hook_event_name")
    if not messages or name not in DELIVERS:
        return None
    text = "\n\n".join("Message from the owner, sent from the sb hub page:\n" + m for m in messages)
    if DELIVERS[name] == "block":
        return {"decision": "block", "reason": text}
    return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}


def cmd_hook(port, event=None):
    """Read one hook event on stdin, report it, and hand the session any messages queued for it.
    Whatever goes wrong, exit 0: a hook never fails a session."""
    out = None
    try:
        e = json.load(sys.stdin)
        r = event_report(e, event=event) if isinstance(e, dict) else None
        queued = os.environ.get("SB_HUB_AGENT")  # a worker the hub started for a queued ticket
        if r and queued:
            r = worker_report(r, e, queued, os.environ.get("SB_HUB_PARENT") or "queue")
        if r and r.get("role") != "worker" and not e.get("agent_id"):
            title = session_title(e.get("transcript_path"))
            if title:
                r["title"] = title
        if r:
            call(port, "/api/report", r)
        who = e.get("agent_id") or queued or e.get("session_id") if isinstance(e, dict) and not event else None
        if isinstance(who, str) and who and e.get("hook_event_name") in DELIVERS:
            code, got = call(port, "/api/take", {"agent": who, "how": e["hook_event_name"]}, timeout=1)
            msgs = got.get("messages") if code == 200 else None
            out = delivery(e, [m for m in msgs if isinstance(m, str)] if isinstance(msgs, list) else [])
    except Exception:
        pass
    if out:
        print(json.dumps(out))
    elif event:
        print("{}")
    return 0


def cmd_send(a):
    code, out = call(a.port, "/api/send", {"to": a.to, "text": a.text})
    if code == 0:
        print("sbhub: not running", file=sys.stderr)
        return 2
    if out.get("ok"):
        print(out["id"])
        return 0
    print(out.get("error", "not sent"), file=sys.stderr)
    return 1


def cmd_trust(a, yes):
    project = os.path.abspath(a.project)
    set_trusted(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub", project, yes)
    print(("trusted " if yes else "untrusted ") + project)
    return 0


def cmd_queue(a):
    port, act, rest = a.port, a.action, a.rest
    code, rows = call(port, "/api/tickets", timeout=70)  # first: it also seeds the queue
    if code == 0:
        print("sbhub: not running", file=sys.stderr)
        return 2
    q = call(port, "/api/state")[1]["queue"]
    if act == "show":
        titles = {sbqueue.key(t): t for t in rows if isinstance(rows, list) and isinstance(t, dict)}
        names = pool(q)
        print("{}{}".format("paused, " if q["paused"] else "", ("agents " if len(names) > 1 else "agent ")
                            + (", ".join(names) or "none")))
        for n, i in enumerate(q["items"], 1):
            t = titles.get(i["key"], {})
            print("{:>2}. {}  {}  {}{}".format(n, i["key"], i["state"], t.get("title", ""),
                                               "  [" + i["agent"] + "]" if i["agent"] else ""))
        for k, t in titles.items():
            if not t["queued"]:
                print("    {}  {}: {}  {}".format(k, t["state"], t["reason"], t["title"]))
        return 0
    if act in ("add", "rm"):
        if len(rest) < 2:
            print("usage: queue {} <map> <NNN>...".format(act), file=sys.stderr)
            return 1
        keys = {"{}#{}".format(rest[0], int(n)) for n in rest[1:]}
        for _ in range(QUEUE_TRIES):  # a write on a stale version is read again and tried again
            have = [i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
            want = (have + [k for k in sorted(keys) if k not in have] if act == "add"
                    else [k for k in have if k not in keys])
            code, out = call(port, "/api/queue/set", {"keys": want, "version": q["version"],
                                                      **({"agent": a.by} if act == "add" and a.by else {})})
            if not out.get("stale"):
                break
            q = out.get("queue") or call(port, "/api/state")[1]["queue"]
        if out.get("ok"):
            moved = sorted(set(want) - set(have)) if act == "add" else sorted(set(have) - set(want))
            print("{} {}".format("queued" if act == "add" else "unqueued", ", ".join(moved) or "nothing new (already so)"))
    elif act == "integrate":
        if len(rest) < 2:
            print("usage: queue integrate <map> <NNN>...", file=sys.stderr)
            return 1
        code, out = call(port, "/api/queue/integrate", {"keys": ["{}#{}".format(rest[0], int(n)) for n in rest[1:]]},
                         timeout=60)  # it reads every night it may copy a ticket from
        if out.get("ok"):
            print("queued for a Unity pass: " + ", ".join(out["queued"]))
    elif act in ("pause", "resume"):
        code, out = call(port, "/api/queue/pause", {"paused": act == "pause"})
    elif act == "job":
        prompt = a.prompt
        if a.prompt_file:
            try:
                prompt = Path(a.prompt_file).read_text(encoding="utf-8")
            except OSError as e:
                print("sbhub: cannot read the prompt file: {}".format(e), file=sys.stderr)
                return 1
        if not a.project or not prompt:
            print("usage: queue job --project P --agent A [--model M] [--name N] [--at HH:MM] (--prompt TEXT | --prompt-file F)",
                  file=sys.stderr)
            return 1
        code, out = call(port, "/api/queue/job", {"project": a.project, "prompt": prompt, "agent": a.agent, "at": a.at,
                                                  "model": a.model, "name": a.name})
        if out.get("ok"):
            print(out["key"])
    elif act == "agent" and rest:
        code, out = call(port, "/api/queue/agent", {"name": rest[0]})
    elif act == "agents" and rest:
        code, out = call(port, "/api/queue/agents", {"names": rest, "version": q["version"]})
    else:
        print("usage: queue [add|rm <map> <NNN>...|pause|resume|agent <name>|agents <name>...]", file=sys.stderr)
        return 1
    if out.get("ok"):
        return 0
    print("the queue kept changing, {} tries failed: try again".format(QUEUE_TRIES) if out.get("stale")
          else out.get("error") or "not done (hub answered {})".format(code), file=sys.stderr)
    return 1


def cmd_night(a):
    """sbhub night start [--name N] [--by SESSION] | stop [--mode after] | show"""
    if a.action == "start":
        code, out = call(a.port, "/api/night/start", {"name": a.name, "by": a.by or os.environ.get("SB_HUB_AGENT")})
    elif a.action == "stop":
        code, out = call(a.port, "/api/night/stop", {"mode": a.mode})
    elif a.action == "show":
        code, out = call(a.port, "/api/nights")
        if code == 200:
            for n in out["nights"]:
                c = n["counts"]
                print("{}  {}  {}{}  {} done, {} failed, {} skipped, {} queued, {} running, {} not reached".format(
                    n["id"], n["state"], n["name"], " (" + n["how"] + ")" if n["how"] else "", c["done"], c["failed"],
                    c["skipped"], c["queued"], c["running"], c["not_reached"]))
            return 0
    else:
        print("usage: night start|stop|show", file=sys.stderr)
        return 1
    if code == 0:
        print("sbhub: not running", file=sys.stderr)
        return 2
    if code != 200:
        print("sbhub: {}".format(out.get("error") if isinstance(out, dict) else out), file=sys.stderr)
        return 1
    n = out["night"]
    print("{} {}: {}".format(n["id"], n["state"], n["name"]))
    for x in n["not_reached"]:
        print("  not reached: {}  {}".format(x["key"], x["title"]))
    return 0


def cmd_agents(a):
    if a.scan:
        code, out = call(a.port, "/api/agents/scan", {}, timeout=30)
        found = out.get("installed", {})
    else:
        code, out = call(a.port, "/api/state")
        found = out.get("installed", {})
    if code == 0:
        print("sbhub: not running", file=sys.stderr)
        return 2
    for name, e in sorted(found.items()):
        print("{}  {}  {}  {}".format(name, e["kind"], e.get("dir") or "-", e.get("model") or "-"))
    return 0


RUN_ITEM_FIELDS = ("tries", "stops", "retry", "resume", "base_sha", "first_base", "tree", "branch", "redo", "fails")


def _hub_home():
    return Path(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub")


def _emit(obj):
    print(json.dumps(obj, indent=1), flush=True)


def _run_status_file(home, pid):
    return Path(home) / "run-ticket" / "{}.json".format(int(pid))


def _ticket_agent(hub, name):
    """(name, entry) of the agent a ticket runs on: the one named, else the queue's pool's first installed one,
    else the first installed Claude account, else plain `claude` with its default config. ValueError for a name
    that is not installed (except `claude` and `agy` themselves)."""
    installed = hub._data.get("installed") or {}
    if name:
        if name in installed:
            return name, dict(installed[name])
        if name in ("claude", "agy"):
            return name, {"kind": name, "dir": None, "model": None}
        raise ValueError("{} is not an installed agent (sbhub.py agents --scan lists them)".format(name))
    for n in pool(hub._data.get("queue") or {}) + sorted(n for n, e in installed.items() if e.get("kind") == "claude"):
        if n in installed:
            return n, dict(installed[n])
    return "claude", {"kind": "claude", "dir": None, "model": None}


def run_ticket(key, agent=None, model=None, item=None, home=None, port=None, limit=WORKER_LIMIT, hub=None,
               on_start=None):
    """Run one ticket to its end and return its result (TicketRun.result): read it, check it is ready, claim it,
    start its worker, wait (killed past `limit`), check it in code, resolve or comment, release. The hub's state
    is only read (its installed agents), never written: the queue applies the result. `item` carries an earlier
    try's fields (RUN_ITEM_FIELDS); `on_start(run)` is told once the worker runs."""
    hub = hub or Hub(home or _hub_home())
    item = {"key": key, "kind": "ticket", **{k: v for k, v in (item or {}).items() if k in RUN_ITEM_FIELDS}}
    runner = TicketRun(hub, port or default_port(), limit)
    try:
        name, inst = _ticket_agent(hub, agent)
    except ValueError as e:
        return runner.result({**item, "model": model}, "failed", "could not start: {}".format(e))
    rows = hub._fresh_tickets()
    if rows is None:
        return runner.result({**item, "model": model}, "failed", "could not start: the tickets could not be read")
    t = next((r for r in rows if sbqueue.key(r) == key), None)
    if t is None:
        return runner.result({**item, "model": model}, "skipped", "no longer open: resolved, dropped or not a ticket")
    mine = {**t, "status": "open", "claimed_by": None} if _hub_holds(t) else t
    state, reason = sbqueue.classify(mine, set(), rows)  # nothing is queued ahead of it: an open blocker blocks
    skip = "{}: {}".format(state, reason) if state != "ready" else None
    if not skip and not usable_project(t.get("repo")):
        skip = "its map's repo is not a folder here: {}".format(t.get("repo") or "none")
    item["model"] = model or (item.get("model") if item.get("tries") else None) or (
        inst.get("model") if inst.get("kind") == "agy" else None) or t.get("tier") or "sonnet"
    if skip:
        return runner.result(item, "skipped", skip, {"t": t, "agent": name, "inst": inst})
    run, res = runner.start(item, t, name, inst)
    if res is not None:
        return res
    if on_start:
        on_start(run)
    p, over = run["p"], False
    try:
        p.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        over = True
    _kill_group(p, grace=3 if over else 0)  # also whatever it left running
    res = runner.finish(item, run, over)
    if res["state"] != "landed":
        return res
    sha, checked = res["commit"], res.pop("checked")
    try:
        rv = runner.review_start([(item, run, sha)])
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {**runner.result(item, "recheck", "review could not run: could not start it: {}".format(e), run, sha,
                                res["checks"])}
    over = False
    try:
        rv["p"].wait(timeout=rv["limit"])
    except subprocess.TimeoutExpired:
        over = True
    _kill_group(rv["p"], grace=3 if over else 0)
    res = runner.review_end(item, run, sha, checked, res["checks"], rv, over)
    res.pop("checked", None)
    return res


def cmd_run_ticket(a):
    """`run-ticket`: one JSON result on stdout (exit 0 when done, 1 otherwise, 2 for a bad call); --detach, the
    child's pid and files; --status <pid>, a detached run's progress and, once it ended, its result."""
    home = _hub_home()
    if a.status is not None:
        return _run_status(home, a.status)
    if not a.key or not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)*#\d+", a.key):
        print("usage: run-ticket <map>#<num> [--agent A] [--model M] [--item JSON] [--detach] | run-ticket --status PID",
              file=sys.stderr)
        return 2
    try:
        item = json.loads(a.item) if a.item else None
        if item is not None and not isinstance(item, dict):
            raise ValueError("not an object")
    except ValueError as e:
        print("sbhub: --item is the queue item's JSON object: {}".format(e), file=sys.stderr)
        return 2
    if a.detach:
        return _run_detached(home, a)
    detached = os.environ.get("SB_RUN_DETACHED") == "1"  # a detached run notes its worker in <home>/run-ticket/<pid>.json

    def started(run):
        if detached:
            _note_status(home, os.getpid(), worker={"pid": run["p"].pid, "log": run["log"], "agent": run["agent"]})
    res = run_ticket(a.key, a.agent, a.model, item, home=home, port=a.port, limit=a.limit, on_start=started)
    _emit(res)
    return 0 if res["state"] == "done" else 1


def _run_detached(home, a):
    """Start `run-ticket` again without --detach in its own session: stdout (the result) to <stamp>.json, stderr
    to <stamp>.log under <home>/run-ticket/, and <pid>.json to find them by pid."""
    folder = home / "run-ticket"
    folder.mkdir(parents=True, exist_ok=True)
    stem = "{}-{}".format(re.sub(r"[^A-Za-z0-9._-]+", "-", a.key).strip("-"), datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    result, log = folder / (stem + ".json"), folder / (stem + ".log")
    cmd = [sys.executable, str(Path(__file__).resolve()), "run-ticket", a.key, "--port", str(a.port),
           "--limit", str(a.limit)]
    for flag, v in (("--agent", a.agent), ("--model", a.model), ("--item", a.item)):
        if v:
            cmd += [flag, v]
    with open(result, "wb") as out, open(log, "ab") as err:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
                             env={**os.environ, "SB_RUN_DETACHED": "1"})
    status = _note_status(home, p.pid, key=a.key, log=str(log), result=str(result), started=time.time(), pid=p.pid,
                          pid_start=_proc_start(p.pid))
    _emit({"pid": p.pid, "log": str(log), "result": str(result), "status": str(status)})
    return 0


def _note_status(home, of, **fields):
    """Merge `fields` into a detached run's status file (the parent writes its files, the child its worker)."""
    path = _run_status_file(home, of)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"worker": None}
    tmp = path.with_suffix(".tmp{}".format(os.getpid()))
    tmp.write_text(json.dumps({**data, **fields}), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _run_status(home, pid):
    """A detached run's progress: running (its own process is alive), its worker once started, and its result
    once it printed one."""
    path = _run_status_file(home, pid)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or "key" not in data:
        _emit({"pid": pid, "known": False, "running": False, "key": None, "log": None, "worker": None, "result": None,
               "note": "no run-ticket started with --detach has this pid"})
        return 1
    res = None
    try:
        got = json.loads(Path(data["result"]).read_text(encoding="utf-8"))
        res = got if isinstance(got, dict) and got.get("state") in RESULT_STATES else None
    except (OSError, ValueError):
        pass
    running = res is None and _Adopted(pid, data.get("pid_start")).poll() is None
    note = ("running" if running else "ended: " + res["state"] if res else
            "ended without a result: read its log")
    _emit({"pid": pid, "known": True, "running": running, "key": data["key"], "log": data["log"],
           "worker": data.get("worker"), "result": res, "note": note})
    return 0


def cmd_review_now(a):
    code, out = call(a.port, "/api/review/now", {}, timeout=70)
    if code == 0:
        print("sbhub: not running", file=sys.stderr)
        return 2
    print("review started: " + (", ".join(out.get("started") or []) or "none"))
    return 0


def cmd_state(a):
    print(json.dumps(call(a.port, "/api/state")[1]))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 0
    p = argparse.ArgumentParser(prog="sbhub.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, *args):
        sp = sub.add_parser(name)
        sp.add_argument("--port", type=int, default=default_port())
        for a in args:
            sp.add_argument(a[0], **a[1])
        return sp

    add("serve")
    add("report", ("--agent", {"required": True}),
        *[("--" + f, {}) for f in AGENT_FIELDS])
    add("lock", ("key", {}), ("--by", {"required": True}))
    add("unlock", ("key", {}), ("--by", {"required": True}))
    add("ask", ("--agent", {"required": True}), ("--q", {"required": True}),
        ("--options", {"required": True}), ("--default", {"required": True}),
        ("--wait", {"type": float, "default": 600}))
    add("state")
    add("send", ("--to", {"required": True}), ("text", {}))
    add("queue", ("action", {"nargs": "?", "default": "show"}), ("rest", {"nargs": "*"}),
        ("--project", {}), ("--agent", {}), ("--model", {}), ("--name", {}), ("--prompt", {}),
        ("--prompt-file", {}), ("--at", {}), ("--by", {}))
    add("night", ("action", {"nargs": "?", "default": "show"}), ("--name", {}), ("--by", {}),
        ("--mode", {"default": "after"}))
    add("agents", ("--scan", {"action": "store_true"}))
    add("review-now")
    add("trust", ("project", {}))
    add("untrust", ("project", {}))
    add("hook", ("--event", {}))
    add("run-ticket", ("key", {"nargs": "?"}), ("--agent", {}), ("--model", {}), ("--item", {}),
        ("--detach", {"action": "store_true"}), ("--status", {"type": int}),
        ("--limit", {"type": float, "default": WORKER_LIMIT}))
    a = p.parse_args(argv)
    if a.cmd == "serve":
        serve(a.port)
        return 0
    if a.cmd == "hook":
        return cmd_hook(a.port, event=a.event)
    if a.cmd == "report":
        return cmd_report(a)
    if a.cmd in ("lock", "unlock"):
        return cmd_lock(a, a.cmd)
    if a.cmd in ("trust", "untrust"):
        return cmd_trust(a, a.cmd == "trust")
    if a.cmd == "ask":
        return cmd_ask(a)
    if a.cmd == "send":
        return cmd_send(a)
    if a.cmd == "queue":
        return cmd_queue(a)
    if a.cmd == "night":
        return cmd_night(a)
    if a.cmd == "agents":
        return cmd_agents(a)
    if a.cmd == "review-now":
        return cmd_review_now(a)
    if a.cmd == "run-ticket":
        return cmd_run_ticket(a)
    return cmd_state(a)


if __name__ == "__main__":
    sys.exit(main())
