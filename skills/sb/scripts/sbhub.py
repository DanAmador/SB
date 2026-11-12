"""sbhub: the hub that sb sessions report to.

Hub holds the rules and the state (agents, locks, questions with defaults) and
saves them to $SB_HUB_HOME/state.json. It knows nothing of HTTP or argv; the
server and CLI sit on top of it.
"""
import json
import os
import threading
import time
import uuid
from pathlib import Path

AGENT_FIELDS = ("name", "project", "role", "parent", "ticket", "state", "note", "done", "total")
ALERT_STATES = ("needs you", "blocked")
SILENT_LIMIT = 86400


class Hub:
    def __init__(self, home, now=time.time):
        self.home = Path(home)
        self.now = now
        self._lock = threading.Lock()
        self._data = {"agents": {}, "locks": {}, "questions": {}}
        path = self.home / "state.json"
        if path.exists():
            self._data.update(json.loads(path.read_text(encoding="utf-8")))

    def _save(self):
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.home / "state.json.tmp"
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        os.replace(tmp, self.home / "state.json")

    def _remove(self, agent):
        agents = self._data["agents"]
        agents.pop(agent, None)
        for k in [k for k, v in agents.items() if v.get("parent") == agent]:
            del agents[k]

    def _settle(self):
        """Apply defaults whose deadline passed; drop agents silent for a day."""
        now = self.now()
        changed = False
        for q in self._data["questions"].values():
            if q["answer"] is None and now >= q["deadline"]:
                q["answer"], q["by"] = q["default"], "default"
                changed = True
        for k, v in list(self._data["agents"].items()):
            if now - v.get("at", now) > SILENT_LIMIT:
                self._remove(k)
                changed = True
        if changed:
            self._save()

    def report(self, d):
        with self._lock:
            if d.get("state") == "gone":
                self._remove(d["agent"])
                self._save()
                return {"ok": True, "needs_you": False}
            a = self._data["agents"].setdefault(d["agent"], {})
            before = a.get("state")
            for f in AGENT_FIELDS:
                if d.get(f) not in (None, ""):
                    a[f] = d[f]
            a["at"] = self.now()
            self._save()
            after = a.get("state")
            return {"ok": True, "needs_you": after in ALERT_STATES and after != before}

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
        if not 2 <= len(options) <= 4:
            raise ValueError("a question takes two to four options")
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
            q = self._data["questions"][qid]
            if answer not in q["options"]:
                raise ValueError("the answer must be one of the options")
            if q["answer"] is None:
                q["answer"], q["by"] = answer, by
                self._save()
            return {"ok": True}

    def question(self, qid):
        with self._lock:
            self._settle()
            return dict(self._data["questions"][qid])

    def state(self):
        with self._lock:
            self._settle()
            return {**json.loads(json.dumps(self._data)), "now": self.now()}
