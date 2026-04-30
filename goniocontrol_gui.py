#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
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
        self.reflectance_var = tk.BooleanVar(value=True)
        default_outfile = str((self.workspace / "Test00.pickle").resolve())
        self.outfile_var = tk.StringVar(value=default_outfile)
        self.state_obj.outfile = default_outfile
        self.angle_var = tk.StringVar(value=str(self.workspace / "Angles.txt"))
        self.angles_status_var = tk.StringVar(value="Sequence with 0 positions")
        self.repeats_var = tk.StringVar(value="1")
        self.white_zenith_var = tk.StringVar(value="0")
        self.motor_labels = dict(self.MOTOR_ROLES)
        self.motor_current_vars = {role: tk.StringVar(value="N/A") for role, _ in self.MOTOR_ROLES}
        self.motor_target_vars = {role: tk.StringVar(value="0.0") for role, _ in self.MOTOR_ROLES}
        self.motor_drive_buttons = {}
        self.motor_zero_buttons = {}

        self._build_ui()
        self.after(200, self._startup_refresh)
        self.after(500, self._refresh_motor_angles)

    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        top = ttk.Frame(root)
        top.pack(fill=tk.X)

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        status = ttk.Frame(notebook)
        motors = ttk.Frame(notebook)
        setup = ttk.Frame(notebook)
        calibr = ttk.Frame(notebook)
        plotting = ttk.Frame(notebook)
        notebook.add(status, text="System Status")
        notebook.add(motors, text="Motors")
        notebook.add(setup, text="Measurement")
        notebook.add(calibr, text="Calibration")
        notebook.add(plotting, text="Plot/View")

        self.log_text = tk.Text(root, height=12, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=False, pady=(8, 0))

        self._build_status_panel(status)
        self._build_setup_panel(setup)
        self._build_calibration_panel(calibr)
        self._build_motors_panel(motors)
        self._build_plotting_panel(plotting)
        self.log(self.log_boot)

    def _build_status_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        button_width = 22

        status_row = ttk.Frame(frm)
        status_row.pack(fill=tk.X, pady=2)
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self.busy_var).pack(side=tk.LEFT, padx=6)

        ttk.Button(frm, text="Connect Devices", command=self._connect_devices, width=button_width).pack(anchor="w", padx=4, pady=2)
        ttk.Button(frm, text="Restore Spectrometer", command=self._restore, width=button_width).pack(anchor="w", padx=4, pady=2)
        ttk.Button(frm, text="Load Runtime State", command=self._load_runtime_state, width=button_width).pack(anchor="w", padx=4, pady=2)
        ttk.Button(frm, text="Preflight", command=self._run_preflight, width=button_width).pack(anchor="w", padx=4, pady=2)
        ttk.Button(frm, text="Shutdown", command=self._shutdown, width=button_width).pack(anchor="w", padx=4, pady=2)

    def _build_setup_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        italic_font = tkfont.nametofont("TkDefaultFont").copy()
        italic_font.configure(slant="italic")
        self.angles_status_font = italic_font

        output_frame = ttk.LabelFrame(frm, text="Output file")
        output_frame.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 10))
        ttk.Entry(output_frame, textvariable=self.outfile_var, width=60).grid(row=0, column=0, sticky="we", padx=6, pady=4)
        ttk.Button(output_frame, text="Browse", command=self._browse_output_file).grid(row=0, column=1, padx=4, pady=4)
        ttk.Checkbutton(
            output_frame,
            text="Reflectance mode (uncheck for radiance)",
            variable=self.reflectance_var,
            command=self._toggle_mode,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))
        output_frame.columnconfigure(0, weight=1)

        sequence_frame = ttk.LabelFrame(frm, text="Measurement Sequence")
        sequence_frame.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=2, pady=(0, 0))

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
        button_width = 16
        ttk.Button(
            button_row, text="Start Measure", command=self._measure, style="TallMeasure.TButton", width=button_width
        ).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(
            button_row,
            text="Abort Measure",
            command=self.controller.cancel,
            style="TallMeasure.TButton",
            width=button_width,
        ).grid(row=0, column=1)
        frm.columnconfigure(1, weight=1)
        sequence_frame.columnconfigure(1, weight=1)

    def _build_calibration_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Label(frm, text="Zen angle during WhiteReference/Optimize:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.white_zenith_var, width=20).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(frm, text="Optimize", command=self._optimize).grid(row=1, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="Dark Current", command=self._dark).grid(row=1, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="White Reference (Start)", command=self._white).grid(row=2, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="White Reference (End)", command=self._ending_white).grid(row=2, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="Calibrate Polarizer", command=self._calibrate_polarizer).grid(row=2, column=2, padx=4, pady=4, sticky="w")

    def _build_motors_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Label(frm, text="Motor").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, text="Current angle").grid(row=0, column=1, sticky="w")
        ttk.Label(frm, text="Target angle").grid(row=0, column=2, sticky="w")
        for row_idx, (role, label) in enumerate(self.MOTOR_ROLES, start=1):
            ttk.Label(frm, text=f"{label}:").grid(row=row_idx, column=0, sticky="w")
            ttk.Entry(frm, textvariable=self.motor_current_vars[role], width=6, state="readonly").grid(
                row=row_idx, column=1, sticky="w", padx=4
            )
            target_controls = ttk.Frame(frm)
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
            drive_btn = ttk.Button(frm, text="Drive", command=lambda r=role: self._drive_motor(r))
            drive_btn.grid(row=row_idx, column=3, padx=4, pady=2)
            zero_btn = ttk.Button(frm, text="Set Zero", command=lambda r=role: self._set_motor_zero(r))
            zero_btn.grid(row=row_idx, column=4, padx=4, pady=2)
            self.motor_drive_buttons[role] = drive_btn
            self.motor_zero_buttons[role] = zero_btn

    def _build_plotting_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Button(frm, text="View Snapshot", command=self._view).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(frm, text="Plot Current Data", command=self._plot).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(frm, text="VNIR Info", command=self._vnir_info).pack(side=tk.LEFT, padx=4, pady=4)

    def _set_busy(self, busy: bool):
        self.after(0, lambda: self.busy_var.set("Busy" if busy else "Idle"))

    def _startup_refresh(self):
        self._apply_angles()
        self._run_preflight()

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

    def log(self, msg: str):
        def append():
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)

        self.after(0, append)

    def _run_preflight(self):
        self.state_obj.angles_file = Path(self.angle_var.get())
        result = self.workflow.startup_preflight()
        self.log(f"Preflight: {result}")

    def _connect_devices(self):
        self.controller.run_async("Connect devices", self.workflow.connect_devices)

    def _load_runtime_state(self):
        def run():
            self.workflow.load_runtime_state()
            self.after(0, lambda: self.outfile_var.set(self.state_obj.outfile))

        self.controller.run_async("Load runtime state", run)

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
            self.after(0, lambda: self.angles_status_var.set(f"Sequence with {loaded_positions} positions"))
            self.log(f"Loaded {len(self.state_obj.angles)} angle rows from {path}")

        self.controller.run_async("Load angles", run)

    def _show_angle_file(self):
        path = Path(self.angle_var.get())
        if not path.exists():
            messagebox.showerror("Angles file missing", f"Angles file does not exist:\n{path}")
            return
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Open file failed", f"Could not open angles file:\n{exc}")

    def _toggle_mode(self):
        # Keep both GUI and backend mode aligned.
        desired = self.reflectance_var.get()
        if self.state_obj.reflectance_mode != desired:
            self.workflow.toggle_mode()
        self.log(f"Mode => {'Reflectance' if self.state_obj.reflectance_mode else 'Radiance'}")

    def _restore(self):
        self.controller.run_async("Restore spectrometer", self.workflow.restore_spectrometer)

    def _optimize(self):
        za = float(self.white_zenith_var.get() or "0")
        self.controller.run_async("Optimize", lambda: self.workflow.optimize(za, progress=self.log))

    def _dark(self):
        self.controller.run_async("Collect dark", self.workflow.collect_dark)

    def _white(self):
        za = float(self.white_zenith_var.get() or "0")
        self.controller.run_async("Collect white", lambda: self.workflow.collect_white(za))

    def _ending_white(self):
        za = float(self.white_zenith_var.get() or "0")
        self.controller.run_async("Collect ending white", lambda: self.workflow.collect_ending_white(za))

    def _calibrate_polarizer(self):
        za = float(self.white_zenith_var.get() or "0")
        self.controller.run_async("Calibrate polarizer", lambda: self.workflow.calibrate_polarizer(za, progress=self.log))

    def _format_angle(self, angle: float) -> str:
        return f"{angle:+.2f}°"

    def _nudge_target(self, role: str, delta: float):
        raw = self.motor_target_vars[role].get().strip()
        try:
            current = float(raw) if raw else 0.0
        except ValueError:
            current = 0.0
        self.motor_target_vars[role].set(f"{current + delta:.2f}")

    def _confirm_out_of_range(self, role: str, value: float) -> bool:
        minimum, maximum = self.MOTOR_LIMITS[role]
        if minimum <= value <= maximum:
            return True
        return messagebox.askyesno(
            "Target angle outside nominal range",
            (
                f"{self.motor_labels[role]} target {value:.2f}° is outside nominal range "
                f"[{minimum:.2f}, {maximum:.2f}]°. Continue?"
            ),
        )

    def _drive_motor(self, role: str):
        try:
            target = float(self.motor_target_vars[role].get() or "0")
        except ValueError:
            messagebox.showerror("Invalid input", f"Enter a numeric target angle for {self.motor_labels[role]}.")
            return
        if not self._confirm_out_of_range(role, target):
            return
        motor_name = self.motor_labels[role]
        self.controller.run_async(
            f"Drive {motor_name} to {target:.2f} deg",
            lambda: self.workflow.drive_motor_to_angle(role, target),
        )

    def _set_motor_zero(self, role: str):
        motor_name = self.motor_labels[role]
        self.controller.run_async(f"Set zero for {motor_name}", lambda: self.workflow.set_zero_at_current_position(role))

    def _measure(self):
        repeats = int(self.repeats_var.get() or "1")
        self.controller.run_measure(repeats)

    def _view(self):
        self.controller.run_async("View snapshot", self.workflow.view_snapshot)

    def _plot(self):
        self.controller.run_async("Plot data", self.workflow.plot_current_data)

    def _vnir_info(self):
        self.controller.run_async("VNIR info", lambda: self.log(str(self.workflow.show_vnir_info())))

    def _shutdown(self):
        def run():
            self.workflow.shutdown()
            self.after(0, self.destroy)

        if messagebox.askyesno("Exit", "Shutdown devices and exit?"):
            self.controller.run_async("Shutdown", run)


def main():
    app = GoniocontrolGUI()
    app.mainloop()


if __name__ == "__main__":
    main()

