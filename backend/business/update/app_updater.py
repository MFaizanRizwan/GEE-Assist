"""Update the installed app: download the new version's Setup, check it, run it over the app.

The app ships as an installer (``GEE-Assist-Setup-X.Y.Z.exe``, Inno Setup, see
``installer/GEE-Assist.iss``) that installs a folder: per user into
``%LOCALAPPDATA%\\Programs\\GEE-Assist`` by default, no administrator rights needed. Updating:

1. Download the release's Setup from its direct download URL (with progress, cancellable)
   into the temp folder, after checking there is room for it and for the installed app.
2. Check it before anything is changed: a Windows program ("MZ"), not tiny, the release's
   SHA-256 when the server gives one, and the version stamped in the Setup's file properties
   is the version announced. A wrong or damaged download never runs.
3. Start the Setup silently (``/VERYSILENT``) for the folder this app runs from, then quit.
   The Setup waits for the app to close, replaces the app's files, and starts the new version.
   If that folder is shared by all users (Program Files), the Setup asks Windows for
   administrator rights once.
4. On the next start, older downloaded Setups are deleted.

User data is not in the app's folder (it is in %APPDATA%\\GEE-Assist), so settings, projects
and the signed-in session survive the update.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from backend.exceptions import UpdateError

MIN_SIZE = 1_000_000              # a real Setup is hundreds of MB; anything tiny is an error page
UNPACK_FACTOR = 4                 # the installed app is about this many times the size of its Setup
CHUNK = 1 << 20
DOWNLOAD_FOLDER = "GEE-Assist-update"
SETUP_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/RELAUNCH=1")


def parse_version(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    a, b = list(parse_version(candidate)), list(parse_version(current))
    width = max(len(a), len(b))
    return a + [0] * (width - len(a)) > b + [0] * (width - len(b))


def same_version(a: str, b: str) -> bool:
    return not is_newer(a, b) and not is_newer(b, a)


def file_version(path: Path) -> str:
    """The version in a Windows program's file properties ("" when it has none)."""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ""
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        return ""
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)) or not length.value:
        return ""
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents   # VS_FIXEDFILEINFO
    ms, ls = words[2], words[3]   # dwFileVersionMS, dwFileVersionLS
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


