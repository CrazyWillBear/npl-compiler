# nplc

A deterministic compiler that turns natural-language pseudocode (`.npl`) into
runnable Python (`.py`). See [`PRD.md`](./PRD.md) for the full design.

> Status: early slice. `nplc FILE.npl` splits a file into an optional top-of-file
> preamble plus ordered function units — a function opens with an optional delimiter
> synonym (`def`, `function`, `func`, `fn`, `procedure`, `algorithm`) and a
> `name(params):` signature, with indentation-delimited prose bodies, so control-flow
> keywords (`if`/`for`/`while`) inside a body never start a new function. Each unit is
> translated with the whole current generated `.py` as context, validated, and written
> to an `ast`-valid sibling `FILE.py`. Translation runs through a model-agnostic
> `Translator`; the default is a deterministic `StubTranslator` (the real Ollama
> adapter and caching land in later slices).

## Development

This project uses [uv](https://docs.astral.sh/uv/). The full check is:

```sh
uv run pytest
uv run ruff check .
uv run mypy .
```

Run the CLI with `uv run nplc --help`.
