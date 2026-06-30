"""Tests for the compile pipeline: ``.npl`` source -> validated sibling ``.py``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nplc.cli import main
from nplc.compiler import compile_file
from nplc.translator import StubTranslator, Translator
from nplc.unit import CompileError, FunctionUnit, parse_source

SINGLE_FUNCTION = "add(a, b):\n    return the sum of\n    the two arguments\n"


def test_cli_compiles_single_function_to_valid_python(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real CLI entry point writes an ``ast``-valid sibling ``.py``."""
    source = tmp_path / "one_fn.npl"
    source.write_text(SINGLE_FUNCTION)

    exit_code = main([str(source)])

    assert exit_code == 0
    target = tmp_path / "one_fn.py"
    assert target.exists()
    ast.parse(target.read_text())  # raises SyntaxError if the output is invalid
    assert str(target) in capsys.readouterr().out


def test_parse_source_extracts_signature_and_body() -> None:
    unit = parse_source(SINGLE_FUNCTION)

    assert unit.signature == "add(a, b)"
    assert unit.name == "add"
    assert "the two arguments" in unit.body


def test_parse_source_rejects_missing_signature() -> None:
    with pytest.raises(CompileError):
        parse_source("just some prose with no signature\n")


def test_stub_translator_emits_valid_named_function() -> None:
    unit = FunctionUnit(signature="add(a, b)", body="return the sum")

    python_source = StubTranslator().translate(unit)

    tree = ast.parse(python_source)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "add"
        for node in ast.walk(tree)
    )


def test_stub_translator_is_deterministic() -> None:
    unit = FunctionUnit(signature="add(a, b)", body="return the sum")

    assert StubTranslator().translate(unit) == StubTranslator().translate(unit)


def test_stub_translator_satisfies_translator_protocol() -> None:
    assert isinstance(StubTranslator(), Translator)


def test_compile_rejects_unparseable_python_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """When the adapter returns invalid Python, compile fails and writes no file."""

    class BrokenTranslator:
        def translate(self, unit: FunctionUnit) -> str:
            return "def (this is not python:::"

    source = tmp_path / "broken.npl"
    source.write_text(SINGLE_FUNCTION)

    with pytest.raises(CompileError):
        compile_file(source, BrokenTranslator())

    assert not (tmp_path / "broken.py").exists()
