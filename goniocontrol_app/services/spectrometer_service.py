import socket
import threading
import time
from typing import Optional

import numpy as np

from ASDlib import Optimize, ReadASD, ReadASD1, Restore, SetOpt, VNIRinfo


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
        # Set when a hard transport error (broken pipe / connection reset)
        # invalidates ``self.socket``. Read paths check this flag before they
        # touch the socket and trigger a reconnect instead of issuing a send
        # that would otherwise raise BrokenPipeError forever.
        self._needs_reconnect = False

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
            self._needs_reconnect = False
            greeting = sock.recv(128)
            self._trace("connect", "greeting len={} bytes={!r}".format(
                len(greeting), greeting[:64]))
            return greeting

    def reconnect(self):
        """Tear down the existing socket (if any) and dial a fresh one.

        Used by callers that have observed a transport-level failure and
        want subsequent operations to succeed once the spectrometer is
        responsive again. Returns the greeting bytes from the new socket.
        Caller is responsible for retrying any in-flight workflow.
        """
        with self._locked("reconnect"):
            old = self.socket
            self.socket = None
            self._needs_reconnect = False
            if old is not None:
                try:
                    old.shutdown(socket.SHUT_RDWR)
                except OSError as exc:
                    self._trace("reconnect", "shutdown skipped {}: {}".format(
                        type(exc).__name__, exc))
                try:
                    old.close()
                except OSError as exc:
                    self._trace("reconnect", "close skipped {}: {}".format(
                        type(exc).__name__, exc))
            self._trace("reconnect", "dialing host={} port={}".format(
                self.host, self.port))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect((self.host, self.port))
            if self.default_timeout_s is not None:
                sock.settimeout(self.default_timeout_s)
            self.socket = sock
            greeting = sock.recv(128)
            self._trace("reconnect", "greeting len={} bytes={!r}".format(
                len(greeting), greeting[:64]))
            return greeting

    def needs_reconnect(self) -> bool:
        return self._needs_reconnect or self.socket is None

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
        if self.socket is None or self._needs_reconnect:
            raise ConnectionError(
                "Spectrometer link is down (needs reconnect={}).".format(
                    self._needs_reconnect
                )
            )
        return self.socket

    # Errors that indicate the TCP connection is unusable and a fresh
    # ``reconnect()`` is required before the next command can succeed.
    # ``socket.timeout`` is included because, empirically, the ASD's TCP
    # server resets the connection after a long recv stall, which means any
    # operation after a recv timeout will fail with BrokenPipeError until
    # we reconnect. Treating the timeout itself as fatal-to-the-link lets
    # the next attempt rebuild the socket immediately instead of wasting
    # 30 more seconds on a doomed retry.
    _TRANSPORT_DEAD_EXCEPTIONS = (
        BrokenPipeError,
        ConnectionResetError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        ConnectionError,
        socket.timeout,
    )

    def _mark_dead_if_transport_error(self, exc: BaseException):
        if isinstance(exc, self._TRANSPORT_DEAD_EXCEPTIONS):
            if not self._needs_reconnect:
                self._trace(
                    "transport",
                    "marking link dead, reconnect required ({}: {})".format(
                        type(exc).__name__, exc
                    ),
                )
            self._needs_reconnect = True

    def restore(self):
        with self._locked("restore"):
            try:
                Restore(self._s())
            except Exception as exc:
                self._mark_dead_if_transport_error(exc)
                self._trace("restore", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise

    def optimize(self):
        with self._locked("optimize"):
            t0 = time.time()
            try:
                result = Optimize(self._s())
            except Exception as exc:
                self._mark_dead_if_transport_error(exc)
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
                self._mark_dead_if_transport_error(exc)
                self._trace("set_opt", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise

    def read_single(self):
        # Prefer legacy single-shot ``b"A"`` first because this project's
        # long-lived acquisition paths historically used it successfully.
        # Some firmware variants support only one of ``A`` / ``A,1,1``.
        # We therefore try both forms before declaring the link dead.
        with self._locked("read_single"):
            t0 = time.time()
            try:
                result = ReadASD(self._s())
            except socket.timeout as exc:
                self._trace(
                    "read_single",
                    "legacy ReadASD timed out; reconnecting and retrying ReadASD",
                )
                try:
                    self.reconnect()
                    result = ReadASD(self._s())
                except socket.timeout:
                    self._trace(
                        "read_single",
                        "ReadASD retry timed out; reconnecting and trying A,1,1 fallback",
                    )
                    self.reconnect()
                    result = ReadASD1(self._s(), 1)
                except Exception as fallback_exc:
                    self._mark_dead_if_transport_error(fallback_exc)
                    self._trace(
                        "read_single",
                        "fallback FAILED {}: {} elapsed={:.3f}s".format(
                            type(fallback_exc).__name__,
                            fallback_exc,
                            time.time() - t0,
                        ),
                    )
                    raise fallback_exc from exc
            except Exception as exc:
                self._mark_dead_if_transport_error(exc)
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
            except socket.timeout as exc:
                # Some firmware images do not answer ``A,1,N`` reliably.
                # Reconnect before fallback because a timed-out acquisition
                # often leaves the server-side session wedged.
                self._trace(
                    "read_average",
                    "A,1,{} timed out; reconnecting and retrying A,1,N".format(
                        repeats
                    ),
                )
                try:
                    self.reconnect()
                    result = ReadASD1(self._s(), repeats)
                except socket.timeout:
                    self._trace(
                        "read_average",
                        "A,1,{} retry timed out; reconnecting and falling back to repeated A".format(
                            repeats
                        ),
                    )
                    self.reconnect()
                    spectra = []
                    header = None
                    for _ in range(max(1, int(repeats))):
                        header, spectrum = ReadASD(self._s())
                        spectra.append(spectrum)
                    if len(spectra) == 1:
                        avg = spectra[0]
                    else:
                        avg = np.mean(np.stack(spectra, axis=0), axis=0)
                    result = (header, avg)
                except Exception as fallback_exc:
                    self._mark_dead_if_transport_error(fallback_exc)
                    self._trace(
                        "read_average",
                        "fallback FAILED repeats={} {}: {} elapsed={:.3f}s".format(
                            repeats,
                            type(fallback_exc).__name__,
                            fallback_exc,
                            time.time() - t0,
                        ),
                    )
                    raise fallback_exc from exc
            except Exception as exc:
                self._mark_dead_if_transport_error(exc)
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
                self._mark_dead_if_transport_error(exc)
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
