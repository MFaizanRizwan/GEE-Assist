"""Updating the app: download the new installer, check it, start it."""

from __future__ import annotations

import httpx
import pytest

from backend.business.update.update_service import INSTALLER_NAME, UpdateService
from backend.config.version import UPDATE_DOWNLOAD_URL
from backend.exceptions import UpdateCancelledError, UpdateError

@pytest.fixture(scope="module")
def qapp():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])  # kept alive by the fixture


INSTALLER = b"MZ" + b"\0" * 600_000  # a Windows .exe starts with "MZ"


def _service(tmp_path, handler, launcher=None):
    return UpdateService(
        download_dir=tmp_path,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
        launcher=launcher or (lambda path: None),
    )


def test_downloads_the_installer_following_the_github_redirect(tmp_path):
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://objects.example.com/setup.exe"})
        return httpx.Response(200, content=INSTALLER)

    progress = []
    path = _service(tmp_path, handler).download_update(UPDATE_DOWNLOAD_URL, lambda r, t: progress.append((r, t)))

    assert path == tmp_path / INSTALLER_NAME
    assert path.read_bytes() == INSTALLER
    assert progress[-1] == (len(INSTALLER), len(INSTALLER))
    assert not list(tmp_path.glob("*.part"))


def test_missing_release_says_so(tmp_path):
    with pytest.raises(UpdateError, match="not found"):
        _service(tmp_path, lambda r: httpx.Response(404)).download_update(UPDATE_DOWNLOAD_URL)
    assert not list(tmp_path.iterdir())


def test_network_failure_is_a_plain_message(tmp_path):
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(UpdateError, match="internet connection"):
        _service(tmp_path, handler).download_update(UPDATE_DOWNLOAD_URL)


def test_a_file_that_is_not_an_installer_is_rejected(tmp_path):
    handler = lambda r: httpx.Response(200, content=b"<html>Not Found</html>")  # noqa: E731
    with pytest.raises(UpdateError, match="not a valid installer"):
        _service(tmp_path, handler).download_update(UPDATE_DOWNLOAD_URL)
    assert not (tmp_path / INSTALLER_NAME).exists()


def test_cancelling_stops_the_download_and_removes_the_partial_file(tmp_path):
    handler = lambda r: httpx.Response(200, content=INSTALLER)  # noqa: E731
    with pytest.raises(UpdateCancelledError):
        _service(tmp_path, handler).download_update(UPDATE_DOWNLOAD_URL, is_cancelled=lambda: True)
    assert not list(tmp_path.iterdir())


def test_install_starts_the_downloaded_installer(tmp_path):
    started = []
    service = _service(tmp_path, lambda r: httpx.Response(200, content=INSTALLER), launcher=started.append)
    path = service.download_update(UPDATE_DOWNLOAD_URL)
    service.install_update(path)
    assert started == [path]


def test_install_reports_an_installer_that_cannot_start(tmp_path):
    def refuse(path):
        raise OSError(1223, "The operation was canceled by the user")  # e.g. UAC prompt declined

    service = _service(tmp_path, lambda r: httpx.Response(200, content=INSTALLER), launcher=refuse)
    path = service.download_update(UPDATE_DOWNLOAD_URL)
    with pytest.raises(UpdateError, match="Could not start the installer"):
        service.install_update(path)


def test_server_without_download_url_uses_the_github_release():
    from unittest.mock import MagicMock

    from backend.business.user.user_service import UserService

    api = MagicMock()
    api.check_app_version.return_value = {"latest_version": "1.0.1", "download_url": "", "update_available": True}
    service = UserService(api=api, session_store=MagicMock(), session=MagicMock(active=False))
    assert service.check_app_version().download_url == UPDATE_DOWNLOAD_URL


def test_update_dialog_downloads_installs_and_quits(qapp, monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from backend.dto.version_dto import AppVersionDTO
    from frontend.views import update_dialog

    installer = tmp_path / INSTALLER_NAME
    facade = MagicMock()
    # run the "background" download at once, on this thread
    monkeypatch.setattr(update_dialog, "run_task",
                        lambda owner, fn, *args, on_success, on_error: on_success(fn(*args)))
    quit_called = []
    monkeypatch.setattr(update_dialog.QApplication, "quit", lambda: quit_called.append(True))
    facade.download_update.return_value = installer

    info = AppVersionDTO(latest_version="1.0.1", minimum_supported_version="1.0.0",
                         download_url=UPDATE_DOWNLOAD_URL, update_available=True)
    dialog = update_dialog.UpdateDialog(facade, info)
    dialog.start_update()

    assert facade.download_update.call_args.args[0] == UPDATE_DOWNLOAD_URL
    facade.install_update.assert_called_once_with(installer)
    assert quit_called == [True]


def test_update_dialog_shows_a_failed_download(qapp, monkeypatch):
    from unittest.mock import MagicMock

    from backend.dto.version_dto import AppVersionDTO
    from frontend.views import update_dialog

    monkeypatch.setattr(update_dialog, "run_task",
                        lambda owner, fn, *args, on_success, on_error: on_error(UpdateError("No internet.")))
    facade = MagicMock()
    info = AppVersionDTO(latest_version="1.0.1", minimum_supported_version="1.0.0",
                         download_url=UPDATE_DOWNLOAD_URL, update_available=True)
    dialog = update_dialog.UpdateDialog(facade, info)
    dialog.start_update()

    assert dialog.status_label.text() == "No internet."
    assert dialog.update_button.text() == "Try Again" and dialog.update_button.isEnabled()
    facade.install_update.assert_not_called()
