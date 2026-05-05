import socket
from typing import Optional, Tuple

from ASDlib import Optimize, ReadASD, ReadASD1, Restore, SetOpt, VNIRinfo


class SpectrometerService:
    def __init__(self, host= "169.254.1.11", port= 8080):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.connect((self.host, self.port))
        return self.socket.recv(128)

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def _s(self):
        if self.socket is None:
            raise RuntimeError("Spectrometer is not connected.")
        return self.socket

    def restore(self):
        Restore(self._s())

    def optimize(self):
        return Optimize(self._s())

    def set_opt(self, itime, gain, offset):
        SetOpt(self._s(), itime, gain, offset)

    def read_single(self):
        return ReadASD(self._s())

    def read_average(self, repeats):
        return ReadASD1(self._s(), repeats)

    def vnir_info(self):
        return VNIRinfo(self._s())

