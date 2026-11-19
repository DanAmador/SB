# /sb run [map]

The owner stays at the machine and runs the work through the hub with this chat. Queue the picks,
press Start, join this chat to the run as its integrator, and land each finished ticket with the
owner until they say stop. When the owner is about to leave instead, use [tonight](tonight.md):
it queues, starts a run that ends by itself, and exits.

This chat is the run's integrator, not its operator: the hub starts the workers, runs their checks
and hands each finished ticket here ([hub.md](../reference/hub.md), *Joining a run*). Your id for
every command below is this session's id (`$SB_HUB_AGENT` when set). Without a running hub
(`scripts/sbhub_service.sh status`), say so and offer [tonight](tonight.md)'s *No hub* path.

## Start

1. **Read the world and make the picks runnable**: [tonight](tonight.md) steps 1 to 3, with the
   owner here, so ask each question as it comes up, one at a time, each with ➡️ its default.
2. **One "go"**, in chat: the tickets (name · tier · hours · what the owner will see), the accounts,
   and what this chat does (lands each finished ticket with you). Edits apply without a second round.
3. **Queue and start.**
   - `sbhub report --agent <id> --map <project>/<map>`, so the hub knows who runs the map.
   - `sbhub queue add <map> <NNN>... --by <id>` (or `sb_queue` with `agent`): `--by` sends each
     finished ticket back to this chat.
   - `sbhub night start --name "<what this run is for>"`, without `--drain`: a run you start ends
     only on Stop. The hub refuses a second start while a run is live; then join that run, never
     stop it.
4. **Join**: `sbhub night join --agent <id> --role integrator` (or `sb_join`). The board shows this
   chat from now on.
5. **Watch**: start `sbhub watch --chat <id>` in the background (the host's background command, not a
   loop of your own). It exits 0 when a ticket is handed to this chat or comes back to it, which wakes
   you; 3 when this chat is no longer joined; 2 when the hub is down. Chat one line: how many tickets
   run, the board's link, and that you wait for the first one.

## Each finished ticket

6. The watch prints, per ticket, its commit, branch, worktree and the land and send-back commands.
   Review it in its worktree, never in the repo's main folder:
   - `git -C <tree> log --oneline <base>..HEAD` and the diff; the ticket's `Done when` (`sbmap show`);
     the report in its run folder.
   - Chat, per ticket: one line on what changed and whether it meets its `Done when`, then ➡️ land
     or send back with what to change.
7. On the owner's word (a standing "land what passes" counts for later tickets too):
   - `sbhub integrate <key> land --agent <id>` (or `sb_integrate`): the hub lands it under the repo's
     landing lock and resolves it as your review. A ticket it could not land comes back.
   - `sbhub integrate <key> back --agent <id> --note "<what to change>"`: built again, the worker told
     the note.
8. Start the watch again, and wait.

## The owner builds one here

9. When the owner wants this chat to build a queued ticket itself:
   `sbhub take <key> --agent <id>` (or `sb_take`). It prints the ticket's worktree, branch and brief;
   work and commit there only, with the ticket's `Ticket:` trailer. Then
   `sbhub done <key> --agent <id>` (or `sb_done`): the hub runs its checks and hands it on, or prints
   why it failed (exit 4) so you fix it and say done again.

## Stop

10. On the owner's "stop": `sbhub night stop`: running tickets finish, nothing new starts, and the
    run ends once its work is judged. Land what is still handed here, or leave it to the hub with
    `sbhub night leave --agent <id>`, which hands it on or lands it.
11. Chat, one line: what landed, what went back, what is still open, and the board's link.
    [morning](morning.md) reads the same results later.
