# -*- coding: utf-8 -*-
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import matplotlib.pyplot as plt
import numpy as np

try:
    from ASDlib import (
        MakeAA3,
        MakeAA44,
        MakeI,
        MakeMuller,
        MakeRef,
        MakeRef44,
        MakeStokesIQU,
        Nwl,
    )
except ModuleNotFoundError:
    Nwl = 2151

    def MakeAA3(subdata):
        return np.zeros((Nwl, len(subdata), 3))

    def MakeAA44(subdata):
        return np.zeros((Nwl, len(subdata), 16))

    def MakeI(subdata, DC, driftDC, VDCC):
        spectrum = np.atleast_1d(subdata[0][2])
        return np.reshape(spectrum, (1, -1))

    def MakeMuller(subdata, DC, driftDC, VDCC, AA):
        return np.zeros((4, 4, Nwl))

    def MakeRef(IQUV, WR):
        denom = np.maximum(WR[0, :], 1e-9)
        return IQUV / denom

    def MakeRef44(MM, WR):
        return MM

    def MakeStokesIQU(subdata, DC, driftDC, VDCC, AA3):
        spectrum = np.atleast_1d(subdata[0][2])
        out = np.zeros((3, spectrum.shape[0]))
        out[0, :] = spectrum
        return out
from goniocontrol_app.errors import CalibrationMissingError, PreconditionError
from goniocontrol_app.state import AppState

ProgressFn = Callable[[str], None]
ShouldCancelFn = Callable[[], bool]


