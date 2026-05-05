# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


AngleRow = Tuple[float, float, float, float, float, float, float]


@dataclass
class PositionState:
    step_position = 0
    microstep_position = 0
    calibrated_position = 0.0
    encoder_position = 0.0


@dataclass
class MotorIdentity:
    serial_number: int
    device_name: str
    device_id: Any


@dataclass
class CalibrationState:
    dark_current = None
    drift_dark = None
    dark_remainder = None
    white = None
    aa = None
    ending_white = None
    wr_zenith = None
    wr_end_zenith = None
    optimizer_header = None


@dataclass
class DeviceState:
    npols = 1
    sample_rotator_present = False
    motors = field(default_factory=dict)
    positions_zero = field(default_factory=dict)
    positions_current = field(default_factory=dict)
    connected_spectrometer = False
    connected_lcc = False


@dataclass
class AppState:
    workspace: Path
    outfile = "Test00"
    reflectance_mode = True
    angles_file = field(default_factory=lambda: Path("Angles.txt"))
    angles = field(default_factory=list)
    data = field(default_factory=list)
    runtime_notice = None
    calibration = field(default_factory=CalibrationState)
    devices = field(default_factory=DeviceState)

