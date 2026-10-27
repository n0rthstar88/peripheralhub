from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import replace
from typing import Callable, Literal

from .luaconf import write_monitors
from .model import Monitor, logical_size, mode_string, overlaps

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
            r = run(["hyprctl", "eval", _lua(m)], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            raise ApplyError(f"hyprctl failed: {e}") from e
        text = f"{r.stdout or ''}{r.stderr or ''}".strip()
        if r.returncode != 0 or re.search(r"error|invalid", text, re.I):
            raise ApplyError(f"{m.name}: {text or f'hyprctl exited {r.returncode}'}")


def apply_order(current: list[Monitor], target: list[Monitor]) -> list[Monitor]:
    """Steps (one hl.monitor each) that reach `target` without two monitors ever overlapping.

    Hyprland checks the layout after every hl.monitor call and warns "Monitor X overlaps" when a
    half-applied layout overlaps. Apply first whatever fits; if nothing fits (e.g. two monitors swap
    places), park one to the right of everything, then carry on.
    """
    state = {m.name: m for m in current}
    pending = list(target)
    steps: list[Monitor] = []

    def fits(m: Monitor) -> bool:
        return m.disabled or not any(
            overlaps(m, o) for o in state.values() if o.name != m.name and not o.disabled)

    for _ in range(3 * len(target) + 1):
        if not pending:
            break
        m = next((m for m in pending if fits(m)), None)
        if m is not None:
            pending.remove(m)
        else:
            enabled = [o for o in state.values() if not o.disabled]
            right = max((o.x + logical_size(o)[0] for o in enabled), default=0)
            m = replace(state.get(pending[0].name, pending[0]), x=int(right) + 1, y=0)
        steps.append(m)
        state[m.name] = m
    return steps + pending


def apply_live(ms: list[Monitor], run=subprocess.run) -> None:
    """apply_monitors in an overlap-free order worked out from the live layout."""
    try:
        current = read_monitors(run)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        current = []
    apply_monitors(apply_order(current, ms), run)


State = Literal["idle", "pending", "kept", "reverted", "revert_failed"]


class RevertController:
    """Apply a layout, then keep it (write to disk) or revert; driven by a UI timer.

    tick()/cancel() never raise: if the revert itself fails, state becomes
    "revert_failed" (see last_error) and retry_revert() can try again.
    """

    def __init__(
        self,
        previous: list[Monitor],
        apply: Callable[[list[Monitor]], None] = apply_live,
        write: Callable[[str, list[Monitor], float], str] = write_monitors,
        *,
        path: str,
        seconds: int = 15,
    ) -> None:
        self._previous, self._apply, self._write = previous, apply, write
        self._path, self._seconds = path, seconds
        self._new: list[Monitor] | None = None
        self._left = 0
        self.state: State = "idle"
        self.last_error: Exception | None = None

    def start(self, new: list[Monitor]) -> None:
        self._new, self._left, self.state, self.last_error = new, self._seconds, "pending", None
        try:
            self._apply(new)
        except Exception as e:
            if self._revert():
                if isinstance(e, ApplyError):
                    raise
                raise ApplyError(str(e)) from e
            raise ApplyError(f"apply failed ({e}) and revert failed ({self.last_error})") from e

    def keep(self) -> str:
        if self.state != "pending" or self._new is None:
            raise RuntimeError("no pending display change to keep")
        backup = self._write(self._path, self._new, time.time())
        self.state = "kept"
        return backup

    def cancel(self) -> None:
        if self.state == "pending":
            self._revert()

    def tick(self) -> int:
        if self.state == "pending":
            self._left -= 1
            if self._left <= 0:
                self._left = 0
                self._revert()
        return self._left

    def retry_revert(self) -> bool:
        if self.state == "revert_failed":
            return self._revert()
        return self.state == "reverted"

    def _revert(self) -> bool:
        try:
            self._apply(self._previous)
        except Exception as e:
            self.last_error, self.state = e, "revert_failed"
            return False
        self.last_error, self.state = None, "reverted"
        return True
