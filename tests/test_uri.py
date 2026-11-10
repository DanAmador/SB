"""sbmap uri: the one link format that opens a vault file in Obsidian from Claude Code Desktop."""
from urllib.parse import quote, unquote

from helpers import VaultCase


class UriTest(VaultCase):
    def uri(self, p):
        return "obsidian://open?path=" + quote(str(p.resolve()), safe="")

    def test_relative_path_gets_full_uri(self):
        p = self.write("wayfinder/README.md", "# Rules\n")
        out = self.sb("uri", "wayfinder/README.md").stdout.strip()
        self.assertEqual(f"[README]({self.uri(p)})", out)

    def test_label_and_title(self):
        p = self.write("notes/route.md", "---\ntitle: Route rules\n---\nBody\n")
        self.assertEqual(f"[Route rules]({self.uri(p)})", self.sb("uri", "notes/route.md").stdout.strip())
        self.assertEqual(f"[My label]({self.uri(p)})",
                         self.sb("uri", "notes/route.md", "My label").stdout.strip())

    def test_md_suffix_optional(self):
        self.write("wayfinder/README.md", "# Rules\n")
        self.assertEqual(self.sb("uri", "wayfinder/README.md").stdout, self.sb("uri", "wayfinder/README").stdout)

    def test_absolute_path(self):
        p = self.write("wayfinder/README.md", "# Rules\n")
        self.assertEqual(f"[README]({self.uri(p)})", self.sb("uri", str(p)).stdout.strip())

    def test_reserved_characters(self):
        for name in ("a #1 & b?.md", "Café.md", "100%.md"):
            p = self.write(f"odd/{name}", "x\n")
            out = self.sb("uri", f"odd/{name}").stdout.strip()
            encoded = out.split("path=", 1)[1][:-1]
            for ch in " #&?/":
                self.assertNotIn(ch, encoded, f"{name}: {out}")
            self.assertEqual(str(p.resolve()), unquote(encoded))

    def test_missing_file_fails(self):
        r = self.sb("uri", "nope.md", ok=False)
        self.assertIn("nope.md", r.stderr)

    def test_show_prints_link(self):
        self.sb("init", "repo/one", "--title", "Map one", "--why", "Why.", "--destination", "There.")
        self.sb("new", "repo/one", "--title", "First step", "--why", "Because.", "--no-sync")
        line = self.sb("show", "repo/one", "1").stdout.splitlines()[1]
        self.assertTrue(line.startswith("link: [001 First step]("), line)
        self.assertIn("obsidian://open?path=", line)
