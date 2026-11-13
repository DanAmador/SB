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
  sbhub.py queue agent <name>         the agent that runs the night's items (an installed one)
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
"""
import argparse
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
        self._seed_queue(fetch=False)  # never waits on sbmap: it reads the cache
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
        got = self._fetch(run)
        with self._lock:
            if got is not None:
                self._tcache = (self.now(), got)
            self._tfailed = None if got is not None else self.now()
            return got if got is not None else self._tcache[1]

    def _fresh_tickets(self):
        """The open tickets read now, which also refreshes the cache; None when sbmap failed (never the cache)."""
        got = self._fetch()
        with self._lock:
            if got is not None:
                self._tcache = (self.now(), got)
            self._tfailed = None if got is not None else self.now()
        return got

    def tickets(self, run=None, fresh=False):
        """Open tickets with `state`/`reason` (sbqueue.classify) and `queued`."""
        self._seed_queue(run)
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

    def _seed_queue(self, run=None, fetch=True):
        """The first time the tickets can be read, tick every ready one; the owner unticks."""
        if self._data["queue"]["seeded"]:
            return
        if fetch:
            rows = self._open_tickets(run)
        else:
            with self._lock:
                rows = self._tcache[1]
        if not rows:
            return
        with self._lock:
            q = self._data["queue"]
            if q["seeded"]:
                return
            ready = [sbqueue.key(t) for t in rows if sbqueue.classify(t, set(), rows)[0] == "ready"]
            self._apply_selection(q, ready, rows)
            q["seeded"] = True
            q["paused"] = True  # the first seed ticks tonight's tickets; they wait for the owner's resume
            q["version"] += 1
            self._save()

    def _apply_selection(self, q, keys, rows):
        """Queued tickets become `keys`, in run order; every other item stays where it was, in front."""
        have = {i["key"]: i for i in q["items"] if i["kind"] == "ticket"}
        keep = [i for i in q["items"] if not (i["kind"] == "ticket" and i["state"] == "queued")]
        taken = {i["key"] for i in keep if i["kind"] == "ticket"}
        keys = [k for k in dict.fromkeys(keys) if k not in taken]
        running = taken & self._live_keys()
        ordered = [k for k in sbqueue.order(rows, keys + sorted(running)) if k in keys]
        known = {sbqueue.key(t) for t in rows}
        ordered += [k for k in keys if k not in known and k in have]  # no longer listed: kept, not dropped
        q["items"] = keep + [have.get(k) or self._item(k) for k in ordered]

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

    def queue_pause(self, paused):
        def change(q, rows):
            q["paused"] = bool(paused)
        return self._queue_write(None, change)

    def queue_agent(self, name):
        """The agent that runs tonight's items unless an item names its own."""
        def change(q, rows):
            if name not in self._data["installed"]:
                raise ValueError("unknown agent: {}".format(name))
            q["agent"] = name
        return self._queue_write(None, change)

    def queue_item_agent(self, key, name):
        def change(q, rows):
            item = next((i for i in q["items"] if i["key"] == key and i["state"] == "queued"), None)
            if item is None:
                raise ValueError("not a queued item: {}".format(key))
            if name is not None and name not in self._data["installed"]:
                raise ValueError("unknown agent: {}".format(name))
            item["agent"] = name
        return self._queue_write(None, change)

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
               "--output-format", "json"]
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


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _tail(path, size=LOG_TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - size))
            return f.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return ""


def _vault():
    return Path(os.environ.get("SB_VAULT") or Path.home() / "Documents" / "Second Brain")


