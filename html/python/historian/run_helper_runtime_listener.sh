#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/var/www"
APP_DIR="${ROOT_DIR}/html/python/historian"
VENV_BIN="${ROOT_DIR}/.venv/bin"
INTERVAL_MS="${HELPER_INTERVAL_MS:-50}"
EVENT_HOLDOFF_MS="${HELPER_EVENT_HOLDOFF_MS:-100}"

PYTHON_BIN="${VENV_BIN}/python"
if [[ -x "${PYTHON_BIN}" ]]; then
  if ! "${PYTHON_BIN}" -c "import psycopg2, snap7" >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  fi
else
  PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${APP_DIR}/helper_runtime_listener.py" \
  --interval-ms "${INTERVAL_MS}" \
  --event-holdoff-ms "${EVENT_HOLDOFF_MS}" \
  "$@"