class AppUpdater:
    def __init__(self, executable: Path | None = None, frozen: bool | None = None, http=None,
                 version_of: Callable[[Path], str] = file_version, download_root: Path | None = None,
                 launch: Callable[[list[str]], None] | None = None):
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.executable = Path(executable or sys.executable).resolve()
        self._http = http                    # an httpx.Client (tests pass one with a mock transport)
        self._version_of = version_of        # reads the Setup's version (tests pass a stand-in)
        self._download_root = Path(download_root or tempfile.gettempdir()) / DOWNLOAD_FOLDER
        self._launch = launch or _start_detached

    @property
    def app_folder(self) -> Path:
        return self.executable.parent

    # ------------------------------------------------------------- can it?
    def can_self_update(self) -> bool:
        """Only the packaged app updates itself (from source there is nothing to install over)."""
        return self.frozen and self.executable.suffix.lower() == ".exe" and self.executable.is_file()

    def folder_writable(self) -> bool:
        probe = self.app_folder / f".gee-assist-write-test-{os.getpid()}"
        try:
            probe.write_bytes(b"")
            probe.unlink()
            return True
        except OSError:
            return False

    # ------------------------------------------------------------- 1-2: download and check
    def download(self, url: str, expected_version: str, sha256: str | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> Path:
        """Download and check the new version's Setup; returns its path (ready for ``install``)."""
        if not url:
            raise UpdateError("This release has no download link.")
        folder = self._download_root
        folder.mkdir(parents=True, exist_ok=True)
        partial = folder / f"GEE-Assist-Setup-{expected_version}.download"
        target = folder / f"GEE-Assist-Setup-{expected_version}.exe"
        for leftover in (partial, target):
            leftover.unlink(missing_ok=True)
        digest = hashlib.sha256()
        client = self._http or _default_client()
        try:
            with client.stream("GET", url, follow_redirects=True, timeout=60) as response:
                if response.status_code >= 400:
                    raise UpdateError(f"The download failed (HTTP {response.status_code}).")
                kind = response.headers.get("content-type", "")
                if "text/html" in kind:
                    raise UpdateError("The download link opens a web page, not the program.", web_page=True)
                total = int(response.headers.get("content-length") or 0)
                self._check_space(folder, total)
                done = 0
                with open(partial, "wb") as out:
                    for chunk in response.iter_bytes(CHUNK):
                        if cancelled is not None and cancelled():
                            raise UpdateError("Update cancelled.")
                        out.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, total)
        except UpdateError:
            partial.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001 - any network failure
            partial.unlink(missing_ok=True)
            raise UpdateError(f"The download failed: {exc}") from exc
        finally:
            if self._http is None:
                client.close()
        try:
            self._check_file(partial, digest.hexdigest(), sha256)
            self._check_version(partial, expected_version)
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)      # only ever the file this download made
            raise
        return target

    def _check_space(self, folder: Path, setup_size: int) -> None:
        """Room for the Setup where it is downloaded, and for the installed app where it goes."""
        size = max(setup_size, 600_000_000)
        needs = [(folder, size), (self.app_folder, size * UNPACK_FACTOR)]
        for place, need in needs:
            try:
                free = shutil.disk_usage(place).free
            except OSError:
                continue
            if free < need:
                raise UpdateError(f"Not enough free space on the drive of {place} to update ({free / 1e9:.1f} GB "
                                  f"free, about {need / 1e9:.1f} GB needed). Free some space and try again. "
                                  "Nothing was changed.")

    @staticmethod
    def _check_file(path: Path, actual_sha256: str, expected_sha256: str | None) -> None:
        size = path.stat().st_size
        with open(path, "rb") as file:
            head = file.read(2)
        if head != b"MZ":
            raise UpdateError("The download is not a Windows program (the link may point to a page).",
                              web_page=True)
        if size < MIN_SIZE:
            raise UpdateError(f"The download is too small ({size:,} bytes) to be GEE-Assist.")
        if expected_sha256 and actual_sha256.lower() != expected_sha256.strip().lower():
            raise UpdateError("The download is damaged or not the published release (its SHA-256 does not "
                              "match). Nothing was changed.")

    def _check_version(self, path: Path, expected_version: str) -> None:
        """The Setup carries its version in its file properties: it must be the version announced."""
        found = self._version_of(path)
        if not found:
            raise UpdateError("The download is not a GEE-Assist Setup (it carries no version). Nothing was changed.")
        if not same_version(found, expected_version):
            raise UpdateError(f"The download is version {_short(found)}, not {expected_version} as published. "
                              "Nothing was changed.")

    # ------------------------------------------------------------- 3: install
    def setup_command(self, setup: Path) -> list[str]:
        """Run the Setup silently over this app's folder, then start the new version. A folder the
        user cannot write to (installed for all users) needs the Setup's all-users mode, for which
        Windows asks for administrator rights."""
        scope = "/CURRENTUSER" if self.folder_writable() else "/ALLUSERS"
        log = self._download_root / "setup.log"
        return [str(setup), *SETUP_ARGS, scope, f"/DIR={self.app_folder}", f"/LOG={log}"]

    def install(self, setup: Path) -> str:
        """Start the Setup; returns "installing": quit the app now (the Setup waits for it)."""
        setup = Path(setup)
        if not self.can_self_update():
            raise UpdateError("Only the installed GEE-Assist can update itself.")
        if not setup.is_file():
            raise UpdateError("The downloaded update is missing; download it again.")
        try:
            self._launch(self.setup_command(setup))
        except OSError as exc:
            raise UpdateError(f"The update could not be started: {exc}. Nothing was changed.") from exc
        return "installing"

    # ------------------------------------------------------------- 4: tidy up
    def cleanup(self) -> None:
        """Delete Setups an earlier update downloaded (never the running app's files)."""
        if not self.frozen or not self._download_root.is_dir():
            return
        for pattern in ("GEE-Assist-Setup-*.exe", "GEE-Assist-Setup-*.download"):
            for leftover in self._download_root.glob(pattern):
                try:
                    leftover.unlink()
                except OSError:
                    pass   # the Setup may still be running; the next start tries again


def _short(version: str) -> str:
    """1.2.0.0 -> 1.2.0 (the Setup's file properties always have four numbers)."""
    parts = version.split(".")
    while len(parts) > 3 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _start_detached(command: list[str]) -> None:
    """Start the Setup on its own, so it keeps running after the app quits."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(command, creationflags=flags, close_fds=True)


def _default_client():
    import httpx

    return httpx.Client(headers={"User-Agent": "GEE-Assist-Updater"})
