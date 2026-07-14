#!/usr/bin/env bash
# Optional convenience installer:
#   1. installs the Python deps into your account (no virtualenv),
#   2. drops a clickable launcher on your Desktop + app menu:
#        "Claude Bridge — Connect" → opens run.sh in a terminal
#
# There's no separate disconnect launcher — the bridge only ever runs while
# that terminal window is open, so closing it (or Ctrl+C) already stops
# everything immediately.
#
# You don't need this to use the bridge — ./run.sh works on its own. This is just
# for people who'd rather double-click an icon.
set -euo pipefail

BASE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PY="${PYTHON:-python3}"

echo "→ installing Python deps (pip --user, no virtualenv)…"
"$PY" -m pip install --user -r "$BASE/requirements.txt"

chmod +x "$BASE/run.sh"

# Find a terminal to run the console in. Fall back to a terminal-less launch.
if   command -v konsole        >/dev/null; then RUN_EXEC="konsole --hold -p tabtitle=Claude-Bridge -e $BASE/run.sh"; TERM_FLAG=false
elif command -v gnome-terminal >/dev/null; then RUN_EXEC="gnome-terminal -- $BASE/run.sh";                          TERM_FLAG=false
elif command -v xterm          >/dev/null; then RUN_EXEC="xterm -hold -e $BASE/run.sh";                             TERM_FLAG=false
else                                             RUN_EXEC="$BASE/run.sh";                                           TERM_FLAG=true
fi

APPS="$HOME/.local/share/applications"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
mkdir -p "$APPS" "$DESK"

launcher() { # $1 name  $2 comment  $3 icon  $4 exec  $5 terminal  $6 outfile
    cat > "$6" <<EOF
[Desktop Entry]
Type=Application
Name=$1
Comment=$2
Icon=$3
Exec=$4
Terminal=$5
Categories=Utility;
EOF
    chmod +x "$6"
    gio set "$6" metadata::trusted true 2>/dev/null || true
}

for dir in "$APPS" "$DESK"; do
    launcher "Claude Bridge — Connect" \
        "Start the bridge. Keep the window open to stay connected; close it to disconnect." \
        "$BASE/icons/connect.svg" "$RUN_EXEC" "$TERM_FLAG" \
        "$dir/claude-bridge-connect.desktop"
done

echo "→ done."
echo "  Launcher added to your Desktop and app menu."
echo "  On KDE you may have to right-click the Desktop icon once and choose"
echo "  'Allow Launching' (or 'Properties → check Is executable')."
