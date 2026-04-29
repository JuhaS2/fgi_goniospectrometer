#!/usr/bin/env bash
set -euo pipefail

# Installs a shared virtual environment for goniocontrol on Raspberry Pi.
# Run this once as user "pi" (it uses sudo for system-level steps).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="/opt/gonio-venv"
PYTHON_BIN="python3.13"

echo "[1/5] Installing OS packages..."
sudo apt update
sudo apt install -y python3.13 python3.13-venv python3.13-tk libatlas-base-dev

echo "[2/5] Creating shared virtual environment at ${VENV_DIR}..."
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Could not find ${PYTHON_BIN} after package installation."
  echo "Install a Raspberry Pi OS release with Python 3.13 packages, then re-run."
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  sudo "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

echo "[3/5] Updating venv ownership for current user..."
sudo chown -R "$(id -un)":"$(id -gn)" "${VENV_DIR}"

echo "[4/5] Installing Python dependencies into shared venv..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install numpy scipy matplotlib pyvisa pyserial pyusb

echo "[5/5] Installing launcher helper to /usr/local/bin..."
sudo tee /usr/local/bin/run-goniocontrol-gui > /dev/null <<EOF
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT}"
VENV_PYTHON="/opt/gonio-venv/bin/python"
APP_PATH="\${PROJECT_ROOT}/goniocontrol_gui.py"

if [[ ! -x "\${VENV_PYTHON}" ]]; then
  echo "Shared venv not found at \${VENV_PYTHON}."
  echo "Run ${PROJECT_ROOT}/scripts/install_pi.sh first."
  exit 1
fi

if [[ ! -f "\${APP_PATH}" ]]; then
  echo "Could not find app entrypoint at \${APP_PATH}."
  echo "If project path changed, re-run ${PROJECT_ROOT}/scripts/install_pi.sh."
  exit 1
fi

if [[ -z "\${DISPLAY:-}" ]]; then
  export DISPLAY=:0
fi

if [[ -z "\${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="/run/user/\$(id -u)"
fi

if [[ "\${1:-}" == "--dry-run" ]]; then
  export GONIO_DRY_RUN=1
  shift
fi

cd "\${PROJECT_ROOT}"
exec "\${VENV_PYTHON}" "\${APP_PATH}" "\$@"
EOF
sudo chmod 0755 /usr/local/bin/run-goniocontrol-gui

cat <<EOF

Install completed.

Next steps:
  1) Open terminal in the Raspberry Pi desktop session.
  2) Run:
       run-goniocontrol-gui

Optional dry-run mode:
  run-goniocontrol-gui --dry-run
EOF
