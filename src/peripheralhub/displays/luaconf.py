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


def _split_lines(text: str) -> list[str]:
    """Split on \\n only (keeping endings), so CRLF and odd separators survive."""
    return re.findall(r"[^\n]*\n|[^\n]+", text)


def _single_line_calls(text: str):
    """Yield (line_index, match, output) for single-line hl.monitor calls."""
    for i, line in enumerate(_split_lines(text)):
        if not _START.match(line):
            continue
        m = _CALL.search(line)
        o = _OUTPUT.search(m.group("body")) if m else None
        if m and o:
            yield i, m, o.group(1)


def _multiline_outputs(text: str) -> set[str]:
    single = {i for i, _, _ in _single_line_calls(text)}
    lines = [l.rstrip("\r\n") for l in _split_lines(text)]
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


def _set_key(body: str, key: str, value: str) -> str:
    """Replace `key = <value>` in place, or append it; other keys are untouched."""
    pat = re.compile(rf'(?<![\w])({key}\s*=\s*)(?:"[^"]*"|[-\w.]+)')
    if pat.search(body):
        return pat.sub(lambda m: m.group(1) + value, body, count=1)
    core = body.rstrip()
    tail = body[len(core):]
    sep = " " if core.endswith(",") else ", "
    return f"{core}{sep}{key} = {value}{tail}"


def _edit_body(body: str, m: Monitor) -> str:
    if m.disabled:
        return _set_key(body, "disabled", "true")
    if re.search(r"(?<![\w])disabled\s*=", body):
        body = _set_key(body, "disabled", "false")
    body = _set_key(body, "mode", f'"{mode_string(m)}"')
    body = _set_key(body, "position", f'"{m.x}x{m.y}"')
    body = _set_key(body, "scale", f"{m.scale:g}")
    return _set_key(body, "transform", str(m.transform))


def update_monitors(text: str, monitors: list[Monitor]) -> str:
    by_name = {m.name: m for m in monitors}
    clash = _multiline_outputs(text) & by_name.keys()
    if clash:
        raise UnsupportedConfig(
            f"multi-line hl.monitor for {', '.join(sorted(clash))}: edit monitors.lua manually"
        )
    lines = _split_lines(text)
    seen: set[str] = set()
    for i, match, name in _single_line_calls(text):
        if name in by_name:
            line = lines[i]
            s, e = match.span("body")
            lines[i] = line[:s] + _edit_body(match.group("body"), by_name[name]) + line[e:]
            seen.add(name)
    out = "".join(lines)
    missing = [m for m in monitors if m.name not in seen]
    if missing:
        nl = "\r\n" if "\r\n" in text else "\n"
        if out and not out.endswith("\n"):
            out += nl
        out += "".join(render_monitor(m) + nl for m in missing)
    return out


def write_monitors(path: str, monitors: list[Monitor], now: float) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        old = f.read()
    new = update_monitors(old, monitors)
    backup = path + f".bak.{int(now)}"
    n = 0
    while os.path.exists(backup):
        n += 1
        backup = path + f".bak.{int(now)}.{n}"
    shutil.copy2(path, backup)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(tmp, path)
    return backup
