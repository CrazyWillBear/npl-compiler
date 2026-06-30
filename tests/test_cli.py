"""Tests for the ``nplc`` console-script entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from nplc import __version__
from nplc.cli import build_parser, main
from nplc.unit import Unit


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


def test_unparseable_output_exits_nonzero_and_names_function(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stub that emits un-parseable Python makes the CLI hard-fail by name."""

    class BrokenStub:
        def translate(self, unit: Unit, context: str) -> str:
            return "def (broken:::"

    monkeypatch.setattr("nplc.cli.StubTranslator", BrokenStub)
    source = tmp_path / "broken.npl"
    source.write_text("add(a, b):\n    return the sum\n")

    exit_code = main([str(source)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "nplc:" in err
    assert "add" in err  # names the offending function
    assert not (tmp_path / "broken.py").exists()
