"""sbhub: the hub that sb sessions report to.

Hub holds the rules and the state (agents, locks, questions with defaults) and
saves them to $SB_HUB_HOME/state.json (default ~/.sb-hub/). `serve` puts it on
127.0.0.1 (port 8765, or --port, or SB_HUB_PORT); the other commands talk to it
and never fail a session when it is down.

  sbhub.py serve  [--port N]          run the hub
  sbhub.py report --agent A [--name N] [--project PATH] [--role R] [--parent A]
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
  sbhub.py hook                       read one Claude Code hook event on stdin and report it;
                                      always exits 0 (the hub-report mod runs this)

Every command but `serve` also takes --port N.

`serve` also runs tonight's queue (SB_HUB_QUEUE=0 serves the board only). A new queue waits paused until
the owner resumes it (`queue resume`); a resumed queue stays so across restarts. Every 5 s it starts the next
queued ticket whose agent and repo are free as a headless worker (`claude -p` in auto mode, or `agy -p`),
with SB_HUB_AGENT=<ticket key> and SB_HUB_PARENT=queue so `hook` reports it as that item's worker; when the
worker exits it checks the commit, paths and checks in code, and resolves the ticket only when they pass.

It paces each Claude account: workers print their account's 5-hour and weekly use (stream-json), a one-line
Haiku probe reads an idle one, and an item starts only where its learned cost fits under GATE_5H (weekly under
GATE_7D); one cut off by a limit or a logout goes back to the front for another account of the pool.
"""
import argparse
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

import sbqueue

AGENT_FIELDS = ("name", "title", "asked", "project", "role", "parent", "ticket", "state", "note", "done", "total")
ALERT_STATES = ("needs you", "blocked")
SILENT_LIMIT = 86400
ORPHAN_LOCK_LIMIT = 600
DONE_WORKER_LIMIT = 600  # a finished worker stays on its session's row this long
DECIDED_KEPT = 50
SENT_KEPT = 30  # finished messages kept for the page's log
MESSAGE_MAX = 4000