def _plain_words(t):
    """The map's `## In plain words`, read from the map.md beside the ticket's issues/ folder."""
    try:
        body = (Path(t["file"]).parents[1] / "map.md").read_text(encoding="utf-8")
    except (OSError, KeyError, IndexError, TypeError):
        body = ""
    m = re.search(r"^## In plain words\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return (m.group(1).strip() if m else "") or t.get("map_title") or t["map"]


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

    def __init__(self, hub, port=None, limit=WORKER_LIMIT):
        self.hub, self.port, self.limit = hub, port or default_port(), limit
        self.procs = {}  # item key -> {p, t (the ticket row it started from), agent, inst, base, log}
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
        for run in list(self.procs.values()):
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
        self._reap()
        if not self.stopped:
            self._start()
        self._digest()

    # ---- state, always under the hub's lock ----

    def _update(self, key, front=False, **fields):
        """Change one ticket item; `front` puts it first among the queued ones."""
        with self.hub._lock:
            q = self.hub._data["queue"]
            item = next((i for i in q["items"] if i["key"] == key and i["kind"] == "ticket"), None)
            if item is None:
                return
            item.update(fields)
            if front:
                q["items"].remove(item)
                at = next((n for n, i in enumerate(q["items"]) if i["kind"] == "ticket" and i["state"] == "queued"),
                          len(q["items"]))
                q["items"].insert(at, item)
            q["version"] += 1
            self.hub._save()

    def _end(self, key, state, **fields):
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
        if t and t["status"] == "claimed" and str(t.get("claimed_by") or "").startswith("hub "):
            self.sbmap("set", t["map"], "{:03d}".format(int(t["num"])), "status=open")

    # ---- workers that ended, ran too long, or were lost with a restart ----

    def _reap(self):
        with self.hub._lock:
            running = [dict(i) for i in self.hub._data["queue"]["items"]
                       if i["kind"] == "ticket" and i["state"] == "running"]
        for item in running:
            run = self.procs.get(item["key"])
            if run is None:
                self._recover(item)
                continue
            ended = run["p"].poll() is not None
            over = not ended and self.hub.now() - (item.get("started") or self.hub.now()) > self.limit
            if not (ended or over):
                continue
            _kill_group(run["p"], grace=3 if over else 0)  # also whatever it left running
            del self.procs[item["key"]]
            try:
                self._finish(item, run, over)
            except Exception as e:  # the item still ends, never resolved
                self._fail(item, run, "the hub could not check it: {}: {}".format(type(e).__name__, e), None)

    def _recover(self, item):
        pid, started = item.get("pid"), item.get("pid_start")
        if pid and started and _proc_start(pid) == started:  # the same worker outlived its hub
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        self._release(item["key"])
        self._update(item["key"], state="queued", pid=None, pid_start=None, started=None,
                     note="queued again: the hub stopped while it ran")

    def _finish(self, item, run, over):
        key, t = item["key"], run["t"]
        until = None if over else limited_until(_tail(run["log"]), self.hub.now())
        if until is not None:
            with self.hub._lock:
                inst = self.hub._data["installed"].get(run["agent"])
                if inst is not None:
                    inst["limited_until"] = until
                self.hub._save()
            self._release(key)
            self._update(key, state="queued", pid=None, pid_start=None, started=None,
                         note="{} hit its usage limit; waits until {}".format(
                             run["agent"], datetime.fromtimestamp(until).strftime("%H:%M")))
            return
        if over:
            passed, reason, sha = False, ran_past(self.limit), None
        else:
            passed, reason, sha = sbqueue.verdict(t, t["repo"], run["base"])
        if passed:
            self._resolve(item, run, sha)
            return
        if not over and not item.get("tries") and t.get("tier", "sonnet") == "sonnet" and run["inst"].get("kind") == "claude":
            self._release(key)
            self._update(key, front=True, state="queued", tries=1, model="opus", retry=reason, commit=sha,
                          pid=None, pid_start=None, started=None,
                          note="retrying on opus: " + reason.splitlines()[0])
            return
        self._fail(item, run, reason, sha)

    def _resolve(self, item, run, sha):
        key, t = item["key"], run["t"]
        found, now_t = self._row(key)
        if found and not (now_t and now_t["status"] == "claimed" and str(now_t.get("claimed_by") or "").startswith("hub ")):
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

    # ---- starting the next tickets ----

    def _free_agent(self, q, item, busy, now):
        name = item.get("agent") or q["agent"]
        inst = self.hub._data["installed"].get(name)
        if inst is None or name in busy or (inst.get("limited_until") or 0) > now:
            return None, None
        return name, inst

    def _start(self):
        now = self.hub.now()
        with self.hub._lock:
            q = self.hub._data["queue"]
            busy = {i.get("runner") for i in q["items"] if i["kind"] == "ticket" and i["state"] == "running"}
            if q["paused"] or not any(i["kind"] == "ticket" and i["state"] == "queued"
                                      and self._free_agent(q, i, busy, now)[0] for i in q["items"]):
                return  # nothing could start: no need to read the tickets
        rows = self.hub._fresh_tickets()  # re-read just before starting: the vault may have changed
        if rows is None:
            return
        by = {sbqueue.key(t): t for t in rows}
        picks = []
        with self.hub._lock:
            q = self.hub._data["queue"]
            if q["paused"]:
                return
            live = self.hub._live_keys()
            running = [i for i in q["items"] if i["kind"] == "ticket" and i["state"] == "running"]
            busy, repos = {i.get("runner") for i in running}, {i.get("repo") for i in running}
            changed = False
            for item in q["items"]:
                if item["kind"] != "ticket" or item["state"] != "queued":
                    continue
                t = by.get(item["key"])
                name, inst = self._free_agent(q, item, busy, now)
                if name is None or t is not None and t.get("repo") in repos:
                    continue  # its agent or its repo is busy: it is not about to start, so it is not judged yet
                skip = None
                if t is None:
                    skip = "no longer open: resolved or out of scope since it was queued"
                else:
                    state, reason = sbqueue.classify(t, live, rows)
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
                busy.add(name)
                repos.add(t["repo"])
                picks.append((dict(item), t, name, dict(inst)))
                changed = True
            if changed:
                q["version"] += 1
                self.hub._save()
        for item, t, name, inst in picks:
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

    def _launch(self, item, t, name, inst):
        key, nnn = item["key"], "{:03d}".format(int(t["num"]))
        board = self._board(t["map"])
        base = _git(t["repo"], "rev-parse", "HEAD")
        if board is None or not base:
            self._end(key, "failed", note="could not start: " + ("sbmap run failed" if board is None else
                                                                 "the repo has no commit to start from"))
            return
        rc, out, err = self.sbmap("claim", t["map"], nnn, "--by", "hub " + name)
        if rc != 0:
            self._end(key, "skipped", note="could not claim it: " + (err or out))
            return
        folder = Path(board).parent
        brief = sbqueue.brief(t, _plain_words(t), str(folder), t["repo"],
                              _git(t["repo"], "rev-parse", "--abbrev-ref", "HEAD") or "the current branch")
        if item.get("retry"):
            brief += "\nThe first try failed; the hub's check said:\n" + item["retry"] + "\n"
        log = str(folder / "{}.log".format(int(t["num"])))
        env = {"SB_HUB_AGENT": key, "SB_HUB_PARENT": "queue", "SB_HUB_PORT": str(self.port)}
        try:
            if self.stopped:
                raise OSError("the hub is stopping")
            p = self.hub.launcher(inst, brief, t["repo"], item["model"], env, log)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            self._release(key)
            self._end(key, "failed", note="could not start the worker: {}".format(e))
            return
        self.procs[key] = {"p": p, "t": t, "agent": name, "inst": inst, "base": base, "log": log}
        self._update(key, base_sha=base, log=log, run=str(folder), pid=p.pid, pid_start=_proc_start(p.pid),
                     note="running on {} ({})".format(name, item["model"]))

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
BOARD_JS = Path(__file__).resolve().parent / "sbhub_board.js"  # the page's renderer, shared with the chat widget


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

        def send(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
        print("{}{}".format("paused, " if q["paused"] else "", "agent " + (q["agent"] or "none")))
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
    elif act == "agent" and rest:
        code, out = call(port, "/api/queue/agent", {"name": rest[0]})
    else:
        print("usage: queue [add|rm <map> <NNN>...|pause|resume|agent <name>]", file=sys.stderr)
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
    add("queue", ("action", {"nargs": "?", "default": "show"}), ("rest", {"nargs": "*"}))
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
