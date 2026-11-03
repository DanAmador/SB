# The wiki

The wiki's format and tools are the **wikibrain** skill, pinned in `skills-lock.json` and installed
beside sb. Read its `reference/wiki.md` (`~/.agents/skills/wikibrain/reference/wiki.md`): the
layout, properties, links, the grounding invariant, *Writing a finding*, *Anchoring a source*,
*Sharing projects*, and the commands. `sbmap wiki <command>` runs its tools against the vault.

wikibrain knows nothing about sb; `sbmap wiki` adds sb's part around each command
(`scripts/wiki_bridge.py`):

- **Tickets and research notes are sources.** `<map>#NNN` in any ref (`--sources`, `set
  sources+=…`) becomes the ticket's full-path link; only a resolved ticket may be cited. Notes under
  `wayfinder/` are cited as they are and found by `find --raw`.
- **`check`** also flags a source that is an open ticket or another tracker note (a map, a
  handoff), and a bare `#NNN` in wiki prose (`sbmap link` prints the ticket's link).
- **`backlog`** also lists research notes and resolved research tickets no article cites.
- **`tend`** without `--repos` verifies the clones the maps name in `repo`.
- **`migrate`** relinks `wayfinder/` too; **`dump`** keeps the `tickets` property in the vault.
- After `check --fix` and `import`, sbmap fills each article's `tickets`: the resolved tickets its
  raw sources share a pull request or commit with.