class Hub:
    def __init__(self, home, now=time.time, run=None, launcher=None):
        self.home = Path(home)
        self._run = run  # () -> the open tickets (list or JSON); sbmap when None
        self.launcher = launcher or launch  # starts one worker; tests hand in their own
        self._tcache = (0.0, None)
        self._tfailed = None  # when sbmap last failed
        self.now = now
        self._lock = threading.Lock()
        self.providers = {}
        self.queued = set()
        self.changed = threading.Event()
        self.queue_kick = threading.Event()  # set by every queue write: the supervisor ticks at once
        # aliases: session id -> the agent id that session reports as (`report --agent X`)
        self._data = {"agents": {}, "locks": {}, "questions": {}, "aliases": {}, "messages": {},
                      # a new queue waits paused until the owner resumes it: nothing runs on its own
                      "queue": {"version": 0, "seeded": False, "paused": True, "agent": None, "items": []},
                      "installed": {}}
        path = self.home / "state.json"
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            self._data.update(saved)

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
        for k in [k for k, v in agents.items() if v.get("parent") == agent]:
            del agents[k]
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
        for k, held in list(self._data["locks"].items()):
            if self._resolve(held["by"]) not in self._data["agents"] and now - held["at"] > ORPHAN_LOCK_LIMIT:
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

    def report(self, d):
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
            for f in AGENT_FIELDS:
                if d.get(f) in (None, ""):
                    continue
                if agent != sid and (f in ("name", "role") or f == "project" and f in a):
                    continue  # a session's hook events never rename the agent it reports as
                a[f] = self._resolve(d[f]) if f == "parent" else d[f]
            a["at"] = self.now()
            after = a.get("state")
            if after is not None and (after != before or "since" not in a):
                a["since"] = a["at"]  # when the agent entered its current state, for "working 14m"
            self._save()
            return {"ok": True, "needs_you": after in ALERT_STATES and after != before, "agent": agent}

    def _queue_title(self, key):
        item = next((i for i in self._data["queue"]["items"] if i["key"] == key), None)
        if item and item.get("title"):
            return item["title"]
        return next((t.get("title") for t in self._tcache[1] or [] if sbqueue.key(t) == key), None)

    def lock(self, key, by):
        with self._lock:
            held = self._data["locks"].get(key)
            if held and held["by"] != by:
                return {"ok": False, "held_by": held["by"]}
            self._data["locks"][key] = {"by": by, "at": self.now()}
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
            out = json.loads(json.dumps(self._data))
            for k, v in out["agents"].items():
                v["agent"] = k
            return {**out, "now": self.now(), "providers": dict(self.providers)}

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
            self._tfailed = None if got is not None else self.now()
        return got

    def tickets(self, run=None, fresh=False):
        """Open tickets with `state`/`reason` (sbqueue.classify) and `queued`. Reading them never ticks one:
        only the owner's own ticks queue a ticket."""
        rows = self._open_tickets(run, fresh) or []
        with self._lock:
            live = self._live_keys()
        queued = {sbqueue.key(t) for t in rows} & live
        return [{**t, "queued": sbqueue.key(t) in queued,
                 **dict(zip(("state", "reason"), sbqueue.classify(t, live, rows)))} for t in rows]

    def _live_keys(self):
        return {i["key"] for i in self._data["queue"]["items"]
                if i["kind"] == "ticket" and i["state"] in ("queued", "running")}

    @staticmethod
    def _item(key):
        return {"key": key, "kind": "ticket", "agent": None, "state": "queued", "note": "", "commit": None,
                "tries": 0, "started": None, "ended": None}

    def _apply_selection(self, q, keys, rows):
        """Queued tickets become `keys`, in run order; every other item stays where it was, in front. A
        failed or skipped ticket that is ticked again is queued afresh (a stop time or a passing error is
        no reason to keep it out); a running or done one is never queued twice."""
        want = set(keys)
        have = {i["key"]: i for i in q["items"] if i["kind"] == "ticket"}
        again = lambda i: i["kind"] == "ticket" and (
            i["state"] == "queued" or i["state"] in ("failed", "skipped") and i["key"] in want)
        keep = [i for i in q["items"] if not again(i)]
        taken = {i["key"] for i in keep if i["kind"] == "ticket"}
        keys = [k for k in dict.fromkeys(keys) if k not in taken]
        running = taken & self._live_keys()
        ordered = [k for k in sbqueue.order(rows, keys + sorted(running)) if k in keys]
        known = {sbqueue.key(t) for t in rows}
        ordered += [k for k in keys if k not in known and k in have]  # no longer listed: kept, not dropped
        q["items"] = keep + [self._afresh(have.get(k)) or self._item(k) for k in ordered]

    def _afresh(self, item):
        """A failed or skipped item queued again: its last try's outcome is cleared; the owner's agent stays."""
        if item is None or item["state"] == "queued":
            return item
        for f in ("retry", "digested", "runner", "pid", "pid_start", "result", "base_sha", "resume", "stops", "log_start"):
            item.pop(f, None)
        item.update(state="queued", note="", ended=None, tries=0, started=None, commit=None)
        return item

    def _queue_write(self, version, change, needs_tickets=False):
        """One accepted queue write: stale versions are refused, the rest bump the version once."""
        rows = []
        if needs_tickets:
            rows = self._open_tickets()
            if rows is None:
                raise ValueError("tickets unavailable")
        with self._lock:
            q = self._data["queue"]
            if version is not None and version != q["version"]:
                return {"ok": False, "stale": True, "queue": json.loads(json.dumps(q))}
            change(q, rows)
            q["version"] += 1
            self._save()
            self.queue_kick.set()
            return {"ok": True, "queue": json.loads(json.dumps(q))}

    def queue_set(self, keys, version):
        """Replace the ticket selection (jobs, running and finished items untouched)."""
        def change(q, rows):
            self._apply_selection(q, list(keys), rows)
            q["seeded"] = True
        return self._queue_write(version, change, needs_tickets=True)

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

    def queue_clear_finished(self, version):
        """Take done, failed and skipped items off the queue list; they stay in `cleared` (the page's log) and
        in the vault. Nothing running or queued is touched."""
        def change(q, rows):
            gone = [i for i in q["items"] if i["state"] in ("done", "failed", "skipped")]
            q["items"] = [i for i in q["items"] if i["state"] not in ("done", "failed", "skipped")]
            q["cleared"] = (q.get("cleared") or []) + gone
            q["cleared"] = q["cleared"][-CLEARED_KEPT:]
        return self._queue_write(version, change)

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
            item = next((i for i in q["items"] + (q.get("cleared") or []) if i["key"] == key), None)
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

    def _media_dir(self, item):
        """A ticket item's media folder, <run folder>/<num>-media, or None for a job or an item that never ran."""
        if item.get("kind") == "job" or not item.get("run") or "#" not in item["key"]:
            return None
        return Path(item["run"]) / "{}-media".format(item["key"].rsplit("#", 1)[-1])

    def media_of(self, key):
        """The sorted names of the pictures and clips a worker left for this item: known kinds, at most
        MEDIA_MAX, none over MEDIA_BYTES (the phone page forwards a file whole)."""
        with self._lock:
            item = next((i for i in self._data["queue"]["items"] if i["key"] == key), None)
        d = item and self._media_dir(item)
        if not d or not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir()
                      if p.suffix.lower() in MEDIA_TYPES and p.is_file() and p.stat().st_size <= MEDIA_BYTES)[:MEDIA_MAX]

    def media_file(self, key, name):
        """(path, content type) of one of an item's recorded media; KeyError for a name it did not record, a name
        with a path in it, or a file that now resolves outside its media folder."""
        with self._lock:
            q = self._data["queue"]
            item = next((dict(i) for i in q["items"] + (q.get("cleared") or []) if i["key"] == key), None)
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
        with self._lock:
            running = any(i["key"] == key and i["state"] == "running" for i in self._data["queue"]["items"])
        if running:
            raise ValueError("a worker is running it; wait until it ends")
        try:
            name, num, row, path = self._ticket_file(key)
        except KeyError:
            raise ValueError("no such ticket") from None
        words = " ".join(str(text or "").split())
        if action in ("done", "drop", "comment", "checks", "tier") and not words:
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
        elif action == "tier":
            calls = [["set", name, nnn, "tier=" + words]]
        else:
            calls = [["mapset", name, "checks=" + str(text).strip()]]
        for c in calls:
            rc, out, err = sbmap_call(*c)
            if rc != 0:
                raise ValueError(err or out or "sbmap failed")
        self._fresh_tickets()
        return {"ok": True}

    def queue_pause(self, paused):
        def change(q, rows):
            q["paused"] = bool(paused)
        return self._queue_write(None, change)

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

    def queue_item_agent(self, key, name):
        def change(q, rows):
            item = next((i for i in q["items"] if i["key"] == key and i["state"] == "queued"), None)
            if item is None:
                raise ValueError("not a queued item: {}".format(key))
            if name is not None and name not in self._data["installed"]:
                raise ValueError("unknown agent: {}".format(name))
            item["agent"] = name
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
        stamp, "passed" if passed else "failed: " + firstline(reason), ", commit " + sha[:9] if sha else "")]
    if not checks:
        lines.append("No check ran (the verdict stopped before the checks).")
    for c in checks:
        lines += ["", "- `{}`: {}, {} s".format(c["cmd"], "timed out" if c["code"] is None else "exit {}".format(c["code"]),
                                              c["secs"]), "", "  ```", *("  " + l for l in c["tail"].splitlines()), "  ```"]
    m = re.search(r"^## Self-checks[^\n]*\n(.*?)(?=^## |\Z)", report_text or "", re.M | re.S)
    lines += ["", "### The worker's self-checks", "", (m.group(1).strip() if m and m.group(1).strip() else "none reported"), ""]
    return "\n".join(lines)


