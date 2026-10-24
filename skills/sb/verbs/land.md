# /sb land

Lanes and worktrees come home. The owner asks this as "have you merged all the worktrees?" or "merge
everything into one branch".

1. **Inventory.** `git worktree list`, `git branch --no-merged <working branch>`, and the running
   agents or sessions started from here. For each branch: commits ahead, last commit time, the
   ticket it belongs to.
2. **Ask once**, as a list with ➡️ defaults: which branches merge into the working branch, which stay.
   Never `main` without his explicit yes.
3. **Merge** each, one at a time, in ticket order. Run the repo's own pre-merge rules first (a Unity
   repo closes open scenes so the Editor does not save stale copies over the merge). After an asset
   merge, `git status --short`: a file you did not touch showing modified is a stale-copy write-back.
   Conflicts: resolve them, then run the contract's fast loop.
4. **Clean up** only what merged: remove its worktree (the host's cleanup tool when there is one),
   then the branch. List orphaned agents and batch processes; stop the ones this run started.
5. Update the checkpoint and the tickets each merge resolved, `sbmap diagram --write`, and end with
   the 🎮 list of what he should play now.
