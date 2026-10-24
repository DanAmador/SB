# /sb resume [effort]

A run stopped (a usage limit, a crash, a session that ran out of context) or the owner says
"continue" or "reorient me". Pick up exactly where the work is, never where a summary says it was.

1. **Find the trail.** In the vault: this repo's checkpoint and handoff (newest first), the maps'
   claimed tickets. In the repo: `git log --oneline` since the checkpoint's base, the ledger it
   names, `git status --short`.
2. **Reconcile the trail with the tree.** For each ticket the trail calls in flight:
   - committed and verified → resolve it if the run died before recording it
   - committed but unrecorded and unverified → verify now, then resolve
   - uncommitted edits in its paths → read the diff; finish it or say why not
   - claimed, no commit, its `claimed_by` session not running → the claim is stale;
     `sbmap set <map> <NNN> status=open`, then claim it as yours
   - a map, ticket or checkpoint that lost content (a dead session's half-write) → recover it from
     Obsidian's file history ([reference/obsidian.md](../reference/obsidian.md)); the vault has no git
   Completed work is never re-dispatched.
3. **Say where things are** in five lines or fewer: done since the checkpoint, in flight, next, and any
   ruling the dead session made. If the owner only asked to be reoriented, stop here.
4. **Continue** under the recorded contract, at the step the trail stopped on: inside a night run that
   is `tonight` step 6; otherwise the handoff's next step. Update the checkpoint before the first dispatch.
