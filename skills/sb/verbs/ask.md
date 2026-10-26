# /sb ask <question> [--save]

"What do I know about X?" answered from the vault's wiki, citing it. Writes nothing in the vault
unless the owner says to keep the answer. Format and commands: [reference/wiki.md](../reference/wiki.md).

1. **Find.** `sbmap wiki index --project <repo>`, then `sbmap wiki find --raw --project <repo>` with
   the question's terms *and* their synonyms (the repo is the one the owner is working in; leave
   `--project` off for a question about another repo or about everything); `--raw` reaches what is not compiled yet (research notes, resolved research tickets,
   clippings). With Obsidian running, also `search:context` across the vault. No `wiki/` at all →
   say so and offer `/sb learn`.
2. **Read** what was found: `sbmap wiki show` (`--full` for the notes the answer rests on), tickets
   with `sbmap show`. Note every Outdated or Disputed callout.
3. **Answer** in the owner's shape ([output.md](../reference/output.md)): line 1 is the answer.
   - Each claim cites its article as a markdown link to the file.
   - A claim from a raw note cites it and is marked ⚠️ not compiled.
   - A claim from your own training is marked as such; the wiki wins where they disagree.
   - A disputed point gives both sides, with sources.
   - Nothing found: say that the index and `wiki find --raw` (and the vault search, if run) came
     back empty, naming the terms tried.
4. **End** with the one action that would most improve the answer, as a `/sb learn` the owner can
   run: the uncompiled note it leaned on, a source to fetch, or a topic to research.

## Keep it (`--save`, or the owner asks)

Only an answer resting on at least one article is kept; otherwise `learn` its raw first.

1. `sbmap wiki find` the question's terms among synthesis pages; an earlier page on the same
   question goes in `--related`.
2. `sbmap wiki new <project>/<topic>/<slug> --type synthesis --title "<the question, as a title>"
   --summary "…" --sources <the articles and raw notes cited>`, in the project and topic of the
   article cited most, the slug from the title.
3. Write the answer as the body, by [Writing a finding](../reference/wiki.md#writing-a-finding):
   the Overview opens with the answer, citations go in `sources`, and claims from training stay out.
4. `sbmap wiki log ask --subject "Archived: <the page>"`, then `sbmap wiki check --fix`.

A synthesis page is always a new page, even when one on the same question exists.
