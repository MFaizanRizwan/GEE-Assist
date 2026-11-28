"""The app updates itself: download, check, swap in place (any folder, any name), clean up."""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")

from backend.business.update import AppUpdater, is_newer, same_version  # noqa: E402
from backend.business.update import app_updater as module  # noqa: E402
from backend.exceptions import UpdateError  # noqa: E402

RELEASE = b"MZ" + b"\0" * 1_200_000 + b"release 1.2.0"


def _installed(tmp_path, name="GEE Assist (copy).exe") -> Path:
    folder = tmp_path / "Some Folder" / "apps"
    folder.mkdir(parents=True)
    exe = folder / name
    exe.write_bytes(b"MZ old version")
    return exe


def _server(body: bytes = RELEASE, content_type="application/octet-stream", status=200):
    def handler(request):
        return httpx.Response(status, content=body, headers={"content-type": content_type,
                                                             "content-length": str(len(body))})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def runs_as(monkeypatch):
    """The downloaded program "starts" and reports this version (no real process)."""
    reported = {"version": "1.2.0"}

    def fake_run(args, **_kw):
        Path(args[2]).write_text(reported["version"], encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return reported


def test_versions_compare_by_number():
    assert is_newer("1.10.0", "1.9.3") and is_newer("v2.0", "1.99.99") and not is_newer("1.0.0", "1.0")
    assert same_version("1.2", "1.2.0") and not same_version("1.2.1", "1.2.0")


def test_download_checks_and_installs_over_the_running_copy_wherever_it_is(tmp_path, runs_as):
    exe = _installed(tmp_path)
    updater = AppUpdater(executable=exe, frozen=True, http=_server())
    seen = []
    new = updater.download("https://example.test/GEE-Assist.exe", "1.2.0",
                           sha256=hashlib.sha256(RELEASE).hexdigest(), progress=lambda d, t: seen.append((d, t)))
    assert new.parent == exe.parent and seen[-1] == (len(RELEASE), len(RELEASE))
    assert updater.install(new) == "swapped"
    assert exe.read_bytes() == RELEASE                             # same path, same name: the new version
    assert (exe.parent / (exe.name + ".old")).read_bytes() == b"MZ old version"
    updater.cleanup()
    assert sorted(p.name for p in exe.parent.iterdir()) == [exe.name]


def test_a_web_page_link_is_recognised_and_nothing_changes(tmp_path, runs_as):
    exe = _installed(tmp_path)
    page = AppUpdater(executable=exe, frozen=True, http=_server(b"<html>releases</html>", "text/html"))
    with pytest.raises(UpdateError) as caught:
        page.download("https://github.com/org/gee-assist/releases/latest", "1.2.0")
    assert caught.value.web_page
    assert exe.read_bytes() == b"MZ old version" and sorted(p.name for p in exe.parent.iterdir()) == [exe.name]


def test_a_damaged_download_is_refused(tmp_path, runs_as):
    exe = _installed(tmp_path)
    updater = AppUpdater(executable=exe, frozen=True, http=_server())
    with pytest.raises(UpdateError, match="SHA-256 does not match"):
        updater.download("https://example.test/x.exe", "1.2.0", sha256="0" * 64)
    tiny = AppUpdater(executable=exe, frozen=True, http=_server(b"MZ tiny"))
    with pytest.raises(UpdateError, match="too small"):
        tiny.download("https://example.test/x.exe", "1.2.0")
    assert exe.read_bytes() == b"MZ old version" and sorted(p.name for p in exe.parent.iterdir()) == [exe.name]


def test_the_wrong_version_is_refused_after_starting_it(tmp_path, runs_as):
    exe = _installed(tmp_path)
    runs_as["version"] = "1.0.0"                     # e.g. a release built without raising the number
    updater = AppUpdater(executable=exe, frozen=True, http=_server())
    with pytest.raises(UpdateError, match="version 1.0.0, not 1.2.0"):
        updater.download("https://example.test/x.exe", "1.2.0")
    assert sorted(p.name for p in exe.parent.iterdir()) == [exe.name]


def test_a_download_can_be_cancelled(tmp_path, runs_as):
    exe = _installed(tmp_path)
    updater = AppUpdater(executable=exe, frozen=True, http=_server())
    with pytest.raises(UpdateError, match="cancelled"):
        updater.download("https://example.test/x.exe", "1.2.0", cancelled=lambda: True)
    assert sorted(p.name for p in exe.parent.iterdir()) == [exe.name]


def test_a_failed_move_puts_the_working_app_back(tmp_path, monkeypatch):
    exe = _installed(tmp_path)
    new = exe.with_name("GEE-new.new.exe")
    new.write_bytes(RELEASE)

    def refuse(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(UpdateError, match="Nothing was changed"):
        AppUpdater(executable=exe, frozen=True).install(new)
    assert exe.read_bytes() == b"MZ old version"                     # restored


def test_running_from_source_never_replaces_anything(tmp_path):
    updater = AppUpdater(executable=Path(sys.executable), frozen=False)
    assert not updater.can_self_update()
    with pytest.raises(UpdateError):
        updater.install(tmp_path / "x.exe")


def test_a_protected_folder_uses_an_administrator_helper(tmp_path):
    script = module.helper_script(1234, Path(r"C:\Temp\GEE-Assist-1.2.0.new.exe"),
                                  Path(r"C:\Program Files\GEE Assist\GEE-Assist.exe"))
    assert "Wait-Process -Id 1234" in script
    assert "Move-Item -LiteralPath $new -Destination $exe -Force" in script
    assert "'C:\\Program Files\\GEE Assist\\GEE-Assist.exe'" in script and "Start-Process -FilePath $exe" in script


def test_main_reports_its_version_without_starting_the_app(tmp_path):
    report = tmp_path / "v.txt"
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "main.py"), "--write-version", str(report)], cwd=root, timeout=60,
                   check=True)
    from backend.config.version import APP_VERSION

    assert report.read_text(encoding="utf-8") == APP_VERSION


