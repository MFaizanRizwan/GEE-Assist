"""Run blocking backend calls (network requests) off the UI thread.

    run_task(self, self._facade.log_in, username, password,
             on_success=self._on_logged_in, on_error=self._on_failed)

Callbacks run on the UI thread. They are dropped if ``owner`` has been deleted meanwhile.

An exception raised by a callback is logged and, from ``on_success``, handed to ``on_error``:
PyQt ends the whole application when a slot raises, so a bug in showing one result (or a test
leaving a window behind) must never take the app down.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)


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
            if not _is_expected(exc):
                logger.exception("Background task failed")
            self._emit(self._signals.failed, exc)
        else:
            self._emit(self._signals.succeeded, result)

    @staticmethod
    def _emit(signal, value: Any) -> None:
        try:
            signal.emit(value)
        except RuntimeError:
            pass  # the owner widget (and with it the signals object) was deleted


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
    # Parented to the owner (UI thread), so the callbacks are queued back onto the UI thread.
    signals = _TaskSignals(owner)
    if on_success:
        signals.succeeded.connect(_guarded_success(on_success, on_error))
    if on_error:
        signals.failed.connect(_guarded_error(on_error))
    signals.succeeded.connect(signals.deleteLater)
    signals.failed.connect(signals.deleteLater)
    QThreadPool.globalInstance().start(_Task(fn, args, signals))


def _guarded_success(on_success: Callable[[Any], None],
                     on_error: Callable[[Exception], None] | None) -> Callable[[Any], None]:
    """``on_success``, with an exception it raises logged and passed to ``on_error`` instead of ending the app."""
    def deliver(value: Any) -> None:
        try:
            on_success(value)
        except Exception as exc:  # noqa: BLE001 - shown on the page through on_error, never fatal
            logger.exception("Showing the result of a background task failed")
            if on_error is not None:
                _guarded_error(on_error)(exc)
    return deliver


def _guarded_error(on_error: Callable[[Exception], None]) -> Callable[[Exception], None]:
    """``on_error``, with an exception it raises itself logged instead of ending the app."""
    def deliver(exc: Exception) -> None:
        try:
            on_error(exc)
        except Exception:  # noqa: BLE001
            logger.exception("Reporting the failure of a background task failed")
    return deliver
