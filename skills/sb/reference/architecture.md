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

## Resolving one

1. Read the code as it is. Draw **today** first, as its own diagram, when the change moves something.
2. Draw the **decision**: the target structure. Every node is a real name (a file, type, module or
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
