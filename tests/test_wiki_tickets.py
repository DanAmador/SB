import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from helpers import VaultCase

WIKIBRAIN = Path.home() / "Documents/Coding/wikiBrain/skills/wikibrain/scripts"
PR = "https://github.com/acme/widgets/pull/7"
A, B, C, D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)
ARTICLE = """---
wiki: article
type: concept
project: p
status: current
summary: S
updated: 2026-10-28
sources:
  - "[[wiki/raw/p/t/src|Source]]"
tags:
  - wiki/concept
  - project/p
  - topic/t
---
# Art

## Overview

S
"""
RAW = """---
wiki: raw
type: source
project: p
title: Source
source: "x"
repo: acme/widgets
{props}---
# Source

Text.
"""
LINK = "[[wayfinder/acme/fix/issues/001-first|#001]]"


class TicketsProperty(VaultCase):
    def setUp(self):
        super().setUp()
        env = {"WIKIBRAIN_CACHE": str(Path(self._tmp.name) / "cache")}
        if WIKIBRAIN.is_dir():
            env["WIKIBRAIN_DIR"] = str(WIKIBRAIN)
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.write("wiki/p/t/t.md", "---\nwiki: topic\ntype: topic\nproject: p\n---\n# T\n")
        self.write("wiki/p/t/art.md", ARTICLE)
        self.map("acme/fix")
        self.ticket_path = "wayfinder/acme/fix/issues/001-first.md"

    def raw(self, **props):
        self.write("wiki/raw/p/t/src.md", RAW.format(props="".join(f'{k}: "{v}"\n' for k, v in props.items())))

    def stamp(self, status="Project.Finished", **props):
        self.ticket("acme/fix", 1, "First", status=status)
        text = self.read(self.ticket_path).replace("tags:", "".join(f'{k}: "{v}"\n' for k, v in props.items()) + "tags:", 1)
        self.write(self.ticket_path, text.replace("type: research\n", "type: research\nrepo: acme/widgets\n"))

    def gh(self, body):
        d = Path(self._tmp.name) / "bin"
        d.mkdir(exist_ok=True)
        (d / "gh").write_text(f"#!/bin/sh\n{body}\n")
        (d / "gh").chmod(0o755)
        return f"{d}:/usr/bin:/bin"

    def fix(self, **kw):
        return self.sb("wiki", "check", "--fix", ok=None, **kw)

    def test_the_same_pr_fills_the_property_and_losing_the_match_clears_it(self):
        self.raw(pr=PR, commit=A)
        self.stamp(pr=PR, commit=B)
        r = self.fix()
        self.assertIn("tickets: 1 article(s) updated", r.stdout)
        text = self.read("wiki/p/t/art.md")
        self.assertIn(f'tickets:\n  - "{LINK}"\n', text)
        self.assertEqual(text.replace(f'tickets:\n  - "{LINK}"\n', ""), ARTICLE)
        self.assertIn("tickets: 0 article(s) updated", self.fix().stdout)
        self.stamp(pr="https://github.com/acme/widgets/pull/8", commit=B)
        self.assertIn("tickets: 1 article(s) updated", self.fix().stdout)
        self.assertEqual(self.read("wiki/p/t/art.md"), ARTICLE)

    def test_the_commit_within_the_sources_pr_matches_through_gh(self):
        self.raw(pr=PR, commit=A)
        self.stamp(commit=B)
        path = self.gh(f'[ "$3" = "{PR}" ] && echo \'{{"commits": [{{"oid": "{C}"}}, {{"oid": "{B}"}}]}}\'')
        self.fix(path=path)
        self.assertIn(LINK, self.read("wiki/p/t/art.md"))
        self.fix(path=self.gh("exit 1"))
        self.assertNotIn(LINK, self.read("wiki/p/t/art.md"))

    def test_an_exact_commit_matches_without_gh(self):
        self.raw(pr=PR, commit=A)
        self.stamp(commit=A)
        self.fix()
        self.assertIn(LINK, self.read("wiki/p/t/art.md"))

    def test_another_repo_an_open_ticket_or_a_missing_commit_never_match(self):
        self.raw(commit=A)
        self.stamp(commit=A, status="Project.Planned")
        self.fix()
        self.stamp(commit=A)
        self.write(self.ticket_path, self.read(self.ticket_path).replace("repo: acme/widgets", "repo: acme/other"))
        self.fix()
        self.stamp(pr=PR)
        self.fix()
        self.assertEqual(self.read("wiki/p/t/art.md"), ARTICLE)

    def test_a_stale_property_is_replaced_in_place(self):
        self.raw(commit=A)
        self.stamp(commit=A)
        self.write("wiki/p/t/art.md", ARTICLE.replace("tags:", 'tickets:\n  - "[[old|x]]"\ntags:', 1))
        self.fix()
        self.assertEqual(self.read("wiki/p/t/art.md"), ARTICLE.replace("tags:", f'tickets:\n  - "{LINK}"\ntags:', 1))

    def test_an_import_fills_it(self):
        clone = Path(self._tmp.name) / "clone"
        clone.mkdir()
        git = lambda *a: subprocess.run(["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                        capture_output=True, text=True, check=True)
        git("init", "-q", "-b", "main")
        rel = ARTICLE.replace('"[[wiki/raw/p/t/src|Source]]"', "wiki/raw/p/t/src.md")
        for name, text in (("wiki/p/t/t.md", "---\nwiki: topic\ntype: topic\nproject: p\n---\n# T\n"),
                           ("wiki/p/t/art.md", rel),
                           ("wiki/raw/p/t/src.md", RAW.format(props=f'commit: "{A}"\n'))):
            (clone / name).parent.mkdir(parents=True, exist_ok=True)
            (clone / name).write_text(text)
        git("add", "-A")
        git("commit", "-q", "-m", "wiki")
        self.stamp(commit=A)
        os.remove(self.vault / "wiki/p/t/art.md")
        r = self.sb("wiki", "import", str(clone), "--projects", "p")
        self.assertIn("tickets: 1 article(s) updated", r.stdout)
        self.assertIn(f'tickets:\n  - "{LINK}"\n', self.read("wiki/p/t/art.md"))


if __name__ == "__main__":
    unittest.main()
