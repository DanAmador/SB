# /sb explain [thing]

The owner lost the thread ("wait what", "I don't get it", "what does X mean"). Retell it in plain
words and stop. Read-only: nothing is written to the vault, nothing is claimed or resolved.

1. **Pick the thing.** The one the owner named; else the last question you asked them; else the
   current map (`sbmap maps --repo <repo>`, the one this repo's session is on).
2. **Read just enough.**
   - A map: `python3 <skill>/scripts/sbmap.py status <map>`, its `## In plain words` section, and the
     `why` of the tickets on its frontier.
   - A ticket: `sbmap show <map> <NNN>`.
   - A question: your own last message, plus the ticket it came from.
3. **Retell it** in short plain sentences, as if to a friend who was not there:
   - 🔒 No class names, internal codes or bare ticket numbers. A ticket is its name as a link
     ([output.md](../reference/output.md)). A term the owner never used is dropped, or glossed in five words.
   - Say what the owner will *see* or *feel* when it is done, not what the code does.
   - Words the owner already used stay; do not paraphrase their own phrases into new jargon.
4. **Shape.** Line 1 is the point. At most 5 lines in all, then one ➡️ next step (a thing they can do,
   or the question they can answer with "yes"). Then stop: no offer to explain more, no recap.
