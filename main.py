"""GEE-Assist entry point. Run with:  python main.py

``GEE-Assist.exe --write-version <file>`` writes the app's version into <file> and exits at
once, without opening a window: the updater uses it to check that a downloaded release starts
and is the version it should be.

While it runs, the app holds the named mutex ``GEE-Assist-Running``: the Setup (see
installer/GEE-Assist.iss) waits for it to go before it replaces the app's files.
"""

import sys

APP_MUTEX = "GEE-Assist-Running"


def _hold_running_mutex():
    """Tell the Setup the app is running (Windows frees the mutex when the process ends)."""
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)


def _write_version(argv: list[str]) -> bool:
    if "--write-version" not in argv:
        return False
    index = argv.index("--write-version")
    from backend.config.version import APP_VERSION

    if index + 1 < len(argv):
        with open(argv[index + 1], "w", encoding="utf-8") as report:
            report.write(APP_VERSION)
    return True


if __name__ == "__main__":
    if _write_version(sys.argv):
        sys.exit(0)
    _running = _hold_running_mutex()   # kept for the life of the app
    from frontend.app import run

    sys.exit(run())
