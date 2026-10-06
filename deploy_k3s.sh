#!/usr/bin/env bash
# hydros-k3s-app-live-deploy-skill app-live-deploy template version: 0.1.20
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[ERROR] missing python3/python" >&2
    exit 1
  fi
fi

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/deploy/k3s/scripts/live_deploy.py" "$@"