# ------------------------------------------------------------------ the window
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    """One application for the window tests, kept alive while they run (a discarded one is
    destroyed at once, taking its windows down with it)."""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_a_required_update_offers_no_later(qt_app):
    from unittest.mock import MagicMock

    from backend.dto.version_dto import AppVersionDTO
    from frontend.views import update_dialog

    facade = MagicMock()
    facade.can_self_update.return_value = True
    forced = update_dialog.UpdateDialog(AppVersionDTO("9.0.0", "9.0.0", "https://x/GEE-Assist.exe", force_update=True,
                                                      update_available=True), facade)
    assert forced.later_button.text() == "Quit GEE-Assist" and "must be updated" in forced.windowTitle() + \
        forced.findChildren(type(forced.status))[0].text()
    optional = update_dialog.UpdateDialog(AppVersionDTO("9.0.0", "1.0.0", "https://x/GEE-Assist.exe",
                                                        update_available=True), facade)
    assert optional.later_button.text() == "Later"


def test_the_dialog_downloads_installs_and_restarts(qt_app, monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from backend.dto.version_dto import AppVersionDTO
    from frontend.views import update_dialog

    def run_now(owner, fn, *args, on_success=None, on_error=None):
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001
            on_error(exc)
        else:
            on_success(result)

    started, quit_calls = [], []
    monkeypatch.setattr(update_dialog, "run_task", run_now)
    monkeypatch.setattr(update_dialog.QProcess, "startDetached", lambda *a: started.append(a) or True)
    monkeypatch.setattr(update_dialog.QTimer, "singleShot", lambda ms, fn: quit_calls.append(ms))
    facade = MagicMock()
    facade.can_self_update.return_value = True
    facade.download_update.return_value = tmp_path / "new.exe"
    facade.install_update.return_value = "swapped"
    facade.app_executable.return_value = r"D:\Tools\GEE\GEE-Assist.exe"
    dialog = update_dialog.UpdateDialog(AppVersionDTO("1.2.0", "1.0.0", "https://x/GEE-Assist.exe",
                                                      update_available=True), facade)
    dialog.update_button.click()
    assert dialog.state == "done"
    assert started and started[0][0] == r"D:\Tools\GEE\GEE-Assist.exe" and quit_calls   # restarted from where it is
    facade.download_update.side_effect = module.UpdateError("The download failed (HTTP 404).")
    again = update_dialog.UpdateDialog(AppVersionDTO("1.2.0", "1.0.0", "https://x/GEE-Assist.exe",
                                                     update_available=True), facade)
    again.update_button.click()
    assert again.state == "failed" and "current version still works" in again.status.text()
    assert again.update_button.text() == "Try again"
