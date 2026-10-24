# Checkpoint: <effort>

Kept current by whoever is running the work, after every ticket, so a fresh agent can take over at
any point. **Read this first, then what it names.** Last updated: <date time>.

## Where things are

| track | branch / checkout | ledger | state |
|---|---|---|---|
| <map or plan> | `<branch>` in `<path>` | `<progress file, if any>` | <tickets done, in flight (who, which model), next> |

## How to resume

1. `git log --oneline <base>..` on the branch, then the ledger. Completed work is never re-dispatched.
2. A ticket marked `claimed` whose session is gone is yours: re-read its body and any partial diff.
3. The contract is in <map>'s Notes. <anything not yet written there>

## Rulings made without the owner

- R<n>: <ruling> · ticket <name> · cost if wrong: <…>

## Morning digest

<!-- /sb tonight writes this at the end of a run; /sb morning reads it -->
