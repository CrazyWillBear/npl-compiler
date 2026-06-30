# nplc

A deterministic compiler that turns natural-language pseudocode (`.npl`) into
runnable Python (`.py`). See [`PRD.md`](./PRD.md) for the full design.

> Status: early slice. `nplc FILE.npl` compiles a file holding a single
> explicit-signature function (`name(params):` + indented prose body) to an
> `ast`-valid sibling `FILE.py`. Validation is syntax-only: if a function's
> translated output fails `ast.parse`, the compile fails hard — it names the
> function, prints the `SyntaxError`, writes nothing (leaving any prior good
> `.py` untouched), and does not retry. Translation runs through a
> model-agnostic `Translator`; the default is a deterministic `StubTranslator`
> (the real Ollama adapter, multiple functions, preamble, and caching land in
> later slices).

## Development

This project uses [uv](https://docs.astral.sh/uv/). The full check is:

```sh
uv run pytest
uv run ruff check .
uv run mypy .
```

Run the CLI with `uv run nplc --help`.