TICKET_ACTIONS = ("done", "drop", "release", "comment", "tier", "checks")


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
AUTH_PATTERNS = ("authentication_failed", "failed to authenticate", "oauth session expired")
RESUME = ("\n## An earlier try stopped\n\nAn earlier try on {agent} stopped {why}. Its changes may already be in "
          "the tree, committed or not: read `git log {base}..HEAD` and {diff} first, continue from there, do not "
          "redo finished work. Its log: {log}.\n")


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


def launch(agent, brief, repo, model, env, log):
    """Start one headless worker and return its Popen: the only place that knows the agents' commands.
    Own process group, cwd the ticket's repo, stdout and stderr to `log`; `env` adds the hub's ids."""
    full = {**os.environ, **env}
    if agent.get("kind") == "agy":
        cmd = [_exe("agy", full), "-p", brief] + (["--model", model] if model else []) + ["--output-format", "json"]
    else:
        if agent.get("dir"):
            full["CLAUDE_CONFIG_DIR"] = agent["dir"]
        cmd = [_exe("claude", full), "-p", brief, "--permission-mode", "auto", "--model", model,
               "--output-format", "stream-json", "--verbose"]  # stream-json carries the account's usage
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        return subprocess.Popen(cmd, cwd=repo, env=full, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)


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


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


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


