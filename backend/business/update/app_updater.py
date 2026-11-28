"""Update the packaged app in place: download the new GEE-Assist.exe, check it, swap it in.

Users have only the .exe (PyInstaller one-file build; the Cython-compiled backend is inside
it), placed in any folder under any name. Updating replaces that exact file:

1. Download the new .exe from the release's direct download URL (with progress, cancellable),
   next to the running one when that folder is writable, else in the temp folder.
2. Check it before touching anything: it is a Windows program ("MZ"), matches the release's
   SHA-256 when the server gives one, and actually starts and reports the expected version
   (``GEE-Assist.exe --write-version <file>``, see ``main.py``). A broken or wrong download
   never replaces a working app.
3. Swap. Windows lets a running .exe be renamed (not overwritten), so the running one becomes
   ``<name>.old``, the new one takes its exact path, and the app restarts from there; if the
   move fails, the old one is put back. In a folder the user cannot write to (e.g. Program
   Files), a small helper started with administrator rights (one UAC prompt) waits for the
   app to close, moves the new .exe in, and starts it.
4. On the next start, the leftover ``.old`` file is deleted.

User data is not in the app's folder (it is in %APPDATA%\\GEE-Assist), so settings, projects
and the signed-in session survive the update.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from backend.exceptions import UpdateError

MIN_SIZE = 1_000_000              # a real build is hundreds of MB; anything tiny is an error page
UNPACK_FACTOR = 4                 # a one-file .exe unpacks to about this many times its size when it starts
VERIFY_TIMEOUT_S = 240            # the one-file exe unpacks itself before it can answer
CHUNK = 1 << 20


def parse_version(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def is_newer(candidate: str, current: str) -> bool:
    a, b = list(parse_version(candidate)), list(parse_version(current))
    width = max(len(a), len(b))
    return a + [0] * (width - len(a)) > b + [0] * (width - len(b))


def same_version(a: str, b: str) -> bool:
    return not is_newer(a, b) and not is_newer(b, a)


class AppUpdater:
    def __init__(self, executable: Path | None = None, frozen: bool | None = None, http=None):
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.executable = Path(executable or sys.executable).resolve()
        self._http = http   # an httpx.Client (tests pass one with a mock transport)

    # ------------------------------------------------------------- can it?
    def can_self_update(self) -> bool:
        """Only the packaged app can replace itself (from source, there is no .exe to swap)."""
        return self.frozen and self.executable.suffix.lower() == ".exe" and self.executable.is_file()

    def folder_writable(self) -> bool:
        probe = self.executable.parent / f".gee-assist-write-test-{os.getpid()}"
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
        """Download and check the new .exe; returns its path (ready for ``install``)."""
        if not url:
            raise UpdateError("This release has no download link.")
        folder = self.executable.parent if self.folder_writable() else Path(tempfile.gettempdir()) / "GEE-Assist-update"
        folder.mkdir(parents=True, exist_ok=True)
        self._check_space(folder, self.executable.stat().st_size if self.executable.is_file() else 0)
        partial = folder / f"{self.executable.stem}-{expected_version}.download"
        target = folder / f"{self.executable.stem}-{expected_version}.new.exe"
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
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        try:
            self.verify_runs(target, expected_version, unpack_in=folder)
        except Exception:
            target.unlink(missing_ok=True)       # only ever the file this download made
            raise
        return target

    @staticmethod
    def _check_space(folder: Path, size_hint: int) -> None:
        """Enough room to download the new .exe and let it unpack once for the check."""
        import shutil

        need = max(size_hint, 600_000_000) * (1 + UNPACK_FACTOR)
        free = shutil.disk_usage(folder).free
        if free < need:
            raise UpdateError(f"Not enough free space on the drive of {folder} to update ({free / 1e9:.1f} GB free, "
                              f"about {need / 1e9:.1f} GB needed for a moment). Free some space and try again. "
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

    def verify_runs(self, path: Path, expected_version: str, unpack_in: Path | None = None) -> None:
        """Start the new .exe just long enough to report its version: it must run, and be that version.

        Never deletes anything (the caller removes a download that fails). The one-file .exe
        unpacks itself into its temp folder as it starts; that folder is ``unpack_in`` (the
        download folder) rather than the system temp folder, which may be on a full C: drive."""
        scratch = Path(unpack_in or Path(path).parent) / f".gee-assist-check-{os.getpid()}"
        scratch.mkdir(parents=True, exist_ok=True)
        report = scratch / "version.txt"
        env = dict(os.environ, TEMP=str(scratch), TMP=str(scratch))
        try:
            subprocess.run([str(path), "--write-version", str(report)], timeout=VERIFY_TIMEOUT_S, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            reported = report.read_text(encoding="utf-8").strip() if report.exists() else ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f"The downloaded program does not start ({exc}). Nothing was changed.") from exc
        finally:
            import shutil

            shutil.rmtree(scratch, ignore_errors=True)
        if not reported:
            raise UpdateError("The downloaded program did not start and report its version (it may be damaged, "
                              "or the drive too full for it to unpack). Nothing was changed.")
        if not same_version(reported, expected_version):
            raise UpdateError(f"The download is version {reported}, not {expected_version} as published. "
                              "Nothing was changed.")

    # ------------------------------------------------------------- 3: swap
    def install(self, new_file: Path) -> str:
        """Put ``new_file`` in place of the running .exe. Returns "swapped" (restart the app from
        ``self.executable`` now) or "elevated" (quit now: the admin helper finishes the swap)."""
        new_file = Path(new_file)
        if not self.can_self_update():
            raise UpdateError("Only the installed GEE-Assist.exe can update itself.")
        if not new_file.is_file():
            raise UpdateError("The downloaded update is missing; download it again.")
        if self.folder_writable() and new_file.parent == self.executable.parent:
            return self._swap(new_file)
        return self._swap_elevated(new_file)

    def _swap(self, new_file: Path) -> str:
        exe = self.executable
        old = exe.with_name(exe.name + ".old")
        try:
            old.unlink(missing_ok=True)
        except OSError:   # an older leftover still locked: use another name
            old = exe.with_name(f"{exe.name}.{int(time.time())}.old")
        exe.rename(old)                 # allowed while it runs
        try:
            new_file.replace(exe)
        except OSError as exc:
            old.rename(exe)             # put the working app back
            raise UpdateError(f"The new version could not be put in place: {exc}. Nothing was changed.") from exc
        return "swapped"

    def _swap_elevated(self, new_file: Path) -> str:
        """A folder the user cannot write to: a PowerShell helper, run as administrator, waits for
        this process to end, moves the new .exe in (retrying while files are still locked) and
        starts it."""
        script = Path(tempfile.gettempdir()) / f"gee-assist-update-{os.getpid()}.ps1"
        script.write_text(helper_script(os.getpid(), new_file, self.executable), encoding="utf-8")
        if sys.platform != "win32":
            raise UpdateError("Updating needs Windows.")
        import ctypes

        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "powershell.exe",
            f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}"', None, 0)
        if result <= 32:   # the user said no to the administrator prompt, or it failed
            raise UpdateError("Updating this folder needs administrator permission, which was not given. "
                              "Nothing was changed.")
        return "elevated"

    # ------------------------------------------------------------- 4: tidy up
    def cleanup(self) -> None:
        """Delete what an earlier update left behind (the old .exe, partial downloads)."""
        if not self.frozen:
            return
        folder = self.executable.parent
        patterns = (f"{self.executable.name}*.old", f"{self.executable.stem}-*.download",
                    f"{self.executable.stem}-*.new.exe")
        for pattern in patterns:
            for leftover in folder.glob(pattern):
                try:
                    leftover.unlink()
                except OSError:
                    pass   # the old process may still be closing; next start tries again


def helper_script(pid: int, new_file: Path, executable: Path) -> str:
    """The PowerShell steps the administrator helper runs."""
    def quoted(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    return f"""$ErrorActionPreference = 'Stop'
$new = {quoted(new_file)}
$exe = {quoted(executable)}
try {{ Wait-Process -Id {pid} -Timeout 120 }} catch {{ }}
$ok = $false
for ($i = 0; $i -lt 60 -and -not $ok; $i++) {{
    try {{ Move-Item -LiteralPath $new -Destination $exe -Force; $ok = $true }}
    catch {{ Start-Sleep -Milliseconds 500 }}
}}
Start-Process -FilePath $exe
"""


def _default_client():
    import httpx

    return httpx.Client(headers={"User-Agent": "GEE-Assist-Updater"})
