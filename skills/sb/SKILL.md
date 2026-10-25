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

- **Vault:** `$SB_VAULT`, else `~/Documents/Second Brain`. Maps live in `wayfinder/`.
- **`sbmap` CLI:** `python3 <this skill's dir>/scripts/sbmap.py` (run without args to list all commands).
  - 🔒 **Token rule: Author and inspect 100% through the CLI.** Never use `read_file`, `write_file`, or `edit_file` on tickets or maps. Use `sbmap show` to read tickets, `sbmap new` with `--question` and `--done-when` to create, `sbmap comment` for rulings, and `sbmap resolve` with `--answer`. Changes auto-sync the Route diagram.
  - 🔒 **Token rule: Never load external skills or the full vault.** The contract, ticket types, and output rules are self-contained here.
- **Ticket types:** `task` (concrete unit, ~1.5 h), `grilling` (clarification), `research` (subagent spike in `<map>/research/`), `prototype` (throwaway code), `architecture` (structural design with mermaid).
- **Obsidian CLI:** when the app is running, `obsidian` adds search, backlinks, renderer, and file history: [reference/obsidian.md](reference/obsidian.md).

## Output contract (succinct, high-information, ADHD-friendly)

- **Line 1 is the action or decision he can take now.**
- Bullets, short. ≤5 visible per group.
- **Status emojis only:** ✅ landed · 🎮 needs play · 👤 his call · ⚠️ problem/unverified · ⏳ running · 🔒 rule · 🗺️ map change. Never decorative.
- Refer to tickets by name with number link: `[<name>](<path>)`.
- Every question carries `➡️ recommendation`. Silence = accepted on recommendation.
- End with one action in under two minutes. Zero conversational filler.

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
