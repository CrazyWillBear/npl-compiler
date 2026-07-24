"""Tests for the real Ollama-backed translator.

The tests that prove the central mechanism are *not* mocked: they translate through a
local Ollama server running ``qwen2.5-coder`` and assert the result is ``ast``-valid.
They skip when no such server is reachable, so CI without a model still runs green.
The mocked tests below stub only the HTTP boundary to exercise response handling that a
live model cannot be made to produce on demand (fences, transport failure, bad body).
"""

from __future__ import annotations

import ast
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from nplc.cli import main
from nplc.translator import DEFAULT_MODEL, OllamaTranslator, Translator
from nplc.unit import CompileError, FunctionUnit, PreambleUnit


def _ollama_has_model() -> bool:
    """Whether a local Ollama server is up and serving the default model."""
    try:
        with urllib.request.urlopen(
            f"{OllamaTranslator().base_url}/api/tags", timeout=2
        ) as response:
            tags = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    names = [model.get("name", "") for model in tags.get("models", [])]
    return any(name.split(":", 1)[0] == DEFAULT_MODEL for name in names)


requires_ollama = pytest.mark.skipif(
    not _ollama_has_model(),
    reason=f"needs a local Ollama server with {DEFAULT_MODEL} pulled",
)


def _fake_urlopen(body: object) -> Any:
    """An ``urlopen`` replacement returning ``body`` as the JSON response."""

    def opener(request: object, timeout: float | None = None) -> io.BytesIO:
        return io.BytesIO(json.dumps(body).encode())

    return opener


def _raising_urlopen(error: Exception) -> Any:
    """An ``urlopen`` replacement that always fails with ``error``."""

    def opener(request: object, timeout: float | None = None) -> io.BytesIO:
        raise error

    return opener


def test_ollama_translator_satisfies_the_translator_protocol() -> None:
    assert isinstance(OllamaTranslator(), Translator)


def test_model_and_base_url_are_configurable() -> None:
    translator = OllamaTranslator(model="other-model", base_url="http://host:1234/")

    assert translator.model == "other-model"
    assert translator.base_url == "http://host:1234"  # trailing slash normalised


def test_environment_overrides_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NPLC_OLLAMA_MODEL", "env-model")
    monkeypatch.setenv("NPLC_OLLAMA_URL", "http://env-host:9999")

    translator = OllamaTranslator()

    assert translator.model == "env-model"
    assert translator.base_url == "http://env-host:9999"


def test_markdown_fences_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    fenced = "```python\ndef add(a, b):\n    return a + b\n```"
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen({"response": fenced}))

    source = OllamaTranslator().translate(FunctionUnit("add(a, b)", "sum"), "")

    assert source == "def add(a, b):\n    return a + b\n"


def test_unfenced_output_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen({"response": "X = 1"}))

    assert OllamaTranslator().translate(PreambleUnit("a constant"), "") == "X = 1\n"


def test_transport_failure_becomes_a_compile_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _raising_urlopen(urllib.error.URLError("connection refused")),
    )

    with pytest.raises(CompileError, match="ollama request failed"):
        OllamaTranslator().translate(FunctionUnit("add(a, b)", "sum"), "")


def test_response_without_the_expected_field_becomes_a_compile_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen({"error": "boom"}))

    with pytest.raises(CompileError, match="unexpected ollama response"):
        OllamaTranslator().translate(FunctionUnit("add(a, b)", "sum"), "")


@requires_ollama
def test_real_model_translates_a_function_to_valid_python() -> None:
    """The central mechanism, unmocked: real qwen2.5-coder emits parseable Python."""
    unit = FunctionUnit(
        declaration="add(a, b)", body="Return the sum of the two numbers a and b."
    )

    source = OllamaTranslator().translate(unit, "")

    ast.parse(source)  # raises SyntaxError if the model produced junk
    assert "def add" in source


@requires_ollama
def test_real_model_infers_a_signature_from_prose(tmp_path: Path) -> None:
    """A prose-only function compiles, and the model's inferred def lands in the .py."""
    source = tmp_path / "avg.npl"
    source.write_text(
        "def compute the average of a list of numbers:\n"
        "    add all the numbers together\n"
        "    divide by how many numbers there are\n"
    )

    assert main([str(source)]) == 0

    tree = ast.parse((tmp_path / "avg.py").read_text())
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert len(definitions) == 1
    assert definitions[0].args.args, "the model should have inferred a parameter"


@requires_ollama
def test_real_model_compiles_through_the_cli_by_default(tmp_path: Path) -> None:
    """``nplc FILE.npl`` translates for real — no stub on the default path."""
    source = tmp_path / "add.npl"
    source.write_text("def add(a, b):\n    Return the sum of the numbers a and b.\n")

    exit_code = main([str(source)])

    assert exit_code == 0
    generated = (tmp_path / "add.py").read_text()
    ast.parse(generated)
    assert "def add" in generated
