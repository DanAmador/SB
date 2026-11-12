# /sb close <map>

The map's Destination is reached, or the owner is ending it. Leave two things: the map's knowledge
compiled into the wiki, and a report the owner can review in one sitting and Semantra can place
beside similar maps. Both follow wikibrain's *Writing a finding* ([the wiki](../reference/wiki.md)):
the report's one subject is the map's effort, and each finding in it is one sentence, the article
holding the depth.

1. **Can it close?** `sbmap status <map>`: every ticket resolved or out of scope, nothing claimed,
   lanes landed (`land`). Anything else: list it, each with ➡️ out of scope or keep open, and stop
   until the owner rules.
2. **Learn the map.** Run *Learn a source* ([learn.md](learn.md)) over the map's research notes and
   every resolved ticket, one at a time. Their measurements, gotchas and the reasons behind
   decisions are the findings. Log no-material only for research notes and research tickets.
3. **Rewrite `## In plain words` one last time**: what the map set out to do, whether it did, what
   was left out and where it went.
4. **`sbmap close <map>`** writes `report.md` from [templates/map-report.md](../templates/map-report.md)
   (properties, `findings`, one *Also learned* line per finding) and archives the map.
5. **Write the report** into the scaffold, leaving out any empty section:
   - **Heading:** the map's title, then its outcome in a few words.
   - **Outcome:** one paragraph a stranger could follow: what exists now that did not, whether the
     Destination was reached, what fell short.
   - **Your calls:** what is left open and needs the owner, each with ➡️ the recommendation that
     stands on silence.
   - **Findings:** the five that most change how later work is done, ranked, moved up from *Also
     learned*. Each is what this map added to its article, as one bold sentence, then how it is
     known and what a future agent does with it, then the article's link.
   - **Also learned:** every other article in `findings`, one sentence and the link each.
   - **Decisions later work must respect:** at most five, each with its reason.

   A map that learned nothing says so in the Outcome and has no Findings sections.
6. **Check.** `sbmap check <map>` and `sbmap wiki check --fix` exit zero, and `sbmap wiki verify`
   passes for the articles in `findings`.

Done when every article in `findings` has its line in the report and every line names an article.

## Report

`obsidian open` the report when the owner is present. Chat:

1. "Review <report link, the line `sbmap uri <report>` prints>: tick each finding you accept; under
   one that is wrong, add a line saying what is true."
2. The outcome in one line.
3. 👤 Your calls, each with ➡️.

## Applying the review

The next `/sb learn` (tend) reads every report:

- A ticked finding whose article's `reviewed` is empty or older than the report's `closed`:
  `sbmap wiki set <article> reviewed=today`. A tick is applied once; a later change to the article
  waits for its own review.
- An indented line the owner wrote under a finding is a correction: learn it as a source ("pasted by
  the owner") through *Learn a source*, then append ` (learned <date>)` to that line.
- An unticked finding with no line under it is not reviewed yet: leave it.
