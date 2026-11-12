"""sbhub's providers: the generic one, a project's own scripts, and the refresh thread.
Only temp git repos are used here: the repo's own .sb/providers runs this suite and would recurse."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HubCase, free_port, wait_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "sb" / "scripts"))
from sbhub import Hub, generic_provider, run_providers, usable_project  # noqa: E402


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

    def test_an_untrusted_project_runs_no_script_and_says_so(self):
        marker = Path(self.repo, "ran")
        script(self.repo, "tests", 'open("ran", "w").close()\nprint(json.dumps({"widgets": []}))')
        out = run_providers(self.repo, trusted=False)
        self.assertFalse(marker.exists())
        self.assertEqual(out[1], {"title": "Project providers", "widgets": [
            {"kind": "status", "label": "Not trusted yet", "value": "run: sbhub trust <project>", "level": "warn"}]})
        self.assertEqual(len(out), 2)

    def test_an_untrusted_project_without_scripts_gets_the_generic_one_only(self):
        Path(self.repo, ".sb", "providers").mkdir(parents=True)
        Path(self.repo, ".sb", "providers", "README.md").write_text("notes")
        self.assertEqual(len(run_providers(self.repo, trusted=False)), 1)

    def test_symlinked_scripts_are_skipped(self):
        script(self.repo, "real", 'print(json.dumps({"title": "Real", "widgets": []}))')
        os.symlink(Path(self.repo, ".sb", "providers", "real"), Path(self.repo, ".sb", "providers", "link"))
        self.assertEqual([p["title"] for p in run_providers(self.repo)], ["Repo and maps", "Real"])
        os.unlink(Path(self.repo, ".sb", "providers", "real"))
        self.assertEqual(len(run_providers(self.repo)), 1)

    def test_output_of_the_wrong_types_becomes_an_error_entry(self):
        bodies = ['{"title": 5, "widgets": []}', '{"icon": 5, "widgets": []}', '{"widgets": [1]}', '{"widgets": {}}']
        for i, b in enumerate(bodies):
            script(self.repo, "s%d" % i, "print(%r)" % b)
        out = run_providers(self.repo)[1:]
        self.assertEqual([p["title"] for p in out], ["s0", "s1", "s2", "s3"])
        self.assertTrue(all(p["widgets"][0]["level"] == "bad" for p in out))

    def test_only_an_absolute_existing_directory_is_a_project(self):
        self.assertTrue(usable_project(self.repo))
        for bad in ("relative/dir", "/no/such/dir", "", None, 5, str(Path(self.repo, "..", "nope"))):
            self.assertFalse(usable_project(bad), bad)

    def test_the_providers_name_their_icons(self):
        self.assertEqual(generic_provider(self.repo)["icon"], "git")
        mine = Path(__file__).resolve().parents[1] / ".sb" / "providers" / "tests"
        self.assertIn('"icon": "tests"', mine.read_text())

    def test_more_reports_during_the_first_run_queue_no_more_runs(self):
        hub = Hub(self._tmp.name)
        hub.report({"agent": "a", "project": self.repo})
        self.assertTrue(hub.changed.is_set())
        hub.changed.clear()
        hub.report({"agent": "b", "project": self.repo})
        hub.report({"agent": "a", "project": self.repo, "state": "working"})
        self.assertFalse(hub.changed.is_set())


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
        self.hub("trust", repo)
        self.hub("report", "--agent", "a", "--project", repo)
        got = wait_for(lambda: self.get("/api/state").get("providers", {}).get(os.path.abspath(repo)))
        self.assertEqual([p["title"] for p in got], ["Repo and maps", "One"])

    def test_trust_and_untrust_edit_the_file_without_a_hub(self):
        home = Path(self._tmp.name, "trusted")
        a, b = os.path.abspath("x"), os.path.abspath("y")
        self.assertEqual(self.hub("trust", "x", port=free_port()).stdout.strip(), "trusted " + a)
        self.hub("trust", "x")
        self.hub("trust", "y")
        self.assertEqual(home.read_text().split(), [a, b])
        self.hub("untrust", "x")
        self.assertEqual(home.read_text().split(), [b])

    def test_an_untrusted_project_shows_the_warning_until_it_is_trusted(self):
        repo = make_repo(self._tmp.name)
        script(repo, "one", 'print(json.dumps({"title": "One", "widgets": []}))')
        self.hub("report", "--agent", "a", "--project", repo)
        key = os.path.abspath(repo)
        got = wait_for(lambda: self.get("/api/state").get("providers", {}).get(key))
        self.assertEqual([p["title"] for p in got], ["Repo and maps", "Project providers"])
        self.hub("trust", repo)
        self.hub("report", "--agent", "a", "--project", repo)  # no new run is asked for; the next refresh reads the file
        wait_for(lambda: [p["title"] for p in self.get("/api/state")["providers"][key]] == ["Repo and maps", "One"], timeout=40)

    def test_a_project_that_is_not_a_directory_gets_no_providers(self):
        good = make_repo(self._tmp.name)
        self.hub("report", "--agent", "a", "--project", "/no/such/dir")
        self.hub("report", "--agent", "b", "--project", good)
        wait_for(lambda: self.get("/api/state").get("providers", {}).get(os.path.abspath(good)))
        self.assertNotIn("/no/such/dir", self.get("/api/state")["providers"])


if __name__ == "__main__":
    unittest.main()
