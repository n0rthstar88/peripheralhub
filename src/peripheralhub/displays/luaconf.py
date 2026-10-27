from __future__ import annotations

import os
import re
import shutil

from .model import Monitor, mode_string


class UnsupportedConfig(Exception):
    """monitors.lua has a form we won't edit (e.g. a multi-line hl.monitor)."""


_CALL = re.compile(r"hl\.monitor\(\s*\{(?P<body>.*?)\}\s*\)")
_START = re.compile(r"^\s*hl\.monitor\(")
_OUTPUT = re.compile(r'output\s*=\s*"([^"]*)"')


def _field(body: str, key: str) -> str | None:
    m = re.search(rf'\b{key}\s*=\s*(?:"([^"]*)"|([-\w.]+))', body)
    return None if m is None else (m.group(1) if m.group(1) is not None else m.group(2))


def _single_line_calls(text: str):
    """Yield (line_index, match, output) for single-line hl.monitor calls."""
    for i, line in enumerate(text.splitlines(keepends=True)):
        if not _START.match(line):
            continue
        m = _CALL.search(line)
        o = _OUTPUT.search(m.group("body")) if m else None
        if m and o:
            yield i, m, o.group(1)


def _multiline_outputs(text: str) -> set[str]:
    single = {i for i, _, _ in _single_line_calls(text)}
    lines = text.splitlines()
    found: set[str] = set()
    for i, line in enumerate(lines):
        if _START.match(line) and i not in single:
            block = "\n".join(lines[i:i + 12])
            block = block.split("})", 1)[0]
            found.update(_OUTPUT.findall(block))
    return found


def parse_monitors(text: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for _, m, name in _single_line_calls(text):
        body = m.group("body")
        result[name] = {
            "mode": _field(body, "mode") or "preferred",
            "position": _field(body, "position") or "auto",
            "scale": float(_field(body, "scale") or 1),
            "transform": int(float(_field(body, "transform") or 0)),
        }
    return result


def render_monitor(m: Monitor) -> str:
    if m.disabled:
        return f'hl.monitor({{ output = "{m.name}", disabled = true }})'
    return (
        f'hl.monitor({{ output = "{m.name}", mode = "{mode_string(m)}", '
        f'position = "{m.x}x{m.y}", scale = {m.scale:g}, transform = {m.transform} }})'
    )


def update_monitors(text: str, monitors: list[Monitor]) -> str:
    by_name = {m.name: m for m in monitors}
    clash = _multiline_outputs(text) & by_name.keys()
    if clash:
        raise UnsupportedConfig(
            f"multi-line hl.monitor for {', '.join(sorted(clash))}: edit monitors.lua manually"
        )
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    for i, match, name in _single_line_calls(text):
        if name in by_name:
            line = lines[i]
            lines[i] = line[:match.start()] + render_monitor(by_name[name]) + line[match.end():]
            seen.add(name)
    out = "".join(lines)
    missing = [m for m in monitors if m.name not in seen]
    if missing:
        if out and not out.endswith("\n"):
            out += "\n"
        out += "".join(render_monitor(m) + "\n" for m in missing)
    return out


def write_monitors(path: str, monitors: list[Monitor], now: float) -> str:
    with open(path, encoding="utf-8") as f:
        old = f.read()
    new = update_monitors(old, monitors)
    backup = path + f".bak.{int(now)}"
    shutil.copy2(path, backup)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return backup
