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
        interval_factor: float = 1.2,
    ):
        self.spectrometer = spectrometer
        self.emit_log = emit_log
        self.should_idle_poll = should_idle_poll or (lambda: True)
        self.min_interval_s = min_interval_s
        self.max_interval_s = max_interval_s
        self.interval_factor = interval_factor

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._latest = None
        self._latest_seq = 0
        self._next_interval_s = self.min_interval_s
        self._error_backoff_s = self.max_interval_s

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
        while not self._stop_event.is_set():
            if not self.should_idle_poll():
                self._stop_event.wait(0.05)
                continue

            t0 = time.perf_counter()
            try:
                header, spectrum = self.spectrometer.read_single()
                elapsed_s = max(0.001, time.perf_counter() - t0)
                self._publish(header, spectrum, "idle_poll")
                tuned = elapsed_s * self.interval_factor
                self._next_interval_s = min(
                    self.max_interval_s,
                    max(self.min_interval_s, tuned),
                )
            except Exception as exc:
                if self.emit_log:
                    self.emit_log("Live spectrum poll failed: {}".format(exc))
                self._next_interval_s = min(
                    self.max_interval_s,
                    max(self.min_interval_s, self._error_backoff_s),
                )
                self._error_backoff_s = min(self.max_interval_s, self._error_backoff_s * 1.5)
            else:
                self._error_backoff_s = self.max_interval_s

            self._stop_event.wait(self._next_interval_s)
