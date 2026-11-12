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
  sbhub.py trust  <project path>      let the hub run that project's own .sb/providers scripts
  sbhub.py untrust <project path>     stop doing so (both work with the hub stopped)
  sbhub.py hook                       read one Claude Code hook event on stdin and report it;
                                      always exits 0 (the hub-report mod runs this)

Every command but `serve` also takes --port N.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AGENT_FIELDS = ("name", "project", "role", "parent", "ticket", "state", "note", "done", "total")
ALERT_STATES = ("needs you", "blocked")
SILENT_LIMIT = 86400


class Hub:
    def __init__(self, home, now=time.time):
        self.home = Path(home)
        self.now = now
        self._lock = threading.Lock()
        self.providers = {}
        self.queued = set()
        self.changed = threading.Event()
        self._data = {"agents": {}, "locks": {}, "questions": {}}
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
            if d.get("project") and d["project"] not in self.providers and d["project"] not in self.queued:
                self.queued.add(d["project"])
                self.changed.set()
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
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or wait < 0:
            raise ValueError("wait must be a number of seconds, 0 or more")
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
            self._settle()
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
            return {**json.loads(json.dumps(self._data)), "now": self.now(), "providers": dict(self.providers)}

    def trusted(self):
        return read_trusted(self.home)


SBMAP = Path(__file__).resolve().parent / "sbmap.py"
REFRESH_EVERY = 15


def _run(cmd, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, **kw)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def generic_provider(project):
    """Branch, uncommitted files, last commit and the vault's maps for a project."""
    git = ["git", "-C", project]
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
    try:
        return sorted(f for f in (Path(project) / ".sb" / "providers").iterdir()
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
            r = subprocess.run([str(f)], capture_output=True, text=True, timeout=timeout, cwd=project)
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
            result = run_providers(p, trusted=p in trusted)
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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                self.send(200, hub.state())
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
            path = self.path.split("?", 1)[0]
            if not self.from_the_page_or_a_program():
                self.send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                d = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(d, dict):
                    raise ValueError("the body must be a JSON object")
                code, out = 200, None
                if path == "/api/report":
                    out = hub.report(d)
                    if out["needs_you"]:
                        notify("sb hub: needs you", "{}: {}".format(d["agent"], d.get("note") or d.get("state")))
                elif path == "/api/lock":
                    out = hub.lock(d["key"], d["by"])
                    code = 200 if out["ok"] else 409
                elif path == "/api/unlock":
                    out = hub.unlock(d["key"], d["by"])
                elif path == "/api/ask":
                    out = hub.ask(d["agent"], d["q"], d["options"], d["default"], d["wait"])
                    notify("sb hub: question", "{}: {}".format(d["agent"], d["q"]))
                elif path == "/api/answer":
                    out = hub.answer(d["qid"], d["answer"], d.get("by", "you"))
                else:
                    code, out = 404, {"ok": False, "error": "not found"}
                self.send(code, out)
            except KeyError as e:
                missing = e.args[0] if e.args else ""
                if path == "/api/answer" and missing == d.get("qid"):
                    self.send(404, {"ok": False, "error": "no such question"})
                else:
                    self.send(400, {"ok": False, "error": "missing field {}".format(missing)})
            except (ValueError, TypeError) as e:
                self.send(400, {"ok": False, "error": str(e)})
            except Exception as e:
                self.send(500, {"ok": False, "error": "{}: {}".format(type(e).__name__, e)})

    return Handler


def serve(port):
    home = Path(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub")
    hub = Hub(home)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(hub))
    threading.Thread(target=refresh_loop, args=(hub,), daemon=True).start()
    print("sb hub on http://127.0.0.1:{}".format(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


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


def event_report(e):
    """The report body for one Claude Code hook event, or None for an event the hub ignores."""
    name, sid, cwd = e.get("hook_event_name"), e.get("session_id"), e.get("cwd")
    # every event of the session's own carries who it is: the hub often starts after the session did
    session = {"agent": sid, "name": "{} {}".format(os.path.basename(cwd.rstrip("/")), sid[:6]),
               "project": cwd, "role": "orchestrator"} if sid and cwd else {"agent": sid}
    if name == "SessionStart":
        return {**session, "state": "idle", "note": "session started"}
    if name == "UserPromptSubmit":
        return {**session, "state": "working", "note": "reading your message"}
    if name == "PreToolUse":
        tin = e.get("tool_input") or {}
        detail = next((tin[k] for k in ("description", "file_path", "pattern") if tin.get(k)), "")
        r = {"state": "working", "note": "{}: {}".format(e["tool_name"], detail)[:90]}
        if e.get("agent_id"):
            return {**r, "agent": e["agent_id"], "role": "worker", "parent": sid}
        return {**session, **r}
    if name == "Notification":
        return {**session, "state": "needs you", "note": e["message"]}
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


def cmd_hook(port):
    """Read one hook event on stdin and report it. Whatever goes wrong, exit 0: a hook never fails a session."""
    try:
        e = json.load(sys.stdin)
        r = event_report(e) if isinstance(e, dict) else None
        if r:
            call(port, "/api/report", r)
    except Exception:
        pass
    return 0


def cmd_trust(a, yes):
    project = os.path.abspath(a.project)
    set_trusted(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub", project, yes)
    print(("trusted " if yes else "untrusted ") + project)
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
    add("trust", ("project", {}))
    add("untrust", ("project", {}))
    add("hook")
    a = p.parse_args(argv)
    if a.cmd == "serve":
        serve(a.port)
        return 0
    if a.cmd == "hook":
        return cmd_hook(a.port)
    if a.cmd == "report":
        return cmd_report(a)
    if a.cmd in ("lock", "unlock"):
        return cmd_lock(a, a.cmd)
    if a.cmd in ("trust", "untrust"):
        return cmd_trust(a, a.cmd == "trust")
    if a.cmd == "ask":
        return cmd_ask(a)
    return cmd_state(a)


if __name__ == "__main__":
    sys.exit(main())
