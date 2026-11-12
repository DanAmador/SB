---
name: sb
description: "Second-brain workflow: the owner's maps, tickets, night runs and wiki in the Obsidian vault. /sb <anything>: free text is the default, a verb is a shortcut; no argument shows the board."
disable-model-invocation: true
argument-hint: "[what you want, in your own words] or [chart|tonight|morning|resume|explain|close|learn|ask|handoff|capture|land]"
---

# sb: the vault is the hub

Maps, tickets, handoffs and run boards are plain markdown in the owner's Obsidian vault. A fresh
context in any tool starts from one line: *"Read `<vault file>` and do what it says."* The owner
reads the vault, not the chat: results are written there, and chat only points at them
([output](reference/output.md)).

- **Vault:** `$SB_VAULT`, else `~/Documents/Second Brain`. Maps live in `wayfinder/`.
- **`sbmap`:** `python3 <this skill's dir>/scripts/sbmap.py` (no args lists every command).
  🔒 Maps and tickets are written through it only: it writes the properties, wikilinks and the
  Route. Read a ticket with `sbmap show`.
- **Notes written by hand** (handoffs, reports, research): load `obsidian-markdown` first;
  `obsidian-bases` before editing a `.base`; `obsidian-cli` for vault reads sbmap lacks.
- **Ticket types:** `task` (one commit, ~1.5 h), `grilling` (a talk with the owner), `research`
  (a subagent spike into `<map>/research/`), `prototype` (throwaway code), `architecture` (a
  structure, drawn in mermaid: [architecture.md](reference/architecture.md)).

## The owner talks; you route

`/sb <anything>` is a request in the owner's words. Name the verb in one line ("→ chart, on
card-grammar") and run it. Two intents run in the order given.

| the owner says something like | verb |
|---|---|
| "where are we", "what's open", "what were agents doing", *(nothing)* | board: `sbmap info --repo <repo path>`, any checkpoint; name the verb that fits |
| "chart / draft / plan / let's think about X", a brain-dump | [chart](verbs/chart.md) |
| "add these as todos", playtest notes, "I noticed…" | [capture](verbs/capture.md) |
| "tonight", "overnight", "enqueue", "I'm going to bed" | [tonight](verbs/tonight.md) |
| "what happened", "I'm back", "what do I test" | [morning](verbs/morning.md) |
| "continue", "tokens are back", "reorient me", a dead session | [resume](verbs/resume.md) |
| "wait what", "I don't get it", "explain this", "what does X mean" | [explain](verbs/explain.md) |
| "write a handoff", "move to a new session" | [handoff](verbs/handoff.md) |
| "merge the worktrees", "bring the lanes home" | [land](verbs/land.md) |
| "close this map", "we're done here" | [close](verbs/close.md) |
| "learn from…", a source to keep | [learn](verbs/learn.md) |
| "what do we know about…" | [ask](verbs/ask.md) |

Nothing fits: do what was asked under the rules below, and say no verb applied.

## Every ticket and map says why, in the owner's words

Intent that lives only in a dictation never reaches the ticket. So:

- 🔒 **`--why`** on every ticket (sbmap requires it): one plain line, the problem and what changes
  for the player or user. Invisible structure says so: "nothing to see: lets 677 drop the string keys".
- 🔒 **`--said`**: the owner's dictation, verbatim, trimmed to the sentences that bear on this map
  or ticket.
- 🔒 **`--out`** when a neighbour is close: what this ticket leaves alone ("the clip planes stay
  separate"). An implementer that touches it has drifted.
- 🔒 **Every map opens with `## In plain words`**: two to five lines, why it exists (the owner's
  words) and where it stands (done, left, the owner's next decision). `sbmap summary <map> --text`;
  rewrite it when a batch resolves, at every handoff and at close.
- 🔒 **The map's scope holds.** A ticket that does not serve the Destination is a question to the
  owner: redraw the Destination, or start a new map. A map is never a backlog.

`sbmap check` flags a missing why or plain-words section; fill it from the history, or ask.

## Plain words

- 🔒 **Titles, whys, questions and buttons use the owner's words, not the code's.** Class names,
  internal codes ("P2a", "band D", "lanes", "probe pad") and bare ticket numbers stay out. A term
  the owner has not used gets five words of gloss the first time.
- A question's options say what the owner will *see* or *feel*: a button they cannot read later is
  a decision they did not make.

## Every verb starts here

1. **Read the vault first.** `sbmap info --repo <repo path>`, then `sbmap info <map>` for the map in
   play; `sbmap status <map>` for claims and the handoff, checkpoint and run boards it names;
   `sbmap wiki index --project <repo>` and `sbmap wiki find` the effort's nouns. Say in one line
   what they gave you, "nothing" included.
2. **Resolve the contract**: [contract.md](reference/contract.md) (commits, tests, models, lanes,
   the usage gate, blocked rules). `learn`, `ask` and `explain` skip it.
3. Run the verb.
4. **Write the result to the vault, then point at it**: [output.md](reference/output.md).

Reference: [models](reference/models.md), [architecture](reference/architecture.md) (and its
*Build the least* ladder), [the wiki](reference/wiki.md), [Obsidian CLI](reference/obsidian.md),
[templates](templates/).
