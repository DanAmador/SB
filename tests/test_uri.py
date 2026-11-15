"""sbmap uri: the path form opens a vault file in Obsidian from Claude Code Desktop; --vault names it by vault and vault path for a phone."""
import subprocess
import sys
from urllib.parse import quote, unquote

from helpers import SBMAP, VaultCase


class UriTest(VaultCase):
    def uri(self, p):
        return "obsidian://open?path=" + quote(str(p.resolve()), safe="")

    def vault_uri(self, p):
        return ("obsidian://open?vault=" + quote(self.vault.name, safe="")
                + "&file=" + quote(str(p.resolve().relative_to(self.vault.resolve())), safe=""))

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

    def test_vault_flag_gives_vault_name_and_relative_path(self):
        p = self.write("wayfinder/README.md", "# Rules\n")
        out = self.sb("uri", "wayfinder/README.md", "--vault").stdout.strip()
        self.assertEqual(f"[README]({self.vault_uri(p)})", out)

    def test_spaces_colons_slashes_are_encoded_in_the_vault_form(self):
        p = self.write("wayfinder/My Repo/e: one/issues/001 A: b.md", "x\n")
        out = self.sb("uri", str(p), "--vault").stdout.strip()
        self.assertIn(f"(obsidian://open?vault={self.vault.name}&file=wayfinder%2FMy%20Repo%2Fe%3A%20one%2Fissues%2F001%20A%3A%20b.md)", out)

    def test_vault_name_with_a_space_is_encoded(self):
        spaced = self.vault.parent / "Second Brain"
        spaced.mkdir()
        (spaced / "n.md").write_text("x\n")
        r = subprocess.run([sys.executable, str(SBMAP), "uri", "n.md", "--vault"], capture_output=True, text=True,
                           env=self.env(SB_VAULT=str(spaced)), cwd=spaced)
        self.assertEqual("[n](obsidian://open?vault=Second%20Brain&file=n.md)", r.stdout.strip(), r.stderr)

    def test_file_outside_the_vault_keeps_the_path_form(self):
        out_file = self.vault.parent / "elsewhere.md"
        out_file.write_text("x\n")
        want = f"[elsewhere](obsidian://open?path={quote(str(out_file.resolve()), safe='')})"
        self.assertEqual(want, self.sb("uri", str(out_file), "--vault").stdout.strip())
        self.assertEqual(want, self.sb("uri", str(out_file)).stdout.strip())
