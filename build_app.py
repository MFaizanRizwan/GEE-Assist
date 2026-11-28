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
    python build_app.py --version 1.1.0   # a release: stamps the version, then builds
    python build_app.py                   # rebuild the version already in backend/config/version.py
    python build_app.py --no-backend      # reuse existing dist/backend, just repackage

Releasing an update (the app updates itself from it):
  1. python build_app.py --version X.Y.Z   (always a higher number than the last release)
  2. Upload dist/GEE-Assist.exe as a release asset, e.g. on GitHub Releases.
  3. In the admin version settings, set latest_version = X.Y.Z, download_url = the *direct* link
     to the .exe asset (…/releases/download/vX.Y.Z/GEE-Assist.exe, not the release page), and
     sha256 = the value printed below / in dist/GEE-Assist.exe.sha256.
The version is compiled into the backend (Cython), so it must be stamped before the build:
an .exe built without raising it would report the old number forever.
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


VERSION_FILE = ROOT / "backend" / "config" / "version.py"


def stamp_version(argv: list[str]) -> str:
    """Write ``--version X.Y.Z`` into backend/config/version.py (before the backend is compiled);
    returns the version the build will carry."""
    import re

    current = re.search(r'APP_VERSION = "([^"]+)"', VERSION_FILE.read_text(encoding="utf-8")).group(1)
    if "--version" not in argv:
        print(f"Building version {current} (no --version given: the number is not raised).")
        return current
    index = argv.index("--version")
    if index + 1 >= len(argv) or not re.fullmatch(r"\d+(\.\d+){1,3}", argv[index + 1]):
        raise SystemExit("--version needs a number like 1.2.0")
    new = argv[index + 1]
    as_tuple = lambda text: tuple(int(p) for p in text.split("."))  # noqa: E731
    if as_tuple(new) < as_tuple(current):
        raise SystemExit(f"--version {new} is lower than the current {current}: users would never be offered it.")
    text = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(text.replace(f'APP_VERSION = "{current}"', f'APP_VERSION = "{new}"'), encoding="utf-8")
    print(f"Version {current} -> {new} (backend/config/version.py)")
    return new


def main() -> None:
    skip_backend = "--no-backend" in sys.argv
    version = stamp_version(sys.argv)
    if skip_backend and "--version" in sys.argv:
        raise SystemExit("--version needs the backend recompiled (the number is inside it): drop --no-backend")

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
        import hashlib

        digest = hashlib.sha256()
        with open(exe, "rb") as built:
            for block in iter(lambda: built.read(1 << 20), b""):
                digest.update(block)
        sha = digest.hexdigest()
        (exe.parent / (exe.name + ".sha256")).write_text(f"{sha}  {exe.name}\n", encoding="utf-8")
        print(f"BUILD OK -> {exe}  ({size_mb:.0f} MB), version {version}")
        print(f"  sha256: {sha}")
        print("  distribute: upload this single .exe (e.g. GitHub Releases); set the version, the direct")
        print("  download link and this sha256 in the admin version settings (see the top of build_app.py)")
    else:
        print("PyInstaller finished but GEE-Assist.exe was not found - check log above")
    print("=" * 60)


if __name__ == "__main__":
    main()
