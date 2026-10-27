"""RGB matrix effect names keyed by VIA effect id."""
from __future__ import annotations

# Ids 1-17 accepted by the hardware (probed 2026-10-27); names pending user confirmation.
EFFECTS: dict[int, str] = {i: f"Effect {i}" for i in range(1, 18)}


def effect_name(i: int, overrides: dict[str, str] | None = None) -> str:
    if overrides and str(i) in overrides:
        return overrides[str(i)]
    return EFFECTS.get(i, f"Effect {i}")
