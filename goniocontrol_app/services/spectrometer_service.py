import socket
import threading
import time
from typing import List, Optional

import numpy as np

from asdcontroller.asd_controller import ASDController
from asdcontroller.asd_types import frinterp_to_legacy_header_and_spectrum


class SpectrometerService:
    """Thin wrapper around ``ASDController`` (ASD TCP protocol).

    All public methods that touch the controller are serialized through
    ``self._lock``. The ASD speaks a single byte stream; concurrent senders
    or receivers would interleave commands and corrupt response framing.
    A reentrant lock lets a single thread compose higher-level operations
    without self-deadlock.
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
        self._controller: Optional[ASDController] = None
        # Backward compatibility: truthy when a link exists (tests / old code).
        self.socket = None
        self._lock = threading.RLock()
        self._needs_reconnect = False

    def _trace(self, op: str, msg: str = ""):
        thread = threading.current_thread().name
        suffix = (" " + msg) if msg else ""
        # print("DEBUG: SpectrometerService[{}] {}{}".format(thread, op, suffix))

    def _locked(self, op: str):
        thread = threading.current_thread().name
        t0 = time.time()
        self._trace(op, "wait-lock")
        self._lock.acquire()
        wait_s = time.time() - t0
        if wait_s > 0.001:
            # print("DEBUG: SpectrometerService[{}] {} got-lock wait={:.3f}s".format(
                # thread, op, wait_s))
        return _LockHandle(self._lock, op, thread)

    def _dispose_controller(self):
        if self._controller is not None:
            try:
                self._controller.close()
            except Exception as exc:
                self._trace("_dispose_controller", "{}: {}".format(type(exc).__name__, exc))
            self._controller = None
        self.socket = None

    def connect(self):
        with self._locked("connect"):
            self._trace("connect", "host={} port={}".format(self.host, self.port))
            self._dispose_controller()
            self._needs_reconnect = False
            try:
                self._controller = ASDController(
                    ip=self.host,
                    port=self.port,
                    default_sock_timeout_s=self.default_timeout_s,
                )
            except Exception as exc:
                self._dispose_controller()
                raise
            self.socket = self._controller
            greeting = b"ASD"
            self._trace("connect", "controller ok")
            return greeting

    def reconnect(self):
        """Tear down the existing controller and dial a fresh one."""
        with self._locked("reconnect"):
            self._trace("reconnect", "host={} port={}".format(self.host, self.port))
            self._dispose_controller()
            self._needs_reconnect = False
            try:
                self._controller = ASDController(
                    ip=self.host,
                    port=self.port,
                    default_sock_timeout_s=self.default_timeout_s,
                )
            except Exception as exc:
                self._dispose_controller()
                raise
            self.socket = self._controller
            greeting = b"ASD"
            self._trace("reconnect", "controller ok")
            return greeting

    def needs_reconnect(self) -> bool:
        return self._needs_reconnect or self._controller is None

    def close(self):
        self._trace("close", "begin")
        acquired = self._lock.acquire(timeout=2.0)
        try:
            self._dispose_controller()
            self._needs_reconnect = False
            self._trace("close", "done acquired_lock={}".format(acquired))
        finally:
            if acquired:
                self._lock.release()

    def _ctrl(self) -> ASDController:
        if self._controller is None or self._needs_reconnect:
            raise ConnectionError(
                "Spectrometer link is down (needs reconnect={}).".format(
                    self._needs_reconnect
                )
            )
        return self._controller

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

    def _optimize_tuple(self, ctrl: ASDController):
        opt = ctrl.optimize()
        return (
            opt.header,
            opt.errbyte,
            opt.itime,
            [opt.gain_1, opt.gain_2],
            [opt.offset_1, opt.offset_2],
        )

    def restore(self):
        with self._locked("restore"):
            try:
                self._ctrl().restore()
            except Exception as exc:
                self._mark_dead_if_transport_error(exc)
                self._trace("restore", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise

    def optimize(self):
        with self._locked("optimize"):
            t0 = time.time()
            try:
                result = self._optimize_tuple(self._ctrl())
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
                g: List[int] = list(gain) if not isinstance(gain, list) else gain
                o: List[int] = list(offset) if not isinstance(offset, list) else offset
                self._ctrl().apply_set_opt(int(itime), g, o)
            except Exception as exc:
                self._mark_dead_if_transport_error(exc)
                self._trace("set_opt", "FAILED {}: {}".format(type(exc).__name__, exc))
                raise

    def read_single(self):
        with self._locked("read_single"):
            t0 = time.time()
            attempts = (
                ("A,1,1", lambda: frinterp_to_legacy_header_and_spectrum(
                    self._ctrl().acquire(1))),
                ("A,1,1 retry", lambda: frinterp_to_legacy_header_and_spectrum(
                    self._ctrl().acquire(1))),
            )
            last_exc = None
            for idx, (label, reader) in enumerate(attempts):
                if idx > 0:
                    self._trace("read_single", "{} after reconnect".format(label))
                    self.reconnect()
                try:
                    result = reader()
                    break
                except socket.timeout as exc:
                    last_exc = exc
                    self._trace(
                        "read_single",
                        "{} timed out after {:.3f}s".format(label, time.time() - t0),
                    )
                    continue
                except Exception as exc:
                    self._mark_dead_if_transport_error(exc)
                    self._trace(
                        "read_single",
                        "{} FAILED {}: {} elapsed={:.3f}s".format(
                            label,
                            type(exc).__name__,
                            exc,
                            time.time() - t0,
                        ),
                    )
                    raise
            else:
                if last_exc is None:
                    last_exc = TimeoutError("all read_single attempts failed")
                self._mark_dead_if_transport_error(last_exc)
                self._trace(
                    "read_single",
                    "FAILED after all attempts {}: {} elapsed={:.3f}s".format(
                        type(last_exc).__name__,
                        last_exc,
                        time.time() - t0,
                    ),
                )
                raise last_exc
            self._trace("read_single", "ok header[0]={} elapsed={:.3f}s".format(
                result[0][0], time.time() - t0))
            return result

    def read_average(self, repeats):
        with self._locked("read_average({})".format(repeats)):
            t0 = time.time()
            count = max(1, int(repeats))
            attempts = (
                ("A,1,{}".format(count), lambda: frinterp_to_legacy_header_and_spectrum(
                    self._ctrl().acquire(count))),
                ("A,1,{} retry".format(count), lambda: frinterp_to_legacy_header_and_spectrum(
                    self._ctrl().acquire(count))),
            )
            last_exc = None
            for idx, (label, reader) in enumerate(attempts):
                if idx > 0:
                    self._trace(
                        "read_average",
                        "{} after reconnect".format(label),
                    )
                    self.reconnect()
                try:
                    result = reader()
                    break
                except socket.timeout as exc:
                    last_exc = exc
                    self._trace(
                        "read_average",
                        "{} timed out after {:.3f}s".format(
                            label, time.time() - t0
                        ),
                    )
                    continue
                except Exception as exc:
                    self._mark_dead_if_transport_error(exc)
                    self._trace(
                        "read_average",
                        "{} FAILED {}: {} elapsed={:.3f}s".format(
                            label,
                            type(exc).__name__,
                            exc,
                            time.time() - t0,
                        ),
                    )
                    raise
            else:
                if last_exc is None:
                    last_exc = TimeoutError("all read_average attempts failed")
                self._mark_dead_if_transport_error(last_exc)
                self._trace(
                    "read_average",
                    "FAILED repeats={} after all attempts {}: {} elapsed={:.3f}s".format(
                        repeats,
                        type(last_exc).__name__,
                        last_exc,
                        time.time() - t0,
                    ),
                )
                raise last_exc
            self._trace("read_average", "ok repeats={} header[0]={} elapsed={:.3f}s".format(
                repeats, result[0][0], time.time() - t0))
            return result

    def vnir_info(self):
        with self._locked("vnir_info"):
            t0 = time.time()
            try:
                result = self._ctrl().vnir_info()
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
            # print("DEBUG: SpectrometerService[{}] {} release".format(
                # self._thread, self._op))
        else:
            # print("DEBUG: SpectrometerService[{}] {} release-after-error {}: {}".format(
                # self._thread, self._op, exc_type.__name__, exc))
        return False
