import socket
import threading
import time
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

    def _trace(self, op: str, msg: str = ""):
        thread = threading.current_thread().name
        suffix = (" " + msg) if msg else ""
        print("DEBUG: SpectrometerService[{}] {}{}".format(thread, op, suffix))

    def _locked(self, op: str):
        thread = threading.current_thread().name
        t0 = time.time()
        self._trace(op, "wait-lock")
        self._lock.acquire()
        wait_s = time.time() - t0
        if wait_s > 0.001:
            print("DEBUG: SpectrometerService[{}] {} got-lock wait={:.3f}s".format(
                thread, op, wait_s))
        return _LockHandle(self._lock, op, thread)

    def connect(self):
        with self._locked("connect"):
            self._trace("connect", "host={} port={}".format(self.host, self.port))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect((self.host, self.port))
            if self.default_timeout_s is not None:
                sock.settimeout(self.default_timeout_s)
            self.socket = sock
            greeting = sock.recv(128)
            self._trace("connect", "greeting len={} bytes={!r}".format(
                len(greeting), greeting[:64]))
            return greeting

    def close(self):
        sock = self.socket
        if sock is None:
            self._trace("close", "no-socket")
            return
        self._trace("close", "begin")
        # Try to wait briefly so we don't tear down a live transaction; if a
        # peer thread is stuck in recv, fall through and force-close anyway.
        acquired = self._lock.acquire(timeout=2.0)
        try:
            try:
                sock.shutdown(socket.SHUT_RDWR)
                self._trace("close", "shutdown ok")
            except OSError as exc:
                self._trace("close", "shutdown skipped {}: {}".format(
                    type(exc).__name__, exc))
            try:
                sock.close()
                self._trace("close", "closed acquired_lock={}".format(acquired))
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
        with self._locked("restore"):
            try:
                Restore(self._s())
            except Exception as exc:
                self._trace("restore", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise

    def optimize(self):
        with self._locked("optimize"):
            t0 = time.time()
            try:
                result = Optimize(self._s())
            except Exception as exc:
                self._trace("optimize", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise
            self._trace("optimize", "ok header={} elapsed={:.3f}s".format(
                result[0], time.time() - t0))
            return result

    def set_opt(self, itime, gain, offset):
        with self._locked("set_opt"):
            try:
                SetOpt(self._s(), itime, gain, offset)
            except Exception as exc:
                self._trace("set_opt", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise

    def read_single(self):
        # Use the canonical "A,1,1" form via ReadASD1 instead of the bare
        # ``b"A"`` that ASDlib.ReadASD sends. The ASD firmware does not respond
        # to the bare command in our setup; the result is a recv timeout
        # followed by a broken pipe on the next send.
        with self._locked("read_single"):
            t0 = time.time()
            try:
                result = ReadASD1(self._s(), 1)
            except Exception as exc:
                self._trace("read_single", "FAILED {}: {} elapsed={:.3f}s".format(
                    type(exc).__name__, exc, time.time() - t0))
                raise
            self._trace("read_single", "ok header[0]={} elapsed={:.3f}s".format(
                result[0][0], time.time() - t0))
            return result

    def read_average(self, repeats):
        with self._locked("read_average({})".format(repeats)):
            t0 = time.time()
            try:
                result = ReadASD1(self._s(), repeats)
            except Exception as exc:
                self._trace("read_average", "FAILED repeats={} {}: {} elapsed={:.3f}s".format(
                    repeats, type(exc).__name__, exc, time.time() - t0))
                raise
            self._trace("read_average", "ok repeats={} header[0]={} elapsed={:.3f}s".format(
                repeats, result[0][0], time.time() - t0))
            return result

    def vnir_info(self):
        with self._locked("vnir_info"):
            t0 = time.time()
            try:
                result = VNIRinfo(self._s())
            except Exception as exc:
                self._trace("vnir_info", "FAILED {}: {} elapsed={:.3f}s".format(
                    type(exc).__name__, exc, time.time() - t0))
                raise
            self._trace("vnir_info", "ok elapsed={:.3f}s".format(time.time() - t0))
            return result


class _LockHandle:
    """Minimal context manager wrapping the held lock so we can still trace release."""

    def __init__(self, lock: threading.RLock, op: str, thread: str):
        self._lock = lock
        self._op = op
        self._thread = thread

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._lock.release()
        except Exception:
            pass
        if exc_type is None:
            print("DEBUG: SpectrometerService[{}] {} release".format(
                self._thread, self._op))
        else:
            print("DEBUG: SpectrometerService[{}] {} release-after-error {}: {}".format(
                self._thread, self._op, exc_type.__name__, exc))
        return False
