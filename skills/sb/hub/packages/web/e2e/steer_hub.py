"""The fixture hub's real half, for the Steer test: a throwaway vault with one map of three tickets, and the real Hub
running a ticket action on it through sbmap. `setup <dir>` makes the vault; `rows` prints its open tickets as the hub
lists them; `act <action> <key> <text>` runs the action and prints {"ok": true} or {"ok": false, "error": ...}."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from sbhub import Hub  # noqa: E402


def sbmap(*a):
    subprocess.run([sys.executable, str(SCRIPTS / "sbmap.py"), *a], check=True, capture_output=True, text=True)


def hub():
    return Hub(Path(os.environ["SB_HUB_HOME"]))


if sys.argv[1] == "setup":
    os.environ["SB_VAULT"] = sys.argv[2]
    Path(sys.argv[2], "wayfinder").mkdir(parents=True, exist_ok=True)
    sbmap("init", "steer/lab", "--title", "The steer lab", "--why", "A map to steer.", "--destination", "Somewhere.", "--repo", sys.argv[2])
    sbmap("mapset", "steer/lab", "checks=true")
    for title, why in (("Lay the base", "First."), ("Build the wall", "Second."), ("Paint the wall", "Third.")):
        sbmap("new", "steer/lab", "--title", title, "--why", why, "--done-when", "It stands.", "--paths", "src/", "--no-sync")
    sbmap("block", "steer/lab", "3", "2", "--no-sync")
elif sys.argv[1] == "rows":
    print(json.dumps(hub().tickets(fresh=True)))
else:
    try:
        print(json.dumps(hub().ticket_action(sys.argv[2], sys.argv[3], sys.argv[4])))
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
