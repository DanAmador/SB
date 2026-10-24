### The night-run contract (<date>)

<!-- Written into the map's ## Notes by /sb tonight. Edit in place for later rulings, dated. -->

- **Where:** repo `<path>`, branch `<branch>` (from `<sha>`), <main tree | worktree on request>.
  Never push; never merge into `main`.
- **Lanes:** <one serial agent | lane A owns `<paths>`, lane B owns `<paths>`>. Max 2 agents at once,
  reviewers counted.
- **Commits:** one per ticket, explicit pathspec. <files never to commit, e.g. editor-dirtied assets>.
- **Per ticket, verify with:** <the repo's fast loop, exact commands>.
- **Once, at the end:** <the slow suite, or "none: owner ruling <date>">.
- **Hard rules:** <the repo's own: e.g. no screen reads while the display sleeps; stop Play before editing>.
- **Models:** <ticket → tier/model, or "per ticket, recorded on each Answer">.
- **Blocked:** take the recommendation, write it on the ticket as a ruling, keep going.
- **Stop when:** the queue is empty, the window (<hours> h, until ~<time>) is over, or the same
  failure repeats twice. Nothing else stops the run.
- **Claim** with `sbmap claim`. **Resolve** with `## Answer` (commit, what was verified and how,
  what was **not**, model; tickets named as wikilinks), then `sbmap resolve`, `sbmap diagram --write`,
  checkpoint updated.

### The night's order

1. <ticket name link> · <tier> · ~<h>
2. …
