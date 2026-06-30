"""Tests for the ``nplc`` console-script entry point."""

from __future__ import annotations

import pytest

from nplc import __version__
from nplc.cli import build_parser, main


def test_version_is_exposed() -> None:
    assert __version__ == "0.1.0"


def test_parser_program_name() -> None:
    assert build_parser().prog == "nplc"


def test_main_without_source_prints_help_and_exits_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    assert "usage: nplc" in capsys.readouterr().out


def test_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_missing_source_file_reports_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["does_not_exist.npl"]) == 1
    assert "nplc:" in capsys.readouterr().err
