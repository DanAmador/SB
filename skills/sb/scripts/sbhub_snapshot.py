#!/usr/bin/env python3
"""sbhub_snapshot: the hub page as a phone-width picture.

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
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_TIMEOUT = 60  # a safety net: --timeout ends the page after 8 s of real time (virtual time could hang for ever)


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
