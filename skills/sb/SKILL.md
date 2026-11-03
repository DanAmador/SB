---
name: sb
description: "Second-brain workflow: the owner's maps, tickets, night runs and wiki in the Obsidian vault. /sb <anything>: free text is the default, a verb is a shortcut; no argument shows the board."
disable-model-invocation: true
argument-hint: "[what you want, in your own words] or [chart|tonight|morning|resume|close|learn|ask|handoff|capture|land]"
---

# sb: the vault is the hub

The owner's Obsidian vault is where every agent, session and harness meets. Maps and tickets,
handoffs and checkpoints live there as plain markdown, so a fresh context in any tool starts from
one line: *"Read `<vault file>` and do what it says."*

- **Vault:** `$SB_VAULT`, else `~/Documents/Second Brain`. Maps live in `wayfinder/`.
- **`sbmap` CLI:** `python3 <this skill's dir>/scripts/sbmap.py` (no args lists every command).
  🔒 Maps and tickets are authored through it only (`init`, `summary`, `new`, `set`, `comment`,
  `claim`, `resolve`, `close`); read a ticket with `sbmap show`. It writes the properties, wikilinks and Route.
- **Ticket types:** `task` (one commit, ~1.5 h), `grilling` (a talk with the owner), `research`
  (a subagent spike into `<map>/research/`), `prototype` (throwaway code), `architecture` (a
  structure, drawn in mermaid: [reference/architecture.md](reference/architecture.md)).

## The owner talks; you route

The owner dictates. `/sb` followed by anything is a request in the owner's words, not a parse error. Read
the intent, say in one line which verb you are running ("→ chart, on card-grammar"), and run it.
Two intents in one message ("close and learn", "draft and for tonight") run in that order.

| the owner says something like | verb |
|---|---|
| "where are we", "what's open", "what were agents doing", *(nothing)* | board: `sbmap maps`, this repo's frontier with each ticket's why, any checkpoint; name the verb that fits |
| "chart / draft / plan / let's think about X", a brain-dump | [chart](verbs/chart.md) |
| "add these as todos", playtest notes, "I noticed…" | [capture](verbs/capture.md) |
| "tonight", "overnight", "enqueue", "I'm going to bed" | [tonight](verbs/tonight.md) |
| "what happened", "I'm back", "what do I test" | [morning](verbs/morning.md) |
| "continue", "tokens are back", "reorient me", a dead session | [resume](verbs/resume.md) |
| "write a handoff", "move to a new session" | [handoff](verbs/handoff.md) |
| "merge the worktrees", "bring the lanes home" | [land](verbs/land.md) |
| "close this map", "we're done here" | [close](verbs/close.md) |
| "learn from…", a source to keep | [learn](verbs/learn.md) |
| "what do we know about…" | [ask](verbs/ask.md) |

Nothing fits: do what the owner asked, under the rules below, and say no verb applied.

## Every ticket and map says why, in the owner's words

The owner and their agents disagree when intent lives in one dictation and never reaches the ticket.
So intent is written down where both read it:

- 🔒 **Every ticket has a `why`** (`sbmap new --why`, required): one line, plain words, the problem
  and what changes for the player or user once it is done. Quote the owner where they said it.
  Invisible structure says so: "nothing to see: lets 677 drop the string keys".
- 🔒 **`--out` when a neighbour is close**: what this ticket leaves alone ("the clip planes stay
  separate"). An implementer that touches what `Not this ticket` names has drifted.
- 🔒 **Every map opens with `## In plain words`**: two to five lines, why the map exists (the owner's words)
  and where it stands now (what is done, what is left, what the owner decides next). Write it with `sbmap summary <map> --text`, and rewrite it
  whenever a batch of tickets resolves, at every handoff and at close. The Decisions list is the log; this is
  the summary.
- 🔒 **The map's scope holds.** A new ticket that does not serve the Destination is a question to
  the owner: redraw the Destination, or start a new map. Never let a map quietly become a backlog.
- `sbmap check` lists tickets with no `why` and maps with no plain-words section as notes. Fill
  them from the ticket's own history, or ask.

## Plain words

- 🔒 **Titles, whys, questions and buttons are in the owner's words, not the code's.** No class
  names, internal codes ("P2a", "band D", "lanes", "probe pad") or ticket numbers standing alone.
  A term the owner has not used gets five words of gloss the first time, or is not used.
- A question's options say what the owner will *see* or *feel* for each, not what the code does. The
  owner approves buttons fast; a button they cannot read later is a decision they did not make.
- 🔒 **Build the least:** reuse what exists, delete over deprecate, fewer knobs the player sees. The
  ladder is in [reference/architecture.md](reference/architecture.md#build-the-least).

## Every verb starts here

1. **Read the vault first.** `sbmap maps --repo <repo path>`, then `sbmap status <map>` (it names
   the map's `handoff.md` and `checkpoint.md`, and `wayfinder/runs/` files; 🔒 never a file at the
   `wayfinder/` root). `sbmap wiki index --project <repo>`, and `sbmap wiki find` the effort's
   nouns. Say in one line what they gave you, "nothing" included.
2. **Resolve the contract**: [reference/contract.md](reference/contract.md). `learn` and `ask` skip it.
3. Run the verb.
4. **Report in the owner's shape** ([reference/output.md](reference/output.md)): line 1 is what the
   owner can do now; ≤5 short bullets; status emojis only; ticket names as Obsidian links; every
   question with ➡️ a recommendation (silence accepts it); the detail goes in the vault, not chat.

Reference: [models](reference/models.md) (which tier runs what), [architecture](reference/architecture.md),
[the wiki](reference/wiki.md) (`sbmap wiki` is the pinned wikibrain skill's command),
[Obsidian CLI](reference/obsidian.md), and the [templates](templates/) every verb writes from.
