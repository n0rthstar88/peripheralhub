"""JSON settings store with dotted keys and atomic saves.

Keys used by the app:
  wd75.layer_names, wd75.effect_names
  wd75.rgb            {"hue", "sat", "brightness", "effect", "speed"}
  battery.wd75        {"level": int, "at": float}
  battery.low_threshold (default 20)
  mouse.dpi (int), mouse.poll (125|500|1000), mouse.brightness (0-255)
  mouse.stages        {"values": [int, ...1-5], "active": int (1-based)}
  mouse.effect        {"kind": "firmware"|"host", "name": str, "params": dict}; colours are [r, g, b] lists
    params by effect: static {"color"}; breathing {"color", "period"}; color_cycle {"period"};
    strip_gradient {"colors": [[r,g,b], [r,g,b]], "period"}; zones_static {"zone_colors": {"logo","wheel","strip"}};
    match_keyboard {"hue", "sat"} (VIA units, from wd75.rgb); spectrum/wave/off {}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_PATH = "~/.config/peripheralhub/settings.json"


class Settings:
    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = Path(path).expanduser()
        self._mtime = self.mtime()
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def reload(self) -> None:
        self._mtime = self.mtime()
        self._data = self._load()

    def set(self, key: str, value: Any) -> None:
        if self.mtime() != self._mtime:  # another process (app or service) saved since: merge onto theirs
            self.reload()
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[parts[-1]] = value
        self._save()

    def mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)
        self._mtime = self.mtime()
