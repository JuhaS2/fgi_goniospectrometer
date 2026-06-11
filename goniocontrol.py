#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import math
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from asdcontroller.asd_types import ITimeEnum
from goniocontrol_app.errors import PreconditionError
from goniocontrol_app.gui_controller import GuiController
from goniocontrol_app.services.mock_services import (
    MockLCCService,
    MockMotorService,
    MockSpectrometerService,
)
from goniocontrol_app.services.live_spectrum_service import LiveSpectrumService
from goniocontrol_app.services.persistence_service import PersistenceService
from goniocontrol_app.state import (
    CALIBRATION_SPECTRUM_AVERAGES,
    DEFAULT_SEQUENCE_REPEATS,
    DEFAULT_SPECTRUM_AVERAGES,
    AppState,
)
from goniocontrol_app.workflow_service import WorkflowService

DEFAULT_OUTPUT_DATA_DIR = Path("/home/pi/Desktop/Data")
BASE_WINDOW_TITLE = "Goniocontrol GUI"


class GoniocontrolGUI(tk.Tk):
    MOTOR_ROLES = (
        ("zenith", "Sensor Zenith"),
        ("azimuth", "Sensor Azimuth"),
        ("sample", "Sample Azimuth"),
    )
    MOTOR_LIMITS = {
        "zenith": (-95.0, 95.0),
        "azimuth": (-365.0, 365.0),
        "sample": (-365.0, 365.0),
    }

    def __init__(self):
        super().__init__()
        self.title(BASE_WINDOW_TITLE)
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
        self.controller = GuiController(
            self.workflow, self.log, self._set_busy, self._set_window_status
        )
        self._shutting_down = False
        self.live_spectrum_service = LiveSpectrumService(
            spectrometer=spectrometer,
            emit_log=self.log,
            should_idle_poll=lambda: not self.controller.is_busy()
            and not self._shutting_down,
            get_spectrum_averages=lambda: self.state_obj.spectrum_averages,
        )
        self.workflow.on_spectrum = self.live_spectrum_service.on_spectrum
        # Dedicated single-thread executor for periodic spectrometer health
        # probes. Kept separate from the GuiController worker so a long-running
        # measurement does not block the status indicator, and so a stuck probe
        # cannot starve user-driven operations.
        self._status_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="StatusProbe"
        )
        self._spectrometer_status_cache = "Unknown"
        self._spectrometer_probe_in_flight = False

        self.busy_var = tk.StringVar(value="Idle")
        self.spectrometer_status_var = tk.StringVar(value="Unknown")
        self.motors_status_var = tk.StringVar(value="Unknown")
        self.polarizer_status_var = tk.StringVar(value="Unknown")
        self.save_format_var = tk.StringVar(
            value="reflectance" if self.state_obj.reflectance_mode else "radiance"
        )
        self.outfile_var = tk.StringVar(value="")
        self.output_authors_var = tk.StringVar(value="")
        self.output_target_name_var = tk.StringVar(value="")
        self.angle_var = tk.StringVar(
            value=str(self.workspace / "example_sequences/PrincipalPlane_5deg.seq.txt")
        )
        self.angles_status_var = tk.StringVar(value="Sequence with 0 positions")
        self.repeats_var = tk.StringVar(value=str(DEFAULT_SEQUENCE_REPEATS))
        self.spectrum_averages_var = tk.StringVar(
            value=str(DEFAULT_SPECTRUM_AVERAGES)
        )
        self.spectrum_averages_var.trace_add(
            "write", lambda *_: self._push_acquisition_settings_to_state()
        )
        self.calibration_averages_var = tk.StringVar(
            value=str(CALIBRATION_SPECTRUM_AVERAGES)
        )
        self.calibration_averages_var.trace_add(
            "write", lambda *_: self._push_calibration_settings_to_state()
        )
        self._push_acquisition_settings_to_state()
        self._push_calibration_settings_to_state()
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
        self.light_zenith_var = tk.StringVar(value="0.00")
        self.light_azimuth_var = tk.StringVar(value="0.00")
        self.motor_drive_buttons = {}
        self.motor_zero_buttons = {}
        self.live_source_var = tk.StringVar(value="none")
        self.live_timestamp_var = tk.StringVar(value="n/a")
        self.live_view_mode_var = tk.StringVar(value="dn")
        self.live_plot_status_var = tk.StringVar(value="")
        self._live_last_seq = -1
        self._live_fg_line = None
        self._live_bg_line = None
        self._dark_collected_at = None
        self._white_collected_at = None

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
        output_file_tab = ttk.Frame(notebook)
        setup = ttk.Frame(notebook)
        notebook.add(status, text="System Status")
        notebook.add(motors, text="Motors")
        notebook.add(spectrometer, text="Spectrometer")
        notebook.add(output_file_tab, text="Output&Metadata")
        notebook.add(setup, text="Measurement")

        self._build_status_panel(status)
        self._build_motors_panel(motors)
        self._build_spectrometer_panel(spectrometer)
        self._build_output_file_panel(output_file_tab)
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

        manual_frame = self._build_manual_measurement_frame(frm)
        manual_frame.grid(
            row=0, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10)
        )

        sequence_frame = self._build_measurement_sequence_frame(frm)
        sequence_frame.grid(
            row=1, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 0)
        )

        frm.columnconfigure(1, weight=1)
        sequence_frame.columnconfigure(1, weight=1)

    def _build_output_file_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(3, weight=1)

        output_frame = self._build_output_file_frame(frm)
        output_frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=(0, 10))

        authors_row = ttk.Frame(frm)
        authors_row.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 6))
        authors_row.columnconfigure(1, weight=1)
        ttk.Label(authors_row, text="Authors:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(authors_row, textvariable=self.output_authors_var).grid(
            row=0, column=1, sticky="ew"
        )

        target_row = ttk.Frame(frm)
        target_row.grid(row=2, column=0, sticky="ew", padx=2, pady=(0, 8))
        target_row.columnconfigure(1, weight=1)
        ttk.Label(target_row, text="Target name:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(target_row, textvariable=self.output_target_name_var).grid(
            row=0, column=1, sticky="ew"
        )

        desc_frame = ttk.LabelFrame(frm, text="Target description")
        desc_frame.grid(row=3, column=0, sticky="nsew", padx=2, pady=0)
        desc_frame.columnconfigure(0, weight=1)
        desc_frame.rowconfigure(0, weight=1)
        self.output_target_description_text = tk.Text(
            desc_frame, wrap=tk.WORD, undo=True
        )
        desc_scroll = ttk.Scrollbar(
            desc_frame,
            orient=tk.VERTICAL,
            command=self.output_target_description_text.yview,
        )
        self.output_target_description_text.configure(yscrollcommand=desc_scroll.set)
        self.output_target_description_text.grid(
            row=0, column=0, sticky="nsew", padx=(4, 0), pady=4
        )
        desc_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 4), pady=4)

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

        mode_row = ttk.Frame(live_frame)
        mode_row.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Radiobutton(
            mode_row,
            text="DN",
            value="dn",
            variable=self.live_view_mode_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(
            mode_row,
            text="Radiance",
            value="radiance",
            variable=self.live_view_mode_var,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(
            mode_row,
            text="Reflectance",
            value="reflectance",
            variable=self.live_view_mode_var,
        ).pack(side=tk.LEFT)

        ttk.Label(
            live_frame,
            textvariable=self.live_plot_status_var,
            font=self.angles_status_font,
        ).pack(fill=tk.X, padx=4, pady=(0, 2))

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
        drive_btn = ttk.Button(
            sensor_frame,
            text="Drive",
            width=6,
            command=self._drive_sensor_zenith,
        )
        drive_btn.grid(row=0, column=0, padx=(4, 2), pady=4, sticky="w")
        entry = ttk.Entry(sensor_frame, textvariable=self.sensor_zenith_var, width=8)
        entry.grid(row=0, column=1, padx=(2, 4), pady=4, sticky="w")
        self._bind_return_to_drive(entry, drive_btn)
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
        self._reflectance_save_radio = ttk.Radiobutton(
            format_row,
            text="reflectance",
            value="reflectance",
            variable=self.save_format_var,
            command=self._toggle_mode,
        )
        self._reflectance_save_radio.grid(row=0, column=1, padx=(10, 10))
        self._radiance_save_radio = ttk.Radiobutton(
            format_row,
            text="radiance",
            value="radiance",
            variable=self.save_format_var,
            command=self._toggle_mode,
        )
        self._radiance_save_radio.grid(row=0, column=2)
        output_frame.columnconfigure(0, weight=1)
        return output_frame

    def _build_measurement_calibration_frame(self, parent):
        calibration_frame = ttk.LabelFrame(parent, text="Spectrometer Config")
        calibration_button_width = 16
        calibration_frame.columnconfigure(0, weight=0)
        ttk.Label(calibration_frame, text="Averages:").grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 0)
        )
        ttk.Entry(
            calibration_frame,
            textvariable=self.calibration_averages_var,
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Button(
            calibration_frame,
            text="Optimize",
            command=self._optimize,
            width=calibration_button_width,
        ).grid(row=1, column=0, padx=4, pady=4, sticky="w")
        ttk.Label(
            calibration_frame,
            textvariable=self.optimize_status_var,
            font=self.angles_status_font,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))

        ttk.Button(
            calibration_frame,
            text="Dark Current",
            command=self._dark,
            width=calibration_button_width,
        ).grid(row=3, column=0, padx=4, pady=(6, 4), sticky="w")
        ttk.Label(
            calibration_frame,
            textvariable=self.dark_last_measured_var,
            font=self.angles_status_font,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))

        ttk.Button(
            calibration_frame,
            text="White Reference",
            command=self._white,
            width=calibration_button_width,
        ).grid(row=5, column=0, padx=4, pady=(6, 4), sticky="w")
        ttk.Label(
            calibration_frame,
            textvariable=self.white_last_measured_var,
            font=self.angles_status_font,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 4))

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

        settings_row = ttk.Frame(sequence_frame)
        settings_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(settings_row, text="Sequence repeats:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(settings_row, textvariable=self.repeats_var, width=8).grid(
            row=0, column=1, padx=(4, 16), sticky="w"
        )
        ttk.Label(settings_row, text="Spectrum averages:").grid(
            row=0, column=2, sticky="w"
        )
        ttk.Entry(
            settings_row, textvariable=self.spectrum_averages_var, width=8
        ).grid(row=0, column=3, padx=4, sticky="w")
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
            target_entry = ttk.Entry(
                target_controls, textvariable=self.motor_target_vars[role], width=6
            )
            target_entry.grid(row=0, column=2, padx=(0, 2))
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
            self._bind_return_to_drive(target_entry, drive_btn)
            zero_btn = ttk.Button(
                goniometer_frame,
                text="Set Zero",
                command=lambda r=role: self._set_motor_zero(r),
            )
            zero_btn.grid(row=row_idx, column=4, padx=4, pady=2)
            self.motor_drive_buttons[role] = drive_btn
            self.motor_zero_buttons[role] = zero_btn
        light_frame = ttk.LabelFrame(frm, text="Light Zen & Az")
        light_frame.grid(row=1, column=0, sticky="we", padx=4, pady=(0, 4))
        light_row = ttk.Frame(light_frame)
        light_row.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(light_row, text="Light Zenith:").pack(side=tk.LEFT)
        light_zen_entry = ttk.Entry(
            light_row, textvariable=self.light_zenith_var, width=8
        )
        light_zen_entry.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(light_row, text="Light Azimuth:").pack(side=tk.LEFT)
        light_az_entry = ttk.Entry(
            light_row, textvariable=self.light_azimuth_var, width=8
        )
        light_az_entry.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(light_row, text="Set Here", command=self._set_light_here).pack(
            side=tk.LEFT
        )
        light_zen_entry.bind("<FocusOut>", self._on_light_angle_focus_out)
        light_az_entry.bind("<FocusOut>", self._on_light_angle_focus_out)
        polarizer_frame = ttk.LabelFrame(frm, text="Polarizer")
        polarizer_frame.grid(row=2, column=0, sticky="we", padx=4, pady=(0, 4))
        ttk.Button(
            polarizer_frame,
            text="Calibrate Polarizer",
            command=self._calibrate_polarizer,
            state="disabled",
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")

    def _set_busy(self, busy):
        self.after(0, lambda: self.busy_var.set("Busy" if busy else "Idle"))

    def _set_window_status(self, suffix):
        def apply():
            if suffix:
                self.title("{} — {}".format(BASE_WINDOW_TITLE, suffix))
            else:
                self.title(BASE_WINDOW_TITLE)

        self.after(0, apply)

    def _startup_refresh(self):
        self.controller.run_async(
            "Startup initialization",
            self._initialize_on_startup,
            on_error=self._handle_startup_error,
        )

    def _initialize_on_startup(self):
        self.workflow.connect_devices()
        # Match the known-working command-line startup sequence: connect,
        # read VNIR metadata, load cached Oheader.npy, then apply SetOpt.
        # Do not run OPT,7 automatically here; the old workflow only optimizes
        # when the user explicitly asks, and then requires a fresh dark current.
        self.workflow.load_runtime_state()
        self.live_spectrum_service.start()
        if self.state_obj.devices.connected_spectrometer:
            self._spectrometer_status_cache = "Connected"
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
        self.light_zenith_var.set("{:.2f}".format(self.state_obj.light_zenith_deg))
        self.light_azimuth_var.set("{:.2f}".format(self.state_obj.light_azimuth_deg))
        self.output_authors_var.set(self.state_obj.authors or "")
        self.output_target_name_var.set(self.state_obj.target_name or "")
        self.output_target_description_text.delete("1.0", tk.END)
        self.output_target_description_text.insert(
            "1.0", self.state_obj.target_description or ""
        )
        self._update_reflectance_save_controls()
        self._dark_collected_at = self.state_obj.calibration.dark_collected_at
        self._white_collected_at = self.state_obj.calibration.white_collected_at
        if self._dark_collected_at is None:
            self.dark_last_measured_var.set("Not collected yet!")
        else:
            self.dark_last_measured_var.set(
                self._format_collection_status(self._dark_collected_at)
            )
        if self._white_collected_at is None:
            self.white_last_measured_var.set("Not collected yet!")
        else:
            self.white_last_measured_var.set(
                self._format_collection_status(self._white_collected_at)
            )

    def _format_optimize_status(self, header):
        if header is None:
            return "Not optimized yet!"
        try:
            itime = int(header[2])
            gain_1 = int(header[3][0])
            gain_2 = int(header[3][1])
            offset_1 = int(header[4][0])
            offset_2 = int(header[4][1])
        except Exception:
            return "Optimize parameters unavailable"
        try:
            itime_label = ITimeEnum(itime).to_str().replace(" ", "")
        except Exception:
            itime_label = str(itime)
        return "{}, {}, {}, {}, {}".format(
            itime_label, gain_1, gain_2, offset_1, offset_2
        )

    def _format_collection_status(self, collected_at):
        now = datetime.now()
        delta = now - collected_at
        total_seconds = max(0, int(delta.total_seconds()))
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            ago = "{:02d}:{:02d}:{:02d} ago".format(hours, minutes, seconds)
        else:
            ago = "{:02d}:{:02d} ago".format(minutes, seconds)
        return "{} ({})".format(collected_at.strftime("%H:%M:%S"), ago)

    def _refresh_collection_status_labels(self):
        if self._dark_collected_at is not None:
            self.dark_last_measured_var.set(
                self._format_collection_status(self._dark_collected_at)
            )
        if self._white_collected_at is not None:
            self.white_last_measured_var.set(
                self._format_collection_status(self._white_collected_at)
            )

    def _has_dark_calibration(self):
        calibration = self.state_obj.calibration
        return (
            calibration.dark_current is not None and calibration.drift_dark is not None
        )

    def _reset_collection_status_labels(self):
        self._dark_collected_at = None
        self._white_collected_at = None
        self.dark_last_measured_var.set("Not collected yet!")
        self.white_last_measured_var.set("Not collected yet!")

    def _ensure_output_dataset_selected(self):
        self._push_output_metadata_to_state()
        raw = self.outfile_var.get().strip()
        try:
            self.workflow.set_output_dataset_path(raw)
        except PreconditionError as exc:
            messagebox.showerror("Output file required", str(exc))
            return False
        except ValueError as exc:
            messagebox.showerror("Dataset load failed", str(exc))
            return False
        self.outfile_var.set(self.state_obj.outfile)
        self._sync_runtime_state_ui()
        return True

    def _current_spectrum_averages(self):
        try:
            return max(
                1,
                int(
                    self.spectrum_averages_var.get()
                    or str(DEFAULT_SPECTRUM_AVERAGES)
                ),
            )
        except ValueError:
            return DEFAULT_SPECTRUM_AVERAGES

    def _push_acquisition_settings_to_state(self):
        self.state_obj.spectrum_averages = self._current_spectrum_averages()

    def _current_calibration_averages(self):
        try:
            return max(
                1,
                int(
                    self.calibration_averages_var.get()
                    or str(CALIBRATION_SPECTRUM_AVERAGES)
                ),
            )
        except ValueError:
            return CALIBRATION_SPECTRUM_AVERAGES

    def _push_calibration_settings_to_state(self):
        self.state_obj.calibration_spectrum_averages = (
            self._current_calibration_averages()
        )

    def _push_output_metadata_to_state(self):
        self.state_obj.authors = (self.output_authors_var.get() or "").strip()
        self.state_obj.target_name = (self.output_target_name_var.get() or "").strip()
        self.state_obj.target_description = (
            self.output_target_description_text.get("1.0", "end-1c") or ""
        ).strip()

    def _browse_output_file(self):
        raw = self.outfile_var.get().strip()
        if raw:
            current = Path(raw)
            initialdir = (
                str(current.parent) if current.parent.exists() else str(self.workspace)
            )
            initialfile = current.name
        else:
            data_dir = DEFAULT_OUTPUT_DATA_DIR
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                data_dir = self.workspace
            initialdir = str(data_dir) if data_dir.is_dir() else str(self.workspace)
            initialfile = ""
        selected = filedialog.asksaveasfilename(
            title="Select output file",
            initialdir=initialdir,
            initialfile=initialfile,
            defaultextension=".json",
            filetypes=[("JSON datasets", "*.json"), ("All files", "*.*")],
            confirmoverwrite=False,
        )
        if not selected:
            return
        selected_path = Path(selected)
        if selected_path.suffix.lower() != ".json":
            selected_path = selected_path.with_suffix(".json")
        selected_path = selected_path.resolve()
        outfile = str(selected_path)
        exists = selected_path.exists()
        label = "Open dataset" if exists else "New dataset"
        self.outfile_var.set(outfile)

        def run_open_or_create():
            try:
                self._push_output_metadata_to_state()
                self.workflow.new_dataset(outfile)
            except ValueError as exc:
                self.after(
                    0,
                    lambda msg=str(exc): messagebox.showerror(
                        "Dataset load failed", msg
                    ),
                )
            except PreconditionError as exc:
                self.after(
                    0,
                    lambda msg=str(exc): messagebox.showerror(
                        "Output file required", msg
                    ),
                )
            finally:
                self.after(0, self._sync_runtime_state_ui)

        self.controller.run_async(label, run_open_or_create)

    def _browse_angle_file(self):
        selected = filedialog.askopenfilename(
            title="Select angle file",
            initialdir=self.workspace,
            filetypes=[
                ("Sequence files", "*.seq.txt *.seq"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
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

    def _update_reflectance_save_controls(self):
        state = "disabled" if self.state_obj.reflectance_mode_locked else "normal"
        if getattr(self, "_reflectance_save_radio", None) is not None:
            self._reflectance_save_radio.configure(state=state)
        if getattr(self, "_radiance_save_radio", None) is not None:
            self._radiance_save_radio.configure(state=state)

    def _toggle_mode(self):
        if self.state_obj.reflectance_mode_locked:
            self.save_format_var.set(
                "reflectance" if self.state_obj.reflectance_mode else "radiance"
            )
            return
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
            self.after(0, self._reset_collection_status_labels)

        self.controller.run_async("Optimize", run)

    def _dark(self):
        proceed = messagebox.askokcancel(
            "Dark Current",
            "Close shutter",
        )
        if not proceed:
            return
        self._push_calibration_settings_to_state()

        def run():
            self.workflow.collect_dark()
            collected_at = (
                self.state_obj.calibration.dark_collected_at or datetime.now()
            )
            self._dark_collected_at = collected_at
            self.after(
                0,
                lambda: self.dark_last_measured_var.set(
                    self._format_collection_status(collected_at)
                ),
            )
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Dark Current",
                    "Open shutter",
                ),
            )

        self.controller.run_async("Collect dark", run)

    def _white(self):
        if not self._has_dark_calibration():
            messagebox.showerror(
                "White Reference",
                "Dark Current must be measured before White Reference",
            )
            return
        self._push_calibration_settings_to_state()

        def run():
            za = float(self.sensor_zenith_var.get() or "0")
            self.workflow.collect_white(za)
            collected_at = (
                self.state_obj.calibration.white_collected_at or datetime.now()
            )
            self._white_collected_at = collected_at
            self.after(
                0,
                lambda: self.white_last_measured_var.set(
                    self._format_collection_status(collected_at)
                ),
            )

        self.controller.run_async("Collect white", run)

    def _ending_white(self):
        if not self._ensure_output_dataset_selected():
            return
        self._push_calibration_settings_to_state()
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

    def _bind_return_to_drive(self, entry, drive_button):
        def on_return(_event):
            drive_button.invoke()
            return "break"

        entry.bind("<Return>", on_return)
        entry.bind("<KP_Enter>", on_return)

    def _on_light_angle_focus_out(self, event=None):
        raw_z = self.light_zenith_var.get().strip()
        raw_a = self.light_azimuth_var.get().strip()
        try:
            z = float(raw_z) if raw_z else 0.0
            a = float(raw_a) if raw_a else 0.0
        except ValueError:
            messagebox.showerror(
                "Invalid input",
                "Light Zenith and Light Azimuth must be numeric.",
            )
            self.light_zenith_var.set("{:.2f}".format(self.state_obj.light_zenith_deg))
            self.light_azimuth_var.set(
                "{:.2f}".format(self.state_obj.light_azimuth_deg)
            )
            return
        self.state_obj.light_zenith_deg = z
        self.state_obj.light_azimuth_deg = a
        self.light_zenith_var.set("{:.2f}".format(z))
        self.light_azimuth_var.set("{:.2f}".format(a))
        self.workflow.save_runtime_settings()

    def _flush_light_angles_before_shutdown(self):
        raw_z = self.light_zenith_var.get().strip()
        raw_a = self.light_azimuth_var.get().strip()
        try:
            z = float(raw_z) if raw_z else 0.0
            a = float(raw_a) if raw_a else 0.0
        except ValueError:
            return
        self.state_obj.light_zenith_deg = z
        self.state_obj.light_azimuth_deg = a
        self.workflow.save_runtime_settings()

    def _set_light_here(self):
        try:
            zen = self.workflow.get_motor_angle_from_zero("zenith")
            az = self.workflow.get_motor_angle_from_zero("azimuth")
        except Exception as exc:
            messagebox.showerror(
                "Set Here unavailable",
                "Could not read current sensor zenith/azimuth:\n{}".format(exc),
            )
            return
        if zen < 0:
            light_zen = abs(zen)
            light_az = (az + 180.0) % 360.0
        else:
            light_zen = zen
            light_az = az
        self.state_obj.light_zenith_deg = light_zen
        self.state_obj.light_azimuth_deg = light_az
        self.light_zenith_var.set("{:.2f}".format(light_zen))
        self.light_azimuth_var.set("{:.2f}".format(light_az))
        self.workflow.save_runtime_settings()

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
        self.motor_target_vars[role].set("{:.2f}".format(0.0))
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
        if not self._ensure_output_dataset_selected():
            return
        self._push_output_metadata_to_state()
        self._push_acquisition_settings_to_state()
        repeats = int(self.repeats_var.get() or str(DEFAULT_SEQUENCE_REPEATS))
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

        if not self._ensure_output_dataset_selected():
            return
        self._push_output_metadata_to_state()
        self._push_acquisition_settings_to_state()

        angle_row = (sensor_pol, lamp_pol, zenith, azimuth, sample, 0.0, 1.0)
        previous_angles = list(self.state_obj.angles)
        self.log(
            "Manual single-spectrum at current position: "
            "sz={:.2f}, sa00={:.2f}, ze={:.2f}, az={:.2f}, sample={:.2f}".format(
                sensor_pol, lamp_pol, zenith, azimuth, sample
            )
        )
        self.state_obj.angles = [angle_row]

        repeats = int(self.repeats_var.get() or str(DEFAULT_SEQUENCE_REPEATS))
        self.controller.run_measure(
            repeats,
            label="Manual single spectrum",
            on_finally=lambda: setattr(self.state_obj, "angles", previous_angles),
        )

    def _view(self):
        self._push_acquisition_settings_to_state()
        self.controller.run_async("View snapshot", self.workflow.view_snapshot)

    def _plot(self):
        self.controller.run_async("Plot data", self.workflow.plot_current_data)

    def _vnir_info(self):
        self.controller.run_async(
            "VNIR info", lambda: self.log(str(self.workflow.show_vnir_info()))
        )

    def _update_device_status_labels(self):
        try:
            snapshot = self.workflow.get_motor_status_snapshot()
        except Exception:
            snapshot = {"motors": "Unknown", "polarizer": "Unknown"}
        spectrometer_status = self._spectrometer_status_cache
        self.spectrometer_status_var.set(spectrometer_status)
        self.motors_status_var.set(snapshot["motors"])
        self.polarizer_status_var.set(snapshot["polarizer"])
        self.spectrometer_status_label.configure(
            fg=("red" if spectrometer_status.startswith("NOT CONNECTED") else "black")
        )
        self.motors_status_label.configure(
            fg="red" if snapshot["motors"].startswith("NOT CONNECTED") else "black"
        )
        self.polarizer_status_label.configure(fg="black")

    def _refresh_device_status(self):
        if self._shutting_down:
            return
        self._update_device_status_labels()
        self._refresh_collection_status_labels()
        self._update_reflectance_save_controls()
        self._submit_spectrometer_probe()
        self.after(2000, self._refresh_device_status)

    def _submit_spectrometer_probe(self):
        if self._shutting_down or self._spectrometer_probe_in_flight:
            return
        if not self.state_obj.devices.connected_spectrometer:
            # Reflect the cached "not connected" state without attempting I/O;
            # connection is established by the startup task on the GuiController
            # worker, which will refresh the cache when it finishes.
            if self._spectrometer_status_cache != "NOT CONNECTED":
                self._spectrometer_status_cache = "NOT CONNECTED"
                self.after(0, self._update_device_status_labels)
            return
        self._spectrometer_probe_in_flight = True
        try:
            self._status_executor.submit(self._run_spectrometer_probe)
        except RuntimeError:
            # Executor was shut down between the check and submit (e.g. during
            # teardown); leave the cache as-is.
            self._spectrometer_probe_in_flight = False

    def _run_spectrometer_probe(self):
        try:
            status = self.workflow.probe_spectrometer_connected()
        except Exception:
            status = "NOT CONNECTED"
        self.after(0, self._apply_spectrometer_probe_result, status)

    def _apply_spectrometer_probe_result(self, status):
        self._spectrometer_probe_in_flight = False
        if self._shutting_down:
            return
        if status != self._spectrometer_status_cache:
            self._spectrometer_status_cache = status
            self._update_device_status_labels()

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
                mode = self.live_view_mode_var.get()
                header = latest.get("header")
                y_live = None
                y_overlay = None
                ylabel = "DN"
                status = ""
                overlay_label = None
                if mode == "dn":
                    y_live, y_overlay, status = self.workflow.compute_live_dn_pair(
                        spectrum
                    )
                    ylabel = "DN"
                    overlay_label = "Dark current"
                elif mode == "radiance":
                    y_live, y_overlay, status = (
                        self.workflow.compute_live_radiance_pair(header, spectrum)
                    )
                    ylabel = "Radiance-like signal"
                    overlay_label = "White reference"
                elif mode == "reflectance":
                    y_live, status = self.workflow.compute_live_reflectance(
                        header, spectrum
                    )
                    ylabel = "Reflectance factor"
                else:
                    y_live = np.asarray(spectrum)
                    ylabel = "DN"
                    status = "Unknown mode '{}'; showing DN.".format(mode)

                if self._live_bg_line is None:
                    (self._live_bg_line,) = self._live_ax.plot(
                        wl,
                        np.full_like(wl, np.nan, dtype=float),
                        color="black",
                        zorder=1,
                    )
                if self._live_fg_line is None:
                    (self._live_fg_line,) = self._live_ax.plot(
                        wl,
                        np.full_like(wl, np.nan, dtype=float),
                        color="blue",
                        zorder=2,
                    )

                if y_overlay is not None:
                    self._live_bg_line.set_data(wl, y_overlay)
                    self._live_bg_line.set_visible(True)
                    if overlay_label is not None:
                        self._live_bg_line.set_label(overlay_label)
                else:
                    self._live_bg_line.set_data(
                        wl, np.full_like(wl, np.nan, dtype=float)
                    )
                    self._live_bg_line.set_visible(False)

                if y_live is not None:
                    self._live_fg_line.set_data(wl, y_live)
                    self._live_fg_line.set_visible(True)
                    self._live_fg_line.set_label("Live")
                else:
                    self._live_fg_line.set_data(
                        wl, np.full_like(wl, np.nan, dtype=float)
                    )
                    self._live_fg_line.set_visible(False)

                self._live_ax.set_ylabel(ylabel)
                if (
                    self._live_bg_line.get_visible()
                    and self._live_fg_line.get_visible()
                ):
                    self._live_ax.legend(loc="upper right")
                else:
                    legend = self._live_ax.get_legend()
                    if legend is not None:
                        legend.remove()

                self.live_plot_status_var.set(status)
                self._live_ax.relim()
                if mode == "reflectance" and y_live is not None:
                    reflectance = np.asarray(y_live, dtype=float).reshape(-1)
                    if wl is not None and len(wl) == len(reflectance):
                        wl_arr = np.asarray(wl, dtype=float)
                        analysis_mask = (wl_arr >= 500.0) & (wl_arr <= 2000.0)
                    else:
                        # Fallback for expected ASD grid (350..2500 nm, len=2151):
                        # use indices ~150..1650 => ~500..2000 nm.
                        analysis_mask = np.zeros(reflectance.shape[0], dtype=bool)
                        i0 = max(0, 500 - 350)
                        i1 = min(reflectance.shape[0], 2000 - 350 + 1)
                        analysis_mask[i0:i1] = True
                    finite = reflectance[analysis_mask]
                    finite = finite[np.isfinite(finite)]
                    if finite.size > 0:
                        p99 = float(np.percentile(finite, 99))
                        ymax = min(5.0, math.ceil((p99 + 0.1) * 10.0) / 10.0)
                        ymax = max(0.1, ymax)
                        self._live_ax.set_autoscaley_on(False)
                        self._live_ax.set_ylim(-0.05, ymax)
                    else:
                        self._live_ax.set_autoscaley_on(True)
                        self._live_ax.set_ylim(auto=True)
                        self._live_ax.autoscale_view()
                else:
                    self._live_ax.set_autoscaley_on(True)
                    self._live_ax.set_ylim(auto=True)
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
                self._flush_light_angles_before_shutdown()
                self.live_spectrum_service.stop()
                self._shutdown_status_executor()
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
        self._shutdown_status_executor()
        self.quit()
        self.destroy()

    def _shutdown_status_executor(self):
        executor = getattr(self, "_status_executor", None)
        if executor is None:
            return
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=True)
        self._status_executor = None


def main():
    app = GoniocontrolGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
