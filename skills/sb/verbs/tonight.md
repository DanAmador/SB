# /sb tonight [hours] [map]

The owner is about to leave the machine (a night, a nap, a trip). Turn the vault's frontier into a
queue that fills the window, get **one** confirm while the owner is still here, then run it unattended to
the end. Default window: 8 h. Default map: this repo's open maps, in the order `sbmap maps` lists.

Two phases with a hard line between them: **propose** (the owner is present; one round of questions) and
**run** (the owner is gone; nothing waits on them).

**One repo or several.** A night whose maps span more than one repo runs as an **operator**: this
session holds the contract, the checkpoint and every commit check, and each repo gets its own
**lane session** (the host's session tool, one per repo, in that repo's checkout) that claims,
dispatches implementers and resolves on its own map. The *Operator* lines below say what changes; a
one-repo night skips them.

## Propose

1. **Read the world.** No questions yet.
   - `sbmap maps --repo <repo path>` for this repo's maps; `sbmap status` and `sbmap check` on each
     candidate. `status` also names any handoff or checkpoint to read.
   - `git status --short`, the branch, `git log --oneline -15`. Dirty files you did not make are a
     peer's: name them.
   - Live peers: other sessions on this repo (the host's session list, loaded if it is deferred), and
     every claimed ticket with its `claimed_by` (`sbmap status` lists them). A claim whose claimant is not running is stale.
   - Every session on the account that shares the usage budget, the owner's own included (a game
     session in another repo counts), and the host's usage windows with their reset times.
   - The contract ([reference/contract.md](../reference/contract.md)), resolved from map Notes, repo, defaults.
   - *Operator:* `sbmap maps` without `--repo`, then the steps above per repo.
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
   - A tier and model per ticket, and one for the orchestrator ([reference/models.md](../reference/models.md)):
     mid by default; capable only for a ticket that passes the *hard* test there, with its reason
     ("hard: migrates serialized assets + changes 9 callers"). Count the hard ones; past a quarter of
     the queue, propose an architecture ticket instead.
   - Lanes: every queued ticket needs `paths` (the files or folders it will change). Set any missing
     ones from the code the ticket names (`sbmap set <map> <NNN> paths=a,b`), then take the split
     from `sbmap lanes <map> --max <the contract's agent cap> --json`; never pick lanes by eye.
   - A live peer under a one-agent contract: the default is to start once the peer is idle, doing
     code-only work until then. That default becomes a proposal question.
   - *Operator:* each lane session drafts its own queue, `paths` and implementer briefs in its repo
     (no code, no new tickets yet) and messages the operator; the operator merges them into the one
     proposal and splits the agent cap between lanes, one implementer per lane by default. A scope
     the owner gives a lane directly reaches the operator as that lane's message and replaces its queue.
4. **Present one proposal**, in the owner's shape ([reference/output.md](../reference/output.md)), in
   plain text, in this order:
   1. One line: what "go" starts (map, tickets, lanes, until what clock time).
   2. One line: what the vault and reconciliation gave you (🗺️ closed, moved, half-built).
   3. The queue per lane: ticket name link · tier/model · hours, then its `why`; ≤5 visible,
      the rest folded; then what is not queued and why (👤 the owner's, blocked deeper).
   4. What the owner will *see* in the morning, per ticket; say plainly when a ticket is invisible structure.
   5. ⚠️ peers and contract conflicts, with the agent count at once (lanes plus peers) against the cap.
   6. Questions the evidence raised, each with ➡️ its default, applied if the owner says only "go". None is a
      fine number.
   7. Tests: what runs per ticket, what runs once, or that nothing does, and the ruling behind it.

   Wait for the owner's answer. "go" / "yes" accepts everything; edits ("drop X", "no lane B") apply and
   then go without a second round. This is the run's only stop for the owner.

## Run

5. **Launch.** Write the contract into the map's Notes from
   [templates/launch-contract.md](../templates/launch-contract.md), with the night's order. Create or
   update the vault checkpoint from [templates/checkpoint.md](../templates/checkpoint.md)
   (`<map folder>/checkpoint.md`, overwritten in place). Keep the machine awake if the host offers
   it. Then `sbmap diagram <map> --write`.
   - *Operator:* one file for the night, `wayfinder/runs/<date>-tonight.md`, a row per lane, holding
     the contract with each lane's own Where, checks and hard rules; each map's Notes points at it.
     A lane's brief is a section of that file, never a file of its own. Send each lane GO with the checkpoint's path and its order. Each lane keeps the
     machine awake too.
   - Tell every peer outside the run the usage gate, in a message, so the budget has one rule.
6. **Per ticket, in order:**
   0. Read the usage windows. Past the contract's usage gate, start nothing: wait for the reset
      (step 7).
   1. Claim before any work: `sbmap claim <map> <NNN> --by "<session title or harness/model>"`.
   2. Dispatch a fresh implementer on the ticket's model, passing `model:` explicitly (mid tier unless
      the ticket was queued hard), from
      [templates/implementer-brief.md](../templates/implementer-brief.md). The
      `subagent-driven-development` skill is the per-task engine when present: its review and fix
      rounds run on the mid tier.
   3. Verify the report against the tree yourself: the commit exists, touches only the ticket's
      paths, and the contract's per-ticket checks ran with results.
   4. Resolve via CLI:
      `sbmap resolve <map> <NNN> --gist "<one line>" --answer "<commit, verified, rulings, model>" [--commit <sha>]`
      Automatically stamps `## Answer`, resolves status, appends Decisions line to `map.md`, and syncs Route.
      Run `sbmap check <map>`, update checkpoint. Then the next ticket.
   5. At the end of a map's batch, rewrite its `## In plain words` (where it stands now).

   *Operator:* the lane does 0–2 and reports its commit and checks, with the usage it read; the
   operator does 3 in the lane's checkout and logs it in the checkpoint; then the lane does 4. The
   lane claims its next ticket without waiting for that check.
7. **Hold the line while unattended.**
   - A question is a ruling: take the recommendation, write `R: …, cost if wrong: …` on the ticket and in
     the checkpoint, continue. No question cards.
   - A mid-tier ticket that fails its checks: retry it once on the capable tier, the failed report in
     the brief, and record the escalation in the checkpoint.
   - A ticket that fails twice the same way: write what was tried on the ticket, leave it `open` with
     a `## Comments` note, move to the next.
   - The usage gate is a pause, not a stop: finish the ticket in flight, then wait for the reset time
     the host's usage windows give (a scheduled wake-up, not a poll) and carry on.
   - A usage limit or a crash costs nothing, because the checkpoint is current after every ticket:
     the next session runs `/sb resume`.
   - A lane whose queue empties before the window ends pings the owner's phone once (the host's push
     notification), then stops; the other lanes carry on.
   - The run stops only on the contract's stop conditions. Reporting midway is not one.
8. **Close the night.**
   - Run the slow suite if the contract says so.
   - Run the final whole-run review on the capable tier, with **one** fix wave; *operator:* one per lane.
   - Write the checkpoint's *Morning digest*: the shape `/sb morning` prints; *operator:* once, in
     the night's checkpoint, every lane in it.
   - Power off only if the owner said so tonight.
