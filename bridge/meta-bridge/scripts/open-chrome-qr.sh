#!/bin/bash
# Opens the WhatsApp QR pairing page in Chrome as user omar.
# Called via ExecStartPost from meta-bridge.service.

set -euo pipefail

CHROME=/usr/bin/google-chrome
URL="http://localhost:8766"
USER_PROFILE="/home/omar/.config/google-chrome"

# Open Chrome with profile "omar" — launch via systemd-run --scope so it
# survives ExecStartPost exiting (systemd kills all cgroup children otherwise).
/usr/bin/systemd-run --user --scope -- \
  "$CHROME" --user-data-dir="$USER_PROFILE" --profile-directory="omar" "$URL" >/dev/null 2>&1 &
disown || true
