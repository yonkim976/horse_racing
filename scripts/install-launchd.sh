#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"
LABEL_PREFIX="com.horse-racing"

mkdir -p "${LAUNCH_AGENTS}"
chmod +x "${ROOT}/scripts/run-daily-sync.sh"

install_plist() {
  local template="$1"
  local label="$2"
  local destination="${LAUNCH_AGENTS}/${label}.plist"
  sed "s|__PROJECT_ROOT__|${ROOT}|g" "${template}" >"${destination}"
  launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "${destination}"
  launchctl enable "gui/$(id -u)/${label}"
  echo "installed: ${destination}"
}

install_plist "${ROOT}/scripts/launchd/com.horse-racing.sync-morning.plist" \
  "${LABEL_PREFIX}.sync-morning"
install_plist "${ROOT}/scripts/launchd/com.horse-racing.sync-evening.plist" \
  "${LABEL_PREFIX}.sync-evening"

if [[ "${ROOT}" == *"/Desktop/"* ]]; then
  echo
  echo "경고: 프로젝트가 Desktop 아래에 있습니다."
  echo "macOS TCC가 launchd(/bin/bash)의 Desktop 접근을 막아 exit 126이 날 수 있습니다."
  echo "해결: 시스템 설정에서 /bin/bash에 전체 디스크 접근을 허용하거나,"
  echo "      저장소를 Desktop 밖으로 옮긴 뒤 이 스크립트를 다시 실행하세요."
  echo "상세: docs/DATA_AND_OPERATIONS.md (launchd가 실패하는 경우)"
fi

echo
echo "등록 완료. 상태 확인:"
launchctl print "gui/$(id -u)/${LABEL_PREFIX}.sync-morning" | sed -n '1,20p' || true
launchctl print "gui/$(id -u)/${LABEL_PREFIX}.sync-evening" | sed -n '1,20p' || true
echo
echo "즉시 한 번 실행하려면:"
echo "  launchctl kickstart -k gui/\$(id -u)/${LABEL_PREFIX}.sync-morning"
echo "  launchctl kickstart -k gui/\$(id -u)/${LABEL_PREFIX}.sync-evening"
echo "로그: ${ROOT}/data/logs/"
echo "성공 시 daily-sync-YYYYMMDD.log 가 생겨야 합니다. launchd-*.err.log 만 늘면 권한 문제입니다."
