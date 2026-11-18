#!/bin/bash
# Run the sb hub (and its read-only phone page) as background services (launchd on macOS, systemd
# user units on Linux), so the queue keeps going when the terminal or app session that started it closes.
#
#   sbhub_service.sh install [--ts] [--no-lan] [--take-over] [--linger]
#   sbhub_service.sh uninstall
#   sbhub_service.sh status
#   sbhub_service.sh restart
#   sbhub_service.sh plist [--ts]     print the hub's LaunchAgent without installing it
#
# --ts runs the TypeScript server (skills/sb/hub/packages/server) on the port instead of sbhub.py serve;
# it starts sbhub.py as its child on a port of its own. install --ts first installs the workspace's
# packages and builds the board (pnpm), so node and pnpm must be on PATH.
#
# macOS: install writes two LaunchAgents (com.sb.hub, com.sb.hub-lan) to ~/Library/LaunchAgents and starts
# them. Each restarts within 10 s if it exits and starts again at login. The hub runs under
# `caffeinate -i`, so the Mac does not idle-sleep while it runs (closing the lid on battery still
# sleeps). PATH, SB_HUB_HOME, SB_VAULT and SB_CODE are copied from the shell that runs install, so the
# workers find claude, git, pnpm, the vault and the repos; run it again after those change.
#
# Linux: the same two services as systemd user units in ~/.config/systemd/user, with the same restart,
# environment and log behaviour (KillMode=process plays AbandonProcessGroup's part). A third unit,
# com.sb.hub-awake, holds a systemd-inhibit idle and sleep lock while the hub runs, in place of
# caffeinate; logind grants it only to a logged-in user, so it retries every minute until one is.
# The units start at login; --linger (loginctl enable-linger) starts them at boot and keeps them
# running after logout.
#
# A hub already listening on the port (one started by hand or by an app) makes install stop, unless
# --take-over: then only the hub's own process is killed (SIGKILL, never its process group), its
# workers keep running, and the new hub adopts them. Workers also survive later restarts
# (AbandonProcessGroup), and re-running install on a live hub keeps them the same way. uninstall
# stops the hub normally, which ends its running workers. restart loads new hub code and keeps the workers:
# it SIGKILLs only the hub's own process and launchd (systemd on Linux) starts it again; never `launchctl kickstart -k`, whose
# SIGTERM makes the hub end its workers. Logs: $SB_HUB_HOME/com.sb.hub.log and com.sb.hub-lan.log.
set -euo pipefail

OS="$(uname)"
case "$OS" in Darwin|Linux) ;; *) echo "sbhub_service: macOS (launchd) or Linux (systemd) only"; exit 2 ;; esac

SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
HUB_HOME="${SB_HUB_HOME:-$HOME/.sb-hub}"
LA="$HOME/Library/LaunchAgents"
UNITS="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
DOMAIN="gui/$(id -u)"
PY="$(command -v python3)"
HUB_PORT="${SB_HUB_PORT:-8765}"
LAN_PORT=8766

esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }

HUB="$REPO/skills/sb/hub"

need_node() { # --ts flag
  [ "$1" = 1 ] || return 0
  command -v node >/dev/null || { echo "sbhub_service: --ts needs node (24 or later) on PATH"; exit 2; }
}

hub_args() { # --ts flag: the hub service's program arguments, one per line (macOS: under caffeinate)
  [ "$OS" = Darwin ] && printf '%s\n' /usr/bin/caffeinate -i
  if [ "$1" = 1 ]; then
    printf '%s\n' "$(command -v node)" "$HUB/packages/server/src/index.ts" --port $HUB_PORT
  else
    printf '%s\n' "$PY" "$SCRIPTS/sbhub.py" serve --port $HUB_PORT
  fi
}

plist() { # label, program args...: the plist on stdout
  local label=$1; shift
  local env="    <key>PATH</key><string>$(esc "$PATH")</string>
    <key>HOME</key><string>$(esc "$HOME")</string>"
  [ -n "${SB_HUB_HOME:-}" ] && env="$env
    <key>SB_HUB_HOME</key><string>$(esc "$SB_HUB_HOME")</string>"
  [ -n "${SB_VAULT:-}" ] && env="$env
    <key>SB_VAULT</key><string>$(esc "$SB_VAULT")</string>"
  [ -n "${SB_CODE:-}" ] && env="$env
    <key>SB_CODE</key><string>$(esc "$SB_CODE")</string>"
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
  }
}

