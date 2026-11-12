# /sb morning

The owner is back, probably on a phone. The run board's *Morning digest* is the report; chat points
at it.

1. Read this repo's checkpoint(s) (the files `sbmap status` lists), their *Morning digest* if
   written, and `git log --oneline` since the run's base. A ticket still `claimed` with nobody
   running it is a run that died; say so.
2. Verify before you report: each ✅ names a commit that exists on the branch. A digest line you
   cannot back with the tree becomes ⚠️.
3. **Bring the digest up to date on the board** (write it if the run died before it did), ticket
   names as links, in this order:
   - **👤 Your calls**: rulings made without the owner (`R: …`), forks waiting, each with ➡️ the
     default that stands on silence.
   - **🎮 Play these**: landed work whose Done-when needs the owner's hands; how to reach it in one line.
   - **✅ Landed**: ticket, commit sha, one line each: what changed for the player or user.
   - **⚠️ Didn't**: failed, skipped, unverified, and why.
   - **🌿 Branch**: name, commits ahead, unpushed/unmerged, dirty files.
   - The map's frontier now. When `sbmap wiki backlog` counts any: "<N> sources wait to be learned
     (`/sb learn`)". A map the run finished: offer `/sb close <map>`.

   Chat: one line of counts ("✅ 6 landed · 🎮 2 to play · 👤 1 call · ⚠️ 1 didn't"), the board's
   link, then the 👤 calls with their ➡️ defaults. `obsidian open` the board.
4. Delete the run folders (`<project>/runs/<run>/`, and `wayfinder/runs/<run>/` across projects) of
   runs older than the one you just read: a run is read once, and the tickets keep what lasts.
