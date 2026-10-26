# The Obsidian CLI

`obsidian` (on PATH, Obsidian ≥ 1.12 with the CLI enabled) talks to the **running** app: its search
index, its link graph, its renderer, its file history. The vault's files stay the source of truth,
and every verb works from files alone. The CLI adds what only Obsidian knows. It is there when
`obsidian version` answers; when it does not (the app is closed, a headless box, the Windows
machine), skip these steps and say so in one line.

Every call targets the vault by name and takes vault-relative paths, quoted when they hold spaces:
`obsidian vault="Second Brain" read path="wayfinder/sk4te-one-tether/map.md"`.

| need | command |
|---|---|
| The frontier, as the owner's board shows it | `base:query path="wayfinder/<map>/board.base" view=Frontier format=paths` (agrees with `sbmap frontier`; one repo's maps: `wayfinder/<repo>/board.base`; every map at once: `wayfinder/frontier.base`, view *Every frontier*, or *Frontier by project*) |
| Who holds what right now | `base:query path="wayfinder/frontier.base" view="Claimed now" format=md` |
| Read the vault beyond `wayfinder/` for what bears on an idea or ticket | `search:context query="<nouns>" limit=10` (Obsidian's index, every note) |
| What points at a ticket before you change, merge or rule it out | `backlinks path="wayfinder/<map>/issues/<file>"` |
| Broken links in a map | `sbmap check <map>` (it asks Obsidian) |
| Every mermaid block in a map parses in the renderer the owner sees | `sbmap verify <map>`, after writing any diagram |
| Show the owner the result, with its diagrams rendered | `open path="<file>"`, at the end of a verb he is present for; never during an unattended run |
| A vault file an agent clobbered (the vault has no git) | `history path=…`, `history:read path=… version=<n>`, then `history:restore` saying which version and why |

## The owner's app

The app, its settings and his own notes are his. Read anything; write only the tracker
(`wayfinder/`) and the wiki (`wiki/`, through `sbmap wiki` and the article prose; `Clippings/` is
his). Plugins, themes, snippets, sync, restart and reload, `delete`, and the `dev:` tools
stay untouched. `eval` is for read-only probes (`sbmap verify` uses it). Daily notes are his notes:
a run writes there only when he asks.

## What the tracker gives Obsidian

Since 2026-10-25 the tracker is shaped so Obsidian sees all of it (the vault README has the format):

- **Properties** hold every ticket's fields, so the properties panel, search (`[status:open]`) and
  Bases read them. Write them through `sbmap` (`claim`, `set`, `block`, `resolve`), which keeps the
  YAML and the links well-formed.
- **Wikilinks** carry every reference, in `blocked_by`, `map` and prose, so the graph, backlinks and
  `unresolved` cover the whole route. A bare number in new text is a bug; `sbmap link` prints the link.
- **Bases**: each map's `board.base` (views *Frontier*, *All tickets*, *Board*) is embedded in its
  `map.md`; `wayfinder/<repo>/board.base` spans one repo's maps; `wayfinder/frontier.base` spans every
  map. Statuses are Operon's (`Project.Planned` … `Project.Finished`), and the formulas read them.
- **Project and Operon**: every ticket and map carries `project: <repo>` and the tag `project/<repo>`,
  and `priority` is an Operon letter (S highest, C the default). Operon's own boards filter on those or
  on the folder; its filter sets and kanban presets are the owner's settings, never written by an agent. The frontier is a formula over `blocked_by`, so
  the board stays live with nothing regenerated. `sbmap board <map>` rewrites a map's board.
