#!/usr/bin/env bash
# Links skills/sb into the shared skills folder and into Claude Code's, the way the other shared
# skills are linked (~/.claude/skills/<name> -> ../../.agents/skills/<name>).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

link() {  # link <target> <link path>
    if [ -L "$2" ]; then rm "$2"
    elif [ -e "$2" ]; then echo "install: $2 exists and is not a link; leaving it" >&2; return 1
    fi
    ln -s "$1" "$2"
    echo "linked $2 -> $1"
}

mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
link "$here/skills/sb" "$HOME/.agents/skills/sb"
link "../../.agents/skills/sb" "$HOME/.claude/skills/sb"
chmod +x "$here/skills/sb/scripts/sbmap.py"
