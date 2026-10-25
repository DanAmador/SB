# /sb tonight [hours] [map]

The owner is about to leave the machine (a night, a nap, a trip). Turn the vault's frontier into a
queue that fills the window, get **one** confirm while he is still here, then run it unattended to
the end. Default window: 8 h. Default map: this repo's open maps, in the order `sbmap maps` lists.

Two phases with a hard line between them: **propose** (he is present; one round of questions) and
**run** (he is gone; nothing waits on him).

## Propose

1. **Read the world.** No questions yet.
   - `sbmap maps --repo <repo path>` for this repo's maps; `sbmap status` and `sbmap check` on each
     candidate. `status` also names any handoff or checkpoint to read.
   - `git status --short`, the branch, `git log --oneline -15`. Dirty files you did not make are a
     peer's: name them.
   - Live peers: other sessions on this repo (the host's session list, loaded if it is deferred), and
     every claimed ticket with its `claimed_by` (`sbmap status` lists them). A claim whose claimant is not running is stale.
   - The contract ([reference/contract.md](../reference/contract.md)), resolved from map Notes, repo, defaults.
2. **Reconcile the map against the code.** For every frontier and claimed ticket, check what the
   commits already did: grep the log for its `Ticket:` trailer, the hashes the ticket names, and its
   nouns; read the code it names.
   - Done already → resolve it with the commit as evidence.
   - Partly done (progress slices, a "left on this ticket" list) → it stays open; size only the remainder.
   - Superseded → fold it into the ticket that replaced it, or rule it out of scope.
   Done when every frontier ticket's remaining work is stated and genuinely unbuilt.
3. **Size and pick.**
   - Hours come from commits: find this repo's commits closest in kind (`git log --stat`), ~1.5 h
     each, never under the per-ticket floor from the contract.
   - Fill about 80% of the window, in map order. Blocked tickets count once their blockers are queued
     ahead of them. Tickets only the owner can close (a playtest, a call) never queue: list them as 👤.
   - A tier and model per ticket, and one for the orchestrator ([reference/models.md](../reference/models.md)).
   - Lanes: infer each ticket's file set from the code it names. A second lane only when the sets are
     disjoint and the contract allows more than one agent; write each lane's paths.
   - A live peer under a one-agent contract: the default is to start once the peer is idle, doing
     code-only work until then. That default becomes a proposal question.
4. **Present one proposal**, in the owner's shape ([reference/output.md](../reference/output.md)), in
   plain text, in this order:
   1. One line: what "go" starts (map, tickets, lanes, until what clock time).
   2. One line: what the vault and reconciliation gave you (🗺️ closed, moved, half-built).
   3. The queue per lane: ticket name link · tier/model · hours, one line of what it does; ≤5 visible,
      the rest folded; then what is not queued and why (👤 his, blocked deeper).
   4. What he will *see* in the morning, per ticket; say plainly when a ticket is invisible structure.
   5. ⚠️ peers and contract conflicts.
   6. Questions the evidence raised, each with ➡️ its default, applied if he says only "go". None is a
      fine number.
   7. Tests: what runs per ticket, what runs once, or that nothing does, and the ruling behind it.

   Wait for his answer. "go" / "yes" accepts everything; edits ("drop X", "no lane B") apply and
   then go without a second round. This is the run's only stop for him.

## Run

5. **Launch.** Write the contract into the map's Notes from
   [templates/launch-contract.md](../templates/launch-contract.md), with the night's order. Create or
   update the vault checkpoint from [templates/checkpoint.md](../templates/checkpoint.md)
   (`wayfinder/<effort>-checkpoint.md`). Keep the machine awake if the host offers it. Then
   `sbmap diagram <map> --write`.
6. **Per ticket, in order:**
   1. Claim before any work: `sbmap claim <map> <NNN> --by "<session title or harness/model>"`.
   2. Dispatch a fresh implementer on the ticket's model, from
      [templates/implementer-brief.md](../templates/implementer-brief.md). The
      `subagent-driven-development` skill is the per-task engine when present: its review and fix
      rounds run on the mid tier.
   3. Verify the report against the tree yourself: the commit exists, touches only the ticket's
      paths, and the contract's per-ticket checks ran with results.
   4. Resolve via CLI:
      `sbmap resolve <map> <NNN> --gist "<one line>" --answer "<commit, verified, rulings, model>" [--commit <sha>]`
      Automatically stamps `## Answer`, resolves status, appends Decisions line to `map.md`, and syncs Route.
      Run `sbmap check <map>`, update checkpoint. Then the next ticket.
7. **Hold the line while unattended.**
   - A question is a ruling: take the recommendation, write `R: …, cost if wrong: …` on the ticket and in
     the checkpoint, continue. No question cards.
   - A ticket that fails twice the same way: write what was tried on the ticket, leave it `open` with
     a `## Comments` note, move to the next.
   - A usage limit or a crash costs nothing, because the checkpoint is current after every ticket:
     the next session runs `/sb resume`.
   - The run stops only on the contract's stop conditions. Reporting midway is not one.
8. **Close the night.**
   - Run the slow suite if the contract says so.
   - Run the final whole-run review on the capable tier, with **one** fix wave.
   - Write the checkpoint's *Morning digest*: the shape `/sb morning` prints.
   - Power off only if the owner said so tonight.
