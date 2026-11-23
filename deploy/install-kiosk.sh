#!/usr/bin/env bash
# Opens the dashboard full screen at every login (XDG autostart). Undo: install-kiosk.sh --remove
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.local/bin/boat-dashboard-kiosk"
ENTRY="$HOME/.config/autostart/boat-dashboard-kiosk.desktop"

if [[ "${1:-}" == "--remove" ]]; then
  rm -f "$ENTRY" "$BIN"
  echo "Removed kiosk autostart."
  exit 0
fi

mkdir -p "$(dirname "$BIN")" "$(dirname "$ENTRY")"
# Copied out of the repo so login works whatever branch the checkout is on.
install -m 0755 "$REPO/deploy/kiosk.sh" "$BIN"
cat > "$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Boat Dashboard (full screen)
Exec=$BIN
Icon=boat-dashboard
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP
echo "Installed: $ENTRY"
