# The Obsidian CLI

`obsidian` (on PATH, Obsidian ≥ 1.12 with the CLI enabled) talks to the **running** app: its search
index, link graph, renderer and file history. Every verb works from files alone; the CLI adds what
only Obsidian knows. It is there when `obsidian version` answers; when not, skip these steps and say
so in one line.

Calls take the vault by name (the last folder of `$SB_VAULT`) and vault-relative paths, quoted when
they hold spaces: `obsidian vault="<vault name>" read path="wayfinder/<repo>/<effort>/map.md"`.

| need | command |
|---|---|
| The frontier, as the owner's board shows it | `base:query path="wayfinder/<map>/board.base" view=Frontier format=paths` (one repo: `wayfinder/<repo>/board.base`; every map: `wayfinder/frontier.base`, view *Every frontier* or *Frontier by project*) |
| Who holds what right now | `base:query path="wayfinder/frontier.base" view="Claimed now" format=md` |
| What the vault beyond `wayfinder/` says about an idea or ticket | `search:context query="<nouns>" limit=10` |
| What points at a ticket before you change, merge or rule it out | `backlinks path="wayfinder/<map>/issues/<file>"` |
| Show the owner the result, diagrams rendered | `open path="<file>"`, at the end of a verb the owner is present for; never unattended |
| A vault file an agent clobbered (the vault has no git) | `history path=…`, `history:read path=… version=<n>`, then `history:restore`, saying which version and why |

Broken links and mermaid parsing go through `sbmap check` and `sbmap verify`, which ask Obsidian themselves.

## The owner's app

The app, its settings and the owner's notes are theirs. Read anything; write only `wayfinder/` and
`wiki/` (through `sbmap`; `Clippings/` is theirs). Plugins, themes, snippets, sync, restart and
reload, `delete`, the `dev:` tools, and Operon's filter sets and boards stay untouched. `eval` is
for read-only probes. Daily notes get written only when the owner asks.

The tracker's format (properties, wikilinks, Bases, Operon statuses) is the vault's
`wayfinder/README.md`. A bare ticket number in new text is a bug: `sbmap link` prints the link.
