#!/usr/bin/env bash
# Start the bridge and put it online for browser Claude.
#
# While this window is open the bridge is up and reachable. Close the window (or
# hit Ctrl+C) and it all goes away — the server, the Pinggy tunnel, the public
# URL. They're child processes of this script, so there's nothing left behind.
#
# First run installs the Python deps into your own account (pip --user, no venv).
set -uo pipefail

BASE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="${PYTHON:-python3}"
PORT="${BRIDGE_PORT:-8747}"
CFGDIR="$HOME/.config/claude-fedora-bridge"
STATE="$HOME/.local/state"
URLFILE="$STATE/claude-bridge-connector-url.txt"
mkdir -p "$CFGDIR" "$STATE"

G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; DIM=$'\e[2m'; BLD=$'\e[1m'; C=$'\e[36m'; N=$'\e[0m'

BRIDGE_PID=""; SSH_PID=""
cleanup() {
    trap - EXIT INT TERM HUP
    printf '\n%sShutting down…%s\n' "$Y" "$N"
    [ -n "$SSH_PID" ]    && kill "$SSH_PID"    2>/dev/null
    [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null
    pkill -u "$USER" -f 'a.pinggy.io' 2>/dev/null
    rm -f "$URLFILE"
    printf '%s● disconnected%s — the bridge is stopped and nothing is exposed.\n' "$R" "$N"
    exit 0
}
trap cleanup EXIT INT TERM HUP

# --- deps (first run only) -------------------------------------------------
if ! "$PY" -c 'import mcp' 2>/dev/null; then
    printf '%sFirst run — installing Python deps into your account (no virtualenv)…%s\n' "$DIM" "$N"
    "$PY" -m pip install --user -q -r "$BASE/requirements.txt" || {
        printf '%sCouldn'\''t install deps. Try: %spip install --user -r requirements.txt%s\n' "$R" "$BLD" "$N"
        exit 1
    }
fi

export PYTHONPATH="$BASE/src${PYTHONPATH:+:$PYTHONPATH}"
SECRET="$(cat "$CFGDIR/url-secret" 2>/dev/null)"
[ -z "$SECRET" ] && SECRET="$("$PY" -c 'from claude_fedora_bridge import config; print(config.load([]).url_secret)')"

clear
printf '%s%s┌────────────────────────────────────────────────┐%s\n' "$BLD" "$C" "$N"
printf '%s%s│            Claude Fedora Bridge                 │%s\n' "$BLD" "$C" "$N"
printf '%s%s└────────────────────────────────────────────────┘%s\n\n' "$BLD" "$C" "$N"

# --- 1. public tunnel (Pinggy over 443) ------------------------------------
printf '%sOpening a public tunnel (Pinggy, SSH over 443)…%s\n' "$DIM" "$N"
LOG="$STATE/pinggy.log"; : > "$LOG"
# Pinggy's free tier takes an empty password; feed it one non-interactively so
# ssh never stops to prompt.
ASKPASS="$CFGDIR/empty-askpass.sh"
printf '#!/bin/sh\necho ""\n' > "$ASKPASS"; chmod +x "$ASKPASS"
export SSH_ASKPASS="$ASKPASS" SSH_ASKPASS_REQUIRE=force
unset DISPLAY
ssh -p 443 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
    -o ExitOnForwardFailure=yes -o NumberOfPasswordPrompts=1 \
    -o PreferredAuthentications=keyboard-interactive,password \
    -R0:localhost:"$PORT" a.pinggy.io >> "$LOG" 2>&1 &
SSH_PID=$!

URLS=""
for _ in $(seq 1 40); do
    URLS=$(tr -d '\r' < "$LOG" \
        | grep -oE 'https://[a-z0-9.-]+\.(pinggy-free\.link|free\.pinggy\.net|pinggy\.link)' | sort -u)
    [ -n "$URLS" ] && break
    kill -0 "$SSH_PID" 2>/dev/null || { printf '%sTunnel failed to start:%s\n' "$R" "$N"; cat "$LOG"; exit 1; }
    sleep 1
done
[ -z "$URLS" ] && { printf '%sNo tunnel URL appeared — see %s%s\n' "$R" "$LOG" "$N"; exit 1; }
HOST=$(echo "$URLS" | sed -E 's#https?://##' | paste -sd,)
URL="$(echo "$URLS" | head -1)/mcp-$SECRET"

# --- 2. the bridge, told to trust this tunnel host -------------------------
export BRIDGE_ALLOWED_HOSTS="$HOST" BRIDGE_PORT="$PORT" BRIDGE_WORKSPACE="$HOME/ClaudeWorkspace"
"$PY" -m claude_fedora_bridge.server > "$STATE/claude-bridge.log" 2>&1 &
BRIDGE_PID=$!
sleep 2
kill -0 "$BRIDGE_PID" 2>/dev/null || {
    printf '%sBridge failed to start — see %s%s\n' "$R" "$STATE/claude-bridge.log" "$N"; exit 1
}
printf '%s\n' "$URL" > "$URLFILE"

# --- 3. live status --------------------------------------------------------
printf '%s%s●%s connected  %s(URL changes each session, ~60 min on the free tier)%s\n\n' "$BLD" "$G" "$N" "$DIM" "$N"
printf '%sPaste this into claude.ai → Settings → Connectors:%s\n' "$BLD" "$N"
printf '   %s%s%s\n\n' "$C" "$URL" "$N"
printf 'Workspace: %s/ClaudeWorkspace    Mode: standard (root asks first, via Polkit)\n' "$HOME"
printf '%sKeep this window open to stay connected. Close it or press Ctrl+C to stop.%s\n\n' "$Y" "$N"

START=$(date +%s)
while true; do
    kill -0 "$BRIDGE_PID" 2>/dev/null || { printf '\n%sThe bridge exited unexpectedly.%s\n' "$R" "$N"; exit 1; }
    if ! kill -0 "$SSH_PID" 2>/dev/null; then
        printf '\n%sTunnel dropped (free Pinggy session probably expired). Reopen to reconnect.%s\n' "$Y" "$N"; exit 1
    fi
    UP=$(( $(date +%s) - START ))
    printf '\r%s%s● live%s  uptime %02d:%02d:%02d   bridge up · tunnel up   ' \
        "$G" "$BLD" "$N" $((UP/3600)) $(((UP%3600)/60)) $((UP%60))
    sleep 1
done
