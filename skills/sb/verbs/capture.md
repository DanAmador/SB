# /sb capture [map]

The owner hands over findings, playtest notes or "add these as todos". Each lands on a map as a
ticket an agent can later run from the ticket alone.

1. **Pick the map**: the one the owner named, else the open map of this repo whose Destination the
   items serve. Items serving none: say so and offer `chart`; never stretch a map to fit.
2. **Split** the input into items, one behaviour each. An item that states what is true (a
   measurement, a gotcha, how a tool behaves) rather than work to do is knowledge: learn it as
   pasted text through *Learn a source* in [learn.md](learn.md), not as a ticket.
3. **Match before you create** (`sbmap show <map> <NNN>`). An open ticket covering it gets
   `sbmap comment <map> <NNN> --text "<note>"`; a resolved ticket it contradicts is reopened with
   `sbmap set <map> <NNN> status=open`.
4. **Create the rest:**
   `sbmap new <map> --title "<sentence stating the behaviour>" --why "<the problem in one plain line>" --said "<the owner's words, verbatim>" --type task --question "<question>" --done-when "<done-when>" [--blocked-by 624,625]`
   (`--type architecture` for a structural question; the flags as in [SKILL.md](../SKILL.md#every-ticket-and-map-says-why-in-the-owners-words)).
5. `sbmap check <map>` clean, `sbmap verify <map>`.
6. Report one line per item: 🆕 created, 💬 added to, ♻️ reopened, each with its name link; a
   learned item as `learn` reports it.
