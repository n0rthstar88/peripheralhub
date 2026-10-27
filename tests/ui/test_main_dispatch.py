import importlib

import pytest

from peripheralhub.__main__ import main


def test_missing_mode_module_exits_2(capsys):
    assert main(["service"]) == 2
    assert "service is not available yet" in capsys.readouterr().err


def test_other_missing_module_propagates(monkeypatch):
    def boom(name):
        raise ModuleNotFoundError("No module named 'foo'", name="foo")

    monkeypatch.setattr(importlib, "import_module", boom)
    with pytest.raises(ModuleNotFoundError):
        main(["cli"])
