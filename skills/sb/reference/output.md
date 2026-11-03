# Writing for the owner

The general rules (headline first, plain words, ➡️ on every question, numbered steps, at most 5
items per group, one two-minute next action) live in one place: the **Plain** output style,
[`output-styles/plain.md`](../../../output-styles/plain.md), installed by `install.sh --output-style`
and set with `"outputStyle": "Plain"`. With the style off, read that file and follow it. Only the
sb-specific rules are here.

- **Detail goes to the vault.** Evidence, reasoning, file lists and logs go into the ticket
  (`sbmap comment`), the handoff or the map, and chat links to them.
- **Status emojis**, one meaning each: ✅ landed · 🎮 needs the owner's play · 👤 owner's call ·
  ⚠️ problem or unverified · ⏳ running · 🔒 rule · 🗺️ map change · 🆕 created · 💬 added to ·
  ♻️ reopened.
- Refer to tickets by **name**, with the number inside the link, never a wall of numbers. In chat a
  markdown link to the note's Obsidian URI, so a click opens it in Obsidian:
  `[<name> #NNN](obsidian://open?path=%2FUsers%2F…%2F<vault>%2Fwayfinder%2F…)`, the
  absolute path percent-encoded (`/` → `%2F`, space → `%20`). Claude Code Desktop leaves these
  links dead without the `obsidian-links` mod, which `install.sh` installs. In the vault a
  wikilink (`sbmap link`), so Obsidian's graph sees it.
- Options say what the owner will *see*, so a button approved fast is still readable later.
- Estimates in hours, from commits (see the contract). Say what the owner will *see* when it is done.
