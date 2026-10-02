#!/bin/bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${TASK_ROOT}"
exec "${TASK_ROOT}/.venv/bin/python" -m horse_racing.jobs.local_race_day --apply "$@"
