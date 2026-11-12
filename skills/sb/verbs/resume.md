# /sb resume [effort]

A run stopped (a usage limit, a crash, a context that ran out) or the owner says "continue" or
"reorient me". Pick up where the work is, never where a summary says it was.

1. **Find the trail.** The files `sbmap status <map>` lists (`checkpoint.md`, `handoff.md`, then
   the run boards naming it, newest first) and the claimed tickets. In the repo:
   `git log --oneline` since the checkpoint's base, the ledger it names, `git status --short`.
2. **Reconcile the trail with the tree.** For each ticket the trail calls in flight:
   - committed, verified or verifiable now → resolve it if the run died before recording it
   - uncommitted edits in its paths → read the diff; finish it or say why not
   - claimed, no commit, its claimant not running → stale: `sbmap set <map> <NNN> status=open`,
     then claim it as yours
   - a map, ticket or checkpoint that lost content → recover it from Obsidian's file history
     ([reference/obsidian.md](../reference/obsidian.md))

   Completed work is never re-dispatched.
3. **Say where things are** in three lines or fewer: done since the checkpoint, in flight, next;
   rulings the dead session made go on the checkpoint, linked. If the owner only asked to be
   reoriented, stop here.
4. **Continue** under the recorded contract, at the step the trail stopped on (in a night run,
   `tonight` step 6, or step 5 for a run board with nothing logged yet: the owner chose the cleared
   start; otherwise the handoff's next step). Update the checkpoint before the first dispatch.
