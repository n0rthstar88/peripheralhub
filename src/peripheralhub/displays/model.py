from __future__ import annotations

from dataclasses import dataclass, replace

TRANSFORMS: dict[int, str] = {
    0: "Normal", 1: "90°", 2: "180°", 3: "270°",
    4: "Flipped", 5: "Flipped 90°", 6: "Flipped 180°", 7: "Flipped 270°",
}
SCALES = (1.0, 1.25, 1.5, 1.6, 1.75, 2.0)


@dataclass
class Monitor:
    name: str
    description: str
    width: int
    height: int
    refresh: float
    x: int
    y: int
    scale: float
    transform: int
    modes: list[str]
    disabled: bool = False


def logical_size(m: Monitor) -> tuple[float, float]:
    w, h = m.width / m.scale, m.height / m.scale
    return (h, w) if m.transform % 2 == 1 else (w, h)


def mode_string(m: Monitor) -> str:
    r = round(m.refresh)
    refresh = str(int(r)) if abs(m.refresh - r) <= 0.05 else f"{m.refresh:.2f}"
    return f"{m.width}x{m.height}@{refresh}"


def _rect(m: Monitor) -> tuple[float, float, float, float]:
    w, h = logical_size(m)
    return m.x, m.y, m.x + w, m.y + h


def snap_position(
    moving: Monitor, others: list[Monitor], x: float, y: float, threshold: float = 40
) -> tuple[int, int]:
    """Snap a dragged monitor's top-left to the edges of the other monitors."""
    w, h = logical_size(moving)
    xs: list[float] = []
    ys: list[float] = []
    for o in others:
        if o.disabled or o.name == moving.name:
            continue
        ox0, oy0, ox1, oy1 = _rect(o)
        xs += [ox1, ox0 - w, ox0, ox1 - w]
        ys += [oy1, oy0 - h, oy0, oy1 - h]

    def nearest(value: float, candidates: list[float]) -> float:
        best = min(candidates, key=lambda c: abs(c - value), default=None)
        return best if best is not None and abs(best - value) <= threshold else value

    return round(nearest(x, xs)), round(nearest(y, ys))


def validate_layout(ms: list[Monitor]) -> list[str]:
    enabled = [m for m in ms if not m.disabled]
    if not enabled:
        return ["All monitors are disabled: at least one must stay on"]
    errors: list[str] = []
    touching = {m.name: False for m in enabled}
    for i, a in enumerate(enabled):
        ax0, ay0, ax1, ay1 = _rect(a)
        for b in enabled[i + 1:]:
            bx0, by0, bx1, by1 = _rect(b)
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 0 and oy > 0:
                errors.append(f"{a.name} and {b.name} overlap")
            elif (ox == 0 and oy > 0) or (oy == 0 and ox > 0):
                touching[a.name] = touching[b.name] = True
    if len(enabled) > 1:
        errors += [f"{n} is not touching any other monitor" for n, t in touching.items() if not t]
    return errors


def normalize(ms: list[Monitor]) -> list[Monitor]:
    enabled = [m for m in ms if not m.disabled] or ms
    if not enabled:
        return []
    dx, dy = min(m.x for m in enabled), min(m.y for m in enabled)
    return [replace(m, x=m.x - dx, y=m.y - dy) for m in ms]
