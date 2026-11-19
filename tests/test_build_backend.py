"""The Cython build of the backend must behave like the Python source.

Cython turns type hints into strict run-time checks unless told not to. In the
packaged app that made every analysis fail with "Expected dict, got _LazyRoles".
These tests generate the C code (no C compiler needed) and look for the check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import build_backend

cython_compiler = pytest.importorskip("Cython.Compiler.Main", reason="Cython is only needed to build the .exe")

ROOT = Path(__file__).resolve().parents[1]
RASTER_ENGINE = ROOT / "backend" / "business" / "analysis" / "raster_engine.py"
TYPE_ERROR = '__Pyx_RaiseUnexpectedTypeError("dict"'


def _generate_c(tmp_path: Path, directives: dict) -> str:
    source = tmp_path / "raster_engine.py"
    source.write_text(RASTER_ENGINE.read_text(encoding="utf-8"), encoding="utf-8")
    options = cython_compiler.CompilationOptions(
        cython_compiler.default_options, compiler_directives=dict(directives), language_level=3,
    )
    result = cython_compiler.compile(str(source), options)
    assert result.num_errors == 0
    return Path(result.c_file).read_text(encoding="utf-8")


def test_type_hints_are_not_turned_into_checks():
    assert build_backend.COMPILER_DIRECTIVES["annotation_typing"] is False


def test_compiled_block_roles_accepts_the_lazy_dict(tmp_path):
    c_code = _generate_c(tmp_path, build_backend.COMPILER_DIRECTIVES)
    assert TYPE_ERROR not in c_code


def test_default_cython_settings_would_reject_it(tmp_path):
    # Guards the test above: it must be able to see the check when it is there.
    c_code = _generate_c(tmp_path, {"language_level": "3"})
    assert TYPE_ERROR in c_code
