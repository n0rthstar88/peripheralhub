"""Computer-driven lighting effects: pure time -> per-column colour frame generators."""
import colorsys
import math
from typing import Callable

RGB = tuple[int, int, int]
FrameFn = Callable[[float], list[RGB]]

OFF: RGB = (0, 0, 0)


def _byte(x: float) -> int:
    return max(0, min(255, round(x * 255)))


def _hsv(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return _byte(r), _byte(g), _byte(b)


def _breathing(cols: int, zones: dict[str, range], color: RGB, period: float = 4.0) -> FrameFn:
    def frame(t: float) -> list[RGB]:
        # Sinusoidal: full colour at t = period/4, off at t = 3*period/4.
        level = (1 + math.sin(2 * math.pi * t / period)) / 2
        px = tuple(max(0, min(255, round(c * level))) for c in color)
        return [px] * cols  # type: ignore[list-item]

    return frame


def _color_cycle(cols: int, zones: dict[str, range], period: float = 8.0) -> FrameFn:
    def frame(t: float) -> list[RGB]:
        return [_hsv(t / period)] * cols

    return frame


def _strip_gradient(cols: int, zones: dict[str, range], colors: list[RGB], period: float = 6.0) -> FrameFn:
    strip = [i for i in zones.get("strip", range(cols)) if 0 <= i < cols]
    n = len(colors)

    def sample(pos: float) -> RGB:
        pos = (pos % 1.0) * n  # closed loop through the colour list
        i = int(pos)
        k = pos - i
        a, b = colors[i % n], colors[(i + 1) % n]
        return tuple(round(a[c] + (b[c] - a[c]) * k) for c in range(3))  # type: ignore[return-value]

    def frame(t: float) -> list[RGB]:
        out = [OFF] * cols
        for j, col in enumerate(strip):
            out[col] = sample(t / period + j / len(strip))
        return out

    return frame


def _zones_static(cols: int, zones: dict[str, range], zone_colors: dict[str, RGB]) -> FrameFn:
    out = [OFF] * cols
    for name, color in zone_colors.items():
        for i in zones.get(name, range(0)):
            if 0 <= i < cols:
                out[i] = tuple(color)  # type: ignore[assignment]

    def frame(t: float) -> list[RGB]:
        return list(out)

    return frame


def _match_keyboard(cols: int, zones: dict[str, range], hue: int, sat: int) -> FrameFn:
    px = _hsv(hue / 255, sat / 255)

    def frame(t: float) -> list[RGB]:
        return [px] * cols

    return frame


HOST_EFFECTS: dict[str, Callable[..., FrameFn]] = {
    "breathing": _breathing,
    "color_cycle": _color_cycle,
    "strip_gradient": _strip_gradient,
    "zones_static": _zones_static,
    "match_keyboard": _match_keyboard,
}


def make_effect(name: str, cols: int, zones: dict[str, range], **params) -> FrameFn:
    try:
        factory = HOST_EFFECTS[name]
    except KeyError:
        raise ValueError(f"unknown host effect: {name}") from None
    return factory(cols, zones, **params)