class WorkflowService:
    MOTOR_STEP_SCALE = 100.0

    def __init__(
        self,
        state: AppState,
        persistence: Any,
        motors: Any,
        spectrometer: Any,
        lcc: Any,
    ):
        self.state = state
        self.persistence = persistence
        self.motors = motors
        self.spectrometer = spectrometer
        self.lcc = lcc

    def startup_preflight(self):
        result = {}
        angle_path = self.resolve_path(self.state.angles_file)
        result["angles_file"] = "ok" if angle_path.exists() else "missing"
        for name in ["DC.npy", "DriftDC.npy", "Oheader.npy"]:
            result[name] = "ok" if (self.state.workspace / name).exists() else "missing"
        return result

    def connect_devices(self):
        motors = self.motors.discover()
        self.state.devices.motors = motors
        self.state.devices.sample_rotator_present = "sample" in motors
        self.state.devices.connected_lcc = self.lcc.enabled
        required_motors = {"zenith", "azimuth", "sample"}
        missing_motors = sorted(required_motors - set(motors.keys()))
        if missing_motors:
            raise PreconditionError(
                "Missing required motor controllers: "
                + ", ".join(missing_motors)
                + ". Optional polarizer controllers may be absent."
            )

        try:
            greeting = self.spectrometer.connect()
        except Exception as exc:
            raise PreconditionError(
                "Could not connect to spectrometer at configured host/port."
            ) from exc
        self.state.devices.connected_spectrometer = bool(greeting)

        for role in ["zenith", "azimuth", "sample", "sensor_polarizer", "lamp_polarizer"]:
            if role in self.motors.handles:
                pos = self.motors.get_position(role)
                self.state.devices.positions_zero[role] = pos
                self.state.devices.positions_current[role] = pos

        if "sensor_polarizer" not in self.motors.handles:
            self.state.devices.npols = 1
        elif "lamp_polarizer" in self.motors.handles:
            self.state.devices.npols = 16
        else:
            self.state.devices.npols = 3

    def get_device_status_snapshot(self):
        required_motors = ("zenith", "azimuth", "sample")
        polarizer_roles = ("sensor_polarizer", "lamp_polarizer")
        snapshot = {
            "spectrometer": "NOT CONNECTED",
            "motors": "NOT CONNECTED",
            "polarizer": "Optional / Not present",
        }

        if self.state.devices.connected_spectrometer:
            try:
                self.spectrometer.vnir_info()
                snapshot["spectrometer"] = "Connected"
            except Exception:
                snapshot["spectrometer"] = "NOT CONNECTED"
                self.state.devices.connected_spectrometer = False

        missing_required = [role for role in required_motors if role not in self.motors.handles]
        if missing_required:
            snapshot["motors"] = "NOT CONNECTED ({})".format(", ".join(sorted(missing_required)))
        else:
            motor_faults = []
            for role in required_motors:
                try:
                    self.motors.get_position(role)
                except Exception:
                    motor_faults.append(role)
            if motor_faults:
                snapshot["motors"] = "NOT CONNECTED ({})".format(", ".join(sorted(motor_faults)))
            else:
                snapshot["motors"] = "Connected"

        present_polarizers = [role for role in polarizer_roles if role in self.motors.handles]
        if not present_polarizers:
            snapshot["polarizer"] = "Not present"
        else:
            polarizer_faults = []
            for role in present_polarizers:
                try:
                    self.motors.get_position(role)
                except Exception:
                    polarizer_faults.append(role)
            if polarizer_faults:
                snapshot["polarizer"] = "NOT CONNECTED ({})".format(", ".join(sorted(polarizer_faults)))
            else:
                snapshot["polarizer"] = "Connected"
        return snapshot

    def load_runtime_state(self):
        self.load_runtime_settings()
        self.state.runtime_notice = None
        vwl1, _, vdcc = self.spectrometer.vnir_info()
        self.state.calibration.optimizer_header = self.persistence.load_optional_array("Oheader.npy")
        self.state.calibration.dark_current = self.persistence.load_optional_array("DC.npy")
        self.state.calibration.drift_dark = self.persistence.load_optional_array("DriftDC.npy")
        self.state.outfile = self.persistence.load_outfile_name(self.state.outfile)
        self.state.data = self.persistence.load_existing_dataset(self.state.outfile)
        try:
            self.state.angles = self.persistence.read_angles(self.state.angles_file)
        except FileNotFoundError:
            fallback = Path("Angles.txt")
            fallback_resolved = self.resolve_path(fallback)
            self.state.runtime_notice = "Saved angles file not found ({}); falling back to {}.".format(
                self.state.angles_file, fallback_resolved
            )
            self.state.angles_file = fallback
            if fallback_resolved.exists():
                self.state.angles = self.persistence.read_angles(fallback)
            else:
                self.state.angles = []
        self.state.calibration.wr_zenith = self.persistence.load_optional_array("WRZA.npy")
        self.state.calibration.dark_remainder = self.persistence.load_optional_array("DC_remainder.npy")
        self._load_polarization_calibration()

        hdr = self.state.calibration.optimizer_header
        if hdr is not None:
            self.spectrometer.set_opt(hdr[2], hdr[3], hdr[4])
        self._vwl1 = vwl1
        self._vdcc = vdcc
        self._wl = vwl1 + np.arange(Nwl)

    def load_runtime_settings(self):
        defaults = {
            "outfile": self.state.outfile,
            "angles_file": str(self.state.angles_file),
            "reflectance_mode": self.state.reflectance_mode,
        }
        settings = self.persistence.load_runtime_settings(defaults)
        self.state.outfile = str(settings["outfile"])
        self.state.angles_file = Path(str(settings["angles_file"]))
        self.state.reflectance_mode = bool(settings["reflectance_mode"])

    def save_runtime_settings(self):
        self.persistence.save_runtime_settings(
            outfile=self.state.outfile,
            angles_file=self.state.angles_file,
            reflectance_mode=self.state.reflectance_mode,
        )

    def _load_polarization_calibration(self):
        npols = self.state.devices.npols
        if npols == 1:
            self.state.calibration.white = self.persistence.load_optional_array("White1.npy")
        elif npols == 3:
            self.state.calibration.aa = self.persistence.load_optional_array("AA3.npy")
            self.state.calibration.white = self.persistence.load_optional_array("White3.npy")
        elif npols == 16:
            self.state.calibration.aa = self.persistence.load_optional_array("AA44.npy")
            self.state.calibration.white = self.persistence.load_optional_array("White44.npy")

    def new_dataset(self, outfile):
        candidate = Path((outfile or "").strip() or "Test00.pickle")
        if candidate.suffix.lower() != ".pickle":
            candidate = candidate.with_suffix(".pickle")
        if not candidate.is_absolute():
            candidate = self.state.workspace / candidate
        self.state.outfile = str(candidate.resolve())
        self.persistence.save_outfile_name(self.state.outfile)
        self.save_runtime_settings()
        os.makedirs(Path(self.state.outfile).parent, exist_ok=True)
        self.state.data = []

    def restore_spectrometer(self):
        self.spectrometer.restore()
        self.spectrometer.vnir_info()

    def show_vnir_info(self):
        return self.spectrometer.vnir_info()

    def optimize(self, wr_zenith, progress= None):
        self.go_zenith(wr_zenith)
        for idx in range(25):
            header = self.spectrometer.optimize()
            if progress:
                progress("Optimize try {}/25 => header {}".format(idx + 1, header[0]))
            if header[0] == 100:
                break
        self.state.calibration.optimizer_header = np.array(header, dtype=object)
        self.persistence.save_array("Oheader.npy", self.state.calibration.optimizer_header)

    def collect_dark(self):
        header, dc = self.spectrometer.read_average(25)
        drift = header[22]
        idata = self._take_i(repeats=25)
        dc_remainder = MakeI(idata, dc, drift, self._vdcc)
        self.state.calibration.dark_current = dc
        self.state.calibration.drift_dark = drift
        self.state.calibration.dark_remainder = dc_remainder
        self.persistence.save_array("DC.npy", dc)
        self.persistence.save_array("DriftDC.npy", drift)
        self.persistence.save_array("DC_remainder.npy", dc_remainder)

    def collect_white(self, wr_zenith):
        self._require_dark()
        self.go_zenith(wr_zenith)
        npols = self.state.devices.npols
        if npols == 1:
            wrdata = self._take_i(repeats=25)
            wc = MakeI(wrdata, self._dc(), self._drift(), self._vdcc) - self._dc_remainder()
            self.state.calibration.white = wc
            self.persistence.save_array("White1.npy", wc)
        elif npols == 3:
            wrdata = self._take_pol_sequence_iqu()
            aa = MakeAA3(wrdata)
            wc = MakeStokesIQU(wrdata, self._dc(), self._drift(), self._vdcc, aa)
            self.state.calibration.aa = aa
            self.state.calibration.white = wc
            self.persistence.save_array("AA3.npy", aa)
            self.persistence.save_array("White3.npy", wc)
        elif npols == 16:
            wrdata = self._take_pol_sequence_44()
            aa = MakeAA44(wrdata)
            wc = MakeMuller(wrdata, self._dc(), self._drift(), self._vdcc, aa)
            self.state.calibration.aa = aa
            self.state.calibration.white = wc
            self.persistence.save_array("AA44.npy", aa)
            self.persistence.save_array("White44.npy", wc)
        else:
            raise PreconditionError("Unsupported polarization mode.")
        self.state.calibration.wr_zenith = wr_zenith
        self.persistence.save_array("WRZA.npy", wr_zenith)

    def collect_ending_white(self, wr_zenith):
        self._require_white()
        self.go_zenith(wr_zenith)
        npols = self.state.devices.npols
        if npols == 1:
            wrdata = self._take_i(repeats=25)
            wce = MakeI(wrdata, self._dc(), self._drift(), self._vdcc) - self._dc_remainder()
            self.state.calibration.ending_white = wce
            self.persistence.save_array("{}White1E.npy".format(self.state.outfile), wce)
        elif npols == 3:
            wrdata = self._take_pol_sequence_iqu()
            wce = MakeStokesIQU(wrdata, self._dc(), self._drift(), self._vdcc, self.state.calibration.aa)
            self.state.calibration.ending_white = wce
            self.persistence.save_array("White3E.npy", wce)
        elif npols == 16:
            wrdata = self._take_pol_sequence_44()
            wce = MakeMuller(wrdata, self._dc(), self._drift(), self._vdcc, self.state.calibration.aa)
            self.state.calibration.ending_white = wce
            self.persistence.save_array("White44E.npy", wce)
        self.state.calibration.wr_end_zenith = wr_zenith
        self.persistence.save_array("WRZAE.npy", wr_zenith)

    def calibrate_polarizer(self, forward_zenith, progress= None):
        if self.state.devices.npols == 1:
            raise PreconditionError("Polarizer calibration requires polarizer hardware.")
        self.go_zenith(forward_zenith)
        _ = self._take_pol_sequence_iqu()
        # Original script's calibration path is incomplete/broken. Preserve command surface and report state.
        if progress:
            progress("Polarizer calibration sequence collected (manual calibration model not defined in source).")

    def go_zenith(self, angle_deg):
        zero = self.state.devices.positions_zero["zenith"]
        self.motors.move_deg_from_zero("zenith", angle_deg, zero)
        self.motors.wait("zenith")

    def refresh_motor_position(self, role):
        if role not in self.motors.handles:
            raise PreconditionError("Motor '{}' is not available.".format(role))
        self.state.devices.positions_current[role] = self.motors.get_position(role)

    def get_motor_angle_from_zero(self, role):
        if role not in self.state.devices.positions_zero:
            raise PreconditionError("Motor '{}' has no zero reference.".format(role))
        if role not in self.state.devices.positions_current:
            self.refresh_motor_position(role)
        current = self.state.devices.positions_current[role]
        zero = self.state.devices.positions_zero[role]
        return (current.step_position - zero.step_position) / self.MOTOR_STEP_SCALE

    def drive_motor_to_angle(self, role, angle_deg):
        if role not in self.state.devices.positions_zero:
            raise PreconditionError("Motor '{}' has no zero reference.".format(role))
        zero = self.state.devices.positions_zero[role]
        self.motors.move_deg_from_zero(role, angle_deg, zero)
        self.motors.wait(role)
        self.refresh_motor_position(role)

    def set_zero_at_current_position(self, role):
        self.refresh_motor_position(role)
        self.state.devices.positions_zero[role] = self.state.devices.positions_current[role]

    def zero_all(self):
        for role in ["azimuth", "zenith", "sample", "sensor_polarizer", "lamp_polarizer"]:
            if role in self.state.devices.positions_zero:
                self.motors.move_to_zero(role, self.state.devices.positions_zero[role])

    def toggle_mode(self):
        self.state.reflectance_mode = not self.state.reflectance_mode
        self.save_runtime_settings()
        return self.state.reflectance_mode

    def view_snapshot(self):
        self._require_white()
        if self.state.devices.npols == 1:
            vdata = self._take_i(repeats=1)
            vi = MakeI(vdata, self._dc(), self._drift(), self._vdcc) - self._dc_remainder()
            rv = MakeRef(vi, self.state.calibration.white)
            plt.figure(figsize=(8, 4))
            plt.plot(self._wl, rv[0, :])
            plt.ylim(0.0, 2.0)
            plt.savefig(self.state.workspace / "GonioViews.png")
            plt.close()

    def plot_current_data(self):
        if not self.state.data:
            raise PreconditionError("No data to plot.")
        datum = self.state.data[-1]
        spectrum = datum[5]
        if spectrum.ndim == 2:
            plt.figure(figsize=(8, 4))
            plt.plot(self._wl, spectrum[0, :])
            plt.title("Latest measurement")
            plt.show()

    def measure_sequence(
        self,
        repeats: int,
        progress = None,
        should_cancel = None,
    ) -> None:
        self._require_measure_preconditions()
        total = len(self.state.angles)
        for idx, (sz, sa00, ze, az, be, wwa, wwb) in enumerate(self.state.angles, start=1):
            if should_cancel and should_cancel():
                return
            if progress:
                progress("Angle {}/{}: ze={} az={} be={}".format(idx, total, ze, az, be))
            self._move_measurement_axes(ze=ze, az=az, be=be)
            if wwb == 0.0:
                continue
            self._apply_opt()
            ss, rr = self._measure_at_angle(repeats=repeats)
            payload = rr if self.state.reflectance_mode else ss
            self.state.data.append((sz, sa00, ze, az, be, payload, wwa, wwb))
            self.persistence.checkpoint_dataset(self.state.outfile, self.state.data)
        self.zero_all()
        self.persistence.checkpoint_dataset(self.state.outfile, self.state.data)

    def shutdown(self):
        self.persistence.export_text(self.state)
        self.spectrometer.close()
        self.motors.close_all()

    def _move_measurement_axes(self, ze, az, be):
        self.motors.move_deg_from_zero("azimuth", az, self.state.devices.positions_zero["azimuth"])
        self.motors.move_deg_from_zero("zenith", ze, self.state.devices.positions_zero["zenith"])
        if self.state.devices.sample_rotator_present and "sample" in self.state.devices.positions_zero:
            self.motors.move_deg_from_zero("sample", be, self.state.devices.positions_zero["sample"])
        self.motors.wait("zenith")
        self.motors.wait("azimuth")

    def _measure_at_angle(self, repeats):
        npols = self.state.devices.npols
        if npols == 16:
            subdata = self._take_pol_sequence_44()
            ss = MakeMuller(subdata, self._dc(), self._drift(), self._vdcc, self.state.calibration.aa)
            rr = MakeRef44(ss, self.state.calibration.white)
        elif npols == 3:
            subdata = self._take_pol_sequence_iqu()
            ss = MakeStokesIQU(subdata, self._dc(), self._drift(), self._vdcc, self.state.calibration.aa)
            rr = MakeRef(ss, self.state.calibration.white)
        else:
            subdata = self._take_i(repeats=repeats)
            ss = MakeI(subdata, self._dc(), self._drift(), self._vdcc) - self._dc_remainder()
            rr = MakeRef(ss, self.state.calibration.white)
        return ss, rr

    def _take_i(self, repeats= 1):
        header, spectrum = self.spectrometer.read_average(repeats)
        drift = header[22]
        return [(0.0, 0.0, spectrum, drift)]

    def _take_pol_sequence_iqu(self):
        subdata = []
        self.lcc.set_retardance(0)
        for wg in [0, 45, 90, 135]:
            self._move_sensor_polarizer(wg)
            header, spectrum = self.spectrometer.read_single()
            subdata.append((0.0, wg, spectrum, header[22]))
        self._move_sensor_polarizer(0)
        return subdata

    def _take_pol_sequence_44(self):
        subdata = []
        rets = list(self.lcc.retardances) if self.lcc.retardances is not None else [0]
        rets = rets or [0]
        for lamp in [0, 45, 90, 135]:
            self._move_lamp_polarizer(lamp)
            for wg in [0, 45, 90, 135]:
                self._move_sensor_polarizer(wg)
                for ret in rets:
                    self.lcc.set_retardance(float(ret))
                    header, spectrum = self.spectrometer.read_single()
                    subdata.append((float(ret), wg, lamp, spectrum, header[22]))
        self._move_sensor_polarizer(0)
        self._move_lamp_polarizer(0)
        return subdata

    def _move_sensor_polarizer(self, angle_deg):
        if "sensor_polarizer" not in self.state.devices.positions_zero:
            return
        self.motors.move_deg_from_zero("sensor_polarizer", angle_deg, self.state.devices.positions_zero["sensor_polarizer"])
        self.motors.wait("sensor_polarizer")

    def _move_lamp_polarizer(self, angle_deg):
        if "lamp_polarizer" not in self.state.devices.positions_zero:
            return
        self.motors.move_deg_from_zero("lamp_polarizer", angle_deg, self.state.devices.positions_zero["lamp_polarizer"])
        self.motors.wait("lamp_polarizer")

    def _require_measure_preconditions(self):
        self._require_dark()
        self._require_white()
        if self.state.calibration.optimizer_header is None:
            raise CalibrationMissingError("Oheader.npy not loaded. Run optimize first.")
        if not self.state.angles:
            raise PreconditionError("Angle list is empty.")

    def _require_dark(self):
        if self.state.calibration.dark_current is None or self.state.calibration.drift_dark is None:
            raise CalibrationMissingError("Dark calibration missing.")

    def _require_white(self):
        if self.state.calibration.white is None:
            raise CalibrationMissingError("White calibration missing.")

    def _dc(self):
        return self.state.calibration.dark_current

    def _drift(self):
        return self.state.calibration.drift_dark

    def _dc_remainder(self):
        if self.state.calibration.dark_remainder is None:
            return 0.0
        return self.state.calibration.dark_remainder

    def _apply_opt(self):
        hdr = self.state.calibration.optimizer_header
        self.spectrometer.set_opt(hdr[2], hdr[3], hdr[4])

    def resolve_path(self, path):
        return path if path.is_absolute() else self.state.workspace / path

