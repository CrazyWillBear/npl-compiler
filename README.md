# nplc

A deterministic compiler that turns natural-language pseudocode (`.npl`) into
runnable Python (`.py`). See [`PRD.md`](./PRD.md) for the full design.

> Status: early slice. `nplc FILE.npl` splits a file into an optional top-of-file
> preamble plus ordered function units — a function opens with an optional delimiter
> synonym (`def`, `function`, `func`, `fn`, `procedure`, `algorithm`) and a declaration
> that is either an explicit `name(params):` signature or a prose name the model infers
> a signature from, with indentation-delimited prose bodies, so control-flow keywords
> (`if`/`for`/`while`) inside a body never start a new function. Each unit is
> translated with the whole current generated `.py` as context, then `ast`-validated
> before anything is written. Validation is syntax-only and all-or-nothing: if any
> unit's translated output fails `ast.parse`, the compile fails hard — it names the
> function, prints the `SyntaxError`, writes nothing (leaving any prior good `.py`
> untouched), and does not retry; otherwise the validated whole is written to an
> `ast`-valid sibling `FILE.py`. Translation runs through a model-agnostic
> `Translator`; the default backend is `OllamaTranslator`, prompting a local Ollama
> server for real (caching lands in a later slice).

Both declaration forms in one file:

```
def compute the average of a list of numbers:
    add all the numbers together
    divide by how many numbers there are

def is_odd(n):
    return whether n is odd
```

The first has no signature, so the model picks the name and parameters and the compiler
reads them back off the generated `def` — that derived `name(params)` is the function's
*canonical signature*, used identically whether the author wrote it or the model did. An
inferred function whose output holds zero or several top-level `def`s fails the compile.

## Requirements

Compiling needs a local [Ollama](https://ollama.com) server with the model pulled:

```sh
ollama serve &
ollama pull qwen2.5-coder
```

Both are configurable — `NPLC_OLLAMA_MODEL` (default `qwen2.5-coder`) and
`NPLC_OLLAMA_URL` (default `http://localhost:11434`).

## Development

This project uses [uv](https://docs.astral.sh/uv/). The full check is:

```sh
uv run pytest
uv run ruff check .
uv run mypy .
```

Run the CLI with `uv run nplc --help`.

The tests that exercise the real model skip automatically when no Ollama server with
the default model is reachable, so the suite stays green without one; everything else
runs against the deterministic `StubTranslator` test double.
