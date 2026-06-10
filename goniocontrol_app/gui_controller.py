# -*- coding: utf-8 -*-
import threading
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from goniocontrol_app.workflow_service import WorkflowService


class GuiController:
    def __init__(self, workflow, emit_log, emit_busy, emit_window_status=None):
        self.workflow = workflow
        self.emit_log = emit_log
        self.emit_busy = emit_busy
        self.emit_window_status = emit_window_status or (lambda _suffix: None)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._cancel_event = threading.Event()
        self._future: Optional[Future] = None
        self._sequence_active = False
        self._last_progress_suffix: Optional[str] = None

    def is_busy(self):
        return self._future is not None and not self._future.done()

    def cancel(self):
        self._cancel_event.set()
        self.emit_log("Cancellation requested.")
        if self._sequence_active:
            suffix = "Cancelling..."
            if self._last_progress_suffix:
                suffix = "Cancelling · {}".format(self._last_progress_suffix)
            self.emit_window_status(suffix)

    @staticmethod
    def _format_measure_status(msg):
        if msg.startswith("Angle "):
            return "Measuring " + msg[6:].replace(": ", " · ", 1)
        return msg

    def run_async(
        self,
        label: str,
        fn: Callable[[], None],
        on_error=None,
        suppress_completed_log: bool = False,
    ) -> None:
        if self.is_busy():
            self.emit_log("Another operation is already running.")
            return
        self._cancel_event.clear()
        self.emit_busy(True)
        self.emit_log("Starting: {}".format(label))

        def task():
            try:
                fn()
                if not suppress_completed_log:
                    self.emit_log("Completed: {}".format(label))
            except Exception as exc:
                self.emit_log("Failed: {}: {}".format(label, exc))
                self.emit_log("Failure type: {}".format(type(exc).__name__))
                tb = traceback.format_exc()
                self.emit_log("Traceback:\n{}".format(tb))
                print("=== Async task failure: {} ===".format(label))
                print(tb)
                if on_error:
                    on_error(exc)
            finally:
                self.emit_busy(False)

        self._future = self.executor.submit(task)

    def run_measure(self, repeats, label=None, on_finally=None):
        if label is None:
            label = "Measure (repeats={})".format(repeats)

        def progress(msg):
            self.emit_log(msg)
            suffix = self._format_measure_status(msg)
            self._last_progress_suffix = suffix
            self.emit_window_status(suffix)

        def measure():
            self.workflow.measure_sequence(
                repeats=repeats,
                progress=progress,
                should_cancel=self._cancel_event.is_set,
            )
            if self._cancel_event.is_set():
                self.emit_log("Aborted: {}".format(label))
            else:
                self.emit_log("Completed: {}".format(label))

        def wrapped():
            self._sequence_active = True
            self._last_progress_suffix = None
            try:
                measure()
            finally:
                self._sequence_active = False
                if on_finally:
                    on_finally()
                self.emit_window_status(None)

        self.run_async(label, wrapped, suppress_completed_log=True)

    def shutdown_executor(self, wait=True):
        # Prevent the worker thread from keeping the process alive on app exit.
        self._cancel_event.set()
        try:
            self.executor.shutdown(wait=wait, cancel_futures=True)
        except TypeError:
            # Python <3.9 does not support cancel_futures.
            self.executor.shutdown(wait=wait)
