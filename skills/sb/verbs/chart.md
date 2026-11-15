# /sb chart <idea>

A brain-dump becomes a vault map: a destination, the decisions it needs, and tickets an agent can
later run alone. This replaces the wayfinder skill's *Chart the map*: load no other skill's files.

1. **Scan existing context:** other maps' Decisions (`sbmap maps --repo <path>`) and the repo's
   ADRs. Say in one line what bears on it.
2. **Grill:** destination first, then breadth-first. Every question carries ➡️ a recommendation; ask
   in rounds of ≤5.
3. **Initialize the map:** `sbmap init <repo>/<effort> --title "<title>" --why "<why, in the owner's words>" --said "<owner's dictation, verbatim>" --destination "<dest>" --done-when "<dw>"`. Its `--why` becomes the map's `## In plain words`.
4. **Author tickets:**
   `sbmap new <map> --title "<title>" --why "<problem → what changes, plain words>" --type <type> --question "<question>" --done-when "<done-when>" [--out "<what it leaves alone>"] [--said "<owner's words>"] [--blocked-by 624,625] [--paths a,b] [--tier opus] [--check owner]`
   - **Title**: one sentence on what is true once it is done, about 60 characters; the rest goes in `--why`.
   - `--why`, `--said` and `--out` follow [SKILL.md](../SKILL.md#every-ticket-and-map-says-why-in-the-owners-words).
   - Each sized to one session (~1.5 h). Fewer, bigger-reason tickets beat many slices: a slice
     whose why is only "part of X" belongs in X's Question as a step.
   - `--paths`: the files or folders it will change, when the code already says. `sbmap lanes` runs
     tickets with disjoint paths in parallel; a ticket without paths runs alone.
   - Structural decisions are `architecture` tickets.
   - **One layer per ticket.** The hub's code and its contract in one ticket, the page that shows it in
     the next, `--blocked-by` the first. Tickets that edit the same file get a `--blocked-by` chain now,
     so they never meet at landing.
   - `--done-when` names something a command can check (a test, a script's output, a file), so the
     hub's queue can run the ticket alone; set the map's checks once,
     `sbmap mapset <map> checks="cmd; cmd"`, from the repo's fast loop ([hub.md](../reference/hub.md)).
     Write it as a numbered list (`1. …\n2. …`), one test or command per item, so a reviewer ticks
     each one. Then:
     - **A real-data line** whenever the code reads what another part makes: "Real data: a test
       feeds it what `<that part>` really writes, not a hand-written fixture." Tests on data the
       worker wrote themself pass while the real thing fails.
     - **A next-step line** whenever the ticket keeps or changes something that lives on: what
       happens to it when the ticket is queued again, stopped, or the hub restarts.
     - **A shared-word line** when the ticket changes a state or word other tickets use: "every open
       ticket of this map that uses `<word>` gets a comment on what changed".
     - A screenshot item says what the picture must show, not only that it exists.
   - **Who checks it** (`--check`): `tests` (the default) or `owner`. Anything only the owner can
     do (tap a link on the phone, judge a look, play it) is its own `--check owner` ticket: the
     hub never gives it to a worker and lists it under Waits for you.
   - **Model** (`--tier`): `sonnet` (the default) or `opus` for a ticket judged hard. It is always
     written, so the board shows it.
5. **Verify:** `sbmap check <map>` clean, `sbmap verify <map>`. With Obsidian running,
   `obsidian open path="wayfinder/<repo>/<effort>/map.md"`.
6. **Read it back (plain-reader check).** Read the map's plain-words section and each ticket's
   title + why (`sbmap info <map>`), nothing else, and fix what fails before step 7:
   - [ ] The owner's words are quoted (`--said`) wherever they gave a reason.
   - [ ] Each why says the problem and what the owner will see, in plain words: no class names, internal codes or bare ticket numbers (a measurement with its unit is fine).
   - [ ] Each Done-when is a numbered list a worker can check by running something; the looking is
         a `--check owner` ticket of its own.
   - [ ] A ticket whose code reads another part's data has a real-data line.
   - [ ] No ticket's why is only "part of X".
   - [ ] At most 3 open questions remain (grilling tickets or Not yet specified), each with a ➡️ default.
   - [ ] Every ticket serves the Destination.

   Report one line: `✅ plain-reader check passed`, or `⚠️ fixed: <what>`. Only then ask the owner.
7. **Readiness check.** For each frontier ticket: could an agent start it tonight with no question?
   Chat: "<N> tickets, <R> ready for `/sb tonight`, <G> need a talk first", the map's link, and
   the open questions with their ➡️ defaults.

Research tickets resolve at once in parallel subagents (the research skill); their findings go to
`<map>/research/<topic>.md` in the vault, linked from the ticket. Charting resolves nothing else.
