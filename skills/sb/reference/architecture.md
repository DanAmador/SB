# Architecture tickets

An **architecture ticket** (`type: architecture`) is a decision whose answer is a *structure*. Its
answer is a **mermaid diagram**, which Obsidian renders, plus the prose a diagram cannot carry.

## When to make one

While charting or capturing, when a question's honest answer is a box-and-arrow drawing:

- "where does X live, and what may it import?" → `flowchart` of modules and allowed arrows
- "what happens, in order, when Y?" → `sequenceDiagram`
- "what does Z hold, and how do the types relate?" → `classDiagram` / `erDiagram`
- "which states can W be in, and what moves it?" → `stateDiagram-v2`
- "what is this effort made of?" → `mindmap`

A ticket that only *uses* a structure stays a `task`, blocked by the architecture ticket, and links
it (`[[…|#NNN]]`, or `![[…#Answer]]` to embed the diagram) instead of redrawing it.

## Build the least

The `ponytail` skill's ladder (pinned in `skills-lock.json`), inlined so no run loads it. Stop at
the first rung that holds:

1. Does it need to exist? A speculative need is skipped, in one line.
2. Does a tool the repo already has do it (a CLI, a library in the lockfile, the platform)? Use it.
3. Does the stdlib do it? Use it.
4. Can it be one line? One line.
5. Only then: the least new code that works, in the fewest files.

No interface with one implementation, no config for a value that never changes, no scaffolding
"for later". A deliberate shortcut with a known ceiling gets a `ponytail:` comment naming the
ceiling and the upgrade. Never simplified away: validation at trust boundaries, error handling
that prevents data loss, security, anything the owner asked for. Non-trivial logic leaves one
runnable check behind.

## Resolving one

1. Read the code as it is. Draw **today** first, as its own diagram, when the change moves something.
2. Draw the **decision**: the lowest rung of [the ladder](#build-the-least) that holds; every new
   node names the rung it beat in one line under the diagram. Every node is a real name (a file,
   type, module or glossary term from the repo's `CONTEXT.md`), never a placeholder.
3. Under the diagram, each arrow or rule it cannot show ("the bridge never imports `obsidian`"), and
   what was ruled without the owner (`R: …, cost if wrong: …`).
4. `sbmap verify <map>`: the diagram parses in Obsidian's own renderer, or it is not done.
5. The diagram is the one source of truth for that structure: a later change edits this ticket's
   Answer (dated), never a rival copy.

The body comes from [templates/architecture-ticket.md](../templates/architecture-ticket.md).

## The map's Route

Every `map.md` carries a **Route**: the tickets as a mermaid flowchart that sbmap redraws on every
write, between `%% sb:diagram:start %%` and `%% sb:diagram:end %%`. Never hand-edit the block.
