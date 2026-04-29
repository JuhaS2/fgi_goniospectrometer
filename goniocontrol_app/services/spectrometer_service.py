from __future__ import annotations

import socket
from typing import Optional, Tuple

from ASDlib import Optimize, ReadASD, ReadASD1, Restore, SetOpt, VNIRinfo


class SpectrometerService:
    def __init__(self, host: str = "169.254.1.11", port: int = 8080):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None

    def connect(self) -> bytes:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.connect((self.host, self.port))
        return self.socket.recv(128)

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def _s(self) -> socket.socket:
        if self.socket is None:
            raise RuntimeError("Spectrometer is not connected.")
        return self.socket

    def restore(self) -> None:
        Restore(self._s())

    def optimize(self):
        return Optimize(self._s())

    def set_opt(self, itime, gain, offset) -> None:
        SetOpt(self._s(), itime, gain, offset)

    def read_single(self):
        return ReadASD(self._s())

    def read_average(self, repeats: int):
        return ReadASD1(self._s(), repeats)

    def vnir_info(self) -> Tuple[float, float, float]:
        return VNIRinfo(self._s())

