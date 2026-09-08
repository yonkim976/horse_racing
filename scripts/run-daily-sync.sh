#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
AS_OF="${2:-}"
LOG_DIR="${ROOT}/data/logs"
CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/horse-racing-uv-cache}"
STAMP="$(date '+%Y%m%d')"
LOG_FILE="${LOG_DIR}/daily-sync-${STAMP}.log"

mkdir -p "${LOG_DIR}"
cd "${ROOT}"

export UV_CACHE_DIR="${CACHE_DIR}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') sync-daily mode=${MODE} ====="
  ARGS=(horse-racing sync-daily --mode "${MODE}")
  if [[ -n "${AS_OF}" ]]; then
    ARGS+=(--as-of "${AS_OF}")
  fi
  set +e
  uv run "${ARGS[@]}"
  code=$?
  set -e
  echo "===== done exit=${code} ====="
  exit "${code}"
} >>"${LOG_FILE}" 2>&1
