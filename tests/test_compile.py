"""Tests for the compile pipeline: ``.npl`` source -> validated sibling ``.py``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nplc.cli import main
from nplc.compiler import compile_file, render_validated
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


def test_compile_failure_names_function_and_quotes_syntax_error(
    tmp_path: Path,
) -> None:
    """A hard-fail message names the offending function and prints the SyntaxError."""
    broken_python = "def (this is not python:::"
    try:
        ast.parse(broken_python)
    except SyntaxError as exc:
        syntax_message = str(exc)

    class BrokenTranslator:
        def translate(self, unit: FunctionUnit) -> str:
            return broken_python

    source = tmp_path / "broken.npl"
    source.write_text(SINGLE_FUNCTION)

    with pytest.raises(CompileError) as exc_info:
        compile_file(source, BrokenTranslator())

    message = str(exc_info.value)
    assert "add" in message  # names the offending function
    assert syntax_message in message  # surfaces the SyntaxError verbatim
    assert isinstance(exc_info.value.__cause__, SyntaxError)


def test_compile_does_not_retry_on_failure(tmp_path: Path) -> None:
    """The translator is invoked exactly once per unit — no automatic retry."""

    class CountingBrokenTranslator:
        def __init__(self) -> None:
            self.calls = 0

        def translate(self, unit: FunctionUnit) -> str:
            self.calls += 1
            return "def (broken:::"

    translator = CountingBrokenTranslator()
    source = tmp_path / "broken.npl"
    source.write_text(SINGLE_FUNCTION)

    with pytest.raises(CompileError):
        compile_file(source, translator)

    assert translator.calls == 1


def test_failed_compile_leaves_prior_good_py_byte_identical(tmp_path: Path) -> None:
    """A failing compile never clobbers a previously written good ``.py``."""
    source = tmp_path / "fn.npl"
    source.write_text(SINGLE_FUNCTION)

    target = compile_file(source, StubTranslator())
    good_bytes = target.read_bytes()

    class BrokenTranslator:
        def translate(self, unit: FunctionUnit) -> str:
            return "def (broken:::"

    with pytest.raises(CompileError):
        compile_file(source, BrokenTranslator())

    assert target.read_bytes() == good_bytes


def test_render_validated_is_atomic_across_multiple_functions() -> None:
    """One bad function fails the whole batch and never returns partial output."""
    first = FunctionUnit(signature="first(a)", body="return a")
    second = FunctionUnit(signature="second(b)", body="return b")

    class SelectiveTranslator:
        """Valid Python for ``first``; un-parseable Python for ``second``."""

        def translate(self, unit: FunctionUnit) -> str:
            if unit.name == "second":
                return "def (broken:::"
            return StubTranslator().translate(unit)

    with pytest.raises(CompileError) as exc_info:
        render_validated([first, second], SelectiveTranslator())

    # The gate names the *later* offending function, not the earlier good one.
    assert "second" in str(exc_info.value)


def test_render_validated_concatenates_valid_functions() -> None:
    """When every unit parses, the gate returns the joined, ast-valid source."""
    first = FunctionUnit(signature="first(a)", body="return a")
    second = FunctionUnit(signature="second(b)", body="return b")

    rendered = render_validated([first, second], StubTranslator())

    tree = ast.parse(rendered)
    names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert names == {"first", "second"}
