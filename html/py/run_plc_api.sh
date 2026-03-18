#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/var/www"
APP_DIR="${ROOT_DIR}/html/py"
VENV_BIN="${ROOT_DIR}/.venv/bin"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
export PLC_POLL_INTERVAL_MS="${PLC_POLL_INTERVAL_MS:-1000}"

exec "${VENV_BIN}/uvicorn" plc_api:app --app-dir "${APP_DIR}" --host "${HOST}" --port "${PORT}"
