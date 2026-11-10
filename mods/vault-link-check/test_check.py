"""Run: python3 mods/vault-link-check/test_check.py  (stdlib only; a temp vault, touches nothing else)"""
import io
import json
import os
import sys
import tempfile
import unittest
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check  # noqa: E402


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def uri(path):
    return "obsidian://open?path=" + quote(path, safe="")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self._tmp.name)
        self.vault = os.path.join(root, "Vault")
        self.repo = os.path.join(root, "repo")
        os.makedirs(os.path.join(self.vault, "wayfinder"))
        os.makedirs(self.repo)
        self.readme = os.path.join(self.vault, "wayfinder", "README.md")
        self.cafe = os.path.join(self.vault, "Café #1.md")
        for p in (self.readme, self.cafe):
            write(p, "x\n")

    def tearDown(self):
        self._tmp.cleanup()

    def bad(self, text, vault=None):
        return check.bad_links(text, vault or self.vault, self.repo)


class BadLinks(Base):
    def test_good_links_pass(self):
        text = (f"[a]({uri(self.readme)}) and [b]({uri(self.cafe)}) "
                f"[c](file://{quote(self.readme)}) [d](https://obsidian.md/help)")
        self.assertEqual([], self.bad(text))

    def test_format_b_flagged(self):
        found = self.bad("[r](obsidian://open?vault=Vault&file=wayfinder%2FREADME)")
        self.assertEqual(1, len(found))
        self.assertIn("browser", found[0][1])

    def test_short_form_flagged(self):
        found = self.bad(f"[r](obsidian://{quote(self.readme)})")
        self.assertEqual(1, len(found))
        self.assertIn("browser", found[0][1])

    def test_broken_encoding_flagged(self):
        typo = self.readme.replace("README", "READNE")
        found = self.bad(f"[r](obsidian://open?path={quote(typo)})")
        self.assertEqual(1, len(found))
        self.assertIn("no such file", found[0][1])

    def test_plain_paths_flagged(self):
        rel = os.path.relpath(self.readme, self.repo)
        for text in (f"[x]({self.readme.replace(' ', '%20')})", f"[x]({quote(self.cafe)})", f"[x]({rel})"):
            found = self.bad(text)
            self.assertEqual(1, len(found), text)
            self.assertIn("plain path", found[0][1])

    def test_repo_file_links_pass(self):
        write(os.path.join(self.repo, "a.md"), "x")
        self.assertEqual([], self.bad("[a](a.md) and [b](a.md:12)"))

    def test_wikilink_flagged(self):
        found = self.bad("see [[wayfinder/README]] for the rules")
        self.assertEqual(1, len(found))
        self.assertIn("wikilink", found[0][1])

    def test_code_brackets_pass(self):
        for text in ("use [[ -n $x ]] in bash", 'df[["a","b"]]', "a [[tool.uv.index]] header"):
            self.assertEqual([], self.bad(text), text)

    def test_wikilink_by_name_flagged(self):
        self.assertEqual(1, len(self.bad("see [[README|the rules]]")))
        self.assertEqual(1, len(self.bad("see [[README#Heading]]")))

    def test_raw_spaces_flagged(self):
        spaced = os.path.join(self.vault, "two words.md")
        write(spaced, "x")
        found = self.bad(f"[n](obsidian://open?path={spaced})")
        self.assertEqual(1, len(found))
        self.assertIn("space", found[0][1])

    def test_anchor_in_vault_session_passes(self):
        self.assertEqual([], check.bad_links("[r](#section)", self.vault, self.vault))

    def test_code_ignored(self):
        bad = "[r](obsidian://open?vault=Vault&file=x) [[wayfinder/README]]"
        self.assertEqual([], self.bad(f"run `{bad}` now"))
        self.assertEqual([], self.bad(f"```\n{bad}\n```\n"))
        self.assertEqual([], self.bad(f"`sbmap show sb-workflow/x` and `{self.readme}`"))

    def test_no_links_pass(self):
        self.assertEqual([], self.bad("Nothing to link here. See https://example.com."))

    def test_vault_trailing_slash(self):
        text = f"[x]({quote(self.readme)}) [r](obsidian://open?vault=V&file=x)"
        self.assertEqual(self.bad(text), self.bad(text, self.vault + "/"))


class Main(Base):
    def run_main(self, data):
        out = io.StringIO()
        env = os.environ.get("SB_VAULT")
        os.environ["SB_VAULT"] = self.vault
        try:
            stdin = io.StringIO(data if isinstance(data, str) else json.dumps(data))
            self.assertEqual(0, check.main(stdin, out))
        finally:
            if env is None:
                os.environ.pop("SB_VAULT")
            else:
                os.environ["SB_VAULT"] = env
        return out.getvalue()

    def test_main_blocks_once(self):
        data = {"last_assistant_message": "[r](obsidian://open?vault=Vault&file=x)", "cwd": self.repo}
        out = json.loads(self.run_main(data))
        self.assertEqual("block", out["decision"])
        self.assertIn("sbmap.py uri", out["reason"])
        self.assertEqual("", self.run_main(dict(data, stop_hook_active=True)))

    def test_main_good_reply_silent(self):
        self.assertEqual("", self.run_main({"last_assistant_message": f"[a]({uri(self.readme)})", "cwd": self.repo}))

    def test_main_reads_transcript(self):
        lines = [
            {"type": "user", "message": {"role": "user", "content": "[[old]] link from before"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "[[wayfinder/README]]"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
        ]
        path = os.path.join(self.repo, "t.jsonl")
        write(path, "\n".join(json.dumps(x) for x in lines))
        out = json.loads(self.run_main({"transcript_path": path, "cwd": self.repo}))
        self.assertIn("wikilink", out["reason"])
        self.assertNotIn("old", out["reason"])

    def test_main_never_traps(self):
        for data in ("", "not json", {"transcript_path": "/nope/t.jsonl"}):
            self.assertEqual("", self.run_main(data))


if __name__ == "__main__":
    unittest.main()
