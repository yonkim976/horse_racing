#!/usr/bin/env bash
set -euo pipefail

LABEL_PREFIX="com.horse-racing"
UID_NUM="$(id -u)"

for label in "${LABEL_PREFIX}.sync-morning" "${LABEL_PREFIX}.sync-evening"; do
  launchctl bootout "gui/${UID_NUM}/${label}" 2>/dev/null || true
  rm -f "${HOME}/Library/LaunchAgents/${label}.plist"
  echo "removed: ${label}"
done
