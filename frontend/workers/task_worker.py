"""Run blocking backend calls (network requests) off the UI thread.

    run_task(self, self._facade.log_in, username, password,
             on_success=self._on_logged_in, on_error=self._on_failed)

Callbacks run on the UI thread. They are dropped if ``owner`` (or the object a callback belongs
to) has been deleted meanwhile, e.g. the page was closed while the task ran. The signals that
carry the result back are not owned by ``owner``: deleting a page must never delete them while
the worker thread may still emit on them (that crashed the process).

An exception raised by a callback is logged and, from ``on_success``, handed to ``on_error``:
PyQt ends the whole application when a slot raises, so a bug in showing one result (or a test
leaving a window behind) must never take the app down.

Quitting while a task runs: ``shutdown`` (called once the event loop has ended) stops tasks
from reporting back and waits a moment for the running ones. A task finishing during Python's
own shutdown used to reach for its already-deleted signals object ("wrapped C/C++ object of
type _TaskSignals has been deleted") or crash the process.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)

_pending: set = set()  # the signals of running tasks, until their result is delivered
_shutting_down = False  # set by shutdown(): finished tasks no longer report back


class _TaskSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args: tuple, signals: _TaskSignals):
        super().__init__()
        self._fn = fn
        self._args = args
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn(*self._args)
        except Exception as exc:  # delivered to on_error
            if not _is_expected(exc) and not _shutting_down:
                logger.exception("Background task failed")
            self._emit("failed", exc)
        else:
            self._emit("succeeded", result)

    def _emit(self, name: str, value: Any) -> None:
        """Deliver the result, unless the app is quitting or the signals object is gone.

        Even reading the signal off a deleted object raises, so that is inside the guard too
        (it used to be read before it, and the error escaped the worker thread)."""
        if _shutting_down:
            return
        try:
            signals = self._signals
            if sip.isdeleted(signals):
                return
            getattr(signals, name).emit(value)
        except RuntimeError:
            pass  # deleted meanwhile (the app is closing)


def shutdown(timeout_ms: int = 3000) -> bool:
    """The app is quitting: finished tasks stop reporting back, queued ones never start, and
    the running ones get ``timeout_ms`` to finish. True when none is left running."""
    global _shutting_down
    _shutting_down = True
    pool = QThreadPool.globalInstance()
    pool.clear()
    return pool.waitForDone(timeout_ms)


def _is_expected(exc: Exception) -> bool:
    from backend.exceptions import GeeAssistError

    return isinstance(exc, GeeAssistError)


def run_task(
    owner: QObject,
    fn: Callable[..., Any],
    *args: Any,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    # Created on the UI thread, so the callbacks are queued back onto it. Kept alive here, not by
    # ``owner``, until the result is delivered (see the module docstring).
    signals = _TaskSignals()
    _pending.add(signals)
    if on_success:
        signals.succeeded.connect(_guarded_success(owner, on_success, on_error))
    if on_error:
        signals.failed.connect(_guarded_error(owner, on_error))
    def finished(_value: Any) -> None:
        _pending.discard(signals)
        signals.deleteLater()

    signals.succeeded.connect(finished)
    signals.failed.connect(finished)
    QThreadPool.globalInstance().start(_Task(fn, args, signals))


def _alive(*objects: object) -> bool:
    """False once one of the Qt objects among ``objects`` has been deleted.

    Connected straight to a widget's method, PyQt drops a queued call when that widget is deleted;
    the guards below are plain functions, so they check it themselves (calling into a deleted
    widget crashes the process)."""
    return not any(isinstance(obj, QObject) and sip.isdeleted(obj) for obj in objects)


def _guarded_success(owner: QObject, on_success: Callable[[Any], None],
                     on_error: Callable[[Exception], None] | None) -> Callable[[Any], None]:
    """``on_success``, dropped once its owner is deleted, with an exception it raises logged and
    passed to ``on_error`` instead of ending the app."""
    def deliver(value: Any) -> None:
        if not _alive(owner, getattr(on_success, "__self__", None)):
            return
        try:
            on_success(value)
        except Exception as exc:  # noqa: BLE001 - shown on the page through on_error, never fatal
            logger.exception("Showing the result of a background task failed")
            if on_error is not None:
                _guarded_error(owner, on_error)(exc)
    return deliver


def _guarded_error(owner: QObject, on_error: Callable[[Exception], None]) -> Callable[[Exception], None]:
    """``on_error``, dropped once its owner is deleted, with an exception it raises logged instead of
    ending the app."""
    def deliver(exc: Exception) -> None:
        if not _alive(owner, getattr(on_error, "__self__", None)):
            return
        try:
            on_error(exc)
        except Exception:  # noqa: BLE001
            logger.exception("Reporting the failure of a background task failed")
    return deliver
