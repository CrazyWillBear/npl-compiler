"""Pseudocode units and the splitter that produces them.

A ``.npl`` source splits into an optional top-of-file *preamble* unit (imports and
constants prose) followed by N ordered *function* units. A function begins at a
function-definition line: an optional delimiter keyword from a configurable synonym
set (``def``, ``function``, ``func``, …) plus an explicit ``name(params):`` signature
at column zero. Bodies are indentation-delimited, so control-flow keywords
(``if``/``for``/``while``) inside a body are never mistaken for function boundaries.
"""

from __future__ import annotations

import keyword
import re
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass

# The delimiter synonyms recognised at function-definition position. Configurable
# via the ``delimiters`` argument of :func:`parse_source`; this is only the default.
DELIMITER_KEYWORDS: tuple[str, ...] = (
    "def",
    "function",
    "func",
    "fn",
    "procedure",
    "algorithm",
)


_EXPLICIT_DECLARATION = re.compile(r"\w+\s*\([^)]*\)")


class CompileError(Exception):
    """Raised when a ``.npl`` source cannot be compiled to valid Python."""


def _slug(text: str) -> str:
    """Reduce prose to a usable Python identifier."""
    slug = re.sub(r"\W+", "_", text.strip().lower()).strip("_")
    if not slug:
        return "unnamed"
    return f"_{slug}" if slug[0].isdigit() else slug


@dataclass(frozen=True)
class PreambleUnit:
    """Top-of-file prose (imports, constants) preceding the first function.

    Attributes:
        body: The natural-language preamble text, dedented.
    """

    body: str


@dataclass(frozen=True)
class FunctionUnit:
    """A single pseudocode function: its declaration line and its prose body.

    Attributes:
        declaration: The declaration text, without any delimiter keyword or trailing
            colon. Either an explicit ``name(params)`` the author wrote, or a prose
            name (``the average of some numbers``) whose real signature the model
            infers during translation.
        body: The natural-language description of the function, dedented.
    """

    declaration: str
    body: str

    @property
    def is_explicit(self) -> bool:
        """Whether the author wrote a real ``name(params)`` signature."""
        return _EXPLICIT_DECLARATION.fullmatch(self.declaration) is not None

    @property
    def name(self) -> str:
        """A Python identifier for this function, for prompts and error messages.

        For an explicit declaration this is the author's function name. For a prose
        declaration the model has not named the function yet, so the prose is slugged
        into a placeholder identifier — the *canonical* name comes from the generated
        ``def`` (see :func:`nplc.compiler.canonical_signature`).
        """
        if self.is_explicit:
            return self.declaration.split("(", 1)[0].strip()
        return _slug(self.declaration)


# A parsed unit is either the optional preamble or one of the function units.
Unit = PreambleUnit | FunctionUnit


def _function_def_pattern(delimiters: Sequence[str]) -> re.Pattern[str]:
    """Build the column-zero ``[delimiter] declaration:`` recogniser.

    A declaration is either an explicit ``name(params)`` or a prose name. The optional
    ``delim`` group matches only a configured synonym; an empty set collapses to a
    never-matching alternation so the bare ``name(params):`` form still works while no
    keyword is treated as a delimiter. The prose alternative excludes parentheses and
    colons so it can never swallow an explicit signature or a trailing clause.
    """
    keywords = "|".join(re.escape(word) for word in delimiters) or r"(?!)"
    return re.compile(
        rf"^(?:(?P<delim>{keywords})\s+)?"
        rf"(?:(?P<signature>(?P<name>\w+)\s*\([^)]*\))|(?P<prose>[^():]+?))"
        rf"\s*:\s*$"
    )


def _match_function_def(line: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    """Return the match if ``line`` opens a function, applying the control guards.

    Two things are rejected. A bare ``name(params):`` whose name is a Python keyword
    (``if``/``for``/``while`` and friends) is control flow, not a definition. And a
    prose declaration without a delimiter keyword is ordinary text — prose is only a
    function boundary when the author marked it with a synonym, otherwise every
    unindented sentence ending in a colon would open a function.
    """
    match = pattern.match(line)
    if match is None:
        return None
    if match.group("prose") is not None:
        return match if match.group("delim") is not None else None
    if match.group("delim") is None and keyword.iskeyword(match.group("name")):
        return None
    return match


def parse_source(
    text: str, delimiters: Sequence[str] = DELIMITER_KEYWORDS
) -> list[Unit]:
    """Split ``.npl`` source into an optional preamble plus ordered functions.

    Args:
        text: The full contents of a ``.npl`` file.
        delimiters: The function-delimiter synonym keywords to recognise. Defaults
            to :data:`DELIMITER_KEYWORDS`.

    Returns:
        The units in source order: an optional :class:`PreambleUnit` followed by one
        :class:`FunctionUnit` per function definition.

    Raises:
        CompileError: If the source contains no function-definition line.
    """
    pattern = _function_def_pattern(delimiters)
    lines = text.splitlines()

    definitions: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = _match_function_def(line, pattern)
        if match is not None:
            definitions.append((index, match))

    if not definitions:
        raise CompileError("no function signature found in source")

    units: list[Unit] = []
    preamble = textwrap.dedent("\n".join(lines[: definitions[0][0]])).strip("\n")
    if preamble.strip():
        units.append(PreambleUnit(body=preamble))

    for position, (start, match) in enumerate(definitions):
        is_last = position + 1 == len(definitions)
        end = len(lines) if is_last else definitions[position + 1][0]
        body = textwrap.dedent("\n".join(lines[start + 1 : end])).strip("\n")
        declaration = match.group("signature") or match.group("prose")
        units.append(FunctionUnit(declaration=declaration.strip(), body=body))

    return units
