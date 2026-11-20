"""The saved window-layout choice (classical vs modern)."""

import pytest

from frontend import layout_mode


def test_no_choice_yet_means_classical(tmp_path):
    path = tmp_path / "layout.json"
    assert layout_mode.saved_layout(path) is None
    assert layout_mode.current_layout(path) == "classical"
    assert layout_mode.is_modern(path) is False


@pytest.mark.parametrize("name", ["classical", "modern"])
def test_choice_is_saved(tmp_path, name):
    path = tmp_path / "workspace" / "layout.json"
    layout_mode.save_layout(name, path)
    assert layout_mode.saved_layout(path) == name and layout_mode.current_layout(path) == name
    assert layout_mode.is_modern(path) == (name == "modern")


def test_unknown_or_damaged_settings_count_as_no_choice(tmp_path):
    path = tmp_path / "layout.json"
    path.write_text('{"layout": "fancy"}', encoding="utf-8")
    assert layout_mode.saved_layout(path) is None
    path.write_text("not json", encoding="utf-8")
    assert layout_mode.saved_layout(path) is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert layout_mode.saved_layout(path) is None


def test_unknown_layout_cannot_be_saved(tmp_path):
    with pytest.raises(ValueError):
        layout_mode.save_layout("fancy", tmp_path / "layout.json")
