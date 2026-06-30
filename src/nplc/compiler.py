"""The compile pipeline: ``.npl`` source -> validated sibling ``.py``.

Parse the source into function units, translate each with a
:class:`~nplc.translator.Translator`, and validate every result with ``ast.parse``
*before* writing anything. The validate step is an all-or-nothing gate
(:func:`render_validated`): the full ``.py`` is written only once every function
parses, so a single un-parseable function fails the compile hard and can never
clobber a previously written good ``.py``. Validation is syntax-only — no
subprocess, no LSP — and no retry is attempted.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from nplc.translator import Translator
from nplc.unit import CompileError, FunctionUnit, parse_source


def compile_file(source_path: Path, translator: Translator) -> Path:
    """Compile a ``.npl`` file to its sibling ``.py``.

    Args:
        source_path: Path to the ``.npl`` pseudocode file.
        translator: Adapter that turns each function unit into Python source.

    Returns:
        The path of the written ``.py`` file.

    Raises:
        CompileError: If the source has no valid signature, or any translated
            function fails ``ast.parse``. Nothing is written on failure — a
            pre-existing ``.py`` is left untouched.
        OSError: If the source cannot be read or the target cannot be written.
    """
    # A single explicit-signature unit today; issue #4 turns this into N units.
    units = [parse_source(source_path.read_text())]
    python_source = render_validated(units, translator)
    target = source_path.with_suffix(".py")
    target.write_text(python_source)
    return target


def render_validated(units: Iterable[FunctionUnit], translator: Translator) -> str:
    """Translate and ``ast``-validate every unit, returning the joined source.

    This is the atomic gate. Each unit is translated exactly once (no retry) and
    checked with ``ast.parse``. The validated outputs are accumulated and returned
    only once *all* units parse, so the caller writes the file once at the end —
    a later bad function therefore never overwrites an earlier good ``.py``.

    Args:
        units: The function units to translate, in source order.
        translator: Adapter that turns each unit into Python source.

    Returns:
        The concatenated, fully validated Python source for all units.

    Raises:
        CompileError: If any unit's translated output fails ``ast.parse``. The
            message names the offending function and quotes the ``SyntaxError``.
    """
    rendered: list[str] = []
    for unit in units:
        python_source = translator.translate(unit)
        try:
            ast.parse(python_source)
        except SyntaxError as exc:
            raise CompileError(
                f"{unit.name}: translated output is not valid Python: {exc}"
            ) from exc
        rendered.append(python_source)
    return "".join(rendered)
