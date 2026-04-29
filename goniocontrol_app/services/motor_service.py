from __future__ import annotations

from ctypes import POINTER, byref, c_int, c_uint, cast
from dataclasses import dataclass
from typing import Dict, Optional

from pyximc import (
    calibration_t,
    engine_settings_t,
    get_position_calb_t,
    get_position_t,
    lib,
    move_settings_t,
)

from goniocontrol_app.errors import RecoverableHardwareError
from goniocontrol_app.state import MotorIdentity, PositionState


@dataclass
class MotorHandle:
    identity: MotorIdentity
    calibration: calibration_t


class MotorService:
    SERIALS = {
        "sensor_polarizer": 13536,
        "lamp_polarizer": 13635,
        "sample": 12224,
        "zenith": 13217,
        "azimuth": 13225,
    }
    SCAN_NAMES = [f"xi-com:///dev/ttyACM{i}" for i in range(11)]

    def __init__(self):
        self.handles: Dict[str, MotorHandle] = {}

    def discover(self) -> Dict[str, MotorIdentity]:
        discovered: Dict[str, MotorIdentity] = {}
        for name in self.SCAN_NAMES:
            encoded = name.encode()
            device_id = lib.open_device(encoded)
            serial = c_uint()
            lib.get_serial_number(device_id, byref(serial))
            role = self._role_from_serial(serial.value)
            if role is None:
                lib.close_device(byref(cast(device_id, POINTER(c_int))))
                continue

            calibration = calibration_t()
            engine = engine_settings_t()
            lib.get_engine_settings(device_id, byref(engine))
            calibration.MicrostepMode = engine.MicrostepMode
            calibration.A = 1.0 / (80.0 if "polarizer" in role else 100.0)
            self._configure_motion(role, device_id)

            identity = MotorIdentity(serial_number=serial.value, device_name=name, device_id=device_id)
            discovered[role] = identity
            self.handles[role] = MotorHandle(identity=identity, calibration=calibration)
        return discovered

    def _configure_motion(self, role: str, device_id) -> None:
        if role not in {"sample", "zenith", "azimuth"}:
            return
        move = move_settings_t()
        lib.get_move_settings(device_id, byref(move))
        move.Decel = move.Accel
        if role == "sample":
            move.Speed = 1000
        lib.set_move_settings(device_id, byref(move))

    def _role_from_serial(self, serial: int) -> Optional[str]:
        for role, expected in self.SERIALS.items():
            if serial == expected:
                return role
        return None

    def get_position(self, role: str) -> PositionState:
        handle = self.handles[role]
        p_steps = get_position_t()
        p_cal = get_position_calb_t()
        lib.get_position(handle.identity.device_id, byref(p_steps))
        lib.get_position_calb(handle.identity.device_id, byref(p_cal), byref(handle.calibration))
        return PositionState(
            step_position=p_steps.Position,
            microstep_position=p_steps.uPosition,
            calibrated_position=p_cal.Position,
            encoder_position=p_cal.EncPosition,
        )

    def move_deg_from_zero(self, role: str, deg: float, zero: PositionState) -> None:
        handle = self.handles[role]
        target = int(deg * 100 + zero.step_position)
        lib.command_move(handle.identity.device_id, target, zero.microstep_position)

    def move_to_zero(self, role: str, zero: PositionState) -> None:
        handle = self.handles[role]
        lib.command_move(handle.identity.device_id, int(zero.step_position), zero.microstep_position)

    def wait(self, role: str, timeout_ms: int = 10) -> None:
        handle = self.handles[role]
        result = lib.command_wait_for_stop(handle.identity.device_id, timeout_ms)
        if result != 0:
            raise RecoverableHardwareError(f"Motor {role} stop wait returned {result}")

    def close_all(self) -> None:
        for handle in self.handles.values():
            lib.close_device(byref(cast(handle.identity.device_id, POINTER(c_int))))

