#!/usr/bin/env bash
# Installs the "Boat Dashboard" icon on the desktop and in the applications menu (XFCE / freedesktop).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APP_DIR="$HOME/.local/share/applications"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/boat-dashboard-open"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

mkdir -p "$ICON_DIR" "$APP_DIR" "$DESKTOP_DIR" "$BIN_DIR"
install -m 0644 "$REPO/deploy/boat-dashboard.svg" "$ICON_DIR/boat-dashboard.svg"
# Copy the launcher script out of the repo: the desktop icon must keep working whatever branch
# the checkout is on (the script does not exist on every branch).
install -m 0755 "$REPO/deploy/open-dashboard.sh" "$LAUNCHER"

cat > "$APP_DIR/boat-dashboard.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Boat Dashboard
Name[fr]=Tableau de bord
Comment=Batteries, énergie et navigation
Exec=$LAUNCHER
Icon=boat-dashboard
Terminal=false
Categories=Utility;
EOF

install -m 0755 "$APP_DIR/boat-dashboard.desktop" "$DESKTOP_DIR/boat-dashboard.desktop"

# XFCE only runs desktop launchers it has marked as trusted (checksum of the file).
if command -v gio >/dev/null; then
  gio set "$DESKTOP_DIR/boat-dashboard.desktop" metadata::xfce-exe-checksum \
    "$(sha256sum "$DESKTOP_DIR/boat-dashboard.desktop" | cut -d' ' -f1)" 2>/dev/null || true
fi
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed: $DESKTOP_DIR/boat-dashboard.desktop"
