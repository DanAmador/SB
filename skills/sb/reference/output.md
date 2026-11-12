# Output: the vault holds it, chat points at it

The owner reads the vault, not the chat, and every chat line costs tokens in each later turn. So a
verb's result is **written where it lasts** (the ticket through `sbmap comment` or `resolve`, the
run board, the handoff, the map, the report), and the verb's last message is **at most three
lines**:

1. What is true now, or the one action that starts the next thing.
2. The link to the note that holds the rest.
3. 👤 What waits on the owner, if anything: each call with ➡️ the default that stands on silence
   (≤5; the rest are in the note).

- **The note is the report.** Chat never repeats it: ticket lists, files, checks, evidence and
  reasoning stay there. A result with no note yet gets one (`sbmap comment`, or the run board).
- **Between tool calls, silence**, except the one-liners the steps ask for (the verb, what the
  vault gave, the contract applied).
- **Unattended:** nothing is said in chat; rulings and progress go on the ticket and the board.
  A decision that changes what gets built or cannot be undone cheaply goes to the hub (anything
  else is ruled on the spot): `sbhub ask --agent <your reported id> --q "<question>" --options "a|b"
  --default a --wait 540`, two to four choices in the owner's words, the recommendation as
  `--default`. Whatever it prints is the ruling. Every ruling, asked or on the spot, is written on
  the ticket as `R: …, cost if wrong: …`.
- **Chat is the product** only for `explain`, `ask`, and questions the owner must answer now (a
  grilling round, tonight's proposal questions). Those follow the **Plain** output style
  ([`output-styles/plain.md`](../../../output-styles/plain.md); read it when the style is off).

Inside the vault, notes are **dense**: findings first, one fact per line, numbers with units,
links instead of retelling. No narrative of how the work went.

- **Status emojis**, one meaning each: ✅ landed · 🎮 needs the owner's play · 👤 owner's call ·
  ⚠️ problem or unverified · ⏳ running · 🔒 rule · 🗺️ map change · 🆕 created · 💬 added to ·
  ♻️ reopened.
- **Links.** In chat, a vault note is the line `sbmap uri <file> "<name> #NNN"` prints, pasted as
  is (the `vault-link-check` mod sends back a typed `obsidian://` link). In the vault, a wikilink
  (`sbmap link`). Tickets go by name, the number inside the link.
- **Estimates** in hours, from commits ([contract](contract.md)), with what the owner will *see*
  when it is done.
- Words: [Plain words](../SKILL.md#plain-words).
