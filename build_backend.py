"""Compile the backend into binary .pyd extensions for distribution.

What it does
------------
Reads from ``backend/`` (your source of truth, NEVER modified) and produces
``dist/backend/`` where every module is a compiled ``.pyd`` binary instead of a
readable ``.py``. The folder layout is preserved exactly, so imports such as
``from backend.business.facade import IBusinessFacade`` keep working and the
``Path(__file__).resolve().parents[2]`` logic in ``backend/config`` still
resolves to the project root.

``__init__.py`` package markers are kept as source (they only declare the
package; compiling them is fragile and they expose nothing worth protecting).

Usage
-----
    python build_backend.py

Requirements
------------
- Cython + setuptools + wheel  (pip install cython setuptools wheel)
- MSVC C++ Build Tools (Desktop development with C++)

After it runs, ``dist/backend/`` is the protected backend. Your own
``backend/`` folder is untouched, so you keep developing in normal Python and
only run this at release time.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "backend"
DIST = ROOT / "dist"
OUT = DIST / "backend"
WORK = ROOT / "build" / "cython"  # scratch for generated .c / .obj

# Files kept as plain .py in the output (not compiled).
KEEP_AS_PY = {"__init__.py"}

# How Cython compiles the backend.
#
# annotation_typing=False: type hints stay hints, as in normal Python. By
# default Cython turns hints such as ``-> dict`` or ``x: list`` into strict
# run-time checks that reject subclasses and other compatible types. In the
# compiled app that broke every analysis with "Expected dict, got _LazyRoles"
# (``Block.roles`` returns a dict subclass), and about a thousand other checks
# like it could fail the same way. Without them the compiled backend behaves
# exactly like the Python source that the tests run against.
COMPILER_DIRECTIVES = {
    "language_level": "3",
    "annotation_typing": False,
}


def _fail(msg: str) -> "None":
    print(f"\nERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not SRC.is_dir():
        _fail(f"backend/ not found at {SRC}")

    try:
        from Cython.Build import cythonize
        from setuptools import Distribution, Extension
    except ImportError:
        _fail("Cython/setuptools missing. Run: pip install cython setuptools wheel")

    # 1. Clean previous output.
    if OUT.exists():
        shutil.rmtree(OUT)
    if WORK.exists():
        shutil.rmtree(WORK)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    # 2. Copy the whole backend tree into dist/ (so structure, __init__.py and
    #    any non-.py resources are preserved). We compile this copy in place.
    shutil.copytree(SRC, OUT)

    # 3. Collect modules to compile (everything except kept-as-py markers).
    py_files = sorted(p for p in OUT.rglob("*.py") if p.name not in KEEP_AS_PY)
    if not py_files:
        _fail("no .py modules found to compile")

    extensions = []
    for path in py_files:
        rel = path.relative_to(DIST)  # e.g. backend/config/settings.py
        dotted = ".".join(rel.with_suffix("").parts)  # backend.config.settings
        extensions.append(Extension(dotted, [str(path)]))

    print(f"Cythonizing {len(extensions)} backend modules ...")
    ext_modules = cythonize(
        extensions,
        build_dir=str(WORK),  # generated .c files go here, not into dist/
        compiler_directives=COMPILER_DIRECTIVES,
        quiet=True,
    )

    # 4. Compile the generated C into .pyd, placed next to each source module
    #    inside dist/backend (build_ext --inplace, run with cwd=dist).
    dist_obj = Distribution({"ext_modules": ext_modules, "script_name": "build_backend.py"})
    dist_obj.script_args = [
        "build_ext",
        "--inplace",
        "--build-temp",
        str(WORK),
    ]
    import os

    prev_cwd = os.getcwd()
    os.chdir(DIST)  # --inplace resolves dotted names relative to cwd
    try:
        dist_obj.parse_command_line()
        if not dist_obj.run_commands():
            pass
    finally:
        os.chdir(prev_cwd)

    # 5. Remove the readable sources and build leftovers from dist/backend,
    #    leaving only .pyd binaries (+ kept __init__.py).
    removed = 0
    for path in list(OUT.rglob("*.py")):
        if path.name in KEEP_AS_PY:
            continue
        # Only delete a .py if its compiled .pyd actually exists beside it.
        stem = path.with_suffix("")
        pyd_exists = any(stem.parent.glob(stem.name + "*.pyd"))
        if pyd_exists:
            path.unlink()
            removed += 1
        else:
            _fail(f"no .pyd produced for {path.relative_to(DIST)} - aborting so no source is lost")

    for junk in list(OUT.rglob("*.c")):
        junk.unlink()
    for cache in list(OUT.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)

    pyd_count = sum(1 for _ in OUT.rglob("*.pyd"))
    leftover_py = sorted(
        p.relative_to(OUT).as_posix()
        for p in OUT.rglob("*.py")
        if p.name not in KEEP_AS_PY
    )

    print("\nDone.")
    print(f"  compiled .pyd modules : {pyd_count}")
    print(f"  sources removed       : {removed}")
    print(f"  kept as .py (markers) : {sum(1 for _ in OUT.rglob('__init__.py'))}")
    if leftover_py:
        print(f"  WARNING leftover .py  : {leftover_py}")
    print(f"\nProtected backend is at: {OUT}")
    print("Your source backend/ was not modified.")


if __name__ == "__main__":
    main()
