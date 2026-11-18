"""The Linux side: systemd user units from sbhub_service.sh, notify-send, and the link opener of obsidian-links.
systemctl and loginctl are fakes on PATH that log their arguments; nothing touches the real user manager."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import free_port, SCRIPT

sys.path.insert(0, os.path.dirname(SCRIPT))
import sbhub  # noqa: E402

SERVICE = Path(SCRIPT).with_name("sbhub_service.sh")
REGISTER = Path(__file__).resolve().parents[1] / "mods" / "obsidian-links" / "hooks" / "register.tsx"
FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >> "$CALLS"
case "$*" in
  *is-active*) exit 1 ;;
  *"-p ActiveState"*) echo active ;;
  *"-p MainPID"*) echo 4242 ;;
esac
"""


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux only")
class ServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        t = Path(self._tmp.name)
        (t / "bin").mkdir()
        for name in ("systemctl", "loginctl"):
            (t / "bin" / name).write_text(FAKE)
            (t / "bin" / name).chmod(0o755)
        self.units = t / "home" / ".config" / "systemd" / "user"
        self.calls = t / "calls"
        self.port = free_port()
        self.env = {"HOME": str(t / "home"), "PATH": "{}:/usr/bin:/bin".format(t / "bin"), "CALLS": str(self.calls),
                    "SB_HUB_HOME": str(t / "hub"), "SB_HUB_PORT": str(self.port),
                    "SB_VAULT": str(t / "Second Brain 100%$x"), "SB_CODE": str(t / "code")}

    def run_service(self, *args):
        r = subprocess.run(["bash", str(SERVICE), *args], capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_install_writes_units_that_keep_workers_and_quote_the_environment(self):
        out = self.run_service("install", "--no-lan", "--linger")
        hub = (self.units / "com.sb.hub.service").read_text()
        self.assertIn('/sbhub.py" "serve" "--port" "{}"'.format(self.port), hub)
        for line in ("KillMode=process", "WorkingDirectory={}".format(SERVICE.parents[3]), "Restart=always", "Wants=com.sb.hub-awake.service", "WantedBy=default.target",
                     "StartLimitIntervalSec=0",
                     'Environment="SB_VAULT={}"'.format(self.env["SB_VAULT"].replace("%", "%%")),
                     'Environment="SB_CODE={}"'.format(self.env["SB_CODE"]),
                     "StandardOutput=append:{}/com.sb.hub.log".format(self.env["SB_HUB_HOME"])):
            self.assertIn(line, hub.splitlines())
        awake = (self.units / "com.sb.hub-awake.service").read_text()
        self.assertIn("--what=idle:sleep", awake)
        self.assertIn("PartOf=com.sb.hub.service", awake)
        self.assertFalse((self.units / "com.sb.hub-lan.service").exists())
        calls = self.calls.read_text()
        self.assertIn("systemctl --user enable --quiet com.sb.hub.service", calls)
        self.assertIn("systemctl --user restart com.sb.hub.service", calls)
        self.assertIn("loginctl enable-linger", calls)
        self.assertIn("com.sb.hub: active, pid 4242", out)
        self.assertIn("com.sb.hub-lan: not installed", out)

    def test_without_linger_loginctl_is_never_called(self):
        self.run_service("install", "--no-lan")
        self.assertNotIn("loginctl", self.calls.read_text())

    def test_uninstall_removes_every_unit(self):
        self.run_service("install", "--no-lan")
        self.run_service("uninstall")
        self.assertEqual(list(self.units.iterdir()), [])
        self.assertIn("systemctl --user disable --quiet com.sb.hub.service", self.calls.read_text())


class NotifyTest(unittest.TestCase):
    def test_linux_uses_notify_send(self):
        with mock.patch.object(sbhub.sys, "platform", "linux"), mock.patch.dict(os.environ, {"SB_HUB_NOTIFY": "1"}), \
                mock.patch.object(sbhub.shutil, "which", return_value="/usr/bin/notify-send"), \
                mock.patch.object(sbhub.subprocess, "run") as run:
            sbhub.notify("sb hub", "-a question")
        self.assertEqual(run.call_args[0][0], ["notify-send", "--app-name=sb hub", "--", "sb hub", "-a question"])

    def test_off_with_sb_hub_notify_0(self):
        with mock.patch.dict(os.environ, {"SB_HUB_NOTIFY": "0"}), mock.patch.object(sbhub.subprocess, "run") as run:
            sbhub.notify("t", "x")
        run.assert_not_called()


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux only")
class OpenerTest(unittest.TestCase):
    def test_a_vault_link_goes_to_xdg_open_as_one_argument(self):
        script = re.search(r"const OPEN = '(.*)'", REGISTER.read_text()).group(1)
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "xdg-open").write_text('#!/bin/sh\nprintf "%s|%s" "$#" "$1"\n')
            (Path(t) / "xdg-open").chmod(0o755)
            uri = "obsidian://open?path=%2Fv%2Fa%20b.md"
            r = subprocess.run(["sh", "-c", script, "sh", uri], capture_output=True, text=True,
                               env={"PATH": t + ":/usr/bin:/bin"})
        self.assertEqual(r.stdout, "1|" + uri)


if __name__ == "__main__":
    unittest.main()
