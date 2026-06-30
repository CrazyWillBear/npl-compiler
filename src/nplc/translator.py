"""The model-agnostic translator interface and a deterministic stub.

A :class:`Translator` turns a pseudocode :class:`~nplc.unit.FunctionUnit` into
Python source. The real model-backed adapter (local Ollama, issue #8) implements
this same protocol, so callers in the compile pipeline never change when it lands.
:class:`StubTranslator` returns canned, deterministic Python so the rest of the
pipeline can be exercised in CI without a model.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nplc.unit import FunctionUnit


@runtime_checkable
class Translator(Protocol):
    """Translates a pseudocode function unit into Python source code."""

    def translate(self, unit: FunctionUnit) -> str:
        """Return Python source implementing ``unit``."""
        ...


class StubTranslator:
    """Deterministic :class:`Translator` for tests and CI.

    Emits a syntactically valid function that carries the pseudocode prose as
    comments and a ``raise NotImplementedError`` placeholder body. It performs no
    model call, so its output is byte-stable for the same input — the real
    translation is deferred to the Ollama adapter (issue #8).
    """

    def translate(self, unit: FunctionUnit) -> str:
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
