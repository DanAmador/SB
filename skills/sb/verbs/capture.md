# /sb capture [map]

The owner hands over findings, playtest notes or "add these as todos". Each one lands on a map as a
ticket an agent can later run from the ticket alone.

1. **Pick the map**: the one he named, else the open map of this repo whose Destination the items
   serve. Items serving no open map: say so and offer `chart`.
2. **Split** the input into items, one behaviour each. Quote his words on each.
3. **Match before you create.** For each item, search the map's ticket titles and bodies: an existing
   open ticket that covers it gets a dated `## Comments` entry instead of a twin; a resolved ticket it
   contradicts gets reopened with the reason.
4. **Create** the rest with `sbmap new <map> --title "<sentence stating the behaviour>" --type task`
   (`architecture` when the item is a structure question, see
   [reference/architecture.md](../reference/architecture.md)), then fill *Question* and *Done when*.
   Every ticket or map the item mentions is a wikilink (`sbmap link <map> <NNN>`). Wire blockers in a
   second pass with `sbmap block`. Add each to the map's order if it has one.
5. `sbmap check <map>` clean, `sbmap diagram <map> --write`, `sbmap verify <map>`.
6. Report one line per item: 🆕 created, 💬 added to, ♻️ reopened, each with its name link.
