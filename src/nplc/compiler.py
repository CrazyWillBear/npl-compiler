"""The compile pipeline: ``.npl`` source -> validated sibling ``.py``.

Parse the source into ordered units (optional preamble + N functions), translate each
unit in order with the whole current generated ``.py`` supplied as context, and
``ast``-validate every result *before* writing anything. The validate step is an
all-or-nothing gate (:func:`render_validated`): the full ``.py`` is written only once
every unit parses, so a single un-parseable function fails the compile hard — it names
the offending function, surfaces the ``SyntaxError``, writes nothing (leaving any prior
good ``.py`` untouched), and does not retry. Validation is syntax-only — no subprocess,
no LSP.

The generated ``.py`` is also the cache — the gcc-writes-assembly model. Every block is
preceded by a marker comment holding two hashes: the unit's own pseudocode, and the
context it was translated against (the preamble plus its siblings' signatures). On
recompile a block whose two hashes still match is reused verbatim, so unchanged input
costs zero model calls and yields byte-identical output. A sibling's *body* edit changes
no signature and therefore never cascades. A ``.py`` that lost its markers to a
hand-edit or a formatter simply misses the cache, with a note on stderr.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from nplc.translator import Translator
from nplc.unit import CompileError, FunctionUnit, PreambleUnit, Unit, parse_source

# Long enough that collisions are not a practical concern, short enough to keep the
# marker comment unobtrusive in the generated file.
_HASH_LENGTH = 12

_MARKER_PATTERN = re.compile(
    r"^# nplc:(?P<label>[^:]+):(?P<own>[0-9a-f]+):(?P<context>[0-9a-f]+)$"
)


@dataclass(frozen=True)
class _CachedBlock:
    """One reusable block recovered from a previously generated ``.py``."""

    own_hash: str
    context_hash: str
    source: str


def compile_file(source_path: Path, translator: Translator) -> Path:
    """Compile a multi-unit ``.npl`` file to its sibling ``.py``.

    Args:
        source_path: Path to the ``.npl`` pseudocode file.
        translator: Adapter that turns each unit into Python source.

    Returns:
        The path of the written ``.py`` file.

    Raises:
        CompileError: If the source has no function signature, or any translated
            unit fails ``ast.parse``. Nothing is written on failure — a pre-existing
            ``.py`` is left untouched.
        OSError: If the source cannot be read or the target cannot be written.
    """
    units = parse_source(source_path.read_text())
    target = source_path.with_suffix(".py")
    previous = target.read_text() if target.exists() else ""
    python_source = render_validated(units, translator, previous)
    target.write_text(python_source)
    return target


def _unit_label(unit: Unit) -> str:
    """Name the unit, for hard-fail messages and as its cache key."""
    return unit.name if isinstance(unit, FunctionUnit) else "preamble"


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:_HASH_LENGTH]


def _own_hash(unit: Unit) -> str:
    """Hash the pseudocode the author wrote for this unit, and nothing else."""
    if isinstance(unit, FunctionUnit):
        return _digest(unit.declaration, unit.body)
    return _digest(unit.body)


def _block(label: str, own_hash: str, context_hash: str, source: str) -> str:
    """Render one marked, newline-normalised cache block.

    Normalising the trailing newlines is what makes the cache round-trip byte-exact:
    a reused block is re-emitted through this same function, so re-reading and
    re-writing an unchanged ``.py`` cannot drift.
    """
    body = source.strip("\n")
    return f"# nplc:{label}:{own_hash}:{context_hash}\n{body}\n"


def _read_cache(previous: str) -> dict[str, _CachedBlock]:
    """Recover the reusable blocks from a previously generated ``.py``.

    Anything the markers no longer describe — a hand-edited file, a formatter that
    dropped the comments, a block that stopped parsing — is simply absent from the
    result, which costs a re-translation rather than a failure. That is reported on
    stderr so an unexpectedly slow compile is explainable.

    Args:
        previous: Contents of the existing ``.py``, or ``""`` when there is none.

    Returns:
        The usable blocks, keyed by unit label.
    """
    sections: list[tuple[re.Match[str], list[str]]] = []
    for line in previous.splitlines():
        marker = _MARKER_PATTERN.match(line)
        if marker is not None:
            sections.append((marker, []))
        elif sections:
            sections[-1][1].append(line)

    blocks: dict[str, _CachedBlock] = {}
    damaged = 0
    for marker, body in sections:
        source = "\n".join(body).strip("\n") + "\n"
        try:
            ast.parse(source)
        except SyntaxError:
            damaged += 1
            continue
        blocks[marker["label"]] = _CachedBlock(marker["own"], marker["context"], source)

    if previous.strip() and not sections:
        print(
            "nplc: no cache markers in the existing .py; re-translating everything",
            file=sys.stderr,
        )
    elif damaged:
        print(
            f"nplc: cache damaged for {damaged} block(s); re-translating them",
            file=sys.stderr,
        )
    return blocks


def _context_hashes(
    units: Sequence[Unit], own_hashes: Sequence[str], signatures: Sequence[str | None]
) -> list[str]:
    """Hash, per unit, everything *outside* it that its translation depended on.

    A function is translated against the preamble (the imports and constants it may
    reference) and against its siblings' signatures (the calls it can make) — never
    against their bodies, which is exactly why a sibling's body-only edit does not
    cascade. The preamble itself depends on no other unit.
    """
    preamble_hash = next(
        (
            own_hash
            for own_hash, unit in zip(own_hashes, units, strict=True)
            if isinstance(unit, PreambleUnit)
        ),
        "",
    )
    hashes = []
    for index, unit in enumerate(units):
        if isinstance(unit, PreambleUnit):
            hashes.append(_digest())
            continue
        siblings = [
            signature
            for position, signature in enumerate(signatures)
            if signature is not None and position != index
        ]
        hashes.append(_digest(preamble_hash, *siblings))
    return hashes


def canonical_signature(unit: FunctionUnit, tree: ast.Module) -> str:
    """Return the one signature that identifies ``unit``, explicit or inferred.

    Every function has exactly one canonical signature regardless of how it was
    written: the author's when they wrote one, otherwise the signature the model chose,
    read back off the generated ``def``. Later slices key their cache on this, so it
    must not depend on which form the author used.

    Args:
        unit: The function unit that was translated.
        tree: The parsed module produced from that unit's translated Python.

    Returns:
        The ``name(params)`` text, without the ``def`` keyword or trailing colon.

    Raises:
        CompileError: If an inferred function's output does not hold exactly one
            top-level function definition. Nested definitions are not counted, so a
            closure inside the body is fine.
    """
    if unit.is_explicit:
        return unit.declaration
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if not definitions:
        raise CompileError(
            f"{unit.name}: no function was inferred from the prose declaration "
            f"{unit.declaration!r}"
        )
    if len(definitions) > 1:
        names = ", ".join(node.name for node in definitions)
        raise CompileError(
            f"{unit.name}: inferred {len(definitions)} functions ({names}), "
            "expected exactly one"
        )
    return f"{definitions[0].name}({ast.unparse(definitions[0].args)})"


def _translate_validated(unit: Unit, context: str, translator: Translator) -> str:
    """Translate one unit exactly once and reject output that is not valid Python."""
    python_source = translator.translate(unit, context)
    try:
        ast.parse(python_source)
    except SyntaxError as exc:
        raise CompileError(
            f"{_unit_label(unit)}: translated output is not valid Python: {exc}"
        ) from exc
    return python_source


def _signature(unit: Unit, python_source: str) -> str | None:
    """The unit's canonical signature, or ``None`` for the preamble."""
    if not isinstance(unit, FunctionUnit):
        return None
    return canonical_signature(unit, ast.parse(python_source))


