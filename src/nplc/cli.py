"""Command-line entry point for the ``nplc`` compiler.

The real compiler is not implemented yet; this module provides the console-script
seam so later slices have a stable place to hang argument parsing and dispatch.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

NOT_IMPLEMENTED_NOTICE = "nplc: compiler not implemented yet"


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
        help="pseudocode source file to compile (not implemented yet)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the compiler.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        The process exit code. Compilation is not implemented yet, so any
        invocation prints a placeholder notice and exits cleanly with ``0``.
    """
    build_parser().parse_args(argv)
    print(NOT_IMPLEMENTED_NOTICE)
    return 0
