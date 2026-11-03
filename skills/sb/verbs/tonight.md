# /sb tonight [hours] [map]

The owner is about to leave the machine. Turn the frontier into a queue that fills the window, get
**one** confirm while the owner is here, then run it unattended to the end. Default window: 8 h.
Default map: this repo's open maps, in the order `sbmap maps` lists.

Two phases: **propose** (the owner is present; one round of questions) and **run** (nothing waits
on them).

**Several repos:** this session is the **operator**: it holds the contract, the checkpoint and
every commit check, and each repo gets a **lane session** (the host's session tool, one per repo,
in its checkout) that claims, dispatches and resolves on its own map. *Operator* lines say what
changes; a one-repo night skips them.

## Propose

1. **Read the world**, beyond the shared start. No questions yet.
   - `sbmap status` and `sbmap check` on each candidate map.
   - `git status --short`, the branch, `git log --oneline -15`. Dirty files you did not make are a
     peer's: name them.
   - Live peers: other sessions on this repo (the host's session list, loaded if deferred) and every
     `claimed_by`. A claim whose claimant is not running is stale.
   - Every session sharing the usage budget, the owner's included, and the host's usage windows
     with their reset times.
   - *Operator:* `sbmap maps` without `--repo`, then the above per repo.
2. **Reconcile the map against the code.** For every frontier and claimed ticket, grep the log for
   its `Ticket:` trailer, the hashes it names and its nouns; read the code it names.
   - Done already → resolve it with the commit as evidence.
   - Partly done → it stays open; size only the remainder.
   - Superseded → fold it into its replacement, or rule it out of scope.
3. **Size and pick.**
   - Hours from this repo's commits closest in kind (`git log --stat`), ~1.5 h each, never under
     the contract's per-ticket floor.
   - Fill about 80% of the window, in map order. A blocked ticket counts once its blockers queue
     ahead of it. Tickets only the owner can close (a playtest, a call) never queue: list them as 👤.
   - A tier per ticket and for the orchestrator by [models.md](../reference/models.md): mid by
     default, capable only past its *hard* test, with the reason ("hard: migrates serialized assets
     + changes 9 callers").
   - Lanes: every queued ticket needs `paths`; set missing ones from the code it names
     (`sbmap set <map> <NNN> paths=a,b`), then take the split from
     `sbmap lanes <map> --max <the contract's agent cap> --json`, never by eye.
   - A live peer under a one-agent contract: default to starting once it is idle, code-only work
     until then, as a proposal question.
   - *Operator:* each lane session drafts its queue, `paths` and briefs in its repo (no code, no new
     tickets yet) and messages the operator, who merges them into one proposal and splits the agent
     cap, one implementer per lane by default. A scope the owner gives a lane directly replaces its queue.
4. **Present one proposal**, in plain text, in this order:
   1. What "go" starts (map, tickets, lanes, until what clock time).
   2. What the vault and reconciliation gave you (🗺️ closed, moved, half-built).
   3. The queue per lane: ticket name link · tier/model · hours, then its `why`; ≤5 visible, the
      rest folded; then what is not queued and why.
   4. What the owner will *see* in the morning, per ticket; say so when it is invisible structure.
   5. ⚠️ peers and contract conflicts, with the agents at once (lanes plus peers) against the cap.
   6. Questions the evidence raised, each with ➡️ its default, applied on a bare "go". None is fine.
   7. Tests: what runs per ticket, what runs once, or nothing, and the ruling behind it.

   "go" accepts everything; edits ("drop X", "no lane B") apply, then go without a second round.
   This is the run's only stop for the owner.

## Run

5. **Launch.** Write the contract into the map's Notes from
   [templates/launch-contract.md](../templates/launch-contract.md), with the night's order. Write
   `<map folder>/checkpoint.md` from [templates/checkpoint.md](../templates/checkpoint.md),
   overwritten in place. Keep the machine awake if the host offers it.
   - *Operator:* one file for the night, `wayfinder/runs/<date>-tonight.md`, a row per lane, holding
     the contract with each lane's Where, checks and hard rules; each map's Notes points at it. A
     lane's brief is a section of that file. Send each lane GO with the file's path and its order.
   - Tell every peer outside the run the usage gate, in a message, so the budget has one rule.
6. **Per ticket, in order:**
   0. Past the contract's usage gate, start nothing: wait for the reset (step 7).
   1. `sbmap claim <map> <NNN> --by "<session title or harness/model>"`, before any work.
   2. Dispatch a fresh `implementer` agent with the brief from
      [templates/implementer-brief.md](../templates/implementer-brief.md); add `model: opus` only
      for a ticket queued hard. Lookups go to the `scout` agent. The `subagent-driven-development` skill is
      the per-task engine when present; its review and fix rounds run on the mid tier.
   3. Verify the report against the tree yourself: the commit exists, touches only the ticket's
      paths, and the contract's per-ticket checks ran with results.
   4. `sbmap resolve <map> <NNN> --gist "<one line>" --answer "<commit, verified, rulings, model>" [--commit <sha>]`,
      then `sbmap check <map>` and the checkpoint.
   5. At the end of a map's batch, rewrite its `## In plain words`.

   *Operator:* the lane does 0–2 and reports its commit, checks and the usage it read; the operator
   does 3 in the lane's checkout and logs it in the checkpoint; then the lane does 4, claiming its
   next ticket without waiting for that check.
7. **Hold the line while unattended**, by the contract's *Unattended* and *Blocked* rules.
   - Rulings go on the ticket and in the checkpoint. A failed mid-tier ticket escalates once
     ([models.md](../reference/models.md)), recorded in the checkpoint.
   - A ticket that fails twice the same way: write what was tried on it, leave it `open` with a
     `## Comments` note, move on.
   - The usage gate is a pause: finish the ticket in flight, then wait for the reset time with a
     scheduled wake-up (not a poll) and carry on.
   - A lane whose queue empties early pings the owner's phone once (the host's push
     notification), then stops; the others carry on.
   - The run stops only on the contract's stop conditions. Reporting midway is not one.
8. **Close the night.**
   - The slow suite, if the contract says so.
   - The final whole-run review on the capable tier, with **one** fix wave; *operator:* one per lane.
   - The checkpoint's *Morning digest*, the shape `/sb morning` prints; *operator:* once, every lane in it.
   - Power off only if the owner said so tonight.
