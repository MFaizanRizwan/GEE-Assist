"""InlineEdit: text that turns into a text box when clicked (offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QFocusEvent, QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.widgets.inline_edit import InlineEdit  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])  # kept alive for the whole module


@pytest.fixture
def edit(app):
    widget = InlineEdit()
    widget.set_value("Ayesha Khan")
    yield widget
    widget.deleteLater()


def test_shows_the_value_as_text_until_clicked(edit):
    assert edit.display.text() == "Ayesha Khan" and not edit.is_editing()
    edit.display.click()
    assert edit.is_editing() and edit.input.text() == "Ayesha Khan" and not edit.is_dirty()


def test_an_empty_value_shows_a_dash(app):
    widget = InlineEdit()
    widget.set_value(None)
    assert widget.display.text() == "—" and widget.value() == ""


def test_only_a_real_change_is_dirty(edit):
    changes = []
    edit.changed.connect(lambda: changes.append(edit.is_dirty()))
    edit.display.click()
    edit.input.setText("Ayesha Kiran Khan")
    edit.input.textEdited.emit("Ayesha Kiran Khan")
    assert edit.is_dirty() and edit.value() == "Ayesha Kiran Khan" and changes == [True]
    edit.input.setText("Ayesha Khan ")  # back to the same value (spaces do not count)
    assert not edit.is_dirty()


def test_leaving_without_a_change_shows_text_again(edit):
    edit.display.click()
    QApplication.sendEvent(edit.input, QFocusEvent(QEvent.Type.FocusOut))
    assert not edit.is_editing()


def test_leaving_with_a_change_keeps_the_text_box(edit):
    edit.display.click()
    edit.input.setText("Someone Else")
    QApplication.sendEvent(edit.input, QFocusEvent(QEvent.Type.FocusOut))
    assert edit.is_editing() and edit.is_dirty()


def test_escape_and_discard_give_the_change_up(edit):
    edit.display.click()
    edit.input.setText("Someone Else")
    QApplication.sendEvent(edit.input, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                                 Qt.KeyboardModifier.NoModifier))
    assert not edit.is_editing() and edit.value() == "Ayesha Khan"


def test_a_new_saved_value_keeps_a_change_being_typed(edit):
    edit.display.click()
    edit.input.setText("Typed Name")
    edit.set_value("From The Server")
    assert edit.input.text() == "Typed Name" and edit.display.text() == "From The Server"


def test_an_error_opens_the_text_box_and_goes_when_typing(edit):
    edit.set_error("Use letters only")
    assert edit.is_editing() and not edit.error.isHidden()
    edit.input.textEdited.emit("x")
    assert edit.error.isHidden()
