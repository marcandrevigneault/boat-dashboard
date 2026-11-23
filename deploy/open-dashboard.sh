#!/usr/bin/env bash
# Desktop launcher: make sure the dashboard service is running, then open it in a browser window.
# Installed as ~/.local/bin/boat-dashboard-open by install-desktop-launcher.sh; re-run the installer
# after changing this file.
set -euo pipefail

URL="http://localhost:${BOATDASH_PORT:-8080}"

notify() { command -v notify-send >/dev/null && notify-send -i boat-dashboard "Boat Dashboard" "$1" || true; }

if ! systemctl is-active --quiet boat-dashboard; then
  notify "Démarrage du tableau de bord…"
  if ! sudo -n systemctl start boat-dashboard; then
    notify "Impossible de démarrer le service. Voir: journalctl -u boat-dashboard"
    exit 1
  fi
fi

# Wait up to 20 s for the web server to answer.
for _ in $(seq 40); do
  curl -fs -o /dev/null "$URL" && break
  sleep 0.5
done

if ! curl -fs -o /dev/null "$URL"; then
  notify "Le tableau de bord ne répond pas. Voir: journalctl -u boat-dashboard"
  exit 1
fi

exec xdg-open "$URL"
