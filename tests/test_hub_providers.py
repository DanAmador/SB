"""sbhub's providers: the generic one, a project's own scripts, and the refresh thread.
Only temp git repos are used here: the repo's own .sb/providers runs this suite and would recurse."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HubCase, wait_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import generic_provider, run_providers  # noqa: E402


def script(repo, name, body):
    p = Path(repo, ".sb", "providers", name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env python3\nimport json\n" + body + "\n")
    p.chmod(0o755)


def make_repo(tmp):
    repo = Path(tmp, "repo")
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "first commit"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env, capture_output=True)
    return str(repo)


class ProviderCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        vault = Path(self._tmp.name, "Vault")
        vault.mkdir()
        old = os.environ.get("SB_VAULT")
        os.environ["SB_VAULT"] = str(vault)
        self.addCleanup(lambda: os.environ.pop("SB_VAULT") if old is None else os.environ.update(SB_VAULT=old))
        self.repo = make_repo(self._tmp.name)

    def test_generic_provider_reads_the_repo(self):
        Path(self.repo, "new.txt").write_text("x")
        w = {x["label"]: x for x in generic_provider(self.repo)["widgets"]}
        self.assertEqual((w["Uncommitted files"]["value"], w["Uncommitted files"]["level"]), ("1", "warn"))
        self.assertIn("first commit", w["Last commit"]["value"])
        self.assertEqual(w["Maps in the vault"]["kind"], "log")

    def test_a_project_script_adds_its_widgets(self):
        script(self.repo, "tests", 'print(json.dumps({"title": "Suite", "widgets": [{"kind": "counts", "label": "Tests", "items": {"pass": 3, "fail": 0}}]}))')
        self.assertEqual([p["title"] for p in run_providers(self.repo)], ["Repo and maps", "Suite"])

    def test_a_broken_script_shows_its_error_and_harms_nothing(self):
        script(self.repo, "a-garbage", 'print("not json")')
        script(self.repo, "b-crash", 'raise SystemExit(3)')
        script(self.repo, "c-hang", 'import time; time.sleep(30)')
        script(self.repo, "d-ok", 'print(json.dumps({"title": "Ok", "widgets": []}))')
        out = run_providers(self.repo, timeout=1)
        self.assertEqual([p["title"] for p in out], ["Repo and maps", "a-garbage", "b-crash", "c-hang", "Ok"])
        self.assertTrue(all(p["widgets"][0]["level"] == "bad" for p in out[1:4]))

    def test_a_non_executable_file_is_ignored(self):
        Path(self.repo, ".sb", "providers").mkdir(parents=True)
        Path(self.repo, ".sb", "providers", "README.md").write_text("notes")
        self.assertEqual(len(run_providers(self.repo)), 1)


class RefreshTest(HubCase):
    def setUp(self):
        self._vault = tempfile.TemporaryDirectory()
        self.addCleanup(self._vault.cleanup)
        old = os.environ.get("SB_VAULT")
        os.environ["SB_VAULT"] = self._vault.name
        self.addCleanup(lambda: os.environ.pop("SB_VAULT") if old is None else os.environ.update(SB_VAULT=old))
        super().setUp()

    def test_state_carries_each_agents_project_providers(self):
        repo = make_repo(self._tmp.name)
        script(repo, "one", 'print(json.dumps({"title": "One", "widgets": []}))')
        self.hub("report", "--agent", "a", "--project", repo)
        got = wait_for(lambda: self.get("/api/state").get("providers", {}).get(os.path.abspath(repo)))
        self.assertEqual([p["title"] for p in got], ["Repo and maps", "One"])


if __name__ == "__main__":
    unittest.main()
