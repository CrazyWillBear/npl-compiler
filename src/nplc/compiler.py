"""The compile pipeline: ``.npl`` source -> validated sibling ``.py``.

This is the load-bearing path for issue #3: parse one function unit, hand it to a
:class:`~nplc.translator.Translator`, validate the result with ``ast.parse``, and
write the sibling ``.py`` only when it is valid. On any failure the source `.py`
is left untouched (nothing is written), per the PRD's fail-hard contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

from nplc.translator import Translator
from nplc.unit import CompileError, parse_source


def compile_file(source_path: Path, translator: Translator) -> Path:
    """Compile a single-function ``.npl`` file to its sibling ``.py``.

    Args:
        source_path: Path to the ``.npl`` pseudocode file.
        translator: Adapter that turns the function unit into Python source.

    Returns:
        The path of the written ``.py`` file.

    Raises:
        CompileError: If the source has no valid signature, or the translated
            Python fails ``ast.parse``. Nothing is written on failure.
        OSError: If the source cannot be read or the target cannot be written.
    """
    unit = parse_source(source_path.read_text())
    python_source = translator.translate(unit)
    try:
        ast.parse(python_source)
    except SyntaxError as exc:
        raise CompileError(
            f"{unit.name}: translated Python is not valid: {exc}"
        ) from exc
    target = source_path.with_suffix(".py")
    target.write_text(python_source)
    return target
