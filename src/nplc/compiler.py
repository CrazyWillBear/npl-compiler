"""The compile pipeline: ``.npl`` source -> validated sibling ``.py``.

Parse the source into ordered units (optional preamble + N functions), translate each
unit in order with the whole current generated ``.py`` supplied as context, validate the
assembled result with ``ast.parse``, and write the sibling ``.py`` only when valid. On
failure the source ``.py`` is left untouched, per the PRD's fail-hard contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

from nplc.translator import Translator
from nplc.unit import CompileError, Unit, parse_source


def _assemble_python(units: list[Unit], translator: Translator) -> str:
    """Translate units in order, feeding each the current generated ``.py``."""
    generated_parts: list[str] = []
    for unit in units:
        context = "\n".join(generated_parts)
        generated_parts.append(translator.translate(unit, context))
    return "\n".join(generated_parts)


def compile_file(source_path: Path, translator: Translator) -> Path:
    """Compile a multi-unit ``.npl`` file to its sibling ``.py``.

    Args:
        source_path: Path to the ``.npl`` pseudocode file.
        translator: Adapter that turns each unit into Python source.

    Returns:
        The path of the written ``.py`` file.

    Raises:
        CompileError: If the source has no function signature, or the assembled
            Python fails ``ast.parse``. Nothing is written on failure.
        OSError: If the source cannot be read or the target cannot be written.
    """
    units = parse_source(source_path.read_text())
    python_source = _assemble_python(units, translator)
    try:
        ast.parse(python_source)
    except SyntaxError as exc:
        raise CompileError(f"translated Python is not valid: {exc}") from exc
    target = source_path.with_suffix(".py")
    target.write_text(python_source)
    return target
