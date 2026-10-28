# /sb learn [source… | map | --research "<topic>"]

Knowledge goes into the vault's wiki: a source is kept as raw, then compiled into articles that
outlive the map that found it. The format, the commands and the grounding invariant are in
[reference/wiki.md](../reference/wiki.md); read it before the first write.

Read each argument as the first of these that fits:

| argument | sources |
|---|---|
| none | `sbmap wiki backlog`, then **tend** (below) |
| `--research "<topic>"` | **research** (below) |
| starts with `http://` or `https://` | the page, fetched with the harness's web tool; a page too long or paywalled → ask the owner to clip it into `Clippings/` |
| a map folder `sbmap maps` lists, optionally with `<NNN>` | the map's backlog notes (its research notes and resolved research tickets), or the one ticket |
| a vault path that exists | that note, already raw |
| anything else | pasted text, `--source "pasted by the owner"` |

## Learn a source

`sbmap wiki init` if `wiki/` is missing. Then one source at a time: the index, the log and the
cascade are shared, so compiling never runs in parallel.

1. **Read it.** A fetch goes to a scratchpad file exactly as the tool returned it; that file becomes
   the raw, so grounding checks against what you actually read. A ticket is read with `sbmap show`;
   its knowledge is the Answer (measurements, gotchas, the reason behind a decision), and its
   progress log is no material.
2. **Triage.** First the **project**: a ticket or research note belongs to its map's repo (the
   folder under `wayfinder/`), a fetch or a paste to the repo the owner is working in. Knowledge that
   another repo could use unchanged (a tool, a library, a technique) goes in `general` instead
   ([Projects](../reference/wiki.md#layout)). Then `sbmap wiki find --project <project>` with the
   source's entities, their synonyms and abbreviations; with Obsidian running, also
   `search:context query="path:wiki/ <terms>"`. Say the project and the disposition in one line:
   - **New**: a concept no article covers.
   - **Update**: an article's Overview stays true and the source only adds evidence or detail.
   - **Disputed**: the source contradicts an article; combines with New or Update.
   - **No material**: the wiki already holds everything it says. A thin source never forces an
     article.
3. **Keep the raw**, whatever the disposition, in the topic the triage pointed to (`sbmap wiki index
   --project <project>` lists them): `sbmap wiki raw <project>/<topic> … --from <scratchpad file>`
   for a fetch or a paste. A vault note is raw already, except in two cases, where it is first kept
   as a raw note (its Question and Answer, or its body, verbatim, with machine paths, personal
   emails and links into `wayfinder/` turned to plain text) and the article cites that raw note:
   - its claims rest on a repo, so the raw note can carry the commit (step 4);
   - it is in a **shared project** (one a clone syncs, see
     [Sharing projects](../reference/wiki.md#sharing-projects-through-a-git-clone)), so every source
     travels with the wiki.

   No material: log it (step 7) and stop.
4. **Anchor it** by wikibrain's *Anchoring a source* (its `reference/wiki.md`): a raw note whose
   claims rest on a repo carries `repo`, `commit` and `paths` (or `pr`), never without them.
5. **Compile**, by [Writing a finding](../reference/wiki.md#writing-a-finding). Locate every
   number, date and quote in the raw before writing it, and write it as found.
   - Update: `sbmap wiki set <article> sources+=<raw> updated=today`, then rewrite the sections it
     changes.
   - New: `sbmap wiki new <project>/<topic>/<slug>`, named after the concept rather than the source,
     with a `summary` an agent can triage from, and `--tags` for the concepts it is about (tags are
     Semantra's edges: [the wiki](../reference/wiki.md)). A source spanning topics lands in the closest one and
     links the rest through `related`. The heading names the project's own things in its own words
     ("Assemblio part hierarchy"), so the article reads right outside its folder too.
   - Disputed: the Disputed callout under the contested claim, `status=disputed`; on both articles,
     with `disputes`, when the clash spans two.
6. **Cascade.** For each entity and claim the source touches, run `wiki find` and open every article
   it returns (the index alone misses body mentions); for a source with `paths`, also `sbmap wiki
   covers <paths> --repo-root <clone>`, which names the articles resting on the same files. Update each one the source materially changes,
   `updated=today`. A superseded claim keeps its text under an Outdated callout. Synthesis pages are
   snapshots: leave them.
7. **Log.** `sbmap wiki log learn --subject <primary article> --disposition … --raw … --updated …`;
   for no material, `--subject "no material: <vault path>"`.

Done when `sbmap wiki check --fix` exits zero, you have judged every grounding suspect against its
source (a real mismatch is fixed in the article, never in the raw), every article you touched
opens with its point and holds one subject, and `sbmap wiki verify` passes as wikibrain's
*Anchoring a source* says.

## Research

The owner asked to gather sources on a topic (a question alone is `ask`).

1. Split the topic into angles. Search each with a wide net: official names, abbreviations,
   synonyms.
2. For each conclusion you expect, search the opposing side: failures, criticism, failed
   replications.
3. Keep at most 8 sources unless the owner names a number; stop early once two angles in a row add
   no claim the others lack. Fetching may run in parallel subagents (mid tier); compiling stays
   serial, through *Learn a source*.

## Tend

`/sb learn` with no argument. First apply the owner's review in every map report
(`wayfinder/**/report.md`), by *Applying the review* in [close.md](close.md). Then work the backlog through
*Learn a source*, ten at a time (say the total), then `sbmap wiki check --fix`, then read for what the check cannot see. Report each of
these; fix none without the owner:

- contradictions between articles with no Disputed callout
- claims a newer source superseded, still standing without an Outdated callout
- a concept many articles mention that has no article of its own
- articles nothing links to, and obvious `related` links missing
- synthesis pages whose source articles changed substantially since `archived`

For each project that has a repo, `sbmap wiki verify --repo-root <clone>`: re-read every drifted or
broken article against its branch or main, keep the re-read as a raw note (`wiki raw --repo-root
<clone> --rev <branch> --paths … --symbols …`), put each stale claim under a dated Outdated callout
grounded in that note, add it to `sources`, and set `updated`. An unanchored article gets the same
re-read so it is anchored from then on. A re-read that changes nothing can instead set
`verified=<sha>` on the article.

Log it: `sbmap wiki log tend --subject "<N> problems, <M> fixed"`.

## Report

In the owner's shape ([output.md](../reference/output.md)), one line per source, as `capture`
reports: 🆕 new article, 💬 merged into, ⚠️ disputed, or "no material", each with the article's
name as a link and where it is anchored (`<repo>@<short sha>`, or ⚠️ unanchored and why). Then the backlog left, and one action under two minutes (often: rule on a ⚠️
dispute).
