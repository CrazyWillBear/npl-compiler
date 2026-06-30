"""Tests for the compile pipeline: ``.npl`` source -> validated sibling ``.py``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nplc.cli import main
from nplc.compiler import compile_file
from nplc.translator import StubTranslator, Translator
from nplc.unit import (
    DELIMITER_KEYWORDS,
    CompileError,
    FunctionUnit,
    PreambleUnit,
    Unit,
    parse_source,
)

SINGLE_FUNCTION = "add(a, b):\n    return the sum of\n    the two arguments\n"

# A mix of delimiter synonyms (def / function / algorithm) with control-flow
# keywords (if / for / while) living *inside* the first function's body.
MULTI_FUNCTION = (
    "def is_even(n):\n"
    "    if n is divisible by two:\n"
    "        return true\n"
    "    for each remainder check:\n"
    "        keep checking\n"
    "    while still unsure:\n"
    "        keep going\n"
    "    otherwise return false\n"
    "\n"
    "function double(x):\n"
    "    return x added to itself\n"
    "\n"
    "algorithm main():\n"
    "    print whether four is even, then double it\n"
)

PREAMBLE_SOURCE = (
    "import the math module\n"
    "set PI to about three point one four\n"
    "\n"
    "def area(r):\n"
    "    return PI times r squared\n"
)


def _function_names(units: list[Unit]) -> list[str]:
    return [unit.name for unit in units if isinstance(unit, FunctionUnit)]


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


def test_multi_function_synonyms_compile_to_valid_python_in_order(
    tmp_path: Path,
) -> None:
    """Mixed delimiter synonyms compile to valid Python with functions in order."""
    source = tmp_path / "many.npl"
    source.write_text(MULTI_FUNCTION)

    assert main([str(source)]) == 0

    tree = ast.parse((tmp_path / "many.py").read_text())
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert names == ["is_even", "double", "main"]


def test_control_flow_keyword_in_body_is_not_a_function_boundary() -> None:
    """``if``/``for``/``while`` inside a body never start a new function unit."""
    units = parse_source(MULTI_FUNCTION)

    assert _function_names(units) == ["is_even", "double", "main"]
    is_even = next(unit for unit in units if isinstance(unit, FunctionUnit))
    assert "if n is divisible by two:" in is_even.body
    assert "for each remainder check:" in is_even.body
    assert "while still unsure:" in is_even.body


def test_preamble_is_recognized_translated_and_appears_in_output(
    tmp_path: Path,
) -> None:
    """A top-of-file preamble is its own unit and lands in the generated ``.py``."""
    units = parse_source(PREAMBLE_SOURCE)
    assert isinstance(units[0], PreambleUnit)
    assert _function_names(units) == ["area"]

    source = tmp_path / "pre.npl"
    source.write_text(PREAMBLE_SOURCE)
    assert main([str(source)]) == 0

    output = (tmp_path / "pre.py").read_text()
    ast.parse(output)
    assert "import the math module" in output
    assert "set PI to about three point one four" in output
    assert "def area(r):" in output


def test_each_function_receives_current_generated_py_as_context(
    tmp_path: Path,
) -> None:
    """Each unit is translated with the whole current generated ``.py`` as context."""
    source = tmp_path / "ctx.npl"
    source.write_text(
        "def alpha():\n    do alpha things\n\ndef beta():\n    call alpha\n"
    )
    stub = StubTranslator()

    compile_file(source, stub)

    # alpha is translated first with nothing generated yet; beta then sees alpha's
    # real Python so an inter-function call could resolve.
    assert stub.contexts[0] == ""
    assert "def alpha():" in stub.contexts[1]


def test_delimiter_synonym_set_is_configurable() -> None:
    """The delimiter keyword set is a parameter, not hardcoded inline."""
    source = "subroutine greet(name):\n    say hello to name\n"

    # 'subroutine' is not in the default set, so the file has no function unit.
    with pytest.raises(CompileError):
        parse_source(source)

    units = parse_source(source, delimiters=("subroutine",))
    assert _function_names(units) == ["greet"]
    assert "def" in DELIMITER_KEYWORDS  # the shipped default set is non-empty


def test_parse_source_extracts_signature_and_body() -> None:
    units = parse_source(SINGLE_FUNCTION)

    assert len(units) == 1
    unit = units[0]
    assert isinstance(unit, FunctionUnit)
    assert unit.signature == "add(a, b)"
    assert unit.name == "add"
    assert "the two arguments" in unit.body


def test_parse_source_rejects_missing_signature() -> None:
    with pytest.raises(CompileError):
        parse_source("just some prose with no signature\n")


def test_stub_translator_emits_valid_named_function() -> None:
    unit = FunctionUnit(signature="add(a, b)", body="return the sum")

    python_source = StubTranslator().translate(unit, "")

    tree = ast.parse(python_source)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "add"
        for node in ast.walk(tree)
    )


def test_stub_translator_renders_preamble_as_valid_python() -> None:
    unit = PreambleUnit(body="import json\nset LIMIT to ten")

    python_source = StubTranslator().translate(unit, "")

    ast.parse(python_source)  # comments-only module is valid
    assert "import json" in python_source
    assert "set LIMIT to ten" in python_source


def test_stub_translator_is_deterministic() -> None:
    unit = FunctionUnit(signature="add(a, b)", body="return the sum")

    assert StubTranslator().translate(unit, "") == StubTranslator().translate(unit, "")


def test_stub_translator_satisfies_translator_protocol() -> None:
    assert isinstance(StubTranslator(), Translator)


def test_compile_rejects_unparseable_python_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """When the adapter returns invalid Python, compile fails and writes no file."""

    class BrokenTranslator:
        def translate(self, unit: Unit, context: str) -> str:
            return "def (this is not python:::"

    source = tmp_path / "broken.npl"
    source.write_text(SINGLE_FUNCTION)

    with pytest.raises(CompileError):
        compile_file(source, BrokenTranslator())

    assert not (tmp_path / "broken.py").exists()
