# Goniocontrol GUI Operator Guide

## Start

THESE INSTRUCTIONS ARE OUTDATED!

- Raspberry Pi target runtime: Python 3.7 in shared venv at `/opt/gonio-venv` (installed via `scripts/install_pi.sh`)
- Real hardware mode:
  - `run-goniocontrol-gui`
- Dry-run mode (no hardware required):
  - `run-goniocontrol-gui --dry-run`
- Launch from a terminal in the active desktop session (not headless SSH shell).

### Windows PowerShell: run in dry mode

From the repository root (`C:\git\fgi_goniospectrometer`):

1. Activate your Python environment (example for conda):
   - `conda activate main`
2. Enable dry mode for this shell session:
   - `$env:GONIO_DRY_RUN = "1"`
3. Launch the GUI:
   - `python .\goniocontrol_gui.py`
4. Optional cleanup after exit (remove dry-mode env var):
   - `Remove-Item Env:GONIO_DRY_RUN`

## Typical workflow

1. **System Status**:
   - Press `Connect Devices`
   - Press `Load Runtime State`
   - Run `Preflight` and verify required files are present.
2. **Measurement Setup**:
   - Set output file and press `New Dataset`.
   - Select angle file (`Angles.txt` or `Angles_PanelReflCalib.txt`).
   - Choose reflectance or radiance mode.
3. **Calibration**:
   - `Restore Spectrometer` (optional if needed).
   - `Optimize` at desired white-reference zenith.
   - `Dark` (close cap before running).
   - `White` (place white panel before running).
   - Optionally run `Ending White` at end of sequence.
4. **Acquisition**:
   - Use `Go Zenith` and `Zero All` for positioning.
   - Set repeats and click `Start Measure`.
   - Use `Abort Measure` to cancel a running sequence.
5. **Plot/View**:
   - `View Snapshot` and `Plot Current Data` for quick checks.

## Outputs and compatibility

- Runtime state location:
  - Runtime/calibration artifacts are stored outside repo root in an OS-specific state folder.
  - Override folder with environment variable `GONIO_STATE_DIR`.
  - Linux/Raspberry Pi default: `$XDG_STATE_HOME/goniocontrol` or `~/.local/state/goniocontrol`.
  - Windows default (dry run/dev): `%LOCALAPPDATA%\\goniocontrol`.
  - Fallback if defaults are not writable: `<repo>/.goniocontrol_state`.
- Runtime artifacts written to the state folder:
  - `outfile.txt`, `outfile.npy`, `runtime_settings.json`
  - `DC.npy`, `DriftDC.npy`, `DC_remainder.npy`, `Oheader.npy`
  - `AA*.npy`, `White*.npy`, `White*E.npy`, `WRZA.npy`, `WRZAE.npy`
- Measurement outputs stay at the user-selected output path:
  - `<outfile>.pickle`, `<outfile>.txt`, `<outfile>_.txt`
- Backward compatibility:
  - On startup, if runtime files are missing from the new state folder, legacy repo-root files are used as fallback and copied to the state folder.

## Notes

- GUI preserves legacy workflow logic but runs long operations in background worker threads.
- `Calibrate Polarizer` is exposed; original model in legacy script is incomplete and remains operator-assisted.

