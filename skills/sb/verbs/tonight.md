# /sb tonight [hours] [map]

The owner is about to leave the machine. Make the frontier runnable, queue it on the hub, get
**one** "go" while the owner is here, and leave: the hub runs the queue unattended
([hub.md](../reference/hub.md), *Tonight's queue*). No orchestrator session stays up. Default
window: 8 h. Default maps: this repo's open maps, in the order `sbmap maps` lists; several repos
queue into the same hub.

Two phases: **propose** (the owner is present; one round of questions) and **queue** (nothing
waits on them). The hub runs the night as a background service (`scripts/sbhub_service.sh
install`; `status` to check), never from this session, which can end before the queue does.
Without a running hub, see *No hub* at the end.

## Propose

1. **Read the world**, after SKILL.md's *Every verb starts here* step 1. No questions yet.
   - `sbmap status` and `sbmap check` on each candidate map; `sbhub queue` for what is already
     queued, running or failed.
   - `git status --short`, the branch, `git log --oneline -15` in each repo. Dirty files you did
     not make are a peer's or the owner's: name them. Workers commit on the current branch.
   - Live peers: other sessions on these repos and every `claimed_by`. A claim whose claimant is not
     running is stale.
   - The pool: `sbhub agents --scan`. Each account's headless login must work: an expired one
     shows as *sign in* on the page; the owner signs in (`CLAUDE_CONFIG_DIR=<dir> claude`, `/login`).
2. **Reconcile the map against the code.** For every frontier and claimed ticket, grep the log for
   its `Ticket:` trailer, the hashes it names and its nouns; read the code it names.
   - Done already → resolve it with the commit as evidence.
   - Partly done → it stays open; size only the remainder.
   - Superseded → fold it into its replacement, or rule it out of scope.
3. **Make the picks runnable and size them.** Unattended (the owner already gone), do this as a hub
   job (`sbhub queue job`) instead of in chat.
   - **Checks** per map from the contract's fast loop: `sbmap mapset <map> checks="cmd; cmd"`. A
     check that fails on today's tree fails every ticket: fix it first as the night's first ticket,
     or leave it out until that ticket lands.
   - Every pick needs a `Done when` a command can check and `paths` (where the worker starts; it may
     edit other files it needs, and the verdict names them): `sbmap set <map> <NNN> paths=a,b` from the
     code it names.
   - `tier=opus` on a ticket judged complex, by [models.md](../reference/models.md), with the
     reason as a comment ("Opus: migrates serialized assets and changes 9 callers").
   - Hours from this repo's commits closest in kind, ~1.5 h each. The pool's pacing decides how many
     run at once; queue about what the window holds, in map order. Tickets only the owner can close
     (a playtest, a call) never queue: list them as 👤.
4. **Write the proposal on the run board, then ask for "go".** The board is at the path
   `sbmap run <map>` prints, from [templates/checkpoint.md](../templates/checkpoint.md), with the
   map's wikilink so `sbmap status` finds it. Under `## Proposal`:
   1. What the vault and reconciliation gave you (🗺️ closed, moved, half-built).
   2. The queue: ticket name link · tier · hours · its `why` · what the owner will *see* in the
      morning (or "invisible structure"); then what is not ready and why.
   3. ⚠️ Peers, dirty trees and the pool: which accounts, each one's usage and reset.
   4. Each map's checks, and the ruling behind them.

   Chat, nothing else: what "go" queues (ticket count, accounts, about until when), the board's
   link, the questions the evidence raised each with ➡️ its default (applied on a bare "go"). Edits
   ("drop X") apply without a second round. This is the run's only stop for the owner.

## Queue

5. Write the contract into each map's Notes from
   [templates/launch-contract.md](../templates/launch-contract.md), dated.
6. `sbhub queue agents <pool>`, then `sbhub queue add <map> <NNN>...` (or `sb_queue`, or tick them
   on the page), then `sbhub queue resume`. Keep the machine awake if the host offers it.
7. Chat, one line: how many tickets, on which accounts, about when the queue ends, and the board's
   link. Then stop: the hub runs it, writes each verdict to the ticket, and [morning](morning.md)
   reads the results.

## No hub

When the hub cannot run, the old path: this session is the operator and runs the queue itself.

- Per ticket, in order: past the contract's usage gate start nothing and wait for the reset;
  `sbmap claim`; **one session per ticket** where the host can start sessions (`context: fresh`,
  model by tier, `permission_mode: auto`, `use_worktree: false`, the brief from
  [templates/session-brief.md](../templates/session-brief.md) filled by hand), else a fresh
  `implementer` agent with [templates/implementer-brief.md](../templates/implementer-brief.md);
  wait idle, no polling.
- Verify from git, the checks and the report file, as the hub's verdict does; then `sbmap resolve`
  and a log line on the board; rewrite the map's `## In plain words` at the end of its batch.
- Hold the line by the contract's *Unattended* and *Blocked* rules: rulings on the ticket and the
  board; a failed mid-tier ticket escalates once; one that fails twice the same way stays open with
  what was tried; arm one hourly heartbeat so the run survives lost wake-ups.
- Close the night: the slow suite if the contract says so, one whole-run review with one fix wave,
  the board's *Morning digest*, one chat line with the board's link.
