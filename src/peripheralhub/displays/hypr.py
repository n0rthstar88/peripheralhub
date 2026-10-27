from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Callable

from .luaconf import write_monitors
from .model import Monitor, mode_string

# Live apply: `hyprctl keyword monitor ...` fails with the Lua config on Hyprland 0.56.2;
# `hyprctl eval 'hl.monitor({...})'` works. It prints "ok" on success, and exits 7 with
# "error: ..." on a bad call (verified against a fake output name).


class ApplyError(Exception):
    """hyprctl rejected or failed to apply a monitor change."""


def _clean_mode(s: str) -> str:
    """'1920x1080@144.00Hz' -> '1920x1080@144' (the form mode_string produces)."""
    s = s.removesuffix("Hz")
    return re.sub(r"(@\d+)\.00$", r"\1", s)


def read_monitors(run=subprocess.run) -> list[Monitor]:
    out = run(["hyprctl", "monitors", "all", "-j"], capture_output=True, text=True, check=True).stdout
    result = []
    for d in json.loads(out):
        modes = list(dict.fromkeys(_clean_mode(m) for m in d.get("availableModes", [])))
        result.append(Monitor(
            name=d["name"], description=d.get("description", ""),
            width=d["width"], height=d["height"], refresh=d["refreshRate"],
            x=d["x"], y=d["y"], scale=d["scale"], transform=d["transform"],
            modes=modes, disabled=bool(d.get("disabled", False)),
        ))
    return result


def _lua(m: Monitor) -> str:
    if m.disabled:
        return f'hl.monitor({{ output = "{m.name}", disabled = true }})'
    return (
        f'hl.monitor({{ output = "{m.name}", mode = "{mode_string(m)}", '
        f'position = "{m.x}x{m.y}", scale = {m.scale:g}, transform = {m.transform} }})'
    )


def apply_monitors(ms: list[Monitor], run=subprocess.run) -> None:
    for m in ms:
        try:
            r = run(["hyprctl", "eval", _lua(m)], capture_output=True, text=True)
        except OSError as e:
            raise ApplyError(f"hyprctl failed: {e}") from e
        text = f"{r.stdout or ''}{r.stderr or ''}".strip()
        if r.returncode != 0 or re.search(r"error|invalid", text, re.I):
            raise ApplyError(f"{m.name}: {text or f'hyprctl exited {r.returncode}'}")


class RevertController:
    """Apply a layout, then keep it (write to disk) or revert; driven by a UI timer."""

    def __init__(
        self,
        previous: list[Monitor],
        apply: Callable[[list[Monitor]], None] = apply_monitors,
        write: Callable[[str, list[Monitor], float], str] = write_monitors,
        path: str = "",
        seconds: int = 15,
    ) -> None:
        self._previous, self._apply, self._write = previous, apply, write
        self._path, self._seconds = path, seconds
        self._new: list[Monitor] | None = None
        self._left = 0
        self._active = False

    def start(self, new: list[Monitor]) -> None:
        self._new, self._left, self._active = new, self._seconds, True
        try:
            self._apply(new)
        except ApplyError:
            self._revert()
            raise

    def keep(self) -> str:
        if not self._active or self._new is None:
            raise RuntimeError("no pending display change to keep")
        self._active = False
        return self._write(self._path, self._new, time.time())

    def cancel(self) -> None:
        self._revert()

    def tick(self) -> int:
        if self._active:
            self._left -= 1
            if self._left <= 0:
                self._left = 0
                self._revert()
        return self._left

    def _revert(self) -> None:
        if self._active:
            self._active = False
            self._apply(self._previous)
