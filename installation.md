# Installation

## 1) System requirements

- Raspberry Pi OS (or other Linux) with Python 3.9+ and `pip3`
- USB access for:
  - XIMC motor controllers
  - LCC controller (serial)
  - ASD spectrometer network connection (`169.254.1.11:8080`)
- XIMC native driver/library installed (`libximc`), because `pyximc.py` loads `libximc.dll`/`libximc.so`

## 2) Install OS packages

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-tk libatlas-base-dev
```

`python3-tk` is required for the Tkinter GUI.

## 3) Install Python dependencies

Run this in the project folder:

```bash
pip3 install numpy scipy matplotlib pyvisa pyserial pyusb
```

## 4) Verify files in this project

- `goniocontrol_gui.py`
- `goniocontrol_app/` package
- `ASDlib.py`
- `LCClib.py`
- `pyximc.py`

## 5) Run

Real hardware mode:

```bash
python3 goniocontrol_gui.py
```

Dry-run mode (no hardware):

```bash
GONIO_DRY_RUN=1 python3 goniocontrol_gui.py
```

## Notes

- `pyximc` in this project is a Python wrapper file (`pyximc.py`), but it still requires the vendor native `libximc` runtime to be installed and discoverable in the system library path.
- If LCC is not connected, the app can still start, but polarization functionality may be limited depending on measurement mode.

