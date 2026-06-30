"""Tests for the ``nplc`` console-script entry point."""

from __future__ import annotations

import pytest

from nplc import __version__
from nplc.cli import NOT_IMPLEMENTED_NOTICE, build_parser, main


def test_version_is_exposed() -> None:
    assert __version__ == "0.1.0"


def test_parser_program_name() -> None:
    assert build_parser().prog == "nplc"


def test_main_exits_cleanly() -> None:
    assert main([]) == 0


def test_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_invocation_prints_not_implemented_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["example.npl"])
    assert NOT_IMPLEMENTED_NOTICE in capsys.readouterr().out
