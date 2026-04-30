#!/usr/bin/env python3
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from goniocontrol_app.gui_controller import GuiController
from goniocontrol_app.services.mock_services import MockLCCService, MockMotorService, MockSpectrometerService
from goniocontrol_app.services.persistence_service import PersistenceService
from goniocontrol_app.state import AppState
from goniocontrol_app.workflow_service import WorkflowService


class GoniocontrolGUI(tk.Tk):
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
        self.repeats_var = tk.StringVar(value="1")
        self.zenith_var = tk.StringVar(value="0")
        self.white_zenith_var = tk.StringVar(value="0")

        self._build_ui()
        self.after(200, self._startup_refresh)

    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        top = ttk.Frame(root)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Status:").pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self.busy_var).pack(side=tk.LEFT, padx=6)

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        status = ttk.Frame(notebook)
        setup = ttk.Frame(notebook)
        calibr = ttk.Frame(notebook)
        acquisition = ttk.Frame(notebook)
        plotting = ttk.Frame(notebook)
        notebook.add(status, text="System Status")
        notebook.add(setup, text="Measurement Setup")
        notebook.add(calibr, text="Calibration")
        notebook.add(acquisition, text="Acquisition")
        notebook.add(plotting, text="Plot/View")

        self.log_text = tk.Text(root, height=12, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=False, pady=(8, 0))

        self._build_status_panel(status)
        self._build_setup_panel(setup)
        self._build_calibration_panel(calibr)
        self._build_acquisition_panel(acquisition)
        self._build_plotting_panel(plotting)
        self.log(self.log_boot)

    def _build_status_panel(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(row, text="Connect Devices", command=self._connect_devices).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Load Runtime State", command=self._load_runtime_state).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Preflight", command=self._run_preflight).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Shutdown", command=self._shutdown).pack(side=tk.LEFT, padx=4)

    def _build_setup_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        ttk.Label(frm, text="Output file:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.outfile_var, width=60).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(frm, text="Browse", command=self._browse_output_file).grid(row=0, column=2, padx=4)

        ttk.Label(frm, text="Angles file:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.angle_var, width=60, state="readonly").grid(row=1, column=1, sticky="we", padx=6)
        ttk.Button(frm, text="Browse", command=self._browse_angle_file).grid(row=1, column=2, padx=4)
        ttk.Button(frm, text="Apply Angles", command=self._apply_angles).grid(row=2, column=2, padx=4)

        ttk.Checkbutton(
            frm,
            text="Reflectance mode (uncheck for radiance)",
            variable=self.reflectance_var,
            command=self._toggle_mode,
        ).grid(row=2, column=1, sticky="w")
        frm.columnconfigure(1, weight=1)

    def _build_calibration_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Label(frm, text="White/Optimize Zenith:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.white_zenith_var, width=20).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(frm, text="Restore Spectrometer", command=self._restore).grid(row=1, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="Optimize", command=self._optimize).grid(row=1, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="Dark", command=self._dark).grid(row=1, column=2, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="White", command=self._white).grid(row=2, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="Ending White", command=self._ending_white).grid(row=2, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(frm, text="Calibrate Polarizer", command=self._calibrate_polarizer).grid(row=2, column=2, padx=4, pady=4, sticky="w")

    def _build_acquisition_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Label(frm, text="Zenith angle (Go):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.zenith_var, width=20).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(frm, text="Go Zenith", command=self._go_zenith).grid(row=0, column=2, padx=4, pady=4)
        ttk.Button(frm, text="Zero All", command=self._zero).grid(row=0, column=3, padx=4, pady=4)

        ttk.Label(frm, text="Measure repeats:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.repeats_var, width=20).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Button(frm, text="Start Measure", command=self._measure).grid(row=1, column=2, padx=4, pady=4)
        ttk.Button(frm, text="Abort Measure", command=self.controller.cancel).grid(row=1, column=3, padx=4, pady=4)

    def _build_plotting_panel(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        ttk.Button(frm, text="View Snapshot", command=self._view).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(frm, text="Plot Current Data", command=self._plot).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(frm, text="VNIR Info", command=self._vnir_info).pack(side=tk.LEFT, padx=4, pady=4)

    def _set_busy(self, busy: bool):
        self.after(0, lambda: self.busy_var.set("Busy" if busy else "Idle"))

    def _startup_refresh(self):
        self._run_preflight()

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

    def _apply_angles(self):
        path = Path(self.angle_var.get())

        def run():
            self.state_obj.angles_file = path
            self.state_obj.angles = self.workflow.persistence.read_angles(path)
            self.log(f"Loaded {len(self.state_obj.angles)} angle rows from {path}")

        self.controller.run_async("Load angles", run)

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

    def _go_zenith(self):
        za = float(self.zenith_var.get() or "0")
        self.controller.run_async("Go zenith", lambda: self.workflow.go_zenith(za))

    def _zero(self):
        self.controller.run_async("Zero all", self.workflow.zero_all)

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

