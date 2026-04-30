# Goniocontrol GUI Operator Guide

## Start

THESE INSTRUCTIONS ARE OUTDATED!

- Raspberry Pi target runtime: Python 3.7 in shared venv at `/opt/gonio-venv` (installed via `scripts/install_pi.sh`)
- Real hardware mode:
  - `run-goniocontrol-gui`
- Dry-run mode (no hardware required):
  - `run-goniocontrol-gui --dry-run`
- Launch from a terminal in the active desktop session (not headless SSH shell).

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

- Uses and updates compatible artifacts:
  - `outfile.txt`, `outfile.npy`, `<outfile>.pickle`, `<outfile>.txt`
  - `DC.npy`, `DriftDC.npy`, `DC_remainder.npy`, `Oheader.npy`
  - `AA*.npy`, `White*.npy`, `White*E.npy`

## Notes

- GUI preserves legacy workflow logic but runs long operations in background worker threads.
- `Calibrate Polarizer` is exposed; original model in legacy script is incomplete and remains operator-assisted.

