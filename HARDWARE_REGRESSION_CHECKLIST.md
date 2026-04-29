# Hardware Regression Checklist

Use this checklist on Raspberry Pi + instrument to validate parity with legacy CLI behavior.

## Environment

- [ ] `python3 goniocontrol_gui.py` launches without traceback.
- [ ] `Connect Devices` discovers expected motors (zenith, azimuth, sample, polarizers as available).
- [ ] Spectrometer connects to `169.254.1.11:8080`.
- [ ] Angle file loads correctly (`Angles.txt` or selected alternate file).

## Command parity

- [ ] New dataset writes `outfile.txt` and starts empty in-memory dataset.
- [ ] Restore executes and VNIR info is readable.
- [ ] Optimize stores `Oheader.npy`.
- [ ] Dark stores `DC.npy`, `DriftDC.npy`, `DC_remainder.npy`.
- [ ] White stores correct `White*.npy` and `AA*.npy` for current polarization mode.
- [ ] Ending white stores expected `White*E.npy` + `WRZAE.npy`.
- [ ] Go Zenith moves to requested angle.
- [ ] Zero All returns axes to zero positions.
- [ ] Measure creates/updates `<outfile>.pickle` incrementally.
- [ ] Measure final export writes `<outfile>.txt`.
- [ ] Reflectance/radiance toggle changes stored payload type.

## Reliability

- [ ] Abort Measure cancels gracefully and leaves app responsive.
- [ ] GUI remains responsive during long measurement loops.
- [ ] Shutdown closes connections and exits cleanly.
- [ ] Restart loads previous state and continues with same output file.

## Data spot check

- [ ] Compare one short run against legacy CLI with same angles and repeats.
- [ ] Confirm comparable magnitude/trends in spectra/reflectance output.

