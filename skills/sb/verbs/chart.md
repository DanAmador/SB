# /sb chart <idea>

A brain-dump becomes a vault map: a destination, the decisions it needs, and tickets an agent can
later run alone. This replaces the wayfinder skill's *Chart the map*: load no other skill's files.

1. **Scan existing context:** other maps' Decisions (`sbmap maps --repo <path>`) and the repo's
   ADRs. Say in one line what bears on it.
2. **Grill:** destination first, then breadth-first. Every question carries ➡️ a recommendation; ask
   in rounds of ≤5.
3. **Initialize the map:** `sbmap init <repo>/<effort> --title "<title>" --why "<why, in the owner's words>" --said "<owner's dictation, verbatim>" --destination "<dest>" --done-when "<dw>"`. Its `--why` becomes the map's `## In plain words`.
4. **Author tickets:**
   `sbmap new <map> --title "<title>" --why "<problem → what changes, plain words>" --type <type> --question "<question>" --done-when "<done-when>" [--out "<what it leaves alone>"] [--said "<owner's words>"] [--blocked-by 624,625] [--paths a,b]`
   - `--why`, `--said` and `--out` follow [SKILL.md](../SKILL.md#every-ticket-and-map-says-why-in-the-owners-words).
   - Each sized to one session (~1.5 h). Fewer, bigger-reason tickets beat many slices: a slice
     whose why is only "part of X" belongs in X's Question as a step.
   - `--paths`: the files or folders it will change, when the code already says. `sbmap lanes` runs
     tickets with disjoint paths in parallel; a ticket without paths runs alone.
   - Structural decisions are `architecture` tickets.
5. **Verify:** `sbmap check <map>` clean, `sbmap verify <map>`. With Obsidian running,
   `obsidian open path="wayfinder/<repo>/<effort>/map.md"`.
6. **Read it back (plain-reader check).** Read the map's plain-words section and each ticket's
   title + why (`sbmap info <map>`), nothing else, and fix what fails before step 7:
   - [ ] The owner's words are quoted (`--said`) wherever they gave a reason.
   - [ ] Each why says the problem and what the owner will see, in plain words: no class names, internal codes or bare ticket numbers (a measurement with its unit is fine).
   - [ ] Each Done-when can be checked by running or looking.
   - [ ] No ticket's why is only "part of X".
   - [ ] At most 3 open questions remain (grilling tickets or Not yet specified), each with a ➡️ default.
   - [ ] Every ticket serves the Destination.

   Report one line: `✅ plain-reader check passed`, or `⚠️ fixed: <what>`. Only then ask the owner.
7. **Readiness check.** For each frontier ticket: could an agent start it tonight with no question?
   Chat: "<N> tickets, <R> ready for `/sb tonight`, <G> need a talk first", the map's link, and
   the open questions with their ➡️ defaults.

Research tickets resolve at once in parallel subagents (the research skill); their findings go to
`<map>/research/<topic>.md` in the vault, linked from the ticket. Charting resolves nothing else.
