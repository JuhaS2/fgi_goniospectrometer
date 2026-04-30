from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from goniocontrol_app.workflow_service import WorkflowService


class GuiController:
    def __init__(self, workflow: WorkflowService, emit_log: Callable[[str], None], emit_busy: Callable[[bool], None]):
        self.workflow = workflow
        self.emit_log = emit_log
        self.emit_busy = emit_busy
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._cancel_event = threading.Event()
        self._future: Optional[Future] = None

    def is_busy(self) -> bool:
        return self._future is not None and not self._future.done()

    def cancel(self) -> None:
        self._cancel_event.set()
        self.emit_log("Cancellation requested.")

    def run_async(
        self,
        label: str,
        fn: Callable[[], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        if self.is_busy():
            self.emit_log("Another operation is already running.")
            return
        self._cancel_event.clear()
        self.emit_busy(True)
        self.emit_log(f"Starting: {label}")

        def task():
            try:
                fn()
                self.emit_log(f"Completed: {label}")
            except Exception as exc:
                self.emit_log(f"Failed: {label}: {exc}")
                if on_error:
                    on_error(exc)
            finally:
                self.emit_busy(False)

        self._future = self.executor.submit(task)

    def run_measure(self, repeats: int) -> None:
        self.run_async(
            f"Measure (repeats={repeats})",
            lambda: self.workflow.measure_sequence(
                repeats=repeats,
                progress=self.emit_log,
                should_cancel=self._cancel_event.is_set,
            ),
        )

