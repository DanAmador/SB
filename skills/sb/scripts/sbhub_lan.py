#!/usr/bin/env python3
"""sbhub_lan.py: the hub's own page, read-only, for a phone on the same WiFi.

  sbhub_lan.py serve [--port 8766] [--hub-port P]   serve it on every interface, behind /v/<token>/
  sbhub_lan.py url [--port 8766]                    print http://<the Mac's WiFi address>:<port>/v/<token>/

The hub itself only listens on 127.0.0.1. This server sits beside it: it serves the hub's page (switched to
read-only) and board.js, forwards GET requests under /api/ to the hub, and forwards exactly three POSTs that
change display state only (clear finished items, dismiss a session row, clear quiet rows). Every other POST
answers 403. Every path without the token answers 404 with no body. The token is 32 random url-safe
characters in $SB_HUB_HOME/lan-token (default ~/.sb-hub), made on the first run.
"""
import argparse
import hmac
import os
import secrets
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sbhub  # noqa: E402

LAN_PORT = 8766
WRITES = ("/api/queue/clear-finished", "/api/agents/dismiss", "/api/agents/clear-quiet")
BODY_MAX = 65536


def home():
    return Path(os.environ.get("SB_HUB_HOME") or Path.home() / ".sb-hub")


def token():
    """The secret in every path, made once and readable by the owner only."""
    path = home() / "lan-token"
    try:
        t = path.read_text(encoding="utf-8").strip()
        if len(t) >= 32:
            return t
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(24)  # 24 bytes: 32 characters
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(t + "\n")
    return t


def wifi_address():
    """The Mac's WiFi IPv4 (en0, then en1), else the address it would reach the internet from, else 127.0.0.1."""
    for dev in ("en0", "en1"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", dev], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            ip = ""
        if ip:
            return ip
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # a documentation address: picks the route, sends nothing
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def make_handler(secret, hub_port):
    prefix = "/v/" + secret

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            if body:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")  # the token is in the path
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def rest(self):
            """The path after /v/<token>, or None (and an empty 404 sent) when the token is not there."""
            path = self.path.split("?", 1)[0]
            given = path[:len(prefix)]
            if hmac.compare_digest(given.encode(), prefix.encode()) and (len(path) == len(prefix) or path[len(prefix)] == "/"):
                return self.path[len(prefix):] or "/"
            self.send(404)
            return None

        def forward(self, rest, body=None):
            req = urllib.request.Request("http://127.0.0.1:{}{}".format(hub_port, rest), body,
                                         {"Content-Type": "application/json"} if body is not None else {})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    self.send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                with e:
                    self.send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
            except (OSError, ValueError):
                self.send(502, b'{"ok": false, "error": "hub not reachable"}')

        def do_GET(self):
            rest = self.rest()
            if rest is None:
                return
            path = rest.split("?", 1)[0]
            if path == "/":
                if not self.path.split("?", 1)[0].endswith("/"):  # relative links need the trailing slash
                    self.send_response(301)
                    self.send_header("Location", prefix + "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                page = sbhub.PAGE.read_bytes().replace(b'<div id="hq">', b'<div id="hq" data-readonly="1">', 1)
                self.send(200, page, "text/html; charset=utf-8")
            elif path == "/board.js":
                self.send(200, sbhub.BOARD_JS.read_bytes(), "text/javascript; charset=utf-8")
            elif path.startswith("/api/"):
                self.forward(rest)
            else:
                self.send(404)

        def do_POST(self):
            rest = self.rest()
            if rest is None:
                return
            ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            origin = self.headers.get("Origin")
            same = origin is None or origin == "http://" + str(self.headers.get("Host"))
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = BODY_MAX + 1
            if rest.split("?", 1)[0] not in WRITES or ctype != "application/json" or not same or n > BODY_MAX:
                self.send(403, b'{"ok": false, "error": "this page is read-only"}')
                return
            self.forward(rest.split("?", 1)[0], self.rfile.read(n) or b"{}")

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sbhub_lan.py", description="The hub's page, read-only, on the WiFi.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=LAN_PORT)
    s.add_argument("--hub-port", type=int, default=sbhub.default_port())
    s.add_argument("--bind", default="0.0.0.0", help=argparse.SUPPRESS)  # tests: 127.0.0.1
    u = sub.add_parser("url")
    u.add_argument("--port", type=int, default=LAN_PORT)
    a = ap.parse_args(argv)
    secret = token()
    if a.cmd == "url":
        print("http://{}:{}/v/{}/".format(wifi_address(), a.port, secret))
        return
    server = ThreadingHTTPServer((a.bind, a.port), make_handler(secret, a.hub_port))
    print("sb hub phone page on http://{}:{}/v/{}/ (read-only; the hub on 127.0.0.1:{})".format(
        wifi_address() if a.bind == "0.0.0.0" else a.bind, server.server_address[1], secret, a.hub_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