write_plist() { # label, program args...
  plist "$@" >"$LA/$1.plist"
  plutil -lint -s "$LA/$1.plist"
}

# One systemd value in double quotes; its backslashes, quotes and % specifiers kept literal.
sdq() {
  local v=$1
  v=${v//\\/\\\\}
  v=${v//\"/\\\"}
  v=${v//%/%%}
  printf '"%s"' "$v"
}

# One ExecStart word: there $ starts a variable too.
sdw() { sdq "${1//\$/\$\$}"; }

write_unit() { # label, program args...
  local label=$1 cmd="" a; shift
  for a in "$@"; do cmd="$cmd $(sdw "$a")"; done
  {
    echo "[Unit]"
    echo "Description=$label (sb hub)"
    echo "StartLimitIntervalSec=0"
    [ "$label" = com.sb.hub ] && echo "Wants=com.sb.hub-awake.service"
    echo
    echo "[Service]"
    echo "ExecStart=${cmd# }"
    echo "WorkingDirectory=${REPO//%/%%}"
    echo "Environment=$(sdq "PATH=$PATH")"
    echo "Environment=$(sdq "HOME=$HOME")"
    [ -n "${SB_HUB_HOME:-}" ] && echo "Environment=$(sdq "SB_HUB_HOME=$SB_HUB_HOME")"
    [ -n "${SB_VAULT:-}" ] && echo "Environment=$(sdq "SB_VAULT=$SB_VAULT")"
    [ -n "${SB_CODE:-}" ] && echo "Environment=$(sdq "SB_CODE=$SB_CODE")"
    [ -n "${SB_HUB_PORT:-}" ] && echo "Environment=$(sdq "SB_HUB_PORT=$SB_HUB_PORT")"
    echo "Restart=always"
    echo "RestartSec=10"
    echo "KillMode=process"
    echo "StandardOutput=append:${HUB_HOME//%/%%}/$label.log"
    echo "StandardError=append:${HUB_HOME//%/%%}/$label.log"
    echo
    echo "[Install]"
    echo "WantedBy=default.target"
  } >"$UNITS/$label.service"
}

write_awake_unit() {
  local inhibit; inhibit="$(command -v systemd-inhibit || echo /usr/bin/systemd-inhibit)"
  {
    echo "[Unit]"
    echo "Description=keeps the machine from idle-sleeping while the sb hub runs"
    echo "PartOf=com.sb.hub.service"
    echo "StartLimitIntervalSec=0"
    echo
    echo "[Service]"
    echo "ExecStart=$(sdw "$inhibit") --what=idle:sleep --who=sb-hub \"--why=the sb hub is running\" sleep infinity"
    echo "Restart=always"
    echo "RestartSec=60"
  } >"$UNITS/com.sb.hub-awake.service"
}

if [ "$OS" = Linux ]; then
  loaded() { systemctl --user is-active --quiet "$1.service"; }
else
  loaded() { launchctl print "$DOMAIN/$1" >/dev/null 2>&1; }
fi

listener() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1 || true; }

start() { # label, port
  if loaded "$1"; then
    # The hub ends its workers on SIGTERM; SIGKILL its own process first so they live on.
    local pid; pid="$(listener "$2")"
    [ -n "$pid" ] && kill -9 "$pid"
    [ "$OS" = Linux ] || launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
    sleep 1
  fi
  if [ "$OS" = Linux ]; then
    systemctl --user daemon-reload
    systemctl --user enable --quiet "$1.service"
    systemctl --user restart "$1.service"
  else
    launchctl bootstrap "$DOMAIN" "$LA/$1.plist"
  fi
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
    lan=1 take=0 ts=0 linger=0
    for a in "$@"; do
      case "$a" in
        --ts) ts=1 ;;
        --no-lan) lan=0 ;;
        --take-over) take=1 ;;
        --linger) linger=1 ;;
        *) echo "sbhub_service: unknown option $a"; exit 2 ;;
      esac
    done
    need_node $ts
    mkdir -p "$HUB_HOME"
    args=()
    while IFS= read -r a; do args+=("$a"); done < <(hub_args $ts)
    if [ $ts = 1 ]; then
      pnpm --dir "$HUB" install --frozen-lockfile
      pnpm --dir "$HUB" build
    fi
    if [ "$OS" = Linux ]; then
      mkdir -p "$UNITS"
      loaded com.sb.hub || free_port "$HUB_PORT" $take
      write_awake_unit
      write_unit com.sb.hub "${args[@]}"
      start com.sb.hub "$HUB_PORT"
      if [ $lan = 1 ]; then
        loaded com.sb.hub-lan || free_port $LAN_PORT $take
        write_unit com.sb.hub-lan "$PY" "$SCRIPTS/sbhub_lan.py" serve --port $LAN_PORT
        start com.sb.hub-lan $LAN_PORT
      fi
      if [ $linger = 1 ]; then
        loginctl enable-linger "$(id -un)" && echo "linger on: the hub starts at boot and runs after logout"
      fi
    else
      [ $linger = 0 ] || echo "sbhub_service: --linger is Linux only; a LaunchAgent runs while you are logged in"
      mkdir -p "$LA"
      loaded com.sb.hub || free_port "$HUB_PORT" $take
      write_plist com.sb.hub "${args[@]}"
      start com.sb.hub "$HUB_PORT"
      if [ $lan = 1 ]; then
        loaded com.sb.hub-lan || free_port $LAN_PORT $take
        write_plist com.sb.hub-lan "$PY" "$SCRIPTS/sbhub_lan.py" serve --port $LAN_PORT
        start com.sb.hub-lan $LAN_PORT
      fi
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
        if [ "$OS" = Linux ]; then
          systemctl --user stop "$l.service" 2>/dev/null || true
        else
          launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
        fi
        echo "stopped $l"
      fi
      if [ "$OS" = Linux ]; then
        systemctl --user disable --quiet "$l.service" 2>/dev/null || true
        rm -f "$UNITS/$l.service"
      else
        rm -f "$LA/$l.plist"
      fi
    done
    if [ "$OS" = Linux ]; then
      systemctl --user stop com.sb.hub-awake.service 2>/dev/null || true
      rm -f "$UNITS/com.sb.hub-awake.service"
      systemctl --user daemon-reload
    fi
    ;;
  restart)
    loaded com.sb.hub || { echo "sbhub_service: com.sb.hub is not installed; run install"; exit 1; }
    pid="$(listener $HUB_PORT)"
    [ -n "$pid" ] && kill -9 "$pid"  # SIGKILL: the hub cannot end its workers; they live on and are adopted
    for _ in $(seq 1 30); do
      sleep 1
      new="$(listener $HUB_PORT)"
      [ -n "$new" ] && [ "$new" != "$pid" ] && { echo "hub restarted: pid $new (was ${pid:-none}); its workers keep running"; exit 0; }
    done
    echo "sbhub_service: the hub did not come back within 30 s; see $HUB_HOME/com.sb.hub.log"
    exit 1
    ;;
  plist)
    ts=0
    [ "${2:-}" = --ts ] && ts=1
    need_node $ts
    args=()
    while IFS= read -r a; do args+=("$a"); done < <(hub_args $ts)
    plist com.sb.hub "${args[@]}"
    ;;
  status)
    for l in com.sb.hub com.sb.hub-lan; do
      if [ "$OS" = Linux ]; then
        if [ -f "$UNITS/$l.service" ]; then
          state="$(systemctl --user show "$l.service" -p ActiveState --value)"
          pid="$(systemctl --user show "$l.service" -p MainPID --value)"
          echo "$l: $state$([ "${pid:-0}" = 0 ] || echo ", pid $pid")"
        else
          echo "$l: not installed"
        fi
      elif loaded $l; then
        echo "$l: $(launchctl print "$DOMAIN/$l" | awk -F' = ' '/^\tstate/{s=$2} /^\tpid/{p=$2} END{print s (p? ", pid " p : "")}')"
      else
        echo "$l: not installed"
      fi
    done
    ;;
  *)
    sed -n '5,9p' "$0" | sed 's/^# *//'
    exit 2
    ;;
esac
