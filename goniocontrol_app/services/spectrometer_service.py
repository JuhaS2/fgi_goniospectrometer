import socket
import threading
from typing import Optional

from ASDlib import Optimize, ReadASD1, Restore, SetOpt, VNIRinfo


class SpectrometerService:
    """Thin wrapper around the ASD TCP socket.

    All public methods that touch ``self.socket`` are serialized through
    ``self._lock``. The ASD speaks a single byte stream; concurrent senders
    or receivers would interleave commands and corrupt response framing.
    A reentrant lock lets a single thread compose higher-level operations
    (e.g. SetOpt followed by ReadASD1) without self-deadlock.
    """

    def __init__(
        self,
        host: str = "169.254.1.11",
        port: int = 8080,
        default_timeout_s: float = 30.0,
    ):
        self.host = host
        self.port = port
        self.default_timeout_s = default_timeout_s
        self.socket: Optional[socket.socket] = None
        self._lock = threading.RLock()

    def connect(self):
        with self._lock:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect((self.host, self.port))
            if self.default_timeout_s is not None:
                sock.settimeout(self.default_timeout_s)
            self.socket = sock
            return sock.recv(128)

    def close(self):
        sock = self.socket
        if sock is None:
            return
        # Try to wait briefly so we don't tear down a live transaction; if a
        # peer thread is stuck in recv, fall through and force-close anyway.
        acquired = self._lock.acquire(timeout=2.0)
        try:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            finally:
                self.socket = None
        finally:
            if acquired:
                self._lock.release()

    def _s(self):
        if self.socket is None:
            raise RuntimeError("Spectrometer is not connected.")
        return self.socket

    def restore(self):
        with self._lock:
            Restore(self._s())

    def optimize(self):
        with self._lock:
            return Optimize(self._s())

    def set_opt(self, itime, gain, offset):
        with self._lock:
            SetOpt(self._s(), itime, gain, offset)

    def read_single(self):
        # Use the canonical "A,1,1" form via ReadASD1 instead of the bare
        # ``b"A"`` that ASDlib.ReadASD sends. The ASD firmware does not respond
        # to the bare command in our setup; the result is a recv timeout
        # followed by a broken pipe on the next send.
        with self._lock:
            return ReadASD1(self._s(), 1)

    def read_average(self, repeats):
        with self._lock:
            return ReadASD1(self._s(), repeats)

    def vnir_info(self):
        with self._lock:
            return VNIRinfo(self._s())
