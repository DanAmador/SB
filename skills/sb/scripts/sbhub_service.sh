#!/bin/bash
# Run the sb hub (and its read-only phone page) as macOS background services, so the queue keeps
# going when the terminal or app session that started it closes.
#
#   sbhub_service.sh install [--no-lan] [--take-over]
#   sbhub_service.sh uninstall
#   sbhub_service.sh status
#
# install writes two LaunchAgents (com.sb.hub, com.sb.hub-lan) to ~/Library/LaunchAgents and starts
# them. Each restarts within 10 s if it exits and starts again at login. The hub runs under
# `caffeinate -i`, so the Mac does not idle-sleep while it runs (closing the lid on battery still
# sleeps). PATH, SB_HUB_HOME and SB_VAULT are copied from the shell that runs install, so the
# workers find claude, git, pnpm and the rest; run it again after those change.
#
# A hub already listening on the port (one started by hand or by an app) makes install stop, unless
# --take-over: then only the hub's own process is killed (SIGKILL, never its process group), its
# workers keep running, and the new hub adopts them. Workers also survive later restarts
# (AbandonProcessGroup), and re-running install on a live hub keeps them the same way. uninstall
# stops the hub normally, which ends its running workers. Logs: $SB_HUB_HOME/com.sb.hub.log and com.sb.hub-lan.log.
set -euo pipefail

[ "$(uname)" = Darwin ] || { echo "sbhub_service: macOS only (launchd)"; exit 2; }

SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
HUB_HOME="${SB_HUB_HOME:-$HOME/.sb-hub}"
LA="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
PY="$(command -v python3)"
HUB_PORT=8765
LAN_PORT=8766

esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

write_plist() { # label, program args...
  local label=$1; shift
  local env="    <key>PATH</key><string>$(esc "$PATH")</string>
    <key>HOME</key><string>$(esc "$HOME")</string>"
  [ -n "${SB_HUB_HOME:-}" ] && env="$env
    <key>SB_HUB_HOME</key><string>$(esc "$SB_HUB_HOME")</string>"
  [ -n "${SB_VAULT:-}" ] && env="$env
    <key>SB_VAULT</key><string>$(esc "$SB_VAULT")</string>"
  {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>
EOF
    for a in "$@"; do echo "    <string>$(esc "$a")</string>"; done
    cat <<EOF
  </array>
  <key>WorkingDirectory</key><string>$(esc "$REPO")</string>
  <key>EnvironmentVariables</key><dict>
$env
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>AbandonProcessGroup</key><true/>
  <key>StandardOutPath</key><string>$(esc "$HUB_HOME/$label.log")</string>
  <key>StandardErrorPath</key><string>$(esc "$HUB_HOME/$label.log")</string>
</dict></plist>
EOF
  } >"$LA/$label.plist"
  plutil -lint -s "$LA/$label.plist"
}

loaded() { launchctl print "$DOMAIN/$1" >/dev/null 2>&1; }

listener() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1 || true; }

start() { # label, port
  if loaded "$1"; then
    # The hub ends its workers on SIGTERM; SIGKILL its own process first so they live on.
    local pid; pid="$(listener "$2")"
    [ -n "$pid" ] && kill -9 "$pid"
    launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
    sleep 1
  fi
  launchctl bootstrap "$DOMAIN" "$LA/$1.plist"
}

free_port() { # port, --take-over flag
  local pid; pid="$(listener "$1")"
  [ -z "$pid" ] && return 0
  if [ "$2" != 1 ]; then
    echo "sbhub_service: port $1 is held by pid $pid ($(ps -o comm= -p "$pid")); stop it, or pass --take-over"
    exit 1
  fi
  echo "taking over port $1 from pid $pid (its workers keep running)"
  kill -9 "$pid"
  sleep 1
}

case "${1:-}" in
  install)
    shift
    lan=1 take=0
    for a in "$@"; do
      case "$a" in
        --no-lan) lan=0 ;;
        --take-over) take=1 ;;
        *) echo "sbhub_service: unknown option $a"; exit 2 ;;
      esac
    done
    mkdir -p "$LA" "$HUB_HOME"
    loaded com.sb.hub || free_port $HUB_PORT $take
    write_plist com.sb.hub /usr/bin/caffeinate -i "$PY" "$SCRIPTS/sbhub.py" serve --port $HUB_PORT
    start com.sb.hub $HUB_PORT
    if [ $lan = 1 ]; then
      loaded com.sb.hub-lan || free_port $LAN_PORT $take
      write_plist com.sb.hub-lan "$PY" "$SCRIPTS/sbhub_lan.py" serve --port $LAN_PORT
      start com.sb.hub-lan $LAN_PORT
    fi
    sleep 3
    "$0" status
    ;;
  uninstall)
    # Stops the hub the normal way (SIGTERM), which also ends its running workers.
    for pair in com.sb.hub-lan:$LAN_PORT com.sb.hub:$HUB_PORT; do
      l=${pair%%:*} port=${pair##*:}
      if loaded $l; then
        pid="$(listener $port)"; [ -n "$pid" ] && kill "$pid" && sleep 2
        launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
        echo "stopped $l"
      fi
      rm -f "$LA/$l.plist"
    done
    ;;
  status)
    for l in com.sb.hub com.sb.hub-lan; do
      if loaded $l; then
        echo "$l: $(launchctl print "$DOMAIN/$l" | awk -F' = ' '/^\tstate/{s=$2} /^\tpid/{p=$2} END{print s (p? ", pid " p : "")}')"
      else
        echo "$l: not installed"
      fi
    done
    ;;
  *)
    sed -n '5,8p' "$0" | sed 's/^# *//'
    exit 2
    ;;
esac
