"""The analysis engine must still work when the packaged app compiles it with Cython.

Cython turns some type hints into strict run-time checks: a ``-> dict`` hint
rejects dict subclasses. ``Block.roles`` returns ``_LazyRoles`` (a dict
subclass), so with a ``dict`` hint every analysis in the .exe failed with
"Expected dict, got _LazyRoles". These tests generate the C code with Cython's
default settings (no C compiler needed) and look for that check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cython_compiler = pytest.importorskip("Cython.Compiler.Main", reason="Cython is only needed to build the .exe")

RASTER_ENGINE = Path(__file__).resolve().parents[1] / "backend" / "business" / "analysis" / "raster_engine.py"
DICT_CHECK = '__Pyx_RaiseUnexpectedTypeError("dict"'


def _generate_c(tmp_path: Path, source_text: str) -> str:
    source = tmp_path / "raster_engine.py"
    source.write_text(source_text, encoding="utf-8")
    options = cython_compiler.CompilationOptions(cython_compiler.default_options, language_level=3)
    result = cython_compiler.compile(str(source), options)
    assert result.num_errors == 0
    return Path(result.c_file).read_text(encoding="utf-8")


def test_compiled_block_roles_accepts_the_lazy_dict(tmp_path):
    assert DICT_CHECK not in _generate_c(tmp_path, RASTER_ENGINE.read_text(encoding="utf-8"))


def test_a_dict_hint_would_reject_it(tmp_path):
    # Guards the test above: it must be able to see the check when it is there.
    source = RASTER_ENGINE.read_text(encoding="utf-8")
    broken = source.replace("def roles(self, period: int = -1) -> Mapping[str, Any]:",
                            "def roles(self, period: int = -1) -> dict[str, Any]:")
    assert broken != source
    assert DICT_CHECK in _generate_c(tmp_path, broken)
