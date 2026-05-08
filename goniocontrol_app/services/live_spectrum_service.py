import threading
import time
from typing import Any, Callable, Optional

import numpy as np


class LiveSpectrumService:
    def __init__(
        self,
        spectrometer: Any,
        emit_log: Optional[Callable[[str], None]] = None,
        should_idle_poll: Optional[Callable[[], bool]] = None,
        min_interval_s: float = 0.1,
        max_interval_s: float = 1.0,
        error_max_interval_s: float = 30.0,
        interval_factor: float = 1.2,
    ):
        self.spectrometer = spectrometer
        self.emit_log = emit_log
        self.should_idle_poll = should_idle_poll or (lambda: True)
        self.min_interval_s = min_interval_s
        self.max_interval_s = max_interval_s
        self.error_max_interval_s = max(error_max_interval_s, max_interval_s)
        self.interval_factor = interval_factor

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest = None
        self._latest_seq = 0
        self._next_interval_s = self.min_interval_s
        self._error_backoff_s = self.max_interval_s
        self._last_error_message: Optional[str] = None
        self._error_streak = 0

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_idle_poll_loop,
                name="LiveSpectrumService",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout_s: float = 2.0):
        self._stop_event.set()
        thread = None
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_s)

    def on_spectrum(self, header, spectrum, source):
        self._publish(header, spectrum, source)

    def get_latest(self):
        with self._lock:
            return self._latest, self._latest_seq

    def _publish(self, header, spectrum, source):
        record = {
            "header": tuple(header) if header is not None else None,
            "spectrum": np.array(spectrum, copy=True) if spectrum is not None else None,
            "source": source,
            "timestamp": time.time(),
        }
        with self._lock:
            self._latest = record
            self._latest_seq += 1

    def _run_idle_poll_loop(self):
        # print("DEBUG: LiveSpectrumService loop starting")
        poll_id = 0
        while not self._stop_event.is_set():
            if not self.should_idle_poll():
                self._stop_event.wait(0.05)
                continue

            poll_id += 1
            t0 = time.perf_counter()
            # print("DEBUG: LiveSpectrumService poll #{} starting".format(poll_id))
            self._maybe_reconnect_before_poll(poll_id)
            try:
                header, spectrum = self.spectrometer.read_single()
                elapsed_s = max(0.001, time.perf_counter() - t0)
                self._publish(header, spectrum, "idle_poll")
                tuned = elapsed_s * self.interval_factor
                self._next_interval_s = min(
                    self.max_interval_s,
                    max(self.min_interval_s, tuned),
                )
                # print("DEBUG: LiveSpectrumService poll #{} ok elapsed={:.3f}s next={:.3f}s".format(
                # poll_id, elapsed_s, self._next_interval_s))
                self._on_poll_success()
            except Exception as exc:
                elapsed_s = time.perf_counter() - t0
                # print("DEBUG: LiveSpectrumService poll #{} FAILED elapsed={:.3f}s {}: {}".format(
                # poll_id, elapsed_s, type(exc).__name__, exc))
                self._on_poll_failure(exc)
                # print("DEBUG: LiveSpectrumService poll #{} next={:.3f}s streak={} backoff={:.3f}s".format(
                # poll_id, self._next_interval_s, self._error_streak,
                # self._error_backoff_s))

            self._stop_event.wait(self._next_interval_s)
        # print("DEBUG: LiveSpectrumService loop exiting")

    def _maybe_reconnect_before_poll(self, poll_id: int):
        """Re-establish the spectrometer link if it has been marked dead.

        Without this, once a BrokenPipeError or recv timeout flips the
        ``needs_reconnect`` flag in SpectrometerService, every subsequent
        poll would raise immediately and the live preview would be silently
        stuck for the rest of the session.
        """
        needs_reconnect = getattr(self.spectrometer, "needs_reconnect", None)
        reconnect = getattr(self.spectrometer, "reconnect", None)
        if not callable(needs_reconnect) or not callable(reconnect):
            return
        if not needs_reconnect():
            return
        try:
            # print("DEBUG: LiveSpectrumService poll #{} reconnect attempt".format(poll_id))
            reconnect()
            # print("DEBUG: LiveSpectrumService poll #{} reconnect ok".format(poll_id))
            if self.emit_log:
                self.emit_log("Live spectrum: reconnected to spectrometer.")
        except Exception as exc:
            # print("DEBUG: LiveSpectrumService poll #{} reconnect FAILED {}: {}".format(
            # poll_id, type(exc).__name__, exc))
            # Swallow: the upcoming read_single() will raise too and the
            # error path below will keep us in backoff until the next try.
            pass

    def _on_poll_success(self):
        if self._error_streak > 0 and self.emit_log:
            self.emit_log(
                "Live spectrum poll recovered after {} failures.".format(
                    self._error_streak
                )
            )
        self._error_streak = 0
        self._last_error_message = None
        self._error_backoff_s = self.max_interval_s

    def _on_poll_failure(self, exc: BaseException):
        message = "{}: {}".format(type(exc).__name__, exc)
        self._error_streak += 1
        # Log the first occurrence of an error and any change in error type;
        # otherwise stay quiet so a dead spectrometer link cannot flood the
        # log every second.
        if self.emit_log and message != self._last_error_message:
            self.emit_log("Live spectrum poll failed: {}".format(message))
        self._last_error_message = message

        # Backoff grows exponentially up to ``error_max_interval_s`` so a hard
        # error (e.g. broken pipe) eventually polls only every few seconds.
        self._error_backoff_s = min(
            self.error_max_interval_s,
            max(self.max_interval_s, self._error_backoff_s * 1.5),
        )
        self._next_interval_s = min(
            self.error_max_interval_s,
            max(self.min_interval_s, self._error_backoff_s),
        )
