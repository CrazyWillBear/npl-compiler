# NPL Compiler — natural-language pseudocode → Python

## Problem
Writing real Python means writing real Python. There's no tool that takes a file of
human-readable, natural-language pseudocode and *compiles* it — deterministically and
repeatably — into runnable Python, the way a C compiler turns source into assembly. People
sketch algorithms in prose first; today that prose is throwaght. We want the prose to be the
source of truth and the Python to be the compiled artifact, regenerated on demand, with
unchanged input always producing the same output.

## Solution
A one-shot command-line compiler, `nplc`. Run `nplc file.npl` and it writes `file.py`.

The compiler reads a pseudocode file organized into **functions** (plus an optional top-of-file
**preamble** for imports/constants). Each function is a unit: a delimiter keyword from a
configurable synonym set (`def`, `function`, `func`, `fn`, `procedure`, `algorithm`), a signature
line that is either explicit (`name(params):`) or a prose name the model infers, and an indented
natural-language body describing what the function does.

Translation is performed by a **model-agnostic LLM** behind a pluggable adapter interface. The
default adapter is a **local Ollama** server (`http://localhost:11434`) running **`qwen2.5-coder`**
— no API key, no network, free, fast to loop on. Other backends (Claude, OpenAI) can be added
later behind the same interface. Each function is translated with the **whole current generated
`.py`** (the real Python of its siblings) supplied as context, so calls between functions resolve
correctly.

The compiler is **deterministic by construction via caching**, not by sampling settings. The
generated `.py` *is* the cache (the gcc-writes-assembly model): each function block carries a
**source-hash marker comment**. On recompile, a function is reused verbatim from the existing `.py`
unless **its own pseudocode changed, or a sibling function's signature changed** — so unchanged work
never re-hits the model and unchanged input yields byte-identical output. Body-only edits to a
sibling do not cascade.

Every translated function is checked with the standard library's `ast.parse` before anything is
written. If the model returns Python that doesn't parse, the compile **fails hard**: it names the
offending function and prints the `SyntaxError`, writes **nothing**, and stops. The user fixes the
pseudocode and reruns. There is no automatic retry.

The compiler itself is written in **Python** (toolchain: uv + ruff + mypy + pytest, already
scaffolded), which also gives `ast`-based validation for free.

## User Stories
- As a developer sketching an algorithm, I write it in plain language in `binary_search.npl` and run
  `nplc binary_search.npl` to get a runnable `binary_search.py`.
- As a developer iterating, I tweak one function's prose and recompile; only that function (and any
  whose signature I changed) is re-translated — the rest is reused instantly from cache, no model
  calls.
- As a developer who mistyped a description, I get a clear failure naming the function and the
  Python `SyntaxError`, and my previous good `.py` is not clobbered with garbage.
- As a developer offline, I compile against my local Ollama model with no API key and no network.
- As a developer with a preferred backend, I point the config at a different model/adapter without
  changing my pseudocode.

## Implementation Decisions
- **Form factor:** single one-shot CLI invocation `nplc file.npl` → writes sibling `file.py`. No
  watcher, no daemon, no editor integration in v1.
- **Unit of translation and caching:** the function. The file splits into an optional preamble unit
  plus ordered function units.
- **Function delimiter:** a configurable set of synonym keywords; only a keyword at
  function-definition position starts a unit (control-flow keywords like `if`/`for`/`while` must not
  be mis-read as function boundaries). Body is indentation-delimited.
- **Signature:** explicit `name(params):` if the author wrote one; otherwise the model infers it from
  the prose name/body.
- **Engine:** model-agnostic translator interface; default backend = local Ollama (`qwen2.5-coder`),
  configurable. Each function is translated with the entire current generated `.py` as context.
- **Determinism:** guaranteed by the per-function source-hash cache, *not* by temperature/sampling
  (the newest hosted models reject sampling params; the cache is the real contract).
- **Cache storage:** the generated `.py` is the cache, via per-function hash-marker comments. Accepted
  trade-off: formatters, hand-edits, or deleting the `.py` can corrupt/wipe the cache, and the
  compiler must `ast`-read its own output each run.
- **Re-translate trigger:** a function's own pseudocode hash changed, OR any sibling's signature
  changed. Sibling body-only changes do not cascade. (Cache key = own-pseudocode-hash +
  sibling-signatures-hash.)
- **Validation:** `ast.parse` on each function's output, syntax only. No LSP, no subprocess.
- **Failure mode:** hard error — name the function, print the `SyntaxError`, write nothing, no retry.
- **Host language:** Python (uv + ruff + mypy + pytest).

## Testing Decisions
- **Test level:** end-to-end, through the CLI (`nplc file.npl`). Tests assert the written `.py` is
  `ast`-valid and that known algorithms import and run correctly. Pipeline machinery (splitter,
  hasher/cache, assembler, validator) is exercised through that outer interface; a stub translator
  adapter is used for deterministic CI.
- **Central mechanism (must run for real, not mocked, before ship):** *natural-language pseudocode in
  → `ast`-valid Python out via the LLM translator, driven through the CLI.* At least one
  non-mocked test must exercise real Ollama translation end-to-end, so the load-bearing behavior is
  proven and not faked away (anti-mock-drift). The stub translator is permitted only to make the
  *other* assertions deterministic, never as a substitute for the one real-translation test.
- **Caching is verified behaviorally:** a second compile of unchanged input performs zero translator
  calls (assert against a counting/spy adapter) and produces byte-identical output.
- **TDD:** new behavior starts with a failing test; the full done-check (`uv run pytest` /
  `uv run ruff check .` / `uv run mypy .`) must pass.

## Out of Scope
- **Live/watch mode** (`--watch`) and any editor/IDE/LSP plugin (vscode/vim/emacs). v1 is a one-shot
  command only.
- **Full-module pseudocode** — arbitrary top-level statements, classes, free-form module bodies. v1
  is functions + a simple preamble.
- **Non-Ollama backends** (Claude, OpenAI, etc.) — the adapter interface must allow them, but no
  adapter beyond Ollama ships in v1.
- **Source maps / line-level traceability** between pseudocode and generated Python.
- **Automatic retry / self-repair** on a parse failure.
- **Reverse direction** (Python → pseudocode), formatting/style configuration of the output, and
  multi-file/project compilation.

## Further Notes
- First demoable slice: a `binary_search.npl` compiles to a correct, `ast`-valid `binary_search.py`
  via Ollama `qwen2.5-coder`, and a second run hits the cache (zero translator calls, identical
  output).
- Bootstrap not yet done: the `uv run …` commands in `CLAUDE.md` need `uv init` +
  `uv add --dev ruff mypy pytest` first.
- The repo is **not yet under git**; `git init` is needed before issue-tracking/`/orchestrate` flows.
- Requirements were locked via a full `/grill-me` pass this session; this PRD is the synthesis, no
  open questions remain.
