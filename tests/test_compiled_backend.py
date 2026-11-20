"""The backend must still work when the packaged app compiles it with Cython.

Cython turns some type hints into strict run-time checks: a ``-> dict`` hint
rejects dict subclasses and a ``text: str`` parameter rejects None. Code that
works in Python can then fail only in the .exe (for example every analysis
failed with "Expected dict, got _LazyRoles"). These tests generate the C code
with Cython's default settings (no C compiler needed) and look for the checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cython_compiler = pytest.importorskip("Cython.Compiler.Main", reason="Cython is only needed to build the .exe")

BACKEND = Path(__file__).resolve().parents[1] / "backend"
RASTER_ENGINE = BACKEND / "business" / "analysis" / "raster_engine.py"
REQUEST_SERVICE = BACKEND / "business" / "request" / "request_service.py"
BUSINESS_FACADE = BACKEND / "business" / "facade" / "business_facade.py"
DICT_CHECK = '__Pyx_RaiseUnexpectedTypeError("dict"'


def _generate_c(tmp_path: Path, source_text: str) -> str:
    source = tmp_path / "module.py"
    source.write_text(source_text, encoding="utf-8")
    options = cython_compiler.CompilationOptions(cython_compiler.default_options, language_level=3)
    result = cython_compiler.compile(str(source), options)
    assert result.num_errors == 0
    return Path(result.c_file).read_text(encoding="utf-8")


def _text_must_be_str(c_code: str) -> bool:
    """True if the compiled submit_query refuses a text that is not a str (None included)."""
    return '__Pyx_ArgTypeTest(((PyObject *)__pyx_v_text), (&PyUnicode_Type), 0, "text", 2)' in c_code


def test_compiled_block_roles_accepts_the_lazy_dict(tmp_path):
    assert DICT_CHECK not in _generate_c(tmp_path, RASTER_ENGINE.read_text(encoding="utf-8"))


def test_a_dict_hint_would_reject_it(tmp_path):
    # Guards the test above: it must be able to see the check when it is there.
    source = RASTER_ENGINE.read_text(encoding="utf-8")
    broken = source.replace("def roles(self, period: int = -1) -> Mapping[str, Any]:",
                            "def roles(self, period: int = -1) -> dict[str, Any]:")
    assert broken != source
    assert DICT_CHECK in _generate_c(tmp_path, broken)


@pytest.mark.parametrize("path", [REQUEST_SERVICE, BUSINESS_FACADE], ids=lambda p: p.stem)
def test_compiled_submit_query_accepts_no_text(tmp_path, path):
    # None must reach the "Please describe the data you need" message, not a TypeError.
    assert not _text_must_be_str(_generate_c(tmp_path, path.read_text(encoding="utf-8")))


def test_a_str_hint_would_refuse_no_text(tmp_path):
    source = REQUEST_SERVICE.read_text(encoding="utf-8")
    broken = source.replace("def submit_query(self, text: str | None)", "def submit_query(self, text: str)")
    assert broken != source
    assert _text_must_be_str(_generate_c(tmp_path, broken))
