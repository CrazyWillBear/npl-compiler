"""The model-agnostic translator interface and a deterministic stub.

A :class:`Translator` turns a pseudocode unit into Python source, given the whole
current generated ``.py`` as context so calls between functions can resolve. The real
model-backed adapter (local Ollama, issue #8) implements this same protocol, so callers
in the compile pipeline never change when it lands. :class:`StubTranslator` returns
canned, deterministic Python so the rest of the pipeline can be exercised in CI without
a model, and records every context it receives so tests can assert on it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nplc.unit import FunctionUnit, PreambleUnit, Unit


@runtime_checkable
class Translator(Protocol):
    """Translates a pseudocode unit into Python source code."""

    def translate(self, unit: Unit, context: str) -> str:
        """Return Python source for ``unit``.

        Args:
            unit: The preamble or function unit to translate.
            context: The whole current generated ``.py`` produced from earlier units,
                supplied so inter-unit references resolve.
        """
        ...


class StubTranslator:
    """Deterministic :class:`Translator` for tests and CI.

    Renders a function unit as a syntactically valid ``def`` carrying the prose as
    comments and a ``raise NotImplementedError`` placeholder, and a preamble unit as
    comment lines. It performs no model call, so its output is byte-stable for the same
    input — the real translation is deferred to the Ollama adapter (issue #8). Every
    context passed to :meth:`translate` is appended to :attr:`contexts` so a test can
    assert each unit saw the current generated ``.py``.
    """

    def __init__(self) -> None:
        self.contexts: list[str] = []

    def translate(self, unit: Unit, context: str) -> str:
        self.contexts.append(context)
        if isinstance(unit, PreambleUnit):
            return self._translate_preamble(unit)
        return self._translate_function(unit)

    @staticmethod
    def _translate_preamble(unit: PreambleUnit) -> str:
        comment_lines = [f"# {line}" for line in unit.body.splitlines()]
        if not comment_lines:
            comment_lines = ["# (empty preamble)"]
        return "\n".join([*comment_lines, ""])

    @staticmethod
    def _translate_function(unit: FunctionUnit) -> str:
        comment_lines = [f"    # {line}" for line in unit.body.splitlines()]
        if not comment_lines:
            comment_lines = ["    # (no body provided)"]
        parts = [
            f"def {unit.signature}:",
            *comment_lines,
            '    raise NotImplementedError("nplc stub translator")',
            "",
        ]
        return "\n".join(parts)
