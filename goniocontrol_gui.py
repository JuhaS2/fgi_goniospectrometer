#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from goniocontrol_app.gui_controller import GuiController
from goniocontrol_app.services.mock_services import MockLCCService, MockMotorService, MockSpectrometerService
from goniocontrol_app.services.persistence_service import PersistenceService
from goniocontrol_app.state import AppState
from goniocontrol_app.workflow_service import WorkflowService


class GoniocontrolGUI(tk.Tk):
    MOTOR_ROLES = (
        ("zenith", "Sensor Zenith"),
        ("azimuth", "Sensor Azimuth"),
        ("sample", "Sample Azimuth"),
    )
    MOTOR_LIMITS = {
        "zenith": (-90.0, 90.0),
        "azimuth": (-360.0, 360.0),
        "sample": (-360.0, 360.0),
    }

    def __init__(self):
        super().__init__()
        self.title("Goniocontrol GUI")
        self.geometry("1100x760")
        self.workspace = Path(__file__).resolve().parent

        self.state_obj = AppState(workspace=self.workspace)
        persistence = PersistenceService(self.workspace)
        dry_run = os.environ.get("GONIO_DRY_RUN", "0") == "1"
        self.dry_run = dry_run
        if dry_run:
            motors = MockMotorService()
            spectrometer = MockSpectrometerService()
            lcc = MockLCCService()
            self.log_boot = "Running in DRY RUN mode."
        else:
            from goniocontrol_app.services.lcc_service import LCCService
            from goniocontrol_app.services.motor_service import MotorService
            from goniocontrol_app.services.spectrometer_service import SpectrometerService

            motors = MotorService()
            spectrometer = SpectrometerService()
            lcc = LCCService()
            self.log_boot = "Running with real hardware services."
        self.workflow = WorkflowService(self.state_obj, persistence, motors, spectrometer, lcc)
        self.controller = GuiController(self.workflow, self.log, self._set_busy)

        self.busy_var = tk.StringVar(value="Idle")
        self.save_format_var = tk.StringVar(value="reflectance" if self.state_obj.reflectance_mode else "radiance")
        default_outfile = str((self.workspace / "Test00.pickle").resolve())
        self.outfile_var = tk.StringVar(value=default_outfile)
        self.state_obj.outfile = default_outfile
        self.angle_var = tk.StringVar(value=str(self.workspace / "Angles.txt"))
        self.angles_status_var = tk.StringVar(value="Sequence with 0 positions")
        self.repeats_var = tk.StringVar(value="1")
        self.optimize_zenith_var = tk.StringVar(value="0")
        self.white_ref_zenith_var = tk.StringVar(value="0")
        self.dark_last_measured_var = tk.StringVar(value="Not collected yet!")
        self.white_last_measured_var = tk.StringVar(value="Not collected yet!")
        self.motor_labels = dict(self.MOTOR_ROLES)
        self.motor_current_vars = {role: tk.StringVar(value="N/A") for role, _ in self.MOTOR_ROLES}
        self.motor_target_vars = {role: tk.StringVar(value="0.0") for role, _ in self.MOTOR_ROLES}
        self.motor_drive_buttons = {}
        self.motor_zero_buttons = {}
        self._shutting_down = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.after(200, self._startup_refresh)
        self.after(500, self._refresh_motor_angles)

    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        status = ttk.Frame(notebook)
        motors = ttk.Frame(notebook)
        setup = ttk.Frame(notebook)
        plotting = ttk.Frame(notebook)
        notebook.add(status, text="System Status")
        notebook.add(motors, text="Motors")
        notebook.add(setup, text="Measurement")
        notebook.add(plotting, text="Plot/View")

        self.log_text = tk.Text(root, height=12, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=False, pady=(8, 0))

        self._build_status_panel(status)
        self._build_setup_panel(setup)
        self._build_motors_panel(motors)
        self._build_plotting_panel(plotting)
        self.log(self.log_boot)

    def _build_status_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        button_width = 22
        italic_font = tkfont.nametofont("TkDefaultFont").copy()
        italic_font.configure(slant="italic")

        status_row = ttk.Frame(frm)
        status_row.pack(fill=tk.X, pady=2)
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.busy_var).pack(side=tk.LEFT, padx=6)

        actions = (
            ("Restore Spectrometer", self._restore, "Reconnects to spectrometer communication."),
            ("Load Runtime State", self._load_runtime_state, "Unnecessary button? Loads saved runtime settings into the GUI."),
            ("Check configuration", self._run_preflight, "Unnecessary button? Runs startup checks for devices and readiness."),
        )
        for text, command, description in actions:
            row = ttk.Frame(frm)
            row.pack(fill=tk.X, padx=4, pady=2, anchor="w")
            ttk.Button(row, text=text, command=command, width=button_width).pack(side=tk.LEFT)
            ttk.Label(row, text=description, font=italic_font).pack(side=tk.LEFT, padx=(8, 0))

    def _build_setup_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        italic_font = tkfont.nametofont("TkDefaultFont").copy()
        italic_font.configure(slant="italic")
        self.angles_status_font = italic_font

        output_frame = self._build_output_file_frame(frm)
        output_frame.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10))

        calibration_frame = self._build_measurement_calibration_frame(frm)
        calibration_frame.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10))

        manual_frame = self._build_manual_measurement_frame(frm)
        manual_frame.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10))

        sequence_frame = self._build_measurement_sequence_frame(frm)
        sequence_frame.grid(row=3, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 0))

        frm.columnconfigure(1, weight=1)
        sequence_frame.columnconfigure(1, weight=1)

    def _build_output_file_frame(self, parent):
        output_frame = ttk.LabelFrame(parent, text="Output file")
        ttk.Entry(output_frame, textvariable=self.outfile_var, width=60).grid(row=0, column=0, sticky="we", padx=6, pady=4)
        ttk.Button(output_frame, text="Browse", command=self._browse_output_file).grid(row=0, column=1, padx=4, pady=4)
        format_row = ttk.Frame(output_frame)
        format_row.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))
        ttk.Label(format_row, text="Save format:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            format_row,
            text="reflectance",
            value="reflectance",
            variable=self.save_format_var,
            command=self._toggle_mode,
        ).grid(row=0, column=1, padx=(10, 10))
        ttk.Radiobutton(
            format_row,
            text="radiance",
            value="radiance",
            variable=self.save_format_var,
            command=self._toggle_mode,
        ).grid(row=0, column=2)
        output_frame.columnconfigure(0, weight=1)
        return output_frame

    def _build_measurement_calibration_frame(self, parent):
        calibration_frame = ttk.LabelFrame(parent, text="Spectrometer Config")
        calibration_button_width = 16
        ttk.Button(calibration_frame, text="Optimize", command=self._optimize, width=calibration_button_width).grid(
            row=0, column=0, padx=4, pady=4, sticky="w"
        )
        ttk.Label(calibration_frame, text="Sensor Zen").grid(row=0, column=1, sticky="w", padx=(12, 4))
        ttk.Entry(calibration_frame, textvariable=self.optimize_zenith_var, width=10).grid(row=0, column=2, sticky="w", padx=4)
        ttk.Label(
            calibration_frame,
            text="Not optimized yet!",
            font=self.angles_status_font,
        ).grid(row=0, column=3, sticky="w", padx=(10, 4))

        ttk.Button(calibration_frame, text="Dark Current", command=self._dark, width=calibration_button_width).grid(
            row=1, column=0, padx=4, pady=4, sticky="w"
        )
        ttk.Label(calibration_frame, textvariable=self.dark_last_measured_var, font=self.angles_status_font).grid(
            row=1, column=3, sticky="w", padx=(10, 4)
        )

        ttk.Button(calibration_frame, text="White Reference", command=self._white, width=calibration_button_width).grid(
            row=2, column=0, padx=4, pady=4, sticky="w"
        )
        ttk.Label(calibration_frame, text="Sensor Zen").grid(row=2, column=1, sticky="w", padx=(12, 4))
        ttk.Entry(calibration_frame, textvariable=self.white_ref_zenith_var, width=10).grid(row=2, column=2, sticky="w", padx=4)
        ttk.Label(calibration_frame, textvariable=self.white_last_measured_var, font=self.angles_status_font).grid(
            row=2, column=3, sticky="w", padx=(10, 4)
        )

        return calibration_frame

    def _build_measurement_sequence_frame(self, parent):
        sequence_frame = ttk.LabelFrame(parent, text="Measurement Sequence")
        ttk.Label(sequence_frame, text="Angles file:").grid(row=0, column=0, sticky="w")
        ttk.Entry(sequence_frame, textvariable=self.angle_var, width=60, state="readonly").grid(
            row=0, column=1, sticky="we", padx=6
        )
        ttk.Button(sequence_frame, text="Browse", command=self._browse_angle_file).grid(row=0, column=2, padx=4)
        ttk.Label(sequence_frame, textvariable=self.angles_status_var, font=self.angles_status_font).grid(
            row=1, column=1, sticky="w", padx=6
        )
        ttk.Button(sequence_frame, text="Show", command=self._show_angle_file).grid(row=1, column=2, padx=4)

        ttk.Label(sequence_frame, text="Sequence repeats:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(sequence_frame, textvariable=self.repeats_var, width=20).grid(
            row=2, column=1, sticky="w", padx=4, pady=(10, 0)
        )
        style = ttk.Style()
        style.configure("TallMeasure.TButton", padding=(8, 10))

        button_row = ttk.Frame(sequence_frame)
        button_row.grid(row=3, column=1, columnspan=2, pady=(10, 0))
        button_width = 40
        ttk.Button(
            button_row, text="Collect Measurement Sequence", command=self._measure, style="TallMeasure.TButton", width=button_width
        ).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(
            button_row,
            text="Abort Measurement Sequence",
            command=self.controller.cancel,
            style="TallMeasure.TButton",
            width=button_width,
        ).grid(row=0, column=1)
        return sequence_frame

    def _build_manual_measurement_frame(self, parent):
        manual_frame = ttk.LabelFrame(parent, text="Manual measurement")
        style = ttk.Style()
        style.configure("TallMeasure.TButton", padding=(8, 10))
        manual_frame.columnconfigure(0, weight=1)
        ttk.Button(
            manual_frame,
            text="Collect Single Spectrum",
            command=self._measure_single_current_position,
            style="TallMeasure.TButton",
            width=40,
        ).grid(row=0, column=0, padx=6, pady=6)
        return manual_frame

    def _build_motors_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        frm.columnconfigure(0, weight=1)
        goniometer_frame = ttk.LabelFrame(frm, text="Goniometer")
        goniometer_frame.grid(row=0, column=0, sticky="we", padx=4, pady=4)
        ttk.Label(goniometer_frame, text="Motor").grid(row=0, column=0, sticky="w")
        ttk.Label(goniometer_frame, text="Current angle").grid(row=0, column=1, sticky="w")
        ttk.Label(goniometer_frame, text="Target angle").grid(row=0, column=2, sticky="w")
        for row_idx, (role, label) in enumerate(self.MOTOR_ROLES, start=1):
            ttk.Label(goniometer_frame, text="{}:".format(label)).grid(row=row_idx, column=0, sticky="w")
            ttk.Entry(goniometer_frame, textvariable=self.motor_current_vars[role], width=6, state="readonly").grid(
                row=row_idx, column=1, sticky="w", padx=4
            )
            target_controls = ttk.Frame(goniometer_frame)
            target_controls.grid(row=row_idx, column=2, sticky="w", padx=4)
            ttk.Button(target_controls, text="<<", width=3, command=lambda r=role: self._nudge_target(r, -1.0)).grid(
                row=0, column=0, padx=(0, 2)
            )
            ttk.Button(target_controls, text="<", width=3, command=lambda r=role: self._nudge_target(r, -0.1)).grid(
                row=0, column=1, padx=(0, 2)
            )
            ttk.Entry(target_controls, textvariable=self.motor_target_vars[role], width=6).grid(
                row=0, column=2, padx=(0, 2)
            )
            ttk.Button(target_controls, text=">", width=3, command=lambda r=role: self._nudge_target(r, 0.1)).grid(
                row=0, column=3, padx=(0, 2)
            )
            ttk.Button(target_controls, text=">>", width=3, command=lambda r=role: self._nudge_target(r, 1.0)).grid(
                row=0, column=4
            )
            drive_btn = ttk.Button(goniometer_frame, text="Drive", command=lambda r=role: self._drive_motor(r))
            drive_btn.grid(row=row_idx, column=3, padx=4, pady=2)
            zero_btn = ttk.Button(goniometer_frame, text="Set Zero", command=lambda r=role: self._set_motor_zero(r))
            zero_btn.grid(row=row_idx, column=4, padx=4, pady=2)
            self.motor_drive_buttons[role] = drive_btn
            self.motor_zero_buttons[role] = zero_btn
        polarizer_frame = ttk.LabelFrame(frm, text="Polarizer")
        polarizer_frame.grid(row=1, column=0, sticky="we", padx=4, pady=(0, 4))
        ttk.Button(polarizer_frame, text="Calibrate Polarizer", command=self._calibrate_polarizer).grid(
            row=0, column=0, padx=4, pady=4, sticky="w"
        )

    def _build_plotting_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Button(frm, text="View Snapshot", command=self._view).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(frm, text="Plot Current Data", command=self._plot).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(frm, text="VNIR Info", command=self._vnir_info).pack(side=tk.LEFT, padx=4, pady=4)

    def _set_busy(self, busyF):
        self.after(0, lambda: self.busy_var.set("Busy" if busy else "Idle"))

    def _startup_refresh(self):
        self.controller.run_async(
            "Startup initialization",
            self._initialize_on_startup,
            on_error=self._handle_startup_error,
        )

    def _initialize_on_startup(self):
        self.workflow.connect_devices()
        self.workflow.load_runtime_state()
        self.after(0, self._sync_runtime_state_ui)
        if self.state_obj.runtime_notice:
            self.log(self.state_obj.runtime_notice)
        result = self.workflow.startup_preflight()
        self.log("Preflight: {}".format(result))

    def _handle_startup_error(self, exc):
        def show():
            if self.dry_run:
                title = "Startup failed in dry run mode"
            else:
                title = "Hardware startup failed"
            messagebox.showerror(
                title,
                (
                    "Automatic hardware initialization failed.\n\n"
                    "{}\n\n".format(exc)
                    + "Verify spectrometer connectivity and required motor controllers "
                    "(zenith, azimuth, sample), then restart the application."
                ),
            )

        self.after(0, show)

    def _refresh_motor_angles(self):
        if self.controller.is_busy():
            self.after(500, self._refresh_motor_angles)
            return
        for role, _ in self.MOTOR_ROLES:
            available = role in self.workflow.motors.handles and role in self.state_obj.devices.positions_zero
            state = "normal" if available else "disabled"
            self.motor_drive_buttons[role].configure(state=state)
            self.motor_zero_buttons[role].configure(state=state)
            if not available:
                self.motor_current_vars[role].set("N/A")
                continue
            try:
                self.workflow.refresh_motor_position(role)
                angle = self.workflow.get_motor_angle_from_zero(role)
                self.motor_current_vars[role].set(self._format_angle(angle))
            except Exception:
                self.motor_current_vars[role].set("N/A")
        self.after(500, self._refresh_motor_angles)

    def log(self, msg):
        def append():
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)

        self.after(0, append)

    def _run_preflight(self):
        self.state_obj.angles_file = Path(self.angle_var.get())
        result = self.workflow.startup_preflight()
        self.log("Status: {}".format(result))

    def _load_runtime_state(self):
        def run():
            self.workflow.load_runtime_state()
            self.after(0, self._sync_runtime_state_ui)
            if self.state_obj.runtime_notice:
                self.log(self.state_obj.runtime_notice)

        self.controller.run_async("Load runtime state", run)

    def _sync_runtime_state_ui(self):
        self.outfile_var.set(self.state_obj.outfile)
        angle_path = self.workflow.resolve_path(self.state_obj.angles_file)
        self.angle_var.set(str(angle_path))
        self.angles_status_var.set("Sequence with {} positions".format(len(self.state_obj.angles)))
        self.save_format_var.set("reflectance" if self.state_obj.reflectance_mode else "radiance")

    def _browse_output_file(self):
        current = Path(self.outfile_var.get().strip() or (self.workspace / "Test00.pickle"))
        selected = filedialog.asksaveasfilename(
            title="Select output file",
            initialdir=str(current.parent if current.parent.exists() else self.workspace),
            initialfile=current.name,
            defaultextension=".pickle",
            filetypes=[("Pickle files", "*.pickle"), ("All files", "*.*")],
        )
        if not selected:
            return
        selected_path = Path(selected)
        if selected_path.suffix.lower() != ".pickle":
            selected_path = selected_path.with_suffix(".pickle")
        outfile = str(selected_path.resolve())
        self.outfile_var.set(outfile)
        self.controller.run_async("New dataset", lambda: self.workflow.new_dataset(outfile))

    def _browse_angle_file(self):
        selected = filedialog.askopenfilename(
            title="Select angle file",
            initialdir=self.workspace,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if selected:
            self.angle_var.set(selected)
            self._apply_angles()

    def _apply_angles(self):
        path = Path(self.angle_var.get())

        def run():
            self.state_obj.angles_file = path
            self.state_obj.angles = self.workflow.persistence.read_angles(path)
            loaded_positions = len(self.state_obj.angles)
            self.after(0, lambda: self.angles_status_var.set("Sequence with {} positions".format(loaded_positions)))
            self.workflow.save_runtime_settings()
            self.log("Loaded {} angle rows from {}".format(len(self.state_obj.angles), path))

        self.controller.run_async("Load angles", run)

    def _show_angle_file(self):
        path = Path(self.angle_var.get())
        if not path.exists():
            messagebox.showerror("Angles file missing", "Angles file does not exist:\n{}".format(path))
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Open file failed", "Could not open angles file:\n{}".format(exc))

    def _toggle_mode(self):
        # Keep both GUI and backend mode aligned.
        desired = self.save_format_var.get() == "reflectance"
        if self.state_obj.reflectance_mode != desired:
            self.workflow.toggle_mode()
        self.log("Mode => {}".format("Reflectance" if self.state_obj.reflectance_mode else "Radiance"))

    def _restore(self):
        self.controller.run_async("Restore spectrometer", self.workflow.restore_spectrometer)

    def _optimize(self):
        za = float(self.optimize_zenith_var.get() or "0")
        self.controller.run_async("Optimize", lambda: self.workflow.optimize(za, progress=self.log))

    def _dark(self):
        def run():
            self.workflow.collect_dark()
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.after(0, lambda: self.dark_last_measured_var.set("Last collection: {}".format(timestamp)))

        self.controller.run_async("Collect dark", run)

    def _white(self):
        def run():
            za = float(self.white_ref_zenith_var.get() or "0")
            self.workflow.collect_white(za)
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.after(0, lambda: self.white_last_measured_var.set("Last collection: {}".format(timestamp)))

        self.controller.run_async("Collect white", run)

    def _ending_white(self):
        za = float(self.white_ref_zenith_var.get() or "0")
        self.controller.run_async("Collect ending white", lambda: self.workflow.collect_ending_white(za))

    def _calibrate_polarizer(self):
        za = float(self.white_ref_zenith_var.get() or "0")
        self.controller.run_async("Calibrate polarizer", lambda: self.workflow.calibrate_polarizer(za, progress=self.log))

    def _format_angle(self, angle):
        return "{:+.2f}°".format(angle)

    def _nudge_target(self, role: str, delta):
        raw = self.motor_target_vars[role].get().strip()
        try:
            current = float(raw) if raw else 0.0
        except ValueError:
            current = 0.0
        self.motor_target_vars[role].set("{:.2f}".format(current + delta))

    def _confirm_out_of_range(self, role, value):
        minimum, maximum = self.MOTOR_LIMITS[role]
        if minimum <= value <= maximum:
            return True
        return messagebox.askyesno(
            "Target angle outside nominal range",
            (
                "{} target {:.2f}° is outside nominal range [{:.2f}, {:.2f}]°. Continue?".format(
                    self.motor_labels[role], value, minimum, maximum
                )
            ),
        )

    def _drive_motor(self, role):
        try:
            target = float(self.motor_target_vars[role].get() or "0")
        except ValueError:
            messagebox.showerror("Invalid input", "Enter a numeric target angle for {}.".format(self.motor_labels[role]))
            return
        if not self._confirm_out_of_range(role, target):
            return
        motor_name = self.motor_labels[role]
        self.controller.run_async(
            "Drive {} to {:.2f} deg".format(motor_name, target),
            lambda: self.workflow.drive_motor_to_angle(role, target),
        )

    def _set_motor_zero(self, role):
        motor_name = self.motor_labels[role]
        self.controller.run_async("Set zero for {}".format(motor_name), lambda: self.workflow.set_zero_at_current_position(role))

    def _measure(self):
        angle_path = Path(self.angle_var.get())
        self.state_obj.angles_file = angle_path
        if not self.state_obj.angles:
            try:
                self.state_obj.angles = self.workflow.persistence.read_angles(angle_path)
                loaded_positions = len(self.state_obj.angles)
                self.angles_status_var.set("Sequence with {} positions".format(loaded_positions))
                self.log("Loaded {} angle rows from {}".format(loaded_positions, angle_path))
            except Exception as exc:
                messagebox.showerror("Angles file error", "Could not load angles file:\n{}".format(exc))
                return
        if len(self.state_obj.angles) == 0:
            messagebox.showerror("Angles required", "Measurement sequence requires at least one angle row.")
            return
        repeats = int(self.repeats_var.get() or "1")
        self.controller.run_measure(repeats)

    def _measure_single_current_position(self):
        try:
            sensor_pol = self.workflow.get_motor_angle_from_zero("sensor_polarizer")
        except Exception:
            sensor_pol = 0.0
        try:
            lamp_pol = self.workflow.get_motor_angle_from_zero("lamp_polarizer")
        except Exception:
            lamp_pol = 0.0
        try:
            zenith = self.workflow.get_motor_angle_from_zero("zenith")
            azimuth = self.workflow.get_motor_angle_from_zero("azimuth")
            sample = self.workflow.get_motor_angle_from_zero("sample")
        except Exception as exc:
            messagebox.showerror("Manual measurement unavailable", "Could not read current motor angles:\n{}".format(exc))
            return

        angle_row = (sensor_pol, lamp_pol, zenith, azimuth, sample, 0.0, 1.0)
        previous_angles = list(self.state_obj.angles)
        self.log(
            "Manual single-spectrum at current position: "
            "sz={:.2f}, sa00={:.2f}, ze={:.2f}, az={:.2f}, sample={:.2f}".format(
                sensor_pol, lamp_pol, zenith, azimuth, sample
            )
        )
        self.state_obj.angles = [angle_row]

        def run_manual_measure():
            try:
                self.workflow.measure_sequence(
                    repeats=1,
                    progress=self.log,
                    should_cancel=self.controller._cancel_event.is_set,
                )
            finally:
                self.state_obj.angles = previous_angles

        self.controller.run_async("Manual single spectrum", run_manual_measure)

    def _view(self):
        self.controller.run_async("View snapshot", self.workflow.view_snapshot)

    def _plot(self):
        self.controller.run_async("Plot data", self.workflow.plot_current_data)

    def _vnir_info(self):
        self.controller.run_async("VNIR info", lambda: self.log(str(self.workflow.show_vnir_info())))

    def _shutdown(self):
        if self._shutting_down:
            return
        if messagebox.askyesno("Exit", "Shutdown devices and exit?"):
            if self.controller.is_busy():
                messagebox.showwarning("Busy", "Wait for the current operation to finish, then try shutdown again.")
                return
            self._shutting_down = True
            self.busy_var.set("Shutting down")
            self.update_idletasks()
            try:
                self.workflow.shutdown()
            except Exception as exc:
                self._shutting_down = False
                self.busy_var.set("Idle")
                messagebox.showerror("Shutdown failed", "Could not shutdown devices:\n{}".format(exc))
                return
            self._finalize_exit()

    def _finalize_exit(self):
        self.controller.shutdown_executor()
        self.quit()
        self.destroy()


def main():
    app = GoniocontrolGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

