# Which model runs what

**Pick the tier by the work's shape, then the model by the tier.** Recommend one per ticket in every
proposal; never one model for everything.

| tier | the work | today (2026-10) | effort |
|---|---|---|---|
| **capable** | charting and grilling a map, a spec or plan, architecture tickets, the orchestrator, the final whole-branch review, and the **hard** tickets below | Opus 5.5; Fable 5.1 when the weekly allotment allows and the work is judgement-heavy (charting, specs, the final review) | high |
| **mid** | the default for implementation, design-heavy included when the ticket or its architecture ticket holds the design; per-task reviews and re-reviews; research reading; Explore; re-reading a broken wiki article in the code | Sonnet 5.5 | medium |
| **cheap** | the brief already holds the full code or an exact recipe; mechanical sweeps; cold-reading a handoff; judging a drifted wiki article against its diff | Haiku 5.5 | low |

- **Hard tickets earn Opus; the rest never do.** The tier is chosen when a ticket is queued, with a
  reason in a few words. A ticket is hard when it has **two or more** of:
  - it changes how data is stored or shared (serialized assets, a migration, a save format, an API);
  - it changes many callers at once, or the ticket itself calls it the risky one;
  - concurrency, timing, physics or anything that fails only sometimes;
  - no ticket or architecture ticket holds the design yet, so the implementer must decide it;
  - it already failed once on the mid tier.

  Fewer than a quarter of a night's tickets should be hard; more means the map needs an
  architecture ticket first, not more Opus.
- **Escalate, don't start high.** A mid-tier ticket that fails its checks once is retried once on
  the capable tier with the failed report in the brief; a second failure stops it.
- **Plan high, execute lower.** A ticket charted by the capable tier is written so a mid-tier agent
  can run it from the ticket alone ("write it so a sonnet agent could read it").
- **A second model checks the first** when the owner doubts a result: re-review on another tier.
- **Budget:** when the owner names what is left ("10% of the week"), spend it on the capable tier's
  work only and queue the rest for cheaper sessions.
- Record the model on the ticket's Answer and in the checkpoint, so a wrong model is caught in the morning.

Update the *today* column when the line-up changes; the tiers stay.
