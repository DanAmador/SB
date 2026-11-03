# /sb chart <idea>

A brain-dump becomes a vault map: a destination, the decisions it needs, and tickets an agent can
later run alone. This is wayfinder's *Chart the map*, run on the vault tracker with the owner's habits
built in.

1. **Rules & scope.** Do not load external skill files or vault docs. Author 100% through `sbmap` CLI.
2. **Scan existing context:** check other maps' Decisions (`sbmap maps --repo <path>`) and local ADRs. Say in one line what bears on it.
3. **Grill:** destination first, then breadth-first. Every question carries ➡️ a recommendation; ask in rounds of ≤5; when the owner answers some, list the rest as accepted on recommendation.
4. **Initialize the map:** `sbmap init <repo>/<effort> --title "<title>" --why "<why, in the owner's words>" --said "<owner's dictation, verbatim>" --destination "<dest>" --done-when "<dw>"`. It creates `map.md` (opening with `## In plain words`), `board.base` and the Route.
5. **Author tickets via CLI:**
   `sbmap new <map> --title "<title>" --why "<problem → what changes, plain words>" --type <type> --question "<question>" --done-when "<done-when>" [--out "<what it leaves alone>"] [--said "<owner's words>"] [--blocked-by 624,625] [--paths a,b]`
   - `--said` is the owner's own dictation, copied verbatim and trimmed to the sentences that bear on
     the map or ticket, never paraphrased; sbmap dates and quotes it beside the why.
   - `--why` is the owner's reason, quoted from the grilling where they gave one; `--out` names the
     neighbouring ticket or area it must not touch.
   - Each sized to one session (~1.5 h). Fewer, bigger-reason tickets beat many slices: a slice
     whose why is only "part of X" belongs in X's Question as a step.
   - `--paths`: the repo files or folders it will change, when the code already says. `sbmap lanes` runs
     tickets with disjoint paths in parallel; a ticket without paths runs alone.
   - Structural decisions are `architecture` tickets.
   - Diagram syncs automatically on each ticket.
6. **Verify:** `sbmap check <map>` clean, `sbmap verify <map>`. If Obsidian is open, `obsidian open path="wayfinder/<effort>/map.md"`.
7. **Read it back (plain-reader check).** Print the map's plain-words section and each ticket's title
   + why, nothing else, and run this on that list (Spec Kit's spec gate), fixing what fails before step 8:
   - [ ] The owner's words are quoted (`--said`) wherever they gave a reason.
   - [ ] Each why says the problem and what the owner will see, in plain words: no class names, internal codes or bare numbers.
   - [ ] Each Done-when can be checked by running or looking.
   - [ ] No ticket's why is only "part of X".
   - [ ] At most 3 open questions remain (grilling tickets or Not yet specified), each with a ➡️ default.
   - [ ] Every ticket serves the Destination.

   Report one line: `✅ plain-reader check passed`, or `⚠️ fixed: <what>`. Only then ask the owner.
8. **Readiness check.** For each frontier ticket: could an agent start it tonight with no question?
   Say which are ready, which need a grilling session, and offer `/sb tonight` for the ready ones.

Research tickets resolve at once in parallel subagents (the research skill); their findings go to
`<map>/research/<topic>.md` in the vault, linked from the ticket. Charting resolves nothing else.