class Supervisor:
    """Runs tonight's queue, one pass per `tick()` (every TICK_EVERY s from `serve`; tests call it).

    It owns each item's state from its worker's process and the verdict checked in code: nothing waits on
    a worker reaching the hub. Every state change happens under the hub's lock; sbmap, git and the workers
    run outside it. The workers' Popen handles live here, in memory: a `running` item with none (the hub
    restarted) has its leftover process group killed, its claim released, and is queued again."""

    def __init__(self, hub, port=None, limit=WORKER_LIMIT, probe=None):
        self.hub, self.port, self.limit = hub, port or default_port(), limit
        self.probe = probe or probe_usage  # (agent entry, cwd) -> its output; tests hand in their own
        self.probe_async, self.probing = True, []  # probes run in their own thread (tests may run them inline)
        self.close_off = True  # the daily morning close-off job (tests of other things turn it off)
        # item key -> {p, t (the ticket row it started from), agent, inst, base, log, start, pos (log read up to),
        # u0/u1 (its first and newest usage reading), alone (no other worker on its agent overlapped it), braked}
        self.procs = {}
        self.streak = (None, 0)  # the failure class of the last failed items in a row, and how many
        self.stopped = False

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

    def sbmap(self, *args):
        try:
            r = subprocess.run([sys.executable, str(SBMAP), *args], capture_output=True, text=True,
                               errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            return 1, "", str(e)
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def tick(self):
        self.hub.tickets()  # keeps the page's ticket cache fresh and seeds the queue (both cached)
        self._watch()
        self._reap()
        self._final_review()
        self._close_off()
        if not self.stopped:
            self._probe()
            self._start()
        self._digest()

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

    def _update(self, key, front=False, **fields):
        """Change one item; `front` puts it first among the queued ones."""
        with self.hub._lock:
            q = self.hub._data["queue"]
            item = next((i for i in q["items"] if i["key"] == key), None)
            if item is None:
                return
            item.update(fields)
            if front:
                q["items"].remove(item)
                at = next((n for n, i in enumerate(q["items"]) if i["state"] == "queued"), len(q["items"]))
                q["items"].insert(at, item)
            q["version"] += 1
            self.hub._save()

    def _end(self, key, state, **fields):
        if state in ("done", "failed"):
            fields.setdefault("media", self.hub.media_of(key))
        self._update(key, state=state, ended=self.hub.now(), pid=None, pid_start=None, **fields)

    def _row(self, key):
        """(found, row): the ticket read now; found is False when sbmap could not be read."""
        rows = self.hub._fresh_tickets()
        if rows is None:
            return False, None
        return True, next((t for t in rows if sbqueue.key(t) == key), None)

    def _release(self, key):
        """Reopen the ticket when the hub holds its claim (`hub <agent>`); a session's claim, or a ticket
        resolved meanwhile, is left alone."""
        found, t = self._row(key)
        if _hub_holds(t):
            self.sbmap("set", t["map"], "{:03d}".format(int(t["num"])), "status=open")

    # ---- workers that ended, ran too long, or were lost with a restart ----

    def _reap(self):
        with self.hub._lock:
            running = [dict(i) for i in self.hub._data["queue"]["items"]
                       if i["state"] == "running"]
        for item in running:
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
                    self._fail(item, run, why, None)
            with self.hub._lock:
                now_item = next((i for i in self.hub._data["queue"]["items"] if i["key"] == item["key"]), {})
            if now_item.get("state") == "done":  # only finished work says what an item costs
                self._learn(run, item.get("model") or "sonnet")

    def _stopped(self, item, run):
        """True when this try's own output shows a logout or a usage limit (a rejected window's exact reset,
        else the reset its message names); the item is then queued again (see _stopped_early)."""
        text, now = _tail(run["log"], run.get("start", 0)), self.hub.now()
        said = _said(text)
        auth = run.get("auth") or logged_out(said)
        rejected = next((r for u, r in reversed(readings(text)) if r and r > now), None)
        until = None if auth else rejected or limited_until(said, now)
        if not auth and until is None:
            return False
        self._stopped_early(item, run, until, auth)
        return True

    def _stopped_early(self, item, run, until, auth):
        """The worker stopped at its agent's usage limit or a logout: the agent waits (limited until `until`, or
        signed out), the claim is released, and the item goes back to the front of the queue for any agent of
        the pool that fits, keeping its base commit; its next brief says where the last try stopped."""
        run["stopped"] = True
        stops = (item.get("stops") or 0) + 1
        if until is not None:
            with self.hub._lock:
                inst = self.hub._data["installed"].get(run["agent"])
                if inst is not None:
                    inst["limited_until"] = until
                self.hub._save()
        if auth:
            self._signed_out(run["agent"])
        why = "when its login expired" if auth else "at its usage limit"
        if stops >= STOPS_MAX:  # something keeps cutting it off: the owner looks rather than the queue looping
            reason = "stopped {} times at a usage limit or a logout (the last on {}, {}); not tried again".format(
                stops, run["agent"], why)
            if item["kind"] == "ticket":
                self._fail(item, run, reason, None)
            else:
                self._end(item["key"], "failed", note=reason)
            return
        if item["kind"] == "ticket":
            self._release(item["key"])
        self._update(item["key"], front=True, state="queued", pid=None, pid_start=None, started=None, stops=stops,
                     resume={"agent": run["agent"], "log": run["log"], "why": why},
                     note="{} stopped {}{}; queued again at the front".format(
                         run["agent"], why, "" if auth else " (until {})".format(_hm(until))))

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
                                       "log": item.get("log"), "start": item.get("log_start") or 0, "alone": False}
            self._update(item["key"], note="running on {}, started before the hub restarted".format(item.get("runner")))
            return
        if item["kind"] == "ticket":
            self._release(item["key"])
        self._update(item["key"], state="queued", pid=None, pid_start=None, started=None,
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
        t = run["t"]
        if over:
            passed, reason, sha = False, ran_past(self.limit), None
        else:
            checks = []
            passed, reason, sha = sbqueue.verdict(t, t["repo"], run["base"], run=_recording(checks))
            self._update(key, checks=checks)
            self._report_checks(t, run, passed, reason, sha, checks)
        if passed:  # a worker that did the work is resolved, whatever it printed afterwards
            self._resolve(item, run, sha)
            return
        # a failed run whose own output (not an earlier try's) names a usage limit or a logout is tried again
        if not over and self._stopped(item, run):
            return
        if not item.get("tries") and t.get("tier", "sonnet") == "sonnet" and run["inst"].get("kind") == "claude":
            self._release(key)
            self._update(key, front=True, state="queued", tries=1, model="opus", retry=reason, commit=sha,
                          pid=None, pid_start=None, started=None,
                          note="retrying on opus: " + reason.splitlines()[0])
            return
        self._fail(item, run, reason, sha)

    def _report_checks(self, t, run, passed, reason, sha, checks):
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

    def _resolve(self, item, run, sha):
        key, t = item["key"], run["t"]
        found, now_t = self._row(key)
        if found and not _hub_holds(now_t):
            self._end(key, "skipped", commit=sha, note="passed its checks, but the ticket changed while it ran ({})".format(
                "no longer open" if now_t is None else "claimed by " + str(now_t.get("claimed_by"))))
            return
        checks = "; ".join("`{}`".format(c) for c in t["checks"])
        answer = ("Checked by the sb hub in code: commit {} carries `Ticket: {}/{:03d}`, stays inside the ticket's "
                  "paths, and every check exited 0 ({n} of {n}): {}. Model: {} on agent {} (try {}). "
                  "Worker's report: {}/{}.md; its log: {}.").format(
            sha, t["map"], int(t["num"]), checks, item.get("model"), run["agent"], (item.get("tries") or 0) + 1,
            Path(run["log"]).parent, int(t["num"]), run["log"], n=len(t["checks"]))
        nnn = "{:03d}".format(int(t["num"]))
        rc, out, err = self.sbmap("resolve", t["map"], nnn, "--gist", t["title"], "--answer", answer,
                                  "--commit", sha, "--repo-root", t["repo"])
        if rc != 0 and "remote" in err:  # sbmap stamps a commit only in a repo with an origin: name it in the gist
            rc, out, err = self.sbmap("resolve", t["map"], nnn, "--gist", "{} ({})".format(t["title"], sha[:9]),
                                      "--answer", answer)
        if rc != 0:
            self._fail(item, run, "checks passed, but sbmap resolve failed: " + (err or out), sha)
            return
        self.streak = (None, 0)
        self._end(key, "done", commit=sha, note="resolved, commit " + sha[:9])

    def _fail(self, item, run, reason, sha):
        """Leave the ticket open with the reason as a comment, release the claim, and count the failure."""
        key, t = item["key"], run["t"]
        text = "The sb hub's run of this ticket failed ({} on agent {}): {}{}".format(
            item.get("model"), run["agent"], reason.replace("\n", "\n  "),
            "\n  The commit {} is left in place.".format(sha[:9]) if sha else "")
        self.sbmap("comment", t["map"], "{:03d}".format(int(t["num"])), "--text", text)
        self._release(key)
        self._end(key, "failed", commit=sha, note=reason[:2000])
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

    def _finish_job(self, item, run, over):
        """A job has no claim, verdict or retry: exit 0 is done, anything else failed, except a usage limit,
        which queues it again for the agent's reset. Its result text is saved in its run folder."""
        key, code = item["key"], run["p"].returncode
        text = _tail(run["log"], run.get("start", 0))
        if run.get("adopted"):  # not this hub's child: its exit code is lost, its result line says how it went
            code = 0 if _result_ok(text) else 1
        if not over and code != 0 and self._stopped(item, run):
            return
        result = Path(run["log"]).parent / "result.md"
        result.write_text(_job_result(text) + "\n", encoding="utf-8")
        if over:
            self._end(key, "failed", result=str(result), note=ran_past(self.limit))
        elif code == 0:
            self._end(key, "done", result=str(result), note="done; result in " + str(result.parent))
        else:
            self._end(key, "failed", result=str(result), note="the worker exited {}".format(code))

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
            if any(i["kind"] == "ticket" and i["state"] in ("queued", "running") for i in q["items"]):
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
        answered) an agent runs one worker; measured agents rank first, then by the room left after it."""
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
        if n == 0 and five < IDLE_FLOOR:
            return (1, room), need, ""  # an idle, nearly empty account is never left waiting
        if room < -1e-9:
            return None, need, "{} {} used{}, needs about {}; resets {}".format(
                name, _pct(five), ", {} more held by its running work".format(_pct(owed)) if owed >= 0.005 else "",
                _pct(need), _hm(resets))
        return (1, room), need, ""

    def _pick(self, q, item, t, load, now):
        """(agent, its entry, need) for the agent the item fits on with the most room left (ties: pool order),
        or (None, None, why): why is a note naming each agent's use and reset when usage alone stops it,
        empty when an agent is only busy. An item's own agent wins and never falls back to the pool."""
        names = [item["agent"]] if item.get("agent") else pool(q)
        model = item.get("model") if item.get("tries") or item["kind"] == "job" else (t or {}).get("tier")
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

    def _start(self):
        now = self.hub.now()
        with self.hub._lock:
            q = self.hub._data["queue"]
            if q.get("stop_at") and now >= q["stop_at"]:  # also what waits for an agent's reset
                waiting = [i for i in q["items"] if i["state"] == "queued"]
                for i in waiting:
                    i.update(state="skipped", note="past the stop time", ended=now)
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
        picks = []
        with self.hub._lock:
            q = self.hub._data["queue"]
            if q["paused"]:
                return
            live = self.hub._live_keys()
            running = [i for i in q["items"] if i["state"] == "running"]
            load, repos = self._load(running), {i.get("repo") for i in running}
            changed = False

            def take(name, need):  # what this pass started counts against its agent at once
                l = load.setdefault(name, [0, 0.0])
                l[0] += 1
                l[1] += need
            for item in q["items"]:
                if item["state"] != "queued" or (item.get("not_before") or 0) > now:
                    continue
                if item["kind"] == "job":
                    if item.get("repo") in repos:
                        continue
                    name, inst, need = self._pick(q, item, None, load, now)
                    if name is None:
                        if item.get("resume"):  # its last try's work is in the tree: nothing else goes first
                            repos.add(item.get("repo"))
                        continue
                    item.update(state="running", runner=name, started=now, ended=None, note="starting")
                    take(name, need)
                    repos.add(item.get("repo"))
                    picks.append((dict(item), None, name, dict(inst)))
                    changed = True
                    continue
                t = by.get(item["key"])
                if t is not None and t.get("repo") in repos:
                    continue  # its repo is busy: it is not about to start, so it is not judged yet
                name, inst, need = self._pick(q, item, t, load, now)
                if name is None:
                    if item.get("resume") and t is not None:  # its last try's work is in the tree: nothing else goes first
                        repos.add(t.get("repo"))
                    continue  # no agent has room for it now (the first pass noted why)
                skip = None
                if t is None:
                    skip = "no longer open: resolved or out of scope since it was queued"
                else:
                    # the hub's own claim left by a release that failed is no claim against its own queued item
                    mine = {**t, "status": "open", "claimed_by": None} if _hub_holds(t) else t
                    state, reason = sbqueue.classify(mine, live, rows)
                    if state != "ready":
                        skip = "{}: {}".format(state, reason)
                    elif not usable_project(t.get("repo")):
                        skip = "its map's repo is not a folder here: {}".format(t.get("repo") or "none")
                if skip:
                    item.update(state="skipped", note=skip, ended=now, **({"title": t["title"]} if t else {}))
                    changed = True
                    continue
                if t["blocked_by_open"]:
                    continue  # its blockers are queued ahead of it: it waits for them
                model = (item.get("model") if item.get("tries") else
                         inst.get("model") if inst.get("kind") == "agy" else t.get("tier") or "sonnet")
                item.update(state="running", runner=name, repo=t["repo"], map=t["map"], title=t["title"],
                            model=model, started=now, ended=None, note="starting")
                take(name, need)
                repos.add(t["repo"])
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
        key, nnn = item["key"], "{:03d}".format(int(t["num"]))
        board = self._board(t["map"])
        # a try after one cut off by a limit or a logout keeps its base: the verdict sees all of the ticket's commits
        base = item.get("resume") and item.get("base_sha") or _git(t["repo"], "rev-parse", "HEAD")
        if board is None or not base:
            self._end(key, "failed", note="could not start: " + ("sbmap run failed" if board is None else
                                                                 "the repo has no commit to start from"))
            return
        if _hub_holds(t):  # a claim of the hub's own left from an earlier try: reopened, then claimed afresh
            self.sbmap("set", t["map"], nnn, "status=open")
        rc, out, err = self.sbmap("claim", t["map"], nnn, "--by", "hub " + name)
        if rc != 0:
            self._end(key, "skipped", note="could not claim it: " + (err or out))
            return
        with self.hub._lock:  # the night's first base of each repo, for the final review
            self.hub._data["queue"].setdefault("bases", {}).setdefault(
                t["repo"], {"sha": base, "project": _project_of(t["map"])})
            self.hub._save()
        folder = Path(board).parent
        brief = sbqueue.brief(t, _plain_words(t), str(folder), t["repo"],
                              _git(t["repo"], "rev-parse", "--abbrev-ref", "HEAD") or "the current branch")
        if item.get("retry"):
            brief += "\nThe first try failed; the hub's check said:\n" + item["retry"] + "\n"
        log = str(folder / "{}.log".format(int(t["num"])))
        if item.get("resume"):
            r, paths = item["resume"], " ".join(t.get("paths") or [])
            brief += RESUME.format(agent=r["agent"], why=r["why"], base=base, log=r.get("log") or log,
                                   diff="`git diff -- {}`".format(paths) if paths else "`git diff`")
        env = {"SB_HUB_AGENT": key, "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.port)}
        try:
            start = os.path.getsize(log)  # launch appends: this try's output begins here
        except OSError:
            start = 0
        try:
            if self.stopped:
                raise OSError("the hub is stopping")
            p = self.hub.launcher(inst, brief, t["repo"], item["model"], env, log)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            self._release(key)
            self._end(key, "failed", note="could not start the worker: {}".format(e))
            return
        self._track(key, {"p": p, "t": t, "agent": name, "inst": inst, "base": base, "log": log, "start": start})
        self._update(key, base_sha=base, log=log, log_start=start, run=str(folder), pid=p.pid, pid_start=_proc_start(p.pid),
                     note="running on {} ({})".format(name, item["model"]))

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
        env = {"SB_HUB_AGENT": key, "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.port)}
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
            if any(i["state"] in ("queued", "running") for i in tickets):
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
            r = subprocess.run([str(f)], capture_output=True, text=True, errors="replace", timeout=timeout,
                               cwd=project)
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
PAGE = Path(__file__).resolve().parent / "sbhub.html"
BOARD_JS = Path(__file__).resolve().parent / "sbhub_board.js"  # the page's renderer


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
            if path == "/":
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/board.js":
                self.send(200, BOARD_JS.read_bytes(), "text/javascript; charset=utf-8")
            elif path == "/api/state":
                self.send(200, hub.state())
            elif path == "/api/tickets":
                self.send(200, hub.tickets())
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
                try:
                    self.send_file(*hub.media_file((qs.get("key") or [""])[0], (qs.get("name") or [""])[0]))
                except (KeyError, OSError):
                    self.send(404, b"", "text/plain")
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
                    out = hub.queue_set(d["keys"], d["version"])
                elif path == "/api/queue/move":
                    out = hub.queue_move(d["key"], d["to"], d["version"])
                elif path == "/api/queue/pause":
                    out = hub.queue_pause(d["paused"])
                elif path == "/api/queue/agent":
                    out = hub.queue_agent(d["name"])
                elif path == "/api/queue/agents":
                    out = hub.queue_agents(d["names"], d["version"])
                elif path == "/api/queue/options":
                    out = hub.queue_options(d.get("stop_at"), d.get("final_review", False), d["version"])
                elif path == "/api/queue/job":
                    out = hub.queue_job(d["project"], d["prompt"], d.get("agent"), d.get("model"), d.get("name"),
                                        d.get("at") or None)
                elif path == "/api/queue/remove_job":
                    out = hub.queue_remove_job(d["key"], d["version"])
                elif path == "/api/queue/clear-finished":
                    out = hub.queue_clear_finished(d.get("version"))
                elif path == "/api/agents/dismiss":
                    out = hub.agents_dismiss(d["agent"])
                elif path == "/api/agents/clear-quiet":
                    out = hub.agents_clear_quiet()
                elif path.startswith("/api/ticket/") and path[len("/api/ticket/"):] in TICKET_ACTIONS:
                    out = hub.ticket_action(path[len("/api/ticket/"):], d["key"], d.get("text"), d.get("commit"))
                elif path == "/api/queue/item_agent":
                    out = hub.queue_item_agent(d["key"], d.get("name"))
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


def serve(port):
    home = Path(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub")
    hub = Hub(home)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(hub))
    threading.Thread(target=refresh_loop, args=(hub,), daemon=True).start()
    supervisor = None
    if os.environ.get("SB_HUB_QUEUE") != "0":
        supervisor = Supervisor(hub, port=server.server_address[1])
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
        return {**session, "state": "working", "note": "reading your message", **({"asked": asked} if asked else {})}
    if name == "PreToolUse":
        tin = e.get("tool_input") or {}
        detail = next((tin[k] for k in ("description", "file_path", "pattern", "question", "note") if tin.get(k)), "")
        tool = e["tool_name"].rsplit("__", 1)[-1]  # mcp__Server__navigate -> navigate
        r = {"state": "working", "note": ("{}: {}".format(tool, detail) if detail else tool)[:90]}
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
        return {**session, "state": "your turn", "note": "finished its turn"}
    if name == "SubagentStart":
        return {"agent": e["agent_id"], "name": e["agent_type"], "role": "worker", "parent": sid,
                "state": "working", "note": "started"}
    if name == "SubagentStop":
        return {"agent": e["agent_id"], "role": "worker", "parent": sid, "state": "done", "note": "finished"}
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
    return {**mine, "agent": agent, "role": "worker", "parent": parent}


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
        have = [i["key"] for i in q["items"] if i["kind"] == "ticket" and i["state"] == "queued"]
        want = have + [k for k in sorted(keys) if k not in have] if act == "add" else [k for k in have if k not in keys]
        code, out = call(port, "/api/queue/set", {"keys": want, "version": q["version"]})
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
    print("the queue changed meanwhile, try again" if out.get("stale") else out.get("error", "not done"), file=sys.stderr)
    return 1


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
        ("--prompt-file", {}), ("--at", {}))
    add("agents", ("--scan", {"action": "store_true"}))
    add("trust", ("project", {}))
    add("untrust", ("project", {}))
    add("hook", ("--event", {}))
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
    if a.cmd == "agents":
        return cmd_agents(a)
    return cmd_state(a)


if __name__ == "__main__":
    sys.exit(main())
