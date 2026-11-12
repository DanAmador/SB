### The night-run contract (<date>)

<!-- Into the map's ## Notes, or the night's board (`sbmap run --shared tonight`) across repos.
     Later rulings edit it in place, dated. -->

- **Where:** repo `<path>`, branch `<branch>` (from `<sha>`), <main tree | worktree on request>;
  across repos, one line per lane. Never push; never merge into `main`.
- **Lanes:** <one session per ticket, serial | one serial agent | lane A owns `<paths>`, lane B owns `<paths>` | one lane session per
  repo, one implementer each>. Max <2> agents at once across the account, reviewers and the owner's
  own sessions counted.
- **Usage:** past 90% of the 5-hour window, finish the ticket in flight and start nothing new until
  it resets (~<reset times>). <peers that agreed to the same gate>.
- **Commits:** one per ticket, explicit pathspec. <files never to commit, e.g. editor-dirtied assets>.
- **Per ticket, verify with:** <the repo's fast loop, exact commands>.
- **Once, at the end:** <the slow suite, or "none: owner ruling <date>">.
- **Hard rules:** <the repo's own: e.g. no screen reads while the display sleeps; stop Play before
  editing; the owner's live services (dev server, store, vault) off or read-only>.
- **Models:** orchestrator <capable model>; implementers <mid model>, except the complex ones: <ticket →
  capable model, reason>. A mid ticket that fails once retries once on <capable model>.
- **Context:** hand off at ~150k; one ticket per session or implementer context; the operator starts
  from the run board `<board path>`.
- **Blocked:** by `~/.claude/skills/sb/reference/output.md` *Unattended*: a decision that qualifies
  there goes to `sbhub ask`; any other is ruled on the spot. Either way it is written on the ticket
  as `R:`; keep going.
- **Stop when:** the queue is empty, the window (<hours> h, until ~<time>) is over, or the same
  failure repeats twice. Nothing else stops the run.
- **Claim** with `sbmap claim`. **Resolve** with `sbmap resolve --answer` (commit, what was verified
  and how, what was **not**, model), then the checkpoint.

### The night's order

1. <ticket name link> · <tier> · ~<h>
2. …
