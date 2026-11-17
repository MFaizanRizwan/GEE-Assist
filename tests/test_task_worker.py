"""run_task: callbacks run on the UI thread, and a failing callback never ends the application."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.workers.task_worker import run_task  # noqa: E402

app = QApplication.instance() or QApplication([])


def _wait(condition, timeout_ms=3000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    assert condition()


def test_the_result_reaches_on_success():
    owner, got = QObject(), []
    run_task(owner, lambda a, b: a + b, 2, 3, on_success=got.append)
    _wait(lambda: got)
    assert got == [5]


def test_an_error_in_the_task_reaches_on_error():
    owner, errors = QObject(), []
    run_task(owner, lambda: 1 / 0, on_error=errors.append)
    _wait(lambda: errors)
    assert isinstance(errors[0], ZeroDivisionError)


def test_a_failing_on_success_is_reported_to_on_error_instead_of_ending_the_app():
    owner, errors = QObject(), []

    def show(value):
        raise TypeError(f"cannot show {value}")

    run_task(owner, lambda: "result", on_success=show, on_error=errors.append)
    _wait(lambda: errors)
    assert isinstance(errors[0], TypeError) and str(errors[0]) == "cannot show result"


def test_a_failing_callback_without_on_error_is_only_logged(caplog):
    owner = QObject()
    run_task(owner, lambda: "result", on_success=lambda value: 1 / 0)
    _wait(lambda: "Showing the result of a background task failed" in caplog.text)


def test_a_failing_on_error_is_only_logged(caplog):
    owner = QObject()

    def report(exc):
        raise RuntimeError("the page is gone")

    run_task(owner, lambda: 1 / 0, on_error=report)
    _wait(lambda: "Reporting the failure of a background task failed" in caplog.text)


def test_nothing_is_delivered_once_the_owner_is_deleted():
    import time

    from PyQt6 import sip

    owner, got = QObject(), []

    def slow():
        time.sleep(0.2)
        return "late"

    run_task(owner, slow, on_success=got.append, on_error=got.append)
    sip.delete(owner)  # e.g. the page was closed while the task ran
    QTest.qWait(500)
    assert got == []


def test_nothing_is_delivered_to_a_deleted_page_even_if_the_owner_lives():
    import time

    from PyQt6 import sip

    class Page(QObject):
        def __init__(self):
            super().__init__()
            self.shown = []

        def show(self, value):
            self.shown.append(value)

    owner, page = QObject(), Page()

    def slow():
        time.sleep(0.2)
        return "late"

    run_task(owner, slow, on_success=page.show)
    sip.delete(page)
    QTest.qWait(500)  # no crash calling into the deleted page