def render_validated(
    units: Iterable[Unit], translator: Translator, previous: str = ""
) -> str:
    """Translate, cache-reuse and ``ast``-validate every unit, returning the ``.py``.

    This is the atomic gate. Units are handled in source order, each translation
    receiving the whole current generated ``.py`` as context so inter-unit references
    resolve. Each output is translated at most once (no retry) and checked with
    ``ast.parse``. The result is accumulated and returned only once *all* units pass,
    so the caller writes the file once at the end — a later bad function therefore
    never overwrites an earlier good ``.py``.

    Reuse runs in two passes, because a prose function's signature is only knowable
    once it has been translated. The first pass re-translates every unit whose own
    pseudocode changed, which settles every signature; the second then re-translates
    those whose context — the preamble or a sibling's signature — moved under them.

    Args:
        units: The units to translate, in source order.
        translator: Adapter that turns each unit into Python source.
        previous: Contents of the existing ``.py``, whose marked blocks are the cache.
            Empty for a first compile, which translates everything.

    Returns:
        The concatenated, fully validated Python source for all units, each block
        preceded by its cache marker.

    Raises:
        CompileError: If any unit's translated output fails ``ast.parse``, or an
            inferred function's output holds no single top-level ``def``.
    """
    units = list(units)
    labels = [_unit_label(unit) for unit in units]
    own_hashes = [_own_hash(unit) for unit in units]
    # A label appearing twice cannot identify a block, so those units go uncached
    # rather than silently reusing each other's Python.
    duplicates = {label for label in labels if labels.count(label) > 1}
    cache = {
        label: block
        for label, block in _read_cache(previous).items()
        if label not in duplicates
    }

    rendered: list[str] = []
    stale: list[bool] = []
    for index, unit in enumerate(units):
        cached = cache.get(labels[index])
        if cached is not None and cached.own_hash == own_hashes[index]:
            rendered.append(cached.source)
            stale.append(False)
        else:
            rendered.append(_translate_validated(unit, "\n".join(rendered), translator))
            stale.append(True)

    signatures = [
        _signature(unit, source) for unit, source in zip(units, rendered, strict=True)
    ]
    context_hashes = _context_hashes(units, own_hashes, signatures)

    for index, unit in enumerate(units):
        if stale[index] or cache[labels[index]].context_hash == context_hashes[index]:
            continue
        # ponytail: the markers keep the context each block was translated *against*,
        # not the signatures that came out of this pass. If re-translating an inferred
        # function here changes its signature, its siblings go stale and re-translate
        # on the next compile rather than looping to a fixpoint in this one.
        rendered[index] = _translate_validated(
            unit, "\n".join(rendered[:index]), translator
        )

    return "\n".join(
        _block(label, own_hash, context_hash, source)
        for label, own_hash, context_hash, source in zip(
            labels, own_hashes, context_hashes, rendered, strict=True
        )
    )
