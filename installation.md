# Installation

## 1) System requirements

- Raspberry Pi OS (or other Linux) with Python 3.7 and `sudo` access.
- USB access for:
  - XIMC motor controllers
  - LCC controller (serial)
  - ASD spectrometer network connection (`169.254.1.11:8080`)
- XIMC native driver/library installed (`libximc`), because `pyximc.py` loads `libximc.dll`/`libximc.so`.

## 2) One-time install (recommended for `pi` user)

This project ships helper scripts to create a shared venv at `/opt/gonio-venv`
and install a launcher command.

From the project root:

```bash
chmod +x scripts/install_pi.sh scripts/run_goniocontrol_gui.sh
./scripts/install_pi.sh
```

This performs:

- OS package install (`python3`, `python3-venv`, `python3-pip`, `python3-tk`, etc.)
- shared virtual environment creation at `/opt/gonio-venv`
- Python dependency install into that venv
- launcher install to `/usr/local/bin/run-goniocontrol-gui`

## 3) Run

Run from a terminal in the Raspberry Pi desktop session.

Real hardware mode:

```bash
run-goniocontrol-gui
```

Dry-run mode (no hardware):

```bash
run-goniocontrol-gui --dry-run
```

## 4) Verify files in this project

- `goniocontrol_gui.py`
- `goniocontrol_app/` package
- `ASDlib.py`
- `LCClib.py`
- `pyximc.py`

## Notes

- Using the shared venv avoids needing to switch users just to access Python dependencies.
- `python3-tk` is required for the Tkinter GUI.
- `pyximc` in this project is a Python wrapper file (`pyximc.py`), but it still requires the vendor native `libximc` runtime to be installed and discoverable in the system library path.
- If LCC is not connected, the app can still start, but polarization functionality may be limited depending on measurement mode.

