#!/usr/bin/env bash
# Links skills/sb into the shared skills folder and into Claude Code's, the way the other shared
# skills are linked (~/.claude/skills/<name> -> ../../.agents/skills/<name>), installs the
# third-party skills pinned in skills-lock.json the same way, and installs the obsidian-links mod
# into every Claude Code config, so obsidian:// links in chat open the note.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

link() {  # link <target> <link path>
    if [ -L "$2" ]; then rm "$2"
    elif [ -e "$2" ]; then echo "install: $2 exists and is not a link; leaving it" >&2; return 0
    fi
    ln -s "$1" "$2"
    echo "linked $2 -> $1"
}

mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.gemini/config/skills"
link "$here/skills/sb" "$HOME/.agents/skills/sb"
link "../../.agents/skills/sb" "$HOME/.claude/skills/sb"
link "$here/skills/sb" "$HOME/.gemini/config/skills/sb"
chmod +x "$here/skills/sb/scripts/sbmap.py"

# Third-party skills: skills-lock.json names each one's GitHub repo, folder and, when pinned, the
# commit (`ref`). An unpinned skill already in ~/.agents/skills is left as it is (delete it and rerun
# to update); a pinned one is reinstalled when its ref changes. A link (a local checkout you develop
# in, e.g. ~/.agents/skills/wikibrain -> your wikiBrain clone) is never replaced.
while read -r name repo dir ref; do
    dest="$HOME/.agents/skills/$name"
    [ -L "$dest" ] && { link "../../.agents/skills/$name" "$HOME/.claude/skills/$name"; continue; }
    if [ ! -e "$dest" ] || { [ "$ref" != "-" ] && [ "$(cat "$dest/.lock-ref" 2>/dev/null)" != "$ref" ]; }; then
        tmp="$(mktemp -d)"
        if [ "$ref" = "-" ]; then
            git clone -q --depth 1 "https://github.com/$repo.git" "$tmp"
        else
            git clone -q "https://github.com/$repo.git" "$tmp" && git -C "$tmp" checkout -q "$ref"
        fi
        rm -rf "$tmp/.git" "$dest"
        cp -R "$tmp/$dir" "$dest"
        [ "$ref" = "-" ] || echo "$ref" > "$dest/.lock-ref"
        rm -rf "$tmp"
        echo "installed $name from $repo${ref:+ at $ref}"
    fi
    link "../../.agents/skills/$name" "$HOME/.claude/skills/$name"
done < <(python3 -c 'import json, os, sys
for k, v in json.load(open(sys.argv[1]))["skills"].items():
    print(k, v["source"], os.path.dirname(v["skillPath"]) or ".", v.get("ref") or "-")' "$here/skills-lock.json")

# Obsidian reads CSS snippets only from real files in the vault, so the Route's link styling is
# copied, not linked: rerun after editing it, then enable it in Settings → Appearance → CSS snippets.
vault="${SB_VAULT:-$HOME/Documents/Second Brain}"
if [ -d "$vault/.obsidian" ]; then
    mkdir -p "$vault/.obsidian/snippets"
    cp "$here/obsidian/snippets/sb-route-links.css" "$vault/.obsidian/snippets/"
    echo "copied sb-route-links.css into $vault/.obsidian/snippets"
fi

# The repo is a folder marketplace, so Claude Code reads the mod from mods/ itself: an edit lands
# with /reload-plugins, no reinstall. One install per config: ~/.claude, and any ~/.claude-*
# config that has plugins.
# Shells often wrap claude in an alias or function a script cannot see, so fall back to the
# native installer's path.
claude="$(command -v claude || true)"
[ -n "$claude" ] || [ ! -x "$HOME/.local/bin/claude" ] || claude="$HOME/.local/bin/claude"
if [ -z "$claude" ]; then
    echo "install: claude not found; skipped the obsidian-links mod, so obsidian:// links in chat" \
         "will not open. Install Claude Code and rerun." >&2
    exit 0
fi
for dir in "$HOME/.claude" "$HOME"/.claude-*; do
    [ "$dir" = "$HOME/.claude" ] || [ -d "$dir/plugins" ] || continue
    cc() { CLAUDE_CONFIG_DIR="$dir" "$claude" "$@"; }
    cc plugin marketplace list 2>/dev/null | grep -q sb-workflow || cc plugin marketplace add "$here"
    cc plugin install obsidian-links@sb-workflow
done
