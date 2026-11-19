"""Build the distributable GEE-Assist app (one folder, no Python needed).

Pipeline:
  1. Compile backend/ -> dist/backend/ as .pyd   (build_backend.py)
  2. Stage the app under build/app_stage/:
         main.py        (copied)
         frontend/      (source; bundled as bytecode)
         backend/       (the COMPILED .pyd from dist/backend)
  3. Run PyInstaller on GEE-Assist.spec -> dist/GEE-Assist/ (exe + _internal/)
  4. Zip that folder -> dist/GEE-Assist-<version>-win64.zip
  5. Inno Setup installer -> dist/GEE-Assist-Setup-<version>.exe (installer/GEE-Assist.iss)

Your source backend/ is never modified. Distribute the installer, or the zip
(the user extracts it and runs GEE-Assist.exe). No Python is needed on the
user's PC.

Why one folder and not one .exe: a one-file .exe unpacks ~6,000 files into
%TEMP% on every start and Microsoft Defender scans them all each time (high
CPU, slow start). See GEE-Assist.spec.

Requirements: see requirements-build.txt.

Usage:
    python build_app.py            # full build
    python build_app.py --no-backend   # reuse existing dist/backend, just repackage
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "build" / "app_stage"
DIST_BACKEND = ROOT / "dist" / "backend"
SPEC = ROOT / "GEE-Assist.spec"
PY = sys.executable


def _patch_dis_3100() -> None:
    """Work around a bug in Python 3.10.0's `dis` module.

    `dis._get_const_info` raises IndexError on some bytecode (e.g. in the
    opentelemetry/googleapiclient deps pulled in by earthengine-api), which
    crashes PyInstaller's analysis. Fixed in CPython 3.10.1+. We make the
    function tolerant so the build can proceed on 3.10.0. Only affects the
    repr/argval used for display, not which modules get bundled.
    """
    import dis

    if sys.version_info[:3] != (3, 10, 0):
        return
    _orig = dis._get_const_info

    def _safe(const_index, const_list):  # type: ignore[no-untyped-def]
        try:
            return _orig(const_index, const_list)
        except IndexError:
            return (None, "None")

    dis._get_const_info = _safe
    print("  [patched Python 3.10.0 dis._get_const_info]")


def run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0:
        raise SystemExit(f"step failed ({res.returncode}): {' '.join(cmd)}")


def main() -> None:
    skip_backend = "--no-backend" in sys.argv

    # 1. Compile backend -> dist/backend (.pyd)
    if not skip_backend:
        run([PY, str(ROOT / "build_backend.py")])
    if not DIST_BACKEND.is_dir() or not any(DIST_BACKEND.rglob("*.pyd")):
        raise SystemExit("dist/backend missing or has no .pyd - run without --no-backend")

    # 2. Stage the app
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    shutil.copy2(ROOT / "main.py", STAGE / "main.py")
    shutil.copytree(ROOT / "frontend", STAGE / "frontend")
    shutil.copytree(DIST_BACKEND, STAGE / "backend")
    # strip any stray bytecode caches from the staged copies
    for cache in STAGE.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    print(f"staged app at {STAGE}")

    # 3. PyInstaller (run in-process so we can patch the Python 3.10.0 `dis` bug
    #    that otherwise crashes PyInstaller's analysis of the ee/google deps).
    _patch_dis_3100()
    import PyInstaller.__main__

    print("\n$ PyInstaller --noconfirm --clean GEE-Assist.spec  (with dis 3.10.0 patch)")
    PyInstaller.__main__.run(["--noconfirm", "--clean", str(SPEC)])

    app_dir = ROOT / "dist" / "GEE-Assist"  # one-folder output
    exe = app_dir / "GEE-Assist.exe"
    print("\n" + "=" * 60)
    if not exe.exists():
        print("PyInstaller finished but GEE-Assist.exe was not found - check log above")
        print("=" * 60)
        raise SystemExit(1)

    # 4. Zip the folder for distribution.
    zip_base = ROOT / "dist" / f"GEE-Assist-{_app_version()}-win64"
    archive = Path(shutil.make_archive(str(zip_base), "zip", root_dir=app_dir.parent, base_dir=app_dir.name))
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"BUILD OK -> {exe}")
    print(f"  distribute: {archive}  ({size_mb:.0f} MB)")
    print(r"  the user extracts it and runs GEE-Assist\GEE-Assist.exe")

    # 5. Installer (Inno Setup), if it is installed.
    iscc = _find_iscc()
    if iscc is None:
        print("  installer skipped: Inno Setup not found (winget install JRSoftware.InnoSetup)")
    else:
        cmd = [str(iscc), f"/DAppVersion={_app_version()}", f"/DSourceDir={app_dir}",
               f"/O{ROOT / 'dist'}", str(ROOT / "installer" / "GEE-Assist.iss")]
        # Defender scans the new Setup.exe while Inno Setup is still writing its
        # icon, which can fail with "EndUpdateResource failed"; a retry succeeds.
        for attempt in range(3):
            print(f"\n$ {' '.join(cmd)}")
            if subprocess.run(cmd, cwd=str(ROOT)).returncode == 0:
                break
            print("  installer step failed (often a virus scan holding the file); retrying ...")
        else:
            raise SystemExit("installer step failed 3 times - see the Inno Setup output above")
        setup = ROOT / "dist" / f"GEE-Assist-Setup-{_app_version()}.exe"
        print(f"  installer : {setup}  ({setup.stat().st_size / (1024 * 1024):.0f} MB)")
    print("=" * 60)


def _find_iscc() -> Path | None:
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    import os

    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        for sub in ("Programs/Inno Setup 6", "Inno Setup 6"):
            candidate = Path(base) / sub / "ISCC.exe"
            if base and candidate.exists():
                return candidate
    return None


def _app_version() -> str:
    for line in (ROOT / "backend" / "config" / "version.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "0.0.0"


if __name__ == "__main__":
    main()
