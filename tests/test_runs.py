import unittest

from helpers import TODAY, VaultCase


class Runs(VaultCase):
    def setUp(self):
        super().setUp()
        self.map("sk4te/build-menu", title="Build menu")
        self.map("homestudio/comedy-pass", title="Comedy pass")

    def test_run_makes_the_folder_in_the_maps_project(self):
        out = self.sb("run", "sk4te/build-menu").stdout.strip()
        self.assertEqual(out, f"wayfinder/sk4te/runs/{TODAY}-build-menu/{TODAY}-build-menu.md")
        self.assertTrue(self.exists(f"wayfinder/sk4te/runs/{TODAY}-build-menu"))

    def test_run_for_a_project_and_across_projects(self):
        self.assertEqual(self.sb("run", "sk4te", "editor-lock", "--date", "2026-11-11").stdout.strip(),
                         "wayfinder/sk4te/runs/2026-11-11-editor-lock/2026-11-11-editor-lock.md")
        self.assertEqual(self.sb("run", "--shared", "wiki-tend", "--date", "2026-11-11").stdout.strip(),
                         "wayfinder/runs/2026-11-11-wiki-tend/2026-11-11-wiki-tend.md")

    def test_status_finds_a_board_in_its_run_folder(self):
        board = self.sb("run", "sk4te/build-menu").stdout.strip()
        self.write(board, "# Board\n\n[[wayfinder/sk4te/build-menu/map|Build menu]]\n")
        self.assertIn(board, self.sb("status", "sk4te/build-menu").stdout)

    def test_migrate_sorts_loose_runs_and_their_links_follow(self):
        self.write("wayfinder/runs/2026-11-08-afternoon.md",
                   "# Run\n\n[[wayfinder/sk4te/build-menu/map|Build menu]], sk4te all night.\n")
        self.write("wayfinder/runs/2026-11-08-afternoon-877.md", "# 877 report\n")
        self.write("wayfinder/runs/2026-11-08-afternoon/925.md", "# 925\n")
        self.write("wayfinder/runs/2026-11-07-wiki-tend.md",
                   "# Tend\n\nwayfinder/sk4te/ and wayfinder/homestudio/ both.\n")
        note = self.write("wayfinder/sk4te/build-menu/issues/001-a.md",
                          "See [[wayfinder/runs/2026-11-08-afternoon|the run]], "
                          "`wayfinder/runs/2026-11-08-afternoon/925.md`, "
                          "`wayfinder/runs/2026-11-08-afternoon-877.md` and "
                          "[[wayfinder/runs/2026-11-07-wiki-tend]].\n")
        dry = self.sb("migrate", "--runs").stdout
        self.assertIn("dry run", dry)
        self.assertTrue(self.exists("wayfinder/runs/2026-11-08-afternoon.md"))

        self.sb("migrate", "--runs", "--write")
        run = "wayfinder/sk4te/runs/2026-11-08-afternoon"
        self.assertTrue(self.exists(f"{run}/2026-11-08-afternoon.md"))
        self.assertTrue(self.exists(f"{run}/2026-11-08-afternoon-877.md"))
        self.assertTrue(self.exists(f"{run}/925.md"))
        self.assertTrue(self.exists("wayfinder/runs/2026-11-07-wiki-tend/2026-11-07-wiki-tend.md"))
        self.assertFalse(self.exists("wayfinder/runs/2026-11-08-afternoon.md"))
        text = note.read_text()
        self.assertIn(f"[[{run}/2026-11-08-afternoon|the run]]", text)
        self.assertIn(f"`{run}/925.md`", text)
        self.assertIn(f"`{run}/2026-11-08-afternoon-877.md`", text)
        self.assertIn("[[wayfinder/runs/2026-11-07-wiki-tend/2026-11-07-wiki-tend]]", text)
        self.assertNotIn("wayfinder/runs/2026-11-08", text)

        again = self.sb("migrate", "--runs", "--write").stdout  # nothing loose left: nothing moves
        self.assertIn("0 run(s)", again)
        self.assertEqual(note.read_text(), text)


if __name__ == "__main__":
    unittest.main()
