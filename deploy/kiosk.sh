#!/usr/bin/env bash
# Opens the dashboard full screen (Firefox kiosk) on this computer's display.
# Uses its own Firefox profile, so normal browsing in Firefox is unaffected. Exit with Alt+F4.
set -euo pipefail

URL="${BOATDASH_URL:-http://localhost:8080/}"
PROFILE="$HOME/.local/share/boat-dashboard/kiosk-profile"

# At login the service may still be starting: wait up to 60 s for it to answer.
for _ in $(seq 60); do
  curl -fs -o /dev/null --max-time 1 "$URL" && break
  sleep 1
done

# Already open? Don't start a second window.
pgrep -f -- "--profile $PROFILE" >/dev/null && exit 0

mkdir -p "$PROFILE"
# Quiet profile: no first-run pages, default-browser nag, crash-restore prompt or translation bar.
cat > "$PROFILE/user.js" <<'PREFS'
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.translations.automaticallyPopup", false);
user_pref("browser.translations.enable", false);
user_pref("app.update.auto", false);
PREFS

exec firefox --no-remote --profile "$PROFILE" --kiosk "$URL"
