"""Command-line entry point for the ``nplc`` compiler.

``nplc FILE.npl`` parses a single explicit-signature function, translates it via
the configured :class:`~nplc.translator.Translator` (the deterministic
:class:`~nplc.translator.StubTranslator` for now), validates the result, and
writes the sibling ``FILE.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from nplc.compiler import compile_file
from nplc.translator import StubTranslator
from nplc.unit import CompileError


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``nplc`` command."""
    parser = argparse.ArgumentParser(
        prog="nplc",
        description="Compile natural-language pseudocode (.npl) into Python (.py).",
    )
    parser.add_argument(
        "source",
        nargs="?",
        metavar="FILE.npl",
        help="pseudocode source file to compile",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the compiler.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        The process exit code: ``0`` on success (or when no source is given and
        help is printed), ``1`` when compilation fails.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.source is None:
        parser.print_help()
        return 0
    try:
        target = compile_file(Path(args.source), StubTranslator())
    except (CompileError, OSError) as exc:
        print(f"nplc: {exc}", file=sys.stderr)
        return 1
    print(f"nplc: wrote {target}")
    return 0
