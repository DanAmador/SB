# /sb learn [source… | map | --research "<topic>"]

Knowledge goes into the vault's wiki: a source is kept as raw, then compiled into articles that
outlive the map that found it. The format, the commands and the grounding invariant are in
[reference/wiki.md](../reference/wiki.md); read it before the first write.

Read each argument as the first of these that fits:

| argument | sources |
|---|---|
| none | **tend** (below), which ends with the backlog |
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
   (wikibrain's *Layout*). Then `sbmap wiki find --project <project>` with the
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
   - it is in a **shared project** (one a clone syncs: wikibrain's
     *Sharing projects*), so every source
     travels with the wiki.

   No material: log it (step 7) and stop.
4. **Anchor it** by wikibrain's *Anchoring a source* (its `reference/wiki.md`): a raw note whose
   claims rest on a repo carries `repo`, `commit` and `paths` (or `pr`), never without them.
5. **Compile**, by wikibrain's *Writing a finding*. Locate every
   number, date and quote in the raw before writing it, and write it as found.
   - Update: `sbmap wiki set <article> sources+=<raw> updated=today`, then rewrite the sections it
     changes.
   - New: `sbmap wiki new <project>/<topic>/<slug>`, named after the concept rather than the source,
     with a `summary` an agent can triage from, and `--tags` for the concepts it is about (tags are
     Semantra's edges). A source spanning topics lands in the closest one and
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

`/sb learn` with no argument. Upkeep is the AI's (owner, 2026-11-03: "the maintenance should be
entirely done by the AI"): tend fixes what it finds and asks the owner nothing. Every step a command
can do is a command, so tokens go only to judging changed code.

1. **Review.** Apply the owner's review in every map report (`wayfinder/**/report.md`), by
   *Applying the review* in [close.md](close.md).
2. **List.** `sbmap wiki tend --out <scratchpad>/tend.json` (sbmap passes the repos the maps name),
   with `--import <clone>` for each shared wiki clone. One call imports, runs `check --fix` and verifies those repos; stdout is one
   line per article that is not current, and the file holds each one's item (its paths, symbols and
   the code lines changed under it). Read stdout, never the whole file: each subagent gets its own
   items, cut from the file. `git -C <root> rev-parse <target>` once per repo gives the sha that
   `verified` takes.
3. **Judge, cheapest first.** Subagents only read and answer; the writes in step 4 stay serial,
   since the index and the log are shared. At most two at a time ([the contract](../reference/contract.md)).
   - **drifted**: the cheap tier ([models](../reference/models.md)), up to five articles per agent,
     each as `sbmap wiki show <note> --full` plus its item's `diff`. Per article it answers in under
     150 words: `STILL TRUE`, or `CHANGED: "<words from one line of the claim>" → <what is true now>`
     quoting the changed lines that show it, or `UNSURE: <why>`.
   - **broken**, **orphaned** and every `UNSURE`: the mid tier, one article per agent, with its item
     and `removed_in`; it may read the code at the target (CodeGraph first where the repo is
     indexed, then `git show <target>:<path>`, `git grep`) and answers the same way, or `GONE: <what
     replaced it, or nothing>`.
   - **unanchored**: skipped; tying old articles to code is wiki-provenance's backfill.
4. **Write**, one article at a time:
   - `STILL TRUE`: `sbmap wiki set <note> verified=<sha>`.
   - `CHANGED`: keep the answer as the re-read (`sbmap wiki raw <project>/<topic> --title "Re-read of
     <article title>" --source "re-read of <paths> in <repo>" --repo-root <root> --rev <target>
     --paths … --symbols … --from <file holding the answer>`), then `sbmap wiki supersede <note>
     --claim "…" --now "…" --source <that raw>` and `set verified=<sha>`.
   - `GONE`: the same re-read, then `supersede --by <article>` when another article now holds it,
     else `supersede` on the Overview's first line, saying what was removed and when.
   - A note the import listed as changed on both sides: the vault copy stands. Fold in what the
     shared version adds; a claim it contradicts is kept as a raw note (`--source "<clone>
     <base>:<path>"`) and becomes `supersede --dispute`. Then `sbmap wiki import <clone> --keep-mine`.
   - Each grounding suspect `check --fix` printed: the cheap tier judges it against its raw note; a
     real mismatch is fixed in the article, never in the raw.
5. **Cascade, bounded.** For each article step 4 changed, `sbmap wiki find` its changed claim among
   its `related` and `covers` neighbours only: a contradiction becomes `supersede --dispute` on
   both, a claim it supersedes gets `supersede`. A concept with no article, an orphan or a stale
   synthesis page goes in the run note for the next learn, not written tonight.
6. **Backlog**, while the usage gate allows: work it through *Learn a source*, ten at a time (say the
   total). Past the gate, stop after the article in flight: tomorrow's list starts from what is left.
7. **Log and note.** `sbmap wiki log tend --subject "<N> stale: <V> verified, <S> superseded, <D>
   disputed, <K> skipped; ~<T>k tokens"`, the tokens being the subagents' reported totals plus your
   own. Write the board `sbmap run --shared wiki-tend` prints (`sbmap run <project> wiki-tend` for one
   project's wiki): one line per article with what changed and the
   sha, then what step 5 left for later. The morning report reads it.

## Report

The wiki log and the run note hold one line per source. Chat: one line of counts ("🆕 2 · 💬 3 ·
⚠️ 1 disputed · 4 no material · 12 left in the backlog"), then each ⚠️ dispute or unanchored
article as a link with ➡️ a ruling.
