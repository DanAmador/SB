# /sb morning

The owner is back, probably on a phone. Say what the run did and what waits on them, in one screen.

1. Read this repo's checkpoint(s) (the files `sbmap status` lists), their *Morning digest* if
   written, and `git log --oneline` since the run's base. A ticket still `claimed` with nobody
   running it is a run that died; say so.
2. Verify before you report: each ✅ names a commit that exists on the branch. A digest line you
   cannot back with the tree is ⚠️, not ✅.
3. Print, in this order, ticket names as links:
   - **👤 Your calls**: rulings made without the owner (`R: …`), forks waiting, each with ➡️ the
     default that stands on silence.
   - **🎮 Play these**: landed work whose Done-when needs the owner's hands; how to reach it in one line.
   - **✅ Landed**: ticket, commit sha, one line each: what changed for the player or user.
   - **⚠️ Didn't**: failed, skipped, unverified, and why.
   - **🌿 Branch**: name, commits ahead, unpushed/unmerged, dirty files.
   - The map's frontier now, and the Route link (`obsidian open` the map).
   - When `sbmap wiki backlog` counts any: "<N> sources wait to be learned (`/sb learn`)". A map
     the run finished: offer `/sb close <map>`.
4. Delete the `wayfinder/runs/` files, and their report folders, of runs older than the one you
   just read: a run file is read once, and the tickets keep what lasts.
5. End with one question: queue more now (→ `/sb tonight`), or rule on the calls first?
