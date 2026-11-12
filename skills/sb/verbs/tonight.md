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

1. **Read the world**, after SKILL.md's *Every verb starts here* step 1. No questions yet.
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
   - A tier per ticket and for the orchestrator by [models.md](../reference/models.md): Sonnet
     preferred, Opus for a ticket judged complex, with the reason ("Opus: migrates serialized assets
     and changes 9 callers").
   - Lanes: every queued ticket needs `paths`; set missing ones from the code it names
     (`sbmap set <map> <NNN> paths=a,b`), then take the split from
     `sbmap lanes <map> --max <the contract's agent cap> --json`, never by eye.
   - A live peer under a one-agent contract: default to starting once it is idle, code-only work
     until then, as a proposal question.
   - *Operator:* each lane session drafts its queue, `paths` and briefs in its repo (no code, no new
     tickets yet) and messages the operator, who merges them into one proposal and splits the agent
     cap, one implementer per lane by default. A scope the owner gives a lane directly replaces its queue.
4. **Write the proposal on the run board, then ask for "go".** The board is at the path
   `sbmap run <map>` prints (`wayfinder/<project>/runs/<date>-<map name>/<date>-<map name>.md`; the
   run's briefs and reports go in that folder), from
   [templates/checkpoint.md](../templates/checkpoint.md), with the map's wikilink so `sbmap status`
   finds it. It holds the contract, a row per ticket (model, paths or ports, session, state), a log,
   and under `## Proposal`:
   1. What the vault and reconciliation gave you (🗺️ closed, moved, half-built).
   2. The queue per lane: ticket name link · tier/model · hours · its `why` · what the owner will
      *see* in the morning (or "invisible structure"); then what is not queued and why.
   3. ⚠️ Peers and contract conflicts, with the agents at once (lanes plus peers) against the cap.
   4. Tests: what runs per ticket, what runs once, or nothing, and the ruling behind it.

   Chat, nothing else:
   1. What "go" starts: map, ticket count, lanes, until what clock time.
   2. The board's link.
   3. Questions the evidence raised, each with ➡️ its default, applied on a bare "go". None is fine.
   4. The two ways to start:
      - **"go"**: the run starts here at once. Use it when leaving the machine.
      - **"`/clear`, then `/sb resume <board path>`"**: the same run from a cleared session, about
        15% cheaper, since every operator turn here re-reads the planning conversation. Shown only
        past ~60k of context.

   Either accepts everything; edits ("drop X", "no lane B") apply, then the run starts without a
   second round. This is the run's only stop for the owner: after either, nothing waits on them.

## Run

5. **Launch.** Write the contract into the map's Notes from
   [templates/launch-contract.md](../templates/launch-contract.md), with the night's order, and
   apply the owner's edits to the run board. Keep the machine awake if the host offers it.
   - *Operator:* one board for the night, `sbmap run --shared tonight` (one project's lanes:
     `sbmap run <project> tonight`), a row per lane, holding
     the contract with each lane's Where, checks and hard rules; each map's Notes points at it. A
     lane's brief is a section of that file. Send each lane GO with the file's path and its order.
   - Tell every peer outside the run the usage gate, in a message, so the budget has one rule.
6. **Per ticket, in order:**
   0. Past the contract's usage gate, start nothing: wait for the reset (step 7).
   1. `sbmap claim <map> <NNN> --by "<session title or harness/model>"`, before any work.
   2. **One session per ticket** when the host can start sessions: each ticket is a row the owner
      can open and steer, and the operator gets a short note instead of the whole report. Start it
      with `initiation: user_asked`, `context: fresh`, `model` by tier, `effort: medium` for Sonnet,
      `permission_mode: auto`, `wake_when_done: true`, `name: ticket-<NNN>`, title
      `<ticket name> (<map name> <NNN>)`, `use_worktree: false` in the main tree, and the brief from
      [templates/session-brief.md](../templates/session-brief.md), naming `<run name>` (the
      board's, `<date>-<map name>`) as its `--parent`. Log the session's link on the
      board. Then **wait idle**: no polling; the host wakes you when it ends a turn. Usage is read
      once per ticket boundary, never in a loop.
      - No session tool, or a start refused (a turn woken by a timer cannot start one): dispatch a
        fresh `implementer` agent with [templates/implementer-brief.md](../templates/implementer-brief.md),
        `model: opus` for a complex ticket, and log the fallback on the board. Lookups go to the
        `scout` agent. The `subagent-driven-development` skill is the per-task engine when present;
        its review and fix rounds run on the mid tier.
   3. Verify against the tree yourself, from git, the per-ticket checks and the report file: the
      commit exists, touches only the ticket's paths, and the checks pass with counts. Open the
      session's transcript only when those disagree.
   4. `sbmap resolve <map> <NNN> --gist "<one line>" --answer "<commit, verified, rulings, model>" [--commit <sha>]`,
      then `sbmap check <map>` and a log line on the board.
   5. At the end of a map's batch, rewrite its `## In plain words`.

   At each ticket boundary, `sbhub report --agent <run name> --role orchestrator --done <n> --total
   <N> --note "<next ticket name>"`. A resource only one agent may use at a time (the Unity editor,
   a port) is taken with `sbhub lock <name> --by <agent>` and released with `sbhub unlock` after
   ([hub.md](../reference/hub.md)).

   *Operator:* the lane does 0–2 and reports its commit, checks and the usage it read; the operator
   does 3 in the lane's checkout and logs it on the board; then the lane does 4, claiming its
   next ticket without waiting for that check.
7. **Hold the line while unattended**, by the contract's *Unattended* and *Blocked* rules.
   - Rulings go on the ticket and on the board. A failed mid-tier ticket escalates once
     ([models.md](../reference/models.md)), recorded on the board.
   - A ticket that fails twice the same way: write what was tried on it, leave it `open` with a
     `## Comments` note, move on.
   - The usage gate is a pause: finish the ticket in flight, then wait for the reset time with a
     scheduled wake-up (not a poll) and carry on. That woken turn cannot start a session, nor can
     the agent wake-ups after it: until the owner's next message, tickets run as `implementer` agents.
   - Wake-ups from finished sessions can stop arriving after a long chain with no word from the
     owner. Arm one hourly heartbeat (the host's scheduled task or cron): a heartbeat turn that
     finds nothing in flight and the queue not empty dispatches the next ticket as an agent.
   - A lane whose queue empties early pings the owner's phone once (the host's push
     notification), then stops; the others carry on.
   - The run stops only on the contract's stop conditions. Reporting midway is not one.
8. **Close the night.**
   - The slow suite, if the contract says so.
   - The final whole-run review on the capable tier, with **one** fix wave; *operator:* one per lane.
   - The board's *Morning digest*, in the sections [morning](morning.md) step 3 names; *operator:*
     once, every lane in it. Chat: one line and the board's link.
   - Power off only if the owner said so tonight.
