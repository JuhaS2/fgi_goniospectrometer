#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from goniocontrol_app.gui_controller import GuiController
from goniocontrol_app.services.mock_services import (
    MockLCCService,
    MockMotorService,
    MockSpectrometerService,
)
from goniocontrol_app.services.live_spectrum_service import LiveSpectrumService
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
        self.geometry("800x416")
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
            from goniocontrol_app.services.spectrometer_service import (
                SpectrometerService,
            )

            motors = MotorService()
            spectrometer = SpectrometerService()
            lcc = LCCService()
            self.log_boot = "Running with real hardware services."
        self.log_boot += " Runtime state dir: {}".format(persistence.state_dir)
        self.workflow = WorkflowService(
            self.state_obj, persistence, motors, spectrometer, lcc
        )
        self.controller = GuiController(self.workflow, self.log, self._set_busy)
        self.live_spectrum_service = LiveSpectrumService(
            spectrometer=spectrometer,
            emit_log=self.log,
            should_idle_poll=lambda: not self.controller.is_busy()
            and not self._shutting_down,
        )
        self.workflow.on_spectrum = self.live_spectrum_service.on_spectrum

        self.busy_var = tk.StringVar(value="Idle")
        self.spectrometer_status_var = tk.StringVar(value="Unknown")
        self.motors_status_var = tk.StringVar(value="Unknown")
        self.polarizer_status_var = tk.StringVar(value="Unknown")
        self.save_format_var = tk.StringVar(
            value="reflectance" if self.state_obj.reflectance_mode else "radiance"
        )
        default_outfile = str((self.workspace / "Test00.pickle").resolve())
        self.outfile_var = tk.StringVar(value=default_outfile)
        self.state_obj.outfile = default_outfile
        self.angle_var = tk.StringVar(value=str(self.workspace / "Angles.txt"))
        self.angles_status_var = tk.StringVar(value="Sequence with 0 positions")
        self.repeats_var = tk.StringVar(value="1")
        self.sensor_zenith_var = tk.StringVar(value="0")
        self.optimize_status_var = tk.StringVar(value="Not optimized yet!")
        self.dark_last_measured_var = tk.StringVar(value="Not collected yet!")
        self.white_last_measured_var = tk.StringVar(value="Not collected yet!")
        self.angles_status_font = tkfont.nametofont("TkDefaultFont").copy()
        self.angles_status_font.configure(slant="italic")
        self.status_value_font = tkfont.nametofont("TkDefaultFont").copy()
        self.status_value_font.configure(weight="bold")
        self.motor_labels = dict(self.MOTOR_ROLES)
        self.motor_current_vars = {
            role: tk.StringVar(value="N/A") for role, _ in self.MOTOR_ROLES
        }
        self.motor_target_vars = {
            role: tk.StringVar(value="0.0") for role, _ in self.MOTOR_ROLES
        }
        self.motor_drive_buttons = {}
        self.motor_zero_buttons = {}
        self._shutting_down = False
        self.live_source_var = tk.StringVar(value="none")
        self.live_timestamp_var = tk.StringVar(value="n/a")
        self._live_last_seq = -1
        self._live_line = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.after(200, self._startup_refresh)
        self.after(500, self._refresh_motor_angles)
        self.after(700, self._refresh_device_status)
        self.after(400, self._refresh_live_plot)

    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        status = ttk.Frame(notebook)
        motors = ttk.Frame(notebook)
        spectrometer = ttk.Frame(notebook)
        setup = ttk.Frame(notebook)
        notebook.add(status, text="System Status")
        notebook.add(motors, text="Motors")
        notebook.add(spectrometer, text="Spectrometer")
        notebook.add(setup, text="Measurement")

        self._build_status_panel(status)
        self._build_motors_panel(motors)
        self._build_spectrometer_panel(spectrometer)
        self._build_setup_panel(setup)
        self.log(self.log_boot)

    def _build_status_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        button_width = 22
        italic_font = tkfont.nametofont("TkDefaultFont").copy()
        italic_font.configure(slant="italic")
        frm.columnconfigure(0, weight=1)

        status_row = ttk.Frame(frm)
        status_row.pack(fill=tk.X, pady=(2, 4))
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        tk.Label(
            status_row, textvariable=self.busy_var, font=self.status_value_font
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(status_row, text="Spectrometer:").pack(side=tk.LEFT, padx=(12, 4))
        self.spectrometer_status_label = tk.Label(
            status_row,
            textvariable=self.spectrometer_status_var,
            font=self.status_value_font,
            fg="black",
        )
        self.spectrometer_status_label.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(status_row, text="Motors:").pack(side=tk.LEFT, padx=(4, 4))
        self.motors_status_label = tk.Label(
            status_row,
            textvariable=self.motors_status_var,
            font=self.status_value_font,
            fg="black",
        )
        self.motors_status_label.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(status_row, text="Polarizer:").pack(side=tk.LEFT, padx=(4, 4))
        self.polarizer_status_label = tk.Label(
            status_row,
            textvariable=self.polarizer_status_var,
            font=self.status_value_font,
            fg="black",
        )
        self.polarizer_status_label.pack(side=tk.LEFT, padx=(0, 2))

        actions_frame = ttk.Frame(frm)
        actions_frame.pack(fill=tk.X)
        actions = (
            (
                "Restore Spectrometer",
                self._restore,
                "Reconnects to spectrometer communication.",
            ),
            (
                "Load Runtime State",
                self._load_runtime_state,
                "Unnecessary button? Loads saved runtime settings into the GUI.",
            ),
            (
                "Check configuration",
                self._run_preflight,
                "Unnecessary button? Runs startup checks for devices and readiness.",
            ),
        )
        for text, command, description in actions:
            row = ttk.Frame(actions_frame)
            row.pack(fill=tk.X, padx=4, pady=2, anchor="w")
            ttk.Button(row, text=text, command=command, width=button_width).pack(
                side=tk.LEFT
            )
            ttk.Label(row, text=description, font=italic_font).pack(
                side=tk.LEFT, padx=(8, 0)
            )

        log_frame = ttk.LabelFrame(frm, text="Terminal Output")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(8, 0))
        self.log_text = tk.Text(log_frame, wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)

    def _build_setup_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        output_frame = self._build_output_file_frame(frm)
        output_frame.grid(
            row=0, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10)
        )

        manual_frame = self._build_manual_measurement_frame(frm)
        manual_frame.grid(
            row=1, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10)
        )

        sequence_frame = self._build_measurement_sequence_frame(frm)
        sequence_frame.grid(
            row=2, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 0)
        )

        frm.columnconfigure(1, weight=1)
        sequence_frame.columnconfigure(1, weight=1)

    def _build_spectrometer_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        frm.columnconfigure(0, weight=0)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(0, weight=1)
        left_column = ttk.Frame(frm)
        left_column.grid(row=0, column=0, sticky="nsw", padx=(2, 8), pady=0)
        sensor_zenith_frame = self._build_sensor_zenith_frame(left_column)
        sensor_zenith_frame.pack(fill=tk.X, padx=0, pady=(0, 8))
        calibration_frame = self._build_measurement_calibration_frame(left_column)
        calibration_frame.pack(fill=tk.X, padx=0, pady=0)
        live_frame = ttk.LabelFrame(frm, text="Live spectrum")
        live_frame.grid(row=0, column=1, sticky="nsew", padx=2, pady=0)

        meta_row = ttk.Frame(live_frame)
        meta_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(meta_row, text="Source:").pack(side=tk.LEFT)
        ttk.Label(meta_row, textvariable=self.live_source_var).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(meta_row, text="Timestamp:").pack(side=tk.LEFT)
        ttk.Label(meta_row, textvariable=self.live_timestamp_var).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        self.live_figure = Figure(figsize=(7.2, 2.5), dpi=100)
        ax = self.live_figure.add_subplot(111)
        # ax.set_title("Latest spectrum")
        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("DN")
        ax.grid(True)
        self._live_ax = ax
        self.live_canvas = FigureCanvasTkAgg(self.live_figure, master=live_frame)
        self.live_canvas.get_tk_widget().pack(
            fill=tk.BOTH, expand=True, padx=4, pady=(0, 4)
        )

    def _build_sensor_zenith_frame(self, parent):
        sensor_frame = ttk.LabelFrame(parent, text="Sensor Zenith")
        ttk.Button(
            sensor_frame,
            text="Drive",
            width=6,
            command=self._drive_sensor_zenith,
        ).grid(row=0, column=0, padx=(4, 2), pady=4, sticky="w")
        ttk.Entry(sensor_frame, textvariable=self.sensor_zenith_var, width=8).grid(
            row=0, column=1, padx=(2, 4), pady=4, sticky="w"
        )
        return sensor_frame

    def _build_output_file_frame(self, parent):
        output_frame = ttk.LabelFrame(parent, text="Output file")
        ttk.Entry(output_frame, textvariable=self.outfile_var, width=60).grid(
            row=0, column=0, sticky="we", padx=6, pady=4
        )
        ttk.Button(output_frame, text="Browse", command=self._browse_output_file).grid(
            row=0, column=1, padx=4, pady=4
        )
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
        calibration_frame.columnconfigure(0, weight=0)
        ttk.Button(
            calibration_frame,
            text="Optimize",
            command=self._optimize,
            width=calibration_button_width,
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ttk.Label(
            calibration_frame,
            textvariable=self.optimize_status_var,
            font=self.angles_status_font,
        ).grid(row=1, column=0, sticky="w", padx=4, pady=(0, 4))

        ttk.Button(
            calibration_frame,
            text="Dark Current",
            command=self._dark,
            width=calibration_button_width,
        ).grid(row=2, column=0, padx=4, pady=(6, 4), sticky="w")
        ttk.Label(
            calibration_frame,
            textvariable=self.dark_last_measured_var,
            font=self.angles_status_font,
        ).grid(row=3, column=0, sticky="w", padx=4, pady=(0, 4))

        ttk.Button(
            calibration_frame,
            text="White Reference",
            command=self._white,
            width=calibration_button_width,
        ).grid(row=4, column=0, padx=4, pady=(6, 4), sticky="w")
        ttk.Label(
            calibration_frame,
            textvariable=self.white_last_measured_var,
            font=self.angles_status_font,
        ).grid(row=5, column=0, sticky="w", padx=4, pady=(0, 4))

        return calibration_frame

    def _build_measurement_sequence_frame(self, parent):
        sequence_frame = ttk.LabelFrame(parent, text="Measurement Sequence")
        ttk.Label(sequence_frame, text="Angles file:").grid(row=0, column=0, sticky="w")
        ttk.Entry(
            sequence_frame, textvariable=self.angle_var, width=60, state="readonly"
        ).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(sequence_frame, text="Browse", command=self._browse_angle_file).grid(
            row=0, column=2, padx=4
        )
        ttk.Label(
            sequence_frame,
            textvariable=self.angles_status_var,
            font=self.angles_status_font,
        ).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(sequence_frame, text="Show", command=self._show_angle_file).grid(
            row=1, column=2, padx=4
        )

        ttk.Label(sequence_frame, text="Sequence repeats:").grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Entry(sequence_frame, textvariable=self.repeats_var, width=20).grid(
            row=2, column=1, sticky="w", padx=4, pady=(10, 0)
        )
        style = ttk.Style()
        style.configure("TallMeasure.TButton", padding=(8, 10))

        button_row = ttk.Frame(sequence_frame)
        button_row.grid(row=3, column=1, columnspan=2, pady=(10, 0))
        button_width = 30
        ttk.Button(
            button_row,
            text="Collect Measurement Sequence",
            command=self._measure,
            style="TallMeasure.TButton",
            width=button_width,
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
        ttk.Label(goniometer_frame, text="Current angle").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(goniometer_frame, text="Target angle").grid(
            row=0, column=2, sticky="w"
        )
        for row_idx, (role, label) in enumerate(self.MOTOR_ROLES, start=1):
            ttk.Label(goniometer_frame, text="{}:".format(label)).grid(
                row=row_idx, column=0, sticky="w"
            )
            ttk.Entry(
                goniometer_frame,
                textvariable=self.motor_current_vars[role],
                width=6,
                state="readonly",
            ).grid(row=row_idx, column=1, sticky="w", padx=4)
            target_controls = ttk.Frame(goniometer_frame)
            target_controls.grid(row=row_idx, column=2, sticky="w", padx=4)
            ttk.Button(
                target_controls,
                text="<<",
                width=3,
                command=lambda r=role: self._nudge_target(r, -1.0),
            ).grid(row=0, column=0, padx=(0, 2))
            ttk.Button(
                target_controls,
                text="<",
                width=3,
                command=lambda r=role: self._nudge_target(r, -0.1),
            ).grid(row=0, column=1, padx=(0, 2))
            ttk.Entry(
                target_controls, textvariable=self.motor_target_vars[role], width=6
            ).grid(row=0, column=2, padx=(0, 2))
            ttk.Button(
                target_controls,
                text=">",
                width=3,
                command=lambda r=role: self._nudge_target(r, 0.1),
            ).grid(row=0, column=3, padx=(0, 2))
            ttk.Button(
                target_controls,
                text=">>",
                width=3,
                command=lambda r=role: self._nudge_target(r, 1.0),
            ).grid(row=0, column=4)
            drive_btn = ttk.Button(
                goniometer_frame,
                text="Drive",
                command=lambda r=role: self._drive_motor(r),
            )
            drive_btn.grid(row=row_idx, column=3, padx=4, pady=2)
            zero_btn = ttk.Button(
                goniometer_frame,
                text="Set Zero",
                command=lambda r=role: self._set_motor_zero(r),
            )
            zero_btn.grid(row=row_idx, column=4, padx=4, pady=2)
            self.motor_drive_buttons[role] = drive_btn
            self.motor_zero_buttons[role] = zero_btn
        polarizer_frame = ttk.LabelFrame(frm, text="Polarizer")
        polarizer_frame.grid(row=1, column=0, sticky="we", padx=4, pady=(0, 4))
        ttk.Button(
            polarizer_frame,
            text="Calibrate Polarizer",
            command=self._calibrate_polarizer,
            state="disabled",
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")

    def _set_busy(self, busy):
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
        self.live_spectrum_service.start()
        self.after(0, self._sync_runtime_state_ui)
        self.after(0, self._update_device_status_labels)
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
            available = (
                role in self.workflow.motors.handles
                and role in self.state_obj.devices.positions_zero
            )
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
        self._update_device_status_labels()

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
        self.optimize_status_var.set(
            self._format_optimize_status(self.state_obj.calibration.optimizer_header)
        )
        self.angles_status_var.set(
            "Sequence with {} positions".format(len(self.state_obj.angles))
        )
        self.save_format_var.set(
            "reflectance" if self.state_obj.reflectance_mode else "radiance"
        )

    def _format_optimize_status(self, header):
        if header is None:
            return "Not optimized yet!"
        try:
            itime = int(header[2])
            gain = [int(header[3][0]), int(header[3][1])]
            offset = [int(header[4][0]), int(header[4][1])]
        except Exception:
            return "Optimize parameters unavailable"
        return "itime={} gain={} offset={}".format(itime, gain, offset)

    def _browse_output_file(self):
        current = Path(
            self.outfile_var.get().strip() or (self.workspace / "Test00.pickle")
        )
        selected = filedialog.asksaveasfilename(
            title="Select output file",
            initialdir=str(
                current.parent if current.parent.exists() else self.workspace
            ),
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
        self.controller.run_async(
            "New dataset", lambda: self.workflow.new_dataset(outfile)
        )

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
            self.after(
                0,
                lambda: self.angles_status_var.set(
                    "Sequence with {} positions".format(loaded_positions)
                ),
            )
            self.workflow.save_runtime_settings()
            self.log(
                "Loaded {} angle rows from {}".format(len(self.state_obj.angles), path)
            )

        self.controller.run_async("Load angles", run)

    def _show_angle_file(self):
        path = Path(self.angle_var.get())
        if not path.exists():
            messagebox.showerror(
                "Angles file missing", "Angles file does not exist:\n{}".format(path)
            )
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror(
                "Open file failed", "Could not open angles file:\n{}".format(exc)
            )

    def _toggle_mode(self):
        # Keep both GUI and backend mode aligned.
        desired = self.save_format_var.get() == "reflectance"
        if self.state_obj.reflectance_mode != desired:
            self.workflow.toggle_mode()
        self.log(
            "Mode => {}".format(
                "Reflectance" if self.state_obj.reflectance_mode else "Radiance"
            )
        )

    def _restore(self):
        def run():
            self.workflow.restore_spectrometer()
            self.after(0, self._update_device_status_labels)

        self.controller.run_async("Restore spectrometer", run)

    def _optimize(self):
        za = float(self.sensor_zenith_var.get() or "0")
        def run():
            self.workflow.optimize(za, progress=self.log)
            self.after(
                0,
                lambda: self.optimize_status_var.set(
                    self._format_optimize_status(
                        self.state_obj.calibration.optimizer_header
                    )
                ),
            )
        self.controller.run_async(
            "Optimize", run
        )

    def _dark(self):
        def run():
            self.workflow.collect_dark()
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.after(
                0,
                lambda: self.dark_last_measured_var.set(
                    "Last collection: {}".format(timestamp)
                ),
            )

        self.controller.run_async("Collect dark", run)

    def _white(self):
        def run():
            za = float(self.sensor_zenith_var.get() or "0")
            self.workflow.collect_white(za)
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.after(
                0,
                lambda: self.white_last_measured_var.set(
                    "Last collection: {}".format(timestamp)
                ),
            )

        self.controller.run_async("Collect white", run)

    def _ending_white(self):
        za = float(self.sensor_zenith_var.get() or "0")
        self.controller.run_async(
            "Collect ending white", lambda: self.workflow.collect_ending_white(za)
        )

    def _calibrate_polarizer(self):
        za = float(self.sensor_zenith_var.get() or "0")
        self.controller.run_async(
            "Calibrate polarizer",
            lambda: self.workflow.calibrate_polarizer(za, progress=self.log),
        )

    def _drive_sensor_zenith(self):
        try:
            target = float(self.sensor_zenith_var.get() or "0")
        except ValueError:
            messagebox.showerror(
                "Invalid input",
                "Enter a numeric target angle for Sensor Zenith.",
            )
            return
        if not self._confirm_out_of_range("zenith", target):
            return
        self.controller.run_async(
            "Drive Sensor Zenith to {:.2f} deg".format(target),
            lambda: self.workflow.drive_motor_to_angle("zenith", target),
        )

    def _format_angle(self, angle):
        return "{:+.2f}°".format(angle)

    def _nudge_target(self, role, delta):
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
            messagebox.showerror(
                "Invalid input",
                "Enter a numeric target angle for {}.".format(self.motor_labels[role]),
            )
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
        self.controller.run_async(
            "Set zero for {}".format(motor_name),
            lambda: self.workflow.set_zero_at_current_position(role),
        )

    def _measure(self):
        angle_path = Path(self.angle_var.get())
        self.state_obj.angles_file = angle_path
        if not self.state_obj.angles:
            try:
                self.state_obj.angles = self.workflow.persistence.read_angles(
                    angle_path
                )
                loaded_positions = len(self.state_obj.angles)
                self.angles_status_var.set(
                    "Sequence with {} positions".format(loaded_positions)
                )
                self.log(
                    "Loaded {} angle rows from {}".format(loaded_positions, angle_path)
                )
            except Exception as exc:
                messagebox.showerror(
                    "Angles file error", "Could not load angles file:\n{}".format(exc)
                )
                return
        if len(self.state_obj.angles) == 0:
            messagebox.showerror(
                "Angles required",
                "Measurement sequence requires at least one angle row.",
            )
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
            messagebox.showerror(
                "Manual measurement unavailable",
                "Could not read current motor angles:\n{}".format(exc),
            )
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
        self.controller.run_async(
            "VNIR info", lambda: self.log(str(self.workflow.show_vnir_info()))
        )

    def _update_device_status_labels(self):
        try:
            snapshot = self.workflow.get_device_status_snapshot()
        except Exception:
            snapshot = {
                "spectrometer": "Unknown",
                "motors": "Unknown",
                "polarizer": "Unknown",
            }
        self.spectrometer_status_var.set(snapshot["spectrometer"])
        self.motors_status_var.set(snapshot["motors"])
        self.polarizer_status_var.set(snapshot["polarizer"])
        self.spectrometer_status_label.configure(
            fg=(
                "red"
                if snapshot["spectrometer"].startswith("NOT CONNECTED")
                else "black"
            )
        )
        self.motors_status_label.configure(
            fg="red" if snapshot["motors"].startswith("NOT CONNECTED") else "black"
        )
        self.polarizer_status_label.configure(fg="black")

    def _refresh_device_status(self):
        if self._shutting_down:
            return
        self._update_device_status_labels()
        self.after(2000, self._refresh_device_status)

    def _refresh_live_plot(self):
        if self._shutting_down:
            return
        latest, seq = self.live_spectrum_service.get_latest()
        if latest is not None and seq != self._live_last_seq:
            spectrum = latest.get("spectrum")
            if spectrum is not None:
                wl = getattr(self.workflow, "_wl", None)
                if wl is None or len(wl) != len(spectrum):
                    wl = np.arange(len(spectrum))
                if self._live_line is None:
                    (self._live_line,) = self._live_ax.plot(wl, spectrum)
                else:
                    self._live_line.set_data(wl, spectrum)
                self._live_ax.relim()
                self._live_ax.autoscale_view()
                self.live_canvas.draw_idle()
                self._live_last_seq = seq
            source = latest.get("source", "unknown")
            self.live_source_var.set(str(source))
            stamp = datetime.fromtimestamp(latest.get("timestamp", 0)).strftime(
                "%H:%M:%S"
            )
            self.live_timestamp_var.set(stamp)
        self.after(150, self._refresh_live_plot)

    def _shutdown(self):
        if self._shutting_down:
            return
        if messagebox.askyesno("Exit", "Shutdown devices and exit?"):
            if self.controller.is_busy():
                messagebox.showwarning(
                    "Busy",
                    "Wait for the current operation to finish, then try shutdown again.",
                )
                return
            self._shutting_down = True
            self.busy_var.set("Shutting down")
            self.update_idletasks()
            try:
                self.live_spectrum_service.stop()
                self.workflow.shutdown()
            except Exception as exc:
                self._shutting_down = False
                self.busy_var.set("Idle")
                messagebox.showerror(
                    "Shutdown failed", "Could not shutdown devices:\n{}".format(exc)
                )
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
