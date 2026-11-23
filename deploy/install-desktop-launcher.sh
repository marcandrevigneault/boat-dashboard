#!/usr/bin/env bash
# Installs the "Boat Dashboard" icon on the desktop and in the applications menu (XFCE / freedesktop).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APP_DIR="$HOME/.local/share/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

mkdir -p "$ICON_DIR" "$APP_DIR" "$DESKTOP_DIR"
install -m 0644 "$REPO/deploy/boat-dashboard.svg" "$ICON_DIR/boat-dashboard.svg"
chmod +x "$REPO/deploy/open-dashboard.sh"

cat > "$APP_DIR/boat-dashboard.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Boat Dashboard
Name[fr]=Tableau de bord
Comment=Batteries, énergie et navigation
Exec=$REPO/deploy/open-dashboard.sh
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
