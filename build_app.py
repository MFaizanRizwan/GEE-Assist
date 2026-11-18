"""Build the distributable GEE-Assist app (one folder, no Python needed).

Pipeline:
  1. Compile backend/ -> dist/backend/ as .pyd   (build_backend.py)
  2. Stage the app under build/app_stage/:
         main.py        (copied)
         frontend/      (source; bundled as bytecode)
         backend/       (the COMPILED .pyd from dist/backend)
  3. Run PyInstaller on GEE-Assist.spec -> dist/GEE-Assist/ (exe + _internal/)

Your source backend/ is never modified. Distribute the dist/GEE-Assist/ folder
(zip it); the user runs GEE-Assist.exe with no Python installed.

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

    exe = ROOT / "dist" / "GEE-Assist.exe"  # one-file output
    print("\n" + "=" * 60)
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"BUILD OK -> {exe}  ({size_mb:.0f} MB)")
        print("  distribute: upload this single .exe (e.g. GitHub Releases)")
    else:
        print("PyInstaller finished but GEE-Assist.exe was not found - check log above")
    print("=" * 60)


if __name__ == "__main__":
    main()
