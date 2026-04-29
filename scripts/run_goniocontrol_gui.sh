#!/usr/bin/env bash
set -euo pipefail

# Launches the GUI from a shared virtual environment.
# Intended to be run by user "pi" in desktop session.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="/opt/gonio-venv/bin/python"
APP_PATH="${PROJECT_ROOT}/goniocontrol_gui.py"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Shared venv not found at ${VENV_PYTHON}."
  echo "Run scripts/install_pi.sh first."
  exit 1
fi

if [[ ! -f "${APP_PATH}" ]]; then
  echo "Could not find app entrypoint at ${APP_PATH}."
  exit 1
fi

# Require GUI session unless user already exports a valid display.
if [[ -z "${DISPLAY:-}" ]]; then
  export DISPLAY=:0
fi

if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  export GONIO_DRY_RUN=1
  shift
fi

cd "${PROJECT_ROOT}"
exec "${VENV_PYTHON}" "${APP_PATH}" "$@"
