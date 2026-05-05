from pathlib import Path
from typing import Dict

import numpy as np

from goniocontrol_app.state import MotorIdentity, PositionState

Nwl = 2151


class MockSpectrometerService:
    def __init__(self, host= "", port= 0):
        self.socket = object()
        self._itime = 1

    def connect(self):
        return b"MOCK ASD"

    def close(self):
        return None

    def restore(self):
        return None

    def optimize(self):
        return (100, 0, self._itime, [1, 1], [0, 0])

    def set_opt(self, itime, gain, offset):
        self._itime = int(itime)

    def read_single(self):
        header = [0] * 64
        header[22] = 0
        spectrum = np.linspace(1000, 1500, Nwl)
        return header, spectrum

    def read_average(self, repeats):
        return self.read_single()

    def vnir_info(self):
        return 350, 1000, 1.0


class MockMotorService:
    def __init__(self):
        self.handles = {}
        self._positions = {k: PositionState() for k in ["zenith", "azimuth", "sample", "sensor_polarizer", "lamp_polarizer"]}

    def discover(self):
        roles = {}
        for idx, role in enumerate(self._positions):
            roles[role] = MotorIdentity(serial_number=1000 + idx, device_name="mock_{}".format(role), device_id=idx)
            self.handles[role] = role
        return roles

    def get_position(self, role):
        return self._positions[role]

    def move_deg_from_zero(self, role, deg, zero):
        self._positions[role] = PositionState(step_position=int(deg * 100), microstep_position=0, calibrated_position=deg, encoder_position=deg)

    def move_to_zero(self, role, zero):
        self._positions[role] = zero

    def wait(self, role, timeout_ms= 10):
        return None

    def close_all(self):
        return None


class MockLCCService:
    def __init__(self):
        self.enabled = True
        self.retardances = [206, 103, 0]

    def set_retardance(self, value):
        return None

    def drain(self):
        return None

