---
wayfinder: ticket
operonId: b299e69
number: 122
title: "A ticket whose work cannot land into a checkout with unsaved edits waits for it, instead of failing and stalling its map"
why: "On 2026-11-15 three sk4te chase tickets passed their checks but failed at landing because the main checkout held unsaved edits to the same files, and the map then skipped the fourth; the same hit the run's timeline graph on sb-workflow. After this finished work waits on its branch, says which files block it, and lands on its own once they are saved or cleared, while the rest of the map goes on."
project: sb-workflow
aliases:
  - "#122"
  - "122"
status: Project.Planned
type: task
priority: A
tier: opus
check: tests
created: 2026-11-16
filed_during: "Night of 2026-11-15, 15:22"
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/scripts/sbhub.py
  - skills/sb/scripts/sbqueue.py
  - skills/sb/hub/packages/contract
  - tests/test_hub_runner.py
  - tests/test_queue_rules.py
tags:
  - project/sb-workflow
  - status/open
  - type/task
  - wayfinder/map/sb-workflow-night-spend
  - wayfinder/ticket
run_minutes: 90.2234
check_minutes: 0
tries: 1
model: opus
account: personal
night: night-20261115-152229
outcome: failed
---
> Owner, 2026-11-16: Owner, 2026-11-16: "we need to land all the broken tickets, have we made htis more robust ?"

## Not this ticket

Not the repo-health line before a run starts (hub-typed 055) and not reviews dirtying the checkout (098); this is only what happens at landing.

## Question

When git merge --ff-only refuses because the checkout's uncommitted files overlap the branch, the item becomes 'landed on its branch, waiting for a clean checkout' instead of failed: it keeps its branch and worktree, names the blocking files on the item and in one alert, does not count as a failure, and does not stop later tickets of its map that do not touch those files. The hub retries the landing when the overlapping files are clean (each loop pass, cheap: git status on those paths), rebasing the branch onto HEAD first when HEAD moved. A branch that no longer rebases cleanly becomes a named outcome for the owner.

## Done when

1. A test: a branch whose files overlap an unsaved edit in the checkout ends 'waiting for a clean checkout', not failed, with the blocking files named. 2. A test: once the edit is committed or cleared, the next loop pass lands it, rebasing when HEAD moved. 3. A test: a later ticket of the same map that touches other files still runs. 4. A test: a rebase conflict ends as a named outcome for the owner, the branch kept. 5. The contract fixtures are regenerated and every check exits 0.

## Comments

- **2026-11-16**: Build on what is already there, 2026-11-16. Another session has unsaved work in the main checkout (sbhub.py, not committed when this was queued) that extends Recheck into 'Land again': a failed run whose commit waits in its kept worktree (landing_failed) is rebased, checked, landed and reviewed without its worker running again. That is the manual half. This ticket is the automatic half: the hub calls that same path by itself once the blocking files are clean, and it never fails the item or stalls its map meanwhile. Use landing_failed and the recheck path if they are on main when you start; if they are not, do not write a second copy, say so in the report. Owner, 2026-11-16: "land it as the next ticket and ensure the workflow becomes more robust to these issues". Known risk for this very run: if the checkout still has unsaved edits to sbhub.py or sbqueue.py when this lands, its own landing fails the old way; its branch and worktree are kept, and Land again lands it once they are committed.

- **2026-11-16**: R: landing_failed and Land again are not on main (they sit only as unsaved edits in the main checkout), so I did not copy them; the automatic landing reuses the recheck path already on main (rebase onto HEAD, checks, fast-forward). cost if wrong: once Land again lands, two entry points reach the same finish(recheck) path; small to merge.

- **2026-11-16**: R: a waiting landing is a new item state, unclean ('waits for a clean checkout'), with the blocking files on the item and one macOS alert when it enters it. It keeps its claim, branch and worktree, is not a failure and not in the failure streak. Its map stays current; tickets blocked by it wait, others run. cost if wrong: a file never saved keeps the night open until the owner clears it or drops the ticket.

- **2026-11-16**: R: the blocking files are the branch's changed files that git status shows unsaved (modified, staged or untracked), worked out only after git merge --ff-only refuses; each loop pass runs git status on those paths and, once clean, the checks run again before landing even when HEAD did not move. cost if wrong: one extra checks run per waited landing.

- **2026-11-16**: R: a branch that no longer rebases ends as the existing named outcome 'could not land: its commits conflict with <sha> in <files>. Its work stays on branch ... in ...': failed, commented on the ticket, claim released, branch and worktree kept (Land again can pick it up). cost if wrong: it counts toward the three-in-a-row pause.

- **2026-11-16**: The sb hub's run of this ticket failed (opus on agent personal): ran past 90 minutes
  Its work stays on branch sb/sb-workflow-night-spend-122 in /Users/danamador/.sb-hub/worktrees/sb-workflow-74ed4c/sb-workflow-night-spend-122.
