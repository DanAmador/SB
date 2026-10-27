# Architecture tickets

An **architecture ticket** (`type: architecture`) is a decision whose answer is a *structure*:
which modules exist and who depends on whom, how a flow runs, what a piece of data looks like,
which states a thing moves through. Its answer is a **mermaid diagram** plus the prose a diagram
cannot carry. Obsidian renders ```` ```mermaid ```` blocks natively, so the owner reads the
decision as a picture, in the vault, on any device.

## When to make one

While charting or capturing, when a question's honest answer is a box-and-arrow drawing:

- "where does X live, and what may it import?" → `flowchart` of modules and allowed arrows
- "what happens, in order, when Y?" → `sequenceDiagram`
- "what does Z hold, and how do the types relate?" → `classDiagram` / `erDiagram`
- "which states can W be in, and what moves it?" → `stateDiagram-v2`
- "what is this effort made of?" → `mindmap` (also the map's own overview)

A ticket that only *uses* a structure stays a `task`; it is blocked by the architecture ticket and
links it (`[[…|#NNN]]`, or `![[…#Answer]]` to embed the diagram itself) instead of redrawing it.
Obsidian's backlinks on the architecture ticket then list everything built on that structure.

## Build the least

Every structure starts from the `ponytail` skill's ladder (dietrichgebert/ponytail, MIT, pinned in
`skills-lock.json`), inlined here so no run has to load it. Stop at the first rung that holds:

1. Does it need to exist? A speculative need is skipped, in one line.
2. Does a tool the repo already has do it (a CLI, a library in the lockfile, the platform)? Use it.
3. Does the stdlib do it? Use it.
4. Can it be one line? One line.
5. Only then: the least new code that works, in the fewest files.

No interface with one implementation, no config for a value that never changes, no scaffolding
"for later". A deliberate shortcut with a known ceiling says so in a `ponytail:` comment naming the
ceiling and the upgrade. Never simplified away: validation at trust boundaries, error handling
that prevents data loss, security, anything the owner asked for. Non-trivial logic leaves one
runnable check behind.

## Resolving one

1. Read the code as it is. Draw **today** first, as its own diagram, when the change moves something.
2. Draw the **decision**: the target structure, the lowest rung of [the ladder](#build-the-least)
   that holds; every new node names the rung it beat in one line under the diagram. Every node is a real name (a file, type, module or
   glossary term from the repo's `CONTEXT.md`), never a placeholder.
3. Under the diagram, list each arrow or rule the diagram cannot show ("the bridge never imports
   `obsidian`"), and what was ruled without the owner (`R: …, cost if wrong: …`).
4. `sbmap verify <map>`: the diagram parses in Obsidian's own renderer, or it is not done.
5. The diagram is the single source of truth for that structure. A later ticket that changes it
   edits this ticket's Answer (dated) rather than drawing a rival copy.

The ticket body comes from [templates/architecture-ticket.md](../templates/architecture-ticket.md).

## The map's Route

Every `map.md` carries a generated **Route**: the tickets as a mermaid flowchart, blocking edges as
arrows, coloured by status (frontier blue, claimed amber, resolved green, blocked grey), shaped by
type (architecture tickets are hexagons). It replaces the visual frontier the GitHub tracker used to
draw. It is generated: `sbmap diagram <map> --write`, between `%% sb:diagram:start %%` and
`%% sb:diagram:end %%`. Edit tickets, then regenerate; never hand-edit the block.
