"""The pseudocode function unit and the parser that produces it.

In this slice a ``.npl`` source holds a single function: an explicit
``name(params):`` signature line followed by an indented natural-language body.
Later slices add the delimiter-keyword synonym set, a preamble, and multiple
functions; this module is the seam they extend.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

_SIGNATURE = re.compile(r"^(?P<signature>\w+\s*\([^)]*\))\s*:\s*$")


class CompileError(Exception):
    """Raised when a ``.npl`` source cannot be compiled to valid Python."""


@dataclass(frozen=True)
class FunctionUnit:
    """A single pseudocode function: its signature and its prose body.

    Attributes:
        signature: The ``name(params)`` text, without the trailing colon.
        body: The natural-language description of the function, dedented.
    """

    signature: str
    body: str

    @property
    def name(self) -> str:
        """The function name parsed from the signature."""
        return self.signature.split("(", 1)[0].strip()


def parse_source(text: str) -> FunctionUnit:
    """Parse a single explicit-signature function from ``.npl`` source.

    Args:
        text: The full contents of a ``.npl`` file.

    Returns:
        The parsed :class:`FunctionUnit`.

    Raises:
        CompileError: If no explicit ``name(params):`` signature line is found.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = _SIGNATURE.match(stripped)
        if match is None:
            raise CompileError(
                "expected an explicit 'name(params):' signature, "
                f"got: {stripped!r}"
            )
        body = textwrap.dedent("\n".join(lines[index + 1 :])).strip("\n")
        return FunctionUnit(signature=match.group("signature"), body=body)
    raise CompileError("no function signature found in source")
