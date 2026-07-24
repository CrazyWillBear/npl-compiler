"""The model-agnostic translator interface and its implementations.

A :class:`Translator` turns a pseudocode unit into Python source, given the whole
current generated ``.py`` as context so calls between functions can resolve.
:class:`OllamaTranslator` is the real, default backend: it prompts a local Ollama
server (``qwen2.5-coder`` by default) over HTTP. :class:`StubTranslator` returns canned,
deterministic Python so the rest of the pipeline can be exercised in CI without a model,
and records every context it receives so tests can assert on it — it is a test double
only, never the default backend.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from nplc.unit import CompileError, FunctionUnit, PreambleUnit, Unit

DEFAULT_MODEL = "qwen2.5-coder"
DEFAULT_BASE_URL = "http://localhost:11434"
# A 7B model on modest hardware can take tens of seconds for a single function.
DEFAULT_TIMEOUT = 180.0

_SYSTEM_PROMPT = """\
You translate natural-language pseudocode into Python source code.

Rules:
- Output ONLY Python source code. No markdown fences, no prose, no explanation.
- Do not restate the pseudocode description as comments.
- Emit exactly what the task asks for and nothing else."""

# Models routinely wrap output in a fenced block despite being told not to; strip it
# rather than fail the compile on an otherwise correct translation.
_FENCE_PATTERN = re.compile(r"\A\s*```[^\n]*\n(?P<body>.*?)\n?```\s*\Z", re.DOTALL)


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


def _build_prompt(unit: Unit, context: str) -> str:
    """Render the task prompt for one unit, prefixed with the generated-so-far code."""
    if isinstance(unit, PreambleUnit):
        task = (
            "Write the module-level preamble (imports and constants) described below. "
            "Do not define any functions.\n\n"
            f"Description:\n{unit.body}"
        )
    else:
        task = (
            "Write exactly one Python function with this signature:\n"
            f"    def {unit.signature}:\n"
            "Give it a short docstring. Write no other top-level code.\n\n"
            f"Description:\n{unit.body}"
        )
    if not context.strip():
        return task
    return (
        "This is the Python generated so far. Call into it where the description "
        "refers to it, and do not repeat any of it:\n\n"
        f"{context}\n\n{task}"
    )


def _strip_code_fence(text: str) -> str:
    """Unwrap a fenced code block if present, normalising to one trailing newline."""
    match = _FENCE_PATTERN.match(text)
    body = match.group("body") if match else text
    return body.strip("\n") + "\n"


class OllamaTranslator:
    """:class:`Translator` backed by a local Ollama server — the default backend.

    Prompts the configured model over Ollama's ``/api/generate`` endpoint at
    temperature zero with a fixed seed, so the same unit and context yield the same
    Python as far as the model allows. Only the HTTP call is this class's concern —
    validating the returned source is the compiler's job.
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Configure the backend.

        Args:
            model: Ollama model tag. Defaults to ``$NPLC_OLLAMA_MODEL``, else
                :data:`DEFAULT_MODEL`.
            base_url: Ollama server root. Defaults to ``$NPLC_OLLAMA_URL``, else
                :data:`DEFAULT_BASE_URL`.
            timeout: Seconds to wait on a single generate call.
        """
        self.model = model or os.environ.get("NPLC_OLLAMA_MODEL") or DEFAULT_MODEL
        url = base_url or os.environ.get("NPLC_OLLAMA_URL") or DEFAULT_BASE_URL
        self.base_url = url.rstrip("/")
        self.timeout = timeout

    def translate(self, unit: Unit, context: str) -> str:
        """Return model-generated Python source for ``unit``.

        Args:
            unit: The preamble or function unit to translate.
            context: The whole current generated ``.py``, supplied to the model so
                inter-unit references resolve.

        Returns:
            The generated Python source, unwrapped from any markdown fence.

        Raises:
            CompileError: If the server is unreachable, times out, or returns a body
                that is not a generate response.
        """
        return _strip_code_fence(self._generate(_build_prompt(unit, context)))

    def _generate(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "system": _SYSTEM_PROMPT,
                "stream": False,
                "options": {"temperature": 0, "seed": 0},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CompileError(
                f"ollama request failed ({self.base_url}, model {self.model}): {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise CompileError(f"unexpected ollama response: {exc}") from exc
        generated = body.get("response") if isinstance(body, dict) else None
        if not isinstance(generated, str):
            raise CompileError(f"unexpected ollama response: {body!r}")
        return generated


class StubTranslator:
    """Deterministic :class:`Translator` test double — never the default backend.

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
