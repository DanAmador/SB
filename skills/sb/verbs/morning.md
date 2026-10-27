# /sb morning

The owner is back, probably reading on a phone. Say what the run did and what waits on them, in
one screen.

1. Read this repo's checkpoint(s) in the vault, their *Morning digest* if written, the maps
   (`sbmap status`), and `git log --oneline` since the run's base. Check the claims: a ticket still
   `claimed` with nobody running it is a run that died; say so.
2. Verify before you report: each ✅ names a commit that exists on the branch. A digest line you
   cannot back with the tree is ⚠️, not ✅.
3. Print, in this order, each group ≤5 lines, ticket names as links:
   - **👤 Your calls**: rulings made without the owner (`R: …`), forks waiting. Each carries ➡️ the default
     that stands if they say nothing.
   - **🎮 Play these**: landed work whose Done-when needs the owner's hands; how to reach it in one line.
   - **✅ Landed**: ticket, commit sha, one line each.
   - **⚠️ Didn't**: failed, skipped, unverified, and why.
   - **🌿 Branch**: name, commits ahead, unpushed/unmerged, dirty files.
   - The map's frontier now, and the Route link (`obsidian open` the map, so it is on screen when they sit down).
   - The wiki's backlog, when `sbmap wiki backlog` counts any: "<N> sources wait to be learned
     (`/sb learn`)". A map the run finished: offer `/sb close <map>`.
4. End with one question: queue more now (→ `/sb tonight`), or rule on the calls first?
