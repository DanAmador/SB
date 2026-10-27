# Writing for the owner

The owner reads on a phone, often walking. Shape every report so it can be acted on without
scrolling back. The style is the `i-have-adhd` skill's (pinned in `skills-lock.json`;
`~/.agents/skills/i-have-adhd/SKILL.md` holds the full rules; these are the ones that matter here.)

- **Chat is the headline; the vault holds the detail.** A report is a few lines: what changed, what
  the owner decides, a link. Evidence, reasoning, file lists and logs go into the ticket (`sbmap comment`),
  the handoff or the map, and chat links to them instead of repeating them.
- **First line is the decision or action the owner can take now.** Context comes after, if at all.
- Bullets, short. Numbered when it is a sequence. At most 5 items visible per group: rank and group.
- **Emojis as status only**, one meaning each: ✅ landed · 🎮 needs the owner's play · 👤 owner's call ·
  ⚠️ problem or unverified · ⏳ running · 🔒 rule · 🗺️ map change · 🆕 created · 💬 added to ·
  ♻️ reopened. Never decoration.
- Refer to tickets by **name**, with the number inside the link, never a wall of numbers. In chat a
  markdown link to the note's Obsidian URI, so a click opens it in Obsidian:
  `[<name> #NNN](obsidian://open?path=%2FUsers%2F…%2F<vault>%2Fwayfinder%2F…)`, the
  absolute path percent-encoded (`/` → `%2F`, space → `%20`). Claude Code Desktop leaves these
  links dead without the `obsidian-links` mod, which `install.sh` installs. In the vault a
  wikilink (`sbmap link`), so Obsidian's graph sees it.
- Estimates in hours, from commits (see the contract). Say what the owner will *see* when it is done.
- Every question carries a ➡️ recommendation. When the owner answers only some, list the rest as accepted
  on recommendation in one line and carry on: silence means the recommendation stands.
- End with one thing the owner can do in under two minutes.
