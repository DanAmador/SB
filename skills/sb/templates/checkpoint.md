# Checkpoint: <effort | tonight <date> (<lanes>)>

Kept current by whoever is running the work, after every ticket, so a fresh agent can take over at
any point. **Read this first, then what it names.** Last updated: <date time>.

<!-- A night across repos: window <start> → <end>; peers sharing the budget and where they run. -->

## Where things are

| lane | track | branch / checkout | session | state |
|---|---|---|---|---|
| <lane, or "—" for one repo> | <map or plan> | `<branch>` in `<path>` (from `<sha>`) | <session title (id), or this one> | <tickets done, in flight (who, which model), next> |

<!-- A night across repos: the contract (templates/launch-contract.md) and each lane's order go here,
     then a ## Log, one line per ticket as the operator checks it. -->


## Proposal

<!-- tonight step 4: reconciliation, the queue per lane with whys and what the owner will see,
     what is not queued, peers and conflicts, tests. -->

## How to resume

1. `git log --oneline <base>..` on the branch, then the ledger. Completed work is never re-dispatched.
2. A ticket marked `claimed` whose session is gone is yours: re-read its body and any partial diff.
3. The contract is in <map>'s Notes, or above for a night across repos. <anything not yet written there>

## Rulings made without the owner

- R<n>: <ruling> · ticket <name> · cost if wrong: <…>

## Morning digest

<!-- written at the end of a run; /sb morning reads it -->
