"""The feedback modal opens the matching tab of the website's community page (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from backend.config.settings import Settings, get_settings  # noqa: E402
from frontend.views.feedback_dialog import CHOICES, FeedbackDialog, community_url  # noqa: E402

app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize(("tab", "url"), [
    ("rate", "http://localhost:5173/community?tab=rate"),
    ("feedback", "http://localhost:5173/community?tab=feedback"),
    ("suggest", "http://localhost:5173/community?tab=suggest"),
])
def test_each_choice_has_its_community_tab(tab, url):
    assert community_url(tab, "http://localhost:5173/") == url


def test_the_website_address_comes_from_the_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("WEB_APP_URL", "https://gee-assist.example/")
    try:
        assert community_url("feedback") == "https://gee-assist.example/community?tab=feedback"
    finally:
        get_settings.cache_clear()


def test_the_default_website_is_the_deployed_site():
    assert Settings().web_app_url == "https://gee-assist-web.vercel.app"


def test_an_unknown_tab_is_refused():
    with pytest.raises(ValueError):
        community_url("complaints", "http://localhost:5173")


@pytest.mark.parametrize("tab", list(CHOICES))
def test_choosing_opens_the_tab_in_the_browser_and_closes(tab):
    opened = []
    dialog = FeedbackDialog(open_url=lambda url: opened.append(url.toString()) or True,
                            base_url="http://localhost:5173")
    dialog.buttons[tab].click()
    assert opened == [f"http://localhost:5173/community?tab={tab}"]
    assert dialog.choice == tab and dialog.result() == QDialog.DialogCode.Accepted


def test_not_now_opens_nothing():
    opened = []
    dialog = FeedbackDialog(open_url=opened.append, base_url="http://localhost:5173")
    dialog.not_now.click()
    assert opened == [] and dialog.choice is None and dialog.result() == QDialog.DialogCode.Rejected


def test_the_dialog_offers_rating_feedback_and_suggestion():
    dialog = FeedbackDialog(reason="You just read an AI explanation.", open_url=lambda url: True)
    texts = [button.text() for button in dialog.buttons.values()]
    assert any("Rate the app" in t for t in texts)
    assert any("Send feedback" in t for t in texts)
    assert any("Suggest a feature" in t for t in texts)
