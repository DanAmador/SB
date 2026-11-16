---
wayfinder: ticket
operonId: 26766f7
number: 25
title: "When a ticket stops, who gets it next: the same model, Opus, or you"
why: "Today any Sonnet stop goes to Opus at three times the price, even when the stop was a narrow file list or a cut-off run that Opus cannot fix. This decides the rule before anything in the hub changes."
project: sb-workflow
aliases:
  - "#025"
  - "025"
status: Project.Planned
type: grilling
priority: A
tier: sonnet
check: tests
created: 2026-11-13
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
blocked_by:
  - "[[wayfinder/sb-workflow/night-spend/issues/done/024 Why each thrown-away run stopped, and what a second try would have needed|024]]"
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/grilling
---
> Owner, 2026-11-13: Owner, 2026-11-13: "Put it as a discussion and research ticket. We don't want to modify anything until discussed."

## Not this ticket

Vault cleanup and log placement are separate; pacing is separate.

## Question

Today any Sonnet stop goes to Opus at three times the price, even when Opus cannot fix it, such as a run cut off from outside (disk full, sign-in failing, the hub stopping) or a stop over a file outside the ticket's list. Proposed: cut-off runs resume on the same model and don't count as a try; file stops come to Needs you naming the file, and one yes widens the list; a run whose work is already committed resolves without a second run; Opus takes over only when Sonnet said the code was beyond it or failed a check its own change broke. Which rule should the hub follow?

## Options

- ➡️ The proposed rule, and a run may not ask for an extra file mid-run, since that lets work wander from the ticket
- The proposed rule, but a run may ask for one more file instead of stopping
- Keep today's rule: any Sonnet stop goes to Opus

## Done when

Each of the five has an answer written on this ticket, and the follow-up build task is written with its paths and checks.

## Comments

- **2026-11-14**: Owner rulings of 2026-11-14 that touch this discussion: a ticket whose work landed but which a second pass judges Partly or Not met gets one more try with the reviewer's findings, then comes to the owner (tickets 058 and 059). That covers runs that finished but fell short. The five questions here, about runs that stopped before finishing, are still open.

- **2026-11-15**: The question before it was split into options for the hub page:
  Decide, from the research table: (1) A run cut off from outside (disk full, sign-in failing, the hub stopping): resume on the same model from where it stopped? Default: yes, and it does not count as a try. (2) A run that stopped for a file outside its list: goes to Needs you naming the file, and one yes widens the list and ticks it again? Default: yes, never to Opus. (3) A run that stopped because the work was already done: the hub checks for an existing trailered commit and resolves without a second run? Default: yes. (4) When does Opus still take over? Default: only when Sonnet said the code itself was beyond it, or failed a check its own change broke. (5) Should a ticket be able to ask for one more file during the run, instead of stopping? Default: no for now, it widens drift.
