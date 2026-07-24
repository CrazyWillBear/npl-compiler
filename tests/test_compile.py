"""Tests for the compile pipeline: ``.npl`` source -> validated sibling ``.py``."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nplc.cli import main
from nplc.compiler import canonical_signature, compile_file, render_validated
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


# Prose declarations carry no parens; a delimiter keyword is what marks them as
# function boundaries, so an undelimited prose line stays ordinary body text.
PROSE_SOURCE = (
    "def compute the average of a list of numbers:\n"
    "    add all the numbers together\n"
    "    divide by how many there are\n"
)


def _function_names(units: list[Unit]) -> list[str]:
    return [unit.name for unit in units if isinstance(unit, FunctionUnit)]


@pytest.fixture(autouse=True)
def stub_the_cli_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the CLI's default backend to the stub for this module.

    These tests cover splitting, context assembly and the write/fail gate — not
    translation quality — so they must stay fast and deterministic rather than call a
    live model. The real backend is exercised in ``test_ollama.py``.
    """
    monkeypatch.setattr("nplc.cli.OllamaTranslator", StubTranslator)


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
    assert unit.declaration == "add(a, b)"
    assert unit.name == "add"
    assert "the two arguments" in unit.body


def test_parse_source_rejects_missing_signature() -> None:
    with pytest.raises(CompileError):
        parse_source("just some prose with no signature\n")


def test_prose_declaration_is_a_function_unit_without_an_explicit_signature() -> None:
    """A delimited prose line opens a function whose signature the model infers."""
    units = parse_source(PROSE_SOURCE)

    assert len(units) == 1
    unit = units[0]
    assert isinstance(unit, FunctionUnit)
    assert unit.is_explicit is False
    assert unit.declaration == "compute the average of a list of numbers"
    assert "divide by how many there are" in unit.body


def test_explicit_declaration_is_marked_explicit() -> None:
    units = parse_source(SINGLE_FUNCTION)
    unit = units[0]

    assert isinstance(unit, FunctionUnit)
    assert unit.is_explicit is True
    assert unit.declaration == "add(a, b)"
    assert unit.name == "add"


def test_undelimited_prose_line_is_not_a_function_boundary() -> None:
    """Without a delimiter keyword a prose line is body text, not a new function."""
    source = "def outer(x):\n    compute the average of a list:\n        do it\n"

    assert _function_names(parse_source(source)) == ["outer"]


def test_canonical_signature_is_the_declaration_when_explicit() -> None:
    unit = FunctionUnit(declaration="add(a, b)", body="return the sum")

    generated = ast.parse("def add(a, b):\n    return a + b\n")

    assert canonical_signature(unit, generated) == "add(a, b)"


def test_canonical_signature_is_read_off_the_generated_def_when_inferred() -> None:
    """An inferred function's canonical signature comes from the model's def line."""
    unit = FunctionUnit(declaration="the average of some numbers", body="add them up")

    signature = canonical_signature(
        unit,
        ast.parse("def average(numbers):\n    return sum(numbers) / len(numbers)\n"),
    )

    assert signature == "average(numbers)"


def test_inferred_function_compiles_and_its_def_appears_in_the_output(
    tmp_path: Path,
) -> None:
    """A prose-only function compiles end-to-end, inferred def included."""
    source = tmp_path / "prose.npl"
    source.write_text(PROSE_SOURCE)

    assert main([str(source)]) == 0

    output = (tmp_path / "prose.py").read_text()
    ast.parse(output)
    assert "def compute_the_average_of_a_list_of_numbers(" in output


@pytest.mark.parametrize(
    ("generated", "expected_message"),
    [
        ("x = 1\n", "no function"),
        ("def a():\n    pass\n\n\ndef b():\n    pass\n", "2 functions"),
    ],
)
def test_inference_requires_exactly_one_top_level_def(
    generated: str, expected_message: str
) -> None:
    """Zero or several top-level defs is a hard failure naming the function."""
    unit = FunctionUnit(declaration="something vague", body="do a thing")

    with pytest.raises(CompileError, match=expected_message):
        canonical_signature(unit, ast.parse(generated))


def test_nested_defs_do_not_count_toward_the_one_def_rule() -> None:
    """A closure inside the function body is not a second top-level function."""
    unit = FunctionUnit(declaration="a counter factory", body="make a counter")
    generated = (
        "def counter():\n    def bump(n):\n        return n + 1\n    return bump\n"
    )

    assert canonical_signature(unit, ast.parse(generated)) == "counter()"


def test_explicit_signature_skips_the_one_def_rule() -> None:
    """An author-written signature is authoritative; extra defs are not inspected."""
    unit = FunctionUnit(declaration="add(a, b)", body="return the sum")
    generated = "def helper():\n    pass\n\n\ndef add(a, b):\n    return a + b\n"

    assert canonical_signature(unit, ast.parse(generated)) == "add(a, b)"


def test_stub_translator_emits_valid_named_function() -> None:
    unit = FunctionUnit(declaration="add(a, b)", body="return the sum")

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
    unit = FunctionUnit(declaration="add(a, b)", body="return the sum")

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
        def translate(self, unit: Unit, context: str) -> str:
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

        def translate(self, unit: Unit, context: str) -> str:
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
        def translate(self, unit: Unit, context: str) -> str:
            return "def (broken:::"

    with pytest.raises(CompileError):
        compile_file(source, BrokenTranslator())

    assert target.read_bytes() == good_bytes


def test_render_validated_is_atomic_across_multiple_functions() -> None:
    """One bad function fails the whole batch and never returns partial output."""
    first = FunctionUnit(declaration="first(a)", body="return a")
    second = FunctionUnit(declaration="second(b)", body="return b")

    class SelectiveTranslator:
        """Valid Python for ``first``; un-parseable Python for ``second``."""

        def translate(self, unit: Unit, context: str) -> str:
            if isinstance(unit, FunctionUnit) and unit.name == "second":
                return "def (broken:::"
            return StubTranslator().translate(unit, context)

    with pytest.raises(CompileError) as exc_info:
        render_validated([first, second], SelectiveTranslator())

    # The gate names the *later* offending function, not the earlier good one.
    assert "second" in str(exc_info.value)


def test_render_validated_concatenates_valid_functions() -> None:
    """When every unit parses, the gate returns the joined, ast-valid source."""
    first = FunctionUnit(declaration="first(a)", body="return a")
    second = FunctionUnit(declaration="second(b)", body="return b")

    rendered = render_validated([first, second], StubTranslator())

    tree = ast.parse(rendered)
    names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert names == {"first", "second"}
