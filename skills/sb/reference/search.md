# Search the vault before you write to it

The vault already holds most answers: past tickets, research, run notes, the wiki. An agent that
skips the search files a ticket that already exists, or re-researches something that was settled.
**Semantra** (search by meaning, not by keyword; the owner's own tool) finds a note even when it
uses different words from the query. It runs as `semantra` on the PATH; `semantra --help` lists
every option. Without it, the keyword fallbacks below still work.

## You need… → run

| you are about to… | run | you get |
|---|---|---|
| start any verb ("what do we already know about this?") | `semantra search "<the ask, in a sentence>" --vault "$SB_VAULT" --limit 8` | the closest notes anywhere in the vault: tickets, research, runs, wiki, each with the matching passage |
| file a ticket | `sbmap new …`: it checks for you | refused while an open ticket of the repo reads the same; add to that one with `sbmap comment`, or rerun with `--not-a-duplicate` when it is really different |
| answer "what does the wiki say about X" | `sbmap wiki find <terms> [--raw]` | wiki articles ranked by meaning (by keyword when Semantra is missing) |
| brief a worker or pick up a ticket | `semantra related "<ticket path>" --vault "$SB_VAULT" --limit 5` | the notes closest to that ticket: earlier tickets, research, runs on the same problem |
| see what blocks, links to or sits next to a note | `semantra links "<note>" --vault "$SB_VAULT" [--relation blocked_by]` | the note's neighbours in the vault's graph, under a second, no model |
| list every note under a tag | `semantra tag "<tag>" --vault "$SB_VAULT"` | the notes, nested tags included (`--exact` leaves them out) |
| find an exact string (a file name, an error, a number) | `grep -rl` / `sbmap show` | meaning search is the wrong tool for exact text |

`$SB_VAULT` unset means `~/Documents/Second Brain`. A note is named by its vault path, the path
without `.md`, or a unique file name.

## Read the answer like this

- **JSON when piped**, a `hits` list: `path`, `cosine` (0 to 1), and for `search` the `passage`
  that matched. Read the passage before you open the note.
- **Hits come in meaning-plus-keyword order**, so the list is not sorted by `cosine`. Cosines sit
  close together: on this vault a real match scores about 0.5 to 0.6, and unrelated notes about
  0.45. Treat the top 3 to 5 as leads to open, not answers.
- **Run notes crowd the hits** (`wayfinder/*/runs/`). Skip them unless you want what a night did.

## When it is slow

- A search first embeds every note that changed since the last one (turns it into numbers it can
  compare). After a night of notes that can take minutes and four cores. Warm, it answers in about
  3 seconds.
- A night that ends (`sbmap close --finished`) starts `semantra index` in the background, so the
  morning starts warm. Run `semantra index --vault "$SB_VAULT"` yourself before a burst of searches.
- `sbmap new` gives up on the check after 30 seconds (`SB_SEMANTRA_TIMEOUT`), says so on stderr and
  files the ticket anyway.
- Exit code 1, or a dead worker: the notes stay pending and the next run picks them up. Fall back
  to `sbmap wiki find --words` or grep; never block a run on Semantra.

## Where it comes from

The CLI is built in the owner's `semantic-graph-plugin-release` checkout (`pnpm run build:cli`; the
`plugin-release` branch, the only one whose search mixes in keyword matching), and
`~/.local/bin/semantra` links to its `packages/cli/dist/semantra.mjs`. It shares one index file
with the Obsidian plugin (`<vault>/.semantra/`). How it is shipped beyond this machine is still
open: the `semantra/agent-cli` map.
