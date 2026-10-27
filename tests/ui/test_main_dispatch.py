import importlib

import pytest

from peripheralhub.__main__ import main


def test_missing_mode_module_exits_2(capsys, monkeypatch):
    def missing(name):
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(importlib, "import_module", missing)
    assert main(["service"]) == 2
    assert "service is not available yet" in capsys.readouterr().err


def test_other_missing_module_propagates(monkeypatch):
    def boom(name):
        raise ModuleNotFoundError("No module named 'foo'", name="foo")

    monkeypatch.setattr(importlib, "import_module", boom)
    with pytest.raises(ModuleNotFoundError):
        main(["cli"])


def test_cli_dispatch_passes_args(monkeypatch, capsys):
    import peripheralhub.cli as cli
    seen = []
    monkeypatch.setattr(cli, "main", lambda: seen.append(__import__("sys").argv) or 0)
    assert main(["cli", "battery"]) == 0
    assert seen[0][1:] == ["battery"]
