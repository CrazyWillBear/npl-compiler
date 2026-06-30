# nplc

A deterministic compiler that turns natural-language pseudocode (`.npl`) into
runnable Python (`.py`). See [`PRD.md`](./PRD.md) for the full design.

> Status: bootstrap skeleton. The CLI is wired up but compilation is not
> implemented yet — `nplc FILE.npl` currently prints a placeholder notice.

## Development

This project uses [uv](https://docs.astral.sh/uv/). The full check is:

```sh
uv run pytest
uv run ruff check .
uv run mypy .
```

Run the CLI with `uv run nplc --help`.
