"""The compile pipeline: ``.npl`` source -> validated sibling ``.py``.

Parse the source into ordered units (optional preamble + N functions), translate each
unit in order with the whole current generated ``.py`` supplied as context, and
``ast``-validate every result *before* writing anything. The validate step is an
all-or-nothing gate (:func:`render_validated`): the full ``.py`` is written only once
every unit parses, so a single un-parseable function fails the compile hard — it names
the offending function, surfaces the ``SyntaxError``, writes nothing (leaving any prior
good ``.py`` untouched), and does not retry. Validation is syntax-only — no subprocess,
no LSP.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from nplc.translator import Translator
from nplc.unit import CompileError, FunctionUnit, Unit, parse_source


def compile_file(source_path: Path, translator: Translator) -> Path:
    """Compile a multi-unit ``.npl`` file to its sibling ``.py``.

    Args:
        source_path: Path to the ``.npl`` pseudocode file.
        translator: Adapter that turns each unit into Python source.

    Returns:
        The path of the written ``.py`` file.

    Raises:
        CompileError: If the source has no function signature, or any translated
            unit fails ``ast.parse``. Nothing is written on failure — a pre-existing
            ``.py`` is left untouched.
        OSError: If the source cannot be read or the target cannot be written.
    """
    units = parse_source(source_path.read_text())
    python_source = render_validated(units, translator)
    target = source_path.with_suffix(".py")
    target.write_text(python_source)
    return target


def _unit_label(unit: Unit) -> str:
    """Name the offending unit for a hard-fail message."""
    return unit.name if isinstance(unit, FunctionUnit) else "preamble"


def canonical_signature(unit: FunctionUnit, tree: ast.Module) -> str:
    """Return the one signature that identifies ``unit``, explicit or inferred.

    Every function has exactly one canonical signature regardless of how it was
    written: the author's when they wrote one, otherwise the signature the model chose,
    read back off the generated ``def``. Later slices key their cache on this, so it
    must not depend on which form the author used.

    Args:
        unit: The function unit that was translated.
        tree: The parsed module produced from that unit's translated Python.

    Returns:
        The ``name(params)`` text, without the ``def`` keyword or trailing colon.

    Raises:
        CompileError: If an inferred function's output does not hold exactly one
            top-level function definition. Nested definitions are not counted, so a
            closure inside the body is fine.
    """
    if unit.is_explicit:
        return unit.declaration
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if not definitions:
        raise CompileError(
            f"{unit.name}: no function was inferred from the prose declaration "
            f"{unit.declaration!r}"
        )
    if len(definitions) > 1:
        names = ", ".join(node.name for node in definitions)
        raise CompileError(
            f"{unit.name}: inferred {len(definitions)} functions ({names}), "
            "expected exactly one"
        )
    return f"{definitions[0].name}({ast.unparse(definitions[0].args)})"


def render_validated(units: Iterable[Unit], translator: Translator) -> str:
    """Translate and ``ast``-validate every unit in order, returning the joined source.

    This is the atomic gate. Units are translated in source order, each receiving the
    whole current generated ``.py`` as context so inter-unit references resolve. Each
    output is translated exactly once (no retry) and checked with ``ast.parse``. The
    validated outputs are accumulated and returned only once *all* units parse, so the
    caller writes the file once at the end — a later bad function therefore never
    overwrites an earlier good ``.py``.

    Args:
        units: The units to translate, in source order.
        translator: Adapter that turns each unit into Python source.

    Returns:
        The concatenated, fully validated Python source for all units.

    Raises:
        CompileError: If any unit's translated output fails ``ast.parse``. The message
            names the offending function and quotes the ``SyntaxError``.
    """
    generated_parts: list[str] = []
    for unit in units:
        context = "\n".join(generated_parts)
        python_source = translator.translate(unit, context)
        try:
            tree = ast.parse(python_source)
        except SyntaxError as exc:
            raise CompileError(
                f"{_unit_label(unit)}: translated output is not valid Python: {exc}"
            ) from exc
        if isinstance(unit, FunctionUnit):
            # Derived for every function, inside the same all-or-nothing gate: an
            # un-inferable function must fail the compile before anything is written.
            canonical_signature(unit, tree)
        generated_parts.append(python_source)
    return "\n".join(generated_parts)
