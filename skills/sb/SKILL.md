---
name: sb
description: "Second-brain workflow: chart a map in the vault, queue a night run, read the morning, hand off, resume, capture, land. /sb <verb>; no verb shows the board."
disable-model-invocation: true
argument-hint: "[chart|tonight|morning|handoff|resume|capture|land] [args]"
---

# sb: the vault is the hub

The owner's Obsidian vault is where every agent, session and harness meets. Maps and tickets,
handoffs and checkpoints live there as plain markdown, so a fresh context in any tool starts from
one line: *"Read `<vault file>` and do what it says."* This skill is the owner's repeatable rituals
around that vault, each one a verb.

- **Vault:** `$SB_VAULT`, else `~/Documents/Second Brain`. Maps live in `wayfinder/`; its
  `README.md` is the tracker's rulebook. Read it once per session before touching a map. Tickets
  are Obsidian notes: fields in **properties**, every reference a **wikilink**, a **Bases** board per map.
- **`sbmap`:** `python3 <this skill's dir>/scripts/sbmap.py` (no arguments prints every command).
  It reads what you never compute by eye (`maps`, `status`, `frontier`, `check`, `verify`) and writes
  what you never hand-type (`new`, `claim`, `block`, `set`, `resolve`, `link`, `diagram --write`,
  `board`). Run `diagram --write` after every change to a map's tickets.
- **Obsidian CLI:** when the app is running, `obsidian` adds its search, backlinks, renderer and
  file history: [reference/obsidian.md](reference/obsidian.md).

## Every verb starts here

1. **Read the vault first.** Find this repo's maps (`sbmap maps --repo <repo path>`) and their
   handoff/checkpoint files (`sbmap status <map>` names them); search the rest of the vault for the
   effort's nouns (`obsidian search:context`). Say in one line what they gave you, "nothing" included.
2. **Resolve the contract**: the rules this run works under. [reference/contract.md](reference/contract.md).
3. Run the verb.
4. Report in the owner's shape: [reference/output.md](reference/output.md).

## Verbs

| verb | when | file |
|---|---|---|
| *(none)* | "where are we?" Print `sbmap maps`, this repo's frontier and any checkpoint, then name the verb that fits | — |
| `chart <idea>` | a brain-dump becomes a map: grilling, tickets, architecture tickets, the Route | [verbs/chart.md](verbs/chart.md) |
| `tonight [hours] [map]` | the owner is leaving: reconcile, size, propose lanes and models, one confirm, then orchestrate unattended | [verbs/tonight.md](verbs/tonight.md) |
| `morning` | the owner is back: a phone-sized digest of what landed and what waits on them | [verbs/morning.md](verbs/morning.md) |
| `handoff` | context or tokens are running out, or work moves to another session or harness | [verbs/handoff.md](verbs/handoff.md) |
| `resume` | a session died, hit a limit, or the owner says "continue" / "reorient me" | [verbs/resume.md](verbs/resume.md) |
| `capture` | "add these as todos": feedback or findings become tickets on a map | [verbs/capture.md](verbs/capture.md) |
| `land` | lanes and worktrees come home: merge, clean up, list what to playtest | [verbs/land.md](verbs/land.md) |

Reference, reached from the verbs: [models](reference/models.md) (which tier runs what),
[architecture tickets](reference/architecture.md) (mermaid decisions), and the
[templates](templates/) every verb writes from.
