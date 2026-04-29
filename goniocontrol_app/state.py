from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


AngleRow = Tuple[float, float, float, float, float, float, float]


@dataclass
class PositionState:
    step_position: int = 0
    microstep_position: int = 0
    calibrated_position: float = 0.0
    encoder_position: float = 0.0


@dataclass
class MotorIdentity:
    serial_number: int
    device_name: str
    device_id: Any


@dataclass
class CalibrationState:
    dark_current: Optional[np.ndarray] = None
    drift_dark: Optional[float] = None
    dark_remainder: Optional[np.ndarray] = None
    white: Optional[np.ndarray] = None
    aa: Optional[np.ndarray] = None
    ending_white: Optional[np.ndarray] = None
    wr_zenith: Optional[float] = None
    wr_end_zenith: Optional[float] = None
    optimizer_header: Optional[np.ndarray] = None


@dataclass
class DeviceState:
    npols: int = 1
    sample_rotator_present: bool = False
    motors: Dict[str, MotorIdentity] = field(default_factory=dict)
    positions_zero: Dict[str, PositionState] = field(default_factory=dict)
    positions_current: Dict[str, PositionState] = field(default_factory=dict)
    connected_spectrometer: bool = False
    connected_lcc: bool = False


@dataclass
class AppState:
    workspace: Path
    outfile: str = "Test00"
    reflectance_mode: bool = True
    angles_file: Path = field(default_factory=lambda: Path("Angles.txt"))
    angles: List[AngleRow] = field(default_factory=list)
    data: List[Any] = field(default_factory=list)
    calibration: CalibrationState = field(default_factory=CalibrationState)
    devices: DeviceState = field(default_factory=DeviceState)

