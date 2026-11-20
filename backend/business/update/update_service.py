"""Download the new version's installer and start it (the app then quits so it can be replaced)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import httpx

from backend.business.update.i_update_service import IUpdateService
from backend.exceptions import UpdateCancelledError, UpdateError

INSTALLER_NAME = "GEE-Assist-Setup.exe"
_CHUNK = 256 * 1024


def _start_installer(installer: Path) -> None:
    """Start the installer detached from the app.

    ``os.startfile`` goes through the Windows shell, so an installer that needs administrator
    rights shows the UAC prompt; starting it with ``subprocess`` would fail with WinError 740.
    """
    if sys.platform == "win32":
        os.startfile(str(installer))  # noqa: S606 - the installer we just downloaded and checked
    else:
        subprocess.Popen([str(installer)], cwd=str(installer.parent), start_new_session=True)


class UpdateService(IUpdateService):
    def __init__(
        self,
        download_dir: Path | None = None,
        client_factory: Callable[[], httpx.Client] | None = None,
        launcher: Callable[[Path], None] = _start_installer,
    ):
        """``download_dir`` defaults to a GEE-Assist-update folder in the temp folder.
        ``client_factory`` and ``launcher`` are replaced in tests."""
        self._dir = download_dir or Path(tempfile.gettempdir()) / "GEE-Assist-update"
        self._client_factory = client_factory or (
            lambda: httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0))
        )
        self._launcher = launcher

    def download_update(
        self,
        url: str,
        on_progress: Callable[[int, int | None], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Path:
        if not url:
            raise UpdateError("No download address is set for this update.")
        target = self._dir / INSTALLER_NAME
        partial = target.with_name(target.name + ".part")
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._client_factory() as client, client.stream("GET", url) as response:
                if response.status_code == 404:
                    raise UpdateError("The update was not found on the server. Please try again later.")
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0) or None
                received = 0
                with partial.open("wb") as out:
                    for chunk in response.iter_bytes(_CHUNK):
                        if is_cancelled is not None and is_cancelled():
                            raise UpdateCancelledError("The update was cancelled.")
                        out.write(chunk)
                        received += len(chunk)
                        if on_progress is not None:
                            on_progress(received, total)
            self._check_installer(partial, total)
            partial.replace(target)
        except UpdateError:
            partial.unlink(missing_ok=True)
            raise
        except httpx.HTTPError as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError("Could not download the update. Check your internet connection and try again.") from exc
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError(f"Could not save the update: {exc.strerror or exc}") from exc
        return target

    @staticmethod
    def _check_installer(path: Path, total: int | None) -> None:
        size = path.stat().st_size
        if total is not None and size != total:
            raise UpdateError("The update download was incomplete. Please try again.")
        with path.open("rb") as f:
            if f.read(2) != b"MZ":  # every Windows .exe starts with "MZ"
                raise UpdateError("The downloaded update is not a valid installer.")

    def install_update(self, installer: Path) -> None:
        if not installer.is_file():
            raise UpdateError("The downloaded update is missing. Please download it again.")
        try:
            self._launcher(installer)
        except OSError as exc:
            raise UpdateError(f"Could not start the installer: {exc.strerror or exc}") from exc
