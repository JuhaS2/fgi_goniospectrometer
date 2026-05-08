# Radiometric Processing Workflow

This document describes the mathematics currently implemented in this codebase for converting ASD spectrometer digital numbers (DN) into corrected spectral signals ("radiance-like" quantities in the software terminology) and then into reflectance factors using a white reference (WR) panel.

The implementation is split between:

- `goniocontrol_app/workflow_service.py` (workflow and calibration state handling)
- `spectrum_math_utils.py` (numerical conversion functions)

---

## 1. Symbols and Definitions

For one wavelength channel `iw`:

- `DN(iw)`: raw spectrometer digital number from acquisition
- `DC(iw)`: dark spectrum from `collect_dark` (`DC.npy`)
- `driftM`: drift value in current measurement header (`header[22]`)
- `driftDC`: drift value stored during dark calibration (`DriftDC.npy`)
- `VDCC`: spectrometer-reported dark-current-correction constant from VNIR info
- `WR(iw)`: white-reference spectrum (already dark/drift corrected in the same pipeline)

Global spectral settings in math module:

- `Nwl = 2151`
- VNIR correction window is implemented as indices `iw <= (Vwl2 - Vwl1)` with defaults `Vwl1=350`, `Vwl2=1000`.

---

## 2. Unpolarized Workflow (`npols == 1`)

### 2.1 Raw DN Spectrum

At measurement time, one or more spectra are read from the instrument:

- via `spectrometer.read_average(repeats)` in `_take_i(...)`
- packed as tuples `(ret, wga, spectrum, driftM)` where only `spectrum` and `driftM` are used for unpolarized processing

This stage is pure DN and contains instrument dark offset and drift effects.

### 2.2 DN -> Corrected Signal ("Radiance" in workflow)

Implemented by `MakeI(...)` in `spectrum_math_utils.py`.

For channels in the VNIR correction range:

`B(iw) = DN(iw) - DC(iw) + VDCC + (driftM - driftDC)`

Then clipped to nonnegative:

`B(iw) <- max(0, B(iw))`

If multiple repeats were acquired, the function returns the mean over repeats for each wavelength:

`I(iw) = mean(B(iw))`

Outside VNIR correction range, code uses raw `DN(iw)` (with the same averaging logic).

### 2.3 Residual Dark Remainder Correction

In unpolarized mode, an additional residual correction is used:

1. During `collect_dark()`, after dark capture, another blocked-light acquisition is processed by `MakeI(...)` and saved as `DC_remainder`.
2. This remainder is subtracted from subsequent unpolarized products:

`I_corr(iw) = I(iw) - DC_remainder(iw)`

This subtraction is applied both for:

- white-reference acquisition (`WC = MakeI(...) - DC_remainder`)
- normal unpolarized measurements (`SS = MakeI(...) - DC_remainder`)

### 2.4 Reflectance Factor Relative to White Reference

Implemented by `MakeRef(...)`:

`R(iw) = I_corr(iw) / WR(iw)`

where `WR(iw)` is the first row of the stored white-reference array (`WR = WC` in unpolarized flow).

Interpretation:

- This is a relative reflectance factor (sample signal normalized by reference panel signal in same instrument units and processing chain).
- It is not an absolute physical radiance calibration in SI units in this code path.

---

## 3. Polarized Workflow

Polarized operation has two modes:

- 3-state (`npols == 3`): retrieve Stokes-like `I,Q,U`
- 16-state (`npols == 16`): retrieve Mueller-matrix estimate

The key structural difference is that multiple analyzer/generator states are measured and then inverted by least squares using instrument matrices (`AA3` or `AA44`).

### 3.1 Polarized Raw Data Acquisition

Workflow:

- `_take_pol_sequence_iqu()` for 3-state style processing:
  - sensor polarizer at angles 0, 45, 90, 135 degrees
  - each measurement contributes `(ret, wga, spectrum, driftM)`
- `_take_pol_sequence_44()` for 16-state style processing:
  - lamp polarizer x sensor polarizer x retardance combinations
  - each measurement contributes `(ret, wga, lpol, spectrum, driftM)`

### 3.2 Instrument Matrix Construction

- `MakeAA3(subdata)` builds wavelength-dependent analyzer matrix rows:
  - row form is `0.5 * [1, cos(2*theta), sin(2*theta)]`
- `MakeAA44(subdata)` builds expanded matrix using analyzer and lamp polarizer states with retardance model

These are saved as calibration products (`AA3.npy` or `AA44.npy`) during white calibration.

### 3.3 Dark/Drift Correction for Polarized Inversion

Before inversion, each measurement channel is corrected similarly to unpolarized case but embedded in linear system assembly.

For `MakeStokesIQU(...)` (3-state), VNIR range correction is:

`B(iw) = DN(iw) - DC(iw) + VDCC + (driftM - driftDC)`

followed by nonnegative clipping, then least-squares solution:

`[I,Q,U]^T(iw) = argmin_x ||AA3(iw) x - B(iw)||_2`

For `MakeMuller(...)` (16-state), VNIR range correction currently implemented is:

`B(iw) = DN(iw) - DC(iw) + VDCC - (driftM - driftDC)`

then least-squares solution to recover 16 coefficients reshaped into `4x4` Mueller matrix per wavelength:

`vec(M)(iw) = argmin_x ||AA44(iw) x - B(iw)||_2`

Note: the drift-term sign differs between `MakeStokesIQU` (`+`) and `MakeMuller` (`-`) in current implementation.

### 3.4 Polarized Reflectance Factors

After obtaining polarized spectral quantities:

- 3-state reflectance via `MakeRef(...)`:
  - component-wise division by white-reference intensity channel:
  - `Ref_IQU(:,iw) = IQU(:,iw) / WR(0,iw)`
- 16-state reflectance via `MakeRef44(...)`:
  - element-wise division by `WR(0,0,iw)`:
  - `Ref_MM(:,:,iw) = MM(:,:,iw) / WR(0,0,iw)`

Thus, polarized reflectance products are normalized to polarized white-reference calibrations collected in the same mode (`White3.npy` or `White44.npy`).

---

## 4. End-to-End State Sequence

### Unpolarized

1. Acquire dark -> save `DC`, `driftDC`
2. Acquire blocked-light residual -> save `DC_remainder`
3. Acquire white -> `WR = MakeI(...) - DC_remainder`
4. Acquire sample -> `I_corr = MakeI(...) - DC_remainder`
5. Compute reflectance factor -> `R = I_corr / WR`

### Polarized

1. Acquire dark -> save `DC`, `driftDC`
2. Build polarization instrument matrix (`AA3` or `AA44`) and white product (`White3`/`White44`)
3. Acquire polarized sample state sequence
4. Solve least-squares per wavelength for Stokes (`I,Q,U`) or Mueller matrix
5. Normalize by white reference (`MakeRef` or `MakeRef44`)

---

## 5. Practical Interpretation

- The code performs relative radiometric normalization suitable for BRF-style workflows using an in-run WR panel.
- Dark handling combines a stored dark spectrum (`DC`), drift correction term (`driftM - driftDC`), and instrument constant (`VDCC`).
- In unpolarized mode an extra empirical baseline term (`DC_remainder`) is additionally removed from both white and sample signals.
